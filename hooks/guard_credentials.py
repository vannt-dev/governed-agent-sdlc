#!/usr/bin/env python
"""PreToolUse guard: agents do not read credential material or dump the environment.

A rule about a command fires on the command, not on text that mentions it. Until 2026-10-11 the
word `env` anywhere in a command line was refused, so `git commit -m "document env vars"`,
`uv run --env-file x pytest`, `npx cross-env ...` and a heredoc that only named
`git credential` were all blocked. A guard that refuses ordinary work gets routed around, so the
environment rule now needs `env`/`printenv` in command position, and heredoc bodies are treated as
data.

Still refused on purpose: a secret file named as a shell word (`cat .env`, `--env-file=.env`,
`echo ".env" >> .gitignore`) and a rule named inside quotes on the command line itself
(`sh -c "env"`). Put such text in a heredoc or a file instead.

`src/agentkit/codex_hook.py` carries the same rules for Codex, which copies that file out on its
own; `tests/test_guards.py` runs one command table against both.
"""

from __future__ import annotations

import re
from typing import Any

from common import deny, input_error, read_hook_input, tool_input, tool_input_error

SECRET_PATH = re.compile(
    r"(?:^|[/\\])(?:\.env(?:\.[^/\\]+)?|\.git-credentials|\.netrc|id_rsa|id_ed25519|"
    r"credentials?|secrets?)(?:$|[/\\])",
    re.IGNORECASE,
)
# SECRET_PATH needs a path separator in front of the name, which `cat .env` does not have.
SECRET_FILE_WORD = re.compile(
    r"(?:^|[\s'\"=<>(:,/])(?:\.env(?:\.[\w.-]+)?|\.git-credentials|\.netrc|id_rsa|id_ed25519)"
    r"(?=$|[\s'\")|;&<>,:/])",
    re.IGNORECASE,
)
SECRET_COMMAND = re.compile(
    r"(?:git\s+credential|secret-tool|security\s+find-(?:generic|internet)-password|"
    r"cmdkey\s+/list|Get-StoredCredential|"
    r"(?:Get-ChildItem|gci|dir|ls)\s+Env:|GetEnvironmentVariables)",
    re.IGNORECASE,
)
# `env` or `printenv` as the command itself: at the start of a command, behind a wrapper such as
# `sudo`, or as a whole quoted script. `env NAME=value command` runs a command and prints nothing.
ENV_DUMP = re.compile(
    r"(?:^|[|;&(){`'\"\n])\s*"
    r"(?:(?:sudo|command|exec|time|nohup|xargs)(?:\s+-\S+)*\s+)?"
    r"(?:[\w.-]*/)*"
    r"(?:printenv\b|env(?:\.exe)?(?:\s+(?:-\S+|\w+=\S*))*\s*(?:$|[|;&)}`'\">\n]))",
    re.IGNORECASE,
)
# The whole environment object printed from a one-line script; a single key is not a dump.
SCRIPT_ENV_DUMP = re.compile(
    r"\b(?:node|bun|deno)\b[^\n]*\bprocess\.env\b(?!\s*[.\[])"
    r"|\bpython[\d.]*\b[^\n]*\bos\.environ\b(?!\s*(?:\[|\.get\b))",
    re.IGNORECASE,
)
# Printing a literal word is harmless; the leak is an expanded variable next to a secret name.
TOKEN_ECHO = re.compile(
    r"(?:echo|write-output|write-host|printf)\s+(?=[^\n]*\$)[^\n]*"
    r"(?:token|secret|password|api[_-]?key)",
    re.IGNORECASE,
)
# `<<TAG` expands its body; `<<'TAG'`, `<<"TAG"` and `<<\TAG` take it literally.
HEREDOC_OPERATOR = re.compile(r"<<-?[ \t]*(?:'([^'\n]+)'|\"([^\"\n]+)\"|(\\?)([\w.-]+))")
SUBSTITUTION = re.compile(r"\$\([^()]*\)|`[^`]*`")


def _unquoted_heredocs(line: str, quote: str) -> tuple[list[tuple[str, bool]], str]:
    """Heredoc tags opened outside quotes on this line, and the quote state the line ends in."""
    tags: list[tuple[str, bool]] = []
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif line.startswith("<<<", index):
            index += 3
            continue
        elif line.startswith("<<", index):
            match = HEREDOC_OPERATOR.match(line, index)
            if match:
                single, double, escaped, bare = match.groups()
                tags.append((single or double or bare, bare is None or bool(escaped)))
                index = match.end()
                continue
        index += 1
    return tags, quote


def strip_heredoc_bodies(command: str) -> str:
    """Remove heredoc bodies, which are data rather than commands.

    `<<` inside quotes is not a heredoc (`python -c "print(1 << n)"`), and a tag with no closing
    line is not one either; in both cases every following line stays a command. An unquoted tag
    still expands command substitutions, so those are kept and checked.
    """
    lines = command.split("\n")
    kept: list[str] = []
    quote = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        kept.append(line)
        tags, quote = _unquoted_heredocs(line, quote)
        for tag, literal in tags:
            end = next((i for i in range(index, len(lines)) if lines[i].strip() == tag), None)
            if end is None:
                continue
            if not literal:
                for body_line in lines[index:end]:
                    kept.extend(SUBSTITUTION.findall(body_line))
            index = end + 1
    return "\n".join(kept)


def command_reason(raw_command: str) -> str | None:
    command = strip_heredoc_bodies(raw_command)
    normalized = command.replace("\\", "/")
    if SECRET_PATH.search(normalized) or SECRET_FILE_WORD.search(normalized):
        return "agents may not read credential material through a command"
    if (
        SECRET_COMMAND.search(command)
        or ENV_DUMP.search(normalized)
        or SCRIPT_ENV_DUMP.search(command)
    ):
        return "agents may not query credential stores or dump the environment"
    if TOKEN_ECHO.search(command):
        return "agents may not print potential secrets"
    return None


def evaluate(data: dict[str, Any]) -> str | None:
    malformed = input_error(data)
    if malformed:
        return malformed
    malformed_tool = tool_input_error(data)
    if malformed_tool:
        return malformed_tool
    values = tool_input(data)
    candidates = [values.get("file_path"), values.get("path")]
    if str(data.get("tool_name") or "").lower() in {"glob", "grep"}:
        candidates.append(values.get("glob") or values.get("pattern"))
    for candidate in candidates:
        path = str(candidate or "")
        normalized = re.sub(r"[?*{}\[\]]", "", path.replace("\\", "/"))
        if path and SECRET_PATH.search(normalized):
            return f"agents may not read credential material: {path}"
    command = str(values.get("command") or "")
    return command_reason(command) if command else None


def main() -> int:
    reason = evaluate(read_hook_input())
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
