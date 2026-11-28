"""The messaging bridge against what the e-mail provider really writes for a file (AT2): the update of providers/messenger/email-imap.py, checked by the
bridge's own `valid_update`, then the policy, the precheck on what was declared, the fetch through a stand-in that stays connected and serves the very bytes the
provider's child reads from the message, the hold, the card with typed `/add` and `/discard` lines (e-mail has no buttons), and the add. The operations layer is
the real one over a real store; the messenger is the stand-in; the e-mail provider is loaded by path. Offline, no model, no network, no mailbox; every name is
invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_email_attachments_bridge.py
"""
from __future__ import annotations

import base64
import importlib.util
import sys

import pytest

import phrase_kit as pk
import standin_tree as st
from sources_fixture import make_pdf
from test_attachments import accept, case  # noqa: F401  (the project the attachment tests use)
from test_messaging_attach import card_action, make_world, told  # noqa: F401
from test_service import WAIT

providers = st.load("messaging_provider")
attachments = st.load("attachments")
provider_path = st.REPO / "providers" / "messenger" / "email-imap.py"
spec = importlib.util.spec_from_file_location("email_imap_for_the_bridge_test", provider_path)
email_imap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = email_imap
spec.loader.exec_module(email_imap)
mail = email_imap.helpers()

OWN = "assistant@office.example"
OWNER = "owner@office.example"
ID = "mx.office.example"
GOOD = f"{ID}; dkim=pass header.d=office.example header.s=sel1; dmarc=pass (p=quarantine) header.from=office.example"
PLAN = make_pdf("The Q3 plan: grow the newsletter by a third.")
REF = "1000:7:1"


def message(data=PLAN, name="Q3 plan.pdf"):
    """A message with the words and one PDF, as the receiving server stores it."""
    body = ["--B1", "Content-Type: text/plain; charset=utf-8", "", "Here is the plan.",
            "--B1", "Content-Type: application/pdf", "Content-Transfer-Encoding: base64", f'Content-Disposition: attachment; filename="{name}"', "",
            *base64.encodebytes(data).decode("ascii").splitlines(), "--B1--"]
    head = [f"Authentication-Results: {GOOD}", f"From: {OWNER}", f"To: {OWN}", "Subject: Plan for Q3", "Date: Sat, 17 Oct 2026 08:59:00 +0000",
            "Message-ID: <inbound-7@office.example>", "MIME-Version: 1.0", 'Content-Type: multipart/mixed; boundary="B1"']
    return ("\r\n".join([*head, "", *body]) + "\r\n").encode("utf-8")


def the_update(data=None):
    """What the provider emits for the message, as the bridge reads it (valid_update), with the update id the bridge adds."""
    raw = data or message()
    found, why = email_imap.inspect_message(raw, OWN, ID, lambda chat: set(), mail, ref_base="1000:7")
    assert why is None, why
    valid = providers.valid_update(found)
    assert valid is not None and valid["attachments"][0]["ref"] == REF
    return raw, {**valid, "update_id": 1}


@pytest.fixture
def mailworld(case, monkeypatch):
    """The bridge over the chirp stand-in, which declares what the e-mail provider declares and lists the owner's address as a sender."""
    w = make_world(case, monkeypatch, platform="chirp", caps=email_imap.CAPABILITIES)
    accept(case.path, messaging={"senders": {"telegram": ["4242424242"], "chirp": [OWNER]}})
    raw, update = the_update()
    w.put(REF, email_imap.part_in_child(raw, 1))
    w.update = update
    yield w
    w.bridge.stopping.set()
    for thread in list(w.bridge.threads):
        thread.join(WAIT)
    w.messenger.close_session()


def handle(w, update):
    w.bridge.handle(update)
    w.settle()


def test_a_pdf_from_the_email_provider_is_fetched_held_and_carded_like_one_from_a_phone(mailworld):
    w = mailworld
    handle(w, w.update)
    [call] = w.fetches()
    assert call["ref"] == REF and call["max_bytes"] == 1048576 and call["out"].split("/")[-2] == "incoming"
    assert [(r["status"], r["platform"], r["name"]) for r in w.case.rows()] == [("held", "chirp", "Q3 plan.pdf")]
    [sent] = w.sent()
    assert sent["chat"] == OWNER and sent["message"]["actions"] == []
    assert sent["message"]["text"].endswith("Send /add 1\nSend /discard 1"), sent["message"]["text"]
    w.say("/add 1", sender=OWNER)
    pk.assert_said(w.texts()[-1].splitlines()[0], "ATT_ADDED", name="Q3 plan.pdf", id="q3-plan", n=1)
    assert w.incoming() == []
    assert w.case.rows("held") == [], "what was added is no longer held"


def test_a_discard_by_typed_line_drops_the_held_file_and_nothing_enters_the_sources(mailworld):
    w = mailworld
    handle(w, w.update)
    w.say("/discard 1", sender=OWNER)
    assert w.case.rows("held") == [] and w.incoming() == []
    assert not [x for x in w.log if OWNER in x or "Q3" in x]


def test_a_channel_without_the_group_fetches_nothing_from_an_email_file(mailworld):
    w = mailworld
    accept(w.case.path, channels={"messaging": ["read", "talk"]}, policies=None)
    handle(w, w.update)
    told(w.texts(), 1, "ATT_OFF")
    assert w.fetches() == [] and w.case.rows() == [] and w.incoming() == []
    assert [x for x in w.log if OWNER in x or REF in x or "Q3" in x] == [], "one log line, no address, no ref"


def test_an_email_file_declared_over_one_mebibyte_is_refused_before_any_fetch(mailworld):
    w = mailworld
    big = {**w.update, "attachments": [{**w.update["attachments"][0], "size": email_imap.MAX_SIZE + 1}]}
    handle(w, big)
    told(w.texts(), 1, "ATT_TOO_LARGE", name="Q3 plan.pdf", size="1.0 MiB", cap="1.0 MiB")
    assert w.fetches() == [] and w.case.rows() == [] and w.incoming() == []


def test_a_file_the_mailbox_no_longer_has_is_told_gone_and_nothing_is_held(mailworld):
    w = mailworld
    w.flag("gone.json", [REF])
    handle(w, w.update)
    told(w.texts(), 1, "ATT_GONE", platform="chirp")
    assert [(r["status"], r["code"], r["bytes"]) for r in w.case.rows()] == [("refused", "gone", 0)] and w.incoming() == []


def test_a_sender_the_project_does_not_list_gets_no_fetch(mailworld):
    w = mailworld
    stranger = {**w.update, "sender": "stranger@elsewhere.example", "chat": "stranger@elsewhere.example"}
    handle(w, stranger)
    assert w.fetches() == [] and w.case.rows() == [] and w.incoming() == []
