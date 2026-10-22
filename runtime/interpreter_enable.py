#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The decision that turns the natural-language interpreter on for a project's lines (slice S1), as a committed file the runtime reads.

The interpreter (runtime/interpreter.py) runs for a messaging line only while the NEWEST entry of runtime/interpreter_enable.json is in force. An entry is the
maintainer's dated decision (`basis` "maintainer-decision"; `evidence` is reserved for a row a later package generates from a passing band) and it names exactly
what was decided on: the route, and the hashes of the route's object, of the prompt, of the served catalog and of the protocol, with the languages it covers. It is
in force only while every one of those hashes equals the checkout's own, and only for a project whose language is listed. A change of the prompt, the catalog, the
protocol or the route therefore turns the interpreter off until a new dated entry is appended: nothing ticks it back on, and no band moves it.

The route is read from `interpreter_route.daily_routes()` (kind `http` only: the routes that may run for a person every day), never from the file of all routes,
so a route of another kind cannot be named by an entry. The status (evals/interpreter_status.py) reads the same file as data and prints `status_line` beside the
route's band; a test compares the two readings.

  load(path=None)               the file, checked: {"v": 1, "entries": [...]} with closed keys, dates in order. Raises EnableError.
  checkout_hashes(route_id)     {"route_sha256", "prompt_sha256", "catalog_sha256", "protocol_sha256"} of this checkout for a daily route, or EnableError
  active(language, path=None)   {"entry", "route"} when the newest entry is in force for the language, else None (it never raises: any fault is "off")
  compose_active(language, path=None)
                                the same as `active` and the newest entry also pins THIS checkout's e-mail compose prompt (`compose_prompt_sha256`, runtime/mail_compose.py), else
                                None: a changed compose prompt turns composing off and leaves the interpreter on (slice S7)
  retention(path=None)          the retention text of the newest entry's route, or None (what a person is shown when they widen the group `interpret`)

Pure: it reads files and calls nothing. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import interpreter  # noqa: E402  (the same folder: the prompt, the served catalog and the protocol whose hashes an entry names)
import interpreter_route  # noqa: E402  (the same folder: the daily routes and the hash of a route)
import mail_compose  # noqa: E402  (the same folder: the sha256 of the e-mail compose prompt)

ENABLE_FILE = os.path.join(HERE, "interpreter_enable.json")
KEYS = ("basis", "date", "route", "route_sha256", "prompt_sha256", "catalog_sha256", "protocol_sha256", "languages", "reason", "status_line")
BASES = ("maintainer-decision",)
LANGUAGES = ("pt-BR", "en", "es", "fr", "de", "it")
HASH_KEYS = ("route_sha256", "prompt_sha256", "catalog_sha256", "protocol_sha256")
OPTIONAL_KEYS = ("compose_prompt_sha256",)      # an entry may also pin the e-mail compose prompt (slice S7); an older entry does not
HEX64 = re.compile(r"[0-9a-f]{64}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
TEXT_MAX = 600


class EnableError(ValueError):
    """The enabling file is not what this module accepts."""


def _entry_problem(entry) -> str:
    """The first thing wrong with one entry (a sentence that never repeats a value), or ''."""
    if not isinstance(entry, dict) or not set(KEYS) <= set(entry) <= set(KEYS + OPTIONAL_KEYS):
        return "an entry has the keys " + ", ".join(KEYS) + " and, optionally, " + ", ".join(OPTIONAL_KEYS)
    if entry["basis"] not in BASES:
        return "basis is one of " + ", ".join(BASES)
    if not isinstance(entry["date"], str) or not DATE.fullmatch(entry["date"]):
        return "date is YYYY-MM-DD"
    try:
        datetime.date.fromisoformat(entry["date"])
    except ValueError:
        return "date is a real day"
    if not isinstance(entry["route"], str) or not entry["route"]:
        return "route is a route id"
    for key in HASH_KEYS + tuple(k for k in OPTIONAL_KEYS if k in entry):
        if not isinstance(entry[key], str) or not HEX64.fullmatch(entry[key]):
            return f"{key} is a sha256 (64 lower-case hexadecimal digits)"
    langs = entry["languages"]
    if not isinstance(langs, list) or not langs or len(set(langs)) != len(langs) or not all(isinstance(l, str) and l in LANGUAGES for l in langs):
        return "languages is a list of distinct languages from " + ", ".join(LANGUAGES)
    for key in ("reason", "status_line"):
        if not isinstance(entry[key], str) or not entry[key].strip() or len(entry[key]) > TEXT_MAX:
            return f"{key} is a non-empty text of at most {TEXT_MAX} characters"
    return ""


def load(path=None) -> dict:
    try:
        with open(path or ENABLE_FILE, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError):
        raise EnableError("the enabling file cannot be read") from None
    if not isinstance(doc, dict) or set(doc) != {"v", "entries"} or doc["v"] != 1 or not isinstance(doc["entries"], list) or not doc["entries"]:
        raise EnableError("the enabling file is {v: 1, entries: [...]} with at least one entry")
    for entry in doc["entries"]:
        problem = _entry_problem(entry)
        if problem:
            raise EnableError(problem)
    dates = [e["date"] for e in doc["entries"]]
    if dates != sorted(dates):
        raise EnableError("the entries are in the order of their dates")
    return doc


def _daily_row(route_id: str):
    """The one daily (http) route with this id, or None."""
    try:
        rows = [r for r in interpreter_route.daily_routes() if r["id"] == route_id]
    except (interpreter_route.RouteError, OSError, ValueError):
        return None
    return rows[0] if len(rows) == 1 and rows[0].get("kind") == "http" else None


def checkout_hashes(route_id: str) -> dict:
    row = _daily_row(route_id)
    if row is None:
        raise EnableError("the entry names no daily route")
    return {"route_sha256": interpreter_route.route_sha256(row), "prompt_sha256": interpreter.prompt_sha256(), "catalog_sha256": interpreter.SERVED_SHA256,
            "protocol_sha256": hashlib.sha256(interpreter.canonical(interpreter.PROTOCOL)).hexdigest()}


def active(language, path=None):
    """{"entry", "route"} when the NEWEST entry is in force for `language`, else None. Every fault is "off"."""
    try:
        entry = load(path)["entries"][-1]
        if language not in entry["languages"]:
            return None
        here = checkout_hashes(entry["route"])
        if any(entry[key] != here[key] for key in HASH_KEYS):
            return None
        return {"entry": entry, "route": _daily_row(entry["route"])}
    except (EnableError, OSError, ValueError, KeyError, TypeError):
        return None


def compose_active(language, path=None):
    """The result of `active` when the newest entry also pins this checkout's compose prompt, else None. Every fault is "off"."""
    got = active(language, path)
    if got is None:
        return None
    try:
        return got if got["entry"].get(OPTIONAL_KEYS[0]) == mail_compose.prompt_sha256() else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def retention(path=None):
    """The retention text of the newest entry's daily route, or None."""
    try:
        row = _daily_row(load(path)["entries"][-1]["route"])
    except (EnableError, OSError, ValueError, KeyError, TypeError):
        return None
    return row.get("retention") if row else None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
