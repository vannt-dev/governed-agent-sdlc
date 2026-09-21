from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVENTS_FILE = "events.jsonl"

EVENT_TYPES = frozenset(
    {
        "review.started",
        "review.completed",
        "review.failed",
        "policy.evaluated",
        "policy.blocked",
        "policy.approval_required",
        "approval.granted",
        "approval.rejected",
    }
)


@dataclass(frozen=True)
class GovernanceEvent:
    id: str
    run_id: str
    type: str
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "runId": self.run_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }


def read_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / EVENTS_FILE
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def emit_event(
    run_dir: Path, run_id: str, event_type: str, payload: dict[str, Any] | None = None
) -> GovernanceEvent:
    from agentkit.locking import run_lock

    with run_lock(run_dir):
        return _emit_event(run_dir, run_id, event_type, payload)


def _emit_event(
    run_dir: Path, run_id: str, event_type: str, payload: dict[str, Any] | None
) -> GovernanceEvent:
    """Append one event to the run log.

    The log is append-only and derived from the evidence files, never the source of truth: it lets
    audit tooling, a viewer or an integration follow a run in order.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown governance event type: {event_type}")
    run_dir.mkdir(parents=True, exist_ok=True)
    problems = validate_events(run_dir)
    if problems:
        raise ValueError("Cannot append to invalid event log: " + "; ".join(problems))
    sequence = len(read_events(run_dir)) + 1
    event = GovernanceEvent(
        id=f"{run_id}-{sequence:04d}",
        run_id=run_id,
        type=event_type,
        timestamp=datetime.now(UTC).isoformat(),
        payload=payload or {},
    )
    with (run_dir / EVENTS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
    return event


def validate_events(run_dir: Path) -> list[str]:
    """Problems in an events log: unparsable lines, unknown types, or non-sequential ids."""
    path = run_dir / EVENTS_FILE
    if not path.is_file():
        return []
    problems: list[str] = []
    expected = 0
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        expected += 1
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"{EVENTS_FILE} line {number} is not valid JSON")
            continue
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("type"), str)
            or item["type"] not in EVENT_TYPES
        ):
            problems.append(f"{EVENTS_FILE} line {number} has an unknown event type")
            continue
        if not str(item.get("id", "")).endswith(f"-{expected:04d}"):
            problems.append(f"{EVENTS_FILE} line {number} breaks the id sequence")
    return problems
