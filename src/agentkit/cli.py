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
from agentkit.events import emit_event
from agentkit.generator import generate_claude, generate_codex, install_scaffold
from agentkit.runs import EXIT_PROVIDER_ERROR, GateStatus
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

    evaluate = review_sub.add_parser(
        "evaluate", help="Evaluate findings file against governance policies"
    )
    evaluate.add_argument("findings_path", help="Path to raw findings JSON file")
    evaluate.add_argument("--output-dir", help="Directory to store review evidence")
    _add_format(evaluate)

    run_rev = review_sub.add_parser(
        "run", help="Run a review provider and evaluate governance policies"
    )
    run_rev.add_argument(
        "--provider",
        choices=("mock", "open-code-review", "cli"),
        help="Defaults to [review].provider",
    )
    run_rev.add_argument("--run-id", help="Reuse a run id to record another review attempt")
    run_rev.add_argument(
        "--requirement", help="Requirement file passed to the reviewer as background"
    )
    run_rev.add_argument("--spec", help="Specification file passed to the reviewer as background")
    run_rev.add_argument("--plan", help="Plan file passed to the reviewer as background")
    run_rev.add_argument("--from", dest="from_ref", help="Review the diff starting at this ref")
    run_rev.add_argument("--to", dest="to_ref", help="Review the diff ending at this ref")
    run_rev.add_argument("--commit", help="Review a single commit")
    run_rev.add_argument(
        "--artifact", help="Review artifact under docs/agent this run provides evidence for"
    )
    run_rev.add_argument("--mock-findings", help="JSON findings returned by the mock provider")
    run_rev.add_argument("--files", nargs="*", default=[], help=argparse.SUPPRESS)
    run_rev.add_argument(
        "--output-dir", help="Run directory for evidence (default: .agent/runs/<run-id>)"
    )
    _add_format(run_rev)

    approve = review_sub.add_parser("approve", help="Record a human decision for a review policy")
    approve.add_argument("--run-id", required=True)
    approve.add_argument("--attempt", type=int, help="Defaults to the latest attempt")
    approve.add_argument("--policy", required=True)
    approve.add_argument("--actor", required=True, help="Durable human identity, never an AI agent")
    approve.add_argument(
        "--evidence", required=True, help="Ticket, PR or review URL backing the decision"
    )
    approve.add_argument(
        "--reject", action="store_true", help="Record a rejection instead of an approval"
    )
    _add_format(approve)

    status = review_sub.add_parser(
        "status", help="Recompute the gate status of a run from recorded evidence"
    )
    status.add_argument("--run-id", required=True)
    status.add_argument("--attempt", type=int, help="Defaults to the latest attempt")
    _add_format(status)

    recover = review_sub.add_parser(
        "recover", help="Seal an interrupted attempt without overwriting evidence"
    )
    recover.add_argument("--run-id", required=True)
    recover.add_argument("--attempt", type=int)
    _add_format(recover)

    report = review_sub.add_parser("report", help="Summarize a run from its stored evidence")
    report.add_argument("--run-id", required=True)
    report.add_argument("--html", help="Also write a static HTML report to this file")
    _add_format(report)

    preview = review_sub.add_parser(
        "preview", help="Ask OpenCodeReview which files are reviewable (no LLM)"
    )
    preview.add_argument("--from", dest="from_ref")
    preview.add_argument("--to", dest="to_ref")
    preview.add_argument("--commit")
    _add_format(preview)

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
            if artifact.kind == "review" and args.target.strip().lower() == "completed":
                from agentkit.config import load_config
                from agentkit.runs import require_artifact_gate

                if load_config(root).review["enforce_artifact_gate"]:
                    require_artifact_gate(root, artifact.id, path)
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
            return _review_run(args)
        if args.command == "review" and args.review_command == "approve":
            return _review_approve(args)
        if args.command == "review" and args.review_command == "status":
            return _review_status(args)
        if args.command == "review" and args.review_command == "recover":
            return _review_recover(args)
        if args.command == "review" and args.review_command == "preview":
            return _review_preview(args)
        if args.command == "review" and args.review_command == "report":
            return _review_report(args)
    except (ArtifactError, ConfigError, OSError, ValueError) as exc:
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


def _project_policies() -> list[dict[str, Any]]:
    """Configured `[[policies]]` of the enclosing project; none (the defaults) outside a project."""
    from agentkit.config import load_config

    try:
        root = find_project_root()
    except ConfigError:
        return []
    return list(load_config(root).policies)


def _review_evaluate(findings_path: Path, output_dir: str | None, output_format: str) -> int:
    from agentkit.policy import PolicyEngine, load_policies
    from agentkit.review import (
        FindingNormalizer,
        ReviewResult,
        write_review_evidence,
    )

    if not findings_path.is_file():
        raise ConfigError(f"Findings file not found: {findings_path}")

    try:
        raw_text = findings_path.read_text(encoding="utf-8")
        parsed = json.loads(raw_text)
    except Exception as exc:
        raise ConfigError(f"Invalid findings JSON: {exc}") from exc

    items = parsed if isinstance(parsed, list) else parsed.get("findings", [])
    findings = [
        FindingNormalizer.normalize(item, source=findings_path.stem, fallback_id=f"f-{i + 1}")
        for i, item in enumerate(items)
        if isinstance(item, dict)
    ]
    engine = PolicyEngine(load_policies(_project_policies()))
    decision = engine.evaluate(findings)

    if output_dir:
        res = ReviewResult(
            provider="file", passed=(decision.action == "continue"), findings=tuple(findings)
        )
        write_review_evidence(Path(output_dir), res, decision)

    _emit(
        decision.to_dict(),
        output_format,
        f"Governance Decision: {decision.action.upper()} | Blocked: {decision.blocked} | "
        f"Requires Approval: {decision.requires_approval}\n"
        + "\n".join(f"- {r}" for r in decision.reasons),
    )
    return 1 if decision.blocked else 0


def _load_mock_findings(path: str | None) -> list[Any]:
    from agentkit.review import FindingNormalizer

    if not path:
        return []
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"Mock findings file not found: {file}")
    try:
        parsed = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid mock findings JSON: {exc}") from exc
    items = parsed if isinstance(parsed, list) else parsed.get("findings", [])
    return [
        FindingNormalizer.normalize(item, source="mock", fallback_id=f"mock-{i + 1}")
        for i, item in enumerate(items)
        if isinstance(item, dict)
    ]


def _review_run_directory(args: argparse.Namespace, root: Path) -> tuple[str, Path]:
    from agentkit.runs import new_run_id, run_directory, validate_run_id

    run_id = validate_run_id(args.run_id) if args.run_id else new_run_id()
    if getattr(args, "output_dir", None):
        return run_id, Path(args.output_dir).resolve()
    return run_id, run_directory(root, run_id)


def _review_run(args: argparse.Namespace) -> int:
    from agentkit.locking import run_lock

    root = find_project_root()
    run_id, run_dir = _review_run_directory(args, root)
    args.run_id = run_id
    with run_lock(run_dir):
        return _review_run_locked(args)


def _review_run_locked(args: argparse.Namespace) -> int:
    import time

    from agentkit.config import load_config
    from agentkit.freshness import capture_source
    from agentkit.policy import PolicyEngine, load_policies, provider_error_decision
    from agentkit.remediation import RemediationManager, next_attempt_number
    from agentkit.review import (
        FindingNormalizer,
        MockReviewProvider,
        OpenCodeReviewProvider,
        ReviewContext,
        ReviewProviderError,
        write_provider_error_evidence,
    )
    from agentkit.runs import build_review_background, read_bounded_text, review_gate_status

    root = find_project_root()
    config = load_config(root)
    provider_name = args.provider or config.review["provider"]
    run_id, run_dir = _review_run_directory(args, root)
    attempt_number = next_attempt_number(run_dir)
    attempt_dir = run_dir / f"review-attempt-{attempt_number}"
    if args.files:
        print(
            "NOTE: --files is ignored; OpenCodeReview selects files from the diff.", file=sys.stderr
        )

    background = build_review_background(
        run_dir,
        requirement=(
            read_bounded_text(Path(args.requirement))
            if args.requirement and config.review["include_requirement"]
            else None
        ),
        specification=(
            read_bounded_text(Path(args.spec))
            if args.spec and config.review["include_spec"]
            else None
        ),
        plan=read_bounded_text(Path(args.plan))
        if args.plan and config.review["include_plan"]
        else None,
    )
    context = ReviewContext(
        run_id=run_id,
        repository_root=root,
        background_file=str(background) if background else None,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
        commit=args.commit,
    )
    if provider_name == "open-code-review":
        provider: Any = OpenCodeReviewProvider(timeout_seconds=config.review["timeout_seconds"])
    elif provider_name == "cli":
        from agentkit.cli_review import CliReviewProvider

        provider = CliReviewProvider(timeout_seconds=config.review["timeout_seconds"])
    else:
        provider = MockReviewProvider(findings=_load_mock_findings(args.mock_findings))

    engine = PolicyEngine(load_policies(list(config.policies)))
    manager = RemediationManager(
        max_attempts=config.remediation["max_attempts"], enabled=config.remediation["enabled"]
    )

    artifact_ref = _artifact_reference(root, args.artifact)
    snapshot = capture_source(
        root, {"from": args.from_ref, "to": args.to_ref, "commit": args.commit}, background
    )
    attempt_dir.mkdir(parents=True, exist_ok=False)
    (attempt_dir / "source.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    (attempt_dir / "in-progress").write_text("Review has not finalized\n", encoding="utf-8")
    emit_event(
        run_dir,
        run_id,
        "review.started",
        {"attempt": attempt_number, "provider": provider_name, "artifact": artifact_ref},
    )
    started = time.monotonic()
    try:
        result = provider.review(context)
        if (
            capture_source(root, snapshot["refs"], background)["fingerprint"]
            != snapshot["fingerprint"]
        ):
            raise ReviewProviderError(
                "stale",
                "Source or review inputs changed while the reviewer was running",
                result.findings,
            )
    except ReviewProviderError as error:
        decision = provider_error_decision(error.kind, error.message)
        write_provider_error_evidence(attempt_dir, provider_name, error, decision)
        (attempt_dir / "in-progress").unlink()
        emit_event(
            run_dir, run_id, "review.failed", {"attempt": attempt_number, "kind": error.kind}
        )
        gate = GateStatus("provider-error", EXIT_PROVIDER_ERROR, error.message)
        _emit(
            {
                "run": {"id": run_id, "attempt": attempt_number, "directory": str(run_dir)},
                "error": error.to_dict(),
                "governance": decision.to_dict(),
                "gate": gate.to_dict(),
            },
            args.output_format,
            f"Review provider failed ({error.kind}): {error.message}\n"
            f"Run: {run_id} attempt {attempt_number}",
        )
        return EXIT_PROVIDER_ERROR

    decision = engine.evaluate(result.findings)
    _, limited = manager.record_attempt(
        run_dir,
        result,
        decision,
        provider_meta={
            "runId": run_id,
            "wallMs": int((time.monotonic() - started) * 1000),
            "artifact": artifact_ref,
            "approvalMode": config.review["approval_mode"],
        },
        attempt_number=attempt_number,
    )
    (attempt_dir / "in-progress").unlink()
    gate = review_gate_status(
        limited, run_dir, attempt_number, nothing_to_review=result.nothing_to_review
    )
    findings_total = len(result.findings)
    emit_event(
        run_dir, run_id, "review.completed", {"attempt": attempt_number, "findings": findings_total}
    )
    fired = [d.policy_id for d in limited.decisions]
    emit_event(
        run_dir,
        run_id,
        "policy.evaluated",
        {"attempt": attempt_number, "decision": limited.action, "policies": fired},
    )
    if limited.action == "block":
        emit_event(
            run_dir, run_id, "policy.blocked", {"attempt": attempt_number, "policies": fired}
        )
    for policy_id, _ in limited.policy_ids_for("require-human-approval"):
        emit_event(
            run_dir,
            run_id,
            "policy.approval_required",
            {"attempt": attempt_number, "policy": policy_id},
        )
    unresolved = _unresolved_from_previous(
        run_dir, attempt_number, result.findings, FindingNormalizer
    )

    _emit(
        {
            "run": {"id": run_id, "attempt": attempt_number, "directory": str(run_dir)},
            "review": result.to_dict(),
            "governance": limited.to_dict(),
            "gate": gate.to_dict(),
            "unresolvedFromPreviousAttempt": [f.id for f in unresolved],
        },
        args.output_format,
        f"Provider: {result.provider} (Passed: {result.passed})\n"
        f"Decision: {limited.action.upper()} | Gate: {gate.status} | "
        f"Run: {run_id} attempt {attempt_number}\n" + "\n".join(f"- {r}" for r in limited.reasons),
    )
    return gate.exit_code


def _unresolved_from_previous(
    run_dir: Path, attempt: int, current: Any, normalizer: Any
) -> list[Any]:
    from agentkit.remediation import RemediationManager

    previous_file = run_dir / f"review-attempt-{attempt - 1}" / "findings.json"
    if attempt < 2 or not previous_file.is_file():
        return []
    try:
        items = json.loads(previous_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    previous = [
        normalizer.normalize(item, source="previous") for item in items if isinstance(item, dict)
    ]
    return RemediationManager.detect_unresolved_findings(previous, list(current))


def _latest_attempt(run_dir: Path, requested: int | None) -> int:
    from agentkit.remediation import existing_attempts

    attempts = existing_attempts(run_dir)
    if not attempts:
        raise ConfigError(f"No review attempts found under {run_dir}")
    if requested is None:
        return attempts[-1]
    if requested not in attempts:
        raise ConfigError(f"Review attempt {requested} does not exist under {run_dir}")
    return requested


def _review_approve(args: argparse.Namespace) -> int:
    from agentkit.locking import run_lock
    from agentkit.runs import run_directory

    with run_lock(run_directory(find_project_root(), args.run_id)):
        return _review_approve_locked(args)


def _review_approve_locked(args: argparse.Namespace) -> int:
    from agentkit.approval import record_review_approval
    from agentkit.policy import GovernanceDecision
    from agentkit.runs import attempt_gate, run_directory

    root = find_project_root()
    run_dir = run_directory(root, args.run_id)
    attempt = _latest_attempt(run_dir, args.attempt)
    _, existing_gate = attempt_gate(run_dir, attempt, root=root)
    if existing_gate.status in ("stale", "unverified", "provider-error"):
        raise ConfigError(existing_gate.detail)
    policy_file = run_dir / f"review-attempt-{attempt}" / "policy-result.json"
    if not policy_file.is_file():
        raise ConfigError(f"Attempt {attempt} has no policy-result.json; nothing to approve")
    decision = GovernanceDecision.from_dict(json.loads(policy_file.read_text(encoding="utf-8")))
    fired = dict(decision.policy_ids_for("require-human-approval"))
    if args.policy not in fired:
        raise ConfigError(
            f"Policy '{args.policy}' did not require human approval on attempt {attempt}. "
            f"Policies awaiting approval: {', '.join(fired) or 'none'}"
        )
    verification = None
    provider_meta = json.loads((policy_file.parent / "provider.json").read_text(encoding="utf-8"))
    if provider_meta.get("approvalMode") == "github":
        from agentkit.github_approval import verify_github_review

        snapshot = json.loads((policy_file.parent / "source.json").read_text(encoding="utf-8"))
        verification = verify_github_review(
            root, args.evidence, args.actor, "rejected" if args.reject else "approved", snapshot
        )
    record = record_review_approval(
        run_dir,
        args.policy,
        fired[args.policy],
        args.actor,
        args.evidence,
        decision="rejected" if args.reject else "approved",
        attempt=attempt,
        verification=verification,
    )
    emit_event(
        run_dir,
        args.run_id,
        "approval.rejected" if args.reject else "approval.granted",
        {"attempt": attempt, "policy": args.policy},
    )
    _, gate = attempt_gate(run_dir, attempt, root=root)
    _emit(
        {"record": str(record), "attempt": attempt, "gate": gate.to_dict()},
        args.output_format,
        f"Recorded {'rejection' if args.reject else 'approval'} for {args.policy}: {record}\n"
        f"Gate: {gate.status}",
    )
    return gate.exit_code


def _review_status(args: argparse.Namespace) -> int:
    from agentkit.runs import attempt_gate, run_directory

    root = find_project_root()
    run_dir = run_directory(root, args.run_id)
    attempt = _latest_attempt(run_dir, args.attempt)
    decision, gate = attempt_gate(run_dir, attempt, root=root)
    _emit(
        {
            "run": {"id": args.run_id, "attempt": attempt},
            "governance": decision.to_dict(),
            "gate": gate.to_dict(),
        },
        args.output_format,
        f"Run {args.run_id} attempt {attempt}: {gate.status}\n{gate.detail}",
    )
    return gate.exit_code


def _review_recover(args: argparse.Namespace) -> int:
    from agentkit.locking import run_lock
    from agentkit.runs import recover_attempt, run_directory

    run_dir = run_directory(find_project_root(), args.run_id)
    with run_lock(run_dir):
        attempt = _latest_attempt(run_dir, args.attempt)
        recover_attempt(run_dir, args.run_id, attempt)
    _emit(
        {"recovered": True, "attempt": attempt},
        args.output_format,
        f"Sealed interrupted attempt {attempt}. Run review again for new evidence.",
    )
    return 0


def _artifact_reference(root: Path, value: str | None) -> dict[str, str] | None:
    """Link a run to a review artifact so the workflow record can point at its evidence."""
    if not value:
        return None
    path = _project_artifact_path(root, value)
    artifact = parse_artifact(path)
    if artifact.kind != "review":
        raise ArtifactError(f"--artifact must be a review artifact, found kind '{artifact.kind}'")
    return {"id": artifact.id, "path": path.relative_to(root.resolve()).as_posix()}


def _review_report(args: argparse.Namespace) -> int:
    from agentkit.report import build_run_report, render_html, render_text
    from agentkit.runs import run_directory

    root = find_project_root()
    run_dir = run_directory(root, args.run_id)
    if not run_dir.is_dir():
        raise ConfigError(f"No run found: {run_dir}")
    report = build_run_report(run_dir, args.run_id)
    if args.html:
        target = Path(args.html)
        with target.open("x", encoding="utf-8") as handle:
            handle.write(render_html(report))
        report["html"] = str(target)
    _emit(report, args.output_format, render_text(report))
    return 0


def _review_preview(args: argparse.Namespace) -> int:
    from agentkit.config import load_config
    from agentkit.review import OpenCodeReviewProvider, ReviewContext, ReviewProviderError

    root = find_project_root()
    config = load_config(root)
    provider = OpenCodeReviewProvider(timeout_seconds=config.review["timeout_seconds"])
    context = ReviewContext(
        run_id="preview",
        repository_root=root,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
        commit=args.commit,
    )
    try:
        preview = provider.delegate_preview(context)
    except ReviewProviderError as error:
        _emit(
            {"error": error.to_dict()},
            args.output_format,
            f"Preview failed ({error.kind}): {error.message}",
        )
        return EXIT_PROVIDER_ERROR
    reviewable = [
        item.get("path") for item in preview["reviewable_files"] if isinstance(item, dict)
    ]
    _emit(
        {"preview": preview},
        args.output_format,
        f"{len(reviewable)} reviewable file(s):\n" + "\n".join(f"- {path}" for path in reviewable),
    )
    return 0
