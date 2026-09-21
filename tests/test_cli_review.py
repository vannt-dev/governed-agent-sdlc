from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agentkit.cli_review import CliReviewProvider
from agentkit.review import OpenCodeReviewProvider, ReviewContext, ReviewProviderError


class CliReviewTests(unittest.TestCase):
    def test_rule_contract_rejects_incomplete_coverage_and_future_versions(self) -> None:
        provider = OpenCodeReviewProvider(executable="fake")
        context = ReviewContext("test", Path.cwd())
        group = {
            "group_id": 1,
            "source": "system",
            "pattern": "*.py",
            "files": ["a.py"],
            "rule": "check",
        }
        with patch.object(
            provider,
            "_run",
            return_value=subprocess.CompletedProcess(
                [], 0, json.dumps({"schema_version": "1", "groups": [group]}), ""
            ),
        ):
            self.assertEqual([group], provider.delegate_rules(context, ["a.py"])["groups"])
            with self.assertRaises(ReviewProviderError):
                provider.delegate_rules(context, ["a.py", "b.py"])
        for doc in (
            {"schema_version": "2", "groups": []},
            {"schema_version": "1", "groups": [None]},
            [],
        ):
            with (
                patch.object(
                    provider,
                    "_run",
                    return_value=subprocess.CompletedProcess([], 0, json.dumps(doc), ""),
                ),
                self.assertRaises(ReviewProviderError),
            ):
                provider.delegate_rules(context, ["a.py"])

    def test_host_cli_gets_bounded_stdin_and_out_of_scope_findings_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            context = ReviewContext("test", Path(temp))
            captured: list[str] = []
            result = {"status": "complete", "comments": []}

            def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if command[0] == "review-cli":
                    captured.append(str(kwargs["input_text"]))
                    return subprocess.CompletedProcess(command, 0, json.dumps(result), "")
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                patch.dict(os.environ, {"AGENTKIT_REVIEW_COMMAND": '["review-cli"]'}),
                patch("agentkit.cli_review.run_bounded", side_effect=run),
                patch.object(
                    OpenCodeReviewProvider,
                    "delegate_preview",
                    return_value={"reviewable_files": [{"path": "a.py"}]},
                ),
                patch.object(
                    OpenCodeReviewProvider,
                    "delegate_rules",
                    return_value={"schema_version": "1", "groups": []},
                ),
            ):
                self.assertTrue(CliReviewProvider().review(context).passed)
                self.assertIn("Do not use tools", captured[0])
                result["comments"] = [{"path": "outside.py", "content": "bad"}]
                with self.assertRaisesRegex(ReviewProviderError, "outside"):
                    CliReviewProvider().review(context)
                with (
                    patch("agentkit.cli_review.MAX_CONTEXT_BYTES", 10),
                    self.assertRaisesRegex(ReviewProviderError, "512 KiB"),
                ):
                    CliReviewProvider().review(context)

    def test_git_failures_become_provider_errors(self) -> None:
        context = ReviewContext("test", Path.cwd())
        for operation in ("diff", "ls-files"):
            for failure, kind in (
                (subprocess.TimeoutExpired("git", 30), "timeout"),
                (OSError("Git unavailable"), "unavailable"),
            ):
                with self.subTest(operation=operation, kind=kind):

                    def run(
                        command: list[str],
                        operation: str = operation,
                        failure: Exception = failure,
                        **kwargs: object,
                    ) -> subprocess.CompletedProcess[str]:
                        if operation in command:
                            raise failure
                        return subprocess.CompletedProcess(command, 0, "", "")

                    with (
                        patch.dict(os.environ, {"AGENTKIT_REVIEW_COMMAND": '["review-cli"]'}),
                        patch("agentkit.cli_review.run_bounded", side_effect=run),
                        patch.object(
                            OpenCodeReviewProvider,
                            "delegate_preview",
                            return_value={"reviewable_files": [{"path": "a.py"}]},
                        ),
                        patch.object(OpenCodeReviewProvider, "delegate_rules", return_value={}),
                        self.assertRaises(ReviewProviderError) as caught,
                    ):
                        CliReviewProvider().review(context)
                    self.assertEqual(kind, caught.exception.kind)

    def test_wildcard_paths_are_literal_for_workspace_range_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()

            def git(*args: str) -> None:
                subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

            def commit() -> None:
                git("add", "app")
                git(
                    "-c",
                    "user.name=Eval",
                    "-c",
                    "user.email=eval@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    "fixture",
                )

            git("init", "-q")
            for name in ("[id]", "i"):
                directory = root / "app" / name
                directory.mkdir(parents=True)
                (directory / "page.py").write_text("value = 1\n", encoding="utf-8")
            commit()
            (root / "app/[id]/page.py").write_text("value = 'selected-marker'\n", encoding="utf-8")
            (root / "app/i/page.py").write_text("value = 'excluded-marker'\n", encoding="utf-8")
            script = (
                "import sys; text=sys.stdin.read(); "
                "assert 'selected-marker' in text and 'excluded-marker' not in text; "
                'print(\'{"status":"complete","comments":[]}\')'
            )
            with (
                patch.dict(
                    os.environ,
                    {"AGENTKIT_REVIEW_COMMAND": json.dumps([sys.executable, "-c", script])},
                ),
                patch.object(
                    OpenCodeReviewProvider,
                    "delegate_preview",
                    return_value={"reviewable_files": [{"path": "app/[id]/page.py"}]},
                ),
                patch.object(OpenCodeReviewProvider, "delegate_rules", return_value={}),
            ):
                context = ReviewContext("test", root)
                self.assertTrue(CliReviewProvider().review(context).passed)
                commit()
                self.assertTrue(CliReviewProvider().review(replace(context, commit="HEAD")).passed)
                self.assertTrue(
                    CliReviewProvider()
                    .review(replace(context, from_ref="HEAD~1", to_ref="HEAD"))
                    .passed
                )


@unittest.skipUnless(os.environ.get("REVIEW_LIVE") == "1", "opt-in live semantic evaluation")
class LiveReviewEvaluation(unittest.TestCase):
    def test_known_bug_and_clean_control(self) -> None:
        """Two calls: detect division by zero, no high false positives on the clean control."""
        with tempfile.TemporaryDirectory(prefix="agentkit-live-") as temp:
            root = Path(temp).resolve()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "-c",
                    "user.name=Eval",
                    "-c",
                    "user.email=eval@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            source = root / "average.py"
            source.write_text(
                "def average(values):\n    if not values:\n        return 0\n"
                "    return sum(values) / len(values)\n",
                encoding="utf-8",
            )
            provider = CliReviewProvider(timeout_seconds=120)
            clean = provider.review(ReviewContext("clean", root))
            self.assertFalse(clean.nothing_to_review)
            self.assertFalse([f for f in clean.findings if f.severity in {"critical", "high"}])
            source.write_text(
                "def average(values):\n    return sum(values) / 0\n", encoding="utf-8"
            )
            buggy = provider.review(ReviewContext("bug", root))
            self.assertTrue(
                [
                    f
                    for f in buggy.findings
                    if f.file == "average.py" and f.category == "correctness"
                ]
            )
            print(
                json.dumps(
                    {
                        "evaluation": "average",
                        "expectedBugDetected": True,
                        "highSeverityFalsePositives": 0,
                        "calls": 2,
                        "timeoutSecondsPerCall": 120,
                    }
                )
            )
