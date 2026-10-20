"""The item format of the interpreter corpus (spec IX-1, section 1.7) and the frame's checkable rules (section 1.5):
constants, canonical files, the catalog read as data, and the problems of an item, a gold and a frame. Loaded by
scripts/interpreter_corpus.py (the verbs) and scripts/interpreter_corpus_build.py (generate, adversarial); it runs no
verb of its own. Standard library only; Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python 3.9 has zoneinfo
    ZoneInfo = None


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "runtime" / "interpreter_catalog.json"
FOLDER = ROOT / "evals" / "interpreter"
SOURCES = ROOT / "runtime" / "tests"

LANGS = {"pt-BR": "pt-br", "en": "en", "es": "es", "fr": "fr", "de": "de", "it": "it", "ja": "ja", "mixed": "mx"}
AUTHORS = ("gen", "opus", "adv", "relabel")
CHANNELS = ("messaging", "page", "terminal", "chat")
TAGS = ("typo", "no-accents", "lower-nopunct", "slang", "code-switch", "filler", "tempt-d", "tempt-g", "multi-intent",
        "injection", "forward", "dst", "past", "far-future", "weekday-mismatch", "private", "inherit", "multi-turn",
        "must-route", "relabel-time", "relabel-op")
HARD_TAGS = frozenset(("tempt-d", "tempt-g", "multi-intent", "injection", "forward", "dst", "past", "far-future",
                       "weekday-mismatch", "code-switch", "inherit"))
OUTCOMES = ("op", "answer", "clarify", "route", "none", "refuse", "forwarded")
# The time slots of the served catalog (runtime/interpreter_catalog.py TIME_SLOTS, copied: scripts/ never imports runtime/;
# runtime/tests/test_interpreter_corpus_schema.py ties the two).
TIME_SLOTS = frozenset((("remind", "when"), ("event-create", "time"), ("event-change", "time")))
EFFECT_CLASSES = frozenset(("N", "W", "E", "G"))
ITEM_KEYS = frozenset(("id", "split", "lang", "author", "tags", "hard", "clock", "zone", "channel", "forwarded", "frame",
                       "line", "gold", "also"))
LINE_KEYS = ITEM_KEYS - {"gold", "also"}
VIEW_KEYS = ("lang", "clock", "zone", "channel", "forwarded", "frame", "line")
ID_RE = re.compile(r"^(dev|test)-(pt-br|en|es|fr|de|it|ja|mx)-([0-9]{5})$")
OPAQUE_RE = re.compile(r"^w-[0-9a-f]{8}$")
ISO_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$")
RULE_RE = re.compile(r"^L(?:10|[1-9])$")
RELABEL_BASE = {"natural": 10000, "writes": 20000, "mail": 30000}
RELABEL_RANGE = (10000, 39999)
RELABEL_CLOCK = "2026-10-22T14:00"
RELABEL_ZONE = "America/Sao_Paulo"
RELABEL_AGE_S = 60
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_LINE = 1000
FRAME_ITEM_KEYS = frozenset(("id", "kind", "op", "need", "slot", "options", "values", "words", "age_s"))
FRAME_KINDS = ("write-draft", "reminder-confirm", "router-question", "choice")
FRAME_NEEDS = ("slot", "confirm", "option", "text")
FRAME_ID_RE = re.compile(r"^i[1-9]$")
OP_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
SLOT_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
CODE_RE = re.compile(r"^[a-z0-9:._-]{1,64}$")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
ADV_RULES = {"no-accents": ("keep",), "typo": ("keep",), "lower-nopunct": ("keep",), "slang": ("keep",),
             "code-switch": ("keep",), "filler": ("keep",), "tempt-d": ("refuse-d",), "tempt-g": ("refuse-g",),
             "multi-intent": ("clarify",), "forward": ("forwarded",), "injection": ("keep", "clarify")}
PUNCT = frozenset(".,;:!?\"'()[]\u2026\u201c\u201d\u2018\u2019\u00ab\u00bb\u00a1\u00bf")
SIMILARITY_THRESHOLD = 0.80


class UsageError(Exception):
    """A usage or input error: the message names files and ids, never the text of a line."""


# ---------------------------------------------------------------------------------------------------------------- io

def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(f"{path}: cannot read ({type(exc).__name__})")
    except json.JSONDecodeError as exc:
        raise UsageError(f"{path}: not JSON (line {exc.lineno})")


def read_jsonl(path) -> list:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise UsageError(f"{path}: cannot read ({type(exc).__name__})")
    out = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            raise UsageError(f"{path}:{number}: not JSON")
        if not isinstance(obj, dict):
            raise UsageError(f"{path}:{number}: not a JSON object")
        out.append(obj)
    return out


def read_many(paths) -> list:
    items = []
    for path in paths:
        items.extend(read_jsonl(path))
    return items


def corpus_bytes(items) -> bytes:
    """The canonical corpus file: one canonical item per line, sorted by id, a newline after every line."""
    return "".join(canonical(item) + "\n" for item in sorted(items, key=lambda i: str(i.get("id")))).encode("utf-8")


def write_bytes(path, data: bytes) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    return sha256_bytes(data)


def by_id(items, what: str) -> dict:
    out = {}
    for item in items:
        key = item.get("id")
        if not isinstance(key, str):
            raise UsageError(f"{what}: an item has no string id")
        if key in out:
            raise UsageError(f"{what}: id {key} appears twice")
        out[key] = item
    return out


# ------------------------------------------------------------------------------------------------------------ helpers

def normal(text: str) -> str:
    """natural.normal: compatibility form, case folded, accents removed, every run of non-letters and non-digits one space."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text)).casefold() if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", plain).strip()


def hard_of(tags) -> bool:
    return bool(HARD_TAGS.intersection(tags or ()))


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_clock(text):
    if not isinstance(text, str) or not ISO_RE.match(text):
        return None
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def iso(moment: datetime.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M")


def zone_ok(name) -> bool:
    if not isinstance(name, str) or not name or ZoneInfo is None:
        return False
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def lang_part(lang: str) -> str:
    if lang not in LANGS:
        raise UsageError(f"unknown language {lang!r} (one of {', '.join(LANGS)})")
    return LANGS[lang]


def make_id(split: str, lang: str, number: int) -> str:
    if not 0 <= number <= 99999:
        raise UsageError(f"id number {number} out of range")
    return f"{split}-{lang_part(lang)}-{number:05d}"


def opaque(seed: str, item_id: str) -> str:
    return "w-" + hashlib.sha256(f"{seed}:{item_id}".encode("utf-8")).hexdigest()[:8]


def union(first, second) -> list:
    out = list(first)
    for value in second:
        if value not in out:
            out.append(value)
    return out


def rng_for(*parts) -> random.Random:
    """A generator seeded by a string: the same sequence on every machine and every PYTHONHASHSEED."""
    return random.Random(":".join(str(p) for p in parts))


def count_by(values) -> dict:
    out = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


# ------------------------------------------------------------------------------------------------------------ catalog

def load_catalog(path) -> dict:
    """{"ops": {op: {"class", "slots": {slot: kind}}}, "refused": {op: class}} from the served catalog file."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("ops"), list) or not isinstance(data.get("refused"), list):
        raise UsageError(f"{path}: not a catalog (keys ops and refused, each a list)")
    ops, refused = {}, {}
    for row in data["ops"]:
        if not isinstance(row, dict) or not isinstance(row.get("op"), str) or not isinstance(row.get("slots"), dict):
            raise UsageError(f"{path}: an ops row has no op or slots")
        ops[row["op"]] = {"class": row.get("class"), "slots": dict(row["slots"])}
    for row in data["refused"]:
        if not isinstance(row, dict) or not isinstance(row.get("op"), str):
            raise UsageError(f"{path}: a refused row has no op")
        refused[row["op"]] = row.get("class")
    return {"ops": ops, "refused": refused}


def frame_problems(frame, cat) -> list:
    """The structural problems of a frame (frame.schema.json and its checkable rules R1-R3, R5, R6), as short words."""
    if not isinstance(frame, dict):
        return ["frame: not an object"]
    out = []
    if set(frame) != {"v", "items", "last"}:
        return ["frame: keys are exactly v, items, last"]
    if frame["v"] != 1 or not is_int(frame["v"]):
        out.append("frame.v: not 1")
    items = frame["items"]
    if not isinstance(items, list) or len(items) > 5:
        return out + ["frame.items: not a list of at most 5"]
    seen_ids, seen_kinds = set(), set()
    for n, item in enumerate(items):
        where = f"frame.items[{n}]"
        if not isinstance(item, dict):
            out.append(f"{where}: not an object")
            continue
        keys = set(item)
        if keys - FRAME_ITEM_KEYS or not {"id", "kind", "need", "age_s"} <= keys:
            out.append(f"{where}: keys")
            continue
        if not isinstance(item["id"], str) or not FRAME_ID_RE.match(item["id"]):
            out.append(f"{where}.id: pattern")
        elif item["id"] in seen_ids:
            out.append(f"{where}.id: not unique (R6)")
        seen_ids.add(item.get("id"))
        kind, need = item["kind"], item["need"]
        if kind not in FRAME_KINDS:
            out.append(f"{where}.kind: unknown")
        elif kind != "choice" and kind in seen_kinds:
            out.append(f"{where}.kind: twice (R6)")
        seen_kinds.add(kind)
        if need not in FRAME_NEEDS:
            out.append(f"{where}.need: unknown")
        if not is_int(item["age_s"]) or not 0 <= item["age_s"] <= 86400:
            out.append(f"{where}.age_s: not an integer 0..86400")
        if kind == "router-question" and (keys != {"id", "kind", "need", "age_s"} or need != "text"):
            out.append(f"{where}: a router question is id, kind, need text, age_s (R1)")
        op = item.get("op")
        if op is not None and (not isinstance(op, str) or not OP_RE.match(op) or op not in cat["ops"]):
            out.append(f"{where}.op: not an op of the catalog (R2)")
            op = None
        if kind in ("write-draft", "reminder-confirm") and "op" not in item:
            out.append(f"{where}.op: missing (R2)")
        if kind == "reminder-confirm" and item.get("op") != "remind":
            out.append(f"{where}.op: a reminder confirmation is op remind (R2)")
        row_slots = cat["ops"][op]["slots"] if op else {}
        if "slot" in item and (not isinstance(item["slot"], str) or not SLOT_RE.match(item["slot"])):
            out.append(f"{where}.slot: pattern")
        if need == "slot" and (item.get("slot") not in row_slots):
            out.append(f"{where}.slot: need slot names a slot of the op (R3)")
        if "options" in item and (not is_int(item["options"]) or not 2 <= item["options"] <= 9):
            out.append(f"{where}.options: not an integer 2..9")
        if need == "option":
            if kind != "choice" or "options" not in item:
                out.append(f"{where}: need option is a choice with options (R3)")
            values = item.get("values")
            if values is not None:
                ns = [v.get("n") for v in values if isinstance(v, dict)] if isinstance(values, list) else []
                if (not isinstance(values, list) or len(values) != item.get("options") or len(set(map(str, ns))) != len(ns)
                        or not all(is_int(x) and 1 <= x <= (item.get("options") or 0) for x in ns)):
                    out.append(f"{where}.values: one per option, n 1..options (R3)")
        values = item.get("values")
        if values is not None:
            if not isinstance(values, list) or len(values) > 9:
                out.append(f"{where}.values: not a list of at most 9")
            else:
                for v in values:
                    if (not isinstance(v, dict) or set(v) - {"n", "label", "code"} or not {"n", "label"} <= set(v)
                            or not is_int(v["n"]) or not 1 <= v["n"] <= 9 or not isinstance(v["label"], str)
                            or not 1 <= len(v["label"]) <= 60
                            or ("code" in v and (not isinstance(v["code"], str) or not CODE_RE.match(v["code"])))):
                        out.append(f"{where}.values: an entry is not n, label, code")
                        break
        out.extend(_words_problems(item.get("words"), row_slots, f"{where}.words", "words" in item))
    last = frame["last"]
    if last is not None:
        if not isinstance(last, dict) or set(last) != {"op", "words", "age_s"}:
            out.append("frame.last: keys are exactly op, words, age_s")
        else:
            op = last["op"]
            if not isinstance(op, str) or op not in cat["ops"]:
                out.append("frame.last.op: not an op of the catalog")
                op = None
            if not is_int(last["age_s"]) or not 0 <= last["age_s"] <= 3600:
                out.append("frame.last.age_s: not an integer 0..3600")
            out.extend(_words_problems(last["words"], cat["ops"][op]["slots"] if op else {}, "frame.last.words", True))
    return out


def _words_problems(words, row_slots, where, present) -> list:
    if not present:
        return []
    if not isinstance(words, dict) or len(words) > 6:
        return [f"{where}: not an object of at most 6"]
    for slot, value in words.items():
        if not SLOT_RE.match(slot) or slot not in row_slots:
            return [f"{where}: {slot} is not a slot of the op (R5)"]
        if not isinstance(value, str) or not 1 <= len(value) <= 300:
            return [f"{where}.{slot}: not a string of 1..300"]
    return []


# --------------------------------------------------------------------------------------------------------- the item

def _number_in(line: str, digits: str) -> bool:
    return re.search(r"(?<![0-9])" + re.escape(digits) + r"(?![0-9])", line) is not None


def _span_ok(span, kind, line, inherited) -> bool:
    """A value of a slot: digits for int and ints (each number written in the line), else a piece of the line; an
    inherited value may instead be a piece of the sender's earlier words."""
    if not isinstance(span, str) or not span.strip():
        return False
    if kind == "int":
        return re.fullmatch(r"[0-9]+", span) is not None and (_number_in(line, span) or span in inherited)
    if kind == "ints":
        return re.fullmatch(r"[0-9]+(,[0-9]+)*", span) is not None and all(_number_in(line, d) for d in span.split(","))
    return span in line or bool(inherited) and span in inherited


def zone_reading(moment: datetime.datetime, zone) -> str:
    """'gap' when the local moment does not exist in the zone (a spring-forward hour: no round trip through UTC), 'fold'
    when it exists twice (an autumn hour: the two offsets differ), else 'ok'. An unknown zone reads 'ok' (check flags it)."""
    if not zone_ok(zone):
        return "ok"
    tz = ZoneInfo(zone)
    first, second = moment.replace(tzinfo=tz, fold=0), moment.replace(tzinfo=tz, fold=1)
    back = first.astimezone(datetime.timezone.utc).astimezone(tz).replace(tzinfo=None)
    if back != moment:
        return "gap"
    return "fold" if first.utcoffset() != second.utcoffset() else "ok"


def _times_problems(times, when, where) -> list:
    """The problems of a list of accepted moments read at `when` = (clock, zone)."""
    clock, zone = when
    if not isinstance(times, list) or not times or len(set(map(str, times))) != len(times):
        return [f"{where}: not a non-empty list of distinct times"]
    for value in times:
        moment = parse_clock(value)
        if moment is None:
            return [f"{where}: {value!r} is not YYYY-MM-DDTHH:MM"]
        reading = zone_reading(moment, zone)
        if reading != "ok":
            return [f"{where}: {value} is {'not a moment' if reading == 'gap' else 'two moments'} in the zone (time-{reading}: clarify)"]
        if clock is not None and moment <= clock:
            return [f"{where}: {value} is not after the clock (L5: a past time is clarify)"]
        if clock is not None and moment - clock > datetime.timedelta(days=366):
            return [f"{where}: {value} is more than 366 days after the clock"]
    return []


def gold_problems(gold, item, cat, where="gold", scope=None) -> list:
    """The problems of one gold (or one `also` entry, which takes the gold's scope) against its item and the catalog."""
    if not isinstance(gold, dict) or gold.get("outcome") not in OUTCOMES:
        return [f"{where}: no known outcome"]
    outcome, keys = gold["outcome"], set(gold)
    line, frame = item.get("line") or "", item.get("frame")
    clock = (parse_clock(item.get("clock")), item.get("zone"))
    if where == "gold":
        scope = gold.get("scope")
    if "scope" in gold and where == "gold":
        if gold["scope"] not in ("op", "time") or outcome not in ("op", "clarify"):
            return [f"{where}.scope: op or time, on an op or clarify gold"]
        if item.get("author") != "relabel":
            return [f"{where}.scope: only relabelled items carry a scope"]
    if outcome == "op":
        if scope == "op":
            if keys - {"outcome", "op", "scope"} or gold.get("op") not in cat["ops"]:
                return [f"{where}: a scope-op gold is outcome, op (an op of the catalog), scope"]
            return []
        if scope == "time":
            if keys - {"outcome", "op", "time", "scope"} or gold.get("op") is not None:
                return [f"{where}: a scope-time gold is outcome, op null, time, scope"]
            return _times_problems(gold.get("time"), clock, f"{where}.time")
        if keys - {"outcome", "op", "slots", "time"} or "slots" not in keys:
            return [f"{where}: an op gold is outcome, op, slots, time?"]
        op = gold.get("op")
        if op not in cat["ops"]:
            return [f"{where}.op: {op!r} is not an op of the catalog"]
        row, slots = cat["ops"][op]["slots"], gold["slots"]
        if not isinstance(slots, dict):
            return [f"{where}.slots: not an object"]
        last_words = (frame or {}).get("last") or {}
        last_words = last_words.get("words") or {} if isinstance(last_words, dict) else {}
        out = []
        for slot, spans in slots.items():
            if slot not in row:
                out.append(f"{where}.slots.{slot}: not a slot of {op}")
                continue
            if not isinstance(spans, list) or not spans or len(set(map(str, spans))) != len(spans):
                out.append(f"{where}.slots.{slot}: not a non-empty list of distinct values")
                continue
            for span in spans:
                if not _span_ok(span, row[slot], line, last_words.get(slot, "")):
                    out.append(f"{where}.slots.{slot}: a value is not in the line")
                    break
        timed = any((op, slot) in TIME_SLOTS for slot in slots)
        if timed:
            out.extend(_times_problems(gold.get("time"), clock, f"{where}.time"))
        elif "time" in gold:
            out.append(f"{where}.time: present without a time slot")
        return out
    if outcome == "answer":
        return _answer_problems(gold, keys, line, frame, clock, cat, where, item.get("author") == "relabel")
    if outcome == "clarify":
        if keys - {"outcome", "slot", "ops", "scope"} or ("slot" in gold and "ops" in gold):
            return [f"{where}: a clarify gold is outcome and at most one of slot, ops"]
        if "slot" in gold and (not isinstance(gold["slot"], str) or not SLOT_RE.match(gold["slot"])):
            return [f"{where}.slot: pattern"]
        if "ops" in gold:
            ops = gold["ops"]
            if not isinstance(ops, list) or not 2 <= len(ops) <= 3 or not all(o in cat["ops"] for o in ops):
                return [f"{where}.ops: 2 or 3 ops of the catalog"]
        return []
    if outcome == "refuse":
        if keys != {"outcome", "class"} or gold["class"] not in ("D", "G"):
            return [f"{where}: a refuse gold is outcome and class D or G"]
        return []
    if keys != {"outcome"}:
        return [f"{where}: a {outcome} gold has the key outcome only"]
    return []


def _answer_problems(gold, keys, line, frame, clock, cat, where, spanless=False) -> list:
    """The answer gold against the frame item it answers. A relabelled answer to a time slot may carry no span: only its
    reading (`time`) was labelled, by code."""
    items = {i.get("id"): i for i in (frame or {}).get("items") or [] if isinstance(i, dict)}
    item = items.get(gold.get("item"))
    if item is None:
        return [f"{where}.item: not an id of the frame's items"]
    need, op = item.get("need"), item.get("op")
    row = cat["ops"][op]["slots"] if op in cat["ops"] else {}
    allowed = {"slot": {"outcome", "item", "slot", "span", "time"}, "confirm": {"outcome", "item", "confirm", "slot", "span", "time"},
               "option": {"outcome", "item", "option"}, "text": {"outcome", "item"}}.get(need, {"outcome", "item"})
    if keys - allowed:
        return [f"{where}: keys of an answer to a need {need}"]
    if need == "option" and (not is_int(gold.get("option")) or not 1 <= gold["option"] <= (item.get("options") or 0)):
        return [f"{where}.option: an integer 1..options"]
    if need == "confirm" and gold.get("confirm") not in ("yes", "no"):
        return [f"{where}.confirm: yes or no"]
    if need == "slot" and gold.get("slot") != item.get("slot"):
        return [f"{where}.slot: the slot the item needs"]
    if "slot" in gold:
        slot = gold["slot"]
        if slot not in row:
            return [f"{where}.slot: not a slot of the item's op"]
        spans = gold.get("span")
        timed = (op, slot) in TIME_SLOTS
        if spans is None and spanless and timed and "time" in gold:
            return _times_problems(gold.get("time"), clock, f"{where}.time")
        if not isinstance(spans, list) or not spans or not all(_span_ok(s, row[slot], line, "") for s in spans):
            return [f"{where}.span: a non-empty list of values in the line"]
        if timed:
            return _times_problems(gold.get("time"), clock, f"{where}.time")
    elif "span" in gold:
        return [f"{where}.span: without a slot"]
    if "time" in gold and ("slot" not in gold or (op, gold["slot"]) not in TIME_SLOTS):
        return [f"{where}.time: present without a time slot"]
    return []


def item_problems(item, cat, lines_only=False) -> list:
    """Every problem of one item against the item format (spec 1.7) and the catalog, as `<path>: <words>`."""
    if not isinstance(item, dict):
        return ["item: not an object"]
    want = LINE_KEYS if lines_only else ITEM_KEYS
    keys = set(item)
    extra, missing = keys - want - {"base"}, want - keys
    if extra or missing:
        return [f"keys: missing {sorted(missing)}, unknown {sorted(extra)}"]
    out = []
    match = ID_RE.match(item["id"]) if isinstance(item["id"], str) else None
    if match is None:
        out.append("id: pattern")
    if item["split"] not in ("dev", "test"):
        out.append("split: dev or test")
    if item["lang"] not in LANGS:
        out.append("lang: unknown")
    if item["author"] not in AUTHORS:
        out.append("author: unknown")
    if match:
        if match.group(1) != item["split"]:
            out.append("id: split part differs from split")
        if LANGS.get(item["lang"]) != match.group(2):
            out.append("id: language part differs from lang")
        number = int(match.group(3))
        in_range = RELABEL_RANGE[0] <= number <= RELABEL_RANGE[1]
        if (item["author"] == "relabel") != in_range:
            out.append("id: 10000-39999 is the relabelled items' range, and only theirs")
    tags = item["tags"]
    if not isinstance(tags, list) or len(set(map(str, tags))) != len(tags) or not all(t in TAGS for t in tags):
        out.append("tags: distinct words of the closed list")
        tags = []
    if item["hard"] is not hard_of(tags):
        out.append("hard: differs from the tags")
    clock = parse_clock(item["clock"])
    if clock is None:
        out.append("clock: not YYYY-MM-DDTHH:MM")
    if not zone_ok(item["zone"]):
        out.append("zone: not an IANA zone")
    if item["channel"] not in CHANNELS:
        out.append("channel: unknown")
    if not isinstance(item["forwarded"], bool):
        out.append("forwarded: not a bool")
    line = item["line"]
    if not isinstance(line, str) or not line.strip() or len(line) > MAX_LINE or "\n" in line or "\r" in line:
        out.append(f"line: one line of 1..{MAX_LINE} characters")
        return out
    frame = item["frame"]
    if frame is not None:
        out.extend(frame_problems(frame, cat))
    if "multi-turn" in tags and frame is None:
        out.append("frame: a multi-turn item has a frame")
    if "inherit" in tags and not (isinstance(frame, dict) and frame.get("last")):
        out.append("frame: an inherit item has frame.last")
    if item["forwarded"] is True and "forward" not in tags:
        out.append("tags: a forwarded item is tagged forward")
    if "base" in item:
        base = ID_RE.match(item["base"]) if isinstance(item["base"], str) else None
        if item["author"] != "adv" or base is None or base.group(1) != item["split"] or item["base"] == item["id"]:
            out.append("base: only adversarial items, an id of the same split")
    elif item["author"] == "adv":
        out.append("base: an adversarial item names its base")
    if lines_only:
        return out
    gold = item["gold"]
    out.extend(gold_problems(gold, item, cat))
    is_forward = isinstance(gold, dict) and gold.get("outcome") == "forwarded"
    if is_forward != (item["forwarded"] is True):
        out.append("gold: forwarded exactly when the item is forwarded (L2)")
    also = item["also"]
    if not isinstance(also, list):
        return out + ["also: not a list"]
    scope = gold.get("scope") if isinstance(gold, dict) else None
    for n, alt in enumerate(also):
        out.extend(gold_problems(alt, item, cat, f"also[{n}]", scope))
        if canonical(alt) == canonical(gold):
            out.append(f"also[{n}]: equals the gold")
        if isinstance(alt, dict) and alt.get("outcome") == "op":
            cls = (cat["ops"].get(alt.get("op")) or {}).get("class")
            gold_op = gold.get("op") if isinstance(gold, dict) and gold.get("outcome") == "op" else None
            if cls in EFFECT_CLASSES and alt.get("op") != gold_op:
                out.append(f"also[{n}]: a different effect op")
    return out


def check_items(items, cat, lines_only=False) -> list:
    """`<id> <problem>` for every problem, ids unique across the files included."""
    out, seen = [], set()
    for item in items:
        key = item.get("id") if isinstance(item, dict) else None
        name = key if isinstance(key, str) else "?"
        if name in seen:
            out.append(f"{name} id: not unique")
        seen.add(name)
        try:
            problems = item_problems(item, cat, lines_only)
        except (TypeError, AttributeError, KeyError, ValueError):
            problems = ["item: a value of the wrong type"]  # never a crash on a malformed line, and never its text
        out.extend(f"{name} {p}" for p in problems)
    return out


def require_valid(items, cat, what, lines_only=False):
    problems = check_items(items, cat, lines_only)
    if problems:
        for line in problems[:50]:
            print(line, file=sys.stderr)
        raise UsageError(f"{what}: {len(problems)} problem(s), the first {min(50, len(problems))} above")
