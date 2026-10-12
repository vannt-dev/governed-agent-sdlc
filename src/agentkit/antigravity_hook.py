"""Antigravity PreToolUse hook, written out as `.agents/hooks/governed_guard.py` and run on its own.

Antigravity hands a hook the tool call as `{"toolCall": {"name": ..., "args": {...}}, ...}` on stdin
and reads a decision from stdout. This file decides nothing itself: it puts the call into the words
the project's guards in `hooks/` read and asks them, so the rules stay in one place for every tool.

No answer means no objection, and Antigravity's own permission flow goes on. Whatever cannot be
checked is denied: input that is not a tool call, a guard that is missing, fails or is too slow.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# `.agents/hooks/governed_guard.py` is two folders below the project root.
ROOT = Path(__file__).resolve().parents[2]
COMMAND_GUARDS = ("guard_credentials.py", "guard_git.py")
PATH_GUARDS = ("guard_credentials.py",)
# What Antigravity adds to every call to describe it to the user; text, not a target.
LABELS = frozenset({"toolAction", "toolSummary"})
GUARD_TIMEOUT_SECONDS = 8
# For the whole decision. `.agents/hooks.json` allows the hook more than this, so a slow guard
# is answered with a refusal here rather than left to whatever a cut-off hook means there.
BUDGET_SECONDS = 20


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 4096 and "\n" not in value


def _path_like(value: Any) -> bool:
    """A string argument that names a place on disk rather than, say, text to search for."""
    return _text(value) and ("/" in value or "\\" in value or value.startswith("."))


def _targets(tool: str, arguments: dict[str, Any]) -> list[str]:
    """The paths and file patterns a file tool's call reaches.

    The file tools name their target under different arguments, so the hook goes by what an
    argument looks like, not by its name: a path, a list (of file patterns), and for the tool
    that finds files by name every text it is given. The text a search looks for is no target.
    """
    by_name = tool == "find_by_name"
    targets: list[str] = []
    for name, value in arguments.items():
        if name in LABELS:
            continue
        if isinstance(value, list):
            targets.extend(item for item in value if _text(item))
        elif _path_like(value) or (by_name and _text(value)):
            targets.append(value)
    return targets


def requests(payload: Any) -> list[tuple[str, dict[str, Any]]] | str:
    """Which guard to ask what, for each thing the call touches; or why this is no tool call."""
    if not isinstance(payload, dict):
        return "hook input must be a JSON object"
    call = payload.get("toolCall")
    if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not call["name"]:
        return "hook input is missing toolCall.name"
    arguments = call.get("args", {})
    if not isinstance(arguments, dict):
        return "hook input toolCall.args must be a JSON object"

    if call["name"] == "run_command":
        command = arguments.get("CommandLine")
        if not isinstance(command, str):
            return "hook input run_command is missing CommandLine"
        request = {"tool_name": "Bash", "tool_input": {"command": command}}
        return [(guard, request) for guard in COMMAND_GUARDS]

    return [
        (guard, {"tool_name": "Glob", "tool_input": {"pattern": target}})
        for target in _targets(call["name"], arguments)
        for guard in PATH_GUARDS
    ]


def ask(guard: str, request: dict[str, Any], *, timeout: float) -> str | None:
    """A guard's objection to a request, or None when it has none."""
    script = ROOT / "hooks" / guard
    if not script.is_file():
        return f"the guard hooks/{guard} is missing; restore it with `agentkit update-hooks`"
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"the guard hooks/{guard} could not run: {exc}"
    if result.returncode == 0:
        return None
    reason = result.stderr.strip().removeprefix("BLOCKED:").strip()
    if result.returncode == 2 and reason:
        return reason
    return f"the guard hooks/{guard} failed (exit {result.returncode})"


def decide(raw: str) -> str | None:
    """Why the tool call in `raw` is refused, or None when nothing objects to it."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"invalid hook input: {exc}"
    planned = requests(payload)
    if isinstance(planned, str):
        return planned
    deadline = time.monotonic() + BUDGET_SECONDS
    for guard, request in planned:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "the guards did not answer in time"
        reason = ask(guard, request, timeout=min(GUARD_TIMEOUT_SECONDS, remaining))
        if reason:
            return reason
    return None


def main() -> int:
    reason = decide(sys.stdin.read())
    if reason:
        print(json.dumps({"decision": "deny", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
