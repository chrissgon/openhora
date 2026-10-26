#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The gate of a person's line: the one home of the limits PLAN-BRAIN section 4.1 re-homes. Each section names its limit and the contract row.

Operations layer. The module-level imports of this file are the standard library and `natural` (and `phrases`, which `natural` already loads), nothing else: `interpreter_route` and
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
                               Callers: `event_lookup.refresh`, `ops_items._refresh_failed`, `mail_refresh.refresh_once`.

What stays with each path: the age of a snapshot and the phone-only condition of the fresh lists (`ops_items`), the per-source lock and the 120 s cooldown of the mail lookup (`mail_refresh`): they are not
per-turn rules. A refreshed snapshot is read for one line and never a task's input (L53): nothing here touches `task_copies`.

Privacy (limit L63): the budget holds the identifiers of sources (a word of the person's own configuration) and one flag, in memory, for the length of the line, and nothing of the line.

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


def _words(items) -> str:
    return "|".join(re.escape(item).replace(r"\ ", " ") for item in sorted(set(items), key=len, reverse=True))


_NOUN = _words(NOUNS)
FORMS = (
    re.compile(r" (?:" + _words(POSSESSIVES) + r")(?: [a-z0-9]+){0,2} (?:" + _NOUN + r") "),
    re.compile(r" (?:" + _words(CLITIC_POSSESSIVES) + r")(?: [a-z0-9]+){0,1} (?:" + _NOUN + r") "),
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
_TURN = threading.local()      # the budget of the line this thread runs: {"sources": set of source ids, "mail_lookup": bool}, or nothing


@contextlib.contextmanager
def turn():
    """The refresh budget of one line on this thread. The outermost `with` creates it and clears it on exit, whatever the way out; an inner one (the same line, the same thread) reuses it."""
    outer = getattr(_TURN, "budget", None) is None
    if outer:
        _TURN.budget = {"sources": set(), "mail_lookup": False}
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


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
