#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The calendar family of the natural writes, with the project (package NR-5a): what the pure reading of runtime/natural_writes_calendar.py leaves to the configuration and
the registered sources, in the fixed order of the questions (SPEC-NATURAL-WRITES 4): the account, the calendar, the event (and the calendar source it is numbered in), the
time, the title. Each step is code: an account is a service word of the line, the account of the reference, the one account that lists calendars, `accounts.default` or the
person's choice; a calendar is a name the account lists, folded, or the operation's default; an event is `<source>#<n>` with the number written in the line, resolved by the
operation with the caller's rights (a caller who may not read a snapshot is told so here and nothing of the calendar is named); a time is the time engine's single reading.

resolve(ctx, op, slots, channel, sender, said) -> {"args"} | {"ask"} | {"say"} (the interface of runtime/natural_writes.py).

Sibling of runtime/ops_natural_writes.py. Standard library only. Runs on Python 3.9: python3 runtime/ops_natural_calendar.py --help
"""
from __future__ import annotations

import importlib
import sys

import item_refs
import sources
import sources_mail

CAL_ACCOUNT = {"google": "google", "outlook": "microsoft"}      # the implementation named in a calendar source's origin -> the account it belongs to


def _w():
    return importlib.import_module("ops_natural_writes")


def calendar_sources(ctx: dict) -> list:
    """The registered calendar sources: [{"id", "account"}], in the registry's order."""
    out = []
    for row in sources.list_catalog(ctx, hashes=False):
        if row["type"] != "calendar":
            continue
        try:
            implementation = sources_mail.origin_of("calendar", row["origin"])["implementation"]
        except sources.SourcesError:
            continue
        out.append({"id": row["id"], "account": CAL_ACCOUNT.get(implementation)})
    return out


def _reference(ctx: dict, slots: dict, channel, sender):
    """("ok", "<source>#<n>", the source's account) or ("spec", the question or sentence). The right to read comes first: a caller who may not read a snapshot learns
    nothing of the calendar's sources."""
    w = _w()
    if "event" not in slots:
        return "spec", w.ask_spec("event", "NW_ASK_EVENT"), None
    if not item_refs.may_read(ctx, w.carrier(channel), sender):
        return "spec", w.say_spec("NW_REF_NOT_READABLE"), None
    found = [s for s in calendar_sources(ctx) if not slots.get("account") or s["account"] == slots["account"]]
    chosen = slots.get("source")
    if chosen:
        found = [s for s in found if s["id"] == chosen]
    if not found:
        return "spec", w.say_spec("NW_NO_CALENDAR_SOURCE"), None
    if len(found) > 1:
        return "spec", w.ask_spec("source", "NW_ASK_SOURCE", options=[{"value": s["id"], "label": s["id"]} for s in found]), None
    return "ok", f"{found[0]['id']}#{slots['event']}", found[0]["account"]


def _create(ctx: dict, slots: dict):
    w = _w()
    state, account = w.pick_account(ctx, slots.get("account"), "calendars")
    if state == "spec":
        return account
    state, calendar = w.named_target(ctx, account, "calendars", slots.get("calendar"), "calendar")
    if state == "spec":
        return calendar
    pending = w.engine_spec(ctx, slots)
    if pending:
        return pending
    if "title" not in slots:
        return w.title_spec(ctx, slots)
    if "start" not in slots:
        return w.ask_spec("day", "NW_ASK_DAY")
    args = {"account": account, "title": slots["title"], "start": slots["start"]}
    if slots.get("end"):
        args["end"] = slots["end"]
    if calendar:
        args["calendar"] = calendar
    return {"args": args}


def _change(ctx: dict, op: str, slots: dict, channel, sender):
    w = _w()
    state, ref, source_account = _reference(ctx, slots, channel, sender)
    if state == "spec":
        return ref
    state, account = w.pick_account(ctx, slots.get("account"), "calendars", source_account=source_account)
    if state == "spec":
        return account
    args = {"account": account, "event": ref}
    if op == "event-change":
        pending = w.engine_spec(ctx, slots)
        if pending:
            return pending
        for key in ("start", "end", "title"):
            if slots.get(key):
                args[key] = slots[key]
    return {"args": args}


def resolve(ctx: dict, op: str, slots: dict, channel, sender, said):
    if op == "event-create":
        return _create(ctx, slots)
    return _change(ctx, op, slots, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
