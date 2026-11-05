"""Tests of the `unread` flag both mailbox readers print (package CB-2): Gmail's from the message's `labelIds` (UNREAD), Graph's from `isRead`. A closed
boolean, or null when the service's answer carried no flag: a message with no label list is never "read". No network, no credential, `.example` addresses;
the Gmail client is a stand-in object, the Outlook provider runs against the loopback stand-in of Graph.

Run: uv run --with pytest==9.1.1 pytest providers/mailbox/tests/test_mailbox_unread.py
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
GMAIL = HERE.parent / "gmail.py"
OUTLOOK = HERE.parent / "outlook.py"
sys.path.insert(0, str(HERE))
import fake_graph_mail  # noqa: E402


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gmail = load(GMAIL, "gmail_unread_under_test")
outlook = load(OUTLOOK, "outlook_unread_under_test")


def raw_message() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Ana Lima <ana@clinic.example>"
    msg["To"] = "sam@mail.example"
    msg["Subject"] = "Appointment confirmed"
    msg["Date"] = "Mon, 12 Oct 2026 09:00:00 +0000"
    msg.set_content("See you on Friday.")
    return msg.as_bytes()


def gmail_answer(**extra) -> dict:
    return {"id": "m1", "threadId": "t1", "internalDate": "1792000000000", "raw": base64.urlsafe_b64encode(raw_message()).decode(), **extra}


def gmail_message(**extra) -> dict:
    """The message Gmail.message prints for an answer of the service, and the requests it made."""
    client = gmail.Gmail("http://127.0.0.1:1", "token")
    asked = []

    def get(path, params=None):
        asked.append((path, params))
        return gmail_answer(**extra)

    client.get = get
    return client.message("m1"), asked


# --- Gmail ---------------------------------------------------------------------------------------------------------------------


def test_gmail_unread_is_true_when_labelids_holds_unread():
    message, _ = gmail_message(labelIds=["INBOX", "UNREAD", "CATEGORY_PERSONAL"])
    assert message["unread"] is True


def test_gmail_unread_is_false_when_labelids_is_a_list_without_unread():
    message, _ = gmail_message(labelIds=["INBOX", "IMPORTANT"])
    assert message["unread"] is False
    message, _ = gmail_message(labelIds=[])
    assert message["unread"] is False, "an empty list of labels is a list: the message is not unread"


@pytest.mark.parametrize("labels", [None, "UNREAD", {"UNREAD": True}, 1, True])
def test_gmail_unread_is_null_never_false_when_there_is_no_list_of_labels(labels):
    extra = {} if labels is None else {"labelIds": labels}
    message, _ = gmail_message(**extra)
    assert message["unread"] is None, "no label list is unknown, not read"


def test_gmail_asks_the_message_once_in_raw_format_and_nothing_more_for_the_flag():
    _, asked = gmail_message(labelIds=["UNREAD"])
    assert asked == [("/gmail/v1/users/me/messages/m1", {"format": "raw"})], "no second request for the labels"


def test_gmail_unread_comes_with_the_rest_of_the_normalized_message():
    message, _ = gmail_message(labelIds=["UNREAD"])
    assert message["id"] == "m1" and message["thread_id"] == "t1" and message["received_at"] == "2026-10-14T17:46:40Z" \
        and message["from_address"] == "ana@clinic.example" and message["external_content"] is True
    assert list(message).index("unread") == list(message).index("received_at") + 1


def test_gmail_read_eml_has_no_labels_so_unread_is_null(tmp_path, capsys):
    path = tmp_path / "saved.eml"
    path.write_bytes(raw_message())
    assert gmail.main(["read-eml", "--file", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["unread"] is None


def test_gmail_normalize_keeps_only_a_boolean():
    for given, wanted in ((True, True), (False, False), (None, None), ("yes", None), (1, None), ([], None)):
        assert gmail.normalize(raw_message(), source="gmail", message_id="m1", unread=given)["unread"] is wanted


def test_gmail_unread_state_reads_the_unread_label_only():
    assert gmail.unread_state(["UNREAD"]) is True and gmail.unread_state(["unread"]) is False, "the label's own spelling"
    assert gmail.unread_state(["STARRED", "INBOX"]) is False and gmail.unread_state(None) is None and gmail.unread_state("UNREAD") is None


def test_gmail_flag_is_vacuous_if_the_reader_drops_it(monkeypatch):
    """The oracle: with the reader's own function made to answer nothing, the flag test above would see null, so it does bite."""
    monkeypatch.setattr(gmail, "unread_state", lambda label_ids: None)
    message, _ = gmail_message(labelIds=["UNREAD"])
    assert message["unread"] is None and message["unread"] is not True


# --- Outlook -------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def fake():
    f = fake_graph_mail.FakeGraphMail()
    f.add("m1", "2026-10-17T07:12:03Z", "Ana Lima", "ana@clinic.example", "Appointment confirmed", text="Hello.")
    f.add("m2", "2026-10-16T18:30:00Z", "Bruno Reis", "bruno@shop.example", "Your order", text="Order 77 shipped.", unread=True)
    yield f
    f.close()


def run(fake, *argv):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("OUTLOOK_", "MAILBOX_"))}
    done = subprocess.run([sys.executable, str(OUTLOOK), *argv], capture_output=True, text=True, timeout=120, env={**base, **fake.env()})
    return done.returncode, json.loads(done.stdout) if done.stdout.strip() else None, done.stdout + done.stderr


def test_outlook_unread_is_the_opposite_of_isread(fake):
    code, out, said = run(fake, "search", "--query", "in:inbox", "--since", "2026-10-01T00:00:00Z")
    assert code == 0, said
    assert {m["id"]: m["unread"] for m in out["messages"]} == {"m1": False, "m2": True}
    code, one, said = run(fake, "get", "--id", "m2")
    assert code == 0 and one["unread"] is True, said


def test_outlook_asks_for_isread_in_the_select_and_still_not_for_a_header_block(fake):
    run(fake, "search", "--query", "in:inbox", "--since", "2026-10-01T00:00:00Z")
    select = fake.api_requests()[0]["query"]["$select"].split(",")
    assert "isRead" in select and "internetMessageHeaders" not in select


def test_outlook_a_message_with_no_isread_has_unread_null_never_false(fake):
    del fake.messages["m1"]["isRead"]
    fake.messages["m2"]["isRead"] = "false"       # not a boolean: not understood, so not known
    code, out, said = run(fake, "search", "--query", "in:inbox", "--since", "2026-10-01T00:00:00Z")
    assert code == 0, said
    assert {m["id"]: m["unread"] for m in out["messages"]} == {"m1": None, "m2": None}


def test_outlook_normalize_in_isolation():
    base = {"id": "m1", "receivedDateTime": "2026-10-17T07:12:03Z", "subject": "Hi", "body": {"contentType": "text", "content": "x"}}
    assert outlook.normalize({**base, "isRead": False})["unread"] is True
    assert outlook.normalize({**base, "isRead": True})["unread"] is False
    assert outlook.normalize(base)["unread"] is None
    assert outlook.normalize({**base, "isRead": 0})["unread"] is None


def test_outlook_flag_is_vacuous_if_the_select_drops_isread(fake, monkeypatch):
    """The oracle: without `isRead` in the select the service sends none, and every message is null, so the test above does bite."""
    monkeypatch.setattr(outlook, "MESSAGE_FIELDS", outlook.MESSAGE_FIELDS.replace(",isRead", ""))
    assert "isRead" not in outlook.select_fields(())
    answered = fake.shown(fake.messages["m2"], outlook.select_fields(()))
    assert "isRead" not in answered and outlook.normalize(answered)["unread"] is None
