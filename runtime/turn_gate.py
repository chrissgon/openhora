#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The gate of a person's line: the one home of the limits PLAN-BRAIN section 4.1 re-homes. Each section names its limit and the contract row.

Operations layer. The module-level imports of this file are the standard library, `natural` (and `phrases`, which `natural` already loads), `natural_time` (which `natural` already loads) and `registry_data` (the pure loader of runtime/registry/*.json, S41-9), nothing else: `interpreter_route` and
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
  private_line(line)               True for a reminder asked in words or a write to the person's mail, calendar or files: the conversation stores a neutral word for it and its words
                                    never leave the host (limits L51, L61, L63). Its words and numbers are the data of runtime/registry/private_words.json (S41-9; the rule is the file's `rule` line
                                    and the docstring of the function); the detector flags every line `natural.private` flags, which stays in runtime/natural.py as the oracle of the tests until
                                    S41-11. Callers: `ops_interpret._no_decision`, `ops_natural.stored_line`, `interpreter.precheck` and `interpreter.check`.
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

Section 5. The fallback route (S41-10: contracts/runtime.md, limit L63, the outage path; the group `interpret-fallback`)

When the interpreter's call on the daily route cannot serve a line, one more route, of another vendor, may serve it for a sender who widened the group `interpret-fallback`. The routes are the ones the
newest dated entry of runtime/interpreter_enable.json names under `fallback` (`interpreter_enable.fallbacks`), each in force only with the hash it was measured on; the gate calls them only through the
same `call`, and only when ALL of these hold:

  * the caller gave `fallback` (the entry's routes) to `admit` and to `call`, and the sender held the group when `admit` made the admission (`Admission.fallback_ok`: the group is read from the project's
    policy by `admit` and carried as a flag, so that a caller that forgets the group, and the mail composer and the two revisers, which pass no fallback, can never reach a fallback);
  * the person's consent covers the companies in force (`_consented`): the record of the accepted file (cursor `config:fallbacks`, policy_widening.FALLBACKS) holds the keyed digest of every `route:hash` of
    the set in force, so a company the person was never shown (named by a dated entry after they widened the group) gets no line, whatever the group says; no store, no key or a fault is no consent;
  * the primary's call failed with an OUTAGE code (OUTAGE_CODES: E_TIMEOUT, E_NETWORK, E_RATE, E_UPSTREAM: the service did not answer or was out) or the primary's breaker was open when `call` began. Every other
    failure stays the caller's own: E_HTTP (a refusal, 4xx), E_RESPONSE (an empty, refused or oversize reply), E_KEY and E_USAGE (local faults), E_ROUTE (the entry's fault) and E_PIN (the reply names another
    provider or model than the row promises: a configuration mismatch or a safety signal, not an outage of the pinned provider) are not outages, and no second company is asked about them;
  * the fallback's row is a daily (http) route, other than the primary, asks the router for zero data retention (`zdr` true) and has the hash the entry names (else E_ROUTE and no request);
  * the fallback's own breaker is closed: each route has its own count of failures in a row and its own BREAKER_OPEN (`record(ok, route)`; the primary's is the section-1 state). `admit` also
    admits a line whose primary breaker is open when a fallback of a sender that holds the group is closed, and refuses it (None) when none is.

One admission covers the line: the rate and the day count it once, whatever the number of calls, and a line makes at most LINE_CALLS_MAX (2) calls, so the primary and one fallback, or two fallbacks when
the primary's breaker is open (D4: at most one more step and a bounded price per line). The fallback gets the same system and user text and the same settings as the primary, and only what is LEFT of the line's
deadline (`deadline_ms` minus the time the primary took; none is asked when less than MIN_FALLBACK_MS is left): the worst case of a line is the primary's own, the deadline plus the provider's 0.5 s margin (6.5 s
at the interpreter's 6 s), whatever the routes; after a primary that ended at its deadline (E_TIMEOUT) no time is left and only an open breaker lets a fallback serve the next lines. Nothing is added to either call and nothing is logged. Both routes failing is the caller's own fallback (a failed call: `_no_decision`). The result of a call that went to the fallback carries `attempts`
(`[(route or None for the primary, ok)]`), which `record_attempts(got)` records route by route; a result without it is recorded as before, `record(ok)`. A fallback call that ended in a code that is not an outage (a local fault, a refusal) counts nothing on that route's breaker.

Privacy (limit L63): the added state is a count of failures and a time for each fallback route, held in memory and keyed by the route's id; the text of a line is passed to the second vendor only for the senders who widened the group.

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
import natural  # noqa: E402  (the same folder: the decision numbers, which section 2 asks)
import natural_time as nt  # noqa: E402  (the same folder: the folding of a line and the time engine, which the private line asks)
from natural_time import find as time_hits  # noqa: E402  (the engine's search of the times a line holds)
import registry_data  # noqa: E402  (the same folder: the closed words of the private line, runtime/registry/private_words.json)

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
_breaker = {"fails": 0, "until": 0.0}      # the primary route's: the one the entry names (section 5 keeps the breakers of the fallback routes beside it)
_MINT = object()         # only `admit` holds it: nothing else can make an Admission


class Admission:
    """The right to make one call on the daily route. Made by `admit` only, used up by the first `call` that is given it; it holds two flags and nothing of the line."""

    def __init__(self, mint, fallback_ok=False):
        if mint is not _MINT:
            raise TypeError("an admission is made by turn_gate.admit only")
        self.used = False
        self.fallback_ok = fallback_ok is True      # section 5: the sender held the group `interpret-fallback` when `admit` made this admission

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
        _fallback_breakers.clear()


def admit(ctx: dict, sender, fallback=None):
    """An Admission when one more call may be made now (the breaker is closed and neither limit is reached), else None; the call is counted when it may be made. With `fallback` (the entry's outage
    routes, section 5) a line whose primary breaker is open is also admitted when the sender holds the group `interpret-fallback` and a fallback route's breaker is closed."""
    ops_natural = importlib.import_module("ops_natural")
    now = clock()
    day = (ops_natural.project_key(ctx["cfg"]["project"]), ops_natural._clock().date().isoformat())
    fallback_ok = _may_fall_back(ctx, sender, fallback)
    with _lock:
        if now < _breaker["until"] and not (fallback_ok and any(_closed(item["route"], now) for item in _fallback_items(fallback))):
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
    return Admission(_MINT, fallback_ok)


def record(ok: bool, route=None) -> None:
    """The end of an admitted attempt: a success closes the failures in a row, a failure counts and the BREAKER_FAILS-th opens the breaker. `route` None is the primary's breaker (the entry's route);
    a fallback route's id is that route's own (section 5)."""
    with _lock:
        state = _breaker if route is None else _fallback_breakers.setdefault(route, {"fails": 0, "until": 0.0})
        if ok:
            state["fails"] = 0
        else:
            state["fails"] += 1
            if state["fails"] >= BREAKER_FAILS:
                state["until"] = clock() + BREAKER_OPEN


def _call_route(route_id, route_sha256, system, user, deadline_ms, params, *, zdr_only=False) -> dict:
    """One request on one daily route: the row is taken from the daily routes (kind http), checked again against the hash the entry was decided on (the only one accepted) and, for a fallback, against `zdr`.
    Any other row is E_ROUTE and no request is made."""
    route = importlib.import_module("interpreter_route")
    rows = [r for r in route.daily_routes() if r["id"] == route_id]
    if len(rows) != 1 or rows[0].get("kind") != "http" or route.route_sha256(rows[0]) != route_sha256 or (zdr_only and rows[0].get("zdr") is not True):
        return {"ok": False, "code": "E_ROUTE"}
    return route.complete(rows[0]["id"], system, user, accepted=[route_sha256], deadline_ms=deadline_ms, **params)


def call(admission, entry: dict, system: str, user: str, *, deadline_ms, params: dict, fallback=None) -> dict:
    """The one model call on the daily route, made only with an unused Admission: the entry's route, taken from the daily routes (kind http) and checked again here, with the hash the
    entry was decided on as the only one accepted, and the caller's own deadline and settings. Any other route is E_ROUTE and no request is made; no admission is E_GATE and
    nothing is asked or checked. With `fallback` and an admission that holds `fallback_ok` the call may go on to the entry's outage routes (section 5)."""
    if not isinstance(admission, Admission) or not admission._use():
        return {"ok": False, "code": "E_GATE"}
    outage = _fallback_items(fallback) if admission.fallback_ok else []
    if not outage:
        return _call_route(entry["route"], entry["route_sha256"], system, user, deadline_ms, params)
    return _call_with_fallback(entry, outage, system, user, deadline_ms, params)


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

_PRIVATE: list = []      # the compiled rule of private_words.json, made on the first use (reload by `forget_private_rule`)


def _alternation(phrases):
    """The alternation of folded phrases as a regular expression, the longest first (a space in a phrase is any run of blanks), or None for no phrase."""
    items = sorted({p for p in phrases if p}, key=lambda p: (-len(p), p))
    return "(?:" + "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in items) + ")" if items else None


def _need(parts):
    """The test of one need of a write shape over `(line, norm, heads)`: True when ANY alternative of the need (merged over the languages) holds: a phrase of `words`; a digit; a colon;
    an `@` in the line; a line that holds nothing but the words of `only` and the shape's heads; or a tail of at most `tail_max` words that are not digits after the first phrase of
    `tail_after` (not counting the words of `tail_skip`)."""
    words = _alternation([w for part in parts for w in part.get("words", [])])
    only = {w for part in parts for w in part.get("only", [])}
    digit, colon, address = (any(part.get(key) for part in parts) for key in ("digit", "colon", "address"))
    pattern = re.compile(r"(?<![a-z0-9])" + words + r"(?![a-z0-9])") if words else None
    after = _alternation([w for part in parts for w in part.get("tail_after", [])])
    skip = {w for part in parts for w in part.get("tail_skip", [])}
    tail_max = max([part["tail_max"] for part in parts if "tail_max" in part] or [0])
    tail = re.compile(r"(?<![a-z0-9])" + after + r"(?![a-z0-9])") if after else None

    def short_tail(norm):
        view = re.sub(r"[\W_]+", " ", re.sub(r"[a-z0-9][a-z0-9-]{0,39}#[0-9]{1,4}", " 0 ", norm))      # an item reference "gmail#3" is a number: a list of them is long and still a reference
        found = tail.search(view)
        rest = view[found.end():] if found else ""
        return bool(found) and len([w for w in re.findall(r"[a-z0-9]+", rest) if not w.isdigit() and w not in skip]) <= tail_max

    def holds(line, norm, heads):
        split = re.sub(r"[\W_]+", " ", norm)      # "e-mail" with any other hyphen, dash, dot or underscore reads as "e mail", as the mail tokenizer reads it
        return bool((pattern and (pattern.search(norm) or pattern.search(split))) or (digit and re.search(r"\d", norm)) or (colon and ":" in norm) or (address and "@" in line)
                    or (only and all(w in only or w in heads for w in re.findall(r"[a-z0-9]+", norm))) or (tail and short_tail(norm)))
    return holds


def _compiled_rule():
    """The detector's data, compiled once from `registry_data.private_words()`: per language the regular expressions of the starts and the lists of the rule's steps, and, over all the
    languages together (the families of runtime/natural_writes_*.py read them together), each write shape of an operation with its heads and its needs (see `private_line`)."""
    if not _PRIVATE:
        found = registry_data.problems("private_words")
        if found:      # fail loud: a data file that does not hold the shape the detector reads must never leave a line silently non-private
            raise ValueError("runtime/registry/private_words.json is not well formed: " + "; ".join(found[:5]))
        data = registry_data.private_words()
        languages = [data["languages"][tag] for tag in sorted(data["languages"])]
        polite = _alternation([p for body in languages for p in body["polite"]])      # the polite words of every language, in any order: "hey, por favor marca ..."
        lead = f"[^a-z0-9]*(?:{polite}(?![a-z0-9])[\\s,;:]*)*" if polite else "[^a-z0-9]*"      # a comma after a polite word is part of it
        start = lambda phrases: re.compile(lead + _alternation(phrases) + r"(?![a-z0-9])") if phrases else None      # noqa: E731
        gap = data["numbers"]["verb_noun_gap_max"]
        steps, shapes = [], {}
        for body in languages:
            anywhere = _alternation(body["anywhere_with_time"])
            pair_verbs, pair_nouns = _alternation(body["verb_noun"]["verbs"]), _alternation(body["verb_noun"]["nouns"])
            steps.append({
                "lead": start(body["lead"]),
                "lead_write": start(body["lead_write"]),
                "lead_time": start(body["lead_with_time"]),
                "anywhere_time": re.compile(r"(?<![a-z0-9])" + anywhere + r"(?![a-z0-9])") if anywhere else None,
                "verb_noun": re.compile(lead + pair_verbs + r"\s+(?:[a-z0-9]+\s+){0," + str(gap) + r"}?" + pair_nouns + r"(?![a-z0-9])") if pair_verbs and pair_nouns else None,
                "starters": set(body["work_starters"]),
            })
            for family in sorted(body["writes"]):
                for shape in body["writes"][family]:
                    merged = shapes.setdefault(shape["op"], {"heads": [], "needs": [[] for _ in shape["needs"]]})
                    merged["heads"] += shape["heads"]
                    for slot, need in zip(merged["needs"], shape["needs"]):
                        slot.append(need)
        compiled = []
        for op in sorted(shapes):
            heads = _alternation(shapes[op]["heads"])
            if heads:
                head_words = {w for phrase in shapes[op]["heads"] for w in phrase.split()}
                compiled.append((re.compile(lead + heads + r"(?![a-z0-9])"), head_words, [_need(slot) for slot in shapes[op]["needs"]]))
        _PRIVATE.append((steps, compiled, data["numbers"]["bare_words_max"]))
    return _PRIVATE[0]


def forget_private_rule() -> None:
    """Drop the compiled rule (a test that edits a copy of the data, and a process that wants to read an edited file)."""
    _PRIVATE.clear()
    registry_data.forget()


def private_line(line) -> bool:
    """Whether the line is a reminder asked in words or a write to the person's mail, calendar or files: its words never leave the host and the conversation stores a neutral word for it.

    The words and the numbers are data, `runtime/registry/private_words.json` (S41-9), and its `rule` line states the rule: a line that is not a typed command (it does not start with "/")
    is private when it starts with a `lead` phrase (a reminder) or a `lead_write` phrase (a new event); or starts with a `lead_with_time` phrase and holds a time; or holds an
    `anywhere_with_time` phrase and a time; or starts with a `verb_noun` verb, at most `verb_noun_gap_max` words and a noun; or starts with the head of a write shape and holds every need
    of that shape; or has no question mark, a clock or a relative time, a first word that is not a work starter and at most `bare_words_max` words once the time is taken out. A start is
    read after blanks, marks (an "@" too) and polite words. A time is what the time engine (runtime/natural_time.py) finds. Every step is wider than the matching step of
    `natural.private`, which stays as the oracle of the tests until S41-11."""
    return private_kind(line) is not None


def private_kind(line):
    """"reminder" for a private line a reminder in words asks (a `lead`, `anywhere_with_time`, `verb_noun` or bare step), "write" for one that asks for a write to the person's mail, calendar or files
    (a `lead_write`, `lead_with_time` or write shape), None for a line that is not private; a line that starts as a new event is a write, as `natural.candidate` reads it first. `ops_natural.stored_line` stores the neutral word of the kind."""
    if not isinstance(line, str) or not line.strip() or line.lstrip().startswith("/"):
        return None
    steps, writes, bare_max = _compiled_rule()
    norm, origin = nt.normalise(line)
    found = []

    def hits():
        if not found:
            found.append(time_hits(line)["hits"])
        return found[0]
    if any(step["lead_write"] and step["lead_write"].match(norm) for step in steps):      # a new event is asked first, as natural.candidate reads it
        return "write"
    write = False
    for step in steps:
        if (step["lead"] and step["lead"].match(norm)) or (step["anywhere_time"] and step["anywhere_time"].search(norm) and hits()) or (step["verb_noun"] and step["verb_noun"].match(norm)):
            return "reminder"
        if step["lead_time"] and step["lead_time"].match(norm) and hits():
            write = True
    if write:
        return "write"
    if "?" not in line and any(h["kind"] in ("clock", "relative") for h in hits()):
        first = re.match(r"[^a-z0-9]*([a-z0-9]+)", norm)
        if not (first and any(first.group(1) in step["starters"] for step in steps)):
            rest = nt.without(line, _joined([(origin[h["s"]], origin[h["e"] - 1] + 1) for h in hits()]))
            if rest and len(rest.split()) <= bare_max:
                return "reminder"
    if any(heads.match(norm) and all(holds(line, norm, head_words) for holds in needs) for heads, head_words, needs in writes):
        return "write"
    return None


def _joined(spans) -> list:
    """The spans, touching or overlapping ones made one (what the time engine's own join does), sorted."""
    out = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


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


# --- section 5: the fallback route (L63, S41-10) -------------------------------------------------------------------------------------------------------

FALLBACK_GROUP = "interpret-fallback"      # the policy group a sender widens to let a line go to a second vendor (a kind-only group of the messaging channel, in no default)
FALLBACK_MAX = 2          # routes an entry may name as the outage path
LINE_CALLS_MAX = 2        # model calls one admitted line may make, whatever the routes (D4)
OUTAGE_CODES = ("E_TIMEOUT", "E_NETWORK", "E_RATE", "E_UPSTREAM")      # the codes of a service that is out: the only failures a second company is asked about
MIN_FALLBACK_MS = 1000    # less than this is left of the line's deadline: no fallback call
_fallback_breakers = {}   # a fallback route's id -> {"fails", "until"}, the same two numbers as `_breaker`; read and written under `_lock`


def _fallback_items(fallback) -> list:
    """The well-formed routes of the caller's `fallback`: at most FALLBACK_MAX items of `{"route": id, "route_sha256": hash}`, each route once, in order; anything else is dropped."""
    out, seen = [], set()
    for item in fallback if isinstance(fallback, (list, tuple)) else []:
        if isinstance(item, dict) and isinstance(item.get("route"), str) and isinstance(item.get("route_sha256"), str) and item["route"] not in seen and len(out) < FALLBACK_MAX:
            seen.add(item["route"])
            out.append({"route": item["route"], "route_sha256": item["route_sha256"]})
    return out


def _closed(route_id, now) -> bool:
    """Whether the fallback route's breaker is closed at `now` (the caller holds `_lock`)."""
    state = _fallback_breakers.get(route_id)
    return state is None or now >= state["until"]


def _consented(ctx, items) -> bool:
    """Whether the person's accepted file covers every company of `items`: the record of the store (policy_widening.FALLBACKS) holds the keyed digest of each `route:hash`, made with the project's key.
    No store, no key, no record or any fault is False: a company nobody was shown gets no line."""
    try:
        widening = importlib.import_module("policy_widening")
        held = ctx["store"].cursor_get(ctx["conn"], widening.FALLBACKS)
        secret = ctx["store"].cursor_get(ctx["conn"], widening.KEY)
        return bool(items) and bool(secret) and widening.fallbacks_covered(held, items, secret)
    except Exception:      # noqa: BLE001 - nothing readable is no consent
        return False


def _may_fall_back(ctx, sender, fallback) -> bool:
    """Whether this sender's line may go to a fallback route: the caller named one, the project's policy lists the group `interpret-fallback` for the sender (read here, at admission, from the
    configuration the context holds) and the person's accepted file covers the companies in force (`_consented`). Any fault is False."""
    items = _fallback_items(fallback)
    if not items:
        return False
    try:
        return importlib.import_module("operations").holds(FALLBACK_GROUP, "messaging", ctx["cfg"]["channels"], sender) is True and _consented(ctx, items)
    except Exception:      # noqa: BLE001 - no policy to read is no group
        return False


def _call_with_fallback(entry: dict, outage: list, system: str, user: str, deadline_ms, params: dict) -> dict:
    """The primary, then the outage routes (see the section's text); at most LINE_CALLS_MAX calls. A primary that answers, or that is E_ROUTE, is returned as `call` returns it (the caller records it as
    before); once a fallback has been asked, or the primary was skipped, the result carries `attempts` for `record_attempts`."""
    started = clock()
    with _lock:
        primary_open = started < _breaker["until"]
    attempts, calls, last = [], 0, None
    if not primary_open:
        last = _call_route(entry["route"], entry["route_sha256"], system, user, deadline_ms, params)
        calls = 1
        if last.get("ok") or last.get("code") not in OUTAGE_CODES:
            return last      # an answer, or a failure that is not an outage (a refusal, a local fault, E_ROUTE, E_PIN): the caller records it as before and no second company is asked
        attempts.append((None, False))
    for item in outage:
        if calls >= LINE_CALLS_MAX:
            break
        if item["route"] == entry["route"]:
            continue      # the entry's own route is never its fallback
        with _lock:
            if not _closed(item["route"], clock()):
                continue
        left = deadline_ms - round((clock() - started) * 1000)      # what is left of the line's deadline: the fallback never gets a fresh one
        if left < MIN_FALLBACK_MS:
            break
        got = _call_route(item["route"], item["route_sha256"], system, user, left, params, zdr_only=True)
        if got.get("code") == "E_ROUTE":
            continue      # a row the entry no longer matches asks nothing and counts nothing
        calls += 1
        last = got
        if got.get("ok") or got.get("code") in OUTAGE_CODES:
            attempts.append((item["route"], bool(got.get("ok"))))      # only an outage counts against a route's breaker
        if not got.get("ok") and got.get("code") not in OUTAGE_CODES:
            break      # a local fault or a refusal of the first would meet the second just the same
        if got.get("ok"):
            break
    return dict(last if last is not None else {"ok": False, "code": "E_BREAKER"}, attempts=attempts)


def record_attempts(got) -> None:
    """The end of an admitted line's calls: a result without `attempts` is one attempt on the primary (`record(ok)`, as before); a result with them records each, the primary's failure on the primary's
    breaker and a fallback's outcome on that route's own."""
    attempts = got.get("attempts") if isinstance(got, dict) else None
    if not isinstance(attempts, list):
        record(bool(isinstance(got, dict) and got.get("ok")))
        return
    for route, ok in attempts:
        record(ok) if route is None else record(ok, route)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
