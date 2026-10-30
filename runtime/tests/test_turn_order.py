"""The table of the order in which the bridge claims a line (packages S41-2 and S41-8): runtime/turn_order.py (the data) and runtime/messaging_turn.py (the dispatcher and the code of the rows and of the kinds).

WHAT IS CHECKED. (1) The table is well formed: names are unique, each row of the bridge stages has a row of code in `messaging_turn` and each row of code a name (the stage `ops` is read by runtime/tests/test_ops_turn.py), the bridge names are the ones the entry kit's trace uses, the module is pure data
(standard library only; AST), the dispatcher reaches no operations module (AST). (2) The dispatcher behaves as the chain it replaced: the first row that takes a line ends the dispatch, an exception
of a row propagates and `Bridge.handle_safely` logs it and nothing after it runs. (3) Every row is load-bearing: with its code replaced by "takes nothing", at least one scenario of the entry corpus
no longer has the outcome of the golden (a row no scenario needs is a corpus gap, reported, never a pass). (4) The row `frame` is load-bearing (the order of its kinds, in runtime/tests/test_frame_dispatch.py: limits L64 and L65). (5) The trace the table gives (`messaging_turn.TRACE`) is the trace the kit records by wrapping the methods, on every messaging scenario (`bridge_trace_problems`: run once per scenario, with the other observers, by `test_entry_observed.py`). (6) S41-8: the seven claimers that answered what is open
are the kinds of the one row `frame` (`FRAME_KINDS`): names unique, each with code that has `applies` and `take`, the seven retired names named with their replacement; the kinds' own tests (the
order of adjacent kinds, each kind load-bearing, the envelope read once) are runtime/tests/test_frame_dispatch.py.

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
FRAME_ROW = "frame"
FRAME_TRACE = tuple(ek.FRAME_KIT_NAMES[kind] for kind in turn_order.kinds())      # the names the kit's trace and the golden give the claimers the row `frame` took over
FINAL = {"bridge": "say", "bridge-say": "say-queue", "ops": "planning-agent"}      # the last row of a stage always takes the line
BRIDGE_STAGES = ("bridge", "bridge-say")      # the stages `messaging_turn` dispatches; the stage `ops` is dispatched by `ops_turn` (test_ops_turn.py)


# --- the table is well formed ------------------------------------------------------------------------------------------------------------------------


def test_the_table_is_a_tuple_of_rows_with_unique_names_and_every_row_has_code_and_every_code_a_row():
    assert isinstance(turn_order.ORDER, tuple) and isinstance(turn_order.RETIRED, tuple)
    assert all(row["stage"] in turn_order.STAGES and row["what"].strip() for row in turn_order.ORDER)
    assert all(set(row) == ({"name", "stage", "what", "channels"} if row["stage"] == "ops" else {"name", "stage", "what"}) for row in turn_order.ORDER), "a row of the stage ops names the shells it applies to; the bridge rows do not"
    assert all(row["channels"] and set(row["channels"]) <= set(turn_order.SHELLS) for row in turn_order.ORDER if row["stage"] == "ops")
    every = [row["name"] for row in turn_order.ORDER]
    assert len(every) == len(set(every)), "a name is the row of one stage only"
    assert set(messaging_turn.ROWS) == {row["name"] for row in turn_order.ORDER if row["stage"] in BRIDGE_STAGES}, "every row of the bridge stages has its code, and no code is without a row"
    for stage in turn_order.STAGES:
        found = turn_order.names(stage)
        assert isinstance(found, tuple) and found and found[-1] == FINAL[stage], f"the last row of {stage} is the one that always takes the line"
    assert {row["name"] for row in turn_order.RETIRED} == {"s20-verb-lists", "write-form", "write-form-ops", "say-natural"} | (set(FRAME_TRACE) - {"card-again"}), "one claimer left before the table existed (S41-3), the seven of the frame left in S41-8; S41-11 adds its own, each with its replacement"


def read_as_claimers(names) -> tuple:
    """The names of the rows of the stage `bridge`, the row `frame` read as the seven claimers it took over (the names of the kit and the golden), in the order of the kinds."""
    return tuple(claimer for name in names for claimer in (FRAME_TRACE if name == FRAME_ROW else (name,)))


def test_the_bridge_names_are_the_ones_of_the_entry_kit_in_the_same_order():
    assert read_as_claimers(turn_order.names("bridge")) == ek.BRIDGE_NAMES
    assert turn_order.names("bridge-say") == ek.BRIDGE_SAY_NAMES
    assert read_as_claimers(turn_order.names("bridge")) + turn_order.names("bridge-say") == tuple(n for n in ek.CLAIMER_NAMES if n in ek.BRIDGE_NAMES + ek.BRIDGE_SAY_NAMES)
    assert len(turn_order.names("bridge")) == 23 and len(turn_order.names("bridge-say")) == 4, "31 rows before S41-8, the seven of the frame replaced by one, and S41-11 took `write-form` and `say-natural` out"
    assert turn_order.names("bridge").count(FRAME_ROW) == 1 and len(FRAME_TRACE) == 8


def test_the_frame_kinds_are_unique_each_has_code_and_the_retired_claimers_name_the_frame():
    """S41-8. The kinds of the row `frame`: names unique, in the table (`FRAME_KINDS`) and in the code (`messaging_turn.KINDS`) alike, each with an `applies` and a `take`, one name in the kit for each;
    the seven claimers they replace are retired with the frame as their replacement and a date (L63(3): a claimer is never dropped silently); the project switch, the help in words and the line about a
    file just sent are not answers to what is open and stay rows of their own."""
    names = [kind["name"] for kind in turn_order.FRAME_KINDS]
    assert len(names) == len(set(names)) == 8 and turn_order.kinds() == tuple(names)
    assert all(kind["what"].strip() for kind in turn_order.FRAME_KINDS)
    assert set(messaging_turn.KINDS) == set(names), "every kind has its code, and no code is without a kind"
    assert all(callable(kind.applies) and callable(kind.take) for kind in messaging_turn.KINDS.values())
    assert set(ek.FRAME_KIT_NAMES) == set(names) and len(set(ek.FRAME_KIT_NAMES.values())) == 8
    retired = {row["name"]: row for row in turn_order.RETIRED}
    for claimer in set(FRAME_TRACE) - {"card-again"}:      # ACEITE-37: the eighth kind never was a row, so it is not retired
        assert retired[claimer]["replaced_by"] == turn_order.FRAME_REPLACEMENT and "FRAME_KINDS" in turn_order.FRAME_REPLACEMENT and retired[claimer]["date"] == "2026-10-26"
        assert claimer not in turn_order.names("bridge"), f"{claimer} is no row any more"
    assert turn_order.names("bridge")[turn_order.names("bridge").index(FRAME_ROW) + 1:][:3] == ("project-switch", "help-in-words", "attachment-line")


def test_an_unknown_stage_is_refused():
    with pytest.raises(ValueError):
        turn_order.names("nowhere")


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
    assert found == {"__future__", "card_words", "command_words", "greeting", "messaging_inbound", "messaging_provider", "natural", "natural_writes", "phone_delete", "turn_order"}, found
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
    called = stub_rows(monkeypatch, "bridge", {"project-switch": True, "say": True})
    assert messaging_turn.dispatch(None, messaging_turn.Turn()) == "project-switch"
    assert called == list(turn_order.names("bridge")[:turn_order.names("bridge").index("project-switch") + 1]), "the rows run in the table's order and none after the one that took the line"
    assert seen == ["project-switch"], "the trace is told the row that took the line, once"


def test_an_exception_of_a_row_propagates_and_no_later_row_runs(monkeypatch):
    called = stub_rows(monkeypatch, "bridge", {FRAME_ROW: RuntimeError, "say": True})
    with pytest.raises(RuntimeError):
        messaging_turn.dispatch(None, messaging_turn.Turn())
    assert called[-1] == FRAME_ROW


def test_a_stage_whose_last_row_takes_nothing_is_an_error_never_a_silent_drop(monkeypatch):
    stub_rows(monkeypatch, "bridge-say", {})
    with pytest.raises(RuntimeError):
        messaging_turn.dispatch(None, messaging_turn.Turn(), stage="bridge-say")


def test_the_dispatcher_reads_the_table_at_each_call(monkeypatch):
    called = stub_rows(monkeypatch, "bridge", {"say": True, "ignore": True})
    monkeypatch.setattr(turn_order, "names", lambda stage: ("say", "ignore"))
    assert messaging_turn.dispatch(None, messaging_turn.Turn()) == "say" and called == ["say"]


class Double:
    """Enough of a bridge for `_handle` to reach the kind `plan-confirm` of the frame: the real `handle_safely`, `handle` and `_handle`, and stand-ins for what they call."""
    DROPPED = bridge.Bridge.DROPPED
    handle_safely, handle, _handle = bridge.Bridge.handle_safely, bridge.Bridge.handle, bridge.Bridge._handle
    Fatal = bridge.Fatal

    def __init__(self):
        self.log_lines, self.reached = [], []
        self.ledger = SimpleNamespace(by_message=self.by_message)
        self.remind = SimpleNamespace(discarded=set(), drafts={}, expired={})
        self.messenger = SimpleNamespace(capabilities=lambda: {})
        self.last_sent = {"1": "m1"}      # the question the "sim" would answer is the last message: the kind reads its record

    def log(self, text):
        self.log_lines.append(text)

    @contextlib.contextmanager
    def read_once(self):
        yield

    def projects_for(self, sender):
        return [{"id": "p1"}]

    def project_of(self, sender, listed):
        return listed[0]

    def sentences_for(self, chat, project=None):      # TT-2: the scope of the sender's sentence language; none is read here
        return contextlib.nullcontext()

    def write_open(self, project, chat):
        return False

    def by_message(self, chat, message):
        raise RuntimeError("the plan question could not be read")

    def word_last(self, *args):
        self.reached.append("word_last")
        return True

    word_reply = word_last


def test_a_row_that_raises_is_logged_by_handle_safely_and_nothing_after_it_runs():
    """Probe 3 of the review: the kind `plan-confirm` of the frame raises (its question could not be read): `handle_safely` logs the class, and the card words (the next kind) never run."""
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
SAME_EFFECT_AS_A_LATER_ROW = {}      # S41-11 retired `say-natural`, the one row of this kind: its work is the row `say`'s


@pytest.mark.parametrize("name", [n for n in turn_order.names("bridge") + turn_order.names("bridge-say") if n not in FINAL.values() and n not in SAME_EFFECT_AS_A_LATER_ROW and n != FRAME_ROW])
def test_every_row_is_load_bearing_disabling_it_changes_a_scenario(name, tmp_path):
    scenarios = lines_of(name)
    assert scenarios, f"the corpus holds lines the row {name} takes (a corpus gap otherwise: add scenarios to entry_corpus_build.py, record on the unchanged base with the supervisor's agreement)"
    assert changed(disabling(name), scenarios, tmp_path), f"no scenario of the corpus needs the row {name}"


def test_the_row_frame_is_load_bearing_and_each_of_its_kinds_is_too(tmp_path):
    """The row `frame` stands for seven claimers: with the whole row disabled, a line each of them takes in the golden changes an outcome (the corpus names those lines by the kit's names for the
    claimers). One kind at a time, and the order of two neighbouring kinds, are runtime/tests/test_frame_dispatch.py."""
    for claimer in FRAME_TRACE:
        scenarios = lines_of(claimer, 8)
        assert scenarios, f"the corpus holds lines {claimer} takes"
        assert changed(disabling(FRAME_ROW), scenarios, tmp_path), f"no scenario of {claimer} needs the row {FRAME_ROW}"


@pytest.mark.parametrize("stage", ["bridge", "bridge-say"])
def test_the_last_row_of_a_stage_always_takes_the_line(stage):
    assert messaging_turn.ROWS[FINAL[stage]](SimpleNamespace(say=lambda *a: None, say_queue=lambda *a: None), SimpleNamespace(project={}, chat="1", text="x", intent={"text": "x"})) is True


# --- the table's trace is the kit's trace --------------------------------------------------------------------------------------------------------------


def bridge_trace_hook(got):
    """A hook that records, in `got`, `(name, rewritten)` of every row of the bridge that took the line, through `messaging_turn.TRACE`, on the thread that builds the hook (the one that replays the
    scenario): a typed line handed back by a job is another dispatch, on another thread, and the kit's first-event rule reads the first claim of the update."""
    mine = threading.current_thread()

    def trace(name, turn):
        if threading.current_thread() is mine:
            got.append((ek.FRAME_KIT_NAMES[turn.frame_kind] if name == FRAME_ROW else name, turn.rewritten))

    def hook(mp):
        mp.setattr(messaging_turn, "TRACE", trace)
    return hook


def bridge_trace_problems(results, recorded) -> list:
    """Item (5), run once per scenario with the other observers by `test_entry_observed.py`: `results` is `[(scenario, what bridge_trace_hook recorded)]`; `recorded` is the golden. On every messaging
    scenario of the corpus the rows that took the line, in the two stages, are the claimers the kit's wrappers recorded in the golden (the kit's marker of a reply to a card is the rewrite the row
    `reply-to-card` made, or the line was claimed before that row)."""
    bridge_names, say_names = set(read_as_claimers(turn_order.names("bridge"))), set(turn_order.names("bridge-say"))      # the row `frame` is the seven claimers it took over: its trace names the kind
    wrong, count = [], 0
    for scenario, got in results:
        if scenario["channel"] != "messaging":
            continue
        count += 1
        first_bridge = next(((n, r) for n, r in got if n in bridge_names), None)
        first_say = next((n for n, _ in got if n in say_names), None)
        table = (["reply-to-card"] if first_bridge and first_bridge[1] else []) + ([first_bridge[0]] if first_bridge else []) + ([first_say] if first_say else [])
        kit = [n for n in recorded[scenario["id"]]["trace"] if n in bridge_names or n in say_names]
        if table != kit:
            wrong.append(f"{scenario['id']}: table {table}, wrapped {kit}")
    found = list(wrong)
    if not count:
        found.append("no messaging scenario was seen")
    return found
