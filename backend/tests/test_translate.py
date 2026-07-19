from __future__ import annotations

import unittest
from unittest.mock import patch

from app import translate


class TranslationTests(unittest.TestCase):
    def test_llm_translation_retries_missing_fields_individually(self) -> None:
        paper = {
            "title": "Paper A",
            "abstract": "This paper studies agent systems.",
            "one_sentence": "It improves agent workflows.",
        }
        config = {"claude_api_key": "test-key", "claude_model": "test-model"}

        def fake_request(payload, context, config, *, timeout):  # type: ignore[no-untyped-def]
            if set(payload) == {"abstract", "one_sentence"}:
                raise RuntimeError("could not parse JSON from LLM response (stop_reason=max_tokens)")
            if set(payload) == {"abstract"}:
                return {"abstract": "本文研究智能体系统。"}
            if set(payload) == {"one_sentence"}:
                return {"one_sentence": "它改进了智能体工作流。"}
            raise AssertionError(f"unexpected payload: {payload}")

        with patch.object(translate, "_request_llm_translation", side_effect=fake_request):
            result = translate.translate_paper_summary_llm(paper, config)

        self.assertEqual(result["abstract"], "本文研究智能体系统。")
        self.assertEqual(result["one_sentence"], "它改进了智能体工作流。")

    def test_llm_translation_raises_when_field_retry_still_missing(self) -> None:
        paper = {
            "title": "Paper A",
            "abstract": "This paper studies agent systems.",
        }
        config = {"claude_api_key": "test-key", "claude_model": "test-model"}

        with patch.object(translate, "_request_llm_translation", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "missing fields"):
                translate.translate_paper_summary_llm(paper, config)


if __name__ == "__main__":
    unittest.main()
