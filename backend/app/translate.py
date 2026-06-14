"""English→Chinese translation: offline Argos (default) or Claude LLM (optional)."""

from __future__ import annotations

import json
from typing import Any


# ── Argos (offline) backend ─────────────────────────────────────────

def _ensure_model() -> None:
    """Download en→zh model if not already installed."""
    import argostranslate.package
    import argostranslate.translate

    installed = argostranslate.translate.get_installed_languages()
    if any(l.code == "zh" for l in installed):
        return

    argostranslate.package.update_package_index()
    packages = argostranslate.package.get_available_packages()
    pkg = next((p for p in packages if p.from_code == "en" and p.to_code == "zh"), None)
    if pkg:
        argostranslate.package.install_from_path(pkg.download())


def translate(text: str) -> str:
    """Translate a single English string to Chinese via Argos."""
    import argostranslate.translate
    _ensure_model()
    return str(argostranslate.translate.translate(text, "en", "zh"))


def translate_paper_summary(paper: dict[str, Any]) -> dict[str, Any]:
    """Translate summary fields of a paper using Argos.

    Returns a dict matching the same shape as the LLM path so callers can
    treat the two backends interchangeably.
    """
    _ensure_model()

    result: dict[str, Any] = {}
    for key in ("abstract", "one_sentence", "problem"):
        text = paper.get(key, "")
        if text and text.strip():
            result[key] = translate(text)

    for key in ("contributions", "method", "experiments", "limitations"):
        items = paper.get(key) or []
        if items:
            translated = [translate(item) for item in items if item.strip()]
            result[key] = translated

    return result


# ── LLM backend (Claude / Anthropic-compatible API) ─────────────────

# Fields the LLM is expected to translate. The shape must match the Argos
# path so the rest of the pipeline can stay engine-agnostic.
_TRANSLATABLE_FIELDS = (
    "abstract",
    "one_sentence",
    "problem",
    "contributions",
    "method",
    "experiments",
    "limitations",
)

PAPER_TRANSLATE_SYSTEM_PROMPT = """\
You are an academic paper translation assistant. Translate the given English
paper-summary fields into idiomatic Simplified Chinese.

Strict requirements:
- Preserve technical accuracy and domain-specific terminology.
- Keep proper nouns, model names, project names, and acronyms in their
  original form when conventionally used untranslated in Chinese CS
  literature (e.g. Transformer, GPT, LSTM, ResNet, CLIP, CNN, Adam, SGD,
  fine-tuning, in-context learning).
- Preserve any LaTeX formulas, code fragments, and citations verbatim.
- Return a strict JSON object whose keys exactly match the input fields.
- List-valued fields (e.g. contributions) must remain arrays; array
  lengths must match the input.
- Do NOT add any commentary, prefix, suffix, or markdown fence — output
  raw JSON only."""


def _extract_translatable(paper: dict[str, Any]) -> dict[str, Any]:
    """Pick the non-empty fields the LLM should translate."""
    payload: dict[str, Any] = {}
    for key in _TRANSLATABLE_FIELDS:
        value = paper.get(key)
        if isinstance(value, str):
            if value.strip():
                payload[key] = value
        elif isinstance(value, list):
            non_empty = [v for v in value if isinstance(v, str) and v.strip()]
            if non_empty:
                payload[key] = non_empty
    return payload


def _parse_json_block(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction from a model response."""
    import re

    # Try fenced ```json ... ``` first
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Then a bare JSON object
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def translate_paper_summary_llm(
    paper: dict[str, Any],
    config: dict[str, Any],
    *,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Translate summary fields via the configured Claude-compatible LLM.

    Returns a dict with the same shape as :func:`translate_paper_summary`.
    Raises on missing config or unrecoverable API error.
    """
    import httpx

    api_key = (config.get("claude_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("translation_engine='llm' requires claude_api_key to be set")

    endpoint = (config.get("claude_endpoint") or "").strip()
    model = (config.get("claude_model") or "sonnet").strip() or "sonnet"
    base_url = endpoint.rstrip("/") if endpoint else "https://api.anthropic.com"

    payload = _extract_translatable(paper)
    if not payload:
        return {}

    user_prompt = (
        "Translate the following English paper-summary fields into Simplified "
        "Chinese. Return a strict JSON object with the same keys.\n\n"
        f"Input:\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )

    body = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.1,
        "system": PAPER_TRANSLATE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{base_url}/v1/messages", headers=headers, json=body)

    if resp.status_code != 200:
        raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    text_output = ""
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text_output += block.get("text", "")

    parsed = _parse_json_block(text_output)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"could not parse JSON from LLM response: {text_output[:200]}")

    # Normalize: keep only known fields, coerce types, drop empties.
    result: dict[str, Any] = {}
    for key in _TRANSLATABLE_FIELDS:
        if key not in parsed:
            continue
        value = parsed[key]
        if key in ("abstract", "one_sentence", "problem"):
            if isinstance(value, str) and value.strip():
                result[key] = value
        else:  # list-valued
            if isinstance(value, list):
                items = [v for v in value if isinstance(v, str) and v.strip()]
                if items:
                    result[key] = items
            elif isinstance(value, str) and value.strip():
                # Some models collapse lists into a single paragraph; split
                # on newlines or bullet markers as a graceful fallback.
                items = [s.strip().lstrip("•·-—*").strip()
                         for s in _split_lines(value) if s.strip()]
                if items:
                    result[key] = items

    return result


def _split_lines(text: str) -> list[str]:
    import re
    return re.split(r"[\n\r]+|(?<=[。！？!?；;])\s+|(?:^|\s)[•·\-—*]\s*", text)
