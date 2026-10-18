"""A queued line instead of "busy" on a messaging app (package BQ-1; runtime/messaging_bridge.py: `queueable`, `Bridge.keep`, `Bridge.drain`,
`Bridge.close_queue`), over the REAL operations layer (its table, its configuration, its policy) and a stand-in messenger provider. The planning
agent's `say` is a recorder that can be held (so a run takes the project's slot as long as a test wants) or made to answer "busy" (RunBusy), and
the bridge's clock for the queue is a fake one. Offline, no model; invented ids.

A test waits for what it expects with a deadline, and waits for the bridge's job threads before it says that something did NOT happen, so the
file is safe under `-n auto`.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_queue.py
"""
from __future__ import annotations

import threading
import time

import pytest

import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging import wait_for
from test_sender_profiles import OWNER, STAFF, accept, write_config
from test_sender_profiles_bridge import NOT_ENABLED, POLICIES_ALL, configure, lab  # noqa: F401  (the lab fixture)

bridge = st.load("messaging_bridge")
ops = st.load("ops")
ops_core = st.load("ops_core")

WAIT = 10
LINE = "SECRET-LINE-7719 when does the shop open"
BUSY = "the planning agent is answering another request of this project"


def chat_ids(count):
    return [f"5511900001{n:04d}" for n in range(count)]


class Planner:
    """The stand-in for ops.say: records each call, holds the calls whose index is in `hold` until the test opens them, and answers the first
    `refusals` calls with RunBusy. Its reply is a fixed sentence with the call's number, never the line."""

    def __init__(self):
        self.calls, self.hold, self.refusals, self.lock = [], set(), 0, threading.Lock()
        self.gates, self.entered, self.free = {}, {}, False

    def event(self, table, k):
        with self.lock:
            return table.setdefault(k, threading.Event())

    def gate(self, k):
        return self.event(self.gates, k)

    def reached(self, k):
        return self.event(self.entered, k)

    def say(self, project, text, channel=None, sender=None):
        with self.lock:
            k = len(self.calls)
            self.calls.append({"text": text, "channel": channel, "sender": sender})
            refuse = self.refusals > 0
            self.refusals -= 1 if refuse else 0
            held = k in self.hold and not self.free
        self.reached(k).set()
        if refuse:
            raise ops_core.RunBusy(BUSY, 1)
        if held:
            self.gate(k).wait(WAIT)
        return {"reply": f"Answer {k}", "request_id": None, "pending_id": None, "ran": True, "queued": False}

    def texts(self):
        with self.lock:
            return [c["text"] for c in self.calls]

    def open_all(self):
        self.free = True
        with self.lock:
            gates = list(self.gates.values())
        for gate in gates:
            gate.set()
        for k in list(self.hold):
            self.gate(k).set()


@pytest.fixture
def planner(lab, monkeypatch):  # noqa: F811
    p = Planner()
    monkeypatch.setattr(ops, "say", p.say)
    yield p
    p.open_all()      # a thread a test left holding ends before the lab fixture joins it


def settle(lab, seconds=WAIT):  # noqa: F811
    """Wait until every job thread of the bridge has ended and the project's slot is free: the point after which 'nothing else happened' is true."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        alive = [t for t in list(lab.bridge.threads) if t.is_alive()]
        if not alive and not lab.bridge.exclusive:
            return True
        for thread in alive:
            thread.join(0.05)
        time.sleep(0.01)
    return False


def clocked(lab, start=1000.0):  # noqa: F811
    """The bridge's clock for the queue as a list the test moves."""
    now = [start]
    lab.bridge.monotonic = lambda: now[0]
    return now


def two(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}])


def many(lab, count):  # noqa: F811
    ids = chat_ids(count)
    configure(lab, [{"id": i, "policy": "owner"} for i in ids])
    return ids


def project_id(lab):  # noqa: F811
    return lab.bridge.projects[0]["id"]


# --- which lines may wait -------------------------------------------------------------------------------------------------------------------


def test_a_plain_line_and_the_lines_that_run_the_router_may_wait_and_a_command_never_does():
    for line in ("when does the shop open", "/new plan the launch", "/ask what is the deadline?", "/ask@openhora_bot what is the deadline?", "/NEW x"):
        assert bridge.queueable(line), line
    for line in ("/progress", "/cancel 3", "/stop-task 2", "/status", "/costs", "/retry 4", "/help", "/pending", "/approve 5", "/"):
        assert not bridge.queueable(line), line


# --- two lines in a row -----------------------------------------------------------------------------------------------------------------------


def test_two_lines_in_a_row_are_both_answered_in_order_and_a_third_is_refused_with_todays_sentence(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0, 1}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(OWNER, "second")
    assert lab.texts(OWNER) == [bridge.QUEUED] and planner.texts() == ["first"], "the second waits: nothing runs beside the first"
    lab.say(OWNER, "third")
    assert lab.texts(OWNER) == [bridge.QUEUED, bridge.STILL_WORKING], "one waiting line per chat: the third gets the sentence it always got"
    planner.gate(0).set()
    assert planner.reached(1).wait(WAIT), "the end of the first job starts the second"
    planner.gate(1).set()
    assert settle(lab)
    assert planner.texts() == ["first", "second"] and lab.texts(OWNER) == [bridge.QUEUED, bridge.STILL_WORKING, "Answer 0", "Answer 1"]
    assert not lab.bridge.waiting


def test_a_queued_line_runs_as_the_channel_messaging_and_as_its_own_sender(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, "second")
    planner.gate(0).set()
    assert settle(lab)
    assert [(c["channel"], c["sender"]) for c in planner.calls] == [("messaging", f"telegram:{OWNER}"), ("messaging", f"telegram:{STAFF}")]
    assert lab.texts(STAFF) == [bridge.QUEUED, "Answer 1"] and lab.texts(OWNER) == ["Answer 0"], "each line is answered to its own chat"


def test_a_new_line_goes_behind_the_lines_already_waiting_even_when_the_slot_just_became_free(lab, planner):  # noqa: F811
    two(lab)
    assert lab.bridge.keep(lab.bridge.projects[0], STAFF, "old") is True       # waiting, and nothing has started it yet
    lab.say(OWNER, "new")
    assert settle(lab)
    assert planner.texts() == ["old", "new"], "first in, first out inside the bridge"
    assert lab.texts(OWNER)[0] == bridge.QUEUED and lab.texts(STAFF) == ["Answer 0"]


def test_at_most_five_lines_wait_in_a_project_and_a_sixth_chat_is_refused_with_todays_sentence(lab, planner):  # noqa: F811
    ids = many(lab, 7)
    planner.hold = {0}
    lab.say(ids[0], "line 0")
    assert planner.reached(0).wait(WAIT)
    for n in range(1, 6):
        lab.say(ids[n], f"line {n}")
        assert lab.texts(ids[n]) == [bridge.QUEUED], n
    lab.say(ids[6], "line 6")
    assert lab.texts(ids[6]) == [bridge.STILL_WORKING], "the project's queue is full"
    planner.gate(0).set()
    assert settle(lab)
    assert planner.texts() == [f"line {n}" for n in range(6)], "the oldest first, and the refused line never ran"
    assert lab.texts(ids[6]) == [bridge.STILL_WORKING]


# --- the sender's policy is read again when the line runs ---------------------------------------------------------------------------------


def test_a_sender_removed_from_the_configuration_while_waiting_is_not_answered_and_the_line_never_runs(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, LINE)
    assert lab.texts(STAFF) == [bridge.QUEUED]
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    planner.gate(0).set()
    assert settle(lab)
    assert planner.texts() == ["first"], "the removed sender's line was not run"
    assert lab.texts(STAFF) == [bridge.QUEUED], "an unlisted sender gets no reply, as an update from one never does"
    assert bridge.DROPPED in lab.log


def test_a_sender_narrowed_while_waiting_is_refused_at_run_time_with_the_policy_sentence(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, LINE)
    accept(lab.path, policies={**POLICIES_ALL, "staff": ["read-limited", "answer"]})      # `talk` taken away: a narrowing
    planner.gate(0).set()
    assert settle(lab)
    assert planner.texts() == ["first"]
    assert NOT_ENABLED in lab.texts(STAFF)[-1] and lab.texts(STAFF)[0] == bridge.QUEUED


def test_a_sender_who_may_not_talk_is_refused_at_once_and_nothing_is_kept(lab, planner):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}],
              policies={**POLICIES_ALL, "staff": ["read-limited", "answer"]})
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, LINE)
    assert NOT_ENABLED in lab.texts(STAFF)[-1] and not lab.bridge.waiting
    planner.gate(0).set()
    assert settle(lab)
    assert planner.texts() == ["first"]


def test_a_queued_new_line_runs_like_any_line_and_its_text_reaches_the_operation_whole(lab, planner):  # noqa: F811
    """`/ask` (the answer from sources) is queued by the same rule; the table has no `ask` row yet, so `/new` stands for it here."""
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, "/new plan the autumn launch")
    assert lab.texts(STAFF) == [bridge.QUEUED]
    planner.gate(0).set()
    assert settle(lab)
    assert planner.texts() == ["first", "/new plan the autumn launch"] and lab.texts(STAFF)[-1] == "Answer 1"


# --- when the project is busy for another reason -------------------------------------------------------------------------------------------


def test_a_line_that_meets_the_planning_agent_busy_elsewhere_is_kept_and_tried_again_after_a_short_pause(lab, planner):  # noqa: F811
    two(lab)
    now = clocked(lab)
    planner.refusals = 1
    lab.say(OWNER, "hello")
    assert wait_for(lambda: lab.texts(OWNER) == [bridge.QUEUED]), "RunBusy (a run of another shell holds the router) is a wait, not a refusal"
    assert settle(lab) and planner.texts() == ["hello"], "not tried again at once"
    now[0] += bridge.QUEUE_RETRY + 1
    lab.bridge.drain()
    assert settle(lab)
    assert planner.texts() == ["hello", "hello"] and lab.texts(OWNER) == [bridge.QUEUED, "Answer 1"]
    assert lab.texts(OWNER).count(bridge.QUEUED) == 1, "kept once, told once"


def test_a_command_is_never_kept_and_gets_the_sentence_it_always_got(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, "/progress")
    assert lab.texts(STAFF) == [bridge.STILL_WORKING] and not lab.bridge.waiting
    planner.gate(0).set()
    assert settle(lab)
    planner.refusals = 1
    lab.say(STAFF, "/progress")
    assert wait_for(lambda: lab.texts(STAFF)[-1] == bridge.RUN_BUSY), "a command that meets RunBusy is refused, not kept"
    assert settle(lab) and not lab.bridge.waiting


def test_a_tap_during_a_run_is_not_kept(lab, planner):  # noqa: F811
    two(lab)
    lab.bridge.tick()
    button = lab.action(OWNER, "Approve")
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    before = len(lab.texts(OWNER))
    lab.say(OWNER, action=button)
    assert lab.texts(OWNER)[before:] == [f"Approved #{lab.plan}."] and not lab.bridge.waiting, "a plan is approved at the tap, beside the run"
    assert bridge.QUEUED not in lab.texts(OWNER)[before - 1:] and lab.texts(OWNER).count(bridge.QUEUED) == 0
    planner.gate(0).set()
    assert settle(lab)


# --- expiry and stop --------------------------------------------------------------------------------------------------------------------------


def test_a_line_waiting_thirty_minutes_is_dropped_with_its_sentence_and_never_runs(lab, planner):  # noqa: F811
    two(lab)
    now = clocked(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, LINE)
    now[0] += bridge.QUEUE_WAIT - 1
    lab.bridge.drain()
    assert lab.texts(STAFF) == [bridge.QUEUED], "not yet"
    now[0] += 1
    lab.bridge.drain()
    assert lab.texts(STAFF) == [bridge.QUEUED, bridge.QUEUE_EXPIRED] and not lab.bridge.waiting
    planner.gate(0).set()
    assert settle(lab)
    assert planner.texts() == ["first"]
    assert bridge.QUEUE_EXPIRED == "Not answered: the project stayed busy for 30 minutes. Send it again." and bridge.QUEUE_WAIT == 1800


def test_the_end_of_the_loop_tells_every_waiting_chat_once_and_runs_nothing_more(lab, planner, monkeypatch):  # noqa: F811
    """A signal raises the shell's Stop inside `serve_loop`: the chats are told before the runs end (messaging.serve's finally) and the provider closes."""
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, LINE)
    stop = threading.Event()

    class Signal(Exception):
        pass

    def receive(offset, timeout):
        if bridge.QUEUED in lab.texts(STAFF) and not stop.is_set():
            stop.set()
            raise Signal()
        stop.wait(0.02)
        return {"updates": [], "next_offset": offset}
    monkeypatch.setattr(lab.bridge.messenger, "receive", receive)
    deadline = threading.Timer(WAIT, stop.set)       # a loop that never sees the signal ends here and the test fails, it does not hang
    deadline.daemon = True
    deadline.start()
    with pytest.raises(Signal):
        lab.bridge.serve_loop(stop, 60, 1)
    deadline.cancel()
    assert bridge.QUEUE_STOPPED in lab.texts(STAFF) and not lab.bridge.waiting and lab.bridge.stopping.is_set()
    assert bridge.QUEUE_STOPPED == "Not answered: the bridge stopped. Send it again."
    timer = threading.Timer(0.3, planner.gate(0).set)
    timer.start()
    assert lab.bridge.end_runs(wait=WAIT) == 0
    timer.join()
    assert planner.texts() == ["first"] and lab.texts(OWNER)[-1] == "Answer 0" and lab.texts(STAFF).count(bridge.QUEUE_STOPPED) == 1


def test_a_job_that_ends_after_the_stop_began_does_not_start_the_next_line_and_tells_its_chat(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, LINE)
    lab.bridge.stopping.set()
    planner.gate(0).set()
    assert settle(lab)
    assert planner.texts() == ["first"]
    assert wait_for(lambda: lab.texts(STAFF) == [bridge.QUEUED, bridge.QUEUE_STOPPED])


def test_no_line_is_kept_once_the_bridge_is_stopping(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.bridge.stopping.set()
    lab.say(STAFF, LINE)
    assert lab.texts(STAFF) == [] and not lab.bridge.waiting, "a stopping bridge starts nothing and keeps nothing"
    assert lab.bridge.keep(lab.bridge.projects[0], STAFF, LINE) is False
    planner.gate(0).set()
    assert settle(lab)


# --- the oldest line of a project whose slot is free --------------------------------------------------------------------------------------


def test_nothing_starts_while_the_slot_is_taken_and_the_order_is_kept_when_it_frees(lab, planner):  # noqa: F811
    two(lab)
    project = lab.bridge.projects[0]
    assert lab.bridge.keep(project, OWNER, "older") and lab.bridge.keep(project, STAFF, "newer")
    lab.bridge.exclusive[project["id"]] = "job x"                 # something else holds the slot
    lab.bridge.drain()
    assert planner.texts() == [] and [e["text"] for e in lab.bridge.waiting] == ["older", "newer"]
    del lab.bridge.exclusive[project["id"]]
    lab.bridge.drain()
    assert settle(lab)
    assert planner.texts() == ["older", "newer"]


def test_the_loops_start_a_waiting_line_and_drop_an_expired_one_at_each_iteration(lab, planner, monkeypatch):  # noqa: F811
    two(lab)
    now = clocked(lab)
    project = lab.bridge.projects[0]
    lab.bridge.keep(project, STAFF, LINE)
    now[0] += bridge.QUEUE_WAIT
    stop = threading.Event()

    def receive(offset, timeout):
        stop.wait(0.02)
        return {"updates": [], "next_offset": offset}
    monkeypatch.setattr(lab.bridge.messenger, "receive", receive)
    runner = threading.Thread(target=lab.bridge.serve_loop, args=(stop, 60, 1), daemon=True)
    runner.start()
    try:
        assert wait_for(lambda: bridge.QUEUE_EXPIRED in lab.texts(STAFF))
    finally:
        stop.set()
        runner.join(WAIT)
    assert planner.texts() == [] and not lab.bridge.waiting

    class Session:
        fatal, generation = None, 0

        def is_ready(self):
            return True

        def take_unread(self):
            return 0

        def next_update(self, wait):
            stop2.wait(min(wait, 0.02))
            return None
    stop2 = threading.Event()
    lab.bridge.stopping.clear()          # the first loop ended as a shell's does: the bridge was stopping
    lab.bridge.keep(project, OWNER, "from the listen loop")
    runner = threading.Thread(target=lab.bridge.listen_loop, args=(stop2, 60, Session(), 1), daemon=True)      # sends still go through the stand-in provider
    runner.start()
    try:
        assert wait_for(lambda: planner.texts() == ["from the listen loop"] and "Answer 0" in lab.texts(OWNER))
    finally:
        stop2.set()
        runner.join(WAIT)


# --- what is kept and where -------------------------------------------------------------------------------------------------------------------


def test_the_text_of_a_queued_line_is_in_memory_only_never_logged_never_in_the_ledger_never_sent_back(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, LINE)
    assert [e["text"] for e in lab.bridge.waiting] == [LINE], "it is kept, in memory"
    planner.gate(0).set()
    assert settle(lab)
    lab.bridge.stopping.set()
    lab.say(STAFF, LINE + " again")                               # refused while stopping: still no trace
    marker = "SECRET-LINE-7719"
    assert marker not in "\n".join(lab.log), "no log line carries the text"
    assert marker not in str(lab.bridge.ledger.data), "the ledger holds no text of a project"
    seen = []
    for folder in (lab.tmp / "ledger-data", lab.tmp / "state", lab.folder):
        for path in folder.rglob("*"):
            if path.is_file():
                seen.append(path.read_bytes())
    assert seen and not any(marker.encode() in blob for blob in seen), "no file written by the bridge or the messenger carries it"
    assert not any(marker in text for text in lab.texts(STAFF)), "and no reply echoes it"


# --- the review of BQ-1 --------------------------------------------------------------------------------------------------------------------


def test_a_line_that_comes_while_the_oldest_is_being_started_goes_behind_it(lab, planner, monkeypatch):  # noqa: F811
    """The oldest stays in the list, marked, until its run begins: a line that arrives between the choice and the start is kept behind it."""
    two(lab)
    project = lab.bridge.projects[0]
    assert lab.bridge.keep(project, STAFF, "old")
    real, state = lab.bridge.start_job, {}

    def wrapped(*args, **kwargs):
        if "thread" not in state:
            state["thread"] = threading.Thread(target=lab.say, args=(OWNER, "new"), daemon=True)
            state["thread"].start()
            assert wait_for(lambda: [e["text"] for e in lab.bridge.waiting] == ["old", "new"]), "the new line is kept behind the one being started"
        return real(*args, **kwargs)
    monkeypatch.setattr(lab.bridge, "start_job", wrapped)
    lab.bridge.drain()
    state["thread"].join(WAIT)
    assert settle(lab)
    assert planner.texts() == ["old", "new"] and not lab.bridge.waiting


def test_a_stop_between_the_choice_and_the_start_loses_no_line(lab, planner, monkeypatch):  # noqa: F811
    two(lab)
    project = lab.bridge.projects[0]
    assert lab.bridge.keep(project, STAFF, "old")

    def stopping(*args, **kwargs):
        raise bridge.shell_kit.Stopping()
    monkeypatch.setattr(lab.bridge, "start_job", stopping)
    lab.bridge.drain()
    assert lab.texts(STAFF) == [bridge.QUEUE_STOPPED] and not lab.bridge.waiting and planner.texts() == []


def test_the_stop_messages_have_a_total_deadline_and_a_hanging_provider_holds_nothing_back(lab, planner, monkeypatch):  # noqa: F811
    ids = many(lab, 6)
    project = lab.bridge.projects[0]
    for chat in ids[:5]:
        assert lab.bridge.keep(project, chat, "x")
    hang, tried = threading.Event(), []
    monkeypatch.setattr(bridge, "QUEUE_STOP_WAIT", 0.5)

    def send(chat, message):
        tried.append(chat)
        hang.wait(WAIT)
    monkeypatch.setattr(lab.bridge.messenger, "send", send)
    started = time.monotonic()
    try:
        lab.bridge.close_queue()
        assert time.monotonic() - started < 5, "five hanging sends take the deadline, not five times the hang"
        assert wait_for(lambda: sorted(tried) == sorted(ids[:5])) and not lab.bridge.waiting
        assert any("not out in" in line for line in lab.log) and not any("x" == line for line in lab.log)
    finally:
        hang.set()


def test_a_job_end_starts_the_next_line_through_the_kits_hook(lab, planner):  # noqa: F811
    assert "job_ended" in vars(bridge.Bridge) and "_run_job" not in vars(bridge.Bridge) and "end_runs" not in vars(bridge.Bridge)
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, "second")
    planner.gate(0).set()
    assert settle(lab) and planner.texts() == ["first", "second"]


def polled(lab, monkeypatch, polls=3):  # noqa: F811
    """The `timeout` of each receive of a polling loop that ends after `polls` of them."""
    timeouts, stop = [], threading.Event()

    def receive(offset, timeout):
        timeouts.append(timeout)
        if len(timeouts) >= polls:
            stop.set()
        return {"updates": [], "next_offset": offset}
    monkeypatch.setattr(lab.bridge.messenger, "receive", receive)
    lab.bridge.serve_loop(stop, 60, 25)
    lab.bridge.stopping.clear()
    return timeouts


def test_a_polling_loop_looks_again_soon_only_while_a_line_waits_out_a_router_pause(lab, planner, monkeypatch):  # noqa: F811
    two(lab)
    clocked(lab)
    project = lab.bridge.projects[0]
    lab.bridge.exclusive[project["id"]] = "job x"            # the slot is held by something that ends on its own: its end drains
    assert lab.bridge.keep(project, STAFF, "held")
    assert polled(lab, monkeypatch) == [25, 25, 25], "a held slot is looked at when its job ends, not by shortening the poll"
    assert lab.bridge.keep(project, STAFF, "paused", retry=True)
    assert max(polled(lab, monkeypatch)) <= bridge.QUEUE_POLL, "a pause of the router has no job to end it: look again soon"
    del lab.bridge.exclusive[project["id"]]


class Session:
    """A listen session the test drives: ready or not, and a count of the loop's iterations."""
    fatal, generation = None, 0

    def __init__(self, ready):
        self.ready, self.polls, self.stop = ready, 0, threading.Event()

    def is_ready(self):
        return self.ready

    def take_unread(self):
        return 0

    def next_update(self, wait):
        self.polls += 1
        self.stop.wait(min(wait, 0.02))
        return None


def test_a_listen_provider_that_is_not_ready_starts_no_line_and_the_line_runs_when_it_is(lab, planner):  # noqa: F811
    two(lab)
    session = Session(ready=False)
    assert lab.bridge.keep(lab.bridge.projects[0], OWNER, "wait for the provider")
    runner = threading.Thread(target=lab.bridge.listen_loop, args=(session.stop, 60, session, 1), daemon=True)
    runner.start()
    try:
        assert wait_for(lambda: session.polls >= 5)
        assert planner.texts() == [] and len(lab.bridge.waiting) == 1
        session.ready = True
        assert wait_for(lambda: "Answer 0" in lab.texts(OWNER))
        assert planner.texts() == ["wait for the provider"]
    finally:
        session.stop.set()
        runner.join(WAIT)


def test_an_expired_line_is_dropped_even_while_the_provider_is_not_ready(lab, planner):  # noqa: F811
    two(lab)
    now = clocked(lab)
    session = Session(ready=False)
    assert lab.bridge.keep(lab.bridge.projects[0], OWNER, "too late")
    now[0] += bridge.QUEUE_WAIT
    runner = threading.Thread(target=lab.bridge.listen_loop, args=(session.stop, 60, session, 1), daemon=True)
    runner.start()
    try:
        assert wait_for(lambda: bridge.QUEUE_EXPIRED in lab.texts(OWNER))
    finally:
        session.stop.set()
        runner.join(WAIT)
    assert planner.texts() == []


def test_a_project_that_became_unaccepted_while_a_line_waits_drops_it_with_no_reply(lab, planner):  # noqa: F811
    two(lab)
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(WAIT)
    lab.say(STAFF, LINE)
    write_config(lab.path, channels={"messaging": "owner"})        # a changed file that nobody accepted
    planner.gate(0).set()
    assert settle(lab)
    assert planner.texts() == ["first"] and lab.texts(STAFF) == [bridge.QUEUED] and bridge.DROPPED in lab.log


def test_a_second_line_of_a_chat_that_waits_out_a_router_pause_gets_the_routers_sentence(lab, planner):  # noqa: F811
    two(lab)
    planner.refusals = 1
    lab.say(OWNER, "x")
    assert wait_for(lambda: lab.texts(OWNER) == [bridge.QUEUED])
    assert settle(lab)
    lab.say(OWNER, "x again")
    assert lab.texts(OWNER) == [bridge.QUEUED, bridge.RUN_BUSY], "the slot is free: the sentence that fits is the router's"
