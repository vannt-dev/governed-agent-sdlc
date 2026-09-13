from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PAGES_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"


class SiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[tuple[str, str]] = []
        self.headings: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag in {"a", "link", "script", "img"}:
            target = values.get("href") or values.get("src")
            if target:
                self.links.append((tag, target))
        if tag in {"h1", "h2", "h3"}:
            self.headings.append(tag)


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (SITE / "index.html").read_text(encoding="utf-8")
        cls.css = (SITE / "styles.css").read_text(encoding="utf-8")
        cls.parser = SiteParser()
        cls.parser.feed(cls.html)

    def test_required_landmarks_and_heading_order(self) -> None:
        for landmark in ("<header", "<nav", '<main id="main"', "<footer"):
            self.assertIn(landmark, self.html)
        self.assertEqual("h1", self.parser.headings[0])
        self.assertEqual(1, self.parser.headings.count("h1"))

    def test_internal_anchors_resolve(self) -> None:
        for tag, target in self.parser.links:
            if tag == "a" and target.startswith("#"):
                self.assertIn(target[1:], self.parser.ids, target)

    def test_local_assets_exist_and_site_has_no_remote_runtime_assets(self) -> None:
        for tag, target in self.parser.links:
            parsed = urlparse(target)
            if tag in {"link", "script", "img"}:
                self.assertFalse(parsed.scheme or parsed.netloc, target)
                self.assertTrue((SITE / target.removeprefix("./")).is_file(), target)
        self.assertIsNone(re.search(r"@import\s|url\([\"']?https?://", self.css, re.I))

    def test_responsive_and_accessibility_basics(self) -> None:
        self.assertIn('name="viewport"', self.html)
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn(":focus-visible", self.css)
        self.assertIn("box-shadow: 0 0 0 6px var(--focus)", self.css)
        self.assertIn("@media (max-width: 380px)", self.css)
        self.assertIn(".site-header .brand span { display: none; }", self.css)
        self.assertIn("skip-link", self.html)
        self.assertNotIn("<script", self.html)

    def test_public_copy_does_not_overstate_enforcement(self) -> None:
        self.assertNotIn("Agents receive only the capability", self.html)
        self.assertNotIn("role-scope escapes fail closed", self.html)
        self.assertIn("platform permissions", self.html)

    def test_conduct_policy_has_real_private_reporting_link(self) -> None:
        conduct = (ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        self.assertIn("https://support.github.com/contact/report-abuse", conduct)
        self.assertNotIn("contact channel on the\nowner's GitHub profile", conduct)

    def test_pages_workflow_is_pinned_and_least_privilege(self) -> None:
        workflow = PAGES_WORKFLOW.read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s*([^\s#]+)", workflow)
        self.assertEqual(4, len(uses))
        for action in uses:
            self.assertRegex(action, r"@[0-9a-f]{40}$")
        self.assertIn("contents: read", workflow)
        self.assertIn("pages: write", workflow)
        self.assertIn("id-token: write", workflow)
        self.assertIn("path: site", workflow)
        self.assertNotIn("pull_request:", workflow)


if __name__ == "__main__":
    unittest.main()
