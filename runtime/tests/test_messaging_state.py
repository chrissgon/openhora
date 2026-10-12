"""The messaging bridge's state (MSG-3a): the per-user state folder and its checks, the single-instance lock, the ledger in
the state folder and its one-time migration, the skip and re-check of a project that is not ready, and the stop on the end
of standard input. Offline: a stand-in operations object and a stand-in messenger; nothing reaches the real state folder
(every test points OPENHORA_STATE_DIR at a temporary one).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_state.py
"""
from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import textwrap
import threading
import time

import pytest

import standin_tree as st
from test_service import Standin, WAIT

messaging = st.load("messaging")
ledgers = st.load("messaging_ledger")
bridge = st.load("messaging_bridge")
shell_kit = st.load("shell_kit")
PROJECT_FILE = "messaging-telegram.json"


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    folder = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(folder))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return folder


def run(*argv, env=None):
    return subprocess.run([sys.executable, str(st.RUNTIME / "messaging.py"), *argv], input=b"", capture_output=True,
                          timeout=60, env=env)


# --- the state folder -------------------------------------------------------------------------------------------------


def test_the_state_folder_is_the_flag_then_the_variable_then_xdg_then_the_home(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENHORA_STATE_DIR")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert ledgers.state_dir() == str(tmp_path / "home" / ".local" / "state" / "openhora")
    monkeypatch.setenv("XDG_STATE_HOME", "relative/state")
    assert ledgers.state_dir() == str(tmp_path / "home" / ".local" / "state" / "openhora"), "a relative XDG value is ignored"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert ledgers.state_dir() == str(tmp_path / "xdg" / "openhora")
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "from-variable"))
    assert ledgers.state_dir() == str(tmp_path / "from-variable")
    assert ledgers.state_dir(str(tmp_path / "from-flag")) == str(tmp_path / "from-flag"), "the flag wins"


def test_the_state_folder_is_made_0700_and_a_good_one_is_accepted(state):
    path = ledgers.prepare_state_dir()
    assert path == str(state) and stat.S_IMODE(os.stat(path).st_mode) == 0o700
    assert ledgers.prepare_state_dir() == path


def test_a_group_writable_folder_and_a_linked_folder_are_refused(tmp_path, state):
    loose = tmp_path / "loose"
    loose.mkdir()
    os.chmod(loose, 0o770)
    with pytest.raises(ledgers.StateError) as e:
        ledgers.prepare_state_dir(str(loose))
    assert str(loose) in str(e.value)
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(ledgers.StateError) as e:
        ledgers.prepare_state_dir(str(link))
    assert str(link) in str(e.value)
    # the shell: exit 2 with the path, before it looks at any project
    for bad in (loose, link):
        done = run("--project", str(tmp_path / "nothing"), "--platform", "telegram", "--state-dir", str(bad))
        assert done.returncode == 2 and str(bad).encode() in done.stderr and done.stdout == b""


# --- the lock ----------------------------------------------------------------------------------------------------------


def test_a_second_bridge_for_the_same_platform_exits_4_and_a_new_one_starts_when_the_first_ends(tmp_path, state):
    folder = ledgers.prepare_state_dir()
    first = tmp_path / "first.py"
    first.write_text(textwrap.dedent(f'''
        import sys, time
        sys.path.insert(0, {str(st.RUNTIME)!r})
        import messaging_ledger as ledgers
        ledgers.take_lock({folder!r}, "telegram")
        print("locked", flush=True)
        time.sleep(60)
    '''), encoding="utf-8")
    holder = subprocess.Popen([sys.executable, str(first)], stdout=subprocess.PIPE)
    try:
        assert holder.stdout.readline().strip() == b"locked"
        refused = run("--project", str(tmp_path / "nothing"), "--platform", "telegram")
        lock = os.path.join(folder, "messaging-telegram.lock")
        assert refused.returncode == 4 and refused.stdout == b""
        assert (f"another messaging bridge already serves telegram on this machine (its lock: {lock}); stop it first").encode() in refused.stderr
        other = run("--project", str(tmp_path / "nothing"), "--platform", "other")
        assert other.returncode == 3, "another platform has its own lock"
    finally:
        holder.kill()
        holder.wait()
    again = run("--project", str(tmp_path / "nothing"), "--platform", "telegram")
    assert again.returncode == 3, "a crash left no stale lock: this one got past it to the missing project"
    assert stat.S_IMODE(os.stat(os.path.join(folder, "messaging-telegram.lock")).st_mode) == 0o600


def test_the_lock_file_is_not_followed_when_it_is_a_link(tmp_path, state):
    folder = ledgers.prepare_state_dir()
    (tmp_path / "elsewhere").write_text("keep")
    os.symlink(tmp_path / "elsewhere", os.path.join(folder, "messaging-telegram.lock"))
    with pytest.raises(ledgers.StateError):
        ledgers.take_lock(folder, "telegram")
    assert (tmp_path / "elsewhere").read_text() == "keep"


def test_a_platform_that_is_not_a_lowercase_word_is_a_usage_error(tmp_path):
    for platform in ("../x", "Telegram", "a b", "-x", ""):
        done = run("--project", str(tmp_path), "--platform", platform)
        assert done.returncode == 2 and b"error:" in done.stderr, platform
    assert messaging.parse(["--project", "a", "--platform", "my-app2"])["platform"] == "my-app2"


# --- the ledger: the state folder, the keys, the migration ----------------------------------------------------------------


def card(project, chat, number, actions, platform=None):
    return {"project": project, "pending_id": number, "kind": "plan", "content_sha256": "c" * 64, "chat": chat,
            "message_id": f"m{number}", "actions": actions, "sent_at": "2026-10-12T10:00:00+00:00"}


def test_the_ledger_lives_in_the_state_folder_keyed_by_platform_project_and_chat(tmp_path, state):
    folder = ledgers.prepare_state_dir()
    one = ledgers.Ledger(folder, "telegram")
    one.add(card("aaaaaaaaaaaa", "4242", 1, {"1:approve": "approve"}))
    assert one.path == os.path.join(folder, PROJECT_FILE) and stat.S_IMODE(os.stat(one.path).st_mode) == 0o600
    assert json.loads(open(one.path).read())["cards"][0]["platform"] == "telegram"
    assert one.sent("aaaaaaaaaaaa", 1, "c" * 64, "4242")
    # the same decision number in another project, or another chat, is another card
    assert not one.sent("bbbbbbbbbbbb", 1, "c" * 64, "4242") and not one.sent("aaaaaaaaaaaa", 1, "c" * 64, "7")
    # a card of another platform in the same file is never found by this one
    one.data["cards"].append(dict(card("aaaaaaaaaaaa", "4242", 9, {"9:approve": "approve"}), platform="other"))
    assert one.by_action("4242", "9:approve") is None and one.last_card("aaaaaaaaaaaa", 9, "4242") is None
    # two sets of projects, run one after the other, keep separate cards
    second = ledgers.Ledger(folder, "telegram")
    assert second.sent("aaaaaaaaaaaa", 1, "c" * 64, "4242") and not second.sent("cccccccccccc", 1, "c" * 64, "4242")


def test_the_one_time_migration_copies_the_served_projects_with_seq_and_offset_and_leaves_the_old_file(tmp_path, state):
    folder = ledgers.prepare_state_dir()
    old_folder = tmp_path / "data"
    old_folder.mkdir()
    old = old_folder / PROJECT_FILE
    old.write_text(json.dumps({"version": 1, "offset": 77, "seq": 5, "cards": [
        card("aaaaaaaaaaaa", "4242", 1, {"5:approve": "approve", "5:reject": "reject"}),
        card("bbbbbbbbbbbb", "4242", 2, {"4:approve": "approve"})]}))
    before = old.read_text()
    lines = []
    one = ledgers.Ledger(folder, "telegram", legacy_folder=str(old_folder), served=["aaaaaaaaaaaa"], log=lines.append)
    assert [c["project"] for c in one.data["cards"]] == ["aaaaaaaaaaaa"], "only the projects this bridge serves"
    assert one.offset == 77 and one.data["seq"] == 5
    assert old.read_text() == before, "the old file stays"
    assert len(lines) == 1 and str(old) in lines[0] and "can be deleted" in lines[0]
    assert os.path.exists(one.path)
    # a tap on an action id of the migrated card, after a new card was sent, acts on the old card's decision
    assert one.next_seq() == 6
    one.add(card("aaaaaaaaaaaa", "4242", 3, {"6:approve": "approve"}))
    found = one.by_action("4242", "5:approve")
    assert found["pending_id"] == 1 and found["project"] == "aaaaaaaaaaaa"
    # once only: with the new file there, a later start does not read the old file again
    old.write_text(json.dumps({"version": 1, "offset": 1, "seq": 1, "cards": []}))
    again = ledgers.Ledger(folder, "telegram", legacy_folder=str(old_folder), served=["aaaaaaaaaaaa"], log=lines.append)
    assert again.offset == 77 and len(lines) == 1


def test_an_unreadable_old_ledger_is_not_migrated_and_says_so(tmp_path, state):
    folder = ledgers.prepare_state_dir()
    old_folder = tmp_path / "data"
    old_folder.mkdir()
    (old_folder / PROJECT_FILE).write_text("{not json")
    lines = []
    one = ledgers.Ledger(folder, "telegram", legacy_folder=str(old_folder), served=["a"], log=lines.append)
    assert one.data["cards"] == [] and one.offset == 0 and len(lines) == 1 and "not migrated" in lines[0]


# --- skip and re-check -------------------------------------------------------------------------------------------------


class Messenger:
    """A messenger that has nothing to say; receive waits a little, as a poll does."""

    def capabilities(self):
        return {"max_text": 4096, "buttons": True, "max_buttons": 6, "max_button_label": 40, "lists": False, "max_list_rows": 0}

    def receive(self, offset, timeout):
        time.sleep(0.05)
        return {"updates": [], "next_offset": offset}

    def send(self, chat, message):
        return "1"


class World:
    pass


@pytest.fixture
def world(tmp_path):
    w = World()
    w.tmp = tmp_path
    w.ready = tmp_path / "ready"
    w.waiting = tmp_path / "waiting"
    for folder in (w.ready, w.waiting, tmp_path / "data"):
        folder.mkdir()
    w.fake = Standin(tmp_path / "data")
    w.mode = {str(w.ready): "ready", str(w.waiting): "no-sender"}

    def config(project):
        mode = w.mode[project]
        base = {"path": project, "sha256": "a" * 64, "accepted": mode != "unaccepted", "data_dir": str(tmp_path / "data")}
        if mode in ("ready", "now-ready"):
            base["messaging"] = {"senders": {"telegram": ["4242"]}}
        return base
    w.fake.config = lambda project: config(project)
    w.fake.answers["pending"] = {"pending": []}
    w.log = []
    return w


def serving(world, folders, **more):
    stop = threading.Event()
    result = {}

    def target():
        result["code"] = messaging.serve([str(f) for f in folders], "telegram", notice_every=0.1, ops_module=world.fake,
                                         messenger=Messenger(), log=world.log.append, stop=stop, poll=1,
                                         out=open(os.devnull, "w"), **more)
    thread = threading.Thread(target=target)
    thread.start()
    return stop, thread, result


def until(condition, seconds=WAIT):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return False


def pending_calls(world, folder):
    return [c for c in world.fake.calls if c[0] == "pending" and c[1] == str(folder)]


def test_a_project_not_accepted_and_one_without_a_sender_are_skipped_once_each_and_served_when_ready(world, state):
    world.mode[str(world.waiting)] = "unaccepted"
    stop, thread, result = serving(world, [world.ready, world.waiting], state_dir=ledgers.prepare_state_dir())
    try:
        assert until(lambda: pending_calls(world, world.ready)), "the ready project is served"
        assert until(lambda: any("skipping waiting" in line for line in world.log))
        time.sleep(0.5)  # several notice periods
        skips = [line for line in world.log if line.startswith("skipping")]
        assert len(skips) == 1 and "not accepted" in skips[0], "one line, not one per notice period"
        assert pending_calls(world, world.waiting) == [] and thread.is_alive()
        world.mode[str(world.waiting)] = "no-sender"
        assert until(lambda: len([line for line in world.log if line.startswith("skipping")]) == 2)
        assert "lists no sender" in world.log[-1] or any("lists no sender" in line for line in world.log)
        world.mode[str(world.waiting)] = "now-ready"  # the person accepted a configuration that lists a sender
        assert until(lambda: pending_calls(world, world.waiting)), "the next notice period serves it"
        assert any("waiting is ready" in line for line in world.log)
    finally:
        stop.set()
        thread.join(WAIT)
    assert result["code"] == 0


def test_with_every_project_skipped_the_bridge_keeps_running(world, state):
    stop, thread, result = serving(world, [world.waiting], state_dir=ledgers.prepare_state_dir())
    try:
        assert until(lambda: any(line.startswith("skipping waiting") for line in world.log))
        time.sleep(0.4)
        assert thread.is_alive() and "code" not in result
    finally:
        stop.set()
        thread.join(WAIT)
    assert result["code"] == 0


def test_a_folder_that_is_not_a_configured_project_still_ends_the_start_with_3(world, state, capsys):
    def refuse(project):
        raise world.fake.OpsError("not a configured project", 3)
    world.fake.config = refuse
    code = messaging.serve([str(world.ready)], "telegram", ops_module=world.fake, messenger=Messenger(),
                           state_dir=ledgers.prepare_state_dir(), out=open(os.devnull, "w"))
    assert code == 3 and "not a configured project" in capsys.readouterr().err


# --- --stop-on-stdin-eof ----------------------------------------------------------------------------------------------


def driver(tmp_path, args, marker):
    """A process that runs messaging.main with a stand-in operations object; it prints the start line, and writes `marker`
    when ops.stop_runs is called."""
    folder = tmp_path / "project"
    folder.mkdir(exist_ok=True)
    script = tmp_path / "driver.py"
    script.write_text(textwrap.dedent(f'''
        import sys, time
        sys.path.insert(0, {str(st.RUNTIME)!r})
        import messaging, operations

        class Fake:
            OpsError = type("OpsError", (Exception,), {{"code": 1}})
            operations = operations
            def config(self, project):
                return {{"path": project, "sha256": "a" * 64, "accepted": True, "data_dir": {str(tmp_path / "data")!r},
                        "messaging": {{"senders": {{"telegram": ["4242"]}}}}}}
            def pending(self, project, pending_id=None):
                return {{"pending": []}}
            def stop_runs(self):
                open({str(marker)!r}, "w").write("stopped")
                return {{}}

        class Messenger:
            def capabilities(self):
                return {{"max_text": 4096, "buttons": True, "max_buttons": 6}}
            def receive(self, offset, timeout):
                time.sleep(0.2)
                return {{"updates": [], "next_offset": offset}}

        messaging.ops = Fake()
        messaging.providers.Messenger = lambda platform: Messenger()
        sys.exit(messaging.main(["--project", {str(folder)!r}, "--platform", "telegram", "--notice-every", "5"] + {args!r}))
    '''), encoding="utf-8")
    return subprocess.Popen([sys.executable, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_with_the_flag_the_end_of_standard_input_stops_the_bridge_as_sigterm_does(tmp_path):
    marker = tmp_path / "stopped"
    proc = driver(tmp_path, ["--stop-on-stdin-eof"], marker)
    try:
        assert json.loads(proc.stdout.readline())["platform"] == "telegram"
        time.sleep(0.5)
        assert proc.poll() is None, "an open pipe changes nothing"
        proc.stdin.close()
        assert proc.wait(timeout=30) == 0 and marker.read_text() == "stopped"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_without_the_flag_the_end_of_standard_input_changes_nothing(tmp_path):
    marker = tmp_path / "stopped"
    proc = driver(tmp_path, [], marker)
    try:
        assert json.loads(proc.stdout.readline())["platform"] == "telegram"
        proc.stdin.close()
        time.sleep(1.5)
        assert proc.poll() is None and not marker.exists()
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == 0 and marker.read_text() == "stopped"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_the_watcher_calls_its_function_when_the_stream_ends_and_not_before():
    import io
    import os as _os
    read, write = _os.pipe()
    ended = threading.Event()
    thread = messaging.watch_stdin(io.open(read, "rb"), ended.set)
    _os.write(write, b"ignored text")
    assert not ended.wait(0.3)
    _os.close(write)
    assert ended.wait(WAIT)
    thread.join(WAIT)


def test_a_messenger_conflict_is_a_fatal_error_that_prints_the_sentence_and_exits_3(world, state, capsys):
    providers = st.load("messaging_provider")
    sentence = "Telegram answered 409: another program is reading this bot's updates (a second bridge, or another tool with the same token)"

    class Conflicted(Messenger):
        def receive(self, offset, timeout):
            raise providers.MessengerError("not-configured", sentence)
    code = messaging.serve([str(world.ready)], "telegram", notice_every=0.1, ops_module=world.fake, messenger=Conflicted(),
                           state_dir=ledgers.prepare_state_dir(), out=open(os.devnull, "w"), log=world.log.append)
    err = capsys.readouterr().err
    assert code == 3 and "another program is reading this bot's updates" in err
