"""The time facts a write line is checked with are kept by the CONTENT of the language tables, not by the identity of the objects (review of NR-5a, package LIVE-2):
runtime/natural_writes.py `_facts`, `_digest`, `clear_facts`. An object that is freed can hand its id to another, so a key made of `id()` could serve one table's answer to
another; a key made of a digest of the content cannot, and the cache is bounded and cleared after every test (runtime/tests/conftest.py).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_facts.py
"""
from __future__ import annotations

import copy
import datetime

import standin_tree as st

natural_writes = st.load("natural_writes")
natural_time = st.load("natural_time")

NOW = datetime.datetime(2026, 10, 19, 9, 0)


def test_two_tables_with_the_same_content_share_an_answer_and_a_changed_one_does_not():
    natural_writes.clear_facts()
    tables = natural_time.languages()
    first = natural_writes._facts("quinta as 10h", NOW, tables)
    assert natural_writes._facts("quinta as 10h", NOW, copy.deepcopy(tables)) == first and len(natural_writes._FACTS) == 1, "the key is the content: a copy hits"
    changed = copy.deepcopy(tables)
    changed[0]["tag"] = changed[0]["tag"] + "-edited"
    natural_writes._facts("quinta as 10h", NOW, changed)
    assert len(natural_writes._FACTS) == 2, "another content is another key"


def test_a_digest_is_held_with_its_table_so_an_id_is_never_reused_while_its_entry_lives():
    natural_writes.clear_facts()
    table = {"tag": "xx", "days": ["a"]}
    digest = natural_writes._digest(table)
    assert natural_writes._DIGESTS[id(table)][0] is table and natural_writes._digest(table) == digest
    assert natural_writes._digest({"tag": "xx", "days": ["a"]}) == digest and natural_writes._digest({"tag": "xx", "days": ["b"]}) != digest


def test_the_cache_is_bounded_and_can_be_cleared(monkeypatch):
    natural_writes.clear_facts()
    monkeypatch.setattr(natural_writes, "_FACTS_MAX", 3)
    tables = natural_time.languages()
    for n in range(7):
        natural_writes._facts(f"quinta as {n}h", NOW, tables)
    assert len(natural_writes._FACTS) <= 3
    natural_writes.clear_facts()
    assert natural_writes._FACTS == {} and natural_writes._DIGESTS == {}


def test_a_test_leaves_nothing_behind_for_the_next_one_the_fixture_clears_it():
    natural_writes._facts("sexta as 15h", NOW, natural_time.languages())
    assert natural_writes._FACTS, "kept during the test; runtime/tests/conftest.py clears it after"
