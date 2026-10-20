from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from test_review_audit import ProjectFixture

from agentkit.artifacts import create_artifact, parse_artifact
from agentkit.validator import validate_project

COMMENT = "https://github.com/example/project/issues/4#issuecomment-7"
PR_COMMENT = "https://github.com/example/project/pull/5#issuecomment-8"
REVIEW = "https://github.com/example/project/pull/1#pullrequestreview-2"


class FakeGitHub:
    """Answers the git and gh calls of the verifier, and records the API paths asked for."""

    def __init__(self) -> None:
        self.origin = "git@github.com:example/project.git"
        self.docs: dict[str, dict[str, Any]] = {}
        self.paths: list[str] = []
        self.fail = False

    def add(self, url: str, path: str, **overrides: Any) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "user": {"type": "User", "login": "lead"},
            "html_url": url,
            "author_association": "COLLABORATOR",
            "state": "APPROVED",
            "submitted_at": "2026-10-20T00:00:00Z",
        }
        doc.update(overrides)
        self.docs[path] = doc
        return doc

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "git" and command[1] == "remote":
            return subprocess.CompletedProcess(command, 0, self.origin + "\n", "")
        if command[0] == "gh":
            path = command[-1]
            self.paths.append(path)
            if self.fail or path not in self.docs:
                return subprocess.CompletedProcess(command, 1, "", "HTTP 404")
            return subprocess.CompletedProcess(command, 0, json.dumps(self.docs[path]), "")
        raise AssertionError(f"unexpected command {command}")


class ArtifactApprovalTests(ProjectFixture):
    def setUp(self) -> None:
        super().setUp()
        self.fresh_github()
        self.path = create_artifact(self.project, "spec", "search")
        self.assertEqual(
            0, self.cli("artifact", "transition", str(self.path), "awaiting_approval", fmt=False)[0]
        )

    def fresh_github(self) -> None:
        self.github = FakeGitHub()
        self.github.add(COMMENT, "repos/example/project/issues/comments/7")
        self.github.add(PR_COMMENT, "repos/example/project/issues/comments/8")
        self.github.add(REVIEW, "repos/example/project/pulls/1/reviews/2")

    def github_mode(self) -> None:
        manifest = self.project / ".agent" / "project.toml"
        text = manifest.read_text(encoding="utf-8")
        self.assertNotIn("[review]", text)
        manifest.write_text(text + '\n[review]\napproval_mode = "github"\n', encoding="utf-8")

    def approve(self, *extra: str) -> int:
        with patch("agentkit.github_approval.run_bounded", side_effect=self.github):
            code, _ = self.cli(
                "artifact", "transition", str(self.path), "approved", *extra, fmt=False
            )
        return code

    def approval(self) -> dict[str, Any]:
        approval = parse_artifact(self.path).metadata.get("approval")
        self.assertIsInstance(approval, dict)
        return dict(approval)

    def assert_valid(self) -> None:
        errors = [f for f in validate_project(self.project) if f.severity == "error"]
        self.assertEqual([], errors)

    def test_local_mode_is_the_default_and_records_an_unverified_claim(self) -> None:
        code = self.approve("--approved-by", "workspace-user", "--evidence", COMMENT)
        self.assertEqual(0, code)
        approval = self.approval()
        self.assertEqual("workspace-user", approval["approved_by"])
        self.assertEqual("unverified", approval["verification"])
        self.assertEqual([], self.github.paths)  # local mode never calls GitHub
        self.assert_valid()

    def test_github_mode_records_the_verified_comment_author(self) -> None:
        self.github_mode()
        self.assertEqual(0, self.approve("--evidence", COMMENT))
        approval = self.approval()
        self.assertEqual("github:lead", approval["approved_by"])
        self.assertEqual("github", approval["verification"])
        self.assertEqual(COMMENT, approval["evidence"])
        self.assertEqual(["repos/example/project/issues/comments/7"], self.github.paths)
        self.assert_valid()

    def test_a_pull_request_conversation_comment_is_accepted(self) -> None:
        self.github_mode()
        self.assertEqual(0, self.approve("--approved-by", "github:lead", "--evidence", PR_COMMENT))
        self.assertEqual(["repos/example/project/issues/comments/8"], self.github.paths)

    def test_the_flag_asks_for_verification_of_an_approving_review(self) -> None:
        self.assertEqual(0, self.approve("--approval-mode", "github", "--evidence", REVIEW))
        self.assertEqual("github", self.approval()["verification"])
        self.assertEqual(["repos/example/project/pulls/1/reviews/2"], self.github.paths)

    def test_a_github_project_cannot_record_a_local_approval(self) -> None:
        self.github_mode()
        before = self.path.read_bytes()
        code = self.approve(
            "--approval-mode", "local", "--approved-by", "someone", "--evidence", COMMENT
        )
        self.assertEqual(2, code)
        self.assertEqual(before, self.path.read_bytes())

    def test_unverifiable_evidence_is_refused_and_the_artifact_is_left_alone(self) -> None:
        self.github_mode()
        comment_path = "repos/example/project/issues/comments/7"
        review_path = "repos/example/project/pulls/1/reviews/2"
        cases: list[tuple[str, tuple[str, ...], dict[str, Any] | None, str | None]] = [
            ("not a GitHub URL", ("--evidence", "https://tickets.example/1"), None, None),
            ("no evidence", (), None, None),
            ("not a collaborator", ("--evidence", COMMENT), {"author_association": "NONE"}, None),
            ("a bot", ("--evidence", COMMENT), {"user": {"type": "Bot", "login": "x"}}, None),
            ("another URL", ("--evidence", COMMENT), {"html_url": PR_COMMENT}, None),
            (
                "another approver named",
                ("--approved-by", "github:other", "--evidence", COMMENT),
                None,
                None,
            ),
            ("another repository", ("--evidence", COMMENT), None, "https://github.com/x/y"),
            ("changes requested", ("--evidence", REVIEW), {"state": "CHANGES_REQUESTED"}, None),
            ("unsubmitted review", ("--evidence", REVIEW), {"submitted_at": None}, None),
        ]
        before = self.path.read_bytes()
        for name, args, change, origin in cases:
            with self.subTest(case=name):
                self.fresh_github()
                if change:
                    path = review_path if REVIEW in args else comment_path
                    self.github.docs[path].update(change)
                if origin:
                    self.github.origin = origin
                self.assertEqual(2, self.approve(*args))
                self.assertEqual(before, self.path.read_bytes())
        with self.subTest(case="gh fails"):
            self.fresh_github()
            self.github.fail = True
            self.assertEqual(2, self.approve("--evidence", COMMENT))
            self.assertEqual(before, self.path.read_bytes())

    def test_validate_checks_the_verification_field(self) -> None:
        self.approve("--approved-by", "workspace-user", "--evidence", COMMENT)
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(
            text.replace('verification = "unverified"', 'verification = "trusted"'),
            encoding="utf-8",
        )
        self.assertIn(
            "approval.verification", "\n".join(str(f) for f in validate_project(self.project))
        )
        self.path.write_text(
            text.replace('verification = "unverified"', 'verification = "github"'),
            encoding="utf-8",
        )
        self.assertIn("github:LOGIN", "\n".join(str(f) for f in validate_project(self.project)))
        # an approval written before verification existed carries no field and stays valid
        self.path.write_text(text.replace('verification = "unverified"\n', ""), encoding="utf-8")
        self.assertNotIn("verification", self.path.read_text(encoding="utf-8"))
        self.assert_valid()


class SharedVerifierTests(unittest.TestCase):
    def test_review_and_artifact_paths_share_the_collaborator_check(self) -> None:
        from agentkit import github_approval

        github = FakeGitHub()
        github.add(COMMENT, "repos/example/project/issues/comments/7", author_association="OWNER")
        with patch("agentkit.github_approval.run_bounded", side_effect=github):
            verified = github_approval.verify_github_approval_evidence(Path("."), COMMENT)
        self.assertEqual("github:lead", verified["actor"])
        self.assertEqual("comment", verified["kind"])


if __name__ == "__main__":
    unittest.main()
