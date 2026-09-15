from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def load_workflow(name: str) -> dict[str, Any]:
    value = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must contain a YAML mapping")
    return value


class WorkflowStructureChecks(unittest.TestCase):
    def test_all_external_actions_use_immutable_commits(self) -> None:
        for path in WORKFLOWS.glob("*.yml"):
            workflow = load_workflow(path.name)
            for job in workflow.get("jobs", {}).values():
                for step in job.get("steps", []):
                    action = step.get("uses")
                    if action:
                        self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$", path.name)

    def test_validation_has_quality_package_and_browser_jobs(self) -> None:
        workflow = load_workflow("validate.yml")
        self.assertEqual({"test", "quality", "package", "browser"}, set(workflow["jobs"]))
        package_steps = "\n".join(
            str(step.get("run", "")) for step in workflow["jobs"]["package"]["steps"]
        )
        self.assertIn("twine check", package_steps)
        self.assertRegex(package_steps, re.compile(r"pip install dist/\*\.whl"))

    def test_release_permissions_and_provenance_are_explicit(self) -> None:
        release = load_workflow("release.yml")["jobs"]["release"]
        self.assertEqual("write", release["permissions"]["attestations"])
        self.assertEqual("write", release["permissions"]["id-token"])
        actions = [step.get("uses", "") for step in release["steps"]]
        self.assertTrue(
            any(action.startswith("actions/attest-build-provenance@") for action in actions)
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
