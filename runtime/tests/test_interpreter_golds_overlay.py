"""The gold overlay of CB-9 (OPEN-CB9-4): two golds files, `evals/interpreter/golds-catalog-v2-dev.jsonl` (for the frozen `dev.jsonl`) and `golds-catalog-v2-dev-long-v2.jsonl` (for `dev-long-v2.jsonl`),
each a full copy of its frozen corpus whose `also` is widened by one written rule: an item whose gold is `items {}` also accepts `items` with any non-empty subset of the slots `target`, `day`
and `state`, each a span of the line (every run of whole words of the line, edge punctuation stripped). The catalog of version 2 gives `items` three slots, and the frozen golds were written
when it had none, so an honest `items {day: "amanha"}` is not a wrong read. A file is applied at 0 calls with `interpreter_measure.py --replay <answers> --golds <file>` (a re-score, never evidence);
neither the scorer nor the pipeline is touched; the raw and the overlay figures are both published.

What is checked, with this test's own literals: each file holds the corpus's ids and, for each, every key but `gold` and `also` equal (the harness's own `load_golds` accepts it); exactly the
literal ids are widened, each with its own `also` kept first and seven alternatives after it, each an `items` op with a non-empty subset of the three slots and spans that are pieces of the line; every
other item is byte for byte the corpus item; both files pass the corpus tool's check; an honest `items {day}` is `correct` under the overlay and `wrong_read` under the raw gold, and a span that is
not in the line is not accepted. Offline, no model.

The overlays of catalog version 4 (package P5, SPEC-P5-CATALOG-V4 section 4), `golds-catalog-v4-dev.jsonl` and `golds-catalog-v4-dev-long-v2.jsonl`, are a full copy of the matching v2 overlay whose
`also` is widened by two written rules and nothing else, built by the function `widen_v4` below (the file is that function's output byte for byte): W4-1, an item whose gold or an `also` is `items`
and whose line names calendar nouns and no mail noun (`natural_writes._items_nouns`: a calendar noun plain, no mail noun plain or negated), or whose frame's live plan is a calendar list, also accepts
`agenda` with the same `day` and `target` (no `state`; the one German line `dev-de-50002` is added by hand, `HAND_CALENDAR_IDS`), because `items` is the mail from catalog version 4 and the calendar alone is `agenda`; W4-2, an item whose gold or an `also` is one of the six
mail act ops or `items` (since P5b: the slot `service` of `items`; no item of the two corpora is widened by it, because none of their `items` lines names an account) and whose line names exactly one account (`event_lookup.account_named`) also accepts that answer plus `service`, the brand words of that account that stand in the line. Checked:
the ids and every key but `gold` and `also` equal the corpus, exactly the literal ids the rules widen are widened, every other item is byte for byte the v2 overlay's, and an honest `agenda {day}` is
`correct` under the v4 overlay and `wrong_read` under the v2 one.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_golds_overlay.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

import standin_tree as st

interpreter_measure = st.load("interpreter_measure")
score = st.load("interpreter_score")
natural = st.load("natural")
natural_writes = st.load("natural_writes")
event_lookup = st.load("event_lookup")

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
DEV_GOLDS = FOLDER / "golds-catalog-v2-dev.jsonl"          # evals/interpreter/golds-catalog-v2-dev.jsonl
LONG_GOLDS = FOLDER / "golds-catalog-v2-dev-long-v2.jsonl"          # evals/interpreter/golds-catalog-v2-dev-long-v2.jsonl
PAIRS = ((DEV_GOLDS, FOLDER / "dev.jsonl", ["dev-de-00012", "dev-fr-00002", "dev-fr-00015"], 310),
         (LONG_GOLDS, FOLDER / "dev-long-v2.jsonl", ["dev-de-50002", "dev-en-50005", "dev-en-50008", "dev-pt-br-50012", "dev-pt-br-50013", "dev-pt-br-50016"], 46))
SLOTS = {"target", "day", "state"}
SUBSETS = [{"target"}, {"day"}, {"state"}, {"target", "day"}, {"target", "state"}, {"day", "state"}, {"target", "day", "state"}]


def rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tool(name="interpreter_corpus"):
    spec = importlib.util.spec_from_file_location(f"{name}_golds_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("golds,corpus,widened,count", PAIRS)
def test_the_file_is_accepted_by_the_harness_and_holds_the_corpus_ids(golds, corpus, widened, count):
    items = rows(corpus)
    assert len(items) == count == len(rows(golds))
    got, sha = interpreter_measure.load_golds(str(golds), items)
    assert len(sha) == 64 and [i["id"] for i in got] == [i["id"] for i in items]


@pytest.mark.parametrize("golds,corpus,widened,count", PAIRS)
def test_exactly_the_items_whose_gold_is_items_with_no_slot_are_widened_and_nothing_else_changes(golds, corpus, widened, count):
    raw = {i["id"]: i for i in rows(corpus)}
    new = {i["id"]: i for i in rows(golds)}
    assert sorted(i for i, item in raw.items() if item["gold"].get("op") == "items" and item["gold"].get("slots") == {} and item["gold"].get("outcome") == "op") == widened
    for item_id, item in raw.items():
        if item_id not in widened:
            assert new[item_id] == item, f"{item_id} must be the corpus item byte for byte"
            continue
        mine = new[item_id]
        assert mine["gold"] == item["gold"] and {k: v for k, v in mine.items() if k != "also"} == {k: v for k, v in item.items() if k != "also"}
        assert mine["also"][:len(item["also"])] == item["also"], "the corpus item's own `also` stays first"
        extra = mine["also"][len(item["also"]):]
        assert len(extra) == 7
        assert [set(alt["slots"]) for alt in extra] == SUBSETS
        for alt in extra:
            assert set(alt) == {"op", "outcome", "slots"} and alt["op"] == "items" and alt["outcome"] == "op"
            for slot, spans in alt["slots"].items():
                assert slot in SLOTS and spans and len(set(spans)) == len(spans)
                assert all(s in item["line"] and s == s.strip() for s in spans), (item_id, slot)


@pytest.mark.parametrize("golds,corpus,widened,count", PAIRS)
def test_the_corpus_tool_finds_no_problem_in_the_file(golds, corpus, widened, count):
    catalog = tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")
    assert tool().check_items(rows(golds), catalog) == []


def read_of(slots):
    return {"op": "items", "slots": slots}


def test_an_honest_items_with_a_day_is_wrong_under_the_raw_gold_and_correct_under_the_overlay():
    raw = next(i for i in rows(FOLDER / "dev-long-v2.jsonl") if i["id"] == "dev-pt-br-50012")
    new = next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-pt-br-50012")
    assert raw["line"] == "me mostra o que tenho na agenda amanhã, por favor"      # validate: allow english-only -- the Portuguese line under test
    detail = read_of({"day": "amanhã"})      # validate: allow english-only -- the Portuguese line under test
    assert score.categorize(raw["gold"], raw["also"], "full", "read", detail) == "wrong_read"
    assert score.categorize(new["gold"], new["also"], "full", "read", detail) == "correct"
    both = read_of({"target": "agenda", "day": "amanhã"})      # validate: allow english-only -- the Portuguese line under test
    assert score.categorize(new["gold"], new["also"], "full", "read", both) == "correct"
    assert score.categorize(new["gold"], new["also"], "full", "read", read_of({})) == "correct", "the gold itself still holds"


def test_the_overlay_does_not_accept_a_span_that_is_not_in_the_line_or_a_slot_that_is_not_listed():
    new = next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-pt-br-50012")
    assert score.categorize(new["gold"], new["also"], "full", "read", read_of({"day": "sexta"})) == "wrong_read", "a day the line does not hold"
    assert score.categorize(new["gold"], new["also"], "full", "read", read_of({"place": "agenda"})) == "wrong_read", "a slot items does not have"
    other = next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-pt-br-50000")
    assert other["gold"]["op"] == "event-cancel"
    assert score.categorize(other["gold"], other["also"], "full", "read", read_of({"day": "amanhã"})) == "wrong_read", "an item that is not an items read is not widened"      # validate: allow english-only -- the Portuguese line under test


def test_the_checks_are_not_vacuous(tmp_path):
    items = rows(FOLDER / "dev-long-v2.jsonl")
    planted = [copy.deepcopy(i) for i in rows(LONG_GOLDS)]
    planted[0]["line"] = planted[0]["line"] + " x"          # a key but gold and also differs from the corpus
    path = tmp_path / "planted.jsonl"
    path.write_text("".join(json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for i in planted), encoding="utf-8")
    with pytest.raises(interpreter_measure.Refused):
        interpreter_measure.load_golds(str(path), items)
    short = tmp_path / "short.jsonl"
    short.write_text("".join(json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for i in rows(LONG_GOLDS)[1:]), encoding="utf-8")
    with pytest.raises(interpreter_measure.Refused):
        interpreter_measure.load_golds(str(short), items)
    outside = copy.deepcopy(next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-pt-br-50012"))
    outside["also"][-1]["slots"]["day"].append("nunca escrito na linha")          # a span that is not in the line
    assert any("not in the line" in p for p in tool().check_items([outside], tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")))
    assert re.fullmatch(r"[0-9a-f]{64}", interpreter_measure.load_golds(str(LONG_GOLDS), items)[1])


# --- the overlays of catalog version 4 (P5) -----------------------------------------------------------------------------------------------------------

V4_DEV_GOLDS = FOLDER / "golds-catalog-v4-dev.jsonl"          # evals/interpreter/golds-catalog-v4-dev.jsonl
V4_LONG_GOLDS = FOLDER / "golds-catalog-v4-dev-long-v2.jsonl"          # evals/interpreter/golds-catalog-v4-dev-long-v2.jsonl
V4_PAIRS = ((V4_DEV_GOLDS, DEV_GOLDS, FOLDER / "dev.jsonl", [], 310),
            (V4_LONG_GOLDS, LONG_GOLDS, FOLDER / "dev-long-v2.jsonl", ["dev-de-50002", "dev-en-50005", "dev-pt-br-50012"], 46))      # the literal ids the rules widen: dev.jsonl none (W4-1: its three `items` lines name no calendar noun the tables read, and its lines name no account on a mail act), dev-long-v2 the two calendar-only lines the tables read plus the German "Termine" line widened by hand (HAND_CALENDAR_IDS; the frames of 50008 and 50016 hold no calendar words)
MAIL_ACTS = ("mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash")
SERVICE_OPS = MAIL_ACTS + ("items",)      # W4-2: the ops that take the account word (`items` since P5b)
V4_KEYS = ("also", "gold")
HAND_CALENDAR_IDS = {"dev-de-50002"}      # W4-1 by hand: "Termine" are appointments, the calendar alone, but the engine's tables hold no German calendar noun (supervisor decision 2026-11-05)


def calendar_only(line) -> bool:
    """W4-1 by the line: it names a calendar noun plainly and no mail noun, plain or negated (`natural_writes._items_nouns`, the engine's own tables)."""
    (calendar, _negated), (mail, mail_negated) = natural_writes._items_nouns(natural_writes.Line(line), natural_writes._tables(None))
    return bool(calendar) and not mail and not mail_negated


def calendar_plan(frame) -> bool:
    """W4-1 by the frame: it holds a plan-confirm of `items` and the words of the last request are calendar words only (the frames of the corpora name no kind: `last.words` is empty)."""
    if not frame or not any(i.get("kind") == "plan-confirm" and i.get("op") == "items" for i in frame.get("items") or []):
        return False
    words = " ".join(str(w) for w in ((frame.get("last") or {}).get("words") or {}).values())
    return bool(words) and calendar_only(words)


def service_words(line) -> list:
    """W4-2: the brand words (a single word each) of the one account the line names, as the line writes them; [] when it names none or two."""
    account = event_lookup.account_named(line)
    if account is None:
        return []
    brands = {brand[0] for brand in event_lookup._brands()[account] if len(brand) == 1}
    return [w for w in dict.fromkeys(re.findall(r"[^\W_]+", line)) if natural.normal(w) in brands]


def widen_v4(item: dict) -> dict:
    """The item of a v2 overlay with its `also` widened by W4-1 and W4-2, or the item itself when neither applies."""
    answers = [item["gold"]] + item["also"]
    added = []

    def add(answer):
        if answer not in answers and answer not in added:
            added.append(answer)

    ops = [a for a in answers if a.get("outcome") == "op"]
    if any(a["op"] == "items" for a in ops) and (calendar_only(item["line"]) or calendar_plan(item["frame"]) or item["id"] in HAND_CALENDAR_IDS):
        for a in ops:
            if a["op"] == "items":
                add({"op": "agenda", "outcome": "op", "slots": {k: v for k, v in a["slots"].items() if k in ("target", "day")}})
    words = service_words(item["line"])
    if words:
        for a in ops:
            if a["op"] in SERVICE_OPS and "service" not in a["slots"]:
                add({"op": a["op"], "outcome": "op", "slots": dict(a["slots"], service=words)})
    return dict(item, also=item["also"] + added) if added else item


def canon_line(item: dict) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def v4_text(v2_path: Path) -> str:
    return "".join(canon_line(widen_v4(item)) + "\n" for item in rows(v2_path))


@pytest.mark.parametrize("golds,v2,corpus,widened,count", V4_PAIRS)
def test_v4_the_file_is_the_builders_output_accepted_by_the_harness_and_holds_the_corpus_ids(golds, v2, corpus, widened, count):
    items = rows(corpus)
    assert len(items) == count == len(rows(golds))
    assert golds.read_text(encoding="utf-8") == v4_text(v2), "the file is the output of `widen_v4` over the v2 overlay, byte for byte"
    got, sha = interpreter_measure.load_golds(str(golds), items)
    assert len(sha) == 64 and [i["id"] for i in got] == [i["id"] for i in items]
    assert tool().check_items(rows(golds), tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")) == []


@pytest.mark.parametrize("golds,v2,corpus,widened,count", V4_PAIRS)
def test_v4_exactly_the_literal_ids_are_widened_each_by_agenda_and_nothing_else_changes(golds, v2, corpus, widened, count):
    raw = {i["id"]: i for i in rows(corpus)}
    old = {i["id"]: i for i in rows(v2)}
    new = {i["id"]: i for i in rows(golds)}
    assert [i for i in new if new[i] != old[i]] == widened
    for item_id, item in new.items():
        assert {k: v for k, v in item.items() if k not in V4_KEYS} == {k: v for k, v in raw[item_id].items() if k not in V4_KEYS}, "every key but `gold` and `also` is the corpus's"
        assert item["gold"] == old[item_id]["gold"] and item["also"][:len(old[item_id]["also"])] == old[item_id]["also"], "the v2 overlay's own `also` stays first"
        if item_id not in widened:
            assert canon_line(item) == canon_line(old[item_id]), f"{item_id} must be the v2 overlay's item byte for byte"
            continue
        extra = item["also"][len(old[item_id]["also"]):]
        assert extra and all(a["op"] == "agenda" and a["outcome"] == "op" and set(a) == {"op", "outcome", "slots"} and set(a["slots"]) <= {"target", "day"} for a in extra), item_id
        assert [set(a["slots"]) for a in extra] == [set(), {"target"}, {"day"}, {"target", "day"}], "the four shapes `items` gave, without `state`"
        for a in extra:
            for slot, spans in a["slots"].items():
                assert spans and all(s in item["line"] and s == s.strip() for s in spans), (item_id, slot)


def test_v4_an_honest_agenda_with_a_day_is_wrong_read_under_the_v2_overlay_and_correct_under_the_v4_one():
    old = next(i for i in rows(LONG_GOLDS) if i["id"] == "dev-en-50005")
    new = next(i for i in rows(V4_LONG_GOLDS) if i["id"] == "dev-en-50005")
    assert new["line"] == "show me what's on my calendar for tomorrow afternoon"
    detail = {"op": "agenda", "slots": {"day": "tomorrow"}}
    assert score.categorize(old["gold"], old["also"], "full", "read", detail) == "wrong_read"
    assert score.categorize(new["gold"], new["also"], "full", "read", detail) == "correct"
    assert score.categorize(new["gold"], new["also"], "full", "read", {"op": "agenda", "slots": {}}) == "correct"
    assert score.categorize(new["gold"], new["also"], "full", "read", {"op": "agenda", "slots": {"day": "next year"}}) == "wrong_read", "a day the line does not hold"
    assert score.categorize(new["gold"], new["also"], "full", "read", {"op": "agenda", "slots": {"state": "unread"}}) == "wrong_read", "no `state`"
    assert score.categorize(new["gold"], new["also"], "full", "read", {"op": "items", "slots": {"day": "tomorrow"}}) == "correct", "items still holds (the v2 overlay's own widening)"


def test_v4_the_rules_by_themselves_on_planted_items():
    """W4-1 and W4-2 on lines the corpora do not hold (invented), so that the two rules are checked where the data has no case."""
    base = {"also": [], "author": "opus", "channel": "messaging", "clock": "2026-11-04T14:30", "forwarded": False, "frame": None, "hard": False, "lang": "en", "split": "dev", "tags": [], "zone": "America/New_York"}
    calendar = dict(base, id="x-1", line="list my events for Friday", gold={"op": "items", "outcome": "op", "slots": {}}, also=[{"op": "items", "outcome": "op", "slots": {"day": ["Friday"]}}])
    widened = widen_v4(calendar)
    assert [a["slots"] for a in widened["also"][1:]] == [{}, {"day": ["Friday"]}] and all(a["op"] == "agenda" for a in widened["also"][1:]), "the gold `items {}` gives `agenda {}` and the `also` with a day gives `agenda {day}`"
    both = dict(calendar, id="x-2", line="list my emails and my events for Friday")
    assert widen_v4(both) == both, "a line that names mail plainly is not widened"
    negated = dict(calendar, id="x-3", line="list my events, not the emails")
    assert widen_v4(negated) == negated, "a negated mail noun is not a calendar-only line either"
    nothing = dict(calendar, id="x-4", line="show me the one for Friday")
    assert widen_v4(nothing) == nothing, "no calendar noun, no frame: not widened"
    framed = dict(nothing, id="x-5", frame={"v": 1, "items": [{"age_s": 5, "id": "i1", "kind": "plan-confirm", "need": "confirm", "op": "items"}], "last": {"age_s": 5, "op": "items", "words": {"day": "my events for Friday"}}})
    assert [a["op"] for a in widen_v4(framed)["also"]].count("agenda") >= 1, "a plan whose last words are calendar words is a calendar plan"
    archive = dict(base, id="x-6", line="archive the newsletter email in gmail", gold={"op": "mail-archive", "outcome": "op", "slots": {"target": ["newsletter"]}})
    wide = widen_v4(archive)
    assert wide["also"] == [{"op": "mail-archive", "outcome": "op", "slots": {"target": ["newsletter"], "service": ["gmail"]}}]
    two = dict(archive, id="x-7", line="archive the newsletter email in gmail and in outlook")
    assert widen_v4(two) == two, "two accounts: nothing is added"
    none = dict(archive, id="x-8", line="archive the newsletter email")
    assert widen_v4(none) == none
    listing = dict(base, id="x-9", line="list my emails from gmail", gold={"op": "items", "outcome": "op", "slots": {"state": ["unread"]}})      # P5b: W4-2 covers `items`
    assert widen_v4(listing)["also"] == [{"op": "items", "outcome": "op", "slots": {"state": ["unread"], "service": ["gmail"]}}]
    both_boxes = dict(listing, id="x-10", line="list my emails from gmail and from outlook")
    assert widen_v4(both_boxes) == both_boxes, "two accounts: nothing is added to an items answer either"
