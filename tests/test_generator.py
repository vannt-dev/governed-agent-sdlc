from __future__ import annotations

import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from agentkit.generator import generate_claude, generate_codex, install_scaffold


class GeneratorTests(unittest.TestCase):
    def test_scaffold_includes_instructions_and_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            install_scaffold(root, name='quoted "project"')
            self.assertTrue((root / "AGENTS.md").is_file())
            self.assertTrue((root / "profiles" / "generic" / "profile.toml").is_file())
            manifest = (root / ".agent" / "project.toml").read_text(encoding="utf-8")
            self.assertIn('name = "quoted \\"project\\""', manifest)

    def test_scaffold_preserves_existing_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            instructions = root / "AGENTS.md"
            instructions.write_text("owned by project\n", encoding="utf-8")
            install_scaffold(root, name="fixture")
            self.assertEqual("owned by project\n", instructions.read_text(encoding="utf-8"))

    def test_generated_agent_supports_both_manifest_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generate_claude(root)
            developer = (root / ".claude" / "agents" / "developer.md").read_text(encoding="utf-8")
            self.assertIn("agentkit.toml", developer)
            self.assertIn(".agent/project.toml", developer)

    def test_generate_codex_creates_project_config_and_roles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated = generate_codex(root)
            self.assertEqual(9, len(generated))
            config_path = root / ".codex" / "config.toml"
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
            self.assertNotIn("approval_policy", config)
            self.assertNotIn("sandbox_mode", config)
            self.assertTrue(config["features"]["multi_agent"])
            self.assertTrue(config["features"]["hooks"])
            self.assertEqual("agents/developer.toml", config["agents"]["developer"]["config_file"])
            developer = (root / ".codex" / "agents" / "developer.toml").read_text(encoding="utf-8")
            self.assertIn("core/roles/developer.toml", developer)
            self.assertIn("Never self-approve", developer)
            self.assertNotIn("sandbox_mode", developer)
            reviewer = (root / ".codex" / "agents" / "reviewer.toml").read_text(encoding="utf-8")
            self.assertIn('sandbox_mode = "read-only"', reviewer)
            hooks = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            self.assertEqual("*", hooks["hooks"]["PreToolUse"][0]["matcher"])
            handler = hooks["hooks"]["PreToolUse"][0]["hooks"][0]
            self.assertIn("uv run --no-project python", handler["command"])
            self.assertEqual(handler["command"], handler["commandWindows"])
            self.assertTrue((root / ".codex" / "hooks" / "pre_tool_use.py").is_file())

    def test_generate_codex_is_additive_unless_forced(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / ".codex" / "config.toml"
            config.parent.mkdir(parents=True)
            config.write_text("project owned\n", encoding="utf-8")
            generate_codex(root)
            self.assertEqual("project owned\n", config.read_text(encoding="utf-8"))
            generate_codex(root, force=True)
            forced = config.read_text(encoding="utf-8")
            self.assertIn("multi_agent = true", forced)
            self.assertNotIn("approval_policy", forced)

    def test_dry_run_does_not_touch_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "new-project"
            scaffold = install_scaffold(root, name="preview", dry_run=True)
            codex = generate_codex(root, dry_run=True)
            self.assertFalse(root.exists())
            self.assertGreaterEqual(len(scaffold), 5)
            self.assertEqual(9, len(codex))


if __name__ == "__main__":
    unittest.main()
