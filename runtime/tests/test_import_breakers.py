"""A ratchet on the lazy imports of the runtime (PLAN-BRAIN section 4.4, package 44-A). Offline: the sources are read, nothing is run.

The runtime holds no import cycle among its top-level imports, but it holds many imports inside functions, and with them the operations
layer, the interpreter and the mail and calendar modules are one strongly connected component. This file does not remove them: it fixes
their number, names every one with its reason, and fails when a package adds one without writing why beside the number.

A lazy edge is `(module, target)`: a function (or method, or lambda) of `module` calls `importlib.import_module("<target>")` with a
constant name, or holds an `import <target>` or `from <target> import ...` statement, where `<target>` is a module of runtime/ or of
runtime/handlers/. Not counted: a top-level import, in a `try`, an `if` or a class body included; a call whose name is a variable
(`effects.py`, `natural_writes.py`: the registries); a script loaded by path.

An edge is *forced by a cycle* when its target already reaches its module through top-level imports: a top-level import there would close
a cycle. The test is made on each edge on its own, so it does not depend on the order of the files. Rules, each a test below:
  1. the lazy calls and the distinct lazy edges are at most LAZY_CALLS_BUDGET and LAZY_EDGES_BUDGET (only ever lowered);
  2. the edges are exactly the keys of ALLOWED_LAZY: an edge that is not listed fails ("make it a top-level import, or list it with its
     reason"), and a listed edge that is gone fails ("remove it, and lower the budgets");
  3. a reason starts with its kind: `cycle:` (a cycle forces the edge: the tag is checked against the graph, so a `cycle:` on an edge that
     closes none fails, "make it a top-level import"), `debt:` (closes no cycle today; package 44-B converts it or writes the reason it
     stays lazy) or `light-start:` (closes no cycle, but a top-level import would slow a start that must stay light; the reason says which);
     the edges tagged `debt:` are at most PLAIN_DEBT_BUDGET, and a forced edge tagged `debt:` fails.
Package 44-B lowers the numbers as it converts a cluster; 44-C does the same for the edges to `ops`. Nothing raises a number without a
reason written beside it.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_import_breakers.py
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"

# The ratchet, on the tip after S41-11 PR 2b (34102d10): 236 lazy calls, 172 distinct edges, of which 35 are forced by a cycle (12 of
# them point at `ops`) and 137 close no cycle on their own (2 of them point at `ops`). The plan's figures at 3afee52b were 160 + 32 calls,
# 140 edges, about 97 convertible and 43 not, 12 to `ops`; the code has grown since and the spec's greedy count is order-dependent, so
# the numbers here are the real ones on this tip and use the independent test above.
# 44-B cluster 1 (mail and calendar modules): 20 debt edges became top-level imports (mail_compose, mail_refresh, mail_revise, event_created,
# event_series, event_lookup, messaging_cards) and 6 more edges, whose target now reaches the importer through them, are cycle edges (event_lookup ->
# event_series, ops_items -> event_lookup, ops_natural -> event_lookup, ops_natural_writes -> event_lookup and -> ops_interpret, policy_widening ->
# interpreter_enable): 207 lazy calls, 152 edges, 111 debt. event_series -> event_lookup is the direction converted (event_series reads event_lookup
# 3 times, event_lookup reads event_series once); a mutual pair can only have one direction at the top.
# 44-B cluster 2 (the ops_* siblings, but not ops_natural.py, ops_natural_writes.py, natural.py and turn_gate.py as importers, and not the edges to `ops`):
# 70 debt edges became top-level imports and 9 more became cycle edges, whose target now reaches the importer through them (ops_interpret -> ops_card_revise,
# ops_natural -> ops_file_read, ops_mail_read, ops_research and ops_todo, ops_natural_writes -> ops, ops_say -> ops_turn, ops_step_seams -> ops_file_read,
# source_names -> ops_natural_calendar): 101 lazy calls, 82 edges, 32 debt. What is left as debt is cluster 3 (the rest), the edges of ops_natural and
# ops_natural_writes, the edges of turn_gate, and the one edge to `ops` that 44-C moves.
# 44-B cluster 3a (the rest, but not the importers of the natural layer: natural, ops_natural, ops_natural_writes, turn_gate): 17 debt edges became top-level
# imports (board, changeset, deps, effect_files, endings, interpreter, plan_confirm, run_stop, source_names, upkeep) and 3 stay lazy as `light-start:`
# (dispatcher -> lab, interpreter_route -> lab, registry -> turn_gate; the reasons are LIGHT_ENTRY, LIGHT_LAB and LIGHT_REGISTRY): 81 lazy calls, 65 edges, 12 debt. What is left as debt is cluster 3b
# (the 11 edges of natural, ops_natural, ops_natural_writes and turn_gate) and the one edge to `ops` that 44-C moves.
# CANDIDATE-OUT 2: the repeat scope (`repeat_goes_on` and its four openers) is deleted, and with it two lazy edges: natural -> recurrence (debt) and ops_natural_writes -> ops_interpret
# (a cycle edge), one call each; the numbers are the file's own AST count on the head rebased onto 44-B 3a: 79 lazy calls, 63 edges, 11 debt (81, 65 and 12 minus the two edges).
# Nothing raises a number without a reason written beside it; 44-B and 44-C lower them.
LAZY_CALLS_BUDGET = 79
LAZY_EDGES_BUDGET = 63
PLAIN_DEBT_BUDGET = 11

CYCLE = ("cycle: the target reaches this module through top-level imports, so a top-level import here would close an import cycle")
CYCLE_OPS = ("cycle: ops imports its siblings at module level, so a sibling reaches an operation of ops at call time "
             "(test_runtime_rules); package 44-C moves the functions the siblings need")
DEBT = ("debt: closes no cycle on its own today; package 44-B makes it a top-level import, or writes here the reason it stays lazy "
        "(`light-start:`)")
LIGHT_ENTRY = ("light-start: the dispatcher is the entry the scheduler starts with the system interpreter; it imports no sibling, checks the project's configuration "
               "against the pin, and only then puts the checkout's runtime/ first on sys.path (bootstrap), so the `check` verb loads the lab from the checkout the "
               "project names and reports a lab that cannot load; a top-level `import lab` would load the lab of the dispatcher's own folder before the pin check")
LIGHT_LAB = ("light-start: an http call, a replay and a status of the interpreter's route never load the lab (its module text; "
             "test_interpreter_account_route.py pins it): only an account route reaches the lab facade, when it first needs it")
LIGHT_REGISTRY = ("light-start: the registry is pure and loads before the gate; `origins` reads the gate's ALLOWED table when it is first asked, and "
                  "test_registry_rows.py pins that importing the registry never loads turn_gate")
DEBT_OPS = ("debt: points at ops and no top-level path from ops leads back today, but the sibling calls an operation of the facade at call time; "
            "package 44-C moves the function the sibling needs")

# (module, reason, targets): one row per module and kind of reason, the targets in one string.
ROWS = (
    ("dispatcher", CYCLE_OPS, "ops"),
    ("dispatcher", LIGHT_ENTRY, "lab"),
    ("event_lookup", CYCLE, "event_series"),
    ("interpreter_route", LIGHT_LAB, "lab"),
    ("mail_compose", CYCLE, "interpreter_enable ops_interpret"),
    ("natural_writes", CYCLE, "turn_gate"),
    ("ops_ask", CYCLE_OPS, "ops"),
    ("ops_cancel", CYCLE, "board"),
    ("ops_cancel", CYCLE_OPS, "ops"),
    ("ops_card_revise", CYCLE, "ops_event_revise"),
    ("ops_card_revise", CYCLE_OPS, "ops"),
    ("ops_contained", CYCLE_OPS, "ops"),
    ("ops_event_revise", DEBT_OPS, "ops"),
    ("ops_file_ask", CYCLE_OPS, "ops"),
    ("ops_file_read", CYCLE, "ops_file_ask ops_file_trash"),
    ("ops_instructions", CYCLE, "ops_routines"),
    ("ops_instructions", CYCLE_OPS, "ops"),
    ("ops_interpret", CYCLE, "ops_card_revise"),
    ("ops_items", CYCLE, "event_lookup"),
    ("ops_models", CYCLE, "ops_routines"),
    ("ops_natural", CYCLE, "event_lookup ops_file_ask ops_file_read ops_mail_read ops_natural_writes ops_research ops_say ops_todo"),
    ("ops_natural", CYCLE_OPS, "ops"),
    ("ops_natural", DEBT, "item_refs natural_writes ops_items ops_reminders reminders"),
    ("ops_natural_writes", CYCLE, "event_lookup"),
    ("ops_natural_writes", CYCLE_OPS, "ops"),
    ("ops_natural_writes", DEBT, "account_start natural_writes_calendar"),
    ("ops_reads", CYCLE_OPS, "ops"),
    ("ops_research", CYCLE_OPS, "ops"),
    ("ops_runs", CYCLE, "ops_file_ask ops_routines ops_steps"),
    ("ops_runs", CYCLE_OPS, "ops"),
    ("ops_say", CYCLE, "ops_ask ops_turn"),
    ("ops_say", CYCLE_OPS, "ops"),
    ("ops_step_seams", CYCLE, "ops_file_read"),
    ("phrases", CYCLE, "phone_questions"),
    ("plan_confirm", CYCLE, "ops_natural"),
    ("policy_widening", CYCLE, "interpreter_enable"),
    ("registry", LIGHT_REGISTRY, "turn_gate"),
    ("source_names", CYCLE, "ops_natural_calendar"),
    ("sources", CYCLE, "sources_mail sources_onedrive workcopy"),
    ("turn_gate", CYCLE, "ops_natural"),
    ("turn_gate", DEBT, "interpreter_route operations policy_widening"),
    ("workcopy", CYCLE, "drop"),
)
ALLOWED_LAZY = {(source, target): reason for source, reason, targets in ROWS for target in targets.split()}


# --- the measurement -------------------------------------------------------------------------------------------------------------------

def module_names(runtime: Path) -> list:
    """The modules the edges are drawn between: runtime/*.py by stem, runtime/handlers/*.py as `handlers.<stem>`."""
    return sorted(p.stem for p in runtime.glob("*.py")) + sorted("handlers." + p.stem for p in (runtime / "handlers").glob("*.py"))


def read_sources(runtime: Path) -> dict:
    sources = {p.stem: p.read_text(encoding="utf-8") for p in runtime.glob("*.py")}
    sources.update({"handlers." + p.stem: p.read_text(encoding="utf-8") for p in (runtime / "handlers").glob("*.py")})
    return sources


class _Edges(ast.NodeVisitor):
    def __init__(self, module: str, names: set):
        self.module, self.names, self.depth = module, names, 0
        self.top, self.lazy = set(), []

    def _function(self, node):
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_FunctionDef = visit_AsyncFunctionDef = visit_Lambda = _function

    def _add(self, target, line):
        if target in self.names and target != self.module:
            if self.depth:
                self.lazy.append((target, line))
            else:
                self.top.add(target)

    def visit_Import(self, node):
        for alias in node.names:
            self._add(alias.name, node.lineno)

    def visit_ImportFrom(self, node):
        if node.level == 0 and node.module:
            self._add(node.module, node.lineno)
            for alias in node.names:  # `from handlers import social`
                self._add(node.module + "." + alias.name, node.lineno)

    def visit_Call(self, node):
        if ast.unparse(node.func).endswith("import_module") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self._add(first.value, node.lineno)
        self.generic_visit(node)


def import_edges(sources: dict) -> tuple:
    """(top, lazy): top maps a module to the set of modules it imports at the top; lazy maps (module, target) to the lines of its lazy calls."""
    names = set(sources)
    top, lazy = {name: set() for name in names}, {}
    for name, source in sources.items():
        visitor = _Edges(name, names)
        visitor.visit(ast.parse(source))
        top[name] = visitor.top
        for target, line in visitor.lazy:
            lazy.setdefault((name, target), []).append(line)
    return top, lazy


def reaches(top: dict, start: str) -> set:
    seen, todo = set(), [start]
    while todo:
        for nxt in top.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def forced_by_cycle(top: dict, lazy: dict) -> set:
    """The lazy edges whose target already reaches the module through top-level imports."""
    return {(a, b) for (a, b) in lazy if a in reaches(top, b)}


def ratchet_problems(top: dict, lazy: dict, allowed: dict, calls_budget: int, edges_budget: int, debt_budget: int) -> dict:
    """The failures of each rule, as a dict of lists (empty lists when the rule holds)."""
    forced = forced_by_cycle(top, lazy)
    found = {"budget": [], "listed": [], "kind": [], "debt": []}
    calls = sum(len(lines) for lines in lazy.values())
    if calls > calls_budget:
        found["budget"].append(f"{calls} lazy calls, the budget is {calls_budget}: write the reason beside the number, or make an import top-level")
    if len(lazy) > edges_budget:
        found["budget"].append(f"{len(lazy)} lazy edges, the budget is {edges_budget}")
    for edge in sorted(set(lazy) - set(allowed)):
        how = "it is forced by a cycle: list it with its reason" if edge in forced else "it closes no cycle: make it a top-level import"
        found["listed"].append(f"{edge[0]} -> {edge[1]} (line {lazy[edge][0]}) is not in ALLOWED_LAZY; {how}")
    for edge in sorted(set(allowed) - set(lazy)):
        found["listed"].append(f"{edge[0]} -> {edge[1]} is in ALLOWED_LAZY and no longer lazy: remove it and lower the budgets")
    debt = 0
    for edge in sorted(set(lazy) & set(allowed)):
        kind = allowed[edge].split(":", 1)[0]
        if kind not in ("cycle", "debt", "light-start"):
            found["kind"].append(f"{edge[0]} -> {edge[1]}: the reason starts with {kind!r}, not cycle, debt or light-start")
        elif kind == "cycle" and edge not in forced:
            found["kind"].append(f"{edge[0]} -> {edge[1]} says a cycle forces it and none does: make it a top-level import")
        elif kind == "debt" and edge in forced:
            found["kind"].append(f"{edge[0]} -> {edge[1]} says it is debt and a cycle forces it: write the cycle reason")
        debt += kind == "debt"
    if debt > debt_budget:
        found["debt"].append(f"{debt} edges tagged debt, the budget is {debt_budget}: an edge that closes no cycle is a top-level import")
    return found


# --- the real tree ---------------------------------------------------------------------------------------------------------------------

def real_edges() -> tuple:
    sources = read_sources(RUNTIME)
    assert len(sources) > 150, "runtime/ was not read"
    return import_edges(sources)


def test_the_lazy_calls_and_edges_are_within_the_budget():
    top, lazy = real_edges()
    assert ratchet_problems(top, lazy, ALLOWED_LAZY, LAZY_CALLS_BUDGET, LAZY_EDGES_BUDGET, PLAIN_DEBT_BUDGET)["budget"] == []
    assert sum(len(lines) for lines in lazy.values()) > 0, "no lazy edge was found: the reader is blind"


def test_every_lazy_edge_is_listed_with_its_reason_and_no_listed_edge_is_gone():
    top, lazy = real_edges()
    assert ratchet_problems(top, lazy, ALLOWED_LAZY, LAZY_CALLS_BUDGET, LAZY_EDGES_BUDGET, PLAIN_DEBT_BUDGET)["listed"] == []
    assert all(reason.strip() for reason in ALLOWED_LAZY.values())


def test_the_kind_of_each_reason_matches_the_graph_and_the_debt_does_not_grow():
    top, lazy = real_edges()
    found = ratchet_problems(top, lazy, ALLOWED_LAZY, LAZY_CALLS_BUDGET, LAZY_EDGES_BUDGET, PLAIN_DEBT_BUDGET)
    assert found["kind"] == []
    assert found["debt"] == []


def test_the_top_level_imports_hold_no_cycle():
    top, _ = real_edges()
    assert [name for name in top if name in reaches(top, name)] == []


# --- vacuity: the same checks on planted trees (the twin of each rule) -----------------------------------------------------------------

LEAF = {"a": "def f():\n    import b\n", "b": ""}                     # a lazy import of a leaf: it closes no cycle
CYCLE_TREE = {"a": "import b\n", "b": "def f():\n    import a\n"}      # b -> a closes the cycle a -> b -> a


def planted(sources: dict, allowed: dict, calls=99, edges=99, debt=99) -> dict:
    top, lazy = import_edges(sources)
    return ratchet_problems(top, lazy, allowed, calls, edges, debt)


def test_the_reader_finds_every_form_of_a_lazy_edge_and_no_other():
    sources = {
        "m1": "import t1\nfrom t2 import x\ntry:\n    import t3\nexcept ImportError:\n    t3 = None\nclass K:\n    import t4\n",
        "m2": ("import importlib\n"
               "def f():\n    importlib.import_module('t1')\n    importlib.import_module(\"t1\")\n    import t2\n"
               "def g(name):\n    importlib.import_module(name)\n    from t3 import y\n    import os\n"
               "class K:\n    def m(self):\n        import t4\n        from t5 import z\n"
               "h = lambda: importlib.import_module('t2')\n"),
        "handlers.t6": "from handlers import t7\ndef f():\n    from handlers import t7\n",
        "m3": "def f():\n    import m3\n    import notamodule\n",
        **{f"t{i}": "" for i in range(1, 6)}, "handlers.t7": "",
    }
    top, lazy = import_edges(sources)
    assert top["m1"] == {"t1", "t2", "t3", "t4"} and top["m2"] == set() and top["handlers.t6"] == {"handlers.t7"}
    assert {k: len(v) for k, v in lazy.items()} == {("m2", "t1"): 2, ("m2", "t2"): 2, ("m2", "t3"): 1, ("m2", "t4"): 1, ("m2", "t5"): 1,
                                                     ("handlers.t6", "handlers.t7"): 1}


def test_a_planted_lazy_import_of_a_leaf_fails_the_rule_that_names_it_a_top_level_import():
    found = planted(LEAF, {})
    assert len(found["listed"]) == 1 and "make it a top-level import" in found["listed"][0]
    # listed under a cycle reason it still fails: no cycle forces it
    found = planted(LEAF, {("a", "b"): "cycle: made up"})
    assert len(found["kind"]) == 1 and "make it a top-level import" in found["kind"][0]
    # listed as debt it passes only while the debt budget has room
    assert planted(LEAF, {("a", "b"): "debt: made up"}, debt=1)["debt"] == []
    assert len(planted(LEAF, {("a", "b"): "debt: made up"}, debt=0)["debt"]) == 1
    # listed with a stated reason to stay lazy it passes
    assert [v for v in planted(LEAF, {("a", "b"): "light-start: made up"}).values() if v] == []


def test_a_planted_edge_that_closes_a_cycle_is_listed_with_a_cycle_reason_and_nothing_else_passes():
    assert planted(CYCLE_TREE, {("b", "a"): "cycle: made up"}) == {"budget": [], "listed": [], "kind": [], "debt": []}
    assert "forced by a cycle" in planted(CYCLE_TREE, {})["listed"][0]
    assert len(planted(CYCLE_TREE, {("b", "a"): "debt: made up"})["kind"]) == 1  # a cycle forces it: the debt tag is wrong
    assert len(planted(CYCLE_TREE, {("b", "a"): "because"})["kind"]) == 1        # no kind at the start of the reason
    assert len(planted(CYCLE_TREE, {("b", "a"): "cycle: made up", ("a", "b"): "cycle: gone"})["listed"]) == 1  # a listed edge that is not lazy


def test_a_planted_extra_call_or_edge_breaks_the_budget_and_a_planted_extra_edge_on_the_real_tree_fails_the_listing():
    assert len(planted(CYCLE_TREE, {("b", "a"): "cycle: made up"}, calls=0)["budget"]) == 1
    assert len(planted(CYCLE_TREE, {("b", "a"): "cycle: made up"}, edges=0)["budget"]) == 1
    top, lazy = real_edges()
    names = sorted(top)
    extra = next((a, b) for a in names for b in names if a != b and (a, b) not in lazy)
    lazy[extra] = [1]
    found = ratchet_problems(top, lazy, ALLOWED_LAZY, LAZY_CALLS_BUDGET, LAZY_EDGES_BUDGET, PLAIN_DEBT_BUDGET)
    assert len(found["listed"]) == 1 and len(found["budget"]) == 2
    del lazy[extra]
    lazy.pop(next(iter(lazy)))  # a listed edge that is no longer lazy
    found = ratchet_problems(top, lazy, ALLOWED_LAZY, LAZY_CALLS_BUDGET, LAZY_EDGES_BUDGET, PLAIN_DEBT_BUDGET)
    assert len(found["listed"]) == 1 and "no longer lazy" in found["listed"][0]
