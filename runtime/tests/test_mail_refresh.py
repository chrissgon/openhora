"""The platform reads a stale mail snapshot again, once, for the line that needs it (package BL5E, runtime/mail_refresh.py, SPEC-BLITE-5E-MAIL-REFRESH, limits L52 and L53).

The live case (2026-10-25, a pt-BR project, Telegram): "apague o e-mail do github" was answered "De qual caixa?", then "1", then "the newest snapshot of the mailbox is more
than 26 hours old: refresh it and ask again". The person's words: the platform refreshes the mailbox itself; it does not wait for the person to do it in the terminal. The guard
here is what keeps that read from becoming a hole: never twice in one line, never for a sender without the right to read the mailbox, never for a line that names a message
number or a written reference (a refresh renumbers the snapshot), never from the terminal, the page or the conversation, never on stale data when it fails, one source at a time,
the provider bounded, and nothing of a provider's words in a reply, the console or the draft.

Held here over the REAL operations layer and the REAL snapshots of two mail sources, `inbox` (Gmail) and `work` (Outlook), of the mailbox world of test_mailbox_write.py (the real
writers over stand-ins on loopback, a stand-in reader that records every call), the real family (`ops_natural_mail.resolve`, `ops_natural_writes.natural_write`) and the real right
to read (`item_refs.may_read`), with a clock that the test moves. No provider is called (every read is the stand-in's, every write is a stand-in's on loopback), no model is called,
no credential is read; every name is invented, every address is on a `.example` name. The count of provider reads is the stand-in's own list of calls, and every oracle that counts
has a vacuity case that fails on a planted wrong result (as test_phone_card_targets.py does).
Wording is compared with the phrase table by key (T8), with the Portuguese literals of the maintainer's words only where the person's sentence is the case.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_refresh.py   (also on Python 3.9)
"""
from __future__ import annotations

import datetime
import json
import threading
import time

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_mailbox_write import world as mailbox_world  # noqa: F401  (the mailbox world: a fixture of its own name here)
from test_ops_natural_writes import PLAIN, READER, SENDER, policy  # noqa: F401  (READER holds ask-mail and mail-organize; SENDER holds mail-organize only)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_sources = st.load("ops_sources")
ops_items = st.load("ops_items")
onm = st.load("ops_natural_mail")
onw = st.load("ops_natural_writes")
item_refs = st.load("item_refs")
mail_refresh = st.load("mail_refresh")
mail_refs = st.load("mail_refs")
phrases = st.load("phrases")
sources = st.load("sources")
sources_mail = st.load("sources_mail")
drafts = st.load("drafts")

LINE = "apague o e-mail da Ana"      # the words of the retest of 2026-10-25, over the stand-in mailbox whose first message is from Ana
PLANTED = "PLANTED-PROVIDER-TEXT-7731"
ANA = "ana@clinic.example"


class Wall:
    """The monotonic clock of the cooldown, moved by the test."""

    def __init__(self, monkeypatch, start=1000.0):
        self.now = start
        monkeypatch.setattr(mail_refresh, "MONOTONIC", lambda: self.now)


@pytest.fixture
def world(mailbox_world, monkeypatch):
    """The mailbox world, with a clock the test moves (`stale`): the snapshots are read at the real time, and a source is stale when the clock is moved 27 hours."""
    shift = {"by": datetime.timedelta(0)}

    def moved():
        return datetime.datetime.now(datetime.timezone.utc) + shift["by"]
    monkeypatch.setattr(sources_mail, "CLOCK", moved)
    original = sources.snapshot_age
    monkeypatch.setattr(sources, "snapshot_age", lambda stamp, clock=None: original(stamp, clock or moved))
    path = mailbox_world["path"]
    drafts.clear()
    mail_refresh.forget()
    policy({"path": path})
    del mailbox_world["readers"].calls[:]
    yield {**mailbox_world, "shift": shift}
    drafts.clear()
    mail_refresh.forget()


def reads(world, implementation=None):
    """The reads of a mailbox the stand-in provider has answered so far: the test's own count of the verbs it was sent."""
    return [c for c in world["readers"].calls if c["cls"] == "reader:email" and implementation in (None, c["implementation"])]


def stale(world, hours=27):
    world["shift"]["by"] += datetime.timedelta(hours=hours)


def newest(world, source_id):
    """When the newest snapshot of a source was read, as the store records it."""
    ctx = ops_core.context(world["path"])
    return ctx["store"].source_latest(ctx["conn"], source_id)["imported_at"]


def cards(world):
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_list(ctx["conn"], "open")


def resolve(world, op="mail-trash", sender=READER, channel="messaging", **slots):
    """What the mail family resolves for a line: the arguments, a question or a sentence. `source` is the person's answer to "De qual caixa?"."""
    ctx = ops_core.context(world["path"])
    return onm.resolve(ctx, op, {"words": ["ana"], "source": "inbox", **slots}, channel, sender)


def said(out):
    assert "say" in out, out
    return out["say"]["sentence_key"]


def set_language(world, tag):
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw["language"] = tag
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def phone_problems(reply):
    """What a phone must never be told: a command, a path, a file name or a flag (limit L62)."""
    return [w for w in ("source-mail", "source-calendar", "--origin", "--source", "cli.py", ".py", "/", "uv run", "python") if w in reply]


def words_seed(op="mail-trash", target="e-mail da Ana"):
    return onm.mail_target_seed(op, {"op": op, "spans": {"target": target}, "args": {}})


def phone(world, line, seed=None, sender=READER):
    return onw.natural_write(world["path"], line, channel="messaging", sender=sender, seed=seed)


def counter(monkeypatch, does=None, through=False):
    """`ops_sources.source_refresh` replaced by a stand-in that counts its calls (the keyword arguments too) and does `does` instead of reading, or, with `through`, makes the real
    read (so that the snapshot is fresh afterwards); with neither it reads nothing and the snapshot stays as it was."""
    seen = []
    real = ops_sources.source_refresh

    def stand_in(project, source_id, file=None, timeout=None):
        seen.append({"source": source_id, "timeout": timeout})
        if through:
            return real(project, source_id, file, timeout)
        return does(project, source_id, file, timeout) if does else {"refreshed": False}
    monkeypatch.setattr(ops_sources, "source_refresh", stand_in)
    return seen, real


# --- (a) the retest ------------------------------------------------------------------------------------------------------------------------------


def test_limit_52_a_stale_gmail_is_read_once_by_the_platform_and_the_line_ends_in_the_card_of_the_message(world):
    old = newest(world, "inbox")
    stale(world)
    first = phone(world, LINE, words_seed())
    assert first["asked"] and "inbox" in first["reply"] and "work" in first["reply"], "the question that opened the retest"
    assert reads(world) == [], "the question reads nothing"
    done = phone(world, "1")
    assert len(reads(world, "gmail")) == 1 and reads(world, "outlook") == [], "one Gmail read, no Outlook read"
    call = reads(world)[0]
    assert call["verb"] == "search" and call["args"][call["args"].index("--query") + 1] == "in:inbox" and call["args"][call["args"].index("--limit") + 1] == "50"
    assert "--own-words" in call["args"] and not [a for a in call["args"] if "ana" in a.lower()], "the origin's arguments: nothing of the line reaches the provider"
    assert "resend" in done and done["resend"], "the card is opened"
    body = cards(world)[0]["body"]
    assert "Account: google" in body and ANA in body and "bob@shop.example" not in body and "ACCT_MAIL_REF_STALE" not in done["reply"]
    assert newest(world, "inbox") != old and f"Chosen from a snapshot read at {newest(world, 'inbox')}." in body, "the card is made from the snapshot the platform just read"
    assert len(cards(world)) == 1
    # vacuity: the snapshot is fresh now, so the same line reads nothing and opens the same card (the count sees reads only when they happen)
    again = phone(world, LINE, words_seed(op="mail-trash"))
    again = phone(world, "1") if again["asked"] else again
    assert len(reads(world)) == 1, "a fresh snapshot: still the one read of before"
    assert "resend" in again and ANA in cards(world)[-1]["body"] and len(cards(world)) == 2


def test_the_line_reads_the_outlook_source_when_it_is_the_one_the_person_chose_and_never_the_other_one(world):
    stale(world)
    phone(world, LINE, words_seed())
    done = phone(world, "2")
    assert len(reads(world, "outlook")) == 1 and reads(world, "gmail") == [], "(h) only the source the line needs"
    body = cards(world)[0]["body"]
    assert "resend" in done and "Account: microsoft" in body and ANA in body


def test_the_oracle_that_counts_reads_sees_a_read_when_there_is_one(world):
    stale(world)
    assert reads(world) == []
    out = resolve(world)
    assert reads(world) != [] and "args" in out, "a counter that always said zero would pass every test below: this one sees the read"


# --- (b) never twice in one line --------------------------------------------------------------------------------------------------------------


def double_attempt(world, monkeypatch):
    """A refresh that 'succeeds' and leaves the snapshot stale, and a resolution that asks for the snapshot twice, 200 seconds apart (so that the rest after a failure, 120 seconds,
    is over and only the budget of the line stops the second read). Returns (the calls of the refresh, the reply)."""
    stale(world)
    wall = Wall(monkeypatch)
    seen, _ = counter(monkeypatch)
    real = onm._by_words

    def twice(ctx, slots, source_id, channel, sender):
        try:
            onm._read_snapshot(ctx, source_id, channel, sender, True)
        except onm.Say:
            pass
        wall.now += 200
        return real(ctx, slots, source_id, channel, sender)
    monkeypatch.setattr(onm, "_by_words", twice)
    return seen, resolve(world)


def test_a_refresh_that_leaves_the_snapshot_stale_runs_once_and_says_so_and_a_second_attempt_in_the_same_line_does_not_read_again(world, monkeypatch):
    seen, out = double_attempt(world, monkeypatch)
    assert said(out) == "NW_MAIL_REFRESH_FAILED" and out["say"]["fields"] == {"source": "inbox"}
    assert len(seen) == 1, "one provider read for the line, whatever the number of attempts inside it"
    assert cards(world) == [] and reads(world) == []


def test_the_budget_is_gone_for_a_line_that_asks_twice_so_a_budget_that_returned_would_read_twice_and_the_oracle_would_fail(world, monkeypatch):
    real_once = mail_refresh.refresh_once

    def fresh_budget_each_time(*args):      # the planted fault: every call is given a new turn
        mail_refresh._LOCAL.budget = None
        with mail_refresh.turn():
            return real_once(*args)
    monkeypatch.setattr(mail_refresh, "refresh_once", fresh_budget_each_time)
    seen, _ = double_attempt(world, monkeypatch)
    assert len(seen) == 2, "the probe sees it: with a fresh budget on each call the stand-in is called twice"
    with pytest.raises(AssertionError):
        assert len(seen) == 1


def test_each_resolution_opens_its_own_turn_and_the_budget_is_cleared_when_it_ends(world, monkeypatch):
    seen, _ = counter(monkeypatch, through=True)
    stale(world)
    resolve(world)
    stale(world)
    resolve(world)
    assert len(seen) == 2, "two lines, two turns: one read each (the rest is for a failed read only)"
    assert getattr(mail_refresh._LOCAL, "budget", None) is None, "nothing is left open on the thread"


def test_nothing_is_read_outside_a_turn_and_an_inner_turn_shares_the_outer_budget(world, monkeypatch):
    seen, _ = counter(monkeypatch, through=True)
    stale(world)
    ctx = ops_core.context(world["path"])
    assert mail_refresh.refresh_once(ctx, "inbox", "messaging", READER) == "spent" and seen == [], "fail closed: no turn, no read"
    with mail_refresh.turn():
        with mail_refresh.turn():
            assert mail_refresh.refresh_once(ctx, "inbox", "messaging", READER) == "refreshed"
        assert mail_refresh.refresh_once(ctx, "inbox", "messaging", READER) == "spent", "the inner exit did not clear the budget of the outer turn"
    assert len(seen) == 1
    assert mail_refresh.refresh_once(ctx, "inbox", "messaging", READER) == "spent", "the outer exit cleared it"
    assert len(seen) == 1


# --- (c) never for a sender without the right to read ----------------------------------------------------------------------------------------------


def test_limit_52_a_sender_without_ask_mail_gets_the_sentence_of_the_right_and_the_mailbox_is_not_read(world):
    stale(world)
    for sender in (SENDER, PLAIN):
        out = resolve(world, sender=sender)
        assert said(out) == "ACCT_MAIL_REF_NOT_READABLE" and out["say"]["fields"] == {"ref": "your messages"}, sender
    assert reads(world) == [] and cards(world) == [], "no read, no card"


def test_refresh_once_refuses_a_caller_who_may_not_read_even_when_called_directly_and_a_reader_is_the_vacuity(world, monkeypatch):
    seen, _ = counter(monkeypatch, through=True)
    stale(world)
    ctx = ops_core.context(world["path"])
    with mail_refresh.turn():
        assert mail_refresh.refresh_once(ctx, "inbox", "messaging", SENDER) == "not-allowed"
    assert seen == []
    for sender in (None, "", "5151", "telegram:", ":5151", "telegram:9999", 5151):
        with mail_refresh.turn():
            assert mail_refresh.refresh_once(ctx, "inbox", "messaging", sender) == "not-allowed", repr(sender)
    for channel in (None, "", 0, "mcp"):
        with mail_refresh.turn():
            assert mail_refresh.refresh_once(ctx, "inbox", channel, READER) == "not-allowed", repr(channel)
    assert seen == [], "a sender that is not <platform>:<id>, an unlisted one and a channel that is not messaging read nothing"
    with mail_refresh.turn():
        assert mail_refresh.refresh_once(ctx, "inbox", "messaging", READER) == "refreshed"
    assert len(seen) == 1, "the vacuity: the reader of the same call does read"


def test_a_source_that_is_not_a_mail_source_or_is_not_registered_is_not_allowed_and_reads_nothing(world, monkeypatch):
    seen, _ = counter(monkeypatch)
    note = world["tmp"] / "notes.md"
    note.write_text("# Notes\n\nA line.\n")
    ops_sources.source_import(world["path"], "notes", file=str(note))
    ctx = ops_core.context(world["path"])
    with mail_refresh.turn():
        assert mail_refresh.refresh_once(ctx, "notes", "messaging", READER) == "not-allowed"
        assert mail_refresh.refresh_once(ctx, "nao-existe", "messaging", READER) == "not-allowed"
    assert seen == []


# --- (d) not on the terminal, the page or the conversation ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("channel,sender", [("chat", None), ("terminal", None), ("page", None)])
def test_the_terminal_the_page_and_the_conversation_keep_the_sentence_that_says_to_refresh_and_read_nothing(world, channel, sender):
    stale(world)
    out = resolve(world, channel=channel, sender=sender)
    assert said(out) == "ACCT_MAIL_REF_STALE" and "inbox" in out["say"]["fields"]["ref"]
    assert reads(world) == [] and cards(world) == []


def test_in_the_conversation_the_line_ends_in_the_old_sentence_with_the_id_and_no_read(world):
    stale(world)
    seed = words_seed()
    seed["slots"]["source"] = "inbox"      # the person's answer to "which mailbox?"
    reply = onw.natural_write(world["path"], LINE, channel="chat", sender=None, seed=seed)
    assert reply["reply"] == phrases.text("ACCT_MAIL_REF_STALE", {"language": "en"}, ref="inbox") and reads(world) == [] and cards(world) == []


# --- (e) not for a number or a written reference, nor for a message the person chose ----------------------------------------------------------------


@pytest.mark.parametrize("more", [{"numbers": [3]}, {"refs": ["inbox#3"]}, {"numbers": [1], "refs": ["inbox#2"]}])
def test_a_line_that_names_a_number_or_a_reference_with_words_never_refreshes(world, more):
    stale(world)
    out = resolve(world, **more)
    assert said(out) == "ACCT_MAIL_REF_STALE" and reads(world) == [] and cards(world) == [], "a refresh renumbers the snapshot: the number the person saw would name another message"


def test_a_reference_alone_is_passed_on_and_the_operation_itself_refuses_the_stale_snapshot_with_no_read(world):
    stale(world)
    out = resolve(world, words=[], refs=["inbox#3"], source=None)
    assert out == {"args": {"account": "google", "messages": "inbox#3"}}, "the family resolves no snapshot for a written reference"
    with pytest.raises(ops.OpsError) as refused:
        ops.mail_trash(world["path"], "google", "inbox#3", channel="messaging", sender=READER)
    assert "too old to name a message" in str(refused.value) and reads(world) == [] and cards(world) == []


def test_a_message_the_person_chose_from_a_list_is_never_looked_up_again_and_reads_nothing(world):
    stale(world)
    out = resolve(world, chosen="inbox#2")
    assert out == {"args": {"account": "google", "messages": "inbox#2"}} and reads(world) == []


def test_a_line_that_asks_for_the_newest_message_refreshes_once_and_a_number_with_it_does_not(world):
    stale(world)
    out = resolve(world, words=[], newest=True)
    assert out == {"args": {"account": "google", "messages": "inbox#1"}} and len(reads(world)) == 1
    stale(world)
    out = resolve(world, words=[], newest=True, numbers=[2])
    assert said(out) == "ACCT_MAIL_REF_STALE" and len(reads(world)) == 1, "the number forbids it: still the one read of before"


@pytest.mark.parametrize("code,refreshes", [("stale", True), ("no_version", True), ("no_index", True), ("integrity", False), ("not_readable", False), ("no_source", False),
                                            ("wrong_kind", False), ("not_snapshot", False)])
def test_only_a_refusal_that_a_read_cures_asks_for_a_refresh(world, monkeypatch, code, refreshes):
    asked = []
    monkeypatch.setattr(mail_refresh, "refresh_once", lambda ctx, source_id, channel, sender: (asked.append(source_id), "refreshed")[1])
    answers = [item_refs.ItemRefError(code, "x"), {"entries": [], "source": "inbox"}]

    def read_index(ctx, source_id, **kw):
        out = answers.pop(0) if answers else {"entries": []}
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(item_refs, "read_index", read_index)
    ctx = ops_core.context(world["path"])
    if refreshes:
        assert onm._read_snapshot(ctx, "inbox", "messaging", READER, True) == {"entries": [], "source": "inbox"} and asked == ["inbox"]
    else:
        with pytest.raises(onm.Say) as why:
            onm._read_snapshot(ctx, "inbox", "messaging", READER, True)
        assert why.value.key == mail_refs.REF_PHRASES[code] and asked == []
    asked.clear()
    answers[:] = [item_refs.ItemRefError(code, "x")]
    with pytest.raises(onm.Say):
        onm._read_snapshot(ctx, "inbox", "messaging", READER, False)
    assert asked == [], "may_refresh False: never"


def test_a_snapshot_still_refused_after_the_read_is_the_plain_failure_and_another_refusal_after_it_is_its_own_sentence(world, monkeypatch):
    monkeypatch.setattr(mail_refresh, "refresh_once", lambda *a: "refreshed")
    ctx = ops_core.context(world["path"])
    for second, key in (("stale", "NW_MAIL_REFRESH_FAILED"), ("no_index", "NW_MAIL_REFRESH_FAILED"), ("integrity", "ACCT_MAIL_REF_INTEGRITY")):
        answers = [item_refs.ItemRefError("stale", "x"), item_refs.ItemRefError(second, "x")]
        monkeypatch.setattr(item_refs, "read_index", lambda c, s, **kw: (_ for _ in ()).throw(answers.pop(0)))
        with pytest.raises(onm.Say) as why:
            onm._read_snapshot(ctx, "inbox", "messaging", READER, True)
        assert why.value.key == key, second


# --- (f) a failed refresh --------------------------------------------------------------------------------------------------------------------------


def test_a_failing_provider_gives_one_plain_sentence_in_portuguese_with_nothing_of_the_provider_and_one_closed_line_on_stderr(world, capsys):
    set_language(world, "pt-BR")
    stale(world)
    world["readers"].fail = tsm.Failure("unavailable", f"{PLANTED} in /home/pat/secret.py run uv run x --token abc")
    phone(world, LINE, words_seed())
    out = phone(world, "1")
    expected = phrases.text("NW_MAIL_REFRESH_FAILED", {"language": "pt-BR"}, source="inbox")
    assert out["reply"] == expected and expected.startswith("Não consegui atualizar o inbox agora")      # validate: allow english-only -- the Portuguese sentence under test
    assert PLANTED not in out["reply"] and phone_problems(out["reply"]) == []
    err = capsys.readouterr().err
    assert err.splitlines() == ["mail: refresh of inbox failed (mail)"] and PLANTED not in err and "secret" not in err
    assert "resend" not in out and cards(world) == [] and not out["asked"], "no card, no list, no pending decision, no question kept"
    assert len(reads(world)) == 1
    key = (ops_core.context(world["path"])["cfg"]["project"], "inbox")
    assert mail_refresh._lock_of(key).acquire(blocking=False), "the lock of the source is released after a failure"


def test_an_unknown_fault_is_printed_as_the_word_error_and_never_as_its_text(world, capsys, monkeypatch):
    def boom(project, source_id, file, timeout):
        raise RuntimeError(f"{PLANTED} in /etc/passwd")
    counter(monkeypatch, boom)
    stale(world)
    assert said(resolve(world)) == "NW_MAIL_REFRESH_FAILED"
    err = capsys.readouterr().err
    assert err.splitlines() == ["mail: refresh of inbox failed (error)"] and PLANTED not in err


def test_a_source_that_failed_is_not_tried_again_for_120_seconds_and_is_tried_after_that(world, monkeypatch, capsys):
    wall = Wall(monkeypatch)
    stale(world)
    world["readers"].fail = tsm.Failure("unavailable", PLANTED)
    assert said(resolve(world)) == "NW_MAIL_REFRESH_FAILED" and len(reads(world)) == 1
    wall.now += 100
    assert said(resolve(world)) == "NW_MAIL_REFRESH_FAILED" and len(reads(world)) == 1, "within 120 s: no further read, the same sentence"
    assert said(resolve(world, source="work")) == "NW_MAIL_REFRESH_FAILED" and len(reads(world)) == 2, "the cooldown is for the source that failed (the other one is a read of its own)"
    wall.now += 21
    world["readers"].fail = None
    out = resolve(world)
    assert "args" in out and len(reads(world)) == 3, "at 121 s: one read, and now it works"
    assert capsys.readouterr().err.count("failed (mail)") == 2


def test_the_cooldown_oracle_sees_a_read_when_the_clock_has_moved(world, monkeypatch):
    wall = Wall(monkeypatch)
    stale(world)
    world["readers"].fail = tsm.Failure("unavailable", PLANTED)
    resolve(world)
    wall.now += 100
    resolve(world)
    assert len(reads(world)) == 1
    mail_refresh._FAILED.clear()      # the planted fault: a cooldown that forgot
    resolve(world)
    assert len(reads(world)) == 2
    with pytest.raises(AssertionError):
        assert len(reads(world)) == 1


# --- (g) the timeout -------------------------------------------------------------------------------------------------------------------------------


def test_limit_52_the_read_of_a_line_is_bounded_at_60_seconds_and_the_typed_command_keeps_300(world):
    stale(world)
    resolve(world)
    assert [c["timeout"] for c in reads(world)] == [60]
    world["shift"]["by"] += datetime.timedelta(minutes=1)
    ops_sources.source_refresh(world["path"], "inbox")
    assert [c["timeout"] for c in reads(world)] == [60, 300], "the typed command, the page and the routine pass no timeout"


def test_a_timeout_applies_only_to_a_mail_or_calendar_read(world):
    note = world["tmp"] / "notes.md"
    note.write_text("# Notes\n\nA line.\n")
    ops_sources.source_import(world["path"], "notes", file=str(note))
    with pytest.raises(ops.OpsError) as refused:
        ops_sources.source_refresh(world["path"], "notes", timeout=5)
    assert "timeout applies to a mail or calendar read" in str(refused.value) and refused.value.why == "usage"
    assert ops_sources.source_refresh(world["path"], "notes")["refreshed"] in (True, False), "without it the file source refreshes as before"


def test_a_lock_not_free_in_time_is_a_failure_with_no_read_and_a_later_line_can_still_refresh(world, monkeypatch):
    monkeypatch.setattr(mail_refresh, "TURN_TIMEOUT_S", 0.05)
    stale(world)
    ctx = ops_core.context(world["path"])
    key = (ctx["cfg"]["project"], "inbox")
    held = mail_refresh._lock_of(key)
    held.acquire()
    try:
        started = time.monotonic()
        with mail_refresh.turn():
            assert mail_refresh.refresh_once(ctx, "inbox", "messaging", READER) == "failed"
        assert time.monotonic() - started < 5 and reads(world) == []
    finally:
        held.release()
    assert "args" in resolve(world), "once the lock is free the next line refreshes"
    assert len(reads(world)) == 1


# --- (i) no refresh when the snapshot is fresh ----------------------------------------------------------------------------------------------------


def test_a_fresh_snapshot_is_searched_as_it_is_with_no_read(world):
    out = resolve(world)
    assert out == {"args": {"account": "google", "messages": "inbox#1"}} and reads(world) == []


def test_a_message_that_only_the_provider_holds_is_found_after_the_refresh_and_not_before(world):
    world["readers"].mail["gmail"].append(tsm.message(4, sender="Ana Costa <ana.costa@clinic.example>", subject="Reschedule request", id="m4"))
    before = resolve(world, words=["clinic"], plural=True)
    assert before == {"args": {"account": "google", "messages": "inbox#1"}} and reads(world) == [], "fresh: the snapshot holds one message from the clinic, and nothing was read"
    stale(world)
    out = resolve(world, words=["clinic"], plural=True)
    assert len(reads(world)) == 1 and len(out["args"]["messages"].split(",")) == 2, "the refreshed snapshot holds both messages from the clinic (the stale one held one)"


# --- (j) two lines at once ---------------------------------------------------------------------------------------------------------------------------


def two_lines_at_once(world, monkeypatch, lock_of=None):
    stale(world)
    original = type(world["readers"]).__call__

    def slow(self, *a, **k):
        time.sleep(0.2)
        return original(self, *a, **k)
    monkeypatch.setattr(type(world["readers"]), "__call__", slow)
    if lock_of:
        monkeypatch.setattr(mail_refresh, "_lock_of", lock_of)
    gate, results = threading.Barrier(2), []

    def line():
        ctx = ops_core.context(world["path"])
        gate.wait(timeout=10)
        results.append(onm.resolve(ctx, "mail-trash", {"words": ["ana"], "source": "inbox"}, "messaging", READER))
    threads = [threading.Thread(target=line) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads) and len(results) == 2
    return results


def test_two_lines_that_need_the_same_stale_source_at_once_read_it_once_and_both_end_in_the_card(world, monkeypatch):
    results = two_lines_at_once(world, monkeypatch)
    assert len(reads(world)) == 1, "one provider read for the source: the second line waited and found it fresh"
    assert results == [{"args": {"account": "google", "messages": "inbox#1"}}] * 2


def test_without_the_lock_of_the_source_two_lines_would_read_twice_so_the_oracle_sees_the_lock(world, monkeypatch):
    results = two_lines_at_once(world, monkeypatch, lock_of=lambda key: threading.Lock())      # the planted fault: a lock of its own for every line
    assert len(reads(world)) == 2
    with pytest.raises(AssertionError):
        assert len(reads(world)) == 1
    assert len(results) == 2


def test_a_line_that_waited_for_a_source_that_then_failed_does_not_try_again_inside_the_cooldown(world, monkeypatch):
    stale(world)
    world["readers"].fail = tsm.Failure("unavailable", PLANTED)
    results = two_lines_at_once(world, monkeypatch)
    assert len(reads(world)) == 1, "the second line, holding the lock after the first failed, finds the source cooling"
    assert [said(r) for r in results] == ["NW_MAIL_REFRESH_FAILED"] * 2


# --- (k) the stage the phone's acknowledgement reads -------------------------------------------------------------------------------------------------


def test_the_read_publishes_the_mail_stage_and_nothing_else_of_the_line(world):
    line_stage = st.load("line_stage")
    slot = line_stage.watch()
    try:
        stale(world)
        resolve(world)
        assert slot.stage == "mail"
    finally:
        line_stage.release(slot)


# --- a number chosen from a list names the message of that list only; a refresh that changes nothing rests the source --------------------------------------------


def listed(world):
    """The list of three messages asked of READER ("which message?"), drawn from a fresh snapshot in which every subject holds the word `report`; returns the reply that asked."""
    for n, message in enumerate(world["readers"].mail["gmail"], 1):
        message["subject"] = f"Weekly report {n}"
    stale(world)
    ops_sources.source_refresh(world["path"], "inbox")      # the snapshot the list is drawn from: read now, fresh
    del world["readers"].calls[:]
    seed = words_seed()
    seed["slots"].update(words=["report"], source="inbox")
    first = phone(world, "apague o e-mail report", seed)
    assert first["asked"] and "ana@clinic.example" in first["reply"] and "bob@shop.example" in first["reply"], first["reply"]
    return first


def another_line_refreshes(world):
    """A new message arrives, the snapshot goes stale and ANOTHER line (a second reader, a list on a phone, a routine) reads the source again: the numbers now name other messages."""
    world["readers"].mail["gmail"].insert(0, tsm.message(10, "2026-10-25T09:00:00Z", sender="Dan Reis <dan@work.example>", subject="Brand new", id="m10"))
    stale(world)
    before = len(reads(world))
    assert said(resolve(world, words=["zzz-nothing"])) == "NW_MAIL_NONE" and len(reads(world)) == before + 1, "the other line read the source"


def test_a_number_chosen_from_a_list_is_refused_when_another_line_read_the_source_again_since(world):
    listed(world)
    another_line_refreshes(world)
    done = phone(world, "2")
    assert done["reply"] == phrases.text("NW_MAIL_LIST_CHANGED", {"language": "en"}) and "resend" not in done and cards(world) == [], "nothing is opened"
    assert phone_problems(done["reply"]) == []


def test_the_check_of_the_list_is_what_stops_the_wrong_card_so_without_it_another_message_would_open(world, monkeypatch):
    listed(world)
    another_line_refreshes(world)
    monkeypatch.setattr(onm, "_same_list", lambda *a: None)      # the planted fault: no check
    done = phone(world, "2")
    assert "resend" in done and "ana@clinic.example" in cards(world)[0]["body"] and "bob@shop.example" not in cards(world)[0]["body"], "the card is on another message than the one the person saw"
    with pytest.raises(AssertionError):
        assert cards(world) == []


def test_a_number_chosen_from_a_list_that_is_still_the_newest_snapshot_opens_the_message_it_named(world):
    listed(world)
    done = phone(world, "2")
    assert "resend" in done and len(cards(world)) == 1
    body = cards(world)[0]["body"]
    assert "bob@shop.example" in body and "ana@clinic.example" not in body, "the second message of the list, as the person saw it"
    assert reads(world) == [], "the answer reads no provider"


def test_a_list_that_went_stale_without_a_refresh_is_answered_with_the_stale_sentence_and_no_read(world):
    listed(world)
    stale(world)
    done = phone(world, "2")
    assert done["reply"] == phrases.text("ACCT_MAIL_REF_STALE", {"language": "en"}, ref="inbox") and cards(world) == [] and reads(world) == []


def test_a_draft_that_records_no_snapshot_for_its_list_fails_closed(world):
    ctx = ops_core.context(world["path"])
    for bad in ({}, {"source": "inbox"}, {"version": 1}, "inbox", {"source": 5, "version": 1}):
        out = onm.resolve(ctx, "mail-trash", {"words": ["report"], "chosen": "inbox#2", "_listed": bad}, "messaging", READER)
        assert said(out) == "NW_MAIL_LIST_CHANGED", bad
    assert reads(world) == []


def test_a_refresh_that_works_but_leaves_the_snapshot_refused_rests_the_source_like_a_failure_and_the_next_lines_read_nothing(world, monkeypatch, capsys):
    wall = Wall(monkeypatch)
    seen, _ = counter(monkeypatch)      # the read "works" and the snapshot stays stale (a clock that is off, the same signature: no new version)
    stale(world)
    for _ in range(5):
        assert said(resolve(world)) == "NW_MAIL_REFRESH_FAILED"
    assert len(seen) == 1, "five lines, one read: the source rests after a read that changed nothing"
    assert capsys.readouterr().err.splitlines() == ["mail: refresh of inbox failed (unchanged)"]
    wall.now += 121
    assert said(resolve(world)) == "NW_MAIL_REFRESH_FAILED" and len(seen) == 2, "after the rest: one more read"


def test_the_rest_oracle_sees_a_read_when_the_rest_is_forgotten(world, monkeypatch):
    seen, _ = counter(monkeypatch)
    stale(world)
    for _ in range(5):
        mail_refresh._FAILED.clear()      # the planted fault: a rest that forgot
        resolve(world)
    assert len(seen) == 5
    with pytest.raises(AssertionError):
        assert len(seen) == 1


# --- the docs ----------------------------------------------------------------------------------------------------------------------------------------


def test_the_module_names_no_provider_class_no_provider_path_and_no_model_and_the_family_names_the_module():
    import ast
    tree = ast.parse((st.RUNTIME / "mail_refresh.py").read_text(encoding="utf-8"))
    imported, strings = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append(node.value)
    assert imported <= {"__future__", "contextlib", "importlib", "os", "sys", "threading", "time", "item_refs", "line_stage", "sources"}, imported
    code_strings = [t for t in strings if len(t) < 200]      # the module's text is longer than any literal of the code
    for forbidden in ("reader:email", "integration:calendar", "providers", "resolve.py", "subprocess", "provider_call"):
        assert not [t for t in code_strings if forbidden in t], forbidden
    assert "ops_sources" in code_strings and "ops_items" in code_strings, "the two modules reached by name, lazily: the one source operation and the closed words"
    assert "import mail_refresh" in (st.RUNTIME / "ops_natural_mail.py").read_text(encoding="utf-8")
    assert list(mail_refresh.TRIGGERS) == ["stale", "no_version", "no_index"] and mail_refresh.TURN_TIMEOUT_S == 60 and mail_refresh.FAIL_COOLDOWN_S == 120


def test_the_failure_sentence_is_in_both_columns_with_the_source_field_and_holds_no_command_or_path():
    for tag in ("en", "pt-BR"):
        text = phrases.text("NW_MAIL_REFRESH_FAILED", {"language": tag}, source="o Gmail")
        assert "o Gmail" in text and phone_problems(text.replace("/", "")) == [] and "/" not in text, tag
    assert phrases._fields_of(phrases.TABLE["en"]["NW_MAIL_REFRESH_FAILED"]) == phrases._fields_of(phrases.TABLE["pt-BR"]["NW_MAIL_REFRESH_FAILED"])
