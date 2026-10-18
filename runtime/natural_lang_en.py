#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""English, as a language table of the natural-request engine (package NR-1): the words a person types, as data. A pure literal, no code and no import.

A language is one file like this one, `runtime/natural_lang_<tag>.py`, holding `TABLE`, and one name in the list of shipped languages
(`runtime/natural_languages.json`); the engine (runtime/natural_time.py reads the time words, runtime/natural.py the trigger words) reads the file as data
(`ast.literal_eval`, never executed), tries the table of every language on every line, so a project written in one language still understands a line in
another, and adding a language adds one file, one name in that list and its tests, never an engine edit. The schema is in runtime/natural_time.py
(`check_table` refuses a table that breaks it); runtime/natural_lang_pt_br.py is the second table.

Every word is lower case, with no accent, and a phrase is words separated by one space (a hyphen between two letters is read as a space: "next-friday" is
"next friday"). The sentences the runtime says back are not here: they are the phrase table's (runtime/phrases.py), in the project's language.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

TABLE = {
    "tag": "en",
    # words that mark a line as this language (they decide how a date such as 5/6 is read, and whether a weak word of this table counts); only words that are
    # not common in the other languages of the tables
    "markers": ["remind", "reminder", "reminders", "tomorrow", "today", "tonight", "the", "to", "about", "next", "please", "my", "of", "and", "on", "at"],
    # how a date written x/y reads when both numbers are 12 or less: "ask" (month first or day first, the person is asked) or "day-first"
    "slash_dates": "ask",
    "days": {"today": ["today"], "tomorrow": ["tomorrow"], "day_after_tomorrow": ["the day after tomorrow", "day after tomorrow"]},
    # Monday first
    "weekdays": [["monday", "mon"], ["tuesday", "tue", "tues"], ["wednesday", "wed"], ["thursday", "thu", "thur", "thurs"], ["friday", "fri"], ["saturday"],
                 ["sunday"]],
    "weekday_next": ["next"],
    "weekday_this": ["this"],
    # words after a weekday that make it the next one, not the nearest ("friday next")
    "weekday_after": [],
    "months": [["january", "jan"], ["february", "feb"], ["march", "mar"], ["april", "apr"], ["may"], ["june", "jun"], ["july", "jul"], ["august", "aug"],
               ["september", "sep", "sept"], ["october", "oct"], ["november", "nov"], ["december", "dec"]],
    # words of this table that are also common words (an abbreviation, "may"): they count only when the line is in this language, and never as a capitalised name
    "weak": ["mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "may"],
    # weak words that count only with a cue before them ("on may 5": "I may 2 people" is not a date)
    "cued": ["may"],
    "month_joiners": ["of"],
    "day_words": [],
    "ordinal_prefixes": ["the"],
    "ordinal_suffixes": ["st", "nd", "rd", "th"],
    # connectors that stand just before a time phrase and leave the reminder's words with it
    "prefixes": ["at", "on", "for"],
    # after a number: a 24-hour clock ("13h" is rare in English, "1300 hours" is not read)
    "hour_words_24": [],
    # after a number with a bare-hour prefix: "at 10 o'clock"
    "hour_words_long": ["o'clock", "oclock"],
    "meridiem": {"am": ["am", "a.m.", "a.m"], "pm": ["pm", "p.m.", "p.m"]},
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
    # "an hour and a half": what follows the hours; "13 and 30": the word between an hour and its minutes, and the word for 30 minutes
    "and_half": ["and a half", "and half"],
    "joiners": [],
    "half_words": [],
    # a word left in the line near the time that shows the time was not fully understood (a week, a month): the reading is shown and confirmed
    "time_words": ["next", "last", "week", "weeks", "weekend", "month", "months", "year", "years", "yesterday", "early", "morning", "afternoon", "evening", "night",
                   "tonight", "hour", "hours", "minute", "minutes", "soon", "ago", "before", "after", "until", "till"],
    # a word one letter away from a day word that is a word of its own: never read as a typo
    "not_typos": ["match", "matches", "mayor", "toady", "sundae", "mondays", "tuesdays", "wednesdays", "thursdays", "fridays", "saturdays", "sundays", "march",
                  "august", "toast", "monday", "money", "funday"],
    # a repetition: reminders here are one-time, so a line that repeats is said not to be one (a routine does that)
    "recurrence": ["every", "each", "daily", "weekly", "monthly", "yearly", "annually", "recurring", "repeat", "repeating"],
    "recurrence_before_day": [],
    "recurrence_joiners": [],
    # a word just before or just after x/y that makes it a fraction or a count and not a date ("installment 3/10", "3/10 of the rent")
    "fraction_before": ["installment", "installments", "part", "page", "pages", "chapter", "item", "episode", "score", "volume", "vol", "step", "round", "slide",
                        "question"],
    "fraction_after": ["of"],
    # a word just before x/y that makes it a date
    "date_cues": ["on", "until", "by", "for", "before", "due"],
    # words at the edge of the reminder's words that are not part of them ("to call mom", "mom for")
    "edge_words": ["to", "about", "of", "that", "for", "and", "or", "at", "on", "in"],
    # words that say a line is about reminders not working, not a request about them
    "problem_words": ["not", "never", "broken", "bug", "bugs", "fail", "fails", "failed", "failing", "error", "errors", "doesnt", "dont", "wont", "isnt", "arent",
                      "late", "why", "stuck", "wrong", "missing", "work", "works", "working"],
    # a verb or the opening of a request for work: a line that holds one is not the words of a reminder
    "work_verbs": ["write", "create", "make", "generate", "build", "draft", "prepare", "review", "analyze", "analyse", "summarize", "summarise", "search", "find",
                   "send", "publish", "post", "plan", "design", "implement", "fix", "check", "run", "show", "list", "give", "tell", "please", "want", "need",
                   "could", "would", "can", "schedule", "book", "update", "delete", "remove"],
    # the words after a bare calendar noun that make it a question about the calendar, not a request to write to it
    "calendar_noun_reads": ["of", "for", "on", "today", "tomorrow", "this", "next", "view", "full"],
    # the words that start a line the engine reads as a request of the tier
    "triggers": {
        "remind": ["remind me", "reminder", "set a reminder", "set reminder", "create a reminder", "make a reminder", "add a reminder", "new reminder"],
        # a verb phrase that makes a reminder wherever it stands in the line, when the line holds a time
        "remind_anywhere": ["remind me"],
        "reminders": ["my reminders", "list my reminders", "list reminders", "show my reminders", "show reminders", "what reminders", "which reminders"],
        # a word that is a list request only when it is the whole line
        "reminders_bare": ["reminders"],
        # a verb with a calendar word: an event write (not built)
        "calendar": ["put on my calendar", "put it on my calendar", "add to my calendar", "add it to my calendar", "put in my calendar", "create an event",
                     "create event", "add an event", "put on the calendar", "add to the calendar"],
        # a verb that is an event write when it has a time
        "calendar_verb": [],
        # a calendar noun: a read ("calendar for tomorrow?"), or with a time and nothing that makes it a read, a request that is asked about
        "calendar_noun": ["calendar"],
        # a scheduling verb with no calendar word: the person is asked whether it is an event or something else
        "calendar_loose": ["schedule", "book"],
        "note": ["note"],
        "undo": ["undo", "undo that", "undo it", "bring it back", "bring that back", "restore it"],
    },
    "forget": {"verbs": ["forget", "cancel", "delete", "remove", "drop"], "nouns": ["reminder"], "fillers": ["the", "my", "number", "no", "n"]},
    "polite": ["please", "can you", "could you", "would you", "hey", "hi"],
    # one of these directly after the trigger is not part of the reminder's words
    "connectors": ["to", "about", "of", "that"],
    "answers": {"yes": ["yes", "y", "yeah", "yep", "ok", "okay", "sure", "confirm", "do it"], "notice": ["reminder", "notice", "alert", "ping", "notification"],
                "event": ["event", "calendar", "agenda", "appointment"], "other": ["other", "something else", "else", "no", "nope", "nothing", "neither"],
                "cancel": ["cancel", "never mind", "nevermind", "forget it", "stop", "drop it", "skip it"], "thanks": ["thanks", "thank you", "thx", "ty", "cheers"]},
    # a line that starts with one of these is a request for work, never a reminder with no trigger
    "work_starters": ["write", "create", "make", "generate", "build", "draft", "prepare", "review", "analyze", "analyse", "summarize", "summarise", "search",
                      "find", "send", "publish", "post", "plan", "design", "implement", "fix", "check", "run", "show", "list", "give", "tell", "what", "how",
                      "why", "when", "where", "who", "which", "is", "are", "do", "does", "can", "could", "would", "should", "schedule", "book"],
}
