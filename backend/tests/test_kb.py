from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent_chat import _merge_review_patch
from app.kb import list_papers, load_paper, save_paper


class KnowledgeBaseTests(unittest.TestCase):
    def test_list_papers_ignores_atomic_write_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "papers"
            papers.mkdir(parents=True)
            (papers / "real.yaml").write_text("id: real\ntitle: Real Paper\n")
            (papers / ".paper_tmp.yaml").write_text("id: temp\ntitle: Temp Paper\n")

            listed = list_papers(root)

            self.assertEqual([paper["id"] for paper in listed], ["real"])

    def test_old_paper_records_get_new_enrichment_defaults_on_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "papers"
            papers.mkdir(parents=True)
            (papers / "legacy.yaml").write_text("id: legacy\ntitle: Legacy Paper\n")

            paper = load_paper(root, "legacy")
            listed = list_papers(root)

            self.assertEqual(paper["author_affiliations"], [])
            self.assertEqual(paper["core_concepts"], [])
            self.assertEqual(paper["key_figures"], [])
            self.assertEqual(listed[0]["author_affiliations"], [])
            self.assertEqual(listed[0]["core_concepts"], [])
            self.assertEqual(listed[0]["key_figures"], [])

    def test_save_paper_persists_new_enrichment_defaults_for_legacy_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "papers"
            papers.mkdir(parents=True)

            save_paper(root, {"id": "legacy", "title": "Legacy Paper"})
            content = (papers / "legacy.yaml").read_text()

            self.assertIn("author_affiliations: []", content)
            self.assertIn("core_concepts: []", content)
            self.assertIn("key_figures: []", content)

    def test_list_papers_skips_files_deleted_during_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            papers = root / "papers"
            papers.mkdir(parents=True)
            (papers / "real.yaml").write_text("id: real\ntitle: Real Paper\n")
            (papers / "vanished.yaml").write_text("id: vanished\ntitle: Vanished Paper\n")

            original_read_text = Path.read_text

            def read_text(path: Path, *args: object, **kwargs: object) -> str:
                if path.name == "vanished.yaml":
                    raise FileNotFoundError(str(path))
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", read_text):
                listed = list_papers(root)

            self.assertEqual([paper["id"] for paper in listed], ["real"])

    def test_enrichment_merge_preserves_existing_key_figure_asset(self) -> None:
        paper = {
            "id": "paper",
            "key_figures": [{
                "label": "Figure 1",
                "title": "System overview",
                "page": 2,
                "caption": "Old caption",
                "reason": "Old reason",
                "image_path": "assets/paper_figures/paper_figure_1_p2.png",
                "crop": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
                "crop_method": "caption",
            }],
        }
        patch_data = {
            "key_figures": [{
                "label": "Figure 1",
                "title": "System overview",
                "page": 2,
                "caption": "New caption",
                "reason": "New reason",
                "image_path": "assets/paper_figures/paper_figure_1_p2_new.png",
                "crop": {"x0": 0.1, "y0": 0.2, "x1": 0.7, "y1": 0.8},
                "crop_method": "agent_pymupdf",
            }],
        }

        merged, _ = _merge_review_patch(paper, patch_data)

        self.assertEqual(merged["key_figures"][0]["image_path"], "assets/paper_figures/paper_figure_1_p2_new.png")
        self.assertEqual(merged["key_figures"][0]["crop"], {"x0": 0.1, "y0": 0.2, "x1": 0.7, "y1": 0.8})
        self.assertEqual(merged["key_figures"][0]["crop_method"], "agent_pymupdf")
        self.assertEqual(merged["key_figures"][0]["caption"], "New caption")


if __name__ == "__main__":
    unittest.main()
