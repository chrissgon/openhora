#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Check the closed `brand-tokens` block of a visual identity (docs/brand/identity.md).

Usage:
  python3 check_brand_tokens.py --file docs/brand/identity.md
  python3 check_brand_tokens.py --help

The block is a fenced code block whose first line is ```brand-tokens and whose body is one JSON object, closed:

  {"version": 1, "status": "draft" | "approved", "mode_default": "dark" | "light",
   "color": {"bg": {"dark": "#RRGGBB", "light": "#RRGGBB"}, "fg": {...}, "muted": {...}, "accent": {...}, "surface": {...}},
   "font": {"display": {"family": "Inter", "weight": 800}, "body": {...}, "mono": {...}}}

  - Every key is listed here; any other key is refused.
  - Colour roles: `bg`, `fg`, `muted` and `accent` are required, `surface` is optional. Each holds `dark`, `light` or both
    (a role with one value uses it); every value is `#RRGGBB`, six hex digits, nothing else.
  - Font roles: `display` and `body` are required, `mono` is optional. Each is {"family": <name>, "weight": 100..900 in
    steps of 100}. A family is a plain name (letters, digits, spaces, dots, hyphens, at most 40 characters).
  - `status` says in a word of the closed pair whether the person approved the identity. It is the machine-readable twin of
    the `Status:` line, which may be written in the document's language. The words that line may start with are a closed
    list (STATUS_WORDS): `draft` and `approved`, and in Brazilian Portuguese `rascunho`, `aprovado` and `aprovada`. A
    `Status:` line that is present and starts with another word is refused (`status_unknown`); one that agrees with the
    block's `status` passes; one that disagrees is `status_mismatch`. The block's `status` is never taken in place of a
    line that cannot be read. A document with no `Status:` line is judged by the block alone.
  - A key written twice in one object is refused (`duplicate_key`): JSON would keep the last one without a word.
  - The fence is ```brand-tokens or ~~~brand-tokens (three or more of the same character, indented or not), closed by a
    line of the same character, at least as long. A fence that names `brand-tokens` but is not closed or has more text on
    its line is a problem (`block_unclosed`, `block_fence_odd`), never ignored.
  - `version` is 1. A block with no `version` is an open block, written before this one existed: it is reported as
    `block_open`, and the reader of the pipeline uses the default theme for it and says so.
  - The block is data. Nothing in it is ever used as CSS, a path or a command.

Output: one JSON object on standard output, {"ok": true|false, "problems": [{"code": ..., "field": ...}]}; each code is a closed
word and each field a path of closed key names (`color.accent.dark`), never a value of the file. Diagnostics go to standard error.
Exit codes: 0 the block is closed and valid; 1 at least one problem; 2 a usage error or a file that cannot be read.

As a module (the pipeline of the task runtime carries a generated copy): `blocks(text)`, `scan(text)`, `parse(text)`,
`problems(obj)`, `document_status(text)`, and the constants COLOR_ROLES, OPTIONAL_COLOR_ROLES, FONT_ROLES, OPTIONAL_FONT_ROLES, MODES.
Standard library only. Runs on Python 3.9.
"""
import json
import os
import re
import sys

VERSION = 1
LIMIT = 8 * 1024                      # bytes of the block's JSON
FILE_LIMIT = 1024 * 1024              # bytes of the identity file this script reads
COLOR_ROLES = ("bg", "fg", "muted", "accent")
OPTIONAL_COLOR_ROLES = ("surface",)
FONT_ROLES = ("display", "body")
OPTIONAL_FONT_ROLES = ("mono",)
MODES = ("dark", "light")
STATUSES = ("draft", "approved")
TOP_KEYS = ("version", "status", "mode_default", "color", "font")
HEX = re.compile(r"#[0-9A-Fa-f]{6}")
FAMILY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .-]{0,39}")
KEY = re.compile(r"[a-z][a-z0-9_]{0,19}")
STATUS_LINE = re.compile(r"^- Status:[ \t]*([^\s(),;:.]*)", re.M | re.I)
STATUS_WORDS = {"draft": "draft", "approved": "approved", "rascunho": "draft", "aprovado": "approved", "aprovada": "approved"}
OPEN_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*brand-tokens\b(.*)$")


def _key(value):
    """A key of the file as a field name: only a short word of lowercase letters, digits and underscores, else `?`."""
    return value if isinstance(value, str) and KEY.fullmatch(value) else "?"


class _Duplicate(ValueError):
    """A key written twice in one JSON object."""


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _Duplicate()
        out[key] = value
    return out


def scan(text):
    """(bodies, problems): the bodies of the brand-tokens fences of a document, in order, and the fences that cannot be read as
    one (`block_fence_odd`: more text on the opening line; `block_unclosed`: no closing line). A fence opens on a line of three or
    more backticks or tildes, indented or not, followed by `brand-tokens`, and closes on a line of the same character, at least as
    long."""
    found, odd, body, mark = [], [], None, None
    for line in text.splitlines():
        if body is None:
            opened = OPEN_FENCE.match(line)
            if opened:
                if opened.group(2).strip():
                    odd.append({"code": "block_fence_odd", "field": ""})
                else:
                    body, mark = [], opened.group(1)
        elif re.fullmatch(r"[ \t]*" + re.escape(mark[0]) + "{%d,}[ \\t]*" % len(mark), line):
            found.append("\n".join(body))
            body = None
        else:
            body.append(line)
    if body is not None:
        odd.append({"code": "block_unclosed", "field": ""})
    return found, odd


def blocks(text):
    """The bodies of the readable brand-tokens fences of a document (see `scan`)."""
    return scan(text)[0]


def document_status(text):
    """The document's `- Status:` line as `draft`, `approved`, `unknown` (a line is there and starts with a word the list does not
    have) or None (no such line). The words are STATUS_WORDS."""
    found = STATUS_LINE.search(text)
    if not found:
        return None
    return STATUS_WORDS.get(found.group(1).lower(), "unknown")


def parse(text):
    """(object, problems) for the one block of a document: the object is None when no block could be read."""
    found, odd = scan(text)
    if odd:
        return None, odd[:1]
    if not found:
        return None, [{"code": "block_missing", "field": ""}]
    if len(found) > 1:
        return None, [{"code": "block_repeated", "field": ""}]
    if len(found[0].encode("utf-8")) > LIMIT:
        return None, [{"code": "block_too_large", "field": ""}]
    try:
        obj = json.loads(found[0], object_pairs_hook=_no_duplicates)
    except _Duplicate:
        return None, [{"code": "duplicate_key", "field": ""}]
    except (ValueError, RecursionError):
        return None, [{"code": "block_not_json", "field": ""}]
    if not isinstance(obj, dict):
        return None, [{"code": "block_not_object", "field": ""}]
    return obj, problems(obj)


def problems(obj):
    """The problems of a block that parsed as an object: [{"code", "field"}], empty when it is closed and valid. An open block
    (no `version`) is the one problem `block_open`, so that a reader can tell it from a closed block that is wrong."""
    if "version" not in obj:
        return [{"code": "block_open", "field": ""}]
    out = []

    def add(code, field=""):
        out.append({"code": code, "field": field})

    if obj["version"] != VERSION or isinstance(obj["version"], bool):
        add("block_version", "version")
    for key in obj:
        if key not in TOP_KEYS:
            add("unknown_key", _key(key))
    for key in TOP_KEYS[1:]:
        if key not in obj:
            add("missing_key", key)
    if "status" in obj and obj["status"] not in STATUSES:
        add("bad_status", "status")
    if "mode_default" in obj and obj["mode_default"] not in MODES:
        add("bad_mode", "mode_default")
    if "color" in obj:
        _colors(obj["color"], add)
    if "font" in obj:
        _fonts(obj["font"], add)
    return out


def _colors(colors, add):
    if not isinstance(colors, dict):
        add("bad_color", "color")
        return
    for role in colors:
        if role not in COLOR_ROLES + OPTIONAL_COLOR_ROLES:
            add("unknown_role", "color." + _key(role))
    for role in COLOR_ROLES:
        if role not in colors:
            add("missing_role", "color." + role)
    for role in COLOR_ROLES + OPTIONAL_COLOR_ROLES:
        if role not in colors:
            continue
        columns = colors[role]
        if not isinstance(columns, dict) or not columns:
            add("bad_color", "color." + role)
            continue
        for mode, value in columns.items():
            if mode not in MODES:
                add("unknown_mode", "color.%s.%s" % (role, _key(mode)))
            elif not isinstance(value, str) or not HEX.fullmatch(value):
                add("bad_color", "color.%s.%s" % (role, mode))


def _fonts(fonts, add):
    if not isinstance(fonts, dict):
        add("bad_font", "font")
        return
    for role in fonts:
        if role not in FONT_ROLES + OPTIONAL_FONT_ROLES:
            add("unknown_role", "font." + _key(role))
    for role in FONT_ROLES:
        if role not in fonts:
            add("missing_role", "font." + role)
    for role in FONT_ROLES + OPTIONAL_FONT_ROLES:
        if role not in fonts:
            continue
        spec = fonts[role]
        if not isinstance(spec, dict) or set(spec) != {"family", "weight"}:
            add("bad_font", "font." + role)
            continue
        if not isinstance(spec["family"], str) or not FAMILY.fullmatch(spec["family"]):
            add("bad_font", "font.%s.family" % role)
        weight = spec["weight"]
        if isinstance(weight, bool) or not isinstance(weight, int) or weight not in range(100, 1000, 100):
            add("bad_font", "font.%s.weight" % role)


def check_text(text):
    """The problems of a whole identity document: its block's, and a Status line that disagrees with the block's `status`."""
    obj, found = parse(text)
    if obj is not None and not found:
        line = document_status(text)
        if line == "unknown":
            found = [{"code": "status_unknown", "field": "status"}]
        elif line is not None and line != obj["status"]:
            found = [{"code": "status_mismatch", "field": "status"}]
    return found


def main(argv):
    if argv in (["--help"], ["-h"]):
        print(__doc__.strip())
        return 0
    if len(argv) != 2 or argv[0] != "--file":
        print("check_brand_tokens.py: takes --file <identity.md>; --help says more", file=sys.stderr)
        return 2
    path = argv[1]
    try:
        if os.path.getsize(path) > FILE_LIMIT:
            print("check_brand_tokens.py: the file is over %d bytes" % FILE_LIMIT, file=sys.stderr)
            return 2
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as e:
        print("check_brand_tokens.py: cannot read %s: %s" % (path, e.__class__.__name__), file=sys.stderr)
        return 2
    found = check_text(text)
    print(json.dumps({"ok": not found, "problems": found}))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
