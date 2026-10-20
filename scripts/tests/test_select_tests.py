"""Tests of scripts/select_tests.py (which tests a change can reach) and of scripts/test_slots.py (at most N test runs at once).

Offline. The selector is run on a small repository built in a temporary folder (fictional modules and tests), where every expected set is
written out by hand in this file, and on this repository for a few literal cases. The oracles are this file's own lists: they never
read the selector's GUARDS, its rules or the import graph it builds. Each group has a case that fails on a planted wrong selector.

Run: uv run --with pytest==9.1.1 pytest scripts/tests/test_select_tests.py
"""
from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_under_test", REPO / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sel = load("select_tests")
slots = load("test_slots")

# The guards, written out here a second time on purpose: dropping one from the selector fails a test (rule 6).
GUARDS = [
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
]

# A small repository. Its import graph, written out:
#   alpha --import--> beta --from--> gamma            hub --from--> beta            reader reads data.json
FIXTURE = {
    "pytest.ini": "[pytest]\n",
    "conftest.py": "",
    "README.md": "root readme\n",
    "runtime/README.md": "runtime readme\n",
    "runtime/alpha.py": "import beta\n\n\ndef a():\n    return beta.b()\n",
    "runtime/beta.py": "from gamma import g\n\n\ndef b():\n    return g()\n",
    "runtime/gamma.py": "def g():\n    return 1\n",
    "runtime/hub.py": "from beta import b\n",
    "runtime/delta.py": "def d():\n    return 4\n",
    "runtime/reader.py": "NAME = 'data.json'\n",
    "runtime/data.json": "{}\n",
    "runtime/notes.json": "{}\n",
    "runtime/orphan.json": "{}\n",
    "runtime/tests/conftest.py": "",
    "runtime/tests/kit.py": "VALUE = 1\n",
    "runtime/tests/test_alpha.py": "import alpha\n",
    "runtime/tests/test_beta.py": "import beta\n",
    "runtime/tests/test_hub.py": "import hub\n",
    "runtime/tests/test_names.py": "def load(n):\n    return n\n\n\nX = load('gamma')\n",
    "runtime/tests/test_gamma_core.py": "def test_x():\n    assert True\n",
    "runtime/tests/test_reader.py": "import reader\n",
    "runtime/tests/test_notes.py": "P = ('runtime', 'notes.json')\n",
    "runtime/tests/test_readme_plain.py": "N = 'README.md'\n",
    "runtime/tests/test_readme_runtime.py": "N = ('runtime', 'README.md')\n",
    "runtime/tests/test_interface_page.py": "D = 'interface'\n",
    "runtime/tests/test_unrelated.py": "import os\n",
    "runtime/c1.py": "def c():\n    return 1\n",
    "runtime/c2.py": "import c1\n",
    "runtime/c3.py": "import c2\n",
    "runtime/c4.py": "import c3\n",
    "runtime/c5.py": "import c4\n",
    "runtime/c4x.py": "from c4 import c\n",
    "runtime/tests/test_c4x.py": "import c4x\n",
    "runtime/lang_a.py": "WORDS = {}\n",
    "runtime/languages.json": '{"languages": ["lang_a"]}\n',
    "runtime/loader.py": "NAME = 'languages.json'\n",
    "runtime/tests/test_c1.py": "import c1\n",
    "runtime/tests/test_c2.py": "import c2\n",
    "runtime/tests/test_c3.py": "import c3\n",
    "runtime/tests/test_c4.py": "import c4\n",
    "runtime/tests/test_c5.py": "import c5\n",
    "runtime/tests/test_loader.py": "import loader\n",
    "runtime/tests/test_base.py": "VALUE = 1\n",
    "runtime/tests/test_uses_base.py": "import test_base\n",
    "runtime/tests/test_uses_uses.py": "import test_uses_base\n",
    "scripts/tool.py": "print('tool')\n",
    "scripts/other.py": "print('other')\n",
    "scripts/tests/test_runs_tool.py": "CMD = ['python3', 'scripts/tool.py']\n",
    "scripts/tests/test_scripts_unrelated.py": "import os\n",
    "scripts/tests/test_script_copies.py": "import os\n",
    "scripts/tests/test_sync_copies.py": "import os\n",
    "shared/scripts/rank.py": "def rank():\n    return 1\n",
    "shared/scripts/copies.json": '{"copies": [{"source": "shared/scripts/rank.py", "to": [{"path": "skills/demo/scripts/rank.py", "adopted": true}]}]}\n',
    "shared/scripts/tests/test_shared_rank.py": "R = 'rank.py'\n",
    "skills/demo/SKILL.md": "# demo\n",
    "skills/demo/evals/evals.json": "{}\n",
    "skills/demo/evals/runtime-manifest.json": "{}\n",
    "skills/demo/references/notes.md": "notes\n",
    "skills/demo/scripts/run.py": "def run():\n    return 1\n",
    "skills/demo/scripts/rank.py": "def rank():\n    return 1\n",
    "skills/demo/scripts/tests/test_run.py": "import run\n",
    "runtime/tests/test_manifest_reader.py": "M = 'runtime-manifest.json'\n",
    "interface/index.html": "<html></html>\n",
    "interface/js/x.js": "x\n",
    "docs/decisions.md": "d\n",
    "docs/architecture/plan.md": "p\n",
}
for guard in GUARDS:
    FIXTURE.setdefault(guard, "import os\n")


def build(root, extra=None):
    for rel, text in {**FIXTURE, **(extra or {})}.items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Path(root)


@pytest.fixture()
def tree(tmp_path):
    return build(tmp_path)


def pick(root, *files, explain=False):
    """What the selector prints for a list of changed files, through its command line (a fresh process)."""
    cmd = [sys.executable, str(REPO / "scripts" / "select_tests.py"), "--root", str(root), "--files", *files]
    if explain:
        cmd.append("--explain")
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines(), done.stderr


def expect(*targets, minus=()):
    """Sorted: folders first (a name without .py), then files; the guards are always there."""
    both = set(targets) | (set(GUARDS) - set(minus))
    folders = sorted(t for t in both if not t.endswith(".py"))
    files = sorted(t for t in both if t.endswith(".py") and not any(t.startswith(f + "/") for f in folders))
    return folders + files


# ---- rule 1: a changed test selects itself --------------------------------------------------------------------------------------------

def test_a_changed_test_selects_itself_and_a_deleted_one_selects_nothing(tree):
    assert pick(tree, "runtime/tests/test_alpha.py")[0] == expect("runtime/tests/test_alpha.py")
    assert pick(tree, "runtime/tests/test_removed.py")[0] == expect()


# ---- rule 2: a changed module -----------------------------------------------------------------------------------------------------------

REACH_OF_GAMMA = ["runtime/tests/test_alpha.py", "runtime/tests/test_beta.py", "runtime/tests/test_gamma_core.py", "runtime/tests/test_hub.py", "runtime/tests/test_names.py"]


def via_command_line(root, *files):
    return pick(root, *files)[0]


def in_process(root, *files):
    return sel.select(sel.Repo(str(root)), list(files)).result()


def check_gamma(root, run=via_command_line):
    """gamma.py changed. beta imports it (one step: test_beta); alpha only `import beta`s, two steps away (test_alpha); hub re-exports beta with
    `from beta import` (test_hub); test_names loads "gamma" by name; test_gamma_core is named for it."""
    assert run(root, "runtime/gamma.py") == expect(*REACH_OF_GAMMA)


def test_a_changed_module_selects_the_tests_that_reach_it_through_importers_and_re_exports(tree):
    check_gamma(tree)
    check_gamma(tree, in_process)  # the in-process path, which the planted selectors below replace, gives the same set


def test_planted_selector_that_drops_the_re_export_step_is_caught_by_the_oracle(tree, monkeypatch):
    def plain_steps_only(self, changed, depth=None):
        any_edge, _ = self.reverse()
        seen, frontier = set(changed), list(changed)
        for _ in range(sel.PLAIN_DEPTH):  # every reference up to the depth, and no re-export beyond it
            frontier = [i for rel in frontier for i in any_edge.get(rel, ()) if i not in seen and not seen.add(i)]
        return seen

    monkeypatch.setattr(sel.Repo, "reach", plain_steps_only)
    with pytest.raises(AssertionError):
        check_chain(tree, in_process)  # loses test_c4x: c4x re-exports c4 (`from c4 import`), a fourth step that is followed


CHAIN = ["runtime/tests/test_c1.py", "runtime/tests/test_c2.py", "runtime/tests/test_c3.py", "runtime/tests/test_c4.py", "runtime/tests/test_c4x.py"]


def check_chain(root, run=via_command_line):
    """c2..c5 each `import` the one before; c4x re-exports c4 with `from c4 import`. c1 changed: three plain steps (c2, c3, c4) are followed,
    then only the re-export (c4x); the plain fourth step (c5) is the bound."""
    assert run(root, "runtime/c1.py") == expect(*CHAIN)


def test_plain_imports_are_followed_three_steps_deep_and_no_further(tree):
    check_chain(tree)
    check_chain(tree, in_process)


def test_planted_selectors_that_follow_one_step_or_every_step_are_caught_by_the_oracle(tree, monkeypatch):
    original = sel.Repo.reach
    monkeypatch.setattr(sel.Repo, "reach", lambda self, changed, depth=None: original(self, changed, 1))
    with pytest.raises(AssertionError):
        check_chain(tree, in_process)  # loses test_c3 and test_c4
    monkeypatch.setattr(sel.Repo, "reach", lambda self, changed, depth=None: original(self, changed, 99))
    with pytest.raises(AssertionError):
        check_chain(tree, in_process)  # adds test_c5: the bound is part of the rule


def test_a_test_that_other_tests_import_selects_its_importers_and_theirs(tree, monkeypatch):
    wanted = expect("runtime/tests/test_base.py", "runtime/tests/test_uses_base.py", "runtime/tests/test_uses_uses.py")
    assert pick(tree, "runtime/tests/test_base.py")[0] == wanted
    assert in_process(tree, "runtime/tests/test_base.py") == wanted
    monkeypatch.setattr(sel.Repo, "tests_referencing", lambda self, stems: {})  # a selector without the test-to-test step
    assert in_process(tree, "runtime/tests/test_base.py") != wanted


def test_a_module_loaded_by_a_name_read_from_a_data_file_selects_the_tests_of_the_reader(tree, monkeypatch):
    assert pick(tree, "runtime/lang_a.py")[0] == expect("runtime/tests/test_loader.py")  # not the whole runtime/tests, which a module nothing links gets
    monkeypatch.setattr(sel.Repo, "data_files_naming", lambda self, stem: [])
    assert in_process(tree, "runtime/lang_a.py") == expect("runtime/tests")  # the planted selector loses the link and falls back to the folder


def test_a_module_with_no_importer_selects_only_its_named_tests_and_the_guards(tree):
    assert pick(tree, "runtime/alpha.py")[0] == expect("runtime/tests/test_alpha.py")  # nothing imports alpha but its own test
    assert pick(tree, "skills/demo/scripts/run.py")[0] == expect("skills/demo/scripts/tests/test_run.py")


def test_a_deleted_module_selects_the_tests_that_still_name_it(tree):
    (tree / "runtime/gamma.py").unlink()
    # beta, which imported it, is now broken: its importer alpha (and so test_alpha) is one step from it
    assert pick(tree, "runtime/gamma.py")[0] == expect("runtime/tests/test_gamma_core.py", "runtime/tests/test_names.py", "runtime/tests/test_beta.py",
                                                       "runtime/tests/test_hub.py", "runtime/tests/test_alpha.py")


# ---- rule 3: a script run by path --------------------------------------------------------------------------------------------------------

def test_a_script_run_by_path_selects_the_test_that_names_its_path(tree):
    assert pick(tree, "scripts/tool.py")[0] == expect("scripts/tests/test_runs_tool.py")


# ---- rule 4: a data file -----------------------------------------------------------------------------------------------------------------

def test_a_data_file_selects_the_tests_that_name_it_and_the_tests_of_the_module_that_reads_it(tree):
    assert pick(tree, "runtime/notes.json")[0] == expect("runtime/tests/test_notes.py")
    assert pick(tree, "runtime/data.json")[0] == expect("runtime/tests/test_reader.py")  # reader.py names data.json; test_reader imports it


def test_a_name_shared_by_two_files_counts_only_with_its_folder_beside_it(tree):
    assert pick(tree, "runtime/README.md")[0] == expect("runtime/tests/test_readme_runtime.py")  # not test_readme_plain, which names only README.md
    assert pick(tree, "README.md")[0] == expect()  # the files at the root are read by the guards, not named by tests


def test_a_folder_that_tests_name_selects_them_when_a_file_in_it_changes(tree):
    assert pick(tree, "interface/js/x.js")[0] == expect("runtime/tests/test_interface_page.py")


def test_a_data_file_nothing_names_selects_the_whole_test_folder_and_a_document_nothing_names_selects_nothing(tree):
    assert pick(tree, "runtime/orphan.json")[0] == expect("runtime/tests")
    assert pick(tree, "docs/architecture/plan.md")[0] == expect()
    assert pick(tree, "docs/decisions.md")[0] == expect()


# ---- rule 5: the whole-folder fallbacks --------------------------------------------------------------------------------------------------

def test_a_conftest_or_a_test_kit_selects_its_whole_folder(tree):
    assert pick(tree, "runtime/tests/conftest.py")[0] == expect("runtime/tests")
    assert pick(tree, "runtime/tests/kit.py")[0] == expect("runtime/tests")


def test_a_module_nothing_references_selects_the_whole_folder_that_owns_it(tree):
    assert pick(tree, "runtime/delta.py")[0] == expect("runtime/tests")
    assert pick(tree, "scripts/other.py")[0] == expect("scripts/tests")


def test_a_module_that_does_not_parse_selects_the_whole_folder(tree):
    (tree / "runtime/alpha.py").write_text("def broken(:\n", encoding="utf-8")
    assert pick(tree, "runtime/alpha.py")[0] == expect("runtime/tests")


def test_the_root_configuration_selects_every_folder(tree):
    folders = ["runtime/tests", "scripts/tests", "shared/scripts/tests", "skills/demo/scripts/tests"]
    assert pick(tree, "pytest.ini")[0] == expect(*folders)
    assert pick(tree, "conftest.py")[0] == expect(*folders)


def test_the_wiring_of_the_checks_selects_scripts_tests(tree):
    for changed in ("scripts/select_tests.py", "scripts/test_slots.py", ".githooks/pre-commit", ".github/workflows/checks.yml", "packs/default.txt",
                    "templates/agent.md", "agents/reviewer.md"):
        assert pick(tree, changed)[0] == expect("scripts/tests"), changed


# ---- rule 6: the guards ------------------------------------------------------------------------------------------------------------------

def test_the_guards_are_the_literal_list_and_every_one_exists_in_this_repository():
    assert list(sel.GUARDS) == GUARDS
    assert [g for g in GUARDS if not (REPO / g).is_file()] == []


def test_an_empty_change_prints_the_guards_only(tree, tmp_path):
    empty = tmp_path / "none.txt"
    empty.write_bytes(b"")
    done = subprocess.run([sys.executable, str(REPO / "scripts/select_tests.py"), "--root", str(tree), "--files-from", str(empty)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and done.stdout.splitlines() == expect()


def test_planted_selector_that_forgets_the_guards_is_caught_by_the_oracle(tree, monkeypatch):
    monkeypatch.setattr(sel, "GUARDS", ())
    repo = sel.Repo(str(tree))
    assert sel.select(repo, ["README.md"]).result() != expect()
    assert sel.select(repo, ["README.md"]).result() == []


# ---- rule 7: a skill's own content -------------------------------------------------------------------------------------------------------

def test_a_change_inside_a_skill_other_than_its_scripts_selects_only_the_guards(tree):
    for changed in ("skills/demo/SKILL.md", "skills/demo/evals/evals.json", "skills/demo/references/notes.md"):
        assert pick(tree, changed)[0] == expect(), changed
    assert pick(tree, "skills/demo/evals/runtime-manifest.json")[0] == expect("runtime/tests/test_manifest_reader.py")


# ---- shared scripts and their generated copies -------------------------------------------------------------------------------------------

def test_a_shared_script_its_copy_and_the_identity_tests_go_together(tree):
    both = expect("shared/scripts/tests/test_shared_rank.py", "scripts/tests/test_script_copies.py", "scripts/tests/test_sync_copies.py")
    assert pick(tree, "shared/scripts/rank.py")[0] == both
    assert pick(tree, "skills/demo/scripts/rank.py")[0] == expect("shared/scripts/tests/test_shared_rank.py", "scripts/tests/test_script_copies.py",
                                                                  "scripts/tests/test_sync_copies.py")


# ---- the command line --------------------------------------------------------------------------------------------------------------------

def test_explain_writes_to_standard_error_only(tree):
    quiet_out, quiet_err = pick(tree, "runtime/gamma.py")
    loud_out, loud_err = pick(tree, "runtime/gamma.py", explain=True)
    assert loud_out == quiet_out == expect(*REACH_OF_GAMMA)
    assert quiet_err == ""
    assert "runtime/tests/test_hub.py <-" in loud_err and "rule 6: always-run guard" in loud_err


def test_files_may_be_given_absolute_or_with_a_dot_slash(tree):
    out, _ = pick(tree, str(tree / "runtime/gamma.py"), "./runtime/gamma.py")
    assert out == expect(*REACH_OF_GAMMA)


def git(path, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"})
    done = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, env=env, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout


def test_base_reads_the_commits_since_the_merge_base_and_the_working_tree(tree):
    git(tree, "init", "-q", "-b", "main")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "base")
    git(tree, "checkout", "-q", "-b", "work")
    (tree / "runtime/gamma.py").write_text("def g():\n    return 2\n", encoding="utf-8")  # committed on the branch
    git(tree, "commit", "-q", "-am", "gamma")
    (tree / "scripts/tool.py").write_text("print('changed')\n", encoding="utf-8")  # uncommitted
    (tree / "runtime/tests/test_fresh.py").write_text("import os\n", encoding="utf-8")  # untracked
    done = subprocess.run([sys.executable, str(REPO / "scripts/select_tests.py"), "--root", str(tree), "--base", "main"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == expect(*REACH_OF_GAMMA, "scripts/tests/test_runs_tool.py", "runtime/tests/test_fresh.py")


def test_a_base_that_cannot_be_read_selects_every_folder_instead_of_nothing(tree):
    git(tree, "init", "-q", "-b", "main")
    done = subprocess.run([sys.executable, str(REPO / "scripts/select_tests.py"), "--root", str(tree), "--base", "no-such-ref"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0
    assert "cannot compute the changed files" in done.stderr
    assert done.stdout.splitlines() == expect("runtime/tests", "scripts/tests", "shared/scripts/tests", "skills/demo/scripts/tests")


# ---- this repository, literal cases ------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real():
    return sel.Repo(str(REPO))


def real_pick(repo, *files):
    return sel.select(repo, list(files)).result()


def test_a_change_to_the_time_parser_selects_its_tests_and_the_natural_dialogue_tests(real):
    got = real_pick(real, "runtime/natural_time.py")
    for wanted in ("runtime/tests/test_natural_time.py", "runtime/tests/test_natural_dialogues.py", "runtime/tests/test_natural_writes_dialogues.py",
                   "runtime/tests/test_natural_writes_mail_dialogues.py"):
        assert wanted in got, wanted
    assert "runtime/tests" not in got  # the files, not the folder


def test_a_language_table_selects_the_natural_dialogue_tests_through_the_data_file_that_names_it_and_through_the_listed_row(real):
    got = real_pick(real, "runtime/natural_lang_pt_br.py")
    assert "runtime/tests/test_natural_dialogues.py" in got and "runtime/tests/test_natural_writes_dialogues.py" in got
    assert "runtime/natural_languages.json" in real.data_files_naming("natural_lang_pt_br")  # the link M2 follows, not only the table


def test_the_column_of_portuguese_sentences_selects_the_tests_that_assert_them(real):
    got = real_pick(real, "runtime/phrases_pt_br.py")
    assert "runtime/tests/test_runtime_language_status.py" in got and "runtime/tests/test_phrases.py" in got


def test_a_test_that_other_tests_import_selects_them_in_this_repository(real):
    got = real_pick(real, "runtime/tests/test_service.py")
    assert "runtime/tests/test_ask_service.py" in got and "runtime/tests/test_agent_spend_fields.py" in got  # both `import test_service`


def real_import_oracle(root, start, depth):
    """The tests that really `import` the file, or a module that imports it, up to `depth` steps: only the `import` statements of the
    Python files, read here with the test's own parser (never the selector's graph), a name resolved by stem within the importer's area first."""
    import ast
    files = [str(p.relative_to(root)).replace(os.sep, "/") for p in Path(root).rglob("*.py")
             if not any(part in (".git", "node_modules", "__pycache__") for part in p.parts)]
    files = [f for f in files if not f.startswith("skills/") or "/scripts/" in f]
    by_stem = {}
    for f in files:
        by_stem.setdefault(os.path.basename(f)[:-3], []).append(f)
    importers = {}
    for f in files:
        try:
            tree = ast.parse((Path(root) / f).read_text(encoding="utf-8"))
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
    seen, frontier = {start}, [start]
    for _ in range(depth):
        frontier = [i for x in frontier for i in importers.get(x, ()) if i not in seen and not seen.add(i)]
    return {f for f in seen if os.path.basename(f).startswith("test_") and "/tests/" in f}


def test_every_test_that_really_imports_a_changed_file_within_three_steps_is_selected(real):
    """The regression the review found: a selection that missed tests importing the changed module through another module."""
    for changed in ("runtime/natural_time.py", "runtime/phrases_pt_br.py", "runtime/ops_core.py", "runtime/tests/test_service.py", "runtime/lease.py"):
        got = set(real_pick(real, changed))
        covered = lambda t: t in got or any(t.startswith(g + "/") for g in got)
        missed = sorted(t for t in real_import_oracle(REPO, changed, 3) if not covered(t))
        assert missed == [], (changed, missed[:5])


def test_every_row_of_the_table_of_unlinked_modules_still_matches_files(real):
    import fnmatch
    assert sel.UNLINKED_MODULES
    for folder, module_glob, test_globs in sel.UNLINKED_MODULES:
        assert [f for f in real.modules if fnmatch.fnmatchcase(f, folder + "/" + module_glob + ".py")], module_glob
        for glob in test_globs:
            assert [t for t in real.tests if fnmatch.fnmatchcase(t, folder + "/tests/" + glob + ".py")], glob


@pytest.mark.skipif(not (REPO / "runtime/interpreter_catalog.py").is_file(), reason="the interpreter catalog is not in this tree")
def test_a_change_to_the_interpreter_catalog_selects_its_interface_test(real):
    assert "runtime/tests/test_interpreter_interfaces.py" in real_pick(real, "runtime/interpreter_catalog.py")


def test_documents_and_skill_text_select_only_the_guards(real):
    assert real_pick(real, "docs/decisions.md", "docs/backlog.md", "AGENTS.md", "skills/mkt-publish/SKILL.md") == expect()


def test_the_wiring_and_the_test_configuration_of_this_repository_select_folders(real):
    assert "scripts/tests" in real_pick(real, ".githooks/pre-commit")
    got = real_pick(real, "runtime/tests/conftest.py")
    assert "runtime/tests" in got and not [t for t in got if t.startswith("runtime/tests/")]


def test_a_script_run_by_path_in_this_repository_selects_the_tests_that_name_it(real):
    got = real_pick(real, "skills/mkt-publish/scripts/payload.py")
    assert any(t.startswith("skills/mkt-publish/scripts/tests/") for t in got)


# ---- the slot helper (scripts/test_slots.py) ---------------------------------------------------------------------------------------------

def holder(directory, *extra, seconds=60):
    """A process that holds a slot for `seconds` seconds, started through the helper; returns it after it says it holds one."""
    code = "import sys, time; print('held', flush=True); time.sleep(%d)" % seconds
    proc = subprocess.Popen([sys.executable, str(REPO / "scripts/test_slots.py"), "--dir", str(directory), "--slots", "1", *extra, "--", sys.executable, "-c", code],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    timer = threading.Timer(30, proc.kill)  # a test must not hang the run
    timer.start()
    try:
        assert proc.stdout.readline().strip() == "held"
    finally:
        timer.cancel()
    return proc


def stop(proc):
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=30)
    for stream in (proc.stdout, proc.stderr):
        if stream:
            stream.close()


def test_a_slot_is_exclusive_and_a_second_run_gets_it_when_the_first_ends(tmp_path):
    first = slots.try_acquire(str(tmp_path), 1)
    assert first is not None
    assert slots.try_acquire(str(tmp_path), 1) is None  # the one slot is held
    os.close(first[0])
    again = slots.try_acquire(str(tmp_path), 1)
    assert again is not None and again[1] == 0
    os.close(again[0])


def test_three_slots_by_default_hold_three_runs_and_refuse_a_fourth(tmp_path):
    held = [slots.try_acquire(str(tmp_path), 3) for _ in range(3)]
    assert sorted(h[1] for h in held) == [0, 1, 2]
    assert slots.try_acquire(str(tmp_path), 3) is None
    for fd, _ in held:
        os.close(fd)


def test_the_wait_has_a_deadline(tmp_path):
    first = slots.try_acquire(str(tmp_path), 1)
    clock = iter([0.0, 0.1, 0.2, 0.5, 5.0, 9.0])
    waited = []
    got = slots.acquire(str(tmp_path), 1, 1, clock=lambda: next(clock), sleep=waited.append)
    assert got is None and len(waited) >= 1
    os.close(first[0])


def test_the_second_holder_waits_and_then_gets_the_slot_and_a_killed_holder_frees_it(tmp_path):
    first = holder(tmp_path)
    try:
        second = subprocess.Popen([sys.executable, str(REPO / "scripts/test_slots.py"), "--dir", str(tmp_path), "--slots", "1", "--wait", "30", "--",
                                   sys.executable, "-c", "print('second ran')"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(1.5)
            assert second.poll() is None  # still waiting: the first holds the only slot
            first.send_signal(signal.SIGKILL)  # a killed holder: nothing cleans up after it
            out, err = second.communicate(timeout=60)
            assert second.returncode == 0 and out.strip() == "second ran"
            assert "waiting for one" in err
        finally:
            stop(second)
    finally:
        stop(first)


def test_the_deadline_fails_with_the_message_and_exit_3_and_runs_nothing(tmp_path):
    first = holder(tmp_path)
    try:
        done = subprocess.run([sys.executable, str(REPO / "scripts/test_slots.py"), "--dir", str(tmp_path), "--slots", "1", "--wait", "1", "--",
                               sys.executable, "-c", "print('must not run')"], capture_output=True, text=True, timeout=60)
        assert done.returncode == 75
        assert "must not run" not in done.stdout
        assert "no test slot became free" in done.stderr and "NOT passed" in done.stderr
    finally:
        stop(first)


def test_a_killed_holder_frees_its_slot_at_once(tmp_path):
    first = holder(tmp_path)
    assert slots.try_acquire(str(tmp_path), 1) is None
    first.send_signal(signal.SIGKILL)
    first.wait(timeout=30)
    again = slots.try_acquire(str(tmp_path), 1)
    assert again is not None
    os.close(again[0])
    stop(first)


def test_the_command_exit_status_and_the_options_are_passed_through_or_refused(tmp_path):
    base = [sys.executable, str(REPO / "scripts/test_slots.py"), "--dir", str(tmp_path)]
    assert subprocess.run(base + ["--", sys.executable, "-c", "raise SystemExit(7)"], timeout=60).returncode == 7
    assert subprocess.run(base + ["--slots", "0", "--", "true"], capture_output=True, text=True, timeout=60).returncode == 2
    assert subprocess.run(base + ["--wait", "x", "--", "true"], capture_output=True, text=True, timeout=60).returncode == 2
    assert subprocess.run(base, capture_output=True, text=True, timeout=60).returncode == 2  # no command
    assert subprocess.run(base + ["--", "no-such-command-anywhere"], capture_output=True, text=True, timeout=60).returncode == 127


def test_the_environment_sets_the_defaults(tmp_path):
    env = {**os.environ, "WB_TEST_SLOT_DIR": str(tmp_path), "WB_TEST_SLOTS": "1", "WB_TEST_SLOT_WAIT": "1"}
    code = "import sys, time; print('held', flush=True); time.sleep(30)"
    first = subprocess.Popen([sys.executable, str(REPO / "scripts/test_slots.py"), "--", sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, text=True)
    try:
        assert first.stdout.readline().strip() == "held"
        done = subprocess.run([sys.executable, str(REPO / "scripts/test_slots.py"), "--", "true"], env=env, capture_output=True, text=True, timeout=60)
        assert done.returncode == 75 and "1 slots" in done.stderr
    finally:
        stop(first)
