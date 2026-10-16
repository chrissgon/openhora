"""Tests of providers/_email.py, the code every e-mail provider shares: addresses, header values, Message-IDs, the rules of the
connection and the message. Fictional addresses on `.example`. No network.

Run: uv run --python 3.9 --with pytest==8.4.2 pytest providers/mailer/tests/test_email_helpers.py
"""
from __future__ import annotations

import email
import email.policy
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("email_helpers_under_test", Path(__file__).resolve().parents[2] / "_email.py")
mail = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mail)


@pytest.mark.parametrize("text, expected", [
    ("ana@client.example", "ana@client.example"),
    ("Ana.B+tag@Client.Example", "Ana.B+tag@client.example"),
    ("ana@Bücher.Example", "ana@xn--bcher-kva.example"),
    ("o'neil@sub.client.example", "o'neil@sub.client.example"),
])
def test_a_plain_address_is_normalised_with_the_domain_in_lower_case_ascii(text, expected):
    assert mail.normalize_address(text) == expected


@pytest.mark.parametrize("text", [
    "", " ana@client.example", "ana@client.example ", "ana", "ana@client", "@client.example", "ana@", "ana@@client.example",
    "a@b@client.example", "Ana <ana@client.example>", "<ana@client.example>", "ana@client.example, bo@client.example", "ana (note)@client.example",
    "\"ana\"@client.example", "ana..b@client.example", ".ana@client.example", "ana.@client.example", "ana@client.example\n", "ana@client.example\r\nBcc: x@y.example",
    "ana\x00@client.example", "añá@client.example", "ana@-client.example", "ana@client-.example", "ana@[127.0.0.1]", "x" * 65 + "@client.example",
    "ana@" + "a" * 64 + ".example", "-x@client.example", "--confirmed@client.example", "ana@client.example;bo@client.example", 12, None,
])
def test_a_display_name_comment_quote_break_or_second_at_is_not_an_address(text):
    with pytest.raises(mail.EmailError):
        mail.normalize_address(text)


def test_addresses_are_compared_whole_and_in_lower_case_with_no_folding():
    assert mail.address_key("Ana.B+tag@client.example") == "ana.b+tag@client.example"
    assert mail.address_key("ana.b@client.example") != mail.address_key("anab@client.example")
    assert mail.address_key("ana+x@client.example") != mail.address_key("ana@client.example")
    assert mail.domain_of("ana@client.example") == "client.example"


def test_a_header_value_is_one_line_without_a_control_character_and_not_too_long():
    assert mail.header_text("Invoice\tfor October", "the subject") == "Invoice\tfor October"
    for bad in ("a\nb", "a\rb", "a\r\nBcc: x@y.example", "a\x00b", "a\x1bb", "a b", "a" * 999, "", "   "):
        with pytest.raises(mail.EmailError):
            mail.header_text(bad, "the subject")
    assert mail.header_text("a" * 998, "the subject") == "a" * 998


def test_a_message_id_is_random_or_derived_from_its_seed_and_always_in_the_one_form():
    assert mail.MESSAGE_ID.fullmatch(mail.message_id("office.example"))
    assert mail.message_id("office.example") != mail.message_id("office.example")
    one, two = mail.message_id("office.example", "send-abc"), mail.message_id("office.example", "send-abc")
    assert one == two and one != mail.message_id("office.example", "send-abd") and mail.MESSAGE_ID.fullmatch(one)
    for bad in ("<id@office.example>", "<oh.xyz@office.example>", "oh.0123456789abcdef0123456789abcdef@office.example",
                "<oh.0123456789abcdef0123456789abcdef@office.example>\r\n", "<oh.0123456789abcdef0123456789abcdef@office example>"):
        assert not mail.MESSAGE_ID.fullmatch(bad), bad
    assert mail.reference_id("<abc.def@mail.example>") == "<abc.def@mail.example>"
    for bad in ("abc@mail.example", "<a b@mail.example>", "<abc@mail.example>\n", "<>", "<abc>"):
        with pytest.raises(mail.EmailError):
            mail.reference_id(bad)


def test_an_attachment_name_is_plain_and_ends_in_a_listed_extension():
    assert mail.attachment_name("Invoice October.pdf") == "Invoice October.pdf"
    assert mail.media_type("Plan.XLSX").endswith("spreadsheetml.sheet") and mail.media_type("a.md") == "text/markdown"
    for bad in ("../a.pdf", "a/b.pdf", "a.exe", "a", "a.pdf ", ".pdf", "a..pdf", "a\n.pdf", "a.pdf.", "x" * 101 + ".pdf", "a;b.pdf"):
        with pytest.raises(mail.EmailError):
            mail.attachment_name(bad)


def test_smtp_465_is_tls_from_the_start_587_is_starttls_and_a_port_that_says_nothing_is_refused():
    assert mail.security_for("smtp", "mail.office.example", 465, env={}) == "ssl"
    assert mail.security_for("smtp", "mail.office.example", 587, env={}) == "starttls"
    assert mail.security_for("imap", "mail.office.example", 993, env={}) == "ssl"
    for kind, port in (("smtp", 25), ("smtp", 2525), ("imap", 143)):
        with pytest.raises(mail.EmailError):
            mail.security_for(kind, "mail.office.example", port, env={})
    assert mail.security_for("smtp", "mail.office.example", 2525, "starttls", env={}) == "starttls"      # still TLS, on another port
    with pytest.raises(mail.EmailError):
        mail.security_for("imap", "mail.office.example", 143, "starttls", env={})


def test_plain_needs_the_test_variable_and_a_loopback_host_and_the_variable_refuses_every_other_host():
    on = {mail.TEST_PLAIN_ENV: "1"}
    assert mail.security_for("smtp", "127.0.0.1", 2525, "plain", env=on) == "plain"
    assert mail.security_for("smtp", "localhost", 2525, "plain", env=on) == "plain"
    assert mail.security_for("smtp", "::1", 2525, "plain", env=on) == "plain"
    for env, host in (({}, "127.0.0.1"), ({mail.TEST_PLAIN_ENV: "0"}, "127.0.0.1"), ({mail.TEST_PLAIN_ENV: "yes"}, "127.0.0.1")):
        with pytest.raises(mail.EmailError):
            mail.security_for("smtp", host, 2525, "plain", env=env)
    for host in ("mail.office.example", "10.0.0.5", "192.168.1.9", "8.8.8.8"):
        with pytest.raises(mail.EmailError):
            mail.security_for("smtp", host, 465, env=on)
        with pytest.raises(mail.EmailError):
            mail.security_for("smtp", host, 2525, "plain", env=on)
    assert not mail.is_loopback("127.0.0.1.example") and not mail.is_loopback(None) and mail.is_loopback("127.1.2.3")


def test_the_message_has_to_and_cc_only_one_text_part_and_never_a_bcc_header():
    msg = mail.build_message(from_addr="outbox@office.example", to=["ana@client.example"], cc=["bo@client.example"], subject="Your invoice",
                             body="Hello Ana.\n", attachments=[("Invoice.pdf", "application/pdf", b"%PDF-1.4")],
                             message_id_value="<oh.0123456789abcdef0123456789abcdef@office.example>", in_reply_to="<earlier@client.example>")
    parsed = email.message_from_bytes(msg.as_bytes(), policy=email.policy.default)
    assert parsed["To"] == "ana@client.example" and parsed["Cc"] == "bo@client.example" and parsed["Bcc"] is None
    assert parsed["In-Reply-To"] == "<earlier@client.example>" and parsed["Date"] is None, "a dry run builds no Date"
    assert parsed.get_body(("plain",)).get_content_type() == "text/plain" and parsed.get_body(("html",)) is None
    assert [a.get_filename() for a in parsed.iter_attachments()] == ["Invoice.pdf"]


def test_the_message_builder_refuses_a_subject_with_a_line_break():
    with pytest.raises(mail.EmailError):
        mail.build_message(from_addr="outbox@office.example", to=["ana@client.example"], cc=[], subject="Hi\nBcc: x@y.example", body="Hello.\n",
                           attachments=[], message_id_value="<oh.0123456789abcdef0123456789abcdef@office.example>")


def test_the_digest_is_the_hash_of_the_sorted_ascii_json():
    assert mail.canonical({"b": 1, "a": "é"}) == b'{"a":"\\u00e9","b":1}'
    assert mail.digest({"b": 1, "a": 2}) == mail.digest({"a": 2, "b": 1}) and len(mail.digest({})) == 64
