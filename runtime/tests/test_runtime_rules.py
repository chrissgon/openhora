"""Tests of the rules the task runtime keeps outside the validator's core: no module of runtime/ or runtime/handlers/
and no flow file names an AI tool or a model id (rule R19 of the platform plan), the terminal shell imports only
the operations layer, every module runs on the system interpreter, and the Python 3.9 job of CI runs the tests of
the runtime and of the store. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_rules.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"

spec = importlib.util.spec_from_file_location("validate_for_runtime_rules", REPO / "scripts" / "validate.py")
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)


def runtime_modules() -> list:
    """Every module of runtime/ and of runtime/handlers/ (the handlers the dispatcher ticks)."""
    return sorted(RUNTIME.glob("*.py")) + sorted((RUNTIME / "handlers").glob("*.py"))


def scanned_files() -> list:
    return runtime_modules() + [RUNTIME / "README.md"] + sorted((REPO / "flows").glob("*.json"))


def known_model_ids() -> set:
    """Every model id the gate file names: the grader, the lab models and each id of its `models` table with its
    aliases. The gate file is the one place that names them (rule R19)."""
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    ids = {gate["grader"], *(gate.get("lab_models") or [])}
    for name, entry in (gate.get("models") or {}).items():  # a list of aliases, or an object that holds them (and the model's route)
        ids |= {name, *(entry["aliases"] if isinstance(entry, dict) else entry)}
    return {i for i in ids if i}


def test_no_module_of_the_runtime_and_no_flow_file_names_an_ai_tool():
    assert any(p.parent.name == "handlers" for p in runtime_modules()), "runtime/handlers/ holds no module"
    found = []
    for path in scanned_files():
        match = validate.HARNESS_RE.search(path.read_text(encoding="utf-8"))
        if match:
            found.append(f"{path.relative_to(REPO)}: {match.group(0)!r}")
    assert found == []


def test_no_module_of_the_runtime_and_no_flow_file_names_a_model_id():
    ids = known_model_ids()
    assert len(ids) >= 2, "the gate file names no model"
    found = [f"{path.relative_to(REPO)}: {i!r}" for path in scanned_files() for i in sorted(ids)
             if i in path.read_text(encoding="utf-8")]
    assert found == [], "the model comes from evals/eval-gate.json, never from a literal in the runtime"


# 2026-10-09 (CONS-2a): the social agent's auto reply goes through the operation (execute-under-policy), so the
# exemption is no longer a list of files: it is the functions that confirm an exact content the person approved by its
# hash, checked by code (the inbox reply of social.py, the vote post of social_vote.py and its job). `main` of
# social.py only declares the flag that cmd_approve reads. CONS-2b hands these to the operation too and empties this table.
EXACT_CONTENT_PORTS = {"social.py": ("cmd_approve", "main"), "social_vote.py": ("vote_approve", "_action"),
                       "social_vote_job.py": ("main",)}
EFFECT_WORDS = ("--confirmed", "action-add", "action_add")


def effect_occurrences(path) -> list:
    """(enclosing function or None, word, line) of each place a handler's code names the flag that confirms a provider
    verb or the record of an action: a text in the code and a name, never a docstring; each attributed with ast to the
    function it is inside, the innermost."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                  if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    found = []

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            inside = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            texts = []
            if isinstance(child, ast.Constant) and isinstance(child.value, str) and id(child) not in docstrings:
                texts.append(child.value)
            elif isinstance(child, ast.Name):
                texts.append(child.id)
            elif isinstance(child, ast.Attribute):
                texts.append(child.attr)
            found.extend((function, word, child.lineno) for text in texts for word in EFFECT_WORDS if word in text)
            visit(child, inside)

    visit(tree, None)
    return found


def test_no_handler_executes_an_effect_itself():
    """Limit L15 lives in one operation (ops.execute_under_policy): a handler prepares an effect and hands it over,
    it never confirms a provider verb and never records an action. The one exemption is EXACT_CONTENT_PORTS, by
    function: any other place a handler names the confirming flag or the record of an action fails, in the files
    that were exempt before as in the others."""
    seen = {}
    for handler in sorted((RUNTIME / "handlers").glob("*.py")):
        allowed = EXACT_CONTENT_PORTS.get(handler.name, ())
        for function, word, line in effect_occurrences(handler):
            seen.setdefault(handler.name, set()).add(function)
            assert function in allowed, \
                f"{handler.name}:{line} names {word!r} in {function or 'the module'}: hand the effect to execute-under-policy"
    # a row that names no occurrence is a row to remove: the table only shrinks
    for name, functions in EXACT_CONTENT_PORTS.items():
        assert set(functions) <= seen.get(name, set()), f"{name}: {sorted(set(functions) - seen.get(name, set()))} hold no such name"


def test_the_social_agents_auto_reply_path_names_neither_the_flag_nor_the_record():
    in_reply_path = {f for f, _, _ in effect_occurrences(RUNTIME / "handlers" / "social.py")}
    assert not ({"handle_event", "hand_over", "cmd_replay", "cmd_tick"} & in_reply_path)


def test_main_of_the_social_handler_holds_one_occurrence_and_it_is_the_flag_declaration():
    """`main` is exempt only for the argparse line that declares the flag cmd_approve reads: a second occurrence there
    (a confirmed call, a recorded action) fails."""
    found = [word for function, word, _ in effect_occurrences(RUNTIME / "handlers" / "social.py") if function == "main"]
    assert found == ["--confirmed"]


def test_the_attribution_sees_a_name_inside_a_function_and_leaves_a_docstring_alone(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text('"""Run with --confirmed."""\n\ndef a():\n    """Mentions action-add."""\n    return ["--confirmed"]\n\n'
                      'def b():\n    def inner():\n        return store.action_add\n    return inner\n')
    assert effect_occurrences(sample) == [("a", "--confirmed", 5), ("inner", "action_add", 9)]


def test_the_terminal_shell_imports_only_the_operations_layer():
    source = (RUNTIME / "cli.py").read_text(encoding="utf-8")
    imported = re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][\w.]*)", source, re.M)
    assert [name for name in imported if name not in ("__future__", "argparse", "json", "os", "sys")] == ["ops"]
    for loader in ("importlib", "__import__", "spec_from_file_location"):
        assert loader not in source, f"runtime/cli.py loads a module another way: {loader}"


def test_every_module_of_the_runtime_is_on_the_list_the_python_39_job_checks():
    listed = (REPO / "scripts" / "tests" / "test_runtime_python39.py").read_text(encoding="utf-8")
    missing = [p.relative_to(REPO).as_posix() for p in runtime_modules()
               if f'"{p.relative_to(REPO).as_posix()}"' not in listed]
    assert missing == []


def test_the_python_39_job_runs_the_tests_of_the_runtime_and_of_the_store():
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text(encoding="utf-8")
    rest = text[text.index("\n  python39:") + 1:]
    following = re.search(r"\n  [A-Za-z0-9_-]+:\n", rest)
    job = rest[:following.start()] if following else rest
    assert "runtime/tests" in job
    assert "providers/store/tests" in job


# --- the operations layer is seven files (CONS-1B, ADJ-R1, R4-C3, PAR-4): runtime/ops.py and its siblings ops_say.py, ops_reads.py, ops_waits.py, ops_config.py, ops_runs.py, ops_core.py ----------

SHARED_NAMES = ("ROOT", "context", "_stored", "OpsError", "_try_lock", "_task_lock", "_route_lock", "_claim_lock",
                "_write_lock", "_dispatch_lock", "_lock_owner", "_lock_pgid", "_LAB_GUARD", "_config_lock",
                "_effect_lock", "_effects_running")


def ops_modules() -> list:
    """The files of the operations layer: ops.py and its siblings ops_*.py (not operations.py, the table)."""
    return sorted(RUNTIME.glob("ops.py")) + sorted(RUNTIME.glob("ops_*.py"))


def top_level_names(tree) -> list:
    """(name, node) of each definition and assignment at the top of a module."""
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found.append((node.name, node))
        elif isinstance(node, ast.Assign):
            found += [(t.id, node) for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.append((node.target.id, node))
    return found


def test_no_module_of_the_operations_layer_binds_a_name_of_ops_core_at_import():
    """A from-import of `ROOT` out of ops_core would copy the name when the module loads: a test that patches
    `ops_core.ROOT` would not reach it, and the code would run against the real checkout with nothing failing. Every
    module reads a shared name as an attribute of the module, at call time (`core.ROOT`)."""
    assert ops_modules(), "runtime/ holds no ops.py"
    found = []
    for path in ops_modules():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module == "ops_core":
                found.append(f"{path.name}:{node.lineno}")
    assert found == []


def test_the_shared_names_of_the_operations_layer_have_one_home():
    homes = {name: [] for name in SHARED_NAMES}
    for path in ops_modules():
        for name, node in top_level_names(ast.parse(path.read_text(encoding="utf-8"))):
            if name not in SHARED_NAMES:
                continue
            # the one re-export: the shells catch `ops.OpsError`, and the class is never patched
            if name == "OpsError" and isinstance(node, ast.Assign) and ast.unparse(node.value) == "core.OpsError":
                continue
            homes[name].append(path.name)
    assert homes == {name: ["ops_core.py"] for name in SHARED_NAMES}


def test_ops_core_imports_no_other_file_of_the_operations_layer():
    path = RUNTIME / "ops_core.py"
    assert path.is_file(), "runtime/ops_core.py is gone"
    names = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
        elif isinstance(node, ast.Call) and ast.unparse(node.func).endswith("import_module") and node.args:
            names.append(ast.unparse(node.args[0]).strip("\"'"))
    assert [n for n in names if n == "ops" or n.startswith("ops_")] == []


def test_the_siblings_of_ops_py_do_not_import_ops_py_at_module_level():
    """ops.py imports its siblings; a sibling reaches an operation of ops.py at call time, so that no import cycle
    exists. ops_say.py imports neither sibling above it; ops_reads.py imports ops_say.py (the conversation's name)."""
    # ops_actor is a leaf (operations and ops_core only): it can close no cycle
    allowed = {"ops_say.py": {"ops_core", "ops_actor", "ops_natural"}, "ops_natural.py": {"ops_core", "ops_actor"},
               "ops_natural_writes.py": {"ops_core", "ops_actor", "ops_natural"}, "ops_interpret.py": {"ops_core", "ops_actor", "ops_natural"}, "ops_natural_calendar.py": {"ops_core", "ops_actor"}, "ops_natural_files.py": {"ops_core", "ops_actor"}, "ops_natural_mail.py": {"ops_core"},
               "ops_items.py": {"ops_core", "ops_actor"}, "ops_reads.py": {"ops_core", "ops_say", "ops_models"},
               "ops_config.py": {"ops_core", "ops_models"}, "ops_contained.py": {"ops_core", "ops_instructions"}, "ops_runs.py": {"ops_core", "ops_waits"}, "ops_models.py": {"ops_core"}}
    for name, may in allowed.items():
        tree = ast.parse((RUNTIME / name).read_text(encoding="utf-8"))
        at_top = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                at_top |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                at_top.add(node.module or "")
        assert {n for n in at_top if n == "ops" or n.startswith("ops_")} <= may, name
    assert set(allowed) == {"ops_say.py", "ops_natural.py", "ops_reads.py", "ops_config.py", "ops_contained.py", "ops_runs.py", "ops_models.py", "ops_natural_mail.py", "ops_natural_writes.py",
                            "ops_natural_calendar.py", "ops_natural_files.py", "ops_items.py", "ops_interpret.py"}, "the guard covers each of its files"


# The size budget (CONS-1B). ops.py held 3,514 lines before the move; after it, 2,676. The budget is that count plus
# 100, so that a change that adds an operation does not breach it by a few lines but a block that should live in a
# sibling does. A sibling is capped at 1,200 lines. The next package of the layer (the domain out of ops.py, after the
# launch) lowers OPS_PY_BUDGET as it moves code; nothing raises it without a reason written beside the number.
OPS_PY_BUDGET = 2776
SIBLING_BUDGET = 1200


def test_the_operations_layer_keeps_its_size_budget():
    assert len((RUNTIME / "ops.py").read_text(encoding="utf-8").splitlines()) <= OPS_PY_BUDGET, \
        "runtime/ops.py is over its budget (package CONS-1B): move a block to a sibling of the layer, do not raise the number"
    over = {p.name: n for p in sorted(RUNTIME.glob("ops_*.py"))
            if (n := len(p.read_text(encoding="utf-8").splitlines())) > SIBLING_BUDGET}
    assert over == {}, f"a sibling of ops.py is over {SIBLING_BUDGET} lines (package CONS-1B): split it by job"
