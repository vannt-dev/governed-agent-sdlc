from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from agentkit.artifacts import (
    ARTIFACT_KINDS,
    ArtifactError,
    create_artifact,
    parse_artifact,
    transition,
)


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

    def test_new_task_and_spec_use_the_core_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = parse_artifact(create_artifact(root, "task", "Add Search"))
            self.assertTrue(task.body.startswith("\n# Task: Add Search\n"))
            for section in ("## Write scope", "## Verification", "## Completion evidence"):
                self.assertIn(section, task.body)
            self.assertNotIn("YYYYMMDD", task.body)
            self.assertNotIn("parent", task.metadata)
            spec = parse_artifact(create_artifact(root, "spec", "Add Search"))
            self.assertTrue(spec.body.startswith("\n# Spec: Add Search\n\n## Goal\n"))
            self.assertIn("## Risks and required approvals", spec.body)
            self.assertNotIn("# Specification", spec.body)

    def test_project_template_wins_over_the_packaged_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            template = root / "core" / "templates" / "spec.md"
            template.parent.mkdir(parents=True)
            template.write_text(
                '+++\nkind = "spec"\n+++\n\n# Specification\n\n## Local section\n', encoding="utf-8"
            )
            spec = parse_artifact(create_artifact(root, "spec", "Local"))
            self.assertTrue(spec.body.startswith("\n# Spec: Local\n\n## Local section\n"))
            self.assertNotIn("## Risks and required approvals", spec.body)

    def test_plan_review_and_qa_use_their_templates(self) -> None:
        expected = {
            "plan": ("## Task graph", "## Ordering rationale"),
            "review": ("## Scope reviewed", "## Findings", "## Residual risk"),
            "qa": ("## Environment and subject", "## Unresolved defects"),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for kind, sections in expected.items():
                body = parse_artifact(create_artifact(root, kind, "Check")).body
                for section in sections:
                    self.assertIn(section, body, kind)
                self.assertNotIn("## Confirmed facts", body, kind)

    def test_every_artifact_kind_has_a_packaged_template(self) -> None:
        templates = Path(__file__).resolve().parents[1] / "core" / "templates"
        for kind in ARTIFACT_KINDS:
            text = (templates / f"{kind}.md").read_text(encoding="utf-8")
            self.assertIn(f'kind = "{kind}"', text)
            self.assertIn('status = "draft"', text)

    def test_kind_without_a_template_keeps_the_generic_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bare = Path(temp) / "package"
            (bare / "core").mkdir(parents=True)
            with patch("agentkit.generator.package_root", return_value=bare):
                review = parse_artifact(create_artifact(Path(temp), "review", "Check"))
            self.assertTrue(review.body.startswith("\n# Review: Check\n"))
            self.assertIn("## Evidence", review.body)

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
