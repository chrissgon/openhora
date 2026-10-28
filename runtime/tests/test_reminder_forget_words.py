"""A reminder forgotten by the words of the person's line, through the operations layer (package CB-8 REMIND-WORDS, runtime/reminders.py and runtime/ops_natural.py, catalog version 2).

The tier-1 form "cancela o lembrete da florista" finds the reminder by words (runtime/messaging_remind.py `forget_words`); when S41-11 deletes the forms, scenario 23 must still work, so the row
`reminder-forget` gains a v2 slot `target` (param `matching`) and the operations layer finds the reminder with the SAME rule (`reminders.matching`): one match is shown and cancelled only on the
person's yes (the question a reminder named by its number gets), several are a numbered list that asks which, none is one sentence. A line reaches the slot only after the flip (`LINE_CATALOG` is 1).
Here the real operations and store (test_reminders.py's world: four listed senders, a clock), the real dispatcher, and the interpreter's own `check` over the catalog of version 2. Every expectation
is a literal of this file or the question the same reminder gets by its number (the control); sentences are asserted by phrase key (T8). Each oracle that matches has a vacuity case. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_reminder_forget_words.py
"""
from __future__ import annotations

import pytest

import interpreter_kit as kit
import standin_tree as st
from natural_kit import said_yes
from test_attachments import IDENT, OTHER, accept, case  # noqa: F401  (the project the reminders' tests build on)
from test_reminders import PROFILES, SENDER, world  # noqa: F401  (the world fixture: a project with four listed senders and a clock)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
ops_turn = st.load("ops_turn")
phrases = st.load("phrases")
natural = st.load("natural")
reminders = st.load("reminders")
interpreter = st.load("interpreter")
interpreter_catalog = st.load("interpreter_catalog")

OTHER_SENDER = f"telegram:{OTHER}"


def make(world):
    """Three reminders of SENDER (1: the florist, 2: the florist's invoice, 3: the dentist) and one of the other sender (4: the florist), in that order."""
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 1 pm to pay the florist")
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 2 pm to review the florist invoice")
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 3 pm to call the dentist")
    said_yes(ops, world.path, OTHER_SENDER, "remind me tomorrow at 4 pm to pay the florist")
    assert {r["id"]: r["text"] for r in world.rows()} == {1: "pay the florist", 2: "review the florist invoice", 3: "call the dentist", 4: "pay the florist"}


def forget(world, args, sender=SENDER, extras=None):
    """The reply of the dispatcher for a reminder to forget named by `args`, as a decision of the interpreter or the router reaches it (routed)."""
    ctx = ops_core.context(world.path)
    return ops_natural.run(world.path, ctx, "reminder-forget", dict(args), "cancel the reminder", "messaging", sender, extras if extras is not None else {}, routed=True)


def statuses(world):
    return {r["id"]: r["status"] for r in world.rows()}


# --- the rule, pure ---------------------------------------------------------------------------------------------------------------------------------


def test_the_words_of_a_span_are_its_folded_words_without_the_joining_words_and_the_noun():
    assert reminders.forget_words("the florist") == ["florist"]
    assert reminders.forget_words("the reminder about the florist") == ["florist"]
    assert reminders.forget_words("o lembrete da florista") == ["florista"]
    assert reminders.forget_words("da Clínica Sorriso") == ["clinica", "sorriso"]      # validate: allow english-only -- an invented name with an accent
    assert reminders.forget_words("of the") == [] and reminders.forget_words("") == []
    assert reminders.forget_words("a b c d e f") == [], "more than FORGET_WORDS_MAX words is a sentence, not a name"


def test_a_reminder_matches_when_its_whole_words_hold_every_key_and_a_prefix_is_not_a_word():
    rows = [{"id": 1, "text": "pay the florist"}, {"id": 2, "text": "call 9h"}, {"id": 3, "text": "Dentist, 9 o'clock"}]
    assert [r["id"] for r in reminders.matching(rows, ["florist"])] == [1]
    assert [r["id"] for r in reminders.matching(rows, ["flor"])] == [], "a prefix is not a word"
    assert [r["id"] for r in reminders.matching(rows, ["9"])] == [3], "9 is not 9h"
    assert [r["id"] for r in reminders.matching(rows, ["dentist", "9"])] == [3] and reminders.matching(rows, ["pay", "dentist"]) == []
    assert reminders.matching(rows, []) == [] and reminders.holds("anything", []) is True


def test_vacuity_a_matcher_that_looks_inside_words_is_seen_by_the_oracle(monkeypatch):
    rows = [{"id": 1, "text": "pay the florist"}]
    monkeypatch.setattr(reminders, "holds", lambda text, keys: all(k in str(text).lower() for k in keys))
    assert [r["id"] for r in reminders.matching(rows, ["flor"])] == [1] != []


# --- the operations layer ---------------------------------------------------------------------------------------------------------------------------


def test_one_match_is_shown_with_the_question_its_number_gets_and_nothing_is_cancelled(world):  # noqa: F811
    make(world)
    by_number = forget(world, {"reminder_id": 3})
    extras = {}
    reply = forget(world, {"matching": "the dentist"}, extras=extras)
    assert reply == by_number and "#3" in reply, "the same question as the reminder named by its number"
    assert statuses(world) == {1: "open", 2: "open", 3: "open", 4: "open"}
    assert extras["stored"] == phrases.text("NAT_PRIVATE_REPLY", None), "the conversation keeps a neutral word, never the reminder's words (L51)"


def test_the_yes_cancels_exactly_that_reminder(world):  # noqa: F811
    make(world)
    forget(world, {"matching": "the dentist"})
    ctx = ops_core.context(world.path)
    done = ops_turn.dispatch_rows(ops_turn.TAKE_ROWS, world.path, ctx, "yes", "messaging", None, SENDER, {})[0]
    assert done and statuses(world) == {1: "open", 2: "open", 3: "cancelled", 4: "open"}


def test_several_matches_are_a_numbered_list_that_asks_which_and_nothing_is_cancelled(world):  # noqa: F811
    make(world)
    reply = forget(world, {"matching": "the florist"})
    lines = reply.splitlines()
    assert lines[0] == phrases.text("RM_FORGET_WORDS_WHICH", None)
    assert [line.split(" ")[0] for line in lines[1:]] == ["#1", "#2"], "the sender's own two, by their numbers; the other sender's reminder 4 is not there"
    assert "pay the florist" in lines[1] and "review the florist invoice" in lines[2]
    assert statuses(world) == {1: "open", 2: "open", 3: "open", 4: "open"}


def test_none_is_one_sentence_and_a_prefix_or_a_number_that_is_in_no_word_finds_nothing(world):  # noqa: F811
    make(world)
    none = phrases.text("RM_FORGET_WORDS_NONE", None)
    assert forget(world, {"matching": "the plumber"}) == none
    assert forget(world, {"matching": "the flor"}) == none, "a prefix is not a word"
    assert forget(world, {"matching": "of the"}) == none, "a span with no word to look for finds nothing"
    assert statuses(world) == {1: "open", 2: "open", 3: "open", 4: "open"}


def test_another_senders_reminder_never_matches_and_is_never_shown(world):  # noqa: F811
    make(world)
    said_yes(ops, world.path, OTHER_SENDER, "remind me tomorrow at 5 pm to water the ferns")
    assert forget(world, {"matching": "the ferns"}) == phrases.text("RM_FORGET_WORDS_NONE", None), "SENDER has no such reminder"
    assert "#5" in forget(world, {"matching": "the ferns"}, sender=OTHER_SENDER), "the other sender sees their own"
    assert statuses(world)[5] == "open"


def test_with_notices_as_a_count_no_word_of_a_reminder_is_in_the_reply(world):  # noqa: F811
    make(world)
    accept(world.path, policies=PROFILES, channels={"messaging": "staff"}, messaging={"senders": {"telegram": [IDENT, {"id": OTHER, "policy": "staff"}]}, "notices": "count"})
    reply = forget(world, {"matching": "the florist"})
    assert "florist" not in reply and "invoice" not in reply and [line.split(" ")[0] for line in reply.splitlines()[1:]] == ["#1", "#2"]
    one = forget(world, {"matching": "the dentist"})
    assert "dentist" not in one and "#3" in one


def test_the_bridge_path_is_unchanged_one_match_by_words_cancels_at_once_and_a_preview_only_shows(world):  # noqa: F811
    make(world)
    shown = ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["dentist"], preview=True)
    assert shown["preview"]["id"] == 3 and statuses(world)[3] == "open", "a preview never cancels"
    done = ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["dentist"])
    assert done["reminder"]["id"] == 3 and statuses(world)[3] == "cancelled", "the bridge's own words form still acts at once, as before"
    assert [r["id"] for r in ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["florist"], preview=True)["choose"]] == [1, 2]
    assert ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["plumber"], preview=True) == {"none": True}


def test_vacuity_a_forget_that_ignores_the_words_would_show_the_wrong_reminder(world, monkeypatch):  # noqa: F811
    make(world)
    monkeypatch.setattr(reminders, "forget_words", lambda span: ["dentist"])
    assert "#3" in forget(world, {"matching": "the florist"}), "the planted wrong words find the dentist: the tests above would fail on it"


# --- the line of a model, version 2 ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def v2(monkeypatch):
    """The catalog of version 2 and the views over it: what a line reaches after the flip, which CB-9 alone makes."""
    classes, table = natural.views(2)
    monkeypatch.setattr(natural, "CLASSES", classes)
    monkeypatch.setattr(natural, "NATURAL", table)
    catalog = interpreter_catalog.generate(2)
    monkeypatch.setattr(interpreter, "SERVED_SHA256", interpreter.catalog_sha256(catalog))
    return catalog


def decide(catalog, line, slots):
    obj = {"v": 1, "kind": "op", "op": "reminder-forget", "slots": slots}
    return interpreter.check(obj, line, None, catalog, kit.NOW, kit.ZONE, frozenset(("reminder-forget",)))


def test_a_line_reaches_the_slot_only_at_version_2(monkeypatch):
    line = "cancela o lembrete da florista"
    assert natural.check_operation("reminder-forget", {"target": "da florista"}, None, line)["ok"] is False, "L54: at version 1 the slot is not reachable"
    classes, table = natural.views(2)
    monkeypatch.setattr(natural, "CLASSES", classes)
    monkeypatch.setattr(natural, "NATURAL", table)
    assert natural.check_operation("reminder-forget", {"target": "da florista"}, None, line) == {"ok": True, "name": "reminder-forget", "args": {"matching": "da florista"}, "when": None}
    assert natural.check_operation("reminder-forget", {"id": "3"}, None, "forget reminder 3")["args"] == {"reminder_id": 3}, "the number slot of version 1 is untouched"


def test_the_model_names_the_florist_and_the_question_is_the_reminders(world, v2):  # noqa: F811
    make(world)
    line = "cancel the dentist reminder"
    decision = decide(v2, line, {"target": "the dentist"})
    assert decision["kind"] == "op" and decision["args"] == {"matching": "the dentist"}
    ctx = ops_core.context(world.path)
    reply = ops_natural.run(world.path, ctx, decision["op"], decision["args"], line, "messaging", SENDER, {}, routed=True)
    assert reply == forget(world, {"reminder_id": 3}), "the question of reminder 3, the dentist"
    assert statuses(world) == {1: "open", 2: "open", 3: "open", 4: "open"}


def test_vacuity_at_version_1_the_model_cannot_name_the_words():
    decision = decide(interpreter_catalog.generate(1), "cancela o lembrete da florista", {"target": "da florista"})
    assert decision["kind"] != "op", decision
