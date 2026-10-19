"""W1, the re-check of the calendar write: what a calendar card, a reference and a plan may carry or show, and to whom.

The private text of an event (its title, place and notes) is shown on messaging only to a reader who holds `ask-mail`, per reader; the MCP mode never gets it; a
`created:` reference is for the sender who asked for the event (or a reader of the person's mail and calendar) and answers one neutral sentence otherwise; a
flow or a plan cannot carry a calendar-event step around the one entry for account writes; a renumbered snapshot never moves a re-prepared card onto another
event. Fictional names only; a fake server on loopback; nothing here reaches a real account.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import standin_tree as st
from test_calendar_write import (SEEDED, approve, effect_doc, fgw, install_item_refs, item_of, made_event, ops, ops_core, ops_steps, operations, phrases, rows, seed_google,  # noqa: F401
                                 snapshot_event, steps, world)
from test_channel_grants import accept

cards = st.load("messaging_cards")
ops_grants = st.load("ops_grants")
SENDER = "telegram:4242"
OTHER = "telegram:9999"
CAPS = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}
SECRET_TITLE = "Therapy with Dr Example"


def card_for(world, pending, groups, sender=SENDER):
    full = ops.pending(world["path"], pending)
    return cards.build("office", full, CAPS, {"messaging": groups}, "text", None, operations=operations, sender=sender)


# --- MAJOR-1 (a), (b): the title read live is private; per reader ------------------------------------------------------------------------


def test_the_time_and_the_id_of_the_event_are_not_private_but_its_title_is_and_it_is_drawn_per_reader(world):
    made = made_event(world, title=SECRET_TITLE)
    accept(world["path"], {"messaging": ["read", "calendar-write"]})
    started = ops.event_cancel(world["path"], "google", f"created:{made['pending']}", channel="terminal")
    other = card_for(world, started["pending"], ["read", "approve-effect-calendar"], sender=OTHER)["message"]["text"]
    holder = card_for(world, started["pending"], ["read", "approve-effect-calendar", "ask-mail"], sender=OTHER)["message"]["text"]
    assert "Event: ev0001" in other and "The event now is at: Mon 19/10/2026 13:00-14:00" in other
    assert SECRET_TITLE not in other and "The event now:" not in other
    assert f"The event now: {SECRET_TITLE}" in holder, "the reader who holds ask-mail sees it, whoever created the card"


# --- MAJOR-1 (c): the MCP mode never gets the private lines --------------------------------------------------------------------------------


def test_the_mcp_channel_gets_no_private_line_of_a_calendar_card_from_pending_or_task(world):
    made = made_event(world, title=SECRET_TITLE)
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="X")
    terminal = ops.pending(world["path"], started["pending"])["body"]
    assert f"The event now: {SECRET_TITLE}" in terminal and "Before: Title: " + SECRET_TITLE in terminal, "the terminal and the page read all of it"
    for channel in ("mcp",):
        shown = ops.pending(world["path"], started["pending"], channel=channel)
        assert SECRET_TITLE not in json.dumps(shown), channel
        assert "The event now is at:" in shown["body"], "the id and the time stay"
        listed = ops.pending(world["path"], channel=channel)
        assert SECRET_TITLE not in json.dumps(listed), channel
        assert SECRET_TITLE not in json.dumps(ops.task(world["path"], started["task"], channel=channel)), channel
    assert SECRET_TITLE not in json.dumps(ops.pending(world["path"], started["pending"], channel="messaging", sender=SENDER)), "no sender, no right: nothing private"


def test_the_pending_and_task_rows_carry_the_channel_so_that_a_shell_cannot_leave_it_out():
    for name in ("pending", "task"):
        assert operations.by_name(name).get("channel_arg") is True, name


# --- MAJOR-1 (d): a created reference is for whoever asked, answered neutrally ------------------------------------------------------------


def test_a_created_reference_from_messaging_is_for_the_sender_who_asked_for_the_event_or_a_reader_of_the_calendar(world):
    accept(world["path"], {"messaging": ["read", "calendar-write"]})
    own = ops.event_create(world["path"], "google", SECRET_TITLE, "2026-10-21T12:00", channel="messaging", sender=SENDER)
    approve(world, own)
    assert effect_doc(world, own)["asker"] == SENDER
    ok = ops.event_cancel(world["path"], "google", f"created:{own['pending']}", channel="messaging", sender=SENDER)
    assert ok["pending"]
    with pytest.raises(ops.OpsError) as other:
        ops.event_cancel(world["path"], "google", f"created:{own['pending']}", channel="messaging", sender=OTHER)
    terminal = made_event(world, title="Dentist visit")
    with pytest.raises(ops.OpsError) as person:
        ops.event_cancel(world["path"], "google", f"created:{terminal['pending']}", channel="messaging", sender=SENDER)
    with pytest.raises(ops.OpsError) as nothing:
        ops.event_cancel(world["path"], "google", "created:999", channel="messaging", sender=SENDER)
    assert str(other.value) == str(person.value) == str(nothing.value), "one sentence, whether the guess matched or not"
    assert ops.event_cancel(world["path"], "google", f"created:{terminal['pending']}", channel="terminal")["pending"], "the person at the terminal asked for it"


def test_the_answer_nothing_to_change_does_not_tell_a_guess_of_the_title_right_to_a_stranger(world):
    made = made_event(world, title=SECRET_TITLE)
    accept(world["path"], {"messaging": ["read", "calendar-write"]})
    answers = []
    for guess in (SECRET_TITLE, "A wrong guess"):
        with pytest.raises(ops.OpsError) as why:
            ops.event_change(world["path"], "google", f"created:{made['pending']}", title=guess, channel="messaging", sender=OTHER)
        answers.append(str(why.value))
    assert answers[0] == answers[1], "the same neutral sentence, matched or not"
    assert SECRET_TITLE not in answers[0] and "13:00" not in answers[0]


# --- MINOR-1: a flow or a plan cannot carry a calendar-event step ---------------------------------------------------------------------------


def test_a_plan_cannot_carry_a_step_whose_gate_word_is_an_account_write():
    for channel in ("terminal", "messaging"):
        args = {"account": "google", "operation": "change", "event": "cal#1", "title": "x", "channel": channel}
        if channel == "messaging":
            args["sender"] = SENDER
        with pytest.raises(steps.StepFailure) as why:
            steps.plan_task("calendar-event", args, key="k", title="t", text="x")
        assert why.value.code == "not_plannable"
    import account_start
    assert set(steps.ACCOUNT_WORDS) | {"send"} == set(account_start.WORDS), "the list of the plan check is the one the account entry uses; `send` is a plain kind too, its account arguments are refused by ACCOUNT_ARGS (W2)"


def test_a_project_flow_with_a_calendar_event_step_is_refused_when_it_is_planned(world, monkeypatch):
    install_item_refs(world, monkeypatch, {"cal#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    seed_google(world)
    folder = Path(world["path"]) / "docs" / "workbench" / "flows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "calfix.json").write_text(json.dumps({"flow": "calfix", "title": "Rename an event", "params": {"ev": {"description": "the event", "type": "text"}},
        "tasks": [{"key": "rename", "step": "calendar-event", "args": {"account": "google", "operation": "change", "event": "{ev}", "title": "Renamed", "channel": "terminal"},
                   "title": "Rename", "text": "Rename it.", "depends_on": [], "milestone": True}]}))
    tree = Path(world["tree"])
    for rel in ("scripts/select_skills.py", "scripts/validate.py", "scripts/security_scan.py", "scripts/redact.py"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(st.REPO / rel, tree / rel)
    if not (tree / "packs").exists():
        shutil.copytree(st.REPO / "packs", tree / "packs")
    request = ops.request(world["path"], "rename my event")
    with pytest.raises(ops.OpsError) as why:
        ops.route(world["path"], request["request"], flow="calfix", channel="mcp", params=["ev=cal#1"])
    assert "not_plannable" in str(why.value)
    assert world["google"].requests == []


def test_a_calendar_event_step_without_a_channel_never_means_full_read_rights(world, monkeypatch):
    from test_calendar_write import step_calendar_event
    install_item_refs(world, monkeypatch, {"cal#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    seed_google(world)
    with pytest.raises(Exception):
        step_calendar_event.check({"account": "google", "operation": "change", "event": "cal#1", "title": "x"})


# --- MINOR-2: a re-prepare after a stale card never moves to another event ------------------------------------------------------------------


def test_a_renumbered_snapshot_does_not_move_a_re_prepared_card_onto_another_event(world, monkeypatch):
    snaps = install_item_refs(world, monkeypatch, {"cal#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    seed_google(world)
    world["google"].add_event("evother999", "Other", {"dateTime": "2026-10-20T09:00:00-03:00"}, {"dateTime": "2026-10-20T10:00:00-03:00"})
    started = ops.event_change(world["path"], "google", "cal#1", title="Renamed")
    assert effect_doc(world, started)["event_id"] == SEEDED
    world["google"].events[SEEDED]["etag"] = world["google"].next_etag()
    snaps.providers.events[("google", fgw.CALENDAR)] = [snapshot_event(1, "evother999", title="Other"), snapshot_event(2, SEEDED)]
    snaps.later(minutes=5)
    snaps.refresh("cal")
    with pytest.raises(ops.OpsError):
        approve(world, started)
    out = ops_steps.run_step(world["path"], started["task"])
    assert out["ok"] is False and out["code"] == "not_eligible" and out["field"] == "reference"
    assert "name the event again" in out["next"]
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_list(ctx["conn"], "open", started["task"]) == [], "no new card for the other event"
    assert all(r["method"] != "PATCH" for r in world["google"].requests)


# --- MINOR-3: an unknown channel reaches may_read and is refused there -----------------------------------------------------------------------


@pytest.mark.parametrize("channel", ["chat", "Terminal", "web", ""])
def test_an_unknown_channel_is_refused_and_nothing_is_read_or_written(world, monkeypatch, channel):
    install_item_refs(world, monkeypatch, {"cal#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    seed_google(world)
    with pytest.raises(ops.OpsError):
        ops.event_change(world["path"], "google", "cal#1", title="X", channel=channel)
    assert all(r["method"] not in ("PATCH", "DELETE", "POST") or "token" in r["path"] for r in world["google"].requests)
    assert rows(world)[1] == []


# --- NIT-1, NIT-2 ------------------------------------------------------------------------------------------------------------------------


def test_the_calendar_id_of_a_created_event_is_recorded_and_compared_on_use(world):
    made = made_event(world, title=SECRET_TITLE)
    result = item_of(world, made)["payload"]["result"]
    assert isinstance(result["calendar_id"], str) and result["calendar_id"] == fgw.CALENDAR
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Other")
    assert effect_doc(world, started)["calendar_id"] == fgw.CALENDAR


def test_a_reference_refusal_names_the_reference_not_the_calendar(world):
    with pytest.raises(ops.OpsError) as why:
        ops.event_change(world["path"], "google", "created:999", title="X")
    assert "refused reference" in str(why.value) and "calendar --" not in str(why.value)


# --- the executed result of a created event names the sender who asked: for that sender only (W2 follow-up of the W4a re-check) -------------------------------


def test_the_result_of_a_created_event_shows_the_messaging_sender_who_asked_to_no_other_reader_not_even_a_reader_of_the_calendar(world, monkeypatch):
    accept(world["path"], {"messaging": ["read", "calendar-write"]})
    own = ops.event_create(world["path"], "google", "Haircut", "2026-10-21T12:00", channel="messaging", sender=SENDER)
    approve(world, own)
    assert effect_doc(world, own)["asker"] == SENDER
    whole = ops.pending(world["path"], own["pending"])
    assert whole["payload"]["result"]["asker"] == SENDER and whole["payload"]["result"]["operation"] == "create", "the terminal and the page read the record whole"
    readers = (("mcp", None), ("messaging", OTHER), ("messaging", None))

    def views(channel, sender):
        return (ops.pending(world["path"], own["pending"], channel=channel, sender=sender),
                next(p for p in ops.task(world["path"], own["task"], channel=channel, sender=sender)["pending"] if p["id"] == own["pending"]))
    for channel, sender in readers:
        for shown in views(channel, sender):
            result = shown["payload"]["result"]
            assert "asker" not in result and result["event_id"] and result["operation"] == "create", (channel, sender)
            assert SENDER not in json.dumps(shown), (channel, sender)
    for shown in views("messaging", SENDER):
        assert shown["payload"]["result"]["asker"] == SENDER, "the sender who asked reads their own id"
    monkeypatch.setattr(ops_grants.item_refs, "may_read", lambda *a, **k: True)      # a reader of the person's own mail and calendar
    for channel, sender in readers:
        for shown in views(channel, sender):
            assert "asker" not in shown["payload"]["result"] and SENDER not in json.dumps(shown), (channel, sender)
    assert ops.pending(world["path"], own["pending"], channel="terminal")["payload"]["result"]["asker"] == SENDER
    terminal = made_event(world, title="Dentist visit")
    assert "asker" not in ops.pending(world["path"], terminal["pending"], channel="mcp")["payload"]["result"], "always, also when the asker was the terminal"
    assert ops.pending(world["path"], terminal["pending"], channel="page")["payload"]["result"]["asker"] == "terminal"


# --- a card with the current text of an event is approved from messaging only by a reader of the calendar, at the operations layer too ---------------------------------


def test_the_cancel_card_of_an_event_is_not_approved_from_messaging_by_a_sender_who_may_not_read_the_calendar_and_is_by_a_reader(world, monkeypatch):
    accept(world["path"], {"messaging": ["read", "calendar-write", "approve-effect-calendar"]})
    own = ops.event_create(world["path"], "google", SECRET_TITLE, "2026-10-21T12:00", channel="messaging", sender=SENDER)
    assert approve(world, own, "messaging")["task_state"] == "done", "the card of a new event carries only what the sender wrote"
    cancel = ops.event_cancel(world["path"], "google", f"created:{own['pending']}", channel="messaging", sender=SENDER)
    item = item_of(world, cancel)
    assert ops_grants.has_private_lines(item), "the card shows the title as the service holds it now"
    with pytest.raises(ops.OpsError) as no:
        approve(world, cancel, "messaging")
    assert "ask-mail" in str(no.value) and item_of(world, cancel)["status"] == "open"
    with pytest.raises(ops.OpsError):
        approve(world, cancel, "mcp")
    monkeypatch.setattr(ops_grants.item_refs, "may_read", lambda ctx, channel, sender=None: channel == "messaging")      # a sender who holds `ask-mail`
    assert approve(world, cancel, "messaging")["task_state"] == "done"


def test_the_private_lines_of_a_calendar_card_show_and_approve_for_the_sender_whose_own_profile_lists_ask_mail_alone(world):
    """The real configuration (NR-2): `ask-mail` is in one listed sender's own profile, never in the channel's list; the card is drawn from that policy."""
    from test_channel_grants_mailbox import accept as accept_holder      # the channel keeps the list without ask-mail; SENDER's profile `holder` lists it
    made = made_event(world, title=SECRET_TITLE)
    accept_holder(world["path"], {"messaging": ["read", "calendar-write", "approve-effect-calendar", "ask-mail"]})
    started = ops.event_cancel(world["path"], "google", f"created:{made['pending']}", channel="terminal")
    channels = ops.config(world["path"])["channels"]
    full = ops.pending(world["path"], started["pending"])
    holder = cards.build("office", full, CAPS, channels, "text", None, operations=operations, sender=SENDER)
    other = cards.build("office", full, CAPS, channels, "text", None, operations=operations, sender=OTHER)
    assert f"The event now: {SECRET_TITLE}" in holder["message"]["text"] and holder["approvable"] is True
    assert SECRET_TITLE not in other["message"]["text"] and other["approvable"] is False, "the same channel, another sender: a partial card, not approved from here"


def test_the_private_card_of_a_calendar_change_a_holder_reads_is_not_kept_in_the_conversation_the_mcp_mode_reads(world):
    """A messaging read of the card drawn for a holder of `ask-mail` (the title of the event as it is now) goes to that chat alone; the conversation keeps a neutral word."""
    from test_channel_grants_mailbox import accept as accept_holder      # the channel keeps the list without ask-mail; SENDER's profile `holder` lists it
    made = made_event(world, title=SECRET_TITLE)
    accept_holder(world["path"], {"messaging": ["read", "talk", "calendar-write", "ask-mail"]})
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="X", channel="messaging", sender=SENDER)
    neutral = phrases.text("NAT_READ_REPLY", None)
    typed = ops.say(world["path"], f"/pending {started['pending']}", channel="messaging", sender=SENDER)
    assert SECRET_TITLE in typed["reply"], "the holder reads the whole card"
    ops.say(world["path"], f"task {started['task']}", channel="messaging", sender=SENDER)
    messages = ops.conversation(world["path"], channel="mcp")["messages"]
    assert [m["text"] for m in messages if m["role"] == "assistant"] == [neutral, neutral]
    assert not any(SECRET_TITLE in m["text"] for m in messages)
