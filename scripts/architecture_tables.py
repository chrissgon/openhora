#!/usr/bin/env python3
"""Generate the volatile tables of the architecture pages (docs/architecture/platform/) from the code.

Usage:
  python3 scripts/architecture_tables.py --write    # rewrite every generated block of the pages
  python3 scripts/architecture_tables.py --check    # exit 1 and name each block that differs from its source
  python3 scripts/architecture_tables.py --print <table>   # print one table and change nothing
  python3 scripts/architecture_tables.py --help

  --root <path>   the workbench checkout to read and write, instead of the one this script is in

A page holds a generated table between the lines `<!-- generated: <table> -->` and `<!-- /generated -->`;
nothing outside them is touched, and a block is never edited by hand. Each table has one source:

  artifacts-by-owner    every outputs and updates path and its skills: the skills' frontmatters, through
                        scripts/owner_table.py (the same rows as the table of contracts/project-layout.md)
  provider-classes      each class of the "Verbs per class" table of providers/CONTRACT.md, its folder
                        (providers/resolve.py), its implementations and the verbs each one declares, read from
                        the file's text (a VERBS constant, the choices of its "verb" argument, a "--check" flag):
                        no provider is imported or run
  limits                the limits table of contracts/runtime.md, and the test named after each limit
                        (test_limit_<nn>_...) found under runtime/tests/ and providers/store/tests/
  operations            OPERATIONS of runtime/operations.py, the table of operations: each one's function, verb,
                        channels, whether it calls a model, and what it does (its `help`)
  cli-verbs             the same table: the verbs of runtime/cli.py, the flags each reads and the function it calls
  say-commands          the same table: the conversation's commands (the rows that list the chat channel and
                        CHAT_OWN), with their `help`
  dispatcher-jobs       ENTRY_VERBS and JOBS of runtime/dispatcher.py, with the usage lines of its docstring
  store-migrations      MIGRATIONS of providers/store/sqlite.py: number, description, what each creates
  task-runtime-tables   the tables migrations 2 and later create, with their columns
  gate-keys             the keys of evals/eval-gate.json and the measurement version; a value is shown only
                        when it is a number or a model or adapter id, never a text that could be a credential
  runtime-modules       the first sentence of the docstring of each module of runtime/ and runtime/handlers/
  service-routes        ROUTES of runtime/service.py: the constant arguments of each _route(...) call
  handlers              VERBS of each file of runtime/handlers/, read as runtime/ops.py reads it; a file without
                        one shows a dash
  config-keys           the closed key lists of the configuration: REQUIRED, TASK_RUNTIME_KEYS, FIRST_RUNTIME_KEYS,
                        CODE_KEYS and PRICE_KEYS (computed from PRICE_KINDS) of runtime/project_config.py,
                        AGENT_KEYS and BOUNDS_KEYS of runtime/autonomy.py, ENTRY_KEYS and the names of RECIPES of
                        runtime/deps.py; names only, no configuration is opened and no value is read
  flow-files            each flows/*.json: the flow, its title, and its tasks' keys and skills in order
  roles                 runtime/roles.json: each key and its value (names of skills, areas and packs)
  held-reasons          REASONS of runtime/dispatcher.py: its text literals and the module's own text constants

Every source is read as text or parsed with ast (the table of operations is read with ast.literal_eval of its
two literals; runtime/*.py are never imported, since they import their siblings); nothing is executed but
scripts/owner_table.py, scripts/validate.py (the frontmatter parser) and providers/resolve.py (the class-to-folder
rule), which read files only. scripts/validate.py reports a stale block as a warning (rule architecture-tables).

output: --print writes the table on stdout; --check names each stale block on stderr.
exit codes: 0 ok (written, or every block current), 1 --check found a stale block, 2 usage error, an unknown
table name in a page, or a source that cannot be read.
Standard library only.
"""
import ast
import glob
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = os.path.join("docs", "architecture", "platform")
BLOCK_RE = re.compile(r"(<!-- generated: ([a-z0-9-]+) -->\n)(.*?)(<!-- /generated -->)", re.S)
NONE = "-"
NO_TEST = "no test named"
LIMIT_TEST_DIRS = ("runtime/tests", "providers/store/tests")
LIMIT_TEST_RE = re.compile(r"^def (test_limit_(\d+)_\w+)\(", re.M)
SHOWN_TEXT_KEYS = re.compile(r"(_model|_harness|^grader)$")


class SourceError(Exception):
    """A source of a table cannot be read."""


# --- helpers -----------------------------------------------------------------------------------------------------

def _read(root, rel):
    path = os.path.join(root, rel)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        raise SourceError(f"{rel}: {e.strerror}") from None


def _tree(root, rel):
    try:
        return ast.parse(_read(root, rel))
    except SyntaxError as e:
        raise SourceError(f"{rel}: {e}") from None


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _constant(tree, name):
    """The literal value of a top-level assignment `name = <literal>`, or None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


def _cell(text):
    return re.sub(r"(?<!\\)\|", r"\\|", " ".join(str(text).split()))


def _code(text):
    return f"`{text}`"


def _first_sentence(doc):
    """The docstring's first sentence, on one line: up to the first period followed by a space or the end."""
    text = " ".join((doc or "").split())
    m = re.match(r"(.+?\.)(\s|$)", text)
    return m.group(1) if m else text


def _table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def _markdown_rows(text, heading, first_header):
    """The rows (lists of cells) of the first table whose header starts with first_header under the heading."""
    start = text.find(heading)
    if start == -1:
        raise SourceError(f"no heading {heading!r}")
    m = re.search(r"^\|\s*" + re.escape(first_header) + r"\s*\|.*$", text[start:], re.M)
    if not m:
        raise SourceError(f"no table starting with {first_header!r} under {heading!r}")
    rows = []
    for line in text[start + m.end():].lstrip("\n").split("\n"):
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        if not re.fullmatch(r":?-+:?", cells[0]):
            rows.append(cells)
    return rows


# --- the tables ----------------------------------------------------------------------------------------------------

def artifacts_by_owner(root):
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import validate  # noqa: E402  the one frontmatter parser
    owner_table = _load("owner_table_for_architecture", os.path.join(here, "owner_table.py"))
    return owner_table.table(validate.declarations(root))


def verbs_of(path):
    """(has --check, [verbs]) of one provider implementation, read from its text: a top-level VERBS constant (dict
    keys or a sequence), else the choices of an add_argument("verb", choices=...). Nothing is imported."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    check, verbs = False, []
    for node in tree.body:  # VERBS = {"name": cmd_name, ...} or a sequence of names
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "VERBS" for t in node.targets):
            if isinstance(node.value, ast.Dict):
                verbs = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            elif isinstance(node.value, (ast.Tuple, ast.List)):
                verbs = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "--check":
            check = True
        if not verbs and isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument" \
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == "verb":
            for kw in node.keywords:
                if kw.arg == "choices":
                    try:
                        verbs = [str(v) for v in ast.literal_eval(kw.value)]
                    except ValueError:
                        pass
    return check, verbs


def provider_classes(root):
    text = _read(root, "providers/CONTRACT.md")
    classes = []
    for row in _markdown_rows(text, "## Verbs per class", "Class"):
        classes += re.findall(r"`([^`]+)`", row[0])
    resolve = _load("resolve_for_architecture", os.path.join(root, "providers", "resolve.py"))
    rows = []
    for cls in classes:
        folder = resolve.folder(cls)
        names = resolve.implementations_in(folder, root=root)
        if not names:
            rows.append([_code(cls), _code(f"{folder}/"), "none ships", NONE])
            continue
        for name in names:
            check, verbs = verbs_of(os.path.join(root, "providers", folder, name + ".py"))
            shown = (["--check"] if check else []) + verbs
            impl = _code(f"{name}.py")
            if resolve.PARAMETER_ROLES and cls.split(":")[0] in resolve.PARAMETER_ROLES:
                platforms = resolve.served_platforms(cls, name, root=root)
                impl += f" (PLATFORMS: {', '.join(platforms) or 'none'})"
            rows.append([_code(cls), _code(f"{folder}/"), impl, ", ".join(_code(v) for v in shown) or NONE])
    return _table(["Class", "Folder", "Implementation", "Verbs"], rows)


def _limit_tests(root):
    found = {}
    for folder in LIMIT_TEST_DIRS:
        for path in sorted(glob.glob(os.path.join(root, folder, "test_*.py"))):
            with open(path, encoding="utf-8") as f:
                for m in LIMIT_TEST_RE.finditer(f.read()):
                    found.setdefault(int(m.group(2)), []).append((os.path.relpath(path, root), m.group(1)))
    return found


def limits(root):
    rows_in = _markdown_rows(_read(root, "contracts/runtime.md"), "## The limits", "#")
    tests = _limit_tests(root)
    rows = []
    for cells in rows_in:
        m = re.fullmatch(r"L(\d+)", cells[0])
        if not m:
            continue
        named = tests.get(int(m.group(1)), [])
        cell = "; ".join(f"`{path}`, `{name}`" for path, name in named) or NO_TEST
        rows.append([cells[0], cells[1], cells[2] if len(cells) > 2 else NONE, cell])
    return _table(["#", "Limit", "Built by", "Test named after it"], rows)


def _operations_table(root):
    """(OPERATIONS, CHAT_OWN) of runtime/operations.py, read with ast.literal_eval: nothing is executed."""
    tree = _tree(root, "runtime/operations.py")
    rows, own = _constant(tree, "OPERATIONS"), _constant(tree, "CHAT_OWN")
    if not rows:
        raise SourceError("runtime/operations.py: OPERATIONS is not a literal tuple of rows")
    return rows, own or ()


def _flag(arg):
    return arg.get("flag") or arg["name"].replace("_", "-")


def _flags(row):
    """The flags a row's verb reads: required ones bare, optional ones in brackets; a text argument is the pair."""
    out = []
    for arg in row["args"]:
        flag = "--text | --text-file" if arg["kind"] == "text" else "--" + _flag(arg)
        out.append(flag if arg.get("required") else f"[{flag}]")
    return out


def cli_verbs(root):
    rows = []
    for row in _operations_table(root)[0]:
        if "terminal" in row["channels"]:
            rows.append([_code(row["name"]), " ".join(_code(f) for f in _flags(row)) or NONE, _code(row["call"])])
    return _table(["Verb", "Flags it reads", "Operation"], rows)


def _model(value):
    if value is True:
        return "yes"
    return f"yes, {value}" if value else "no"


def operations(root):
    rows = [[_code(r["call"]), _code(r["name"]), ", ".join(r["channels"]), _model(r["model"]), r["help"]]
            for r in _operations_table(root)[0]]
    return _table(["Operation", "Verb of `cli.py`", "Channels", "Calls a model", "What it does"], rows)


def _usage(row):
    parts = ["/" + row["name"]]
    for arg in row["args"]:
        if arg["kind"] in ("int", "str", "text"):
            label = arg.get("label") or (_flag(arg) if arg["kind"] == "int" else arg["name"])
            parts.append(f"<{label}>" if arg.get("required") else f"[{label}]")
    return " ".join(parts)


def say_commands(root):
    rows, own = _operations_table(root)
    first = [("/help" if not c.get("args") else f"/{c['name']} <{c['args']}>", c["help"]) for c in own if c.get("order") == "first"]
    last = [("/help" if not c.get("args") else f"/{c['name']} <{c['args']}>", c["help"]) for c in own if c.get("order") != "first"]
    chat = [(_usage(r), r["help"]) for r in rows if "chat" in r["channels"]]
    return _table(["Command", "What it does (its `help` in the table)"], [[_code(u), h] for u, h in first + chat + last])


def dispatcher_jobs(root):
    tree = _tree(root, "runtime/dispatcher.py")
    verbs, jobs = _constant(tree, "ENTRY_VERBS") or (), _constant(tree, "JOBS") or {}
    doc = ast.get_docstring(tree) or ""
    usage = {}
    for line in doc.splitlines():
        m = re.match(r"\s*\S*python3 runtime/dispatcher\.py\s+(\S+)\s*(.*)$", line)
        if m and m.group(1) in verbs:
            parts = re.split(r"\s{2,}", m.group(2).strip(), maxsplit=1)
            usage.setdefault(m.group(1), (parts[0], parts[1] if len(parts) > 1 else ""))
    rows = []
    for verb in verbs:
        flags, what = usage.get(verb, ("", ""))
        minutes = jobs.get(verb)
        rows.append([_code(verb), _code(flags) if flags else NONE, what or NONE,
                     f"{minutes} minutes" if minutes is not None else NONE])
    return _table(["Verb", "Flags", "What it does (the module's docstring)", "Time limit (`JOBS`)"], rows)


def _migrations(root):
    tree = _tree(root, "providers/store/sqlite.py")
    found = _constant(tree, "MIGRATIONS")
    if not isinstance(found, dict):
        raise SourceError("providers/store/sqlite.py: MIGRATIONS is not a literal dict")
    return found


def _split_top(text):
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return parts + [cur]


def _created_tables(statement):
    m = re.match(r"\s*CREATE TABLE\s+(\w+)\s*\((.*)\)\s*$", statement, re.S)
    if not m:
        return None
    columns = []
    for part in _split_top(m.group(2)):
        word = part.split()[0] if part.split() else ""
        if word.upper() not in ("PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT", ""):
            columns.append(word)
    return m.group(1), columns


def store_migrations(root):
    migrations = _migrations(root)
    rows = []
    for number in sorted(migrations):
        description, statements = migrations[number]
        created, added, triggers = [], [], []
        for s in statements:
            table = _created_tables(s)
            if table:
                created.append(_code(table[0]))
            m = re.match(r"\s*ALTER TABLE\s+(\w+)\s+ADD COLUMN\s+(\w+)", s)
            if m:
                added.append(_code(f"{m.group(1)}.{m.group(2)}"))
            m = re.match(r"\s*CREATE TRIGGER\s+(\w+)", s)
            if m:
                triggers.append(_code(m.group(1)))
        rows.append([str(number), description, ", ".join(created) or NONE, ", ".join(added) or NONE,
                     ", ".join(triggers) or NONE])
    head = f"Schema version {max(migrations)}: the highest migration of `MIGRATIONS`.\n\n"
    return head + _table(["Migration", "Description", "Tables created", "Columns added", "Triggers"], rows)


def task_runtime_tables(root):
    migrations = _migrations(root)
    tables, order = {}, []
    for number in sorted(migrations):
        for s in migrations[number][1]:
            table = _created_tables(s)
            if table and number >= 2:
                tables[table[0]] = (number, list(table[1]))
                order.append(table[0])
            m = re.match(r"\s*ALTER TABLE\s+(\w+)\s+ADD COLUMN\s+(\w+)", s)
            if m and m.group(1) in tables:
                tables[m.group(1)][1].append(f"{m.group(2)} (migration {number})")
    rows = [[_code(name), str(tables[name][0]), ", ".join(tables[name][1])] for name in order]
    return _table(["Table", "Created by migration", "Columns"], rows)


def _shape(key, value):
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _code(value) if SHOWN_TEXT_KEYS.search(key) else "text, not shown"
    if isinstance(value, dict):
        if value and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value.values()):
            return ", ".join(f"{_code(k)}: {v}" for k, v in value.items())
        return f"{len(value)} keys: " + ", ".join(_code(k) for k in value)
    if isinstance(value, list):
        if value and all(isinstance(v, str) for v in value):
            return f"{len(value)} name{'s' if len(value) != 1 else ''}, not shown"
        keys = []
        for item in value:
            if isinstance(item, dict):
                keys += [k for k in item if k not in keys]
        return f"{len(value)} entr{'ies' if len(value) != 1 else 'y'}" + (f", each with {', '.join(_code(k) for k in keys)}" if keys else "")
    return type(value).__name__


def gate_keys(root):
    try:
        gate = json.loads(_read(root, "evals/eval-gate.json"))
    except ValueError as e:
        raise SourceError(f"evals/eval-gate.json: {e}") from None
    head = (f"Measurement version {gate.get('measurement_version', NONE)}, measurement floor "
            f"{gate.get('measurement_floor', NONE)}.\n\n")
    rows = [[_code(k), _shape(k, v)] for k, v in gate.items()]
    return head + _table(["Key", "Value, or its shape"], rows)


def _files(root, folder, suffix):
    """The files of one folder of the tree with the suffix, as sorted repository-relative paths with forward slashes
    (never an __init__.py); a SourceError when there is none, so that a missing folder is named and not shown as an
    empty table. The folder is listed, not matched with a pattern, so that the layer-map scan, which reads a string
    that is a path to a script as a dependency, sees no arrow to each file of runtime/: a documentation table that
    reads the docstring of every module depends on none of them."""
    try:
        names = sorted(n for n in os.listdir(os.path.join(root, folder)) if n.endswith(suffix) and n != "__init__" + suffix)
    except OSError as e:
        raise SourceError(f"{folder}: {e.strerror}") from None
    if not names:
        raise SourceError(f"{folder}: no {suffix} file")
    return [f"{folder}/{n}" for n in names]


def runtime_modules(root):
    """One row per module of runtime/ and of runtime/handlers/: the first sentence of its docstring."""
    rows = []
    for rel in _files(root, "runtime", ".py") + _files(root, "runtime/handlers", ".py"):
        sentence = _first_sentence(ast.get_docstring(_tree(root, rel))) or NONE
        # a docstring names paths like flows/<name>.json: written as text, `<name>` would be read as a tag and vanish
        rows.append([_code(rel), sentence.replace("<", "&lt;").replace(">", "&gt;")])
    return _table(["Module", "What it is (first sentence of its docstring)"], rows)


def _argument(node, where, limit=False):
    """The value of one argument of a _route call, which must be a literal; only `query_max` may be the name of a
    limit constant, and then the table shows that a limit applies, not its value."""
    try:
        return ast.literal_eval(node)
    except ValueError:
        if limit and isinstance(node, ast.Name):
            return node.id
        raise SourceError(f"{where}: an argument of a _route call is not a constant") from None


def _routes(root):
    tree = _tree(root, "runtime/service.py")
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ROUTES" for t in node.targets):
            if not isinstance(node.value, (ast.Tuple, ast.List)):
                raise SourceError("runtime/service.py: ROUTES is not a tuple of _route calls")
            routes = []
            for call in node.value.elts:
                if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_route"):
                    raise SourceError("runtime/service.py: ROUTES holds something other than a _route call")
                where = f"runtime/service.py:{call.lineno}"
                args = [_argument(a, where) for a in call.args]
                if len(args) < 2 or not all(isinstance(a, str) for a in args):
                    raise SourceError(f"{where}: a _route call needs a method, a pattern and, if any, an operation as text")
                route = {"method": args[0], "pattern": args[1], "op": args[2] if len(args) > 2 else None,
                         "bind": {}, "take": None, "hidden": (), "own": None, "upload": False, "query_max": None,
                         "raw": False}
                for kw in call.keywords:
                    if kw.arg not in route:
                        raise SourceError(f"{where}: unknown argument {kw.arg!r} of a _route call")
                    route[kw.arg] = _argument(kw.value, where, limit=kw.arg == "query_max")
                routes.append(route)
            if not routes:
                raise SourceError("runtime/service.py: ROUTES is empty")
            return routes
    raise SourceError("runtime/service.py: no ROUTES")


def _names(values):
    return ", ".join(_code(v) for v in values) or NONE


def service_routes(root):
    rows = []
    for r in _routes(root):
        if r["own"]:
            rows.append([r["method"], _code(r["pattern"]), f"the service's own {_code(r['own'])}", NONE, NONE, NONE, NONE])
            continue
        bound = ", ".join(f"{_code(arg)} from {_code('{' + part + '}')}" for arg, part in r["bind"].items())
        take = "every other argument" if r["take"] is None else ("none" if not r["take"] else _names(r["take"]))
        special = [text for on, text in ((r["upload"], "file upload"), (r["query_max"] is not None, "query value capped"),
                                      (r["raw"], "answers bytes")) if on]
        rows.append([r["method"], _code(r["pattern"]), _code(r["op"]), bound or NONE, take, _names(r["hidden"]),
                     ", ".join(special) or NONE])
    return _table(["Method", "Path", "Operation", "Bound from the path", "Body or query may carry",
                   "Hidden (the service supplies)", "Special"], rows)


def _handler_verbs(root, rel):
    """The words of a handler's VERBS constant, as runtime/ops.py reads them; () when the file has none."""
    for node in _tree(root, rel).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "VERBS" for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return ()
            if isinstance(value, (tuple, list)) and all(isinstance(v, str) for v in value):
                return tuple(value)
    return ()


def handlers(root):
    rows = []
    for rel in _files(root, "runtime/handlers", ".py"):
        stem = os.path.basename(rel)[:-3]
        rows.append([_code(stem.replace("_", "-")), _code(rel), _names(_handler_verbs(root, rel))])
    return _table(["Handler", "File", "Verbs"], rows)


def _price_keys(tree, where):
    """PRICE_KEYS, an expression `tuple(f"{kind}<suffix>" for kind in PRICE_KINDS) + (<names>)`: computed here from
    PRICE_KINDS, and refused when the expression has another form."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PRICE_KEYS" for t in node.targets):
            value, kinds = node.value, _constant(tree, "PRICE_KINDS")
            try:
                gen = value.left.args[0]
                part = gen.elt.values
                var = gen.generators[0].target.id
                if not (isinstance(value.op, ast.Add) and value.left.func.id == "tuple" and gen.generators[0].iter.id == "PRICE_KINDS"
                        and isinstance(part[0], ast.FormattedValue) and part[0].value.id == var
                        and all(isinstance(p, ast.Constant) for p in part[1:]) and isinstance(kinds, tuple)):
                    raise AttributeError
                suffix = "".join(p.value for p in part[1:])
                return [f"{kind}{suffix}" for kind in kinds] + list(ast.literal_eval(value.right))
            except (AttributeError, IndexError, ValueError):
                raise SourceError(f"{where}: PRICE_KEYS is not tuple(f\"{{kind}}...\" for kind in PRICE_KINDS) + (...)") from None
    raise SourceError(f"{where}: no PRICE_KEYS")


# (constant, source, what the keys are keys of): the closed lists a configuration is checked against.
CONFIG_LISTS = (
    ("REQUIRED", "runtime/project_config.py", "the top level of `runtime.json`, required"),
    ("TASK_RUNTIME_KEYS", "runtime/project_config.py", "the top level, read by the task runtime"),
    ("FIRST_RUNTIME_KEYS", "runtime/project_config.py", "the top level, read by the first runtime"),
    ("CODE_KEYS", "runtime/project_config.py", "the `code` object"),
    ("PRICE_KEYS", "runtime/project_config.py", "an entry of `model_prices`, which is keyed by model id"),
    ("AGENT_KEYS", "runtime/autonomy.py", "an entry of `area_agents`"),
    ("BOUNDS_KEYS", "runtime/autonomy.py", "a standing-approval policy: a `.json` file under `docs/`, checked whole"),
    ("ENTRY_KEYS", "runtime/deps.py", "an entry of `dependencies`"),
    ("RECIPES", "runtime/deps.py", "the closed table of recipes: the names an entry's `recipe` may take"),
)


def config_keys(root):
    """The names of the closed key lists of the configuration. Only names of constants of the source are read: no
    configuration is opened, so no value of one can reach the table."""
    trees, rows = {}, []
    for constant, source, meaning in CONFIG_LISTS:
        tree = trees.setdefault(source, _tree(root, source))
        if constant == "PRICE_KEYS":
            names = _price_keys(tree, source)
        else:
            value = _constant(tree, constant)
            names = list(value) if isinstance(value, (tuple, list, dict)) else None
            if not names or not all(isinstance(n, str) for n in names):
                raise SourceError(f"{source}: {constant} is not a literal tuple of names")
        rows.append([meaning, f"{_code(constant)} of {_code(source)}", _names(names)])
    return _table(["Keys of", "Constant", "Names"], rows)


def flow_files(root):
    rows = []
    for rel in _files(root, "flows", ".json"):
        try:
            flow = json.loads(_read(root, rel))
            tasks = ", ".join(f"{_code(t['key'])} ({_code(t['skill'])})" for t in flow["tasks"])
            rows.append([_code(flow["flow"]), flow["title"], tasks or NONE])
        except (ValueError, KeyError, TypeError) as e:
            raise SourceError(f"{rel}: not a flow file ({type(e).__name__}: {e})") from None
    return _table(["Flow", "Title", "Tasks, in order (key and skill)"], rows)


def roles(root):
    try:
        data = json.loads(_read(root, "runtime/roles.json"))
    except ValueError as e:
        raise SourceError(f"runtime/roles.json: {e}") from None
    rows = []
    for key, value in data.items() if isinstance(data, dict) else ():
        names = [value] if isinstance(value, str) else value
        if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
            raise SourceError(f"runtime/roles.json: {key} is neither a name nor a list of names")
        rows.append([_code(key), _names(names)])
    if not rows:
        raise SourceError("runtime/roles.json: no keys")
    return _table(["Key", "Value"], rows)


def held_reasons(root):
    """REASONS of runtime/dispatcher.py: a tuple of text literals and of names of the module's own text constants."""
    tree = _tree(root, "runtime/dispatcher.py")
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "REASONS" for t in node.targets):
            if not isinstance(node.value, (ast.Tuple, ast.List)):
                raise SourceError("runtime/dispatcher.py: REASONS is not a tuple")
            rows = []
            for item in node.value.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    rows.append([_code(item.value), NONE])
                    continue
                word = _constant(tree, item.id) if isinstance(item, ast.Name) else None
                if not isinstance(word, str):
                    raise SourceError(f"runtime/dispatcher.py: a word of REASONS is not text or the name of a text constant "
                                      f"({ast.unparse(item)})")
                rows.append([_code(word), _code(item.id)])
            return _table(["Word", "Constant that names it"], rows)
    raise SourceError("runtime/dispatcher.py: no REASONS")


TABLES = {
    "artifacts-by-owner": artifacts_by_owner,
    "provider-classes": provider_classes,
    "limits": limits,
    "operations": operations,
    "cli-verbs": cli_verbs,
    "say-commands": say_commands,
    "dispatcher-jobs": dispatcher_jobs,
    "store-migrations": store_migrations,
    "task-runtime-tables": task_runtime_tables,
    "gate-keys": gate_keys,
    "runtime-modules": runtime_modules,
    "service-routes": service_routes,
    "handlers": handlers,
    "config-keys": config_keys,
    "flow-files": flow_files,
    "roles": roles,
    "held-reasons": held_reasons,
}


# --- the blocks ----------------------------------------------------------------------------------------------------

def pages(root=ROOT):
    """The Markdown files of the platform pages, relative to root; [] when the folder is not in the tree."""
    folder = os.path.join(root, PAGES)
    if not os.path.isdir(folder):
        return []
    return [os.path.join(PAGES, n) for n in sorted(os.listdir(folder)) if n.endswith(".md")]


def _generated(name, root, cache):
    """The table's Markdown, or a SourceError when its name is unknown or its source cannot be read."""
    if name not in TABLES:
        return SourceError("unknown table")
    if name not in cache:
        try:
            cache[name] = TABLES[name](root)
        except (SourceError, OSError, SyntaxError, ValueError) as e:
            cache[name] = SourceError(f"source not readable: {e}")
    return cache[name]


def _blocks(root, cache):
    """[(page, text, [(match, generated)])] for every page of the tree."""
    out = []
    for page in pages(root):
        with open(os.path.join(root, page), encoding="utf-8") as f:
            text = f.read()
        out.append((page, text, [(m, _generated(m.group(2), root, cache)) for m in BLOCK_RE.finditer(text)]))
    return out


def stale_blocks(root=ROOT):
    """[(page, table, problem)] for every block that differs from its source, is unknown or cannot be generated."""
    out = []
    for page, _, blocks in _blocks(root, {}):
        for m, generated in blocks:
            if isinstance(generated, SourceError):
                out.append((page, m.group(2), str(generated)))
            elif m.group(3) != generated:
                out.append((page, m.group(2), "differs from its source"))
    return out


def write(root=ROOT):
    """Rewrite every block; [(page, table, problem)] for the blocks that could not be generated, kept as they are."""
    out = []
    for page, text, blocks in _blocks(root, {}):
        new, end = "", 0
        for m, generated in blocks:
            if isinstance(generated, SourceError):
                out.append((page, m.group(2), str(generated)))
                continue
            new += text[end:m.start(3)] + generated
            end = m.end(3)
        new += text[end:]
        if new != text:
            with open(os.path.join(root, page), "w", encoding="utf-8") as f:
                f.write(new)
    return out


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__.strip())
        return 0
    root, mode, table, i = ROOT, None, None, 0
    while i < len(argv):
        a = argv[i]
        if a in ("--root", "--print"):
            if i + 1 >= len(argv):
                print(f"error: {a} needs a value. See --help.", file=sys.stderr)
                return 2
            if a == "--root":
                root = os.path.abspath(argv[i + 1])
            else:
                if mode is not None:
                    print("error: give one of --write, --check and --print. See --help.", file=sys.stderr)
                    return 2
                mode, table = "print", argv[i + 1]
            i += 2
            continue
        if a not in ("--write", "--check"):
            print(f"error: unknown option {a!r}. See --help.", file=sys.stderr)
            return 2
        if mode is not None:
            print("error: give one of --write, --check and --print. See --help.", file=sys.stderr)
            return 2
        mode, i = a[2:], i + 1
    if mode is None:
        print("error: give one of --write, --check and --print. See --help.", file=sys.stderr)
        return 2
    if mode == "print":
        if table not in TABLES:
            print(f"error: unknown table {table!r}; known: {', '.join(TABLES)}.", file=sys.stderr)
            return 2
        try:
            print(TABLES[table](root), end="")
        except SourceError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0
    if not pages(root):
        print(f"error: {PAGES} is not in {root}.", file=sys.stderr)
        return 2
    if mode == "check":
        stale = stale_blocks(root)
        for page, name, problem in stale:
            print(f"{page}: generated block {name}: {problem}; run python3 scripts/architecture_tables.py --write",
                  file=sys.stderr)
        broken = [s for s in stale if s[2] != "differs from its source"]
        return 2 if broken else (1 if stale else 0)
    broken = write(root)
    for page, name, problem in broken:
        print(f"{page}: generated block {name}: {problem}", file=sys.stderr)
    return 2 if broken else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
