"""A line that names the target of a card is never left off a phone (slice S16c, review round; runtime/messaging_cards.py PHONE_DROPPED and PHONE_LINE).

The probe, generalised: for each kind of card (calendar create, change and cancel; mail send, reply and draft; mailbox actions; file write, replace and trash) two cards that differ only in
their TARGET are drawn for a phone, and their texts must differ; the same two cards on the terminal differ too (vacuity: the difference is in the card, so a phone text that is equal
dropped it). The cards are the lines each builder (runtime/calendar_document.py, send_document.py, mailbox_document.py, files_document.py) writes, with every field filled and the
target's field changed. A second test lists every line a phone drops and says why it names no target: a line added to PHONE_DROPPED has to be added there, with its reason, or the
test fails. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_card_targets.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

cards = st.load("messaging_cards")
phrases = st.load("phrases")

PT = {"language": "pt-BR"}


def line(key, **given):
    """A card line of `key` with every field of its sentence filled ("x"), the given ones as given."""
    fields = phrases._fields_of(phrases.TABLE[phrases.DEFAULT][key])
    return [key, {name: given.get(name, "x") for name in fields}]


def item(lines):
    return {"kind": "effect", "id": 7, "payload": {"card": lines}, "body": phrases.card_text(lines), "payload_sha256": "a" * 64}


def phone(lines):
    return cards.effect_card_text(item(lines), PT, True, False, False)


def terminal(lines):
    return cards.effect_card_text(item(lines), {}, True, False, True)


def calendar_create(title="Haircut", when="Mon 19/10/2026 13:00-14:00"):
    return [line("CARD_CAL_CREATE"), line("CARD_ACCOUNT"), line("CARD_CAL_CALENDAR"), line("CARD_CAL_TITLE", title=title), line("CARD_CAL_WHEN", when=when), line("CARD_CAL_NOBODY")]


def calendar_change(title="Haircut", when="Mon 19/10/2026 13:00-14:00"):
    return [line("CARD_CAL_CHANGE"), line("CARD_ACCOUNT"), line("CARD_CAL_CALENDAR"), line("CARD_CAL_EVENT"), line("CARD_CAL_NOW_WHEN", when=when), line("CARD_CAL_NOW_TITLE", title=title),
            line("CARD_CAL_SNAPSHOT"), line("CARD_CAL_BEFORE_WHEN", when=when), line("CARD_CAL_AFTER_WHEN"), line("CARD_CAL_KEPT_TITLE", title=title), line("CARD_CAL_BASE"), line("CARD_CAL_NOBODY")]


def calendar_cancel(title="Haircut", when="Mon 19/10/2026 13:00-14:00"):
    return [line("CARD_CAL_CANCEL"), line("CARD_ACCOUNT"), line("CARD_CAL_CALENDAR"), line("CARD_CAL_EVENT"), line("CARD_CAL_NOW_WHEN", when=when), line("CARD_CAL_NOW_TITLE", title=title),
            line("CARD_CAL_SNAPSHOT"), line("CARD_CAL_DROP_TITLE", title=title), line("CARD_CAL_WHEN", when=when), line("CARD_CAL_BASE")]


def mail_send(to="ana@example.com", subject="Budget"):
    return [line("CARD_MAIL_SEND"), line("CARD_MAIL_FROM_ACCOUNT"), line("CARD_MAIL_TO", addresses=to), line("CARD_MAIL_SUBJECT", subject=subject), line("CARD_MAIL_COUNT"),
            line("CARD_MAIL_MESSAGE", body="│ Hi"), line("CARD_MAIL_HASH"), line("CARD_MAIL_APPROVE"), line("CARD_MAIL_ONCE")]


def mail_reply(ref="inbox#3", message_id="<a1@mail.example>"):
    return [line("CARD_MAIL_REPLY"), line("CARD_MAIL_FROM_ACCOUNT"), line("CARD_MAIL_REPLY_TO", address="ana@example.com", ref=ref, read_at="2026-10-21T17:00:00Z", subject="Budget"),
            line("CARD_MAIL_IN_REPLY", message_id=message_id), line("CARD_MAIL_SUBJECT_REPLY", subject="Re: Budget"), line("CARD_MAIL_COUNT"), line("CARD_MAIL_MESSAGE", body="│ Hi"),
            line("CARD_MAIL_HASH"), line("CARD_MAIL_APPROVE"), line("CARD_MAIL_ONCE")]


def mail_draft(to="ana@example.com"):
    return [line("CARD_BOX_CODE_DRAFT"), line("CARD_BOX_DRAFT_TO", to=to), line("CARD_BOX_DRAFT_SUBJECT", subject="Budget"), line("CARD_BOX_DRAFT_TEXT", body="│ Hi"), line("CARD_BOX_DRAFT_END")]


def draft_reply(ref="inbox#3", date="2026-10-17 06:00"):
    return [line("CARD_BOX_CODE_DRAFT"), line("CARD_BOX_DRAFT_REPLY_TO", to="ana@example.com"), line("CARD_BOX_DRAFT_REPLY_SUBJECT", subject="Re: Budget"),
            line("CARD_BOX_DRAFT_REPLY", address="ana@example.com", ref=ref, date=date, subject="Budget"), line("CARD_BOX_DRAFT_TEXT", body="│ Hi"), line("CARD_BOX_DRAFT_END")]


def mailbox_actions(subject="Budget", sender="ana@example.com"):
    return [line("CARD_BOX_CODE"), line("CARD_BOX_ARCHIVE", n="1"), line("CARD_BOX_ITEM", i="1", date="2026-10-17 06:00", sender=sender, subject=subject), line("CARD_BOX_READ_AT"), line("CARD_BOX_SNAPSHOT")]


def file_write(folder="Documents", name="plan.txt"):
    return [line("CARD_FILE_CODE_NEW"), line("CARD_ACCOUNT"), line("CARD_FILE_NAME", name=name), line("CARD_FILE_FOLDER", folder=folder), line("CARD_FILE_NEW"), line("CARD_FILE_TEXT", content="│ x"),
            line("CARD_FILE_HASH"), line("CARD_FILE_APPROVE")]


def file_replace(source="notas-trabalho", name="notas.txt", modified="2026-10-20 10:00"):
    return [line("CARD_FILE_CODE_REPLACE"), line("CARD_ACCOUNT"), line("CARD_FILE_NOW", name=name), line("CARD_FILE_SOURCE", source=source), line("CARD_FILE_OWNED"),
            line("CARD_FILE_BASE", revision="r17", modified=modified), line("CARD_FILE_KEPT_DRIVE"), line("CARD_FILE_TEXT", content="│ x"), line("CARD_FILE_HASH"), line("CARD_FILE_APPROVE")]


def file_trash(name="plan.txt", folder="Documents"):
    return [line("CARD_FILE_CODE_TRASH"), line("CARD_ACCOUNT"), line("CARD_FILE_NAME", name=name), line("CARD_FILE_FOLDER", folder=folder), line("CARD_FILE_TRASH_MODIFIED"),
            line("CARD_FILE_TRASH_DRIVE"), line("CARD_FILE_HASH"), line("CARD_FILE_APPROVE")]


# (kind, builder, the two targets as keyword arguments)
PAIRS = [
    ("calendar create, the title", calendar_create, ({"title": "Haircut"}, {"title": "Dentist"})),
    ("calendar create, the time", calendar_create, ({"when": "Mon 19/10/2026 13:00-14:00"}, {"when": "Tue 20/10/2026 13:00-14:00"})),
    ("calendar change, the event's title", calendar_change, ({"title": "Haircut"}, {"title": "Dentist"})),
    ("calendar change, the event's time", calendar_change, ({"when": "Mon 19/10/2026 13:00-14:00"}, {"when": "Tue 20/10/2026 13:00-14:00"})),
    ("calendar cancel, the event's title", calendar_cancel, ({"title": "Haircut"}, {"title": "Dentist"})),
    ("calendar cancel, the event's time", calendar_cancel, ({"when": "Mon 19/10/2026 13:00-14:00"}, {"when": "Tue 20/10/2026 13:00-14:00"})),
    ("mail send, the recipient", mail_send, ({"to": "ana@example.com"}, {"to": "bob@example.com"})),
    ("mail reply, the message answered (same sender, same subject)", mail_reply, ({"ref": "inbox#3"}, {"ref": "inbox#7"})),
    ("mail draft, the recipient", mail_draft, ({"to": "ana@example.com"}, {"to": "bob@example.com"})),
    ("draft reply, the message answered", draft_reply, ({"ref": "inbox#3", "date": "2026-10-17 06:00"}, {"ref": "inbox#7", "date": "2026-10-18 07:00"})),
    ("mailbox actions, the message", mailbox_actions, ({"subject": "Budget"}, {"subject": "Invoice"})),
    ("file write, the folder", file_write, ({"folder": "Documents"}, {"folder": "Clients"})),
    ("file replace, the source (the same name in two sources)", file_replace, ({"source": "notas-trabalho"}, {"source": "notas-casa"})),
    ("file replace, the version it replaces", file_replace, ({"modified": "2026-10-20 10:00"}, {"modified": "2026-10-21 11:00"})),
    ("file trash, the file", file_trash, ({"name": "plan.txt"}, {"name": "budget.txt"})),
    ("file trash, the folder", file_trash, ({"folder": "Documents"}, {"folder": "Clients"})),
]


@pytest.mark.parametrize("kind, build, targets", PAIRS, ids=[p[0] for p in PAIRS])
def test_two_cards_that_differ_only_in_their_target_read_differently_on_a_phone(kind, build, targets):
    first, second = build(**targets[0]), build(**targets[1])
    assert phrases.card_valid(first) and phrases.card_valid(second), "the stand-in lines are well-formed cards"
    assert terminal(first) != terminal(second), "vacuity: the cards differ on the terminal"
    assert phone(first) != phone(second), kind


def test_the_probe_sees_a_phone_that_drops_a_target_line(monkeypatch):
    """Vacuity of the test above: if the source label of a replace card were dropped again, the two replace cards would read alike on a phone and the probe would say so."""
    monkeypatch.setattr(cards, "PHONE_DROPPED", cards.PHONE_DROPPED + ("CARD_FILE_SOURCE",))
    assert phone(file_replace(source="notas-trabalho")) == phone(file_replace(source="notas-casa"))


# Every line a phone drops, and why it names no target (the card names it by other lines that stay).
NO_TARGET = {
    "CARD_MAIL_HASH": "the hash a button binds to",
    "CARD_FILE_HASH": "the hash a button binds to",
    "CARD_CAL_EVENT": "the event's id: the event is named by its title and time as read now",
    "CARD_CAL_SNAPSHOT": "the snapshot's name and read time: the event is named by its title and time as read now",
    "CARD_CAL_BASE": "the version of the event: a check code makes, not a name",
    "CARD_MAIL_IN_REPLY": "the message id of the message answered: it is named by its number, sender and subject",
    "CARD_BOX_SNAPSHOT": "the time the snapshot was read: the messages are listed one by one",
}


def test_every_line_a_phone_drops_has_a_reason_it_names_no_target():
    dropped = set(cards.PHONE_DROPPED)
    assert dropped == set(NO_TARGET), "a line added to (or taken from) PHONE_DROPPED is added to (or taken from) NO_TARGET, with its reason"
    assert all(NO_TARGET.values())
    assert "CARD_FILE_SOURCE" not in dropped and "CARD_MAIL_REPLY_TO" not in dropped, "the lines that name a file's source and the message a reply answers stay"
