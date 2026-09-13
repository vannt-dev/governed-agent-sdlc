from __future__ import annotations

import argparse
import platform
import shutil
import sys
from pathlib import Path

from agentkit import __version__
from agentkit.artifacts import ArtifactError, create_artifact, parse_artifact, serialize_artifact, transition
from agentkit.config import ConfigError, find_project_root
from agentkit.generator import generate_claude, install_scaffold
from agentkit.validator import validate_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentkit", description="Governed Agent SDLC toolkit")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize Governed Agent SDLC in a project")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--name")
    init.add_argument("--adapter", choices=("none", "claude-code"), default="claude-code")

    validate = sub.add_parser("validate", help="Validate manifest and artifacts")
    validate.add_argument("path", nargs="?", default=".")

    doctor = sub.add_parser("doctor", help="Check local prerequisites and configuration")
    doctor.add_argument("path", nargs="?", default=".")

    generate = sub.add_parser("generate", help="Generate an AI-tool adapter")
    generate.add_argument("adapter", choices=("claude-code",))
    generate.add_argument("path", nargs="?", default=".")
    generate.add_argument("--force", action="store_true")

    artifact = sub.add_parser("artifact", help="Create or transition workflow artifacts")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    new = artifact_sub.add_parser("new")
    new.add_argument("kind", choices=("spec", "plan", "task", "review", "qa"))
    new.add_argument("slug")
    new.add_argument("--path", default=".")

    move = artifact_sub.add_parser("transition")
    move.add_argument("artifact_path")
    move.add_argument("target")
    move.add_argument("--approved-by")
    move.add_argument("--evidence")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            return _init(args)
        if args.command == "validate":
            return _validate(Path(args.path))
        if args.command == "doctor":
            return _doctor(Path(args.path))
        if args.command == "generate":
            root = find_project_root(Path(args.path))
            generated = generate_claude(root, force=args.force)
            print(f"Generated {len(generated)} Claude Code file(s).")
            return 0
        if args.command == "artifact" and args.artifact_command == "new":
            root = find_project_root(Path(args.path))
            print(create_artifact(root, args.kind, args.slug))
            return 0
        if args.command == "artifact" and args.artifact_command == "transition":
            root = find_project_root()
            path = _project_artifact_path(root, args.artifact_path)
            artifact = parse_artifact(path)
            updated = transition(
                artifact,
                args.target,
                approved_by=args.approved_by,
                evidence=args.evidence,
            )
            path.write_text(serialize_artifact(updated), encoding="utf-8")
            print(f"{artifact.status} -> {updated.status}: {path}")
            return 0
    except (ArtifactError, ConfigError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


def _project_artifact_path(root: Path, value: str) -> Path:
    path = Path(value).resolve()
    artifact_root = (root / "docs" / "agent").resolve()
    try:
        path.relative_to(artifact_root)
    except ValueError as exc:
        raise ArtifactError(f"Artifact must stay within {artifact_root}: {path}") from exc
    if path.suffix.lower() != ".md":
        raise ArtifactError(f"Artifact must be a Markdown file: {path}")
    return path


def _init(args: argparse.Namespace) -> int:
    destination = Path(args.path).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    name = args.name or destination.name
    copied = install_scaffold(destination, name=name)
    if args.adapter == "claude-code":
        copied.extend(generate_claude(destination))
    print(f"Initialized {name} at {destination} ({len(copied)} item(s) created).")
    return 0


def _validate(path: Path) -> int:
    findings = validate_project(path.resolve())
    for finding in findings:
        print(finding)
    errors = sum(item.level == "error" for item in findings)
    warnings = sum(item.level == "warning" for item in findings)
    print(f"Validation complete: {errors} error(s), {warnings} warning(s).")
    return 1 if errors else 0


def _doctor(path: Path) -> int:
    print(f"Governed Agent SDLC: {__version__}")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"Platform: {platform.platform()}")
    print(f"Git: {shutil.which('git') or 'NOT FOUND'}")
    print(f"uv: {shutil.which('uv') or 'NOT FOUND (optional)'}")
    return _validate(path)
