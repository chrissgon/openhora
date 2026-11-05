"""The phrase kit (T8-0a): how a test asserts a sentence of the phrase table without writing the sentence.

A test that must say "the card names the day and the time" used to quote the sentence (`assert "Wed 21/10/2026 at 13:00" in out`),
so every rewording of the table broke every test that quoted it. A test now names the table's key and the values of its fields,
and the table's own wording is pinned once, in one place (T8-0b, the snapshot of every key in each language):

    import phrase_kit as pk
    pk.assert_said(out, "EVENT_AT", cfg, day="Wed 21/10/2026", time="13:00")
    assert pk.said(out, "EVENT_AT", cfg, day="Wed 21/10/2026")           # a field not given matches anything
    key, fields = pk.which(out, cfg)                                       # what sentence is this?

  said(text, key, cfg=None, **fields)       (the first three arguments are positional only, so a field may be called `text`, `key` or `cfg`) True when a line of `text`, or the whole of it, is the sentence of `key` in the language of
                                            `cfg` (the tag `phrases.tag(cfg)`: the project's language, else English; a language with no
                                            table, or a key it lacks, says the English sentence, as `phrases.text` does) with the
                                            given fields; a field not given matches any text. A key of another language does not match.
  which(text, cfg=None)                     (key, {field: text}) of the sentence that `text` (the whole of it, else its first line that
                                            is one) says, looked for among the keys of the language of `cfg` first and then of the other
                                            languages, the template with the most fixed words first; None when none matches
  assert_said(text, key, cfg=None, **fields)  `said`, or an AssertionError that shows the expected template, what was found, and the
                                            nearest key (the same key with another field value, the same key in the other language, or
                                            the key that the text does say)

Only the table is read (`phrases.TABLE`, at the moment of the call), never a sentence of a module's own: a test of this kit carries its own table
and its own literals, so its oracle is not the thing it checks. Standard library only; Python 3.9.
"""
from __future__ import annotations

import difflib
import functools
import os
import re
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import phrases  # noqa: E402  (runtime/: the table, and the tag a configuration chooses)

SHOWN = 300           # characters of the text an assertion message quotes
NEAREST_CUTOFF = 0.5  # the least difflib ratio at which a nearest sentence is named


def _tag(cfg) -> str:
    return phrases.tag(cfg)


def _template(key: str, cfg):
    """(language, template) the text of `key` is looked up in for `cfg`: the language of the configuration, else English, as `phrases.text` does. A key no
    table has is a KeyError (a typo in the test, not a thing to hide)."""
    tag = _tag(cfg)
    template = (phrases.TABLE.get(tag) or {}).get(key)
    if template is not None:
        return tag, template
    english = phrases.DEFAULT
    template = (phrases.TABLE.get(english) or {}).get(key)
    if template is None:
        raise KeyError(f"no phrase key {key!r} in the table (a typo?)")
    return english, template


def _fields_of(template: str) -> list:
    """The field names of a template, in order of first appearance."""
    names = []
    for _literal, name, _spec, _conv in string.Formatter().parse(template):
        if name is not None and name not in names:
            names.append(name)
    return names


def _render(value, spec, conv) -> str:
    """One given value as the template's own `format` writes it (a conversion or a format spec is applied)."""
    if conv == "r":
        value = repr(value)
    elif conv == "s":
        value = str(value)
    elif conv == "a":
        value = ascii(value)
    return format(value, spec or "")


@functools.lru_cache(maxsize=8192)
def _compile(template: str, given: tuple, lines: bool):
    """The regular expression of `template`: a given field is its text exactly (escaped), a field not given is any text (not across a line when the match
    is by lines), a field repeated holds one value. Returns (pattern, {field name: group name})."""
    given_map = dict(given)
    groups, parts = {}, []
    wild = r"[^\n]*?" if lines else r".*?"
    for literal, name, spec, conv in string.Formatter().parse(template):
        parts.append(re.escape(literal))
        if name is None:
            continue
        if name in given_map:
            parts.append(re.escape(_render(given_map[name], spec, conv)))
        elif name in groups:
            parts.append(f"(?P={groups[name]})")
        else:
            groups[name] = f"f{len(groups)}"
            parts.append(f"(?P<{groups[name]}>{wild})")
    body = "".join(parts)
    pattern = re.compile(r"(?m)^" + body + r"$") if lines else re.compile(body, re.S)
    return pattern, groups


def _given(fields: dict) -> tuple:
    return tuple(sorted((name, str(value)) for name, value in fields.items()))


def _check_fields(key: str, template: str, fields: dict) -> None:
    unknown = sorted(set(fields) - set(_fields_of(template)))
    if unknown:
        raise ValueError(f"{key} has no field {unknown[0]!r}: its fields are {_fields_of(template)}")


def _match(text: str, template: str, given: tuple):
    """{field: text} when `text` says the template with the given fields, as a whole or in one of its lines; else None. The fields not given are returned
    with the text they matched."""
    pattern, groups = _compile(template, given, False)
    found = pattern.fullmatch(text)
    if found is None:
        pattern, groups = _compile(template, given, True)
        found = pattern.search(text)
    if found is None:
        return None
    got = {name: found.group(group) for name, group in groups.items()}
    got.update(dict(given))
    return got


def said(text, key: str, cfg=None, /, **fields) -> bool:
    """True when `text` says the sentence of `key` in the language of `cfg` with `fields` (a field not given matches anything)."""
    _language, template = _template(key, cfg)
    _check_fields(key, template, fields)
    if not isinstance(text, str):
        return False
    return _match(text, template, _given(fields)) is not None


def _order(language: str) -> list:
    """The keys of one language, the template with the most fixed characters first (a template that is nearly all placeholders cannot swallow a sentence
    that a more exact one says)."""
    table = phrases.TABLE.get(language) or {}

    def fixed(key):
        return len("".join(literal for literal, _n, _s, _c in string.Formatter().parse(table[key])))
    return sorted(table, key=lambda k: (-fixed(k), k))


def _languages(cfg) -> list:
    """The language of `cfg` first, then the other tables, in the table's own order."""
    first = _tag(cfg)
    rest = [lang for lang in phrases.TABLE if lang != first]
    return ([first] if first in phrases.TABLE else []) + rest


def _find(text: str, cfg):
    """(language, key, fields) of the first sentence of the table that `text` says (the whole text, else its lines from the top), or None."""
    if not isinstance(text, str):
        return None
    candidates = [text] + [line for line in text.splitlines() if line.strip() and line != text]
    for candidate in candidates:
        for language in _languages(cfg):
            table = phrases.TABLE[language]
            for key in _order(language):
                pattern, groups = _compile(table[key], (), False)
                found = pattern.fullmatch(candidate)
                if found is not None:
                    return language, key, {name: found.group(group) for name, group in groups.items()}
    return None


def which(text, cfg=None):
    """(key, {field: text}) of the sentence `text` says, or None. The language of `cfg` is tried first; a sentence of the other language is found too (the
    answer is its key, which the table has in both)."""
    found = _find(text, cfg)
    return (found[1], found[2]) if found else None


def _show(template: str, given: dict) -> str:
    """The template with the given values in place, and `{field}` where any value is accepted."""
    parts = []
    for literal, name, spec, conv in string.Formatter().parse(template):
        parts.append(literal)
        if name is not None:
            parts.append(_render(given[name], spec, conv) if name in given else "{" + name + "}")
    return "".join(parts)


def _quote(text) -> str:
    text = str(text).replace("\n", "\\n")
    return text if len(text) <= SHOWN else text[:SHOWN] + "..."


def _nearest(text: str, language: str, key: str, template: str, given: dict, cfg) -> str:
    """One line of the message that says what the text is instead."""
    wild = _match(text, template, ()) if isinstance(text, str) else None
    if wild is not None:
        different = [f"field {name!r} is {wild[name]!r}, not {str(given[name])!r}"
                     for name in sorted(given) if wild.get(name) != str(given[name])]
        return f"the text is the sentence of {key} ({language}), but " + "; ".join(different or ["a field differs"])
    for other in phrases.TABLE:
        other_template = (phrases.TABLE[other] or {}).get(key)
        if other != language and other_template is not None and _match(text, other_template, ()) is not None:
            return f"the text is the sentence of {key} in {other}, not in {language}"
    found = _find(text, cfg)
    if found:
        return f"the text is the sentence of {found[1]} ({found[0]}) with fields {found[2]}"
    lines = [line for line in str(text).splitlines() if line.strip()] or [str(text)]
    shown = {_show(t, {}): (lang, k) for lang in phrases.TABLE for k, t in phrases.TABLE[lang].items()}
    best = None
    for line in lines:
        close = difflib.get_close_matches(line, list(shown), n=1, cutoff=NEAREST_CUTOFF)
        if close:
            ratio = difflib.SequenceMatcher(None, line, close[0]).ratio()
            if best is None or ratio > best[0]:
                best = (ratio, close[0])
    if best:
        lang, near = shown[best[1]]
        return f"no sentence of the table equals the text; the nearest is {near} ({lang}): {best[1]!r}"
    return "no sentence of the table equals the text, and none is near it"


def assert_said(text, key: str, cfg=None, /, **fields) -> None:
    """Assert that `text` says the sentence of `key` (in the language of `cfg`) with `fields`; the message shows the expected template, what was found and
    the nearest key."""
    language, template = _template(key, cfg)
    _check_fields(key, template, fields)
    if said(text, key, cfg, **fields):
        return
    raise AssertionError("\n".join([
        f"the text does not say {key} ({language}) with fields {dict(sorted(fields.items()))}",
        f"  expected: {_show(template, fields)}",
        f"  got:      {_quote(text)}",
        f"  nearest:  {_nearest(text, language, key, template, {k: str(v) for k, v in fields.items()}, cfg)}",
    ]))
