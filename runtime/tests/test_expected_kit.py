"""The expectation ledger (package HOT-1; runtime/tests/expected_kit.py, runtime/tests/expected/): `extend` adds the packages' items to a test's base list, refuses an item listed twice and a
malformed file, every name of the ledger is read by some test, and the double entry still bites in both directions (an item added that the source lacks, an item removed that the source has).
Pure: a fictional folder under `tmp_path`, and the real tree for the tests that read it. Every name and item is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_expected_kit.py
"""
from __future__ import annotations

import importlib.util
import json
import re

import pytest

import expected_kit as ek
import standin_tree as st

TESTS = ek.HERE
CONVERTED = {"natural_table.R", "natural_table.N", "natural_table.W", "natural_table.E", "natural_table.WORK", "registry_rows.EFFECTS", "registry_rows.MODEL_ROWS", "registry_rows.OFF_HOST",
             "registry_rows.SEPARATES", "messaging_policy.ON_MESSAGING", "messaging_policy.NOT_PERMITTED_BY_DEFAULT", "mcp.CHANNEL_ARG", "operations_table.NOT_OPERATIONS", "operations_table.PUBLIC_MODULES",
             "interpreter_coverage.NOT_SERVED", "interpreter_coverage.INTERNAL", "interpreter_coverage.WIDENING", "interpreter_coverage.PENDING_CORPUS", "interpreter_coverage.KNOWN_GRANTED",
             "phone_plain_words.MESSAGING_FILES", "phone_plain_words.SWEEP_FILES", "phone_plain_words.PAGE_ONLY", "run_limits.NUMBERS", "run_limits.BUILT"}      # the conversion of HOT-1: each is read through extend


def put(folder, package, add, stem=None):
    folder.mkdir(exist_ok=True)
    (folder / f"{stem or package}.json").write_text(json.dumps({"package": package, "add": add}), encoding="utf-8")


def fresh(name, source_edit=None):
    """The test module `test_<name>` loaded again under a name of its own, so that its constants are computed with the ledger in force now; `source_edit` changes its text first."""
    path = TESTS / f"test_{name}.py"
    source = path.read_text(encoding="utf-8")
    if source_edit:
        edited = source_edit(source)
        assert edited != source, "the planted edit changed nothing"
        source = edited
    spec = importlib.util.spec_from_loader(f"planted_{name}", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)  # security-scan: allow dynamic-eval -- runs this repository's own test module text, with a planted edit, to prove that the test fails
    return module


# --- (a) extend returns the base with the additions --------------------------------------------------------------------------------------------------


def test_extend_returns_the_base_of_its_own_type_with_every_files_additions_in_file_name_order(tmp_path):
    put(tmp_path, "zz-late", {"fict.LIST": ["d"], "fict.SET": ["x2"], "fict.DICT": {"k3": "v3"}, "fict.TUPLE": [9]})
    put(tmp_path, "aa-early", {"fict.LIST": ["c"], "fict.DICT": {"k2": "v2"}, "fict.FROZEN": ["f2"]})
    assert ek.extend("fict.LIST", ["a", "b"], tmp_path) == ["a", "b", "c", "d"]
    assert ek.extend("fict.SET", {"x1"}, tmp_path) == {"x1", "x2"} and isinstance(ek.extend("fict.SET", {"x1"}, tmp_path), set)
    assert ek.extend("fict.FROZEN", frozenset({"f1"}), tmp_path) == frozenset({"f1", "f2"}) and isinstance(ek.extend("fict.FROZEN", frozenset(), tmp_path), frozenset)
    assert ek.extend("fict.TUPLE", (1, 2), tmp_path) == (1, 2, 9) and isinstance(ek.extend("fict.TUPLE", (), tmp_path), tuple)
    assert ek.extend("fict.DICT", {"k1": "v1"}, tmp_path) == {"k1": "v1", "k2": "v2", "k3": "v3"}
    assert ek.extend("fict.UNNAMED", ["only", "base"], tmp_path) == ["only", "base"], "a name no file adds to returns the base"
    assert ek.extend("fict.LIST", ["a"], tmp_path / "no-such-folder") == ["a"], "no folder, no additions"
    base = ["a", "b"]
    ek.extend("fict.LIST", base, tmp_path)
    assert base == ["a", "b"], "the base is not changed in place"


def test_an_item_that_is_a_list_in_the_file_is_a_tuple_in_a_set_and_is_compared_as_one(tmp_path):
    put(tmp_path, "pack-a", {"fict.PAIRS": [["a", 1]]})
    assert ek.extend("fict.PAIRS", {("b", 2)}, tmp_path) == {("b", 2), ("a", 1)}
    put(tmp_path, "pack-b", {"fict.PAIRS": [["a", 1]]})
    with pytest.raises(ValueError, match="listed twice"):
        ek.extend("fict.PAIRS", {("b", 2)}, tmp_path)


# --- (b) vacuity: an item listed twice raises ---------------------------------------------------------------------------------------------------------


def test_vacuity_an_item_in_the_base_or_in_two_files_or_twice_in_one_file_raises(tmp_path):
    put(tmp_path, "one", {"fict.LIST": ["a"]})
    with pytest.raises(ValueError, match="listed twice"):
        ek.extend("fict.LIST", ["a", "b"], tmp_path)      # in the base and a file
    put(tmp_path, "two", {"fict.LIST": ["new"]})
    put(tmp_path, "one", {"fict.LIST": ["new"]})
    with pytest.raises(ValueError, match="listed twice"):
        ek.extend("fict.LIST", ["z"], tmp_path)      # in two files
    put(tmp_path, "one", {"fict.LIST": ["twice", "twice"]})
    put(tmp_path, "two", {})
    with pytest.raises(ValueError, match="listed twice"):
        ek.extend("fict.LIST", ["z"], tmp_path)      # twice in one file
    put(tmp_path, "one", {"fict.DICT": {"k": 1}})
    with pytest.raises(ValueError, match="listed twice"):
        ek.extend("fict.DICT", {"k": 0}, tmp_path)      # a key of a dict
    with pytest.raises(ValueError, match="twice"):
        ek.extend("fict.LIST", ["z", "z"], tmp_path)      # the base itself


def test_an_addition_of_another_type_than_the_base_raises(tmp_path):
    put(tmp_path, "one", {"fict.LIST": {"k": 1}, "fict.DICT": ["a"]})
    with pytest.raises(ValueError, match="is a list in the test"):
        ek.extend("fict.LIST", ["a"], tmp_path)
    with pytest.raises(ValueError, match="is a dict in the test"):
        ek.extend("fict.DICT", {"a": 1}, tmp_path)


# --- (c) a malformed file raises -----------------------------------------------------------------------------------------------------------------------


def test_vacuity_a_wrong_package_a_wrong_file_name_an_unknown_key_or_a_malformed_file_raises(tmp_path):
    put(tmp_path, "right", {"fict.LIST": ["a"]}, stem="wrong")
    with pytest.raises(ValueError, match="package"):
        ek.extend("fict.LIST", [], tmp_path)
    (tmp_path / "wrong.json").unlink()
    (tmp_path / "Bad_Name.json").write_text(json.dumps({"package": "Bad_Name", "add": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="lower case"):
        ek.files(tmp_path)
    (tmp_path / "Bad_Name.json").unlink()
    (tmp_path / "extra.json").write_text(json.dumps({"package": "extra", "add": {}, "note": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="keys"):
        ek.files(tmp_path)
    (tmp_path / "extra.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        ek.files(tmp_path)
    (tmp_path / "extra.json").write_text(json.dumps({"package": "extra", "add": {"NoModule": ["a"]}}), encoding="utf-8")
    with pytest.raises(ValueError, match="CONSTANT"):
        ek.files(tmp_path)
    (tmp_path / "extra.json").write_text(json.dumps({"package": "extra", "add": {"fict.LIST": "a"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="list of items"):
        ek.files(tmp_path)


# --- (d) the real tree ----------------------------------------------------------------------------------------------------------------------------------


def test_every_file_of_the_real_ledger_is_well_formed_and_every_name_in_it_is_read_by_a_test():
    ek.files()      # raises on a malformed file
    assert ek.unread() == [], "a name in runtime/tests/expected/ that no `extend(\"<name>\"` of the tests reads"


def test_vacuity_a_name_that_no_test_reads_is_caught(tmp_path):
    put(tmp_path, "zz-plant", {"natural_table.R": ["x"], "no_such_module.NOTHING": ["x"], "natural_table.NO_SUCH_CONSTANT": ["x"]})
    assert ek.unread(tmp_path) == ["natural_table.NO_SUCH_CONSTANT", "no_such_module.NOTHING"]


def test_the_names_the_tests_read_are_the_module_and_the_constant_they_are_written_in():
    """`extend("<module>.<CONSTANT>"` sits in `test_<module>.py` as the assignment of `<CONSTANT>`, so that `--show <name>` finds it. The readers are found by a regular expression over the files."""
    found = set()
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == "test_expected_kit.py":
            continue
        for module, constant in re.findall(r"\bextend\(\s*\"([a-z0-9_]+)\.([A-Za-z_][A-Za-z0-9_]*)\"", path.read_text(encoding="utf-8")):
            found.add(f"{module}.{constant}")
            assert path.name == f"test_{module}.py", f"{path.name} reads {module}.{constant}"
            assert re.search(rf"^{constant} = extend\(\"{module}\.{constant}\"", path.read_text(encoding="utf-8"), re.M), f"{path.name}: {constant} is not assigned from its own name"
    assert CONVERTED <= found, f"constants of the conversion no longer read through extend: {sorted(CONVERTED - found)}"


def test_show_prints_the_merged_value_the_test_module_computes():
    assert json.loads(ek.show("natural_table.R")) == sorted(fresh("natural_table").R)
    assert json.loads(ek.show("registry_rows.SEPARATES")) == fresh("registry_rows").SEPARATES


# --- (e), (f) vacuity on the real tree: the double entry bites in both directions ------------------------------------------------------------------------


def test_vacuity_an_item_the_ledger_adds_and_the_source_lacks_fails_the_class_test_of_the_natural_table(tmp_path, monkeypatch):
    put(tmp_path, "zz-plant", {"natural_table.R": ["no-such-op"]})
    monkeypatch.setattr(ek, "EXPECTED_DIR", tmp_path)
    module = fresh("natural_table")
    assert "no-such-op" in module.R
    with pytest.raises(AssertionError):
        module.test_the_classes_are_pinned_a_move_between_classes_changes_this_file_too()


def test_vacuity_a_base_without_a_real_item_fails_the_same_test_while_the_source_still_has_it():
    module = fresh("natural_table", lambda text: text.replace('R = extend("natural_table.R", {"status", "progress", ', 'R = extend("natural_table.R", {"progress", ', 1))
    assert "status" not in module.R
    with pytest.raises(AssertionError):
        module.test_the_classes_are_pinned_a_move_between_classes_changes_this_file_too()


def test_the_class_test_passes_on_the_real_tree_so_that_the_two_vacuity_tests_above_fail_for_their_planted_item_alone():
    module = fresh("natural_table")
    module.test_the_classes_are_pinned_a_move_between_classes_changes_this_file_too()


def test_the_ledger_extends_the_other_converted_constants_too(tmp_path, monkeypatch):
    """One planted item per module of the conversion shows up in that module's constant, and nowhere else."""
    plan = {"registry_rows.EFFECTS": ("EFFECTS", "x-effect"), "messaging_policy.ON_MESSAGING": ("ON_MESSAGING", "x-op"), "operations_table.NOT_OPERATIONS": ("NOT_OPERATIONS", "x_fn"),
            "interpreter_coverage.INTERNAL": ("INTERNAL", "x-internal"), "phone_plain_words.PAGE_ONLY": ("PAGE_ONLY", None), "run_limits.NUMBERS": ("NUMBERS", 99), "mcp.CHANNEL_ARG": ("CHANNEL_ARG", "x-op"),
            "operations_table.PUBLIC_MODULES": ("PUBLIC_MODULES", "x_module")}
    add = {name: ({"X_KEY": "x reason"} if item is None else [item]) for name, (_, item) in plan.items()}
    put(tmp_path, "zz-plant", add)
    monkeypatch.setattr(ek, "EXPECTED_DIR", tmp_path)
    for name, (constant, item) in plan.items():
        module = fresh(name.split(".")[0])
        value = getattr(module, constant)
        assert ("X_KEY" in value) if item is None else (item in value), name
