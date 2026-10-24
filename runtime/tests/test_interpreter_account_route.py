"""The account route of the interpreter (package ACCT-C; SPEC-ACCT-ROUTE sections 2.1, 2.4, 3.5 and 7): the two rows of kind `account` in
runtime/interpreter_routes.json, the loader's rules for them, the hash a caller accepts them by (the same in runtime/interpreter_route.py and in
evals/interpreter_status.py), `daily_routes()` (kind http only), `complete()`'s account branch, and what a measurement on an account route writes
(billing subscription, no cost on any line). Every expected value is this file's own literal, or is computed here from the raw file with this
file's own canonical JSON; each invariant has a vacuity case that fails on a planted wrong result. The lab is a stand-in: no model, no process,
no credential, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_account_route.py
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_interpreter_measure_cli import CONFIGURED, ITEMS, Cli
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

ir = st.load("interpreter_route")
measure = st.load("interpreter_measure")
evidence = st.load("interpreter_evidence")

REPO = Path(__file__).resolve().parents[2]
RETENTION = "Sent to the vendor under the maintainer's subscription account terms; zero data retention is not confirmed."
SONNET_ID, HAIKU_ID = "acct-claude-sonnet-5.5", "acct-claude-haiku-4.5"
DEEPSEEK_ID = "or-deepseek-v4.1-flash"
# The sha256 of the canonical JSON of each row without `retention` and `reference`, computed once offline from the rows below; the values are in scripts/tests/pinned_hashes.json.
HASHES = {
    DEEPSEEK_ID: PINNED_HASHES["route_or_deepseek_v4_1_flash"],
    SONNET_ID: PINNED_HASHES["route_acct_sonnet_5_5"],
    HAIKU_ID: PINNED_HASHES["route_acct_haiku_4_5"],
}
RUNNER_VERSION = "run-text/1 cli/2.1.283"
SONNET_ROW = {"id": SONNET_ID, "kind": "account", "model": "claude-sonnet-5-5", "upstream_model": "claude-sonnet-5-5", "lab_model": "claude-sonnet-5-5",
              "pin": "anthropic", "params": {"max_tokens": 2000, "reasoning": "low", "temperature": None}, "deadline_ms": 60000,
              "runner_version": RUNNER_VERSION, "envelope_sha256": "3ef9b0668fc2798353994e820aab652bc745a106b1655353636bad8ff54b232f",
              "reference": True, "retention": RETENTION}
HAIKU_ROW = {"id": HAIKU_ID, "kind": "account", "model": "claude-haiku-4-5", "upstream_model": "claude-haiku-4-5", "lab_model": "claude-sonnet-5-5",
             "pin": "anthropic", "params": {"max_tokens": 300, "reasoning": "off", "temperature": None}, "deadline_ms": 60000,
             "runner_version": RUNNER_VERSION, "envelope_sha256": "7203a61429bff45e54353b8cef836dd38c0307a2a058ece600455b649a75f646",
             "reference": False, "retention": RETENTION}


def by_path(rel, name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


status_module = by_path("evals/interpreter_status.py", "workbench_interpreter_status_for_acct_c")
lines_module = by_path("evals/evidence_lines.py", "workbench_evidence_lines_for_acct_c")


def raw_routes():
    return json.loads((REPO / "runtime" / "interpreter_routes.json").read_text(encoding="utf-8"))


def raw_row(row_id):
    return next(r for r in raw_routes()["routes"] if r["id"] == row_id)


def runner_sha256_of_files():
    """The sha256 over the files adapter.json lists as `text_files`, written out here (contracts/runtime.md, "The text contract"): for each, in
    sorted name order, its name, a newline, its bytes, a newline."""
    folder = REPO / "adapters" / "claude-code"
    names = json.loads((folder / "adapter.json").read_text(encoding="utf-8"))["text_files"]
    digest = hashlib.sha256()
    for name in sorted(names):
        digest.update(name.encode("utf-8") + b"\n" + (folder / name).read_bytes() + b"\n")
    return digest.hexdigest()


def canonical_hash(row):
    kept = {k: v for k, v in row.items() if k not in ("retention", "reference")}
    return hashlib.sha256(json.dumps(kept, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


# --- the committed rows ----------------------------------------------------------------------------------------------------------------

def test_the_committed_account_rows_are_the_literal_rows_the_probe_gave():
    for literal in (SONNET_ROW, HAIKU_ROW):
        assert raw_row(literal["id"]) == dict(literal, runner_sha256=runner_sha256_of_files())


def test_the_runner_sha256_of_the_rows_is_the_one_of_the_runner_files_now():
    """A change to a runner file without a new probe breaks this test, as it breaks the preflight at the first call."""
    assert {r["runner_sha256"] for r in raw_routes()["routes"] if r["kind"] == "account"} == {runner_sha256_of_files()}


def test_vacuity_the_runner_digest_follows_the_bytes(tmp_path):
    first = runner_sha256_of_files()
    folder = REPO / "adapters" / "claude-code"
    names = sorted(json.loads((folder / "adapter.json").read_text(encoding="utf-8"))["text_files"])
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode("utf-8") + b"\n" + (folder / name).read_bytes() + (b"x" if name == names[0] else b"") + b"\n")
    assert digest.hexdigest() != first


@pytest.mark.parametrize("row_id", sorted(HASHES))
def test_the_route_hash_of_every_committed_row_is_the_literal_in_both_modules(row_id):
    row = raw_row(row_id)
    assert ir.route_sha256(row) == status_module.route_sha256(row) == HASHES[row_id]
    if row["kind"] == "account":
        assert canonical_hash(row) == HASHES[row_id]


def test_vacuity_a_changed_setting_changes_an_account_hash_and_retention_and_reference_do_not():
    row = raw_row(SONNET_ID)
    for change in ({"params": dict(row["params"], reasoning="high")}, {"params": dict(row["params"], max_tokens=2001)}, {"deadline_ms": 59999},
                   {"envelope_sha256": "0" * 64}, {"runner_sha256": "1" * 64}, {"runner_version": "run-text/1 cli/9.9.9"}, {"lab_model": "claude-haiku-4-5"},
                   {"model": "claude-haiku-4-5"}, {"upstream_model": "claude-haiku-4-5"}, {"id": "acct-other"}):
        assert ir.route_sha256(dict(row, **change)) != HASHES[SONNET_ID] and status_module.route_sha256(dict(row, **change)) != HASHES[SONNET_ID], change
    for same in ({"retention": "another sentence"}, {"reference": False}):
        assert ir.route_sha256(dict(row, **same)) == HASHES[SONNET_ID] == status_module.route_sha256(dict(row, **same))


def test_the_deepseek_hash_is_unchanged_by_the_account_rows():
    assert ir.route_sha256(raw_row(DEEPSEEK_ID)) == PINNED_HASHES["route_or_deepseek_v4_1_flash"]


def test_an_account_route_is_not_shown_to_a_provider():
    with pytest.raises(ir.RouteError):
        ir.stdin_route(raw_row(SONNET_ID))


# --- the loader --------------------------------------------------------------------------------------------------------------------------

def workbench(tmp_path, rows):
    root = tmp_path / "wb"
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "secrets.json").write_text((REPO / "runtime" / "secrets.json").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "runtime" / "interpreter_routes.json").write_text(json.dumps({"v": 1, "routes": rows}), encoding="utf-8")
    return str(root)


def with_account(**over):
    """The committed file's rows, the Sonnet row changed by `over` (a key set to the string "<drop>" is removed)."""
    rows = copy.deepcopy(raw_routes()["routes"])
    for key, value in over.items():
        if value == "<drop>":
            del rows[1][key]
        else:
            rows[1][key] = value
    return rows


def test_the_committed_file_loads_with_the_two_account_rows_and_one_reference():
    doc = ir.load()
    assert [r["id"] for r in doc["routes"]] == [DEEPSEEK_ID, SONNET_ID, HAIKU_ID] and [r["kind"] for r in doc["routes"]] == ["http", "account", "account"]
    assert [r["id"] for r in doc["routes"] if r["reference"]] == [SONNET_ID]


REFUSED = {
    "an extra key": {"extra": 1}, "a key (an account row has none)": {"key": "WB_RUNTIME_KEY_OPENROUTER_API_KEY"}, "a missing retention": {"retention": "<drop>"},
    "a missing lab_model": {"lab_model": "<drop>"}, "a blank lab_model": {"lab_model": " "},
    "a lab_model of the floor model": {"lab_model": "openrouter/deepseek/deepseek-v4.1-flash"}, "a lab_model of another provider": {"lab_model": "deepseek/deepseek-v4.1-flash"},
    "a lab_model with the prefix in the middle": {"lab_model": "x-claude-sonnet-5-5"}, "a lab_model with the prefix in capitals": {"lab_model": "Claude-sonnet-5-5"}, "a missing params": {"params": "<drop>"},
    "kind http with the account keys": {"kind": "http"}, "kind blank": {"kind": " "},
    "a model of another vendor": {"model": "deepseek/deepseek-v4.1-flash", "upstream_model": "deepseek/deepseek-v4.1-flash"},
    "an upstream_model of another vendor": {"upstream_model": "deepseek/deepseek-v4.1-flash"}, "a router model": {"model": "openrouter/auto", "upstream_model": "openrouter/auto"},
    "another pin": {"pin": "deepinfra"}, "a blank pin": {"pin": ""}, "a bad id": {"id": "Bad_Id"}, "a long id": {"id": "a" * 65},
    "a duplicate id": {"id": "acct-claude-haiku-4.5"},
    "a temperature": {"params": {"max_tokens": 2000, "reasoning": "low", "temperature": 0}},
    "a reasoning word of no list": {"params": {"max_tokens": 2000, "reasoning": "ultra", "temperature": None}},
    "reasoning on or true": {"params": {"max_tokens": 2000, "reasoning": True, "temperature": None}},
    "max_tokens 0": {"params": {"max_tokens": 0, "reasoning": "low", "temperature": None}},
    "max_tokens true": {"params": {"max_tokens": True, "reasoning": "low", "temperature": None}},
    "max_tokens 64001": {"params": {"max_tokens": 64001, "reasoning": "low", "temperature": None}},
    "max_tokens text": {"params": {"max_tokens": "2000", "reasoning": "low", "temperature": None}},
    "a param key more": {"params": {"max_tokens": 2000, "reasoning": "low", "temperature": None, "top_p": 1}},
    "a param key fewer": {"params": {"max_tokens": 2000, "reasoning": "low"}},
    "deadline 0": {"deadline_ms": 0}, "deadline true": {"deadline_ms": True}, "deadline 600001": {"deadline_ms": 600001}, "deadline text": {"deadline_ms": "60000"},
    "a short runner_sha256": {"runner_sha256": "abc"}, "an upper-case runner_sha256": {"runner_sha256": "A" * 64}, "a non-hex envelope_sha256": {"envelope_sha256": "g" * 64},
    "a missing envelope": {"envelope_sha256": "<drop>"}, "a blank runner_version": {"runner_version": " "},
    "a reference that is not a flag": {"reference": "yes"}, "a blank retention": {"retention": " "},
}


@pytest.mark.parametrize("name", sorted(REFUSED))
def test_an_account_row_that_breaks_a_rule_is_refused(tmp_path, name):
    with pytest.raises(ir.RouteError):
        ir.load(workbench(tmp_path, with_account(**REFUSED[name])))


def test_vacuity_the_unchanged_rows_and_a_change_that_breaks_no_rule_load(tmp_path):
    assert ir.load(workbench(tmp_path, with_account()))["routes"][1]["id"] == SONNET_ID
    moved = ir.load(workbench(tmp_path / "moved", with_account(params={"max_tokens": 1500, "reasoning": "high", "temperature": None}, deadline_ms=30000)))
    assert moved["routes"][1]["params"]["reasoning"] == "high" and moved["routes"][1]["deadline_ms"] == 30000


def test_vacuity_a_lab_model_of_the_vendor_loads_and_the_committed_rows_keep_their_literal_hashes(tmp_path):
    for lab_model in ("claude-sonnet-5-5", "claude-haiku-4-5"):
        assert ir.load(workbench(tmp_path / lab_model, with_account(lab_model=lab_model)))["routes"][1]["lab_model"] == lab_model
    rows = {r["id"]: r for r in ir.load()["routes"]}
    assert ir.route_sha256(rows[SONNET_ID]) == PINNED_HASHES["route_acct_sonnet_5_5"]
    assert ir.route_sha256(rows[HAIKU_ID]) == PINNED_HASHES["route_acct_haiku_4_5"]
    assert ir.route_sha256(rows[DEEPSEEK_ID]) == PINNED_HASHES["route_or_deepseek_v4_1_flash"]


def test_the_references_are_exactly_one_across_the_two_kinds(tmp_path):
    rows = copy.deepcopy(raw_routes()["routes"])
    rows[0]["reference"] = True                      # the http row and the Sonnet row
    with pytest.raises(ir.RouteError):
        ir.load(workbench(tmp_path / "two", rows))
    rows[0]["reference"], rows[1]["reference"] = False, False
    with pytest.raises(ir.RouteError):
        ir.load(workbench(tmp_path / "none", rows))
    rows[2]["reference"] = True                      # exactly one: the Haiku row
    assert [r["id"] for r in ir.load(workbench(tmp_path / "one", rows))["routes"] if r["reference"]] == [HAIKU_ID]


def test_daily_routes_holds_no_account_row_while_load_does():
    daily = ir.daily_routes()
    assert [r["id"] for r in daily] == [DEEPSEEK_ID] and all(r["kind"] == "http" for r in daily)
    assert {r["id"] for r in ir.load()["routes"]} - {r["id"] for r in daily} == {SONNET_ID, HAIKU_ID}      # vacuity: the account rows exist


def test_daily_routes_of_a_file_whose_only_http_row_is_gone_is_empty(tmp_path):
    rows = [r for r in raw_routes()["routes"] if r["kind"] == "account"]
    assert ir.daily_routes(workbench(tmp_path, rows)) == []


# --- the call ----------------------------------------------------------------------------------------------------------------------------

class FakeLab:
    """What `complete()` reaches in place of runtime/lab.py: it records each call and answers with `reply`."""

    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply if reply is not None else {"ok": True, "text": "a reply", "finish": "stop", "latency_ms": 12,
                                                      "usage": {"input": 7, "output": 3, "cache_read": 1, "cache_write": None}}

    def account_text(self, row, system, user, run=None):
        self.calls.append((row["id"], system, user, run))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def lab(monkeypatch):
    fake = FakeLab()
    monkeypatch.setattr(ir, "_lab", lambda: fake)
    return fake


def call(row_id=SONNET_ID, accepted=None, **kw):
    kw.setdefault("deadline_ms", 1)
    return ir.complete(row_id, "the system text", "the user text", accepted=[HASHES[row_id]] if accepted is None else accepted, **kw)


def test_an_accepted_account_route_returns_the_reply_in_the_shape_of_the_http_path(lab):
    got = call()
    assert got == {"ok": True, "text": "a reply", "finish": "stop", "usage": {"input": 7, "output": 3, "cache_read": 1, "cache_write": None},
                   "latency_ms": 12, "upstream": "anthropic"}
    assert lab.calls == [(SONNET_ID, "the system text", "the user text", None)]


def test_the_arguments_of_a_caller_do_not_reach_the_lab_the_row_decides(lab):
    """The call hands the lab the row alone: temperature, max_tokens, reasoning and deadline_ms of the caller are not an input of the account path."""
    seen = []
    lab.account_text = lambda row, system, user, run=None: seen.append(row) or {"ok": True, "text": "x", "finish": "stop", "latency_ms": 1, "usage": {}}
    call(temperature=0.9, max_tokens=5, reasoning="max", deadline_ms=1)
    (row,) = seen
    assert row["params"] == {"max_tokens": 2000, "reasoning": "low", "temperature": None} and row["deadline_ms"] == 60000


def test_a_route_hash_that_is_not_accepted_is_e_route_and_the_lab_is_never_reached(lab):
    for accepted in ([], ["0" * 64], [HASHES[HAIKU_ID]], [HASHES[DEEPSEEK_ID]], ["", None]):
        assert call(accepted=accepted) == {"ok": False, "code": "E_ROUTE"}, accepted
    assert lab.calls == []
    assert call()["ok"] is True and len(lab.calls) == 1      # vacuity: the accepted hash reaches it


def test_a_changed_row_is_not_accepted_by_the_old_hash(tmp_path, lab):
    root = workbench(tmp_path, with_account(params={"max_tokens": 2000, "reasoning": "high", "temperature": None}))
    got = ir.complete(SONNET_ID, "s", "u", accepted=[HASHES[SONNET_ID]], deadline_ms=1, root=root)
    assert got == {"ok": False, "code": "E_ROUTE"} and lab.calls == []


def test_a_failure_of_the_lab_is_its_code_and_nothing_else(lab):
    for code in ("E_ROUTE", "E_KEY", "E_TIMEOUT", "E_RATE", "E_RESPONSE"):
        lab.reply = {"ok": False, "code": code, "detail": "the user text"}
        assert call() == {"ok": False, "code": code}
    for junk in ({"ok": False}, {"ok": False, "code": "boom"}, {"ok": False, "code": None}, {"ok": False, "code": "the user text"}, "oops", None, {"ok": 1, "text": "x"}):
        lab.reply = junk
        assert call() == {"ok": False, "code": "E_UNKNOWN"}, junk


def test_a_lab_that_raises_is_e_internal_and_the_message_is_not_returned(lab):
    lab.reply = RuntimeError("the user text leaked")
    got = call()
    assert got == {"ok": False, "code": "E_INTERNAL"} and "leaked" not in json.dumps(got)


def test_a_reply_that_is_not_a_reply_is_e_response(lab):
    for bad in ({"ok": True, "text": 5, "finish": "stop"}, {"ok": True, "text": "x", "finish": "done"}, {"ok": True, "finish": "stop"}):
        lab.reply = bad
        assert call() == {"ok": False, "code": "E_RESPONSE"}, bad


def test_the_system_and_the_user_text_must_be_text(lab):
    assert ir.complete(SONNET_ID, None, "u", accepted=[HASHES[SONNET_ID]], deadline_ms=1) == {"ok": False, "code": "E_USAGE"}
    assert ir.complete(SONNET_ID, "s", 5, accepted=[HASHES[SONNET_ID]], deadline_ms=1) == {"ok": False, "code": "E_USAGE"}
    assert lab.calls == []


def test_an_unknown_route_is_e_route(lab):
    assert ir.complete("acct-nowhere", "s", "u", accepted=[], deadline_ms=1) == {"ok": False, "code": "E_ROUTE"}


def test_the_account_path_reads_no_key_and_the_http_path_never_reaches_the_lab(monkeypatch, lab):
    def refuse(*a, **k):
        raise AssertionError("a key was looked up")
    monkeypatch.setattr(ir, "_key", refuse)
    monkeypatch.setenv("WB_RUNTIME_KEY_OPENROUTER_API_KEY", "sk-or-v1-fictional")
    assert call()["ok"] is True
    monkeypatch.setattr(ir, "_key", lambda name, root: None)           # the http route with no key: E_KEY, and the lab is not asked
    lab.calls.clear()
    assert ir.complete(DEEPSEEK_ID, "s", "u", accepted=[HASHES[DEEPSEEK_ID]], deadline_ms=1) == {"ok": False, "code": "E_KEY"} and lab.calls == []


def test_the_lab_is_imported_when_an_account_call_first_needs_it_and_not_before():
    source = (REPO / "runtime" / "interpreter_route.py").read_text(encoding="utf-8")
    top = source.split("class RouteError")[0]
    assert "import lab" not in top and 'import_module("lab")' in source


# --- what a measurement on an account route writes ----------------------------------------------------------------------------------------

class AccountCli(Cli):
    def run_route(self, route, *argv):
        code = measure.main(["--corpus", str(self.corpus), "--route", route, *argv, "--evidence-dir", str(self.evidence)])
        out = self.capsys.readouterr()
        return code, out.out, out.err


@pytest.fixture
def acli(tmp_path, monkeypatch, capsys):
    return AccountCli(tmp_path, monkeypatch, capsys, ITEMS)


def test_billing_comes_from_the_kind_of_the_route():
    assert measure.billing_of(raw_row(SONNET_ID)) == measure.billing_of(raw_row(HAIKU_ID)) == "subscription"
    assert measure.billing_of(raw_row(DEEPSEEK_ID)) == "metered"


def test_an_account_event_says_subscription_and_every_item_line_has_a_null_cost(acli):
    code, out, err = acli.run_route(SONNET_ID, "--json", "--jobs", "3")
    assert code == 0, err
    (path,) = acli.files()
    body = acli.lines(path)
    assert body[0]["billing"] == "subscription" and body[0]["model"] == "claude-sonnet-5-5" and body[0]["route"] == SONNET_ID
    assert body[0]["route_sha256"] == HASHES[SONNET_ID]
    items = body[1:]
    assert items and all(line["cost_usd"] is None for line in items)
    called = [line for line in items if line["latency_ms"] is not None]
    assert called and all(line["usage"] is not None for line in called), "a line of a call carries the usage the call reported (the proxy figure is computed from it)"
    assert all(line["upstream"] == "anthropic" for line in called), "the upstream of an account line is the row's pin"
    assert acli.problems(path) == []


def test_vacuity_a_metered_route_on_the_same_run_writes_metered_and_a_cost(acli):
    code, out, err = acli.run_route(DEEPSEEK_ID, "--json", "--jobs", "3")
    assert code == 0, err
    (path,) = acli.files()
    body = acli.lines(path)
    assert body[0]["billing"] == "metered" and body[0]["route_sha256"] == HASHES[DEEPSEEK_ID]
    assert any(line["cost_usd"] is not None for line in body[1:])


def test_the_validator_refuses_what_the_account_run_would_get_wrong(acli, tmp_path):
    acli.run_route(SONNET_ID, "--json", "--jobs", "3")
    (path,) = acli.files()
    body = acli.lines(path)
    wrong_billing = [dict(body[0], billing="metered")] + body[1:]
    planted = tmp_path / "planted-billing.jsonl"
    planted.write_text("".join(json.dumps(line, sort_keys=True) + "\n" for line in wrong_billing), encoding="utf-8")
    assert acli.problems(planted) != []
    priced = [body[0]] + [dict(body[1], cost_usd=0.001)] + body[2:]
    planted_cost = tmp_path / "planted-cost.jsonl"
    planted_cost.write_text("".join(json.dumps(line, sort_keys=True) + "\n" for line in priced), encoding="utf-8")
    assert acli.problems(planted_cost) != []


def test_the_cost_of_a_call_on_an_account_route_is_none_whatever_the_usage():
    usage = {"input": 1000, "output": 200, "cache_read": 5000, "cache_write": None}
    table = {"models": {"claude-sonnet-5-5": {"input_usd_per_mtok": 3, "output_usd_per_mtok": 15, "cache_read_usd_per_mtok": 0.3}}}
    assert evidence.cost_usd(usage, raw_row(SONNET_ID), table) is None
    http = dict(raw_row(DEEPSEEK_ID))
    priced = {"models": {http["model"]: {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 5.0, "cache_read_usd_per_mtok": 0.1}}}
    assert evidence.cost_usd(usage, http, priced) == pytest.approx((1000 * 1.0 + 200 * 5.0 + 5000 * 0.1) / 1e6)     # vacuity: the http route is priced
