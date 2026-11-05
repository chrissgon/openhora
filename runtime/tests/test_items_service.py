"""The account word of a list of mail (package P5b, round 2 of catalog version 4; runtime/ops_items.py `service_spans` and `items_args`, runtime/ops_natural.py, runtime/ops_interpret.py `_unchanged`).

The slot `service` of `items` (a word, since version 4) carries "Gmail" or "Outlook" as the line writes it. Code reads it as `mail-read` reads it (`ops_mail_read._service_of`), the account it names narrows
the list as the line's own account word does, and the raw word never reaches the call as `account`: a word that names no account is the target (the word filter or the mailbox of CB-9), as it was before the
slot existed. Over the real snapshots behind the real natural-request path (the world of test_mail_list_account.py: a Gmail source `inbox` and an Outlook source `work`); every expectation is a literal of
this file; each oracle that narrows has a control that fails on a planted wrong result. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_items_service.py
"""
# validate: allow english-only -- the file holds Portuguese lines under test
from __future__ import annotations

import standin_tree as st
from test_calendar_write import world  # noqa: F401  (the calendar world and its real snapshots)
from test_mail_list_account import ASKING, READER, boxes, call, clock, live, snaps  # noqa: F401

ops_items = st.load("ops_items")
ops_natural = st.load("ops_natural")
ops_interpret = st.load("ops_interpret")

GMAIL_SENDER, OUTLOOK_SENDER = "Bia Costa", "Dan Reis"      # the senders the stand-in providers print in the Gmail and the Outlook box


def test_the_service_word_narrows_the_list_to_that_account_and_never_reaches_the_call_as_a_word(world, snaps, clock):
    boxes(world, snaps)
    line = "list my latest Gmail emails"      # `latest` keeps the line's own reading of the account silent (`_named_account` is empty): the slot is what reads it
    assert ops_items._named_account(line) == {}
    _, extras = call(world, line, {"service_word": "Gmail"})      # the plan of the asking sender: the account is in the call, so the hash binds it
    state = live(world)["state"]["args"]
    assert state["account"] == "google" and "service_word" not in state and "choices" not in extras["plan_confirm"], state
    reply, _ = call(world, "list my latest Outlook emails", {"service_word": "Outlook"}, sender=READER)
    assert OUTLOOK_SENDER in reply and GMAIL_SENDER not in reply, reply


def test_control_without_the_word_the_same_line_holds_no_account_and_lists_the_newest_of_both_boxes(world, snaps, clock):
    boxes(world, snaps)
    line = "list my latest Gmail emails"
    _, extras = call(world, line, {})
    assert "account" not in live(world)["state"]["args"] and "choices" not in extras["plan_confirm"], "no account in the call: both boxes (a count asks no question)"
    reply, _ = call(world, "list my latest Outlook emails", {}, sender=READER)
    assert GMAIL_SENDER in reply and OUTLOOK_SENDER not in reply, "without the word the newest message of both boxes is listed, not Outlook's"


def test_a_word_that_names_no_account_is_the_target_never_an_account(world, snaps, clock):
    boxes(world, snaps, "pt-BR")
    line = "meus e-mails do trabalho"
    via_word, _ = call(world, line, {"service_word": "trabalho"}, sender=READER)
    via_match, _ = call(world, line, {"match": "trabalho"}, sender=READER)
    assert via_word == via_match, "the same reply as the target span"
    call(world, line, {"service_word": "trabalho"})
    args = live(world)["state"]["args"]
    assert "account" not in args and "service_word" not in args, args
    spans = ops_items.service_spans({"service": "trabalho", "day": "hoje"}, None)
    assert spans == {"day": "hoje", "target": "trabalho"}
    assert ops_items.service_spans({"service": "trabalho", "target": "banco"}, None) == {"target": "banco"}, "a target the model gave wins, the word is dropped"
    assert ops_items.service_spans({"service": "Gmail", "state": "não lidos"}, "google") == {"state": "não lidos"}, "a word that names its account is that account and no word filter"      # validate: allow english-only -- the Portuguese words under test


def test_service_args_are_read_from_the_slot_and_a_line_that_names_an_account_wins(world, snaps, clock):
    assert ops_items.span_args_of({"service_word": "Gmail", "match": "banco"}) == {"service": "Gmail", "target": "banco"}
    now = ops_natural._clock()
    assert ops_items.items_args("list my latest Gmail emails", now, None, {}, service="google")["account"] == "google"
    assert "account" not in ops_items.items_args("list my latest Gmail emails", now, None, {}), "control: the line alone names none"
    assert ops_items.items_args("e-mails do outlook", now, None, {}, service="google")["account"] == "microsoft", "the account the line names itself wins"
    assert "account" not in ops_items.items_args("list my latest Gmail emails", now, None, {}, service="trabalho"), "only an account is carried"


def test_a_correction_that_only_adds_the_account_word_is_a_change(world, snaps, clock):
    boxes(world, snaps)
    now = ops_natural._clock()
    line = "no, list my latest Gmail emails"
    old = ops_items.items_args(line, now, None, {})
    assert "account" not in old
    kept = {"op": "items", "args": {}}
    added = {"op": "items", "args": {"service_word": "Gmail"}}
    assert ops_interpret._unchanged(kept, {"args": old}, line) is True, "control: no word, nothing changed"
    assert ops_interpret._unchanged(added, {"args": old}, line) is False, "the account word changes the call"
    assert ops_interpret._unchanged(added, {"args": ops_items.items_args(line, now, None, {}, service="google")}, line) is True, "the plan that already holds the account is unchanged"
