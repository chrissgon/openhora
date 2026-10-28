#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A daily or weekly series of the person's own calendar, named by the words of a line (package CB-7): "cancela a série academia teste", "cancela só a academia da próxima segunda".

runtime/event_lookup.py finds an event by its words and hands the events it found to this file when every one of them is part of a series (the snapshot's index says `recurring`, and a
series the platform created says so in its document). What a line can do with a series is two things and no third (limits L54, L55, L56, L57, L61):

  reply(project, ctx, op, found, kind, value, spans, said, sender, extras, writes, now, account)
      the reply for a change or a cancel, or None when the events are not one series the person may cancel here (then the lookup goes on as it always did: a list, or a card that the
      preparation refuses). A CHANGE of a series is refused in a plain sentence, with no card (RECUR_CHANGE_REFUSED). A CANCEL reads the series from the provider and decides, by the
      closed words of runtime/recurrence.py and never by a guess, between:
        the whole series      series words (todas, a serie, toda segunda ...), no word for one occurrence, no date: a card of the series, in words;
        one occurrence        a word for one occurrence (so, so essa vez, da proxima, dessa semana) or a date (amanha, dia 16, 16/11), no series word: the day is read by the time engine from
                              the person's words (never from the model's time), the occurrence is the one instance the PROVIDER lists for that day (none, several, one that has started
                              and a day that cannot be read are each a sentence), and the card names its date and time as the provider has them and says that the series stays;
        a question            both kinds of words, or neither, or a bare weekday ("cancela a academia de segunda"): RECUR_WHICH, with no card and no memory: the next line is read on its own
                              words.
      A series that is not a plain daily or weekly one, or that the person does not organize alone, gets one sentence and no card (RECUR_CANCEL_NOT_SIMPLE).
      The card is opened through the family path the numbered form uses, with a seed that carries the event's number (the snapshot's, or the card that created it) and `series` or
      `occurrence` (a local day), each with its origin; the master's id and the instance's are read again by the step's preparation from the provider, never taken from here. Nothing is
      written, approved or sent here.

Reading the series is a read of the person's own calendar by the writer's `event-get` and `event-instances` (limit L58: through the seam `calendar_read`, with the right to read a snapshot the
lookup has already checked). Privacy (limit L63): no title, time or id is logged, printed or kept here; the reply holds the person's titles, so the conversation stores a neutral word.
Standard library only. Runs on Python 3.9: python3 runtime/event_series.py --help
"""
from __future__ import annotations

import datetime
import importlib
import sys

import event_created
import natural_time as nt
import phrases
import recurrence
import turn_gate

CHANNEL = "messaging"
WEEK_DAYS = 7              # "this week" is today and the six days after it (the engine reads no range: a day is "this week" while it is among the next seven)
WINDOW_DAYS = 2            # the most days a read of a series' instances spans (the writer refuses more)
LISTED_MAX = 8             # events of the lookup whose series is read (the lookup lists at most as many)
SPECIFIC_SPECS = ("rel", "monthday", "md", "ymd")      # the `spec` kinds of a hit of the time engine that name one date (today, tomorrow, "dia 16", "16 de novembro"), never a bare weekday
WEEKDAY_WORDS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")      # the shape phrases.localize_dates turns into the language's word


def _text(ctx: dict, key: str, **fields) -> str:
    return phrases.text(key, ctx["cfg"], **fields)


def _seams():
    return importlib.import_module("ops_step_seams")


def _document():
    return importlib.import_module("calendar_document")


def _lookup():
    return importlib.import_module("event_lookup")


def specific_day(said: str) -> bool:
    """Whether the line names one date: a date with slashes, today, tomorrow, "dia 16", "16 de novembro", or "this Monday" / "next Monday" ("da proxima segunda"); not a bare weekday name."""
    if _lookup().SLASH.search(said):
        return True
    for hit in nt.find(said)["hits"]:
        spec = hit.get("spec") if isinstance(hit.get("spec"), dict) else {}
        if hit["kind"] == "slash" or (hit["kind"] == "date" and (spec.get("k") in SPECIFIC_SPECS or (spec.get("k") == "wd" and (spec.get("mod") or spec.get("next"))))):
            return True
    return False


def bare_weekday(text):
    """The weekday number (0 = Monday) of a text that names a weekday and no date, and does not say "next" ("segunda", "de segunda", "dessa segunda", "this Monday"), else None. A bare weekday is
    the first such day from TODAY on: today when today is that day (the one occurrence of today may not have started yet)."""
    hits = [h for h in nt.find(text)["hits"] if h["kind"] in ("date", "slash")]
    if _lookup().SLASH.search(text) or len(hits) != 1 or hits[0]["kind"] != "date":
        return None
    spec = hits[0].get("spec") if isinstance(hits[0].get("spec"), dict) else {}
    index = spec.get("i")
    if spec.get("k") != "wd" or spec.get("next") or not isinstance(index, int) or isinstance(index, bool) or not 0 <= index <= 6:
        return None
    return index


def _day_text(day: datetime.date) -> str:
    return f"{WEEKDAY_WORDS[day.weekday()]} {day.strftime('%d/%m')}"


def _local_day(start: str) -> datetime.date:
    """The local day (the machine's zone, the one every wall time of a document is written in) of an instant the writer printed."""
    return _document().parse_instant(start).astimezone().date()


def _rule_text(ctx: dict, rule: str, clock: str) -> str:
    key = "RECUR_RULE_DAILY" if rule == "daily" else "RECUR_RULE_WEEKLY_" + rule[-2:]
    return _text(ctx, key, time=clock)


def _target(reader, row: dict, sender) -> tuple:
    """(account, calendar id, event id) of a row of the lookup: a snapshot's row through the reference the family resolves (with the sender's own right to read it), a row of an event this
    platform created by what its document recorded."""
    if row["source"] == event_created.SOURCE:
        return row["account"], row["calendar_id"], row["event_id"]
    got = reader.event_ref(f"{row['source']}#{row['n']}", CHANNEL, sender)
    return got["account"], got["calendar_id"], got["event_id"]


def _read(ctx: dict, rows: list, sender):
    """([(row, the event the writer printed)], the seam, (account, calendar id)) for the rows, or None when a read fails, a row is gone or the rows are not on one account and one calendar."""
    reader = _seams().CalendarReader(ctx)
    out, where = [], set()
    for row in rows[:LISTED_MAX]:
        account, calendar_id, event_id = _target(reader, row, sender)
        got = reader.event_get(account, calendar_id, event_id)
        raw = got.get("event") if isinstance(got, dict) and got.get("found") is True else None
        if raw is None:
            return None
        out.append((row, raw))
        where.add((account, calendar_id))
    return (out, reader, next(iter(where))) if len(where) == 1 and out else None


def _instances(reader, account: str, calendar_id: str, series: str, days: list) -> list:
    """The live instances of the series on the local days `days` (consecutive), read from the provider in windows of at most two days: [{"id", "start" (as the provider printed it), "day"}]."""
    document, out, at = _document(), [], 0
    while at < len(days):
        chunk = days[at:at + WINDOW_DAYS]
        first, last = document.day_window(chunk[0], len(chunk))
        got = reader.event_instances(account, calendar_id, series, first, last)
        for item in (got.get("instances") if isinstance(got, dict) else None) or []:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("start"), str) and item.get("status") != "cancelled":
                day = _local_day(item["start"])
                if day in chunk:
                    out.append({"id": item["id"], "start": item["start"], "day": day})
        at += WINDOW_DAYS
    return sorted(out, key=lambda i: (i["day"], i["start"]))


def _days_asked(said: str, spans: dict, kind: str, value, now) -> tuple:
    """(the local days the person's words name for ONE occurrence, whether they are a bare weekday that is today). The days are read as the time engine reads them (never the model's time):
    "this week" is a range of seven days from today; a bare weekday ("segunda", "dessa segunda") is that day counting from today, today included; a date is that day; a weekday with "next"
    is the first such day after today; the span the model named for the day is read first, then what the lookup already read, then the whole line. ([], False) when no day can be read (a
    question, never a guess). `said` is the line without the event's name."""
    today = now.date()
    if recurrence.week_range(said):
        return [today + datetime.timedelta(days=i) for i in range(WEEK_DAYS)], False
    for text in (spans.get("day"), said):
        index = bare_weekday(text) if isinstance(text, str) and text else None
        if index is not None:
            ahead = (index - today.weekday()) % 7
            return [today + datetime.timedelta(days=ahead)], ahead == 0
    lookup = _lookup()
    readings = []
    if spans.get("day"):
        readings.append(lookup._day_named(spans["day"], now))
    readings += [(kind, value), lookup._day_named(said, now)]
    for found, got in readings:
        if found == "day":
            return [got], False
        if found == "weekday":
            return [today + datetime.timedelta(days=(got - today.weekday()) % 7 or 7)], False
        if found == "unread":
            return [], False
    return [], False


def _open(project: str, ctx: dict, said: str, sender, extras: dict, writes, row: dict, account, extra: dict, lead_key, lead_fields) -> str:
    """The card of the series cancel or of the occurrence cancel, opened through the family path by the seed of the number of the event the lookup found."""
    if row["source"] == event_created.SOURCE:
        slots = {"created": row["pending"], "account": row["account"]}
    else:
        slots = {"event": row["n"], "source": row["source"], **({"account": account} if account else {})}
    origins = {"event": "grounded", **({"account": "card-copy"} if "created" in slots else {"account": "line-span"} if "account" in slots else {}), **{key: "time-engine" for key in extra}}
    opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed=turn_gate.Seed({"op": "event-cancel", "slots": {**slots, **extra}}, origins))
    if opened is not None and not row.get("exact", True):          # the name was near, not the same: the person is shown which series or occurrence it is, and the card is the question
        lead = _text(ctx, lead_key, **lead_fields)
        extras["lead"] = lead
        return lead + "\n" + opened
    return opened


def reply(project: str, ctx: dict, op: str, found: list, kind: str, value, spans: dict, said: str, sender, extras: dict, writes, now, account):
    """The reply for the events `found` (all part of a series: see the module's text), or None when the lookup should go on as before."""
    extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
    if op == "event-change":
        return _text(ctx, "RECUR_CHANGE_REFUSED")
    try:
        read = _read(ctx, found, sender)
    except Exception:      # noqa: BLE001 - a failed read is one plain sentence; nothing of the fault (it can hold a provider's words) is kept
        return _text(ctx, "EV_CHECK_FAILED")
    if read is None:
        return None
    pairs, reader, (where_account, calendar_id) = read
    series = {raw.get("series_id") for _row, raw in pairs}
    first_row, first = pairs[0]
    if len(series) != 1 or not isinstance(first.get("series_id"), str):
        return None          # events of several series, or one the provider does not call a series: the lookup goes on as it always did
    rule = first.get("series_rule")
    if rule not in ("daily",) and not (isinstance(rule, str) and rule.startswith("weekly:")) or first.get("organizer_self") is not True or first.get("attendees_other"):
        return _text(ctx, "RECUR_CANCEL_NOT_SIMPLE")
    title, clock = first_row["title"], str(first_row["time"])[:5]
    shown = _day_text(first_row["day"])
    rest = recurrence.without(said, spans.get("target"), title)      # the event's own name is not the person's words for the series or the occurrence ("cancela a daily")
    own = recurrence.markers(spans.get("target"), title)      # CB-9: the series or occurrence words a model put inside the target are the person's, unless they stand in the event's name
    rest = (rest + " " + own).strip() if own else rest
    choice = recurrence.which(rest, specific_day(rest))
    if choice == "ask":
        return _text(ctx, "RECUR_WHICH", title=title, rule=_rule_text(ctx, rule, clock), example=shown)
    if choice == "series":
        return _open(project, ctx, said, sender, extras, writes, first_row, account, {"series": True}, "RECUR_FOUND_SERIES", {"title": title, "rule": _rule_text(ctx, rule, clock)})
    days, bare_today = _days_asked(rest, spans, kind, value, now)
    if not days:
        return _text(ctx, "RECUR_ASK_DATE", title=title, example=shown)
    today = now.date()
    days = [d for d in days if d >= today]
    if not days:
        return _text(ctx, "RECUR_OCCURRENCE_PAST", title=title)
    try:
        listed = _instances(reader, where_account, calendar_id, first["series_id"], days)
    except Exception:      # noqa: BLE001 - as above
        return _text(ctx, "EV_CHECK_FAILED")
    span = _day_text(days[0]) if len(days) == 1 else f"{_day_text(days[0])} - {_day_text(days[-1])}"
    if not listed:
        return _text(ctx, "RECUR_NO_OCCURRENCE", title=title, day=span)
    later = [i for i in listed if _document().parse_instant(i["start"]) > now.astimezone()]      # an instance that has started is no choice: it is not cancelled
    if not later and bare_today:
        return _text(ctx, "RECUR_ASK_DATE", title=title, example=shown)      # "segunda" on a Monday whose instance has started: today's is past and next Monday is not what was said
    if not later:
        return _text(ctx, "RECUR_OCCURRENCE_PAST", title=title)
    if len(later) > 1:
        return _text(ctx, "RECUR_WHICH_DAY", title=title, days=", ".join(_day_text(i["day"]) for i in later), example=_day_text(later[0]["day"]))
    one = later[0]
    when = f"{_day_text(one['day'])} {_document().parse_instant(one['start']).astimezone().strftime('%H:%M')}"
    return _open(project, ctx, said, sender, extras, writes, first_row, account, {"occurrence": one["day"].isoformat()}, "RECUR_FOUND_OCCURRENCE",
                 {"title": title, "when": when, "rule": _rule_text(ctx, rule, clock)})


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv in (["--help"], ["-h"]):
        print(__doc__.strip())
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
