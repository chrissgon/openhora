"""A message the provider gave up reaches the person (F2-A): the error-event kind `skipped` of runtime/messaging_provider.py (counted by the
listen session, never stored), and the bridge's notice (runtime/messaging_bridge.py, `Bridge.notify_unread`): one fixed sentence to the senders
the "N more waiting" line goes to, at most once an hour to a chat, never the provider's reason. Offline, no model; invented ids.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_skip_notice.py
"""
from __future__ import annotations

import time

import pytest

import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging import wait_for
from test_messaging_listen import rig  # noqa: F401  (the listen rig fixture)
from test_sender_profiles import OWNER, STAFF
from test_sender_profiles_bridge import CLERK, OTHER, POLICIES_ALL, configure, lab  # noqa: F401  (the lab fixture)

bridge = st.load("messaging_bridge")
providers = st.load("messaging_provider")

REASON = "uid 905318264170 <qzxw@mail.example> could not be read at /Users/someone/Mail/x"
POLICIES = {**POLICIES_ALL, "mute": ["talk"]}


def event(kind="skipped", reason=REASON) -> bytes:
    return ('{"event": "error", "kind": "%s", "reason": "%s"}' % (kind, reason)).encode()


def four(lab):  # noqa: F811
    """The owner (reads), the employee (reads what a limited reader may), a profile that is sent only what it can act on, and one that cannot read."""
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}, {"id": CLERK, "policy": "watcher"},
                    {"id": OTHER, "policy": "mute"}], policies=POLICIES)


def unread_texts(lab, chat):  # noqa: F811
    return [t for t in lab.texts(chat) if "could not be read and" in t]


def give(lab, *counts):  # noqa: F811
    """The messenger reports these counts at its next calls to take_unread, then 0."""
    left = list(counts)
    lab.bridge.messenger.take_unread = lambda: left.pop(0) if left else 0


# --- 1. the provider side: a skipped event is counted and is not the state of the run --------------------------------------------------


def test_skipped_is_an_error_kind_that_is_counted_once_each_and_leaves_the_run_as_it_was():
    assert "skipped" in providers.ERROR_KINDS and "skipped" not in providers.ANSWER_KINDS
    logged = []
    session = providers.ListenSession(None, "chirp", None, None, log=logged.append)
    run = providers.Run(None)
    session.take(run, event("paused", "the session is gone"))
    assert (run.kind, run.reason) == ("paused", "the session is gone")
    session.take(run, event())
    assert (run.kind, run.reason) == ("paused", "the session is gone"), "a skip is not the state of the run: an exit after it keeps its own reason"
    assert session.take_unread() == 1 and session.take_unread() == 0
    session.take(run, event())
    session.take(run, event())
    assert session.take_unread() == 2
    joined = " ".join(logged)
    assert "skipped" in joined and "905318264170" not in joined and "qzxw" not in joined and "/Users/someone" not in joined and "could not be read at" not in joined


def test_a_burst_of_skipped_events_is_one_log_line_until_the_count_is_taken():
    logged = []
    session = providers.ListenSession(None, "chirp", None, None, log=logged.append)
    run = providers.Run(None)
    for _ in range(200):
        session.take(run, event())
    assert len([line for line in logged if "skipped" in line]) == 1 and session.take_unread() == 200
    session.take(run, event())
    assert len([line for line in logged if "skipped" in line]) == 2 and session.take_unread() == 1


def test_a_failed_event_does_not_count_so_a_discord_retry_never_becomes_a_notice():
    session = providers.ListenSession(None, "chirp", None, None, log=lambda text: None)
    run = providers.Run(None)
    for kind in ("failed", "usage", "not-configured", "something-new"):
        session.take(run, event(kind, "a retry"))
    assert session.take_unread() == 0 and run.kind == "other"


def test_a_messenger_that_polls_has_nothing_unread():
    messenger = providers.Messenger("chirp", root=str(st.REPO))
    assert messenger.session is None and messenger.take_unread() == 0


# --- 2. the bridge: who is told ----------------------------------------------------------------------------------------------------------


def test_the_senders_the_more_line_goes_to_are_told_once_and_the_others_are_not(lab):  # noqa: F811
    four(lab)
    give(lab, 1)
    lab.bridge.tick()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE], "a full reader is told"
    assert unread_texts(lab, STAFF) == [bridge.UNREAD_ONE], "a read-limited profile is told: the lost message may be theirs"
    assert unread_texts(lab, CLERK) == [], "a profile sent only what it can act on is not told"
    assert unread_texts(lab, OTHER) == [], "a profile that cannot read is not told"
    lab.bridge.tick()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE], "the count was cleared: not told again"


def test_the_default_policy_tells_a_listed_sender_with_no_profile(lab):  # noqa: F811
    configure(lab, [OWNER], policies=POLICIES, channel=None)
    give(lab, 1)
    lab.bridge.tick()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE]


def test_a_chat_listed_in_two_served_projects_gets_one_line(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    lab.bridge.projects = [lab.bridge.projects[0], {**lab.bridge.projects[0], "id": "second", "name": "second-shop"}]
    give(lab, 1)
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE]


def test_a_sender_added_after_a_skip_is_not_told_of_it(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    give(lab, 1)
    answers = [None]
    real = lab.bridge.reply
    lab.bridge.reply = lambda chat, text: answers.pop(0) if answers else real(chat, text)      # the first line is deferred: the count waits
    lab.bridge.notify_unread()
    assert lab.bridge.unread_waiting == {OWNER: 1}
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}])
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE] and unread_texts(lab, STAFF) == []


# --- 3. the bridge: how often ------------------------------------------------------------------------------------------------------------


def test_a_second_skip_within_the_hour_waits_and_goes_as_one_line_with_the_count(lab, monkeypatch):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    now = [1000.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: now[0])
    give(lab, 1, 1, 1)
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE]
    now[0] += bridge.UNREAD_EVERY - 1
    lab.bridge.notify_unread()
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE], "two more skips inside the hour send nothing yet"
    now[0] += 2
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE, bridge.UNREAD_MANY.format(n=2)]
    now[0] += 5 * bridge.UNREAD_EVERY
    lab.bridge.notify_unread()
    assert len(unread_texts(lab, OWNER)) == 2, "nothing waits: nothing is sent"


# --- 4. the bridge: a deferred and a failed send -----------------------------------------------------------------------------------------


def test_a_deferred_line_keeps_its_count_and_the_next_tick_sends_it(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    answers = [None]
    real = lab.bridge.reply
    lab.bridge.reply = lambda chat, text: answers.pop(0) if answers else real(chat, text)
    give(lab, 1)
    lab.bridge.notify_unread()
    assert lab.bridge.unread_waiting == {OWNER: 1} and OWNER not in lab.bridge.unread_told and unread_texts(lab, OWNER) == []
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE] and lab.bridge.unread_waiting == {}


def test_a_failed_send_keeps_the_count_and_is_tried_again_an_hour_later_never_at_every_tick(lab, monkeypatch):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    now = [1000.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: now[0])
    calls = []
    lab.bridge.reply = lambda chat, text: calls.append(text) or False
    give(lab, 1)
    for _ in range(3):
        lab.bridge.notify_unread()
    assert len(calls) == 1 and lab.bridge.unread_waiting == {OWNER: 1} and lab.bridge.unread_told[OWNER] == 1000.0
    now[0] += bridge.UNREAD_EVERY + 1
    lab.bridge.notify_unread()
    assert len(calls) == 2, "an hour later it is tried once more, with the count it kept"
    del lab.bridge.reply
    now[0] += bridge.UNREAD_EVERY + 1
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE] and lab.bridge.unread_waiting == {}


# --- 4b. the policy is read again when the line goes out -----------------------------------------------------------------------------------


def staff_removed(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}], policies=POLICIES)


def staff_muted(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "mute"}], policies=POLICIES)


def staff_actionable(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "watcher"}], policies=POLICIES)


@pytest.mark.parametrize("narrow", [staff_removed, staff_muted, staff_actionable], ids=["removed", "muted", "actionable"])
def test_a_line_held_back_for_the_hour_is_not_sent_to_a_sender_the_policy_has_since_closed(lab, monkeypatch, narrow):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}], policies=POLICIES)
    now = [1000.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: now[0])
    give(lab, 1, 1)
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE] and unread_texts(lab, STAFF) == [bridge.UNREAD_ONE]
    lab.bridge.notify_unread()      # the second skip is taken now and waits for the hour
    assert lab.bridge.unread_waiting == {OWNER: 1, STAFF: 1}
    narrow(lab)
    now[0] += bridge.UNREAD_EVERY + 1
    lab.bridge.notify_unread()
    assert unread_texts(lab, STAFF) == [bridge.UNREAD_ONE], "nothing more to the sender the policy closed"
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE, bridge.UNREAD_ONE]
    assert STAFF not in lab.bridge.unread_waiting


def test_the_count_is_taken_only_after_the_hearers_are_read(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    taken = []
    lab.bridge.messenger.take_unread = lambda: taken.append(1) or 1

    def broken():
        raise RuntimeError("the settings could not be read")
    lab.bridge.hearers = broken
    with pytest.raises(RuntimeError):
        lab.bridge.notify_unread()
    assert taken == [], "an error while reading the hearers loses no count"


# --- 5. nothing of the provider's words is sent ------------------------------------------------------------------------------------------


def test_the_sentence_is_the_bridges_own_and_holds_nothing_the_provider_said(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    session = providers.ListenSession(None, "chirp", None, None, log=lambda text: None)
    session.take(providers.Run(None), event())
    lab.bridge.messenger.take_unread = session.take_unread
    lab.bridge.tick()
    # the tick also sends the owner the cards of the open decisions, which carry sha256 digests, so the planted words are looked for in
    # the notice lines alone, which are the bridge's sentence under test
    sent = " ".join(unread_texts(lab, OWNER))
    assert bridge.UNREAD_ONE in sent
    for planted in ("905318264170", "qzxw", "mail.example", "/Users/someone", "uid"):
        assert planted not in sent and planted not in bridge.UNREAD_MANY.format(n=3)


# --- 6. a provider that is polled sends nothing new ----------------------------------------------------------------------------------------


def test_a_bridge_over_a_polled_provider_sends_no_unread_line(lab):  # noqa: F811
    four(lab)
    lab.bridge.tick()
    lab.bridge.tick()
    assert lab.bridge.messenger.session is None
    assert not [t for t in lab.texts() if "could not be read" in t]
    assert lab.bridge.unread_waiting == {}


# --- 7. end to end over a listen provider -------------------------------------------------------------------------------------------------


def test_a_skipped_event_after_ready_makes_one_notice_to_a_listed_sender_and_the_bridge_keeps_running(rig):  # noqa: F811
    r = rig(script={"default": {"skipped_after_ready": 1}})
    r.run(notice_every=0.1)
    assert wait_for(lambda: bridge.UNREAD_ONE in r.texts())
    time.sleep(0.5)      # a few more notice periods: the hour has not passed
    assert r.texts().count(bridge.UNREAD_ONE) == 1 and len(r.starts()) == 1
    assert r.sent()[0]["chat"] == "830461975213" and r.error == [] and r.thread.is_alive()
    joined = " ".join(r.texts() + r.log)
    for planted in ("905318264170", "qzxw", "mail.example", "/Users/someone"):
        assert planted not in joined
    r.finish()
