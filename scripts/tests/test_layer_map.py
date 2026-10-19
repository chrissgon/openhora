"""The dependency map between the layers: every arrow of the layer diagram in
docs/architecture/platform/README.md is a row of ALLOWED below, and a Python file that reaches a file it may not is
a failing test.

What the scan reads: every .py file under skills/*/scripts/, shared/, providers/, contracts/, agents/, templates/,
packs/, scripts/, evals/, adapters/ and runtime/ (test folders excluded: they may reach anything). What it
collects, as repository-relative targets, only code (.py and .sh); reading a data file is not a dependency here:
  - an import (a sibling module, a dotted repository path, or a module whose file name is found in the repository);
  - a string that is wholly a path to a script ("providers/resolve.py");
  - os.path.join(...) or a `/` chain of Path objects whose literal parts name a script, a variable part read as a
    wildcard; a chain that ends in a variable inside a scripts/ folder is the target `<top>/.../scripts/*`.
A subprocess argument list is covered by the strings it holds. A file named only inside prose (a docstring, an
error message, a usage text) is not a string that is wholly a path and is not collected.

What the scan cannot see: a path built from variables only, a module loaded by a name read from a data file, and
the targets that a provider resolution returns at run time (providers/resolve.py exists so that those are not
paths in code). A new way of reaching a file is added to `scan` with its own case in the self-test below.

ALLOWED is the rules of the layer diagram. TOLERATED is every edge the code has today that ALLOWED refuses, each
named after the finding of the platform review (removed on 2026-10-14: git show d3e60770:docs/architecture/platform/review-2026-10-06.md) that removes it (or that names the
rule it breaks), so that the list only shrinks: the test fails on an edge that is neither allowed nor tolerated,
and on a tolerated row the scan no longer finds. NOT_A_DEPENDENCY lists the paths the scan finds that are not a
dependency (a path read as text, a name in a table), each with the reason, held to the same staleness rule.

Run: uv run --with pytest pytest scripts/tests/test_layer_map.py
Print every edge the scan finds: python3 scripts/tests/test_layer_map.py
"""
from __future__ import annotations

import ast
import fnmatch
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TOP = ("skills", "shared", "providers", "contracts", "agents", "templates", "packs", "scripts", "evals",
       "adapters", "runtime")
CODE = re.compile(r"\.(py|sh)$")
WHOLE_PATH = re.compile(r"(?:\./)?[\w./*<>{}-]+\.(?:py|sh)")
STDLIB = getattr(sys, "stdlib_module_names", frozenset())


# --- the scan ---------------------------------------------------------------------------------------------

def sources(root):
    """The files the scan reads, repository-relative with forward slashes."""
    found = []
    for top in TOP:
        for path in sorted((Path(root) / top).rglob("*.py")):
            parts = path.relative_to(root).parts
            if {"tests", "__pycache__", "node_modules"} & set(parts):
                continue
            if top == "skills" and not (len(parts) > 3 and parts[2] == "scripts"):
                continue
            found.append("/".join(parts))
    return found


def code_files(root):
    """Every .py and .sh file a target can be."""
    found = set()
    for top in TOP:
        for path in (Path(root) / top).rglob("*"):
            parts = path.relative_to(root).parts
            if path.suffix not in (".py", ".sh") or {"node_modules", "__pycache__", "tests"} & set(parts):
                continue
            if top == "skills" and not (len(parts) > 3 and parts[2] == "scripts"):
                continue  # a skill's evals/ hold fixtures, not code of the repository
            found.add("/".join(parts))
    return found


def _docstrings(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _literal_parts(nodes):
    """The literal text of each part, "*" for a part that is not a literal; leading variables dropped."""
    parts = [n.value if isinstance(n, ast.Constant) and isinstance(n.value, str) else "*" for n in nodes]
    while parts and parts[0] == "*":
        parts.pop(0)
    return parts


def _div_chain(node):
    parts = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        parts.append(node.right)
        node = node.left
    parts.append(node)
    return list(reversed(parts))


def _is_path_call(node):
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return name in ("join", "Path", "PurePath")


def _resolve(path, here, files):
    """The files a path names: an exact repository path, a glob of one, a unique tail of one, a sibling."""
    while path.startswith("../"):
        path = path[3:]
    if path.startswith("./"):
        path = path[2:]
    pattern = re.compile(re.escape(path).replace(r"\*", "[^/]*"))
    if path.split("/")[0] in TOP:
        return sorted(f for f in files if pattern.fullmatch(f))
    if "/" in path:
        return sorted(f for f in files if re.fullmatch(".*/" + pattern.pattern, f))
    sibling = here + "/" + path
    return [sibling] if sibling in files else []


def _import_targets(module, here, files, by_name):
    parts = module.split(".")
    if parts[0] in STDLIB:
        return []
    dotted = "/".join(parts)
    for candidate in (dotted + ".py", dotted + "/__init__.py"):
        if candidate in files:
            return [candidate]
    name = parts[-1] + ".py"
    if here + "/" + name in files:
        return [here + "/" + name]
    return by_name.get(name, []) if len(parts) == 1 else []


def edges_of(root, rel, files, by_name):
    tree = ast.parse((Path(root) / rel).read_text(encoding="utf-8"))
    here = os.path.dirname(rel)
    docs = _docstrings(tree)
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.update(_import_targets(alias.name, here, files, by_name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = here
                for _ in range(node.level - 1):
                    base = os.path.dirname(base)
                for name in ([node.module] if node.module else [a.name for a in node.names]):
                    candidate = f"{base}/{name.replace('.', '/')}.py"
                    if candidate in files:
                        out.add(candidate)
            else:
                module = node.module or ""
                out.update(_import_targets(module, here, files, by_name))
                if module.split(".")[0] not in STDLIB:
                    for alias in node.names:
                        out.update(_import_targets(module + "." + alias.name, here, files, by_name))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            text = node.value.strip()
            if WHOLE_PATH.fullmatch(text):
                out.update(_resolve(text, here, files))
        elif (isinstance(node, ast.Call) and _is_path_call(node)) or (
                isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            parts = _literal_parts(node.args if isinstance(node, ast.Call) else _div_chain(node))
            if not parts:
                continue
            joined = "/".join(parts)
            if CODE.search(joined):
                out.update(_resolve(joined, here, files))
            elif parts[0] in TOP and "scripts" in parts[1:] and parts[-1] == "*":
                out.add(joined)  # a script of unknown name inside a scripts/ folder
    out.discard(rel)
    return out


def scan(root=ROOT):
    """{file: {target, ...}} for every source file, targets repository-relative (a glob where a part is a variable)."""
    files = code_files(root)
    by_name = {}
    for f in sorted(files):
        by_name.setdefault(os.path.basename(f), []).append(f)
    return {rel: edges_of(root, rel, files, by_name) for rel in sources(root)}


def edge_set(root=ROOT):
    return {(f, t) for f, targets in scan(root).items() for t in targets}


# --- the map ----------------------------------------------------------------------------------------------

CORE = ("skills/", "shared/", "providers/", "contracts/", "agents/", "templates/", "packs/")
NOT_RUNTIME = CORE + ("scripts/", "evals/", "adapters/")
NOT_RUNTIME_OR_LAB = CORE + ("scripts/", "adapters/")

# What a runtime module may reach outside runtime/: the resolver of providers, the store (a provider the runtime
# owns), the secret resolver (rule R13: a credential is read through it), the scripts the runtime shares with the
# first runtime.
RUNTIME_OUTSIDE = ("providers/resolve.py", "providers/store/", "providers/secrets/resolver.py",
                   "scripts/select_skills.py", "scripts/evidence.py", "scripts/redact.py")

# The first matching row decides. A target is a folder (trailing "/"), a file or a glob; "{own}" is the folder of
# the skill the file belongs to.
ALLOWED = (
    # layer 1, skills: its own folder, and providers only through the resolver (gap A11)
    ("skills/*/scripts/**", ("{own}", "providers/resolve.py")),
    # layers 2 and 3 follow nothing above them: never the lab, the runtime, the adapters, scripts/ (gap A17)
    ("providers/**", ("providers/",)),
    ("shared/**", ("shared/",)),
    ("contracts/**", ("contracts/",)),
    ("agents/**", ("agents/",)),
    ("templates/**", ("templates/",)),
    ("packs/**", ("packs/",)),
    # layer 4, the lab: never the runtime
    ("evals/**", NOT_RUNTIME),
    # layer 5, adapters: never the runtime, never the lab
    ("adapters/**", NOT_RUNTIME_OR_LAB),
    # layer 7, the shells: the operations layer only; the local service and the MCP mode (neither calls a platform)
    # may also import the kit they share, which is handed the operations object and imports nothing of runtime/; the
    # local service also imports service_bridge.py (standard library only), which starts the messaging bridge as a child
    # process (--messaging) and is the one file that names runtime/messaging.py
    ("runtime/cli.py", ("runtime/ops.py",)),
    ("runtime/chat.py", ("runtime/ops.py",)),
    ("runtime/service.py", ("runtime/ops.py", "runtime/shell_kit.py", "runtime/service_bridge.py")),
    ("runtime/service_bridge.py", ("runtime/messaging.py",)),
    ("runtime/mcp.py", ("runtime/ops.py", "runtime/shell_kit.py")),
    ("runtime/shell_kit.py", ()),
    # the messaging bridge (MSG-1): a shell over ops.py and the kit, with its own modules; the modules reach the kit and the
    # resolver of providers (the one function that runs a messenger provider's verb), never ops.py
    ("runtime/messaging.py", ("runtime/ops.py", "runtime/shell_kit.py", "runtime/messaging_*.py")),
    # (ATT-1b: the modules also read runtime/attachments.py, the limits, sentences and folders of the files a sender sends: pure helpers and the one fetch lock,
    # which reach the intake and the sources inside runtime/, never the operations layer; RM-1: and runtime/reminders.py, the pure words of a reminder; LR-1: and runtime/phrases.py, the table of sentences in the project's language; NR-1: and runtime/natural.py, a line in the person's own words matched to a reminder operation by code)
    ("runtime/messaging_*.py", ("runtime/messaging_*.py", "runtime/shell_kit.py", "runtime/attachments.py", "runtime/reminders.py", "runtime/phrases.py", "runtime/natural.py", "runtime/natural_time.py", "providers/resolve.py", "scripts/redact.py")),
    # the handlers: the resolver of providers and the shell's verbs, nothing imported from runtime/
    # a handler reaches the resolver, the terminal shell, the shared credential formats and its sibling handlers
    ("runtime/handlers/*.py", ("providers/resolve.py", "runtime/cli.py", "scripts/redact.py", "runtime/handlers/")),
    # layer 6, the runtime: runtime/lab.py is the one file that reaches evals/ and, through the lab, the adapters
    # (it also loads scripts/image_lock.py, the one reading of the published eval image's lock file: no other module does)
    ("runtime/lab.py", ("runtime/", "evals/", "adapters/", "scripts/image_lock.py") + RUNTIME_OUTSIDE),
    # the one runner of a skill's script, as an isolated subprocess with a scrubbed environment; no other module of
    # runtime/ reaches skills/ as code (runtime/tests/test_isolated.py holds that)
    ("runtime/isolated.py", ("runtime/", "skills/*/scripts/*") + RUNTIME_OUTSIDE),
    ("runtime/*.py", ("runtime/",) + RUNTIME_OUTSIDE),
    # scripts/: anything but the runtime (the first runtime, scripts/runtime.py, reaches providers/ and adapters/;
    # it leaves with stage 7)
    # scripts/validate.py alone may also read the runtime's flow-file checker by path: tooling may read a layer's
    # own checker (the validator reuses the runtime's flow-file rules instead of holding a copy); a layer never
    # reads tooling except the scripts the runtime rows list.
    ("scripts/validate.py", ("scripts/",) + NOT_RUNTIME + ("runtime/flow_files.py",)),
    ("scripts/**", ("scripts/",) + NOT_RUNTIME),
)

# Edges the code has today that ALLOWED refuses: (file, target) -> the finding that removes it. Only shrinks.
TOLERATED = {
    ("runtime/ops.py", "scripts/validate.py"):
        "finding 11 (outside the fix plan: waits for the next change of reference model): _effect_words reads the SIDE_EFFECTS line of scripts/validate.py with a regex",
    ("skills/mkt-engage/scripts/policy_gate.py", "skills/brand-profile/scripts/sensitive_topics.py"):
        "finding 17 (a skill script falls back to another skill's copy of a shared script; removed at the next "
        "Y change of mkt-engage)",
    ("runtime/handlers/social.py", "skills/mkt-engage/scripts/parse_notification.py"):
        "finding 9 (skill code on the host; removed by stage 7, WP-7.6, through runtime/isolated.py)",
    ("runtime/handlers/social_vote.py", "skills/brand-identity/scripts/render.py"):
        "finding 9 (skill code on the host; removed by stage 7, WP-7.6, through runtime/isolated.py)",
    ("runtime/handlers/social_vote.py", "skills/mkt-publish/scripts/payload.py"):
        "finding 9 (skill code on the host; removed by stage 7, WP-7.6, through runtime/isolated.py)",
    ("runtime/handlers/social_vote.py", "skills/mkt-social-copy/scripts/check_post.py"):
        "finding 9 (skill code on the host; removed by stage 7, WP-7.6, through runtime/isolated.py)",
    ("runtime/handlers/social_vote.py", "skills/mkt-vote-round/scripts/vote_state.py"):
        "finding 9 (skill code on the host; removed by stage 7, WP-7.6, through runtime/isolated.py)",
    ("runtime/handlers/social_vote.py", "skills/mkt-vote-round/scripts/vote_update.py"):
        "finding 9 (skill code on the host; removed by stage 7, WP-7.6, through runtime/isolated.py)",
}

# Paths the scan finds that are not a dependency: (file, target) -> why.
NOT_A_DEPENDENCY = {
    ("skills/mkt-publish/scripts/payload.py", "providers/secrets/resolver.py"):
        "the script hashes that file into the scheduled job's snapshot (the integrity record of what the job will "
        "run); nothing is loaded or run",
    ("runtime/handlers/social.py", "skills/mkt-engage/scripts/policy_gate.py"):
        "the handler hashes that file into the scheduled tick's pin (the integrity record of what the tick will run) "
        "and checks that it exists; nothing is loaded or run: the engagement gate runs inside the operations layer, "
        "through runtime/isolated.py (CONS-2a)",
    ("providers/secrets/resolver.py", "runtime/effects.py"):
        "a row of the secrets table names the module that reads the secret; nothing is loaded",
    ("scripts/architecture_tables.py", "runtime/operations.py"):
        "the generator reads the literal table in the source text of the file to write a documentation table; "
        "nothing is imported",
    ("scripts/architecture_tables.py", "runtime/dispatcher.py"):
        "the generator reads the source text of the file to write a documentation table; nothing is imported",
    ("scripts/architecture_tables.py", "runtime/service.py"):
        "the generator reads the routes in the source text of the file to write a documentation table; nothing is "
        "imported",
    ("scripts/architecture_tables.py", "runtime/project_config.py"):
        "the generator reads the closed key lists in the source text of the file to write a documentation table; "
        "nothing is imported and no configuration is opened",
    ("scripts/architecture_tables.py", "runtime/autonomy.py"):
        "the generator reads the closed key lists in the source text of the file to write a documentation table; "
        "nothing is imported",
    ("scripts/architecture_tables.py", "runtime/deps.py"):
        "the generator reads the closed key list and the names of the recipes in the source text of the file to write "
        "a documentation table; nothing is imported",
}


def _matches(path, pattern):
    return fnmatch.fnmatchcase(path, pattern.replace("**", "*"))


def _row(file):
    for pattern, targets in ALLOWED:
        if _matches(file, pattern):
            return targets
    return None


def allowed(file, target):
    targets = _row(file)
    if targets is None:
        return False
    own = "/".join(file.split("/")[:2]) + "/" if file.startswith("skills/") else None
    for rule in targets:
        rule = own if rule == "{own}" else rule
        if rule is None:
            continue
        if rule.endswith("/") and target.startswith(rule):
            return True
        if target == rule or (not rule.endswith("/") and _matches(target, rule)):
            return True
    return False


def violations(edges):
    """The edges neither allowed nor tolerated nor named as not a dependency."""
    return sorted(e for e in edges if not allowed(*e) and e not in TOLERATED and e not in NOT_A_DEPENDENCY)


# --- the tests --------------------------------------------------------------------------------------------

EDGES = edge_set()


def test_every_edge_of_the_code_is_allowed_or_tolerated():
    bad = violations(EDGES)
    assert not bad, "an arrow the layer diagram does not have (add a row to ALLOWED only if the diagram says so):\n" + \
        "\n".join(f"  {file} -> {target}" for file, target in bad)


def test_a_fixed_row_is_removed_from_the_tolerated_list():
    stale = sorted(e for e in TOLERATED if e not in EDGES)
    assert not stale, f"tolerated rows the scan no longer finds, remove them: {stale}"
    now_allowed = sorted(e for e in TOLERATED if allowed(*e))
    assert not now_allowed, f"tolerated rows that ALLOWED now accepts, remove them: {now_allowed}"


def test_a_path_named_as_not_a_dependency_is_still_found():
    stale = sorted(e for e in NOT_A_DEPENDENCY if e not in EDGES)
    assert not stale, f"rows the scan no longer finds, remove them: {stale}"
    assert not sorted(e for e in NOT_A_DEPENDENCY if allowed(*e)), "a row that ALLOWED already accepts"
    assert all(why for why in NOT_A_DEPENDENCY.values())


def test_a_tolerated_row_names_the_finding_that_removes_it():
    for edge, why in TOLERATED.items():
        assert re.match(r"findings? \d+", why), (edge, why)


def test_every_source_file_has_a_row_in_the_map():
    assert not [f for f in sources(ROOT) if _row(f) is None]


def test_the_rules_the_diagram_states_hold_for_the_code_as_it_is():
    """The same rules, read straight off the edges, so a wrong row of ALLOWED cannot hide an arrow."""
    for file, target in EDGES:
        if (file, target) in NOT_A_DEPENDENCY:
            continue
        if file.startswith(("providers/", "shared/", "contracts/", "agents/", "templates/", "packs/")):
            assert not target.startswith(("evals/", "runtime/", "adapters/", "scripts/")), (file, target)
        if file.startswith("skills/"):
            assert not target.startswith(("evals/", "runtime/", "adapters/", "scripts/")), (file, target)
        if file.startswith("evals/") or file.startswith("adapters/"):
            assert not target.startswith("runtime/"), (file, target)
        if file.startswith("runtime/") and target.startswith("evals/"):
            assert file == "runtime/lab.py", (file, target)
        if file in ("runtime/cli.py", "runtime/chat.py"):
            assert target == "runtime/ops.py", (file, target)
        if file == "runtime/messaging.py":  # the bridge's shell imports ops.py, shell_kit.py and its own modules
            assert target in ("runtime/ops.py", "runtime/shell_kit.py") or fnmatch.fnmatch(target, "runtime/messaging_*.py"), (file, target)
        if file == "runtime/mcp.py":  # a network-free shell imports only ops.py and shell_kit.py
            assert target in ("runtime/ops.py", "runtime/shell_kit.py"), (file, target)
        if file == "runtime/service.py":  # the same, and service_bridge.py, which starts the bridge as a child process
            assert target in ("runtime/ops.py", "runtime/shell_kit.py", "runtime/service_bridge.py"), (file, target)
        if file == "runtime/service_bridge.py":  # it imports nothing of the runtime and names the bridge's command only
            assert target == "runtime/messaging.py", (file, target)
        if file == "runtime/shell_kit.py":  # the kit imports nothing of the runtime: it is handed the operations object
            assert not target.startswith("runtime/"), (file, target)
        if file.startswith("runtime/handlers/") and (file, target) not in TOLERATED:
            assert target in ("providers/resolve.py", "runtime/cli.py", "scripts/redact.py") \
                or target.startswith("runtime/handlers/"), (file, target)


# --- the scanner's own cases, on a small tree -------------------------------------------------------------

def _tree(tmp_path, files):
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_the_scan_sees_each_way_of_reaching_a_file(tmp_path):
    root = _tree(tmp_path, {
        "providers/resolve.py": "",
        "providers/store/sqlite.py": "",
        "providers/secrets/resolver.py": "",
        "evals/eval_run.py": "",
        "scripts/stage.py": "",
        "adapters/h/run-prompt.sh": "",
        "skills/a-one/scripts/own.py": "",
        "skills/a-one/scripts/main.py": (
            'import os\nfrom own import thing\nimport json\n'
            'RESOLVE = "providers/resolve.py"\n'
            'STORE = os.path.join(ROOT, "providers", "store", "sqlite.py")\n'
            'LAB = ROOT / "evals" / "eval_run.py"\n'
            'RUN = ["bash", "adapters/h/run-prompt.sh", "--x"]\n'
            'WHICH = os.path.join(ROOT, "skills", name, "scripts", script)\n'
            '"""A docstring that says scripts/stage.py is not a dependency."""\n'
            'MESSAGE = "see scripts/stage.py for the rest"\n'),
    })
    found = scan(root)["skills/a-one/scripts/main.py"]
    assert found == {"skills/a-one/scripts/own.py", "providers/resolve.py", "providers/store/sqlite.py",
                     "evals/eval_run.py", "adapters/h/run-prompt.sh", "skills/*/scripts/*"}


def test_a_planted_violation_fails_the_map(tmp_path):
    root = _tree(tmp_path, {
        "evals/eval_run.py": "",
        "runtime/ops.py": "",
        "runtime/cli.py": "from ops import run\n",
        "providers/vcs/x.py": 'import importlib.util\nPATH = "evals/eval_run.py"\n',
        "runtime/handlers/h.py": 'MOD = "runtime/ops.py"\n',
        "evals/other.py": 'from runtime import ops\nimport ops\n',
    })
    bad = violations(edge_set(root))
    assert ("providers/vcs/x.py", "evals/eval_run.py") in bad
    assert ("runtime/handlers/h.py", "runtime/ops.py") in bad
    assert ("evals/other.py", "runtime/ops.py") in bad
    assert not [e for e in bad if e[0] == "runtime/cli.py"]


def test_the_allowed_rules_say_what_the_diagram_says():
    """The ALLOWED rules on representative pairs. This test reads no diagram: the layer diagram of
    docs/architecture/platform/README.md is held to the rows by convention, and the scan of
    test_every_edge_of_the_code_is_allowed_or_tolerated holds the code to them."""
    assert allowed("skills/a/scripts/x.py", "skills/a/scripts/y.py")
    assert not allowed("skills/a/scripts/x.py", "skills/b/scripts/y.py")
    assert allowed("skills/a/scripts/x.py", "providers/resolve.py")
    assert not allowed("skills/a/scripts/x.py", "providers/vcs/github.py")
    assert not allowed("providers/vcs/github.py", "scripts/validate.py")
    assert allowed("providers/vcs/github.py", "providers/secrets/resolver.py")
    assert not allowed("evals/eval_run.py", "runtime/lab.py")
    assert not allowed("adapters/api/run_agent.py", "evals/eval_run.py")
    assert allowed("runtime/lab.py", "evals/eval_run.py")
    assert not allowed("runtime/ops.py", "evals/eval_run.py")
    assert allowed("runtime/cli.py", "runtime/ops.py") and not allowed("runtime/cli.py", "runtime/plan.py")
    assert allowed("runtime/service.py", "runtime/ops.py") and not allowed("runtime/service.py", "providers/store/sqlite.py")
    assert allowed("runtime/service.py", "runtime/service_bridge.py") and not allowed("runtime/service.py", "runtime/messaging.py")
    assert allowed("runtime/service_bridge.py", "runtime/messaging.py") and not allowed("runtime/service_bridge.py", "runtime/ops.py")
    assert not allowed("runtime/service_bridge.py", "runtime/service.py") and not allowed("runtime/service_bridge.py", "runtime/shell_kit.py")
    assert not allowed("runtime/service_bridge.py", "providers/resolve.py")
    assert not allowed("runtime/service.py", "runtime/lab.py") and not allowed("runtime/service.py", "runtime/plan.py")
    assert allowed("runtime/mcp.py", "runtime/ops.py") and not allowed("runtime/mcp.py", "runtime/service.py")
    assert allowed("runtime/mcp.py", "runtime/shell_kit.py") and allowed("runtime/service.py", "runtime/shell_kit.py")
    assert not allowed("runtime/cli.py", "runtime/shell_kit.py") and not allowed("runtime/chat.py", "runtime/shell_kit.py")
    assert not allowed("runtime/shell_kit.py", "runtime/ops.py") and not allowed("runtime/shell_kit.py", "providers/store/sqlite.py")
    assert not allowed("runtime/mcp.py", "providers/store/sqlite.py") and not allowed("runtime/mcp.py", "runtime/lab.py")
    assert allowed("runtime/handlers/h.py", "runtime/cli.py") and not allowed("runtime/handlers/h.py", "runtime/ops.py")
    assert not allowed("scripts/doctor.py", "runtime/ops.py")
    assert allowed("scripts/runtime.py", "adapters/api/run-agent.sh")


if __name__ == "__main__":
    for source, targets in sorted(scan().items()):
        for target in sorted(targets):
            state = ("allowed" if allowed(source, target) else "tolerated" if (source, target) in TOLERATED
                     else "not a dependency" if (source, target) in NOT_A_DEPENDENCY else "REFUSED")
            print(f"{source} -> {target}  [{state}]")
