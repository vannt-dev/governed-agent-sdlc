from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

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
    "testing": "testing",
    "test": "testing",
    "coverage": "testing",
    "architecture": "architecture",
    "design": "architecture",
}


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


@dataclass(frozen=True)
class ReviewResult:
    provider: str
    passed: bool
    findings: tuple[NormalizedFinding, ...]
    raw_evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
            "rawEvidence": self.raw_evidence,
        }


class ReviewProvider(Protocol):
    def review(self, context: ReviewContext) -> ReviewResult:
        """Execute a review and return structured review findings."""
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
        line = int(line_val) if isinstance(line_val, (int, str)) and str(line_val).isdigit() else None
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
        passed = self._explicit_passed if self._explicit_passed is not None else len(self.configured_findings) == 0
        return ReviewResult(
            provider=self.name,
            passed=passed,
            findings=self.configured_findings,
            raw_evidence=json.dumps([f.to_dict() for f in self.configured_findings], indent=2),
        )


def write_review_evidence(
    output_dir: Path,
    result: ReviewResult,
    governance_decision: dict[str, Any] | Any,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    findings_path = output_dir / "findings.json"
    findings_path.write_text(
        json.dumps([f.to_dict() for f in result.findings], indent=2), encoding="utf-8"
    )

    decision_data = (
        governance_decision.to_dict()
        if hasattr(governance_decision, "to_dict")
        else governance_decision
    )
    policy_path = output_dir / "policy-result.json"
    policy_path.write_text(json.dumps(decision_data, indent=2), encoding="utf-8")

    if result.raw_evidence:
        raw_path = output_dir / f"{result.provider}-raw.json"
        raw_path.write_text(result.raw_evidence, encoding="utf-8")

    return {"findings": findings_path, "policy": policy_path}


class OpenCodeReviewProvider:
    def __init__(
        self,
        executable: str | None = None,
        timeout_seconds: int = 180,
    ) -> None:
        import os
        import shutil

        self.executable = (
            executable
            or os.environ.get("OPEN_CODE_REVIEW_BIN")
            or shutil.which("open-code-review")
            or shutil.which("ocr")
            or "open-code-review"
        )
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        import shutil

        return shutil.which(self.executable) is not None or Path(self.executable).is_file()

    def review(self, context: ReviewContext) -> ReviewResult:
        import subprocess

        if not self.is_available():
            raise FileNotFoundError(
                f"OpenCodeReview executable '{self.executable}' not found on PATH or disk."
            )

        cmd = [self.executable, "review", "--repo", str(context.repository_root), "--format", "json"]
        if context.files:
            cmd.extend(["--files", *context.files])
        if context.background_file:
            cmd.extend(["--context", context.background_file])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ReviewResult(
                provider="open-code-review",
                passed=False,
                findings=(
                    NormalizedFinding(
                        id="ocr-timeout",
                        source="open-code-review",
                        severity="high",
                        category="other",
                        file=".",
                        message=f"OpenCodeReview timed out after {self.timeout_seconds}s",
                    ),
                ),
                raw_evidence=str(exc),
            )

        raw_output = proc.stdout.strip()
        if not raw_output and proc.stderr:
            raw_output = proc.stderr.strip()

        findings: list[NormalizedFinding] = []
        try:
            parsed = json.loads(raw_output) if raw_output else []
            items = parsed if isinstance(parsed, list) else parsed.get("findings", [])
            for index, item in enumerate(items):
                if isinstance(item, dict):
                    findings.append(
                        FindingNormalizer.normalize(
                            item,
                            source="open-code-review",
                            fallback_id=f"ocr-{index + 1}",
                        )
                    )
        except Exception:
            findings.append(
                NormalizedFinding(
                    id="ocr-parse-error",
                    source="open-code-review",
                    severity="high",
                    category="other",
                    file=".",
                    message=f"Could not parse OpenCodeReview output. Exit code: {proc.returncode}",
                    metadata={"stdout": proc.stdout, "stderr": proc.stderr},
                )
            )

        passed = (proc.returncode == 0) and (len(findings) == 0)
        return ReviewResult(
            provider="open-code-review",
            passed=passed,
            findings=tuple(findings),
            raw_evidence=raw_output,
        )

