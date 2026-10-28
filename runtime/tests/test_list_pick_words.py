"""LP-1: the words of a pick are data the registry owns (runtime/registry/list_pick_words.json, loaded by runtime/registry_data.py `list_pick_words()` and checked by `problems`).

What is proven here (each fault planted in a copy is the vacuity of its check: the real file passes, the plant is named): the file is well formed (header, version, folded, sorted, without repeat, no ordinal word twice, none shared with the word for last or with a lead or
an article, the weekday words are ordinal words); the loader returns both languages together with the position of each ordinal word; and a file with each fault planted is refused with a
sentence that names the fault. The files `private_words.json` and `search_stop_words.json` are checked by test_registry_data.py. Offline; the planted files are copies in a temporary folder.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_list_pick_words.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "runtime"))

import registry_data  # noqa: E402

FOLDER = REPO / "runtime" / "registry"
NAME = "list_pick_words"


@pytest.fixture
def data_copy(tmp_path):
    """A copy of the file that the loader reads, with the caches dropped before and after."""
    (tmp_path / "list_pick_words.json").write_text((FOLDER / "list_pick_words.json").read_text(encoding="utf-8"), encoding="utf-8")
    real = registry_data.FOLDER
    registry_data.FOLDER = str(tmp_path)
    registry_data.forget()
    yield tmp_path
    registry_data.FOLDER = real
    registry_data.forget()


def planted(data_copy, change):
    data = json.loads((FOLDER / "list_pick_words.json").read_text(encoding="utf-8"))
    change(data)
    (data_copy / "list_pick_words.json").write_text(json.dumps(data), encoding="utf-8")
    return " | ".join(registry_data.problems(NAME))


def test_the_file_is_well_formed_and_the_checker_runs_from_the_command_line():
    assert registry_data.problems(NAME) == []
    data = json.loads((FOLDER / "list_pick_words.json").read_text(encoding="utf-8"))
    assert data["v"] == 1 and data["made_from"] and "\n" not in data["rule"] and set(data["languages"]) == {"en", "pt-BR"}
    assert subprocess.run([sys.executable, str(REPO / "runtime/registry_data.py"), "--check"], capture_output=True, text=True).returncode == 0
    assert NAME in registry_data.FILES and registry_data.FILES[NAME] == "list_pick_words.json"


def test_the_loader_returns_both_languages_together_and_the_position_of_each_ordinal_word():
    words = registry_data.list_pick_words()
    assert words["ordinals"]["primeiro"] == (1, "primeiro") and words["ordinals"]["primeira"] == (1, "primeiro")
    assert words["ordinals"]["tenth"] == (10, "tenth") and words["ordinals"]["quarta"] == (4, "quarto")
    assert words["weekday_ordinals"] == {"segunda", "quarta", "quinta", "sexta"}
    assert ("a", "das") in words["clock_leads"] and ("the", "one", "at") in words["clock_leads"] and ("o", "do") in words["value_leads"]
    assert ("ultimo",) in words["last"] and ("last", "one") in words["last"] and ("por", "favor") in words["polite"] and ("o",) in words["articles"] and ("the",) in words["articles"]
    assert registry_data.list_pick_words() is words, "read once"


def test_a_badly_formed_file_is_reported_with_the_fault_named(data_copy):
    def unsorted(d):
        d["languages"]["pt-BR"]["articles"] = ["o", "a"]
    assert "pt-BR.articles: not sorted" in planted(data_copy, unsorted)

    def repeated(d):
        d["languages"]["en"]["polite"] = ["please", "please"]
    assert "en.polite: a repeated entry" in planted(data_copy, repeated)

    def unfolded(d):
        d["languages"]["pt-BR"]["last"] = ["Ultimo"]
    assert "pt-BR.last: not a list of folded phrases" in planted(data_copy, unfolded)

    def empty(d):
        d["languages"]["en"]["clock_leads"] = []
    assert "en.clock_leads: empty" in planted(data_copy, empty)

    def missing(d):
        del d["languages"]["pt-BR"]["ordinals"]
    assert "pt-BR: the keys are not" in planted(data_copy, missing)

    def header(d):
        d["v"], d["rule"] = 2, "two\nlines"
    found = planted(data_copy, header)
    assert "v is 2" in found and "rule is not one line" in found

    def languages(d):
        del d["languages"]["en"]
    assert "languages is not exactly" in planted(data_copy, languages)


def test_an_ordinal_word_is_never_two_positions_nor_a_word_for_last_nor_a_lead_nor_an_article(data_copy):
    def twice(d):
        d["languages"]["en"]["ordinals"][1] = ["first", "second"]
    assert "en.ordinals: a repeated word" in planted(data_copy, twice)

    def also_last(d):
        d["languages"]["pt-BR"]["last"] = ["primeiro", "ultimo"]
    assert "'primeiro' is both an ordinal and a word for last" in planted(data_copy, also_last)

    def also_article(d):
        d["languages"]["pt-BR"]["articles"] = sorted(d["languages"]["pt-BR"]["articles"] + ["primeiro"])
    assert "pt-BR.articles: 'primeiro' is also an ordinal word" in planted(data_copy, also_article)

    def also_lead(d):
        d["languages"]["en"]["value_leads"] = sorted(d["languages"]["en"]["value_leads"] + ["first"])
    assert "en.value_leads: 'first' is also an ordinal word" in planted(data_copy, also_lead)

    def weekday(d):
        d["languages"]["pt-BR"]["weekday_ordinals"] = ["domingo"]
    assert "'domingo' is not an ordinal word" in planted(data_copy, weekday)


def test_the_loader_refuses_nothing_it_was_not_given_so_a_good_copy_reads_as_the_original(data_copy):
    assert registry_data.problems(NAME) == []
    assert registry_data.list_pick_words()["ordinals"]["decimo"] == (10, "decimo")


def test_the_words_are_generic_words_of_the_languages():
    text = (FOLDER / "list_pick_words.json").read_text(encoding="utf-8")
    assert "@" not in text and "http" not in text and not any(ch.isdigit() for ch in text.replace('"v": 1', "").replace('"made_from": "73c7594"', ""))
