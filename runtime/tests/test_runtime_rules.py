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
    """Since HOT-1 the list is derived from the two folders of runtime modules (scripts/tests/test_runtime_python39.py: RUNTIME_FILES, minus EXCLUDED, which names a module with a reason), so a module is
    on it unless it is excluded; the list is read from that file, not copied here."""
    spec = importlib.util.spec_from_file_location("python39_list_under_test", REPO / "scripts" / "tests" / "test_runtime_python39.py")
    listed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(listed)
    missing = [p.relative_to(REPO).as_posix() for p in runtime_modules() if p.relative_to(REPO).as_posix() not in listed.ON_SYSTEM_PYTHON
               and p.relative_to(REPO).as_posix() not in listed.EXCLUDED]
    assert missing == []


def test_the_python_39_job_runs_the_tests_of_the_runtime_and_of_the_store():
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text(encoding="utf-8")
    rest = text[text.index("\n  python39:") + 1:]
    following = re.search(r"\n  [A-Za-z0-9_-]+:\n", rest)
    job = rest[:following.start()] if following else rest
    assert "scripts/python39_tests.txt" in job  # the list is the file's: written once, read by this job and by the nightly's
    listed = [line.strip() for line in (REPO / "scripts" / "python39_tests.txt").read_text(encoding="utf-8").splitlines()
              if line.strip() and not line.startswith("#")]
    assert "runtime/tests" in listed
    assert "providers/store/tests" in listed


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
    exists. A sibling imports other siblings at module level only where no path leads back (runtime/tests/test_import_breakers.py proves that the top-level graph holds no cycle)."""
    # ops_actor is a leaf (operations and ops_core only): it can close no cycle
    allowed = {"ops_say.py": {"ops_core", "ops_actor", "ops_natural", "ops_cancel", "ops_file_read", "ops_interpret", "ops_natural_writes", "ops_todo"}, "ops_natural.py": {"ops_core", "ops_actor", "ops_items", "ops_reminders"}, "ops_turn.py": {"ops_natural", "ops_say", "ops_file_read", "ops_file_trash", "ops_instructions", "ops_interpret"},
               "ops_natural_writes.py": {"ops_core", "ops_actor", "ops_natural"}, "ops_interpret.py": {"ops_core", "ops_actor", "ops_natural", "ops_file_trash", "ops_items", "ops_natural_mail", "ops_natural_writes", "ops_todo"}, "ops_natural_calendar.py": {"ops_core", "ops_actor", "ops_natural_writes"}, "ops_natural_files.py": {"ops_core", "ops_actor", "ops_natural_writes"}, "ops_natural_mail.py": {"ops_core"},
               "ops_items.py": {"ops_core", "ops_actor", "ops_sources"}, "ops_reads.py": {"ops_core", "ops_say", "ops_models", "ops_ask", "ops_natural", "ops_runs"},
               "ops_config.py": {"ops_core", "ops_models", "ops_google_folders", "ops_steps"}, "ops_contained.py": {"ops_core", "ops_instructions"}, "ops_runs.py": {"ops_core", "ops_waits"}, "ops_models.py": {"ops_core"}}
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
                            "ops_natural_calendar.py", "ops_natural_files.py", "ops_items.py", "ops_interpret.py", "ops_turn.py"}, "the guard covers each of its files"


# The size budget (CONS-1B, counting rule of SPEC-HOTSPOTS). ops.py held 3,514 lines before the move; after it, 2,676. The budget keeps
# headroom, so that a change that adds an operation does not breach it by a few lines but a block that should live in a sibling does. A sibling
# is capped at 1,200 lines. The next package of the layer (the domain out of ops.py, after the launch) lowers OPS_PY_BUDGET as it moves code;
# nothing raises it without a reason written beside the number.
# The count is the lines of ops.py OUTSIDE its top-level `import` and `from ... import` statements: most changes to the file were a re-export line,
# and a re-export is not code to move out. The budget is that count on the file as migrated (2,655 lines: the file's 2,744 lines before the move to
# one name per line, less its imports, plus the marker line) plus 32, the headroom the old rule had (2,776 lines for a file of 2,744).
OPS_PY_BUDGET = 2687
SIBLING_BUDGET = 1200
REEXPORT_MARKER = "# --- re-exports added from SPEC-HOTSPOTS on: one block per module, sorted by module name ---"


def import_lines(tree) -> set:
    """The line numbers (1-based) covered by the top-level import statements of a module, a multi-line statement included."""
    covered = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            covered.update(range(node.lineno, node.end_lineno + 1))
    return covered


def code_lines(source: str) -> int:
    """The lines of a module's source that no top-level import statement covers: code, comments and blank lines."""
    return len(source.splitlines()) - len(import_lines(ast.parse(source)))


def reexport_tail_problems(source: str) -> list:
    """What is wrong with the blocks after the marker: anything but an import statement (the `if __name__` guard that ends the file is the one
    exception), a statement that is not `from <module> import (...)` or `import <module>`, a module that is not after the one before it."""
    lines = source.splitlines()
    marks = [n for n, line in enumerate(lines, 1) if line == REEXPORT_MARKER]
    if len(marks) != 1:
        return [f"the marker line must appear once, it appears {len(marks)} times"]
    problems, previous = [], ""
    after = [node for node in ast.parse(source).body if node.lineno > marks[0]]
    for node in after:
        if isinstance(node, ast.If) and node is after[-1] and ast.unparse(node.test) == "__name__ == '__main__'":
            continue
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            problems.append(f"line {node.lineno}: {type(node).__name__} after the marker, only imports belong there")
            continue
        module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
        if module <= previous:
            problems.append(f"line {node.lineno}: {module} is not after {previous} (one block per module, sorted by module name)")
        previous = module
    return problems


def test_the_operations_layer_keeps_its_size_budget():
    source = (RUNTIME / "ops.py").read_text(encoding="utf-8")
    assert code_lines(source) <= OPS_PY_BUDGET, \
        "runtime/ops.py is over its budget (package CONS-1B): move a block to a sibling of the layer, do not raise the number"
    assert OPS_PY_BUDGET - code_lines(source) <= 32, "the headroom is 32 lines (SPEC-HOTSPOTS): lower the budget when code moves out, do not leave room"
    assert reexport_tail_problems(source) == []
    over = {p.name: n for p in sorted(RUNTIME.glob("ops_*.py"))
            if (n := len(p.read_text(encoding="utf-8").splitlines())) > SIBLING_BUDGET}
    assert over == {}, f"a sibling of ops.py is over {SIBLING_BUDGET} lines (package CONS-1B): split it by job"


def test_the_counting_rule_leaves_out_imports_only_and_the_tail_rule_catches_code_and_disorder():
    """Vacuity of the two rules above, on planted sources: each fails on a wrong result."""
    planted = ("import os\nfrom a import (\n    b,\n    c,\n)\nx = 1\n# a comment\n\n" + REEXPORT_MARKER + "\n"
               "from b_mod import d  # noqa\nfrom c_mod import (\n    e,\n)\nif __name__ == \"__main__\":\n    pass\n")
    assert code_lines(planted) == 6, "the assignment, the comment, the blank, the marker and the guard (two lines): the eight lines of imports are out"
    assert reexport_tail_problems(planted) == []
    assert reexport_tail_problems(planted.replace(REEXPORT_MARKER + "\n", "")) != [], "no marker"
    with_def = planted.replace("if __name__", "def helper():\n    return 1\nif __name__")
    assert any("FunctionDef after the marker" in p for p in reexport_tail_problems(with_def))
    unsorted = planted.replace("from b_mod import d  # noqa\n", "from d_mod import d\n")
    assert any("not after" in p for p in reexport_tail_problems(unsorted)), "an unsorted block"
    twice = planted.replace("from b_mod import d  # noqa\n", "from c_mod import d\n")
    assert any("not after" in p for p in reexport_tail_problems(twice)), "one block per module"
    assert code_lines(planted + "y = 2\n") == code_lines(planted) + 1, "a planted line of code counts"


# --- the three lists that were tables are paragraphs (SPEC-HOTSPOTS) -----------------------------------------------------------------------------------
# runtime/README.md "## Modules", contracts/runtime.md "## Pieces" and "## The limits" were tables of one row per entry: the place where most packages edited the
# same few lines, adjacent rows included. An entry is a paragraph of its own (a blank line before and after), so that two packages that add an entry edit
# different places. A module is `` `path`: what it owns `` on one line; a limit is `**L<n>.** <limit>` and, on the next line, `Built by: <cell>. Test: <cell>.`.
MODULE_ENTRY = re.compile(r"`[^`\n]+`(?:, `[^`\n]+`| and `[^`\n]+`)*: ")
LIMIT_START = re.compile(r"\*\*L\d+\.\*\* ")
LIMIT_SECOND = re.compile(r"Built by: .+\. Test: .+\.")
PARAGRAPH_SECTIONS = (("runtime/README.md", "## Modules", MODULE_ENTRY, 1), ("contracts/runtime.md", "## Pieces", MODULE_ENTRY, 1),
                      ("contracts/runtime.md", "## The limits", LIMIT_START, 2))


def section_of(text: str, heading: str) -> list:
    """The lines of a section, from the line after its heading to the line before the next `## ` heading."""
    body = text.split("\n" + heading + "\n", 1)[1].split("\n## ", 1)[0]
    return body.split("\n")


def paragraph_problems(lines: list, start, length: int) -> list:
    """What is wrong with a section's entries: a table row anywhere, an entry (a line that starts like `start`) that is not `length` lines followed by a blank
    line, an entry that does not follow a blank line, or, for two lines, a second line that is not `Built by: ... Test: ....`."""
    problems = [f"a table row: {line[:50]!r}" for line in lines if line.startswith("|")]
    entries = 0
    for n, line in enumerate(lines):
        if not start.match(line):
            continue
        entries += 1
        block = lines[n:n + length]
        after = lines[n + length] if n + length < len(lines) else ""
        if n > 0 and lines[n - 1].strip():
            problems.append(f"entry without a blank line before it: {line[:50]!r}")
        if len(block) < length or any(not part.strip() for part in block) or after.strip():
            problems.append(f"entry that is not {length} line(s) and a blank line: {line[:50]!r}")
        elif length == 2 and not LIMIT_SECOND.fullmatch(block[1]):
            problems.append(f"limit without its `Built by: ... Test: ....` line: {line[:50]!r}")
    if not entries:
        problems.append("no entry")
    return problems


def test_the_modules_the_pieces_and_the_limits_are_one_paragraph_each_and_hold_no_table_row():
    for path, heading, start, length in PARAGRAPH_SECTIONS:
        lines = section_of((REPO / path).read_text(encoding="utf-8"), heading)
        assert paragraph_problems(lines, start, length) == [], (path, heading)
        assert sum(1 for line in lines if start.match(line)) >= (60 if length == 2 else 100), (path, heading, "the entries are all there")


def test_the_paragraph_rule_catches_a_table_row_a_missing_blank_line_and_a_half_entry():
    """Vacuity of the rule above, on planted sections: each wrong shape is named, and the right one passes."""
    good = ["", "`a.py`: one.", "", "`b.py`: two.", "", "Prose after the entries."]
    assert paragraph_problems(good, MODULE_ENTRY, 1) == []
    assert paragraph_problems(good + ["| `c.py` | a table row |"], MODULE_ENTRY, 1) != [], "a table row"
    assert paragraph_problems(["", "`a.py`: one.", "`b.py`: two.", ""], MODULE_ENTRY, 1) != [], "two entries in one paragraph"
    assert paragraph_problems(["", "`a.py`: one.", "continued on a next line", ""], MODULE_ENTRY, 1) != [], "an entry that runs on"
    assert paragraph_problems(["", "Prose.", "`a.py`: one.", ""], MODULE_ENTRY, 1) != [], "no blank line before"
    assert paragraph_problems([], MODULE_ENTRY, 1) == ["no entry"]
    limit = ["", "**L1.** A copy is new.", "Built by: stage 2. Test: `t.py`, `test_x`.", "", "**L2.** Two.", "Built by: stage 4. Test: anything.", ""]
    assert paragraph_problems(limit, LIMIT_START, 2) == []
    assert paragraph_problems(["", "**L1.** A copy is new.", "", "**L2.** Two.", "Built by: x. Test: y.", ""], LIMIT_START, 2) != [], "a limit with no second line"
    assert paragraph_problems(["", "**L1.** One.", "Built by: stage 2", ""], LIMIT_START, 2) != [], "a second line that is not the form"
    assert paragraph_problems(["", "**L1.** One.", "Built by: x. Test: y.", "**L2.** Two.", "Built by: x. Test: y.", ""], LIMIT_START, 2) != [], "no blank line between limits"
