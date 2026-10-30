"""The frame: one dispatcher over the pending kinds (package S41-8; PLAN-BRAIN section 3, "one dispatcher decides a sim or a correction across all pending kinds"; limits L64 and L65).

WHAT IS CHECKED. The seven claimers that answered what is open (a question about a reminder, an expired one, a question about a write, the OK of a plan, the words that decide a card, the stop of a
search, the change of the card that waits) are the kinds of the one row `frame`: `turn_order.FRAME_KINDS`, with code in `messaging_turn.KINDS` (`applies` and `take`). This file proves, on the
entry corpus and never by reading, what S41-8 must keep:

(1) The dispatcher: the first kind that applies and takes ends the frame and is named by `turn.frame_kind`; a `take` that returns False after its side effect (the write kind) lets the next kind read the
line; the discarded-question mark is cleared before any kind reads; the order is read from `turn_order.kinds()` at each call.
(2) Every kind is load-bearing: with its `applies` made to read nothing, at least one scenario that the golden has the claimer take no longer has the golden's outcome.
(3) The order of adjacent kinds. For each of the six pairs, the corpus has scenarios where both kinds apply to the line (a probe reads every kind's `applies` on the live turn): where the order is seen,
the first kind wins in the golden and swapping the two changes an outcome; for the two pairs whose order no outcome sees (the question about a reminder and the expired one, which are disjoint by the
`drafted` mark; the OK of a plan and the card words, which share a word and never a record), the corpus shows that they are disjoint, and the swap is shown to change nothing (a finding, stated: if a
later package lets the two overlap in outcome, the test fails and the order must be reconsidered with L64 and L65 in hand).
(4) The corpus lines the spec names: a "no" with a card last while a search runs rejects the card and leaves the search running (the card words go before the brake); a "stop" stops the search and leaves the
card open; a greeting that is also a yes ("beleza", "tudo bem", "ok, beleza") OKs a plan that is the last message, and a greeting in question form ("oi, tudo bem?", "tudo bem?") never does: it is the greeting
(the maintainer's decision of 2026-10-26, DECISIONS.md, package L64H; the golden rows of the two question forms with the plan last were re-recorded for it), and with the plan not last all five are as recorded.
(5) The envelope is read once (`envelope_problems`: run once per scenario, with the other observers, by `test_entry_observed.py`; the vacuity without the memo and the size of the set are here): over the corpus, no ledger record of the same message is read twice in one dispatch, and at most two messages (the one replied to and the last) are read; with the memo
taken away the same scenarios read twice (vacuity); a record that was not found is never kept. The envelope does not keep `last_sent`: the kind `plan-confirm` reads the last record when it acts, so a
message sent after the line was read ends the OK (a barrier test). The kind `decision-card-word` reads `last_sent` once, when it takes the line, and `word_act` reads it again just before the act
(`Bridge.still_last`, package L64H), as `plan_decide` does for a yes: a message sent between the two decides nothing (test_messaging_word_barrier.py, test_messaging_plan_greeting.py).
(6) Two guards no corpus line reaches, kept by unit tests: the card words' kind refuses a forwarded line, and the plan kind refuses a question of a project that no longer lists the sender.

NO CALLS. The scenarios are replayed with the stand-ins of entry_kit.py: no model, no provider process. The golden is never recorded here.

Run: uv run --with pytest==9.1.1 --with pytest-xdist pytest -q -n 4 runtime/tests/test_frame_dispatch.py
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

import entry_kit as ek
import standin_tree as st
import test_entry_replay as rp
import test_turn_order as to


messaging_turn = st.load("messaging_turn")
turn_order = st.load("turn_order")
messaging_ledger = st.load("messaging_ledger")
messaging_bridge = st.load("messaging_bridge")
shell_kit = st.load("shell_kit")

KINDS = tuple(turn_order.kinds())
KIT = ek.FRAME_KIT_NAMES      # the names the golden gives the claimers the kinds took over
PAIRS = list(zip(KINDS, KINDS[1:]))
SEEN = {("reminder-expired", "write-draft"), ("write-draft", "plan-confirm"), ("decision-card-word", "research-run"), ("research-run", "decision-card-again")}
DISJOINT = {("reminder-draft", "reminder-expired"), ("plan-confirm", "decision-card-word"), ("decision-card-again", "decision-card-revise")}


def swapping(first, second):
    """A hook that puts two kinds in each other's places in `turn_order.kinds()` (the frame reads it at each call)."""
    def hook(mp):
        order = list(turn_order.kinds())
        a, b = order.index(first), order.index(second)
        order[a], order[b] = order[b], order[a]
        mp.setattr(turn_order, "kinds", lambda order=tuple(order): order)
    return hook


def disabling(kind):
    def hook(mp):
        mp.setattr(messaging_turn.KINDS[kind], "applies", lambda *a, **k: None)
    return hook


def applying(scenario, tmp_path) -> list:
    """The kinds whose `applies` is true on the live turn when the frame is entered, in the order of the kinds: a probe, taken before the real frame runs (the outcome is not compared)."""
    seen, mine, real = [], threading.current_thread(), messaging_turn.ROWS["frame"]

    def hook(mp):
        def frame(bridge, turn):
            if threading.current_thread() is mine and not seen:      # a job started by the pre-state or the line is another dispatch on another thread
                turn.bridge = bridge
                seen.append([name for name in turn_order.kinds() if messaging_turn.KINDS[name].applies(bridge, turn)])
            return real(bridge, turn)
        mp.setitem(messaging_turn.ROWS, "frame", frame)
    rp.replay(scenario, tmp_path, hook)
    return seen[0] if seen else []


def candidates(first, second, extra=()) -> list:
    """The messaging scenarios whose golden trace names either of the two kinds (by the kit's names), plus the ones of the pre-states in `extra`."""
    _, recorded = rp.golden()
    names = {KIT[first], KIT[second]}
    return [s for s in rp.corpus() if s["channel"] == "messaging" and (names & set(recorded[s["id"]]["trace"]) or s["prestate"] in extra)]


# --- the dispatcher ------------------------------------------------------------------------------------------------------------------------------------


def stub_kinds(monkeypatch, results):
    """Replace every kind by a stand-in that records its `applies` and its `take`: `results[name]` is `(found, took)` (default `(None, False)`). Returns the list of calls."""
    called = []
    for name in turn_order.kinds():
        found, took = results.get(name, (None, False))

        def applies(b, t, name=name, found=found):
            called.append(("applies", name))
            return found

        def take(b, t, f, name=name, took=took):
            called.append(("take", name))
            return took
        monkeypatch.setitem(messaging_turn.KINDS, name, messaging_turn.Kind(applies, take))
    return called


def bridge_stub(chat="1"):
    return SimpleNamespace(remind=SimpleNamespace(discarded={chat}, drafts={}, expired={}))


def test_the_first_kind_that_applies_and_takes_ends_the_frame_and_is_named(monkeypatch):
    called = stub_kinds(monkeypatch, {"write-draft": (True, True), "decision-card-word": (True, True)})
    bridge, turn = bridge_stub(), messaging_turn.Turn(chat="1")
    assert messaging_turn.frame(bridge, turn) is True and turn.frame_kind == "write-draft"
    assert called == [("applies", "reminder-draft"), ("applies", "reminder-expired"), ("applies", "write-draft"), ("take", "write-draft")], "none after the one that took the line, and a kind that does not apply is not taken"
    assert bridge.remind.discarded == set(), "a new line begins with no write question dropped by it, before any kind reads it"


def test_a_take_that_returns_false_lets_the_next_kind_read_the_line(monkeypatch):
    called = stub_kinds(monkeypatch, {"write-draft": ("question", False), "plan-confirm": ("yes", True)})
    turn = messaging_turn.Turn(chat="1")
    assert messaging_turn.frame(bridge_stub(), turn) is True and turn.frame_kind == "plan-confirm"
    assert ("take", "write-draft") in called and called.index(("take", "write-draft")) < called.index(("applies", "plan-confirm"))


def test_a_line_no_kind_takes_leaves_the_frame_false_and_unnamed(monkeypatch):
    stub_kinds(monkeypatch, {})
    turn = messaging_turn.Turn(chat="1")
    assert messaging_turn.frame(bridge_stub(), turn) is False and turn.frame_kind is None


def test_the_frame_reads_the_order_of_the_kinds_at_each_call(monkeypatch):
    called = stub_kinds(monkeypatch, {"research-run": (True, True), "plan-confirm": (True, True)})
    monkeypatch.setattr(turn_order, "kinds", lambda: ("research-run", "plan-confirm"))
    turn = messaging_turn.Turn(chat="1")
    assert messaging_turn.frame(bridge_stub(), turn) is True and turn.frame_kind == "research-run" and called == [("applies", "research-run"), ("take", "research-run")]


# --- every kind is load-bearing ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_is_load_bearing_disabling_it_changes_a_scenario(kind, tmp_path):
    scenarios = rp.scenarios_of(KIT[kind], 60)
    assert scenarios, f"the corpus holds lines the claimer {KIT[kind]} (the kind {kind}) takes"
    assert to.changed(disabling(kind), scenarios, tmp_path), f"no scenario of the corpus needs the kind {kind}"


# --- the order of adjacent kinds -----------------------------------------------------------------------------------------------------------------------


def test_the_adjacent_pairs_are_the_ones_the_tests_below_say():
    assert PAIRS == [("reminder-draft", "reminder-expired"), ("reminder-expired", "write-draft"), ("write-draft", "plan-confirm"), ("plan-confirm", "decision-card-word"),
                     ("decision-card-word", "research-run"), ("research-run", "decision-card-again"), ("decision-card-again", "decision-card-revise")]
    assert SEEN | DISJOINT == set(PAIRS) and not SEEN & DISJOINT


@pytest.mark.parametrize("first, second", sorted(SEEN))
def test_where_both_kinds_apply_the_first_wins_and_swapping_them_changes_an_outcome(first, second, tmp_path):
    """L64 and L65. A scenario where both kinds read the line and the golden has the first take it: put in the other order, the second takes it (or the first no longer sees it) and the outcome differs.
    The examples: a stop word with a card last while a search runs; a yes with a write question open and a plan last; a yes that an expired reminder question and an open write question both read."""
    _, recorded = rp.golden()
    both = [s for s in candidates(first, second) if {first, second} <= set(applying(s, tmp_path))]
    assert both, f"the corpus holds lines that both {first} and {second} read"
    first_wins = [s for s in both if KIT[first] in recorded[s["id"]]["trace"]]
    assert first_wins, f"in the golden, {KIT[first]} takes at least one line that {second} also reads"
    assert to.changed(swapping(first, second), first_wins, tmp_path), f"swapping {first} and {second} changes no scenario: the corpus does not see this order"


def test_the_two_reminder_questions_are_disjoint_by_the_mark_and_their_swap_is_not_seen(tmp_path):
    """The question about a reminder that is open and the one that expired are never read by both kinds: `drafted` (the question was open when the line came) keeps the expired kind and the write kind
    away from a chat that has one, whatever `remind.answer` says. The corpus has both states at once (`reminder_and_expired`): there the first kind reads and the second does not."""
    _, recorded = rp.golden()
    states = ("reminder_draft", "reminder_expired", "reminder_and_expired", "expired_and_write_draft", "reminder_and_write_draft")
    scenarios = [s for s in rp.corpus() if s["channel"] == "messaging" and s["prestate"] in states]
    assert len([s for s in scenarios if s["prestate"] == "reminder_and_expired"]) >= 5
    reads = {s["id"]: applying(s, tmp_path) for s in scenarios}
    assert not [sid for sid, kinds in reads.items() if {"reminder-draft", "reminder-expired"} <= set(kinds)], "no line is read by both"
    assert len([s for s in scenarios if s["prestate"] == "reminder_and_expired" and "reminder-draft" in reads[s["id"]] and "reminder-expired" not in reads[s["id"]]]) >= 3
    assert any(KIT["reminder-draft"] in recorded[s["id"]]["trace"] for s in scenarios if s["prestate"] == "reminder_and_expired")
    assert not to.changed(swapping("reminder-draft", "reminder-expired"), scenarios, tmp_path), "the two kinds never read the same line, so their order is no outcome"


def plan_and_card_candidates() -> list:
    """The scenarios either of the OK of a plan and the card words takes, with the pre-states the two tests below need (at least 40 of them)."""
    scenarios = candidates("plan-confirm", "decision-card-word")
    assert len(scenarios) >= 40 and {s["prestate"] for s in scenarios} >= {"plan_last", "plan_not_last", "plan_then_card", "card_last", "two_cards"}
    return scenarios


def test_the_ok_of_a_plan_and_the_card_words_both_read_the_word_in_many_scenarios(tmp_path):
    """SPEC-41-2 asked for a swap of the OK of a plan and the card words that changes a scenario. It cannot: the two read the same word (a "sim" is a yes and an approve), and their `take`s are
    disjoint by their own conditions, not by their place. SLOW-1 split the one test that held this and the swap below in two (the same work, half the longest item): this half is "on every scenario
    where both read the word (at least 20 of them)"."""
    scenarios = plan_and_card_candidates()
    assert len([s for s in scenarios if {"plan-confirm", "decision-card-word"} <= set(applying(s, tmp_path))]) >= 20, "both read the word in many scenarios"


def test_the_ok_of_a_plan_and_the_card_words_swap_changes_no_scenario(tmp_path):
    """The other half of the finding: `plan-confirm` takes only a ledger record of kind `plan-confirm`; `decision-card-word` decides only a decision card (`word_reply` and `word_cards` refuse every
    kind of `NOT_DECISION`, which holds `plan-confirm`) and, with a plan that waits and a card sent after it, answers `PLAN_TWO_OPEN` without deciding. On every scenario either takes, the swap
    changes none."""
    scenarios = plan_and_card_candidates()
    assert not to.changed(swapping("plan-confirm", "decision-card-word"), scenarios, tmp_path)


# --- the lines the spec names -------------------------------------------------------------------------------------------------------------------------


def outcome(sid, tmp_path) -> dict:
    scenario = next(s for s in rp.corpus() if s["id"] == sid)
    return rp.replay(scenario, tmp_path)


def test_a_no_with_a_card_last_while_a_search_runs_rejects_the_card_and_leaves_the_search_running(tmp_path):
    """L64 and BL2b: the card words go before the brake. A no word is a card word first."""
    scenarios = [s for s in rp.corpus() if s["prestate"] == "research_and_card" and s["platform"] == "buttons" and s["text"] in ("n\u00e3o", "no")]
    assert len(scenarios) >= 2
    for scenario in scenarios:
        found = rp.replay(scenario, tmp_path)
        assert found["trace"] == ["card-word"], scenario["id"]
        assert [call[0] for call in found["ops_calls"] if call[0] in ("reject", "research_stop")] == ["reject"], "the card is rejected and the search is not stopped"


def test_a_stop_word_with_a_card_last_while_a_search_runs_stops_the_search_and_leaves_the_card_open(tmp_path):
    """A stop word is no card word: the search is the brake's, the card still waits."""
    scenarios = [s for s in rp.corpus() if s["prestate"] == "research_and_card" and s["platform"] == "buttons" and s["text"] in ("pare", "stop")]
    assert len(scenarios) >= 2
    for scenario in scenarios:
        found = rp.replay(scenario, tmp_path)
        assert found["trace"] == ["research-stop"], scenario["id"]
        assert [call[0] for call in found["ops_calls"] if call[0] in ("reject", "approve", "research_stop")] == ["research_stop"], "the search is stopped and no card is decided"


YES_GREETINGS = ("beleza", "tudo bem", "ok, beleza")
GREETING_QUESTIONS = ("oi, tudo bem?", "tudo bem?")
GREETINGS_THAT_ARE_YES = YES_GREETINGS + GREETING_QUESTIONS


def test_a_greeting_that_is_a_yes_oks_a_plan_that_is_last_and_a_greeting_question_never_does(tmp_path):
    """With the plan's question as the last message the yes greetings are its OK (the confirmed call runs: a read of the items) and a greeting in question form is the greeting (the maintainer's decision
    of 2026-10-26, L64H): trace `say`, `decide-without-slot` (S41-11: the sender is read by the interpreter), `greeting`, no read, each equal to its golden row, and field by field the outcome of its `plan_not_last` twin (the same id suffix). With another message
    after the question all five are as recorded."""
    _, recorded = rp.golden()
    last = {s["text"]: s for s in rp.corpus() if s["id"].startswith("opscomp.plan_last_and_a_greeting_that_is_a_yes.") and s["channel"] == "messaging" and s["text"] in GREETINGS_THAT_ARE_YES}
    not_last = {s["text"]: s for s in rp.corpus() if s["id"].startswith("opscomp.plan_not_last_and_a_greeting_that_is_a_yes.") and s["channel"] == "messaging" and s["text"] in GREETINGS_THAT_ARE_YES}
    assert set(last) == set(GREETINGS_THAT_ARE_YES) and set(not_last) == set(GREETINGS_THAT_ARE_YES)
    for text in YES_GREETINGS:
        found = rp.replay(last[text], tmp_path)
        assert found["trace"] == ["plan-confirm-word", "confirmed-plan"] and "read:items" in [call[0] for call in found["ops_calls"]], text
        assert not rp.differences(recorded[last[text]["id"]], found)
    for text in GREETING_QUESTIONS:
        found = rp.replay(last[text], tmp_path)
        assert found["trace"] == ["say", "decide-without-slot", "greeting"] and "read:items" not in [call[0] for call in found["ops_calls"]], text
        assert not rp.differences(recorded[last[text]["id"]], found)
        twin = rp.replay(not_last[text], tmp_path)
        assert not rp.differences(twin, found), f"{text}: the same outcome as the plan that is not last"
        assert last[text]["id"].rsplit(".", 1)[1] == not_last[text]["id"].rsplit(".", 1)[1], "the twin has the same id suffix"
    for text in GREETINGS_THAT_ARE_YES:
        found = rp.replay(not_last[text], tmp_path)
        assert "plan-confirm-word" not in found["trace"] and "confirmed-plan" not in found["trace"], text
        assert not rp.differences(recorded[not_last[text]["id"]], found)


# --- the envelope is read once ----------------------------------------------------------------------------------------------------------------------


def envelope_hook(seen, memo=True):
    """A hook that records in `seen` the `(chat, message id)` of every ledger read that found a record, which this scenario's own dispatch makes (the thread that builds the hook is the one that delivers the
    line), with the turn's memo as it is or taken away."""
    handling, mine = [], threading.current_thread()

    def hook(mp):
        real, real_handle = messaging_ledger.Ledger.by_message, messaging_bridge.Bridge._handle

        def by_message(self, chat, message_id):
            found = real(self, chat, message_id)
            if found is not None and threading.current_thread() is mine and handling:      # the kit reads the ledger itself before it delivers the line: only what `Bridge._handle` reads is the dispatch's; a record not found is read again on purpose
                seen.append((chat, message_id))
            return found

        def handle(self, update):
            handling.append(True)
            try:
                return real_handle(self, update)
            finally:
                handling.pop()
        mp.setattr(messaging_ledger.Ledger, "by_message", by_message)
        mp.setattr(messaging_bridge.Bridge, "_handle", handle)
        if not memo:
            mp.setattr(messaging_turn.Turn, "record", lambda self, message_id: self.bridge.ledger.by_message(self.chat, message_id) if message_id else None)
    return hook


def reads_of(scenario, tmp_path, memo=True) -> list:
    """The `(chat, message id)` of every ledger read that found a record, which this scenario's own dispatch makes, with the turn's memo as it is or taken away."""
    seen = []
    rp.replay(scenario, tmp_path, envelope_hook(seen, memo))
    return seen


def envelope_scenarios() -> list:
    _, recorded = rp.golden()
    frame_names = set(KIT.values())
    return [s for s in rp.corpus() if s["channel"] == "messaging" and (s["reply_to"] is not None or (frame_names & set(recorded[s["id"]]["trace"])))]


def envelope_problems(results, ids) -> list:
    """Item (5), run once per scenario with the other observers by `test_entry_observed.py`: `results` is `[(scenario, what envelope_hook recorded)]` and `ids` the ids of `envelope_scenarios()`. Today's
    chain read the record of the message replied to up to four times (the rewrite of a reply, the OK of a plan, the card words, the change of a card) and the last message's twice; the envelope reads
    each once. The spy counts the reads of the dispatching thread over the scenarios where a kind reads a record (a reply, a plan, a card, a stop, a change): at most two messages (the one replied to
    and the last), each read once; and the spy sees at least one read in the set it is given (a line reads the record of the message it replies to, or of the last message: in this corpus never
    both, a reply names its card)."""
    found, worst = [], 0
    for scenario, reads in results:
        if scenario["id"] not in ids:
            continue
        if len(reads) != len(set(reads)):
            found.append(f"{scenario['id']}: a message was read twice in one dispatch: {reads}")
        if len({message for _, message in reads}) > 2:
            found.append(f"{scenario['id']}: more than the replied and the last message: {reads}")
        worst = max(worst, len(reads))
    if worst < 1:
        found.append("the spy sees no read: a line reads the record of the message it replies to, or of the last message")
    return found


def test_the_envelope_scenarios_are_enough():
    """The size of the set `envelope_problems` is run over (no replay): the scenarios where a kind reads a record (a reply, a plan, a card, a stop, a change), at least 100, at least 30 of them replies."""
    scenarios = envelope_scenarios()
    assert len(scenarios) >= 100 and len([s for s in scenarios if s["reply_to"] is not None]) >= 30


def test_vacuity_without_the_memo_the_same_scenarios_read_a_message_twice(tmp_path):
    twice = [s["id"] for s in envelope_scenarios() if s["reply_to"] is not None and (lambda r: len(r) != len(set(r)))(reads_of(s, tmp_path, memo=False))]
    assert twice, "the test above can fail: a reply to a card read by the OK of a plan and again by the card words is two reads when each asks for itself"


# --- last_sent is read where a kind uses it -----------------------------------------------------------------------------------------------------------


class Barrier:
    """A bridge that holds the question of a plan as the last message and lets a second thread send another message at a chosen moment."""

    def __init__(self):
        self.ledger = SimpleNamespace(by_message=self.by_message)
        self.messenger = SimpleNamespace(capabilities=lambda: {})
        self.last_sent = {"1": "question"}
        self.records = {"question": {"kind": "plan-confirm", "chat": "1", "project": "p1", "message_id": "question", "plan_item": "i1", "plan_sha256": "h"},
                        "reminder": {"kind": "reminder", "chat": "1", "project": "p1", "message_id": "reminder"}}
        self.read, self.decided = [], []

    def by_message(self, chat, message_id):
        self.read.append(message_id)
        return self.records.get(message_id)

    def plan_decide(self, target, chat, rec, word, said, last=None):
        self.decided.append((rec["message_id"], word))


def make_turn(bridge, listed=None, forwarded=False):
    update = {"reply_to": None, "text": "sim"}
    if forwarded:
        update["forwarded"] = True
    turn = messaging_turn.Turn(update=update, sender="1", chat="1", listed=listed if listed is not None else [{"id": "p1"}], project={"id": "p1"}, bridge=bridge)
    turn.intent, turn.kind = {"kind": "text", "text": "sim"}, "text"
    return turn


def test_a_message_sent_between_the_reading_of_the_line_and_the_call_ends_the_word():
    """L64: the question is the last message while the line is read; another thread sends a message (a delivered reminder) before the kind reads the record it acts on. `last_sent` is read where the kind
    uses it, so the record read is the reminder's and nothing is decided. Barrier: the second thread sends after `applies`, the kind's `take` runs only after it did."""
    bridge = Barrier()
    kind, turn = messaging_turn.KINDS["plan-confirm"], make_turn(bridge)
    word = kind.applies(bridge, turn)
    assert word == "yes"
    sent, release = threading.Event(), threading.Event()

    def another_thread():
        bridge.last_sent["1"] = "reminder"      # the platform's reply of a job thread: the last message is now the reminder
        sent.set()
        release.wait(5)
    worker = threading.Thread(target=another_thread, daemon=True)
    worker.start()
    assert sent.wait(5)
    try:
        assert kind.take(bridge, turn, word) is False and bridge.decided == [], "the last message is no longer the question: the word decides nothing"
        assert bridge.read == ["reminder"], "the record read is the one of the message that is last when the kind acts"
    finally:
        release.set()
        worker.join(5)


def test_vacuity_a_kept_last_message_would_have_decided_the_plan(monkeypatch):
    """The test above can fail: with the last message kept from the reading of the line (a snapshot the envelope does not take), the same sequence decides the plan."""
    bridge = Barrier()
    kind, turn = messaging_turn.KINDS["plan-confirm"], make_turn(bridge)
    word = kind.applies(bridge, turn)
    kept = bridge.last_sent["1"]
    bridge.last_sent["1"] = "reminder"
    monkeypatch.setattr(messaging_turn.Turn, "last_record", property(lambda self: self.record(kept)))
    assert kind.take(bridge, turn, word) is True and bridge.decided == [("question", "yes")], "the same sequence decides the plan when the last message is kept"


# --- two guards that no corpus line reaches, kept by unit tests ------------------------------------------------------------------------------------------


def test_the_card_words_kind_refuses_a_forwarded_line():
    """L64: a forwarded message never decides a card. The row `forwarded-refusal` answers a forwarded text before the frame, so no corpus line reaches this check; the kind keeps it for itself (as the
    kind `plan-confirm` does, `claims` in test_messaging_plan_confirm.py) and this test is what fails if it goes."""
    kind = messaging_turn.KINDS["decision-card-word"]
    bridge = Barrier()
    assert kind.applies(bridge, make_turn(bridge, forwarded=True)) is None
    assert kind.applies(bridge, make_turn(bridge))["op"] == "approve", "control: the same line, not forwarded, is the word"


def test_vacuity_the_forwarded_check_is_the_turns_property(monkeypatch):
    monkeypatch.setattr(messaging_turn.Turn, "forwarded", property(lambda self: False))
    bridge = Barrier()
    assert messaging_turn.KINDS["decision-card-word"].applies(bridge, make_turn(bridge, forwarded=True)) is not None, "the test above can fail"


def test_the_plan_kind_refuses_a_question_of_a_project_that_no_longer_lists_the_sender():
    """L64 and L65: the OK is taken only when the question's project lists the sender now. The question is the last message and its record is a live plan's; the sender's projects no longer name it."""
    kind = messaging_turn.KINDS["plan-confirm"]
    bridge = Barrier()
    turn = make_turn(bridge, listed=[{"id": "p2"}])
    word = kind.applies(bridge, turn)
    assert word == "yes"
    assert kind.take(bridge, turn, word) is False and bridge.decided == [], "no project of the sender holds the question: nothing is decided"
    control = make_turn(bridge)
    assert kind.take(bridge, control, kind.applies(bridge, control)) is True and bridge.decided == [("question", "yes")], "control: with the project listed, the same word is the OK"


def test_a_record_that_lands_during_the_dispatch_is_seen_and_a_found_one_is_read_once():
    """The envelope keeps only a record that was found: an absent one is read again (a send that returns while the line is handled is seen by the next kind), a found one is read once."""
    bridge = Barrier()
    turn = make_turn(bridge)
    bridge.records.pop("question")
    assert turn.record("question") is None
    bridge.records["question"] = {"kind": "plan-confirm", "chat": "1", "message_id": "question"}
    assert turn.record("question")["kind"] == "plan-confirm" and turn.record("question") is turn.record("question")
    assert bridge.read.count("question") == 2, "one read that found nothing, one that found the record, and no more"


# --- the pre-states wait for the job that built them ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sid", ["guard.plan_confirm.15"])
def test_a_job_that_ends_late_does_not_change_the_world_the_line_meets(sid, tmp_path, monkeypatch):
    """CI failed twice on a timing the kit left open, on the base as on this package (reproduced there: the same fields differ). The job that sends a pre-state's question records it in the ledger and then
    releases the project's slot; the kit went on as soon as the record was there, so on a loaded machine a line (or the owner's yes) met a busy project: it was queued and told so (an extra `say`,
    `Got it: I will answer this after the current one`), or the yes was refused as busy and the plan was never taken (`PLAN_TWO_OPEN` for the next word, no search running). Here every job ends 0.5 s
    after its call returns: the pre-state must wait for it (`entry_kit.slot_free`), and the outcome is the golden's."""
    real = shell_kit.Jobs._run_job

    def run(self, job, call, exclusive):
        def slow():
            try:
                return call()
            finally:
                time.sleep(0.5)      # the tail of a job: the result is recorded, the slot is not yet free
        return real(self, job, slow, exclusive)
    monkeypatch.setattr(shell_kit.Jobs, "_run_job", run)
    _, recorded = rp.golden()
    scenario = next(s for s in rp.corpus() if s["id"] == sid)
    found = rp.replay(scenario, tmp_path)
    assert not rp.differences(recorded[sid], found), sid


@pytest.mark.parametrize("sid", ["card-word.take.27", "guard.research_brake.22", "guard.research_brake.24"])
def test_an_acknowledgement_that_is_slow_to_send_does_not_change_the_search_prestate(sid, tmp_path, monkeypatch):
    """FLAKY-RESEARCH-PRESTATE-2. The search's pre-state set the acknowledgement delay to 0.2 s before the owner asked. On a loaded machine the line that asks the question took longer than that: its
    acknowledgement timer fired, the send began, and the job ended and sent the question (the timer is stopped before the question, but a send that had begun is not undone) before the acknowledgement
    reached the chat: it came AFTER the question, which was then no longer the last message, so the owner's yes was told "to confirm, reply yes to the question" and no search began. Here the call that
    answers the line takes 0.3 s and an acknowledgement takes 0.5 s to send, which is that order on any machine; the pre-state must give the question's line no acknowledgement (the delay is
    set for the owner's yes only), and the outcome is the golden's. (The same loaded machine let the held search time out at the kit's 10 s bound and answer before the line: the search is held
    for `HELD_SECONDS`.)"""
    real_run, real_ack = messaging_bridge.Bridge.run_op, messaging_bridge.Bridge.acknowledge

    def run_op(self, project, op, *args, **kwargs):
        if op == "say":
            time.sleep(0.3)
        return real_run(self, project, op, *args, **kwargs)

    def acknowledge(self, project, chat, stage):
        time.sleep(0.5)
        return real_ack(self, project, chat, stage)
    monkeypatch.setattr(messaging_bridge.Bridge, "run_op", run_op)
    monkeypatch.setattr(messaging_bridge.Bridge, "acknowledge", acknowledge)
    _, recorded = rp.golden()
    scenario = next(s for s in rp.corpus() if s["id"] == sid)
    found = rp.replay(scenario, tmp_path)
    assert not rp.differences(recorded[sid], found), sid
