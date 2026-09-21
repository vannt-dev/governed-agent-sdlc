from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from agentkit.approval import load_review_approvals
from agentkit.events import read_events
from agentkit.remediation import existing_attempts
from agentkit.review import validate_review_evidence
from agentkit.runs import attempt_gate

SEVERITIES = ("critical", "high", "medium", "low", "info")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_run_report(run_dir: Path, run_id: str) -> dict[str, Any]:
    """Summarize a run from its evidence files. It only reads: the report is a view, never a source
    of truth, so it cannot change what governance decided."""
    attempts: list[dict[str, Any]] = []
    approvals = load_review_approvals(run_dir)
    for number in existing_attempts(run_dir):
        attempt_dir = run_dir / f"review-attempt-{number}"
        policy = _load_json(attempt_dir / "policy-result.json")
        findings = _load_json(attempt_dir / "findings.json") or []
        provider_data = _load_json(attempt_dir / "provider.json")
        provider = provider_data if isinstance(provider_data, dict) else {}
        error_data = _load_json(attempt_dir / "provider-error.json")
        provider_error = error_data if isinstance(error_data, dict) else None
        escalation = _load_json(attempt_dir / "escalation.json")

        counts = {severity: 0 for severity in SEVERITIES}
        for finding in findings if isinstance(findings, list) else []:
            severity = finding.get("severity") if isinstance(finding, dict) else None
            if isinstance(severity, str) and severity in counts:
                counts[severity] += 1

        gate: dict[str, Any] = {"status": "unknown", "detail": "policy-result.json is unreadable"}
        if isinstance(policy, dict):
            try:
                gate = attempt_gate(run_dir, number)[1].to_dict()
            except (ValueError, OSError) as exc:
                gate = {"status": "unknown", "detail": str(exc)}

        attempts.append(
            {
                "attempt": number,
                "provider": provider.get("provider") or (provider_error or {}).get("provider"),
                "toolVersion": provider.get("toolVersion"),
                "artifact": provider.get("artifact"),
                "findings": counts,
                "decision": policy.get("decision") if isinstance(policy, dict) else None,
                "policies": [p.get("policyId") for p in policy["policies"] if isinstance(p, dict)]
                if isinstance(policy, dict) and isinstance(policy.get("policies"), list)
                else [],
                "escalated": bool(escalation),
                "providerError": provider_error,
                "approvals": [a for a in approvals if a.get("attempt", 1) == number],
                "gate": gate,
                "evidenceProblems": validate_review_evidence(attempt_dir),
            }
        )

    latest = attempts[-1] if attempts else None
    return {
        "runId": run_id,
        "directory": str(run_dir),
        "background": (run_dir / "review-background.md").is_file(),
        "attempts": attempts,
        "latestGate": latest["gate"] if latest else None,
        "events": read_events(run_dir),
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [f"Run {report['runId']} ({len(report['attempts'])} attempt(s))"]
    for attempt in report["attempts"]:
        counts = " ".join(f"{k}={v}" for k, v in attempt["findings"].items())
        lines.append(
            f"- attempt {attempt['attempt']}: {attempt['provider']} | {counts} | "
            f"decision={attempt['decision']} | gate={attempt['gate']['status']}"
        )
        for approval in attempt["approvals"]:
            lines.append(
                f"    {approval.get('decision')} {approval.get('policyId')} "
                f"by {approval.get('actor')} ({approval.get('evidence')})"
            )
        for problem in attempt["evidenceProblems"]:
            lines.append(f"    evidence problem: {problem}")
    lines.append(f"Events: {len(report['events'])}")
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    """Self-contained static page; values are escaped because evidence holds reviewer text."""

    def esc(value: object) -> str:
        return html.escape("" if value is None else str(value))

    rows = []
    for attempt in report["attempts"]:
        counts = ", ".join(f"{esc(k)}: {esc(v)}" for k, v in attempt["findings"].items())
        approvals = (
            "<br>".join(
                f"{esc(a.get('decision'))} {esc(a.get('policyId'))} by {esc(a.get('actor'))}"
                for a in attempt["approvals"]
            )
            or "none"
        )
        problems = "<br>".join(esc(p) for p in attempt["evidenceProblems"]) or "none"
        rows.append(
            "<tr>"
            f"<td>{esc(attempt['attempt'])}</td><td>{esc(attempt['provider'])}</td>"
            f"<td>{counts}</td><td>{esc(attempt['decision'])}</td>"
            f"<td>{esc(attempt['gate']['status'])}</td><td>{approvals}</td><td>{problems}</td>"
            "</tr>"
        )
    events = "".join(
        f"<li>{esc(e.get('timestamp'))} {esc(e.get('type'))}</li>" for e in report["events"]
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>Review run {esc(report['runId'])}</title>"
        "<style>body{font:14px system-ui;margin:2rem}table{border-collapse:collapse}"
        "td,th{border:1px solid #888;padding:.35rem .6rem;text-align:left}</style></head><body>"
        f"<h1>Review run {esc(report['runId'])}</h1>"
        "<table><tr><th>Attempt</th><th>Provider</th><th>Findings</th><th>Decision</th>"
        "<th>Gate</th><th>Approvals</th><th>Evidence problems</th></tr>"
        f"{''.join(rows)}</table><h2>Events</h2><ul>{events}</ul></body></html>"
    )
