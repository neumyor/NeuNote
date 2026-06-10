"""Offline English→Chinese translation via Argos Translate."""

from __future__ import annotations

from typing import Any


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
    """Translate a single English string to Chinese."""
    import argostranslate.translate
    _ensure_model()
    return str(argostranslate.translate.translate(text, "en", "zh"))


def translate_paper_summary(paper: dict[str, Any]) -> dict[str, str]:
    """Translate summary fields of a paper. Returns {field: translation}."""
    _ensure_model()

    fields = {
        "abstract": paper.get("abstract", ""),
        "one_sentence": paper.get("one_sentence", ""),
        "problem": paper.get("problem", ""),
    }

    result: dict[str, str] = {}
    for key, text in fields.items():
        if text and text.strip():
            result[key] = translate(text)

    # Translate list fields as concatenated text
    for key in ("contributions", "method", "experiments", "limitations"):
        items = paper.get(key) or []
        if items:
            translated = [translate(item) for item in items if item.strip()]
            result[key] = translated

    return result
