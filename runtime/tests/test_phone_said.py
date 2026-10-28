"""T8-1: the phone helpers (runtime/tests/phone_said.py) say what they say.

The oracles are this file's own literals over a small table of its own (swapped in for `phrases.TABLE`), so the helpers are not checked against the wording they will be used on.
The planted cases are the vacuity of the rest: a place that is another sentence, a sentence with another key, and a sentence with another line, each makes the check fail.
"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import phone_said as ps  # noqa: E402
import phrases  # noqa: E402

TABLE = {
    "en": {"PHONE_WHERE": "at the desk", "PHONE_WHERE_LINK": "at the desk: {url}", "PHONE_NOT_ALLOWED": "Not for you. Ask {where}", "PHONE_OTHER": "Other thing {where}", "PLAIN": "Plain."},
    "pt-BR": {"PHONE_WHERE": "na mesa", "PHONE_WHERE_LINK": "na mesa: {url}", "PHONE_NOT_ALLOWED": "Nao para voce. Pergunte {where}", "PHONE_OTHER": "Outra coisa {where}", "PLAIN": "Simples."},
}
EN = {"language": "en"}
PT = {"language": "pt-BR"}


@pytest.fixture(autouse=True)
def small_table(monkeypatch):
    monkeypatch.setattr(phrases, "TABLE", TABLE)


def test_a_sentence_with_the_place_and_a_full_stop_is_placed():
    assert ps.placed("Not for you. Ask at the desk.", "PHONE_NOT_ALLOWED", EN)
    assert ps.placed("Nao para voce. Pergunte na mesa.", "PHONE_NOT_ALLOWED", PT)
    assert ps.refused("Not for you. Ask at the desk.") and ps.refused("Nao para voce. Pergunte na mesa.", PT)
    assert ps.placed("Other thing at the desk.", "PHONE_OTHER", EN)


def test_a_link_is_the_place_and_no_stop_follows_it():
    assert ps.placed("Not for you. Ask at the desk: https://page.example/p", "PHONE_NOT_ALLOWED", EN)
    assert ps.placed("Nao para voce. Pergunte na mesa: https://page.example/p", "PHONE_NOT_ALLOWED", PT)


def test_a_field_not_the_key_the_place_or_the_language_that_is_wrong_fails():
    # vacuity: each planted wrong result makes the check false
    assert not ps.placed("Not for you. Ask at the desk.", "PHONE_OTHER", EN), "another key"
    assert not ps.placed("Not for you. Ask in the cellar.", "PHONE_NOT_ALLOWED", EN), "another place"
    assert not ps.placed("Not for you. Ask at the desk", "PHONE_NOT_ALLOWED", EN), "the stop is missing"
    assert not ps.placed("Nao para voce. Pergunte na mesa.", "PHONE_NOT_ALLOWED", EN), "the other language"
    assert not ps.refused("Other thing at the desk."), "not the refusal"
    assert not ps.refused(None) and not ps.refused(["Not for you. Ask at the desk."])


def test_alone_is_one_line_that_is_the_sentence():
    assert ps.alone("Plain.", "PLAIN", EN) and ps.alone("Simples.", "PLAIN", PT)
    assert not ps.alone("A caption\nPlain.", "PLAIN", EN), "vacuity: `said` alone finds the line, `alone` refuses the caption"
    assert not ps.alone("Plain.\nPlain.", "PLAIN", EN) and not ps.alone("Simples.", "PLAIN", EN) and not ps.alone(None, "PLAIN", EN)
