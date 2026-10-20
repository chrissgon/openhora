#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The interpreter's protocol and its validator (package IX-2a): what a model may say about a person's line, and what code believes of it (plan `PLAN-NL-INTERPRETER-FINAL.md`, section 1).

Pure: the clock is passed in, nothing is read but the prompt and the protocol files beside this one, nothing is stored, logged, sent or printed, and no model is called here.
The model reads a line and returns ONE JSON object (protocol 1); this module parses it, checks every part of it against the line and the frame, and returns a decision that
code acts on. Nothing the model writes is ever shown to a person, and nothing it says is believed until a check has passed. The checks are the security of the layer:

  parse(text)                   (object | None, "ok" | "fenced" | "invalid" | "none", error code | None): one JSON object, at most `max_output_bytes`, optionally in one
                                ```json fence; a repeated key, an unknown key, NaN, a wrong type or `v` other than 1 is refused
  check(obj, line, frame, catalog, now, zone, allowed)
                                the decision (below). Operations go through `natural.check_operation`, UNCHANGED (the same checks as the router's outcome): a span is a
                                piece of the line, an integer is written in the line, an address is a word the sender typed
  precheck(line)                the decision for a line that must not be sent (too long), else None
  time_source(span, now, zone)  "code" | "ask" | "model": who may decide the time of a span. Code alone decides (a model never reports a language and so never
                                unlocks its own time): "code" when `natural_time.parse` reads the span as one clear reading, "ask" when it holds a time the code
                                half-reads or doubts, "model" when no table knows the words (or the code reads only an hour and the span holds words no table has)
  frame_problems(frame, catalog)  the problems of a typed frame (schema and rules R1-R7), as a list of sentences that never repeat a value
  typed_frame(items, last, labels)  the only way to build a frame: it copies the keys of the schema and nothing else
  build_messages(catalog, now, zone, frame, line)  (system, user): the prompt with the catalog, and exactly five lines
  render_catalog(catalog), prompt_sha256(), PROTOCOL

The decision, always {"kind", "error"} plus, by kind:
  op        op, args {parameter: value}, spans {slot: span}, time {local "YYYY-MM-DDTHH:MM", source "code"|"model"} | None, inherited [slots], time_disagree
  answer    item (the id), need, and what the item's need asks: slot / span / args, confirm, option, time, time_disagree
  clarify   slot | ops (code writes the question), why: model | time-ask | time-past | time-far | time-gap | time-fold | weekday | private-route | invalid | long-line
  route     none
  refuse    class D | G, op            refuse_policy   op
`error` is None or one of E_JSON, E_SIZE, E_SHAPE, E_VERSION, E_OP_UNKNOWN, E_SLOT_UNKNOWN, E_SPAN, E_INT, E_TIME_FORMAT, E_WEEKDAY, E_ITEM_UNKNOWN, E_INHERIT; any of them
but E_WEEKDAY gives a `clarify` with why `invalid` (never an op).

Python 3.9, standard library only. `python3 runtime/interpreter.py --help` prints this text.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import unicodedata
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import natural  # noqa: E402  (the same folder: the operations, their slots and `check_operation`, which this module calls unchanged)
import natural_time as nt  # noqa: E402  (the same folder: the time reader whose reading wins over the model's)

PROMPT_FILE = os.path.join(HERE, "interpreter_prompt.txt")
PROTOCOL_FILE = os.path.join(HERE, "interpreter_protocol.json")
PLACEHOLDER = "{{CATALOG}}"
with open(PROTOCOL_FILE, encoding="utf-8") as _handle:
    PROTOCOL = json.load(_handle)

# The slots that hold a time: (operation, slot). The model gives them `time_iso` and `weekday`; code decides who is believed (`time_source`).
TIME_SLOTS = frozenset({("remind", "when"), ("event-create", "time"), ("event-change", "time")})
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")        # the weekday of the `today:` line: fixed, never the locale's
FAR_DAYS = 366                 # a time further away than this is asked back
SPAN_MAX = natural.SPAN_MAX
KNOWN_MIN = 3                  # a word shorter than this is never taken as proof that a span is in a language the tables know ("a", "de", "o")
WHYS = ("model", "time-ask", "time-past", "time-far", "time-gap", "time-fold", "weekday", "private-route", "invalid", "long-line")
ERRORS = ("E_JSON", "E_SIZE", "E_SHAPE", "E_VERSION", "E_OP_UNKNOWN", "E_SLOT_UNKNOWN", "E_SPAN", "E_INT", "E_TIME_FORMAT", "E_WEEKDAY", "E_ITEM_UNKNOWN", "E_INHERIT")

OP_RE = re.compile(r"[a-z][a-z0-9-]{0,39}")
SLOT_RE = re.compile(r"[a-z][a-z0-9_]{0,23}")
ID_RE = re.compile(r"i[1-9]")
CODE_RE = re.compile(r"[a-z0-9:._-]{1,64}")
TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
FENCE_RE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n?```", re.S)
INTS_RE = re.compile(r"[0-9]{1,9}(?:,[0-9]{1,9})*")
LINE_BREAKS = re.compile(r"\s+")           # every run of white space, line separators included (str `\s` holds U+0085, U+2028 and U+2029)

KINDS = ("op", "answer", "clarify", "route", "none")
# The keys of each kind: (required, optional). Anything else is refused.
KEYS = {"op": ({"v", "kind", "op", "slots"}, {"time_iso", "weekday", "inherit"}),
        "answer": ({"v", "kind", "answers_item"}, {"slot", "span", "time_iso", "weekday", "confirm", "option"}),
        "clarify": ({"v", "kind"}, {"slot", "ops"}),
        "route": ({"v", "kind"}, set()),
        "none": ({"v", "kind"}, set())}
FRAME_KINDS = ("write-draft", "reminder-confirm", "router-question", "choice")
FRAME_NEEDS = ("slot", "confirm", "option", "text")
ITEM_KEYS = {"id", "kind", "op", "need", "slot", "options", "values", "words", "age_s"}
ITEM_REQUIRED = {"id", "kind", "need", "age_s"}
MAX_ITEMS = 5
MAX_WORDS = 6
WORDS_MAX = 300
LABEL_MAX = 60


# --- the files ----------------------------------------------------------------------------------------------------------------------------------------

def canonical(obj) -> bytes:
    """The canonical JSON of an object (the form every hash of the interpreter is taken over)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def prompt_template() -> str:
    with open(PROMPT_FILE, encoding="utf-8") as handle:
        return handle.read()


def prompt_sha256() -> str:
    """The sha256 of the prompt file's bytes: the version of the prompt (it is tuned only against the dev split, then frozen by this hash)."""
    with open(PROMPT_FILE, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


# --- the catalog as the model reads it, and the two messages ---------------------------------------------------------------------------------------

def render_catalog(catalog: dict) -> str:
    """One line per op `- {op} [{class}] {what}; slots: {slot}:{kind}, ...`, then `refused:` and one line per refused op `- {op} [refused {class}] {what}`."""
    lines = []
    for row in catalog["ops"]:
        slots = ", ".join(f"{slot}:{kind}" for slot, kind in row["slots"].items()) or "none"
        lines.append(f"- {row['op']} [{row['class']}] {row['what']}; slots: {slots}")
    lines.append("refused:")
    for row in catalog["refused"]:
        lines.append(f"- {row['op']} [refused {row['class']}] {row['what']}")
    return "\n".join(lines)


def _local_now(now, zone):
    """`now` as an aware datetime in the project's zone (a naive one is read as that zone's wall clock)."""
    tz = ZoneInfo(zone)
    if not isinstance(now, datetime.datetime):
        raise ValueError("now is a datetime")
    return now.replace(tzinfo=tz) if now.tzinfo is None else now.astimezone(tz)


def collapse(text: str) -> str:
    """The line as the model reads it: outer white space off, every inner run (a line break included) one space, so that the user message stays five lines."""
    return LINE_BREAKS.sub(" ", text).strip()


def build_messages(catalog: dict, now, zone: str, frame, line: str) -> tuple:
    """(system, user). `system` is the prompt with the rendered catalog and so is constant per (prompt, catalog); `user` is exactly five lines: today, time, zone, the
    frame as canonical JSON (or null) and the line. Nothing else ever enters either message. ValueError for a frame that is not valid or a line that is empty or too long."""
    template = prompt_template()
    if template.count(PLACEHOLDER) != 1:
        raise ValueError("the prompt holds the catalog placeholder exactly once")
    if not isinstance(line, str) or not collapse(line):
        raise ValueError("the line is empty")
    seen = collapse(line)
    if len(seen) > PROTOCOL["max_line_chars"]:
        raise ValueError("the line is too long to be sent")
    problems = frame_problems(frame, catalog)
    if problems:
        raise ValueError("the frame is not valid: " + "; ".join(problems))
    local = _local_now(now, zone)
    frame_text = "null" if frame is None else canonical(frame).decode("utf-8")
    if LINE_BREAKS.search(frame_text.replace(" ", "")):
        raise ValueError("the frame holds a line break")
    system = template.replace(PLACEHOLDER, render_catalog(catalog), 1)
    user = "\n".join([f"today: {local.strftime('%Y-%m-%d')} {DAY_NAMES[local.weekday()]}", f"time: {local.strftime('%H:%M')}", f"zone: {zone}", f"frame: {frame_text}", f"line: {seen}"])
    return system, user


# --- the typed frame ----------------------------------------------------------------------------------------------------------------------------------

def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _words_problems(words, where: str, row: dict, out: list) -> None:
    if not isinstance(words, dict) or len(words) > MAX_WORDS:
        out.append(f"{where}: words is an object of at most {MAX_WORDS} slots")
        return
    for slot, value in words.items():
        if not isinstance(slot, str) or not SLOT_RE.fullmatch(slot):
            out.append(f"{where}: a words key is not a slot name")
        elif row is not None and slot not in row:
            out.append(f"{where}: words holds a slot ({slot}) that the op does not have")      # R5
        if not isinstance(value, str) or not 1 <= len(value) <= WORDS_MAX:
            out.append(f"{where}: a words value is a string of 1 to {WORDS_MAX} characters")
        elif LINE_BREAKS.search(value.replace(" ", "")):
            out.append(f"{where}: a words value holds a line break")


def frame_problems(frame, catalog=None) -> list:
    """The problems of a frame, as sentences that name a place and never repeat a value (a hostile string must not be echoed): the schema of
    `evals/interpreter/frame.schema.json` and the rules R1 to R7 that code can check (R4, that a label comes only from the accepted configuration, is a property of
    `typed_frame`; R7, that no string is third-party text, is the builder's too, and here a string with a line break is a problem). `None` is a valid frame (no open item);
    with `catalog` None the rules that need the catalog's rows are skipped."""
    if frame is None:
        return []
    rows = None if catalog is None else {row["op"]: row["slots"] for row in catalog["ops"]}
    out: list = []
    if not isinstance(frame, dict):
        return ["the frame is an object"]
    if set(frame) != {"v", "items", "last"}:
        return ["the frame has exactly the keys v, items and last"]
    if not _is_int(frame["v"]) or frame["v"] != 1:
        out.append("v is 1")
    items = frame["items"]
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        return out + [f"items is a list of at most {MAX_ITEMS}"]
    seen_ids, kinds = set(), {}
    for n, item in enumerate(items):
        where = f"item {n}"
        if not isinstance(item, dict) or not ITEM_REQUIRED <= set(item) or set(item) - ITEM_KEYS:
            out.append(f"{where}: an object with the keys id, kind, need and age_s, and optionally op, slot, options, values and words")
            continue
        if not isinstance(item["id"], str) or not ID_RE.fullmatch(item["id"]):
            out.append(f"{where}: id is i1 to i9")
        elif item["id"] in seen_ids:
            out.append(f"{where}: id repeats")          # R6
        else:
            seen_ids.add(item["id"])
        kind, need = item["kind"], item["need"]
        if kind not in FRAME_KINDS:
            out.append(f"{where}: kind is not one of the four")
            continue
        if need not in FRAME_NEEDS:
            out.append(f"{where}: need is not one of the four")
            continue
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind != "choice" and kinds[kind] > 1:
            out.append(f"{where}: more than one item of kind {kind}")          # R6
        if not _is_int(item["age_s"]) or not 0 <= item["age_s"] <= 86400:
            out.append(f"{where}: age_s is 0 to 86400")
        op = item.get("op")
        if "op" in item and (not isinstance(op, str) or not OP_RE.fullmatch(op)):
            out.append(f"{where}: op is an op name")
            op = None
        row = rows.get(op) if rows is not None and op is not None else None
        if kind == "router-question":          # R1
            if set(item) != ITEM_REQUIRED or need != "text":
                out.append(f"{where}: a router item is its id, kind, need (text) and age only")
            continue
        if kind in ("write-draft", "reminder-confirm"):          # R2
            if op is None:
                out.append(f"{where}: a {kind} carries op")
            elif rows is not None and row is None:
                out.append(f"{where}: op is not an op of the catalog")
            if kind == "reminder-confirm" and op != "remind":
                out.append(f"{where}: a reminder-confirm has op remind")
        if need == "slot":          # R3
            slot = item.get("slot")
            if not isinstance(slot, str) or not SLOT_RE.fullmatch(slot) or op is None:
                out.append(f"{where}: need slot carries a slot and an op")
            elif row is not None and slot not in row:
                out.append(f"{where}: slot is not a slot of the op")
        elif "slot" in item:
            out.append(f"{where}: only need slot carries a slot")
        if need == "option":
            options = item.get("options")
            if kind != "choice" or not _is_int(options) or not 2 <= options <= 9:
                out.append(f"{where}: need option is a choice with options 2 to 9")
            elif "values" in item and not (isinstance(item["values"], list) and [v.get("n") if isinstance(v, dict) else None for v in item["values"]] == list(range(1, options + 1))):
                out.append(f"{where}: values are absent or numbered 1 to options")          # R3
        elif "options" in item:
            out.append(f"{where}: only need option carries options")
        if "values" in item:
            if not isinstance(item["values"], list) or len(item["values"]) > 9:
                out.append(f"{where}: values is a list of at most 9")
            else:
                for value in item["values"]:
                    if (not isinstance(value, dict) or set(value) - {"n", "code", "label"} or not {"n", "label"} <= set(value) or not _is_int(value["n"]) or not 1 <= value["n"] <= 9
                            or not isinstance(value["label"], str) or not 1 <= len(value["label"]) <= LABEL_MAX or LINE_BREAKS.search(value["label"].replace(" ", ""))
                            or ("code" in value and not (isinstance(value["code"], str) and CODE_RE.fullmatch(value["code"])))):
                        out.append(f"{where}: a value is {{n, label}} with an optional code")
                        break
        if "words" in item:
            _words_problems(item["words"], where, row, out)
    last = frame["last"]
    if last is not None:
        if not isinstance(last, dict) or set(last) != {"op", "words", "age_s"}:
            out.append("last has exactly the keys op, words and age_s")
        else:
            if not isinstance(last["op"], str) or not OP_RE.fullmatch(last["op"]) or (rows is not None and last["op"] not in rows):
                out.append("last: op is an op of the catalog")
            if not _is_int(last["age_s"]) or not 0 <= last["age_s"] <= 3600:
                out.append("last: age_s is 0 to 3600")
            _words_problems(last["words"], "last", rows.get(last["op"]) if rows is not None and isinstance(last["op"], str) else None, out)
    return out


def _clean(text) -> str:
    return collapse(text) if isinstance(text, str) else ""


def typed_frame(items, last, labels) -> dict:
    """The frame, built by a whitelist: only the keys of the schema are copied, whatever else an item carries (a subject, a file name, a router's question, the body of a
    card) is left behind. `labels` is the accepted configuration's map {code (or the option number as text): label}: a value's label comes from it and never from an item.
    A word is copied only from the field `own_words` of an item (and of `last`), which the caller sets from what the same sender typed; an item's `words` is never read. An item
    older than a day and a `last` older than an hour are left out. ValueError (with no value in it) when what is left is not a valid frame."""
    if not isinstance(labels, dict):
        raise ValueError("labels is the accepted configuration's map")
    built = []
    for item in items or []:
        if not isinstance(item, dict):
            raise ValueError("an item is an object")
        age = item.get("age_s")
        if _is_int(age) and age > 86400:
            continue
        out = {key: item[key] for key in ("id", "kind", "need", "age_s") if key in item}
        for key in ("op", "slot", "options"):
            if key in item:
                out[key] = item[key]
        if isinstance(item.get("values"), list):
            values = []
            for value in item["values"]:
                if not isinstance(value, dict):
                    raise ValueError("a value is an object")
                code = value.get("code")
                label = labels.get(code) if isinstance(code, str) else labels.get(str(value.get("n")))
                entry = {"n": value.get("n"), "label": _clean(label)}
                if isinstance(code, str):
                    entry["code"] = code
                values.append(entry)
            out["values"] = values
        words = _own_words(item.get("own_words"))
        if words:
            out["words"] = words
        if out.get("kind") == "router-question":
            out = {key: out[key] for key in ("id", "kind", "need", "age_s") if key in out}
        built.append(out)
    kept = None
    if isinstance(last, dict) and _is_int(last.get("age_s")) and last["age_s"] <= 3600:
        kept = {"op": last.get("op"), "words": _own_words(last.get("own_words")) or {}, "age_s": last["age_s"]}
    frame = {"v": 1, "items": built[:MAX_ITEMS], "last": kept}
    problems = frame_problems(frame, None)
    if problems:
        raise ValueError("the typed frame is not valid: " + "; ".join(problems))
    return frame


def _own_words(given) -> dict:
    """The words the caller marked as the sender's own, a slot at a time: a string of 1 to 300 characters under a slot name; the first six by name."""
    out = {}
    if isinstance(given, dict):
        for slot in sorted(k for k in given if isinstance(k, str) and SLOT_RE.fullmatch(k)):
            value = _clean(given[slot])
            if value and len(value) <= WORDS_MAX and len(out) < MAX_WORDS:
                out[slot] = value
    return out


# --- parsing --------------------------------------------------------------------------------------------------------------------------------------------

class _Refused(ValueError):
    pass


def _pairs(pairs) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise _Refused("a repeated key")
        out[key] = value
    return out


def _constant(_name):
    raise _Refused("NaN or infinity")


def _strings_ok(value) -> bool:
    """No string anywhere holds a lone surrogate (it cannot be written as UTF-8) or a NUL."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            return False
        return "\x00" not in value
    if isinstance(value, dict):
        return all(_strings_ok(k) and _strings_ok(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_strings_ok(v) for v in value)
    return True


def _shape(obj):
    """The error code of an object that is not of the protocol's shape, else None. Keys, types and the patterns of names, ids and times; nothing that needs a line or a catalog."""
    if not isinstance(obj, dict):
        return "E_SHAPE"
    if "v" not in obj or not _is_int(obj["v"]) or obj["v"] != PROTOCOL["protocol"]:
        return "E_VERSION"
    kind = obj.get("kind")
    if kind not in KINDS:
        return "E_SHAPE"
    required, optional = KEYS[kind]
    if not required <= set(obj) or set(obj) - required - optional:
        return "E_SHAPE"
    if kind == "op":
        if not isinstance(obj["op"], str) or not OP_RE.fullmatch(obj["op"]):
            return "E_SHAPE"
        for field in ("slots", "inherit"):
            given = obj.get(field, {})
            if not isinstance(given, dict) or len(given) > 8 or not all(isinstance(k, str) and SLOT_RE.fullmatch(k) and isinstance(v, str) for k, v in given.items()):
                return "E_SHAPE"
    elif kind == "answer":
        if not isinstance(obj["answers_item"], str) or not ID_RE.fullmatch(obj["answers_item"]):
            return "E_SHAPE"
        if "slot" in obj and (not isinstance(obj["slot"], str) or not SLOT_RE.fullmatch(obj["slot"])):
            return "E_SHAPE"
        if ("slot" in obj) != ("span" in obj) or ("span" in obj and not isinstance(obj["span"], str)):
            return "E_SHAPE"
        if "confirm" in obj and obj["confirm"] not in ("yes", "no"):
            return "E_SHAPE"
        if "option" in obj and (not _is_int(obj["option"]) or not 1 <= obj["option"] <= 9):
            return "E_SHAPE"
        if "option" in obj and len(obj) != 4:
            return "E_SHAPE"
    elif kind == "clarify":
        if ("slot" in obj) == ("ops" in obj):
            return "E_SHAPE"
        if "slot" in obj and (not isinstance(obj["slot"], str) or not SLOT_RE.fullmatch(obj["slot"])):
            return "E_SHAPE"
        if "ops" in obj:
            ops = obj["ops"]
            if not isinstance(ops, list) or not 2 <= len(ops) <= 3 or len(set(o for o in ops if isinstance(o, str))) != len(ops) or not all(isinstance(o, str) and OP_RE.fullmatch(o) for o in ops):
                return "E_SHAPE"
    if kind in ("op", "answer"):
        if ("time_iso" in obj) != ("weekday" in obj):
            return "E_SHAPE"
        if "weekday" in obj and obj["weekday"] not in WEEKDAYS:
            return "E_SHAPE"
        if "time_iso" in obj:
            stamp = obj["time_iso"]
            if not isinstance(stamp, str) or not TIME_RE.fullmatch(stamp):
                return "E_TIME_FORMAT"
            try:
                datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M")
            except ValueError:
                return "E_TIME_FORMAT"
    return None


def parse(text) -> tuple:
    """(object, state, error): `state` is "ok", "fenced" (the object was in one ```json fence), "invalid" or "none" (there is no text: no call was made). One JSON object of at
    most `max_output_bytes` bytes; a repeated key, NaN, an unknown key, a wrong type and a `v` other than 1 are refused (E_JSON, E_SIZE, E_SHAPE, E_VERSION)."""
    if text is None:
        return None, "none", "E_JSON"
    if not isinstance(text, str):
        return None, "invalid", "E_JSON"
    if len(text.encode("utf-8", "replace")) > PROTOCOL["max_output_bytes"]:
        return None, "invalid", "E_SIZE"
    body, state = text.strip(), "ok"
    if body.startswith("```"):
        fenced = FENCE_RE.fullmatch(body)
        if not fenced or "```" in fenced.group(1):
            return None, "invalid", "E_JSON"
        body, state = fenced.group(1).strip(), "fenced"
    try:
        obj = json.loads(body, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        return None, "invalid", "E_JSON"
    if not _strings_ok(obj):
        return None, "invalid", "E_JSON"
    error = _shape(obj)
    if error:
        return None, "invalid", error
    return obj, state, None


# --- the time -------------------------------------------------------------------------------------------------------------------------------------------

def _known(span: str, tables: list) -> bool:
    """Whether the span holds a word (of three letters or more) that some shipped table holds."""
    folded = nt.normalise(span)[0]
    known = nt.known_words(tables)
    return any(len(word) >= KNOWN_MIN and word in known for word in re.findall(r"[a-z0-9]+", folded))


def _classify(span: str, now_local):
    """(source, reading): who may decide the time of a span, and the reading code has of it (the model's `time_iso` is checked against it, never the other way)."""
    parsed = nt.parse(span, now_local)
    found = nt.find(span)
    tables = found["tables"]
    flagged = nt.doubt(span)
    if parsed is not None and "when" in parsed:
        reading = parsed["reading"]
        if parsed.get("vague") or flagged or reading.get("assumed_year") or not TIME_RE.fullmatch(f"{reading.get('date')}T{reading.get('time')}"):
            return "ask", None
        if nt.leftover_doubt(found, None, tables, unknown=False):          # a date word the engine did not read: asked, as the NR-1 guard shows and confirms
            return "ask", None
        if not reading.get("dated") and nt.leftover_doubt(found, None, tables, unknown=True):
            return "model", reading          # code read an hour only and the span holds words no table has (a language without tables): the model's date, the code's hour
        return "code", reading
    if parsed is not None:          # two readings, or a day and no hour
        return "ask", None
    if flagged or _known(span, tables):
        return "ask", None
    return "model", None


def time_source(span, now, zone) -> str:
    """"code", "ask" or "model" for a span of the line that fills a time slot. Only code decides (D4): "code" when `natural_time.parse` reads the span as one clear reading,
    which then wins over the model's `time_iso`; "ask" when the span holds any time phrase or word of a table but no single clear reading, or `natural_time.doubt` says it
    may be misread; "model" otherwise. The model never says which language the line is in."""
    return _classify(span, _local_now(now, zone))[0]


def _instant_problem(naive: datetime.datetime, tz, now_local):
    """The `why` of a wall time that cannot be used as it is: time-gap (the clock skips it), time-fold (it happens twice), time-past, time-far; else None."""
    first = naive.replace(tzinfo=tz, fold=0)
    if first.astimezone(datetime.timezone.utc).astimezone(tz).replace(tzinfo=None) != naive:
        return "time-gap"
    if first.utcoffset() != naive.replace(tzinfo=tz, fold=1).utcoffset():
        return "time-fold"
    if first <= now_local:
        return "time-past"
    if first - now_local > datetime.timedelta(days=FAR_DAYS):
        return "time-far"
    return None


def _time(span, time_iso, weekday, now_local, zone):
    """(time | None, disagree, why | error): the time of a span, or why it is asked back. `time` is {"local", "source"}."""
    source, reading = _classify(span, now_local)
    if source == "ask":
        return None, False, ("time-ask", None)
    disagree = False
    if source == "code":
        local = f"{reading['date']}T{reading['time']}"
        disagree = time_iso != local
    else:
        local = time_iso
        naive = datetime.datetime.strptime(local, "%Y-%m-%dT%H:%M")
        if WEEKDAYS[naive.weekday()] != weekday:
            return None, False, ("weekday", "E_WEEKDAY")
        if reading is not None and reading["time"] != local[11:]:          # code read the hour: the model may not move it
            return None, False, ("time-ask", None)
    naive = datetime.datetime.strptime(local, "%Y-%m-%dT%H:%M")
    problem = _instant_problem(naive, ZoneInfo(zone), now_local)
    if problem:
        return None, False, (problem, None)
    return {"local": local, "source": source}, disagree, None


# --- the decision ---------------------------------------------------------------------------------------------------------------------------------------

def _clarify(why: str, slot=None, ops=None, error=None, **extra) -> dict:
    return {"kind": "clarify", "error": error, "why": why, "slot": slot, "ops": ops, **extra}


def _invalid(error: str) -> dict:
    return _clarify("invalid", error=error)


def precheck(line):
    """The decision for a line that must not be sent to the model (longer than `max_line_chars`): a `route`, or a `clarify` with why long-line when the line is private
    (a reminder or a write in words: its words never leave). Else None."""
    if isinstance(line, str) and len(collapse(line)) > PROTOCOL["max_line_chars"]:
        return _clarify("long-line") if natural.private(line) else {"kind": "route", "error": None}
    return None


def _span_in_line(span: str, line: str) -> bool:
    return bool(span) and (span in line or span in collapse(line))


def _slot_error(op: str, slot: str, value: str, line: str) -> str:
    """Why `natural.check_operation` refused one slot: E_INT for a number slot, E_SPAN for the rest."""
    kind = natural.NATURAL[op]["slots"][slot][0]
    return "E_INT" if kind in ("int", "ints") else "E_SPAN"


def _check_slots(op: str, slots: dict, line: str):
    """(args, None) when every slot passes `natural.check_operation` (unchanged) and every text slot is also a piece of the line as written; else (None, error)."""
    for slot, value in slots.items():
        if slot not in natural.NATURAL[op]["slots"]:
            return None, "E_SLOT_UNKNOWN"
        if natural.NATURAL[op]["slots"][slot][0] == "ints" and not INTS_RE.fullmatch(value):
            return None, "E_INT"          # the protocol writes a list of numbers as digits joined by commas, nothing looser
    got = natural.check_operation(op, slots, None, line)
    if not got["ok"]:
        for slot, value in slots.items():
            if not natural.check_operation(op, {slot: value}, None, line)["ok"]:
                return None, _slot_error(op, slot, value, line)
        return None, "E_SPAN"
    for slot, value in slots.items():
        if natural.NATURAL[op]["slots"][slot][0] == "span" and not _span_in_line(value, line):
            return None, "E_SPAN"
    return got["args"], None


def _catalog_rows(catalog: dict):
    return {row["op"]: row for row in catalog["ops"]}, {row["op"]: row for row in catalog["refused"]}


def check(obj, line, frame, catalog, now, zone, allowed) -> dict:
    """The decision for a parsed object (the module's text says its shape). `allowed` is the set of operations the sender's policy lets them ask: an op outside it is
    `refuse_policy` (None allows nothing). Every part of the object is checked against the line, the frame and the clock here; the object is shaped again first, so a
    caller that did not `parse` it gets the same answer."""
    error = _shape(obj)
    if error:
        return _invalid(error)
    if not isinstance(line, str) or not line.strip():
        return _invalid("E_SHAPE")
    early = precheck(line)
    if early is not None:
        return early
    if frame_problems(frame, catalog):
        return _invalid("E_SHAPE")
    try:
        now_local = _local_now(now, zone)
    except Exception:
        return _invalid("E_SHAPE")
    kind = obj["kind"]
    if kind == "none":
        return {"kind": "none", "error": None}
    if kind == "route":
        return _clarify("private-route") if natural.private(line) else {"kind": "route", "error": None}
    ops, refused = _catalog_rows(catalog)
    if kind == "clarify":
        if "slot" in obj:
            if not any(obj["slot"] in row["slots"] for row in ops.values()):
                return _invalid("E_SLOT_UNKNOWN")
            return _clarify("model", slot=obj["slot"])
        if not all(name in ops and ops[name]["class"] != "work" for name in obj["ops"]):
            return _invalid("E_OP_UNKNOWN")
        return _clarify("model", ops=list(obj["ops"]))
    if kind == "answer":
        return _check_answer(obj, line, frame, ops, now_local, zone)
    return _check_op(obj, line, frame, ops, refused, now_local, zone, allowed)


def _check_op(obj, line, frame, ops, refused, now_local, zone, allowed) -> dict:
    name = obj["op"]
    if name in refused:
        return {"kind": "refuse", "error": None, "class": refused[name]["class"], "op": name}
    if name not in ops or (ops[name]["class"] == "work" and name != "ask"):
        return _invalid("E_OP_UNKNOWN")
    if allowed is None or name not in allowed:
        return {"kind": "refuse_policy", "error": None, "op": name}
    row = ops[name]["slots"]
    slots, inherit = obj["slots"], obj.get("inherit", {})
    if any(slot not in row for slot in list(slots) + list(inherit)):
        return _invalid("E_SLOT_UNKNOWN")
    time_slots = [slot for slot in slots if (name, slot) in TIME_SLOTS]
    if len(time_slots) > 1 or bool(time_slots) != ("time_iso" in obj):
        return _invalid("E_SHAPE")
    plain = {slot: value for slot, value in slots.items() if slot not in time_slots}
    args, error = _check_slots(name, plain, line)
    if error:
        return _invalid(error)
    spans = dict(plain)
    inherited = []
    if inherit:
        last = (frame or {}).get("last")
        for slot, span in inherit.items():
            if slot in slots or (name, slot) in TIME_SLOTS or last is None or slot not in last["words"]:
                return _invalid("E_INHERIT")
            recorded = last["words"][slot]
            if not natural.normal(span) or natural.normal(span) not in natural.normal(recorded) or span not in recorded:
                return _invalid("E_INHERIT")
            got, error = _check_slots(name, {slot: span}, recorded)          # an inherited span is checked as a span of the sender's own earlier words
            if error:
                return _invalid("E_INHERIT")
            args.update(got)
            spans[slot] = span
            inherited.append(slot)
    time, disagree = None, False
    if time_slots:
        span = slots[time_slots[0]]
        if not _span_in_line(span, line) or len(span) > SPAN_MAX:
            return _invalid("E_SPAN")
        time, disagree, problem = _time(span, obj["time_iso"], obj["weekday"], now_local, zone)
        if problem:
            return _clarify(problem[0], slot=time_slots[0], error=problem[1], op=name)
        spans[time_slots[0]] = span
    return {"kind": "op", "error": None, "op": name, "args": args, "spans": spans, "time": time, "inherited": inherited, "time_disagree": disagree}


def _check_answer(obj, line, frame, ops, now_local, zone) -> dict:
    item = next((i for i in (frame or {"items": []})["items"] if i["id"] == obj["answers_item"]), None)
    if item is None:
        return _invalid("E_ITEM_UNKNOWN")
    need = item["need"]
    given = set(obj) - {"v", "kind", "answers_item"}
    out = {"kind": "answer", "error": None, "item": item["id"], "need": need}
    if need == "text":
        return out if not given else _invalid("E_SHAPE")
    if need == "option":
        if given != {"option"} or obj["option"] > item["options"]:
            return _invalid("E_SHAPE")
        return {**out, "option": obj["option"]}
    if need == "confirm":
        if "confirm" not in obj or given - {"confirm", "slot", "span", "time_iso", "weekday"}:
            return _invalid("E_SHAPE")
        out["confirm"] = obj["confirm"]
    elif given - {"slot", "span", "time_iso", "weekday"} or "slot" not in obj:
        return _invalid("E_SHAPE")
    if "slot" not in obj:
        return out
    op = item.get("op")
    if op is None or op not in ops or obj["slot"] not in ops[op]["slots"] or (need == "slot" and obj["slot"] != item["slot"]):
        return _invalid("E_SLOT_UNKNOWN")
    is_time = (op, obj["slot"]) in TIME_SLOTS
    if is_time != ("time_iso" in obj):
        return _invalid("E_SHAPE")
    out.update({"slot": obj["slot"], "span": obj["span"]})
    if is_time:
        if not _span_in_line(obj["span"], line) or len(obj["span"]) > SPAN_MAX:
            return _invalid("E_SPAN")
        time, disagree, problem = _time(obj["span"], obj["time_iso"], obj["weekday"], now_local, zone)
        if problem:
            return _clarify(problem[0], slot=obj["slot"], error=problem[1], op=op, item=item["id"])
        return {**out, "args": {}, "time": time, "time_disagree": disagree}
    args, error = _check_slots(op, {obj["slot"]: obj["span"]}, line)
    if error:
        return _invalid(error)
    return {**out, "args": args}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
