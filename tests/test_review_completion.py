from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_review_audit import ProjectFixture

from agentkit.artifacts import create_artifact, parse_artifact, serialize_artifact
from agentkit.config import load_config
from agentkit.events import emit_event, read_events
from agentkit.freshness import capture_source
from agentkit.github_approval import verify_github_review
from agentkit.locking import run_lock
from agentkit.review import ReviewResult
from agentkit.runs import attempt_gate, require_artifact_gate


class CompletionTests(ProjectFixture):
    def run_review(self, *args: str) -> Path:
        self.assertEqual(0, self.cli("review", "run", "--run-id", "r1", *args)[0])
        return self.project / ".agent/runs/r1"

    def test_source_policy_and_background_changes_invalidate_gate(self) -> None:
        source = self.project / "source.py"
        source.write_text("x = 1\n", encoding="utf-8")
        run = self.run_review()
        for path in (source, self.project / "agentkit.toml", run / "review-background.md"):
            with self.subTest(path=path.name):
                old = path.read_bytes() if path.exists() else None
                path.write_bytes((old or b"") + b"\n# changed\n")
                self.assertEqual("stale", attempt_gate(run, 1, root=self.project)[1].status)
                if old is None:
                    path.unlink()
                else:
                    path.write_bytes(old)
        self.assertEqual("passed", attempt_gate(run, 1, root=self.project)[1].status)

    def test_legacy_evidence_is_explicitly_unverified(self) -> None:
        run = self.run_review()
        (run / "review-attempt-1/source.json").unlink()
        self.assertEqual("unverified", attempt_gate(run, 1, root=self.project)[1].status)

    @unittest.skipIf(os.name == "nt", "Windows does not expose POSIX executable modes")
    def test_unstaged_executable_mode_change_invalidates_gate(self) -> None:
        source = self.project / "script.py"
        source.write_text("print('hello')\n", encoding="utf-8")
        source.chmod(0o644)
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "add", "script.py"], check=True)
        run = self.run_review()
        source.chmod(0o755)
        self.assertEqual("stale", attempt_gate(run, 1, root=self.project)[1].status)
        source.chmod(0o644)
        self.assertEqual("passed", attempt_gate(run, 1, root=self.project)[1].status)

    def test_changes_during_review_never_pass(self) -> None:
        def change_source(_context: object) -> ReviewResult:
            (self.project / "changed.py").write_text("x = 1", encoding="utf-8")
            return ReviewResult("mock", True, ())

        with patch("agentkit.review.MockReviewProvider.review", side_effect=change_source):
            code, data = self.cli("review", "run", "--run-id", "r1")
        self.assertEqual(3, code)
        self.assertEqual("stale", data["error"]["kind"])  # type: ignore[index]

    def test_interrupted_attempt_recovery_keeps_evidence_and_allocates_next_attempt(self) -> None:
        run = self.project / ".agent/runs/r1"
        attempt = run / "review-attempt-1"
        attempt.mkdir(parents=True)
        marker = attempt / "in-progress"
        marker.write_text("interrupted", encoding="utf-8")
        evidence = attempt / "findings.json"
        evidence.write_text("partial evidence", encoding="utf-8")
        self.assertEqual(3, self.cli("review", "status", "--run-id", "r1")[0])
        self.assertEqual(0, self.cli("review", "recover", "--run-id", "r1")[0])
        self.assertEqual("partial evidence", evidence.read_text(encoding="utf-8"))
        self.assertEqual(3, self.cli("review", "status", "--run-id", "r1")[0])
        self.assertEqual(2, self.cli("review", "recover", "--run-id", "r1")[0])
        self.run_review()
        self.assertTrue((run / "review-attempt-2/provider.json").is_file())

    def test_process_and_thread_writers_are_refused_and_crash_releases_lock(self) -> None:
        run = self.project / ".agent/runs/r1"
        script = (
            "from pathlib import Path; from agentkit.locking import run_lock; import sys; "
            "lock=run_lock(Path(sys.argv[1])); lock.__enter__(); print('locked', flush=True); "
            "sys.stdin.read()"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(run)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            assert child.stdout is not None
            self.assertEqual("locked", child.stdout.readline().strip())
            with self.assertRaisesRegex(ValueError, "busy"):
                emit_event(run, "r1", "review.started")
        finally:
            child.kill()
            child.communicate(timeout=10)
        with run_lock(run):
            emit_event(run, "r1", "review.started")  # same-thread reentrancy
            errors: list[str] = []

            def contend() -> None:
                try:
                    emit_event(run, "r1", "review.completed")
                except ValueError as exc:
                    errors.append(str(exc))

            thread = threading.Thread(target=contend)
            thread.start()
            thread.join(timeout=5)
            self.assertEqual(1, len(errors))
        emit_event(run, "r1", "review.completed")
        self.assertEqual(["r1-0001", "r1-0002"], [e["id"] for e in read_events(run)])

    def test_artifact_completion_requires_fresh_latest_linked_attempt_when_enabled(self) -> None:
        manifest = load_config(self.project).manifest_path
        with manifest.open("a", encoding="utf-8") as handle:
            handle.write("\n[review]\nenforce_artifact_gate = true\n")
        path = create_artifact(self.project, "review", "check")
        artifact = parse_artifact(path)
        artifact.metadata["status"] = "active"
        path.write_text(serialize_artifact(artifact), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "fresh passing"):
            require_artifact_gate(self.project, artifact.id, path)
        run = self.run_review("--artifact", str(path))
        require_artifact_gate(self.project, artifact.id, path)
        interrupted = run / "review-attempt-2"
        interrupted.mkdir()
        (interrupted / "in-progress").touch()
        with self.assertRaises(ValueError):
            require_artifact_gate(self.project, artifact.id, path)
        self.cli("review", "recover", "--run-id", "r1")
        self.run_review("--artifact", str(path))
        self.assertEqual(
            0, self.cli("artifact", "transition", str(path), "completed", fmt=False)[0]
        )

    def test_github_verifies_identity_decision_commit_and_repository(self) -> None:
        url = "https://github.com/example/project/pull/1#pullrequestreview-2"
        doc = {
            "user": {"type": "User", "login": "lead"},
            "state": "APPROVED",
            "commit_id": "abc",
            "html_url": url,
            "submitted_at": "2026-09-20",
            "author_association": "COLLABORATOR",
        }

        def response(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            value = "https://github.com/example/project.git" if command[1] == "remote" else ""
            if command[0] == "gh":
                value = json.dumps(doc)
            return subprocess.CompletedProcess(command, 0, value, "")

        with patch("agentkit.github_approval.run_bounded", side_effect=response):
            snapshot = {"head": "abc", "resolvedRefs": {}}
            verified = verify_github_review(self.project, url, "github:lead", "approved", snapshot)
            self.assertEqual("abc", verified["commit"])
            for key, value in (
                ("commit_id", "old"),
                ("state", "DISMISSED"),
                ("author_association", "NONE"),
            ):
                old = doc[key]
                doc[key] = value
                with self.assertRaises(ValueError):
                    verify_github_review(self.project, url, "github:lead", "approved", snapshot)
                doc[key] = old

    def test_git_index_and_symbolic_ref_changes_invalidate_fingerprint(self) -> None:
        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)

        git("init", "-q")
        tracked = self.project / "src/build/compiler.py"
        tracked.parent.mkdir(parents=True)
        tracked.write_text("x = 1\n", encoding="utf-8")
        git("add", "src/build/compiler.py")
        git("add", ".agent/project.toml")
        git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        )
        before = capture_source(self.project, {"from": "HEAD"})
        tracked.write_text("x = 2\n", encoding="utf-8")
        self.assertNotEqual(
            before["fingerprint"], capture_source(self.project, {"from": "HEAD"})["fingerprint"]
        )
        tracked.write_text("x = 1\n", encoding="utf-8")
        git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--allow-empty",
            "-qm",
            "next",
        )
        self.assertNotEqual(
            before["fingerprint"], capture_source(self.project, {"from": "HEAD"})["fingerprint"]
        )
