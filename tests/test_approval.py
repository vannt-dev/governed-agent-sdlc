from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentkit.approval import (
    load_review_approvals,
    record_review_approval,
    validate_approval_for_policy,
)


class ApprovalGateTests(unittest.TestCase):
    def test_record_and_validate_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)

            app_file = record_review_approval(
                output_dir=out_dir,
                policy_id="security-high-approval",
                finding_ids=["sec-1"],
                actor="github:lead-security",
                evidence="https://github.com/org/repo/issues/123#issuecomment-999",
            )
            self.assertTrue(app_file.is_file())

            approvals = load_review_approvals(out_dir)
            self.assertEqual(len(approvals), 1)
            self.assertEqual(approvals[0]["policyId"], "security-high-approval")
            self.assertEqual(approvals[0]["actor"], "github:lead-security")

            self.assertTrue(validate_approval_for_policy(out_dir, "security-high-approval"))
            self.assertFalse(validate_approval_for_policy(out_dir, "non-existent-policy"))

    def test_rejects_ai_agent_as_approval_actor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            for invalid_actor in ("ai", "agent", "llm", "bot"):
                with self.assertRaises(ValueError):
                    record_review_approval(
                        output_dir=out_dir,
                        policy_id="sec-policy",
                        finding_ids=["f-1"],
                        actor=invalid_actor,
                        evidence="http://...",
                    )

    def test_rejects_empty_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir)
            with self.assertRaises(ValueError):
                record_review_approval(
                    output_dir=out_dir,
                    policy_id="sec-policy",
                    finding_ids=["f-1"],
                    actor="human-dev",
                    evidence="",
                )


if __name__ == "__main__":
    unittest.main()
