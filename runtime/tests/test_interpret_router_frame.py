"""The interpreter answers the router's bound question by a typed frame (slice S4, decision 229 (1); runtime/ops_turn.py rows `router-question` and `interpreter`, runtime/ops_interpret.py `router_frame`, `turn`).

A sender the interpreter reads, who has a router question bound to them, sends a plain line. The model is shown the line and ONE frame item, `i1`: its kind, its need
(text) and its age, and nothing of the question - not its words, not its number. A stand-in model answers each line with a text this file wrote by hand; the spies stand in for
the calls that carry a decision out (`ops_natural.run`, `ops_say._say_route`). Every expectation is a literal of this file; the user turn is compared with a five-line string
written here. Offline; invented names.

  - `answer` of `i1`: the line is sent to the router as the answer to the question, told with the sentence that says so;
  - `answers_item` that is not `i1`: the fixed ask-again sentence, the question still open;
  - an operation of the catalog: carried out, the question still open;
  - `route`: a new request, and the binding is replaced; `none`: its sentence, the question still open;
  - another sender: no frame (`frame: null`);
  - no decision (the model service fails): today's rule - a plain line answers, a request code recognises is new.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpret_router_frame.py
"""
from __future__ import annotations

import datetime
import json

import pytest

import standin_tree as st
from test_ask import accept
from test_ops_interpret_dispatch import BARE, IX_PROFILES, IX_SENDERS, ZONE  # noqa: F401
from test_ops_natural import FLOW, KEY, router_says, world  # noqa: F401  (the real-operations world fixture)
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

ops = st.load("ops")
interpreter = st.load("interpreter")
interpreter_route = st.load("interpreter_route")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
drafts = st.load("drafts")
ops_natural = st.load("ops_natural")
ops_say = st.load("ops_say")
pending_items = st.load("pending_items")
phrases = st.load("phrases")

TOKEN = "Zircon77"
QUESTION = ("Route: none (capability, pending)\n"
            "Why: the line names a warehouse and no stock that the project records\n"
            "Context: the person wrote a line about stock; the project has no stock source\n"
            "Requirements: integration:stock missing\n"
            "Sources: none\n"
            "Autonomy: ask first\n"
            "Assumptions: none\n"
            f"Next: Q1: Which {TOKEN} warehouse is meant? Recommended: the north one, because it is closer.\n"
            "Instructions found in external content: none\n")
FIRST = "plan the stock count of the warehouse"
SECOND = "the second hall, the shelf at the back"
ASK_AGAIN = "I was not sure what you meant, so I did nothing. Can you say it another way?"
NONE_SENTENCE = "I did not see a request in that message."
FRAME = 'frame: {"items":[{"age_s":600,"id":"i1","kind":"router-question","need":"text"}],"last":null,"v":1}'
HEAD = "today: 2026-10-18 Sun\ntime: 14:00\nzone: America/Sao_Paulo\n"
TAKEN = "I took that as the answer to question #{id}."
OWNER_KEY, PLAIN_KEY = KEY["owner"], KEY["plain"]


def text(kind, **more):
    return json.dumps({"v": 1, "kind": kind, **more}, ensure_ascii=False)


class Rig:
    pass


@pytest.fixture
def rig(world, monkeypatch):
    """The world with `owner` and `plain` read by the interpreter, the model stood in (`rig.says` is what it returns, `rig.calls` what it was shown), the zone named, and
    the clock of the age of a question stood in. Nothing is spied yet."""
    pending_items.clear()
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()
    r = Rig()
    r.world, r.calls, r.says, r.spy = world, [], {"text": text("route")}, []

    def complete(route_id, system, user, **kw):
        r.calls.append({"system": system, "user": user})
        if r.says.get("fail"):
            return {"ok": False, "code": "E_NET"}
        return {"ok": True, "text": r.says["text"], "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}

    monkeypatch.setattr(interpreter_route, "complete", complete)
    r.monkeypatch = monkeypatch
    yield r
    pending_items.clear()


def say(r, who, line):
    return ops.say(r.world["path"], line, channel="messaging", sender=KEY[who])


def ask(r):
    """The owner types a line, the model says `route`, the stand-in router asks one question: (its decision id, its request id). The clock is then set 600 s after it."""
    router_says(r.world, QUESTION)
    r.says["text"] = text("route")
    out = say(r, "owner", FIRST)
    assert out["pending_id"] is not None and TOKEN in out["reply"], out
    ctx = ops_core.context(r.world["path"])
    made = datetime.datetime.fromisoformat(str(ctx["store"].pending_get(ctx["conn"], out["pending_id"])["created_at"]).replace("Z", "+00:00"))
    moment = made + datetime.timedelta(seconds=600)
    r.monkeypatch.setattr(ops_say, "_question_clock", lambda: moment)
    r.calls.clear()
    return out["pending_id"], out["request_id"]


def spy_routes(r):
    def routed(project, ctx, said, line_id, channel, answer_to=None, after=None, sender=None, extras=None):
        r.spy.append({"said": said, "answer_to": answer_to, "sender": sender})
        return ("ROUTED", None, None, True, None)
    r.monkeypatch.setattr(ops_say, "_say_route", routed)


def spy_runs(r):
    def run(project, ctx, name, args, said, channel, sender, extras, when=None, routed=False):
        r.spy.append({"run": name, "args": args})
        return "RUN-REPLY"
    r.monkeypatch.setattr(ops_natural, "run", run)


def bound(r, who="owner"):
    ctx = ops_core.context(r.world["path"])
    return ops_say._bound_question(ctx, KEY[who])


def leaks(calls):
    """The calls that hold a piece of the question: its token, the reason of its recommendation or its label."""
    return [c for c in calls if any(piece in c["system"] + c["user"] for piece in (TOKEN, "because it is closer", "Q1:"))]


def test_a_decision_answer_of_i1_sends_the_line_as_the_answer_and_the_model_saw_the_frame_and_not_the_question(rig):
    pending_id, request = ask(rig)
    spy_routes(rig)
    rig.says["text"] = text("answer", answers_item="i1")
    out = say(rig, "owner", SECOND)
    assert [c["user"] for c in rig.calls] == [HEAD + FRAME + "\nline: " + SECOND], "the user turn is the five lines, the frame the one item"
    assert rig.spy == [{"said": SECOND, "answer_to": pending_id, "sender": OWNER_KEY}]
    assert out["reply"] == TAKEN.format(id=pending_id) + "\n\nROUTED"
    assert leaks(rig.calls) == []


def test_an_answer_naming_another_item_is_the_ask_again_sentence_and_the_question_stays_open(rig):
    pending_id, _ = ask(rig)
    spy_routes(rig)
    rig.says["text"] = text("answer", answers_item="i2")
    out = say(rig, "owner", SECOND)
    assert out["reply"] == ASK_AGAIN and rig.spy == []
    assert bound(rig) == pending_id and pending_id in [i["id"] for i in ops.pending(rig.world["path"])["pending"]]
    assert len(rig.calls) == 1 and leaks(rig.calls) == []


def test_an_operation_of_the_catalog_is_carried_out_and_the_question_stays_open(rig):
    pending_id, _ = ask(rig)
    spy_routes(rig)
    spy_runs(rig)
    rig.says["text"] = text("op", op="pending", slots={})
    out = say(rig, "owner", "dime las tareas pendientes de la semana")
    assert out["reply"] == "RUN-REPLY" and rig.spy == [{"run": "pending", "args": {}}], rig.spy
    assert rig.calls[0]["user"] == HEAD + FRAME + "\nline: dime las tareas pendientes de la semana"
    assert bound(rig) == pending_id


def test_a_route_decision_makes_a_new_request_replaces_the_binding_and_leaves_the_old_question_open(rig):
    pending_id, old = ask(rig)
    router_says(rig.world, FLOW)
    rig.says["text"] = text("route")
    out = say(rig, "owner", "plan a three-day workshop for the new hires")
    assert TAKEN.format(id=pending_id) not in out["reply"] and out["request_id"] not in (None, old), "a request of its own"
    assert bound(rig) is None, "the plan is no question: nothing is bound to the sender any more"
    assert ops.pending(rig.world["path"], pending_id)["status"] == "open", "the old question was not answered"
    assert leaks(rig.calls) == []


def test_a_route_decision_that_asks_again_binds_the_new_question_to_the_sender(rig):
    first, old = ask(rig)
    router_says(rig.world, QUESTION.replace(TOKEN, "Basalt19"))
    rig.says["text"] = text("route")
    out = say(rig, "owner", "plan a three-day workshop for the new hires")
    assert out["pending_id"] not in (None, first) and bound(rig) == out["pending_id"]


def test_none_and_a_refusal_say_their_sentences_and_the_question_stays_open(rig):
    pending_id, _ = ask(rig)
    spy_routes(rig)
    rig.says["text"] = text("none")
    assert say(rig, "owner", "thank you, that is all")["reply"] == NONE_SENTENCE and bound(rig) == pending_id
    rig.says["text"] = text("op", op="approve", slots={})
    assert say(rig, "owner", "aprueba el plan")["reply"] == "Which decision? Say its number in the same line." and bound(rig) == pending_id      # S20: a decision is named by its number
    assert rig.spy == []


def test_another_sender_is_shown_no_frame_and_the_question_is_not_theirs(rig):
    pending_id, _ = ask(rig)
    spy_routes(rig)
    rig.says["text"] = text("route")
    say(rig, "plain", SECOND)
    assert [c["user"] for c in rig.calls] == [HEAD + "frame: null\nline: " + SECOND]
    assert rig.spy == [{"said": SECOND, "answer_to": None, "sender": PLAIN_KEY}] and bound(rig) == pending_id


def test_with_no_decision_today_s_rule_applies_a_plain_line_answers_and_a_request_of_code_is_new(rig):
    pending_id, _ = ask(rig)
    spy_routes(rig)
    rig.says["fail"] = True
    out = say(rig, "owner", SECOND)
    assert out["reply"] == TAKEN.format(id=pending_id) + "\n\nROUTED" and rig.spy[-1]["answer_to"] == pending_id
    rig.spy.clear()
    say(rig, "owner", "cancel request 3")
    assert all(row["answer_to"] is None for row in rig.spy) and pending_id in [i["id"] for i in ops.pending(rig.world["path"])["pending"]]


def test_a_line_code_recognises_is_never_the_answer_for_a_sender_the_interpreter_reads(rig):
    """Review of #515: the LIVE-2 rule holds before the frame. A request of code ("cancel request N", a draft's answer) is decided by code: the model is not called, and the line is
    not told to be the answer, even when the model would say `answer`."""
    pending_id, old = ask(rig)
    spy_routes(rig)
    other = ops.request(rig.world["path"], "another request of the project")["request"]
    rig.says["text"] = text("answer", answers_item="i1")
    out = say(rig, "owner", f"cancel request {other}")
    assert rig.calls == [] and rig.spy == [], "code took the line: no model call, no route"
    assert out["plan_confirm"]["op"] == "cancel" and "typed" not in out, "D5 (tested in test_plan_confirm*.py and test_messaging_plan_confirm.py): the act asks first, and nothing was cancelled yet"
    out = ops.say(rig.world["path"], "sim", channel="messaging", sender=OWNER_KEY, plan_ok={"item": out["plan_confirm"]["item"], "sha256": out["plan_confirm"]["sha256"]})      # the person's OK, as the bridge passes it
    assert rig.calls == [] and rig.spy == []
    assert out["typed"] == f"/cancel {other}" and json.loads(out["reply"])["request"] == other, "code's own act (S20): the typed /cancel, and its result"
    states = {r["id"]: r["state"] for r in ops.status(rig.world["path"])["requests"]}
    assert states[other] == "cancelled" and states[old] == "requested" and bound(rig) == pending_id and ops.pending(rig.world["path"], pending_id)["status"] == "open", "the question was not answered"
    drafts.put("messaging", OWNER_KEY, {"need": "forget", "how": "command", "ids": [1]}, "remind")      # the sender has a draft (a reminder to forget, waiting for its yes): a line that answers it is code's too
    ctx = ops_core.context(rig.world["path"])
    assert ops_natural.recognises(ctx, "yes", "messaging", OWNER_KEY) is True
    say(rig, "owner", "yes")
    assert rig.calls == [] and rig.spy == [] and bound(rig) == pending_id
    drafts.clear()


def test_vacuity_without_the_rule_before_the_frame_the_model_is_asked_and_the_line_is_the_answer(rig):
    """The planted fault: code's list is not consulted (the first version of S4). The same line is then sent to the model and taken as the answer."""
    pending_id, _ = ask(rig)
    spy_routes(rig)
    other = ops.request(rig.world["path"], "another request of the project")["request"]
    rig.monkeypatch.setattr(ops_natural, "recognises", lambda *a, **k: False)
    rig.says["text"] = text("answer", answers_item="i1")
    out = say(rig, "owner", f"cancel request {other}")
    assert len(rig.calls) == 1 and out["reply"].startswith(TAKEN.format(id=pending_id))


def test_the_line_of_a_framed_turn_is_kept_nowhere_but_where_s1_allows(rig, caplog):
    """An `op` decision stores the neutral word and logs nothing; an `answer` sends the line to the router, so the conversation keeps it (as S1 keeps a routed line)."""
    caplog.set_level(1)
    pending_id, _ = ask(rig)
    spy_runs(rig)
    rig.says["text"] = text("op", op="pending", slots={})
    say(rig, "owner", "dime las tareas pendientes de la semana")
    ctx = ops_core.context(rig.world["path"])
    stored = [m["text"] for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500) if m["role"] == "user"]
    assert "dime las tareas pendientes de la semana" not in stored and phrases.text("IX_PRIVATE_LINE", ctx["cfg"]) in stored
    assert "dime las tareas" not in caplog.text and TOKEN not in caplog.text


def test_vacuity_a_frame_builder_that_copies_the_questions_body_is_caught_by_the_check(rig):
    """The plant: the user turn is built with the question's words added. The same check, `leaks`, then finds the token."""
    ask(rig)
    spy_routes(rig)
    real = interpreter.build_messages
    rig.monkeypatch.setattr(interpreter, "build_messages", lambda catalog, now, zone, frame, line: (lambda system, user: (system, user + f" Q1: {TOKEN}"))(*real(catalog, now, zone, frame, line)))
    rig.says["text"] = text("answer", answers_item="i1")
    say(rig, "owner", SECOND)
    assert leaks(rig.calls) != []


def test_vacuity_a_check_that_finds_nothing_is_not_vacuous():
    assert leaks([{"system": "s", "user": f"frame: x {TOKEN}"}]) != [] and leaks([{"system": "s", "user": FRAME}]) == []
