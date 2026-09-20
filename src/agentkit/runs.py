from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agentkit.approval import approval_status
from agentkit.policy import GovernanceDecision

RUNS_RELATIVE = Path(".agent") / "runs"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# OCR rejects a background over 8000 characters and warns over 2000; stay under the hard limit.
BACKGROUND_MAX_CHARS = 6000
SECTION_MAX_CHARS = {"Requirement": 2000, "Specification": 2000, "Plan": 2000}
MAX_INPUT_BYTES = 1024 * 1024
_RESERVED_TAGS = re.compile(r"</?ocr_user_background>", re.IGNORECASE)

# Exit codes of `agentkit review run|status`; 2 stays "configuration or filesystem error".
EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_PROVIDER_ERROR = 3
EXIT_AWAITING_APPROVAL = 4
EXIT_REMEDIATION_REQUIRED = 5
EXIT_SKIPPED = 6


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(2)}"


def validate_run_id(run_id: str) -> str:
    if not _RUN_ID.match(run_id):
        raise ValueError(
            f"Invalid run id {run_id!r}. Use letters, digits, '.', '_' and '-' (max 64)."
        )
    return run_id


def run_directory(root: Path, run_id: str) -> Path:
    path = (root / RUNS_RELATIVE / validate_run_id(run_id)).resolve()
    path.relative_to((root / RUNS_RELATIVE).resolve())
    return path


def read_bounded_text(path: Path) -> str:
    """Read a requirement/spec/plan file, refusing anything unreasonably large."""
    if not path.is_file():
        raise FileNotFoundError(f"Context file not found: {path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"Context file exceeds {MAX_INPUT_BYTES} bytes: {path}")
    return path.read_text(encoding="utf-8")


def sanitize_background(text: str) -> str:
    """Drop control/invisible characters and OCR's reserved delimiters so the file always loads."""
    cleaned = "".join(
        ch
        for ch in text.replace("\r", "")
        if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf"}
    )
    cleaned = _RESERVED_TAGS.sub("", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _clip(text: str, limit: int) -> str:
    clean = sanitize_background(text)
    return clean if len(clean) <= limit else clean[:limit].rstrip() + "\n[truncated]"


def build_review_background(
    run_dir: Path,
    requirement: str | None = None,
    specification: str | None = None,
    plan: str | None = None,
) -> Path | None:
    """Write only the requirement context the reviewer needs, never the whole run history.

    The file goes to `<run>/review-background.md`; an existing one is left untouched so an earlier
    attempt's evidence is not rewritten. Different context requires a new run id.
    Retries without context arguments reuse the existing background.
    """
    sections = [
        f"# {title}\n\n{_clip(body, SECTION_MAX_CHARS[title])}"
        for title, body in (
            ("Requirement", requirement),
            ("Specification", specification),
            ("Plan", plan),
        )
        if body and sanitize_background(body)
    ]
    path = run_dir / "review-background.md"
    if not sections:
        return path if path.is_file() else None
    text = _clip("\n\n".join(sections), BACKGROUND_MAX_CHARS)
    if path.exists():
        if read_bounded_text(path) != text + "\n":
            raise ValueError(
                "Review background differs from the existing run. Use a new --run-id to "
                "change the requirement, specification or plan; prior evidence is immutable."
            )
        return path
    run_dir.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text + "\n")
    return path


@dataclass(frozen=True)
class GateStatus:
    status: str
    exit_code: int
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "exitCode": self.exit_code, "detail": self.detail}


def review_gate_status(
    decision: GovernanceDecision, run_dir: Path, attempt: int, *, nothing_to_review: bool = False
) -> GateStatus:
    """Turn a governance decision plus recorded approvals into a pass/fail state.

    Only recorded human approvals clear a require-human-approval decision; model text cannot.
    """
    if decision.action == "block":
        return GateStatus("blocked", EXIT_BLOCKED, "; ".join(decision.reasons))
    if nothing_to_review:
        return GateStatus(
            "skipped",
            EXIT_SKIPPED,
            "The reviewer selected no files; no completed review is available.",
        )

    pending: list[str] = []
    for policy_id, finding_ids in decision.policy_ids_for("require-human-approval"):
        state = approval_status(run_dir, policy_id, attempt=attempt, finding_ids=finding_ids)
        if state == "rejected":
            return GateStatus(
                "rejected", EXIT_BLOCKED, f"Policy {policy_id} was rejected by a human."
            )
        if state == "pending":
            pending.append(policy_id)
    if pending:
        return GateStatus(
            "awaiting-approval",
            EXIT_AWAITING_APPROVAL,
            f"Human approval required for: {', '.join(pending)}.",
        )

    remediation = decision.policy_ids_for("require-remediation")
    if remediation:
        return GateStatus(
            "remediation-required",
            EXIT_REMEDIATION_REQUIRED,
            f"Fix and re-run the review: {', '.join(policy_id for policy_id, _ in remediation)}.",
        )
    return GateStatus("passed", EXIT_OK, "; ".join(decision.reasons))


def attempt_gate(run_dir: Path, attempt: int) -> tuple[GovernanceDecision, GateStatus]:
    """Recompute the gate of one stored attempt from its evidence and the recorded approvals.

    A provider error and an escalation are read from their own records, so the stored
    `policy-result.json` is used exactly as the engine wrote it.
    """
    import json

    attempt_dir = run_dir / f"review-attempt-{attempt}"
    decision = GovernanceDecision.from_dict(
        json.loads((attempt_dir / "policy-result.json").read_text(encoding="utf-8"))
    )
    escalation = attempt_dir / "escalation.json"
    if escalation.is_file():
        decision = GovernanceDecision(
            action="block",
            decisions=decision.decisions,
            findings_count=decision.findings_count,
            blocked=True,
            requires_approval=False,
            reasons=tuple(json.loads(escalation.read_text(encoding="utf-8")).get("reasons", [])),
        )
    if (attempt_dir / "provider-error.json").is_file():
        return decision, GateStatus(
            "provider-error", EXIT_PROVIDER_ERROR, "; ".join(decision.reasons)
        )
    provider_file = attempt_dir / "provider.json"
    provider = (
        json.loads(provider_file.read_text(encoding="utf-8")) if provider_file.is_file() else {}
    )
    return decision, review_gate_status(
        decision, run_dir, attempt, nothing_to_review=provider.get("nothingToReview") is True
    )
