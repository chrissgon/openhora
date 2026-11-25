"""Advice, not refusal: the maintainer's principle of 2026-11-24 ("limit for security, release the creative questions"). A creative choice that goes past a
default is drawn and reported as a row of the `advice` list; the host turns the closed code into one plain sentence, the container never writes it.

A row is {code, value, default, count, ids?}: `code` one of CODES, `value` and `default` finite numbers in the code's unit, `count` the number of items past
the default (1 or more), `ids` at most IDS_MAX ids of the closed pattern (beat ids, effect ids, `c<k>` for a caption entry, `r<k>` for a kept range). There is
one row per code, `value` is the worst case seen (the largest for a "max" code, the smallest for a "min" one), and the list is sorted by code, at most
ROWS_MAX rows. Standard library only.
"""
from __future__ import annotations

import math
import re

ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
IDS_MAX = 12
ROWS_MAX = 24

# code -> (worst, unit). The sentence of each code lives on the host (runtime/deliver_document.py), keyed by this closed word.
CODES = {
    "card_room_small": ("min", "px"),
    "caption_room_small": ("min", "px"),
    "caption_below_line": ("max", "px"),
    "drawn_below_line": ("max", "frames"),
    "block_not_drawn": ("max", "frames"),
    "caption_not_drawn": ("max", "frames"),
    "face_pixels_changed": ("min", "dB"),
    "beats_over_default": ("max", "beats"),
    "punches_over_default": ("max", "punches"),
    "aside_repeated": ("max", "asides"),
    "aside_with_punch": ("max", "punches"),
    "text_over_default": ("max", "characters"),
    "beat_shorter_than_default": ("min", "s"),
    "punch_short": ("min", "s"),
    "pip_card_over_face": ("min", "px"),
    "split_band_over_face": ("min", "px"),
}


def _number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError("advice number")
    x = round(float(x), 3)
    return int(x) if x == int(x) else x


def add(rows: list, code: str, value, default, id=None) -> list:
    """Merge one finding into the row of its code in `rows` (a list this module made), in place: the worst value (its default goes with it), `count` plus one,
    and `id` appended while the row holds fewer than IDS_MAX. An id the row already holds is the same item reported again: the value is merged and the
    count stays. An id that is not of the closed pattern is left out. An unknown code is a ValueError. Returns `rows`."""
    if code not in CODES:
        raise ValueError("advice code")
    worst = CODES[code][0]
    value, default = _number(value), _number(default)
    if id is not None and not (isinstance(id, str) and ID.fullmatch(id)):
        id = None
    for row in rows:
        if row["code"] == code:
            again = id is not None and id in row.get("ids", [])
            if (value > row["value"]) if worst == "max" else (value < row["value"]):
                row["value"], row["default"] = value, default
            if not again:
                row["count"] += 1
            if id is not None and not again and len(row.setdefault("ids", [])) < IDS_MAX:
                row["ids"].append(id)
            return rows
    row = {"code": code, "value": value, "default": default, "count": 1}
    if id is not None:
        row["ids"] = [id]
    rows.append(row)
    return rows


def check_row(r) -> dict:
    """`r` if it is a closed row (a known code, finite numbers, an integer `count` of 1 or more, at most IDS_MAX ids of the closed pattern), else a ValueError."""
    if not isinstance(r, dict) or set(r) - {"code", "value", "default", "count", "ids"} or not {"code", "value", "default", "count"} <= set(r) or r["code"] not in CODES:
        raise ValueError("advice row")
    for key in ("value", "default"):
        _number(r[key])
    if isinstance(r["count"], bool) or not isinstance(r["count"], int) or r["count"] < 1:
        raise ValueError("advice count")
    ids = r.get("ids", [])
    if not isinstance(ids, list) or len(ids) > IDS_MAX or not all(isinstance(i, str) and ID.fullmatch(i) for i in ids):
        raise ValueError("advice ids")
    return r


def merge(*lists) -> list:
    """The rows of several lists as one: per code the worst value (with its default), the counts added, the ids joined (no repeat, at most IDS_MAX).
    Sorted by code. Every input row is checked (`check_row`: a ValueError for one that is not closed)."""
    out = []
    for one in lists:
        for r in one or []:
            check_row(r)
            worst = CODES[r["code"]][0]
            for row in out:
                if row["code"] == r["code"]:
                    if (r["value"] > row["value"]) if worst == "max" else (r["value"] < row["value"]):
                        row["value"], row["default"] = r["value"], r["default"]
                    row["count"] += r["count"]
                    for i in r.get("ids", []):
                        if i not in row.setdefault("ids", []) and len(row["ids"]) < IDS_MAX:
                            row["ids"].append(i)
                    break
            else:
                out.append({k: (list(v) if k == "ids" else v) for k, v in r.items()})
    return rows(out)


def rows(found) -> list:
    """The sorted list of rows (a copy), or `[]` when there is none."""
    return [{k: (list(v) if k == "ids" else v) for k, v in row.items()} for row in sorted(found or [], key=lambda r: r["code"])]
