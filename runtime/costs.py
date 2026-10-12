#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The cost of the runs, recomputed from the token counts the adapter left in a run folder and the prices the person
typed into the project's configuration (model_prices, runtime/project_config.py).

The cost the store records for a run is the adapter's own number, kept only for a run on a metered credential (an API
key: its cost is billed). A run on a subscription or a free credential carries no cost, and the pinned tool does not
price the reference model either. So the page and the report recompute it: the tokens of each kind times the price of
that kind per million, summed. Arithmetic only. Nothing here guesses: a run whose folder holds no usage, or whose model
has no price, has no recomputed cost; it is `unknown`, and the summary counts it (`unknown_runs`).

  usage_of(run_dir)               the token counts of one run by kind, or None
  recompute(usage, price)         the cost in dollars of one usage at one price
  summary(runs, prices, since)    rows by day, agent, model and adapter

Usage (a library): python3 runtime/costs.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import json
import os
import sys

KINDS = ("input", "output", "cache_read", "cache_write")
# The reference model's adapter keeps the CLI's result event as outputs/raw.json: its `usage` object has these four
# names. The floor model's adapter keeps only its event stream, outputs/stream.jsonl, one `step_finish` event per step.
REFERENCE_NAMES = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens",
                   "cache_write": "cache_creation_input_tokens"}
RAW = os.path.join("outputs", "raw.json")
STREAM = os.path.join("outputs", "stream.jsonl")
RAW_MAX = 8 * 1024 * 1024      # a result event is small; a larger file is not one
STREAM_MAX = 256 * 1024 * 1024  # a stream carries every tool result; a larger one is not read
PER_MILLION = 1_000_000


# T23: the recomputation of a run's cost from its token counts and the prices in the project's configuration is a
# workaround: the pinned tool does not know the model of the reference adapter, so its runs record no cost. It leaves
# at the change of the reference model, when the tool prices it. Two limits meanwhile: a run made again after a failed
# attempt keeps only the last attempt's files (an earlier one is set aside beside them), so the tokens of such a run
# are understated; and the floor adapter's reasoning tokens have no kind of their own, so a stream that reports any is
# read as unknown rather than priced short.
def usage_of(run_dir) -> dict | None:
    """The token counts of one run by kind, {"input", "output", "cache_read", "cache_write"}, read from what the
    adapter left in the run folder: outputs/raw.json (the reference adapter's result event: `usage` with
    input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens; a list of events is read at
    its `result` event) or, when there is no raw.json, outputs/stream.jsonl (the floor adapter: the `part.tokens` of
    each `step_finish` event summed). None when the folder holds neither, when a file is a link, is not a regular
    file or is over its size limit, or when what it holds is not in one of these two forms (a missing or negative
    count, a count that is not a whole number). A cache count the reference form leaves out is 0, as the adapter
    sums it; the input and output counts must be there. Never a guess."""
    if not isinstance(run_dir, str) or not run_dir or not os.path.isabs(run_dir):
        return None
    raw = _text(os.path.join(run_dir, RAW), RAW_MAX)
    if raw is not None:
        return _from_result(raw)
    if os.path.lexists(os.path.join(run_dir, RAW)):
        return None  # a raw.json that cannot be read is unknown; the stream is not asked in its place
    stream = _text(os.path.join(run_dir, STREAM), STREAM_MAX)
    return None if stream is None else _from_stream(stream)


def _text(path: str, limit: int):
    """The text of a regular file that is not a link and not over limit; None otherwise."""
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > limit:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _count(value):
    """A whole number of 0 or more, never a boolean; else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _from_result(text: str):
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, list):
        data = next((e for e in reversed(data) if isinstance(e, dict) and e.get("type") == "result"), None)
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None
    out = {}
    for kind in KINDS:
        name = REFERENCE_NAMES[kind]
        value = _count(usage[name]) if name in usage else (0 if kind.startswith("cache") else None)
        if value is None:
            return None
        out[kind] = value
    return out


def _from_stream(text: str):
    out, seen = {kind: 0 for kind in KINDS}, False
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "step_finish":
            continue
        part = event.get("part")
        tokens = part.get("tokens") if isinstance(part, dict) else None
        if not isinstance(tokens, dict):
            return None
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        found = {"input": tokens.get("input"), "output": tokens.get("output"), "cache_read": cache.get("read"),
                 "cache_write": cache.get("write")}
        reasoning = tokens.get("reasoning")
        if reasoning not in (None, 0):
            return None  # no kind of its own: priced short if it were left out
        for kind, value in found.items():
            if value is None and kind.startswith("cache"):
                value = 0
            if _count(value) is None:
                return None
            out[kind] += value
        seen = True
    return out if seen else None


def recompute(usage: dict, price: dict) -> float:
    """The cost in dollars of one usage at one price: for each kind, its tokens times its price per million
    (price["<kind>_usd_per_mtok"]), summed. Arithmetic only; the caller has checked that both are there."""
    return sum(usage[kind] * price[f"{kind}_usd_per_mtok"] / PER_MILLION for kind in KINDS)


def day_of(started_at) -> str:
    """The local calendar day (YYYY-MM-DD) of a stored ISO-8601 time, the day the daily caps count by."""
    moment = datetime.datetime.fromisoformat(str(started_at).strip().replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone().date().isoformat()


def summary(runs, prices: dict, since=None) -> list:
    """Rows by day, agent, model and adapter, oldest day first: {"day", "agent", "model", "adapter", "runs",
    "tokens", "recorded_usd", "recomputed_usd", "unknown_runs", "price"}.

    runs are rows of task_runs with an "agent" (the task's); a row needs started_at, model, adapter, cost_usd,
    tokens and run_dir. prices is the configuration's model_prices. since is None or a day YYYY-MM-DD: earlier days
    are left out. `tokens` is the sum of the recorded totals (None when none was recorded); `recorded_usd` the sum of
    the recorded costs, None when every one is NULL; `recomputed_usd` the sum of recompute() over the group's runs,
    None when the model has no price or any run of the group has no usage (usage_of); `unknown_runs` is the number
    of runs of the group with no usage; `price` is the entry's source and date when the model has one, else None."""
    groups = {}
    for run in runs:
        day = day_of(run["started_at"])
        if since is not None and day < since:
            continue
        key = (day, run.get("agent"), run["model"], run["adapter"])
        groups.setdefault(key, []).append(run)
    rows = []
    for (day, agent, model, adapter), members in sorted(groups.items(), key=lambda item: (item[0][0], str(item[0][1]),
                                                                                         item[0][2], item[0][3])):
        costs = [r["cost_usd"] for r in members if r.get("cost_usd") is not None]
        tokens = [r["tokens"] for r in members if r.get("tokens") is not None]
        usages = [usage_of(r.get("run_dir")) for r in members]
        unknown = sum(1 for u in usages if u is None)
        price = prices.get(model)
        recomputed = None if price is None or unknown else round(sum(recompute(u, price) for u in usages), 6)
        rows.append({"day": day, "agent": agent, "model": model, "adapter": adapter, "runs": len(members),
                     "tokens": sum(tokens) if tokens else None,
                     "recorded_usd": round(sum(costs), 6) if costs else None, "recomputed_usd": recomputed,
                     "unknown_runs": unknown,
                     "price": {"source": price["source"], "date": price["date"]} if price else None})
    return rows


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
