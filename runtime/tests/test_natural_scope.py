"""The independent review of PR #477 (package NR-2, phase A), as tests: a sender who may not talk never causes a router run and never answers the router's open
question (B1); what the MCP mode could not read itself is stored as a neutral word (B2, limits L50 and L51); a notice the router chose always asks first (M1);
the help and the reads whose row does not list the channel are answered with a true sentence (M2); and the smaller findings: the choice of a file by a profile
that may ask and not talk, a card sent again only when one is sent and at most once a minute, a file chosen while the router is busy is queued, no path of this
machine in a reply to the MCP mode, and the conversation's own shell reading as the terminal does. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_scope.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import pytest

import standin_tree as st
from test_ask import accept, add_source
from test_messaging_ask import wait_for
from test_messaging_natural_ops import rig  # noqa: F401
from test_ops_natural import KEY, OPERATION, OWNER, PROFILES, READER, SENDERS, docs, phone, router_says, say, stored, with_senders, world  # noqa: F401
from test_say_operation import reminders

ops = st.load("ops")
ops_ask = st.load("ops_ask")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
drafts = st.load("drafts")
operations = st.load("operations")
phrases = st.load("phrases")

QUESTION = "Q1: Which market do you mean?\n"


def settled(rig):
    return wait_for(lambda: not rig.bridge.exclusive)


# --- B1 -------------------------------------------------------------------------------------------------------------------------------------


def test_a_sender_without_talk_answers_no_router_question_and_causes_no_router_run(rig):
    router_says(rig.world, QUESTION)
    rig.bridge.handle(rig.update(OWNER, "Which market first?"))
    assert wait_for(lambda: len(rig.sent()) >= 1) and settled(rig)
    ran = list(st.calls(rig.world["adapter"]))
    assert ran == ["core-orchestrator 1"]
    rig.bridge.handle(rig.update(READER, "quais arquivos voce tem?"))      # a form of a read: code takes it, though the router asked the owner something
    assert wait_for(lambda: len(rig.sent()) >= 2) and settled(rig)
    assert rig.sent()[1]["chat"] == READER and rig.sent()[1]["message"]["text"].startswith("- lease-contract")
    rig.bridge.handle(rig.update(READER, "Which market first?"))        # no form takes it: it needs talk, which the viewer lacks
    assert wait_for(lambda: len(rig.sent()) >= 3) and settled(rig)
    assert rig.sent()[2]["message"]["text"] == PLAIN_REFUSAL
    assert st.calls(rig.world["adapter"]) == ran, "the viewer started no router run"
    open_question = ops.pending(rig.project["path"])["pending"]
    assert [p["kind"] for p in open_question] == ["question"], "the owner's question is still open: nobody answered it"


def test_a_line_admitted_under_another_group_is_refused_by_the_layer_when_no_form_takes_it(world):
    accept(world["path"], policies={"viewer": ["read", "sources"]}, messaging={"senders": {"telegram": [{"id": READER, "policy": "viewer"}]}})
    router_says(world, QUESTION)
    ops.say(world["path"], "Which market first?", channel="page")      # the page asks the router a question
    before = list(st.calls(world["adapter"]))
    out = ops.say(world["path"], "The clinic project.", channel="messaging", sender=KEY["reader"])      # a viewer's plain line would answer it
    assert out["reply"] == PLAIN_REFUSAL and out["ran"] is False and out["pending_id"] is None
    assert st.calls(world["adapter"]) == before
    assert ops.pending(world["path"])["pending"][0]["kind"] == "question"
    assert ops.say(world["path"], "pendencias", channel="messaging", sender=KEY["reader"])["reply"] != out["reply"], "a form is still answered while a question is open"


def test_the_bridge_asks_a_non_talk_group_only_for_a_line_code_will_certainly_take(rig):
    bridge = rig.bridge
    assert bridge.needs("quais arquivos voce tem?", rig.project, READER) == "sources"
    assert bridge.needs("Which market first?", rig.project, READER) is None
    assert bridge.needs("aceita o pedido 7", rig.project, OWNER) == "pending"
    assert bridge.needs("ajuda", rig.project, OWNER) is None, "the help is not a row of this channel: it needs talk, and is answered by code"


# --- B2 -------------------------------------------------------------------------------------------------------------------------------------


def test_the_words_of_a_reminder_listed_by_a_natural_read_are_not_in_the_conversation_the_mcp_mode_reads(world):
    with_senders(world)
    ops.remind(world["path"], "in 2h", "secret dentist words", to=KEY["owner"], channel="terminal")
    router_says(world, OPERATION.format(name="reminders"))
    out = phone(world, "owner", "what did I ask you to remind me of?")
    assert "secret dentist words" in out["reply"], "the asking channel gets the real reply"
    for channel in ("mcp", "page"):
        shown = [m["text"] for m in ops.conversation(world["path"], channel=channel)["messages"]]
        assert not any("secret dentist words" in t for t in shown), channel
    assert [m["text"] for m in stored(world) if m["role"] == "assistant"] == [phrases.text("NAT_READ_REPLY", None)]


def test_a_read_the_mcp_mode_may_make_itself_is_stored_as_it_was_said(docs):
    out = say(docs, "what files do you have?")
    shown = [m["text"] for m in ops.conversation(docs["path"], channel="mcp")["messages"] if m["role"] == "assistant"]
    assert shown == [out["reply"]], "sources is a row of the MCP ceiling: no secret in it"
    acted = say(docs, "list my attachments")      # attachments is not: neutral
    assert acted["reply"] and [m["text"] for m in ops.conversation(docs["path"], channel="mcp")["messages"] if m["role"] == "assistant"][-1] \
        == phrases.text("NAT_READ_REPLY", None)


# --- M1 -------------------------------------------------------------------------------------------------------------------------------------


def test_a_reminder_the_router_chose_to_forget_is_never_forgotten_at_once(world):
    with_senders(world)
    ops.remind(world["path"], "in 2h", "dentist", to=KEY["owner"], channel="terminal")
    [made] = reminders(world)
    router_says(world, OPERATION.format(name="reminder-forget") + f"Argument id: {made['id']}\n")
    asked = phone(world, "owner", f"how is task {made['id']} going?")
    assert asked["reply"].startswith(f"Cancel reminder #{made['id']}: ") and asked["reply"].endswith("dentist? (yes / no)")
    assert [r["status"] for r in reminders(world)] == ["open"], "nothing was cancelled by the router's word"
    assert phone(world, "owner", "no")["reply"] == phrases.text("NT_KEPT", None) and [r["status"] for r in reminders(world)] == ["open"]
    phone(world, "owner", f"how is task {made['id']} going?")
    done = phone(world, "owner", "yes")
    assert done["ran"] is False and [r["status"] for r in reminders(world)] == ["cancelled"]


# --- M2 -------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line, expected", [
    ("help", "GREET_HEAD"), ("ajuda", "GREET_HEAD"), ("what can you do", "GREET_HEAD"),      # S5: a help line in words from a sender who may talk is the summary of what that sender may do
    ("what flows are there", "That is not done from a message. Do it on the platform's page."),
])
def test_the_help_and_a_read_the_channel_does_not_have_get_a_true_sentence_through_the_bridge(rig, line, expected):
    rig.bridge.handle(rig.update(OWNER, line))
    assert wait_for(lambda: len(rig.sent()) == 1) and settled(rig)
    text = rig.sent()[0]["message"]["text"]
    assert "turns it on" not in text and "is not enabled" not in text
    assert text.splitlines()[0] == phrases.text("GREET_HEAD", None) if expected == "GREET_HEAD" else text == expected


def test_a_refusal_for_a_row_no_configuration_can_turn_on_says_where_it_is_done():
    assert operations.not_enabled("flows", "messaging") == "/flows is done in the terminal or on the page"
    assert operations.not_enabled("give-consent", "messaging") == "/give-consent is done on the page"
    assert operations.not_enabled("attachment-hold", "page") == "/attachment-hold is not done on this channel"
    assert "turns it on" in operations.not_enabled("pending", "messaging"), "a row the channel lists keeps its sentence"
    assert "turns it on" in operations.not_enabled("approve", "mcp"), "and a grant can turn on the MCP mode's approve"


# --- the smaller findings -------------------------------------------------------------------------------------------------------------------


def test_a_profile_with_ask_and_without_talk_can_answer_the_list_of_files_to_choose_from(rig):
    add_source(rig.world, "report-2025", "# Report 2025\n\nSales grew.\n", name="report 2025.txt")
    add_source(rig.world, "report-2026", "# Report 2026\n\nSales fell.\n", name="report 2026.txt")
    accept(rig.world["path"], policies={**PROFILES, "askonly": ["read", "ask"]}, messaging={"senders": {"telegram": [{"id": OWNER, "policy": "askonly"}]}})
    rig.bridge.handle(rig.update(OWNER, "/ask what does the report say about sales?"))
    assert wait_for(lambda: len(rig.sent()) == 1) and settled(rig)
    assert rig.sent()[0]["message"]["text"].startswith("Which file do you mean?")
    rig.bridge.handle(rig.update(OWNER, "1"))
    assert wait_for(lambda: len(rig.sent()) == 2) and settled(rig)
    assert "not enabled" not in rig.sent()[1]["message"]["text"] and "Which file" not in rig.sent()[1]["message"]["text"]


def test_the_card_goes_out_again_at_most_once_a_minute_and_the_sentence_says_so_only_when_a_card_is_there(rig, monkeypatch):
    router_says(rig.world, "Route: flow-demo (flow, pending)\nWhy: x\nNext: y.\n")
    rig.bridge.handle(rig.update(OWNER, "Which market first?"))
    assert wait_for(lambda: len(rig.sent()) == 1) and settled(rig)
    clock = {"t": 100.0}
    rig.bridge.monotonic = lambda: clock["t"]
    cards = lambda: len([s for s in rig.sent() if s["message"].get("actions")])
    rig.bridge.handle(rig.update(OWNER, "aprova a entrega 1"))
    assert wait_for(lambda: cards() == 1) and settled(rig)
    rig.bridge.handle(rig.update(OWNER, "aprova o pedido 1"))
    assert wait_for(lambda: len(rig.sent()) == 3) and settled(rig)
    assert cards() == 1, "the second line within a minute sent no second card"
    clock["t"] += 61
    rig.bridge.handle(rig.update(OWNER, "aprova a decisao 1"))
    assert wait_for(lambda: cards() == 2) and settled(rig)
    clock["t"] += 61
    monkeypatch.setattr(rig.bridge, "send_card", lambda *a, **k: False)      # a card that cannot be sent
    rig.bridge.handle(rig.update(OWNER, "aprova a pendencia 1"))
    assert wait_for(lambda: rig.sent()[-1]["message"]["text"] == phrases.text("NAT_DECISION_NO_CARD", None)) and settled(rig)


def test_the_answer_to_a_file_list_waits_in_the_queue_when_the_router_is_busy_and_is_not_lost(world):
    add_source(world, "report-2025", "# Report 2025\n\nSales grew.\n", name="report 2025.txt")
    add_source(world, "report-2026", "# Report 2026\n\nSales fell.\n", name="report 2026.txt")
    first = ops.say(world["path"], "/ask what does the report say about sales?", channel="page")
    assert first["reply"].startswith("Which file do you mean?")
    with ops_core._route_lock(world["ctx"]["cfg"]):
        queued = ops.say(world["path"], "2", channel="page")
        assert queued["queued"] is True and drafts.count() == 1, "queued, and the draft is still there"
    done = ops.route_queued(world["path"])
    assert done["routed"] == "line" and drafts.count() == 0
    last = [m for m in ops.conversation(world["path"], channel="page")["messages"] if m["role"] == "assistant"][-1]
    assert last["run_id"] and "Which file" not in last["text"]


def test_a_reply_to_the_mcp_mode_carries_no_path_of_this_machine_and_a_terminal_reply_does_not_say_message(world):
    out = say(world, "muda o modelo do agente", channel="mcp")["reply"]
    assert "/set-model is done" in out
    assert str(world["path"]) not in out and str(world["tree"]) not in out and "<project>" in out
    page = say(world, "muda o modelo do agente", channel="page")["reply"]
    assert "from a message" not in page and "line of words" in page and str(world["path"]) in page
    assert str(world["path"]) not in say(world, "approve 3", channel="mcp")["reply"]


def test_the_conversations_own_shell_reads_as_the_terminal_does(docs):
    for line in ("what files do you have?", "tarefa 1", "list the agents", "what are the costs", "show the routines"):
        reply = ops.say(docs["path"], line, channel="chat")["reply"]
        assert "is done in the terminal or on the page" not in reply, (line, reply)
    assert ops.say(docs["path"], "what files do you have?")["reply"].startswith("- lease-contract"), "no channel is the conversation's own shell"


def test_a_mail_answer_is_withheld_when_the_group_ask_mail_is_gone_by_the_time_it_is_ready(docs):
    accept(docs["path"], policies={"mailer": ["read", "talk", "ask", "ask-mail"], "asker": ["read", "talk", "ask"]},
           messaging={"senders": {"telegram": [{"id": OWNER, "policy": "mailer"}]}})
    key = KEY["owner"]
    assert ops_ask._still_may_ask(docs["path"], "messaging", key, mail=True) is True
    accept(docs["path"], messaging={"senders": {"telegram": [{"id": OWNER, "policy": "asker"}]}})
    assert ops_ask._still_may_ask(docs["path"], "messaging", key, mail=True) is False, "an answer that read the mailbox needs the group now"
    assert ops_ask._still_may_ask(docs["path"], "messaging", key, mail=False) is True, "and a document answer needs only ask"
