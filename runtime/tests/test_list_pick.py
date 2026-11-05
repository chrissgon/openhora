"""LP-1: a row of a list named by an ordinal word or by a value the list shows (runtime/list_pick.py, the words in runtime/registry/list_pick_words.json).

`read` turns a WHOLE line into one closed form or into None; `choose` decides which row of the list, as printed, the form names. Both are pure. Every expectation is a literal of this file
(the lines, the rows, the verdicts); the oracle is `mismatches`, a table walked row by row, and each rule has a vacuity test that plants the wrong result and shows the oracle fails.
The rows are the ones of the corpus list (printed numbers 2 and 4, not 1 and 2), a Monday and a Wednesday list for the weekday words, and a list of one Friday. Offline; no name is a
real one.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_list_pick.py
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import list_pick  # noqa: E402

D = datetime.date
THU, FRI = D(2026, 10, 22), D(2026, 10, 23)


def row(n, day, start, position, account=None):
    return {"n": n, "day": day.isoformat() if day else None, "start": start, "account": account, "position": position}


# The list of the corpus: "2. Thu 22/10 13:00-14:00 · title" and "4. Fri 23/10 13:00-14:00 · title"
CORPUS = [row(2, THU, "13:00", 1), row(4, FRI, "13:00", 2)]
# Two meetings of one day: 10:00 and 15:00, printed 3 and 5
MEETINGS = [row(3, FRI, "10:00", 1), row(5, FRI, "15:00", 2)]
MON, TUE, WED = D(2026, 10, 19), D(2026, 10, 20), D(2026, 10, 21)
ANSWERS = {"sexta": ("weekday", 4), "friday": ("weekday", 4), "segunda": ("weekday", 0), "quarta": ("weekday", 2), "quinta": ("weekday", 3), "dia 22": ("day", THU), "dia 23": ("day", FRI),
           "amanha": ("day", FRI), "tomorrow": ("day", FRI)}


def day_of(text):
    """The day engine, stood in with the answers this file needs (the real one is event_lookup._day_named, run in test_event_list_pick.py)."""
    return ANSWERS.get(text, ("none", None))


def verdict(line, rows, more=False):
    form = list_pick.read(line)
    assert form is not None, line
    return list_pick.choose(form, rows, day_of, more)


# --- read -----------------------------------------------------------------------------------------------------------------------------------------------

FORMS = [
    ("a última", {"kind": "last"}), ("o último", {"kind": "last"}), ("the last one", {"kind": "last"}), ("last", {"kind": "last"}), ("A ÚLTIMA!", {"kind": "last"}),
    ("a primeira", {"kind": "ordinal", "position": 1}), ("o primeiro", {"kind": "ordinal", "position": 1}), ("o segundo", {"kind": "ordinal", "position": 2}),
    ("the second one", {"kind": "ordinal", "position": 2}), ("third", {"kind": "ordinal", "position": 3}), ("a terceira da lista", {"kind": "ordinal", "position": 3}),
    ("o décimo", {"kind": "ordinal", "position": 10}), ("a primeira, por favor", {"kind": "ordinal", "position": 1}), ("the first please", {"kind": "ordinal", "position": 1}),
    ("a das 15h", {"kind": "clock", "readings": ["15:00"]}), ("a das 15h30", {"kind": "clock", "readings": ["15:30"]}), ("o das 15:30", {"kind": "clock", "readings": ["15:30"]}),
    ("the one at 3pm", {"kind": "clock", "readings": ["15:00"]}), ("the one at 3 pm", {"kind": "clock", "readings": ["15:00"]}),
    ("a das 3", {"kind": "clock", "readings": ["03:00", "15:00"]}), ("a das 15", {"kind": "clock", "readings": ["15:00"]}), ("a de 15h", {"kind": "clock", "readings": ["15:00"]}),
    ("a das 12", {"kind": "clock", "readings": ["12:00"]}), ("a das 15 horas", {"kind": "clock", "readings": ["15:00"]}),
    ("a de amanhã", {"kind": "words", "words": ["amanha"]}), ("a do dia 22", {"kind": "words", "words": ["dia", "22"]}), ("the one on friday", {"kind": "words", "words": ["friday"]}),  # validate: allow english-only -- the Portuguese lines under test
    ("o do outlook", {"kind": "account", "account": "microsoft"}), ("a do google", {"kind": "account", "account": "google"}),
    ("o do banco", {"kind": "words", "words": ["banco"]}), ("o da ana", {"kind": "words", "words": ["ana"]}), ("the one from ana", {"kind": "words", "words": ["ana"]}),
    ("a segunda", {"kind": "ordinal", "position": 2, "weekday": True}), ("a sexta", {"kind": "ordinal", "position": 6, "weekday": True}),
]
NOT_FORMS = ["", "   ", "15h", "às 15h", "as 15h", "a das 15h e muda pra 17h", "os dois últimos", "both", "aprovo a segunda", "a reunião das 15h", "o 2", "2", "cancela", "a das 25h",  # validate: allow english-only -- the Portuguese lines under test
             "a das 15h30 e 20h", "the one at", "o do", "a das", "o primeiro e o segundo", "oi", "a última, e agora?", "sim", "a de um dois três quatro cinco seis"]


@pytest.mark.parametrize("line, wanted", FORMS)
def test_a_whole_line_that_names_a_row_is_read_as_one_closed_form(line, wanted):
    form = list_pick.read(line)
    assert form is not None, line
    assert {key: form[key] for key in wanted} == wanted, line


@pytest.mark.parametrize("line", NOT_FORMS)
def test_a_line_that_is_more_or_less_than_a_closed_form_is_no_pick(line):
    assert list_pick.read(line) is None, line


def test_a_verb_and_a_pick_are_one_form_and_the_verb_is_the_calendars():
    cancel, change = list_pick.read("cancela a última"), list_pick.read("muda a das 15h")
    assert cancel["verb"] == "cancel" and cancel["kind"] == "last" and cancel["head"].split()[0] == "cancela"
    assert change["verb"] == "change" and change["kind"] == "clock" and change["head"].split()[0] == "muda"
    assert list_pick.read("a última")["verb"] is None and list_pick.read("a última")["head"] is None
    assert list_pick.read("por favor, cancela a primeira, por favor")["verb"] == "cancel"
    assert list_pick.read("apaga o segundo")["position"] == 2


def test_a_clock_with_no_lead_is_never_a_pick_so_that_a_new_time_after_a_list_is_not_a_row():
    for line in ("15h", "às 15h", "as 15h", "3pm", "10:00", "para as 17h", "muda para as 17h"):
        assert list_pick.read(line) is None, line


def test_the_hour_with_no_marker_has_two_readings_and_one_with_a_marker_or_after_noon_has_one():
    assert list_pick.read("a das 3")["readings"] == ["03:00", "15:00"]
    assert list_pick.read("a das 03h")["readings"] == ["03:00"]
    assert list_pick.read("a das 11")["readings"] == ["11:00", "23:00"]
    assert list_pick.read("a das 3pm")["readings"] == ["15:00"]
    assert list_pick.read("a das 0h")["readings"] == ["00:00"]


# --- choose ---------------------------------------------------------------------------------------------------------------------------------------------

# (line, rows, more, the verdict the oracle wants): the rows are indexes into the list as printed
CASES = [
    ("o primeiro", CORPUS, False, ("one", 0, None)),
    ("a primeira", CORPUS, False, ("one", 0, None)),
    ("a última", CORPUS, False, ("one", 1, None)),
    ("the last one", CORPUS, False, ("one", 1, None)),
    ("o segundo", CORPUS, False, ("ask", "ordinal-clash", {"n": 2, "position": 2, "m": 4})),
    ("the second one", CORPUS, False, ("ask", "ordinal-clash", {"n": 2, "position": 2, "m": 4})),
    ("a das 13h", CORPUS, False, ("several", [0, 1], ("clock", "13:00"))),
    ("a das 17h", CORPUS, False, ("none", None, ("clock", "17:00"))),
    ("a de sexta", CORPUS, False, ("one", 1, None)),
    ("the one on friday", CORPUS, False, ("one", 1, None)),
    ("a do dia 22", CORPUS, False, ("one", 0, None)),
    ("o terceiro", CORPUS, False, ("none", None, ("ordinal", 3))),
    ("a de amanhã", CORPUS, False, ("one", 1, None)),  # validate: allow english-only -- the Portuguese lines under test
    ("a de quinta", CORPUS, False, ("one", 0, None)),
    ("a de sábado", CORPUS, False, "skip"),
    ("o do banco", CORPUS, False, "skip"),
    ("a das 10h", MEETINGS, False, ("one", 0, None)),
    ("a das 15h", MEETINGS, False, ("one", 1, None)),
    ("a das 3", MEETINGS, False, ("one", 1, None)),
    ("a das 10", MEETINGS, False, ("one", 0, None)),
    ("a das 12h", MEETINGS, False, ("none", None, ("clock", "12:00"))),
    ("a primeira", MEETINGS, False, ("one", 0, None)),
    ("o segundo", MEETINGS, False, ("one", 1, None)),
    # more rows exist than were printed
    ("a última", CORPUS, True, ("ask", "last-not-shown", None)),
    ("o primeiro", CORPUS, True, ("one", 0, None)),
    ("o quarto", CORPUS, True, ("ask", "last-not-shown", None)),
    # the accounts of the rows
    ("o do outlook", [row(2, THU, "09:00", 1, "google"), row(4, THU, "11:00", 2, "microsoft")], False, ("one", 1, None)),
    ("o do google", [row(2, THU, "09:00", 1, "google"), row(4, THU, "11:00", 2, "google")], False, ("several", [0, 1], ("account", "google"))),
    ("o do outlook", [row(2, THU, "09:00", 1, "google")], False, ("none", None, ("account", "microsoft"))),
    # a list with no positions (several sections): an ordinal says nothing
    ("a última", [row(2, THU, "09:00", None), row(4, THU, "11:00", None)], False, "skip"),
    ("a das 11h", [row(2, THU, "09:00", None), row(4, THU, "11:00", None)], False, ("one", 1, None)),
    # a row with no start is never taken for a clock
    ("a das 9h", [row(2, THU, None, 1), row(4, THU, "09:00", 2)], False, ("one", 1, None)),
    # rule 5: W the weekday reading, P the position reading
    ("a segunda", [row(1, MON, "10:00", 1), row(2, WED, "15:00", 2)], False, ("ask", "day-or-position", {"position": 2, "a": [1], "b": [2]})),
    ("a segunda", [row(1, TUE, "10:00", 1), row(2, WED, "15:00", 2)], False, ("one", 1, None)),
    ("a segunda", [row(1, MON, "10:00", 1), row(2, MON, "15:00", 2)], False, ("ask", "day-or-position", {"position": 2, "a": [1, 2], "b": [2]})),
    ("a segunda", [row(1, TUE, "10:00", 1), row(2, MON, "15:00", 2)], False, ("one", 1, None)),
    ("a sexta", [row(7, FRI, "10:00", 1)], False, ("one", 0, None)),
    ("a sexta", [row(7, THU, "10:00", 1)], False, ("none", None, ("ordinal", 6))),
    ("a quarta", [row(1, TUE, "10:00", 1), row(2, TUE, "11:00", 2), row(3, TUE, "12:00", 3), row(4, WED, "13:00", 4)], False, ("one", 3, None)),
    ("a quarta", [row(1, TUE, "10:00", 1), row(2, WED, "11:00", 2), row(3, TUE, "12:00", 3), row(4, TUE, "13:00", 4)], False, ("ask", "day-or-position", {"position": 4, "a": [2], "b": [4]})),
    ("a quarta", [row(1, MON, "10:00", 1)], True, ("ask", "last-not-shown", None)),
]


def normal(found):
    return found if isinstance(found, str) else tuple(found)


def mismatches(choose=list_pick.choose):
    """The cases whose verdict is not the wanted one (the oracle: a table of this file)."""
    out = []
    for line, rows, more, wanted in CASES:
        form = list_pick.read(line)
        got = choose(form, rows, day_of, more) if form is not None else None
        if got is None:
            out.append((line, "not read"))
        elif wanted == "skip":
            if got[0] != "skip":
                out.append((line, got))
        elif tuple(got) != tuple(wanted):
            out.append((line, got))
    return out


def test_every_case_of_the_table_is_decided_as_the_table_says():
    assert mismatches() == []


def test_the_corpus_list_asks_for_the_second_and_never_opens_the_row_numbered_four_silently():
    got = verdict("o segundo", CORPUS)
    assert got[0] == "ask" and got[1] == "ordinal-clash", "the printed number 2 is the first row: a position 2 is not the number 2"
    assert got[2] == {"n": 2, "position": 2, "m": 4}


def test_what_a_number_means_wins_only_when_a_different_row_prints_it():
    rows = [row(1, THU, "13:00", 1), row(2, FRI, "13:00", 2)]          # a list whose printed numbers are its positions: no clash
    assert verdict("o segundo", rows) == ("one", 1, None)
    rows = [row(3, THU, "13:00", 1), row(2, FRI, "13:00", 2)]          # the second row prints 2 itself: the position and the number are the same row
    assert verdict("o segundo", rows) == ("one", 1, None)


def test_a_weekday_word_and_the_position_agree_or_one_of_them_is_missing_or_the_person_is_asked():
    assert verdict("a segunda", [row(1, MON, "10:00", 1), row(2, WED, "15:00", 2)])[:2] == ("ask", "day-or-position")
    assert verdict("a segunda", [row(1, TUE, "10:00", 1), row(2, WED, "15:00", 2)])[:2] == ("one", 1)
    assert verdict("a segunda", [row(1, TUE, "10:00", 1), row(2, MON, "15:00", 2)])[:2] == ("one", 1)
    assert verdict("a sexta", [row(7, FRI, "10:00", 1)])[:2] == ("one", 0)


def test_an_ordinal_and_last_are_read_by_position_in_the_printed_list_not_by_the_snapshot_number():
    rows = [row(9, THU, "13:00", 1), row(12, FRI, "13:00", 2), row(30, FRI, "15:00", 3)]
    assert verdict("o primeiro", rows)[:2] == ("one", 0)
    assert verdict("a última", rows)[:2] == ("one", 2)
    assert verdict("a terceira", rows)[:2] == ("one", 2)


def test_the_words_of_an_address_are_the_local_part_and_the_domain_without_its_last_label():
    assert list_pick.address_words("avisos@banco-aurora.example · Fatura") == {"avisos", "banco", "aurora"}
    assert list_pick.address_words("ana.lima@estudio-norte.example · Orçamento") == {"ana", "lima", "estudio", "norte"}  # validate: allow english-only -- the Portuguese lines under test
    assert list_pick.address_words("sem endereço · assunto") == set()  # validate: allow english-only -- the Portuguese lines under test
    assert "orcamento" not in list_pick.address_words("ana@estudio.example · Orçamento"), "the subject is not read"  # validate: allow english-only -- the Portuguese lines under test


def test_help_is_printed_and_a_bad_call_is_refused(capsys):
    assert list_pick.main(["--help"]) == 0 and "ordinal" in capsys.readouterr().out
    assert list_pick.main([]) == 2


# --- vacuity: each rule removed shows the oracle can fail ----------------------------------------------------------------------------------------------------


def test_vacuity_without_the_clash_rule_the_second_picks_row_four_and_the_oracle_sees_it(monkeypatch):
    monkeypatch.setattr(list_pick, "_clash", lambda rows, place: [])
    wrong = mismatches()
    assert any(line in ("o segundo", "the second one") for line, _ in wrong), wrong
    assert verdict("o segundo", CORPUS)[:2] == ("one", 1), "the planted rule opens row 4 silently"


def test_vacuity_without_the_weekday_rule_a_segunda_picks_the_second_row_and_the_oracle_sees_it(monkeypatch):
    def position_only(form, rows, day_of, more):
        found, detail = list_pick._position(form, rows, more)
        return list_pick._from_position(form, found, detail)
    monkeypatch.setattr(list_pick, "_weekday_or_position", position_only)
    wrong = mismatches()
    assert any(line == "a segunda" for line, _ in wrong), wrong


def test_vacuity_a_choose_that_returns_the_first_match_fails_the_several_cases():
    def first_match(form, rows, day_of_=None, more=False):
        got = list_pick.choose(form, rows, day_of_, more)
        return ("one", got[1][0], None) if got[0] == "several" else got
    wrong = mismatches(first_match)
    assert any(line == "a das 13h" for line, _ in wrong), wrong


def test_vacuity_a_choose_that_ignores_more_fails_the_last_not_shown_case():
    def ignores_more(form, rows, day_of_=None, more=False):
        return list_pick.choose(form, rows, day_of_, False)
    assert any(line == "a última" for line, _ in mismatches(ignores_more))


def test_vacuity_a_reader_that_takes_a_clock_with_no_lead_is_seen_by_the_negative_table(monkeypatch):
    real = list_pick.read
    monkeypatch.setattr(list_pick, "read", lambda said: real("a das " + said) if said == "15h" else real(said))
    assert [line for line in NOT_FORMS if list_pick.read(line) is not None] == ["15h"], "the planted reader reads them: the table sees it"
