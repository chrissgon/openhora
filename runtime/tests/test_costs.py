"""Tests of runtime/costs.py: the cost of a run recomputed from the token counts the adapter left in its folder and the
prices of the one price table (runtime/prices.json, here a table of invented prices). Run folders are built by hand in the form the adapters leave
(outputs/raw.json for the reference adapter, outputs/stream.jsonl for the floor adapter). Offline; invented model ids.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_costs.py
"""
from __future__ import annotations

import json
import os
import time

import pytest

import standin_tree as st

costs = st.load("costs")

PRICE = {"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0, "cache_read_usd_per_mtok": 0.3,
         "cache_write_usd_per_mtok": 3.75, "source": "https://prices.example/models", "accessed": "2026-10-01"}
CHEAP = dict(PRICE, input_usd_per_mtok=1.0, output_usd_per_mtok=2.0, cache_read_usd_per_mtok=0.1,
             cache_write_usd_per_mtok=1.25)
USAGE = {"input_tokens": 1000, "output_tokens": 2000, "cache_read_input_tokens": 100000, "cache_creation_input_tokens": 4000}
# By hand: 1000*3 + 2000*15 + 100000*0.3 + 4000*3.75 = 3000 + 30000 + 30000 + 15000 = 78000 per million = 0.078
HAND = 0.078


def table(**by_model) -> dict:
    """The price table of the tests: {"models": {id: entry}}."""
    return {"models": by_model}


@pytest.fixture
def utc(monkeypatch):
    """The local day is the system's: pin it, so that a run at noon UTC is on the same day everywhere."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def reference_run(folder, usage=USAGE, as_list=False) -> str:
    """A run folder as the reference adapter leaves it: outputs/raw.json is the CLI's result event."""
    event = {"type": "result", "subtype": "success", "result": "the reply", "usage": usage, "total_cost_usd": None}
    (folder / "outputs").mkdir(parents=True)
    body = [{"type": "system"}, event] if as_list else event
    (folder / "outputs" / "raw.json").write_text(json.dumps(body), encoding="utf-8")
    return str(folder)


def floor_run(folder, steps) -> str:
    """A run folder as the floor adapter leaves it: outputs/stream.jsonl has one step_finish event per step."""
    (folder / "outputs").mkdir(parents=True)
    lines = [json.dumps({"type": "text", "part": {"text": "hello"}})]
    for tokens in steps:
        lines.append(json.dumps({"type": "step_finish", "part": {"type": "step-finish", "tokens": tokens, "cost": 0.001}}))
    (folder / "outputs" / "stream.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(folder)


def run(path, model="model-alpha", adapter="adapter-a", agent="business", started="2026-10-05T12:00:00.000000Z",
        cost=None, tokens=None) -> dict:
    return {"model": model, "adapter": adapter, "agent": agent, "started_at": started, "cost_usd": cost, "tokens": tokens,
            "run_dir": path}


def test_a_cost_is_recomputed_from_token_counts_and_prices_by_arithmetic_only(tmp_path):
    reference = reference_run(tmp_path / "reference")
    usage = costs.usage_of(reference)
    assert usage == {"input": 1000, "output": 2000, "cache_read": 100000, "cache_write": 4000}
    assert costs.recompute(usage, PRICE) == pytest.approx(HAND)
    # Each kind is its tokens times its own price per million, and nothing else is added.
    for kind, name in (("input", "input_usd_per_mtok"), ("output", "output_usd_per_mtok"),
                       ("cache_read", "cache_read_usd_per_mtok"), ("cache_write", "cache_write_usd_per_mtok")):
        only = {k: 0 for k in costs.KINDS}
        only[kind] = 1_000_000
        assert costs.recompute(only, PRICE) == pytest.approx(PRICE[name])
    # The result event inside a list of events is the one that is read, and a cache count the event leaves out is 0.
    assert costs.usage_of(reference_run(tmp_path / "listed", as_list=True)) == usage
    bare = {"input_tokens": 10, "output_tokens": 20}
    assert costs.usage_of(reference_run(tmp_path / "bare", bare)) == {"input": 10, "output": 20, "cache_read": 0, "cache_write": 0}
    # The floor adapter's stream: the tokens of each step_finish event, summed.
    steps = [{"input": 100, "output": 10, "reasoning": 0, "cache": {"read": 50, "write": 5}},
             {"input": 200, "output": 20, "reasoning": 0, "cache": {"read": 0, "write": 0}}]
    streamed = costs.usage_of(floor_run(tmp_path / "floor", steps))
    assert streamed == {"input": 300, "output": 30, "cache_read": 50, "cache_write": 5}
    assert costs.recompute(streamed, CHEAP) == pytest.approx((300 * 1.0 + 30 * 2.0 + 50 * 0.1 + 5 * 1.25) / 1_000_000)


def test_a_run_without_usage_or_a_model_without_a_price_has_no_recomputed_cost(tmp_path, utc):
    assert costs.usage_of(str(tmp_path / "missing")) is None
    assert costs.usage_of(None) is None and costs.usage_of("relative/path") is None
    (tmp_path / "empty").mkdir()
    assert costs.usage_of(str(tmp_path / "empty")) is None  # neither file
    # What is not the recorded form is unknown, never a guess.
    for n, bad in enumerate(({"input_tokens": 1}, {"input_tokens": -1, "output_tokens": 2}, {"input_tokens": True, "output_tokens": 2},
                             {"input_tokens": 1.5, "output_tokens": 2}, {"input_tokens": "1", "output_tokens": 2},
                             {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": None}, "x", None)):
        assert costs.usage_of(reference_run(tmp_path / f"bad{n}", bad)) is None, bad
    notjson = tmp_path / "notjson"
    (notjson / "outputs").mkdir(parents=True)
    (notjson / "outputs" / "raw.json").write_text("the raw stream text, not a result event", encoding="utf-8")
    (notjson / "outputs" / "stream.jsonl").write_text(json.dumps(
        {"type": "step_finish", "part": {"tokens": {"input": 1, "output": 1}}}) + "\n", encoding="utf-8")
    assert costs.usage_of(str(notjson)) is None  # an unreadable raw.json is unknown; the stream is not asked in its place
    # A step without counts, a reasoning count (no kind of its own, so it would be priced short), a link: unknown.
    assert costs.usage_of(floor_run(tmp_path / "nostep", [{}])) is None
    assert costs.usage_of(floor_run(tmp_path / "thinks", [{"input": 1, "output": 1, "reasoning": 7}])) is None
    linked = tmp_path / "linked"
    (linked / "outputs").mkdir(parents=True)
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"usage": USAGE}), encoding="utf-8")
    os.symlink(real, linked / "outputs" / "raw.json")
    assert costs.usage_of(str(linked)) is None
    # In a summary: a group with a run of unknown usage has no recomputed cost and counts the run; so has a model
    # with no price, whatever its runs hold.
    known = reference_run(tmp_path / "known")
    rows = costs.summary([run(known, cost=None, tokens=10), run(str(tmp_path / "empty"), tokens=5)], table(**{"model-alpha": PRICE}))
    assert len(rows) == 1 and rows[0]["recomputed_usd"] is None and rows[0]["unknown_runs"] == 1 and rows[0]["runs"] == 2
    rows = costs.summary([run(known, model="model-gamma")], table(**{"model-alpha": PRICE}))
    assert rows[0]["recomputed_usd"] is None and rows[0]["unknown_runs"] == 0 and rows[0]["price"] is None
    rows = costs.summary([run(known)], table(**{"model-alpha": PRICE}), today="2026-10-15")
    assert rows[0]["recomputed_usd"] == pytest.approx(HAND) and rows[0]["unknown_runs"] == 0
    assert rows[0]["price"] == {"source": PRICE["source"], "accessed": PRICE["accessed"], "age_days": 14, "stale": False}
    stale = costs.summary([run(known)], table(**{"model-alpha": PRICE}), today="2026-10-15", max_days=7)
    assert stale[0]["price"]["stale"] is True, "a price older than the project's price_max_age_days is shown as stale"
    # a price that lacks a kind the run used is unknown for that run, never a guess; a model is also found by an alias
    no_cache = {k: v for k, v in PRICE.items() if not k.startswith("cache")}
    assert costs.summary([run(known)], table(**{"model-alpha": no_cache}))[0]["recomputed_usd"] is None
    aliased = costs.summary([run(known, model="alias-alpha")], table(**{"model-alpha": dict(PRICE, aliases=["alias-alpha"])}))
    assert aliased[0]["recomputed_usd"] == pytest.approx(HAND)
    named = costs.summary([run(known, model="other")], table(**{"model-alpha": PRICE}), names_of=lambda model: ["model-alpha"])
    assert named[0]["recomputed_usd"] == pytest.approx(HAND)


def test_the_summary_groups_by_day_agent_model_and_adapter(tmp_path, utc):
    a = reference_run(tmp_path / "a")
    b = reference_run(tmp_path / "b", {"input_tokens": 1_000_000, "output_tokens": 0})
    c = floor_run(tmp_path / "c", [{"input": 1_000_000, "output": 1_000_000, "cache": {"read": 0, "write": 0}}])
    runs = [run(a, started="2026-10-05T09:00:00.000000Z", cost=None, tokens=107000),
            run(b, started="2026-10-05T15:30:00.000000Z", cost=None, tokens=1000000),   # same day, agent, model, adapter
            run(c, model="model-beta", adapter="adapter-b", started="2026-10-05T10:00:00.000000Z", cost=0.25, tokens=2000000),
            run(a, agent="design", started="2026-10-05T11:00:00.000000Z", tokens=107000),  # another agent
            run(a, started="2026-10-06T11:00:00.000000Z", tokens=107000),                  # another day
            run(a, model="model-beta", adapter="adapter-a", started="2026-10-06T12:00:00.000000Z", cost=0.5),
            run(b, agent=None, started="2026-10-06T13:00:00.000000Z")]                     # a run with no agent
    prices = table(**{"model-alpha": PRICE, "model-beta": CHEAP})
    rows = costs.summary(runs, prices)
    keys = [(r["day"], r["agent"], r["model"], r["adapter"], r["runs"]) for r in rows]
    assert keys == [("2026-10-05", "business", "model-alpha", "adapter-a", 2),
                    ("2026-10-05", "business", "model-beta", "adapter-b", 1),
                    ("2026-10-05", "design", "model-alpha", "adapter-a", 1),
                    ("2026-10-06", None, "model-alpha", "adapter-a", 1),
                    ("2026-10-06", "business", "model-alpha", "adapter-a", 1),
                    ("2026-10-06", "business", "model-beta", "adapter-a", 1)]
    first, second = rows[0], rows[1]
    assert first["tokens"] == 1107000 and first["recorded_usd"] is None  # every recorded cost is NULL
    assert first["recomputed_usd"] == pytest.approx(HAND + 3.0)           # the two runs' costs, summed
    assert second["recorded_usd"] == 0.25 and second["tokens"] == 2000000
    assert second["recomputed_usd"] == pytest.approx(3.0)                 # (1e6 * 1.0 + 1e6 * 2.0) per million
    assert rows[5]["tokens"] is None and rows[5]["recorded_usd"] == 0.5 and rows[5]["unknown_runs"] == 0
    assert rows[5]["recomputed_usd"] == pytest.approx(0.02)               # 1000*1 + 2000*2 + 100000*0.1 + 4000*1.25
    assert rows[3]["agent"] is None and rows[3]["recomputed_usd"] == pytest.approx(3.0)
    # since leaves the earlier days out; a day is the local calendar day.
    later = costs.summary(runs, prices, since="2026-10-06")
    assert {r["day"] for r in later} == {"2026-10-06"} and len(later) == 3
    assert costs.summary([], prices) == []


def test_the_first_comment_above_the_first_function_says_when_the_recomputation_leaves():
    text = open(os.path.join(st.RUNTIME, "costs.py"), encoding="utf-8").read()
    head = text[:text.index("def usage_of")].rstrip().splitlines()
    comment = []
    for line in reversed(head):
        if not line.startswith("#"):
            break
        comment.insert(0, line)
    assert comment and comment[0].startswith("# T23:") and "change of the lab default list or of the grader" in " ".join(comment)
    assert "def " not in text[:text.index("def usage_of")]  # it is above the first function of the file


# --- the key proxy's count (package P2b): the run could not change it, so the run's own report is never read in its place ---


def metered_run(folder, meter, own=USAGE):
    """A run folder with the reference adapter's own report AND the key proxy's meter beside it."""
    reference_run(folder, own)
    (folder / "outputs" / "meter.json").write_text(json.dumps(meter), encoding="utf-8")
    return str(folder)


def meter(input=10, output=20, cache_read=30, cache_write=40, unknown=0):
    return {"input": input, "output": output, "cache_read": cache_read, "cache_write": cache_write, "total": input + output + cache_read + cache_write,
            "responses": 3, "unknown_responses": unknown}


def test_a_run_with_a_meter_is_counted_from_it_and_never_from_what_the_run_reports(tmp_path):
    run = metered_run(tmp_path / "run", meter())
    assert costs.metered_usage(run) == {"input": 10, "output": 20, "cache_read": 30, "cache_write": 40, "unknown_responses": 0}
    assert costs.usage_of(run)["input"] == 10 and costs.usage_of(run)["cache_read"] == 30  # not the 1000 and 100000 of raw.json
    assert costs.recompute(costs.usage_of(run), PRICE) == pytest.approx((10 * 3 + 20 * 15 + 30 * 0.3 + 40 * 3.75) / 1e6)


def test_a_run_without_a_meter_is_read_from_its_own_output_as_before(tmp_path):
    run = reference_run(tmp_path / "run")
    assert costs.metered_usage(run) is None and costs.usage_of(run)["input"] == 1000


def test_a_meter_that_could_not_count_every_answer_is_a_lower_bound_flagged_and_never_replaced_by_the_run_s_report(tmp_path):
    run = metered_run(tmp_path / "run", meter(unknown=2))
    found = costs.usage_of(run)
    assert found["unknown_responses"] == 2 and found["input"] == 10 and found["output"] == 20  # what was counted, not 1000
    for broken in ("{", json.dumps([1]), json.dumps({"input": "many"}), json.dumps({**meter(), "output": -1})):
        run = metered_run(tmp_path / f"b{len(broken)}", meter())
        (tmp_path / f"b{len(broken)}" / "outputs" / "meter.json").write_text(broken)
        found = costs.usage_of(run)
        assert found["unknown_responses"] == 1 and found["input"] == 0 and found["output"] == 0  # a meter that exists: no fallback


def test_the_attempts_a_run_set_aside_are_in_the_count_and_one_without_a_meter_is_flagged(tmp_path):
    run = metered_run(tmp_path / "run", meter())
    for name, content in (("failed-1", meter(1, 2, 3, 4)), ("early-end-1", None), ("paused-1", meter(5, 5, 5, 5))):
        (tmp_path / "run" / name / "outputs").mkdir(parents=True)
        if content:
            (tmp_path / "run" / name / "outputs" / "meter.json").write_text(json.dumps(content))
    found = costs.metered_usage(run)
    assert (found["input"], found["output"], found["cache_read"], found["cache_write"]) == (16, 27, 38, 49)
    assert found["unknown_responses"] == 1  # the attempt with no meter spent something that is not in the counts


def test_the_summary_counts_the_runs_that_are_a_lower_bound(tmp_path, utc):
    whole = metered_run(tmp_path / "a", meter())
    partial = metered_run(tmp_path / "b", meter(unknown=1))
    rows = costs.summary([{"started_at": "2026-10-01T12:00:00Z", "agent": "x", "model": "m", "adapter": "h", "cost_usd": None,
                           "tokens": None, "run_dir": whole},
                          {"started_at": "2026-10-01T13:00:00Z", "agent": "x", "model": "m", "adapter": "h", "cost_usd": None,
                           "tokens": None, "run_dir": partial}], table(m=PRICE))
    assert len(rows) == 1 and rows[0]["lower_bound_runs"] == 1 and rows[0]["unknown_runs"] == 0
    assert rows[0]["recomputed_usd"] == pytest.approx(2 * (10 * 3 + 20 * 15 + 30 * 0.3 + 40 * 3.75) / 1e6, abs=1e-6)


def test_a_meter_that_still_had_a_request_under_way_or_could_not_be_written_is_a_lower_bound_flagged(tmp_path):
    for name, extra, flagged in (("whole", {"in_flight": 0}, 0), ("under_way", {"in_flight": 2}, 1), ("failed", {"failed": True}, 1),
                                 ("both", {"in_flight": 1, "failed": True}, 1), ("said_too", {"in_flight": 1, "unknown_responses": 2}, 3)):
        run = metered_run(tmp_path / name, {**meter(), **extra})
        found = costs.usage_of(run)
        assert (found["unknown_responses"] > 0) == bool(flagged), (name, found)
        assert found["input"] == 10 and found["output"] == 20  # what was counted, never the run's 1000
    assert costs.usage_of(str(tmp_path / "said_too"))["unknown_responses"] == 3


def test_an_attempt_set_aside_with_a_request_under_way_flags_the_run(tmp_path, utc):
    run = metered_run(tmp_path / "run", meter())
    (tmp_path / "run" / "failed-1" / "outputs").mkdir(parents=True)
    (tmp_path / "run" / "failed-1" / "outputs" / "meter.json").write_text(json.dumps({**meter(1, 2, 3, 4), "in_flight": 1}))
    found = costs.metered_usage(run)
    assert found["unknown_responses"] == 1 and found["input"] == 11
    rows = costs.summary([{"started_at": "2026-10-01T12:00:00Z", "agent": "x", "model": "m", "adapter": "h", "cost_usd": None,
                           "tokens": None, "run_dir": run}], table(m=PRICE))
    assert rows[0]["lower_bound_runs"] == 1
