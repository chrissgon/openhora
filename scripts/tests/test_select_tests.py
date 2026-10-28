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
    "docs/decisions/2030-01-01-pkg-a-rule.md": "## 2030-01-01: A rule\n",
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
    assert pick(tree, "docs/decisions/2030-01-01-pkg-a-rule.md")[0] == expect()  # one file per entry: the same as the closed log


def test_vacuity_a_decision_file_selects_nothing_because_it_is_a_document_not_because_the_selector_never_looks_at_documents(tmp_path):
    """A test that names a document of a named area is selected for it; the same test naming a decision file is not (docs/decisions/ is read
    by the validator's decision-files check and by the guards, as docs/decisions.md was)."""
    tree = build(tmp_path, {"runtime/tests/test_names_docs.py": "A = 'docs/architecture/plan.md'\nB = 'docs/decisions/2030-01-01-pkg-a-rule.md'\nC = 'docs/decisions.md'\n"})
    assert pick(tree, "docs/architecture/plan.md")[0] == expect("runtime/tests/test_names_docs.py")
    assert pick(tree, "docs/decisions/2030-01-01-pkg-a-rule.md")[0] == expect()
    assert pick(tree, "docs/decisions.md")[0] == expect()


DATA_FOLDER_FIXTURE = {
    "runtime/tests/entry_ext/zz-pack.scenarios.jsonl": "{}\n",
    "runtime/tests/entry_ext/README.md": "readme\n",
    "runtime/tests/test_entry_replay.py": "import os\n",
    "runtime/tests/expected/zz-pack.json": "{}\n",
    "runtime/tests/test_expected_kit.py": "import os\n",
    "runtime/tests/test_natural_table.py": "import os\n",
    "runtime/phrases_parts/zz-pack.en.json": "{}\n",
    "runtime/phrases_parts/README.md": "readme\n",
    "runtime/phrases_en.py": "TABLE = {}\n",
    "runtime/tests/test_phrases.py": "import os\n",
    "runtime/tests/test_runtime_language_x.py": "import os\n",
    "runtime/tests/test_phone_x.py": "import os\n",
}


def test_a_file_of_a_data_folder_selects_the_tests_that_read_the_folder_and_never_the_whole_test_folder(tmp_path):
    """HOT-1: the scenarios and goldens of the packages select the entry replay, the ledger the tests that read it, the phrase parts the tests of the `phrases_*` row of UNLINKED_MODULES."""
    root = build(tmp_path, DATA_FOLDER_FIXTURE)
    for changed in ("runtime/tests/entry_ext/zz-pack.scenarios.jsonl", "runtime/tests/entry_ext/zz-pack.golden.jsonl"):
        assert in_process(root, changed) == expect("runtime/tests/test_entry_replay.py"), changed
    got = in_process(root, "runtime/tests/expected/zz-pack.json")
    assert set(got) - set(GUARDS) == {"runtime/tests/test_expected_kit.py", "runtime/tests/test_natural_table.py"} and "runtime/tests" not in got
    got = in_process(root, "runtime/phrases_parts/zz-pack.en.json")
    assert set(got) - set(GUARDS) == {"runtime/tests/test_phrases.py", "runtime/tests/test_runtime_language_x.py", "runtime/tests/test_phone_x.py",
                                                  "runtime/tests/test_interface_page.py"} and "runtime/tests" not in got
    assert in_process(root, "runtime/tests/entry_ext/README.md") == expect() and in_process(root, "runtime/phrases_parts/README.md") == expect(), "a document of the folder selects only the guards"
    assert "rule 4" in "\n".join(sel.select(sel.Repo(str(root)), ["runtime/tests/entry_ext/zz-pack.scenarios.jsonl"]).targets["runtime/tests/test_entry_replay.py"])


def test_vacuity_a_selector_without_the_table_of_data_folders_falls_back_to_the_whole_test_folder(tmp_path, monkeypatch):
    root = build(tmp_path, DATA_FOLDER_FIXTURE)
    monkeypatch.setattr(sel, "DATA_FOLDERS", ())
    assert in_process(root, "runtime/tests/entry_ext/zz-pack.scenarios.jsonl") == expect("runtime/tests"), "the fallback the table avoids"
    assert in_process(root, "runtime/tests/entry_ext/zz-pack.scenarios.jsonl") != expect("runtime/tests/test_entry_replay.py")


def test_the_hook_s_fast_set_adds_nothing_for_a_file_of_a_data_folder(tmp_path):
    root = build(tmp_path, DATA_FOLDER_FIXTURE)
    for changed in ("runtime/tests/entry_ext/zz-pack.scenarios.jsonl", "runtime/tests/expected/zz-pack.json", "runtime/phrases_parts/zz-pack.en.json"):
        assert direct_in_process(root, changed) == expect(), changed


def test_every_data_folder_of_the_table_and_every_test_it_lists_exists_in_this_repository(real):
    import fnmatch
    assert [folder for folder, _ in sel.DATA_FOLDERS] == ["runtime/tests/entry_ext/", "runtime/tests/expected/", "runtime/phrases_parts/"]
    for folder, test_globs in sel.DATA_FOLDERS:
        assert (REPO / folder).is_dir(), folder
        for glob in test_globs:
            assert [t for t in real.tests if fnmatch.fnmatchcase(t, glob)], glob
    phrases = [g for folder, g in sel.DATA_FOLDERS if folder == "runtime/phrases_parts/"][0]
    row = [globs for folder, module_glob, globs in sel.UNLINKED_MODULES if module_glob == "phrases_*"][0]
    assert sorted(phrases) == sorted("runtime/tests/" + g + ".py" for g in row), "the phrase parts select the tests of the phrases row of UNLINKED_MODULES"


def test_a_change_under_each_data_folder_of_this_repository_selects_the_tests_that_read_it_and_no_folder(real):
    assert "runtime/tests/test_entry_replay.py" in real_pick(real, "runtime/tests/entry_ext/zz-pack.scenarios.jsonl")
    got = real_pick(real, "runtime/tests/expected/zz-pack.json")
    assert {"runtime/tests/test_expected_kit.py", "runtime/tests/test_run_limits.py", "runtime/tests/test_natural_table.py"} <= set(got) and "runtime/tests" not in got
    got = real_pick(real, "runtime/phrases_parts/zz-pack.en.json")
    assert "runtime/tests/test_phrases.py" in got and "runtime/tests/test_runtime_language.py" in got and "runtime/tests" not in got


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
                    "templates/agent.md", "agents/reviewer.md", "scripts/test_dirs.py", "scripts/shard_tests.py", "scripts/pytest_plugins/wb_shard.py",
                    ".github/workflows/nightly.yml"):
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


# ---- --within: the selection kept inside a list of targets (the python39 job) -----------------------------------------------------------

# The list the fixture's tests use, written out here: a folder, a file under a folder that is not listed as a folder, and two guards' homes.
WITHIN_LIST = ("# the targets of a fictional python39 check\n"
               "\n"
               "runtime/tests\n"
               "scripts/tests/test_runs_tool.py\n"
               "scripts/tests/test_runtime_python39.py\n"
               "shared/scripts/tests\n")
# The guards that fall inside that list: the guard of the runtime rules is under runtime/tests, the 3.9 guard is listed by name.
KEPT_GUARDS = ["runtime/tests/test_runtime_rules.py", "scripts/tests/test_runtime_python39.py"]


def write_within(root, text=WITHIN_LIST, name="within.txt"):
    path = Path(root) / name
    path.write_text(text, encoding="utf-8")
    return path


def pick_within(root, within, *files, explain=False):
    cmd = [sys.executable, str(REPO / "scripts" / "select_tests.py"), "--root", str(root), "--within", str(within), "--files", *files]
    if explain:
        cmd.append("--explain")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def within_in_process(root, within, *files, capsys):
    assert sel.main(["--root", str(root), "--within", str(within), "--files", *files]) == 0
    return capsys.readouterr().out.splitlines()


def check_within(run):
    """`run(files)` gives the printed lines. Four changes, with the expected lines written out by hand: a module whose tests are under a
    listed folder (kept, with the two guards that fall inside the list); a module whose only test is outside the list (dropped); the
    wiring (a folder that holds listed files is replaced by those files, and the listed folder's guard stays)."""
    assert run(["runtime/gamma.py"]) == sorted(REACH_OF_GAMMA + KEPT_GUARDS)
    assert run(["skills/demo/scripts/run.py"]) == sorted(KEPT_GUARDS)  # skills/demo/scripts/tests/test_run.py is not listed
    assert run([".github/workflows/checks.yml"]) == sorted(KEPT_GUARDS + ["scripts/tests/test_runs_tool.py"])  # scripts/tests -> the listed files in it
    assert run(["README.md"]) == sorted(KEPT_GUARDS)


def test_within_keeps_what_is_inside_the_list_drops_the_rest_and_replaces_a_folder_by_the_listed_targets_in_it(tree):
    within = write_within(tree)

    def run(files):
        done = pick_within(tree, within, *files)
        assert done.returncode == 0, done.stderr
        assert done.stderr == ""  # nothing extra on either stream
        return done.stdout.splitlines()

    check_within(run)


def test_within_in_process_gives_the_same_lines(tree, capsys):
    within = write_within(tree)
    check_within(lambda files: within_in_process(tree, within, *files, capsys=capsys))


def test_vacuity_a_within_that_keeps_everything_or_drops_everything_is_caught_by_the_oracle(tree, capsys, monkeypatch):
    within = write_within(tree)
    monkeypatch.setattr(sel, "restrict", lambda result, listed, reasons=None: result)  # keeps every selected target
    with pytest.raises(AssertionError):
        check_within(lambda files: within_in_process(tree, within, *files, capsys=capsys))
    monkeypatch.setattr(sel, "restrict", lambda result, listed, reasons=None: [])  # keeps none
    with pytest.raises(AssertionError):
        check_within(lambda files: within_in_process(tree, within, *files, capsys=capsys))


def test_within_never_adds_a_target_the_selector_did_not_select_except_the_listed_ones_inside_a_selected_folder(tree):
    within = write_within(tree)
    listed = ["runtime/tests", "scripts/tests/test_runs_tool.py", "scripts/tests/test_runtime_python39.py", "shared/scripts/tests"]
    for changed in (["runtime/gamma.py"], ["scripts/tool.py"], [".githooks/pre-commit"], ["pytest.ini"], ["shared/scripts/rank.py"], ["README.md"]):
        plain = pick(tree, *changed)[0]
        kept = pick_within(tree, within, *changed).stdout.splitlines()
        assert kept == sorted(kept) and len(kept) == len(set(kept)), changed
        for target in kept:
            inside_list = any(target == item or target.startswith(item + "/") for item in listed)
            selected = target in plain or any(target.startswith(folder + "/") for folder in plain if folder in ("runtime/tests", "scripts/tests", "shared/scripts/tests"))
            assert inside_list and selected, (changed, target)


def test_within_explain_says_how_many_were_kept_on_standard_error_only(tree):
    within = write_within(tree)
    quiet = pick_within(tree, within, "runtime/gamma.py")
    loud = pick_within(tree, within, "runtime/gamma.py", explain=True)
    assert loud.stdout == quiet.stdout
    assert quiet.stderr == ""
    assert "within" in loud.stderr and "7 of" in loud.stderr  # the five tests of gamma and the two kept guards


def test_an_empty_or_missing_within_file_is_a_usage_error_and_prints_nothing(tree):
    empty = write_within(tree, "", "empty.txt")
    comments = write_within(tree, "# only a comment\n\n   \n", "comments.txt")
    for path in (empty, comments, Path(tree) / "no-such-list.txt"):
        done = pick_within(tree, path, "runtime/gamma.py")
        assert done.returncode == 2 and done.stdout == "", path
        assert "--within" in done.stderr, path


def test_a_relative_within_file_is_read_from_the_root(tree):
    (Path(tree) / "scripts" / "list.txt").write_text("runtime/tests\n", encoding="utf-8")
    done = subprocess.run([sys.executable, str(REPO / "scripts/select_tests.py"), "--root", str(tree), "--within", "scripts/list.txt",
                           "--files", "runtime/gamma.py"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == sorted(REACH_OF_GAMMA + ["runtime/tests/test_runtime_rules.py"])


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
    assert real_pick(real, "docs/decisions/README.md", "docs/decisions/2026-10-27-decisions-files-one-file-per-entry.md") == expect()


def test_the_wiring_and_the_test_configuration_of_this_repository_select_folders(real):
    assert "scripts/tests" in real_pick(real, ".githooks/pre-commit")
    got = real_pick(real, "runtime/tests/conftest.py")
    assert "runtime/tests" in got and not [t for t in got if t.startswith("runtime/tests/")]


def test_a_script_run_by_path_in_this_repository_selects_the_tests_that_name_it(real):
    got = real_pick(real, "skills/mkt-publish/scripts/payload.py")
    assert any(t.startswith("skills/mkt-publish/scripts/tests/") for t in got)


SLOW_META = ("scripts/tests/test_select_tests_oracle.py", "scripts/tests/test_checks_wiring.py", "scripts/tests/test_security_scan_repo.py")


def test_the_slow_meta_tests_are_no_guard_and_run_when_the_wiring_the_selector_or_the_scanner_changes(real):
    """docs/decisions.md, the entry of T2b: the three run in the nightly run and the whole-suite runs, and on these changes; never on every commit."""
    assert not set(SLOW_META) & set(sel.GUARDS) and all((REPO / name).is_file() for name in SLOW_META)
    for changed in (".github/workflows/checks.yml", ".github/workflows/nightly.yml", ".githooks/pre-commit", "scripts/select_tests.py",
                    "scripts/test_slots.py", "scripts/test_dirs.py", "scripts/shard_tests.py"):
        assert "scripts/tests" in real_pick(real, changed), changed
    assert "scripts/tests/test_security_scan_repo.py" in real_pick(real, "scripts/security_scan.py")


def test_vacuity_a_change_of_a_document_or_of_runtime_code_does_not_run_the_slow_meta_tests_as_a_folder_and_a_document_runs_none(real):
    """A change that no import, name or wiring links to the meta-tests runs none of the three. A runtime module can still reach the oracle
    and the scan test through the references the selector follows (the oracle names runtime/natural_time.py in a string), which is the
    selector working: it is never the whole folder scripts/tests."""
    assert not set(SLOW_META) & set(real_pick(real, "docs/decisions.md", "AGENTS.md", "skills/mkt-publish/SKILL.md"))
    assert not set(SLOW_META) & set(real_pick(real, "docs/decisions/2026-10-27-decisions-files-one-file-per-entry.md"))
    assert "scripts/tests" not in real_pick(real, "runtime/natural_time.py")


# ---- rule 1, second part: the importers of a SELECTED test (TEST-SPEED, part D(a)) ---------------------------------------------------------

IMPORTER_FIXTURE = {
    "runtime/m.py": "def m():\n    return 1\n",
    "runtime/tests/test_m.py": "import m\n\n\ndef helper():\n    return m.m()\n",
    "runtime/tests/test_user.py": "from test_m import helper\n",  # names nothing of `m`: it only uses the helper of the test that does
    "runtime/tests/test_user_of_user.py": "import test_user\n",
    "runtime/tests/test_imports_guard.py": "import test_validate_rules\n",  # imports a guard, which only rule 6 selects for most changes
}


def test_a_test_selected_by_a_module_change_selects_the_tests_that_import_it_and_theirs(tmp_path):
    root = build(tmp_path, IMPORTER_FIXTURE)
    wanted = expect("runtime/tests/test_m.py", "runtime/tests/test_user.py", "runtime/tests/test_user_of_user.py")
    assert pick(root, "runtime/m.py")[0] == wanted
    assert in_process(root, "runtime/m.py") == wanted
    assert "rule 1: imports the selected test test_m" in pick(root, "runtime/m.py", explain=True)[1]


def test_a_guard_that_only_rule_6_adds_is_never_followed_but_a_selected_one_is(tmp_path):
    root = build(tmp_path, IMPORTER_FIXTURE)
    assert in_process(root, "runtime/alpha.py") == expect("runtime/tests/test_alpha.py")  # test_imports_guard imports a guard; the guard is no seed
    assert pick(root, "docs/decisions.md")[0] == expect()
    # the same guard file, changed: rule 1 selects it, and then its importer follows
    assert in_process(root, "scripts/tests/test_validate_rules.py") == expect("runtime/tests/test_imports_guard.py")


def test_planted_selector_without_the_importer_step_is_caught_by_the_oracle(tmp_path, monkeypatch):
    root = build(tmp_path, IMPORTER_FIXTURE)
    wanted = expect("runtime/tests/test_m.py", "runtime/tests/test_user.py", "runtime/tests/test_user_of_user.py")
    assert in_process(root, "runtime/m.py") == wanted
    monkeypatch.setattr(sel, "follow_test_importers", lambda repo, selection, seeds, reason: [])
    planted = in_process(root, "runtime/m.py")
    assert planted == expect("runtime/tests/test_m.py") and planted != wanted  # test_user.py is lost: the miss this step closes
    # and a changed test still selects its own importers through rule 1 only if the helper is the one that does it: with it gone, they are lost too
    assert in_process(root, "runtime/tests/test_m.py") == expect("runtime/tests/test_m.py")


def test_on_this_repository_the_natural_reply_test_follows_a_change_to_the_natural_module(real):
    assert "runtime/tests/test_messaging_natural_reply.py" in real_pick(real, "runtime/natural.py")
    assert "runtime/tests/test_messaging_natural_reply.py" in real_pick(real, "runtime/ops.py")
    # a guard that only rule 6 adds is no seed: a small leaf stays small
    assert len(real_pick(real, "providers/scheduler/launchd.py")) < 60


# ---- --direct, the fast set of the hook (rule 9) ---------------------------------------------------------------------------------------------

DIRECT_FIXTURE = {
    "skills/demo/scripts/some-tool.py": "def f():\n    return 1\n",
    "skills/demo/scripts/tests/test_some_tool.py": "import os\n",
    "runtime/tests/test_alpha_extra.py": "import os\n",
}


def pick_direct(root, *files, explain=False):
    cmd = [sys.executable, str(REPO / "scripts" / "select_tests.py"), "--root", str(root), "--direct", "--files", *files]
    if explain:
        cmd.append("--explain")
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout.splitlines(), done.stderr


def direct_in_process(root, *files):
    return sel.select_direct(sel.Repo(str(root)), list(files)).result()


def test_direct_selects_the_guards_the_changed_test_and_the_tests_named_for_a_changed_module_and_nothing_followed(tmp_path):
    root = build(tmp_path, {**IMPORTER_FIXTURE, **DIRECT_FIXTURE})
    # alpha: test_alpha and test_alpha_extra are named for it; beta, which alpha imports, and every importer of alpha are not followed
    assert pick_direct(root, "runtime/alpha.py")[0] == expect("runtime/tests/test_alpha.py", "runtime/tests/test_alpha_extra.py")
    # gamma: only test_gamma_core is named for it (beta, alpha, hub and test_names reach it through imports, which the fast set does not follow)
    assert pick_direct(root, "runtime/gamma.py")[0] == expect("runtime/tests/test_gamma_core.py")
    # a changed test: itself, with no importers (test_user and test_user_of_user import test_m)
    assert pick_direct(root, "runtime/tests/test_m.py")[0] == expect("runtime/tests/test_m.py")
    # a hyphen in a script's name is an underscore in its test's
    assert pick_direct(root, "skills/demo/scripts/some-tool.py")[0] == expect("skills/demo/scripts/tests/test_some_tool.py")
    assert direct_in_process(root, "runtime/gamma.py", "runtime/alpha.py") == expect("runtime/tests/test_alpha.py", "runtime/tests/test_alpha_extra.py",
                                                                                     "runtime/tests/test_gamma_core.py")


def test_direct_adds_nothing_for_data_documents_test_kits_conftest_files_the_wiring_and_skills_and_never_prints_a_folder(tmp_path):
    root = build(tmp_path, {**IMPORTER_FIXTURE, **DIRECT_FIXTURE})
    for changed in ("runtime/data.json", "runtime/notes.json", "docs/decisions.md", "docs/decisions/2030-01-01-pkg-a-rule.md", "docs/architecture/plan.md", "runtime/tests/kit.py",
                    "runtime/tests/conftest.py", "conftest.py", "pytest.ini", ".githooks/pre-commit", ".github/workflows/checks.yml",
                    "skills/demo/SKILL.md", "skills/demo/evals/evals.json", "interface/index.html", "runtime/__init__.py"):
        got = pick_direct(root, changed)[0]
        assert got == expect(), (changed, got)
        assert not [t for t in got if not t.endswith(".py")], changed  # never a folder
    # the same files in the full selection do select folders or more: the fast set is the narrower one
    assert in_process(root, "conftest.py") != expect()


def test_direct_reads_a_deleted_module_by_its_name_and_a_deleted_test_selects_nothing(tmp_path):
    root = build(tmp_path, {**IMPORTER_FIXTURE, **DIRECT_FIXTURE})
    (root / "runtime/alpha.py").unlink()
    assert pick_direct(root, "runtime/alpha.py")[0] == expect("runtime/tests/test_alpha.py", "runtime/tests/test_alpha_extra.py")
    assert pick_direct(root, "runtime/tests/test_removed.py")[0] == expect()


def test_direct_adds_the_copy_identity_tests_for_a_shared_script_a_generated_copy_and_the_manifest(tmp_path):
    root = build(tmp_path, DIRECT_FIXTURE)
    identity = ("scripts/tests/test_script_copies.py", "scripts/tests/test_sync_copies.py")
    for changed in ("shared/scripts/rank.py", "skills/demo/scripts/rank.py", "shared/scripts/copies.json"):
        assert pick_direct(root, changed)[0] == expect(*identity), changed
    assert pick_direct(root, "shared/scripts/tests/test_shared_rank.py")[0] == expect("shared/scripts/tests/test_shared_rank.py")


def test_direct_cannot_be_combined_with_within_and_explains_its_choices(tmp_path):
    root = build(tmp_path)
    (root / "listed.txt").write_text("runtime/tests\n", encoding="utf-8")
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "select_tests.py"), "--root", str(root), "--direct", "--within", "listed.txt",
                           "--files", "runtime/alpha.py"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and "--direct" in done.stderr and done.stdout == ""
    out, err = pick_direct(root, "runtime/alpha.py", explain=True)
    assert "runtime/tests/test_alpha.py <- rule 9: named for test_alpha" in err and "rule 6: always-run guard" in err
    assert out == expect("runtime/tests/test_alpha.py")


def test_direct_without_a_diff_prints_the_guards_and_no_folder(tmp_path):
    root = build(tmp_path)
    git(root, "init", "-q", "-b", "main")
    done = subprocess.run([sys.executable, str(REPO / "scripts/select_tests.py"), "--root", str(root), "--direct", "--base", "no-such-ref"],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "cannot compute the changed files" in done.stderr
    assert done.stdout.splitlines() == expect()


def test_planted_direct_that_follows_importers_or_drops_the_named_tests_is_caught_by_the_oracle(tmp_path, monkeypatch):
    root = build(tmp_path, {**IMPORTER_FIXTURE, **DIRECT_FIXTURE})
    wanted = expect("runtime/tests/test_alpha.py", "runtime/tests/test_alpha_extra.py")
    assert direct_in_process(root, "runtime/alpha.py") == wanted
    monkeypatch.setattr(sel.Repo, "tests_named_for", lambda self, stem: [])
    assert direct_in_process(root, "runtime/alpha.py") != wanted
    monkeypatch.undo()
    original = sel.select_direct

    def follows(repo, files, copies=None):  # a fast set that also followed the importers: the same change then selects more
        chosen = original(repo, files, copies)
        sel.follow_test_importers(repo, chosen, sorted(t for t in chosen.targets if t not in repo.test_folders), "x {stem}")
        return chosen

    assert direct_in_process(root, "runtime/m.py") == expect("runtime/tests/test_m.py")
    monkeypatch.setattr(sel, "select_direct", follows)
    assert direct_in_process(root, "runtime/m.py") != expect("runtime/tests/test_m.py")


def test_on_this_repository_direct_gives_the_named_tests_of_a_module_and_only_the_guards_for_one_without(real):
    got = sel.select_direct(real, ["runtime/turn_gate.py"]).result()
    assert "runtime/tests/test_turn_gate_fallback.py" in got and "runtime/tests/test_turn_gate_refresh.py" in got
    assert not [t for t in got if not t.endswith(".py")]
    extra = [t for t in sel.select_direct(real, ["runtime/messaging_bridge.py", "runtime/messaging_turn.py"]).result() if t not in GUARDS]
    assert extra == []  # no test is named for either of them: the guards alone
    assert sorted(sel.select_direct(real, ["docs/backlog.md"]).result()) == sorted(GUARDS)


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


# ---- the workers of one run (scripts/test_slots.py --workers) ----------------------------------------------------------------------------

def workers_run(*args, **env):
    clean = {k: v for k, v in os.environ.items() if k not in ("WB_TEST_WORKERS", "WB_TEST_SLOTS")}
    return subprocess.run([sys.executable, str(REPO / "scripts/test_slots.py"), *args], env={**clean, **env}, capture_output=True, text=True, timeout=60)


def test_the_workers_of_a_run_are_the_cores_divided_by_the_slots_and_never_fewer_than_two():
    assert slots.workers(3, cpu=14, env={}) == 4  # 3 runs of 4 workers use 12 of the 14 cores
    assert slots.workers(3, cpu=4, env={}) == 2
    assert slots.workers(3, cpu=1, env={}) == 2
    assert slots.workers(1, cpu=14, env={}) == 14
    assert slots.workers(3, cpu=None, env={}) == max(2, (os.cpu_count() or 2) // 3)


def test_the_environment_sets_the_workers_by_hand_and_a_bad_value_is_refused():
    assert slots.workers(3, cpu=14, env={"WB_TEST_WORKERS": "7"}) == 7
    for bad in ("0", "x", "-3", "2.5", ""):
        with pytest.raises(Exception, match="WB_TEST_WORKERS"):
            slots.workers(3, cpu=14, env={"WB_TEST_WORKERS": bad})


def test_workers_prints_one_integer_with_no_command_and_a_bad_value_exits_2():
    done = workers_run("--slots", "3", "--workers")
    assert done.returncode == 0 and done.stdout == "%d\n" % max(2, (os.cpu_count() or 2) // 3) and done.stderr == ""
    assert workers_run("--workers", WB_TEST_WORKERS="7").stdout == "7\n"
    assert workers_run("--workers", WB_TEST_SLOTS="1").stdout == "%d\n" % max(2, os.cpu_count() or 2)  # the slots are read as the run reads them
    for bad in ("0", "x"):
        refused = workers_run("--workers", WB_TEST_WORKERS=bad)
        assert refused.returncode == 2 and "WB_TEST_WORKERS" in refused.stderr and refused.stdout == ""


def test_vacuity_without_workers_no_command_still_fails():
    done = workers_run()
    assert done.returncode == 2 and "no command" in done.stderr and done.stdout == ""
    assert workers_run("--slots", "3").returncode == 2
