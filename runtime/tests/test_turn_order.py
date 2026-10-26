"""The table of the order in which the bridge claims a line (package S41-2): runtime/turn_order.py (the data) and runtime/messaging_turn.py (the dispatcher and the code of the rows).

WHAT IS CHECKED. (1) The table is well formed: names are unique, each has a row of code and each row of code a name, the bridge names are the ones the entry kit's trace uses, the module is pure data
(standard library only; AST), the dispatcher reaches no operations module (AST). (2) The dispatcher behaves as the chain it replaced: the first row that takes a line ends the dispatch, an exception
of a row propagates and `Bridge.handle_safely` logs it and nothing after it runs. (3) Every row is load-bearing: with its code replaced by "takes nothing", at least one scenario of the entry corpus
no longer has the outcome of the golden (a row no scenario needs is a corpus gap, reported, never a pass). (4) The order matters: swapping the OK of a plan and the card words, and the card words and
the research stop, changes a scenario (limits L64 and L65). (5) The trace the table gives (`messaging_turn.TRACE`) is the trace the kit records by wrapping the methods, on every messaging scenario.

NO CALLS. The scenarios are replayed by test_entry_replay.py's own functions, with the stand-ins of entry_kit.py: no model, no provider process. The golden is never recorded here.

Run: uv run --with pytest==9.1.1 --with pytest-xdist pytest -q -n 4 runtime/tests/test_turn_order.py
"""
from __future__ import annotations

import ast
import contextlib
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import entry_kit as ek
import standin_tree as st
import test_entry_replay as rp

bridge = st.load("messaging_bridge")
turn_order = st.load("turn_order")
messaging_turn = st.load("messaging_turn")

RUNTIME = Path(__file__).resolve().parents[1]
FINAL = {"bridge": "say", "bridge-say": "say-queue"}      # the last row of a stage always takes the line
SHARDS = rp.SHARDS


# --- the table is well formed ------------------------------------------------------------------------------------------------------------------------


def test_the_table_is_a_tuple_of_rows_with_unique_names_and_every_row_has_code_and_every_code_a_row():
    assert isinstance(turn_order.ORDER, tuple) and isinstance(turn_order.RETIRED, tuple)
    assert all(set(row) == {"name", "stage", "what"} and row["stage"] in turn_order.STAGES and row["what"].strip() for row in turn_order.ORDER)
    every = [row["name"] for row in turn_order.ORDER]
    assert len(every) == len(set(every)), "a name is the row of one stage only"
    assert set(messaging_turn.ROWS) == set(every), "every row of the table has its code, and no code is without a row"
    for stage in turn_order.STAGES:
        found = turn_order.names(stage)
        assert isinstance(found, tuple) and found and found[-1] == FINAL[stage], f"the last row of {stage} is the one that always takes the line"
    assert {row["name"] for row in turn_order.RETIRED} == set(), "nothing is retired yet (S41-8 and S41-11 fill it, each with its replacement)"


def test_the_bridge_names_are_the_ones_of_the_entry_kit_in_the_same_order():
    assert turn_order.names("bridge") == ek.BRIDGE_NAMES
    assert turn_order.names("bridge-say") == ek.BRIDGE_SAY_NAMES
    assert turn_order.names("bridge") + turn_order.names("bridge-say") == tuple(n for n in ek.CLAIMER_NAMES if n in turn_order.names("bridge") + turn_order.names("bridge-say"))
    assert len(turn_order.names("bridge")) == 31 and len(turn_order.names("bridge-say")) == 3


def test_an_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        turn_order.names("ops")


def test_the_module_prints_its_rows_and_its_help():
    help_text = subprocess.run([sys.executable, str(RUNTIME / "turn_order.py"), "--help"], capture_output=True, text=True, check=True).stdout
    assert "usage" in help_text.lower() and "--stage" in help_text
    rows = subprocess.run([sys.executable, str(RUNTIME / "turn_order.py"), "--stage", "bridge-say"], capture_output=True, text=True, check=True).stdout.splitlines()
    assert [line.split("\t")[1] for line in rows] == list(turn_order.names("bridge-say"))


def imported(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add((node.module or "").split(".")[0])
    return names


def test_the_table_imports_only_the_standard_library():
    runtime_modules = {p.stem for p in RUNTIME.glob("*.py")}
    found = imported(RUNTIME / "turn_order.py")
    assert found == {"__future__", "argparse", "sys"}, found
    assert not found & runtime_modules, "the table imports no module of runtime/"


def test_the_dispatcher_imports_no_operations_module():
    """The layer map (scripts/tests/test_layer_map.py) says it too; the names are checked here, where the reader looks."""
    found = imported(RUNTIME / "messaging_turn.py")
    assert found == {"__future__", "messaging_inbound", "messaging_provider", "natural", "phone_delete", "turn_order"}, found
    assert not {name for name in found if name.startswith("ops") or name in ("operations", "shell_kit", "messaging_bridge")}


# --- the dispatcher ----------------------------------------------------------------------------------------------------------------------------------


def stub_rows(monkeypatch, stage, results):
    """Replace the code of every row of `stage` by a function that records its call and answers what `results` says for its name (default False); an exception class in `results` is raised."""
    called = []
    for name in turn_order.names(stage):
        def row(b, t, name=name):
            called.append(name)
            result = results.get(name, False)
            if isinstance(result, type) and issubclass(result, Exception):
                raise result(name)
            return result
        monkeypatch.setitem(messaging_turn.ROWS, name, row)
    return called


def test_the_first_row_that_takes_the_line_ends_the_dispatch(monkeypatch):
    seen = []
    monkeypatch.setattr(messaging_turn, "TRACE", lambda name, turn: seen.append(name))
    called = stub_rows(monkeypatch, "bridge", {"card-word": True, "say": True})
    assert messaging_turn.dispatch(None, messaging_turn.Turn()) == "card-word"
    assert called == list(turn_order.names("bridge")[:turn_order.names("bridge").index("card-word") + 1]), "the rows run in the table's order and none after the one that took the line"
    assert seen == ["card-word"], "the trace is told the row that took the line, once"


def test_an_exception_of_a_row_propagates_and_no_later_row_runs(monkeypatch):
    called = stub_rows(monkeypatch, "bridge", {"plan-confirm-word": RuntimeError, "say": True})
    with pytest.raises(RuntimeError):
        messaging_turn.dispatch(None, messaging_turn.Turn())
    assert called[-1] == "plan-confirm-word"


def test_a_stage_whose_last_row_takes_nothing_is_an_error_never_a_silent_drop(monkeypatch):
    stub_rows(monkeypatch, "bridge-say", {})
    with pytest.raises(RuntimeError):
        messaging_turn.dispatch(None, messaging_turn.Turn(), stage="bridge-say")


def test_the_dispatcher_reads_the_table_at_each_call(monkeypatch):
    called = stub_rows(monkeypatch, "bridge", {"say": True, "ignore": True})
    monkeypatch.setattr(turn_order, "names", lambda stage: ("say", "ignore"))
    assert messaging_turn.dispatch(None, messaging_turn.Turn()) == "say" and called == ["say"]


class Double:
    """Enough of a bridge for `_handle` to reach `plan_line`: the real `handle_safely`, `handle` and `_handle`, and stand-ins for what they call."""
    DROPPED = bridge.Bridge.DROPPED
    handle_safely, handle, _handle = bridge.Bridge.handle_safely, bridge.Bridge.handle, bridge.Bridge._handle
    Fatal = bridge.Fatal

    def __init__(self):
        self.log_lines, self.reached = [], []
        self.ledger = SimpleNamespace(by_message=lambda chat, message: None)
        self.remind = SimpleNamespace(discarded=set(), drafts={}, expired={})

    def log(self, text):
        self.log_lines.append(text)

    @contextlib.contextmanager
    def read_once(self):
        yield

    def projects_for(self, sender):
        return [{"id": "p1"}]

    def project_of(self, sender, listed):
        return listed[0]

    def write_open(self, project, chat):
        return False

    def plan_line(self, *args):
        raise RuntimeError("the plan question could not be read")

    def word_line(self, *args):
        self.reached.append("word_line")
        return True


def test_a_row_that_raises_is_logged_by_handle_safely_and_nothing_after_it_runs():
    """Probe 3 of the review: patch `plan_line` to raise: `handle_safely` logs the class, and the card words (the next row) never run."""
    double = Double()
    double.handle_safely({"sender": "1", "chat": "1", "private": True, "text": "sim", "update_id": 3})
    assert double.log_lines == ["an update failed: RuntimeError"] and double.reached == []


def test_an_update_of_an_unlisted_sender_is_dropped_by_the_first_row_and_reads_nothing_else():
    double = Double()
    double.projects_for = lambda sender: []
    double.config_pending = lambda update, sender, chat: double.reached.append("config_pending")
    double.handle({"sender": "1", "chat": "2", "private": True, "text": "sim"})
    assert double.log_lines == [double.DROPPED] and double.reached == ["config_pending"]


# --- every row is load-bearing, and the order matters -------------------------------------------------------------------------------------------------


def changed(hook, scenarios, tmp_path) -> list:
    """The ids of the scenarios whose outcome is not the golden's with `hook` in force, stopping at the first (an exception counts: a row that is gone and breaks the line is a change)."""
    _, recorded = rp.golden()
    for scenario in scenarios:
        try:
            found = rp.replay(scenario, tmp_path, hook)
        except Exception:      # noqa: BLE001 - the line broke: the outcome is not the golden's
            return [scenario["id"]]
        if rp.differences(recorded[scenario["id"]], found):
            return [scenario["id"]]
    return []


def disabling(name):
    def hook(mp):
        mp.setitem(messaging_turn.ROWS, name, lambda b, t: False)
    return hook


def lines_of(name, limit=60) -> list:
    return rp.scenarios_of(name, limit)


# A row whose effect is the effect of a later row: the original chain had two branches that both call `say` with the line's text (`elif kind == "natural"` ... `else`), so with the row disabled
# the later one does the same and no outcome field differs: the corpus can see that the row took the line only in the table's own trace (the test below).
SAME_EFFECT_AS_A_LATER_ROW = {"say-natural": "say"}


@pytest.mark.parametrize("name", [n for n in turn_order.names("bridge") + turn_order.names("bridge-say") if n not in FINAL.values() and n not in SAME_EFFECT_AS_A_LATER_ROW])
def test_every_row_is_load_bearing_disabling_it_changes_a_scenario(name, tmp_path):
    scenarios = lines_of(name)
    assert scenarios, f"the corpus holds lines the row {name} takes (a corpus gap otherwise: add scenarios to entry_corpus_build.py, record on the unchanged base with the supervisor's agreement)"
    assert changed(disabling(name), scenarios, tmp_path), f"no scenario of the corpus needs the row {name}"


@pytest.mark.parametrize("name, later", sorted(SAME_EFFECT_AS_A_LATER_ROW.items()))
def test_a_row_with_the_effect_of_a_later_row_changes_the_trace_of_the_table_only(name, later, tmp_path):
    """`say-natural` and `say` call `Bridge.say` with the same text: disabled, the later row takes the line and the outcome is the golden's; the table's trace names the later row (and the kit, which
    names a claimer from the kind of the line, still says `say-natural`: it is not a trace of the table). If a scenario's outcome ever differs, the two have stopped being the same and this test says so."""
    _, recorded = rp.golden()
    scenarios = lines_of(name, 6)
    assert scenarios, f"the corpus holds lines the row {name} takes"
    taken = []
    for scenario in scenarios:
        got = []
        mine = threading.current_thread()

        def hook(mp, got=got, mine=mine):
            mp.setitem(messaging_turn.ROWS, name, lambda b, t: False)
            mp.setattr(messaging_turn, "TRACE", lambda n, t: got.append(n) if threading.current_thread() is mine else None)
        found = rp.replay(scenario, tmp_path, hook)
        assert not rp.differences(recorded[scenario["id"]], found), f"{scenario['id']}: {name} and {later} no longer have the same effect"
        taken.append(next(n for n in got if n in turn_order.names("bridge")))
    assert set(taken) == {later}, f"with {name} disabled the line is taken by {later}"


@pytest.mark.parametrize("stage", ["bridge", "bridge-say"])
def test_the_last_row_of_a_stage_always_takes_the_line(stage):
    assert messaging_turn.ROWS[FINAL[stage]](SimpleNamespace(say=lambda *a: None, say_queue=lambda *a: None), SimpleNamespace(project={}, chat="1", text="x", intent={"text": "x"})) is True


def swapped(first, second):
    def hook(mp):
        order = list(turn_order.names("bridge"))
        a, b = order.index(first), order.index(second)
        order[a], order[b] = order[b], order[a]
        mp.setattr(turn_order, "names", lambda stage, order=tuple(order), real=turn_order.names: order if stage == "bridge" else real(stage))
    return hook


@pytest.mark.parametrize("first, second", [("card-word", "research-stop"), ("plan-confirm-word", "research-stop")])
def test_the_order_matters_two_rows_that_swap_change_a_scenario(first, second, tmp_path):
    """L64 and L65: the research stop is read after the card words (a "no" with a card as the last message rejects the card and leaves the search alone), and after the OK of a plan. Swapped, a
    line the golden has taken by one of the two is taken by the other, and the outcome differs."""
    _, recorded = rp.golden()
    scenarios = [s for s in rp.corpus() if {first, second} & set(recorded[s["id"]]["trace"])]
    assert scenarios, "the corpus holds lines that one of the two takes"
    assert changed(swapped(first, second), scenarios, tmp_path), f"swapping {first} and {second} changes no scenario: the corpus does not see this order"


def test_the_ok_of_a_plan_and_the_card_words_never_take_the_same_line_so_their_swap_is_not_seen(tmp_path):
    """SPEC-41-2 asked for a swap of `plan-confirm-word` and `card-word` that changes a scenario. It cannot: the two claimers are disjoint by their own conditions in the code that was moved, not by
    their place. `plan_line` takes only a ledger record of kind `plan-confirm`; `word_line` decides only a decision card (`word_reply` and `word_cards` refuse every kind of `NOT_DECISION`, which
    holds `plan-confirm`) and, with a plan that waits and a card sent after it, answers `PLAN_TWO_OPEN` without deciding. This test records that finding on every scenario that either takes: the swap
    changes none. If a later package lets the two overlap, this test fails and the order must be reconsidered with the contract's L64 and L65 in hand."""
    _, recorded = rp.golden()
    scenarios = [s for s in rp.corpus() if {"plan-confirm-word", "card-word"} & set(recorded[s["id"]]["trace"])]
    assert len(scenarios) >= 40 and {s["prestate"] for s in scenarios} >= {"plan_last", "plan_not_last", "plan_then_card", "card_last", "two_cards"}
    assert not changed(swapped("plan-confirm-word", "card-word"), scenarios, tmp_path)


# --- the table's trace is the kit's trace --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("shard", range(SHARDS))
def test_the_table_trace_equals_the_wrapped_trace(shard, tmp_path):
    """On every messaging scenario of the corpus the rows that took the line, in the two stages, are the claimers the kit's wrappers recorded in the golden (the kit's marker of a reply to a card
    is the rewrite the row `reply-to-card` made, or the line was claimed before that row)."""
    _, recorded = rp.golden()
    bridge_names, say_names = set(turn_order.names("bridge")), set(turn_order.names("bridge-say"))
    wrong, count = [], 0
    for scenario in rp.shard_of(rp.corpus(), shard):
        if scenario["channel"] != "messaging":
            continue
        got = []
        mine = threading.current_thread()

        def trace(name, turn, got=got, mine=mine):
            if threading.current_thread() is mine:      # a typed line handed back by a job is another dispatch, on another thread: the kit's first-event rule reads the first claim of the update
                got.append((name, turn.rewritten))

        def hook(mp, trace=trace):
            mp.setattr(messaging_turn, "TRACE", trace)
        rp.replay(scenario, tmp_path, hook)
        count += 1
        first_bridge = next(((n, r) for n, r in got if n in bridge_names), None)
        first_say = next((n for n, _ in got if n in say_names), None)
        table = (["reply-to-card"] if first_bridge and first_bridge[1] else []) + ([first_bridge[0]] if first_bridge else []) + ([first_say] if first_say else [])
        kit = [n for n in recorded[scenario["id"]]["trace"] if n in bridge_names or n in say_names]
        if table != kit:
            wrong.append(f"{scenario['id']}: table {table}, wrapped {kit}")
    assert count and not wrong, f"{len(wrong)} of {count} scenarios of shard {shard} have another trace:\n" + "\n".join(wrong[:12])
