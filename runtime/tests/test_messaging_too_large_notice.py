"""A message too large for the channel reaches the person (AT2b): the error-event kind `too-large` of runtime/messaging_provider.py (counted by the
listen session apart from `skipped`, never stored), and the bridge's notice (runtime/messaging_bridge.py, `Bridge.notify_unread`): one fixed sentence of
its own to the senders the "N more waiting" line goes to, at most once an hour to a chat, counted apart from the skipped kind, never the provider's
reason. Offline, no model; invented ids.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_too_large_notice.py
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

import phrase_kit as pk
import phrases
import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_skip_notice import POLICIES, REASON, event, four  # noqa: F401
from test_sender_profiles import OWNER, STAFF, accept
from test_sender_profiles_bridge import CLERK, OTHER, configure, lab  # noqa: F401  (the lab fixture)

bridge = st.load("messaging_bridge")
providers = st.load("messaging_provider")


def large_texts(lab, chat):  # noqa: F811
    return [t for t in lab.texts(chat) if pk.said(t, "TOO_LARGE_ONE") or pk.said(t, "TOO_LARGE_MANY")]


def unread_texts(lab, chat):  # noqa: F811
    return [t for t in lab.texts(chat) if pk.said(t, "UNREAD_ONE") or pk.said(t, "UNREAD_MANY")]


def give_large(lab, *counts):  # noqa: F811
    left = list(counts)
    lab.bridge.messenger.take_too_large = lambda: left.pop(0) if left else 0


def give_skipped(lab, *counts):  # noqa: F811
    left = list(counts)
    lab.bridge.messenger.take_unread = lambda: left.pop(0) if left else 0


# --- 1. the session ------------------------------------------------------------------------------------------------------------------------


def test_too_large_is_an_error_kind_counted_apart_from_skipped_and_it_never_stops_the_session():
    assert "too-large" in providers.ERROR_KINDS and "too-large" not in providers.ANSWER_KINDS
    logged = []
    session = providers.ListenSession(None, "chirp", None, None, log=logged.append)
    run = providers.Run(None)
    session.take(run, event("paused", "the session is gone"))
    session.take(run, event("too-large", REASON))
    assert (run.kind, run.reason) == ("paused", "the session is gone"), "a too-large event is not the state of the run"
    assert session.take_too_large() == 1 and session.take_too_large() == 0 and session.take_unread() == 0
    session.take(run, event("skipped"))
    session.take(run, event("too-large"))
    session.take(run, event("too-large"))
    assert session.take_unread() == 1 and session.take_too_large() == 2
    joined = " ".join(logged)
    assert "too-large" in joined and "905318264170" not in joined and "qzxw" not in joined and "/Users/someone" not in joined
    assert session.fatal is None


def test_a_burst_of_too_large_events_is_one_log_line_until_the_count_is_taken():
    logged = []
    session = providers.ListenSession(None, "chirp", None, None, log=logged.append)
    run = providers.Run(None)
    for _ in range(50):
        session.take(run, event("too-large"))
    assert len([line for line in logged if "too-large" in line]) == 1 and session.take_too_large() == 50
    session.take(run, event("too-large"))
    assert len([line for line in logged if "too-large" in line]) == 2 and session.take_too_large() == 1


def test_a_messenger_that_polls_has_nothing_too_large():
    messenger = providers.Messenger("chirp", root=str(st.REPO))
    assert messenger.session is None and messenger.take_too_large() == 0


# --- 2. the bridge: who is told, and how often ---------------------------------------------------------------------------------------------


def test_the_senders_who_hear_the_count_are_told_once_and_the_others_are_not(lab):  # noqa: F811
    four(lab)
    give_large(lab, 1)
    lab.bridge.tick()
    assert large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE]
    assert large_texts(lab, STAFF) == [bridge.TOO_LARGE_ONE]
    assert large_texts(lab, CLERK) == [] and large_texts(lab, OTHER) == []
    assert unread_texts(lab, OWNER) == [], "it is not the skipped sentence"
    lab.bridge.tick()
    assert large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE], "the count was cleared: not told again"


def test_several_in_the_hour_go_as_one_line_with_the_count(lab, monkeypatch):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    now = [1000.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: now[0])
    give_large(lab, 1, 1, 2)
    lab.bridge.notify_unread()
    assert large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE]
    now[0] += bridge.UNREAD_EVERY - 1
    lab.bridge.notify_unread()
    lab.bridge.notify_unread()
    assert large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE], "inside the hour nothing more goes"
    now[0] += 2
    lab.bridge.notify_unread()
    assert large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE, bridge.TOO_LARGE_MANY.format(n=3)]


def test_skipped_and_too_large_in_one_tick_are_two_lines_one_of_each(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    give_skipped(lab, 1)
    give_large(lab, 1)
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE] and large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE]


def test_the_hourly_cap_of_one_kind_does_not_hold_back_the_other(lab, monkeypatch):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    now = [1000.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: now[0])
    give_skipped(lab, 1)
    give_large(lab, 0, 1)
    lab.bridge.notify_unread()
    assert unread_texts(lab, OWNER) == [bridge.UNREAD_ONE] and large_texts(lab, OWNER) == []
    now[0] += 10
    lab.bridge.notify_unread()
    assert large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE], "the skipped line of ten seconds ago does not hold it"


@pytest.mark.parametrize("made", ["removed", "muted", "actionable"])
def test_a_sender_the_policy_has_closed_is_never_told_and_loses_the_count(lab, made):  # noqa: F811
    wanted = {"removed": [{"id": OWNER, "policy": "owner"}],
              "muted": [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "mute"}],
              "actionable": [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "watcher"}]}[made]
    configure(lab, [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}], policies=POLICIES)
    answers = [None, None]
    real = lab.bridge.reply
    lab.bridge.reply = lambda chat, text: answers.pop(0) if answers else real(chat, text)      # both lines are deferred: the counts wait
    give_large(lab, 1)
    lab.bridge.notify_unread()
    assert lab.bridge.too_large_waiting == {OWNER: 1, STAFF: 1}
    configure(lab, wanted, policies=POLICIES)
    lab.bridge.notify_unread()
    assert large_texts(lab, STAFF) == [] and STAFF not in lab.bridge.too_large_waiting
    assert large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE]


def test_a_deferred_line_is_tried_at_the_next_tick_and_a_failed_one_an_hour_later(lab, monkeypatch):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    now = [1000.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: now[0])
    answers = [None]
    real = lab.bridge.reply
    lab.bridge.reply = lambda chat, text: answers.pop(0) if answers else real(chat, text)
    give_large(lab, 1)
    lab.bridge.notify_unread()
    assert lab.bridge.too_large_waiting == {OWNER: 1} and OWNER not in lab.bridge.too_large_told
    lab.bridge.notify_unread()
    assert large_texts(lab, OWNER) == [bridge.TOO_LARGE_ONE] and lab.bridge.too_large_waiting == {}
    calls = []
    lab.bridge.reply = lambda chat, text: calls.append(text) or False
    give_large(lab, 1)
    now[0] += bridge.UNREAD_EVERY + 1
    for _ in range(3):
        lab.bridge.notify_unread()
    assert len(calls) == 1 and lab.bridge.too_large_waiting == {OWNER: 1}
    now[0] += bridge.UNREAD_EVERY + 1
    lab.bridge.notify_unread()
    assert len(calls) == 2


def test_the_count_is_taken_only_after_the_hearers_are_read(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    taken = []
    lab.bridge.messenger.take_too_large = lambda: taken.append(1) or 1

    def broken():
        raise RuntimeError("the settings could not be read")
    lab.bridge.hearers = broken
    with pytest.raises(RuntimeError):
        lab.bridge.notify_unread()
    assert taken == []


def test_a_pt_br_project_is_told_in_portuguese(lab):  # noqa: F811
    accept(lab.path, policies=POLICIES, channels={"messaging": "staff"}, language="pt-BR",
           messaging={"senders": {"telegram": [{"id": OWNER, "policy": "owner"}]}, "notices": "text"})
    give_large(lab, 1, 1, 1)
    lab.bridge.notify_unread()
    assert lab.texts(OWNER)[-1] == phrases.text("TOO_LARGE_ONE", {"language": "pt-BR"})
    assert pk.said(lab.texts(OWNER)[-1], "TOO_LARGE_ONE", {"language": "pt-BR"}) and not pk.said(lab.texts(OWNER)[-1], "TOO_LARGE_ONE")


def test_nothing_of_the_providers_words_is_sent(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    session = providers.ListenSession(None, "chirp", None, None, log=lambda text: None)
    session.take(providers.Run(None), event("too-large"))
    lab.bridge.messenger.take_too_large = session.take_too_large
    lab.bridge.notify_unread()
    sent = " ".join(large_texts(lab, OWNER))
    assert bridge.TOO_LARGE_ONE in sent
    for planted in ("905318264170", "qzxw", "mail.example", "/Users/someone", "uid"):
        assert planted not in sent and planted not in bridge.TOO_LARGE_MANY.format(n=3)


# --- 3. the sentences are tied to the provider's limit --------------------------------------------------------------------------------------


def test_the_sentences_name_the_limit_of_the_provider_and_the_size_of_a_file_that_fits():
    caps = json.loads(subprocess.run(
        [sys.executable, str(st.REPO / "providers" / "messenger" / "email-imap.py"), "capabilities", "--platform", "email"],
        capture_output=True, text=True, timeout=30).stdout)
    limit = caps["max_attachment_bytes"]
    assert limit == 1048576, "the limit changed: change TOO_LARGE_ONE and TOO_LARGE_MANY (en and pt-BR) with it, then this number"
    file_kb = limit * 3 // 4 // 1000 // 100 * 100      # base64 makes a file a third larger; rounded down to 100 KB
    assert file_kb == 700
    for lang in ("en", "pt-BR"):
        for key in ("TOO_LARGE_ONE", "TOO_LARGE_MANY"):
            text = phrases.text(key, {"language": lang}, n=2)
            assert "1 MB" in text and f"{file_kb} KB" in text, (lang, key)
            assert ("in all" if lang == "en" else "no total") in text, "the limit is that of the whole message, not of each file"
