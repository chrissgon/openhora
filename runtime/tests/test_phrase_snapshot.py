"""T8-0b: the phrase snapshot (runtime/tests/phrase_snapshot.py) is the table's, and it says what it says.

`test_the_snapshot_is_the_table` is the one test that pins the table's wording: it fails when a sentence, a key or a field of the table changed and the two files under
runtime/tests/snapshots/ were not regenerated, and it prints the command. Every other test here checks the snapshot tool against a small table of this file's own and its
own literals, so the oracle is not the wording it renders; the planted cases at the end are the vacuity of the rest (a reworded sentence, a renamed field, a missing key,
a missing file, each makes the check fail).
"""
import copy
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import phrase_snapshot as snap  # noqa: E402
import phrases  # noqa: E402

# A table of this file's own (fictional sentences; the second language carries no accented letter, the repository's English check reads this file).
SMALL = {
    "en": {"GREET": "Hello {name}, you have {n} messages.", "TWO": "First {day}.\nSecond \\ line.", "ODD": "Needs {zzz_unknown}.", "BYE": "Goodbye."},
    "pt-BR": {"GREET": "Ola {name}, voce tem {n} mensagens.", "TWO": "Primeira {day}.\nSegunda \\ linha.", "ODD": "Precisa de {zzz_unknown}.", "BYE": "Tchau."},
}


def test_the_snapshot_is_the_table():
    """Strict (WB_GENERATED_BLOCKS=strict: a batch, a pull request into main, a push, the nightly run): the files are the table's, byte for byte. Lenient (a package's pull
    request, and the default): only what a package cannot leave stale (`phrase_snapshot.lenient_problems`); the batch regenerates the files."""
    mode = os.environ.get("WB_GENERATED_BLOCKS", "lenient")
    found = snap.problems(mode)
    assert not found, "\n".join(found) + f"\nthe wording of the table changed: review it, then run `{snap.COMMAND}` (the batch does it for a package's pull request)"


def test_every_key_of_each_language_is_a_line_sorted_once():
    for language in snap.LANGUAGES:
        keys = [line.split(": ", 1)[0] for line in snap.render(language).splitlines()]
        assert keys == sorted(phrases.TABLE[language]), language
        assert len(keys) == len(set(keys)) == len(phrases.TABLE[language]), language


def test_the_parts_are_in_the_snapshot():
    # The keys that a part file adds (runtime/phrases_parts/) are in the table, so in the snapshot; the part files are read from disk, not from the table.
    import json
    for language, tag in (("en", "en"), ("pt-BR", "pt-BR")):
        keys = set()
        for path in sorted((HERE.parent / "phrases_parts").glob(f"*.{tag}.json")):
            keys |= set(json.loads(path.read_text(encoding="utf-8"))["table"])
        assert keys, "the phrase parts folder holds keys"
        lines = {line.split(": ", 1)[0] for line in snap.render(language).splitlines()}
        assert keys <= lines, sorted(keys - lines)[:5]


def test_a_line_is_the_key_and_the_sentence_with_the_values_in_place():
    assert snap.render("en", SMALL) == (
        "BYE: Goodbye.\n"
        "GREET: Hello Ana Lima, you have 3 messages.\n"
        "ODD: Needs <zzz_unknown>.\n"
        "TWO: First Wed 21/10/2026.\\nSecond \\\\ line.\n"
    )
    assert snap.render("pt-BR", SMALL).splitlines()[1] == "GREET: Ola Ana Lima, voce tem 3 mensagens."


def test_a_field_with_no_fixed_value_shows_its_name():
    assert snap.render_sentence("Needs {zzz_unknown} and {name}.") == "Needs <zzz_unknown> and Ana Lima."
    assert snap.render_sentence("Needs {name}.", {"name": "Zed"}) == "Needs Zed."


def test_the_render_is_deterministic():
    assert snap.render("en") == snap.render("en")
    assert snap.render("pt-BR") == snap.render("pt-BR")


def test_write_then_check_agree_and_the_files_are_the_render(tmp_path):
    paths = snap.write(tmp_path, SMALL)
    assert sorted(Path(p).name for p in paths) == ["phrases.en.txt", "phrases.pt-BR.txt"]
    assert snap.differences(tmp_path, SMALL) == []
    assert (tmp_path / "phrases.en.txt").read_text(encoding="utf-8") == snap.render("en", SMALL)


def test_a_reworded_sentence_is_a_difference_naming_the_key(tmp_path):
    snap.write(tmp_path, SMALL)
    planted = copy.deepcopy(SMALL)
    planted["en"]["BYE"] = "See you."
    found = "\n".join(snap.differences(tmp_path, planted))
    assert "-BYE: Goodbye." in found and "+BYE: See you." in found


def test_a_renamed_field_is_a_difference(tmp_path):
    snap.write(tmp_path, SMALL)
    planted = copy.deepcopy(SMALL)
    planted["pt-BR"]["GREET"] = "Ola {person}, voce tem {n} mensagens."
    found = "\n".join(snap.differences(tmp_path, planted))
    assert "+GREET: Ola <person>, voce tem 3 mensagens." in found


def test_an_added_and_a_removed_key_are_differences(tmp_path):
    snap.write(tmp_path, SMALL)
    added = copy.deepcopy(SMALL)
    added["en"]["NEW"] = "New."
    added["pt-BR"]["NEW"] = "Novo."
    assert "+NEW: New." in "\n".join(snap.differences(tmp_path, added))
    removed = copy.deepcopy(SMALL)
    del removed["en"]["BYE"], removed["pt-BR"]["BYE"]
    assert "-BYE: Goodbye." in "\n".join(snap.differences(tmp_path, removed))


def test_a_missing_file_is_a_difference(tmp_path):
    snap.write(tmp_path, SMALL)
    (tmp_path / "phrases.pt-BR.txt").unlink()
    assert snap.differences(tmp_path, SMALL) == ["phrases.pt-BR.txt: the file does not exist"]


def test_a_long_difference_is_cut(tmp_path):
    snap.write(tmp_path, SMALL)
    planted = {lang: {f"K{i}": "x" for i in range(100)} for lang in SMALL}
    found = snap.differences(tmp_path, planted, limit=10)
    assert found[-1].startswith("... ") and found[-1].endswith("more lines") and len(found) == 22


def test_check_prints_the_command_and_exits_1(tmp_path, monkeypatch, capsys):
    snap.write(tmp_path, SMALL)
    monkeypatch.setattr(snap, "SNAPSHOTS", str(tmp_path))
    monkeypatch.setattr(phrases, "TABLE", copy.deepcopy(SMALL))
    assert snap.main(["--check"]) == 0
    monkeypatch.setitem(phrases.TABLE["en"], "BYE", "See you.")
    assert snap.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "+BYE: See you." in err and "python3 runtime/tests/phrase_snapshot.py --write" in err
    assert snap.main(["--write"]) == 0 and snap.main(["--check"]) == 0


def test_the_command_line_needs_a_mode():
    with pytest.raises(SystemExit):
        snap.main([])


# --- strict and lenient (WB_GENERATED_BLOCKS), the same variable as the generated blocks of the platform pages ---------------------------------------------------

def test_strict_fails_on_a_reworded_sentence_and_lenient_passes_it(tmp_path):
    snap.write(tmp_path, SMALL)
    planted = copy.deepcopy(SMALL)
    planted["en"]["BYE"] = "See you."
    strict = snap.problems("strict", tmp_path, planted)
    assert any(line.startswith("+BYE: See you.") for line in strict)
    assert snap.problems("lenient", tmp_path, planted) == []


def test_lenient_passes_an_added_key_and_strict_does_not(tmp_path):
    snap.write(tmp_path, SMALL)
    added = copy.deepcopy(SMALL)
    added["en"]["NEW"] = "New {name}."
    added["pt-BR"]["NEW"] = "Novo {name}."
    assert snap.problems("lenient", tmp_path, added) == []
    assert "+NEW: New Ana Lima." in "\n".join(snap.problems("strict", tmp_path, added))


def test_lenient_still_fails_for_a_snapshot_key_the_table_lacks_a_missing_file_and_an_invalid_sentence(tmp_path):
    snap.write(tmp_path, SMALL)
    removed = copy.deepcopy(SMALL)
    del removed["en"]["BYE"]
    assert snap.problems("lenient", tmp_path, removed) == ["phrases.en.txt: the key BYE is not in the table"]
    bad = copy.deepcopy(SMALL)
    bad["pt-BR"]["BYE"] = "Tchau {0} e {name"
    problems = snap.problems("lenient", tmp_path, bad)
    assert len(problems) == 1 and problems[0].startswith("pt-BR BYE: the sentence cannot be rendered")
    (tmp_path / "phrases.pt-BR.txt").unlink()
    assert snap.problems("lenient", tmp_path, SMALL) == ["phrases.pt-BR.txt: the file does not exist"]


def test_an_unset_or_unknown_mode_is_lenient_and_only_strict_is_strict(tmp_path):
    snap.write(tmp_path, SMALL)
    planted = copy.deepcopy(SMALL)
    planted["en"]["BYE"] = "See you."
    for mode in ("lenient", "", "other"):
        assert snap.problems(mode, tmp_path, planted) == [], mode
    assert snap.problems("strict", tmp_path, planted)


def test_vacuity_a_lenient_check_that_compares_byte_for_byte_would_fail_a_package_that_rewords_a_sentence(tmp_path, monkeypatch):
    """The point of the lenient mode: with the strict comparison in its place, the planted reword (the case of a package's pull request) fails."""
    snap.write(tmp_path, SMALL)
    planted = copy.deepcopy(SMALL)
    planted["en"]["BYE"] = "See you."
    assert snap.problems("lenient", tmp_path, planted) == []
    monkeypatch.setattr(snap, "lenient_problems", snap.differences)
    assert snap.problems("lenient", tmp_path, planted) != []


def test_the_real_table_is_lenient_clean_and_strict_clean_on_this_tree():
    assert snap.problems("lenient") == [] and snap.problems("strict") == []
