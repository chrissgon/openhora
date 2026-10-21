"""A line the router answered with an operation (package NR-2), through `ops.say` on the stand-in tree with a stand-in router: the request the line recorded is
cancelled by code (`code:operation`), the dispatcher believes the operation against the line again and checks the policy as the typed command is, `ask` is
called with the person's whole line and never the router's `Sources:`, and a time the router normalised (in Spanish, in Japanese) is confirmed before a
reminder exists. The plumbing only: the router skill does not emit the outcome yet (package NR-3). Offline; every name, id and sender is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_say_operation.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_ask import LEASE, NOTES, accept, add_source, run_files, run_prompt
from test_ask_snapshots import INBOX, snapshot
from test_ops_natural import KEY, OPERATION, OWNER, PROFILES, SENDERS, docs, phone, router_says, say, stored, with_senders, world  # noqa: F401

ops = st.load("ops")
ops_cancel = st.load("ops_cancel")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
drafts = st.load("drafts")
ops_ask = st.load("ops_ask")
operations = st.load("operations")
phrases = st.load("phrases")

SPANISH = "recuerdame el viernes a las 17 recoger el paquete en la porteria"
JAPANESE = "金曜の17時に荷物を受け取ると私に思い出させて"
HAIRCUT_ES = OPERATION.format(name="remind") + "Argument text: recoger el paquete en la porteria\nWhen: 2026-10-23 17:00\n"
HAIRCUT_JA = OPERATION.format(name="remind") + "Argument text: 荷物を受け取る\nWhen: 2026-10-23 17:00\n"
CONFIRM_ES = "I understood: Fri 23/10 at 17:00: recoger el paquete en la porteria. Confirm? (yes / another time)"


def reminders(world) -> list:
    ctx = ops_core.context(world["path"])
    return ctx["store"].reminders_list(ctx["conn"], None)


@pytest.fixture
def cancelled(monkeypatch):
    """The `by` of every cancel by code, in order."""
    seen = []
    real = ops_cancel.request_cancel
    monkeypatch.setattr(ops_cancel, "request_cancel", lambda conn, request_id, *, by, context: seen.append(by) or real(conn, request_id, by=by, context=context))
    return seen


# --- the request, the router, the answer -----------------------------------------------------------------------------------------------------


def test_an_operation_the_router_named_is_executed_by_code_the_request_is_cancelled_by_code_and_the_run_is_done(docs, cancelled):
    router_says(docs, OPERATION.format(name="sources"))
    out = say(docs, "tell me which sources you hold")
    assert out["ran"] is True and out["request_id"] is None and out["pending_id"] is None and out["queued"] is False
    assert out["reply"].startswith("- lease-contract (file, ") and "meeting-notes" in out["reply"]
    assert cancelled == ["code:operation"] and st.calls(docs["adapter"]) == ["core-orchestrator 1"], "one router run, nothing else"
    [recorded] = ops.status(docs["path"])["requests"]
    assert recorded["state"] == "cancelled" and ops.pending(docs["path"])["pending"] == []
    reply = [m for m in stored(docs) if m["role"] == "assistant"][0]
    assert reply["text"] == out["reply"] and reply["task_id"] is None and reply["run_id"]
    [run] = [r for r in ops_core.context(docs["path"])["store"].runs_since(docs["ctx"]["conn"], "2000-01-01T00:00:00Z")]
    assert run["status"] == "ok"


def test_the_operation_is_believed_against_the_line_alone_not_against_the_conversations_memory(world):
    router_says(world, OPERATION.format(name="reminder-forget") + "Argument id: 7\n")
    first = say(world, "forget the old reminder 7 please")
    assert first["reply"].startswith("error: ") and "7" in first["reply"], "believed (7 is written in the line): the operation was asked about reminder 7, which does not exist"
    second = say(world, "forget that other old reminder please")
    assert "Earlier in this conversation" in (world["adapter"] / "last-router-prompt.md").read_text(encoding="utf-8")
    assert "reminder 7" in (world["adapter"] / "last-router-prompt.md").read_text(encoding="utf-8"), "7 is in the memory the router saw"
    assert ops.pending(world["path"], second["pending_id"])["payload"]["ending"] == "unclassified", "...but not in this line, so it is not believed"


def test_ask_is_called_with_the_whole_line_and_the_sources_are_chosen_by_code_never_by_the_routers_sources_line(docs):
    with_senders(docs)
    line = "qual o prazo do contrato?"
    router_says(docs, OPERATION.format(name="ask") + "Sources: meeting-notes\nLanguage: en\n")
    out = phone(docs, "asker", line)
    assert out["ran"] is True and "Quote" not in out["reply"] or out["reply"]
    last = [m for m in stored(docs) if m["role"] == "assistant"][-1]
    assert last["task_id"] is None and last["run_id"], "stored with the answer run and no request: only the asker reads it back"
    result = {"run_id": last["run_id"]}
    assert run_prompt(docs, result).startswith(line), "the question is the person's whole line, not a rewrite"
    copied = sorted(f for f in run_files(docs, result) if f.endswith("converted.md"))
    assert copied == ["./.workbench-local/sources/lease-contract/converted.md", "./.workbench-local/sources/meeting-notes/converted.md"], \
        "both documents, as the code selects them: the router's Sources line (meeting-notes) chose nothing"
    assert ops.status(docs["path"])["requests"][0]["state"] == "cancelled"


def test_ask_from_a_messaging_sender_without_the_group_is_the_typed_refusal_and_no_answer_run(docs):
    with_senders(docs)
    router_says(docs, OPERATION.format(name="ask"))
    out = phone(docs, "plain", "qual o prazo do contrato?")
    assert out["reply"] == "error: " + operations.refusal("ask", "messaging", ops_core.context(docs["path"])["cfg"]["channels"], sender=KEY["plain"])
    typed = phone(docs, "plain", "/ask qual o prazo do contrato?")
    assert typed["reply"] == out["reply"]
    assert st.calls(docs["adapter"]) == ["core-orchestrator 1"], "the router ran (the line cost it); the answer skill did not"


def test_a_mail_snapshot_named_in_an_ask_from_a_messaging_app_is_snapshot_here_and_nothing_is_copied_or_run(docs):
    with_senders(docs)
    snapshot(docs, "inbox", "mail", INBOX, "gmail:box=inbox;days=7;max=50")
    router_says(docs, OPERATION.format(name="ask"))
    out = phone(docs, "asker", "what is the prazo in @inbox?")
    assert out["reply"] == ops_ask.SNAPSHOT_HERE
    assert st.calls(docs["adapter"]) == ["core-orchestrator 1"]


# --- a router that cannot be believed -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("reply", [
    OPERATION.format(name="remind") + "Argument text: recordar al dentista\nWhen: 2026-10-23 17:00\n",
    OPERATION.format(name="remind") + "Argument text: recoger el paquete en la porteria\nWhen: manana a las 13\n",
    OPERATION.format(name="delete-everything"),
    OPERATION.format(name="sources") + OPERATION.format(name="reminders"),
    OPERATION.format(name="reminder-forget") + "Argument id: 7\n",
])
def test_an_operation_the_line_does_not_bear_out_is_the_unrecognised_route_and_makes_nothing(world, reply):
    with_senders(world)
    router_says(world, reply)
    out = phone(world, "owner", SPANISH)
    assert out["ran"] is True and out["pending_id"] is None      # on a phone (S1, limit L63): one plain sentence, and the request is cancelled by code
    assert out["reply"] == "I did not understand the request and started nothing. Can you say it another way?"
    assert ops.status(world["path"])["requests"][-1]["state"] == "cancelled" and ops.pending(world["path"])["pending"] == []
    assert reminders(world) == [] and drafts.count() == 0


# --- D, G, E by the router -----------------------------------------------------------------------------------------------------------------


def test_the_router_naming_a_decision_a_gated_act_or_a_planned_effect_executes_nothing(world):
    with_senders(world)
    plan_id = phone(world, "owner", "Which market first?")["pending_id"]
    router_says(world, OPERATION.format(name="approve") + f"Argument id: {plan_id}\n")
    out = phone(world, "owner", f"please sign off on number {plan_id}")
    assert out["reply"] == phrases.text("NAT_DECISION_CARD", None, id=plan_id) and out["resend"] == plan_id
    assert ops.pending(world["path"], plan_id)["status"] == "open"
    router_says(world, OPERATION.format(name="set-model"))
    gated = phone(world, "owner", "use the cheap model for the writer")
    assert gated["reply"] == "Settings, accounts and permissions are changed on the platform's page."
    router_says(world, OPERATION.format(name="event-create"))
    planned = phone(world, "owner", "pon al dentista en mi calendario")      # a line in a language no table ships has no head the code reads: the place and the command, as before (NR-5)
    assert planned["reply"] == phrases.text("PHONE_EVENT_AGAIN", None) and "event-create" not in planned["reply"]
    assert reminders(world) == []


# --- a time the router normalised is confirmed first ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("line, reply, shown, words", [
    (SPANISH, HAIRCUT_ES, CONFIRM_ES, "recoger el paquete en la porteria"),
    (JAPANESE, HAIRCUT_JA, "I understood: Fri 23/10 at 17:00: 荷物を受け取る. Confirm? (yes / another time)", "荷物を受け取る"),
])
def test_a_reminder_with_a_router_normalised_time_asks_first_and_is_made_only_by_the_answer(world, line, reply, shown, words):
    with_senders(world)
    router_says(world, reply)
    asked = phone(world, "owner", line)
    assert asked["reply"] == shown and asked["ran"] is True
    assert reminders(world) == [], "not created before the answer"
    stored_texts = [m["text"] for m in stored(world)]
    assert not any(words in t for t in stored_texts[1:]), "the reply is not stored with the words"
    made = phone(world, "owner", "yes")
    assert made["ran"] is False and made["request_id"] is None and "Reminder #1" in made["reply"] and "Fri 23/10 at 17:00 (BRT)" in made["reply"]
    [row] = reminders(world)
    assert row["text"] == words and row["due_local"] == "2026-10-23T17:00" and row["status"] == "open"
    assert drafts.count() == 0
    assert st.calls(world["adapter"]) == ["core-orchestrator 1"], "the answer to the draft ran no model"
    assert not any(words in m["text"] for m in stored(world) if m["role"] == "assistant"), "L51: the words are in the reminders table alone"


def test_the_confirmation_is_understood_in_other_languages_and_a_no_drops_the_draft(world):
    with_senders(world)
    router_says(world, HAIRCUT_ES)
    phone(world, "owner", SPANISH)
    assert phone(world, "owner", "no")["reply"] == "Ok, no reminder was made." and reminders(world) == [] and drafts.count() == 0
    for word in ("Sí", "SIM.", "はい", "oui", "ok"):
        phone(world, "owner", SPANISH)
        assert "Reminder #" in phone(world, "owner", word)["reply"], word
        ops.reminder_forget(world["path"], [r for r in reminders(world) if r["status"] == "open"][0]["id"], channel="terminal")
    assert len(reminders(world)) == 5 and {r["status"] for r in reminders(world)} == {"cancelled"}


def test_a_line_that_is_not_the_answer_drops_the_draft_and_is_handled_as_new(world):
    with_senders(world)
    router_says(world, HAIRCUT_ES)
    phone(world, "owner", SPANISH)
    router_says(world, "Route: flow-demo (flow, pending)\nWhy: x\nNext: y.\n")
    other = phone(world, "owner", "Which market first?")
    assert other["pending_id"] and drafts.count() == 0
    assert reminders(world) == []
    late = phone(world, "owner", "yes")      # the draft is gone: this is a new line for the router
    assert reminders(world) == [] and late["ran"] is True


def test_a_draft_expires_after_ten_minutes(world, monkeypatch):
    with_senders(world)
    clock = {"t": 50.0}
    monkeypatch.setattr(ops_natural, "monotonic", lambda: clock["t"])
    router_says(world, HAIRCUT_ES)
    phone(world, "owner", SPANISH)
    clock["t"] += 601
    router_says(world, "Route: flow-demo (flow, pending)\nWhy: x\nNext: y.\n")
    phone(world, "owner", "yes")
    assert reminders(world) == []


def test_in_count_mode_the_question_carries_no_words_and_the_answer_makes_the_reminder(world):
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS, "notices": "count"})
    router_says(world, HAIRCUT_ES)
    asked = phone(world, "owner", SPANISH)
    assert asked["reply"] == "I understood: Fri 23/10 at 17:00. Confirm? (yes / another time)" and "paquete" not in asked["reply"]
    phone(world, "owner", "yes")
    assert len(reminders(world)) == 1


def test_a_profile_without_the_group_reminders_is_refused_and_no_draft_is_made(world):
    with_senders(world)
    router_says(world, HAIRCUT_ES)
    out = phone(world, "asker", SPANISH)
    assert out["reply"] == "error: " + operations.refusal("remind", "messaging", ops_core.context(world["path"])["cfg"]["channels"], sender=KEY["asker"])
    assert drafts.count() == 0 and reminders(world) == []


def test_the_group_is_asked_again_when_the_answer_comes_a_profile_narrowed_meanwhile_gets_nothing(world):
    with_senders(world)
    router_says(world, HAIRCUT_ES)
    phone(world, "owner", SPANISH)
    accept(world["path"], policies={**PROFILES, "owner": ["read", "talk"]}, messaging={"senders": SENDERS})
    out = phone(world, "owner", "yes")
    assert out["reply"].startswith("error: /remind is not enabled") and reminders(world) == []


def test_a_time_that_is_past_or_missing_or_a_text_that_is_missing_is_refused_or_asked_back_before_any_draft(world):
    with_senders(world)
    router_says(world, OPERATION.format(name="remind") + "Argument text: recoger el paquete en la porteria\nWhen: 2026-10-17 13:00\n")
    past = phone(world, "owner", SPANISH)
    assert past["reply"].startswith("error: ") and drafts.count() == 0
    router_says(world, OPERATION.format(name="remind") + "Argument text: recoger el paquete en la porteria\n")
    assert phone(world, "owner", SPANISH)["reply"] == phrases.text("NT_ASK_WHEN_SLASH", None) and drafts.count() == 1, "the engine asks the time and keeps the question"
    router_says(world, OPERATION.format(name="remind") + "When: 2026-10-23 17:00\n")
    assert phone(world, "owner", SPANISH)["reply"] == phrases.text("NT_ASK_TEXT", None)
    assert reminders(world) == [] and drafts.count() == 1, "the engine asks the words and keeps the question: nothing is made"


def test_on_the_page_a_reminder_is_the_terminals_command_with_the_time_and_no_draft(world):
    router_says(world, HAIRCUT_ES)
    out = say(world, SPANISH, channel="page")
    assert out["reply"].startswith("This changes something, so it is done by its command") and "remind" in out["reply"] and "--to" in out["reply"]
    assert drafts.count() == 0 and reminders(world) == []


def test_a_draft_of_one_sender_is_not_answered_by_another(world):
    with_senders(world)
    router_says(world, HAIRCUT_ES)
    phone(world, "owner", SPANISH)
    router_says(world, "Route: flow-demo (flow, pending)\nWhy: x\nNext: y.\n")
    phone(world, "asker", "yes")
    assert reminders(world) == []
    assert drafts.get("messaging", KEY["owner"]) is not None, "the owner's draft stays until the owner answers or it expires"
    phone(world, "owner", "yes")
    assert len(reminders(world)) == 1
