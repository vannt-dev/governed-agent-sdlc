from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentkit.instructions import instruction_findings
from agentkit.validator import validate_project

MANIFEST = """version = 1
[project]
name = "fixture"
topology = "single-repo"
[[repositories]]
id = "root"
path = "."
profiles = ["generic"]
[workflow]
require_spec = true
require_plan = true
require_review = true
require_qa = true
"""

MISSING = "Instruction names a file that does not exist: "


class InstructionReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.write(".agent/project.toml", MANIFEST)

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")

    def messages(self) -> list[str]:
        return [finding.message for finding in instruction_findings(self.root)]

    def test_reports_a_role_file_that_was_deleted(self) -> None:
        self.write(".claude/agents/planner.md", "Read `core/roles/planner.toml` before acting.")
        self.assertEqual([MISSING + "core/roles/planner.toml"], self.messages())
        self.write("core/roles/planner.toml", 'id = "planner"')
        self.assertEqual([], self.messages())

    def test_reports_a_bare_path_in_a_role_definition(self) -> None:
        self.write(
            "core/roles/developer.toml",
            'instructions = "Follow docs/standards/testing.md before editing."',
        )
        self.assertEqual([MISSING + "docs/standards/testing.md"], self.messages())

    def test_either_manifest_location_satisfies_a_reference_to_both(self) -> None:
        self.write("AGENTS.md", "Read `agentkit.toml` or `.agent/project.toml` first.")
        self.assertEqual([], self.messages())

    def test_markdown_link_resolves_from_the_file_that_holds_it(self) -> None:
        self.write(".claude/skills/review/SKILL.md", "See [the checklist](checklist.md).")
        self.assertEqual([MISSING + "checklist.md"], self.messages())
        self.write(".claude/skills/review/checklist.md", "- one")
        self.assertEqual([], self.messages())

    def test_patterns_examples_and_links_elsewhere_are_not_references(self) -> None:
        self.write("core/policies/security.toml", "version = 1")
        lines = [
            "Policies live in `core/policies/*.toml`.",
            "Create `docs/agent/specs/<file>.md` for each change.",
            "See [the guide](https://example.com/guide.md) and [below](#security).",
            "```bash",
            "cat docs/missing/example.md",
            "```",
        ]
        self.write("AGENTS.md", "\n".join(lines))
        self.assertEqual([], self.messages())

    def test_pattern_that_matches_nothing_is_reported(self) -> None:
        self.write("AGENTS.md", "Policies live in `core/policies/*.toml`.")
        self.assertEqual([MISSING + "core/policies/*.toml"], self.messages())

    def test_findings_are_warnings_inside_project_validation(self) -> None:
        self.write("CLAUDE.md", "Read `docs/agent/README.md` first.")
        findings = [f for f in validate_project(self.root) if "does not exist" in f.message]
        self.assertEqual(["warning"], [finding.level for finding in findings])
        self.assertEqual("CLAUDE.md", findings[0].path.name)


if __name__ == "__main__":
    unittest.main()
