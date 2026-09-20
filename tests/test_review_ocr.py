from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agentkit.policy import PolicyEngine
from agentkit.review import (
    MAX_OUTPUT_BYTES,
    FindingNormalizer,
    NormalizedFinding,
    OpenCodeReviewProvider,
    ReviewContext,
    ReviewProviderError,
    ReviewResult,
    filter_env,
    parse_ocr_output,
    redact_secrets,
    validate_review_evidence,
    write_review_evidence,
)

# Shape taken from a real `ocr review --format json` run (v1.12.7): success reports "complete".
OCR_SUCCESS = json.dumps(
    {
        "status": "complete",
        "comments": [
            {
                "path": "src\\api.py",
                "content": "SQL injection via api_key=sk-abcdefghijklmnopqrstuvwxyz",
                "start_line": 15,
                "end_line": 17,
                "category": "security",
                "severity": "high",
            },
            {
                "path": "src/util.py",
                "content": "Unused helper",
                "start_line": 0,
                "category": "style",
            },
        ],
    }
)


def _proc(stdout: str = "", returncode: int = 0, stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class ParseOcrOutputTests(unittest.TestCase):
    def test_parses_comments_into_normalized_redacted_findings(self) -> None:
        findings, nothing = parse_ocr_output(OCR_SUCCESS)
        self.assertFalse(nothing)
        self.assertEqual(2, len(findings))
        first, second = findings
        self.assertEqual("ocr-1", first.id)
        self.assertEqual(("src/api.py", 15), (first.file, first.line))
        self.assertEqual(("high", "security"), (first.severity, first.category))
        self.assertNotIn("sk-abcdef", first.message)
        self.assertEqual({"end_line": 17}, first.metadata)
        # Missing severity stays visible, a zero line means "no line", style is maintainability.
        self.assertEqual(
            ("medium", "maintainability", None), (second.severity, second.category, second.line)
        )

    def test_skipped_means_nothing_to_review(self) -> None:
        skipped = json.dumps({"status": "skipped", "comments": []})
        self.assertEqual(([], True), parse_ocr_output(skipped))

    def test_accepts_every_completed_status_and_null_comments(self) -> None:
        # Go marshals an empty slice as null, so a clean real review has "comments": null.
        for status in ("complete", "success", "completed_with_warnings"):
            with self.subTest(status=status):
                self.assertEqual(
                    ([], False), parse_ocr_output(json.dumps({"status": status, "comments": None}))
                )
                self.assertEqual(([], False), parse_ocr_output(json.dumps({"status": status})))

    def test_partial_runs_are_incomplete_errors_that_keep_their_findings(self) -> None:
        for status in ("partial", "completed_with_errors"):
            with self.subTest(status=status), self.assertRaises(ReviewProviderError) as ctx:
                parse_ocr_output(
                    json.dumps(
                        {
                            "status": status,
                            "message": "1 of 3 items failed",
                            "comments": [{"path": "a.py", "content": "x", "severity": "low"}],
                        }
                    )
                )
            self.assertEqual("incomplete", ctx.exception.kind)
            self.assertEqual(1, len(ctx.exception.findings))

    def test_rejects_malformed_output_instead_of_guessing(self) -> None:
        cases = {
            "not json": "parse",
            "[]": "schema",
            json.dumps({"comments": []}): "schema",
            json.dumps({"status": "success", "comments": {}}): "schema",
            json.dumps({"status": "success", "comments": [{"path": "a"}]}): "schema",
            json.dumps({"status": "failed", "message": "quota"}): "exit",
        }
        for output, kind in cases.items():
            with self.subTest(output=output), self.assertRaises(ReviewProviderError) as ctx:
                parse_ocr_output(output)
            self.assertEqual(kind, ctx.exception.kind)


class HelperTests(unittest.TestCase):
    def test_redacts_common_secret_shapes(self) -> None:
        self.assertNotIn("sk-abcdef", redact_secrets("key sk-abcdefghijklmnopqrstuvwxyz end"))
        self.assertIn("[REDACTED]", redact_secrets('password = "hunter2hunter2"'))
        self.assertEqual("nothing secret", redact_secrets("nothing secret"))

    def test_filter_env_keeps_only_what_the_reviewer_needs(self) -> None:
        env = filter_env(
            {
                "PATH": "/bin",
                "GITHUB_TOKEN": "x",
                "OCR_HOME": "/o",
                "ANTHROPIC_API_KEY": "k",
                "NPM_TOKEN": "y",
            }
        )
        self.assertEqual({"PATH", "OCR_HOME", "ANTHROPIC_API_KEY"}, set(env))

    def test_category_vocabulary_from_ocr(self) -> None:
        self.assertEqual("correctness", FindingNormalizer.normalize_category("bug"))
        self.assertEqual("testing", FindingNormalizer.normalize_category("test"))
        documentation = FindingNormalizer.normalize_category("documentation")
        self.assertEqual("maintainability", documentation)


class OpenCodeReviewProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OpenCodeReviewProvider(executable="mock_ocr")
        self.context = ReviewContext(run_id="r", repository_root=Path("/repo"))

    def _run(
        self, outcome: MagicMock | Exception, context: ReviewContext | None = None
    ) -> ReviewResult:
        with (
            patch("shutil.which", return_value="/bin/mock_ocr"),
            patch("subprocess.run") as mock_run,
        ):
            if isinstance(outcome, Exception):
                mock_run.side_effect = outcome
            else:
                mock_run.return_value = outcome
            self.mock_run = mock_run
            return self.provider.review(context or self.context)

    def test_missing_executable_is_a_provider_error_not_a_finding(self) -> None:
        provider = OpenCodeReviewProvider(executable="nonexistent_ocr_bin_xyz_999")
        self.assertFalse(provider.is_available())
        with self.assertRaises(ReviewProviderError) as ctx:
            provider.review(self.context)
        self.assertEqual("unavailable", ctx.exception.kind)

    def test_uses_the_real_ocr_cli_flags(self) -> None:
        context = ReviewContext(
            run_id="r2",
            repository_root=Path("/repo"),
            files=("src/api.py",),
            background_file="/repo/bg.md",
            from_ref="main",
            to_ref="HEAD",
        )
        result = self._run(_proc(OCR_SUCCESS), context)

        cmd = self.mock_run.call_args_list[0][0][0]
        self.assertEqual(["mock_ocr", "review"], cmd[:2])
        for flag in ("--repo", "--format", "--background-file", "--from", "--to"):
            self.assertIn(flag, cmd)
        self.assertEqual("json", cmd[cmd.index("--format") + 1])
        self.assertNotIn("--files", cmd)
        self.assertNotIn("--context", cmd)
        self.assertNotIn("shell", self.mock_run.call_args_list[0][1])
        self.assertEqual("open-code-review", result.provider)
        self.assertEqual(2, len(result.findings))
        self.assertNotIn("sk-abcdef", result.raw_evidence or "")
        self.assertEqual("mock_ocr", result.command[0])

    def test_environment_is_filtered(self) -> None:
        with patch.dict("os.environ", {"GITHUB_TOKEN": "secret", "OCR_HOME": "/o"}):
            self._run(_proc(OCR_SUCCESS))
        env = self.mock_run.call_args_list[0][1]["env"]
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertEqual("/o", env["OCR_HOME"])

    def test_skipped_output_is_not_a_passed_review(self) -> None:
        result = self._run(_proc(json.dumps({"status": "skipped", "comments": []})))
        self.assertTrue(result.nothing_to_review)
        self.assertFalse(result.passed)

    def test_provider_failures_raise_typed_errors(self) -> None:
        cases: list[tuple[MagicMock | Exception, str]] = [
            (subprocess.TimeoutExpired(cmd="mock_ocr", timeout=5), "timeout"),
            (_proc(returncode=2, stderr="boom"), "exit"),  # non-zero exit
            (_proc("<html>"), "parse"),
            (_proc(json.dumps({"status": "success", "comments": {}})), "schema"),
            (
                _proc(json.dumps({"status": "partial", "message": "budget", "comments": []})),
                "incomplete",
            ),
            (_proc("x" * (MAX_OUTPUT_BYTES + 1)), "output-too-large"),
            (OSError("cannot spawn"), "exit"),
        ]
        for outcome, kind in cases:
            with self.subTest(kind=kind), self.assertRaises(ReviewProviderError) as ctx:
                self._run(outcome)
            self.assertEqual(kind, ctx.exception.kind)

    def test_delegate_preview_calls_ocr_and_validates(self) -> None:
        preview = {
            "mode": "workspace",
            "reviewable_files": [{"path": "a.py"}],
            "excluded_files": [],
        }
        with (
            patch("shutil.which", return_value="/bin/mock_ocr"),
            patch("subprocess.run", return_value=_proc(json.dumps(preview))) as mock_run,
        ):
            result = self.provider.delegate_preview(self.context)
        self.assertEqual(preview, result)
        self.assertEqual(["delegate", "preview"], mock_run.call_args[0][0][1:3])
        with (
            patch("shutil.which", return_value="/bin/mock_ocr"),
            patch("subprocess.run", return_value=_proc(json.dumps({"mode": "workspace"}))),
            self.assertRaises(ReviewProviderError),
        ):
            self.provider.delegate_preview(self.context)


class EvidenceIntegrityTests(unittest.TestCase):
    @staticmethod
    def _result() -> ReviewResult:
        finding = NormalizedFinding("f-1", "ocr", "low", "other", "a.py", "msg", 3)
        return ReviewResult(
            "open-code-review", False, (finding,), raw_evidence='{"token": "abcdefghij123"}'
        )

    def test_evidence_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "attempt"
            decision = PolicyEngine().evaluate(self._result().findings)
            write_review_evidence(out, self._result(), decision)
            with self.assertRaises(FileExistsError):
                write_review_evidence(out, self._result(), decision)

    def test_raw_is_redacted_and_kept_apart_and_provider_meta_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "attempt"
            decision = PolicyEngine().evaluate(self._result().findings)
            written = write_review_evidence(out, self._result(), decision, {"attempt": 1})
            self.assertNotIn("abcdefghij123", written["raw"].read_text(encoding="utf-8"))
            meta = json.loads(written["provider"].read_text(encoding="utf-8"))
            self.assertEqual((1, "open-code-review"), (meta["attempt"], meta["provider"]))
            self.assertEqual([], validate_review_evidence(out))

    def test_validation_reports_schema_problems(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            self.assertEqual(["policy-result.json is missing"], validate_review_evidence(out))
            (out / "policy-result.json").write_text(
                json.dumps({"decision": "continue"}), encoding="utf-8"
            )
            bad = {
                "id": "a",
                "source": "s",
                "file": "f",
                "message": "m",
                "severity": "bad",
                "category": "other",
                "line": 0,
            }
            (out / "findings.json").write_text(json.dumps([bad]), encoding="utf-8")
            problems = validate_review_evidence(out)
            self.assertTrue(any("severity" in p for p in problems))
            self.assertTrue(any("line" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
