"""Helpers of the offline tests of providers/messenger/whatsapp-twilio.py (not a test file): the module loaded by path, fake
secrets and SIDs, a reference implementation of Twilio's signature written apart from the provider, a fake Twilio API opener,
signed webhook calls and a rig that runs a listener in a thread over a pipe. Nothing here reaches a network: the only socket is
the provider's own server on 127.0.0.1."""
from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import importlib.util
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "whatsapp-twilio.py"


def load(name="messenger_whatsapp_twilio_under_test"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wt = load()

# Fake secrets and SIDs, built from pieces so that no scanner takes them for a real credential.
KEY_SID = "SK" + "0123456789abcdef" * 2
KEY_SECRET = "fake-twilio-key-secret-" + "q7w8e9" * 4
AUTH = "fakeauthtoken" + "3c" * 10
SECRETS = {wt.SECRET_KEY_SID: KEY_SID, wt.SECRET_KEY_SECRET: KEY_SECRET, wt.SECRET_AUTH: AUTH}
ACCOUNT = "AC" + "fedcba9876543210" * 2
OTHER_ACCOUNT = "AC" + "1111222233334444" * 2
SENDER = "whatsapp:+14155550100"
TEMPLATE = "HX" + "aaaa0000" * 4
BUTTONS = {"1": "HX" + "b1b1b1b1" * 4, "2": "HX" + "b2b2b2b2" * 4, "3": "HX" + "b3b3b3b3" * 4}
HOST = "northwind-laptop.tail1234.ts.net"
PATH = "0123456789abcdef0123456789abcdef"
PUBLIC_URL = f"https://{HOST}/{PATH}"
PERSON = "5511900000000"
FROM = f"whatsapp:+{PERSON}"
BSUID = "BR.fakeuserid1234567"
TEXT = "the quarterly plan for northwind-shop is ready"
NOW = 1_800_000_000.0


def sid(n, prefix="SM"):
    return f"{prefix}{n:032x}"


def settings(**more):
    return {"account_sid": ACCOUNT, "sender": SENDER, "port": 0, "webhook_path": PATH, "public_url": PUBLIC_URL,
            "template_sid": TEMPLATE, "template_button_id": "see-decisions", "buttons": {}, **more}


def reference_signature(token, url, pairs):
    """Twilio's validator (twilio-python request_validator.py compute_signature), written again here and not shared with the
    provider: the URL, then each parameter name in sorted order followed by each of its distinct values in sorted order."""
    params = {}
    for name, value in pairs:
        params.setdefault(name, []).append(value)
    s = url
    for name in sorted(set(params)):
        for value in sorted(set(params[name])):
            s += name + value
    mac = hmac.new(token.encode("utf-8"), s.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode("utf-8")


def as_pairs(fields):
    return list(fields.items()) if isinstance(fields, dict) else list(fields)


def form_body(fields) -> bytes:
    return urllib.parse.urlencode(as_pairs(fields)).encode("utf-8")


def inbound(n=1, body=TEXT, frm=FROM, to=SENDER, account=ACCOUNT, **more):
    fields = {"MessageSid": sid(n), "SmsSid": sid(n), "AccountSid": account, "From": frm, "To": to, "Body": body, "NumMedia": "0",
              "ProfileName": "Maria Souza", "WaId": PERSON}
    fields.update(more)
    return fields


def card_tap(n=2, payload="7:approve", title="Approve", **more):
    return inbound(n, body=title, ButtonPayload=payload, ButtonText=title, ButtonType="QUICK_REPLY", **more)


def status_report(message_sid, code="63016", status="failed", frm=SENDER, to=FROM, account=ACCOUNT):
    return {"MessageSid": message_sid, "MessageStatus": status, "ErrorCode": code, "AccountSid": account, "From": frm, "To": to}


class Response:
    def __init__(self, data):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")

    def read(self, n=-1):
        return self.data if n < 0 else self.data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(status, code=None, body_text="planted-answer-text"):
    body = json.dumps({"code": code, "message": body_text, "status": status, "more_info": "https://twilio.invalid/x"}).encode("utf-8")
    return urllib.error.HTTPError("https://api.invalid/x", status, "x", {}, io.BytesIO(body))


class Opener:
    """A fake Twilio API. `rules` maps a substring of "METHOD url" to a function(call) -> dict | Exception | None, tried in order;
    anything else answers a fresh message SID. Records every call, with the form decoded."""

    def __init__(self, rules=None):
        self.rules, self.calls, self.lock, self.count = list(rules or []), [], threading.Lock(), 0

    def open(self, request, timeout=None):
        form = dict(urllib.parse.parse_qsl(request.data.decode("utf-8"), keep_blank_values=True)) if request.data else {}
        entry = {"method": request.get_method(), "url": request.full_url, "fields": form, "auth": request.get_header("Authorization"),
                 "content_type": request.get_header("Content-type"), "timeout": timeout}
        with self.lock:
            self.calls.append(entry)
            self.count += 1
            n = self.count
        for needle, rule in self.rules:
            if needle in f"{entry['method']} {entry['url']}":
                answer = rule(entry) if callable(rule) else rule
                if isinstance(answer, Exception):
                    raise answer
                if answer is not None:
                    return Response(answer)
        return Response({"sid": sid(0x1000 + n), "status": "queued"})

    def sent(self):
        return [c["fields"] for c in self.calls]

    def texts(self):
        return [f for f in self.sent() if "Body" in f]

    def contents(self):
        return [f for f in self.sent() if "ContentSid" in f]


class Pipe:
    """A binary stdin the test writes to and closes."""

    def __init__(self):
        r, w = os.pipe()
        self.reader, self.writer = os.fdopen(r, "rb"), os.fdopen(w, "wb", buffering=0)

    def send(self, request: dict) -> None:
        self.writer.write(json.dumps(request).encode("utf-8") + b"\n")

    def close(self) -> None:
        self.writer.close()


class Capture:
    """The protocol output: lines the listener wrote, in order."""

    def __init__(self):
        self.lines, self.lock = [], threading.Lock()

    def write(self, line: dict) -> None:
        with self.lock:
            self.lines.append(json.loads(json.dumps(line, ensure_ascii=True)))

    def events(self, name):
        return [l for l in self.lines if l.get("event") == name]

    def answers(self):
        return [l for l in self.lines if "id" in l]

    def updates(self):
        return [l["update"] for l in self.lines if l.get("event") == "update"]


def wait_for(condition, seconds=10.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.01)
    return False


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class Rig:
    """A Listener over a state folder, a fake Twilio API and a pipe for stdin, run in a thread. `port` is the server's."""

    def __init__(self, tmp_path, opener=None, clock=None, config=None, **options):
        self.folder = str(tmp_path / "wt")
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        self.opener = opener or Opener()
        self.clock = clock or Clock()
        self.out, self.pipe, self.logs = Capture(), Pipe(), []
        self.store = wt.Store(self.folder, self.clock)
        api = wt.Twilio(KEY_SID, KEY_SECRET, ACCOUNT, opener=self.opener)
        self.settings = settings(**(config or {}))
        self.listener = wt.Listener(self.settings, dict(SECRETS), self.store, out=self.out, stdin=self.pipe.reader, api=api,
                                    clock=self.clock, log=self.logs.append, **options)
        self.result = []
        self.thread = threading.Thread(target=lambda: self.result.append(self.listener.run()), daemon=True)

    def start(self, ready=True):
        self.thread.start()
        if ready:
            assert wait_for(lambda: self.out.events("ready")), (self.out.lines, self.logs)
        return self

    @property
    def port(self):
        return self.listener.port

    def post(self, fields=None, query="", token=AUTH, url=None, header=None, raw=None, path=None, headers=None):
        """A call signed as Twilio signs it: over the public URL (and the query) and the form."""
        pairs = as_pairs(fields or {})
        body = raw if raw is not None else form_body(pairs)
        signed = url if url is not None else PUBLIC_URL + ("?" + query if query else "")
        head = {"Content-Type": "application/x-www-form-urlencoded",
                "X-Twilio-Signature": header if header is not None else reference_signature(token, signed, pairs)}
        head.update(headers or {})
        target = (path or "/" + PATH) + ("?" + query if query else "")
        return self.request("POST", target, body, head)

    def status(self, fields, **kw):
        return self.post(fields, query=wt.STATUS_QUERY, **kw)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            answer = conn.getresponse()
            return answer.status, answer.read(), dict(answer.getheaders())
        finally:
            conn.close()

    def ask(self, number, chat, message):
        self.pipe.send({"id": number, "op": "send", "chat": chat, "message": message})
        assert wait_for(lambda: any(a["id"] == number for a in self.out.answers())), (self.out.lines, self.logs)
        return next(a for a in self.out.answers() if a["id"] == number)

    def stop(self):
        self.pipe.close()
        self.thread.join(10)
        assert not self.thread.is_alive()
        return self.result[0] if self.result else None


def plain(text, **more):
    return {"text": text, "actions": [], "link": None, "document": None, **more}


def card(text="Plan ready. Approve it?", n=2, **more):
    labels = ["Approve", "Reject", "Later"][:n]
    ids = ["7:approve", "7:reject", "7:later"][:n]
    return {"text": text, "actions": [{"id": i, "label": l} for i, l in zip(ids, labels)], "link": None, "document": None, **more}
