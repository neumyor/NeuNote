from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.kb import load_app_config, save_app_config


class ConfigTests(unittest.TestCase):
    def test_auto_sync_defaults_and_interval_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = load_app_config(root)
            self.assertFalse(config["git_auto_sync"])
            self.assertEqual(config["git_sync_interval_minutes"], 10)
            self.assertEqual(config["default_summary_language"], "en")
            self.assertEqual(config["figure_extraction_mode"], "fast_pillow")
            self.assertTrue(config["figure_reextract_on_enrich"])

            updated = save_app_config(root, {
                "sync_mode": "git",
                "git_auto_sync": True,
                "git_sync_interval_minutes": 25,
                "default_summary_language": "zh",
                "figure_extraction_mode": "agent_pymupdf",
                "figure_reextract_on_enrich": False,
            })
            self.assertTrue(updated["git_auto_sync"])
            self.assertEqual(updated["git_sync_interval_minutes"], 25)
            self.assertEqual(updated["default_summary_language"], "zh")
            self.assertEqual(updated["figure_extraction_mode"], "agent_pymupdf")
            self.assertFalse(updated["figure_reextract_on_enrich"])


if __name__ == "__main__":
    unittest.main()
