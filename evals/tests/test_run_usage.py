"""Offline tests of the usage a run line carries (P2c): where its tokens are read from and what is never read.

The count is the key proxy's when the run went through one; otherwise the `modelUsage` of the run's raw output (it counts
the subagents a run starts) or the `step_finish` tokens of the floor adapter's stream; never the total of timing.json.

Run: uv run --with pytest pytest evals/tests/test_run_usage.py
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "eval_run.py"
_spec = importlib.util.spec_from_file_location("eval_run_for_usage", SCRIPT)
er = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(er)

KINDS = ("input", "output", "cache_read", "cache_write")


def result(model_usage=None, usage=None):
    return json.dumps({"type": "result", "result": "ok", **({"modelUsage": model_usage} if model_usage is not None else {}),
                       **({"usage": usage} if usage is not None else {})})


def raw(tmp_path, text):
    (tmp_path / "raw.json").write_text(text)
    return str(tmp_path)


def step(tokens):
    return json.dumps({"type": "step_finish", "part": {"tokens": tokens}})


def stream(tmp_path, *events):
    (tmp_path / "stream.jsonl").write_text("\n".join(events) + "\n")
    return str(tmp_path)


def test_the_model_usage_of_a_result_event_is_summed_over_the_models_so_subagents_count(tmp_path):
    text = result({"main-model": {"inputTokens": 100, "outputTokens": 20, "cacheReadInputTokens": 3000, "cacheCreationInputTokens": 50, "costUSD": 1.2},
                   "subagent-model": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 200, "cacheCreationInputTokens": 0}},
                  usage={"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 3000, "cache_creation_input_tokens": 50})
    assert er.run_usage(None, raw(tmp_path, text)) == {"input": 110, "output": 25, "cache_read": 3200, "cache_write": 50}
    # A list of events is read at its result event.
    assert er.usage_from_model_usage(json.dumps([{"type": "system"}, json.loads(text)])) == {
        "input": 110, "output": 25, "cache_read": 3200, "cache_write": 50}


def test_a_cache_count_it_leaves_out_is_zero_and_an_input_or_output_it_leaves_out_is_unknown(tmp_path):
    assert er.usage_from_model_usage(result({"m": {"inputTokens": 7, "outputTokens": 3}})) == {
        "input": 7, "output": 3, "cache_read": 0, "cache_write": 0}
    for bad in ({"m": {"outputTokens": 3}}, {"m": {"inputTokens": 7}}, {"m": {"inputTokens": -1, "outputTokens": 3}},
                {"m": {"inputTokens": 1.5, "outputTokens": 3}}, {"m": {"inputTokens": True, "outputTokens": 3}},
                {"m": {"inputTokens": 7, "outputTokens": 3, "cacheReadInputTokens": "9"}}, {"m": "text"}, {}, []):
        assert er.usage_from_model_usage(result(bad)) is None, bad


def test_the_usage_total_of_a_result_event_is_never_read_in_place_of_model_usage(tmp_path):
    # Without modelUsage the subagents are unaccounted for: the `usage` object would understate the run, so it is unknown.
    text = result(usage={"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})
    assert er.run_usage(None, raw(tmp_path, text)) is None
    assert er.usage_from_model_usage("not json") is None and er.usage_from_model_usage("[1, 2]") is None


def test_the_floor_adapters_stream_is_summed_over_its_step_finish_events(tmp_path):
    out = stream(tmp_path, json.dumps({"type": "text"}),
                 step({"input": 100, "output": 10, "reasoning": 0, "cache": {"read": 500, "write": 20}}),
                 step({"input": 40, "output": 5, "cache": {"read": 700, "write": 0}}), "not json")
    assert er.run_usage(None, out) == {"input": 140, "output": 15, "cache_read": 1200, "cache_write": 20}


def test_a_stream_with_reasoning_tokens_or_a_bad_count_or_no_step_is_unknown(tmp_path):
    assert er.run_usage(None, stream(tmp_path, step({"input": 1, "output": 1, "reasoning": 9, "cache": {}}))) is None
    assert er.run_usage(None, stream(tmp_path, step({"input": 1, "output": -1}))) is None
    assert er.run_usage(None, stream(tmp_path, step({"input": 1}))) is None
    assert er.run_usage(None, stream(tmp_path, json.dumps({"type": "text"}))) is None
    assert er.run_usage(None, str(tmp_path / "nowhere")) is None


def test_the_key_proxys_count_is_the_count_and_the_runs_own_report_is_not_read_beside_it(tmp_path):
    meter = {"input": 5, "output": 6, "cache_read": 7, "cache_write": 8, "total": 26, "responses": 3, "unknown_responses": 0,
             "budget_reached": False, "in_flight": 0}
    lying = result({"m": {"inputTokens": 999999, "outputTokens": 999999}})
    assert er.run_usage(meter, raw(tmp_path, lying)) == {"input": 5, "output": 6, "cache_read": 7, "cache_write": 8}
    # A count that names answers it could not read is a lower bound: a line cannot say so, so it has no usage, and
    # the run's own report (which the run could have written) is not asked in its place.
    assert er.run_usage({**meter, "unknown_responses": 1}, raw(tmp_path, lying)) is None
    assert er.run_usage({k: v for k, v in meter.items() if k != "cache_write"}, str(tmp_path)) is None
    assert er.run_usage({**meter, "input": -1}, str(tmp_path)) is None


def test_a_raw_file_that_cannot_be_read_is_unknown_and_the_stream_is_not_asked_in_its_place(tmp_path):
    (tmp_path / "raw.json").write_text("x" * (er.RAW_JSON_LIMIT + 1))
    stream(tmp_path, step({"input": 1, "output": 1, "cache": {}}))
    assert er.run_usage(None, str(tmp_path)) is None


def test_a_linked_file_is_not_read(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "real.json").write_text(result({"m": {"inputTokens": 1, "outputTokens": 1}}))
    run = tmp_path / "run"
    run.mkdir()
    os.symlink(outside / "real.json", run / "raw.json")
    assert er.run_usage(None, str(run)) is None
