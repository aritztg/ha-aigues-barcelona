"""Checks on the translation files that hassfest also enforces.

hassfest runs in CI inside a Docker image, so these catch the same mistakes on a
developer's machine, where the error otherwise only turns up after a push.
"""

import json
import re
from pathlib import Path

import pytest

TRANSLATIONS = (
    Path(__file__)
    .resolve()
    .parent.parent.joinpath("custom_components", "aigues_barcelona", "translations")
)
LANGUAGES = sorted(p.stem for p in TRANSLATIONS.glob("*.json"))


def load(lang: str) -> dict:
    return json.loads(TRANSLATIONS.joinpath(f"{lang}.json").read_text(encoding="utf-8"))


def strings(node, path="") -> list[tuple[str, str]]:
    """Every string in the file, paired with its dotted path."""
    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        return [
            p for k, v in node.items() for p in strings(v, f"{path}.{k}".lstrip("."))
        ]
    return []


def test_there_are_translations():
    assert LANGUAGES, "no translation files found"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_no_urls_in_translation_strings(lang):
    """hassfest: "the string should not contain URLs, please use description
    placeholders instead". A link has to arrive through
    description_placeholders so that translators never handle the address.
    """
    offenders = [
        (path, text)
        for path, text in strings(load(lang))
        if re.search(r"https?://", text)
    ]
    assert not offenders, f"{lang}.json has hardcoded URLs: {offenders}"


@pytest.mark.parametrize("lang", LANGUAGES)
def test_placeholders_match_english(lang):
    """A missing placeholder renders as raw braces to the user."""
    english = {
        path: set(re.findall(r"\{(\w+)\}", text)) for path, text in strings(load("en"))
    }
    for path, text in strings(load(lang)):
        expected = english.get(path)
        if expected:
            assert set(re.findall(r"\{(\w+)\}", text)) == expected, (
                f"{lang}.json at {path} does not use the same placeholders as en.json"
            )


@pytest.mark.parametrize("lang", LANGUAGES)
def test_every_english_string_is_translated(lang):
    """Otherwise Home Assistant falls back to English for that one string."""
    missing = [
        path for path, _ in strings(load("en")) if path not in dict(strings(load(lang)))
    ]
    assert not missing, f"{lang}.json is missing: {missing}"
