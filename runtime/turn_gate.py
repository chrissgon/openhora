#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The gate of a person's line: the one home of the limits PLAN-BRAIN section 4.1 re-homes. Each section names its limit and the contract row.

Operations layer. The module-level imports of this file are the standard library, `natural` (and `phrases`, which `natural` already loads), `natural_time` and the toolkit of the pure module `natural_writes` that
section 4's value oracle reads (`LIST_MAX`, `Line`, `_facts`, `_tables`, `listed`, `service`; `natural_writes` loads the gate only when `problems` is called, never at import time), nothing else: `interpreter_route` and
`ops_natural` are loaded by `importlib` when a function needs them, so that a pure module (runtime/interpreter.py) can import the gate without joining an import cycle.

Section 1. The daily route's admission (contracts/runtime.md, limit L63, S7 and S13)

Every model call on the daily route a person's line can cause (the interpreter's call, the e-mail composer's, the two revisers') goes through this section and nowhere else:

  admit(ctx, sender)   an `Admission`, or None when the call may not be made now (the breaker is open, the sender's rate or the project's day is spent). The call is counted
                       when it may be made. An `Admission` is single-use, can only be made here, and holds nothing of the line (a flag and no text).
  call(admission, entry, system, user, *, deadline_ms, params)
                       the one place the route is called. It refuses (`{"ok": False, "code": "E_GATE"}`, no request) unless it is given an unused `Admission`; it checks the route again
                       (the entry's route among `interpreter_route.daily_routes()`, kind `http`, the hash the entry was decided on: else `{"ok": False, "code": "E_ROUTE"}`, no request)
                       and then asks `interpreter_route.complete` with that hash as the only one accepted. It does not record: each caller records the end of its attempt.
  record(ok)           the end of an attempt: a success closes the count of failures in a row, a failure counts, and BREAKER_FAILS in a row open the breaker for BREAKER_OPEN seconds.
                       A caller records exactly once for each admission, also when its attempt failed before the call.
  forget_all()         drop the counts and close the breaker (a test, and a process that stops).

The limits (counts in memory, this slice's choice, not measured): RATE_MAX calls per sender in RATE_WINDOW seconds, DAY_MAX per project per local day, and an open breaker for
BREAKER_OPEN seconds after BREAKER_FAILS failed calls in a row. The three callers share one set of counters; a test of any caller replaces `clock` here.

Privacy (limit L63): the gate keeps no line, span, model text or exception message: it holds a count per sender (the sender's own identifier, as before), a count per project
and local day, and the breaker's two numbers; the arguments of `call` are passed on and kept nowhere.

Section 2. The line checks (S41-5: taint, private routing, decision numbers from the line; contracts/runtime.md, limits L54 and L63, slice R2-F1)

Three checks of code over the person's own line. Each had one home and callers elsewhere; the homes moved here unchanged, no word, number or rule changed:

  research_allowed(question, line)  False when the question or the line holds a possessive form of a source of the project ("minha agenda", "my e-mails", "mon dossier", "mein Kalender",
                                    "la mia cartella"...): a question about the person's own data is not a web search (R2-F1). The bare noun is allowed ("agenda cultural", "the calendar of
                                    holidays"). `personal(*texts)` is the check itself and the lists (POSSESSIVES, CLITIC_POSSESSIVES, NOUNS) are the closed forms of the six languages the interpreter
                                    reads (pt-BR, en, es, fr, de, it); a possessive and a noun are at most two words apart, the Spanish and Italian "mi" counts only next to the noun or one word before it.
                                    Accents, case and punctuation do not matter. Callers: `ops_research._research`.
  private_line(line)                True for a reminder asked in words or a write to the person's mail or calendar (`natural.private`): the conversation stores a neutral word for it and its words
                                    never leave the host (limits L51, L61, L63). Callers: `ops_interpret._no_decision`, `ops_natural.stored_line`, `interpreter.precheck` and `interpreter.check`.
  the_number(line)                  the one whole number a line writes (`natural.decision_numbers`), None for none or for two or more; a number glued to a mark, followed by a unit or beside a
                                    currency, and every number of a line that says a date or a time, is not a number of a decision. Caller: `ops_interpret._decided`.
  number_believed(line, number)     a decision or an act that a MODEL or the router chose is believed for `number` only when `number` is a whole number (not a bool) and is the one number the line
                                    writes (limit L54: decision numbers only from the line). What the line means is not read here: the person says yes to the sentence code wrote (limit L65).
                                    Caller: `ops_natural.run`.

Privacy (limit L63): these functions keep nothing and print nothing; they are pure over the text they are given.

Section 3. One refresh per turn (S41-6: contracts/runtime.md, limits L52 and L53)

A person's line may make the runtime read a source the person chose again, never more than once for a source in one line and only through the source operation `source_refresh`. Three paths
do it, each for one purpose; before S41-6 each held a budget of its own (the calendar's structural, the phone list's per call, the mail lookup's thread-local). This section holds the one budget:

  turn()                       a context manager: opens the budget of one line on this thread. The outermost `with` on a thread creates it and the outermost exit clears it (also when the line
                               raised, so that the next line can refresh); an inner `with` on the same thread reuses it, so that a line that takes another entry (a write that becomes a plain line, a card
                               revised and a new card opened) is still one line. Opened by the entry points of the operations layer: `ops_say.say` (through `ops_turn.turn`), `ops_natural_writes.natural_write`,
                               `ops_card_revise.card_revise_check` and `card_revise`, `ops_items.items` and `ops_natural_mail.resolve`. A budget belongs to the thread that opened it.
  may_refresh(source_id, purpose)
                               whether the line may read `source_id` again now, for `purpose` ("calendar-miss", "list-fresh" or "mail-lookup"; any other word is refused). False outside a turn (fail
                               closed: a typed `source-refresh`, the routine's `ingest` and a test that calls a path directly have no turn and read nothing here; the typed command is not a line's
                               refresh and never asks the gate); False when the source was already read in this turn, for any purpose; for "mail-lookup" also False when a mail lookup already read in this
                               turn (the BL5E rule: one provider read for a line). A True marks the source (and the mail lookup) as spent, so the caller reads exactly once. It never reads a provider itself.
                               Callers: `event_lookup.refresh`, `ops_items._refresh_failed`, `mail_refresh.refresh_once`. A path that asks only when it would otherwise read must ask AFTER its own
                               checks that cost the line nothing (`mail_refresh` asks after its cooldown: a source that is cooling must not spend the one mail-lookup grant).
  mark_failed(source_id)       the line's read of `source_id` failed: remembered for this turn only (a no-op outside a turn), so that a second list of the same line, whose read the gate refuses, still
  failed_in_turn(source_id)    says the snapshot is old (`ops_items._refresh_failed` returns it); False outside a turn and for a source whose read did not fail in this turn.

What stays with each path: the age of a snapshot and the phone-only condition of the fresh lists (`ops_items`), the per-source lock and the 120 s cooldown of the mail lookup (`mail_refresh`): they are not
per-turn rules. A refreshed snapshot is read for one line and never a task's input (L53): nothing here touches `task_copies`.

Privacy (limit L63): the budget holds the identifiers of sources (a word of the person's own configuration) and one flag, in memory, for the length of the line, and nothing of the line.

Section 4. Provenance by origin per argument (S41-7: contracts/runtime.md, limits L55, L60 and L61)

A card that a person's LINE opens is opened by the operation's own function with arguments that a resolver made. Every resolver (`ops_natural_<family>.resolve`) and every seed says where each argument
came from, in `{"args", "origins"}`, and the card-opening paths ask the gate before they open anything (`ops_natural_writes._opened`, `ops_file_trash._card`, `ops_event_revise.revise`). FAIL CLOSED
(OPEN-41-8, recommended): what the table does not name opens no card.

  ORIGINS            the closed vocabulary: `line-span` (the person's words, in the line or in an answer), `line-number` (a number written in it), `time-engine` (a time the engine of NR-1 read), `config` (a name of the
                     accepted `accounts`, their default, the account of a registered source), `picked` (an option code listed and the person chose), `listed` (a number of a list code showed this sender),
                     `grounded` (an item code found by searching with a span of the line: the event ranking, the mail index match, the file search: the ITEM, never an address), `index-from` (a reply's recipient
                     from the index), `held` (a file this sender sent and the hold keeps), `card-copy` (a part copied by code from the card being revised), `composed` (the subject or the body of an e-mail worded by
                     the compose or the revise call).
  ALLOWED            the origins each argument key may have. An address (`to`, `cc`, `bcc`) is `line-span`, `config`, `index-from` or `card-copy` and nothing else (L60); `composed` is the text of an e-mail
                     (`subject`, `body`, `text`) and nothing else; a time is `time-engine` or `card-copy`; a message, an event or a file is `line-number`, `listed`, `picked` or `grounded` (an event may also be
                     `card-copy`); an account, a calendar and a folder are `config`, `picked`, `line-span` or `card-copy`; an attachment is `held`; a title, a content and a name are `line-span` or `card-copy`.
                     A key with no row is refused.
  OPS                the arguments each operation of a card opened from a line takes. Any other key is refused: a reply and a reply draft have no recipient argument, its recipient is the index's From, chosen by the
                     effect (L60).
  provenance(op, args, origins)
                     the problems, as `"<key>: <what>"` (key names and origin words, never a value), or []: an operation not in OPS, a key the operation does not take, an argument with no origin, an origin outside
                     ORIGINS and an origin its key may not have are each a problem. `refusal_line` (the one line on stderr: the operation and the key names) and `refusal_text` (the precise error where a person reads it;
                     a phone is asked again in the plain sentence IX_ASK_AGAIN, limit L62) never hold a value.
  Seed(parts, origins)   a seed (what `open_line` takes in place of a line) with the origin of each part that is not the person's own words; it equals the plain dict. `origin_of(slots, key, default)` reads the
                     origin the draft recorded for a slot (a pick, a seed's part), else the default of the slot; `account_origin(slots, wanted)` is the account's.
  value_problems(op, args, said, accounts, offered, now, languages=None)
                     the value oracle of the fuzzers (`natural_writes.problems` until S41-7): why the arguments of a write about to be opened are not all from the person's lines. Moved unchanged (a test holds the sha256
                     of every function); `natural_writes.problems` is a delegate until S41-11 deletes the line-claiming forms of that module, which must keep what the oracle reads of it.

Privacy (limit L63): the checks are pure over the arguments and the origins they are given and keep and print nothing of a value.

Runs on Python 3.9: python3 runtime/turn_gate.py --help
"""
from __future__ import annotations

import collections
import contextlib
import importlib
import os
import re
import sys
import threading
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural  # noqa: E402  (the same folder: the closed forms of the private line and of the decision numbers, which section 2 asks)
import natural_time as nt  # noqa: E402  (the same folder: the value oracle of section 4 reads the engine's facts)
from natural_writes import LIST_MAX, Line, _facts, _tables, listed, service  # noqa: E402  (the same folder: the toolkit of the families the value oracle of section 4 reads; it imports no gate at load time)

# --- section 1: the daily route's admission (L63) ------------------------------------------------------------------------------------------------------

RATE_MAX = 10          # calls per sender in RATE_WINDOW seconds
RATE_WINDOW = 60.0
DAY_MAX = 300          # calls per project per local day
BREAKER_FAILS = 3        # failed calls in a row that open the breaker
BREAKER_OPEN = 300.0     # seconds it stays open
clock = time.monotonic   # the clock of the rate window and of the breaker (a test replaces it)

_lock = threading.Lock()
_calls = {}              # sender -> times of its calls inside the window
_days = {}               # (project key, local day) -> calls
_breaker = {"fails": 0, "until": 0.0}
_MINT = object()         # only `admit` holds it: nothing else can make an Admission


class Admission:
    """The right to make one call on the daily route. Made by `admit` only, used up by the first `call` that is given it; it holds a flag and nothing of the line."""

    def __init__(self, mint):
        if mint is not _MINT:
            raise TypeError("an admission is made by turn_gate.admit only")
        self.used = False

    def _use(self) -> bool:
        """True once: the first use marks it used, and the second finds it used."""
        with _lock:
            if self.used:
                return False
            self.used = True
            return True

    def __repr__(self) -> str:
        return "<Admission used>" if self.used else "<Admission>"


def forget_all() -> None:
    """Drop the counts and close the breaker (a test, and a process that stops)."""
    with _lock:
        _calls.clear()
        _days.clear()
        _breaker.update(fails=0, until=0.0)


def admit(ctx: dict, sender):
    """An Admission when one more call may be made now (the breaker is closed and neither limit is reached), else None; the call is counted when it may be made."""
    ops_natural = importlib.import_module("ops_natural")
    now = clock()
    day = (ops_natural.project_key(ctx["cfg"]["project"]), ops_natural._clock().date().isoformat())
    with _lock:
        if now < _breaker["until"]:
            return None
        window = _calls.setdefault(sender or "", collections.deque())
        while window and now - window[0] >= RATE_WINDOW:
            window.popleft()
        if len(window) >= RATE_MAX or _days.get(day, 0) >= DAY_MAX:
            return None
        window.append(now)
        for old in [k for k in _days if k[1] != day[1]]:
            del _days[old]
        _days[day] = _days.get(day, 0) + 1
    return Admission(_MINT)


def record(ok: bool) -> None:
    """The end of an admitted attempt: a success closes the failures in a row, a failure counts and the BREAKER_FAILS-th opens the breaker."""
    with _lock:
        if ok:
            _breaker["fails"] = 0
        else:
            _breaker["fails"] += 1
            if _breaker["fails"] >= BREAKER_FAILS:
                _breaker["until"] = clock() + BREAKER_OPEN


def call(admission, entry: dict, system: str, user: str, *, deadline_ms, params: dict) -> dict:
    """The one model call on the daily route, made only with an unused Admission: the entry's route, taken from the daily routes (kind http) and checked again here, with the hash the
    entry was decided on as the only one accepted, and the caller's own deadline and settings. Any other route is E_ROUTE and no request is made; no admission is E_GATE and
    nothing is asked or checked."""
    if not isinstance(admission, Admission) or not admission._use():
        return {"ok": False, "code": "E_GATE"}
    route = importlib.import_module("interpreter_route")
    rows = [r for r in route.daily_routes() if r["id"] == entry["route"]]
    if len(rows) != 1 or rows[0].get("kind") != "http" or route.route_sha256(rows[0]) != entry["route_sha256"]:
        return {"ok": False, "code": "E_ROUTE"}
    return route.complete(rows[0]["id"], system, user, accepted=[entry["route_sha256"]], deadline_ms=deadline_ms, **params)


# --- section 2: the line checks (L54, L63, R2-F1) ------------------------------------------------------------------------------------------------------

# taint (slice R2-F1): moved verbatim from runtime/research_guard.py (deleted by S41-5)
# The possessives (a word that can only possess) and the nouns of the project's sources, folded: lower case, no accent, every other character a space.
POSSESSIVES = ["my", "meu", "meus", "minha", "minhas", "mis", "mon", "ma", "mes", "mein", "meine", "meinen", "meinem", "meiner", "meines", "mio", "mia", "miei", "mie"]
CLITIC_POSSESSIVES = ["mi"]      # a possessive in Spanish and a pronoun in Italian: only next to the noun or one word before it
NOUNS = [
    # calendar
    "calendar", "calendars", "agenda", "agendas", "schedule", "calendario", "calendarios", "calendrier", "calendriers", "kalender", "terminkalender",
    # mail
    "email", "emails", "e mail", "e mails", "mail", "mails", "inbox", "mailbox", "caixa de entrada", "caixa de e mail", "correo", "correos", "courrier", "courriers", "posteingang",
    "posta", "casella di posta",
    # files, documents, folders, drive
    "file", "files", "arquivo", "arquivos", "archivo", "archivos", "fichier", "fichiers", "datei", "dateien", "documento", "documentos", "documento", "document", "documents",
    "dokument", "dokumente", "documenti", "folder", "folders", "pasta", "pastas", "carpeta", "carpetas", "dossier", "dossiers", "ordner", "cartella", "cartelle", "drive", "onedrive",
    "google drive",
]


def fold(text) -> str:
    """The text folded for the check: lower case, accents removed, every run of other characters a single space."""
    if not isinstance(text, str):
        return ""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return " " + re.sub(r"[^a-z0-9]+", " ", plain).strip() + " "


def _alternation(items) -> str:
    return "|".join(re.escape(item).replace(r"\ ", " ") for item in sorted(set(items), key=len, reverse=True))


_NOUN = _alternation(NOUNS)
FORMS = (
    re.compile(r" (?:" + _alternation(POSSESSIVES) + r")(?: [a-z0-9]+){0,2} (?:" + _NOUN + r") "),
    re.compile(r" (?:" + _alternation(CLITIC_POSSESSIVES) + r")(?: [a-z0-9]+){0,1} (?:" + _NOUN + r") "),
)


def personal(*texts) -> bool:
    """Whether any of the texts holds a possessive form of a source of the project (see the module's text)."""
    for text in texts:
        folded = fold(text)
        if folded.strip() and any(form.search(folded) for form in FORMS):
            return True
    return False


def research_allowed(question, line) -> bool:
    """Whether the question may go to a web search: False when the question or the line holds a possessive form of a source of the project (see the section's text)."""
    return not personal(question, line)


# private routing (limits L51, L61, L63)

def private_line(line) -> bool:
    """Whether the line is a reminder asked in words or a write to the person's mail or calendar: its words never leave the host and the conversation stores a neutral word for it."""
    return natural.private(line)


# decision numbers from the line (limit L54)

def the_number(line):
    """The one whole number the line writes (`natural.decision_numbers`: none in a line that says a date or a time), or None when it writes none or two or more."""
    numbers = natural.decision_numbers(line if isinstance(line, str) else "")
    return numbers[0] if len(numbers) == 1 else None


def number_believed(line, number) -> bool:
    """Whether a decision or an act that a model or the router chose on `number` is believed against the person's line: `number` is a whole number (not a bool) and is the one number
    the line writes. What the line MEANS is not read here: the person is shown the sentence code wrote from the call and says yes (limit L65)."""
    return isinstance(number, int) and not isinstance(number, bool) and the_number(line) == number


# --- section 3: one refresh per turn (L52, L53) --------------------------------------------------------------------------------------------------------

REFRESH_PURPOSES = ("calendar-miss", "list-fresh", "mail-lookup")
_TURN = threading.local()      # the budget of the line this thread runs: {"sources": set of source ids, "mail_lookup": bool, "failed": set of source ids whose read failed}, or nothing


@contextlib.contextmanager
def turn():
    """The refresh budget of one line on this thread. The outermost `with` creates it and clears it on exit, whatever the way out; an inner one (the same line, the same thread) reuses it."""
    outer = getattr(_TURN, "budget", None) is None
    if outer:
        _TURN.budget = {"sources": set(), "mail_lookup": False, "failed": set()}
    try:
        yield
    finally:
        if outer:
            _TURN.budget = None


def may_refresh(source_id, purpose) -> bool:
    """Whether the line may read `source_id` again now (see the section's text): False outside a turn, for a source already read in this turn and, for "mail-lookup", after a mail lookup already
    read; a True spends the budget, so it is asked once for each read. It never reads a provider."""
    budget = getattr(_TURN, "budget", None)
    if budget is None or purpose not in REFRESH_PURPOSES or not isinstance(source_id, str) or not source_id:
        return False
    if source_id in budget["sources"] or (purpose == "mail-lookup" and budget["mail_lookup"]):
        return False
    budget["sources"].add(source_id)
    if purpose == "mail-lookup":
        budget["mail_lookup"] = True
    return True


def mark_failed(source_id) -> None:
    """Remember that the line's read of `source_id` failed (see the section's text); nothing outside a turn."""
    budget = getattr(_TURN, "budget", None)
    if budget is not None and isinstance(source_id, str) and source_id:
        budget["failed"].add(source_id)


def failed_in_turn(source_id) -> bool:
    """Whether the line's read of `source_id` failed in this turn: False outside a turn."""
    budget = getattr(_TURN, "budget", None)
    return budget is not None and source_id in budget["failed"]


# --- section 4: provenance by origin per argument (L55, L60, L61) --------------------------------------------------------------------------------------------

# Where an argument of a card that a line opens came from. A closed vocabulary: a resolver says which word each argument has, and nothing else is believed.
ORIGINS = (
    "line-span",      # the person's own words in the line, or in an answer to a question (a title, a subject, a body, a content, an address typed whole, a name of the configuration written in it)
    "line-number",    # a number written in the line (an event, a message, a reference)
    "time-engine",    # a time read by the engine of NR-1 on the person's words
    "config",         # a name of the accepted `accounts`, their default, or the account of a registered source
    "picked",         # an option code listed and the person chose
    "listed",         # a number of a list code showed this sender
    "grounded",       # an item code found by searching with a span of the line (the event ranking, the mail index match, the file search): the item, never an address
    "index-from",     # a reply's recipient taken from the index's From of the message answered
    "held",           # a file this sender sent and the hold keeps
    "card-copy",      # copied by code from the card that is being revised
    "composed",       # the subject or the body of an e-mail worded by the compose or the revise call (limits L63, slices S7 and S13)
)
_ADDRESSEES = ("line-span", "config", "index-from", "card-copy")      # L60: a recipient is never read from a body, a subject, a Reply-To or the index's other fields
_TEXTS = ("line-span", "card-copy")
_WORDED = ("line-span", "composed", "card-copy")      # the text of an e-mail: the person's words, or the model's wording of them (never an address, never a title)
_ITEMS = ("line-number", "listed", "picked", "grounded")
_NAMES = ("config", "picked", "line-span", "card-copy")
_TIMES = ("time-engine", "card-copy")
# The origins an argument may have, by the key the operation's own function takes. A key with no row here is refused: the table is closed.
ALLOWED = {
    "to": _ADDRESSEES, "cc": _ADDRESSEES, "bcc": _ADDRESSEES,
    "subject": _WORDED, "body": _WORDED, "text": _WORDED,
    "title": _TEXTS, "content": _TEXTS, "name": _TEXTS, "file_name": _TEXTS,
    "event": _ITEMS + ("card-copy",), "message": _ITEMS, "messages": _ITEMS, "file": _ITEMS,
    "account": _NAMES, "calendar": _NAMES, "folder": _NAMES, "mail_folder": _NAMES,
    "start": _TIMES, "end": _TIMES,
    "attachment": ("held",),
    "state": ("line-span", "picked"),
    "location": ("card-copy",), "notes": ("card-copy",), "reminder_minutes": ("card-copy",),      # carried over from the card an event's revision replaces
}
# The arguments each operation of a card opened from a line takes (the keys of the operation's own function, as the resolvers of the families return them). Any other key is refused, so a
# reply or a reply draft has no `to`: its recipient is the index's From, chosen by the effect (L60).
OPS = {
    "event-create": ("account", "title", "start", "end", "calendar", "location", "reminder_minutes", "notes"),
    "event-change": ("account", "event", "calendar", "title", "start", "end", "location", "reminder_minutes", "notes"),
    "event-cancel": ("account", "event"),
    "file-create": ("account", "file_name", "content", "folder"),
    "file-replace": ("account", "file", "content"),
    "file-save": ("account", "attachment", "folder"),
    "file-trash": ("account", "file", "folder"),
    "mail-send": ("account", "to", "subject", "text"),
    "mail-reply": ("account", "message", "text"),
    "mail-draft": ("account", "to", "subject", "body", "message"),
    "mail-archive": ("account", "messages"),
    "mail-trash": ("account", "messages"),
    "mail-move": ("account", "messages", "folder"),
    "mail-mark": ("account", "messages", "state"),
}


def _name(word) -> str:
    """A key or an operation as a closed word, or "?": what a problem names is a word of code, never a value."""
    return word if isinstance(word, str) and re.fullmatch(r"[a-z_-]{1,32}", word) else "?"


def provenance(op, args, origins) -> list:
    """The problems of a card about to be opened for a line, as `"<key>: <what>"` (key names and origin words only, never a value), or [] when every argument is allowed. Closed on every
    side: an operation that is not in OPS, an argument it does not take, an argument with no origin, an origin that is not one of ORIGINS and an origin its key may not have are each a problem."""
    if op not in OPS:
        return [f"{_name(op)}: not an operation opened from a line"]
    if not isinstance(args, dict) or not isinstance(origins, dict):
        return ["arguments: no origins"]
    out = []
    for key in args:
        name = _name(key)
        if key not in OPS[op] or key not in ALLOWED:
            out.append(f"{name}: not an argument of {op}")
            continue
        origin = origins.get(key)
        if not isinstance(origin, str) or origin not in ORIGINS:
            out.append(f"{name}: no origin")
        elif origin not in ALLOWED[key]:
            out.append(f"{name}: origin {origin} not allowed")
    return out


class Seed(dict):
    """The seed of a card (what `ops_natural_writes.open_line` takes in place of a line: an event found by its words, a new e-mail the interpreter decided, a card's own parts) with the origin of
    each part that is not the person's own words, as `seed.origins` ({slot: origin}). It IS the dict and equals it (a test that compares a seed with a plain dict still passes); a plain dict is a
    seed whose parts have the origin of the slot by default."""

    def __init__(self, parts: dict, origins: dict):
        super().__init__(parts)
        self.origins = dict(origins)


def origin_of(slots: dict, key: str, default: str) -> str:
    """The origin a slot of a draft was recorded with (a pick, a seed whose part was not the person's own words), else `default`: the origin that the reading of a line and the answers to its
    questions give that slot. The record is `slots["_origins"]`, put there by the card-opening path for the resolver; no value is ever read from it."""
    return (slots.get("_origins") or {}).get(key) or default


def account_origin(slots: dict, wanted) -> str:
    """The origin of the account a resolver chose: what the person gave or picked (the origin recorded for the slot, `line-span` by default) when `wanted` was given, else the configuration's
    (the registered source's account, the one configured account or `accounts.default`)."""
    return origin_of(slots, "account", "line-span") if wanted else "config"


def refusal_line(op, problems) -> str:
    """The one line a refused opening leaves on stderr: the operation and the names of the arguments, nothing of their values."""
    keys = sorted({str(p).partition(":")[0] for p in problems})
    return f"gate: provenance refused {_name(op)} ({', '.join(keys)})"


def refusal_text(op, problems) -> str:
    """The sentence of a refused opening where a person reads the precise error (the terminal and the page, limit L62: a phone gets a plain sentence of its own): the operation and the names of
    the arguments, nothing of their values."""
    keys = sorted({str(p).partition(":")[0] for p in problems})
    return f"error: nothing was opened: an argument of {_name(op)} was not from your words or your choice ({', '.join(keys)})"


# --- the value oracle: moved unchanged from runtime/natural_writes.py (S41-7), where it was the fuzz's check; `def problems` is `def value_problems` and nothing else of it changed ---

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


def value_problems(op: str, args: dict, said: list, accounts: dict, offered: dict, now, languages=None) -> list:
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
            if not (op.startswith("mail-") and (_of_service(value, said, tables) or _mailbox_account(value, args, said, offered, picks if options is None else bool(options), tables))):
                out += _account_problems(op, value, lines, accounts, offered, picks if options is None else value in options, tables)
        elif key in ("calendar", "folder"):
            section = "calendars" if key == "calendar" else "mail_folders" if op.startswith("mail-") else "folders"
            listed = ((accounts.get(args.get("account")) or {}).get(section)) or {}
            if value not in listed or not (any(_contiguous(_words(value), w) for w in line_words) or (picks if options is None else value in options)):
                out.append(f"{key} {value!r} is not a configured name written or picked")
        elif key in ("to", "cc", "bcc"):
            out += _address_problems(key, value, said, tables)
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


# --- the provenance of a mail write: derived from the person's RAW lines, never from a reading of the mail family ----------------------------------------------
#
# The checks below take the closed marker words of the language tables (the `mail` lists) and look at the raw line with small expressions of their own. They do not call the
# mail family (`read`, `match_words`, `answer`), so a misreading of the family cannot vouch for itself: an address must stand in the recipients' part of a line (after a
# recipient marker, before the subject marker, the body marker or the first colon), a number in the references' part (after the object, before the body, the folder or the
# state words), a message found by words must match the words written after an "of" marker, and a state is a state word at the end of a line.

ADDRESS = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class _Frame:
    """The parts of one raw line of a mail write, found with the marker words of the tables (folded positions; `part` gives the raw text of a part)."""

    def __init__(self, text: str, tables: list):
        self.line, self.tables = Line(text), tables
        norm = self.line.norm
        noun = self.line.find(listed(tables, "mail", "nouns"))
        self.noun = noun
        self.after = noun[1] if noun else 0
        self.subject = self.line.find(listed(tables, "mail", "subject"), self.after)
        body = self.line.find(listed(tables, "mail", "body"), self.after)
        colon = norm.find(":", self.after)
        self.body_at = min([m[0] for m in (body,) if m] + ([colon] if colon >= 0 else []), default=None)
        self.stop = min([m[0] for m in (self.subject,) if m] + ([self.body_at] if self.body_at is not None else []), default=len(norm))

    def part(self, start: int, end: int) -> str:
        return self.line.span(start, end) if start < end else ""

    def recipients(self) -> str:
        to = self.line.find(listed(self.tables, "mail", "to"), self.after)
        return self.part(to[1], max(self.stop, to[1])) if to else ""

    def references_end(self) -> int:
        """Where the references end: the body, the subject, a folder marker or a state word (whichever comes first)."""
        ends = [self.stop]
        for key in ("read", "unread"):
            found = self.line.find(listed(self.tables, "mail", key), self.after)
            if found:
                ends.append(found[0])
        markers = self.line.find_all(listed(self.tables, "mail", "folder"), self.after)
        if markers:      # the last folder marker with a name after it: a number alone, or a state or a service clause, is not a folder ("1 to 3 as read" is a range)
            tail = self.line.norm[markers[-1][1]:]
            clauses = listed(self.tables, "mail", "read") + listed(self.tables, "mail", "unread") + [p + " " + n for p in listed(self.tables, None, "service_in") + [""]
                                                                                                       for a in ("google", "microsoft") for n in listed(self.tables, "services", a)]
            alt = nt._alt(clauses)
            rest = re.sub(rf"(?<![a-z0-9]){alt}(?![a-z0-9])", " ", tail) if alt else tail
            if rest.strip() and not rest.strip().isdigit():
                ends.append(markers[-1][0])
        return min(ends)

    def references(self) -> str:
        return self.part(self.after, self.references_end()) if self.noun else ""


def _address_problems(key: str, value, said: list, tables: list) -> list:
    """The addresses of a recipient list (at most 20) must each stand in the recipients' part of a line (after a recipient marker, before the subject, the body or a colon), or
    be the whole of a line that is nothing but addresses (the answer to "what is the address?"): never inside a body or a subject, never found in a mailbox."""
    addresses = [a for a in str(value).split(",") if a]
    if not addresses or len(addresses) > 20:
        return [f"{key} is {len(addresses)} addresses: an e-mail takes 1 to 20"]
    joiners = set(listed(tables, None, "joiners"))
    regions = []
    for text in said:
        regions.append(_Frame(text, tables).recipients().lower())
        bare = ADDRESS.sub(" ", text)
        if ADDRESS.search(text) and all(w in joiners for w in re.findall(r"[a-z]+", natural.normal(bare))):
            regions.append(text.lower())
    return [f"{key} {a!r} is not an address written as a recipient" for a in addresses if not any(a.lower() in region for region in regions)]


def _written_numbers(text: str, tables: list) -> set:
    """The numbers a part of a line writes: its digit groups, and every number between two of them joined by a range word of the tables or a dash."""
    folded = natural.normal(text)
    out = {int(n) for n in re.findall(r"[0-9]{1,9}", folded)}
    ranges = nt._alt(listed(tables, None, "range"))
    for a, b in re.findall(rf"([0-9]{{1,9}})\s+(?:{ranges})\s+([0-9]{{1,9}})", folded) if ranges else []:
        if int(a) < int(b) <= int(a) + 40:
            out |= set(range(int(a), int(b) + 1))
    for a, b in re.findall(r"([0-9]{1,9})\s*-\s*([0-9]{1,9})", text):
        if int(a) < int(b) <= int(a) + 40:
            out |= set(range(int(a), int(b) + 1))
    return out


def _entry_words(entry: dict) -> set:
    """The whole words of a message of an index (its sender's address and its subject), written again here from the rule of the contract, not taken from the family."""
    local, _, domain = str(entry.get("from_address") or "").partition("@")
    labels = domain.lower().split(".")
    pieces = [local] + (labels[:-1] if len(labels) > 1 else labels) + [str(entry.get("subject") or "")]
    return {w for piece in pieces for w in re.findall(r"[a-z0-9]+", _norm(piece))}


def _words_of_the_line(frame: _Frame, tables: list) -> list:
    """The content words written after the first "of" marker, up to where the references end, without a service clause at the end and without the little words."""
    of = frame.line.find(listed(tables, "mail", "of"), frame.after)
    if not of:
        return []
    end = frame.references_end()
    served = service(frame.line, tables, of[1], end)
    words = [(w, s_, e_) for w, s_, e_ in frame.line.words_after(of[1]) if e_ <= end and not (served and served[1] <= s_ and e_ <= served[2])]
    little = {w for phrase in listed(tables, None, "articles") + listed(tables, None, "joiners") + listed(tables, "mail", "of") for w in phrase.split()}
    return [w for w, _s, _e in words if w not in little]


def _message_problems(key: str, value, said: list, offered: dict, tables: list, options) -> list:
    """Each `<source>#<n>` of a message write: the source is a mailbox code listed (`offered["mail_index"]`: {source: entries of its index}), and the number is written in the
    references' part of a line (or is the whole of a line of numbers), is an option the person was shown (`offered["options"]`), is the first message for "the latest", or is
    the unique match (a plural object: every match, up to 20) of the words written after an "of" marker."""
    refs = [r for r in str(value).split(",") if r]
    index = offered.get("mail_index") or {}
    if not refs or len(refs) > LIST_MAX:
        return [f"{key} is {len(refs)} messages: a card takes 1 to {LIST_MAX}"]
    only_numbers = nt._alt(listed(tables, None, "joiners") + listed(tables, None, "range"))
    written, words, newest, plural, named = set(), None, False, False, ""
    for text in said:
        frame = _Frame(text, tables)
        if frame.noun:
            region = frame.references()
            written |= _written_numbers(region, tables)
            named += " " + region.lower()
            found = _words_of_the_line(frame, tables)
            words = found or words
            newest = newest or bool(frame.line.find(listed(tables, "mail", "newest")))
            plural = plural or bool(frame.line.find(listed(tables, "mail", "plural"), frame.noun[0], frame.noun[1]))
        elif re.fullmatch(rf"[0-9\s,;#-]*(?:(?:{only_numbers})[0-9\s,;#-]*)*" if only_numbers else r"[0-9\s,;#-]*", natural.normal(text)) and natural.normal(text):
            written |= _written_numbers(text, tables)      # a line of numbers alone answers "which one?"
    out = []
    for ref in refs:
        source, _, n = ref.partition("#")
        if source not in index or not n.isdigit():
            out.append(f"{ref!r} is not a message of a mailbox code listed")
            continue
        n = int(n)
        strong = sorted(e["n"] for e in index[source] if words and set(words) <= _entry_words(e))
        by_words = n in strong and (len(strong) == 1 or (plural and not newest and len(strong) <= LIST_MAX)) or bool(newest and strong and n == strong[0])
        if not (n in written or ref in (offered.get("options") or ()) or ref in named or (newest and not words and n == 1) or by_words):
            out.append(f"message {ref} is not written in the references, shown or the unique match of the words")
    if words and plural and not newest and not written and not out:      # a plural object found by words is the WHOLE set of matches (up to a card), unless the person chose among them
        for source in {r.partition("#")[0] for r in refs}:
            strong = {e["n"] for e in index[source] if set(words) <= _entry_words(e)}
            given = {int(r.partition("#")[2]) for r in refs if r.partition("#")[0] == source}
            if len(strong) <= LIST_MAX and given != strong and not all(r in (offered.get("options") or ()) for r in refs):
                out.append(f"messages {sorted(given)} are a part of the {len(strong)} that hold the words")
    return out


def _state_said(value: str, said: list, tables: list) -> bool:
    """Whether a line ends in the state words of `value`, or is nothing but them or their tail ("lido" for "como lido"). The words of "unread" are tried first: a line that
    ends in them says "unread", whatever its last word is."""
    for text in said:
        norm = natural.normal(text)
        unread = [p for p in listed(tables, "mail", "unread") if norm.endswith(p) or norm == " ".join(p.split()[1:])]
        if unread:
            if value == "unread":
                return True
            continue
        if value == "read" and any(norm.endswith(p) or norm == " ".join(p.split()[1:]) for p in listed(tables, "mail", "read")):
            return True
    return False


def _of_service(value: str, said: list, tables: list) -> bool:
    """Whether a line ends its references with an "of" word and the name of the service of `value` ("os e-mails 2 e 4 do gmail", "emails 2 and 4 from gmail"): the "of" word
    introduces the bare name, as `service_in` does elsewhere."""
    of = nt._alt(listed(tables, "mail", "of"))
    names = nt._alt(listed(tables, "services", value))
    if not of or not names:
        return False
    return any(_Frame(text, tables).noun and re.search(rf"(?<![a-z0-9]){of}\s+{names}\s*$", natural.normal(_Frame(text, tables).references())) for text in said)


def _mailbox_account(value: str, args: dict, said: list, offered: dict, picked: bool, tables: list) -> bool:
    """Whether the account of a write on messages is the account of their mailbox: the references' sources all belong to `value`, and the mailbox is the only one code listed, is
    written in the references' part of a line, or was picked."""
    sources = offered.get("mail_sources") or {}
    refs = [r for r in str(args.get("messages") or args.get("message") or "").split(",") if r]
    if not refs or any(sources.get(r.partition("#")[0]) != value for r in refs):
        return False
    written = " ".join(_Frame(text, tables).references().lower() for text in said)
    return len(sources) == 1 or picked or any(re.search(rf"(?<![a-z0-9]){re.escape(r.partition('#')[0])}(?![a-z0-9])", written) for r in refs)


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


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
