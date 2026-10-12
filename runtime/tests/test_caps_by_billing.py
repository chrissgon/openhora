"""Tests of package ADJ-R3 (row A-38): the daily caps follow the billing of the credential a run used, not the model's
tier. The pure rules of runtime/autonomy.py (the split by billing, the fallback for a run older than the column, the
start rule), the manifest reader runtime/billing.py, the dispatcher's use of the billing it resolved, and the operations
on the stand-in tree of standin_tree.py: the billing a run records, the cost a metered run keeps, the `agents` read and the
three projects of the package's acceptance (a subscription reference with a metered floor key, an API key as the reference
credential, a subscription alone). Offline; invented names, invented keys (EXAMPLE_*), no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_caps_by_billing.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st

autonomy = st.load("autonomy")
billing = st.load("billing")
dispatcher = st.load("dispatcher")
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
plan = st.load("plan")

# six runs of one agent across the three billings and both tiers' models, and one run of another agent
RUNS = [
    {"agent": "brand", "model": "ref", "billing": "subscription", "cost_usd": None},
    {"agent": "brand", "model": "floor", "billing": "subscription", "cost_usd": 0.2},   # a cost on a subscription run is not billed
    {"agent": "brand", "model": "ref", "billing": "metered", "cost_usd": 0.4},
    {"agent": "brand", "model": "floor", "billing": "metered", "cost_usd": None},
    {"agent": "brand", "model": "floor", "billing": "free", "cost_usd": None},
    {"agent": "brand", "model": "ref", "billing": "metered", "cost_usd": 0.03},
    {"agent": "business", "model": "ref", "billing": "metered", "cost_usd": 0.9},
]


# --- the vocabulary is written once per place that must know it -------------------------------------------------------------------


def test_the_three_words_are_the_same_in_the_manifest_reader_the_caps_and_the_store():
    assert tuple(billing.WORDS) == ("subscription", "metered", "free"), "the words a manifest may declare"
    assert tuple(autonomy.BILLINGS) == billing.WORDS + ("unknown",), "the runtime adds one, for a route no manifest could bill"
    assert set(autonomy.RUNS_BILLINGS) | set(autonomy.SPEND_BILLINGS) == set(autonomy.BILLINGS) - {"unknown"}
    assert set(autonomy.RUNS_BILLINGS) == {"subscription", "free"} and set(autonomy.SPEND_BILLINGS) == {"metered"}


# --- autonomy.spend_split: the split by billing -----------------------------------------------------------------------------------


def test_subscription_and_free_runs_count_as_runs_and_metered_runs_as_dollars():
    split = autonomy.spend_split(RUNS, "brand", 0.5)
    assert split == {"usd_recorded": 0.43, "usd_reserved": 0.5, "runs_total": 6, "runs_counted": 3, "runs_without_cost": 1}
    # a metered run of unknown cost is reserved at the per-run limit, never counted as free
    assert autonomy.spend_split(RUNS, "brand", 0.25)["usd_reserved"] == 0.25
    # the other agent's run is not counted here; an agent nobody ran has nothing
    assert autonomy.spend_split(RUNS, "business", 0.5) == {"usd_recorded": 0.9, "usd_reserved": 0.0, "runs_total": 1,
                                                          "runs_counted": 0, "runs_without_cost": 0}
    assert autonomy.spend_split(RUNS, "nobody", 0.5) == {"usd_recorded": 0.0, "usd_reserved": 0.0, "runs_total": 0,
                                                        "runs_counted": 0, "runs_without_cost": 0}


def test_spend_is_the_split_folded_and_the_two_parts_add_up_to_the_dollars_exactly():
    split = autonomy.spend_split(RUNS, "brand", 0.5)
    spent = autonomy.spend(RUNS, "brand", 0.5)
    assert spent == {"runs_counted": 3, "usd_metered": split["usd_recorded"] + split["usd_reserved"], "runs_without_cost": 1}
    import inspect
    assert "cost_usd" not in inspect.getsource(autonomy.spend), "spend reads spend_split: the rule is written once"


def test_a_run_recorded_as_unknown_counts_as_metered_and_is_not_a_row_older_than_the_column():
    rows = [{"agent": "a", "model": "ref", "billing": "unknown", "cost_usd": None}, {"agent": "a", "model": "ref", "billing": "unknown", "cost_usd": 0.2}]
    assert autonomy.spend_split(rows, "a", 0.5) == {"usd_recorded": 0.2, "usd_reserved": 0.5, "runs_total": 2, "runs_counted": 0, "runs_without_cost": 1}
    kept = autonomy.with_billing(rows, "floor")
    assert [r["billing"] for r in kept] == ["unknown", "unknown"], "unknown is a word, not the NULL of an older row: the tier rule does not apply"


def test_a_run_whose_billing_is_unknown_counts_as_metered_never_as_free():
    odd = [{"agent": "a", "model": "m", "billing": "prepaid", "cost_usd": 0.1}, {"agent": "a", "model": "m", "billing": None, "cost_usd": None}]
    split = autonomy.spend_split(odd, "a", 0.5)
    assert split["runs_counted"] == 0 and split["usd_recorded"] == 0.1 and split["usd_reserved"] == 0.5


# --- the fallback for a run older than the column, for history only ---------------------------------------------------------------


def test_history_billing_follows_the_old_tier_rule_for_a_run_with_no_billing():
    assert autonomy.history_billing({"model": "floor", "billing": None}, "floor") == "metered"
    assert autonomy.history_billing({"model": "ref", "billing": None}, "floor") == "subscription"
    assert autonomy.history_billing({"model": "another", "billing": None}, "floor") == "subscription"
    for word in autonomy.BILLINGS:   # a recorded billing is never replaced
        assert autonomy.history_billing({"model": "floor", "billing": word}, "floor") == word


def test_the_three_cases_of_a_row_null_unknown_and_a_known_word():
    rows = [{"agent": "a", "model": "ref", "billing": None, "cost_usd": None}, {"agent": "a", "model": "ref", "billing": "unknown", "cost_usd": None},
            {"agent": "a", "model": "ref", "billing": "subscription", "cost_usd": None}]
    filled = autonomy.with_billing(rows, "floor")
    assert [r["billing"] for r in filled] == ["subscription", "unknown", "subscription"], "NULL: the tier rule (a reference-model run is a subscription run)"
    assert autonomy.spend_split(filled, "a", 0.5)["runs_counted"] == 2 and autonomy.spend_split(filled, "a", 0.5)["usd_reserved"] == 0.5, "unknown: metered"


def test_the_spend_limit_of_a_metered_run_is_the_per_run_limit_or_what_is_left_of_the_day():
    entries, _ = checked(runs=2, usd=4.0)
    entry = entries["a"]
    assert autonomy.run_budget(entry, spent(usd=3.8), 0.5) == 0.2, "$4.00 cap, $3.80 spent: 0.20"
    assert autonomy.run_budget(entry, spent(usd=0.0), 0.5) == 0.5, "plenty left: the per-run limit"
    assert autonomy.run_budget(entry, spent(usd=3.97), 0.5) is None, "under the least budget: no run is started"
    assert autonomy.run_budget(entry, spent(usd=4.0), 0.5) is None and autonomy.run_budget(entry, spent(usd=9.0), 0.5) is None
    assert autonomy.run_budget(entry, spent(usd=3.999 - 3.9), 0.5) == 0.5
    assert autonomy.run_budget(entry, spent(usd=3.8749), 0.5) == 0.12, "rounded down to the cent, never above what is left"
    assert autonomy.MIN_RUN_BUDGET_USD == 0.05


def test_with_billing_fills_only_the_runs_that_have_none_and_changes_no_input():
    runs = [{"agent": "a", "model": "floor", "cost_usd": 0.3}, {"agent": "a", "model": "ref", "cost_usd": None},
            {"agent": "a", "model": "ref", "billing": "metered", "cost_usd": 0.2}]
    before = json.dumps(runs)
    filled = autonomy.with_billing(runs, "floor")
    assert [r["billing"] for r in filled] == ["metered", "subscription", "metered"]
    assert json.dumps(runs) == before
    # the days before the column count as they always did: the floor model's dollars, the others' runs
    assert autonomy.spend(filled, "a", 0.5) == {"runs_counted": 1, "usd_metered": 0.5, "runs_without_cost": 0}


# --- autonomy.may_start: by the billing of the run about to start ------------------------------------------------------------------


def checked(runs=2, usd=1.0):
    entries = autonomy.agents({"a": {"pack": "p", "mode": "autonomous", "max_runs_per_day": runs, "max_usd_per_day": usd}})
    return entries, autonomy.facts("a", entries, [], "2026-10-10T00:00:00Z")


def spent(runs=0, usd=0.0):
    return {"runs_counted": runs, "usd_metered": usd, "runs_without_cost": 0}


def test_a_subscription_or_free_run_is_held_by_the_runs_cap_only():
    entries, f = checked(runs=2, usd=1.0)
    for word in ("subscription", "free"):
        assert autonomy.may_start("a", entries, f, spent(runs=1, usd=5.0), word) == (True, ""), "dollars never hold a run of this billing"
        assert autonomy.may_start("a", entries, f, spent(runs=2), word) == (False, "cap: runs per day")


def test_a_metered_run_is_held_by_the_dollar_cap_only():
    entries, f = checked(runs=2, usd=1.0)
    assert autonomy.may_start("a", entries, f, spent(runs=9, usd=0.9), "metered") == (True, ""), "runs never hold a metered run"
    assert autonomy.may_start("a", entries, f, spent(usd=0.97), "metered") == (False, "cap: usd per day"), "under the least budget a run may be given"
    assert autonomy.may_start("a", entries, f, spent(usd=1.0), "metered") == (False, "cap: usd per day")
    assert autonomy.may_start("a", entries, f, spent(usd=2.5), "metered") == (False, "cap: usd per day")


def test_the_dollar_cap_is_reached_by_the_rounded_sum():
    entries, f = checked(usd=0.8)
    assert 0.1 + 0.7 < 0.8   # a sum a float leaves a hair under the cap
    assert autonomy.may_start("a", entries, f, spent(usd=0.1 + 0.7), "metered") == (False, "cap: usd per day")
    assert autonomy.may_start("a", entries, f, spent(usd=0.7), "metered") == (True, "")


@pytest.mark.parametrize("word", ["prepaid", "", None, "strong", "floor"])
def test_an_unknown_billing_refuses_the_start_and_says_so(word):
    entries, f = checked()
    ok, why = autonomy.may_start("a", entries, f, spent(), word)
    assert ok is False and why == f"unknown billing {word!r}"


def test_an_absent_cap_is_zero_for_each_billing_and_a_stopped_agent_stays_stopped():
    entries = autonomy.agents({"a": {"pack": "p", "mode": "autonomous"}, "q": {"pack": "p", "mode": "stopped", "max_runs_per_day": 5}})
    f = autonomy.facts("a", entries, [], "2026-10-10T00:00:00Z")
    assert autonomy.may_start("a", entries, f, spent(), "subscription") == (False, "cap: runs per day")
    assert autonomy.may_start("a", entries, f, spent(), "free") == (False, "cap: runs per day")
    assert autonomy.may_start("a", entries, f, spent(), "metered") == (False, "cap: usd per day")
    quiet = autonomy.facts("q", entries, [], "2026-10-10T00:00:00Z")
    assert autonomy.may_start("q", entries, quiet, spent(), "subscription") == (False, "stopped")
    assert autonomy.may_start("nobody", entries, f, spent(), "subscription") == (False, "stopped")


# --- runtime/billing.py: the manifests' reader ------------------------------------------------------------------------------------

MANIFESTS = {
    "alpha": {"harness": "alpha", "login_billing": "subscription", "secrets": [
        {"name": "EXAMPLE_TOKEN", "billing": "subscription"}, {"name": "EXAMPLE_KEY", "billing": "metered"}]},
    "beta": {"harness": "beta", "secrets": [{"name": "EXAMPLE_KEY", "billing": "metered"}, {"name": "EXAMPLE_LOCAL", "billing": "free"},
                                            {"name": "EXAMPLE_ODD", "billing": "prepaid"}, {"name": "EXAMPLE_NONE"}]},
}


def test_the_billing_of_a_route_is_the_manifest_entry_of_the_variable_it_passes():
    assert billing.of_route(MANIFESTS, "alpha", ["EXAMPLE_TOKEN"]) == "subscription"
    assert billing.of_route(MANIFESTS, "alpha", ["EXAMPLE_KEY"]) == "metered"
    assert billing.of_route(MANIFESTS, "beta", ["EXAMPLE_LOCAL"]) == "free"


def test_a_variable_the_adapter_does_not_list_is_found_in_another_adapters_manifest():
    assert billing.of_route(MANIFESTS, "alpha", ["EXAMPLE_LOCAL"]) == "free"
    assert billing.of_route(MANIFESTS, "beta", ["EXAMPLE_TOKEN"]) == "subscription"


def test_a_route_with_no_variable_reads_the_login_billing_of_its_adapter():
    assert billing.of_route(MANIFESTS, "alpha", []) == "subscription"
    assert billing.of_route(MANIFESTS, "beta", []) is None, "an adapter with no login declared has no billing to guess"
    assert billing.of_route(MANIFESTS, "gamma", []) is None


def test_an_unlisted_variable_or_a_word_outside_the_three_is_unknown_never_a_guess():
    assert billing.of_route(MANIFESTS, "alpha", ["EXAMPLE_MISSING"]) is None
    assert billing.of_route(MANIFESTS, "beta", ["EXAMPLE_ODD"]) is None
    assert billing.of_route(MANIFESTS, "beta", ["EXAMPLE_NONE"]) is None
    assert billing.of_route(MANIFESTS, "alpha", ["EXAMPLE_TOKEN", "EXAMPLE_MISSING"]) is None, "one unknown makes the route unknown"


def test_several_variables_of_one_route_take_the_strictest_billing_metered_first():
    assert billing.of_route(MANIFESTS, "alpha", ["EXAMPLE_TOKEN", "EXAMPLE_KEY"]) == "metered"
    assert billing.of_route(MANIFESTS, "beta", ["EXAMPLE_LOCAL", "EXAMPLE_TOKEN"]) == "subscription"
    assert billing.of_route(MANIFESTS, "beta", ["EXAMPLE_LOCAL"]) == "free"


def test_the_manifests_of_the_checkout_declare_the_billing_of_every_credential_the_gate_file_names():
    manifests = billing.load(str(st.REPO))
    assert {"agents-dir", "api", "claude-code"} <= set(manifests)
    gate = json.loads((st.REPO / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    assert billing.of_route(manifests, gate["strong_harness"], gate["strong_pass_env"]) == "subscription"
    assert billing.of_route(manifests, gate["floor_harness"], gate["floor_pass_env"]) == "metered"
    assert billing.of_route(manifests, "claude-code", []) == "subscription", "the CLI's own login"
    assert billing.of_route(manifests, "claude-code", ["ANTHROPIC_API_KEY"]) == "metered", "an API key as the reference credential"
    assert billing.of_route(manifests, "api", ["OPENROUTER_API_KEY"]) == "metered"
    assert billing.of_route(manifests, "claude-code", ["CLAUDE_CODE_WEB_API_KEY"]) == "metered"


def test_load_reads_only_adapter_manifests_and_survives_one_that_is_unreadable(tmp_path):
    (tmp_path / "adapters" / "one").mkdir(parents=True)
    (tmp_path / "adapters" / "one" / "adapter.json").write_text(json.dumps({"login_billing": "free", "secrets": []}), encoding="utf-8")
    (tmp_path / "adapters" / "two").mkdir()
    (tmp_path / "adapters" / "two" / "adapter.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "adapters" / "three").mkdir()   # no manifest at all
    assert set(billing.load(str(tmp_path))) == {"one"}
    assert billing.load(str(tmp_path / "missing")) == {}


# --- the dispatcher passes the billing it resolved --------------------------------------------------------------------------------


def agent_snapshot(runs=0, usd=0.0, runs_cap=5, usd_cap=1.0):
    entry = {"pack": "p", "enabled": True, "mode": "autonomous", "max_runs_per_day": runs_cap, "max_usd_per_day": usd_cap}
    return {"entry": entry, "facts": autonomy.facts("x", {"x": entry}, [], "2026-10-10T00:00:00Z"),
            "spent": {"runs_counted": runs, "usd_metered": usd, "runs_without_cost": 0}}


def ready(task_id):
    return {"id": task_id, "agent": "x", "state": "ready", "milestone": 0, "parent_id": 1}


def test_decide_gives_each_task_the_billing_of_its_route():
    seen = []

    def may_start(name, entries, facts, spent_, word):
        seen.append(word)
        return True, ""

    snapshot = {"running": None, "ready": [ready(4)], "reviews": [], "agents": {"x": agent_snapshot()}, "tier": {4: "strong"},
                "billing": {4: "metered"}}
    assert dispatcher.decide(snapshot, autonomy.review_action, may_start)["start"] == 4
    assert seen == ["metered"]


def test_a_metered_task_is_held_at_the_dollar_cap_whatever_its_tier_and_the_runs_cap():
    snapshot = {"running": None, "ready": [ready(4), ready(5)], "reviews": [], "agents": {"x": agent_snapshot(runs=0, usd=1.0, runs_cap=0)},
                "tier": {4: "strong", 5: "strong"}, "billing": {4: "metered", 5: "subscription"}}
    got = dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start)
    assert got["start"] is None
    assert got["held"] == [{"task_id": 4, "why": "cap: usd per day"}, {"task_id": 5, "why": "cap: runs per day"}]


def test_a_metered_task_under_its_dollar_cap_starts_although_the_runs_cap_is_zero():
    snapshot = {"running": None, "ready": [ready(4)], "reviews": [], "agents": {"x": agent_snapshot(runs=7, usd=0.2, runs_cap=0)},
                "tier": {4: "strong"}, "billing": {4: "metered"}}
    assert dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start)["start"] == 4


def test_a_task_with_no_billing_in_the_snapshot_is_held_as_unknown_and_the_reason_reaches_a_page_as_other():
    snapshot = {"running": None, "ready": [ready(4)], "reviews": [], "agents": {"x": agent_snapshot()}, "tier": {4: "strong"}, "billing": {}}
    got = dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start)
    assert got["start"] is None and got["held"] == [{"task_id": 4, "why": "unknown billing None"}]
    assert dispatcher.held_of(snapshot, got) == [{"task_id": 4, "agent": "x", "reason": dispatcher.OTHER}]


# --- the operations, on the stand-in tree -----------------------------------------------------------------------------------------

AGENTS = {"business": {"pack": "biz", "mode": "autonomous", "max_runs_per_day": 5, "max_usd_per_day": 1.0}}
PACKS = {"biz": ["demo-asks", "demo-writes"]}
API_KEY = "EXAMPLE_API_KEY"        # registered by the stand-in manifest as metered (standin_tree.SECRETS)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS[pack]))
    (built["tree"] / "flows" / "single.json").write_text(json.dumps({"flow": "single", "title": "Single", "tasks": [
        {"key": "profile", "skill": "demo-writes", "title": "Profile", "text": "write the profile."}]}), encoding="utf-8")
    business = built["project"] / "docs" / "business"
    business.mkdir(parents=True)
    (business / "market.md").write_text("# Market analysis\n\n- Owner: demo-asks\n- Status: draft\n", encoding="utf-8")
    configure(built, AGENTS)
    return built


def configure(tree, agents) -> None:
    path = tree["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = agents
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(tree["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])


def credentials(monkeypatch, strong=(), floor=(), floor_key=True):
    """The variables each tier passes (names only), whether a key for the floor model was found, and no real lookup."""
    control = {"total_jobs": 2, "web_jobs": {"strong": 1, "floor": 1}}
    tiers = {"strong": ("m", list(strong)), "floor": ("fm", list(floor))}
    monkeypatch.setattr(lab, "reference", lambda tier="strong": {
        "tier": tier, "model": tiers[tier][0], "adapter": "h", "pass_env": tiers[tier][1], "timeout_seconds": 60, "retries": 2,
        "control": control})
    monkeypatch.setattr(lab, "credential_missing", lambda tier: [])
    monkeypatch.setattr(ops_core, "_floor_key", lambda: {"value": None, "source": "lab" if floor_key else None,
                                                        "reason": None if floor_key else "no key"})


def plan_single(tree) -> None:
    path = str(tree["project"])
    request = ops.request(path, "Invented request.", title="Invented")["request"]
    pending_id = ops.route(path, request, "single")["pending_id"]
    ops.approve(path, pending_id, ops.pending(path, pending_id)["payload"]["plan_sha256"])


def seed(tree, rows) -> None:
    """Runs of today for the planned task: (model, billing, cost) -> a row of task_runs, as the store holds it."""
    import datetime
    ctx = ops_core.context(str(tree["project"]))
    task = next(t for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] is not None)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for model, word, cost in rows:
        ctx["conn"].execute("INSERT INTO task_runs (task_id, skill, model, adapter, status, started_at, cost_usd, billing) "
                            "VALUES (?, ?, ?, 'h', 'ok', ?, ?, ?)", (task["id"], task["skill"], model, now, cost, word))
    ctx["conn"].commit()


def runs_of(tree):
    ctx = ops_core.context(str(tree["project"]))
    return [r for t in ctx["store"].tasks_list(ctx["conn"]) for r in ctx["store"].task_runs_list(ctx["conn"], t["id"])]


def test_a_run_records_the_billing_of_the_credential_it_used_and_a_subscription_run_keeps_no_cost(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch)                      # no variable: the harness's own login, declared subscription
    plan_single(tree)
    out = ops.run_next(path)
    assert out["status"] == "ok" and out["routing"]["billing"] == "subscription"
    [run] = runs_of(tree)
    assert run["billing"] == "subscription" and run["cost_usd"] is None, "the stand-in adapter reported 0.01; it is not billed"
    assert ops.task(path, run["task_id"])["runs"][0]["billing"] == "subscription", "the task read carries it on each run row"


def test_a_metered_run_keeps_the_cost_the_adapter_reported_on_any_tier(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=[API_KEY])    # the reference model through an API key
    monkeypatch.setenv(API_KEY, "invented-value-never-shown")
    plan_single(tree)
    out = ops.run_next(path)
    assert out["status"] == "ok" and out["routing"]["tier"] == "strong" and out["routing"]["billing"] == "metered"
    [run] = runs_of(tree)
    assert run["billing"] == "metered" and run["cost_usd"] == 0.01


def test_a_run_whose_billing_cannot_be_resolved_is_recorded_as_unknown(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=["EXAMPLE_UNLISTED"])
    monkeypatch.setenv("EXAMPLE_UNLISTED", "invented-value-never-shown")
    plan_single(tree)
    assert ops.run_next(path)["routing"]["billing"] is None
    assert runs_of(tree)[0]["billing"] == "unknown", "written at the start; NULL is only a row older than the column"


def test_the_snapshot_carries_the_billing_of_each_ready_task(tree, monkeypatch):
    credentials(monkeypatch, strong=[API_KEY])
    plan_single(tree)
    ctx = ops_core.context(str(tree["project"]))
    snapshot = ops._snapshot(ctx, ops_core._floor_key())
    [task_id] = snapshot["tier"]
    assert snapshot["billing"] == {task_id: "metered"}


def test_the_agents_read_counts_by_billing_and_says_which_meters_are_in_use(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch)
    plan_single(tree)
    seed(tree, [("m", "subscription", None), ("m", "subscription", None), ("fm", "metered", 0.3), ("fm", "metered", None)])
    [got] = ops.agents(path)["agents"]
    assert got["runs_today"] == 2 and got["runs_total_today"] == 4 and got["runs_without_cost"] == 1
    assert got["usd_recorded"] == pytest.approx(0.3) and got["usd_reserved"] == pytest.approx(ops.PER_RUN_USD)
    assert got["usd_today"] == got["usd_recorded"] + got["usd_reserved"]
    assert got["billing"] == {"runs": ["subscription", "free"], "spend": ["metered"]}
    assert got["caps_in_use"] == {"runs": True, "spend": True}


def test_a_run_from_before_the_column_counts_by_the_old_tier_rule(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch)
    plan_single(tree)
    seed(tree, [("m", None, None), ("fm", None, 0.4), ("fm", None, None)])
    [got] = ops.agents(path)["agents"]
    assert got["runs_today"] == 1 and got["usd_today"] == pytest.approx(0.4 + ops.PER_RUN_USD) and got["runs_without_cost"] == 1
    assert got["caps_in_use"]["spend"] is True, "a day with dollars shows the dollar meter"


# --- the acceptance: three projects --------------------------------------------------------------------------------------------


def test_a_subscription_reference_and_a_metered_floor_key_show_two_meters_and_count_as_before(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=[], floor=["STANDIN_FLOOR_PASS"], floor_key=True)
    plan_single(tree)
    seed(tree, [("m", "subscription", None), ("m", "subscription", None), ("fm", "metered", 0.25)])
    [got] = ops.agents(path)["agents"]
    assert (got["runs_today"], got["usd_today"], got["runs_total_today"]) == (2, 0.25, 3)
    assert got["caps_in_use"] == {"runs": True, "spend": True}
    caps = ops.costs(path)["caps"][0]
    assert (caps["runs_today"], caps["usd_today"]) == (2, 0.25)


def test_an_api_key_as_the_reference_credential_counts_its_runs_in_dollars_and_holds_at_the_dollar_cap(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=[API_KEY], floor_key=False)
    monkeypatch.setenv(API_KEY, "invented-value-never-shown")
    configure(tree, {"business": dict(AGENTS["business"], max_runs_per_day=0, max_usd_per_day=1.0)})   # no runs cap at all
    plan_single(tree)
    seed(tree, [("m", "metered", 0.6)])
    [got] = ops.agents(path)["agents"]
    assert got["runs_today"] == 0 and got["usd_today"] == pytest.approx(0.6), "reference runs are counted in dollars"
    assert got["caps_in_use"] == {"runs": False, "spend": True}
    seed(tree, [("m", "metered", 0.4)])
    out = ops.dispatch(path)
    assert out["ran"] == [] and out["stopped"] == "nothing may start"
    assert [h["reason"] for h in ops.status(path)["held"]] == ["cap: usd per day"], "held at max_usd_per_day, not at the runs cap"


def test_the_same_project_below_its_dollar_cap_runs_although_its_runs_cap_is_zero(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=[API_KEY], floor_key=False)
    monkeypatch.setenv(API_KEY, "invented-value-never-shown")
    configure(tree, {"business": dict(AGENTS["business"], max_runs_per_day=0, max_usd_per_day=1.0)})
    plan_single(tree)
    seed(tree, [("m", "metered", 0.4)])
    out = ops.dispatch(path)
    assert len(out["ran"]) == 1 and out["ran"][0]["status"] == "ok"
    assert [r for r in runs_of(tree) if r["billing"] == "metered" and r["cost_usd"] == 0.01], "the new run is metered and keeps its cost"


def test_a_project_whose_only_credential_is_a_subscription_shows_one_meter(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, floor_key=False)
    plan_single(tree)
    seed(tree, [("m", "subscription", None)])
    [got] = ops.agents(path)["agents"]
    assert got["caps_in_use"] == {"runs": True, "spend": False}
    assert got["runs_today"] == 1 and got["usd_today"] == 0.0


def test_a_free_credential_counts_in_runs_and_a_route_with_an_unlisted_credential_is_held(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=["EXAMPLE_UNLISTED"], floor_key=False)
    plan_single(tree)
    out = ops.dispatch(path)
    assert out["ran"] == [] and [h["reason"] for h in ops.status(path)["held"]] == [dispatcher.OTHER]
    assert autonomy.spend_split([{"agent": "a", "model": "m", "billing": "free", "cost_usd": None}], "a", 0.5)["runs_counted"] == 1


def test_the_planning_agent_s_router_run_is_held_by_the_billing_of_its_route(tree, monkeypatch):
    credentials(monkeypatch, strong=[API_KEY], floor_key=False)
    st.skill(tree["tree"], st.load("router").ROUTER_SKILL, "docs/workbench/state.md", "")   # the router, as the stand-in tree has it
    configure(tree, {"planning": {"pack": "biz", "mode": "autonomous", "max_runs_per_day": 9, "max_usd_per_day": 0.5}})
    ctx = ops_core.context(str(tree["project"]))
    ops_say = st.load("ops_say")
    assert ops_say._planning_may_start(ctx) == (True, "")
    request = ops.request(str(tree["project"]), "Invented request.", title="Invented")["request"]
    store, conn = ctx["store"], ctx["conn"]
    run = store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h", billing="metered")["run_id"]
    store.route_run_finish(conn, run, status="ok", cost_usd=0.5)
    assert ops_say._planning_may_start(ctx) == (False, "cap: usd per day")


# --- the spend limit travels with a metered run --------------------------------------------------------------------------------


def watch_budget(monkeypatch) -> list:
    """The max_cost each call of lab.run_skill gets."""
    seen, real = [], lab.run_skill

    def run_skill(*args, **kwargs):
        seen.append(kwargs.get("max_cost"))
        return real(*args, **kwargs)

    monkeypatch.setattr(lab, "run_skill", run_skill)
    return seen


def test_a_metered_run_is_given_what_is_left_of_the_day_as_its_spend_limit(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=[API_KEY], floor_key=False)
    monkeypatch.setenv(API_KEY, "invented-value-never-shown")
    configure(tree, {"business": dict(AGENTS["business"], max_usd_per_day=4.0)})
    plan_single(tree)
    seed(tree, [("m", "metered", 3.8)])
    seen = watch_budget(monkeypatch)
    assert ops.run_next(path)["status"] == "ok"
    assert seen == [0.2], "$4.00 cap and $3.80 spent: the run is given 0.20, not the per-run limit"


def test_a_metered_run_with_plenty_left_gets_the_per_run_limit_and_a_subscription_run_none(tree, monkeypatch):
    path = str(tree["project"])
    seen = watch_budget(monkeypatch)
    credentials(monkeypatch, strong=[API_KEY], floor_key=False)
    monkeypatch.setenv(API_KEY, "invented-value-never-shown")
    configure(tree, {"business": dict(AGENTS["business"], max_usd_per_day=4.0)})
    plan_single(tree)
    ops.run_next(path)
    credentials(monkeypatch, floor_key=False)       # the harness's own login: a subscription
    plan_single(tree)
    ops.run_next(path)
    assert seen == [0.5, None]


def test_a_task_the_dollar_cap_leaves_under_the_least_budget_is_held_not_started(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=[API_KEY], floor_key=False)
    monkeypatch.setenv(API_KEY, "invented-value-never-shown")
    configure(tree, {"business": dict(AGENTS["business"], max_usd_per_day=4.0)})
    plan_single(tree)
    seed(tree, [("m", "metered", 3.97)])
    out = ops.dispatch(path)
    assert out["ran"] == [] and [h["reason"] for h in ops.status(path)["held"]] == ["cap: usd per day"]


def test_a_run_started_on_a_route_no_manifest_bills_records_unknown_counts_as_metered_and_is_bounded(tree, monkeypatch):
    path = str(tree["project"])
    credentials(monkeypatch, strong=["EXAMPLE_UNLISTED"], floor_key=False)
    monkeypatch.setenv("EXAMPLE_UNLISTED", "invented-value-never-shown")
    plan_single(tree)
    seen = watch_budget(monkeypatch)
    assert ops.run_next(path)["status"] == "ok"
    [run] = runs_of(tree)
    assert run["billing"] == "unknown" and run["cost_usd"] is None and seen == [0.5]
    [got] = ops.agents(path)["agents"]
    assert got["runs_today"] == 0 and got["usd_reserved"] == pytest.approx(ops.PER_RUN_USD) and got["runs_without_cost"] == 1
    assert got["caps_in_use"] == {"runs": True, "spend": True}, "nothing says which cap: both meters, as for a service that sends none"


# --- the tier's billing and the container's environment ----------------------------------------------------------------------------


def test_the_billing_of_a_tier_is_the_manifest_reading_of_the_gate_files_variables_for_both_tiers():
    for tier, expected in (("strong", "subscription"), ("floor", "metered")):
        found = lab.reference(tier)
        assert ops_core._tier_billing(tier) == billing.of_route(billing.load(str(st.REPO)), found["adapter"], found["pass_env"]) == expected


def test_the_container_environment_drops_a_provider_key_unless_it_is_passed(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_WEB_API_KEY"):
        monkeypatch.setenv(name, "invented-value-never-shown")
    bare = lab.LAB.contained_env(str(tmp_path / "a"), ())
    assert "ANTHROPIC_API_KEY" not in bare and "CLAUDE_CODE_WEB_API_KEY" not in bare
    passed = lab.LAB.contained_env(str(tmp_path / "b"), ("ANTHROPIC_API_KEY",))
    assert "ANTHROPIC_API_KEY" in passed and "CLAUDE_CODE_WEB_API_KEY" not in passed


def test_caps_in_use_reads_the_manifests_once_and_takes_the_key_from_its_caller(monkeypatch):
    calls = []
    real = billing.load
    monkeypatch.setattr(billing, "load", lambda root: calls.append(root) or real(root))
    monkeypatch.setattr(ops_core, "_floor_key", lambda: (_ for _ in ()).throw(AssertionError("the caller gives the key")))
    both = ops_core._caps_in_use([], {"value": None, "source": "lab", "reason": None})
    assert len(calls) == 1 and both == {"runs": True, "spend": True}
    ops_core._caps_in_use([], {"value": None, "source": None, "reason": "no key"})
    assert len(calls) == 2


def test_lab_run_skill_hands_the_spend_limit_to_the_adapter_to_the_cent_and_refuses_a_nonsense_one(tree, tmp_path, monkeypatch):
    kit, got, real = lab.load(), [], lab.load().run_failure

    def run_failure(*args, **kwargs):
        got.append(args[7] if len(args) > 7 else kwargs.get("max_cost"))
        return real(*args, **kwargs)

    monkeypatch.setattr(kit, "run_failure", run_failure)
    for index, limit in enumerate((0.2, None)):
        with lab.session():
            lab.run_skill("demo-writes", "write it.", [], str(tmp_path / f"run-{index}"), max_cost=limit)
    assert got == ["0.20", None], "--max-cost-usd gets a decimal number of dollars; no limit, no flag"
    for bad in (0, -1, True, "0.2"):
        with pytest.raises(lab.LabError) as refused:
            lab.run_skill("demo-writes", "write it.", [], str(tmp_path / "bad"), max_cost=bad)
        assert refused.value.kind == "config" and "max_cost" in refused.value.reason
