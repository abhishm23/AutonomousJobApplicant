"""
Unit test suite verifying the complete elimination and deprecation of paywalled scrapers
(RemoteOK and WeWorkRemotely) across files, imports, SCRAPERS registry, and UI badges.
"""

import os
import unittest


class TestPaywallDeprecation(unittest.TestCase):
    def test_remoteok_file_deleted(self):
        remoteok_path = os.path.join(os.path.dirname(__file__), "..", "scraper", "remoteok_scraper.py")
        self.assertFalse(os.path.exists(remoteok_path), "scraper/remoteok_scraper.py must be deleted.")

    def test_weworkremotely_file_deleted(self):
        wwr_path = os.path.join(os.path.dirname(__file__), "..", "scraper", "weworkremotely_scraper.py")
        self.assertFalse(os.path.exists(wwr_path), "scraper/weworkremotely_scraper.py must be deleted.")

    def test_remoteok_module_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            import scraper.remoteok_scraper  # noqa: F401

    def test_weworkremotely_module_not_importable(self):
        with self.assertRaises(ModuleNotFoundError):
            import scraper.weworkremotely_scraper  # noqa: F401

    def test_multi_scraper_registry_excludes_deprecated(self):
        from scraper.multi_scraper import SCRAPERS
        self.assertNotIn("RemoteOK", SCRAPERS)
        self.assertNotIn("WeWorkRemotely", SCRAPERS)
        self.assertNotIn("remoteok", [k.lower() for k in SCRAPERS])
        self.assertNotIn("weworkremotely", [k.lower() for k in SCRAPERS])

    def test_dashboard_caption_excludes_deprecated(self):
        app_path = os.path.join(os.path.dirname(__file__), "..", "dashboard", "app.py")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("RemoteOK", content)
        self.assertNotIn("WeWorkRemotely", content)


if __name__ == "__main__":
    unittest.main()
