"""Every command a messaging sender can type can be asked for in words (slice S20, limits L54 and L64), through the real messaging bridge, the stand-in Telegram provider, the real
operations layer over the stand-in tree and a stand-in model for the interpreter. Offline, no network; every name, number and sender is invented.

The maintainer's words, 2026-10-22: he sent "rejeite a pergunta 25" and was told to use the buttons of the card, while `/reject 25` worked; "Devemos ser capaz de acionar QUALQUER comando
utilizando linguagem natural". The rule these tests pin: a command asked for in words is the typed command (the same policy check, the same refusals, the same effect), except that
`approve` is never made from words (the decision's card is sent again) and `answer` keeps the words it had. The bridge side (the typed line is handled as typed, no model slot) is
in test_commands_in_words_bridge.py; the pure reading of "muda para o projeto" is in test_command_words.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_commands_in_words.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL, PLAIN_REFUSAL_PT  # noqa: E402

import json
import shutil
import time

import pytest

import standin_tree as st
from test_ask import accept
from test_interpret_router_frame import QUESTION
from test_messaging_ask import FIXTURE, wait_for
from test_ops_natural import KEY, OWNER, PROFILES, docs, router_says, with_senders, world  # noqa: F401
from test_service import WAIT

ops = st.load("ops")
ops_core = st.load("ops_core")
bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")
ops_interpret = st.load("ops_interpret")
interpreter_route = st.load("interpreter_route")
natural = st.load("natural")
command_words = st.load("command_words")
ops_natural = st.load("ops_natural")

ZONE = "America/Sao_Paulo"
BARE, OTHER = "55119000000007", "55119000000008"
FLOW = "Route: flow-demo (flow, pending)\nWhy: a market question\nNext: the market task.\n"
PROFILES2 = {**PROFILES, "owner": PROFILES["owner"] + ["interpret", "routine-brakes"], "bare": ["read", "talk", "interpret"], "other": PROFILES["owner"] + ["interpret"]}
SENDERS2 = {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": BARE, "policy": "bare"}, {"id": OTHER, "policy": "other"}]}
# what each sentence is, per language: the test's own literals
SAY = {
    "en": {"dismissed": "Question #{id} dismissed.", "rejected": "Rejected #{id}.", "released": "Released #{id}.", "cancelled": "Request {id} cancelled.",
           "stopped": "Task {id} stopped.", "retried": "Task {id} is ready to run again.", "paused": "Routine {id} paused.", "routine_cancelled": "Routine {id} cancelled.",
           "no_decision": "There is no open decision #{id}.", "which": "Which decision? Say its number in the same line.",
           "refusal": PLAIN_REFUSAL, "approved": "Approved #{id}.",
           "card": ('A decision is approved from its card, never from a line of words: I sent the card of #{id} again so that you see exactly what you approve; '
                    'approve it with its button, or by saying "approve" right after it.'), "no_card": "Act on the card sent to you (send /pending).", "again": "I was not sure what you meant, so I did nothing. Can you say it another way?", "which_number": "Which number? Say it again with the number in the line.",
           "no_card_sent": ("A decision is made from its card, never from a line of words, and its card could not be sent now. Send /pending.")},
    "pt-BR": {"dismissed": "Pergunta #{id} dispensada.", "rejected": "#{id} rejeitada.", "released": "#{id} liberada.", "cancelled": "Pedido {id} cancelado.",
              "stopped": "Tarefa {id} parada.", "retried": "A tarefa {id} está pronta para rodar de novo.", "paused": "Rotina {id} pausada.",  # validate: allow english-only -- the Portuguese sentences under test
              "routine_cancelled": "Rotina {id} cancelada.", "no_decision": "Não há decisão aberta #{id}.", "which": "Qual decisão? Diga o número dela na mesma frase.",  # validate: allow english-only -- the Portuguese sentences under test
              "card": ('Uma decisão se aprova pelo card, nunca por uma frase: enviei de novo o card de #{id} para você ver exatamente o que aprova; '  # validate: allow english-only -- the Portuguese sentences under test
                       'aprove pelo botão dele, ou dizendo "aprovo" logo depois.'), "no_card": "Use o card que foi enviado a você (envie /pending).", "refusal": PLAIN_REFUSAL_PT, "approved": "#{id} aprovada.",  # validate: allow english-only -- the Portuguese sentences under test
              "again": "Não tive certeza do que você quis dizer, então não fiz nada. Pode dizer de outro jeito?", "which_number": "Qual número? Diga de novo com o número na mensagem.",  # validate: allow english-only -- the Portuguese sentences under test
              "no_card_sent": "Uma decisão é tomada pelo card, nunca por uma frase, e o card não pôde ser enviado agora. Envie /pending."},  # validate: allow english-only -- the Portuguese sentences under test
}


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

    def line(who, text, model=None):
        """The sender types `text`; the bridge's jobs end; what was sent to that sender's chat since is returned."""
        before = len([s for s in sent() if s["chat"] == who])
        r.asked.clear()
        r.model["text"] = model or '{"v":1,"kind":"none"}'
        r.bridge.handle({"update_id": 1, "sender": who, "chat": who, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None})
        assert wait_for(lambda: not r.bridge.exclusive and all(not t.is_alive() for t in r.bridge.threads))
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


def bridge_wants_nothing(rig) -> str:
    """The bridge sends a card only to a sender whose profile is sent that decision (`notices: actionable`): the other chat gets the sentence that says the card could not be sent."""
    rig.bridge.wants = lambda project, settings, item, sender: sender == OWNER      # the test's own stand-in for a profile that is sent nothing of this decision
    return say(rig, "no_card_sent")


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
    assert rig.line(OWNER, words.format(id=first)) == [say(rig, "dismissed").format(id=first)] and rig.asked == [], "code took the line: no model was asked"
    assert status_of(rig, first) != "open"
    assert rig.line(OWNER, f"/reject {second}") == [say(rig, "dismissed").format(id=second)] and status_of(rig, second) != "open"


def test_the_line_of_the_live_test_in_portuguese_dismisses_question_25_when_the_stand_in_model_reads_it(rig):
    """"rejeite a pergunta 25" did not reach the closed list in the live test (the model named `reject` and was told to use the card); now it is the typed reject, from either path."""
    questions = [make_question(rig, f"Zircon{n}") for n in (1, 2, 3)]
    target = questions[-1]
    line = f"rejeite a pergunta {target}"
    assert rig.line(OWNER, line, op("reject")) == [say(rig, "dismissed").format(id=target)] and status_of(rig, target) != "open"
    rig.asked.clear()
    assert rig.line(OWNER, "por favor, dispense a pergunta " + str(questions[0]), op("reject")) == [say(rig, "dismissed").format(id=questions[0])]  # validate: allow english-only -- the Portuguese line under test
    assert len(rig.asked) == 1, "this one is not a closed form: the model named the operation, code read the number, and the line's own verb says the same"


@pytest.mark.parametrize("english,portuguese", [("reject plan {id}", "rejeite o plano {id}"), ("decline the decision number {id}", "recuse a decisao numero {id}")])
def test_a_plan_is_rejected_by_words_as_the_typed_reject_rejects_it_and_only_in_the_chat_it_was_sent_to(rig, english, portuguese):
    plan = make_plan(rig)
    other_plan = make_plan(rig)
    words = (english if rig.language == "en" else portuguese).format(id=plan)
    assert rig.card_for(plan, OWNER) and rig.card_for(plan, OTHER) and not rig.card_for(plan, BARE), "a sender with no group to decide is sent no card"
    assert rig.line(BARE, words) == [say(rig, "refusal")] and status_of(rig, plan) == "open", "a sender without the group is refused, as the typed line refuses it"
    assert rig.line(OWNER, words) == [say(rig, "rejected").format(id=plan)] and status_of(rig, plan) != "open"
    assert rig.line(OWNER, f"/reject {other_plan}") == [say(rig, "rejected").format(id=other_plan)] and status_of(rig, other_plan) != "open"
    assert rig.line(OWNER, words) == [say(rig, "no_decision").format(id=plan)], "a number that is not an open decision gets the one sentence"


def test_a_decision_never_sent_to_the_chat_is_not_rejected_by_words_either(rig):
    plan = make_plan(rig)
    router_says(rig.world, FLOW)
    later = ops.say(rig.project["path"], "/new Which market first? again", channel="page")["pending_id"]      # no tick: no card of it went to any chat
    words = f"reject plan {later}" if rig.language == "en" else f"rejeite o plano {later}"
    assert rig.line(OTHER, words) == [say(rig, "no_card")] and status_of(rig, later) == "open"
    assert rig.line(OTHER, f"/reject {later}") == [say(rig, "no_card")]
    assert status_of(rig, plan) == "open"


@pytest.mark.parametrize("english,portuguese", [("release the delivery {id}", "libere a entrega {id}"), ("release {id}", "libera {id}")])
def test_a_delivery_is_released_by_words_as_the_typed_release_releases_it(rig, english, portuguese):
    review, other = make_review(rig), make_review(rig)
    words = (english if rig.language == "en" else portuguese).format(id=review)
    assert rig.line(BARE, words) == [say(rig, "refusal")] and status_of(rig, review) == "open"
    assert rig.line(OWNER, words) == [say(rig, "released").format(id=review)] and status_of(rig, review) != "open"
    assert rig.line(OWNER, f"/release {other}") == [say(rig, "released").format(id=other)] and status_of(rig, other) != "open"


# --- approve is never made from words: the card is sent again, once --------------------------------------------------------------------------------------


@pytest.mark.parametrize("english,portuguese", [("approve {id}", "aprova o {id}"), ("approve the plan {id}", "aprove o plano {id}"), ("accept decision {id}", "aceite a decisao {id}")])
def test_an_approve_line_sends_the_card_again_and_approves_nothing_then_the_word_that_follows_approves_it(rig, english, portuguese):
    plan = make_plan(rig)
    words = (english if rig.language == "en" else portuguese).format(id=plan)
    cards = len(rig.card_for(plan, OWNER))
    out = rig.line(OWNER, words)
    assert len(out) == 2 and out[0].startswith("northwind-shop · ") and out[1] == say(rig, "card").format(id=plan), "the card of that decision once more, then the one sentence"
    assert len(rig.card_for(plan, OWNER)) == cards + 1
    assert status_of(rig, plan) == "open" and ops.status(rig.project["path"])["requests"][-1]["state"] == "requested", "nothing was approved"
    assert rig.line(OWNER, "approve" if rig.language == "en" else "aprovo") == [say(rig, "approved").format(id=plan)], "the word right after the card approves it (S2)"
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
    assert out[-1] == say(rig, "card").format(id=later) and status_of(rig, later) == "open" and status_of(rig, plan) == "open"
    with_policy = bridge_wants_nothing(rig)
    assert rig.line(OTHER, words) == [with_policy], "a chat the bridge does not send that card to"


def test_an_approve_line_with_no_number_or_with_a_date_asks_which_and_sends_nothing(rig):
    make_plan(rig)
    cards = len(rig.sent())
    assert rig.line(OWNER, "aprueba el plan", op("approve")) == [say(rig, "which")]
    assert rig.line(OWNER, "aprova até 25 de outubro", op("approve")) == [say(rig, "which")]
    assert rig.line(OWNER, "libera os 3 e 4", op("release")) == [say(rig, "which")]
    assert len(rig.sent()) == cards + 3


# --- the other acts: the typed command is run, by its words ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("english,portuguese", [("cancel request {id}", "cancela o pedido {id}"), ("cancel the request number {id}", "cancele o pedido numero {id}")])
def test_a_request_is_cancelled_by_words_as_the_typed_cancel_cancels_it(rig, english, portuguese):
    first, second = (ops.request(rig.project["path"], f"Invented request {n}")["request"] for n in (1, 2))
    words = (english if rig.language == "en" else portuguese).format(id=first)
    assert rig.line(BARE, words) == [say(rig, "refusal")] and rig.line(BARE, f"/cancel {first}") == [say(rig, "refusal")]
    assert rig.line(OWNER, words) == [say(rig, "cancelled").format(id=first)]
    assert rig.line(OWNER, f"/cancel {second}") == [say(rig, "cancelled").format(id=second)]
    states = {r["id"]: r["state"] for r in ops.status(rig.project["path"])["requests"]}
    assert states[first] == states[second] == "cancelled"
    assert rig.line(OWNER, words) == [say(rig, "cancelled").format(id=first).replace("cancelled", "was already cancelled") if rig.language == "en" else "O pedido " + str(first) + " já estava cancelado."]  # validate: allow english-only -- the Portuguese sentence under test


@pytest.mark.parametrize("function,english,portuguese,key", [("stop_task", "stop task {id}", "para a tarefa {id}", "stopped"), ("retry", "retry task {id}", "tenta de novo a tarefa {id}", "retried")])
def test_a_task_is_stopped_or_retried_by_words_with_the_call_the_typed_command_makes(rig, function, english, portuguese, key):
    calls = []
    rig.monkeypatch.setattr(ops, function, lambda project, task_id, channel=None, sender=None: calls.append((task_id, channel, sender)) or {"task_id": task_id, "task": task_id, "already": False})
    command = "/" + ("stop-task" if function == "stop_task" else "retry")
    words = (english if rig.language == "en" else portuguese).format(id=7)
    assert rig.line(BARE, words) == [say(rig, "refusal")] and rig.line(BARE, f"{command} 7") == [say(rig, "refusal")] and calls == []
    assert rig.line(OWNER, words) == [say(rig, key).format(id=7)]
    assert rig.line(OWNER, f"{command} 7") == [say(rig, key).format(id=7)]
    assert calls == [(7, "messaging", KEY["owner"])] * 2, "the same call, the same channel and sender"


@pytest.mark.parametrize("english,portuguese", [("pause routine {id}", "pausa a rotina {id}"), ("pause the routine number {id}, please", "pause a rotina numero {id}, por favor")])
def test_a_routine_is_paused_by_words_after_the_same_policy_check_and_the_actor_is_recorded(rig, english, portuguese):
    calls = []
    rig.monkeypatch.setattr(ops, "routine_pause", lambda project, routine_id, channel=None, sender=None: calls.append((routine_id, channel, sender)) or {"routine": routine_id})
    words = (english if rig.language == "en" else portuguese).format(id=4)
    assert rig.line(BARE, words, op("routine-pause", {"id": "4"})) == [say(rig, "refusal")] and calls == []
    assert rig.line(OWNER, words, op("routine-pause", {"id": "4"})) == [say(rig, "paused").format(id=4)] and calls == [(4, "messaging", KEY["owner"])]


@pytest.mark.parametrize("english,portuguese", [("cancel routine {id}", "cancela a rotina {id}"), ("cancel the routine {id} for good", "cancele a rotina {id} de vez")])
def test_a_routine_is_never_cancelled_by_words_the_reply_says_to_pause_it_here_and_cancel_it_on_the_page(rig, english, portuguese):
    calls = []
    rig.monkeypatch.setattr(ops, "routine_cancel", lambda project, routine_id: calls.append(routine_id) or {})
    rig.monkeypatch.setattr(ops, "routine_pause", lambda project, routine_id, channel=None, sender=None: calls.append(("pause", routine_id)) or {})
    page = ('To stop a routine for now, say "pause routine" and its number. A routine is cancelled for good on the platform\'s page.' if rig.language == "en" else
            'Para parar uma rotina por enquanto, diga "pausa a rotina" e o número dela. Uma rotina se cancela de vez na página da plataforma.')  # validate: allow english-only -- the Portuguese sentence under test
    words = (english if rig.language == "en" else portuguese).format(id=4)
    assert rig.line(OWNER, words, op("routine-cancel", {"id": "4"})) == [page] and calls == []
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
    assert attachments == ["Files waiting for your answer: 0."] or attachments == ["Arquivos esperando sua resposta: 0."]


def test_the_conversation_keeps_a_neutral_word_for_the_reply_of_a_command_the_mcp_mode_could_not_read_itself(rig):
    ctx = ops_core.context(rig.project["path"])
    rig.line(OWNER, "my attachments" if rig.language == "en" else "meus anexos")
    rows = ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=50)
    assert [m["text"] for m in rows if m["role"] == "assistant"][-1] == ("(shown where it was asked)" if rig.language == "en" else "(mostrado onde foi pedido)"), "as when the files were asked for by a read in words, before the typed line"  # validate: allow english-only -- the Portuguese sentence under test


# --- the same commands in the four other languages, through the interpreter ---------------------------------------------------------------------------------


def test_the_interpreter_carries_a_decision_named_in_any_of_the_six_languages_as_the_closed_lists_do(rig):
    questions = [make_question(rig, f"Zircon{n}") for n in (1, 2, 3, 4)]
    reviews = make_review(rig)
    plan = make_plan(rig)
    rows = [("es", f"rechaza la pregunta {questions[0]}", op("reject"), [say(rig, "dismissed").format(id=questions[0])]),
            ("fr", f"refuse la question {questions[1]}", op("reject"), [say(rig, "dismissed").format(id=questions[1])]),
            ("de", f"lehne die Frage {questions[2]} ab", op("reject"), [say(rig, "dismissed").format(id=questions[2])]),
            ("it", f"respingi la domanda {questions[3]}", op("reject"), [say(rig, "dismissed").format(id=questions[3])]),
            ("fr", f"libere la livraison {reviews}", op("release"), [say(rig, "released").format(id=reviews)]),
            ("de", f"genehmige die Entscheidung {plan}", op("approve"), [say(rig, "card").format(id=plan)])]
    for _language, line, model, wanted in rows:
        assert rig.line(OWNER, line, model)[-len(wanted):] == wanted, line      # an approval is the card and then its sentence
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
    sentence = "A question is answered by replying to it: write your answer." if rig.language == "en" else "Uma pergunta se responde respondendo a ela: escreva a sua resposta."  # validate: allow english-only -- the Portuguese sentence under test
    assert rig.line(OWNER, f"responda a pergunta {question} com sim", op("answer")) == [sentence] and status_of(rig, question) == "open"
    for line in ("rejeite 25 de outubro", "libera 25h", "rejeita a pergunta 25 do dia 3/11"):      # the model named a decision; the number is a date or a time, or there are two
        assert rig.line(OWNER, line, op("reject")) == [say(rig, "which")], line
    for line in ("me lembra às 25h", "marca reuniao dia 25", "remind me at 25"):      # lines that other lists of code take: a reminder, an event: no decision is touched
        said = rig.line(OWNER, line, op("reject"))
        assert said and all(sentence not in said for sentence in (say(rig, "dismissed").format(id=question), say(rig, "rejected").format(id=question))), line
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

    def planted(project, ctx, name, args, channel, sender, extras):
        if name == "approve" and channel == "messaging":
            return ops_natural.hand_over(project, ctx, f"/approve {args['pending_id']}", True, sender, extras)
        return real(project, ctx, name, args, channel, sender, extras)
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
        said = rig.line(OWNER, line.format(id=request), op("cancel", {"id": str(request)}))
        assert said == [say(rig, "again")] or said == [say(rig, "which_number")], line
        assert request_state(rig, request) != "cancelled", line
    assert len(rig.asked) == 1


def test_a_cancel_the_model_chose_for_an_object_that_is_not_a_request_is_not_done(rig):
    request = make_request(rig)
    for line in (f"cancel task {request}", f"cancel the event {request}", f"cancela o {request}"):
        rig.line(OWNER, line, op("cancel", {"id": str(request)}))
        assert request_state(rig, request) != "cancelled", line


STOP_PROBES = {"en": ["if it fails, stop task {id}", "don't stop task {id}", "stop task {id} of 2", "should I stop task {id}?", "never stop the task {id}"],
               "pt-BR": ["se der erro, para a tarefa {id}", "não pare a tarefa {id}", "pare a tarefa {id} de 2", "devo parar a tarefa {id}?", "nunca pare a tarefa {id}"]}  # validate: allow english-only -- the Portuguese lines under test


def test_a_stop_the_model_chose_is_not_done_for_a_condition_a_negation_a_second_number_or_a_question(rig):
    calls = []
    rig.monkeypatch.setattr(ops, "stop_task", lambda project, task_id, channel=None, sender=None: calls.append(task_id) or {"task": task_id, "already": False})
    for line in probes(rig, STOP_PROBES):
        rig.line(OWNER, line.format(id=3), op("stop-task", {"id": "3"}))
        assert calls == [], line


def test_the_same_acts_are_done_when_the_line_says_them_plainly_though_no_closed_form_takes_the_line(rig):
    request = make_request(rig)
    stopped, retried = [], []
    rig.monkeypatch.setattr(ops, "stop_task", lambda project, task_id, channel=None, sender=None: stopped.append(task_id) or {"task": task_id, "already": False})
    rig.monkeypatch.setattr(ops, "retry", lambda project, task_id, channel=None, sender=None: retried.append(task_id) or {"task_id": task_id})
    cancel, stop, retry = (("please cancel the request number {id}", "please stop task {id}", "please retry the task {id}") if rig.language == "en" else
                           ("por favor, cancele a solicitação número {id}", "por favor, pare a tarefa {id}", "por favor, tente a tarefa {id} de novo"))  # validate: allow english-only -- the Portuguese lines under test
    assert rig.line(OWNER, cancel.format(id=request), op("cancel", {"id": str(request)})) == [say(rig, "cancelled").format(id=request)] and request_state(rig, request) == "cancelled"
    assert rig.line(OWNER, stop.format(id=3), op("stop-task", {"id": "3"})) == [say(rig, "stopped").format(id=3)] and stopped == [3]
    assert rig.line(OWNER, retry.format(id=3), op("retry", {"id": "3"})) == [say(rig, "retried").format(id=3)] and retried == [3]


def test_a_routine_pause_the_model_chose_is_not_done_for_a_negation_or_a_condition(rig):
    calls = []
    rig.monkeypatch.setattr(ops, "routine_pause", lambda project, routine_id, channel=None, sender=None: calls.append(routine_id) or {})
    for line in (("don't pause routine 4", "pause routine 4 if it runs late", "should I pause routine 4?") if rig.language == "en" else
                 ("não pause a rotina 4", "pause a rotina 4 se atrasar", "devo pausar a rotina 4?")):  # validate: allow english-only -- the Portuguese lines under test
        rig.line(OWNER, line, op("routine-pause", {"id": "4"}))
        assert calls == [], line


DECISION_PROBES = {"en": ["don't reject question {id}", "reject the question from 3 days ago", "reject the question 2 hours ago", "if it is late, reject question {id}",
                          "should I reject question {id}?", "reject 25%"],
                   "pt-BR": ["não rejeite a pergunta {id}", "rejeite a pergunta de 3 dias atrás", "rejeite a pergunta há 2 horas",  # validate: allow english-only -- the Portuguese lines under test
                             "se estiver atrasada, rejeite a pergunta {id}", "devo rejeitar a pergunta {id}?", "rejeite 25%"]}  # validate: allow english-only -- the Portuguese lines under test


def test_a_rejection_the_model_chose_is_not_done_for_a_negation_a_relative_time_a_condition_a_question_or_a_percentage(rig):
    question = make_question(rig)
    for line in probes(rig, DECISION_PROBES):
        said = rig.line(OWNER, line.format(id=question), op("reject"))
        assert said in ([say(rig, "again")], [say(rig, "which")]), (line, said)
        assert status_of(rig, question) == "open", line


def test_vacuity_without_the_check_of_the_line_the_negated_cancel_and_the_negated_rejection_are_done(rig, monkeypatch):
    """The fault: the vetting of the model's reading is gone (the first S20 version). The same probes then act, and the checks above would have failed."""
    request, question = make_request(rig), make_question(rig)
    monkeypatch.setattr(command_words, "vet", lambda line, op_, number: None)
    cancel, reject = (("no need to cancel the request {id}", "don't reject question {id}") if rig.language == "en" else
                      ("não precisa cancelar o pedido {id}", "não rejeite a pergunta {id}"))  # validate: allow english-only -- the Portuguese lines under test
    rig.line(OWNER, cancel.format(id=request), op("cancel", {"id": str(request)}))
    rig.line(OWNER, reject.format(id=question), op("reject"))
    assert request_state(rig, request) == "cancelled" and status_of(rig, question) != "open"


def test_a_percentage_a_price_or_a_quantity_is_not_the_number_of_a_decision_in_a_closed_form_or_in_a_line():
    for line in ("rejeite 25%", "rejeite $25", "reject 25 euros", "rejeite R$ 25", "reject 25 %"):
        assert natural.match(line) is None, line
    assert natural.match("rejeite a pergunta 25")["args"] == {"pending_id": 25}
    for line, wanted in (("rejeite a pergunta de 3 dias atrás", []), ("há 2 horas rejeite a 1", [1]), ("reject question 5 3 days ago", [5]), ("em 2 semanas", []), ("reject 3 times", [])):
        assert natural.decision_numbers(line) == wanted, line
