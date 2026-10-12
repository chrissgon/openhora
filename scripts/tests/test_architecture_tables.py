"""Offline tests of scripts/architecture_tables.py, which generates the volatile tables of the architecture pages
(docs/architecture/platform/), and of the validator's warning rule architecture-tables. One test reads this
repository; the others write a small tree with an invented skill, provider and runtime to a temporary folder.
Nothing calls a model, the network or a provider.

Run: uv run --with pytest pytest scripts/tests/test_architecture_tables.py
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "architecture_tables.py"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tables = load("architecture_tables_under_test", "scripts/architecture_tables.py")
validate = load("validate_architecture_under_test", "scripts/validate.py")

SKILL = """---
name: biz-sample
description: Write the sample. Use when a sample is asked for.
license: MIT
metadata:
  area: business
  kind: capability
  inputs: []
  outputs: [docs/business/sample.md]
  updates: [docs/workbench/state.md]
  requires: []
  side_effects: []
  version: "0.1.0"
---
# Sample
"""

CONTRACT = """# Providers

## Verbs per class

| Class | Verb and flags | Prints |
|-------|----------------|--------|
| `integration:widget` | `spin` | `ok` |
| `search:web` | No implementation ships. | nothing |
"""

PROVIDER = '''import argparse
VERBS = {"spin": print, "stop": print}
SWITCHES = ("--dry-run", "--check")
'''

RUNTIME_CONTRACT = """# Runtime

## The limits

| # | Limit | Built by | Test |
|---|---|---|---|
| L1 | A copy is new | stage 2 | anything |
| L2 | A record \\| only grows | stage 4 | anything |
"""

LIMIT_TESTS = """def test_limit_01_a_copy_is_new():
    pass
"""

OPERATIONS_PY = '''"""The table of operations."""
OPERATIONS = (
    {"name": "go", "call": "go",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "id", "label": "id"},
              {"name": "dry_run", "kind": "flag", "flag": "dry-run"}),
     "channels": ("terminal", "chat"), "model": False, "help": "go on with one task"},
    {"name": "status", "call": "status", "args": (), "channels": ("terminal",), "model": "for a new request",
     "help": "where things stand"},
)
CHAT_OWN = (
    {"name": "help", "args": "", "help": "this text", "order": "first"},
    {"name": "new", "args": "text", "help": "start a new request", "order": "last"},
)
'''

DISPATCHER = '''"""The dispatcher.

  /usr/bin/python3 runtime/dispatcher.py tick  --project <dir>   ops.tick: the job
"""
ENTRY_VERBS = ("tick",)
JOBS = {"tick": 7}
NO_AGENT = "no enabled agent"
OTHER = "other"
REASONS = ("stopped", "cap: runs per day", NO_AGENT, OTHER)
'''

SQLITE = '''MIGRATIONS = {
    1: ("the first table", ["CREATE TABLE first (id INTEGER PRIMARY KEY, name TEXT)"]),
    2: ("the task table", [
        """CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            state TEXT CHECK (state IN ('a', 'b')),
            UNIQUE (id, state))""",
        "CREATE TRIGGER jobs_kept BEFORE DELETE ON jobs BEGIN SELECT RAISE(ABORT, 'no'); END",
    ]),
    3: ("a column", ["ALTER TABLE jobs ADD COLUMN note TEXT"]),
}
'''

GATE = {"strong_model": "model-one", "strong_harness": "adapter-one", "threshold": 0.8, "runs": 3,
        "measurement_version": 4, "measurement_floor": 2, "strong_pass_env": ["SOME_VARIABLE_NAME"],
        "free_text": "never-shown-text", "web_jobs": {"strong": 2}, "epochs": [{"date": "x", "cause": "y"}]}

SERVICE = '''"""The local service, for a <name> in flows/<name>.json. A second sentence that is not shown."""
FILE_LIMIT = 100
QUERY_VALUE_LIMIT = 50


def _route(method, pattern, op=None, *, bind=None, take=None, hidden=(), own=None, upload=False, query_max=None):
    return {}


ROUTES = (
    _route("GET", "/projects", own="projects"),
    _route("GET", "/projects/{p}/items/{id}", "item", bind={"item_id": "id"}, take=()),
    _route("POST", "/projects/{p}/items/{id}/files", "hand-over", bind={"item_id": "id"}, hidden=("file",), upload=True),
    _route("GET", "/projects/{p}/artifact", "artifact", take=("path",), query_max=QUERY_VALUE_LIMIT),
    _route("POST", "/projects/{p}/items", "make"),
)
'''

PROJECT_CONFIG = '''"""The configuration of the runtime. Reads the file runtime.json."""
REQUIRED = ("workbench", "data_dir")
TASK_RUNTIME_KEYS = ("workbench", "data_dir", "model_prices")
FIRST_RUNTIME_KEYS = ("agent", "path")
CODE_KEYS = ("provider", "repo")
PRICE_KINDS = ("input", "output")
PRICE_KEYS = tuple(f"{kind}_usd_per_mtok" for kind in PRICE_KINDS) + ("source", "date")
PLANTED = "wb-planted-credential-value"  # a constant that is not a key list: it must never be printed
'''

AUTONOMY = '''"""The modes."""
AGENT_KEYS = ("pack", "enabled")
BOUNDS_KEYS = ("policy", "agent", "files")
'''

DEPS = '''"""The dependencies."""
RECIPES = {
    "node-npm": {"files": ("package.json",), "commands": (("npm", "ci"),)},
    "python-requirements": {"files": None, "commands": (("pip", "install"),)},
}
ENTRY_KEYS = ("recipe", "file")
'''

HANDLER_WITH_VERBS = '''"""A routine that lists things. More text."""
VERBS = ("tick", "preview")
'''

HANDLER_WITHOUT_VERBS = '''"""A step imported by a script, with no verbs of its own."""
'''

ROLES = {"router": "role-router", "brief": "role-brief", "code_areas": ["engineering", "delivery"],
         "packs_in_use": ["business", "code"]}

FLOW_ONE = {"flow": "one", "title": "The first flow", "tasks": [
    {"key": "make", "skill": "biz-sample", "title": "Make it", "text": "x", "depends_on": [], "milestone": False},
    {"key": "ship", "skill": "ops-ship", "title": "Ship it", "text": "x", "depends_on": ["make"], "milestone": True}]}
FLOW_TWO = {"flow": "two", "title": "The second flow", "tasks": [
    {"key": "only", "skill": "biz-sample", "title": "Only", "text": "x", "depends_on": [], "milestone": False}]}

# A configuration of a project, which no table may read: its keys and values stay out of every output.
PLANTED_CONFIGURATION = json.dumps({"workbench": "/somewhere", "planted_setting": "wb-planted-credential-value"})

NEW_TABLES = ("runtime-modules", "service-routes", "handlers", "config-keys", "flow-files", "roles", "held-reasons")

PAGE = "".join(f"# {name}\n\nProse kept.\n\n<!-- generated: {name} -->\nstale\n<!-- /generated -->\n\nMore prose.\n\n"
               for name in tables.TABLES)


def fixture(tmp_path):
    root = tmp_path / "wb"
    files = {
        "skills/biz-sample/SKILL.md": SKILL,
        "providers/CONTRACT.md": CONTRACT,
        "providers/widget/fake.py": PROVIDER,
        "providers/widget/auth.py": "VERBS = {'login': print}\n",
        "contracts/runtime.md": RUNTIME_CONTRACT,
        "runtime/tests/test_limits.py": LIMIT_TESTS,
        "runtime/operations.py": OPERATIONS_PY,
        "runtime/dispatcher.py": DISPATCHER,
        "providers/store/sqlite.py": SQLITE,
        "evals/eval-gate.json": json.dumps(GATE),
        "runtime/service.py": SERVICE,
        "runtime/project_config.py": PROJECT_CONFIG,
        "runtime/autonomy.py": AUTONOMY,
        "runtime/deps.py": DEPS,
        "runtime/notes.py": "# a module with no docstring\nX = 1\n",
        "runtime/handlers/lister.py": HANDLER_WITH_VERBS,
        "runtime/handlers/two_part_step.py": HANDLER_WITHOUT_VERBS,
        "runtime/roles.json": json.dumps(ROLES),
        "flows/one.json": json.dumps(FLOW_ONE),
        "flows/two.json": json.dumps(FLOW_TWO),
        "docs/workbench/runtime.json": PLANTED_CONFIGURATION,
        "docs/architecture/platform/page.md": PAGE,
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    shutil.copy(REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    return root


def block(root, name):
    text = (root / "docs/architecture/platform/page.md").read_text(encoding="utf-8")
    return text.split(f"<!-- generated: {name} -->\n", 1)[1].split("<!-- /generated -->", 1)[0]


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


def test_the_blocks_of_this_repository_are_current():
    assert tables.stale_blocks(str(REPO)) == []
    named = set()
    for page in tables.pages(str(REPO)):
        named |= {m.group(2) for m in tables.BLOCK_RE.finditer((REPO / page).read_text(encoding="utf-8"))}
    assert named == set(tables.TABLES), "every table is used by a page, and a page names only known tables"


def test_check_names_each_stale_block_and_write_makes_them_current(tmp_path):
    root = fixture(tmp_path)
    checked = run("--check", "--root", str(root))
    assert checked.returncode == 1 and checked.stdout == ""
    assert checked.stderr.count("differs from its source") == len(tables.TABLES)
    assert run("--write", "--root", str(root)).returncode == 0
    assert run("--check", "--root", str(root)).returncode == 0
    text = (root / "docs/architecture/platform/page.md").read_text(encoding="utf-8")
    assert "stale" not in text and text.count("Prose kept.") == len(tables.TABLES)


def test_the_tables_have_their_shape(tmp_path):
    root = fixture(tmp_path)
    run("--write", "--root", str(root))
    assert "| `docs/business/sample.md` | biz-sample | - |" in block(root, "artifacts-by-owner")
    assert "| `docs/workbench/state.md` | - | biz-sample |" in block(root, "artifacts-by-owner")
    classes = block(root, "provider-classes")
    assert "| `integration:widget` | `widget/` | `fake.py` | `--check`, `spin`, `stop` |" in classes
    assert "auth.py" not in classes and "| `search:web` | `search/` | none ships | - |" in classes
    limits = block(root, "limits")
    assert "| L1 | A copy is new | stage 2 | `runtime/tests/test_limits.py`, `test_limit_01_a_copy_is_new` |" in limits
    assert "| L2 | A record \\| only grows | stage 4 | no test named |" in limits
    ops = block(root, "operations")
    assert "| `go` | `go` | terminal, chat | no | go on with one task |" in ops
    assert "| `status` | `status` | terminal | yes, for a new request | where things stand |" in ops
    assert "| `go` | `--id` `[--dry-run]` | `go` |" in block(root, "cli-verbs")
    assert "| `status` | - | `status` |" in block(root, "cli-verbs")
    commands = block(root, "say-commands")
    assert "| `/go <id>` | go on with one task |" in commands and "`/status`" not in commands
    assert commands.index("`/help`") < commands.index("`/go <id>`") < commands.index("`/new <text>`")
    assert "| `tick` | `--project <dir>` | ops.tick: the job | 7 minutes |" in block(root, "dispatcher-jobs")
    migrations = block(root, "store-migrations")
    assert migrations.startswith("Schema version 3:")
    assert "| 2 | the task table | `jobs` | - | `jobs_kept` |" in migrations
    assert "| 3 | a column | - | `jobs.note` | - |" in migrations
    runtime_tables = block(root, "task-runtime-tables")
    assert "| `jobs` | 2 | id, state, note (migration 3) |" in runtime_tables and "`first`" not in runtime_tables
    for name, header in (("runtime-modules", "| Module | What it is (first sentence of its docstring) |"),
                         ("service-routes", "| Method | Path | Operation | Bound from the path | Body or query may carry | "
                                            "Hidden (the service supplies) | Special |"),
                         ("handlers", "| Handler | File | Verbs |"),
                         ("config-keys", "| Keys of | Constant | Names |"),
                         ("flow-files", "| Flow | Title | Tasks, in order (key and skill) |"),
                         ("roles", "| Key | Value |"),
                         ("held-reasons", "| Word | Constant that names it |")):
        assert block(root, name).startswith(header + "\n|---|"), name


def test_the_gate_keys_show_names_and_never_a_text_that_could_be_a_credential(tmp_path):
    root = fixture(tmp_path)
    gate = tables.gate_keys(str(root))
    assert gate.startswith("Measurement version 4, measurement floor 2.")
    assert "| `strong_model` | `model-one` |" in gate and "| `threshold` | 0.8 |" in gate
    assert "| `strong_pass_env` | 1 name, not shown |" in gate and "SOME_VARIABLE_NAME" not in gate
    assert "| `free_text` | text, not shown |" in gate and "never-shown-text" not in gate
    assert "| `epochs` | 1 entry, each with `date`, `cause` |" in gate


def test_an_unknown_table_or_a_missing_source_is_named_and_the_block_kept(tmp_path):
    root = fixture(tmp_path)
    page = root / "docs/architecture/platform/other.md"
    page.write_text("<!-- generated: no-such-table -->\nkept\n<!-- /generated -->\n", encoding="utf-8")
    (root / "runtime" / "dispatcher.py").unlink()
    written = run("--write", "--root", str(root))
    assert written.returncode == 2
    assert "no-such-table: unknown table" in written.stderr and "dispatcher-jobs: source not readable" in written.stderr
    assert "kept" in page.read_text(encoding="utf-8") and block(root, "dispatcher-jobs") == "stale\n"
    assert block(root, "limits") != "stale\n"


def test_usage_errors_exit_2_on_stderr(tmp_path):
    for args in ([], ["--write", "--check"], ["--print"], ["--print", "nothing"], ["--no-such-flag"]):
        done = run(*args)
        assert done.returncode == 2 and done.stdout == "" and "error" in done.stderr, args
    helped = run("--help")
    assert helped.returncode == 0
    assert all(f"\n  {name} " in helped.stdout for name in tables.TABLES), "--help names every table, one line each"
    assert run("--check", "--root", str(tmp_path)).returncode == 2  # no pages in that tree


def test_the_validator_warns_on_a_stale_block_and_notes_a_tree_without_the_pages(tmp_path):
    root = fixture(tmp_path)
    (root / "scripts").mkdir()
    shutil.copy(SCRIPT, root / "scripts" / "architecture_tables.py")
    shutil.copy(REPO / "scripts" / "owner_table.py", root / "scripts" / "owner_table.py")
    shutil.copy(REPO / "scripts" / "validate.py", root / "scripts" / "validate.py")
    report = validate.Report()
    validate.check_architecture_tables(report, root=str(root))
    assert report.errors == [] and len(report.warnings) == len(tables.TABLES)
    assert all(w["rule"] == "architecture-tables" and "--write" in w["message"] for w in report.warnings)
    run("--write", "--root", str(root))
    report = validate.Report()
    validate.check_architecture_tables(report, root=str(root))
    assert report.warnings == [] and report.errors == []
    report = validate.Report()
    validate.check_architecture_tables(report, root=str(tmp_path / "empty"))
    assert report.warnings == [] and report.notes and "[architecture-tables] skipped" in report.notes[0]


# --- the seven tables of WP-D.1: one test each, on the fixture ------------------------------------------------------

def printed(root, name):
    done = run("--print", name, "--root", str(root))
    assert done.returncode == 0 and done.stderr == "", (name, done.stderr)
    return done.stdout


def test_runtime_modules_gives_the_first_sentence_of_each_docstring(tmp_path):
    out = printed(fixture(tmp_path), "runtime-modules")
    assert "| `runtime/autonomy.py` | The modes. |" in out
    assert "| `runtime/dispatcher.py` | The dispatcher. |" in out
    assert "| `runtime/service.py` | The local service, for a &lt;name&gt; in flows/&lt;name&gt;.json. |" in out
    assert "second sentence" not in out and "<name>" not in out, "no angle bracket is left to be read as a tag"
    assert "| `runtime/notes.py` | - |" in out  # no docstring: a dash, not an error
    assert "| `runtime/handlers/lister.py` | A routine that lists things. |" in out
    assert "tests" not in out and "test_limits" not in out
    paths = [line.split("`")[1] for line in out.splitlines()[2:]]
    assert paths == sorted(p for p in paths if "/handlers/" not in p) + sorted(p for p in paths if "/handlers/" in p)


def test_the_module_table_of_this_repository_lists_every_runtime_module():
    out = tables.TABLES["runtime-modules"](str(REPO))
    listed = {line.split("`")[1] for line in out.splitlines()[2:]}
    on_disk = {p.relative_to(REPO).as_posix() for pattern in ("runtime/*.py", "runtime/handlers/*.py")
               for p in REPO.glob(pattern) if p.name != "__init__.py"}
    assert listed == on_disk and "runtime/ops.py" in listed and "runtime/handlers/social.py" in listed


def test_service_routes_reads_the_constant_calls_of_the_routes_tuple(tmp_path):
    out = printed(fixture(tmp_path), "service-routes")
    assert "| GET | `/projects` | the service's own `projects` | - | - | - | - |" in out
    assert "| GET | `/projects/{p}/items/{id}` | `item` | `item_id` from `{id}` | none | - | - |" in out
    assert ("| POST | `/projects/{p}/items/{id}/files` | `hand-over` | `item_id` from `{id}` | every other argument | "
            "`file` | file upload |") in out
    assert "| GET | `/projects/{p}/artifact` | `artifact` | - | `path` | - | query value capped |" in out
    assert "| POST | `/projects/{p}/items` | `make` | - | every other argument | - | - |" in out
    assert len(out.splitlines()) == 2 + 5, "one row per route call, in source order"


def test_service_routes_refuses_an_argument_that_is_not_a_constant(tmp_path):
    root = fixture(tmp_path)
    service = root / "runtime" / "service.py"
    service.write_text(service.read_text(encoding="utf-8").replace('"/projects/{p}/items", "make")', '"/projects/{p}/items", operation_from_elsewhere)'),
                       encoding="utf-8")
    done = run("--print", "service-routes", "--root", str(root))
    assert done.returncode == 2 and "runtime/service.py" in done.stderr and "constant" in done.stderr


def test_handlers_shows_the_verbs_and_a_dash_for_a_file_without_them(tmp_path):
    out = printed(fixture(tmp_path), "handlers")
    assert "| `lister` | `runtime/handlers/lister.py` | `tick`, `preview` |" in out
    assert "| `two-part-step` | `runtime/handlers/two_part_step.py` | - |" in out


def test_config_keys_gives_the_names_of_each_closed_list(tmp_path):
    out = printed(fixture(tmp_path), "config-keys")
    assert "`REQUIRED` of `runtime/project_config.py` | `workbench`, `data_dir` |" in out
    assert "`TASK_RUNTIME_KEYS` of `runtime/project_config.py` | `workbench`, `data_dir`, `model_prices` |" in out
    assert "`FIRST_RUNTIME_KEYS` of `runtime/project_config.py` | `agent`, `path` |" in out
    assert "`CODE_KEYS` of `runtime/project_config.py` | `provider`, `repo` |" in out
    assert "`AGENT_KEYS` of `runtime/autonomy.py` | `pack`, `enabled` |" in out
    assert "`BOUNDS_KEYS` of `runtime/autonomy.py` | `policy`, `agent`, `files` |" in out
    assert "`ENTRY_KEYS` of `runtime/deps.py` | `recipe`, `file` |" in out
    assert "`RECIPES` of `runtime/deps.py` | `node-npm`, `python-requirements` |" in out
    # computed from PRICE_KINDS, because the list is an expression and not a literal
    assert ("`PRICE_KEYS` of `runtime/project_config.py` | `input_usd_per_mtok`, `output_usd_per_mtok`, `source`, "
            "`date` |") in out


def test_config_keys_and_every_other_table_print_names_and_never_a_value_of_a_configuration(tmp_path):
    root = fixture(tmp_path)
    for name in tables.TABLES:
        out = tables.TABLES[name](str(root))
        assert "wb-planted-credential-value" not in out, name  # a constant of the source and a value of a configuration
        assert "planted_setting" not in out and "/somewhere" not in out, name
    assert "PLANTED" not in tables.TABLES["config-keys"](str(root)), "only the closed lists are read"


def test_config_keys_refuses_a_price_list_it_cannot_compute(tmp_path):
    root = fixture(tmp_path)
    config = root / "runtime" / "project_config.py"
    config.write_text(config.read_text(encoding="utf-8").replace(
        'PRICE_KEYS = tuple(f"{kind}_usd_per_mtok" for kind in PRICE_KINDS) + ("source", "date")',
        "PRICE_KEYS = compute_it()"), encoding="utf-8")
    done = run("--print", "config-keys", "--root", str(root))
    assert done.returncode == 2 and "PRICE_KEYS" in done.stderr


def test_flow_files_gives_each_flow_with_its_tasks_in_order(tmp_path):
    out = printed(fixture(tmp_path), "flow-files")
    assert "| `one` | The first flow | `make` (`biz-sample`), `ship` (`ops-ship`) |" in out
    assert "| `two` | The second flow | `only` (`biz-sample`) |" in out
    assert out.index("`one`") < out.index("`two`") and "Make it" not in out, "keys and skills only"


def test_roles_gives_each_key_of_the_roles_file_and_its_value(tmp_path):
    out = printed(fixture(tmp_path), "roles")
    assert "| `router` | `role-router` |" in out and "| `brief` | `role-brief` |" in out
    assert "| `code_areas` | `engineering`, `delivery` |" in out
    assert "| `packs_in_use` | `business`, `code` |" in out


def test_held_reasons_resolves_the_names_the_tuple_is_built_from(tmp_path):
    out = printed(fixture(tmp_path), "held-reasons")
    assert "| `stopped` | - |" in out and "| `cap: runs per day` | - |" in out
    assert "| `no enabled agent` | `NO_AGENT` |" in out and "| `other` | `OTHER` |" in out
    assert out.index("`stopped`") < out.index("`no enabled agent`") < out.index("`other`"), "the order of the tuple"


def test_held_reasons_refuses_a_name_the_module_does_not_define_as_text(tmp_path):
    root = fixture(tmp_path)
    dispatcher = root / "runtime" / "dispatcher.py"
    dispatcher.write_text(dispatcher.read_text(encoding="utf-8").replace("NO_AGENT, OTHER)", "UNDEFINED, OTHER)"),
                          encoding="utf-8")
    done = run("--print", "held-reasons", "--root", str(root))
    assert done.returncode == 2 and "UNDEFINED" in done.stderr


def test_a_stale_block_of_each_new_table_is_named_by_check_and_made_current_by_write(tmp_path):
    for name in NEW_TABLES:
        root = fixture(tmp_path / name)
        page = root / "docs/architecture/platform/page.md"
        page.write_text(f"Intro.\n\n<!-- generated: {name} -->\nstale\n<!-- /generated -->\n\nOutro.\n", encoding="utf-8")
        checked = run("--check", "--root", str(root))
        assert checked.returncode == 1 and f"generated block {name}: differs from its source" in checked.stderr, name
        assert run("--write", "--root", str(root)).returncode == 0
        assert run("--check", "--root", str(root)).returncode == 0, name
        text = page.read_text(encoding="utf-8")
        assert text.startswith("Intro.\n\n") and text.endswith("Outro.\n") and "stale" not in text
        assert block(root, name) == tables.TABLES[name](str(root)), name


SOURCES_OF = {  # the files a table reads: removing one must name it, exit 2, and keep the block as it was
    "runtime-modules": ("runtime",),
    "service-routes": ("runtime/service.py",),
    "handlers": ("runtime/handlers",),
    "config-keys": ("runtime/project_config.py", "runtime/autonomy.py", "runtime/deps.py"),
    "flow-files": ("flows",),
    "roles": ("runtime/roles.json",),
    "held-reasons": ("runtime/dispatcher.py",),
}


def test_a_missing_source_of_a_new_table_is_named_with_exit_2(tmp_path):
    assert set(SOURCES_OF) == set(NEW_TABLES)
    for name, sources in SOURCES_OF.items():
        for source in sources:
            root = fixture(tmp_path / f"{name}-{source.replace('/', '_')}")
            target = root / source
            shutil.rmtree(target) if target.is_dir() else target.unlink()
            page = root / "docs/architecture/platform/other.md"
            page.write_text(f"<!-- generated: {name} -->\nkept\n<!-- /generated -->\n", encoding="utf-8")
            printed_err = run("--print", name, "--root", str(root))
            assert printed_err.returncode == 2 and printed_err.stdout == "" and "error" in printed_err.stderr, (name, source)
            written = run("--write", "--root", str(root))
            assert written.returncode == 2, (name, source)
            assert f"generated block {name}: source not readable" in written.stderr, (name, source)
            assert "kept" in page.read_text(encoding="utf-8")
            assert run("--check", "--root", str(root)).returncode == 2, (name, source)
