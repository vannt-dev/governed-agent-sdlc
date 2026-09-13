from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentkit.generator import generate_claude, install_scaffold


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


if __name__ == "__main__":
    unittest.main()
