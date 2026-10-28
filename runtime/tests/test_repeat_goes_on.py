"""A line that holds a repetition phrase goes on to the interpreter since catalog version 2 (package CB-9, round 2).

The measurement of 2026-10-28 found that the closed forms claimed seven of the seventeen repeating lines of its sets before the interpreter: `natural_writes.candidate` took the commonest pt-BR
phrasings ("marca ... toda segunda as 7h", "poe na agenda ... todo dia") and `ops_natural_writes.advance` answered NW_RECURRING_EVENT, "an event that repeats is not available yet", and the reminders'
calendar intent (`natural.candidate`, "agenda ... todo dia as 18h") asked "an event, or something else?". At version 2 the interpreter reads the slot `repeat` (CB-7: a daily or weekly series, or the
honest sentence), so none of those closed forms may take the line first: `natural.repeat_goes_on` is what both ask. At version 1 nothing changes.

The gate is limited to a line of a sender whom the interpreter reads (the maintainer, 2026-10-28): `natural.repeat_scope(on)` is open only when the interpreter is ON for that sender and language,
and outside a scope nothing goes on, so with the interpreter off (or in any entry that opens no scope) a repeating line keeps the closed form's honest "not available yet" answer, as before, and never
goes to the router. This is the restrictive default.

What is checked, with this test's own literals: for each of the ten repeating lines (the seven the closed forms claimed at version 1 and three that they never did) neither `natural_writes.candidate`
nor `natural.candidate` nor the bridge's `messaging_inbound.parse` claims the line at version 2 with the scope on (the bridge says `text`: the line goes to `say` and its interpreter), and at version 1
and at version 2 with the scope off or none the seven are claimed as they were; a line with a time and no repetition and a reminder that repeats are claimed in every case; the fixed operation
(`op="event-create"`, what the interpreter's seed uses) still reads a repeating line at version 2; the scope asks its question at most once, only for a repeating line, never outside the version,
ends with its block and reads a failing question as off; and a vacuity case that fails on a planted wrong result (the rule turned off gives the seven back at version 2 with the scope on). Offline;
invented lines.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_repeat_goes_on.py
"""
from __future__ import annotations

import contextlib

import pytest

import standin_tree as st

natural = st.load("natural")
natural_writes = st.load("natural_writes")
messaging_inbound = st.load("messaging_inbound")
operations = st.load("operations")

CLAIMED_AT_V1 = (
    "marca academia toda segunda às 7h",      # validate: allow english-only -- the Portuguese lines under test
    "coloca na agenda aula de inglês toda sexta às 16h",      # validate: allow english-only -- the Portuguese lines under test
    "marca fisioterapia a cada duas semanas na quinta às 8h",      # validate: allow english-only -- the Portuguese lines under test
    "marca revisão do orçamento todo mês no dia 10 às 9h",      # validate: allow english-only -- the Portuguese lines under test
    "põe na agenda alongamento todo dia às 17h",      # validate: allow english-only -- the Portuguese lines under test
    "marca natação toda quinta às 19h",      # validate: allow english-only -- the Portuguese lines under test
    "marca reunião de pais a cada 15 dias na sexta às 18h",      # validate: allow english-only -- the Portuguese lines under test
)
NEVER_CLAIMED = (
    "bota na agenda reunião de equipe toda quarta às 10h",      # validate: allow english-only -- the Portuguese lines under test
    "put gym on my calendar every Monday at 7am",
)
ASKED_AT_V1 = "agenda corrida no parque todo dia às 18h"      # validate: allow english-only -- the Portuguese line under test: the calendar intent asks "an event, or something else?"
NO_REPEAT = "marca dentista amanhã às 9h"      # validate: allow english-only -- the Portuguese line under test
REMINDER = "me lembra toda segunda de regar as plantas"      # validate: allow english-only -- the Portuguese line under test


def at_version(monkeypatch, version):
    monkeypatch.setattr(operations, "LINE_CATALOG", version)


def parsed(line):
    return messaging_inbound.parse({"text": line})


def test_at_version_1_the_closed_forms_claim_the_seven_lines_as_they_did(monkeypatch):
    at_version(monkeypatch, 1)
    for line in CLAIMED_AT_V1:
        assert natural_writes.candidate(line) == {"family": "calendar", "op": "event-create"}, line
        assert natural.candidate(line) == {"op": "calendar-event-create", "how": "trigger"}, line
        assert parsed(line)["kind"] == "natural" and parsed(line)["op"] == "write", line
    assert natural.candidate(ASKED_AT_V1) == {"op": "calendar-event-create", "how": "ask"} and parsed(ASKED_AT_V1)["kind"] == "natural"
    assert not natural_writes.candidate(NEVER_CLAIMED[0]) and parsed(NEVER_CLAIMED[0])["kind"] == "text"


def test_at_version_2_with_the_scope_on_no_closed_form_claims_a_repeating_line_and_the_bridge_sends_it_on(monkeypatch):
    at_version(monkeypatch, 2)
    with natural.repeat_scope(True):
        for line in CLAIMED_AT_V1 + NEVER_CLAIMED + (ASKED_AT_V1,):
            assert natural_writes.candidate(line) is None, line
            assert natural.candidate(line) is None, line
            assert parsed(line) == {"kind": "text", "text": line}, line


@pytest.mark.parametrize("scope", ["none", False])
def test_at_version_2_with_the_interpreter_off_the_closed_forms_keep_the_seven_lines_as_at_version_1(monkeypatch, scope):
    at_version(monkeypatch, 2)
    with natural.repeat_scope(False) if scope is False else contextlib.nullcontext():      # no scope at all is the restrictive default; a scope that says off is the same
        for line in CLAIMED_AT_V1:
            assert natural_writes.candidate(line) == {"family": "calendar", "op": "event-create"}, line
            assert natural.candidate(line) == {"op": "calendar-event-create", "how": "trigger"}, line
            assert parsed(line)["kind"] == "natural" and parsed(line)["op"] == "write", line
        assert natural.candidate(ASKED_AT_V1) == {"op": "calendar-event-create", "how": "ask"} and parsed(ASKED_AT_V1)["kind"] == "natural"
        assert not natural_writes.candidate(NEVER_CLAIMED[0]) and parsed(NEVER_CLAIMED[0])["kind"] == "text"


def test_a_line_with_no_repetition_and_a_reminder_that_repeats_are_claimed_at_both_versions_with_the_scope_on_or_off(monkeypatch):
    for version in (1, 2):
        for on in (None, False, True):
            at_version(monkeypatch, version)
            with contextlib.nullcontext() if on is None else natural.repeat_scope(on):
                assert natural_writes.candidate(NO_REPEAT) == {"family": "calendar", "op": "event-create"}, (version, on)
                assert parsed(NO_REPEAT)["kind"] == "natural" and parsed(NO_REPEAT)["op"] == "write", (version, on)
                assert natural.candidate(REMINDER) == {"op": "remind", "how": "trigger"} and parsed(REMINDER)["kind"] == "natural", (version, on)


def test_the_operation_fixed_by_the_interpreter_still_reads_a_repeating_line_at_version_2(monkeypatch):
    at_version(monkeypatch, 2)
    line = CLAIMED_AT_V1[0]
    with natural.repeat_scope(True):
        got = natural_writes.read(line, None, None, op="event-create")
    assert got is not None and got["op"] == "event-create" and got["family"] == "calendar", "the seed of the interpreter's decision is read as before: only the claim of the closed form is gone"


def test_the_scope_asks_once_and_only_for_a_repeating_line_and_a_failing_question_is_off(monkeypatch):
    at_version(monkeypatch, 2)
    asked = []

    def ask():
        asked.append(1)
        return True
    with natural.repeat_scope(ask):
        assert natural.repeat_goes_on(NO_REPEAT) is False and asked == [], "a line with no repetition phrase never asks"
        assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is True and natural.repeat_goes_on(CLAIMED_AT_V1[1]) is True and asked == [1], "the answer is kept for the line"
        with natural.repeat_scope(False):
            assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is True, "a scope that is open is kept: the outermost entry decides for the whole line"
    assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is False, "the scope ended with its block"
    at_version(monkeypatch, 1)
    with natural.repeat_scope(ask):
        assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is False and asked == [1], "at version 1 nothing goes on and nothing is asked"
    at_version(monkeypatch, 2)

    def broken():
        raise RuntimeError("the configuration cannot be read")
    with natural.repeat_scope(broken):
        assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is False
    with pytest.raises(ValueError):
        with natural.repeat_scope(True):
            raise ValueError("a path that leaves the block by an error")
    assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is False, "the scope ends on every path"


def test_vacuity_without_the_rule_the_seven_lines_are_claimed_again_at_version_2_with_the_scope_on(monkeypatch):
    at_version(monkeypatch, 2)
    monkeypatch.setattr(natural, "repeat_goes_on", lambda line: False)
    with natural.repeat_scope(True):
        for line in CLAIMED_AT_V1:
            assert natural_writes.candidate(line) is not None and parsed(line)["kind"] == "natural", line
        assert natural.candidate(ASKED_AT_V1) == {"op": "calendar-event-create", "how": "ask"}
    monkeypatch.undo()
    at_version(monkeypatch, 1)
    with natural.repeat_scope(True):
        assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is False, "the rule is a rule of version 2 only"
        assert natural.repeat_goes_on(None) is False
