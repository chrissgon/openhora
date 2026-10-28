"""The hard limits of the interpreter on a messaging line (slice S1, limit L63): who it reads, what turns it off, the route it can reach, how often it calls, and what
a line gets when no call is made. Offline; the model is a stand-in that counts its calls, the clock is a stand-in, every name is invented.

Each test counts the calls the model service would have received (`calls`), so "0 calls" is a literal count, not a mock's word.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_interpret_limits.py
"""
from __future__ import annotations

import ast

import json
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_ops_interpret_dispatch import BARE, IX_PROFILES, IX_SENDERS, KEY, PLAIN, ROUTED, TODAY, ZONE, op, phone, prepare  # noqa: F401
from test_ops_natural import world  # noqa: F401  (the real-operations world fixture)
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

ops_interpret = st.load("ops_interpret")
turn_gate = st.load("turn_gate")
interpreter_enable = st.load("interpreter_enable")
interpreter_route = st.load("interpreter_route")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
lab = st.load("lab")
ops = st.load("ops")

RUNTIME = Path(__file__).resolve().parents[1]
NONE = '{"v":1,"kind":"none"}'
PLAIN_LINE = "tell me something about the unicorns"
HASHES = {"route_sha256": PINNED_HASHES["route_or_deepseek_v4_1_flash"], "prompt_sha256": PINNED_HASHES["interpreter_prompt"],
          "catalog_sha256": PINNED_HASHES["interpreter_catalog_before_s8"], "protocol_sha256": PINNED_HASHES["interpreter_protocol"]}
FLIP = {"0": "1"}


class Clock:
    """The stand-in clock of the rate window and of the breaker (seconds)."""

    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(turn_gate, "clock", lambda: self.now)


def gate_call(entry):
    """The one call site, given an admission of its own (the route check is the gate's)."""
    return turn_gate.call(turn_gate.Admission(turn_gate._MINT), entry, "system", "user", deadline_ms=6000, params={"temperature": 0.0, "max_tokens": 10, "reasoning": "off"})


def models(calls):
    return [c for c in calls if "user" in c]


def routed(calls):
    return [c for c in calls if "routed" in c]


def entry_file(tmp_path, monkeypatch, **changes):
    """A copy of the committed enabling file with the newest entry changed (None removes a key), and the module pointed at it."""
    doc = json.loads((RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            doc["entries"][-1].pop(key, None)
        else:
            doc["entries"][-1][key] = value
    path = tmp_path / "enable.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", str(path))
    return path


def flipped(text):
    return ("1" if text[0] == "0" else "0") + text[1:]


def test_the_committed_entry_is_in_force_here_and_a_line_of_the_listed_sender_makes_one_call(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    assert phone(world, PLAIN_LINE)["reply"] == "I did not see a request in that message."
    assert len(models(calls)) == 1 and routed(calls) == []


def test_a_sender_without_the_group_interpret_makes_no_call_and_is_routed_as_before(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    for n in range(2):
        assert phone(world, PLAIN_LINE, who=BARE)["reply"] == "ROUTED"
    assert models(calls) == [] and [c["routed"] for c in routed(calls)] == [PLAIN_LINE] * 2


def test_a_line_on_the_page_is_never_read_by_the_interpreter(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    out = ops.say(world["path"], PLAIN_LINE, channel="page")
    assert out["reply"] == "ROUTED" and models(calls) == []
    assert ops_interpret.enabled(ops_core.context(world["path"]), "page", None) is False


@pytest.mark.parametrize("change", [
    {"prompt_sha256": flipped(HASHES["prompt_sha256"])},
    {"catalog_sha256": flipped(HASHES["catalog_sha256"])},
    {"route_sha256": flipped(HASHES["route_sha256"])},
    {"protocol_sha256": flipped(HASHES["protocol_sha256"])},
    {"languages": ["pt-BR"]},
    {"route": "no-such-route"},
    {"extra": "key"},
    {"date": "21-10-2026"},
    {"basis": "evidence"},
], ids=["prompt", "catalog", "route-hash", "protocol", "language-not-listed", "unknown-route", "extra-key", "date-shape", "basis"])
def test_an_entry_that_does_not_match_this_checkout_or_is_not_well_formed_turns_the_interpreter_off(world, monkeypatch, tmp_path, change):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    entry_file(tmp_path, monkeypatch, **change)
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED"
    assert models(calls) == [] and len(routed(calls)) == 1


def test_a_missing_or_malformed_file_turns_the_interpreter_off(world, monkeypatch, tmp_path):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", str(tmp_path / "absent.json"))
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED"
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(interpreter_enable, "ENABLE_FILE", str(broken))
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED"
    assert models(calls) == [] and len(routed(calls)) == 2


def test_vacuity_the_control_of_the_entry_tests_calls_when_nothing_is_changed(world, monkeypatch, tmp_path):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    entry_file(tmp_path, monkeypatch)
    assert phone(world, PLAIN_LINE)["reply"] == "I did not see a request in that message." and len(models(calls)) == 1


def test_limit_63_an_entry_that_names_the_account_route_is_not_in_force_and_no_account_call_is_made(world, monkeypatch, tmp_path):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    account = interpreter_route.find("acct-claude-sonnet-5.5")
    assert account["kind"] == "account"
    entry_file(tmp_path, monkeypatch, route="acct-claude-sonnet-5.5", route_sha256=interpreter_route.route_sha256(account))

    def refuse(*a, **k):
        raise AssertionError("the account route was reached")

    monkeypatch.setattr(lab, "account_text", refuse)
    monkeypatch.setattr(interpreter_route, "_lab", refuse)
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED"
    assert models(calls) == []


def test_a_routes_file_whose_only_match_is_an_account_row_is_not_called_by_the_one_call_site(monkeypatch):
    account = dict(interpreter_route.find("acct-claude-sonnet-5.5"), id="or-deepseek-v4.1-flash")
    monkeypatch.setattr(interpreter_route, "daily_routes", lambda root=None: [account])

    def refuse(*a, **k):
        raise AssertionError("the model service was reached")

    monkeypatch.setattr(interpreter_route, "complete", refuse)
    monkeypatch.setattr(lab, "account_text", refuse)
    entry = {"route": "or-deepseek-v4.1-flash", "route_sha256": interpreter_route.route_sha256(account)}
    assert gate_call(entry) == {"ok": False, "code": "E_ROUTE"}
    assert interpreter_enable.active("en") is None
    entry = {"route": "or-deepseek-v4.1-flash", "route_sha256": HASHES["route_sha256"]}
    assert gate_call(entry) == {"ok": False, "code": "E_ROUTE"}


ORACLE_NAMES = {"TEXT_ARGS", "SECTION_OF", "ADDRESS", "_words", "_subsequence", "_contiguous", "value_problems", "_Frame", "_address_problems", "_written_numbers", "_entry_words", "_words_of_the_line",
                "_message_problems", "_state_said", "_of_service", "_mailbox_account", "_named", "_account_problems", "_hour_written", "_range_texts", "_norm", "_variants", "_time_problems"}


def gate_code_scanned(text: str) -> str:
    """The gate's CODE as the scan reads it (S41-7): parsed and written back, so that no comment and no docstring is in it (documentation names the arguments of a card), without the 23 definitions of
    the value oracle moved from natural_writes (they read lines with `find(`), and with the argument key `'account'` and the name `account_origin` taken out (the table of section 4 names the
    arguments). Anything else, an account route first of all, wherever it is in the module, is still there to be found."""
    tree = ast.parse(text)
    tree.body = [node for node in tree.body
                 if not ({node.name} if isinstance(node, (ast.FunctionDef, ast.ClassDef)) else {t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)}) & ORACLE_NAMES]
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree).replace("'account'", "").replace("account_origin", "")


def test_the_scan_of_the_gate_sees_code_appended_after_the_oracle_and_leaves_out_only_what_it_names():
    text = (RUNTIME / "turn_gate.py").read_text(encoding="utf-8")
    scanned = gate_code_scanned(text)
    assert "find(" not in scanned and "account" not in scanned and "lab" not in scanned and "def value_problems" not in scanned and "def provenance" in scanned
    planted = text + "\n\ndef later(route):\n    return interpreter_route.account_route(route)\n"
    assert "account" in gate_code_scanned(planted), "an account route appended after the oracle is found"
    assert "find(" in gate_code_scanned(text + "\n\ndef lookup(route):\n    return interpreter_route.find(route)\n"), "a lookup of a route appended is found"


def test_the_source_of_the_module_and_of_the_gate_name_no_account_route_no_lab_and_no_route_lookup_of_their_own():
    for name in ("ops_interpret.py", "turn_gate.py"):      # the route check moved from the first to the second (S41-4): both stay clean of an account route, the lab and a lookup of a route by id
        text = (RUNTIME / name).read_text(encoding="utf-8")
        if name == "turn_gate.py":      # S41-7: what is left out is named (comments and docstrings, the moved value oracle by its names, the argument key `'account'` and the helper `account_origin`); code appended to the gate later is scanned
            text = gate_code_scanned(text)
        assert [word for word in ("account", "lab", "load(", "find(") if word in text] == [], name
    gate = (RUNTIME / "turn_gate.py").read_text(encoding="utf-8")
    assert "daily_routes()" in gate and 'get("kind") != "http"' in gate


def test_vacuity_the_source_check_sees_a_word_it_forbids():
    assert [word for word in ("account", "lab", "load(", "find(") if word in "route = interpreter_route.find(entry)"] == ["find("]


# --- the rate, the cap, the breaker ---------------------------------------------------------------------------------------------------------------------


def rate_scenario(world, monkeypatch):
    """Eleven lines in ten seconds from one sender: ten calls, the eleventh routed; sixty seconds later a call again. Returns what is wrong."""
    calls, wrong = [], []
    prepare(world, monkeypatch, calls, {"text": NONE})
    clock = Clock(monkeypatch)
    replies = []
    for n in range(11):
        replies.append(phone(world, PLAIN_LINE)["reply"])
        clock.now += 1.0
    if replies != ["I did not see a request in that message."] * 10 + ["ROUTED"]:
        wrong.append(f"replies {replies}")
    if len(models(calls)) != 10:
        wrong.append(f"{len(models(calls))} calls")
    clock.now += 61.0
    if phone(world, PLAIN_LINE)["reply"] != "I did not see a request in that message." or len(models(calls)) != 11:
        wrong.append("no call after the window")
    return wrong


def test_ten_calls_per_sender_per_minute_and_the_eleventh_is_routed(world, monkeypatch):
    assert rate_scenario(world, monkeypatch) == []


def test_vacuity_with_the_rate_check_off_the_eleventh_call_goes_through_and_the_scenario_fails(world, monkeypatch):
    monkeypatch.setattr(turn_gate, "admit", lambda ctx, sender, fallback=None: turn_gate.Admission(turn_gate._MINT))      # LUNA-ENABLE: the committed entry names a fallback, so the caller passes `fallback=`
    assert rate_scenario(world, monkeypatch) != []


def test_the_rate_is_per_sender(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    Clock(monkeypatch)
    for n in range(10):
        phone(world, PLAIN_LINE)
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED"
    assert phone(world, PLAIN_LINE, who="plain")["reply"] == "I did not see a request in that message."


def test_three_hundred_calls_per_project_per_local_day_and_the_next_day_calls_again(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    clock = Clock(monkeypatch)
    for n in range(300):
        assert phone(world, PLAIN_LINE)["reply"] == "I did not see a request in that message."
        clock.now += 7.0
    assert len(models(calls)) == 300
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED" and len(models(calls)) == 300
    ops_core.context(world["path"])
    day = ops_natural._clock()
    monkeypatch.setattr(ops_natural, "_clock", lambda: day.replace(day=day.day + 1))
    assert phone(world, PLAIN_LINE)["reply"] == "I did not see a request in that message." and len(models(calls)) == 301


def failing(calls, code="E_NETWORK"):
    def complete(route_id, system, user, **kw):
        calls.append({"route": route_id, "user": user})
        return {"ok": False, "code": code}

    return complete


def test_three_failed_calls_open_the_breaker_for_five_minutes(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    clock = Clock(monkeypatch)
    monkeypatch.setattr(interpreter_route, "complete", failing(calls))
    for n in range(3):
        assert phone(world, PLAIN_LINE)["reply"] == "ROUTED"
        clock.now += 1.0
    assert len(models(calls)) == 3
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED" and len(models(calls)) == 3, "the breaker is open: no call"
    clock.now += 298.0      # 1301 s: the third failure was at 1002 s, so the breaker is open until 1302 s
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED" and len(models(calls)) == 3
    clock.now += 2.0      # 1303 s
    monkeypatch.setattr(interpreter_route, "complete", lambda route_id, system, user, **kw: calls.append({"route": route_id, "user": user}) or
                        {"ok": True, "text": NONE, "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"})
    assert phone(world, PLAIN_LINE)["reply"] == "I did not see a request in that message." and len(models(calls)) == 4


def test_a_success_between_failures_keeps_the_breaker_closed(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    clock = Clock(monkeypatch)
    good = interpreter_route.complete
    for outcome in ("bad", "bad", "good", "bad", "bad", "good"):
        monkeypatch.setattr(interpreter_route, "complete", failing(calls) if outcome == "bad" else good)
        phone(world, PLAIN_LINE)
        clock.now += 1.0
    assert len(models(calls)) == 6


# --- a line when no call is made ---------------------------------------------------------------------------------------------------------------------


PRIVATE_PT = "me lembra de ligar para o Zebulon amanha as 10h"


def test_a_failed_call_on_a_private_line_gets_the_outage_sentence_and_never_the_agent(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    monkeypatch.setattr(interpreter_route, "complete", failing(calls))
    write_config(world["path"], language="pt-BR")
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    assert phone(world, PRIVATE_PT)["reply"] == "Não consegui entender agora. Tente de novo em alguns minutos."      # validate: allow english-only -- the Portuguese line or sentence under test
    assert routed(calls) == []


def test_a_failed_call_on_a_plain_line_of_a_pt_br_or_en_project_goes_to_the_agent_as_before(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    monkeypatch.setattr(interpreter_route, "complete", failing(calls))
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED"
    write_config(world["path"], language="pt-BR")
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    assert phone(world, "me conta algo sobre os unicornios")["reply"] == "ROUTED"
    assert len(routed(calls)) == 2


def test_a_failed_call_in_a_project_of_another_language_gets_the_outage_sentence_even_for_a_plain_line(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})
    monkeypatch.setattr(interpreter_route, "complete", failing(calls))
    write_config(world["path"], language="es")
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    assert phone(world, "cuentame algo sobre los unicornios")["reply"] == "I could not understand that right now. Try again in a few minutes."
    assert routed(calls) == []


def test_a_call_that_raises_or_a_zone_that_cannot_be_named_is_a_failed_call_and_nothing_of_it_is_shown(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": NONE})

    def explode(*a, **k):
        raise RuntimeError("Zebulon42 in a message")

    monkeypatch.setattr(interpreter_route, "complete", explode)
    out = phone(world, PLAIN_LINE)["reply"]
    assert out == "ROUTED"
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: (_ for _ in ()).throw(ValueError("no zone")))
    assert phone(world, PLAIN_LINE)["reply"] == "ROUTED"
    assert len(routed(calls)) == 2
