#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A row of a list the platform just showed, named by an ordinal word or by a value the list shows (package LP-1, lane A3', scenario 38): "a última", "o primeiro", "a das 15h",
"a do dia 23", "the second one", "o do banco".

The number a list prints ("o 2", "cancela o 4") is read by runtime/event_lookup.py `_number_form`; this file reads the replies that name a row WITHOUT a number, and decides which
row of the list they name, by code, against the rows exactly as the list printed them. Both functions are pure: they read no project, no calendar, no snapshot and no model, and
keep nothing. The words are data (runtime/registry/list_pick_words.json, through `registry_data.list_pick_words()`), in pt-BR and en.

  read(said)                          one closed form for a WHOLE line, or None
  choose(form, rows, day_of, more)    (verdict, payload, detail) against the rows as shown
  address_words(label)                the folded words an option's address holds (the options of a write question)

`read`. A line is a pick only when it is, from its first word to its last: an optional cancel or change verb (the calendar tables' `cancel_verbs` and `change_verbs`, read as
`_number_form` reads them), then exactly one of
  - an ordinal word (primeiro..décimo, first..tenth; an article before it is optional, "da lista" or "one" may follow);
  - the word for last ("a última", "the last one");
  - a lead and a clock ("a das 15h", "a das 3", "o das 15h30", "the one at 3pm"; a clock that names its marker (h, pm) also follows a value lead: "a de 15h");
  - a lead and a value ("a de amanha", "a do dia 22", "o do outlook", "o do banco", "the one on friday": a lead is "o do", "a de", "the one from"...),
and then nothing but polite words. A clock with no lead ("15h", "às 15h") is no pick, so that a new time said after a list of a change is never taken for a row; a title word
("a reuniao das 15h"), a plural ("os dois últimos"), a longer request ("a das 15h e muda para 17h") and a line that holds another verb are no pick either: the line goes on as it does
today. The form: {"verb": "cancel" | "change" | None, "head": the verb and the event noun in the folded words the numbered line starts with ("cancela evento"), None with no verb, and
"kind": "ordinal" ("position", "word": the word the data shows for it, "said": the word written, "weekday": whether the word is also a day of the week) | "last" | "clock" ("readings": ["HH:MM"],
"spoken") | "account" ("account", "words": the brand as written) | "words" ("words": the folded words of a day or of a sender)}.

`choose` (rows: [{"n": the number the list printed, "day": ISO date | None, "start": "HH:MM" | None, "account": ... | None, "position": 1.. | None}], in the order printed). The verdict:
  ("one", i, None)                     the row i; the caller goes on exactly as it does for the number `rows[i]["n"]`
  ("several", [i, ...], value)         more than one row fits: the list is kept and the sentence asks for the number (`value` says what was named: ("clock", spoken) | ("day", date) |
                                       ("weekday", 0-6) | ("account", account))
  ("none", None, value)                no row fits (an ordinal beyond the list is ("ordinal", its position))
  ("ask", why, detail)                 the reading is not safe and the person is asked: "ordinal-clash" ({"n", "position", "m"}: the number that is also the position, the position, the number of the row
                                       at that position), "last-not-shown", "day-or-position" ({"position", "a": the numbers of the rows on the weekday, "b": the number of the row at the position})
  ("skip", None, None)                 the form needs what the rows do not have (a position when the list had several sections, a sender in a list of events): not a pick, the line goes on
The ordinal is the POSITION in the printed list, and the lists number their rows by the snapshot (2 and 4, not 1 and 2), so an ordinal whose position number is also the printed number
of ANOTHER row ("o segundo" when "2." is the first row) is asked, never guessed (what a number means wins over a position); "o último" of a list that said it holds more rows than it
printed is asked. A pt-BR word that is both an ordinal and a weekday ("a segunda", "a quarta", "a quinta", "a sexta") is read both ways: the weekday reading W and the position reading
P; W none -> P; P none -> W (one row: that row, several: "several"); W and P one row and the same -> that row; anything else -> "day-or-position". A day is read by `day_of`, which the
caller passes (event_lookup `_day_named`: ("day", date) | ("weekday", 0-6) | ("none", None) | ("unread", None)); a clock matches the start the list printed; a clock written with no marker
and one to eleven o'clock ("a das 3") matches either reading (03:00 and 15:00).

Never kept, never logged: the line, the rows' titles or the words of a sender. Standard library only. Runs on Python 3.9: python3 runtime/list_pick.py --help
"""
from __future__ import annotations

import datetime
import re
import sys

import natural
import natural_writes as nw
import registry_data

LINE_MAX = 80          # characters of a line that can be a pick: a pick is a few words
WORDS_MAX = 5          # words of a day or of the sender words after a lead
CLOCK = re.compile(r"(?P<h>[0-9]{1,2})(?P<hm> ?h(?:oras?)?(?: ?(?P<m>[0-9]{2}))?)?(?: ?(?P<ap>am|pm))?")
SKIP = ("skip", None, None)


def _tokens(text: str) -> list:
    """The folded words of the text after the verb; a clock written 15:30 reads as 15h30."""
    return re.findall(r"[a-z0-9]+", re.sub(r"([0-9]{1,2}):([0-9]{2})", r"\1h\2", text))


def _leading(words: list, phrases) -> int:
    """The number of words of the longest phrase of `phrases` (tuples of words) the list of words starts with, 0 for none."""
    best = 0
    for phrase in phrases:
        if len(phrase) > best and tuple(words[:len(phrase)]) == phrase:
            best = len(phrase)
    return best


def _clock(words: list, marked_only: bool):
    """The clock a run of words is, as {"readings", "spoken"}, or None. `marked_only`: a clock with no h or am/pm is not read (it follows a value lead, not a clock lead)."""
    found = CLOCK.fullmatch(" ".join(words))
    if not found:
        return None
    hour, minute = int(found.group("h")), int(found.group("m") or 0)
    marked = bool(found.group("hm") or found.group("ap"))
    if minute > 59 or (marked_only and not marked):
        return None
    if found.group("ap"):
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if found.group("ap") == "pm" else 0)
        hours = [hour]
    elif hour > 23:
        return None
    elif 1 <= hour <= 11 and not found.group("h").startswith("0"):
        hours = [hour, hour + 12]          # one to eleven with no marker: the morning and the afternoon reading
    else:
        hours = [hour]
    return {"readings": [f"{h:02d}:{minute:02d}" for h in hours], "spoken": f"{found.group('h').lstrip('0') or '0'}:{minute:02d}" if not found.group("ap") else f"{hours[0]}:{minute:02d}"}


def _form(verb, head, kind, **more) -> dict:
    return {"verb": verb, "head": head, "kind": kind, **more}


def read(said):
    """The closed form of a whole line that names a row of a list without its number, or None (see the module's text)."""
    if not isinstance(said, str) or not said.strip() or len(said) > LINE_MAX:
        return None
    tables = natural._tables(None)
    line = nw.Line(said)
    verb_end, verb = line.lead(nw.listed(tables, "calendar", "cancel_verbs"), tables), "cancel"
    if verb_end is None:
        verb_end, verb = line.lead(nw.listed(tables, "calendar", "change_verbs"), tables), "change"
    if verb_end is None:
        verb = None
    nouns = nw.listed(tables, "calendar", "nouns")
    head = f"{line.norm[:verb_end].rstrip()} {nouns[0]}" if verb and nouns else None
    words = _tokens(line.norm[verb_end or 0:])
    data = registry_data.list_pick_words()
    while words:
        ended = next((p for p in data["polite"] if len(p) <= len(words) and tuple(words[-len(p):]) == p), None)
        if ended is None:
            break
        words = words[:-len(ended)]          # the polite words that end the line
    if not words:
        return None
    # an ordinal word or the word for last, with an optional article before and "one" or "da lista" after
    rest = words[_leading(words, data["articles"]):]
    if tuple(rest) in data["last"]:
        return _form(verb, head, "last")
    if rest and rest[0] in data["ordinals"] and _leading(rest[1:], data["after_ordinal"]) == len(rest) - 1:
        position, shown = data["ordinals"][rest[0]]
        return _form(verb, head, "ordinal", position=position, word=shown, said=rest[0], weekday=rest[0] in data["weekday_ordinals"])
    # a lead and a value
    lead = _leading(words, data["clock_leads"] + data["value_leads"])
    if not lead:
        return None
    value, leading = words[lead:], tuple(words[:lead])
    if not value or len(value) > WORDS_MAX:
        return None
    clock = _clock(value, marked_only=leading not in data["clock_leads"])
    if clock:
        return _form(verb, head, "clock", **clock)
    if leading not in data["value_leads"]:
        return None
    for account, brands in registry_data.search_stop_words()["brands"].items():
        if tuple(value) in brands:
            return _form(verb, head, "account", account=account, words=value)
    return _form(verb, head, "words", words=value)


def address_words(label) -> set:
    """The folded words of the address of an option's label ("who@domain.example · subject"): the words of the local part (split on . _ - +) and the labels of the domain except the last
    (the same words `natural_writes_mail.entry_words` folds from a From). The subject is not read; a label with no address holds none."""
    local, sign, domain = str(label or "").split(" · ")[0].strip().partition("@")
    if not sign:
        return set()
    labels = domain.lower().split(".")
    words = set(_tokens(natural.normal(local)))
    for part in labels[:-1] if len(labels) > 1 else labels:
        words |= set(_tokens(natural.normal(part)))
    return words


def _date(value):
    try:
        return datetime.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _numbers(rows: list, indexes: list) -> list:
    return [rows[i]["n"] for i in indexes]


def _clash(rows: list, place: int) -> list:
    """The rows, other than the one at `place`, whose printed number is `place` itself: what a number means wins over a position."""
    return [i for i, r in enumerate(rows) if r["n"] == place and i != place - 1]


def _position(form: dict, rows: list, more: bool):
    """The position reading of an ordinal or of "last": ("row", i), ("none", None), ("clash", detail) or ("not-shown", None)."""
    if form["kind"] == "last":
        return ("not-shown", None) if more else ("row", len(rows) - 1)
    place = form["position"]
    if place > len(rows):
        return ("not-shown", None) if more else ("none", None)
    if _clash(rows, place):
        return ("clash", {"n": place, "position": place, "m": rows[place - 1]["n"]})
    return ("row", place - 1)


def _of_day(rows: list, found) -> list:
    kind, value = found
    if kind == "day":
        return [i for i, r in enumerate(rows) if _date(r.get("day")) == value]
    if kind == "weekday":
        return [i for i, r in enumerate(rows) if _date(r.get("day")) is not None and _date(r["day"]).weekday() == value]
    return []


def choose(form: dict, rows: list, day_of=None, more: bool = False) -> tuple:
    """The verdict of a form against the rows as the list printed them (see the module's text)."""
    kind = form["kind"]
    if not rows:
        return SKIP
    if kind in ("ordinal", "last"):
        if any(r.get("position") is None for r in rows):
            return SKIP          # the list had several sections: a position says nothing
        if kind == "ordinal" and form["weekday"] and day_of is not None:
            return _weekday_or_position(form, rows, day_of, more)
        found, detail = _position(form, rows, more)
        if found == "row":
            return ("one", detail, None)
        if found == "clash":
            return ("ask", "ordinal-clash", detail)
        if found == "not-shown":
            return ("ask", "last-not-shown", None)
        return ("none", None, ("ordinal", form["position"]))
    if kind == "clock":
        hits = [i for i, r in enumerate(rows) if r.get("start") in form["readings"]]
        value = ("clock", form["spoken"])
    elif kind == "account":
        hits = [i for i, r in enumerate(rows) if r.get("account") == form["account"]]
        value = ("account", form["account"])
    else:
        found = day_of(" ".join(form["words"])) if day_of is not None else ("none", None)
        if found[0] not in ("day", "weekday"):
            return SKIP          # sender words, or a day the engine doubts: a list of events holds no sender, and a doubt is the family's to ask
        hits, value = _of_day(rows, found), found
    if len(hits) == 1:
        return ("one", hits[0], None)
    return ("several", hits, value) if hits else ("none", None, value)


def _weekday_or_position(form: dict, rows: list, day_of, more: bool) -> tuple:
    """Rule 5: a word that is both an ordinal and a weekday is read both ways (W: the weekday, P: the position)."""
    found = day_of(form["said"])
    if found[0] == "day":
        found = ("weekday", found[1].weekday())          # a bare weekday word that the caller read as a date: its weekday
    w = _of_day(rows, found) if found[0] == "weekday" else []
    kind, detail = _position(form, rows, more)
    if not w:
        return _from_position(form, kind, detail)
    if kind == "not-shown":
        return ("ask", "last-not-shown", None)          # the position cannot be told and the weekday is one of the readings: the number is asked
    if kind == "none":
        return ("one", w[0], None) if len(w) == 1 else ("several", w, found)
    if kind == "row" and len(w) == 1 and w[0] == detail:
        return ("one", detail, None)
    shown = [rows[detail]["n"]] if kind == "row" else [detail["m"]] if kind == "clash" else []
    return ("ask", "day-or-position", {"position": form["position"], "a": _numbers(rows, w), "b": shown})


def _from_position(form: dict, kind: str, detail) -> tuple:
    if kind == "row":
        return ("one", detail, None)
    if kind == "clash":
        return ("ask", "ordinal-clash", detail)
    if kind == "not-shown":
        return ("ask", "last-not-shown", None)
    return ("none", None, ("ordinal", form["position"]))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
