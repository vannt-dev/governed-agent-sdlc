#!/usr/bin/env python
"""PostToolUse hook: warn the agent when a tool's output looks like it holds a secret.

The tool has already run, so nothing is refused here. When the output of a command, a file read,
a search, a web fetch or an MCP tool matches a secret pattern, the hook answers Claude Code with
`additionalContext`: a note next to the tool result that tells the agent to treat the value as a
secret, not to repeat, store, commit or send it, and to tell the user where it appeared. The note
names the kind of secret, never the text that matched. Output that holds nothing is answered with
nothing, and so is input that cannot be read: a warning hook does not stand in the way.

The patterns are the ones `src/agentkit/review.py` redacts from review evidence, except that a
`token = ...` style assignment counts only when its value is quoted or looks like a key (letters
and digits, 12 or more), so that `token: string` in ordinary source is not reported. A private
key block is reported as well.

Claude Code can also replace a tool's output from this hook; this hook does not, so the agent
still sees what the tool returned.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from typing import Any

# The same expressions as `_SECRET_PATTERNS` in `src/agentkit/review.py`, minus the assignment.
SHARED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "an API key (sk-...)"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "a GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "an AWS access key ID"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE), "a bearer token"),
)
OWN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"""(?:api[_-]?key|secret|token|password)["']?\s*[:=]\s*"""
            # unquoted: letters and digits, not a call or an index such as `hashlib.sha256(`
            r"""(?:["'][^\s"']{8,}["']|(?=[\w+/=.-]*\d)(?=[\w+/=.-]*[A-Za-z])"""
            r"""[\w+/=.-]{12,}+(?![(\[]))""",
            re.IGNORECASE,
        ),
        "a key, secret, token or password value",
    ),
    (re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"), "a private key"),
)
# Enough to cover what a tool shows an agent; a larger output is scanned this far.
SCAN_LIMIT = 4 * 1024 * 1024


def texts(value: Any, depth: int = 0) -> Iterator[str]:
    """Every string in a tool's response, whatever its shape (a failed call gives a string)."""
    if depth > 16:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from texts(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from texts(item, depth + 1)


def secret_kinds(response: Any) -> list[str]:
    """The kinds of secret the response appears to hold, in pattern order, each named once."""
    budget = SCAN_LIMIT
    found: list[str] = []
    for text in texts(response):
        if budget <= 0:
            break
        part = text[:budget]
        budget -= len(part)
        for pattern, kind in (*SHARED_PATTERNS, *OWN_PATTERNS):
            if kind not in found and pattern.search(part):
                found.append(kind)
    order = [kind for _, kind in (*SHARED_PATTERNS, *OWN_PATTERNS)]
    return sorted(found, key=order.index)


def warning(tool: str, kinds: list[str]) -> str:
    listed = ", ".join(kinds[:-1]) + (" and " if len(kinds) > 1 else "") + kinds[-1]
    return (
        f"Governed Agent SDLC: the output of {tool or 'this tool'} looks like it holds {listed}. "
        "Treat the value as a secret: do not repeat or quote it, do not write it to a file, "
        "commit, log or message, and do not send it anywhere. Tell the user where it appeared "
        "so they can check it and rotate it if it is real."
    )


def answer(data: Any) -> dict[str, Any] | None:
    """The hook's answer to one PostToolUse call, or None when there is nothing to say."""
    if not isinstance(data, dict):
        return None
    kinds = secret_kinds(data.get("tool_response"))
    if not kinds:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": warning(str(data.get("tool_name") or ""), kinds),
        }
    }


def main() -> int:
    try:
        # Claude Code writes UTF-8; Windows would otherwise read standard input in its code page
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return 0
    result = answer(data)
    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
