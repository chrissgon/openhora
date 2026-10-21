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

KEY_NAME = "WB_RUNTIME_KEY_OPENROUTER_API_KEY"
OTHER_SERVICE_KEY = "sk-ant-oat01-AAAA"      # security-scan: allow secret-assignment -- a fictional value in the shape of another service's key, to be refused
RIGHT_KEY = "sk-or-v1-test"
DEEPSEEK_HASH = "1365ea7c385a28f38103f9b2d3b959faee6012691ed6ef50478a560d1014c9fd"     # the committed row, computed offline before this package
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
    return ir.load(workbench(tmp_path, list(rows)))


@pytest.fixture
def no_key(monkeypatch, tmp_path):
    monkeypatch.delenv(KEY_NAME, raising=False)
    monkeypatch.setenv("OPENHORA_CREDENTIALS_DIR", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))


# --- guard 1: no Claude model on an HTTP route ----------------------------------------------------------------------------------------------

# (what is changed, the Claude value, the same field with a clean value): the clean twin proves the refusal is the guard's and nothing else's
CASES = [("upstream_model", "anthropic/claude-haiku-4.5", "vendor/model-mini"),
         ("model", "openrouter/anthropic/claude-sonnet-5.5", "openrouter/vendor/model-big"),
         ("pin", "anthropic", "provider-a"),
         ("upstream_model", "x/Claude-mini", "x/model-mini"),
         ("model", "openrouter/x/CLAUDE-big", "openrouter/x/model-big"),
         ("pin", "Anthropic", "provider-b"),
         ("upstream_model", "claude", "vendor/model-mini")]


@pytest.mark.parametrize("field,claude,clean", CASES, ids=[f"{c[0]}={c[1]}" for c in CASES])
def test_a_route_that_names_a_claude_model_refuses_the_whole_file(tmp_path, field, claude, clean):
    other = row(id="other-route")
    with pytest.raises(ir.RouteError):
        loads(tmp_path, other, row(**{field: claude}))
    with pytest.raises(ir.RouteError):
        loads(tmp_path, row(**{field: claude}), other)          # in either order: no route of the file runs
    assert [r["id"] for r in loads(tmp_path, other, row(**{field: clean}))["routes"]] == ["other-route", ROW["id"]]     # vacuity: the clean twin loads


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
    assert [r["id"] for r in raw["routes"]] == ["or-deepseek-v4.1-flash"]
    assert [r["kind"] for r in raw["routes"]] == ["http"] and [r["key_prefix"] for r in raw["routes"]] == ["sk-or-v1-"]


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


def test_the_references_are_at_most_one(tmp_path):
    with pytest.raises(ir.RouteError):
        loads(tmp_path, row(reference=True), row(id="other-route", reference=True))
    assert [r["reference"] for r in loads(tmp_path / "a", row(reference=True), row(id="other-route"))["routes"]] == [True, False]
    assert [r["reference"] for r in loads(tmp_path / "b", row(), row(id="other-route"))["routes"]] == [False, False]


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
