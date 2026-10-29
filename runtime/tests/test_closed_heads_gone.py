"""The tier-1 claimers are gone from the product (S41-11 PR 2a); the stand-ins that put them back live in tests alone (runtime/tests/closed_heads.py cites this file).

No fixture of closed_heads.py is imported here, so every assertion reads the product as it is: the write families read a line with no operation fixed as nothing, `natural_writes.candidate` is gone,
`natural.decision` knows the decisions said in words and no read, notice, act or brake, a plain line of words is a `text` for the bridge (the interpreter reads it), and the table of the bridge has no row of a
retired claimer. Each guard has a vacuity case that fails on a planted claimer. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_closed_heads_gone.py
"""
from __future__ import annotations

import datetime

import closed_heads      # the module only: its fixtures are not imported here, so every assertion above the vacuity case reads the product as it is
import standin_tree as st

natural = st.load("natural")
ops_natural = st.load("ops_natural")
natural_writes = st.load("natural_writes")
inbound = st.load("messaging_inbound")
messaging_turn = st.load("messaging_turn")
turn_order = st.load("turn_order")

NOW = datetime.datetime(2026, 10, 18, 14, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
LINES = ("marca dentista quinta às 10h", "arquiva o email 3", "add to my calendar dentist thursday at 10am", "salva esse pdf no drive")      # validate: allow english-only -- Portuguese lines under test


def test_the_write_families_read_a_line_with_no_operation_as_nothing_and_have_no_candidate():
    for line in LINES:
        assert natural_writes.read(line, NOW) is None, line
    assert not hasattr(natural_writes, "candidate"), "the claim of a write by its head is gone"


def test_natural_decision_knows_the_decisions_said_in_words_and_no_read_notice_act_or_brake():
    assert natural.decision("approve 3") is not None and natural.decision("reject 3") is not None
    for line in ("what files do you have?", "stop task 5", "cancel request 3", "list my reminders", "retry task 5"):
        assert natural.decision(line) is None, line
    assert ops_natural.line_group("show me the status please") is None and ops_natural.line_group("approve 3") == "pending" and ops_natural.line_group("stop task 5") is None and ops_natural.line_group("what files do you have?") is None
    assert not hasattr(natural, "needs") and not hasattr(natural, "claim"), "the group a plain line needs is `ops_natural.line_group`, and no site claims a line by the reminders' reading"


def test_a_plain_line_of_words_is_a_text_for_the_bridge_and_only_a_typed_remind_is_natural():
    for line in ("remind me at 15:00", "me lembra de ligar amanhã 9h", *LINES):      # validate: allow english-only -- Portuguese lines under test
        assert inbound.parse({"text": line})["kind"] == "text", line
    assert inbound.parse({"text": "/remind 15:00"}) == {"kind": "natural", "op": "remind", "how": "command", "text": "15:00"}


def test_the_table_of_the_bridge_has_no_row_of_a_retired_claimer():
    retired = {row["name"] for row in turn_order.RETIRED}
    names = {row["name"] for row in turn_order.ORDER}
    assert {"write-form", "write-form-ops", "say-natural"} <= retired and not retired & names
    assert not {"write-form", "say-natural"} & set(messaging_turn.ROWS)


def test_vacuity_the_old_reader_run_on_the_same_lines_is_seen_by_the_same_assertions(monkeypatch):
    """The twin (the review of 2026-10-29, round 2): the old reader of `closed_heads.py` is run on the very lines of `LINES`, and it reads every one of them where the product reads none; with it
    installed the assertions of the first and second tests fail on those lines."""
    read, candidate = closed_heads.make(natural_writes.read)
    for line in LINES:
        assert read(line, NOW) is not None, f"the old reader reads {line!r}"
        assert natural_writes.read(line, NOW) is None, f"and the product reads it as nothing: {line!r}"
    monkeypatch.setattr(natural_writes, "read", read)
    monkeypatch.setattr(natural_writes, "candidate", candidate, raising=False)
    assert all(natural_writes.read(line, NOW) is not None for line in LINES) and hasattr(natural_writes, "candidate"), "the first test would fail"
    monkeypatch.setattr(natural, "decision", natural.match)
    assert natural.decision("stop task 5") is not None, "the second would fail"
    monkeypatch.setattr(ops_natural, "line_group", closed_heads._old_needs)
    assert ops_natural.line_group("what files do you have?") == "sources", "and its group assertion (a read of its own)"
