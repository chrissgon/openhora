"""Tests of providers/messenger/email-imap.py (class messenger:email, platform email) against a fake IMAP inbox and a fake SMTP server on loopback
(providers/messenger/tests/email_kit.py and providers/mailer/tests/fake_mail.py): no real mail service, no credential, `.example` addresses,
fictional people. They hold the rules of the channel: a sender is admitted only by the receiving server's own authentication result for the
From domain; a message that is not private, or automatic, or a forged one, is dropped with no reply; only the sender's own words reach the
bridge (quoted history, HTML-hidden text and signatures never do); the mailbox is never changed; a card is one plain-text message to one
address, with a random Message-ID that a reply must name.

Run: uv run --python 3.9 --with pytest==9.1.1 pytest providers/messenger/tests/test_messenger_email.py
"""
from __future__ import annotations

import email
import email.policy
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
PROVIDERS = HERE.parents[2]
ROOT = PROVIDERS.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


provider = load("messenger_email_under_test", PROVIDERS / "messenger" / "email-imap.py")
mail = load("providers_email", PROVIDERS / "_email.py")
fake_mail = load("fake_mail_for_channel_tests", PROVIDERS / "mailer" / "tests" / "fake_mail.py")
email_kit = load("email_kit_for_channel_tests", HERE.parent / "email_kit.py")
inbound = load("messaging_inbound_for_channel_tests", ROOT / "runtime" / "messaging_inbound.py")

PASSWORD = "app-password-x"  # security-scan: allow secret-assignment -- a made-up password for a fake server on loopback; no real account has it
OWN = "assistant@office.example"
OWNER = "owner@office.example"
ID = "mx.office.example"
GOOD = f"{ID}; dkim=pass header.d=office.example header.s=sel1; dmarc=pass (p=quarantine) header.from=office.example"
SENT = "<oh.0123456789abcdef0123456789abcdef@office.example>"


def raw(text="/approve 12", sender=OWNER, to=OWN, auth=GOOD, above=(), below=(), extra=(), html=None, subject="Re: card", cc=None,
        in_reply_to=None, body_type="plain"):
    """A message as the receiving server stores it: the server's own trace headers on top (the Authentication-Results first), then what the
    sender wrote. `above` goes before the server's header, `below` right after it, `extra` among the sender's own headers."""
    head = [*above]
    if auth is not None:
        head.append(f"Authentication-Results: {auth}")
    head += [*below, "Received: from mail.office.example by mx.office.example; Sat, 17 Oct 2026 09:00:00 +0000",
             f"From: {sender}", f"To: {to}", f"Subject: {subject}", "Date: Sat, 17 Oct 2026 08:59:00 +0000",
             "Message-ID: <inbound-1@office.example>", "MIME-Version: 1.0"]
    if cc:
        head.append(f"Cc: {cc}")
    if in_reply_to:
        head.append(f"In-Reply-To: {in_reply_to}")
    head += [*extra]
    if html is not None:
        head += ["Content-Type: text/html; charset=utf-8", "Content-Transfer-Encoding: 8bit"]
        body = html
    else:
        head += [f"Content-Type: text/{body_type}; charset=utf-8", "Content-Transfer-Encoding: 8bit"]
        body = text
    return ("\r\n".join(head) + "\r\n\r\n" + body + "\r\n").encode("utf-8")


def admit(data, sent=()):
    return provider.inspect_message(data, OWN, ID, lambda chat: set(sent), mail)


def dropped(data, why, sent=()):
    update, found = admit(data, sent)
    assert update is None and found == why, (update, found)


# --- the sender: only the receiving server's own result admits ---------------------------------------------------------------------


def test_an_authenticated_private_message_is_an_update_with_the_sender_as_chat_and_no_action():
    update, why = admit(raw())
    assert why is None
    assert update == {"sender": OWNER, "chat": OWNER, "private": True, "text": "/approve 12", "action": None, "action_ref": None,
                      "reply_to": None}


def test_the_sender_is_the_from_address_lower_cased_with_the_domain_in_ascii_and_no_plus_or_dot_folding():
    update, _ = admit(raw(sender="Owner.Name+Tag@Office.Example"))
    assert update["sender"] == update["chat"] == "owner.name+tag@office.example"


@pytest.mark.parametrize("auth", [
    None,                                                                                  # the server writes none
    "other.example; dkim=pass header.d=office.example; dmarc=pass header.from=office.example",       # another server's id
    f"{ID}; dkim=pass header.d=office.example; dmarc=fail header.from=office.example",
    f"{ID}; dkim=pass header.d=office.example; dmarc=temperror header.from=office.example",
    f"{ID}; dkim=pass header.d=office.example; dmarc=permerror",
    f"{ID}; dmarc=pass header.from=evil.example",                                            # DMARC passed for another domain
    f"{ID}; spf=pass smtp.mailfrom=office.example",                                          # SPF alone never admits
    f"{ID}; spf=pass smtp.mailfrom=office.example; dmarc=none",
    f"{ID}; dkim=pass header.d=evil.example; dmarc=none",                                    # dmarc=none, header.d not the From domain
    f"{ID}; dkim=pass header.d=mail.office.example; dmarc=none",                              # a subdomain is not the domain
    f"{ID}; dkim=pass header.d=office.example.evil.example",
    f"{ID}; dkim=fail header.d=office.example; dmarc=none",
    f"{ID}; dkim=neutral header.d=office.example",
    f"{ID}; none",
    f"{ID}",
    "",
    f"{ID}; dmarc=pass",                                                                       # a pass that names no header.from vouches for nothing
    f"{ID}; dmarc=pass header.from=office.example; dmarc=none",                                  # a second DMARC result
    f"{ID}; dkim=pass header.d=office.example; dmarc=pass header.from=office.example) smtp.mailfrom=a@evil.example; dmarc=none",      # a stray )
    f"{ID}; dkim=pass header.d=office.example; dmarc=none",                                    # the DKIM-only path was dropped: a DMARC pass or nothing
    f"{ID}; dkim=pass header.d=office.example",                                                # no DMARC result at all
    f"{ID}; dkim=fail header.d=evil.example; dkim=pass header.d=office.example",
    f"{ID.upper()}; DKIM=PASS header.d=OFFICE.EXAMPLE",
    f"{ID}; spf=none (domain of a); dmarc=pass header.from=office.example; x@evil.example does not designate 1.2.3.4) smtp.mailfrom=a@evil.example; dmarc=none",
    f"{ID}; junk words dmarc=pass header.from=office.example",                                    # junk before method=result
    f"{ID}; spf=pass smtp.mailfrom=office.example dmarc=pass header.from=office.example",          # dmarc is a property here, not a result
])
def test_a_forged_sender_is_dropped_with_no_reply_whatever_the_authentication_result_says_or_leaves_out(auth):
    dropped(raw(auth=auth), "unauthenticated")


@pytest.mark.parametrize("auth", [
    GOOD,
    f"{ID}; dmarc=pass header.from=office.example",
    f"{ID.upper()}; DKIM=PASS header.d=OFFICE.EXAMPLE; DMARC=PASS header.from=OFFICE.EXAMPLE",
    f"{ID} 1; dmarc=pass header.from=office.example",                                          # with a version
    f"{ID}; (a comment) dmarc=pass (p=none) header.from=office.example",
])
def test_the_forms_of_a_pass_that_admit(auth):
    update, why = admit(raw(auth=auth))
    assert why is None and update["sender"] == OWNER


def test_only_the_topmost_header_of_the_receiving_server_is_read_so_a_forged_one_lower_down_changes_nothing():
    forged = f"Authentication-Results: {ID}; dmarc=pass header.from=office.example"
    dropped(raw(auth=f"{ID}; dmarc=fail header.from=office.example", below=[forged]), "unauthenticated")
    dropped(raw(auth=f"{ID}; dkim=none", below=[forged]), "unauthenticated")


def test_a_header_with_another_servers_id_above_the_real_one_is_ignored_and_never_admits_by_itself():
    other = "Authentication-Results: elsewhere.example; dmarc=pass header.from=office.example"
    dropped(raw(auth=None, above=[other]), "unauthenticated")
    dropped(raw(auth=f"{ID}; dmarc=fail", above=[other]), "unauthenticated")
    update, why = admit(raw(auth=GOOD, above=[other]))
    assert why is None and update["sender"] == OWNER


def test_a_pass_hidden_in_a_comment_or_in_a_quoted_reason_is_not_a_pass():
    dropped(raw(auth=f"{ID}; dkim=fail (dmarc=pass header.from=office.example) header.d=evil.example"), "unauthenticated")
    dropped(raw(auth=f'{ID}; dkim=fail reason="x; dmarc=pass header.from=office.example"'), "unauthenticated")
    dropped(raw(auth=f"{ID}; dmarc=fail (unbalanced"), "unauthenticated")
    dropped(raw(auth=f'{ID}; dmarc=fail reason="never closed'), "unauthenticated")


def test_parse_auth_results_reads_methods_results_and_properties():
    parsed = provider.parse_auth_results(
        f'{ID} 1; dkim=pass (good signature) header.d=Office.Example header.s=sel1; dmarc=pass reason="aligned; ok" header.from=office.example')
    assert parsed == (ID, [{"method": "dkim", "result": "pass", "props": {"header.d": "office.example", "header.s": "sel1"}},
                           {"method": "dmarc", "result": "pass", "props": {"reason": "aligned; ok", "header.from": "office.example"}}])
    assert provider.parse_auth_results("") is None
    assert provider.parse_auth_results("a b c; dkim=pass") is None


@pytest.mark.parametrize("sender", [
    "owner@office.example, other@office.example",                       # two addresses
    "Team: owner@office.example;",                                       # a group
    "undisclosed-recipients:;",
    "=?utf-8?q?owner=40office=2Eexample?=",                              # an address written as an encoded word
    "owner=?utf-8?q?@evil.example?=",
    '"owner@office.example"@evil.example',
    "owner@office.example\u202e",
    "",
])
def test_a_from_that_is_not_one_plain_address_is_dropped(sender):
    update, why = admit(raw(sender=sender))
    assert update is None and why in ("sender", "unparsable")


def test_two_from_headers_or_none_are_dropped():
    data = raw()
    dropped(data.replace(b"From: " + OWNER.encode(), b"From: " + OWNER.encode() + b"\r\nFrom: other@office.example", 1), "sender")
    dropped(data.replace(b"From: " + OWNER.encode() + b"\r\n", b"", 1), "sender")


def test_an_encoded_word_in_the_display_name_never_becomes_the_sender():
    # the display name claims the owner's address; the address in the angle brackets is the one that counts, and the server vouched for none
    # but its own domain
    forged = '=?utf-8?q?owner=40office=2Eexample?= <attacker@evil.example>'
    dropped(raw(sender=forged), "unauthenticated")
    update, why = admit(raw(sender=forged, auth=f"{ID}; dmarc=pass header.from=evil.example"))
    assert why is None and update["sender"] == "attacker@evil.example"


def test_an_encoded_subject_with_a_line_break_is_never_read_and_makes_no_header():
    update, why = admit(raw(subject="=?utf-8?q?hello=0D=0ABcc=3A_evil=40evil=2Eexample?="))
    assert why is None and "evil" not in json.dumps(update)


def test_a_sender_header_that_differs_and_any_resent_header_are_dropped():
    dropped(raw(extra=["Sender: other@office.example"]), "sender")
    dropped(raw(extra=["Sender: list-service@evil.example"]), "sender")
    dropped(raw(extra=["Resent-From: other@office.example"]), "sender")
    dropped(raw(extra=["Resent-To: other@office.example"]), "sender")
    update, why = admit(raw(extra=[f"Sender: {OWNER.upper()}"]))
    assert why is None


def test_a_message_from_the_mailboxs_own_address_is_dropped():
    dropped(raw(sender=OWN, auth=GOOD.replace("office.example", "office.example")), "self")


@pytest.mark.parametrize("to,cc", [
    (f"{OWN}, other@office.example", None),
    (f"{OWN}", "other@office.example"),
    ("other@office.example", OWN),
    ("other@office.example", None),
    ("Team: " + OWN + ";", None) if False else (f"{OWN}, {OWN.replace('assistant', 'second')}", None),
    ("undisclosed-recipients:;", None),
])
def test_a_message_that_is_not_private_is_dropped(to, cc):
    dropped(raw(to=to, cc=cc), "not-private")


def test_the_mailbox_address_alone_in_to_is_private_with_a_display_name_and_in_any_case():
    update, why = admit(raw(to=f"Assistant <{OWN.upper()}>"))
    assert why is None


@pytest.mark.parametrize("extra", [
    ["Auto-Submitted: auto-replied"], ["Auto-Submitted: auto-generated"], ["Auto-Submitted: auto-notified"],
    ["Precedence: bulk"], ["Precedence: list"], ["Precedence: junk"], ["Precedence: auto_reply"],
    ["List-Id: <news.office.example>"], ["List-Unsubscribe: <mailto:out@office.example>"],
    ["Return-Path: <>"], ["Content-Type: multipart/report; report-type=delivery-status; boundary=x"],
])
def test_automatic_and_bulk_messages_are_dropped(extra):
    data = raw(extra=extra)
    if extra[0].startswith("Content-Type"):
        data = data.replace(b"Content-Type: text/plain", b"X-Was: text/plain")
    dropped(data, "automatic")


def test_auto_submitted_no_is_an_ordinary_message():
    update, why = admit(raw(extra=["Auto-Submitted: no"]))
    assert why is None


def test_a_message_over_one_mebibyte_is_dropped_before_anything_is_read():
    big = raw(text="x" * (1 << 20))
    assert len(big) > provider.MAX_SIZE
    dropped(big, "size")


def test_a_message_the_parser_cannot_read_admits_nothing_and_does_not_raise():
    update, why = admit(b"\x00\xff\xfe not a message")
    assert update is None and why in ("sender", "unparsable")


def test_reply_to_is_the_in_reply_to_only_when_it_is_a_message_id_sent_to_that_chat():
    update, _ = admit(raw(in_reply_to=SENT), sent=[SENT])
    assert update["reply_to"] == SENT
    update, _ = admit(raw(in_reply_to=SENT), sent=[])
    assert update["reply_to"] is None
    update, _ = admit(raw(in_reply_to="<other@evil.example>"), sent=[SENT])
    assert update["reply_to"] is None
    seen = []
    provider.inspect_message(raw(in_reply_to=SENT), OWN, ID, lambda chat: seen.append(chat) or {SENT}, mail)
    assert seen == [OWNER]      # looked up for the sender's own chat only


# --- the text: only the sender's own words -----------------------------------------------------------------------------------------


def text_of(text, **kw):
    update, why = admit(raw(text=text, **kw))
    assert why is None, why
    return update["text"]


def test_a_signature_delimiter_and_a_quoted_line_cut_the_message():
    assert text_of("Yes, go ahead.\n\n-- \nA. Owner\nOffice") == "Yes, go ahead."
    assert text_of("Yes, go ahead.\n--\nA. Owner") == "Yes, go ahead."
    assert text_of("Yes, go ahead.\n\n> /approve 12\n> thanks") == "Yes, go ahead."


def test_an_old_quoted_approve_is_never_the_text_so_it_is_never_an_act():
    dropped(raw(text="> /approve 12\n"), "empty")
    dropped(raw(text="\n> /approve 12\n>\n> and the rest"), "empty")
    assert text_of("Not yet.\n\nOn Fri, Oct 16, 2026 at 5:00 PM Assistant <assistant@office.example> wrote:\n> /approve 12\n") == "Not yet."


@pytest.mark.parametrize("marker", [
    "On Fri, Oct 16, 2026 at 5:00 PM Assistant <assistant@office.example> wrote:",
    "On Fri, Oct 16, 2026 at 5:00 PM Assistant <assistant@office.example>\nwrote:",       # wrapped over two lines
    "On 16/10/2026 17:00, Assistant wrote:",
    "-----Original Message-----",
    "Begin forwarded message:",
    "---------- Forwarded message ---------",
    "________________________________\nFrom: Assistant <assistant@office.example>\nSent: Friday, October 16, 2026 5:00 PM\nTo: Owner\nSubject: card",
    "From: Assistant <assistant@office.example>\nDate: Friday, October 16, 2026\nTo: Owner\nSubject: card",
    "Em sex., 16 de out. de 2026 às 17:00, Assistant <assistant@office.example> escreveu:",      # validate: allow english-only -- an attribution of a Portuguese mail client, a closed-list form the channel must cut
    "Em 16/10/2026 17:00, Assistant escreveu:",      # validate: allow english-only -- an attribution of a Portuguese mail client
    "-----Mensagem original-----",      # validate: allow english-only -- the original-message marker of a Portuguese mail client
    "---------- Mensagem encaminhada ---------",      # validate: allow english-only -- the forward marker of a Portuguese mail client
    "De: Assistant <assistant@office.example>\nEnviado: sexta-feira, 16 de outubro de 2026 17:00\nPara: Owner\nAssunto: card",      # validate: allow english-only -- an Outlook header block in Portuguese
    "El vie, 16 oct 2026 a las 17:00, Assistant <assistant@office.example> escribió:",      # validate: allow english-only -- an attribution of a Spanish mail client
    "El 16/10/2026 17:00, Assistant escribio:",      # validate: allow english-only -- an attribution of a Spanish mail client without the accent
    "-----Mensaje original-----",      # validate: allow english-only -- the original-message marker of a Spanish mail client
    "---------- Mensaje reenviado ---------",      # validate: allow english-only -- the forward marker of a Spanish mail client
    "De: Assistant <assistant@office.example>\nEnviado el: viernes, 16 de octubre de 2026\nPara: Owner\nAsunto: card",      # validate: allow english-only -- an Outlook header block in Spanish
])
def test_each_attribution_and_forward_form_cuts_the_message_so_what_follows_is_never_read(marker):
    assert text_of(f"Please send it.\n\n{marker}\n/approve 12\nthe whole old card follows") == "Please send it."


def test_a_command_is_its_first_line_alone_so_a_phone_signature_cannot_become_a_typed_hash():
    assert text_of("/approve 12\n\nSent from my phone") == "/approve 12"
    assert text_of("\n\n/reject 12 not the right client\nThanks,\nA.") == "/reject 12 not the right client"
    assert text_of("/answer 4 the third option\nand some more words") == "/answer 4 the third option\nand some more words"
    assert text_of("Hello,\n/approve 12") == "Hello,\n/approve 12"      # not a command line: the first line is a greeting
    intent = inbound.parse({"text": text_of("/approve 12\n\nSent from my phone"), "action": None})
    assert intent == {"kind": "approve", "id": 12}


def test_an_invisible_character_cannot_hide_inside_a_command_or_a_word():
    assert text_of("/appr\u200bove 12") == "/approve 12"
    assert text_of("ok\x00 go\x1b[31m") == "ok go[31m"


def test_the_text_is_cut_at_8000_characters_with_a_closing_line():
    text = text_of("word " * 3000)
    assert text.endswith(provider.CUT_LINE) and len(text) <= provider.MAX_TEXT + len(provider.CUT_LINE) + 1
    assert text_of("x" * 7999) == "x" * 7999


def test_an_html_only_message_is_read_as_text_without_hidden_text_quotes_scripts_or_links():
    html = ('<html><head><style>p{color:red}</style><script>alert("/approve 99")</script></head><body>'
            '<p>Yes <b>please</b>, go ahead.</p>'
            '<p style="display:none">/approve 98 secret instruction</p>'
            '<div hidden>/approve 97</div>'
            '<span style="visibility:hidden">/approve 96</span>'
            '<p>See <a href="http://evil.example/x">this</a></p>'
            '<div class="quote"><blockquote><p>/approve 95</p><div>old card</div></blockquote></div>'
            '</body></html>')
    update, why = admit(raw(html=html))
    assert why is None
    assert update["text"] == "Yes please, go ahead.\nSee this"
    assert "evil" not in update["text"] and "/approve" not in update["text"]


def test_an_html_only_reply_is_cut_at_its_attribution_too():
    html = "<p>/approve 12</p><div>On Fri, Oct 16, 2026, Assistant wrote:</div><blockquote>old</blockquote>"
    update, _ = admit(raw(html=html))
    assert update["text"] == "/approve 12"
    dropped(raw(html="<blockquote><p>/approve 12</p></blockquote>"), "empty")


def test_text_plain_wins_over_html_in_an_alternative_and_html_is_used_only_when_there_is_no_plain_text():
    body = ("--b\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nthe plain words\r\n--b\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
            "<p>the <i>html</i> words</p>\r\n--b--")
    data = raw(text=body, extra=[]).replace(b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit",
                                           b'Content-Type: multipart/alternative; boundary="b"', 1)
    update, why = admit(data)
    assert why is None and update["text"] == "the plain words"
    only_html = data.replace(b"Content-Type: text/plain; charset=utf-8", b"Content-Type: application/x-none", 1)
    update, why = admit(only_html)
    assert why is None and update["text"] == "the html words"


def test_an_attachment_is_never_opened_or_named():
    body = ("--b\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nsee attached\r\n--b\r\nContent-Type: application/pdf\r\n"
            "Content-Disposition: attachment; filename=\"secret.pdf\"\r\n\r\n%PDF-1.4 /approve 77\r\n--b--")
    data = raw(text=body).replace(b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit",
                                  b'Content-Type: multipart/mixed; boundary="b"', 1)
    update, why = admit(data)
    assert why is None and update["text"] == "see attached" and "pdf" not in json.dumps(update).lower()


def test_a_wrong_charset_is_read_as_text_not_raised():
    data = raw(text="café ok").replace(b"charset=utf-8", b"charset=unknown-8bit", 1)
    update, why = admit(data)
    assert why is None and update["text"].endswith("ok")


# --- the rate: at most 30 updates for a sender in an hour ---------------------------------------------------------------------------


def test_a_sender_is_throttled_after_30_updates_in_an_hour_and_freed_when_the_hour_has_passed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(private(tmp_path / "s")))
    now = [1000.0]
    listener = provider.Listener(settings_for(), PASSWORD, out=provider.Out(io.BytesIO()), stdin=io.BytesIO(), clock=lambda: now[0])
    assert [listener.throttled("a@x.example") for _ in range(30)] == [False] * 30
    assert listener.throttled("a@x.example") is True
    assert listener.throttled("b@x.example") is False       # another sender has its own count
    now[0] += provider.PER_WINDOW + 1
    assert listener.throttled("a@x.example") is False


# --- a card in: one plain-text message to one address ------------------------------------------------------------------------------


def private(path):
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def settings_for(smtp_port=1, imap_port=1, **over):
    found = {"address": OWN, "username": None, "imap_host": "127.0.0.1", "imap_port": imap_port, "imap_security": "plain",
             "smtp_host": "127.0.0.1", "smtp_port": smtp_port, "smtp_security": "plain", "authserv_id": ID, "poll_seconds": 15}
    found.update(over)
    return found


@pytest.fixture
def world(tmp_path, monkeypatch):
    state = private(tmp_path / "state")
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.setenv("OPENHORA_MAIL_TEST_PLAIN", "1")
    monkeypatch.setenv("MESSENGER_EMAIL_PASSWORD", PASSWORD)
    monkeypatch.setenv("MESSENGER_EMAIL_TIMEOUT", "5")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    smtp, imap = fake_mail.FakeSmtp(PASSWORD), email_kit.FakeInbox(PASSWORD)
    yield {"smtp": smtp, "imap": imap, "tmp": tmp_path, "state": state / "messenger-email",
           "settings": settings_for(smtp.port, imap.port)}
    smtp.stop()
    imap.stop()


HASH = "ab12" * 16


FOOTER = ["Send /approve 12", f"Approving applies exactly the text above (sha256 {HASH})."]


def card(text=None, footer=None, **over):
    """A card as the bridge hands it to the provider on a platform that declares actions_need_reply: `footer` names the lines `text` ends with."""
    footer = FOOTER if footer is None else footer
    text = text if text is not None else "acme-office \u00b7 effect #12\n\nSend the invoice to the client.\n\n" + "\n".join(footer)
    found = {"text": text, "actions": [], "link": None, "document": None, **over}
    if footer:
        found["footer"] = footer
    return found


def send(world, chat=OWNER, message=None):
    ledger = provider.SentLedger(provider.folder())
    return provider.send_card(world["settings"], PASSWORD, mail, chat, message or card(), ledger), ledger


def parsed(raw_bytes):
    return email.message_from_bytes(raw_bytes, policy=email.policy.default)


def test_a_card_is_one_plain_text_message_to_the_chat_with_a_random_message_id_that_is_remembered(world):
    message_id, ledger = send(world)
    taken = world["smtp"].messages
    assert len(taken) == 1 and taken[0]["to"] == [OWNER] and taken[0]["from"] == OWN
    message = parsed(taken[0]["data"])
    assert message["To"] == OWNER and message["Cc"] is None and message["Bcc"] is None and message["From"] == OWN
    assert message["Message-ID"] == message_id and re.fullmatch(r"<oh\.[0-9a-f]{32}@office\.example>", message_id)
    assert message["Auto-Submitted"] == "auto-generated"
    assert message.get_content_type() == "text/plain" and not message.is_multipart() and message.get_content_charset() == "utf-8"
    assert message["Subject"] == "acme-office · effect #12"
    body = message.get_content()
    assert "Reply to this e-mail with: /approve 12" in body and "\nSend /approve 12" not in body
    assert "Send the invoice to the client." in body and f"sha256 {HASH}" in body
    assert ledger.ids(OWNER) == {message_id}
    assert json.loads((world["state"] / "sent.json").read_text())["chats"] == {OWNER: [message_id]}
    other, _ = send(world)
    assert other != message_id      # random, not derived from the text


def test_a_card_has_no_threading_header_and_no_html_part(world):
    send(world)
    message = parsed(world["smtp"].messages[0]["data"])
    assert message["In-Reply-To"] is None and message["References"] is None
    assert [part.get_content_type() for part in message.walk()] == ["text/plain"]


def test_a_link_becomes_a_line_and_only_an_http_address_is_taken(world):
    send(world, message=card(link={"label": "Open the page", "url": "https://page.example/p/1"}))
    assert "Open the page: https://page.example/p/1" in parsed(world["smtp"].messages[0]["data"]).get_content()
    for bad in ("javascript:alert(1)", "https://page.example/a b", "https://page.example/\r\nBcc: x@evil.example", "ftp://x.example/"):
        with pytest.raises(provider.ProviderError) as e:
            send(world, message=card(link={"label": "x", "url": bad}))
        assert e.value.code == provider.EXIT_USAGE
    assert len(world["smtp"].messages) == 1


@pytest.mark.parametrize("chat", [
    "owner@office.example\r\nBcc: spy@evil.example", "owner@office.example\nBcc: spy@evil.example", "Owner <owner@office.example>",
    "owner@office.example, spy@evil.example", "=?utf-8?q?owner=40office.example?=", "owner@@office.example", "", "owner",
    '"owner@office.example"@evil.example',
])
def test_a_chat_that_is_not_one_plain_address_is_refused_and_nothing_is_sent(world, chat):
    with pytest.raises(provider.ProviderError) as e:
        send(world, chat=chat)
    assert e.value.code == provider.EXIT_USAGE and world["smtp"].messages == [] and world["smtp"].connections == 0


def test_text_with_header_syntax_in_it_makes_no_header_and_no_extra_recipient(world):
    hostile = "x\r\nBcc: spy@evil.example\r\nTo: spy@evil.example\r\n\r\nbody\nSubject: =?utf-8?q?evil?= =?"
    send(world, message=card(text=hostile))
    taken = world["smtp"].messages[0]
    assert taken["to"] == [OWNER]
    message = parsed(taken["data"])
    assert message["Bcc"] is None and message.get_all("To") == [OWNER] and len(message.get_all("Subject")) == 1
    assert "\r" not in message["Subject"] and "\n" not in message["Subject"] and len(message["Subject"]) <= provider.SUBJECT_MAX
    head = taken["data"].split(b"\r\n\r\n", 1)[0]
    assert b"spy@evil.example" not in head


def test_the_subject_is_the_first_line_cut_to_78_characters_and_an_encoded_word_in_it_is_broken(world):
    send(world, message=card(text="=?utf-8?q?x?= " + "word " * 40))
    subject = parsed(world["smtp"].messages[0]["data"])["Subject"]
    assert len(subject) <= provider.SUBJECT_MAX and subject.startswith("= ?utf-8")


def test_a_message_beyond_the_capabilities_is_refused_with_nothing_sent(world):
    for message, word in ((card(actions=[{"id": "1:approve", "label": "Approve"}]), "buttons"),
                          (card(document={"name": "effect-12.txt", "text": "the whole text"}), "document"),
                          (card(text="x" * 8001), "8000"), (card(text="   "), "text"), ("text", "message")):
        with pytest.raises(provider.ProviderError) as e:
            send(world, message=message)
        assert e.value.code == provider.EXIT_USAGE
    assert world["smtp"].messages == [] and world["smtp"].connections == 0


def test_a_card_is_never_sent_to_the_mailboxs_own_address(world):
    with pytest.raises(provider.ProviderError) as e:
        send(world, chat=OWN.upper())
    assert e.value.code == provider.EXIT_USAGE and world["smtp"].messages == []


def test_a_refused_recipient_is_a_failed_send_that_is_tried_again_and_remembers_nothing(world):
    world["smtp"].refuse.add(OWNER)
    with pytest.raises(provider.ProviderError) as e:
        send(world)
    assert e.value.kind == "failed" and e.value.code == provider.EXIT_SERVICE
    assert not (world["state"] / "sent.json").exists()


def test_a_refused_smtp_login_is_not_configured_and_never_prints_the_password(world):
    world["settings"]["username"] = "someone-else"
    world["smtp"].user = "assistant@office.example"
    with pytest.raises(provider.ProviderError) as e:
        send(world)
    assert e.value.kind == "not-configured" and PASSWORD not in str(e.value)


def test_the_password_is_sent_only_after_tls_and_plain_needs_the_test_variable_and_a_loopback_host(world, monkeypatch):
    monkeypatch.delenv("OPENHORA_MAIL_TEST_PLAIN")
    with pytest.raises(provider.ProviderError) as e:
        send(world)
    assert e.value.code == provider.EXIT_USAGE and world["smtp"].logins == []
    monkeypatch.setenv("OPENHORA_MAIL_TEST_PLAIN", "1")
    with pytest.raises(mail.EmailError):
        mail.security_for("imap", "imap.office.example", 993, "plain")
    world["settings"]["smtp_host"] = "mail.office.example"
    with pytest.raises(provider.ProviderError) as e:
        send(world)
    assert world["smtp"].logins == []


# --- the capabilities and the command line -------------------------------------------------------------------------------------


def run_cli(capsys, *argv):
    code = provider.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_the_capabilities_declare_no_attachment_and_that_an_action_needs_a_reply():
    assert provider.CAPABILITIES == {"max_text": 8000, "buttons": False, "max_buttons": 0, "max_button_label": 0, "lists": False,
                                     "max_list_rows": 0, "url_buttons": False, "reply_context": True, "documents": False, "listen": True,
                                     "actions_need_reply": True}


STDLIB_FALLBACK = {"email", "json", "http", "smtplib", "imaplib", "ssl", "socket", "select", "queue", "logging", "string", "types", "signal",
                   "secrets", "random", "time", "re", "os", "sys", "io", "code", "token", "platform", "site", "ast", "copy", "csv", "html",
                   "xml", "uuid", "hashlib", "hmac", "base64", "struct", "tempfile", "shutil", "stat", "glob", "pickle", "sqlite3", "urllib",
                   "argparse", "getpass", "locale", "datetime", "decimal", "enum", "typing", "abc", "inspect", "traceback", "unittest",
                   "threading", "subprocess", "asyncio", "zlib", "codecs", "textwrap", "pathlib", "configparser", "mailbox", "mimetypes",
                   "ftplib", "poplib", "ipaddress", "gettext", "operator", "collections", "itertools", "functools", "contextlib"}


def test_no_provider_script_is_named_like_a_standard_library_module_and_the_scripts_beside_this_one_still_run():
    """A script's own folder is first on its sys.path: a providers/messenger/email.py would be imported in place of the standard library's
    email package by http.client, urllib and smtplib, in every other script run from that folder. This provider is email-imap.py."""
    names = getattr(sys, "stdlib_module_names", None) or STDLIB_FALLBACK
    for folder in sorted(PROVIDERS.iterdir()):
        for script in ([folder] if folder.suffix == ".py" else sorted(folder.glob("*.py")) if folder.is_dir() else []):
            assert script.stem not in names, f"{script} would shadow the standard library module {script.stem}"
    assert not (PROVIDERS / "messenger" / "email.py").exists()
    for script, platform in (("email-imap.py", "email"), ("telegram.py", "telegram"), ("whatsapp-cloud.py", "whatsapp-cloud")):
        done = subprocess.run([sys.executable, str(PROVIDERS / "messenger" / script), "capabilities", "--platform", platform],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0 and "max_text" in json.loads(done.stdout), (script, done.stderr[-300:])
    assert json.loads(subprocess.run([sys.executable, str(PROVIDERS / "messenger" / "email-imap.py"), "capabilities", "--platform", "email"],
                                     capture_output=True, text=True, timeout=60).stdout) == provider.CAPABILITIES
    assert subprocess.run([sys.executable, str(PROVIDERS / "messenger" / "email-imap.py"), "--help"], capture_output=True, text=True,
                          timeout=60).returncode == 0


def test_the_resolver_lists_the_provider_for_the_platform_email():
    resolve = load("resolve_for_email_tests", PROVIDERS / "resolve.py")
    assert "email-imap" in resolve.implementations_in("messenger", root=str(ROOT))
    assert resolve.served_platforms("messenger:<platform>", "email-imap", root=str(ROOT)) == ["email"]


def test_the_polling_verbs_exit_2_and_another_platform_is_refused(capsys):
    for verb in ("receive", "send", "ack"):
        code, _, err = run_cli(capsys, verb, "--platform", "email")
        assert code == 2 and "listen mode" in err
    assert run_cli(capsys, "capabilities", "--platform", "telegram")[0] == 2
    assert run_cli(capsys, "--platform", "email")[0] == 2


def test_setup_writes_the_settings_without_a_secret_in_a_private_folder_and_whoami_prints_them(world, capsys):
    code, out, err = run_cli(capsys, "setup", "--platform", "email", "--address", OWN.upper(), "--imap-host", "127.0.0.1", "--imap-port",
                             str(world["imap"].port), "--imap-security", "plain", "--smtp-host", "127.0.0.1", "--smtp-port",
                             str(world["smtp"].port), "--smtp-security", "plain", "--authserv-id", ID.upper(), "--poll-seconds", "20")
    assert code == 0, err
    saved = json.loads((world["state"] / "settings.json").read_text())
    assert saved["address"] == "ASSISTANT@office.example" and saved["authserv_id"] == ID and saved["poll_seconds"] == 20 and PASSWORD not in json.dumps(saved)
    assert stat.S_IMODE(os.stat(world["state"] / "settings.json").st_mode) == 0o600 and stat.S_IMODE(os.stat(world["state"]).st_mode) == 0o700
    code, out, _ = run_cli(capsys, "whoami", "--platform", "email")
    assert code == 0 and json.loads(out)["address"] == "ASSISTANT@office.example" and json.loads(out)["authserv_id"] == ID


def test_setup_without_an_authserv_id_prints_the_ids_on_the_newest_message_and_never_picks_one(world, capsys):
    world["imap"].add(raw(auth=GOOD, above=["Authentication-Results: elsewhere.example; none"]))
    code, out, err = run_cli(capsys, "setup", "--platform", "email", "--address", OWN, "--imap-host", "127.0.0.1", "--imap-port",
                             str(world["imap"].port), "--imap-security", "plain", "--smtp-host", "127.0.0.1", "--smtp-port",
                             str(world["smtp"].port), "--smtp-security", "plain")
    assert code == 0, err
    shown = json.loads(out)
    assert shown["authserv_id"] is None and shown["authserv_ids_seen"] == ["elsewhere.example"]      # the topmost header of each message only
    assert json.loads((world["state"] / "settings.json").read_text())["authserv_id"] is None
    code, _, err = run_cli(capsys, "listen", "--platform", "email")
    assert code == 3 and "authserv-id" in err


def test_setup_refuses_a_poll_below_15_seconds_a_bad_address_and_a_connection_without_tls(world, capsys, monkeypatch):
    base = ["setup", "--platform", "email", "--imap-host", "imap.office.example", "--smtp-host", "smtp.office.example"]
    assert run_cli(capsys, *base, "--address", OWN, "--poll-seconds", "14")[0] == 2
    assert run_cli(capsys, *base, "--address", "Assistant <assistant@office.example>")[0] == 2
    assert run_cli(capsys, *base, "--address", OWN, "--smtp-security", "plain")[0] == 2
    assert run_cli(capsys, *base, "--address", OWN, "--imap-port", "143")[0] == 2
    assert run_cli(capsys, *base, "--address", OWN, "--authserv-id", "bad id;")[0] == 2
    assert not (world["state"] / "settings.json").exists()


def test_check_logs_in_to_both_servers_and_exits_3_when_the_newest_messages_carry_no_authentication(world, capsys):
    world["imap"].add(raw())
    assert run_cli(capsys, "--check", "--platform", "email")[0] == 3      # no settings yet
    provider.write_private_json(os.path.join(provider.folder(), "settings.json"), world["settings"])
    code, out, err = run_cli(capsys, "--check", "--platform", "email")
    assert code == 0, err
    assert json.loads(out) == {"ok": True, "address": OWN, "authserv_id": ID, "messages_checked": 1, "with_authentication": 1,
                               "with_dmarc_pass": 1}
    world["imap"].add(raw(auth=None))
    world["imap"].messages = {k: v for k, v in world["imap"].messages.items() if b"Authentication-Results" not in v}
    code, _, err = run_cli(capsys, "--check", "--platform", "email")
    assert code == 3 and "cannot tell a forged sender" in err
    assert PASSWORD not in err


def test_check_needs_the_id_at_the_top_of_every_one_of_the_newest_messages_and_a_header_the_sender_planted_does_not_count(world, capsys):
    provider.write_private_json(os.path.join(provider.folder(), "settings.json"), world["settings"])
    world["imap"].add(raw())
    world["imap"].add(raw(auth=None, above=["Authentication-Results: elsewhere.example; none"], below=[f"Authentication-Results: {GOOD}"]))      # ours is lower down: the sender's own
    code, _, err = run_cli(capsys, "--check", "--platform", "email")
    assert code == 3 and "1 of 2" in err
    world["imap"].messages.pop(2)
    world["imap"].add(raw(auth=GOOD, above=["Authentication-Results: elsewhere.example; none"]))      # another id on top: not ours
    assert run_cli(capsys, "--check", "--platform", "email")[0] == 3


def test_check_and_setup_say_when_the_newest_messages_carry_no_dmarc_result_and_why_the_channel_will_refuse_them(world, capsys):
    provider.write_private_json(os.path.join(provider.folder(), "settings.json"), world["settings"])
    only_dkim = f"{ID}; dkim=pass header.d=office.example"
    world["imap"].add(raw(auth=only_dkim))
    code, out, err = run_cli(capsys, "--check", "--platform", "email")
    assert code == 3 and "DMARC result" in err and "refused" in err and PASSWORD not in err      # a host that writes none cannot be used
    world["imap"].add(raw(auth=GOOD))
    code, out, err = run_cli(capsys, "--check", "--platform", "email")
    shown = json.loads(out)
    assert code == 0 and shown["with_dmarc_pass"] == 1 and shown["messages_checked"] == 2 and "carry no single dmarc=pass" in shown["note"]
    base = ["setup", "--platform", "email", "--address", OWN, "--imap-host", "127.0.0.1", "--imap-port", str(world["imap"].port), "--imap-security",
            "plain", "--smtp-host", "127.0.0.1", "--smtp-port", str(world["smtp"].port), "--smtp-security", "plain"]
    world["imap"].messages = {1: raw(auth=only_dkim)}
    code, out, err = run_cli(capsys, *base)
    shown = json.loads(out)
    assert code == 0 and shown["authserv_ids_seen"] == [ID] and shown["dmarc_results_seen"] == [] and "no DMARC result" in shown["note"]
    world["imap"].add(raw(auth=GOOD))
    shown = json.loads(run_cli(capsys, *base)[1])
    assert shown["dmarc_results_seen"] == ["pass"] and "note" not in shown


def test_check_exits_3_on_a_refused_login_and_names_no_password(world, capsys):
    provider.write_private_json(os.path.join(provider.folder(), "settings.json"), world["settings"])
    world["imap"].refuse_login = True
    code, _, err = run_cli(capsys, "--check", "--platform", "email")
    assert code == 3 and PASSWORD not in err


def test_listen_without_a_password_is_not_configured(world, capsys, monkeypatch):
    provider.write_private_json(os.path.join(provider.folder(), "settings.json"), world["settings"])
    monkeypatch.delenv("MESSENGER_EMAIL_PASSWORD")
    monkeypatch.setattr(provider, "secret_resolver", lambda: type("R", (), {"resolve": staticmethod(lambda name: None)}))
    code, _, err = run_cli(capsys, "listen", "--platform", "email")
    assert code == 3 and "MESSENGER_EMAIL_PASSWORD" in err


# --- the listen process ---------------------------------------------------------------------------------------------------------


class Pipe:
    """The bridge's side of a listener: its requests in, its protocol lines out."""

    def __init__(self, world, **options):
        self.world = world
        self.read_fd, self.write_fd = os.pipe()
        self.stdin = os.fdopen(self.read_fd, "rb")
        self.lines, self.cond = [], threading.Condition()

        class Stream:
            def write(inner, data):
                with self.cond:
                    self.lines.extend(json.loads(x) for x in data.decode().splitlines() if x)
                    self.cond.notify_all()

            def flush(inner):
                pass

        self.listener = provider.Listener(world["settings"], PASSWORD, out=provider.Out(Stream()), stdin=self.stdin,
                                          poll_seconds=options.pop("poll_seconds", 0.05), **options)
        self.code = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        self.code = self.listener.run()

    def wait(self, test, seconds=10.0):
        deadline = time.monotonic() + seconds
        with self.cond:
            while True:
                found = [x for x in self.lines if test(x)]
                if found:
                    return found
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError(f"no such line in {seconds} s; lines so far: {self.lines}")
                self.cond.wait(left)

    def events(self, name):
        return [x for x in self.lines if x.get("event") == name]

    def request(self, value):
        os.write(self.write_fd, json.dumps(value).encode() + b"\n")

    def end(self, seconds=5.0):
        try:
            os.close(self.write_fd)
        except OSError:
            pass
        self.thread.join(seconds)
        assert not self.thread.is_alive(), "the listener did not stop within 5 s of the end of stdin"
        return self.code


def settle(pipe, seconds=0.6):
    time.sleep(seconds)
    return pipe.lines


def updates(pipe):
    return [x["update"] for x in pipe.lines if x.get("event") == "update"]


def test_listen_says_ready_then_serves_only_what_arrives_after_the_start(world, capfd):
    world["imap"].add(raw(text="/approve 1"))        # already in the mailbox: from now on, never the whole mailbox
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    world["imap"].add(raw(text="/approve 2"))
    pipe.wait(lambda x: x.get("event") == "update")
    assert [u["text"] for u in updates(pipe)] == ["/approve 2"]
    assert pipe.end() == 0
    assert json.loads((world["state"] / "cursor.json").read_text()) == {"last_uid": 2, "uidvalidity": 1000}
    assert stat.S_IMODE(os.stat(world["state"] / "cursor.json").st_mode) == 0o600


def test_a_restart_goes_on_from_the_cursor_and_serves_nothing_twice(world):
    world["imap"].add(raw(text="first"))
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    world["imap"].add(raw(text="second"))
    pipe.wait(lambda x: x.get("event") == "update")
    assert pipe.end() == 0
    world["imap"].add(raw(text="third"))      # arrived while the provider was not running
    again = Pipe(world)
    again.wait(lambda x: x.get("event") == "update")
    settle(again)
    assert [u["text"] for u in updates(again)] == ["third"]
    assert again.end() == 0


def test_a_new_uidvalidity_restarts_from_now_on_never_the_whole_mailbox(world):
    world["imap"].add(raw(text="old one"))
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    assert pipe.end() == 0
    world["imap"].uidvalidity = 2000
    world["imap"].add(raw(text="old two"))
    again = Pipe(world)
    again.wait(lambda x: x.get("event") == "ready")
    settle(again)
    assert updates(again) == []
    assert json.loads((world["state"] / "cursor.json").read_text()) == {"last_uid": 2, "uidvalidity": 2000}
    world["imap"].add(raw(text="new"))
    again.wait(lambda x: x.get("event") == "update")
    assert again.end() == 0


def test_the_mailbox_is_never_changed_every_command_is_read_only_and_every_body_fetch_is_a_peek(world):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    for text in ("one", "two"):
        world["imap"].add(raw(text=text))
    world["imap"].add(raw(text="forged", auth=None))
    pipe.wait(lambda x: x.get("event") == "update")
    settle(pipe)
    assert pipe.end() == 0
    verbs = set(world["imap"].verbs())
    assert verbs <= set(provider.ALLOWED_IMAP), verbs
    assert not verbs & {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "CLOSE", "APPEND", "DELETE", "CREATE", "RENAME", "SUBSCRIBE", "IDLE"}
    fetches = [c for c in world["imap"].commands if c.startswith("UID FETCH")]
    assert fetches and all(re.search(r"\((BODY\.PEEK\[\]|RFC822\.SIZE)\)$", c) for c in fetches), fetches
    assert any(c.startswith("EXAMINE") for c in world["imap"].commands)


def test_a_forged_automatic_or_not_private_message_is_dropped_with_no_reply_and_no_log_of_what_it_held(world, capfd):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    for data in (raw(text="SECRETWORDS forged", auth=None), raw(text="SECRETWORDS dmarc", auth=f"{ID}; dmarc=fail"),
                 raw(text="SECRETWORDS bulk", extra=["Precedence: bulk"]), raw(text="SECRETWORDS cc", cc="x@office.example"),
                 raw(text="SECRETWORDS auto", extra=["Auto-Submitted: auto-replied"]),
                 raw(text="SECRETWORDS list", extra=["List-Id: <l.office.example>"]),
                 raw(text="SECRETWORDS spoof", sender="boss@client.example", auth=f"{ID}; dmarc=pass header.from=office.example")):
        world["imap"].add(data)
    world["imap"].add(raw(text="the only real one"))
    pipe.wait(lambda x: x.get("event") == "update")
    settle(pipe)
    assert [u["text"] for u in updates(pipe)] == ["the only real one"]
    assert world["smtp"].messages == [] and world["smtp"].connections == 1      # one login check at the start; nothing sent: no backscatter
    assert pipe.end() == 0
    err = capfd.readouterr().err
    assert "SECRETWORDS" not in err and "office.example" not in err and "client.example" not in err and "Re: card" not in err
    for why in ("unauthenticated", "automatic", "not-private"):
        assert f"dropped a message: {why}" in err


def test_a_message_over_a_mebibyte_is_skipped_without_fetching_its_body(world, capfd):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    huge = world["imap"].add(raw(text="HUGE"))
    world["imap"].sizes[huge] = provider.MAX_SIZE + 1
    world["imap"].add(raw(text="small"))
    pipe.wait(lambda x: x.get("event") == "update")
    assert [u["text"] for u in updates(pipe)] == ["small"]
    assert not [c for c in world["imap"].commands if c.startswith(f"UID FETCH {huge} (BODY")]
    assert pipe.end() == 0
    assert "dropped a message: size" in capfd.readouterr().err


def test_a_send_request_sends_the_card_and_a_reply_that_names_it_comes_back_as_reply_to(world):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    pipe.request({"id": 1, "op": "send", "chat": OWNER, "message": card()})
    answer = pipe.wait(lambda x: x.get("id") == 1)[0]
    assert answer["ok"] is True and re.fullmatch(r"<oh\.[0-9a-f]{32}@office\.example>", answer["message_id"])
    assert world["smtp"].messages[0]["to"] == [OWNER]
    world["imap"].add(raw(text="/approve 12", in_reply_to=answer["message_id"]))
    world["imap"].add(raw(text="/approve 12", in_reply_to="<forged-guess@office.example>"))
    pipe.wait(lambda x: x.get("event") == "update")
    settle(pipe)
    assert [u["reply_to"] for u in updates(pipe)] == [answer["message_id"], None]
    assert pipe.end() == 0


def test_a_bad_request_is_answered_as_a_usage_error_and_the_provider_goes_on(world):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    pipe.request({"id": 2, "op": "send", "chat": "x\r\nBcc: spy@evil.example", "message": card()})
    pipe.request({"id": 3, "op": "send", "chat": OWNER, "message": card(document={"name": "a.txt", "text": "t"})})
    pipe.request({"id": 4, "op": "delete", "chat": OWNER})
    pipe.request({"id": 5, "op": "send", "chat": OWNER, "message": card()})
    pipe.wait(lambda x: x.get("id") == 5)
    answers = {x["id"]: x for x in pipe.lines if "id" in x}
    assert [answers[i]["kind"] for i in (2, 3, 4)] == ["usage"] * 3 and answers[5]["ok"] is True
    assert len(world["smtp"].messages) == 1
    assert pipe.end() == 0


def test_a_refused_imap_login_is_an_error_event_and_exit_3(world):
    world["imap"].refuse_login = True
    pipe = Pipe(world)
    pipe.thread.join(10)
    assert pipe.code == 3
    assert pipe.events("error")[0]["kind"] == "not-configured" and PASSWORD not in json.dumps(pipe.lines) and pipe.events("ready") == []


def test_a_refused_smtp_login_stops_the_start_before_ready(world):
    world["smtp"].refuse_login = True
    pipe = Pipe(world)
    pipe.thread.join(10)
    assert pipe.code == 3 and pipe.events("ready") == [] and pipe.events("error")[0]["kind"] == "not-configured"


def test_a_lost_mailbox_connection_is_a_failed_error_event_and_exit_1_for_the_bridge_to_restart(world):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    world["imap"].kill = True
    pipe.thread.join(10)
    assert pipe.code == 1 and pipe.events("error")[-1]["kind"] == "failed"


def test_a_second_reader_of_the_same_mailbox_is_refused(world):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    with pytest.raises(provider.ProviderError) as e:
        provider.Listener(world["settings"], PASSWORD, out=provider.Out(io.BytesIO()), stdin=io.BytesIO(), poll_seconds=0.05).run()
    assert e.value.code == 3 and "another program" in str(e.value)
    assert pipe.end() == 0


def test_the_provider_stops_within_five_seconds_of_the_end_of_its_stdin(world):
    pipe = Pipe(world, poll_seconds=15)
    pipe.wait(lambda x: x.get("event") == "ready")
    started = time.monotonic()
    assert pipe.end(5.0) == 0 and time.monotonic() - started < 5.0


def test_a_listener_needs_an_authserv_id(world):
    with pytest.raises(provider.ProviderError) as e:
        provider.Listener(settings_for(authserv_id=None), PASSWORD, out=provider.Out(io.BytesIO()), stdin=io.BytesIO())
    assert e.value.code == 3


# --- hostile input that costs time or memory ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("html", ["<a " * 8000, "<b x=1 " * 8000, "<!--" * 64000], ids=["open-a", "open-b-attr", "open-comment"])
def test_an_html_part_that_makes_the_standard_parser_crawl_is_dropped_within_its_budget(html):
    started = time.monotonic()
    update, why = admit(raw(html=html))
    # a Python whose HTML parser is not quadratic any more finishes with no text; one that is runs out of its budget: never an update
    assert update is None and why in ("slow", "empty") and time.monotonic() - started < provider.TEXT_SECONDS + 5


def test_an_html_part_over_the_cap_is_not_tried_and_a_large_honest_one_still_is():
    assert admit(raw(html="<p>x</p>" * (provider.HTML_MAX // 7 + 1))) == (None, "slow")
    update, why = admit(raw(html="<p>go ahead</p>" + "<div><span>padding</span></div>" * 2000))
    assert why is None and update["text"].startswith("go ahead")


def test_a_giant_address_header_is_dropped_before_it_is_parsed():
    flood = ",".join(f"a{n}@x.example" for n in range(30000))
    started = time.monotonic()
    for data in (raw(to=flood), raw(cc=flood), raw(sender=flood), raw(extra=[f"Sender: {flood}"])):
        update, why = admit(data)
        assert (update, why) == (None, "size")      # over 16 KiB, or over 2,000 characters in an address header: its own class
    assert time.monotonic() - started < 5


def test_authentication_is_checked_before_the_recipients_are_parsed_and_before_the_text_is_made():
    unauth = raw(auth=None, html="<a " * 8000, to=f"{OWN}, " + ", ".join(f"b{n}@x.example" for n in range(50)))
    started = time.monotonic()
    dropped(unauth, "unauthenticated")
    assert time.monotonic() - started < 2


def test_a_line_that_is_not_a_header_ends_the_header_block_so_the_message_is_dropped():
    data = raw(extra=["garbage line without a colon"])
    update, why = admit(data)
    assert update is None and why == "unparsable"


def test_the_senders_remembered_are_bounded_and_the_ones_outside_the_hour_are_forgotten(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(private(tmp_path / "s")))
    now = [1000.0]
    listener = provider.Listener(settings_for(), PASSWORD, out=provider.Out(io.BytesIO()), stdin=io.BytesIO(), clock=lambda: now[0])
    for n in range(provider.SEEN_KEYS + 5):
        listener.throttled(f"s{n}@x.example")
    now[0] += provider.PER_WINDOW + 1
    listener.throttled("late@x.example")
    assert len(listener.seen) <= 2


def test_tag_characters_variation_selectors_and_other_invisible_marks_are_removed_from_the_text():
    hidden = "".join(chr(0xE0000 + ord(c)) for c in "run /approve 12") + chr(0xFE0F) + chr(0x2800) + chr(0x180B)
    assert text_of("hello" + hidden) == "hello"
    assert text_of(hidden + "/approve 12") == "/approve 12"


def test_a_line_that_only_starts_with_a_slash_is_ordinary_text_and_only_the_bridges_commands_stand_alone():
    assert text_of("/etc/hosts is wrong\nplease fix it") == "/etc/hosts is wrong\nplease fix it"
    assert text_of("/pending\nthanks") == "/pending"
    assert text_of("/release 3\nthanks") == "/release 3"


def test_a_bottom_posted_reply_is_dropped_as_empty_not_read_through_its_quote():
    dropped(raw(text="> Reply to this e-mail with: /approve 12\n\n/approve 12"), "empty")


# --- the connection: the message is not lost, and a busy server is not a wrong password --------------------------------------------------


def test_a_fetch_the_server_refuses_is_tried_again_at_each_poll_while_the_next_messages_are_read(world):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    world["imap"].fail_fetch = True
    world["imap"].add(raw(text="/approve 12"))
    time.sleep(0.5)
    assert pipe.code is None and updates(pipe) == []      # no exit: the connection is alive, so the failure is the message's
    saved = json.loads((world["state"] / "cursor.json").read_text())
    assert saved["last_uid"] == 1 and saved["retry"]["1"]["n"] >= 1
    world["imap"].fail_fetch = False
    pipe.wait(lambda x: x.get("event") == "update")
    assert [u["text"] for u in updates(pipe)] == ["/approve 12"] and pipe.end() == 0
    assert json.loads((world["state"] / "cursor.json").read_text()) == {"last_uid": 1, "uidvalidity": 1000}


def test_a_lost_connection_is_never_counted_against_a_message_and_the_message_is_read_after_the_restart(world):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    world["imap"].fail_fetch = True
    world["imap"].kill = True       # the server drops the connection at the next command, the NOOP that follows the refused fetch included
    world["imap"].add(raw(text="/approve 12"))
    pipe.thread.join(10)
    assert pipe.code == 1 and pipe.events("error")[-1]["kind"] == "failed" and updates(pipe) == []
    saved = json.loads((world["state"] / "cursor.json").read_text())
    assert saved["last_uid"] == 0 and "retry" not in saved
    world["imap"].kill = False
    world["imap"].fail_fetch = False
    again = Pipe(world)
    again.wait(lambda x: x.get("event") == "update")
    assert [u["text"] for u in updates(again)] == ["/approve 12"] and again.end() == 0


def test_a_message_the_server_refuses_for_three_tries_over_an_hour_is_skipped_with_an_error_event_and_the_channel_goes_on(world):
    clock = [1_000_000.0]
    pipe = Pipe(world, wall=lambda: clock[0])
    pipe.wait(lambda x: x.get("event") == "ready")
    world["imap"].fail_fetch = True
    world["imap"].add(raw(text="poison"))
    time.sleep(0.6)
    assert json.loads((world["state"] / "cursor.json").read_text())["retry"]["1"]["n"] >= 3      # three tries, but not over an hour
    assert pipe.events("error") == [] and pipe.code is None
    clock[0] += provider.RETRY_SPAN + 1
    pipe.wait(lambda x: x.get("event") == "error")
    assert pipe.events("error")[0]["kind"] == "skipped" and "skipped" in pipe.events("error")[0]["reason"]
    deadline = time.monotonic() + 5
    while "retry" in json.loads((world["state"] / "cursor.json").read_text()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "retry" not in json.loads((world["state"] / "cursor.json").read_text())
    world["imap"].fail_fetch = False
    world["imap"].add(raw(text="second"))
    pipe.wait(lambda x: x.get("event") == "update")
    assert [u["text"] for u in updates(pipe)] == ["second"] and pipe.end() == 0


def test_a_server_that_is_busy_or_limited_is_a_failed_start_that_is_tried_again_and_only_wrong_credentials_are_exit_3(world):
    for answer, code in (("NO [UNAVAILABLE] too many connections", 1), ("NO [LIMIT] too many simultaneous connections", 1),
                         ("NO [AUTHENTICATIONFAILED] invalid credentials", 3), ("NO Login failed.", 3)):
        world["imap"].login_answer = answer
        pipe = Pipe(world)
        pipe.thread.join(10)
        assert pipe.code == code, (answer, pipe.code)
        assert pipe.events("error")[0]["kind"] == ("not-configured" if code == 3 else "failed")


def test_an_smtp_login_that_is_not_a_refusal_of_the_password_is_not_exit_3(world, monkeypatch):
    import smtplib

    class Server:
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(454, b"4.7.0 temporary authentication failure")

        def quit(self):
            pass
    monkeypatch.setattr(mail, "smtp_connect", lambda *a, **k: Server())
    with pytest.raises(provider.ProviderError) as e:
        provider.connect_smtp(world["settings"], mail, PASSWORD)
    assert e.value.code == provider.EXIT_SERVICE and e.value.kind == "failed"
    monkeypatch.setattr(Server, "login", lambda self, u, p: (_ for _ in ()).throw(smtplib.SMTPAuthenticationError(535, b"5.7.8 bad")))
    with pytest.raises(provider.ProviderError) as e:
        provider.connect_smtp(world["settings"], mail, PASSWORD)
    assert e.value.code == provider.EXIT_NOT_CONFIGURED


def test_new_uids_are_asked_for_a_window_at_a_time_never_as_an_open_ended_range(world):
    world["imap"].add(raw(text="one"), uid=1)
    world["imap"].add(raw(text="far"), uid=5000)
    box = provider.Mailbox(provider.connect_imap(world["settings"], mail, PASSWORD))
    try:
        box.examine()
        assert box.highest() == 5000
        assert box.new_uids(0) == [1] and box.new_uids(1) == [5000] and box.new_uids(5000) == []
        searches = [c for c in world["imap"].commands if c.startswith("UID SEARCH")]
        assert searches and not any(c.endswith(":*") for c in searches), searches
    finally:
        box.logout()


# --- the card puts how to act at the top -------------------------------------------------------------------------------------------


def test_the_typed_commands_and_the_hash_come_right_under_the_first_line_where_a_preview_or_a_clipped_message_still_shows_them():
    footer = ["Send /approve 12", "Send /reject 12", f"Approving applies exactly the text above (sha256 {HASH}).", "Approve it on the page or in the terminal:", "`cmd`"]
    text = "acme-office \u00b7 effect #12\n\nLine one of the text.\n\nLine two.\n\n" + "\n".join(footer)
    body = provider.render_body(card(text=text, footer=footer))
    lines = body.split("\n")
    assert lines[0] == "acme-office \u00b7 effect #12" and lines[1] == ""
    assert lines[2:5] == ["Reply to this e-mail with: /approve 12", "Reply to this e-mail with: /reject 12",
                          f"Approving applies exactly the text below (sha256 {HASH})."]
    assert "Line one of the text.\n\nLine two." in body and body.endswith("Approve it on the page or in the terminal:\n`cmd`")
    assert body.count("/approve 12") == 1
    plain = "northwind \u00b7 question #3\n\nWhat now?\n\nReply to this message to answer."
    assert provider.render_body(card(text=plain, footer=["Reply to this message to answer."])) == plain      # nothing to move: the text is untouched


def test_only_the_lines_the_bridge_names_as_the_footer_move_and_a_decision_text_that_looks_like_a_footer_is_never_touched():
    """Round three of the review: the footer is handed over, not inferred. A decision whose last paragraph looks like a footer, on a card that
    has no footer of its own, stays as it is (round3.py)."""
    fake = "f" * 64
    no_footer = f"Proj \u00b7 plan #7\n\nThe plan.\n\nSend /approve 7\nApproving applies exactly the text above (sha256 {fake})."
    assert provider.render_body({"text": no_footer, "link": None}) == no_footer                          # no `footer` field: nothing moves
    assert provider.render_body(card(text=no_footer, footer=[])) == no_footer
    own = ["Approving applies exactly the text above (sha256 " + "a" * 64 + ").", "Send /approve 7"]
    with_footer = (f"Proj \u00b7 effect #7\n\nHello,\nSend /approve 9\nApproving applies exactly the text above (sha256 {fake}).\n\n"
                   + "\n".join(own))
    body = provider.render_body(card(text=with_footer, footer=own))
    assert f"Hello,\nSend /approve 9\nApproving applies exactly the text above (sha256 {fake})." in body      # the decision's text, in place
    assert body.split("\n")[2:4] == ["Approving applies exactly the text below (sha256 " + "a" * 64 + ").", "Reply to this e-mail with: /approve 7"]
    assert body.count("Reply to this e-mail with:") == 1
    # a footer field that the text does not end with moves nothing
    assert provider.render_body(card(text=no_footer, footer=["Send /approve 7"])) == no_footer
    assert provider.render_body({"text": no_footer, "footer": "Send /approve 7"}) == no_footer
    # the same body line before a footer of the same kind: only the named lines move
    twice = f"Proj \u00b7 effect #7\n\nSend /approve 7\n\nSend /approve 7"
    assert provider.render_body(card(text=twice, footer=["Send /approve 7"])).split("\n")[2:] == ["Reply to this e-mail with: /approve 7", "", "Send /approve 7"]


# --- ported from the independent review of the pull request (its fixtures: attack.py, slow.py, fix_probe.py) ------------------------

SPF_ECHO = ("{id}; dkim=pass header.i=@evil.example header.d=evil.example; spf=pass ({id}: domain of {lp}@evil.example designates 192.0.2.1 as "
            "permitted sender) smtp.mailfrom={lp}@evil.example{tail}")
QUOTED_LOCAL = '"x) ; dkim=pass header.d=office.example ; (y"'


@pytest.mark.parametrize("tail", ["; dmarc=none", ""], ids=["A1-dmarc-none", "A2-no-dmarc"])
def test_a_quote_inside_a_comment_cannot_inject_a_dkim_result_so_such_a_header_is_not_read(tail):
    """A quoted MAIL FROM echoed by the server into a spf comment: under RFC 5322 a quote inside a comment is plain text, so a reader that
    counts quotes would end the comment at the first `)` and read the `dkim=pass header.d=office.example` the sender wrote."""
    value = SPF_ECHO.format(id=ID, lp=QUOTED_LOCAL, tail=tail)
    assert provider.parse_auth_results(value) is None
    dropped(raw(auth=value), "unauthenticated")


def test_the_count_guard_still_reads_the_headers_gmail_and_fastmail_write():
    gmail_like = (f"{ID};\r\n       dkim=pass header.i=@office.example header.s=s1 header.b=AbC+/d;\r\n       spf=pass ({ID}: domain of "
                  "owner@office.example designates 192.0.2.1 as permitted sender) smtp.mailfrom=owner@office.example;\r\n       dmarc=pass "
                  "(p=QUARANTINE sp=QUARANTINE dis=NONE) header.from=office.example")
    fastmail_like = (f"{ID} 1; dkim=pass (2048-bit rsa key sha256) header.d=office.example header.i=@office.example header.b=x "
                     "header.a=rsa-sha256 header.s=fm1 x-bits=2048; dmarc=pass policy.published-domain-policy=none (p=none,d=none) "
                     "header.from=office.example; spf=pass smtp.mailfrom=owner@office.example smtp.helo=out.example")
    for value in (gmail_like, fastmail_like):
        assert admit(raw(auth=value))[1] is None


def test_a_server_that_strips_the_quotes_from_an_echoed_address_is_a_residual_risk_the_readme_names():
    """Fixture B of the review, now that only one dmarc=pass aligned to the domain admits: a server that writes the echoed address WITHOUT its
    quotes, and wrote no DMARC result of its own, puts the sender's `dmarc=pass` into the header as a result of its own, and nothing in the
    header tells it from a real one. It is documented ("What an address proves"), checked by hand on first use ("To verify"), and this test
    fails the day the provider can tell (then the README line goes). With a DMARC result of the server's own, the injected one is a second
    one and the header is refused."""
    injected = f"{ID}; dkim=pass header.i=x; dmarc=pass header.from=office.example z@evil.example header.d=evil.example"
    assert admit(raw(auth=injected))[0] is not None
    dropped(raw(auth=injected + "; dmarc=none"), "unauthenticated")
    assert "residual" in (PROVIDERS / "messenger" / "README.md").read_text(encoding="utf-8").lower()


def test_a_quote_in_a_comment_is_refused_wherever_the_comment_is_and_a_legitimate_comment_is_read():
    """Round two of the review: the echo can sit in a comment alone (the A1 variant), and a count of method tokens refused legitimate comments
    (an ARC summary, reason="dkim=ok", (dmarc=p:reject)). The rule is the RFC 5322 reading: a double quote inside a comment makes the header
    unreadable."""
    lp = QUOTED_LOCAL
    only_comment = f"{ID}; spf=pass ({ID}: domain of {lp}@evil.example designates 192.0.2.1) smtp.mailfrom=evil.example; dmarc=none"
    assert provider.parse_auth_results(only_comment) is None
    dropped(raw(auth=only_comment), "unauthenticated")
    dropped(raw(auth=only_comment.replace("dmarc=none", "dmarc=pass header.from=office.example")), "unauthenticated")      # a pass beside it is not read either
    dropped(raw(auth=f"{ID}; dkim=pass header.d=evil.example; spf=none (helo a) ; dkim=pass header.d=office.example ; (b) smtp.helo=evil.example; dmarc=none"), "unauthenticated")
    arc = (f"{ID};\r\n       dkim=pass header.i=@office.example header.s=s1 header.b=AbCdEfGh;\r\n"
           "       arc=pass (i=1 spf=pass spfdomain=office.example dkim=pass dkdomain=office.example dmarc=pass fromdomain=office.example);\r\n"
           f"       spf=pass ({ID}: domain of owner@office.example designates 192.0.2.1 as permitted sender) smtp.mailfrom=owner@office.example;\r\n"
           "       dmarc=pass (p=NONE sp=NONE dis=NONE) header.from=office.example")
    for value in (arc, f'{ID}; dkim=pass reason="dkim=ok" header.d=office.example; dmarc=pass header.from=office.example',
                  f"{ID}; dkim=pass header.d=office.example; dmarc=pass (dmarc=p:reject) header.from=office.example",
                  f"{ID}; dkim=pass header.d=office.example header.b=Ab+dkim=; dmarc=pass header.from=office.example"):
        assert admit(raw(auth=value))[1] is None, value


def test_two_headers_with_our_id_are_refused_whatever_they_say():
    good = f"Authentication-Results: {GOOD}"
    dropped(raw(auth=GOOD, below=[good]), "unauthenticated")
    dropped(raw(auth=f"{ID}; dmarc=fail header.from=office.example", below=[good]), "unauthenticated")
    dropped(raw(auth=None, extra=[good], below=[good]), "unauthenticated")
    update, why = admit(raw(auth=GOOD, above=["Authentication-Results: elsewhere.example; dmarc=pass header.from=office.example"]))
    assert why is None


AR_TABLE = [
    ("A. no server header, the sender planted one with our id (the residual risk of a host that annotates some mail only)", dict(auth=None, extra=[f"Authentication-Results: {GOOD}"]), True),
    ("D. folded and upper case", dict(auth="MX.OFFICE.EXAMPLE;\r\n\tDKIM=PASS header.d=Office.Example;\r\n dmarc=PASS header.from=OFFICE.EXAMPLE"), True),
    ("E1 dmarc pass for the parent, From a subdomain", dict(sender="owner@sub.office.example", auth=f"{ID}; dmarc=pass header.from=office.example"), False),
    ("E2 dkim d=parent, From a subdomain, no dmarc", dict(sender="owner@sub.office.example", auth=f"{ID}; dkim=pass header.d=office.example"), False),
    ("E3 dmarc pass for a subdomain, From the parent", dict(auth=f"{ID}; dmarc=pass header.from=sub.office.example"), False),
    ("F. arc=pass only", dict(auth=f"{ID}; arc=pass (i=1); dmarc=fail header.from=office.example"), False),
    ("F2 ARC-Authentication-Results passes, the real one fails", dict(auth=f"{ID}; dmarc=fail header.from=office.example", above=[f"ARC-Authentication-Results: i=1; {GOOD}"]), False),
    ("G. header name in lower case", dict(auth=None, above=[f"authentication-results: {GOOD}"]), True),
    ("I. id with a version", dict(auth=f"{ID} 1; dmarc=pass header.from=office.example"), True),
    ("J. dmarc pass for another domain, dkim pass for ours", dict(auth=f"{ID}; dkim=pass header.d=office.example; dmarc=pass header.from=evil.example"), False),
    ("K. dmarc=none with a policy property (no DKIM-only path)", dict(auth=f"{ID}; dkim=pass header.d=office.example; dmarc=none policy.dmarc=none"), False),
    ("L. header.d quoted, no DMARC", dict(auth=f'{ID}; dkim=pass header.d="office.example"'), False),
    ("L2 header.from quoted", dict(auth=f'{ID}; dmarc=pass header.from="office.example"'), True),
    ("M. header.d with a trailing dot", dict(auth=f"{ID}; dkim=pass header.d=office.example."), False),
    ("N. dkim/1, no DMARC", dict(auth=f"{ID}; dkim/1=pass header.d=office.example"), False),
    ("N2 dmarc/1", dict(auth=f"{ID}; dmarc/1=pass header.from=office.example"), True),
    ("P. two header.d in one result", dict(auth=f"{ID}; dkim=pass header.d=evil.example header.d=office.example"), False),
    ("Q. header.from with a comment", dict(auth=f"{ID}; dmarc=pass header.from=office.example(x)"), True),
]


@pytest.mark.parametrize("label,kwargs,admitted", AR_TABLE, ids=[row[0].split(" ")[0] for row in AR_TABLE])
def test_authentication_results_shapes_from_the_review(label, kwargs, admitted):
    update, why = admit(raw(**kwargs))
    assert (update is not None) is admitted, (label, update, why)


FROM_TABLE = [
    ('"Owner" <owner@office.example>', OWNER), ('"ceo@office.example" <owner@office.example>', OWNER),
    ("owner@office.example <attacker@evil.example>", None), ("owner@office.example, attacker@evil.example", None),
    ("=?utf-8?q?Owner?= <owner@office.example>", OWNER), ("=?utf-8?b?b3duZXJAb2ZmaWNlLmV4YW1wbGU=?=", None),
    ("=?utf-8?q?owner?=@office.example", None), ("OWNER@OFFICE.EXAMPLE", OWNER), ("owner+x@office.example", "owner+x@office.example"),
    ("\u043ewner@office.example", None),                # a Cyrillic o in the local part
    ("owner@\u043effice.example", None),               # an international domain is refused: the A-label form is the way
    ("owner@xn--ffice-3ve.example", "unauthenticated"), ("<@relay.example:owner@office.example>", None),
    ("owner@office.example.", None), ("grp: owner@office.example;", None), ("owner\\@office.example", None),
]


@pytest.mark.parametrize("sender,expected", FROM_TABLE)
def test_from_shapes_from_the_review(sender, expected):
    update, why = admit(raw(sender=sender))
    if expected is None:
        assert update is None and why in ("sender", "unparsable"), (update, why)
    elif expected == "unauthenticated":
        assert update is None and why == expected      # a valid address of a domain the server did not vouch for
    else:
        assert update is not None and update["sender"] == expected


@pytest.mark.parametrize("header", [
    "Auto-Submitted: auto-replied", "Auto-Submitted: auto-generated; owner-email=x", "Precedence: bulk", "Precedence: Auto_Reply",
    "List-Id: <l.example>", "List-Post: <mailto:l@x>", "X-Autoreply: yes", "X-Autorespond: yes", "Return-Path: <>", "Return-Path: < >",
    "List-Unsubscribe: <mailto:out@office.example>"])
def test_automatic_headers_from_the_review(header):
    dropped(raw(extra=[header]), "automatic")


def test_a_bounce_from_the_mailer_daemon_without_a_report_part_is_automatic_and_a_normal_or_suppress_header_is_not():
    dropped(raw(sender="MAILER-DAEMON@office.example", subject="Undelivered Mail Returned to Sender"), "automatic")
    dropped(raw(sender="postmaster@office.example"), "automatic")
    assert admit(raw(extra=["Auto-Submitted: No"]))[1] is None and admit(raw(extra=["X-Auto-Response-Suppress: All"]))[1] is None


def test_the_binding_in_reply_to_reads_the_first_message_id_and_ignores_references():
    assert admit(raw(in_reply_to=SENT), sent=[SENT])[0]["reply_to"] == SENT
    assert admit(raw(in_reply_to=f"<a@b.example> {SENT}"), sent=[SENT])[0]["reply_to"] is None
    assert admit(raw(extra=[f"References: {SENT}"]), sent=[SENT])[0]["reply_to"] is None
    assert admit(raw(in_reply_to=SENT), sent=[])[0]["reply_to"] is None


def test_text_shapes_from_the_review():
    top = "/approve 12\r\n\r\nOn Sat, Oct 17, 2026 at 9:00 AM Assistant <assistant@office.example> wrote:\r\n> Reply to this e-mail with: /approve 12"
    assert admit(raw(text=top))[0]["text"] == "/approve 12"
    dropped(raw(text="On Sat, Oct 17, 2026 at 9:00 AM Assistant wrote:\r\n> card\r\n\r\n/approve 12"), "empty")
    dropped(raw(text="> /approve 12"), "empty")
    assert admit(raw(text="thanks\r\n > /approve 12"))[0]["text"] == "thanks"
    assert admit(raw(text="ok\r\n\r\nFrom: Assistant\r\nDate: today\r\n/approve 12"))[0]["text"] == "ok"
    assert admit(raw(text="\uff0fapprove 12"))[0]["text"] == "\uff0fapprove 12"      # a full-width slash is not a command to the bridge
    alt = "--b\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n/approve 12\r\n--b\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>no thanks</p>\r\n--b--"
    data = raw(text=alt).replace(b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit", b'Content-Type: multipart/alternative; boundary="b"', 1)
    assert admit(data)[0]["text"] == "/approve 12"      # the plain part wins, as the sender's own
    for kind in ("text/calendar", "text/enriched"):
        dropped(raw(text="/approve 12").replace(b"Content-Type: text/plain", f"Content-Type: {kind}".encode(), 1), "empty")


def test_html_hidden_text_by_display_none_or_the_hidden_attribute_is_removed_and_the_other_hiding_forms_are_a_documented_limit():
    removed = '<div>hello</div><div style="DISPLAY : NONE">/approve 12</div><div hidden>x</div><span style="visibility:hidden">y</span>'
    assert admit(raw(html=removed))[0]["text"] == "hello"
    read = '<div>hello</div><span style="font-size:0">/approve 13</span><font color="#ffffff">white</font><div style="opacity:0">op</div>'
    text = admit(raw(html=read))[0]["text"]
    assert "hello" in text and "white" in text      # read as text: the limit the module docstring and the README state


SLOW_SHAPES = {
    "content-type params": lambda: raw().replace(b"Content-Type: text/plain; charset=utf-8", b"Content-Type: text/plain; " + "; ".join(f"a{i}=b" for i in range(60000)).encode()),
    "content-type comments": lambda: raw().replace(b"Content-Type: text/plain; charset=utf-8", b"Content-Type: text/plain " + b"(" * 20000 + b")" * 20000),
    "in-reply-to huge": lambda: raw(in_reply_to="<a@b> " * 150000),
    "in-reply-to encoded words": lambda: raw(in_reply_to="=?utf-8?q?a?= " * 60000),
    "auto-submitted huge": lambda: raw(extra=["Auto-Submitted: " + "no " * 300000]),
    "precedence encoded": lambda: raw(extra=["Precedence: " + "=?utf-8?b?YQ==?= " * 50000]),
    "return-path comments": lambda: raw(extra=["Return-Path: " + "(" * 30000 + ")" * 30000]),
    "auth-results long": lambda: raw(auth=GOOD + "; " + "; ".join("dkim=fail header.d=x.example" for _ in range(25000))),
    "auth-results nested comments": lambda: raw(auth=GOOD + " " + "(" * 200000 + ")" * 200000),
    "header block of many small headers": lambda: raw(extra=[f"X-H{i}: v" for i in range(12000)]),
}


@pytest.mark.parametrize("name", sorted(SLOW_SHAPES))
def test_a_huge_header_is_dropped_as_unparsable_before_any_structured_header_is_read(name):
    data = SLOW_SHAPES[name]()
    if len(data) > provider.MAX_SIZE:
        data = data[:provider.MAX_SIZE - 10]
    started = time.monotonic()
    update, why = admit(data)
    assert update is None and why in ("unparsable", "size") and time.monotonic() - started < 5, (why, time.monotonic() - started)


def test_a_header_just_under_the_cap_and_deep_structures_cost_little_time_and_never_an_update_by_accident():
    nested = "".join(f'Content-Type: multipart/mixed; boundary="b{i}"\r\n\r\n--b{i}\r\n' for i in range(8000))
    data = raw().replace(b"Content-Type: text/plain; charset=utf-8", nested.split("\r\n\r\n", 1)[0].encode(), 1)
    data = data.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n" + nested.split("\r\n\r\n", 1)[1].encode() + b"Content-Type: text/plain\r\n\r\nhi"
    started = time.monotonic()
    update, why = admit(data)
    assert update is None and time.monotonic() - started < 10
    big_but_allowed = raw().replace(b"Content-Type: text/plain; charset=utf-8", b"Content-Type: text/plain; " + "; ".join(f"a{i}=b" for i in range(1500)).encode())
    started = time.monotonic()
    admit(big_but_allowed)
    assert time.monotonic() - started < 5
    lines = raw(text="a\r\n" + "x\r\n" * 300000)
    started = time.monotonic()
    assert admit(lines)[1] is None and time.monotonic() - started < 10


def test_the_rate_is_asked_before_the_text_is_made_so_a_refused_sender_never_reaches_the_html_child(monkeypatch):
    monkeypatch.setattr(provider.subprocess, "run", lambda *a, **k: pytest.fail("the HTML child was started for a sender over its rate"))
    asked = []
    update, why = provider.inspect_message(raw(html="<p>hi</p>"), OWN, ID, lambda chat: set(), mail,
                                           allow=lambda sender, domain: asked.append((sender, domain)) or False)
    assert (update, why) == (None, "rate") and asked == [(OWNER, "office.example")]
    update, why = provider.inspect_message(raw(auth=None, html="<p>hi</p>"), OWN, ID, lambda chat: set(), mail,
                                           allow=lambda *a: pytest.fail("asked for an unauthenticated message"))
    assert why == "unauthenticated"


def test_the_listener_counts_a_domain_as_well_as_a_sender(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(private(tmp_path / "s")))
    listener = provider.Listener(settings_for(), PASSWORD, out=provider.Out(io.BytesIO()), stdin=io.BytesIO(), clock=lambda: 1000.0)
    allowed = sum(1 for n in range(provider.PER_DOMAIN + 40) if listener.permit(f"p{n}@office.example", "office.example"))
    assert allowed == provider.PER_DOMAIN
    assert listener.permit("a@other.example", "other.example")
    assert sum(1 for _ in range(provider.PER_SENDER + 5) if listener.permit("same@other.example", "other.example")) == provider.PER_SENDER


# --- round two of the review: part headers, the domain rate, size classes -------------------------------------------------------------


def multipart(part_head, part_body="hi"):
    return raw(text=f"--b\r\n{part_head}\r\n\r\n{part_body}\r\n--b--").replace(
        b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit", b'Content-Type: multipart/mixed; boundary="b"', 1)


@pytest.mark.parametrize("head", [
    "Content-Type: text/plain; " + "; ".join(f"a{i}=b" for i in range(60000)),
    "Content-Type: text/html; charset=utf-8\r\nContent-Disposition: inline; " + "; ".join(f"a{i}=b" for i in range(60000)),
    "Content-Type: text/plain " + "(" * 20000 + ")" * 20000,
], ids=["part-content-type", "part-content-disposition", "part-comments"])
def test_a_hostile_header_inside_a_part_costs_one_budget_not_the_reader(head):
    """The headers of the parts are not capped by the header caps (they are in the body): the structure of the body is parsed in the child with
    a time and CPU budget, and the parent reads the headers of the message only."""
    data = multipart(head)
    assert len(data) < provider.MAX_SIZE
    started = time.monotonic()
    update, why = admit(data)
    assert update is None and why in ("slow", "unparsable") and time.monotonic() - started < provider.TEXT_SECONDS + 5, (why, time.monotonic() - started)


def test_a_part_with_ordinary_headers_is_read_in_the_child():
    update, why = admit(multipart("Content-Type: text/plain; charset=utf-8\r\nContent-Disposition: inline", "go ahead"))
    assert why is None and update["text"] == "go ahead"


def test_the_headers_of_the_message_are_read_without_parsing_its_body(monkeypatch):
    seen = []
    real = provider.BytesParser.parsebytes
    monkeypatch.setattr(provider.BytesParser, "parsebytes", lambda self, data, headersonly=False: seen.append(headersonly) or real(self, data, headersonly=headersonly))
    assert admit(raw())[1] is None and seen == [True]


def test_strangers_at_a_shared_domain_cannot_use_up_the_owners_share_but_the_address_limit_holds_for_everyone(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(private(tmp_path / "s")))
    listener = provider.Listener(settings_for(), PASSWORD, out=provider.Out(io.BytesIO()), stdin=io.BytesIO(), clock=lambda: 1000.0)
    listener.sent.add("owner@webmail.example", SENT)        # the provider has written to the owner: a person, not a stranger
    assert sum(1 for n in range(provider.PER_DOMAIN + 50) if listener.permit(f"stranger{n}@webmail.example", "webmail.example")) == provider.PER_DOMAIN
    assert listener.permit("another-stranger@webmail.example", "webmail.example") is False
    assert listener.permit("owner@webmail.example", "webmail.example") is True      # still permitted after 120 strangers
    assert sum(1 for _ in range(provider.PER_SENDER + 10) if listener.permit("owner@webmail.example", "webmail.example")) == provider.PER_SENDER - 1


def test_an_oversized_header_or_block_is_logged_with_the_class_size_and_not_unparsable():
    assert admit(raw(extra=["X-Big: " + "a" * (provider.HEADER_VALUE_MAX + 10)])) == (None, "size")
    assert admit(raw(extra=[f"X-H{i}: " + "v" * 100 for i in range(700)])) == (None, "size")        # a block over 64 KiB in headers under 16 KiB
    assert admit(raw(to="a@x.example, " * 400))[1] == "size"


# --- the retry list and the notes of the final review ------------------------------------------------------------------------------


def test_the_list_of_messages_to_try_again_is_capped_and_the_oldest_is_given_up_with_a_log_line(world, capfd):
    clock = [1_000_000.0]
    pipe = Pipe(world, wall=lambda: clock[0], poll_seconds=0.05)
    pipe.wait(lambda x: x.get("event") == "ready")
    world["imap"].fail_fetch = True
    for n in range(provider.RETRY_MAX + 5):
        world["imap"].add(raw(text=f"m{n}"))
        clock[0] += 1
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        saved = json.loads((world["state"] / "cursor.json").read_text())
        if saved["last_uid"] == provider.RETRY_MAX + 5:
            break
        time.sleep(0.1)
    saved = json.loads((world["state"] / "cursor.json").read_text())
    assert saved["last_uid"] == provider.RETRY_MAX + 5 and len(saved["retry"]) <= provider.RETRY_MAX
    assert "1" not in saved["retry"] and str(provider.RETRY_MAX + 5) in saved["retry"]      # the oldest went, the newest stayed
    assert capfd.readouterr().err.count("the list of messages to try again was full") >= 5
    gave_up = [e for e in pipe.events("error") if e["kind"] == "skipped"]
    assert len(gave_up) >= 5 and all("list of messages to try again was full" in e["reason"] for e in gave_up)      # each give-up reaches the bridge
    assert pipe.end() == 0


def test_an_unexpected_error_on_a_first_read_is_a_log_line_with_no_event_and_the_channel_goes_on(world, monkeypatch, capfd):
    real = provider.Listener.handle_uid

    def handle(self, box, uid):
        if uid == 1:
            raise KeyError("a surprise")
        return real(self, box, uid)
    monkeypatch.setattr(provider.Listener, "handle_uid", handle)
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    world["imap"].add(raw(text="poison"))
    world["imap"].add(raw(text="second"))
    pipe.wait(lambda x: x.get("event") == "update")
    assert "unreadable (KeyError)" in capfd.readouterr().err
    assert pipe.events("error") == [], "a stranger who passes DMARC for their own domain can craft a message that raises: never a message to the person"
    assert pipe.end() == 0


def test_the_cursor_is_written_once_for_a_pass_over_the_retry_list_not_once_for_each_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(private(tmp_path / "s")))
    listener = provider.Listener(settings_for(), PASSWORD, out=provider.Out(io.BytesIO()), stdin=io.BytesIO())
    listener.retry = {str(n): {"n": 1, "first": 1.0} for n in range(1, 41)}
    saves = []
    monkeypatch.setattr(listener, "save", lambda validity, last: saves.append(last))
    monkeypatch.setattr(listener, "handle_uid", lambda box, uid: None)
    listener.retry_pending(object(), 1000, 40)
    assert saves == [40] and listener.retry == {}


def test_an_unexpected_error_on_a_message_to_try_again_is_logged_and_the_pass_goes_on(tmp_path, monkeypatch, capfd):
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(private(tmp_path / "s")))
    out = io.BytesIO()
    listener = provider.Listener(settings_for(), PASSWORD, out=provider.Out(out), stdin=io.BytesIO())
    listener.retry = {"1": {"n": 1, "first": 1.0}, "2": {"n": 1, "first": 1.0}}
    seen = []

    def handle(box, uid):
        seen.append(uid)
        if uid == 1:
            raise KeyError("a surprise")
    monkeypatch.setattr(listener, "handle_uid", handle)
    monkeypatch.setattr(listener, "save", lambda *a: None)
    listener.retry_pending(object(), 1000, 2)
    assert seen == [1, 2] and listener.retry == {} and "unreadable (KeyError)" in capfd.readouterr().err
    assert out.getvalue() == b"", "an exception on one message is a log line only: a stranger's message never becomes a message to the person"
    listener.retry = {"1": {"n": 1, "first": 1.0}}
    monkeypatch.setattr(listener, "handle_uid", lambda box, uid: (_ for _ in ()).throw(OSError("connection")))
    with pytest.raises(OSError):
        listener.retry_pending(object(), 1000, 1)      # a lost connection still ends the pass: the bridge starts the provider again


# --- ported from round3.py of the final review ---------------------------------------------------------------------------------------

ROUND3 = [
    ("escaped quotes in a comment, parens escaped too",
     f'{ID}; spf=pass (domain of \\"x\\) ; dmarc=pass header.from=office.example ; \\(y\\"@evil.example) smtp.mailfrom=evil.example; dmarc=fail header.from=office.example', False),
    ("escaped quotes only, the server escapes quotes but not parens, no server dmarc (residual, README)",
     f'{ID}; spf=pass (domain of \\"x) ; dmarc=pass header.from=office.example ; (y\\"@evil.example) smtp.mailfrom=evil.example', True),
    ("the same, and the server also writes its dmarc result",
     f'{ID}; spf=pass (domain of \\"x) ; dmarc=pass header.from=office.example ; (y\\"@evil.example) smtp.mailfrom=evil.example; dmarc=fail header.from=office.example', False),
    ("a nested comment that holds a quote", f'{ID}; dmarc=pass (a (b "c) d) header.from=office.example', False),
    ("a quoted string with parens next to a comment", f'{ID}; spf=pass smtp.mailfrom="a(b)c"@x.example (ok); dmarc=pass header.from=office.example', True),
    ("an unquoted HELO in a comment injects a dmarc, the server writes its own",
     f"{ID}; spf=none (helo a) ; dmarc=pass header.from=office.example ; (b) smtp.helo=x.example; dmarc=fail header.from=office.example", False),
    ("an unquoted HELO in a comment injects a dmarc, the server writes none (residual, README)",
     f"{ID}; spf=none (helo a) ; dmarc=pass header.from=office.example ; (b) smtp.helo=x.example", True),
    ("the DKIM-only path is gone", f"{ID}; dkim=pass header.d=office.example; dmarc=none", False),
]


@pytest.mark.parametrize("label,auth,admitted", ROUND3, ids=[str(n) for n in range(len(ROUND3))])
def test_the_comment_rule_cases_of_round_three(label, auth, admitted):
    assert (admit(raw(auth=auth))[0] is not None) is admitted, label


def test_the_worst_structured_headers_under_the_caps_cost_the_parent_nothing():
    ct = "Content-Type: text/plain; " + "; ".join(f"a{i}=b" for i in range(1700))
    junk = ["In-Reply-To: " + "=?utf-8?q?a?= " * 1150, "Auto-Submitted: " + "=?utf-8?b?YQ==?= " * 900, "Precedence: " + "=?utf-8?b?YQ==?= " * 900,
            "Return-Path: " + "=?utf-8?b?YQ==?= " * 900]
    data = raw(extra=junk).replace(b"Content-Type: text/plain; charset=utf-8", ct.encode(), 1)
    started = time.monotonic()
    update, why = admit(data)
    assert update is None and time.monotonic() - started < provider.TEXT_SECONDS + 5      # a block over 64 KiB is size, else it costs one budget at most
