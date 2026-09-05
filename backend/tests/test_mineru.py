from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.mineru import _extract_document_title, MinerUExtractionError, extract_paper_with_mineru


class MinerUExtractionTests(unittest.TestCase):
    def _run(self, command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        (output / "parsed.md").write_text(
            "# A Paper\n\n![Figure 1](images/figure.png)\n", encoding="utf-8",
        )
        image_dir = output / "images"
        image_dir.mkdir()
        (image_dir / "figure.png").write_bytes(b"png")
        (output / "layout.json").write_text(
            '{"page": 3, "image_path": "images/figure.png"}', encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_precision_parser_persists_markdown_and_imports_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "originals/papers/example.pdf"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"%PDF-test")
            with patch("app.mineru.shutil.which", return_value="/usr/local/bin/mineru-open-api"), patch(
                "app.mineru.subprocess.run", side_effect=self._run,
            ) as run:
                result = extract_paper_with_mineru(root, "example", source, {
                    "mineru_api_token": "secret", "mineru_allow_remote": True,
                })

            command = run.call_args.args[0]
            self.assertEqual(result["mode"], "precision")
            self.assertIn("extract", command)
            self.assertIn("--format", command)
            self.assertIn("md,json", command)
            self.assertIn("--token", command)
            self.assertEqual(result["assets"][0]["page"], 3)
            self.assertEqual(result["document_title"], "A Paper")
            self.assertEqual(result["assets"][0]["image_path"], "assets/paper_figures/example_mineru_1.png")
            self.assertTrue((root / result["markdown_path"]).exists())
            self.assertTrue((root / result["assets"][0]["image_path"]).exists())

    def test_flash_is_the_no_token_default_and_remote_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "paper.pdf"
            source.write_bytes(b"%PDF-test")
            with patch("app.mineru.shutil.which", return_value="mineru-open-api"), patch(
                "app.mineru.subprocess.run", side_effect=self._run,
            ) as run:
                result = extract_paper_with_mineru(root, "example", source, {})
            self.assertEqual(result["mode"], "flash")
            self.assertIn("flash-extract", run.call_args.args[0])
            with self.assertRaisesRegex(MinerUExtractionError, "disabled"):
                extract_paper_with_mineru(root, "example-disabled", source, {"mineru_allow_remote": False})

    def test_title_extraction_only_accepts_a_document_level_heading(self) -> None:
        self.assertEqual(
            _extract_document_title("# ExpeL: LLM Agents Are Experiential Learners\n\n## Abstract\n"),
            "ExpeL: LLM Agents Are Experiential Learners",
        )
        self.assertEqual(_extract_document_title("## Introduction\nBody"), "")


if __name__ == "__main__":
    unittest.main()
