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
  problems(op, args, said, accounts, offered, now)   why the arguments of a write about to be opened are not all from the person's lines (the provenance check of the fuzz)

Standard library only. Runs on Python 3.9: python3 runtime/natural_writes.py --help
"""
from __future__ import annotations

import importlib
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
             "file-create": "files", "file-replace": "files", "file-save": "files"}      # the family of each write operation (the router's hint names an operation)

LINE_WORDS_MAX = 120          # a longer line is a request, not a form
SPAN_MAX = {"title": 200, "subject": 200, "body": 4000, "content": 65536, "name": 120}      # characters of a text slot read from a line
LIST_MAX = 20                 # numbers in one list ("os e-mails 2, 4 e 7"): the most a mailbox write takes
MENTION = re.compile(r"(?:^|\s)@\S")      # an `@id` mention of a source; an address has its @ inside a word

# The keys of `requests.writes`, by section. A value of a key is a list of PHRASES; `services` and `kinds` map a name to such a list. NR-5b fills the lists of `mail`.
TOP_KEYS = ("polite", "articles", "joiners", "range", "service_in", "kind_fillers")
SECTIONS = {
    "services": ("google", "microsoft"),
    "calendar": ("in_calendar", "calendar_after", "range_from", "range_to", "all_day", "change_verbs", "cancel_verbs", "nouns", "nouns_plural", "to_time", "rename", "rename_to"),
    "mail": ("send_verbs", "reply_verbs", "draft_verbs", "archive_verbs", "move_verbs", "mark_verbs", "trash_verbs", "nouns", "plural", "to", "subject", "body", "of",
             "folder", "read", "unread", "newest"),
    "files": ("create_verbs", "replace_verbs", "save_verbs", "nouns", "named", "content", "folder", "this", "held_nouns", "gdoc", "text_words", "of", "replace_with"),
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


def items_kind(line, languages=None) -> str:
    """"calendar" when the line that asks for the numbered items names events (`requests.writes.calendar` nouns, singular or plural), else "mail"."""
    tables = _tables(languages)
    shaped = Line(line if isinstance(line, str) else "")
    names = listed(tables, "calendar", "nouns") + listed(tables, "calendar", "nouns_plural")
    return "calendar" if shaped.find(names) else "mail"


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


# --- the provenance check (the fuzz of tests/test_natural_writes_dialogues.py reads it) ---------------------------------------------------------------------

TEXT_ARGS = ("title", "subject", "text", "body", "content", "file_name", "name")
SECTION_OF = {"event-create": "calendars", "event-change": "calendars", "event-cancel": "calendars", "file-create": "folders", "file-replace": "folders", "file-save": "folders"}


def _words(text) -> list:
    return natural.normal(text).split()


def _subsequence(small: list, big: list) -> bool:
    it = iter(big)
    return all(word in it for word in small)


def _contiguous(small: list, big: list) -> bool:
    n = len(small)
    return n > 0 and any(big[i:i + n] == small for i in range(len(big) - n + 1))


def problems(op: str, args: dict, said: list, accounts: dict, offered: dict, now, languages=None) -> list:
    """Why the arguments of a write the code is about to open are not all from the person: [] when every slot traces to one of the person's lines (`said`), to a name of the
    configuration (`accounts`: the checked `accounts` object, with its `default`), or to an option code listed and the person chose (`offered`: {"numbers": ids of the files
    and events code listed, "sources": ids of the file sources code listed, "source_accounts": the accounts of the calendar sources code listed}). A span slot is the person's
    words in order (a body, a content and a file name are one contiguous run of a line); a number is written in a line or was listed; an account is named in a line, is the only
    one that has what the operation needs, is the default, or was picked among the options; a calendar or folder is a configured name written in a line or picked; a time is a
    reading of the time engine on the person's words."""
    tables = _tables(languages)
    out = []
    lines = [natural.normal(s) for s in said]
    line_words = [l.split() for l in lines]
    digits = {int(d) for l in lines for d in re.findall(r"[0-9]+", l) if len(d) <= 9}
    picks = any(re.fullmatch(r"[0-9]{1,2}", l) for l in lines)
    options = offered.get("options")          # the values of the options code asked the person to choose from (when the caller records them): a pick counts only for those
    for key, value in args.items():
        if key in TEXT_ARGS:
            words = _words(str(value).removesuffix(".gdoc") if key == "file_name" else value)
            contiguous = key in ("body", "content", "text", "subject", "file_name", "name")
            check = _contiguous if contiguous else _subsequence
            if not words or not any(check(words, w) for w in line_words):
                out.append(f"{key} is not the person's words: {value!r}")
        elif key in ("start", "end"):
            out += _time_problems(key, str(value), said, now, tables)
        elif key in ("event", "attachment"):
            n = value if isinstance(value, int) else int(str(value).rsplit("#", 1)[-1])
            if n not in digits and n not in offered.get("numbers", ()):
                out.append(f"{key} {n} is not written in a line nor listed")
        elif key == "file":
            if value not in offered.get("sources", ()):
                out.append(f"file {value!r} is not a source code listed")
        elif key == "account":
            if not (op.startswith("mail-") and _mailbox_account(value, args, said, offered, picks if options is None else bool(options))):
                out += _account_problems(op, value, lines, accounts, offered, picks if options is None else value in options, tables)
        elif key in ("calendar", "folder"):
            section = "calendars" if key == "calendar" else "mail_folders" if op.startswith("mail-") else "folders"
            listed = ((accounts.get(args.get("account")) or {}).get(section)) or {}
            if value not in listed or not (any(_contiguous(_words(value), w) for w in line_words) or (picks if options is None else value in options)):
                out.append(f"{key} {value!r} is not a configured name written or picked")
        elif key in ("to", "cc", "bcc"):
            out += _address_problems(key, value, said)
        elif key in ("message", "messages"):
            out += _message_problems(key, value, said, offered, tables, options)
        elif key == "state":
            if value not in ("read", "unread") or not (_state_said(value, said, tables) or (picks if options is None else value in options)):
                out.append(f"state {value!r} was not said")
        else:
            out.append(f"{key} is not a slot of a natural write")
    if "start" in args and "end" in args:
        start_day, _, start_clock = str(args["start"]).partition("T")
        end_day, _, end_clock = str(args["end"]).partition("T")
        if start_day != end_day or not (start_clock and end_clock and end_clock > start_clock):
            out.append(f"end {args['end']} is not after start {args['start']} on the same day")
    return out


def _address_problems(key: str, value, said: list) -> list:
    """The addresses of a recipient list (comma-separated, at most 20) must each be written in one of the person's lines: a recipient is never found in a mailbox or a body."""
    addresses = [a for a in str(value).split(",") if a]
    if not addresses or len(addresses) > 20:
        return [f"{key} is {len(addresses)} addresses: an e-mail takes 1 to 20"]
    haystack = [s.lower() for s in said]
    return [f"{key} {a!r} is not an address written in a line" for a in addresses if not any(a.lower() in line for line in haystack)]


def _written_numbers(text: str) -> set:
    """The numbers a line writes: its digit groups, and every number between two of them joined by a range word or a dash (`1 a 3`, `1 to 3`, `1-3`)."""
    folded = natural.normal(text)
    out = {int(n) for n in re.findall(r"[0-9]{1,9}", folded)}
    for a, b in re.findall(r"([0-9]{1,9})\s*(?:a|ate|to|through|thru)?\s*([0-9]{1,9})", folded):
        if int(a) < int(b) <= int(a) + 40 and re.search(rf"{a}\s*(?:a|ate|to|through|thru)\s*{b}", folded):
            out |= set(range(int(a), int(b) + 1))
    for a, b in re.findall(r"([0-9]{1,9})\s*-\s*([0-9]{1,9})", text):
        if int(a) < int(b) <= int(a) + 40:
            out |= set(range(int(a), int(b) + 1))
    return out


def _mail_readings(said: list, tables: list) -> list:
    """What the mail family reads of each of the person's lines ({} for a line it does not read)."""
    module = family_module("mail")
    return [module.read(s, tables) or {} for s in said]


def _message_problems(key: str, value, said: list, offered: dict, tables: list, options) -> list:
    """Each `<source>#<n>` of a message write: the source is a mailbox code listed (`offered["mail_index"]`: {source: entries of its index}), and the number is written in a line,
    is an option the person was shown (`offered["options"]`), is the first message for "the latest", or is the unique strong match (a plural object: the strong set, up to 20)
    of the words the line said."""
    refs = [r for r in str(value).split(",") if r]
    index = offered.get("mail_index") or {}
    if not refs or len(refs) > LIST_MAX:
        return [f"{key} is {len(refs)} messages: a card takes 1 to {LIST_MAX}"]
    written = set()
    for s in said:
        written |= _written_numbers(s)
    readings = [r.get("slots", {}) for r in _mail_readings(said, tables) if r]
    words = next((r["words"] for r in readings if r.get("words")), None)
    newest = any(r.get("newest") for r in readings)
    plural = any(r.get("plural") for r in readings)
    module = family_module("mail")
    out = []
    for ref in refs:
        source, _, n = ref.partition("#")
        if source not in index or not n.isdigit():
            out.append(f"{ref!r} is not a message of a mailbox code listed")
            continue
        n = int(n)
        strong = [e["n"] for e in module.match_words(index[source], words, False)] if words else []
        by_words = n in strong and (len(strong) == 1 or (plural and not newest and len(strong) <= LIST_MAX)) or (newest and strong and n == min(strong))
        if not (n in written or ref in (offered.get("options") or ()) or (newest and not words and n == 1) or by_words):
            out.append(f"message {ref} is not written, shown or the unique match of the words")
    return out


def _state_said(value: str, said: list, tables: list) -> bool:
    module = family_module("mail")
    for line in said:
        got = module.answer("state", line, {}, tables)
        read = module.read(line, tables)
        if (got and got["slots"].get("state") == value) or (read and read["slots"].get("state") == value):
            return True
    return False


def _mailbox_account(value: str, args: dict, said: list, offered: dict, picked: bool) -> bool:
    """Whether the account of a write on messages is the account of their mailbox: the references' sources all belong to `value`, and the mailbox is the only one code listed, is
    written in a line, or was picked."""
    sources = offered.get("mail_sources") or {}
    refs = [r for r in str(args.get("messages") or args.get("message") or "").split(",") if r]
    if not refs or any(sources.get(r.partition("#")[0]) != value for r in refs):
        return False
    return len(sources) == 1 or picked or any(r.partition("#")[0] in natural.normal(" ".join(said)).split() or r in " ".join(said) for r in refs)


def _named(op: str, value: str, lines: list, tables: list) -> bool:
    """Whether a line names the service of `value` the way the reader takes it: a service word behind its introducing word or a phrase of two words, a line that is nothing
    but the service's name (the answer to the account question), or, for a new file, the word of a Google Doc."""
    names = listed(tables, "services", value)
    docs = listed(tables, "files", "gdoc") if value == "google" and op == "file-create" else []
    for text in lines:
        line = Line(text)
        found = service(line, tables)
        if (found and found[0] == value) or line.norm.strip() in names or line.norm.strip() == value or (docs and line.find(docs)):
            return True
    return False


def _account_problems(op, value, lines, accounts, offered, picks, tables) -> list:
    if value not in ("google", "microsoft"):
        return [f"account {value!r} is not an account"]
    if _named(op, value, lines, tables):
        return []          # named in a line, where the reader takes a service word: an account the file does not list is refused by the operation itself, with its sentence
    if value not in accounts:
        return [f"account {value!r} is not configured and was not named"]
    section = SECTION_OF.get(op)
    qualifying = [a for a in ("google", "microsoft") if a in accounts and (accounts[a].get(section) if section else True)]
    if value in offered.get("source_accounts", ()) or qualifying == [value] or (accounts.get("default") == value and value in qualifying) or (picks and len(qualifying) > 1):
        return []
    return [f"the account {value} was guessed: {len(qualifying)} qualify, none was named, chosen or the default"]


def _hour_written(clock: str, text: str) -> bool:
    """Whether the hour (and the minutes, when they are not 00) of `clock` "HH:MM" is a number written in `text`, in the 24-hour form or the 12-hour one."""
    folded = natural.normal(text)
    hour, minute = int(clock[:2]), clock[3:]
    numbers = {int(n) for n in re.findall(r"(?<![0-9:])([0-9]{1,2})(?![0-9])", folded)} | {int(n) for n in re.findall(r"(?<![0-9])([0-9]{1,2})(?=[:h][0-9]{2})", folded)}
    if hour not in numbers and hour % 12 not in numbers and not (hour % 12 == 0 and 12 in numbers):
        return False
    return minute == "00" or bool(re.search(rf"[:h]{minute}(?![0-9])", folded))


def _range_texts(text: str, tables: list) -> list:
    """The text with a range written in bare numbers replaced by the clock of its start, for the checker. This is NOT the parser's rewrite (the checker must not accept what
    the parser misread): it knows two shapes only, written again here from the lists of the tables, and nothing else is a range: (1) a range marker, two numbers and a joiner
    ("de 13 a 15", "from 13 to 15"), both from 7 to 23; (2) a number, a dash and a number with "h", "am" or "pm" ("13-15h", "1-2pm"), the first not behind a date cue. A
    range is not longer than 12 hours."""
    norm = _norm(text)
    out = []
    starts = nt._alt(listed(tables, "calendar", "range_from"))
    joins = nt._alt(listed(tables, "calendar", "range_to"))
    cues = {w for t in tables for w in t.get("date_cues", [])}
    if starts and joins:
        for m in re.finditer(rf"(?<![a-z0-9:/.]){starts}\s+([0-9]{{1,2}})\s*(?:{joins}|-)\s*([0-9]{{1,2}})h?(?![a-z0-9:])", norm):
            first, last = int(m.group(1)), int(m.group(2))
            if 7 <= first < last <= 23 and last - first <= 12:
                out.append(norm[:m.start()] + f"{first:02d}:00" + norm[m.end():])
    for m in re.finditer(r"(?<![a-z0-9:/.])([0-9]{1,2})\s*-\s*([0-9]{1,2})(h|am|pm)(?![a-z0-9])", norm):
        first, last, unit = int(m.group(1)), int(m.group(2)), m.group(3)
        if cues & set(re.findall(r"[a-z0-9]+", norm[:m.start()])[-2:]):
            continue
        if unit == "h":
            ok, begin = 7 <= first < last <= 23 and last - first <= 12, first
        else:
            begin = first % 12 + (12 if unit == "pm" else 0)
            end = last % 12 + (12 if unit == "pm" else 0)
            if unit == "pm" and begin >= end:
                begin -= 12
            ok = 1 <= first <= 12 and 1 <= last <= 12 and begin < end and end - begin <= 12
        if ok:
            out.append(norm[:m.start()] + f"{begin:02d}:00" + norm[m.end():])
    return out


def _norm(text: str) -> str:
    return nt.normalise(text)[0]


def _variants(window: list, text: str, tables: list, prefixes: list) -> list:
    """The texts of one window the time engine is asked about: the words as they are; the words with the bare hours of a range read the way the calendar family reads them
    (a deterministic rewrite: "9-10h" -> "09:00"); and, when the last line is a bare number (the answer to "at what time?"), the words with the introducing word the question
    machine puts before it ("at 21")."""
    out = [text] + _range_texts(text, tables)
    if re.fullmatch(r"[0-9]{1,2}", window[-1].strip()):
        out += [" ".join(window[:-1] + [prefix, window[-1]]) for prefix in prefixes]
    return out


_FACTS: dict = {}


def _facts(text: str, now, tables: list):
    """(the clocks written in `text`, the days it names alone, the (date, time) readings of the engine on it): what a window of the person's lines says about time. The
    engine is the slow part of the checker and a window is asked about again and again, so the answer is kept for the moment `now` and the tables it was made with."""
    key = (text, str(now), tuple(id(t) for t in tables))
    if key not in _FACTS:
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


def _time_problems(key, value, said, now, tables) -> list:
    """A start or end whose date and time are not a reading of the engine on the person's words (some window of consecutive lines). A start with a clock must be read
    TOGETHER with its day: the day and the clock are the two parts of one reading of one window, never a day from one place and a clock from another. An end is a clock the
    person wrote (the pairing with the start is checked by `problems`)."""
    day, _, clock = value.partition("T")
    seen_days, seen_times, pairs = set(), set(), set()
    written = False
    prefixes = [p for t in tables for p in t.get("bare_hour_prefixes", [])]
    for i in range(len(said)):
        for j in range(i + 1, len(said) + 1):
            text = " ".join(said[i:j])
            for variant in _variants(said[i:j], text, tables, prefixes):
                clocks, days, readings = _facts(variant, now, tables)
                seen_times |= clocks
                seen_days |= days
                for date, time in readings:
                    seen_days.add(date)
                    seen_times.add(time)
                    pairs.add((date, time))
            if clock and _hour_written(clock, text):
                written = True
    if not clock:
        return [] if day in seen_days else [f"{key} {value}: the day is not a reading of the person's words"]
    if key == "end":
        return [] if clock in seen_times or written else [f"{key} {value}: the time is not written"]
    return [] if (day, clock) in pairs else [f"{key} {value}: the day and the time are not one reading of the person's words"]


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


def candidate(line, languages=None):
    """What the line is, with no clock: {"family", "op"} | None. The same test as `read`, without the time engine."""
    got = read(line, None, languages)
    return {"family": got["family"], "op": got["op"]} if got else None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
