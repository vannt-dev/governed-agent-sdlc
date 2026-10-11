#!/usr/bin/env python
"""PreToolUse guard: a role writes only what its definition under `core/roles/` grants.

Two kinds of grant are checked. A directory grant (`docs/agent/specs/**`) is a path prefix. A
`*.completion_evidence` grant lets a role that does not own a task file fill in that file's
completion evidence section and nothing else: the proposed write is applied in memory, the
evidence section is masked on both sides, and anything else that moved is refused. A whole-file
`Write` is therefore judged exactly like a one-line `Edit`.

Without the second kind a developer could rewrite its own write scope or acceptance criteria, and
a reviewer could not record evidence in the task it reviewed. Status and approval stay in the
frontmatter, which is outside the evidence section; they change through
`agentkit artifact transition`.

Not checked here: the source paths a task lists under its write scope. That list is prose, so it
is held by review. The main session carries no role and is not restricted by this guard.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from common import deny, input_error, read_hook_input, tool_input, tool_input_error

ARTIFACT_PREFIX = "docs/agent/"
TASK_PREFIX = "docs/agent/tasks/"
ROLE_PREFIXES = {
    "architect": ("docs/agent/specs/",),
    "planner": ("docs/agent/plans/", "docs/agent/tasks/"),
    "reviewer": ("docs/agent/reviews/", "docs/agent/tasks/reviews/"),
    "qa": ("docs/agent/qa/", "docs/agent/tasks/qa/"),
    "publisher": ("docs/agent/",),
}
# Roles granted `*.completion_evidence` in core/roles/.
EVIDENCE_ROLES = {"developer", "reviewer", "qa"}

HEADING = re.compile(r"^(#{1,6})\s")
EVIDENCE_HEADING = re.compile(r"^(#{2,6})\s*(?:completion\s+)?evidence\b", re.IGNORECASE)
FENCE = re.compile(r"^\s{0,3}(```|~~~)")


def mask_evidence(text: str) -> str | None:
    """The document without the body of its evidence section, or None when it has no such section.

    The section runs to the next heading of the same or a higher level. A `#` line inside a fenced
    block is command output or a comment, not a heading.
    """
    kept: list[str] = []
    level = 0
    in_fence = False
    found = False
    for line in text.splitlines():
        if level:
            if FENCE.match(line):
                in_fence = not in_fence
                continue
            heading = None if in_fence else HEADING.match(line)
            if heading is None or len(heading.group(1)) > level:
                continue
            level = 0
        kept.append(line)
        evidence = EVIDENCE_HEADING.match(line)
        if evidence:
            level = len(evidence.group(1))
            in_fence = False
            found = True
    return "\n".join(kept) if found else None


def proposed_text(values: dict[str, Any], current: str) -> str | None:
    """The file as it would read after this Write, Edit or MultiEdit; None when it cannot apply."""
    if isinstance(values.get("content"), str):
        return str(values["content"])
    edits = values.get("edits")
    steps = edits if isinstance(edits, list) else [values]
    text = current
    for step in steps:
        if not isinstance(step, dict):
            return None
        old, new = step.get("old_string"), step.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or not old or old not in text:
            return None
        text = text.replace(old, new) if step.get("replace_all") else text.replace(old, new, 1)
    return text


def evidence_only_reason(
    role: str, target: Path, relative: str, values: dict[str, Any]
) -> str | None:
    if not target.is_file():
        return f"{role} may not create a task file; the planner owns {TASK_PREFIX}"
    try:
        current = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"{role} write to {relative} cannot be checked: {exc}"
    before = mask_evidence(current)
    if before is None:
        return f"{relative} has no completion evidence section; ask the planner to add one"
    after_text = proposed_text(values, current)
    if after_text is None:
        return f"{role} write to {relative} cannot be applied to the current file, so it is refused"
    if mask_evidence(after_text) != before:
        return (
            f"{role} may change only the completion evidence section of {relative}; "
            "record the problem there and let the planner change the rest"
        )
    return None


def evaluate(data: dict[str, Any]) -> str | None:
    malformed = input_error(data)
    if malformed:
        return malformed
    malformed_tool = tool_input_error(data)
    if malformed_tool:
        return malformed_tool
    role = str(data.get("agent_type") or os.environ.get("AGENTKIT_ROLE") or "").lower()
    role = role.removeprefix("governed-agent-sdlc:").removeprefix("agent-workbench:")
    prefixes = ROLE_PREFIXES.get(role, ())
    if not prefixes and role not in EVIDENCE_ROLES:
        return None

    values = tool_input(data)
    raw_path = str(values.get("file_path") or values.get("path") or "")
    if not raw_path:
        return f"{role} write has no resolvable file path"

    cwd = Path(str(data.get("cwd") or Path.cwd())).resolve()
    target = Path(raw_path)
    if not target.is_absolute():
        target = cwd / target
    target = target.resolve()
    try:
        relative = target.relative_to(cwd).as_posix()
    except ValueError:
        return f"{role} cannot write outside the project root: {target}"
    if any(relative.startswith(prefix) for prefix in prefixes):
        return None
    if role in EVIDENCE_ROLES and relative.startswith(TASK_PREFIX):
        return evidence_only_reason(role, target, relative, values)
    if role == "developer":
        if relative.startswith(ARTIFACT_PREFIX):
            return (
                "developer may write task scope and task completion evidence only; "
                f"requested {relative}"
            )
        return None
    return f"{role} may write only {', '.join(prefixes)}; requested {relative}"


def main() -> int:
    reason = evaluate(read_hook_input())
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
