"""Tests of the reading of a reply about captions (runtime/media_phone_words.py, package V1d-1): `continue`, `wrong -> right` lines, the run of words a correction
names and its mapping to the closed edits of runtime/captions.py. Pure: no file, no store, no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_phone_words.py
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import standin_tree as st
from media_kit import WORDS, transcript

words = st.load("media_phone_words")
captions = st.load("captions")
RUNTIME = st.REPO / "runtime"
ROWS = [{"index": i, "text": text} for i, text in enumerate(WORDS)]      # Welcome to Aster Lane where every small step counts


def test_a_reply_that_goes_on_is_one_of_the_continue_words_alone():
    for text in ("continue", "Continue.", "go on", "continuar", "pode seguir!", "  NEXT  ", "pode continuar"):
        assert words.read(text) == {"kind": "continue"}, text
    for text in ("continue please", "ok", "go on now"):
        assert words.read(text) == {"kind": "unknown"}, text


def test_corrections_are_lines_with_one_arrow_each_and_the_three_arrows_read():
    assert words.read("Lane -> Laine") == {"kind": "corrections", "pairs": [[["Lane"], ["Laine"]]]}
    got = words.read("Aster -> Astor\nwhere → were\nsmall step => tiny step")
    assert got == {"kind": "corrections", "pairs": [[["Aster"], ["Astor"]], [["where"], ["were"]], [["small", "step"], ["tiny", "step"]]]}
    assert words.read("a -> ") == {"kind": "corrections", "pairs": [[["a"], []]]}      # an empty right side is a deletion
    assert words.read("Aster -> Astor\n\n  \nLane -> Laine")["pairs"] == [[["Aster"], ["Astor"]], [["Lane"], ["Laine"]]]


def test_a_reply_that_is_not_every_line_a_correction_is_unknown():
    assert words.read("Aster -> Astor\nthis is not one") == {"kind": "unknown"}
    assert words.read("a -> b -> c") == {"kind": "unknown"}, "two arrows in a line are no correction"
    assert words.read("-> Astor") == {"kind": "unknown"}, "nothing to correct"
    assert words.read("... -> x") == {"kind": "unknown"}, "a left side with no word in it"
    assert words.read(" ".join("w%d" % i for i in range(9)) + " -> x") == {"kind": "unknown"}, "more than eight words on the left"
    assert words.read("a -> " + " ".join("w%d" % i for i in range(21))) == {"kind": "unknown"}, "more than twenty words on the right"
    twenty, over = "\n".join("w%d -> x" % i for i in range(20)), "\n".join("w%d -> x" % i for i in range(21))
    assert words.read(twenty)["kind"] == "corrections" and words.read(over) == {"kind": "unknown"}
    for empty in ("", "   \n ", None, 5, ["a -> b"]):
        assert words.read(empty) == {"kind": "unknown"}, empty


def test_find_returns_the_one_run_of_words_ignoring_case_and_edge_punctuation():
    assert words.find(ROWS, ["Aster", "Lane"]) == (2, 3)
    assert words.find(ROWS, ["lane,"]) == (3, 3) and words.find(ROWS, ["(ASTER)", "lane."]) == (2, 3)
    assert words.find([{"index": 7, "text": "Aster,"}, {"index": 8, "text": "Lane"}], ["aster", "lane"]) == (7, 8), "the rows' own index values come back"


def test_find_refuses_a_run_that_is_missing_or_appears_twice():
    with pytest.raises(words.WordsError) as missing:
        words.find(ROWS, ["Astor"])
    assert missing.value.code == "not_found" and missing.value.wrong == "Astor"
    twice = [{"index": i, "text": t} for i, t in enumerate("go to the park, go to the shop".split())]
    with pytest.raises(words.WordsError) as ambiguous:
        words.find(twice, ["go", "to"])
    assert ambiguous.value.code == "ambiguous" and ambiguous.value.wrong == "go to"
    assert words.find(twice, ["go", "to", "the", "park"]) == (0, 3), "a longer run is unique"


def test_edits_one_correction_for_each_branch_of_the_mapping():
    assert words.edits(ROWS, [[["Aster", "Lane"], ["Astor", "Laine"]]]) == [{"op": "edit", "index": 2, "text": "Astor"}, {"op": "edit", "index": 3, "text": "Laine"}]
    assert words.edits(ROWS, [[["small"], []]]) == [{"op": "delete", "index": 6}]
    assert words.edits(ROWS, [[["small", "step"], []]]) == [{"op": "delete", "index": 6}, {"op": "delete", "index": 7}]
    assert words.edits(ROWS, [[["Aster"], ["Astor", "Lane"]]]) == [{"op": "edit", "index": 2, "text": "Astor Lane"}], "more words than one: a split"
    assert words.edits(ROWS, [[["Aster", "Lane"], ["A", "B", "C"]]]) == [{"op": "edit", "index": 2, "text": "A"}, {"op": "edit", "index": 3, "text": "B C"}]
    assert words.edits(ROWS, [[["Aster", "Lane", "where"], ["Astoria"]]]) == [{"op": "merge", "from": 2, "to": 4, "text": "Astoria"}]
    assert words.edits(ROWS, [[["Aster", "Lane", "where"], ["A", "B"]]]) == [{"op": "edit", "index": 2, "text": "A"}, {"op": "merge", "from": 3, "to": 4, "text": "B"}]
    assert words.edits(ROWS, [[["to"], ["too"]], [["step"], ["steps"]]]) == [{"op": "edit", "index": 1, "text": "too"}, {"op": "edit", "index": 7, "text": "steps"}]
    with pytest.raises(words.WordsError):
        words.edits(ROWS, [[["to"], ["too"]], [["nothing"], ["x"]]])


@pytest.mark.parametrize("pairs", [
    [[["Aster", "Lane"], ["Astor", "Laine"]]],
    [[["small"], []]],
    [[["small", "step"], []]],
    [[["Aster"], ["Astor", "Lane"]]],
    [[["Aster", "Lane"], ["A", "B", "C"]]],
    [[["Aster", "Lane", "where"], ["Astoria"]]],
    [[["Aster", "Lane", "where"], ["A", "B"]]],
    [[["to"], ["too"]], [["step"], ["steps"]]],
])
def test_the_edits_of_every_branch_are_accepted_by_the_closed_edits_of_the_captions(pairs):
    edited = captions.start_edited(transcript())
    review = captions.new_review()
    made = words.edits(ROWS, pairs)
    after, _, counts = captions.apply_edits(edited, review, made, revision=review["revision"], proposals={}, beats=set(), slots=set())
    assert after["words"] != edited["words"] and sum(counts.values()) >= 1


def test_two_corrections_that_touch_one_word_are_left_to_the_captions_to_refuse():
    edited, review = captions.start_edited(transcript()), captions.new_review()
    made = words.edits(ROWS, [[["Aster", "Lane"], ["A", "B"]], [["Lane"], ["C"]]])
    with pytest.raises(captions.CaptionError) as refused:
        captions.apply_edits(edited, review, made, revision=review["revision"], proposals={}, beats=set(), slots=set())
    assert refused.value.code == "overlapping_edits"


def test_post_choice_is_a_whole_number_in_range():
    for text in ("2", " 2. ", "2)", " 02 "):
        assert words.post_choice(text, 3) == 2, text
    for text in ("4", "0", "two", "2 please", "", "-1", None, 2):
        assert words.post_choice(text, 3) is None, text


def test_the_module_starts_on_its_own():
    flags = ["--help"]
    done = subprocess.run([sys.executable, "-I", str(RUNTIME / "media_phone_words.py"), *flags], capture_output=True, text=True, timeout=60, env={})
    assert done.returncode == 0 and "wrong -> right" in done.stdout
    other = ["--nope"]
    assert subprocess.run([sys.executable, "-I", str(RUNTIME / "media_phone_words.py"), *other], capture_output=True, text=True, timeout=60, env={}).returncode == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
