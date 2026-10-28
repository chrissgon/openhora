#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The numbered items of the mail and calendar snapshots (package NR-5a): the read that gives "o e-mail 3" and "o evento 2" something to point to on a phone.

  items(project[, kind, source])   for each registered mail (or calendar) source, the items of its newest snapshot, numbered as the references `<source>#<n>` number them
                                   (runtime/item_refs.py): a message by its sender and subject, an event by its line as the snapshot prints it

Fresh lists (S15). On a line from a messaging app, a source whose newest snapshot was read more than FRESH_S seconds ago (10 minutes) is read again once before the list is made
(`ops_sources.source_refresh`, the one provider read of a snapshot, as runtime/event_lookup.py `refresh` does it for a calendar), under the read right the sender already holds
(`item_refs.may_read`, checked first; no new group). One refresh for each source for a line; a failure is dropped (nothing of the provider's words is kept or said) and the list is the
old snapshot, with one short note of the time it was read (`NW_ITEMS_OLD`). A line that names an account ("do meu Outlook") lists and refreshes only that account's sources. With no source
of the asked kind (or of the named account) the reply says what to add: a phone gets one plain sentence with no command (limit L62); the terminal, the conversation and the page get the
exact `source-mail` / `source-calendar` command with an example origin for each configured account. A listing unchanged since the last read makes no new version; the check is remembered (S15b, below), so a list asked again within FRESH_S of it reads nothing.

On a phone (`reply`, channel messaging) the list is written for a person and not for a program: each source has a plain name ("Google calendar", "Gmail"; runtime/source_names.py, BL5D) and not its id, the time it was read is in the
machine's zone ("read at 10:31", with the day when it is not today), each event is written with its weekday and date ("Thu 22/10 14:00–15:00 · haircut") in the project's language, the
organizer is left out when it is the person and said in words otherwise, and no internal word of the snapshot's text shows. The numbers are the snapshot's own, as before (the numbered forms and
runtime/event_lookup.py read them). The terminal and the page keep the source id and the line as the snapshot prints it.

S15b. A refresh that finds the listing unchanged makes no new version, so the snapshot still says when it was read; the check is remembered apart (`_CHECKED`, a time for each source and no
content, in memory) and the phone says "checked at 16:59" when it is later than the reading. A refresh that fails writes one line to stderr with a word of a closed list and no text of
the provider (`items: refresh of <source> failed (<word>)`), and the phone gets the note of the old snapshot. A mail on a phone is one line for a person: the sender's display name (else the
address without the random token of its local part, plus the domain), the subject as it is, and when it came ("today 14:02", "yesterday 09:39", "Mon 20/10 18:10"). A line that asks for the
last e-mail ("o último email", "the last email") lists that one message with the start of its text (about 300 characters of the snapshot's own cleaned body); "os 3 últimos emails" lists three,
newest first; the words of the count are a closed list in code (runtime/items_mail.py). The terminal and the page keep today's form.
CB-2. A row of a mail source carries `unread` (true or false) when the index has the provider's flag for the message, and no key when it is null (an index written before the key, or a provider that
printed none); a phone's list puts the closed mark `NW_ITEMS_UNREAD_MARK` before a message whose flag is true and nothing before one whose flag is false or not known.

CB-1 (MAIL-QUERY). A list can be narrowed, by code, over the snapshots' own index: `match` (the content words of a `target` span, or the words of the typed `--match`) keeps the messages whose
sender or subject hold every word (`natural_writes_mail.match_words`) and the events whose title holds every word (the stop words of runtime/registry/search_stop_words.json left out); a day or a
week (the `day` span, else the line as before) keeps the messages whose `received` day, in the machine's zone, is inside it (a message with no `received` is left out and counted: `NW_ITEMS_MATCH_NODATE`);
`unread` keeps the messages whose index `unread` is true (CB-2). On a phone, a source whose messages all have no flag is read once more under the turn's budget (the terminal and the page read no provider, S15); if they still have none, nothing is listed for it and the
reply says the unread state is not known (`NW_ITEMS_UNREAD_UNKNOWN`), never a guess. A `match` that holds no content word filters nothing and the reply says so (`NW_ITEMS_MATCH_EMPTY`). Nothing reaches a
model: the narrowing is code over the index, and a phone's header names it (`NW_ITEMS_MATCH_HEAD`). A day or a state the person stated and code cannot read is a sentence, never a list that looks filtered (`unreadable_filter`).

S15c. A source that is registered and has nothing in its window is empty, never missing: `missing` is only for a kind (and account) with no source in the catalog, and a phone is told in one
sentence what was looked at ("No e-mail in the Outlook inbox in the last 7 days (checked at 16:59)."). A calendar list asked for a day or a range ("de amanha", "de hoje", "de sexta", "desta
semana") keeps the events of that day or range, read with the time engine, and its header says which ("Agenda de amanha, sab 24/10:"). After a calendar or mailbox effect has been carried out
(an event created, changed or removed; a message archived, moved or trashed) the sources of that account are marked (`mark_changed`, called where the effect is recorded) and the next list on a
phone reads the provider again whatever the age of the snapshot, so a list never shows what the person has just changed.

It reads only what a reference reads, with the same rights: the terminal, the conversation and the page, and a messaging sender whose profile lists the group `ask-mail`
(item_refs.may_read); the MCP mode has no row. The lines are another person's words, so the reply is private: it goes to the chat that asked, and the conversation stores a neutral
word for it (runtime/ops_natural.py). Every value is read back through the closed shapes of runtime/item_refs.py; the text of an event is read only after the index and the
text were checked against the store's record, and only its numbered lines are taken. Nothing is written anywhere, no provider is called and no model is.

Sibling of runtime/ops.py, which exposes it under its name. Standard library only. Runs on Python 3.9: python3 runtime/ops_items.py --help
"""
from __future__ import annotations

import datetime
import hashlib
import importlib
import re
import sys

import item_refs
import natural
import ops_actor
import ops_core as core
import items_mail as mailtext
import phrases
import registry_data
import snapshot_text
import source_names
import sources
import sources_mail
import turn_gate

LINE_MAX = 120          # characters of one line
ITEMS_MAX = 100         # items of one snapshot (the sources keep at most this many)
SHOWN_MAX = 20          # items of one source the reply prints (`render`); runtime/event_lookup.py ITEMS_SHOWN is the same number
EVENT_LINE = re.compile(r"([0-9]{1,4})\. (.+)")
HEADING = re.compile(r"## ([0-9]{4}-[0-9]{2}-[0-9]{2}) \([A-Za-z]+\)")          # the day heading the text prints above its events
ALL_DAY = re.compile(r"all day(?: until ([0-9]{4})-([0-9]{2})-([0-9]{2}))?")
RANGE = re.compile(r"[0-9]{2}:[0-9]{2}-[0-9]{2}:[0-9]{2}")
ORGANIZER = re.compile(r"organizer: (\S+)")
FLAGS = {"you: accepted": "NW_ITEMS_R_ACCEPTED", "you: declined": "NW_ITEMS_R_DECLINED", "you: tentative": "NW_ITEMS_R_TENTATIVE", "you: no answer yet": "NW_ITEMS_R_NOANSWER",
         "cancelled": "NW_ITEMS_T_CANCELLED", "tentative": "NW_ITEMS_T_TENTATIVE", "online meeting": "NW_ITEMS_T_ONLINE", "recurring": "NW_ITEMS_T_RECURRING"}          # the words snapshot_text.event_line writes
KINDS = ("mail", "calendar")
FRESH_S = 600            # a snapshot read longer ago than this is read again once for a line from a messaging app (10 minutes)
ACCOUNTS = ("google", "microsoft")
LABEL = source_names.LABEL          # BL5D: one object, the provider's plain name, shared with runtime/source_names.py
EXAMPLES = {"mail": {"google": ("mail-gmail", "gmail:box=inbox;days=7;max=50"), "microsoft": ("mail-outlook", "outlook:box=inbox;days=7;max=50")},
            "calendar": {"google": ("calendar-google", "google:calendar=primary;past=0;ahead=14"), "microsoft": ("calendar-outlook", "outlook:calendar=default;past=0;ahead=14")}}
COMMAND = {"mail": "source-mail", "calendar": "source-calendar"}
SNAPSHOT_CLOCK = None          # the clock the age of a snapshot is read against (None: the real one); a test replaces it


def _text_of(ctx: dict, source_id: str, version):
    """The text of the newest version of a source, when `version` is still the newest and its hash is the one the store records (else None): the number and the text always come from
    one snapshot."""
    latest = sources._stored(ctx, "source_latest", source_id)
    if latest is None or latest["version"] != version:
        return None
    with sources.Folder(ctx["cfg"], None) as folder:
        raw = folder.read([source_id, str(version), latest["converted_name"]], sources.CONVERTED_CAP)
    if hashlib.sha256(raw).hexdigest() != latest["converted_sha256"]:
        return None
    return raw.decode("utf-8", errors="replace")


def _event_lines(ctx: dict, source_id: str, version) -> dict:
    """{n: (the line of the event as the snapshot prints it, the day it is listed under as YYYY-MM-DD or None)} of the version `read_index` read the index of: the text is read only when the newest version is still that one
    and its hash is the one the store records, so that the number and the line always come from the same snapshot (else nothing: the lines are blank)."""
    text = _text_of(ctx, source_id, version)
    if text is None:
        return {}
    out, day = {}, None
    for line in text.splitlines():
        heading = HEADING.fullmatch(line.strip())
        if heading:
            day = heading.group(1)
            continue
        found = EVENT_LINE.fullmatch(line.strip())
        if found:
            out[int(found.group(1))] = (snapshot_text.one_line(snapshot_text.clean_text(found.group(2)), LINE_MAX), day)
    return out


def _named_account(said) -> dict:
    """{"account": "google" | "microsoft"} when the line names exactly one account (the brand words beside a lead word, runtime/event_lookup.py `account_named`), else {}."""
    found = importlib.import_module("event_lookup").account_named(said if isinstance(said, str) else "")
    return {"account": found} if found else {}


WEEK = {"semana", "week", "semaine", "woche", "settimana"}          # a word for "week" in the six languages, folded      # validate: allow english-only -- the closed words of the languages a line may be written in
NEXT = {"proxima", "proximo", "vem", "next", "nachste", "nachsten", "prochaine", "prossima", "siguiente", "viene"}          # ... and for "next"


def _range_args(said, now) -> dict:
    """{"first", "last"} (YYYY-MM-DD) when the line names a day ("de amanha", "de hoje", "de sexta", "dia 25") or this week or the next one, read with the time engine (which reads Portuguese and
    English), else {}. A date word the engine doubts names no range: the whole list is the answer."""
    if now is None or not isinstance(said, str):
        return {}
    words = natural.normal(said).split()
    today = now.date()
    if any(w in WEEK for w in words):
        monday = today - datetime.timedelta(days=today.weekday()) + (datetime.timedelta(days=7) if any(w in NEXT for w in words) else datetime.timedelta(0))
        return {"first": monday.isoformat(), "last": (monday + datetime.timedelta(days=6)).isoformat()}
    kind, value = importlib.import_module("event_lookup")._day_named(said, now)
    if kind == "weekday":
        value = today + datetime.timedelta(days=(value - today.weekday()) % 7)
    elif kind != "day":
        return {}
    return {"first": value.isoformat(), "last": value.isoformat()}


def _line_args(said, now=None) -> dict:
    """The arguments a line adds to `items`: the account it names, how many messages it asks for (runtime/items_mail.py `count_of`) and the day or week a calendar list is asked for."""
    out = _named_account(said)
    count = mailtext.count_of(said)
    return {**out, **({"count": count} if count else {}), **_range_args(said, now)}


SPAN_PARAMS = {"target": "match", "day": "day_span", "state": "state_span"}          # CB-1: the slot of `items` (catalog version 2) -> the parameter its span arrives as


def span_args_of(args) -> dict:
    """{slot: the person's span} of the v2 slots of `items` from the arguments a decision or the router checked (`SPAN_PARAMS`): only a text that is there. Pure."""
    return {slot: args[param] for slot, param in SPAN_PARAMS.items() if isinstance(args, dict) and isinstance(args.get(param), str) and args[param].strip()}


def _tables():
    return natural._tables(None)


def _read_state(span):
    """"unread" or "read" when the `state` span is one of the closed words of the mail family (`natural_writes_mail.answer`), else None."""
    got = importlib.import_module("natural_writes_mail").answer("state", span, {}, _tables())
    return got["slots"]["state"] if got else None


def unreadable_filter(spans, now):
    """The phrase key of the sentence that answers a day or a state the person stated and code cannot read, else None: a `day` span that names no day or week, a `state` span that is not "unread". A stated
    filter is never dropped silently, and a list that looks filtered while it is not would be worse than a question (CB-1). Pure."""
    spans = spans if isinstance(spans, dict) else {}
    if isinstance(spans.get("day"), str) and spans["day"].strip() and not _range_args(spans["day"], now):
        return "NW_ITEMS_MATCH_DAY"
    if isinstance(spans.get("state"), str) and spans["state"].strip() and _read_state(spans["state"]) != "unread":
        return "NW_ITEMS_MATCH_STATE"
    return None


def items_args(said, now, previous=None, spans=None) -> dict:
    """The arguments a line gives `items`, whole, so that a plan's hash binds them (BL5B): `kind` ("calendar" or "mail"), `account`, the range (`first`, `last`), `count`, and, from the interpreter's
    verified spans (`spans`, {slot: span}: CB-1), `match` (the content words of the `target` span as code reads them, [] when it holds none) and `unread` (True when the `state` span is the closed word for
    unread). Each is read from the line as `_line_args` reads it; the range comes from the `day` span when there is one. `previous` is the arguments of the plan this line corrects (the sender's own
    live plan, never a third party's): the kind the new line names wins ("no, the e-mails"), else the old kind is kept, else the line alone decides (`items_kind`); the account, the range and the `match`
    the old plan had are kept when the new line names none. A number of messages (`count`) is only the line's own. Pure: nothing is read."""
    spans = spans if isinstance(spans, dict) else {}
    found = _line_args(said, now)
    if isinstance(spans.get("day"), str) and spans["day"].strip():
        read = _range_args(spans["day"], now)
        if read:
            found = {**{k: v for k, v in found.items() if k not in ("first", "last")}, **read}
    noun = importlib.import_module("natural_writes").items_noun(said)
    old = previous if isinstance(previous, dict) else {}
    kind = noun or old.get("kind") or importlib.import_module("natural_writes").items_kind(said)
    out = {"kind": kind, **found}
    if "account" not in out and old.get("account"):
        out["account"] = old["account"]
    if "first" not in out and old.get("first") and old.get("last"):
        out.update(first=old["first"], last=old["last"])
    if isinstance(spans.get("target"), str) and spans["target"].strip():
        out["match"] = importlib.import_module("natural_writes_mail").target_words(spans["target"], _tables())
    elif isinstance(old.get("match"), list):
        out["match"] = list(old["match"])
    if isinstance(spans.get("state"), str) and _read_state(spans["state"]) == "unread":
        out["unread"] = True
    return out


def _account_of(row: dict):
    """The account ("google" | "microsoft") a mail or calendar source belongs to, from the implementation its origin names; None when the origin is not one this runtime reads (BL5D: the
    reading lives in runtime/source_names.py `account_of`, which the phone names use too)."""
    return source_names.account_of(row)


_CHECKED = {}          # (project, source id) -> the UTC time a read for a line last succeeded: a time and no content, in memory; a new version is not made when the listing did not change
_DIRTY = set()          # (project, source id) of a source whose account had an effect carried out since it was last read: the next list on a phone reads it whatever the age of the snapshot
CHANGING = ("archive", "move", "trash")          # the actions of a mailbox effect that change what a mailbox lists
CLOSED_WHY = ("folder", "path", "type", "size", "credential", "convert", "integrity", "notion", "usage", "unattended", "missing", "drive", "mail", "calendar")          # sources.SourcesError codes


def _now():
    return (SNAPSHOT_CLOCK() if SNAPSHOT_CLOCK else datetime.datetime.now(datetime.timezone.utc)).astimezone(datetime.timezone.utc)


def mark_changed(ctx: dict, doc) -> None:
    """Called where an approved effect has been recorded as done (runtime/ops_step_effects.py): when it changed a calendar (any operation) or a mailbox (archive, move, trash), the mail or
    calendar sources of its account need a read, so the check times are forgotten and the sources are marked. It reads no provider and never fails the approval that called it."""
    try:
        kind = {"calendar": "calendar", "mailbox": "mail"}.get(doc.get("effect"))
        if kind is None or (kind == "mail" and doc.get("action") not in CHANGING):
            return
        for row in sources.list_catalog(ctx, hashes=False):
            if row["type"] == kind and _account_of(row) in (doc.get("account"), None):
                key = (ctx["cfg"]["project"], row["id"])
                _CHECKED.pop(key, None)
                _DIRTY.add(key)
    except Exception:      # noqa: BLE001 - the effect is already recorded; a list that is not marked is read again when it is older than FRESH_S
        return


def _refresh_failed(project: str, ctx: dict, source_id: str, force: bool = False) -> bool:
    """Read a source again once when the later of its newest snapshot and its last check is older than FRESH_S (or there is none, or its time cannot be trusted), or at once when `force` says the
    snapshot cannot answer the list (CB-1: an unread filter over a snapshot whose messages carry no flag). True when that read failed
    (one line to stderr with a word of CLOSED_WHY; the provider's words are dropped), and again for a second list of the same line whose read the gate refuses (the snapshot is still old: the note stays);
    False when nothing was needed or it worked, and then the check is remembered. The provider is reached
    only by `ops_sources.source_refresh`, one source after the other: they share the store."""
    key = (ctx["cfg"]["project"], source_id)
    latest = sources._stored(ctx, "source_latest", source_id)
    last = max([t for t in (_local(latest["imported_at"]) if latest else None, _CHECKED.get(key)) if t is not None], default=None)
    age = sources.snapshot_age(last.isoformat(), SNAPSHOT_CLOCK) if last else None
    if not force and age is not None and age <= FRESH_S and key not in _DIRTY:
        return False
    if not turn_gate.may_refresh(source_id, "list-fresh"):      # L52: this line has read the source already, or no line is open: nothing was needed, the list is the snapshot as it is
        return turn_gate.failed_in_turn(source_id)      # ...but a read of this line that failed leaves the snapshot old: the second list of the line keeps its note
    try:
        importlib.import_module("ops_sources").source_refresh(project, source_id)
    except Exception as e:      # noqa: BLE001 - the fault can hold a provider's words; the list is the old snapshot and a note
        why = getattr(e, "why", None)
        print(f"items: refresh of {source_id} failed ({why if why in CLOSED_WHY else 'error'})", file=sys.stderr)
        turn_gate.mark_failed(source_id)
        return True
    _CHECKED[key] = _now()
    _DIRTY.discard(key)
    return False


def _words_given(match):
    """The folded words of a `match` argument: None for none; the words of a typed `--match` text (`natural_writes_mail.target_words`: the articles and the mail nouns left out, [] when none is left or when
    a sentence is given); a list code made (`items_args`) is checked as the words it must be. A list of no word is a filter that holds no content word: the reply says so."""
    nwm = importlib.import_module("natural_writes_mail")
    if match is None:
        return None
    if isinstance(match, str):
        return nwm.target_words(match, _tables())
    if (isinstance(match, list) and len(match) <= nwm.TARGET_WORDS_MAX
            and all(isinstance(w, str) and re.fullmatch(r"[^\W_]+", w) and w == natural.normal(w) for w in match)):
        return list(match)
    raise core.OpsError("match is a few words", 2)


def _event_words(line: str) -> set:
    """The folded whole words of an event's title and place, as the snapshot's line prints them (`when · title · place · flags`): the time and the flags the snapshot adds are not words of the event."""
    fields = [f for f in line.split(" · ")[1:] if f not in FLAGS and not ORGANIZER.fullmatch(f) and f != "organizer: you"]
    return set(re.findall(r"[^\W_]+", natural.normal(" ".join(fields))))


def _received_on(entry: dict):
    """The local date (machine zone) a message of the index came in, or None when the index has no time for it."""
    moment = _local(entry.get("received"))
    return moment.date() if moment is not None and entry.get("received") else None


def items(project: str, kind: str | None = None, source: str | None = None, channel: str | None = None, sender: str | None = None, account: str | None = None, count: int | None = None,
          first: str | None = None, last: str | None = None, match=None, unread: bool = False) -> dict:
    ctx = core.context(project)
    ops_actor.guard(ctx, "items", channel, sender)
    if kind is not None and kind not in KINDS:
        raise core.OpsError("the kind of item is mail or calendar", 2)
    if account is not None and account not in ACCOUNTS:
        raise core.OpsError("the account is google or microsoft", 2)
    if count is not None and (type(count) is not int or not 1 <= count <= mailtext.COUNT_MAX):
        raise core.OpsError(f"the count is a number from 1 to {mailtext.COUNT_MAX}", 2)
    try:
        span = (datetime.date.fromisoformat(first), datetime.date.fromisoformat(last)) if first or last else None
    except (TypeError, ValueError):
        raise core.OpsError("first and last are dates, YYYY-MM-DD", 2) from None
    if unread not in (True, False):
        raise core.OpsError("unread is a flag", 2)
    words = _words_given(match)
    stops = set(registry_data.search_stop_words()["stop_words"])
    event_words = None if words is None else [w for w in words if w not in stops]
    if not item_refs.may_read(ctx, channel, sender):
        raise core.OpsError(phrases.en("NW_REF_NOT_READABLE"), 1)
    with turn_gate.turn():      # S41-6: the line's refresh budget (limits L52 and L53); an inner reuse inside a line, an entry of its own when the entry is called directly
        phone = channel == ops_actor.MESSAGING
        found, refused, matched = [], [], 0
        for row in sources.list_catalog(ctx, hashes=False):
            if row["type"] not in KINDS or (kind and row["type"] != kind) or (source and row["id"] != source):
                continue
            if account and _account_of(row) != account:
                continue
            matched += 1
            force = False
            if unread and phone and row["type"] == "mail":      # CB-1: a snapshot whose messages carry no flag (one made before CB-2, or a provider that printed none) cannot answer an unread filter: the list reads it once more, whatever its age
                try:
                    peek = item_refs.read_index(ctx, row["id"], channel=channel, sender=sender, kinds=(row["type"],), clock=SNAPSHOT_CLOCK)["entries"][:ITEMS_MAX]
                except item_refs.ItemRefError:
                    peek = []      # the read below says why a snapshot cannot be listed
                force = bool(peek) and all(e.get("unread") is None for e in peek)
            old = phone and _refresh_failed(project, ctx, row["id"], force)
            try:
                snapshot = item_refs.read_index(ctx, row["id"], channel=channel, sender=sender, kinds=(row["type"],), clock=SNAPSHOT_CLOCK)
            except item_refs.ItemRefError as e:
                refused.append({"source": row["id"], "why": str(e)})
                continue
            nodate, unknown = 0, False
            if row["type"] == "mail":
                entries = snapshot["entries"][:ITEMS_MAX]
                unknown = bool(unread) and bool(entries) and all(e.get("unread") is None for e in entries)      # still none after the one read: the state is not known, and nothing is listed for this box
                if unknown:
                    entries = []
                else:
                    if words:      # CB-1: the sender or subject words of the index, every one of them (a word of the person's, never a word of a message)
                        entries = importlib.import_module("natural_writes_mail").match_words(entries, words)
                    if span:      # CB-1: the day or week, by the local day a message came in; an entry with no time is left out and counted, never guessed
                        nodate = sum(1 for e in entries if _received_on(e) is None)
                        entries = [e for e in entries if _received_on(e) is not None and span[0] <= _received_on(e) <= span[1]]
                    if unread:
                        entries = [e for e in entries if e.get("unread") is True]
                rows = [{"n": e["n"], "line": snapshot_text.one_line(f"{e.get('from_address') or '?'} · {e.get('subject') or ''}", LINE_MAX)} for e in entries]
                for r, e in zip(rows, entries):
                    if isinstance(e.get("unread"), bool):      # CB-2: the provider's flag, only when it printed one (null: not known, so no key); a phone marks the true ones
                        r["unread"] = e["unread"]
                if phone or count:      # S15b: when it came and, for a phone, who and what, from the text the index was read with
                    text = _text_of(ctx, row["id"], snapshot["version"])
                    parsed = mailtext.blocks(text) if text is not None else {}
                    for r, e in zip(rows, entries):
                        block = parsed.get(e["n"], {})
                        r["received"] = block.get("when")
                        if phone:
                            r["mail"] = {"who": mailtext.who(block.get("from", ""), e.get("from_address") or ""), "subject": snapshot_text.one_line(e.get("subject") or "", mailtext.SUBJECT_MAX),
                                         **({"body": block.get("body", [])} if count == 1 else {})}
            else:
                lines = _event_lines(ctx, row["id"], snapshot["version"])
                rows = [{"n": e["n"], "line": lines.get(e["n"], ("", None))[0], "day": lines.get(e["n"], ("", None))[1]} for e in snapshot["entries"][:ITEMS_MAX]]
                if span:      # S15c: a day or a week was asked for: only the events listed under those days (the numbers stay the snapshot's own)
                    rows = [r for r in rows if r["day"] and span[0].isoformat() <= r["day"] <= span[1].isoformat()]
                if event_words:      # CB-1: the events whose title and place hold every word (the stop words of the registry left out)
                    rows = [r for r in rows if set(event_words) <= _event_words(r["line"])]
            checked = _CHECKED.get((ctx["cfg"]["project"], row["id"])) if phone else None
            later = checked is not None and (_local(snapshot["read_at"]) or checked) < checked
            found.append({"source": row["id"], "type": row["type"], "account": _account_of(row), "read_at": snapshot["read_at"], "items": rows,
                          **({"old": True} if old else {}), **({"checked_at": checked.isoformat()} if later else {}),
                          **({"nodate": nodate} if nodate else {}), **({"unread_unknown": True} if unknown else {}),
                          **({"window": _window(ctx, row, snapshot)} if not rows else {})})
        if count:
            _newest(found, count, phone)
        out = {"sources": found, "refused": refused, **({"range": {"first": first, "last": last}} if span else {})}
        if words is not None or unread:      # CB-1: what the list was narrowed by, in code's words (the header and the notes of a phone read it)
            types = {e["type"] for e in found}
            out["filter"] = {"words": words or [], "unread": bool(unread)}
            if words is not None and ("mail" in types and not words or "calendar" in types and not event_words):
                out["match_empty"] = True      # a `match` with no content word filters nothing for that kind: the reply says so, it never passes for a filtered list
        if kind and not matched:      # S15c: only when no source of the asked kind (and account) is registered; a registered one with nothing in its window is not missing
            out["missing"] = {"kind": kind, "account": account}
        return out


def _window(ctx: dict, row: dict, snapshot: dict) -> dict:
    """What an empty source looked at, for the sentence that says so: {"days": n} for a mailbox (the origin's), {"first", "last"} (YYYY-MM-DD) for a calendar (the snapshot's own range,
    else the origin's past and ahead around the day it was read)."""
    origin = sources_mail.origin_of(row["type"], row["origin"])
    if row["type"] == "mail":
        return {"days": origin["days"]}
    text = _text_of(ctx, row["id"], snapshot["version"]) or ""
    found = re.search(r"^# Calendar snapshot of .*?, ([0-9]{4}-[0-9]{2}-[0-9]{2}) to ([0-9]{4}-[0-9]{2}-[0-9]{2}) \(", text, re.M)
    if found:
        return {"first": found.group(1), "last": found.group(2)}
    day = (_local(snapshot["read_at"]) or _now().astimezone()).date()
    return {"first": (day - datetime.timedelta(days=origin["past"])).isoformat(), "last": (day + datetime.timedelta(days=origin["ahead"])).isoformat()}


def _range_words(span: dict, cfg: dict) -> tuple:
    """(the header label, the words for a sentence) of the day or week a calendar list was asked for: ("for tomorrow, Sat 24/10", "tomorrow"), ("for Fri 23/10", "on Fri 23/10"),
    ("for the week, Mon 19/10 to Sun 25/10", "between 19/10 and 25/10"), in the project's language."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    first, last = (datetime.date.fromisoformat(span[k]) for k in ("first", "last"))
    shown = lambda day: f"{t(phrases.WEEKDAY_KEYS[day.weekday()])} {day.strftime('%d/%m')}"  # noqa: E731
    today = (SNAPSHOT_CLOCK() if SNAPSHOT_CLOCK else datetime.datetime.now(datetime.timezone.utc)).astimezone().date()
    if first != last:
        return t("NW_ITEMS_RL_WEEK", first=shown(first), last=shown(last)), t("NW_ITEMS_EW_RANGE", first=first.strftime("%d/%m"), last=last.strftime("%d/%m"))
    if first == today:
        return t("NW_ITEMS_RL_TODAY", day=shown(first)), t("NW_ITEMS_EW_TODAY")
    if first == today + datetime.timedelta(days=1):
        return t("NW_ITEMS_RL_TOMORROW", day=shown(first)), t("NW_ITEMS_EW_TOMORROW")
    return t("NW_ITEMS_RL_DAY", day=shown(first)), t("NW_ITEMS_EW_DAY", day=shown(first))


def _filter_pieces(kind: str, filt, cfg: dict, span=None) -> str:
    """What a list was narrowed by, in the person's words, as the pieces of a phrase, each with a space before it: ` with "bank"`, ` (unread only)`, ` between 19/10 and 25/10` (the words code read, at most
    80 characters; the day or week only for a mail list, a calendar list names its range in its own header). "" when the list was not narrowed."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    filt = filt if isinstance(filt, dict) else {}
    words = [w for w in filt.get("words") or [] if kind == "mail" or w not in registry_data.search_stop_words()["stop_words"]]
    pieces = [t("NW_ITEMS_MATCH_WORDS", words=snapshot_text.one_line(" ".join(words), 80))] if words else []
    if kind == "mail" and filt.get("unread"):
        pieces.append(t("NW_ITEMS_MATCH_UNREAD"))
    if kind == "mail" and span:
        pieces.append(_range_words(span, cfg)[1])
    return "".join(" " + piece for piece in pieces)


def _empty_sentence(entry: dict, cfg: dict, span=None, filt=None) -> str:
    """The one sentence for a registered source with nothing in its window: "No e-mail in the Outlook inbox in the last 7 days (checked at 16:59)." / "No event in the Google calendar between
    16/10 and 30/10 (...)." / "No event in the Google calendar tomorrow (...)."."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    label = LABEL[entry["type"]].get(entry.get("account"))
    checked = entry.get("checked_at")
    state = t("NW_ITEMS_STATE_CHECKED" if checked else "NW_ITEMS_STATE_READ", when=_read_when(checked or entry["read_at"], cfg))
    name = t("NW_ITEMS_NAMEIN_MAIL" if entry["type"] == "mail" else "NW_ITEMS_NAMEIN_CAL", service=label) if label else entry["source"]
    narrowed = _filter_pieces(entry["type"], filt, cfg, span)
    if narrowed and entry["type"] == "calendar" and span:
        narrowed += " " + _range_words(span, cfg)[1]
    if narrowed:      # CB-1: a list that was narrowed says by what, in one sentence ("No e-mail with "bank" between 19/10 and 25/10 in the Gmail inbox (checked at 16:59).")
        return t("NW_ITEMS_EMPTY_MAIL_MATCH" if entry["type"] == "mail" else "NW_ITEMS_EMPTY_CAL_MATCH", name=name, filter=narrowed, state=state)
    window = entry.get("window") or {}
    if entry["type"] == "mail":
        days = window.get("days", 0)
        return t("NW_ITEMS_EMPTY_MAIL_ONE" if days == 1 else "NW_ITEMS_EMPTY_MAIL", name=name, days=days, state=state)
    if span:
        return t("NW_ITEMS_EMPTY_CAL_AT", name=name, when=_range_words(span, cfg)[1], state=state)
    shown = [datetime.date.fromisoformat(window[k]).strftime("%d/%m") if k in window else "?" for k in ("first", "last")]
    return t("NW_ITEMS_EMPTY_CAL", name=name, first=shown[0], last=shown[1], state=state)


def _newest(found: list, count: int, phone: bool) -> None:
    """Keep the `count` newest messages of the mail sources (by the time the snapshot prints, a source's own order breaking a tie), each under its source with its own number, so that
    the numbered forms still point at the same messages; a source the selection left with none is dropped, but a source that had none to begin with stays (S15c: it is told as empty). With one message asked and one kept, the phone's row also gets the start of its text."""
    candidates = [(entry["source"], row) for entry in found if entry["type"] == "mail" for row in entry["items"]]
    empty = {entry["source"] for entry in found if entry["type"] == "mail" and not entry["items"]}
    keep = {(source, row["n"]) for source, row in sorted(candidates, key=lambda c: c[1].get("received") or "", reverse=True)[:count]}
    for entry in list(found):
        if entry["type"] == "mail":
            entry["items"] = [row for row in entry["items"] if (entry["source"], row["n"]) in keep]
            if not entry["items"] and entry["source"] not in empty:
                found.remove(entry)
    if phone and count == 1 and len(keep) == 1:
        row = next(row for entry in found if entry["type"] == "mail" for row in entry["items"])
        row["preview"] = mailtext.preview(row["mail"].get("body", []))
    for entry in found:
        for row in entry["items"]:
            row.get("mail", {}).pop("body", None)


def _local(read_at):
    """The aware datetime a snapshot's `read_at` names, in the machine's zone, or None when it cannot be read."""
    try:
        return datetime.datetime.fromisoformat(str(read_at).replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def _read_when(read_at: str, cfg: dict) -> str:
    """"at 10:31", or "on 21/10 at 10:31" when the snapshot was read on another day than today, in the machine's zone."""
    moment = _local(read_at)
    if moment is None:
        return "?"
    now = (SNAPSHOT_CLOCK() if SNAPSHOT_CLOCK else datetime.datetime.now(datetime.timezone.utc)).astimezone()
    if moment.date() == now.date():
        return phrases.text("NW_ITEMS_WHEN_TODAY", cfg, time=moment.strftime("%H:%M"))
    return phrases.text("NW_ITEMS_WHEN_DAY", cfg, day=moment.strftime("%d/%m"), time=moment.strftime("%H:%M"))


def _names(entries: list, cfg: dict) -> dict:
    """{source id: the plain name a phone shows}: "Gmail", "Google Calendar"; a source whose account is not known keeps its id; two sources of one name are numbered."""
    named = {}
    for entry in entries:
        label = LABEL[entry["type"]].get(entry.get("account"))
        named[entry["source"]] = source_names.plain(entry["type"], label, cfg) if label else entry["source"]
    for name in set(named.values()):
        twins = [i for i in named if named[i] == name]
        if len(twins) > 1:
            named.update({i: f"{name} {k}" for k, i in enumerate(twins, 1)})
    return named


def _phone_event(row: dict, cfg: dict) -> str:
    """One event of a calendar snapshot for a phone: "Thu 22/10 14:00–15:00 · haircut · organized by work.example": the weekday and date, the time, the title and place, the
    organizer only when it is not the person, and the snapshot's English words (all day, you: accepted, online meeting...) in the project's language."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    fields = row["line"].split(" · ")
    if len(fields) < 2:
        return row["line"]
    when, title = fields[0], fields[1]
    found = ALL_DAY.fullmatch(when)
    if found:
        when = t("NW_ITEMS_ALLDAY_UNTIL", date=f"{found.group(3)}/{found.group(2)}") if found.group(1) else t("NW_ITEMS_ALLDAY")
    elif RANGE.fullmatch(when):
        when = when.replace("-", "\u2013")
    try:
        day = datetime.date.fromisoformat(row.get("day") or "")
        when = f"{t(phrases.WEEKDAY_KEYS[day.weekday()])} {day.strftime('%d/%m')} {when}"
    except ValueError:
        pass
    parts = [when, title]
    for field in fields[2:]:
        who = ORGANIZER.fullmatch(field)
        if field == "organizer: you":
            continue
        parts.append(t("NW_ITEMS_ORG", who=who.group(1)) if who else t(FLAGS[field]) if field in FLAGS else field)
    return " · ".join(parts)


def _phone_mail(row: dict, cfg: dict) -> str:
    """One message for a phone: "Ana Lima · Appointment confirmed · yesterday 09:39" (the sender's name, or the address without its random token; the subject as the e-mail has it; when it came)."""
    now = (SNAPSHOT_CLOCK() if SNAPSHOT_CLOCK else datetime.datetime.now(datetime.timezone.utc)).astimezone()
    return " · ".join(part for part in (row["mail"]["who"], row["mail"]["subject"], mailtext.when_text(row.get("received"), now, cfg)) if part)


def render(out: dict, cfg: dict, limit: int = SHOWN_MAX, phone: bool = False, names=None) -> str:
    """The reply for a phone (`phone`) or a terminal: one heading for each source, then `n. line` for the first items. `names` ({source id: plain name}, runtime/source_names.py) is what a phone
    calls each source and what it says of one it could not read; without it a phone gets the names of `_names` (BL5D)."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    names = {**_names(out["sources"], cfg), **(names or {})} if phone else {}
    lines = []
    span = out.get("range")
    filt = out.get("filter")
    if phone and span and any(e["type"] == "calendar" for e in out["sources"]):
        lines.append(t("NW_ITEMS_RANGE_HEAD", label=_range_words(span, cfg)[0]))
    if phone and any(e["type"] == "calendar" for e in out["sources"]) and _filter_pieces("calendar", filt, cfg):      # CB-1: the words a calendar list was narrowed by
        lines.append(t("NW_ITEMS_MATCH_HEAD_CAL", filter=_filter_pieces("calendar", filt, cfg)))
    if phone and any(e["type"] == "mail" for e in out["sources"]) and _filter_pieces("mail", filt, cfg, span):      # CB-1: a mail list that was narrowed names how, in the person's words
        lines.append(t("NW_ITEMS_MATCH_HEAD", filter=_filter_pieces("mail", filt, cfg, span)))
    for entry in out["sources"]:
        if entry.get("unread_unknown"):      # CB-1: a box whose messages carry no flag lists nothing for an unread filter, and says why: the state is never guessed
            lines.append(t("NW_ITEMS_UNREAD_UNKNOWN", name=names[entry["source"]] if phone else entry["source"]))
            continue
        if phone and not entry["items"]:      # S15c: a source with nothing in its window is one sentence, not a bare heading
            lines.append(_empty_sentence(entry, cfg, span, filt))
            continue
        if phone:
            checked = entry.get("checked_at")
            lines.append(t("NW_ITEMS_HEAD_CHECKED" if checked else "NW_ITEMS_HEAD_PHONE", name=names[entry["source"]], when=_read_when(checked or entry["read_at"], cfg)))
        else:
            lines.append(t("NW_ITEMS_HEAD", source=entry["source"], read_at=entry["read_at"][:16].replace("T", " ")))
        for i in entry["items"][:limit]:
            mark = (t("NW_ITEMS_UNREAD_MARK") + " ") if phone and entry["type"] == "mail" and i.get("unread") is True else ""      # CB-2: a closed mark before an unread message
            lines.append(f"{i['n']}. " + mark + (_phone_event(i, cfg) if phone and entry["type"] == "calendar" else _phone_mail(i, cfg) if phone and "mail" in i else i["line"]))
            if i.get("preview"):
                lines.append(t("NW_ITEMS_PREVIEW", text=i["preview"]))
        if len(entry["items"]) > limit:
            lines.append(t("NW_ITEMS_MORE", n=len(entry["items"]) - limit))
    for entry in out["refused"]:
        lines.append(t("NW_ITEMS_REFUSED_PHONE", name=names.get(entry["source"], entry["source"])) if phone else f"{entry['source']}: {entry['why']}")
    if out.get("match_empty"):      # CB-1: a `match` with no content word filtered nothing: this is the whole list, said once
        lines.append(t("NW_ITEMS_MATCH_EMPTY"))
    if sum(e.get("nodate", 0) for e in out["sources"]):      # CB-1: messages with no time in the index are left out of a day filter, counted and said once
        lines.append(t("NW_ITEMS_MATCH_NODATE", n=sum(e.get("nodate", 0) for e in out["sources"])))
    old = sorted(e.get("checked_at") or e["read_at"] for e in out["sources"] if e.get("old"))
    moment = _local(old[0]) if old else None
    if moment is not None:      # one note for the whole list: the time of the oldest snapshot whose new read failed, in the machine's zone as the snapshots are
        lines.append(t("NW_ITEMS_OLD", time=moment.strftime("%H:%M")))
    return "\n".join(lines) or t("NW_ITEMS_NONE")


def reply(project: str, ctx: dict, out: dict, channel) -> str:
    """The reply of the natural request for the items: `render`, or, when there was nothing of the asked kind (or account) to list, what to add and where."""
    missing = out.get("missing")
    if not missing:
        phone = channel == ops_actor.MESSAGING
        return render(out, ctx["cfg"], phone=phone, names={i: e["name"] for i, e in source_names.catalog(ctx).items()} if phone else None)
    cfg, kind, account = ctx["cfg"], missing["kind"], missing["account"]
    tag = "MAIL" if kind == "mail" else "CAL"
    if channel == ops_actor.MESSAGING:      # a phone: what and where, never a command or a path (limit L62)
        return phrases.phone(f"NW_ITEMS_ADD_{tag}" + ("_ACCOUNT" if account else ""), cfg, service=LABEL[kind].get(account, ""))
    configured = [a for a in ACCOUNTS if isinstance(((cfg.get("accounts") or {}).get(a)), dict)] or list(ACCOUNTS)
    lines = [f"{LABEL[kind][a]}: " + core._command(COMMAND[kind], project, source_id=EXAMPLES[kind][a][0], origin=EXAMPLES[kind][a][1])
             for a in ([account] if account else configured)]
    return phrases.text(f"NW_ITEMS_CMD_{tag}" + ("_ACCOUNT" if account else ""), cfg, service=LABEL[kind].get(account, ""), commands="\n".join(lines))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
