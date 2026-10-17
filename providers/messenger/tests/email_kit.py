"""A fake IMAP inbox on loopback for the tests of providers/messenger/email-imap.py (the SMTP side is FakeSmtp of
providers/mailer/tests/fake_mail.py, loaded by path). Not a test file. No real mail service, no credential, `.example` addresses.

FakeInbox understands CAPABILITY, LOGIN, EXAMINE INBOX (with UIDVALIDITY and UIDNEXT), UID SEARCH UID a:b (the `n:*` rule included: a
range that ends in `*` always matches the highest message, even below n), UID FETCH n (RFC822.SIZE), UID FETCH n (BODY.PEEK[]) and
(BODY.PEEK[HEADER]), NOOP and LOGOUT. Any other command is answered BAD, and every command is kept in `commands`, so a test can assert that
the provider never sent a command that changes a mailbox (SELECT, STORE, COPY, EXPUNGE, CLOSE, APPEND...), and never fetched a body without PEEK.
"""
from __future__ import annotations

import re
import socketserver
import threading


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class FakeInbox:
    def __init__(self, password="app-password-x", uidvalidity=1000):  # security-scan: allow secret-assignment -- a made-up password for a fake server on loopback; no real account has it
        self.password, self.uidvalidity = password, uidvalidity
        self.messages = {}           # uid -> raw bytes
        self.sizes = {}              # uid -> a size to report instead of the real one
        self.refuse_login = False
        self.kill = False            # close every connection at its next command (a lost connection)
        self.commands, self.connections = [], 0
        self.lock = threading.Lock()
        self.server = _Server(("127.0.0.1", 0), self.handler())
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def add(self, raw, uid=None):
        with self.lock:
            uid = uid or (max(self.messages, default=0) + 1)
            self.messages[uid] = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        return uid

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()

    def verbs(self):
        return [c.split(" ", 1)[0].upper() for c in self.commands]

    def handler(self):
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            def line(self, text):
                self.wfile.write(text.encode("latin-1") + b"\r\n")
                self.wfile.flush()

            def literal(self, prefix, data, suffix=")"):
                self.wfile.write(prefix.encode("latin-1") + b" {" + str(len(data)).encode() + b"}\r\n" + data + suffix.encode() + b"\r\n")
                self.wfile.flush()

            def handle(self):
                with outer.lock:
                    outer.connections += 1
                self.line("* OK fake IMAP ready")
                while True:
                    raw = self.rfile.readline()
                    if not raw or outer.kill:
                        return
                    text = raw.decode("latin-1").rstrip("\r\n")
                    tag, _, rest = text.partition(" ")
                    verb, _, args = rest.partition(" ")
                    verb = verb.upper()
                    with outer.lock:
                        outer.commands.append(f"{verb} <redacted>" if verb == "LOGIN" else rest)
                        messages = dict(outer.messages)
                    uids = sorted(messages)
                    if verb == "CAPABILITY":
                        self.line("* CAPABILITY IMAP4rev1")
                        self.line(f"{tag} OK done")
                    elif verb == "LOGIN":
                        found = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', args)
                        values = [a or b for a, b in found]
                        if outer.refuse_login or len(values) != 2 or values[1].replace("\\\\", "\\").replace('\\"', '"') != outer.password:
                            self.line(f"{tag} NO [AUTHENTICATIONFAILED] login refused")
                        else:
                            self.line(f"{tag} OK logged in")
                    elif verb == "EXAMINE":
                        self.line(f"* {len(uids)} EXISTS")
                        self.line(f"* OK [UIDVALIDITY {outer.uidvalidity}] uids are valid")
                        self.line(f"* OK [UIDNEXT {(uids[-1] if uids else 0) + 1}] next uid")
                        self.line(f"{tag} OK [READ-ONLY] examined")
                    elif verb == "UID" and args.upper().startswith("SEARCH"):
                        found = re.search(r"UID (\d+):(\d+|\*)", args, re.I)
                        if not found:
                            self.line("* SEARCH " + " ".join(str(u) for u in uids) if uids else "* SEARCH")
                        else:
                            low = int(found.group(1))
                            high = uids[-1] if found.group(2) == "*" and uids else (int(found.group(2)) if found.group(2) != "*" else 0)
                            hit = [u for u in uids if low <= u <= high]
                            if found.group(2) == "*" and uids and not hit:
                                hit = [uids[-1]]
                            self.line("* SEARCH" + "".join(f" {u}" for u in hit))
                        self.line(f"{tag} OK search done")
                    elif verb == "UID" and args.upper().startswith("FETCH"):
                        found = re.match(r"FETCH (\d+) \((.*)\)$", args, re.I)
                        uid = int(found.group(1)) if found else 0
                        item = found.group(2).upper() if found else ""
                        data = messages.get(uid)
                        if data is None:
                            self.line(f"{tag} OK fetch done")
                            continue
                        index = uids.index(uid) + 1
                        if item == "RFC822.SIZE":
                            self.line(f"* {index} FETCH (UID {uid} RFC822.SIZE {outer.sizes.get(uid, len(data))})")
                        elif item == "BODY.PEEK[]":
                            self.literal(f"* {index} FETCH (UID {uid} BODY[]", data)
                        elif item == "BODY.PEEK[HEADER]":
                            head = data.split(b"\r\n\r\n", 1)[0] if b"\r\n\r\n" in data else data.split(b"\n\n", 1)[0]
                            self.literal(f"* {index} FETCH (UID {uid} BODY[HEADER]", head + b"\r\n\r\n")
                        else:
                            self.line(f"{tag} BAD that fetch item is not allowed here")
                            continue
                        self.line(f"{tag} OK fetch done")
                    elif verb == "NOOP":
                        self.line(f"{tag} OK nothing new")
                    elif verb == "LOGOUT":
                        self.line("* BYE")
                        self.line(f"{tag} OK bye")
                        return
                    else:
                        self.line(f"{tag} BAD command not allowed here")

        return Handler
