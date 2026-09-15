from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentkit.config import _available_profiles


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
