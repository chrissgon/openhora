#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""An event of the person's own calendar named by its words (slice S6): "remove the haircut for tomorrow", "move the dentist to 3 pm".

The interpreter (runtime/ops_interpret.py) decides that a line asks to change or to cancel an event; the numbered form ("cancela o evento 2") needs the number of the event in the
newest snapshot of a calendar source (runtime/ops_items.py). This file finds that number from the words of the line, by code only, and then opens the card through the existing
family path (`ops_natural_writes.open_line` with a seed of the source and the number: the same card the numbered line opens, approved by its hash). Nothing the model wrote is read
here but the operation and the two spans the check already verified against the line; the event is found from the PERSON'S OWN line.

  open_event(project, ctx, decision, said, sender, extras, writes, now)   the reply: a card notice, a numbered list of the events that fit, or one plain sentence
  take(project, ctx, said, sender, extras, writes, now)   a number after a list (below): the reply, or None when the line is not one
  account_named(said, title, hint)   "google" | "microsoft" | None: the account a line names
  verb_op(said)   "event-cancel" | "event-change" | None: the operation a line's leading verb names (a model that asked only for "the event" gets it from here)

How the calendar is read (the reading the numbered form reads, with its rights): the sender must pass `item_refs.may_read` (the group `ask-mail`; the same sentence as the family
when not); the calendar sources are the registered ones (`ops_natural_calendar.calendar_sources`); for each, `item_refs.read_index` checks the newest snapshot (younger than 26
hours, files hashed against the store's record, index against its digest) and the text is read as `ops_items._event_lines` reads it, only after its hash was checked, now with the
day headings (`## 2026-10-22 (Thursday)`) the text prints above the events. The event's title is the second field of its line (the first is the time). Nothing is called, nothing is
written and no model is used.

Which events fit. An event is a candidate when it is not cancelled and falls in the window: from today to 30 days ahead, or, when the line names a day, that day alone. A day is
named by a date word code reads (today, tomorrow, "dia 22", 22/10, a weekday: any date of that weekday in the window); a time of day alone names none, so a title that holds a number is
never mistaken for one; a date word code cannot read is a question, not a guess. A candidate fits when its title, folded (case and accents) and cut into words, occurs as whole words
in the line (for a change, the line without the spans that hold the new time and the new title, found in the line with its white space collapsed; a span not found is a question). A title that is part of a longer title that also fits is dropped. Exactly one fits: the card opens.
Several: a short numbered list and the question which. None: the calendar sources are read again once (`refresh`: only a sender who may read a snapshot gets here, no new
group; a snapshot older than its limit counts as a miss too; a failure is dropped), the search is made again, and still none is one plain sentence; never a second refresh for a line. The numbers listed are the snapshot's own, so "cancela o evento 7" is then the numbered form.

A number after a list (slice S11). Right after the numbered list above (or the items list of the calendar, `remember_items`), "cancela o 2", "o 2", "2", "the 2nd" and "muda o 2 para as
15h" from the SAME sender in the same chat, within LIST_WINDOW_S seconds, mean the entry with that number of the snapshot the list was made from, exactly as "cancela o evento 2" does (the
same family path and card, never approved here). `take` is called by the interpreter's `turn` before any model call. What is kept for it is a small record in memory for each (project,
channel, sender): the time, the operation the list asked about, the new time a change list was asked with, and (source, number, read_at) for each entry shown; no line, title or text. Before a
number is carried out the newest snapshot of that source is read again and its `read_at` must be the recorded one: a refreshed snapshot, or a number that two sources listed, is asked again
(EV_LIST_AGAIN) and never guessed; a number the list did not show is no form of this list and the line goes on as before; a sender with no live list is not touched.

The account a line names (slice S11). "no outlook", "na agenda do outlook", "on google calendar", "in my gmail": a closed list of brand words (the language tables' `brands_google` and `brands_microsoft`) that counts as an account word only
beside a word that introduces it or a calendar word (LEADS, CAL_WORDS), outside the title the model read, so "lunch with Google" names none; the model's own `service` word counts only
when it is one of those brands and stands in the line (`account_named`). Exactly one account is the account; both, or none, leave the question to the family. An account named but
with no calendar configured is one plain sentence (EV_ACCOUNT_NONE), never another account's card. For an event to change or cancel the account narrows the search to its sources.

Events the platform created (slice S16). When no calendar source holds an event the line names, or the project has no calendar source at all, the search goes on over the events this
platform created itself and has not removed since (runtime/event_created.py: the approved cards of this project's ledger and their documents), by the same rules: the window or the
named day, the title as whole words of the line, the account a line names. Exactly one: the card opens through the family path with the reference `created:<card>`, the reference the
calendar operations already take for an event the runtime made; the preparation of that card reads the event from the provider and pins its version, so an event deleted there is
refused. Before it is named, each event that fits (at most LIST_MAX of them for a line; the rest are only counted, and a count makes the answer a list) is read back once from the provider (`event_created.live`) and dropped when it is gone or no longer at the instants the ledger says (compared as absolute instants, never as wall times); a read that fails is one plain sentence (EV_CHECK_FAILED), never 'no calendar added' (a read
of the event the platform wrote, covered by the right to read the calendar, contracts/runtime.md L52). Several: the same numbered list; a number said after it (`take`) opens the card
of that entry. None, with no calendar source: one plain sentence (EV_NONE_NO_SOURCE) that only events created here can be found until a calendar is added.

Privacy (limit L63): the line, the titles and the lines of the snapshot are never logged, printed or kept here; the reply holds titles of the person's own calendar, so the
conversation stores a neutral word for it (`extras["stored"]`). Standard library only. Runs on Python 3.9: python3 runtime/event_lookup.py --help
"""
from __future__ import annotations

import datetime
import hashlib
import importlib
import re
import sys
import threading

import event_created
import item_refs
import natural
import natural_time as nt
import natural_writes as nw
import phrases
import snapshot_text
import sources

CHANNEL = "messaging"
OPS = ("event-change", "event-cancel")
WINDOW_DAYS = 30
LIST_WINDOW_S = 600             # seconds after a list in which a number from the same sender means one of its entries (the lifetime of a write draft, ops_natural.DRAFT_TTL)
ITEMS_SHOWN = 20                # entries of one source the items list prints (ops_items.render)
LIST_MAX = 8                    # events listed when several fit
TITLE_MIN = 3                   # letters a title needs before its words can name an event
HEADING = re.compile(r"## ([0-9]{4}-[0-9]{2}-[0-9]{2}) \([A-Za-z]+\)")
SLASH = re.compile(r"(?<![0-9/])([0-9]{1,2})/([0-9]{1,2})(?:/([0-9]{2,4}))?(?![0-9/])")
EVENT_LINE = re.compile(r"([0-9]{1,4})\. (.+)")
DAY_HITS = ("date", "slash")    # the hits of the time engine that name a day (a clock alone names none)
ENGLISH_WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")      # the shape phrases.localize_dates turns into the language's word on a phone


# The closed words of the account a line names, folded; a brand (language data, `requests.writes.calendar.brands_<account>`) counts beside a LEAD or before a CAL_WORD, never alone.
SERVICE_NAME = {"google": "Google", "microsoft": "Microsoft"}
CAL_WORDS = {"agenda", "agendas", "calendar", "calendars", "calendario", "calendarios", "calendrier", "calendriers", "kalender", "calendari"}
LEADS = CAL_WORDS | {"no", "na", "nos", "nas", "pelo", "pela", "via", "usando", "pro", "pra", "em", "de", "do", "da", "meu", "minha",     # pt  validate: allow english-only -- the closed words of the languages a line may be written in
                     "on", "in", "to", "from", "using", "of", "my", "at",                                                                      # en
                     "en", "del", "por", "mi", "mis", "con",                                                                                   # es
                     "sur", "dans", "avec", "mon", "ma", "chez",                                                                               # fr
                     "im", "auf", "bei", "mit", "uber", "mein", "meine", "unter",                                                              # de
                     "su", "sul", "sulla", "nel", "nella", "tramite", "mio", "mia", "di"}                                                      # it


def _brands() -> dict:
    """{account: [brand as a tuple of folded words]} from the language tables."""
    tables = natural._tables(None)
    return {account: [tuple(_words(p)) for p in nw.listed(tables, "calendar", "brands_" + account)] for account in SERVICE_NAME}


PLURAL = {"os", "as", "uns", "umas", "aos", "los", "las", "les", "die", "gli", "le", "ambos", "ambas", "todos", "todas", "both", "all"}          # a plural article or a word for "both": a number after it is a group      # validate: allow english-only -- the closed words of the languages a line may be written in


def _text(ctx: dict, key: str, **fields) -> str:
    return phrases.text(key, ctx["cfg"], **fields)


def _words(text) -> list:
    return natural.normal(text).split()


def _contains(words: list, piece: list) -> bool:
    return bool(piece) and any(words[i:i + len(piece)] == piece for i in range(len(words) - len(piece) + 1))


# --- the calendar --------------------------------------------------------------------------------------------------------------------------------


def _rows(ctx: dict, source_id: str, version) -> list:
    """[(n, day, [fields of the line])] of the version the index was read from: the text is read only when it is still the newest version and its hash is the store's record
    (as ops_items._event_lines does), so the number and the line come from one snapshot. Else nothing."""
    latest = sources._stored(ctx, "source_latest", source_id)
    if latest is None or latest["version"] != version:
        return []
    with sources.Folder(ctx["cfg"], None) as folder:
        raw = folder.read([source_id, str(version), latest["converted_name"]], sources.CONVERTED_CAP)
    if hashlib.sha256(raw).hexdigest() != latest["converted_sha256"]:
        return []
    day, out = None, []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        heading = HEADING.fullmatch(line.strip())
        if heading:
            try:
                day = datetime.date.fromisoformat(heading.group(1))
            except ValueError:
                day = None
            continue
        found = EVENT_LINE.fullmatch(line.strip())
        if found and day is not None:
            fields = snapshot_text.clean_text(found.group(2)).split(" · ")
            if len(fields) >= 2:
                out.append((int(found.group(1)), day, fields))
    return out


def events(ctx: dict, sender) -> tuple:
    """(events, problem): the events of every registered calendar source whose newest snapshot can be read, as {"source", "n", "day", "time", "title", "read_at"}; `problem` says why there is
    none: "not-readable" (the sender may not read a snapshot), "no-source", "stale" (every snapshot was refused)."""
    if not item_refs.may_read(ctx, CHANNEL, sender):
        return [], "not-readable"
    listed = importlib.import_module("ops_natural_calendar").calendar_sources(ctx)
    if not listed:
        return [], "no-source"
    clock = importlib.import_module("ops_items").SNAPSHOT_CLOCK
    out, refused = [], 0
    for source in listed:
        try:
            snapshot = item_refs.read_index(ctx, source["id"], channel=CHANNEL, sender=sender, kinds=("calendar",), clock=clock)
        except item_refs.ItemRefError:
            refused += 1
            continue
        known = {e["n"] for e in snapshot["entries"]}
        for n, day, fields in _rows(ctx, source["id"], snapshot["version"]):
            if n in known and "cancelled" not in fields[2:]:
                out.append({"source": source["id"], "n": n, "day": day, "time": fields[0], "title": fields[1], "read_at": snapshot["read_at"]})
    return (out, None) if refused < len(listed) else ([], "stale")


def refresh(project: str, ctx: dict) -> None:
    """Read each registered calendar source again, once: the provider read the snapshots come from (`ops_sources.source_refresh`, which `snapshot_refresh` in
    runtime/sources_mail.py does), a new version only when the listing changed. The caller has passed `item_refs.may_read`, the right to read these snapshots; the
    read is of the person's own calendar and writes nothing to it. A failure is dropped: nothing of it is kept or said."""
    refresh_one = importlib.import_module("ops_sources").source_refresh
    for source in importlib.import_module("ops_natural_calendar").calendar_sources(ctx):
        try:
            refresh_one(project, source["id"])
        except Exception:      # noqa: BLE001 - the fault can hold a provider's words; the reply is the not-found sentence
            continue


# --- the account a line names ----------------------------------------------------------------------------------------------------------------------


def account_named(said, title=None, hint=None):
    """`google`, `microsoft` or None: the account the line names, by the closed brand words of the language tables. A brand counts when the word before it is a LEAD or the word after it is a
    calendar word, and not when it stands in `title` (the title the model read: "lunch at Google" is a title). `hint`, the model's own `service` word, counts only when it is
    one of the brands and stands in the line as a whole word. Two accounts, or none, are None: the family asks."""
    words = _words(said)
    inside = set()
    piece = _words(title) if title else []
    at = next((i for i in range(len(words) - len(piece) + 1) if words[i:i + len(piece)] == piece), None) if piece else None
    if at is not None:
        inside.update(range(at, at + len(piece)))
    found = set()
    brands_of = _brands()
    for account, brands in brands_of.items():
        for brand in brands:
            n = len(brand)
            for i in range(len(words) - n + 1):
                if tuple(words[i:i + n]) == brand and not inside.intersection(range(i, i + n)):
                    before, after = words[i - 1] if i else "", words[i + n] if i + n < len(words) else ""
                    if before in LEADS or after in CAL_WORDS:
                        found.add(account)
    said_hint = tuple(_words(hint)) if isinstance(hint, str) else ()
    n = len(said_hint)
    for account, brands in brands_of.items():
        if said_hint in brands and any(tuple(words[i:i + n]) == said_hint and not inside.intersection(range(i, i + n)) for i in range(len(words) - n + 1)):
            found.add(account)          # the model's word, at a place of the line that is not the title
    return next(iter(found)) if len(found) == 1 else None


def _sources_of(ctx: dict, account: str) -> set:
    return {s["id"] for s in importlib.import_module("ops_natural_calendar").calendar_sources(ctx) if s["account"] == account}


def _of_account(ctx: dict, rows: list, account) -> list:
    if not account:
        return rows
    ids = _sources_of(ctx, account)
    return [r for r in rows if r.get("account") == account or r["source"] in ids]          # an event the platform created carries its account; a snapshot's event, its source's


def seed_service(ctx: dict, decision: dict, said: str, extras: dict, seed: dict):
    """Put the account the line names in the seed of a new event (the family then does not ask which), and return None; or return the sentence when it names one whose
    calendar the project has not set up (a card for another account would be the wrong one). A line that names none leaves the seed as it is."""
    named = account_named(said, (decision.get("spans") or {}).get("title"), (decision.get("args") or {}).get("account"))      # the slot `service` is the parameter `account`
    if named is None:
        return None
    if named not in importlib.import_module("ops_natural_writes").accounts_with(ctx, "calendars"):
        extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
        return _text(ctx, "EV_ACCOUNT_NONE", service=SERVICE_NAME[named])
    seed["account"] = named
    return None


# --- a number after a list ----------------------------------------------------------------------------------------------------------------------

_LISTS = {}          # (project key, channel, sender) -> {"at", "op", "start", "items": [(source, n, read_at)]}: in memory only, no line and no title
_lock = threading.Lock()


def forget_lists() -> None:
    """Drop every record (a test, and a process that stops)."""
    with _lock:
        _LISTS.clear()


def _natural():
    return importlib.import_module("ops_natural")


def _last_pending(ctx: dict) -> int:
    """The number of the newest pending decision (0 when there is none): a card that appears after a list was shown ends the list."""
    try:
        return max([p["id"] for p in ctx["store"].pending_list(ctx["conn"], "all")] or [0])
    except Exception:      # noqa: BLE001 - the store's refusal is no reason to keep a list alive: 0 only ends it earlier
        return 0


def _slot(ctx: dict, channel, sender) -> tuple:
    return (_natural().project_key(ctx["cfg"]["project"]), channel, sender or "")


def _remember(ctx: dict, channel, sender, op, start, items: list) -> None:
    now = _natural()._clock()
    with _lock:
        for old in [k for k, v in _LISTS.items() if (now - v["at"]).total_seconds() > LIST_WINDOW_S]:
            del _LISTS[old]
        if items:
            _LISTS[_slot(ctx, channel, sender)] = {"at": now, "op": op, "start": start, "items": list(items), "seen": 0, "pending": _last_pending(ctx)}
        else:
            _LISTS.pop(_slot(ctx, channel, sender), None)


def remember_list(ctx: dict, sender, op: str, found: list, start) -> None:
    """The list of events `_list` shows: what the sender may now point to by number (`start` is the new time a change was asked with, or None)."""
    _remember(ctx, CHANNEL, sender, op, start, [(r["source"], r["n"], r["read_at"]) for r in found[:LIST_MAX]])


def remember_items(ctx: dict, channel, sender, out: dict) -> None:
    """The items list of the calendar sources (ops_items.items, as ops_natural prints it): the entries it shows, up to ITEMS_SHOWN for each source. A list of another kind
    clears the record. Only a messaging sender has one."""
    if channel != CHANNEL:
        return
    shown = [(e["source"], i["n"], e["read_at"]) for e in out.get("sources") or [] if e.get("type") == "calendar" for i in e["items"][:ITEMS_SHOWN]]
    _remember(ctx, channel, sender, None, None, shown)


def begin_turn(ctx: dict, channel, sender) -> None:
    """Called by `ops_say.say` at the start of every line of a messaging sender: a list is valid only for the line that comes right after it (the bot's next message is the
    answer to that line, and a list is then no longer the last thing it said)."""
    if channel == CHANNEL:
        with _lock:
            found = _LISTS.get(_slot(ctx, channel, sender))
            if found is not None:
                found["seen"] += 1


def _drop(ctx: dict, sender) -> None:
    with _lock:
        _LISTS.pop(_slot(ctx, CHANNEL, sender), None)


def _live(ctx: dict, sender, now):
    """The sender's record while it is the last thing said to them: not older than the window, no line since the one that is being read, no decision card made since."""
    with _lock:
        found = _LISTS.get(_slot(ctx, CHANNEL, sender))
    if found is not None and ((now - found["at"]).total_seconds() > LIST_WINDOW_S or found["seen"] > 1 or _last_pending(ctx) > found["pending"]):
        _drop(ctx, sender)
        return None
    return found


def _number_form(said: str):
    """{"n", "verb": "cancel" | "change" | None, "canonical": the numbered line, with the event noun} for a line that is a number and nothing else but the closed words, or a
    cancel or change verb and a number (and what the numbered form reads after it), else None. "cancela o 2", "o 2", "2", "#2", "the 2nd", "muda o 2 para as 15h"."""
    tables = natural._tables(None)
    line = nw.Line(said)
    norm = line.norm
    nouns = nw.listed(tables, "calendar", "nouns")
    verb_end, kind = line.lead(nw.listed(tables, "calendar", "cancel_verbs"), tables), "cancel"
    if verb_end is None:
        verb_end, kind = line.lead(nw.listed(tables, "calendar", "change_verbs"), tables), "change"
    at = nw.skip_articles(line, verb_end or 0, tables)
    found = re.compile(r"\s*(?:" + nt._alt(nouns) + r"\s+)?#?\s*([0-9]{1,4})(?:st|nd|rd|th|o|a)?(?![a-z0-9])").match(norm, at)
    if not found or int(found.group(1)) < 1 or found.group(1) != str(int(found.group(1))):
        return None
    n, rest = int(found.group(1)), norm[found.end():]
    if PLURAL.intersection(re.findall(r"[a-z0-9]+", norm[verb_end or 0:found.start()])):
        return None          # "cancela os 2", "apaga as 2", "os 2": both of them, not the second
    if verb_end is None:
        fillers = set(nw.listed(tables, None, "articles")) | {w for p in nouns for w in p.split()} | {"numero", "number", "item", "n", "num"}
        before = re.findall(r"[a-z0-9]+", norm[:found.start()])
        if all(w in fillers for w in before) and not re.search(r"[a-z0-9]", rest):
            return {"n": n, "verb": None, "canonical": None}
        return None
    return {"n": n, "verb": kind, "canonical": f"{norm[:verb_end].rstrip()} {nouns[0]} {n}{rest}"}


def _fresh(ctx: dict, sender, source: str, read_at: str) -> bool:
    """Whether the newest snapshot of `source` is the one the list was made from."""
    try:
        snapshot = item_refs.read_index(ctx, source, channel=CHANNEL, sender=sender, kinds=("calendar",), clock=importlib.import_module("ops_items").SNAPSHOT_CLOCK)
    except item_refs.ItemRefError:
        return False
    return snapshot["read_at"] == read_at


def take(project: str, ctx: dict, said: str, sender, extras: dict, writes, now):
    """The reply to a number after a list (see the module's text), or None when the line is not one: no live list for this sender, a line that is no number form, a number the list
    did not show, or a numbered line the family does not read. A line that is not taken ends the sender's list: it is valid for the line right after it and no other."""
    record = _live(ctx, sender, now)
    if record is None:
        return None
    reply, keep = _taken(project, ctx, said, sender, extras, writes, record)
    if keep:          # a question about the list's entry (what to do with it): the list is still the last thing said
        with _lock:
            record["seen"], record["at"] = 0, now
    else:
        _drop(ctx, sender)
    return reply


def _taken(project: str, ctx: dict, said: str, sender, extras: dict, writes, record: dict) -> tuple:
    """(reply or None, keep the list): the list is kept only by a reply that asks what to do with an entry."""
    form = _number_form(said)
    if form is None or not item_refs.may_read(ctx, CHANNEL, sender):
        return None, False
    matches = [(source, read_at) for source, n, read_at in record["items"] if n == form["n"]]
    if not matches:
        return None, False
    extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
    if len(matches) > 1:
        return _text(ctx, "EV_LIST_AGAIN"), False
    source, op = matches[0][0], {"cancel": "event-cancel", "change": "event-change"}.get(form["verb"]) or record["op"]
    if source == event_created.SOURCE:          # an entry of the list of events the platform created: the card number and the signature the list recorded; the entry must still be in the ledger and as shown
        number, _, shown = matches[0][1].partition(":")
        own = event_created.by_pending(ctx, int(number)) if number.isdigit() else None
        if own is None or event_created.signature(own) != shown:
            return _text(ctx, "EV_LIST_AGAIN"), False
        bind = {"created": own["pending"], "account": own["account"]}
    elif not _fresh(ctx, sender, *matches[0]):
        return _text(ctx, "EV_LIST_AGAIN"), False
    else:
        bind = {"source": source}
    if form["verb"] is not None:
        return writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed={"op": op, "line": form["canonical"], "bind": bind}), False
    if op is None:
        return _text(ctx, "EV_LIST_WHAT", n=form["n"]), True
    slots = dict(bind) if "created" in bind else {"event": form["n"], "source": source}
    if op == "event-change":
        if not record["start"]:
            return _text(ctx, "EV_CHANGE_WHAT"), True
        slots["start"] = record["start"]
    return writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed={"op": op, "slots": slots}), False


# --- the line ------------------------------------------------------------------------------------------------------------------------------------


def _slash_day(text: str, today: datetime.date):
    """The date of a day/month[/year] written with slashes (the order of the engine, which reads none without a cue word), or None when none is written; ValueError when it
    does not exist. With no year it is the next such day from today."""
    found = SLASH.search(text)
    if not found:
        return None
    day, month, year = int(found.group(1)), int(found.group(2)), found.group(3)
    if year is not None and len(year) == 3:
        raise ValueError(year)
    if year is not None:
        return datetime.date(int(year) + (2000 if len(year) == 2 else 0), month, day)
    got = datetime.date(today.year, month, day)
    return got if got >= today else datetime.date(today.year + 1, month, day)


def _day_named(text: str, now):
    """("none", None), ("day", a date), ("weekday", 0-6) or ("unread", None): the day the words name, as the time engine reads them (or a date with slashes). A clock alone
    names none. A date word the engine doubts, or one it finds and cannot turn into a day, is "unread": a question, never a guess."""
    if nt.doubt(text):
        return "unread", None
    found = nt.find(text)
    named = [h for h in found["hits"] if h["kind"] in DAY_HITS]
    if not named:
        try:
            got = _slash_day(text, now.date())
        except ValueError:
            return "unread", None
        return ("day", got) if got else ("none", None)
    got = nt.parse(text, now)
    if got is not None:
        shown = got.get("day") or got.get("reading")
        if shown and shown.get("date"):
            try:
                return "day", datetime.date.fromisoformat(shown["date"])
            except ValueError:
                pass
    if len(named) == 1 and named[0]["spec"].get("k") == "wd":
        return "weekday", named[0]["spec"]["i"]
    return "unread", None


def _cut(text: str, span):
    """`text` without the first occurrence of `span` (both with every run of white space one space, as the interpreter accepts a span against the collapsed line), or None when
    the span is not in it."""
    piece = " ".join(str(span).split())
    at = text.find(piece) if piece else -1
    return None if at < 0 else text[:at] + " " + text[at + len(piece):]


_CONFIRM = []


def _confirmations() -> list:
    """The closed confirmation words and phrases of every language table (yes and no, in the answers and in the requests), as word lists, longest first."""
    if not _CONFIRM:
        found = set()
        for table in nt.languages():
            for group in ("answers", "requests"):
                for key in ("yes", "no"):
                    found.update(tuple(_words(w)) for w in (table.get(group) or {}).get(key) or [] if isinstance(w, str) and _words(w))
        _CONFIRM.extend(sorted(found, key=len, reverse=True))
    return _CONFIRM


def _edges(text: str) -> list:
    """The words of the line without a confirmation word or phrase at its start or its end ("sim, cancela o dentista"): a word of the title is never one of those."""
    words = _words(text)
    changed = True
    while changed:
        changed = False
        for phrase in _confirmations():
            n = len(phrase)
            if len(words) > n and tuple(words[:n]) == phrase:
                words, changed = words[n:], True
            elif len(words) > n and tuple(words[-n:]) == phrase:
                words, changed = words[:-n], True
    return words


def candidates(rows: list, said: str, kind: str, value, today: datetime.date) -> list:
    """The events of `rows` the line names: in the window or on the named day, and whose title is whole words of the line (a title inside a longer fitting title is dropped).
    The words of the line are those left when a confirmation word at its edges is taken out; the words the time engine reads as a day or a time are taken out too, so that a
    title such as "Dia" is not named by "dia 23", except for a title that holds such a word itself ("Reuniao 10h"), which is read against the whole line."""
    whole = _edges(said)
    bare = _edges(nt.without(said, nt._spans(nt.find(said))))
    fits = []
    for row in rows:
        words = _words(row["title"])
        line = whole if nt.find(row["title"])["hits"] else bare
        if sum(len(w) for w in words) < TITLE_MIN or not _contains(line, words):
            continue
        if kind == "day":
            ok = row["day"] == value
        else:
            ok = today <= row["day"] <= today + datetime.timedelta(days=WINDOW_DAYS) and (kind != "weekday" or row["day"].weekday() == value)
        if ok:
            fits.append((row, words))
    return [row for row, words in fits if not any(other != words and _contains(other, words) for _, other in fits)]


def _narrowed(ctx: dict, rows: list, text: str, kind: str, value, today: datetime.date, said: str, account):
    """(the events that fit, the account that narrowed them): an account word narrows the search to that account's calendars, except when the word stands in the title of an
    event that fits the line ("cancela a reuniao do google"): then it is part of the name, no account is named, and every fitting event is listed."""
    fits = candidates(rows, text, kind, value, today)
    if account and any(account_named(said, fit["title"]) != account for fit in fits):
        account = None
    return (candidates(_of_account(ctx, rows, account), text, kind, value, today) if account else fits), account


# --- the reply -----------------------------------------------------------------------------------------------------------------------------------


def _shown(row: dict, with_source: bool) -> str:
    day = row["day"]
    weekday = ENGLISH_WEEKDAY[day.weekday()]
    where = f" ({row['source']})" if with_source else ""
    return f"{row['n']}. {weekday} {day.strftime('%d/%m/%Y')} {row['time']} · {row['title']}{where}"


def _list(ctx: dict, op: str, found: list) -> str:
    many = len({r["source"] for r in found}) > 1
    lines = [_shown(r, many) for r in found[:LIST_MAX]]
    if len(found) > LIST_MAX:
        lines.append(_text(ctx, "EV_MORE", k=len(found) - LIST_MAX))
    key = "EV_MANY_CANCEL" if op == "event-cancel" else "EV_MANY_CHANGE"
    return _text(ctx, key) + "\n" + "\n".join(lines) + "\n" + _text(ctx, key + "_HOW", n=found[0]["n"])


PROBLEM = {"not-readable": "NW_REF_NOT_READABLE"}          # the sender may not read a snapshot: nothing of the calendar is named. "no-source" has no sentence of its own: the events created here are searched


def verb_op(said: str):
    """`event-cancel`, `event-change` or None: the operation the line's leading verb names, by the closed verbs of the language tables (what the numbered form reads). Used when the
    model could only say that it needs the event: the event is then found from the words of the line, whichever way the model asked."""
    tables = natural._tables(None)
    line = nw.Line(said)
    if line.lead(nw.listed(tables, "calendar", "cancel_verbs"), tables) is not None:
        return "event-cancel"
    return "event-change" if line.lead(nw.listed(tables, "calendar", "change_verbs"), tables) is not None else None


def _own(ctx: dict, text: str, kind: str, value, today: datetime.date, said: str, account) -> tuple:
    """(the events the platform created that fit, the account that narrowed them, how many fit beyond the cap, whether a read-back failed): `_narrowed` over the ledger rows (read
    once), cut to LIST_MAX before any call to the provider, so a line reads at most that many events; each one is read back from the provider (event_created.live) and one that is gone
    or at other instants is dropped. The rows are numbered 1, 2, ... in the order of their start: the number of the list `_list` shows, and they record the card number with a
    signature of what was shown (`read_at`)."""
    fits, account = _narrowed(ctx, event_created.created(ctx), text, kind, value, today, said, account)
    extra, checked = max(0, len(fits) - LIST_MAX), fits[:LIST_MAX]
    states = [event_created.live(ctx, r) for r in checked]
    kept = [r for r, state in zip(checked, states) if state == "ok"]
    return [dict(r, n=i + 1, read_at=f"{r['pending']}:{event_created.signature(r)}") for i, r in enumerate(kept)], account, extra, "error" in states


def _none(ctx: dict, kind: str, problem, account) -> str:
    """The sentence when nothing fits. Without any calendar source the person is told what is searched; an account named with no calendar of it set up has its own sentence."""
    if problem == "no-source":
        return _text(ctx, "EV_NONE_NO_SOURCE")
    if account and not _sources_of(ctx, account):
        return _text(ctx, "EV_ACCOUNT_NONE", service=SERVICE_NAME[account])
    return _text(ctx, "EV_NONE_DAY" if kind == "day" else "EV_NONE", days=WINDOW_DAYS)


def open_event(project: str, ctx: dict, decision: dict, said: str, sender, extras: dict, writes, now):
    """The reply for a decision to change or cancel an event (module text). `writes` is the module ops_natural_writes, which opens the card."""
    op, time_ = decision["op"], decision.get("time")
    reading = nw.read(said, now, op=op)
    if reading is None or (not reading.get("say") and "event" in reading["slots"]):
        opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, hint=op)          # the call as before: the numbered form, or nothing the family reads
        if opened is not None:
            return opened
    extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
    spans = decision.get("spans") or {}
    text = " ".join(said.split())
    for key in (("time", "title") if op == "event-change" else ()):          # the new time and the new title are not the words of the event to change
        if spans.get(key):
            text = _cut(text, spans[key])
            if text is None:
                return _text(ctx, "EV_ASK_DAY")          # a span the line does not hold as written: no day is read from the unstripped line
    kind, value = _day_named(text, now)
    if kind == "unread":
        return _text(ctx, "EV_ASK_DAY")
    named = account_named(said, spans.get("title"))          # S11: "no outlook" narrows the search to that account's calendars
    account = named
    rows, problem = events(ctx, sender)
    if problem in PROBLEM:
        return _text(ctx, PROBLEM[problem])          # the sender may not read a snapshot: nothing is refreshed and nothing is searched
    found, account = ([], account) if problem else _narrowed(ctx, rows, text, kind, value, now.date(), said, account)
    if not found and problem != "no-source" and not (account and not _sources_of(ctx, account)):
        refresh(project, ctx)          # a miss (nothing fits, or every snapshot is older than its limit): the calendar is read again ONCE for this line, then searched again
        rows, problem = events(ctx, sender)
        found, account = ([], account) if problem else _narrowed(ctx, rows, text, kind, value, now.date(), said, account)
    extra = 0
    if not found:          # S16: no source holds it (or there is none): the events this platform created are searched, the same way
        found, account, extra, failed = _own(ctx, text, kind, value, now.date(), said, named)
        if failed:
            return _text(ctx, "EV_CHECK_FAILED")          # a read-back failed: neither a card nor "not found" is true; nothing of the failure is said
    if not found:
        return _none(ctx, kind, problem, account)
    if len(found) > 1 or extra:
        remember_list(ctx, sender, op, found, time_["local"] if op == "event-change" and time_ else None)
        return _list(ctx, op, found) + (("\n" + _text(ctx, "EV_MORE", k=extra)) if extra else "")
    slots = {"event": found[0]["n"], "source": found[0]["source"]}
    if found[0]["source"] == event_created.SOURCE:          # a card number, not a place in a snapshot: the reference `created:<card>` (runtime/ops_natural_calendar.py)
        slots = {"created": found[0]["pending"], "account": found[0]["account"]}
    elif account:
        slots["account"] = account
    if op == "event-change":
        title = spans.get("title")
        if time_:
            slots["start"] = time_["local"]
        if title and _words(title) != _words(found[0]["title"]):
            slots["title"] = title
        if "start" not in slots and "title" not in slots:
            return _text(ctx, "EV_CHANGE_WHAT")
    return writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed={"op": op, "slots": slots})


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
