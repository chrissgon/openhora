#!/usr/bin/env python3
"""Print the tests that a change can reach, one pytest target per line (a test file, or a whole test folder).

The repository standard (docs/decisions.md, 2026-10-20): during development only the SELECTED tests run (every commit, every
pull request into an integration branch); the whole suite runs at the end of a large delivery (a pull request into main, a push to
main, a manual run, a pull request labelled `full-suite`). The pre-commit hook and the `tests` job of .github/workflows/checks.yml
call this script.

Usage:
  python3 scripts/select_tests.py --files <path>...          # exactly these changed files (paths from the repository root)
  git diff --cached --name-only -z | python3 scripts/select_tests.py --files-from -     # NUL-separated names, from a file or stdin
  python3 scripts/select_tests.py --base origin/main         # git diff --name-only <merge-base of the ref and HEAD>, plus the working tree
  python3 scripts/select_tests.py                            # the working tree against HEAD
  add --explain to print, on stderr, why each target was chosen; --root <dir> reads another tree (the tests of this script use it)

Data goes to stdout (one target per line, sorted, repository-relative); diagnostics and --explain go to stderr. Nothing to run still
prints the fixed guards (rule 6), so the output is never empty.

THE RULES (conservative: when the selector is unsure it selects more)
 1. A changed test file (test_*.py) selects itself (when it still exists).
 2. A changed Python module selects every test file that references it: an `import x`, a `from x import y`, or a string that
    names it in a call that loads a module (`importlib.import_module("x")`, `st.load("x")`, `_load("x")`, `sys.modules["x"]`),
    or a string that names its file (`"x.py"`); and every test file named `test_<module stem>.py` or starting with `test_<module stem>_`. The reach goes one
    step to every module that references the changed one (its importers, kits included) and then on only through `from M import ...`
    at a module's top level, which is how a module re-exports another's names (ops.py re-exports the functions of its siblings).
    A module that only calls the changed one through `import M` two steps away is NOT reached: that is the accepted slip (rule 8
    of SPEC-TESTSEL), caught by the whole-suite run at the end of a delivery.
 3. A script run by path (`scripts/x.py`, `providers/**/x.py`, `skills/*/scripts/x.py`, `runtime/x.py`) also selects every test file
    that names its file in a string (it runs it as a subprocess or loads it from a path): the `"x.py"` reference of rule 2.
 4. A changed data file (json, jsonl, txt, md, html, js, css, sh, ... under runtime/, providers/, evals/, scripts/, shared/, contracts/,
    docs/architecture/, flows/, interface/, adapters/, site/, and the files at the root) selects every test file that names it (its
    file name or its path in a string) and every test of a module that names it (the module that reads it); under interface/ and flows/
    also the tests that name that folder. contracts/*.md, docs/architecture/** and AGENTS.md also run the documentation guards, which
    are always run (rule 6).
 5. Whole-folder fallbacks: a conftest.py, pytest.ini, pyproject.toml, a test kit (a module that is not a test inside a tests/ folder),
    a module or data file that nothing references (the graph cannot resolve it) and a file that does not parse select the whole test
    folder that owns it; a change to this script, to scripts/test_slots.py, .githooks/**, .github/**, packs/, templates/ or agents/
    selects scripts/tests; a root conftest.py, pytest.ini or pyproject.toml selects every test folder.
 6. The guards (GUARDS below) always run: the validator and the security scan, the layer map, the runtime rules, the Python 3.9
    script check, the architecture tables, the wiring of the hook and of CI, the test isolation and this script's own tests.
 7. A change inside skills/<name>/ other than scripts/ selects nothing beyond the guards (the lab measures skills, the validator
    checks them); skills/*/evals/runtime-manifest.json is the one data file of a skill that the runtime reads, so it follows rule 4.
 8. Fuzz files run in their default sampled mode; only the whole-suite job sets WB_FULL_FUZZ=1.
A shared script, its generated copies and the identity tests of the copies (scripts/tests/test_script_copies.py, test_sync_copies.py)
go together: a change to either selects the others' tests.

Python 3.9 compatible; standard library only; nothing is run, only read.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)

# Rule 6: fast, listed literally. A name that stops existing is a test failure (test_select_tests.py), never a silent drop.
GUARDS = (
    "scripts/tests/test_validate_agent_invokes.py",
    "scripts/tests/test_validate_contract.py",
    "scripts/tests/test_validate_flows.py",
    "scripts/tests/test_validate_foreign.py",
    "scripts/tests/test_validate_private_terms.py",
    "scripts/tests/test_validate_rules.py",
    "scripts/tests/test_security_scan.py",
    "scripts/tests/test_layer_map.py",
    "runtime/tests/test_runtime_rules.py",
    "scripts/tests/test_runtime_python39.py",
    "scripts/tests/test_architecture_tables.py",
    "scripts/tests/test_checks_wiring.py",
    "scripts/tests/test_hook_parallel.py",
    "scripts/tests/test_test_isolation.py",
    "scripts/tests/test_select_tests.py",
)

# The two tests that read the manifest of generated copies (shared/scripts/copies.json).
COPY_IDENTITY_TESTS = ("scripts/tests/test_script_copies.py", "scripts/tests/test_sync_copies.py")
# The tests of the wiring that a change to the hook, the workflows or this selector can break (rule 5).
WIRING_FOLDER = "scripts/tests"
# Files whose change selects scripts/tests whole (rule 5): the selector and the slot helper are the hook's own machinery.
WIRING_FILES = ("scripts/select_tests.py", "scripts/test_slots.py")
WIRING_DIRS = (".githooks/", ".github/", "packs/", "templates/", "agents/")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".workbench-local", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
# Areas whose non-Python files can be named by a test (rule 4). The files at the root (AGENTS.md, README.md) are not: they
# are read by the validator and its guards, and naming them would select most of the suite for every edit of a document.
NAME_AREAS = ("runtime/", "providers/", "evals/", "scripts/", "shared/", "contracts/", "docs/architecture/", "flows/", "interface/",
              "adapters/", "site/")
# For these the tests that name the folder (a glob over it) also count.
FOLDER_MENTION = {"interface": "interface", "flows": "flows"}
LOADERS = ("load", "import", "module", "script")
PY_NAME = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_.-]*)\.py\b")


def posix(path):
    return path.replace(os.sep, "/")


def load_test_dirs(root):
    """The folders the repository's own tests live in (scripts/test_dirs.py is the one definition CI uses)."""
    spec = importlib.util.spec_from_file_location("test_dirs_for_select_tests", os.path.join(HERE, "test_dirs.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [posix(d) for d in module.test_dirs(root)]


class Info:
    """What one Python file says about the files it references."""

    __slots__ = ("tokens", "from_tokens", "consts", "blob", "code_blob")

    def __init__(self, tokens, from_tokens, consts, code_consts):
        self.tokens = tokens
        self.from_tokens = from_tokens
        self.consts = consts
        self.blob = "\n".join(consts)  # every string, docstrings included: a test that names a file in any way is selected
        # What a module reads is a short string without whitespace outside its docstrings (a path or a file name); its prose (messages, documentation of the
        # module) says "see runtime/README.md" without reading it, and would pull the whole graph in for every edit of a document.
        self.code_blob = "\n".join(code_consts)


def _name_of(func):
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _strings_in(node):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub.value


def _add_name_tokens(tokens, text):
    """A module name, a dotted name or a path: every part, the last one without `.py`, is a token."""
    if not text or len(text) > 300 or "\n" in text:
        return
    last = text.replace("\\", "/").split("/")[-1]
    if last.endswith(".py"):
        last = last[:-3]
    tokens.add(last)
    for part in last.split("."):
        if part:
            tokens.add(part)


def _is_modules(node):
    return isinstance(node, ast.Attribute) and node.attr == "modules"


def _top_level_from_imports(body, out):
    """The names a module re-exports: the `from M import ...` statements outside any function or class."""
    for stmt in body:
        if isinstance(stmt, ast.ImportFrom):
            if stmt.module:
                out.update(p for p in stmt.module.split(".") if p)
            out.update(a.name for a in stmt.names)
        elif isinstance(stmt, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for field in ("body", "orelse", "finalbody", "handlers"):
                inner = getattr(stmt, field, None) or []
                for item in inner:
                    if isinstance(item, ast.ExceptHandler):
                        _top_level_from_imports(item.body, out)
                    else:
                        _top_level_from_imports([item], out)


def scan_source(text):
    """Parse a file; None when it does not parse (the caller then selects its whole folder)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    tokens, consts, code_consts = set(), [], []
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tokens.update(p for p in alias.name.split(".") if p)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                tokens.update(p for p in node.module.split(".") if p)
            tokens.update(a.name for a in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            consts.append(node.value)
            if id(node) not in docstrings and len(node.value) <= 160 and not re.search(r"\s", node.value):
                code_consts.append(node.value)
            for stem in PY_NAME.findall(node.value):
                _add_name_tokens(tokens, stem)
        if isinstance(node, ast.Call):
            name = _name_of(node.func).lower()
            args = list(node.args) + [k.value for k in node.keywords]
            loads = any(w in name for w in LOADERS) or name == "__import__"
            via_modules = (name in ("get", "pop", "setdefault") and isinstance(node.func, ast.Attribute) and _is_modules(node.func.value)) \
                or any(_is_modules(a) for a in args)
            if loads or via_modules:
                for arg in args:
                    for value in _strings_in(arg):
                        _add_name_tokens(tokens, value)
        elif isinstance(node, ast.Subscript) and _is_modules(node.value):
            for value in _strings_in(node.slice):
                _add_name_tokens(tokens, value)
    from_tokens = set()
    _top_level_from_imports(tree.body, from_tokens)
    return Info(tokens, from_tokens, consts, code_consts)


class Repo:
    """The files of one tree, read once: its test files, its modules and what each says about the others."""

    def __init__(self, root):
        self.root = root
        self.test_folders = load_test_dirs(root)
        self.files = []  # every repository-relative .py path that is not fixture content of a skill
        self.name_count = {}  # how many files carry each name: a name that is not unique cannot be matched on its own
        for base, dirs, names in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            rel_base = posix(os.path.relpath(base, root))
            for name in sorted(names):
                rel = name if rel_base == "." else rel_base + "/" + name
                if re.match(r"skills/[^/]+/evals/", rel):  # cases and fixtures of a skill: not modules, not tests of ours
                    continue
                self.name_count[name] = self.name_count.get(name, 0) + 1
                if name.endswith(".py"):
                    self.files.append(rel)
        self._info = {}
        self.tests = [f for f in self.files if self.is_test_file(f)]
        self.modules = [f for f in self.files if f not in set(self.tests) and os.path.basename(f) not in ("conftest.py", "__init__.py")]
        self.stems = {}
        for f in self.modules:
            self.stems.setdefault(os.path.basename(f)[:-3], []).append(f)
        self._reverse = None

    def is_test_file(self, rel):
        name = os.path.basename(rel)
        return name.startswith("test_") and name.endswith(".py") and self.test_folder_of(rel) is not None

    def test_folder_of(self, rel):
        best = None
        for folder in self.test_folders:
            if rel.startswith(folder + "/") and (best is None or len(folder) > len(best)):
                best = folder
        return best

    def info(self, rel):
        if rel not in self._info:
            try:
                with open(os.path.join(self.root, rel), encoding="utf-8") as handle:
                    self._info[rel] = scan_source(handle.read())
            except (OSError, UnicodeDecodeError):
                self._info[rel] = None
        return self._info[rel]

    def reverse(self):
        """For each module: the modules that reference it (any way) and those that re-export from it (`from M import`)."""
        if self._reverse is None:
            any_edge, from_edge = {}, {}
            for rel in self.modules:
                info = self.info(rel)
                if info is None:
                    continue
                for token in info.tokens:
                    for target in self.stems.get(token, ()):
                        if target != rel:
                            any_edge.setdefault(target, set()).add(rel)
                for token in info.from_tokens:
                    for target in self.stems.get(token, ()):
                        if target != rel:
                            from_edge.setdefault(target, set()).add(rel)
            self._reverse = (any_edge, from_edge)
        return self._reverse

    def reach(self, changed):
        """Rule 2: the changed modules, everything that references one of them, and on through re-exports."""
        any_edge, from_edge = self.reverse()
        seen = set(changed)
        frontier = []
        for rel in changed:
            for importer in any_edge.get(rel, ()):
                if importer not in seen:
                    seen.add(importer)
                    frontier.append(importer)
        while frontier:
            rel = frontier.pop()
            for importer in from_edge.get(rel, ()):
                if importer not in seen:
                    seen.add(importer)
                    frontier.append(importer)
        return seen

    def modules_naming_stem(self, stem):
        return [m for m in self.modules if self.info(m) is not None and stem in self.info(m).tokens]

    def tests_referencing(self, stems):
        picked = {}
        for rel in self.tests:
            info = self.info(rel)
            if info is None:
                picked[rel] = "does not parse"
                continue
            hit = sorted(stems & info.tokens)
            if hit:
                picked[rel] = hit[0]
        return picked

    def tests_named_for(self, stem):
        """The tests named for a module: test_<stem>.py, or test_<stem>_<more>.py (never test_runtime_x.py for run.py)."""
        out = []
        for t in self.tests:
            name = os.path.basename(t)[:-3]
            if name == "test_" + stem or name.startswith("test_" + stem + "_"):
                out.append(t)
        return out

    def matcher(self, rel, strict=False):
        """A function that says whether a text (the strings of a Python file) names the data file `rel`: its path, or its name when
        that name is unique in the repository, or, when several files carry the name (README.md, index.html), its name together
        with the name of its folder (`strict`: only its path or
        `folder/name`, for the code of a module, where a bare README.md is the name of some project's own file)."""
        base, parent = os.path.basename(rel), os.path.basename(os.path.dirname(rel))

        def word(text):
            return re.compile(r"(?<![\w.-])" + re.escape(text) + r"(?![\w])")

        path_re, base_re = word(rel), word(base)
        parent_re = word(parent) if parent else None
        short = word(parent + "/" + base) if parent else None
        unique = self.name_count.get(base, 0) <= 1

        def matches(blob):
            if path_re.search(blob) or (short is not None and short.search(blob)):
                return True
            if not base_re.search(blob):
                return False
            if unique or parent_re is None:
                return True
            return False if strict else bool(parent_re.search(blob))
        return matches

    def tests_with_text(self, matches):
        return [rel for rel in self.tests if self.info(rel) is not None and matches(self.info(rel).blob)]

    def modules_with_text(self, matches):
        return [rel for rel in self.modules if self.info(rel) is not None and matches(self.info(rel).code_blob)]

    def tests_naming_folder(self, folder):
        out = []
        for rel in self.tests:
            info = self.info(rel)
            if info is not None and any(c == folder or c.startswith(folder + "/") for c in info.consts):
                out.append(rel)
        return out

    def owner_folder(self, rel):
        """The test folder that owns a file, or None."""
        inside = self.test_folder_of(rel)
        if inside:
            return inside
        parts = rel.split("/")
        guess = None
        if rel in WIRING_FILES or rel.startswith(WIRING_DIRS):
            guess = WIRING_FOLDER
        elif parts[0] in ("runtime", "flows", "interface"):
            guess = "runtime/tests"
        elif parts[0] == "scripts":
            guess = "scripts/tests"
        elif parts[0] == "providers":
            guess = "providers/%s/tests" % parts[1] if len(parts) > 2 else "scripts/tests"
        elif parts[0] == "evals":
            guess = "evals/tests"
        elif parts[0] == "adapters" and len(parts) > 2:
            guess = "adapters/%s/tests" % parts[1]
        elif parts[0] == "shared":
            guess = "shared/scripts/tests"
        elif parts[0] == "skills" and len(parts) > 3 and parts[2] == "scripts":
            guess = "skills/%s/scripts/tests" % parts[1]
        return guess if guess in self.test_folders else None


class Selection:
    def __init__(self, repo):
        self.repo = repo
        self.targets = {}  # target -> [reasons]
        self.notes = []

    def add(self, target, reason):
        if target and (target in self.repo.test_folders or os.path.isfile(os.path.join(self.repo.root, target))):
            self.targets.setdefault(target, [])
            if reason not in self.targets[target]:
                self.targets[target].append(reason)

    def add_folder(self, folder, reason):
        if folder in self.repo.test_folders:
            self.add(folder, reason)

    def add_all_folders(self, reason):
        for folder in self.repo.test_folders:
            self.add(folder, reason)

    def result(self):
        folders = sorted(t for t in self.targets if t in self.repo.test_folders)
        files = sorted(t for t in self.targets if t not in self.repo.test_folders and not any(t.startswith(f + "/") for f in folders))
        return folders + files


def copies_map(root):
    """{source: [destination, ...]} of shared/scripts/copies.json; empty when there is none."""
    try:
        with open(os.path.join(root, "shared", "scripts", "copies.json"), encoding="utf-8") as handle:
            data = json.load(handle)
        return {entry["source"]: [d["path"] for d in entry.get("to", [])] for entry in data.get("copies", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def select_module(repo, sel, changed, label, stems=()):
    """Rules 2 and 3 for modules that changed (or whose data changed). `stems` adds names that have no file to read (a deleted
    module). Returns how many tests were chosen."""
    chosen = 0
    reach = repo.reach(changed)
    wanted = {os.path.basename(m)[:-3] for m in reach} | set(stems)
    for rel, why in repo.tests_referencing(wanted).items():
        sel.add(rel, "%s: references %s" % (label, why))
        chosen += 1
    for stem in {os.path.basename(m)[:-3] for m in changed} | set(stems):
        for rel in repo.tests_named_for(stem):
            sel.add(rel, "%s: named for test_%s" % (label, stem))
            chosen += 1
    return chosen


def handle_file(repo, sel, rel):
    """The rules for one changed file (see the module text)."""
    base = os.path.basename(rel)
    parts = rel.split("/")
    full = os.path.join(repo.root, rel)

    # Rule 1: a test file selects itself.
    if repo.is_test_file(rel):
        if os.path.isfile(full):
            sel.add(rel, "rule 1: a changed test")
        return

    # Rule 5: configuration of the test run.
    if base in ("pytest.ini", "pyproject.toml") or (base == "conftest.py" and len(parts) == 1):
        sel.add_all_folders("rule 5: %s configures every test run" % rel)
        return
    if base == "conftest.py":
        folder = repo.owner_folder(rel)
        if folder:
            sel.add_folder(folder, "rule 5: conftest.py of %s" % folder)
        else:
            sel.notes.append("%s: no test folder owns this conftest.py" % rel)
        return

    inside = repo.test_folder_of(rel)
    if inside and base.endswith(".py"):
        sel.add_folder(inside, "rule 5: %s is a test kit" % rel)
        return

    if rel in WIRING_FILES or rel.startswith(WIRING_DIRS):
        sel.add_folder(WIRING_FOLDER, "rule 5: %s is the wiring of the checks" % rel)
        return

    # Rule 7: a skill's own content is measured by the lab and read by the validator.
    if parts[0] == "skills":
        in_scripts = len(parts) > 3 and parts[2] == "scripts"
        manifest = len(parts) == 4 and parts[2] == "evals" and base == "runtime-manifest.json"
        if not in_scripts and not manifest:
            return

    if base.endswith(".py"):
        handle_module(repo, sel, rel)
        return

    # Rule 4: a data file.
    if inside is None and not (rel.startswith(NAME_AREAS) or parts[0] == "skills"):
        return
    handle_data(repo, sel, rel)


def handle_module(repo, sel, rel):
    label = "rule 2/3: %s" % rel
    stem = os.path.basename(rel)[:-3]
    if os.path.basename(rel) == "__init__.py":
        folder = repo.owner_folder(rel)
        if folder:
            sel.add_folder(folder, "rule 5: %s cannot be resolved by name" % rel)
        return
    if rel in repo.modules and repo.info(rel) is not None:
        changed = [rel]
    elif rel in repo.modules:  # it does not parse: nothing can be said of what it references
        changed = []
    else:  # deleted: the modules that still name it are what it breaks
        changed = repo.modules_naming_stem(stem)
    chosen = select_module(repo, sel, changed, label, stems=[stem])
    if chosen == 0 or (rel in repo.modules and repo.info(rel) is None):
        folder = repo.owner_folder(rel)
        if folder:
            sel.add_folder(folder, "rule 5: %s is not resolved by the graph (nothing references it, or it does not parse); its whole test folder" % rel)
        else:
            sel.notes.append("%s: no test references it and no test folder owns it" % rel)


def handle_data(repo, sel, rel):
    parts = rel.split("/")
    label = "rule 4: %s" % rel
    is_doc = rel.endswith(".md")
    matches = repo.matcher(rel)
    chosen = 0
    for test in repo.tests_with_text(matches):
        sel.add(test, "%s: names it" % label)
        chosen += 1
    if not is_doc:  # the module that reads a data file runs differently when it changes; a document is read by people (and by the guards)
        readers = repo.modules_with_text(repo.matcher(rel, strict=True))
        if readers:
            chosen += select_module(repo, sel, readers, "%s: read by %s" % (label, ", ".join(readers[:3]) + ("..." if len(readers) > 3 else "")))
    folder = FOLDER_MENTION.get(parts[0])
    if folder:
        for test in repo.tests_naming_folder(folder):
            sel.add(test, "%s: names the folder %s/" % (label, folder))
            chosen += 1
    if chosen == 0 and not is_doc:
        owner = repo.owner_folder(rel)
        if owner:
            sel.add_folder(owner, "rule 5: nothing names %s; its whole test folder" % rel)
        else:
            sel.notes.append("%s: no test names it and no test folder owns it" % rel)


def select(repo, files, copies=None):
    """The targets for a list of changed repository-relative files."""
    sel = Selection(repo)
    copies = copies if copies is not None else copies_map(repo.root)
    destination_of = {dest: src for src, dests in copies.items() for dest in dests}
    extended = []
    for rel in files:
        extended.append(rel)
        if rel in destination_of:  # a generated copy and its source are one script
            extended.append(destination_of[rel])
        if rel in copies or rel in destination_of or rel == "shared/scripts/copies.json":
            for test in COPY_IDENTITY_TESTS:
                sel.add(test, "copies: %s is a shared script, a generated copy or their manifest" % rel)
    seen = set()
    for rel in extended:
        if rel not in seen:
            seen.add(rel)
            handle_file(repo, sel, rel)
        if rel == "shared/scripts/copies.json":
            sel.add_folder("shared/scripts/tests", "copies: manifest of generated copies")
    for guard in GUARDS:
        sel.add(guard, "rule 6: always-run guard")
    for rel in files:
        if rel in ("AGENTS.md",) or rel.startswith(("contracts/", "docs/architecture/")):
            sel.notes.append("%s: the documentation guards run (rule 6)" % rel)
    return sel


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    proc = subprocess.run(["git", "-C", root] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), proc.stderr.decode("utf-8", "replace").strip()))
    return proc.stdout.decode("utf-8", "surrogateescape")


def changed_since(root, base):
    """Files changed from the merge base of `base` and HEAD to the working tree, deleted ones included, and untracked ones."""
    names = []
    if base:
        merge_base = git(root, "merge-base", base, "HEAD").strip()
        names += git(root, "diff", "--name-only", "-z", "--no-renames", merge_base).split("\0")
    else:
        names += git(root, "diff", "--name-only", "-z", "--no-renames", "HEAD").split("\0")
    names += git(root, "ls-files", "-o", "--exclude-standard", "-z").split("\0")
    return [n for n in names if n]


def normalise(root, names):
    out = []
    for name in names:
        name = name.strip("\n") if name.endswith("\n") and "\0" not in name else name
        if not name:
            continue
        if os.path.isabs(name):
            name = os.path.relpath(name, root)
        name = posix(os.path.normpath(name))
        if name not in out and not name.startswith("../") and name != ".":
            out.append(name)
    return out


def read_names(source):
    data = sys.stdin.buffer.read() if source == "-" else open(source, "rb").read()
    return [n.decode("utf-8", "surrogateescape") for n in data.split(b"\0") if n]


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="See the top of scripts/select_tests.py for the rules.")
    parser.add_argument("--base", help="a git ref: the changed files are those since its merge base with HEAD, plus the working tree")
    parser.add_argument("--files", nargs="+", metavar="PATH", help="exactly these changed files (repository-relative or absolute)")
    parser.add_argument("--files-from", metavar="FILE", help="NUL-separated changed files read from FILE, or from stdin with -")
    parser.add_argument("--explain", action="store_true", help="print on stderr why each target was chosen")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="the tree to read (default: this repository)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = os.path.abspath(args.root)
    fell_back = None
    if args.files is not None or args.files_from is not None:
        names = list(args.files or [])
        if args.files_from is not None:
            names += read_names(args.files_from)
        files = normalise(root, names)
    else:
        try:
            files = normalise(root, changed_since(root, args.base))
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            files, fell_back = [], str(error)
    repo = Repo(root)
    if fell_back is not None:
        # The diff cannot be computed (an unknown ref, a shallow clone): never guess "nothing changed".
        sys.stderr.write("select_tests: cannot compute the changed files (%s); selecting every test folder\n" % fell_back)
        sel = Selection(repo)
        sel.add_all_folders("the diff could not be computed")
    else:
        sel = select(repo, files)
    result = sel.result()
    if args.explain:
        sys.stderr.write("select_tests: %d changed file(s), %d target(s)\n" % (len(files), len(result)))
        for note in sel.notes:
            sys.stderr.write("select_tests: note: %s\n" % note)
        for target in result:
            sys.stderr.write("select_tests: %s <- %s\n" % (target, "; ".join(sel.targets.get(target, [])[:4])))
    sys.stdout.write("".join(t + "\n" for t in result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
