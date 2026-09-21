from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentkit.policy import GovernanceDecision, PolicyDecision
from agentkit.remediation import RemediationManager
from agentkit.review import NormalizedFinding, ReviewResult


class RemediationManagerTests(unittest.TestCase):
    def test_remediation_bounded_attempts_escalation(self) -> None:
        manager = RemediationManager(max_attempts=2)
        self.assertTrue(manager.can_remediate())
        self.assertEqual(manager.current_attempt, 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)

            finding = NormalizedFinding(
                id="r-1",
                source="ocr",
                severity="high",
                category="correctness",
                file="app.py",
                message="Null pointer dereference",
            )
            result = ReviewResult(provider="ocr", passed=False, findings=(finding,))
            decision = GovernanceDecision(
                action="require-remediation",
                decisions=(
                    PolicyDecision(
                        policy_id="remediation-needed",
                        action="require-remediation",
                        finding_ids=("r-1",),
                        reason="Bug requires remediation",
                    ),
                ),
                findings_count={"critical": 0, "high": 1, "medium": 0, "low": 0, "info": 0},
                blocked=False,
                requires_approval=False,
                reasons=("Bug requires remediation",),
            )

            # Attempt 1
            att1, dec1 = manager.record_attempt(base_dir, result, decision)
            self.assertEqual(att1.attempt_number, 1)
            self.assertEqual(dec1.action, "require-remediation")
            self.assertTrue(manager.can_remediate())
            self.assertTrue((base_dir / "review-attempt-1" / "findings.json").is_file())

            # Attempt 2 (remediation limit reached -> escalates to block)
            att2, dec2 = manager.record_attempt(base_dir, result, decision)
            self.assertEqual(att2.attempt_number, 2)
            self.assertEqual(dec2.action, "block")
            self.assertTrue(dec2.blocked)
            self.assertIn("Remediation retry ceiling reached", dec2.reasons[0])
            self.assertFalse(manager.can_remediate())
            self.assertTrue((base_dir / "review-attempt-2" / "findings.json").is_file())

    def test_detect_unresolved_findings(self) -> None:
        f1 = NormalizedFinding(
            id="1",
            source="ocr",
            severity="high",
            category="security",
            file="src/a.py",
            message="SQLi",
        )
        f2 = NormalizedFinding(
            id="2",
            source="ocr",
            severity="medium",
            category="maintainability",
            file="src/b.py",
            message="Style",
        )
        f3_resolved = NormalizedFinding(
            id="3",
            source="ocr",
            severity="low",
            category="testing",
            file="src/c.py",
            message="Unused",
        )

        prev = [f1, f2, f3_resolved]
        curr = [f1, f2]

        unresolved = RemediationManager.detect_unresolved_findings(prev, curr)
        self.assertEqual(len(unresolved), 2)
        self.assertEqual([u.id for u in unresolved], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
