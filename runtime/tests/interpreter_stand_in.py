"""A stand-in model for the fuzzers of the natural writes (S41-11). Not a test file.

The fuzzers used to enter a line through the closed heads of the write families. The product no longer claims a line that way: the interpreter reads it and names the operation (L63), and
`ops_interpret._carry_out` carries the decision out through the same family resolvers. This module is the model's side of that entry, for a test: for a line and the operation its corpus row
says (the gold), `model_text` is what a model that read the line the way the family's own reader does would answer (the spans the family found, the integers it found, the moment it found), and
`perturbed` is the same answer made wrong in one of the four ways a model can be wrong about a value: a span that is not in the line, a number the line does not write, an account the project does
not list, an `inherit` with nothing to inherit. `decide` is the interpreter's own parse and check (`ops_interpret.decide`), so a decision that reaches the carry-out is one the product would carry out.

Every line and name here is the corpus's own, invented.
"""
from __future__ import annotations

import datetime
import json

import standin_tree as st

interpreter = st.load("interpreter")
ops_interpret = st.load("ops_interpret")
natural_writes = st.load("natural_writes")
nt = st.load("natural_time")

ZONE = "America/Sao_Paulo"
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def catalog_slots(op: str) -> dict:
    return next((row["slots"] for row in interpreter.SERVED["ops"] if row["op"] == op), {})


def time_phrase(line: str, tables) -> str:
    """The piece of the line that holds the time: from the first to the last hit of the time engine, as written."""
    hits = nt.find(line, tables)["hits"]
    norm, origin = nt.normalise(line)
    spans = nt._spans({"origin": origin, "hits": hits})
    if not spans:
        return ""
    start, end = min(s for s, _ in spans), max(e for _, e in spans)
    return line[start:end].strip()


def model_text(line: str, op: str, now, tables=None):
    """The model's answer for `line` when its operation is `op` (the corpus row's), or None when the family's reader finds nothing in the line with that operation fixed."""
    reading = natural_writes.read(line, now, op=op)
    if reading is None:
        return None
    wanted, slots, found = catalog_slots(op), {}, reading.get("slots") or {}
    for key, span in (reading.get("spans") or {}).items():
        if key in wanted and isinstance(span, str) and span in line:
            slots[key] = span
    addresses = [a for a in (found.get("to") if isinstance(found.get("to"), list) else [found.get("to")]) if isinstance(a, str) and a in line]
    if "to" in wanted and addresses:      # a recipient is a word of the line (an address written in it)
        slots["to"] = addresses[0]
    if "folder" in wanted and isinstance(found.get("folder_name"), str) and found["folder_name"] in line:
        slots["folder"] = found["folder_name"]
    if "event" in wanted and isinstance(found.get("event"), int):
        slots["event"] = str(found["event"])
    numbers = [n for n in found.get("numbers") or [] if isinstance(n, int)]
    if numbers and "messages" in wanted:
        slots["messages"] = ",".join(str(n) for n in numbers)
    elif numbers and "message" in wanted:
        slots["message"] = str(numbers[0])
    extra = {}
    if "time" in wanted and isinstance(found.get("start"), str):
        phrase = time_phrase(line, tables or nt.languages())
        if phrase:
            slots["time"] = phrase
            moment = datetime.datetime.fromisoformat(found["start"])
            extra = {"time_iso": moment.strftime("%Y-%m-%dT%H:%M"), "weekday": WEEKDAYS[moment.weekday()]}
    return json.dumps({"v": 1, "kind": "op", "op": op, "slots": slots, **extra}, ensure_ascii=False)


def perturbed(text: str, index: int, accounts) -> str:
    """The same answer made wrong in the way `index` modulo 4 says: 0 a span that is not in the line, 1 a number the line does not write, 2 an account the project does not list, 3 an `inherit`
    with nothing to inherit. An answer the way cannot touch (no span slot, no number slot) gets the one that can."""
    obj = json.loads(text)
    slots, wanted = obj["slots"], catalog_slots(obj["op"])
    kind = index % 4
    spans = [k for k in slots if wanted.get(k) == "span" and k != "time"]
    if kind == 0 and spans:
        slots[spans[0]] = "an invented " + slots[spans[0]] + " the person never wrote"
    elif kind == 1 and any(wanted.get(k) in ("int", "ints") for k in wanted):
        key = next(k for k in wanted if wanted[k] in ("int", "ints"))
        slots[key] = "4242"
    elif kind == 2 and "service" in wanted:
        slots["service"] = next(name for name in ("outlook", "yahoo") if name not in accounts)
    else:
        obj["inherit"] = ["title"]
    return json.dumps(obj, ensure_ascii=False)


def decide(line: str, text: str, now, allowed) -> dict:
    """The interpreter's own parse and check of a model text for a line (no frame)."""
    return ops_interpret.decide(line, text, now, ZONE, allowed)
