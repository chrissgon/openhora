#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The calendar family of the natural writes, with the project (package NR-5a): what the pure reading of runtime/natural_writes_calendar.py leaves to the configuration and
the registered sources, in the fixed order of the questions (SPEC-NATURAL-WRITES 4): the account, the calendar, the event (and the calendar source it is numbered in, or the card that created it: `created`), the
time, the title. Each step is code: an account is a service word of the line, the account of the reference, the one account that lists calendars, `accounts.default` or the
person's choice; a calendar is a name the account lists, folded, or the operation's default; an event is `<source>#<n>` with the number written in the line (or `created:<card>` for an event the platform created, slice S16: the slot `created`), resolved by the
operation with the caller's rights (a caller who may not read a snapshot is told so here and nothing of the calendar is named); a time is the time engine's single reading.

resolve(ctx, op, slots, channel, sender, said) -> {"args"} | {"ask"} | {"say"} (the interface of runtime/natural_writes.py).

Sibling of runtime/ops_natural_writes.py. Standard library only. Runs on Python 3.9: python3 runtime/ops_natural_calendar.py --help
"""
from __future__ import annotations

import sys

import item_refs
import ops_natural_writes
import sources
import sources_mail
import turn_gate

CAL_ACCOUNT = {"google": "google", "outlook": "microsoft"}      # the implementation named in a calendar source's origin -> the account it belongs to


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
    w = ops_natural_writes
    if "event" not in slots and slots.get("created") is None:
        return "spec", w.ask_spec("event", "NW_ASK_EVENT"), None
    if not item_refs.may_read(ctx, w.carrier(channel), sender):
        return "spec", w.say_spec("NW_REF_NOT_READABLE"), None
    if slots.get("created") is not None:          # an event the platform itself created (runtime/event_lookup.py, slice S16): the reference is the card that created it
        return "ok", f"created:{int(slots['created'])}", slots.get("account")
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
    w = ops_natural_writes
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
        return w.ask_spec("day", "NW_ASK_DAY_INVALID" if slots.get("_clock") else "NW_ASK_DAY")          # a kept clock: the date written does not exist
    args = {"account": account, "title": slots["title"], "start": slots["start"]}
    origins = {"account": turn_gate.account_origin(slots, slots.get("account")), "title": turn_gate.origin_of(slots, "title", "line-span"), "start": turn_gate.origin_of(slots, "start", "time-engine")}
    if slots.get("end"):
        args["end"] = slots["end"]
        origins["end"] = turn_gate.origin_of(slots, "end", "time-engine")
    if calendar:
        args["calendar"] = calendar
        origins["calendar"] = turn_gate.origin_of(slots, "calendar", "line-span")
    if slots.get("repeat"):          # CB-7: "daily" or "weekly", read by code from the closed words of the line (runtime/recurrence.py): the card says it, the writer expands it in the start's zone
        args["repeat"] = slots["repeat"]
        origins["repeat"] = turn_gate.origin_of(slots, "repeat", "time-engine")
    return {"args": args, "origins": origins}


def _change(ctx: dict, op: str, slots: dict, channel, sender):
    w = ops_natural_writes
    state, ref, source_account = _reference(ctx, slots, channel, sender)
    if state == "spec":
        return ref
    ref_origin = "grounded" if slots.get("created") is not None else turn_gate.origin_of(slots, "event", "line-number")          # S41-7: an event this platform created was found by words; a number is the line's unless a list or a search made it
    state, account = w.pick_account(ctx, slots.get("account"), "calendars", source_account=source_account)
    if state == "spec":
        return account
    args = {"account": account, "event": ref}
    origins = {"account": turn_gate.account_origin(slots, slots.get("account")), "event": ref_origin}
    for key in (("series", "occurrence") if op == "event-cancel" else ()):          # CB-7: the whole series, or the local day of one occurrence, chosen by code (runtime/event_series.py)
        if slots.get(key):
            args[key] = slots[key]
            origins[key] = turn_gate.origin_of(slots, key, "time-engine")
    if op == "event-change":
        pending = w.engine_spec(ctx, slots)
        if pending:
            return pending
        for key in ("start", "end", "title"):
            if slots.get(key):
                args[key] = slots[key]
                origins[key] = turn_gate.origin_of(slots, key, "line-span" if key == "title" else "time-engine")
    return {"args": args, "origins": origins}


def resolve(ctx: dict, op: str, slots: dict, channel, sender, said):
    if op == "event-create":
        return _create(ctx, slots)
    return _change(ctx, op, slots, channel, sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
