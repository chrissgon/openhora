"""The time parser of natural requests (package NR-1, runtime/natural_time.py) and its language tables (runtime/natural_lang_*.py): what time a line means, with a
fixed clock, in Portuguese and in English; the readings it offers when a line can be read two ways; the days and hours it asks about and never invents; the
checks `reminders.resolve` keeps (a time that has passed, a wall time the clock skips) over a clock change; and the rule that a language is data: a stub third
language plugs in with no edit of the engine, and the engine itself holds no word of any language. Offline, no model, no network, no store; invented words.

The Portuguese lines are in natural_cases_pt_br.py, the one test file written in Portuguese on purpose.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_time.py
"""
from __future__ import annotations

import ast
import datetime
import re

import pytest

import standin_tree as st
from natural_cases_pt_br import PARSER_CASES, PARSER_CLOCK

nt = st.load("natural_time")
rm = st.load("reminders")

BRT = datetime.timezone(datetime.timedelta(hours=-3), "BRT")


def clock(wall=PARSER_CLOCK, zone=BRT):
    return datetime.datetime.strptime(wall, "%Y-%m-%d %H:%M").replace(tzinfo=zone)


def outcome(line, now=None):
    """The parse of a line in the shape the cases are written in."""
    got = nt.parse(line, now or clock())
    if got is None:
        return None
    if "when" in got:
        return got["when"]
    if "ask" in got:
        return ("ask", [r["when"] for r in got["ask"]])
    assert got["missing"] == "time"
    return "missing"


# English lines, the same clock: Thursday 2026-10-22 14:00 at -03:00. Tomorrow is Friday the 23rd.
ENGLISH_CASES = [
    ("tomorrow at 3pm", "2026-10-23 15:00"),
    ("tomorrow 3 pm", "2026-10-23 15:00"),
    ("1pm", "13:00"),
    ("1 pm", "13:00"),
    ("1:30pm", "13:30"),
    ("9am", "09:00"),
    ("12am", "00:00"),
    ("12pm", "12:00"),
    ("noon", "12:00"),
    ("midnight", "00:00"),
    ("tomorrow noon", "2026-10-23 12:00"),
    ("9 in the morning", "09:00"),
    ("7 in the evening", "19:00"),
    ("at 3:30pm", "15:30"),
    ("13:00", "13:00"),
    ("at 15", "15:00"),
    ("at 9", ("ask", ["09:00", "21:00"])),
    ("friday at 9", ("ask", ["2026-10-23 09:00", "2026-10-23 21:00"])),
    ("in 2 hours", "in 2h"),
    ("within 2 hours", "in 2h"),
    ("in 30 minutes", "in 30m"),
    ("in 3 days", "in 3d"),
    ("in an hour", "in 1h"),
    ("in half an hour", "in 30m"),
    ("in 1 week", "in 7d"),
    ("friday at 9am", "2026-10-23 09:00"),
    ("next friday 9am", "2026-10-23 09:00"),
    ("next thursday 10am", "2026-10-29 10:00"),
    ("thursday 3pm", "2026-10-22 15:00"),
    ("thursday 1pm", "2026-10-29 13:00"),
    ("on monday at 8am", "2026-10-26 08:00"),
    ("this saturday 11am", "2026-10-24 11:00"),
    ("the day after tomorrow at 10:00", "2026-10-24 10:00"),
    ("today at 6pm", "2026-10-22 18:00"),
    ("on the 25th at 5pm", "2026-10-25 17:00"),
    ("the 10th at 9am", "2026-11-10 09:00"),
    ("october 25 2pm", "2026-10-25 14:00"),
    ("25 october 2pm", "2026-10-25 14:00"),
    ("oct 25th at 2pm", "2026-10-25 14:00"),
    ("jan 5 at 9am", "2027-01-05 09:00"),
    ("25/10 at 10:00", "2026-10-25 10:00"),
    ("10/25 at 10:00", "2026-10-25 10:00"),
    ("2026-10-25 08:00", "2026-10-25 08:00"),
    ("tomorrow", "missing"),
    ("later", "missing"),
    ("tonight", "missing"),
    ("this afternoon", "missing"),
    ("friday morning", "missing"),
    ("nothing in this line", None),
    ("remind me", None),
]
# A date written x/y with both numbers 12 or less is asked back in an English line (month first or day first) and is day first in a Portuguese one.
ENGLISH_SLASH = ("5/6 at 10:00", ("ask", ["2027-06-05 10:00", "2027-05-06 10:00"]))


@pytest.mark.parametrize("line,expected", PARSER_CASES)
def test_portuguese_lines_mean_what_a_person_means(line, expected):
    assert outcome(line) == expected


@pytest.mark.parametrize("line,expected", ENGLISH_CASES + [ENGLISH_SLASH])
def test_english_lines_mean_what_a_person_means(line, expected):
    assert outcome(line) == expected


def test_there_are_at_least_eighty_phrases_in_the_two_languages():
    assert len(PARSER_CASES) + len(ENGLISH_CASES) + 1 >= 80


def test_a_time_with_an_h_is_24_hour_and_an_hour_with_nothing_is_asked_never_guessed():
    assert outcome("13hrs") == "13:00" and outcome("9h") == "09:00" and outcome("9:30") == "09:30", "Brazil writes 24-hour with an h"
    for line in ("at 9", "at 3", "at 11"):
        got = nt.parse(line, clock())
        assert [r["time"] for r in got["ask"]] == [f"{int(re.search(r'[0-9]+', line).group()):02d}:00", f"{int(re.search(r'[0-9]+', line).group()) + 12:02d}:00"], line
    assert outcome("at 12") == "12:00" and outcome("at 0") == "00:00" and outcome("at 23") == "23:00"
    assert nt.parse("at 25", clock()) is None, "not an hour"


def test_a_day_with_no_hour_and_a_vague_time_ask_and_never_get_a_default_hour():
    got = nt.parse("tomorrow", clock())
    assert got["missing"] == "time" and got["day"]["date"] == "2026-10-23" and got["day"]["rel"] == 1 and got["day"]["weekday"] == 4
    assert nt.parse("friday", clock())["day"]["date"] == "2026-10-23"
    assert nt.parse("thursday", clock())["day"] is None, "the same weekday as today: today or in 7 days depends on the hour, which is not known"
    assert nt.parse("later", clock())["day"] is None
    assert "when" not in nt.parse("tomorrow morning", clock()) and "ask" not in nt.parse("tomorrow morning", clock())


def test_a_reading_carries_the_day_the_time_the_weekday_and_whether_it_rolled_over():
    got = nt.parse("13h", clock())
    assert got["when"] == "13:00" and got["reading"] == {"when": "13:00", "date": "2026-10-23", "time": "13:00", "rel": 1, "weekday": 4, "rolled": True, "relative": None}
    ahead = nt.parse("15h", clock())["reading"]
    assert ahead["date"] == "2026-10-22" and ahead["rel"] == 0 and ahead["rolled"] is False
    dated = nt.parse("on the 25th at 5pm", clock())["reading"]
    assert dated["when"] == "2026-10-25 17:00" and dated["weekday"] == 6 and dated["rel"] == 3 and dated["rolled"] is False
    relative = nt.parse("in 2 hours", clock())["reading"]
    assert relative["relative"] == "in 2h" and relative["date"] == "2026-10-22" and relative["time"] == "16:00"
    seconds = nt.parse("in 2 hours", clock() + datetime.timedelta(seconds=30))["reading"]
    assert seconds["time"] == "16:01", "to the minute, upwards, as resolve does"


def test_two_readings_are_all_offered_up_to_four_and_nothing_is_picked():
    got = nt.parse("tomorrow 9h or 10h or 11h or 12h or 13h", clock())
    assert len(got["ask"]) == nt.MAX_READINGS == 4
    assert nt.parse("9h 9h", clock())["when"] == "09:00", "the same time twice is one reading"
    both = nt.parse("tomorrow 9h in 2 hours", clock())
    assert [r["when"] for r in both["ask"]] == ["in 2h", "2026-10-23 09:00"]


def test_the_spans_are_those_of_the_original_line_whatever_the_accents_and_the_hyphens():
    line = "Corte de cabelo às 13hrs amanhã, por favor"      # validate: allow english-only -- a Portuguese line, the case of the parser
    got = nt.parse(line, clock())
    assert nt.without(line, got["spans"]) == "Corte de cabelo , por favor"
    assert nt.without("remind me tomorrow at 1 pm to call", nt.parse("remind me tomorrow at 1 pm to call", clock())["spans"]) == "remind me to call"
    folded, origin = nt.normalise("Sexta-Feira à noite")      # validate: allow english-only -- a Portuguese line, the case of the parser
    assert folded == "sexta feira a noite" and len(origin) == len(folded)
    assert nt.parse("no time phrase", clock()) is None


def test_the_phrases_found_have_no_clock_and_say_which_language_found_them():
    found = nt.find("tomorrow at 3pm", None)
    assert [h["kind"] for h in found["hits"]] == ["date", "clock"] and {h["lang"] for h in found["hits"]} == {"en"}
    assert nt.find("hello there")["hits"] == []
    assert all("lang" in h for h in nt.find("amanhã 9h or friday 3pm")["hits"])      # validate: allow english-only -- a Portuguese line, the case of the parser


# --- the checks resolve keeps over what the parser says ------------------------------------------------------------------------------------------------


def resolve(when, now, zone):
    return rm.resolve(when, now, lambda naive: naive.replace(tzinfo=zone))


def test_a_time_that_has_passed_today_means_tomorrow_and_a_day_that_has_passed_is_refused_by_resolve():
    now = clock()
    assert resolve(nt.parse("13h", now)["when"], now, BRT)["wall"] == "2026-10-23T13:00"
    with pytest.raises(ValueError) as e:
        resolve(nt.parse("today at 1pm", now)["when"], now, BRT)
    assert str(e.value) == "That time has passed. Now it is 2026-10-22 14:00."
    with pytest.raises(ValueError) as e:
        resolve(nt.parse("30/02 10h", now)["when"], now, BRT)
    assert str(e.value) == "2027-02-30 is not a day of the calendar."
    with pytest.raises(ValueError):
        resolve(nt.parse("in 2000 days", now)["when"], now, BRT)


def lisbon():
    zoneinfo = pytest.importorskip("zoneinfo")
    try:
        return zoneinfo.ZoneInfo("Europe/Lisbon")
    except zoneinfo.ZoneInfoNotFoundError:
        pytest.skip("this machine has no time zone database")


def test_across_the_october_clock_change_the_first_of_two_occurrences_is_meant_and_the_hour_after_is_normal():
    zone = lisbon()
    now = clock("2026-10-24 12:00", zone)                 # Saturday; the clocks go back at 02:00 on Sunday the 25th
    twice = nt.parse("tomorrow at 01:30", now)
    assert twice["when"] == "2026-10-25 01:30"
    due = resolve(twice["when"], now, zone)["due"]
    assert due.utcoffset() == datetime.timedelta(hours=1), "01:30 happens twice that night; the first is meant"
    after = resolve(nt.parse("tomorrow at 02:30", now)["when"], now, zone)["due"]
    assert after.utcoffset() == datetime.timedelta(0)
    assert resolve(nt.parse("sunday 8h", now)["when"], now, zone)["wall"] == "2026-10-25T08:00"


def test_across_the_march_clock_change_a_wall_time_the_clock_skips_is_refused_by_resolve_not_guessed_here():
    zone = lisbon()
    now = clock("2027-03-27 12:00", zone)                 # Saturday; the clocks go forward at 01:00 on Sunday the 28th
    skipped = nt.parse("tomorrow at 01:30", now)
    assert skipped["when"] == "2027-03-28 01:30"
    with pytest.raises(ValueError) as e:
        resolve(skipped["when"], now, zone)
    assert str(e.value) == "2027-03-28 01:30 does not exist on that day (the clock skips it). Pick another time."
    assert resolve(nt.parse("tomorrow at 02:30", now)["when"], now, zone)["wall"] == "2027-03-28T02:30"


def test_a_time_of_day_that_has_passed_today_is_tomorrow_even_on_the_day_the_clock_changes():
    zone = lisbon()
    now = clock("2026-10-25 12:00", zone)
    got = nt.parse("9h", now)
    assert got["when"] == "09:00" and got["reading"]["date"] == "2026-10-26" and got["reading"]["rolled"] is True
    assert resolve(got["when"], now, zone)["wall"] == "2026-10-26T09:00"


# --- a language is data ---------------------------------------------------------------------------------------------------------------------------


STUB = {      # an invented language: "morgen" is tomorrow, "heute" today, and an hour written "7u" is a 24-hour clock
    "tag": "xx", "markers": ["bitte"], "slash_dates": "day-first",
    "days": {"today": ["heute"], "tomorrow": ["morgen"], "day_after_tomorrow": ["uebermorgen"]},
    "weekdays": [["montag"], ["dienstag"], ["mittwoch"], ["donnerstag"], ["freitag"], ["samstag"], ["sonntag"]],
    "weekday_next": ["naechsten"], "weekday_this": [], "months": [[f"monat{n}"] for n in range(1, 13)], "month_joiners": [], "day_words": [], "ordinal_prefixes": [],
    "ordinal_suffixes": [], "prefixes": ["um", "am"], "hour_words_24": ["u"], "meridiem": {"am": [], "pm": []},
    "dayparts": {"morning": [], "dawn": [], "afternoon": [], "evening": [], "night": []}, "vague": ["spaeter"], "noon": ["mittag"], "midnight": [],
    "bare_hour_prefixes": ["um"], "relative_in": ["in"], "relative_units": {"m": ["min"], "h": ["std"], "d": ["tagen"], "w": []}, "number_words": {"ein": 1},
    "half_hour": [], "triggers": {"remind": ["erinnere mich"], "reminders": [], "calendar": [], "calendar_loose": [], "note": []},
    "forget": {"verbs": [], "nouns": [], "fillers": []}, "polite": [], "connectors": ["an"], "answers": {"yes": ["ja"], "notice": [], "event": []},
    "work_starters": [],
}


def test_a_third_language_plugs_in_as_a_table_with_no_edit_of_the_engine():
    nt.check_table(STUB)
    now = clock()
    assert nt.parse("morgen 7u", now, [STUB])["when"] == "2026-10-23 07:00"
    assert nt.parse("uebermorgen mittag", now, [STUB])["when"] == "2026-10-24 12:00"
    assert nt.parse("naechsten donnerstag 9u", now, [STUB])["when"] == "2026-10-29 09:00"
    assert nt.parse("in 30 min", now, [STUB])["when"] == "in 30m"
    assert nt.parse("spaeter", now, [STUB])["missing"] == "time"
    assert nt.parse("um 9", now, [STUB])["ask"][1]["time"] == "21:00"
    assert nt.parse("morgen 7u", now) is None, "the shipped tables know nothing of the stub"
    both = nt.languages() + [STUB]
    assert nt.parse("morgen 7u", now, both)["when"] == "2026-10-23 07:00", "and every table is tried on every line: a line in the stub's words with the shipped ones"
    assert nt.parse("tomorrow 7u", now, both)["when"] == "2026-10-23 07:00", "even half of a line in each"


def test_a_table_file_dropped_in_the_folder_is_found_and_checked(tmp_path):
    (tmp_path / "natural_lang_xx.py").write_text("TABLE = " + repr(STUB) + "\n", encoding="utf-8")
    (tmp_path / "natural_lang_en.py").write_text((st.RUNTIME / "natural_lang_en.py").read_text(encoding="utf-8"), encoding="utf-8")
    found = nt.load_languages(str(tmp_path))
    assert [t["tag"] for t in found] == ["en", "xx"]
    assert nt.parse("morgen 7u", clock(), found)["when"] == "2026-10-23 07:00" and nt.parse("tomorrow 7pm", clock(), found)["when"] == "2026-10-23 19:00"
    (tmp_path / "natural_lang_bad.py").write_text("TABLE = {'tag': 'bad'}\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        nt.load_languages(str(tmp_path))
    assert "language table 'bad'" in str(e.value)


def test_the_shipped_tables_follow_the_schema_and_a_table_that_breaks_it_is_refused():
    assert [t["tag"] for t in nt.languages()] == ["en", "pt-BR"]
    for table in nt.languages():
        nt.check_table(table)
    for broken, why in (({**STUB, "tag": ""}, "tag"), ({**STUB, "slash_dates": "maybe"}, "slash_dates"), ({**STUB, "weekdays": [["a"]]}, "weekdays"),
                        ({**STUB, "vague": ["Spaeter"]}, "vague"), ({**STUB, "vague": ["später"]}, "vague"), ({**STUB, "vague": ["two  spaces"]}, "vague"),
                        ({**STUB, "days": {"today": []}}, "days"), ({**STUB, "number_words": {"ein": 0}}, "number_words"),
                        ({k: v for k, v in STUB.items() if k != "markers"}, "markers"), ("not a table", "dict")):
        with pytest.raises(ValueError) as e:
            nt.check_table(broken)
        assert why in str(e.value), (why, str(e.value))


def flatten(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from flatten(item)
    elif isinstance(value, list):
        for item in value:
            yield from flatten(item)


def test_the_engine_holds_no_word_of_any_language_and_no_import_of_the_runtime():
    """Every word of a table is data: no string of the engine (a docstring aside) is one. The words of the Portuguese table that English does not also hold
    are the check, since the engine's own sentences are English."""
    source = (st.RUNTIME / "natural_time.py").read_text(encoding="utf-8")
    english = {w for phrase in flatten(nt.languages()[0]) for w in phrase.split()}
    words = {w for phrase in flatten({k: v for k, v in nt.languages()[1].items() if k not in ("tag", "slash_dates")}) for w in phrase.split()} - english
    tree = ast.parse(source)
    docstrings = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]
    found = sorted(w for w in words if len(w) > 2 and any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text) for text in strings))
    assert len(words) > 100 and found == [], "a word of a language is data in a table, not in the engine"
    imports = set(re.findall(r"^\s*(?:import|from)\s+(\w+)", source, re.M))
    assert imports <= {"__future__", "calendar", "datetime", "glob", "importlib", "os", "re", "sys", "unicodedata"}, imports
