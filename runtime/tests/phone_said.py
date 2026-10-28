"""The sentences of a phone, for the tests of the phone family (T8-1): what `phrase_kit` cannot say alone, in two functions. Not a test file.

A sentence of the PHONE_ family ends with the place a phone is sent to (`{where}`: "on the platform's page", then a full stop, or the page link with no stop after it), so a
test that wrote that place as a literal would quote a second sentence of the table (PHONE_WHERE). `placed` says both: the sentence of the key, and its place being the
table's own place for the same language.

  placed(text, key, cfg=None, **fields)   True when `text` is the sentence of `key` with `fields` and its `where` is the page (PHONE_WHERE, then a full stop) or the page
                                          link (PHONE_WHERE_LINK with `url`, no stop) in the language of `cfg`
  refused(text, cfg=None)                 `placed` for PHONE_NOT_ALLOWED: the plain sentence a phone is given for what its profile may not do
  alone(text, key, cfg=None, **fields)    `phrase_kit.said` for a text that is that sentence and nothing else (no line before or after it)

Standard library and the kit only; Python 3.9.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrase_kit as pk  # noqa: E402


def placed(text, key: str, cfg=None, /, **fields) -> bool:
    """True when `text` is the sentence of `key` (a key whose template ends with `{where}`) with `fields`, its place being the page of the language of `cfg`."""
    if not isinstance(text, str) or not pk.said(text, key, cfg, **fields):
        return False
    found = pk.which(text, cfg)
    if found is None or found[0] != key:
        return False
    where = found[1].get("where", "")
    return pk.said(where.rstrip("."), "PHONE_WHERE", cfg) and where.endswith(".") or pk.said(where, "PHONE_WHERE_LINK", cfg)


def refused(text, cfg=None) -> bool:
    return placed(text, "PHONE_NOT_ALLOWED", cfg)


def alone(text, key: str, cfg=None, /, **fields) -> bool:
    """True when `text` is the sentence of `key` with `fields` and a single line."""
    return isinstance(text, str) and "\n" not in text and pk.said(text, key, cfg, **fields)
