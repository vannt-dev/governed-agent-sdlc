from __future__ import annotations

import json
import re
import sys
from typing import Any

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
FORCE_PUSH = re.compile(r"\bgit\b[^\n]*(?:push\s+[^\n]*(?:--force(?:-with-lease)?|-f\b))", re.I)
FORCE_REFSPEC = re.compile(r"\bgit\b[^\r\n;&|]*\bpush\b[^\r\n;&|]*(?:^|\s)\+[^\s]+", re.I)
DIRECT_PROTECTED = re.compile(
    r"\bgit\b[^\r\n;&|]*\bpush\b[^\r\n;&|]*(?:^|\s|['\"])(?:\+?[^\s:'\"]*:)?"
    r"(?:refs/heads/)?(?:main|master|develop)(?=\s|$|['\"])",
    re.I,
)
DESTRUCTIVE_GIT = re.compile(r"\bgit\s+(?:reset\s+--hard|clean\s+-[^\s]*f|checkout\s+--\s)", re.I)


def evaluate(data: dict[str, Any]) -> str | None:
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return "hook input must contain a tool_input object"

    candidates: list[Any] = [
        tool_input.get("file_path"),
        tool_input.get("path"),
        tool_input.get("glob"),
        tool_input.get("pattern"),
    ]
    paths = tool_input.get("paths")
    if isinstance(paths, list):
        candidates.extend(paths)
    for candidate in candidates:
        path = str(candidate or "")
        normalized = re.sub(r"[?*{}\[\]]", "", path.replace("\\", "/"))
        if path and SECRET_PATH.search(normalized):
            return f"agents may not read credential material: {path}"

    command = str(tool_input.get("command") or "")
    normalized_command = command.replace("\\", "/")
    if command and SECRET_PATH.search(normalized_command):
        return "agents may not access credential material through a command or patch"
    if command and SECRET_COMMAND.search(command):
        return "agents may not query credential stores or dump the environment"
    if command and TOKEN_ECHO.search(command):
        return "agents may not print potential secrets"
    if command and (FORCE_PUSH.search(command) or FORCE_REFSPEC.search(command)):
        return "force push is forbidden"
    if command and DIRECT_PROTECTED.search(command):
        return "push through a task branch and pull request, not directly to a protected branch"
    if command and DESTRUCTIVE_GIT.search(command):
        return "destructive git commands require an explicit human-approved workflow"
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"BLOCKED: invalid hook input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(data, dict):
        print("BLOCKED: hook input must be a JSON object", file=sys.stderr)
        return 2
    reason = evaluate(data)
    if reason:
        print(f"BLOCKED: {reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
