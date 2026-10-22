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
exact `source-mail` / `source-calendar` command with an example origin for each configured account. A listing unchanged since the last read makes no new version, so a list asked again
after FRESH_S reads the provider again; that is the price of a list that is never silently old.

On a phone (`reply`, channel messaging) the list is written for a person and not for a program: each source has a plain name ("Google calendar", "Gmail inbox") and not its id, the time it was read is in the
machine's zone ("read at 10:31", with the day when it is not today), each event is written with its weekday and date ("Thu 22/10 14:00–15:00 · haircut") in the project's language, the
organizer is left out when it is the person and said in words otherwise, and no internal word of the snapshot's text shows. The numbers are the snapshot's own, as before (the numbered forms and
runtime/event_lookup.py read them). The terminal and the page keep the source id and the line as the snapshot prints it.

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
import ops_actor
import ops_core as core
import phrases
import snapshot_text
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
LABEL = {"mail": {"google": "Gmail", "microsoft": "Outlook"}, "calendar": {"google": "Google", "microsoft": "Outlook"}}
EXAMPLES = {"mail": {"google": ("mail-gmail", "gmail:box=inbox;days=7;max=50"), "microsoft": ("mail-outlook", "outlook:box=inbox;days=7;max=50")},
            "calendar": {"google": ("calendar-google", "google:calendar=primary;past=0;ahead=14"), "microsoft": ("calendar-outlook", "outlook:calendar=default;past=0;ahead=14")}}
COMMAND = {"mail": "source-mail", "calendar": "source-calendar"}
SNAPSHOT_CLOCK = None          # the clock the age of a snapshot is read against (None: the real one); a test replaces it


def _event_lines(ctx: dict, source_id: str, version) -> dict:
    """{n: (the line of the event as the snapshot prints it, the day it is listed under as YYYY-MM-DD or None)} of the version `read_index` read the index of: the text is read only when the newest version is still that one
    and its hash is the one the store records, so that the number and the line always come from the same snapshot (else nothing: the lines are blank)."""
    latest = sources._stored(ctx, "source_latest", source_id)
    if latest is None or latest["version"] != version:
        return {}
    with sources.Folder(ctx["cfg"], None) as folder:
        raw = folder.read([source_id, str(version), latest["converted_name"]], sources.CONVERTED_CAP)
    if hashlib.sha256(raw).hexdigest() != latest["converted_sha256"]:
        return {}
    text = raw.decode("utf-8", errors="replace")
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


def _account_of(row: dict):
    """The account ("google" | "microsoft") a mail or calendar source belongs to, from the implementation its origin names; None when the origin is not one this runtime reads."""
    table = importlib.import_module("mail_refs").ACCOUNT_OF if row["type"] == "mail" else importlib.import_module("ops_natural_calendar").CAL_ACCOUNT
    try:
        return table.get(sources_mail.origin_of(row["type"], row["origin"])["implementation"])
    except sources.SourcesError:
        return None


def _refresh_failed(project: str, ctx: dict, source_id: str) -> bool:
    """Read a source again once when its newest snapshot is older than FRESH_S (or there is none, or its time cannot be trusted). True when that read failed (the failure is dropped:
    it can hold a provider's words); False when nothing was needed or it worked. The provider is reached only by `ops_sources.source_refresh`, one source after the other: they share the store."""
    latest = sources._stored(ctx, "source_latest", source_id)
    age = sources.snapshot_age(latest["imported_at"], SNAPSHOT_CLOCK) if latest else None
    if age is not None and age <= FRESH_S:
        return False
    try:
        importlib.import_module("ops_sources").source_refresh(project, source_id)
    except Exception:      # noqa: BLE001 - the fault can hold a provider's words; the list is the old snapshot and a note
        return True
    return False


def items(project: str, kind: str | None = None, source: str | None = None, channel: str | None = None, sender: str | None = None, account: str | None = None) -> dict:
    ctx = core.context(project)
    ops_actor.guard(ctx, "items", channel, sender)
    if kind is not None and kind not in KINDS:
        raise core.OpsError("the kind of item is mail or calendar", 2)
    if account is not None and account not in ACCOUNTS:
        raise core.OpsError("the account is google or microsoft", 2)
    if not item_refs.may_read(ctx, channel, sender):
        raise core.OpsError(phrases.en("NW_REF_NOT_READABLE"), 1)
    found, refused = [], []
    for row in sources.list_catalog(ctx, hashes=False):
        if row["type"] not in KINDS or (kind and row["type"] != kind) or (source and row["id"] != source):
            continue
        if account and _account_of(row) != account:
            continue
        old = channel == ops_actor.MESSAGING and _refresh_failed(project, ctx, row["id"])
        try:
            snapshot = item_refs.read_index(ctx, row["id"], channel=channel, sender=sender, kinds=(row["type"],), clock=SNAPSHOT_CLOCK)
        except item_refs.ItemRefError as e:
            refused.append({"source": row["id"], "why": str(e)})
            continue
        if row["type"] == "mail":
            rows = [{"n": e["n"], "line": snapshot_text.one_line(f"{e.get('from_address') or '?'} · {e.get('subject') or ''}", LINE_MAX)} for e in snapshot["entries"][:ITEMS_MAX]]
        else:
            lines = _event_lines(ctx, row["id"], snapshot["version"])
            rows = [{"n": e["n"], "line": lines.get(e["n"], ("", None))[0], "day": lines.get(e["n"], ("", None))[1]} for e in snapshot["entries"][:ITEMS_MAX]]
        found.append({"source": row["id"], "type": row["type"], "account": _account_of(row), "read_at": snapshot["read_at"], "items": rows, **({"old": True} if old else {})})
    out = {"sources": found, "refused": refused}
    if kind and not found and not refused:
        out["missing"] = {"kind": kind, "account": account}
    return out


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
        named[entry["source"]] = phrases.text("NW_ITEMS_NAME_MAIL" if entry["type"] == "mail" else "NW_ITEMS_NAME_CAL", cfg, service=label) if label else entry["source"]
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


def render(out: dict, cfg: dict, limit: int = SHOWN_MAX, phone: bool = False) -> str:
    """The reply for a phone (`phone`) or a terminal: one heading for each source, then `n. line` for the first items."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    names = _names(out["sources"], cfg) if phone else {}
    lines = []
    for entry in out["sources"]:
        if phone:
            lines.append(t("NW_ITEMS_HEAD_PHONE", name=names[entry["source"]], when=_read_when(entry["read_at"], cfg)))
        else:
            lines.append(t("NW_ITEMS_HEAD", source=entry["source"], read_at=entry["read_at"][:16].replace("T", " ")))
        lines += [f"{i['n']}. {_phone_event(i, cfg) if phone and entry['type'] == 'calendar' else i['line']}" for i in entry["items"][:limit]]
        if len(entry["items"]) > limit:
            lines.append(t("NW_ITEMS_MORE", n=len(entry["items"]) - limit))
    for entry in out["refused"]:
        lines.append(f"{entry['source']}: {entry['why']}")
    old = sorted(e["read_at"] for e in out["sources"] if e.get("old"))
    moment = _local(old[0]) if old else None
    if moment is not None:      # one note for the whole list: the time of the oldest snapshot whose new read failed, in the machine's zone as the snapshots are
        lines.append(t("NW_ITEMS_OLD", time=moment.strftime("%H:%M")))
    return "\n".join(lines) or t("NW_ITEMS_NONE")


def reply(project: str, ctx: dict, out: dict, channel) -> str:
    """The reply of the natural request for the items: `render`, or, when there was nothing of the asked kind (or account) to list, what to add and where."""
    missing = out.get("missing")
    if not missing:
        return render(out, ctx["cfg"], phone=channel == ops_actor.MESSAGING)
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
