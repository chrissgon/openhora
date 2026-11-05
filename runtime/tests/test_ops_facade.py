"""The seam of the operations layer (package 44-C2, OPEN-C1 answered B; runtime/ops_facade.py): a sibling of runtime/ops.py calls an operation of the facade
through `ops_facade.function(name)`, which reads `ops.<name>` at the moment of the call. Three rules, each pinned here with the test of its own failure:
  (a) a patch on `ops.<name>` is what `function(name)` returns (the seam keeps nothing): that is what lets the golden kit's spies, the sentinel of the L54 walk
      (test_ops_natural.py, `spy_all`) and the sentinels of the effect paths keep reaching what production calls;
  (b) every literal argument of `ops_facade.function(...)` in runtime/ and runtime/handlers/ is a public name of `ops` (no leading `_`, not UPPER_CASE) that holds a
      callable and not a module (`function("ops_runs")` would hand a sibling's module to a caller): a private
      helper or a constant never goes through the seam, it lives in the sibling that owns its job; a call that passes a variable is one of a closed list (the table's
      own `row["call"]`, and the name `ops_event_revise._arguments` returns), and the module is imported as `import ops_facade`, so that no call is missed;
  (c) the modules that reach `ops` at call time are exactly EXPECTED_IMPORTERS (the dispatcher's entry and the seam).
Offline; no model, no network; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_facade.py
"""
from __future__ import annotations

import ast
import types
from pathlib import Path

import standin_tree as st
import test_import_breakers as tib

ops = st.load("ops")
ops_facade = st.load("ops_facade")
operations = st.load("operations")

RUNTIME = Path(__file__).resolve().parents[1]

# (c): the modules whose function bodies load `ops` by name. dispatcher: the entry (CYCLE_ENTRY). ops_facade: the seam. ops_say left the set in 44-C3: `_route_request` lives
# in ops_requests, which `_drain_route` loads by name; ops_runs left it in 44-C4b: the run body is in ops_task_run (44-C4a) and the round in ops_round, loaded by name.
EXPECTED_IMPORTERS = {"dispatcher", "ops_facade"}
MISSING = object()      # what `lookup` returns for a name ops does not have

# (b): a call whose argument is not a literal. (module, the argument's source): the three dispatches of a row of the table, and the operation `ops_event_revise` opens.
DYNAMIC_ARGUMENTS = {("ops_natural", "row['call']"), ("ops_natural_writes", "row['call']"), ("ops_say", "row['call']"), ("ops_event_revise", "name")}


def public(name: str) -> bool:
    return not name.startswith("_") and not name.isupper()


# --- (a) the seam keeps nothing ----------------------------------------------------------------------------------------------------------------------

def follows_a_patch(function, module) -> bool:
    """Whether `function(name)` returns what `module.<name>` holds NOW: the patched function, and the real one again once the patch is undone."""
    real = module.pending
    patched = lambda *a, **k: "patched"      # noqa: E731
    module.pending = patched
    try:
        followed = function("pending") is patched
    finally:
        module.pending = real
    return followed and function("pending") is real


def test_function_returns_what_ops_holds_at_the_call_and_follows_a_patch(monkeypatch):
    assert ops_facade.function("pending") is ops.pending
    assert ops_facade.function("reject") is ops.reject
    marker = lambda *a, **k: "patched"      # noqa: E731
    monkeypatch.setattr(ops, "pending", marker)
    assert ops_facade.function("pending") is ops.pending      # whatever the patch is, the seam returns what ops holds now
    assert ops_facade.function("pending")("project") == "patched"      # and it is the patched one: the call reaches the marker
    assert follows_a_patch(ops_facade.function, ops)


def test_function_raises_for_a_name_ops_does_not_have():
    try:
        ops_facade.function("no_such_operation_here")
    except AttributeError:
        return
    raise AssertionError("function returned something for a name ops does not have")


def test_vacuity_a_seam_that_keeps_the_function_it_first_found_is_caught_by_the_oracle():
    fake = types.SimpleNamespace(pending=lambda *a, **k: "real")
    reading = lambda name: getattr(fake, name)      # noqa: E731
    assert follows_a_patch(reading, fake)
    first = {}
    keeping = lambda name: first.setdefault(name, getattr(fake, name))      # noqa: E731
    assert not follows_a_patch(keeping, fake)


# --- (b) what goes through the seam --------------------------------------------------------------------------------------------------------------------

def calls_of_the_seam(source: str) -> tuple:
    """(calls, problems) of one source: calls = [(line, source of the argument, the literal or None)] for every `ops_facade.function(...)`; problems = a form that the
    reader would miss (`from ops_facade import ...`, `import ops_facade as x`) or a call that does not pass exactly one positional argument."""
    calls, problems = [], []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == "ops_facade":
            problems.append(f"line {node.lineno}: from ops_facade import: write `import ops_facade` and call ops_facade.function(...)")
        elif isinstance(node, ast.Import) and any(a.name == "ops_facade" and a.asname for a in node.names):
            problems.append(f"line {node.lineno}: import ops_facade as <alias>: the reader finds the calls by the name ops_facade")
        elif isinstance(node, ast.Call) and ast.unparse(node.func) == "ops_facade.function":
            if len(node.args) != 1 or node.keywords:
                problems.append(f"line {node.lineno}: ops_facade.function takes exactly one positional argument")
                continue
            arg = node.args[0]
            calls.append((node.lineno, ast.unparse(arg), arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None))
    return calls, problems


def seam_problems(sources: dict, lookup) -> list:
    """What breaks the rule in `sources` ({module: text}): a literal that is not a public name of ops, a name ops does not have, a name that holds a module or
    something that cannot be called, or a variable argument outside DYNAMIC_ARGUMENTS. `lookup(name)` is what ops holds under the name, or MISSING."""
    found = []
    for module, text in sorted(sources.items()):
        calls, problems = calls_of_the_seam(text)
        found += [f"{module}: {p}" for p in problems]
        for line, argument, literal in calls:
            if literal is None:
                if (module, argument) not in DYNAMIC_ARGUMENTS:
                    found.append(f"{module}:{line}: ops_facade.function({argument}): a variable argument is allowed only where DYNAMIC_ARGUMENTS lists it")
            elif not public(literal):
                found.append(f"{module}:{line}: ops_facade.function({literal!r}) is not a public name of ops: a helper or a constant lives in the sibling that owns its job")
            elif lookup(literal) is MISSING:
                found.append(f"{module}:{line}: ops_facade.function({literal!r}): ops has no such name")
            elif isinstance(lookup(literal), types.ModuleType):
                found.append(f"{module}:{line}: ops_facade.function({literal!r}) is a module of ops, not an operation: a sibling imports a module itself")
            elif not callable(lookup(literal)):
                found.append(f"{module}:{line}: ops_facade.function({literal!r}) holds something that cannot be called")
    return found


def runtime_sources() -> dict:
    sources = {p.stem: p.read_text(encoding="utf-8") for p in RUNTIME.glob("*.py")}
    sources.update({"handlers." + p.stem: p.read_text(encoding="utf-8") for p in (RUNTIME / "handlers").glob("*.py")})
    assert len(sources) > 150, "runtime/ was not read"
    return sources


def test_every_argument_of_the_seam_in_the_runtime_is_a_public_name_of_ops():
    sources = runtime_sources()
    assert seam_problems(sources, lambda name: getattr(ops, name, MISSING)) == []
    # the reader is not blind: the siblings that moved to the seam are found, with their literals and the four variables
    found = {module: calls_of_the_seam(text)[0] for module, text in sources.items() if "ops_facade.function" in text}
    assert {"ops_natural", "ops_natural_writes", "ops_say", "ops_card_revise", "ops_event_revise", "ops_instructions"} <= set(found)
    literals = {c[2] for calls in found.values() for c in calls if c[2] is not None}
    assert {"pending", "answer", "reject", "natural_write", "natural_forget", "status", "progress", "request", "route"} <= literals
    dynamic = {(module, c[1]) for module, calls in found.items() for c in calls if c[2] is None}
    assert dynamic == DYNAMIC_ARGUMENTS


def test_the_variable_calls_name_only_the_calls_of_the_table_and_the_two_operations_of_event_revise():
    calls = [row["call"] for row in operations.OPERATIONS]
    assert calls and all(public(call) and hasattr(ops, call) for call in calls), [call for call in calls if not (public(call) and hasattr(ops, call))]
    event_revise = ast.parse((RUNTIME / "ops_event_revise.py").read_text(encoding="utf-8"))
    arguments = next(node for node in event_revise.body if isinstance(node, ast.FunctionDef) and node.name == "_arguments")
    returned = {r.value.elts[0].value for r in ast.walk(arguments) if isinstance(r, ast.Return) and isinstance(r.value, ast.Tuple)
                and isinstance(r.value.elts[0], ast.Constant)}
    assert returned == {"event_create", "event_change"} and all(public(name) and hasattr(ops, name) for name in returned)


def test_vacuity_a_planted_private_or_constant_name_or_unlisted_variable_or_other_import_form_fails_the_rule():
    held = {"pending": lambda: 1, "answer": lambda: 2, "ops_runs": types.ModuleType("ops_runs"), "version": "1.2", "Klass": type("Klass", (), {})}
    has = lambda name: held.get(name, MISSING)      # noqa: E731
    clean = {"m": "import ops_facade\ndef f():\n    return ops_facade.function('pending')(1) or ops_facade.function(\"answer\")\n"}
    assert seam_problems(clean, has) == []
    private = {"m": "import ops_facade\ndef f():\n    return ops_facade.function('_x')\n"}
    assert len(seam_problems(private, has)) == 1 and "not a public name" in seam_problems(private, has)[0]
    constant = {"m": "import ops_facade\ndef f():\n    return ops_facade.function('PER_RUN_USD')\n"}
    assert len(seam_problems(constant, has)) == 1
    absent = {"m": "import ops_facade\ndef f():\n    return ops_facade.function('nothing_here')\n"}
    assert "no such name" in seam_problems(absent, has)[0]
    module = {"m": "import ops_facade\ndef f():\n    return ops_facade.function('ops_runs')\n"}      # public by name, a module by value: only the lookup tells it apart
    assert public("ops_runs") and len(seam_problems(module, has)) == 1 and "module" in seam_problems(module, has)[0]
    not_callable = {"m": "import ops_facade\ndef f():\n    return ops_facade.function('version')\n"}
    assert len(seam_problems(not_callable, has)) == 1 and "cannot be called" in seam_problems(not_callable, has)[0]
    assert seam_problems({"m": "import ops_facade\ndef f():\n    return ops_facade.function('Klass')\n"}, has) == []      # a class is callable
    variable = {"m": "import ops_facade\ndef f(name):\n    return ops_facade.function(name)\n"}
    assert "variable argument" in seam_problems(variable, has)[0]
    assert seam_problems({"ops_event_revise": "import ops_facade\ndef f(name):\n    return ops_facade.function(name)\n"}, has) == []      # the listed one passes
    for text in ("from ops_facade import function\n", "import ops_facade as facade\n", "import ops_facade\nops_facade.function('pending', 1)\n"):
        assert len(seam_problems({"m": text}, has)) == 1, text


# --- (c) who reaches ops at call time -------------------------------------------------------------------------------------------------------------------

def importers_of_ops(sources: dict) -> set:
    """The modules with a function that loads `ops` by name (the lazy edges to ops of test_import_breakers). The shells (cli, service, mcp, chat, messaging) import it at the top
    on purpose: they are its callers, and a sibling that imports it at the top is test_runtime_rules.py's rule."""
    _top, lazy = tib.import_edges(sources)
    return {module for module, target in lazy if target == "ops"}


def test_the_modules_that_reach_ops_are_the_entry_and_the_seam():
    importers = importers_of_ops(tib.read_sources(RUNTIME))
    assert importers == EXPECTED_IMPORTERS, f"a module that reaches ops: {sorted(importers ^ EXPECTED_IMPORTERS)}; call an operation through ops_facade.function(...), move a helper to its job's sibling"


def test_the_seam_imports_nothing_of_the_runtime_so_that_every_sibling_may_import_it_at_the_top():
    top, lazy = tib.import_edges(tib.read_sources(RUNTIME))
    assert top["ops_facade"] == set() and set(lazy) >= {("ops_facade", "ops")}
    assert [edge for edge in lazy if edge[0] == "ops_facade"] == [("ops_facade", "ops")]


def test_vacuity_a_planted_module_that_loads_ops_by_name_is_found_and_breaks_the_expected_set():
    planted = {"ops": "", "quiet": "import os\n", "loud": "import importlib\ndef f():\n    return importlib.import_module('ops')\n",
               "shell": "import ops\n", "other": "def f():\n    import ops_runs\n", "ops_runs": ""}
    assert importers_of_ops(planted) == {"loud"}      # a top-level `import ops` (a shell) and a lazy import of another module are not call-time reaches of ops
    real = tib.read_sources(RUNTIME)
    assert importers_of_ops({**real, "loud": planted["loud"]}) != EXPECTED_IMPORTERS
    assert importers_of_ops(real) == EXPECTED_IMPORTERS
