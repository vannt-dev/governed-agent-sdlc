from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agentkit.artifacts import ArtifactError
from agentkit.cli import _project_artifact_path, main


class CliTests(unittest.TestCase):
    def test_accepts_artifact_below_project_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "docs" / "agent" / "specs" / "one.md"
            self.assertEqual(path.resolve(), _project_artifact_path(root, str(path)))

    def test_rejects_artifact_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            root = Path(temp)
            path = Path(other) / "outside.md"
            with self.assertRaisesRegex(ArtifactError, "must stay within"):
                _project_artifact_path(root, str(path))

    def test_rejects_non_markdown_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "docs" / "agent" / "specs" / "one.toml"
            with self.assertRaisesRegex(ArtifactError, "Markdown"):
                _project_artifact_path(root, str(path))

    def test_relative_artifact_path_is_resolved_from_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = root / "docs" / "agent" / "specs" / "one.md"
            self.assertEqual(
                expected.resolve(),
                _project_artifact_path(root, "docs/agent/specs/one.md"),
            )

    def test_init_codex_json_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            preview = Path(temp) / "preview"
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    ["init", str(preview), "--adapter", "codex", "--dry-run", "--format", "json"]
                )
            self.assertEqual(0, result)
            self.assertTrue(json.loads(output.getvalue())["dry_run"])
            self.assertFalse(preview.exists())

            project = Path(temp) / "project"
            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["init", str(project), "--adapter", "codex", "--format", "json"])
            self.assertEqual(0, result)
            self.assertEqual("project", json.loads(output.getvalue())["name"])
            self.assertTrue((project / ".codex" / "config.toml").is_file())

    def test_validate_doctor_and_migrate_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            self.assertEqual(0, main(["init", str(project), "--adapter", "none"]))
            for command in ("validate", "doctor"):
                output = io.StringIO()
                with redirect_stdout(output):
                    result = main([command, str(project), "--format", "json"])
                self.assertEqual(0, result)
                self.assertTrue(json.loads(output.getvalue())["ok"])

            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["migrate", str(project), "--dry-run", "--format", "json"])
            self.assertEqual(0, result)
            self.assertFalse(json.loads(output.getvalue())["changed"])

    def test_artifact_list_show_and_graph_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            main(["init", str(project), "--adapter", "none"])
            main(["artifact", "new", "spec", "example", "--path", str(project)])
            artifact_path = next((project / "docs" / "agent" / "specs").glob("*.md"))

            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["artifact", "list", "--path", str(project), "--format", "json"])
            self.assertEqual(0, result)
            self.assertEqual("spec", json.loads(output.getvalue())[0]["kind"])

            output = io.StringIO()
            with redirect_stdout(output):
                result = main(
                    [
                        "artifact",
                        "show",
                        str(artifact_path),
                        "--path",
                        str(project),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(0, result)
            self.assertEqual("draft", json.loads(output.getvalue())["metadata"]["status"])

            output = io.StringIO()
            with redirect_stdout(output):
                result = main(["artifact", "graph", "--path", str(project), "--format", "json"])
            self.assertEqual(0, result)
            self.assertEqual([], json.loads(output.getvalue())["edges"])

    def test_json_errors_are_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            main(["init", str(project), "--adapter", "none"])
            error = io.StringIO()
            with redirect_stderr(error):
                result = main(["migrate", str(project), "--to-version", "2", "--format", "json"])
            self.assertEqual(2, result)
            self.assertFalse(json.loads(error.getvalue())["ok"])

    def test_text_commands_and_adapter_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["init", str(project), "--adapter", "claude-code"]))
                self.assertEqual(0, main(["generate", "codex", str(project), "--dry-run"]))
                self.assertEqual(0, main(["validate", str(project)]))
                self.assertEqual(0, main(["doctor", str(project)]))
            rendered = output.getvalue()
            self.assertIn("Initialized", rendered)
            self.assertIn("Would generate", rendered)
            self.assertIn("Validation complete", rendered)
            self.assertIn("Governed Agent SDLC", rendered)

    def test_text_artifact_commands_and_transition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            main(["init", str(project), "--adapter", "none"])
            main(["artifact", "new", "spec", "example", "--path", str(project)])
            artifact_path = next((project / "docs" / "agent" / "specs").glob("*.md"))
            relative = artifact_path.relative_to(project).as_posix()
            output = io.StringIO()
            with (
                patch("agentkit.cli.find_project_root", return_value=project),
                redirect_stdout(output),
            ):
                self.assertEqual(
                    0,
                    main(["artifact", "transition", relative, "awaiting_approval"]),
                )
                self.assertEqual(0, main(["artifact", "list", "--path", str(project)]))
                self.assertEqual(
                    0,
                    main(["artifact", "show", relative, "--path", str(project)]),
                )
                self.assertEqual(0, main(["artifact", "graph", "--path", str(project)]))
            rendered = output.getvalue()
            self.assertIn("draft -> awaiting_approval", rendered)
            self.assertIn("awaiting_approval", rendered)
            self.assertIn("# Spec: example", rendered)

    def test_migrate_rejects_ambiguous_and_invalid_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            main(["init", str(project), "--adapter", "none"])
            manifest = project / ".agent" / "project.toml"
            (project / "agentkit.toml").write_text(
                manifest.read_text(encoding="utf-8"), encoding="utf-8"
            )
            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(2, main(["migrate", str(project)]))
            self.assertIn("exactly one", error.getvalue())

            (project / "agentkit.toml").unlink()
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace("version = 1", "version = true"),
                encoding="utf-8",
            )
            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(2, main(["migrate", str(project)]))
            self.assertIn("must be an integer", error.getvalue())

            manifest.write_text("version = [\n", encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(2, main(["migrate", str(project)]))
            self.assertIn("Invalid TOML manifest", error.getvalue())

            error = io.StringIO()
            with redirect_stderr(error):
                self.assertEqual(2, main(["migrate", str(project), "--format", "json"]))
            payload = json.loads(error.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIn("Invalid TOML manifest", payload["error"])

    def test_review_evaluate_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            findings_file = Path(temp) / "findings.json"
            findings_file.write_text(
                json.dumps(
                    [
                        {
                            "id": "f-1",
                            "severity": "critical",
                            "category": "security",
                            "file": "main.py",
                            "message": "Critical vulnerability",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            out_dir = Path(temp) / "evidence"
            output = io.StringIO()
            with redirect_stdout(output):
                # blocked exit code is 1
                exit_code = main(
                    [
                        "review",
                        "evaluate",
                        str(findings_file),
                        "--output-dir",
                        str(out_dir),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(1, exit_code)
            data = json.loads(output.getvalue())
            self.assertEqual(data["decision"], "block")
            self.assertTrue(data["blocked"])
            self.assertTrue((out_dir / "findings.json").is_file())
            self.assertTrue((out_dir / "policy-result.json").is_file())

    def test_review_run_cli_mock(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            main(["init", str(project), "--adapter", "none"])
            output = io.StringIO()
            with (
                patch("agentkit.cli.find_project_root", return_value=project),
                redirect_stdout(output),
            ):
                exit_code = main(["review", "run", "--provider", "mock", "--format", "json"])
            self.assertEqual(0, exit_code)
            data = json.loads(output.getvalue())
            self.assertEqual(data["review"]["provider"], "mock")
            self.assertEqual(data["governance"]["decision"], "continue")


if __name__ == "__main__":
    unittest.main()
