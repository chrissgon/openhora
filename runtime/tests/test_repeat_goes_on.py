"""A line that holds a repetition phrase goes on to the interpreter since catalog version 2 (package CB-9, round 2).

The measurement of 2026-10-28 found that the closed forms claimed seven of the seventeen repeating lines of its sets before the interpreter: `natural_writes.candidate` took the commonest pt-BR
phrasings ("marca ... toda segunda as 7h", "poe na agenda ... todo dia") and `ops_natural_writes.advance` answered NW_RECURRING_EVENT, "an event that repeats is not available yet", and the reminders'
calendar intent (`natural.candidate`, "agenda ... todo dia as 18h") asked "an event, or something else?". At version 2 the interpreter reads the slot `repeat` (CB-7: a daily or weekly series, or the
honest sentence), so none of those closed forms may take the line first: `natural.repeat_goes_on` is what both ask. At version 1 nothing changes.

What is checked, with this test's own literals: for each of the ten repeating lines (the seven the closed forms claimed at version 1 and three that they never did) neither `natural_writes.candidate`
nor `natural.candidate` nor the bridge's `messaging_inbound.parse` claims the line at version 2 (the bridge says `text`: the line goes to `say` and its interpreter), and at version 1 the seven are claimed as
they were; a line with a time and no repetition and a reminder that repeats are claimed at both versions; the fixed operation (`op="event-create"`, what the interpreter's seed uses) still reads a repeating
line at version 2; and a vacuity case that fails on a planted wrong result (the rule turned off gives the seven back at version 2). Offline; invented lines.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_repeat_goes_on.py
"""
from __future__ import annotations

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


def test_at_version_2_no_closed_form_claims_a_repeating_line_and_the_bridge_sends_it_on(monkeypatch):
    at_version(monkeypatch, 2)
    for line in CLAIMED_AT_V1 + NEVER_CLAIMED + (ASKED_AT_V1,):
        assert natural_writes.candidate(line) is None, line
        assert natural.candidate(line) is None, line
        assert parsed(line) == {"kind": "text", "text": line}, line


def test_a_line_with_no_repetition_and_a_reminder_that_repeats_are_claimed_at_both_versions(monkeypatch):
    for version in (1, 2):
        at_version(monkeypatch, version)
        assert natural_writes.candidate(NO_REPEAT) == {"family": "calendar", "op": "event-create"}, version
        assert parsed(NO_REPEAT)["kind"] == "natural" and parsed(NO_REPEAT)["op"] == "write", version
        assert natural.candidate(REMINDER) == {"op": "remind", "how": "trigger"} and parsed(REMINDER)["kind"] == "natural", version


def test_the_operation_fixed_by_the_interpreter_still_reads_a_repeating_line_at_version_2(monkeypatch):
    at_version(monkeypatch, 2)
    line = CLAIMED_AT_V1[0]
    got = natural_writes.read(line, None, None, op="event-create")
    assert got is not None and got["op"] == "event-create" and got["family"] == "calendar", "the seed of the interpreter's decision is read as before: only the claim of the closed form is gone"


def test_vacuity_without_the_rule_the_seven_lines_are_claimed_again_at_version_2(monkeypatch):
    at_version(monkeypatch, 2)
    monkeypatch.setattr(natural, "repeat_goes_on", lambda line: False)
    for line in CLAIMED_AT_V1:
        assert natural_writes.candidate(line) is not None and parsed(line)["kind"] == "natural", line
    assert natural.candidate(ASKED_AT_V1) == {"op": "calendar-event-create", "how": "ask"}
    monkeypatch.undo()
    at_version(monkeypatch, 1)
    assert natural.repeat_goes_on(CLAIMED_AT_V1[0]) is False, "the rule is a rule of version 2 only"
    assert natural.repeat_goes_on(None) is False
