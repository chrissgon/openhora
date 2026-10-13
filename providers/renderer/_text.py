"""Closed refusal codes and the text rules of the renderer's inputs.

Every text that reaches a template or a filter graph, whatever its source (the transcript's words, a script's labels,
a caption), is normalised to NFC and refused when it holds a character of the Unicode categories Cc, Cf, Zl or Zp
(a newline, a bidirectional override, a zero-width space, U+2028). A refusal carries a closed code and the name of the
field, never the text that was refused. Standard library only.
"""
from __future__ import annotations

import unicodedata

REFUSED_CATEGORIES = {"Cc", "Cf", "Zl", "Zp"}


class Refusal(ValueError):
    """An input was refused. `code` is a closed word; `field` names where; the refused text is never in the message."""

    def __init__(self, code: str, field: str = ""):
        super().__init__(f"{code}:{field}" if field else code)
        self.code = code
        self.field = field


def clean_text(value, max_len: int, field: str, allow_empty: bool = False) -> str:
    """The text as NFC, or a Refusal. A text longer than max_len is refused, never cut."""
    if not isinstance(value, str):
        raise Refusal("not_text", field)
    value = unicodedata.normalize("NFC", value)
    for ch in value:
        if unicodedata.category(ch) in REFUSED_CATEGORIES:
            raise Refusal("forbidden_character", field)
    value = value.strip()
    if not value and not allow_empty:
        raise Refusal("empty_text", field)
    if len(value) > max_len:
        raise Refusal("text_too_long", field)
    return value


def is_clean(value: str) -> bool:
    return isinstance(value, str) and unicodedata.is_normalized("NFC", value) and not any(
        unicodedata.category(ch) in REFUSED_CATEGORIES for ch in value)
