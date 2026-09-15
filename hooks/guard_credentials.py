#!/usr/bin/env python
from __future__ import annotations

import re
from typing import Any

from common import deny, input_error, read_hook_input, tool_input, tool_input_error

SECRET_PATH = re.compile(
    r"(?:^|[/\\])(?:\.env(?:\.[^/\\]+)?|\.git-credentials|\.netrc|id_rsa|id_ed25519|"
    r"credentials?|secrets?)(?:$|[/\\])",
    re.IGNORECASE,
)
SECRET_COMMAND = re.compile(
    r"(?:git\s+credential|secret-tool|security\s+find-(?:generic|internet)-password|"
    r"cmdkey\s+/list|Get-StoredCredential|printenv|\benv\b|"
    r"(?:Get-ChildItem|gci|dir)\s+Env:|GetEnvironmentVariables)",
    re.IGNORECASE,
)
TOKEN_ECHO = re.compile(
    r"(?:echo|write-output|printf)\s+[^\n]*(?:token|secret|password|api[_-]?key)",
    re.IGNORECASE,
)


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
    command = str(values.get("command") or "")
    for candidate in candidates:
        path = str(candidate or "")
        normalized = re.sub(r"[?*{}\[\]]", "", path.replace("\\", "/"))
        if path and SECRET_PATH.search(normalized):
            return f"agents may not read credential material: {path}"
    if command and SECRET_PATH.search(command.replace("\\", "/")):
        return "agents may not read credential material through a command"
    if command and SECRET_COMMAND.search(command):
        return "agents may not query credential stores or dump the environment"
    if command and TOKEN_ECHO.search(command):
        return "agents may not print potential secrets"
    return None


def main() -> int:
    reason = evaluate(read_hook_input())
    return deny(reason) if reason else 0


if __name__ == "__main__":
    raise SystemExit(main())
