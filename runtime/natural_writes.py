#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Natural writes (package NR-5): a plain line that asks for a write to the person's own accounts, read by code into the slots of the operation. Pure: the clock is
passed in, nothing is stored, logged or sent, and no project is read. A line never makes a write: it only OPENS the card of the exact content, through the
operation's own function (runtime/ops_natural_writes.py), and the card is the approval (limit L61, contracts/runtime.md).

The words are not here: they are the language tables (`runtime/natural_lang_<tag>.py`, the key `requests.writes`, lists of PHRASES in plain words, never a regular
expression), and the table of EVERY language is tried on EVERY line. A write line is a CLOSED HEAD (a verb and the object it acts on, at the start of the line, after
polite words) followed by slots whose markers are closed word lists; an open question in the line is never a marker. A text slot (a title, a subject, a body, a content)
is the person's own words between two markers, cut of the connectives at its edge and never rewritten.

A FAMILY is the set of operations of one kind of write: `calendar` (event-create, event-change, event-cancel), `files` (file-create, file-replace, file-save) and `mail`
(mail-send, mail-reply, mail-draft, mail-archive, mail-move, mail-mark, mail-trash; package NR-5b). Each family is a module `natural_writes_<family>` (pure, read here)
and a module `ops_natural_<family>` (resolution with the project, read by runtime/ops_natural_writes.py). The registry is `FAMILIES`; adding a family adds a line
there, a module of each kind and the family's lists in the language tables.

The family interface:

  natural_writes_<family>.HEADS(tables) -> [phrase, ...]
        the closed heads the family recognises (folded phrases): the line must start with one of them (after polite words) for `read` to be tried
  natural_writes_<family>.read(line, tables, now) -> {"op", "slots", "spans", "ranges", "need", "engine", "doubt"} | None
        pure. `op` is the operation's name; `slots` the values the line gave (an integer, a list of integers, a name, a text); `spans` the subset of `slots` that are the
        person's own words (for the provenance check); `ranges` {slot: (start, end)} of those spans in the folded line (the reminder-trigger test reads them); `need`
        the required slots the line did not give, in the order they are asked; `engine` the draft of the time engine (runtime/natural.py, `how` "write") when the time
        is not one settled reading, else None; `doubt` true when the engine understood a time but is not sure of it. `now` may be None (the clock-free test that
        `candidate` makes): no time is worked out then. None when the line is not a form of the family: the line goes on as before
  ops_natural_<family>.resolve(ctx, op, slots, channel, sender, said) -> one of
        {"args": {...}}                                          every slot is final: the arguments of the operation's own function (`account` included)
        {"ask": {"need", "options", "sentence_key", "fields"}}   one question about the first thing still open, in the fixed order of runtime/ops_natural_writes.py
        {"say": {"sentence_key", "fields"}}                      a final sentence: nothing is opened (nothing found, nothing held, a recurrence)
        `said` is the list of the person's lines so far (the provenance of a text slot). Nothing is read from a project that the caller may not read: a reference into a
        snapshot is resolved with `channel` and `sender`, and a message is listed only after `item_refs.read_index` allowed it
  natural_writes_<family>.NEEDS = (need, ...)        (optional) the needs the family answers itself
  natural_writes_<family>.answer(need, line, slots, tables, now, options=None) -> {"slots": {...}} | None      (optional)
        the answer to a question whose need is in NEEDS, tried BEFORE the generic answers of runtime/ops_natural_writes.py (an option by number or word, a text, a number, a time);
        `options` are the options the question stored ([{"value", "label"}], what the person was shown), so that an answer can be a number the person was shown. None: not an answer

The shape of a draft, the order of the questions and the answers to them are runtime/ops_natural_writes.py's. The helpers below (`Line`, `numbers`, `service`,
`reminder_outside`) are for the families.

  candidate(line, languages=None)   what the line is, with no clock: {"family", "op"} | None; the order of recognition is the families' heads in the order of `FAMILIES`
                                    (the mail, the files, the calendar), then the calendar event of runtime/natural.py `candidate` (how "trigger"), then nothing
  read(line, now=None, languages=None, op=None)   the family's reading plus {"family"}; with `op` the family of that operation reads the line with the operation fixed
                                    (the seed of a question answered "event", and the router's hint)
  check_writes(table)               ValueError(sentence) when `requests.writes` of a language table is not of the shape of SECTIONS
  problems(op, args, said, accounts, offered, now)   a delegate to `turn_gate.value_problems` (S41-7): why the arguments of a write about to be opened are not all from the person's lines (the fuzz's oracle)

Standard library only. Runs on Python 3.9: python3 runtime/natural_writes.py --help
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import natural  # noqa: E402  (the same folder: the language tables, the time engine and the calendar intent)
import natural_time as nt  # noqa: E402

# The registry of the families: name -> the module that reads it. The module of the resolution is `ops_natural_<name>`. Order is the order of recognition.
# NR-5b adds the line  "mail": "natural_writes_mail",  (first, so that "marca o e-mail 3 como lido" is a mail form before it is a calendar verb).
FAMILIES = {
    "mail": "natural_writes_mail",
    "calendar": "natural_writes_calendar",
    "files": "natural_writes_files",
}
OP_FAMILY = {"event-create": "calendar", "event-change": "calendar", "event-cancel": "calendar",
             "mail-send": "mail", "mail-reply": "mail", "mail-draft": "mail", "mail-archive": "mail", "mail-move": "mail", "mail-mark": "mail", "mail-trash": "mail",
             "file-create": "files", "file-replace": "files", "file-save": "files", "file-trash": "files"}      # the family of each write operation (the router's hint names an operation)

LINE_WORDS_MAX = 120          # a longer line is a request, not a form
SPAN_MAX = {"title": 200, "subject": 200, "body": 4000, "content": 65536, "name": 120}      # characters of a text slot read from a line
LIST_MAX = 20                 # numbers in one list ("os e-mails 2, 4 e 7"): the most a mailbox write takes
MENTION = re.compile(r"(?:^|\s)@\S")      # an `@id` mention of a source; an address has its @ inside a word

# The keys of `requests.writes`, by section. A value of a key is a list of PHRASES; `services` and `kinds` map a name to such a list. NR-5b fills the lists of `mail`.
TOP_KEYS = ("polite", "articles", "joiners", "range", "service_in", "kind_fillers", "negators")
SECTIONS = {
    "services": ("google", "microsoft"),
    "calendar": ("in_calendar", "calendar_after", "range_from", "range_to", "all_day", "change_verbs", "cancel_verbs", "nouns", "nouns_plural", "to_time", "rename", "rename_to",
                 "brands_google", "brands_microsoft"),
    "mail": ("send_verbs", "reply_verbs", "draft_verbs", "archive_verbs", "move_verbs", "mark_verbs", "trash_verbs", "nouns", "plural", "to", "subject", "body", "of",
             "folder", "read", "unread", "newest", "date_words"),
    "files": ("create_verbs", "replace_verbs", "save_verbs", "nouns", "named", "content", "folder", "this", "held_nouns", "gdoc", "text_words", "of", "replace_with",
              "add_words", "save_lines", "add_lines", "discard_lines"),
}
PHRASE = re.compile(r"[a-z0-9]+(?: [a-z0-9]+)*")      # a phrase: words of a-z and 0-9 separated by one space; no character a regular expression means anything by


def _tables(languages=None) -> list:
    return natural._tables(languages)


def writes_of(table: dict) -> dict:
    """The `requests.writes` of one language table ({} when it has none)."""
    given = table.get("requests", {}).get("writes", {})
    return given if isinstance(given, dict) else {}


def check_writes(table: dict) -> None:
    """ValueError(sentence) when the key `requests.writes` of a language table is not of the shape of SECTIONS: every list is a list of phrases (a-z, 0-9 and single
    spaces: no regular-expression character), `services` maps each account to such a list, `files.kinds` maps a kind to one."""
    where = f"language table {table.get('tag')!r}: requests.writes"
    given = writes_of(table)
    if not given:
        return

    def phrases(value, path):
        if not isinstance(value, list) or not all(isinstance(p, str) and PHRASE.fullmatch(p) for p in value):
            raise ValueError(f"{where}.{path} is a list of phrases: words of a-z and 0-9 separated by one space, no regular-expression character")
    extra = sorted(set(given) - set(TOP_KEYS) - set(SECTIONS) - {"files"})
    if extra:
        raise ValueError(f"{where} has no key {extra[0]!r}")
    for key in TOP_KEYS:
        phrases(given.get(key, []), key)
    for section, keys in SECTIONS.items():
        body = given.get(section, {})
        if not isinstance(body, dict):
            raise ValueError(f"{where}.{section} is an object")
        allowed = set(keys) | ({"kinds"} if section == "files" else set())
        if set(body) - allowed:
            raise ValueError(f"{where}.{section} has no key {sorted(set(body) - allowed)[0]!r}")
        for key in keys:
            phrases(body.get(key, []), f"{section}.{key}")
        if section == "files":
            kinds = body.get("kinds", {})
            if not isinstance(kinds, dict):
                raise ValueError(f"{where}.files.kinds maps a kind of file to a list of phrases")
            for kind, listed in kinds.items():
                phrases(listed, f"files.kinds.{kind}")


# --- the toolkit of the families (pure) --------------------------------------------------------------------------------------------------------------------


class Line:
    """A line of the person, folded for matching (lower case, no accent: `natural_time.normalise`) with the way back to the original characters: `span(s, e)` of a range of
    the folded text is the person's own words, verbatim."""

    def __init__(self, text):
        self.text = text if isinstance(text, str) else ""
        self.norm, self.origin = nt.normalise(self.text)

    def span(self, start: int, end: int) -> str:
        """The original text of the folded range [start, end), the person's words as they wrote them (blanks at the edges are cut)."""
        if start >= end or start < 0 or end > len(self.origin):
            return ""
        return self.text[self.origin[start]:self.origin[end - 1] + 1].strip()

    def without(self, ranges) -> str:
        """The line with the folded ranges taken out (each cut leaves one space), in the person's own characters; overlapping ranges are one."""
        spans = sorted((self.origin[s], self.origin[e - 1] + 1) for s, e in ranges if 0 <= s < e <= len(self.origin))
        merged = []
        for s, e in spans:
            if merged and s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
            else:
                merged.append((s, e))
        return nt.without(self.text, merged)

    def find(self, phrases, start: int = 0, end=None):
        """(s, e), in the folded line, of the first place at or after `start` (before `end`) where a phrase of `phrases` stands as whole words; the longest phrase at that
        place wins. None when there is none."""
        alt = nt._alt(phrases)
        if not alt:
            return None
        end = len(self.norm) if end is None else end
        m = re.compile(f"{nt._L}{alt}{nt._R}").search(self.norm, start, end)
        return (m.start(), m.end()) if m else None

    def find_all(self, phrases, start: int = 0, end=None) -> list:
        alt = nt._alt(phrases)
        if not alt:
            return []
        end = len(self.norm) if end is None else end
        return [(m.start(), m.end()) for m in re.compile(f"{nt._L}{alt}{nt._R}").finditer(self.norm, start, end)]

    def lead(self, phrases, tables: list):
        """The end, in the folded line, of the longest phrase of `phrases` that the line starts with (after blanks, marks and polite words), or None."""
        best = None
        alt = nt._alt(phrases)
        if not alt:
            return None
        polite = sorted({p for t in tables for p in writes_of(t).get("polite", []) + t.get("polite", [])}, key=lambda p: (-len(p), p))
        lead = nt._alt(polite)
        pre = f"(?:{lead}(?![a-z0-9])[\\s,;:]*)*" if lead else ""          # a comma after a polite word is part of it ("por favor, marca ...")
        m = re.match(f"[^a-z0-9@]*{pre}{alt}(?![a-z0-9])", self.norm)
        if m:
            best = m.end()
        return best

    def words_after(self, start: int) -> list:
        """The words of the folded line from `start`: [(word, s, e)]."""
        return [(m.group(0), m.start() + start, m.end() + start) for m in re.finditer(r"[a-z0-9]+", self.norm[start:])]


def listed(tables: list, section, key: str) -> list:
    """The phrases of one list of `requests.writes`, over every table (`section` None: a top-level key), in order and without repeats."""
    out = []
    for table in tables:
        body = writes_of(table) if section is None else writes_of(table).get(section, {})
        for phrase in (body.get(key, []) if isinstance(body, dict) else []):
            if phrase not in out:
                out.append(phrase)
    return out


def skip_articles(line: Line, at: int, tables: list) -> int:
    """`at` moved past the articles ("o", "um", "esse"...) that stand right there."""
    articles = listed(tables, None, "articles")
    while True:
        m = re.compile(r"\s*").match(line.norm, at)
        here = m.end() if m else at
        found = line.find(articles, here, here + 20)
        if found and found[0] == here:
            at = found[1]
        else:
            return here if here != at else at


def numbers(line: Line, start: int, end: int, tables: list):
    """The integers written in [start, end) of the folded line, in order, when that part is nothing but numbers and the words that join them ("2", "2, 4 e 7", "1 a 3",
    "#5"): a list of 1 to LIST_MAX integers, each at least 1, a range written out ("1 a 3" is 1, 2, 3) and no number twice. None when the part holds anything else."""
    part = line.norm[start:end]
    joiners = [j for j in listed(tables, None, "joiners")]
    spans = [j for j in listed(tables, None, "range")]
    tokens = re.findall(r"#?[0-9]{1,4}|[a-z]+|,|-", part)
    if "".join(re.sub(r"\s+", "", t) for t in tokens) != re.sub(r"\s+", "", part) or not tokens:
        return None
    out, expect_number, ranged = [], True, False
    for token in tokens:
        if expect_number:
            if not re.fullmatch(r"#?[0-9]{1,4}", token):
                return None
            n = int(token.lstrip("#"))
            if n < 1 or token.lstrip("#") != str(n):
                return None
            if ranged:
                if n <= out[-1]:
                    return None
                out += list(range(out[-1] + 1, n + 1))
                ranged = False
            else:
                out.append(n)
            expect_number = False
        else:
            if token == "," or token in joiners:
                expect_number = True
            elif token == "-" or token in spans:
                expect_number, ranged = True, True
            else:
                return None
    if expect_number or len(out) > LIST_MAX or len(set(out)) != len(out):
        return None
    return out


def service(line: Line, tables: list, start: int = 0, end=None):
    """(account, s, e) of the service the line names, or None: `account` is `google` or `microsoft`; (s, e) is the folded range to take out of the line (the word that
    introduces it, "no", "on", comes with it). A phrase of two words or more names a service by itself ("google calendar"); one word needs an introducing word ("no
    outlook"). A line that names both services names none: the account is asked."""
    found = {}
    alt = nt._alt(listed(tables, None, "service_in"))
    before = re.compile(f"{nt._L}{alt}\\s+$") if alt else None
    for account in ("google", "microsoft"):
        names = listed(tables, "services", account)
        for s, e in line.find_all(names, start, end):
            word_count = len(line.norm[s:e].split())
            lead = before.search(line.norm[:s], start) if before else None
            if lead:
                found.setdefault(account, (lead.start(), e))
            elif word_count >= 2:
                found.setdefault(account, (s, e))
    if len(found) != 1:
        return None
    account = next(iter(found))
    return account, found[account][0], found[account][1]


def _negated_before(norm: str, at: int, negators: list, articles: list) -> bool:
    """Whether the folded text right before `at` is a negator phrase, then only single spaces and article phrases, with no punctuation in between ("not the " and "nao a " are; "nao, a " and
    "no " are not: a comma or any other mark breaks the reach of the negator)."""
    prefix = norm[:at]
    by_length = lambda phrases: sorted(set(phrases), key=lambda p: (-len(p), p))      # noqa: E731  (the longest phrase first)

    def ends_with(text: str, phrases: list):
        for phrase in by_length(phrases):
            if text.endswith(phrase) and (len(text) == len(phrase) or not text[-len(phrase) - 1].isalnum()):
                return phrase
        return None
    while prefix.endswith(" ") and not prefix.endswith("  "):
        prefix = prefix[:-1]
        if ends_with(prefix, negators):
            return True
        article = ends_with(prefix, articles)
        if not article:
            return False
        prefix = prefix[:-len(article)]
    return False


def _nouns_named(shaped: "Line", phrases: list, tables: list) -> tuple:
    """(plain, negated): the places, in the folded line, where a phrase of `phrases` stands as whole words, split by whether a negator (`requests.writes.negators`: "not", "nao", "sem", "em vez de") reaches
    it. A hit is negated when the text right before it is a negator phrase followed only by single spaces and articles ("not the calendar", "nao a agenda"); a mark in between ("nao, a agenda") or a
    word that is no article leaves it plain. Both lists are in line order."""
    negators, articles = listed(tables, None, "negators"), listed(tables, None, "articles")
    plain, negated = [], []
    for hit in shaped.find_all(phrases):
        (negated if _negated_before(shaped.norm, hit[0], negators, articles) else plain).append(hit)
    return plain, negated


def _items_nouns(shaped: "Line", tables: list) -> tuple:
    """((calendar plain, calendar negated), (mail plain, mail negated)): the hits of the calendar nouns (singular and plural) and of the mail nouns in one line."""
    calendar = _nouns_named(shaped, listed(tables, "calendar", "nouns") + listed(tables, "calendar", "nouns_plural"), tables)
    return calendar, _nouns_named(shaped, listed(tables, "mail", "nouns"), tables)


def items_kind(line, languages=None) -> str:
    """"calendar" when the line that asks for the numbered items names events (`requests.writes.calendar` nouns, singular or plural) that no negator reaches, or when the only messages it names are
    negated ("not the e-mails") and it names no event; else "mail". A line that names both and negates neither is "calendar"; "list my e-mails, not the calendar" is "mail"."""
    tables = _tables(languages)
    (cal_plain, cal_negated), (mail_plain, mail_negated) = _items_nouns(Line(line if isinstance(line, str) else ""), tables)
    if cal_plain:
        return "calendar"
    return "calendar" if mail_negated and not mail_plain and not cal_negated else "mail"


def items_noun(line, languages=None):
    """"calendar" when the line names events (`requests.writes.calendar` nouns, singular or plural), "mail" when it names messages (`requests.writes.mail` nouns), else None: a line that
    names neither ("no, the one for tomorrow") leaves the kind of a list to the plan it corrects. A noun that a negator reaches ("not the calendar", "nao a agenda") is the one the person does not
    want: a line that names only the e-mails plainly is "mail" whatever else it negates, and a line that only negates one kind ("not the calendar") is the other kind. A line that names both
    plainly is "calendar", as `items_kind` reads it; one that negates both is None."""
    tables = _tables(languages)
    (cal_plain, cal_negated), (mail_plain, mail_negated) = _items_nouns(Line(line if isinstance(line, str) else ""), tables)
    if cal_plain:
        return "calendar"
    if mail_plain:
        return "mail"
    if cal_negated and not mail_negated:
        return "mail"
    if mail_negated and not cal_negated:
        return "calendar"
    return None


def reminder_outside(line: Line, tables: list, ranges: dict) -> bool:
    """Whether the line holds a reminder trigger ("me lembra") that is not inside one of the text spans the family took (`ranges`, folded): a body that says "me lembra"
    is a body, a line that also asks for a reminder is two requests and no write form."""
    spots = []
    anywhere = natural._anywhere(line.norm, tables, "remind_anywhere")
    if anywhere:
        spots.append(anywhere)
    head = natural._head(line.norm, tables, "remind")
    if head is not None:
        spots.append((0, head))
    return any(not any(s >= rs and e <= re_ for rs, re_ in ranges.values()) for s, e in spots)


# --- the value oracle is the gate's (S41-7) ------------------------------------------------------------------------------------------------------------------


def problems(op: str, args: dict, said: list, accounts: dict, offered: dict, now, languages=None) -> list:
    """The value oracle (why the arguments of a write about to be opened are not all from the person's lines). It moved, unchanged, to the gate (runtime/turn_gate.py
    `value_problems`, S41-7), so that it outlives the line-claiming forms of this module (S41-11); this is the delegate the fuzzers and the older tests call."""
    return importlib.import_module("turn_gate").value_problems(op, args, said, accounts, offered, now, languages)


# The engine's answers the oracle's time check asks for, kept by the content of the language tables (the oracle's own functions are in runtime/turn_gate.py and ask `_facts` here).
_FACTS: dict = {}
_FACTS_MAX = 4000      # entries kept; past it the cache is dropped whole (an answer is recomputed, never wrong)
_DIGESTS: dict = {}    # id(table) -> (table, digest): the table is held, so an id is never reused by another object while its entry lives


def _digest(table) -> str:
    held = _DIGESTS.get(id(table))
    if held is None or held[0] is not table:
        held = _DIGESTS[id(table)] = (table, hashlib.sha256(json.dumps(table, sort_keys=True, default=repr).encode("utf-8")).hexdigest())
    return held[1]


def clear_facts() -> None:
    """Drop what `_facts` kept (a test, and a process that wants the memory back)."""
    _FACTS.clear()
    _DIGESTS.clear()


def _facts(text: str, now, tables: list):
    """(the clocks written in `text`, the days it names alone, the (date, time) readings of the engine on it): what a window of the person's lines says about time. The
    engine is the slow part of the checker and a window is asked about again and again, so the answer is kept for the moment `now` and the CONTENT of the tables it was made
    with (a digest of each table, never the identity of the object), at most `_FACTS_MAX` entries."""
    key = (text, str(now), tuple(_digest(t) for t in tables))
    if key not in _FACTS:
        if len(_FACTS) >= _FACTS_MAX:
            _FACTS.clear()
        clocks, days, readings = set(), set(), []
        for hit in nt.find(text, tables)["hits"]:
            if hit["kind"] == "clock":
                clocks |= {f"{h:02d}:{m:02d}" for h, m in hit["times"]}
        parsed = nt.parse(text, now, tables)
        if parsed and "when" in parsed:
            readings = [(parsed["reading"]["date"], parsed["reading"]["time"])]
        elif parsed and "ask" in parsed:
            readings = [(r["date"], r["time"]) for r in parsed["ask"]]
        elif parsed and parsed.get("day"):
            days.add(parsed["day"]["date"])
        _FACTS[key] = (clocks, days, readings)
    return _FACTS[key]



# --- recognition -------------------------------------------------------------------------------------------------------------------------------------


def family_module(name: str):
    """The pure module of a family (`natural_writes_<family>`), imported once."""
    return importlib.import_module(FAMILIES[name])


def families() -> list:
    return list(FAMILIES)


def _claim(text: str) -> bool:
    return bool(text.strip()) and not text.lstrip().startswith("/") and len(text.split()) <= LINE_WORDS_MAX and not MENTION.search(text)


def read(line, now=None, languages=None, op=None):
    """The reading of a write line (see the module's text), or None when it is not one. With `op` the family of that operation reads the line with the operation fixed."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    if not _claim(text):
        return None
    shaped = Line(text)
    if op is not None:
        name = OP_FAMILY.get(op)
        if name not in FAMILIES:
            return None
        got = family_module(name).read(text, tables, now, op=op) if _takes_op(name) else family_module(name).read(text, tables, now)
        return _finish(got, name, shaped, tables, op)
    found = _read_closed(text, tables, now, shaped)
    if found is not None and found["op"] == "event-create" and natural.repeat_goes_on(text):
        return None      # CB-9: since catalog version 2 a line that holds a repetition phrase goes on to the interpreter: an event form does not claim it, so NW_RECURRING_EVENT never answers it
    return found


def _read_closed(text, tables, now, shaped):
    """The closed forms of the families, in order, with no operation fixed."""
    for name in FAMILIES:
        module = family_module(name)
        if module.HEADS(tables) and shaped.lead(module.HEADS(tables), tables) is None:
            continue
        got = module.read(text, tables, now)
        if got:
            return _finish(got, name, shaped, tables, None)
    named = natural.candidate(text, tables)
    if named and named["op"] == "calendar-event-create" and named["how"] == "trigger" and "calendar" in FAMILIES:
        got = family_module("calendar").read(text, tables, now, op="event-create")
        return _finish(got, "calendar", shaped, tables, None)
    return None


def _takes_op(name: str) -> bool:
    import inspect
    return "op" in inspect.signature(family_module(name).read).parameters


def _finish(got, name: str, shaped: Line, tables: list, op):
    if not got or (op is not None and got.get("op") != op):
        return None
    if reminder_outside(shaped, tables, got.get("ranges") or {}):
        return None
    return dict(got, family=name)


def caption_files(text, languages=None) -> dict:
    """What the text sent with a file asks, loosely (the caption preselects what the file's card offers and writes nothing): {"mode": "save" | "card", "account", "kind"}
    (runtime/natural_writes_files.py `caption`)."""
    return family_module("files").caption(text, _tables(languages))


def file_line(text, languages=None):
    """"save", "add" or "discard" when the whole line is one of the closed phrases that ask it of the file just sent (`requests.writes.files.save_lines`, `add_lines`,
    `discard_lines`), else None. The phrase says nothing of a file by itself: whether one is there to act on is the bridge's (a recent file with a card in the chat)."""
    if not isinstance(text, str) or not text.strip() or text.lstrip().startswith("/") or len(text.split()) > 12:
        return None
    tables = _tables(languages)
    files = family_module("files")
    for word, key in (("save", "save_lines"), ("add", "add_lines"), ("discard", "discard_lines")):
        if files.whole(text, tables, key):
            return word
    return None


def candidate(line, languages=None):
    """What the line is, with no clock: {"family", "op"} | None. The same test as `read`, without the time engine."""
    got = read(line, None, languages)
    return {"family": got["family"], "op": got["op"]} if got else None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
