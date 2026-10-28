"""The echo model over the dev split (package IX-2c; runtime/interpreter_pipeline.py with runtime/interpreter_score.py): a stand-in `call` that answers each item with the
protocol object its own gold implies, so that everything the harness does between the model's answer and the category is measured against a model that is right. Offline: no
model, no network, no key; fictional corpus.

Every item of a 60-item sample of evals/interpreter/dev.jsonl (seed 20261024) is `correct` except a literal allow-list of ids, each with the reason the pipeline, not the echo,
decides it differently (the code reads a time and wins over the echo's `time_iso`; tier 1 decides before the model; a private line asking for work is asked back). With
WB_FULL_FUZZ=1 the whole dev file, and the scope-full items of dev-relabelled.jsonl, run the same way. The echo is also the model of the replay and CLI tests.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_echo.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path

import pytest

import standin_tree as st

pipeline = st.load("interpreter_pipeline")
score = st.load("interpreter_score")
interpreter = st.load("interpreter")

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "evals" / "interpreter" / "dev.jsonl"
RELABELLED = ROOT / "evals" / "interpreter" / "dev-relabelled.jsonl"
SEED = "20261024"
SAMPLE = 60
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TIME_SLOTS = {("remind", "when"), ("event-create", "time"), ("event-change", "time")}          # the test's own list (the protocol's time slots)
D_OP, G_OP = "approve", "give-consent"          # the first refused operation of each class, written here


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def sample(items, n=SAMPLE, seed=SEED):
    ordered = sorted(items, key=lambda i: hashlib.sha256(f"{seed}:{i['id']}".encode("utf-8")).hexdigest())
    return sorted(ordered[:n], key=lambda i: i["id"])


def weekday_of(stamp):
    return WEEKDAYS[datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M").weekday()]


def echo_object(item):
    """The protocol object (a dict) that the gold of `item` implies, or None for an item the echo cannot read (a gold of scope op or time)."""
    gold, frame = item["gold"], item["frame"]
    outcome = gold["outcome"]
    if gold.get("scope", "full") != "full":
        return None
    if outcome == "op":
        slots, inherit = {}, {}
        last = (frame or {}).get("last")
        for slot, accepted in (gold.get("slots") or {}).items():
            span = accepted[0]
            held = ((last or {}).get("words") or {}).get(slot)
            if last and last["op"] == gold["op"] and held and not any(a in item["line"] for a in accepted):
                inherit[slot] = held
            else:
                slots[slot] = span
        obj = {"v": 1, "kind": "op", "op": gold["op"], "slots": slots}
        if inherit:
            obj["inherit"] = inherit
        if any((gold["op"], slot) in TIME_SLOTS for slot in slots):
            obj["time_iso"] = gold["time"][0]
            obj["weekday"] = weekday_of(gold["time"][0])
        return obj
    if outcome == "answer":
        obj = {"v": 1, "kind": "answer", "answers_item": gold["item"]}
        for key in ("option", "confirm", "slot"):
            if key in gold:
                obj[key] = gold[key]
        if "span" in gold:
            obj["span"] = gold["span"][0]
        if "time" in gold:
            obj["time_iso"] = gold["time"][0]
            obj["weekday"] = weekday_of(gold["time"][0])
            obj.setdefault("span", item["line"].strip())
        return obj
    if outcome == "clarify":
        return {"v": 1, "kind": "clarify", "slot": gold.get("slot") or "when"}
    if outcome == "refuse":
        return {"v": 1, "kind": "op", "op": D_OP if gold["class"] == "D" else G_OP, "slots": {}}
    return {"v": 1, "kind": outcome}          # route, none (a forwarded item never reaches the model)


class Echo:
    """The stand-in `call` of one item: it answers with the gold's object, as the route's reply would arrive."""

    def __init__(self, item, calls=None):
        self.item, self.calls = item, calls

    def __call__(self, system, user):
        if self.calls is not None:
            self.calls.append(self.item["id"])
        obj = echo_object(self.item)
        return {"ok": True, "text": json.dumps(obj), "finish": "stop", "usage": {"input": 100, "output": 20, "cache_read": None, "cache_write": None},
                "latency_ms": 5, "upstream": "pinned"}


def run(item):
    """(category, observed) of the echo on one item."""
    outcome = pipeline.run_item(item, 1, Echo(item))
    return score.categorize(item["gold"], item["also"], item["gold"].get("scope", "full"), outcome["observed"], outcome["detail"]), outcome["observed"]


def collapse(text):
    return " ".join(text.split())


def key_of_item(item):
    frame = "null" if item["frame"] is None else interpreter.canonical(item["frame"]).decode("utf-8")
    return collapse(item["line"]), item["clock"], frame


def key_of_user(user):
    """The same key from the five-line user message of a call: the line, the clock and the frame as the model is shown them."""
    rows = user.split("\n")
    assert len(rows) == 5 and rows[0].startswith("today: ") and rows[1].startswith("time: ") and rows[3].startswith("frame: ") and rows[4].startswith("line: ")
    return rows[4][len("line: "):], rows[0][7:17] + "T" + rows[1][6:], rows[3][len("frame: "):]


def unique_items(items):
    """The items whose (line, clock, frame) is the only one of its kind: an echo that is told only the user message can find them."""
    count = {}
    for i in items:
        count[key_of_item(i)] = count.get(key_of_item(i), 0) + 1
    return [i for i in items if count[key_of_item(i)] == 1]


class EchoRoute:
    """A stand-in for `interpreter_route.complete`: it finds the item the user message was built from and answers with the gold's object, as a reply arrives. `calls` lists
    the ids it was asked for, `fail` maps an id to a code to fail with (every call of that item), `texts` maps an id to a text to answer with instead."""

    def __init__(self, items, fail=None, texts=None):
        self.by_key = {key_of_item(i): i for i in items}
        self.calls, self.fail, self.texts = [], dict(fail or {}), dict(texts or {})
        self.accepted = []

    def __call__(self, route_id, system, user, *, accepted, deadline_ms, run=None, root=None, temperature=0, max_tokens=300, reasoning="off"):
        item = self.by_key[key_of_user(user)]
        self.calls.append(item["id"])
        self.accepted.append(list(accepted))
        if item["id"] in self.fail:
            return {"ok": False, "code": self.fail[item["id"]]}
        text = self.texts.get(item["id"]) or json.dumps(echo_object(item))
        return {"ok": True, "text": text, "finish": "stop", "usage": {"input": 3000, "output": 40, "cache_read": 2000, "cache_write": None}, "latency_ms": 9,
                "upstream": "pinned"}


def write_corpus(path, items):
    from pathlib import Path as _Path
    body = "".join(json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for i in sorted(items, key=lambda i: i["id"]))
    _Path(path).write_text(body, encoding="utf-8")
    return body.encode("utf-8")


# The ids of the dev file whose echo is not `correct`, each with why: the pipeline, not the echo, decides them (a literal list).
TIME_ASK = "the code half-reads or doubts the time phrase, so it asks instead of taking the echo's time_iso (clarify time-ask)"
TIME_ASK_GUARD = "TIME-GUARD (#505, decisions.md 2026-10-21): an hour-only reading beside a weekday word of a language with no table (`el jueves a las 15:00`) is asked, never read on the clock's own day (time-ask)"
CODE_WINS = "the code reads the time itself and its reading wins over the echo's time_iso (time_disagree), and it is not the gold's"
CONFIRM_RULE = "the confirm rule: the echo says yes or no, and code does not read the line as that yes or no, so it asks again (clarify)"
FORWARD_OFF_MESSAGING = "the gold is `forwarded` but the channel is not messaging: a forward is read on the messaging channel only (as the current arm reads it), so the item reaches the model, and the echo's `forwarded` object is not a protocol kind (invalid, so clarify)"
MAIL_NOT_PREPARED = "BL7-5: the product does not open this mail card: the numbers the echo names are not written after a mail noun or chained to such a number by a joiner (`natural_writes_mail.free_numbers`: \"emails 2 4 e 7\", no joiner between 2 and 4), so it says it could not prepare the write (clarify)"
MAIL_WRITE_LANGUAGE = "BL7-4: a mail write named by words in a de, es, fr or it project is answered IX_WRITE_LANGUAGE by design (gap G4): the write forms of the tables are read in pt-BR and en only, so the product does not open this card (clarify)"
ALLOWED = {
    "dev-es-00036": TIME_ASK, "dev-es-00043": TIME_ASK, "dev-fr-00018": TIME_ASK, "dev-it-00020": TIME_ASK,
    "dev-pt-br-00007": TIME_ASK, "dev-es-00016": TIME_ASK_GUARD,
    "dev-es-00005": CODE_WINS, "dev-es-00012": CODE_WINS, "dev-es-00033": CODE_WINS,
    "dev-en-00040": FORWARD_OFF_MESSAGING,
    "dev-es-00025": CONFIRM_RULE, "dev-fr-00019": CONFIRM_RULE, "dev-pt-br-00058": CONFIRM_RULE,
    "dev-pt-br-00035": MAIL_NOT_PREPARED,
    "dev-de-00013": MAIL_WRITE_LANGUAGE, "dev-es-00009": MAIL_WRITE_LANGUAGE,
}
FULL = bool(os.environ.get("WB_FULL_FUZZ"))


def off_the_mark(items):
    return {i["id"]: run(i)[0] for i in items if i["gold"].get("scope", "full") == "full" and run(i)[0] != "correct"}


def test_the_echo_model_is_correct_on_every_item_of_the_sample_but_the_listed_ones():
    items = sample(load(DEV))
    assert len(items) == SAMPLE
    assert set(off_the_mark(items)) == {i["id"] for i in items if i["id"] in ALLOWED}, "an item is wrong that is not listed, or a listed item is no longer wrong"


def test_the_sample_reaches_every_stage_and_the_classes_the_mapping_distinguishes():
    items = sample(load(DEV))
    stages, observed = set(), set()
    for one in items:
        out = pipeline.run_item(one, 1, Echo(one))
        stages.add(out["stage"])
        observed.add(out["observed"])
    assert {"model", "forwarded"} <= stages and {"card", "read", "remind_confirm", "route", "clarify", "refuse_d", "refuse_g"} <= observed, (stages, observed)


def test_a_mapping_that_shows_every_effect_as_a_confirm_makes_items_the_list_does_not_allow(monkeypatch):
    items = sample(load(DEV))
    monkeypatch.setitem(pipeline.OBSERVED_OF, "E", "confirm")
    assert set(off_the_mark(items)) - set(ALLOWED), "the oracle sees a changed mapping"


def test_every_listed_id_is_an_item_of_the_dev_file_with_a_reason():
    ids = {i["id"] for i in load(DEV)}
    assert set(ALLOWED) <= ids and all(len(reason) > 20 for reason in ALLOWED.values())


def test_a_forward_is_off_the_mark_exactly_when_the_channel_is_not_messaging():
    """An oracle over the raw items (the test's own literals): of the dev items whose gold is `forwarded`, those on the messaging channel are read as forwards and are correct,
    the others reach the model and the echo cannot answer them (the one listed id of that kind). It runs on the whole file, 9 items, whatever WB_FULL_FUZZ says."""
    forwards = [i for i in load(DEV) if i["gold"]["outcome"] == "forwarded"]
    on_messaging = [i for i in forwards if i["channel"] == "messaging"]
    elsewhere = [i for i in forwards if i["channel"] != "messaging"]
    assert on_messaging and elsewhere and {i["id"] for i in elsewhere} == {k for k, why in ALLOWED.items() if why == FORWARD_OFF_MESSAGING}
    assert set(off_the_mark(on_messaging)) == set() and set(off_the_mark(elsewhere)) == {i["id"] for i in elsewhere}
    planted = dict(on_messaging[0], channel="page")          # vacuity: the same forward on another channel is off the mark
    assert set(off_the_mark([planted])) == {planted["id"]}


@pytest.mark.skipif(not FULL, reason="the whole dev file runs with WB_FULL_FUZZ=1")
def test_the_echo_model_over_the_whole_dev_file_is_wrong_only_where_listed():
    assert set(off_the_mark(load(DEV))) == set(ALLOWED)


# The scope-full items of the relabelled file whose echo is not `correct` (a literal list, as ALLOWED is). It is empty: an answer to a reminder question with a bare whole hour
# ("remind me at 12 to eat", "as 12", "ao meio-dia e meia", "a meia-noite") is read as code, the connector being part of the hour's phrase (R1).
RELABELLED_ALLOWED = {}


@pytest.mark.skipif(not FULL, reason="the relabelled file runs with WB_FULL_FUZZ=1")
def test_the_echo_model_over_the_scope_full_items_of_the_relabelled_file_is_wrong_only_where_listed():
    items = load(RELABELLED)
    assert set(RELABELLED_ALLOWED) <= {i["id"] for i in items} and all(len(reason) > 20 for reason in RELABELLED_ALLOWED.values())
    assert off_the_mark(items) == {k: "clarify" for k in RELABELLED_ALLOWED}


def test_a_bare_hour_answer_with_its_connector_is_correct_and_without_one_it_is_asked():
    """Vacuity of the check above: the four answers that were asked back are correct, and the same answer with the connector taken away (`remind me 12 to eat` has none, and
    `remind Dana 3pm to eat` neither) is off the mark, so the oracle does see a time-ask and an empty list is not an oracle that sees nothing."""
    by_id = {i["id"]: i for i in load(RELABELLED)}
    four = [by_id[k] for k in ("dev-en-10259", "dev-pt-br-10207", "dev-pt-br-10209", "dev-pt-br-10223")]
    assert off_the_mark(four) == {}
    planted = dict(by_id["dev-en-10259"], line="remind Dana 3pm to eat", gold=dict(by_id["dev-en-10259"]["gold"], time=["2026-10-15T15:00"]))
    assert set(off_the_mark([planted])) == {planted["id"]}
