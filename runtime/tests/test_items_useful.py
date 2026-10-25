"""A mail list a person can use, and a freshness that tells the truth (slice S15b, runtime/ops_items.py and runtime/items_mail.py).

The live case (2026-10-22, pt-BR, Telegram): "Liste o ultimo email do meu Outlook" at 16:59 answered "(lido as 10:31)" with a sender address made of a random token and a subject followed by a
date, and the maintainer wrote that the list brought no useful information. The cause of "10:31": the refresh at 16:59 WORKED but found the listing unchanged, which makes no new version, so the
snapshot still said when it was read. Here the same stand-ins as test_items_fresh.py (the real snapshots, the stand-in providers, the real natural-request path), every expectation a literal of this
file, and a vacuity case for each oracle that counts, searches or compares. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_items_useful.py
"""
from __future__ import annotations

import logging

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, world  # noqa: F401  (the calendar world and its real snapshots)
from test_items_fresh import ask, mail_reads, project  # noqa: F401
from test_ops_natural_writes import READER  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_sources = st.load("ops_sources")
ops_items = st.load("ops_items")
mailtext = st.load("items_mail")

LATE = {"hours": 9, "minutes": 47}          # 10:12 UTC + 9h47 = 19:59 UTC = 16:59 in the world's zone (America/Sao_Paulo)
BODY = ("Hello Bia.\n\nPlease confirm your visit at https://clinic.example/confirm?token=abc123 before **Friday**, and write to "
        "ana@clinic.example if you cannot come.\n\n> an old quoted line\n\nThank you,\nThe clinic")


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


@pytest.fixture
def snaps(world, monkeypatch):  # noqa: F811
    s = Snapshots(world, monkeypatch)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: s.now)
    ops_items._CHECKED.clear()
    return s


def inbox(world, snaps, messages, language="en", source="inbox", implementation="gmail"):
    """A project, one mail source of the implementation read once (it holds `messages`), and a provider read count that starts at zero."""
    project(world, language)
    snaps.providers.mail[implementation] = messages
    ops_sources.source_mail(world["path"], source, f"{implementation}:box=inbox;days=7;max=50")
    del snaps.providers.calls[:]


def bia(**more):
    return tsm.message(1, sender="Bia Costa <bia@clinic.example>", subject="Appointment confirmed", **more)


# --- the freshness tells the truth -----------------------------------------------------------------------------------------------------------------


def test_a_refresh_that_finds_the_listing_unchanged_says_it_was_checked_now_and_makes_no_new_version(world, snaps, clock):
    inbox(world, snaps, [bia()])
    before = ops.items(world["path"], kind="mail", channel="terminal")["sources"][0]["read_at"]
    snaps.later(**LATE)
    reply = ask(world, "list my emails")
    assert len(mail_reads(snaps)) == 1, "the provider was asked once"
    assert ops.items(world["path"], kind="mail", channel="terminal")["sources"][0]["read_at"] == before, "the listing did not change: no new version"
    assert reply.splitlines()[0] == "Gmail (checked at 16:59):" and "read at" not in reply
    snaps.later(minutes=3)
    assert ask(world, "list my emails").splitlines()[0] == "Gmail (checked at 16:59):"
    assert len(mail_reads(snaps)) == 1, "the check counts as fresh: a list asked three minutes later reads nothing"


def test_a_refresh_that_finds_a_new_message_says_it_was_read_now(world, snaps, clock):
    inbox(world, snaps, [bia()])
    snaps.providers.mail["gmail"].append(tsm.message(2, sender="Cora Dias <cora@clinic.example>", subject="New invoice"))
    snaps.later(**LATE)
    reply = ask(world, "list my emails")
    assert reply.splitlines()[0] == "Gmail (read at 16:59):" and "New invoice" in reply


def test_the_heading_is_the_old_reading_when_no_check_was_made_so_the_oracle_can_fail(world, snaps, clock):
    inbox(world, snaps, [bia()])
    snaps.later(minutes=5)          # fresh: no read, no check
    assert ask(world, "list my emails").splitlines()[0] == "Gmail (read at 07:12):"


def test_a_failed_refresh_keeps_the_old_time_adds_the_note_and_writes_one_closed_line_to_stderr(world, snaps, clock, capfd):
    inbox(world, snaps, [bia()])
    snaps.later(**LATE)
    snaps.providers.fail = tsm.Failure(reason="the provider said ZEBRA-SECRET")
    capfd.readouterr()
    reply = ask(world, "list my emails")
    seen = capfd.readouterr()
    assert reply.splitlines() == ["Gmail (read at 07:12):", "1. " + "Bia Costa · Appointment confirmed · today 06:00", "(list from 07:12)"]
    assert seen.err == "items: refresh of inbox failed (mail)\n" and "ZEBRA" not in reply + seen.out + seen.err


def test_a_failure_after_a_check_names_the_time_of_the_check(world, snaps, clock):
    inbox(world, snaps, [bia()])
    snaps.later(**LATE)
    ask(world, "list my emails")          # checked at 16:59
    snaps.later(hours=1)
    snaps.providers.fail = tsm.Failure()
    assert ask(world, "list my emails").splitlines()[-1] == "(list from 16:59)"


def test_the_freshness_in_portuguese(world, snaps, clock):
    inbox(world, snaps, [bia()], "pt-BR")
    snaps.later(**LATE)
    assert ask(world, "lista os emails").splitlines()[0] == "Gmail (verificado às 16:59):"      # validate: allow english-only -- the Portuguese sentence under test


# --- one line a person can use ---------------------------------------------------------------------------------------------------------------------


def test_the_sender_is_the_display_name_and_the_address_is_not_shown(world, snaps, clock):
    inbox(world, snaps, [bia()])
    assert ask(world, "list my emails").splitlines()[1] == "1. Bia Costa · Appointment confirmed · today 06:00"


def test_with_no_display_name_the_address_is_shown_without_its_random_token(world, snaps, clock):
    inbox(world, snaps, [tsm.message(1, sender="no-reply-3f9a8c21@mail.vendor.example", subject="Your receipt"),
                         tsm.message(2, sender="<7fa93bc2e1d4@news.vendor.example>", subject="This week"),
                         tsm.message(3, sender="\"ana@clinic.example\" <ana@clinic.example>", subject="Hello")])
    lines = ask(world, "list my emails").splitlines()[1:]
    assert lines == ["1. no-reply@mail.vendor.example · Your receipt · today 06:00", "2. news.vendor.example · This week · today 06:00",
                     "3. ana@clinic.example · Hello · today 06:00"]


@pytest.mark.parametrize("address, readable", [
    ("no-reply-3f9a8c21@mail.vendor.example", "no-reply@mail.vendor.example"),
    ("bounces+1234567-abc@x.example", "bounces-abc@x.example"),
    ("john.smith@clinic.example", "john.smith@clinic.example"),
    ("noreply@vendor.example", "noreply@vendor.example"),
    ("7fa93bc2e1d4@x.example", "x.example"),
    ("12345678@x.example", "x.example"),
    ("reply_a1b2c3d4e5_team@x.example", "reply_team@x.example"),
])
def test_the_readable_address_drops_the_random_tokens_and_keeps_the_words_and_the_domain(address, readable):
    assert mailtext.readable_address(address) == readable


def test_the_readable_address_oracle_can_fail():
    assert mailtext.readable_address("no-reply-3f9a8c21@mail.vendor.example") != "no-reply-3f9a8c21@mail.vendor.example"


def test_the_date_is_today_yesterday_or_the_weekday_and_the_day_in_the_project_language(world, snaps, clock):
    inbox(world, snaps, [tsm.message(1, "2026-10-17T09:00:00Z", sender="Ana <ana@clinic.example>", subject="Today one"),
                         tsm.message(2, "2026-10-16T12:00:00Z", sender="Ana <ana@clinic.example>", subject="Yesterday one"),
                         tsm.message(3, "2026-10-12T21:10:00Z", sender="Ana <ana@clinic.example>", subject="Monday one")])
    assert ask(world, "list my emails").splitlines()[1:] == ["1. Ana · Today one · today 06:00", "2. Ana · Yesterday one · yesterday 09:00", "3. Ana · Monday one · Mon 12/10 18:10"]


def test_the_date_in_portuguese(world, snaps, clock):
    inbox(world, snaps, [tsm.message(1, "2026-10-17T09:00:00Z", sender="Ana <ana@clinic.example>", subject="Today one"),
                         tsm.message(2, "2026-10-16T12:00:00Z", sender="Ana <ana@clinic.example>", subject="Yesterday one"),
                         tsm.message(3, "2026-10-12T21:10:00Z", sender="Ana <ana@clinic.example>", subject="Monday one")], "pt-BR")
    assert ask(world, "lista os emails").splitlines()[1:] == ["1. Ana · Today one · hoje 06:00", "2. Ana · Yesterday one · ontem 09:00", "3. Ana · Monday one · seg 12/10 18:10"]      # validate: allow english-only -- the Portuguese sentence under test


def test_the_subject_is_the_emails_own_words_in_any_language(world, snaps, clock):
    inbox(world, snaps, [tsm.message(1, sender="Ana <ana@clinic.example>", subject="Confirmação da consulta")], "pt-BR")      # validate: allow english-only -- the Portuguese subject under test
    assert ask(world, "lista os emails").splitlines()[1] == "1. Ana · Confirmação da consulta · hoje 06:00"      # validate: allow english-only -- the Portuguese sentence under test


# --- "the last e-mail" and "the 3 last" ---------------------------------------------------------------------------------------------------------------


def test_the_last_email_is_one_item_with_the_start_of_its_text(world, snaps, clock):
    inbox(world, snaps, [bia(text=BODY), tsm.message(2, "2026-10-16T12:00:00Z", sender="Cora <cora@clinic.example>", subject="Older one")])
    assert ask(world, "show me the last email").splitlines() == [
        "Gmail (read at 07:12):",
        "1. Bia Costa · Appointment confirmed · today 06:00",
        "Start of the text: Hello Bia. Please confirm your visit at before Friday, and write to ana@clinic.example if you cannot come. an old quoted line Thank you, The clinic"]


def test_the_live_line_in_portuguese_gives_the_last_message_of_that_account(world, snaps, clock):
    project(world, "pt-BR")
    snaps.providers.mail["gmail"] = [tsm.message(1, "2026-10-17T09:00:00Z", sender="Bia <bia@clinic.example>", subject="Gmail one")]
    snaps.providers.mail["outlook"] = [tsm.message(1, "2026-10-17T08:00:00Z", sender="Dan Reis <dan@work.example>", subject="Weekly report", text="Numbers are in.", source="outlook")]
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    ops_sources.source_mail(world["path"], "work", "outlook:box=inbox;days=7;max=50")
    assert ask(world, "Liste o ultimo email do meu Outlook").splitlines() == [
        "Outlook (lido às 07:12):",      # validate: allow english-only -- the Portuguese sentence under test
        "1. Dan Reis · Weekly report · hoje 05:00",      # validate: allow english-only -- the Portuguese sentence under test
        "Início do texto: Numbers are in."]      # validate: allow english-only -- the Portuguese sentence under test


def test_the_last_email_of_two_mailboxes_is_the_newest_of_both(world, snaps, clock):
    project(world)
    snaps.providers.mail["gmail"] = [tsm.message(1, "2026-10-17T09:00:00Z", sender="Bia <bia@clinic.example>", subject="Gmail one")]
    snaps.providers.mail["outlook"] = [tsm.message(1, "2026-10-17T11:00:00Z", sender="Dan <dan@work.example>", subject="Outlook one", source="outlook")]
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    ops_sources.source_mail(world["path"], "work", "outlook:box=inbox;days=7;max=50")
    reply = ask(world, "the last email")
    assert "Outlook one" in reply and "Gmail one" not in reply and "Gmail (" not in reply


def test_the_three_last_emails_are_three_lines_newest_first_and_no_preview(world, snaps, clock):
    inbox(world, snaps, [tsm.message(n, f"2026-10-17T{8 + n:02d}:00:00Z", sender="Pat <pat@clinic.example>", subject=f"Subject {n}", text="Some text.") for n in (1, 2, 3, 4)])
    reply = ask(world, "show the last 3 emails")
    assert reply.splitlines()[1:] == ["1. Pat · Subject 4 · today 09:00", "2. Pat · Subject 3 · today 08:00", "3. Pat · Subject 2 · today 07:00"], "the snapshot's own numbers, newest first"
    assert "Start of the text" not in reply and "Subject 1" not in reply


PLAIN_COUNTS = [
    ("o ultimo email", 1), ("Liste o último e-mail do meu Outlook", 1), ("a última mensagem", 1), ("os 3 últimos emails", 3), ("os três últimos emails", 3), ("me mostra os dois ultimos", 2),
    ("the last email", 1), ("show the last 3 emails", 3), ("the last three emails", 3), ("my latest e-mail", 1), ("last 5 messages", 5), ("my last emails", None),
    ("el último correo", 1), ("los tres últimos correos", 3), ("los últimos 4 correos", 4),
    ("le dernier courriel", 1), ("les trois derniers e-mails", 3), ("mes 2 derniers mails", 2),
    ("die letzte E-Mail", 1), ("die letzten drei E-Mails", 3), ("zeig die letzten 5 Nachrichten", 5),
    ("l'ultimo messaggio", 1), ("gli ultimi tre messaggi", 3), ("gli ultimi 2 messaggi", 2),
    ("lista os emails", None), ("os últimos emails", None), ("my emails", None), ("o email 3", None), ("30 últimos emails", 20),
]


@pytest.mark.parametrize("line, count", PLAIN_COUNTS)
def test_the_count_a_line_asks_for_comes_from_a_closed_list_of_words_in_six_languages(line, count):
    assert mailtext.count_of(line) == count, line


def test_the_count_oracle_can_fail():
    assert mailtext.count_of("os 3 últimos emails") != 1 and mailtext.count_of("o ultimo email") != 3


def test_the_preview_is_plain_about_300_characters_and_cut_on_a_word():
    words = " ".join(f"word{n}" for n in range(1, 120))
    got = mailtext.preview([words])
    assert got.endswith("…") and 250 < len(got) <= 301 and got[:-1].split(" ")[-1] in words.split(" "), got
    assert mailtext.preview(["short <link: example.com> text *with* markup", "and <address> more"]) == "short text with markup and more"
    assert mailtext.preview(["(no text)"]) == "" and mailtext.preview(["(nothing but the history of earlier messages)"]) == ""
    assert mailtext.preview(["a body that was cut", "(cut)"]) == "a body that was cut"
    assert "…" not in mailtext.preview(["x" * 0 + "fits"]), "vacuity: a short body is not cut"


# --- the terminal and the page keep today's form --------------------------------------------------------------------------------------------------


def test_the_terminal_and_the_conversation_keep_the_address_the_subject_and_the_source_id(world, snaps, clock):
    inbox(world, snaps, [bia(text=BODY)])
    rows = ops.items(world["path"], kind="mail", channel="terminal")["sources"][0]["items"]
    assert rows == [{"n": 1, "line": "bia@clinic.example · Appointment confirmed"}]
    assert ask(world, "show me the last email", sender=None, channel="chat").splitlines() == ["inbox (read 2026-10-17 10:12):", "1. bia@clinic.example · Appointment confirmed"]


# --- nothing of a mail reaches a log ---------------------------------------------------------------------------------------------------------------


def test_no_word_of_a_message_reaches_stderr_stdout_or_a_log(world, snaps, clock, capfd, caplog):
    caplog.set_level(logging.DEBUG)
    inbox(world, snaps, [tsm.message(1, sender="ZEBRAname Person <zebra@clinic.example>", subject="ZEBRAsubject here", text="ZEBRAbody text")])
    capfd.readouterr()
    shown = ask(world, "show me the last email")
    snaps.later(**LATE)
    snaps.providers.fail = tsm.Failure(reason="ZEBRAprovider")
    shown += ask(world, "show me the last email")
    seen = capfd.readouterr()
    assert "ZEBRAname" in shown and "ZEBRAsubject" in shown and "ZEBRAbody" in shown, "vacuity: the words do reach the reply"
    assert "ZEBRA" not in seen.out + seen.err + caplog.text, "and nothing else"
