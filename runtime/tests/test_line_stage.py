"""The stage of the line being answered (slice S19; runtime/line_stage.py and the points of the operations layer that publish it), offline: no model, no network, every name invented.

Held here:
  * the registry: a thread that is watched gets what it publishes, any other thread (the terminal, the page) and any word outside the closed list gets nothing, and a released
    thread is no longer watched;
  * `for_kinds` chooses mail, calendar or research from the types of the sources an answer reads;
  * the real call sites publish: the interpreter's model call (`think`), the read of the numbered items (`mail`, `calendar`), the read of a file (`file`), the calendar read again
    (`calendar`), and, over the real operations layer with a stand-in model, the line of the e-mail bug goes through `think`, `card` and `compose` in that order;
  * every word published anywhere in runtime/ is a member of the closed list and every member of the list is published somewhere (the test's own scan of the sources, with its own
    literal list of the eight stages), and no publish call carries a variable, so no word of the person can become a stage.

THE ORACLE is the test's own list of stages and its own regular expression over the text of runtime/*.py. The vacuity cases plant a stage outside the list and a source that publishes
a variable, and the scan must flag both.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_line_stage.py
"""
from __future__ import annotations

import re
import threading

import pytest

import standin_tree as st
from test_mail_compose_flow import (LIVE, LIVE_DECISION, ADDRESS, COMPOSED, clock, forget, phone, setup, world)  # noqa: F401  (the own-account mail world with a stand-in model)

line_stage = st.load("line_stage")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
ops_file_read = st.load("ops_file_read")
event_lookup = st.load("event_lookup")

THE_EIGHT = ["think", "mail", "calendar", "file", "compose", "card", "research", "plan"]


@pytest.fixture
def watched():
    slot = line_stage.watch()
    yield slot
    line_stage.release(slot)


def recorded(monkeypatch):
    seen = []
    real = line_stage.publish

    def publish(stage):
        seen.append(stage)
        return real(stage)
    monkeypatch.setattr(line_stage, "publish", publish)
    return seen


# --- the registry ------------------------------------------------------------------------------------------------------------------------------------


def test_the_closed_list_is_the_eight_stages_the_test_knows():
    assert list(line_stage.STAGES) == THE_EIGHT


def test_a_watched_thread_gets_the_last_stage_it_published_and_an_unknown_word_changes_nothing(watched):      # also the vacuity case
    assert watched.stage is None
    assert line_stage.publish("mail") is True and watched.stage == "mail"
    assert line_stage.publish("file") is True and watched.stage == "file"
    for word in ("Mail", "tell me about the shop", "", None, 3):
        assert line_stage.publish(word) is False
    assert watched.stage == "file"


def test_a_thread_nobody_watches_publishes_into_nothing_and_a_released_one_is_forgotten():
    assert line_stage.publish("mail") is False      # this thread is not watched
    slot = line_stage.watch()
    assert line_stage.watch() is slot      # a second watch of the same thread returns the slot it has
    seen = {}

    def other():
        seen["other"] = line_stage.publish("mail")      # another thread is not the watched one
    thread = threading.Thread(target=other)
    thread.start()
    thread.join()
    assert seen == {"other": False} and slot.stage is None
    line_stage.release(slot)
    line_stage.release(slot)
    line_stage.release(None)
    assert line_stage.publish("mail") is False and slot.stage is None


def test_the_slot_is_read_from_another_thread():
    slot = line_stage.watch()
    try:
        line_stage.publish("calendar")
        out = []
        thread = threading.Thread(target=lambda: out.append(slot.stage))
        thread.start()
        thread.join()
        assert out == ["calendar"]
    finally:
        line_stage.release(slot)


def test_for_kinds_chooses_by_the_types_of_the_sources():
    assert line_stage.for_kinds(["file", "mail"]) == "mail"
    assert line_stage.for_kinds(iter(["calendar", "file"])) == "calendar"
    assert line_stage.for_kinds(["mail", "calendar"]) == "mail"
    assert line_stage.for_kinds(["file", "notion", None]) == "research"
    assert line_stage.for_kinds([]) == "research"


# --- the real call sites ----------------------------------------------------------------------------------------------------------------------------


def test_the_interpreters_model_call_publishes_think(watched, monkeypatch):
    monkeypatch.setattr(ops_interpret, "_daily_call", lambda entry, system, user: {"ok": False})
    monkeypatch.setattr(ops_interpret, "_record", lambda ok: None)
    assert ops_interpret._ask_model({"cfg": {}}, {}, "hello there", None) is None
    assert watched.stage == "think"


@pytest.mark.parametrize("kind, stage", [("calendar", "calendar"), ("mail", "mail"), (None, "mail")])
def test_the_read_of_the_numbered_items_publishes_the_kind_it_reads(watched, monkeypatch, kind, stage):
    def refuse(project, row, args, channel, sender):
        raise ops_core.OpsError("nothing to read", 1)
    monkeypatch.setattr(ops_natural, "_call", refuse)
    monkeypatch.setattr(ops_natural, "_error", lambda cfg, error, channel: "none")
    args = {"kind": kind} if kind else {}
    assert ops_natural._read("p", {"cfg": {}}, "items", {"args": []}, args, "messaging", "telegram:1") == "none"
    assert watched.stage == stage


def test_another_read_publishes_nothing(watched, monkeypatch):
    monkeypatch.setattr(ops_natural, "_call", lambda *a: (_ for _ in ()).throw(ops_core.OpsError("x", 1)))
    monkeypatch.setattr(ops_natural, "_error", lambda cfg, error, channel: "none")
    ops_natural._read("p", {"cfg": {}}, "reminders", {"args": []}, {}, "messaging", "telegram:1")
    assert watched.stage is None


def test_the_read_of_a_file_publishes_file_only_after_the_name_is_checked(watched, monkeypatch):
    monkeypatch.setattr(ops_file_read, "_find_and_read", lambda cfg, wanted, account=None: {"status": "no-folders"})
    monkeypatch.setattr(ops_file_read, "_render", lambda cfg, found: "none")
    ctx = {"cfg": {}}
    assert ops_file_read.reply("p", ctx, {"file": "missing"}, "show the invented report", "messaging", "telegram:1", {}) != "none"      # the name is not in the line: asked again
    assert watched.stage is None      # no promise was made that the refusal then broke
    assert ops_file_read.reply("p", ctx, {"file": "report"}, "show the invented report", "messaging", "telegram:1", {}) == "none"
    assert watched.stage == "file"


def test_the_calendar_read_again_publishes_calendar(watched, monkeypatch):
    monkeypatch.setattr(st.load("ops_natural_calendar"), "calendar_sources", lambda ctx: [])
    event_lookup.refresh("p", {})
    assert watched.stage == "calendar"


def test_the_line_of_the_email_bug_goes_through_think_card_and_compose_in_that_order(world, clock, monkeypatch, watched):
    setup(world, monkeypatch)
    seen = recorded(monkeypatch)
    out = phone(world, LIVE)
    assert out["resend"] is not None      # the card opened, as in test_mail_compose_flow.py
    assert seen == ["think", "card", "compose"] and watched.stage == "compose"


# --- the scan of the sources ------------------------------------------------------------------------------------------------------------------------

PUBLISH = re.compile(r"""(?:\bline_stage|import_module\("line_stage"\))\.publish\(\s*(?P<arg>[^)]*?)\s*\)""")


def published_words(text):
    """(the literal words, the calls with anything else) of the `line_stage.publish(...)` calls in a source text."""
    words, other = [], []
    for found in PUBLISH.finditer(text):
        arg = found.group("arg")
        if arg.startswith("line_stage.for_kinds("):      # the one call that chooses from the sources' types: checked by name below
            continue
        literal = re.fullmatch(r"""(["'])([a-z]+)\1""", arg)
        (words if literal else other).append(literal.group(2) if literal else arg)
    return words, other


def scan():
    words, other = [], []
    for path in sorted(st.RUNTIME.glob("*.py")):
        if path.name in ("line_stage.py", "messaging_ack.py"):
            continue
        w, o = published_words(path.read_text(encoding="utf-8"))
        words += w
        other += [f"{path.name}: {a}" for a in o]
    return words, other


def test_every_word_published_in_the_runtime_is_in_the_closed_list_and_every_stage_but_research_is_published_by_name():
    words, other = scan()
    assert other == []      # no call passes a variable: no word of the person can become a stage
    assert set(words) <= set(THE_EIGHT)
    assert set(words) == set(THE_EIGHT) - {"research"}      # `research` is chosen by `for_kinds` where an answer reads other sources
    source = (st.RUNTIME / "ops_ask.py").read_text(encoding="utf-8")
    assert "line_stage.publish(line_stage.for_kinds(" in source


def test_the_scan_flags_a_planted_unknown_stage_and_a_planted_variable():      # vacuity
    words, other = published_words('line_stage.publish("mailbox")\nline_stage.publish(said)\nline_stage.publish("mail")\nother.publish(said)\n')
    assert words == ["mailbox", "mail"] and other == ["said"]
    assert set(words) - set(THE_EIGHT) == {"mailbox"}
