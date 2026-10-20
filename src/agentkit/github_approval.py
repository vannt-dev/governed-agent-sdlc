"""Optional GitHub approval verification via the user's authenticated gh CLI.

Review runs (`review approve`) and artifact approvals (`artifact transition ... approved`) share one
check: the evidence URL belongs to this repository's GitHub origin, GitHub returns it for exactly
that URL, and its author is a human with an OWNER, MEMBER or COLLABORATOR association.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agentkit.review import filter_env, run_bounded

REVIEW_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)#pullrequestreview-([1-9][0-9]*)"
)
COMMENT_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(?:issues|pull)/([1-9][0-9]*)#issuecomment-([1-9][0-9]*)"
)
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def _gh_env() -> dict[str, str]:
    return filter_env(extra=("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR"))


def _require_origin(root: Path, repository: str, env: dict[str, str], what: str) -> None:
    origin = run_bounded(["git", "remote", "get-url", "origin"], cwd=str(root), timeout=15, env=env)
    allowed = {
        f"https://github.com/{repository}",
        f"git@github.com:{repository}",
        f"ssh://git@github.com/{repository}",
    }
    if origin.returncode or origin.stdout.strip().removesuffix(".git") not in allowed:
        raise ValueError(f"{what} must belong to this repository's GitHub origin")


def _gh_api(root: Path, path: str, env: dict[str, str], what: str) -> dict[str, Any]:
    response = run_bounded(
        ["gh", "api", "--hostname", "github.com", path],
        cwd=str(root),
        timeout=30,
        env=env,
    )
    if response.returncode:
        raise ValueError(
            f"GitHub {what} verification failed; check gh authentication and repository access"
        )
    try:
        doc = json.loads(response.stdout)
    except ValueError as exc:
        raise ValueError(f"GitHub {what} verification returned malformed JSON") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"GitHub {what} verification returned an unexpected document")
    return doc


def _trusted_author(doc: dict[str, Any], evidence: str) -> str | None:
    """The `github:LOGIN` of a human collaborator who wrote exactly this URL, or None."""
    user = doc.get("user")
    if (
        not isinstance(user, dict)
        or user.get("type") != "User"
        or not isinstance(user.get("login"), str)
        or not user["login"]
        or doc.get("html_url") != evidence
        or doc.get("author_association") not in TRUSTED_ASSOCIATIONS
    ):
        return None
    return f"github:{user['login']}"


def verify_github_review(
    root: Path, evidence: str, actor: str, decision: str, snapshot: dict[str, Any]
) -> dict[str, Any]:
    match = REVIEW_URL.fullmatch(evidence)
    if not match:
        raise ValueError(
            "GitHub mode requires a pull request review URL including #pullrequestreview-ID"
        )
    repository, pull, review_id = match.groups()
    env = _gh_env()
    _require_origin(root, repository, env, "Approval review")
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
    doc = _gh_api(root, f"repos/{repository}/pulls/{pull}/reviews/{review_id}", env, "review")
    expected = "CHANGES_REQUESTED" if decision == "rejected" else "APPROVED"
    if (
        _trusted_author(doc, evidence) != actor
        or doc.get("state") != expected
        or doc.get("commit_id") != head
        or not doc.get("submitted_at")
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


def verify_github_approval_evidence(
    root: Path, evidence: str, actor: str | None = None
) -> dict[str, Any]:
    """Verify an artifact approval: an approving PR review or an issue/PR comment.

    Returns the verified `github:LOGIN`. A comment proves who wrote it, not what it says; the
    reader of the evidence judges whether it approves. An `actor`, when given, must be that login.
    """
    review = REVIEW_URL.fullmatch(evidence)
    comment = COMMENT_URL.fullmatch(evidence)
    if review:
        repository, pull, item_id = review.groups()
        api_path = f"repos/{repository}/pulls/{pull}/reviews/{item_id}"
        what = "review"
    elif comment:
        repository, _, item_id = comment.groups()
        api_path = f"repos/{repository}/issues/comments/{item_id}"
        what = "comment"
    else:
        raise ValueError(
            "GitHub approval mode requires a pull request review URL (#pullrequestreview-ID) "
            "or an issue or pull request comment URL (#issuecomment-ID)"
        )
    env = _gh_env()
    _require_origin(root, repository, env, "Approval evidence")
    doc = _gh_api(root, api_path, env, what)
    verified = _trusted_author(doc, evidence)
    if verified is None:
        raise ValueError(
            f"GitHub {what} author is not a human collaborator of this repository, "
            "or the URL does not match"
        )
    if review and (doc.get("state") != "APPROVED" or not doc.get("submitted_at")):
        raise ValueError("GitHub review is not a submitted approval")
    if actor and actor != verified:
        raise ValueError(f"--approved-by {actor} does not match the evidence author {verified}")
    return {"mode": "github", "actor": verified, "evidenceUrl": evidence, "kind": what}
