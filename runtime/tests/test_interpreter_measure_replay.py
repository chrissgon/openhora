"""Record, replay and resume of the measurement harness (package IX-2c; runtime/interpreter_measure.py): the raw answers of a run are kept as they arrive; a replay reads them
back, makes no call of any kind and gives the same categories; a resume calls only the pairs the file lacks and writes one complete event; a header that is not this checkout's
is refused naming the field; and a recorded text that is malformed parses as `interpreter.parse` says. The model is the echo route of test_interpreter_echo.py; a replay is run with
`interpreter_route.complete`, the providers' `call` and every socket replaced by something that raises. Offline: no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_measure_replay.py
"""
from __future__ import annotations

import collections
import json
import socket
from pathlib import Path

import pytest

import standin_tree as st
from test_interpreter_measure_cli import Cli, ITEMS, ROUTE, route_module

measure = st.load("interpreter_measure")
pipeline = st.load("interpreter_pipeline")
interpreter = st.load("interpreter")
project_config = st.load("project_config")

MODEL_ITEMS = [i for i in sorted(ITEMS, key=lambda i: i["id"]) if pipeline.pre_model(i) is None]


@pytest.fixture
def cli(tmp_path, monkeypatch, capsys):
    return Cli(tmp_path, monkeypatch, capsys, ITEMS)


def answers_file(cli):
    (path,) = cli.answers.glob("*.answers.jsonl")
    return path


def lines_of(path):
    return Path(path).read_text(encoding="utf-8").splitlines()


def forbid_every_way_out(cli, monkeypatch):
    """After this, a call of any kind raises: the route's `complete`, the providers' `call` and every socket."""
    def forbidden(*a, **k):
        raise AssertionError("a replay made a call")
    monkeypatch.setattr(route_module, "complete", forbidden)
    monkeypatch.setattr(project_config.resolver(str(Path(__file__).resolve().parents[2])), "call", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def summary(out):
    return json.loads(out)


# --- the same categories, no call ----------------------------------------------------------------------------------------------------------------

def test_a_replay_gives_the_categories_of_the_recorded_run_and_makes_no_call(cli, monkeypatch):
    code, out, err = cli.run("--record", str(cli.answers), "--json", "--no-evidence")
    assert code == 0, err
    recorded, made = summary(out), len(cli.echo.calls)
    assert made > 0 and recorded["live_calls"] == made, "the recording run did call: so a replay that makes none is a result"
    forbid_every_way_out(cli, monkeypatch)
    code, out, err = cli.run("--replay", str(cli.answers), "--json")
    assert code == 0, err
    replayed = summary(out)
    assert replayed["live_calls"] == 0 and len(cli.echo.calls) == made
    for key in ("items", "runs", "measures", "by_language", "stages", "observed", "errors", "parse_failure_rate", "calls", "time_disagree", "private_route"):
        assert replayed[key] == recorded[key], key
    assert cli.files() == [], "a replay is a regression check of the code: no evidence"
    assert "evidence: not written" in err


def test_a_replay_of_the_test_split_reads_answers_kept_outside_the_checkout_and_makes_no_call(tmp_path, monkeypatch, capsys):
    from test_interpreter_measure_cli import as_split
    held = Cli(tmp_path, monkeypatch, capsys, as_split(ITEMS, "test"))
    outside = tmp_path / "outside"
    assert held.run("--record", str(outside), "--no-evidence")[0] == 0
    forbid_every_way_out(held, monkeypatch)
    code, out, err = held.run("--replay", str(outside), "--json")
    assert code == 0, err
    assert held.run("--replay", str(held.checkout / "x"))[0] == 1


def test_a_replay_with_a_pair_missing_is_refused_and_names_no_item(cli, monkeypatch):
    cli.run("--record", str(cli.answers), "--no-evidence")
    path = answers_file(cli)
    kept = lines_of(path)[:-3]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    forbid_every_way_out(cli, monkeypatch)
    code, out, err = cli.run("--replay", str(cli.answers))
    assert code == 1 and "lacks a call" in err and not any(i["id"] in err for i in ITEMS)


def test_a_replay_reads_a_recorded_failure_as_an_outage_with_its_code(cli, monkeypatch):
    victim = MODEL_ITEMS[0]
    cli.echo.fail[victim["id"]] = "E_RATE"
    cli.run("--record", str(cli.answers), "--no-evidence")
    forbid_every_way_out(cli, monkeypatch)
    code, out, err = cli.run("--replay", str(cli.answers), "--json")
    assert code == 0 and summary(out)["errors"] == {"E_RATE": 2}


def test_a_replay_directory_holds_exactly_one_answers_file(cli):
    cli.run("--record", str(cli.answers), "--no-evidence")
    cli.run("--record", str(cli.answers), "--no-evidence")
    assert len(list(cli.answers.glob("*.answers.jsonl"))) == 2
    code, out, err = cli.run("--replay", str(cli.answers))
    assert code == 1 and "exactly one answers file" in err
    code, out, err = cli.run("--replay", str(cli.tmp / "nowhere"))
    assert code == 1


# --- the header ----------------------------------------------------------------------------------------------------------------------------------

def test_the_answers_file_starts_with_a_header_of_hashes_and_holds_one_line_per_call(cli):
    cli.run("--record", str(cli.answers), "--no-evidence")
    body = [json.loads(l) for l in lines_of(answers_file(cli))]
    header, answers = body[0], body[1:]
    assert set(header) == {"record", "v", "test", "route", "route_sha256", "prompt_sha256", "catalog_sha256", "protocol_sha256", "corpus_sha256", "runs", "sequential", "sample"}
    assert header["route"] == ROUTE and header["runs"] == 2 and header["sequential"] is False and header["sample"] is None
    assert len(answers) == len(cli.echo.calls) and all(set(a) == {"item", "run", "ok", "text", "code", "finish", "usage", "latency_ms", "upstream"} for a in answers)
    assert all(a["latency_ms"] >= 0 and a["ok"] and isinstance(a["text"], str) for a in answers)
    assert not any("system" in a or "user" in a or "prompt" in a for a in answers), "the prompt is never written"


@pytest.mark.parametrize("field", ["route", "route_sha256", "prompt_sha256", "catalog_sha256", "protocol_sha256", "corpus_sha256"])
def test_a_header_that_is_not_this_checkouts_is_refused_naming_the_field(cli, monkeypatch, field):
    cli.run("--record", str(cli.answers), "--no-evidence")
    path = answers_file(cli)
    rows = lines_of(path)
    header = json.loads(rows[0])
    header[field] = "0" * 64 if field != "route" else "another-route"
    path.write_text("\n".join([json.dumps(header)] + rows[1:]) + "\n", encoding="utf-8")
    forbid_every_way_out(cli, monkeypatch)
    code, out, err = cli.run("--replay", str(cli.answers))
    assert code == 1 and err.strip() == f"error: the answers file differs from this checkout in {field}"


def test_a_file_that_is_not_an_answers_file_is_refused(cli):
    cli.answers.mkdir()
    (cli.answers / "x.answers.jsonl").write_text('{"record": "event"}\n', encoding="utf-8")
    code, out, err = cli.run("--replay", str(cli.answers))
    assert code == 1 and "header" in err
    (cli.answers / "x.answers.jsonl").write_text("not json\n", encoding="utf-8")
    assert cli.run("--replay", str(cli.answers))[0] == 1


# --- resume --------------------------------------------------------------------------------------------------------------------------------------

def test_a_resume_with_half_the_answers_calls_only_the_missing_pairs_and_writes_one_complete_event(cli):
    cli.run("--record", str(cli.answers), "--no-evidence")
    path = answers_file(cli)
    rows = lines_of(path)
    total = len(rows) - 1
    keep = total // 2
    kept = {(json.loads(r)["item"], json.loads(r)["run"]) for r in rows[1:1 + keep]}
    path.write_text("\n".join(rows[:1 + keep]) + "\n" + rows[1 + keep][: len(rows[1 + keep]) // 2], encoding="utf-8")          # the last line is cut short by an interruption
    cli.echo.calls.clear()
    code, out, err = cli.run("--resume", str(cli.answers), "--json")
    assert code == 0, err
    assert len(cli.echo.calls) == total - keep, "only the missing pairs are paid for"
    assert answers_file(cli) == path and len(list(cli.answers.glob("*.answers.jsonl"))) == 1
    body = [json.loads(l) for l in lines_of(path)]
    pairs = collections.Counter((a["item"], a["run"]) for a in body[1:])
    assert len(body) - 1 == total and set(pairs.values()) == {1} and kept <= set(pairs), "every pair once, the first half untouched"
    (evidence,) = cli.files()
    event = [json.loads(l) for l in lines_of(evidence)]
    assert event[0]["test"] == body[0]["test"] and cli.problems(evidence) == [] and len(event) == 1 + 2 * len(ITEMS)


def test_a_resume_that_finds_nothing_to_continue_starts_a_new_record(cli):
    code, out, err = cli.run("--resume", str(cli.answers), "--no-evidence")
    assert code == 0 and len(list(cli.answers.glob("*.answers.jsonl"))) == 1 and len(cli.echo.calls) > 0


def test_a_file_of_another_run_is_not_continued(cli):
    cli.run("--sequential", "--sample", "6", "--seed", "1", "--record", str(cli.answers), "--no-evidence")
    first = answers_file(cli)
    cli.echo.calls.clear()
    code, out, err = cli.run("--resume", str(cli.answers), "--no-evidence")
    assert code == 0 and len(list(cli.answers.glob("*.answers.jsonl"))) == 2, "the full run does not continue the sequential sample"
    assert len(lines_of(first)) == 1 + 12


def test_a_resume_of_a_finished_run_makes_no_call_and_never_overwrites_its_evidence(cli):
    cli.run("--resume", str(cli.answers))
    (written,) = cli.files()
    before = written.read_bytes()
    cli.echo.calls.clear()
    code, out, err = cli.run("--resume", str(cli.answers))
    assert code == 1 and "never overwritten" in err and cli.echo.calls == [] and written.read_bytes() == before


def test_a_recorded_failure_is_kept_by_a_resume_not_called_again(cli):
    victim = MODEL_ITEMS[0]
    cli.echo.fail[victim["id"]] = "E_UPSTREAM"
    cli.run("--record", str(cli.answers), "--no-evidence")
    cli.echo.fail.clear()
    cli.echo.calls.clear()
    cli.run("--resume", str(cli.answers), "--no-evidence")
    assert cli.echo.calls == [], "the recorded pairs include the failed ones: no pair is paid twice"


# --- the recorded text is parsed as the protocol says ---------------------------------------------------------------------------------------------------

def two_k():
    filler = "a" * (2049 - len('{"v":1,"kind":"none","x":""}'))
    text = '{"v":1,"kind":"none","x":"' + filler + '"}'
    assert len(text.encode("utf-8")) == 2049
    return text


MALFORMED = [
    ("truncated", '{"v": 1, "kind": "op", "op": "sta', "invalid"),
    ("two objects", '{"v": 1, "kind": "none"}{"v": 1, "kind": "none"}', "invalid"),
    ("2049 bytes", two_k(), "invalid"),
    ("trailing text", '{"v": 1, "kind": "none"} thanks', "invalid"),
    ("fenced", '```json\n{"v": 1, "kind": "none"}\n```', "fenced"),
    ("plain", '{"v": 1, "kind": "none"}', "ok"),
    ("empty", "", "invalid"),
]


@pytest.mark.parametrize("name,text,parse", MALFORMED, ids=[m[0] for m in MALFORMED])
def test_a_recorded_text_parses_as_the_protocol_says(cli, name, text, parse):
    one = MODEL_ITEMS[0]
    found = {(one["id"], 1): {"item": one["id"], "run": 1, "ok": True, "text": text, "code": None, "finish": "stop", "usage": None, "latency_ms": 5, "upstream": None}}
    answers = measure.Answers("replay", {}, found, None)
    done = measure.run_all([one], 1, 1, answers, route_module.find(ROUTE))
    outcome = done[(1, 1)]
    assert outcome["parse"] == parse
    assert outcome["observed"] == ("clarify" if parse == "invalid" else "none") and outcome["error"] is None
    assert outcome["call"]["latency_ms"] == 5 and answers.live_calls == 0


def test_a_replay_of_a_pair_the_file_lacks_raises_instead_of_calling(cli, monkeypatch):
    one = MODEL_ITEMS[0]
    answers = measure.Answers("replay", {}, {}, None)
    monkeypatch.setattr(route_module, "complete", lambda *a, **k: pytest.fail("a replay called the route"))
    with pytest.raises(measure.Refused):
        measure.run_all([one], 1, 1, answers, route_module.find(ROUTE))
