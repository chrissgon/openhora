"""The account question end to end on the messaging bridge (package mail-list-account; runtime/messaging_bridge.py, runtime/ops_say.py, runtime/ops_natural.py, runtime/item_refs.py).

test_messaging_mail_list_account.py stands in the project's accounts (`ops_items.account_choices`) and the one place a read runs, so the memory of the list on screen (N1) never ran on the bridge,
and the entry replay has no world with two mail sources. Here neither is stood in: two real mail sources behind the real snapshots (test_calendar_write.py's world and the stand-in providers of
test_sources_mail.py), the real catalog, the real read, the real bridge and a stand-in messenger, model and clock (plan_bridge_kit.py). The sequence a person lives: the question, a tap, the list,
"open the 1st" and the yes, then every account (bold, blank line), the number that now asks which box, a greeting. The model is stood in at its route, and only to say the operation of
"open the 1st". Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_mail_list_account_e2e.py
"""
from __future__ import annotations

import json

import pytest

import plan_confirm_kit as pck
import standin_tree as st
import test_sources_mail as tsm
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the bridge, not the claim)
from plan_bridge_kit import OWNER_ID, OWNER_KEY, brig, ops, phrases, plan_confirm, rig, wait_for, world  # noqa: F401
from test_calendar_write import Snapshots
from test_messaging_mail_list_account import last_message, question, t

ops_items = st.load("ops_items")
ops_natural = st.load("ops_natural")
ops_sources = st.load("ops_sources")
item_refs = st.load("item_refs")
REAL_READ = ops_natural._read      # the rig's `brig` fixture puts a spy here; this file wants the real one
LINE = "mostra meus emails"
pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did


class Mailboxes:
    pass


@pytest.fixture
def mail(brig, monkeypatch):
    """The rig's world with a real Gmail source (two messages) and a real Outlook source (one), the real read, and the right to read the bodies for every sender."""
    monkeypatch.setattr(ops_natural, "_read", REAL_READ)
    snaps = Snapshots(brig.rig.world, monkeypatch)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: snaps.now)
    ops_items._CHECKED.clear()
    item_refs._LISTED.clear()
    profiles = {name: sorted(set(groups) | {"ask-mail", "read-mail-body"}) for name, groups in pck.PROF.items()}
    pck.accept(brig.rig.world["path"], policies=profiles, messaging={"senders": pck.SENDER_LIST})
    snaps.providers.mail["gmail"] = [tsm.message(1, "2026-10-17T09:00:00Z", "Bia Costa <bia@clinic.example>", "Appointment confirmed", "Your visit is confirmed."),
                                     tsm.message(2, "2026-10-17T08:00:00Z", "Eva Luz <eva@clinic.example>", "Second subject", "Second body.")]
    snaps.providers.mail["outlook"] = [tsm.message(1, "2026-10-17T09:00:00Z", "Dan Reis <dan@work.example>", "Weekly report", "Weekly numbers attached.", source="outlook")]
    ops_sources.source_mail(brig.rig.world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    ops_sources.source_mail(brig.rig.world["path"], "work", "outlook:box=inbox;days=7;max=50")
    del snaps.providers.calls[:]
    m = Mailboxes()
    m.brig, m.snaps = brig, snaps
    m.provider_reads = lambda: len([c for c in snaps.providers.calls if c["cls"] == "reader:email"])
    return m


def says_read(brig, number):
    """The model, stood in at its route, reads "open the 1st" as the operation `mail-read` with the number the line writes."""
    brig.rig.says["text"] = json.dumps({"v": 1, "kind": "op", "op": "mail-read", "slots": {"message": str(number)}})


def sent_after(brig, count, line=None, tap=None):
    """Say a line (or tap a button) and return the texts that came after `count` sent messages, once the bridge is idle and something new was sent."""
    if line is not None:
        brig.say(line)
    else:
        brig.tap(tap)
    assert wait_for(lambda: len(brig.texts()) > count) and brig.idle()
    return brig.texts()[count:]


def pick(brig, word):
    """Ask for the e-mails and tap the option `word` (pick:0, pick:1 or pick:2): the reply that follows."""
    brig.ask(LINE)
    assert brig.idle()
    return sent_after(brig, len(brig.texts()), tap=brig.question_actions()[word])[-1]


def plan_args(brig):
    return plan_confirm.live(brig.rig.world["path"], OWNER_KEY)["state"]["args"]


def test_the_question_a_tap_the_list_and_the_number_after_it_end_to_end(mail):
    b = mail.brig
    b.ask(LINE)
    assert b.idle()
    assert last_message(b)["text"] == question(b) and [a["label"] for a in last_message(b)["actions"]] == ["Gmail", "Outlook", t(b, "PLAN_ALL_ACCOUNTS")]
    assert mail.provider_reads() == 0, "nothing was read before an answer"
    listed = sent_after(b, len(b.texts()), tap=b.question_actions()["pick:0"])[-1]
    assert listed.startswith("Gmail (") and "Bia Costa" in listed and "Eva Luz" in listed and "Outlook" not in listed and "Dan Reis" not in listed and "**" not in listed
    assert [(v["source"], v["seen"]) for v in item_refs._LISTED.values()] == [("inbox", 0)], "the list on screen is remembered by the real read"
    says_read(b, 1)
    asked = sent_after(b, len(b.texts()), line="abre o 1")[-1]      # validate: allow english-only -- the Portuguese words under test
    assert asked == t(b, "PLAN_HEAD", what=t(b, "UNDERSTOOD_MAIL_READ_N", n=1)) + " " + t(b, "PLAN_ASK")
    assert plan_args(b) == {"number": 1, "message": "inbox#1"}, "the number is bound to the list on screen, and the plan's hash binds it"
    shown = sent_after(b, len(b.texts()), line="sim")[-1]      # validate: allow english-only -- the Portuguese words under test
    assert shown.startswith(t(b, "MR_HEAD", box="Gmail", line="Bia Costa")[:len("Gmail · Bia")]) and "Your visit is confirmed." in shown and "Weekly numbers" not in shown
    assert mail.provider_reads() == 0, "a number never reads a provider"


def test_every_account_is_one_message_with_bold_names_and_a_number_after_it_asks_which_box(mail):
    b = mail.brig
    listed = pick(b, "pick:2")
    assert listed.startswith("**Gmail** (") and "\n\n**Outlook** (" in listed and "Bia Costa" in listed and "Dan Reis" in listed
    assert item_refs._LISTED == {}, "two mail sources on screen: no list is remembered"
    says_read(b, 1)
    sent_after(b, len(b.texts()), line="abre o 1")      # validate: allow english-only -- the Portuguese words under test
    assert plan_args(b) == {"number": 1}, "no binding"
    shown = sent_after(b, len(b.texts()), line="sim")[-1]      # validate: allow english-only -- the Portuguese words under test
    assert "Your visit is confirmed." not in shown and "Weekly numbers" not in shown and "Bia Costa" in shown and "Dan Reis" in shown, "the sentence names both boxes and shows no message"


def test_the_second_line_after_a_list_forgets_it_and_a_greeting_drops_the_question_and_reads_nothing(mail):
    b = mail.brig
    pick(b, "pick:1")      # Outlook: one row
    assert [v["source"] for v in item_refs._LISTED.values()] == ["work"]
    b.rig.says["text"] = json.dumps({"v": 1, "kind": "none"})
    sent_after(b, len(b.texts()), line="obrigado")      # validate: allow english-only -- the Portuguese words under test
    says_read(b, 1)
    sent_after(b, len(b.texts()), line="abre o 1")      # validate: allow english-only -- the Portuguese words under test
    assert "message" not in plan_args(b), "the second line after the list: the memory is gone and the which-box question comes back"
    reads_before = mail.provider_reads()
    b.ask(LINE)
    assert b.idle()
    sent_after(b, len(b.texts()), line="oi")      # validate: allow english-only -- the Portuguese words under test
    assert plan_confirm.live(b.rig.world["path"], OWNER_KEY) is None and mail.provider_reads() == reads_before


def test_vacuity_without_the_counter_of_lines_the_number_binds_to_a_list_that_is_no_longer_the_last(mail, monkeypatch):
    b = mail.brig
    pick(b, "pick:0")
    monkeypatch.setattr(item_refs, "begin_turn", lambda ctx, channel, sender: None)      # planted: no line is ever counted
    says_read(b, 1)
    sent_after(b, len(b.texts()), line="abre o 1")      # validate: allow english-only -- the Portuguese words under test
    assert "message" not in plan_args(b), "the same line that is bound in the first test is not bound when the counter is gone"
