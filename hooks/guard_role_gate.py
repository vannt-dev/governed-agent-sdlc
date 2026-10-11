#!/usr/bin/env python
"""PreToolUse guard for the Agent tool: a role starts only from artifacts that passed its gate.

`agentkit validate` already refuses a plan whose parent spec is not approved, but only once the
plan exists. By then the planner has spent a full run on a spec that can still change. This guard
moves the same check to the moment the role is spawned.

The gates are read from `core/policies/workflow.toml` (`[gates]`), so the policy keeps one home. A
requirement such as `spec.approved` is met by that status or a later one in the lifecycle
(`approved`, `active`, `completed`); `superseded` and `archived` never meet it. A stage whose
`[workflow].require_*` flag is off in the manifest is not gated.

Only artifacts the prompt names by path are checked, and only kinds the role's gate lists. A path
that does not exist yet is an output, not an input. The guard stops a visible violation; it does
not guess which artifact an unnamed task belongs to.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from common import deny, input_error, read_hook_input, tool_input, tool_input_error

STAGE_ROLES = {
    "plan": "planner",
    "implementation": "developer",
    "review": "reviewer",
    "qa": "qa",
    "publish": "publisher",
}
STAGE_FLAGS = {
    "plan": "require_spec",
    "implementation": "require_plan",
    "review": "require_review",
    "qa": "require_qa",
    "publish": "require_qa",
}
ARTIFACT_KINDS = {"spec", "plan", "task", "review", "qa"}
LIFECYCLE = ("approved", "active", "completed")
MANIFEST_NAMES = ("agentkit.toml", ".agent/project.toml")
POLICY_PATH = "core/policies/workflow.toml"
ARTIFACT_PATH = re.compile(r"docs/agent/(?:specs|plans|tasks|reviews|qa)/[\w./-]*\.md")


class GateError(ValueError):
    """Raised when a gate cannot be evaluated; the spawn is refused."""


def _load_toml(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise GateError(f"{path.name} cannot be read: {exc}") from exc


def requirements_for(root: Path, role: str) -> dict[str, str]:
    """Artifact kind -> required status for the stage this role runs, from the workflow policy."""
    policy = _load_toml(root / POLICY_PATH)
    if policy is None:
        return {}
    gates = policy.get("gates")
    if not isinstance(gates, dict):
        return {}
    manifest: dict[str, Any] = {}
    for name in MANIFEST_NAMES:
        loaded = _load_toml(root / name)
        if loaded is not None:
            manifest = loaded
            break
    workflow = manifest.get("workflow")
    flags = workflow if isinstance(workflow, dict) else {}
    required: dict[str, str] = {}
    for stage, stage_role in STAGE_ROLES.items():
        if stage_role != role or flags.get(STAGE_FLAGS[stage]) is False:
            continue
        entries = gates.get(f"{stage}_requires")
        for entry in entries if isinstance(entries, list) else []:
            kind, _, status = str(entry).partition(".")
            if kind in ARTIFACT_KINDS and status:
                required[kind] = status
    return required


def artifact_state(path: Path) -> tuple[str, str]:
    """`kind` and `status` from an artifact's TOML frontmatter."""
    try:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as exc:
        raise GateError(f"cannot be read: {exc}") from exc
    if not text.startswith("+++\n") or "\n+++\n" not in text[4:]:
        raise GateError("has no TOML frontmatter")
    try:
        metadata = tomllib.loads(text[4:].split("\n+++\n", 1)[0])
    except tomllib.TOMLDecodeError as exc:
        raise GateError(f"has invalid frontmatter: {exc}") from exc
    return str(metadata.get("kind") or ""), str(metadata.get("status") or "")


def meets(status: str, required: str) -> bool:
    if required not in LIFECYCLE:
        return status == required
    return status in LIFECYCLE and LIFECYCLE.index(status) >= LIFECYCLE.index(required)


def evaluate(data: dict[str, Any]) -> str | None:
    malformed = input_error(data)
    if malformed:
        return malformed
    malformed_tool = tool_input_error(data)
    if malformed_tool:
        return malformed_tool
    values = tool_input(data)
    role = str(values.get("subagent_type") or "").lower()
    role = role.removeprefix("governed-agent-sdlc:").removeprefix("agent-workbench:")
    if role not in STAGE_ROLES.values():
        return None

    root = Path(str(data.get("cwd") or Path.cwd())).resolve()
    try:
        required = requirements_for(root, role)
    except GateError as exc:
        return f"{role} cannot start: {exc}"
    if not required:
        return None

    prompt = f"{values.get('prompt') or ''} {values.get('description') or ''}".replace("\\", "/")
    failures: list[str] = []
    for relative in dict.fromkeys(ARTIFACT_PATH.findall(prompt)):
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        try:
            kind, status = artifact_state(path)
        except GateError as exc:
            failures.append(f"{relative} {exc}")
            continue
        needed = required.get(kind)
        if needed and not meets(status, needed):
            failures.append(f"{relative} is {status or 'without a status'}, needs {needed}")
    if not failures:
        return None
    return (
        f"{role} starts only from artifacts that passed their gate ({POLICY_PATH}): "
        + "; ".join(failures)
        + ". Move the artifact with `agentkit artifact transition` first; approval is a human's."
    )


def main() -> int:
    reason = evaluate(read_hook_input())
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
