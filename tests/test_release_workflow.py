from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


class ReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.content = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(RELEASE_WORKFLOW.is_file(), "release.yml must exist")

    def test_workflow_triggers_on_version_tags_and_dispatch(self) -> None:
        self.assertIn('tags:\n      - "v*"', self.content)
        self.assertIn("workflow_dispatch:", self.content)

    def test_workflow_actions_are_pinned_to_immutable_shas(self) -> None:
        uses = re.findall(r"uses:\s*([^\s#]+)", self.content)
        self.assertGreaterEqual(len(uses), 3)
        for action in uses:
            self.assertRegex(
                action,
                r"@[0-9a-f]{40}$",
                f"Action {action} must be pinned to a 40-character SHA",
            )

    def test_least_privilege_permissions(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.content)
        self.assertIn("contents: write", self.content)
        self.assertIn("id-token: write", self.content)

    def test_build_and_release_commands(self) -> None:
        self.assertIn("python -m build", self.content)
        self.assertIn("gh release create", self.content)
        self.assertIn("pypa/gh-action-pypi-publish@", self.content)


if __name__ == "__main__":
    unittest.main()
