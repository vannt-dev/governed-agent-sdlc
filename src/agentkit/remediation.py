from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentkit.policy import GovernanceDecision, PolicyAction
from agentkit.review import NormalizedFinding, ReviewResult, write_review_evidence

DEFAULT_MAX_REMEDIATION_ATTEMPTS = 2


@dataclass(frozen=True)
class RemediationAttempt:
    attempt_number: int
    result: ReviewResult
    decision: GovernanceDecision
    evidence_dir: Path


class RemediationManager:
    def __init__(self, max_attempts: int = DEFAULT_MAX_REMEDIATION_ATTEMPTS) -> None:
        self.max_attempts = max_attempts
        self.attempts: list[RemediationAttempt] = []

    @property
    def current_attempt(self) -> int:
        return len(self.attempts)

    def can_remediate(self) -> bool:
        return len(self.attempts) < self.max_attempts

    def record_attempt(
        self,
        base_dir: Path,
        result: ReviewResult,
        decision: GovernanceDecision,
    ) -> tuple[RemediationAttempt, GovernanceDecision]:
        attempt_num = len(self.attempts) + 1
        attempt_dir = base_dir / f"review-attempt-{attempt_num}"
        attempt_dir.mkdir(parents=True, exist_ok=True)

        write_review_evidence(attempt_dir, result, decision)

        attempt = RemediationAttempt(
            attempt_number=attempt_num,
            result=result,
            decision=decision,
            evidence_dir=attempt_dir,
        )
        self.attempts.append(attempt)

        # If decision requested remediation but limit was reached, escalate to block
        if decision.action == "require-remediation" and not self.can_remediate():
            escalated_decision = GovernanceDecision(
                action="block",
                decisions=decision.decisions,
                findings_count=decision.findings_count,
                blocked=True,
                requires_approval=False,
                reasons=(
                    f"Remediation retry ceiling reached ({self.max_attempts} attempts). "
                    "Manual human intervention required.",
                ),
            )
            # update written policy result in attempt directory with escalation
            (attempt_dir / "policy-result.json").write_text(
                json.dumps(escalated_decision.to_dict(), indent=2), encoding="utf-8"
            )
            return attempt, escalated_decision

        return attempt, decision

    @staticmethod
    def detect_unresolved_findings(
        previous_findings: tuple[NormalizedFinding, ...] | list[NormalizedFinding],
        current_findings: tuple[NormalizedFinding, ...] | list[NormalizedFinding],
    ) -> list[NormalizedFinding]:
        """Identify findings from previous attempt that still persist in current attempt."""
        prev_signatures = {
            (f.file.replace("\\", "/"), f.line, f.category, f.message): f
            for f in previous_findings
        }
        unresolved: list[NormalizedFinding] = []
        for current in current_findings:
            sig = (current.file.replace("\\", "/"), current.line, current.category, current.message)
            if sig in prev_signatures or any(
                p.id == current.id or (p.file == current.file and p.message == current.message)
                for p in previous_findings
            ):
                unresolved.append(current)
        return unresolved
