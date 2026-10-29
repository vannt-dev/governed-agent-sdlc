from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agentkit.cli import main

RECORD = Path(".agent") / "generated.json"


def run(*argv: str) -> tuple[int, str]:
    output = io.StringIO()
    with redirect_stdout(output):
        result = main(list(argv))
    return result, output.getvalue()


def doctor_json(project: Path) -> tuple[int, dict[str, object]]:
    result, output = run("doctor", str(project), "--format", "json")
    return result, json.loads(output)


def statuses(report: dict[str, object]) -> dict[str, str]:
    generated = report["generated"]
    assert isinstance(generated, dict)
    return {item["path"]: item["status"] for item in generated["files"]}


def make_outdated(project: Path, relative: str) -> None:
    """Rewrite a generated file and its record as an older version would have left them."""
    path = project / relative
    path.write_text(path.read_text(encoding="utf-8") + "# older release\n", encoding="utf-8")
    record = json.loads((project / RECORD).read_text(encoding="utf-8"))
    from agentkit.generator import content_digest

    record["files"][relative]["sha256"] = content_digest(path.read_bytes())
    record["files"][relative]["agentkit"] = "0.0.1"
    (project / RECORD).write_text(json.dumps(record), encoding="utf-8")


class GeneratedRecordTests(unittest.TestCase):
    def test_init_and_generate_record_what_they_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.assertEqual(0, run("init", str(project), "--adapter", "claude-code")[0])
            self.assertEqual(0, run("generate", "codex", str(project))[0])
            files = json.loads((project / RECORD).read_text(encoding="utf-8"))["files"]
            self.assertIn("hooks/guard_git.py", files)
            self.assertIn(".claude/settings.json", files)
            self.assertIn(".codex/hooks/pre_tool_use.py", files)

    def test_dry_run_writes_no_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "none")
            (project / RECORD).unlink()
            run("generate", "opencode", str(project), "--dry-run")
            self.assertFalse((project / RECORD).exists())


class DoctorGeneratedFilesTests(unittest.TestCase):
    def test_fresh_project_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "antigravity")
            result, report = doctor_json(project)
            self.assertEqual(0, result)
            self.assertTrue(report["ok"])
            found = statuses(report)
            self.assertEqual({"current"}, set(found.values()))
            self.assertIn(".agents/hooks/governed_guard.py", found)
            self.assertNotIn(".claude/settings.json", found)

    def test_outdated_file_fails_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "claude-code")
            make_outdated(project, ".claude/settings.json")
            result, report = doctor_json(project)
            self.assertEqual(1, result)
            self.assertFalse(report["ok"])
            self.assertEqual("outdated", statuses(report)[".claude/settings.json"])

            result, text = run("doctor", str(project))
            self.assertEqual(1, result)
            self.assertIn("outdated", text)
            self.assertIn("agentkit upgrade", text)

    def test_missing_file_of_an_adapter_in_use_fails_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "codex")
            (project / ".codex" / "agents" / "qa.toml").unlink()
            result, report = doctor_json(project)
            self.assertEqual(1, result)
            self.assertEqual("missing", statuses(report)[".codex/agents/qa.toml"])

    def test_removed_adapter_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "codex")
            shutil.rmtree(project / ".codex")
            result, report = doctor_json(project)
            self.assertEqual(0, result)
            self.assertFalse([path for path in statuses(report) if path.startswith(".codex/")])

    def test_hand_edited_file_warns_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "claude-code")
            agent = project / ".claude" / "agents" / "qa.md"
            agent.write_text(agent.read_text(encoding="utf-8") + "Our own note.\n", "utf-8")
            result, report = doctor_json(project)
            self.assertEqual(0, result)
            self.assertEqual("modified", statuses(report)[".claude/agents/qa.md"])

    def test_unrecorded_differing_file_warns_without_failing(self) -> None:
        # a project generated before the record existed cannot tell old output from an edit
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "claude-code")
            (project / RECORD).unlink()
            guard = project / "hooks" / "guard_git.py"
            guard.write_text("# an older guard\n", encoding="utf-8")
            result, report = doctor_json(project)
            self.assertEqual(0, result)
            self.assertTrue(report["ok"])
            self.assertEqual(0, report["generated"]["problems"])  # type: ignore[index]
            found = statuses(report)
            self.assertEqual("unknown", found["hooks/guard_git.py"])
            self.assertEqual("current", found["hooks/guard_role_gate.py"])

            result, text = run("doctor", str(project))
            self.assertEqual(0, result)
            self.assertIn("UNKNOWN: hooks/guard_git.py", text)
            self.assertIn("agentkit upgrade --force", text)

    def test_unknown_file_does_not_hide_an_outdated_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "claude-code")
            make_outdated(project, ".claude/settings.json")
            agent = project / ".claude" / "agents" / "qa.md"
            agent.write_text("old\n", encoding="utf-8")
            record = json.loads((project / RECORD).read_text(encoding="utf-8"))
            del record["files"][".claude/agents/qa.md"]
            (project / RECORD).write_text(json.dumps(record), encoding="utf-8")
            result, report = doctor_json(project)
            self.assertEqual(1, result)
            self.assertEqual(1, report["generated"]["problems"])  # type: ignore[index]
            self.assertEqual("unknown", statuses(report)[".claude/agents/qa.md"])

    def test_line_endings_do_not_count_as_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "claude-code")
            settings = project / ".claude" / "settings.json"
            settings.write_bytes(settings.read_bytes().replace(b"\n", b"\r\n"))
            result, report = doctor_json(project)
            self.assertEqual(0, result)
            self.assertEqual("current", statuses(report)[".claude/settings.json"])

    def test_doctor_outside_a_project_still_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result, report = doctor_json(Path(temp))
            self.assertIn("version", report)
            self.assertEqual([], report["generated"]["files"])  # type: ignore[index]
            del result


class UpgradeTests(unittest.TestCase):
    def test_upgrade_rewrites_outdated_and_keeps_hand_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "claude-code")
            make_outdated(project, ".claude/settings.json")
            make_outdated(project, "hooks/guard_git.py")
            (project / ".claude" / "agents" / "planner.md").unlink()
            agent = project / ".claude" / "agents" / "qa.md"
            edited = agent.read_text(encoding="utf-8") + "Our own note.\n"
            agent.write_text(edited, encoding="utf-8")

            result, output = run("upgrade", str(project), "--format", "json")
            self.assertEqual(0, result)
            changes = json.loads(output)
            self.assertEqual(
                [".claude/settings.json", "hooks/guard_git.py"], sorted(changes["updated"])
            )
            self.assertEqual([".claude/agents/planner.md"], changes["added"])
            self.assertEqual([".claude/agents/qa.md"], changes["kept"])
            self.assertEqual(edited, agent.read_text(encoding="utf-8"))
            self.assertNotIn("older release", (project / "hooks" / "guard_git.py").read_text())

            result, report = doctor_json(project)
            self.assertEqual(0, result)
            self.assertEqual("modified", statuses(report)[".claude/agents/qa.md"])

    def test_upgrade_text_names_each_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "claude-code")
            make_outdated(project, ".claude/settings.json")
            (project / ".claude" / "agents" / "planner.md").unlink()
            agent = project / ".claude" / "agents" / "qa.md"
            agent.write_text(agent.read_text(encoding="utf-8") + "Our own note.\n", "utf-8")

            output = run("upgrade", str(project), "--dry-run")[1]
            self.assertIn("Would add .claude/agents/planner.md", output)
            self.assertIn("Would keep .claude/agents/qa.md", output)
            output = run("upgrade", str(project))[1]
            self.assertIn("Added .claude/agents/planner.md", output)
            self.assertIn("Updated .claude/settings.json", output)
            self.assertIn("Kept .claude/agents/qa.md", output)
            self.assertIn("1 added, 1 updated, 1 kept", output)

    def test_force_overwrites_hand_edits_and_unknown_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "claude-code")
            (project / RECORD).unlink()
            agent = project / ".claude" / "agents" / "qa.md"
            agent.write_text("old\n", encoding="utf-8")

            result, output = run("upgrade", str(project))
            self.assertEqual(0, result)
            self.assertIn(".claude/agents/qa.md", output)
            self.assertEqual("old\n", agent.read_text(encoding="utf-8"))
            result, report = doctor_json(project)
            self.assertEqual(0, result)
            self.assertEqual("unknown", statuses(report)[".claude/agents/qa.md"])

            result, output = run("upgrade", str(project), "--force")
            self.assertEqual(0, result)
            self.assertIn("Updated .claude/agents/qa.md", output)
            self.assertNotEqual("old\n", agent.read_text(encoding="utf-8"))
            result, report = doctor_json(project)
            self.assertEqual(0, result)
            # files that already matched are adopted into the record
            record = json.loads((project / RECORD).read_text(encoding="utf-8"))["files"]
            self.assertIn(".claude/agents/architect.md", record)

    def test_dry_run_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "opencode")
            make_outdated(project, ".opencode/plugins/governed-guards.js")
            before = (project / ".opencode" / "plugins" / "governed-guards.js").read_bytes()
            record = (project / RECORD).read_bytes()
            result, output = run("upgrade", str(project), "--dry-run")
            self.assertEqual(0, result)
            self.assertIn("Would update .opencode/plugins/governed-guards.js", output)
            after = (project / ".opencode" / "plugins" / "governed-guards.js").read_bytes()
            self.assertEqual(before, after)
            self.assertEqual(record, (project / RECORD).read_bytes())

    def test_upgrade_of_a_current_project_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            run("init", str(project), "--adapter", "codex")
            result, output = run("upgrade", str(project))
            self.assertEqual(0, result)
            self.assertIn("up to date", output)


if __name__ == "__main__":
    unittest.main()
