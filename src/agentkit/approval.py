from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

VALID_DECISIONS = ("approved", "rejected")
# Identity tokens that mark an automated actor. Approval must come from a human-controlled channel.
AI_ACTOR_TOKENS = frozenset(
    {"ai", "agent", "llm", "bot", "assistant", "claude", "codex", "gpt", "copilot"}
)
_POLICY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ReviewApprovalRecord:
    policy_id: str
    finding_ids: tuple[str, ...]
    actor: str
    evidence: str
    decision: str = "approved"
    approval_type: str = "review-policy-approval"
    attempt: int = 1
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.approval_type,
            "decision": self.decision,
            "policyId": self.policy_id,
            "findingIds": list(self.finding_ids),
            "attempt": self.attempt,
            "actor": self.actor,
            "evidence": self.evidence,
            "timestamp": self.timestamp or datetime.now(UTC).isoformat(),
        }


def _is_ai_actor(actor: str) -> bool:
    return any(
        token in AI_ACTOR_TOKENS for token in re.split(r"[^a-z0-9]+", actor.lower()) if token
    )


def _approvals_dir(output_dir: Path) -> Path:
    return output_dir if output_dir.name == "approvals" else output_dir / "approvals"


def record_review_approval(
    output_dir: Path,
    policy_id: str,
    finding_ids: list[str] | tuple[str, ...],
    actor: str,
    evidence: str,
    decision: str = "approved",
    attempt: int = 1,
) -> Path:
    if not actor or not actor.strip() or _is_ai_actor(actor):
        raise ValueError(
            f"Approval actor cannot be an AI agent ('{actor}'). "
            "A durable human identity is required."
        )
    if not evidence or not evidence.strip():
        raise ValueError(
            "Durable approval evidence (e.g. ticket, PR link, review URL) is required."
        )
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Approval decision must be one of: {', '.join(VALID_DECISIONS)}")
    if not _POLICY_ID.match(policy_id):
        raise ValueError(f"Invalid policy id for an approval record: {policy_id!r}")
    if attempt < 1:
        raise ValueError("Approval attempt must be a positive integer")

    approvals_dir = _approvals_dir(output_dir)
    approvals_dir.mkdir(parents=True, exist_ok=True)

    record = ReviewApprovalRecord(
        policy_id=policy_id,
        finding_ids=tuple(finding_ids),
        actor=actor.strip(),
        evidence=evidence.strip(),
        decision=decision,
        attempt=attempt,
        timestamp=datetime.now(UTC).isoformat(),
    )

    approval_file = approvals_dir / f"review-approval-attempt-{attempt}-{policy_id}.json"
    try:
        # A decision is recorded once; changing it later needs a new attempt, not an overwrite.
        with approval_file.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), indent=2))
    except FileExistsError as exc:
        raise ValueError(
            f"A decision for policy '{policy_id}' on attempt {attempt} is already recorded; "
            "approval evidence is not overwritten."
        ) from exc
    return approval_file


def load_review_approvals(output_dir: Path) -> list[dict[str, Any]]:
    approvals_dir = output_dir / "approvals" if (output_dir / "approvals").is_dir() else output_dir
    if not approvals_dir.is_dir():
        return []

    records: list[dict[str, Any]] = []
    for file in sorted(approvals_dir.glob("review-approval-*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def approval_status(
    output_dir: Path,
    policy_id: str,
    *,
    attempt: int | None = None,
    finding_ids: Iterable[str] | None = None,
) -> str:
    """Return "approved", "rejected" or "pending" for one policy.

    A rejection always wins. An approval only counts when it names a human actor and evidence and
    covers every finding the policy fired on, so approving one finding cannot wave through another.
    """
    required = set(finding_ids) if finding_ids is not None else None
    approved = False
    for record in load_review_approvals(output_dir):
        if record.get("policyId") != policy_id:
            continue
        if attempt is not None and record.get("attempt", 1) != attempt:
            continue
        if not record.get("actor") or not record.get("evidence"):
            continue
        if record.get("decision") == "rejected":
            return "rejected"
        if record.get("decision") == "approved":
            covered = set(record.get("findingIds", []))
            if required is None or required <= covered:
                approved = True
    return "approved" if approved else "pending"


def validate_approval_for_policy(
    output_dir: Path,
    policy_id: str,
    *,
    attempt: int | None = None,
    finding_ids: Iterable[str] | None = None,
) -> bool:
    return (
        approval_status(output_dir, policy_id, attempt=attempt, finding_ids=finding_ids)
        == "approved"
    )
