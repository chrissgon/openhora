"""LP-1: the options of a write question answered by an ordinal word, the word for last, the sender's words or a brand (runtime/ops_natural_writes.py `_option`, `_option_pick`; runtime/list_pick.py).

The question is the real one: the mail family finds three e-mails for "responde o e-mail de orcamento" in a real snapshot of the stand-in mailbox (the desk of test_send_own_account.py, the
reading of test_blite_mail_target.py), keeps the options in the draft and asks which one; the answer is read by `_classify`, and one answer is carried through `answer` to the card. The
account question and the multiple choice are asked with hand-made states, because their options are the family's own. Every address and name is invented; every expectation is a literal of
this file; each rule has a vacuity test that plants the wrong result. Offline; no model is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_write_option_pick.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_blite_mail_target import desk_with, open_card, pending
from test_send_own_account import world  # noqa: F401  (the mail desk, the stand-in mailers and the accepted configuration)

onw = st.load("ops_natural_writes")
ops_core = st.load("ops_core")
phrases = st.load("phrases")

CLINICA, BANCO, ANA = "contato@clinica-sorriso.example", "avisos@banco-aurora.example", "ana.lima@estudio-norte.example"
SPANS = {"target": "orçamento", "body": "assino amanhã"}      # validate: allow english-only -- the Portuguese words under test
SAID = "responde o e-mail de orçamento dizendo que assino amanhã"      # validate: allow english-only -- the Portuguese line under test


def mailbox(world):
    desk_with(world, [
        tsm.message(1, "2026-10-17T09:00:00Z", sender=f"Clinica Sorriso <{CLINICA}>", subject="Orçamento da limpeza", id="o1", thread_id="t1", headers={"Message-ID": "<o1@exemplo.example>"}),      # validate: allow english-only -- an invented Portuguese subject
        tsm.message(2, "2026-10-16T14:30:00Z", sender=f"Banco Aurora <{BANCO}>", subject="Orçamento do seguro", id="o2", thread_id="t2", headers={"Message-ID": "<o2@exemplo.example>"}),      # validate: allow english-only -- an invented Portuguese subject
        tsm.message(3, "2026-10-15T08:00:00Z", sender=f"Ana Lima <{ANA}>", subject="Orçamento da reforma", id="o3", thread_id="t3", headers={"Message-ID": "<o3@exemplo.example>"}),      # validate: allow english-only -- an invented Portuguese subject
    ])


def asked(world, monkeypatch):
    """The question the family asks: three e-mails fit, which one. Returns (the draft, the ctx, the calls the family made so far, the spies)."""
    mailbox(world)
    reply, extras, called, started = open_card(world, monkeypatch, "mail-reply", SPANS, SAID)
    draft = onw.live("chat", None)
    assert draft is not None and draft["need"] == "message" and not draft["multi"], reply
    assert [o["value"] for o in draft["options"]] == ["inbox#1", "inbox#2", "inbox#3"]
    return draft, ops_core.context(world["path"]), called, started


def picked(ctx, draft, said):
    """The slot a reply fills, or None when it fills none (the question is asked once more, or given up)."""
    found = onw._classify(ctx, draft, said)
    return found["slots"]["chosen"] if found is not None and found["kind"] == "slots" else None


PICKS = [("o primeiro", "inbox#1"), ("a primeira", "inbox#1"), ("o segundo", "inbox#2"), ("a última", "inbox#3"), ("o último", "inbox#3"), ("the last one", "inbox#3"), ("the first", "inbox#1"),      # validate: allow english-only -- the Portuguese lines under test
         ("o do banco", "inbox#2"), ("a do banco", "inbox#2"), ("o da ana", "inbox#3"), ("o da clinica", "inbox#1"), ("a da clínica", "inbox#1"), ("the one from ana", "inbox#3"),      # validate: allow english-only -- the Portuguese lines under test
         ("o do aurora", "inbox#2"), ("a do estudio", "inbox#3"), ("2", "inbox#2")]
NOT_PICKS = ["o do example", "o do outlook", "a das 15h", "os dois primeiros", "o quarto", "o décimo", "a do banco aurora clinica", "o do orçamento", "cancela a última", "o do"]      # validate: allow english-only -- the Portuguese lines under test


def wrong_picks(ctx, draft):
    return [(line, got) for line, wanted in PICKS if (got := picked(ctx, draft, line)) != wanted]


def test_an_ordinal_the_word_for_last_and_the_words_of_a_sender_pick_the_option_of_the_question(world, monkeypatch):
    draft, ctx, _, _ = asked(world, monkeypatch)
    assert wrong_picks(ctx, draft) == []


@pytest.mark.parametrize("line", NOT_PICKS)
def test_a_reply_that_names_no_option_or_several_is_no_pick_and_the_question_is_asked_again(world, monkeypatch, line):
    draft, ctx, _, _ = asked(world, monkeypatch)
    assert picked(ctx, draft, line) is None, line
    assert onw._classify(ctx, draft, line) in ({"kind": "retry"}, None), "a short reply that fits nothing is asked once more; a line that is a request of its own is a new line"


def test_the_pick_is_carried_through_the_answer_to_the_card_of_the_message_it_names(world, monkeypatch):
    draft, ctx, called, _ = asked(world, monkeypatch)
    extras = {}
    reply = onw.answer(world["path"], ctx, draft, "o do banco", "chat", None, extras)
    assert reply is not None and extras.get("resend"), reply
    assert [(name, args["message"]) for name, args in called] == [("mail-reply", "inbox#2")], "the message of the bank, by the words of its address"
    assert f"Reply to: {BANCO}" in " ".join(pending(world, extras["resend"])["body"].splitlines()[:4]), pending(world, extras["resend"])["body"]


def test_the_pick_yields_the_value_of_the_option_and_changes_no_other_slot(world, monkeypatch):
    draft, ctx, _, _ = asked(world, monkeypatch)
    assert onw._classify(ctx, draft, "a última") == {"kind": "slots", "slots": {"chosen": "inbox#3"}, "origin": "picked"}


def test_a_multiple_choice_is_answered_by_numbers_alone_and_a_pick_changes_nothing_there():
    options = [{"value": f"inbox#{i}", "label": f"{a} · Orçamento"} for i, a in enumerate([CLINICA, BANCO, ANA], 1)]      # validate: allow english-only -- an invented Portuguese subject
    state = {"need": "message", "options": options, "multi": True}
    assert onw._option(state, "1, 3") == ["inbox#1", "inbox#3"] and onw._option(state, "2") == ["inbox#2"]
    for line in ("os dois primeiros", "a última", "o do banco", "o primeiro"):      # validate: allow english-only -- the Portuguese lines under test
        assert onw._option(state, line) is None, line


def test_the_account_and_the_mailbox_questions_are_answered_by_position_the_last_or_the_brand():
    accounts = {"need": "account", "multi": False, "options": [{"value": "google", "label": "Google (pat@example.com)"}, {"value": "microsoft", "label": "Microsoft (pat@outlook.example)"}]}
    assert onw._option(accounts, "a primeira") == "google" and onw._option(accounts, "a última") == "microsoft" and onw._option(accounts, "o segundo") == "microsoft"      # validate: allow english-only -- the Portuguese lines under test
    assert onw._option(accounts, "o do outlook") == "microsoft" and onw._option(accounts, "a do google") == "google" and onw._option(accounts, "outlook") == "microsoft", "the brand: the keys a whole line is matched with"
    assert onw._option(accounts, "o do banco") is None and onw._option(accounts, "o terceiro") is None
    boxes = {"need": "source", "multi": False, "options": [{"value": "inbox", "label": "inbox", "words": ["gmail", "google"]}, {"value": "work", "label": "work", "words": ["outlook", "microsoft"]}]}
    assert onw._option(boxes, "a última") == "work" and onw._option(boxes, "o do outlook") == "work" and onw._option(boxes, "o do gmail") == "inbox"      # validate: allow english-only -- the Portuguese lines under test
    folders = {"need": "folder", "multi": False, "options": [{"value": "L1", "label": "contas"}, {"value": "L2", "label": "viagens"}]}
    assert onw._option(folders, "a primeira") == "L1" and onw._option(folders, "o do outlook") is None, "a brand names no folder"      # validate: allow english-only -- the Portuguese lines under test


def test_a_verb_makes_a_line_a_new_request_never_an_answer():
    options = [{"value": "inbox#1", "label": f"{CLINICA} · A"}, {"value": "inbox#2", "label": f"{BANCO} · B"}]
    state = {"need": "message", "multi": False, "options": options}
    assert onw._option(state, "a última") == "inbox#2" and onw._option(state, "cancela a última") is None and onw._option(state, "apaga o primeiro") is None      # validate: allow english-only -- the Portuguese lines under test


def test_a_number_and_a_whole_line_label_are_matched_before_any_pick_and_a_label_that_is_an_ordinal_word_keeps_its_meaning():
    state = {"need": "folder", "multi": False, "options": [{"value": "F-first", "label": "primeiro"}, {"value": "F-second", "label": "segundo"}]}      # validate: allow english-only -- the Portuguese labels under test
    assert onw._option(state, "primeiro") == "F-first" and onw._option(state, "segundo") == "F-second", "the whole-line label match wins"
    assert onw._option(state, "o segundo") == "F-second", "and the position is the same row here"


# --- vacuity ------------------------------------------------------------------------------------------------------------------------------------------


def test_vacuity_without_the_pick_the_oracle_sees_every_pick_fail_and_the_draft_is_dropped(world, monkeypatch):
    draft, ctx, _, _ = asked(world, monkeypatch)
    monkeypatch.setattr(onw, "_option_pick", lambda state, said: None)
    failed = wrong_picks(ctx, draft)
    assert [line for line, _ in failed if line == "o do banco"] == ["o do banco"] and len(failed) == len(PICKS) - 1, failed      # only the digit keeps working
    extras = {}
    assert onw.answer(world["path"], ctx, draft, "o do banco", "chat", None, extras) is None or extras.get("resend") is None, "the planted `_option` answers nothing: no card"


def test_vacuity_a_pick_that_takes_the_first_of_several_matches_is_seen_by_the_several_case(world, monkeypatch):
    draft, ctx, _, _ = asked(world, monkeypatch)
    real = onw._option_pick

    def first_of_several(state, said):
        found = real(state, said)
        form = onw.list_pick.read(said)
        if found is None and form and form["kind"] == "words" and form["words"] == ["example"]:
            return state["options"][0]["value"]
        return found
    monkeypatch.setattr(onw, "_option_pick", first_of_several)
    assert picked(ctx, draft, "o do example") == "inbox#1", "the planted rule picks the first: the real one asks"
    monkeypatch.setattr(onw, "_option_pick", real)
    assert picked(ctx, draft, "o do example") is None
