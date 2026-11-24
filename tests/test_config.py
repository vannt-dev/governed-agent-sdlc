from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentkit.config import ConfigError, _available_profiles, load_config

MANIFEST = """version = 1

[project]
name = "fixture"
topology = "single-repo"

[[repositories]]
id = "root"
path = "."
profiles = ["generic"]

[workflow]
require_spec = true
require_plan = true
require_review = true
require_qa = true
"""


class EgressSettingsTests(unittest.TestCase):
    def load(self, extra: str):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "agentkit.toml").write_text(MANIFEST + extra, encoding="utf-8")
            return load_config(Path(temp))

    def test_no_table_allows_no_host(self) -> None:
        self.assertEqual((), self.load("").egress_allowed_hosts)

    def test_allowed_hosts_are_read(self) -> None:
        config = self.load('\n[egress]\nallowed_hosts = ["uploads.example.com", "*.example.org"]\n')
        self.assertEqual(("uploads.example.com", "*.example.org"), config.egress_allowed_hosts)

    def test_invalid_settings_are_rejected(self) -> None:
        for extra in (
            "\negress = 1\n",
            '\n[egress]\nallowed_hosts = "uploads.example.com"\n',
            '\n[egress]\nallowed_hosts = ["https://uploads.example.com"]\n',
            '\n[egress]\nallowed_hosts = ["uploads.example.com:443"]\n',
            '\n[egress]\nallowed_hosts = ["*"]\n',
            '\n[egress]\nallowed_hosts = ["a.example.com", "a.example.com"]\n',
            '\n[egress]\nhosts = ["a.example.com"]\n',
        ):
            with self.subTest(extra=extra), self.assertRaises(ConfigError):
                self.load(extra)


class ConfigResourceTests(unittest.TestCase):
    def test_installed_resource_adapters_are_available_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            package = base / "site-packages" / "agentkit"
            for adapter in ("codex", "claude-code"):
                (package / "resources" / "adapters" / adapter).mkdir(parents=True)
            project = base / "project"
            project.mkdir()
            with patch("agentkit.config.__file__", str(package / "config.py")):
                available = _available_profiles(project)
            self.assertTrue({"codex", "claude-code"}.issubset(available))


if __name__ == "__main__":
    unittest.main()
