"""A line that holds a repetition phrase goes on to the interpreter since catalog version 2 (package CB-9, round 2).

The measurement of 2026-10-28 found that the closed forms claimed seven of the seventeen repeating lines of its sets before the interpreter: `natural_writes.candidate` took the commonest pt-BR
phrasings ("marca ... toda segunda as 7h", "poe na agenda ... todo dia") and `ops_natural_writes.advance` answered NW_RECURRING_EVENT, "an event that repeats is not available yet", and the reminders'
calendar intent (`natural.candidate`, "agenda ... todo dia as 18h") asked "an event, or something else?". At version 2 the interpreter reads the slot `repeat` (CB-7: a daily or weekly series, or the
honest sentence), so none of those closed forms may take the line first: `natural.repeat_goes_on` is what both ask. At version 1 nothing changes.

The gate is limited to a line of a sender whom the interpreter reads (the maintainer, 2026-10-28): `natural.repeat_scope(on)` is open only when the interpreter is ON for that sender and language,
and outside a scope nothing goes on, so with the interpreter off (or in any entry that opens no scope) a repeating line keeps the closed form's honest "not available yet" answer, as before, and never
goes to the router. This is the restrictive default.

What is checked, with this test's own literals: for each of the ten repeating lines (the seven the closed forms claimed at version 1 and three that they never did) neither `natural_writes.candidate`
nor `natural.claim` nor the bridge's `messaging_inbound.parse` claims the line at version 2 with the scope on (the bridge says `text`: the line goes to `say` and its interpreter), and at version 1
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
ops_natural = st.load("ops_natural")
ops_natural_writes = st.load("ops_natural_writes")

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
        assert natural.claim(line) == {"op": "calendar-event-create", "how": "trigger"}, line
        assert parsed(line)["kind"] == "natural" and parsed(line)["op"] == "write", line
    assert natural.claim(ASKED_AT_V1) == {"op": "calendar-event-create", "how": "ask"} and parsed(ASKED_AT_V1)["kind"] == "natural"
    assert not natural_writes.candidate(NEVER_CLAIMED[0]) and parsed(NEVER_CLAIMED[0])["kind"] == "text"


def test_at_version_2_with_the_scope_on_no_closed_form_claims_a_repeating_line_and_the_bridge_sends_it_on(monkeypatch):
    at_version(monkeypatch, 2)
    with natural.repeat_scope(True):
        for line in CLAIMED_AT_V1 + NEVER_CLAIMED + (ASKED_AT_V1,):
            assert natural_writes.candidate(line) is None, line
            assert natural.claim(line) is None, line
            assert parsed(line) == {"kind": "text", "text": line}, line


@pytest.mark.parametrize("scope", ["none", False])
def test_at_version_2_with_the_interpreter_off_the_closed_forms_keep_the_seven_lines_as_at_version_1(monkeypatch, scope):
    at_version(monkeypatch, 2)
    with natural.repeat_scope(False) if scope is False else contextlib.nullcontext():      # no scope at all is the restrictive default; a scope that says off is the same
        for line in CLAIMED_AT_V1:
            assert natural_writes.candidate(line) == {"family": "calendar", "op": "event-create"}, line
            assert natural.claim(line) == {"op": "calendar-event-create", "how": "trigger"}, line
            assert parsed(line)["kind"] == "natural" and parsed(line)["op"] == "write", line
        assert natural.claim(ASKED_AT_V1) == {"op": "calendar-event-create", "how": "ask"} and parsed(ASKED_AT_V1)["kind"] == "natural"
        assert not natural_writes.candidate(NEVER_CLAIMED[0]) and parsed(NEVER_CLAIMED[0])["kind"] == "text"


def test_a_line_with_no_repetition_and_a_reminder_that_repeats_are_claimed_at_both_versions_with_the_scope_on_or_off(monkeypatch):
    for version in (1, 2):
        for on in (None, False, True):
            at_version(monkeypatch, version)
            with contextlib.nullcontext() if on is None else natural.repeat_scope(on):
                assert natural_writes.candidate(NO_REPEAT) == {"family": "calendar", "op": "event-create"}, (version, on)
                assert parsed(NO_REPEAT)["kind"] == "natural" and parsed(NO_REPEAT)["op"] == "write", (version, on)
                assert natural.claim(REMINDER) == {"op": "remind", "how": "trigger"} and parsed(REMINDER)["kind"] == "natural", (version, on)


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
        assert natural.claim(ASKED_AT_V1) == {"op": "calendar-event-create", "how": "ask"}
    monkeypatch.undo()
    at_version(monkeypatch, 1)
    with natural.repeat_scope(True):
        assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is False, "the rule is a rule of version 2 only"
        assert natural.repeat_goes_on(None) is False


# --- the gate is at the claim sites only: a recogniser reads the line as it always did ----------------------------------------------------------


def draft_state(need="subject"):
    """The state of an open mail draft that asks for its `need` (the shape `ops_natural_writes._classify` reads), for the project key of a context with the project name "p"."""
    return {"project": ops_natural.project_key("p"), "need": need, "family": "mail", "op": "mail-send", "slots": {"to": "bia@exemplo.example", "body": "ok"}, "options": None}


def classify(line):
    return ops_natural_writes._classify({"cfg": {"project": "p"}}, draft_state(), line)


def test_a_repeating_line_is_a_new_request_for_an_open_mail_draft_that_asks_its_subject_with_the_scope_on_off_or_none(monkeypatch):
    at_version(monkeypatch, 2)
    for scope in (None, False, True):
        with contextlib.nullcontext() if scope is None else natural.repeat_scope(scope):
            assert classify(CLAIMED_AT_V1[0]) is None, scope      # a new line, never the subject of the e-mail
            assert classify("assunto da reunião de pais")["kind"] == "slots", scope      # validate: allow english-only -- the Portuguese line under test: a line that is no request is the subject


def test_the_recognisers_read_a_repeating_line_whatever_the_scope(monkeypatch):
    at_version(monkeypatch, 2)
    ctx = {"cfg": {"project": "p"}}
    for on in (False, True):
        with natural.repeat_scope(on):
            for line in CLAIMED_AT_V1:
                assert natural.candidate(line) == {"op": "calendar-event-create", "how": "trigger"}, (on, line)
                assert natural_writes.candidate(line, claim=False) == {"family": "calendar", "op": "event-create"}, (on, line)
                assert ops_natural.recognises(ctx, line, "messaging", "telegram:1") is True, (on, line)
            assert natural.private(CLAIMED_AT_V1[0]) is True, "a repeating line stays a private line"
    with natural.repeat_scope(True):
        assert natural_writes.candidate(CLAIMED_AT_V1[0]) is None and ops_natural.peek(ctx, CLAIMED_AT_V1[0], "messaging", "telegram:1") is False, "the claim sites are the ones that let it go on"


def test_vacuity_a_recogniser_that_reads_through_the_scope_takes_the_line_for_the_subject(monkeypatch):
    at_version(monkeypatch, 2)
    real = natural_writes.candidate
    monkeypatch.setattr(ops_natural_writes.nw, "candidate", lambda line, languages=None, claim=True: real(line, languages))      # the planted fault: the recogniser reads through the scope
    plain = natural.candidate

    def through_the_scope(line, languages=None):
        got = plain(line, languages)
        return None if got is not None and got["op"] == "calendar-event-create" and natural.repeat_goes_on(line) else got
    monkeypatch.setattr(ops_natural_writes.natural, "candidate", through_the_scope)
    with natural.repeat_scope(True):
        assert classify(CLAIMED_AT_V1[0]) is not None, "the oracle above (a new line) fails on the planted fault"
