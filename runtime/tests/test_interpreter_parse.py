"""The parser of the interpreter's output (package IX-2a, runtime/interpreter.py `parse`): one JSON object of protocol 1, nothing else.

A literal list of malformed outputs that are all refused, each with the error code it must give; the accepted forms (plain and in one ```json fence); and a seeded mutation fuzz
of valid outputs where every mutant the parser accepts is re-checked by an oracle that is written here and shares nothing with the code under test (closed key lists per kind,
types, a repeated key, NaN, the size, the fence), and where the decision `check` makes on an accepted object is re-checked the same way (a span is a piece of the line as written,
a time is in the future, within a year, and of the weekday it says). Vacuity: a parser that tolerates a repeated key and a validator that skips the substring rule are caught by the
same oracles. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_parse.py
"""
from __future__ import annotations

import datetime
import json
import random
import re
from zoneinfo import ZoneInfo

import interpreter_kit as kit
import standin_tree as st

interp = st.load("interpreter")

MAX_BYTES = 2048
# The oracle's own tables (the protocol's table, written out): required and optional keys of each kind.
REQUIRED = {"op": {"v", "kind", "op", "slots"}, "answer": {"v", "kind", "answers_item"}, "clarify": {"v", "kind"}, "route": {"v", "kind"}, "none": {"v", "kind"}}
OPTIONAL = {"op": {"time_iso", "weekday", "inherit"}, "answer": {"slot", "span", "time_iso", "weekday", "confirm", "option"}, "clarify": {"slot", "ops"}, "route": set(), "none": set()}

VALID = {
    "op": '{"v":1,"kind":"op","op":"remind","slots":{"text":"call Dana","when":"Thursday at 3pm"},"time_iso":"2026-10-22T15:00","weekday":"thu"}',
    "op-no-slots": '{"v":1,"kind":"op","op":"status","slots":{}}',
    "op-inherit": '{"v":1,"kind":"op","op":"event-create","slots":{"time":"friday at 4pm"},"time_iso":"2026-10-23T16:00","weekday":"fri","inherit":{"title":"car service"}}',
    "answer-slot": '{"v":1,"kind":"answer","answers_item":"i1","slot":"to","span":"ben@example.test"}',
    "answer-confirm": '{"v":1,"kind":"answer","answers_item":"i2","confirm":"yes"}',
    "answer-option": '{"v":1,"kind":"answer","answers_item":"i3","option":2}',
    "answer-text": '{"v":1,"kind":"answer","answers_item":"i4"}',
    "clarify-slot": '{"v":1,"kind":"clarify","slot":"to"}',
    "clarify-ops": '{"v":1,"kind":"clarify","ops":["event-create","remind"]}',
    "route": '{"v":1,"kind":"route"}',
    "none": '{"v":1,"kind":"none"}',
}

TWO = '{"v":1,"kind":"none"}'
PAD_PREFIX = '{"v":1,"kind":"op","op":"status","slots":{"since":"'
PAD_SUFFIX = '"}}'


def padded(total_bytes: int) -> str:
    return PAD_PREFIX + "x" * (total_bytes - len(PAD_PREFIX) - len(PAD_SUFFIX)) + PAD_SUFFIX


# (text, the error code it must give). More than forty malformed outputs; none may be accepted.
MALFORMED = [
    ("", "E_JSON"), ("   \n ", "E_JSON"), ("null", "E_SHAPE"), ("[]", "E_SHAPE"), ("42", "E_SHAPE"), ('"x"', "E_SHAPE"), ("true", "E_SHAPE"),
    ("{", "E_JSON"), ('{"v":1,"kind":"none"', "E_JSON"), ('{"v":1,"kind":"none"}}', "E_JSON"), ('{"v":1,"kind":"op","op":"remind","slots":{"text":"call', "E_JSON"),
    (TWO + TWO, "E_JSON"), (TWO + "\n" + TWO, "E_JSON"), (TWO + " trailing words", "E_JSON"), ("Sure! Here is the JSON: " + TWO, "E_JSON"), (TWO + "\n```", "E_JSON"),
    ('{"v":1,"v":1,"kind":"none"}', "E_JSON"), ('{"v":1,"kind":"none","kind":"route"}', "E_JSON"), ('{"v":1,"kind":"op","op":"status","slots":{"a":"x","a":"y"}}', "E_JSON"),
    ('{"v":2,"kind":"none"}', "E_VERSION"), ('{"v":"1","kind":"none"}', "E_VERSION"), ('{"v":true,"kind":"none"}', "E_VERSION"), ('{"v":1.0,"kind":"none"}', "E_VERSION"),
    ('{"v":null,"kind":"none"}', "E_VERSION"), ('{"kind":"none"}', "E_VERSION"),
    ('{"v":1}', "E_SHAPE"), ('{"v":1,"kind":"wait"}', "E_SHAPE"), ('{"v":1,"kind":5}', "E_SHAPE"), ('{"v":1,"kind":"none","extra":1}', "E_SHAPE"),
    ('{"v":1,"kind":"route","op":"status"}', "E_SHAPE"),
    ('{"v":1,"kind":"clarify","slot":NaN}', "E_JSON"), ('{"v":1,"kind":"op","op":"status","slots":{},"x":Infinity}', "E_JSON"), ('{"v":1,"kind":"none","x":-Infinity}', "E_JSON"),
    ('{"v":1,"kind":"op","op":"status"}', "E_SHAPE"), ('{"v":1,"kind":"op","op":5,"slots":{}}', "E_SHAPE"), ('{"v":1,"kind":"op","op":"Status","slots":{}}', "E_SHAPE"),
    ('{"v":1,"kind":"op","op":"status","slots":[]}', "E_SHAPE"), ('{"v":1,"kind":"op","op":"pending","slots":{"id":3}}', "E_SHAPE"),
    ('{"v":1,"kind":"op","op":"status","slots":{"Bad Slot":"x"}}', "E_SHAPE"), ('{"v":1,"kind":"op","op":"status","slots":{},"inherit":{"a":1}}', "E_SHAPE"),
    ('{"v":1,"kind":"clarify","slot":"to","ops":["a","b"]}', "E_SHAPE"), ('{"v":1,"kind":"clarify"}', "E_SHAPE"), ('{"v":1,"kind":"clarify","ops":["remind"]}', "E_SHAPE"),
    ('{"v":1,"kind":"clarify","ops":["a","b","c","d"]}', "E_SHAPE"), ('{"v":1,"kind":"clarify","ops":["remind","remind"]}', "E_SHAPE"),
    ('{"v":1,"kind":"answer","slot":"to","span":"x"}', "E_SHAPE"), ('{"v":1,"kind":"answer","answers_item":"i0"}', "E_SHAPE"), ('{"v":1,"kind":"answer","answers_item":"i10"}', "E_SHAPE"),
    ('{"v":1,"kind":"answer","answers_item":"i1","slot":"to"}', "E_SHAPE"), ('{"v":1,"kind":"answer","answers_item":"i1","confirm":"maybe"}', "E_SHAPE"),
    ('{"v":1,"kind":"answer","answers_item":"i1","option":0}', "E_SHAPE"), ('{"v":1,"kind":"answer","answers_item":"i1","option":true}', "E_SHAPE"),
    ('{"v":1,"kind":"answer","answers_item":"i1","option":2,"confirm":"yes"}', "E_SHAPE"),
    ('{"v":1,"kind":"op","op":"remind","slots":{},"time_iso":"2026-10-22T15:00"}', "E_SHAPE"), ('{"v":1,"kind":"op","op":"remind","slots":{},"weekday":"thu"}', "E_SHAPE"),
    ('{"v":1,"kind":"op","op":"remind","slots":{},"time_iso":"2026-10-22T15:00","weekday":"thursday"}', "E_SHAPE"),
    ('{"v":1,"kind":"op","op":"remind","slots":{},"time_iso":"2026-02-30T10:00","weekday":"mon"}', "E_TIME_FORMAT"),
    ('{"v":1,"kind":"op","op":"remind","slots":{},"time_iso":"2026-10-22 15:00","weekday":"thu"}', "E_TIME_FORMAT"),
    ('{"v":1,"kind":"op","op":"remind","slots":{},"time_iso":"2026-10-22T15:00:00","weekday":"thu"}', "E_TIME_FORMAT"),
    ('{"v":1,"kind":"op","op":"remind","slots":{},"time_iso":"2026-10-22T24:00","weekday":"thu"}', "E_TIME_FORMAT"),
    ('{"v":1,"kind":"op","op":"remind","slots":{},"time_iso":"２０２６-10-22T15:00","weekday":"thu"}', "E_TIME_FORMAT"),
    ("```json\n```json\n" + TWO + "\n```\n```", "E_JSON"), ("```\n" + TWO + "\n```", "E_JSON"), ("```json\n" + TWO + "\n```\n```json\n" + TWO + "\n```", "E_JSON"),
    ("```json\n" + TWO + "\n``` and then some words", "E_JSON"), ("```json\n" + TWO, "E_JSON"), ("```JSON\n" + TWO + "\n```", "E_JSON"), ("``` json\n" + TWO + "\n```", "E_JSON"),
    (padded(MAX_BYTES + 1), "E_SIZE"), (padded(MAX_BYTES + 1000), "E_SIZE"), ("\ufeff" + TWO, "E_JSON"),
    ('{"v":1,"kind":"op","op":"status","slots":{"since":"\\ud800"}}', "E_JSON"), ('{"v":1,"kind":"op","op":"status","slots":{"since":"a\\u0000b"}}', "E_JSON"),
    ("{'v':1,'kind':'none'}", "E_JSON"), ('{"v":1,"kind":"none",}', "E_JSON"), ('{"v":1,"kind":"none"} // done', "E_JSON"), ('{"v":1,/*x*/"kind":"none"}', "E_JSON"),
    ("[" * 3000 + "]" * 3000, "E_SIZE"), ("[" * 1000 + "]" * 1000, "E_JSON"), ("<json>" + TWO + "</json>", "E_JSON"), ("v=1 kind=none", "E_JSON"),
    ('{"v":1,"kind":"op","op":"status","slots":{"a":"b"},"slots":{}}', "E_JSON"),
]


def read_fence(text: str):
    """The oracle's reading of the optional fence: (inner, "fenced" | "ok"), or None when a fence is malformed."""
    body = text.strip()
    if not body.startswith("```"):
        return body, "ok"
    match = re.fullmatch(r"```json[ \t]*\r?\n(.*?)\r?\n?```", body, re.S)
    if not match or "```" in match.group(1):
        return None
    return match.group(1).strip(), "fenced"


def violations(text: str, obj) -> list:
    """Why an object the parser accepted should have been refused, by this test's own rules; [] when the acceptance is right."""
    out = []
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        out.append("size")
    read = read_fence(text)
    if read is None:
        return out + ["fence"]
    inner = read[0]

    def pairs(items):
        keys = [k for k, _v in items]
        if len(keys) != len(set(keys)):
            raise ValueError("repeated key")
        return dict(items)

    def constant(_name):
        raise ValueError("NaN")
    try:
        again = json.loads(inner, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as error:
        return out + [f"json: {error}"]
    if again != obj:
        out.append("not the object of the text")
    if not isinstance(obj, dict) or type(obj.get("v")) is not int or obj.get("v") != 1:
        return out + ["version"]
    kind = obj.get("kind")
    if not isinstance(kind, str) or kind not in REQUIRED:
        return out + ["kind"]
    keys = set(obj)
    if not REQUIRED[kind] <= keys:
        out.append("missing key")
    if keys - REQUIRED[kind] - OPTIONAL[kind]:
        out.append("unknown key")
    for key, value in obj.items():
        if key in ("kind", "op", "slot", "span", "time_iso", "weekday", "answers_item", "confirm") and not isinstance(value, str):
            out.append(f"{key} is not a string")
        if key == "option" and (type(value) is not int or not 1 <= value <= 9):
            out.append("option")
        if key in ("slots", "inherit") and not (isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())):
            out.append(f"{key} is not an object of strings")
        if key == "ops" and not (isinstance(value, list) and 2 <= len(value) <= 3 and all(isinstance(o, str) for o in value) and len(set(value)) == len(value)):
            out.append("ops")
    if kind == "clarify" and ("slot" in obj) == ("ops" in obj):
        out.append("clarify needs exactly one of slot and ops")
    if ("time_iso" in obj) != ("weekday" in obj):
        out.append("time_iso and weekday go together")
    if "time_iso" in obj and isinstance(obj["time_iso"], str):
        try:
            datetime.datetime.strptime(obj["time_iso"], "%Y-%m-%dT%H:%M")
        except ValueError:
            out.append("time_iso")
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}", obj["time_iso"]):
            out.append("time_iso shape")
    if "weekday" in obj and obj["weekday"] not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
        out.append("weekday")
    if "confirm" in obj and obj["confirm"] not in ("yes", "no"):
        out.append("confirm")

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for k, v in value.items():
                yield k
                yield from strings(v)
        elif isinstance(value, list):
            for v in value:
                yield from strings(v)
    for text_value in strings(obj):
        try:
            text_value.encode("utf-8")
        except UnicodeEncodeError:
            out.append("surrogate")
        if "\x00" in text_value:
            out.append("NUL")
    return out


# --- the literal list ---------------------------------------------------------------------------------------------------------------------------------

def test_the_list_of_malformed_outputs_is_long_enough():
    assert len(MALFORMED) >= 40
    assert len({text for text, _code in MALFORMED}) == len(MALFORMED)


def test_every_malformed_output_is_refused_with_its_code():
    wrong = []
    for text, code in MALFORMED:
        got = interp.parse(text)
        if got != (None, "invalid", code):
            wrong.append((text[:60], code, got[2]))
    assert wrong == []


def test_the_boundary_of_the_size_is_2048_bytes_and_counts_bytes_not_characters():
    assert interp.parse(padded(MAX_BYTES))[1:] == ("ok", None)
    assert interp.parse(padded(MAX_BYTES + 1)) == (None, "invalid", "E_SIZE")
    wide = PAD_PREFIX + "é" * ((MAX_BYTES - len(PAD_PREFIX) - len(PAD_SUFFIX)) // 2 + 1) + PAD_SUFFIX          # fewer characters than the limit, more bytes
    assert len(wide) < MAX_BYTES < len(wide.encode("utf-8"))
    assert interp.parse(wide) == (None, "invalid", "E_SIZE")


def test_no_text_is_state_none_and_a_non_string_is_invalid():
    assert interp.parse(None) == (None, "none", "E_JSON")
    assert interp.parse(b'{"v":1,"kind":"none"}') == (None, "invalid", "E_JSON")
    assert interp.parse(5) == (None, "invalid", "E_JSON")


def test_every_valid_form_is_accepted_plain_and_in_one_fence():
    for name, text in VALID.items():
        obj, state, error = interp.parse(text)
        assert (state, error) == ("ok", None), name
        assert obj == json.loads(text)
        for fenced in ("```json\n" + text + "\n```", "  ```json  \r\n" + text + "\r\n```  \n", "```json\n" + text + "```"):
            again, state, error = interp.parse(fenced)
            assert (again, state, error) == (obj, "fenced", None), name
        assert violations(text, obj) == []


def test_whitespace_around_the_object_is_tolerated_and_unicode_text_is_kept():
    obj, state, _error = interp.parse('\n  {"v":1,"kind":"op","op":"mail-send","slots":{"subject":"reuni\u00e3o de mar\u00e7o – 会議"}}  \n')
    assert state == "ok" and obj["slots"]["subject"] == "reuni\u00e3o de mar\u00e7o – 会議"


# --- the fuzz -----------------------------------------------------------------------------------------------------------------------------------------

SEEDS = list(VALID.values()) + [
    '{"v":1,"kind":"op","op":"mail-archive","slots":{"messages":"3,7"}}',
    '{"v":1,"kind":"op","op":"mail-send","slots":{"to":"ben@example.test","subject":"the invoice","body":"it is attached"}}',
    '{"v":1,"kind":"op","op":"approve","slots":{}}',
    '{"v":1,"kind":"op","op":"pending","slots":{"id":"12"}}',
    '{"v":1,"kind":"op","op":"remind","slots":{"text":"call Dana","when":"Dana"},"time_iso":"2026-10-22T15:00","weekday":"thu"}',
    '{"v":1,"kind":"op","op":"remind","slots":{"text":"call Dana","when":"at 3pm"},"time_iso":"2026-10-22T15:00","weekday":"thu"}',
    '{"v":1,"kind":"answer","answers_item":"i2","confirm":"yes","slot":"when","span":"at 3pm","time_iso":"2026-10-22T15:00","weekday":"thu"}',
    '{"v":1,"kind":"answer","answers_item":"i1","slot":"when","span":"friday at 4pm","time_iso":"2026-10-23T16:00","weekday":"fri"}',
    "```json\n" + VALID["op"] + "\n```",
]
ALPHABET = list('{}[]",:\\ \n\t0123456789abcdefghijklmnopqrstuvwxyzABC-_.é\u00e7会\u2028\ud800\x00`') + ["null", "true", "NaN", "1e999", "-0", '"v"', '"kind"', '"op"', "```", "```json"]
LINE = "remind me to call Dana Thursday at 3pm, then archive messages 3 and 7 and write to ben@example.test the invoice"


def mutate(rng: random.Random, text: str) -> str:
    for _ in range(rng.choice((1, 1, 2, 3))):
        n = len(text)
        how = rng.randrange(14)
        if how == 0 and n:
            i = rng.randrange(n)
            text = text[:i] + text[i + 1:]
        elif how == 1:
            i = rng.randrange(n + 1)
            text = text[:i] + rng.choice(ALPHABET) + text[i:]
        elif how == 2 and n:
            i = rng.randrange(n)
            text = text[:i] + rng.choice(ALPHABET) + text[i + 1:]
        elif how == 3 and n:
            i = rng.randrange(n)
            j = min(n, i + rng.randrange(1, 12))
            text = text[:j] + text[i:j] + text[j:]
        elif how == 4 and n > 1:
            i = rng.randrange(n - 1)
            text = text[:i] + text[i + 1] + text[i] + text[i + 2:]
        elif how == 5 and n:
            text = text[:rng.randrange(n)]
        elif how == 6:
            text = text + rng.choice((" ", "\n", "x", "}", TWO, "\n```", "."))
        elif how == 7:
            text = rng.choice(SEEDS) + rng.choice(("", "\n")) + text
        elif how == 8:
            try:
                obj = json.loads(text)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj:
                key = rng.choice(sorted(obj))
                pick = rng.randrange(6)
                if pick == 0:
                    del obj[key]
                elif pick == 1:
                    obj[key] = rng.choice([None, True, 0, 2, 1.5, [], {}, "", "x", ["a"], {"a": "b"}])
                elif pick == 2:
                    obj[rng.choice(["extra", "slot", "span", "op", "option", "confirm"])] = rng.choice(["x", 1, "yes", None])
                elif pick == 3:
                    obj["v"] = rng.choice([0, 2, "1", True])
                elif pick == 4:
                    obj["kind"] = rng.choice(["op", "answer", "clarify", "route", "none", "wait"])
                else:
                    obj = [obj]
                text = json.dumps(obj, ensure_ascii=rng.random() < 0.5)
        elif how == 9:
            text = "```json\n" + text + "\n```"
        elif how == 10:
            text = text.replace('"', "'", 1) if rng.random() < 0.3 else text.replace(",", ",,", 1)
        elif how == 11 and n:
            text = text.replace(rng.choice(("1", "o", "e", "s")), rng.choice(("2", "0", "")), 1)
        elif how == 12:
            text = text[:-1] + "x" * rng.choice((0, 2040, 2100)) + text[-1:] if text else text
        else:
            text = text.strip() if rng.random() < 0.5 else " " + text
    return text


# The words of the line that mean a time, written out by this test (English and Portuguese, the languages of the tables): a time the model alone decided on such a line is a fault.
TIME_WORDS = ("tomorrow", "today", "tonight", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "december", "next week", "noon", "midnight",
              "amanha", "hoje", "segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo", "janeiro", "dezembro", "meio-dia", " 3pm", " 5pm", "pm", "am ", ":")


def decision_violations(decision: dict, line: str, frame_words: dict, now: datetime.datetime, allowed=None, live_ids=None) -> list:
    """The oracle of a decision `check` made for the fixed line below, written from the protocol's rules and not from the code: what an op carries is a piece of the line as written
    (a number slot: digits that are written in the line), an inherited slot is a piece of the sender's earlier words, a time is in the future, within 366 days and of its weekday."""
    out = []
    kind = decision.get("kind")
    if allowed is not None and kind == "op" and decision["op"] not in allowed:
        out.append("an op outside the policy")
    if allowed is not None and kind == "answer" and decision.get("item") not in (live_ids or ()):
        out.append("an answer to an item that is not live")
    if kind == "answer" and decision.get("span") is not None and decision["span"] not in line and decision["span"] not in " ".join(line.split()):
        out.append("an answer span that is not in the line")
    if kind == "clarify" and allowed is not None and any(name not in allowed for name in (decision.get("ops") or [])):
        out.append("a clarify that names an op outside the policy")
    if kind in ("refuse",) and decision.get("op") not in kit.D_OPS + kit.WIDENING:
        out.append("refused an op that is neither a decision nor a widening")
    if kind == "op":
        if decision["op"] in kit.D_OPS + kit.WIDENING + kit.INTERNAL + kit.WORK_NOT_ASK:
            out.append("an op that is not in the vocabulary was accepted")
        flat = " ".join(line.split())
        for slot, span in decision["spans"].items():
            if slot in decision["inherited"]:
                if span not in frame_words.get(slot, ""):
                    out.append(f"inherited {slot} is not in the earlier words")
            elif span in line or span in flat:
                continue
            elif re.fullmatch(r"[0-9]{1,9}(,[0-9]{1,9})*", span) and all(re.search(r"(?<![0-9])" + n + r"(?![0-9])", line) for n in span.split(",")):
                continue
            else:
                out.append(f"span of {slot} is not in the line")
    when = decision.get("time")
    if when:
        local = datetime.datetime.strptime(when["local"], "%Y-%m-%dT%H:%M").replace(tzinfo=ZoneInfo(kit.ZONE))
        if not now < local <= now + datetime.timedelta(days=366):
            out.append("a time outside the next 366 days")
        if when["source"] not in ("code", "model"):
            out.append("a time without a source")
        if when["source"] == "model" and any(word in " " + line.lower() for word in TIME_WORDS):
            out.append("the model's own time on a line that holds a time word")
    return out


ALLOWED = kit.ALL_OPS - {"mail-archive", "event-change", "pending"}          # the sender's policy in the fuzz: not every op


def run_fuzz(parse, check, count: int, seed: int):
    rng = random.Random(seed)
    frame = {"v": 1, "items": [kit.item("i1", need="slot", slot="to"), {"id": "i2", "kind": "reminder-confirm", "need": "confirm", "op": "remind", "age_s": 5},
                               {"id": "i3", "kind": "choice", "need": "option", "options": 3, "age_s": 5}, {"id": "i4", "kind": "router-question", "need": "text", "age_s": 5}],
             "last": {"op": "event-create", "words": {"title": "car service"}, "age_s": 30}}
    assert interp.frame_problems(frame, kit.CATALOG) == []
    accepted = refused = decided = wrong = 0
    wrong_cases = []
    for _ in range(count):
        text = mutate(rng, rng.choice(SEEDS))
        obj, state, error = parse(text)
        if obj is None:
            refused += 1
            assert state in ("invalid", "none") and error is not None
            continue
        accepted += 1
        bad = violations(text, obj)
        if bad:
            wrong += 1
            wrong_cases.append((text[:80], bad))
            continue
        decision = check(obj, LINE, frame, kit.CATALOG, kit.NOW, kit.ZONE, ALLOWED)
        decided += decision["kind"] in ("op", "answer")
        found = decision_violations(decision, LINE, frame["last"]["words"], kit.NOW, ALLOWED, {"i1", "i2", "i3", "i4"})
        if found:
            wrong += 1
            wrong_cases.append((text[:80], found))
    return accepted, refused, decided, wrong, wrong_cases


def test_the_fuzz_of_20000_mutants_has_no_wrongly_accepted_object():
    accepted, refused, decided, wrong, cases = run_fuzz(interp.parse, interp.check, 20000, 20261020)
    assert wrong == 0, cases[:3]
    # The run is not trivial: it accepts some mutants, refuses many, and some accepted objects reach a decision.
    assert accepted >= 1500 and refused >= 8000 and decided >= 100, (accepted, refused, decided)


# --- vacuity: the oracles catch planted faults ----------------------------------------------------------------------------------------------------------

def test_vacuity_a_parser_that_tolerates_a_repeated_key_is_caught_by_the_oracle():
    def lax(text):
        try:
            obj = json.loads(text)
        except ValueError:
            return None, "invalid", "E_JSON"
        return obj, "ok", None
    text = '{"v":1,"v":1,"kind":"none"}'
    assert lax(text)[0] is not None and violations(text, lax(text)[0])
    assert interp.parse(text)[0] is None
    accepted, refused, decided, wrong, _cases = run_fuzz(lax, interp.check, 4000, 7)
    assert wrong > 0


def test_vacuity_a_parser_that_ignores_the_size_nan_and_unknown_keys_is_caught():
    for text, why in ((padded(MAX_BYTES + 5), "size"), ('{"v":1,"kind":"none","x":NaN}', "json"), ('{"v":1,"kind":"none","x":1}', "unknown key"), ('{"v":1.0,"kind":"none"}', "version")):
        try:
            obj = json.loads(text)
        except ValueError:
            continue
        assert any(why in v for v in violations(text, obj)), (why, violations(text, obj))


def test_vacuity_a_validator_that_skips_the_substring_rule_is_caught_by_the_decision_oracle():
    def credulous(obj, line, frame, catalog, now, zone, allowed):
        return {"kind": "op", "error": None, "op": obj.get("op", "status"), "args": {}, "spans": dict(obj.get("slots", {})), "time": None, "inherited": [], "time_disagree": False}
    planted = {"v": 1, "kind": "op", "op": "mail-send", "slots": {"to": "mallory@example.test"}}
    assert decision_violations(credulous(planted, LINE, None, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS), LINE, {}, kit.NOW)
    assert decision_violations(interp.check(planted, LINE, None, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS), LINE, {}, kit.NOW) == []
    assert interp.check(planted, LINE, None, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)["kind"] == "clarify"
    accepted, refused, decided, wrong, _cases = run_fuzz(interp.parse, credulous, 6000, 11)
    assert wrong > 0


def test_vacuity_the_decision_oracle_catches_a_model_time_on_a_time_line_a_policy_breach_and_a_dead_item():
    base = {"kind": "op", "op": "remind", "spans": {}, "inherited": [], "time": {"local": "2026-10-22T15:00", "source": "model"}}
    assert any("model's own time" in v for v in decision_violations(base, LINE, {}, kit.NOW))
    assert not decision_violations(base, "call Dana", {}, kit.NOW)
    assert any("policy" in v for v in decision_violations(dict(base, time=None, op="mail-archive"), LINE, {}, kit.NOW, ALLOWED))
    assert any("not live" in v for v in decision_violations({"kind": "answer", "item": "i9"}, LINE, {}, kit.NOW, ALLOWED, {"i1"}))
    assert any("names an op" in v for v in decision_violations({"kind": "clarify", "ops": ["mail-archive", "remind"]}, LINE, {}, kit.NOW, ALLOWED))


def test_vacuity_a_time_in_the_past_is_caught_by_the_decision_oracle():
    decision = {"kind": "op", "op": "remind", "spans": {}, "inherited": [], "time": {"local": "2026-10-19T09:00", "source": "model"}}
    assert decision_violations(decision, LINE, {}, kit.NOW)
    assert decision_violations({**decision, "time": {"local": "2027-10-22T09:00", "source": "model"}}, LINE, {}, kit.NOW)

# --- nesting (review of #495, B2) ------------------------------------------------------------------------------------------------------------------------

def test_no_depth_of_nesting_raises_and_every_deep_output_is_refused():
    for depth in list(range(5, 60)) + list(range(60, 1021, 7)) + [1020, 1021]:
        for text in ("[" * depth + "]" * depth, '{"a":' * depth + "1" + "}" * depth, '{"v":1,"kind":"op","op":"status","slots":{"a":' + "[" * depth + "]" * depth + "}}",
                     '{"v":1,"kind":"none","x":' + '{"a":' * depth + "1" + "}" * depth + "}"):
            if len(text.encode("utf-8")) > MAX_BYTES:
                continue
            got = interp.parse(text)
            assert got[0] is None and got[1] == "invalid" and got[2] in ("E_JSON", "E_SHAPE", "E_SIZE"), (depth, got)


def test_the_700_byte_nested_output_of_the_review_is_refused():
    text = '{"v":1,"kind":"op","op":"status","slots":{},"inherit":' + '{"a":' * 120 + '"x"' + "}" * 120 + "}"
    assert 600 < len(text) < 800
    assert interp.parse(text)[0] is None


def test_the_nesting_the_protocol_needs_is_accepted_and_brackets_inside_strings_do_not_count():
    for key in ("op", "answer-slot", "clarify-ops", "op-inherit"):
        assert interp.parse(VALID[key])[1:] == ("ok", None)
    text = '{"v":1,"kind":"op","op":"status","slots":{"since":"[[[[[[[[[[[[[[[[[[[[ {{{{{{{{{{{{{{{{ \\" [[[["}}'
    assert interp.parse(text)[1:] == ("ok", None)
    assert interp.parse('{"v":1,"kind":"clarify","ops":["a-b","c-d"]}')[1:] == ("ok", None)


def test_a_failure_inside_the_shape_check_is_a_refusal_not_an_exception(monkeypatch):
    def boom(_obj):
        raise RecursionError("planted")
    monkeypatch.setattr(interp, "_shape", boom)
    assert interp.parse(VALID["none"]) == (None, "invalid", "E_JSON")
    assert interp.check({"v": 1, "kind": "none"}, "hi", None, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)["error"] == "E_JSON"


def test_vacuity_a_validator_that_decides_the_time_from_the_span_alone_is_caught_by_the_fuzz(monkeypatch):
    real = interp._classify
    monkeypatch.setattr(interp, "_classify", lambda span, line, now_local: real(span, span, now_local))          # the fault of the review: the model chooses the span
    accepted, refused, decided, wrong, cases = run_fuzz(interp.parse, interp.check, 6000, 20261020)
    assert wrong > 0 and any("model's own time" in str(c) or "outside the next" in str(c) for c in cases), cases[:2]
