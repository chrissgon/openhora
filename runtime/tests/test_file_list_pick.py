"""LP-2: a file of a list of files named by an ordinal word (runtime/ops_file_read.py `take` and `_place`, runtime/list_pick.py), after the maintainer's ok of 2026-10-28.

After "Encontrei 2 arquivos que combinam", "o primeiro", "o segundo" and "a última" open the file in that place of the list as it was printed. The lists here are the real ones of
`file-read` (the stand-in drives of test_file_read.py, the real `ops.say` path with its row `file-list-number`); every expectation is a literal of this file (the files, the places, the ids
a provider was asked to read), and each rule has a vacuity test that plants a wrong result. What is not a pick of a file is tested through `take` itself, which must return None and read nothing.
Offline; no model is asked; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_list_pick.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_file_read import ACTIVITIES, HEAD, LINE_1, READER_KEY, SECRET_MARK, WANTED, drives, item, ops_core, ops_file_read, phone  # noqa: F401  (the file world)
from test_ops_natural import world  # noqa: F401

ops = st.load("ops")
list_pick = st.load("list_pick")

FIRST = ("google", "gfile0000000003")          # the first row printed: the Google folder "Contratos 2026" is walked before the OneDrive folder
SECOND = ("microsoft", "drv1/it!1")            # the second row printed: ACTIVITIES
FIRST_TEXT = "Contrato de locacao, primeira via."


@pytest.fixture(autouse=True)
def fresh_lists():
    ops_file_read.forget_lists()


def add_first(drives):
    """A second file carries the name (the Google folder "Contratos 2026"), so that the search of the first use finds two."""
    if FIRST not in drives["drives"].files:
        drives["drives"].folders[("google", "GDRIVEFOLDER0002")].append(item("gfile0000000003", WANTED))
        drives["drives"].files[FIRST] = FIRST_TEXT.encode("utf-8")


def two(drives):
    """Two files carry the name: the list of the first use of the file world, shown (or shown again)."""
    add_first(drives)
    first = phone(drives, LINE_1)
    assert first.startswith("Encontrei 2 arquivos que combinam.") and drives["drives"].reads() == []
    return first


def many(drives, extra):
    """`extra` more files carry the name in the OneDrive folder, so that the list holds the two of `two` and `extra` more (the list prints at most 8 of them); the list is shown."""
    add_first(drives)
    for n in range(extra):
        drives["drives"].folders[("microsoft", "/Documentos")].append(item(f"drv1/more!{n}", WANTED))
        drives["drives"].files[("microsoft", f"drv1/more!{n}")] = f"more {n}".encode("utf-8")
    return phone(drives, LINE_1)


def take(drives, said):
    """What `take` answers to the line right after the list: its reply, or None."""
    ctx = ops_core.context(drives["path"])
    ops_file_read.begin_turn(ctx, "messaging", READER_KEY)
    return ops_file_read.take(drives["path"], ctx, said, "messaging", READER_KEY, {})


# --- the picks ---------------------------------------------------------------------------------------------------------------------------------


def test_o_primeiro_opens_the_first_file_of_the_list(drives):
    two(drives)
    reply = phone(drives, "o primeiro")
    assert drives["drives"].reads() == [FIRST]
    assert FIRST_TEXT in reply


@pytest.mark.parametrize("said", ["o segundo", "O segundo.", "a última", "o último", "the second one", "the last one", "o último, por favor"])
def test_the_second_and_the_last_open_the_second_file_of_a_list_of_two(drives, said):
    two(drives)
    reply = phone(drives, said)
    assert drives["drives"].reads() == [SECOND]
    assert reply.startswith(HEAD) and SECRET_MARK in reply and ACTIVITIES.strip().splitlines()[0] in reply


def test_the_number_forms_still_pick_as_before(drives):
    two(drives)
    assert phone(drives, "o 1") and drives["drives"].reads() == [FIRST]
    phone(drives, LINE_1)
    phone(drives, "2")
    assert drives["drives"].reads() == [FIRST, SECOND]


def test_the_row_file_list_number_takes_the_pick_before_the_interpreter_and_no_model_is_asked(drives, monkeypatch):
    two(drives)
    asked = []
    monkeypatch.setattr(ops_file_read.importlib.import_module("interpreter_route"), "complete", lambda *a, **k: asked.append(a) or {"ok": False})
    phone(drives, "o primeiro")
    assert asked == [] and drives["drives"].reads() == [FIRST]


# --- what is not a pick of a file --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("said", [
    "lê o primeiro",                    # a verb with it: not a pick (as "lê o 2" is none)
    "cancela o segundo",
    "o das 15h",                        # a value the list does not show (OPEN-LP-7)
    "a de amanhã",  # validate: allow english-only -- the Portuguese line under test
    "o do banco",
    "o terceiro",                       # a place beyond the list of two
    "o décimo",
    "o primeiro e o segundo",           # a longer request
    "os dois últimos",
    "o primeiro arquivo do drive",      # a title or folder word
    "15h",
])
def test_a_line_that_is_not_a_closed_pick_of_a_place_is_not_a_pick_and_reads_nothing(drives, said):
    two(drives)
    assert take(drives, said) is None
    assert drives["drives"].reads() == []


def test_a_pick_is_used_once_and_only_for_the_next_line_of_the_same_sender(drives):
    two(drives)
    ctx = ops_core.context(drives["path"])
    ops_file_read.begin_turn(ctx, "messaging", READER_KEY)
    ops_file_read.begin_turn(ctx, "messaging", READER_KEY)
    assert ops_file_read.take(drives["path"], ctx, "o primeiro", "messaging", READER_KEY, {}) is None          # two lines have begun: the list ended
    two(drives)
    assert ops_file_read.take(drives["path"], ctx, "o primeiro", "messaging", "telegram:55119000000099", {}) is None          # another sender
    assert drives["drives"].reads() == []
    assert take(drives, "o primeiro") is not None and take(drives, "o primeiro") is None


def test_a_last_of_a_list_that_printed_fewer_files_than_fit_is_not_a_pick_but_a_place_is(drives):
    shown = many(drives, 8)          # 10 files carry the name: the list prints 8 of them
    assert shown.startswith("Encontrei 10 arquivos que combinam.") and shown.count("\n") == 8
    assert take(drives, "a última") is None and drives["drives"].reads() == []
    phone(drives, LINE_1)
    eighth = take(drives, "o oitavo")
    phone(drives, LINE_1)
    assert eighth is not None and eighth == take(drives, "o 8")
    assert len(drives["drives"].reads()) == 2 and drives["drives"].reads()[0] == drives["drives"].reads()[1]


def test_a_last_of_a_list_that_printed_every_file_is_the_last_row_printed(drives):
    shown = many(drives, 6)          # 8 files carry the name: the list prints all 8
    assert shown.startswith("Encontrei 8 arquivos que combinam.") and shown.count("\n") == 8
    last = take(drives, "a última")
    phone(drives, LINE_1)
    assert last is not None and last == take(drives, "o 8")
    assert len(drives["drives"].reads()) == 2 and drives["drives"].reads()[0] == drives["drives"].reads()[1]


# --- vacuity: a planted wrong result is seen -----------------------------------------------------------------------------------------------------


def test_vacuity_the_pick_removed_makes_o_primeiro_no_pick(drives, monkeypatch):
    two(drives)
    monkeypatch.setattr(list_pick, "read", lambda said: None)
    assert take(drives, "o primeiro") is None and drives["drives"].reads() == []


def test_vacuity_a_wrong_place_would_open_another_file(drives, monkeypatch):
    two(drives)
    monkeypatch.setattr(list_pick, "choose", lambda form, rows, day_of=None, more=False: ("one", 1, None))
    phone(drives, "o primeiro")
    assert drives["drives"].reads() == [SECOND] != [FIRST]


def test_vacuity_a_pick_that_ignored_the_verb_would_read_with_lê_o_primeiro(drives, monkeypatch):
    two(drives)
    real = list_pick.read
    monkeypatch.setattr(list_pick, "read", lambda said: dict(real("o primeiro"), verb=None))
    assert take(drives, "lê o primeiro") is not None
    assert drives["drives"].reads() == [FIRST]
