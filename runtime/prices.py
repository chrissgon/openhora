#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The one price table: runtime/prices.json, read once, here.

The table holds, for each model, the prices in dollars per million tokens of the four kinds a run's usage is counted in
(input, output, cache_read, cache_write), the URL they were read from (`source`) and the day (`accessed`), and the other
ids the workbench writes for the same model (`aliases`). The runtime's cost of a run (runtime/costs.py), the `auto`
ranking (runtime/proof.py), the proof page and the API adapter read this file and no other:
the project's `model_prices` key is retired (runtime/project_config.py keeps accepting it and ignores it). A price is
shown as stale when it is older than the project's `price_max_age_days` (default 90).

A kind an entry leaves out is unknown: `expected_cost` is None when the usage holds tokens of a kind that has no price,
and counts a kind with no tokens as nothing. Nothing is guessed.

Functions:
  load(path=None)                       the table: {"models": {id: entry}}; {"models": {}} when the file is missing or invalid
  find(table, names)                    (id, entry) of the first name that is an id or an alias of an entry, else (None, None)
  price_of(table, names)                the entry, or None
  expected_cost(usage, price)           dollars for one run of this usage at this price, or None when a kind used has no price
  age_days(price, today)                whole days since the price was accessed, or None
  is_stale(price, today, max_days)      True when the price is older than max_days (or its date cannot be read)
  summary(price, today, max_days)       {"source", "accessed", "age_days", "stale"} for a page, or None

Usage (a library): python3 runtime/prices.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "prices.json")
KINDS = ("input", "output", "cache_read", "cache_write")
PER_MILLION = 1_000_000
MAX_AGE_DEFAULT = 90  # days; a project sets price_max_age_days


def field(kind: str) -> str:
    """The name of a kind's price in an entry."""
    return f"{kind}_usd_per_mtok"


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def load(path: str | None = None) -> dict:
    """The price table. An entry is kept when it is an object; a field that is not a number of 0 or more is dropped from it
    (unknown, not zero). A missing or invalid file gives {"models": {}}."""
    try:
        with open(path or FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"models": {}}
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        return {"models": {}}
    out = {}
    for name, entry in models.items():
        if not isinstance(entry, dict):
            continue
        clean = {k: v for k, v in entry.items() if not k.endswith("_usd_per_mtok") or _number(v) is not None}
        out[str(name)] = clean
    return {"models": out}


def find(table: dict, names) -> tuple:
    """(id, entry) for the first of `names` (a model id, then its aliases) that is an id of the table or one of an entry's
    aliases; (None, None) when none is."""
    models = (table or {}).get("models") or {}
    for name in names or ():
        if name in models:
            return name, models[name]
        for key, entry in models.items():
            if name in (entry.get("aliases") or ()):
                return key, entry
    return None, None


def price_of(table: dict, names):
    """The entry of the model written under any of `names`, or None."""
    return find(table, names)[1]


def expected_cost(usage, price):
    """Dollars for one run that used `usage` ({kind: tokens}, any kind may be absent) at `price` (an entry): the sum over the
    kinds of tokens times the kind's price per million. None when price or usage is missing, or when a kind with tokens
    has no price in the entry. A kind with 0 tokens costs nothing whatever its price."""
    if not isinstance(usage, dict) or not isinstance(price, dict):
        return None
    total = 0.0
    for kind in KINDS:
        tokens = usage.get(kind) or 0
        if not tokens:
            continue
        per = _number(price.get(field(kind)))
        if per is None:
            return None
        total += tokens * per / PER_MILLION
    return total


def _day(value):
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def age_days(price, today) -> int | None:
    """Whole days from the price's `accessed` date to `today` (a date or YYYY-MM-DD); None when either cannot be read."""
    if not isinstance(price, dict):
        return None
    accessed = _day(price.get("accessed"))
    now = today if isinstance(today, datetime.date) else _day(today)
    if accessed is None or now is None:
        return None
    return (now - accessed).days


def is_stale(price, today, max_days: int = MAX_AGE_DEFAULT) -> bool:
    """True when the price is older than max_days, or its date cannot be read: a price with no date is not fresh."""
    age = age_days(price, today)
    return age is None or age > max_days


def summary(price, today, max_days: int = MAX_AGE_DEFAULT):
    """What a page shows beside a price: {"source", "accessed", "age_days", "stale"}; None when there is no price."""
    if not isinstance(price, dict):
        return None
    return {"source": price.get("source"), "accessed": price.get("accessed"), "age_days": age_days(price, today),
            "stale": is_stale(price, today, max_days)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
