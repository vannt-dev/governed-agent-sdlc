#!/usr/bin/env python
from __future__ import annotations

import re

from common import deny, input_error, read_hook_input, tool_input, tool_input_error


FORCE_PUSH = re.compile(r"\bgit\b[^\n]*(?:push\s+[^\n]*(?:--force(?:-with-lease)?|-f\b))", re.I)
FORCE_REFSPEC = re.compile(r"\bgit\b[^\r\n;&|]*\bpush\b[^\r\n;&|]*(?:^|\s)\+[^\s]+", re.I)
DIRECT_PROTECTED = re.compile(
    r"\bgit\b[^\r\n;&|]*\bpush\b[^\r\n;&|]*(?:^|\s|['\"])(?:\+?[^\s:'\"]*:)?"
    r"(?:refs/heads/)?(?:main|master|develop)(?=\s|$|['\"])",
    re.I,
)
DESTRUCTIVE = re.compile(r"\bgit\s+(?:reset\s+--hard|clean\s+-[^\s]*f|checkout\s+--\s)", re.I)


def evaluate(data: dict) -> str | None:
    malformed = input_error(data)
    if malformed:
        return malformed
    malformed_tool = tool_input_error(data)
    if malformed_tool:
        return malformed_tool
    command = str(tool_input(data).get("command") or "")
    if FORCE_PUSH.search(command) or FORCE_REFSPEC.search(command):
        return "force push is forbidden"
    if DIRECT_PROTECTED.search(command):
        return "push through a task branch and pull request, not directly to a protected branch"
    if DESTRUCTIVE.search(command):
        return "destructive git commands require an explicit human-approved workflow"
    return None


def main() -> int:
    reason = evaluate(read_hook_input())
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
