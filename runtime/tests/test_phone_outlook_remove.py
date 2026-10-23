"""Removing an event from an Outlook calendar, on a phone (slice S14b, changed by slice S21; runtime/ops_natural.py, runtime/account_start.py).

The live line (2026-10-22, 17:03): "Remova o corte de cabelo de amanha da agenda" about an event on the Microsoft account was answered with the writer's English sentence, raw, because
removing an Outlook event was off (decision Q12 of SPEC-SECRETARY-WRITES). S14b told that refusal in one plain sentence of the language. The maintainer then reversed Q12 ("Apenas apague",
2026-10-22, slice S21): the removal is on, the line opens the cancel card with the Outlook line, and the refusal, its phrase and the code that told it are gone. What this file holds now: the
live line on an Outlook event opens a card in the language of the project (never raw English), the typed path opens the same card, the Google event of the same line still opens its
card, and the file lines keep their sentence.

THE ORACLE is this file's own literals. It never calls the code under test to decide what is right. The vacuity cases plant a raw English sentence and show the oracle flags it. Over the
real calendar world of test_calendar_write.py; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_outlook_remove.py
"""
from __future__ import annotations

import re

import standin_tree as st
from test_calendar_write import Snapshots, fgc, fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import CANCEL, OWNER, build, carry, reads_only  # noqa: F401
from test_event_lookup_number_account import CARD_SENT, Model, add_outlook, fresh_lists, listed, say  # noqa: F401

ops = st.load("ops")

LINE = "Cancela o corte de cabelo no outlook"
ENGLISH = re.compile(r"\b(the|is|not|removing|available|yet|where|goes|until|shown|from|an|event)\b")


def raw_english(text: str) -> bool:
    return bool(ENGLISH.search(text))


OUTLOOK_LINE_EN = "Code removes this event after your approval. Outlook may not keep a copy of a removed event; once approved, it may not be possible to recover it."


def test_the_live_line_on_an_outlook_event_opens_the_cancel_card_in_portuguese_and_never_the_old_refusal(world, monkeypatch):
    build(world, monkeypatch)
    add_outlook(world)
    reply, extras = carry(world, LINE, CANCEL)
    assert reply == CARD_SENT and "resend" in extras and reads_only(world) == [], "a card waits for the approval; nothing was written"
    assert not raw_english(reply) and "Microsoft" not in reply
    item = ops.pending(world["path"], extras["resend"])
    assert item["status"] == "open" and item["body"].splitlines()[0] == OUTLOOK_LINE_EN and f"Account: microsoft ({fgc.ADDRESS})" in item["body"].splitlines()
    assert [r["method"] for r in world["graph"].graph_requests() if r["method"] != "GET"] == [] and "AAMkOut=" in world["graph"].events


def test_the_same_line_in_an_english_project_opens_the_same_card_with_the_english_sentence(world, monkeypatch):
    build(world, monkeypatch, language="en")
    add_outlook(world)
    reply, extras = carry(world, LINE, CANCEL)
    assert reply == "Card #1 waits for your approval." and "resend" in extras
    assert ops.pending(world["path"], extras["resend"])["body"].splitlines()[0] == OUTLOOK_LINE_EN


def test_the_typed_path_opens_the_same_card(world, monkeypatch):
    build(world, monkeypatch)
    add_outlook(world)
    started = ops.event_cancel(world["path"], "microsoft", "outlook#1", channel="terminal")
    assert ops.pending(world["path"], started["pending"])["body"].splitlines()[0] == OUTLOOK_LINE_EN


def test_a_google_event_of_the_same_line_still_opens_its_cancel_card(world, monkeypatch):
    build(world, monkeypatch)
    add_outlook(world)
    model = Model(monkeypatch)
    listed(world, "Cancela o corte de cabelo no google")
    assert say(world, "cancela o 2") == CARD_SENT and model.calls == 0
    item = ops.pending(world["path"], 1)
    assert item["status"] == "open" and "Account: google (pat@example.com)" in item["body"].splitlines() and reads_only(world) == []


FILE_SENTENCE = "Ainda não consigo apagar arquivos por mensagem. Você pode apagar pelo Drive ou OneDrive."      # validate: allow english-only -- the Portuguese sentence under test
LIVE_FILE_LINES = ["Remova o arquivo openhora-mark.png do drive", "Remova o arquivo openhora-mark do drive em /openhora", "Remova o arquivo openhora-mark do drive",  # validate: allow english-only -- the live lines (2026-10-22 17:07)
                   "remova openhora-mark.png da pasta /openhora", "Apague o arquivo logo.png do onedrive", "jogue o arquivo openhora-mark na lixeira"]  # validate: allow english-only -- the lines under test


def test_the_live_file_lines_get_the_sentence_in_the_world_of_the_interpreter_with_no_model_and_no_request(world, monkeypatch):
    """The sender is one the interpreter reads: the check runs before it (and before the planning agent), so the generic "could not build the card" sentence is never reached."""
    build(world, monkeypatch)
    model = Model(monkeypatch)
    for line in LIVE_FILE_LINES:
        assert say(world, line) == FILE_SENTENCE, line
    assert model.calls == 0 and ops.status(world["path"])["requests"] == [] and reads_only(world) == []


def test_an_open_list_does_not_make_the_file_line_a_number_or_an_answer(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch)
    listed(world)      # a list of events is open: the next line could be a number or an answer (the check runs before it is asked)
    assert say(world, "Remova o arquivo openhora-mark.png do drive") == FILE_SENTENCE and model.calls == 0
    assert reads_only(world) == [] and ops.status(world["path"])["requests"] == []


def test_event_and_mail_removals_are_not_taken_for_a_file(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, CANCEL)
    reply = say(world, "Cancela o corte de cabelo")      # the model reads it: an event, so the list of events comes back
    assert reply.startswith("Mais de um evento combina.") and reply != FILE_SENTENCE      # validate: allow english-only -- the Portuguese sentence under test
    assert model.calls == 1


def test_vacuity_a_raw_english_sentence_is_noticed_and_the_card_sentence_is_not():
    assert raw_english("removing an event from an Outlook calendar is not available yet") and not raw_english(CARD_SENT)
