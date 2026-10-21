"""The command line of the measurement harness (package IX-2c; runtime/interpreter_measure.py): the guards of the held-out test split, the sample, the sequential event, the local
aggregates, what is and is not printed, and the run that is stopped by a fault. The model is the echo route of test_interpreter_echo.py put in place of
`interpreter_route.complete`; the split file and the checkout's root are replaced by files and folders of the test, so that no real held-out file, key or route is touched.
The oracle is this file's own list of fictional lines and markers, the calls the echo counted, and IX-E's validator (evals/evidence_lines.py, loaded by path).
Offline: no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_measure_cli.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_interpreter_echo import DEV, EchoRoute, load, sample, unique_items, write_corpus

measure = st.load("interpreter_measure")
pipeline = st.load("interpreter_pipeline")
route_module = st.load("interpreter_route")

ROOT = Path(__file__).resolve().parents[2]
ROUTE = "or-claude-haiku-4.5"
MARKER = "SECRET-MARKER-5527-ZETA"


def by_path(rel, name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


lines_module = by_path("evals/evidence_lines.py", "workbench_evidence_lines_for_ix2c")
CONFIGURED = {"runs": 2, "routes": {r["id"]: r["model"] for r in route_module.load()["routes"]}, "pins": {r["id"]: r["pin"] for r in route_module.load()["routes"]}}

ITEMS = [i for i in unique_items(sample(load(DEV), 80)) if i["gold"].get("scope", "full") == "full"]


def as_split(items, split):
    return [{**i, "id": split + i["id"][3:], "split": split} for i in items]


def as_local(items):
    return [{**i, "id": f"local-{n:05d}", "split": "local"} for n, i in enumerate(items, 1)]


class Cli:
    """A call of the harness in process, with the echo route in place of the real one."""

    def __init__(self, tmp, monkeypatch, capsys, items, split="dev"):
        self.tmp, self.monkeypatch, self.capsys, self.items = tmp, monkeypatch, capsys, items
        self.corpus = tmp / "corpus.jsonl"
        self.body = write_corpus(self.corpus, items)
        self.checkout = tmp / "checkout"
        self.checkout.mkdir()
        self.split_file = tmp / "test-split.json"
        self.split_file.write_text(json.dumps({"v": 1, "file": "corpus.jsonl", "sha256": hashlib.sha256(self.body).hexdigest(), "items": len(items)}), encoding="utf-8")
        monkeypatch.setattr(measure, "ROOT", str(self.checkout))
        monkeypatch.setattr(measure, "SPLIT_FILE", str(self.split_file))
        self.echo = EchoRoute(items)
        monkeypatch.setattr(route_module, "complete", self.echo)
        self.evidence = tmp / "evidence"
        self.answers = tmp / "answers"

    def run(self, *argv, evidence=True):
        extra = ["--evidence-dir", str(self.evidence)] if evidence and "--no-evidence" not in argv and "--replay" not in argv else []
        code = measure.main(["--corpus", str(self.corpus), "--route", ROUTE, *argv, *extra])
        out = self.capsys.readouterr()
        return code, out.out, out.err

    def files(self):
        return sorted(self.evidence.glob("ix-*.jsonl")) if self.evidence.exists() else []

    def problems(self, path):
        return lines_module.interpreter_file_problems(str(path), CONFIGURED)

    def lines(self, path):
        return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def cli(tmp_path, monkeypatch, capsys):
    return Cli(tmp_path, monkeypatch, capsys, ITEMS)


SUMMARY_KEYS = {"items", "runs", "measures", "by_language", "parse_failure_rate", "calls", "p95_latency_ms", "median_cost_usd", "wrong_route_cost_usd", "stages", "observed",
                "errors", "time_disagree", "private_route", "scope_time", "live_calls", "route", "test"}


# --- a dev run --------------------------------------------------------------------------------------------------------------------------------------

def test_a_dev_run_writes_one_valid_file_with_a_line_for_every_item_and_run_and_prints_the_summary(cli):
    code, out, err = cli.run("--json", "--jobs", "3")
    assert code == 0, err
    summary = json.loads(out)
    assert set(summary) == SUMMARY_KEYS and summary["items"] == len(ITEMS) and summary["runs"] == 2 * len(ITEMS) and summary["route"] == ROUTE
    assert set(summary["measures"]) == {"n", "counts", "direct", "rate", "wilson", "correct_direct", "clarify_rate"} and summary["p95_latency_ms"] is None
    (path,) = cli.files()
    assert cli.problems(path) == []
    body = cli.lines(path)
    assert body[0]["split"] == "dev" and body[0]["runs"] == 2 and body[0]["items"] == len(ITEMS) and body[0]["billing"] == "metered" and body[0]["sequential"] is False
    assert len(body) == 1 + 2 * len(ITEMS) and {(l["item"], l["run"]) for l in body[1:]} == {(i["id"], r) for i in ITEMS for r in (1, 2)}
    assert len([l for l in body[1:] if l["latency_ms"] is not None]) == len(cli.echo.calls) and summary["live_calls"] == len(cli.echo.calls)
    assert all(accepted == [route_module.route_sha256(route_module.find(ROUTE))] for accepted in cli.echo.accepted), "every call names the route's hash as the one accepted"


def test_the_text_summary_names_the_categories_and_no_item(cli):
    code, out, err = cli.run()
    assert code == 0 and "categories" in out and "correct_direct" in out and "by language" not in out
    assert not any(i["id"] in out + err for i in ITEMS) and not any(i["line"] in out + err for i in ITEMS)


def test_what_the_model_said_and_the_lines_are_never_printed(cli):
    victim = next(i for i in ITEMS if pipeline.pre_model(i) is None)
    cli.echo.texts[victim["id"]] = MARKER + " " + victim["line"]
    code, out, err = cli.run("--json")
    assert code == 0 and MARKER not in out + err and victim["line"] not in out + err
    assert MARKER not in cli.files()[0].read_text(encoding="utf-8")


def test_a_failed_call_is_an_outage_line_and_the_run_goes_on(cli, monkeypatch):
    monkeypatch.setattr(measure, "OUTAGE_MAX", 0.2)          # the default share is tested below
    victim = next(i for i in ITEMS if pipeline.pre_model(i) is None)
    cli.echo.fail[victim["id"]] = "E_TIMEOUT"
    code, out, err = cli.run("--json")
    assert code == 0
    gone = [l for l in cli.lines(cli.files()[0])[1:] if l["item"] == victim["id"]]
    assert {(l["observed"], l["category"], l["error"]) for l in gone} == {("outage", "missed", "E_TIMEOUT")} and json.loads(out)["errors"] == {"E_TIMEOUT": 2}


def test_a_route_that_cannot_be_called_stops_the_run_at_once_and_writes_nothing(cli):
    cli.monkeypatch.setattr(route_module, "complete", lambda *a, **k: cli.echo.calls.append("x") or {"ok": False, "code": "E_KEY"})
    code, out, err = cli.run("--jobs", "1", "--record", str(cli.answers))
    assert code == 1 and "E_KEY" in err and cli.echo.calls == ["x"], "one call, then no more"
    assert cli.files() == [] and [l for f in cli.answers.glob("*.answers.jsonl") for l in f.read_text().splitlines()[1:]] == [], "a configuration fault is not kept as an answer"


def test_a_route_that_cannot_be_called_makes_no_call_after_the_first_even_with_four_jobs(cli):
    import threading
    import time as _time
    calls, gate = [], threading.Lock()

    def refusing(*a, **k):
        with gate:
            calls.append(1)
        _time.sleep(0.05)
        return {"ok": False, "code": "E_KEY"}
    cli.monkeypatch.setattr(route_module, "complete", refusing)
    code, out, err = cli.run("--jobs", "4", "--record", str(cli.answers))
    assert code == 1 and "E_KEY" in err and len(calls) == 1, "four threads started, one call was made"
    assert "no more calls were made" not in err and cli.files() == []


def test_a_first_call_refused_with_a_client_error_is_a_configuration_fault_and_a_later_one_is_an_outage(cli):
    first = next(i for i in sorted(ITEMS, key=lambda i: i["id"]) if pipeline.pre_model(i) is None)
    cli.echo.fail[first["id"]] = "E_HTTP"          # a revoked key, no credits, forbidden
    code, out, err = cli.run("--jobs", "1", "--no-evidence")
    assert code == 1 and "E_HTTP" in err and cli.echo.calls == [first["id"]]
    cli.echo.calls.clear()
    cli.echo.fail.clear()
    later = [i for i in sorted(ITEMS, key=lambda i: i["id"]) if pipeline.pre_model(i) is None][5]
    cli.echo.fail[later["id"]] = "E_HTTP"
    code, out, err = cli.run("--jobs", "1", "--no-evidence", "--json")
    assert code == 0 and json.loads(out)["errors"] == {"E_HTTP": 2}


def test_outages_over_one_percent_of_the_calls_write_no_evidence_and_the_run_is_resumed(cli):
    victims = [i for i in sorted(ITEMS, key=lambda i: i["id"]) if pipeline.pre_model(i) is None][:2]
    for one in victims:
        cli.echo.fail[one["id"]] = "E_RATE"
    code, out, err = cli.run("--record", str(cli.answers))
    assert code == 1 and "4 of " in err and "E_RATE" in err and "--resume" in err and cli.files() == [], err
    assert not any(i["id"] in err for i in ITEMS)
    cli.echo.fail.clear()
    cli.echo.calls.clear()
    code, out, err = cli.run("--resume", str(cli.answers), "--json")
    assert code == 0, err
    assert sorted(cli.echo.calls) == sorted(i["id"] for i in victims for _ in (1, 2)), "only the failed pairs were called again"
    (path,) = cli.files()
    assert cli.problems(path) == [] and not [l for l in cli.lines(path)[1:] if l["observed"] == "outage"]
    code, out, err = cli.run("--no-evidence")          # without evidence the share is not checked: a pilot may look at its outages
    assert code == 0


def test_an_exception_inside_an_item_prints_its_class_and_ordinal_and_nothing_else(cli):
    real = pipeline.run_item
    ordinal = 5
    victim = sorted(ITEMS, key=lambda i: i["id"])[ordinal - 1]

    def boom(one, run, call):
        if one["id"] == victim["id"]:
            raise KeyError(MARKER + one["line"])
        return real(one, run, call)
    cli.monkeypatch.setattr(pipeline, "run_item", boom)
    code, out, err = cli.run("--jobs", "1")
    assert code == 1 and err.strip() == f"error: KeyError at item #{ordinal}" and out == ""
    assert MARKER not in out + err and cli.files() == []


def test_a_fault_in_a_worker_thread_stops_the_run_and_still_names_only_the_class(cli):
    real = pipeline.run_item
    victim = sorted(ITEMS, key=lambda i: i["id"])[9]

    def boom(one, run, call):
        if one["id"] == victim["id"] and run == 2:
            raise ValueError(MARKER + one["line"])
        return real(one, run, call)
    cli.monkeypatch.setattr(pipeline, "run_item", boom)
    code, out, err = cli.run("--jobs", "4")
    assert code == 1 and err.strip() == "error: ValueError at item #10" and MARKER not in out + err and cli.files() == []


def test_a_corpus_fault_names_the_line_and_the_field_never_the_value(cli):
    lines = cli.corpus.read_text(encoding="utf-8").splitlines()
    broken = json.loads(lines[2])
    broken["line"] = MARKER
    broken["clock"] = "tomorrow-ish " + MARKER
    lines[2] = json.dumps(broken)
    cli.corpus.write_text("\n".join(lines) + "\n", encoding="utf-8")
    code, out, err = cli.run()
    assert code == 1 and MARKER not in out + err and "corpus line 3" in err and "clock" in err
    cli.corpus.write_text(MARKER + "\n", encoding="utf-8")
    code, out, err = cli.run()
    assert code == 1 and MARKER not in out + err and "corpus line 1 is not JSON" in err
    assert cli.echo.calls == []


def test_usage_errors_exit_two_and_refused_inputs_exit_one(cli):
    assert cli.run("--sample", "5")[0] == 2
    assert cli.run("--record", str(cli.answers), "--resume", str(cli.answers))[0] == 2
    assert cli.run("--replay", str(cli.answers), "--evidence-dir", str(cli.evidence), evidence=False)[0] == 2
    assert cli.run("--jobs", "0")[0] == 2
    assert cli.run("--runs", "11")[0] == 2 and cli.run("--runs", "0")[0] == 2, "the validator takes 1 to 10 runs"
    assert cli.run("--local-aggregates", "--sample", "3", "--seed", "1")[0] == 2
    assert measure.main(["--corpus", str(cli.corpus), "--route", "no-such-route"]) == 1
    assert cli.capsys.readouterr().err.strip() == "error: no such route in runtime/interpreter_routes.json"
    assert cli.echo.calls == []
    assert measure.main(["--help"]) == 0 and "--local-aggregates" in cli.capsys.readouterr().out


def test_the_first_live_call_is_made_alone_and_the_rest_may_overlap(cli):
    import threading
    active, seen, gate = [0], [], threading.Lock()
    real = cli.echo

    def watching(*a, **k):
        with gate:
            active[0] += 1
            seen.append(active[0])
        try:
            import time as _time
            _time.sleep(0.005)
            return real(*a, **k)
        finally:
            with gate:
                active[0] -= 1
    cli.monkeypatch.setattr(route_module, "complete", watching)
    code, out, err = cli.run("--jobs", "4", "--no-evidence")
    assert code == 0 and seen[0] == 1 and max(seen) > 1, "the first call ran alone; later ones overlapped"


# --- the held-out test split ---------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def held(tmp_path, monkeypatch, capsys):
    return Cli(tmp_path, monkeypatch, capsys, as_split(ITEMS, "test"))


def test_a_corpus_that_is_not_the_test_split_is_refused_before_any_call(held):
    held.split_file.write_text(json.dumps({"v": 1, "sha256": "0" * 64, "items": len(ITEMS)}), encoding="utf-8")
    code, out, err = held.run("--record", str(held.tmp / "outside"))
    assert code == 1 and "not the test split" in err and held.echo.calls == [] and held.files() == []
    held.split_file.unlink()
    code, out, err = held.run("--record", str(held.tmp / "outside"))
    assert code == 1 and "test-split.json cannot be read" in err and held.echo.calls == []


def test_the_answers_of_the_test_split_may_not_be_kept_inside_the_checkout(held):
    inside = held.checkout / "answers"
    code, out, err = held.run("--record", str(inside))
    assert code == 1 and "inside this checkout" in err and held.echo.calls == [] and not inside.exists()
    link = held.tmp / "link"
    link.symlink_to(held.checkout)
    code, out, err = held.run("--record", str(link / "answers"))
    assert code == 1 and "inside this checkout" in err and held.echo.calls == [], "a link into the checkout is the checkout"
    for mode in ("--resume", "--replay"):
        assert held.run(mode, str(inside), evidence=False)[0] == 1
    assert held.echo.calls == []


def test_the_test_split_needs_a_place_for_its_answers(held):
    code, out, err = held.run()
    assert code == 1 and "needs --record, --resume or --replay" in err and held.echo.calls == []


def test_a_sample_of_the_test_split_is_never_a_band_and_the_runs_are_the_configured_number(held):
    outside = str(held.tmp / "outside")
    code, out, err = held.run("--sample", "5", "--seed", "1", "--record", outside)
    assert code == 1 and "needs --sequential" in err
    code, out, err = held.run("--runs", "1", "--record", outside)
    assert code == 1 and "run 2 times" in err and held.echo.calls == []


def test_the_test_split_runs_whole_and_its_evidence_is_valid_and_states_the_split_files_hash(held):
    outside = held.tmp / "outside"
    code, out, err = held.run("--record", str(outside), "--json")
    assert code == 0, err
    (path,) = held.files()
    assert held.problems(path) == []
    event = held.lines(path)[0]
    assert event["split"] == "test" and event["runs"] == 2 and event["corpus_sha256"] == hashlib.sha256(held.split_file.read_bytes()).hexdigest()
    assert event["items"] == len(ITEMS) and {l["item"] for l in held.lines(path)[1:]} == {i["id"] for i in held.items}
    (kept,) = outside.glob("*.answers.jsonl")
    assert oct(kept.stat().st_mode & 0o777) == "0o600" and kept.name.startswith(event["test"])


# --- the sequential sample ---------------------------------------------------------------------------------------------------------------------------

def test_a_sequential_sample_draws_only_items_that_reach_the_model(cli, monkeypatch):
    monkeypatch.setattr(measure.prices, "load", lambda: {"models": {route_module.find(ROUTE)["model"]: {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 5.0,
                                                                                                           "cache_read_usd_per_mtok": 0.1}}})
    cli.run("--no-evidence")
    reach = set(cli.echo.calls)
    assert reach and len(reach) < len(ITEMS), "the fixture has items decided before the model"
    cli.echo.calls.clear()
    code, out, err = cli.run("--sequential", "--sample", "8", "--seed", "20261026", "--json")
    assert code == 0, err
    (path,) = cli.files()
    body = cli.lines(path)
    ids = {l["item"] for l in body[1:]}
    assert len(ids) == 8 and ids <= reach and body[0]["sequential"] is True and body[0]["items"] == len(ITEMS)
    assert all(l["latency_ms"] is not None for l in body[1:]), "every line of a sequential event is a call"
    assert len(cli.echo.calls) == 16 and cli.problems(path) == []
    assert json.loads(out)["p95_latency_ms"] is not None
    assert [l["cost_usd"] for l in body[1:]] == [pytest.approx(3000 * 1.0 / 1e6 + 40 * 5.0 / 1e6 + 2000 * 0.1 / 1e6)] * 16 and json.loads(out)["median_cost_usd"] == pytest.approx(0.0034)


def test_a_kind_of_token_with_no_price_leaves_the_cost_unknown_and_the_median_null(cli, monkeypatch):
    monkeypatch.setattr(measure.prices, "load", lambda: {"models": {route_module.find(ROUTE)["model"]: {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 5.0}}})
    code, out, err = cli.run("--sequential", "--sample", "4", "--seed", "1", "--json")
    (path,) = cli.files()
    assert code == 0 and all(l["cost_usd"] is None for l in cli.lines(path)[1:]) and json.loads(out)["median_cost_usd"] is None


def test_a_sequential_sample_is_the_same_for_the_same_seed_and_other_for_another(cli):
    def drawn(seed):
        cli.run("--sequential", "--sample", "8", "--seed", seed, "--no-evidence")
        return sorted(set(cli.echo.calls))
    first = drawn("20261026")
    cli.echo.calls.clear()
    again = drawn("20261026")
    cli.echo.calls.clear()
    other = drawn("20261027")
    assert first == again and first != other and len(first) == 8


def test_a_sample_larger_than_the_pool_is_refused(cli):
    code, out, err = cli.run("--sequential", "--sample", "500", "--seed", "1")
    assert code == 1 and "asks for 500 items" in err and cli.echo.calls == []


def test_a_sequential_event_forces_one_job(cli):
    seen = []
    real = measure.concurrent.futures.ThreadPoolExecutor

    class Spy(real):
        def __init__(self, max_workers=None, *a, **k):
            seen.append(max_workers)
            super().__init__(max_workers, *a, **k)
    cli.monkeypatch.setattr(measure.concurrent.futures, "ThreadPoolExecutor", Spy)
    cli.run("--sequential", "--sample", "4", "--seed", "1", "--jobs", "6", "--no-evidence")
    cli.run("--jobs", "6", "--no-evidence")
    assert seen == [1, 6]


# --- the maintainer's own lines ---------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def local(tmp_path, monkeypatch, capsys):
    items = as_local(ITEMS[:30])
    items[3] = {**items[3], "line": items[3]["line"] + " " + MARKER}
    return Cli(tmp_path, monkeypatch, capsys, items)


def test_local_aggregates_print_and_write_counts_only(local):
    code, out, err = local.run("--local-aggregates")
    assert code == 0, err
    (path,) = local.files()
    text = path.read_text(encoding="utf-8")
    for what in (out, err, text):
        assert MARKER not in what and "local-0" not in what and not any(i["line"] in what for i in local.items)
    body = local.lines(path)
    event, aggregates = body[0], body[1:]
    assert event["split"] == "local" and event["runs"] == 1 and event["arm"] == "bprime" and event["items"] == 30
    assert all(a["record"] == "aggregate" for a in aggregates) and sum(a["n"] for a in aggregates) == 30
    assert {a["lang"] for a in aggregates} == {i["lang"] for i in local.items}
    assert local.problems(path) == []
    assert local.echo.calls, "the local lines are run through the model"


def test_local_aggregates_refuse_options_that_would_keep_or_show_lines(local):
    for argv in (["--record", str(local.tmp / "a")], ["--resume", str(local.tmp / "a")], ["--replay", str(local.tmp / "a")], ["--sample", "3", "--seed", "1"], ["--sequential"]):
        assert local.run("--local-aggregates", *argv)[0] == 2, argv
    assert local.echo.calls == [] and local.files() == []
    code, out, err = local.run()
    assert code == 1 and "--local-aggregates" in err, "local lines are measured as local lines only"


def test_a_local_corpus_with_an_id_that_is_not_local_is_refused(local):
    body = local.corpus.read_text(encoding="utf-8").replace("local-00007", "dev-en-00007")
    local.corpus.write_text(body, encoding="utf-8")
    code, out, err = local.run("--local-aggregates")
    assert code == 1 and local.echo.calls == []


def test_the_evidence_is_never_overwritten_and_a_second_run_writes_another_file(cli, monkeypatch):
    cli.run("--no-evidence")
    monkeypatch.setattr(measure.evidence, "new_test_id", lambda now=None: "20261021T120000Z-abcdef12")
    assert cli.run()[0] == 0
    code, out, err = cli.run()
    assert code == 1 and "never overwritten" in err and len(cli.files()) == 1


# --- vacuity: the oracles of this file see a planted fault --------------------------------------------------------------------------------------------

def test_vacuity_without_the_checkout_guard_the_inside_directory_would_be_accepted(held, monkeypatch):
    monkeypatch.setattr(measure, "outside_checkout", lambda directory: True)
    code, out, err = held.run("--record", str(held.checkout / "answers"), "--no-evidence")
    assert code == 0 and held.echo.calls, "so the guard test above fails when the guard is gone"


def test_vacuity_a_report_that_prints_a_line_is_seen_by_the_leak_oracle(cli, monkeypatch):
    victim = ITEMS[0]
    monkeypatch.setattr(measure, "text_report", lambda result, head: victim["line"])
    code, out, err = cli.run("--no-evidence")
    assert victim["line"] in out, "so the oracle that finds no line in the output can fail"


def test_vacuity_a_sample_that_ignores_what_reaches_the_model_is_seen_by_the_sequential_oracle(cli, monkeypatch):
    monkeypatch.setattr(measure, "draw", lambda items, n, seed, sequential: sorted(items, key=lambda i: i["id"])[:n])
    cli.run("--sequential", "--sample", "12", "--seed", "1")
    (path,) = cli.files()
    assert any(l["latency_ms"] is None for l in cli.lines(path)[1:]), "a line with no call in a sequential event is what the oracle of the test above refuses"
