#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Routines, the pure part (package P6b; decisions D23, D24, D31 to D35): the schedule, the slots that are due, the catch-up rule and the
content a routine's approval covers. No store, no clock of its own, no file: the operations (runtime/ops_routines.py) pass everything in.

A schedule is one of three forms, checked by check_schedule():

  {"every": "day", "at": "HH:MM"}                          every day at that local time
  {"every": "week", "weekday": 1..7, "at": "HH:MM"}        every week on that day (1 Monday, 7 Sunday) at that local time
  {"every": "minutes", "minutes": N}                       every N minutes from local midnight (N from 15 to 720 that divides 1,440)

Times are the local time of the clock the caller gives, which carries its zone: a slot is named by its local date and time,
"2026-10-15T08:00". A slot is a moment the routine is due, not a fire.

The fire key (finding I5). A fire is the pair (routine, slot): the store's `routine_fires` has that pair unique, so a slot creates
tasks once, whatever process or tick finds it due.

The catch-up rule (the supervisor's decision of 2026-10-15 while the maintainer was away, logged in docs/decisions.md). due() looks at
the slots after the last one the routine has a row for (after its approval, for a routine that never fired) up to now. If the newest of
them is younger than the routine's window it is the one fire, and every older slot is skipped and noted; if it is older, all are skipped
and noted. Never one run per missed slot. The window is the one the record holds (`window_seconds`), else the routine's own period
(a day, a week, or its interval), so an outage shorter than a period is made up once and a longer one is not.

What an approval covers (decision D35). content() is the dictionary whose sha256 the person approves: the schedule (with its window),
the workflow's template hash and the fixed arguments (never the values the dates take), the `X.Y` of every skill the workflow names (a
Z change moves nothing), the digest of the eval image, the scripts' hashes and destinations (a slot for package P9), the model and the
routine's own consent (decision D34, with the hash of the warning it was given), and for `auto` the approved set of providers. A
routine has no mode, cap, policy or standing approval of its own. A new version of a source moves nothing: the workflow pins the id.
differences() says which parts differ between two contents, for the sentence of the stop.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
import sys

HHMM = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])")
EVERY = ("day", "week", "minutes")
MIN_MINUTES, MAX_MINUTES = 15, 720
MIN_WINDOW = 60
SLOT_FORMAT = "%Y-%m-%dT%H:%M"
LOOK_BACK = 500          # the slots due() looks at, newest first: a routine every 15 minutes silent for 5 days has 480
KEEP_SKIPPED = 10        # the skipped slots that get a row of their own; the rest are counted in the newest one's reason
CONTENT_VERSION = 1


def check_schedule(raw) -> dict:
    """The schedule, checked and in its canonical form; ValueError says how it is not one."""
    if not isinstance(raw, dict) or raw.get("every") not in EVERY:
        raise ValueError(f"a schedule says every: {', '.join(EVERY)}")
    every = raw["every"]
    wanted = {"day": {"every", "at"}, "week": {"every", "weekday", "at"}, "minutes": {"every", "minutes"}}[every]
    if set(raw) != wanted:
        raise ValueError(f"a schedule every {every} has exactly {', '.join(sorted(wanted - {'every'}))}")
    if every == "minutes":
        n = raw["minutes"]
        if isinstance(n, bool) or not isinstance(n, int) or not MIN_MINUTES <= n <= MAX_MINUTES or 1440 % n:
            raise ValueError(f"minutes is a whole number from {MIN_MINUTES} to {MAX_MINUTES} that divides 1,440 (a day)")
        return {"every": "minutes", "minutes": n}
    if not isinstance(raw["at"], str) or not HHMM.fullmatch(raw["at"]):
        raise ValueError("at is a local time HH:MM, 00:00 to 23:59")
    if every == "week":
        day = raw["weekday"]
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 7:
            raise ValueError("weekday is 1 (Monday) to 7 (Sunday)")
        return {"every": "week", "weekday": day, "at": raw["at"]}
    return {"every": "day", "at": raw["at"]}


def period_seconds(schedule: dict) -> int:
    return {"day": 86400, "week": 7 * 86400}.get(schedule["every"]) or schedule["minutes"] * 60


def window_of(schedule: dict, window_seconds) -> int:
    """The catch-up window: the record's, else the period."""
    return window_seconds if isinstance(window_seconds, int) and window_seconds >= MIN_WINDOW else period_seconds(schedule)


def _at(day: datetime.date, hhmm: str) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(int(hhmm[:2]), int(hhmm[3:])))


def slot_name(moment: datetime.datetime) -> str:
    return moment.strftime(SLOT_FORMAT)


def parse_slot(name: str) -> datetime.datetime:
    return datetime.datetime.strptime(name, SLOT_FORMAT)


def newest_slot(schedule: dict, local: datetime.datetime) -> datetime.datetime:
    """The newest slot at or before a local time (naive)."""
    every = schedule["every"]
    if every == "minutes":
        n = schedule["minutes"]
        since = local.hour * 60 + local.minute
        return local.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(minutes=since - since % n)
    if every == "day":
        slot = _at(local.date(), schedule["at"])
        return slot if slot <= local else slot - datetime.timedelta(days=1)
    back = (local.isoweekday() - schedule["weekday"]) % 7
    slot = _at(local.date() - datetime.timedelta(days=back), schedule["at"])
    return slot if slot <= local else slot - datetime.timedelta(days=7)


def previous_slot(schedule: dict, slot: datetime.datetime) -> datetime.datetime:
    """The slot before another."""
    if schedule["every"] == "minutes":
        return slot - datetime.timedelta(minutes=schedule["minutes"])
    return slot - datetime.timedelta(days=1 if schedule["every"] == "day" else 7)


def due(schedule: dict, last_slot, since: datetime.datetime, now: datetime.datetime, window_seconds=None) -> dict:
    """What a tick does for one routine. schedule is checked; last_slot is the name of the newest slot the routine has a row for, or
    None; since is the local time (naive) its approval was recorded, from which a routine that never fired counts; now is the local
    time (naive). Returns {"fire": the slot's name or None, "skipped": [names, oldest first], "skipped_count", "window"}."""
    lower = parse_slot(last_slot) if last_slot else since
    window = window_of(schedule, window_seconds)
    slots, slot = [], newest_slot(schedule, now)
    while slot > lower and len(slots) < LOOK_BACK:
        slots.append(slot)
        slot = previous_slot(schedule, slot)
    if not slots:
        return {"fire": None, "skipped": [], "skipped_count": 0, "window": window}
    newest = slots[0]
    age = (now - newest).total_seconds()
    fire = slot_name(newest) if age <= window else None
    missed = slots[1:] if fire else slots
    kept = [slot_name(m) for m in sorted(missed)][-KEEP_SKIPPED:]
    return {"fire": fire, "skipped": kept, "skipped_count": len(missed), "window": window}


def content(*, schedule: dict, window_seconds, flow: str, template_sha256: str, params: dict, skills: dict, image, scripts=(),
            model, consent: bool, warning_sha256: str, providers) -> dict:
    """The content whose sha256 a routine's approval covers (module text). skills is {skill: "X.Y"}; scripts is [] until package P9
    (a project script's sha256 and declared destinations will be listed there); model is the model id, "auto" or "default" resolved by
    the caller to the word that will choose; providers is the approved set for auto (sorted here)."""
    return {"version": CONTENT_VERSION, "schedule": {**schedule, "window_seconds": window_of(schedule, window_seconds)},
            "workflow": {"name": flow, "template_sha256": template_sha256, "params": dict(sorted(params.items()))},
            "skills": dict(sorted(skills.items())), "image": image, "scripts": sorted(scripts, key=json.dumps),
            "model": model, "consent": {"given": True, "warning_sha256": warning_sha256} if consent else {"given": False},
            "providers": sorted(set(providers))}


def sha256_of(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def differences(old: dict, new: dict) -> list:
    """The names of the parts of two contents that differ, for a sentence: schedule, workflow template, fixed arguments, a skill's
    X.Y (named), the image, scripts, model, consent, providers."""
    if not old:
        return ["the approved content is not on record"]
    out = []
    if old.get("schedule") != new.get("schedule"):
        out.append("the schedule")
    if (old.get("workflow") or {}).get("template_sha256") != new["workflow"]["template_sha256"]:
        out.append("the workflow's template")
    if (old.get("workflow") or {}).get("params") != new["workflow"]["params"] or (old.get("workflow") or {}).get("name") != new["workflow"]["name"]:
        out.append("the workflow or its fixed arguments")
    for skill in sorted(set(old.get("skills") or {}) | set(new["skills"])):
        if (old.get("skills") or {}).get(skill) != new["skills"].get(skill):
            out.append(f"the version of {skill} ({(old.get('skills') or {}).get(skill)} to {new['skills'].get(skill)})")
    for key, word in (("image", "the eval image"), ("scripts", "a script"), ("model", "the model"), ("consent", "the consent"),
                      ("providers", "the approved providers")):
        if old.get(key) != new[key]:
            out.append(word)
    return out or ["the content (its version)"]


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
