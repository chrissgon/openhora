"""The guards of runtime/interpreter_route.py (package ACCT-B, SPEC-ACCT-ROUTE sections 3 and 7): no Claude model on an HTTP route, and KEY-SHAPE (a key
that does not have the shape of the service it is sent to never leaves the process). Every oracle reads the raw routes file or the raw input with the
literals written here, never a list of the module under test. Offline; every key is fictional and matches no real credential format.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_route_guards.py
"""
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
import interpreter_route as ir  # noqa: E402
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

KEY_NAME = "WB_RUNTIME_KEY_OPENROUTER_API_KEY"
OTHER_SERVICE_KEY = "sk-ant-oat01-AAAA"      # security-scan: allow secret-assignment -- a fictional value in the shape of another service's key, to be refused
RIGHT_KEY = "sk-or-v1-test"
DEEPSEEK_HASH = PINNED_HASHES["route_or_deepseek_v4_1_flash"]     # the committed row, computed offline before this package (scripts/tests/pinned_hashes.json)
ROUTES = json.loads((REPO / "runtime" / "interpreter_routes.json").read_text(encoding="utf-8"))
ROW = ROUTES["routes"][0]
CLAUDE_WORDS = ("claude", "anthropic")        # the test's own list


def by_path(rel, name):
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / rel)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


status_module = by_path("evals/interpreter_status.py", "workbench_interpreter_status_for_acct_b")


def workbench(tmp_path, rows):
    root = tmp_path / "wb"
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "secrets.json").write_text((REPO / "runtime" / "secrets.json").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "runtime" / "interpreter_routes.json").write_text(json.dumps({"v": 1, "routes": rows}), encoding="utf-8")
    return str(root)


def row(**over):
    out = copy.deepcopy(ROW)
    out.update(over)
    return out


def loads(tmp_path, *rows):
    """The file with these rows, loaded. The loader wants exactly one reference: the first row is made the reference when none is."""
    rows = list(rows)
    if not any(r["reference"] for r in rows):
        rows[0] = dict(rows[0], reference=True)
    return ir.load(workbench(tmp_path, rows))


@pytest.fixture
def no_key(monkeypatch, tmp_path):
    monkeypatch.delenv(KEY_NAME, raising=False)
    monkeypatch.setenv("OPENHORA_CREDENTIALS_DIR", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))


# --- guard 1: no Claude model on an HTTP route ----------------------------------------------------------------------------------------------

# (what is changed, the Claude value, the same field with a clean value): the clean twin proves the refusal is the guard's and nothing else's. The
# clean value is one the allow-list admits (a model of the allowed vendor under the route's own prefix), so the twin loads. Only the vendor-word
# layer is tested here; the allow-list has its own test below.
def twin(field, value):
    """The row with `field` set to `value`; an upstream model is set with its matching `model`."""
    if field == "upstream_model":
        return row(upstream_model=value, model="openrouter/" + value)
    return row(**{field: value})


CASES = [("upstream_model", "anthropic/claude-haiku-4.5", "deepseek/model-mini"),
         ("model", "openrouter/anthropic/claude-sonnet-5.5", "openrouter/deepseek/deepseek-v4.1-flash"),
         ("pin", "anthropic", "provider-a"),
         ("upstream_model", "x/Claude-mini", "deepseek/model-mini"),
         ("model", "openrouter/x/CLAUDE-big", "openrouter/deepseek/deepseek-v4.1-flash"),
         ("pin", "Anthropic", "provider-b"),
         ("upstream_model", "claude", "deepseek/model-mini")]


@pytest.mark.parametrize("field,claude,clean", CASES, ids=[f"{c[0]}={c[1]}" for c in CASES])
def test_a_route_that_names_a_claude_model_refuses_the_whole_file(tmp_path, field, claude, clean):
    other = row(id="other-route")
    with pytest.raises(ir.RouteError):
        loads(tmp_path, other, twin(field, claude))
    with pytest.raises(ir.RouteError):
        loads(tmp_path, twin(field, claude), other)          # in either order: no route of the file runs
    assert [r["id"] for r in loads(tmp_path, other, twin(field, clean))["routes"]] == ["other-route", ROW["id"]]     # vacuity: the clean twin loads


# --- the allow-list: a model of a vendor that is not named never loads, whatever its pin ----------------------------------------------------

ALLOWED = [("openrouter/auto", "amazon-bedrock"), ("@preset/fast", "google-vertex"), ("@preset/x", "deepinfra"), ("mistralai/x", "deepinfra"),
           ("openai/o3-mini", "azure"), ("openai/chatgpt-4o-latest", "azure"), ("google/gemma-3", "google-vertex"), ("~google/gemini-flash-latest", "google-vertex"), ("google/gemini", "google-vertex"), ("Google/Gemini-x", "google-vertex"), ("~anthropic/claude-latest", "amazon-bedrock"), ("deepseek", "deepinfra"), ("DeepSeek/x", "deepinfra"),
           (" deepseek/x", "deepinfra"), ("x/deepseek/y", "deepinfra"), ("", "deepinfra")]


@pytest.mark.parametrize("upstream,pin", ALLOWED, ids=[f"{u or 'empty'}@{p}" for u, p in ALLOWED])
def test_an_upstream_model_outside_the_allow_list_is_refused_whatever_its_pin(tmp_path, upstream, pin):
    """The test's own literal: the only allowed start is the vendor of the shipped row, lower case, followed by a slash."""
    with pytest.raises(ir.RouteError):
        loads(tmp_path, row(upstream_model=upstream, model="openrouter/" + upstream, pin=pin))
    with pytest.raises(ir.RouteError):
        loads(tmp_path / "b", row(), row(id="other-route", upstream_model=upstream, model="openrouter/" + upstream, pin=pin))


@pytest.mark.parametrize("model", ["deepseek/deepseek-v4.1-flash", "openrouter/deepseek/other", "openrouter/auto", "other/deepseek/deepseek-v4.1-flash",
                                   "openrouter/ deepseek/deepseek-v4.1-flash"])
def test_a_model_that_is_not_the_prefix_plus_the_upstream_model_is_refused(tmp_path, model):
    with pytest.raises(ir.RouteError):
        loads(tmp_path, row(model=model))


def test_vacuity_a_model_of_the_allowed_vendor_under_the_prefix_loads_and_the_allow_list_is_the_literal_one(tmp_path):
    assert [r["upstream_model"] for r in loads(tmp_path, row(upstream_model="deepseek/another-model", model="openrouter/deepseek/another-model"))["routes"]] == ["deepseek/another-model"]
    assert loads(tmp_path / "b", row())["routes"][0]["upstream_model"] == "deepseek/deepseek-v4.1-flash"
    assert ir.HTTP_MODELS == {"openrouter.ai": ("deep" + "seek/", "google/gemini-", "openai/gpt-")} and ir.MODEL_PREFIX == {"openrouter.ai": "openrouter/"}      # S41-10: the daily vendor and the two fallback families
    two = loads(tmp_path / "c", row(), row(id="fallback-a", upstream_model="google/gemini-x", model="openrouter/google/gemini-x", pin="google-vertex"),
                row(id="fallback-b", upstream_model="openai/gpt-x", model="openrouter/openai/gpt-x", pin="azure"))
    assert [r["upstream_model"] for r in two["routes"]] == ["deepseek/deepseek-v4.1-flash", "google/gemini-x", "openai/gpt-x"], "a model of each of the three families loads"



def test_a_route_that_is_asked_for_in_a_file_with_a_claude_row_is_a_route_error(tmp_path, no_key, monkeypatch):
    monkeypatch.setenv(KEY_NAME, RIGHT_KEY)
    root = workbench(tmp_path, [row(), row(id="or-claude-x", model="openrouter/anthropic/claude-x", upstream_model="anthropic/claude-x", pin="anthropic")])
    seen = []
    got = ir.complete(ROW["id"], "s", "u", accepted=[], deadline_ms=1000, root=root, run=lambda argv, stdin=None: seen.append(argv))
    assert got == {"ok": False, "code": "E_ROUTE"} and seen == []


def test_the_committed_routes_file_holds_no_http_row_that_names_claude():
    raw = json.loads((REPO / "runtime" / "interpreter_routes.json").read_text(encoding="utf-8"))
    http = [r for r in raw["routes"] if r["kind"] == "http"]
    assert http, "the oracle has rows to read"
    assert [r["id"] for r in http if any(w in json.dumps(r).lower() for w in CLAUDE_WORDS)] == []
    assert [r["id"] for r in raw["routes"]] == ["or-deepseek-v4.1-flash", "acct-claude-sonnet-5.5", "acct-claude-haiku-4.5", "or-gemini-3.5-flash-lite", "or-gpt-6-luna"]      # S41-10: the two fallback rows, last
    assert [r["id"] for r in raw["routes"] if r["kind"] == "account"] == ["acct-claude-sonnet-5.5", "acct-claude-haiku-4.5"]
    assert [r["kind"] for r in raw["routes"]] == ["http", "account", "account", "http", "http"] and [r["key_prefix"] for r in http] == ["sk-or-v1-"] * 3
    assert all("key" not in r and "key_prefix" not in r for r in raw["routes"] if r["kind"] == "account"), "an account row has no key"


def test_vacuity_the_raw_file_oracle_finds_a_claude_row_in_a_planted_file():
    planted = {"routes": [dict(ROW), dict(ROW, id="or-claude-haiku-4.5", upstream_model="anthropic/claude-haiku-4.5")]}
    assert [r["id"] for r in planted["routes"] if any(w in json.dumps(r).lower() for w in CLAUDE_WORDS)] == ["or-claude-haiku-4.5"]


# --- the DeepSeek row keeps its hash --------------------------------------------------------------------------------------------------------

def test_the_deepseek_route_hash_is_the_literal_from_both_modules():
    assert ir.route_sha256(ROW) == DEEPSEEK_HASH
    assert status_module.route_sha256(ROW) == DEEPSEEK_HASH
    shown = {"allow_fallbacks": False, "base_url": "https://openrouter.ai/api/v1", "cache_breakpoint": False, "data_collection": "deny",
             "id": "or-deepseek-v4.1-flash", "model": "deepseek/deepseek-v4.1-flash", "pin": "deepinfra", "zdr": False}
    assert hashlib.sha256(json.dumps(shown, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() == DEEPSEEK_HASH
    assert ir.stdin_route(ROW) == shown, "kind and key_prefix are not part of what the provider is shown of a route"


def test_vacuity_a_changed_route_changes_the_hash_in_both_modules():
    assert ir.route_sha256(row(pin="provider-a")) != DEEPSEEK_HASH and status_module.route_sha256(row(pin="provider-a")) != DEEPSEEK_HASH


# --- guard 2: KEY-SHAPE in the file -------------------------------------------------------------------------------------------------------

def test_the_key_shapes_table_is_closed_and_literal():
    assert ir.KEY_SHAPES == {"openrouter.ai": "sk-or-v1-"}


@pytest.mark.parametrize("over", [{"base_url": "https://models.example/v1"}, {"base_url": "https://api.openrouter.ai/v1"}, {"base_url": "https://openrouter.ai.example/v1"},
                                  {"base_url": "https://example.com/openrouter.ai"}],
                         ids=["unlisted host", "subdomain of a listed host", "listed host as a prefix", "listed host in the path"])
def test_a_host_outside_key_shapes_is_refused(tmp_path, over):
    with pytest.raises(ir.RouteError):
        loads(tmp_path, row(**over))


@pytest.mark.parametrize("prefix", ["sk-ant-", "sk-or-v1", "sk-or-v1-x", "SK-OR-V1-", "sk-", "x", " "], ids=repr)
def test_a_key_prefix_that_is_not_the_one_of_its_host_is_refused(tmp_path, prefix):
    with pytest.raises(ir.RouteError):
        loads(tmp_path, row(key_prefix=prefix))


def test_vacuity_the_listed_host_with_its_prefix_loads_and_the_host_is_read_in_lower_case(tmp_path):
    assert loads(tmp_path, row())["routes"][0]["key_prefix"] == "sk-or-v1-"
    assert loads(tmp_path / "up", row(base_url="https://OpenRouter.AI/api/v1"))["routes"][0]["id"] == ROW["id"]


def test_the_references_are_exactly_one(tmp_path):
    with pytest.raises(ir.RouteError):
        loads(tmp_path, row(reference=True), row(id="other-route", reference=True))
    with pytest.raises(ir.RouteError):
        ir.load(workbench(tmp_path / "none", [row(), row(id="other-route")]))
    assert [r["reference"] for r in loads(tmp_path / "a", row(reference=True), row(id="other-route"))["routes"]] == [True, False]
    assert [r["reference"] for r in loads(tmp_path / "b", row(), row(id="other-route"))["routes"]] == [True, False]


# --- guard 2: KEY-SHAPE in the call --------------------------------------------------------------------------------------------------------

def counting():
    calls = []

    def run(argv, stdin=None):
        calls.append((argv, stdin))
        return subprocess.CompletedProcess(argv, 0, json.dumps({"v": 1, "text": "t", "finish": "stop", "usage": {}, "latency_ms": 3, "upstream": "deepinfra"}), "")
    return run, calls


def ask(run):
    return ir.complete(ROW["id"], "system text", "user text", accepted=[DEEPSEEK_HASH], deadline_ms=2000, run=run)


def test_a_key_of_another_service_in_the_environment_is_a_key_error_and_the_provider_is_never_started(no_key, monkeypatch):
    monkeypatch.setenv(KEY_NAME, OTHER_SERVICE_KEY)
    run, calls = counting()
    assert ask(run) == {"ok": False, "code": "E_KEY"}
    assert calls == []


@pytest.mark.parametrize("value", ["sk-or-v1", "sk-or-v2-test", "SK-OR-V1-test", "x sk-or-v1-test", "bearer sk-or-v1-test", "-or-v1-test"])
def test_a_key_that_nearly_has_the_shape_is_refused(no_key, monkeypatch, value):
    monkeypatch.setenv(KEY_NAME, value)
    run, calls = counting()
    assert ask(run) == {"ok": False, "code": "E_KEY"} and calls == []


def test_vacuity_a_key_of_the_shape_starts_the_provider_once_with_the_prefix_in_the_request(no_key, monkeypatch):
    monkeypatch.setenv(KEY_NAME, RIGHT_KEY)
    run, calls = counting()
    got = ask(run)
    assert got["ok"] is True and got["text"] == "t" and len(calls) == 1
    sent = json.loads(calls[0][1])
    assert sent["key_prefix"] == "sk-or-v1-" and RIGHT_KEY not in calls[0][1] and OTHER_SERVICE_KEY not in calls[0][1]


def test_the_key_error_leaves_only_a_code(no_key, monkeypatch):
    monkeypatch.setenv(KEY_NAME, OTHER_SERVICE_KEY)
    run, _ = counting()
    assert OTHER_SERVICE_KEY not in json.dumps(ask(run))
