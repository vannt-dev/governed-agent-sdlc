"""Compare a project's generated files with what the installed version writes, and upgrade them.

A file `agentkit` writes is recorded in `.agent/generated.json` by its hash. A file that still has
that hash but differs from today's output was left by an older version and is safe to replace; a
file whose hash changed since was edited by hand and is kept unless the caller forces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentkit.generator import (
    ADAPTER_PLANS,
    content_digest,
    load_record,
    plan_hooks,
    record_generated,
)

# Statuses that make `agentkit doctor` fail: the project does not run what this version ships.
FAILING = ("missing", "outdated", "unknown")

HINTS = {
    "missing": "run `agentkit upgrade` to add it",
    "outdated": "written by an older version; run `agentkit upgrade`",
    "modified": "edited by hand; kept by `agentkit upgrade` unless --force",
    "unknown": "differs and has no generation record, so an edit cannot be told apart; "
    "check `agentkit upgrade --dry-run`, then run `agentkit upgrade --force` "
    "and re-apply any edits of your own",
}


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    component: str
    status: str
    content: str | bytes

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "component": self.component, "status": self.status}


def _plans() -> dict[str, dict[str, str | bytes]]:
    plans: dict[str, dict[str, str | bytes]] = {"hooks": dict(plan_hooks())}
    for name, plan in ADAPTER_PLANS.items():
        plans[name] = dict(plan())
    return plans


def check_generated(root: Path) -> list[GeneratedFile]:
    """Classify every file of the guards and adapters the project uses.

    A component is in use when one of its files is on disk, so a project that never generated an
    adapter, or removed one, is not told to add it.
    """
    record = load_record(root)
    found: list[GeneratedFile] = []
    for component, plan in _plans().items():
        if not any((root / path).is_file() for path in plan):
            continue
        for path, content in plan.items():
            found.append(
                GeneratedFile(
                    path, component, _status(root / path, content, record.get(path)), content
                )
            )
    return found


def _status(path: Path, content: str | bytes, recorded: dict[str, str] | None) -> str:
    if not path.is_file():
        return "missing"
    actual = content_digest(path.read_bytes())
    if actual == content_digest(content):
        return "current"
    if recorded is None:
        return "unknown"
    return "outdated" if actual == recorded.get("sha256") else "modified"


def upgrade_generated(
    root: Path, *, force: bool = False, dry_run: bool = False
) -> dict[str, list[str]]:
    """Rewrite outdated and missing files; keep edited ones unless forced.

    Files that already match are written into the record, so a project generated before the
    record existed is recognised from then on.
    """
    result: dict[str, list[str]] = {"added": [], "updated": [], "kept": [], "unchanged": []}
    recorded: dict[str, str | bytes] = {}
    for item in check_generated(root):
        if item.status == "current":
            result["unchanged"].append(item.path)
            recorded[item.path] = item.content
            continue
        if item.status in ("modified", "unknown") and not force:
            result["kept"].append(item.path)
            continue
        result["added" if item.status == "missing" else "updated"].append(item.path)
        recorded[item.path] = item.content
        if not dry_run:
            target = root / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(item.content, bytes):
                target.write_bytes(item.content)
            else:
                target.write_text(item.content, encoding="utf-8", newline="\n")
    if not dry_run:
        record_generated(root, recorded)
    return result
