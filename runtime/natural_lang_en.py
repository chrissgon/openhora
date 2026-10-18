#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""English, as a language table of the natural-request engine (package NR-1): the words a person types, as data. A pure literal, no code and no import.

A language is one file like this one, `runtime/natural_lang_<tag>.py`, holding `TABLE`; the engine (runtime/natural_time.py reads the time words,
runtime/natural.py the trigger words) tries the table of every language on every line, so a project written in one language still understands a line in another,
and adding a language adds one file and its tests, never an engine edit. The schema is in runtime/natural_time.py (`check_table` refuses a table that breaks it);
runtime/natural_lang_pt_br.py is the second table.

Every word is lower case, with no accent, and a phrase is words separated by one space (a hyphen between two letters is read as a space: "next-friday" is
"next friday"). The sentences the runtime says back are not here: they are the phrase table's (runtime/phrases.py), in the project's language.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

TABLE = {
    "tag": "en",
    # words that mark a line as this language (they decide how a date such as 5/6 is read, and nothing else)
    "markers": ["remind", "reminder", "reminders", "tomorrow", "today", "tonight", "the", "to", "about", "next", "please", "my", "of", "and", "on", "at"],
    # how a date written x/y reads when both numbers are 12 or less: "ask" (month first or day first, the person is asked) or "day-first"
    "slash_dates": "ask",
    "days": {"today": ["today"], "tomorrow": ["tomorrow"], "day_after_tomorrow": ["the day after tomorrow", "day after tomorrow"]},
    # Monday first
    "weekdays": [["monday", "mon"], ["tuesday", "tue", "tues"], ["wednesday", "wed"], ["thursday", "thu", "thur", "thurs"], ["friday", "fri"], ["saturday"],
                 ["sunday"]],
    "weekday_next": ["next"],
    "weekday_this": ["this"],
    "months": [["january", "jan"], ["february", "feb"], ["march", "mar"], ["april", "apr"], ["may"], ["june", "jun"], ["july", "jul"], ["august", "aug"],
               ["september", "sep", "sept"], ["october", "oct"], ["november", "nov"], ["december", "dec"]],
    "month_joiners": ["of"],
    "day_words": [],
    "ordinal_prefixes": ["the"],
    "ordinal_suffixes": ["st", "nd", "rd", "th"],
    # connectors that stand just before a time phrase and leave the reminder's words with it
    "prefixes": ["at", "on", "for"],
    # after a number: a 24-hour clock ("13h" is rare in English, "1300 hours" is not read)
    "hour_words_24": [],
    "meridiem": {"am": ["am"], "pm": ["pm"]},
    # a number and a part of the day: "9 in the morning"
    "dayparts": {"morning": ["in the morning"], "dawn": [], "afternoon": ["in the afternoon"], "evening": ["in the evening"], "night": ["at night", "in the night"]},
    "vague": ["later", "later today", "this morning", "this afternoon", "this evening", "tonight", "in the morning", "in the afternoon", "in the evening", "soon"],
    "noon": ["noon", "midday"],
    "midnight": ["midnight"],
    # words that introduce an hour with no marker ("at 9"): asked back, 09:00 or 21:00
    "bare_hour_prefixes": ["at", "around", "by"],
    "relative_in": ["in", "within"],
    "relative_units": {"m": ["minutes", "minute", "mins", "min", "m"], "h": ["hours", "hour", "hrs", "hr", "h"], "d": ["days", "day"], "w": ["weeks", "week"]},
    "number_words": {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                     "fifteen": 15, "twenty": 20, "thirty": 30},
    "half_hour": ["half an hour", "half hour", "a half hour"],
    # the words that start a line the engine reads as a request of the tier
    "triggers": {
        "remind": ["remind me", "reminder", "set a reminder", "set reminder", "create a reminder", "make a reminder", "add a reminder", "new reminder"],
        "reminders": ["my reminders", "list my reminders", "list reminders", "show my reminders", "show reminders", "what reminders", "which reminders",
                      "reminders"],
        "calendar": ["put on my calendar", "put it on my calendar", "add to my calendar", "add it to my calendar", "put in my calendar", "create an event",
                     "create event", "add an event", "put on the calendar"],
        "calendar_loose": ["schedule", "book"],
        "note": ["note"],
    },
    "forget": {"verbs": ["forget", "cancel", "delete", "remove", "drop"], "nouns": ["reminder"], "fillers": ["the", "my", "number", "no", "n"]},
    "polite": ["please", "can you", "could you", "would you", "hey", "hi"],
    # one of these directly after the trigger is not part of the reminder's words
    "connectors": ["to", "about", "of", "that"],
    "answers": {"yes": ["yes", "y", "yeah", "yep", "ok", "okay", "sure", "confirm", "do it"], "notice": ["reminder", "notice", "alert", "ping", "notification"],
                "event": ["event", "calendar", "agenda", "appointment"]},
    # a line that starts with one of these is a request for work, never a reminder with no trigger
    "work_starters": ["write", "create", "make", "generate", "build", "draft", "prepare", "review", "analyze", "analyse", "summarize", "summarise", "search",
                      "find", "send", "publish", "post", "plan", "design", "implement", "fix", "check", "run", "show", "list", "give", "tell", "what", "how",
                      "why", "when", "where", "who", "which", "is", "are", "do", "does", "can", "could", "would", "should"],
}
