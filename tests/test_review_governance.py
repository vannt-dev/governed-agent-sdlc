from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agentkit.approval import approval_status, record_review_approval
from agentkit.cli import main
from agentkit.config import ConfigError, load_config
from agentkit.policy import (
    GovernanceDecision,
    PolicyEngine,
    load_policies,
    provider_error_decision,
)
from agentkit.remediation import RemediationManager, existing_attempts, next_attempt_number
from agentkit.review import NormalizedFinding, ReviewProviderError, ReviewResult
from agentkit.runs import (
    BACKGROUND_MAX_CHARS,
    EXIT_AWAITING_APPROVAL,
    EXIT_BLOCKED,
    EXIT_OK,
    EXIT_PROVIDER_ERROR,
    EXIT_REMEDIATION_REQUIRED,
    EXIT_SKIPPED,
    build_review_background,
    review_gate_status,
    run_directory,
    sanitize_background,
    validate_run_id,
)


def _finding(fid: str, severity: str, category: str, message: str = "msg") -> NormalizedFinding:
    return NormalizedFinding(fid, "test", severity, category, "src/a.py", message, 1)


class PolicyConfigTests(unittest.TestCase):
    def test_defaults_when_no_policies_are_configured(self) -> None:
        self.assertEqual("critical-block", load_policies(None)[0].id)
        self.assertEqual("critical-block", load_policies([])[0].id)

    def test_custom_policies_replace_the_defaults(self) -> None:
        rules = load_policies(
            [
                {
                    "id": "sec",
                    "action": "require-remediation",
                    "severity": "high",
                    "category": "security",
                }
            ]
        )
        engine = PolicyEngine(rules)
        decision = engine.evaluate([_finding("f1", "high", "security")])
        self.assertEqual("require-remediation", decision.action)
        # A critical finding no longer blocks because the operator chose different policies.
        self.assertEqual("continue", engine.evaluate([_finding("f2", "critical", "other")]).action)

    def test_invalid_policies_are_rejected(self) -> None:
        bad = [
            [{"id": "a", "action": "explode"}],
            [{"id": "", "action": "block"}],
            [{"id": "a", "action": "block"}, {"id": "a", "action": "warn"}],
            [{"id": "a", "action": "block", "surprise": 1}],
            [{"id": "a", "action": "block", "severity": 3}],
        ]
        for entries in bad:
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                load_policies(entries)

    def test_provider_error_always_blocks(self) -> None:
        decision = provider_error_decision("timeout", "slow")
        self.assertEqual("block", decision.action)
        self.assertTrue(decision.blocked)

    def test_decision_round_trips_through_evidence(self) -> None:
        decision = PolicyEngine().evaluate([_finding("f1", "high", "security")])
        restored = GovernanceDecision.from_dict(decision.to_dict())
        self.assertEqual(decision.action, restored.action)
        self.assertEqual(
            [("security-high-approval", ("f1",))], restored.policy_ids_for("require-human-approval")
        )
        with self.assertRaises(ValueError):
            GovernanceDecision.from_dict({"decision": "nonsense"})


class ManifestTests(unittest.TestCase):
    def _project(self, temp: str, extra: str) -> Path:
        root = Path(temp)
        main(["init", str(root), "--adapter", "none"])
        manifest = root / "agentkit.toml"
        if not manifest.exists():
            manifest = root / ".agent" / "project.toml"
        manifest.write_text(manifest.read_text(encoding="utf-8") + "\n" + extra, encoding="utf-8")
        return root

    def test_defaults_without_review_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            config = load_config(self._project(temp, ""))
        self.assertEqual("mock", config.review["provider"])
        self.assertEqual({"enabled": True, "max_attempts": 2}, config.remediation)
        self.assertEqual((), config.policies)

    def test_reads_review_policies_and_remediation(self) -> None:
        extra = """
[review]
provider = "open-code-review"
timeout_seconds = 60
include_plan = false

[remediation]
enabled = false
max_attempts = 3

[[policies]]
id = "auth-block"
action = "block"
file_pattern = "**/auth/**"
severity = "high"
"""
        with tempfile.TemporaryDirectory() as temp, redirect_stdout(io.StringIO()):
            config = load_config(self._project(temp, extra))
        self.assertEqual("open-code-review", config.review["provider"])
        self.assertFalse(config.review["include_plan"])
        self.assertTrue(config.review["include_spec"])
        self.assertEqual(3, config.remediation["max_attempts"])
        self.assertEqual("auth-block", config.policies[0]["id"])

    def test_rejects_invalid_settings(self) -> None:
        bad = [
            '[review]\nprovider = "other"',
            "[review]\ntimeout_seconds = 0",
            "[review]\nsurprise = 1",
            "[remediation]\nmax_attempts = 0",
            '[remediation]\nenabled = "yes"',
            '[[policies]]\nid = "a"\naction = "explode"',
        ]
        for extra in bad:
            with (
                self.subTest(extra=extra),
                tempfile.TemporaryDirectory() as temp,
                redirect_stdout(io.StringIO()),
                self.assertRaises(ConfigError),
            ):
                load_config(self._project(temp, extra))


class ApprovalTests(unittest.TestCase):
    def _record(self, out: Path, **overrides: object) -> Path:
        args: dict[str, object] = {
            "policy_id": "sec",
            "finding_ids": ["f1"],
            "actor": "github:lead",
            "evidence": "https://example.test/pr/1",
        }
        args.update(overrides)
        return record_review_approval(out, **args)  # type: ignore[arg-type]

    def test_duplicate_decision_is_refused_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            self._record(out)
            with self.assertRaises(ValueError):
                self._record(out, decision="rejected")
            self.assertEqual("approved", approval_status(out, "sec"))

    def test_rejection_wins_and_pending_when_nothing_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            self.assertEqual("pending", approval_status(out, "sec"))
            self._record(out, attempt=1, decision="rejected")
            self._record(out, attempt=2)
            self.assertEqual("rejected", approval_status(out, "sec", attempt=1))
            self.assertEqual("approved", approval_status(out, "sec", attempt=2))
            self.assertEqual("rejected", approval_status(out, "sec"))

    def test_approval_must_cover_every_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            self._record(out, finding_ids=["f1"])
            self.assertEqual("approved", approval_status(out, "sec", finding_ids=["f1"]))
            self.assertEqual("pending", approval_status(out, "sec", finding_ids=["f1", "f2"]))

    def test_approval_is_scoped_to_its_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            self._record(out, attempt=1)
            self.assertEqual("pending", approval_status(out, "sec", attempt=2))

    def test_actor_and_inputs_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            for actor in ("ai", "Claude", "github:copilot-bot", "codex", " "):
                with self.subTest(actor=actor), self.assertRaises(ValueError):
                    self._record(out, actor=actor)
            for bad in ({"decision": "maybe"}, {"policy_id": "../x"}, {"attempt": 0}):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    self._record(out, **bad)


class RemediationTests(unittest.TestCase):
    @staticmethod
    def _decision(action: str = "require-remediation") -> GovernanceDecision:
        engine = PolicyEngine(load_policies([{"id": "fix", "action": action, "severity": "high"}]))
        return engine.evaluate([_finding("f1", "high", "correctness")])

    def test_attempts_survive_across_manager_instances_and_are_never_overwritten(self) -> None:
        result = ReviewResult("mock", False, (_finding("f1", "high", "correctness"),))
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            first, decision1 = RemediationManager(max_attempts=3).record_attempt(
                base, result, self._decision()
            )
            second, decision2 = RemediationManager(max_attempts=3).record_attempt(
                base, result, self._decision()
            )
            self.assertEqual((1, 2), (first.attempt_number, second.attempt_number))
            self.assertEqual([1, 2], existing_attempts(base))
            self.assertEqual(3, next_attempt_number(base))
            self.assertEqual("require-remediation", decision1.action)
            self.assertEqual("require-remediation", decision2.action)

    def test_escalation_is_a_separate_record_and_policy_result_is_untouched(self) -> None:
        result = ReviewResult("mock", False, (_finding("f1", "high", "correctness"),))
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            manager = RemediationManager(max_attempts=1)
            attempt, limited = manager.record_attempt(base, result, self._decision())
            self.assertEqual("block", limited.action)
            stored = json.loads((attempt.evidence_dir / "policy-result.json").read_text("utf-8"))
            self.assertEqual("require-remediation", stored["decision"])
            escalation = json.loads((attempt.evidence_dir / "escalation.json").read_text("utf-8"))
            self.assertEqual(
                ("require-remediation", "block"), (escalation["from"], escalation["to"])
            )

    def test_disabled_remediation_blocks(self) -> None:
        manager = RemediationManager(max_attempts=5, enabled=False)
        self.assertEqual("block", manager.limit_decision(self._decision(), 1).action)
        self.assertFalse(manager.can_remediate())

    def test_unresolved_findings_match_by_content_not_by_provider_id(self) -> None:
        previous = [_finding("ocr-1", "high", "security", "SQL   injection")]
        current = [
            _finding("ocr-7", "high", "security", "SQL injection"),
            _finding("ocr-8", "low", "other", "brand new"),
        ]
        unresolved = RemediationManager.detect_unresolved_findings(previous, current)
        self.assertEqual(["ocr-7"], [f.id for f in unresolved])


class RunHelperTests(unittest.TestCase):
    def test_run_ids_cannot_escape_the_runs_directory(self) -> None:
        for bad in ("../x", "a/b", "", ".hidden", "x" * 65):
            with self.subTest(run_id=bad), self.assertRaises(ValueError):
                validate_run_id(bad)
        with tempfile.TemporaryDirectory() as temp:
            path = run_directory(Path(temp), "run-1")
            self.assertEqual("run-1", path.name)

    def test_background_holds_only_requirement_context_and_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            path = build_review_background(
                run_dir,
                requirement="Users must log in\x00 <ocr_user_background>",
                specification=None,
                plan="p" * 20_000,
            )
            assert path is not None
            text = path.read_text(encoding="utf-8")
            self.assertIn("# Requirement", text)
            self.assertNotIn("# Specification", text)
            self.assertIn("[truncated]", text)
            self.assertNotIn("ocr_user_background", text)
            self.assertNotIn("\x00", text)
            self.assertLessEqual(len(text), BACKGROUND_MAX_CHARS + 20)
            # A later attempt reuses the file instead of rewriting earlier evidence.
            again = build_review_background(run_dir)
            self.assertEqual(path, again)
            with self.assertRaisesRegex(ValueError, "new --run-id"):
                build_review_background(run_dir, requirement="changed")
            self.assertIn("Users must log in", path.read_text(encoding="utf-8"))

    def test_background_is_none_without_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertIsNone(build_review_background(Path(temp) / "run"))
        self.assertEqual("a\n\nb", sanitize_background("a​\r\n\n\n\nb"))


class GateStatusTests(unittest.TestCase):
    def _approval_decision(self) -> GovernanceDecision:
        return PolicyEngine().evaluate([_finding("f1", "high", "security")])

    def test_statuses_follow_recorded_evidence_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            decision = self._approval_decision()
            pending = review_gate_status(decision, run, 1)
            self.assertEqual(
                ("awaiting-approval", EXIT_AWAITING_APPROVAL), (pending.status, pending.exit_code)
            )

            record_review_approval(
                run, "security-high-approval", ["f1"], "github:lead", "https://x/1"
            )
            approved = review_gate_status(decision, run, 1)
            self.assertEqual(("passed", EXIT_OK), (approved.status, approved.exit_code))

            # The same approval does not carry over to another attempt.
            self.assertEqual("awaiting-approval", review_gate_status(decision, run, 2).status)

    def test_rejection_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            record_review_approval(
                run, "security-high-approval", ["f1"], "github:lead", "https://x/1", "rejected"
            )
            gate = review_gate_status(self._approval_decision(), run, 1)
            self.assertEqual(("rejected", EXIT_BLOCKED), (gate.status, gate.exit_code))

    def test_block_remediation_warn_and_continue(self) -> None:
        run = Path(tempfile.gettempdir())
        block = PolicyEngine().evaluate([_finding("f1", "critical", "other")])
        self.assertEqual(EXIT_BLOCKED, review_gate_status(block, run, 1).exit_code)
        fix = PolicyEngine(load_policies([{"id": "fix", "action": "require-remediation"}]))
        remediation = fix.evaluate([_finding("f1", "low", "other")])
        self.assertEqual(
            EXIT_REMEDIATION_REQUIRED, review_gate_status(remediation, run, 1).exit_code
        )
        warn = PolicyEngine().evaluate([_finding("f1", "medium", "other")])
        self.assertEqual(EXIT_OK, review_gate_status(warn, run, 1).exit_code)
        self.assertEqual(EXIT_OK, review_gate_status(PolicyEngine().evaluate([]), run, 1).exit_code)


class ReviewCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.project = Path(self._temp.name) / "project"
        with redirect_stdout(io.StringIO()):
            main(["init", str(self.project), "--adapter", "none"])
        self.findings = Path(self._temp.name) / "findings.json"

    def _write_findings(self, items: list[dict[str, object]]) -> None:
        self.findings.write_text(json.dumps(items), encoding="utf-8")

    def _cli(self, *argv: str) -> tuple[int, dict[str, object]]:
        out, err = io.StringIO(), io.StringIO()
        with (
            patch("agentkit.cli.find_project_root", return_value=self.project),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = main([*argv, "--format", "json"])
        text = out.getvalue() or err.getvalue()
        return code, json.loads(text.strip().splitlines()[-1]) if text.strip() else {}

    def test_run_writes_attempt_evidence_under_the_project_run_directory(self) -> None:
        code, data = self._cli("review", "run", "--provider", "mock", "--run-id", "run-a")
        self.assertEqual(EXIT_OK, code)
        attempt = self.project / ".agent" / "runs" / "run-a" / "review-attempt-1"
        for name in ("findings.json", "policy-result.json", "provider.json"):
            self.assertTrue((attempt / name).is_file(), name)
        self.assertEqual("passed", data["gate"]["status"])  # type: ignore[index]

    def test_human_approval_flow_end_to_end(self) -> None:
        self._write_findings(
            [
                {
                    "id": "s1",
                    "severity": "high",
                    "category": "security",
                    "file": "a.py",
                    "message": "x",
                }
            ]
        )
        base = ("review", "run", "--provider", "mock", "--mock-findings", str(self.findings))
        code, data = self._cli(*base, "--run-id", "run-b")
        self.assertEqual(EXIT_AWAITING_APPROVAL, code)
        self.assertEqual("awaiting-approval", data["gate"]["status"])  # type: ignore[index]

        code, _ = self._cli("review", "status", "--run-id", "run-b")
        self.assertEqual(EXIT_AWAITING_APPROVAL, code)

        args = ("review", "approve", "--run-id", "run-b", "--policy", "security-high-approval")
        code, _ = self._cli(*args, "--actor", "claude", "--evidence", "https://x/1")
        self.assertEqual(2, code)  # an AI actor cannot approve

        code, data = self._cli(*args, "--actor", "github:lead", "--evidence", "https://x/1")
        self.assertEqual(EXIT_OK, code)
        self.assertEqual("passed", data["gate"]["status"])  # type: ignore[index]
        code, _ = self._cli("review", "status", "--run-id", "run-b")
        self.assertEqual(EXIT_OK, code)

        code, _ = self._cli(
            *args, "--actor", "github:lead", "--evidence", "https://x/1", "--reject"
        )
        self.assertEqual(2, code)  # the recorded decision is not overwritten

    def test_approving_a_policy_that_did_not_fire_is_refused(self) -> None:
        self._cli("review", "run", "--provider", "mock", "--run-id", "run-c")
        code, _ = self._cli(
            "review", "approve", "--run-id", "run-c", "--policy", "security-high-approval",
            "--actor", "github:lead", "--evidence", "https://x/1",
        )  # fmt: skip
        self.assertEqual(2, code)

    def test_blocked_and_repeated_runs_create_new_attempts(self) -> None:
        self._write_findings(
            [
                {
                    "id": "c1",
                    "severity": "critical",
                    "category": "other",
                    "file": "a.py",
                    "message": "x",
                }
            ]
        )
        args = ("review", "run", "--provider", "mock", "--mock-findings", str(self.findings))
        self.assertEqual(EXIT_BLOCKED, self._cli(*args, "--run-id", "run-d")[0])
        code, data = self._cli(*args, "--run-id", "run-d")
        self.assertEqual(EXIT_BLOCKED, code)
        self.assertEqual(2, data["run"]["attempt"])  # type: ignore[index]
        self.assertEqual(["c1"], data["unresolvedFromPreviousAttempt"])
        runs = self.project / ".agent" / "runs" / "run-d"
        self.assertEqual(
            {"review-attempt-1", "review-attempt-2", "events.jsonl"},
            {p.name for p in runs.iterdir()},
        )

    def test_provider_failure_is_exit_3_with_evidence_and_never_a_pass(self) -> None:
        error = ReviewProviderError("timeout", "OpenCodeReview exceeded its 5s timeout")
        with patch("agentkit.review.OpenCodeReviewProvider.review", side_effect=error):
            code, data = self._cli(
                "review", "run", "--provider", "open-code-review", "--run-id", "run-e"
            )
        self.assertEqual(EXIT_PROVIDER_ERROR, code)
        self.assertEqual("provider-error", data["gate"]["status"])  # type: ignore[index]
        attempt = self.project / ".agent" / "runs" / "run-e" / "review-attempt-1"
        self.assertTrue((attempt / "provider-error.json").is_file())
        code, _ = self._cli("review", "status", "--run-id", "run-e")
        self.assertEqual(EXIT_PROVIDER_ERROR, code)

    def test_incomplete_review_is_a_provider_error_but_keeps_its_findings(self) -> None:
        finding = _finding("ocr-1", "low", "other")
        error = ReviewProviderError("incomplete", "budget reached", (finding,))
        with patch("agentkit.review.OpenCodeReviewProvider.review", side_effect=error):
            code, data = self._cli(
                "review", "run", "--provider", "open-code-review", "--run-id", "run-g"
            )
        self.assertEqual(EXIT_PROVIDER_ERROR, code)
        attempt = self.project / ".agent" / "runs" / "run-g" / "review-attempt-1"
        kept = json.loads((attempt / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual(["ocr-1"], [f["id"] for f in kept])
        self.assertEqual(
            "incomplete", json.loads((attempt / "provider-error.json").read_text("utf-8"))["kind"]
        )

    def test_requirement_is_passed_to_the_reviewer_as_a_background_file(self) -> None:
        requirement = Path(self._temp.name) / "req.md"
        requirement.write_text("Users must log in with refresh tokens", encoding="utf-8")
        captured: dict[str, str | None] = {}

        def fake_review(self_: object, context: object) -> ReviewResult:
            captured["background"] = context.background_file
            captured["from"] = context.from_ref
            return ReviewResult("open-code-review", True, ())

        with patch("agentkit.review.OpenCodeReviewProvider.review", fake_review):
            code, _ = self._cli(
                "review", "run", "--provider", "open-code-review", "--run-id", "run-f",
                "--requirement", str(requirement), "--from", "main",
            )  # fmt: skip
        self.assertEqual(EXIT_OK, code)
        background = Path(captured["background"] or "")
        self.assertIn("refresh tokens", background.read_text(encoding="utf-8"))
        self.assertEqual("main", captured["from"])

    def test_retry_reuses_context_and_rejects_a_changed_plan_before_running_ocr(self) -> None:
        plan = Path(self._temp.name) / "plan.md"
        plan.write_text("Keep existing permissions.", encoding="utf-8")
        base = ("review", "run", "--provider", "open-code-review", "--run-id", "context-run")
        result = ReviewResult("open-code-review", True, ())
        with patch("agentkit.review.OpenCodeReviewProvider.review", return_value=result) as review:
            self.assertEqual(EXIT_OK, self._cli(*base, "--plan", str(plan))[0])
            initial = review.call_args[0][0].background_file
            self.assertEqual(EXIT_OK, self._cli(*base)[0])
            self.assertEqual(initial, review.call_args[0][0].background_file)
            self.assertEqual(EXIT_OK, self._cli(*base, "--plan", str(plan))[0])
            plan.write_text("Require stronger permissions.", encoding="utf-8")
            code, data = self._cli(*base, "--plan", str(plan))
            self.assertEqual(2, code)
            self.assertIn("new --run-id", data["error"])
            self.assertEqual(3, review.call_count)
        assert initial is not None
        self.assertIn("Keep existing permissions.", Path(initial).read_text(encoding="utf-8"))

    def test_skipped_review_stays_nonpassing_in_run_status_and_report(self) -> None:
        result = ReviewResult("open-code-review", False, (), nothing_to_review=True)
        with patch("agentkit.review.OpenCodeReviewProvider.review", return_value=result):
            code, data = self._cli(
                "review", "run", "--provider", "open-code-review", "--run-id", "skipped-run"
            )
        self.assertEqual(EXIT_SKIPPED, code)
        self.assertEqual("skipped", data["gate"]["status"])
        code, data = self._cli("review", "status", "--run-id", "skipped-run")
        self.assertEqual(EXIT_SKIPPED, code)
        self.assertEqual("skipped", data["gate"]["status"])
        code, data = self._cli("review", "report", "--run-id", "skipped-run")
        self.assertEqual(EXIT_OK, code)
        self.assertEqual("skipped", data["latestGate"]["status"])

    def test_evaluate_still_works_and_refuses_to_overwrite_evidence(self) -> None:
        self._write_findings(
            [
                {
                    "id": "f-1",
                    "severity": "critical",
                    "category": "security",
                    "file": "m.py",
                    "message": "x",
                }
            ]
        )
        out_dir = Path(self._temp.name) / "evidence"
        argv = ("review", "evaluate", str(self.findings), "--output-dir", str(out_dir))
        self.assertEqual(EXIT_BLOCKED, self._cli(*argv)[0])
        self.assertEqual(2, self._cli(*argv)[0])


if __name__ == "__main__":
    unittest.main()
