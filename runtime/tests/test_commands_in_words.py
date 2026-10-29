"""Every command a messaging sender can type can be asked for in words (slice S20, limits L54 and L64), through the real messaging bridge, the stand-in Telegram provider, the real
operations layer over the stand-in tree and a stand-in model for the interpreter. Offline, no network; every name, number and sender is invented.

The maintainer's words, 2026-10-22: he sent "rejeite a pergunta 25" and was told to use the buttons of the card, while `/reject 25` worked; "Devemos ser capaz de acionar QUALQUER comando
utilizando linguagem natural". The rule these tests pin: a command asked for in words is the typed command (the same policy check, the same refusals, the same effect), except that
`approve` is never made from words (the decision's card is sent again) and `answer` keeps the words it had. The bridge side (the typed line is handled as typed, no model slot) is
in test_commands_in_words_bridge.py; the pure reading of "muda para o projeto" is in test_command_words.py.

D5 (BL2b, limit L65): a read or an act asked in words now meets the question "I understood: ... Shall I go ahead?" before it runs, and the closed verb lists that refused a negated or conditional line are gone.
D5 is tested in test_plan_confirm*.py and test_messaging_plan_confirm.py: here `rig.line` says "sim" to the question (the question is the last message, so it is the OK of L64) and returns what was
sent after it, so every assertion about the act itself reads as it did; a test of a line the verb lists refused passes `confirm=False` and asserts the question and that nothing ran before the OK.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_commands_in_words.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL, PLAIN_REFUSAL_PT  # noqa: E402

import json
import shutil
import time

import pytest

import phrase_kit as pk
import standin_tree as st
from test_ask import accept
from test_interpret_router_frame import QUESTION
from test_messaging_ask import FIXTURE, wait_for
from test_ops_natural import KEY, OWNER, PROFILES, docs, router_says, with_senders, world  # noqa: F401
from test_service import WAIT
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

ops = st.load("ops")
ops_core = st.load("ops_core")
bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")
ops_interpret = st.load("ops_interpret")
interpreter_route = st.load("interpreter_route")
natural = st.load("natural")
turn_gate = st.load("turn_gate")
ops_natural = st.load("ops_natural")
phrases = st.load("phrases")

ZONE = "America/Sao_Paulo"
BARE, OTHER = "55119000000007", "55119000000008"
FLOW = "Route: flow-demo (flow, pending)\nWhy: a market question\nNext: the market task.\n"
PROFILES2 = {**PROFILES, "owner": PROFILES["owner"] + ["interpret", "routine-brakes"], "bare": ["read", "talk", "interpret"], "other": PROFILES["owner"] + ["interpret"]}
SENDERS2 = {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": BARE, "policy": "bare"}, {"id": OTHER, "policy": "other"}]}
# the plain refusal is quoted by a limit row (L54), so it stays a literal of the test; every other sentence is asserted by its phrase key (`says`, `is_said`)
SAY = {"en": {"refusal": PLAIN_REFUSAL}, "pt-BR": {"refusal": PLAIN_REFUSAL_PT}}
PAGE = {"en": "on the platform's page.", "pt-BR": "na página da plataforma."}      # the place a phone is sent to, as the sentence of PHONE_ROUTINE_CANCEL closes with it  # validate: allow english-only -- the Portuguese place under test


class Rig:
    pass


@pytest.fixture(params=["en", "pt-BR"])
def rig(request, docs, tmp_path, monkeypatch):
    root = tmp_path / "bench"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "state"))
    accept(docs["path"], policies=PROFILES2, messaging={"senders": SENDERS2}, **({} if request.param == "en" else {"language": "pt-BR"}))
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()
    r = Rig()
    r.language, r.say_for, r.model, r.asked = request.param, SAY[request.param], {"text": '{"v":1,"kind":"none"}'}, []

    def complete(route_id, system, user, **kw):
        r.asked.append(user)
        return {"ok": True, "text": r.model["text"], "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}
    monkeypatch.setattr(interpreter_route, "complete", complete)
    r.world, r.folder, r.monkeypatch = docs, folder, monkeypatch
    r.project = {"id": shell_kit.project_id(docs["path"]), "name": "northwind-shop", "path": docs["path"], "data_dir": str(docs["data"])}
    r.bridge = bridge.Bridge(ops, [r.project], providers.Messenger("telegram", root=str(root)), ledgers.Ledger(str(docs["data"]), "telegram"), "telegram",
                             [].append, clock=lambda: "2026-10-17T10:00:00+00:00")

    def sent():
        path = folder / "sent.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
    r.sent = sent
    r.texts = lambda chat=None: [s["message"]["text"] for s in sent() if chat is None or s["chat"] == chat]

    def plan_cards(who):
        return [c for c in r.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm" and c["chat"] == who]
    r.plan_cards = plan_cards

    def answer(who, word):
        """The sender says `word` (it does not reset the model's record); what was sent to that sender's chat since is returned."""
        before = len([s for s in sent() if s["chat"] == who])
        r.bridge.handle({"update_id": 1, "sender": who, "chat": who, "private": True, "text": word, "action": None, "action_ref": None, "reply_to": None})
        assert wait_for(lambda: not r.bridge.exclusive and all(not t.is_alive() for t in r.bridge.threads))
        return [s["message"]["text"] for s in sent() if s["chat"] == who][before:]
    r.answer = answer

    def line(who, text, model=None, confirm=True):
        """The sender types `text`; the bridge's jobs end; what was sent to that sender's chat since is returned. D5 is tested in test_plan_confirm*.py and test_messaging_plan_confirm.py: when
        the line met the question "Shall I go ahead?" and `confirm` is true, the sender says "sim" to it and what was sent after that is returned; with `confirm` false the question is returned."""
        before = len([s for s in sent() if s["chat"] == who])
        asked = len(plan_cards(who))
        r.asked.clear()
        r.model["text"] = model or '{"v":1,"kind":"none"}'
        r.bridge.handle({"update_id": 1, "sender": who, "chat": who, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None})
        assert wait_for(lambda: not r.bridge.exclusive and all(not t.is_alive() for t in r.bridge.threads))
        if confirm and len(plan_cards(who)) > asked:
            return answer(who, "sim")
        return [s["message"]["text"] for s in sent() if s["chat"] == who][before:]
    r.line = line

    def card_for(pending_id, chat):
        return [s for s in sent() if s["chat"] == chat and s["message"].get("actions") and f"#{pending_id}" in s["message"]["text"]]
    r.card_for = card_for
    yield r
    r.bridge.stopping.set()
    for thread in list(r.bridge.threads):
        thread.join(WAIT)


def say(rig, key):
    return rig.say_for[key]


def is_said(rig, text, key, **fields):
    """`text` is exactly the sentence of the phrase `key` with `fields`, in the project's language (one line: no other text beside it)."""
    assert "\n" not in text, text
    pk.assert_said(text, key, {"language": rig.language}, **fields)
    return True


def says(rig, out, key, **fields):
    """What was sent is exactly one message, and it is the sentence of the phrase `key` with `fields`, in the project's language."""
    assert len(out) == 1, out
    return is_said(rig, out[0], key, **fields)


def question(rig, key, **fields):
    """The question "I understood: ... Shall I go ahead?" for a sentence, by phrase key and values, in the project's language."""
    cfg = {"language": rig.language}
    return phrases.text("PLAN_HEAD", cfg, what=phrases.text(key, cfg, **fields)) + " " + phrases.text("PLAN_ASK", cfg)


def nothing_ran_before_the_ok(rig, who, said, asked, nothing_changed):
    """A line the verb lists refused meets the question now (the person reads the sentence and says no there): the reply is that question, `nothing_changed()` holds, and "nao" drops it."""
    assert said == [asked] and nothing_changed()
    assert says(rig, rig.answer(who, "n\u00e3o"), "PLAN_DROPPED") and nothing_changed()


def make_question(rig, token="Zircon77") -> int:
    router_says(rig.world, QUESTION.replace("Zircon77", token))
    return ops.say(rig.project["path"], "/new plan the stock count of the warehouse " + token, channel="page")["pending_id"]


def make_plan(rig) -> int:
    router_says(rig.world, FLOW)
    made = ops.say(rig.project["path"], "/new Which market first? " + str(time.monotonic()), channel="page")["pending_id"]
    rig.bridge.notify_project(rig.project)      # the card of every open decision goes to every listed sender, as the bridge's tick sends it
    return made


def make_plan_without_card(rig) -> int:
    router_says(rig.world, FLOW)
    return ops.say(rig.project["path"], "/new Which market first? a plan with no card yet " + str(time.monotonic()), channel="page")["pending_id"]


def bridge_wants_nothing(rig) -> None:
    """The bridge sends a card only to a sender whose profile is sent that decision (`notices: actionable`): the other chat gets the sentence that says the card could not be sent."""
    rig.bridge.wants = lambda project, settings, item, sender: sender == OWNER      # the test's own stand-in for a profile that is sent nothing of this decision


def make_review(rig) -> int:
    request = ops.request(rig.project["path"], "Invented market request " + str(time.monotonic()), flow="demo")
    ctx = ops_core.context(rig.project["path"])
    store = ctx["store"]
    claimed = store.task_claim(ctx["conn"], request["tasks"][0]["id"])["task"]
    run = store.task_run_start(ctx["conn"], claimed["id"], skill=claimed["skill"], model="m", adapter="h")
    made = store.task_run_finish(ctx["conn"], run["run_id"], status="ok", ending="done", task_state="waiting", pending={"kind": "review", "title": "Draft of the brief", "body": "draft"})
    rig.bridge.notify_project(rig.project)
    return made["pending_id"]


def status_of(rig, pending_id) -> str:
    return ops.pending(rig.project["path"], pending_id=pending_id)["status"]


def op(name, slots=None):
    return json.dumps({"v": 1, "kind": "op", "op": name, "slots": slots or {}})


# --- the maintainer's line: a question is dismissed by words, as by the typed /reject -------------------------------------------------------------------


@pytest.mark.parametrize("english,portuguese", [("reject question {id}", "rejeite a pergunta {id}"), ("dismiss the question {id}", "dispense a pergunta {id}"),
                                               ("decline question number {id}", "recuse a pergunta numero {id}")])
def test_a_question_is_dismissed_by_words_exactly_as_the_typed_reject_dismisses_it(rig, english, portuguese):
    first, second = make_question(rig, "Zircon77"), make_question(rig, "Basalt19")
    words = english if rig.language == "en" else portuguese
    assert says(rig, rig.line(OWNER, words.format(id=first)), "QUESTION_DISMISSED", id=first) and rig.asked == [], "code took the line: no model was asked"
    assert status_of(rig, first) != "open"
    assert says(rig, rig.line(OWNER, f"/reject {second}"), "QUESTION_DISMISSED", id=second) and status_of(rig, second) != "open"


def test_the_line_of_the_live_test_in_portuguese_dismisses_question_25_when_the_stand_in_model_reads_it(rig):
    """"rejeite a pergunta 25" did not reach the closed list in the live test (the model named `reject` and was told to use the card); now it is the typed reject, from either path."""
    questions = [make_question(rig, f"Zircon{n}") for n in (1, 2, 3)]
    target = questions[-1]
    line = f"rejeite a pergunta {target}"
    assert says(rig, rig.line(OWNER, line, op("reject")), "QUESTION_DISMISSED", id=target) and status_of(rig, target) != "open"
    rig.asked.clear()
    assert says(rig, rig.line(OWNER, "por favor, dispense a pergunta " + str(questions[0]), op("reject")), "QUESTION_DISMISSED", id=questions[0])  # validate: allow english-only -- the Portuguese line under test
    assert len(rig.asked) == 1, "this one is not a closed form: the model named the operation, code read the number, and the line's own verb says the same"


@pytest.mark.parametrize("english,portuguese", [("reject plan {id}", "rejeite o plano {id}"), ("decline the decision number {id}", "recuse a decisao numero {id}")])
def test_a_plan_is_rejected_by_words_as_the_typed_reject_rejects_it_and_only_in_the_chat_it_was_sent_to(rig, english, portuguese):
    plan = make_plan(rig)
    other_plan = make_plan(rig)
    words = (english if rig.language == "en" else portuguese).format(id=plan)
    assert rig.card_for(plan, OWNER) and rig.card_for(plan, OTHER) and not rig.card_for(plan, BARE), "a sender with no group to decide is sent no card"
    assert rig.line(BARE, words) == [say(rig, "refusal")] and status_of(rig, plan) == "open", "a sender without the group is refused, as the typed line refuses it"
    assert says(rig, rig.line(OWNER, words), "REJECTED", id=plan) and status_of(rig, plan) != "open"
    assert says(rig, rig.line(OWNER, f"/reject {other_plan}"), "REJECTED", id=other_plan) and status_of(rig, other_plan) != "open"
    assert says(rig, rig.line(OWNER, words), "NAT_NO_DECISION", id=plan), "a number that is not an open decision gets the one sentence"


def test_a_decision_never_sent_to_the_chat_is_not_rejected_by_words_either(rig):
    plan = make_plan(rig)
    router_says(rig.world, FLOW)
    later = ops.say(rig.project["path"], "/new Which market first? again", channel="page")["pending_id"]      # no tick: no card of it went to any chat
    words = f"reject plan {later}" if rig.language == "en" else f"rejeite o plano {later}"
    assert says(rig, rig.line(OTHER, words), "NO_CARD") and status_of(rig, later) == "open"
    assert says(rig, rig.line(OTHER, f"/reject {later}"), "NO_CARD")
    assert status_of(rig, plan) == "open"


@pytest.mark.parametrize("english,portuguese", [("release the delivery {id}", "libere a entrega {id}"), ("release {id}", "libera {id}")])
def test_a_delivery_is_released_by_words_as_the_typed_release_releases_it(rig, english, portuguese):
    review, other = make_review(rig), make_review(rig)
    words = (english if rig.language == "en" else portuguese).format(id=review)
    assert rig.line(BARE, words) == [say(rig, "refusal")] and status_of(rig, review) == "open"
    assert says(rig, rig.line(OWNER, words), "RELEASED", id=review) and status_of(rig, review) != "open"
    assert says(rig, rig.line(OWNER, f"/release {other}"), "RELEASED", id=other) and status_of(rig, other) != "open"


# --- approve is never made from words: the card is sent again, once --------------------------------------------------------------------------------------


@pytest.mark.parametrize("english,portuguese", [("approve {id}", "aprova o {id}"), ("approve the plan {id}", "aprove o plano {id}"), ("accept decision {id}", "aceite a decisao {id}")])
def test_an_approve_line_sends_the_card_again_and_approves_nothing_then_the_word_that_follows_approves_it(rig, english, portuguese):
    plan = make_plan(rig)
    words = (english if rig.language == "en" else portuguese).format(id=plan)
    cards = len(rig.card_for(plan, OWNER))
    out = rig.line(OWNER, words)
    assert len(out) == 2 and out[0].startswith("northwind-shop · ") and is_said(rig, out[1], "NAT_DECISION_CARD", id=plan), "the card of that decision once more, then the one sentence"
    assert len(rig.card_for(plan, OWNER)) == cards + 1
    assert status_of(rig, plan) == "open" and ops.status(rig.project["path"])["requests"][-1]["state"] == "requested", "nothing was approved"
    assert says(rig, rig.line(OWNER, "approve" if rig.language == "en" else "aprovo"), "APPROVED", id=plan), "the word right after the card approves it (S2)"
    assert status_of(rig, plan) != "open"


def test_an_approve_line_for_a_decision_the_sender_may_not_approve_is_refused_and_no_card_is_sent(rig):
    plan = make_plan(rig)
    cards = len(rig.sent())
    words = f"approve {plan}" if rig.language == "en" else f"aprova o {plan}"
    assert rig.line(BARE, words) == [say(rig, "refusal")] and len(rig.sent()) == cards + 1, "no approve group: the plain refusal and nothing else"
    assert status_of(rig, plan) == "open"


def test_an_approve_line_for_a_decision_that_was_never_sent_to_the_chat_is_the_sentence_that_says_so_and_nothing_is_decided(rig):
    plan = make_plan(rig)
    later = make_plan_without_card(rig)
    words = f"approve {later}" if rig.language == "en" else f"aprova o {later}"
    out = rig.line(OWNER, words)      # the owner is listed: the decision's card is sent to it now, the first time
    assert is_said(rig, out[-1], "NAT_DECISION_CARD", id=later) and status_of(rig, later) == "open" and status_of(rig, plan) == "open"
    bridge_wants_nothing(rig)
    assert says(rig, rig.line(OTHER, words), "NAT_DECISION_NO_CARD"), "a chat the bridge does not send that card to"


def test_an_approve_line_with_no_number_or_with_a_date_asks_which_and_sends_nothing(rig):
    make_plan(rig)
    cards = len(rig.sent())
    assert says(rig, rig.line(OWNER, "aprueba el plan", op("approve")), "NAT_WHICH_DECISION")
    assert says(rig, rig.line(OWNER, "aprova até 25 de outubro", op("approve")), "NAT_WHICH_DECISION")
    assert says(rig, rig.line(OWNER, "libera os 3 e 4", op("release")), "NAT_WHICH_DECISION")
    assert len(rig.sent()) == cards + 3


# --- the other acts: the typed command is run, by its words ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("english,portuguese", [("cancel request {id}", "cancela o pedido {id}"), ("cancel the request number {id}", "cancele o pedido numero {id}")])
def test_a_request_is_cancelled_by_words_as_the_typed_cancel_cancels_it(rig, english, portuguese):
    first, second = (ops.request(rig.project["path"], f"Invented request {n}")["request"] for n in (1, 2))
    words = (english if rig.language == "en" else portuguese).format(id=first)
    assert rig.line(BARE, words) == [say(rig, "refusal")] and rig.line(BARE, f"/cancel {first}") == [say(rig, "refusal")]
    assert says(rig, rig.line(OWNER, words), "CMD_CANCELLED", n=first)
    assert says(rig, rig.line(OWNER, f"/cancel {second}"), "CMD_CANCELLED", n=second)
    states = {r["id"]: r["state"] for r in ops.status(rig.project["path"])["requests"]}
    assert states[first] == states[second] == "cancelled"
    assert says(rig, rig.line(OWNER, words), "CMD_CANCEL_ALREADY", n=first)


@pytest.mark.parametrize("function,english,portuguese,key", [("stop_task", "stop task {id}", "para a tarefa {id}", "CMD_TASK_STOPPED"), ("retry", "retry task {id}", "tenta de novo a tarefa {id}", "CMD_TASK_RETRY")])
def test_a_task_is_stopped_or_retried_by_words_with_the_call_the_typed_command_makes(rig, function, english, portuguese, key):
    calls = []
    rig.monkeypatch.setattr(ops, function, lambda project, task_id, channel=None, sender=None: calls.append((task_id, channel, sender)) or {"task_id": task_id, "task": task_id, "already": False})
    command = "/" + ("stop-task" if function == "stop_task" else "retry")
    words = (english if rig.language == "en" else portuguese).format(id=7)
    assert rig.line(BARE, words) == [say(rig, "refusal")] and rig.line(BARE, f"{command} 7") == [say(rig, "refusal")] and calls == []
    assert says(rig, rig.line(OWNER, words), key, n=7)
    assert says(rig, rig.line(OWNER, f"{command} 7"), key, n=7)
    assert calls == [(7, "messaging", KEY["owner"])] * 2, "the same call, the same channel and sender"


@pytest.mark.parametrize("english,portuguese", [("pause routine {id}", "pausa a rotina {id}"), ("pause the routine number {id}, please", "pause a rotina numero {id}, por favor")])
def test_a_routine_is_paused_by_words_after_the_same_policy_check_and_the_actor_is_recorded(rig, english, portuguese):
    calls = []
    rig.monkeypatch.setattr(ops, "routine_pause", lambda project, routine_id, channel=None, sender=None: calls.append((routine_id, channel, sender)) or {"routine": routine_id})
    words = (english if rig.language == "en" else portuguese).format(id=4)
    assert rig.line(BARE, words, op("routine-pause", {"id": "4"})) == [say(rig, "refusal")] and calls == []
    assert says(rig, rig.line(OWNER, words, op("routine-pause", {"id": "4"})), "CMD_ROUTINE_PAUSED", n=4) and calls == [(4, "messaging", KEY["owner"])]


@pytest.mark.parametrize("english,portuguese", [("cancel routine {id}", "cancela a rotina {id}"), ("cancel the routine {id} for good", "cancele a rotina {id} de vez")])
def test_a_routine_is_never_cancelled_by_words_the_reply_says_to_pause_it_here_and_cancel_it_on_the_page(rig, english, portuguese):
    calls = []
    rig.monkeypatch.setattr(ops, "routine_cancel", lambda project, routine_id: calls.append(routine_id) or {})
    rig.monkeypatch.setattr(ops, "routine_pause", lambda project, routine_id, channel=None, sender=None: calls.append(("pause", routine_id)) or {})
    words = (english if rig.language == "en" else portuguese).format(id=4)
    assert says(rig, rig.line(OWNER, words, op("routine-cancel", {"id": "4"})), "PHONE_ROUTINE_CANCEL", where=PAGE[rig.language]) and calls == []
    assert rig.line(BARE, words, op("routine-cancel", {"id": "4"})) == [say(rig, "refusal")] and calls == []


@pytest.mark.parametrize("english,portuguese,word", [("add file {id}", "adiciona o arquivo {id}", "add"), ("discard attachment {id}", "descarta o arquivo {id}", "discard")])
def test_a_file_is_added_or_discarded_by_words_through_the_binding_of_the_typed_command(rig, english, portuguese, word):
    seen = []
    rig.monkeypatch.setattr(rig.bridge.attach, "typed", lambda project, chat, kind, number: seen.append((chat, kind, number)))
    words = (english if rig.language == "en" else portuguese).format(id=3)
    assert rig.line(BARE, words) == [say(rig, "refusal")] and seen == []
    assert rig.line(OWNER, words) == [] and seen == [(OWNER, word, 3)]
    assert rig.line(OWNER, f"/{word} 3") == [] and seen == [(OWNER, word, 3)] * 2


def test_the_pending_list_and_the_files_waiting_are_the_typed_commands_when_asked_in_words(rig):
    make_plan(rig)
    listed = rig.line(OWNER, "/pending")
    assert rig.line(OWNER, "mostra as pendencias" if rig.language != "en" else "show my pending decisions") == listed
    attachments = rig.line(OWNER, "/attachments")
    assert rig.line(OWNER, "meus anexos" if rig.language != "en" else "my attachments") == attachments
    assert says(rig, attachments, "CMD_ATTACHMENTS", n=0)


def test_the_conversation_keeps_a_neutral_word_for_the_reply_of_a_command_the_mcp_mode_could_not_read_itself(rig):
    ctx = ops_core.context(rig.project["path"])
    rig.line(OWNER, "my attachments" if rig.language == "en" else "meus anexos")
    rows = ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=50)
    assert is_said(rig, [m["text"] for m in rows if m["role"] == "assistant"][-1], "NAT_READ_REPLY"), "as when the files were asked for by a read in words, before the typed line"


# --- the same commands in the four other languages, through the interpreter ---------------------------------------------------------------------------------


def test_the_interpreter_carries_a_decision_named_in_any_of_the_six_languages_as_the_closed_lists_do(rig):
    questions = [make_question(rig, f"Zircon{n}") for n in (1, 2, 3, 4)]
    reviews = make_review(rig)
    plan = make_plan(rig)
    rows = [("es", f"rechaza la pregunta {questions[0]}", op("reject"), ("QUESTION_DISMISSED", {"id": questions[0]})),
            ("fr", f"refuse la question {questions[1]}", op("reject"), ("QUESTION_DISMISSED", {"id": questions[1]})),
            ("de", f"lehne die Frage {questions[2]} ab", op("reject"), ("QUESTION_DISMISSED", {"id": questions[2]})),
            ("it", f"respingi la domanda {questions[3]}", op("reject"), ("QUESTION_DISMISSED", {"id": questions[3]})),
            ("fr", f"libere la livraison {reviews}", op("release"), ("RELEASED", {"id": reviews})),
            ("de", f"genehmige die Entscheidung {plan}", op("approve"), ("NAT_DECISION_CARD", {"id": plan}))]
    for _language, line, model, (key, fields) in rows:
        assert is_said(rig, rig.line(OWNER, line, model)[-1], key, **fields), line      # an approval is the card and then its sentence
        assert len(rig.asked) == 1, line
    assert all(status_of(rig, q) != "open" for q in questions) and status_of(rig, reviews) != "open"
    assert status_of(rig, plan) == "open", "an approval is never made from words"


def test_a_sender_who_may_not_decide_is_refused_the_same_way_whatever_the_language(rig):
    plan, review = make_plan(rig), make_review(rig)
    for line, model in ((f"rechaza el plan {plan}", op("reject")), (f"libere la livraison {review}", op("release")), (f"aprueba la decision {plan}", op("approve")),
                        (f"annulla la richiesta {plan}", op("cancel", {"id": str(plan)})), (f"pausa la rutina {plan}", op("routine-pause", {"id": str(plan)}))):
        assert rig.line(BARE, line, model) == [say(rig, "refusal")], line
    assert status_of(rig, plan) == "open" and status_of(rig, review) == "open"


def test_an_answer_keeps_the_words_it_had_and_a_line_with_a_number_that_is_no_decision_does_not_become_one(rig):
    question = make_question(rig)
    assert says(rig, rig.line(OWNER, f"responda a pergunta {question} com sim", op("answer")), "IX_ANSWER_ON_QUESTION") and status_of(rig, question) == "open"
    for line in ("rejeite 25 de outubro", "libera 25h", "rejeita a pergunta 25 do dia 3/11"):      # the model named a decision; the number is a date or a time, or there are two
        assert says(rig, rig.line(OWNER, line, op("reject")), "NAT_WHICH_DECISION"), line
    for line in ("me lembra às 25h", "marca reuniao dia 25", "remind me at 25"):      # lines that other lists of code take: a reminder, an event: no decision is touched
        said = rig.line(OWNER, line, op("reject"))
        assert said and not any(pk.said(sent, key, {"language": rig.language}, id=question) for sent in said for key in ("QUESTION_DISMISSED", "REJECTED")), line
    assert status_of(rig, question) == "open" and [q["id"] for q in ops.pending(rig.project["path"])["pending"]] == [question], "the one question is the only decision, still open"


def test_a_closed_list_never_reads_a_date_a_time_or_a_stray_number_as_a_decision():
    for line in ("me lembra às 25h", "marca reuniao dia 25", "25 de outubro", "rejeito 25 de outubro", "remind me at 25", "reject 12:30", "libera as 25", "cancel 25 requests"):
        assert natural.match(line) is None, line
    assert natural.match("rejeite a pergunta 25") == {"op": "reject", "args": {"pending_id": 25}, "tier": 1}
    assert natural.match("dismiss question 25") == {"op": "reject", "args": {"pending_id": 25}, "tier": 1}
    assert natural.match("aprova o 31") == {"op": "approve", "args": {"pending_id": 31}, "tier": 1}
    assert natural.decision_numbers("rejeite a pergunta 25") == [25] and natural.decision_numbers("rejeite 25 de outubro") == []


# --- vacuity: the checks above see the effect when it is there, and a planted fault is noticed ----------------------------------------------------------------------


def test_vacuity_without_the_hand_off_the_question_stays_open_and_the_check_of_the_dismissal_sees_it(rig, monkeypatch):
    """The fault: the typed line is not handed over (the behaviour before S20 for a rejection). The same check, `status_of(...) != "open"`, then fails."""
    question = make_question(rig)
    real = ops_natural.hand_over
    monkeypatch.setattr(ops_natural, "hand_over", lambda project, ctx, line, by_bridge, sender, extras: "")
    words = f"reject question {question}" if rig.language == "en" else f"rejeite a pergunta {question}"
    rig.line(OWNER, words)
    assert status_of(rig, question) == "open", "nothing was dismissed: the check of the real tests would have failed"
    monkeypatch.setattr(ops_natural, "hand_over", real)
    rig.line(OWNER, words)
    assert status_of(rig, question) != "open", "the same line, with the hand-off, dismisses it"


def test_vacuity_an_approval_handed_over_as_the_typed_approve_is_noticed_by_the_check_that_nothing_was_approved(rig, monkeypatch):
    """The fault: `approve` is handed over like `reject` and the bridge does it. The plan is then approved by words, and `status_of(plan) == "open"` (the check of the real tests) fails."""
    plan = make_plan(rig)
    real = ops_natural._decision

    def planted(project, ctx, name, args, channel, sender, extras, *more):      # `*more`: the line, the time, `routed` and `confirmed` that BL2a's D5 passes down
        if name == "approve" and channel == "messaging":
            return ops_natural.hand_over(project, ctx, f"/approve {args['pending_id']}", True, sender, extras)
        return real(project, ctx, name, args, channel, sender, extras, *more)
    monkeypatch.setattr(ops_natural, "_decision", planted)
    monkeypatch.setattr(bridge.Bridge, "typed_line", lambda self, project, chat, typed: self.act(project, chat, "approve", int(typed.split()[1])))
    rig.line(OWNER, f"approve {plan}" if rig.language == "en" else f"aprova o {plan}")
    assert status_of(rig, plan) != "open", "the planted fault approves; the real test asserts the opposite"


# --- a decision or an act that a MODEL chose is believed only when the line says the same (review round) -----------------------------------------------------


def make_request(rig) -> int:
    return ops.request(rig.project["path"], "Invented request " + str(time.monotonic()))["request"]


def request_state(rig, number) -> str:
    return {r["id"]: r["state"] for r in ops.status(rig.project["path"])["requests"]}[number]


def probes(rig, lines):
    """The lines, in the language of the project's example (the test's own literals)."""
    return lines["en"] if rig.language == "en" else lines["pt-BR"]


CANCEL_PROBES = {"en": ["no need to cancel the request {id}", "should I cancel the request {id}?", "if it fails, cancel the request {id}", "cancel the request {id} tomorrow", "cancel request {id} and then {id}"],
                 "pt-BR": ["não precisa cancelar o pedido {id}", "devo cancelar o pedido {id}?", "se der erro, cancela o pedido {id}", "cancele o pedido {id} depois do almoço",  # validate: allow english-only -- the Portuguese lines under test
                           "cancele o pedido {id} e o {id}"]}  # validate: allow english-only -- the Portuguese lines under test


def test_a_cancel_the_model_chose_is_not_done_when_the_line_negates_asks_conditions_or_names_two_numbers(rig):
    request = make_request(rig)
    for line in probes(rig, CANCEL_PROBES):
        said = rig.line(OWNER, line.format(id=request), op("cancel", {"id": str(request)}), confirm=False)
        if natural.decision_numbers(line.format(id=request)) == [request]:      # the number rule stays: the line writes it once; what the line means is now the person's to read
            nothing_ran_before_the_ok(rig, OWNER, said, question(rig, "UNDERSTOOD_CANCEL", id=request), lambda: request_state(rig, request) != "cancelled")
        else:
            assert says(rig, said, "NAT_ASK_ID"), line
        assert request_state(rig, request) != "cancelled", line
    assert len(rig.asked) == 1


def test_a_cancel_the_model_chose_for_an_object_that_is_not_a_request_is_not_done(rig):
    request = make_request(rig)
    for line in (f"cancel task {request}", f"cancel the event {request}", f"cancela o {request}"):
        rig.line(OWNER, line, op("cancel", {"id": str(request)}), confirm=False)      # the verb and object lists are gone: a line that names another object meets the question, where the person says no
        assert request_state(rig, request) != "cancelled", line      # nothing ran before the OK
        rig.answer(OWNER, "n\u00e3o")
        assert request_state(rig, request) != "cancelled", line


STOP_PROBES = {"en": ["if it fails, stop task {id}", "don't stop task {id}", "stop task {id} of 2", "should I stop task {id}?", "never stop the task {id}"],
               "pt-BR": ["se der erro, para a tarefa {id}", "não pare a tarefa {id}", "pare a tarefa {id} de 2", "devo parar a tarefa {id}?", "nunca pare a tarefa {id}"]}  # validate: allow english-only -- the Portuguese lines under test


def test_a_stop_the_model_chose_is_not_done_for_a_condition_a_negation_a_second_number_or_a_question(rig):
    calls = []
    rig.monkeypatch.setattr(ops, "stop_task", lambda project, task_id, channel=None, sender=None: calls.append(task_id) or {"task": task_id, "already": False})
    for line in probes(rig, STOP_PROBES):
        said = rig.line(OWNER, line.format(id=3), op("stop-task", {"id": "3"}), confirm=False)
        assert calls == [], line      # nothing ran before the OK
        assert (said == [question(rig, "UNDERSTOOD_STOP_TASK", id=3)] if natural.decision_numbers(line.format(id=3)) == [3] else says(rig, said, "NAT_ASK_ID")), line
        rig.answer(OWNER, "n\u00e3o")
        assert calls == [], line


def test_the_same_acts_are_done_when_the_line_says_them_plainly_though_no_closed_form_takes_the_line(rig):
    request = make_request(rig)
    stopped, retried = [], []
    rig.monkeypatch.setattr(ops, "stop_task", lambda project, task_id, channel=None, sender=None: stopped.append(task_id) or {"task": task_id, "already": False})
    rig.monkeypatch.setattr(ops, "retry", lambda project, task_id, channel=None, sender=None: retried.append(task_id) or {"task_id": task_id})
    cancel, stop, retry = (("please cancel the request number {id}", "please stop task {id}", "please retry the task {id}") if rig.language == "en" else
                           ("por favor, cancele a solicitação número {id}", "por favor, pare a tarefa {id}", "por favor, tente a tarefa {id} de novo"))  # validate: allow english-only -- the Portuguese lines under test
    assert says(rig, rig.line(OWNER, cancel.format(id=request), op("cancel", {"id": str(request)})), "CMD_CANCELLED", n=request) and request_state(rig, request) == "cancelled"
    assert says(rig, rig.line(OWNER, stop.format(id=3), op("stop-task", {"id": "3"})), "CMD_TASK_STOPPED", n=3) and stopped == [3]
    assert says(rig, rig.line(OWNER, retry.format(id=3), op("retry", {"id": "3"})), "CMD_TASK_RETRY", n=3) and retried == [3]


def test_a_routine_pause_the_model_chose_is_not_done_for_a_negation_or_a_condition(rig):
    calls = []
    rig.monkeypatch.setattr(ops, "routine_pause", lambda project, routine_id, channel=None, sender=None: calls.append(routine_id) or {})
    for line in (("don't pause routine 4", "pause routine 4 if it runs late", "should I pause routine 4?") if rig.language == "en" else
                 ("não pause a rotina 4", "pause a rotina 4 se atrasar", "devo pausar a rotina 4?")):  # validate: allow english-only -- the Portuguese lines under test
        said = rig.line(OWNER, line, op("routine-pause", {"id": "4"}), confirm=False)
        assert calls == [] and said == [question(rig, "UNDERSTOOD_ROUTINE_PAUSE", id=4)], line      # nothing ran before the OK
        rig.answer(OWNER, "n\u00e3o")
        assert calls == [], line


DECISION_PROBES = {"en": ["don't reject question {id}", "reject the question from 3 days ago", "reject the question 2 hours ago", "if it is late, reject question {id}",
                          "should I reject question {id}?", "reject 25%"],
                   "pt-BR": ["não rejeite a pergunta {id}", "rejeite a pergunta de 3 dias atrás", "rejeite a pergunta há 2 horas",  # validate: allow english-only -- the Portuguese lines under test
                             "se estiver atrasada, rejeite a pergunta {id}", "devo rejeitar a pergunta {id}?", "rejeite 25%"]}  # validate: allow english-only -- the Portuguese lines under test


def test_a_rejection_the_model_chose_is_not_done_for_a_negation_a_relative_time_a_condition_a_question_or_a_percentage(rig):
    question_id = make_question(rig)
    for line in probes(rig, DECISION_PROBES):
        said = rig.line(OWNER, line.format(id=question_id), op("reject"), confirm=False)
        if natural.decision_numbers(line.format(id=question_id)) == [question_id]:      # the number rule stays; the meaning is the person's to read in the question
            nothing_ran_before_the_ok(rig, OWNER, said, question(rig, "UNDERSTOOD_REJECT", id=question_id), lambda: status_of(rig, question_id) == "open")
        else:
            assert says(rig, said, "NAT_WHICH_DECISION"), (line, said)
        assert status_of(rig, question_id) == "open", line


def test_vacuity_without_the_check_of_the_number_in_the_line_a_cancel_with_two_numbers_is_asked_and_done(rig, monkeypatch):
    """The fault: the vetting of the model's number is gone (the first S20 version). A line with two numbers, of which the model chose one, then reaches the question and, with the person's "sim", acts on
    the one the model picked: the real behaviour (the number rule stays, L54) asks which number and does nothing."""
    first, second = make_request(rig), make_request(rig)
    line = f"cancel requests {first} and {second}" if rig.language == "en" else f"cancele os pedidos {first} e {second}"
    assert says(rig, rig.line(OWNER, line, op("cancel", {"id": str(first)})), "NAT_ASK_ID") and request_state(rig, first) != "cancelled"
    monkeypatch.setattr(turn_gate, "number_believed", lambda line_, number: True)      # S41-5: the vet moved from command_words.vet (returned None) to the gate
    assert says(rig, rig.line(OWNER, line, op("cancel", {"id": str(first)})), "CMD_CANCELLED", n=first)
    assert request_state(rig, first) == "cancelled" and request_state(rig, second) != "cancelled"


def test_a_percentage_a_price_or_a_quantity_is_not_the_number_of_a_decision_in_a_closed_form_or_in_a_line():
    for line in ("rejeite 25%", "rejeite $25", "reject 25 euros", "rejeite R$ 25", "reject 25 %"):
        assert natural.match(line) is None, line
    assert natural.match("rejeite a pergunta 25")["args"] == {"pending_id": 25}
    for line, wanted in (("rejeite a pergunta de 3 dias atrás", []), ("há 2 horas rejeite a 1", [1]), ("reject question 5 3 days ago", [5]), ("em 2 semanas", []), ("reject 3 times", [])):
        assert natural.decision_numbers(line) == wanted, line
