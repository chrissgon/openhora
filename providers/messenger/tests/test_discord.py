"""Offline tests for providers/messenger/discord.py: no network, no Discord, no websockets library, no real token.

The Gateway logic is a state machine fed decoded payloads and a fake clock; the socket is a fake transport; HTTP goes
through a fake opener. Run: uv run --with pytest pytest providers/messenger/tests
"""
from __future__ import annotations

import email.message
import importlib.util
import io
import json
import os
import queue
import random
import re
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "discord.py"
WEBSOCKETS_WAS_LOADED = "websockets" in sys.modules
spec = importlib.util.spec_from_file_location("messenger_discord_under_test", SCRIPT)
discord = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = discord
spec.loader.exec_module(discord)

TOKEN = ".".join(["MTIzNDU2Nzg5MDEyMzQ1Njc4", "GaBcDe", "fakeFAKEfake_never-print-me-0123456789"])   # shaped like a bot token, built in pieces so that no scanner reads it as one
BARE_VALUE = "plain-token-value"          # not shaped like a Discord token: only the exact replacement catches it
TAP_VALUE = "aW50ZXJhY3Rpb24tdG9rZW4" + "x" * 80
USER = "4242424242424242"                   # a made-up snowflake


# --- fakes ----------------------------------------------------------------------------------------------------------

class Reply:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit=None):
        return self.body


def http_error(status, body=None, retry_header=None):
    headers = email.message.Message()
    if retry_header is not None:
        headers["Retry-After"] = str(retry_header)
    return urllib.error.HTTPError("https://discord.com/api/v10/x", status, "x", headers, io.BytesIO(json.dumps(body or {}).encode()))


class Router:
    """A fake opener. `on(method, path regex, *answers)`: an answer is a JSON-able value, an exception to raise, or
    a callable(request, body) returning one of those. The last answer repeats. Every request is recorded."""

    def __init__(self, journal=None):
        self.routes, self.requests, self.journal = [], [], journal if journal is not None else []
        self.lock = threading.Lock()

    def on(self, method, pattern, *answers):
        self.routes.append((method, re.compile(pattern), list(answers)))
        return self

    def open(self, request, timeout=None):
        path = request.full_url.split("/api/v10", 1)[1]
        body = request.data
        parsed = None
        if body and request.get_header("Content-type") == "application/json":
            parsed = json.loads(body.decode("utf-8"))
        with self.lock:
            self.requests.append({"method": request.get_method(), "path": path, "body": parsed, "raw": body,
                                  "headers": {k.lower(): v for k, v in request.header_items()}, "timeout": timeout})
            self.journal.append(("http", request.get_method(), path))
            for method, pattern, answers in self.routes:
                if method == request.get_method() and pattern.search(path):
                    answer = answers.pop(0) if len(answers) > 1 else answers[0]
                    break
            else:
                raise AssertionError(f"no route for {request.get_method()} {path}")
        if callable(answer):
            answer = answer(request, parsed)
        if isinstance(answer, BaseException):
            raise answer
        return Reply(answer)

    def calls(self, method, pattern):
        return [r for r in self.requests if r["method"] == method and re.search(pattern, r["path"])]


def gateway_info(remaining=900, url="wss://gateway.discord.gg"):
    return {"url": url, "shards": 1, "session_start_limit": {"total": 1000, "remaining": remaining, "reset_after": 50_000_000,
                                                              "max_concurrency": 1}}


def router(**kw):
    r = Router(kw.get("journal"))
    r.on("GET", r"^/gateway/bot$", gateway_info())
    r.on("POST", r"^/users/@me/channels$", {"id": "7001"})
    r.on("POST", r"^/channels/7001/messages$", {"id": "8001"})
    r.on("POST", r"/callback$", None)
    return r


class Sink:
    """The protocol descriptor: collects the lines the provider writes, in order."""

    def __init__(self, journal=None):
        self.raw, self.journal, self.lock = [], journal if journal is not None else [], threading.Lock()

    def write(self, data):
        with self.lock:
            self.raw.append(data)
            self.journal.append(("line", json.loads(data.decode("ascii"))))

    def flush(self):
        pass

    @property
    def lines(self):
        with self.lock:
            return [json.loads(d.decode("ascii")) for d in self.raw]

    def events(self, name):
        return [l for l in self.lines if l.get("event") == name]


class Conn:
    def __init__(self, *frames):
        self.frames, self.sent, self.closed = queue.Queue(), [], []
        for f in frames:
            self.frames.put(f)

    def push(self, frame):
        self.frames.put(frame)

    def recv(self, timeout):
        try:
            item = self.frames.get(timeout=min(timeout, 0.03))
        except queue.Empty:
            return None
        if isinstance(item, discord.Closed):
            raise item
        return item if isinstance(item, str) else json.dumps(item)

    def send(self, text):
        self.sent.append(json.loads(text))

    def close(self, code=1000):
        self.closed.append(code)


class Transport:
    def __init__(self, *conns):
        self.conns, self.urls = list(conns), []

    def connect(self, url):
        self.urls.append(url)
        if not self.conns:
            raise discord.ConnectFailed("no connection left in the test")
        item = self.conns.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def hello(ms=45000):
    return {"op": 10, "d": {"heartbeat_interval": ms}}


def ready(seq=1, session="sess-1", url="wss://gateway-us-east1-b.discord.gg"):
    return {"op": 0, "t": "READY", "s": seq, "d": {"session_id": session, "resume_gateway_url": url, "user": {"id": "900"}}}


def dm(content="hello", author=USER, mid="5001", seq=2, **extra):
    d = {"id": mid, "type": 0, "channel_id": "7001", "author": {"id": author}, "content": content}
    d.update(extra)
    return {"op": 0, "t": "MESSAGE_CREATE", "s": seq, "d": d}


def tap(custom_id="7:approve", seq=3, **extra):
    d = {"id": "6001", "token": TAP_VALUE, "type": 3, "context": 1, "user": {"id": USER},
         "data": {"custom_id": custom_id, "component_type": 2}, "message": {"id": "5555"}}
    d.update(extra)
    return {"op": 0, "t": "INTERACTION_CREATE", "s": seq, "d": d}


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Rig:
    """A Listener running in a thread, with a pipe for stdin and a fake transport, router and sink."""

    def __init__(self, monkeypatch, transport, opener=None, token=TOKEN, rng=lambda: 0.5):
        self.journal = []
        self.sink = Sink(self.journal)
        self.opener = opener or router(journal=self.journal)
        monkeypatch.setattr(discord, "OPENER", self.opener)
        self.pauses = []
        read_fd, self.write_fd = os.pipe()
        self.stdin = os.fdopen(read_fd, "rb")
        self.writer = os.fdopen(self.write_fd, "wb")
        self.logs = []
        self.listener = discord.Listener(token, api=discord.Api(token), transport=transport, out=discord.Out(self.sink),
                                         stdin=self.stdin, rng=rng, pause=self.pause, log=self.logs.append)
        self.code = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def pause(self, seconds):
        self.pauses.append(seconds)
        time.sleep(0.01)
        return self.listener.stop.is_set()

    def _run(self):
        self.code = self.listener.run()

    def request(self, rid=1, chat=USER, message=None, op="send"):
        message = message or {"text": "hello", "actions": [], "link": None, "document": None}
        self.writer.write(json.dumps({"id": rid, "op": op, "chat": chat, "message": message}).encode() + b"\n")
        self.writer.flush()

    def answer(self, rid, timeout=5):
        wait_for(lambda: any(l.get("id") == rid for l in self.sink.lines), timeout)
        return next(l for l in self.sink.lines if l.get("id") == rid)

    def eof(self):
        self.writer.close()

    def join(self, timeout=5):
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "the listener did not exit"
        return self.code

    def end(self):
        self.eof()
        return self.join()


def wait_for(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for a condition")


def started(monkeypatch, *frames, opener=None, **kw):
    conn = Conn(hello(), *frames)
    rig = Rig(monkeypatch, Transport(conn), opener, **kw)
    return rig, conn


# --- import hygiene and capabilities --------------------------------------------------------------------------------

def test_the_module_imports_without_the_websockets_library():
    if not WEBSOCKETS_WAS_LOADED:
        assert "websockets" not in sys.modules
    assert discord.PLATFORMS == ("discord",)


def test_the_header_pins_exactly_and_the_platforms_line_is_one_top_level_line():
    header = SCRIPT.read_text(encoding="utf-8").split('"""', 1)[0]
    assert 'requires-python = ">=3.10"' in header
    assert re.search(r'dependencies = \["keyring==25\.7\.0", "websockets==\d+(\.\d+)+"\]', header)
    assert re.search(r'^PLATFORMS = \("discord",\)$', SCRIPT.read_text(encoding="utf-8"), re.M)


def test_capabilities_have_every_key_the_bridge_requires_with_its_type(monkeypatch, capsys):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime"))
    import messaging_provider as provider  # noqa: E402
    caps = discord.CAPABILITIES
    for key, kind in provider.CAPABILITY_KEYS.items():
        assert isinstance(caps[key], kind) and (kind is not int or not isinstance(caps[key], bool)), key
    assert caps["listen"] is True and caps["max_text"] == 1900 and caps["max_buttons"] == 5
    assert caps["max_button_label"] == 80 and caps["url_buttons"] and caps["reply_context"] and caps["documents"]
    assert discord.main(["capabilities", "--platform", "discord"]) == 0
    assert json.loads(capsys.readouterr().out) == caps


@pytest.mark.parametrize("verb", ["receive", "send", "ack"])
def test_the_per_call_verbs_refuse_with_one_sentence(verb, capsys):
    assert discord.main([verb, "--platform", "discord", "--offset", "0", "--chat", "1", "--message-file", "x"]) == 2
    out = capsys.readouterr()
    assert "discord works only in listen mode" in out.err and out.out == ""


def test_another_platform_is_a_usage_error(capsys):
    assert discord.main(["capabilities", "--platform", "telegram"]) == 2


# --- the Gateway state machine --------------------------------------------------------------------------------------

def machine(rng=0.5):
    clock = Clock()
    return discord.Gateway(TOKEN, clock, lambda: rng), clock


def test_hello_answers_with_one_identify_whose_only_intent_is_direct_messages():
    gw, clock = machine()
    gw.begin(False)
    (effect,) = gw.on_payload(hello(40000))
    assert effect[0] == "send" and effect[1]["op"] == 2
    d = effect[1]["d"]
    assert d["intents"] == 1 << 12 == 4096 and d["token"] == TOKEN and set(d) == {"token", "intents", "properties"}
    assert len(json.dumps(effect[1])) <= 4096


def test_heartbeats_start_after_interval_times_jitter_then_every_interval_with_the_last_sequence():
    gw, clock = machine(rng=0.5)
    gw.begin(False)
    gw.on_payload(hello(40000))
    assert gw.next_wake() == 20.0
    clock.t += 19.9
    assert gw.tick() == []
    clock.t += 0.1
    assert gw.tick() == [("send", {"op": 1, "d": None})]
    gw.on_payload(ready(seq=7))
    gw.on_payload({"op": 11})
    clock.t += 39.9
    assert gw.tick() == []
    clock.t += 0.1
    assert gw.tick() == [("send", {"op": 1, "d": 7})]
    assert gw.next_wake() == pytest.approx(40.0)


def test_a_heartbeat_with_no_ack_is_a_zombie_and_the_connection_is_closed_to_resume():
    gw, clock = machine()
    gw.begin(False)
    gw.on_payload(hello(40000))
    gw.on_payload(ready(seq=3))
    clock.t += 20.0
    assert gw.tick()[0][0] == "send"          # a heartbeat, never acknowledged
    clock.t += 40.0
    assert gw.tick() == [("reconnect", True, 0.0)]
    gw.begin(True)
    (effect,) = gw.on_payload(hello())
    assert effect[1] == {"op": 6, "d": {"token": TOKEN, "session_id": "sess-1", "seq": 3}}


def test_an_ack_keeps_the_connection():
    gw, clock = machine()
    gw.begin(False)
    gw.on_payload(hello(40000))
    clock.t += 20.0
    gw.tick()
    gw.on_payload({"op": 11})
    clock.t += 40.0
    assert gw.tick()[0][0] == "send"


def test_op_1_asks_for_a_heartbeat_at_once():
    gw, clock = machine()
    gw.begin(False)
    gw.on_payload(hello(40000))
    gw.on_payload(ready(seq=4))
    clock.t += 3.0
    assert gw.on_payload({"op": 1}) == [("send", {"op": 1, "d": 4})]
    assert gw.next_wake() == pytest.approx(40.0)


def test_reconnect_op_7_resumes():
    gw, clock = machine()
    gw.begin(False)
    gw.on_payload(hello())
    gw.on_payload(ready())
    assert gw.on_payload({"op": 7, "d": None}) == [("reconnect", True, 0.0)]


@pytest.mark.parametrize("rng,expected", [(0.0, 1.0), (1.0, 5.0)])
def test_invalid_session_not_resumable_waits_one_to_five_seconds_and_identifies_again(rng, expected):
    gw, clock = machine(rng=rng)
    gw.begin(False)
    gw.on_payload(hello())
    gw.on_payload(ready())
    assert gw.on_payload({"op": 9, "d": False}) == [("reconnect", False, expected)]
    assert gw.session_id is None and not gw.resumable
    gw.begin(False)
    (effect,) = gw.on_payload(hello())
    assert effect[1]["op"] == 2


def test_invalid_session_resumable_resumes_after_the_wait():
    gw, clock = machine(rng=0.5)
    gw.begin(False)
    gw.on_payload(hello())
    gw.on_payload(ready())
    (effect,) = gw.on_payload({"op": 9, "d": True})
    assert effect[:2] == ("reconnect", True) and 1.0 <= effect[2] <= 5.0 and gw.resumable


def test_at_most_one_identify_in_five_seconds():
    gw, clock = machine()
    assert gw.identify_wait() == 0.0
    gw.begin(False)
    gw.on_payload(hello())
    assert gw.identify_wait() == 5.0
    clock.t += 3.5
    assert gw.identify_wait() == pytest.approx(1.5)
    clock.t += 2.0
    assert gw.identify_wait() == 0.0


def test_ready_is_one_event_per_connection_and_keeps_the_resume_data():
    gw, clock = machine()
    gw.begin(False)
    gw.on_payload(hello())
    assert gw.on_payload(ready()) == [("event", {"event": "ready"})]
    assert gw.on_payload(ready(seq=2)) == []
    assert gw.resumable and gw.resume_url == "wss://gateway-us-east1-b.discord.gg"
    gw.begin(False)
    gw.on_payload(hello())
    assert gw.on_payload(ready()) == [("event", {"event": "ready"})]


def test_a_resume_url_that_is_not_a_discord_gg_wss_url_is_not_kept():
    gw, clock = machine()
    gw.begin(False)
    gw.on_payload(hello())
    gw.on_payload(ready(url="wss://gateway.attacker.example"))
    assert not gw.resumable
    for bad in ["ws://gateway.discord.gg", "wss://discord.gg.attacker.example", "wss://user:pw@gateway.discord.gg",
                "wss://gateway.discord.gg:8443", "https://gateway.discord.gg", "wss://evildiscord.gg", "", None]:
        assert not discord.gateway_url_ok(bad), bad
    for good in ["wss://gateway.discord.gg", "wss://gateway-us-east1-b.discord.gg", "wss://discord.gg/"]:
        assert discord.gateway_url_ok(good), good


def test_close_codes_decide_between_stop_identify_and_resume():
    def plan(code, resumable=True):
        gw, clock = machine()
        gw.begin(False)
        gw.on_payload(hello())
        if resumable:
            gw.on_payload(ready())
        return gw.on_close(code)

    assert plan(4004).fatal[:2] == (3, "not-configured") and "4004" in plan(4004).fatal[2]
    assert plan(4014).fatal[:2] == (3, "not-configured")
    for code in (4010, 4011, 4012, 4013):
        assert plan(code).fatal[:2] == (2, "usage")
    for code in (4007, 4009, 1000, 1001):
        got = plan(code)
        assert got.fatal is None and got.resume is False and 1.0 <= got.wait <= 5.0
    for code in (4000, 4001, 4002, 4003, 4005, 4008, None, 1006):
        assert plan(code).resume is True and plan(code).fatal is None
    assert plan(4000, resumable=False).resume is False
    assert plan(4008).wait == 5.0


def test_a_malformed_hello_reconnects_instead_of_crashing():
    gw, clock = machine()
    gw.begin(False)
    assert gw.on_payload({"op": 10, "d": {}})[0][0] == "reconnect"
    assert gw.on_payload("nonsense") == [] and gw.on_payload({"op": 99}) == []


# --- messages and taps as updates -----------------------------------------------------------------------------------

def test_a_direct_message_is_an_update_with_chat_equal_to_sender_the_user_id():
    got = discord.message_update(dm("hi there")["d"])
    assert got == {"update_id": "5001", "sender": USER, "chat": USER, "private": True, "text": "hi there", "action": None,
                   "action_ref": None, "reply_to": None}
    assert got["chat"] != "7001"          # never the DM channel id


def test_a_reply_carries_the_replied_message_and_a_forward_does_not():
    reply = dm("yes", type=19, message_reference={"type": 0, "message_id": "4999", "channel_id": "7001"})["d"]
    assert discord.message_update(reply)["reply_to"] == "4999"
    untyped = dm("yes", type=19, message_reference={"message_id": "4999"})["d"]
    assert discord.message_update(untyped)["reply_to"] == "4999"
    forward = dm("fwd", type=19, message_reference={"type": 1, "message_id": "4999"})["d"]
    assert discord.message_update(forward)["reply_to"] is None


@pytest.mark.parametrize("change", [
    {"guild_id": "1234"},                          # a server message
    {"author": {"id": USER, "bot": True}},         # a bot, the provider's own messages included
    {"webhook_id": "99"},
    {"type": 7},                                   # a join message
    {"type": 21},
    {"content": ""}, {"content": "   "}, {"content": None},
    {"author": {"id": "not-a-snowflake"}}, {"author": None},
])
def test_what_is_not_a_person_writing_in_a_direct_message_is_ignored(change):
    assert discord.message_update(dm(**change)["d"]) is None


def test_a_tap_in_a_direct_message_is_an_update_with_the_action_and_a_null_action_ref():
    got = discord.interaction_update(tap("7:approve")["d"])
    assert got == {"update_id": "6001", "sender": USER, "chat": USER, "private": True, "text": None, "action": "7:approve",
                   "action_ref": None, "reply_to": "5555"}


@pytest.mark.parametrize("change", [
    {"guild_id": "1234"}, {"context": 0}, {"context": 2}, {"type": 2}, {"type": 5}, {"user": None}, {"user": {"id": "x"}},
    {"data": {"custom_id": ""}}, {"data": {}}, {"data": None}, {"message": None},
])
def test_only_a_component_tap_in_a_bot_dm_is_an_update(change):
    assert discord.interaction_update(tap(**change)["d"]) is None


def test_a_dm_tap_reads_the_user_not_the_member():
    d = tap()["d"]
    d["member"] = {"user": {"id": "1111"}}          # present only in a server; a DM has `user`
    assert discord.interaction_update(d)["sender"] == USER


# --- the listen process ---------------------------------------------------------------------------------------------

def test_a_connection_identifies_says_ready_once_and_asks_the_gateway_for_the_dm_intent_only(monkeypatch):
    rig, conn = started(monkeypatch, ready())
    wait_for(lambda: rig.sink.events("ready"))
    assert rig.sink.events("ready") == [{"event": "ready"}]
    assert conn.sent[0]["op"] == 2 and conn.sent[0]["d"]["intents"] == 4096
    assert rig.listener.transport.urls == ["wss://gateway.discord.gg/?v=10&encoding=json"]
    assert rig.end() == 0
    assert conn.closed == [1000]


def test_a_dm_message_reaches_the_bridge_and_a_server_message_and_a_bots_own_do_not(monkeypatch):
    rig, conn = started(monkeypatch, ready(), dm("from a server", guild_id="1"), dm("from a bot", author="900", mid="5002")["d"] and
                        {"op": 0, "t": "MESSAGE_CREATE", "s": 3, "d": {"id": "5002", "type": 0, "author": {"id": "900", "bot": True},
                                                                       "content": "own"}},
                        dm("real one", mid="5003", seq=4))
    wait_for(lambda: rig.sink.events("update"))
    (update,) = rig.sink.events("update")
    assert update["update"]["text"] == "real one" and update["update"]["chat"] == update["update"]["sender"] == USER
    assert rig.end() == 0


def test_the_callback_type_6_is_posted_before_the_update_is_written(monkeypatch):
    rig, conn = started(monkeypatch, ready(), tap("9:reject"))
    wait_for(lambda: rig.sink.events("update"))
    kinds = [(j[0], j[2] if j[0] == "http" else None) for j in rig.journal if j[0] == "http" and "callback" in j[2]
             or (j[0] == "line" and j[1].get("event") == "update")]
    assert [k[0] for k in kinds] == ["http", "line"]
    (call,) = rig.opener.calls("POST", "/callback")
    assert call["path"] == f"/interactions/6001/{TAP_VALUE}/callback" and call["body"] == {"type": 6}
    assert "authorization" not in call["headers"] and call["timeout"] <= 3
    (update,) = rig.sink.events("update")
    assert update["update"]["action"] == "9:reject" and update["update"]["action_ref"] is None
    assert update["update"]["text"] is None and update["update"]["chat"] == USER
    rig.end()


def test_a_failed_callback_is_logged_by_class_and_the_update_is_still_written(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "callback" not in r[1].pattern]
    opener.on("POST", r"/callback$", http_error(404, {"message": f"unknown {TAP_VALUE}", "code": 10062}))
    rig, conn = started(monkeypatch, ready(), tap(), opener=opener)
    wait_for(lambda: rig.sink.events("update"))
    assert any("button tap failed" in l and "HttpError" in l for l in rig.logs)
    assert TAP_VALUE not in json.dumps(rig.logs) and TAP_VALUE not in json.dumps(rig.sink.lines)
    rig.end()


def test_a_tap_from_a_server_is_neither_answered_nor_emitted(monkeypatch):
    rig, conn = started(monkeypatch, ready(), tap(guild_id="1"), tap(context=0, seq=4), dm("marker", seq=5))
    wait_for(lambda: rig.sink.events("update"))
    assert [u["update"]["text"] for u in rig.sink.events("update")] == ["marker"]
    assert rig.opener.calls("POST", "/callback") == []
    rig.end()


def test_a_dropped_connection_resumes_on_the_resume_url_and_sends_resume(monkeypatch):
    first = Conn(hello(), ready(seq=5), discord.Closed(None))
    second = Conn(hello(), {"op": 0, "t": "RESUMED", "s": 6, "d": {}})
    transport = Transport(first, second)
    rig = Rig(monkeypatch, transport)
    wait_for(lambda: second.sent)
    assert transport.urls == ["wss://gateway.discord.gg/?v=10&encoding=json",
                              "wss://gateway-us-east1-b.discord.gg/?v=10&encoding=json"]
    assert second.sent[0] == {"op": 6, "d": {"token": TOKEN, "session_id": "sess-1", "seq": 5}}
    assert len(rig.opener.calls("GET", "/gateway/bot")) == 1     # a resume asks for no Gateway URL and spends no Identify
    assert len(rig.sink.events("ready")) == 1
    rig.end()


def test_op_7_closes_with_4000_never_1000_or_1001_and_resumes(monkeypatch):
    first = Conn(hello(), ready(seq=5), {"op": 7, "d": None})
    second = Conn(hello())
    rig = Rig(monkeypatch, Transport(first, second))
    wait_for(lambda: second.sent)
    assert first.closed == [4000] and second.sent[0]["op"] == 6
    rig.end()
    assert second.closed == [1000]


def test_a_zombie_connection_is_closed_with_4000_and_resumed(monkeypatch):
    first = Conn(hello(30), ready(seq=2))          # a 30 ms interval; no ACK ever comes
    second = Conn(hello())
    rig = Rig(monkeypatch, Transport(first, second), rng=lambda: 0.0)
    wait_for(lambda: second.sent, 5)
    assert first.closed == [4000]
    assert [m for m in first.sent if m["op"] == 1] and second.sent[0]["op"] == 6
    rig.end()


def test_op_1_gets_a_heartbeat_at_once_over_the_socket(monkeypatch):
    rig, conn = started(monkeypatch, ready(seq=2), {"op": 1, "d": None})
    wait_for(lambda: [m for m in conn.sent if m["op"] == 1])
    assert [m for m in conn.sent if m["op"] == 1][0]["d"] == 2
    rig.end()


def test_invalid_session_not_resumable_identifies_again_after_the_wait_and_the_five_second_gap(monkeypatch):
    first = Conn(hello(), ready(), {"op": 9, "d": False})
    second = Conn(hello())
    rig = Rig(monkeypatch, Transport(first, second), rng=lambda: 0.5)
    wait_for(lambda: second.sent)
    assert first.closed == [4000] and second.sent[0]["op"] == 2
    assert any(abs(p - 3.0) < 1e-9 for p in rig.pauses)          # 1 + 4 * 0.5
    assert any(4.0 < p <= 5.0 for p in rig.pauses)               # the gap since the last Identify
    assert len(rig.opener.calls("GET", "/gateway/bot")) == 2
    rig.end()


@pytest.mark.parametrize("code", [4007, 4009])
def test_close_codes_4007_and_4009_start_a_new_identify(monkeypatch, code):
    first = Conn(hello(), ready(), discord.Closed(code))
    second = Conn(hello())
    rig = Rig(monkeypatch, Transport(first, second))
    wait_for(lambda: second.sent)
    assert second.sent[0]["op"] == 2
    rig.end()


@pytest.mark.parametrize("code,exit_code,kind", [(4004, 3, "not-configured"), (4014, 3, "not-configured"), (4013, 2, "usage"),
                                                  (4010, 2, "usage")])
def test_fatal_close_codes_tell_the_bridge_and_exit(monkeypatch, code, exit_code, kind):
    rig = Rig(monkeypatch, Transport(Conn(hello(), discord.Closed(code))))
    assert rig.join() == exit_code
    (error,) = rig.sink.events("error")
    assert error["kind"] == kind and str(code) in error["reason"] and len(error["reason"]) > 40
    assert TOKEN not in json.dumps(rig.sink.lines)


def test_an_unreachable_gateway_is_retried_by_the_provider_with_error_events_and_backoff(monkeypatch):
    transport = Transport(discord.ConnectFailed("could not open the Gateway connection (OSError)"),
                          discord.ConnectFailed("could not open the Gateway connection (OSError)"), Conn(hello(), ready()))
    rig = Rig(monkeypatch, transport)
    wait_for(lambda: rig.sink.events("ready"))
    errors = rig.sink.events("error")
    assert len(errors) == 2 and all(e["kind"] == "failed" for e in errors)
    assert [p for p in rig.pauses if p >= 1][:2] == [1.0, 2.0]
    rig.end()


def test_a_connection_that_is_accepted_and_dropped_backs_off_instead_of_looping(monkeypatch):
    transport = Transport(*[Conn(hello(), discord.Closed(None)) for _ in range(4)], Conn(hello(), ready()))
    rig = Rig(monkeypatch, transport)
    wait_for(lambda: rig.sink.events("ready"))
    assert [p for p in rig.pauses if p in (1.0, 2.0, 4.0, 8.0)] == [1.0, 2.0, 4.0, 8.0]
    assert len([e for e in rig.sink.events("error") if "before it was ready" in e["reason"]]) == 4
    rig.end()


def test_ready_and_resumed_reset_the_backoff(monkeypatch):
    transport = Transport(Conn(hello(), discord.Closed(None)), Conn(hello(), discord.Closed(None)),
                          Conn(hello(), ready(), discord.Closed(None)),                       # READY: reset
                          Conn(hello(), {"op": 0, "t": "RESUMED", "s": 9, "d": {}}, discord.Closed(None)),   # RESUMED: reset
                          Conn(hello(), discord.Closed(None)), Conn(hello(), ready()))
    rig = Rig(monkeypatch, transport)
    wait_for(lambda: len(rig.sink.events("ready")) == 2 or len(transport.conns) == 0)
    assert [p for p in rig.pauses if p in (1.0, 2.0, 4.0, 8.0)] == [1.0, 2.0, 1.0]
    rig.end()


def test_the_identify_budget_stops_the_provider_below_fifty_with_exit_3_and_a_sentence(monkeypatch):
    opener = Router()
    opener.on("GET", r"^/gateway/bot$", gateway_info(remaining=49))
    transport = Transport(Conn(hello()))
    rig = Rig(monkeypatch, transport, opener)
    assert rig.join() == 3
    (error,) = rig.sink.events("error")
    assert error["kind"] == "not-configured" and "49" in error["reason"] and "reset the token" in error["reason"]
    assert transport.urls == []


def test_fifty_remaining_is_still_allowed(monkeypatch):
    opener = router()
    opener.routes[0] = ("GET", opener.routes[0][1], [gateway_info(remaining=50)])
    rig = Rig(monkeypatch, Transport(Conn(hello(), ready())), opener)
    wait_for(lambda: rig.sink.events("ready"))
    rig.end()


def test_a_gateway_url_that_is_not_discord_gg_is_never_connected_to(monkeypatch):
    opener = Router()
    opener.on("GET", r"^/gateway/bot$", gateway_info(url="wss://gateway.attacker.example"))
    transport = Transport(Conn(hello()))
    rig = Rig(monkeypatch, transport, opener)
    assert rig.join() == 1
    assert transport.urls == [] and "discord.gg" in rig.sink.events("error")[0]["reason"]


def test_a_401_from_the_gateway_lookup_is_not_configured_exit_3(monkeypatch):
    opener = Router()
    opener.on("GET", r"^/gateway/bot$", http_error(401, {"message": "401: Unauthorized", "code": 0}))
    rig = Rig(monkeypatch, Transport(Conn(hello())), opener)
    assert rig.join() == 3 and rig.sink.events("error")[0]["kind"] == "not-configured"


def test_stdin_eof_exits_within_five_seconds_and_closes_the_socket_with_1000(monkeypatch):
    rig, conn = started(monkeypatch, ready())
    wait_for(lambda: rig.sink.events("ready"))
    began = time.time()
    rig.eof()
    assert rig.join(5) == 0
    assert time.time() - began < 5 and conn.closed == [1000]


def test_sigterm_is_the_same_as_the_end_of_stdin(monkeypatch):
    rig, conn = started(monkeypatch, ready())
    wait_for(lambda: rig.sink.events("ready"))
    rig.listener.finish(0)
    assert rig.join(5) == 0 and conn.closed == [1000]


def test_a_blocked_send_does_not_delay_the_exit(monkeypatch):
    gate = threading.Event()
    opener = router()
    opener.routes = [r for r in opener.routes if "channels" not in r[1].pattern or "messages" in r[1].pattern]
    opener.on("POST", r"^/users/@me/channels$", lambda request, body: (gate.wait(30), {"id": "7001"})[1])
    rig, conn = started(monkeypatch, ready(), opener=opener)
    wait_for(lambda: rig.sink.events("ready"))
    rig.request(1)
    wait_for(lambda: opener.calls("POST", "channels$"))
    began = time.time()
    rig.eof()
    assert rig.join(5) == 0 and time.time() - began < 4
    gate.set()


# --- sends ----------------------------------------------------------------------------------------------------------

CARD = {"text": "## Plan #4\n\nBody", "actions": [{"id": "4:approve", "label": "Approve"}, {"id": "4:reject", "label": "Reject"}],
        "link": {"label": "Open the page", "url": "https://northwind.example/p/4"}, "document": None}


def test_a_send_opens_the_dm_channel_once_and_caches_it(monkeypatch):
    rig, conn = started(monkeypatch, ready())
    rig.request(1)
    rig.request(2)
    assert rig.answer(1) == {"id": 1, "ok": True, "message_id": "8001"}
    assert rig.answer(2)["ok"] is True
    (opened,) = rig.opener.calls("POST", "^/users/@me/channels$")
    assert opened["body"] == {"recipient_id": USER}
    assert len(rig.opener.calls("POST", "^/channels/7001/messages$")) == 2
    rig.end()


def test_the_message_body_has_no_mentions_no_embeds_one_button_row_a_link_row_and_the_reply(monkeypatch):
    rig, conn = started(monkeypatch, ready())
    rig.request(1, message=dict(CARD, reply_to="5001"))
    assert rig.answer(1)["ok"] is True
    (posted,) = rig.opener.calls("POST", "^/channels/7001/messages$")
    body = posted["body"]
    assert body["allowed_mentions"] == {"parse": []} and body["flags"] == 4
    assert body["message_reference"] == {"message_id": "5001", "fail_if_not_exists": False}
    rows = body["components"]
    assert [r["type"] for r in rows] == [1, 1]
    assert rows[0]["components"] == [{"type": 2, "style": 1, "label": "Approve", "custom_id": "4:approve"},
                                     {"type": 2, "style": 2, "label": "Reject", "custom_id": "4:reject"}]
    assert rows[1]["components"] == [{"type": 2, "style": 5, "label": "Open the page", "url": "https://northwind.example/p/4"}]
    assert posted["headers"]["authorization"] == f"Bot {TOKEN}" and posted["headers"]["user-agent"].startswith("DiscordBot (")
    assert "message_reference" not in discord.payload_of({"text": "x"})
    rig.end()


def test_five_actions_and_a_link_are_two_rows_not_six_buttons(monkeypatch):
    message = {"text": "x", "actions": [{"id": f"{n}:a", "label": f"A{n}"} for n in range(5)],
               "link": {"label": "L", "url": "https://northwind.example"}, "document": None}
    rows = discord.components(discord.check_message(message))
    assert [len(r["components"]) for r in rows] == [5, 1]
    assert [b["style"] for b in rows[0]["components"]] == [1, 2, 2, 2, 2]
    only_link = discord.components({"text": "x", "link": {"label": "L", "url": "https://n.example"}})
    assert len(only_link) == 1 and only_link[0]["components"][0]["style"] == 5


def test_a_long_label_is_cut_to_80_characters():
    rows = discord.components({"text": "x", "actions": [{"id": "1:a", "label": "L" * 120}]})
    assert len(rows[0]["components"][0]["label"]) == 80


def test_a_document_goes_as_multipart_with_payload_json_and_the_file(monkeypatch):
    rig, conn = started(monkeypatch, ready())
    rig.request(1, message={"text": "see the file", "actions": [], "link": None,
                            "document": {"name": "plan 4/full", "text": "the whole plan\nline two"}})
    assert rig.answer(1)["ok"] is True
    (posted,) = rig.opener.calls("POST", "^/channels/7001/messages$")
    assert posted["headers"]["content-type"].startswith("multipart/form-data; boundary=")
    raw = posted["raw"].decode("utf-8")
    assert 'name="payload_json"' in raw and 'name="files[0]"; filename="plan_4_full.txt"' in raw
    payload = json.loads(raw.split("\r\n\r\n", 2)[1].split("\r\n--")[0])
    assert payload["allowed_mentions"] == {"parse": []} and payload["flags"] == 4
    assert payload["attachments"] == [{"id": 0, "filename": "plan_4_full.txt"}]
    assert "the whole plan\nline two" in raw
    rig.end()


def test_a_429_waits_retry_after_once_and_asks_again(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "messages" not in r[1].pattern]
    opener.on("POST", r"^/channels/7001/messages$", http_error(429, {"message": "slow down", "retry_after": 1.5, "global": False}),
              {"id": "8002"})
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    assert rig.answer(1) == {"id": 1, "ok": True, "message_id": "8002"}
    assert 1.5 in rig.pauses
    assert len(opener.calls("POST", "^/channels/7001/messages$")) == 2
    rig.end()


def test_a_second_429_fails_the_request(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "messages" not in r[1].pattern]
    opener.on("POST", r"^/channels/7001/messages$", http_error(429, {"message": "slow", "retry_after": 2.0}))
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    answer = rig.answer(1)
    assert answer["ok"] is False and answer["kind"] == "failed" and "429" in answer["reason"]
    assert 2.0 in rig.pauses
    assert len(opener.calls("POST", "^/channels/7001/messages$")) == 2          # waited for once, not again
    rig.end()


def test_a_retry_after_over_thirty_seconds_fails_at_once_without_waiting(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "messages" not in r[1].pattern]
    opener.on("POST", r"^/channels/7001/messages$", http_error(429, {"message": "slow", "retry_after": 600.0}))
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    answer = rig.answer(1)
    assert answer["ok"] is False and "429" in answer["reason"]
    assert not any(p >= 1 for p in rig.pauses)
    assert len(opener.calls("POST", "^/channels/7001/messages$")) == 1
    rig.end()


def test_one_request_has_one_wait_budget_for_the_channel_call_and_the_post(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "channels" not in r[1].pattern or "gateway" in r[1].pattern]
    opener.on("POST", r"^/users/@me/channels$", http_error(429, {"retry_after": 20.0}), {"id": "7001"})
    opener.on("POST", r"^/channels/7001/messages$", http_error(429, {"retry_after": 20.0}), {"id": "8001"})
    opener.on("POST", r"/callback$", None)
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    answer = rig.answer(1)
    assert answer["ok"] is False and "429" in answer["reason"]          # 20 s spent, the second 20 s does not fit in 30
    assert [p for p in rig.pauses if p >= 1] == [20.0]
    rig.end()


def test_a_retry_after_header_is_read_when_the_body_has_none(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "messages" not in r[1].pattern]
    opener.on("POST", r"^/channels/7001/messages$", http_error(429, {}, retry_header=2), {"id": "8003"})
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    assert rig.answer(1)["ok"] is True and 2.0 in rig.pauses
    rig.end()


def test_a_401_answers_the_request_writes_the_error_event_and_exits_3(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "channels$" not in r[1].pattern or "messages" in r[1].pattern]
    opener.on("POST", r"^/users/@me/channels$", http_error(401, {"message": "401: Unauthorized", "code": 0}))
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    assert rig.join() == 3
    answer = rig.answer(1)
    assert answer["ok"] is False and answer["kind"] == "not-configured"
    (error,) = rig.sink.events("error")
    assert error["kind"] == "not-configured" and "token" in error["reason"]


def test_a_403_answers_the_request_with_the_dm_sentence_and_the_bridge_keeps_going(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "messages" not in r[1].pattern]
    opener.on("POST", r"^/channels/7001/messages$", http_error(403, {"message": "Cannot send messages to this user", "code": 50007}),
              {"id": "8009"})
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    answer = rig.answer(1)
    assert answer == {"id": 1, "ok": False, "kind": "failed", "reason": discord.FORBIDDEN_SENTENCE}
    assert "share a server" in answer["reason"] and "allow direct messages" in answer["reason"]
    assert not rig.listener.stop.is_set() and rig.sink.events("error") == []
    rig.request(2)
    assert rig.answer(2)["ok"] is True
    rig.end()


def test_a_403_with_another_code_gets_a_generic_sentence(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "messages" not in r[1].pattern]
    opener.on("POST", r"^/channels/7001/messages$", http_error(403, {"message": "Missing Access", "code": 50001}))
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    reason = rig.answer(1)["reason"]
    assert "50001" in reason and "share a server" not in reason
    rig.end()


def test_a_403_on_opening_the_dm_channel_is_the_same_answer(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "channels$" not in r[1].pattern or "messages" in r[1].pattern]
    opener.on("POST", r"^/users/@me/channels$", http_error(403, {"message": "x", "code": 50007}))
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    assert rig.answer(1)["reason"] == discord.FORBIDDEN_SENTENCE
    rig.end()


@pytest.mark.parametrize("message", [
    {"text": ""}, {"text": "x" * 1901}, {"text": "x", "actions": [{"id": "a", "label": "b"}] * 6},
    {"text": "x", "actions": [{"id": "i" * 101, "label": "b"}]}, {"text": "x", "actions": [{"id": "", "label": "b"}]},
    {"text": "x", "actions": [{"id": "a"}]}, {"text": "x", "link": {"label": "L", "url": "javascript:alert(1)"}},
    {"text": "x", "link": {"label": "", "url": "https://n.example"}},
    {"text": "x", "link": {"label": "L", "url": "https://n.example/" + "p" * 500}}, {"text": "x", "document": {"name": "n", "text": ""}},
    {"text": "x", "document": "nope"}, {"text": "x", "reply_to": "abc"}, "not an object",
])
def test_a_request_that_does_not_fit_is_answered_usage_and_nothing_is_posted(monkeypatch, message):
    rig, conn = started(monkeypatch, ready())
    rig.request(1, message=message)
    answer = rig.answer(1)
    assert answer["ok"] is False and answer["kind"] == "usage" and answer["reason"]
    assert rig.opener.calls("POST", "messages$") == [] and rig.opener.calls("POST", "^/users/@me/channels$") == []
    rig.end()


@pytest.mark.parametrize("chat", ["abc", "", "12 34", "../../x", "1" * 30])
def test_a_chat_that_is_not_a_user_id_is_a_usage_answer(monkeypatch, chat):
    rig, conn = started(monkeypatch, ready())
    rig.request(1, chat=chat)
    assert rig.answer(1)["kind"] == "usage"
    rig.end()


def test_an_unknown_op_and_a_line_that_is_not_json_do_not_stop_the_process(monkeypatch):
    rig, conn = started(monkeypatch, ready())
    rig.writer.write(b"this is not json\n")
    rig.writer.flush()
    rig.request(1, op="ack")
    assert rig.answer(1)["kind"] == "usage"
    rig.request(2)
    assert rig.answer(2)["ok"] is True
    rig.end()


def test_a_request_line_over_one_mebibyte_is_dropped_and_the_next_one_is_served(monkeypatch):
    rig, conn = started(monkeypatch, ready())
    rig.writer.write(b"x" * (discord.MAX_REQUEST_LINE + 50) + b"\n")
    rig.writer.flush()
    rig.request(2)
    assert rig.answer(2)["ok"] is True
    assert any("over 1 MiB" in l for l in rig.logs)
    rig.end()


def test_a_stale_dm_channel_is_forgotten_after_a_404(monkeypatch):
    opener = router()
    opener.routes = [r for r in opener.routes if "messages" not in r[1].pattern]
    opener.on("POST", r"^/channels/7001/messages$", http_error(404, {"message": "Unknown Channel", "code": 10003}), {"id": "8010"})
    rig, conn = started(monkeypatch, ready(), opener=opener)
    rig.request(1)
    assert rig.answer(1)["ok"] is False
    rig.request(2)
    assert rig.answer(2)["ok"] is True
    assert len(opener.calls("POST", "^/users/@me/channels$")) == 2
    rig.end()


# --- rendering ------------------------------------------------------------------------------------------------------

render = discord.render_discord


def test_plain_markdown_is_kept():
    text = "## Heading\n- item **bold** and _it_\n> quote\n-# small print\n1. one\n@everyone and @here stay text"
    assert render(text) == text


@pytest.mark.parametrize("source,expected", [
    ("[site](https://northwind.example/a)", "site (https://northwind.example/a)"),
    ("[site](<https://northwind.example/a>)", "site (https://northwind.example/a)"),
    ('[site](https://northwind.example/a "a title")', "site (https://northwind.example/a)"),
    ("[site](https://northwind.example/a 'a title')", "site (https://northwind.example/a)"),
    ("see [a](https://x.example/1) and [b](https://x.example/2).", "see a (https://x.example/1) and b (https://x.example/2)."),
    ("[[inner](https://x.example/i)](https://x.example/o)", "inner (https://x.example/i) (https://x.example/o)"),
])
def test_masked_links_become_text_with_the_url(source, expected):
    assert render(source) == expected


def test_a_masked_link_that_is_not_recognised_is_still_not_left_as_a_link():
    out = render("[odd](https://x.example/a b)")
    assert "](" not in out


@pytest.mark.parametrize("opener", ["<@123>", "<@!123>", "<@&77>", "<#456>", "<t:1:R>", "<t:1>", "<:smile:1>", "<a:wave:1>",
                                    "</cmd:123>", "<id:customize>"])
def test_the_openers_of_mentions_channels_timestamps_emoji_commands_and_guild_links_are_escaped(opener):
    assert render(f"hi {opener} there") == f"hi \\{opener} there"


def test_an_escaped_opener_is_not_escaped_twice_and_an_escaped_backslash_does_not_hide_one():
    assert render("\\<@1>") == "\\<@1>"
    assert render("\\\\<@1>") == "\\\\\\<@1>"
    assert render("\\\\\\<@1>") == "\\\\\\<@1>"


def test_other_angle_brackets_are_left_alone():
    assert render("a <b> and 1 < 2 > 0 and <https://x.example>") == "a <b> and 1 < 2 > 0 and <https://x.example>"


def test_spoilers_are_escaped_and_a_single_pipe_is_not():
    assert render("a ||hidden|| b") == "a \\|\\|hidden\\|\\| b"
    assert render("a | b") == "a | b"
    assert "||" not in render("x |||y||| z").replace("\\|", "")


def test_code_spans_and_fences_are_not_touched():
    for text in ["`<@123> [a](b) ||x||`", "``a ` <@1> ``", "```\n<@123> [a](https://x.example) ||x||\n```",
                 "```python\nprint('<t:1:R>')\n```", "x `<@1>` y <@2>"]:
        out = render(text)
        assert out.replace("\\<@2>", "<@2>") == text, text
    assert render("x `<@1>` y <@2>") == "x `<@1>` y \\<@2>"


def test_a_fence_that_never_closes_is_shown_as_text_so_it_cannot_swallow_the_rest():
    out = render("```\nnever closed <@1>")
    assert out == "\\`\\`\\`\nnever closed \\<@1>"


@pytest.mark.parametrize("text", [
    "```\ncode\n```x\n[a](http://e.com)\n```",                      # a closer with text after it
    "```\nfoo ``` [a](http://e.com)\n```",                           # a ``` in the middle of a line closes the block
    "```py\nx\n```python\n[a](http://e.com) <@1> ||s||\n```",
    "```\n[a](http://e.com)\n``` trailing\n```",
    "text ``` [a](http://e.com) <@1> ||s||",                           # a stray fence mark inside a line
    "`ok` and ``` stray `[a](http://e.com)`",
])
def test_a_fence_is_code_only_when_discord_would_read_it_the_same_way(text):
    out = render(text)
    assert "[a](" not in out.replace("]\\(", "") or "[a](" not in out
    assert "http://e.com" in out
    assert not LIVE_OPENER.search(out)
    assert not re.search(r"(?<!\\)\|\|", out)
    assert "```" not in out.replace("\\`", "")                          # no live fence mark is left for Discord to read


def test_a_clean_fence_still_keeps_its_content():
    text = "before [a](http://e.com)\n```py\n[a](http://e.com) <@1> ||s||\n```\nafter <@2>"
    assert render(text) == "before a (http://e.com)\n```py\n[a](http://e.com) <@1> ||s||\n```\nafter \\<@2>"


def test_table_lines_are_fenced_and_not_read():
    table = "| a | b |\n|---|---|\n| <@1> | [x](https://x.example) |"
    out = render("before\n" + table + "\nafter [t](https://x.example)")
    assert out == "before\n```\n" + table + "\n```\nafter t (https://x.example)"
    assert render("  | indented |") == "```\n  | indented |\n```"


def test_a_table_cell_cannot_close_the_fence_it_sits_in():
    out = render("| ``` |\n| ```x [a](http://e.com) |")
    assert out.count("```") == 2 + 0 and "\u200b" in out           # a real zero-width space, not six characters
    assert "\\u200b" not in out
    assert "\u200b" not in SCRIPT.read_text(encoding="utf-8")         # and none in the source either


EFFECT_COMMANDS = ["python3 /w/ops.py approve --project /p/northwind-shop --id 7 --sha256 " + "e" * 64,
                   "run '/p/_a_/__init__/*' \"q\" 'a b' <@x> & y", "echo `hi`", "echo ``hi``", "`lead", "trail`", "a ` b `` c ``` d",
                   " spaced ", "echo '<@123>' '||' '[a](b)'"]


@pytest.mark.parametrize("command", EFFECT_COMMANDS)
def test_a_real_effect_card_keeps_its_command_byte_for_byte(command):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime"))
    import messaging_cards as cards  # noqa: E402
    import operations  # noqa: E402
    item = {"kind": "effect", "id": 7, "title": "Pull request in [the repo](https://x.example)", "text": "Open it",
            "actions": ["approved", "rejected"], "payload_sha256": "e" * 64}
    card = cards.build("northwind-shop", item, dict(discord.CAPABILITIES), {"messaging": {"approve": True}}, "text", None,
                       operations=operations, effect_command=command)
    text = card["message"]["text"]
    assert len(text) <= discord.CAPABILITIES["max_text"]
    out = render(text)
    assert cards.code_span(command) in out.split("\n")
    assert out.split("\n")[-1] == cards.code_span(command)
    assert "the repo (https://x.example)" in out


LIVE_OPENER = re.compile(r"(?<!\\)(?:\\\\)*<(?=@|#|t:|:|a:|/|id:)")


def test_a_text_that_renders_over_2000_characters_is_still_safe_and_cut_with_a_closing_line():
    worst = "<@1>" * 475                                 # 1900 characters; every opener grows by one
    assert len(worst) == 1900 and len(render(worst)) == 2375
    sent = discord.rendered_for_send(worst)
    assert len(sent) <= 2000 and sent.endswith("\n(continues on the page)")
    assert not LIVE_OPENER.search(sent) and "\\<@1>" in sent
    links = "[a](https://x.example/1) " * 70 + "<t:1:R> ||x||\n" * 10
    sent = discord.rendered_for_send(links[:1900])
    assert "](" not in sent.replace("]\\(", "") and len(sent) <= 2000


def test_the_fallback_drops_the_table_fences_before_it_cuts(monkeypatch):
    table = "| a |\n" * 280 + "[l](https://x.example) <@1>"
    monkeypatch.setattr(discord, "DISCORD_TEXT_LIMIT", 1710)
    assert len(render(table)) > 1710 and len(render(table, fence_tables=False)) <= 1710
    sent = discord.rendered_for_send(table)
    assert "```" not in sent and "[l](" not in sent and "\\<@1>" in sent and not sent.endswith("(continues on the page)")


def test_a_full_card_of_every_kind_always_fits_and_is_safe():
    for text in (("<@1> | x\n| row\n" * 200)[:1900], ("[a](https://x.example)\n" * 40 + "<t:1:R> ||x||\n" * 40)[:1900],
                 "x" * 1900, "||" * 950, "| a |\n" * 300 + "<@1>"):
        sent = discord.rendered_for_send(text[:1900])
        assert len(sent) <= 2000 and not LIVE_OPENER.search(sent.replace("```", ""))


def test_random_text_is_safe_outside_code_and_never_longer_than_discord_takes():
    rng = random.Random(7)
    alphabet = ["<", "@", "#", "t:", ":", "a:", "/", "id:", "|", "[", "]", "(", ")", "\\", " ", "\n", "x", "1", "http://u", "`"]
    opener = re.compile(r"(?<!\\)(?:\\\\)*<(?=@|#|t:|:|a:|/|id:)")
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 60)))
        out = discord.rendered_for_send(text)
        assert len(out) <= 2000
        if "`" in text or any(l.lstrip().startswith("|") for l in text.split("\n")):
            continue
        assert not opener.search(out), (text, out)
        assert not re.search(r"\]\(", out.replace("]\\(", "")), (text, out)   # Discord's link needs ]( side by side
        assert not re.search(r"(?<!\\)\|\|", out), (text, out)


# --- HTTP, the token and redaction ----------------------------------------------------------------------------------

def test_a_redirect_is_refused_and_the_authorization_header_is_never_forwarded():
    handler = discord.RefuseRedirect()
    with pytest.raises(discord.ProviderError) as e:
        handler.redirect_request(None, io.BytesIO(b""), 302, "Found", {}, "https://attacker.example/")
    assert "redirect" in str(e.value) and "attacker" not in str(e.value)
    assert any(isinstance(h, discord.RefuseRedirect) for h in discord.OPENER.handlers)


FAILURES = [
    urllib.error.URLError(f"connection to https://discord.com/api/v10?t={TOKEN} refused"),
    urllib.error.URLError(OSError(f"host {TOKEN}")),
    OSError(f"broken {TOKEN} {BARE_VALUE}"),
    ValueError(f"{TOKEN}"),
    http_error(500, {"message": f"oops {TOKEN} {BARE_VALUE} {TAP_VALUE}", "code": 0}),
    http_error(400, {"message": f"bad {TAP_VALUE}"}),
    http_error(401, {"message": TOKEN}),
]


@pytest.mark.parametrize("failure", FAILURES)
def test_no_error_path_of_the_api_shows_a_token(monkeypatch, failure):
    monkeypatch.setattr(discord, "OPENER", Router().on("POST", r".*", failure).on("GET", r".*", failure))
    api = discord.Api(BARE_VALUE)
    for call in (lambda: api.request("GET", "/users/@me"),
                 lambda: api.request("POST", f"/interactions/1234/{TAP_VALUE}/callback", {"type": 6}, auth=False)):
        with pytest.raises(discord.ProviderError) as e:
            call()
        shown = discord.redact(e.value, BARE_VALUE)
        for secret in (TOKEN, BARE_VALUE, TAP_VALUE):
            assert secret not in str(e.value) and secret not in shown


def test_redact_masks_the_exact_token_a_token_shape_an_interaction_path_and_a_long_word():
    text = f"x {BARE_VALUE} y {TOKEN} z /interactions/123/abc_DEF-1/callback w {'q' * 70}"
    out = discord.redact(text, BARE_VALUE)
    assert BARE_VALUE not in out and TOKEN not in out and "abc_DEF-1" not in out and "q" * 60 not in out
    assert "/interactions/<id>/<token>/callback" in out


def test_check_verifies_the_token_with_users_me(monkeypatch, capsys):
    monkeypatch.setenv("MESSENGER_DISCORD_BOT_TOKEN", TOKEN)
    opener = Router().on("GET", r"^/users/@me$", {"id": "900", "username": "northwind-bot", "bot": True})
    monkeypatch.setattr(discord, "OPENER", opener)
    assert discord.main(["--check", "--platform", "discord"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}
    assert opener.requests[0]["headers"]["authorization"] == f"Bot {TOKEN}"


def test_check_with_a_refused_token_is_exit_3_and_prints_no_token(monkeypatch, capsys):
    monkeypatch.setenv("MESSENGER_DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(discord, "OPENER", Router().on("GET", r".*", http_error(401, {"message": f"401 {TOKEN}"})))
    assert discord.main(["--check", "--platform", "discord"]) == 3
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and "refused the bot token" in out.err


def test_check_with_a_service_failure_is_exit_1_and_prints_no_token(monkeypatch, capsys):
    monkeypatch.setenv("MESSENGER_DISCORD_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(discord, "OPENER", Router().on("GET", r".*", urllib.error.URLError(f"x {TOKEN}")))
    assert discord.main(["--check", "--platform", "discord"]) == 1
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_a_missing_token_is_not_configured_and_names_the_way_to_store_one(monkeypatch, capsys):
    class NoSecrets:
        @staticmethod
        def resolve(name, **kw):
            assert name == "MESSENGER_DISCORD_BOT_TOKEN"
            return None

    monkeypatch.setattr(discord, "secret_resolver", lambda: NoSecrets)
    assert discord.main(["--check", "--platform", "discord"]) == 3
    assert "keyring set openhora messenger-discord" in capsys.readouterr().err
    assert discord.main(["listen", "--platform", "discord"]) == 3


def test_a_surprise_in_main_prints_the_class_only(monkeypatch, capsys):
    monkeypatch.setattr(discord, "run", lambda argv: (_ for _ in ()).throw(RuntimeError(f"boom {TOKEN}")))
    assert discord.main(["--check"]) == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err and TOKEN not in err


def test_the_secret_is_in_the_registry_with_the_username_and_this_reader():
    resolver = importlib_resolver()
    secret = resolver.REGISTRY["MESSENGER_DISCORD_BOT_TOKEN"]
    assert secret.store_username == "messenger-discord" and secret.readers == ("providers/messenger/discord.py",)
    assert "no server permissions" in secret.permission


def importlib_resolver():
    path = Path(__file__).resolve().parents[2] / "secrets" / "resolver.py"
    s = importlib.util.spec_from_file_location("resolver_for_discord_test", path)
    module = importlib.util.module_from_spec(s)
    sys.modules[s.name] = module
    s.loader.exec_module(module)
    return module


def test_the_websockets_transport_says_so_when_the_library_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "websockets", None)
    monkeypatch.setitem(sys.modules, "websockets.sync", None)
    monkeypatch.setitem(sys.modules, "websockets.sync.client", None)
    with pytest.raises(discord.ConnectFailed) as e:
        discord.WebsocketsTransport().connect("wss://gateway.discord.gg/?v=10&encoding=json")
    assert "uv run" in str(e.value)


def test_the_websockets_transport_with_a_fake_library_sets_the_logger_and_maps_a_close_code(monkeypatch):
    import logging
    import types

    class FakeWs:
        def __init__(self):
            self.closed = []

        def recv(self, timeout=None):
            raise TimeoutError

        def send(self, text):
            raise Exception(f"closed with {TOKEN}")

        def close(self, code=1000):
            self.closed.append(code)

    class Rcvd:
        code = 4004

    ws = FakeWs()
    calls = {}

    def connect(url, **kw):
        calls.update(url=url, **kw)
        return ws

    package = types.ModuleType("websockets")
    sync = types.ModuleType("websockets.sync")
    client = types.ModuleType("websockets.sync.client")
    client.connect = connect
    package.sync, sync.client = sync, client
    for name, module in (("websockets", package), ("websockets.sync", sync), ("websockets.sync.client", client)):
        monkeypatch.setitem(sys.modules, name, module)
    logging.getLogger("websockets").setLevel(logging.DEBUG)
    conn = discord.WebsocketsTransport().connect("wss://gateway.discord.gg/?v=10&encoding=json")
    assert logging.getLogger("websockets").level >= logging.WARNING
    assert conn.recv(0.1) is None
    with pytest.raises(discord.Closed) as e:
        conn.send("x")
    assert e.value.code is None and TOKEN not in str(e.value)
    conn.close(4000)
    assert ws.closed == [4000]
    assert "ping_interval" in calls and calls["ping_interval"] is None        # Discord has its own heartbeat

    class Closing(Exception):
        rcvd = Rcvd()

    ws.recv = lambda timeout=None: (_ for _ in ()).throw(Closing())
    with pytest.raises(discord.Closed) as e:
        conn.recv(0.1)
    assert e.value.code == 4004


# --- the process: nothing but protocol on the protocol descriptor ----------------------------------------------------

DRIVER = '''
import importlib.util, os, sys, time, json
spec = importlib.util.spec_from_file_location("d", sys.argv[1])
d = importlib.util.module_from_spec(spec); sys.modules["d"] = d; spec.loader.exec_module(d)
TOKEN = sys.argv[2]

class Reply:
    def __init__(self, body): self.body = json.dumps(body).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=None): return self.body

class Opener:
    def open(self, request, timeout=None):
        path = request.full_url.split("/api/v10", 1)[1]
        print("library noise: GET", path)
        if path == "/gateway/bot":
            return Reply({"url": "wss://gateway.discord.gg", "session_start_limit": {"remaining": 900, "reset_after": 1}})
        if path == "/users/@me/channels":
            return Reply({"id": "7001"})
        raise OSError("failure " + TOKEN)

class Conn:
    def __init__(self): self.frames = [{"op": 10, "d": {"heartbeat_interval": 45000}},
                                       {"op": 0, "t": "READY", "s": 1, "d": {"session_id": "s", "resume_gateway_url": "wss://gateway.discord.gg"}}]
    def recv(self, timeout):
        print("library noise: recv")
        if self.frames: return json.dumps(self.frames.pop(0))
        time.sleep(min(timeout, 0.05)); return None
    def send(self, text): print("library noise: send")
    def close(self, code=1000): print("library noise: close", code)

class Transport:
    def connect(self, url):
        print("library noise: connect", url); sys.stdout.write("raw write to stdout\\n"); return Conn()

d.OPENER = Opener()
code = d.run_listen(TOKEN, transport=Transport())
sys.stderr.flush(); os._exit(code)
'''


def test_the_protocol_descriptor_gets_only_json_lines_a_library_print_goes_to_stderr_and_stdin_eof_ends_it(tmp_path):
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-I", str(driver), str(SCRIPT), TOKEN], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=dict(os.environ))
    try:
        assert json.loads(proc.stdout.readline()) == {"event": "ready"}
        request = {"id": 1, "op": "send", "chat": USER, "message": {"text": "hi", "actions": [], "link": None, "document": None}}
        proc.stdin.write(json.dumps(request).encode() + b"\n")
        proc.stdin.flush()
        answer = json.loads(proc.stdout.readline())
        assert answer["id"] == 1 and answer["ok"] is False and answer["kind"] == "failed"
        began = time.time()
        proc.stdin.close()
        rest = proc.stdout.read()
        assert proc.wait(5) == 0 and time.time() - began < 5
        err = proc.stderr.read().decode("utf-8", "replace")
    finally:
        if proc.poll() is None:
            proc.kill()
    for line in rest.decode().splitlines():
        json.loads(line)
    assert "library noise" in err and "raw write to stdout" in err
    assert TOKEN not in err and TOKEN not in json.dumps(answer) and TOKEN not in rest.decode()


def test_the_module_never_sets_a_session_of_its_own():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "setsid" not in source and "start_new_session" not in source
