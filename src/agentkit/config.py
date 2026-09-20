from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST_NAMES = ("agentkit.toml", ".agent/project.toml")
SUPPORTED_MANIFEST_VERSION = 1
SUPPORTED_TOPOLOGIES = {"single-repo", "monorepo", "polyrepo"}
WORKFLOW_FLAGS = ("require_spec", "require_plan", "require_review", "require_qa")
MANIFEST_FIELDS = {
    "version",
    "protected_areas",
    "project",
    "repositories",
    "workflow",
    "commands",
    "review",
    "policies",
    "remediation",
}
REVIEW_PROVIDERS = ("mock", "open-code-review")
REVIEW_DEFAULTS: dict[str, Any] = {
    "provider": "mock",
    "timeout_seconds": 180,
    "include_requirement": True,
    "include_spec": True,
    "include_plan": True,
}
REMEDIATION_DEFAULTS: dict[str, Any] = {"enabled": True, "max_attempts": 2}


class ConfigError(ValueError):
    """Raised when a Governed Agent SDLC manifest is invalid."""


@dataclass(frozen=True)
class Repository:
    id: str
    path: Path
    profiles: tuple[str, ...]


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    manifest_path: Path
    name: str
    repositories: tuple[Repository, ...]
    workflow: dict[str, Any]
    protected_areas: tuple[str, ...]
    commands: dict[str, Any]
    review: dict[str, Any] = field(default_factory=lambda: dict(REVIEW_DEFAULTS))
    policies: tuple[dict[str, Any], ...] = ()
    remediation: dict[str, Any] = field(default_factory=lambda: dict(REMEDIATION_DEFAULTS))


def _load_review_settings(
    raw: dict[str, Any],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any]]:
    from agentkit.policy import load_policies

    review = dict(REVIEW_DEFAULTS)
    review_raw = raw.get("review", {})
    if not isinstance(review_raw, dict):
        raise ConfigError("[review] must be a table")
    _reject_unknown_fields(review_raw, set(REVIEW_DEFAULTS), "[review]")
    review.update(review_raw)
    if review["provider"] not in REVIEW_PROVIDERS:
        raise ConfigError(f"[review].provider must be one of: {', '.join(REVIEW_PROVIDERS)}")
    timeout = review["timeout_seconds"]
    if type(timeout) is not int or not 1 <= timeout <= 3600:
        raise ConfigError("[review].timeout_seconds must be an integer between 1 and 3600")
    for flag in ("include_requirement", "include_spec", "include_plan"):
        if not isinstance(review[flag], bool):
            raise ConfigError(f"[review].{flag} must be a boolean")

    remediation = dict(REMEDIATION_DEFAULTS)
    remediation_raw = raw.get("remediation", {})
    if not isinstance(remediation_raw, dict):
        raise ConfigError("[remediation] must be a table")
    _reject_unknown_fields(remediation_raw, set(REMEDIATION_DEFAULTS), "[remediation]")
    remediation.update(remediation_raw)
    if not isinstance(remediation["enabled"], bool):
        raise ConfigError("[remediation].enabled must be a boolean")
    attempts = remediation["max_attempts"]
    if type(attempts) is not int or not 1 <= attempts <= 10:
        raise ConfigError("[remediation].max_attempts must be an integer between 1 and 10")

    policies_raw = raw.get("policies", [])
    if not isinstance(policies_raw, list) or any(
        not isinstance(item, dict) for item in policies_raw
    ):
        raise ConfigError("[[policies]] must be an array of tables")
    try:
        load_policies(policies_raw)  # validates ids, actions and field types
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return review, tuple(dict(item) for item in policies_raw), remediation


def _require_table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"[{key}] table is required")
    return value


def _reject_unknown_fields(value: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ConfigError(f"Unknown {context} fields: {', '.join(sorted(unknown))}")


def _string_list(value: Any, field: str, *, required: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ConfigError(f"{field} must be an array of non-empty strings")
    normalized = tuple(item.strip() for item in value)
    if required and not normalized:
        raise ConfigError(f"{field} must contain at least one value")
    if len(set(normalized)) != len(normalized):
        raise ConfigError(f"{field} must not contain duplicate values")
    return normalized


def _available_profiles(project_root: Path) -> set[str]:
    available: set[str] = set()
    candidates = [
        project_root / "profiles",
        Path(__file__).resolve().parents[2] / "profiles",
        Path(__file__).resolve().parent / "resources" / "profiles",
    ]
    for folder in candidates:
        if folder.is_dir():
            available.update(path.parent.name for path in folder.glob("*/profile.toml"))

    capability_roots = [
        project_root,
        Path(__file__).resolve().parents[2],
        Path(__file__).resolve().parent / "resources",
    ]
    for root in capability_roots:
        adapters = root / "adapters"
        if adapters.is_dir():
            available.update(path.name for path in adapters.iterdir() if path.is_dir())
        if (root / ".github").is_dir():
            available.add("github")
    if not available:
        raise ConfigError("Profile definitions are missing from the project and installed package")
    return available


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if any((candidate / name).is_file() for name in MANIFEST_NAMES):
            return candidate
    raise ConfigError("No agentkit.toml or .agent/project.toml found. Run `agentkit init`.")


def manifest_path(root: Path) -> Path:
    for name in MANIFEST_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise ConfigError(f"No Governed Agent SDLC manifest found under {root}")


def load_config(root: Path | None = None) -> ProjectConfig:
    project_root = find_project_root(root) if root else find_project_root()
    path = manifest_path(project_root)
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML manifest: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Manifest root must be a TOML table")
    _reject_unknown_fields(raw, MANIFEST_FIELDS, "manifest")
    if type(raw.get("version")) is not int or raw["version"] != SUPPORTED_MANIFEST_VERSION:
        raise ConfigError(f"version must be {SUPPORTED_MANIFEST_VERSION}")

    project = _require_table(raw, "project")
    _reject_unknown_fields(project, {"name", "topology"}, "[project]")
    name_value = project.get("name")
    name = name_value.strip() if isinstance(name_value, str) else ""
    if not name:
        raise ConfigError("[project].name is required")
    topology = project.get("topology")
    if topology not in SUPPORTED_TOPOLOGIES:
        choices = ", ".join(sorted(SUPPORTED_TOPOLOGIES))
        raise ConfigError(f"[project].topology must be one of: {choices}")

    repository_entries = raw.get("repositories")
    if not isinstance(repository_entries, list) or not repository_entries:
        raise ConfigError("At least one [[repositories]] entry is required")
    known_profiles = _available_profiles(project_root)

    repositories: list[Repository] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for index, item in enumerate(repository_entries):
        if not isinstance(item, dict):
            raise ConfigError(f"repositories[{index}] must be a table")
        _reject_unknown_fields(item, {"id", "path", "profiles"}, f"repositories[{index}]")
        repo_id_value = item.get("id")
        repo_path_value = item.get("path")
        repo_id = repo_id_value.strip() if isinstance(repo_id_value, str) else ""
        repo_path = repo_path_value.strip() if isinstance(repo_path_value, str) else ""
        if not repo_id or not repo_path:
            raise ConfigError("Every [[repositories]] entry requires id and path")
        if repo_id in seen_ids:
            raise ConfigError(f"Duplicate repository id: {repo_id}")
        seen_ids.add(repo_id)
        resolved = (project_root / repo_path).resolve()
        try:
            resolved.relative_to(project_root)
        except ValueError as exc:
            raise ConfigError(
                f"Repository path must stay within the project root: {repo_path}"
            ) from exc
        if resolved in seen_paths:
            raise ConfigError(f"Duplicate repository path: {repo_path}")
        seen_paths.add(resolved)
        profiles = _string_list(
            item.get("profiles"), f"repositories[{index}].profiles", required=True
        )
        unknown_profiles = set(profiles) - known_profiles
        if unknown_profiles:
            raise ConfigError(f"Unknown profiles: {', '.join(sorted(unknown_profiles))}")
        repositories.append(Repository(repo_id, resolved, profiles))

    workflow = _require_table(raw, "workflow")
    _reject_unknown_fields(workflow, set(WORKFLOW_FLAGS), "[workflow]")
    for flag in WORKFLOW_FLAGS:
        if not isinstance(workflow.get(flag), bool):
            raise ConfigError(f"[workflow].{flag} must be a boolean")

    protected_areas = _string_list(raw.get("protected_areas", []), "protected_areas")
    commands = raw.get("commands", {})
    if not isinstance(commands, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in commands.items()
    ):
        raise ConfigError("[commands] values must be strings")

    review, policies, remediation = _load_review_settings(raw)
    return ProjectConfig(
        root=project_root,
        manifest_path=path,
        name=name,
        repositories=tuple(repositories),
        workflow=dict(workflow),
        protected_areas=protected_areas,
        commands=dict(commands),
        review=review,
        policies=policies,
        remediation=remediation,
    )


def portable_python_command(script: str) -> str:
    """Return a command that avoids machine-specific Python executable paths."""
    if os.name == "nt":
        return f'uv run --no-project python "{script}"'
    return f'uv run --no-project python "{script}"'
