"""Tests of the `reply_to` field of the two mailbox readers (package SNAP-IDX): a message that asks its replies to go to an address other than its
sender's carries that address, alone, with no display name; a message with no Reply-To, with one that is the sender's own (in any case), or with
one that holds no address carries no `reply_to` key at all, so that the shape every other test pins is unchanged. The Gmail reader keeps the
Reply-To header among the generic ones; the Outlook reader adds `replyTo` to its $select and to nothing else. Offline: Gmail through its
`normalize`, Outlook through the stand-in Graph on loopback; every name and address is invented.

Run: uv run --with pytest==9.1.1 pytest providers/mailbox/tests/test_mailbox_reply_to.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fake_graph_mail  # noqa: E402


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gmail = load(HERE.parent / "gmail.py", "gmail_reply_to_under_test")
OUTLOOK = HERE.parent / "outlook.py"


def eml(sender="Ana Lima <ana@clinic.example>", reply_to=None, **more) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Message-ID"] = sender, "Sam Sample <sam@mail.example>", "Appointment", "<m1@clinic.example>"
    if reply_to is not None:
        msg["Reply-To"] = reply_to
    for key, value in more.items():
        msg[key] = value
    msg.set_content("Your appointment is confirmed.")
    return msg.as_bytes()


# --- Gmail ----------------------------------------------------------------------------------------------------------------------------


def test_gmail_a_reply_to_other_than_the_sender_is_the_address_alone():
    out = gmail.normalize(eml(reply_to="Front Desk <desk@clinic.example>"), source="gmail", message_id="m1", thread_id="t1")
    assert out["reply_to"] == "desk@clinic.example", "the display name is dropped"
    assert out["headers"]["Reply-To"] == "Front Desk <desk@clinic.example>", "the header itself is kept among the generic ones"
    assert out["from"] == "Ana Lima <ana@clinic.example>"


@pytest.mark.parametrize("reply_to", ["ana@clinic.example", "Ana L. <ANA@Clinic.Example>", "<ana@clinic.example>"])
def test_gmail_a_reply_to_that_is_the_senders_own_address_is_absent(reply_to):
    out = gmail.normalize(eml(reply_to=reply_to), source="gmail", message_id="m1", thread_id="t1")
    assert "reply_to" not in out, "compared without case, after the display name is dropped"


def raw_eml(reply_header: str) -> bytes:
    """A message whose Reply-To line is written as given, even when no mail library would build it."""
    return ("From: Ana Lima <ana@clinic.example>\r\nTo: Sam Sample <sam@mail.example>\r\nSubject: Appointment\r\nMessage-ID: <m1@clinic.example>\r\n"
            f"Reply-To: {reply_header}\r\nContent-Type: text/plain\r\n\r\nHello\r\n").encode("utf-8")


def test_gmail_no_reply_to_leaves_no_key():
    assert "reply_to" not in gmail.normalize(eml(), source="gmail", message_id="m1", thread_id="t1")
    assert "reply_to" not in gmail.normalize(eml(reply_to=""), source="gmail", message_id="m1", thread_id="t1")


@pytest.mark.parametrize("reply_to", ["no address here", "desk@", "@clinic.example", "a b@clinic.example", "Undisclosed recipients:;", "desk@@clinic.example",
                                      "<>", "=?utf-8?q?bad?="])
def test_gmail_a_reply_to_without_an_address_leaves_no_key_and_never_a_crash(reply_to):
    out = gmail.normalize(raw_eml(reply_to), source="gmail", message_id="m1", thread_id="t1")
    assert "reply_to" not in out


def test_gmail_a_reply_to_that_lists_two_mailboxes_leaves_no_key():
    raw = raw_eml("Desk <desk@clinic.example>, Billing <billing@clinic.example>")
    assert "reply_to" not in gmail.normalize(raw, source="gmail", message_id="m1", thread_id="t1")


def test_gmail_a_message_without_reply_to_has_the_same_keys_as_before():
    out = gmail.normalize(eml(), source="gmail", message_id="m1", thread_id="t1")
    assert set(out) == {"id", "thread_id", "source", "received_at", "unread", "from", "to", "subject", "text", "truncated", "links", "headers",
                        "attachments", "external_content", "from_address"}      # `unread`: CB-2, null for a message that carries no label list
    assert out["from_address"] == "ana@clinic.example"
    assert set(out["headers"]) == {"From", "To", "Subject", "Message-ID"}


def test_gmail_the_help_text_names_the_field():
    assert "reply_to" in gmail.HELP_EPILOG and "Reply-To" in gmail.HELP_EPILOG


# --- Outlook --------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def fake():
    f = fake_graph_mail.FakeGraphMail()
    f.add("m1", "2026-10-17T07:12:03Z", "Ana Lima", "ana@clinic.example", "Appointment confirmed", text="Your appointment is confirmed.")
    f.add("m2", "2026-10-16T18:30:00Z", "Bruno Reis", "bruno@shop.example", "Your order", text="Order 77 shipped.")
    yield f
    f.close()


def run(fake, *argv):
    base = {k: v for k, v in os.environ.items() if not k.startswith("OUTLOOK_") and not k.startswith("MAILBOX_")}
    done = subprocess.run([sys.executable, str(OUTLOOK), *argv], capture_output=True, text=True, timeout=120, env={**base, **fake.env()})
    return done.returncode, (json.loads(done.stdout) if done.stdout.strip() else None), done.stdout + done.stderr


def test_outlook_a_reply_to_other_than_the_sender_is_the_address_alone(fake):
    fake.messages["m1"]["replyTo"] = [fake_graph_mail.recipient("Front Desk", "desk@clinic.example")]
    code, out, said = run(fake, "get", "--id", "m1")
    assert code == 0, said
    assert out["reply_to"] == "desk@clinic.example" and out["from"] == "Ana Lima <ana@clinic.example>"
    assert "replyTo" in fake.api_requests()[0]["query"]["$select"].split(","), "the request asks for the field"


def test_outlook_search_carries_it_on_the_messages_that_have_one_only(fake):
    fake.messages["m1"]["replyTo"] = [fake_graph_mail.recipient("Front Desk", "desk@clinic.example")]
    code, out, said = run(fake, "search", "--query", "in:inbox", "--since", "2026-10-01T00:00:00Z")
    assert code == 0, said
    by_id = {m["id"]: m for m in out["messages"]}
    assert by_id["m1"]["reply_to"] == "desk@clinic.example" and "reply_to" not in by_id["m2"]


@pytest.mark.parametrize("reply_to", [
    [fake_graph_mail.recipient("Ana", "ANA@clinic.example")], [], None, [{"emailAddress": {"name": "Nobody", "address": ""}}], ["not a recipient"],
    [{"emailAddress": "not an object"}], [fake_graph_mail.recipient("Bad", "no-at-sign")]])
def test_outlook_a_reply_to_that_is_the_senders_or_holds_no_address_leaves_no_key(fake, reply_to):
    fake.messages["m1"]["replyTo"] = reply_to
    code, out, said = run(fake, "get", "--id", "m1")
    assert code == 0, said
    assert "reply_to" not in out


def test_outlook_the_one_address_of_the_list_is_kept_whatever_else_is_in_it(fake):
    fake.messages["m1"]["replyTo"] = [{"emailAddress": {"name": "Empty", "address": ""}}, fake_graph_mail.recipient("Desk", "desk@clinic.example"),
                                      fake_graph_mail.recipient("Desk again", "DESK@clinic.example"), "not a recipient"]
    code, out, said = run(fake, "get", "--id", "m1")
    assert code == 0, said
    assert out["reply_to"] == "desk@clinic.example"


def test_outlook_two_different_addresses_in_the_list_leave_no_key(fake):
    fake.messages["m1"]["replyTo"] = [fake_graph_mail.recipient("Desk", "desk@clinic.example"), fake_graph_mail.recipient("Billing", "billing@clinic.example")]
    code, out, said = run(fake, "get", "--id", "m1")
    assert code == 0, said
    assert "reply_to" not in out


def test_outlook_the_request_still_reads_only_and_the_select_gains_one_field_and_no_other(fake):
    code, out, said = run(fake, "get", "--id", "m1")
    assert code == 0, said
    asked = fake.api_requests()[0]
    assert asked["method"] == "GET"
    assert set(asked["query"]["$select"].split(",")) == {"id", "conversationId", "changeKey", "receivedDateTime", "sentDateTime", "from", "toRecipients",
                                                         "replyTo", "subject", "body", "hasAttachments", "internetMessageId", "isRead"}      # `isRead`: CB-2


# --- the sender's plain address (review M1): read from the parsed header or the address field, never picked out of words ---------------------


@pytest.mark.parametrize("sender, expected", [
    ("Ana Lima <ana@clinic.example>", "ana@clinic.example"),
    ("ana@clinic.example", "ana@clinic.example"),
    ('"ceo@corp.example, x" <attacker@evil.example>', "attacker@evil.example"),        # one mailbox: the one in the angle brackets is the real one
    ("=?utf-8?q?ceo=40corp.example=2C?= <attacker@evil.example>", "attacker@evil.example"),
    ("ceo@corp.example, Attacker <attacker@evil.example>", None),                       # two mailboxes: no address is picked out of them
    ("ceo@corp.example <attacker@evil.example>", None),                                 # an address in the display name without quotes: a defect
    ("Group: a@x.example, b@y.example;", None),
    ("a@x.example., b@y.example", None), ("a..b@x.example", None), ("attacker@evil.example@corp.example", None), ("Nobody", None)])
def test_gmail_the_sender_address_is_the_one_mailbox_of_the_from_header_or_nothing(sender, expected):
    out = gmail.normalize(raw_eml("Ana <ana@clinic.example>").replace(b"From: Ana Lima <ana@clinic.example>", b"From: " + sender.encode("utf-8")),
                          source="gmail", message_id="m1", thread_id="t1")
    assert out.get("from_address") == expected, out["from"]


def test_gmail_a_reply_to_is_taken_only_from_a_header_of_one_mailbox_and_is_compared_with_the_senders_address():
    both = raw_eml("Desk <desk@clinic.example>").replace(b"From: Ana Lima <ana@clinic.example>", b"From: ceo@corp.example, Ana <ana@clinic.example>")
    out = gmail.normalize(both, source="gmail", message_id="m1", thread_id="t1")
    assert "from_address" not in out and out["reply_to"] == "desk@clinic.example", "no sender address to compare with: the Reply-To is still the one mailbox of its header"


@pytest.mark.parametrize("name, expected", [("Ana Lima", "attacker@evil.example"), ("ceo@corp.example, x", "attacker@evil.example"), ("", "attacker@evil.example")])
def test_outlook_the_sender_address_is_the_address_field_whatever_the_display_name_says(fake, name, expected):
    fake.messages["m1"]["from"] = fake_graph_mail.recipient(name, "attacker@evil.example")
    code, out, said = run(fake, "get", "--id", "m1")
    assert code == 0, said
    assert out["from_address"] == expected


@pytest.mark.parametrize("address", ["", "no at sign", "a..b@x.example", "a@x.example.", "a@-x.example", "a b@x.example", "x" * 65 + "@y.example", None])
def test_outlook_a_sender_field_that_is_not_a_plain_address_leaves_no_key(fake, address):
    fake.messages["m1"]["from"] = {"emailAddress": {"name": "Ana", "address": address}}
    code, out, said = run(fake, "get", "--id", "m1")
    assert code == 0, said
    assert "from_address" not in out


def test_gmail_a_header_that_appears_twice_gives_no_address():
    base = ("To: Sam Sample <sam@mail.example>\r\nSubject: Appointment\r\nMessage-ID: <m1@clinic.example>\r\nContent-Type: text/plain\r\n\r\nHello\r\n")
    twice_from = ("From: ceo@corp.example\r\nFrom: attacker@evil.example\r\nReply-To: desk@clinic.example\r\n" + base).encode("utf-8")
    out = gmail.normalize(twice_from, source="gmail", message_id="m1", thread_id="t1")
    assert "from_address" not in out and out["reply_to"] == "desk@clinic.example"
    twice_reply = ("From: Ana <ana@clinic.example>\r\nReply-To: rt@evil.example\r\nReply-To: other@evil.example\r\n" + base).encode("utf-8")
    out = gmail.normalize(twice_reply, source="gmail", message_id="m1", thread_id="t1")
    assert out["from_address"] == "ana@clinic.example" and "reply_to" not in out
    once = ("From: Ana <ana@clinic.example>\r\nReply-To: rt@evil.example\r\n" + base).encode("utf-8")
    out = gmail.normalize(once, source="gmail", message_id="m1", thread_id="t1")
    assert out["from_address"] == "ana@clinic.example" and out["reply_to"] == "rt@evil.example"
