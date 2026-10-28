"""The table of the order in which the operations layer claims a line (package S41-3): the stage `ops` of runtime/turn_order.py, dispatched by runtime/ops_turn.py, and limit L63(3) read against it.

WHAT IS CHECKED. (1) The stage is well formed: each row of the stage has code in `ops_turn.ROWS` and each code a row, the names are the entry kit's `OPS_NAMES` in order, the last row always takes
the line, the module is called at call time by `ops_say` and imports no module that closes a cycle (AST). `_turn` and `ops_natural.take` are gone. (2) The dispatcher walks the table: the first row that
takes a line ends the dispatch, a row whose `channels` excludes the shell is skipped (every row of the real table, on every shell), an exception of a row propagates, a stage whose last row takes nothing
is an error. (3) `code_claims`, the queue decision `handled` of `say`, equals the expression `say` had (a frozen copy, below) on every scenario of the entry corpus (`claims_problems`: run once per scenario, with the other observers, by `test_entry_observed.py`). (4) Limit L63(3) is the table: the
contract's L63 row lists the names of `turn_order.ORDER` in order and names every retired claimer with its replacement; the check is shown to fail when a name is left out, swapped or added, and when the
row is edited (the mirror of the row in docs/architecture/platform/runtime.md is read the same way). (5) Every row is load-bearing (with its code replaced by "takes nothing" at least one scenario no longer
has the golden's outcome) and the order matters (four swaps change a scenario of the corpus). (6) Page, terminal, chat and mcp lines pass through the same order and never reach the interpreter: the trace holds no `interpreter`
and the stand-in model is never asked, with `ops_interpret.enabled` left as it is, and the row stays out of their reach when `enabled` is wrongly true (the table and `enabled` are two layers of L63(1)).
(7) The trace the table gives (`ops_turn.TRACE`) is the trace the kit records by wrapping the methods, on every scenario of the corpus (`ops_trace_problems`: run once per scenario, with the other observers, by `test_entry_observed.py`).

NO CALLS. The scenarios are replayed by test_entry_replay.py's own functions, with the stand-ins of entry_kit.py: no model, no provider process. The golden is never recorded here.

Run: uv run --with pytest==9.1.1 --with pytest-xdist pytest -q -n 4 runtime/tests/test_ops_turn.py
"""
from __future__ import annotations

import ast
import re
import threading
from pathlib import Path

import pytest

import entry_kit as ek
import standin_tree as st
import test_entry_replay as rp
import test_turn_order as bridge_side

turn_order = st.load("turn_order")
ops_turn = st.load("ops_turn")
ops_say = st.load("ops_say")
ops_natural = st.load("ops_natural")
ops_interpret = st.load("ops_interpret")
natural = st.load("natural")
ops_instructions = st.load("ops_instructions")
real_interpreter = ops_turn.ROWS["interpreter"]
real_talk_refusal = ops_turn.ROWS["talk-refusal"]

RUNTIME = Path(__file__).resolve().parents[1]
REPO = RUNTIME.parent
SHARDS = rp.SHARDS
OPS = turn_order.names("ops")
FINAL = "planning-agent"
CONTRACT = REPO / "contracts" / "runtime.md"
MIRROR = REPO / "docs" / "architecture" / "platform" / "runtime.md"


# --- the stage is well formed -----------------------------------------------------------------------------------------------------------------------


def test_every_row_of_the_stage_has_code_and_every_code_a_row_in_the_kits_order():
    assert set(ops_turn.ROWS) == set(OPS), "every row of the stage has its code, and no code is without a row"
    assert OPS == ek.OPS_NAMES, "the names are the ones the entry kit's trace uses, in the same order"
    assert OPS == tuple(n for n in ek.CLAIMER_NAMES if n in OPS)
    assert len(OPS) == 15 and OPS[-1] == FINAL, "the last row of the stage is the one that always takes the line"
    assert OPS[0] == ops_turn.EARLY == "confirmed-plan", "the OK of a plan is the first row, and runs out of the dispatch of the turn"
    assert set(ops_turn.TAKE_ROWS) <= set(OPS) and ops_turn.TAKE_ROWS == tuple(n for n in OPS if n in ops_turn.TAKE_ROWS), "the five rows that were `ops_natural.take`, in the table's order"


def test_the_channels_of_the_rows_are_the_shells_the_code_reads():
    expected = {"confirmed-plan": {"messaging"}, "plan-bare-word": {"messaging"}, "delete-file": {"messaging"}, "event-list-number": {"messaging"}, "file-list-number": {"messaging"},
                "interpreter": {"messaging"}, "write-form-ops": set(turn_order.SHELLS) - {"mcp"}}
    for name in OPS:
        assert set(turn_order.channels(name)) == expected.get(name, set(turn_order.SHELLS)), name
    assert set(turn_order.SHELLS) == {"messaging", "page", "terminal", "mcp", "chat", "queue"}
    assert turn_order.channels("drop-unlisted") == ("messaging",), "a row of the bridge is the messaging bridge's"
    with pytest.raises(ValueError):
        turn_order.channels("no-such-row")


def test_the_turn_and_take_are_gone_and_say_calls_the_table():
    assert not hasattr(ops_say, "_turn") and not hasattr(ops_natural, "take"), "`_turn` and `ops_natural.take` are rows of the table now"
    assert callable(ops_say._say_confirmed) and callable(ops_say._greeting_reply), "the bodies the rows call stay where they were"
    text = (RUNTIME / "ops_say.py").read_text(encoding="utf-8")
    assert "turns.dispatch(" in text and "turns.code_claims(" in text and "turns.confirmed(" in text and "_turns().dispatch(" in text, "`say` and the queue's drain dispatch from the table"


def module_level_imports(path: Path) -> set:
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add((node.module or "").split(".")[0])
    return names


def test_ops_turn_adds_no_module_level_import_that_joins_the_import_cycle():
    """Probe 5 of the review. `ops_say` and `ops_natural` reach `ops.py` and each other at call time; `ops_say` reaches this module at call time; this module imports only `turn_order`
    (pure), three pure leaves of the standard library alone (`drafts`, `greeting`, `phone_delete`) and modules `ops_say` or `ops_natural` already import at module level, none of which imports `ops_say` or this module."""
    found = module_level_imports(RUNTIME / "ops_turn.py")
    assert found == {"__future__", "importlib", "sys", "drafts", "greeting", "natural", "operations", "ops_natural", "phone_delete", "phone_refusal", "phrases", "plan_confirm", "turn_order"}, found
    assert not {"ops", "ops_say", "ops_core", "ops_interpret", "messaging_bridge", "messaging_turn", "event_lookup", "ops_file_read"} & found
    say_top = module_level_imports(RUNTIME / "ops_say.py")
    assert "ops_turn" not in say_top and "turn_order" not in say_top, "`ops_say` reaches the dispatcher at call time"
    natural_top = module_level_imports(RUNTIME / "ops_natural.py")
    leaves = {"drafts", "greeting", "phone_delete"}      # pure modules of the standard library alone: no cycle can pass through them
    for name in leaves:
        assert module_level_imports(RUNTIME / f"{name}.py") <= {"__future__", "re", "sys", "unicodedata", "collections", "threading", "time"}, name
    assert found - {"__future__", "importlib", "sys", "turn_order", "ops_natural"} - leaves <= say_top | natural_top, "every other module this one imports at module level is one `ops_say` or `ops_natural` imports at module level already"
    for name in ("ops_natural.py", "drafts.py", "greeting.py", "natural.py", "operations.py", "phone_delete.py", "phone_refusal.py", "phrases.py", "plan_confirm.py"):
        assert not {"ops_turn", "ops_say"} & module_level_imports(RUNTIME / name), f"{name} imports neither the dispatcher nor `ops_say` at module level"


def test_the_module_prints_its_text_and_the_table_prints_the_shells():
    import subprocess
    import sys
    help_text = subprocess.run([sys.executable, str(RUNTIME / "ops_turn.py"), "--help"], capture_output=True, text=True, check=True).stdout
    assert "dispatcher" in help_text
    rows = subprocess.run([sys.executable, str(RUNTIME / "turn_order.py"), "--stage", "ops"], capture_output=True, text=True, check=True).stdout.splitlines()
    assert [line.split("\t")[1] for line in rows] == list(OPS) and rows[0].split("\t")[3] == "messaging"


# --- the dispatcher ----------------------------------------------------------------------------------------------------------------------------------


def stub_rows(monkeypatch, results):
    """Replace the code of every row of the stage by a function that records its call and answers what `results` says for its name (default None); an exception class is raised."""
    called = []
    for name in OPS:
        def row(project, ctx, said, channel, sender, extras, state, name=name):
            called.append(name)
            result = results.get(name)
            if isinstance(result, type) and issubclass(result, Exception):
                raise result(name)
            return result
        monkeypatch.setitem(ops_turn.ROWS, name, row)
    return called


def test_the_first_row_that_takes_the_line_ends_the_dispatch_and_the_trace_names_it_once(monkeypatch):
    seen = []
    monkeypatch.setattr(ops_turn, "TRACE", lambda name, state: seen.append(name))
    called = stub_rows(monkeypatch, {"state-question": ("reply", None, None, False, None, None), FINAL: ("planner", None, None, False, None, None)})
    assert ops_turn.dispatch("p", {}, "line", "messaging", 1)[0] == "reply"
    assert called == list(OPS[1:OPS.index("state-question") + 1]), "the rows run in the table's order, `confirmed-plan` apart, and none after the one that took the line"
    assert seen == ["state-question"]


def test_a_row_whose_channels_exclude_the_shell_is_skipped_on_every_shell_of_the_real_table(monkeypatch):
    for shell in turn_order.SHELLS:
        called = stub_rows(monkeypatch, {FINAL: ("planner", None, None, False, None, None)})
        ops_turn.dispatch("p", {}, "line", shell, 1)
        assert called == [n for n in OPS if n != "confirmed-plan" and shell in turn_order.channels(n)], shell
    called = stub_rows(monkeypatch, {FINAL: ("planner", None, None, False, None, None)})
    ops_turn.dispatch("p", {}, "line", "page", 1)
    assert "interpreter" not in called and "plan-bare-word" not in called and "event-list-number" not in called, "a page line never reaches a row of the messaging shell"


def test_a_name_that_is_no_shell_never_reaches_a_row_of_the_messaging_shell_and_is_left_to_the_other_rows(monkeypatch):
    """Fail closed (L63(1)): a row whose channels are exactly the messaging shell's is skipped for every other name, the unknown ones included; the rows of every shell are left to their own conditions."""
    called = stub_rows(monkeypatch, {FINAL: ("planner", None, None, False, None, None)})
    ops_turn.dispatch("p", {}, "line", "somewhere-else", 1)
    assert called == [n for n in OPS if n != "confirmed-plan" and turn_order.channels(n) != turn_order.MESSAGING]
    assert "interpreter" not in called and "plan-bare-word" not in called


def test_an_unknown_shell_name_never_reaches_the_interpreter_even_when_the_line_is_deferred_to_it(monkeypatch):
    """The probe of the review: with the real `interpreter` row and a deferred line, the name `web` is kept away by the table, as `page` is; only `messaging` reaches the model's seam."""
    reached = []
    monkeypatch.setattr(ops_interpret, "turn", lambda project, ctx, said, sender, extras: reached.append(said) or None)
    called = stub_rows(monkeypatch, {FINAL: ("planner", None, None, False, None, None)})
    monkeypatch.setitem(ops_turn.ROWS, "interpreter", real_interpreter)
    for shell in ("page", "web", "messaging"):
        ops_turn.dispatch("p", {"cfg": {}}, f"{shell} line", shell, 1, None, {"deferred": True})
    assert reached == ["messaging line"]


def test_the_row_that_does_not_take_a_line_where_it_stands_sets_the_trace_name_of_its_line(monkeypatch):
    """`router-question` takes no line where it stands; the line it binds is taken by `planning-agent`, and the trace says `router-question` for it."""
    seen = []
    monkeypatch.setattr(ops_turn, "TRACE", lambda name, state: seen.append(name))
    monkeypatch.setattr(ops_say, "_say_route", lambda *a, **k: ("routed", 5, None, True, None))
    monkeypatch.setattr(ops_say, "_open_question", lambda ctx, channel, sender=None: {"id": 3})
    monkeypatch.setattr(ops_natural, "recognises", lambda *a: False)
    monkeypatch.setattr(ops_say, "may_talk", lambda *a: True)
    monkeypatch.setattr(ops_instructions, "proposal", lambda *a: None)
    for name in OPS:
        if name not in ("router-question", "planning-agent"):
            monkeypatch.setitem(ops_turn.ROWS, name, lambda *a: None)
    ops_turn.dispatch("p", {"cfg": {}}, "um evento", "page", 1)
    assert seen == ["router-question"]
    monkeypatch.setattr(ops_say, "_open_question", lambda ctx, channel, sender=None: None)
    seen.clear()
    ops_turn.dispatch("p", {"cfg": {}}, "um evento", "page", 1)
    assert seen == ["planning-agent"]


def test_an_exception_of_a_row_propagates_and_no_later_row_runs(monkeypatch):
    called = stub_rows(monkeypatch, {"greeting": RuntimeError, FINAL: ("planner",) + (None,) * 5})
    with pytest.raises(RuntimeError):
        ops_turn.dispatch("p", {}, "line", "page", 1)
    assert called[-1] == "greeting"


def test_a_stage_whose_last_row_takes_nothing_is_an_error_never_a_silent_drop(monkeypatch):
    stub_rows(monkeypatch, {})
    with pytest.raises(RuntimeError):
        ops_turn.dispatch("p", {}, "line", "page", 1)


def test_the_dispatcher_reads_the_table_at_each_call(monkeypatch):
    called = stub_rows(monkeypatch, {"command": ("c", None, None, False, None, None), "greeting": ("g", None, None, False, None, None)})
    monkeypatch.setattr(turn_order, "names", lambda stage: ("greeting", "command") if stage == "ops" else ())
    assert ops_turn.dispatch("p", {}, "line", "page", 1)[0] == "g" and called == ["greeting"]


def test_dispatch_rows_runs_the_named_rows_in_the_tables_order_and_answers_none_when_none_takes(monkeypatch):
    called = stub_rows(monkeypatch, {})
    assert ops_turn.dispatch_rows(("tier-1-form", "draft-answer"), "p", {}, "line", "messaging") is None
    assert called == ["draft-answer", "tier-1-form"], "the table's order, not the order of the names given"
    called.clear()
    assert ops_turn.dispatch_rows(ops_turn.TAKE_ROWS, "p", {}, "line", "page") is None and called == ["draft-answer", "write-form-ops", "tier-1-form"], "the rows of the messaging shell are skipped on the page"
    with pytest.raises(ValueError):
        ops_turn.dispatch_rows(("no-such-row",), "p", {}, "line", "page")


def test_confirmed_walks_the_first_row_only_and_says_none_when_the_row_is_gone_or_there_is_no_plan(monkeypatch):
    called = stub_rows(monkeypatch, {"confirmed-plan": {"reply": "ran"}})
    assert ops_turn.confirmed("p", {}, "sim", "owner", None, {"item": 1, "sha256": "x"}) == {"reply": "ran"} and called == ["confirmed-plan"]
    monkeypatch.setattr(turn_order, "names", lambda stage: tuple(n for n in OPS if n != "confirmed-plan"))
    called.clear()
    assert ops_turn.confirmed("p", {}, "sim", "owner", None, {"item": 1, "sha256": "x"}) is None and called == [], "a retired row runs no plan"
    monkeypatch.undo()
    assert ops_turn.confirmed_plan("p", {}, "sim", "messaging", "owner", {}, ops_turn.State("p", {}, "sim", "messaging", None, "owner", {})) is None, "no `plan_ok`: the row takes nothing"


# --- the queue decision ------------------------------------------------------------------------------------------------------------------------------


def old_handled(ctx, said, channel, sender, plan_before):
    """FROZEN. The expression `ops_say.say` computed `handled` with before package S41-3 (764c9a3:runtime/ops_say.py:187), copied with its callees read from `ops_say`: the queue decision of a plain
    line. It is never edited to follow `ops_turn.code_claims`: the test below says they are the same on every scenario."""
    import importlib
    return (ops_say.asks_natural(ctx, said, channel, sender) and not ops_natural.peek_model(ctx, said, ops_say._natural_channel(channel), sender)
            or ops_say._greets(ctx, said, channel, sender)
            or (channel == "messaging" and ops_say.may_talk(ctx, channel, sender) and importlib.import_module("ops_file_trash").catches(ctx, said, channel, sender))
            or (plan_before and natural.confirm_kind(said) is not None))


def recording_claims(pairs, lock):
    """A hook that replaces `ops_turn.code_claims` by a function that answers what it answers and records, beside it, what the frozen expression says for the same arguments. The function it
    wraps is the one in force when the hook runs (so a hook installed before it, in the test that plants a defect, is what it observes)."""
    def hook(mp):
        real = ops_turn.code_claims

        def claims(ctx, said, channel, sender, plan_before):
            old = bool(old_handled(ctx, said, channel, sender, plan_before))
            new = real(ctx, said, channel, sender, plan_before)
            with lock:
                pairs.append((said, channel, plan_before, old, new))
            return new
        mp.setattr(ops_turn, "code_claims", claims)
    return hook


def claims_problems(results) -> list:
    """Item (3), run once per scenario with the other observers by `test_entry_observed.py`: `results` is `[(scenario id, [(said, channel, plan_before, old, new), ...])]`, what `recording_claims` saw;
    it returns one text for each problem.
    On every scenario of the entry corpus (every pre-state, composite ones included, page and terminal lines too) `code_claims` and the frozen expression give the same boolean for each call `say`
    makes; and the rows seen hold both answers and more than one shell (so the check is not vacuous)."""
    rows = [row for _, pairs in results for row in pairs]
    found = [f"{sid}: the frozen expression says {row[3]}, `code_claims` says {row[4]}: {row}" for sid, pairs in results for row in pairs if row[3] != row[4]]
    if not rows:
        found.append("the corpus makes `say` ask the queue decision")
    elif not (any(row[3] for row in rows) and any(not row[3] for row in rows) and {row[1] for row in rows} >= {"messaging", "page"}):
        found.append("both answers, and more than one shell, were seen")
    return found


def test_a_claim_goes_with_its_rows(monkeypatch):
    """Every claim is asked, in the old order, while its rows are in the table; the claim of a row that has left is not asked."""
    asked = []
    claims = tuple((rows, lambda *a, rows=rows: asked.append(rows) or False) for rows, _ in ops_turn.CLAIMS)
    monkeypatch.setattr(ops_turn, "CLAIMS", claims)
    assert ops_turn.code_claims({}, "x", "page", None, False) is False and asked == [rows for rows, _ in claims]
    asked.clear()
    monkeypatch.setattr(turn_order, "names", lambda stage: tuple(n for n in OPS if n != "greeting"))
    ops_turn.code_claims({}, "x", "page", None, False)
    assert ("greeting",) not in asked and len(asked) == len(claims) - 1, "the claim of a retired row is not asked"
    assert [rows[0] for rows, _ in ops_turn.CLAIMS] == ["draft-answer", "greeting", "delete-file", "plan-bare-word"]


# --- L63(3) is the table -----------------------------------------------------------------------------------------------------------------------------

MARKER = "the claimers come first in the order of `runtime/turn_order.py` `ORDER`"
REPLACED = "Replaced so far:"


def l63_row(path: Path) -> str:
    """The line of L63: a table row in the generated mirror, `**L63.** <limit>` in the contract (an entry of "The limits": a paragraph each)."""
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith(("| L63 |", "**L63.** "))]
    assert len(rows) == 1, f"{path.name} holds one L63 row"
    return rows[0]


def listed_names(row: str) -> list:
    """The names the row lists after the marker sentence, in order: `a`, `b`, ..., up to the end of the list."""
    assert row.count(MARKER) == 1, "the row holds the marker sentence once"
    found = re.search(re.escape(MARKER) + r"[^:]*:\s*((?:`[a-z0-9-]+`(?:,\s*)?)+)", row)
    assert found, "the marker sentence is followed by the names, each in backticks"
    return re.findall(r"`([a-z0-9-]+)`", found.group(1))


def replaced_sentence(row: str) -> str:
    """The sentence that starts at "Replaced so far:", up to the first full stop followed by a space."""
    assert row.count(REPLACED) == 1, "the row holds the sentence \"Replaced so far:\" once"
    tail = row.split(REPLACED, 1)[1]
    return tail.split(". ", 1)[0]


def order_names(order=None) -> list:
    return [row["name"] for row in (turn_order.ORDER if order is None else order)]


def missing_retired(row: str, retired) -> list:
    """The retired entries whose name or whose replacement is not in the sentence."""
    sentence = replaced_sentence(row)
    return [entry["name"] for entry in retired if entry["name"] not in sentence or entry["replaced_by"] not in sentence]


@pytest.mark.parametrize("path", [CONTRACT, MIRROR], ids=["contract", "mirror"])
def test_l63_lists_the_order_of_the_table(path):
    """L63(3) says the order of the claimers; this is the test that reads it against the table. Every stage, in the order of `ORDER`."""
    assert listed_names(l63_row(path)) == order_names()
    assert len(order_names()) == 25 + 3 + 15, "S41-8: the stage `bridge` is 25 rows, the seven claimers of the frame being the one row `frame`"


@pytest.mark.parametrize("path", [CONTRACT, MIRROR], ids=["contract", "mirror"])
def test_l63_names_every_retired_claimer(path):
    row = l63_row(path)
    assert turn_order.RETIRED and missing_retired(row, turn_order.RETIRED) == []
    for entry in turn_order.RETIRED:
        assert entry["name"] and entry["replaced_by"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"])


def test_the_l63_checks_fail_when_the_table_or_the_text_changes():
    """Vacuity. A name left out of the table, two swapped, one added, and the same edits made to the contract's row, all fail the first check; a retired entry the text does not hold fails the second;
    a row without the marker sentence fails at once."""
    row = l63_row(CONTRACT)
    full = list(turn_order.ORDER)
    assert listed_names(row) == order_names(full)
    for index in (0, len(full) // 2, len(full) - 1):
        assert listed_names(row) != order_names(full[:index] + full[index + 1:]), f"the first check sees `{full[index]['name']}` left out of the table"
    swapped_order = list(full)
    swapped_order[3], swapped_order[40] = swapped_order[40], swapped_order[3]
    assert listed_names(row) != order_names(swapped_order), "and two rows that changed places"
    assert listed_names(row) != order_names(full + [{"name": "a-new-claimer"}]), "and a row added"
    for name in ("tier-1-form", "interpreter", "frame"):
        edited = row.replace(f"`{name}`, ", "", 1)
        assert edited != row and listed_names(edited) != order_names(), f"the text with `{name}` left out"
    edited = row.replace("`project-switch`, `help-in-words`", "`help-in-words`, `project-switch`")
    assert edited != row and listed_names(edited) != order_names(), "the text with two names swapped"
    assert missing_retired(row, turn_order.RETIRED + ({"name": "x-unnamed", "replaced_by": "nothing", "date": "2026-10-26"},)) == ["x-unnamed"]
    assert missing_retired(row.replace("by the plan-confirm OK of L65", "by something else"), turn_order.RETIRED) == [turn_order.RETIRED[0]["name"]], "the replacement is part of what is read"
    with pytest.raises(AssertionError):
        listed_names(row.replace(MARKER, "the claimers come first in some order"))
    with pytest.raises(AssertionError):
        replaced_sentence(row.replace(REPLACED, "Gone so far:"))


def test_the_l63_row_keeps_the_sentences_the_spec_keeps():
    row = l63_row(CONTRACT)
    assert "A claimer is removed only in a change that names, in this row, what replaces it; it is never dropped silently" in row
    assert "router's open question bound to the sender is not decided by a list but by the interpreter, with a typed frame item (S4)" in row
    assert "the lists of code come first in this order" not in row, "the prose list of 2026-10-24 is replaced by the table's"


# --- every row is load-bearing, and the order matters --------------------------------------------------------------------------------------------------


def disabling(name):
    def hook(mp):
        mp.setitem(ops_turn.ROWS, name, lambda *a, **k: None)
    return hook


def lines_of(name, limit=60) -> list:
    return rp.scenarios_of(name, limit)


@pytest.mark.parametrize("name", [n for n in OPS if n != FINAL])
def test_every_row_is_load_bearing_disabling_it_changes_a_scenario(name, tmp_path):
    scenarios = lines_of(name)
    assert scenarios, f"the corpus holds lines the row {name} takes (a corpus gap otherwise: add scenarios to entry_corpus_build.py, record on the unchanged base with the supervisor's agreement)"
    assert bridge_side.changed(disabling(name), scenarios, tmp_path), f"no scenario of the corpus needs the row {name}"


def test_the_last_row_of_the_stage_always_takes_the_line(monkeypatch):
    monkeypatch.setattr(ops_say, "_say_route", lambda *a, **k: ("routed", 1, None, True, None))
    state = ops_turn.State("p", {"cfg": {}}, "x", "page", 1, None, {})
    assert ops_turn.ROWS[FINAL]("p", {"cfg": {}}, "x", "page", None, {}, state) == ("routed", 1, None, True, None, None)


def swapped(first, second):
    def hook(mp):
        order = list(OPS)
        a, b = order.index(first), order.index(second)
        order[a], order[b] = order[b], order[a]
        mp.setattr(turn_order, "names", lambda stage, order=tuple(order), real=turn_order.names: order if stage == "ops" else real(stage))
    return hook


SWAPS = [("draft-answer", "tier-1-form"), ("router-question", "state-question"), ("tier-1-form", "interpreter"), ("talk-refusal", "interpreter")]


@pytest.mark.parametrize("first, second", SWAPS)
def test_the_order_matters_two_rows_that_swap_change_a_scenario(first, second, tmp_path):
    """L63(3): a reminder question or a write question is answered, or dropped, before a form is read; the router's question is bound before the state question is looked at; the forms of code come
    before the interpreter; the refusal of a sender who may not talk comes before the interpreter (the scenarios of `reader_interpret`: `interpret` and a read group, no `talk`). Swapped, a line the golden
    has taken by one of the two is taken by the other, and the outcome differs from the golden's."""
    _, recorded = rp.golden()
    scenarios = [s for s in rp.corpus() if {first, second} & set(recorded[s["id"]]["trace"])]
    assert scenarios, "the corpus holds lines that one of the two takes"
    assert bridge_side.changed(swapped(first, second), scenarios, tmp_path), f"swapping {first} and {second} changes no scenario: the corpus does not see this order"


def test_the_corpus_holds_a_sender_with_interpret_and_no_talk():
    assert [s["id"] for s in rp.corpus() if s["sender"] == "reader_interpret"], "the scenarios the swap of `talk-refusal` and `interpreter` is seen on"


def test_the_order_matters_the_talk_refusal_comes_before_the_interpreter_for_a_sender_who_holds_interpret_and_may_not_talk(monkeypatch):
    """Lines of our own (no sender of the entry kit holds `interpret` and a read group without `talk`): in the table's order the refusal answers and no model reads the line; with the two rows
    swapped the interpreter, a daily-route call, reads the line of a sender who may not talk. (OPEN-41-15, decided: S41-11 moves the refusal after the interpreter, for such a sender only.)"""
    reached = []
    line = "quais os meus eventos amanha, por favor"
    monkeypatch.setattr(ops_interpret, "turn", lambda project, ctx, said, sender, extras: reached.append(said) or None)
    monkeypatch.setattr(ops_say, "may_talk", lambda *a, **k: False)
    monkeypatch.setattr(ops_turn.phone_refusal, "said", lambda *a, **k: "refused")
    monkeypatch.setattr(ops_turn.operations, "refusal", lambda *a, **k: "refused")
    stub_rows(monkeypatch, {FINAL: ("planner", None, None, False, None, None)})
    monkeypatch.setitem(ops_turn.ROWS, "talk-refusal", real_talk_refusal)
    monkeypatch.setitem(ops_turn.ROWS, "interpreter", real_interpreter)
    out = ops_turn.dispatch("p", {"cfg": {"channels": {}}}, line, "messaging", 1, "telegram:1", {"deferred": True})
    assert out[0] == "refused" and reached == [], "the table's order: refused, and no model reads the line"
    monkeypatch.setattr(turn_order, "names", lambda stage, real=turn_order.names: tuple("interpreter" if n == "talk-refusal" else "talk-refusal" if n == "interpreter" else n for n in OPS) if stage == "ops" else real(stage))
    ops_turn.dispatch("p", {"cfg": {"channels": {}}}, line, "messaging", 1, "telegram:1", {"deferred": True})
    assert reached == [line], "swapped, the interpreter reads the line of a sender who may not talk"


# --- page and terminal -------------------------------------------------------------------------------------------------------------------------------


SHELLS = ("page", "terminal", "chat", "mcp")      # the shells that are not the messaging bridge (the drain acts as the page: its lines are page scenarios with the router busy)


def shell_scenarios() -> list:
    return [s for s in rp.corpus() if s["channel"] in SHELLS]


def test_the_corpus_holds_page_and_terminal_lines():
    counts = {shell: len([s for s in shell_scenarios() if s["channel"] == shell]) for shell in SHELLS}
    assert all(counts.values()) and sum(counts.values()) >= 166, counts      # 99 page, 51 terminal, 9 chat and 7 mcp scenarios when S41-3 was merged with S41-1c


@pytest.mark.parametrize("shard", range(SHARDS))
def test_a_page_or_terminal_line_passes_the_order_and_never_reaches_the_interpreter(shard, tmp_path):
    """Every page, terminal, chat and mcp scenario of the corpus (the queue's drain included: its lines are page scenarios with the router busy), with `ops_interpret.enabled` left as it is: the trace never holds
    `interpreter`, the stand-in model is never asked and no provider process starts."""
    _, recorded = rp.golden()
    scenarios = rp.shard_of(shell_scenarios(), shard)
    assert scenarios
    for scenario in scenarios:
        found = rp.replay(scenario, tmp_path)
        assert "interpreter" not in found["trace"] and found["model_calls"] == 0 and found["provider_calls"] == 0, scenario["id"]
        assert not rp.differences(recorded[scenario["id"]], found), scenario["id"]
        assert all(name in OPS for name in found["trace"]), f"{scenario['id']} was taken by a row of the stage ops"
        assert found["trace"] or scenario["prestate"].startswith("route_busy"), f"{scenario['id']}: a line no row took is a page line queued while the router is busy"


def test_the_interpreter_row_stays_out_of_reach_of_a_page_line_even_when_enabled_is_wrongly_true(tmp_path):
    """The two layers of L63(1): `ops_interpret.enabled` says messaging only, and the table does too. With `enabled` patched to say yes for the page, a page line still never calls the interpreter."""
    reached = []

    def hook(mp):
        mp.setattr(ops_interpret, "enabled", lambda ctx, channel, sender: True)
        mp.setattr(ops_interpret, "turn", lambda *a, **k: reached.append(a[2]) or None)
    plain = [s for s in shell_scenarios() if s["prestate"] == "none" and s["kind"] == "text" and not s["text"].startswith("/")][:12]
    assert len(plain) >= 6
    for scenario in plain:
        rp.replay(scenario, tmp_path, hook)
    assert reached == [], "the row `interpreter` is a row of the messaging shell only"


# --- the table's trace is the kit's trace --------------------------------------------------------------------------------------------------------------


# The two rows that the bridge's own rows reach without a dispatch of the turn: the kind `write-draft` of the row `frame` and the row `write-form` call `ops.natural_write`, whose family functions `ops_natural_writes.answer` and
# `open_line` are what the kit's wrappers name `draft-answer` and `write-form-ops`. The table's trace is empty for those lines (no turn was dispatched) and the kit's names one of the two.
FAMILY_CALLS = {"draft-answer", "write-form-ops"}


def ops_trace_hook(got, lock):
    """A hook that records, in `got`, the names of the rows of the stage `ops` that took the line, through `ops_turn.TRACE`: the dispatch of a bridge line runs on the bridge's job thread, and only
    counts when it began while the line was being delivered (a job the pre-state started may still be running when the line comes: the kit's `live` rule)."""
    def hook(mp):
        real_walk = ops_turn._walk

        def walk(order, state):
            state.live_at_entry = ek.rec().live      # a job the pre-state started may still be running when the line comes, and end after: the kit records at entry too
            return real_walk(order, state)

        def trace(name, state):
            if getattr(state, "live_at_entry", False):
                with lock:
                    got.append(name)
        mp.setattr(ops_turn, "_walk", walk)
        mp.setattr(ops_turn, "TRACE", trace)
    return hook


def ops_trace_problems(results, recorded) -> list:
    """Item (7), run once per scenario with the other observers by `test_entry_observed.py`: `results` is `[(scenario, the rows of the stage ops that took the line, in time)]`; `recorded` is the golden.
    On every scenario of the corpus, page and terminal lines included, the row that took the line is the claimer the kit's wrappers recorded in the golden for the operations layer. The first row that
    took a line, in time, is the one compared (the kit's first-event rule). A line the bridge's own write rows took has no dispatch of the turn: the kit names the family function they called."""
    names = set(OPS)
    wrong, count, direct, dispatched = [], 0, 0, 0
    for scenario, got in results:
        count += 1
        kit = [n for n in recorded[scenario["id"]]["trace"] if n in names]
        if not got and kit and set(kit) <= FAMILY_CALLS and scenario["channel"] == "messaging":
            direct += 1
            continue
        dispatched += bool(got)
        if got[:1] != kit:
            wrong.append(f"{scenario['id']}: table {got[:1]}, wrapped {kit}")
    found = list(wrong)
    if not (count and dispatched > direct):
        found.append(f"{dispatched} of {count} scenarios were dispatched by the table, {direct} went straight to a family function: the dispatch is not seen")
    return found
