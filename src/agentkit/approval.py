from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReviewApprovalRecord:
    policy_id: str
    finding_ids: tuple[str, ...]
    actor: str
    evidence: str
    decision: str = "approved"
    approval_type: str = "review-policy-approval"
    timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.approval_type,
            "decision": self.decision,
            "policyId": self.policy_id,
            "findingIds": list(self.finding_ids),
            "actor": self.actor,
            "evidence": self.evidence,
            "timestamp": self.timestamp or datetime.now(UTC).isoformat(),
        }


def record_review_approval(
    output_dir: Path,
    policy_id: str,
    finding_ids: list[str] | tuple[str, ...],
    actor: str,
    evidence: str,
    decision: str = "approved",
) -> Path:
    if not actor or actor.strip().lower() in ("ai", "agent", "llm", "bot", "assistant"):
        raise ValueError(
            f"Approval actor cannot be an AI agent ('{actor}'). A durable human identity is required."
        )
    if not evidence or not evidence.strip():
        raise ValueError("Durable approval evidence (e.g. ticket, PR link, review URL) is required.")

    approvals_dir = output_dir / "approvals" if output_dir.name != "approvals" else output_dir
    approvals_dir.mkdir(parents=True, exist_ok=True)

    record = ReviewApprovalRecord(
        policy_id=policy_id,
        finding_ids=tuple(finding_ids),
        actor=actor.strip(),
        evidence=evidence.strip(),
        decision=decision,
        timestamp=datetime.now(UTC).isoformat(),
    )

    approval_file = approvals_dir / f"review-approval-{policy_id}.json"
    approval_file.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
    return approval_file


def load_review_approvals(output_dir: Path) -> list[dict[str, Any]]:
    approvals_dir = output_dir / "approvals" if (output_dir / "approvals").is_dir() else output_dir
    if not approvals_dir.is_dir():
        return []

    records: list[dict[str, Any]] = []
    for file in sorted(approvals_dir.glob("review-approval-*.json")):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                records.append(data)
        except Exception:
            continue
    return records


def validate_approval_for_policy(output_dir: Path, policy_id: str) -> bool:
    approvals = load_review_approvals(output_dir)
    for app in approvals:
        if (
            app.get("policyId") == policy_id
            and app.get("decision") == "approved"
            and app.get("actor")
            and app.get("evidence")
        ):
            return True
    return False
