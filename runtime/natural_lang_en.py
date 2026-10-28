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
    "days": {"today": ["today"], "tomorrow": ["tomorrow", "tommorow", "tmrw", "tmr", "2morrow", "2moro"], "day_after_tomorrow": ["the day after tomorrow", "day after tomorrow"]},
    # Monday first
    "weekdays": [["monday", "mon"], ["tuesday", "tue", "tues"], ["wednesday", "wed", "weds"], ["thursday", "thu", "thur", "thurs"], ["friday", "fri"], ["saturday"],
                 ["sunday"]],
    "weekday_next": ["next"],
    "weekday_this": ["this"],
    # words after a weekday that make it the next one, not the nearest ("friday next")
    "weekday_after": [],
    "months": [["january", "jan"], ["february", "feb"], ["march", "mar"], ["april", "apr"], ["may"], ["june", "jun"], ["july", "jul"], ["august", "aug"],
               ["september", "sep", "sept"], ["october", "oct"], ["november", "nov"], ["december", "dec"]],
    # words of this table that are also common words (an abbreviation, "may"): they count only when the line is in this language, and never as a capitalised name
    "weak": ["mon", "tue", "tues", "wed", "weds", "thu", "thur", "thurs", "fri", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "may"],
    # weak words that count only with a cue before them ("on may 5": "I may 2 people" is not a date)
    "cued": ["may"],
    "month_joiners": ["of"],
    "day_words": [],
    "ordinal_prefixes": ["the"],
    "ordinal_suffixes": ["st", "nd", "rd", "th"],
    # a sign written after the number of a day that is not a suffix ("1o", from the ordinal sign)
    "ordinal_marks": [],
    # an ordinal word that is the number 1 where a date stands ("the first of may")
    "first_words": ["first"],
    # "quarter past 4 pm" is 16:15, "quarter to 5 pm" 16:45, "half past 4 pm" 16:30
    "quarter_past": ["quarter past", "a quarter past"],
    "quarter_to": ["quarter to", "a quarter to"],
    "half_past": ["half past"],
    # words that make a number right after them a date ("on 5", "by 5"); a number beside one of these in the reminder's words is a date the engine did not read
    "date_markers": ["on", "by", "until", "due", "dated"],
    # the name of a day of the year: in the reminder's words it is a date the engine does not know
    "date_nouns": ["christmas", "christmas eve", "easter", "new year", "new years", "new years eve", "thanksgiving", "halloween", "holiday", "holidays", "valentines day",
                   "mothers day", "fathers day"],
    # connectors that stand just before a time phrase and leave the reminder's words with it
    "prefixes": ["at", "on", "for"],
    # after a number: a 24-hour clock ("13h" is rare in English, "1300 hours" is not read)
    "hour_words_24": [],
    # after a number with a bare-hour prefix: "at 10 o'clock"
    "hour_words_long": ["o'clock", "oclock"],
    "meridiem": {"am": ["am", "a.m.", "a.m"], "pm": ["pm", "p.m.", "p.m"]},
    # a number and a part of the day: "9 in the morning"
    "dayparts": {"morning": ["in the morning"], "dawn": [], "afternoon": ["in the afternoon"], "evening": ["in the evening"], "night": ["at night", "in the night"]},
    "vague": ["later", "later today", "this morning", "this afternoon", "this evening", "tonight", "in the morning", "in the afternoon", "in the evening", "soon", "morning", "afternoon",
              "evening", "night"],
    # the vague words that name a part of the day: with an hour that has no marker they say which of the two is meant ("tonight at 9" is 21:00)
    "vague_parts": {"morning": ["this morning", "in the morning", "morning"], "afternoon": ["this afternoon", "in the afternoon", "afternoon"],
                    "evening": ["this evening", "in the evening", "evening"], "night": ["tonight", "night"]},
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
    # an opener that repeats when a length of time or a weekday follows it ("every monday", "every 2 hours"); "every client" and "each supplier" are the reminder's words
    "recurrence": ["every", "each"],
    # what may follow an opener besides a weekday: "every day", "every 2 hours", "every other week"
    "recurrence_units": ["day", "days", "week", "weeks", "month", "months", "year", "years", "hour", "minute", "min", "weekday", "weekdays", "weekend", "weekends",
                         "morning", "afternoon", "evening", "night", "half hour", "half an hour", "fortnight", "fortnights"],
    # units that repeat only after a number ("every 2 hours"), never alone
    "recurrence_counted_units": ["hours", "minutes", "mins"],
    # phrases that repeat by themselves
    "recurrence_phrases": ["on weekdays", "on weekends", "twice a day", "three times a day", "once a day", "once a week", "twice a week", "three times a week", "once a month"],
    "recurrence_other": ["other"],
    # a word right after the unit that makes the opener part of the reminder's words ("every day of the month")
    "recurrence_not_before": ["of"],
    # adverbs that repeat only beside the time ("daily at 9") or at the edge of the words ("remind me weekly to ..."); "weekly report" is the reminder's words
    "recurrence_adverbs": ["daily", "weekly", "monthly", "yearly", "annually", "hourly", "nightly", "fortnightly", "always"],
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
                   "could", "would", "can", "schedule", "book", "update", "delete", "remove", "explain", "ask", "request", "compose", "notify"],
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
    "forget": {"verbs": ["forget", "cancel", "delete", "remove", "drop"], "nouns": ["reminder", "reminders"], "fillers": ["the", "my", "of", "number", "no", "n"],
               # the words that make the number after the noun its id ("reminder number 9"); any other word between them is not an id
               "id_words": ["number", "n", "num", "nr"],
               # words that make the number after them an id only when written with a full stop or glued to it ("no. 3", "no3"); "no 3" is a preposition and a number
               "id_marked": ["no"]},
    # the noun of a reminder: "schedule a reminder", "book a reminder" make a reminder, whatever the scheduling verb
    "remind_nouns": ["reminder", "reminders"],
    # a week that is named without a day: the day of it is asked ("next week at 10")
    "week_phrases": ["of next week", "in next week", "next week"],
    # "30 minutes before the meeting at 3pm": the offset is taken off the hour that follows
    "before_words": ["before"],
    # a weekday right after one of these is the topic of the reminder, not its day ("about friday", "the meeting of friday")
    "topic_words": ["of", "about"],
    # the word that joins a date to the hour before it ("9am on 12/12")
    "date_after_clock": ["on"],
    # a date right after one of these, after the moment, is the content of the request, not its moment ("tomorrow at 9am ... before it expires on the 15th"); never "before", "until" or "by": they may name the moment
    "deadline_words": ["expires", "expire", "expiring", "expired", "due", "deadline"],
    # a date right after one of these is where something goes, never the content of the request ("move the meeting to the deadline on the 20th")
    "deadline_to": ["to", "for", "until", "till", "into"],
    # a word between the moment and the date that says a second moment follows ("tomorrow at 9am, then again on the due date, the 15th")
    "deadline_breaks": ["then", "again", "and", "also"],
    "polite": ["please", "can you", "could you", "would you", "hey", "hi"],
    # "yes, but at 3pm": the word that joins a yes to the change
    "but_words": ["but", "except", "only"],
    # one of these directly after the trigger is not part of the reminder's words
    "connectors": ["to", "about", "of", "that"],
    "answers": {"yes": ["yes", "y", "yeah", "yep", "ok", "okay", "sure", "confirm", "do it", "go ahead", "sounds good", "of course", "thats right", "exactly", "that is right"], "notice": ["reminder", "notice", "alert", "ping", "notification"],
                "event": ["event", "calendar", "agenda", "appointment"], "other": ["other", "something else", "else", "no", "nope", "nothing", "neither"],
                "cancel": ["cancel", "never mind", "nevermind", "forget it", "stop", "drop it", "skip it"], "thanks": ["thanks", "thank you", "thx", "ty", "cheers"],
                # "another time": the reading shown is not the one meant, and the person will say which
                "again": ["another time", "other time", "different time", "another day", "change it", "change"]},
    # a line that starts with one of these is a request for work, never a reminder with no trigger
    "work_starters": ["write", "create", "make", "generate", "build", "draft", "prepare", "review", "analyze", "analyse", "summarize", "summarise", "search",
                      "find", "send", "publish", "post", "plan", "design", "implement", "fix", "check", "run", "show", "list", "give", "tell", "what", "how",
                      "why", "when", "where", "who", "which", "is", "are", "do", "does", "can", "could", "would", "should", "schedule", "book"],
    # package NR-2: tier 1 for the other operations of the platform (runtime/natural.py `match`), as data. A form is a regular expression matched against the WHOLE line (lower
    # case, no accent, every run of other characters one space) and has no open tail; `{n}` is the integer written in the line, the only argument a form gives
    "requests": {
        "forms": {
            "pending": [r"my pending( decisions| items)?", r"what (do i need to|must i|should i|am i supposed to) (approve|decide|answer)",
                        r"what (is|s) (waiting|pending) for me", r"(list|show)( me)?( my)? pending( decisions| items)?"],
            "sources": [r"(what|which) (files|documents|sources|spreadsheets) do you (have|know)", r"(what|which)( are)?( the| my)? (files|documents|sources)( do you have)?",
                        r"(list|show)( me)?( the| my)? (files|documents|sources)"],
            "attachments": [r"(what|which) (files|attachments) did i send", r"(list|show)( my)? (attachments|held files)", r"my attachments"],
            "artifacts": [r"(list|show)( the)?( project)? artifacts"],
            "routines": [r"(what|which) routines( do i have| exist| are there)?", r"(list|show)( my| the)? routines", r"my routines"],
            "skills": [r"(what|which) skills do you have", r"(list|show)( the)? skills"],
            "agents": [r"(what|which) agents( do i have| exist| are there)?", r"(list|show)( the| my)? agents"],
            "costs": [r"how much (did|have) (i|we) (spend|spent)( today| this week| this month)?", r"(what are|show)( the| my)? costs"],
            "instructions": [r"(what are|show)( me)?( the| my)?( standing)? instructions"],
            "flows": [r"(what|which) flows( are there| exist| do you have)?", r"(list|show)( the)? flows"],
            "connections": [r"(what are|show)( me)?( the)? connections"],
            "task": [r"(?:(?:show|how is|what about)(?: the)? )?task(?: (?:number|n|id))? {n}"],
            "commands": [r"help( me)?", r"what can you do", r"what (commands|can i ask)( do you (have|know))?", r"how (do|can) i use (this|you)"],
            "reject": [r"(reject|decline)(?: (?:the|this))?(?: (?:plan|request|delivery|decision|acceptance|question))?(?: (?:number|n|id))? {n}",
                       r"(dismiss|discard)(?: (?:the|this))? question(?: (?:number|n|id))? {n}"],
            "approve": [r"(approve|accept)(?: (?:the|this))?(?: (?:plan|request|delivery|decision|acceptance))?(?: (?:number|n|id))? {n}"],
            "release": [r"release(?: (?:the|this))?(?: (?:plan|request|delivery|decision))?(?: (?:number|n|id))? {n}"],
            "go-ahead": [r"(go ahead|proceed)(?: (?:on|with))?(?: the)? task(?: (?:number|n|id))? {n}"],
            "cancel": [r"cancel(?: the)? request(?: (?:number|n|id))? {n}"],
            "stop-task": [r"stop(?: the)? task(?: (?:number|n|id))? {n}"],
            "retry": [r"retry(?: the)? task(?: (?:number|n|id))? {n}", r"try task(?: (?:number|n|id))? {n} again"],
            "routine-pause": [r"pause(?: the)? routine(?: (?:number|n|id))? {n}"],
            "routine-cancel": [r"cancel(?: the)? routine(?: (?:number|n|id))? {n}"],
            "routine-resume": [r"resume(?: the)? routine(?: (?:number|n|id))? {n}"],
            "routine-approve": [r"approve(?: the)? routine(?: (?:number|n|id))? {n}"],
            "routine-create": [r"(create|set up|make)( a| an)?( new)? routine"],
            "routine-change": [r"(change|edit)(?: the)? routine(?: (?:number|n|id))? {n}"],
            "attachment-add": [r"add(?: the)? (file|attachment)(?: (?:number|n|id))? {n}"],
            "attachment-discard": [r"(discard|delete)(?: the)? (file|attachment)(?: (?:number|n|id))? {n}"],
            "set-model": [r"(change|set|switch)( the)? model( of the agent)?"],
            "set-mode": [r"(change|set|switch)( the)? (autonomy )?mode( of the agent)?"],
            "config": [r"(show|see)( me)?( the)? config(uration)?", r"what is the config(uration)?"],
            "accept-config": [r"accept( the)? config(uration)?"],
            "give-consent": [r"give( my)? consent"],
            "instructions-set": [r"(change|replace|edit)( the| my)?( standing)? instructions"],
            "instructions-add": [r"add( an| a)? instruction"],
            "source-add": [r"(add|register)( a| an)?( new)? source"],
            "source-import": [r"import( a| an| the)?( new)? (version|source|file)"],
            "source-refresh": [r"(refresh|update)( a| the)? source"],
            "source-describe": [r"describe( a| the)? source"],
            "flow-save": [r"save (this|that) (plan|flow)"],
            "sync": [r"(sync|synchronize)( the)?( documents| tasks)?"],
            "dispatch": [r"(run|start)( the)? dispatcher"],
            "run-next": [r"run( the)? next task"],
            "deps": [r"install( the)? dependencies"],
            "verdict": [r"(record|give) a verdict"],
            "proof": [r"show( the)? proof"],
            "items": [r"my (emails|e mails|events|appointments)", r"(list|show)( me)?( my)? (emails|e mails|events|appointments)", r"(what|which) (emails|e mails|events|appointments)( do i have| came in)?",
                      # slice S4b: the calendar read in words, the nouns of `writes.calendar.nouns_plural` (so `items_kind` says calendar); a day word is allowed and read by nobody (the list is the snapshot's)
                      r"my (calendar|agenda|schedule)( today| tomorrow)?", r"(list|show)( me)?( my| the)? (calendar|agenda|schedule)( for)?( today| tomorrow)?",
                      r"(what|which) (is|are) (on|in)( my| the) (calendar|agenda|schedule)( today| tomorrow)?", r"what s (on|in)( my| the) (calendar|agenda|schedule)( today| tomorrow)?",
                      r"what do i have (on|in)( my| the) (calendar|agenda|schedule)( today| tomorrow)?"],
            "mail-send": [r"send( an| a| the)? (e mail|email)"],
            "mail-reply": [r"reply to( the| an| a)? (e mail|email)"],
            "mail-draft": [r"draft( an| a| the)? (e mail|email)"],
            "mail-archive": [r"archive( the| these| this| my)? (e mails|emails|e mail|email|messages)"],
            "mail-mark": [r"mark( the| these| this)?( e mails| emails| e mail| email| messages)? as (read|unread)"],
            "mail-trash": [r"(delete|trash)( the| these| this)? (e mails|emails|e mail|email|messages)",
                           r"move( the| these| this)? (e mails|emails|e mail|email|messages) to( the)? trash"],
            "event-change": [r"(reschedule|move)( the| my)? (meeting|event|appointment)"],
            "event-cancel": [r"cancel( the| my)? (meeting|event|appointment)"],
            "file-create": [r"create( a| an| the)?( new)? (document|file)"],
            "file-save": [r"save (this|that) (file|document|attachment)"],
        },
        # words for one kind of document, for runtime/source_resolve.py: a group is one word (groups that share a word are one)
        "aliases": [["cv", "resume", "curriculum"], ["spreadsheet", "sheet"], ["invoice", "bill"], ["budget", "quote"], ["report"], ["presentation", "slides", "deck"],
                    ["proposal"], ["receipt"], ["minutes"], ["passport"], ["statement"], ["manual", "handbook", "guide"]],
        # words that say "a file": they make a line name a document, and never match a source by themselves
        "cues": ["file", "files", "document", "documents", "doc", "docs", "pdf", "attachment", "attachments", "source", "sources", "spreadsheet"],
        # words that never name a source
        "generic": ["my", "mine", "our", "say", "says", "said", "about", "tell", "show", "read"],
        "short_stop": ["to", "of", "in", "on", "at", "is", "it", "be", "an", "as", "me", "el", "la", "le", "un", "une", "der", "die", "das"],
        # the words of a confirmation: the table of `answers` holds this language's; these are the words of languages that no table ships (a router-chosen operation is
        # confirmed in the person's own language), in any script
        "yes": ["si", "oui", "ja", "da", "hai", "はい", "да", "是", "네",
                # slice S4: whole-line confirmations of es, fr, de, it and pt that no shipped table of those languages holds (an interpreted reminder is confirmed in the person's own words)
                "vale", "claro", "de acuerdo", "dale", "d accord", "bien sur", "volontiers", "genau", "klar", "gerne", "jawohl", "va bene", "certo", "volentieri"],
        "no": ["non", "nein", "нет", "いいえ", "否", "아니요",
               "nee", "nicht", "pas question", "no gracias", "non merci", "nein danke", "no grazie"],
        # package NR-5: the words of the natural writes (runtime/natural_writes.py): lists of PHRASES (words of a-z and 0-9 separated by one space, no accent, no character a
        # regular expression means anything by), never an expression. The family `mail` is filled by NR-5b.
        "writes": {
            "polite": ["please", "pls", "can you", "could you", "would you", "hey", "hi"],
            "articles": ["a", "an", "the", "my", "our", "your", "new"],
            "joiners": ["and"],
            # the words that turn the noun after them into the one the person does not want ("the e-mails, not the calendar"): never "no" (the lists merge across tables and the pt-BR "no" is "in the")
            "negators": ["not", "never", "without", "except", "instead of", "rather than"],
            "range": ["to", "through", "thru"],
            "service_in": ["on", "in", "to", "via", "using", "from", "on my", "in my", "to my", "from my"],
            # the words that may surround the kind in the answer to the reminder-or-event question (an article, a possessive, a place word, a polite word): a closed list
            "kind_fillers": ["a", "an", "the", "my", "in", "on", "here", "at", "chat", "please", "i", "want", "would", "like", "it", "to", "be", "as", "just", "make", "this"],
            "services": {
                "google": ["google", "gmail", "google drive", "gdrive", "drive", "google calendar", "google docs"],
                "microsoft": ["outlook", "onedrive", "one drive", "microsoft cloud", "microsoft", "hotmail", "office 365"],
            },
            "calendar": {
                "in_calendar": ["on my", "in my", "on the", "in the", "to my", "to the"],
                "calendar_after": ["calendar"],
                # S11: the words that name the account of a calendar line (runtime/event_lookup.py): the brand alone, not the file or mail words of the same service
                "brands_google": ["google", "gmail", "gcal"],
                "brands_microsoft": ["outlook", "microsoft", "hotmail", "office365", "office 365"],
                "range_from": ["from"],
                "range_to": ["to", "until", "till", "through"],
                "all_day": ["all day", "the whole day", "the entire day"],
                "change_verbs": ["reschedule", "move", "change", "shift", "postpone"],
                "cancel_verbs": ["cancel", "delete", "remove", "drop"],
                "nouns": ["event", "meeting", "appointment"],
                "nouns_plural": ["events", "meetings", "appointments", "calendar", "agenda", "schedule"],
                "to_time": ["to", "for"],
                "rename": ["rename", "retitle", "change the title of", "change the name of"],
                "rename_to": ["to"],
            },
            "mail": {
                "send_verbs": ["send", "write", "compose"],
                "reply_verbs": ["reply to", "reply", "answer", "respond to"],
                "draft_verbs": ["draft", "make a draft of", "save a draft of", "write a draft of"],
                "archive_verbs": ["archive"],
                "move_verbs": ["move"],
                "mark_verbs": ["mark"],
                "trash_verbs": ["delete", "trash", "remove", "throw away"],
                "nouns": ["email", "emails", "e mail", "e mails", "message", "messages"],
                "plural": ["emails", "e mails", "messages"],
                "to": ["to"],
                "subject": ["with the subject", "with subject", "subject line", "subject"],
                "body": ["saying that", "saying", "that says", "with the text"],
                "of": ["from", "of", "about", "regarding"],
                "folder": ["to the folder", "into the folder", "to folder", "to the label", "to"],
                "read": ["as read"],
                "unread": ["as unread"],
                "newest": ["latest", "last", "newest", "most recent"],
                "date_words": ["yesterday", "today", "tomorrow", "last week", "last month", "last year", "this week", "this month", "week", "month", "year", "day", "days", "hour",
                               "hours", "morning", "afternoon", "evening", "night", "recent", "recently"],
            },
            "files": {
                "create_verbs": ["create", "make", "save", "write"],
                "replace_verbs": ["replace", "swap", "overwrite", "update"],
                "save_verbs": ["save", "upload", "store", "put", "keep", "send", "drop"],
                "nouns": ["file", "document", "note", "doc", "text file"],
                "named": ["named", "called", "with the name"],
                "content": ["with the text", "with the content", "saying", "that says", "containing"],
                "folder": ["in the folder", "to the folder", "into the folder", "in folder"],
                "this": ["this", "that", "it"],
                "held_nouns": ["file", "attachment", "document", "pdf", "photo", "picture", "image"],
                "save_lines": ["save", "save it", "save this", "please save", "keep it", "keep this"],
                "add_words": ["to the project", "as a source", "make it a source", "add"],
                "add_lines": ["add to the project", "add it to the project", "add this file to the project", "add as a source", "make it a source", "you can add it", "add"],
                "discard_lines": ["discard", "discard it", "discard this file", "discard the file", "discard this photo"],
                "gdoc": ["google doc", "google docs", "google document"],
                "text_words": ["text", "content"],
                "of": ["of"],
                "replace_with": ["with the text", "with the content", "with"],
                "kinds": {"pdf": ["pdf"], "docx": ["docx", "word document", "word file"], "xlsx": ["spreadsheet", "xlsx"], "txt": ["txt"], "image": ["photo", "picture", "image", "png", "jpg", "jpeg"]},
            },
        },
    },
}
