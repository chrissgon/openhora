"""What a phone is told when a source cannot be read for a reason only the computer solves (package sources-identity, limit L62).

Two reasons have a closed word and a sentence of their own: `folder` (the project's sources folder is refused: another project's marker, a mode, a missing folder)
and `authorization` (the provider answered `not-configured`: the account is no longer authorized). Every other failure keeps the plain sentence, because a retry may
work. Here the real snapshots behind the real runtime/item_refs.py (test_calendar_write.py's world, test_items_fresh.py's helpers and the stand-in providers of
test_sources_mail.py), a refused folder made the way a person's would be (a marker that names another project, written as text), a stand-in clock. Every expectation
is a literal of this file. The words of the provider (ZEBRA-SECRET) must never reach the reply or stderr. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_items_refused_reason.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import phrase_kit as pk
import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, world  # noqa: F401  (the calendar world and its real snapshots)
from test_items_fresh import EN, OLD, add_message, ask, clock, is_note, mail_reads, phone_problems, project, snaps, with_inbox  # noqa: F401
from test_ops_natural_writes import READER, policy  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_items = st.load("ops_items")
event_lookup = st.load("event_lookup")
sources = st.load("sources")
turn_gate = st.load("turn_gate")

PROVIDER_WORDS = "Google said ZEBRA-SECRET: run uv run providers/mailbox/auth.py --provider gmail"


def refuse_folder(world) -> None:
    """The sources folder is marked for another project (a marker as an old one reads on disk): every use of it is refused as `foreign`."""
    cfg = ops_core.context(world["path"])["cfg"]
    info = os.stat(cfg["project"])
    text = json.dumps({"kind": "openhora-sources", "version": 3, "id": "0123456789abcdef", "project": f"{info.st_dev}:{info.st_ino + 1}",
                       "project_path": os.path.join(world["tmp"], "another-project")}) + "\n"
    (Path(cfg["sources_dir"]) / sources.MARKER).write_text(text, encoding="utf-8")


def only(reply, key, **fields):
    """The reply is exactly one sentence of the table."""
    assert "\n" not in reply, reply
    pk.assert_said(reply, key, EN, **fields)


@pytest.mark.parametrize("hours", [0.4, 30])
def test_a_folder_refusal_says_so_with_the_snapshot_fresh_or_stale(world, snaps, clock, hours):
    with_inbox(world, snaps)
    snaps.later(hours=hours)
    refuse_folder(world)
    reply = ask(world, "list my emails")
    only(reply, "NW_ITEMS_REFUSED_FOLDER", name="Gmail")
    assert phone_problems(reply) == [] and "{" not in reply
    info = os.stat(ops_core.context(world["path"])["cfg"]["project"])
    assert str(info.st_dev) not in reply and str(info.st_ino) not in reply and "another-project" not in reply, "no device number, no path of the marker"
    assert pk.said(reply, "NW_ITEMS_REFUSED_PHONE", EN, name="Gmail") is False, "and not the plain sentence"


def test_an_expired_authorization_has_its_own_sentence_and_nothing_of_the_provider(world, snaps, clock, capfd):
    with_inbox(world, snaps)
    snaps.later(hours=30)
    snaps.providers.fail = tsm.Failure("not-configured", PROVIDER_WORDS)
    reply = ask(world, "list my emails")
    only(reply, "NW_ITEMS_REFUSED_AUTH", name="Gmail")
    assert len(mail_reads(snaps)) == 1 and phone_problems(reply) == []
    seen = reply + " ".join(capfd.readouterr())
    assert "ZEBRA" not in seen and "auth.py" not in seen and "not-configured" not in seen


def test_a_fresh_snapshot_keeps_its_list_its_note_and_says_the_authorization(world, snaps, clock):
    with_inbox(world, snaps)
    add_message(snaps)
    snaps.later(minutes=11)
    snaps.providers.fail = tsm.Failure("not-configured", PROVIDER_WORDS)
    lines = ask(world, "list my emails").splitlines()
    assert OLD in "\n".join(lines), "the old list is still there"
    assert is_note(lines[-2]) and sum(is_note(line) for line in lines) == 1, "the note of the old time is the line before the reason"
    pk.assert_said(lines[-1], "NW_ITEMS_REFUSED_AUTH", EN, name="Gmail")


def test_any_other_failure_keeps_the_plain_sentence(world, snaps, clock):
    with_inbox(world, snaps)
    snaps.later(hours=30)
    snaps.providers.fail = tsm.Failure("failed", "exit 1")
    reply = ask(world, "list my emails")
    only(reply, "NW_ITEMS_REFUSED_PHONE", name="Gmail")
    # the oracle can tell the three sentences apart: the reply is not either of the other two
    assert not pk.said(reply, "NW_ITEMS_REFUSED_AUTH", EN, name="Gmail") and not pk.said(reply, "NW_ITEMS_REFUSED_FOLDER", EN, name="Gmail")
    snaps.providers.fail = tsm.Failure("not-configured", "x")
    snaps.later(hours=1)
    assert pk.said(ask(world, "list my emails"), "NW_ITEMS_REFUSED_AUTH", EN, name="Gmail"), "the same world with an authorization failure says the authorization"


def test_two_sources_with_one_reason_are_one_sentence(world):
    cfg = {"language": "en"}
    out = {"sources": [], "refused": [{"source": "a", "why": "x", "reason": "folder"}, {"source": "b", "why": "y", "reason": "folder"}]}
    reply = ops_items.render(out, cfg, phone=True, names={"a": "Gmail", "b": "Google calendar"})
    only(reply, "NW_ITEMS_REFUSED_FOLDER", name="Gmail, Google calendar")
    mixed = {"sources": [], "refused": [{"source": "a", "why": "x", "reason": "folder"}, {"source": "b", "why": "y", "reason": "authorization"},
                                        {"source": "c", "why": "z"}]}
    lines = ops_items.render(mixed, cfg, phone=True, names={"a": "Gmail", "b": "Outlook", "c": "Google calendar"}).splitlines()
    assert len(lines) == 3
    pk.assert_said(lines[0], "NW_ITEMS_REFUSED_PHONE", EN, name="Google calendar")
    pk.assert_said(lines[1], "NW_ITEMS_REFUSED_FOLDER", EN, name="Gmail")
    pk.assert_said(lines[2], "NW_ITEMS_REFUSED_AUTH", EN, name="Outlook")
    plain = ops_items.render({"sources": [], "refused": [{"source": "a", "why": "x"}, {"source": "b", "why": "y"}]}, cfg, phone=True, names={"a": "Gmail", "b": "Outlook"})
    assert len(plain.splitlines()) == 2, "with no reason each source keeps its own sentence"


def test_the_terminal_keeps_the_id_and_the_words(world, snaps, clock):
    with_inbox(world, snaps)
    refuse_folder(world)
    ctx = ops_core.context(world["path"])
    out = ops.items(world["path"], kind="mail", channel="terminal")
    reply = ops_items.reply(world["path"], ctx, out, "terminal")
    assert reply.startswith("inbox: the sources folder") and "--adopt-sources" in reply and "another project" in reply
    assert "needs a step on the computer" not in reply, "the phone's words are not the terminal's"


def test_reason_of_vacuity():
    assert ops_items.reason_of("mail") is None and ops_items.reason_of("mail", "failed") is None and ops_items.reason_of("mail", "usage") is None
    assert ops_items.reason_of("credential", "not-configured") is None, "`credential` is a secret found in converted text, not an authorization"
    assert ops_items.reason_of("integrity") is None and ops_items.reason_of(None) is None and ops_items.reason_of("lease") is None
    assert ops_items.reason_of("foreign") == "folder" and ops_items.reason_of("path") == "folder" and ops_items.reason_of("folder") == "folder"
    assert ops_items.reason_of("calendar", "not-configured") == "authorization" and ops_items.reason_of("mail", "not-configured") == "authorization"
    # a planted wrong table: the checks above read the word, not the sentence, so a wrong word is seen
    assert ops_items.REASON_KEYS == {"folder": "NW_ITEMS_REFUSED_FOLDER", "authorization": "NW_ITEMS_REFUSED_AUTH"}


def test_the_turn_keeps_a_word_and_nothing_outside_a_turn():
    turn_gate.note_reason("inbox", "authorization")
    assert turn_gate.failed_reason("inbox") is None, "outside a turn nothing is kept"
    with turn_gate.turn():
        turn_gate.note_reason("inbox", "authorization")
        turn_gate.note_reason("work", None)
        turn_gate.note_reason("", "folder")
        assert turn_gate.failed_reason("inbox") == "authorization" and turn_gate.failed_reason("work") is None
    with turn_gate.turn():
        assert turn_gate.failed_reason("inbox") is None, "the next line starts empty"


def test_a_folder_refusal_on_a_fresh_snapshot_does_not_escape_the_calendar_lookup(world, snaps, clock):
    project(world)
    snaps.calendar("agenda", "google", "pat@example.com", [tsm.event(1, title="Dentist", id="ev1")])
    ctx = ops_core.context(world["path"])
    found, problem = event_lookup.events(ctx, READER)
    assert problem is None and [e["title"] for e in found] == ["Dentist"], "the same world, before the folder is refused, finds the event"
    refuse_folder(world)
    assert event_lookup.events(ctx, READER) == ([], "stale")
