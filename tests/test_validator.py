from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentkit.artifacts import Artifact, create_artifact, parse_artifact, serialize_artifact
from agentkit.validator import validate_project


MANIFEST = '''version = 1
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
'''


class ValidatorTests(unittest.TestCase):
    def write_artifact(self, root: Path, name: str, metadata: dict) -> Path:
        path = root / "docs" / "agent" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        artifact = Artifact(path, metadata, "\n# Fixture\n")
        path.write_text(serialize_artifact(artifact), encoding="utf-8")
        return path

    def test_valid_empty_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agentkit.toml").write_text(MANIFEST, encoding="utf-8")
            self.assertFalse([f for f in validate_project(root) if f.level == "error"])

    def test_rejects_unknown_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agentkit.toml").write_text(MANIFEST, encoding="utf-8")
            path = create_artifact(root, "task", "unknown repo")
            artifact = parse_artifact(path)
            metadata = dict(artifact.metadata)
            metadata["repositories"] = ["missing"]
            path.write_text(serialize_artifact(Artifact(path, metadata, artifact.body)), encoding="utf-8")
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertTrue(any("Unknown repositories" in message for message in errors))

    def test_rejects_unsupported_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = MANIFEST.replace("version = 1", "version = 2")
            (root / "agentkit.toml").write_text(manifest, encoding="utf-8")
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertIn("version must be 1", errors)

    def test_rejects_boolean_manifest_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = MANIFEST.replace("version = 1", "version = true")
            (root / "agentkit.toml").write_text(manifest, encoding="utf-8")
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertIn("version must be 1", errors)

    def test_rejects_invalid_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = MANIFEST.replace('topology = "single-repo"', 'topology = "invalid"')
            (root / "agentkit.toml").write_text(manifest, encoding="utf-8")
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertTrue(any("topology" in message for message in errors))

    def test_rejects_unknown_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = MANIFEST.replace('profiles = ["generic"]', 'profiles = ["missing"]')
            (root / "agentkit.toml").write_text(manifest, encoding="utf-8")
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertEqual(["Unknown profiles: missing"], errors)

    def test_rejects_missing_workflow_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = MANIFEST.replace("require_plan = true\n", "")
            (root / "agentkit.toml").write_text(manifest, encoding="utf-8")
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertIn("[workflow].require_plan must be a boolean", errors)

    def test_active_artifact_requires_approval_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agentkit.toml").write_text(MANIFEST, encoding="utf-8")
            self.write_artifact(
                root,
                "specs/spec",
                {
                    "schema_version": 1,
                    "id": "SPEC-fixture",
                    "kind": "spec",
                    "status": "active",
                    "task_level": "medium",
                    "repositories": ["root"],
                    "protected_areas": [],
                },
            )
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertTrue(any("Approved artifact lacks" in message for message in errors))

    def test_rejects_boolean_artifact_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agentkit.toml").write_text(MANIFEST, encoding="utf-8")
            path = create_artifact(root, "spec", "boolean version")
            text = path.read_text(encoding="utf-8").replace("schema_version = 1", "schema_version = true")
            path.write_text(text, encoding="utf-8")
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertIn("schema_version must be 1", errors)

    def test_rejects_malformed_optional_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agentkit.toml").write_text(MANIFEST, encoding="utf-8")
            path = create_artifact(root, "spec", "bad approval")
            text = path.read_text(encoding="utf-8").replace(
                "protected_areas = []\n+++",
                'protected_areas = []\n\n[approval]\nunexpected = "value"\n+++',
            )
            path.write_text(text, encoding="utf-8")
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertTrue(any("Unknown approval fields" in message for message in errors))
            self.assertTrue(any("Approved artifact lacks" in message for message in errors))

    def test_plan_requires_approved_spec_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agentkit.toml").write_text(MANIFEST, encoding="utf-8")
            self.write_artifact(
                root,
                "plans/plan",
                {
                    "schema_version": 1,
                    "id": "PLAN-fixture",
                    "kind": "plan",
                    "status": "draft",
                    "task_level": "medium",
                    "repositories": ["root"],
                    "protected_areas": [],
                },
            )
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertIn("plan requires a parent spec", errors)

    def test_rejects_wrong_parent_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agentkit.toml").write_text(MANIFEST, encoding="utf-8")
            approval = {
                "approved_by": "human",
                "approved_at": "2026-01-01T00:00:00+00:00",
                "evidence": "issue-1",
            }
            self.write_artifact(
                root,
                "specs/one",
                {
                    "schema_version": 1,
                    "id": "SPEC-one",
                    "kind": "spec",
                    "status": "approved",
                    "task_level": "medium",
                    "repositories": ["root"],
                    "protected_areas": [],
                    "approval": approval,
                },
            )
            self.write_artifact(
                root,
                "tasks/one",
                {
                    "schema_version": 1,
                    "id": "TASK-one",
                    "kind": "task",
                    "status": "draft",
                    "task_level": "medium",
                    "parent": "SPEC-one",
                    "repositories": ["root"],
                    "protected_areas": [],
                },
            )
            errors = [f.message for f in validate_project(root) if f.level == "error"]
            self.assertIn("task parent must be plan: SPEC-one", errors)


if __name__ == "__main__":
    unittest.main()
