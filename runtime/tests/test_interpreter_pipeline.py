"""The B-prime arm for one item (package IX-2c; runtime/interpreter_pipeline.py): the order of its stages, the confirm rule, the forward rule, the measurement-only mapping from a
decision to `observed`, and the corpus-item check. A stand-in `call` raises unless the item reaches the model, so a stage that should have decided is proved by the call not being
made. The oracle is this file's own literal lines and tables, and the served catalog read as raw JSON. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_pipeline.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import standin_tree as st

pipeline = st.load("interpreter_pipeline")
interpreter = st.load("interpreter")

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "runtime" / "interpreter_catalog.json").read_text(encoding="utf-8"))
TAXONOMY = json.loads((ROOT / "evals" / "interpreter" / "taxonomy.json").read_text(encoding="utf-8"))
CLOCK = "2026-10-22T14:00"

LONG = "marca " + "x" * 1000                      # 1,006 characters: over the 1,000 the protocol sends


def item(line="hello there", **over):
    base = {"id": "dev-en-00001", "split": "dev", "lang": "en", "hard": False, "clock": CLOCK, "zone": "America/Sao_Paulo", "channel": "messaging", "forwarded": False,
            "frame": None, "line": line, "gold": {"outcome": "none"}, "also": []}
    base.update(over)
    return base


def frame(*items, last=None):
    return {"v": 1, "items": list(items), "last": last}


def confirm_item(id="i1", age=30, **more):
    return {"id": id, "kind": "reminder-confirm", "need": "confirm", "op": "remind", "age_s": age, **more}


def option_item(id="i1", age=30, options=3):
    return {"id": id, "kind": "choice", "need": "option", "options": options, "age_s": age}


def never(system, user):
    raise AssertionError("the model was called")


class Model:
    """A stand-in `call` that answers with a fixed text and counts how often it is asked."""

    def __init__(self, text="{}", ok=True, code=None):
        self.text, self.ok, self.code, self.calls = text, ok, code, 0

    def __call__(self, system, user):
        self.calls += 1
        if not self.ok:
            return {"ok": False, "code": self.code, "latency_ms": 40}
        return {"ok": True, "text": self.text, "finish": "stop", "usage": {"input": 10, "output": 5, "cache_read": None, "cache_write": None}, "latency_ms": 12,
                "upstream": "pinned"}


def says(**obj):
    return json.dumps({"v": 1, **obj})


# --- the stages decide before the model -------------------------------------------------------------------------------------------------------------------

def test_a_forwarded_item_is_forwarded_and_calls_nothing():
    for mark in (True, "yes", None, 1, []):
        out = pipeline.run_item(item("marca dentista quinta às 10h", forwarded=mark), 1, never)
        assert (out["observed"], out["stage"], out["call"], out["parse"]) == ("forwarded", "forwarded", None, "none"), mark
    assert pipeline.pre_model(item(forwarded=False)) is None, "false is the only mark that is not a forward"
    for channel in ("page", "terminal", "chat"):
        assert pipeline.pre_model(item("approve 4", forwarded=True, channel=channel))["observed"] == "refuse_d", "only the messaging channel carries the mark, as in the current arm"
    absent = item()
    del absent["forwarded"]
    assert pipeline.pre_model(absent) is None


def test_the_forward_comes_before_the_length_check():
    out = pipeline.run_item(item(LONG, forwarded=True), 1, never)
    assert out["observed"] == "forwarded"


def test_a_line_over_the_limit_is_never_sent():
    out = pipeline.run_item(item(LONG), 1, never)
    assert (out["observed"], out["stage"], out["call"]) == ("route", "precheck", None)
    private = pipeline.run_item(item("me lembra amanhã às 9 de " + "regar " * 200), 1, never)  # validate: allow english-only -- a fictional Portuguese line or word, the input under test
    assert (private["observed"], private["why"], private["stage"]) == ("clarify", "long-line", "precheck"), "a private line is asked back, not routed"
    assert len(LONG) > interpreter.PROTOCOL["max_line_chars"]


@pytest.mark.parametrize("line,answer", [("yes", "yes"), ("sim", "yes"), ("no", "no"), ("não", "no"), ("cancel", "no"), ("ok", "yes"), ("oui", "yes"), ("nein", "no")])  # validate: allow english-only -- a fictional Portuguese line or word, the input under test
def test_a_closed_confirm_is_answered_by_code_when_code_reads_the_same_yes_or_no(line, answer):
    out = pipeline.run_item(item(line, frame=frame(confirm_item())), 1, never)
    assert (out["observed"], out["stage"], out["detail"]) == ("answer", "closed", {"item": "i1", "confirm": answer})


@pytest.mark.parametrize("line", ["sí, dale", "sure thing", "talvez", "yes, but at 10", "negativo", "nao, melhor às 10h30"])
def test_a_line_code_does_not_read_as_yes_or_no_goes_to_the_model(line):
    model = Model(says(kind="none"))
    out = pipeline.run_item(item(line, frame=frame(confirm_item())), 1, model)
    assert model.calls == 1 and out["stage"] == "model" and out["parse"] == "ok"


def test_the_model_cannot_confirm_what_code_does_not_read_as_a_yes():
    out = pipeline.run_item(item("sure thing", frame=frame(confirm_item())), 1, Model(says(kind="answer", answers_item="i1", confirm="yes")))
    assert out["observed"] == "clarify" and out["why"] == "model", "the confirm rule: a model confirm only when code reads the same yes or no"


def test_a_digit_answers_an_option_of_the_newest_item_and_nothing_else_does():
    out = pipeline.run_item(item("2", frame=frame(option_item(options=3))), 1, never)
    assert (out["observed"], out["stage"], out["detail"]) == ("answer", "closed", {"item": "i1", "option": 2})
    for line, options in (("4", 3), ("12", 3), ("0", 3), ("dois", 3), ("2.", 3), ("²", 3)):
        model = Model(says(kind="none"))
        pipeline.run_item(item(line, frame=frame(option_item(options=options))), 1, model)
        assert model.calls == 1, (line, options)


def test_the_newest_item_is_the_one_with_the_smallest_age_and_the_later_wins_a_tie():
    older_confirm, newer_option = confirm_item("i1", age=90), option_item("i2", age=10)
    out = pipeline.run_item(item("2", frame=frame(older_confirm, newer_option)), 1, never)
    assert out["detail"] == {"item": "i2", "option": 2}
    model = Model(says(kind="none"))
    pipeline.run_item(item("yes", frame=frame(older_confirm, newer_option)), 1, model)
    assert model.calls == 1, "a yes does not answer an option item, and the older confirm is not the newest"
    tie = pipeline.run_item(item("yes", frame=frame(confirm_item("i1", age=20), confirm_item("i2", age=20))), 1, never)
    assert tie["detail"]["item"] == "i2"


def test_a_tier_one_line_is_the_operation_and_calls_nothing():
    out = pipeline.run_item(item("approve 4"), 1, never)
    assert (out["observed"], out["stage"], out["detail"], out["notes"]) == ("refuse_d", "tier1", {"class": "D"}, ["tier1"])
    out = pipeline.run_item(item("help"), 1, never)
    assert (out["observed"], out["detail"]) == ("read", {"op": "commands", "slots": {}})


def test_a_slash_line_is_a_typed_command_and_calls_nothing():
    for line in ("/status", "/approve 12", "  /help", "/remind 15:00 call Ana"):
        out = pipeline.run_item(item(line), 1, never)
        assert (out["observed"], out["stage"], out["notes"]) == ("none", "typed", ["typed"]), line


def test_tier_one_and_the_typed_command_wait_for_a_frame_without_open_items():
    model = Model(says(kind="none"))
    pipeline.run_item(item("approve 4", frame=frame(option_item(options=3), last=None)), 1, model)
    assert model.calls == 1, "with an open item, tier 1 does not decide: the line may be its answer"
    pipeline.run_item(item("approve 4", frame=frame(last={"op": "remind", "words": {"text": "x"}, "age_s": 5})), 1, never)    # a frame with only `last` has no open item


def test_a_plain_line_reaches_the_model_once_with_the_messages_the_protocol_builds():
    seen = []

    def call(system, user):
        seen.append((system, user))
        return {"ok": True, "text": says(kind="route"), "finish": "stop", "usage": None, "latency_ms": 3, "upstream": None}
    out = pipeline.run_item(item("write a long report about the launch"), 1, call)
    assert len(seen) == 1 and seen[0] == interpreter.build_messages(interpreter.SERVED, pipeline.now_of(item()), "America/Sao_Paulo", None, "write a long report about the launch")
    assert (out["observed"], out["stage"], out["parse"]) == ("route", "model", "ok")


# --- what the model's answer becomes ------------------------------------------------------------------------------------------------------------------

def test_a_failed_call_is_an_outage_with_its_code_and_unknown_codes_become_e_unknown():
    out = pipeline.run_item(item("write a long report about the launch"), 1, Model(ok=False, code="E_RATE"))
    assert (out["observed"], out["error"], out["parse"], out["time_source"]) == ("outage", "E_RATE", "none", None)
    assert out["call"] == {"latency_ms": 40, "usage": None, "upstream": None}
    assert pipeline.run_item(item("write a long report about the launch"), 1, Model(ok=False, code="E_SURPRISE"))["error"] == "E_UNKNOWN"


@pytest.mark.parametrize("text,parse", [("not json", "invalid"), ('{"v": 1, "kind": "none"} trailing', "invalid"), ('{"v": 2, "kind": "none"}', "invalid"),
                                        ('```json\n{"v": 1, "kind": "none"}\n```', "fenced"), (' {"v": 1, "kind": "none"} ', "ok")])
def test_the_parse_state_is_the_protocols(text, parse):
    out = pipeline.run_item(item("write a long report about the launch"), 1, Model(text))
    assert out["parse"] == parse
    if parse == "invalid":
        assert (out["observed"], out["why"], out["error"]) == ("clarify", "invalid", None), "a parse error is not a call error: the item's error stays null"
    else:
        assert out["observed"] == "none"


def test_a_model_that_names_a_decision_or_a_widening_operation_is_refused_by_code():
    for op, word, cls in (("approve", "refuse_d", "D"), ("release", "refuse_d", "D"), ("give-consent", "refuse_g", "G"), ("set-mode", "refuse_g", "G")):
        out = pipeline.run_item(item("go ahead and do the big thing"), 1, Model(says(kind="op", op=op, slots={})))
        assert (out["observed"], out["detail"]) == (word, {"class": cls}), op


def test_the_time_comes_from_code_when_code_reads_it_and_a_different_model_time_is_counted():
    line = "tomorrow 8am I've got dentist with Dr. Patel, block it in my calendar"
    one = item(line, clock="2026-10-25T11:00")
    agree = Model(says(kind="op", op="event-create", slots={"time": "tomorrow 8am", "title": "dentist with Dr. Patel"}, time_iso="2026-10-26T08:00", weekday="mon"))
    out = pipeline.run_item(one, 1, agree)
    assert (out["observed"], out["time_source"], out["time_disagree"], out["detail"]["time"]) == ("card", "code", False, "2026-10-26T08:00")
    differ = Model(says(kind="op", op="event-create", slots={"time": "tomorrow 8am", "title": "dentist with Dr. Patel"}, time_iso="2026-10-26T09:00", weekday="mon"))
    out = pipeline.run_item(one, 1, differ)
    assert (out["time_source"], out["time_disagree"], out["detail"]["time"], out["notes"]) == ("code", True, "2026-10-26T08:00", ["time-disagree"])


def test_a_time_the_span_does_not_settle_is_asked_back_and_has_no_time_source():
    out = pipeline.run_item(item("me lembra hoje às 9 de levar a marmita", clock="2026-10-27T13:05"), 1,
                            Model(says(kind="op", op="remind", slots={"text": "levar a marmita", "when": "hoje às 9"}, time_iso="2026-10-27T21:00", weekday="tue")))
    assert (out["observed"], out["why"], out["time_source"], out["detail"]) == ("clarify", "time-ask", None, {"slot": "when"})


def test_a_private_line_the_model_routes_is_asked_back():
    out = pipeline.run_item(item("me lembra amanhã às 9 de regar as plantas", clock="2026-10-27T13:05"), 1, Model(says(kind="route")))  # validate: allow english-only -- a fictional Portuguese line or word, the input under test
    assert (out["observed"], out["why"]) == ("clarify", "private-route")


def test_the_call_information_is_kept_for_the_line():
    out = pipeline.run_item(item("write a long report about the launch"), 1, Model(says(kind="none")))
    assert out["call"] == {"latency_ms": 12, "usage": {"input": 10, "output": 5, "cache_read": None, "cache_write": None}, "upstream": "pinned"}


# --- the mapping ------------------------------------------------------------------------------------------------------------------------------------------

def op_decision(op, spans=None, time=None):
    return {"kind": "op", "error": None, "op": op, "args": {}, "spans": spans or {}, "time": ({"local": time, "source": "code"} if time else None), "inherited": [], "time_disagree": False}


EXPECTED = {      # the test's own table: operation -> the observed word (the class in brackets is written here, not read from the code)
    "status": "read", "task": "read", "reminders": "read", "ask": "read",            # R and ask
    "remind": "remind_confirm",                                                       # N, the one that shows its reading
    "reminder-forget": "confirm", "reminder-restore": "confirm",                      # N
    "cancel": "confirm", "routine-create": "confirm", "attachment-add": "confirm",    # W
    "event-create": "card", "mail-send": "card", "mail-trash": "card", "file-save": "card",       # E
    "routine-resume": "confirm", "instructions-set": "confirm", "sync": "confirm", "stop-runs": "confirm",    # G, operational
    "approve": "refuse_d", "go-ahead": "refuse_d",                                    # D (tier 1 only)
    "config": "refuse_g", "deps": "refuse_g", "source-import": "refuse_g",            # G, widening (tier 1 only)
}
WORD_OF_CLASS = {"R": "read", "N": "confirm", "W": "confirm", "E": "card", "G": "confirm", "work": "read"}


@pytest.mark.parametrize("op,word", sorted(EXPECTED.items()))
def test_the_mapping_of_an_operation(op, word):
    assert pipeline.observed_of_op(op) == word
    assert pipeline.observe(op_decision(op))[0] == word


def test_the_mapping_of_every_operation_of_the_served_catalog_follows_its_class():
    assert len(CATALOG["ops"]) == 65
    for row in CATALOG["ops"]:
        want = "remind_confirm" if row["op"] == "remind" else WORD_OF_CLASS[row["class"]]
        assert pipeline.observed_of_op(row["op"]) == want, row["op"]


def test_the_allowed_operations_are_the_served_catalog_s():
    assert pipeline.ALLOWED == frozenset(row["op"] for row in CATALOG["ops"]) and len(pipeline.ALLOWED) == 65
    assert not (pipeline.ALLOWED & {row["op"] for row in CATALOG["refused"]})


def test_the_details_of_each_kind():
    observed, detail = pipeline.observe(op_decision("event-create", {"title": "dentist", "time": "friday 3pm"}, "2026-10-23T15:00"))
    assert (observed, detail) == ("card", {"op": "event-create", "slots": {"title": "dentist", "time": "friday 3pm"}, "time": "2026-10-23T15:00"})
    assert pipeline.observe(op_decision("status")) == ("read", {"op": "status", "slots": {}})
    assert pipeline.observe(op_decision("remind", {"text": "x", "when": "at 9"}))[1] == {"op": "remind", "slots": {"text": "x", "when": "at 9"}, "time": None}
    assert pipeline.observe(op_decision("task", {"id": 4}))[1] == {"op": "task", "slots": {"id": "4"}}, "spans are text"
    answer = {"kind": "answer", "error": None, "item": "i1", "need": "slot", "slot": "when", "span": "at 10", "args": {}, "time": {"local": "2026-10-23T10:00", "source": "code"}}
    assert pipeline.observe(answer) == ("answer", {"item": "i1", "slot": "when", "span": "at 10", "time": "2026-10-23T10:00"})
    assert pipeline.observe({"kind": "answer", "item": "i2", "need": "option", "option": 2}) == ("answer", {"item": "i2", "option": 2})
    assert pipeline.observe({"kind": "clarify", "slot": "to", "ops": None, "why": "model"}) == ("clarify", {"slot": "to"})
    assert pipeline.observe({"kind": "clarify", "slot": None, "ops": ["remind", "event-create"], "why": "model"}) == ("clarify", {"ops": ["remind", "event-create"]})
    assert pipeline.observe({"kind": "clarify", "slot": None, "ops": None, "why": "invalid"}) == ("clarify", {})
    assert pipeline.observe({"kind": "refuse", "class": "G", "op": "config"}) == ("refuse_g", {"class": "G"})
    assert pipeline.observe({"kind": "refuse_policy", "op": "cancel"}) == ("refuse_policy", {"op": "cancel"})
    assert [pipeline.observe({"kind": k})[0] for k in ("route", "none", "forwarded")] == ["route", "none", "forwarded"]
    with pytest.raises(ValueError):
        pipeline.observe({"kind": "executed"})


def decisions():
    """More than forty decisions: one operation decision for every operation of the served catalog (read raw from the JSON) and one of each other kind and shape."""
    out = [op_decision(row["op"], time="2026-10-23T15:00" if row["op"] in ("remind", "event-create", "event-change") else None) for row in CATALOG["ops"]]
    out += [op_decision(op) for op in ("approve", "reject", "release", "answer", "go-ahead", "config", "give-consent", "deps")]
    out += [{"kind": "answer", "item": "i1", "need": "confirm", "confirm": "yes"}, {"kind": "answer", "item": "i1", "need": "option", "option": 1},
            {"kind": "answer", "item": "i1", "need": "text"}, {"kind": "clarify", "slot": "to", "ops": None, "why": "model"},
            {"kind": "clarify", "slot": None, "ops": ["remind", "event-create"], "why": "model"}, {"kind": "clarify", "slot": None, "ops": None, "why": "time-ask"},
            {"kind": "route"}, {"kind": "none"}, {"kind": "forwarded"}, {"kind": "refuse", "class": "D", "op": "approve"}, {"kind": "refuse", "class": "G", "op": "config"},
            {"kind": "refuse_policy", "op": "cancel"}]
    return out


def executed_in(decisions_):
    return [d for d in decisions_ if pipeline.observe(d)[0] == "executed"]


def test_no_decision_is_ever_observed_as_executed_and_every_word_is_the_taxonomys():
    listed = decisions()
    assert len(listed) >= 40
    assert executed_in(listed) == []
    words = {pipeline.observe(d)[0] for d in listed}
    assert words <= set(TAXONOMY["observed"]) - {"executed", "outage"}, words


def test_a_planted_map_that_executes_an_effect_is_caught(monkeypatch):
    monkeypatch.setitem(pipeline.OBSERVED_OF, "E", "executed")
    assert executed_in(decisions()), "the check sees a map that returns executed for class E"


def test_the_stages_are_the_documented_words():
    assert pipeline.STAGES == ("forwarded", "precheck", "closed", "tier1", "typed", "model")
    assert set(pipeline.OBSERVED_OF.values()) <= set(TAXONOMY["observed"]) - {"executed"}


# --- the corpus item check ---------------------------------------------------------------------------------------------------------------------------------

def test_a_valid_item_has_no_problem_and_a_broken_one_names_the_field_never_the_value():
    assert pipeline.item_problems(item()) == []
    assert pipeline.item_problems(item(frame=frame(confirm_item()))) == []
    marker = "SECRET-LINE-MARKER-7731"
    broken = [item(marker, clock="not a time"), item(marker, zone="Nowhere/Atlantis"), item(marker, channel="carrier-pigeon"), item(marker, gold={"outcome": "dance"}),
              item(marker, gold={"outcome": "op", "scope": "wide"}), item(marker, also=[1]), item(marker, hard="yes"), item(marker, frame={"v": 1, "items": [{"id": marker}], "last": None}),
              item("   "), "not an object"]
    for one in broken:
        found = pipeline.item_problems(one)
        assert found, one
        assert marker not in " ".join(found)
    for wrong in (item(lang="klingon"), item(lang="en", id="dev-pt-br-00001"), item(lang="pt-BR", id="dev-en-00001")):
        assert pipeline.item_problems(wrong) in (["lang"], ["id/lang"])
    assert pipeline.item_problems(item(lang="mixed", id="dev-mx-00001")) == [] and pipeline.item_problems(item(lang="pt-BR", id="local-00001")) == []
    lacking = item()
    del lacking["gold"], lacking["clock"]
    assert pipeline.item_problems(lacking) == ["clock", "gold"]

