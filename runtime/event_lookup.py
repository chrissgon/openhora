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
  take(project, ctx, said, sender, extras, writes, now)   a number after a list, or a row named by an ordinal word or a value the list shows (below): the reply, or None when the line is not one
  picks(ctx, said, sender, now)   whether `take` would answer the line as a pick of the sender's live list (read-only; the bridge asks it before a clock-only line becomes a reminder)
  account_named(said, title, hint)   "google" | "microsoft" | None: the account a line names
  verb_op(said)   "event-cancel" | "event-change" | None: the operation a line's leading verb names (a model that asked only for "the event" gets it from here)

How the calendar is read (the reading the numbered form reads, with its rights): the sender must pass `item_refs.may_read` (the group `ask-mail`; the same sentence as the family
when not); the calendar sources are the registered ones (`ops_natural_calendar.calendar_sources`); for each, `item_refs.read_index` checks the newest snapshot (younger than 26
hours, files hashed against the store's record, index against its digest) and the text is read as `ops_items._event_lines` reads it, only after its hash was checked, now with the
day headings (`## 2026-10-22 (Thursday)`) the text prints above the events. The event's title is the second field of its line (the first is the time). Nothing is called, nothing is
written and no model is used.

Which events fit (slice S16b: the closest name; `ranked` below holds the rule). An event is a candidate when it is not cancelled and falls in the window: from today to 30 days ahead, or, when the line names a day, that day alone. A day is
named by a date word code reads (today, tomorrow, "dia 22", 22/10, a weekday: any date of that weekday in the window); a time of day alone names none, so a title that holds a number is
never mistaken for one; a date word code cannot read is a question, not a guess. A candidate fits when its title is near the words of the line (case and accents folded; the closed stop words left out; a small edit distance for each word, none up to 3 letters, 1 up to 6, 2 above; at least half of the title's
words and a Dice share of 0.5: `ranked`); for a change, the line without the spans that hold the new time and the new title (found in the line with its white space collapsed; a span not found is a question). The best fits alone when it beats
the next by 0.15; else the rows within 0.15 of it are the several close ones. Exactly one fits: the card opens.
Several: a short numbered list and the question which. None: the calendar sources are read again once (`refresh`: only a sender who may read a snapshot gets here, no new
group; a snapshot older than its limit counts as a miss too; a failure is dropped), the search is made again, and still none is one plain sentence; never a second refresh for a line. The numbers listed are the snapshot's own, so "cancela o evento 7" is then the numbered form.

A number after a list (slice S11). Right after the numbered list above (or the items list of the calendar, `remember_items`), "cancela o 2", "o 2", "2", "the 2nd" and "muda o 2 para as
15h" from the SAME sender in the same chat, within LIST_WINDOW_S seconds, mean the entry with that number of the snapshot the list was made from, exactly as "cancela o evento 2" does (the
same family path and card, never approved here). `take` is called by the interpreter's `turn` before any model call. What is kept for it is a small record in memory for each (project,
channel, sender): the time, the operation the list asked about, the new time a change list was asked with, and (source, number, read_at) for each entry shown; no line, title or text. Before a
number is carried out the newest snapshot of that source is read again and its `read_at` must be the recorded one: a refreshed snapshot, or a number that two sources listed, is asked again
(EV_LIST_AGAIN) and never guessed; a number the list did not show is no form of this list and the line goes on as before; a sender with no live list is not touched.

A row named without its number (LP-1, scenario 38; runtime/list_pick.py). The same replies may also name a row by an ordinal word or by a value the list shows: "a última", "o primeiro", "a das 15h",
"a do dia 23", "the last one". When the line is no number form, `list_pick.read` turns the WHOLE line into one closed form (or None: a clock with no lead such as "15h", a title word, a plural and
a longer request are no pick and go on as before) and `list_pick.choose` decides which row it names, against the rows exactly as the list printed them: the record keeps, for each row, the values
the list printed (its day, its start, the account of its calendar and its position: clocks, days, accounts and positions only, never a title or a line) and whether the list held more rows than it
printed. One row: it goes on exactly as that row's number does (`_fresh`, the events the platform created, the start a change list recorded, the card path, the origin `listed`). Several rows, none,
or a reading that is not safe (a number the list printed that is also the position, a last of a list that held more, a pt-BR weekday that is also an ordinal): the sentence `LP_*` and the list is kept,
as `EV_LIST_WHAT` keeps it, so the next reply may name the number. `picks` answers the bridge, read-only and before the line is stored, whether this line will be taken so (a short line that holds a
clock is otherwise a reminder with no words, runtime/messaging_turn.py `reminder_form`).

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
import interpreter
import item_refs
import line_stage
import list_pick
import natural
import natural_time as nt
import natural_writes as nw
import ops_items
import ops_natural
import ops_natural_calendar
import ops_natural_writes
import ops_sources
import phrases
import registry_data
import snapshot_text
import source_names
import sources
import turn_gate

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


# The closed words of the account a line names, folded; a brand (data, runtime/registry/search_stop_words.json: S41-9) counts beside a LEAD or before a CAL_WORD, never alone.
SERVICE_NAME = {"google": "Google", "microsoft": "Microsoft"}
CAL_WORDS = set(registry_data.search_stop_words()["cal_words"])
LEADS = set(registry_data.search_stop_words()["leads"])            # the calendar words and the words that introduce an account, in the languages a line may be written in


def _brands() -> dict:
    """{account: [brand as a tuple of folded words]}, read from runtime/registry/search_stop_words.json."""
    return {account: list(brands) for account, brands in registry_data.search_stop_words()["brands"].items() if account in SERVICE_NAME}


PLURAL = set(registry_data.search_stop_words()["plural"])          # a plural article or a word for "both": a number after it is a group


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
    listed = ops_natural_calendar.calendar_sources(ctx)
    if not listed:
        return [], "no-source"
    clock = ops_items.SNAPSHOT_CLOCK
    out, refused = [], 0
    for source in listed:
        try:
            snapshot = item_refs.read_index(ctx, source["id"], channel=CHANNEL, sender=sender, kinds=("calendar",), clock=clock)
        except (item_refs.ItemRefError, sources.SourcesError):      # a refused folder (sources-identity) counts as a snapshot refused: the lookup says "stale", it does not lose the reply
            refused += 1
            continue
        known = {e["n"]: e for e in snapshot["entries"]}
        for n, day, fields in _rows(ctx, source["id"], snapshot["version"]):
            if n in known and "cancelled" not in fields[2:]:
                out.append({"source": source["id"], "n": n, "day": day, "time": fields[0], "title": fields[1], "read_at": snapshot["read_at"],
                            "recurring": known[n].get("recurring") is True})          # CB-7: the index's own record that the event belongs to a series (never the text's word)
    return (out, None) if refused < len(listed) else ([], "stale")


def refresh(project: str, ctx: dict) -> None:
    """Read each registered calendar source again, once: the provider read the snapshots come from (`ops_sources.source_refresh`, which `snapshot_refresh` in
    runtime/sources_mail.py does), a new version only when the listing changed. The caller has passed `item_refs.may_read`, the right to read these snapshots; the
    read is of the person's own calendar and writes nothing to it. A failure is dropped: nothing of it is kept or said. A source is read only when the line's refresh budget allows it
    (`turn_gate.may_refresh`, limit L52: never more than once for a source in one line, none outside a turn): a source already read for this line is left as it is."""
    line_stage.publish("calendar")      # S19
    refresh_one = ops_sources.source_refresh
    for source in ops_natural_calendar.calendar_sources(ctx):
        if not turn_gate.may_refresh(source["id"], "calendar-miss"):
            continue
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
    return {s["id"] for s in ops_natural_calendar.calendar_sources(ctx) if s["account"] == account}


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
    if named not in ops_natural_writes.accounts_with(ctx, "calendars"):
        extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
        return _text(ctx, "EV_ACCOUNT_NONE", service=SERVICE_NAME[named])
    seed["account"] = named
    if hasattr(seed, "origins"):
        seed.origins["account"] = "line-span"          # S41-7: a service word of the line
    return None


# --- a number after a list ----------------------------------------------------------------------------------------------------------------------

_LISTS = {}          # (project key, channel, sender) -> {"at", "op", "start", "items": [(source, n, read_at)], "shown": [{"day", "start", "account", "position"}], "more"}: in memory only, no line and no title
_lock = threading.Lock()


def forget_lists() -> None:
    """Drop every record (a test, and a process that stops)."""
    with _lock:
        _LISTS.clear()


def _last_pending(ctx: dict) -> int:
    """The number of the newest pending decision (0 when there is none): a card that appears after a list was shown ends the list."""
    try:
        return max([p["id"] for p in ctx["store"].pending_list(ctx["conn"], "all")] or [0])
    except Exception:      # noqa: BLE001 - the store's refusal is no reason to keep a list alive: 0 only ends it earlier
        return 0


def _slot(ctx: dict, channel, sender) -> tuple:
    return (ops_natural.project_key(ctx["cfg"]["project"]), channel, sender or "")


def _remember(ctx: dict, channel, sender, op, start, items: list, shown=None, more: bool = False) -> None:
    """Keep what the sender may point to next. `shown` (LP-1) is, for each item in the same order, the values the list printed for it ({"day": ISO date | None, "start": "HH:MM" | None,
    "account": "google" | "microsoft" | None, "position": 1.. | None}): clocks, days, accounts and positions only, never a title, a line or a word of the person's; `more` says the list printed
    fewer rows than it holds."""
    now = ops_natural._clock()
    with _lock:
        for old in [k for k, v in _LISTS.items() if (now - v["at"]).total_seconds() > LIST_WINDOW_S]:
            del _LISTS[old]
        if items:
            _LISTS[_slot(ctx, channel, sender)] = {"at": now, "op": op, "start": start, "start_source": None, "items": list(items), "shown": list(shown or []), "more": bool(more), "seen": 0,
                                                   "pending": _last_pending(ctx)}
        else:
            _LISTS.pop(_slot(ctx, channel, sender), None)


def _start_on(start: str, day) -> str:
    """The new start of a change on the day of the event it is carried out for: a start recorded as "@HH:MM" was a clock with no day in the line ("para as 10h") and takes the
    day of the event (the length of the event is kept by the change); a full start is as it is."""
    return f"{day.isoformat()}T{start[1:]}" if start.startswith("@") else start


def _start_shown(when) -> object:
    """The start a list printed for an event ("13:00-14:00", "13:00"), as "HH:MM"; None for "all day" and anything else."""
    found = re.match(r"([0-2][0-9]:[0-5][0-9])(?:-[0-2][0-9]:[0-5][0-9])?$", when) if isinstance(when, str) else None
    return found.group(1) if found else None


def _shown_values(day, when, account, position) -> dict:
    """The values one printed row holds for a pick (LP-1): its day (ISO), its start, the account of its calendar and its place in the list. Nothing of the row's text."""
    return {"day": day.isoformat() if isinstance(day, datetime.date) else day if isinstance(day, str) else None, "start": _start_shown(when), "account": account, "position": position}


def remember_list(ctx: dict, sender, op: str, found: list, start, more: bool = False) -> None:
    """The list of events `_list` shows: what the sender may now point to by number (`start` is the new time a change was asked with, "@HH:MM" when it is a clock with no day,
    or None) and, for a pick by an ordinal or by a value (runtime/list_pick.py), the values each printed row holds. `more`: the list also said how many more events fit."""
    try:
        accounts = {s["id"]: s.get("account") for s in ops_natural_calendar.calendar_sources(ctx)}
    except Exception:      # noqa: BLE001 - the account of a row is only for a pick by brand; a list that was made is never lost for it
        accounts = {}
    shown = found[:LIST_MAX]
    _remember(ctx, CHANNEL, sender, op, start, [(r["source"], r["n"], r["read_at"]) for r in shown],
              [_shown_values(r["day"], r["time"], r.get("account") or accounts.get(r["source"]), place) for place, r in enumerate(shown, 1)], more or len(found) > LIST_MAX)


def note_start_source(ctx: dict, sender, source) -> None:
    """Who read the time the list's record holds (the interpreter's source "code" or "model"), kept with it so that the card a number opens says whose reading the time is (S41-7)."""
    try:
        slot = _slot(ctx, CHANNEL, sender)
    except (KeyError, TypeError):      # a context with no project names no list
        return
    with _lock:
        found = _LISTS.get(slot)
        if found is not None:
            found["start_source"] = source


def remember_items(ctx: dict, channel, sender, out: dict) -> None:
    """The items list of the calendar sources (ops_items.items, as ops_natural prints it): the entries it shows, up to ITEMS_SHOWN for each source. A list of another kind
    clears the record. Only a messaging sender has one."""
    if channel != CHANNEL:
        return
    shown = [(e["source"], i["n"], e["read_at"]) for e in out.get("sources") or [] if e.get("type") == "calendar" for i in e["items"][:ITEMS_SHOWN]]
    listing = [e for e in out.get("sources") or [] if e.get("items")]
    one = len(listing) == 1 and listing[0].get("type") == "calendar"          # a position means something only when the list is one run of numbered rows: one section, no mail beside it
    values = [_shown_values(i.get("day"), str(i.get("line") or "").split(" · ")[0], e.get("account"), place if one else None)
              for e in out.get("sources") or [] if e.get("type") == "calendar" for place, i in enumerate(e["items"][:ITEMS_SHOWN], 1)]
    _remember(ctx, channel, sender, None, None, shown, values, any(len(e["items"]) > ITEMS_SHOWN for e in listing))


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
        snapshot = item_refs.read_index(ctx, source, channel=CHANNEL, sender=sender, kinds=("calendar",), clock=ops_items.SNAPSHOT_CLOCK)
    except item_refs.ItemRefError:
        return False
    return snapshot["read_at"] == read_at


def take(project: str, ctx: dict, said: str, sender, extras: dict, writes, now):
    """The reply to a number after a list (see the module's text), or None when the line is not one: no live list for this sender, a line that is no number form, a number the list
    did not show, or a numbered line the family does not read. A line that is not taken ends the sender's list: it is valid for the line right after it and no other."""
    record = _live(ctx, sender, now)
    if record is None:
        return None
    reply, keep = _taken(project, ctx, said, sender, extras, writes, record, now)
    if keep:          # a question about the list's entry (what to do with it): the list is still the last thing said
        with _lock:
            record["seen"], record["at"] = 0, now
    else:
        _drop(ctx, sender)
    return reply


def _numbers_text(ctx: dict, numbers: list) -> str:
    """The numbers a list printed, as a sentence says them: "2", "2 e 4", "1, 2 e 4"."""
    shown = [str(n) for n in numbers]
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " " + _text(ctx, "LP_AND") + " " + shown[-1]


def _value_text(ctx: dict, value) -> str:
    """What a pick named, in the words code renders it with (a clock, a day, a weekday, an account, a position); never a title, never an address."""
    kind, what = value
    if kind == "clock":
        return _text(ctx, "LP_VALUE_CLOCK", time=what)
    if kind == "day":
        return _text(ctx, "LP_VALUE_DAY", weekday=_text(ctx, phrases.WEEKDAY_KEYS[what.weekday()]), date=what.strftime("%d/%m"))
    if kind == "weekday":
        return _text(ctx, "LP_VALUE_WEEKDAY", weekday=_text(ctx, phrases.WEEKDAY_KEYS[what]))
    if kind == "account":
        return _text(ctx, "LP_VALUE_ACCOUNT", service=SERVICE_NAME[what])
    return _text(ctx, "LP_VALUE_ORDINAL", p=what)


def _pick_day(text: str, now):
    """`_day_named` for the words of a pick, with one change: a weekday written alone ("sexta", "friday") is ("weekday", 0-6), not the date of its next occurrence, because a list names any row
    of that weekday. A date word the engine doubts or cannot read is ("unread", None); no exception leaves (a day the engine cannot read is no day: the pick is not made)."""
    try:
        kind, value = _day_named(text, now)
        if kind == "day":
            named = [h for h in nt.find(text)["hits"] if h["kind"] in DAY_HITS]
            spec = named[0].get("spec") if len(named) == 1 and named[0]["kind"] == "date" else None
            index = spec.get("i") if isinstance(spec, dict) and spec.get("k") == "wd" else None
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= 6:
                return "weekday", index
        return kind, value
    except Exception:      # noqa: BLE001
        return "unread", None


def _pick(ctx: dict, record: dict, form: dict, now) -> tuple:
    """The verdict of `list_pick.choose` for a reply that names a row of the live list without its number: the rows are the ones the list printed (`shown`), in the order printed."""
    shown = record.get("shown") or []
    if len(shown) != len(record["items"]):
        return list_pick.SKIP
    rows = [dict(values, n=item[1]) for item, values in zip(record["items"], shown)]
    when = now or ops_natural._clock()
    return list_pick.choose(form, rows, lambda text: _pick_day(text, when), bool(record.get("more")))


def _pick_reply(ctx: dict, record: dict, verdict: tuple) -> str:
    """The sentence of a verdict that opens nothing (the list is kept): several rows fit, none does, or the reading is not safe."""
    kind, payload, detail = verdict
    numbers = [item[1] for item in record["items"]]
    if kind == "several":
        return _text(ctx, "LP_SEVERAL", value=_value_text(ctx, detail), rows=_numbers_text(ctx, [numbers[i] for i in payload]))
    if kind == "none":
        return _text(ctx, "LP_NONE", value=_value_text(ctx, detail))
    if payload == "ordinal-clash":
        return _text(ctx, "LP_ORDINAL_CLASH", n=detail["n"], position=_value_text(ctx, ("ordinal", detail["position"])), m=detail["m"])
    if payload == "day-or-position":
        return _text(ctx, "LP_DAY_OR_POSITION", a=_numbers_text(ctx, detail["a"]), position=_value_text(ctx, ("ordinal", detail["position"])), b=_numbers_text(ctx, detail["b"]))
    return _text(ctx, "LP_LAST_NOT_SHOWN")


def picks(ctx: dict, said: str, sender, now) -> bool:
    """Whether `take` would answer `said` as a pick of the sender's live list (LP-1), asked BEFORE the line is stored or read: read-only, it drops nothing and counts nothing. The messaging
    bridge asks it before it takes a short line that holds a clock ("a das 15h") for a reminder that has no words, because the list was the last thing said and the line answers it. The list
    must be live as `_live` reads it for the line about to arrive (no line has reached `say` since; `begin_turn` has not yet counted this one), the line must be a closed pick and no number
    form, the sender must be allowed to read a snapshot, and the verdict must not be "skip"."""
    with _lock:
        record = _LISTS.get(_slot(ctx, CHANNEL, sender))
    if record is None or (now - record["at"]).total_seconds() > LIST_WINDOW_S or record["seen"] > 0 or _last_pending(ctx) > record["pending"]:
        return False
    if _number_form(said) is not None:
        return False
    form = list_pick.read(said)
    return form is not None and item_refs.may_read(ctx, CHANNEL, sender) and _pick(ctx, record, form, now)[0] != "skip"


def _taken(project: str, ctx: dict, said: str, sender, extras: dict, writes, record: dict, now=None) -> tuple:
    """(reply or None, keep the list): the list is kept only by a reply that asks what to do with an entry, or that asks for the number (a pick that names none, several or an unsafe reading).
    A line that is no number form may be a pick (runtime/list_pick.py): the row it names is one of the rows the list printed, and from there it goes exactly as that row's number goes."""
    form, pick = _number_form(said), None
    if form is None:
        pick = list_pick.read(said)
        if pick is None:
            return None, False
    if not item_refs.may_read(ctx, CHANNEL, sender):
        return None, False
    if pick is not None:
        verdict = _pick(ctx, record, pick, now)
        if verdict[0] == "skip":
            return None, False
        extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
        if verdict[0] != "one":
            return _pick_reply(ctx, record, verdict), True
        source, n, read_at = record["items"][verdict[1]]
        form = {"n": n, "verb": pick["verb"], "canonical": f"{pick['head']} {n}" if pick["verb"] else None}
        matches = [(source, read_at)]
    else:
        matches = [(source, read_at) for source, n, read_at in record["items"] if n == form["n"]]
        if not matches:
            return None, False
    extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
    if len(matches) > 1:
        return _text(ctx, "EV_LIST_AGAIN"), False
    source, op = matches[0][0], {"cancel": "event-cancel", "change": "event-change"}.get(form["verb"]) or record["op"]
    entry = None
    if source == event_created.SOURCE:          # an entry of the list of events the platform created: the card number and the signature the list recorded; the entry must still be in the ledger and as shown
        number, _, shown = matches[0][1].partition(":")
        own = event_created.by_pending(ctx, int(number)) if number.isdigit() else None
        if own is None or event_created.signature(own) != shown:
            return _text(ctx, "EV_LIST_AGAIN"), False
        bind, entry = {"created": own["pending"], "account": own["account"]}, own
    elif not _fresh(ctx, sender, *matches[0]):
        return _text(ctx, "EV_LIST_AGAIN"), False
    else:
        bind = {"source": source}
        entry = next((r for r in events(ctx, sender)[0] if (r["source"], r["n"]) == (source, form["n"])), None)
    listed = {"event": "listed", **({"account": "card-copy"} if "created" in bind else {})}          # S41-7: the number is one of the list code showed this sender; the account of an event this platform created is the account of its card
    if form["verb"] is not None:
        return writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed=turn_gate.Seed({"op": op, "line": form["canonical"], "bind": bind}, listed)), False
    if op is None:
        return _text(ctx, "EV_LIST_WHAT", n=form["n"]), True
    slots = dict(bind) if "created" in bind else {"event": form["n"], "source": source}
    if op == "event-change":
        if not record["start"]:
            return _text(ctx, "EV_CHANGE_WHAT"), True
        if entry is None:
            return _text(ctx, "EV_LIST_AGAIN"), False
        if _is_all_day(entry):
            return _text(ctx, "EV_ALLDAY_CLOCK"), False
        slots["start"] = _start_on(record["start"], entry["day"])
        problem = _past_problem(slots["start"], ops_natural._clock())
        if problem:
            return _text(ctx, problem), False
    if "start" in slots:
        listed = {**listed, "start": turn_gate.time_origin({"source": record.get("start_source")})}          # S41-7: the time is the code's or the model's reading, as the interpreter said when the list was made
    return writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed=turn_gate.Seed({"op": op, "slots": slots}, listed)), False


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


def _iso_day(value):
    """The date of an ISO string the time engine wrote, or None when it is no valid date."""
    try:
        return datetime.date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _day_named(text: str, now):
    """("none", None), ("day", a date), ("weekday", 0-6) or ("unread", None): the day the words name, as the time engine reads them (or a date with slashes). A clock alone
    names none. A date word the engine doubts, or one it finds and cannot turn into a day, is "unread": a question, never a guess. Every shape the engine can answer is
    handled, and none ends in an exception (BL5C, 2026-10-25: a `slash` hit has no `spec`, and a time range answers with several readings):
      doubt -> unread;   no day hit -> the slash fallback (a date, none, or unread for a date that does not exist);
      parse gives a day or one reading -> that date;
      parse gives several readings (`ask`: a time range) -> the date they ALL share (one day with two clocks), else unread (a question: two days are never guessed between);
      exactly one `date` hit of a weekday -> that weekday;   exactly one `slash` hit -> its date through the slash fallback (unread when it does not exist);   anything else -> unread."""
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
    if isinstance(got, dict):
        shown = got.get("day") or got.get("reading")
        date = _iso_day(shown.get("date")) if isinstance(shown, dict) else None
        if date is not None:
            return "day", date
        readings = got.get("ask")
        if isinstance(readings, list) and readings and all(isinstance(r, dict) for r in readings):
            dates = {r.get("date") for r in readings}
            if len(dates) == 1 and _iso_day(next(iter(dates))) is not None:          # a time range on one day: every reading names the same date
                return "day", _iso_day(next(iter(dates)))
    if len(named) == 1:
        hit = named[0]
        if hit["kind"] == "date":
            spec = hit.get("spec")
            index = spec.get("i") if isinstance(spec, dict) and spec.get("k") == "wd" else None
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index <= 6:
                return "weekday", index
        elif hit["kind"] == "slash":
            try:
                got = _slash_day(text, now.date())
            except ValueError:
                return "unread", None
            if got:
                return "day", got
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


_STOP = []
CLOSE_MARGIN = 0.15            # a best score must beat the next by this much to be the one; else the close ones are listed
SCORE_MIN = 0.5                # the least share of the words (Dice) for an event to be a candidate at all


def _stop_words() -> set:
    """The words of a line that name no event: articles, polite and linking words, the verbs that ask to change or cancel, the markers of a time, and the closed words of LEADS: all folded,
    read from runtime/registry/search_stop_words.json (S41-9), which is made without the brand words of the accounts (a brand stays a word: it may be part of a title)."""
    if not _STOP:
        _STOP.append(set(registry_data.search_stop_words()["stop_words"]))
    return _STOP[0]


def _tokens(words: list) -> list:
    stop = _stop_words()
    return [w for w in words if w not in stop]


def _edit(a: str, b: str) -> int:
    """The number of edits (add, drop, change, swap two neighbours) between two words (restricted Damerau-Levenshtein)."""
    rows = [list(range(len(b) + 1))]
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            row[j] = min(rows[i - 1][j] + 1, row[j - 1] + 1, rows[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], rows[i - 2][j - 2] + 1)
        rows.append(row)
    return rows[-1][-1]


def _near(a: str, b: str) -> bool:
    """Whether two words are the same word for a title: equal, or within a small edit distance (none up to 3 letters, 1 up to 6, 2 above) of each other."""
    if a == b:
        return True
    longest = max(len(a), len(b))
    allowed = 0 if longest <= 3 else (1 if longest <= 6 else 2)
    return allowed > 0 and abs(len(a) - len(b)) <= allowed and _edit(a, b) <= allowed


def _fit(title: list, line: list) -> float:
    """The share of a title's words in a line's words: Dice (2 * matched / (title words + line words)) with each line word used once and a word matched when `_near`; 0 when
    fewer than half of the title's words are matched."""
    free, matched = list(line), 0
    for word in title:
        at = next((i for i, other in enumerate(free) if other == word), None)
        if at is None:
            at = next((i for i, other in enumerate(free) if _near(word, other)), None)
        if at is None:
            continue
        matched += 1
        free.pop(at)
    if not matched or matched * 2 < len(title):
        return 0.0
    return 2.0 * matched / (len(title) + len(line))


def _brand_words() -> set:
    return {w for brands in _brands().values() for brand in brands for w in brand}


TITLE_NOUNS = {"reuniao", "reunioes", "meeting", "meetings", "appointment", "appointments", "compromisso", "compromissos"}      # nouns of the tables that are also what titles are called: they are words of a title, never skipped


def _noun_words() -> set:
    """The calendar nouns ("evento", "compromisso"...), read from runtime/registry/search_stop_words.json: they name the kind of thing, so a line that says "o evento corte de cabelo" has the title "corte de cabelo"."""
    return set(registry_data.search_stop_words()["nouns"]) - TITLE_NOUNS


def _exact(title_words: list, line_words: list) -> bool:
    """Whether the line's title span is the title: the title's words, all of them and in order, are a run of the line's words, and every word of the line outside that run is a
    word that names no event (a stop word, or the name of an account). "cancela o almoco com a ana" is not exact for an event called "Ana"; "corte cabelo" is not for "corte de cabelo"."""
    n, skippable = len(title_words), _stop_words() | _brand_words() | _noun_words()
    return n > 0 and any(line_words[i:i + n] == title_words and all(w in skippable for w in line_words[:i] + line_words[i + n:]) for i in range(len(line_words) - n + 1))


def ranked(rows: list, said: str, kind: str, value, today: datetime.date) -> list:
    """The events of `rows` that the line names, by the closest name (slice S16b): in the window or on the named day, and whose title is near the words of the line (case and accents
    folded, the closed stop words left out, a small edit distance for each word, at least half of the title's words), each row with its "score" and whether its name is "exact"
    (`_exact`). The words of the line are those left when a confirmation word at its edges is taken out; the words the time engine reads as a day or a time are taken out too, so
    that a title such as "Dia" is not named by "dia 23", except for a title that holds such a word itself ("Reuniao 10h"), which is read against the whole line; the name of an
    account is a word of the line like any other (it makes the title that holds it the closer one). The best row is the one when it beats the next by CLOSE_MARGIN; else the rows within CLOSE_MARGIN
    of it, in the order given, are the several close ones; and among those, the rows whose name is exact win alone, the near ones being dropped."""
    whole_words = _edges(said)
    bare_words = _edges(nt.without(said, nt._spans(nt.find(said))))
    fits = []
    for row in rows:
        words = _words(row["title"])
        title = _tokens(words)
        if sum(len(w) for w in words) < TITLE_MIN or not title:
            continue
        line_words = whole_words if nt.find(row["title"])["hits"] else bare_words
        score = _fit(title, _tokens(line_words))
        if score < SCORE_MIN:
            continue
        if kind == "day":
            ok = row["day"] == value
        else:
            ok = today <= row["day"] <= today + datetime.timedelta(days=WINDOW_DAYS) and (kind != "weekday" or row["day"].weekday() == value)
        if ok:
            fits.append(dict(row, score=score, exact=_exact(words, line_words)))
    if not fits:
        return []
    best = max(f["score"] for f in fits)
    close = [f for f in fits if f["score"] >= best - CLOSE_MARGIN]
    if len(close) > 1:
        close = [f for f in close if f["exact"]] or close
    return close if len(close) > 1 else close[:1]


def candidates(rows: list, said: str, kind: str, value, today: datetime.date) -> list:
    """`ranked` under the name the S6 search was called by."""
    return ranked(rows, said, kind, value, today)


def _narrowed(ctx: dict, rows: list, text: str, kind: str, value, today: datetime.date, said: str, account):
    """(the events that fit, the account that narrowed them): an account word narrows the search to that account's calendars, except when the word stands in the title of an
    event that fits the line ("cancela a reuniao do google"): then it is part of the name, no account is named, and every fitting event is listed."""
    fits = candidates(rows, text, kind, value, today)
    if account and any(account_named(said, fit["title"]) != account for fit in fits):
        account = None
    return (candidates(_of_account(ctx, rows, account), text, kind, value, today) if account else fits), account


# --- the reply -----------------------------------------------------------------------------------------------------------------------------------


def _shown(row: dict, with_source: bool, table=None) -> str:
    """One line of the list of events. With events of two sources the source ends the line: the plain name of the calendar when `table` (runtime/source_names.py `catalog`, BL5D) knows
    it, else its id."""
    day = row["day"]
    weekday = ENGLISH_WEEKDAY[day.weekday()]
    where = f" ({(table or {}).get(row['source'], {}).get('name') or row['source']})" if with_source else ""
    return f"{row['n']}. {weekday} {day.strftime('%d/%m/%Y')} {row['time']} · {row['title']}{where}"


def _when(row: dict) -> str:
    """`Fri 23/10/2026 14:00-15:00` (the shape a phone renders in its language), the day and the time of an event."""
    return f"{ENGLISH_WEEKDAY[row['day'].weekday()]} {row['day'].strftime('%d/%m/%Y')} {row['time']}"


_ZONE_TAIL = re.compile(r"\s*\([^()]*\)$")


def _found_fields(ctx: dict, extras: dict, row: dict) -> dict:
    """{"title", "when"} of the "Encontrei ... É este?" line: the event as the card has it, read live from the provider when the card was prepared (the lines "the event now" of
    the stored card), not as the snapshot or the ledger had it; the row's own values only when the card holds no such line. The zone the card adds to a time is left off."""
    title, when = row["title"], _when(row)
    try:
        item = ctx["store"].pending_get(ctx["conn"], extras["resend"])
        card = item["payload"]["card"]
    except Exception:      # noqa: BLE001 - no card to read: the row's values
        return {"title": title, "when": when}
    for key, fields in card:
        if key == "CARD_CAL_NOW_TITLE" and fields.get("title") not in (None, "-"):
            title = fields["title"]
        elif key == "CARD_CAL_NOW_WHEN" and fields.get("when"):
            when = _ZONE_TAIL.sub("", fields["when"])
    return {"title": title, "when": when}


def _list(ctx: dict, op: str, found: list) -> str:
    many = len({r["source"] for r in found}) > 1
    table = source_names.catalog(ctx) if many else None
    lines = [_shown(r, many, table) for r in found[:LIST_MAX]]
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


# The words of an object that is not an event (closed lists in the six languages of the tables, folded): a line that names one of these, or an address, asks for something
# else than an event even when its verb is "cancel" or "move" (slice S16b, review round).
OTHER_OBJECTS = {
    "mail": ("email", "emails", "mail", "mails", "mensagem", "mensagens", "message", "messages", "mensaje", "mensajes", "correo", "correos", "correio", "courriel", "courriels",
             "nachricht", "nachrichten", "messaggio", "messaggi", "posta"),
    "file": ("arquivo", "arquivos", "file", "files", "archivo", "archivos", "fichier", "fichiers", "datei", "dateien", "documento", "documentos", "document", "documents"),
    "reminder": ("lembrete", "lembretes", "reminder", "reminders", "recordatorio", "recordatorios", "rappel", "rappels", "erinnerung", "erinnerungen", "promemoria"),
    "routine": ("rotina", "rotinas", "routine", "routines", "rutina", "rutinas", "routinen"),
    "task": ("tarefa", "tarefas", "task", "tasks", "tarea", "tareas", "tache", "taches", "aufgabe", "aufgaben", "compito", "compiti"),
    "folder": ("pasta", "pastas", "folder", "folders", "carpeta", "carpetas", "dossier", "dossiers", "ordner", "cartella", "cartelle"),
    "request": ("pedido", "pedidos", "request", "requests", "solicitud", "solicitudes", "demande", "demandes", "anfrage", "anfragen", "richiesta", "richieste"),
}
CONDITIONAL = {"se", "caso", "qualora", "si", "if", "unless", "falls", "wenn", "sofern", "cas"}      # validate: allow english-only -- the closed words of the languages a line may be written in


def names_other_object(said: str) -> bool:
    """Whether the line names an object that is not an event (OTHER_OBJECTS) or holds an address: then the verb of the line does not tell that it is about an event."""
    if "@" in said:
        return True
    words = set(_words(said))
    return any(words.intersection(group) for group in OTHER_OBJECTS.values())


def asks_again(said: str) -> bool:
    """Whether a line is not a plain request to change or cancel one event: it ends in a question mark, it carries a condition after its verb ("... se chover", "... caso ..."), or it
    holds two verbs that change or cancel ("cancela o corte e muda ..."). Such a line is asked again, whatever the model said."""
    if said.rstrip().endswith(("?", "\uff1f")):
        return True
    tables = natural._tables(None)
    line = nw.Line(said)
    verbs = nw.listed(tables, "calendar", "cancel_verbs") + nw.listed(tables, "calendar", "change_verbs")
    spans = line.find_all(verbs, 0)
    if len(spans) >= 2:
        return True
    if spans:
        after = line.norm[spans[0][1]:].split()
        return any(w.strip(",.;:!") in CONDITIONAL for w in after[:-1])
    return False


def _is_all_day(row: dict) -> bool:
    return bool(row.get("all_day")) or str(row.get("time", "")).startswith("all day")


def _past_problem(start: str, now):
    """The sentence key when the new start (`YYYY-MM-DDTHH:MM`) cannot be used as it is, by the same check the model's times pass (interpreter._instant_problem: past, far, a
    clock that skips or repeats the hour), else None. A start the line fixed on the event's own day is checked here too: it is never taken for a time the check accepted."""
    why = interpreter._instant_problem(datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M"), now.tzinfo, now)
    return {"time-past": "IX_ASK_PAST", "time-far": "IX_ASK_FAR"}.get(why, "IX_ASK_TIME") if why else None


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
    return _text(ctx, "EV_NAME_NONE_DAY" if kind == "day" else "EV_NAME_NONE", days=WINDOW_DAYS)


def _code_time(said: str, now):
    """The time the line says when no model read it: {"local": "YYYY-MM-DDTHH:MM", "dated": whether the line names a day} for exactly one clear reading with nothing doubtful
    in it, else None (the change then asks what to change; a time is never guessed)."""
    if nt.doubt(said):
        return None
    found = nt.parse(said, now)
    if not found or "when" not in found:
        return None
    reading = found["reading"]
    if reading.get("assumed_year") or reading.get("far"):
        return None
    return {"local": f"{reading['date']}T{reading['time']}", "dated": bool(reading.get("dated"))}


def _clock_only(time_: dict, spans: dict, now) -> bool:
    """Whether the time of a change is a clock with no day ("para as 10h"): then it is the clock of the event's own day."""
    if "dated" in time_:
        return not time_["dated"]
    return bool(spans.get("time")) and _day_named(spans["time"], now)[0] == "none"


def by_name(project: str, ctx: dict, said: str, sender, extras: dict, writes, now):
    """The reply for a line that asks to change or cancel an event with no number in it, as code reads it (slice S16b): the operation is the one the leading verb names, the time
    is what the time engine reads without doubt, and the event is found by the closest name (`open_event`), whoever read the line. None when the line has no such verb."""
    op = verb_op(said)
    if op is None:
        return None
    if names_other_object(said):          # "mude o lembrete de pagar a conta para as 10h": a reminder, not an event; the line is not carried out as anything else here
        extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
        return _text(ctx, "IX_CANNOT_WRITE")
    decision = {"op": op, "time": _code_time(said, now) if op == "event-change" else None, "spans": {}, "args": {}}
    return open_event(project, ctx, decision, said, sender, extras, writes, now)


def open_event(project: str, ctx: dict, decision: dict, said: str, sender, extras: dict, writes, now):
    """The reply for a decision to change or cancel an event (module text). `writes` is the module ops_natural_writes, which opens the card. A number WRITTEN in the line
    (`args["event"]`) is the numbered form; else the words the model took out of the line as the event's name and day (`spans` target, day: B''-lite, `_by_target`); else the
    whole line is the search text, as before."""
    op, time_ = decision["op"], decision.get("time")
    if asks_again(said):          # a question, a condition, or two verbs: nothing is opened, whatever the model said
        extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
        return _text(ctx, "IX_ASK_AGAIN")
    spans = decision.get("spans") or {}
    if "event" not in (decision.get("args") or {}) and (spans.get("target") or spans.get("day")):
        return _by_target(project, ctx, decision, said, sender, extras, writes, now)
    reading = nw.read(said, now, op=op)
    if reading is None or (not reading.get("say") and "event" in reading["slots"]):
        opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, hint=op)          # the call as before: the numbered form, or nothing the family reads
        if opened is not None:
            return opened
    extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
    if names_other_object(said):          # no number, and the line names a mail, a file, a reminder, a routine, a task, a folder or an address: it is not about an event, whoever read it
        return _text(ctx, "IX_CANNOT_WRITE")
    text = " ".join(said.split())
    for key in (("time", "title") if op == "event-change" else ()):          # the new time and the new title are not the words of the event to change
        if spans.get(key):
            text = _cut(text, spans[key])
            if text is None:
                return _text(ctx, "EV_ASK_DAY")          # a span the line does not hold as written: no day is read from the unstripped line
    kind, value = _day_named(text, now)
    if kind == "unread":
        return _text(ctx, "EV_ASK_DAY")
    return _found(project, ctx, op, time_, spans, said, sender, extras, writes, now, text, kind, value)


def _rest_of(said: str, spans: dict):
    """The line with the pieces the model took out of it (the event's name, its day, the new time and the new title: the spans the check verified) blanked, each at its first occurrence
    in the line with its white space collapsed, or None when a span is not in the line as written. What is left is read for a day only (`_by_target`). Spans that overlap are blanked
    together, so a day span that lies inside the target is cut once and is no unreadable line."""
    text = " ".join(said.split())
    cut = [False] * len(text)
    for key in ("target", "day", "time", "title"):
        piece = " ".join(str(spans.get(key) or "").split())
        if not piece:
            continue
        at = text.find(piece)
        if at < 0:
            return None
        for i in range(at, at + len(piece)):
            cut[i] = True
    return "".join(" " if gone else c for gone, c in zip(cut, text))


def _same_day(a, b):
    """The day two readings of `_day_named` have in common ((kind, value) pairs of a day or a weekday), or None when they differ: a weekday equals a date that falls on it, and the date
    is the one kept."""
    (ka, va), (kb, vb) = a, b
    if ka == kb:
        return a if va == vb else None
    day, weekday = (a, b) if ka == "day" else (b, a)
    return day if day[1].weekday() == weekday[1] else None


def _day_written(ctx: dict, kind: str, value, now) -> str:
    """A day as a sentence writes it, in one form for both kinds: the weekday's word of the project's language and a date (`Wed 28/10/2026`, `qua 28/10/2026`). A weekday with no date is shown
    with the next date that falls on it, counting from today."""
    if kind != "day":
        today = now.date()
        value = today + datetime.timedelta(days=(value - today.weekday()) % 7)
    return f"{_text(ctx, phrases.WEEKDAY_KEYS[value.weekday()])} {value.strftime('%d/%m/%Y')}"


WRITTEN_DATES = ("ymd", "md", "monthday")          # the `spec` kinds of a date written with numbers or a month name ("2026-10-25", "25 de outubro", "dia 25"), never a word like "amanha" or "sexta"


def _written_day(rest: str, now):
    """The day a date WRITTEN in `rest` names, as `_day_named` reads it, or ("none", None): only a slash date or a date of `WRITTEN_DATES` counts, never a day word ("amanha", "sexta"), since a
    day word left in a line is as likely the day of something else ("... mas nao o de amanha") as the event's."""
    hits = [h for h in nt.find(rest)["hits"] if h["kind"] in DAY_HITS]
    if not hits or any(h["kind"] == "date" and not (isinstance(h.get("spec"), dict) and h["spec"].get("k") in WRITTEN_DATES) for h in hits):
        return "none", None
    got = _day_named(rest, now)
    return got if got[0] == "day" else ("none", None)


def _by_target(project: str, ctx: dict, decision: dict, said: str, sender, extras: dict, writes, now):
    """The reply for a change or a removal whose event the model named by its words (B''-lite): `spans["target"]` is the event's name as the line writes it and
    `spans["day"]` the day it is on, both pieces of the line that the check verified. Code finds the event with them (`_found`: the closest name over the snapshot rows and the
    events created here), never with the model's word for a number: the new time and the new title are not part of the name, so nothing is cut from the target. A target with no
    words is asked again, a target that names another object is no event, a day code cannot read is a question; none of them opens a card.

    With no day span the day is that of the target's own words, else the window search, exactly as before: the rest of the line is never read for a day ("cancela o dentista, mas nao o de
    amanha" names no day of the event). With a day span (BL5C, 2026-10-25) the day is read from two places: `own`, the day span, and `rest`, the line with the target, day, time and title
    spans cut out. `own` unread: a question. `own` a day and `rest` none: that day; the same day twice (a weekday equals a date on it): that day; two different days, or `rest` unread:
    a question, EV_ASK_WHICH_DAY naming both for the first (nothing is opened: L61, never a guess). `own` none (the model took a word that is no day, "amanhas", for the day): the day of
    a date WRITTEN in the rest (`_written_day`: a slash or numeric date, never a day word), else a question. A `rest` that names another object (a mail, a file, an address: "o e-mail
    de 25/10") is ignored: its date is not the event's."""
    op, time_ = decision["op"], decision.get("time")
    spans = decision.get("spans") or {}
    extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
    text = " ".join(str(spans.get("target") or "").split())
    if not text:
        return _text(ctx, "IX_ASK_AGAIN")
    if names_other_object(text):          # the TARGET names a mail, a file, an address...: it is not an event
        return _text(ctx, "IX_CANNOT_WRITE")
    if not spans.get("day"):          # no day span: the day of the target's own words, else the window search, as before; the rest of the line is never read for a day
        own = _day_named(text, now)
        if own[0] == "unread":
            return _text(ctx, "EV_ASK_DAY")
        return _found(project, ctx, op, time_, spans, said, sender, extras, writes, now, text, own[0], own[1])
    own = _day_named(spans["day"], now)
    if own[0] == "unread":          # a day span the engine cannot read is a question, never a guess
        return _text(ctx, "EV_ASK_DAY")
    rest = _rest_of(said, spans)
    if rest is None:          # a span the line does not hold as written: no day is read from the unstripped line
        return _text(ctx, "EV_ASK_DAY")
    if names_other_object(rest):          # the date of a mail is not the event's day
        other = ("none", None)
    elif own[0] == "none":          # the day span names no day: only a date written in the line may stand for it, never a day word of the rest
        other = _written_day(rest, now)
    else:
        other = _day_named(rest, now)
    if other[0] == "unread":
        return _text(ctx, "EV_ASK_DAY")
    if own[0] == "none":
        if other[0] == "none":
            return _text(ctx, "EV_ASK_DAY")
        own = other
    elif other[0] != "none":
        same = _same_day(own, other)
        if same is None:
            return _text(ctx, "EV_ASK_WHICH_DAY", a=_day_written(ctx, *own, now), b=_day_written(ctx, *other, now))
        own = same
    return _found(project, ctx, op, time_, spans, said, sender, extras, writes, now, text, own[0], own[1])


def _found(project: str, ctx: dict, op: str, time_, spans: dict, said: str, sender, extras: dict, writes, now, text: str, kind: str, value):
    """The search and its three results, shared by the whole-line path and the target path: `text` is the words that name the event, `kind` and `value` the day they name
    (`_day_named`). One card (through the family path, never approved here), the numbered list of the events that fit, or one plain sentence; the calendar is read again once on a miss."""
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
    if all(r.get("recurring") for r in found):          # CB-7: every event found is part of a series: a change is refused in a plain sentence, a cancel is the whole series, one occurrence or a question
        series = importlib.import_module("event_series").reply(project, ctx, op, found, kind, value, spans, said, sender, extras, writes, now, account)
        if series is not None:
            return series
    if len(found) > 1 or extra:
        remember_list(ctx, sender, op, found, ("@" + time_["local"][11:16] if _clock_only(time_, spans, now) else time_["local"]) if op == "event-change" and time_ else None)
        note_start_source(ctx, sender, time_.get("source") if time_ else None)
        return _list(ctx, op, found) + (("\n" + _text(ctx, "EV_MORE", k=extra)) if extra else "")
    slots, was = {"event": found[0]["n"], "source": found[0]["source"]}, found[0]
    if found[0]["source"] == event_created.SOURCE:          # a card number, not a place in a snapshot: the reference `created:<card>` (runtime/ops_natural_calendar.py)
        slots = {"created": found[0]["pending"], "account": found[0]["account"]}
    elif account:
        slots["account"] = account
    if op == "event-change":
        title = spans.get("title")
        if time_:
            if _is_all_day(was):          # an all-day event has no length for a clock: none is picked
                return _text(ctx, "EV_ALLDAY_CLOCK")
            slots["start"] = _start_on("@" + time_["local"][11:16], was["day"]) if _clock_only(time_, spans, now) else time_["local"]
            problem = _past_problem(slots["start"], now)          # the moment on the event's day is checked as any time is (TIME-GUARD): never taken for one the check accepted
            if problem:
                return _text(ctx, problem)
        if title and _words(title) != _words(found[0]["title"]):
            slots["title"] = title
        if "start" not in slots and "title" not in slots:
            return _text(ctx, "EV_CHANGE_WHAT")
    origins = {"event": "grounded", **({"account": "card-copy"} if "created" in slots else {"account": "line-span"} if "account" in slots else {}),
               **({"title": "line-span"} if "title" in slots else {}), **({"start": turn_gate.time_origin(time_)} if "start" in slots else {})}      # the time is the code's or the model's, as the interpreter said          # S41-7: the event was found by the words of the line (a ranking over the snapshot or the events created here); never an address
    opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed=turn_gate.Seed({"op": op, "slots": slots}, origins))
    if opened is not None and not was.get("exact", True):          # the name was near, not the same: the person is shown which event it is, and the card that follows is the question
        lead = _text(ctx, "EV_FOUND", **_found_fields(ctx, extras, was))
        extras["lead"] = lead          # a messaging app says it BEFORE the card (the bridge), never after it
        return lead + "\n" + opened
    return opened


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
