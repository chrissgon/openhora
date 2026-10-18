"""The functions launchd.py and systemd.py share are the same text in both files.

The two scheduler providers are separate files because a job runs a copy of one of them, alone, with the
system interpreter: they cannot import a common module. So what they share is written twice, and a fix to
the snapshot, the lock or the hash check in one file must reach the other. This test is what makes that
happen: a function of SHARED that differs fails here, and so does a function both files define that is on
neither list.

Run: uv run --with pytest pytest providers/scheduler/tests/test_scheduler_parity.py
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
LAUNCHD, SYSTEMD = HERE.parent / "launchd.py", HERE.parent / "systemd.py"

# Identical in both files: change one, change the other in the same commit.
SHARED = (
    "ProviderError", "acquire_lock", "archive_finished", "argument_file", "changed_since_approval",
    "copy_verified", "cut_note", "differs", "execute", "iso", "job_dir", "keep_tail", "kill_group", "last_firing",
    "load_command_file", "log", "main", "now", "orphan_group", "parse_iso", "pinned_python", "private_dir", "read_job",
    "record_firing", "record_group", "release_lock", "run_one_shot", "runs_path", "sha256", "snapshot_argv",
    "split_argument", "tail", "test_mode", "trim_in_place", "unverified_file", "validate_id", "wait_for_lock",
    "write_job", "write_private",
)
# The same name and another body, because the two services differ (unit files or a plist, the service's own
# time limit, where the jobs live). A function moves here only with that reason.
DIFFERENT = (
    "Stopped", "approval_digest", "build_parser", "cmd_cancel", "cmd_check", "cmd_list", "cmd_resolve",
    "cmd_run", "cmd_schedule", "finish", "home", "notify", "plan_job", "resolve_program", "run_command",
    "run_recurring", "unload",
)


def definitions(path: Path) -> dict:
    """The source text of every top-level function and class of a file, by name."""
    source = path.read_text(encoding="utf-8")
    return {node.name: ast.get_source_segment(source, node) for node in ast.parse(source).body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))}


LAUNCHD_DEFS, SYSTEMD_DEFS = definitions(LAUNCHD), definitions(SYSTEMD)


@pytest.mark.parametrize("name", SHARED)
def test_a_shared_function_is_the_same_text_in_both_providers(name):
    assert name in LAUNCHD_DEFS and name in SYSTEMD_DEFS, f"{name} is gone from one provider; update SHARED"
    assert LAUNCHD_DEFS[name] == SYSTEMD_DEFS[name], (
        f"{name} differs between launchd.py and systemd.py: make the same change in both files")


def test_every_function_both_providers_define_is_classified():
    common = set(LAUNCHD_DEFS) & set(SYSTEMD_DEFS)
    assert not set(SHARED) & set(DIFFERENT)
    assert common == set(SHARED) | set(DIFFERENT), (
        "a function both providers define must be listed in SHARED (identical) or DIFFERENT (with a reason): "
        f"{sorted(common ^ (set(SHARED) | set(DIFFERENT)))}")


def test_the_lists_say_what_is_true_today():
    """DIFFERENT is not a place to park a function that could be shared: one that became identical moves."""
    assert [name for name in DIFFERENT if LAUNCHD_DEFS[name] == SYSTEMD_DEFS[name]] == []


# --- SC8: what the scheduler reads of a command's output is what the contract says a publisher prints ---


def prints_column(cls: str) -> str:
    """The "Prints" cell of a class's row in the verbs table of providers/CONTRACT.md."""
    contract = (HERE.parents[1] / "CONTRACT.md").read_text(encoding="utf-8")
    table = contract.split("\n## Verbs per class\n", 1)[1].split("\n## ", 1)[0]
    (row,) = [line for line in table.splitlines() if line.startswith(f"| `{cls}` |")]
    return row.rstrip().rstrip("|").rsplit(" | ", 1)[1]


@pytest.mark.parametrize("script", [LAUNCHD, SYSTEMD], ids=lambda path: path.name)
def test_the_scheduler_reads_the_address_under_the_contracts_name(script):
    source = script.read_text(encoding="utf-8")
    (key,) = re.findall(r'^ADDRESS_KEY = "(\w+)"', source, flags=re.MULTILINE)
    assert f"`{key}`" in prints_column("publisher:<platform>"), (
        "the scheduler reads a key the contract's Prints column does not name for the publisher")
    assert f"`{key}`" in prints_column("scheduler:job")
    # The key is written once: no other line of the provider's code spells it.
    code = source.split('"""', 2)[2]
    assert [line for line in code.splitlines() if f'"{key}"' in line] == [f'ADDRESS_KEY = "{key}"']


# --- SC13: the contract row and the README state the whole interface ---------------------------


def load(script: Path):
    spec = importlib.util.spec_from_file_location(f"{script.stem}_interface", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verbs_cell(cls: str) -> str:
    """The "Verb and flags" cell of a class's row in providers/CONTRACT.md, with its escaped pipes read back."""
    contract = (HERE.parents[1] / "CONTRACT.md").read_text(encoding="utf-8")
    table = contract.split("\n## Verbs per class\n", 1)[1].split("\n## ", 1)[0]
    (row,) = [line for line in table.splitlines() if line.startswith(f"| `{cls}` |")]
    cells = re.split(r"(?<!\\)\|", row)
    return cells[2].replace("\\|", "|")


def readme_interface() -> str:
    (line,) = [line for line in (HERE.parent / "README.md").read_text(encoding="utf-8").splitlines()
               if line.startswith("Implementations of the `scheduler:job` class")]
    return line


def command_file_keys(source: str) -> set:
    """The keys load_command_file reads from a command file."""
    body = ast.get_source_segment(source, next(node for node in ast.parse(source).body if
                                               getattr(node, "name", "") == "load_command_file"))
    found = re.findall(r'spec(?:\.get\(|\[)"(\w+)"|"(\w+)" in spec', body)
    return {a or b for a, b in found}


@pytest.mark.parametrize("script", [LAUNCHD, SYSTEMD], ids=lambda path: path.name)
def test_the_contract_row_and_the_readme_name_every_verb_flag_and_key(script):
    # The README gave the interface as "schedule ... [--approved <digest>]" and "cancel --id <id>": --id, --dry-run
    # and --confirmed were missing and --approved read as optional; the run verb, cancel --dry-run and the command
    # file's keys were in no contract row.
    row, readme = verbs_cell("scheduler:job"), readme_interface()
    parser = load(script).build_parser()
    verbs = next(action.choices for action in parser._actions if action.dest == "verb")
    flags = {flag for action in parser._actions for flag in action.option_strings if flag not in ("-h", "--help")}
    keys = command_file_keys(script.read_text(encoding="utf-8"))
    assert keys == {"argv", "cwd", "snapshot", "outputs", "grace_minutes", "timeout_minutes"}
    for text, where in ((row, "the contract row"), (readme, "README's interface line")):
        missing = ([verb for verb in verbs if f"`{verb} " not in text and f"`{verb}`" not in text] + [flag for flag in flags if flag not in text]
                   + [key for key in keys if f"`{key}`" not in text])
        assert not missing, f"{where} does not name {missing}"
    assert "[--approved" not in readme and "--confirmed --approved <digest>" in readme


def test_the_readme_copies_the_contracts_synopses():
    row, readme = verbs_cell("scheduler:job"), readme_interface()
    synopses = [span for span in re.findall(r"`([^`]+)`", row)
                if span.split()[0] in ("schedule", "list", "cancel", "resolve", "run", "--check")]
    assert len(synopses) == 6
    for synopsis in synopses:
        assert f"`{synopsis}`" in readme, synopsis
