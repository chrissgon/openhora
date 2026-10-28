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
  time_source(span, now, zone, line)  "code" | "ask" | "model": who may decide the time of a span. Code alone decides (a model never reports a language and so never
                                unlocks its own time): "code" when `natural_time.parse` reads the span as one clear reading, "ask" when it holds a time the code
                                half-reads or doubts, "model" when no table knows the words (or the code reads only an hour and the span holds words no table has)
  frame_problems(frame, catalog)  the problems of a typed frame (schema and rules R1-R7), as a list of sentences that never repeat a value
  typed_frame(items, last, labels)  the only way to build a frame: it copies the keys of the schema and nothing else
  build_messages(catalog, now, zone, frame, line)  (system, user): the prompt with the catalog, and exactly five lines
  render_catalog(catalog), prompt_sha256(), PROTOCOL

The decision, always {"kind", "error"} plus, by kind:
  op        op, args {parameter: value}, spans {slot: span}, time {local "YYYY-MM-DDTHH:MM", source "code"|"model"} | None, inherited [slots], time_disagree; and `target_ground` (a mail target widened
            with the line's subject, or a target of more than six content words that holds its own subject after the sender (BL7-5): the person and the subject without the marker
            word, the text a message is found by), `target_sender` (for the second kind: the person's part of the target, a piece of the line, which a later rule may require to be in the
            From), `corrects` (the plan item a correction answers)
  answer    item (the id), need, and what the item's need asks: slot / span / args, confirm, option, time, time_disagree
  clarify   slot | ops (code writes the question), why: model | time-ask | time-past | time-far | time-gap | time-fold | weekday | private-route | invalid | long-line
  route     none
  refuse    class D | G, op            refuse_policy   op
BL7-4, three rules of the check, none of which can open a card or run anything: a plain no (a line that opens with a no word and holds no digit, date, clock or relative time) is the `answer` no
of a plan item, from a model's `confirm: no` that names no slot and no span and from a model's `none`; a `mail-draft` with no recipient, target, message, day or subject in a line with a draft verb
and no mail noun or reply verb is `route` (`private-route` for a private line), before the policy check; and a date the time engine set apart as a deadline counts as read by code.
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
import recurrence  # noqa: E402  (the same folder: the closed words of a repetition; CB-7)
import turn_gate  # noqa: E402  (the same folder: the private line, the gate's check; the gate imports no interpreter)

PROMPT_FILE = os.path.join(HERE, "interpreter_prompt.txt")
PROTOCOL_FILE = os.path.join(HERE, "interpreter_protocol.json")
SERVED_FILE = os.path.join(HERE, "interpreter_catalog.json")
DAY_WORDS_FILE = os.path.join(HERE, "interpreter_day_words.json")
GATED_FILE = os.path.join(HERE, "gated_ops.json")
PLACEHOLDER = "{{CATALOG}}"
with open(PROTOCOL_FILE, encoding="utf-8") as _handle:
    PROTOCOL = json.load(_handle)

with open(DAY_WORDS_FILE, encoding="utf-8") as _handle:          # words that name a day, a month or a length of days in languages with no time table: used only to detect (`_unread_day`), never to read
    _LANGUAGES = json.load(_handle)["languages"]
DAY_PHRASES = [tuple(phrase.split()) for _lang in _LANGUAGES.values() for _kind in ("weekdays", "months", "relative") for phrase in _lang.get(_kind, [])]
UNIT_PHRASES = [tuple(phrase.split()) for _lang in _LANGUAGES.values() for phrase in _lang.get("units", [])]
_DOTTED = sorted({word for _lang in _LANGUAGES.values() for word in _lang.get("dotted", [])})
DOTTED_RE = re.compile(r"(?<![a-z0-9])(?:" + "|".join(_DOTTED) + r")\.") if _DOTTED else None          # "Do." and "Fr." (German): only with the period, a bare "do" or "fr" is a word
DATE_SHAPE_RE = re.compile(r"(?<![0-9])[0-9]{1,2}[./-][0-9]{1,2}(?![0-9])")          # "29/10", "29.10.", "29-10": a day written as numbers

# The slots that hold a time: (operation, slot). The model gives them `time_iso` and `weekday`; code decides who is believed (`time_source`).
TIME_SLOTS = frozenset({("remind", "when"), ("event-create", "time"), ("event-change", "time")})
TIME_DROPPED_OPS = ("event-cancel",)          # a removal has no time slot; a time the model added is dropped, never read (SPEC-BLITE-5C, 2026-10-25)
EVENT_OPS = ("event-change", "event-cancel")          # the operations that name an event by its words: a day with no event named is asked for (`no-target`)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")        # the weekday of the `today:` line: fixed, never the locale's
FAR_DAYS = 366                 # a time further away than this is asked back
SPAN_MAX = natural.SPAN_MAX
KNOWN_MIN = 3                  # a word shorter than this is never taken as proof that a span is in a language the tables know ("a", "de", "o")
WHYS = ("model", "time-ask", "time-past", "time-far", "time-gap", "time-fold", "weekday", "private-route", "invalid", "long-line")
ERRORS = ("E_JSON", "E_SIZE", "E_SHAPE", "E_VERSION", "E_OP_UNKNOWN", "E_SLOT_UNKNOWN", "E_SPAN", "E_INT", "E_TIME_FORMAT", "E_WEEKDAY", "E_ITEM_UNKNOWN", "E_INHERIT")

# BL7-1 (gap 1): the subject a line gives right after a message's target ("Gideon Farrow about the warehouse lease") stays in the target. Closed lists, folded (`natural.normal`), six languages.
MAIL_TARGET_OPS = ("mail-reply", "mail-draft", "mail-archive", "mail-trash", "mail-move", "mail-mark")          # the operations whose `target` names a message (the tuple of ops_interpret, kept apart on purpose)
SUBJECT_MARKERS = tuple(tuple(m.split()) for m in (
    "sobre", "a respeito de", "a respeito do", "a respeito da", "referente a", "referente ao", "acerca de", "acerca do", "acerca da",
    "about", "regarding", "concerning", "re",
    "respecto a", "respecto al", "respecto de",
    "sur", "au sujet de", "au sujet du", "au sujet des", "concernant", "a propos de", "a propos du", "a propos des",
    "uber", "wegen", "bezuglich", "zum thema",
    "su", "sul", "sullo", "sulla", "sui", "sugli", "sulle", "riguardo", "riguardo a", "riguardo al", "riguardo alla", "a proposito di", "a proposito del", "a proposito della", "circa"))
SUBJECT_STOPS = frozenset((          # the words that end a subject: the lead-ins of a body and the conjunctions
    "e", "que", "pra", "para", "com", "mas", "porque", "pois", "dizendo", "falando", "avisando", "pedindo", "agradecendo", "explicando", "confirmando", "perguntando", "informando", "respondendo",          # validate: allow english-only -- the closed list of Portuguese stop words of a subject
    "and", "that", "to", "with", "but", "because", "so", "saying", "telling", "tell", "asking", "thanking", "explaining", "confirming", "letting", "replying",
    "y", "con", "pero", "diciendo", "et", "pour", "avec", "mais", "disant", "en", "und", "dass", "mit", "aber", "um", "ma", "che", "per", "dicendo",
    "then", "depois", "entao", "luego", "puis", "dann", "poi",          # a second request after the subject ("... about the lease then trash the one from Bo")
    "into", "onto", "folder", "pasta", "carpeta", "dossier", "ordner", "cartella",          # a destination, never the subject ("... about the lease into Archive", "na pasta Trabalho")
    "too", "also", "tambem", "tambien", "aussi", "auch", "anche"))          # a closing "too" is not the subject
SUBJECT_TRAIL = frozenset("de do da dos das em no na nos nas o a os as um uma of the an on at in for from del la el los las le les du des der die das dem den von am im il lo di della dello".split())          # never left at the end of a subject
SUBJECT_WORDS_MAX = 6
_LINE_BREAK = re.compile(r"[\r\n\u0085\u2028\u2029]")          # a break of line ends a subject: what follows it is another request
# BL7-1 (gap 4): a correction of a read plan stays that read only for a card the read's words can be mistaken for, and never when the card holds the content of a new act.
READ_LOOKALIKE_CARDS = ("mail-mark",)          # "my unread emails" read as a mark by state; every other card (archive, trash, move, send, cancel, file-trash ...) is an act the person asked for
ACT_CONTENT_SLOTS = frozenset(("to", "subject", "body", "title", "content", "name", "time"))          # a slot that holds what a new act would carry: a correction of a read never has one

OP_RE = re.compile(r"[a-z][a-z0-9-]{0,39}")
SLOT_RE = re.compile(r"[a-z][a-z0-9_]{0,23}")
ID_RE = re.compile(r"i[1-9]")
CODE_RE = re.compile(r"[a-z0-9:._-]{1,64}")
TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}")
FENCE_RE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n?```", re.S)
INTS_RE = re.compile(r"[0-9]{1,9}(?:,[0-9]{1,9})*")
ACCOUNT_WORDS_MAX = 3      # words in a row an account slot may hold: "google drive", "one drive", "google calendar" (S17)
LINE_BREAKS = re.compile(r"\s+")           # every run of white space, line separators included (str `\s` holds U+0085, U+2028 and U+2029)

KINDS = ("op", "answer", "clarify", "route", "none")
# The keys of each kind: (required, optional). Anything else is refused.
KEYS = {"op": ({"v", "kind", "op", "slots"}, {"time_iso", "weekday", "inherit"}),
        "answer": ({"v", "kind", "answers_item"}, {"slot", "span", "time_iso", "weekday", "confirm", "option"}),
        "clarify": ({"v", "kind"}, {"slot", "ops"}),
        "route": ({"v", "kind"}, set()),
        "none": ({"v", "kind"}, set())}
FRAME_KINDS = ("write-draft", "reminder-confirm", "router-question", "choice", "plan-confirm")
FRAME_NEEDS = ("slot", "confirm", "option", "text")
ITEM_KEYS = {"id", "kind", "op", "need", "slot", "options", "values", "words", "age_s"}
ITEM_REQUIRED = {"id", "kind", "need", "age_s"}
MAX_ITEMS = 5
MAX_WORDS = 6
WORDS_MAX = 300
LABEL_MAX = 60
MAX_DEPTH = 4                  # the deepest nesting an output may have (the protocol needs 2: an object holding an object or a list)


# --- the files ----------------------------------------------------------------------------------------------------------------------------------------

def canonical(obj) -> bytes:
    """The canonical JSON of an object (the form every hash of the interpreter is taken over)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def catalog_sha256(catalog) -> str:
    """The sha256 of the canonical form of a catalog object (the hash the evidence names)."""
    return hashlib.sha256(canonical(catalog)).hexdigest()


def _read_json(path: str):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


SERVED = _read_json(SERVED_FILE)
SERVED_SHA256 = catalog_sha256(SERVED)
# The operations no line may do, read from the classification that C0 committed and from `natural.CLASSES`, so that a catalog handed in cannot widen them.
WIDENING = frozenset(row["op"] for row in _read_json(GATED_FILE)["rows"] if row["kind"] == "widening")


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
    if catalog_sha256(catalog) != SERVED_SHA256:
        raise ValueError("the catalog is not the served one")
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
            out.append(f"{where}: kind is not one of the five")
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
        if rows is not None and op is not None and row is None:
            out.append(f"{where}: op is not an op of the catalog")          # whatever the kind of the item
        if row is not None and "slot" in item and (not isinstance(item["slot"], str) or item["slot"] not in row):
            out.append(f"{where}: slot is not a slot of the op")
        if kind == "router-question":          # R1
            if set(item) != ITEM_REQUIRED or need != "text":
                out.append(f"{where}: a router item is its id, kind, need (text) and age only")
            continue
        if kind == "plan-confirm":          # R8
            if set(item) != ITEM_REQUIRED | {"op"} or need != "confirm" or op is None:
                out.append(f"{where}: a plan-confirm item is its id, kind, need (confirm), op and age only")
            continue
        if kind in ("write-draft", "reminder-confirm"):          # R2
            if op is None:
                out.append(f"{where}: a {kind} carries op")
            if kind == "reminder-confirm" and op != "remind":
                out.append(f"{where}: a reminder-confirm has op remind")
        if need == "slot":          # R3
            slot = item.get("slot")
            if not isinstance(slot, str) or not SLOT_RE.fullmatch(slot) or op is None:
                out.append(f"{where}: need slot carries a slot and an op")
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


def typed_frame(items, last, labels, catalog=None) -> dict:
    """The frame, built by a whitelist: only the keys of the schema are copied, whatever else an item carries (a subject, a file name, a router's question, the body of a
    card) is left behind. `labels` is the accepted configuration's map {code (or the option number as text): label}: a value's label comes from it and never from an item.
    A word is copied only from the field `own_words` of an item (and of `last`), which the caller sets from what the same sender typed; an item's `words` is never read. An item
    older than a day and a `last` older than an hour are left out. An op and a slot are checked against `catalog` (the served one when none is given) and a value's code must be a key of
    `labels`. ValueError (with no value in it) when what is left is not a valid frame."""
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
                if isinstance(code, str) and code not in labels:
                    raise ValueError("a value's code is not in the accepted configuration")
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
        if out.get("kind") == "plan-confirm":          # R8: the operation and the age, never a word (the plan's own words are `last`'s)
            out = {key: out[key] for key in ("id", "kind", "need", "op", "age_s") if key in out}
        built.append(out)
    kept = None
    if isinstance(last, dict) and _is_int(last.get("age_s")) and last["age_s"] <= 3600:
        kept = {"op": last.get("op"), "words": _own_words(last.get("own_words")) or {}, "age_s": last["age_s"]}
    frame = {"v": 1, "items": built[:MAX_ITEMS], "last": kept}
    problems = frame_problems(frame, SERVED if catalog is None else catalog)
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
    """No string anywhere holds a lone surrogate (it cannot be written as UTF-8) or a NUL. Iterative: no depth of nesting reaches the recursion limit."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                return False
            if "\x00" in item:
                return False
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return True


def _depth_ok(body: str) -> bool:
    """Whether the text nests brackets no deeper than MAX_DEPTH, counted outside strings, before any JSON reader sees it."""
    depth, in_string, escaped = 0, False, False
    for ch in body:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                return False
        elif ch in "]}":
            depth -= 1
    return True


def _safe_shape(obj):
    """`_shape`, with any failure of its own read as a refusal."""
    try:
        return _shape(obj)
    except Exception:
        return "E_JSON"


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
    if not _depth_ok(body):
        return None, "invalid", "E_JSON"
    try:
        obj = json.loads(body, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError):
        return None, "invalid", "E_JSON"
    if not _strings_ok(obj):
        return None, "invalid", "E_JSON"
    error = _safe_shape(obj)
    if error:
        return None, "invalid", error
    return obj, state, None


# --- the time -------------------------------------------------------------------------------------------------------------------------------------------

def _known(span: str, tables: list) -> bool:
    """Whether the span holds a word (of three letters or more) that some shipped table holds."""
    folded = nt.normalise(span)[0]
    known = nt.known_words(tables)
    return any(len(word) >= KNOWN_MIN and word in known for word in re.findall(r"[a-z0-9]+", folded))


def _known_outside(found: dict) -> bool:
    """Whether the line holds, outside its time phrases, a word (of three letters or more) that some shipped table holds."""
    folded, known = found["norm"], nt.known_words(found["tables"])
    covered = [(h["s"], h["e"]) for h in found["hits"] + found.get("deadline", [])]          # BL7-4: a deadline date was read by code
    outside = "".join(" " if any(a <= i < b for a, b in covered) else c for i, c in enumerate(folded))
    return any(len(word) >= KNOWN_MIN and word in known for word in re.findall(r"[a-z0-9]+", outside))


def _cover(seen: str, piece: str, found: dict):
    """Whether some occurrence of `piece` in `seen` holds every time phrase the engine found in `seen`. A time phrase the engine reads with a trigger word of a table before it ("para sexta",
    "for tmrw") is held when the piece holds the phrase without that word, so long as the piece holds nothing but time phrases (every character of it lies inside a hit): the prompt tells
    the model to keep the words around a value out of its span, and a span with a word that is no part of a time phrase ("3pm to call Dana") is still not the time of the line."""
    cuts = nt._spans(found)
    origin, hits = found["origin"], found["hits"]
    cores = [(origin[h.get("s0", h["s"])], origin[h["e"] - 1] + 1) for h in hits]
    wholes = [(origin[h["s"]], origin[h["e"] - 1] + 1) for h in hits]
    start = seen.find(piece) if piece else -1
    while start != -1:
        end = start + len(piece)
        if all(start <= a and b <= end for a, b in cuts):
            return True
        if all(start <= a and b <= end for a, b in cores) and all(any(a <= i < b for a, b in wholes) for i in range(start, end) if not seen[i].isspace()):
            return True
        start = seen.find(piece, start + 1)
    return False


def _hour_without_day_is_asked(hits: list) -> bool:
    """Whether an hour-only reading of a line with words no table holds is asked about: true unless a time phrase code read holds a trigger word of a table before the hour ("at 3pm", "às 15h"),
    which says the line is in that table's language, where a day word would have been read or caught as an unread date word."""
    return not any(h.get("s0", h["s"]) > h["s"] for h in hits)


HOUR_OWN_CONNECTORS = ("at", "as")          # folded: the connector a bare-hour phrase holds as its own first word ("at 12", "as 12")
NOON_PHRASES = (("meio", "dia"), ("meia", "noite"), ("noon",), ("midnight",))          # folded: the phrases that name an hour with no digit
NOON_CONNECTORS = ("a", "ao")          # folded: the article-preposition just before one of them ("a meia-noite", "ao meio-dia")


def _connector_beside_hour(found: dict) -> bool:
    """Whether the connector that introduces the hour is part of its phrase, so that `_hour_without_day_is_asked` (which sees a connector only where `natural_time._extend` took it into
    the phrase) must not ask: the first word of a bare-hour phrase ("at 12", "as 12"), or the word just before a noon or midnight phrase ("ao meio-dia", "a meia-noite"). A connector
    before an hour written in digits ("a 15h", "um 15 Uhr", "alle 15") is not enough, and a day word beside the phrase is still caught by `_unread_day`."""
    norm = found["norm"]
    for h in found["hits"]:
        words = re.findall(r"[a-z0-9]+", norm[h["s"]:h["e"]])
        if words and words[0] in HOUR_OWN_CONNECTORS:
            return True
        before = re.findall(r"[a-z0-9]+", norm[:h["s"]])
        if before and before[-1] in NOON_CONNECTORS and any(tuple(words[:len(phrase)]) == phrase for phrase in NOON_PHRASES):
            return True
    return False


def _unread_day(found: dict, dated: bool) -> bool:
    """Whether the line holds, outside its time phrases, a word or a number that may name a day code did not read: a weekday, a month or a relative-day word of `interpreter_day_words.json`, a German
    two-letter weekday with its period, or a day written as numbers ("29/10"); and, when code read an hour only (`dated` is False), also a length of days ("en dos dias", "dans 2 jours") or a whole
    number from 1 to 31 ("the 29", "el 29"). A dated reading is asked only for what conflicts with the day it read: a bare number or a unit word ("2 apples", "this month") does not."""
    norm = found["norm"]
    covered = [(h["s"], h["e"]) for h in found["hits"] + found.get("deadline", [])]          # BL7-4: a deadline date was read by code
    outside = "".join(" " if any(a <= i < b for a, b in covered) else c for i, c in enumerate(norm))
    tokens = [m.group() for m in re.finditer(r"[a-z0-9]+", outside)]
    phrases = DAY_PHRASES if dated else DAY_PHRASES + UNIT_PHRASES
    if any(tokens[i:i + len(phrase)] == list(phrase) for phrase in phrases for i in range(len(tokens))):
        return True
    if (DOTTED_RE and DOTTED_RE.search(outside)) or DATE_SHAPE_RE.search(outside):
        return True
    return not dated and any(w.isdigit() and 1 <= int(w) <= 31 for w in tokens)


def _classify(span: str, line: str, now_local):
    """(source, reading): who may decide the time of a span, and the reading code has of it (the model's `time_iso` is checked against it, never the other way). The decision
    is made from the WHOLE LINE and never from the span the model chose, since the model picks the span: "code" only when the span holds every time phrase of the line and
    the line has no doubt; "model" only when the line has no time phrase, no doubt and no word of a table (or code read an hour only and the line holds words no table has)."""
    seen, piece = collapse(line), collapse(span)
    found = nt.find(seen)
    tables, hits = found["tables"], found["hits"]
    flagged = nt.doubt(seen)
    if not hits:
        return ("ask", None) if flagged or _known(seen, tables) else ("model", None)
    if flagged or not _cover(seen, piece, found) or nt.leftover_doubt(found, None, tables, unknown=False):
        return "ask", None          # a time phrase outside the span, or a date word the engine did not read: asked, as the NR-1 guard shows and confirms
    parsed, whole = nt.parse(piece, now_local), nt.parse(seen, now_local)
    if parsed is None or "when" not in parsed or whole is None or "when" not in whole:
        return "ask", None
    reading = parsed["reading"]
    if (parsed.get("vague") or whole.get("vague") or nt.doubt(piece) or reading.get("assumed_year") or whole["reading"]["when"] != reading["when"]
            or not TIME_RE.fullmatch(f"{reading.get('date')}T{reading.get('time')}")):
        return "ask", None
    if not reading.get("dated") and nt.leftover_doubt(found, None, tables, unknown=True):
        if not _known_outside(found):
            return "model", reading          # code read an hour only, the line holds words no table has and none that a table does (a language without tables): the model's date, the code's hour
        if _hour_without_day_is_asked(hits) and not _connector_beside_hour(found):
            return "ask", None          # an hour with no day, no trigger word of a table beside it and words no table has ("el jueves a las 15:00 en el calendario"): code never takes the clock's own day for a day the line may name
    if _unread_day(found, bool(reading.get("dated"))):
        return "ask", None          # a word or a number that may name a day stands outside the time code read ("jueves at 15:00", "the 29 at 3pm", "tomorrow at 3pm el jueves"): a trigger word does not make it one language
    return "code", reading


def time_source(span, now, zone, line) -> str:
    """"code", "ask" or "model" for a span of the line that fills a time slot (`line` is the whole line, required: the source is never read from the span alone). Only code decides (D4), and
    from the whole line, never from the span the model chose: "code" when `natural_time.parse` reads the span as one clear reading and the span holds every time phrase of the line;
    "ask" when the line holds a time phrase or a word of a table that the span does not settle, or `natural_time.doubt` says it may be misread; "model" when the line holds
    none. The model never says which language the line is in."""
    return _classify(span, line, _local_now(now, zone))[0]


def _instant_problem(naive: datetime.datetime, tz, now_local):
    """The `why` of a wall time that cannot be used as it is: time-gap (the clock skips it), time-fold (it happens twice), time-past, time-far; else None."""
    if naive.year < now_local.year - 1:
        return "time-past"
    if naive.year > now_local.year + 2:
        return "time-far"
    try:
        first = naive.replace(tzinfo=tz, fold=0)
        if first.astimezone(datetime.timezone.utc).astimezone(tz).replace(tzinfo=None) != naive:
            return "time-gap"
        if first.utcoffset() != naive.replace(tzinfo=tz, fold=1).utcoffset():
            return "time-fold"
        if first <= now_local:
            return "time-past"
        if first - now_local > datetime.timedelta(days=FAR_DAYS):
            return "time-far"
    except (OverflowError, ValueError):
        return "time-far"
    return None


def _occurrences(text: str, piece: str) -> list:
    """The start of every occurrence of `piece` in `text`."""
    found, at = [], text.find(piece) if piece else -1
    while at != -1:
        found.append(at)
        at = text.find(piece, at + 1)
    return found


def _without_old_day(name: str, slots: dict, span: str, line: str) -> str:
    """The line the time of an event change is classified against (SPEC-BLITE-5C C1a). A change has two days: the one the event is on now (the `day` slot) and the one it moves to (inside
    the time span). The old day is the other slot, not a doubt about the new time, so for `event-change` only, the first occurrence of the `day` span is blanked (spaces of its length) in
    the collapsed line when ALL hold: the time span holds a day of its own (a date or slash hit: "para sexta as 10h", so that a new day the model put in `day` is never blanked, whatever
    stands between the two spans, and a clock-only time is asked as before); the day span ends before the time span begins and no occurrence of the time span overlaps it; it does not lie
    inside the target ("Reuniao de Segunda"); the time engine reads it as a day and nothing else (every hit a date, no clock); and the engine does not doubt it. Anything else: `line`
    unchanged, so the old day stays a time phrase outside the time span and the time is asked."""
    day = slots.get("day") if name == "event-change" else None
    if not isinstance(day, str) or not isinstance(span, str):
        return line
    seen, piece, mark = collapse(line), collapse(day), collapse(span)
    at = seen.find(piece) if piece else -1
    if at < 0 or not mark:
        return line
    end = at + len(piece)
    times = _occurrences(seen, mark)
    if not any(t >= end for t in times) or any(t < end and at < t + len(mark) for t in times):
        return line
    target = collapse(slots.get("target")) if isinstance(slots.get("target"), str) else ""
    if any(t <= at and end <= t + len(target) for t in _occurrences(seen, target)):
        return line
    if not any(h["kind"] in ("date", "slash") for h in nt.find(mark)["hits"]):
        return line
    hits = nt.find(piece)["hits"]
    if not hits or any(h["kind"] not in ("date", "slash") for h in hits) or nt.doubt(piece):
        return line
    return seen[:at] + " " * len(piece) + seen[end:]


def _time(span, line, time_iso, weekday, now_local, zone):
    """(time | None, disagree, why | error): the time of a span, or why it is asked back. `time` is {"local", "source"}."""
    source, reading = _classify(span, line, now_local)
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
        return _clarify("long-line") if turn_gate.private_line(line) else {"kind": "route", "error": None}
    return None


def _span_in_line(span: str, line: str) -> bool:
    return bool(span) and (span in line or span in collapse(line))


def _slot_error(op: str, slot: str, value: str, line: str) -> str:
    """Why `natural.check_operation` refused one slot: E_INT for a number slot, E_SPAN for the rest."""
    kind = natural.NATURAL[op]["slots"][slot][0]
    return "E_INT" if kind in ("int", "ints") else "E_SPAN"


def _account_run(op: str, slot: str, value: str, line: str) -> bool:
    """Whether `value` is the account slot written with two or three words that stand in a row in the line ("google drive", "one drive"): `natural.check_operation` reads a word slot as ONE
    word of the line, so an account named by a brand of several words is checked here, by the same rule for each of its words (a whole word of the line, no piece inside a longer one)."""
    spec = natural.NATURAL[op]["slots"].get(slot)
    parts = value.split()
    if spec is None or list(spec) != ["word", "account"] or not 2 <= len(parts) <= ACCOUNT_WORDS_MAX or " ".join(parts) != value:
        return False
    tokens = [t.strip(natural.WORD_EDGE) for t in unicodedata.normalize("NFKC", line).split()]
    return all(natural.WORD_RE.fullmatch(p) for p in parts) and any(tokens[i:i + len(parts)] == parts for i in range(len(tokens) - len(parts) + 1))


def _check_slots(op: str, slots: dict, line: str):
    """(args, None) when every slot passes `natural.check_operation` (unchanged; an account of several words in a row passes `_account_run` instead) and every text slot is also a piece of the line as written; else (None, error)."""
    for slot, value in slots.items():
        if slot not in natural.NATURAL[op]["slots"]:
            return None, "E_SLOT_UNKNOWN"
        if natural.NATURAL[op]["slots"][slot][0] == "ints" and not INTS_RE.fullmatch(value):
            return None, "E_INT"          # the protocol writes a list of numbers as digits joined by commas, nothing looser
    runs = {slot: value for slot, value in slots.items() if _account_run(op, slot, value, line)}
    single = {slot: value for slot, value in slots.items() if slot not in runs}
    got = natural.check_operation(op, single, None, line)
    if not got["ok"]:
        for slot, value in single.items():
            if not natural.check_operation(op, {slot: value}, None, line)["ok"]:
                return None, _slot_error(op, slot, value, line)
        return None, "E_SPAN"
    got = dict(got, args={**got["args"], **{natural.NATURAL[op]["slots"][slot][1]: value for slot, value in runs.items()}})
    for slot, value in slots.items():
        if natural.NATURAL[op]["slots"][slot][0] in ("span", "word") and not _span_in_line(value, line):          # a word is also as typed: a full-width or ligature form is not
            return None, "E_SPAN"
    return got["args"], None


def _catalog_rows(catalog: dict):
    return {row["op"]: row for row in catalog["ops"]}, {row["op"]: row for row in catalog["refused"]}


def check(obj, line, frame, catalog, now, zone, allowed) -> dict:
    """The decision for a parsed object (the module's text says its shape). `allowed` is the set of operations the sender's policy lets them ask: an op outside it is
    `refuse_policy` (None allows nothing). Every part of the object is checked against the line, the frame and the clock here; the object is shaped again first, so a
    caller that did not `parse` it gets the same answer."""
    error = _safe_shape(obj)
    if error:
        return _invalid(error)
    if catalog_sha256(catalog) != SERVED_SHA256:
        return _invalid("E_SHAPE")
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
        plan = next((i for i in (frame or {}).get("items") or [] if i.get("kind") == "plan-confirm"), None)
        if plan is not None and _plain_no(line):          # BL7-4 (E): a model's `none` on a plain no of a live plan is that no; it can only drop the plan
            return {"kind": "answer", "error": None, "item": plan["id"], "need": "confirm", "confirm": "no"}
        return {"kind": "none", "error": None}
    if kind == "route":
        return _clarify("private-route") if turn_gate.private_line(line) else {"kind": "route", "error": None}
    ops, refused = _catalog_rows(catalog)
    if kind == "clarify":
        if "slot" in obj:
            if not any(obj["slot"] in row["slots"] for row in ops.values()):
                return _invalid("E_SLOT_UNKNOWN")
            return _clarify("model", slot=obj["slot"])
        if not all(name in ops and ops[name]["class"] != "work" for name in obj["ops"]):
            return _invalid("E_OP_UNKNOWN")
        asked = [name for name in obj["ops"] if allowed is not None and name in allowed]
        if len(asked) < 2:
            return {"kind": "refuse_policy", "error": None, "op": next((n for n in obj["ops"] if allowed is None or n not in allowed), obj["ops"][0])}
        return _clarify("model", ops=asked)
    if kind == "answer":
        return _check_answer(obj, line, frame, ops, now_local, zone, allowed)
    kept = _read_plan_kept(obj, line, frame, ops)          # BL7-1 (gap 4): a correction of a read plan stays that read unless the line asks for an act
    if kept is not None:
        revised, item_id = kept
        decision = _check_op(revised, line, frame, ops, refused, now_local, zone, allowed)
        return dict(decision, corrects=item_id) if decision.get("kind") == "op" else decision
    return _check_op(obj, line, frame, ops, refused, now_local, zone, allowed)


def _check_op(obj, line, frame, ops, refused, now_local, zone, allowed) -> dict:
    name = obj["op"]
    if natural.CLASSES.get(name) == "D":
        return {"kind": "refuse", "error": None, "class": "D", "op": name}
    if name in WIDENING:
        return {"kind": "refuse", "error": None, "class": "G", "op": name}
    if name in refused:
        return {"kind": "refuse", "error": None, "class": refused[name]["class"], "op": name}
    if name not in ops or (ops[name]["class"] == "work" and name != "ask"):
        return _invalid("E_OP_UNKNOWN")
    if _open_note(name, obj, line, ops):          # BL7-4 (C): a draft of a note with no recipient, message, day or subject is open writing, not a mail card
        return _clarify("private-route") if turn_gate.private_line(line) else {"kind": "route", "error": None}
    if allowed is None or name not in allowed:
        return {"kind": "refuse_policy", "error": None, "op": name}
    row = ops[name]["slots"]
    slots, inherit = obj["slots"], obj.get("inherit", {})
    if any(slot not in row for slot in list(slots) + list(inherit)):
        return _invalid("E_SLOT_UNKNOWN")
    inherit = {slot: span for slot, span in inherit.items() if slot not in slots}          # BL7-1 (gap 3): a slot the line fills is the line's; the old words the model also named for it are dropped, never read
    time_slots = [slot for slot in slots if (name, slot) in TIME_SLOTS]
    if name in TIME_DROPPED_OPS and not time_slots:
        obj = {k: v for k, v in obj.items() if k not in ("time_iso", "weekday")}          # a removal has no time slot: the time the model added is dropped, never read nor kept
    if len(time_slots) > 1 or bool(time_slots) != ("time_iso" in obj):
        return _invalid("E_SHAPE")
    plain = {slot: value for slot, value in slots.items() if slot not in time_slots}
    args, error = _check_slots(name, plain, line)
    if error:
        return _invalid(error)
    if name in EVENT_OPS and "day" in slots and not {"target", "event"} & (set(slots) | set(inherit)):
        return _clarify("no-target", slot="target", op=name)          # a day and no event named: the runtime asks again (`natural`'s IX_ASK_AGAIN), and so does the measure
    ground = None
    if name in MAIL_TARGET_OPS and "target" in plain:          # BL7-1 (gap 1): the subject the line gives right after the person stays in the target; the wider span passed `_check_slots` again
        wider = _target_with_subject(plain["target"], line, {slot: value for slot, value in plain.items() if slot != "target"}, name)
        if wider != plain["target"]:
            ground = _subject_ground(plain["target"], wider)          # the words grounding reads: the person and the subject, never the marker word ("a respeito de")
            plain = dict(plain, target=wider)
            args, error = _check_slots(name, plain, line)          # whatever the helper returned is checked as any span of the line, here too: a value that is not in the line is E_SPAN
            if error:
                return _invalid(error)
    sender = None
    if ground is None and name in MAIL_TARGET_OPS and "target" in plain:          # BL7-5 (G3): a target of more than six content words that holds its own subject after the sender is grounded the same way
        own = _own_subject_split(plain["target"])
        if own is not None:
            sender, ground = own
    spans = dict(plain)
    inherited = []
    if inherit:
        last = (frame or {}).get("last")
        for slot, span in inherit.items():
            if (name, slot) in TIME_SLOTS or last is None or last["op"] != name or slot not in last["words"]:
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
        if name == "event-change" and _deadline_set_apart(line):          # BL7-4: in a change the date before a deadline word may be the event's old day and the one after it the new day: asked, as before the deadline rule
            return _clarify("time-ask", slot=time_slots[0], op=name)
        time, disagree, problem = _time(span, _without_old_day(name, slots, span, line), obj["time_iso"], obj["weekday"], now_local, zone)
        if problem and problem[0] == "time-ask" and name == "event-create" and recurrence.mentions(line):          # CB-7: the words that only say the event repeats ("todo dia", the "toda" of "toda segunda") are no doubt about the time: the engine reads the first occurrence of what is left
            again = _time(recurrence.strip(span), recurrence.strip(line), obj["time_iso"], obj["weekday"], now_local, zone)
            if again[2] is None:
                time, disagree, problem = again
        if problem:
            return _clarify(problem[0], slot=time_slots[0], error=problem[1], op=name)
        spans[time_slots[0]] = span
    decision = {"kind": "op", "error": None, "op": name, "args": args, "spans": spans, "time": time, "inherited": inherited, "time_disagree": disagree}
    if ground:
        decision["target_ground"] = ground          # only for a widened target or a target that holds its own subject: `ops_natural_mail.mail_target_seed` finds the message by the words of this text (the line's own words, no marker word)
        if sender:
            decision["target_sender"] = sender          # BL7-5: the person's part of such a target (a piece of the line); nothing reads it yet
    return decision


_WORD = re.compile(r"\S+")
_PUNCT_END = re.compile(r"[,;:.!?)]+$")


def _head_phrases():
    """The folded phrases, as tuples of words, that open an act: the closed heads of the write families (`natural_writes_mail`, `natural_writes_files`, `natural_writes_calendar`) and the
    triggers the tables own for a new event (`triggers.calendar`, `calendar_verb`, `calendar_loose`), read from them and never copied here."""
    import importlib
    tables = natural._tables(None)
    phrases = []
    for family in ("natural_writes_mail", "natural_writes_files", "natural_writes_calendar"):
        phrases += importlib.import_module(family).HEADS(tables)
    for table in tables:
        for key in ("calendar", "calendar_verb", "calendar_loose"):
            phrases += table["triggers"][key]
    return [tuple(phrase.split()) for phrase in phrases if phrase.split()]


def _head_at(words, at, heads):
    """Whether the folded `words` hold, from index `at`, a head phrase of `heads` as whole words in a row."""
    return any(tuple(words[at:at + len(head)]) == head for head in heads)


def _target_with_subject(target, line, others, name):
    """BL7-1 (gap 1). `target` widened by the subject the line gives right after it ("Gideon Farrow" + " about the warehouse lease"), else `target` unchanged. The result is always
    `target` or a piece of the line that starts with it: it comes from the line alone, never from a message, an index or the model's text. Widened only when all hold: `target` stands
    once in the line; a subject marker (SUBJECT_MARKERS, folded) follows it after white space on the same line; the tail after the marker runs to the first stop word (SUBJECT_STOPS),
    date written as numbers, break of line, head of an act (`_head_phrases`), word that ends in punctuation (taken without it), start of another slot's span (`others`) or start of a
    time phrase, less the function words at its end (SUBJECT_TRAIL); the tail holds 1 to SUBJECT_WORDS_MAX words; the wider span is at most SPAN_MAX, passes `_check_slots` like any
    span, and the person and the subject (the marker word never counts: `_subject_ground`) name more content words of a message than `target` did."""
    if not target or line.count(target) != 1:
        return target
    begin = line.find(target)
    start = begin + len(target)
    toks = [(m.start() + start, m.end() + start, m.group()) for m in _WORD.finditer(line[start:])]
    if not toks or not line[start:toks[0][0]] or line[start:toks[0][0]].strip():
        return target          # nothing after the target, or the next word is not set apart from it by white space alone
    if _LINE_BREAK.search(line[start:toks[0][0]]):
        return target          # the next word is on another line: another request
    folded = [natural.normal(t[2]) for t in toks]
    marker = next((m for m in sorted(SUBJECT_MARKERS, key=len, reverse=True) if tuple(folded[:len(m)]) == m and not any(_PUNCT_END.search(t[2]) for t in toks[:len(m)])), None)
    if marker is None:
        return target
    limits = []          # where another slot's span or a time phrase starts, after the target: the subject never reaches past one
    for value in others.values():
        at = line.find(value, start) if isinstance(value, str) and value else -1
        if at >= 0:
            limits.append(at)
    found = nt.find(line)
    for hit in found["hits"]:
        at = found["origin"][hit["s"]]
        if at >= start:
            limits.append(at)
    heads = _head_phrases()
    kept = []
    for index in range(len(marker), len(toks)):
        first, _last, word = toks[index]
        if _LINE_BREAK.search(line[toks[index - 1][1]:first]) or _head_at(folded, index, heads):
            break          # a break of line, or an act's head: another request begins
        if any(first >= limit for limit in limits) or natural.normal(word) in SUBJECT_STOPS or DATE_SHAPE_RE.search(word):
            break
        clean = _PUNCT_END.sub("", word)
        if not clean:
            break
        kept.append((first + len(clean), natural.normal(clean)))
        if clean != word or len(kept) > SUBJECT_WORDS_MAX:
            break
    while kept and kept[-1][1] in SUBJECT_TRAIL:
        kept.pop()          # "sobre a reuniao de" before a day: the function word at the edge is not the subject's
    if not kept or len(kept) > SUBJECT_WORDS_MAX:
        return target
    wider = line[begin:kept[-1][0]]
    if len(wider) > SPAN_MAX or _check_slots(name, {"target": wider}, line)[1] is not None:
        return target
    import importlib
    mail = importlib.import_module("natural_writes_mail")
    tables = natural._tables(None)
    if len(mail.target_words(_subject_ground(target, wider), tables)) <= len(mail.target_words(target, tables)):
        return target          # the widening must add a content word and still name a message (a sentence, more than TARGET_WORDS_MAX words, names nothing)
    return wider


def _subject_ground(target, wider):
    """The text grounding finds a message by when `wider` is `target` widened with a subject: `target`, then the subject without its marker ("Ana a respeito do orcamento" gives "Ana
    orcamento"). The marker words ("a respeito de", "concerning", "re", "sur" ...) say where the subject starts; they are not words of a message, and `natural_writes_mail.target_words`
    would keep most of them. Made of the line's own words only; `target` alone when `wider` holds no marker after it."""
    rest = wider[len(target):].split() if wider.startswith(target) else []
    folded = [natural.normal(word) for word in rest]
    marker = next((m for m in sorted(SUBJECT_MARKERS, key=len, reverse=True) if tuple(folded[:len(m)]) == m), None)
    return target if marker is None else " ".join([target] + rest[len(marker):])


def _own_subject_split(target):
    """BL7-5 (gap G3). (the person's part, the ground) of a mail `target` that has more than TARGET_WORDS_MAX content words and holds its own subject after the person ("Nadia Ferreira about the
    volunteer schedule for the book fair"), else None. None when `natural_writes_mail.target_words` reads the target (a target that is grounded today is untouched), when no subject marker
    (SUBJECT_MARKERS, folded, whole words, the longest first) starts at its second word or later with a word after it that is not itself the start of a marker ("Mei Su about": the name "Su" is a marker of another language), when the part before the marker holds no letter or digit, or when the
    ground (`_subject_ground`: the person, then the subject without the marker word) has no content words within GROUND_WORDS_MAX. Made of the target's own words only (a span the check
    verified): nothing is added, so every word of the ground is a word of the target, and `match_words` still requires every one."""
    import importlib
    mail = importlib.import_module("natural_writes_mail")
    tables = natural._tables(None)
    if not target or mail.target_words(target, tables):
        return None
    toks = [(m.start(), natural.normal(m.group())) for m in _WORD.finditer(target)]
    markers = sorted(SUBJECT_MARKERS, key=len, reverse=True)
    folded = [word for _at, word in toks]
    for index in range(1, len(toks)):
        marker = next((m for m in markers if tuple(folded[index:index + len(m)]) == m), None)
        if marker is None:
            continue
        if index + len(marker) >= len(toks):
            return None          # the marker is the end of the target: no subject follows it
        if any(tuple(folded[index + len(marker):index + len(marker) + len(m)]) == m for m in markers):
            continue          # a marker of another language that is a name ("Mei Su about ...", "Lia Sur regarding ..."): the marker that follows it is the subject's
        person = target[:toks[index][0]].rstrip()
        if not any(ch.isalnum() for ch in person):
            return None
        own = _subject_ground(person, target)
        return (person, own) if mail.ground_words(own, tables) else None
    return None


def _own_subject_ground(target):
    """BL7-5. The ground of `_own_subject_split` alone, or None."""
    split = _own_subject_split(target)
    return None if split is None else split[1]


def _asks_an_act(line):
    """BL7-1 (gap 4): whether the line holds, as whole folded words in a row, the head of an act: a closed head of a write family or a trigger of a new event (`_head_phrases`, read from
    the families and the tables, never copied here). Such a line asks for an act and is never turned into a read."""
    words = natural.normal(line).split()
    heads = _head_phrases()
    return any(_head_at(words, at, heads) for at in range(len(words)))


def _read_plan_kept(obj, line, frame, ops):
    """BL7-1 (gap 4): (the revised op object, the plan item's id) when a line that opens with a no corrects a live plan of a READ (class R) and the model named a card (class E) of another
    operation that the read's words can be mistaken for (READ_LOOKALIKE_CARDS), with no slot that holds the content of a new act (ACT_CONTENT_SLOTS), for a line that holds no head of an
    act; else None (today's path). The revised object is the plan's own read with the slots the model gave, kept only when the read has them all (a list has none, so it keeps none). It
    only ever turns a card into the read the person already had a plan for: never into an act (L65)."""
    last = (frame or {}).get("last")
    item = next((i for i in (frame or {}).get("items") or [] if i.get("kind") == "plan-confirm"), None)
    if item is None or last is None or item.get("op") != last.get("op") or last.get("op") not in ops or ops[last["op"]]["class"] != "R":
        return None
    name = obj.get("op")
    if name == last["op"] or name not in ops or ops[name]["class"] != "E" or not starts_with_no(line) or _asks_an_act(line):
        return None
    if name not in READ_LOOKALIKE_CARDS or ACT_CONTENT_SLOTS & set(obj["slots"]):
        return None          # a card of an act the person may have asked for, or one that carries a new act's content: today's path stands
    row = ops[last["op"]]["slots"]
    slots = {slot: value for slot, value in obj["slots"].items() if slot in row}
    if row and set(slots) != set(obj["slots"]):
        return None          # the read has slots and the model gave one it lacks: it meant another act, today's path stands (a list has none: the day is read from the line by code)
    return {"v": 1, "kind": "op", "op": last["op"], "slots": slots}, item["id"]


NO_LEAD = frozenset(("nao", "no", "nope", "nah"))          # the folded words that open a no, pt-BR and en (BL5B)
THANKS = frozenset(("obrigado", "obrigada", "brigado", "brigada", "valeu", "vlw", "thanks", "thank", "thx"))          # a courtesy that closes a no ("no thanks"), folded
COURTESY_FILL = frozenset(("muito", "very", "much", "so", "a", "lot", "you"))          # the words that may stand beside a thanks ("muito obrigado", "thank you", "thanks a lot")


def starts_with_no(line) -> bool:
    """Whether the line opens with a no word (the closed list `NO_LEAD`, folded: "Nao, a de amanha", "no, the one for Friday"). The line of a correction of an open plan; a new request
    does not (BL5B)."""
    words = natural.normal(line).split() if isinstance(line, str) else []
    return bool(words) and words[0] in NO_LEAD


def polite_no(line) -> bool:
    """Whether the line is a no and a courtesy and nothing else ("nao, obrigado", "no thanks", "no, thank you", "nao, muito obrigado"): the closed lists `NO_LEAD`, `THANKS` and
    `COURTESY_FILL`, folded. It is a bare no for the plan (the plan is dropped); "nao, obrigado, de amanha" holds more and is not (BL5B)."""
    words = natural.normal(line).split() if isinstance(line, str) else []
    rest = words[1:]
    return bool(words) and words[0] in NO_LEAD and any(w in THANKS for w in rest) and all(w in THANKS or w in COURTESY_FILL for w in rest)


NOTE_BLOCKERS = frozenset(("to", "target", "message", "day", "subject"))          # a draft that holds one of these slots names a recipient, a message, a day or a subject: today's path


def _open_note(name, obj, line, ops) -> bool:
    """BL7-4 (C): whether a `mail-draft` of the model is an open writing request ("draft a nice note to the neighbours about our party"): every slot of the object is a slot of the
    catalog row, none of them is a recipient, message, day or subject (NOTE_BLOCKERS, as a slot or an inherited one), and the folded line holds, as whole words in a row, a draft verb of
    some table and no mail noun and no reply verb of any table (`requests.writes.mail`, read from the tables and never copied here). Such a draft has no seed (`mail_compose.seed` refuses a
    draft with no recipient), so the card would be a dead end: the line is `route`, the same answer the model's `route` gets."""
    if name != "mail-draft" or name not in ops:
        return False
    slots, inherit = obj.get("slots") or {}, obj.get("inherit") or {}
    names = set(slots) | set(inherit)
    if not names <= set(ops[name]["slots"]) or names & NOTE_BLOCKERS:
        return False
    import importlib
    writes = importlib.import_module("natural_writes")
    tables = natural._tables(None)
    words = natural.normal(line).split()

    def held(phrases):
        return any(words[at:at + len(p)] == p for p in (phrase.split() for phrase in phrases) if p for at in range(len(words)))
    return (held(writes.listed(tables, "mail", "draft_verbs")) and not held(writes.listed(tables, "mail", "nouns"))
            and not held(writes.listed(tables, "mail", "reply_verbs")))


def _deadline_set_apart(line) -> bool:
    """BL7-4: whether the time engine set a date of the line apart as a deadline (`natural_time.find`'s `deadline`)."""
    return bool(nt.find(collapse(line)).get("deadline"))


PLAIN_NO_FILLER = frozenset(THANKS | COURTESY_FILL | {          # the folded words that may follow a no in a plain no: a courtesy, "leave it", "I will look later" (pt-BR and en); nothing else
    "obrigado", "obrigada", "ok", "okay", "tudo", "bem", "entao", "deixa", "deixe", "deixar", "pra", "la", "isso", "eu", "vejo", "depois", "com", "calma", "mais", "tarde", "agora", "por",      # validate: allow english-only -- the Portuguese filler words of a no
    "enquanto", "leave", "it", "then", "i", "will", "look", "at", "later", "see", "that", "alone", "fine", "all", "right", "is", "its", "never", "mind", "forget", "just", "for", "now"})


def _plain_no(line) -> bool:
    """BL7-4 (B, E): whether the line is a plain no of a plan: it opens with a no word (`starts_with_no`) and every word after it is a word of the closed list PLAIN_NO_FILLER (a courtesy,
    "leave it", "I will look at it later"), so it holds no digit and no time; the time engine reads no date, slash date, clock or relative time in it either (a vague word such as "depois" is
    allowed). A no that carries any other word (a new request, "no problem", "nao esquece") is not a plain no and keeps the path it had. It can only drop a plan (L65)."""
    if not starts_with_no(line) or any(c.isdigit() for c in line):
        return False
    if any(word not in PLAIN_NO_FILLER for word in natural.normal(line).split()[1:]):
        return False
    return not any(hit["kind"] in ("date", "slash", "clock", "relative") for hit in nt.find(collapse(line))["hits"])


def _plan_correction(obj, item, line, frame, ops, now_local, zone, allowed):
    """The decision for a model's `confirm: "no"` on a `plan-confirm` item when the line is a correction ("no, the one for tomorrow"), else None (the answer is checked as before). BL5B.
    Only a plan item of the operation the frame's `last` holds, only a no that is not a bare no, and never a yes: a model's yes is never turned into anything. The result is an `op`
    decision for the plan's own operation, checked like any op (the span in the line, the number written in it, the time engine), with `corrects` set to the item's id; code asks it as a
    NEW "Shall I go ahead?" and runs nothing. Two shapes (the ones the protocol already carries):
      (a) the no names a slot of the plan's operation with a span: that slot is the span; the other slots of `frame.last.words` are inherited, except a number slot (a number is never
          carried from the old line: it is written in the correcting line or asked) and a time slot;
      (b) the no names no slot of the operation, the operation has none in the catalog (a list), and the line holds a day the time engine reads: the operation with no slots (the day is
          read from the line by code, as it is for any list)."""
    last = (frame or {}).get("last")
    if item.get("kind") != "plan-confirm" or obj.get("confirm") != "no" or last is None or item.get("op") != last.get("op") or item["op"] not in ops:
        return None
    if natural.confirm_kind(line) == "no" or polite_no(line):          # a bare no, or a no with a courtesy ("no thanks"), is a no
        return None
    op, slots = item["op"], ops[item["op"]]["slots"]
    if obj.get("slot") in slots and isinstance(obj.get("span"), str):
        slot = obj["slot"]
        inherit = {name: words for name, words in last.get("words", {}).items()
                   if name != slot and name in slots and slots[name] not in ("int", "ints") and (op, name) not in TIME_SLOTS}
        revised = {"v": 1, "kind": "op", "op": op, "slots": {slot: obj["span"]}, **({"inherit": inherit} if inherit else {}),
                   **{key: obj[key] for key in ("time_iso", "weekday") if key in obj}}
    elif not slots and any(hit["kind"] in ("date", "slash") for hit in nt.find(collapse(line))["hits"]):
        revised = {"v": 1, "kind": "op", "op": op, "slots": {}}
    else:
        return None
    decision = _check_op(revised, line, frame, ops, {}, now_local, zone, allowed)
    return dict(decision, corrects=item["id"]) if decision.get("kind") == "op" else decision


def _check_answer(obj, line, frame, ops, now_local, zone, allowed) -> dict:
    item = next((i for i in (frame or {"items": []})["items"] if i["id"] == obj["answers_item"]), None)
    if item is None:
        return _invalid("E_ITEM_UNKNOWN")
    need = item["need"]
    if item.get("op") is not None and (allowed is None or item["op"] not in allowed):
        return {"kind": "refuse_policy", "error": None, "op": item["op"]}
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
        corrected = _plan_correction(obj, item, line, frame, ops, now_local, zone, allowed)          # BL5B: a no that carries a new detail on a plan item is the corrected request
        if corrected is not None:
            return corrected
        if obj["confirm"] == "no" and polite_no(line):          # BL5B: "no, thanks" is a no whatever the model made of the courtesy (a slot, a span): the plan is dropped
            return {**out, "confirm": "no"}
        if obj["confirm"] == "no" and item.get("kind") == "plan-confirm" and "slot" not in obj and "span" not in obj and _plain_no(line):
            return {**out, "confirm": "no"}          # BL7-4 (B): a plain no ("no, leave it, I will look at it later") is a no, though it is not a closed one; the plan is dropped, nothing runs
        probe = line.replace(obj["span"], " ", 1) if "span" in obj else line          # the words that are left once the answer's own span is taken out
        if natural.confirm_kind(probe) != obj["confirm"]:
            return _clarify("model", item=item["id"])          # the line does not say what the model says: asked again, by code
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
        time, disagree, problem = _time(obj["span"], line, obj["time_iso"], obj["weekday"], now_local, zone)
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
