"""Tests of the messenger `listen` mode (MSG-5): a provider that stays connected and receives and sends over its own standard
input and output (providers/messenger/README.md), reached through runtime/messaging_provider.py (ListenSession) and driven by
the bridge's listen loop. The provider is a stand-in (runtime/tests/fixtures/messenger_listen_standin.py) that acts on the
lines it is given, never on time. Offline: no network, no model. Every process a test starts is gone at its end.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_listen.py
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time

import pytest

import standin_tree as st
from test_messaging import OPEN_POLICY, PLAN_HASH, SECRET_TEXT, decision, Fake, wait_for
from test_service import WAIT

bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")
messaging = st.load("messaging")

FIXTURE = st.RUNTIME / "tests" / "fixtures" / "messenger_listen_standin.py"
SENDER = "4242"
FAST = dict(ready_seconds=30, send_seconds=10, backoff=(0.02, 0.05), stdin_wait=5, term_wait=2, join_wait=3)


def alive(pid: int) -> bool:
    """Running. A zombie is dead: a container's init may not reap an orphan at once, and `kill -0` still finds it."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    found = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    if found.returncode == 1 and not found.stdout.strip():   # ps: no such process
        return False
    assert found.returncode == 0, "ps itself failed, so a missing process proves nothing"
    return not found.stdout.strip().startswith("Z")


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.is_file() else []


class Rig:
    """A workbench tree with the stand-in as the messenger provider of the platform `chirp`, an operations stand-in and a
    bridge over a real Messenger. `script` is the stand-in's script.json."""

    def __init__(self, tmp_path, monkeypatch, sender=SENDER, script=None, caps=None, options=None):
        self.base = tmp_path
        root = tmp_path / "bench"
        (root / "providers" / "messenger").mkdir(parents=True)
        shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
        shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
        self.folder = tmp_path / "standin"
        self.folder.mkdir()
        monkeypatch.setenv("STANDIN_DIR", str(self.folder))
        monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "state"))
        if script is not None:
            (self.folder / "script.json").write_text(json.dumps(script))
        if caps is not None:
            (self.folder / "caps.json").write_text(json.dumps(caps))
        (tmp_path / "ledger").mkdir(exist_ok=True)
        self.items, self.log, self.stop = {}, [], threading.Event()
        self.fake = Fake(tmp_path / "data")
        config = {"messaging": {"senders": {"chirp": [sender]}, "notices": "text", "page_url": None}, "channels": {"messaging": OPEN_POLICY}}
        self.fake.config_answer = lambda project: {"path": project, "sha256": "a" * 64, "accepted": True,
                                                   "data_dir": str(tmp_path / "data"), **config}
        self.fake.answers["pending"] = lambda project, pending_id=None, **k: (
            self.items[pending_id] if pending_id is not None else {"pending": [dict(i) for i in self.items.values() if i["status"] == "open"]})
        self.fake.answers["say"] = {"reply": "Noted.", "request_id": 1, "pending_id": None, "ran": True, "queued": False}
        project = tmp_path / "northwind-shop"
        project.mkdir()
        self.projects = [{"id": shell_kit.project_id(str(project)), "name": "northwind-shop", "path": str(project),
                          "data_dir": str(tmp_path / "data")}]
        self.messenger = providers.Messenger("chirp", root=str(root), session_options={**FAST, **(options or {})})
        self.bridge = bridge.Bridge(self.fake, self.projects, self.messenger, ledgers.Ledger(str(tmp_path / "ledger"), "chirp"),
                                    "chirp", self.log.append, clock=lambda: "2026-10-12T10:00:00+00:00")
        self.thread, self.error = None, []

    def run(self, notice_every=0.2):
        self.messenger.open_session(self.log.append)

        def loop():
            try:
                self.bridge.serve_loop(self.stop, notice_every, poll=1)
            except Exception as e:  # noqa: BLE001  (the test reads it)
                self.error.append(e)
        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()
        return self

    def starts(self):
        return lines(self.folder / "starts.jsonl")

    def requests(self):
        return lines(self.folder / "requests.jsonl")

    def sent(self):
        return lines(self.folder / "sent.jsonl")

    def texts(self):
        return [s["message"]["text"] for s in self.sent()]

    def calls(self, name):
        return [c for c in self.fake.calls if c[0] == name]

    def finish(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(WAIT)
        self.bridge.stopping.set()
        self.bridge.end_runs()
        self.messenger.close_session()

    def processes(self):
        pids = [s["pid"] for s in self.starts()]
        pids += [g["pid"] for g in lines(self.folder / "grandchildren.jsonl")]
        return pids


@pytest.fixture
def rig(tmp_path, monkeypatch):
    made = []

    def make(**kw):
        base = tmp_path / f"rig{len(made)}"
        base.mkdir()
        r = Rig(base, monkeypatch, **kw)
        made.append(r)
        return r
    yield make
    for r in made:   # only what this test started: the pids and groups the stand-in recorded
        try:
            r.finish()
        finally:
            for start in r.starts():
                try:
                    os.killpg(start["pgid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            for pid in r.processes():
                assert wait_for(lambda pid=pid: not alive(pid), 10), f"process {pid} is still alive"


# --- 1. capabilities --------------------------------------------------------------------------------------------------


def test_listen_is_optional_in_capabilities_false_when_absent_and_a_bool_when_present(rig):
    r = rig(caps={"listen": None})
    assert r.messenger.capabilities()["listen"] is False
    assert set(r.messenger.capabilities()) == set(providers.CAPABILITY_KEYS) | {"listen"}
    r.messenger.open_session()
    assert r.messenger.session is None and r.starts() == []   # nothing is started for a provider that does not listen
    r = rig(caps={"listen": "yes"})
    with pytest.raises(providers.MessengerError) as caught:
        r.messenger.capabilities()
    assert caught.value.kind == "failed" and "listen" in caught.value.reason
    r = rig()
    assert r.messenger.capabilities()["listen"] is True


# --- 2. a listen provider: started once, cards after ready, updates handled like received ones ------------------------


def test_the_bridge_starts_the_provider_once_sends_cards_after_ready_and_handles_a_tap_without_any_ack(tmp_path, monkeypatch, rig):
    tap = {"event": "update", "update": {"sender": SENDER, "chat": SENDER, "private": True, "text": None, "action": "@first",
                                         "action_ref": "ref-a-hostile-provider-sends", "reply_to": None}}
    r = rig(script={"default": {"after_send": {"1": [tap]}}})
    r.items[1] = decision("plan", 1)
    r.run()
    assert wait_for(lambda: "Approved #1." in r.texts())
    [card] = [s for s in r.sent() if s["message"]["actions"]]
    assert card["chat"] == SENDER and SECRET_TEXT in card["message"]["text"]
    [approve] = r.calls("approve")
    assert approve[2]["sha256"] == PLAN_HASH and approve[2]["pending_id"] == 1
    assert len(r.starts()) == 1 and r.starts()[0]["argv"] == ["listen", "--platform", "chirp"]
    assert [q["op"] for q in r.requests()] == ["send", "send"], "nothing but sends is ever written: no ack op"
    assert r.bridge.ledger.offset == 0, "the ledger's offset is not touched"
    r.finish()


def test_a_card_waits_until_the_provider_says_ready(tmp_path, monkeypatch, rig):
    r = rig(script={"1": {"ready": False}, "2": {}}, options={"ready_seconds": 0.4})
    r.items[1] = decision("plan", 1)
    r.run(notice_every=0.05)
    assert wait_for(lambda: len(r.starts()) == 2 and r.sent())
    assert r.requests()[0]["id"] == 1 and len(r.requests()) == 1, "the first request went to the second start, the ready one"
    assert any("did not become ready" in line for line in r.log)
    r.finish()


def test_a_reply_answers_a_question_and_free_text_goes_to_say(tmp_path, monkeypatch, rig):
    reply = {"event": "update", "update": {"sender": SENDER, "chat": SENDER, "private": True, "text": "blue", "action": None,
                                          "reply_to": "@sent"}}
    free = {"event": "update", "update": {"sender": SENDER, "chat": SENDER, "private": True, "text": "what is the plan?"}}
    r = rig(script={"default": {"after_send": {"1": [reply, free]}}})
    r.items[2] = decision("question", 2, title="Which colour?", actions=["answered"])
    r.run()
    assert wait_for(lambda: r.calls("answer") and r.calls("say"))
    assert r.calls("answer")[0][2] == {"pending_id": 2, "text": "blue"}
    assert r.calls("say")[0][2]["text"] == "what is the plan?"
    assert wait_for(lambda: "Noted." in r.texts() and "Answered #2." in r.texts())
    r.finish()


def test_non_ascii_text_goes_out_as_ascii_json_and_arrives_whole_and_a_request_over_the_limit_is_refused_unwritten(tmp_path, monkeypatch, rig):
    r = rig()
    r.messenger.open_session(r.log.append)
    assert wait_for(r.messenger.session.is_ready)
    text = "Caf\u00e9 \u2615 \u65e5\u672c\u8a9e, na\u00efve"
    assert r.messenger.send(SENDER, {"text": text, "actions": [], "link": None, "document": None}) == "m1"
    assert r.sent()[0]["message"]["text"] == text
    assert providers.line_of({"t": text}).isascii() and providers.line_of({"t": text}).endswith(b"\n")
    with pytest.raises(providers.MessengerError) as caught:
        r.messenger.send(SENDER, {"text": "x" * providers.MAX_LINE, "actions": [], "link": None, "document": None})
    assert caught.value.kind == "usage" and len(r.requests()) == 1
    r.finish()


def test_receive_does_not_apply_to_a_provider_that_listens_and_ack_writes_nothing(tmp_path, monkeypatch, rig):
    r = rig()
    r.messenger.open_session(r.log.append)
    assert wait_for(r.messenger.session.is_ready)
    with pytest.raises(providers.MessengerError) as caught:
        r.messenger.receive(0, 1)
    assert caught.value.kind == "usage"
    r.messenger.ack("ref")
    assert r.requests() == []
    r.finish()


def test_the_answers_of_the_provider_map_to_the_kinds_and_a_missing_message_id_is_a_failure(tmp_path, monkeypatch, rig):
    r = rig()
    r.messenger.open_session(r.log.append)
    assert wait_for(r.messenger.session.is_ready)
    plain = {"text": "x", "actions": [], "link": None, "document": None}
    for chat, kind in (("fail-usage", "usage"), ("fail-failed", "failed"), ("no-id", "failed")):
        with pytest.raises(providers.MessengerError) as caught:
            r.messenger.send(chat, plain)
        assert caught.value.kind == kind, chat
    r.finish()


def test_a_send_that_is_never_answered_fails_after_send_seconds(tmp_path, monkeypatch, rig):
    r = rig(options={"send_seconds": 0.3})
    r.messenger.open_session(r.log.append)
    assert wait_for(r.messenger.session.is_ready)
    with pytest.raises(providers.MessengerError) as caught:
        r.messenger.send("silent", {"text": "x", "actions": [], "link": None, "document": None})
    assert caught.value.kind == "failed" and "in time" in caught.value.reason
    assert r.messenger.send(SENDER, {"text": "y", "actions": [], "link": None, "document": None}) == "m1", "the session goes on"
    r.finish()


# --- 4. crash and restart; exit 3 --------------------------------------------------------------------------------------


def test_a_crash_restarts_the_provider_and_the_card_is_sent_again_and_the_first_copys_button_is_stale(tmp_path, monkeypatch, rig):
    """At least once: the first start delivered the card and died before it answered, so the bridge has no record of it."""
    r = rig(sender="crash-1")
    r.items[1] = decision("plan", 1)
    r.run()
    assert wait_for(lambda: len(r.sent()) == 2 and len(r.starts()) == 2)
    assert [q["id"] for q in r.requests()] == [1, 2], "request ids keep counting across the restart"
    first, second = (s["message"]["actions"][0]["id"] for s in r.sent())
    assert first == "1:approve" and second == "2:approve"
    assert any("exited (1)" in line for line in r.log) and any("could not be sent (failed)" in line for line in r.log)
    stale = {"sender": "crash-1", "chat": "crash-1", "private": True, "text": None, "action": first, "action_ref": None, "reply_to": None}
    r.bridge.handle(stale)
    assert bridge.STALE in r.texts() and not r.calls("approve")
    r.bridge.handle({**stale, "action": second})
    assert r.calls("approve") and "Approved #1." in r.texts()
    r.finish()


def test_exit_3_and_exit_2_stop_the_bridge_with_the_reason_the_provider_gave(tmp_path, monkeypatch, rig):
    for chat in ("exit-3", "exit-2"):
        r = rig(sender=chat)
        r.items[1] = decision("plan", 1)
        r.run()
        assert wait_for(lambda: r.error)
        assert isinstance(r.error[0], bridge.Fatal) and "pairing command" in str(r.error[0])
        assert len(r.starts()) == 1, "a provider that is not configured is not started again"
        r.finish()
        r.starts()


def test_without_an_error_event_fatal_uses_the_stderr_tail_then_the_exit_code(tmp_path, monkeypatch, rig):
    r = rig(script={"default": {"die": 3, "stderr": "the session is gone"}})
    r.run()
    assert wait_for(lambda: r.error) and "the session is gone" in str(r.error[0])
    r.finish()
    fake = "ghp_" + "a1B2c3D4" * 5   # not a real credential: the format only
    r = rig(script={"default": {"die": 3, "stderr": f"login failed with {fake} and then {fake[:10]}"}})
    r.run()
    assert wait_for(lambda: r.error) and fake not in str(r.error[0]) and "login failed" in str(r.error[0])
    r.finish()
    r = rig(script={"default": {"die": 3}})
    r.run()
    assert wait_for(lambda: r.error) and "exit" in str(r.error[0]) and "3" in str(r.error[0])
    r.finish()


def test_the_shell_exits_3_with_the_reason_and_nothing_private(tmp_path, monkeypatch, rig, capfd):
    r = rig(sender="exit-3")
    r.items[1] = decision("plan", 1, body="a private paragraph about Dana")
    folder = r.base / "project"
    folder.mkdir()
    code = messaging.serve([str(folder)], "chirp", notice_every=0.2, ops_module=r.fake, messenger=r.messenger, poll=1,
                           state_dir=str(r.base / "ledger"), out=open(r.base / "out", "w"))
    err = capfd.readouterr().err
    assert code == 3 and "pairing command" in err
    assert "a private paragraph" not in err and "Dana" not in err


def test_the_ceiling_of_starts_stops_the_bridge_with_a_sentence(tmp_path, monkeypatch, rig):
    r = rig(script={"default": {"die": 1}}, options={"max_starts": 3, "backoff": (0.01, 0.01)})
    r.run()
    assert wait_for(lambda: r.error) and isinstance(r.error[0], bridge.Fatal) and "3 times in 24 hours" in str(r.error[0])
    assert len(r.starts()) == 3
    r.finish()


def test_the_start_window_slides_and_the_backoff_doubles_up_to_its_ceiling_and_resets_after_a_long_ready(tmp_path, monkeypatch):
    now = [0.0]
    session = providers.ListenSession(None, "chirp", None, None, max_starts=3, window=100, backoff=(1.0, 4.0), reset_after=600,
                                      clock=lambda: now[0])
    assert [session.allow_start() for _ in range(4)] == [True, True, True, False]
    now[0] = 101.0
    assert session.allow_start() is True and len(session.starts) == 1
    waited = []
    session.closing = type("E", (), {"wait": lambda self, t: waited.append(t) or False, "is_set": lambda self: False})()
    assert [session.pause() for _ in range(5)] == [True] * 5 and waited == [1.0, 2.0, 4.0, 4.0, 4.0]
    run = providers.Run(None)
    run.ready_at = 0.0
    now[0] = 599.0
    session.settle_delay(run)
    assert session.delay == 4.0
    now[0] = 600.0
    session.settle_delay(run)
    assert session.delay == 1.0


# --- 5. hostile output --------------------------------------------------------------------------------------------------


def test_hostile_output_is_logged_by_class_and_dropped_and_the_bridge_keeps_running(tmp_path, monkeypatch, rig):
    secret = "Dana said the launch is on the 9th"
    good = {"event": "update", "update": {"sender": SENDER, "chat": SENDER, "private": True, "text": "still alive"}}
    emit = [{"raw": "this is not json " + secret}, {"bytes": "fffe00"}, {"raw": "[1, 2]"},
            {"id": 99, "ok": True, "message_id": "x"}, {"event": "weather", "text": secret},
            {"over": providers.MAX_LINE + 10}, {"over": 3 * providers.MAX_LINE},
            {"event": "update", "update": {"sender": SENDER, "chat": SENDER, "private": False, "text": secret}},
            {"event": "update", "update": {"sender": "", "chat": SENDER, "private": True}},
            {"event": "update", "update": {"sender": SENDER, "chat": SENDER, "private": True, "text": 5}},
            {"event": "update", "update": "nope"}, {"surprise": secret}, good]
    r = rig(script={"default": {"emit": emit, "noise": True, "stderr": secret}})
    r.run()
    assert wait_for(lambda: r.calls("say"))
    assert r.calls("say")[0][2]["text"] == "still alive" and len(r.calls("say")) == 1
    assert r.thread.is_alive() and not r.error
    joined = "\n".join(r.log)
    for expected in ("not JSON", "over the limit", "not valid", "not waiting", "not known", "neither an event nor an answer", "not an object"):
        assert expected in joined, expected
    assert secret not in joined and "Dana" not in joined and SENDER not in joined
    r.finish()


def test_a_full_update_queue_drops_the_newest_with_one_line(tmp_path, monkeypatch, rig):
    updates = [{"event": "update", "update": {"sender": SENDER, "chat": SENDER, "private": True, "text": f"n{i}"}} for i in range(6)]
    r = rig(script={"default": {"emit": updates}}, options={"queue_size": 3})
    r.messenger.open_session(r.log.append)   # no bridge loop: nothing takes the updates
    assert wait_for(lambda: sum("queue is full" in x for x in r.log) == 1)
    time.sleep(0.2)
    assert sum("queue is full" in x for x in r.log) == 1
    got = [r.messenger.session.next_update(1)["text"] for _ in range(3)]
    assert got == ["n0", "n1", "n2"] and r.messenger.session.next_update(0.1) is None
    r.finish()


# --- 6. stop: no orphan -------------------------------------------------------------------------------------------------


def test_closing_ends_stdin_and_the_provider_exits_with_it(tmp_path, monkeypatch, rig):
    r = rig()
    r.messenger.open_session(r.log.append)
    assert wait_for(r.messenger.session.is_ready)
    pid = r.starts()[0]["pid"]
    began = time.monotonic()
    r.messenger.close_session()
    assert not alive(pid) and time.monotonic() - began < 4
    with pytest.raises(providers.MessengerError):
        r.messenger.send(SENDER, {"text": "late", "actions": [], "link": None, "document": None})


def test_a_provider_that_ignores_stdin_and_sigterm_is_killed_by_group_with_what_it_started(tmp_path, monkeypatch, rig):
    r = rig(script={"default": {"ignore_eof": True, "ignore_term": True, "grandchild": True}},
            options={"stdin_wait": 0.3, "term_wait": 0.3})
    r.messenger.open_session(r.log.append)
    assert wait_for(r.messenger.session.is_ready) and wait_for(lambda: lines(r.folder / "grandchildren.jsonl"))
    pids = r.processes()
    r.messenger.close_session()
    assert wait_for(lambda: all(not alive(p) for p in pids), 10), pids


def test_a_provider_that_exits_on_its_own_leaves_nothing_of_its_group_behind(tmp_path, monkeypatch, rig):
    r = rig(script={"1": {"grandchild": True}, "2": {}}, sender="crash-1")
    r.items[1] = decision("plan", 1)
    r.run()
    assert wait_for(lambda: len(r.starts()) == 2)
    [child] = lines(r.folder / "grandchildren.jsonl")
    assert wait_for(lambda: not alive(child["pid"]))   # the exit of the leader kills its group
    r.finish()


DRIVER = '''
import sys, time
sys.path.insert(0, {runtime!r})
import messaging, operations

class Fake:
    OpsError = type("OpsError", (Exception,), {{"code": 1}})
    operations = operations
    def config(self, project):
        return {{"path": project, "sha256": "a" * 64, "accepted": True, "data_dir": {data!r},
                "messaging": {{"senders": {{"chirp": ["4242"]}}}}, "channels": {{"messaging": ["read"]}}}}
    def pending(self, project, pending_id=None):
        return {{"pending": []}}
    def stop_runs(self):
        open({marker!r}, "w").write("stopped")
        return {{}}

messaging.ops = Fake()
real = messaging.providers.Messenger
messaging.providers.Messenger = lambda platform: real(platform, root={root!r}, session_options={options!r})
sys.exit(messaging.main(["--project", {project!r}, "--platform", "chirp", "--notice-every", "5"] + {extra!r}))
'''


def driver(r, extra=()):
    path = r.base / "driver.py"
    path.write_text(textwrap.dedent(DRIVER.format(runtime=str(st.RUNTIME), data=str(r.base / "data"), marker=str(r.base / "stopped"),
                                                  root=r.messenger.root, options=FAST, project=str(r.base / "northwind-shop"),
                                                  extra=list(extra))))
    return subprocess.Popen([sys.executable, str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=dict(os.environ))


def test_sigterm_of_the_bridge_and_the_end_of_its_stdin_stop_the_provider_after_the_runs_end(tmp_path, monkeypatch, rig):
    for extra, how in (([], "sigterm"), (["--stop-on-stdin-eof"], "eof")):
        r = rig()
        proc = driver(r, extra)
        try:
            assert json.loads(proc.stdout.readline())["platform"] == "chirp"
            assert wait_for(lambda: r.starts())
            pid = r.starts()[-1]["pid"]
            assert wait_for(lambda: alive(pid))
            if how == "sigterm":
                proc.send_signal(signal.SIGTERM)
            else:
                proc.stdin.close()
            assert proc.wait(WAIT * 2) == 0
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        assert (r.base / "stopped").read_text() == "stopped" and not alive(pid)
        assert b"4242" not in proc.stderr.read()


def test_a_killed_bridge_cannot_leave_the_provider_behind_because_its_stdin_ends(tmp_path, monkeypatch, rig):
    """The provider has a session of its own, so the kill of the bridge never reaches it: the end of its stdin does."""
    r = rig()
    proc = driver(r)
    try:
        assert json.loads(proc.stdout.readline())["platform"] == "chirp"
        assert wait_for(lambda: r.starts())
        pid = r.starts()[-1]["pid"]
        proc.kill()
        proc.wait(10)
        assert wait_for(lambda: not alive(pid), 5), "the stand-in must exit within 5 s of the end of its stdin"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


# --- 7. nothing private in the bridge's log --------------------------------------------------------------------------------


def test_the_bridges_log_holds_no_token_no_text_and_no_sender_id(tmp_path, monkeypatch, rig):
    planted = "CREDENTIAL-abc123-not-real"
    r = rig(sender="crash-1", script={"default": {"stderr": f"connecting with {planted}"}})
    r.items[1] = decision("plan", 1, body=f"the private paragraph, {planted}")
    r.run()
    assert wait_for(lambda: len(r.starts()) == 2 and len(r.sent()) == 2)
    r.finish()
    joined = "\n".join(r.log)
    assert joined and planted not in joined and "private paragraph" not in joined and "crash-1" not in joined
