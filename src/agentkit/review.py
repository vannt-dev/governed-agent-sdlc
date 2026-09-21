from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, BinaryIO, Protocol

VALID_SEVERITIES = {"critical", "high", "medium", "low", "info"}
VALID_CATEGORIES = {
    "security",
    "correctness",
    "performance",
    "maintainability",
    "testing",
    "architecture",
    "other",
}

SEVERITY_MAP: dict[str, str] = {
    "critical": "critical",
    "blocker": "critical",
    "fatal": "critical",
    "high": "high",
    "error": "high",
    "major": "high",
    "medium": "medium",
    "warn": "medium",
    "warning": "medium",
    "moderate": "medium",
    "low": "low",
    "minor": "low",
    "style": "low",
    "info": "info",
    "informational": "info",
    "note": "info",
    "suggestion": "info",
}

CATEGORY_MAP: dict[str, str] = {
    "security": "security",
    "vuln": "security",
    "vulnerability": "security",
    "cwe": "security",
    "auth": "security",
    "injection": "security",
    "owasp": "security",
    "correctness": "correctness",
    "bug": "correctness",
    "error": "correctness",
    "fault": "correctness",
    "logic": "correctness",
    "performance": "performance",
    "perf": "performance",
    "memory": "performance",
    "speed": "performance",
    "maintainability": "maintainability",
    "readability": "maintainability",
    "complexity": "maintainability",
    "style": "maintainability",
    "documentation": "maintainability",
    "testing": "testing",
    "test": "testing",
    "coverage": "testing",
    "architecture": "architecture",
    "design": "architecture",
}

# Status values observed from `ocr review --format json` (internal/session terminal states plus the
# older warning-derived ones). "complete" is what a successful run reports.
COMPLETE_STATUSES = frozenset({"complete", "success", "completed_with_warnings"})
INCOMPLETE_STATUSES = frozenset({"partial", "completed_with_errors"})
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
STDERR_EVIDENCE_CHARS = 2048
DEFAULT_OCR_BINARY = "ocr"

_ENV_ALLOWLIST = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
}
_ENV_PREFIXES = ("OCR_", "OPENCODEREVIEW_", "ANTHROPIC_", "OPENAI_")

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE), "Bearer [REDACTED]"),
    (
        re.compile(
            r"""((?:api[_-]?key|secret|token|password)["']?\s*[:=]\s*["']?)[^\s"',}]{6,}""",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
)


def redact_secrets(text: str) -> str:
    """Review output is untrusted and can echo credentials from source; redact before storing."""
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_evidence(text: str) -> str:
    """Keep JSON valid when a secret appears inside an escaped string value."""

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return redact_secrets(value)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {
                key: "[REDACTED]"
                if isinstance(item, str)
                and re.search(r"(?:api[_-]?key|secret|token|password)$", key, re.IGNORECASE)
                else clean(item)
                for key, item in value.items()
            }
        return value

    try:
        return json.dumps(clean(json.loads(text)), indent=2)
    except json.JSONDecodeError:
        return redact_secrets(text)


class ReviewProviderError(RuntimeError):
    """The reviewer itself failed (missing, timed out, malformed output). This is not a finding."""

    def __init__(
        self, kind: str, message: str, findings: tuple[NormalizedFinding, ...] = ()
    ) -> None:
        message = redact_secrets(message)
        super().__init__(message)
        self.kind = kind
        self.message = message
        # Findings reported before a run turned out to be incomplete are kept as evidence.
        self.findings = findings

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "message": self.message}


@dataclass(frozen=True)
class NormalizedFinding:
    id: str
    source: str
    severity: str
    category: str
    file: str
    message: str
    line: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "severity": self.severity,
            "category": self.category,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ReviewContext:
    run_id: str
    repository_root: Path
    files: tuple[str, ...] = field(default_factory=tuple)
    requirement: str | None = None
    background_file: str | None = None
    from_ref: str | None = None
    to_ref: str | None = None
    commit: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    provider: str
    passed: bool
    findings: tuple[NormalizedFinding, ...]
    raw_evidence: str | None = None
    nothing_to_review: bool = False
    command: tuple[str, ...] = ()
    duration_ms: int | None = None
    tool_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
            "rawEvidence": self.raw_evidence,
            "nothingToReview": self.nothing_to_review,
        }


class ReviewProvider(Protocol):
    def review(self, context: ReviewContext) -> ReviewResult:
        """Execute a review and return normalized findings, or raise ReviewProviderError."""
        ...


class FindingNormalizer:
    @staticmethod
    def normalize_severity(raw: str | None) -> str:
        if not raw:
            return "info"
        normalized = raw.strip().lower()
        return SEVERITY_MAP.get(normalized, "info")

    @staticmethod
    def normalize_category(raw: str | None) -> str:
        if not raw:
            return "other"
        normalized = raw.strip().lower()
        return CATEGORY_MAP.get(normalized, "other")

    @classmethod
    def normalize(
        cls,
        raw_finding: dict[str, Any],
        source: str = "review",
        fallback_id: str | None = None,
    ) -> NormalizedFinding:
        finding_id = str(raw_finding.get("id") or fallback_id or "finding-0")
        file_path = str(raw_finding.get("file") or raw_finding.get("path") or "unknown")
        line_val = raw_finding.get("line")
        line = (
            int(line_val)
            if isinstance(line_val, (int, str)) and str(line_val).isdigit() and int(line_val) > 0
            else None
        )
        raw_severity = raw_finding.get("severity") or raw_finding.get("level")
        severity = cls.normalize_severity(str(raw_severity) if raw_severity else None)
        raw_category = raw_finding.get("category") or raw_finding.get("rule_type")
        category = cls.normalize_category(str(raw_category) if raw_category else None)
        message = str(raw_finding.get("message") or raw_finding.get("description") or "").strip()
        metadata = raw_finding.get("metadata")
        clean_metadata = metadata if isinstance(metadata, dict) else {}

        return NormalizedFinding(
            id=finding_id,
            source=source,
            severity=severity,
            category=category,
            file=file_path,
            line=line,
            message=message,
            metadata=clean_metadata,
        )


class MockReviewProvider:
    def __init__(
        self,
        name: str = "mock",
        findings: list[NormalizedFinding] | None = None,
        passed: bool | None = None,
    ) -> None:
        self.name = name
        self.configured_findings = tuple(findings or [])
        self._explicit_passed = passed

    def review(self, context: ReviewContext) -> ReviewResult:
        passed = (
            self._explicit_passed
            if self._explicit_passed is not None
            else len(self.configured_findings) == 0
        )
        return ReviewResult(
            provider=self.name,
            passed=passed,
            findings=self.configured_findings,
            raw_evidence=json.dumps([f.to_dict() for f in self.configured_findings], indent=2),
        )


def parse_ocr_output(
    stdout: str, source: str = "open-code-review"
) -> tuple[list[NormalizedFinding], bool]:
    """Parse `ocr review --format json`: {status, comments:[{path, content, start_line, ...}]}.

    Returns (findings, nothing_to_review). Every field is validated because the output is untrusted.
    """
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ReviewProviderError("parse", "OpenCodeReview output is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ReviewProviderError("schema", "OpenCodeReview output must be a JSON object")

    status = parsed.get("status")
    message = parsed.get("message") if isinstance(parsed.get("message"), str) else "no message"
    if status == "failed":
        raise ReviewProviderError("exit", f'OpenCodeReview reported status "failed": {message}')
    if status == "skipped":
        return [], True
    if not isinstance(status, str) or (
        status not in COMPLETE_STATUSES and status not in INCOMPLETE_STATUSES
    ):
        raise ReviewProviderError("schema", f"Unexpected OpenCodeReview status: {status!r}")
    comments = parsed.get("comments")
    if comments is None:
        comments = []  # Go marshals an empty slice as null
    if not isinstance(comments, list):
        raise ReviewProviderError("schema", "OpenCodeReview comments must be an array or null")

    findings: list[NormalizedFinding] = []
    for index, item in enumerate(comments):
        if not isinstance(item, dict):
            raise ReviewProviderError("schema", f"comments[{index}] must be an object")
        path = item.get("path")
        content = item.get("content")
        if not isinstance(path, str) or not path or not isinstance(content, str):
            raise ReviewProviderError("schema", f"comments[{index}] needs string path and content")
        start = item.get("start_line")
        line = (
            start if isinstance(start, int) and not isinstance(start, bool) and start > 0 else None
        )
        raw_severity = item.get("severity")
        # A missing or unknown severity stays visible (medium) rather than silently becoming info.
        severity = (
            SEVERITY_MAP.get(raw_severity.strip().lower(), "medium")
            if isinstance(raw_severity, str)
            else "medium"
        )
        end = item.get("end_line")
        findings.append(
            NormalizedFinding(
                id=f"ocr-{index + 1}",
                source=source,
                severity=severity,
                category=FindingNormalizer.normalize_category(
                    item.get("category") if isinstance(item.get("category"), str) else None
                ),
                file=path.replace("\\", "/"),
                line=line,
                message=redact_secrets(content.strip()),
                metadata={"end_line": end} if type(end) is int and end > 0 else {},
            )
        )
    if status in INCOMPLETE_STATUSES:
        # Some files were not reviewed (item failures or the token budget). Reporting the reviewed
        # part as a clean review would hide the gap, so this is a provider error with findings.
        raise ReviewProviderError(
            "incomplete",
            f'OpenCodeReview finished with status "{status}": {message}',
            tuple(findings),
        )
    return findings, False


def filter_env(env: dict[str, str] | None = None, extra: tuple[str, ...] = ()) -> dict[str, str]:
    """Give the reviewer only what it needs; other tokens and CI secrets stay out."""
    source = os.environ if env is None else env
    return {
        key: value
        for key, value in source.items()
        if key.upper() in _ENV_ALLOWLIST or key in extra or key.startswith(_ENV_PREFIXES)
    }


def _write_new(path: Path, text: str) -> None:
    """Evidence is append-only: an existing file is an error, never an overwrite."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(redact_evidence(text))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "provider"


def write_review_evidence(
    output_dir: Path,
    result: ReviewResult,
    governance_decision: dict[str, Any] | Any,
    provider_meta: dict[str, Any] | None = None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    findings_path = output_dir / "findings.json"
    _write_new(findings_path, json.dumps([f.to_dict() for f in result.findings], indent=2))

    decision_data = (
        governance_decision.to_dict()
        if hasattr(governance_decision, "to_dict")
        else governance_decision
    )
    policy_path = output_dir / "policy-result.json"
    _write_new(policy_path, json.dumps(decision_data, indent=2))

    written = {"findings": findings_path, "policy": policy_path}
    if result.raw_evidence:
        # Raw provider output is kept beside, never merged into, the normalized findings.
        raw_path = output_dir / f"{_safe_name(result.provider)}-raw.json"
        _write_new(raw_path, result.raw_evidence)
        written["raw"] = raw_path

    meta = {
        "provider": result.provider,
        "toolVersion": result.tool_version,
        "command": [redact_secrets(part) for part in result.command],
        "durationMs": result.duration_ms,
        "nothingToReview": result.nothing_to_review,
        "recordedAt": datetime.now(UTC).isoformat(),
        **(provider_meta or {}),
    }
    provider_path = output_dir / "provider.json"
    _write_new(provider_path, json.dumps(meta, indent=2))
    written["provider"] = provider_path
    return written


def write_provider_error_evidence(
    output_dir: Path, provider: str, error: ReviewProviderError, decision: Any
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_new(output_dir / "policy-result.json", json.dumps(decision.to_dict(), indent=2))
    if error.findings:
        _write_new(
            output_dir / "findings.json",
            json.dumps([f.to_dict() for f in error.findings], indent=2),
        )
    path = output_dir / "provider-error.json"
    _write_new(
        path,
        json.dumps(
            {
                "provider": provider,
                "kind": error.kind,
                "message": redact_secrets(error.message),
                "recordedAt": datetime.now(UTC).isoformat(),
            },
            indent=2,
        ),
    )
    return path


def validate_review_evidence(evidence_dir: Path) -> list[str]:
    """Return schema problems for one review attempt directory (empty list means valid)."""
    errors: list[str] = []
    if (evidence_dir / "in-progress").exists():
        return [
            "Review attempt is running or interrupted; use review recover after its writer exits"
        ]
    if (evidence_dir / "recovery.json").is_file():
        return []
    policy_file = evidence_dir / "policy-result.json"
    if not policy_file.is_file():
        return [f"{policy_file.name} is missing"]
    try:
        policy = json.loads(policy_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"policy-result.json is not valid JSON: {exc}"]
    if not isinstance(policy, dict) or not isinstance(policy.get("decision"), str):
        errors.append("policy-result.json needs a string 'decision'")
    if (evidence_dir / "provider-error.json").is_file():
        return errors

    findings_file = evidence_dir / "findings.json"
    if not findings_file.is_file():
        return [*errors, "findings.json is missing"]
    try:
        findings = json.loads(findings_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [*errors, f"findings.json is not valid JSON: {exc}"]
    if not isinstance(findings, list):
        return [*errors, "findings.json must be an array"]
    seen: set[str] = set()
    for index, item in enumerate(findings):
        if not isinstance(item, dict):
            errors.append(f"findings[{index}] must be an object")
            continue
        errors.extend(f"findings[{index}].{problem}" for problem in finding_contract_errors(item))
        for key in ("id", "source", "file", "message"):
            if not isinstance(item.get(key), str):
                errors.append(f"findings[{index}].{key} must be a string")
        if not isinstance(item.get("severity"), str) or item["severity"] not in VALID_SEVERITIES:
            errors.append(f"findings[{index}].severity is not a valid severity")
        if not isinstance(item.get("category"), str) or item["category"] not in VALID_CATEGORIES:
            errors.append(f"findings[{index}].category is not a valid category")
        line = item.get("line")
        if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
            errors.append(f"findings[{index}].line must be a positive integer or null")
        finding_id = item.get("id")
        if isinstance(finding_id, str):
            if finding_id in seen:
                errors.append(f"duplicate finding id {finding_id!r}")
            seen.add(finding_id)
    return errors


@cache
def _finding_contract() -> dict[str, Any]:
    from agentkit.generator import package_root

    path = package_root() / "core/schemas/review-finding.schema.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def finding_contract_errors(item: dict[str, Any]) -> list[str]:
    schema = _finding_contract()
    properties = schema["properties"]
    problems = [f"{key} is required" for key in schema["required"] if key not in item]
    problems += [f"{key} is not allowed" for key in item if key not in properties]
    for key in ("id", "source", "file", "message"):
        if not isinstance(item.get(key), str) or len(item[key]) < properties[key].get(
            "minLength", 0
        ):
            problems.append(f"{key} must be a valid string")
    for key in ("severity", "category"):
        if item.get(key) not in properties[key]["enum"]:
            problems.append(f"{key} is outside the contract enum")
    if item.get("line") is not None and (type(item["line"]) is not int or item["line"] < 1):
        problems.append("line must be a positive integer or null")
    if not isinstance(item.get("metadata"), dict):
        problems.append("metadata must be an object")
    return problems


class OpenCodeReviewProvider:
    """Adapter for the `ocr` CLI (npm: @alibaba-group/open-code-review).

    The executable comes from the constructor, OPEN_CODE_REVIEW_BIN or PATH only. Not read from
    the project manifest, so repository content cannot choose which binary runs.
    """

    def __init__(
        self,
        executable: str | None = None,
        timeout_seconds: int = 180,
        pass_env: tuple[str, ...] = (),
    ) -> None:
        self.executable = (
            executable
            or os.environ.get("OPEN_CODE_REVIEW_BIN")
            or shutil.which(DEFAULT_OCR_BINARY)
            or DEFAULT_OCR_BINARY
        )
        self.timeout_seconds = timeout_seconds
        self.pass_env = pass_env

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None or Path(self.executable).is_file()

    def _run(
        self, args: list[str], timeout: int, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        try:
            return run_bounded(
                [self.executable, *args],
                timeout=timeout,
                cwd=str(cwd) if cwd else None,
                env=filter_env(extra=self.pass_env),
            )
        except subprocess.TimeoutExpired as exc:
            raise ReviewProviderError(
                "timeout", f"OpenCodeReview exceeded its {timeout}s timeout"
            ) from exc
        except OSError as exc:
            raise ReviewProviderError(
                "exit", redact_secrets(f"Failed to run OpenCodeReview: {exc}")
            ) from exc

    def version(self) -> str | None:
        try:
            proc = self._run(["--version"], 15)
        except ReviewProviderError:
            return None
        return proc.stdout.strip() or None if proc.returncode == 0 else None

    @staticmethod
    def _diff_args(context: ReviewContext) -> list[str]:
        args: list[str] = []
        if context.commit:
            args += ["--commit", context.commit]
        if context.from_ref:
            args += ["--from", context.from_ref]
        if context.to_ref:
            args += ["--to", context.to_ref]
        return args

    def _checked_stdout(self, proc: subprocess.CompletedProcess[str]) -> str:
        stdout = proc.stdout or ""
        if len(stdout.encode("utf-8", errors="replace")) > MAX_OUTPUT_BYTES:
            raise ReviewProviderError(
                "output-too-large", f"OpenCodeReview output exceeded {MAX_OUTPUT_BYTES} bytes"
            )
        if proc.returncode != 0:
            tail = redact_secrets(proc.stderr or "")[-STDERR_EVIDENCE_CHARS:]
            raise ReviewProviderError(
                "exit",
                f"OpenCodeReview exited with code {proc.returncode}"
                + (f": {tail}" if tail else ""),
            )
        return stdout

    def review(self, context: ReviewContext) -> ReviewResult:
        if not self.is_available():
            raise ReviewProviderError(
                "unavailable",
                f"OpenCodeReview executable '{self.executable}' not found on PATH or disk.",
            )

        args = [
            "review",
            "--repo",
            str(context.repository_root),
            "--format",
            "json",
            *self._diff_args(context),
        ]
        if context.background_file:
            args += ["--background-file", context.background_file]
        command = (self.executable, *args)

        started = time.monotonic()
        proc = self._run(args, self.timeout_seconds, cwd=context.repository_root)
        stdout = self._checked_stdout(proc)
        findings, nothing = parse_ocr_output(stdout)
        return ReviewResult(
            provider="open-code-review",
            passed=len(findings) == 0 and not nothing,
            findings=tuple(findings),
            raw_evidence=redact_evidence(stdout.strip()),
            nothing_to_review=nothing,
            command=command,
            duration_ms=int((time.monotonic() - started) * 1000),
            tool_version=self.version(),
        )

    def delegate_preview(self, context: ReviewContext) -> dict[str, Any]:
        """Delegation mode: OCR selects files deterministically; the host agent reasons."""
        if not self.is_available():
            raise ReviewProviderError(
                "unavailable",
                f"OpenCodeReview executable '{self.executable}' not found on PATH or disk.",
            )
        args = ["delegate", "preview", "--repo", str(context.repository_root), "--format", "json"]
        args += self._diff_args(context)
        if context.background_file:
            args += ["--background-file", context.background_file]
        stdout = self._checked_stdout(
            self._run(args, self.timeout_seconds, cwd=context.repository_root)
        )
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise ReviewProviderError(
                "parse", "OpenCodeReview delegate preview is not valid JSON"
            ) from exc
        if not isinstance(parsed, dict) or "reviewable_files" not in parsed:
            raise ReviewProviderError(
                "schema", "OpenCodeReview delegate preview is missing reviewable_files"
            )
        for field_name in ("reviewable_files", "excluded_files"):
            items = parsed.get(field_name)
            if items is None:
                parsed[field_name] = []
                continue
            if not isinstance(items, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("path"), str)
                for item in items
            ):
                raise ReviewProviderError("schema", f"Invalid delegate preview {field_name}")
        return parsed

    def delegate_rules(self, context: ReviewContext, paths: list[str]) -> dict[str, Any]:
        if not paths:
            return {"schema_version": "1", "groups": []}
        args = ["delegate", "rule", "--repo", str(context.repository_root), "--format", "json"]
        args += self._diff_args(context)
        if context.background_file:
            args += ["--background-file", context.background_file]
        args += ["--", *paths]
        stdout = self._checked_stdout(
            self._run(args, self.timeout_seconds, context.repository_root)
        )
        try:
            doc = json.loads(stdout)
        except ValueError as exc:
            raise ReviewProviderError("parse", "Delegate rules are not JSON") from exc
        if (
            not isinstance(doc, dict)
            or doc.get("schema_version") != "1"
            or not isinstance(doc.get("groups"), list)
        ):
            raise ReviewProviderError("schema", "Unsupported delegate rule schema")
        covered: set[str] = set()
        for group in doc["groups"]:
            if (
                not isinstance(group, dict)
                or type(group.get("group_id")) is not int
                or group["group_id"] < 1
                or any(not isinstance(group.get(key), str) for key in ("source", "pattern", "rule"))
                or not isinstance(group.get("files"), list)
                or any(not isinstance(path, str) or path not in paths for path in group["files"])
            ):
                raise ReviewProviderError("schema", "Invalid delegate rule group")
            covered.update(group["files"])
        if covered != set(paths):
            raise ReviewProviderError("schema", "Delegate rules do not cover every requested file")
        return doc


def run_bounded(
    command: list[str],
    *,
    timeout: int,
    cwd: str | None,
    env: dict[str, str],
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Drain both pipes concurrently with bounded memory and no unredacted temporary files."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
    )
    buffers = [bytearray(), bytearray()]
    oversized, read_failed = threading.Event(), threading.Event()

    def drain(stream: BinaryIO, buffer: bytearray) -> None:
        try:
            while chunk := stream.read(65536):
                remaining = MAX_OUTPUT_BYTES - len(buffer)
                buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    oversized.set()
                    process.kill()
                    break
        except OSError:
            read_failed.set()
            if process.poll() is None:
                process.kill()
        finally:
            stream.close()

    readers = [
        threading.Thread(target=drain, args=(stream, buffer), daemon=True)
        for stream, buffer in zip((process.stdout, process.stderr), buffers, strict=True)
    ]
    for reader in readers:
        reader.start()

    def feed() -> None:
        if process.stdin is not None:
            try:
                process.stdin.write((input_text or "").encode("utf-8"))
                process.stdin.close()
            except (OSError, ValueError):
                pass

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()
    try:
        process.wait(timeout=timeout)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        writer.join(timeout=1)
        for reader in readers:
            reader.join(timeout=1)
    if oversized.is_set():
        raise ReviewProviderError(
            "output-too-large", f"OpenCodeReview output exceeded {MAX_OUTPUT_BYTES} bytes"
        )
    if read_failed.is_set() or any(reader.is_alive() for reader in readers):
        raise ReviewProviderError("exit", "OpenCodeReview output could not be read completely")
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        buffers[0].decode("utf-8", errors="replace"),
        buffers[1].decode("utf-8", errors="replace"),
    )
