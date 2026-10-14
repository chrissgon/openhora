#!/usr/bin/env python3
"""Check the ```script block of a drafted post file against the preset vocabulary.

Usage:
  python3 check_script.py --content docs/marketing/content/2027-10-13-slug.md \
      --presets <skills folder>/../../shared/references/video-presets.json [--format reel] [--max-items 10] \
      [--language <code>] [--register calm|neutral] [--material <file>]... [--figure <token>]... [--beat-only]

The content file carries the script of a short video in one fenced block named script. At its top, before the first
beat, may stand a header (script vocabulary version 2): one `key: value` line each, keys from the vocabulary's closed
list, each at most once, in any order: hook_type, title, cta_kind, send_to, loop, pattern. Then the beats, each a run of
`key: value` lines that starts with `beat: <n>` (numbered 1, 2, 3 ...), beats separated by a blank line.

  hook_type: number
  title: Three habits that matter
  cta_kind: send
  send_to: a friend who wants to save

  beat: 1
  role: hook
  line: <the words the person says>
  on-screen: <the text shown: the main parameter of the beat's preset>
  preset: <a name of the vocabulary>
  emphasis: <none | punch>
  <parameter>: <value>          one line per parameter the preset declares, other than its main one

A beat with no preset has only `beat` and `line` (and `role`, `emphasis`). A parameter of type image or clip is
written as a short description of what to show, never as a path or a link. A beat holds no time of any kind.

Two modes, decided by the script: a script with a header or with any `role` or `emphasis` is a version 2 script, and every
rule below is a refusal; a script with none of them is a legacy (version 1) script, which keeps passing: every rule that
is new in version 2 is then a warning with the same code, and `legacy_script` says the header and roles are missing.
`--beat-only` checks one beat's parameters and text only and skips the header, the roles and the script-level rules, and
rules 4 and 6 (the length of a line, the items of a list); it keeps the number beat's value against its line.

What it checks, against the vocabulary file (the one source of the presets and of the script rules):
  - exactly one script block; beat numbers in order; at most the vocabulary's number of beats;
  - with --format carousel or static, a beat holds only `beat` and `line` (no preset, no on-screen, no asset, no role),
    a static post has one beat, and with --max-items a carousel has at most that many; no header;
  - every beat has a `line`; the preset is in the vocabulary; only the parameters the preset declares are
    written; required ones are present; the main parameter is written as `on-screen`, never under its own name;
  - every value fits its type and bounds: text (length, number of items, pattern), icon, colour token and
    choice from their closed lists, an asset slot described in words;
  - an asset slot description is present, within its length, and holds no path, no link, no file name and no time;
  - no field that carries a time (start, end, at, duration ...), and no timestamp or time range in any text;
  - text hardening: every character outside the Unicode categories Cc, Cf, Zl and Zp, and text in NFC form;
  - role and emphasis are closed values; a `number` beat's `value` is a digit token of its `line`; a `list` has 2 to 4 items;
  - version 2, the eleven rules (the quality half of each is for the reader, see the skill): the header and its values;
    1 beat 1 is the hook, at most 18 words, and its hook_type's predicate; 2 the title mirrors the hook;
    3 a payoff after more than half of the beats that come before the cta holds a content word of the title; 4 a line over 30 words is refused;
    6 no preset on more than half of the beats, a number figure is a digit token of the material; 7 the roles of the
    declared pattern are present; 8 exactly one cta, last, at most 20 words, with cta_kind and, for send, send_to;
    9 with --register calm, room is left; 10 every digit token of a line is a digit token of the material
    (--material files and --figure tokens; each --figure needs a row of the post's Claims and sources table whose source is
    the user's words); emphasis `punch` at most one per three beats and 25 words apart;
  - warnings, never refusals: 1 a hook that starts with an opener phrase, a loop that ends with a goodbye word (the word
    lists are a heuristic), 4 a line under 8 words (except a turn), 5 a run of beats with no preset or punch over
    15 words, 11 the spoken words outside 150 to 225 (300 is the most, 2.5 words a second), a missing language or material.

Prints JSON: {"ok", "mode", "header", "beats": [{"beat", "preset", "on_screen", "role", "emphasis"}], "slots": [...],
"problems": [{"beat", "field", "code"}], "warnings": [{"beat", "field", "code"}]}. A problem names the beat, the field and
a closed code and never echoes the text that was refused. "ok" is true only when there is no problem; warnings never fail.
Exit 0 when ok, 1 when a check failed, 2 on a bad content file, a bad vocabulary file or a usage error.
Standard library only; no network.
"""
import argparse
import codecs
import json
import re
import sys
import unicodedata
from pathlib import Path

FENCE = re.compile(r"^```([\w-]*)\s*$")
KEY_LINE = re.compile(r"^([a-z][a-z0-9_-]{0,31}):(?: (.*))?$")
REFUSED_CATEGORIES = {"Cc", "Cf", "Zl", "Zp"}
TIME_FIELDS = {"start", "end", "at", "time", "times", "timing", "timestamp", "duration", "delay", "in", "out",
               "from", "to", "seconds", "ms", "offset", "length", "when"}
RESERVED = {"beat", "line", "on-screen", "preset", "role", "emphasis"}
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


def parse(block: str, header_keys=()):
    """Return (beats, header, problems). beats: a list of {n, fields, declared}. header: {key: value} of the lines before
    the first beat whose key is in header_keys. Any other key before the first beat is a problem."""
    beats, header, problems, current = [], {}, [], None
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
                if key in header_keys:
                    if key in header:
                        problems.append({"beat": None, "field": key, "code": "duplicate_field"})
                    else:
                        header[key] = value
                else:
                    code = "unknown_header_key" if header_keys and key not in RESERVED else "field_before_first_beat"
                    problems.append({"beat": None, "field": key, "code": code})
                continue
            if key in current["fields"]:
                problems.append({"beat": current["n"], "field": key, "code": "duplicate_field"})
                continue
            current["fields"][key] = value
    return beats, header, problems


# ---------------------------------------------------------------- the script's own rules (vocabulary version 2)

def words(text: str) -> list:
    """The words of a text: whitespace-separated tokens that hold at least one letter or digit."""
    return [t for t in text.split() if any(c.isalnum() for c in t)]


def tokens(text: str) -> list:
    """NFKC, casefold, apostrophes dropped, then the runs of letters and digits: what is compared between two texts."""
    t = unicodedata.normalize("NFKC", text).casefold()
    return re.findall(r"\w+", re.sub(r"['\u2019]", "", t))


def digit_tokens(text: str) -> list:
    """Every token that starts with a digit (digits, with . or , inside), without a trailing . or , ."""
    return [t.rstrip(".,") for t in re.findall(r"\d[\d.,]*", text)]


def norm_figure(token: str) -> str:
    """A digit token with its thousand separators dropped, so that 1.520, 1,520 and 1520 are one figure: a `.` or `,` that is
    followed by exactly three digits, in groups, is a thousand separator; any other single separator is a decimal point
    (3,5 and 3.5 are one figure); anything else is left as written."""
    token = token.rstrip(".,")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", token):
        return re.sub(r"[.,]", "", token)
    if re.fullmatch(r"\d+[.,]\d+", token):
        return token.replace(",", ".")
    return token


def first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]


def ends_with_question(text: str) -> bool:
    return text.rstrip().rstrip("\"\u201d\u00bb'\u2019)").endswith("?")


QUOTED = re.compile(r'"([^"]+)"|\u201c([^\u201d]+)\u201d|\u00ab([^\u00bb]+)\u00bb')


def quoted_spans(text: str, min_words: int) -> list:
    return [next(g for g in m.groups() if g) for m in QUOTED.finditer(text)
            if len(words(next(g for g in m.groups() if g))) >= min_words]


def language_data(script: dict, code):
    """The language's lists, or None: the code is matched ignoring case; `pt` finds `pt-BR`."""
    if not code:
        return None
    langs = {k.lower(): v for k, v in script["languages"].items()}
    want = code.lower().replace("_", "-")
    if want in langs:
        return langs[want]
    base = want.split("-")[0]
    for key, value in langs.items():
        if key == base or key.startswith(base + "-"):
            return value
    return None


def phrase_at_start(toks: list, phrase: str) -> bool:
    p = tokens(phrase)
    return bool(p) and toks[:len(p)] == p


def phrase_inside(toks: list, phrase: str) -> bool:
    p = tokens(phrase)
    return bool(p) and any(toks[i:i + len(p)] == p for i in range(len(toks) - len(p) + 1))


def check(block: str, vocab: dict, fmt=None, max_items=None, register="neutral", language=None, figures=None,
          beat_only=False):
    """Return (beats, slots, problems, warnings, extra): extra is {"mode", "header"}."""
    script = vocab.get("script")
    header_keys = tuple(script["header"]["keys"]) if script else ()
    beats, header_raw, problems = parse(block, header_keys)
    warnings = []
    out_beats, slots = [], []
    limits = vocab["limits"]
    images = fmt in IMAGE_FORMATS
    if not beats:
        problems.append({"beat": None, "field": "beat", "code": "no_beats"})
    if len(beats) > limits["beats_max"]:
        problems.append({"beat": None, "field": "beat", "code": "too_many_beats"})
    if fmt == "static" and len(beats) > 1:
        problems.append({"beat": None, "field": "beat", "code": "static_has_one_beat"})
    if images and max_items is not None and len(beats) > max_items:
        problems.append({"beat": None, "field": "beat", "code": "too_many_items"})

    # The mode: a script with a header or a role or an emphasis is version 2; any other video script is legacy.
    v2 = bool(script) and not images and not beat_only and bool(
        header_raw or any("role" in b["fields"] or "emphasis" in b["fields"] for b in beats))
    legacy = bool(script) and not images and not beat_only and not v2
    strict = v2 or beat_only or not script
    mode = "images" if images else "beat-only" if beat_only else "v2" if v2 else "legacy"

    def emit(beat, field, code):
        """A version 2 rule: a refusal in a version 2 script and in --beat-only, a warning in a legacy script."""
        (problems if strict else warnings).append({"beat": beat, "field": field, "code": code})

    def warn(beat, field, code):
        if not any(w["code"] == code and w["field"] == field and w["beat"] == beat for w in warnings):
            warnings.append({"beat": beat, "field": field, "code": code})

    if images and header_raw:
        problems.append({"beat": None, "field": "header", "code": "header_in_image_format"})
    role_values = script["roles"] if script else []
    emphasis_values = script["emphasis"] if script else []

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
        if images:
            for key in fields:
                if key not in ("line",):
                    bad(key, "not_in_image_format")
            out_beats.append({"beat": n, "preset": None, "on_screen": None, "role": None, "emphasis": None})
            continue
        role = emphasis = None
        for key, values, name in (("role", role_values, "role"), ("emphasis", emphasis_values, "emphasis")):
            if key in fields and script:
                try:
                    value = hardened(fields[key].strip())
                except Problem as e:
                    bad(key, e.code)
                    continue
                if value not in values:
                    bad(key, "bad_value")
                elif key == "role":
                    role = value
                else:
                    emphasis = value
        preset_name = fields.get("preset")
        spec = None
        if preset_name is not None:
            spec = vocab["presets"].get(preset_name.strip())
            if spec is None:
                bad("preset", "unknown_preset")
        main = spec["main"] if spec else None
        accepted = {}
        for key, value in fields.items():
            if key in ("line", "preset") or (script and key in ("role", "emphasis")):
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
        b.update(role=role, emphasis=emphasis, preset=preset_name.strip() if preset_name else None, accepted=accepted,
                 line=fields.get("line", "").strip(), ok_line="line" not in flagged)
        out_beats.append({"beat": n, "preset": b["preset"], "on_screen": accepted.get(main) if main else None,
                          "role": role, "emphasis": emphasis})

    if images or not script or not beats:
        return out_beats, slots, problems, warnings, {"mode": mode, "header": {}}

    # ---- the beat-level rules of version 2. --beat-only keeps only the number predicate (A6): rules 4 and 6 are about the
    # shape of a whole script, so a one-beat check skips the line length and the number of list items.
    for b in beats:
        n = b["n"]
        if b["preset"] == "number" and "value" in b["accepted"] and b["ok_line"]:
            if norm_figure(b["accepted"]["value"]) not in {norm_figure(t) for t in digit_tokens(b["line"])}:
                emit(n, "value", "number_value_not_in_line")
        if beat_only:
            continue
        if b["preset"] == "list" and "items" in b["accepted"]:
            count = len(b["accepted"]["items"].split(" | "))
            low, high = script["limits"]["list_items"]
            if not low <= count <= high:
                emit(n, "on-screen", "list_items")
        if b["ok_line"]:
            w = len(words(b["line"]))
            if w > script["limits"]["line_words_max"]:
                emit(n, "line", "line_too_long_words")
            elif w < script["limits"]["line_words_min"] and b["role"] != "turn":
                warn(n, "line", "line_short")
    if beat_only:
        return out_beats, slots, problems, warnings, {"mode": mode, "header": {}}

    # ---- the script-level rules of version 2
    lim = script["limits"]
    rate = script["speech_rate_words_per_second"]
    lines = [b["line"] if b["ok_line"] else "" for b in beats]
    total_words = sum(len(words(t)) for t in lines)
    if legacy:
        warn(None, "header", "legacy_script")
    hdr = {}
    hspec = script["header"]
    for key, value in header_raw.items():
        try:
            if key in ("title", "send_to"):
                hdr[key] = plain_text(value, lim["title_max"] if key == "title" else lim["send_to_max"])
            else:
                value = hardened(value.strip())
                if value not in hspec[key]:
                    raise Problem("bad_value")
                hdr[key] = value
        except Problem as e:
            problems.append({"beat": None, "field": key, "code": e.code})
    lang = language_data(script, language)

    def need_language(beat, field):
        if lang is None:
            warn(None, "language", "language_unset" if not language else "language_data_missing")
            return False
        return True

    ctas = [b for b in beats if b["role"] == "cta"]
    if v2:
        for key in hspec["required"]:
            if key not in header_raw:
                problems.append({"beat": None, "field": key, "code": "missing_header"})
        if ctas and "cta_kind" not in header_raw:
            problems.append({"beat": None, "field": "cta_kind", "code": "missing_header"})
        if hdr.get("cta_kind") == "send" and "send_to" not in header_raw:
            problems.append({"beat": None, "field": "send_to", "code": "missing_header"})
        if "send_to" in header_raw and "cta_kind" in hdr and hdr["cta_kind"] != "send":
            problems.append({"beat": None, "field": "send_to", "code": "send_to_without_send"})

        for b in beats:
            if b["role"] is None and not any(p["beat"] == b["n"] and p["field"] == "role" for p in problems):
                problems.append({"beat": b["n"], "field": "role", "code": "missing_role"})
        if beats[0]["role"] is not None and beats[0]["role"] != "hook":
            problems.append({"beat": 1, "field": "role", "code": "first_beat_not_hook"})
        for b in beats[1:]:
            if b["role"] == "hook":
                problems.append({"beat": b["n"], "field": "role", "code": "hook_not_first"})

        # rule 1: open with the promise
        first = beats[0]
        if first["role"] == "hook" and first["ok_line"]:
            hook_toks = tokens(first["line"])
            if len(words(first["line"])) > lim["hook_words_max"]:
                problems.append({"beat": 1, "field": "line", "code": "hook_too_long"})
            if need_language(1, "line") and any(phrase_at_start(hook_toks, o) for o in lang["openers"]):
                warn(1, "line", "hook_opener")
            kind = hdr.get("hook_type")
            if kind == "number" and not digit_tokens(first_sentence(first["line"])):
                problems.append({"beat": 1, "field": "line", "code": "hook_type_number"})
            elif kind == "question" and not ends_with_question(first["line"]):
                problems.append({"beat": 1, "field": "line", "code": "hook_type_question"})
            elif kind in ("mistake", "contrarian") and need_language(1, "line") \
                    and not set(hook_toks) & set(tokens(" ".join(lang["negations"]))):
                problems.append({"beat": 1, "field": "line", "code": "hook_type_negation"})

            # rule 2: the title mirrors the key phrase
            if "title" in hdr:
                title_toks = tokens(hdr["title"])
                low, high = lim["title_words"]
                if not low <= len(title_toks) <= high:
                    problems.append({"beat": None, "field": "title", "code": "title_length"})
                if not set(title_toks) <= set(hook_toks):
                    problems.append({"beat": None, "field": "title", "code": "title_not_in_hook"})
            if "on-screen" in first["fields"] and first["preset"] in vocab["presets"]:
                text = first["accepted"].get(vocab["presets"][first["preset"]]["main"], "")
                mirrored = [t for t in tokens(text) if t in set(hook_toks)]
                low, high = lim["hook_on_screen_words"]
                if not low <= len(mirrored) <= high:
                    problems.append({"beat": 1, "field": "on-screen", "code": "hook_on_screen_mirror"})

        # rule 3: open a loop, close it late
        payoffs = [b for b in beats if b["role"] == "payoff"]
        before_cta = len(beats) if not ctas else min(b["n"] for b in ctas) - 1      # only the beats before the CTA count
        if not payoffs:
            problems.append({"beat": None, "field": "role", "code": "no_payoff"})
        else:
            late = [b for b in payoffs if b["n"] - 1 > before_cta * lim["payoff_after_share"]]
            if not late:
                problems.append({"beat": payoffs[0]["n"], "field": "role", "code": "payoff_too_early"})
            elif "title" in hdr and need_language(None, "title"):
                stop = set(tokens(" ".join(lang["stop_words"])))
                content = [t for t in tokens(hdr["title"]) if t not in stop] or tokens(hdr["title"])
                if not any(set(content) & set(tokens(b["line"])) for b in late if b["ok_line"]):
                    problems.append({"beat": late[0]["n"], "field": "line", "code": "payoff_misses_title"})

        # rule 8: end on one CTA
        if len(ctas) != 1:
            problems.append({"beat": None, "field": "role", "code": "cta_count"})
        for b in ctas:
            if b["n"] != len(beats):
                problems.append({"beat": b["n"], "field": "role", "code": "cta_not_last"})
            if b["ok_line"] and len(words(b["line"])) > lim["cta_words_max"]:
                problems.append({"beat": b["n"], "field": "line", "code": "cta_too_long"})

        # a loop ends with no goodbye
        if hdr.get("loop") == "yes" and beats[-1]["ok_line"] and need_language(len(beats), "line") \
                and any(phrase_inside(tokens(beats[-1]["line"]), g) for g in lang["goodbyes"]):
            warn(len(beats), "line", "loop_goodbye")

        # emphasis: at most one punch in three beats, and a pause between two
        punches = [b["n"] for b in beats if b["emphasis"] == "punch"]
        gap_words = round(lim["punch_gap_seconds"] * rate)
        for earlier, later in zip(punches, punches[1:]):
            if later - earlier < lim["punch_gap_beats"]:
                problems.append({"beat": later, "field": "emphasis", "code": "punch_too_dense"})
            elif sum(len(words(t)) for t in lines[earlier - 1:later - 1]) < gap_words:
                problems.append({"beat": later, "field": "emphasis", "code": "punch_too_close"})

    # rule 4 and 6 and 7 and 9 and 10 apply to a legacy script as warnings
    # rule 5: a visual event at least every 6 s (a warning always)
    gap = round(lim["visual_gap_seconds"] * rate)
    run_words, run_start = 0, None
    for b in beats + [None]:
        if b is not None and not b["preset"] and b["emphasis"] != "punch":
            if run_start is None:
                run_start = b["n"]
            run_words += len(words(b["line"]))
            continue
        if run_start is not None and run_words > gap:
            warn(run_start, "line", "visual_gap")
        run_words, run_start = 0, None

    # rule 6: vary the presets
    counts = {}
    for b in beats:
        if b["preset"]:
            counts[b["preset"]] = counts.get(b["preset"], 0) + 1
    if any(count > len(beats) * lim["preset_share_max"] for count in counts.values()):
        emit(None, "preset", "preset_overused")

    # rule 7: match the pattern to the roles
    pattern = hdr.get("pattern")
    if pattern:
        row = script["patterns"].get(pattern, {})
        present = {b["role"] for b in beats}
        if any(r not in present for r in row.get("roles", [])) or (row.get("any_of") and not present & set(row["any_of"])):
            emit(None, "pattern", "pattern_role_missing")
        for name, need in row.get("presets", {}).items():
            if counts.get(name, 0) < need:
                emit(None, "pattern", "pattern_preset_missing")
        if row.get("points_from_hook_digit"):
            digits = digit_tokens(beats[0]["line"]) if beats[0]["ok_line"] else []
            if digits and re.fullmatch(r"\d{1,2}", digits[0]) and \
                    sum(1 for b in beats if b["role"] == "point") < int(digits[0]):
                emit(None, "pattern", "pattern_points_missing")

    # rule 9: the register leaves room
    if register == "calm":
        allowed = max(1, total_words // lim["calm_words_per_preset"])
        if sum(counts.values()) > allowed:
            emit(None, "preset", "calm_preset_density")
        for b in beats:
            if b["role"] in ("turn", "payoff") and b["emphasis"] == "punch":
                emit(b["n"], "emphasis", "calm_emphasis")
            if b["ok_line"] and quoted_spans(b["line"], lim["quote_words_min"]):
                if b["preset"] != "quote":
                    emit(b["n"], "preset", "calm_quote_preset")
                elif "author" not in b["accepted"]:
                    emit(b["n"], "author", "calm_quote_author")

    # rule 10: no invented facts, and a number's figure is in the material
    if figures is None:
        warn(None, "material", "material_missing")
    else:
        for b in beats:
            if b["ok_line"] and any(norm_figure(t) not in figures for t in digit_tokens(b["line"])):
                emit(b["n"], "line", "invented_figure")
            if b["preset"] == "number" and "value" in b["accepted"] and norm_figure(b["accepted"]["value"]) not in figures:
                emit(b["n"], "value", "figure_not_in_material")

    # rule 11: length (a warning, never a refusal)
    low, high = (round(s * rate) for s in lim["target_seconds"])
    if total_words < low:
        warn(None, "line", "length_short")
    elif total_words > round(lim["max_seconds"] * rate):
        warn(None, "line", "length_over_max")
    elif total_words > high:
        warn(None, "line", "length_long")
    return out_beats, slots, problems, warnings, {"mode": mode, "header": hdr}


def load_vocabulary(path: str) -> dict:
    try:
        vocab = json.loads(Path(path).read_text(encoding="utf-8"))
        assert vocab["version"] in (1, 2) and isinstance(vocab["presets"], dict)
        for key in ("icons", "palette", "limits"):
            assert key in vocab
        for name, preset in vocab["presets"].items():
            assert preset["main"] in preset["params"], name
            for pspec in preset["params"].values():
                assert "type" in pspec
        if vocab["version"] == 2:
            script = vocab["script"]
            assert isinstance(script["speech_rate_words_per_second"], (int, float)) and script["speech_rate_words_per_second"] > 0
            for key in ("roles", "emphasis", "limits", "patterns", "languages"):
                assert key in script
            for key in ("keys", "required", "hook_type", "cta_kind", "loop", "pattern"):
                assert isinstance(script["header"][key], list)
            for key in ("title_words", "title_max", "send_to_max", "hook_words_max", "hook_on_screen_words", "line_words_min",
                        "line_words_max", "cta_words_max", "payoff_after_share", "visual_gap_seconds", "punch_gap_seconds",
                        "punch_gap_beats", "preset_share_max", "list_items", "calm_words_per_preset", "quote_words_min",
                        "target_seconds", "max_seconds"):
                assert key in script["limits"], key
            for data in script["languages"].values():
                for key in ("openers", "negations", "stop_words", "goodbyes"):
                    assert isinstance(data[key], list)
        else:
            vocab.pop("script", None)
    except (OSError, ValueError, KeyError, AssertionError, TypeError) as e:
        raise ValueError(f"{path}: not a preset vocabulary ({type(e).__name__})")
    return vocab


MATERIAL_MAX_BYTES = 2 * 1024 * 1024


def claim_figures(text: str) -> set:
    """The normalised figures of the rows of a Markdown table (in the post file) whose source cell says `the user's words`:
    the row is `| claim | source |`, the figures are the digit tokens of the claim cell."""
    found = set()
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.strip().startswith("|") and len(cells) >= 2 and "user's words" in cells[-1].replace("\u2019", "'").casefold():
            found.update(norm_figure(t) for t in digit_tokens(cells[0]))
    return found


def read_figures(paths, tokens_given):
    """(figures, warnings): the normalised digit tokens of the material files and of the --figure values, None when neither
    was given. A file that is not UTF-8 text is skipped with `material_unreadable`; a file over MATERIAL_MAX_BYTES is read up to
    the last whitespace before the limit (never inside a character or a figure) with `material_truncated`. A file that cannot
    be opened at all raises OSError."""
    warnings, found, used = [], set(), False
    for path in paths:
        with open(path, "rb") as fh:
            raw = fh.read(MATERIAL_MAX_BYTES + 1)
        cut = len(raw) > MATERIAL_MAX_BYTES
        if cut:
            raw = raw[:MATERIAL_MAX_BYTES]
        try:
            if cut:
                # stop before a character that the cut split, then before a word the cut split
                text = codecs.getincrementaldecoder("utf-8")().decode(raw, final=False)
                text = text[:max(text.rfind(" "), text.rfind("\n"), text.rfind("\t"), 0)]
            else:
                text = raw.decode("utf-8")
        except UnicodeDecodeError:
            warnings.append({"beat": None, "field": "material", "code": "material_unreadable"})
            continue
        if cut:
            warnings.append({"beat": None, "field": "material", "code": "material_truncated"})
        if "\x00" in text:
            warnings.append({"beat": None, "field": "material", "code": "material_unreadable"})
            continue
        used = True
        found.update(norm_figure(t) for t in digit_tokens(text))
    for value in tokens_given:
        used = True
        found.update(norm_figure(t) for t in digit_tokens(value))
    return (found if used else None), warnings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--content", required=True, help="the post file that holds the ```script block")
    p.add_argument("--presets", required=True, help="video-presets.json, the preset vocabulary")
    p.add_argument("--format", choices=FORMATS, default=None,
                   help="the post's format; carousel and static beats hold only `beat` and `line`, a static post one beat")
    p.add_argument("--max-items", type=int, default=None,
                   help="the most beats (images) a carousel may have, from the reference's Items: line")
    p.add_argument("--language", default=None,
                   help="the post's language code (en, pt-BR); the predicates that read word lists need it")
    p.add_argument("--register", choices=("calm", "neutral"), default="neutral",
                   help="the voice's register, from docs/brand/voice.md; calm leaves room (rule 9)")
    p.add_argument("--material", action="append", default=[],
                   help="a file of the material; every digit token of a spoken line must be in one of them (repeatable)")
    p.add_argument("--figure", action="append", default=[],
                   help="a figure the user stated that no material file holds (repeatable)")
    p.add_argument("--beat-only", action="store_true",
                   help="check one beat's parameters and text only: no header, roles or script-level rules")
    a = p.parse_args(argv)
    try:
        vocab = load_vocabulary(a.presets)
        post_text = Path(a.content).read_text(encoding="utf-8")
        block = script_block(post_text)
        figures, extra_warnings = read_figures(a.material, a.figure)
    except (OSError, ValueError) as e:  # a missing file, bytes that are not UTF-8, no or a broken block
        print(f"error: {e}", file=sys.stderr)
        return 2
    beats, slots, problems, warnings, extra = check(block, vocab, a.format, a.max_items, a.register, a.language,
                                                    figures, a.beat_only)
    claimed = claim_figures(post_text)
    for value in a.figure:
        tokens = digit_tokens(value)
        if not tokens or any(norm_figure(t) not in claimed for t in tokens):
            problems.append({"beat": None, "field": "figure", "code": "figure_without_claims_row"})
    json.dump({"ok": not problems, "mode": extra["mode"], "header": extra["header"], "beats": beats, "slots": slots,
               "problems": problems, "warnings": extra_warnings + warnings}, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
