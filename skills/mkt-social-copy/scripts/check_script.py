#!/usr/bin/env python3
"""Check the ```script block of a drafted post file against the preset vocabulary.

Usage:
  python3 check_script.py --content docs/marketing/content/2027-10-13-slug.md \
      --presets <skills folder>/../../shared/references/video-presets.json [--format reel] [--max-items 10]

The content file carries the script of a short video in one fenced block named script: beats, each a run of
`key: value` lines that starts with `beat: <n>` (numbered 1, 2, 3 ...), and beats separated by a blank line.

  beat: 1
  line: <the words the person says>
  on-screen: <the text shown: the main parameter of the beat's preset>
  preset: <a name of the vocabulary>
  <parameter>: <value>          one line per parameter the preset declares, other than its main one

A beat with no preset has only `beat` and `line`. A parameter of type image or clip is written as a short
description of what to show, never as a path or a link. A beat holds no time of any kind.

What it checks, against the vocabulary file (the one source of the presets):
  - exactly one script block; beat numbers in order; at most the vocabulary's number of beats;
  - with --format carousel or static, a beat holds only `beat` and `line` (no preset, no on-screen, no asset), a
    static post has one beat, and with --max-items a carousel has at most that many;
  - every beat has a `line`; the preset is in the vocabulary; only the parameters the preset declares are
    written; required ones are present; the main parameter is written as `on-screen`, never under its own name;
  - every value fits its type and bounds: text (length, number of items, pattern), icon, colour token and
    choice from their closed lists, an asset slot described in words;
  - an asset slot description is present, within its length, and holds no path, no link, no file name and no time;
  - no field that carries a time (start, end, at, duration ...), and no timestamp or time range in any text;
  - text hardening: every character outside the Unicode categories Cc, Cf, Zl and Zp, and text in NFC form.

Prints JSON: {"ok", "beats": [{"beat", "preset", "on_screen"}], "slots": [{"beat", "param", "type", "description"}],
"problems": [{"beat", "field", "code"}]}. A problem names the beat, the field and a closed code and never echoes
the text that was refused. "ok" is true only when there is no problem.
Exit 0 when ok, 1 when a check failed, 2 on a bad content file, a bad vocabulary file or a usage error.
Standard library only; no network.
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

FENCE = re.compile(r"^```([\w-]*)\s*$")
KEY_LINE = re.compile(r"^([a-z][a-z0-9-]{0,31}):(?: (.*))?$")
REFUSED_CATEGORIES = {"Cc", "Cf", "Zl", "Zp"}
TIME_FIELDS = {"start", "end", "at", "time", "times", "timing", "timestamp", "duration", "delay", "in", "out",
               "from", "to", "seconds", "ms", "offset", "length", "when"}
RESERVED = {"beat", "line", "on-screen", "preset"}
FORMATS = ("reel", "video", "carousel", "static")
IMAGE_FORMATS = ("carousel", "static")

# A time written inside a text: m:ss, a range of seconds, a duration in brackets.
TIMESTAMP = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
TIME_RANGE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:-|–|to)\s*\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds?|ms)\b", re.I)
TIME_BRACKET = re.compile(r"[\[(]\s*\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds?|ms)\s*[\])]", re.I)
# In a slot description, which holds no time at all: a duration with a unit, or the unit alone.
TIME_WORDS = re.compile(r"\b(?:\d+(?:\.\d+)?\s*-?\s*)?(?:ms|secs?|seconds?|minutes?|mins?|hours?|hrs?|frames?|fps)\b"
                        r"|\btimestamps?\b", re.I)
# A path, a link or a file name in a slot description.
FILE_EXTENSIONS = ("png", "jpg", "jpeg", "webp", "gif", "svg", "bmp", "tif", "tiff", "heic", "heif", "mp4", "mov", "m4v",
                   "mkv", "webm", "avi", "pdf", "csv", "tsv", "xlsx", "xls", "ods", "docx", "doc", "pptx", "ppt", "key",
                   "numbers", "pages", "txt", "md", "json", "xml", "yaml", "yml", "zip", "gz", "tar", "html", "htm")
# A backslash, a home or parent folder, a drive letter, a path that starts with / or ./, three or more segments, a
# segment with a dot extension, a file name with a known extension, or a camera-style name. A single / between words
# ("dashboard/chart", "and/or") is not path-like.
PATHLIKE = re.compile(r"[\\~]|\.\.|\b[A-Za-z]:\\|(?:^|\s)\.?/|\S+/\S+/\S+|[\w-]+\.\w{1,5}/|/[\w-]*\.\w{1,5}\b"
                      r"|\.(?:" + "|".join(FILE_EXTENSIONS) + r")\b"
                      r"|\b(?:IMG|DSC|DSCN|MVI|PXL|VID|MOV)[_-]?\d{3,}|\bScreen(?:shot|\s?Recording)\s+\d{4}", re.I)
LINKLIKE = re.compile(r"\b(?:https?|ftp|file|data|blob|javascript):|\bwww\.|\b[\w-]+\.(?:com|dev|io|org|net|app|br|ly|co|ai|me|"
                      r"example|test|local)\b", re.I)


class Problem(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def script_block(text: str) -> str:
    """The body of the one ```script block; raise ValueError on none, on several or on one that is not closed."""
    found, name, buf = [], None, []
    for line in text.split("\n"):
        m = FENCE.match(line.rstrip("\r"))
        if name is None:
            if m and m.group(1) == "script":
                name, buf = "script", []
        elif m and m.group(1) == "":
            found.append("\n".join(buf))
            name = None
        else:
            buf.append(line)
    if name is not None:
        raise ValueError("```script block is not closed")
    if not found:
        raise ValueError("no ```script block")
    if len(found) > 1:
        raise ValueError("more than one ```script block")
    return found[0]


def hardened(value: str) -> str:
    """The value, or a Problem: refused categories and not NFC. The value is already stripped."""
    for ch in value:
        if unicodedata.category(ch) in REFUSED_CATEGORIES:
            raise Problem("forbidden_character")
    if not unicodedata.is_normalized("NFC", value):
        raise Problem("not_nfc")
    return value


def plain_text(value: str, max_len: int) -> str:
    value = hardened(value.strip())
    if not value:
        raise Problem("empty_text")
    if len(value) > max_len:
        raise Problem("text_too_long")
    if TIMESTAMP.search(value) or TIME_RANGE.search(value) or TIME_BRACKET.search(value):
        raise Problem("time_value")
    return value


def text_param(value: str, spec: dict) -> str:
    items_max = spec.get("max_items", 1)
    if items_max > 1:
        items = [part.strip() for part in value.split("|")]
        if not all(items):
            raise Problem("empty_item")
        if len(items) > items_max:
            raise Problem("too_many_items")
        clean = [plain_text(item, spec["max"]) for item in items]
        out = " | ".join(clean)
    else:
        out = plain_text(value, spec["max"])
    pattern = spec.get("pattern")
    if pattern and not re.fullmatch(pattern, out):
        raise Problem("bad_pattern")
    return out


def slot_description(value: str, limits: dict) -> str:
    value = hardened(value.strip())
    if len(value) < limits["slot_description_min"]:
        raise Problem("slot_description_missing")
    if len(value) > limits["slot_description_max"]:
        raise Problem("slot_description_too_long")
    if PATHLIKE.search(value):
        raise Problem("slot_path")
    if LINKLIKE.search(value):
        raise Problem("slot_link")
    if TIME_WORDS.search(value) or TIMESTAMP.search(value):
        raise Problem("time_value")
    return value


def slot_types(spec: dict) -> list:
    kinds = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
    return [k for k in kinds if k in ("image", "clip")]


def check_value(vocab: dict, spec: dict, value: str):
    """Return the value as it is accepted, or raise a Problem."""
    kind = spec["type"]
    if slot_types(spec):
        return slot_description(value, vocab["limits"])
    if kind == "text":
        return text_param(value, spec)
    value = hardened(value.strip())
    if kind == "icon":
        allowed = vocab["icons"]
    elif kind == "color":
        allowed = vocab["palette"]
    elif kind == "choice":
        allowed = spec["values"]
    else:
        raise Problem("unknown_type")
    if value not in allowed:
        raise Problem("bad_value")
    return value


def parse(block: str):
    """Return (beats, problems): beats is a list of (number, {key: value}, {key: line_number})."""
    beats, problems, current = [], [], None
    for number, raw in enumerate(block.split("\n"), 1):
        line = raw.rstrip("\r").strip(" ")
        if not line:
            continue
        for ch in line:
            if unicodedata.category(ch) in REFUSED_CATEGORIES:
                problems.append({"beat": current["n"] if current else None, "field": f"line {number}",
                                 "code": "forbidden_character"})
                break
        else:
            m = KEY_LINE.match(line)
            if not m:
                problems.append({"beat": current["n"] if current else None, "field": f"line {number}",
                                 "code": "bad_line"})
                continue
            key, value = m.group(1), m.group(2) or ""
            if key == "beat":
                current = {"n": len(beats) + 1, "fields": {}, "declared": value.strip()}
                beats.append(current)
                continue
            if current is None:
                problems.append({"beat": None, "field": key, "code": "field_before_first_beat"})
                continue
            if key in current["fields"]:
                problems.append({"beat": current["n"], "field": key, "code": "duplicate_field"})
                continue
            current["fields"][key] = value
    return beats, problems


def check(block: str, vocab: dict, fmt=None, max_items=None):
    beats, problems = parse(block)
    out_beats, slots = [], []
    limits = vocab["limits"]
    if not beats:
        problems.append({"beat": None, "field": "beat", "code": "no_beats"})
    if len(beats) > limits["beats_max"]:
        problems.append({"beat": None, "field": "beat", "code": "too_many_beats"})
    if fmt == "static" and len(beats) > 1:
        problems.append({"beat": None, "field": "beat", "code": "static_has_one_beat"})
    if fmt in IMAGE_FORMATS and max_items is not None and len(beats) > max_items:
        problems.append({"beat": None, "field": "beat", "code": "too_many_items"})

    for b in beats:
        n, fields = b["n"], b["fields"]

        flagged = set()

        def bad(field, code):
            flagged.add(field)
            problems.append({"beat": n, "field": field, "code": code})

        if b["declared"] != str(n):
            bad("beat", "beat_number")
        if "line" not in fields:
            bad("line", "missing_line")
        else:
            try:
                plain_text(fields["line"], limits["line_max"])
            except Problem as e:
                bad("line", e.code)
        if fmt in IMAGE_FORMATS:
            for key in fields:
                if key not in ("line",):
                    bad(key, "not_in_image_format")
            out_beats.append({"beat": n, "preset": None, "on_screen": None})
            continue
        preset_name = fields.get("preset")
        spec = None
        if preset_name is not None:
            spec = vocab["presets"].get(preset_name.strip())
            if spec is None:
                bad("preset", "unknown_preset")
        main = spec["main"] if spec else None
        accepted = {}
        for key, value in fields.items():
            if key in ("line", "preset"):
                continue
            if key in TIME_FIELDS:
                bad(key, "time_field")
            elif key == "on-screen":
                if preset_name is None:
                    bad(key, "on_screen_without_preset")
                elif spec is not None:
                    try:
                        accepted[main] = check_value(vocab, spec["params"][main], value)
                    except Problem as e:
                        bad(key, e.code)
            elif spec is None:
                if preset_name is None:
                    bad(key, "parameter_without_preset")
            elif key == main:
                bad(key, "main_parameter_written_twice")
            elif key not in spec["params"]:
                bad(key, "undeclared_parameter")
            else:
                try:
                    accepted[key] = check_value(vocab, spec["params"][key], value)
                except Problem as e:
                    bad(key, e.code)
                if slot_types(spec["params"][key]) and key in accepted:
                    slots.append({"beat": n, "param": key, "type": "|".join(slot_types(spec["params"][key])),
                                  "description": accepted[key]})
        if spec is not None:
            for key, pspec in spec["params"].items():
                field = "on-screen" if key == main else key
                if pspec.get("required") and key not in accepted and field not in flagged:
                    bad(field, "missing_parameter")
        out_beats.append({"beat": n, "preset": preset_name.strip() if preset_name else None,
                          "on_screen": accepted.get(main) if main else None})
    return out_beats, slots, problems


def load_vocabulary(path: str) -> dict:
    try:
        vocab = json.loads(Path(path).read_text(encoding="utf-8"))
        assert vocab["version"] == 1 and isinstance(vocab["presets"], dict)
        for key in ("icons", "palette", "limits"):
            assert key in vocab
        for name, preset in vocab["presets"].items():
            assert preset["main"] in preset["params"], name
            for pspec in preset["params"].values():
                assert "type" in pspec
    except (OSError, ValueError, KeyError, AssertionError, TypeError) as e:
        raise ValueError(f"{path}: not a preset vocabulary ({type(e).__name__})")
    return vocab


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--content", required=True, help="the post file that holds the ```script block")
    p.add_argument("--presets", required=True, help="video-presets.json, the preset vocabulary")
    p.add_argument("--format", choices=FORMATS, default=None,
                   help="the post's format; carousel and static beats hold only `beat` and `line`, a static post one beat")
    p.add_argument("--max-items", type=int, default=None,
                   help="the most beats (images) a carousel may have, from the reference's Items: line")
    a = p.parse_args(argv)
    try:
        vocab = load_vocabulary(a.presets)
        block = script_block(Path(a.content).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # a missing file, bytes that are not UTF-8, no or a broken block
        print(f"error: {e}", file=sys.stderr)
        return 2
    beats, slots, problems = check(block, vocab, a.format, a.max_items)
    json.dump({"ok": not problems, "beats": beats, "slots": slots, "problems": problems}, sys.stdout,
              ensure_ascii=False, indent=1)
    print()
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
