import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config


class FixedUrlConfigTests(unittest.TestCase):
    def test_url_fields_are_not_rendered_in_configuration(self):
        html = (Path(__file__).parents[1] / "templates" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('id="wimtechUrl"', html)
        self.assertNotIn('id="wiamUrl"', html)
        self.assertNotIn('id="commandesUrl"', html)
        self.assertIn('name="executionMode" value="visible" checked', html)
        self.assertIn('name="executionMode" value="headless"', html)
        self.assertIn('name="executionMode" value="http"', html)

    def test_saved_urls_cannot_override_backend_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps({
                    "wimtech_url": "https://wrong.example/wimtech",
                    "wiam_url": "https://wrong.example/wiam",
                    "commandes_url": "https://wrong.example/commandes",
                }),
                encoding="utf-8",
            )
            with patch.object(config, "CONFIG_PATH", path):
                loaded = config.load_config()

        self.assertEqual(loaded["wimtech_url"], config.WIMTECH_URL)
        self.assertEqual(loaded["wiam_url"], config.WIAM_URL)
        self.assertEqual(loaded["commandes_url"], config.COMMANDES_URL)

    def test_save_ignores_url_values_from_browser_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with patch.object(config, "CONFIG_PATH", path):
                saved = config.save_config({
                    "wimtech_url": "https://wrong.example/wimtech",
                    "wiam_url": "https://wrong.example/wiam",
                    "commandes_url": "https://wrong.example/commandes",
                })

        self.assertEqual(saved["wimtech_url"], config.WIMTECH_URL)
        self.assertEqual(saved["wiam_url"], config.WIAM_URL)
        self.assertEqual(saved["commandes_url"], config.COMMANDES_URL)

    def test_http_mode_is_saved_without_enabling_headless(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            with patch.object(config, "CONFIG_PATH", path):
                saved = config.save_config({"execution_mode": "http"})
                loaded = config.load_config()

        self.assertEqual(saved["execution_mode"], "http")
        self.assertFalse(saved["headless"])
        self.assertEqual(loaded["execution_mode"], "http")
        self.assertFalse(loaded["headless"])

    def test_legacy_headless_setting_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"headless": True}), encoding="utf-8")
            with patch.object(config, "CONFIG_PATH", path):
                loaded = config.load_config()

        self.assertEqual(loaded["execution_mode"], "headless")
        self.assertTrue(loaded["headless"])


if __name__ == "__main__":
    unittest.main()
