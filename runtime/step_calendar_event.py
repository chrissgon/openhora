#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `calendar-event`: create, change or remove an event of the person's own calendar, as an external effect the person approves (package W1).
The kind prepares; it never writes. Two steps, as in a send:

  prepare   checks the arguments, takes the account's address and the calendar from the project's `accounts` (a calendar the project does not list is refused: limit
            L55), and, for a change or a removal, names the event (a reference: `created:<decision>`, or `<source>#<n>` once the index of the snapshots is in the
            checkout), reads it from the calendar through the read-only calendar service and refuses an event that is not the person's alone (organized by someone
            else, with another attendee, recurring, or gone). Then it asks the writer for a dry run of the request (nothing is sent, no credential is read, no
            connection is opened), checks that what the writer would send is what the arguments say (the method, no attendee, nobody told), and writes the effect
            document (runtime/calendar_document.py) through the effect-files service to <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a 0700 folder.
  calendar  the gate (runtime/steps.py, Gate): it has no executor. It opens an `effect` decision whose hash is the hash of the effect document and whose body is the
            card: the account, the calendar, the event (for a change, each part as it was and as it will be), and the version of the event it is based on; the task
            waits. The person approves the hash in the terminal or on the page (a messaging app only when the project's policy grants it the word `calendar`), and
            then runtime/ops_step_effects.py calls the effect module (runtime/effect_calendar.py), which reads the event again, writes once, and tells nobody. An event
            changed meanwhile answers the decision, writes nothing and sends the task back to `prepare`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will be asked about):

  {"account": "google" | "microsoft", "operation": "create" | "change" | "cancel" | "cancel-series" | "cancel-occurrence"
   [, "calendar": "<a name of accounts.<a>.calendars>" (the first one when absent)]
   create:  "title", "start" ["end", "location", "reminder_minutes", "notes", "repeat": "daily" | "weekly"]
   change:  "event" and one or more of "title", "start", "end", "location", "reminder_minutes", "notes"
   cancel:  "event"
   cancel-series:      "event" (the whole daily or weekly series the event belongs to)
   cancel-occurrence:  "event" and "occurrence" (the local day, YYYY-MM-DD: one occurrence of the series the event belongs to)}

A series (CB-7). `repeat` makes a daily series, or a weekly one on the weekday the start falls on, with no end, written in this machine's zone (a named one); a series is of timed
events. The two cancels of a series are the only way a series is touched: `cancel-series` removes the whole of it and `cancel-occurrence` only the one occurrence of the day given, found
by code in the provider's own list of the series' instances (never from a time or an id a person or a model wrote). The preparation reads the series' master, refuses a series that is not a
plain daily or weekly one, that the person does not organize alone, or whose version moved, and the occurrence's own version; a plain `change` or `cancel` of any event of a series is
still refused here (`_eligible`), so that nothing else can move or remove a series.

`start` and `end` are `YYYY-MM-DDTHH:MM` (this machine's zone) or `YYYY-MM-DD` for an all-day event; the end defaults to an hour after the start (the same day for an
all-day event). Nobody is invited and nobody is told: v1 has no attendee, and a meeting with other people is refused; a series is created, and cancelled whole or by one occurrence, and
never changed. The account is never an argument of the effect's target: the calendar is the project's name for it.

Limit L30, in the structure of this file: it imports no module that calls a provider. What it needs of the accounts, of the calendar and of the data folder it asks
of `ctx.services` (runtime/ops_step_seams.py), where `calendar_read` has an event read and a dry run and no way to write, and `effect_files` writes and reads the
effect document and does not execute it. The only code that writes is runtime/effect_calendar.py `execute`, which this file cannot reach.

The kind is not `unattended`: a calendar change starts when the person starts it and ends at the person's approval. It writes no file of the project (its footprint is
empty).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import calendar_document  # noqa: E402
import steps  # noqa: E402

WEEKDAY_OF = calendar_document.BYDAY      # datetime.weekday() order, to name the weekday of a weekly series

KEYS = ("account", "operation", "calendar", "title", "start", "end", "location", "reminder_minutes", "notes", "event", "channel", "sender", "repeat", "occurrence")
PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")
REPEATS = ("daily", "weekly")      # the two repetitions a new event may have (CB-7)
CHANNELS = ("terminal", "page", "messaging")      # who asked, for the right to read a snapshot (runtime/item_refs.py): written by the operation, never by a person's words
SENDER = re.compile(r"[a-z][a-z0-9-]{0,31}:[A-Za-z0-9_.@+=-]{1,128}")
CONTENT = ("title", "start", "end", "location", "reminder_minutes", "notes")
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed", "refused": "refused"}
GATE_STEP = "calendar"
NAME = re.compile(r"[a-z0-9-]{1,32}")
REFERENCE = re.compile(r"(?:[a-z0-9][a-z0-9_-]{0,39}#[1-9][0-9]{0,4}|created:[1-9][0-9]{0,9})")
METHOD = {"google": {"create": "POST", "change": "PATCH", "cancel": "DELETE", "cancel-series": "DELETE", "cancel-occurrence": "PATCH"},
          "microsoft": {"create": "POST", "change": "PATCH", "cancel": "DELETE", "cancel-series": "POST", "cancel-occurrence": "POST"}}      # the one request each writer sends for an operation


def _bad(field: str, hint: str = ""):
    return steps.StepFailure("bad_args", field, "", hint[:200])


def _checked(call, *a, field: str):
    """A check of the document module whose refusal is a bad argument: the sentence names the rule, never the content."""
    try:
        return call(*a)
    except Exception as e:      # an EffectError of the document, with its `reason`
        raise _bad(field, str(getattr(e, "reason", ""))) from None


def check(args) -> dict:
    """The arguments of a calendar-event, checked and normalised."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise _bad("args")
    if args.get("account") not in calendar_document.ACCOUNTS:
        raise _bad("account", "give google or microsoft")
    operation = args.get("operation")
    if operation not in calendar_document.OPERATIONS:
        raise _bad("operation", "give create, change or cancel")
    out = {"account": args["account"], "operation": operation}
    if args.get("calendar") is not None:
        if not isinstance(args["calendar"], str) or not NAME.fullmatch(args["calendar"]):
            raise _bad("calendar", "a calendar is named as the project's accounts name it: lowercase letters, digits and hyphens")
        out["calendar"] = args["calendar"]
    content = [name for name in CONTENT if args.get(name) is not None]
    if operation == "create":
        if args.get("event") is not None:
            raise _bad("event", "a new event names no earlier event")
        if "title" not in content or "start" not in content:
            raise _bad("title" if "title" not in content else "start", "a new event needs a title and a start")
    if args.get("repeat") is not None:
        if operation != "create" or args["repeat"] not in REPEATS:
            raise _bad("repeat", "a new event may repeat daily or weekly; nothing else repeats")
        if not isinstance(args.get("start"), str) or not calendar_document.WALL.fullmatch(args["start"]):
            raise _bad("repeat", "a series is made of timed events: give the start as a day and a time")
    if (args.get("occurrence") is not None) != (operation == "cancel-occurrence"):
        raise _bad("occurrence", "cancel-occurrence takes the day of the occurrence, and nothing else does")
    if args.get("occurrence") is not None:
        _checked(calendar_document.parse_when, args["occurrence"], "the day of the occurrence", field="occurrence")
        if not calendar_document.DAY.fullmatch(args["occurrence"]):
            raise _bad("occurrence", "the occurrence is a day: YYYY-MM-DD")
        out["occurrence"] = args["occurrence"]
    if args.get("channel") is not None:      # who asked: a reference into a snapshot is usable only by a caller who may read it (runtime/item_refs.py)
        if args["channel"] not in CHANNELS:
            raise _bad("channel", "the channel is terminal, page or messaging")
        out["channel"] = args["channel"]
    if args.get("sender") is not None:
        if not isinstance(args["sender"], str) or not SENDER.fullmatch(args["sender"]) or args.get("channel") != "messaging":
            raise _bad("sender", "a sender is <platform>:<id> and goes with the channel messaging")
        out["sender"] = args["sender"]
    if operation != "create":
        if "channel" not in out:      # who asks is never left to a default: a missing channel would read as full rights on a snapshot
            raise _bad("channel", "say who asks: terminal, page or messaging")
        if not isinstance(args.get("event"), str) or not REFERENCE.fullmatch(args["event"]):
            raise _bad("event", "name the event as <source>#<n> (the n-th item of a calendar snapshot) or created:<decision>")
        out["event"] = args["event"]
        if operation in calendar_document.CANCELS and content:
            raise _bad(content[0], "removing an event takes no other argument")
        if operation == "change" and not content:
            raise _bad("args", "give at least one part to change")
    if args.get("repeat") is not None:
        out["repeat"] = args["repeat"]
    for name in content:
        value = args[name]
        if name == "title":
            _checked(calendar_document.line, value, "the title", calendar_document.TITLE_MAX, True, field=name)
        elif name == "location":
            _checked(calendar_document.line, value, "the location", calendar_document.LOCATION_MAX, field=name)
        elif name == "notes":
            if _checked(calendar_document.notes_text, value, field=name) != value:
                raise _bad(name, "the notes use \\n for a line end")
        elif name == "reminder_minutes":
            _checked(calendar_document.reminder, value, field=name)
        else:
            _checked(calendar_document.parse_when, value, name, field=name)
        out[name] = value
    return out


def _service(ctx: steps.Context, name: str):
    found = ctx.services.get(name)
    if found is None:
        raise steps.StepFailure("not_configured", name)
    return found


def _asked(call, *args, field="calendar"):
    """A service call whose failure is a closed code of the step; `field` is the argument the sentence is about."""
    try:
        return call(*args)
    except steps.StepFailure:
        raise
    except Exception as e:      # the services raise errors that carry a `code`; anything else is a provider failure
        code = SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed")
        raise steps.StepFailure(code, field, "writer", str(getattr(e, "reason", ""))[:200] if code != "provider_failed" else "") from None


def _eligible(event: dict, series: bool = False) -> None:
    """The event is the person's alone: organized by them, no other attendee, not a series. Anything else is a meeting or a series, and v1 changes neither
    (changing a meeting tells other people; changing a series touches every occurrence). `series` is True only for the cancel of a whole series and the cancel of one occurrence, which
    read the series and check it in `_series_target`: a plain change or removal of any event of a series is refused here, as it always was, and so is the change of a series' master."""
    if event.get("organizer_self") is not True:
        raise steps.StepFailure("not_eligible", "event", "writer", "this event is organized by someone else: only an event you organize can be changed here")
    if event.get("attendees_other"):
        raise steps.StepFailure("not_eligible", "event", "writer", "this event has other attendees: changing it would tell them, and a meeting is not changed here")
    if not series and (event.get("recurring") or event.get("series_id")):
        raise steps.StepFailure("not_eligible", "event", "writer", "this event repeats: a series is not changed here; to remove it, cancel the whole series (--series) or one occurrence of it (--occurrence YYYY-MM-DD)")


def _keys(found):
    """Every key of every object inside `found` (a request as the writer's dry run prints it), so that the words of a title are never mistaken for a key."""
    if isinstance(found, dict):
        for key, value in found.items():
            yield key
            yield from _keys(value)
    elif isinstance(found, list):
        for value in found:
            yield from _keys(value)


def _same(doc: dict, would: dict) -> bool:
    """Whether what the writer's dry run says it would send is what the document says: the method of the operation, the event named in the path, nobody told (the
    query of a Google request says so, and no object of the request has an `attendees` key), and the document's own key in the request of a write."""
    body, query = would.get("body"), would.get("query") or {}
    operation, account = doc["operation"], doc["account"]
    keyless = operation in ("cancel", "cancel-series") or (operation == "cancel-occurrence" and account == "microsoft")      # a request with no body (or Graph's empty cancel) carries no key
    series_ok = operation not in calendar_document.SERIES_CANCELS or (would.get("verb") == calendar_document.verb_of(doc) and would.get("guard") == _guard(doc)
                                                                      and _names(doc, would.get("path")))
    return (would.get("method") == METHOD[account][operation] and isinstance(would.get("path"), str) and (operation == "create" or "/events/" in would["path"])
            and "attendees" not in set(_keys(would)) and (account != "google" or query.get("sendUpdates") == "none") and series_ok
            and (keyless or (isinstance(body, dict) and doc["idempotency_key"] in repr(body))))


def _guard(doc: dict) -> dict:
    """The `guard` a writer's dry run prints for a series cancel (the flags that decide which checks run before the request, part of the hash the person approves): what the document says."""
    series = doc["series"]
    if doc["operation"] == "cancel-occurrence":
        return {"series": series["id"], "expect_start": series["start"]}
    return {"series": True} if doc["account"] == "google" else {}


def _names(doc: dict, path) -> bool:
    """Whether the path of the request names the event the document names (the master's id for the whole series, the instance's for one occurrence) and, on Graph, ends in the cancel action."""
    if not isinstance(path, str):
        return False
    tail = path.rpartition("/events/")[2]
    if doc["account"] == "microsoft":
        if not tail.endswith("/cancel"):
            return False
        tail = tail[:-len("/cancel")]
    return PERCENT.sub(lambda found: chr(int(found.group(1), 16)), tail) == doc["event_id"]      # an id is ASCII (EVENT_ID): the writers quote `=` and `+` in a path


def _recurrence(repeat: str, when: dict, zone: str) -> dict:
    """The repetition of a new event, from the closed word the operation took ("daily" or "weekly") and the start the document will have: weekly is on the weekday of that start in the
    machine's zone. A series is made of timed events written in a NAMED zone (both writers expand it there): an all-day event, or a zone that is only an offset, is refused."""
    if when["all_day"]:
        raise steps.StepFailure("not_eligible", "repeat", "", "a series is made of timed events: an all-day event does not repeat here")
    if not calendar_document.OUTLOOK_ZONE.fullmatch(zone):
        raise steps.StepFailure("not_eligible", "repeat", "", "this machine's time zone has no name (it is only an offset), and a series is written in a named zone: set the zone and start again")
    if repeat == "daily":
        return {"freq": "daily"}
    return {"freq": "weekly", "byday": WEEKDAY_OF[calendar_document.parse_when(when["start"], "the start")[0].weekday()]}


def _read_event(reader, account: str, calendar_id: str, event_id: str) -> dict:
    """The event the writer reads, or the step's refusal: gone (removed, or on another calendar)."""
    read = _asked(reader.event_get, account, calendar_id, event_id)
    raw = read.get("event") if isinstance(read, dict) and read.get("found") is True else None
    if raw is None:
        raise steps.StepFailure("event_gone", "event", "writer", "that event is not on this calendar any more (it was removed, or it is on another calendar)")
    if not isinstance(raw.get("etag"), str) or not isinstance(raw.get("id"), str):
        raise steps.StepFailure("provider_failed", "event", "writer", "the calendar gave no version of the event, so nothing is changed")
    return raw


def _starts_on(start, day) -> bool:
    """Whether the instant `start` (as the writer printed it) falls on the local day `day`; False for anything that is not an instant."""
    try:
        return calendar_document.parse_instant(start).astimezone().date() == day
    except Exception:      # noqa: BLE001 - an EffectError of the document: not an instant, not that day
        return False


def _occurrence(ctx: steps.Context, reader, account: str, calendar_id: str, master_id: str, day: str) -> dict:
    """The one instance of the series that is on the local day `day` (YYYY-MM-DD, read by code from the person's words), from the provider's own list of the series' instances: none, more
    than one and one that has started are each a refusal. The day is the only thing that came from a line; the instance, its id and its start come from the provider."""
    asked = calendar_document.parse_when(day, "the day of the occurrence")[0]
    first, last = calendar_document.day_window(asked)
    found = _asked(reader.event_instances, account, calendar_id, master_id, first, last, field="occurrence")
    listed = found.get("instances") if isinstance(found, dict) else None
    if not isinstance(listed, list):
        raise steps.StepFailure("provider_failed", "occurrence", "writer", "the calendar's answer about the series is not one this code understands")
    live = [i for i in listed if isinstance(i, dict) and i.get("status") != "cancelled" and _starts_on(i.get("start"), asked)]      # a window holds what overlaps it (Google's timeMin filters on the END): the day an instance STARTS on is the day asked
    if not live:
        raise steps.StepFailure("no_occurrence", "occurrence", "", "the series has no occurrence on that day")
    if len(live) > 1:
        raise steps.StepFailure("which_day", "occurrence", "", "the series has more than one occurrence on that day: name the time")
    one = live[0]
    if not isinstance(one.get("id"), str) or not isinstance(one.get("start"), str):
        raise steps.StepFailure("provider_failed", "occurrence", "writer", "the calendar's answer about the series is not one this code understands")
    if calendar_document.parse_instant(one["start"]) <= calendar_document.parse_instant(calendar_document.utc_text(ctx.now())):
        raise steps.StepFailure("occurrence_past", "occurrence", "", "that occurrence has already started: nothing is cancelled")
    return one


def _series_target(ctx: steps.Context, reader, account: str, calendar_id: str, operation: str, args: dict, event_id: str) -> tuple:
    """(the event the document is about as the provider printed it, the document's `series`) for the cancel of a whole series or of one occurrence (CB-7). The event the person named is read;
    it must belong to a series (`series_id`), the series' master is read and must be a plain daily or weekly one the person organizes alone (a cancel would tell every attendee); for one
    occurrence the instance of the day is found in the provider's list and read again for its own version, and must belong to that series and not have started."""
    named = _read_event(reader, account, calendar_id, event_id)
    sid = named.get("series_id")
    if not isinstance(sid, str) or not sid:
        raise steps.StepFailure("not_eligible", "event", "writer", "this event is not part of a series: cancel it as one event")
    master = named if sid == named["id"] else _read_event(reader, account, calendar_id, sid)
    rule = master.get("series_rule")
    if master["id"] != sid or master.get("series_id") != sid or not isinstance(rule, str) or not calendar_document.RULE_WORD.fullmatch(rule):
        raise steps.StepFailure("not_eligible", "event", "writer", "this series is not a plain daily or weekly one (it has an end, a count, an interval or several days): only the calendar app cancels it")
    _eligible(master, series=True)
    if master.get("all_day") is not False:
        raise steps.StepFailure("not_eligible", "event", "writer", "a series of all-day events is not cancelled here")
    if operation == "cancel-series":
        return master, {"id": sid, "rule": rule, "start": None}
    one = _occurrence(ctx, reader, account, calendar_id, sid, args["occurrence"])
    target = _read_event(reader, account, calendar_id, one["id"])
    _eligible(target, series=True)
    if target.get("series_id") != sid or target.get("id") != one["id"] or target.get("all_day") is not False or not isinstance(target.get("start"), str) \
            or target.get("status") == "cancelled" or target["id"] == sid:
        raise steps.StepFailure("not_eligible", "event", "writer", "that occurrence is not one of this series, or it is cancelled already: nothing is cancelled")
    return target, {"id": sid, "rule": rule, "start": target["start"]}


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    reader, files = _service(ctx, "calendar_read"), _service(ctx, "effect_files")
    account, operation = args["account"], args["operation"]
    if not reader.enabled(account):
        raise steps.StepFailure("not_configured", "account", "", "list the account in docs/workbench/runtime.json (the key accounts) and accept the file")
    named = None
    if operation == "create":
        name = reader.calendar_name(account, args.get("calendar"))
    else:
        # The reference decides what the event is; the project's `accounts` decides where it may be written. Both must name the same account and the same
        # calendar, exactly (limit L55): a reference that names no account, or a calendar the project does not list, is refused.
        named = _asked(reader.event_ref, args["event"], args.get("channel"), args.get("sender"), field="reference")
        if named.get("account") != account:
            raise steps.StepFailure("not_eligible", "event", "", "this event is not on the account asked for, or the reference does not say which account it is on")
        name = args.get("calendar") if args.get("calendar") is not None else named.get("calendar")      # an event on a second calendar goes by the calendar it is on
        if name is None:
            raise steps.StepFailure("not_eligible", "event", "", "this event is on a calendar the project's accounts do not list: nothing is changed there")
    calendar_id, why = reader.target(account, name)
    if why:
        raise steps.StepFailure("target_refused", "calendar", "", why[:200])
    if named is not None and named.get("calendar_id") != calendar_id:
        raise steps.StepFailure("not_eligible", "event", "", "this event is not on the calendar asked for (name it with the calendar argument, or ask for the calendar it is on)")
    pieces = dict(task_id=ctx.task_id, account=account, address=reader.address(account), calendar=name, calendar_id=calendar_id, operation=operation,
                  zone=calendar_document.zone_name())
    try:
        if operation == "create":
            when = calendar_document.times(args["start"], args.get("end"))
            event = calendar_document.event_of(args["title"], args.get("location", ""), args.get("reminder_minutes"), args.get("notes", ""), when)
            pieces.update(event=event)
            if args.get("repeat"):
                pieces.update(recurrence=_recurrence(args["repeat"], when, pieces["zone"]))
        else:
            if operation in calendar_document.SERIES_CANCELS:
                raw, series = _series_target(ctx, reader, account, calendar_id, operation, args, named["event_id"])
                pieces.update(series=series)
            else:
                raw = _read_event(reader, account, calendar_id, named["event_id"])
                _eligible(raw)
            if args.get("reminder_minutes") is not None and raw.get("reminders_extra"):
                raise steps.StepFailure("not_eligible", "reminder_minutes", "writer", "this event has several reminders: change them in the calendar, here a reminder is one number of minutes")
            before = calendar_document.from_service(raw)
            if state.get("pinned_event") not in (None, raw["id"]):
                raise steps.StepFailure("not_eligible", "reference", "", "the reference now names another event than the card you were asked about: name the event again and start over")
            pieces.update(event_id=raw["id"], base_etag=raw["etag"], read_at=calendar_document.utc_text(ctx.now()), before=before, reference=named.get("reference"))
            if operation == "change":
                after = calendar_document.apply(before, **{k: args[k] for k in CONTENT if k in args})
                changed = calendar_document.changed_fields(before, after)
                if not changed:
                    raise steps.StepFailure("nothing_to_change", "args", "", "the event is already as asked")
                pieces.update(event=after, changed=changed)
        pieces.update(asker=args["sender"] if args.get("channel") == "messaging" and args.get("sender") else (args.get("channel") or "terminal"))
        draft = calendar_document.document(**pieces, dry_run_sha256="0" * 64)
    except steps.StepFailure:
        raise
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "args", "", str(getattr(e, "reason", ""))[:200]) from None
    shown = _asked(reader.dry_run, draft)
    would, digest = shown.get("would") if isinstance(shown, dict) else None, shown.get("would_sha256") if isinstance(shown, dict) else None
    if not isinstance(would, dict) or not isinstance(digest, str) or not calendar_document.SHA256.fullmatch(digest) or not _same(draft, would):
        raise steps.StepFailure("preview_mismatch", "writer", "writer", "the writer would send something other than the arguments say: nothing is asked about it")
    doc = calendar_document.document(**pieces, dry_run_sha256=digest)
    written = _asked(files.write, ctx.task_id, int(state.get("cycle", 0)), doc)
    if operation != "create":
        state["pinned_event"] = doc["event_id"]      # a start over after a stale prepares the same event, or refuses
    return {"effect_sha256": written, "operation": operation, "account": account, "calendar": name, "changed": len(doc["changed"])}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its card, its hash."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    calendar_document.check(doc)
    return {"title": calendar_document.title(doc), "body": calendar_document.body(doc, recorded), "payload_sha256": recorded,
            "payload": {"effect": calendar_document.summary(doc), "card": calendar_document.card_lines(doc, recorded)}}


KIND = steps.register(steps.Kind(
    name="calendar-event",
    order=("prepare", GATE_STEP),
    executors={"prepare": _prepare},
    gates={GATE_STEP: steps.Gate(word=calendar_document.WORD, open=_open, redo="prepare")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
