"""A correction of a plan is a new interpreter turn with the `plan-confirm` frame item (package BL2a, runtime/ops_interpret.py `frame_for`, runtime/plan_confirm.py `frame_parts`).

After the sender is shown "I understood: ... Shall I go ahead?", a line that is neither a yes nor a no ("no, for tomorrow") is read by the model with the plan as a typed item of the frame:
its operation and age, never a word of it, and `last` with the plan's own words (the spans code checked in the person's line). The model states a new plan or says `answer` of the item; a
model's yes never runs a plan. A stand-in model and a stand-in clock; every expectation is a literal of this file. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_confirm_frame.py
"""
from __future__ import annotations

import datetime

import pytest

from plan_confirm_kit import (ASKER, OWNER, ok_of, op, ops, ops_core, ops_interpret, ops_natural, ops_say, phrases, plan_confirm, pending_items, question, say, text, world, rig)  # noqa: F401
from test_interpret_router_frame import FIRST, QUESTION, SECOND, TOKEN
from test_ops_natural import router_says

import standin_tree as st
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

ops_research = st.load("ops_research")
LINE = "will it rain in Lisbon, weather in Lisbon tomorrow"
TAIL = 'frame: {"items":[{"age_s":30,"id":"i1","kind":"plan-confirm","need":"confirm","op":"items"}],"last":{"age_s":30,"op":"items","words":{}},"v":1}'


def shown_frame(rig) -> str:
    """The `frame:` line of the user turn the stand-in model was last shown."""
    return next(line for line in rig.calls[-1]["user"].splitlines() if line.startswith("frame: "))


def test_a_correction_after_a_plan_is_read_with_the_plan_as_a_typed_item_and_states_a_new_plan(rig):
    first = say(rig, OWNER, "mostra minha agenda")
    rig.now[0] += 30
    rig.says["text"] = op("items")
    out = say(rig, OWNER, "nao, de amanha")
    assert shown_frame(rig) == TAIL
    day = phrases.localize_dates(phrases.text("UNDERSTOOD_ON_DAY", rig.cfg, day="Mon 19/10/2026"), rig.cfg)      # BL5B: the line names no events, so the new question keeps the kind of the plan it corrects (the agenda), not the mail
    assert out["reply"] == phrases.text("PLAN_HEAD", rig.cfg, what=phrases.text("UNDERSTOOD_ITEMS_CALENDAR", rig.cfg) + day) + " " + phrases.text("PLAN_ASK", rig.cfg)
    assert out["plan_confirm"]["item"] != first["plan_confirm"]["item"] and out["plan_confirm"]["op"] == "items"
    assert say(rig, OWNER, "sim", plan_ok=ok_of(first))["reply"] == phrases.text("PLAN_GONE", rig.cfg), "the plan that was corrected is gone"


def test_vacuity_a_frame_without_the_plan_item_differs_from_the_literal(rig, monkeypatch):
    say(rig, OWNER, "mostra minha agenda")
    rig.now[0] += 30
    monkeypatch.setattr(ops_interpret, "frame_for", lambda age_s, plan=None: None)
    rig.says["text"] = op("items")
    say(rig, OWNER, "nao, de amanha")
    assert shown_frame(rig) != TAIL and shown_frame(rig) == "frame: null"


def test_a_correction_inherits_the_question_of_a_search_from_the_plan_and_the_new_plan_quotes_it(rig, monkeypatch):
    calls = []
    monkeypatch.setattr(ops_research, "reply", lambda project, ctx, args, said, channel, sender, extras: calls.append((args, said)) or "SEARCH-REPLY")
    rig.says["text"] = op("research", {"question": "weather in Lisbon tomorrow"})
    first = say(rig, OWNER, LINE)
    assert "plan_confirm" in first
    rig.now[0] += 30
    rig.says["text"] = op("research", {}, inherit={"question": "weather in Lisbon"})
    out = say(rig, OWNER, "no, I meant the weather in Lisbon, thanks")
    assert '"last":{"age_s":30,"op":"research","words":{"question":"weather in Lisbon tomorrow"}}' in shown_frame(rig)
    assert out["reply"] == question(rig, "UNDERSTOOD_RESEARCH", question="weather in Lisbon", cap=phrases.decimal(f"{rig.cfg['research']['max_cost_usd']:.2f}", rig.cfg))
    done = say(rig, OWNER, "yes", plan_ok=ok_of(out))
    assert done["reply"] == "SEARCH-REPLY" and calls[0][0] == {"question": "weather in Lisbon"}
    assert "weather in Lisbon" in calls[0][1], "the line the call runs with holds the span the correction inherited"


def test_an_inherit_from_another_operation_asks_again_and_the_old_plan_is_dropped(rig):
    say(rig, OWNER, "mostra minha agenda")      # `last` holds op items with no words
    rig.says["text"] = op("research", {}, inherit={"question": "weather in Lisbon"})
    out = say(rig, OWNER, "no, search the weather in Lisbon")
    assert out["reply"] == phrases.text("IX_ASK_AGAIN", rig.cfg) and "plan_confirm" not in out and ops.plan_live(rig.world["path"], OWNER) is None


def test_the_models_no_to_the_plan_item_with_a_new_detail_revises_the_plan_with_none_it_drops_it_and_its_yes_keeps_it_for_the_senders_own_ok(rig):
    """BL5B changed the rule BL2a wrote here: a no that carries a new detail (a span of the plan's slot that differs from the plan's) is the corrected request, a new "Shall I go ahead?"; a no
    that changes nothing, or says nothing more, drops the plan; a yes never runs it."""
    rig.says["text"] = op("research", {"question": "weather in Lisbon tomorrow"})
    first = say(rig, OWNER, LINE)
    rig.says["text"] = text("answer", answers_item="i1", confirm="yes", slot="question", span="weather in Lisbon")
    kept = say(rig, OWNER, "yes, weather in Lisbon")
    assert kept["reply"] == phrases.text("PLAN_NOT_LAST", rig.cfg) and ops.plan_live(rig.world["path"], OWNER)["item"] == first["plan_confirm"]["item"]
    rig.says["text"] = text("answer", answers_item="i1", confirm="no", slot="question", span="weather in Lisbon")
    revised = say(rig, OWNER, "no, weather in Lisbon")
    cap = phrases.decimal(f"{rig.cfg['research']['max_cost_usd']:.2f}", rig.cfg)
    assert revised["reply"] == question(rig, "UNDERSTOOD_RESEARCH", question="weather in Lisbon", cap=cap), "a different span: a new question, nothing ran"
    assert revised["plan_confirm"]["item"] != first["plan_confirm"]["item"] and ops.plan_live(rig.world["path"], OWNER)["item"] == revised["plan_confirm"]["item"]
    rig.says["text"] = text("answer", answers_item="i1", confirm="no", slot="question", span="weather in Lisbon")
    dropped = say(rig, OWNER, "no, weather in Lisbon")
    assert dropped["reply"] == phrases.text("PLAN_DROPPED", rig.cfg) and ops.plan_live(rig.world["path"], OWNER) is None, "the same words: the no changed nothing"


def test_a_router_question_and_a_plan_are_two_items_and_an_answer_to_the_question_routes_as_before(rig, monkeypatch):
    router_says(rig.world, QUESTION)
    rig.says["text"] = text("route")
    asked = say(rig, OWNER, FIRST)
    assert asked["pending_id"] is not None and TOKEN in asked["reply"]
    ctx = ops_core.context(rig.world["path"])
    made = datetime.datetime.fromisoformat(str(ctx["store"].pending_get(ctx["conn"], asked["pending_id"])["created_at"]).replace("Z", "+00:00"))
    monkeypatch.setattr(ops_say, "_question_clock", lambda: made + datetime.timedelta(seconds=600))
    plan = say(rig, OWNER, "mostra minha agenda")      # a tier-1 read is a new line even with the question open, and it asks
    assert plan["reply"] == question(rig, "UNDERSTOOD_ITEMS_CALENDAR")
    rig.now[0] += 30
    routed = []
    monkeypatch.setattr(ops_say, "_say_route", lambda project, ctx, said, line_id, channel, answer_to=None, after=None, sender=None, extras=None: routed.append(answer_to) or ("ROUTED", None, None, True, None))
    rig.says["text"] = text("answer", answers_item="i1")
    say(rig, OWNER, SECOND)
    assert shown_frame(rig) == ('frame: {"items":[{"age_s":600,"id":"i1","kind":"router-question","need":"text"},'
                                '{"age_s":30,"id":"i2","kind":"plan-confirm","need":"confirm","op":"items"}],"last":{"age_s":30,"op":"items","words":{}},"v":1}')
    assert routed == [asked["pending_id"]], "the answer to the router's question reaches the router, as before"


def test_a_new_tier_1_read_drops_the_old_plan_and_asks_its_own(rig):
    first = say(rig, OWNER, "mostra minha agenda")
    second = say(rig, OWNER, "quais arquivos voce tem?")
    assert second["reply"] == question(rig, "UNDERSTOOD_SOURCES") and ops.plan_live(rig.world["path"], OWNER)["item"] == second["plan_confirm"]["item"]
    assert second["plan_confirm"]["item"] != first["plan_confirm"]["item"]


def test_the_frame_item_holds_only_the_operation_and_the_age_and_a_plan_the_catalog_lacks_is_left_out(rig):
    item = pending_items.new_item("plan-confirm", "p", "messaging", OWNER, state={"op": "items", "words": {"title": "Dana"}, "args": {}, "when": None, "routed": False, "said": "x",
                                                                                   "state_question": False, "sha256": "0" * 64})
    pending_items.put(item)
    frame = ops_interpret.frame_for(None, item)
    assert frame["items"] == [{"id": "i1", "kind": "plan-confirm", "need": "confirm", "op": "items", "age_s": 0}] and frame["last"] == {"op": "items", "words": {}, "age_s": 0}, "words that are no slot of the op are left out, the plan stays"
    ghost = pending_items.new_item("plan-confirm", "p", "messaging", ASKER, state={"op": "no-such-op", "words": {}, "args": {}, "when": None, "routed": False, "said": "x",
                                                                                    "state_question": False, "sha256": "0" * 64})
    assert ops_interpret.frame_for(None, ghost) is None and ops_interpret.frame_for(600, ghost)["items"] == [{"id": "i1", "kind": "router-question", "need": "text", "age_s": 600}]
    assert ops_interpret.router_frame(None) is None and ops_interpret.router_frame(5)["last"] is None


def test_a_correction_that_inherits_earlier_words_keeps_them_in_the_plans_line_and_the_question_is_not_asked_again(rig, monkeypatch):
    """The correction's own line holds none of the inherited span: only the earlier words the plan carries make the search's span check pass after the OK."""
    ran = []
    monkeypatch.setattr(ops_research, "_research", lambda project, ctx, question, channel, sender, line=None: ran.append((question, line)) or {"reply": "SEARCH-REPLY"})
    rig.says["text"] = op("research", {"question": "weather in Lisbon tomorrow"})
    say(rig, OWNER, LINE)
    rig.says["text"] = op("research", {}, inherit={"question": "weather in Lisbon tomorrow"})
    out = say(rig, OWNER, "make it the same one as before")      # the line holds nothing of the question
    assert "weather" not in "make it the same one as before" and "plan_confirm" in out
    item = pending_items.find(plan_confirm._key(rig.world["path"], OWNER), "plan-confirm")
    assert item["state"]["said"] == "make it the same one as before weather in Lisbon tomorrow" and item["state"]["words"] == {"question": "weather in Lisbon tomorrow"}
    done = say(rig, OWNER, "yes", plan_ok=ok_of(out))
    assert done["reply"] == "SEARCH-REPLY" and ran and ran[0][0] == "weather in Lisbon tomorrow", "the inherited question is not asked again"


def test_the_next_line_after_a_plan_with_string_arguments_sees_the_operation_and_none_of_the_values(rig, monkeypatch):
    """Arguments a tier-1 call carries (a path, a question) are never words of the frame: `last.words` holds only spans the interpreter checked in the person's line, and the frame item only the operation and the age."""
    ctx = ops_core.context(rig.world["path"])
    marker = "ZQX-marker-plan.md"
    for name, args in (("artifact", {"path": marker}), ("progress", {"since": marker}), ("research", {"question": marker})):
        extras = {}
        reply = ops_natural.run(rig.world["path"], ctx, name, args, "x", "messaging", OWNER, extras)
        assert extras["plan_confirm"]["op"] == name
        rig.says["text"] = text("none")
        say(rig, OWNER, "make it the same one as before")
        user = rig.calls[-1]["user"]
        assert marker not in user, name
        assert shown_frame(rig) == f'frame: {{"items":[{{"age_s":0,"id":"i1","kind":"plan-confirm","need":"confirm","op":"{name}"}}],"last":{{"age_s":0,"op":"{name}","words":{{}}}},"v":1}}', name
