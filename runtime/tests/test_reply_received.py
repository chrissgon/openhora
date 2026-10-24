"""The time the message a reply answers came (package BL4, S16C-REPLY-DATE; runtime/sources_mail.py, item_refs.py, mail_refs.py, send_document.py, messaging_cards.py).

The mail snapshot's index keeps `received` (`YYYY-MM-DDTHH:MM:SSZ`) for each message; the facts of a reply carry it; the reply document of an e-mail from the person's own account
has it as an OPTIONAL key (`REPLY_OPTIONAL`), inside the hash the card binds, when the facts have it; the card and the phone's line name the message answered by its number, its sender, its
time and its subject. The document is hashed (limits L55, L56, L60), so the guards come first:

  an old document (no key) keeps exactly its keys and its hash: the literal below was computed from a checkout of 5b684f5, before this change;
  a document with the key binds it: one character changed is another hash, and `check` refuses the edited document;
  the time chooses nothing about the recipient (L60: the recipient checks are the ones they were) and is used for nothing but the card;
  the line that shows it names another person's address and subject, so only a reader holding `ask-mail` sees it;
  two cards that differ only in the message answered read differently on a phone (the S16c rule).

Wording is asserted by phrase key plus values (T8), not by a copied sentence. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_reply_received.py
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import time

import pytest

import standin_tree as st
from test_item_refs import desk  # noqa: F401  (the fixture: a desk with a real mail snapshot and its index)
from test_send_own_account import approve, effect_doc, item_of, reply, sent_message, world  # noqa: F401  (the fixture: the project, the stand-in mailers and the snapshot)

send_document = st.load("send_document")
effect_send = st.load("effect_send")
effects = st.load("effects")
item_refs = st.load("item_refs")
mail_refs = st.load("mail_refs")
sources_mail = st.load("sources_mail")
phrases = st.load("phrases")
cards = st.load("messaging_cards")
ops_core = st.load("ops_core")

PT = {"language": "pt-BR"}
RECEIVED = "2026-10-22T17:05:00Z"      # 14:05 on Thursday 22 October 2026 at UTC-03:00
# What a document of a reply hashed to BEFORE this change, from the pieces of `old_pieces` (computed in a scratch copy of 5b684f5 and again at the base of this change):
OLD_REPLY_HASH = "send-37567b7e2315990c0a9875f4c714a57f"
OLD_MESSAGE_ID = "<oh.4ad81f747052f2314fade64aa93bf273@mail.example>"
OLD_DOCUMENT = json.loads(
    '{"account": "google", "attachments": [], "bcc": [], "body": "See you on Monday at one.\\n", "body_sha256": "0d0f3c6fe204097c5db157b713425a5f71e5ea3e01b169a5d52110f68ab52fba",'
    ' "cc": [], "dry_run_sha256": "0000000000000000000000000000000000000000000000000000000000000000", "effect": "send", "from": "pat@mail.example",'
    ' "idempotency_key": "send-37567b7e2315990c0a9875f4c714a57f", "in_reply_to": "<a1@clinic.example>", "message_id": "<oh.4ad81f747052f2314fade64aa93bf273@mail.example>",'
    ' "provider": "gmail", "references": ["<a1@clinic.example>"], "reply": {"address": "ana@clinic.example", "message_id": "<a1@clinic.example>", "provider_id": "18c0ffee",'
    ' "read_at": "2026-10-17 09:30", "ref": "inbox#1", "reply_to": "desk@clinic.example", "subject": "Appointment confirmed"}, "subject": "Re: Appointment confirmed", "task": 7,'
    ' "thread_id": "t1", "to": ["ana@clinic.example"]}')


def facts(**change):
    """What mail_refs.reply_facts returns, with the pieces of the old fixture."""
    base = {"ref": "inbox#1", "address": "ana@clinic.example", "reply_to": "desk@clinic.example", "subject": "Appointment confirmed", "read_at": "2026-10-17 09:30",
            "provider_id": "18c0ffee", "message_id": "<a1@clinic.example>", "thread_id": "t1", "received": None}
    base.update(change)
    return base


def old_pieces(reply=None):
    return dict(task_id=7, provider="gmail", from_addr="pat@mail.example", to=["ana@clinic.example"], cc=[], bcc=[], subject="Re: Appointment confirmed",
                body="See you on Monday at one.\n", in_reply_to="<a1@clinic.example>", attachments=[], dry_run_sha256="0" * 64, account="google", thread_id="t1",
                references=["<a1@clinic.example>"], reply=reply if reply is not None else send_document.reply_of(facts()))


def with_received(received=RECEIVED, **more):
    return send_document.document(**old_pieces(send_document.reply_of(facts(received=received, **more))))


@pytest.fixture
def zone():
    """The machine's zone is UTC-03:00 for the card (the card shows the time in it), and is put back."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "America/Sao_Paulo"
    time.tzset()
    yield
    if before is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = before
    time.tzset()


# --- the document: old documents keep their hash ------------------------------------------------------------------------------------------


def test_a_document_made_before_this_change_has_the_hash_and_the_keys_it_had():
    assert send_document.REPLY_KEYS == ("ref", "address", "reply_to", "subject", "read_at", "provider_id", "message_id") and send_document.REPLY_OPTIONAL == ("received",)
    doc = send_document.document(**old_pieces())      # the facts of an index that has no time: none is carried
    assert doc == OLD_DOCUMENT
    assert doc["idempotency_key"] == OLD_REPLY_HASH and doc["message_id"] == OLD_MESSAGE_ID and set(doc["reply"]) == set(send_document.REPLY_KEYS)


def test_a_stored_document_of_an_open_card_made_before_still_checks_and_keeps_its_key():
    stored = copy.deepcopy(OLD_DOCUMENT)
    assert send_document.check(stored) is stored
    key = send_document.key_of(task_id=7, from_addr="pat@mail.example", to=stored["to"], cc=[], bcc=[], subject=stored["subject"], body=stored["body"], in_reply_to=stored["in_reply_to"],
                               attachments=[], own=send_document._own_of(stored["account"], stored["thread_id"], stored["references"], stored["reply"]))
    assert key == OLD_REPLY_HASH


def test_a_facts_dict_with_no_time_or_a_null_one_makes_the_old_reply_exactly():
    assert send_document.reply_of(facts()) == OLD_DOCUMENT["reply"]
    assert send_document.reply_of({k: v for k, v in facts().items() if k != "received"}) == OLD_DOCUMENT["reply"]
    assert send_document.reply_of(facts(received=RECEIVED)) == {**OLD_DOCUMENT["reply"], "received": RECEIVED}


# --- the document: a time that is there is bound ----------------------------------------------------------------------------------------


def test_a_document_with_the_time_has_it_inside_its_hash_and_one_character_of_it_is_another_hash():
    doc = with_received()
    assert doc["reply"]["received"] == RECEIVED and send_document.check(doc) is doc
    assert doc["idempotency_key"] != OLD_REPLY_HASH and doc["message_id"] != OLD_MESSAGE_ID
    other = with_received("2026-10-22T17:06:00Z")
    assert other["idempotency_key"] not in (OLD_REPLY_HASH, doc["idempotency_key"])
    for edit in ("2026-10-22T17:05:01Z", "2026-10-23T17:05:00Z", "2025-10-22T17:05:00Z"):
        edited = copy.deepcopy(doc)
        edited["reply"]["received"] = edit      # a well-formed time that is not the one the card was made with
        with pytest.raises(effects.EffectError) as why:
            send_document.check(edited)
        assert "the key and the Message-ID are the ones the content derives" in why.value.reason
    dropped = copy.deepcopy(doc)
    del dropped["reply"]["received"]
    with pytest.raises(effects.EffectError):
        send_document.check(dropped)      # taking the time away is another hash too: the document is not the one approved


def test_the_time_is_a_closed_shape_a_hostile_value_is_refused_and_an_unknown_key_is_too():
    doc = with_received()
    for value in ("yesterday", RECEIVED + "\n", "2026-10-22T17:05:00Z\x1b[2J", "2026-10-22 17:05:00", "2026-10-22T17:05:00+00:00", "2026-10-22", "", " " + RECEIVED, 7, ["x"], {"a": 1}):
        edited = copy.deepcopy(doc)
        edited["reply"]["received"] = value
        with pytest.raises(effects.EffectError) as why:
            send_document.check(edited)
        assert "the message answered has the time it came, as the index recorded it" in why.value.reason, value
    extra = copy.deepcopy(doc)
    extra["reply"]["sent"] = RECEIVED
    with pytest.raises(effects.EffectError) as why:
        send_document.check(extra)
    assert "exactly its keys" in why.value.reason
    nulled = copy.deepcopy(doc)
    nulled["reply"]["received"] = None      # present and null is allowed: the document is then hashed with the null
    with pytest.raises(effects.EffectError) as why:
        send_document.check(nulled)
    assert "the key and the Message-ID are the ones the content derives" in why.value.reason      # ... but it is not the document its key names


def test_a_document_built_with_a_hostile_time_is_refused_before_it_has_a_key():
    for value in ("yesterday", RECEIVED + "\n"):
        with pytest.raises(effects.EffectError):
            send_document.document(**old_pieces({**send_document.reply_of(facts()), "received": value}))


def test_the_time_chooses_nothing_about_the_recipient_the_checks_of_l60_are_the_ones_they_were():
    for change in ({"to": ["carol@elsewhere.example"]}, {"cc": ["carol@elsewhere.example"]}, {"bcc": ["carol@elsewhere.example"]}, {"in_reply_to": "<other@clinic.example>"},
                   {"references": []}):
        edited = copy.deepcopy(with_received())
        edited.update(change)
        with pytest.raises(effects.EffectError):
            send_document.check(edited)
    reply_to = copy.deepcopy(with_received())
    reply_to["to"] = [reply_to["reply"]["reply_to"]]
    with pytest.raises(effects.EffectError):
        send_document.check(reply_to)


# --- (d) the approval refuses a document whose time changed after the card was made -------------------------------------------------------


def spy_for(sent):
    return lambda verb, args, account=None: sent.append((verb, args)) or {}


def test_a_document_whose_time_changed_after_the_card_was_made_is_not_approved_and_nothing_is_sent():
    doc = with_received()
    approval = {"scope": "action", "status": "pending-execution", "payload_sha256": send_document.sha(effects._text(doc))}      # what the card's hash approves
    edited = copy.deepcopy(doc)
    edited["reply"]["received"] = "2026-10-22T17:06:00Z"
    sent = []
    with pytest.raises(effects.EffectError):
        effect_send.execute(edited, approval, spy_for(sent), edited["idempotency_key"])
    with pytest.raises(effects.EffectError):
        effect_send.execute(edited, approval, spy_for(sent), doc["idempotency_key"])
    assert sent == [], "no mailer was reached"
    with pytest.raises(effects.EffectError):
        send_document.check(edited)


def test_the_probe_sees_an_own_of_that_drops_the_time(monkeypatch):
    """Vacuity of the test above: a `_own_of` that leaves the time out of the hash accepts the edited document, so the binding is the one `_own_of` gives."""
    doc = with_received()
    edited = copy.deepcopy(doc)
    edited["reply"]["received"] = "2026-10-22T17:06:00Z"
    real = send_document._own_of

    def forgetful(account, thread_id, references, reply):
        return real(account, thread_id, references, None if reply is None else {k: v for k, v in reply.items() if k != "received"})
    monkeypatch.setattr(send_document, "_own_of", forgetful)
    forgotten = send_document.document(**old_pieces(send_document.reply_of(facts(received=RECEIVED))))      # a document made with the forgetful hash ...
    stored = copy.deepcopy(forgotten)
    stored["reply"]["received"] = "2026-10-22T17:06:00Z"
    assert send_document.check(stored) is stored, "... accepts the time changed"
    monkeypatch.undo()
    with pytest.raises(effects.EffectError):
        send_document.check(edited)


# --- (a) the index keeps the time -----------------------------------------------------------------------------------------------------------------


def test_the_index_entry_of_a_message_has_the_time_it_came_in_utc_and_none_when_it_has_none():
    message = {"id": "m1", "thread_id": "t1", "headers": {"Message-ID": "<a1@clinic.example>"}, "from_address": "ana@clinic.example", "subject": "Appointment confirmed"}
    moment = datetime.datetime(2026, 10, 22, 14, 5, 30, 999, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
    assert sources_mail.mail_index_entry(4, message, None, moment)["received"] == RECEIVED.replace(":00Z", ":30Z")
    assert sources_mail.mail_index_entry(4, message, moment=moment.replace(second=0, microsecond=0))["received"] == RECEIVED
    assert sources_mail.mail_index_entry(4, message)["received"] is None
    assert sources_mail.mail_index_entry(4, message, None, None)["received"] is None
    assert set(sources_mail.mail_index_entry(4, message)) == {"n", "id", "thread_id", "message_id", "from_address", "reply_to_address", "subject", "change_key", "received"}


def test_an_entry_the_credential_scan_hits_loses_the_time_with_its_words_and_keeps_its_number():
    message = {"id": "m1", "thread_id": "t1", "headers": {"Message-ID": "<a1@clinic.example>"}, "from_address": "ana@clinic.example", "subject": "Appointment confirmed"}
    moment = datetime.datetime(2026, 10, 22, 17, 5, tzinfo=datetime.timezone.utc)
    entry = sources_mail.mail_index_entry(9, message, lambda data: "a credential", moment)
    assert entry["n"] == 9 and entry["received"] is None and entry["subject"] == "" and entry["from_address"] is None and entry["message_id"] is None


def test_the_snapshot_a_desk_reads_has_the_time_of_each_message_in_its_index(desk):  # noqa: F811
    assert item_refs.resolve(desk.ctx, "inbox#1", channel="terminal", clock=lambda: desk.now)["entry"]["received"] == "2026-10-17T09:00:00Z"
    assert item_refs.resolve(desk.ctx, "inbox#2", channel="terminal", clock=lambda: desk.now)["entry"]["received"] == "2026-10-16T14:30:00Z"
    assert item_refs.resolve(desk.ctx, "inbox#3", channel="terminal", clock=lambda: desk.now)["entry"]["received"] == "2026-10-15T08:00:00Z"


def test_a_message_with_no_moment_has_no_time_in_the_index(tmp_path, monkeypatch):
    import test_sources_mail as tsm
    desk_ = tsm.Desk(tmp_path, monkeypatch)
    desk_.providers.mail["gmail"] = [tsm.message(1, "no time at all", sender="Ana Lima <ana@clinic.example>", subject="Appointment confirmed")]
    desk_.mail("inbox")
    assert item_refs.resolve(desk_.ctx, "inbox#1", channel="terminal", clock=lambda: desk_.now)["entry"]["received"] is None


# --- (b) the read-back ------------------------------------------------------------------------------------------------------------------------


def raw_entry(**change):
    base = {"n": 1, "id": "m1", "thread_id": "t1", "message_id": "<a1@clinic.example>", "from_address": "ana@clinic.example", "reply_to_address": None,
            "subject": "Appointment confirmed", "change_key": None, "received": RECEIVED}
    base.update(change)
    return base


def test_the_read_back_keeps_a_well_formed_time_and_drops_any_other_shape():
    assert item_refs.INDEX_KEYS["mail"][-1] == "received"
    assert item_refs._entry("mail", 1, raw_entry())["received"] == RECEIVED
    for value in ("yesterday", RECEIVED + "\n", "2026-10-22T17:05:00+00:00", "2026-10-22 17:05:00", "", None, 5, ["x"], "\x1b[2J2026-10-22T17:05:00Z", RECEIVED + "Z"):
        assert item_refs._entry("mail", 1, raw_entry(received=value))["received"] is None, repr(value)
    without = {k: v for k, v in raw_entry().items() if k != "received"}
    assert item_refs._entry("mail", 1, without)["received"] is None, "an entry written before the key had none"
    assert set(item_refs._entry("mail", 1, raw_entry(extra="x"))) == set(item_refs.INDEX_KEYS["mail"]), "the keys are closed"


def test_an_index_written_before_this_change_still_passes_its_digest_and_reads_with_no_time(tmp_path, monkeypatch):
    import test_sources_mail as tsm
    real = sources_mail.mail_index_entry

    def old(n, message, scan=None, moment=None):      # the entry as it was written before the key
        entry = real(n, message, scan)
        entry.pop("received")
        return entry
    monkeypatch.setattr(sources_mail, "mail_index_entry", old)
    desk_ = tsm.Desk(tmp_path, monkeypatch)
    desk_.providers.mail["gmail"] = [tsm.message(1, "2026-10-17T09:00:00Z", sender="Ana Lima <ana@clinic.example>", subject="Appointment confirmed")]
    desk_.mail("inbox")
    got = item_refs.resolve(desk_.ctx, "inbox#1", channel="terminal", clock=lambda: desk_.now)      # an index that does not match its digest is refused: it does match
    assert got["entry"]["received"] is None and got["entry"]["subject"] == "Appointment confirmed"


# --- (c) the facts and the document built from them -------------------------------------------------------------------------------------------


def test_the_facts_of_a_reply_carry_the_time_the_index_recorded(world):  # noqa: F811
    ctx = ops_core.context(world["path"])
    clock = lambda: world["desk"].now      # noqa: E731
    found = item_refs.resolve(ctx, "inbox#1", channel=None, clock=clock)
    got = mail_refs.reply_facts(found, "google")
    assert got["received"] == "2026-10-17T09:00:00Z" and got["ref"] == "inbox#1" and got["address"] == "ana@clinic.example"
    assert {"ref", "address", "reply_to", "subject", "read_at", "provider_id", "message_id", "thread_id", "received"} == set(got)
    document = send_document.document(**old_pieces(send_document.reply_of(got)))
    assert document["reply"]["received"] == "2026-10-17T09:00:00Z" and send_document.check(document) is document
    without = mail_refs.reply_facts({**found, "entry": {**found["entry"], "received": None}}, "google")
    assert without["received"] is None and send_document.reply_of(without)["ref"] == "inbox#1" and "received" not in send_document.reply_of(without)


# --- (e) the card line, its phone form, and who sees it ---------------------------------------------------------------------------------------


def card_item(doc):
    lines = send_document.card_lines(doc, "a" * 64)
    return {"kind": "effect", "id": 7, "payload": {"card": lines}, "body": phrases.card_text(lines), "payload_sha256": "a" * 64}, lines


def the_line(lines, *keys):
    found = [line for line in lines if line[0] in keys]
    assert len(found) == 1, [line[0] for line in lines]
    return found[0]


def test_a_reply_with_the_time_has_the_line_that_names_the_message_by_sender_ref_time_and_subject(zone):
    item, lines = card_item(with_received())
    key, fields = the_line(lines, "CARD_MAIL_REPLY_TO", "CARD_MAIL_REPLY_TO_AT")
    assert key == "CARD_MAIL_REPLY_TO_AT"
    assert fields == {"address": "ana@clinic.example", "ref": "inbox#1", "read_at": "2026-10-17 09:30", "subject": "Appointment confirmed", "received": "Thu 22/10/2026 14:05"}
    assert phrases.card_valid(lines) and phrases.card_text(lines) == item["body"]
    assert phrases.text("CARD_MAIL_REPLY_TO_AT", None, **fields) in item["body"].splitlines()
    assert phrases.text("CARD_MAIL_REPLY_TO_AT", None, **fields) != phrases.text("CARD_MAIL_REPLY_TO_AT", PT, **fields)
    assert "Thu 22/10/2026 14:05" in item["body"]
    assert "22/10/2026" not in card_item(with_received(None))[0]["body"]


def test_a_reply_without_the_time_has_the_line_it_always_had(zone):
    for doc in (send_document.document(**old_pieces()), with_received(None)):
        item, lines = card_item(doc)
        key, fields = the_line(lines, "CARD_MAIL_REPLY_TO", "CARD_MAIL_REPLY_TO_AT")
        assert key == "CARD_MAIL_REPLY_TO" and set(fields) == {"address", "ref", "read_at", "subject"}
        assert phrases.card_valid(lines)


def test_the_time_is_shown_in_the_machines_zone_whatever_the_zone_it_was_written_in(zone):
    doc = with_received("2026-12-31T23:30:00Z")      # 20:30 on Thursday 31 December at UTC-03:00
    assert the_line(card_item(doc)[1], "CARD_MAIL_REPLY_TO_AT")[1]["received"] == "Thu 31/12/2026 20:30"
    early = with_received("2026-01-15T02:00:00Z")      # the day before: 23:00 on Wednesday 14 January
    assert the_line(card_item(early)[1], "CARD_MAIL_REPLY_TO_AT")[1]["received"] == "Wed 14/01/2026 23:00"


def test_a_phone_says_the_line_in_the_language_with_the_localized_weekday_and_keeps_the_ref(zone):
    item, lines = card_item(with_received())
    fields = the_line(lines, "CARD_MAIL_REPLY_TO_AT")[1]
    assert cards.PHONE_LINE["CARD_MAIL_REPLY_TO_AT"] == "PHONE_MAIL_REPLY_TO_AT" and cards.PHONE_LINE["CARD_MAIL_REPLY_TO"] == "PHONE_MAIL_REPLY_TO"
    assert {"address", "ref", "received", "subject"} == phrases._fields_of(phrases.TABLE["en"]["PHONE_MAIL_REPLY_TO_AT"])
    assert "read_at" not in phrases._fields_of(phrases.TABLE["en"]["PHONE_MAIL_REPLY_TO_AT"]), "the read time goes, the received time is new"
    pt = phrases.localize_dates(cards.effect_card_text(item, PT, True, False, False), PT)      # the bridge says the dates of a message in the project's language (messaging_bridge.dated)
    shown = "{} {}".format(phrases.text("WD_THU", PT), "22/10/2026 14:05")
    assert shown == "qui 22/10/2026 14:05"
    assert phrases.text("PHONE_MAIL_REPLY_TO_AT", PT, **{**fields, "received": shown}) in pt.splitlines()
    assert "inbox#1" in pt and "ana@clinic.example" in pt and "Appointment confirmed" in pt and "09:30" not in pt
    en = cards.effect_card_text(item, {}, True, False, False)
    assert phrases.text("PHONE_MAIL_REPLY_TO_AT", {}, **fields) in en.splitlines() and "Thu 22/10/2026 14:05" in en
    terminal = cards.effect_card_text(item, {}, True, False, True)
    assert phrases.text("CARD_MAIL_REPLY_TO_AT", {}, **fields) in terminal.splitlines(), "the terminal keeps the card line, with the read time"


def test_a_reader_without_ask_mail_sees_neither_the_line_nor_the_other_persons_address(zone):
    assert "CARD_MAIL_REPLY_TO_AT" in phrases.CARD_PRIVATE and "CARD_MAIL_REPLY_TO" in phrases.CARD_PRIVATE
    item, lines = card_item(with_received())
    kept = phrases.card_without_private(lines)
    assert "CARD_MAIL_REPLY_TO_AT" not in {line[0] for line in kept} and "CARD_MAIL_REPLY_TO" not in {line[0] for line in kept}
    for approvable in (True, False):
        text = cards.effect_card_text(item, PT, False, False, approvable)
        for secret in ("ana@clinic.example", "Appointment confirmed", "22/10/2026", "inbox#1", "14:05"):
            assert secret not in text, (approvable, secret)
        assert phrases.text(phrases.hidden_note_key(lines, kept), PT) in text, "the card says that lines were left out"


def test_the_phrase_of_each_new_key_is_in_both_languages_with_the_same_fields_and_is_not_the_same_text():
    for key in ("CARD_MAIL_REPLY_TO_AT", "PHONE_MAIL_REPLY_TO_AT"):
        en, pt = phrases.TABLE["en"][key], phrases.TABLE["pt-BR"][key]
        assert phrases._fields_of(en) == phrases._fields_of(pt) and en != pt
    assert phrases._fields_of(phrases.TABLE["en"]["CARD_MAIL_REPLY_TO_AT"]) == {"address", "ref", "read_at", "received", "subject"}
    assert phrases.card_valid([["CARD_MAIL_REPLY_TO_AT", {"address": "a@b.example", "ref": "inbox#1", "read_at": "x", "received": "Thu 22/10/2026 14:05", "subject": "s"}]])


# --- (f) two replies, two messages, two texts --------------------------------------------------------------------------------------------------


def test_two_replies_to_two_messages_of_the_same_sender_read_differently_on_a_phone(zone):
    first = with_received(RECEIVED, ref="inbox#1", message_id="<a1@clinic.example>")
    other = send_document.document(**{**old_pieces(send_document.reply_of(facts(received="2026-10-23T13:40:00Z", ref="inbox#4", message_id="<a4@clinic.example>"))),
                                      "in_reply_to": "<a4@clinic.example>", "references": ["<a4@clinic.example>"]})
    assert first["reply"]["address"] == other["reply"]["address"] and first["reply"]["subject"] == other["reply"]["subject"]
    def phone(doc):
        return phrases.localize_dates(cards.effect_card_text(card_item(doc)[0], PT, True, False, False), PT)
    one, two = phone(first), phone(other)
    assert one != two
    assert "inbox#1" in one and "inbox#4" in two and "22/10/2026 14:05" in one and "23/10/2026 10:40" in two
    # the same message number in two snapshots that differ only in when the message came reads differently too: the time is a target line
    again = with_received("2026-10-24T09:00:00Z")
    assert phone(again) != one
    # vacuity: with no time on either, only the number tells them apart, and with neither the two phone texts would be the same
    assert phone(with_received(None)) != phone(with_received()), "the time is on the phone's line when there is one"


# --- the whole way: the index, the facts, the preparation, the card, the approval ------------------------------------------------------------------


def test_a_reply_prepared_from_a_snapshot_carries_the_time_into_its_document_its_card_and_its_one_send(world, zone):  # noqa: F811
    started = reply(world, "inbox#1")
    doc = effect_doc(world, started)
    assert doc["reply"]["received"] == "2026-10-17T09:00:00Z" and set(doc["reply"]) == set(send_document.REPLY_KEYS) | {"received"}
    item = item_of(world, started)
    card = item["payload"]["card"]
    line = the_line(card, "CARD_MAIL_REPLY_TO", "CARD_MAIL_REPLY_TO_AT")
    assert line[0] == "CARD_MAIL_REPLY_TO_AT" and line[1]["received"] == "Sat 17/10/2026 06:00" and line[1]["ref"] == "inbox#1"
    assert phrases.card_text(card) == item["body"] and item["payload_sha256"] == send_document.sha(effects._text(doc)), "the card is the lines of the document, and the hash is its"
    done = approve(world, started)
    assert done["task_state"] == "done" and len(world["gmail"].sent) == 1
    assert sent_message(world["gmail"])["To"] == "ana@clinic.example" and sent_message(world["gmail"])["Cc"] is None, "the time chose nothing about the recipient"
