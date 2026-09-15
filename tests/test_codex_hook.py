from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from agentkit.codex_hook import evaluate, main


class CodexHookTests(unittest.TestCase):
    def test_allows_safe_feature_branch_command(self) -> None:
        self.assertIsNone(evaluate({"tool_input": {"command": "git push origin feature/safe"}}))

    def test_blocks_credential_paths_and_environment_dumps(self) -> None:
        self.assertIn("credential material", evaluate({"tool_input": {"path": ".env"}}) or "")
        self.assertIn(
            "credential material",
            evaluate({"tool_input": {"paths": ["src/app.py", "config/secrets/key"]}}) or "",
        )
        self.assertIn(
            "credential material",
            evaluate({"tool_input": {"command": "Get-Content config/.env.local"}}) or "",
        )
        self.assertIn(
            "credential stores",
            evaluate({"tool_input": {"command": "Get-ChildItem Env:"}}) or "",
        )
        self.assertIn(
            "potential secrets",
            evaluate({"tool_input": {"command": "echo api_key=$value"}}) or "",
        )

    def test_blocks_unsafe_git_commands(self) -> None:
        self.assertIn(
            "force push",
            evaluate({"tool_input": {"command": "git push --force origin feature"}}) or "",
        )
        self.assertIn(
            "force push",
            evaluate({"tool_input": {"command": "git push origin +feature:feature"}}) or "",
        )
        self.assertIn(
            "protected branch",
            evaluate({"tool_input": {"command": "git push origin main"}}) or "",
        )
        self.assertIn(
            "destructive git",
            evaluate({"tool_input": {"command": "git reset --hard HEAD~1"}}) or "",
        )

    def test_rejects_malformed_tool_input(self) -> None:
        self.assertIn("tool_input", evaluate({}) or "")

    def test_main_returns_stable_hook_exit_codes(self) -> None:
        for payload, expected in (
            ("not-json", 2),
            ("[]", 2),
            ('{"tool_input": {"command": "git push origin main"}}', 2),
            ('{"tool_input": {"command": "git status"}}', 0),
        ):
            with (
                patch("sys.stdin", io.StringIO(payload)),
                redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(expected, main())


if __name__ == "__main__":
    unittest.main()
