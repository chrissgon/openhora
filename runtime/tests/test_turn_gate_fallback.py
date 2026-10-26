"""The gate's fifth section (S41-10, limit L63, the outage path): a second daily route of another company behind the policy group `interpret-fallback`, in code and off by default.

Held here:
  * the fallback is called only after a failed primary call or with the primary's breaker open, never on a primary that answered, never on E_ROUTE or E_GATE, and only for a sender who held the
    group when the line was admitted (the control: with the group check patched open the second call happens and the assertion fails); the mail composer and the two revisers pass no fallback;
  * one admission covers the line: ten lines whose primary fails use ten admissions, the eleventh is not admitted, and a line makes at most two calls;
  * each route has its own breaker: three primary failures open the primary's alone and the fallback serves; three fallback failures open its own; with both open the line is not admitted (the caller's
    own fallback, `_no_decision`, is what happens); concurrent records of one route count exactly;
  * the system and user text sent to the fallback is the primary's, byte for byte, with the same settings, and nothing is printed or logged;
  * an entry whose fallback hash is not this checkout's, whose row is not `zdr`, whose route is the primary or unknown, or whose field is malformed, turns the FALLBACK off and never the primary;
  * the routes file: every http row is pinned, allows no fallback provider and denies collection; the two fallback rows ask for zero retention, with the hashes pinned in scripts/tests/pinned_hashes.json;
  * the group is kind-only, messaging-only, in no default, needs `interpret` beside it, and its widening prints the retention of the fallback routes (or says that none is enabled);
  * the page and the terminal never reach either route.

Offline: the route's `complete` is a stand-in that counts its calls, the clock is a stand-in, every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_turn_gate_fallback.py
"""
from __future__ import annotations

import ast
import json
import threading
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_ops_natural import KEY, PROFILES, SENDERS, world  # noqa: F401  (the real-operations world fixture)

turn_gate = st.load("turn_gate")
interpreter_route = st.load("interpreter_route")
interpreter_enable = st.load("interpreter_enable")
ops_interpret = st.load("ops_interpret")
operations = st.load("operations")
policy_widening = st.load("policy_widening")
project_config = st.load("project_config")
ops = st.load("ops")

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
PINNED_HASHES = json.loads((REPO / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]
PRIMARY = "or-deepseek-v4.1-flash"
FIRST, SECOND = "or-gemini-3.5-flash-lite", "or-gpt-6-luna"
PARAMS = {"temperature": 0.0, "max_tokens": 300, "reasoning": "off"}
NONE = '{"v":1,"kind":"none"}'
SYSTEM, USER = "the system text of a test", "date\ntime\nzone\nframe\nthe line of a test about the unicorns"
WITH = {"messaging": ["read", "talk", "interpret", "interpret-fallback"]}
WITHOUT = {"messaging": ["read", "talk", "interpret"]}


@pytest.fixture(autouse=True)
def fresh():
    turn_gate.forget_all()
    yield
    turn_gate.forget_all()


class Frozen:
    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(turn_gate, "clock", lambda: self.now)


def ctx_of(project, channels=WITH):
    return {"cfg": {"project": str(project), "channels": channels}}


def hash_of(route_id):
    return interpreter_route.route_sha256(next(r for r in interpreter_route.daily_routes() if r["id"] == route_id))


def entry():
    return {"route": PRIMARY, "route_sha256": hash_of(PRIMARY)}


def outage(*ids):
    return [{"route": i, "route_sha256": hash_of(i)} for i in (ids or (FIRST,))]


class Model:
    """The stand-in of the route's `complete`: it answers by route id from a script (`ok`, or a code), and keeps every call."""

    def __init__(self, monkeypatch, script=None):
        self.script = dict(script or {})
        self.calls = []
        monkeypatch.setattr(interpreter_route, "complete", self.complete)

    def complete(self, route_id, system, user, **kw):
        self.calls.append({"route": route_id, "system": system, "user": user, **kw})
        answer = self.script.get(route_id, "ok")
        if callable(answer):
            answer = answer()
        return {"ok": True, "text": NONE} if answer == "ok" else {"ok": False, "code": answer}

    def routes(self):
        return [c["route"] for c in self.calls]


def line(tmp_path, sender="telegram:1", *, channels=WITH, fallback=None, entry_=None):
    """One line the way ops_interpret makes it: admit, call, record. Returns (admission or None, result or None)."""
    ctx = ctx_of(tmp_path, channels)
    given = outage() if fallback is None else fallback
    admission = turn_gate.admit(ctx, sender, fallback=given)
    if admission is None:
        return None, None
    got = turn_gate.call(admission, entry_ or entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS, fallback=given)
    if got.get("code") != "E_GATE":
        turn_gate.record_attempts(got)
    return admission, got


# --- when the fallback is called ---------------------------------------------------------------------------------------------------------------------


def test_the_fallback_is_called_after_a_failed_primary_and_only_then(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    _, got = line(tmp_path)
    assert got["ok"] is True and model.routes() == [PRIMARY, FIRST]
    assert got["attempts"] == [(None, False), (FIRST, True)]


@pytest.mark.parametrize("answer", ["ok"])
def test_the_fallback_is_never_called_when_the_primary_answered(tmp_path, monkeypatch, answer):
    model = Model(monkeypatch, {PRIMARY: answer})
    _, got = line(tmp_path)
    assert got["ok"] is True and model.routes() == [PRIMARY] and "attempts" not in got, "recorded as before: one attempt on the primary"


@pytest.mark.parametrize("code", ["E_TIMEOUT", "E_RATE", "E_UPSTREAM", "E_HTTP", "E_PIN", "E_RESPONSE", "E_KEY", "E_NETWORK"])
def test_every_failure_of_the_provider_but_the_route_check_goes_on_to_the_fallback(tmp_path, monkeypatch, code):
    model = Model(monkeypatch, {PRIMARY: code})
    _, got = line(tmp_path)
    assert model.routes() == [PRIMARY, FIRST] and got["ok"] is True


def test_the_fallback_is_never_called_on_a_primary_that_the_entry_no_longer_matches(tmp_path, monkeypatch):
    model = Model(monkeypatch, {})
    _, got = line(tmp_path, entry_=dict(entry(), route_sha256="0" * 64))
    assert got == {"ok": False, "code": "E_ROUTE"} and model.calls == [], "E_ROUTE is the entry's fault, not an outage: no request, no fallback"


def test_the_fallback_is_never_called_without_an_admission_and_a_used_admission_calls_nothing(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    for nothing in (None, "admission", object()):
        assert turn_gate.call(nothing, entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS, fallback=outage()) == {"ok": False, "code": "E_GATE"}
    one = turn_gate.admit(ctx_of(tmp_path), "telegram:1", fallback=outage())
    assert turn_gate.call(one, entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS, fallback=outage())["ok"] is True
    n = len(model.calls)
    assert turn_gate.call(one, entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS, fallback=outage()) == {"ok": False, "code": "E_GATE"} and len(model.calls) == n


def test_with_the_primarys_breaker_open_the_fallback_serves_and_the_primary_is_not_asked(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    for _ in range(turn_gate.BREAKER_FAILS):
        line(tmp_path, sender=f"telegram:{clock.now}")
        clock.now += 1
    assert model.routes().count(PRIMARY) == 3 and turn_gate._breaker["until"] > clock.now
    before = len(model.calls)
    admission, got = line(tmp_path)
    assert admission is not None and got["ok"] is True and model.routes()[before:] == [FIRST], "the open primary is skipped: only the fallback is asked"
    assert got["attempts"] == [(FIRST, True)]
    clock.now += turn_gate.BREAKER_OPEN + 1      # half open: the primary is asked again, and the fallback only when it fails
    model.script[PRIMARY] = "ok"
    before = len(model.calls)
    line(tmp_path)
    assert model.routes()[before:] == [PRIMARY]


def test_a_sender_without_the_group_gets_todays_behaviour_on_a_primary_failure(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    admission, got = line(tmp_path, channels=WITHOUT)
    assert admission is not None and admission.fallback_ok is False
    assert model.routes() == [PRIMARY] and got == {"ok": False, "code": "E_UPSTREAM"}, "one call, the primary's own failure, no `attempts`"
    for _ in range(turn_gate.BREAKER_FAILS - 1):
        line(tmp_path, channels=WITHOUT, sender="telegram:2")
    assert turn_gate.admit(ctx_of(tmp_path, WITHOUT), "telegram:3", fallback=outage()) is None, "with the primary's breaker open and no group, the line is not admitted (the line goes on as before)"
    assert model.routes() == [PRIMARY] * 3


def test_vacuity_with_the_group_check_open_the_second_call_happens_and_the_assertion_above_fails(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    monkeypatch.setattr(turn_gate, "_may_fall_back", lambda ctx, sender, fallback: True)
    line(tmp_path, channels=WITHOUT)
    assert model.routes() == [PRIMARY, FIRST], "the group check is what keeps the second call away"


@pytest.mark.parametrize("channels", [{}, {"messaging": []}, {"messaging": ["read", "talk"]}, {"page": ["read", "interpret-fallback"]}, None])
def test_only_the_messaging_policy_with_the_group_makes_a_fallback_admission(tmp_path, channels):
    ctx = {"cfg": {"project": str(tmp_path)}} if channels is None else ctx_of(tmp_path, channels)
    assert turn_gate.admit(ctx, "telegram:1", fallback=outage()).fallback_ok is False
    assert turn_gate.admit(ctx_of(tmp_path, WITH), "telegram:1", fallback=outage()).fallback_ok is True, "the control"
    assert turn_gate.admit(ctx_of(tmp_path, WITH), "telegram:1").fallback_ok is False, "a caller that names no fallback never gets one (the composer, the two revisers)"


def test_a_fallback_the_caller_did_not_name_is_never_asked(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    admission = turn_gate.admit(ctx_of(tmp_path), "telegram:1", fallback=outage())
    got = turn_gate.call(admission, entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS)
    assert got == {"ok": False, "code": "E_UPSTREAM"} and model.routes() == [PRIMARY]


def test_only_the_interpreter_names_a_fallback_and_the_group_is_read_by_the_gate_alone():
    """The mail composer, the two revisers and every other caller of the gate pass no `fallback`; the group is named in code by the gate (and the policy files), nowhere else."""
    named = {}
    for path in sorted(RUNTIME.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "fallback":
                named.setdefault(path.name, []).append(node.value.__class__.__name__)
    assert set(named) == {"ops_interpret.py"}, named      # the gate defines the keyword; the interpreter alone passes it
    texts = {p.name: p.read_text(encoding="utf-8") for p in RUNTIME.glob("*.py")}
    holders = sorted(name for name, text in texts.items() if '"interpret-fallback"' in text)
    assert holders == ["operations.py", "policy_widening.py", "project_config.py", "turn_gate.py"], holders      # the table, the widening text, the config check and the gate's one constant
    assert 'FALLBACK_GROUP = "interpret-fallback"' in texts["turn_gate.py"] and "FALLBACK_GROUP" not in texts["ops_interpret.py"] and '"interpret-fallback"' not in texts["ops_interpret.py"]


# --- one admission per line ---------------------------------------------------------------------------------------------------------------------------


def test_ten_lines_whose_primary_fails_use_ten_admissions_and_the_eleventh_is_not_admitted(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    admitted = 0
    for _ in range(turn_gate.RATE_MAX):
        admission, got = line(tmp_path)
        admitted += admission is not None
        assert got["ok"] is True
        clock.now += 0.5
    assert admitted == 10
    assert len(model.calls) == 13, "three primary failures open its breaker; the other seven lines asked only the fallback"
    admission, got = line(tmp_path)
    assert admission is None and got is None, "the eleventh line of the sender in the window is not admitted"
    assert len(model.calls) == 13


def test_a_line_makes_at_most_two_calls_whatever_the_routes(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM", FIRST: "E_UPSTREAM", SECOND: "E_UPSTREAM"})
    _, got = line(tmp_path, fallback=outage(FIRST, SECOND))
    assert model.routes() == [PRIMARY, FIRST], "the primary and one fallback"
    assert got["ok"] is False and got["attempts"] == [(None, False), (FIRST, False)]
    turn_gate.forget_all()
    Frozen(monkeypatch)
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)      # the primary's breaker is open: two fallbacks may serve one line, never three calls
    model.calls.clear()
    admission, got = line(tmp_path, sender="telegram:2", fallback=outage(FIRST, SECOND))
    assert admission is not None and model.routes() == [FIRST, SECOND] and got["attempts"] == [(FIRST, False), (SECOND, False)]


def test_the_second_fallback_serves_when_the_first_fails_and_the_primary_is_open(tmp_path, monkeypatch):
    Frozen(monkeypatch)
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)
    model = Model(monkeypatch, {FIRST: "E_UPSTREAM"})
    _, got = line(tmp_path, fallback=outage(FIRST, SECOND))
    assert model.routes() == [FIRST, SECOND] and got["ok"] is True and got["attempts"] == [(FIRST, False), (SECOND, True)]


# --- the breakers -----------------------------------------------------------------------------------------------------------------------------------


def test_the_breakers_are_per_route_and_both_open_means_the_line_is_not_admitted(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    for i in range(turn_gate.BREAKER_FAILS):
        line(tmp_path, sender=f"telegram:{i}")
        clock.now += 1
    assert turn_gate._breaker["until"] > clock.now, "three primary failures opened the primary's breaker"
    assert turn_gate._fallback_breakers.get(FIRST, {"fails": 0})["fails"] == 0, "the fallback answered: its count is closed"
    admission, got = line(tmp_path, sender="telegram:10")
    assert admission is not None and got["ok"] is True, "the fallback still serves"
    model.script[FIRST] = "E_UPSTREAM"
    for i in range(turn_gate.BREAKER_FAILS):
        admission, got = line(tmp_path, sender=f"telegram:2{i}")
        assert admission is not None and got["ok"] is False
        clock.now += 1
    assert turn_gate._fallback_breakers[FIRST]["until"] > clock.now, "three fallback failures opened its own breaker"
    calls = len(model.calls)
    assert turn_gate.admit(ctx_of(tmp_path), "telegram:99", fallback=outage()) is None, "both open: no admission, no call: `_no_decision` is what the caller does"
    assert len(model.calls) == calls
    clock.now += turn_gate.BREAKER_OPEN + 1
    assert turn_gate.admit(ctx_of(tmp_path), "telegram:99", fallback=outage()) is not None, "both close after their time"


def test_one_route_failing_does_not_count_against_the_other(tmp_path, monkeypatch):
    Frozen(monkeypatch)
    turn_gate.record(False, FIRST)
    turn_gate.record(False, FIRST)
    turn_gate.record(True)
    assert turn_gate._breaker == {"fails": 0, "until": 0.0} and turn_gate._fallback_breakers[FIRST]["fails"] == 2
    turn_gate.record(True, FIRST)
    assert turn_gate._fallback_breakers[FIRST]["fails"] == 0, "a success closes the count of that route"


def test_a_routes_breaker_counts_exactly_under_concurrent_records():
    threads = [threading.Thread(target=turn_gate.record, args=(False, FIRST)) for _ in range(60)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert turn_gate._fallback_breakers[FIRST]["fails"] == 60 and turn_gate._breaker == {"fails": 0, "until": 0.0}


def test_forget_all_closes_the_fallback_breakers_too(tmp_path):
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False, FIRST)
    assert turn_gate._fallback_breakers[FIRST]["until"] > 0
    turn_gate.forget_all()
    assert turn_gate._fallback_breakers == {}


def test_the_calls_of_a_failed_fallback_are_recorded_route_by_route(tmp_path, monkeypatch):
    Frozen(monkeypatch)
    Model(monkeypatch, {PRIMARY: "E_UPSTREAM", FIRST: "E_UPSTREAM"})
    line(tmp_path)
    assert turn_gate._breaker["fails"] == 1 and turn_gate._fallback_breakers[FIRST]["fails"] == 1


def test_record_attempts_with_a_plain_result_is_the_old_record(monkeypatch):
    seen = []
    monkeypatch.setattr(turn_gate, "record", lambda *a: seen.append(a))
    turn_gate.record_attempts({"ok": True, "text": "x"})
    turn_gate.record_attempts({"ok": False, "code": "E_HTTP"})
    turn_gate.record_attempts({"ok": True, "attempts": [(None, False), (FIRST, True)]})
    assert seen == [(True,), (False,), (False,), (True, FIRST)], "the primary is recorded with one argument, as the tests that patch `record` expect"


# --- what is sent -------------------------------------------------------------------------------------------------------------------------------------


def test_the_fallback_gets_the_primarys_text_byte_for_byte_with_the_same_settings_and_nothing_is_logged(tmp_path, monkeypatch, capsys, caplog):
    model = Model(monkeypatch, {PRIMARY: "E_TIMEOUT"})
    with caplog.at_level(0):
        line(tmp_path)
    first, second = model.calls
    assert (first["system"], first["user"]) == (second["system"], second["user"]) == (SYSTEM, USER)
    extra = {k: second[k] for k in second if k not in ("route", "system", "user")}
    assert extra == {k: first[k] for k in first if k not in ("route", "system", "user", "accepted")} | {"accepted": [hash_of(FIRST)]}, "the same deadline and settings; only the accepted hash is the route's own"
    assert set(extra) == {"accepted", "deadline_ms", "temperature", "max_tokens", "reasoning"}, "no extra field"
    out = capsys.readouterr()
    assert out.out == "" and out.err == "" and caplog.records == []


# --- the entry --------------------------------------------------------------------------------------------------------------------------------------


def test_a_fallback_whose_hash_is_not_the_checkouts_is_not_called_and_the_primary_still_serves(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    tampered = [{"route": FIRST, "route_sha256": "0" * 64}]
    admission, got = line(tmp_path, fallback=tampered)
    assert model.routes() == [PRIMARY] and got["ok"] is False and got["attempts"] == [(None, False)], "the gate asks nothing of a row that does not match"
    model.script[PRIMARY] = "ok"
    _, got = line(tmp_path, sender="telegram:2", fallback=tampered)
    assert got["ok"] is True and model.routes()[-1] == PRIMARY


def test_a_fallback_row_that_does_not_ask_for_zero_retention_is_never_called(tmp_path, monkeypatch):
    rows = [dict(r, zdr=False) if r["id"] == FIRST else r for r in interpreter_route.daily_routes()]
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: rows)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    _, got = line(tmp_path, fallback=[{"route": FIRST, "route_sha256": interpreter_route.route_sha256(next(r for r in rows if r["id"] == FIRST))}])
    assert model.routes() == [PRIMARY] and got["ok"] is False


def test_the_entrys_own_route_is_never_its_fallback(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    _, got = line(tmp_path, fallback=outage(PRIMARY))
    assert model.routes() == [PRIMARY] and got["ok"] is False


def newest_with(tmp_path, **fallback):
    doc = json.loads((RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))
    last = dict(doc["entries"][-1])
    if fallback:
        last["fallback"] = fallback["value"]
    path = tmp_path / "enable.json"
    path.write_text(json.dumps({"v": 1, "entries": [last]}), encoding="utf-8")
    return str(path), last


def good_item(route=FIRST, **over):
    known = route in (PRIMARY, FIRST, SECOND)
    return dict({"route": route, "route_sha256": hash_of(route) if known else "0" * 64, "measured": "2026-10-30 RESULT-X"}, **over)


def test_a_valid_fallback_in_the_newest_entry_is_in_force_and_the_committed_entry_has_none(tmp_path):
    assert interpreter_enable.active("en")["fallback"] == [], "this PR enables nothing: the committed entry names no fallback"
    assert "fallback" not in json.loads((RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))["entries"][-1]
    for value in (good_item(), [good_item()], [good_item(), good_item(SECOND)]):
        path, entry_ = newest_with(tmp_path, value=value)
        found = interpreter_enable.active("en", path=path)
        assert found is not None and found["route"]["id"] == PRIMARY
        assert found["fallback"] == [{"route": r, "route_sha256": hash_of(r)} for r in ([FIRST, SECOND] if isinstance(value, list) and len(value) == 2 else [FIRST])]


def broken_values():
    return {
        "a hash that is not the checkout's": [good_item(route_sha256="0" * 64)],
        "a hash that is not a hash": [good_item(route_sha256="not-a-hash")],
        "an unknown route": [good_item(route="no-such-route", route_sha256="0" * 64)],
        "an account route": [good_item(route="acct-claude-sonnet-5.5", route_sha256="0" * 64)],
        "the primary itself": [good_item(PRIMARY)],
        "a route twice": [good_item(), good_item()],
        "three routes": [good_item(), good_item(SECOND), good_item(PRIMARY)],
        "an empty list": [],
        "a text": "or-gemini-3.5-flash-lite",
        "a number": 7,
        "a missing key": [{"route": FIRST, "route_sha256": hash_of(FIRST)}],
        "an extra key": [good_item(extra=1)],
        "an empty measured": [good_item(measured="  ")],
        "a measured that is not a text": [good_item(measured=7)],
        "a long measured": [good_item(measured="x" * 601)],
        "an item that is not an object": ["x"],
        "one good and one bad": [good_item(), good_item(SECOND, route_sha256="0" * 64)],
        "a route that is not a text": [good_item(route=["a"])],
    }


@pytest.mark.parametrize("name", sorted(broken_values()))
def test_a_malformed_or_changed_fallback_turns_the_fallback_off_and_never_the_primary(tmp_path, name):
    path, _ = newest_with(tmp_path, value=broken_values()[name])
    found = interpreter_enable.active("en", path=path)
    assert found is not None and found["fallback"] == [], name
    assert found["route"]["id"] == PRIMARY and interpreter_enable.load(path)["entries"][-1]["route"] == PRIMARY


def test_a_fallback_row_without_zero_retention_is_never_in_force(tmp_path, monkeypatch):
    path, _ = newest_with(tmp_path, value=[good_item()])
    rows = [dict(r, zdr=False) if r["id"] == FIRST else r for r in interpreter_route.daily_routes()]
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: rows)
    found = interpreter_enable.active("en", path=path)
    assert found is not None and found["fallback"] == []


def test_a_changed_primary_hash_still_turns_the_whole_entry_off_as_before(tmp_path):
    path, last = newest_with(tmp_path, value=[good_item()])
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    doc["entries"][-1]["prompt_sha256"] = "0" * 64
    Path(path).write_text(json.dumps(doc), encoding="utf-8")
    assert interpreter_enable.active("en", path=path) is None, "the fallback never keeps the interpreter on"


def test_the_status_script_reads_an_entry_with_a_fallback_as_in_force(tmp_path):
    import importlib.util
    import shutil
    import sys
    name = "workbench_interpreter_status_for_fallback_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / "evals" / "interpreter_status.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    status = sys.modules[name]
    path, _ = newest_with(tmp_path, value=[good_item()])
    root = tmp_path / "root"
    (root / "runtime").mkdir(parents=True)
    shutil.copy(path, root / "runtime" / "interpreter_enable.json")
    assert status.enable_status(str(root), status.load_inputs())["in_force"] is True


def test_the_retention_of_the_fallback_routes_in_force(tmp_path):
    assert interpreter_enable.fallback_retention() is None, "nothing is enabled in this PR"
    path, _ = newest_with(tmp_path, value=[good_item(), good_item(SECOND)])
    kept = interpreter_enable.fallback_retention(path)
    assert kept == [interpreter_route.find(FIRST)["retention"], interpreter_route.find(SECOND)["retention"]]
    path, _ = newest_with(tmp_path, value="junk")
    assert interpreter_enable.fallback_retention(path) is None


# --- the routes file --------------------------------------------------------------------------------------------------------------------------------


def test_routes_file_daily_rows_are_pinned_and_deny_collection():
    rows = interpreter_route.daily_routes()
    assert [r["id"] for r in rows] == [PRIMARY, FIRST, SECOND]
    for row in rows:
        assert row["kind"] == "http" and row["allow_fallbacks"] is False and row["data_collection"] == "deny" and row["pin"].strip(), row["id"]
        assert row["base_url"] == "https://openrouter.ai/api/v1" and row["key"] == "WB_RUNTIME_KEY_OPENROUTER_API_KEY" and row["reference"] is False
    by_id = {r["id"]: r for r in rows}
    assert by_id[PRIMARY]["zdr"] is False, "the daily route's retention is unchanged"
    for fallback_id, pin, upstream in ((FIRST, "google-vertex", "google/gemini-3.5-flash-lite"), (SECOND, "azure", "openai/gpt-6-luna")):
        row = by_id[fallback_id]
        assert row["zdr"] is True and row["pin"] == pin and row["upstream_model"] == upstream and row["model"] == "openrouter/" + upstream, fallback_id
        assert "not confirmed" in row["retention"] and "zero data retention" in row["retention"].lower()


def test_the_fallback_rows_have_the_pinned_hashes_and_the_primary_is_unchanged():
    assert hash_of(PRIMARY) == PINNED_HASHES["route_or_deepseek_v4_1_flash"]
    assert hash_of(FIRST) == PINNED_HASHES["route_or_gemini_3_5_flash_lite"]
    assert hash_of(SECOND) == PINNED_HASHES["route_or_gpt_6_luna"]
    shown = interpreter_route.stdin_route(interpreter_route.find(FIRST))
    assert shown["allow_fallbacks"] is False and shown["data_collection"] == "deny" and shown["zdr"] is True and shown["pin"] == "google-vertex"


@pytest.mark.parametrize("change", [{"allow_fallbacks": True}, {"data_collection": "allow"}, {"pin": ""}])
def test_the_loader_refuses_a_fallback_row_with_fallbacks_or_collection_allowed(tmp_path, change):
    doc = json.loads((RUNTIME / "interpreter_routes.json").read_text(encoding="utf-8"))
    doc["routes"] = [dict(r, **change) if r["id"] == FIRST else r for r in doc["routes"]]
    root = tmp_path / "wb"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "secrets.json").write_text((RUNTIME / "secrets.json").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "runtime" / "interpreter_routes.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(interpreter_route.RouteError):
        interpreter_route.load(str(root))


def test_no_model_of_the_account_vendor_is_on_an_http_route():
    words = ("clau" + "de", "anth" + "ropic")
    for row in interpreter_route.daily_routes():
        assert not any(w in json.dumps(row).lower() for w in words), row["id"]


def test_the_two_fallback_rows_are_priced_at_their_pinned_provider():
    table = json.loads((RUNTIME / "prices.json").read_text(encoding="utf-8"))["models"]
    for fallback_id, provider in ((FIRST, "google-vertex"), (SECOND, "azure")):
        row = interpreter_route.find(fallback_id)
        price = table[row["model"]]
        assert price["provider"] == provider and price["accessed"] == "2026-10-26" and price["source"].startswith("https://openrouter.ai/")
        assert all(isinstance(price[k], (int, float)) and price[k] > 0 for k in ("input_usd_per_mtok", "output_usd_per_mtok", "cache_read_usd_per_mtok"))


# --- the group --------------------------------------------------------------------------------------------------------------------------------------


def test_the_group_is_kind_only_messaging_only_in_no_default_and_never_grants_say():
    assert operations.GROUPS["interpret-fallback"] == {"operations": ("say",), "kind": "interpret-fallback"}
    assert "interpret-fallback" in operations.KIND_ONLY and "interpret-fallback" in operations.MESSAGING_ONLY_GROUPS
    assert "interpret-fallback" not in operations.DEFAULT_POLICY["messaging"] and "interpret-fallback" not in operations.GRANTS.get("messaging", ())
    policy = {"messaging": ["read", "interpret-fallback"]}
    assert operations.holds("interpret-fallback", "messaging", policy, "telegram:1") is True and operations.permitted("say", "messaging", policy, None, "telegram:1") is False
    assert operations.holds("interpret-fallback", "page", {"page": ["read"]}, None) is False and operations.group_refusal("page", "interpret-fallback")
    assert operations.GROUP_TEXT["interpret-fallback"].startswith("when the interpreter's usual model service cannot read a plain line")
    assert "interpret-fallback" not in operations.default_groups("messaging")


def test_a_policy_that_lists_the_fallback_without_interpret_is_refused_and_one_with_both_is_valid(tmp_path):
    with pytest.raises(project_config.ConfigError) as refused:
        project_config._check_assigned("channels.messaging", "messaging", ["read", "talk", "interpret-fallback"], None)
    assert "'interpret-fallback' needs 'interpret' beside it" in str(refused.value)
    project_config._check_assigned("channels.messaging", "messaging", ["read", "talk", "interpret", "interpret-fallback"], None)
    with pytest.raises(project_config.ConfigError):
        project_config._check_assigned("channels.page", "page", ["read", "interpret", "interpret-fallback"], None)      # a group of a messaging app on the page: refused as `interpret` is


def test_widening_the_group_says_that_no_fallback_is_enabled_in_this_checkout(world):
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS})
    write_config(world["path"], policies=dict(PROFILES, owner=PROFILES["owner"] + ["interpret", "interpret-fallback"]))
    shown = ops.config(world["path"])
    mine = [item for item in shown["widening"] if item["group"] == "interpret-fallback"]
    assert len(mine) == 1 and mine[0]["place"] == KEY["owner"]
    assert "no fallback route is enabled in this checkout" in mine[0]["means"] and "second model service of another company" in mine[0]["means"]
    assert policy_widening.widening_sha256([{"place": KEY["owner"], "group": "interpret-fallback"}]) is not None


def test_widening_the_group_prints_the_retention_of_each_fallback_route_the_newest_entry_names(monkeypatch, tmp_path):
    path, _ = newest_with(tmp_path, value=[good_item(), good_item(SECOND)])
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", path)
    text = policy_widening.means("messaging", "interpret-fallback")
    assert text.endswith(" | ".join([interpreter_route.find(FIRST)["retention"], interpreter_route.find(SECOND)["retention"]]))
    assert "Retention of the fallback routes: " in text
    (tmp_path / "one").mkdir()
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", newest_with(tmp_path / "one", value=[good_item()])[0])
    assert "Retention of the fallback route: " in policy_widening.means("messaging", "interpret-fallback")


# --- the page and the terminal never reach a route -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("channel", ["page", "terminal", "chat", "mcp"])
def test_the_page_the_terminal_and_the_other_channels_never_reach_either_route(world, channel, monkeypatch):
    model = Model(monkeypatch, {})
    ctx = ctx_of(world["path"], WITH)
    ctx["cfg"]["language"] = "en"
    assert ops_interpret.enabled(ctx, channel, "telegram:1") is False
    assert model.calls == []


def test_the_interpreters_ask_goes_to_the_fallback_through_the_gate_and_records_each_route(world, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: "America/Sao_Paulo")
    ctx = ctx_of(world["path"], WITH)
    outage_routes = outage()
    admission = turn_gate.admit(ctx, "telegram:1", fallback=outage_routes)
    decision = ops_interpret._ask_model(ctx, entry(), "tell me something about the unicorns", "telegram:1", admission, None, fallback=outage_routes)
    assert decision is not None, "the fallback's answer was read: a decision (here the shape error of a context without a catalog policy, or the answer itself), not an outage"
    assert model.routes() == [PRIMARY, FIRST] and turn_gate._breaker["fails"] == 1 and turn_gate._fallback_breakers[FIRST]["fails"] == 0
    del clock
    for_the_page = turn_gate.admit(ctx_of(world["path"], WITHOUT), "telegram:2", fallback=outage_routes)
    assert ops_interpret._ask_model(ctx_of(world["path"], WITHOUT), entry(), "tell me something", "telegram:2", for_the_page, None, fallback=outage_routes) is None
    assert model.routes() == [PRIMARY, FIRST, PRIMARY], "a sender without the group: the primary failed, the line goes on as before (no decision)"
