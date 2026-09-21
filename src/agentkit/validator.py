from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agentkit.artifacts import (
    ALLOWED_TRANSITIONS,
    ARTIFACT_KINDS,
    Artifact,
    ArtifactError,
    parse_artifact,
)
from agentkit.config import ConfigError, ProjectConfig, load_config

TASK_LEVELS = {"small", "medium", "high_risk"}
APPROVED_HISTORY_STATUSES = {"approved", "active", "completed", "superseded"}
PARENT_RULES = {
    "plan": ("spec", {"approved", "active", "completed"}, "require_spec"),
    "task": ("plan", {"approved", "active", "completed"}, "require_plan"),
    "review": ("task", {"completed"}, "require_review"),
    "qa": ("review", {"completed"}, "require_qa"),
}
ARTIFACT_FIELDS = {
    "schema_version",
    "id",
    "kind",
    "status",
    "task_level",
    "created_at",
    "updated_at",
    "supersedes",
    "parent",
    "repositories",
    "protected_areas",
    "approval",
}


@dataclass(frozen=True)
class Finding:
    level: str
    path: Path
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()}: {self.path}: {self.message}"


def validate_project(root: Path | None = None) -> list[Finding]:
    findings: list[Finding] = []
    try:
        config = load_config(root)
    except ConfigError as exc:
        return [Finding("error", root or Path.cwd(), str(exc))]

    findings.extend(_validate_repositories(config))
    artifacts, parse_findings = _load_artifacts(config.root)
    findings.extend(parse_findings)
    findings.extend(_validate_artifacts(config, artifacts))
    findings.extend(_validate_review_runs(config.root))
    return findings


def _validate_review_runs(root: Path) -> list[Finding]:
    """Check stored review evidence: attempt schemas, approval records and the event log."""
    from agentkit.approval import AI_ACTOR_TOKENS, VALID_DECISIONS
    from agentkit.events import validate_events
    from agentkit.remediation import existing_attempts
    from agentkit.review import validate_review_evidence
    from agentkit.runs import RUNS_RELATIVE

    findings: list[Finding] = []
    runs_root = root / RUNS_RELATIVE
    if not runs_root.is_dir():
        return findings
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        for number in existing_attempts(run_dir):
            attempt_dir = run_dir / f"review-attempt-{number}"
            for problem in validate_review_evidence(attempt_dir):
                findings.append(Finding("error", attempt_dir, problem))
        for problem in validate_events(run_dir):
            findings.append(Finding("error", run_dir, problem))
        for file in sorted((run_dir / "approvals").glob("review-approval-*.json")):
            findings.extend(_validate_approval_file(file, AI_ACTOR_TOKENS, VALID_DECISIONS))
    return findings


def _validate_approval_file(
    file: Path, ai_tokens: frozenset[str], decisions: tuple[str, ...]
) -> list[Finding]:
    import json
    import re

    try:
        record = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Finding("error", file, f"Approval record is unreadable: {exc}")]
    if not isinstance(record, dict):
        return [Finding("error", file, "Approval record must be an object")]
    problems: list[str] = []
    if record.get("decision") not in decisions:
        problems.append("decision must be approved or rejected")
    actor = record.get("actor")
    if not isinstance(actor, str) or not actor.strip():
        problems.append("actor is required")
    elif any(token in ai_tokens for token in re.split(r"[^a-z0-9]+", actor.lower()) if token):
        problems.append("actor must be a human identity, not an AI agent")
    evidence = record.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        problems.append("evidence is required")
    if not isinstance(record.get("policyId"), str):
        problems.append("policyId is required")
    return [Finding("error", file, problem) for problem in problems]


def _validate_repositories(config: ProjectConfig) -> list[Finding]:
    findings: list[Finding] = []
    if not config.repositories:
        findings.append(Finding("warning", config.manifest_path, "No repositories are configured"))
    for repo in config.repositories:
        if not repo.path.exists():
            findings.append(
                Finding(
                    "error", config.manifest_path, f"Repository path does not exist: {repo.path}"
                )
            )
    return findings


def _load_artifacts(root: Path) -> tuple[list[Artifact], list[Finding]]:
    artifacts: list[Artifact] = []
    findings: list[Finding] = []
    artifact_root = root / "docs" / "agent"
    if not artifact_root.exists():
        return artifacts, findings
    for path in sorted(artifact_root.glob("**/*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            artifacts.append(parse_artifact(path))
        except (ArtifactError, OSError) as exc:
            findings.append(Finding("error", path, str(exc)))
    return artifacts, findings


def _validate_artifacts(config: ProjectConfig, artifacts: list[Artifact]) -> list[Finding]:
    findings: list[Finding] = []
    by_id: dict[str, Artifact] = {}
    repo_ids = {repo.id for repo in config.repositories}
    protected_areas = set(config.protected_areas)

    for artifact in artifacts:
        unknown_fields = set(artifact.metadata) - ARTIFACT_FIELDS
        if unknown_fields:
            findings.append(
                Finding(
                    "error",
                    artifact.path,
                    f"Unknown metadata fields: {', '.join(sorted(unknown_fields))}",
                )
            )
        for key in ("schema_version", "id", "kind", "status", "task_level"):
            if artifact.metadata.get(key) in (None, ""):
                findings.append(Finding("error", artifact.path, f"Missing required field: {key}"))
        if artifact.id in by_id:
            findings.append(
                Finding("error", artifact.path, f"Duplicate artifact id: {artifact.id}")
            )
        elif artifact.id:
            by_id[artifact.id] = artifact
        if artifact.kind not in ARTIFACT_KINDS:
            findings.append(Finding("error", artifact.path, f"Unknown kind: {artifact.kind}"))
        elif artifact.id and not artifact.id.startswith(f"{artifact.kind.upper()}-"):
            findings.append(
                Finding("error", artifact.path, "Artifact id prefix does not match kind")
            )
        if artifact.status not in ALLOWED_TRANSITIONS:
            findings.append(Finding("error", artifact.path, f"Unknown status: {artifact.status}"))
        if (
            type(artifact.metadata.get("schema_version")) is not int
            or artifact.metadata["schema_version"] != 1
        ):
            findings.append(Finding("error", artifact.path, "schema_version must be 1"))
        if artifact.metadata.get("task_level") not in TASK_LEVELS:
            findings.append(Finding("error", artifact.path, "Unknown task_level"))
        for key in ("created_at", "updated_at"):
            value = artifact.metadata.get(key)
            if value not in (None, "") and not _valid_timestamp(value):
                findings.append(
                    Finding("error", artifact.path, f"{key} must be an ISO-8601 timestamp")
                )

        artifact_repos, error = _metadata_string_list(artifact.metadata, "repositories")
        if error:
            findings.append(Finding("error", artifact.path, error))
        unknown_repos = set(artifact_repos) - repo_ids
        if unknown_repos:
            findings.append(
                Finding(
                    "error",
                    artifact.path,
                    f"Unknown repositories: {', '.join(sorted(unknown_repos))}",
                )
            )
        artifact_areas, error = _metadata_string_list(artifact.metadata, "protected_areas")
        if error:
            findings.append(Finding("error", artifact.path, error))
        unknown_areas = set(artifact_areas) - protected_areas
        if unknown_areas:
            findings.append(
                Finding(
                    "error",
                    artifact.path,
                    f"Unknown protected areas: {', '.join(sorted(unknown_areas))}",
                )
            )

        approval_value = artifact.metadata.get("approval")
        approval_required = artifact.status in APPROVED_HISTORY_STATUSES
        if approval_value is not None or approval_required:
            approval = approval_value if isinstance(approval_value, dict) else {}
            if approval_value is not None and not isinstance(approval_value, dict):
                findings.append(Finding("error", artifact.path, "approval must be a table"))
            unexpected = set(approval) - {"approved_by", "approved_at", "evidence"}
            if unexpected:
                findings.append(
                    Finding(
                        "error",
                        artifact.path,
                        f"Unknown approval fields: {', '.join(sorted(unexpected))}",
                    )
                )
            missing = []
            for key in ("approved_by", "approved_at", "evidence"):
                value = approval.get(key)
                if not isinstance(value, str) or not value.strip():
                    missing.append(key)
            if missing:
                findings.append(
                    Finding(
                        "error", artifact.path, f"Approved artifact lacks: {', '.join(missing)}"
                    )
                )
            elif not _valid_timestamp(approval["approved_at"]):
                findings.append(
                    Finding(
                        "error", artifact.path, "approval.approved_at must be an ISO-8601 timestamp"
                    )
                )

    for artifact in artifacts:
        parent_value = artifact.metadata.get("parent", "")
        parent_id = parent_value if isinstance(parent_value, str) else ""
        rule = PARENT_RULES.get(artifact.kind)
        if rule is not None and config.workflow.get(rule[2]) and not parent_id:
            findings.append(
                Finding("error", artifact.path, f"{artifact.kind} requires a parent {rule[0]}")
            )
        if parent_id:
            parent = by_id.get(parent_id)
            if not parent:
                findings.append(Finding("error", artifact.path, f"Parent not found: {parent_id}"))
            elif rule:
                expected_kind, allowed_statuses, _ = rule
                if parent.kind != expected_kind:
                    findings.append(
                        Finding(
                            "error",
                            artifact.path,
                            f"{artifact.kind} parent must be {expected_kind}: {parent_id}",
                        )
                    )
                elif parent.status not in allowed_statuses:
                    findings.append(
                        Finding(
                            "error",
                            artifact.path,
                            f"Parent gate is not satisfied: {parent_id} ({parent.status})",
                        )
                    )
        elif parent_value not in (None, ""):
            findings.append(Finding("error", artifact.path, "parent must be a string"))

        supersedes_value = artifact.metadata.get("supersedes", "")
        supersedes = supersedes_value if isinstance(supersedes_value, str) else ""
        if supersedes:
            if supersedes == artifact.id:
                findings.append(Finding("error", artifact.path, "Artifact cannot supersede itself"))
                continue
            old = by_id.get(supersedes)
            if not old:
                findings.append(
                    Finding("error", artifact.path, f"Superseded artifact not found: {supersedes}")
                )
            elif old.kind != artifact.kind:
                findings.append(
                    Finding(
                        "error", artifact.path, f"Cannot supersede a different kind: {supersedes}"
                    )
                )
            elif old.status not in {"superseded", "archived"}:
                findings.append(
                    Finding(
                        "error",
                        artifact.path,
                        f"Replaced artifact still appears active: {supersedes} ({old.status})",
                    )
                )
        elif supersedes_value not in (None, ""):
            findings.append(Finding("error", artifact.path, "supersedes must be a string"))

    findings.extend(_reference_cycle_findings(artifacts, "parent"))
    findings.extend(_reference_cycle_findings(artifacts, "supersedes"))
    return findings


def _reference_cycle_findings(artifacts: list[Artifact], field: str) -> list[Finding]:
    by_id = {artifact.id: artifact for artifact in artifacts if artifact.id}
    findings: list[Finding] = []
    reported: set[frozenset[str]] = set()
    for artifact in artifacts:
        chain: list[str] = []
        positions: dict[str, int] = {}
        current = artifact
        while current.id in by_id:
            if current.id in positions:
                cycle = chain[positions[current.id] :]
                signature = frozenset(cycle)
                if signature not in reported:
                    reported.add(signature)
                    findings.append(
                        Finding(
                            "error",
                            current.path,
                            f"{field} reference cycle: {' -> '.join((*cycle, current.id))}",
                        )
                    )
                break
            positions[current.id] = len(chain)
            chain.append(current.id)
            target = current.metadata.get(field)
            if not isinstance(target, str) or target not in by_id:
                break
            current = by_id[target]
    return findings


def _metadata_string_list(metadata: dict[str, Any], key: str) -> tuple[tuple[str, ...], str | None]:
    value = metadata.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        return (), f"{key} must be an array of non-empty strings"
    if len(set(value)) != len(value):
        return tuple(value), f"{key} must not contain duplicate values"
    return tuple(value), None


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None
