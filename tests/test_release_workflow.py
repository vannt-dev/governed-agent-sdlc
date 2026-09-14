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
        self.assertIn("release_tag:", self.content)

    def test_workflow_actions_are_pinned_to_immutable_shas(self) -> None:
        uses = re.findall(r"uses:\s*([^\s#]+)", self.content)
        self.assertGreaterEqual(len(uses), 3)
        for action in uses:
            self.assertRegex(
                action,
                r"@[0-9a-f]{40}$",
                f"Action {action} must be pinned to a 40-character SHA",
            )
        self.assertIn(
            "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33",
            self.content,
        )

    def test_least_privilege_permissions(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.content)
        self.assertIn("contents: write", self.content)
        self.assertIn("id-token: write", self.content)

    def test_build_and_release_commands(self) -> None:
        self.assertIn("python -m build", self.content)
        self.assertIn("gh release create", self.content)
        self.assertIn("pypa/gh-action-pypi-publish@", self.content)

    def test_pypi_publish_is_isolated_from_release_creation(self) -> None:
        self.assertIn("publish-pypi:", self.content)
        self.assertIn(
            "github.event_name == 'workflow_dispatch' && inputs.publish_to_pypi == true",
            self.content,
        )
        self.assertIn(
            "github.event_name == 'push' || inputs.publish_to_pypi != true",
            self.content,
        )

    def test_pypi_publish_uses_protected_environment_and_existing_assets(self) -> None:
        self.assertIn("environment:\n      name: pypi", self.content)
        self.assertIn('gh release download "$RELEASE_TAG"', self.content)
        self.assertIn("governed_agent_sdlc-${version}-py3-none-any.whl", self.content)
        self.assertIn("governed_agent_sdlc-${version}.tar.gz", self.content)

    def test_release_tag_is_validated_before_publication(self) -> None:
        self.assertIn("Invalid release tag", self.content)
        self.assertIn("Tag $RELEASE_TAG does not match package version", self.content)


if __name__ == "__main__":
    unittest.main()
