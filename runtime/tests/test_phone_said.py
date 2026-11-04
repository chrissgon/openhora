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
import phone_errors  # noqa: E402
import phone_said as ps  # noqa: E402
import phrases  # noqa: E402

REAL_TABLE = phrases.TABLE      # the project's own table, kept before the small one below is swapped in

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


# AF-2: the net of `phone_errors.safe` over the real table. A template whose own text is almost all fields (`{name} ({detail})`, `{n}. {title}`) matches any English text that ends in a
# parenthesis or starts with a number, so it must not be a witness that a text was said in Portuguese already.
@pytest.fixture
def real_table(monkeypatch):
    monkeypatch.setattr(phrases, "TABLE", REAL_TABLE)
    phone_errors._said_already.cache_clear()
    yield
    phone_errors._said_already.cache_clear()


LEAKS = (
    "that event is not on this calendar any more (it was removed, or it is on another calendar)",
    "Something failed (code 7)",
    "1. Some English text",
)


@pytest.mark.parametrize("english", LEAKS)
def test_english_that_ends_in_a_parenthesis_or_starts_with_a_number_is_not_taken_for_portuguese(real_table, english):
    assert not phone_errors.spoken(english, PT)
    assert phone_errors.safe(english, PT) == phrases.phone("PHONE_FAILED", PT)


def test_a_template_with_enough_literal_letters_is_still_a_witness(real_table):
    assert phone_errors.spoken("Conta: Gmail (pessoa@example.com)", PT)
    assert phone_errors.safe("Conta: Gmail (pessoa@example.com)", PT) == "Conta: Gmail (pessoa@example.com)"


def test_a_sentence_with_no_field_or_a_localized_letter_is_still_said_in_the_language(real_table):
    assert phone_errors.spoken("Sim", PT) and phone_errors.spoken("Não consegui abrir (agora)", PT)      # validate: allow english-only -- a Portuguese phrase is the input under test


def test_english_is_untouched_on_an_english_phone(real_table):
    assert phone_errors.safe(LEAKS[0], EN) == LEAKS[0]


def test_vacuity_with_the_threshold_at_zero_the_leak_is_back(real_table, monkeypatch):
    monkeypatch.setattr(phone_errors, "WITNESS_LETTERS", 0)
    phone_errors._said_already.cache_clear()
    for english in LEAKS:
        assert phone_errors.spoken(english, PT), english
        assert phone_errors.safe(english, PT) == english
