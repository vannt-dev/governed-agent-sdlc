from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentkit.artifacts import ArtifactError
from agentkit.cli import _project_artifact_path


class CliTests(unittest.TestCase):
    def test_accepts_artifact_below_project_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "docs" / "agent" / "specs" / "one.md"
            self.assertEqual(path.resolve(), _project_artifact_path(root, str(path)))

    def test_rejects_artifact_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            root = Path(temp)
            path = Path(other) / "outside.md"
            with self.assertRaisesRegex(ArtifactError, "must stay within"):
                _project_artifact_path(root, str(path))

    def test_rejects_non_markdown_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "docs" / "agent" / "specs" / "one.toml"
            with self.assertRaisesRegex(ArtifactError, "Markdown"):
                _project_artifact_path(root, str(path))


if __name__ == "__main__":
    unittest.main()
