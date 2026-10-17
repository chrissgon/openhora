"""Offline tests of two additions to providers/mailbox/gmail.py (class reader:email): `--own-words`, which cuts the quoted history of a
reply from "text", and `attachments`, the name, declared type and size of each attached file read from MIME headers only. Also the move of
`strip_quoted` to providers/_email_text.py: the e-mail channel (providers/messenger/email-imap.py) and the Gmail reader cut a reply with the
same function. No network, no credential, `.example` addresses.

Run: uv run --with pytest pytest providers/mailbox/tests/test_gmail_own_words.py
"""
from __future__ import annotations

import base64
import email.message
import importlib.util
import json
import os
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
SCRIPT = HERE.parent / "gmail.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gmail = load(SCRIPT, "gmail_own_words_under_test")

FORMS = [
    "On Fri, Oct 16, 2026 at 5:00 PM Assistant <assistant@office.example> wrote:",
    "On Fri, Oct 16, 2026 at 5:00 PM Assistant <assistant@office.example>\nwrote:",       # wrapped over two lines
    "On 16/10/2026 17:00, Assistant wrote:",
    "-----Original Message-----",
    "Begin forwarded message:",
    "---------- Forwarded message ---------",
    "________________________________\nFrom: Assistant <assistant@office.example>\nSent: Friday, October 16, 2026 5:00 PM\nTo: Owner\nSubject: card",
    "From: Assistant <assistant@office.example>\nDate: Friday, October 16, 2026\nTo: Owner\nSubject: card",
    "Em sex., 16 de out. de 2026 às 17:00, Assistant <assistant@office.example> escreveu:",      # validate: allow english-only -- an attribution of a Portuguese mail client, a form the cut must know
    "Em 16/10/2026 17:00, Assistant escreveu:",      # validate: allow english-only -- an attribution of a Portuguese mail client
    "-----Mensagem original-----",      # validate: allow english-only -- the original-message marker of a Portuguese mail client
    "---------- Mensagem encaminhada ---------",      # validate: allow english-only -- the forward marker of a Portuguese mail client
    "De: Assistant <assistant@office.example>\nEnviado: sexta-feira, 16 de outubro de 2026 17:00\nPara: Owner\nAssunto: card",      # validate: allow english-only -- an Outlook header block in Portuguese
    "El vie, 16 oct 2026 a las 17:00, Assistant <assistant@office.example> escribió:",      # validate: allow english-only -- an attribution of a Spanish mail client
    "El 16/10/2026 17:00, Assistant escribio:",      # validate: allow english-only -- an attribution of a Spanish mail client without the accent
    "-----Mensaje original-----",      # validate: allow english-only -- the original-message marker of a Spanish mail client
    "---------- Mensaje reenviado ---------",      # validate: allow english-only -- the forward marker of a Spanish mail client
    "De: Assistant <assistant@office.example>\nEnviado el: viernes, 16 de octubre de 2026\nPara: Owner\nAsunto: card",      # validate: allow english-only -- an Outlook header block in Spanish
    "> an old quoted line",
    "-- \nA. Signature",
]


def plain(text: str, **headers) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Sam Placeholder <sam@sender.example>"
    msg["To"] = "alex.sample@example.com"
    msg["Subject"] = "Re: appointment"
    for key, value in headers.items():
        msg[key.replace("_", "-")] = value
    msg.set_content(text)
    return msg.as_bytes()


# --- strip_quoted moved: one function for the channel and the reader --------------------------------------------------------


def test_strip_quoted_lives_in_the_shared_text_module_and_the_channel_uses_that_one():
    shared = (PROVIDERS / "_email_text.py").resolve()
    imap = load(PROVIDERS / "messenger" / "email-imap.py", "email_imap_for_the_own_words_test")
    for function in (gmail.strip_quoted, imap.strip_quoted):      # the function is defined in the shared file, not copied
        assert Path(function.__code__.co_filename).resolve() == shared
    source = (PROVIDERS / "messenger" / "email-imap.py").read_text(encoding="utf-8")
    assert "def strip_quoted" not in source and "ATTRIBUTION = " not in source and "MARKERS = " not in source
    sample = "Fine.\n\nOn Fri, Oct 16, 2026, Assistant wrote:\n> old"
    assert imap.strip_quoted(sample) == gmail.strip_quoted(sample) == "Fine."


@pytest.mark.parametrize("marker", FORMS)
def test_each_attribution_and_forward_form_is_cut_by_the_shared_function(marker):
    text = f"Please send it.\n\n{marker}\nthe whole old card follows"
    assert gmail.strip_quoted(text) == "Please send it."
    assert gmail.strip_quoted("Plain words\nand a second line\n") == "Plain words\nand a second line"
    assert gmail.strip_quoted(f"{marker}\nold history") == "", "a message that is all history has no words of its own"


# --- --own-words on the Gmail reader ------------------------------------------------------------------------------------


@pytest.mark.parametrize("marker", FORMS)
def test_own_words_cuts_every_form_and_without_the_flag_the_text_is_whole(marker):
    raw = plain(f"Please send it.\n\n{marker}\nthe whole old card follows")
    whole = gmail.normalize(raw, source="eml")
    own = gmail.normalize(raw, source="eml", own_words=True)
    assert "the whole old card follows" in whole["text"], "without --own-words nothing changed"
    assert own["text"] == "Please send it."
    assert own["external_content"] is True and own["subject"] == "Re: appointment"


def test_own_words_works_on_the_text_of_an_html_only_reply():
    msg = EmailMessage()
    msg["From"] = "sam@sender.example"
    msg["Subject"] = "Re: card"
    msg.set_content("<html><body><div>Yes, go ahead.</div><div>On Fri, Oct 16, 2026, Assistant wrote:</div>"
                    "<blockquote>old words</blockquote></body></html>", subtype="html")
    assert gmail.normalize(msg.as_bytes(), source="eml", own_words=True)["text"] == "Yes, go ahead."


def test_the_flag_is_read_by_search_get_and_read_eml_and_nothing_else(tmp_path, monkeypatch, capsys):
    eml = tmp_path / "reply.eml"
    eml.write_bytes(plain("Fine.\n\nOn Fri, Oct 16, 2026, Assistant wrote:\n> old"))
    run = lambda *argv: subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60,  # noqa: E731
                                       env={**os.environ, "GMAIL_API_BASE": "", "GOOGLE_TOKEN_URL": ""})
    done = run("read-eml", "--file", str(eml), "--own-words")
    assert done.returncode == 0 and json.loads(done.stdout)["text"] == "Fine."
    assert "old" in json.loads(run("read-eml", "--file", str(eml)).stdout)["text"]
    assert run("--check", "--own-words").returncode == 2, "--check takes no flag"
    assert gmail.VERB_FLAGS["search"] >= {"own_words"} and gmail.VERB_FLAGS["get"] >= {"own_words"} and "own_words" in gmail.VERB_FLAGS["read-eml"]
    assert "own_words" not in gmail.VERB_FLAGS[None]
    # search and get pass it on to every message they fetch.
    seen = []

    class Client:
        def list_ids(self, query, limit):
            return ["m1", "m2"], False

        def message(self, message_id, prefixes=(), own_words=False):
            seen.append((message_id, own_words))
            return {"id": message_id, "received_at": "2026-10-17T10:00:00Z", "text": "x"}

    monkeypatch.setattr(gmail, "connect", lambda: (Client(), None, None))
    assert gmail.main(["search", "--query", "in:inbox", "--own-words", "--jobs", "1"]) == 0
    assert gmail.main(["get", "--id", "m3", "--own-words"]) == 0
    assert gmail.main(["get", "--id", "m4"]) == 0
    assert seen == [("m1", True), ("m2", True), ("m3", True), ("m4", False)]
    capsys.readouterr()


def test_gmail_message_passes_own_words_to_the_normalizer():
    raw = plain("Mine.\n\n> theirs")
    client = gmail.Gmail("http://127.0.0.1:1", "t")
    client.get = lambda path, params=None: {"id": "m1", "threadId": "t1", "internalDate": "1792000000000",
                                            "raw": base64.urlsafe_b64encode(raw).decode()}
    assert client.message("m1", (), True)["text"] == "Mine."
    assert "theirs" in client.message("m1")["text"]


# --- attachments --------------------------------------------------------------------------------------------------------


def with_attachments() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Ana Lima <ana@clinic.example>"
    msg["To"] = "alex.sample@example.com"
    msg["Subject"] = "Appointment confirmed"
    msg.set_content("Your invoice is attached.")
    msg.add_attachment(b"%PDF-1.4 " + b"x" * 291, maintype="application", subtype="pdf", filename="invoice.pdf")
    msg.add_attachment("a,b\n1,2\n", subtype="csv", filename="rows.csv")
    msg.add_attachment(b"\x89PNG" + b"y" * 96, maintype="image", subtype="png", filename="logo.png", disposition="inline", cid="<logo@clinic.example>")
    msg.add_attachment(b"zip-bytes", maintype="application", subtype="zip")    # no file name
    msg.add_attachment(b"bell", maintype="application", subtype="octet-stream", filename="odd\x07name\u202e\nline.exe")
    inner = EmailMessage()
    inner["Subject"] = "Forwarded note"
    inner.set_content("inner body that must not become an attachment")
    msg.add_attachment(inner)
    return msg.as_bytes()


def test_attachments_are_listed_with_name_declared_type_and_size_and_inline_parts_are_not():
    out = gmail.normalize(with_attachments(), source="eml")
    assert out["attachments"] == [
        {"name": "invoice.pdf", "type": "application/pdf", "size": 300},
        {"name": "rows.csv", "type": "text/csv", "size": out["attachments"][1]["size"]},
        {"name": None, "type": "application/zip", "size": 9},
        {"name": "odd name line.exe", "type": "application/octet-stream", "size": 4},
        {"name": None, "type": "message/rfc822", "size": None},
    ]
    assert isinstance(out["attachments"][1]["size"], int) and out["attachments"][1]["size"] > 0
    assert "\u202e" not in json.dumps(out, ensure_ascii=False) and "\x07" not in json.dumps(out)
    assert out["text"].strip() == "Your invoice is attached.", "an attachment is not message text"
    assert "inner body" not in json.dumps(out), "an attached message is listed whole, never entered"


def test_a_message_without_attachments_has_an_empty_list_and_an_eml_without_parts_too():
    assert gmail.normalize(plain("hello"), source="eml")["attachments"] == []
    fixture = (HERE / "fixtures" / "comment-notification.eml").read_bytes()
    assert gmail.normalize(fixture, source="eml")["attachments"] == []


def test_the_list_is_capped_and_a_name_is_cut():
    msg = EmailMessage()
    msg["From"] = "ana@clinic.example"
    msg.set_content("many files")
    for i in range(gmail.MAX_ATTACHMENTS + 7):
        msg.add_attachment(b"x", maintype="application", subtype="octet-stream", filename=f"f{i}-" + "n" * 400)
    out = gmail.normalize(msg.as_bytes(), source="eml")
    assert len(out["attachments"]) == gmail.MAX_ATTACHMENTS
    assert all(len(a["name"]) == gmail.ATTACHMENT_NAME_LIMIT for a in out["attachments"])


def test_no_attachment_part_is_decoded_or_read_as_content(monkeypatch):
    """The sender's bytes are never turned into content: the listing reads headers and the length of the encoded text only. A bomb of a
    base64 part must cost nothing, so the test fails on any decode of a part that is an attachment."""
    decoded, content = [], []
    real_payload, real_content = email.message.Message.get_payload, email.message.MIMEPart.get_content

    def spy_payload(self, i=None, decode=False):
        if decode:
            decoded.append(self.get_content_type())
        return real_payload(self, i, decode)

    def spy_content(self, *args, **kwargs):
        content.append(self.get_content_type())
        return real_content(self, *args, **kwargs)

    monkeypatch.setattr(email.message.Message, "get_payload", spy_payload)
    monkeypatch.setattr(email.message.MIMEPart, "get_content", spy_content)
    out = gmail.normalize(with_attachments(), source="eml")
    assert len(out["attachments"]) == 5
    attached = {"application/pdf", "text/csv", "image/png", "application/zip", "application/octet-stream", "message/rfc822"}
    assert not attached & set(decoded), f"decoded: {decoded}"
    assert not attached & set(content), f"read as content: {content}"
    assert content == ["text/plain"], "only the body of the message was read as text"


def test_the_size_of_a_base64_part_is_exact_without_decoding_it():
    for n in (0, 1, 2, 3, 100, 4097):
        msg = EmailMessage()
        msg["From"] = "ana@clinic.example"
        msg.set_content("x")
        msg.add_attachment(b"z" * n, maintype="application", subtype="octet-stream", filename="blob.bin")
        assert gmail.normalize(msg.as_bytes(), source="eml")["attachments"][0]["size"] == n, n
