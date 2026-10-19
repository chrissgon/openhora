"""A change to the person's own mailbox on the messaging channel and the page (package W3): the group `mail-organize` lets a sender PREPARE a card, the grant
`approve-effect-mailbox` lets a messaging app APPROVE one, and both are in no default policy. Naming a message by a reference into a snapshot of the mailbox needs the group
`ask-mail` (limit L-snapshot of package SNAP-IDX), and the card shows the subject and sender of each message only to a sender who holds it. The world is
test_mailbox_write.py's: the real writers over stand-ins on loopback, a stand-in tree, a real snapshot of a mail source. The group `ask-mail` is the answer from mail and
calendar of package NR-2, which this checkout does not have yet: the tests give the table a stand-in of it (a group over the operation `ask`), as the reference code expects one.
What is held here:

  * a messaging sender with no `mail-organize` prepares nothing; with it but without `ask-mail` it cannot name a message; with both the card is made and the sender is told the
    card waits; nothing is written;
  * the approval from a messaging app needs the grant `approve-effect-mailbox` accepted with `--widen` AND the hash of the exact content; another word's grant covers nothing
    here; and the card the approver sees must be whole: a sender who does not hold `ask-mail` is shown no subject and no sender, and so is offered no approval;
  * the MCP mode never prepares or approves one, whatever a policy lists; the page prepares with its group and approves, as the terminal does;
  * the umbrella `approve-effects` (the page alone) implies the new group, and a messaging app takes it only as a grant;
  * every card of every action is said line by line in Portuguese, with the same hash as in English.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_grants_mailbox.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import standin_tree as st
from test_mailbox_write import NEW_DRAFT, approve, archive, effect_doc, item_of, ops, ops_core, operations, phrases, rows, world  # noqa: F401  (the mailbox world: `world` is a fixture the tests below use)
from test_channel_grants import accept as accept_channels

HOLDER = {"telegram": [{"id": "4242", "policy": "holder"}]}


def accept(path, channels, **extra):
    """`test_channel_grants.accept`, with the group `ask-mail` where it can be given: in the profile of the listed sender (SENDER), never to a whole channel (the
    configuration refuses it there). A list of the channel that names it becomes the profile `holder` of SENDER and the channel keeps the list without it."""
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw.pop("policies", None)
    raw.pop("messaging", None)
    channels = dict(channels or {})
    if "ask-mail" in (channels.get("messaging") or ()):
        raw["policies"] = {"holder": list(channels["messaging"])}
        raw["messaging"] = {"senders": HOLDER}
        channels["messaging"] = [g for g in channels["messaging"] if g != "ask-mail"]
    file.write_text(json.dumps(raw))
    return accept_channels(path, channels, **extra)

cards = st.load("messaging_cards")
account_start = st.load("account_start")
SENDER = "telegram:4242"
OTHER = "telegram:777"
CAPS = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}
EXPENSIVE = "Approve this exact content"


@pytest.fixture
def desk(world, monkeypatch):
    """The mailbox world; the group `ask-mail` (NR-2) is the real one."""
    return world


def labels(card):
    return [a["label"] for a in card["message"]["actions"]]


def card_for(world, started, groups, sender=SENDER, cfg=None, notices="text"):
    full = ops.pending(world["path"], started["pending"])
    return cards.build("office", full, CAPS, {"messaging": groups}, notices, None, operations=operations, sender=sender, cfg=cfg)


def prepare(world, refs="inbox#1,inbox#2", sender=SENDER):
    return ops.mail_archive(world["path"], "google", refs, channel="messaging", sender=sender)


def test_a_messaging_sender_prepares_a_card_only_with_the_group_and_may_name_a_message_only_with_ask_mail_and_nothing_is_written(desk):
    with pytest.raises(ops.OpsError) as no:
        prepare(desk)
    assert "is not enabled for this channel" in str(no.value) and rows(desk) == ([], [])
    accept(desk["path"], {"messaging": ["read", "approve-effect-mailbox"]})       # the approval grant alone does not let a sender ask
    with pytest.raises(ops.OpsError):
        prepare(desk)
    assert rows(desk) == ([], [])
    accepted = accept(desk["path"], {"messaging": ["read", "mail-organize"]})
    assert [w["group"] for w in accepted["widened"]] == ["mail-organize"] and "mailbox" in accepted["widened"][0]["means"]
    with pytest.raises(ops.OpsError) as unreadable:
        prepare(desk)
    assert "this channel may not read it" in str(unreadable.value) and "ask-mail" in str(unreadable.value) and rows(desk) == ([], []) and desk["google"].requests == []
    accept(desk["path"], {"messaging": ["read", "mail-organize", "ask-mail"]})
    started = prepare(desk)
    assert started["word"] == "mailbox" and started["on_cards"] is True and account_start.reply_text({}, started) == f"Card #{started['pending']} waits for your approval."
    assert account_start.reply_text({"language": "pt-BR"}, started) == f"O card #{started['pending']} espera a sua aprova\u00e7\u00e3o."
    assert desk["google"].writes() == []
    item = item_of(desk, started)
    assert item["kind"] == "effect" and "Appointment confirmed for Monday" in item["body"] and item["payload_sha256"]


def test_a_sender_who_may_ask_may_not_approve_without_the_grant_and_the_grant_needs_widen_and_the_hash(desk):
    accept(desk["path"], {"messaging": ["read", "mail-organize", "ask-mail"]})
    started = prepare(desk)
    full = ops.pending(desk["path"], started["pending"])
    assert full["effect_word"] == "mailbox" and full["effect_on_cards"] is True
    with pytest.raises(ops.OpsError) as no:
        approve(desk, started, "messaging")
    assert "an effect is approved in the terminal, with its hash" in str(no.value) and "approve-effect-mailbox" in str(no.value) and desk["google"].writes() == []
    assert EXPENSIVE not in labels(card_for(desk, started, ["read", "ask-mail", "mail-organize"]))
    accept(desk["path"], {"messaging": ["read", "mail-organize", "ask-mail", "approve-effect-write", "approve-effect-send"]})      # another word's grant covers nothing here
    with pytest.raises(ops.OpsError):
        approve(desk, started, "messaging")
    assert desk["google"].writes() == []
    accepted = accept(desk["path"], {"messaging": ["read", "mail-organize", "ask-mail", "approve-effect-mailbox"]})
    assert {w["group"] for w in accepted["widened"]} == {"approve-effect-mailbox"} and "mailbox" in accepted["widened"][0]["means"]      # the channel's list and the holder's profile both widen
    card = card_for(desk, started, ["read", "ask-mail", "approve-effect-mailbox"])
    assert EXPENSIVE in labels(card) and card["whole"] is True and card["approvable"] is True
    for line in ("Archive: 2 message(s)", "1. 2026-10-17 06:00 · from ana@clinic.example · Appointment confirmed for Monday", "Read from your mailbox at"):
        assert line in card["message"]["text"], line
    with pytest.raises(ops.OpsError) as wrong:
        ops.approve(desk["path"], started["pending"], "0" * 64, channel="messaging", sender=SENDER)
    assert "nothing was approved" in str(wrong.value) and desk["google"].writes() == []
    done = approve(desk, started, "messaging")
    assert done["task_state"] == "done" and done["result"]["count"] == 2 and len(desk["google"].writes()) == 1
    with pytest.raises(ops.OpsError):
        approve(desk, started, "messaging")
    assert len(desk["google"].writes()) == 1, "changed once"


def test_a_sender_who_does_not_hold_ask_mail_is_shown_no_subject_and_no_sender_and_is_offered_no_approval(desk):
    started = ops.mail_archive(desk["path"], "google", "inbox#1,inbox#2")
    body = item_of(desk, started)["body"]
    assert "Appointment confirmed for Monday" in body and "ana@clinic.example" in body, "the terminal and the page show all of it"
    holder = card_for(desk, started, ["read", "approve-effect-mailbox", "ask-mail"])
    other = card_for(desk, started, ["read", "approve-effect-mailbox"], sender=OTHER)
    assert "Appointment confirmed for Monday" in holder["message"]["text"] and holder["approvable"] is True and EXPENSIVE in labels(holder)
    text = other["message"]["text"]
    for hidden in ("Appointment confirmed", "Your order", "ana@clinic.example", "bob@shop.example"):
        assert hidden not in text, hidden
    for shown in ("Archive: 2 message(s)", "Account: google", "Read from your mailbox at", "Some of the addresses, subjects and text of the e-mail are not shown here"):
        assert shown in text, shown
    assert other["approvable"] is False and EXPENSIVE not in labels(other), "a card that leaves a line out is not approved where it is partial"
    assert other["content_sha256"] == holder["content_sha256"], "the hash is the effect's, whatever is drawn"
    assert cards.build("office", ops.pending(desk["path"], started["pending"]), CAPS, {"messaging": ["read", "approve-effect-mailbox", "ask-mail"]}, "text", None,
                       operations=operations, sender=None)["approvable"] is False, "no sender, no private text"
    portuguese = card_for(desk, started, ["read"], sender=OTHER, cfg={"language": "pt-BR"})["message"]["text"]
    assert "Parte dos endere\u00e7os, dos assuntos e do texto do e-mail n\u00e3o aparece aqui" in portuguese and "Arquivar: 2 mensagem(ns)" in portuguese and "Appointment" not in portuguese


def test_a_draft_card_hides_the_message_it_answers_from_a_sender_without_ask_mail_but_not_the_drafts_own_words(desk):
    started = ops.mail_draft(desk["path"], "google", message="inbox#1", body="Thanks, Monday works.\n")
    other = card_for(desk, started, ["read", "approve-effect-mailbox"], sender=OTHER)["message"]["text"]
    for hidden in ("Reply to:", "Appointment confirmed", "ana@clinic.example", "desk@clinic.example", "The message asks replies to go to", "To:", "Subject:"):
        assert hidden not in other, hidden
    assert "Thanks, Monday works." not in other and "Some of the addresses, subjects and text of the e-mail are not shown here" in other, "the draft's words are the mail's: not shown, and the card says so"
    assert "Approve exactly" not in other and "not shown here" in other
    assert card_for(desk, started, ["read", "approve-effect-mailbox"], sender=OTHER)["approvable"] is False
    holder_card = card_for(desk, started, ["read", "approve-effect-mailbox", "ask-mail"])
    holder = holder_card["message"]["text"]
    assert holder_card["approvable"] is True and "To: ana@clinic.example" in holder and "Subject: Re: Appointment confirmed for Monday" in holder
    assert "Reply to: ana@clinic.example, the sender of inbox#1" in holder and "The message asks replies to go to desk@clinic.example" in holder
    own = ops.mail_draft(desk["path"], "google", **NEW_DRAFT)
    plain = card_for(desk, own, ["read", "approve-effect-mailbox"], sender=OTHER)
    assert plain["approvable"] is False and "Hello Joe," not in plain["message"]["text"] and "joe@shop.example" not in plain["message"]["text"] and "Haircut" not in plain["message"]["text"]
    assert "not shown here" in plain["message"]["text"], "a new draft's addresses, subject and text are private too: shown, and approved from messaging, only to a reader of the mail"
    holder_plain = card_for(desk, own, ["read", "approve-effect-mailbox", "ask-mail"])
    assert holder_plain["approvable"] is True and "Hello Joe," in holder_plain["message"]["text"] and "joe@shop.example" in holder_plain["message"]["text"]


def test_the_notices_of_count_draw_no_approve_action_and_no_subject_for_a_mailbox_card(desk):
    started = ops.mail_archive(desk["path"], "google", "inbox#1")
    counted = card_for(desk, started, ["read", "approve-effect-mailbox", "ask-mail"], notices="count")
    assert EXPENSIVE not in labels(counted) and "Appointment" not in counted["message"]["text"]


def test_the_mcp_mode_and_the_conversation_never_prepare_or_approve_a_mailbox_change(desk):
    for channel in ("mcp", "chat"):
        with pytest.raises(ops.OpsError):
            ops.mail_archive(desk["path"], "google", "inbox#1", channel=channel)
    assert rows(desk) == ([], [])
    started = archive(desk)
    for channel in ("mcp", "chat", None):
        with pytest.raises(ops.OpsError):
            approve(desk, started, channel)
    for channel in ("messaging", "chat"):       # a line typed into say never approves it, on any channel
        reply = ops.say(desk["path"], f"/approve {started['pending']} {item_of(desk, started)['payload_sha256']}", channel=channel, sender=(SENDER if channel == "messaging" else None))["reply"]
        assert reply.startswith("error: ")
    assert desk["google"].writes() == [] and ops.pending(desk["path"], started["pending"])["status"] == "open"
    assert approve(desk, started, "terminal")["task_state"] == "done"
    assert operations.GRANTS["mcp"] == ("approve-plans", "approve-acceptances", "reject-cancel", "retry")


def test_the_page_prepares_with_its_group_and_approves_and_the_umbrella_implies_the_new_group(desk):
    assert "approve-effect-mailbox" in operations.IMPLIED["approve-effects"] and "mailbox" in operations.EFFECT_APPROVAL_WORDS
    assert operations.GROUPS["mail-organize"] == {"operations": ("mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash"), "kind": None}
    assert operations.GROUPS["approve-effect-mailbox"] == {"operations": ("approve",), "kind": "effect:mailbox"}
    assert "approve-effect-mailbox" in operations.GRANTS["messaging"] and "approve-effect-mailbox" not in operations.GRANTS["mcp"]
    assert "mail-organize" not in operations.DEFAULT_POLICY["messaging"] and operations.GROUP_TEXT["mail-organize"].startswith("prepares changes to your mailbox")
    accept(desk["path"], {"page": ["read", "approve-effects"]})
    with pytest.raises(ops.OpsError) as no:
        ops.mail_archive(desk["path"], "google", "inbox#1", channel="page")
    assert "not enabled" in str(no.value)
    accept(desk["path"], {"page": ["read", "mail-organize", "approve-effects"]})
    started = ops.mail_archive(desk["path"], "google", "inbox#1", channel="page")
    assert approve(desk, started, "page")["task_state"] == "done" and len(desk["google"].writes()) == 1


def test_a_widening_that_lists_the_mailbox_groups_is_shown_in_words_and_changes_nothing_until_accepted(desk):
    assert ops.config(desk["path"])["accepted"] is True
    path = Path(desk["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["channels"] = {"messaging": ["read", "mail-organize", "approve-effect-mailbox"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    after = ops.config(desk["path"])
    means = {w["group"]: w["means"] for w in after["widening"]}
    assert set(means) == {"mail-organize", "approve-effect-mailbox"}
    assert "prepares changes to your mailbox" in means["mail-organize"] and "mailbox" in means["approve-effect-mailbox"] and "ask-mail" in means["approve-effect-mailbox"]
    with pytest.raises(ops.OpsError):
        prepare(desk)
    assert desk["google"].requests == []


# --- every card, in two languages -----------------------------------------------------------------------------------------------------------------------


def test_every_card_of_every_action_is_said_line_by_line_in_portuguese_with_the_same_hash_and_the_english_lines_are_the_stored_body(desk):
    made = [archive(desk), ops.mail_move(desk["path"], "google", "inbox#1", "bills"), ops.mail_mark(desk["path"], "google", "inbox#3", "read"),
            ops.mail_trash(desk["path"], "google", "inbox#2"), ops.mail_trash(desk["path"], "microsoft", "work#1"),
            ops.mail_move(desk["path"], "microsoft", "work#2", "bills"), ops.mail_mark(desk["path"], "microsoft", "work#3", "read"), ops.mail_draft(desk["path"], "google", **NEW_DRAFT),
            ops.mail_draft(desk["path"], "google", message="inbox#1", body="Yes.\n")]
    for each in made:
        item = item_of(desk, each)
        assert phrases.card_valid(item["payload"]["card"]) and cards.effect_card_text(item, {}) == item["body"] == phrases.card_text(item["payload"]["card"])
        portuguese = cards.effect_card_text(item, {"language": "pt-BR"})
        assert portuguese != item["body"] and portuguese.splitlines()[0].startswith("O c\u00f3digo ")
        for key, _ in item["payload"]["card"]:
            assert key in phrases.TABLE["pt-BR"] and key.startswith("CARD_")
        full = ops.pending(desk["path"], each["pending"])
        pt = cards.build("northwind", full, CAPS, {"messaging": ["read", "ask-mail", "approve-effect-mailbox"]}, "text", None, operations=operations, effect_command="cmd",
                         sender=SENDER, cfg={"language": "pt-BR"})
        en = cards.build("northwind", full, CAPS, {"messaging": ["read", "ask-mail", "approve-effect-mailbox"]}, "text", None, operations=operations, effect_command="cmd", sender=SENDER, cfg={})
        assert pt["content_sha256"] == en["content_sha256"] and full["payload_sha256"] in pt["message"]["text"] and pt["approvable"] is True and pt["whole"] is True
    portuguese = cards.effect_card_text(item_of(desk, made[0]), {"language": "pt-BR"})
    for needle in ("Conta: google (pat@example.com)", "Arquivar: 2 mensagem(ns)", "1. 2026-10-17 06:00 · de ana@clinic.example · Appointment confirmed for Monday", "Lidas na sua caixa de e-mail em"):
        assert needle in portuguese, needle
    draft = cards.effect_card_text(item_of(desk, made[7]), {"language": "pt-BR"})
    for needle in ("Para: joe@shop.example", "C\u00f3pia: amy@shop.example", "Cco: boss@shop.example", "Assunto: Haircut on Monday", "O texto do rascunho, exatamente como ser\u00e1 salvo (cada linha come\u00e7a com \u2502):\n\u2502 Hello Joe,"):
        assert needle in draft, needle


# --- the mechanism W1 established, held for the mailbox as well ------------------------------------------------------------------------------------------------


def test_the_mcp_mode_and_a_messaging_reader_without_ask_mail_are_shown_a_mailbox_card_without_its_private_lines(desk):
    started = ops.mail_archive(desk["path"], "google", "inbox#1,inbox#2")
    full = ops.pending(desk["path"], started["pending"])
    assert "Appointment confirmed for Monday" in full["body"] and "ana@clinic.example" in full["body"], "the terminal and the page read all of it"
    for channel, sender in (("mcp", None), ("messaging", OTHER)):
        view = ops.pending(desk["path"], started["pending"], channel=channel, sender=sender)
        text = view["body"] + json.dumps(view["payload"])
        for hidden in ("Appointment confirmed", "Your order", "ana@clinic.example", "bob@shop.example"):
            assert hidden not in text, (channel, hidden)
        assert "Archive: 2 message(s)" in view["body"] and "not shown here" in view["body"] and view["payload_sha256"] == full["payload_sha256"]
    reply = ops.mail_draft(desk["path"], "google", message="inbox#1", body="Yes.\n")
    seen = ops.pending(desk["path"], reply["pending"], channel="mcp")["body"]
    assert "Yes." not in seen and "ana@clinic.example" not in seen and "Appointment" not in seen and "desk@clinic.example" not in seen


def test_a_plan_or_a_flow_cannot_start_a_mailbox_change_only_its_own_operation_does(desk):
    steps = st.load("steps")
    entry = {"ref": "inbox#1", "id": "m1", "snapshot_at": "2026-10-17T09:00:00Z"}
    args = {"account": "google", "action": "archive", "messages": [entry]}
    with pytest.raises(steps.StepFailure) as why:
        steps.plan_task("mailbox-change", args, key="a", title="t", text="x")
    assert why.value.code == "not_plannable"
    ctx = ops_core.context(desk["path"])
    with pytest.raises(steps.StepFailure) as again:
        steps.add_task(ctx["store"], ctx["conn"], "mailbox-change", args, key="mail-archive", title="t", text="x")
    assert again.value.code == "not_plannable" and rows(desk) == ([], [])
    assert "mailbox" in steps.ACCOUNT_WORDS and "mailbox" in account_start.WORDS


def test_a_re_prepare_after_a_stale_card_asks_about_the_same_messages_even_when_the_snapshot_was_renumbered_meanwhile(desk):
    import test_mailbox_write as tw
    started = archive(desk, "inbox#1,inbox#2")
    desk["google"].messages["m2"]["labelIds"] = ["INBOX"]
    with pytest.raises(ops.OpsError):
        approve(desk, started)
    desk["readers"].mail["gmail"].insert(0, tw.tsm.message(9, "2026-10-18T09:00:00Z", subject="A newer message", thread_id="t9", headers={"Message-ID": "<a9@mail.example>"}))
    tw.ops_sources.source_mail(desk["path"], "inbox")           # the snapshot is read again: inbox#1 is now another message
    desk["google"].add_message("m9", "A newer message", "Sender <new@shop.example>", ["INBOX", "UNREAD"])
    assert tw.item_refs.resolve(ops_core.context(desk["path"]), "inbox#1", channel="terminal")["entry"]["id"] == "m9"
    out = tw.ops_steps.run_step(desk["path"], started["task"])
    assert out["ok"] is True
    assert [m["id"] for m in effect_doc(desk, started, cycle=1)["messages"]] == ["m1", "m2"], "the ids the operation pinned, not what the references name now"


def test_a_channel_the_runtime_does_not_know_is_refused_and_never_mapped_to_one_with_more_rights(desk):
    for channel in ("", "terminal2", "MCP", "Messaging", 7):
        with pytest.raises(ops.OpsError):
            ops.mail_archive(desk["path"], "google", "inbox#1", channel=channel)
    assert rows(desk) == ([], []) and desk["google"].requests == []


steps = st.load("steps")
ops_grants = st.load("ops_grants")


def test_a_mailbox_task_read_by_the_mcp_mode_or_a_messaging_reader_without_ask_mail_shows_no_subject_sender_draft_text_recipient_or_asker(desk):
    """W4a's task view (ops_grants.task_view: steps.is_account_step and steps.public_args) covers the step kind `mailbox-change` for every action, a reply draft included."""
    accept(desk["path"], {"messaging": ["read", "mail-organize", "ask-mail"]})
    asked_by_a_sender = ops.mail_trash(desk["path"], "google", "inbox#2", channel="messaging", sender=SENDER)
    started = {
        "from a sender": asked_by_a_sender,
        "archive": ops.mail_archive(desk["path"], "google", "inbox#1,inbox#2"),
        "mark": ops.mail_mark(desk["path"], "google", "inbox#1", "read"),
        "move": ops.mail_move(desk["path"], "google", "inbox#2", "bills"),
        "trash": ops.mail_trash(desk["path"], "google", "inbox#1"),
        "new draft": ops.mail_draft(desk["path"], "google", **NEW_DRAFT),
        "reply draft": ops.mail_draft(desk["path"], "google", message="inbox#1", body="Yes, Monday works for me.\n"),
    }
    accept(desk["path"], {"messaging": ["read"]})
    words = ("Appointment confirmed", "Your order", "ana@clinic.example", "bob@shop.example", "joe@shop.example", "amy@shop.example", "boss@shop.example", "Haircut on Monday",
             "Hello Joe", "Yes, Monday works", "4242", "desk@clinic.example")
    for name, one in started.items():
        whole = ops.task(desk["path"], one["task"])["task"]
        assert whole["step_kind"] == "mailbox-change" and steps.is_account_step(whole["step_kind"], whole["step_args"]), name
        for channel, sender in (("mcp", None), ("messaging", OTHER), ("messaging", None)):
            shown = ops.task(desk["path"], one["task"], channel=channel, sender=sender)["task"]
            assert set(shown["step_args"]) <= set(steps.ACCOUNT_ARGS_SHOWN), (name, channel, sender, shown["step_args"])
            for word in words:
                assert word not in json.dumps(shown), (name, channel, sender, word)
        for channel in ("terminal", "page", "chat"):
            assert ops.task(desk["path"], one["task"], channel=channel)["task"]["step_args"] == whole["step_args"], (name, channel)
    assert "inbox#1" in json.dumps(ops.task(desk["path"], started["reply draft"]["task"])["task"]["step_args"]), "the terminal reads the request itself"
    accept(desk["path"], {"messaging": ["read", "ask-mail"]})
    whole = ops.task(desk["path"], started["archive"]["task"])["task"]["step_args"]
    assert ops.task(desk["path"], started["archive"]["task"], channel="messaging", sender=SENDER)["task"]["step_args"] == whole, "a reader of the person's mail gets the row as it is"
    assert set(ops.task(desk["path"], started["archive"]["task"], channel="mcp")["task"]["step_args"]) <= set(steps.ACCOUNT_ARGS_SHOWN), "the MCP mode never does"


def test_a_failure_sentence_and_a_note_of_a_mailbox_task_are_cut_for_those_readers_and_a_reader_of_mail_gets_the_row_whole(desk, monkeypatch):
    ctx = ops_core.context(desk["path"])
    row = {"id": 1, "step_kind": "mailbox-change", "note": "refused at prepare -- Appointment confirmed for Monday is gone",
           "step_args": {"action": "archive", "account": "google", "messages": [{"ref": "inbox#1", "id": "m1", "snapshot_at": "2026-10-17T09:00:00Z"}]},
           "step_state": {"kind": "mailbox-change", "failure": {"step": "prepare", "code": "gone", "field": "messages", "provider": "", "next": "Appointment confirmed is gone", "at": "t"}}}
    cut = ops_grants.task_view(ctx, row, "mcp")
    assert cut["note"] == "refused at prepare" and cut["step_args"] == {"account": "google"}, cut
    assert cut["step_state"]["failure"] == {"step": "prepare", "code": "gone", "field": "messages", "provider": "", "at": "t"}
    assert "Appointment" not in json.dumps(cut) and ops_grants.task_view(ctx, row, "messaging", OTHER)["note"] == "refused at prepare"
    assert ops_grants.task_view(ctx, row, None) is row and ops_grants.task_view(ctx, row, "page") is row
    monkeypatch.setattr(ops_grants.item_refs, "may_read", lambda *a, **k: True)
    assert ops_grants.task_view(ctx, row, "messaging", SENDER) is row, "a reader of the person's mail gets the row whole"


def tamper_card(desk, started, line):
    """Write a line into the stored card of a pending decision (a test's way to get a card that cannot be read as a card)."""
    ctx = ops_core.context(desk["path"])
    row = ctx["store"].pending_get(ctx["conn"], started["pending"])
    payload = row["payload"]
    payload["card"] = payload["card"] + [line]
    body = phrases.card_text(payload["card"]) if phrases.card_valid(payload["card"]) else row["body"]
    ctx["conn"].execute("UPDATE pending_decisions SET payload = ?, body = ? WHERE id = ?", (json.dumps(payload), body, started["pending"]))
    ctx["conn"].commit()
    return ctx["store"].pending_get(ctx["conn"], started["pending"])


def test_a_card_of_a_mailbox_change_that_cannot_be_read_as_a_card_is_private_and_is_not_approved_from_messaging_fail_closed(desk):
    accept(desk["path"], {"messaging": ["read", "mail-organize", "approve-effect-mailbox"]})
    started = ops.mail_archive(desk["path"], "google", "inbox#1,inbox#2")
    sha = item_of(desk, started)["payload_sha256"]
    item = tamper_card(desk, started, ["CARD_NOT_IN_THE_TABLE", {}])
    assert not phrases.card_valid(item["payload"]["card"])
    assert ops_grants.has_private_lines(item, True) is True and ops_grants.has_private_lines(item) is False and ops_grants.has_private_lines({"payload": {}}) is False
    whole = ops.pending(desk["path"], started["pending"])
    assert "ana@clinic.example" in whole["body"], "the terminal and the page read the stored decision as it is"
    for channel, sender in (("mcp", None), ("messaging", OTHER)):
        view = ops.pending(desk["path"], started["pending"], channel=channel, sender=sender)
        text = view["body"] + json.dumps(view["payload"])
        assert view["body"] == phrases.en("CARD_HIDDEN_NOTE_WHOLE") and "ana@clinic.example" not in text and "Appointment" not in text and "card" not in view["payload"], (channel, sender)
        assert view["payload_sha256"] == whole["payload_sha256"]
    accept(desk["path"], {"messaging": ["read", "mail-organize", "approve-effect-mailbox", "ask-mail"]})
    assert "ana@clinic.example" in ops.pending(desk["path"], started["pending"], channel="messaging", sender=SENDER)["body"], "a reader of the mail gets it as it is"
    accept(desk["path"], {"messaging": ["read", "mail-organize", "approve-effect-mailbox"]})
    card = cards.build("office", ops.pending(desk["path"], started["pending"], channel="messaging", sender=OTHER), CAPS, {"messaging": ["read", "approve-effect-mailbox"]}, "text",
                       None, operations=operations, sender=OTHER)
    assert card["approvable"] is False and "ana@clinic.example" not in card["message"]["text"] and phrases.en("CARD_HIDDEN_NOTE_WHOLE") in card["message"]["text"]
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(desk["path"], started["pending"], sha, channel="messaging", sender=OTHER)
    assert "not whole for you" in str(refused.value) and desk["google"].writes() == []


def test_a_reader_who_cannot_approve_is_not_shown_the_line_that_says_how(desk):
    """The e-mail card of W2 and the file card of W4a carry a line `Approve exactly this: <command>`; the MCP mode never approves and a messaging reader without the grant of the
    word does not either, so neither is shown it; a messaging reader who approves reads it."""
    accept(desk["path"], {"messaging": ["read", "mail-organize", "ask-mail"]})
    started = ops.mail_archive(desk["path"], "google", "inbox#1")
    item = tamper_card(desk, started, ["CARD_MAIL_APPROVE", {"command": "approve --sha256 x"}])
    assert phrases.card_valid(item["payload"]["card"])
    stored = item
    with_line = "Approve exactly this: approve --sha256 x"

    def view(channel, sender):
        return ops_grants.private_view(ops_core.context(desk["path"]), stored, channel, sender)

    assert with_line not in view("mcp", None)["body"] and with_line not in json.dumps(view("mcp", None)["payload"]["card"]), "the MCP mode never approves"
    accept(desk["path"], {"messaging": ["read", "mail-organize", "ask-mail"]})
    assert with_line not in view("messaging", SENDER)["body"], "a reader of the mail without the grant of the word is not offered an approval"
    assert with_line in view(None, None)["body"] and with_line in view("page", None)["body"], "the terminal and the page read it"
    accept(desk["path"], {"messaging": ["read", "mail-organize", "ask-mail", "approve-effect-mailbox"]})
    assert with_line in view("messaging", SENDER)["body"], "a reader who may approve reads it"
    assert with_line not in card_for(desk, started, ["read", "ask-mail"])["message"]["text"], "the messaging card of a reader without the grant leaves it out"
    assert with_line in card_for(desk, started, ["read", "ask-mail", "approve-effect-mailbox"])["message"]["text"]


def test_the_private_card_of_a_mailbox_change_a_holder_reads_is_not_kept_in_the_conversation_the_mcp_mode_reads(desk):
    """A messaging read of the card drawn for a holder of `ask-mail` (the senders and subjects of the messages) goes to that chat alone; the conversation keeps a
    neutral word."""
    accept(desk["path"], {"messaging": ["read", "talk", "mail-organize", "ask-mail"]})
    started = archive(desk, channel="messaging", sender=SENDER)
    neutral = phrases.text("NAT_READ_REPLY", None)
    typed = ops.say(desk["path"], f"/pending {started['pending']}", channel="messaging", sender=SENDER)
    assert "ana@clinic.example" in typed["reply"], "the holder reads the whole card"
    ops.say(desk["path"], f"task {started['task']}", channel="messaging", sender=SENDER)
    messages = ops.conversation(desk["path"], channel="mcp")["messages"]
    assert [m["text"] for m in messages if m["role"] == "assistant"] == [neutral, neutral]
    assert not any("ana@clinic.example" in m["text"] or "bob@shop.example" in m["text"] for m in messages)
