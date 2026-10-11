from __future__ import annotations

import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

from agentkit.codex_hook import evaluate as codex_evaluate

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


# Commands that only mention a credential rule: nothing here reads a secret.
CREDENTIAL_ALLOWED_COMMANDS = (
    'git commit -m "document env vars"',
    "uv run --env-file x pytest",
    "npx cross-env NODE_ENV=test vitest run",
    "env NODE_ENV=test npm test",
    "/usr/bin/env python3 scripts/build.py",
    'grep -rn "process.env" src/',
    'echo "token refresh done"',
    "printf 'password policy updated\\n'",
    "cat <<'EOF' > notes.md\nnever run git credential fill or printenv\nEOF",
    "cat <<EOF > notes.md\nagents may not dump the env\nEOF",
    "cat <<'END-NOTE' > notes.md\nprintenv is refused\nEND-NOTE",
    'cat <<"EOF" > notes.md\nthe guard refuses $(printenv)\nEOF',
    "cat <<\\EOF > notes.md\nthe guard refuses $(printenv)\nEOF",
)

# Commands that reach a secret, in every form the looser matching must still refuse.
CREDENTIAL_DENIED_COMMANDS = (
    "env",
    "env | grep TOKEN",
    "env > dump.txt",
    "env -0",
    "env FOO=1",
    "sudo env",
    "printenv",
    "printenv GITHUB_TOKEN",
    'echo "$(env)"',
    "x=`printenv`",
    'bash -c "env"',
    "git status; env",
    "git status\nenv",
    "cat .env",
    "cat ./.env",
    "source .env",
    "Get-Content config/.env.local",
    "type C:\\proj\\.env",
    "docker run --env-file=.env image",
    "cat ~/.netrc",
    "git credential fill",
    "Get-ChildItem Env:",
    "gci env:",
    "echo api_key=$value",
    'echo "token: $GITHUB_TOKEN"',
    "Write-Output $env:NPM_TOKEN",
    "cat <<EOF\n$(printenv)\nEOF",
    'python -c "print(1 << n)"\ncat .env\nn',
    'node -e "console.log(process.env)"',
    'python -c "import os; print(os.environ)"',
)


class CredentialCommandPrecisionTests(unittest.TestCase):
    """The Claude Code hook and the Codex hook apply one policy; both must agree."""

    evaluators = (("claude", credentials.evaluate), ("codex", codex_evaluate))

    def test_commands_that_only_mention_a_rule_are_allowed(self) -> None:
        for name, evaluate in self.evaluators:
            for command in CREDENTIAL_ALLOWED_COMMANDS:
                with self.subTest(hook=name, command=command):
                    self.assertIsNone(evaluate({"tool_input": {"command": command}}))

    def test_both_hooks_carry_the_same_rule_text(self) -> None:
        def rules(path: Path) -> str:
            text = path.read_text(encoding="utf-8")
            return text[text.index("SECRET_PATH = re.compile(") : text.index("def command_reason(")]

        self.assertEqual(
            rules(ROOT / "hooks" / "guard_credentials.py"),
            rules(ROOT / "src" / "agentkit" / "codex_hook.py"),
        )

    def test_commands_that_reach_a_secret_are_denied(self) -> None:
        for name, evaluate in self.evaluators:
            for command in CREDENTIAL_DENIED_COMMANDS:
                with self.subTest(hook=name, command=command):
                    self.assertIsNotNone(evaluate({"tool_input": {"command": command}}))


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


TASK_FILE = """+++
schema_version = 1
id = "TASK-20261011000000-fixture"
kind = "task"
status = "active"
task_level = "medium"
parent = "PLAN-20261011000000-fixture"
repositories = []
protected_areas = []
+++

# Task

## Goal

Ship the fixture.

## Write scope

- src/fixture.py

## Completion evidence

Not started.
"""


class CompletionEvidenceScopeTests(unittest.TestCase):
    """Roles that do not own a task file may fill in its completion evidence and nothing else."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.task = self.root / "docs" / "agent" / "tasks" / "fixture.md"
        self.task.parent.mkdir(parents=True)
        self.task.write_text(TASK_FILE, encoding="utf-8")

    def edit(self, role: str, old: str, new: str) -> str | None:
        data = {
            "agent_type": role,
            "cwd": str(self.root),
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "docs/agent/tasks/fixture.md",
                "old_string": old,
                "new_string": new,
            },
        }
        return scope_guard.evaluate(data)

    def write(self, role: str, relative: str, content: str) -> str | None:
        data = {
            "agent_type": role,
            "cwd": str(self.root),
            "tool_name": "Write",
            "tool_input": {"file_path": relative, "content": content},
        }
        return scope_guard.evaluate(data)

    def test_developer_can_record_completion_evidence(self) -> None:
        self.assertIsNone(self.edit("developer", "Not started.", "pytest: 12 passed."))

    def test_reviewer_and_qa_can_record_completion_evidence(self) -> None:
        for role in ("reviewer", "qa"):
            with self.subTest(role=role):
                self.assertIsNone(self.edit(role, "Not started.", "Checked against the diff."))

    def test_developer_cannot_widen_the_write_scope(self) -> None:
        reason = self.edit("developer", "- src/fixture.py", "- src/fixture.py\n- src/other.py")
        self.assertIn("completion evidence", reason or "")

    def test_developer_cannot_change_the_status(self) -> None:
        reason = self.edit("developer", 'status = "active"', 'status = "completed"')
        self.assertIn("completion evidence", reason or "")

    def test_whole_file_write_is_judged_like_an_edit(self) -> None:
        evidence_only = TASK_FILE.replace("Not started.", "pytest: 12 passed.")
        self.assertIsNone(self.write("developer", "docs/agent/tasks/fixture.md", evidence_only))
        rescoped = evidence_only.replace("- src/fixture.py", "- src/**")
        self.assertIsNotNone(self.write("developer", "docs/agent/tasks/fixture.md", rescoped))

    def test_developer_cannot_create_a_task_file(self) -> None:
        self.assertIsNotNone(self.write("developer", "docs/agent/tasks/new.md", TASK_FILE))

    def test_developer_cannot_write_other_artifacts(self) -> None:
        self.assertIsNotNone(self.write("developer", "docs/agent/specs/fixture.md", "# Spec\n"))

    def test_developer_can_write_source(self) -> None:
        self.assertIsNone(self.write("developer", "src/fixture.py", "VALUE = 1\n"))

    def test_edit_that_does_not_apply_is_refused(self) -> None:
        self.assertIsNotNone(self.edit("developer", "text that is not in the file", "anything"))

    def test_planner_still_owns_the_whole_task_file(self) -> None:
        self.assertIsNone(self.edit("planner", "- src/fixture.py", "- src/**"))

    def test_fenced_output_with_hash_lines_stays_inside_the_evidence(self) -> None:
        evidence = "Ran the suite:\n\n```text\n# 12 passed\n```"
        self.assertIsNone(self.edit("developer", "Not started.", evidence))

    def test_plain_evidence_heading_is_accepted(self) -> None:
        plain = TASK_FILE.replace("## Completion evidence", "## Evidence")
        self.task.write_text(plain, encoding="utf-8")
        self.assertIsNone(self.edit("developer", "Not started.", "pytest: 12 passed."))

    def test_task_without_an_evidence_section_is_refused(self) -> None:
        self.task.write_text(TASK_FILE.split("## Completion evidence")[0], encoding="utf-8")
        self.assertIsNotNone(self.edit("developer", "Ship the fixture.", "Ship it."))

    def test_section_after_the_evidence_is_still_protected(self) -> None:
        self.task.write_text(TASK_FILE + "\n## Notes\n\nOwner notes.\n", encoding="utf-8")
        self.assertIsNotNone(self.edit("developer", "Owner notes.", "Changed."))
        self.assertIsNone(self.edit("developer", "Not started.", "pytest: 12 passed."))


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
