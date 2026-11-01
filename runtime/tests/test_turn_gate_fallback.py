"""The gate's fifth section (S41-10, limit L63, the outage path): a second daily route of another company behind the policy group `interpret-fallback`, in code and off by default.

Held here:
  * the fallback is called only after a primary failure that is an OUTAGE (E_TIMEOUT, E_NETWORK, E_RATE, E_UPSTREAM) or with the primary's breaker open, never on a primary that answered, never on a refusal
    (E_HTTP), an unusable reply (E_RESPONSE), a local fault (E_KEY, E_USAGE), E_PIN, E_ROUTE or E_GATE (which count against no fallback breaker), and only for a sender who held the group when the line was
    admitted AND whose accepted file covers the companies in force (the consent record `config:fallbacks`; the controls: with either check patched open the second call happens and the assertion fails); the
    fallback gets only what is left of the line's deadline; the mail composer and the two revisers pass no fallback;
  * one admission covers the line: ten lines whose primary fails use ten admissions, the eleventh is not admitted, and a line makes at most two calls;
  * each route has its own breaker: three primary failures open the primary's alone and the fallback serves; three fallback failures open its own; with both open the line is not admitted (the caller's
    own fallback, `_no_decision`, is what happens); concurrent records of one route count exactly;
  * the system and user text sent to the fallback is the primary's, byte for byte, with the same settings, and nothing is printed or logged;
  * an entry whose fallback hash is not this checkout's, whose row is not `zdr` (the entry names the modified row's own hash, so the `zdr` check refuses it and not the hash check), whose route is the
    primary or unknown, or whose field is malformed, turns the FALLBACK off and never the primary;
  * consent is tied to the company: a person who widened `interpret-fallback` is listed it again, with the company's name and retention text, whenever the set in force is not a subset of the set they accepted;
    the group is not accepted while no fallback is in force; a record that holds another company, or none, sends nothing;
  * the rows: `pin_reply` is part of a row's hash, the daily route's hash is unchanged, and the upstream model has the shape vendor/model with no `:variant`, `@preset`, `~alias` or `latest`;
  * the routes file: every http row is pinned, allows no fallback provider and denies collection; the two fallback rows ask for zero retention, with the hashes pinned in scripts/tests/pinned_hashes.json;
  * the group is kind-only, messaging-only, in no default, needs `interpret` beside it, and its widening prints the retention of the fallback routes (or says that none is enabled);
  * the page and the terminal never reach either route.

Offline: the route's `complete` is a stand-in that counts its calls, the clock is a stand-in, every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_turn_gate_fallback.py
"""
from __future__ import annotations

import ast
import json
import threading
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_ops_natural import KEY, PROFILES, SENDERS, world  # noqa: F401  (the real-operations world fixture)

turn_gate = st.load("turn_gate")
interpreter_route = st.load("interpreter_route")
interpreter_enable = st.load("interpreter_enable")
ops_interpret = st.load("ops_interpret")
operations = st.load("operations")
policy_widening = st.load("policy_widening")
project_config = st.load("project_config")
ops = st.load("ops")

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
PINNED_HASHES = json.loads((REPO / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]
PRIMARY = "or-deepseek-v4.1-flash"
FIRST, SECOND = "or-gemini-3.5-flash-lite", "or-gpt-6-luna"
PARAMS = {"temperature": 0.0, "max_tokens": 300, "reasoning": "off"}
NONE = '{"v":1,"kind":"none"}'
SYSTEM, USER = "the system text of a test", "date\ntime\nzone\nframe\nthe line of a test about the unicorns"
WITH = {"messaging": ["read", "talk", "interpret", "interpret-fallback"]}
WITHOUT = {"messaging": ["read", "talk", "interpret"]}


@pytest.fixture(autouse=True)
def fresh():
    turn_gate.forget_all()
    yield
    turn_gate.forget_all()


class Frozen:
    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(turn_gate, "clock", lambda: self.now)


PKEY = "the-projects-key"


class FakeStore:
    """The cursors of the store, as the gate reads them (`cursor_get(conn, name)`)."""

    class StoreError(Exception):
        pass

    def __init__(self, records):
        self.records = records

    def cursor_get(self, conn, name):
        return self.records.get(name)


def consent_of(*ids, secret=PKEY):
    """The cursors of a person who accepted the file while these fallback routes (at this checkout's hashes) were in force."""
    return {policy_widening.FALLBACKS: policy_widening.dump_fallbacks([{"route": i, "route_sha256": hash_of(i)} for i in ids], secret), policy_widening.KEY: secret}


def ctx_of(project, channels=WITH, accepted=None):
    """A line's context: the configuration and a store whose consent record covers both fallback routes unless `accepted` (a tuple of route ids, or a dict of cursors) says otherwise."""
    records = consent_of(FIRST, SECOND) if accepted is None else (accepted if isinstance(accepted, dict) else consent_of(*accepted))
    return {"cfg": {"project": str(project), "channels": channels}, "store": FakeStore(records), "conn": None}


def hash_of(route_id):
    return interpreter_route.route_sha256(next(r for r in interpreter_route.daily_routes() if r["id"] == route_id))


def hash_of_original(route_id):
    """The committed row's hash, read from the pinned file and not from the (possibly patched) route table."""
    return PINNED_HASHES[{FIRST: "route_or_gemini_3_5_flash_lite", SECOND: "route_or_gpt_6_luna", PRIMARY: "route_or_deepseek_v4_1_flash"}[route_id]]


def entry():
    return {"route": PRIMARY, "route_sha256": hash_of(PRIMARY)}


def outage(*ids):
    return [{"route": i, "route_sha256": hash_of(i)} for i in (ids or (FIRST,))]


class Model:
    """The stand-in of the route's `complete`: it answers by route id from a script (`ok`, or a code), and keeps every call."""

    def __init__(self, monkeypatch, script=None, clock=None, takes=None):
        self.script = dict(script or {})
        self.calls = []
        self.clock, self.takes = clock, dict(takes or {})      # a call advances the stand-in clock by `takes[route]` seconds (the time it spent)
        monkeypatch.setattr(interpreter_route, "complete", self.complete)

    def complete(self, route_id, system, user, **kw):
        self.calls.append({"route": route_id, "system": system, "user": user, **kw})
        if self.clock is not None:
            self.clock.now += self.takes.get(route_id, 0.0)
        answer = self.script.get(route_id, "ok")
        if callable(answer):
            answer = answer()
        return {"ok": True, "text": NONE} if answer == "ok" else {"ok": False, "code": answer}

    def routes(self):
        return [c["route"] for c in self.calls]


def line(tmp_path, sender="telegram:1", *, channels=WITH, fallback=None, entry_=None, accepted=None, deadline_ms=6000):
    """One line the way ops_interpret makes it: admit, call, record. Returns (admission or None, result or None)."""
    ctx = ctx_of(tmp_path, channels, accepted)
    given = outage() if fallback is None else fallback
    admission = turn_gate.admit(ctx, sender, fallback=given)
    if admission is None:
        return None, None
    got = turn_gate.call(admission, entry_ or entry(), SYSTEM, USER, deadline_ms=deadline_ms, params=PARAMS, fallback=given)
    if got.get("code") != "E_GATE":
        turn_gate.record_attempts(got)
    return admission, got


# --- when the fallback is called ---------------------------------------------------------------------------------------------------------------------


def test_the_fallback_is_called_after_a_failed_primary_and_only_then(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    _, got = line(tmp_path)
    assert got["ok"] is True and model.routes() == [PRIMARY, FIRST]
    assert got["attempts"] == [(None, False), (FIRST, True)]


@pytest.mark.parametrize("answer", ["ok"])
def test_the_fallback_is_never_called_when_the_primary_answered(tmp_path, monkeypatch, answer):
    model = Model(monkeypatch, {PRIMARY: answer})
    _, got = line(tmp_path)
    assert got["ok"] is True and model.routes() == [PRIMARY] and "attempts" not in got, "recorded as before: one attempt on the primary"


@pytest.mark.parametrize("code", ["E_TIMEOUT", "E_RATE", "E_UPSTREAM", "E_NETWORK"])
def test_an_outage_of_the_primary_goes_on_to_the_fallback(tmp_path, monkeypatch, code):
    model = Model(monkeypatch, {PRIMARY: code})
    _, got = line(tmp_path)
    assert model.routes() == [PRIMARY, FIRST] and got["ok"] is True and got["attempts"] == [(None, False), (FIRST, True)]


@pytest.mark.parametrize("code", ["E_HTTP", "E_RESPONSE", "E_KEY", "E_USAGE", "E_PIN", "E_ROUTE", "E_INTERNAL", "E_UNKNOWN", "E_ANYTHING"])
def test_a_refusal_an_unusable_reply_a_local_fault_or_a_pin_mismatch_is_not_an_outage_and_no_second_company_is_asked(tmp_path, monkeypatch, code):
    """The stricter side (the supervisor's decision): E_HTTP (a 4xx refusal), E_RESPONSE (empty, refused, oversize), E_KEY and E_USAGE (local faults) and E_PIN (another provider or model than the row
    promises: a configuration mismatch or a safety signal, not an outage of the pinned provider) stay the caller's own failure: one call, no `attempts`, and no fallback breaker is touched."""
    model = Model(monkeypatch, {PRIMARY: code})
    _, got = line(tmp_path)
    assert model.routes() == [PRIMARY] and got == {"ok": False, "code": code}
    assert turn_gate._fallback_breakers == {}
    assert turn_gate._breaker["fails"] == 1, "the primary's own breaker counts it as before"


def test_the_outage_codes_are_the_four_of_a_service_that_is_out():
    assert turn_gate.OUTAGE_CODES == ("E_TIMEOUT", "E_NETWORK", "E_RATE", "E_UPSTREAM")


def test_vacuity_with_every_failure_an_outage_a_refusal_would_reach_the_second_company(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_HTTP"})
    monkeypatch.setattr(turn_gate, "OUTAGE_CODES", ("E_TIMEOUT", "E_NETWORK", "E_RATE", "E_UPSTREAM", "E_HTTP"))
    line(tmp_path)
    assert model.routes() == [PRIMARY, FIRST], "the list of outage codes is what keeps a refusal at home"


@pytest.mark.parametrize("code", ["E_KEY", "E_USAGE", "E_HTTP", "E_RESPONSE", "E_PIN"])
def test_a_fallback_call_that_ends_in_a_local_fault_or_a_refusal_counts_against_no_breaker_and_the_second_fallback_is_not_asked(tmp_path, monkeypatch, code):
    Frozen(monkeypatch)
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)      # the primary's breaker is open
    model = Model(monkeypatch, {FIRST: code})
    admission, got = line(tmp_path, fallback=outage(FIRST, SECOND))
    assert admission is not None and model.routes() == [FIRST] and got["ok"] is False and got["code"] == code and got["attempts"] == []
    assert turn_gate._fallback_breakers == {}, "a local fault is not a failure of the company"


def test_a_fallback_outage_counts_on_its_own_breaker_and_the_second_fallback_serves(tmp_path, monkeypatch):
    Frozen(monkeypatch)
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)
    model = Model(monkeypatch, {FIRST: "E_NETWORK"})
    _, got = line(tmp_path, fallback=outage(FIRST, SECOND))
    assert model.routes() == [FIRST, SECOND] and got["ok"] is True and got["attempts"] == [(FIRST, False), (SECOND, True)]
    assert turn_gate._fallback_breakers[FIRST]["fails"] == 1


# --- the deadline ------------------------------------------------------------------------------------------------------------------------------------


def test_the_fallback_gets_only_what_is_left_of_the_lines_deadline(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_NETWORK"}, clock=clock, takes={PRIMARY: 1.5})
    _, got = line(tmp_path)
    assert model.routes() == [PRIMARY, FIRST] and got["ok"] is True
    assert model.calls[0]["deadline_ms"] == 6000 and model.calls[1]["deadline_ms"] == 4500, "6 s minus the 1.5 s the primary took"


def test_no_fallback_is_asked_when_less_than_the_minimum_is_left(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"}, clock=clock, takes={PRIMARY: 5.5})
    _, got = line(tmp_path)
    assert model.routes() == [PRIMARY] and got["ok"] is False and got["attempts"] == [(None, False)]
    clock2 = Frozen(monkeypatch)
    turn_gate.forget_all()
    model2 = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"}, clock=clock2, takes={PRIMARY: 5.0})
    line(tmp_path, sender="telegram:2")
    assert model2.routes() == [PRIMARY, FIRST] and model2.calls[1]["deadline_ms"] == 1000 == turn_gate.MIN_FALLBACK_MS, "exactly the minimum is still asked"


def test_after_a_primary_that_ended_at_its_deadline_no_fallback_is_asked_and_the_worst_case_of_a_line_is_the_primarys_own(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_TIMEOUT"}, clock=clock, takes={PRIMARY: 6.5})      # the deadline and the provider's 0.5 s margin
    started = clock.now
    _, got = line(tmp_path)
    assert model.routes() == [PRIMARY] and got["code"] == "E_TIMEOUT" and clock.now - started == 6.5


@pytest.mark.parametrize("spent", [0.0, 0.4, 1.0, 2.5, 4.9, 5.0])
def test_the_total_time_of_a_line_never_exceeds_the_deadline_plus_the_providers_margin(tmp_path, monkeypatch, spent):
    """Each call may take its deadline and 0.5 s (the provider's margin); the fallback's deadline is the rest, so primary + fallback <= 6 s + 0.5 s + 0.5 s only when the primary ran to its own margin;
    with the primary at `spent` seconds the fallback is asked for 6 - spent seconds and so the line ends by 6 + 0.5 s at the latest, as a line with no fallback."""
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_NETWORK"}, clock=clock, takes={PRIMARY: spent, FIRST: 6.0 - spent + 0.5})      # the fallback runs to its deadline and margin
    started = clock.now
    line(tmp_path)
    assert clock.now - started <= 6.5 + 1e-9
    assert model.calls[-1]["deadline_ms"] == round(6000 - spent * 1000)


def test_with_the_primarys_breaker_open_the_first_fallback_gets_the_whole_deadline_and_the_second_what_is_left(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)
    model = Model(monkeypatch, {FIRST: "E_UPSTREAM"}, clock=clock, takes={FIRST: 2.0})
    line(tmp_path, fallback=outage(FIRST, SECOND))
    assert [c["deadline_ms"] for c in model.calls] == [6000, 4000]


# --- consent: tied to the company --------------------------------------------------------------------------------------------------------------------


def test_a_line_goes_to_a_company_only_while_the_accepted_file_covers_it(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    for accepted, expect in (((), [PRIMARY]), ((SECOND,), [PRIMARY]), ((FIRST,), [PRIMARY, FIRST]), ((FIRST, SECOND), [PRIMARY, FIRST]), ({}, [PRIMARY])):
        turn_gate.forget_all()
        model.calls.clear()
        _, got = line(tmp_path, accepted=accepted)
        assert model.routes() == expect, accepted


def test_a_consent_made_with_another_key_or_for_another_hash_or_with_no_key_covers_nothing(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    other_key = consent_of(FIRST, secret="another-key")
    other_key[policy_widening.KEY] = PKEY      # the record was made with a key that is not the project's
    no_key = consent_of(FIRST)
    del no_key[policy_widening.KEY]
    changed = {policy_widening.FALLBACKS: policy_widening.dump_fallbacks([{"route": FIRST, "route_sha256": "0" * 64}], PKEY), policy_widening.KEY: PKEY}
    junk = {policy_widening.FALLBACKS: "not json", policy_widening.KEY: PKEY}
    for name, accepted in (("another key", other_key), ("no key", no_key), ("another hash", changed), ("junk", junk)):
        turn_gate.forget_all()
        model.calls.clear()
        line(tmp_path, accepted=accepted)
        assert model.routes() == [PRIMARY], name
    turn_gate.forget_all()
    model.calls.clear()
    line(tmp_path, accepted=consent_of(FIRST))
    assert model.routes() == [PRIMARY, FIRST], "the control: the record made with the project's key, for this hash"


def test_with_no_consent_and_the_primarys_breaker_open_the_line_is_not_admitted(tmp_path, monkeypatch):
    Frozen(monkeypatch)
    Model(monkeypatch, {})
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)
    assert turn_gate.admit(ctx_of(tmp_path, accepted=()), "telegram:1", fallback=outage()) is None
    assert turn_gate.admit(ctx_of(tmp_path, accepted=(FIRST,)), "telegram:1", fallback=outage()) is not None


def test_a_context_with_no_store_has_no_consent_and_a_store_that_raises_neither(tmp_path):
    assert turn_gate._consented({"cfg": {}}, outage()) is False

    class Broken:
        def cursor_get(self, conn, name):
            raise RuntimeError("a store fault")

    assert turn_gate._consented({"cfg": {}, "store": Broken(), "conn": None}, outage()) is False
    assert turn_gate._consented(ctx_of(tmp_path), []) is False, "no company in force is no consent to give"
    assert turn_gate._consented(ctx_of(tmp_path), outage()) is True


def test_vacuity_with_the_consent_check_open_a_company_nobody_was_shown_gets_the_line(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    monkeypatch.setattr(turn_gate, "_consented", lambda ctx, items: True)
    line(tmp_path, accepted=())
    assert model.routes() == [PRIMARY, FIRST], "the record of the accepted file is what keeps the company away"


def test_the_fallback_is_never_called_on_a_primary_that_the_entry_no_longer_matches(tmp_path, monkeypatch):
    model = Model(monkeypatch, {})
    _, got = line(tmp_path, entry_=dict(entry(), route_sha256="0" * 64))
    assert got == {"ok": False, "code": "E_ROUTE"} and model.calls == [], "E_ROUTE is the entry's fault, not an outage: no request, no fallback"


def test_the_fallback_is_never_called_without_an_admission_and_a_used_admission_calls_nothing(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    for nothing in (None, "admission", object()):
        assert turn_gate.call(nothing, entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS, fallback=outage()) == {"ok": False, "code": "E_GATE"}
    one = turn_gate.admit(ctx_of(tmp_path), "telegram:1", fallback=outage())
    assert turn_gate.call(one, entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS, fallback=outage())["ok"] is True
    n = len(model.calls)
    assert turn_gate.call(one, entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS, fallback=outage()) == {"ok": False, "code": "E_GATE"} and len(model.calls) == n


def test_with_the_primarys_breaker_open_the_fallback_serves_and_the_primary_is_not_asked(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    for _ in range(turn_gate.BREAKER_FAILS):
        line(tmp_path, sender=f"telegram:{clock.now}")
        clock.now += 1
    assert model.routes().count(PRIMARY) == 3 and turn_gate._breaker["until"] > clock.now
    before = len(model.calls)
    admission, got = line(tmp_path)
    assert admission is not None and got["ok"] is True and model.routes()[before:] == [FIRST], "the open primary is skipped: only the fallback is asked"
    assert got["attempts"] == [(FIRST, True)]
    clock.now += turn_gate.BREAKER_OPEN + 1      # half open: the primary is asked again, and the fallback only when it fails
    model.script[PRIMARY] = "ok"
    before = len(model.calls)
    line(tmp_path)
    assert model.routes()[before:] == [PRIMARY]


def test_a_sender_without_the_group_gets_todays_behaviour_on_a_primary_failure(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    admission, got = line(tmp_path, channels=WITHOUT)
    assert admission is not None and admission.fallback_ok is False
    assert model.routes() == [PRIMARY] and got == {"ok": False, "code": "E_UPSTREAM"}, "one call, the primary's own failure, no `attempts`"
    for _ in range(turn_gate.BREAKER_FAILS - 1):
        line(tmp_path, channels=WITHOUT, sender="telegram:2")
    assert turn_gate.admit(ctx_of(tmp_path, WITHOUT), "telegram:3", fallback=outage()) is None, "with the primary's breaker open and no group, the line is not admitted (the line goes on as before)"
    assert model.routes() == [PRIMARY] * 3


def test_vacuity_with_the_group_check_open_the_second_call_happens_and_the_assertion_above_fails(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    monkeypatch.setattr(turn_gate, "_may_fall_back", lambda ctx, sender, fallback: True)
    line(tmp_path, channels=WITHOUT)
    assert model.routes() == [PRIMARY, FIRST], "the group check is what keeps the second call away"


@pytest.mark.parametrize("channels", [{}, {"messaging": []}, {"messaging": ["read", "talk"]}, {"page": ["read", "interpret-fallback"]}, None])
def test_only_the_messaging_policy_with_the_group_makes_a_fallback_admission(tmp_path, channels):
    ctx = {"cfg": {"project": str(tmp_path)}} if channels is None else ctx_of(tmp_path, channels)
    assert turn_gate.admit(ctx, "telegram:1", fallback=outage()).fallback_ok is False
    assert turn_gate.admit(ctx_of(tmp_path, WITH), "telegram:1", fallback=outage()).fallback_ok is True, "the control"
    assert turn_gate.admit(ctx_of(tmp_path, WITH), "telegram:1").fallback_ok is False, "a caller that names no fallback never gets one (the composer, the two revisers)"


def test_a_fallback_the_caller_did_not_name_is_never_asked(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    admission = turn_gate.admit(ctx_of(tmp_path), "telegram:1", fallback=outage())
    got = turn_gate.call(admission, entry(), SYSTEM, USER, deadline_ms=6000, params=PARAMS)
    assert got == {"ok": False, "code": "E_UPSTREAM"} and model.routes() == [PRIMARY]


def test_only_the_interpreter_names_a_fallback_and_the_group_is_read_by_the_gate_alone():
    """The mail composer, the two revisers and every other caller of the gate pass no `fallback`; the group is named in code by the gate (and the policy files), nowhere else."""
    named = {}
    for path in sorted(RUNTIME.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "fallback":
                named.setdefault(path.name, []).append(node.value.__class__.__name__)
    assert set(named) == {"ops_interpret.py"}, named      # the gate defines the keyword; the interpreter alone passes it
    texts = {p.name: p.read_text(encoding="utf-8") for p in RUNTIME.glob("*.py")}
    holders = sorted(name for name, text in texts.items() if '"interpret-fallback"' in text)
    assert holders == ["operations.py", "policy_widening.py", "project_config.py", "turn_gate.py"], holders      # the table, the widening text, the config check and the gate's one constant
    assert 'FALLBACK_GROUP = "interpret-fallback"' in texts["turn_gate.py"] and "FALLBACK_GROUP" not in texts["ops_interpret.py"] and '"interpret-fallback"' not in texts["ops_interpret.py"]


# --- one admission per line ---------------------------------------------------------------------------------------------------------------------------


def test_ten_lines_whose_primary_fails_use_ten_admissions_and_the_eleventh_is_not_admitted(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    admitted = 0
    for _ in range(turn_gate.RATE_MAX):
        admission, got = line(tmp_path)
        admitted += admission is not None
        assert got["ok"] is True
        clock.now += 0.5
    assert admitted == 10
    assert len(model.calls) == 13, "three primary failures open its breaker; the other seven lines asked only the fallback"
    admission, got = line(tmp_path)
    assert admission is None and got is None, "the eleventh line of the sender in the window is not admitted"
    assert len(model.calls) == 13


def test_a_line_makes_at_most_two_calls_whatever_the_routes(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM", FIRST: "E_UPSTREAM", SECOND: "E_UPSTREAM"})
    _, got = line(tmp_path, fallback=outage(FIRST, SECOND))
    assert model.routes() == [PRIMARY, FIRST], "the primary and one fallback"
    assert got["ok"] is False and got["attempts"] == [(None, False), (FIRST, False)]
    turn_gate.forget_all()
    Frozen(monkeypatch)
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)      # the primary's breaker is open: two fallbacks may serve one line, never three calls
    model.calls.clear()
    admission, got = line(tmp_path, sender="telegram:2", fallback=outage(FIRST, SECOND))
    assert admission is not None and model.routes() == [FIRST, SECOND] and got["attempts"] == [(FIRST, False), (SECOND, False)]


def test_the_second_fallback_serves_when_the_first_fails_and_the_primary_is_open(tmp_path, monkeypatch):
    Frozen(monkeypatch)
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)
    model = Model(monkeypatch, {FIRST: "E_UPSTREAM"})
    _, got = line(tmp_path, fallback=outage(FIRST, SECOND))
    assert model.routes() == [FIRST, SECOND] and got["ok"] is True and got["attempts"] == [(FIRST, False), (SECOND, True)]


# --- the breakers -----------------------------------------------------------------------------------------------------------------------------------


def test_the_breakers_are_per_route_and_both_open_means_the_line_is_not_admitted(tmp_path, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    for i in range(turn_gate.BREAKER_FAILS):
        line(tmp_path, sender=f"telegram:{i}")
        clock.now += 1
    assert turn_gate._breaker["until"] > clock.now, "three primary failures opened the primary's breaker"
    assert turn_gate._fallback_breakers.get(FIRST, {"fails": 0})["fails"] == 0, "the fallback answered: its count is closed"
    admission, got = line(tmp_path, sender="telegram:10")
    assert admission is not None and got["ok"] is True, "the fallback still serves"
    model.script[FIRST] = "E_UPSTREAM"
    for i in range(turn_gate.BREAKER_FAILS):
        admission, got = line(tmp_path, sender=f"telegram:2{i}")
        assert admission is not None and got["ok"] is False
        clock.now += 1
    assert turn_gate._fallback_breakers[FIRST]["until"] > clock.now, "three fallback failures opened its own breaker"
    calls = len(model.calls)
    assert turn_gate.admit(ctx_of(tmp_path), "telegram:99", fallback=outage()) is None, "both open: no admission, no call: `_no_decision` is what the caller does"
    assert len(model.calls) == calls
    clock.now += turn_gate.BREAKER_OPEN + 1
    assert turn_gate.admit(ctx_of(tmp_path), "telegram:99", fallback=outage()) is not None, "both close after their time"


def test_one_route_failing_does_not_count_against_the_other(tmp_path, monkeypatch):
    Frozen(monkeypatch)
    turn_gate.record(False, FIRST)
    turn_gate.record(False, FIRST)
    turn_gate.record(True)
    assert turn_gate._breaker == {"fails": 0, "until": 0.0} and turn_gate._fallback_breakers[FIRST]["fails"] == 2
    turn_gate.record(True, FIRST)
    assert turn_gate._fallback_breakers[FIRST]["fails"] == 0, "a success closes the count of that route"


def test_a_routes_breaker_counts_exactly_under_concurrent_records():
    threads = [threading.Thread(target=turn_gate.record, args=(False, FIRST)) for _ in range(60)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert turn_gate._fallback_breakers[FIRST]["fails"] == 60 and turn_gate._breaker == {"fails": 0, "until": 0.0}


def test_forget_all_closes_the_fallback_breakers_too(tmp_path):
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False, FIRST)
    assert turn_gate._fallback_breakers[FIRST]["until"] > 0
    turn_gate.forget_all()
    assert turn_gate._fallback_breakers == {}


def test_the_calls_of_a_failed_fallback_are_recorded_route_by_route(tmp_path, monkeypatch):
    Frozen(monkeypatch)
    Model(monkeypatch, {PRIMARY: "E_UPSTREAM", FIRST: "E_UPSTREAM"})
    line(tmp_path)
    assert turn_gate._breaker["fails"] == 1 and turn_gate._fallback_breakers[FIRST]["fails"] == 1


def test_record_attempts_with_a_plain_result_is_the_old_record(monkeypatch):
    seen = []
    monkeypatch.setattr(turn_gate, "record", lambda *a: seen.append(a))
    turn_gate.record_attempts({"ok": True, "text": "x"})
    turn_gate.record_attempts({"ok": False, "code": "E_HTTP"})
    turn_gate.record_attempts({"ok": True, "attempts": [(None, False), (FIRST, True)]})
    assert seen == [(True,), (False,), (False,), (True, FIRST)], "the primary is recorded with one argument, as the tests that patch `record` expect"


# --- what is sent -------------------------------------------------------------------------------------------------------------------------------------


def test_the_fallback_gets_the_primarys_text_byte_for_byte_with_the_same_settings_and_nothing_is_logged(tmp_path, monkeypatch, capsys, caplog):
    Frozen(monkeypatch)      # the fallback's deadline is what is left of the line's: with the real clock, a 0.5 ms read gap made it 5999 and the assertion below flaky
    model = Model(monkeypatch, {PRIMARY: "E_TIMEOUT"})
    with caplog.at_level(0):
        line(tmp_path)
    first, second = model.calls
    assert (first["system"], first["user"]) == (second["system"], second["user"]) == (SYSTEM, USER)
    extra = {k: second[k] for k in second if k not in ("route", "system", "user")}
    assert extra == {k: first[k] for k in first if k not in ("route", "system", "user", "accepted")} | {"accepted": [hash_of(FIRST)]}, "the same deadline and settings; only the accepted hash is the route's own"
    assert set(extra) == {"accepted", "deadline_ms", "temperature", "max_tokens", "reasoning"}, "no extra field"
    out = capsys.readouterr()
    assert out.out == "" and out.err == "" and caplog.records == []


# --- the entry --------------------------------------------------------------------------------------------------------------------------------------


def test_a_fallback_whose_hash_is_not_the_checkouts_is_not_called_and_the_primary_still_serves(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    tampered = [{"route": FIRST, "route_sha256": "0" * 64}]
    held = {policy_widening.FALLBACKS: policy_widening.dump_fallbacks(tampered, PKEY), policy_widening.KEY: PKEY}      # the person's record covers the tampered pair: the gate's own check of the row is what refuses
    admission, got = line(tmp_path, fallback=tampered, accepted=held)
    assert admission.fallback_ok is True
    assert model.routes() == [PRIMARY] and got["ok"] is False and got["attempts"] == [(None, False)], "the gate asks nothing of a row that does not match"
    _, got = line(tmp_path, sender="telegram:3", fallback=tampered)
    assert model.routes() == [PRIMARY, PRIMARY], "and with no consent for that hash the line does not even reach the check"
    model.script[PRIMARY] = "ok"
    _, got = line(tmp_path, sender="telegram:2", fallback=tampered, accepted=held)
    assert got["ok"] is True and model.routes()[-1] == PRIMARY


def test_a_fallback_row_that_does_not_ask_for_zero_retention_is_never_called(tmp_path, monkeypatch):
    rows = [dict(r, zdr=False) if r["id"] == FIRST else r for r in interpreter_route.daily_routes()]
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: rows)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    pair = [{"route": FIRST, "route_sha256": interpreter_route.route_sha256(next(r for r in rows if r["id"] == FIRST))}]
    held = {policy_widening.FALLBACKS: policy_widening.dump_fallbacks(pair, PKEY), policy_widening.KEY: PKEY}      # consent and hash both name the modified row: only the gate's `zdr` check refuses it
    admission, got = line(tmp_path, fallback=pair, accepted=held)
    assert admission.fallback_ok is True and model.routes() == [PRIMARY] and got["ok"] is False and got["attempts"] == [(None, False)]
    rows[[r["id"] for r in rows].index(FIRST)]["zdr"] = True      # the control: the same row with zdr true, under its own new hash, is called
    pair = [{"route": FIRST, "route_sha256": interpreter_route.route_sha256(next(r for r in rows if r["id"] == FIRST))}]
    held = {policy_widening.FALLBACKS: policy_widening.dump_fallbacks(pair, PKEY), policy_widening.KEY: PKEY}
    turn_gate.forget_all()
    _, got = line(tmp_path, sender="telegram:2", fallback=pair, accepted=held)
    assert model.routes()[-1] == FIRST and got["ok"] is True


def test_the_entrys_own_route_is_never_its_fallback(tmp_path, monkeypatch):
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    _, got = line(tmp_path, fallback=outage(PRIMARY))
    assert model.routes() == [PRIMARY] and got["ok"] is False


def newest_with(tmp_path, **fallback):
    doc = json.loads((RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))
    last = dict(doc["entries"][-1])
    if fallback:
        if fallback["value"] is None:      # LUNA-ENABLE: the committed newest entry names a fallback now; None gives the same entry without one
            last.pop("fallback", None)
        else:
            last["fallback"] = fallback["value"]
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "enable.json"
    path.write_text(json.dumps({"v": 1, "entries": [last]}), encoding="utf-8")
    return str(path), last


def good_item(route=FIRST, **over):
    known = route in (PRIMARY, FIRST, SECOND)
    return dict({"route": route, "route_sha256": hash_of(route) if known else "0" * 64, "measured": "2026-10-30 RESULT-X"}, **over)


def test_a_valid_fallback_in_the_newest_entry_is_in_force_and_the_committed_entry_names_only_luna(tmp_path):
    committed = json.loads((RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))["entries"]      # LUNA-ENABLE (2026-10-28): the maintainer's dated entry names the outage route; MAIL-SUMMARY-FLIP (2026-10-31) copies it
    assert [item["route"] for item in committed[-1]["fallback"]] == [SECOND] and interpreter_enable.active("en")["fallback"] == [{"route": SECOND, "route_sha256": PINNED_HASHES["route_or_gpt_6_luna"]}]
    assert interpreter_enable.fallbacks(committed[-1]) == [{"route": SECOND, "route_sha256": PINNED_HASHES["route_or_gpt_6_luna"]}] and committed[-2]["fallback"] == committed[-1]["fallback"] and all("fallback" not in earlier for earlier in committed[:-2])
    for value in (good_item(), [good_item()], [good_item(), good_item(SECOND)]):
        path, entry_ = newest_with(tmp_path, value=value)
        found = interpreter_enable.active("en", path=path)
        assert found is not None and found["route"]["id"] == PRIMARY
        assert found["fallback"] == [{"route": r, "route_sha256": hash_of(r)} for r in ([FIRST, SECOND] if isinstance(value, list) and len(value) == 2 else [FIRST])]


def broken_values():
    return {
        "a hash that is not the checkout's": [good_item(route_sha256="0" * 64)],
        "a hash that is not a hash": [good_item(route_sha256="not-a-hash")],
        "an unknown route": [good_item(route="no-such-route", route_sha256="0" * 64)],
        "an account route": [good_item(route="acct-claude-sonnet-5.5", route_sha256="0" * 64)],
        "the primary itself": [good_item(PRIMARY)],
        "a route twice": [good_item(), good_item()],
        "three routes": [good_item(), good_item(SECOND), good_item(PRIMARY)],
        "an empty list": [],
        "a text": "or-gemini-3.5-flash-lite",
        "a number": 7,
        "a missing key": [{"route": FIRST, "route_sha256": hash_of(FIRST)}],
        "an extra key": [good_item(extra=1)],
        "an empty measured": [good_item(measured="  ")],
        "a measured that is not a text": [good_item(measured=7)],
        "a long measured": [good_item(measured="x" * 601)],
        "an item that is not an object": ["x"],
        "one good and one bad": [good_item(), good_item(SECOND, route_sha256="0" * 64)],
        "a route that is not a text": [good_item(route=["a"])],
    }


@pytest.mark.parametrize("name", sorted(broken_values()))
def test_a_malformed_or_changed_fallback_turns_the_fallback_off_and_never_the_primary(tmp_path, name):
    path, _ = newest_with(tmp_path, value=broken_values()[name])
    found = interpreter_enable.active("en", path=path)
    assert found is not None and found["fallback"] == [], name
    assert found["route"]["id"] == PRIMARY and interpreter_enable.load(path)["entries"][-1]["route"] == PRIMARY


def test_a_fallback_row_that_does_not_ask_for_zero_retention_is_never_in_force(tmp_path, monkeypatch):
    """The entry names the hash of the MODIFIED row (zdr false), so the hash check passes and only the `zdr` check can refuse it (finding 5 of the review)."""
    rows = [dict(r, zdr=False) if r["id"] == FIRST else r for r in interpreter_route.daily_routes()]
    modified = next(r for r in rows if r["id"] == FIRST)
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: rows)
    item = good_item(route_sha256=interpreter_route.route_sha256(modified))
    assert item["route_sha256"] != hash_of_original(FIRST), "the modified row has another hash than the committed one: the entry matches the row it names"
    path, _ = newest_with(tmp_path, value=[item])
    found = interpreter_enable.active("en", path=path)
    assert found is not None and found["fallback"] == []
    assert interpreter_enable.fallbacks({"route": PRIMARY, "fallback": [item]}) == []
    unmodified = [r for r in rows]
    unmodified[[r["id"] for r in rows].index(FIRST)] = dict(modified, zdr=True)      # the vacuity: the same row with zdr true is in force under its own hash
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: unmodified)
    ok = good_item(route_sha256=interpreter_route.route_sha256(unmodified[[r["id"] for r in unmodified].index(FIRST)]))
    assert interpreter_enable.fallbacks({"route": PRIMARY, "fallback": [ok]}) == [{"route": FIRST, "route_sha256": ok["route_sha256"]}]


def test_a_changed_primary_hash_still_turns_the_whole_entry_off_as_before(tmp_path):
    path, last = newest_with(tmp_path, value=[good_item()])
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    doc["entries"][-1]["prompt_sha256"] = "0" * 64
    Path(path).write_text(json.dumps(doc), encoding="utf-8")
    assert interpreter_enable.active("en", path=path) is None, "the fallback never keeps the interpreter on"


def test_the_status_script_reads_an_entry_with_a_fallback_as_in_force(tmp_path):
    import importlib.util
    import shutil
    import sys
    name = "workbench_interpreter_status_for_fallback_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / "evals" / "interpreter_status.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    status = sys.modules[name]
    path, _ = newest_with(tmp_path, value=[good_item()])
    root = tmp_path / "root"
    (root / "runtime").mkdir(parents=True)
    shutil.copy(path, root / "runtime" / "interpreter_enable.json")
    assert status.enable_status(str(root), status.load_inputs())["in_force"] is True


def test_the_retention_of_the_fallback_routes_in_force(tmp_path):
    assert interpreter_enable.fallback_retention() == [interpreter_route.find(SECOND)["retention"]], "the committed newest entry names the second route only (LUNA-ENABLE, 2026-10-28)"
    path, _ = newest_with(tmp_path / "none", value=None)
    assert interpreter_enable.fallback_retention(path) is None and interpreter_enable.active("en", path=path)["fallback"] == [], "the same entry without the field: the interpreter on, no fallback"
    path, _ = newest_with(tmp_path, value=[good_item(), good_item(SECOND)])
    kept = interpreter_enable.fallback_retention(path)
    assert kept == [interpreter_route.find(FIRST)["retention"], interpreter_route.find(SECOND)["retention"]]
    path, _ = newest_with(tmp_path, value="junk")
    assert interpreter_enable.fallback_retention(path) is None


# --- the routes file --------------------------------------------------------------------------------------------------------------------------------


def test_routes_file_daily_rows_are_pinned_and_deny_collection():
    rows = interpreter_route.daily_routes()
    assert [r["id"] for r in rows] == [PRIMARY, FIRST, SECOND]
    for row in rows:
        assert row["kind"] == "http" and row["allow_fallbacks"] is False and row["data_collection"] == "deny" and row["pin"].strip(), row["id"]
        assert row["base_url"] == "https://openrouter.ai/api/v1" and row["key"] == "WB_RUNTIME_KEY_OPENROUTER_API_KEY" and row["reference"] is False
    by_id = {r["id"]: r for r in rows}
    assert by_id[PRIMARY]["zdr"] is False, "the daily route's retention is unchanged"
    for fallback_id, pin, upstream in ((FIRST, "google-vertex", "google/gemini-3.5-flash-lite"), (SECOND, "azure", "openai/gpt-6-luna")):
        row = by_id[fallback_id]
        assert row["zdr"] is True and row["pin"] == pin and row["upstream_model"] == upstream and row["model"] == "openrouter/" + upstream, fallback_id
        assert ("not confirmed" if fallback_id == FIRST else "were not checked") in row["retention"] and "zero data retention" in row["retention"].lower()      # Luna: the maintainer accepted the router's ZDR page on 2026-10-28, Azure's own terms not checked
    assert "the maintainer accepted OpenRouter's ZDR page as the written evidence" in by_id[SECOND]["retention"] and "before the maintainer accepts" not in by_id[SECOND]["retention"]


def test_the_fallback_rows_have_the_pinned_hashes_and_the_primary_is_unchanged():
    assert hash_of(PRIMARY) == PINNED_HASHES["route_or_deepseek_v4_1_flash"]
    assert hash_of(FIRST) == PINNED_HASHES["route_or_gemini_3_5_flash_lite"]
    assert hash_of(SECOND) == PINNED_HASHES["route_or_gpt_6_luna"]
    shown = interpreter_route.stdin_route(interpreter_route.find(FIRST))
    assert shown["allow_fallbacks"] is False and shown["data_collection"] == "deny" and shown["zdr"] is True and shown["pin"] == "google-vertex"


@pytest.mark.parametrize("change", [{"allow_fallbacks": True}, {"data_collection": "allow"}, {"pin": ""}])
def test_the_loader_refuses_a_fallback_row_with_fallbacks_or_collection_allowed(tmp_path, change):
    doc = json.loads((RUNTIME / "interpreter_routes.json").read_text(encoding="utf-8"))
    doc["routes"] = [dict(r, **change) if r["id"] == FIRST else r for r in doc["routes"]]
    root = tmp_path / "wb"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "secrets.json").write_text((RUNTIME / "secrets.json").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "runtime" / "interpreter_routes.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(interpreter_route.RouteError):
        interpreter_route.load(str(root))


def test_no_model_of_the_account_vendor_is_on_an_http_route():
    words = ("clau" + "de", "anth" + "ropic")
    for row in interpreter_route.daily_routes():
        assert not any(w in json.dumps(row).lower() for w in words), row["id"]


def test_the_two_fallback_rows_are_priced_at_their_pinned_provider():
    table = json.loads((RUNTIME / "prices.json").read_text(encoding="utf-8"))["models"]
    for fallback_id, provider in ((FIRST, "google-vertex"), (SECOND, "azure")):
        row = interpreter_route.find(fallback_id)
        price = table[row["model"]]
        assert price["provider"] == provider and price["accessed"] == "2026-10-26" and price["source"].startswith("https://openrouter.ai/")
        assert all(isinstance(price[k], (int, float)) and price[k] > 0 for k in ("input_usd_per_mtok", "output_usd_per_mtok", "cache_read_usd_per_mtok"))


# --- the group --------------------------------------------------------------------------------------------------------------------------------------


def test_the_group_is_kind_only_messaging_only_in_no_default_and_never_grants_say():
    assert operations.GROUPS["interpret-fallback"] == {"operations": ("say",), "kind": "interpret-fallback"}
    assert "interpret-fallback" in operations.KIND_ONLY and "interpret-fallback" in operations.MESSAGING_ONLY_GROUPS
    assert "interpret-fallback" not in operations.DEFAULT_POLICY["messaging"] and "interpret-fallback" not in operations.GRANTS.get("messaging", ())
    policy = {"messaging": ["read", "interpret-fallback"]}
    assert operations.holds("interpret-fallback", "messaging", policy, "telegram:1") is True and operations.permitted("say", "messaging", policy, None, "telegram:1") is False
    assert operations.holds("interpret-fallback", "page", {"page": ["read"]}, None) is False and operations.group_refusal("page", "interpret-fallback")
    assert operations.GROUP_TEXT["interpret-fallback"].startswith("when the interpreter's usual model service cannot read a plain line")
    assert "interpret-fallback" not in operations.default_groups("messaging")


def test_a_policy_that_lists_the_fallback_without_interpret_is_refused_and_one_with_both_is_valid(tmp_path):
    with pytest.raises(project_config.ConfigError) as refused:
        project_config._check_assigned("channels.messaging", "messaging", ["read", "talk", "interpret-fallback"], None)
    assert "'interpret-fallback' needs 'interpret' beside it" in str(refused.value)
    project_config._check_assigned("channels.messaging", "messaging", ["read", "talk", "interpret", "interpret-fallback"], None)
    with pytest.raises(project_config.ConfigError):
        project_config._check_assigned("channels.page", "page", ["read", "interpret", "interpret-fallback"], None)      # a group of a messaging app on the page: refused as `interpret` is


def test_widening_the_group_says_that_no_fallback_is_enabled_when_the_newest_entry_names_none(world, monkeypatch, tmp_path):
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", newest_with(tmp_path / "none", value=None)[0])
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS})
    write_config(world["path"], policies=dict(PROFILES, owner=PROFILES["owner"] + ["interpret", "interpret-fallback"]))
    shown = ops.config(world["path"])
    mine = [item for item in shown["widening"] if item["group"] == "interpret-fallback"]
    assert len(mine) == 1 and mine[0]["place"] == KEY["owner"]
    assert "No fallback route is in force in this checkout" in mine[0]["means"] and "second model service of another company" in mine[0]["means"]
    assert "cannot be accepted until the maintainer's dated entry names one" in mine[0]["means"]
    assert policy_widening.widening_sha256([{"place": KEY["owner"], "group": "interpret-fallback"}]) is not None


def test_widening_the_group_names_luna_and_its_retention_on_the_committed_entry(world):
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS})
    write_config(world["path"], policies=dict(PROFILES, owner=PROFILES["owner"] + ["interpret", "interpret-fallback"]))
    mine = [item for item in ops.config(world["path"])["widening"] if item["group"] == "interpret-fallback"]
    luna = interpreter_route.find(SECOND)
    assert len(mine) == 1 and "No fallback route is in force" not in mine[0]["means"]
    assert luna["retention"] in mine[0]["means"] and luna["upstream_model"] in mine[0]["means"] and luna["pin"] in mine[0]["means"], "the person is shown the company, the model, the provider and the retention text"
    assert "the maintainer accepted OpenRouter's ZDR page as the written evidence" in mine[0]["means"] and "Azure's own written terms for this use were not checked" in mine[0]["means"]


def test_widening_the_group_prints_the_retention_of_each_fallback_route_the_newest_entry_names(monkeypatch, tmp_path):
    path, _ = newest_with(tmp_path, value=[good_item(), good_item(SECOND)])
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", path)
    text = policy_widening.means("messaging", "interpret-fallback")
    shown = [f"{r} (model {interpreter_route.find(r)['upstream_model']}, served by {interpreter_route.find(r)['pin']}): {interpreter_route.find(r)['retention']}" for r in (FIRST, SECOND)]
    assert text.endswith(" | ".join(shown)), "each company is named with its model, its pinned provider and its retention text"
    assert "Fallback routes in force, each a company that would receive a plain line when the usual service is out: " in text
    (tmp_path / "one").mkdir()
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", newest_with(tmp_path / "one", value=[good_item()])[0])
    assert "Fallback route in force, each a company" in policy_widening.means("messaging", "interpret-fallback")


# --- the page and the terminal never reach a route -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("channel", ["page", "terminal", "chat", "mcp"])
def test_the_page_the_terminal_and_the_other_channels_never_reach_either_route(world, channel, monkeypatch):
    model = Model(monkeypatch, {})
    ctx = ctx_of(world["path"], WITH)
    ctx["cfg"]["language"] = "en"
    assert ops_interpret.enabled(ctx, channel, "telegram:1") is False
    assert model.calls == []


def test_the_interpreters_ask_goes_to_the_fallback_through_the_gate_and_records_each_route(world, monkeypatch):
    clock = Frozen(monkeypatch)
    model = Model(monkeypatch, {PRIMARY: "E_UPSTREAM"})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: "America/Sao_Paulo")
    ctx = ctx_of(world["path"], WITH)
    outage_routes = outage()
    admission = turn_gate.admit(ctx, "telegram:1", fallback=outage_routes)
    decision = ops_interpret._ask_model(ctx, entry(), "tell me something about the unicorns", "telegram:1", admission, None, fallback=outage_routes)
    assert decision is not None, "the fallback's answer was read: a decision (here the shape error of a context without a catalog policy, or the answer itself), not an outage"
    assert model.routes() == [PRIMARY, FIRST] and turn_gate._breaker["fails"] == 1 and turn_gate._fallback_breakers[FIRST]["fails"] == 0
    del clock
    for_the_page = turn_gate.admit(ctx_of(world["path"], WITHOUT), "telegram:2", fallback=outage_routes)
    assert ops_interpret._ask_model(ctx_of(world["path"], WITHOUT), entry(), "tell me something", "telegram:2", for_the_page, None, fallback=outage_routes) is None
    assert model.routes() == [PRIMARY, FIRST, PRIMARY], "a sender without the group: the primary failed, the line goes on as before (no decision)"


# --- consent through the real acceptance ----------------------------------------------------------------------------------------------------------------


def with_entry(monkeypatch, tmp_path, *routes, name="enable.json"):
    """The enabling file whose newest entry names these fallback routes (none: no `fallback` key), made the file of the module."""
    (tmp_path / name.replace(".json", "")).mkdir(exist_ok=True)
    path, _ = newest_with(tmp_path / name.replace(".json", ""), value=[good_item(r) for r in routes]) if routes else newest_with(tmp_path / name.replace(".json", ""), value=None)
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", path)


def holders(shown):
    return [(i["place"], i["group"]) for i in shown["widening"] if i["group"] == "interpret-fallback"]


def widen_owner(world, monkeypatch, tmp_path, *routes):
    """The person accepts a file with no fallback in force and no group; the maintainer's entry then names `routes` (none: no fallback key); the file is edited to give the owner the group."""
    with_entry(monkeypatch, tmp_path, name="before.json")
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS})      # the file accepted before
    with_entry(monkeypatch, tmp_path, *routes, name="entry.json")
    write_config(world["path"], policies=dict(PROFILES, owner=PROFILES["owner"] + ["interpret", "interpret-fallback"]))


def accepted_now(world, *ids):
    ctx = ops_core.context(world["path"], check_config=False)
    return turn_gate._consented(ctx, outage(*ids))


ops_core = st.load("ops_core")


def test_the_consent_probe_the_group_is_not_accepted_while_no_fallback_is_in_force(world, monkeypatch, tmp_path):
    """The reviewer's probe: before, a person who widened the group accepted a text saying no fallback was enabled, and the record held only the group's bit."""
    widen_owner(world, monkeypatch, tmp_path)
    shown = ops.config(world["path"])
    assert holders(shown) == [(KEY["owner"], "interpret-fallback")]
    with pytest.raises(ops_core.OpsError) as refused:
        ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert "not accepted while no fallback route is in force" in str(refused.value)
    assert accepted_now(world, FIRST) is False


def test_a_company_the_person_was_shown_is_the_one_the_line_may_go_to(world, monkeypatch, tmp_path):
    widen_owner(world, monkeypatch, tmp_path, FIRST)
    shown = ops.config(world["path"])
    mine = [i for i in shown["widening"] if i["group"] == "interpret-fallback"]
    assert len(mine) == 1 and FIRST in mine[0]["means"] and "google-vertex" in mine[0]["means"] and interpreter_route.find(FIRST)["retention"] in mine[0]["means"], "the line names the company and says what it keeps"
    assert accepted_now(world, FIRST) is False, "nothing is consented before the acceptance of the file that gives the group"
    done = ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert [(i["place"], i["group"]) for i in done["widened"] if i["group"] == "interpret-fallback"] == [(KEY["owner"], "interpret-fallback")]
    assert accepted_now(world, FIRST) is True and accepted_now(world, SECOND) is False and accepted_now(world, FIRST, SECOND) is False


def test_a_later_entry_that_names_another_company_lists_the_group_again_for_every_place_that_holds_it(world, monkeypatch, tmp_path):
    widen_owner(world, monkeypatch, tmp_path, FIRST)
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert holders(ops.config(world["path"])) == [], "nothing new: the same company, the same file"
    with_entry(monkeypatch, tmp_path, FIRST, SECOND, name="two.json")      # the maintainer's later entry adds a company
    assert accepted_now(world, FIRST, SECOND) is False, "the group the person holds does not carry the new company: no line goes to it"
    assert accepted_now(world, FIRST) is True, "the company they were shown still serves"
    again = ops.config(world["path"])
    mine = [i for i in again["widening"] if i["group"] == "interpret-fallback"]
    assert [(i["place"], i["group"]) for i in mine] == [(KEY["owner"], "interpret-fallback")], "listed again for the place that holds the group"
    assert FIRST in mine[0]["means"] and SECOND in mine[0]["means"] and "served by azure" in mine[0]["means"] and interpreter_route.find(SECOND)["retention"] in mine[0]["means"]
    assert again["widening_sha256"] is not None
    with pytest.raises(ops_core.OpsError):
        ops.accept_config(world["path"], again["sha256"])      # no hash of the list: not accepted
    ops.accept_config(world["path"], again["sha256"], widen=again["widening_sha256"])
    assert accepted_now(world, FIRST, SECOND) is True
    with_entry(monkeypatch, tmp_path, SECOND, name="only-second.json")      # a subset of what was accepted: nothing to show again
    assert holders(ops.config(world["path"])) == [] and accepted_now(world, SECOND) is True


def test_a_company_that_replaces_the_one_accepted_is_a_new_company(world, monkeypatch, tmp_path):
    widen_owner(world, monkeypatch, tmp_path, FIRST)
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    with_entry(monkeypatch, tmp_path, SECOND, name="other.json")
    assert accepted_now(world, SECOND) is False
    assert [i["group"] for i in ops.config(world["path"])["widening"]] == ["interpret-fallback"]


def test_every_place_that_holds_the_group_is_listed_a_channel_and_each_sender_and_a_place_without_it_is_not(world, monkeypatch, tmp_path):
    with_entry(monkeypatch, tmp_path, name="before.json")
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS})
    with_entry(monkeypatch, tmp_path, FIRST)
    both = PROFILES["owner"] + ["interpret", "interpret-fallback"]
    write_config(world["path"], policies=dict(PROFILES, owner=both, reader=PROFILES["reader"] + ["interpret", "interpret-fallback"]))
    shown = ops.config(world["path"])
    assert sorted(p for p, _ in holders(shown)) == sorted([KEY["owner"], KEY["reader"]])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    with_entry(monkeypatch, tmp_path, FIRST, SECOND, name="two.json")
    assert sorted(p for p, _ in holders(ops.config(world["path"]))) == sorted([KEY["owner"], KEY["reader"]]), "both places that hold the group are listed again, and no other"


def test_vacuity_without_the_fallback_widening_the_second_company_is_not_listed(world, monkeypatch, tmp_path):
    widen_owner(world, monkeypatch, tmp_path, FIRST)
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    with_entry(monkeypatch, tmp_path, FIRST, SECOND, name="two.json")
    assert holders(ops.config(world["path"])) != []
    monkeypatch.setattr(policy_widening, "fallback_widening", lambda *a, **k: [])
    assert holders(ops.config(world["path"])) == [], "the pure function is what lists the company again: with it off, nothing is listed (the record is what the runtime still reads)"
    assert accepted_now(world, FIRST, SECOND) is False, "and the runtime still sends nothing to it: the two checks do not depend on each other"


def test_the_record_of_the_fallbacks_is_keyed_and_holds_no_route_name(world, monkeypatch, tmp_path):
    widen_owner(world, monkeypatch, tmp_path, FIRST)
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    ctx = ops_core.context(world["path"])
    text = ctx["store"].cursor_get(ctx["conn"], policy_widening.FALLBACKS)
    key = ctx["store"].cursor_get(ctx["conn"], policy_widening.KEY)
    assert key and "gemini" not in text.lower() and "google" not in text.lower() and FIRST not in text and hash_of(FIRST) not in text
    assert policy_widening.parse_accounts(text) == {policy_widening.fallback_digest(FIRST, hash_of(FIRST), key)}
    assert policy_widening.fallback_digest(FIRST, hash_of(FIRST), key) != policy_widening.fallback_digest(FIRST, hash_of(FIRST))


def test_a_record_of_no_company_is_written_while_none_is_in_force_and_a_set_change_needs_a_new_acceptance(world, monkeypatch, tmp_path):
    with_entry(monkeypatch, tmp_path)
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS})
    ctx = ops_core.context(world["path"], check_config=False)
    assert policy_widening.parse_accounts(ctx["store"].cursor_get(ctx["conn"], policy_widening.FALLBACKS)) == set()
    with_entry(monkeypatch, tmp_path, FIRST, name="later.json")
    assert holders(ops.config(world["path"])) == [], "nobody holds the group: nothing to list"


def test_the_pure_functions(tmp_path):
    routes = [{"route": FIRST, "route_sha256": hash_of(FIRST)}, {"route": SECOND, "route_sha256": hash_of(SECOND)}]
    snap = {"channels": {"messaging": None}, "senders": {"telegram:1": ["read", "talk", "interpret", "interpret-fallback"], "telegram:2": ["read", "talk", "interpret"], "telegram:3": None}}
    assert policy_widening.fallback_widening(None, snap, PKEY, [], [])[:0] == [] and policy_widening.fallback_widening(None, snap, PKEY, [], []) == [], "no company in force: nothing"
    record = policy_widening.dump_fallbacks(routes[:1], PKEY)
    assert policy_widening.fallbacks_covered(record, routes[:1], PKEY) and not policy_widening.fallbacks_covered(record, routes, PKEY)
    assert not policy_widening.fallbacks_covered(None, routes[:1], PKEY) and policy_widening.fallbacks_covered(None, [], PKEY)
    assert not policy_widening.fallbacks_covered(record, routes[:1], "another-key")
    got = policy_widening.fallback_widening(record, snap, PKEY, [], routes)
    assert [i["place"] for i in got] == ["telegram:1"], "only the place that holds the group, sorted"
    assert policy_widening.fallback_widening(record, snap, PKEY, [{"place": "telegram:1", "group": "interpret-fallback"}], routes) == [], "a place already listed for the group is not listed twice"
    assert policy_widening.fallback_widening(policy_widening.dump_fallbacks(routes, PKEY), snap, PKEY, [], routes) == [], "all accepted"
    open_channel = {"channels": {"messaging": ["read", "interpret", "interpret-fallback"]}, "senders": {"telegram:3": None}}
    assert [i["place"] for i in policy_widening.fallback_widening(record, open_channel, PKEY, [], routes)] == ["messaging", "telegram:3"], "the channel holds it, and a sender that follows the channel with it"
    assert policy_widening.fallback_refusal([{"group": "read"}], []) is None and policy_widening.fallback_refusal([{"group": "interpret-fallback"}], routes) is None
    assert "not accepted while no fallback route is in force" in policy_widening.fallback_refusal([{"group": "interpret-fallback"}], [])


# --- the rows ---------------------------------------------------------------------------------------------------------------------------------------


def test_the_fallback_rows_carry_a_pin_reply_in_their_hash_and_the_daily_route_is_unchanged():
    for route_id in (FIRST, SECOND):
        row = interpreter_route.find(route_id)
        # written out: the name to compare the reply's provider with, the one the router gives (the probe of the Gemini row showed `google` for its Vertex pin)
        assert row["pin_reply"] == {FIRST: "google", SECOND: "azure"}[route_id]
        shown = interpreter_route.stdin_route(row)
        assert shown["pin_reply"] == row["pin_reply"]
        assert interpreter_route.route_sha256(dict(row, pin_reply="Another Name")) != interpreter_route.route_sha256(row), "pin_reply is hashed: the entry pins it"
    deepseek = interpreter_route.find(PRIMARY)
    assert "pin_reply" not in deepseek and "pin_reply" not in interpreter_route.stdin_route(deepseek)
    assert interpreter_route.route_sha256(deepseek) == PINNED_HASHES["route_or_deepseek_v4_1_flash"], "the enabling entry's hash of the daily route did not move"


@pytest.mark.parametrize("bad", ["", "  ", 7, ["a"], "x" * 65, "line\nbreak"])
def test_a_pin_reply_that_is_not_a_short_printable_text_is_refused(tmp_path, bad):
    doc = json.loads((RUNTIME / "interpreter_routes.json").read_text(encoding="utf-8"))
    doc["routes"] = [dict(r, pin_reply=bad) if r["id"] == FIRST else r for r in doc["routes"]]
    with pytest.raises(interpreter_route.RouteError):
        interpreter_route.load(load_root(tmp_path, doc))


def load_root(tmp_path, doc):
    root = tmp_path / "wb"
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "secrets.json").write_text((RUNTIME / "secrets.json").read_text(encoding="utf-8"), encoding="utf-8")
    (root / "runtime" / "interpreter_routes.json").write_text(json.dumps(doc), encoding="utf-8")
    return str(root)


def test_the_status_script_hashes_a_row_with_a_pin_reply_as_the_runtime_does():
    import importlib.util
    import sys
    name = "workbench_interpreter_status_for_pin_reply_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / "evals" / "interpreter_status.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    status = sys.modules[name]
    for route_id in (PRIMARY, FIRST, SECOND):
        row = interpreter_route.find(route_id)
        assert status.route_sha256(row) == interpreter_route.route_sha256(row), route_id


@pytest.mark.parametrize("upstream", ["openai/gpt-6-luna:online", "openai/gpt-6-luna:free", "google/gemini-3.5-flash-lite:online", "openai/gpt-5-chat-latest", "google/gemini-flash-latest",
                                      "google/gemini-3.5-flash-lite@preset", "~google/gemini-flash-latest", "google/gemini-3.5-flash-lite:nitro", "openai/gpt-6-luna:floor", "google/Gemini-3.5", "openai/gpt-6/luna",
                                      "google/gemini-3.5 flash", "deepseek/deepseek-v4.1-flash:free", "deepseek/deepseek-latest"])
def test_an_upstream_model_with_a_variant_suffix_a_preset_an_alias_or_latest_is_refused(tmp_path, upstream):
    doc = json.loads((RUNTIME / "interpreter_routes.json").read_text(encoding="utf-8"))
    doc["routes"] = [dict(r, upstream_model=upstream, model="openrouter/" + upstream) if r["id"] == SECOND else r for r in doc["routes"]]
    with pytest.raises(interpreter_route.RouteError):
        interpreter_route.load(load_root(tmp_path, doc))


def test_the_committed_ids_pass_the_shape_and_a_plain_id_of_each_family_loads(tmp_path):
    for row in interpreter_route.daily_routes():
        assert interpreter_route.UPSTREAM_SHAPE.fullmatch(row["upstream_model"]) and "latest" not in row["upstream_model"], row["id"]
    doc = json.loads((RUNTIME / "interpreter_routes.json").read_text(encoding="utf-8"))
    doc["routes"] = [dict(r, upstream_model="openai/gpt-6.1-luna", model="openrouter/openai/gpt-6.1-luna") if r["id"] == SECOND else r for r in doc["routes"]]
    assert [r["upstream_model"] for r in interpreter_route.load(load_root(tmp_path, doc))["routes"] if r["id"] == SECOND] == ["openai/gpt-6.1-luna"]
