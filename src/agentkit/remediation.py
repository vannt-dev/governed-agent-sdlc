from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentkit.policy import GovernanceDecision
from agentkit.review import NormalizedFinding, ReviewResult, write_review_evidence

DEFAULT_MAX_REMEDIATION_ATTEMPTS = 2
ATTEMPT_DIR_PATTERN = re.compile(r"^review-attempt-(\d+)$")


def existing_attempts(base_dir: Path) -> list[int]:
    """Attempt numbers already on disk, so history survives across separate CLI invocations."""
    if not base_dir.is_dir():
        return []
    numbers = [
        int(match.group(1))
        for entry in base_dir.iterdir()
        if entry.is_dir() and (match := ATTEMPT_DIR_PATTERN.match(entry.name))
    ]
    return sorted(numbers)


def next_attempt_number(base_dir: Path) -> int:
    attempts = existing_attempts(base_dir)
    return (attempts[-1] + 1) if attempts else 1


@dataclass(frozen=True)
class RemediationAttempt:
    attempt_number: int
    result: ReviewResult
    decision: GovernanceDecision
    evidence_dir: Path


def finding_signature(finding: NormalizedFinding) -> tuple[str, str, str]:
    """Stable identity for "the same finding": provider ids like ocr-1 change with output order."""
    return (finding.file.replace("\\", "/"), finding.category, " ".join(finding.message.split()))


class RemediationManager:
    def __init__(
        self, max_attempts: int = DEFAULT_MAX_REMEDIATION_ATTEMPTS, enabled: bool = True
    ) -> None:
        self.max_attempts = max_attempts
        self.enabled = enabled
        self.attempts: list[RemediationAttempt] = []

    @property
    def current_attempt(self) -> int:
        return len(self.attempts)

    def can_remediate(self) -> bool:
        return self.enabled and len(self.attempts) < self.max_attempts

    def limit_decision(
        self, decision: GovernanceDecision, attempt_number: int
    ) -> GovernanceDecision:
        """Turn require-remediation into block when remediation is off or the ceiling is reached."""
        if decision.action != "require-remediation":
            return decision
        if not self.enabled:
            reason = "Remediation is disabled; the finding must be resolved by a human."
        elif attempt_number >= self.max_attempts:
            reason = (
                f"Remediation retry ceiling reached ({self.max_attempts} attempts). "
                "Manual human intervention required."
            )
        else:
            return decision
        return GovernanceDecision(
            action="block",
            decisions=decision.decisions,
            findings_count=decision.findings_count,
            blocked=True,
            requires_approval=False,
            reasons=(reason,),
        )

    def record_attempt(
        self,
        base_dir: Path,
        result: ReviewResult,
        decision: GovernanceDecision,
        provider_meta: dict[str, Any] | None = None,
    ) -> tuple[RemediationAttempt, GovernanceDecision]:
        attempt_num = next_attempt_number(base_dir)
        attempt_dir = base_dir / f"review-attempt-{attempt_num}"
        limited = self.limit_decision(decision, attempt_num)

        # The policy result stays what the engine decided; an escalation is a separate record.
        write_review_evidence(
            attempt_dir, result, decision, {"attempt": attempt_num, **(provider_meta or {})}
        )
        if limited is not decision:
            escalation = attempt_dir / "escalation.json"
            with escalation.open("x", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "from": decision.action,
                            "to": limited.action,
                            "reasons": list(limited.reasons),
                            "recordedAt": datetime.now(UTC).isoformat(),
                        },
                        indent=2,
                    )
                )

        attempt = RemediationAttempt(
            attempt_number=attempt_num,
            result=result,
            decision=limited,
            evidence_dir=attempt_dir,
        )
        self.attempts.append(attempt)
        return attempt, limited

    @staticmethod
    def detect_unresolved_findings(
        previous_findings: tuple[NormalizedFinding, ...] | list[NormalizedFinding],
        current_findings: tuple[NormalizedFinding, ...] | list[NormalizedFinding],
    ) -> list[NormalizedFinding]:
        """Findings from the previous attempt that still persist in the current attempt."""
        previous = {finding_signature(f) for f in previous_findings}
        return [f for f in current_findings if finding_signature(f) in previous]
