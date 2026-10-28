"""A change to the person's own calendar on the messaging channel and the page (package W1): the group `calendar-write` lets a sender PREPARE a card, the grant
`approve-effect-calendar` lets a messaging app APPROVE one, and both are in no default policy. The world is test_calendar_write.py's: the real writers over stand-ins on
loopback, a stand-in tree. What is held here:

  * a messaging sender with no `calendar-write` prepares nothing; with it, the card is made and the sender is told the card waits; nothing is written;
  * the approval from a messaging app needs the grant `approve-effect-calendar` accepted with `--widen` AND the hash of the exact event; another word's grant covers
    nothing here, the card is whole and says every part of the event, and a wrong hash approves nothing;
  * the MCP mode never prepares or approves one, whatever a policy lists; the page prepares with its group and approves, as the terminal does;
  * the umbrella `approve-effects` (the page alone) implies the new group, and a messaging app takes it only as a grant, one word at a time.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_grants_calendar.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import json

import pytest

import phrase_kit as pk
import standin_tree as st
from test_calendar_write import (EVENTS, PIECES, TITLE, approve, create, effect_doc, item_of, made_event, ops, ops_core, operations, rows, world)  # noqa: F401  (the calendar world)
from test_channel_grants import accept

cards = st.load("messaging_cards")
account_start = st.load("account_start")
steps = st.load("steps")
SENDER = "telegram:830461975213"
PT = {"language": "pt-BR"}
CAPS = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}


def card_of(world, started, notices="text"):
    full = ops.pending(world["path"], started["pending"])
    found = ops.config(world["path"])
    return cards.build("office", full, CAPS, found["channels"], notices, None, operations=operations)


def labels(card):
    return [a["label"] for a in card["message"]["actions"]]


def has_label(card, key="EFFECT_LABEL", cfg=None):
    return any(pk.said(label, key, cfg) for label in labels(card))


def prepare(world, channel="messaging", sender=SENDER, **more):
    return ops.event_create(world["path"], "google", TITLE, "2026-10-19T13:00", channel=channel, sender=sender, **more)


def test_a_messaging_sender_prepares_a_card_only_with_the_group_and_nothing_is_written(world):
    with pytest.raises(ops.OpsError) as no:
        prepare(world)
    assert "is not enabled for this channel" in str(no.value) and rows(world) == ([], [])
    accept(world["path"], {"messaging": ["read", "approve-effect-calendar"]})       # the approval grant alone does not let a sender ask
    with pytest.raises(ops.OpsError):
        prepare(world)
    assert rows(world) == ([], [])
    accepted = accept(world["path"], {"messaging": ["read", "calendar-write"]})
    assert [w["group"] for w in accepted["widened"]] == ["calendar-write"] and "calendars" in accepted["widened"][0]["means"]
    started = prepare(world, **PIECES)
    assert started["word"] == "calendar" and started["on_cards"] is True
    pk.assert_said(account_start.reply_text({}, started), "ACCT_CARD_SENT", {}, pending=started["pending"])
    pk.assert_said(account_start.reply_text(PT, started), "ACCT_CARD_SENT", PT, pending=started["pending"])
    assert world["google"].requests == [] and world["graph"].requests == []
    item = item_of(world, started)
    assert item["kind"] == "effect" and TITLE in item["body"] and item["payload_sha256"]


def test_a_sender_who_may_ask_may_not_approve_without_the_grant_and_the_grant_needs_widen_and_the_hash(world):
    accept(world["path"], {"messaging": ["read", "calendar-write"]})
    started = prepare(world)
    full = ops.pending(world["path"], started["pending"])
    assert full["effect_word"] == "calendar" and full["effect_on_cards"] is True
    with pytest.raises(ops.OpsError) as no:
        approve(world, started, "messaging")
    assert "an effect is approved in the terminal, with its hash" in str(no.value) and "approve-effect-calendar" in str(no.value) and world["google"].requests == []
    assert not has_label(card_of(world, started))
    accept(world["path"], {"messaging": ["read", "calendar-write", "approve-effect-write", "approve-effect-send"]})      # another word's grant covers nothing here
    with pytest.raises(ops.OpsError):
        approve(world, started, "messaging")
    assert world["google"].requests == []
    accepted = accept(world["path"], {"messaging": ["read", "calendar-write", "approve-effect-calendar"]})
    assert [w["group"] for w in accepted["widened"]] == ["approve-effect-calendar"] and "event" in accepted["widened"][0]["means"]
    card = card_of(world, started)
    assert has_label(card) and card["whole"] is True and card["approvable"] is True
    for key, fields in (("CARD_CAL_TITLE", {"title": TITLE}), ("CARD_CAL_WHEN", {"when": "Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)"}), ("CARD_CAL_NOBODY", {})):
        pk.assert_said(card["message"]["text"], key, **fields)
    with pytest.raises(ops.OpsError) as wrong:
        ops.approve(world["path"], started["pending"], "0" * 64, channel="messaging", sender=SENDER)
    assert "nothing was approved" in str(wrong.value) and world["google"].requests == []
    done = approve(world, started, "messaging")
    assert done["task_state"] == "done" and done["result"]["event_id"] == "ev0001" and len(world["google"].events) == 1
    [(method, path)] = [(r["method"], r["path"]) for r in world["google"].requests if r["path"] != "/token"]
    assert (method, path) == ("POST", EVENTS)
    with pytest.raises(ops.OpsError):
        approve(world, started, "messaging")
    assert len(world["google"].events) == 1, "created once"
    assert effect_doc(world, started)["event"]["title"] == TITLE


def test_the_notices_of_count_draw_no_approve_action_for_a_calendar_card(world):
    accept(world["path"], {"messaging": ["read", "calendar-write", "approve-effect-calendar"]})
    started = prepare(world)
    assert has_label(card_of(world, started))
    assert not has_label(card_of(world, started, "count")) and TITLE not in card_of(world, started, "count")["message"]["text"]


def test_the_mcp_mode_and_the_conversation_never_prepare_or_approve_a_calendar_change(world):
    for channel in ("mcp", "chat"):
        with pytest.raises(ops.OpsError):
            ops.event_create(world["path"], "google", TITLE, "2026-10-19T13:00", channel=channel)
    assert rows(world) == ([], [])
    started = create(world)
    for channel in ("mcp", "chat", None):
        with pytest.raises(ops.OpsError):
            approve(world, started, channel)
    for channel in ("messaging", "chat"):       # a line typed into say never approves it, on any channel
        reply = ops.say(world["path"], f"/approve {started['pending']} {item_of(world, started)['payload_sha256']}", channel=channel,
                        sender=(SENDER if channel == "messaging" else None))["reply"]
        assert reply == PLAIN_REFUSAL if channel == "messaging" else reply.startswith("error: ")
    assert world["google"].requests == [] and ops.pending(world["path"], started["pending"])["status"] == "open"
    assert approve(world, started, "terminal")["task_state"] == "done"
    assert operations.GRANTS["mcp"] == ("approve-plans", "approve-acceptances", "reject-cancel", "retry")


def test_the_page_prepares_with_its_group_and_approves_and_the_umbrella_implies_the_new_group(world):
    assert "approve-effect-calendar" in operations.IMPLIED["approve-effects"] and "calendar" in operations.EFFECT_APPROVAL_WORDS
    assert operations.GROUPS["calendar-write"] == {"operations": ("event-create", "event-change", "event-cancel"), "kind": None}
    assert operations.GROUPS["approve-effect-calendar"] == {"operations": ("approve",), "kind": "effect:calendar"}
    assert "approve-effect-calendar" in operations.GRANTS["messaging"] and "approve-effect-calendar" not in operations.GRANTS["mcp"]
    assert "calendar-write" not in operations.DEFAULT_POLICY["messaging"] and operations.GROUP_TEXT["calendar-write"].startswith("prepares changes to your own calendars")
    accept(world["path"], {"page": ["read", "approve-effects"]})
    with pytest.raises(ops.OpsError) as no:
        ops.event_create(world["path"], "google", TITLE, "2026-10-19T13:00", channel="page")
    assert "not enabled" in str(no.value)
    accept(world["path"], {"page": ["read", "calendar-write", "approve-effects"]})
    started = ops.event_create(world["path"], "google", TITLE, "2026-10-19T13:00", channel="page")
    assert approve(world, started, "page")["task_state"] == "done" and len(world["google"].events) == 1


def test_a_widening_that_lists_the_calendar_groups_is_shown_in_words_and_changes_nothing_until_accepted(world):
    shown = ops.config(world["path"])
    assert shown["accepted"] is True
    path = world["tmp"] / "project" / "docs" / "workbench" / "runtime.json"
    import json
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["channels"] = {"messaging": ["read", "calendar-write", "approve-effect-calendar"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    after = ops.config(world["path"])
    means = {w["group"]: w["means"] for w in after["widening"]}
    assert set(means) == {"calendar-write", "approve-effect-calendar"}
    assert "prepares changes to your own calendars" in means["calendar-write"] and "event" in means["approve-effect-calendar"]
    with pytest.raises(ops.OpsError):
        prepare(world)
    assert world["google"].requests == []


def card_for(world, started, groups):
    full = ops.pending(world["path"], started["pending"])
    return cards.build("office", full, CAPS, {"messaging": groups}, "text", None, operations=operations, sender=SENDER)


def test_a_change_card_shows_the_events_current_text_on_messaging_only_to_a_sender_who_holds_ask_mail(world):
    made = made_event(world)
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Haircut with Pat", start="2026-10-20T10:00", notes="New notes")
    body = item_of(world, started)["body"]
    assert pk.said(body, "CARD_CAL_BEFORE_TITLE", title=TITLE) and pk.said(body, "CARD_CAL_BEFORE_NOTES", notes="Bring cash") and pk.said(body, "CARD_CAL_KEPT_WHERE", location="Main Street")      # the terminal and the page: all of it
    holder = card_for(world, started, ["read", "approve-effect-calendar", "ask-mail"])
    other = card_for(world, started, ["read", "approve-effect-calendar"])
    assert pk.said(holder["message"]["text"], "CARD_CAL_BEFORE_TITLE", title=TITLE) and holder["approvable"] is True
    text = other["message"]["text"]
    for key, fields in (("CARD_CAL_BEFORE_TITLE", {"title": TITLE}), ("CARD_CAL_BEFORE_NOTES", {"notes": "Bring cash"}), ("CARD_CAL_KEPT_WHERE", {"location": "Main Street"})):
        assert not pk.said(text, key, **fields), key
    assert pk.said(body, "CARD_CAL_NOW_TITLE", title=TITLE) and pk.said(holder["message"]["text"], "CARD_CAL_NOW_TITLE", title=TITLE) and not pk.said(text, "CARD_CAL_NOW_TITLE", title=TITLE)
    assert "Event: ev0001" not in text and "Based on version" not in text and "only if it is still as read at" not in text, "the internals stay off a phone (S16c)"      # literal: a phone card shows no raw event id, snapshot name or version
    for key, fields in (("CARD_CAL_NOW_WHEN", {"when": "Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)"}), ("CARD_CAL_AFTER_TITLE", {"title": "Haircut with Pat"}), ("CARD_CAL_AFTER_NOTES", {"notes": "New notes"}),
                        ("CARD_CAL_BEFORE_WHEN", {"when": "Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)"}), ("CARD_HIDDEN_NOTE", {})):
        pk.assert_said(text, key, **fields)
    assert other["approvable"] is False and not has_label(other), "a card that leaves a line out is not approved where it is partial"
    assert other["content_sha256"] == holder["content_sha256"], "the hash is the effect's, whatever is drawn"
    portuguese = cards.build("office", ops.pending(world["path"], started["pending"]), CAPS, {"messaging": ["read"]}, "text", None, operations=operations, sender=SENDER,
                             cfg={"language": "pt-BR"})["message"]["text"]
    assert pk.said(portuguese, "CARD_HIDDEN_NOTE", PT) and "Evento: ev0001" not in portuguese and pk.said(portuguese, "CARD_CAL_NOW_WHEN", PT) and not pk.said(portuguese, "CARD_CAL_NOW_TITLE", PT)
    assert not pk.said(portuguese, "CARD_CAL_BEFORE_TITLE", PT) and pk.said(portuguese, "CARD_CAL_AFTER_TITLE", PT, title="Haircut with Pat")


def test_a_removal_card_hides_title_place_and_notes_from_a_sender_without_ask_mail_but_not_the_time(world):
    made = made_event(world)
    started = ops.event_cancel(world["path"], "google", f"created:{made['pending']}")
    other = card_for(world, started, ["read", "approve-effect-calendar"])["message"]["text"]
    assert not pk.said(other, "CARD_CAL_DROP_TITLE") and "Main Street" not in other and "Bring cash" not in other
    assert pk.said(other, "CARD_CAL_NOW_WHEN", when="Mon 19/10/2026 13:00-14:00 (America/Sao_Paulo)") and "Event: ev0001" not in other, "the time read live is always there; the id is for the terminal and the page (S16c)"
    assert not pk.said(other, "CARD_CAL_NOW_TITLE"), "the title read live is the person's text: only for a reader of mail and calendar"
    holder = card_for(world, started, ["read", "approve-effect-calendar", "ask-mail"])["message"]["text"]
    assert pk.said(holder, "CARD_CAL_NOW_TITLE", title=TITLE) and pk.said(holder, "CARD_CAL_NOTES", notes="Bring cash") and not pk.said(holder, "CARD_HIDDEN_NOTE") and not pk.said(holder, "CARD_CAL_DROP_TITLE"), "the event is said once on a phone"
    assert cards.build("office", ops.pending(world["path"], started["pending"]), CAPS, {"messaging": ["read", "approve-effect-calendar", "ask-mail"]}, "text", None,
                       operations=operations, sender=None)["approvable"] is False, "no sender, no private text"


def test_a_create_card_has_no_private_line_so_it_is_whole_for_every_sender(world):
    started = create(world, **PIECES)
    card = card_for(world, started, ["read", "approve-effect-calendar"])
    assert card["approvable"] is True and not pk.said(card["message"]["text"], "CARD_HIDDEN_NOTE") and pk.said(card["message"]["text"], "CARD_CAL_TITLE", title=TITLE)


def test_the_task_row_of_a_calendar_write_shows_the_mcp_mode_and_a_reader_without_ask_mail_only_closed_arguments_and_never_a_sender(world):
    accept(world["path"], {"messaging": ["read", "calendar-write"]})
    started = prepare(world, **PIECES)                                   # asked by a messaging sender: the row carries who asked
    mine = create(world, **PIECES)                                       # asked at the terminal
    whole = ops.task(world["path"], started["task"])["task"]
    assert whole["step_args"]["title"] == TITLE and whole["step_args"]["notes"] == "Bring cash" and whole["step_args"]["sender"] == SENDER
    for what in (started, mine):
        for channel, sender in (("mcp", None), ("messaging", "telegram:777"), ("messaging", None), ("messaging", SENDER)):
            shown = ops.task(world["path"], what["task"], channel=channel, sender=sender)["task"]
            assert set(shown["step_args"]) <= set(steps.ACCOUNT_ARGS_SHOWN), (channel, sender)
            seen = json.dumps(shown)
            for word in (TITLE, "Bring cash", "Main Street", "830461975213"):
                assert word not in seen, (channel, sender, word)
            assert shown["step_args"]["operation"] == "create" and shown["step_kind"] == "calendar-event"
