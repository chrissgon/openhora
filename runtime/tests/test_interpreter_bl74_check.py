"""The check takes a plain no of a plan and routes a draft of a note (package BL7-4, fixes B, E and C; limits L63 and L65).

Three refusals of right answers in the second blind set (2026-10-26), all in `runtime/interpreter.py`, which believes nothing the model says until it has checked it against the line:
  B  a plain no that is not a closed one ("no, leave it, I will look at it later", in Portuguese in the blind set) answers a plan item. The model said `confirm: no`; the check re-read the line with the closed lists, found no closed no and asked
     again, while the plan was dropped anyway. A plain no (the line opens with a no word, holds no digit, and the time engine reads no date, clock or relative time in it; the answer names
     no slot and no span) on a `plan-confirm` item is that no. A line that carries a new detail stays a correction or an ask-again; a model's yes is never touched (L65).
  E  the same line, answered `none` by a model, with a live plan: that no too. It can only drop the plan, which the next line drops anyway.
  C  a `mail-draft` with no recipient, target, message, day or subject, in a line with a draft verb and no mail noun and no reply verb ("draft a nice note to the neighbours about our party"),
     is open writing, not a card with no seed: `route`, before the policy check (the route asks its own policy), `private-route` for a private line.
Every line and every expectation is a literal of this file; names are invented. Vacuity: each rule's guard patched to say no makes its test fail. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_bl74_check.py
"""
from __future__ import annotations

import pytest

import interpreter_kit as kit
import standin_tree as st

interp = st.load("interpreter")

PLAIN_NO = "Nao, deixa pra la, depois eu vejo isso com calma."      # validate: allow english-only -- the Portuguese line under test
ANSWER_NO = {"v": 1, "kind": "answer", "answers_item": "i1", "confirm": "no"}
NONE = {"v": 1, "kind": "none"}
TAKEN = {"kind": "answer", "error": None, "item": "i1", "need": "confirm", "confirm": "no"}
ASKED_AGAIN = {"kind": "clarify", "error": None, "why": "model", "slot": None, "ops": None, "item": "i1"}


def run(obj, line, frame=None, allowed=None):
    return interp.check(obj, line, frame, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS if allowed is None else allowed)


def frame(kind="plan-confirm", op="pending"):
    """A frame with one live item of `kind` for `op` (the sender's last request of that operation, no words)."""
    return {"v": 1, "items": [{"id": "i1", "kind": kind, "need": "confirm", "age_s": 25, "op": op}], "last": {"op": op, "words": {}, "age_s": 25}}


# --- B: a plain no on a plan item is taken ---------------------------------------------------------------------------------------------------------------

def assert_plain_no_is_taken():
    assert run(ANSWER_NO, PLAIN_NO, frame()) == TAKEN
    assert run(ANSWER_NO, "nao, deixa pra la", frame()) == TAKEN      # validate: allow english-only -- the Portuguese line under test
    assert run(ANSWER_NO, "No, leave it, I will look at it later.", frame()) == TAKEN


def test_a_plain_no_on_a_plan_item_is_that_no():
    assert_plain_no_is_taken()


@pytest.mark.parametrize("line", ("Nao, a 3", "nao, sexta", "nao, as 9h", "nao, daqui a pouco, em 2 horas", "nao, a de amanha"))
def test_a_no_with_a_digit_or_a_time_phrase_goes_on_as_before(line):
    assert run(ANSWER_NO, line, frame()) == ASKED_AGAIN


def test_a_slot_or_a_span_in_the_answer_goes_on_as_before():
    assert run(dict(ANSWER_NO, slot="day", span="deixa pra la"), PLAIN_NO, frame()) == ASKED_AGAIN      # validate: allow english-only -- the Portuguese line under test
    assert run(dict(ANSWER_NO, span="deixa pra la"), PLAIN_NO, frame()) == {"kind": "clarify", "error": "E_SHAPE", "why": "invalid", "slot": None, "ops": None}      # validate: allow english-only -- the Portuguese line under test


def test_a_line_that_does_not_open_with_a_no_goes_on_as_before():
    assert run(ANSWER_NO, "deixa pra la, depois eu vejo", frame()) == ASKED_AGAIN      # validate: allow english-only -- the Portuguese line under test


def test_an_item_that_is_not_a_plan_goes_on_as_before():
    assert run(ANSWER_NO, PLAIN_NO, frame("reminder-confirm", "remind")) == ASKED_AGAIN
    assert run(ANSWER_NO, PLAIN_NO, frame("write-draft", "mail-send")) == ASKED_AGAIN


def test_a_models_yes_is_never_taken_from_a_line_that_is_not_a_closed_yes():
    assert run(dict(ANSWER_NO, confirm="yes"), PLAIN_NO, frame()) == ASKED_AGAIN
    assert run(dict(ANSWER_NO, confirm="yes"), "Nao, deixa pra la", frame()) == ASKED_AGAIN      # validate: allow english-only -- the Portuguese line under test


def test_a_closed_no_is_still_a_no():
    assert run(ANSWER_NO, "nao", frame()) == TAKEN


def test_nothing_but_the_answer_decision_comes_out_of_the_rule():
    got = run(ANSWER_NO, PLAIN_NO, frame())
    assert set(got) == {"kind", "error", "item", "need", "confirm"} and got["kind"] == "answer" and got["confirm"] == "no"


NOT_A_PLAIN_NO = (      # a line that opens with a no word and says more than a no: a new request, or words that are not a no at all
    "No, email Ana about the invoice instead",
    "N\u00e3o, mas me lembra de ligar pro Jonas",      # validate: allow english-only -- the Portuguese line under test
    "N\u00e3o esquece de mandar o relat\u00f3rio",      # validate: allow english-only -- the Portuguese line under test
    "nope, cancel the dentist instead",
    "no problem, go ahead",
    "no worries, go ahead",
    "N\u00e3o tem problema",      # validate: allow english-only -- the Portuguese line under test
    "sem problema",      # validate: allow english-only -- the Portuguese line under test
    "don't forget the invoice",
)


@pytest.mark.parametrize("line", NOT_A_PLAIN_NO)
def test_a_no_that_says_more_than_a_no_or_is_not_a_no_never_drops_the_plan(line):
    for obj in (ANSWER_NO, dict(ANSWER_NO, confirm="yes")):
        got = run(obj, line, frame())
        assert got != TAKEN and not (got["kind"] == "answer" and got.get("confirm") == "no"), (line, got)
    assert run(NONE, line, frame()) == {"kind": "none", "error": None}, line


def test_the_filler_a_plain_no_may_hold_is_closed():
    for line in ("no", "N\u00e3o, obrigado, deixa pra l\u00e1 ent\u00e3o", "nao, valeu", "no, thanks", "No, leave it, I will look at it later.", "N\u00e3o, deixa pra l\u00e1, eu vejo isso depois com calma."):      # validate: allow english-only -- the Portuguese line under test
        assert interp._plain_no(line), line
    for line in NOT_A_PLAIN_NO:
        assert not interp._plain_no(line), line


def test_vacuity_a_filler_list_that_accepts_every_word_takes_a_request_for_a_no(monkeypatch):
    class Everything:
        def __contains__(self, word):
            return True
    monkeypatch.setattr(interp, "PLAIN_NO_FILLER", Everything())
    assert run(ANSWER_NO, "nope, cancel the dentist instead", frame()) == TAKEN          # what the closed list prevents
    with pytest.raises(AssertionError):
        test_a_no_that_says_more_than_a_no_or_is_not_a_no_never_drops_the_plan("nope, cancel the dentist instead")


def test_vacuity_an_empty_filler_list_takes_nothing_for_a_plain_no(monkeypatch):
    monkeypatch.setattr(interp, "PLAIN_NO_FILLER", frozenset())
    with pytest.raises(AssertionError):
        assert_plain_no_is_taken()


# --- E: a model's `none` on that no, with a live plan ----------------------------------------------------------------------------------------------------

def assert_none_is_the_no():
    assert run(NONE, PLAIN_NO, frame()) == TAKEN


def test_a_none_on_a_plain_no_with_a_live_plan_is_that_no():
    assert_none_is_the_no()


def test_a_none_with_no_plan_or_not_a_plain_no_stays_none():
    none = {"kind": "none", "error": None}
    assert run(NONE, PLAIN_NO, None) == none
    assert run(NONE, "obrigado", frame()) == none
    for line in ("nao, a 3", "nao, sexta", "nao, as 9h", "deixa pra la, depois eu vejo"):      # validate: allow english-only -- the Portuguese line under test
        assert run(NONE, line, frame()) == none, line
    assert run(NONE, PLAIN_NO, frame("reminder-confirm", "remind")) == none


# --- C: a draft of a note is open writing ------------------------------------------------------------------------------------------------------------------

NOTE = "draft a nice note to the neighbours about our party on saturday"
ROUTE = {"kind": "route", "error": None}


def draft(slots, **more):
    return {"v": 1, "kind": "op", "op": "mail-draft", "slots": slots, **more}


def assert_note_is_routed():
    assert run(draft({"body": NOTE}), NOTE) == ROUTE
    assert run(draft({"body": "a short thank-you note to the neighbours"}), "draft a short thank-you note to the neighbours") == ROUTE
    assert run(draft({}), NOTE) == ROUTE


def test_a_draft_of_a_note_with_nothing_to_send_to_is_open_writing():
    assert_note_is_routed()


def test_a_draft_that_names_a_mail_noun_a_recipient_a_message_or_a_subject_keeps_its_path():
    for obj, line in ((draft({"body": "to the neighbours"}), "draft an email to the neighbours about our party"),
                      (draft({"body": "about our party", "to": "ana@home.example"}), "draft a note to ana@home.example about our party"),
                      (draft({"body": "about our party", "target": "the neighbours"}), "draft a note to the neighbours about our party"),
                      (draft({"body": "about our party", "subject": "our party"}), "draft a note about our party"),
                      (draft({"body": "about our party", "message": 3}), "draft a note for message 3 about our party"),
                      (draft({"body": "I agree"}), "draft a reply saying I agree"),
                      (draft({"body": "about our party"}, inherit={"to": "ana@home.example"}), "draft a note about our party")):
        got = run(obj, line)
        assert got["kind"] != "route", (line, got)


def test_the_unrouted_lines_are_the_ops_they_were():
    got = run(draft({"body": "to the neighbours"}), "draft an email to the neighbours about our party")
    assert got["kind"] == "op" and got["op"] == "mail-draft" and got["spans"] == {"body": "to the neighbours"}


def test_a_draft_object_with_a_slot_the_catalog_row_lacks_is_still_invalid_not_routed():
    got = run(draft({"body": NOTE, "colour": "red"}), NOTE)
    assert got["kind"] == "clarify" and got["why"] == "invalid" and got["error"] == "E_SLOT_UNKNOWN", got


def test_another_operation_with_the_same_line_is_not_routed():
    got = run({"v": 1, "kind": "op", "op": "mail-send", "slots": {"body": NOTE}}, NOTE)
    assert got["kind"] != "route", got


def test_a_private_line_is_asked_instead_of_routed(monkeypatch):
    monkeypatch.setattr(interp.turn_gate, "private_line", lambda line: True)
    got = run(draft({"body": NOTE}), NOTE)
    assert got["kind"] == "clarify" and got["why"] == "private-route", got


def test_a_sender_without_the_draft_permission_is_routed_not_refused():
    allowed = frozenset(kit.ALL_OPS) - {"mail-draft"}
    assert run(draft({"body": NOTE}), NOTE, allowed=allowed) == ROUTE
    got = run(draft({"body": "to the neighbours"}), "draft an email to the neighbours about our party", allowed=allowed)
    assert got == {"kind": "refuse_policy", "error": None, "op": "mail-draft"}          # a line that names a mail noun keeps today's path


# --- vacuity: each guard made to say no ------------------------------------------------------------------------------------------------------------------

def test_vacuity_the_plain_no_guard_is_what_moves_b_and_e(monkeypatch):
    monkeypatch.setattr(interp, "_plain_no", lambda line: False)
    with pytest.raises(AssertionError):
        assert_plain_no_is_taken()
    with pytest.raises(AssertionError):
        assert_none_is_the_no()


def test_vacuity_the_open_note_guard_is_what_moves_c(monkeypatch):
    monkeypatch.setattr(interp, "_open_note", lambda name, obj, line, ops: False)
    with pytest.raises(AssertionError):
        assert_note_is_routed()


def test_vacuity_a_plain_no_that_is_always_true_would_take_a_correction(monkeypatch):
    monkeypatch.setattr(interp, "_plain_no", lambda line: True)
    assert run(ANSWER_NO, "nao, a 3", frame()) == TAKEN          # the oracle above (`ASKED_AGAIN` for a digit) is what a wrong guard breaks
    with pytest.raises(AssertionError):
        assert run(ANSWER_NO, "nao, a 3", frame()) == ASKED_AGAIN
