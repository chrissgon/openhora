"""runtime/interpreter_route.py and the routes file (package ROUTE-REASONING): the optional route key `reasoning_off`.

`disable` (the default, a row without the key) and `minimal` are the closed values; any other refuses the routes file. The key is shown to the provider
and hashed only when the row has it, so the daily route's hash is the one the enabling entry holds, byte for byte; the first fallback row carries
`minimal` and its hash is the new pinned one. The body each value makes is checked by running the real provider with --dry-run (no key, no
connection). The literals are written here. Every name is fictional.
"""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
import interpreter_route as ir  # noqa: E402

RUNTIME = REPO / "runtime"
PINNED_HASHES = json.loads((REPO / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]
ROUTES = json.loads((RUNTIME / "interpreter_routes.json").read_text(encoding="utf-8"))
ENTRIES = json.loads((RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))
DEEPSEEK, GEMINI, LUNA = "or-deepseek-v4.1-flash", "or-gemini-3.5-flash-lite", "or-gpt-6-luna"
DEEPSEEK_HASH = PINNED_HASHES["route_or_deepseek_v4_1_flash"]      # the hash the enabling entries hold
GEMINI_HASH = PINNED_HASHES["route_or_gemini_3_5_flash_lite"]
LUNA_HASH = PINNED_HASHES["route_or_gpt_6_luna"]
CHAT = REPO / "providers" / "model" / "chat-http.py"


def canon_sha(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def row(route_id):
    return next(r for r in ROUTES["routes"] if r["id"] == route_id)


def root_with(tmp_path, doc):
    root = tmp_path / "wb"
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "secrets.json").write_text((RUNTIME / "secrets.json").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "runtime" / "interpreter_routes.json").write_text(json.dumps(doc), encoding="utf-8")
    return str(root)


def with_key(route_id, value):
    doc = copy.deepcopy(ROUTES)
    for r in doc["routes"]:
        if r["id"] == route_id:
            if value is None:
                r.pop("reasoning_off", None)
            else:
                r["reasoning_off"] = value
    return doc


def dry_body(route_id, root=None):
    """The body the real provider would send for the row, from --dry-run: no key is read and no connection is made."""
    shown = ir.stdin_route(ir.find(route_id, root))
    req = {"v": 1, "route": shown, "accepted": [ir.route_sha256(ir.find(route_id, root))], "key_prefix": "sk-test-",
           "params": {"temperature": 0, "max_tokens": 300, "reasoning": "off"}, "system": "A test system.", "user": "A test user line.", "deadline_ms": 5000}
    done = subprocess.run([sys.executable, str(CHAT), "complete", "--dry-run"], input=json.dumps(req), capture_output=True, text=True, check=False, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)["would"]["body"]


def test_only_the_first_fallback_row_carries_the_key_and_it_is_minimal():
    assert row(GEMINI)["reasoning_off"] == "minimal"
    assert "reasoning_off" not in row(DEEPSEEK) and "reasoning_off" not in row(LUNA)
    for r in ROUTES["routes"]:
        assert r.get("reasoning_off", "disable") in ("disable", "minimal")


def test_the_key_is_shown_to_the_provider_only_when_the_row_has_it():
    assert ir.stdin_route(ir.find(GEMINI))["reasoning_off"] == "minimal"
    assert "reasoning_off" not in ir.stdin_route(ir.find(DEEPSEEK)) and "reasoning_off" not in ir.stdin_route(ir.find(LUNA))
    assert set(ir.stdin_route(ir.find(DEEPSEEK))) == {"id", "base_url", "model", "pin", "allow_fallbacks", "data_collection", "zdr", "cache_breakpoint"}


def test_the_daily_routes_hash_is_the_one_the_pinned_file_and_the_active_enabling_entry_hold():
    assert ir.route_sha256(ir.find(DEEPSEEK)) == DEEPSEEK_HASH
    newest = ENTRIES[-1] if isinstance(ENTRIES, list) else ENTRIES["entries"][-1]
    assert newest["route"] == DEEPSEEK and newest["route_sha256"] == DEEPSEEK_HASH, "the active entry still holds the daily route's hash"
    assert ir.route_sha256(ir.find(LUNA)) == LUNA_HASH


def test_the_first_fallback_rows_hash_is_the_new_pinned_one_and_depends_on_the_key():
    assert ir.route_sha256(ir.find(GEMINI)) == GEMINI_HASH
    shown = ir.stdin_route(ir.find(GEMINI))
    assert canon_sha(shown) == GEMINI_HASH
    # the earlier row had no key and the pin_reply written before the probe (`google-vertex`; the row now holds the name the router gives, `google`)
    without = {k: v for k, v in shown.items() if k != "reasoning_off"}
    without["pin_reply"] = "google-vertex"
    assert canon_sha(without) == "d6c0cc655c62ac9a02706f109022aed4520a57f221f0bdc96beed79406f2d706", "the earlier hash is the row without the key"
    assert canon_sha(dict(shown, reasoning_off="disable")) != GEMINI_HASH


@pytest.mark.parametrize("value", ["disable", "minimal"])
def test_a_closed_value_loads_on_any_http_row_and_is_hashed_when_present(tmp_path, value):
    root = root_with(tmp_path, with_key(DEEPSEEK, value))
    loaded = ir.find(DEEPSEEK, root)
    assert loaded["reasoning_off"] == value
    assert ir.route_sha256(loaded) != DEEPSEEK_HASH, "a row that has the key is another route: an entry pins the one it was decided for"
    assert ir.stdin_route(loaded)["reasoning_off"] == value


@pytest.mark.parametrize("bad", ["none", "Minimal", "low", "", " ", None, True, 0, ["minimal"], {"effort": "minimal"}])
def test_an_unknown_value_refuses_the_whole_routes_file(tmp_path, bad):
    doc = copy.deepcopy(ROUTES)
    for r in doc["routes"]:
        if r["id"] == GEMINI:
            r["reasoning_off"] = bad
    with pytest.raises(ir.RouteError):
        ir.load(root_with(tmp_path, doc))


def test_the_status_script_hashes_the_key_as_the_runtime_does():
    import importlib.util
    name = "workbench_interpreter_status_for_reasoning_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / "evals" / "interpreter_status.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    status = sys.modules[name]
    for route_id in (DEEPSEEK, GEMINI, LUNA):
        assert status.route_sha256(row(route_id)) == ir.route_sha256(ir.find(route_id)), route_id
    assert status.route_sha256(row(GEMINI)) == GEMINI_HASH


def test_the_provider_sends_each_form_for_its_row():
    assert dry_body(GEMINI)["reasoning"] == {"effort": "minimal"}
    assert dry_body(DEEPSEEK)["reasoning"] == {"enabled": False}, "the daily route's body is today's"
    assert dry_body(LUNA)["reasoning"] == {"enabled": False}


def test_a_closed_value_through_the_loader_reaches_the_body(tmp_path):
    assert dry_body(DEEPSEEK, root_with(tmp_path, with_key(DEEPSEEK, "minimal")))["reasoning"] == {"effort": "minimal"}
    assert dry_body(GEMINI, root_with(tmp_path, with_key(GEMINI, "disable")))["reasoning"] == {"enabled": False}
    assert dry_body(GEMINI, root_with(tmp_path, with_key(GEMINI, None)))["reasoning"] == {"enabled": False}


def test_vacuity_a_planted_wrong_result_is_caught_by_each_oracle(tmp_path):
    # the daily route with the key added is not the pinned hash, and the first fallback row without it is not the new one
    planted = ir.route_sha256(ir.find(DEEPSEEK, root_with(tmp_path, with_key(DEEPSEEK, "minimal"))))
    assert planted != DEEPSEEK_HASH
    assert ir.route_sha256(ir.find(GEMINI, root_with(tmp_path / "b", with_key(GEMINI, None)))) != GEMINI_HASH
    # a body of the wrong form is not the right one for either row
    assert dry_body(GEMINI)["reasoning"] != {"enabled": False}
    assert dry_body(DEEPSEEK)["reasoning"] != {"effort": "minimal"}
    # an unknown value is refused where a closed one is accepted (the refusal is not a failure to load anything)
    with pytest.raises(ir.RouteError):
        ir.load(root_with(tmp_path / "c", with_key(GEMINI, "none")))
    ir.load(root_with(tmp_path / "d", with_key(GEMINI, "minimal")))
