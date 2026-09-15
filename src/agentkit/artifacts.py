from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ARTIFACT_KINDS = ("spec", "plan", "task", "review", "qa")
ARTIFACT_DIRECTORIES = {
    "spec": "specs",
    "plan": "plans",
    "task": "tasks",
    "review": "reviews",
    "qa": "qa",
}
ALLOWED_TRANSITIONS = {
    "draft": {"awaiting_approval", "archived"},
    "awaiting_approval": {"approved", "draft", "archived"},
    "approved": {"active", "superseded", "archived"},
    "active": {"completed", "superseded", "archived"},
    "completed": {"archived"},
    "superseded": {"archived"},
    "archived": set(),
}


class ArtifactError(ValueError):
    """Raised when an artifact cannot be parsed or transitioned."""


@dataclass(frozen=True)
class Artifact:
    path: Path
    metadata: dict[str, Any]
    body: str

    @property
    def id(self) -> str:
        return str(self.metadata.get("id", ""))

    @property
    def kind(self) -> str:
        return str(self.metadata.get("kind", ""))

    @property
    def status(self) -> str:
        return str(self.metadata.get("status", ""))


def parse_artifact(path: Path) -> Artifact:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("+++\n"):
        raise ArtifactError(f"{path}: artifact must start with TOML frontmatter (+++)")
    try:
        header, body = text[4:].split("\n+++\n", 1)
    except ValueError as exc:
        raise ArtifactError(f"{path}: TOML frontmatter is not closed") from exc
    try:
        metadata = tomllib.loads(header)
    except tomllib.TOMLDecodeError as exc:
        raise ArtifactError(f"{path}: invalid TOML frontmatter: {exc}") from exc
    return Artifact(path=path, metadata=metadata, body=body)


def serialize_artifact(artifact: Artifact) -> str:
    lines: list[str] = []
    scalar_order = (
        "schema_version",
        "id",
        "kind",
        "status",
        "task_level",
        "created_at",
        "updated_at",
        "supersedes",
        "parent",
    )
    for key in scalar_order:
        value = artifact.metadata.get(key)
        if value not in (None, ""):
            if isinstance(value, int):
                lines.append(f"{key} = {value}")
            else:
                lines.append(f'{key} = "{_escape(str(value))}"')

    for key in ("repositories", "protected_areas"):
        values = artifact.metadata.get(key, [])
        rendered = ", ".join(f'"{_escape(str(value))}"' for value in values)
        lines.append(f"{key} = [{rendered}]")

    approval = artifact.metadata.get("approval")
    if isinstance(approval, dict) and approval:
        lines.append("")
        lines.append("[approval]")
        for key in ("approved_by", "approved_at", "evidence"):
            value = approval.get(key)
            if value:
                lines.append(f'{key} = "{_escape(str(value))}"')

    return "+++\n" + "\n".join(lines) + "\n+++\n" + artifact.body


def transition(
    artifact: Artifact,
    target: str,
    *,
    approved_by: str | None = None,
    evidence: str | None = None,
) -> Artifact:
    current = artifact.status
    target = target.strip().lower()
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ArtifactError(f"Invalid transition: {current} -> {target}")

    metadata = dict(artifact.metadata)
    metadata["status"] = target
    now = datetime.now(UTC).isoformat()
    metadata["updated_at"] = now

    if target == "approved":
        if not approved_by or not evidence:
            raise ArtifactError(
                "Approval requires --approved-by and --evidence; agents cannot self-approve."
            )
        metadata["approval"] = {
            "approved_by": approved_by,
            "approved_at": now,
            "evidence": evidence,
        }
    return Artifact(artifact.path, metadata, artifact.body)


def create_artifact(root: Path, kind: str, slug: str) -> Path:
    if kind not in ARTIFACT_KINDS:
        raise ArtifactError(f"Unknown artifact kind: {kind}")
    safe_slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")
    if not safe_slug:
        raise ArtifactError("Artifact slug cannot be empty")
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    artifact_id = f"{kind.upper()}-{stamp}-{safe_slug}"
    folder = root / "docs" / "agent" / ARTIFACT_DIRECTORIES[kind]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp}-{safe_slug}.md"
    if path.exists():
        raise ArtifactError(f"Artifact already exists: {path}")
    metadata = {
        "schema_version": 1,
        "id": artifact_id,
        "kind": kind,
        "status": "draft",
        "task_level": "medium",
        "created_at": datetime.now(UTC).isoformat(),
        "repositories": [],
        "protected_areas": [],
    }
    heading = "QA" if kind == "qa" else kind.title()
    body = (
        f"\n# {heading}: {slug}\n\n"
        "## Goal\n\n"
        "## Confirmed facts\n\n"
        "## Assumptions\n\n"
        "## Open questions\n\n"
        "## Scope\n\n"
        "## Out of scope\n\n"
        "## Acceptance criteria\n\n"
        "## Evidence\n"
    )
    artifact = Artifact(path, metadata, body)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialize_artifact(artifact))
    except FileExistsError as exc:
        raise ArtifactError(f"Artifact already exists: {path}") from exc
    return path


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
