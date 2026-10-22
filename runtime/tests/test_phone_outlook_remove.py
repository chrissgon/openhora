"""The refusal to remove an event from an Outlook calendar, told on a Portuguese phone (slice S14b; runtime/messaging_failure.py `from_step`, `ops_natural._error`).

The live line (2026-10-22, 17:03): "Remova o corte de cabelo de amanha da agenda" about an event on the Microsoft account was answered with the writer's English sentence, raw. The refusal
itself is by design (decision Q12 of SPEC-SECRETARY-WRITES: removing an event from Outlook is off until a live check shows where a removed event goes) and is not changed here. The cause:
`step_calendar_event._prepare` raises StepFailure("not_available", ...) with an English `next`; `account_start.start` puts `messaging_failure.from_step(..., said=next)` on the OpsError as
`.phone`; `from_step` had no sentence for that code and returned `phrases.localize(said)`, which only knows the families of reminders and files and returns the English unchanged;
`ops_natural._error` sent `.phone` as it was, as a plain reply with no `error: ` mark, so the net of S14 (`phone_errors`) never looked at it.

THE ORACLE is this file's own literals. It never calls the code under test to decide what is right. The vacuity cases plant the live English sentence and show the oracle flags it. The
Google event of the same line still opens its cancel card. Over the real calendar world of test_calendar_write.py; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_outlook_remove.py
"""
from __future__ import annotations

import re

import standin_tree as st
from test_calendar_write import Snapshots, fgc, fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import CANCEL, OWNER, build, carry, reads_only  # noqa: F401
from test_event_lookup_number_account import CARD_SENT, Model, add_outlook, fresh_lists, listed, say  # noqa: F401

ops = st.load("ops")

PT = "Ainda não consigo apagar eventos da agenda do Outlook por aqui. Você pode apagar pelo próprio Outlook."      # validate: allow english-only -- the Portuguese sentence under test
EN = "I cannot delete events from an Outlook calendar from here yet. You can delete it in Outlook itself."
LIVE = "removing an event from an Outlook calendar is not available yet: Microsoft does not say where a removed event goes, so it is off until that is shown"
LINE = "Cancela o corte de cabelo no outlook"
ENGLISH = re.compile(r"\b(the|is|not|removing|available|yet|where|goes|until|shown|from|an|event)\b")


def raw_english(text: str) -> bool:
    return bool(ENGLISH.search(text))


def test_the_live_line_on_an_outlook_event_is_the_one_plain_sentence_in_portuguese(world, monkeypatch):
    build(world, monkeypatch)
    add_outlook(world)
    reply, extras = carry(world, LINE, CANCEL)
    assert reply == PT and "resend" not in extras and reads_only(world) == [], "nothing was written"
    assert not raw_english(reply) and "Microsoft" not in reply and "off until" not in reply


def test_the_same_line_in_an_english_project_is_the_english_sentence_of_the_table_and_not_the_writers_text(world, monkeypatch):
    build(world, monkeypatch, language="en")
    add_outlook(world)
    reply, extras = carry(world, LINE, CANCEL)
    assert reply == EN and "resend" not in extras


def test_the_typed_path_and_the_page_keep_the_precise_text(world, monkeypatch):
    build(world, monkeypatch)
    add_outlook(world)
    refused = None
    try:
        ops.event_cancel(world["path"], "microsoft", "outlook#1", channel="terminal")
    except ops.OpsError as e:
        refused = e
    assert refused is not None and "removing an event from an Outlook calendar is not available yet" in str(refused)


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


def test_vacuity_the_live_english_sentence_is_noticed_and_the_new_one_is_not():
    assert raw_english(LIVE) and raw_english("error: " + LIVE) and not raw_english(PT)
