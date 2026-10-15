"""Tests of the routines in the operations layer (package P6b): a draft approved by the hash of its exact content, a fire on a fake clock
that creates tasks only when the hash is the approved one, what moves the hash and what does not, one fire for one slot, the catch-up
rule after an outage, the routine's own consent (and the agent's never read), `auto` inside its approved providers, the brakes, and a
workflow a routine cannot take. On the stand-in tree of standin_tree.py (no model, no container, no network). Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_routines.py
"""
from __future__ import annotations

import datetime
import json
import os

import pytest

import standin_tree as st
from test_ops_flows import (CSV, FILE_FLOW, WEB_WITH_SOURCES, csv_file, new_request, ops, ops_core, ops_flows, pending, plan,  # noqa: F401
                            tasks_of, world, write_flow)

ops_models = st.load("ops_models")
ops_routines = st.load("ops_routines")
ops_steps = st.load("ops_steps")
routines = st.load("routines")
autonomy = st.load("autonomy")
lab = st.load("lab")
steps = st.load("steps")
skill_meta = st.load("skill_meta")

REAL = datetime.datetime.now().astimezone().replace(second=0, microsecond=0)


class Clock:
    """The fake clock: ops_flows.now() answers REAL plus an offset the test moves. The store stamps the approval with the real time, so a
    routine's slots are counted from REAL; the schedule is `daily at (REAL + 1 hour)`, so the first slot is one hour ahead."""

    def __init__(self, monkeypatch):
        self.offset = datetime.timedelta(0)
        monkeypatch.setattr(ops_flows, "now", lambda: REAL + self.offset)

    def to(self, **delta):
        self.offset = datetime.timedelta(**delta)
        return REAL + self.offset


@pytest.fixture
def clock(world, monkeypatch):
    return Clock(monkeypatch)


AT = (REAL + datetime.timedelta(hours=1)).strftime("%H:%M")
SLOT = (REAL + datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")


def ctx_of(world):
    return ops_core.context(world["path"])


def make(world, flow="demo", model="m", **extra):
    kw = dict(name=extra.pop("name", "morning"), flow=flow, every="day", at=AT, model=model)
    kw.update(extra)
    return ops.routine_create(world["path"], **kw)


def approve(world, routine_id):
    shown = ops.routine_approve(world["path"], routine_id)
    return ops.routine_approve(world["path"], routine_id, shown["approve"]["sha256"])


def tick(world, now):
    return ops_routines.tick(ctx_of(world), now)


def routine(world, routine_id):
    return ctx_of(world)["store"].routine_get(ctx_of(world)["conn"], routine_id)


def fires(world, routine_id):
    ctx = ctx_of(world)
    return ctx["store"].routine_fires_list(ctx["conn"], routine_id)


# --- a draft, and its approval by the hash of its exact content -----------------------------------------------------------------------


def test_a_routine_is_a_draft_that_fires_nothing_until_the_hash_of_its_exact_content_is_approved(world, clock):
    made = make(world)
    assert made["state"] == "draft" and made["approve"]["sha256"] == made["sha256"] and made["approve"]["consent_needed"] is False
    assert made["content"]["schedule"] == {"every": "day", "at": AT, "window_seconds": 86400} and made["content"]["scripts"] == []
    assert made["content"]["workflow"]["name"] == "demo" and set(made["content"]["skills"]) == {"demo-asks", "demo-writes"}
    assert tick(world, clock.to(days=3)) == []                                          # a draft is not ticked
    with pytest.raises(ops_core.OpsError, match="has the hash .* now, not " + "0" * 64 + ": nothing was approved"):
        ops.routine_approve(world["path"], made["id"], "0" * 64)
    approved = ops.routine_approve(world["path"], made["id"], made["sha256"])
    assert approved["state"] == "active" and approved["approved_sha256"] == made["sha256"] and approved["current"] is True
    changed = ops.routine_change(world["path"], made["id"], at="23:59")
    assert changed["state"] == "draft" and changed["approved_sha256"] is None, "a change clears the approval"
    assert changed["sha256"] != made["sha256"]


def test_a_routine_takes_a_workflow_that_exists_passes_the_check_and_takes_no_file(world, clock):
    write_flow(world, "survey-file", FILE_FLOW)
    with pytest.raises(ops_core.OpsError, match="takes a file \\(survey\\): nobody is there to hand a file over"):
        make(world, flow="survey-file")
    write_flow(world, "survey-web", WEB_WITH_SOURCES)
    with pytest.raises(ops_core.OpsError, match="the flow check refuses this workflow as a routine's target.*requires the web"):
        make(world, flow="survey-web", params=["topic=dental"])
    with pytest.raises(ops_core.OpsError, match="no flow file"):
        make(world, flow="missing")
    ops.flow_save(world["path"], "survey-split", flow="survey-web", split=True)
    with pytest.raises(ops_core.OpsError, match="needs a value for topic"):
        make(world, flow="survey-split")
    assert make(world, flow="survey-split", params=["topic=dental"], name="split")["content"]["workflow"]["params"] == {"topic": "dental"}
    for bad, word in ((dict(every="week"), "exactly"), (dict(every="minutes", minutes=25, at=None), "divides 1,440"), (dict(at="25:00"), "HH:MM"),
                      (dict(every=None, at=None), "says every")):
        with pytest.raises(ops_core.OpsError, match=word):
            make(world, name="other", **bad)
    with pytest.raises(ops_core.OpsError, match="a routine's name is lowercase words"):
        make(world, name="Not A Name")
    with pytest.raises(ops_core.OpsError, match="there is a routine named morning"):
        make(world)
        make(world)


# --- a fire --------------------------------------------------------------------------------------------------------------------------


def test_a_fire_with_the_approved_hash_creates_the_request_and_its_tasks_once_with_the_dates_filled(world, clock):
    write_flow(world, "daily-demo", {"flow": "daily-demo", "title": "Daily", "tasks": [
        {"key": "market", "skill": "demo-asks", "title": "Market of {today}", "text": "Do the market analysis for {week} (today is {today})."}]})
    made = make(world, flow="daily-demo")
    approve(world, made["id"])
    assert tick(world, clock.to(minutes=30)) == []                                      # the slot has not come
    [one] = tick(world, clock.to(minutes=61))
    assert one["status"] == "created" and one["slot"] == SLOT and one["routine"] == "morning"
    rows = tasks_of(world, one["request"])
    ctx = ctx_of(world)
    request = ctx["store"].task_get(ctx["conn"], one["request"])
    today = (REAL + datetime.timedelta(minutes=61)).date().isoformat()
    assert rows["market"]["state"] == "ready" and today in rows["market"]["title"] and request["flow"] == "daily-demo"
    assert request["model"] == "m" and "morning" in request["title"]
    assert tick(world, clock.to(minutes=62)) == [] and len(fires(world, made["id"])) == 1, "the slot is done: the next tick has nothing"
    assert routine(world, made["id"])["state"] == "active"


def test_two_fires_of_one_slot_create_tasks_once(world, clock):
    made = make(world)
    approve(world, made["id"])
    ctx = ctx_of(world)
    record = {**routine(world, made["id"]), "last_fire": None}
    first = ops_routines.fire(ctx, record, SLOT, clock.to(minutes=61))
    second = ops_routines.fire(ctx, record, SLOT, clock.to(minutes=62))
    assert first["status"] == "created" and second["status"] == "duplicate" and second["request"] is None
    requests = [t for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] is None]
    assert len(requests) == 1 and len(fires(world, made["id"])) == 1


def test_a_missed_slot_is_run_once_inside_the_window_skipped_and_noted_outside_it_and_never_once_per_missed_slot(world, clock):
    made = make(world, name="inside")
    approve(world, made["id"])
    out = tick(world, clock.to(days=3, minutes=61))                                     # a three-day outage
    assert [o["status"] for o in out].count("created") == 1 and [o["status"] for o in out].count("skipped") == 3
    rows = fires(world, made["id"])
    assert sorted(f["status"] for f in rows) == ["created", "skipped", "skipped", "skipped"] and "missed" in rows[1]["reason"]
    assert len([t for t in ctx_of(world)["store"].tasks_list(ctx_of(world)["conn"]) if t["parent_id"] is None]) == 1
    late = make(world, name="outside", window_seconds=3600)
    approve(world, late["id"])
    out = tick(world, clock.to(days=3, hours=3))                                        # the newest slot is 2 hours old, the window an hour
    mine = [o for o in out if o["routine"] == "outside"]
    assert mine and {o["status"] for o in mine} == {"skipped"}
    assert all(f["status"] == "skipped" for f in fires(world, late["id"])) and "older than the window of 3600 s" in fires(world, late["id"])[0]["reason"]
    assert tick(world, clock.to(days=3, hours=4)) == [], "what was skipped is not tried again"


def test_a_paused_routine_fires_nothing_and_makes_up_nothing_a_cancelled_one_never_returns(world, clock):
    made = make(world)
    approve(world, made["id"])
    assert ops.routine_pause(world["path"], made["id"])["state"] == "paused"
    assert tick(world, clock.to(days=2)) == [] and fires(world, made["id"]) == []
    assert ops.routine_resume(world["path"], made["id"])["state"] == "active"
    assert ops.routine_cancel(world["path"], made["id"])["state"] == "cancelled"
    assert tick(world, clock.to(days=3)) == []
    with pytest.raises(ops_core.OpsError, match="is cancelled"):
        ops.routine_approve(world["path"], made["id"], "0" * 64)
    with pytest.raises(ops_core.OpsError, match="is cancelled"):
        ops.routine_change(world["path"], made["id"], at="01:00")
    with pytest.raises(ops_core.OpsError, match="cancelled"):
        ops.routine_resume(world["path"], made["id"])


# --- what moves the hash, and what does not ------------------------------------------------------------------------------------------


def stopped(world, clock, text_part):
    [one] = tick(world, clock.to(minutes=61))
    assert one["status"] == "asked" and text_part in one["reason"], one
    return one


def approved_routine(world, **extra):
    made = make(world, **extra)
    approve(world, made["id"])
    return made["id"]


def test_a_changed_workflow_template_stops_the_routine_and_asks_with_a_question_that_messaging_notifies(world, clock):
    write_flow(world, "daily-demo", {"flow": "daily-demo", "title": "Daily", "tasks": [
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "Do the market analysis."}]})
    rid = approved_routine(world, flow="daily-demo")
    write_flow(world, "daily-demo", {"flow": "daily-demo", "title": "Daily", "tasks": [
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "Do the market analysis, and more."}]})
    one = stopped(world, clock, "the workflow's template")
    assert routine(world, rid)["state"] == "stopped" and fires(world, rid)[0]["status"] == "asked"
    ctx = ctx_of(world)
    [question] = [p for p in ctx["store"].pending_list(ctx["conn"], "open") if p["task_id"] == one["request"]]
    assert question["kind"] == "question" and "stopped at" in question["title"] and "routine-approve" in question["body"]
    assert question["payload"]["routine"] == rid
    assert tasks_of(world, one["request"]) == {}, "no task was created"
    assert tick(world, clock.to(days=3)) == [], "a stopped routine is not ticked"
    shown = ops.routine_approve(world["path"], rid)
    assert shown["state"] == "stopped" and shown["approve"]["sha256"] != shown["approved_sha256"]
    ops.routine_approve(world["path"], rid, shown["approve"]["sha256"])
    assert routine(world, rid)["state"] == "active"
    assert ctx["store"].task_get(ctx["conn"], one["request"])["state"] == "cancelled", "approving cancels the request of the stop"
    assert [o["status"] for o in tick(world, clock.to(days=1, minutes=61))] == ["created"]


def set_version(world, skill, version):
    path = world["tree"] / "skills" / skill / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    import re
    path.write_text(re.sub(r'version: "[0-9.]+"', f'version: "{version}"', text), encoding="utf-8")


def test_a_change_of_a_skills_x_y_stops_it_and_a_z_change_does_not(world, clock):
    rid = approved_routine(world)
    set_version(world, "demo-writes", "0.1.1")                                          # Z
    [fired] = tick(world, clock.to(minutes=61))
    assert fired["status"] == "created"
    set_version(world, "demo-writes", "0.2.0")                                          # Y
    [asked] = tick(world, clock.to(days=1, minutes=61))
    assert asked["status"] == "asked" and "the version of demo-writes (0.1 to 0.2)" in asked["reason"]
    assert routine(world, rid)["state"] == "stopped"


def test_a_changed_eval_image_stops_it(world, clock, monkeypatch):
    approved_routine(world)
    monkeypatch.setattr(lab, "image", lambda: {"name": "standin", "digest": "sha256:" + "9" * 64, "platform": "linux/arm64"})
    stopped(world, clock, "the eval image")


def test_a_new_version_of_a_source_does_not_stop_it(world, clock):
    write_flow(world, "with-source", {"flow": "with-source", "title": "With a source", "tasks": [
        {"key": "reading", "skill": "demo-writes", "title": "Read", "text": "Read the survey.", "sources": ["survey"]}]})
    ops.source_import(world["path"], "survey", file=csv_file(world))
    approved_routine(world, flow="with-source")
    [first] = tick(world, clock.to(minutes=61))
    assert first["status"] == "created"
    ops.source_import(world["path"], "survey", file=csv_file(world, "survey2.csv", CSV + "fig,9.99\n"))
    [second] = tick(world, clock.to(days=1, minutes=61))
    assert second["status"] == "created" and tasks_of(world, second["request"])["reading"]["sources"] == ["survey"]


def test_the_default_model_the_routine_follows_is_part_of_what_it_approved(world, clock):
    path = world["project"] / "docs" / "workbench" / "runtime.json"

    def default_model(word):
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["default_model"] = word
        path.write_text(json.dumps(raw), encoding="utf-8")
        ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    default_model("m")
    rid = approved_routine(world, model=None)
    assert routine(world, rid)["model"] is None and ops.routines_read(world["path"])["routines"][0]["model_word"] == "m"
    default_model("fm")
    stopped(world, clock, "the model")


def test_the_workflow_failing_the_check_stops_the_routine_at_the_fire_as_it_would_at_the_save(world, clock):
    write_flow(world, "daily-demo", {"flow": "daily-demo", "title": "Daily", "tasks": [
        {"key": "market", "skill": "demo-writes", "title": "Market", "text": "Do it."}]})
    approved_routine(world, flow="daily-demo")
    write_flow(world, "daily-demo", {"flow": "daily-demo", "title": "Daily", "tasks": [
        {"key": "market", "skill": "demo-web", "title": "Market", "text": "Do it.", "sources": ["survey"]}]})
    stopped(world, clock, "the flow check refuses the workflow now")


# --- the model: auto inside the approved providers, a fixed one with the routine's own consent ---------------------------------------------


def test_auto_needs_the_providers_it_may_use_and_chooses_inside_them_and_a_better_candidate_outside_them_stops_it(world, clock, monkeypatch):
    with pytest.raises(ops_core.OpsError, match="names the providers it may use"):
        make(world, model="auto")
    with pytest.raises(ops_core.OpsError, match="is not a provider of the gate file's models"):
        make(world, model="auto", providers=["nowhere"])
    made = make(world, model="auto", providers=["direct"])
    assert made["content"]["providers"] == ["direct"] and made["content"]["model"] == "auto"
    approve(world, made["id"])
    calls = []

    def route(ctx, skill, meta, keys, task=None, requested=None, approved=None):
        calls.append((skill, approved))
        return {"mode": "auto", "model": "m", "outside_provider": [], "autonomy": "proven"}
    monkeypatch.setattr(ops_models, "route", route)
    [one] = tick(world, clock.to(minutes=61))
    assert one["status"] == "created" and any(a == {None} for _, a in calls) and any(a is None for _, a in calls)     # inside the set, and open
    tasks = tasks_of(world, one["request"])
    ctx = ctx_of(world)
    assert all(t["model"] == "m" for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] == one["request"])
    assert tasks and ctx["store"].task_get(ctx["conn"], one["request"])["model"] is None

    def better_outside(ctx, skill, meta, keys, task=None, requested=None, approved=None):
        if approved is not None:
            return {"mode": "auto", "model": "m", "outside_provider": ["fm"], "autonomy": "proven"}
        return {"mode": "auto", "model": "fm", "outside_provider": [], "autonomy": "proven"}
    monkeypatch.setattr(ops_models, "route", better_outside)
    [asked] = tick(world, clock.to(days=1, minutes=61))
    assert asked["status"] == "asked" and "a better candidate is fm, from a provider the routine was not approved for" in asked["reason"]
    assert routine(world, made["id"])["state"] == "stopped"


def unproven(world):
    """The stand-in skills are proven on the model `m` and not on `fm`."""
    return "fm"


def test_the_routines_own_consent_releases_a_fixed_unproven_model_and_the_agents_consent_never_does(world, clock):
    fixed = unproven(world)
    made = make(world, model=fixed)
    assert made["approve"]["consent_needed"] is True and made["approve"]["warning"] == autonomy.CONSENT_WARNING
    assert made["approve"]["warning_sha256"] == autonomy.CONSENT_WARNING_SHA256, "the warning is P3's constant, whole"
    approve(world, made["id"])
    [one] = tick(world, clock.to(minutes=61))
    rows = tasks_of(world, one["request"])
    ctx = ctx_of(world)
    meta = skill_meta.declared(os.path.join(str(world["tree"]), "skills", "demo-asks"))
    task = ctx["store"].task_get(ctx["conn"], rows["market"]["id"]) if "market" in rows else next(iter(rows.values()))
    routing = ops_models.route(ctx, "demo-asks", meta, None, task)
    assert routing["model"] == fixed and routing["autonomy"] == "supervised" and routing["consent"] is False, "an unproven pair, no consent: reviewed"
    # the agent's consent (D38), given for this very model, is not read for a routine's task
    agent_cfg = {"business": {"pack": "biz", "mode": "autonomous", "model": fixed, "consent": {"model": fixed, "mode": "autonomous"},
                              "max_runs_per_day": 50}}
    ctx["cfg"]["area_agents"] = {"business": autonomy.agents(agent_cfg)["business"]}
    again = ops_models.route(ctx, "demo-asks", meta, None, dict(task, agent="business"))
    assert again["autonomy"] == "supervised" and again["consent"] is False
    # the routine's own consent: the flag in the terminal; it enters the hash and a new approval is needed
    before = ops.routine_approve(world["path"], made["id"])["sha256"]
    changed = ops.routine_change(world["path"], made["id"], consent=True)
    assert changed["consent"] == 1 and changed["state"] == "draft" and changed["sha256"] != before
    approve(world, made["id"])
    [two] = tick(world, clock.to(days=1, minutes=61))
    task2 = next(t for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] == two["request"])
    yes = ops_models.route(ctx, "demo-asks", meta, None, task2)
    assert yes["autonomy"] == "consent" and yes["consent"] is True and any("carries the person's consent" in r for r in yes["reasons"])
    # a review of such a run is released by the routine's consent, and held when the routine no longer carries it
    run = {"task_id": task2["id"], "autonomy": "consent", "model": fixed}
    assert ops_models.consent_for_review(ctx, run, None, False) == (False, True)
    ops.routine_pause(world["path"], made["id"])
    assert ops_models.consent_for_review(ctx, run, None, False) == (False, False)
    # changing the model asks for the consent again
    ops.routine_resume(world["path"], made["id"])
    moved = ops.routine_change(world["path"], made["id"], model="m")
    assert moved["consent"] == 0 and moved["content"]["consent"] == {"given": False}
    back = ops.routine_change(world["path"], made["id"], model=fixed)
    assert back["consent"] == 0, "the consent did not come back with the model"


def test_the_consent_is_given_in_the_terminal_or_on_the_page_with_the_warning_and_never_from_messaging_or_for_auto(world, clock):
    with pytest.raises(ops_core.OpsError, match="never from a messaging channel"):
        make(world, model="fm", consent=True, channel="messaging")
    with pytest.raises(ops_core.OpsError, match="with the hash of the warning it showed"):
        make(world, model="fm", consent=True, channel="page")
    with pytest.raises(ops_core.OpsError, match="needs no consent"):
        make(world, model="auto", providers=["direct"], consent=True)
    page = make(world, model="fm", consent=True, warning_sha256=autonomy.CONSENT_WARNING_SHA256, channel="page")
    assert page["consent"] == 1 and page["content"]["consent"] == {"given": True, "warning_sha256": autonomy.CONSENT_WARNING_SHA256}


def test_a_proven_pair_needs_no_consent_and_a_run_on_it_is_proven(world, clock):
    made = make(world, model="m")
    assert made["approve"]["consent_needed"] is False
    approve(world, made["id"])
    [one] = tick(world, clock.to(minutes=61))
    ctx = ctx_of(world)
    task = next(t for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] == one["request"])
    meta = skill_meta.declared(os.path.join(str(world["tree"]), "skills", task["skill"]))
    assert ops_models.route(ctx, task["skill"], meta, None, task)["autonomy"] == "proven"


# --- the kinds of step a fire may start --------------------------------------------------------------------------------------------------


def test_a_step_of_a_kind_that_is_not_unattended_is_held_for_the_person_whatever_made_the_task(world, clock, monkeypatch):
    kind = steps.Kind(name="by-hand", order=("go",), executors={"go": lambda ctx, state: {}}, unattended=False)
    monkeypatch.setitem(steps.REGISTRY, "by-hand", kind)
    write_flow(world, "with-steps", {"flow": "with-steps", "title": "Steps", "tasks": [
        {"key": "pull", "step": "by-hand", "title": "Pull", "args": {}},
        {"key": "refresh", "step": "ingest", "title": "Refresh", "args": {"source": "survey"}}]})
    approved_routine(world, flow="with-steps")
    [one] = tick(world, clock.to(minutes=61))
    assert one["status"] == "created"
    ctx = ctx_of(world)
    rows = {t["key"]: t for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] == one["request"]}
    assert ops_steps.held_reason(ctx, rows["pull"]) == "start it by hand" and ops_steps.held_reason(ctx, rows["refresh"]) is None


# --- the round and the page ------------------------------------------------------------------------------------------------------------------


def test_the_dispatchers_round_carries_the_fire_and_a_failure_of_a_routine_never_stops_it(world, clock, monkeypatch):
    approved_routine(world)
    ctx = ctx_of(world)
    ops_runs = st.load("ops_runs")
    clock.to(minutes=61)
    [one] = ops_runs._fire_routines(ctx)
    assert one["status"] == "created"
    monkeypatch.setattr(ops_routines, "tick", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ops_runs._fire_routines(ctx) == [{"error": "RuntimeError: boom"}]


def test_the_list_says_for_each_routine_whether_its_hash_is_the_approved_one_and_its_last_fire(world, clock):
    rid = approved_routine(world)
    [row] = ops.routines_read(world["path"])["routines"]
    assert row["current"] is True and row["last_fire"] is None and row["model_word"] == "m"
    tick(world, clock.to(minutes=61))
    [row] = ops.routines_read(world["path"])["routines"]
    assert row["last_fire"]["status"] == "created" and row["last_fire"]["slot"] == SLOT
    detail = ops.routines_read(world["path"], rid)
    assert [f["status"] for f in detail["fires"]] == ["created"] and "approve" not in detail
    set_version(world, "demo-asks", "0.9.0")
    assert ops.routines_read(world["path"])["routines"][0]["current"] is False


def test_a_provider_set_that_differs_from_the_approved_one_stops_the_routine_at_the_fire(world, clock):
    made = make(world, model="auto", providers=["direct"])
    approve(world, made["id"])
    ctx = ctx_of(world)
    with ctx["store"].write(ctx["conn"]):      # a record changed behind the operations' back: the hash catches it all the same
        ctx["conn"].execute("UPDATE routines SET providers = '[\"direct\", \"elsewhere\"]' WHERE id = ?", (made["id"],))
    stopped(world, clock, "the approved providers")
    assert routine(world, made["id"])["state"] == "stopped"


def test_the_tasks_a_fire_creates_belong_to_the_area_agents_and_so_count_against_their_caps(world, clock, monkeypatch):
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: {"biz": ["demo-asks", "demo-writes"]}[pack])
    path = world["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = {"business": {"pack": "biz", "mode": "supervised", "max_runs_per_day": 5}}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    rid = approved_routine(world)
    [one] = tick(world, clock.to(minutes=61))
    ctx = ctx_of(world)
    assert {t["agent"] for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] == one["request"]} == {"business"}
    assert "mode" not in routine(world, rid) and "max_runs_per_day" not in routine(world, rid), "a routine carries no mode or cap of its own"
