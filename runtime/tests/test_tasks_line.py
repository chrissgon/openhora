"""The to-do list asked in words, on a messaging app (package CB-5: runtime/ops_todo.py `reply` and `reply_list`, the branch of runtime/ops_interpret.py `_carry_out`, the gate rows of
runtime/turn_gate.py, the sentence of runtime/plan_confirm.py), end to end against the stand-in services of providers/tasks/tests/ (see test_tasks_ops.py) and a stand-in of the
interpreter's model service that answers the one line each test reads. The catalog is at version 2 for these tests only (`operations.LINE_CATALOG` patched, the served catalog and
the views regenerated from the rows): at version 1 a line reaches none of the three operations, and a test holds that too.

What is held here: "adiciona comprar café na minha lista de tarefas" opens the card of the task and writes nothing before the approval; a title that is not a span of the line opens no card;
a planted origin or argument is refused by the gate and no card is opened (fail closed: limits L55 and L61); an account with no `task_lists` makes nothing; a sender without the group is
refused and one with `tasks-write` and not `tasks-read` cannot complete by words; the list asks "Posso?" first and then numbers the tasks, and "marca o 2 como feita" completes the second one
of THAT list; a reminder line is a reminder and never a task; at catalog version 1 no line reaches a task operation.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_tasks_line.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_tasks_ops import (GOOGLE, MICROSOFT, OTHER, SENDER, approve, calls_of, configure, effect_doc, fg, fm, item_of, open_decisions, world, writes)  # noqa: F401  (the fixture and its helpers)

interpreter = st.load("interpreter")
interpreter_catalog = st.load("interpreter_catalog")
interpreter_enable = st.load("interpreter_enable")
interpreter_route = st.load("interpreter_route")
natural = st.load("natural")
operations = st.load("operations")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_todo = st.load("ops_todo")
phrases = st.load("phrases")
plan_confirm = st.load("plan_confirm")
turn_gate = st.load("turn_gate")

ZONE = "America/Sao_Paulo"
READER, WRITER, PLAIN, TASKER, MAILER = "telegram:888", "telegram:999", "telegram:777", "telegram:555", "telegram:556"
PT = {"cfg": {"language": "pt-BR"}}


def flip(monkeypatch, version=2):
    """The catalog at `version` for the interpreter: the operations table, the views, the served catalog and the enabling entry that pins it (as CB-9 will write it)."""
    real = interpreter_enable.active("pt-BR")
    monkeypatch.setattr(operations, "LINE_CATALOG", version)
    classes, table = natural.views(version)
    monkeypatch.setattr(natural, "CLASSES", classes)
    monkeypatch.setattr(natural, "NATURAL", table)
    served = interpreter_catalog.generate(version=version)
    monkeypatch.setattr(interpreter, "SERVED", served)
    monkeypatch.setattr(interpreter, "SERVED_SHA256", interpreter.catalog_sha256(served))
    monkeypatch.setattr(interpreter_enable, "active", lambda tag: real)


@pytest.fixture
def desk(world, monkeypatch):  # noqa: F811
    flip(monkeypatch)
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()
    answer = {"text": ""}
    monkeypatch.setattr(interpreter_route, "complete", lambda route_id, system, user, **kw: {"ok": True, "text": answer["text"], "finish": "stop", "usage": {}, "latency_ms": 5})
    world["answer"] = answer
    configure(world, accounts={"google": GOOGLE, "microsoft": MICROSOFT, "default": "google"}, **{})
    return world


def profiles(world):
    """Every profile of test_tasks_ops gets `interpret` (the group that lets a plain line reach the model service), the owner also `ask-mail` (a completion's card shows the title of a task
    the service holds, which a messaging app draws only for a sender who may read the person's own items), `tasker` reads and writes the lists and holds no `ask-mail` (a task title is
    gated by `tasks-read`: its card key names its own group), and `mailer` holds `ask-mail` and `tasks-write` and not `tasks-read`; the file is accepted."""
    from test_ask import accept
    from test_tasks_ops import PROFILES, SENDERS
    groups = {name: list(g) + ["interpret"] for name, g in PROFILES.items()}
    groups["owner"] += ["ask", "ask-mail"]
    groups["tasker"] = ["read", "talk", "interpret", "tasks-read", "tasks-write", "approve-effect-tasks"]
    groups["mailer"] = ["read", "talk", "interpret", "ask-mail", "tasks-write", "approve-effect-tasks"]
    senders = {"telegram": SENDERS["telegram"] + [{"id": "555", "policy": "tasker"}, {"id": "556", "policy": "mailer"}]}
    accept(world["path"], accounts={"google": GOOGLE, "microsoft": MICROSOFT, "default": "google"}, policies=groups, messaging={"senders": senders}, language="pt-BR")


def answer_op(world, op, **slots):
    world["answer"]["text"] = json.dumps({"v": 1, "kind": "op", "op": op, "slots": slots})


def say(world, line, key=SENDER, **kw):
    return ops.say(world["path"], line, channel="messaging", sender=key, **kw)


@pytest.fixture
def ready(desk):
    profiles(desk)
    return desk


# --- add ----------------------------------------------------------------------------------------------------------------------------------


def test_a_line_that_adds_a_task_opens_the_card_and_writes_nothing_before_the_approval(ready):
    answer_op(ready, "todo-add", title="comprar café")
    said = say(ready, "adiciona comprar café na minha lista de tarefas")
    assert said.get("resend") is not None and phrases.text("ACCT_CARD_SENT", PT["cfg"], pending=said["resend"]) in said["reply"]
    started = {"pending": said.get("resend"), "task": item_of(ready, {"pending": said.get("resend")})["task_id"]}
    doc = effect_doc(ready, started)
    assert doc["operation"] == "add" and doc["title"] == "comprar café" and doc["list"] == "tarefas" and doc["asker"] == SENDER and doc["account"] == "google"
    assert item_of(ready, started)["title"] == "Tasks: add a task"
    assert writes(ready["google"]) == [] and writes(ready["microsoft"]) == []
    done = approve(ready, started, channel="messaging", sender=SENDER)
    assert done["result"]["done"] is True
    assert [(m, p, b) for m, p, _q, b in writes(ready["google"])] == [("POST", "/tasks/v1/lists/@default/tasks", {"title": "comprar café"})]


def test_a_service_word_of_the_line_chooses_the_account_and_a_word_no_table_knows_asks_again(ready):
    answer_op(ready, "todo-add", title="enviar o relatório", service="microsoft")
    said = say(ready, "adiciona enviar o relatório na minha lista microsoft")
    assert said.get("resend") is not None
    assert effect_doc(ready, {"pending": said.get("resend"), "task": item_of(ready, {"pending": said.get("resend")})["task_id"]})["account"] == "microsoft"
    answer_op(ready, "todo-add", title="ligar", service="notion")
    again = say(ready, "adiciona ligar na minha lista notion")
    assert again.get("resend") is None and phrases.text("IX_ASK_AGAIN", PT["cfg"]) in again["reply"]


def test_without_a_service_word_the_default_account_is_used_and_two_accounts_with_no_default_ask(ready):
    answer_op(ready, "todo-add", title="comprar café")
    said = say(ready, "adiciona comprar café na lista")
    assert effect_doc(ready, {"pending": said.get("resend"), "task": item_of(ready, {"pending": said.get("resend")})["task_id"]})["account"] == "google"      # accounts.default
    from test_ask import accept
    from test_tasks_ops import PROFILES, SENDERS
    accept(ready["path"], accounts={"google": GOOGLE, "microsoft": MICROSOFT}, policies={k: v + ["interpret"] for k, v in PROFILES.items()}, messaging={"senders": SENDERS}, language="pt-BR")
    before = len(open_decisions(ready))
    asked = say(ready, "adiciona comprar café na lista")
    assert asked.get("resend") is None and phrases.text("TODO_ASK_ACCOUNT", PT["cfg"]) in asked["reply"] and len(open_decisions(ready)) == before


def test_a_title_that_is_not_a_span_of_the_line_opens_no_card(ready):
    answer_op(ready, "todo-add", title="comprar vinho")
    said = say(ready, "adiciona comprar café na minha lista de tarefas")
    assert said.get("resend") is None and open_decisions(ready) == [] and ready["google"].requests == []


def test_an_account_with_no_task_lists_makes_nothing_and_says_so(ready):
    from test_ask import accept
    from test_tasks_ops import PROFILES, SENDERS
    accept(ready["path"], accounts={"google": {"address": fg.ACCOUNT}}, policies={k: v + ["interpret"] for k, v in PROFILES.items()}, messaging={"senders": SENDERS}, language="pt-BR")
    answer_op(ready, "todo-add", title="comprar café")
    said = say(ready, "adiciona comprar café na minha lista de tarefas")
    assert said.get("resend") is None and phrases.text("TODO_NO_LISTS", PT["cfg"]) in said["reply"] and open_decisions(ready) == [] and ready["google"].requests == []


def test_limits_55_and_61_the_gate_refuses_a_planted_origin_or_argument_and_no_card_is_opened(ready):
    ctx = ops_core.context(ready["path"])
    extras = {}
    started = []

    def start(car, who):
        started.append(1)
        raise AssertionError("a card was started")
    planted = (({"title": "comprar café"}, {"account": "config", "title": "grounded"}),      # a title no line gave
               ({"title": "comprar café"}, {"account": "config", "title": "composed"}),
               ({"title": "comprar café"}, {"account": "model", "title": "line-span"}),      # an origin that is no origin
               ({"title": "comprar café"}, {"title": "line-span"}),      # an argument with no origin
               ({"title": "comprar café", "due": "amanhã"}, {"account": "config", "title": "line-span", "due": "line-span"}))      # an argument the operation does not take  # validate: allow english-only -- a Portuguese line is the input under test
    for given, origins in planted:
        text = ops_todo._card(ready["path"], ctx, "todo-add", "google", given, origins, start, "messaging", SENDER, extras)
        assert text == phrases.text("IX_ASK_AGAIN", PT["cfg"]) and started == [], (given, origins)
    assert open_decisions(ready) == [] and ready["google"].requests == []
    for given, origins in (({"item": "todo:1", "list": "tarefas"}, {"account": "config", "item": "line-span", "list": "config"}),
                           ({"item": "dentista", "list": "tarefas"}, {"account": "config", "item": "composed", "list": "config"}),
                           ({"item": "dentista", "list": "tarefas"}, {"account": "config", "item": "grounded", "list": "line-span-but-not-an-origin"})):
        assert ops_todo._card(ready["path"], ctx, "todo-done", "google", given, origins, start, "messaging", SENDER, extras) == phrases.text("IX_ASK_AGAIN", PT["cfg"]), (given, origins)
    clean = ops_todo._card(ready["path"], ctx, "todo-add", "google", {"title": "comprar café"}, {"account": "config", "title": "line-span"},
                           lambda car, who: ops.todo_add(ready["path"], "google", "comprar café", None, car, who), "messaging", SENDER, extras)
    assert extras["resend"] and phrases.text("ACCT_CARD_SENT", PT["cfg"], pending=extras["resend"]) in clean, "the same call with honest origins opens the card"


# --- who may ---------------------------------------------------------------------------------------------------------------------------


def test_a_sender_without_the_group_is_refused_and_nothing_is_read_or_written(ready):
    answer_op(ready, "todo-add", title="comprar café")
    for key in (PLAIN, READER):
        said = say(ready, "adiciona comprar café na minha lista de tarefas", key=key)
        assert said.get("resend") is None
    assert open_decisions(ready) == [] and ready["google"].requests == []


def test_a_sender_who_may_write_and_not_read_cannot_complete_by_words(ready):
    answer_op(ready, "todo-done", target="comprar café")
    said = say(ready, "conclui comprar café", key=WRITER)
    assert said.get("resend") is None and open_decisions(ready) == [] and calls_of(ready["google"]) == []


# --- list and complete ----------------------------------------------------------------------------------------------------------------


def test_the_list_asks_first_and_then_numbers_the_tasks_and_a_number_completes_the_task_of_that_list(ready):
    google = ready["google"]
    answer_op(ready, "todo-list")
    asked = say(ready, "o que tem na minha lista de tarefas?")
    assert asked["plan_confirm"] and phrases.text("UNDERSTOOD_TODO_LIST", PT["cfg"]) in asked["reply"] and calls_of(google) == [], "nothing is read before the person's yes"
    listed = say(ready, "sim", plan_ok=asked["plan_confirm"])
    assert "1. comprar café" in listed["reply"] and "2. ligar para o dentista" in listed["reply"] and "3. comprar pão" in listed["reply"] and "1. enviar o relatório" in listed["reply"]  # validate: allow english-only -- a Portuguese line is the input under test
    assert phrases.text("TODO_HEAD", PT["cfg"], service="Google Tasks", list="tarefas") in listed["reply"] and fg.DEFAULT_LIST not in listed["reply"] and "t1" not in listed["reply"]
    assert writes(google) == []
    answer_op(ready, "todo-done", item="2", service="google")
    done = say(ready, "marca o 2 do google como feita")
    assert done.get("resend") is not None
    doc = effect_doc(ready, {"pending": done.get("resend"), "task": item_of(ready, {"pending": done.get("resend")})["task_id"]})
    assert doc["task_id"] == "t2" and doc["title"] == "ligar para o dentista" and doc["operation"] == "complete"
    approve(ready, {"pending": done.get("resend"), "task": item_of(ready, {"pending": done.get("resend")})["task_id"]}, channel="messaging", sender=SENDER)
    assert [(m, p, b) for m, p, _q, b in writes(google)] == [("PATCH", "/tasks/v1/lists/@default/tasks/t2", {"status": "completed"})]


def shown_list(ready):
    answer_op(ready, "todo-list")
    asked = say(ready, "o que tem na minha lista de tarefas?")
    return say(ready, "sim", plan_ok=asked["plan_confirm"])


def test_a_number_shown_in_two_services_asks_which_and_never_takes_the_default_account(ready):
    """The list shows a number 1 under Google Tasks and another under Microsoft To Do, and `accounts.default` is google: a number with no service word does not take the default (a number
    belongs to the list it was shown in), it asks."""
    shown_list(ready)
    answer_op(ready, "todo-done", item="1")
    asked = say(ready, "marca o 1 como feita")
    assert asked.get("resend") is None and phrases.text("TODO_ASK_ACCOUNT", PT["cfg"]) in asked["reply"] and open_decisions(ready) == []
    assert writes(ready["google"]) == [] and writes(ready["microsoft"]) == []
    shown_list(ready)      # vacuity: with the service word the same number opens its card
    answer_op(ready, "todo-done", item="1", service="microsoft")
    chosen = say(ready, "marca o 1 do microsoft como feita")
    assert chosen.get("resend") is not None
    assert effect_doc(ready, {"pending": chosen["resend"], "task": item_of(ready, {"pending": chosen["resend"]})["task_id"]})["account"] == "microsoft"


def test_a_number_shown_in_one_service_only_goes_to_that_service_without_a_word(ready):
    """Vacuity of the test above: when the remembered list holds one account only, that account is the answer whatever `accounts.default` says."""
    from test_ask import accept
    from test_tasks_ops import PROFILES, SENDERS
    accept(ready["path"], accounts={"google": GOOGLE, "microsoft": MICROSOFT, "default": "microsoft"}, policies={k: v + ["interpret"] for k, v in PROFILES.items()}, messaging={"senders": SENDERS}, language="pt-BR")
    answer_op(ready, "todo-list", service="google")
    asked = say(ready, "o que tem na minha lista de tarefas do google?")
    say(ready, "sim", plan_ok=asked["plan_confirm"])
    answer_op(ready, "todo-done", item="2")
    said = say(ready, "marca o 2 como feita")
    assert said.get("resend") is not None
    assert effect_doc(ready, {"pending": said["resend"], "task": item_of(ready, {"pending": said["resend"]})["task_id"]})["account"] == "google"


@pytest.mark.parametrize("number", ("0", "10000", "99999"))
def test_a_number_outside_one_to_9999_answers_none_before_the_list_is_looked_at(ready, monkeypatch, number):
    """A number outside 1 to 9999 names no task: the answer is TODO_NONE, given before `_find` is asked, and no card is opened."""
    shown_list(ready)
    monkeypatch.setattr(ops_todo, "_find", lambda *a, **k: (_ for _ in ()).throw(AssertionError("_find is never asked about a number out of range")))
    answer_op(ready, "todo-done", item=number, service="google")
    said = say(ready, "marca o " + number + " do google como feita")
    assert said.get("resend") is None and phrases.text("TODO_NONE", PT["cfg"]) in said["reply"] and open_decisions(ready) == [] and writes(ready["google"]) == []


def test_vacuity_the_last_number_in_range_is_asked_about_and_the_find_is_called(ready, monkeypatch):
    shown_list(ready)
    asked = []
    real = ops_todo._find
    monkeypatch.setattr(ops_todo, "_find", lambda *a, **k: asked.append(a[4]) or real(*a, **k))
    answer_op(ready, "todo-done", item="9999", service="google")
    said = say(ready, "marca o 9999 do google como feita")
    assert asked == ["todo:9999"] and phrases.text("TODO_NONE", PT["cfg"]) in said["reply"], "in range, so looked at: and the list has no 9999th task"
    shown_list(ready)
    answer_op(ready, "todo-done", item="2", service="google")
    assert say(ready, "marca o 2 do google como feita").get("resend") is not None and asked[-1] == "todo:2"


def test_a_typed_number_out_of_range_names_nothing_and_is_never_read_as_words(ready, monkeypatch):
    """`_find` on its own: `todo:0` and `todo:10000` are `none` with no list read (they are not searched as the words `todo` and the number)."""
    ctx = ops_core.context(ready["path"])
    monkeypatch.setattr(ops_todo, "_read_account", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no list is read for a number")))
    for item in ("todo:0", "todo:10000", "todo:00", "todo:-1", "todo:"):
        assert ops_todo._find(ctx, "messaging", SENDER, "google", item) == {"status": "none"}, item
    assert ops_todo._find(ctx, "messaging", SENDER, "google", "todo:1") == {"status": "no-list"}, "vacuity: a number in range with no list shown is no-list"


def test_a_number_said_two_lines_after_the_list_answers_nothing(ready):
    answer_op(ready, "todo-list")
    asked = say(ready, "o que tem na minha lista de tarefas?")
    say(ready, "sim", plan_ok=asked["plan_confirm"])
    ready["answer"]["text"] = json.dumps({"v": 1, "kind": "none"})
    say(ready, "obrigado")      # one line in between: the list no longer answers a number
    answer_op(ready, "todo-done", item="2")
    stale = say(ready, "marca o 2 como feita")
    assert stale.get("resend") is None and phrases.text("TODO_NO_LIST_SHOWN", PT["cfg"]) in stale["reply"] and open_decisions(ready) == []


def test_a_line_that_completes_by_words_opens_the_card_of_the_one_task_that_fits(ready):
    answer_op(ready, "todo-done", target="dentista")
    said = say(ready, "conclui a tarefa do dentista")
    assert said.get("resend") is not None
    doc = effect_doc(ready, {"pending": said.get("resend"), "task": item_of(ready, {"pending": said.get("resend")})["task_id"]})
    assert doc["task_id"] == "t2" and ready["google"].writes() == []
    answer_op(ready, "todo-done", target="comprar")
    several = say(ready, "conclui comprar")
    assert several.get("resend") is None and phrases.text("TODO_SEVERAL", PT["cfg"], count=2) in several["reply"] and "2. comprar pão" in several["reply"]  # validate: allow english-only -- a Portuguese line is the input under test
    answer_op(ready, "todo-done", target="zzz")
    assert phrases.text("TODO_NONE", PT["cfg"]) in say(ready, "conclui zzz")["reply"]


def test_a_line_that_names_both_a_number_and_words_or_neither_asks_again(ready):
    answer_op(ready, "todo-done", item="2", target="dentista")
    assert phrases.text("IX_ASK_AGAIN", PT["cfg"]) in say(ready, "conclui o 2 dentista")["reply"]
    answer_op(ready, "todo-done")
    assert phrases.text("IX_ASK_AGAIN", PT["cfg"]) in say(ready, "conclui isso")["reply"]  # validate: allow english-only -- a Portuguese line is the input under test
    assert open_decisions(ready) == []


def test_the_conversation_keeps_a_neutral_word_for_every_reply_that_holds_a_title(ready):
    ops_say = st.load("ops_say")
    answer_op(ready, "todo-add", title="comprar café")
    said = say(ready, "adiciona comprar café na minha lista de tarefas")
    assert said.get("resend") is not None
    ctx = ops_core.context(ready["path"])
    stored = " ".join(str(m["text"]) for m in ctx["store"].messages_list(ctx["conn"], ops_say.CONVERSATION))
    assert "comprar café" not in stored and "tarefas" not in stored, "neither the line nor the reply is kept"
    assert phrases.text("NW_PRIVATE_REPLY", PT["cfg"]) in stored


def test_a_completion_is_approved_from_a_phone_by_a_sender_who_may_read_the_lists_without_reading_mail(ready):
    """A card key names its own group: the title of a task is shown to a holder of `tasks-read`, who needs no `ask-mail`."""
    added = ops.todo_add(ready["path"], "google", "comprar leite", channel="messaging", sender=TASKER)
    assert approve(ready, added, channel="messaging", sender=TASKER)["result"]["done"] is True
    done = ops.todo_done(ready["path"], "google", "dentista", channel="messaging", sender=TASKER)
    ctx = ops_core.context(ready["path"])
    cards = st.load("messaging_cards")
    item = item_of(ready, done)
    assert "ligar para o dentista" in cards.effect_card_text(item, ctx["cfg"], {"tasks-read"}, False, False), "the card shown to a holder of tasks-read holds the title"
    assert approve(ready, done, channel="messaging", sender=TASKER)["result"]["done"] is True
    assert [m for m, _p, _q, _b in writes(ready["google"])] == ["POST", "PATCH"]


def test_a_sender_without_tasks_read_is_never_shown_a_title_and_cannot_approve_a_completion_but_an_add_can(ready):
    added = ops.todo_add(ready["path"], "google", "comprar leite", channel="messaging", sender=TASKER)
    assert approve(ready, added, channel="messaging", sender=MAILER)["result"]["done"] is True      # the title of a task being added is the person's own words
    done = ops.todo_done(ready["path"], "google", "dentista", channel="messaging", sender=TASKER)
    with pytest.raises(ops.OpsError) as refused:
        approve(ready, done, channel="messaging", sender=MAILER)      # holding ask-mail does not show the title of a task: the group is tasks-read
    assert "tasks-read" in str(refused.value) and [m for m, _p, _q, _b in writes(ready["google"])] == ["POST"]
    ctx = ops_core.context(ready["path"])
    cards = st.load("messaging_cards")
    item = item_of(ready, done)
    for held in (False, set(), {"ask-mail"}):
        shown = cards.effect_card_text(item, ctx["cfg"], held, False, False)
        assert "ligar para o dentista" not in shown and phrases.text("CARD_HIDDEN_NOTE_TODO", ctx["cfg"]) in shown and "Lista: tarefas (Google Tasks)" in shown, held
    assert approve(ready, done)["result"]["done"] is True      # the terminal shows the whole card


def test_vacuity_with_every_private_key_in_ask_mail_the_two_senders_swap(ready, monkeypatch):
    """The two tests above hold only because `CARD_PRIVATE_GROUP_OF` names `tasks-read` for the title: with the map empty a title is an ask-mail line again, and the sender who holds
    tasks-read and not ask-mail is the one refused."""
    monkeypatch.setattr(phrases, "CARD_PRIVATE_GROUP_OF", {})
    done = ops.todo_done(ready["path"], "google", "dentista", channel="messaging", sender=TASKER)
    with pytest.raises(ops.OpsError):
        approve(ready, done, channel="messaging", sender=TASKER)
    assert approve(ready, done, channel="messaging", sender=MAILER)["result"]["done"] is True
    assert [m for m, _p, _q, _b in writes(ready["google"])] == ["PATCH"]


def test_the_groups_a_private_line_may_name_are_the_groups_the_senders_are_asked_for():
    item_refs = st.load("item_refs")
    assert set(item_refs.PRIVATE_GROUPS) == set(phrases.PRIVATE_GROUPS) == {"ask-mail", "tasks-read"}
    assert phrases.private_group("CARD_TODO_NOW_TITLE") == "tasks-read"
    assert {phrases.private_group(k) for k in phrases.CARD_PRIVATE} <= set(phrases.PRIVATE_GROUPS)
    assert all(phrases.private_group(k) == "ask-mail" for k in phrases.CARD_PRIVATE if k != "CARD_TODO_NOW_TITLE")


# --- what a line reaches --------------------------------------------------------------------------------------------------------------


def test_a_reminder_line_is_a_reminder_and_never_a_task(ready):
    ready["answer"]["text"] = json.dumps({"v": 1, "kind": "op", "op": "remind", "slots": {"text": "comprar café"}, "time_iso": "2099-01-01T09:00", "weekday": None})
    said = say(ready, "me lembra de comprar café amanhã")  # validate: allow english-only -- a Portuguese line is the input under test
    assert said.get("resend") is None and open_decisions(ready) == [] and ready["google"].requests == [] and ready["microsoft"].requests == []


def test_at_catalog_version_1_no_line_reaches_a_task_operation(world, monkeypatch):
    """The L54 switch: with the catalog at 1 (what is shipped) the rows exist for a typed command and are refused as operations of a line."""
    for op in ("todo-list", "todo-add", "todo-done"):
        assert op in natural.CLASSES and op not in natural.NATURAL, op
        assert natural.check_operation(op, {}, None, "adiciona comprar café")["ok"] is False
    served = {row["op"] for row in interpreter.SERVED["ops"]} | {row["op"] for row in interpreter.SERVED["refused"]}
    assert not served & {"todo-list", "todo-add", "todo-done"}
    flip(monkeypatch)
    assert {"todo-list", "todo-add", "todo-done"} <= {row["op"] for row in interpreter.SERVED["ops"]}
    assert natural.check_operation("todo-add", {"title": "comprar café"}, None, "adiciona comprar café na lista")["ok"] is True
    assert natural.check_operation("todo-add", {"title": "comprar café", "service": "google"}, None, "adiciona comprar café no google")["args"] == {"title": "comprar café", "account": "google"}
