"""runtime/interpreter_route.py and runtime/interpreter_routes.json (package IX-2b): the routes file, the hash a route is accepted by, and the one
function that calls the provider `model:text` with a stand-in for the process start. The real provider is started only with --dry-run (no key read,
no connection). Every key is fictional; nothing reaches a network; the keyring is the null backend of the root conftest.py.
"""
import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
import interpreter_route as ir  # noqa: E402
import project_config  # noqa: E402

KEY_NAME = "WB_RUNTIME_KEY_OPENROUTER_API_KEY"
FAKE = "sk-test-not-a-key"
BODY_MARKER = "zz-planted-body-marker-91"
PROMPT = "zz-planted-prompt-marker-47"
ROUTES = json.loads((REPO / "runtime" / "interpreter_routes.json").read_text(encoding="utf-8"))
EXPECTED = {   # the specification's table, written out again here
    "or-deepseek-v4.1-flash": ("openrouter/deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash", "deepinfra", False, False),
    "or-claude-haiku-4.5": ("openrouter/anthropic/claude-haiku-4.5", "anthropic/claude-haiku-4.5", "anthropic", True, False),
    "or-claude-sonnet-5.5": ("openrouter/anthropic/claude-sonnet-5.5", "anthropic/claude-sonnet-5.5", "anthropic", True, True),
}


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@pytest.fixture
def no_key(monkeypatch, tmp_path):
    monkeypatch.delenv(KEY_NAME, raising=False)
    monkeypatch.setenv("OPENHORA_CREDENTIALS_DIR", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))


@pytest.fixture
def key(monkeypatch, no_key):
    monkeypatch.setenv(KEY_NAME, FAKE)


def workbench(tmp_path, doc):
    root = tmp_path / "wb"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "secrets.json").write_text((REPO / "runtime" / "secrets.json").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "runtime" / "interpreter_routes.json").write_text(json.dumps(doc), encoding="utf-8")
    return str(root)


# --- the file -----------------------------------------------------------------------------------------------------

def test_the_shipped_routes_are_the_three_of_the_specification():
    doc = ir.load()
    assert doc["v"] == 1 and {r["id"] for r in doc["routes"]} == set(EXPECTED)
    for r in doc["routes"]:
        model, upstream, pin, breakpoint_on, reference = EXPECTED[r["id"]]
        assert (r["model"], r["upstream_model"], r["pin"], r["cache_breakpoint"], r["reference"]) == (model, upstream, pin, breakpoint_on, reference)
        assert r["base_url"] == "https://openrouter.ai/api/v1" and r["allow_fallbacks"] is False and r["data_collection"] == "deny"
        assert r["key"] == KEY_NAME and isinstance(r["zdr"], bool) and r["retention"].strip()
    assert [r["id"] for r in doc["routes"] if r["reference"]] == ["or-claude-sonnet-5.5"]


def test_every_route_model_is_priced_and_the_key_is_registered_and_this_module_reads_it():
    prices = json.loads((REPO / "runtime" / "prices.json").read_text(encoding="utf-8"))["models"]
    secrets = {s["name"]: s for s in json.loads((REPO / "runtime" / "secrets.json").read_text(encoding="utf-8"))["secrets"]}
    for r in ROUTES["routes"]:
        assert r["model"] in prices and r["key"] in secrets
    assert "runtime/interpreter_route.py" in secrets[KEY_NAME]["readers"] and "runtime/ops_core.py" in secrets[KEY_NAME]["readers"]


def test_an_id_a_zdr_claim_and_a_retention_sentence_are_consistent():
    """A route claims zero retention only with a retention sentence that says so (the sentence is what the widening card quotes)."""
    for r in ROUTES["routes"]:
        assert re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", r["id"])
        assert r["zdr"] is False or "zero" in r["retention"].lower()


def mutations():
    def setv(k, v):
        def f(doc):
            doc["routes"][0][k] = v
        return f

    def drop(k):
        def f(doc):
            del doc["routes"][0][k]
        return f
    return [("extra key", lambda d: d["routes"][0].update(extra=1)), ("missing key", drop("retention")), ("missing top key", lambda d: d.pop("v")),
            ("version", lambda d: d.update(v=2)), ("no routes", lambda d: d.update(routes=[])),
            ("bad id", setv("id", "Bad_Id")), ("long id", setv("id", "a" * 65)), ("id starts with a dot", setv("id", ".x")),
            ("duplicate id", lambda d: d["routes"][1].update(id=d["routes"][0]["id"])),
            ("http", setv("base_url", "http://openrouter.example/api/v1")), ("login in the address", setv("base_url", "https://u:p@x.example/v1")),
            ("query", setv("base_url", "https://x.example/v1?a=1")), ("no host", setv("base_url", "https:///v1")),
            ("fallbacks", setv("allow_fallbacks", True)), ("data collection", setv("data_collection", "allow")),
            ("zdr text", setv("zdr", "yes")), ("key not registered", setv("key", "NOT_A_REGISTERED_SECRET")), ("empty retention", setv("retention", " ")),
            ("pin empty", setv("pin", "")), ("pin null", setv("pin", None)), ("pin blank", setv("pin", "  ")),
            ("subscription token", setv("key", "WB_RUNTIME_KEY_CLAUDE_CODE_OAUTH_TOKEN")), ("no reference", lambda d: [r.update(reference=False) for r in d["routes"]]),
            ("two references", lambda d: [r.update(reference=True) for r in d["routes"]]), ("not a route", lambda d: d["routes"].append("x"))]


@pytest.mark.parametrize("name,mutate", mutations(), ids=[m[0] for m in mutations()])
def test_a_routes_file_that_breaks_a_rule_is_refused(tmp_path, name, mutate):
    doc = copy.deepcopy(ROUTES)
    mutate(doc)
    with pytest.raises(ir.RouteError):
        ir.load(workbench(tmp_path, doc))


def test_a_registered_secret_that_this_module_does_not_read_is_never_a_route_key(tmp_path, key, monkeypatch):
    """The allow-list and the readers both stand: the interpreter's key with this module removed from its readers, and another registered secret."""
    secrets = json.loads((REPO / "runtime" / "secrets.json").read_text(encoding="utf-8"))
    root = Path(workbench(tmp_path, ROUTES))
    entry = next(e for e in secrets["secrets"] if e["name"] == KEY_NAME)
    entry["readers"] = [r for r in entry["readers"] if r != "runtime/interpreter_route.py"]
    (root / "runtime" / "secrets.json").write_text(json.dumps(secrets), encoding="utf-8")
    with pytest.raises(ir.RouteError):
        ir.load(str(root))
    assert ir.ALLOWED_KEYS == {KEY_NAME}


def test_a_routes_file_naming_another_secret_sends_nothing(tmp_path, monkeypatch, key):
    """The probe of the review: a route whose key is the subscription token; its value is set, and no process is started with it."""
    doc = copy.deepcopy(ROUTES)
    doc["routes"][2]["key"] = "WB_RUNTIME_KEY_CLAUDE_CODE_OAUTH_TOKEN"
    monkeypatch.setenv("WB_RUNTIME_KEY_CLAUDE_CODE_OAUTH_TOKEN", "token-not-for-a-model")
    seen = []
    got = ir.complete("or-claude-sonnet-5.5", "s", "u", accepted=[], deadline_ms=1000, run=runner(seen=seen), root=workbench(tmp_path, doc))
    assert got == {"ok": False, "code": "E_ROUTE"} and seen == []


def test_vacuity_the_unchanged_file_loads_and_a_missing_or_broken_file_is_refused(tmp_path):
    assert ir.load(workbench(tmp_path, ROUTES))["routes"] == ROUTES["routes"]
    root = Path(workbench(tmp_path / "b", ROUTES))
    (root / "runtime" / "interpreter_routes.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ir.RouteError):
        ir.load(str(root))
    (root / "runtime" / "interpreter_routes.json").unlink()
    with pytest.raises(ir.RouteError):
        ir.load(str(root))


# --- what the provider is shown -------------------------------------------------------------------------------------

def test_the_route_the_provider_sees_and_its_hash():
    r = ROUTES["routes"][0]
    shown = ir.stdin_route(r)
    assert shown == {"id": r["id"], "base_url": "https://openrouter.ai/api/v1", "model": r["upstream_model"], "pin": r["pin"], "allow_fallbacks": False,
                     "data_collection": "deny", "zdr": r["zdr"], "cache_breakpoint": r["cache_breakpoint"]}
    assert ir.route_sha256(r) == hashlib.sha256(canon(shown)).hexdigest()
    other = dict(r, upstream_model="other/model")
    assert ir.route_sha256(other) != ir.route_sha256(r)
    assert ir.route_sha256(dict(r, retention="another sentence")) == ir.route_sha256(r)    # the hash covers what the provider sees


# --- the call -------------------------------------------------------------------------------------------------------

PROVIDER_OUT = {"v": 1, "text": "a reply", "finish": "stop", "usage": {"input": 9, "output": 3, "cache_read": None, "cache_write": 0}, "latency_ms": 41,
                "upstream": "anthropic", "debug": BODY_MARKER}


def runner(stdout=None, stderr="", code=0, seen=None):
    def run(argv, stdin=None):
        if seen is not None:
            seen.append((argv, stdin))
        return subprocess.CompletedProcess(argv, code, json.dumps(PROVIDER_OUT if stdout is None else stdout), stderr)
    return run


def call(run, route_id="or-claude-sonnet-5.5", **kw):
    r = next(x for x in ROUTES["routes"] if x["id"] == route_id)
    return ir.complete(route_id, "system " + PROMPT, "user " + PROMPT, accepted=[ir.route_sha256(r)], deadline_ms=6000, run=run, **kw)


def test_a_reply_comes_back_with_the_known_keys_only(key):
    seen = []
    got = call(runner(seen=seen))
    assert got == {"ok": True, "text": "a reply", "finish": "stop", "usage": {"input": 9, "output": 3, "cache_read": None, "cache_write": 0},
                   "latency_ms": 41, "upstream": "anthropic"}
    argv, stdin = seen[0]
    assert argv[-2:] == [str(REPO / "providers" / "model" / "chat-http.py"), "complete"] and FAKE not in " ".join(argv) and PROMPT not in " ".join(argv)
    sent = json.loads(stdin)
    r = ROUTES["routes"][2]
    assert sent == {"v": 1, "route": ir.stdin_route(r), "accepted": [ir.route_sha256(r)],
                    "params": {"temperature": 0, "max_tokens": 300, "reasoning": "off"}, "system": "system " + PROMPT, "user": "user " + PROMPT, "deadline_ms": 6000}


def test_the_key_reaches_the_provider_process_alone_and_the_start_is_given_a_deadline(key, monkeypatch):
    resolve = project_config.resolver(str(REPO))
    spy = {}

    def fake_call(cls, verb, args, **kw):
        spy.update(cls=cls, verb=verb, args=args, **kw)
        return dict(PROVIDER_OUT)

    monkeypatch.setattr(resolve, "call", fake_call)
    monkeypatch.setenv("SOME_OTHER_SECRET", "must-not-pass")
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-pass-either")
    assert call(None)["ok"] is True
    assert (spy["cls"], spy["verb"], spy["args"]) == ("model:text", "complete", []) and spy["timeout"] == 6.5
    assert spy["env"]["MODEL_TEXT_KEY"] == FAKE and "SOME_OTHER_SECRET" not in spy["env"] and "OPENROUTER_API_KEY" not in spy["env"]
    assert KEY_NAME not in spy["env"] and set(spy["env"]) <= set(resolve.ENV_MINIMUM) | {"MODEL_TEXT_KEY", "MODEL_TEXT_PROVIDER", "MODEL_PROVIDER"}


def test_without_a_key_nothing_is_started(no_key):
    seen = []
    assert call(runner(seen=seen)) == {"ok": False, "code": "E_KEY"} and seen == []


def test_an_unknown_route_or_a_missing_file_is_a_route_error(key, tmp_path):
    assert ir.complete("nope", "s", "u", accepted=[], deadline_ms=1000, run=runner()) == {"ok": False, "code": "E_ROUTE"}
    assert ir.complete("or-claude-sonnet-5.5", "s", "u", accepted=[], deadline_ms=1000, run=runner(), root=str(tmp_path)) == {"ok": False, "code": "E_ROUTE"}


@pytest.mark.parametrize("stderr,code", [("chat-http: E_RATE\n", "E_RATE"), ("noise\nchat-http: E_ROUTE\n", "E_ROUTE"), ("chat-http: E_PIN\n\n", "E_PIN"),
                                         ("chat-http: e_rate\n", "E_UNKNOWN"), ("boom\n", "E_UNKNOWN"), ("", "E_UNKNOWN"), ("chat-http: E_HTTP extra\n", "E_UNKNOWN")])
def test_a_failure_is_the_code_of_the_last_line_of_stderr_and_nothing_else(key, stderr, code):
    got = call(runner(stdout="{}", stderr=stderr + "", code=1))
    assert got == {"ok": False, "code": code}


def test_a_timeout_and_a_provider_that_prints_a_body_leave_only_a_code(key):
    def slow(argv, stdin=None):
        raise subprocess.TimeoutExpired(argv, 1)

    assert call(slow) == {"ok": False, "code": "E_TIMEOUT"}
    leaky = call(runner(stdout="{}", stderr=BODY_MARKER + " " + FAKE + " " + PROMPT + "\n", code=1))
    assert leaky == {"ok": False, "code": "E_UNKNOWN"}
    before = call(runner(stdout="{}", stderr=BODY_MARKER + "\nchat-http: E_HTTP\n", code=1))
    assert before == {"ok": False, "code": "E_HTTP"}
    for result in (leaky, before):
        assert not [m for m in (BODY_MARKER, FAKE, PROMPT) if m in json.dumps(result)]


def test_vacuity_the_leak_oracle_sees_a_body_in_a_result():
    assert [m for m in (BODY_MARKER,) if m in json.dumps({"ok": False, "code": "E_UNKNOWN", "reason": BODY_MARKER})] == [BODY_MARKER]


@pytest.mark.parametrize("out", [{}, {"v": 2, "text": "t", "finish": "stop"}, {"v": 1, "text": 5, "finish": "stop"}, {"v": 1, "text": "t", "finish": "weird"}])
def test_a_reply_of_another_shape_is_an_invalid_response(key, out):
    assert call(runner(stdout=out)) == {"ok": False, "code": "E_RESPONSE"}


def test_the_real_provider_accepts_what_the_caller_builds_and_refuses_another_route(key):
    """The two sides agree on the hash: the real chat-http.py, started with --dry-run (no key read, no connection), prints what it would send."""
    results = []

    def dry(argv, stdin=None):
        done = subprocess.run(argv + ["--dry-run"], input=stdin, capture_output=True, text=True, timeout=30, check=False,
                              env={"PATH": "/usr/bin:/bin"})
        results.append(done)
        return done

    r = ROUTES["routes"][2]
    ir.complete(r["id"], "s", "u", accepted=[ir.route_sha256(r)], deadline_ms=6000, run=dry)
    assert results[0].returncode == 0
    would = json.loads(results[0].stdout)["would"]
    assert would["url"] == "https://openrouter.ai/api/v1/chat/completions" and would["body"]["model"] == "anthropic/claude-sonnet-5.5"
    assert would["body"]["provider"]["order"] == ["anthropic"] and "cache_control" in json.dumps(would["body"]["messages"][0])
    ir.complete(r["id"], "s", "u", accepted=[ir.route_sha256(ROUTES["routes"][0])], deadline_ms=6000, run=dry)    # another route's hash
    assert results[1].returncode == 3 and results[1].stderr == "chat-http: E_ROUTE\n"


def test_a_lone_surrogate_is_a_usage_error_and_the_request_never_leaves_in_an_exception(key):
    """The text goes to the provider ASCII-escaped, so it cannot fail to encode; the provider refuses it (E_USAGE); an encoding error from the start
    is caught and answered with the code alone."""
    seen = []
    r = ROUTES["routes"][2]
    ask = lambda run: ir.complete(r["id"], "s", "u \ud800 " + PROMPT, accepted=[ir.route_sha256(r)], deadline_ms=6000, run=run)  # noqa: E731
    assert ask(runner(seen=seen))["ok"] is True and seen[0][1].isascii() and "\\ud800" in seen[0][1]

    def real_dry(argv, stdin=None):
        return subprocess.run(argv + ["--dry-run"], input=stdin, capture_output=True, text=True, timeout=30, check=False, env={"PATH": "/usr/bin:/bin"})

    assert ask(real_dry) == {"ok": False, "code": "E_USAGE"}

    def broken(argv, stdin=None):
        raise UnicodeEncodeError("utf-8", "\ud800", 0, 1, "surrogates not allowed " + PROMPT)

    got = ask(broken)
    assert got == {"ok": False, "code": "E_USAGE"} and PROMPT not in json.dumps(got)
    assert ir.complete(r["id"], None, "u", accepted=[], deadline_ms=1000, run=runner()) == {"ok": False, "code": "E_USAGE"}
