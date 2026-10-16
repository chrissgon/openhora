#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What every e-mail provider of the workbench shares (providers/CONTRACT.md, "Shared provider code"): the outbox (providers/mailer/smtp.py,
class sender:email) uses it now, and the e-mail channel of the messaging bridge will. A name with an underscore is never listed as an
implementation by providers/resolve.py, so this file is a module the providers load by path, not a provider.

  normalize_address(text)         one plain address, or EmailError. No display name, no comment, no quoted local part, no `<`, no space,
                                  no control character, exactly one `@`, a domain of at least two labels in IDNA ASCII, lower case. The
                                  local part keeps its case (a server may care); compare addresses with address_key().
  address_key(address)            the form two addresses are compared by: the whole address lower-cased. No plus-tag or dot folding.
  header_text(text, what)         a header value from outside: one line (no CR, LF, NUL or other control character), at most 998 characters.
  message_id(domain, seed=None)   `<oh.<32 hex>@domain>`: random, or derived from `seed` (an idempotency key), so a retry has the same one.
  reference_id(text)              a Message-ID the person names in In-Reply-To, checked: one `<...@...>` with no space.
  tls plan                        security_for(...) and the two connect functions: SMTP 465 is TLS from the first byte, 587 requires
                                  STARTTLS and is refused when the server does not offer it; IMAP 993 is TLS from the first byte; the
                                  default context verifies the certificate and the name. No password is sent before TLS. Plain is for a
                                  test only: the variable TEST_PLAIN_ENV set to 1 and a loopback host (the rule of GMAIL_API_BASE in
                                  providers/mailbox/README.md); with the variable set, a host that is not loopback is refused outright.
  build_message(...)              the MIME message: one text/plain part in UTF-8 and each attachment, every header built here from
                                  checked parts, never from text of a caller (a Bcc is never a header).
  canonical(value), digest(value) the JSON text a hash is taken of (sorted keys, ASCII) and its sha256

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import email.header
import email.message
import email.policy
import email.utils
import hashlib
import imaplib
import ipaddress
import json
import os
import re
import secrets
import smtplib
import ssl

TEST_PLAIN_ENV = "OPENHORA_MAIL_TEST_PLAIN"
LOCAL_PART = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*")
LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
ADDRESS_MAX, LOCAL_MAX, DOMAIN_MAX = 254, 64, 253
HEADER_MAX = 998
CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")       # a tab is text in a header; no other control character is
MESSAGE_ID = re.compile(r"<oh\.[0-9a-f]{32}@[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?>")
REFERENCE = re.compile(r"<[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]{1,200}@[A-Za-z0-9.-]{1,200}>")
ATTACHMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,99}")
MEDIA_TYPES = {"pdf": "application/pdf", "txt": "text/plain", "csv": "text/csv", "md": "text/markdown", "png": "image/png",
               "jpg": "image/jpeg",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
               "odt": "application/vnd.oasis.opendocument.text"}
DEFAULT_PORTS = {"smtp": {465: "ssl", 587: "starttls"}, "imap": {993: "ssl"}}
SECURITIES = ("ssl", "starttls", "plain")
EHLO_NAME = "localhost"


class EmailError(ValueError):
    """A value is not in its form (a usage error: exit 2 for a provider). `reason` never holds a secret."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TlsError(Exception):
    """The connection cannot be made as safely as the rules require (TLS missing, refused or not verified): nothing was sent over it."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


# --- addresses and header values ------------------------------------------------------------------------------------------------


def normalize_address(text) -> str:
    """One plain address, domain in lower-case IDNA ASCII; else EmailError. A display name, a comment, a quoted local part, an angle
    bracket, a space, a comma, a control character, a second `@`, a local part over 64 characters, an address over 254 are refused."""
    if not isinstance(text, str) or not text or text != text.strip():
        raise EmailError("an address is plain text with no space around it")
    if "=?" in text:
        raise EmailError("an address holds no =? (an encoded word would change the address after it was approved)")
    if text.count("@") != 1:
        raise EmailError("an address has exactly one @")
    local, domain = text.split("@")
    if not local or len(local) > LOCAL_MAX or local.startswith("-") or not LOCAL_PART.fullmatch(local):
        raise EmailError("the part of an address before @ is plain letters, digits and . ! # $ % & ' * + / = ? ^ _ ` { | } ~ - (no display name, "
                         "comment, quote or space)")
    if not domain or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        raise EmailError("the domain of an address has two or more labels")
    if not domain.isascii():
        raise EmailError("the domain of an address is ASCII: give an international domain in its xn-- form (no folding of letters is done for you)")
    ascii_domain = domain.lower()
    labels = ascii_domain.split(".")
    if len(labels) < 2 or len(ascii_domain) > DOMAIN_MAX or not all(LABEL.fullmatch(label) for label in labels):
        raise EmailError("the domain of an address has two or more labels of letters, digits and hyphens")
    address = f"{local}@{ascii_domain}"
    if len(address) > ADDRESS_MAX:
        raise EmailError(f"an address is at most {ADDRESS_MAX} characters")
    return address


def address_key(address: str) -> str:
    return address.lower()


def domain_of(address: str) -> str:
    return address.rsplit("@", 1)[1]


def header_text(text, what: str, required: bool = True) -> str:
    """A header value taken from outside: one line, no control character, at most 998 characters. EmailError otherwise."""
    if not isinstance(text, str) or (required and not text.strip()):
        raise EmailError(f"{what} is one line of text")
    if CONTROL.search(text) or "\u2028" in text or "\u2029" in text or "\x85" in text:
        raise EmailError(f"{what} is one line: no line break or control character")
    if "=?" in text:
        raise EmailError(f"{what} holds no =? (a mail library decodes an encoded word, and the text sent would not be the text approved)")
    if len(text) > HEADER_MAX:
        raise EmailError(f"{what} is at most {HEADER_MAX} characters")
    return text


def message_id(domain: str, seed=None) -> str:
    """`<oh.<32 hex>@domain>`: derived from `seed` when given (the same seed, the same id), else random."""
    token = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32] if seed else secrets.token_hex(16)
    value = f"<oh.{token}@{domain}>"
    if not MESSAGE_ID.fullmatch(value):
        raise EmailError("the domain does not make a Message-ID")
    return value


def reference_id(text) -> str:
    """A Message-ID named by the caller (In-Reply-To): one `<local@domain>` with no space, else EmailError."""
    if not isinstance(text, str) or not REFERENCE.fullmatch(text) or "=?" in text:
        raise EmailError("a Message-ID is one <local@domain> with no space and no =?")
    return text


def attachment_name(name) -> str:
    """The file name an attachment shows: plain letters, digits, dots, spaces, hyphens and underscores; an extension of MEDIA_TYPES."""
    if not isinstance(name, str) or not ATTACHMENT_NAME.fullmatch(name) or ".." in name or name != name.strip() or name.endswith("."):
        raise EmailError("an attachment name is plain letters, digits, dots, spaces, hyphens and underscores, at most 100 characters")
    if name.rsplit(".", 1)[-1].lower() not in MEDIA_TYPES or "." not in name:
        raise EmailError(f"an attachment name ends in one of: {', '.join(sorted(MEDIA_TYPES))}")
    return name


def media_type(name: str) -> str:
    return MEDIA_TYPES[name.rsplit(".", 1)[-1].lower()]


# --- the connection ---------------------------------------------------------------------------------------------------------------


def is_loopback(host) -> bool:
    if not isinstance(host, str):
        return False
    host = host.strip("[]").split("%", 1)[0]
    if host.lower() in ("localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def test_plain(env=None) -> bool:
    return (os.environ if env is None else env).get(TEST_PLAIN_ENV) == "1"


def security_for(kind: str, host: str, port: int, security=None, env=None) -> str:
    """How to talk to host:port: "ssl", "starttls" or "plain". `kind` is "smtp" or "imap". With no `security`, the port decides (SMTP 465
    ssl, 587 starttls; IMAP 993 ssl) and another port is refused. "plain" only for a test: TEST_PLAIN_ENV is 1 and the host is loopback.
    With TEST_PLAIN_ENV set, a host that is not loopback is refused whatever the security. EmailError otherwise."""
    if test_plain(env) and not is_loopback(host):
        raise EmailError(f"{TEST_PLAIN_ENV} is for tests and reaches loopback hosts only")
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.:\[\]-]{1,253}", host):
        raise EmailError(f"the {kind} host is a host name or an address")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise EmailError(f"the {kind} port is a number from 1 to 65535")
    if security is None:
        security = DEFAULT_PORTS[kind].get(port)
        if security is None:
            raise EmailError(f"the {kind} port {port} says nothing about TLS: use " + " or ".join(str(p) for p in DEFAULT_PORTS[kind])
                             + ", or name the security (ssl or starttls)")
    if security not in SECURITIES:
        raise EmailError(f"the security is one of {', '.join(SECURITIES)}")
    if security == "plain" and not (test_plain(env) and is_loopback(host)):
        raise EmailError("a connection without TLS is for tests only: it needs " + f"{TEST_PLAIN_ENV}=1 and a loopback host")
    if security == "starttls" and kind == "imap":
        raise EmailError("IMAP is reached with TLS from the first byte (port 993)")
    return security


def tls_context() -> ssl.SSLContext:
    return ssl.create_default_context()


def smtp_connect(host: str, port: int, security: str, timeout: float = 30.0, context=None) -> smtplib.SMTP:
    """A greeted SMTP connection that is encrypted before anything private is sent. STARTTLS is required: a server that does not offer
    it is TlsError, and the certificate is verified by `context` (the default context). The caller logs in."""
    context = context or tls_context()
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, local_hostname=EHLO_NAME, timeout=timeout, context=context)
            server.ehlo()
            return server
        server = smtplib.SMTP(host, port, local_hostname=EHLO_NAME, timeout=timeout)
        try:
            server.ehlo()
            if security == "starttls":
                if not server.has_extn("starttls"):
                    raise TlsError("the SMTP server does not offer STARTTLS: nothing was sent over a connection that is not encrypted")
                server.starttls(context=context)
                server.ehlo()
        except BaseException:
            _close(server)
            raise
        return server
    except ssl.SSLError as e:
        raise TlsError(f"the TLS handshake with the SMTP server failed ({e.__class__.__name__}): the certificate is not trusted, or the "
                       "server does not speak TLS here") from None


def imap_connect(host: str, port: int, security: str, timeout: float = 30.0, context=None) -> imaplib.IMAP4:
    """An IMAP connection, TLS from the first byte (or plain for a test). The caller logs in."""
    try:
        if security == "ssl":
            return imaplib.IMAP4_SSL(host, port, ssl_context=context or tls_context(), timeout=timeout)
        return imaplib.IMAP4(host, port, timeout=timeout)
    except ssl.SSLError as e:
        raise TlsError(f"the TLS handshake with the IMAP server failed ({e.__class__.__name__}): the certificate is not trusted, or the "
                       "server does not speak TLS here") from None


def _close(server) -> None:
    try:
        server.close()
    except Exception:       # a connection that is already gone
        pass


# --- the message ------------------------------------------------------------------------------------------------------------------


SUBJECT_PLACEHOLDER = "openhora-subject-placeholder"
ASCII_SUBJECT_MAX = HEADER_MAX - len("Subject: ")


def encode_subject(subject: str) -> str:
    """The Subject value as it goes on the wire, written here and not by the mail library: ASCII as it is, anything else as RFC 2047 encoded
    words that this function folds (Header, 76 columns). The library, given a long non-ASCII subject, folds it into several encoded words and
    leaves the space between two outside them, so the reader gets the words without it; written already encoded, it is not refolded."""
    if subject.isascii():
        if len(subject) > ASCII_SUBJECT_MAX:
            raise EmailError(f"an ASCII subject is at most {ASCII_SUBJECT_MAX} characters, so that no line passes {HEADER_MAX} bytes")
        return subject
    return email.header.Header(subject, "utf-8", maxlinelen=76, header_name="Subject").encode(linesep="\r\n")


class Message(email.message.EmailMessage):
    """An EmailMessage whose Subject is put in the serialised bytes as encode_subject wrote it. `as_bytes` is the one way out of it."""

    subject_wire = ""

    def as_bytes(self, *args, **kwargs):
        data = super().as_bytes(*args, **kwargs)
        head, sep, rest = data.partition(b"\r\n\r\n")
        line = b"Subject: " + SUBJECT_PLACEHOLDER.encode("ascii")
        if not sep or head.count(line) != 1 or not self.subject_wire:
            raise EmailError("the message has no subject to write")
        return head.replace(line, b"Subject: " + self.subject_wire.encode("ascii")) + sep + rest


def build_message(*, from_addr: str, to, cc, subject: str, body: str, attachments, message_id_value: str, in_reply_to=None,
                  date=None) -> Message:
    """The message. Every header is built here from parts that were checked (addresses by normalize_address, text by header_text); the
    Bcc is never a header. `attachments` is [(name, media type, bytes)]. `date` is a datetime, or None to leave the header out (a dry run).
    The body is a single text/plain part in UTF-8, quoted-printable."""
    msg = Message(policy=email.policy.SMTP)
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = SUBJECT_PLACEHOLDER
    msg.subject_wire = encode_subject(header_text(subject, "the subject"))
    msg["Message-ID"] = message_id_value
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    if date is not None:
        msg["Date"] = email.utils.format_datetime(date)
    msg.set_content(body, subtype="plain", charset="utf-8", cte="quoted-printable")
    for name, kind, data in attachments:
        maintype, subtype = kind.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg


HEADERS_SHOWN = ("From", "To", "Cc", "Subject", "Message-ID", "In-Reply-To", "References")
HEADERS_OTHER = ("date", "mime-version", "content-type", "content-transfer-encoding")      # allowed, not compared: made by the library


def inspect_message(data: bytes) -> dict:
    """Read built bytes back, as a receiving server's library would, and say what they hold: {"headers": {name: value} of HEADERS_SHOWN
    (decoded), "text_sha256": of the text part with its trailing line breaks cut, "attachments": [[name, media type, sha256]]}. EmailError
    when the bytes are not a plain message of the expected shape: a line end other than CRLF, a parse defect, a header that is not one of
    HEADERS_SHOWN and HEADERS_OTHER, a header twice, a part that is not the one text part and the attachments."""
    flat = data.replace(b"\r\n", b"")
    if b"\r" in flat or b"\n" in flat:
        raise EmailError("the message has a line end other than CRLF")
    msg = email.message_from_bytes(data, policy=email.policy.default)
    parts = list(msg.walk())
    if msg.defects or any(part.defects for part in parts):
        raise EmailError("the message does not parse cleanly")
    names = [name.lower() for name in msg.keys()]
    if len(set(names)) != len(names) or set(names) - {h.lower() for h in HEADERS_SHOWN} - set(HEADERS_OTHER):
        raise EmailError("the message has a header that was not asked for, or a header twice")
    shown = {name: str(msg[name]) for name in HEADERS_SHOWN if msg[name] is not None}
    leaves = [part for part in parts if not part.is_multipart()]
    body = msg.get_body(("plain",))
    kind = msg.get_content_type()
    if body is None or kind not in ("text/plain", "multipart/mixed") or any(p.is_multipart() for p in parts[1:]):
        raise EmailError("the message is not one text part and its attachments")
    attached = [part for part in leaves if part is not body]
    if len(attached) != len(list(msg.iter_attachments())) or (kind == "text/plain" and attached):
        raise EmailError("the message is not one text part and its attachments")
    text = body.get_content().replace("\r\n", "\n").rstrip("\n")
    return {"headers": shown, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "attachments": [[part.get_filename(), part.get_content_type(), hashlib.sha256(part.get_payload(decode=True)).hexdigest()]
                            for part in attached]}


if __name__ == "__main__":
    import sys
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
