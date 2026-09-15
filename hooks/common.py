from __future__ import annotations

import json
import sys
from typing import Any

INPUT_ERROR_KEY = "_agentkit_input_error"


def read_hook_input() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError) as exc:
        return {INPUT_ERROR_KEY: f"invalid hook input: {exc}"}
    if not isinstance(value, dict):
        return {INPUT_ERROR_KEY: "hook input must be a JSON object"}
    return value


def input_error(data: dict[str, Any]) -> str | None:
    value = data.get(INPUT_ERROR_KEY)
    return str(value) if value else None


def tool_input_error(data: dict[str, Any]) -> str | None:
    if "tool_input" not in data:
        return "hook input is missing tool_input"
    if not isinstance(data["tool_input"], dict):
        return "hook tool_input must be a JSON object"
    return None


def deny(reason: str) -> int:
    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 2


def tool_input(data: dict[str, Any]) -> dict[str, Any]:
    value = data.get("tool_input", {})
    return value if isinstance(value, dict) else {}
