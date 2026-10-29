"""A11-2, made true (S41-11 PR 2a, SPEC-S41-11-BRAKE): a line in words of a sender whom the interpreter reads runs in two legs, so that a brake works while the planning agent answers.

Leg 1 (decide) is a job that takes no model slot: every row of code and the interpreter run, a brake said in words gets its "Posso?" at once, and only a line the decision hands back goes on.
Leg 2 (route) is today's `say_queue`: the slot, or the queue, with the route pass the decide leg issued, so that the interpreter is asked ONCE. With no model decision (the call failed, or no entry in
force) a brake form gets the typed hint and is never queued.

Over the real messaging bridge, the real operations layer and the stand-in model of test_commands_in_words.py (no network, no model). Every test has a twin that disables the mechanism and must fail:
the decide row out of the table, the pass taken as missing, the hint check out. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_brake_leg.py
"""
from __future__ import annotations

import os
import threading
import time

import pytest

import standin_tree as st
from test_commands_in_words import OWNER, docs, op, rig, with_senders, world  # noqa: F401  (the bridge, the real operations layer and the stand-in model)
from test_ops_natural import router_says

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_turn = st.load("ops_turn")
turn_order = st.load("turn_order")
route_pass = st.load("route_pass")
operations = st.load("operations")
phrases = st.load("phrases")

ROUTE = '{"v":1,"kind":"route"}'
WAIT = 3.0
BUSY_KEYS = ("QUEUED", "STILL_WORKING", "RUN_BUSY")


def deliver(rig, text, who=OWNER):
    rig.bridge.handle({"update_id": 1, "sender": who, "chat": who, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None})


def until(condition, seconds=WAIT):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


def hold_agent(rig):
    """The planning agent answers another request: its job holds the project's model slot and the route lock. Returns the function that lets it go."""
    release = threading.Event()
    rig.bridge.start_job(rig.project["id"], "say", lambda: release.wait(30))
    fd = ops_core._try_lock(ops_core.context(rig.project["path"])["cfg"], "route.lock")
    assert fd is not None

    def let_go():
        release.set()
        os.close(fd)
    return let_go


def busy_sentences():
    return {text for key in BUSY_KEYS for text in phrases.every(key)}


def brake_line(rig, number=5):
    return f"para a tarefa {number}" if rig.language == "pt-BR" else f"stop task {number}"


def disable_row(monkeypatch, name):
    monkeypatch.setattr(turn_order, "names", lambda stage, real=turn_order.names: tuple(n for n in real(stage) if n != name))


# --- test 1: a brake in words while the agent routes ---------------------------------------------------------------------------------------------


def the_brake_scenario(rig, monkeypatch):
    stopped = []
    monkeypatch.setattr(ops, "stop_task", lambda project, task_id, channel=None, sender=None: stopped.append(task_id) or {"task": task_id, "already": False})
    rig.model["text"] = op("stop-task", {"id": "5"})
    let_go = hold_agent(rig)
    started = time.monotonic()
    deliver(rig, brake_line(rig))
    return stopped, let_go, started


def test_a11_2_a_brake_in_words_while_the_agent_routes_is_decided_without_the_slot_and_runs_while_it_is_still_blocked(rig, monkeypatch):
    stopped, let_go, started = the_brake_scenario(rig, monkeypatch)
    try:
        assert until(lambda: len(rig.plan_cards(OWNER)) == 1), "the question \"Posso?\" of the brake came while the agent was blocked"
        assert time.monotonic() - started < 2.0 and len(rig.asked) == 1, "within the bound, one call of the interpreter"
        assert not set(rig.texts(OWNER)) & busy_sentences(), "no QUEUED, no STILL_WORKING, no RUN_BUSY"
        deliver(rig, "sim")
        assert until(lambda: stopped == [5]), "the yes stopped the task once"
        assert rig.bridge.exclusive, "while the agent still held the slot: the brake took none"
    finally:
        let_go()


def test_vacuity_a11_2_without_the_decide_row_the_brake_waits_behind_the_agent(rig, monkeypatch):
    disable_row(monkeypatch, "decide-without-slot")
    stopped, let_go, started = the_brake_scenario(rig, monkeypatch)
    try:
        assert not until(lambda: len(rig.plan_cards(OWNER)) == 1, 1.5), "the line is kept behind the agent, as it was"
        assert set(rig.texts(OWNER)) & busy_sentences()
        assert stopped == []
    finally:
        let_go()


# --- test 2: a plain line while busy still queues, and the model is asked once ------------------------------------------------------------------


def the_queue_scenario(rig, monkeypatch):
    rig.model["text"] = ROUTE
    router_says(rig.world, "Route: none (capability, pending)\nWhy: a plain question\nNext: nothing.\n")
    let_go = hold_agent(rig)
    deliver(rig, "me conta o que voce acha do mar" if rig.language == "pt-BR" else "tell me what you think of the sea")
    return let_go


def test_a11_2_a_plain_line_while_busy_is_still_queued_and_the_model_is_asked_once(rig, monkeypatch):
    let_go = the_queue_scenario(rig, monkeypatch)
    try:
        assert until(lambda: set(rig.texts(OWNER)) & busy_sentences()), "the line was kept: the sentence that says so"
        assert len(rig.bridge.waiting) == 1 and len(rig.asked) == 1 and not rig.plan_cards(OWNER)
    finally:
        let_go()
    assert until(lambda: not rig.bridge.waiting and not rig.bridge.exclusive, 10.0), "the kept line was routed once the agent was done"
    assert len(rig.asked) == 1, "the route leg took the pass: the interpreter was not asked a second time"


def test_vacuity_a11_2_with_the_pass_never_taken_the_model_is_asked_twice(rig, monkeypatch):
    monkeypatch.setattr(ops_interpret, "take_pass", lambda *args, **kwargs: False)
    let_go = the_queue_scenario(rig, monkeypatch)
    try:
        assert until(lambda: len(rig.bridge.waiting) == 1)
    finally:
        let_go()
    assert until(lambda: not rig.bridge.waiting and not rig.bridge.exclusive, 10.0)
    assert len(rig.asked) == 2, "without the pass the route leg asks again"


# --- test 3: an outage gives the typed hint and never queues -------------------------------------------------------------------------------------


def test_a11_2_an_outage_brake_with_no_entry_in_force_gets_the_typed_hint_and_never_queues_and_makes_no_call(rig, monkeypatch):
    monkeypatch.setattr(ops_interpret.interpreter_enable, "active", lambda tag: None)      # no entry in force: the interpreter is off, the sender still holds the group
    let_go = hold_agent(rig)
    try:
        started = time.monotonic()
        deliver(rig, brake_line(rig))
        assert until(lambda: any("/stop-task 5" in text for text in rig.texts(OWNER))), "the typed hint, with the number the line writes"
        assert time.monotonic() - started < 1.5
        assert not rig.bridge.waiting and not rig.asked and not rig.plan_cards(OWNER), "no keep, no call, no question"
        assert not set(rig.texts(OWNER)) & busy_sentences()
    finally:
        let_go()


def test_a11_2_an_outage_brake_after_a_failed_call_gets_the_hint_but_a_decision_of_route_is_believed_over_the_recogniser(rig, monkeypatch):
    monkeypatch.setattr(st.load("interpreter_route"), "complete", lambda route_id, system, user, **kw: rig.asked.append(user) or {"ok": False, "code": "E_NETWORK"})
    let_go = hold_agent(rig)
    try:
        deliver(rig, brake_line(rig))
        assert until(lambda: any("/stop-task 5" in text for text in rig.texts(OWNER))), "no model decided: the hint"
        assert not rig.bridge.waiting
    finally:
        let_go()


def test_a11_2_a_non_brake_line_in_the_same_outage_is_handed_back_and_queued(rig, monkeypatch):
    monkeypatch.setattr(ops_interpret.interpreter_enable, "active", lambda tag: None)
    router_says(rig.world, "Route: none (capability, pending)\nWhy: a plain question\nNext: nothing.\n")
    let_go = hold_agent(rig)
    try:
        deliver(rig, "me conta o que voce acha do mar" if rig.language == "pt-BR" else "tell me what you think of the sea")
        assert until(lambda: len(rig.bridge.waiting) == 1), "not a brake: kept, as any plain line is"
        assert not any("/stop-task" in text for text in rig.texts(OWNER))
    finally:
        let_go()


def test_vacuity_a11_2_without_the_hint_check_the_outage_brake_is_kept_behind_the_agent(rig, monkeypatch):
    monkeypatch.setattr(ops_interpret.interpreter_enable, "active", lambda tag: None)
    monkeypatch.setattr(ops_turn, "brake_hint", lambda *args, **kwargs: None)
    let_go = hold_agent(rig)
    try:
        deliver(rig, brake_line(rig))
        assert until(lambda: len(rig.bridge.waiting) == 1), "no hint: the brake waits in the queue"
        assert not any("/stop-task" in text for text in rig.texts(OWNER))
    finally:
        let_go()


# --- test 4: the pass and the derived list ------------------------------------------------------------------------------------------------------------


def test_the_route_pass_holds_no_text_and_is_taken_once_by_the_line_the_sender_and_the_project_it_was_issued_for(monkeypatch):
    route_pass.forget_all()
    found = route_pass.issue("p1", "telegram:1", "stop   task 5", "new")
    assert "task" not in repr(route_pass._passes) and "stop" not in repr(route_pass._passes), "never the line"
    assert route_pass.take("p1", "telegram:1", "stop task 5", found) == {"frame": "new"}, "the line is read as the interpreter collapses it"
    assert route_pass.take("p1", "telegram:1", "stop task 5", found) is None, "once"
    for project, sender, line in (("p2", "telegram:1", "stop task 5"), ("p1", "telegram:2", "stop task 5"), ("p1", "telegram:1", "stop task 6")):
        again = route_pass.issue("p1", "telegram:1", "stop task 5", "answer")
        assert route_pass.take(project, sender, line, again) is None, (project, sender, line)
        assert route_pass.take("p1", "telegram:1", "stop task 5", again) is None, "a wrong take spends the pass"
    now = [route_pass.clock()]
    monkeypatch.setattr(route_pass, "clock", lambda: now[0])
    late = route_pass.issue("p1", "telegram:1", "x", "new")
    now[0] += route_pass.EXPIRY + 1
    assert route_pass.take("p1", "telegram:1", "x", late) is None, "expired"
    assert route_pass.take("p1", "telegram:1", "x", "no-such-id") is None and route_pass.take("p1", "telegram:1", "x", None) is None
    with pytest.raises(ValueError):
        route_pass.issue("p1", "telegram:1", "x", "route")


def test_vacuity_a_pass_that_does_not_look_at_the_line_would_answer_for_any_line(monkeypatch):
    route_pass.forget_all()
    monkeypatch.setattr(route_pass, "digest", lambda line: "same")      # planted: every line has the same digest
    found = route_pass.issue("p1", "telegram:1", "stop task 5", "new")
    assert route_pass.take("p1", "telegram:1", "something else", found) == {"frame": "new"}, "planted: another line takes the pass, so the check of the real digest above is not vacuous"


def test_the_line_brakes_are_derived_from_the_groups_and_stop_runs_is_none_of_them():
    groups = operations.GROUPS
    assert operations.LINE_BRAKES == tuple(op for g in ("brakes", "retry", "routine-brakes") for op in groups[g]["operations"])
    assert set(operations.LINE_BRAKES) == {"cancel", "stop-task", "retry", "routine-pause", "routine-cancel"}      # this test's own list
    assert "stop-runs" not in operations.LINE_BRAKES and all(name in {row["name"] for row in operations.OPERATIONS} for name in operations.LINE_BRAKES)


# --- test 5: a sender who may not talk -----------------------------------------------------------------------------------------------------------


def test_a_sender_who_may_not_talk_is_refused_in_the_decide_leg_with_no_slot_no_pass_and_no_queue(rig, monkeypatch):
    route_pass.forget_all()
    rig.model["text"] = ROUTE
    monkeypatch.setattr(st.load("ops_say"), "may_talk", lambda *args, **kwargs: False)
    let_go = hold_agent(rig)
    try:
        deliver(rig, "me conta o que voce acha do mar" if rig.language == "pt-BR" else "tell me what you think of the sea")
        assert until(lambda: len(rig.texts(OWNER)) >= 1)
        assert not rig.bridge.waiting and not route_pass._passes, "refused after the interpreter said route: no pass, no keep"
        assert not set(rig.texts(OWNER)) & busy_sentences()
    finally:
        let_go()


def test_p3_the_decide_leg_stores_no_row_for_a_line_it_hands_back(rig, monkeypatch):
    """P3: a handed-back line stores no conversation row in leg 1 (the route leg stores it as it always did)."""
    rig.model["text"] = ROUTE
    router_says(rig.world, "Route: none (capability, pending)\nWhy: a plain question\nNext: nothing.\n")
    ctx = ops_core.context(rig.project["path"])
    before = len(ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500))
    let_go = hold_agent(rig)
    try:
        deliver(rig, "me conta o que voce acha do mar" if rig.language == "pt-BR" else "tell me what you think of the sea")
        assert until(lambda: len(rig.bridge.waiting) == 1)
        ctx = ops_core.context(rig.project["path"])
        assert len(ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)) == before, "nothing stored while the line waits"
    finally:
        let_go()


# --- the plan memory between the two legs -------------------------------------------------------------------------------------------------------------


def the_two_legs_scenario(rig, monkeypatch, strip_the_pass=False):
    """A plain line is handed back and kept while the agent runs; a brake said after it makes a plan ("Posso?"); the agent lets go and the kept line is routed (its route leg)."""
    rig.model["text"] = ROUTE
    router_says(rig.world, "Route: none (capability, pending)\nWhy: a plain question\nNext: nothing.\n")
    let_go = hold_agent(rig)
    deliver(rig, "me conta o que voce acha do mar" if rig.language == "pt-BR" else "tell me what you think of the sea")
    assert until(lambda: len(rig.bridge.waiting) == 1)
    rig.model["text"] = op("stop-task", {"id": "5"})
    deliver(rig, brake_line(rig))
    assert until(lambda: len(rig.plan_cards(OWNER)) == 1), "the brake's question came while the older line waited"
    if strip_the_pass:
        real = ops.say

        def single_leg(project, text, channel=None, sender=None, can_send=None, plan_ok=None, decide=False, route_pass=None):      # the bridge reads this signature to pass the sender
            return real(project, text, channel=channel, sender=sender, can_send=can_send, plan_ok=plan_ok, decide=decide)
        monkeypatch.setattr(ops, "say", single_leg)
        rig.model["text"] = ROUTE      # with no pass the route leg asks the model again: it says route, as it did for the line
    let_go()
    assert until(lambda: not rig.bridge.waiting and not rig.bridge.exclusive, 10.0)


def test_p3_the_route_leg_of_an_older_line_does_not_drop_the_plan_a_newer_brake_made(rig, monkeypatch):
    the_two_legs_scenario(rig, monkeypatch)
    assert ops.plan_live(rig.project["path"], f"telegram:{OWNER}") is not None, "the brake's plan is still live: the older line's route leg did not drop it"


def test_vacuity_p3_with_the_pass_stripped_the_older_lines_route_leg_drops_the_brakes_plan(rig, monkeypatch):
    the_two_legs_scenario(rig, monkeypatch, strip_the_pass=True)
    assert ops.plan_live(rig.project["path"], f"telegram:{OWNER}") is None, "without the pass the route leg is today's single leg: it drops the plan"
