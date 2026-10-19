"""The natural writes (package NR-5, runtime/natural_writes.py and the family modules): the shape of the language data, the registry of the families, the toolkit the
families read lines with, and (further down) each form of the calendar and files families in pt-BR and en. Pure: no store, no model, no network, no clock but the one
a test passes. Every name, address and file is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st

natural = st.load("natural")
nw = st.load("natural_writes")


def tables():
    return nw._tables()


def test_every_shipped_table_has_writes_of_the_shape_the_schema_asks():
    for table in tables():
        assert nw.writes_of(table), table["tag"]
        nw.check_writes(table)
        natural.check_requests(table)


def test_no_phrase_of_writes_holds_a_character_a_regular_expression_means_anything_by():
    for table in tables():
        body = nw.writes_of(table)
        for key in nw.TOP_KEYS:
            assert all(re.fullmatch(r"[a-z0-9]+( [a-z0-9]+)*", p) for p in body[key])
        for section, keys in nw.SECTIONS.items():
            for key in keys:
                assert all(re.fullmatch(r"[a-z0-9]+( [a-z0-9]+)*", p) for p in body[section].get(key, [])), (table["tag"], section, key)


def test_the_mail_lists_are_there_for_the_mail_package_to_fill():
    for table in tables():
        assert set(nw.writes_of(table)["mail"]) == set(nw.SECTIONS["mail"])


def test_a_phrase_with_a_regular_expression_character_or_an_unknown_key_is_refused():
    base = {"tag": "xx", "requests": {"writes": {"polite": ["please."]}}}
    with pytest.raises(ValueError, match="no regular-expression character"):
        nw.check_writes(base)
    with pytest.raises(ValueError, match="has no key 'bogus'"):
        nw.check_writes({"tag": "xx", "requests": {"writes": {"bogus": []}}})
    with pytest.raises(ValueError, match="writes is an object"):
        natural.check_requests({"tag": "xx", "requests": {"writes": ["x"]}})


def test_the_registry_names_the_families_and_every_operation_has_one():
    assert set(nw.FAMILIES) <= {"calendar", "files", "mail"}
    assert {name for name, cls in natural.CLASSES.items() if cls == "E"} == set(nw.OP_FAMILY)


def test_line_gives_back_the_persons_words_not_the_folded_ones():
    line = nw.Line("  Manda  PARA Bia: Até Amanha  ")
    start, end = line.find(["para"])
    assert line.span(start, end) == "PARA"
    assert line.span(*line.find(["ate"])) == "Até"


@pytest.mark.parametrize("text, expected", [("2", [2]), ("2, 4 e 7", [2, 4, 7]), ("1 a 3", [1, 2, 3]), ("#5", [5]), ("2 e 2", None), ("0", None), ("2 mas 3", None),
                                            ("3 a 2", None), ("1 a 40", None), ("", None)])
def test_numbers_reads_a_list_of_references_and_nothing_else(text, expected):
    line = nw.Line(text)
    assert nw.numbers(line, 0, len(line.norm), tables()) == expected


def test_a_service_word_names_an_account_only_with_its_introducing_word_or_by_itself_when_it_is_two_words():
    t = tables()
    for text, expected in [("salva no drive", "google"), ("save it to my onedrive", "microsoft"), ("add to my google calendar", "google"),
                           ("reuniao do google", None), ("no outlook e no gmail", None), ("sem conta", None)]:
        found = nw.service(nw.Line(text), t)
        assert (found[0] if found else None) == expected, text


def test_a_reminder_trigger_outside_the_text_spans_makes_the_line_no_write_form():
    t = tables()
    line = nw.Line("manda tal coisa e me lembra amanha")
    assert nw.reminder_outside(line, t, {}) is True
    start = line.norm.index("me lembra")
    assert nw.reminder_outside(line, t, {"body": (0, len(line.norm))}) is False
    assert nw.reminder_outside(nw.Line("sem gatilho"), t, {}) is False
    assert start > 0


def test_a_line_over_the_word_cap_or_with_a_mention_or_a_slash_is_never_claimed():
    assert nw._claim("marca dentista quinta") is True
    assert nw._claim(" ".join(["a"] * (nw.LINE_WORDS_MAX + 1))) is False
    assert nw._claim("marca @inbox quinta") is False
    assert nw._claim("manda para bia@exemplo.example") is True
    assert nw._claim("/remind 10 x") is False
    assert nw._claim("   ") is False
