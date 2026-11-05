"""A message asked for by number or by words, when its box cannot be read for a reason only the computer solves (package sources-identity, limit L62).

The same two reasons as test_items_refused_reason.py (`folder` and `authorization`), over the world of test_mail_read.py: a Gmail and an Outlook box, the real snapshots,
the stand-in providers. A reply that shows a message keeps it and its note of the old time, and then says the reason once for the boxes it holds for; a reply that
shows nothing is the reason alone, not the plain "not available". The provider's words never reach the reply. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_read_refused_reason.py
"""
from __future__ import annotations

import phrase_kit as pk
import test_sources_mail as tsm
from test_calendar_write import world  # noqa: F401  (the calendar world and its real snapshots)
from test_items_refused_reason import refuse_folder
from test_mail_read import CFG, ask, boxes, clock, shown_text, snaps  # noqa: F401


def test_a_message_found_by_words_keeps_its_note_and_then_says_the_authorization(world, snaps, clock):
    boxes(world, snaps)
    snaps.later(minutes=15)
    snaps.providers.fail = tsm.Failure("not-configured", "Google said ZEBRA-SECRET: run uv run providers/mailbox/auth.py")
    reply, _ = ask(world, {"match": "refund"}, "read the refund e-mail")
    lines = reply.splitlines()
    assert "Please send the receipt." in reply and pk.said(lines[-2], "NW_ITEMS_OLD", CFG, time="07:12")
    pk.assert_said(lines[-1], "NW_ITEMS_REFUSED_AUTH", CFG, name="Gmail, Outlook")
    assert "ZEBRA" not in reply and "auth.py" not in reply


def test_a_refused_folder_by_number_is_the_reason_alone_and_not_the_plain_unavailable(world, snaps, clock):
    boxes(world, snaps)
    refuse_folder(world)
    reply, _ = ask(world, {"number": 1}, "read 1")
    assert "\n" not in reply
    pk.assert_said(reply, "NW_ITEMS_REFUSED_FOLDER", CFG, name="Gmail, Outlook")
    assert not pk.said(reply, "MR_UNAVAILABLE", CFG), "and it is not the sentence of a failure a retry may cure"


def test_a_plain_failure_keeps_the_note_and_says_no_reason(world, snaps, clock):
    boxes(world, snaps)
    snaps.later(minutes=15)
    snaps.providers.fail = tsm.Failure("failed", "exit 1")
    reply, _ = ask(world, {"match": "refund"}, "read the refund e-mail")
    assert "Please send the receipt." in reply
    assert not any(pk.said(line, key, CFG, name=name) for line in reply.splitlines() for key in ("NW_ITEMS_REFUSED_AUTH", "NW_ITEMS_REFUSED_FOLDER")
                   for name in ("Gmail", "Outlook", "Gmail, Outlook"))


def test_the_terminal_and_the_page_keep_their_words_for_a_refused_folder(world, snaps, clock):
    boxes(world, snaps)
    refuse_folder(world)
    for number in (1, 2):
        terminal, _ = ask(world, {"number": number}, f"read {number}", channel="terminal")
        assert not any(pk.said(terminal, key, CFG) for key in ("NW_ITEMS_REFUSED_FOLDER", "NW_ITEMS_REFUSED_AUTH")), "the phone's sentence (trying again here will not help) is for a phone"
        assert "Trying again here" not in terminal
    phone, _ = ask(world, {"number": 1}, "read 1")
    pk.assert_said(phone, "NW_ITEMS_REFUSED_FOLDER", CFG, name="Gmail, Outlook")
