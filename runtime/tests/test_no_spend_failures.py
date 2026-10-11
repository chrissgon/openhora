"""Tests of R4-C7 (A-57, P-19): a run whose stored failure proves that no model was called reserves nothing, and is no
run for the runs cap; a run that may have spent keeps its per-run reservation. One rule, autonomy.spend_split, fed by
one definition of the words (autonomy.NO_SPEND_FAILURES); the rows it reads carry `attempts`, so a pre-start refusal
recorded as `internal` is told from a crash after the adapter started. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_no_spend_failures.py
"""
from __future__ import annotations

import datetime

import pytest

import standin_tree as st
from test_read_ops import tree  # noqa: F401  (business, engineering and design agents)

autonomy = st.load("autonomy")
ops = st.load("ops")
ops_core = st.load("ops_core")
operations = st.load("operations")
lab = st.load("lab")
store_module = None

PER_RUN = 1.5


def run(failure=None, attempts=1, cost=None, billing="metered", agent="planning", status=None, tokens=None):
    return {"agent": agent, "billing": billing, "cost_usd": cost, "failure": failure, "attempts": attempts,
            "tokens": tokens, "status": status or ("failed" if failure else "ok")}


def split(*runs, billing_of=None):
    return autonomy.spend_split(list(runs), "planning", PER_RUN)


# --- the words: each failure word the store knows is decided once ---------------------------------------------------


def store_failures():
    import importlib.util
    spec = importlib.util.spec_from_file_location("wb_store_c7", str(st.REPO / "providers" / "store" / "sqlite.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RUN_FAILURES


# What may have spent, by word, and where the word is set (the reason each keeps its reservation).
MAY_HAVE_SPENT = {
    "timeout": "evals/run_attempts.py classify: the adapter ran and ran out of time",
    "refused": "classify: the provider declined the request (content refusal): the request reached the model's provider",
    "adapter": "classify: the adapter failed after it started; the provider may have billed a call",
    "early_end": "classify: the model answered and ended its turn early",
    "stopped": "providers/store/sqlite.py task_fail_running (a restart) and lab.run_skill (the lab was stopped): mid-run",
}
NO_SPEND = {
    "auth": "classify: the provider refused the key or the credential (a 401), before any model answered",
    "settings": "evals/run_attempts.py: the copy carries a tool's settings; refused before the adapter is called",
}


def test_every_failure_word_of_the_store_is_decided_here_and_in_autonomy():
    words = set(store_failures())
    assert set(autonomy.NO_SPEND_FAILURES) == set(NO_SPEND)
    assert set(NO_SPEND) | set(MAY_HAVE_SPENT) | {"internal"} == words  # a new word forces a decision in this file


@pytest.mark.parametrize("word", sorted(NO_SPEND))
def test_a_run_that_failed_before_the_model_reserves_nothing_and_is_no_run_for_the_cap(word):
    got = split(run(word), run("timeout"))  # a metered pair: the proven one reserves nothing, the other keeps its reservation
    assert got == {"usd_recorded": 0.0, "usd_reserved": PER_RUN, "runs_total": 2, "runs_counted": 0, "runs_without_cost": 1}
    subscription = split(run(word, billing="subscription"), run("timeout", billing="subscription"))
    assert subscription["runs_counted"] == 1 and subscription["runs_total"] == 2   # the runs cap counts the one that ran
    free = split(run(word, billing="free"))
    assert free["runs_counted"] == 0 and free["runs_total"] == 1


@pytest.mark.parametrize("word", sorted(MAY_HAVE_SPENT))
def test_a_run_that_may_have_spent_keeps_its_reservation_and_its_place_in_the_cap(word):
    assert split(run(word)) == {"usd_recorded": 0.0, "usd_reserved": PER_RUN, "runs_total": 1, "runs_counted": 0,
                                "runs_without_cost": 1}
    assert split(run(word, billing="subscription"))["runs_counted"] == 1
    assert split(run(word, billing="unknown"))["usd_reserved"] == PER_RUN   # a billing nobody knows is metered


@pytest.mark.parametrize("word", sorted(NO_SPEND))
def test_a_refusal_after_an_earlier_attempt_keeps_its_reservation(word):
    """With retries, attempt 1 may have timed out after spending and attempt 2 meet the 401: attempts says so (review of #319)."""
    for attempts in (2, 3):
        assert split(run(word, attempts=attempts))["usd_reserved"] == PER_RUN, (word, attempts)
        assert split(run(word, attempts=attempts, billing="subscription"))["runs_counted"] == 1
    for attempts in (0, None):   # an auth refusal with no attempt, or an unknown count, proves nothing either
        assert split(run(word, attempts=attempts))["usd_reserved"] == PER_RUN, (word, attempts)


@pytest.mark.parametrize("word", sorted(NO_SPEND) + ["internal"])
def test_a_run_that_reported_tokens_reached_the_model_whatever_its_word(word):
    attempts = 0 if word == "internal" else 1
    assert split(run(word, attempts=attempts, tokens=1200))["usd_reserved"] == PER_RUN
    assert split(run(word, attempts=attempts, tokens=1, billing="subscription"))["runs_counted"] == 1
    assert split(run(word, attempts=attempts, tokens=0))["usd_reserved"] == 0.0      # 0 and none are the same: nothing reported
    assert split(run(word, attempts=attempts, tokens=None))["usd_reserved"] == 0.0


def test_internal_is_no_spend_only_when_no_attempt_began():
    """`internal` is where the runtime records a refusal before the adapter (the image missing, no secret, a bad
    configuration, a copy that could not be built) and also a crash mid-run: attempts tells them apart."""
    assert split(run("internal", attempts=0))["usd_reserved"] == 0.0
    assert split(run("internal", attempts=0, billing="subscription"))["runs_counted"] == 0
    for attempts in (1, 2, None):
        assert split(run("internal", attempts=attempts))["usd_reserved"] == PER_RUN, attempts
    assert split(run("internal", attempts=0, tokens=50))["usd_reserved"] == PER_RUN
    assert split({"agent": "planning", "billing": "metered", "cost_usd": None, "failure": "internal"})["usd_reserved"] == PER_RUN


def test_a_row_that_says_nothing_of_its_failure_keeps_the_old_rule():
    assert split({"agent": "planning", "billing": "metered", "cost_usd": None})["usd_reserved"] == PER_RUN
    assert split(run(None))["usd_reserved"] == PER_RUN   # a run that did not fail and has no cost yet (still running)


def test_a_recorded_cost_is_always_counted_whatever_the_failure():
    got = split(run("auth", cost=0.25), run("internal", attempts=0, cost=0.5), run("stopped", cost=0.125))
    assert got["usd_recorded"] == 0.875 and got["usd_reserved"] == 0.0 and got["runs_without_cost"] == 0
    assert split(run("timeout", cost=0.25)) == {"usd_recorded": 0.25, "usd_reserved": 0.0, "runs_total": 1,
                                                "runs_counted": 0, "runs_without_cost": 0}


def test_the_maintainer_s_day_two_refused_keys_and_two_restarts():
    """A-57: four router runs without a cost reserved $1.50 each; the two that failed on the key's 401 reserve nothing now,
    the two a restart stopped keep theirs."""
    got = split(run("auth"), run("auth"), run("stopped"), run("stopped"), run(None, cost=0.09))
    assert got["usd_reserved"] == 2 * PER_RUN and got["usd_recorded"] == 0.09 and got["runs_total"] == 5
    spent = autonomy.spend([run("auth"), run("auth"), run("stopped"), run("stopped"), run(None, cost=0.09)], "planning", PER_RUN)
    assert spent["usd_metered"] == pytest.approx(3.09) and spent["runs_without_cost"] == 2


def test_the_cap_check_reads_the_new_figure():
    entry = {"max_usd_per_day": 2.0, "max_runs_per_day": 1}
    spent = autonomy.spend([run("auth"), run("auth")], "planning", PER_RUN)
    assert spent["usd_metered"] == 0.0
    assert autonomy.run_budget(entry, spent, PER_RUN) == 1.5   # the agent is not locked out by two refused keys


# --- the rows the rule reads -----------------------------------------------------------------------------------------


def seed(tree, rows):
    """Runs of today for the business agent's task, as stored: (failure, attempts, cost, billing)."""
    from test_read_ops import planned
    path = str(tree["project"])
    planned(tree, "single")
    ctx = ops_core.context(path)
    task = next(t for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] is not None)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for failure, attempts, cost, billing in rows:
        ctx["conn"].execute(
            "INSERT INTO task_runs (task_id, skill, model, adapter, status, failure, attempts, started_at, cost_usd, billing) "
            "VALUES (?, ?, 'fm', 'h', ?, ?, ?, ?, ?, ?)",
            (task["id"], task["skill"], "failed" if failure else "ok", failure, attempts, now, cost, billing))
    ctx["conn"].commit()
    return path


def test_the_stored_rows_of_the_day_carry_attempts_and_failure(tree):
    path = seed(tree, [("auth", 1, None, "metered"), ("internal", 0, None, "metered")])
    ctx = ops_core.context(path)
    rows = ctx["store"].runs_since(ctx["conn"], "2000-01-01T00:00:00Z")
    assert [(r["failure"], r["attempts"]) for r in rows] == [("auth", 1), ("internal", 0)]
    assert all("tokens" in r for r in rows)


def test_the_agent_tab_meters_and_the_cost_caps_read_the_new_figures(tree):
    """The Agent tab's meters and the KPI cards read `agents`/`costs`: two refused keys and a pre-start refusal are in the
    total of runs and in no dollar; a timeout and a restart keep theirs."""
    path = seed(tree, [("auth", 1, None, "metered"), ("auth", 1, None, "metered"), ("internal", 0, None, "metered"),
                       ("timeout", 1, None, "metered"), ("stopped", 1, None, "metered"), (None, 1, 0.4, "metered")])
    first = ops.agents(path)["agents"][0]
    assert first["runs_total_today"] == 6
    assert first["usd_recorded"] == pytest.approx(0.4) and first["usd_reserved"] == pytest.approx(2 * ops.PER_RUN_USD)
    assert first["usd_today"] == pytest.approx(first["usd_recorded"] + first["usd_reserved"])
    assert first["runs_without_cost"] == 2
    caps = {c["agent"]: c for c in ops.costs(path)["caps"]}[first["name"]]
    for key in ("usd_today", "usd_recorded", "usd_reserved", "runs_without_cost", "runs_total_today", "runs_today"):
        assert caps[key] == first[key], key


def test_a_subscription_agent_is_not_held_by_runs_that_never_reached_the_model(tree):
    path = seed(tree, [("auth", 1, None, "subscription"), ("auth", 1, None, "subscription"), ("stopped", 1, None, "subscription")])
    first = ops.agents(path)["agents"][0]
    assert first["runs_total_today"] == 3 and first["runs_today"] == 1 and first["usd_today"] == 0.0


# --- what the runtime records: attempts tells a refusal before the adapter from a crash after it ----------------------


def request_ready(tree):
    path = str(tree["project"])
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    ops.request(path, "Invented request.", "demo", title="Invented")
    return path


def last_run(tree):
    ctx = ops_core.context(str(tree["project"]))
    return dict(ctx["conn"].execute("SELECT failure, attempts, status FROM task_runs ORDER BY id DESC LIMIT 1").fetchone())


def test_a_refused_key_is_recorded_with_its_attempt_and_the_split_reserves_nothing(tree):
    path = request_ready(tree)
    st.fail(tree["adapter"], "auth", 1)
    out = ops.run_next(path)
    assert out["failure"]["kind"] == "auth"
    row = last_run(tree)
    assert row == {"failure": "auth", "attempts": 1, "status": "failed"}
    ctx = ops_core.context(path)
    runs = ctx["store"].runs_since(ctx["conn"], "2000-01-01T00:00:00Z")
    assert autonomy.spend_split([dict(r, billing="metered") for r in runs], runs[0]["agent"], PER_RUN)["usd_reserved"] == 0.0


def test_a_refusal_before_the_adapter_is_recorded_with_no_attempt(tree, monkeypatch):
    path = request_ready(tree)

    def refuse(*args, **kwargs):
        raise lab.LabError("container", "the eval image of this checkout is not on this machine")

    monkeypatch.setattr(lab, "run_skill", refuse)
    out = ops.run_next(path)
    assert out["failure"]["kind"] == "internal" and "image" in out["failure"]["reason"]
    assert last_run(tree) == {"failure": "internal", "attempts": 0, "status": "failed"}


def test_a_crash_after_an_attempt_began_is_recorded_with_its_attempts_and_keeps_its_reservation(tree, monkeypatch):
    path = request_ready(tree)

    def crash(*args, **kwargs):
        error = RuntimeError("the runner died")
        error.attempts = 2
        raise error

    monkeypatch.setattr(lab, "run_skill", crash)
    ops.run_next(path)
    assert last_run(tree) == {"failure": "internal", "attempts": 2, "status": "failed"}
    ctx = ops_core.context(path)
    runs = ctx["store"].runs_since(ctx["conn"], "2000-01-01T00:00:00Z")
    assert autonomy.spend_split([dict(r, billing="metered") for r in runs], runs[0]["agent"], PER_RUN)["usd_reserved"] == PER_RUN


def test_the_lab_names_how_many_attempts_began_on_an_exception_that_leaves_it(tree, tmp_path):
    def boom(copy, root):
        raise RuntimeError("the copy cannot be prepared")

    with lab.session(), pytest.raises(lab.LabError) as raised:
        lab.run_skill("demo-asks", "go\n", [], str(tmp_path / "data" / "run-c7"), prepare=boom)
    assert raised.value.kind == "copy" and raised.value.attempts == 1   # an attempt began: its reservation is kept


# --- a failed run records what the adapter reported (review of #319) ---------------------------------------------------


def test_a_failed_run_records_the_cost_and_tokens_its_attempts_reported_and_the_split_counts_them(tree, monkeypatch):
    path = request_ready(tree)
    monkeypatch.setattr(ops_core, "_tier_billing", lambda *a, **k: "metered")   # a metered credential: its cost is billed
    st.fail(tree["adapter"], "adapter", 9)   # every attempt fails after the adapter wrote timing.json (100 tokens, $0.01)
    out = ops.run_next(path)
    assert out["failure"]["kind"] == "adapter"
    ctx = ops_core.context(path)
    row = dict(ctx["conn"].execute("SELECT failure, attempts, cost_usd, tokens FROM task_runs ORDER BY id DESC LIMIT 1").fetchone())
    assert row["failure"] == "adapter" and row["attempts"] == 3
    assert row["cost_usd"] == pytest.approx(0.03) and row["tokens"] == 300     # the three attempts, the retried ones included
    runs = ctx["store"].runs_since(ctx["conn"], "2000-01-01T00:00:00Z")
    got = autonomy.spend_split(runs, runs[0]["agent"], PER_RUN)
    assert got["usd_recorded"] == pytest.approx(0.03) and got["usd_reserved"] == 0.0   # the recorded cost replaces the reservation


def test_a_failed_run_on_a_subscription_records_tokens_and_no_cost(tree):
    path = request_ready(tree)
    st.fail(tree["adapter"], "adapter", 9)
    ops.run_next(path)
    ctx = ops_core.context(path)
    row = dict(ctx["conn"].execute("SELECT cost_usd, tokens, billing FROM task_runs ORDER BY id DESC LIMIT 1").fetchone())
    assert row["cost_usd"] is None and row["tokens"] == 300      # only a metered run has a billed cost (as for a run that ended)


def test_a_refused_key_that_reports_no_tokens_is_still_no_spend(tree):
    path = request_ready(tree)
    st.fail(tree["adapter"], "auth", 1)
    ops.run_next(path)
    ctx = ops_core.context(path)
    runs = ctx["store"].runs_since(ctx["conn"], "2000-01-01T00:00:00Z")
    assert (runs[0]["failure"], runs[0]["attempts"], runs[0]["tokens"]) == ("auth", 1, None)
    assert autonomy.never_reached_the_model(runs[0]) is True


# --- every attempt's reported usage counts (R4-C7b) -----------------------------------------------------------------------


def write_timing(folder, tokens=None, cost=None):
    import json
    import os
    os.makedirs(os.path.join(folder, "outputs"), exist_ok=True)
    with open(os.path.join(folder, "outputs", "timing.json"), "w") as f:
        json.dump({"total_tokens": tokens, "cost_usd": cost}, f)


def test_reported_usage_reads_every_attempt_a_paused_one_included(tmp_path):
    """A paused attempt (the account limit) may have spent before it stopped: its timing adds to the run's usage."""
    dest = str(tmp_path / "run")
    write_timing(dest, 100, 0.01)                       # the last attempt
    write_timing(dest + "/failed-1", 100, 0.02)
    write_timing(dest + "/early-end-1", 50, 0.005)
    write_timing(dest + "/paused-1", 70, 0.03)         # stopped on the limit after it spent
    got = lab.reported_usage(dest)
    assert got["total_tokens"] == 320 and got["cost_usd"] == pytest.approx(0.065)
    nothing = lab.reported_usage(str(tmp_path / "none"))
    assert nothing == {"cost_usd": None, "total_tokens": None}
    write_timing(dest + "/paused-2", None, None)       # a file with no number adds nothing
    assert lab.reported_usage(dest)["total_tokens"] == 320


def test_a_run_that_succeeds_after_failed_attempts_records_the_usage_of_every_attempt(tree, monkeypatch):
    path = request_ready(tree)
    monkeypatch.setattr(ops_core, "_tier_billing", lambda *a, **k: "metered")
    st.fail(tree["adapter"], "adapter", 2)      # attempts 1 and 2 fail after reporting (100 tokens, $0.01); attempt 3 answers
    out = ops.run_next(path)
    assert out["status"] == "ok"
    ctx = ops_core.context(path)
    row = dict(ctx["conn"].execute("SELECT status, attempts, cost_usd, tokens FROM task_runs ORDER BY id DESC LIMIT 1").fetchone())
    assert row["status"] == "ok" and row["attempts"] == 3
    assert row["cost_usd"] == pytest.approx(0.03) and row["tokens"] == 300     # not the last attempt's alone


def test_a_run_that_succeeds_at_once_records_its_own_usage_as_before(tree, monkeypatch):
    path = request_ready(tree)
    monkeypatch.setattr(ops_core, "_tier_billing", lambda *a, **k: "metered")
    ops.run_next(path)
    ctx = ops_core.context(path)
    row = dict(ctx["conn"].execute("SELECT attempts, cost_usd, tokens FROM task_runs ORDER BY id DESC LIMIT 1").fetchone())
    assert row["attempts"] == 1 and row["cost_usd"] == pytest.approx(0.01) and row["tokens"] == 100


def test_a_refused_key_that_reported_tokens_keeps_its_reservation_end_to_end(tree):
    """The stand-in's auth case reports usage this time (an adapter that met the 401 after calls): the row keeps tokens and the
    split reserves for it."""
    path = request_ready(tree)
    (tree["adapter"] / "auth-reports-usage").write_text("1\n")
    st.fail(tree["adapter"], "auth", 1)
    ops.run_next(path)
    ctx = ops_core.context(path)
    runs = ctx["store"].runs_since(ctx["conn"], "2000-01-01T00:00:00Z")
    assert (runs[0]["failure"], runs[0]["attempts"], runs[0]["tokens"]) == ("auth", 1, 100)
    assert autonomy.never_reached_the_model(runs[0]) is False
    assert autonomy.spend_split([dict(r, billing="metered") for r in runs], runs[0]["agent"], PER_RUN)["usd_reserved"] == PER_RUN
