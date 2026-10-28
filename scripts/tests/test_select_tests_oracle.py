"""The import oracle of scripts/select_tests.py on this repository: every test that really imports a changed file within three steps
is selected. It reads the whole tree twice (the selector's graph, and its own parse of every `import`), about 18 s locally and 49 s in
CI, so it is no guard of every commit (docs/decisions.md, the entry of T2b). It runs in the nightly run and every whole-suite run
(.github/workflows/nightly.yml, checks.yml), and whenever the selector or the CI wiring changes (scripts/select_tests.py: rule 5 selects
scripts/tests whole; rule 2 selects this file by its name). The planted-selector tests on a fictional tree stay in test_select_tests.py,
which always runs, so a change to the selector's rules is still caught on every commit; what waits for the night is a miss that only the
real tree shows.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_select_tests_oracle.py
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("select_tests_under_oracle", REPO / "scripts" / "select_tests.py")
sel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sel)


@pytest.fixture(scope="module")
def real():
    return sel.Repo(str(REPO))


@functools.lru_cache(maxsize=None)
def _importers_of(root_text):
    files = [str(p.relative_to(root_text)).replace(os.sep, "/") for p in Path(root_text).rglob("*.py")
             if not any(part in (".git", "node_modules", "__pycache__") for part in p.parts)]
    files = [f for f in files if not f.startswith("skills/") or "/scripts/" in f]
    by_stem = {}
    for f in files:
        by_stem.setdefault(os.path.basename(f)[:-3], []).append(f)
    importers = {}
    for f in files:
        try:
            tree = ast.parse((Path(root_text) / f).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[-1] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                names.update([node.module.split(".")[-1]] if node.module else [])
                names.update(a.name for a in node.names)
        for name in names:
            candidates = by_stem.get(name, [])
            area = f.split("/")[0]
            for target in [c for c in candidates if c.split("/")[0] == area] or candidates:
                if target != f:
                    importers.setdefault(target, set()).add(f)
    return {target: frozenset(who) for target, who in importers.items()}


def importers_of(root):
    """{file: the files that import it}: only the `import` statements of the Python files, read here with the test's own parser (never
    the selector's graph), a name resolved by stem within the importer's area first. The parse of a tree runs once per process (the cache is
    keyed by the root as text), so the five changed files of the test below share one reading of the real tree, and a fictional tree has its own."""
    return _importers_of(str(root))


def real_import_oracle(root, start, depth):
    """The tests that really `import` the file, or a module that imports it, up to `depth` steps."""
    importers = importers_of(root)
    seen, frontier = {start}, [start]
    for _ in range(depth):
        frontier = [i for x in frontier for i in importers.get(x, ()) if i not in seen and not seen.add(i)]
    return {f for f in seen if os.path.basename(f).startswith("test_") and "/tests/" in f}


def write_tree(root, files):
    for rel, text in files.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


CHAIN = {  # a <- b <- c, and c <- test_c (3 steps from a); c <- d <- test_far (4 steps from a)
    "pkg/a.py": "", "pkg/b.py": "import a\n", "pkg/c.py": "import b\n", "pkg/d.py": "from c import x\n",
    "pkg/tests/test_c.py": "import c\n", "pkg/tests/test_far.py": "import d\n",
}


def test_the_walk_stops_at_the_depth_on_a_fictional_tree(tmp_path):
    root = write_tree(tmp_path, CHAIN)
    near = real_import_oracle(root, "pkg/a.py", 3)
    assert near == {"pkg/tests/test_c.py"}
    assert real_import_oracle(root, "pkg/a.py", 4) == {"pkg/tests/test_c.py", "pkg/tests/test_far.py"}
    assert real_import_oracle(root, "pkg/a.py", 2) == set()


def test_the_parse_of_a_root_runs_once_and_each_root_has_its_own_graph(tmp_path, monkeypatch):
    first = write_tree(tmp_path / "one", CHAIN)
    second = write_tree(tmp_path / "two", {"pkg/a.py": "", "pkg/tests/test_a.py": "import a\n"})
    graph = importers_of(first)
    assert importers_of(second) is not graph and importers_of(second) != graph
    assert "pkg/tests/test_c.py" in graph["pkg/c.py"] and "pkg/tests/test_c.py" not in importers_of(second).get("pkg/c.py", ())
    assert importers_of(REPO) is not graph and "runtime/ops.py" in importers_of(REPO)  # the real tree never shares an entry
    # a second call, and a walk of another depth or start, read nothing again: with the parser made to raise they still answer
    def no_parse(*args, **kwargs):
        raise AssertionError("the tree was parsed again")

    monkeypatch.setattr(ast, "parse", no_parse)
    assert importers_of(first) is graph
    assert real_import_oracle(first, "pkg/a.py", 3) == {"pkg/tests/test_c.py"}
    assert real_import_oracle(first, "pkg/b.py", 4) == {"pkg/tests/test_c.py", "pkg/tests/test_far.py"}


def test_vacuity_a_parse_that_is_not_cached_is_caught(tmp_path, monkeypatch):
    """The same patched parser, on a root that is not in the cache (it was cleared), makes the call fail: the previous test's claim is
    only worth something because the parser does run when the cache has no answer."""
    root = write_tree(tmp_path, CHAIN)
    importers_of(root)
    _importers_of.cache_clear()
    monkeypatch.setattr(ast, "parse", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("the tree was parsed again")))
    with pytest.raises(AssertionError, match="parsed again"):
        importers_of(root)


def test_every_test_that_really_imports_a_changed_file_within_three_steps_is_selected(real):
    """The regression the review found: a selection that missed tests importing the changed module through another module."""
    for changed in ("runtime/natural_time.py", "runtime/phrases_pt_br.py", "runtime/ops_core.py", "runtime/tests/test_service.py", "runtime/lease.py"):
        got = set(sel.select(real, [changed]).result())
        covered = lambda t: t in got or any(t.startswith(g + "/") for g in got)
        missed = sorted(t for t in real_import_oracle(REPO, changed, 3) if not covered(t))
        assert missed == [], (changed, missed[:5])


# The entry replay (runtime/tests/test_entry_replay.py) is the end-to-end proof of the messaging entry path. It is reached today through the
# test-module imports of that file, not through a rule, so a refactor of the kits could lose it with no other test noticing (the
# 2026-10-27 hygiene entry of docs/decisions.md). These are the modules of the entry path, written out here on purpose.
ENTRY_PATH_MODULES = ("messaging_bridge", "messaging_turn", "turn_order", "ops_turn", "ops_interpret", "ops_say", "ops_natural",
                      "ops_natural_writes", "ops_natural_mail", "ops_items", "plan_confirm", "card_words", "turn_gate", "interpreter",
                      "natural", "natural_writes", "event_lookup")
ENTRY_REPLAY = "runtime/tests/test_entry_replay.py"


def without_the_replay(repo, files):
    """Modules whose selection does not include the entry replay: the replay itself, or a folder that holds it, in the result."""
    return [f for f in files if not covers_replay(sel.select(repo, [f]).result())]


def covers_replay(result):
    return ENTRY_REPLAY in result or any(ENTRY_REPLAY.startswith(t + "/") for t in result)


def test_a_change_to_any_module_of_the_messaging_entry_path_selects_the_entry_replay(real):
    files = ["runtime/%s.py" % name for name in ENTRY_PATH_MODULES]
    assert [f for f in files if not (REPO / f).is_file()] == []  # a renamed module is a failure here, never a silent drop
    assert without_the_replay(real, files) == []


def test_vacuity_a_selection_that_drops_the_entry_replay_is_caught_and_names_the_module(real, monkeypatch):
    """The oracle's own sensitivity: with the replay removed from every selection, every module of the list is named."""
    real_select = sel.select

    def selects_no_replay(repo, files, copies=None):
        selection = real_select(repo, files, copies)
        for target in list(selection.targets):
            if target == ENTRY_REPLAY:
                del selection.targets[target]
        return selection

    monkeypatch.setattr(sel, "select", selects_no_replay)
    files = ["runtime/%s.py" % name for name in ENTRY_PATH_MODULES]
    assert without_the_replay(real, files) == files


# SLOW-1: the corpus-wide properties of the entry path (the claims, the two traces, the reads, the envelope) are checked once, by the observed replay
# (runtime/tests/test_entry_observed.py), no longer by a replay in each of four test files. CI's selection must still run it whenever the entry path moves,
# and the hook's fast set does not (decision SL-2: CI runs it before any merge).
OBSERVED_REPLAY = "runtime/tests/test_entry_observed.py"
ENTRY_DATA_FILES = ["runtime/tests/entry_ext/zz-pack.scenarios.jsonl", "runtime/tests/entry_ext/zz-pack.golden.jsonl"]


def selected(repo, changed, target):
    """Whether the selection for the changed file holds `target`, or a folder that holds it."""
    result = sel.select(repo, [changed]).result()
    return target in result or any(target.startswith(t + "/") for t in result)


def without_target(repo, files, target):
    return [f for f in files if not selected(repo, f, target)]


def test_a_change_to_any_module_of_the_messaging_entry_path_selects_the_observed_replay(real):
    files = ["runtime/%s.py" % name for name in ENTRY_PATH_MODULES]
    assert [f for f in files if not (REPO / f).is_file()] == []
    assert (REPO / OBSERVED_REPLAY).is_file()
    assert without_target(real, files, OBSERVED_REPLAY) == []


def test_a_change_to_a_scenario_or_a_golden_file_of_a_package_selects_the_observed_replay(real):
    assert without_target(real, ENTRY_DATA_FILES, OBSERVED_REPLAY) == []
    assert without_target(real, ENTRY_DATA_FILES, ENTRY_REPLAY) == [], "and still the golden's own replay"


def test_vacuity_a_selection_that_drops_the_observed_replay_is_caught_and_names_the_file(real, monkeypatch):
    """The oracle's own sensitivity: with the observed replay removed from every selection, every module of the list and every data file is named."""
    real_select = sel.select

    def selects_no_observed_replay(repo, files, copies=None):
        selection = real_select(repo, files, copies)
        for target in list(selection.targets):
            if target == OBSERVED_REPLAY:
                del selection.targets[target]
        return selection

    monkeypatch.setattr(sel, "select", selects_no_observed_replay)
    files = ["runtime/%s.py" % name for name in ENTRY_PATH_MODULES] + ENTRY_DATA_FILES
    assert without_target(real, files, OBSERVED_REPLAY) == files
