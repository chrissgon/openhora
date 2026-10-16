"""A fake SMTP server and a fake IMAP server on loopback, written with socketserver, for the tests of providers/mailer/smtp.py (and of the
e-mail channel that will use the same stand-ins). No real mail service, no credential, `.example` addresses. Not a test file.

FakeSmtp understands EHLO, STARTTLS (offered only when asked, and answered with a TLS handshake only when it has a certificate), AUTH PLAIN,
MAIL, RCPT (with a set of refused addresses), DATA (the answer can be refused or dropped), RSET, NOOP and QUIT. Every command line is kept in
`commands` (an AUTH line without its secret); `logins` holds what AUTH PLAIN carried; `messages` holds each message taken.

FakeImap understands CAPABILITY, LOGIN, EXAMINE, UID SEARCH HEADER Message-ID, NOOP and LOGOUT; any other command (SELECT, STORE, COPY, EXPUNGE,
APPEND...) is answered BAD, and every command is kept in `commands`, so a test can assert that nothing that changes a mailbox was ever sent.
"""
from __future__ import annotations

import base64
import re
import shutil
import socketserver
import ssl
import subprocess
import threading


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _Base:
    def __init__(self):
        self.server = _Server(("127.0.0.1", 0), self.handler())
        self.port = self.server.server_address[1]
        self.commands, self.connections = [], 0
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()

    def verbs(self):
        return [c.split(" ", 1)[0].upper() for c in self.commands]


class FakeSmtp(_Base):
    def __init__(self, password="app-password-x", user=None, offer_starttls=False, certificate=None):  # security-scan: allow secret-assignment -- a made-up password for a fake server on loopback; no real account has it
        self.password, self.user = password, user
        self.offer_starttls, self.certificate = offer_starttls, certificate
        self.refuse = set()              # addresses (lower case) answered 550 at RCPT
        self.drop_after_data = False     # read the message, then close the connection without the 250
        self.refuse_data = False         # answer the DATA command itself 554
        self.reject_message = False      # take the message, then answer 554
        self.refuse_login = False
        self.logins, self.messages = [], []
        super().__init__()

    def handler(self):
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def reply(self, text):
                self.wfile.write(text.encode("latin-1") + b"\r\n")
                self.wfile.flush()

            def handle(self):
                with outer.lock:
                    outer.connections += 1
                mail_from, rcpts = None, []
                self.reply("220 fake.example ESMTP ready")
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    text = line.decode("latin-1").rstrip("\r\n")
                    verb = text.split(" ", 1)[0].upper()
                    with outer.lock:
                        outer.commands.append(f"{verb} <redacted>" if verb == "AUTH" else text)
                    if verb == "EHLO":
                        extra = "250-STARTTLS\r\n" if outer.offer_starttls else ""
                        self.wfile.write(f"250-fake.example\r\n{extra}250-AUTH PLAIN\r\n250 8BITMIME\r\n".encode("latin-1"))
                        self.wfile.flush()
                    elif verb == "STARTTLS" and outer.offer_starttls and outer.certificate:
                        self.reply("220 go ahead")
                        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                        context.load_cert_chain(*outer.certificate)
                        try:
                            tls = context.wrap_socket(self.request, server_side=True)
                        except (ssl.SSLError, OSError):
                            return
                        self.rfile, self.wfile = tls.makefile("rb"), tls.makefile("wb")
                    elif verb == "AUTH":
                        parts = text.split(" ")
                        raw = base64.b64decode(parts[2]).split(b"\0") if len(parts) > 2 else []
                        user, secret = (raw[1].decode(), raw[2].decode()) if len(raw) == 3 else ("", "")
                        outer.logins.append((user, secret))
                        if outer.refuse_login or secret != outer.password or (outer.user and user != outer.user):
                            self.reply("535 5.7.8 authentication failed")
                        else:
                            self.reply("235 2.7.0 accepted")
                    elif verb == "MAIL":
                        mail_from, rcpts = re.search(r"<([^>]*)>", text).group(1), []
                        self.reply("250 ok")
                    elif verb == "RCPT":
                        address = re.search(r"<([^>]*)>", text).group(1)
                        if address.lower() in outer.refuse:
                            self.reply("550 5.1.1 no such user")
                        else:
                            rcpts.append(address)
                            self.reply("250 ok")
                    elif verb == "DATA":
                        if outer.refuse_data:
                            self.reply("554 5.5.1 no")
                            continue
                        self.reply("354 end with <CRLF>.<CRLF>")
                        chunks = []
                        while True:
                            data_line = self.rfile.readline()
                            if not data_line or data_line == b".\r\n":
                                break
                            chunks.append(data_line[1:] if data_line.startswith(b"..") else data_line)
                        body = b"".join(chunks)
                        if outer.drop_after_data:
                            with outer.lock:
                                outer.messages.append({"from": mail_from, "to": list(rcpts), "data": body, "answered": False})
                            return
                        if outer.reject_message:
                            self.reply("554 5.7.1 rejected")
                            continue
                        with outer.lock:
                            outer.messages.append({"from": mail_from, "to": list(rcpts), "data": body, "answered": True})
                        self.reply("250 2.0.0 queued")
                    elif verb == "RSET":
                        mail_from, rcpts = None, []
                        self.reply("250 ok")
                    elif verb == "NOOP":
                        self.reply("250 ok")
                    elif verb == "QUIT":
                        self.reply("221 bye")
                        return
                    else:
                        self.reply("502 not implemented")

        return Handler


class FakeImap(_Base):
    def __init__(self, password="app-password-x", folders=("INBOX", "Sent")):  # security-scan: allow secret-assignment -- a made-up password for a fake server on loopback; no real account has it
        self.password, self.folders = password, set(folders)
        self.message_ids = {}        # folder -> {Message-ID: uid}
        self.refuse_login = False
        super().__init__()

    def handler(self):
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def line(self, text):
                self.wfile.write(text.encode("latin-1") + b"\r\n")
                self.wfile.flush()

            def handle(self):
                with outer.lock:
                    outer.connections += 1
                folder = None
                self.line("* OK fake IMAP ready")
                while True:
                    raw = self.rfile.readline()
                    if not raw:
                        return
                    text = raw.decode("latin-1").rstrip("\r\n")
                    tag, _, rest = text.partition(" ")
                    verb, _, args = rest.partition(" ")
                    verb = verb.upper()
                    with outer.lock:
                        outer.commands.append(f"{verb} <redacted>" if verb == "LOGIN" else rest)
                    if verb == "CAPABILITY":
                        self.line("* CAPABILITY IMAP4rev1")
                        self.line(f"{tag} OK done")
                    elif verb == "LOGIN":
                        bits = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', args)
                        values = [a or b for a, b in bits]
                        if outer.refuse_login or len(values) != 2 or values[1].replace("\\\\", "\\").replace('\\"', '"') != outer.password:
                            self.line(f"{tag} NO [AUTHENTICATIONFAILED] login refused")
                        else:
                            self.line(f"{tag} OK logged in")
                    elif verb == "EXAMINE":
                        name = args.strip().strip('"')
                        if name in outer.folders:
                            folder = name
                            self.line("* 0 EXISTS")
                            self.line(f"{tag} OK [READ-ONLY] examined")
                        else:
                            self.line(f"{tag} NO no such folder")
                    elif verb == "UID" and args.upper().startswith("SEARCH"):
                        found = re.search(r'HEADER\s+Message-ID\s+"([^"]*)"', args, re.I)
                        uid = (outer.message_ids.get(folder) or {}).get(found.group(1)) if found and folder else None
                        self.line("* SEARCH" + (f" {uid}" if uid else ""))
                        self.line(f"{tag} OK search done")
                    elif verb == "NOOP":
                        self.line(f"{tag} OK")
                    elif verb == "LOGOUT":
                        self.line("* BYE")
                        self.line(f"{tag} OK bye")
                        return
                    else:
                        self.line(f"{tag} BAD command not allowed here")

        return Handler


def make_certificate(folder):
    """A self-signed certificate and key for localhost in `folder` ((cert, key) paths), or None when the openssl command is not there. A client
    that verifies certificates refuses it: that is the point of the test that uses it."""
    if shutil.which("openssl") is None:
        return None
    cert, key = f"{folder}/cert.pem", f"{folder}/key.pem"
    done = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "2",
                           "-subj", "/CN=localhost"], capture_output=True, check=False)
    return (cert, key) if done.returncode == 0 else None
