from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

from agentkit import __version__
from agentkit.artifacts import (
    ArtifactError,
    create_artifact,
    parse_artifact,
    serialize_artifact,
    transition,
)
from agentkit.config import (
    MANIFEST_NAMES,
    SUPPORTED_MANIFEST_VERSION,
    ConfigError,
    find_project_root,
)
from agentkit.generator import generate_claude, generate_codex, install_scaffold
from agentkit.validator import validate_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentkit", description="Governed Agent SDLC toolkit")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize Governed Agent SDLC in a project")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--name")
    init.add_argument("--adapter", choices=("none", "claude-code", "codex"), default="claude-code")
    init.add_argument("--dry-run", action="store_true")
    _add_format(init)

    validate = sub.add_parser("validate", help="Validate manifest and artifacts")
    validate.add_argument("path", nargs="?", default=".")
    _add_format(validate)

    doctor = sub.add_parser("doctor", help="Check local prerequisites and configuration")
    doctor.add_argument("path", nargs="?", default=".")
    _add_format(doctor)

    generate = sub.add_parser("generate", help="Generate an AI-tool adapter")
    generate.add_argument("adapter", choices=("claude-code", "codex"))
    generate.add_argument("path", nargs="?", default=".")
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--dry-run", action="store_true")
    _add_format(generate)

    migrate = sub.add_parser("migrate", help="Safely migrate a project manifest schema")
    migrate.add_argument("path", nargs="?", default=".")
    migrate.add_argument("--to-version", type=int, default=SUPPORTED_MANIFEST_VERSION)
    migrate.add_argument("--dry-run", action="store_true")
    _add_format(migrate)

    artifact = sub.add_parser("artifact", help="Create or transition workflow artifacts")
    artifact_sub = artifact.add_subparsers(dest="artifact_command", required=True)
    new = artifact_sub.add_parser("new")
    new.add_argument("kind", choices=("spec", "plan", "task", "review", "qa"))
    new.add_argument("slug")
    new.add_argument("--path", default=".")

    listing = artifact_sub.add_parser("list")
    listing.add_argument("--path", default=".")
    _add_format(listing)

    show = artifact_sub.add_parser("show")
    show.add_argument("artifact_path")
    show.add_argument("--path", default=".")
    _add_format(show)

    graph = artifact_sub.add_parser("graph")
    graph.add_argument("--path", default=".")
    _add_format(graph)

    move = artifact_sub.add_parser("transition")
    move.add_argument("artifact_path")
    move.add_argument("target")
    move.add_argument("--approved-by")
    move.add_argument("--evidence")

    review = sub.add_parser("review", help="Evaluate review findings or execute review provider")
    review_sub = review.add_subparsers(dest="review_command", required=True)

    evaluate = review_sub.add_parser("evaluate", help="Evaluate findings file against governance policies")
    evaluate.add_argument("findings_path", help="Path to raw findings JSON file")
    evaluate.add_argument("--output-dir", help="Directory to store review evidence")
    _add_format(evaluate)

    run_rev = review_sub.add_parser("run", help="Run a review provider and evaluate governance policies")
    run_rev.add_argument("--provider", choices=("mock", "open-code-review"), default="mock")
    run_rev.add_argument("--files", nargs="*", default=[])
    run_rev.add_argument("--output-dir", help="Directory to store review evidence")
    _add_format(run_rev)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            return _init(args)
        if args.command == "validate":
            return _validate(Path(args.path), args.output_format)
        if args.command == "doctor":
            return _doctor(Path(args.path), args.output_format)
        if args.command == "generate":
            root = find_project_root(Path(args.path))
            generator = generate_claude if args.adapter == "claude-code" else generate_codex
            generated = generator(root, force=args.force, dry_run=args.dry_run)
            _emit(
                {"adapter": args.adapter, "dry_run": args.dry_run, "paths": _paths(generated)},
                args.output_format,
                f"{'Would generate' if args.dry_run else 'Generated'} {len(generated)} "
                f"{args.adapter} file(s).",
            )
            return 0
        if args.command == "migrate":
            return _migrate(Path(args.path), args.to_version, args.dry_run, args.output_format)
        if args.command == "artifact" and args.artifact_command == "new":
            root = find_project_root(Path(args.path))
            print(create_artifact(root, args.kind, args.slug))
            return 0
        if args.command == "artifact" and args.artifact_command == "list":
            return _artifact_list(Path(args.path), args.output_format)
        if args.command == "artifact" and args.artifact_command == "show":
            return _artifact_show(Path(args.path), args.artifact_path, args.output_format)
        if args.command == "artifact" and args.artifact_command == "graph":
            return _artifact_graph(Path(args.path), args.output_format)
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
        if args.command == "review" and args.review_command == "evaluate":
            return _review_evaluate(Path(args.findings_path), args.output_dir, args.output_format)
        if args.command == "review" and args.review_command == "run":
            return _review_run(args.provider, args.files, args.output_dir, args.output_format)
    except (ArtifactError, ConfigError, OSError) as exc:
        if getattr(args, "output_format", "text") == "json":
            print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


def _project_artifact_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve()
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
    if not args.dry_run:
        destination.mkdir(parents=True, exist_ok=True)
    name = args.name or destination.name
    copied = install_scaffold(destination, name=name, dry_run=args.dry_run)
    if args.adapter == "claude-code":
        copied.extend(generate_claude(destination, dry_run=args.dry_run))
    elif args.adapter == "codex":
        copied.extend(generate_codex(destination, dry_run=args.dry_run))
    _emit(
        {
            "name": name,
            "destination": str(destination),
            "dry_run": args.dry_run,
            "paths": _paths(copied),
        },
        args.output_format,
        f"{'Would initialize' if args.dry_run else 'Initialized'} {name} at {destination} "
        f"({len(copied)} item(s) {'planned' if args.dry_run else 'created'}).",
    )
    return 0


def _validate(path: Path, output_format: str = "text") -> int:
    findings = validate_project(path.resolve())
    errors = sum(item.level == "error" for item in findings)
    warnings = sum(item.level == "warning" for item in findings)
    if output_format == "json":
        print(
            json.dumps(
                {
                    "ok": errors == 0,
                    "errors": errors,
                    "warnings": warnings,
                    "findings": [
                        {"level": item.level, "path": str(item.path), "message": item.message}
                        for item in findings
                    ],
                },
                sort_keys=True,
            )
        )
    else:
        for finding in findings:
            print(finding)
        print(f"Validation complete: {errors} error(s), {warnings} warning(s).")
    return 1 if errors else 0


def _doctor(path: Path, output_format: str = "text") -> int:
    details: dict[str, Any] = {
        "version": __version__,
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "git": shutil.which("git"),
        "uv": shutil.which("uv"),
    }
    findings = validate_project(path.resolve())
    errors = sum(item.level == "error" for item in findings)
    warnings = sum(item.level == "warning" for item in findings)
    if output_format == "json":
        details.update(
            {
                "ok": errors == 0,
                "errors": errors,
                "warnings": warnings,
                "findings": [
                    {"level": item.level, "path": str(item.path), "message": item.message}
                    for item in findings
                ],
            }
        )
        print(json.dumps(details, sort_keys=True))
    else:
        print(f"Governed Agent SDLC: {details['version']}")
        print(f"Python: {details['python']} ({details['executable']})")
        print(f"Platform: {details['platform']}")
        print(f"Git: {details['git'] or 'NOT FOUND'}")
        print(f"uv: {details['uv'] or 'NOT FOUND (optional)'}")
        for finding in findings:
            print(finding)
        print(f"Validation complete: {errors} error(s), {warnings} warning(s).")
    return 1 if errors else 0


def _artifact_files(root: Path) -> list[Path]:
    return sorted((root / "docs" / "agent").glob("**/*.md"))


def _artifact_list(path: Path, output_format: str) -> int:
    root = find_project_root(path)
    artifacts = [parse_artifact(item) for item in _artifact_files(root)]
    rows = [
        {
            "id": item.id,
            "kind": item.kind,
            "status": item.status,
            "parent": item.metadata.get("parent"),
            "path": str(item.path.relative_to(root)),
        }
        for item in artifacts
    ]
    if output_format == "json":
        print(json.dumps(rows, sort_keys=True))
    else:
        for row in rows:
            parent = f" <- {row['parent']}" if row["parent"] else ""
            print(f"{row['status']:<18} {row['kind']:<7} {row['id']}{parent}")
    return 0


def _artifact_show(path: Path, artifact_path: str, output_format: str) -> int:
    root = find_project_root(path)
    artifact = parse_artifact(_project_artifact_path(root, artifact_path))
    if output_format == "json":
        print(
            json.dumps(
                {"metadata": artifact.metadata, "body": artifact.body}, default=str, sort_keys=True
            )
        )
    else:
        print(serialize_artifact(artifact), end="")
    return 0


def _artifact_graph(path: Path, output_format: str) -> int:
    root = find_project_root(path)
    artifacts = [parse_artifact(item) for item in _artifact_files(root)]
    edges = [
        {"from": str(item.metadata["parent"]), "to": item.id}
        for item in artifacts
        if item.metadata.get("parent")
    ]
    graph = {"nodes": [item.id for item in artifacts], "edges": edges}
    if output_format == "json":
        print(json.dumps(graph, sort_keys=True))
    else:
        for edge in edges:
            print(f"{edge['from']} -> {edge['to']}")
    return 0


def _migrate(path: Path, target: int, dry_run: bool, output_format: str) -> int:
    root = find_project_root(path)
    candidates = [root / name for name in MANIFEST_NAMES if (root / name).is_file()]
    if len(candidates) != 1:
        raise ConfigError("Manifest migration requires exactly one project manifest")
    try:
        with candidates[0].open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML manifest: {exc}") from exc
    current = raw.get("version")
    if type(current) is not int:
        raise ConfigError("Manifest version must be an integer before migration")
    if target != SUPPORTED_MANIFEST_VERSION:
        raise ConfigError(f"No safe migration path to manifest version {target}")
    if current != target:
        raise ConfigError(f"No safe migration path from manifest version {current} to {target}")
    data = {
        "ok": True,
        "changed": False,
        "dry_run": dry_run,
        "version": current,
        "path": str(candidates[0]),
    }
    _emit(data, output_format, f"Manifest is already at version {current}; no changes required.")
    return 0


def _add_format(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", dest="output_format", choices=("text", "json"), default="text")


def _paths(values: list[Path]) -> list[str]:
    return [str(value) for value in values]


def _emit(data: dict[str, Any], output_format: str, text: str) -> None:
    print(json.dumps(data, sort_keys=True) if output_format == "json" else text)


def _review_evaluate(findings_path: Path, output_dir: str | None, output_format: str) -> int:
    from agentkit.policy import PolicyEngine
    from agentkit.review import FindingNormalizer, NormalizedFinding, ReviewResult, write_review_evidence

    if not findings_path.is_file():
        raise ConfigError(f"Findings file not found: {findings_path}")

    try:
        raw_text = findings_path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)
    except Exception as exc:
        raise ConfigError(f"Invalid findings JSON: {exc}") from exc

    items = parsed if isinstance(parsed, list) else parsed.get("findings", [])
    findings = [
        FindingNormalizer.normalize(item, source=findings_path.stem, fallback_id=f"f-{i+1}")
        for i, item in enumerate(items)
        if isinstance(item, dict)
    ]
    engine = PolicyEngine()
    decision = engine.evaluate(findings)

    if output_dir:
        res = ReviewResult(provider="file", passed=(decision.action == "continue"), findings=tuple(findings))
        write_review_evidence(Path(output_dir), res, decision)

    _emit(
        decision.to_dict(),
        output_format,
        f"Governance Decision: {decision.action.upper()} | Blocked: {decision.blocked} | "
        f"Requires Approval: {decision.requires_approval}\n"
        + "\n".join(f"- {r}" for r in decision.reasons),
    )
    return 1 if decision.blocked else 0


def _review_run(provider_name: str, files: list[str], output_dir: str | None, output_format: str) -> int:
    from agentkit.policy import PolicyEngine
    from agentkit.review import MockReviewProvider, OpenCodeReviewProvider, ReviewContext, write_review_evidence

    root = find_project_root()
    context = ReviewContext(run_id="cli-run", repository_root=root, files=tuple(files))
    provider = OpenCodeReviewProvider() if provider_name == "open-code-review" else MockReviewProvider()
    result = provider.review(context)

    engine = PolicyEngine()
    decision = engine.evaluate(result.findings)

    if output_dir:
        write_review_evidence(Path(output_dir), result, decision)

    _emit(
        {
            "review": result.to_dict(),
            "governance": decision.to_dict(),
        },
        output_format,
        f"Provider: {result.provider} (Passed: {result.passed})\n"
        f"Decision: {decision.action.upper()}\n"
        + "\n".join(f"- {r}" for r in decision.reasons),
    )
    return 1 if decision.blocked else 0

