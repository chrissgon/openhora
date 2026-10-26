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
THE_GATE_AND_THE_LAB = {"turn_gate.py", "interpreter_route.py", "lab.py", "interpreter_measure.py"}      # the files that may hold a way into the route: the gate, the route module itself, the lab's text runner and measuring tool
ROUTE_NAMES = {"complete", "_complete", "_complete_account", "account_text"}
MINT_NAMES = {"_MINT", "Admission"}
MODULE_NAMES = {"interpreter_route", "interpreter_measure"}
NOT_THE_ROUTE = {("ops_natural.py", "natural", "complete"), ("ops_natural_writes.py", "natural", "complete"), ("ops_reminders.py", "natural", "complete"),
                 ("ops_turn.py", "ops_natural", "_complete")}      # (file, the name the attribute is read from, the attribute): the time engine's own `natural.complete`, a reminder's or a write's draft completed with a time; and (S41-3) the row `draft-answer` calling `ops_natural._complete`, the same draft's completion that `ops_natural.take` called as a bare name. Any other route name, or the same name read from another object, is still a way in
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
    """(file, line) of every way into the daily route that the python files of `folder` (runtime/*.py and runtime/handlers/*.py) hold, found by the shape of the code and not by a name it was
    bound to: any attribute `complete`, `_complete`, `_complete_account` or `account_text` (the route's call, its two private helpers and the lab's text runner), however the module was
    reached (a name, `importlib.import_module(...)` itself, `sys.modules[...]`, an alias, a function taken by `f = module.complete`), except the reminders' own `natural.complete` of the
    the files in NOT_THE_ROUTE; the same names as a string given to `getattr` or as a subscript; `from interpreter_route import *`, and `from interpreter_route import <one of those names>`;
    any import of `interpreter_measure` (a statement, `importlib.import_module`, `__import__`, `sys.modules`, a `from ... import interpreter_measure`); and `sys.modules` read for
    `interpreter_route`. The files that may hold them are in THE_GATE_AND_THE_LAB; the caller of this function says which are allowed."""
    found = []
    for path in sorted(list(folder.glob("*.py")) + list(folder.glob("handlers/*.py"))):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            hit = False
            if isinstance(node, ast.Attribute):
                hit = node.attr in ROUTE_NAMES and not (isinstance(node.value, ast.Name) and (path.name, node.value.id, node.attr) in NOT_THE_ROUTE)
            elif isinstance(node, ast.ImportFrom):
                names = {a.name for a in node.names}
                if node.module == "interpreter_route":
                    hit = bool(names & (ROUTE_NAMES | {"*"}))
                elif node.module == "interpreter_measure" or "interpreter_measure" in names:
                    hit = True
            elif isinstance(node, ast.Import):
                hit = any(a.name.split(".")[-1] == "interpreter_measure" for a in node.names)
            elif isinstance(node, ast.Call):
                args = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                if "interpreter_measure" in args:
                    hit = True      # importlib.import_module("interpreter_measure"), __import__("interpreter_measure"), sys.modules.get("interpreter_measure")
                elif isinstance(node.func, ast.Name) and node.func.id == "getattr" and args and args[-1] in ROUTE_NAMES:
                    hit = True
                elif isinstance(node.func, ast.Attribute) and node.func.attr == "get" and is_sys_modules(node.func.value) and set(args) & MODULE_NAMES:
                    hit = True
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                hit = node.slice.value in ROUTE_NAMES or (is_sys_modules(node.value) and node.slice.value in MODULE_NAMES)
            if hit:
                found.append((path.name, node.lineno))
    return found


def is_sys_modules(node) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "modules" and isinstance(node.value, ast.Name) and node.value.id == "sys"


def test_only_the_gate_calls_the_daily_route():
    named = routes_named(RUNTIME)
    assert {"turn_gate.py", "interpreter_measure.py", "interpreter_route.py"} <= {name for name, _ in named}, named      # the control: the scan sees the three that hold them today
    assert [n for n in named if n[0] not in THE_GATE_AND_THE_LAB] == [], "no other module reaches the route, its helpers or the lab's measuring tool"


def mint_named(folder: Path) -> list:
    """(file, line) of every reference to `_MINT` or `Admission` (a name or an attribute) in the python files of `folder`: the mint is the gate's."""
    found = []
    for path in sorted(list(folder.glob("*.py")) + list(folder.glob("handlers/*.py"))):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if (isinstance(node, ast.Name) and node.id in MINT_NAMES) or (isinstance(node, ast.Attribute) and node.attr in MINT_NAMES):
                found.append((path.name, node.lineno))
    return found


def test_no_module_but_the_gate_makes_or_names_an_admission():
    """`_MINT` and `Admission` are the gate's: a module that made its own admission would call the route with one the gate never counted (tests may mint)."""
    named = mint_named(RUNTIME)
    assert named and {name for name, _ in named} == {"turn_gate.py"}, named


PLANTS = {
    "ops_interpret.py": 'def p1():\n    return importlib.import_module("interpreter_route").complete("r", "s", "u", accepted=[], deadline_ms=1)\n',
    "mail_compose.py": 'def p2():\n    f = interpreter_route.complete\n    return f("r", "s", "u", accepted=[], deadline_ms=1)\n',
    "mail_revise.py": 'def p3():\n    return sys.modules["interpreter_route"].complete("r", "s", "u", accepted=[], deadline_ms=1)\n',
    "ops_event_revise.py": 'def p4():\n    return getattr(importlib.import_module("interpreter_route"), "complete")("r", "s", "u", accepted=[], deadline_ms=1)\n',
    "ops_card_revise.py": 'def p5():\n    route: object = importlib.import_module("interpreter_route")\n    return route.complete("r", "s", "u", accepted=[], deadline_ms=1)\n',
    "ops_say.py": 'def p6():\n    from interpreter_route import *\n    return complete("r", "s", "u", accepted=[], deadline_ms=1)\n',
    "ops_items.py": 'def p7():\n    import interpreter_measure\n    return interpreter_measure._complete({"id": "r"}, [], {}, "s", "u")\n',
    "ops_files.py": 'def p8():\n    return interpreter_route._complete_account(interpreter_route.find("r"), "s", "u", [], None)\n',
    "ops_ask.py": 'def p9():\n    return importlib.import_module("interpreter_measure")\n',
    "ops_research.py": 'def p10():\n    return sys.modules.get("interpreter_measure")\n',
    "ops_reads.py": 'def p11():\n    return lab.account_text({}, "s", "u")\n',
    "ops_sources.py": 'def p12():\n    return turn_gate.Admission(turn_gate._MINT)\n',
    "ops_cancel.py": 'def p13():\n    return vars(interpreter_route)["complete"]\n',
}


def test_vacuity_the_scan_finds_every_planted_way_in_in_a_scratch_copy(tmp_path):
    copy = tmp_path / "runtime"
    (copy / "handlers").mkdir(parents=True)
    for path in list(RUNTIME.glob("*.py")) + list(RUNTIME.glob("handlers/*.py")):
        shutil.copy(path, copy / path.relative_to(RUNTIME))
    for name, text in PLANTS.items():
        assert (copy / name).exists(), name
        with open(copy / name, "a", encoding="utf-8") as handle:
            handle.write("\n\n" + text)
    outside = ({name for name, _ in routes_named(copy)} - THE_GATE_AND_THE_LAB) | {name for name, _ in mint_named(copy)} - {"turn_gate.py"}
    assert outside == set(PLANTS), set(PLANTS) ^ outside


def test_the_allowance_of_the_ops_turn_draft_row_is_one_attribute_of_one_name_and_nothing_else(tmp_path):
    """S41-3. The exemption is the triple (file, name, attribute): `ops_natural._complete` in ops_turn.py is the draft's completion; any other route name read from `ops_natural`, and an alias that is
    named `ops_natural` but is the daily route, are still ways in."""
    folder = tmp_path / "runtime"
    folder.mkdir()
    base = (RUNTIME / "ops_turn.py").read_text(encoding="utf-8")
    (folder / "ops_turn.py").write_text(base, encoding="utf-8")
    assert routes_named(folder) == [], "the draft row as it is: not a way in"
    for planted in ('\n\ndef _planted():\n    ops_natural = importlib.import_module("interpreter_route")\n    return ops_natural.complete("r", "s", "u", accepted=[], deadline_ms=1)\n',
                    '\n\ndef _planted():\n    return ops_natural.account_text("r", "s")\n',
                    '\n\ndef _planted():\n    return ops_natural._complete_account("r", "s")\n'):
        (folder / "ops_turn.py").write_text(base + planted, encoding="utf-8")
        assert [name for name, _ in routes_named(folder)] == ["ops_turn.py"], planted


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


def test_a_call_asked_for_without_an_admission_makes_no_call_and_counts_nothing_against_the_breaker(monkeypatch):
    """E_GATE is a fault of the caller, not of the provider: three of them never open the breaker, and `admission` has no default."""
    import inspect
    assert inspect.signature(ops_interpret._ask_model).parameters["admission"].default is inspect.Parameter.empty
    asked = []
    monkeypatch.setattr(interpreter_route, "complete", lambda *a, **k: asked.append(1) or {"ok": True, "text": NONE})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: "America/Sao_Paulo")
    entry = {"route": "or-deepseek-v4.1-flash", "route_sha256": "0" * 64}
    for _ in range(turn_gate.BREAKER_FAILS + 1):
        assert ops_interpret._ask_model({"cfg": {}}, entry, "hello there", None, None) is None
    assert asked == [] and turn_gate._breaker == {"fails": 0, "until": 0.0}
