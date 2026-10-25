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
import snapshot_text
import source_names
import sources
import sources_mail

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


def items_args(said, now, previous=None) -> dict:
    """The arguments a line gives `items`, whole, so that a plan's hash binds them (BL5B): `kind` ("calendar" or "mail"), `account`, the range (`first`, `last`) and `count`, each read from
    the line as `_line_args` reads it. `previous` is the arguments of the plan this line corrects (the sender's own live plan, never a third party's): the kind the new line names wins
    ("no, the e-mails"), else the old kind is kept, else the line alone decides (`items_kind`); the account and the range the old plan had are kept when the new line names none. A
    number of messages (`count`) is only the line's own. Pure: nothing is read."""
    found = _line_args(said, now)
    noun = importlib.import_module("natural_writes").items_noun(said)
    old = previous if isinstance(previous, dict) else {}
    kind = noun or old.get("kind") or importlib.import_module("natural_writes").items_kind(said)
    out = {"kind": kind, **found}
    if "account" not in out and old.get("account"):
        out["account"] = old["account"]
    if "first" not in out and old.get("first") and old.get("last"):
        out.update(first=old["first"], last=old["last"])
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


def _refresh_failed(project: str, ctx: dict, source_id: str) -> bool:
    """Read a source again once when the later of its newest snapshot and its last check is older than FRESH_S (or there is none, or its time cannot be trusted). True when that read failed
    (one line to stderr with a word of CLOSED_WHY; the provider's words are dropped); False when nothing was needed or it worked, and then the check is remembered. The provider is reached
    only by `ops_sources.source_refresh`, one source after the other: they share the store."""
    key = (ctx["cfg"]["project"], source_id)
    latest = sources._stored(ctx, "source_latest", source_id)
    last = max([t for t in (_local(latest["imported_at"]) if latest else None, _CHECKED.get(key)) if t is not None], default=None)
    age = sources.snapshot_age(last.isoformat(), SNAPSHOT_CLOCK) if last else None
    if age is not None and age <= FRESH_S and key not in _DIRTY:
        return False
    try:
        importlib.import_module("ops_sources").source_refresh(project, source_id)
    except Exception as e:      # noqa: BLE001 - the fault can hold a provider's words; the list is the old snapshot and a note
        why = getattr(e, "why", None)
        print(f"items: refresh of {source_id} failed ({why if why in CLOSED_WHY else 'error'})", file=sys.stderr)
        return True
    _CHECKED[key] = _now()
    _DIRTY.discard(key)
    return False


def items(project: str, kind: str | None = None, source: str | None = None, channel: str | None = None, sender: str | None = None, account: str | None = None, count: int | None = None,
          first: str | None = None, last: str | None = None) -> dict:
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
    if not item_refs.may_read(ctx, channel, sender):
        raise core.OpsError(phrases.en("NW_REF_NOT_READABLE"), 1)
    phone = channel == ops_actor.MESSAGING
    found, refused, matched = [], [], 0
    for row in sources.list_catalog(ctx, hashes=False):
        if row["type"] not in KINDS or (kind and row["type"] != kind) or (source and row["id"] != source):
            continue
        if account and _account_of(row) != account:
            continue
        matched += 1
        old = phone and _refresh_failed(project, ctx, row["id"])
        try:
            snapshot = item_refs.read_index(ctx, row["id"], channel=channel, sender=sender, kinds=(row["type"],), clock=SNAPSHOT_CLOCK)
        except item_refs.ItemRefError as e:
            refused.append({"source": row["id"], "why": str(e)})
            continue
        if row["type"] == "mail":
            rows = [{"n": e["n"], "line": snapshot_text.one_line(f"{e.get('from_address') or '?'} · {e.get('subject') or ''}", LINE_MAX)} for e in snapshot["entries"][:ITEMS_MAX]]
            if phone or count:      # S15b: when it came and, for a phone, who and what, from the text the index was read with
                text = _text_of(ctx, row["id"], snapshot["version"])
                parsed = mailtext.blocks(text) if text is not None else {}
                for r, e in zip(rows, snapshot["entries"]):
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
        checked = _CHECKED.get((ctx["cfg"]["project"], row["id"])) if phone else None
        later = checked is not None and (_local(snapshot["read_at"]) or checked) < checked
        found.append({"source": row["id"], "type": row["type"], "account": _account_of(row), "read_at": snapshot["read_at"], "items": rows,
                      **({"old": True} if old else {}), **({"checked_at": checked.isoformat()} if later else {}),
                      **({"window": _window(ctx, row, snapshot)} if not rows else {})})
    if count:
        _newest(found, count, phone)
    out = {"sources": found, "refused": refused, **({"range": {"first": first, "last": last}} if span else {})}
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


def _empty_sentence(entry: dict, cfg: dict, span=None) -> str:
    """The one sentence for a registered source with nothing in its window: "No e-mail in the Outlook inbox in the last 7 days (checked at 16:59)." / "No event in the Google calendar between
    16/10 and 30/10 (...)." / "No event in the Google calendar tomorrow (...)."."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    label = LABEL[entry["type"]].get(entry.get("account"))
    checked = entry.get("checked_at")
    state = t("NW_ITEMS_STATE_CHECKED" if checked else "NW_ITEMS_STATE_READ", when=_read_when(checked or entry["read_at"], cfg))
    name = t("NW_ITEMS_NAMEIN_MAIL" if entry["type"] == "mail" else "NW_ITEMS_NAMEIN_CAL", service=label) if label else entry["source"]
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
    if phone and span and any(e["type"] == "calendar" for e in out["sources"]):
        lines.append(t("NW_ITEMS_RANGE_HEAD", label=_range_words(span, cfg)[0]))
    for entry in out["sources"]:
        if phone and not entry["items"]:      # S15c: a source with nothing in its window is one sentence, not a bare heading
            lines.append(_empty_sentence(entry, cfg, span if entry["type"] == "calendar" else None))
            continue
        if phone:
            checked = entry.get("checked_at")
            lines.append(t("NW_ITEMS_HEAD_CHECKED" if checked else "NW_ITEMS_HEAD_PHONE", name=names[entry["source"]], when=_read_when(checked or entry["read_at"], cfg)))
        else:
            lines.append(t("NW_ITEMS_HEAD", source=entry["source"], read_at=entry["read_at"][:16].replace("T", " ")))
        for i in entry["items"][:limit]:
            lines.append(f"{i['n']}. " + (_phone_event(i, cfg) if phone and entry["type"] == "calendar" else _phone_mail(i, cfg) if phone and "mail" in i else i["line"]))
            if i.get("preview"):
                lines.append(t("NW_ITEMS_PREVIEW", text=i["preview"]))
        if len(entry["items"]) > limit:
            lines.append(t("NW_ITEMS_MORE", n=len(entry["items"]) - limit))
    for entry in out["refused"]:
        lines.append(t("NW_ITEMS_REFUSED_PHONE", name=names.get(entry["source"], entry["source"])) if phone else f"{entry['source']}: {entry['why']}")
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
