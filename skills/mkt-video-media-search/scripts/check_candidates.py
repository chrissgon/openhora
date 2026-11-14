#!/usr/bin/env python3
"""Check the file of web media candidates against the rules of the skill's self-check step.

Deterministic checks only: it never opens a link and never judges whether a licence claim is true. It checks that
the file has the shape the skill promises and that every link would pass the first rules of a reach to the web.

Usage:
  python3 check_candidates.py --slot <name>[:image|clip] [--slot ...] [--file <path>]

  --slot <name>[:kind]  a slot of the task (required, repeated). `:image` or `:clip` limits the slot to that kind;
                        without it both kinds are allowed
  --file <path>         the file to check (default .workbench-local/video/web-candidates.json)

What fails the check:
  - a file that is not a JSON object, a `schema_version` other than 1, a `candidates` or `open` that is not a list
  - a candidate with a missing or wrong-typed field, a `slot` or `kind` the task does not give, a `screen_work`
    that is not a boolean, a `resolution` that is not `<width>x<height>`, a text over its bound (title 120
    characters, `licence_claim` 200, `site_terms` 200, `note` 200)
  - a `media_url`, `page_url` or `thumb_url` that is not https, is over 2048 characters, carries user info or a
    port other than 443, or whose host is an IP literal, has a trailing dot or is not a plain host name
  - more than 3 candidates for a slot, more than 18 in all, or the same `media_url` twice
  - an `open` item with a code other than `no_result`, `no_search_tool` or `scene_only`, or without a slot where
    the code needs one

Output: one JSON object on stdout with `ok`, `summary`, `errors` (a list of {"where", "field", "code"}; never the
refused text) and `counts`. Diagnostics of a usage error go to stderr. Exit codes: 0 no errors, 1 errors found,
2 usage error (nothing is checked).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_FILE = ".workbench-local/video/web-candidates.json"
KINDS = ("image", "clip")
OPEN_CODES = ("no_result", "no_search_tool", "scene_only")
CODES_WITH_SLOT = ("no_result", "scene_only")
MAX_URL = 2048
MAX_TITLE = 120
MAX_CLAIM = 200
MAX_TERMS = 200
MAX_NOTE = 200
MAX_PER_SLOT = 3
MAX_TOTAL = 18
LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
RESOLUTION_RE = re.compile(r"^[1-9][0-9]{1,4}x[1-9][0-9]{1,4}$")
REQUIRED = ("slot", "kind", "media_url", "page_url", "title", "licence_claim", "screen_work")
OPTIONAL = ("thumb_url", "resolution", "site_terms")


def url_problem(value):
    """The code of the first rule the URL breaks, or None. Never returns the text."""
    if not isinstance(value, str) or not value:
        return "not_text"
    if len(value) > MAX_URL:
        return "too_long"
    if not value.startswith("https://"):
        return "not_https"
    if any(ord(c) <= 32 or ord(c) == 127 for c in value):
        return "bad_character"
    rest = value[len("https://"):]
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if not authority:
        return "no_host"
    if "@" in authority:
        return "user_info"
    host = authority
    if authority.startswith("["):
        return "ip_literal"
    if ":" in authority:
        host, _, port = authority.partition(":")
        if port != "443":
            return "bad_port"
    if host.endswith("."):
        return "trailing_dot"
    labels = host.lower().split(".")
    if len(labels) < 2 or len(host) > 253:
        return "bad_host"
    if all(label.isdigit() for label in labels):
        return "ip_literal"
    if not all(LABEL_RE.match(label) for label in labels):
        return "bad_host"
    if labels[-1].isdigit():
        return "bad_host"
    return None


def parse_slots(values):
    """{slot: kinds allowed} from the `--slot` values, or a message for a usage error."""
    slots = {}
    for raw in values:
        name, sep, kind = raw.partition(":")
        if not name or (sep and kind not in KINDS):
            return None, "a --slot is <name> or <name>:image or <name>:clip"
        slots[name] = (kind,) if sep else KINDS
    return slots, None


def check(data, slots):
    """(errors, counts): each error {"where", "field", "code"}; counts of what was read."""
    errors = []

    def err(where, field, code):
        errors.append({"where": where, "field": field, "code": code})

    counts = {"candidates": 0, "open": 0}
    if not isinstance(data, dict):
        err("file", "root", "not_object")
        return errors, counts
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        err("file", "schema_version", "not_1")
    candidates = data.get("candidates")
    opens = data.get("open")
    if not isinstance(candidates, list):
        err("file", "candidates", "not_list")
        candidates = []
    if not isinstance(opens, list):
        err("file", "open", "not_list")
        opens = []
    counts = {"candidates": len(candidates), "open": len(opens)}
    if len(candidates) > MAX_TOTAL:
        err("file", "candidates", "too_many")
    per_slot = {}
    seen = set()
    for i, item in enumerate(candidates):
        where = f"candidates[{i}]"
        if not isinstance(item, dict):
            err(where, "item", "not_object")
            continue
        for key in item:
            if key not in REQUIRED + OPTIONAL:
                err(where, "item", "unknown_field")
                break
        for key in REQUIRED:
            if key not in item:
                err(where, key, "missing")
        slot = item.get("slot")
        kind = item.get("kind")
        if "slot" in item:
            if not isinstance(slot, str) or slot not in slots:
                err(where, "slot", "not_in_task")
            else:
                per_slot[slot] = per_slot.get(slot, 0) + 1
        if "kind" in item:
            if kind not in KINDS:
                err(where, "kind", "not_image_or_clip")
            elif isinstance(slot, str) and slot in slots and kind not in slots[slot]:
                err(where, "kind", "not_in_task")
        for key in ("media_url", "page_url", "thumb_url"):
            if key in item:
                problem = url_problem(item[key])
                if problem:
                    err(where, key, problem)
        media = item.get("media_url")
        if isinstance(media, str):
            if media in seen:
                err(where, "media_url", "duplicate")
            seen.add(media)
        for key, bound in (("title", MAX_TITLE), ("licence_claim", MAX_CLAIM), ("site_terms", MAX_TERMS)):
            if key in item:
                value = item[key]
                if not isinstance(value, str) or not value.strip():
                    err(where, key, "not_text")
                elif len(value) > bound:
                    err(where, key, "too_long")
        if "screen_work" in item and not isinstance(item["screen_work"], bool):
            err(where, "screen_work", "not_boolean")
        if "resolution" in item:
            value = item["resolution"]
            if not isinstance(value, str) or not RESOLUTION_RE.match(value):
                err(where, "resolution", "bad_form")
    for slot, n in sorted(per_slot.items()):
        if n > MAX_PER_SLOT:
            err("file", "candidates", "too_many_for_slot")
    for i, item in enumerate(opens):
        where = f"open[{i}]"
        if not isinstance(item, dict):
            err(where, "item", "not_object")
            continue
        for key in item:
            if key not in ("code", "slot", "note"):
                err(where, "item", "unknown_field")
                break
        code = item.get("code")
        if code not in OPEN_CODES:
            err(where, "code", "unknown_code")
        if "slot" in item and (not isinstance(item["slot"], str) or item["slot"] not in slots):
            err(where, "slot", "not_in_task")
        elif code in CODES_WITH_SLOT and "slot" not in item:
            err(where, "slot", "missing")
        if "note" in item:
            note = item["note"]
            if not isinstance(note, str) or not note.strip():
                err(where, "note", "not_text")
            elif len(note) > MAX_NOTE:
                err(where, "note", "too_long")
    return errors, counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the file of web media candidates (see the module text).")
    parser.add_argument("--slot", action="append", default=[], help="a slot of the task: <name> or <name>:image|clip (required, repeated)")
    parser.add_argument("--file", default=DEFAULT_FILE, help=f"the file to check (default {DEFAULT_FILE})")
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    if not args.slot:
        print("error: at least one --slot is required", file=sys.stderr)
        return 2
    slots, problem = parse_slots(args.slot)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2
    path = Path(args.file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        print("error: the file cannot be read", file=sys.stderr)
        return 2
    except ValueError:
        out = {"ok": False, "summary": "1 error", "errors": [{"where": "file", "field": "root", "code": "not_json"}],
               "counts": {"candidates": 0, "open": 0}}
        print(json.dumps(out))
        return 1
    errors, counts = check(data, slots)
    ok = not errors
    summary = ("ok: %d candidates, %d open" % (counts["candidates"], counts["open"])) if ok else f"{len(errors)} errors"
    print(json.dumps({"ok": ok, "summary": summary, "errors": errors, "counts": counts}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
