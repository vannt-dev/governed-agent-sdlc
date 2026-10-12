from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentkit import antigravity_hook
from agentkit.cli import main
from agentkit.generator import generate_antigravity, generate_opencode, install_scaffold

ROLES = ("architect", "planner", "developer", "reviewer", "qa", "publisher")


def _quiet(arguments: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(arguments)


def _split(text: str) -> tuple[str, str]:
    """The frontmatter and the body of a generated agent file."""
    assert text.startswith("---\n"), text[:40]
    frontmatter, _, body = text[4:].partition("\n---\n")
    return frontmatter, body


class OpenCodeAdapterTests(unittest.TestCase):
    def test_writes_one_subagent_per_role_where_opencode_looks_for_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated = generate_opencode(root)
            agents = root / ".opencode" / "agents"
            self.assertEqual(
                {f"{role}.md" for role in ROLES}, {path.name for path in agents.iterdir()}
            )
            self.assertIn(root / ".opencode" / "plugins" / "governed-guards.js", generated)
            self.assertEqual(len(ROLES) + 1, len(generated))
            for role in ROLES:
                with self.subTest(role=role):
                    frontmatter, body = _split((agents / f"{role}.md").read_text(encoding="utf-8"))
                    self.assertRegex(frontmatter, r"(?m)^description: .*Governed " + role)
                    self.assertIn("mode: subagent", frontmatter)
                    # only the developer changes files; a shell command is always asked about
                    edit = "allow" if role == "developer" else "deny"
                    self.assertIn(f"permission:\n  edit: {edit}\n  bash: ask", frontmatter)
                    self.assertIn("AGENTS.md", body)
                    self.assertIn(f"core/roles/{role}.toml", body)
                    self.assertIn("agentkit.toml", body)
                    self.assertIn(".agent/project.toml", body)

    def test_generation_is_additive_unless_forced_and_writes_nothing_on_a_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(len(ROLES) + 1, len(generate_opencode(root, dry_run=True)))
            self.assertFalse((root / ".opencode").exists())

            generate_opencode(root)
            reviewer = root / ".opencode" / "agents" / "reviewer.md"
            reviewer.write_text("owned by the project\n", encoding="utf-8")
            self.assertEqual([], generate_opencode(root))
            self.assertEqual("owned by the project\n", reviewer.read_text(encoding="utf-8"))
            self.assertEqual(len(ROLES) + 1, len(generate_opencode(root, force=True)))
            self.assertIn("mode: subagent", reviewer.read_text(encoding="utf-8"))

    def test_the_plugin_names_the_guards_of_the_project_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generate_opencode(root)
            plugin = (root / ".opencode" / "plugins" / "governed-guards.js").read_text("utf-8")
            self.assertIn('"tool.execute.before"', plugin)
            self.assertIn("guard_credentials.py", plugin)
            self.assertIn("guard_git.py", plugin)
            self.assertIn("uv", plugin)
            # no path of the machine that generated it
            self.assertNotIn(str(root), plugin)

    @unittest.skipUnless(shutil.which("node") and shutil.which("uv"), "needs node and uv")
    def test_the_plugin_run_by_node_lets_the_guards_decide(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            install_scaffold(root, name="fixture")
            generate_opencode(root)
            plugin = (root / ".opencode" / "plugins" / "governed-guards.js").as_uri()
            driver = Path(temp) / "driver.mjs"
            driver.write_text(
                f"""
import {{ GovernedGuards }} from {json.dumps(plugin)};
// what OpenCode says about where it runs: the first argument, or the project root
const where = process.argv[2] ?? {json.dumps(str(root))};
const hooks = await GovernedGuards({{ directory: where, worktree: where }});
const before = hooks["tool.execute.before"];
const cases = {{
  forcePush: ["bash", {{ command: "git push --force origin main" }}],
  readEnvByCommand: ["bash", {{ command: "cat .env" }}],
  status: ["bash", {{ command: "git status" }}],
  readEnv: ["read", {{ filePath: ".env" }}],
  readReadme: ["read", {{ filePath: "README.md" }}],
  globEnv: ["glob", {{ pattern: "**/.env" }}],
  edit: ["edit", {{ filePath: "src/app.py" }}],
}};
const outcome = {{}};
for (const [name, [tool, args]] of Object.entries(cases)) {{
  try {{ await before({{ tool }}, {{ args }}); outcome[name] = null; }}
  catch (error) {{ outcome[name] = error.message; }}
}}
console.log(JSON.stringify(outcome));
""",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["node", str(driver)], capture_output=True, text=True, timeout=180, check=False
            )
            self.assertEqual(0, result.returncode, result.stderr)
            outcome = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertIn("force push is forbidden", outcome["forcePush"])
            self.assertIn("credential material", outcome["readEnvByCommand"])
            self.assertIn("credential material", outcome["readEnv"])
            self.assertIn("credential material", outcome["globEnv"])
            self.assertIsNone(outcome["status"])
            self.assertIsNone(outcome["readReadme"])
            # a role's write scope is Claude Code's guard; here it is the agent's own permission
            self.assertIsNone(outcome["edit"])

            # outside a git repository OpenCode names `/` as the worktree, and it may be started
            # in a subfolder: the plugin still finds the guards, by its own place in the project
            for where in ("/", str(root / "core")):
                with self.subTest(where=where):
                    moved = subprocess.run(
                        ["node", str(driver), where],
                        capture_output=True,
                        text=True,
                        timeout=180,
                        check=False,
                    )
                    self.assertEqual(0, moved.returncode, moved.stderr)
                    elsewhere = json.loads(moved.stdout.strip().splitlines()[-1])
                    self.assertIn("force push is forbidden", elsewhere["forcePush"])
                    self.assertIsNone(elsewhere["status"])

            # the guards gone: a call that would have been checked is refused, not waved through
            shutil.rmtree(root / "hooks")
            again = subprocess.run(
                ["node", str(driver)], capture_output=True, text=True, timeout=180, check=False
            )
            missing = json.loads(again.stdout.strip().splitlines()[-1])
            self.assertIn("guard", missing["status"])
            self.assertIsNone(missing["edit"])


class AntigravityAdapterTests(unittest.TestCase):
    def test_writes_one_agent_per_role_and_one_hook_where_antigravity_looks_for_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated = generate_antigravity(root)
            agents = root / ".agents" / "agents"
            self.assertEqual(set(ROLES), {path.name for path in agents.iterdir()})
            self.assertEqual(len(ROLES) + 2, len(generated))
            for role in ROLES:
                with self.subTest(role=role):
                    # one folder per agent, named after it, holding agent.md
                    text = (agents / role / "agent.md").read_text(encoding="utf-8")
                    frontmatter, body = _split(text)
                    self.assertIn(f"name: {role}\n", frontmatter + "\n")
                    self.assertRegex(frontmatter, r"(?m)^description: .+")
                    self.assertIn(f"core/roles/{role}.toml", body)
                    self.assertIn("AGENTS.md", body)

            hooks = json.loads((root / ".agents" / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(["governed-agent-sdlc"], list(hooks))
            (entry,) = hooks["governed-agent-sdlc"]["PreToolUse"]
            for tool in ("run_command", "view_file", "find_by_name", "grep_search"):
                self.assertIn(tool, entry["matcher"].split("|"))
            (handler,) = entry["hooks"]
            self.assertEqual("command", handler["type"])
            # Antigravity starts a hook in the folder of its hooks.json, which is `.agents/`
            self.assertEqual(
                "uv run --no-project python hooks/governed_guard.py", handler["command"]
            )
            self.assertNotIn(str(root), handler["command"])
            # seconds, as Antigravity counts a hook's timeout: room for the hook's own budget and
            # for the interpreter to start, so the hook answers before it is cut off
            self.assertGreaterEqual(handler["timeout"], antigravity_hook.BUDGET_SECONDS + 10)
            # and the budget covers every guard a command is shown to, at its own limit
            slowest = len(antigravity_hook.COMMAND_GUARDS) * antigravity_hook.GUARD_TIMEOUT_SECONDS
            self.assertGreaterEqual(antigravity_hook.BUDGET_SECONDS, slowest)
            self.assertTrue((root / ".agents" / "hooks" / "governed_guard.py").is_file())

    def test_generation_is_additive_unless_forced_and_writes_nothing_on_a_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(len(ROLES) + 2, len(generate_antigravity(root, dry_run=True)))
            self.assertFalse((root / ".agents").exists())

            generate_antigravity(root)
            hooks = root / ".agents" / "hooks.json"
            hooks.write_text("{}\n", encoding="utf-8")
            self.assertEqual([], generate_antigravity(root))
            self.assertEqual("{}\n", hooks.read_text(encoding="utf-8"))
            self.assertEqual(len(ROLES) + 2, len(generate_antigravity(root, force=True)))
            self.assertIn("PreToolUse", hooks.read_text(encoding="utf-8"))

    def _decide(self, root: Path, payload: object, *, cwd: Path | None = None) -> dict | None:
        """What the generated hook answers Antigravity for one tool call, or None for no answer."""
        result = subprocess.run(
            [sys.executable, str(root / ".agents" / "hooks" / "governed_guard.py")],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=cwd or root,
            timeout=60,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_the_hook_lets_the_guards_decide_and_answers_in_antigravitys_words(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            install_scaffold(root, name="fixture")
            generate_antigravity(root)

            def call(name: str, args: dict) -> dict:
                return {
                    "conversationId": "c-1",
                    "workspacePaths": [str(root)],
                    "stepIdx": 3,
                    "toolCall": {"name": name, "args": args},
                }

            pushed = self._decide(
                root,
                call(
                    "run_command", {"CommandLine": "git push --force origin main", "Cwd": str(root)}
                ),
            )
            self.assertEqual("deny", pushed["decision"])
            self.assertIn("force push is forbidden", pushed["reason"])
            self.assertNotIn("BLOCKED", pushed["reason"])

            read = self._decide(root, call("run_command", {"CommandLine": "cat .env"}))
            self.assertEqual("deny", read["decision"])
            self.assertIn("credential material", read["reason"])

            viewed = self._decide(root, call("view_file", {"AbsolutePath": str(root / ".env")}))
            self.assertEqual("deny", viewed["decision"])
            searched = self._decide(
                root,
                call("grep_search", {"Query": "token", "SearchPath": str(root / ".env.local")}),
            )
            self.assertEqual("deny", searched["decision"])

            # nothing to object to: no answer, so Antigravity's own permission flow goes on
            self.assertIsNone(
                self._decide(root, call("run_command", {"CommandLine": "git status"}))
            )
            self.assertIsNone(self._decide(root, call("view_file", {"AbsolutePath": "README.md"})))
            # wherever Antigravity starts the hook from, it finds the project by its own place in it
            elsewhere = self._decide(
                root,
                call("run_command", {"CommandLine": "git push -f origin main"}),
                cwd=Path(temp),
            )
            self.assertEqual("deny", elsewhere["decision"])

    def test_name_patterns_given_to_the_search_tools_are_shown_to_the_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            install_scaffold(root, name="fixture")
            generate_antigravity(root)

            def decide(name: str, args: dict) -> dict | None:
                return self._decide(root, {"toolCall": {"name": name, "args": args}})

            # the hook goes by what an argument looks like, not by its name
            folder = str(root)
            for pattern in ("*.env*", ".env", "id_rsa"):
                with self.subTest(find=pattern):
                    found = decide("find_by_name", {"SearchDirectory": folder, "Pattern": pattern})
                    self.assertEqual("deny", found["decision"])
            self.assertIsNone(
                decide("find_by_name", {"SearchDirectory": folder, "Pattern": "*.py"})
            )

            # a list is a list of file patterns; the text searched for is not a target
            narrowed = {"SearchPath": folder, "Query": "token", "Includes": ["*.md", "*.env"]}
            self.assertEqual("deny", decide("grep_search", narrowed)["decision"])
            self.assertIsNone(decide("grep_search", {"SearchPath": folder, "Query": "secret"}))
            self.assertIsNone(
                decide("grep_search", {"SearchPath": folder, "Query": "x", "Includes": ["*.md"]})
            )

    def test_the_labels_antigravity_adds_to_a_call_are_not_taken_for_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            install_scaffold(root, name="fixture")
            generate_antigravity(root)
            # as Antigravity 1.2.9 sends a file call: the target, and two lines of description
            labelled = {
                "AbsolutePath": str(root / "README.md"),
                "toolAction": "Viewing file",
                "toolSummary": "Compare with docs/secrets",
            }
            self.assertIsNone(
                self._decide(root, {"toolCall": {"name": "view_file", "args": labelled}})
            )
            labelled["AbsolutePath"] = str(root / "docs" / "secrets" / "key.txt")
            answer = self._decide(root, {"toolCall": {"name": "view_file", "args": labelled}})
            self.assertEqual("deny", answer["decision"])

    @unittest.skipUnless(shutil.which("uv"), "needs uv")
    def test_the_hook_command_runs_from_the_folder_antigravity_starts_it_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            install_scaffold(root, name="fixture")
            generate_antigravity(root)
            hooks = json.loads((root / ".agents" / "hooks.json").read_text(encoding="utf-8"))
            command = hooks["governed-agent-sdlc"]["PreToolUse"][0]["hooks"][0]["command"]
            call = {"name": "run_command", "args": {"CommandLine": "cat .env", "Cwd": str(root)}}
            result = subprocess.run(
                command,
                shell=True,
                input=json.dumps({"toolCall": call, "workspacePaths": [str(root)]}),
                capture_output=True,
                text=True,
                cwd=root / ".agents",
                timeout=120,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("deny", json.loads(result.stdout)["decision"])

    def test_guards_that_take_too_long_are_a_refusal_not_a_silence(self) -> None:
        clock = [100.0]

        def slow_guard(guard: str, request: dict, *, timeout: float) -> None:
            self.assertLessEqual(timeout, antigravity_hook.GUARD_TIMEOUT_SECONDS)
            clock[0] += timeout
            return None

        call = {"name": "find_by_name", "args": {"A": "one", "B": "two", "C": "three", "D": "four"}}
        with (
            mock.patch.object(antigravity_hook, "ask", side_effect=slow_guard) as asked,
            mock.patch.object(antigravity_hook.time, "monotonic", side_effect=lambda: clock[0]),
        ):
            reason = antigravity_hook.decide(json.dumps({"toolCall": call}))
        self.assertIn("did not answer in time", reason)
        # it stopped asking once the budget was spent
        self.assertLess(asked.call_count, 4)
        self.assertLessEqual(clock[0] - 100.0, antigravity_hook.BUDGET_SECONDS)

    def test_the_hook_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            install_scaffold(root, name="fixture")
            generate_antigravity(root)
            for payload in (
                "not json",
                "[]",
                {"toolCall": "run_command"},
                {"toolCall": {"args": {}}},
            ):
                with self.subTest(payload=payload):
                    answer = self._decide(root, payload)
                    self.assertEqual("deny", answer["decision"])
                    self.assertIn("hook input", answer["reason"])
            # the guards gone: refused, with what to do about it
            shutil.rmtree(root / "hooks")
            answer = self._decide(
                root, {"toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}}}
            )
            self.assertEqual("deny", answer["decision"])
            self.assertIn("agentkit update-hooks", answer["reason"])


class AdapterCommandTests(unittest.TestCase):
    def test_generate_and_init_know_the_new_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for adapter, marker in (
                ("opencode", ".opencode/agents/reviewer.md"),
                ("antigravity", ".agents/agents/reviewer/agent.md"),
            ):
                with self.subTest(adapter=adapter):
                    project = Path(temp) / f"init-{adapter}"
                    self.assertEqual(0, _quiet(["init", str(project), "--adapter", adapter]))
                    self.assertTrue((project / marker).is_file())
                    self.assertTrue((project / "hooks" / "guard_git.py").is_file())
                    self.assertEqual(0, _quiet(["validate", str(project)]))

                    later = Path(temp) / f"generate-{adapter}"
                    self.assertEqual(0, _quiet(["init", str(later), "--adapter", "none"]))
                    self.assertFalse((later / marker).exists())
                    self.assertEqual(0, _quiet(["generate", adapter, str(later), "--dry-run"]))
                    self.assertFalse((later / marker).exists())
                    self.assertEqual(0, _quiet(["generate", adapter, str(later)]))
                    self.assertTrue((later / marker).is_file())

    def test_a_manifest_may_name_the_new_adapters_as_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "named"
            self.assertEqual(0, _quiet(["init", str(project), "--adapter", "opencode"]))
            manifest = project / ".agent" / "project.toml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    'profiles = ["generic"]', 'profiles = ["generic", "opencode", "antigravity"]'
                ),
                encoding="utf-8",
            )
            self.assertEqual(0, _quiet(["validate", str(project)]))


if __name__ == "__main__":
    unittest.main()
