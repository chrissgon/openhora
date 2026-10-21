"""The evidence lines of the interpreter experiment (package IX-2c; runtime/interpreter_evidence.py): every line the builders write is in the closed form that IX-E's validator
(evals/evidence_lines.py, loaded here by path: a test may read what the layer map keeps runtime/ from importing) accepts, strictly, as a new file is read; the hashes an event
states are recomputed here with the test's own canonical JSON; a file already there is never overwritten; and a builder that adds a free-text key or writes the upstream's own
word instead of the route's pin is refused by that validator. Offline: no model, no network; the model is the echo of test_interpreter_echo.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_measure_evidence.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_interpreter_echo import DEV, Echo, load, sample

evidence = st.load("interpreter_evidence")
pipeline = st.load("interpreter_pipeline")
score = st.load("interpreter_score")
route_module = st.load("interpreter_route")
interpreter = st.load("interpreter")
prices = st.load("prices")

ROOT = Path(__file__).resolve().parents[2]
TEST_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


def by_path(rel, name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


lines_module = by_path("evals/evidence_lines.py", "workbench_evidence_lines_for_ix2c")
status_module = by_path("evals/interpreter_status.py", "workbench_interpreter_status_for_ix2c")

ROUTE = next(r for r in route_module.load()["routes"] if r["id"] == "or-claude-haiku-4.5")
PRICES = {"models": {ROUTE["model"]: {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 5.0, "cache_read_usd_per_mtok": 0.1}}}


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def as_split(items, split):
    """The same fictional items under another split's ids."""
    return [{**i, "id": split + i["id"][3:], "split": split} for i in items]


def runs_of(items, route=ROUTE, runs=2, call=Echo):
    """[(item, run, outcome, category)] as the harness builds them."""
    out = []
    for one in items:
        for run in range(1, runs + 1):
            outcome = pipeline.run_item(one, run, call(one))
            out.append((one, run, outcome, score.categorize(one["gold"], one["also"], one["gold"].get("scope", "full"), outcome["observed"], outcome["detail"])))
    return out


def write_file(folder, arm, split, scored, route=ROUTE, runs=2, items=None, sequential=False, billing="metered", corpus=None, table=PRICES, builder=None):
    test = evidence.new_test_id()
    build = builder or evidence.item_line
    event = evidence.event_line(arm=arm, split=split, test=test, date=evidence.utc_date(), route=route if arm == "bprime" else None, runs=runs,
                                items=items if items is not None else len({s[0]["id"] for s in scored}), sequential=sequential, billing=billing, corpus=corpus or "a" * 64)
    body = [event] + [build(test, one, run, outcome, category, route if arm == "bprime" else None, table) for one, run, outcome, category in scored]
    path = folder / f"ix-{test}.jsonl"
    evidence.write_exclusive(str(path), body)
    return path, test


def strict_for(runs=2):
    return {"runs": runs, "routes": {ROUTE["id"]: ROUTE["model"]}, "pins": {ROUTE["id"]: ROUTE["pin"]}}


def problems(path, runs=2):
    return lines_module.interpreter_file_problems(str(path), strict_for(runs))


def read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


SAMPLE = sample(load(DEV), 24)


# --- the lines are in IX-E's closed forms --------------------------------------------------------------------------------------------------------------

def test_a_bprime_dev_file_is_valid_strictly(tmp_path):
    path, _ = write_file(tmp_path, "bprime", "dev", runs_of(SAMPLE), items=310)
    assert problems(path) == []


def test_a_bprime_test_file_is_valid_strictly_with_the_configured_runs(tmp_path):
    items = as_split(SAMPLE, "test")
    path, _ = write_file(tmp_path, "bprime", "test", runs_of(items), items=800)
    assert problems(path, runs=2) == []
    other, _ = write_file(tmp_path, "bprime", "test", runs_of(items, runs=3), runs=3, items=800)
    assert any("configured number" in p for p in problems(other, runs=2)), "a test event with another number of runs is refused by the validator"


def test_a_sequential_event_may_hold_fewer_items_than_the_file_states(tmp_path):
    path, _ = write_file(tmp_path, "bprime", "test", runs_of(as_split(SAMPLE[:5], "test")), items=800, sequential=True)
    assert problems(path) == [] and read(path)[0]["sequential"] is True and read(path)[0]["items"] == 800


def test_a_current_arm_file_is_valid_and_names_no_model_route_prompt_or_cost(tmp_path):
    scored = runs_of(SAMPLE[:12], route=None)
    path, _ = write_file(tmp_path, "current", "dev", scored, route=None, billing="none", table=None)
    assert problems(path) == []
    first = read(path)
    assert [first[0][k] for k in ("model", "route", "route_sha256", "prompt_sha256")] == [None] * 4 and first[0]["billing"] == "none"
    assert all(line["cost_usd"] is None and line["upstream"] is None for line in first[1:])


def test_a_local_file_holds_aggregates_with_no_id(tmp_path):
    scored = runs_of(SAMPLE, runs=1)
    test = evidence.new_test_id()
    by_lang = {}
    for one, run, outcome, category in scored:
        by_lang.setdefault(one["lang"], []).append((category, outcome["parse"] == "invalid"))
    event = evidence.event_line(arm="bprime", split="local", test=test, date=evidence.utc_date(), route=ROUTE, runs=1, items=len(SAMPLE), sequential=False, billing="metered",
                                corpus="b" * 64)
    aggregates = [evidence.aggregate_line(test, lang, [c for c, _ in rows], sum(1 for _, bad in rows if bad)) for lang, rows in sorted(by_lang.items())]
    path = tmp_path / f"ix-{test}.jsonl"
    evidence.write_exclusive(str(path), [event] + aggregates)
    assert problems(path, runs=1) == []
    assert sum(a["n"] for a in aggregates) == len(SAMPLE) and all(set(a) == set(lines_module.IX_AGGREGATE_KEYS) for a in aggregates)
    assert not any(re.search(r"dev-|local-", line) for line in path.read_text(encoding="utf-8").splitlines()[1:])


def test_the_keys_of_every_line_are_exactly_the_closed_lists_and_the_gold_is_a_closed_word(tmp_path):
    path, _ = write_file(tmp_path, "bprime", "dev", runs_of(SAMPLE[:10]))
    body = read(path)
    assert set(body[0]) == set(lines_module.IX_EVENT_KEYS)
    for line in body[1:]:
        assert set(line) == set(lines_module.IX_ITEM_KEYS)
        assert line["gold"] in ("op", "answer", "clarify", "route", "none", "refuse", "forwarded")
    golds = {l["item"]: l["gold"] for l in body[1:]}
    assert golds == {i["id"]: i["gold"]["outcome"] for i in SAMPLE[:10]}


# --- what the lines say -------------------------------------------------------------------------------------------------------------------------------

def test_the_upstream_is_the_routes_pin_when_the_call_succeeded_and_the_provider_named_one_else_null(tmp_path):
    scored = runs_of(sample(load(DEV), 120))
    path, _ = write_file(tmp_path, "bprime", "dev", scored)
    body = read(path)[1:]
    for line, (one, run, outcome, category) in zip(body, scored):
        called = outcome["call"] is not None
        assert line["upstream"] == (ROUTE["pin"] if called else None)
        assert (line["latency_ms"] is not None) == called and (line["usage"] is not None) == called
    assert any(line["upstream"] is None for line in body) and any(line["upstream"] == ROUTE["pin"] for line in body)


def test_a_provider_that_names_no_upstream_leaves_it_null():
    class Silent(Echo):
        def __call__(self, system, user):
            got = super().__call__(system, user)
            got["upstream"] = None
            return got
    one = next(i for i in SAMPLE if pipeline.pre_model(i) is None)
    outcome = pipeline.run_item(one, 1, Silent(one))
    assert evidence.item_line("t", one, 1, outcome, "correct", ROUTE, PRICES)["upstream"] is None


def test_the_error_of_an_item_is_the_calls_code_never_a_parse_code():
    one = next(i for i in SAMPLE if pipeline.pre_model(i) is None)
    garbled = pipeline.run_item(one, 1, lambda s, u: {"ok": True, "text": "{", "finish": "stop", "usage": None, "latency_ms": 5, "upstream": None})
    line = evidence.item_line("t", one, 1, garbled, "missed", ROUTE, PRICES)
    assert (line["parse"], line["error"]) == ("invalid", None)
    failed = pipeline.run_item(one, 1, lambda s, u: {"ok": False, "code": "E_TIMEOUT", "latency_ms": 6001})
    line = evidence.item_line("t", one, 1, failed, "missed", ROUTE, PRICES)
    assert (line["error"], line["observed"], line["latency_ms"], line["usage"], line["cost_usd"]) == ("E_TIMEOUT", "outage", 6001, None, None)
    assert line["error"] in lines_module.IX_ERRORS


def test_the_cost_is_the_price_table_times_the_tokens_and_unknown_when_a_kind_is_unpriced():
    usage = {"input": 1000, "output": 100, "cache_read": None, "cache_write": None}
    assert evidence.cost_usd(usage, ROUTE, PRICES) == pytest.approx(1000 * 1.0 / 1e6 + 100 * 5.0 / 1e6)
    cached = {"input": 200, "output": 50, "cache_read": 800, "cache_write": None}
    assert evidence.cost_usd(cached, ROUTE, PRICES) == pytest.approx(200 * 1.0 / 1e6 + 50 * 5.0 / 1e6 + 800 * 0.1 / 1e6)
    written = {"input": 200, "output": 50, "cache_read": None, "cache_write": 800}
    assert evidence.cost_usd(written, ROUTE, PRICES) is None, "a cache write has no price in this table: unknown, never zero"
    assert evidence.cost_usd({"input": None, "output": None, "cache_read": None, "cache_write": None}, ROUTE, PRICES) is None, "no token count was reported"
    assert evidence.cost_usd(None, ROUTE, PRICES) is None and evidence.cost_usd(usage, None, PRICES) is None
    assert evidence.cost_usd(usage, ROUTE, {"models": {}}) is None


# --- the hashes ----------------------------------------------------------------------------------------------------------------------------------------

def test_the_hashes_of_an_event_are_recomputed_here_from_the_files(tmp_path):
    h = evidence.hashes(ROUTE)
    read_json = lambda rel: json.loads((ROOT / rel).read_text(encoding="utf-8"))  # noqa: E731
    assert h["route_sha256"] == status_module.route_sha256(ROUTE) == route_module.route_sha256(ROUTE)
    assert h["protocol_sha256"] == sha(canon(read_json("runtime/interpreter_protocol.json"))) and h["protocol"] == 1
    assert h["prompt_sha256"] == sha((ROOT / "runtime" / "interpreter_prompt.txt").read_bytes())
    assert h["catalog_sha256"] == sha(canon(read_json("runtime/interpreter_catalog.json"))) == interpreter.SERVED_SHA256
    assert h["taxonomy_sha256"] == sha(canon(read_json("evals/interpreter/taxonomy.json")))
    assert h["thresholds_sha256"] == sha(canon(read_json("evals/interpreter/thresholds.json")))
    assert (h["model"], h["route"]) == (ROUTE["model"], ROUTE["id"])
    parts = {rel: sha((ROOT / rel).read_bytes()) for rel in ("runtime/interpreter_measure.py", "runtime/interpreter_pipeline.py", "runtime/interpreter_score.py",
                                                            "runtime/interpreter_evidence.py", "runtime/tests/test_interpreter_current_arm.py", "evals/interpreter/taxonomy.json",
                                                            "evals/interpreter/thresholds.json")}
    assert h["harness_sha256"] == sha(canon(parts))
    none = evidence.hashes(None)
    assert [none[k] for k in ("model", "route", "route_sha256", "prompt_sha256")] == [None] * 4
    assert {k: none[k] for k in ("protocol_sha256", "catalog_sha256", "taxonomy_sha256", "thresholds_sha256")} == {k: h[k] for k in ("protocol_sha256", "catalog_sha256", "taxonomy_sha256",
                                                                                                                                    "thresholds_sha256")}


def test_the_languages_and_their_id_codes_are_the_validators():
    assert pipeline.LANG_CODES == lines_module.IX_LANG_CODES and tuple(pipeline.LANG_CODES) == lines_module.IX_LANGS


def test_a_clarification_met_by_an_also_clarify_is_a_valid_line_of_category_correct(tmp_path):
    """The rule stated in evals/interpreter/README.md: the alternatives of `also` are part of the matching of rule 8, so a clarification a gold op lists as acceptable is `correct`
    (its gold stays `op`, so it is in the denominators of correct_direct); without that alternative the same clarification is `clarify`."""
    one = next(i for i in SAMPLE if i["gold"]["outcome"] == "op" and pipeline.pre_model(i) is None)
    clarify = {"ok": True, "text": json.dumps({"v": 1, "kind": "clarify", "slot": "when"}), "finish": "stop", "usage": None, "latency_ms": 5, "upstream": "pinned"}
    outcome = pipeline.run_item(one, 1, lambda s, u: clarify)
    assert outcome["observed"] == "clarify"
    liked = {**one, "also": [{"outcome": "clarify"}]}
    assert score.categorize(liked["gold"], liked["also"], "full", outcome["observed"], outcome["detail"]) == "correct"
    assert score.categorize(one["gold"], [], "full", outcome["observed"], outcome["detail"]) == "clarify"
    scored = [(liked, 1, outcome, "correct"), (liked, 2, outcome, "correct")]
    path, _ = write_file(tmp_path, "bprime", "dev", scored, items=310)
    assert problems(path) == [] and {l["gold"] for l in read(path)[1:]} == {"op"}


def test_the_corpus_hash_is_the_split_files_bytes_for_test_and_local_and_the_corpus_bytes_for_dev(tmp_path):
    split = tmp_path / "test-split.json"
    split.write_text('{"sha256": "x", "items": 3}\n', encoding="utf-8")
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text("{}\n", encoding="utf-8")
    assert evidence.corpus_sha256("test", str(corpus), str(split)) == sha(split.read_bytes())
    assert evidence.corpus_sha256("local", str(corpus), str(split)) == sha(split.read_bytes())
    assert evidence.corpus_sha256("dev", str(corpus), str(split)) == sha(corpus.read_bytes())


def test_the_test_id_and_the_date_have_the_validators_form():
    assert TEST_ID.fullmatch(evidence.new_test_id()) and lines_module.TEST_ID_RE.fullmatch(evidence.new_test_id())
    assert len({evidence.new_test_id() for _ in range(50)}) == 50
    assert evidence.new_test_id(0).startswith("19700101T000000Z-") and evidence.utc_date(0) == "1970-01-01"


# --- the write -----------------------------------------------------------------------------------------------------------------------------------------

def test_an_existing_evidence_file_is_never_overwritten(tmp_path):
    path = tmp_path / "ix-20261021T120000Z-abcdef12.jsonl"
    evidence.write_exclusive(str(path), [{"record": "event"}])
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        evidence.write_exclusive(str(path), [{"record": "event", "other": 1}])
    assert path.read_bytes() == before


def test_the_lines_are_ascii_canonical_json_one_per_line(tmp_path):
    path = tmp_path / "x.jsonl"
    evidence.write_exclusive(str(path), [{"b": "ação", "a": 1}, {"z": "\ud800"}])  # validate: allow english-only -- a fictional Portuguese line or word, the input under test
    text = path.read_bytes().decode("ascii")
    assert text == '{"a":1,"b":"a\\u00e7\\u00e3o"}\n{"z":"\\ud800"}\n'


# --- vacuity: a planted wrong builder is refused by the validator ------------------------------------------------------------------------------------

def test_a_builder_that_adds_a_free_text_key_is_refused(tmp_path):
    def leaky(test, one, run, outcome, category, route, table):
        line = evidence.item_line(test, one, run, outcome, category, route, table)
        line["line"] = one["line"]
        return line
    path, _ = write_file(tmp_path, "bprime", "dev", runs_of(SAMPLE[:4]), builder=leaky)
    assert any("unknown key 'line'" in p for p in problems(path))


def test_a_builder_that_writes_the_upstream_word_instead_of_the_pin_is_refused(tmp_path):
    def wrong(test, one, run, outcome, category, route, table):
        line = evidence.item_line(test, one, run, outcome, category, route, table)
        if outcome["call"]:
            line["upstream"] = outcome["call"]["upstream"]          # the echo's provider word is "pinned"
        return line
    path, _ = write_file(tmp_path, "bprime", "dev", runs_of(SAMPLE[:12]), builder=wrong)
    assert any("the route pins" in p for p in problems(path))


def test_a_builder_that_leaves_the_gold_out_is_refused(tmp_path):
    def forgetful(test, one, run, outcome, category, route, table):
        line = evidence.item_line(test, one, run, outcome, category, route, table)
        del line["gold"]
        return line
    path, _ = write_file(tmp_path, "bprime", "dev", runs_of(SAMPLE[:4]), builder=forgetful)
    assert any("missing key 'gold'" in p for p in problems(path))


def test_a_builder_that_charges_an_unmetered_run_is_refused(tmp_path):
    def charging(test, one, run, outcome, category, route, table):
        line = evidence.item_line(test, one, run, outcome, category, route, table)
        line["cost_usd"] = 0.5
        return line
    path, _ = write_file(tmp_path, "current", "dev", runs_of(SAMPLE[:6], route=None), route=None, billing="none", builder=charging)
    assert any("cost_usd must be null" in p for p in problems(path))
