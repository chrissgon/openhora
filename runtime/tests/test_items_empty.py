"""A registered source with nothing in its window is empty, not missing (slice S15c, runtime/ops_items.py).

The live case (2026-10-23, pt-BR, Telegram): "Liste o ultimo email do meu Outlook" was answered "the mailbox has not been added" while the Outlook source was registered and its newest snapshot held
"0 messages". With a count, the selection dropped every source left with no items; `items` then found nothing and nothing refused and said "missing". Here the same stand-ins as test_items_useful.py,
literal sentences, and a vacuity case for the oracle that tells the two sentences apart. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_items_empty.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, world  # noqa: F401  (the calendar world and its real snapshots)
from test_items_fresh import ask, mail_reads, project  # noqa: F401
from test_items_useful import LATE, bia, clock  # noqa: F401
from test_ops_natural_writes import READER  # noqa: F401

phrases = st.load("phrases")
ops = st.load("ops")
ops_sources = st.load("ops_sources")
ops_items = st.load("ops_items")

LIVE = "Liste o ultimo email do meu Outlook"
PT = {"language": "pt-BR"}
EN = {"language": "en"}
NOT_ADDED_KEYS = ("NW_ITEMS_ADD_MAIL", "NW_ITEMS_ADD_MAIL_ACCOUNT", "NW_ITEMS_ADD_CAL", "NW_ITEMS_ADD_CAL_ACCOUNT",
                  "NW_ITEMS_CMD_MAIL", "NW_ITEMS_CMD_MAIL_ACCOUNT", "NW_ITEMS_CMD_CAL", "NW_ITEMS_CMD_CAL_ACCOUNT")      # the sentences that say a mailbox or a calendar was never added


@pytest.fixture
def snaps(world, monkeypatch):  # noqa: F811
    s = Snapshots(world, monkeypatch)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: s.now)
    ops_items._CHECKED.clear()
    ops_items._DIRTY.clear()
    return s


def register(world, snaps, language="pt-BR", gmail=None, outlook=None, days=7):
    """A project with the Gmail source `inbox` (when `gmail` is a list) and the Outlook source `work` (when `outlook` is a list), each read once; the provider count starts at zero."""
    project(world, language)
    for source, implementation, messages in (("inbox", "gmail", gmail), ("work", "outlook", outlook)):
        if messages is not None:
            snaps.providers.mail[implementation] = messages
            ops_sources.source_mail(world["path"], source, f"{implementation}:box=inbox;days={days};max=50")
    del snaps.providers.calls[:]


def is_not_added(reply):
    """Whether a reply says a mailbox or calendar was never added (either language)."""
    return any(pk.said(reply, key, cfg) for key in NOT_ADDED_KEYS for cfg in (EN, PT))


def not_added_outlook(reply, cfg=PT):
    """The reply is the sentence that says the Outlook mailbox (and no other) was never added to the project."""
    return any(pk.said(reply, key, cfg, service="Outlook") for key in ("NW_ITEMS_ADD_MAIL_ACCOUNT", "NW_ITEMS_CMD_MAIL_ACCOUNT"))


def assert_empty_mail(reply, state="lido às 07:12"):      # validate: allow english-only -- the Portuguese words under test
    """The reply is exactly the one sentence that says the Outlook inbox holds no e-mail in the last 7 days."""
    assert "\n" not in reply, reply
    pk.assert_said(reply, "NW_ITEMS_EMPTY_MAIL", PT, name="caixa do Outlook", days=7, state=state)


def test_an_empty_outlook_source_asked_for_the_last_email_is_an_empty_sentence_and_not_a_missing_one(world, snaps, clock):
    register(world, snaps, outlook=[])
    reply = ask(world, LIVE)
    assert_empty_mail(reply)
    assert not is_not_added(reply)


def test_the_same_without_a_count(world, snaps, clock):
    register(world, snaps, outlook=[])
    assert_empty_mail(ask(world, "lista os emails do meu Outlook"))


def test_after_a_check_the_sentence_says_verified(world, snaps, clock):
    register(world, snaps, outlook=[])
    snaps.later(**LATE)
    assert_empty_mail(ask(world, LIVE), state="verificado às 16:59")      # validate: allow english-only -- the Portuguese words under test


def test_in_english_and_with_a_one_day_window(world, snaps, clock):
    register(world, snaps, "en", outlook=[], days=1)
    reply = ask(world, "show me the last email on my outlook")
    assert "\n" not in reply
    pk.assert_said(reply, "NW_ITEMS_EMPTY_MAIL_ONE", EN, name="Outlook inbox", state="read at 07:12")


def test_gmail_with_messages_and_an_empty_outlook_with_no_account_named(world, snaps, clock):
    register(world, snaps, gmail=[bia()], outlook=[])
    both = ask(world, "lista os emails")
    source, item, blank, empty = both.splitlines()      # mail-list-account: two mail sources in one reply, a blank line before the second and each name in bold
    assert blank == ""
    pk.assert_said(source, "NW_ITEMS_HEAD_PHONE", PT, name="**Gmail**", when="às 07:12")      # validate: allow english-only -- the Portuguese words under test
    assert item == "1. Bia Costa · Appointment confirmed · hoje 06:00"      # literal: the table's word for today sits inside an item line the kit does not match; validate: allow english-only -- the Portuguese word under test
    assert_empty_mail(empty)
    last = ask(world, "o ultimo email").splitlines()
    pk.assert_said(last[0], "NW_ITEMS_HEAD_PHONE", PT, name="**Gmail**", when="às 07:12")      # validate: allow english-only -- the Portuguese words under test
    assert last[1] == "1. Bia Costa · Appointment confirmed · hoje 06:00"      # literal: the table's word for today sits inside an item line the kit does not match; validate: allow english-only -- the Portuguese word under test
    assert_empty_mail(last[-1])


def test_a_source_the_count_left_with_no_message_is_not_called_empty(world, snaps, clock):
    register(world, snaps, gmail=[tsm.message(1, "2026-10-17T09:00:00Z", sender="Bia <bia@clinic.example>", subject="Older")],
             outlook=[tsm.message(1, "2026-10-17T11:00:00Z", sender="Dan <dan@work.example>", subject="Newer", source="outlook")])
    reply = ask(world, "o ultimo email")
    assert "Newer" in reply and "Older" not in reply and not pk.said(reply, "NW_ITEMS_EMPTY_MAIL", PT) and not pk.said(reply, "NW_ITEMS_EMPTY_MAIL_ONE", PT), "the Gmail source has mail; the count only chose another"


def test_an_empty_calendar_source_is_told_with_its_window(world, snaps, clock):
    project(world, "pt-BR")
    snaps.calendar("agenda", "google", "pat@example.com", [])
    reply = ask(world, "meus eventos")
    assert "\n" not in reply
    pk.assert_said(reply, "NW_ITEMS_EMPTY_CAL", PT, name="Agenda do Google", first="17/10", last="31/10", state="lido às 07:12")      # validate: allow english-only -- the Portuguese words under test
    project(world, "en")
    reply = ask(world, "list my events")
    assert "\n" not in reply
    pk.assert_said(reply, "NW_ITEMS_EMPTY_CAL", EN, name="Google calendar", first="17/10", last="31/10", state="read at 07:12")


def test_a_source_that_is_not_registered_still_says_it_was_not_added(world, snaps, clock):
    register(world, snaps, gmail=[bia()])          # only Gmail is registered
    assert not_added_outlook(ask(world, LIVE))
    project(world, "pt-BR")
    snaps.calendar("agenda", "google", "pat@example.com", [])
    assert not_added_outlook(ask(world, "lista os emails do meu Outlook")), "an empty calendar source is not an Outlook mailbox"
    assert is_not_added(ask(world, "lista os emails do meu Outlook"))


def test_the_terminal_and_the_conversation_keep_their_form_for_an_empty_source(world, snaps, clock):
    register(world, snaps, "en", outlook=[])
    out = ops.items(world["path"], kind="mail", channel="terminal")
    assert out["sources"][0]["items"] == [] and "missing" not in out and out["refused"] == []
    chat = ask(world, "show me the last email on my outlook", sender=None, channel="chat")
    assert "\n" not in chat
    pk.assert_said(chat, "NW_ITEMS_HEAD", EN, source="work", read_at="2026-10-17 10:12")
    assert not is_not_added(chat)
    assert mail_reads(snaps) == []


def test_the_oracle_tells_the_two_sentences_apart():
    assert is_not_added(phrases.text("NW_ITEMS_ADD_MAIL", EN, where="in the terminal")) and is_not_added(phrases.text("NW_ITEMS_ADD_MAIL_ACCOUNT", PT, service="Outlook", where="no terminal"))      # validate: allow english-only -- the Portuguese words under test
    assert not is_not_added(phrases.text("NW_ITEMS_EMPTY_MAIL", PT, name="caixa do Outlook", days=7, state="lido às 07:12")) and not is_not_added(phrases.text("NW_ITEMS_EMPTY_MAIL_ONE", EN, name="Outlook inbox", state="read at 07:12"))      # validate: allow english-only -- the Portuguese words under test
