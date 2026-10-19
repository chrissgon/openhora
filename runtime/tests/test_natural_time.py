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
import json
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
    ("next friday 9am", ("ask", ["2026-10-23 09:00", "2026-10-30 09:00"])),
    ("next thursday 10am", ("ask", ["2026-10-29 10:00", "2026-11-05 10:00"])),
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
    ("in 1h30", "in 90m"),
    ("in an hour and a half", "in 90m"),
    ("in 1 hour 30 minutes", "in 90m"),
    ("in 2 days at 9", ("ask", ["2026-10-24 09:00", "2026-10-24 21:00"])),
    ("at 9.30", "09:30"),
    ("at midnight", "00:00"),
    ("friday at midnight", ("ask", ["2026-10-23 00:00", "2026-10-24 00:00"])),
    ("remind me fri 3pm", "2026-10-23 15:00"),
    ("fri 3pm", "2026-10-23 15:00"),
    ("I may 2 people", None),
    ("sex ed class", None),
    ("installment 3/10 tomorrow 9am", "2026-10-23 09:00"),
    ("3/10 of the rent tomorrow 9am", "2026-10-23 09:00"),
    ("on 3/10 at 9am", ("ask", ["2027-10-03 09:00", "2027-03-10 09:00"])),
    ("1.30pm", "13:30"),
    ("9.30 pm", "21:30"),
    ("at 1.30pm", "13:30"),
    ("10 a.m.", "10:00"),
    ("at 10 p.m.", "22:00"),
    ("at 10 o'clock", ("ask", ["10:00", "22:00"])),
    ("email Seg at 9am", "09:00"),
    ("on may 5 at 9am", "2027-05-05 09:00"),
    ("read the may 5 report", "missing"),
    ("5/6 at 10:00 pay Maria da Silva", ("ask", ["2027-06-05 10:00", "2027-05-06 10:00"])),
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
    assert got["when"] == "13:00" and got["reading"] == {"when": "13:00", "date": "2026-10-23", "time": "13:00", "rel": 1, "weekday": 4, "far": False, "rolled": True,
                                                         "relative": None, "dated": False, "assumed_year": False}
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
    line = "Troca de óleo às 13hrs amanhã, por favor"      # validate: allow english-only -- a Portuguese line, the case of the parser
    got = nt.parse(line, clock())
    assert nt.without(line, got["spans"]) == "Troca de óleo , por favor"
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
    "weekday_next": ["naechsten"], "weekday_this": [], "weekday_after": [], "weak": [], "months": [[f"monat{n}"] for n in range(1, 13)], "month_joiners": [],
    "day_words": [], "ordinal_prefixes": [], "and_half": [], "joiners": [], "half_words": [], "time_words": [], "fraction_before": [], "fraction_after": [],
    "date_cues": [], "edge_words": [],
    "ordinal_suffixes": [], "prefixes": ["um", "am"], "hour_words_24": ["u"], "meridiem": {"am": [], "pm": []},
    "dayparts": {"morning": [], "dawn": [], "afternoon": [], "evening": [], "night": []}, "vague": ["spaeter"], "noon": ["mittag"], "midnight": [],
    "bare_hour_prefixes": ["um"], "relative_in": ["in"], "relative_units": {"m": ["min"], "h": ["std"], "d": ["tagen"], "w": []}, "number_words": {"ein": 1},
    "half_hour": [], "triggers": {"remind": ["erinnere mich"], "remind_anywhere": [], "reminders": [], "reminders_bare": [], "calendar": [], "calendar_verb": [], "calendar_noun": [],
                 "calendar_loose": [], "note": [], "undo": []},
    "forget": {"verbs": [], "nouns": [], "fillers": [], "id_words": [], "id_marked": []}, "polite": [], "connectors": ["an"],
    "answers": {"yes": ["ja"], "notice": [], "event": [], "other": [], "cancel": [], "thanks": [], "again": []},
    "vague_parts": {"morning": [], "afternoon": [], "evening": [], "night": []},
    "work_starters": [],
}
STUB = {**{key: [] for key in nt.LISTS}, **STUB, "markers": ["bitte"]}          # every list a table must hold, empty, unless the stub says otherwise


def test_a_third_language_plugs_in_as_a_table_with_no_edit_of_the_engine():
    nt.check_table(STUB)
    now = clock()
    assert nt.parse("morgen 7u", now, [STUB])["when"] == "2026-10-23 07:00"
    assert nt.parse("uebermorgen mittag", now, [STUB])["when"] == "2026-10-24 12:00"
    assert [r["when"] for r in nt.parse("naechsten donnerstag 9u", now, [STUB])["ask"]] == ["2026-10-29 09:00", "2026-11-05 09:00"]
    assert nt.parse("in 30 min", now, [STUB])["when"] == "in 30m"
    assert nt.parse("spaeter", now, [STUB])["missing"] == "time"
    assert nt.parse("um 9", now, [STUB])["ask"][1]["time"] == "21:00"
    assert nt.parse("morgen 7u", now) is None, "the shipped tables know nothing of the stub"
    both = nt.languages() + [STUB]
    assert nt.parse("morgen 7u", now, both)["when"] == "2026-10-23 07:00", "and every table is tried on every line: a line in the stub's words with the shipped ones"
    assert nt.parse("tomorrow 7u", now, both)["when"] == "2026-10-23 07:00", "even half of a line in each"


def folder_with(tmp_path, names, files=None):
    """A folder of language files: the shipped English table, the stub as `natural_lang_xx.py`, and the list of names the loader reads."""
    (tmp_path / "natural_lang_en.py").write_text((st.RUNTIME / "natural_lang_en.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "natural_lang_xx.py").write_text("TABLE = " + repr(STUB) + "\n", encoding="utf-8")
    for name, text in (files or {}).items():
        (tmp_path / f"{name}.py").write_text(text, encoding="utf-8")
    (tmp_path / "natural_languages.json").write_text(json.dumps({"languages": names}), encoding="utf-8")
    return str(tmp_path)


def test_a_language_is_a_file_and_a_name_in_the_list_and_the_engine_is_not_edited(tmp_path):
    folder = folder_with(tmp_path, ["natural_lang_en", "natural_lang_xx"])
    found = nt.load_languages(folder)
    assert [t["tag"] for t in found] == ["en", "xx"]
    assert nt.parse("morgen 7u", clock(), found)["when"] == "2026-10-23 07:00" and nt.parse("tomorrow 7pm", clock(), found)["when"] == "2026-10-23 19:00"


def test_the_tables_are_read_as_data_and_never_executed(tmp_path):
    marker = tmp_path / "ran.txt"
    code = "open(%r, 'w').write('ran')\nTABLE = %r\n" % (str(marker), STUB)
    folder = folder_with(tmp_path, ["natural_lang_en", "natural_lang_xx"], {"natural_lang_xx": code})
    assert [t["tag"] for t in nt.load_languages(folder)] == ["en", "xx"]
    assert not marker.exists(), "the file was parsed and its TABLE literal read; no line of it ran"
    (tmp_path / "natural_lang_xx.py").write_text("TABLE = dict(tag='xx')\n", encoding="utf-8")
    with pytest.raises(ValueError):          # a table that is not a literal is refused, not run
        nt.load_languages(folder)


def test_a_list_that_names_a_bad_file_a_duplicate_tag_or_no_file_is_refused_with_a_sentence_and_a_glob_finds_nothing(tmp_path):
    folder = folder_with(tmp_path, ["natural_lang_en", "natural_lang_xx"], {"natural_lang_bad": "TABLE = {'tag': 'bad'}\n", "natural_lang_twin": "TABLE = " + repr(STUB) + "\n"})
    with pytest.raises(ValueError) as e:
        nt.load_languages(folder, ["natural_lang_en", "natural_lang_bad"])
    assert "language table 'bad'" in str(e.value)
    with pytest.raises(ValueError) as e:
        nt.load_languages(folder, ["natural_lang_xx", "natural_lang_twin"])
    assert "two files have this tag" in str(e.value)
    for name in ("../natural_lang_en", "other", "natural_lang_en.py", "natural_lang_missing"):
        with pytest.raises(ValueError):
            nt.load_languages(folder, [name])
    assert [t["tag"] for t in nt.load_languages(folder)] == ["en", "xx"], "only what the list names is loaded: the files `bad` and `twin` sit in the folder and are not read"
    (tmp_path / "natural_languages.json").write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        nt.load_languages(folder)
    assert "natural_languages.json" in str(e.value)


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
    assert imports <= {"__future__", "ast", "calendar", "datetime", "json", "os", "re", "sys", "unicodedata"}, imports


# --- what is left near the time, what repeats, and the checks of the tables' list ---------------------------------------------------------------------------


def test_a_word_of_the_time_near_it_and_a_typo_of_a_day_word_are_doubts_and_a_name_or_a_far_word_is_not():
    for line in ("remind me next week at 10am to pay", "me lembra semana que vem às 10h de pagar", "me lembra amnha às 9h", "remind me tomorow at 9am",      # validate: allow english-only -- Portuguese lines, the cases of the tests
                 "me lembra amanhã às 9h do próximo mês", "me lembra amanhã às 9h do fim de semana"):      # validate: allow english-only -- Portuguese lines, the cases of the tests
        assert nt.doubt(line), line
    for line in ("me lembra amanhã às 9h de arrumar o quarto", "me lembra amanhã às 9h de ligar para a Amanda", "me lembra amanhã às 9h do segundo andar",      # validate: allow english-only -- Portuguese lines, the cases of the tests
                 "me lembra amanhã às 9h do quintal", "remind me tomorrow at 9am to call Marcos", "remind me tomorrow at 9am to match the invoices",      # validate: allow english-only -- Portuguese lines, the cases of the tests
                 "remind me to pay the rent for the whole month and call the bank, tomorrow at 9am", "remind me tomorrow at 9am"):
        assert not nt.doubt(line), line
    assert not nt.doubt("no time here at all")


def test_a_line_that_repeats_is_recognised_in_every_language_and_a_noun_is_not_a_repetition_far_from_the_time():
    for line in ("me lembra toda terça às 7h30", "me lembra de beber agua de 2 em 2 horas", "me lembra todo dia às 7h", "me lembra a cada 2 horas", "me lembra diariamente às 9h",      # validate: allow english-only -- Portuguese lines, the cases of the tests
                 "remind me every monday", "remind me daily at 9am", "remind me each week on friday at 3pm", "remind me to stretch every 2 hours"):
        assert nt.recurring(line), line
    for line in ("me lembra amanhã às 9h", "me lembra de levar todos os documentos", "remind me tomorrow at 9am", "remind me to pay 8 in 2 hours"):      # validate: allow english-only -- Portuguese lines, the cases of the tests
        assert not nt.recurring(line), line


def test_a_relative_time_is_elapsed_time_across_a_clock_change():
    zone = lisbon()
    now = clock("2026-10-24 12:00", zone)
    reading = nt.parse("in 24 hours", now)["reading"]
    assert reading["date"] == "2026-10-25" and reading["time"] == "11:00", "twenty-four hours later is an hour earlier on the wall after the clocks go back"


def test_a_moment_is_built_from_a_day_and_an_hour_the_person_names():
    now = clock()
    assert nt.moment("2026-10-30", "09:00", now)["when"] == "2026-10-30 09:00" and nt.moment("2026-10-30", "09:00", now)["dated"] is True
    assert nt.moment(None, "13:00", now)["rolled"] is True and nt.moment("2027-02-30", "09:00", now)["when"] == "2027-02-30 09:00"


def test_the_shipped_list_cannot_be_empty_and_a_listed_file_that_is_missing_stops_with_a_sentence(tmp_path):
    (tmp_path / "natural_languages.json").write_text(json.dumps({"languages": []}), encoding="utf-8")
    with pytest.raises(ValueError) as e:
        nt.load_languages(str(tmp_path))
    assert "empty" in str(e.value)
    (tmp_path / "natural_languages.json").write_text(json.dumps({"languages": ["natural_lang_en"]}), encoding="utf-8")
    with pytest.raises(ValueError) as e:
        nt.load_languages(str(tmp_path))
    assert "natural_lang_en.py cannot be read" in str(e.value)
    assert [t["tag"] for t in nt.load_languages()] == ["en", "pt-BR"], "the list shipped with the runtime"
