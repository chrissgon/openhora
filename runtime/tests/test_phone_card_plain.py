"""The card of a calendar change on a phone is plain, and "Encontrei ... É este?" goes before it with the time the card shows (slice S16c, runtime/messaging_cards.py,
runtime/event_lookup.py, runtime/messaging_bridge.py).

The live case (2026-10-23, a pt-BR project): "Remova o evento corte de cabelo da agenda" opened an Outlook removal card that a phone drew with the raw Outlook event id, "Nomeado como
agenda-outlook#1, do instantaneo lido em ...", "Baseado na versao ... do evento" and "Removendo, titulo: corte de cabelo"; and a separate message "Encontrei: corte de cabelo, sab
24/10/2026 14:00-15:00. E este?" arrived AFTER the card, with the time of the snapshot (14:00) when the event, read live for the card, was at 10:00-11:00. Here the real calendar snapshots
(test_calendar_write.py's world, the stand-in Google and Graph services), the real family path and the real card, a stand-in clock (Wednesday 2026-10-21 15:00 at -03:00) and a model that
is stood in. The phone text is what `messaging_cards.build` draws for a sender; the terminal text is the stored body. Every expectation is a literal of this file; each oracle reads
the lines of the card or the messages sent, never the code under test, and each test has a vacuity case. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_card_plain.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import fgw, rows, world  # noqa: F401  (the calendar world and its stand-in providers)
from test_event_lookup import OWNER, build as build_source, op_text
from test_event_lookup_own_events import Model, fresh  # noqa: F401
from test_ops_natural_writes import forget  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
operations = st.load("operations")
cards = st.load("messaging_cards")
event_lookup = st.load("event_lookup")

CAPS = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}
POLICY = {"messaging": ["read", "ask-mail", "approve-effect-calendar"]}
PT = {"language": "pt-BR"}
OUTLOOK_LINE = "remova o evento corte de cabelos da agenda"
# the lines a phone must not show of the live card, as the page and the terminal show them (fragments that cannot be in a plain card)
TECHNICAL = ("Evento: AAMk", "Nomeado como", "instantâneo lido", "Baseado na versão", "Removendo, título:", "Event: AAMk", "Named as", "snapshot read at", "Based on version")      # validate: allow english-only -- the Portuguese fragments under test


def snapshot_world(world, monkeypatch, outlook=True):
    """A calendar source for Google ("agenda", no events) and one for Outlook ("agenda-outlook") that holds a haircut on Saturday 24/10 at 14:00 as of the snapshot, while the
    provider holds it at 10:00-11:00 now (it was moved there since): the card is made from the provider's event, as it is read live."""
    build_source(world, monkeypatch, events=[])
    world["snaps"].calendar("agenda-outlook", "outlook", "default", [tsm.event(1, "2026-10-24T14:00:00-03:00", "2026-10-24T15:00:00-03:00", "corte de cabelo", id="AAMkEv24=")])
    world["graph"].add_event("AAMkEv24=", "corte de cabelo", "2026-10-24T13:00:00", "2026-10-24T14:00:00")          # 10:00-11:00 at -03:00


def google_world(world, monkeypatch):
    """The same for Google: the snapshot says Saturday 24/10 at 14:00, the provider holds it at 10:00-11:00."""
    build_source(world, monkeypatch, events=[])
    world["snaps"].calendar("agenda", "google", fgw.CALENDAR, [tsm.event(1, "2026-10-24T14:00:00-03:00", "2026-10-24T15:00:00-03:00", "corte de cabelo", id="evmoved")])
    world["google"].add_event("evmoved", "corte de cabelo", {"dateTime": "2026-10-24T10:00:00-03:00"}, {"dateTime": "2026-10-24T11:00:00-03:00"})


def asked(world, monkeypatch, line, *answers):
    model = Model(monkeypatch, *answers)
    got = ops.say(world["path"], line, channel="messaging", sender=OWNER)
    return got, model


def phone(world, got, cfg=PT):
    item = ops.pending(world["path"], got["resend"])
    return item, cards.build("northwind", item, CAPS, POLICY, "text", None, operations=operations, cfg=cfg, sender=OWNER)


def lines_of(text):
    return text.splitlines()


def test_the_outlook_removal_card_on_a_phone_has_none_of_the_technical_lines_and_keeps_the_plain_ones(world, monkeypatch):
    snapshot_world(world, monkeypatch)
    got, model = asked(world, monkeypatch, OUTLOOK_LINE, op_text("event-cancel"))
    assert got["reply"].endswith("O card #1 espera a sua aprovação.") and model.calls == 1      # validate: allow english-only -- the Portuguese line or sentence under test
    item, built = phone(world, got)
    text = built["message"]["text"]
    for fragment in TECHNICAL:
        assert fragment not in text, (fragment, text)
    assert "AAMkEv24=" not in text and "agenda-outlook" not in text and "2026-10-21T17:00:00Z" not in text
    wanted = ["Conta: microsoft (", "Agenda: personal", "O evento agora é em: Sat 24/10/2026 10:00-11:00 (America/Sao_Paulo)", "O evento agora: corte de cabelo"]      # validate: allow english-only -- the Portuguese line or sentence under test
    assert [w for w in wanted if not any(l.startswith(w) for l in lines_of(text))] == [], text
    assert "Outlook pode não guardar uma cópia" in text, "the line about where a removed event goes stays"      # validate: allow english-only -- the Portuguese line or sentence under test
    assert text.count("corte de cabelo") == 1, "the event is said once, not twice"
    assert "Quando:" not in text, "the removal says the time once"      # validate: allow english-only -- the Portuguese line or sentence under test
    assert item["status"] == "open" and cards_hash(item) == built["content_sha256"] == item["payload_sha256"]


def cards_hash(item):
    return item["payload_sha256"]


def test_the_terminal_and_the_page_keep_every_line_and_the_hash_is_the_effects_own(world, monkeypatch):
    snapshot_world(world, monkeypatch)
    got, _ = asked(world, monkeypatch, OUTLOOK_LINE, op_text("event-cancel"))
    item, built_pt = phone(world, got)
    english = cards.effect_card_text(item, {})
    assert english == item["body"], "the stored body is the English lines, unchanged"
    for needle in ("Event: AAMkEv24=", "Named as agenda-outlook#1, from the snapshot read at ", "Based on version ", "Removing, title: corte de cabelo"):
        assert needle in item["body"], needle
    whole = cards.effect_card_text(item, PT, True, False, True)          # approvable: what the terminal and the page are told in the language
    for needle in ("Evento: AAMkEv24=", "Nomeado como agenda-outlook#1", "Baseado na versão ", "Removendo, título: corte de cabelo"):      # validate: allow english-only -- the Portuguese line or sentence under test
        assert needle in whole, needle
    built_en = cards.build("northwind", item, CAPS, POLICY, "text", None, operations=operations, cfg={}, sender=OWNER)
    assert built_pt["content_sha256"] == built_en["content_sha256"] == item["payload_sha256"], "the phone's wording is a rendering: the hash is the effect document's"
    doc = json.loads(open(effect_path(world, item), encoding="ascii").read())
    assert st.load("calendar_document").sha(st.load("effects")._text(doc)) == item["payload_sha256"], "the hash is of the effect document, which the phone's wording does not touch"
    assert doc["event_id"] == "AAMkEv24=" and doc["reference"]["source"] == "agenda-outlook", "the effect document keeps the id and the snapshot it was named from"


def effect_path(world, item):
    cfg = ops_core.context(world["path"])["cfg"]
    step = st.load("ops_step_effects")
    return step.effect_dir(cfg, item["task_id"], int(item["payload"].get("cycle", 0))) + "/effect.json"


def test_the_oracle_of_the_technical_lines_sees_them_in_the_page_text(world, monkeypatch):
    """Vacuity: the same fragments are found in the text a terminal gets, so the absence on the phone is the rendering, not a card without them."""
    snapshot_world(world, monkeypatch)
    got, _ = asked(world, monkeypatch, OUTLOOK_LINE, op_text("event-cancel"))
    item, _ = phone(world, got)
    assert sum(1 for f in TECHNICAL if f in cards.effect_card_text(item, PT, True, False, True)) >= 4


def test_encontrei_names_the_event_as_the_card_has_it_not_as_the_snapshot_had_it(world, monkeypatch):
    snapshot_world(world, monkeypatch)
    got, _ = asked(world, monkeypatch, OUTLOOK_LINE, op_text("event-cancel"))
    assert got["lead"] == "Encontrei: corte de cabelo, Sat 24/10/2026 10:00-11:00. É este?", got["lead"]      # validate: allow english-only -- the Portuguese line or sentence under test
    assert got["reply"] == got["lead"] + "\n" + "O card #1 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test
    assert "14:00" not in got["lead"], "vacuity: the snapshot's time (14:00) is not the one said"
    item, built = phone(world, got)
    assert "O evento agora é em: Sat 24/10/2026 10:00-11:00" in built["message"]["text"], "the card and the line say the same time"      # validate: allow english-only -- the Portuguese line or sentence under test


def test_google_has_the_same_plain_card_and_the_live_time_in_the_line(world, monkeypatch):
    google_world(world, monkeypatch)
    got, _ = asked(world, monkeypatch, "remova o evento corte de cabelos da agenda", op_text("event-cancel"))
    assert got["lead"] == "Encontrei: corte de cabelo, Sat 24/10/2026 10:00-11:00. É este?"      # validate: allow english-only -- the Portuguese line or sentence under test
    item, built = phone(world, got)
    text = built["message"]["text"]
    for fragment in TECHNICAL + ("evmoved",):
        assert fragment not in text, (fragment, text)
    assert "Agenda: personal" in text and "O Google deve movê-lo para a lixeira" in text      # validate: allow english-only -- the Portuguese line or sentence under test
    assert "Event: evmoved" in item["body"] and "Event: evmoved" not in cards.effect_card_text(item, {}, True, False, False)


def test_a_change_card_on_a_phone_says_the_time_now_and_the_time_after_and_no_read_time(world, monkeypatch):
    snapshot_world(world, monkeypatch)
    got, _ = asked(world, monkeypatch, "mude o corte de cabelos para as 15h", op_text("event-change", {"time": "as 15h"}, time_iso="2026-10-22T15:00", weekday="thu"))
    item, built = phone(world, got)
    text = built["message"]["text"]
    for fragment in TECHNICAL + ("2026-10-21T17:00:00Z", "AAMkEv24="):
        assert fragment not in text, (fragment, text)
    assert "O código altera este evento depois da sua aprovação, só se ele ainda estiver como está agora." in text      # validate: allow english-only -- the Portuguese line or sentence under test
    for needle in ("Antes: Quando: Sat 24/10/2026 10:00-11:00", "Depois: Quando: Sat 24/10/2026 15:00-16:00"):      # validate: allow english-only -- the Portuguese line or sentence under test
        assert needle in text, (needle, text)
    assert "como foi lido em" not in text, "the phone does not say the time the event was read"      # validate: allow english-only -- the Portuguese line or sentence under test
    assert "only if it is still as read at" in item["body"], "the terminal keeps the read time"


def test_an_exact_name_gets_no_encontrei_line_and_the_plain_card_alone(world, monkeypatch):
    google_world(world, monkeypatch)
    got, _ = asked(world, monkeypatch, "remova o evento corte de cabelo da agenda", op_text("event-cancel"))
    assert "lead" not in got and got["reply"] == "O card #1 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test
    nope = asked(world, monkeypatch, "remova o evento corte de cabelos da agenda", op_text("event-cancel"))[0]
    assert "lead" in nope, "vacuity: a near name does"


# --- the mail and the file cards: the same internals are left off a phone ------------------------------------------------------------------------------------


def synthetic(lines):
    phrases = st.load("phrases")
    return {"kind": "effect", "id": 7, "payload": {"card": lines}, "body": phrases.card_text(lines), "payload_sha256": "a" * 64}


def test_a_mail_reply_card_on_a_phone_leaves_off_the_snapshot_the_message_id_and_the_path(world):
    lines = [["CARD_MAIL_REPLY", {}], ["CARD_MAIL_REPLY_TO", {"address": "ana@example.com", "ref": "inbox#3", "read_at": "2026-10-21T17:00:00Z", "subject": "Budget"}],
             ["CARD_MAIL_IN_REPLY", {"message_id": "<abc123@mail.example>"}],
             ["CARD_MAIL_ATTACHMENT", {"name": "plan.pdf", "bytes": "120", "sha": "b" * 64, "path": "/srv/project/plan.pdf"}], ["CARD_MAIL_HASH", {"sha": "a" * 64}]]
    item = synthetic(lines)
    phone_text = cards.effect_card_text(item, PT, True, False, False)
    for fragment in ("inbox#3", "2026-10-21T17:00:00Z", "abc123", "/srv/project", "b" * 64, "a" * 64):
        assert fragment not in phone_text, (fragment, phone_text)
    assert "Resposta para: ana@example.com, quem enviou a mensagem: Budget" in phone_text and "Anexo: plan.pdf, 120 bytes" in phone_text      # validate: allow english-only -- the Portuguese line or sentence under test
    terminal = cards.effect_card_text(item, {}, True, False, True)
    for fragment in ("inbox#3", "2026-10-21T17:00:00Z", "abc123", "/srv/project", "b" * 64, "a" * 64):
        assert fragment in terminal, ("vacuity: the terminal keeps", fragment)
    assert terminal == item["body"]


def test_a_file_card_on_a_phone_leaves_off_the_read_time_the_revision_and_the_source(world):
    lines = [["CARD_FILE_CODE_REPLACE", {"read_at": "2026-10-21T17:00:00Z"}], ["CARD_FILE_NAME", {"name": "plan.docx", "service": "google"}],
             ["CARD_FILE_BASE", {"revision": "r17", "modified": "2026-10-20T10:00:00Z"}], ["CARD_FILE_SOURCE", {"source": "drive-main"}],
             ["CARD_FILE_PROJECT", {"path": "/srv/project/plan.docx", "size": "4 KB", "sha_short": "cafe0123"}]]
    item = synthetic(lines)
    phone_text = cards.effect_card_text(item, PT, True, False, False)
    for fragment in ("2026-10-21T17:00:00Z", "r17", "drive-main", "/srv/project", "cafe0123"):
        assert fragment not in phone_text, (fragment, phone_text)
    assert "File: plan.docx" in phone_text or "Arquivo: plan.docx" in phone_text      # validate: allow english-only -- the Portuguese line or sentence under test
    terminal = cards.effect_card_text(item, {}, True, False, True)
    assert all(f in terminal for f in ("2026-10-21T17:00:00Z", "r17", "drive-main", "/srv/project", "cafe0123")), "vacuity: the terminal keeps every line"


# --- the order of the messages -------------------------------------------------------------------------------------------------------------------------


def test_the_bridge_sends_the_line_before_the_card_and_the_card_is_the_last_message():
    bridge = st.load("messaging_bridge")
    sent = []

    class Stub:
        def reply(self, chat, text, project, **kw):
            sent.append(text)
            return True
    lead = "Encontrei: corte de cabelo, Sat 24/10/2026 10:00-11:00. É este?"      # validate: allow english-only -- the Portuguese line or sentence under test
    said = bridge.Bridge.lead_first(Stub(), {}, "chat", {"lead": lead}, lead + "\n" + "O card #1 espera a sua aprovação.")      # validate: allow english-only -- the Portuguese line or sentence under test
    assert sent == [lead] and said == "O card #1 espera a sua aprovação.", "the line goes out first; what is left is the card's notice, which the caller drops after the card"      # validate: allow english-only -- the Portuguese line or sentence under test
    assert bridge.Bridge.lead_first(Stub(), {}, "chat", {}, "O card #1") == "O card #1" and sent == [lead], "vacuity: no lead, nothing is sent"

