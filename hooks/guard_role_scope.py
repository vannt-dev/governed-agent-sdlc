#!/usr/bin/env python
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from common import deny, input_error, read_hook_input, tool_input, tool_input_error

ROLE_PREFIXES = {
    "architect": ("docs/agent/specs/",),
    "planner": ("docs/agent/plans/", "docs/agent/tasks/"),
    "reviewer": ("docs/agent/reviews/", "docs/agent/tasks/reviews/"),
    "qa": ("docs/agent/qa/", "docs/agent/tasks/qa/"),
    "publisher": ("docs/agent/",),
}


def evaluate(data: dict[str, Any]) -> str | None:
    malformed = input_error(data)
    if malformed:
        return malformed
    malformed_tool = tool_input_error(data)
    if malformed_tool:
        return malformed_tool
    role = str(data.get("agent_type") or os.environ.get("AGENTKIT_ROLE") or "").lower()
    role = role.removeprefix("governed-agent-sdlc:").removeprefix("agent-workbench:")
    prefixes = ROLE_PREFIXES.get(role)
    if not prefixes:
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
    if not any(relative.startswith(prefix) for prefix in prefixes):
        return f"{role} may write only {', '.join(prefixes)}; requested {relative}"
    return None


def main() -> int:
    reason = evaluate(read_hook_input())
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
