from __future__ import annotations

import functools
import http.server
import threading
import unittest
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class SiteBrowserChecks(unittest.TestCase):
    browser: Browser
    base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def _page(self, width: int, height: int = 900) -> Page:
        page = self.browser.new_page(viewport={"width": width, "height": height})
        page.goto(self.base_url, wait_until="networkidle")
        return page

    def test_layout_has_no_horizontal_overflow(self) -> None:
        for width in (320, 375, 1440):
            with self.subTest(width=width):
                page = self._page(width)
                try:
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth - window.innerWidth"
                    )
                    self.assertLessEqual(overflow, 0)
                finally:
                    page.close()

    def test_keyboard_focus_is_visible(self) -> None:
        page = self._page(1280)
        try:
            page.keyboard.press("Tab")
            focused = page.locator(":focus")
            self.assertEqual("Skip to content", focused.inner_text())
            styles = focused.evaluate(
                "element => { const s = getComputedStyle(element); "
                "return [s.outlineStyle, s.boxShadow]; }"
            )
            self.assertNotEqual("none", styles[0])
            self.assertNotEqual("none", styles[1])
            self.assertGreaterEqual(focused.bounding_box()["y"], 0)
        finally:
            page.close()

    def test_internal_targets_and_external_links(self) -> None:
        page = self._page(1280)
        try:
            hrefs = page.locator("a").evaluate_all("links => links.map(link => link.href)")
            for href in hrefs:
                with self.subTest(href=href):
                    if href.startswith(self.base_url + "#"):
                        fragment = href.split("#", 1)[1]
                        self.assertEqual(1, page.locator(f"#{fragment}").count())
                    elif href.startswith("https://"):
                        response = page.request.get(href, timeout=30_000)
                        self.assertLess(response.status, 400)
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
