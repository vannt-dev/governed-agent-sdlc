from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agentkit.policy import (
    GovernanceDecision,
    PolicyEngine,
    PolicyRule,
)
from agentkit.review import (
    FindingNormalizer,
    MockReviewProvider,
    NormalizedFinding,
    ReviewContext,
    ReviewResult,
    write_review_evidence,
)


class FindingNormalizerTests(unittest.TestCase):
    def test_normalizes_severity_variations(self) -> None:
        self.assertEqual(FindingNormalizer.normalize_severity("blocker"), "critical")
        self.assertEqual(FindingNormalizer.normalize_severity("ERROR"), "high")
        self.assertEqual(FindingNormalizer.normalize_severity("warn"), "medium")
        self.assertEqual(FindingNormalizer.normalize_severity("minor"), "low")
        self.assertEqual(FindingNormalizer.normalize_severity("suggestion"), "info")
        self.assertEqual(FindingNormalizer.normalize_severity("unknown_severity"), "info")

    def test_normalizes_category_variations(self) -> None:
        self.assertEqual(FindingNormalizer.normalize_category("vuln"), "security")
        self.assertEqual(FindingNormalizer.normalize_category("auth"), "security")
        self.assertEqual(FindingNormalizer.normalize_category("bug"), "correctness")
        self.assertEqual(FindingNormalizer.normalize_category("perf"), "performance")
        self.assertEqual(FindingNormalizer.normalize_category("complexity"), "maintainability")
        self.assertEqual(FindingNormalizer.normalize_category("test"), "testing")
        self.assertEqual(FindingNormalizer.normalize_category("random_rule"), "other")

    def test_normalize_dict_to_finding(self) -> None:
        raw = {
            "id": "sec-101",
            "path": "src/auth/token.py",
            "line": "42",
            "level": "error",
            "rule_type": "vuln",
            "message": "Potential token leak in logs",
            "metadata": {"cwe": "CWE-532"},
        }
        finding = FindingNormalizer.normalize(raw, source="ocr")
        self.assertEqual(finding.id, "sec-101")
        self.assertEqual(finding.source, "ocr")
        self.assertEqual(finding.file, "src/auth/token.py")
        self.assertEqual(finding.line, 42)
        self.assertEqual(finding.severity, "high")
        self.assertEqual(finding.category, "security")
        self.assertEqual(finding.message, "Potential token leak in logs")
        self.assertEqual(finding.metadata, {"cwe": "CWE-532"})


class MockReviewProviderTests(unittest.TestCase):
    def test_mock_review_without_findings(self) -> None:
        provider = MockReviewProvider(name="mock-test")
        context = ReviewContext(run_id="run-1", repository_root=Path("."))
        result = provider.review(context)
        self.assertEqual(result.provider, "mock-test")
        self.assertTrue(result.passed)
        self.assertEqual(len(result.findings), 0)

    def test_mock_review_with_findings(self) -> None:
        findings = [
            NormalizedFinding(
                id="f-1",
                source="mock",
                severity="medium",
                category="maintainability",
                file="app.py",
                message="Code complexity too high",
            )
        ]
        provider = MockReviewProvider(findings=findings)
        result = provider.review(ReviewContext(run_id="run-2", repository_root=Path(".")))
        self.assertEqual(result.provider, "mock")
        self.assertFalse(result.passed)
        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].id, "f-1")


class PolicyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = PolicyEngine()

    def test_empty_findings_continue(self) -> None:
        decision = self.engine.evaluate([])
        self.assertEqual(decision.action, "continue")
        self.assertFalse(decision.blocked)
        self.assertFalse(decision.requires_approval)

    def test_critical_finding_blocks(self) -> None:
        findings = [
            NormalizedFinding(
                id="c-1",
                source="ocr",
                severity="critical",
                category="security",
                file="db.py",
                message="Hardcoded root password",
            )
        ]
        decision = self.engine.evaluate(findings)
        self.assertEqual(decision.action, "block")
        self.assertTrue(decision.blocked)
        self.assertFalse(decision.requires_approval)
        self.assertEqual(decision.findings_count["critical"], 1)

    def test_high_security_requires_human_approval(self) -> None:
        findings = [
            NormalizedFinding(
                id="s-1",
                source="ocr",
                severity="high",
                category="security",
                file="auth.py",
                message="Missing CSRF validation",
            )
        ]
        decision = self.engine.evaluate(findings)
        self.assertEqual(decision.action, "require-human-approval")
        self.assertFalse(decision.blocked)
        self.assertTrue(decision.requires_approval)

    def test_precedence_block_over_approval_and_warn(self) -> None:
        findings = [
            NormalizedFinding(
                id="crit-1",
                source="ocr",
                severity="critical",
                category="correctness",
                file="core.py",
                message="Infinite loop",
            ),
            NormalizedFinding(
                id="sec-1",
                source="ocr",
                severity="high",
                category="security",
                file="auth.py",
                message="Weak hash algorithm",
            ),
            NormalizedFinding(
                id="med-1",
                source="ocr",
                severity="medium",
                category="maintainability",
                file="view.py",
                message="Unused parameter",
            ),
        ]
        decision = self.engine.evaluate(findings)
        self.assertEqual(decision.action, "block")
        self.assertTrue(decision.blocked)

    def test_precedence_approval_over_warn(self) -> None:
        findings = [
            NormalizedFinding(
                id="sec-1",
                source="ocr",
                severity="high",
                category="security",
                file="auth.py",
                message="Weak cipher suite",
            ),
            NormalizedFinding(
                id="med-1",
                source="ocr",
                severity="medium",
                category="maintainability",
                file="view.py",
                message="Unused variable",
            ),
        ]
        decision = self.engine.evaluate(findings)
        self.assertEqual(decision.action, "require-human-approval")
        self.assertTrue(decision.requires_approval)

    def test_file_pattern_policy_matching(self) -> None:
        custom_rules = [
            PolicyRule(
                id="protected-auth-block",
                action="block",
                file_pattern="**/auth/**",
                severity="high",
                reason="High severity issue in auth area is blocked.",
            ),
            PolicyRule(
                id="general-high-warn",
                action="warn",
                severity="high",
                reason="High severity issue elsewhere is warning.",
            ),
        ]
        engine = PolicyEngine(rules=custom_rules)

        auth_finding = NormalizedFinding(
            id="f-auth",
            source="test",
            severity="high",
            category="correctness",
            file="services/auth/jwt.py",
            message="Token parsing issue",
        )
        dec_auth = engine.evaluate([auth_finding])
        self.assertEqual(dec_auth.action, "block")

        other_finding = NormalizedFinding(
            id="f-other",
            source="test",
            severity="high",
            category="correctness",
            file="services/reporting/csv.py",
            message="Encoding issue",
        )
        dec_other = engine.evaluate([other_finding])
        self.assertEqual(dec_other.action, "warn")


class ReviewEvidenceTests(unittest.TestCase):
    def test_write_review_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "review-run"
            findings = [
                NormalizedFinding(
                    id="f-1",
                    source="mock",
                    severity="low",
                    category="maintainability",
                    file="test.py",
                    message="Comment typo",
                )
            ]
            result = ReviewResult(
                provider="mock",
                passed=True,
                findings=tuple(findings),
                raw_evidence='[{"id": "f-1"}]',
            )
            decision = GovernanceDecision(
                action="continue",
                decisions=(),
                findings_count={"critical": 0, "high": 0, "medium": 0, "low": 1, "info": 0},
                blocked=False,
                requires_approval=False,
                reasons=("Low severity finding allowed to proceed.",),
            )

            written = write_review_evidence(out, result, decision)
            self.assertTrue(written["findings"].is_file())
            self.assertTrue(written["policy"].is_file())
            self.assertTrue((out / "mock-raw.json").is_file())

            findings_json = json.loads(written["findings"].read_text(encoding="utf-8"))
            self.assertEqual(len(findings_json), 1)
            self.assertEqual(findings_json[0]["id"], "f-1")

            policy_json = json.loads(written["policy"].read_text(encoding="utf-8"))
            self.assertEqual(policy_json["decision"], "continue")


if __name__ == "__main__":
    unittest.main()
