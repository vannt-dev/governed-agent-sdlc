from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_hook(name: str):
    hooks = ROOT / "hooks"
    sys.path.insert(0, str(hooks))
    spec = importlib.util.spec_from_file_location(name, hooks / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


role_gate = load_hook("guard_role_gate")

MANIFEST = """version = 1
[project]
name = "fixture"
topology = "single-repo"
[[repositories]]
id = "root"
path = "."
profiles = ["generic"]
[workflow]
require_spec = {require_spec}
require_plan = true
require_review = true
require_qa = true
"""

DIRECTORIES = {"spec": "specs", "plan": "plans", "task": "tasks", "review": "reviews", "qa": "qa"}


class RoleGateTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.write_manifest()
        policies = self.root / "core" / "policies"
        policies.mkdir(parents=True)
        shutil.copy(ROOT / "core" / "policies" / "workflow.toml", policies / "workflow.toml")

    def write_manifest(self, *, require_spec: bool = True) -> None:
        text = MANIFEST.format(require_spec=str(require_spec).lower())
        (self.root / "agentkit.toml").write_text(text, encoding="utf-8")

    def artifact(self, kind: str, status: str, name: str = "fixture") -> str:
        relative = f"docs/agent/{DIRECTORIES[kind]}/{name}.md"
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'+++\nschema_version = 1\nid = "{kind.upper()}-1-{name}"\nkind = "{kind}"\n'
            f'status = "{status}"\ntask_level = "medium"\n+++\n\n# Fixture\n',
            encoding="utf-8",
        )
        return relative

    def spawn(self, role: str, prompt: str) -> str | None:
        data = {
            "tool_name": "Agent",
            "cwd": str(self.root),
            "tool_input": {"subagent_type": role, "description": "fixture", "prompt": prompt},
        }
        return role_gate.evaluate(data)

    def test_planner_runs_from_an_approved_or_later_spec(self) -> None:
        for status in ("approved", "active", "completed"):
            with self.subTest(status=status):
                spec = self.artifact("spec", status, name=status)
                self.assertIsNone(self.spawn("planner", f"Plan the work in {spec}."))

    def test_planner_is_refused_a_spec_that_has_not_passed_approval(self) -> None:
        for status in ("draft", "awaiting_approval", "superseded", "archived"):
            with self.subTest(status=status):
                spec = self.artifact("spec", status, name=status)
                reason = self.spawn("planner", f"Plan the work in {spec}.")
                self.assertIn(spec, reason or "")
                self.assertIn(status, reason or "")

    def test_one_unapproved_spec_among_several_is_enough_to_refuse(self) -> None:
        approved = self.artifact("spec", "approved", name="ready")
        draft = self.artifact("spec", "draft", name="pending")
        reason = self.spawn("planner", f"Plan {approved} together with {draft}.")
        self.assertIn(draft, reason or "")
        self.assertNotIn(approved, reason or "")

    def test_developer_needs_an_approved_plan_and_an_active_task(self) -> None:
        plan = self.artifact("plan", "approved")
        active = self.artifact("task", "active", name="active")
        self.assertIsNone(self.spawn("developer", f"Implement {active} from {plan}."))
        waiting = self.artifact("task", "approved", name="waiting")
        self.assertIn(waiting, self.spawn("developer", f"Implement {waiting} from {plan}.") or "")

    def test_reviewer_needs_a_completed_task(self) -> None:
        done = self.artifact("task", "completed", name="done")
        self.assertIsNone(self.spawn("reviewer", f"Review {done}."))
        active = self.artifact("task", "active", name="active")
        self.assertIn(active, self.spawn("reviewer", f"Review {active}.") or "")

    def test_qa_needs_a_completed_review(self) -> None:
        done = self.artifact("review", "completed", name="done")
        self.assertIsNone(self.spawn("qa", f"Run QA for {done}."))
        active = self.artifact("review", "active", name="active")
        self.assertIn(active, self.spawn("qa", f"Run QA for {active}.") or "")

    def test_publisher_needs_completed_qa(self) -> None:
        done = self.artifact("qa", "completed", name="done")
        self.assertIsNone(self.spawn("publisher", f"Publish; QA evidence is {done}."))
        active = self.artifact("qa", "active", name="active")
        self.assertIn(active, self.spawn("publisher", f"Publish; QA evidence is {active}.") or "")

    def test_artifacts_the_gate_does_not_cover_are_ignored(self) -> None:
        spec = self.artifact("spec", "approved")
        plan = self.artifact("plan", "draft")
        self.assertIsNone(self.spawn("planner", f"Plan {spec}; write the plan to {plan}."))

    def test_prompt_naming_no_artifact_passes(self) -> None:
        self.assertIsNone(self.spawn("planner", "Plan the checkout work."))

    def test_named_file_that_does_not_exist_yet_passes(self) -> None:
        self.assertIsNone(self.spawn("planner", "Plan docs/agent/specs/not-written-yet.md."))

    def test_other_subagents_are_not_gated(self) -> None:
        spec = self.artifact("spec", "draft")
        self.assertIsNone(self.spawn("general-purpose", f"Summarize {spec}."))
        self.assertIsNone(self.spawn("architect", f"Revise {spec}."))

    def test_plugin_prefixed_role_is_gated(self) -> None:
        spec = self.artifact("spec", "draft")
        self.assertIsNotNone(self.spawn("governed-agent-sdlc:planner", f"Plan {spec}."))

    def test_windows_path_separators_are_understood(self) -> None:
        spec = self.artifact("spec", "draft")
        self.assertIsNotNone(self.spawn("planner", "Plan " + spec.replace("/", "\\") + "."))

    def test_gate_is_skipped_when_the_manifest_does_not_require_a_spec(self) -> None:
        spec = self.artifact("spec", "draft")
        self.write_manifest(require_spec=False)
        self.assertIsNone(self.spawn("planner", f"Plan {spec}."))

    def test_project_without_a_workflow_policy_is_not_gated(self) -> None:
        spec = self.artifact("spec", "draft")
        (self.root / "core" / "policies" / "workflow.toml").unlink()
        self.assertIsNone(self.spawn("planner", f"Plan {spec}."))

    def test_unreadable_policy_or_artifact_is_refused(self) -> None:
        spec = self.artifact("spec", "approved")
        (self.root / spec).write_text("no frontmatter here\n", encoding="utf-8")
        self.assertIn(spec, self.spawn("planner", f"Plan {spec}.") or "")
        self.artifact("spec", "approved")
        policy = self.root / "core" / "policies" / "workflow.toml"
        policy.write_text("[gates\n", encoding="utf-8")
        self.assertIn("workflow.toml", self.spawn("planner", f"Plan {spec}.") or "")

    def test_path_outside_the_project_is_not_followed(self) -> None:
        outside = "docs/agent/specs/../../../../outside.md"
        self.assertIsNone(self.spawn("planner", f"Plan {outside}."))

    def test_malformed_hook_input_is_denied(self) -> None:
        for data in ({}, {"tool_input": "bad"}, {"_agentkit_input_error": "invalid hook input"}):
            with self.subTest(data=data):
                self.assertIsNotNone(role_gate.evaluate(data))


if __name__ == "__main__":
    unittest.main()
