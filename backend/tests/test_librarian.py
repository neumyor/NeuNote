from __future__ import annotations

import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from app.kb import ensure_kb, load_paper, save_paper
from app.librarian import (
    _assert_public_http_url,
    build_fulltext_index,
    create_pdf_archive,
    create_action,
    import_action,
    merge_metadata,
    normalize_venues,
    search_dblp_venues,
    search_papers_aggregated,
    search_fulltext,
    pdf_archive_path,
    _index_connection,
    _http_json,
)


class LibrarianTests(unittest.TestCase):
    def test_pdf_archive_packages_only_downloaded_local_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            for paper_id, title in (("paper-a", "Paper A"), ("paper-b", "Paper B")):
                source = root / "originals/papers" / f"{paper_id}.pdf"
                writer = PdfWriter()
                writer.add_blank_page(width=200, height=200)
                with source.open("wb") as handle:
                    writer.write(handle)
                save_paper(root, {
                    "id": paper_id, "title": title,
                    "source_pdf": str(source.relative_to(root)), "download_status": "downloaded",
                })
            save_paper(root, {"id": "missing", "title": "Missing PDF", "download_status": "not_downloaded"})

            result = create_pdf_archive(root, ["paper-a", "missing", "paper-b", "paper-a"])
            archive = pdf_archive_path(root, result["archive_id"])

            self.assertTrue(archive.is_file())
            self.assertEqual(result["paper_count"], 2)
            self.assertEqual(result["unavailable"], [{"paper_id": "missing", "reason": "PDF is not downloaded"}])
            with zipfile.ZipFile(archive) as packaged:
                names = packaged.namelist()
                self.assertIn("manifest.json", names)
                self.assertEqual(len([name for name in names if name.startswith("papers/")]), 2)

    def test_v12_migration_preserves_legacy_data_and_marks_existing_pdf_downloaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "papers").mkdir(parents=True)
            (root / "originals/papers").mkdir(parents=True)
            (root / "originals/papers/legacy.pdf").write_bytes(b"%PDF-placeholder")
            (root / "papers/legacy.yaml").write_text(
                "id: legacy\ntitle: Legacy\nsource_pdf: originals/papers/legacy.pdf\ntags: [keep]\n",
                encoding="utf-8",
            )

            ensure_kb(root)
            paper = load_paper(root, "legacy")

            self.assertEqual(paper["download_status"], "downloaded")
            self.assertEqual(paper["index_status"], "not_indexed")
            self.assertEqual(paper["tags"], ["keep"])

    def test_metadata_merge_fills_blanks_without_resetting_user_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            save_paper(root, {
                "id": "paper-a", "title": "Same Paper", "doi": "10.1/example",
                "authors": [], "tags": ["personal"], "download_status": "downloaded",
                "index_status": "indexed", "review_notes": [{"text": "keep"}],
            })

            result = merge_metadata(root, {
                "title": "Same Paper", "doi": "https://doi.org/10.1/EXAMPLE",
                "authors": ["A. Author"], "abstract": "New abstract", "tags": [],
                "download_status": "not_downloaded", "metadata_source": "OpenAlex",
            })
            paper = load_paper(root, "paper-a")

            self.assertEqual(result["status"], "merged")
            self.assertEqual(paper["authors"], ["A. Author"])
            self.assertEqual(paper["tags"], ["personal"])
            self.assertEqual(paper["download_status"], "downloaded")
            self.assertEqual(paper["index_status"], "indexed")
            self.assertEqual(paper["review_notes"], [{"text": "keep"}])

    def test_identifier_conflict_does_not_merge_by_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            save_paper(root, {"id": "paper-a", "title": "Same Paper", "doi": "10.1/old"})
            result = merge_metadata(root, {"title": "Same Paper", "doi": "10.1/new"})
            self.assertEqual(result["status"], "conflict")

    def test_import_action_is_confirmation_gated_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            action = create_action(root, "metadata_import", [{"title": "Metadata Only"}])
            self.assertEqual(list((root / "papers").glob("*.yaml")), [])
            first = import_action(root, action["id"])
            second = import_action(root, action["id"])
            self.assertEqual(first["status"], "completed")
            self.assertEqual(first, second)

    def test_neurips_alias_uses_dblp_nips_stream(self) -> None:
        self.assertEqual(normalize_venues(["NeurIPS", "NIPS", "NeurIPS 2025"]), ["nips"])

    def test_unsupported_venue_fails_before_network(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not support"):
            normalize_venues(["ImaginaryConf"])

    @patch("app.librarian._http_json")
    def test_dblp_neurips_list_normalizes_metadata_and_pdf(self, request: object) -> None:
        request.return_value = {"result": {"hits": {"@total": "1", "hit": [{"info": {
            "title": "A NeurIPS Paper.", "authors": {"author": [{"text": "A. Author"}]},
            "year": "2025", "venue": "NeurIPS",
            "ee": "http://papers.nips.cc/paper_files/paper/2025/hash/abc-Abstract-Conference.html",
        }}]}}}
        results = search_dblp_venues(["NeurIPS"], [2025])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "A NeurIPS Paper")
        self.assertEqual(results[0]["authors"], ["A. Author"])
        self.assertTrue(results[0]["pdf_url"].endswith("abc-Paper-Conference.pdf"))

    @patch("app.librarian.search_arxiv", side_effect=RuntimeError("rate limited"))
    @patch("app.librarian.search_crossref", return_value=[{"title": "Shared", "doi": "10.1/x", "authors": [], "abstract": "", "metadata_source": "Crossref"}])
    @patch("app.librarian.search_openalex", return_value=[{"title": "Shared", "doi": "10.1/x", "authors": ["A"], "abstract": "Abstract", "metadata_source": "OpenAlex"}])
    def test_aggregator_returns_partial_results_with_warning(self, _oa: object, _cr: object, _arxiv: object) -> None:
        results, warnings = search_papers_aggregated([], [2025], "shared", 20)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["authors"], ["A"])
        self.assertTrue(any("arXiv" in warning for warning in warnings))

    @patch("app.librarian.search_arxiv", return_value=[{"title": "Arxiv result", "arxiv_id": "2501.1", "metadata_source": "arXiv"}])
    @patch("app.librarian.search_crossref", return_value=[{"title": "Crossref result", "doi": "10.1/c", "metadata_source": "Crossref"}])
    @patch("app.librarian.search_openalex", return_value=[{"title": f"OpenAlex {index}", "doi": f"10.1/o{index}", "metadata_source": "OpenAlex"} for index in range(5)])
    def test_aggregator_round_robins_providers_before_limit(self, _oa: object, _cr: object, _arxiv: object) -> None:
        results, warnings = search_papers_aggregated([], [2025], "agents", 3)
        self.assertEqual(warnings, [])
        self.assertEqual({item["metadata_source"] for item in results}, {"OpenAlex", "Crossref", "arXiv"})

    def test_fulltext_index_marks_pdf_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            pdf = root / "originals/papers/paper.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            with pdf.open("wb") as handle:
                writer.write(handle)
            save_paper(root, {"id": "paper", "title": "Paper", "source_pdf": "originals/papers/paper.pdf", "download_status": "downloaded"})
            result = build_fulltext_index(root, "paper")
            self.assertEqual(result["pages"], 1)
            self.assertEqual(load_paper(root, "paper")["index_status"], "indexed")

    @patch("app.librarian.time.sleep")
    @patch("app.librarian.urllib.request.urlopen")
    def test_provider_retries_transient_http_errors(self, open_url: object, _sleep: object) -> None:
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok": true}'
        open_url.side_effect = [urllib.error.HTTPError("https://example", 500, "error", {}, None), response]
        self.assertEqual(_http_json("https://example", {}), {"ok": True})
        self.assertEqual(open_url.call_count, 2)

    def test_download_rejects_private_networks(self) -> None:
        with self.assertRaises(ValueError):
            _assert_public_http_url("http://127.0.0.1/paper.pdf")

    def test_fulltext_search_excludes_metadata_only_and_unindexed_papers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            save_paper(root, {"id": "indexed", "title": "Indexed", "index_status": "indexed"})
            save_paper(root, {"id": "metadata", "title": "Metadata", "index_status": "not_indexed"})
            with _index_connection(root) as conn:
                conn.execute("INSERT INTO paper_chunks(paper_id,page,chunk_index,content) VALUES (?,?,?,?)", ("indexed", 2, 0, "agent harness safety"))
                conn.execute("INSERT INTO paper_chunks(paper_id,page,chunk_index,content) VALUES (?,?,?,?)", ("metadata", 1, 0, "agent harness safety"))
            results = search_fulltext(root, "agent harness")
            self.assertEqual([item["paper_id"] for item in results], ["indexed"])


if __name__ == "__main__":
    unittest.main()
