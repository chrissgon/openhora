"""Helpers of the offline tests of providers/messenger/whatsapp-cloud.py (not a test file): the module loaded by path, fake
secrets, a fake Graph API opener, signed webhook payloads and a rig that runs a listener in a thread over a pipe. Nothing here
reaches a network: the only socket is the provider's own server on 127.0.0.1."""
from __future__ import annotations

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
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "whatsapp-cloud.py"


def load(name="messenger_whatsapp_cloud_under_test"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wc = load()

# Fake secrets, built from pieces so that no scanner takes them for a real credential.
TOKEN = "fake-cloud-token-" + "a1b2c3d4" * 4
APP_SECRET = "fakeappsecret" + "0f" * 10
VERIFY = "fake-verify-" + "k9" * 6
SECRETS = {wc.SECRET_TOKEN: TOKEN, wc.SECRET_APP: APP_SECRET, wc.SECRET_VERIFY: VERIFY}
PHONE_ID = "109876543210001"
PATH = "0123456789abcdef0123456789abcdef"
PERSON = "5511900000000"
BSUID = "BR.fakeuserid1234567"
TEXT = "the quarterly plan for northwind-shop is ready"
NOW = 1_800_000_000.0


def settings(**more):
    return {"phone_number_id": PHONE_ID, "port": 0, "template": "decisions_waiting", "template_language": "pt_BR",
            "webhook_path": PATH, **more}


def sign(body: bytes, secret=APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def envelope(messages=(), statuses=(), phone_id=PHONE_ID):
    value = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "15550000000", "phone_number_id": phone_id}}
    if messages:
        value["messages"] = list(messages)
    if statuses:
        value["statuses"] = list(statuses)
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": value}]}]}


def text_message(wamid="wamid.A1", body=TEXT, sender=PERSON, uid=BSUID, at=NOW, context=None):
    message = {"id": wamid, "type": "text", "text": {"body": body}, "timestamp": str(int(at))}
    if sender is not None:
        message["from"] = sender
    if uid is not None:
        message["from_user_id"] = uid
    if context:
        message["context"] = {"id": context}
    return message


def button_reply(wamid="wamid.B1", action="7:approve", context="wamid.CARD", sender=PERSON, uid=BSUID, at=NOW):
    return {"id": wamid, "type": "interactive", "from": sender, "from_user_id": uid, "timestamp": str(int(at)),
            "context": {"id": context}, "interactive": {"type": "button_reply", "button_reply": {"id": action, "title": "Approve"}}}


def template_tap(wamid="wamid.T1", sender=PERSON, uid=BSUID, at=NOW):
    return {"id": wamid, "type": "button", "from": sender, "from_user_id": uid, "timestamp": str(int(at)),
            "button": {"payload": "See decisions", "text": "See decisions"}}


def body_of(payload) -> bytes:
    return json.dumps(payload).encode("utf-8")


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
    body = json.dumps({"error": {"message": body_text, "code": code}}).encode("utf-8")
    return urllib.error.HTTPError("https://graph.invalid/x", status, "x", {}, io.BytesIO(body))


class Opener:
    """A fake Graph API. `rules` maps a substring of "METHOD path" to a function(request) -> dict | Exception, tried in order;
    anything else answers a fresh wamid (messages), a media id (media) or {"id": ...}. Records every call."""

    def __init__(self, rules=None):
        self.rules, self.calls, self.lock, self.count = list(rules or []), [], threading.Lock(), 0

    def open(self, request, timeout=None):
        path = request.full_url.split("/v25.0", 1)[1]
        raw = request.data
        content_type = request.get_header("Content-type")
        body = json.loads(raw) if raw and content_type == "application/json" else raw
        entry = {"method": request.get_method(), "path": path, "body": body, "auth": request.get_header("Authorization"),
                 "content_type": content_type, "timeout": timeout}
        with self.lock:
            self.calls.append(entry)
            self.count += 1
            n = self.count
        for needle, rule in self.rules:
            if needle in f"{entry['method']} {path}":
                answer = rule(entry) if callable(rule) else rule
                if isinstance(answer, Exception):
                    raise answer
                if answer is not None:
                    return Response(answer)
        if path.endswith("/messages"):
            return Response({"messaging_product": "whatsapp", "messages": [{"id": f"wamid.OUT{n}"}]})
        if path.endswith("/media"):
            return Response({"id": f"media.{n}"})
        return Response({"id": PHONE_ID})

    def sent(self):
        return [c["body"] for c in self.calls if c["path"].endswith("/messages")]

    def of_type(self, kind):
        return [b for b in self.sent() if b.get("type") == kind]


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
    """A Listener over a state folder, a fake Graph API and a pipe for stdin, run in a thread. `port` is the server's."""

    def __init__(self, tmp_path, opener=None, clock=None, **options):
        self.folder = str(tmp_path / "wc")
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        self.opener = opener or Opener()
        self.clock = clock or Clock()
        self.out, self.pipe, self.logs = Capture(), Pipe(), []
        self.store = wc.Store(self.folder, self.clock)
        graph = wc.Graph(TOKEN, PHONE_ID, opener=self.opener)
        self.listener = wc.Listener(settings(), dict(SECRETS), self.store, out=self.out, stdin=self.pipe.reader, graph=graph,
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

    def post(self, payload, secret=APP_SECRET, headers=None, raw=None, path=None):
        body = raw if raw is not None else body_of(payload)
        head = {"Content-Type": "application/json", "X-Hub-Signature-256": sign(body, secret)}
        head.update(headers or {})
        return self.request("POST", path or "/" + PATH, body, head)

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
