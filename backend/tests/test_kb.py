from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent_chat import _merge_review_patch, _review_string_list, run_agent_paper_review_sync
from app.kb import (
    anthropic_request_options,
    create_job,
    ensure_kb,
    fail_job,
    list_paper_summaries,
    list_papers,
    load_job,
    load_paper,
    pause_job,
    resume_job,
    retry_job,
    run_enrichment_job,
    save_paper,
)


class KnowledgeBaseTests(unittest.TestCase):
    def test_deepseek_anthropic_requests_disable_thinking(self) -> None:
        self.assertEqual(
            anthropic_request_options("https://api.deepseek.com/anthropic"),
            {"thinking": {"type": "disabled"}},
        )
        self.assertEqual(anthropic_request_options("https://api.anthropic.com"), {})
        self.assertEqual(anthropic_request_options("https://deepseek.com.example.org"), {})

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

    def test_paper_list_summaries_omit_detail_only_enrichment_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            save_paper(root, {
                "id": "paper",
                "title": "Paper",
                "abstract": "Short abstract",
                "one_sentence": "Short summary",
                "tags": ["agents"],
                "core_concepts": [{"concept": "Long payload", "explanation": "x" * 5000}],
                "translations": {"abstract": "译文" * 5000},
                "agent_reviews": [{"notes": ["x" * 5000]}],
            })

            summary = list_paper_summaries(root)[0]

        self.assertEqual(summary["title"], "Paper")
        self.assertEqual(summary["tags"], ["agents"])
        self.assertNotIn("core_concepts", summary)
        self.assertNotIn("translations", summary)
        self.assertNotIn("agent_reviews", summary)

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

    def test_enrichment_merge_tolerates_malformed_model_list_fields(self) -> None:
        paper = {"id": "paper", "title": "Paper", "tags": ["existing"]}
        patch_data = {
            "contributions": "A single contribution returned as a string.",
            "method": {"unexpected": "object"},
            "tags": ["agent", {"unexpected": "object"}, ""],
        }

        merged, _ = _merge_review_patch(paper, patch_data)

        self.assertEqual(merged["contributions"], ["A single contribution returned as a string."])
        self.assertNotIn("method", merged)
        self.assertEqual(merged["tags"], ["agent"])
        self.assertEqual(_review_string_list("One note"), ["One note"])
        self.assertEqual(_review_string_list(["Good", None, {"bad": True}]), ["Good"])

    def test_mineru_document_title_overrides_upload_time_title(self) -> None:
        paper = {
            "id": "expel",
            "title": "ExpeL LLM Agents Are Experiential Learners Andrew Zhao Daniel Huang",
        }

        merged, notes = _merge_review_patch(
            paper,
            {"title": None},
            mineru_document_title="ExpeL: LLM Agents Are Experiential Learners",
        )

        self.assertEqual(merged["title"], "ExpeL: LLM Agents Are Experiential Learners")
        self.assertTrue(any(note.startswith("title (MinerU):") for note in notes))

    def test_mineru_title_is_saved_without_an_agent_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            source = root / "originals/papers/example.pdf"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"%PDF-test")
            save_paper(root, {
                "id": "example",
                "title": "example upload filename",
                "source_pdf": "originals/papers/example.pdf",
            })
            mineru_result = {
                "mode": "precision",
                "document_title": "A Source-Verified Paper Title",
                "markdown_path": "logs/mineru/example/parsed.md",
                "json_path": "logs/mineru/example/layout.json",
                "assets": [],
                "markdown": "# A Source-Verified Paper Title",
            }
            with patch("app.mineru.extract_paper_with_mineru", return_value=mineru_result):
                result = run_agent_paper_review_sync(root, "example", config={})

            saved = load_paper(root, "example")
            self.assertEqual(result["status"], "parsed")
            self.assertEqual(saved["title"], "A Source-Verified Paper Title")
            self.assertEqual(saved["mineru"]["document_title"], "A Source-Verified Paper Title")

    def test_agent_review_sync_reports_worker_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "app.agent_chat.run_agent_paper_review",
                side_effect=RuntimeError("malformed review payload"),
            ):
                result = run_agent_paper_review_sync(root, "paper")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["detail"], "RuntimeError: malformed review payload")

    def test_job_pause_reason_prevents_queue_resume_from_manual_pause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            manual = create_job(root, "paper-a", "Paper A")
            queued = create_job(root, "paper-b", "Paper B")

            pause_job(root, manual["id"])
            pause_job(root, queued["id"], reason="queue")

            self.assertEqual(resume_job(root, manual["id"], reason="queue")["status"], "paused")
            resumed = resume_job(root, queued["id"], reason="queue")

            self.assertEqual(resumed["status"], "queued")
            self.assertIsNone(resumed["pause_reason"])

    def test_failed_job_records_error_and_retry_resets_runnable_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            job = create_job(root, "paper-a", "Paper A")

            failed = fail_job(root, job["id"], "Agent review failed")
            retried = retry_job(root, job["id"])

            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["last_error"], "Agent review failed")
            self.assertEqual(retried["status"], "queued")
            self.assertEqual(retried["progress"], 0)
            self.assertIsNone(retried["started_at"])
            self.assertIsNone(retried["completed_at"])
            self.assertIsNone(retried["last_error"])

    def test_required_translation_failure_marks_job_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_kb(root)
            save_paper(root, {
                "id": "paper-a",
                "title": "Paper A",
                "abstract": "This paper studies agent systems and reports new experimental results.",
                "source_pdf": "originals/paper-a.pdf",
                "core_concepts": [{"concept": "Agent", "explanation": "A software actor."}],
                "translations": {},
            })
            job = create_job(root, "paper-a", "Paper A")

            with (
                patch("app.kb.enrich_paper", return_value=None),
                patch("app.agent_chat.run_agent_paper_review_sync", return_value={"status": "ok", "notes": []}),
                patch("app.translate.translate_paper_summary_llm", side_effect=RuntimeError("could not parse JSON from LLM response:")),
            ):
                run_enrichment_job(root, "paper-a", job["id"], {
                    "claude_api_key": "test-key",
                    "claude_model": "test-model",
                    "translation_engine": "llm",
                })

            saved = load_job(root, job["id"])
            self.assertEqual(saved["status"], "failed")
            self.assertEqual(saved["stage"], "failed")
            self.assertIn("Translation failed", saved["last_error"])


if __name__ == "__main__":
    unittest.main()
