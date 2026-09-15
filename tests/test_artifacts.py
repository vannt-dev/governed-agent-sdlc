from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agentkit.artifacts import ArtifactError, create_artifact, parse_artifact, transition


class ArtifactTests(unittest.TestCase):
    def test_create_and_parse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = create_artifact(Path(temp), "spec", "Add Search")
            artifact = parse_artifact(path)
            self.assertEqual("spec", artifact.kind)
            self.assertEqual("draft", artifact.status)

    def test_create_qa_uses_documented_directory_and_heading(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = create_artifact(root, "qa", "Release Candidate")
            self.assertEqual(root / "docs" / "agent" / "qa", path.parent)
            self.assertTrue(parse_artifact(path).body.startswith("\n# QA: Release Candidate\n"))

    def test_approval_requires_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = create_artifact(Path(temp), "spec", "Approval")
            draft = parse_artifact(path)
            waiting = transition(draft, "awaiting_approval")
            with self.assertRaises(ArtifactError):
                transition(waiting, "approved")

    def test_superseded_cannot_be_reactivated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = create_artifact(Path(temp), "spec", "Old Design")
            draft = parse_artifact(path)
            waiting = transition(draft, "awaiting_approval")
            approved = transition(waiting, "approved", approved_by="human", evidence="issue-1")
            superseded = transition(approved, "superseded")
            with self.assertRaises(ArtifactError):
                transition(superseded, "active")

    def test_create_refuses_to_overwrite_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixed = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
            with patch("agentkit.artifacts.datetime") as clock:
                clock.now.return_value = fixed
                create_artifact(root, "spec", "same")
                with self.assertRaisesRegex(ArtifactError, "already exists"):
                    create_artifact(root, "spec", "same")

    def test_parse_rejects_missing_or_invalid_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "bad.md"
            path.write_text("plain markdown\n", encoding="utf-8")
            with self.assertRaisesRegex(ArtifactError, "must start"):
                parse_artifact(path)
            path.write_text("+++\ninvalid = [\n+++\nbody\n", encoding="utf-8")
            with self.assertRaisesRegex(ArtifactError, "invalid TOML"):
                parse_artifact(path)

    def test_invalid_kind_slug_and_transition_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ArtifactError, "Unknown artifact kind"):
                create_artifact(root, "unknown", "item")
            with self.assertRaisesRegex(ArtifactError, "slug cannot be empty"):
                create_artifact(root, "spec", "---")
            artifact = parse_artifact(create_artifact(root, "spec", "valid"))
            with self.assertRaisesRegex(ArtifactError, "Invalid transition"):
                transition(artifact, "completed")


if __name__ == "__main__":
    unittest.main()
