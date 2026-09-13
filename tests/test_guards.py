from __future__ import annotations

import importlib.util
import io
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_hook(name: str):
    import sys

    hooks = ROOT / "hooks"
    sys.path.insert(0, str(hooks))
    spec = importlib.util.spec_from_file_location(name, hooks / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


credentials = load_hook("guard_credentials")
git_guard = load_hook("guard_git")
scope_guard = load_hook("guard_role_scope")
common = load_hook("common")


class CredentialGuardTests(unittest.TestCase):
    def test_blocks_env_file(self) -> None:
        data = {"tool_input": {"file_path": "services/api/.env.production"}}
        self.assertIsNotNone(credentials.evaluate(data))

    def test_blocks_credential_helper(self) -> None:
        data = {"tool_input": {"command": "git credential fill"}}
        self.assertIsNotNone(credentials.evaluate(data))

    def test_allows_normal_read(self) -> None:
        data = {"tool_input": {"file_path": "src/app.py"}}
        self.assertIsNone(credentials.evaluate(data))

    def test_blocks_glob_for_env_files(self) -> None:
        data = {"tool_name": "Glob", "tool_input": {"pattern": "**/.env*"}}
        self.assertIsNotNone(credentials.evaluate(data))

    def test_blocks_powershell_environment_dump(self) -> None:
        data = {"tool_input": {"command": "Get-ChildItem Env:"}}
        self.assertIsNotNone(credentials.evaluate(data))


class GitGuardTests(unittest.TestCase):
    def test_blocks_force_push(self) -> None:
        data = {"tool_input": {"command": "git push --force origin feature"}}
        self.assertIsNotNone(git_guard.evaluate(data))

    def test_blocks_direct_main_push(self) -> None:
        data = {"tool_input": {"command": "git push origin main"}}
        self.assertIsNotNone(git_guard.evaluate(data))

    def test_allows_feature_push(self) -> None:
        data = {"tool_input": {"command": "git push origin feature/example"}}
        self.assertIsNone(git_guard.evaluate(data))

    def test_blocks_head_to_main_refspec(self) -> None:
        data = {"tool_input": {"command": "git push origin HEAD:main"}}
        self.assertIsNotNone(git_guard.evaluate(data))

    def test_blocks_full_protected_ref(self) -> None:
        data = {"tool_input": {"command": "git push origin HEAD:refs/heads/main"}}
        self.assertIsNotNone(git_guard.evaluate(data))

    def test_blocks_protected_branch_deletion_refspecs(self) -> None:
        for refspec in (":main", ":refs/heads/main"):
            with self.subTest(refspec=refspec):
                data = {"tool_input": {"command": f"git push origin {refspec}"}}
                self.assertIsNotNone(git_guard.evaluate(data))

    def test_blocks_force_refspec(self) -> None:
        data = {"tool_input": {"command": "git push origin +HEAD:feature/example"}}
        self.assertIsNotNone(git_guard.evaluate(data))


class RoleScopeGuardTests(unittest.TestCase):
    def test_reviewer_cannot_edit_source(self) -> None:
        data = {
            "agent_type": "reviewer",
            "cwd": str(ROOT),
            "tool_input": {"file_path": "src/agentkit/cli.py"},
        }
        self.assertIsNotNone(scope_guard.evaluate(data))

    def test_reviewer_can_write_review(self) -> None:
        data = {
            "agent_type": "reviewer",
            "cwd": str(ROOT),
            "tool_input": {"file_path": "docs/agent/reviews/result.md"},
        }
        self.assertIsNone(scope_guard.evaluate(data))


class HookInputTests(unittest.TestCase):
    def test_malformed_json_is_denied_by_all_guards(self) -> None:
        import sys

        original = sys.stdin
        try:
            sys.stdin = io.StringIO("not-json")
            data = common.read_hook_input()
        finally:
            sys.stdin = original
        self.assertIsNotNone(credentials.evaluate(data))
        self.assertIsNotNone(git_guard.evaluate(data))
        self.assertIsNotNone(scope_guard.evaluate(data))

    def test_missing_or_non_object_tool_input_is_denied_by_all_guards(self) -> None:
        for data in ({}, {"tool_input": "bad"}):
            with self.subTest(data=data):
                self.assertIsNotNone(credentials.evaluate(data))
                self.assertIsNotNone(git_guard.evaluate(data))
                self.assertIsNotNone(scope_guard.evaluate(data))


if __name__ == "__main__":
    unittest.main()
