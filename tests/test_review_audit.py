from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agentkit.cli import main
from agentkit.events import EVENT_TYPES, emit_event, read_events, validate_events
from agentkit.report import build_run_report, render_html
from agentkit.review import VALID_CATEGORIES, VALID_SEVERITIES
from agentkit.validator import validate_project

SCHEMA = Path(__file__).resolve().parents[1] / "core" / "schemas" / "review-finding.schema.json"


class EventLogTests(unittest.TestCase):
    def test_events_are_sequential_append_only_and_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            first = emit_event(run, "r1", "review.started", {"attempt": 1})
            second = emit_event(run, "r1", "review.completed", {"attempt": 1})
            self.assertEqual(("r1-0001", "r1-0002"), (first.id, second.id))
            self.assertEqual(
                ["review.started", "review.completed"], [e["type"] for e in read_events(run)]
            )
            self.assertEqual([], validate_events(run))
            with self.assertRaises(ValueError):
                emit_event(run, "r1", "made.up")

    def test_validation_reports_a_tampered_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            emit_event(run, "r1", "review.started")
            log = run / "events.jsonl"
            log.write_text(
                log.read_text(encoding="utf-8")
                + "not json\n"
                + json.dumps({"id": "r1-0009", "type": "review.completed"})
                + "\n"
                + json.dumps({"id": "r1-0004", "type": "bogus"})
                + "\n",
                encoding="utf-8",
            )
            problems = validate_events(run)
            self.assertTrue(any("not valid JSON" in p for p in problems))
            self.assertTrue(any("id sequence" in p for p in problems))
            self.assertTrue(any("unknown event type" in p for p in problems))

    def test_documented_event_types_exist(self) -> None:
        for name in ("review.started", "review.completed", "policy.evaluated", "approval.granted"):
            self.assertIn(name, EVENT_TYPES)


class SharedContractTests(unittest.TestCase):
    def test_schema_enums_match_the_code(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        self.assertEqual(VALID_SEVERITIES, set(props["severity"]["enum"]))
        self.assertEqual(VALID_CATEGORIES, set(props["category"]["enum"]))
        self.assertEqual(
            {"id", "source", "severity", "category", "file", "message"}, set(schema["required"])
        )
        self.assertFalse(schema["additionalProperties"])


class ProjectFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.project = Path(self._temp.name) / "project"
        with redirect_stdout(io.StringIO()):
            main(["init", str(self.project), "--adapter", "none"])

    def cli(self, *argv: str, fmt: bool = True) -> tuple[int, dict[str, object]]:
        out, err = io.StringIO(), io.StringIO()
        args = [*argv, "--format", "json"] if fmt else list(argv)
        with (
            patch("agentkit.cli.find_project_root", return_value=self.project),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = main(args)
        text = (out.getvalue() or err.getvalue()).strip()
        return code, json.loads(text.splitlines()[-1]) if text.startswith("{") else {}

    def write_findings(self, items: list[dict[str, object]]) -> Path:
        path = Path(self._temp.name) / "findings.json"
        path.write_text(json.dumps(items), encoding="utf-8")
        return path


class RunEventsAndReportTests(ProjectFixture):
    def approval_run(self) -> None:
        findings = self.write_findings(
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
        self.cli(
            "review",
            "run",
            "--provider",
            "mock",
            "--mock-findings",
            str(findings),
            "--run-id",
            "r1",
        )
        self.cli(
            "review", "approve", "--run-id", "r1", "--policy", "security-high-approval",
            "--actor", "github:lead", "--evidence", "https://x/1",
        )  # fmt: skip

    def test_events_follow_the_run_in_order(self) -> None:
        self.approval_run()
        run = self.project / ".agent" / "runs" / "r1"
        types = [e["type"] for e in read_events(run)]
        self.assertEqual(
            [
                "review.started",
                "review.completed",
                "policy.evaluated",
                "policy.approval_required",
                "approval.granted",
            ],
            types,
        )
        self.assertEqual([], validate_events(run))

    def test_provider_failure_is_logged(self) -> None:
        from agentkit.review import ReviewProviderError

        error = ReviewProviderError("timeout", "slow")
        with patch("agentkit.review.OpenCodeReviewProvider.review", side_effect=error):
            self.cli("review", "run", "--provider", "open-code-review", "--run-id", "r2")
        types = [e["type"] for e in read_events(self.project / ".agent" / "runs" / "r2")]
        self.assertEqual(["review.started", "review.failed"], types)

    def test_report_summarizes_evidence_and_writes_escaped_html(self) -> None:
        self.approval_run()
        html_file = Path(self._temp.name) / "report.html"
        code, data = self.cli("review", "report", "--run-id", "r1", "--html", str(html_file))
        self.assertEqual(0, code)
        attempt = data["attempts"][0]  # type: ignore[index]
        self.assertEqual("passed", attempt["gate"]["status"])
        self.assertEqual(1, attempt["findings"]["high"])
        self.assertEqual("approved", attempt["approvals"][0]["decision"])
        self.assertTrue(html_file.is_file())
        # A report is never overwritten silently.
        code, _ = self.cli("review", "report", "--run-id", "r1", "--html", str(html_file))
        self.assertEqual(2, code)

    def test_report_html_escapes_reviewer_text(self) -> None:
        report = {
            "runId": "<script>x</script>",
            "attempts": [
                {
                    "attempt": 1,
                    "provider": "<b>p</b>",
                    "findings": {"high": 1},
                    "decision": "block",
                    "gate": {"status": "blocked"},
                    "approvals": [{"decision": "approved", "policyId": "<i>", "actor": "a&b"}],
                    "evidenceProblems": ["<img src=x onerror=alert(1)>"],
                }
            ],
            "events": [{"timestamp": "t", "type": "<svg>"}],
        }
        page = render_html(report)
        self.assertNotIn("<script>x", page)
        self.assertNotIn("<img", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("a&amp;b", page)

    def test_report_for_an_unknown_run_is_an_error(self) -> None:
        code, _ = self.cli("review", "report", "--run-id", "nope")
        self.assertEqual(2, code)
        self.assertEqual(
            [], build_run_report(self.project / ".agent" / "runs" / "nope", "nope")["attempts"]
        )


class ValidateRunEvidenceTests(ProjectFixture):
    def errors(self) -> list[str]:
        return [str(f) for f in validate_project(self.project) if f.level == "error"]

    def test_clean_runs_validate(self) -> None:
        findings = self.write_findings(
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
        self.cli(
            "review",
            "run",
            "--provider",
            "mock",
            "--mock-findings",
            str(findings),
            "--run-id",
            "ok",
        )
        self.cli(
            "review", "approve", "--run-id", "ok", "--policy", "security-high-approval",
            "--actor", "github:lead", "--evidence", "https://x/1",
        )  # fmt: skip
        self.assertEqual([], self.errors())

    def test_broken_evidence_is_reported(self) -> None:
        self.cli("review", "run", "--provider", "mock", "--run-id", "bad")
        run = self.project / ".agent" / "runs" / "bad"
        (run / "review-attempt-1" / "findings.json").write_text(
            json.dumps([{"id": "a", "severity": "nope"}]), encoding="utf-8"
        )
        approvals = run / "approvals"
        approvals.mkdir()
        (approvals / "review-approval-attempt-1-x.json").write_text(
            json.dumps(
                {"decision": "approved", "actor": "Claude", "evidence": "", "policyId": "x"}
            ),
            encoding="utf-8",
        )
        (run / "events.jsonl").write_text("garbage\n", encoding="utf-8")
        problems = "\n".join(self.errors())
        self.assertIn("severity", problems)
        self.assertIn("not an AI agent", problems)
        self.assertIn("evidence is required", problems)
        self.assertIn("events.jsonl", problems)


class ArtifactLinkTests(ProjectFixture):
    def make_review_artifact(self) -> str:
        out = io.StringIO()
        with redirect_stdout(out):
            main(["artifact", "new", "review", "auth-review", "--path", str(self.project)])
        return Path(out.getvalue().strip()).relative_to(self.project).as_posix()

    def test_run_records_the_review_artifact_it_supports(self) -> None:
        relative = self.make_review_artifact()
        code, _ = self.cli(
            "review", "run", "--provider", "mock", "--run-id", "a1", "--artifact", relative
        )
        self.assertEqual(0, code)
        run = self.project / ".agent" / "runs" / "a1"
        meta = json.loads((run / "review-attempt-1" / "provider.json").read_text(encoding="utf-8"))
        self.assertEqual(relative, meta["artifact"]["path"])
        self.assertTrue(meta["artifact"]["id"].startswith("REVIEW-"))
        started = read_events(run)[0]
        self.assertEqual(relative, started["payload"]["artifact"]["path"])
        report = build_run_report(run, "a1")
        self.assertEqual(relative, report["attempts"][0]["artifact"]["path"])

    def test_only_review_artifacts_inside_docs_agent_are_accepted(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            main(["artifact", "new", "spec", "s", "--path", str(self.project)])
        spec = Path(out.getvalue().strip()).relative_to(self.project).as_posix()
        self.assertEqual(2, self.cli("review", "run", "--provider", "mock", "--artifact", spec)[0])
        self.assertEqual(
            2, self.cli("review", "run", "--provider", "mock", "--artifact", "../outside.md")[0]
        )


if __name__ == "__main__":
    unittest.main()
