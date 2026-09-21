"""Optional GitHub review verification via the user's authenticated gh CLI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentkit.review import filter_env, run_bounded

REVIEW_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)#pullrequestreview-([1-9][0-9]*)"
)


def verify_github_review(
    root: Path, evidence: str, actor: str, decision: str, snapshot: dict[str, Any]
) -> dict[str, Any]:
    match = REVIEW_URL.fullmatch(evidence)
    if not match:
        raise ValueError(
            "GitHub mode requires a pull request review URL including #pullrequestreview-ID"
        )
    repository, pull, review_id = match.groups()
    env = filter_env(extra=("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR"))
    origin = run_bounded(["git", "remote", "get-url", "origin"], cwd=str(root), timeout=15, env=env)
    allowed = {
        f"https://github.com/{repository}",
        f"git@github.com:{repository}",
        f"ssh://git@github.com/{repository}",
    }
    if origin.returncode or origin.stdout.strip().removesuffix(".git") not in allowed:
        raise ValueError("Approval review must belong to this repository's GitHub origin")
    clean = run_bounded(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(root),
        timeout=15,
        env=env,
    )
    if clean.returncode or clean.stdout.strip():
        raise ValueError("GitHub approval requires a clean committed source tree")
    head = snapshot.get("head")
    refs = snapshot.get("resolvedRefs", {})
    if not head or (refs.get("commit") or refs.get("to") or head) != head:
        raise ValueError("GitHub approval requires the reviewed target to equal HEAD")
    response = run_bounded(
        [
            "gh",
            "api",
            "--hostname",
            "github.com",
            f"repos/{repository}/pulls/{pull}/reviews/{review_id}",
        ],
        cwd=str(root),
        timeout=30,
        env=env,
    )
    if response.returncode:
        raise ValueError(
            "GitHub review verification failed; check gh authentication and repository access"
        )
    doc = json.loads(response.stdout)
    expected = "CHANGES_REQUESTED" if decision == "rejected" else "APPROVED"
    user = doc.get("user", {}) if isinstance(doc, dict) else {}
    if (
        not isinstance(user, dict)
        or user.get("type") != "User"
        or actor != f"github:{user.get('login')}"
        or doc.get("state") != expected
        or doc.get("commit_id") != head
        or doc.get("html_url") != evidence
        or not doc.get("submitted_at")
        or doc.get("author_association") not in {"OWNER", "MEMBER", "COLLABORATOR"}
    ):
        raise ValueError(
            "GitHub review identity, decision, collaborator status or commit does not match"
        )
    return {
        "mode": "github",
        "actor": actor,
        "decision": decision,
        "commit": head,
        "reviewUrl": evidence,
        "reviewId": int(review_id),
    }
