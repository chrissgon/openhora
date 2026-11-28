"""A first-time recipient on the card of an e-mail from the person's own account (package EM6, chrissgon/openhora#891): `send_document.first_time` (pure),
`ops_step_seams.AccountMailReader.first_time` (the record of correspondents: the senders of the snapshots' indexes and the recipients of e-mails already sent through
this runtime) and `step_send_email._open` (the card and the body, both built from the same list). Offline, on the stand-ins of test_send_own_account.py; every name is
invented. Held here:

  * a card for an address in no snapshot index and in no sent document carries CARD_MAIL_FIRST_TIME, with exactly the new addresses, in the document's order; a known
    address (a sender, a Reply-To, an address already written to), a reply and an incomplete record carry none, and the card still opens;
  * the line changes no hash and adds no key to the document (the approval is of the document, limit L42), and it is a private line (limit L60 stays the card's);
  * the record is read and never kept: a failing record never stops a card.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_first_time.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

import pytest

import phrase_kit as pk
import standin_tree as st
from closed_heads import closed_heads, tier1_forms  # noqa: F401
from test_send_own_account import approve, effect_doc, item_of, reply, send, world  # noqa: F401  (`world` is the fixture)

pytestmark = pytest.mark.usefixtures("tier1_forms")

ops_core = st.load("ops_core")
ops_step_seams = st.load("ops_step_seams")
ops_step_effects = st.load("ops_step_effects")
item_refs = st.load("item_refs")
phrases = st.load("phrases")
send_document = st.load("send_document")
step_send_email = st.load("step_send_email")
cards = st.load("messaging_cards")

CFG, PT = {"language": "en"}, {"language": "pt-BR"}
NEW = "nina@far.example"


def lines_of(item):
    return item["payload"]["card"]


def first_time_lines(item):
    return [line for line in lines_of(item) if line[0] == "CARD_MAIL_FIRST_TIME"]


def test_a_new_address_gets_the_first_time_line(world):
    item = item_of(world, send(world, to=NEW))
    card = lines_of(item)
    keys = [line[0] for line in card]
    at = keys.index("CARD_MAIL_FIRST_TIME")
    assert card[at] == ["CARD_MAIL_FIRST_TIME", {"addresses": NEW}]
    assert keys[at - 1] == "CARD_MAIL_TO" and keys[at + 1] == "CARD_MAIL_SUBJECT"
    assert item["body"] == phrases.card_text(card)


@pytest.mark.parametrize("address", ["bob@shop.example", "Bob@Shop.Example", "desk@clinic.example"])
def test_a_sender_or_a_reply_to_of_the_mailbox_gets_no_line(world, address):
    assert first_time_lines(item_of(world, send(world, to=address))) == []


def test_an_address_already_sent_to_gets_no_line(world):
    first = send(world, to=NEW)
    assert len(first_time_lines(item_of(world, first))) == 1
    approve(world, first)
    second = send(world, to=NEW, subject="Another one")
    assert first_time_lines(item_of(world, second)) == []


def test_only_the_new_recipients_are_listed_in_order(world):
    item = item_of(world, send(world, to="bob@shop.example, " + NEW, cc="omar@far.example"))
    assert first_time_lines(item) == [["CARD_MAIL_FIRST_TIME", {"addresses": f"{NEW}, omar@far.example"}]]


def test_a_reply_never_has_the_line(world):
    assert first_time_lines(item_of(world, reply(world, "inbox#1"))) == []


def test_the_line_changes_no_hash_and_no_document_key(world):
    started = send(world, to=NEW)
    item = item_of(world, started)
    path = Path(ops_step_effects.effect_dir(ops_core.context(world["path"])["cfg"], started["task"], 0)) / "effect.json"
    assert item["payload_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    doc = effect_doc(world, started)
    assert set(doc) == set(send_document.KEYS) | set(send_document.ACCOUNT_KEYS)
    assert [line for line in send_document.card_lines(doc, item["payload_sha256"]) if line[0] == "CARD_MAIL_FIRST_TIME"] == []
    assert send_document.body(doc, item["payload_sha256"]) != item["body"]


def test_an_incomplete_record_shows_no_line(world, monkeypatch):
    desk = world["desk"]
    monkeypatch.setattr(ops_step_seams, "SNAPSHOT_CLOCK", lambda: desk.now + datetime.timedelta(seconds=item_refs.REF_MAX_AGE + 3600))
    assert first_time_lines(item_of(world, send(world, to=NEW))) == [], "a stale snapshot is no complete record"
    monkeypatch.setattr(ops_step_seams.sources, "list_catalog", lambda ctx, **kw: [])
    item = item_of(world, send(world, to=NEW, subject="No source"))
    assert first_time_lines(item) == [] and item["kind"] == "effect", "no mail source is no record, and the card opens"


def test_a_failing_record_never_stops_the_card(world, monkeypatch):
    def broken(self, doc):
        raise RuntimeError("the record failed")
    monkeypatch.setattr(ops_step_seams.AccountMailReader, "first_time", broken)
    item = item_of(world, send(world, to=NEW))
    assert item["kind"] == "effect" and first_time_lines(item) == []


def test_the_line_is_private_on_a_phone(world):
    item = item_of(world, send(world, to=NEW))
    hidden = cards.effect_card_text(item, PT, private=False)
    assert "far.example" not in hidden and phrases.text("CARD_HIDDEN_NOTE_MAIL", PT) in hidden
    shown = cards.effect_card_text(item, PT, private=True)
    assert phrases.text("CARD_MAIL_FIRST_TIME", PT, addresses=NEW) in shown
    assert "Primeira vez" in phrases.text("CARD_MAIL_FIRST_TIME", PT, addresses=NEW)


def test_the_step_kind_name_is_the_seams():
    assert ops_step_seams.SEND_STEP_KIND == step_send_email.KIND.name


def test_the_first_time_of_a_document_is_pure():
    doc = {"from": "me@mine.example", "to": ["a@x.example", "b@x.example"], "cc": ["a@x.example", "me@mine.example"], "bcc": ["c@x.example"], "reply": None}
    assert send_document.first_time(doc, {"b@x.example"}) == ["a@x.example", "c@x.example"]
    assert send_document.first_time(doc, set()) == ["a@x.example", "b@x.example", "c@x.example"]
    assert send_document.first_time(dict(doc, reply={"address": "a@x.example"}), set()) == []


def test_the_sent_record_reads_at_most_sent_read_max_rows_newest_first(world, monkeypatch):
    far, farther = "ola@far.example", "pia@far.example"
    approve(world, send(world, to=far))
    approve(world, send(world, to=farther, subject="Second"))
    ctx = ops_core.context(world["path"])
    rows = ctx["store"].pending_effects_resolved(ctx["conn"], 1)
    assert len(rows) == 1 and rows[0]["id"] == max(r["id"] for r in ctx["store"].pending_list(ctx["conn"], "resolved"))
    monkeypatch.setattr(ops_step_seams, "SENT_READ_MAX", 1)      # only the newest send is read: the older recipient is a first time again
    assert first_time_lines(item_of(world, send(world, to=f"{far}, {farther}", subject="Third"))) == [["CARD_MAIL_FIRST_TIME", {"addresses": far}]]


def test_a_failing_record_is_one_diagnostic_line_with_the_exception_type_only(world, monkeypatch, capsys):
    def broken(self, doc):
        raise RuntimeError("secret@leak.example")
    monkeypatch.setattr(ops_step_seams.AccountMailReader, "first_time", broken)
    item_of(world, send(world, to=NEW))
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "leak.example" not in err and NEW not in err
