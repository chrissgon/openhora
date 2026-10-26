"""The gate's first section (S41-4, limit L63 and its S7 and S13 rows): the one admitted call on the daily route, its rate, its day, its breaker and its route check.

Held here:
  * only runtime/turn_gate.py (and the lab's measuring tool, runtime/interpreter_measure.py, which is not a person's line) names the `complete` of the route module; a scan of the
    source finds a planted call in a scratch copy (the control);
  * `turn_gate.call` asks nothing without an unused admission: no admission, a look-alike, a used one are E_GATE and the route is not asked; an admission can be made by `admit` only and
    holds no text; the route check (an account row, a changed hash, a missing route) is E_ROUTE with no request;
  * for each of the four callers (the interpreter's turn, the e-mail composer, the e-mail reviser, the event reviser) the eleventh call of a sender within 60 s is not made and the caller's own
    fallback happens; three failures in a row of one caller open the breaker for every caller; with `turn_gate.admit` patched to admit always, or `record` to do nothing, the same scenario
    fails (the controls);
  * two threads of one sender with the window at nine calls: at most one passes; 300 calls per project and local day, the next day calls again.

Offline: the model is a stand-in that counts its calls, the clocks are stand-ins, every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_turn_gate_admit.py
"""
from __future__ import annotations

import ast
import shutil
import threading
from pathlib import Path

import pytest

import standin_tree as st
import test_event_revise_flow as ter
import test_mail_compose_flow as tmc
import test_mail_revise_flow as tmr
import test_ops_interpret_dispatch as tid
from test_calendar_write import world as calendar_world  # noqa: F401  (the calendar world of the event reviser)
from test_ops_natural import world as line_world  # noqa: F401  (the real-operations world of the interpreter)
from test_reminders import Clock as WallClock
from test_send_own_account import world as mail_world  # noqa: F401  (the own-account mail world of the composer and the e-mail reviser)

turn_gate = st.load("turn_gate")
interpreter_route = st.load("interpreter_route")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
mail_compose = st.load("mail_compose")
ops_core = st.load("ops_core")

RUNTIME = Path(__file__).resolve().parents[1]
THE_GATE_AND_THE_LAB = {"turn_gate.py", "interpreter_measure.py"}      # the files that may name the route's `complete`
CALLERS = ["interpreter", "composer", "mail-reviser", "event-reviser"]
NONE = '{"v":1,"kind":"none"}'
PLAIN_LINE = "tell me something about the unicorns"
PARAMS = {"temperature": 0.0, "max_tokens": 10, "reasoning": "off"}


@pytest.fixture(autouse=True)
def fresh():
    turn_gate.forget_all()
    yield
    turn_gate.forget_all()


class Frozen:
    """The stand-in clock of the rate window and of the breaker (seconds)."""

    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(turn_gate, "clock", lambda: self.now)


def admission():
    """An admission of the test's own (the one place that makes one is `admit`; the test holds its private mint, as the gate's own function does)."""
    return turn_gate.Admission(turn_gate._MINT)


def ctx_of(project):
    return {"cfg": {"project": str(project)}}


# --- only the gate calls the daily route -----------------------------------------------------------------------------------------------------------------


def routes_named(folder: Path) -> list:
    """(file, line) of every call of the route module's `complete` in the python files of `folder` (runtime/*.py and runtime/handlers/*.py): `interpreter_route.complete(...)`, the same through
    a name bound by `importlib.import_module("interpreter_route")` or `import interpreter_route as x`, `getattr(<that>, "complete")` and a bare `complete(...)` imported from it."""
    found = []
    for path in sorted(list(folder.glob("*.py")) + list(folder.glob("handlers/*.py"))):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names, bare = {"interpreter_route"}, set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.asname or a.name for a in node.names if a.name == "interpreter_route")
            elif isinstance(node, ast.ImportFrom) and node.module == "interpreter_route":
                bare.update(a.asname or a.name for a in node.names if a.name == "complete")
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                if (isinstance(call.func, ast.Attribute) and call.func.attr == "import_module" and call.args and isinstance(call.args[0], ast.Constant)
                        and call.args[0].value == "interpreter_route"):
                    names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "complete" and isinstance(func.value, ast.Name) and func.value.id in names:
                found.append((path.name, node.lineno))
            elif isinstance(func, ast.Name) and func.id in bare:
                found.append((path.name, node.lineno))
            elif (isinstance(func, ast.Name) and func.id == "getattr" and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id in names
                  and isinstance(node.args[1], ast.Constant) and node.args[1].value == "complete"):
                found.append((path.name, node.lineno))
    return found


def test_only_the_gate_calls_the_daily_route():
    named = routes_named(RUNTIME)
    assert {name for name, _ in named} == THE_GATE_AND_THE_LAB, named      # both are there: the gate for a person's line, the lab's tool for a measurement
    assert [n for n in named if n[0] not in THE_GATE_AND_THE_LAB] == []


def test_vacuity_the_scan_finds_a_planted_call_in_a_scratch_copy(tmp_path):
    copy = tmp_path / "runtime"
    (copy / "handlers").mkdir(parents=True)
    for path in list(RUNTIME.glob("*.py")) + list(RUNTIME.glob("handlers/*.py")):
        shutil.copy(path, copy / path.relative_to(RUNTIME))
    with open(copy / "ops_interpret.py", "a", encoding="utf-8") as handle:
        handle.write('\n\ndef planted():\n    return interpreter_route.complete("r", "s", "u")\n')
    with open(copy / "mail_compose.py", "a", encoding="utf-8") as handle:
        handle.write('\n\ndef planted_by_alias():\n    route = importlib.import_module("interpreter_route")\n    return route.complete("r", "s", "u")\n')
    with open(copy / "mail_revise.py", "a", encoding="utf-8") as handle:
        handle.write('\n\ndef planted_by_getattr():\n    route = importlib.import_module("interpreter_route")\n    return getattr(route, "complete")("r", "s", "u")\n')
    with open(copy / "ops_event_revise.py", "a", encoding="utf-8") as handle:
        handle.write('\n\ndef planted_bare():\n    from interpreter_route import complete\n    return complete("r", "s", "u")\n')
    outside = {name for name, _ in routes_named(copy)} - THE_GATE_AND_THE_LAB
    assert outside == {"ops_interpret.py", "mail_compose.py", "mail_revise.py", "ops_event_revise.py"}


# --- a call needs an admission ---------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def standin(monkeypatch):
    """A route table with the one http row, a `complete` that counts, and the entry that names the row and its hash."""
    row = interpreter_route.find("or-deepseek-v4.1-flash")
    asked = []
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: [row])
    monkeypatch.setattr(interpreter_route, "complete", lambda route_id, system, user, **kw: asked.append((route_id, kw)) or {"ok": True, "text": NONE})
    return {"asked": asked, "row": row, "entry": {"route": row["id"], "route_sha256": interpreter_route.route_sha256(row)}}


def test_a_call_without_an_admission_calls_nothing(standin):
    for nothing in (None, "admission", object(), {"used": False}):
        assert turn_gate.call(nothing, standin["entry"], "system", "user", deadline_ms=6000, params=PARAMS) == {"ok": False, "code": "E_GATE"}
    assert standin["asked"] == []
    got = turn_gate.call(admission(), standin["entry"], "system", "user", deadline_ms=6000, params=PARAMS)
    assert got["ok"] is True and len(standin["asked"]) == 1, "the control: an unused admission calls"
    assert standin["asked"][0][0] == standin["row"]["id"] and standin["asked"][0][1]["accepted"] == [standin["entry"]["route_sha256"]]
    assert standin["asked"][0][1]["deadline_ms"] == 6000 and {k: standin["asked"][0][1][k] for k in PARAMS} == PARAMS


def test_an_admission_is_used_by_its_first_call_and_a_second_call_calls_nothing(standin):
    one = admission()
    assert turn_gate.call(one, standin["entry"], "system", "user", deadline_ms=6000, params=PARAMS)["ok"] is True
    assert turn_gate.call(one, standin["entry"], "system", "user", deadline_ms=6000, params=PARAMS) == {"ok": False, "code": "E_GATE"}
    assert len(standin["asked"]) == 1


def test_an_admission_used_on_a_refused_route_is_used_all_the_same(standin):
    one = admission()
    assert turn_gate.call(one, dict(standin["entry"], route_sha256="0" * 64), "system", "user", deadline_ms=6000, params=PARAMS) == {"ok": False, "code": "E_ROUTE"}
    assert turn_gate.call(one, standin["entry"], "system", "user", deadline_ms=6000, params=PARAMS) == {"ok": False, "code": "E_GATE"}
    assert standin["asked"] == []


def test_an_admission_is_made_by_the_gate_only_and_holds_no_text(tmp_path):
    with pytest.raises(TypeError):
        turn_gate.Admission(object())
    with pytest.raises(TypeError):
        turn_gate.Admission(None)
    sender = "telegram:4242-private-sender"
    got = turn_gate.admit(ctx_of(tmp_path), sender)
    assert isinstance(got, turn_gate.Admission) and vars(got) == {"used": False}
    assert not any(isinstance(v, str) for v in vars(got).values()) and sender not in repr(got) and str(tmp_path) not in repr(got)


def test_one_admission_is_used_once_by_two_threads_racing(standin):
    for _ in range(40):
        one, results, gate = admission(), [], threading.Barrier(2)

        def go():
            gate.wait()
            results.append(turn_gate.call(one, standin["entry"], "system", "user", deadline_ms=6000, params=PARAMS))

        threads = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert sorted(r["ok"] for r in results) == [False, True]
    assert len(standin["asked"]) == 40


def test_the_route_check_an_account_row_a_changed_hash_a_missing_route_are_e_route_and_no_request(standin, monkeypatch):
    account = dict(interpreter_route.find("acct-claude-sonnet-5.5"), id=standin["row"]["id"])
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: [account])
    assert turn_gate.call(admission(), dict(standin["entry"], route_sha256=interpreter_route.route_sha256(account)), "s", "u", deadline_ms=6000, params=PARAMS) == {"ok": False, "code": "E_ROUTE"}
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: [standin["row"]])
    assert turn_gate.call(admission(), dict(standin["entry"], route_sha256="0" * 64), "s", "u", deadline_ms=6000, params=PARAMS) == {"ok": False, "code": "E_ROUTE"}
    assert turn_gate.call(admission(), dict(standin["entry"], route="no-such-route"), "s", "u", deadline_ms=6000, params=PARAMS) == {"ok": False, "code": "E_ROUTE"}
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: [standin["row"], standin["row"]])
    assert turn_gate.call(admission(), standin["entry"], "s", "u", deadline_ms=6000, params=PARAMS) == {"ok": False, "code": "E_ROUTE"}
    assert standin["asked"] == []


# --- the gate's own counts -------------------------------------------------------------------------------------------------------------------------------


def test_two_threads_of_one_sender_with_the_window_at_nine_calls_admit_at_most_one(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    for _ in range(25):
        turn_gate.forget_all()
        clock.now += 1000.0
        assert all(turn_gate.admit(ctx_of(tmp_path), "owner") is not None for _ in range(turn_gate.RATE_MAX - 1))
        gate, got = threading.Barrier(2), []

        def go():
            gate.wait()
            got.append(turn_gate.admit(ctx_of(tmp_path), "owner"))

        threads = [threading.Thread(target=go) for _ in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        assert len([g for g in got if g is not None]) == 1


def test_three_hundred_per_project_per_local_day_and_the_next_day_admits_again(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    for _ in range(turn_gate.DAY_MAX):
        assert turn_gate.admit(ctx_of(tmp_path), f"sender-{clock.now}") is not None
        clock.now += 61.0      # a new sender each time and a new window: only the day's count is in play
    assert turn_gate.admit(ctx_of(tmp_path), "a-new-sender") is None
    other = tmp_path / "other"
    other.mkdir()
    assert turn_gate.admit(ctx_of(other), "a-new-sender") is not None, "another project has its own day"
    day = ops_natural._clock()
    monkeypatch.setattr(ops_natural, "_clock", lambda: day.replace(day=day.day + 1) if day.day < 28 else day.replace(day=1, month=day.month % 12 + 1))
    assert turn_gate.admit(ctx_of(tmp_path), "a-new-sender") is not None


def test_the_breaker_opens_at_the_third_failure_in_a_row_stays_five_minutes_and_a_success_closes_the_count(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    for outcome in (False, False, True, False, False):
        turn_gate.record(outcome)
    assert turn_gate.admit(ctx_of(tmp_path), "owner") is not None, "a success between failures keeps it closed"
    turn_gate.record(False)
    assert turn_gate.admit(ctx_of(tmp_path), "owner") is None and turn_gate.admit(ctx_of(tmp_path), "another-sender") is None
    clock.now += turn_gate.BREAKER_OPEN - 1
    assert turn_gate.admit(ctx_of(tmp_path), "owner") is None
    clock.now += 2
    assert turn_gate.admit(ctx_of(tmp_path), "owner") is not None


def test_the_constants_are_the_contracts(tmp_path):
    assert (turn_gate.RATE_MAX, turn_gate.RATE_WINDOW, turn_gate.DAY_MAX, turn_gate.BREAKER_FAILS, turn_gate.BREAKER_OPEN) == (10, 60.0, 300, 3, 300.0)
    for name in ("RATE_MAX", "RATE_WINDOW", "DAY_MAX", "BREAKER_FAILS", "BREAKER_OPEN", "clock", "_calls", "_days", "_breaker", "_lock", "_admit", "_record", "_daily_call"):
        assert not hasattr(ops_interpret, name), f"no state, no limit and no call of its own lives in ops_interpret: {name}"


def test_forget_all_of_the_interpreter_is_the_gates_and_holds_no_state_of_its_own(tmp_path):
    for _ in range(3):
        turn_gate.record(False)
    assert turn_gate.admit(ctx_of(tmp_path), "owner") is None
    ops_interpret.forget_all()
    assert turn_gate.admit(ctx_of(tmp_path), "owner") is not None


# --- the four callers ------------------------------------------------------------------------------------------------------------------------------------


class Env:
    """One caller on its own world: `attempt()` makes one attempt, `made()` counts the calls the stand-in model received (all kinds), `fell_back(result)` says whether the result is the
    caller's own fallback, `fail()` makes the model fail from now on."""

    def __init__(self, kind, request, monkeypatch):
        self.kind, self.monkeypatch = kind, monkeypatch
        getattr(self, "build_" + kind.replace("-", "_"))(request)

    def build_interpreter(self, request):
        world = request.getfixturevalue("line_world")
        self.calls = []
        tid.prepare(world, self.monkeypatch, self.calls, {"text": NONE})
        self.world = world

    def build_composer(self, request):
        world = request.getfixturevalue("mail_world")
        request.getfixturevalue("wall")
        self.model, self.world = tmc.setup(world, self.monkeypatch), world
        self.ctx = ops_core.context(world["path"])

    def build_mail_reviser(self, request):
        world = request.getfixturevalue("mail_world")
        request.getfixturevalue("wall")
        self.model, self.number, self.sha = tmr.live_card(world, self.monkeypatch, revise=tmr.COMPOSE)      # a valid answer that changes nothing: the call is made and ends in the same sentence
        self.world = world
        turn_gate.forget_all()      # the line that opened the card was two admitted calls: the scenario counts from here

    def build_event_reviser(self, request):
        world = request.getfixturevalue("calendar_world")
        self.model = ter.build(world, self.monkeypatch, NONE)
        self.number, self.sha = ter.create(world)
        self.world = world

    def attempt(self):
        if self.kind == "interpreter":
            return tid.phone(self.world, PLAIN_LINE)["reply"]
        if self.kind == "composer":
            return mail_compose.write(self.ctx, "messaging", tmc.SENDER, [tmc.ADDRESS], "Assunto", tmc.SPAN)      # validate: allow english-only -- a Portuguese subject under test
        if self.kind == "mail-reviser":
            return tmr.revise(self.world, self.number, self.sha, tmr.INSTRUCTION)
        return ter.revise(self.world, self.number, self.sha, ter.LIVE)

    def made(self):
        if self.kind == "interpreter":
            return len([c for c in self.calls if "user" in c])
        if self.kind == "mail-reviser":
            return len(self.model.of("revise"))      # the line that opened the card made its own two calls
        return len(self.model.calls)

    def fell_back(self, result):
        return {"interpreter": lambda r: r == "ROUTED",
                "composer": lambda r: r["composed"] is False and r["body"] == tmc.SPAN,
                "mail-reviser": lambda r: r.get("say") == tmr.FAILED,
                "event-reviser": lambda r: r == {"pass": True}}[self.kind](result)

    def fail(self):
        if self.kind == "interpreter":
            self.monkeypatch.setattr(interpreter_route, "complete", lambda route_id, system, user, **kw: self.calls.append({"route": route_id, "user": user}) or {"ok": False, "code": "E_NETWORK"})
        elif self.kind == "composer":
            self.model.compose = None
        elif self.kind == "mail-reviser":
            self.model.answers["revise"] = None
        else:
            self.model.text = None


@pytest.fixture
def wall(monkeypatch):
    return WallClock(monkeypatch, wall="2026-10-21 10:00")


def rate_wrong(env, frozen):
    """Ten attempts in ten seconds from one sender: ten calls; the eleventh is not made and is the caller's own fallback; sixty seconds later it is made again. What is wrong."""
    wrong = []
    for _ in range(turn_gate.RATE_MAX):
        env.attempt()
        frozen.now += 1.0
    if env.made() != turn_gate.RATE_MAX:
        wrong.append(f"{env.made()} calls in the window")
    result = env.attempt()
    if env.made() != turn_gate.RATE_MAX:
        wrong.append("the eleventh call was made")
    if not env.fell_back(result):
        wrong.append(f"the eleventh attempt did not end in the caller's fallback: {result!r}")
    frozen.now += 61.0
    env.attempt()
    if env.made() != turn_gate.RATE_MAX + 1:
        wrong.append("no call after the window")
    return wrong


@pytest.mark.parametrize("kind", CALLERS)
def test_the_eleventh_call_of_a_sender_within_a_minute_is_not_made_and_the_caller_falls_back(request, monkeypatch, kind):
    env = Env(kind, request, monkeypatch)
    assert rate_wrong(env, Frozen(monkeypatch)) == []


@pytest.mark.parametrize("kind", CALLERS)
def test_vacuity_with_the_admission_always_given_the_eleventh_call_is_made_and_the_scenario_fails(request, monkeypatch, kind):
    env = Env(kind, request, monkeypatch)
    monkeypatch.setattr(turn_gate, "admit", lambda ctx, sender: admission())
    assert rate_wrong(env, Frozen(monkeypatch)) != []


def breaker_wrong(env, frozen):
    """Three failed calls of one caller: its fourth attempt is not made and is its fallback, and the gate admits nobody (another sender, another project) until the breaker closes. What is wrong."""
    wrong = []
    env.fail()
    for _ in range(turn_gate.BREAKER_FAILS):
        env.attempt()
        frozen.now += 1.0
    if env.made() != turn_gate.BREAKER_FAILS:
        wrong.append(f"{env.made()} calls before the breaker")
    result = env.attempt()
    if env.made() != turn_gate.BREAKER_FAILS:
        wrong.append("a call was made with the breaker open")
    if not env.fell_back(result):
        wrong.append(f"the attempt with the breaker open did not end in the caller's fallback: {result!r}")
    elsewhere = ctx_of(Path(env.world["path"]) / "elsewhere")
    if turn_gate.admit(elsewhere, "someone-else") is not None:
        wrong.append("the breaker is not shared: another sender of another project was admitted")
    return wrong


@pytest.mark.parametrize("kind", CALLERS)
def test_three_failures_of_one_caller_open_the_breaker_for_every_caller(request, monkeypatch, kind):
    env = Env(kind, request, monkeypatch)
    assert breaker_wrong(env, Frozen(monkeypatch)) == []


@pytest.mark.parametrize("kind", CALLERS)
def test_vacuity_with_the_record_doing_nothing_the_breaker_never_opens_and_the_scenario_fails(request, monkeypatch, kind):
    env = Env(kind, request, monkeypatch)
    monkeypatch.setattr(turn_gate, "record", lambda ok: None)
    assert breaker_wrong(env, Frozen(monkeypatch)) != []


def test_the_failures_of_the_composer_stop_the_interpreter_and_the_failures_of_the_interpreter_stop_the_composer(request, monkeypatch):
    """Across two real callers in one world: the interpreter's turn and the composer count in the same breaker."""
    world, frozen = request.getfixturevalue("mail_world"), Frozen(monkeypatch)
    request.getfixturevalue("wall")
    model = tmc.setup(world, monkeypatch, compose=None)
    ctx, extras = ops_core.context(world["path"]), {}
    for _ in range(turn_gate.BREAKER_FAILS):
        assert mail_compose.write(ctx, "messaging", tmc.SENDER, [tmc.ADDRESS], "Assunto", tmc.SPAN)["composed"] is False      # validate: allow english-only -- a Portuguese subject under test
        frozen.now += 1.0
    assert len(model.of("compose")) == 3
    assert ops_interpret.turn(world["path"], ctx, "tell me something about the unicorns", tmc.SENDER, extras) is None and model.of("interpret") == []      # the breaker is open: no call, the line goes on as before
    frozen.now += turn_gate.BREAKER_OPEN + 1
    model.compose, model.interpret = tmc.COMPOSED, None
    assert mail_compose.write(ctx, "messaging", tmc.SENDER, [tmc.ADDRESS], "Assunto", tmc.SPAN)["composed"] is True      # validate: allow english-only -- a Portuguese subject under test; the half-open call succeeds and closes the count
    for _ in range(turn_gate.BREAKER_FAILS):
        ops_interpret.turn(world["path"], ctx, "tell me something about the unicorns", tmc.SENDER, {})
        frozen.now += 1.0
    assert len(model.of("interpret")) == 3
    assert mail_compose.write(ctx, "messaging", tmc.SENDER, [tmc.ADDRESS], "Assunto", tmc.SPAN)["composed"] is False and len(model.of("compose")) == 4      # validate: allow english-only -- a Portuguese subject under test


def test_a_failure_before_the_call_is_recorded_as_a_failure_the_way_it_was(request, monkeypatch):
    """The interpreter's zone that cannot be named is an admitted attempt that ends before the call: counted, recorded as a failure, never a call."""
    world, frozen = request.getfixturevalue("line_world"), Frozen(monkeypatch)
    calls = []
    tid.prepare(world, monkeypatch, calls, {"text": NONE})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: (_ for _ in ()).throw(ValueError("no zone")))
    for _ in range(turn_gate.BREAKER_FAILS):
        assert tid.phone(world, PLAIN_LINE)["reply"] == "ROUTED"
        frozen.now += 1.0
    assert calls == [] or all("user" not in c for c in calls)
    assert turn_gate._breaker["until"] > frozen.now, "three attempts that failed before the call opened the breaker, as before"
