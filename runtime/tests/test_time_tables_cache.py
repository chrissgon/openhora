"""The patterns of a language table are kept by the table's identity and are never kept without a bound (runtime/natural_time.py `_comp`; runtime/tests/old_claim.py `_frozen_tables`; decision 2026-10-30, fuzz-slow-deadlines).

The frozen copy of the old reading (CANDIDATE-OUT 2) made a new copy of the tables on every call, and `natural_time._comp` keeps the compiled patterns of a table by its identity and dropped none: every
line the oracle of the private-line fuzz was asked about built them again (a third more time) and kept them for good (about 40 kB a line: 800 MB after 20,000 lines, several GB in the full fuzz of
test_registry_data.py, which ran out of time and of memory on a CI machine). Now the oracle makes its copy of a live table once, and `_comp` keeps at most COMPILED_MAX tables.

What is proven here, each with its vacuity:

  * Any number of fresh table objects leaves at most COMPILED_MAX entries, and the answer of `find` is the same with a fresh table as with the kept one. Vacuity: the unbounded cache of before grows past it.
  * The oracle asked about many lines adds no entry after the first. Vacuity: a memo that remembers nothing (the behaviour of before) adds one entry for each call.

Offline, no model. Invented lines.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_time_tables_cache.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import natural_time as nt  # noqa: E402
import old_claim  # noqa: E402

LINE = "remind me tomorrow at 9am to call Maria"
PLAIN = "call Maria tomorrow at 9am"          # no head of the old reading takes it, so the oracle reads its times (`nt.find`) on the tables it was given


def unbounded(table):
    """`_comp` as it was: one entry for each table object, none dropped."""
    found = nt._compiled.get(id(table))
    if found is None or found.table is not table:
        found = nt._compiled[id(table)] = nt._Compiled(table)
    return found


class Forgetful(dict):
    """A memo that keeps nothing: the oracle's behaviour before the fix."""

    def __setitem__(self, key, value):
        pass


@pytest.fixture(autouse=True)
def an_empty_cache_before_and_after(monkeypatch):
    monkeypatch.setattr(nt, "_compiled", {})
    yield


def test_fresh_table_objects_leave_at_most_the_bound_and_the_same_answer():
    live = nt.languages()
    want = [(h["kind"], h["s"], h["e"]) for h in nt.find(LINE, live)["hits"]]
    assert want, "the line holds a time"
    for _ in range(3 * nt.COMPILED_MAX):
        fresh = copy.copy(live)
        fresh = [dict(t) for t in fresh]
        got = nt.find(LINE, fresh)
        assert [(h["kind"], h["s"], h["e"]) for h in got["hits"]] == want
        assert len(nt._compiled) <= nt.COMPILED_MAX


def test_vacuity_the_unbounded_cache_of_before_grows_with_the_tables_it_is_given(monkeypatch):
    monkeypatch.setattr(nt, "_comp", unbounded)
    live = nt.languages()
    for _ in range(3 * nt.COMPILED_MAX):
        nt.find(LINE, [dict(t) for t in live])
    assert len(nt._compiled) > nt.COMPILED_MAX


def test_the_oracle_makes_its_copy_of_a_live_table_once():
    first = old_claim._frozen_tables(None)
    assert [id(t) for t in old_claim._frozen_tables(None)] == [id(t) for t in first]
    old_claim.candidate(PLAIN)
    after_first = len(nt._compiled)
    assert 0 < after_first <= 2 * len(nt.languages())
    for _ in range(300):
        old_claim.candidate(PLAIN)
    assert len(nt._compiled) == after_first


def test_vacuity_an_oracle_that_copies_on_every_call_adds_an_entry_for_each_call(monkeypatch):
    monkeypatch.setattr(old_claim, "_FROZEN", Forgetful())
    monkeypatch.setattr(nt, "_comp", unbounded)
    for _ in range(50):
        old_claim.candidate(PLAIN)
    assert len(nt._compiled) > 50
