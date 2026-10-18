"""The lock on the Microsoft records (providers/_msgraph.py `record_lock`), tested with real processes. Several provider processes share the one
account record, and Microsoft replaces the refresh token on every use. Writing it back is a re-read, a comparison and a write; the lock makes
that one step across processes (an exclusive flock on a per-user file), and the same lock is taken by an authorization's store step and by
forget. What these tests hold:

- two processes whose refreshes overlap write back once, whichever starts first, and both calls succeed;
- a forget that starts while a rotation is between its comparison and its write waits, and is not written over;
- a new authorization that starts in that window waits, and is not written over;
- a process that cannot get the lock in LOCK_TIMEOUT_SECONDS writes nothing and says so;
- the lock file is 0600 in a 0700 folder of the user's, no link is followed, and where it cannot be made (or the platform has no fcntl)
  the write goes on under the in-process lock alone, with one note on stderr.

The stand-ins are the token endpoint of fake_ms_account.py in this process and a secret store that lives in a file (lock_worker.py, the
process each test starts). No network but loopback, no real account, no real credential, and the real state folder is never touched.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_microsoft_lock.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
WORKER = HERE / "lock_worker.py"
sys.path.insert(0, str(HERE))
import fake_ms_account  # noqa: E402

_spec = importlib.util.spec_from_file_location("msgraph_for_the_lock_tests", PROVIDERS / "_msgraph.py")
msgraph = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = msgraph
_spec.loader.exec_module(msgraph)

USERNAME = "microsoft-account"
pytestmark = pytest.mark.skipif(msgraph.fcntl is None, reason="the cross-process lock needs fcntl (POSIX)")


@pytest.fixture
def fake():
    f = fake_ms_account.FakeMsAccount()
    yield f
    f.close()


class World:
    """A shared record in a file, a folder for the signals between processes, and a state folder of its own for the lock."""

    def __init__(self, tmp_path: Path, fake):
        self.fake, self.tmp = fake, tmp_path
        self.store = tmp_path / "store.json"
        self.events = tmp_path / "events"
        self.state = tmp_path / "state"
        self.events.mkdir()
        self.state.mkdir(mode=0o700)
        self.store.write_text(json.dumps({USERNAME: fake.account_record_json()}), encoding="utf-8")
        self.processes = []

    def start(self, name: str, mode: str, **more):
        config = {"mode": mode, "name": name, "store": str(self.store), "events": str(self.events), "token_url": self.fake.token_url, **more}
        env = {**os.environ, "XDG_STATE_HOME": str(self.state)}
        process = subprocess.Popen([sys.executable, str(WORKER), json.dumps(config)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.processes.append(process)
        return process

    def wait_for(self, name: str, seconds: float = 30):
        deadline = time.monotonic() + seconds
        while not (self.events / name).exists():
            assert time.monotonic() < deadline, f"timed out waiting for {name}"
            time.sleep(0.02)

    def go(self):
        (self.events / "go").write_text("1")

    @staticmethod
    def result(process, seconds: float = 60) -> dict:
        out, err = process.communicate(timeout=seconds)
        assert process.returncode == 0, err
        return json.loads(out)

    def record(self):
        text = json.loads(self.store.read_text(encoding="utf-8")).get(USERNAME)
        return None if text is None else json.loads(text)

    def writes(self) -> list:
        path = self.events / "writes.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def close(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.communicate()


@pytest.fixture
def world(tmp_path, fake):
    w = World(tmp_path, fake)
    yield w
    w.close()


# --- two rotations ------------------------------------------------------------------------------------------------------------


def test_two_processes_whose_refreshes_overlap_write_back_once_and_both_succeed(world):
    a = world.start("A", "rotate", delay=0.6)
    b = world.start("B", "rotate", delay=0.6)
    world.wait_for("A-refreshed")
    world.wait_for("B-refreshed")          # both have a new token before either writes
    world.go()
    results = {r["name"]: r for r in (world.result(a), world.result(b))}
    outcomes = sorted(r["outcome"] for r in results.values())
    assert outcomes == ["not stored: the record changed meanwhile", "stored"], outcomes
    assert len(world.writes()) == 1, "one write-back"
    winner = [r for r in results.values() if r["outcome"] == "stored"][0]
    assert world.record()["refresh_token"] == winner["rotated"] and world.record()["slot"] == "main"
    assert len(world.fake.token_forms) == 2 and world.fake.rotations == 2, "both refreshes were answered"
    loser = [r for r in results.values() if r["outcome"] != "stored"][0]
    again = msgraph.refresh_access_token(msgraph.account_profile(run_hint="x", env_prefix="ACCOUNT_MICROSOFT", user_agent="t", not_found="n", forbidden_hint="f"),
                                         world.fake.token_url, {**world.record(), "refresh_token": loser["rotated"]})
    assert again[0], "the loser's token still works"


def test_five_rotations_at_once_write_back_once(world):
    processes = [world.start(name, "rotate", delay=0.3) for name in "ABCDE"]
    for name in "ABCDE":
        world.wait_for(f"{name}-refreshed")
    world.go()
    outcomes = sorted(world.result(p)["outcome"] for p in processes)
    assert outcomes == ["not stored: the record changed meanwhile"] * 4 + ["stored"]
    assert len(world.writes()) == 1


# --- a forget or a new authorization in the window ---------------------------------------------------------------------------------


def test_a_forget_that_starts_between_the_comparison_and_the_write_waits_and_is_not_written_over(world):
    a = world.start("A", "rotate", delay=1.5)
    world.wait_for("A-refreshed")
    world.go()
    world.wait_for("A-writing")             # A has compared and is inside its write: it holds the lock
    started = time.monotonic()
    f = world.start("F", "forget")
    forgot = world.result(f)
    waited = time.monotonic() - started
    assert world.result(a)["outcome"] == "stored"
    assert forgot["code"] == 0
    assert world.record() is None, "the forget was not clobbered by the write that was already under way"
    assert waited >= 0.8, f"the forget did not wait for the rotation's write ({waited:.2f} s)"
    assert len(world.writes()) == 1


def test_a_new_authorization_that_starts_between_the_comparison_and_the_write_waits_and_is_not_written_over(world):
    newer = world.fake.account_record_json(refresh_token="fake-newer-authorization-token-not-real")
    a = world.start("A", "rotate", delay=1.5)
    world.wait_for("A-refreshed")
    world.go()
    world.wait_for("A-writing")
    b = world.start("N", "write", text=newer, delay=0)
    assert world.result(b)["code"] == 0
    assert world.result(a)["outcome"] == "stored"
    assert world.record()["refresh_token"] == "fake-newer-authorization-token-not-real", "the newer authorization is what is stored"
    assert world.writes()[-1].startswith("N "), "its write came after the rotation's"


def test_a_rotation_that_starts_after_a_new_authorization_does_not_overwrite_it(world):
    """The other order: the authorization is stored first; the rotation (whose refresh used the old token) re-reads and leaves it alone."""
    newer = world.fake.account_record_json(refresh_token="fake-newer-authorization-token-not-real")
    a = world.start("A", "rotate", delay=0.0)
    world.wait_for("A-refreshed")
    assert world.result(world.start("N", "write", text=newer, delay=0))["code"] == 0
    world.go()
    assert world.result(a)["outcome"] == "not stored: the record changed meanwhile"
    assert world.record()["refresh_token"] == "fake-newer-authorization-token-not-real"


# --- the lock is not held for ever -------------------------------------------------------------------------------------------------


def test_a_process_that_cannot_get_the_lock_in_time_writes_nothing_and_says_so(world):
    a = world.start("A", "rotate", delay=4)
    world.wait_for("A-refreshed")
    world.go()
    world.wait_for("A-writing")
    b = world.start("B", "write", text=world.fake.account_record_json(refresh_token="fake-late-token-not-real"), delay=0, lock_timeout=0.6)
    late = world.result(b)
    assert late["code"] == 1 and "another process has held the lock" in late["error"] and "nothing was written" in late["error"]
    world.result(a)
    assert world.record()["refresh_token"] != "fake-late-token-not-real"
    # a rotation that cannot get the lock carries on with its old token and says so
    (world.events / "go").unlink()
    c = world.start("C", "rotate", delay=4)
    world.wait_for("C-refreshed")
    world.go()
    world.wait_for("C-writing")
    d = world.start("D", "rotate", delay=0, lock_timeout=0.6)
    dropped = world.result(d)
    assert dropped["outcome"] == "not stored: the lock on the records is held by another process"
    assert world.result(c)["outcome"] == "stored" and len(world.writes()) == 2


# --- the lock file ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(msgraph, "_LOCK_NOTED", set())
    return tmp_path / "xdg"


def test_the_lock_file_is_0600_in_a_0700_folder_of_the_users_state_folder(state):
    assert msgraph.lock_file_path() == state / "openhora" / "msgraph-records.lock"
    with msgraph.record_lock():
        assert stat.S_IMODE(os.stat(state / "openhora").st_mode) == 0o700
        assert stat.S_IMODE(os.stat(state / "openhora" / "msgraph-records.lock").st_mode) == 0o600
    with msgraph.record_lock():
        pass   # taken again: released the first time


def test_a_folder_that_is_too_open_is_tightened_and_a_file_too_open_too(state):
    folder = state / "openhora"
    folder.mkdir(parents=True, mode=0o755)
    os.chmod(folder, 0o755)
    (folder / "msgraph-records.lock").write_text("")
    os.chmod(folder / "msgraph-records.lock", 0o644)
    with msgraph.record_lock():
        pass
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700 and stat.S_IMODE(os.stat(folder / "msgraph-records.lock").st_mode) == 0o600


def test_a_link_in_place_of_the_folder_or_the_file_is_not_followed_and_the_write_goes_on_with_one_note(state, capsys):
    state.mkdir()
    target = state.parent / "elsewhere"
    target.mkdir()
    (state / "openhora").symlink_to(target)
    for _ in range(3):
        with msgraph.record_lock():
            pass
    err = capsys.readouterr().err
    assert err.count("no file lock for the Microsoft records") == 1 and "a write goes on under this process's lock alone" in err
    assert list(target.iterdir()) == [], "nothing was made behind the link"
    (state / "openhora").unlink()
    (state / "openhora").mkdir(mode=0o700)
    (target / "other").write_text("")
    (state / "openhora" / "msgraph-records.lock").symlink_to(target / "other")
    msgraph._LOCK_NOTED.clear()
    with msgraph.record_lock():
        pass
    assert "no file lock for the Microsoft records" in capsys.readouterr().err
    assert (target / "other").read_text() == ""


def test_a_platform_without_fcntl_keeps_the_in_process_lock_and_says_so_once(state, monkeypatch, capsys):
    monkeypatch.setattr(msgraph, "fcntl", None)
    for _ in range(3):
        with msgraph.record_lock():
            pass
    err = capsys.readouterr().err
    assert err.count("this platform has no fcntl") == 1 and "not from two processes" in err
    assert not (state / "openhora").exists(), "no lock file is made"


def test_a_lock_held_by_another_process_for_too_long_is_a_provider_error_and_the_body_does_not_run(state, monkeypatch):
    holder = subprocess.Popen([sys.executable, "-c", (
        "import fcntl, os, sys, time\n"
        "folder = os.path.join(sys.argv[1], 'openhora'); os.makedirs(folder, mode=0o700, exist_ok=True)\n"
        "fd = os.open(os.path.join(folder, 'msgraph-records.lock'), os.O_RDWR | os.O_CREAT, 0o600)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX); print('held', flush=True); time.sleep(20)\n"), str(state)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        monkeypatch.setattr(msgraph, "LOCK_TIMEOUT_SECONDS", 0.4)
        ran = []
        with pytest.raises(msgraph.ProviderError) as refused:
            with msgraph.record_lock():
                ran.append(1)
        assert refused.value.code == 1 and "nothing was written" in str(refused.value) and ran == []
        assert msgraph.ROTATION_LOCK.acquire(blocking=False), "the in-process lock was released too"
        msgraph.ROTATION_LOCK.release()
    finally:
        holder.kill()
        holder.communicate()


def test_the_lock_is_released_when_the_body_raises(state):
    with pytest.raises(RuntimeError):
        with msgraph.record_lock():
            raise RuntimeError("the write failed")
    got = []
    thread = threading.Thread(target=lambda: [got.append(1) for _ in [msgraph.record_lock().__enter__()]], daemon=True)
    thread.start()
    thread.join(5)
    assert got == [1], "another taker gets it at once"


def test_the_write_steps_of_an_authorization_and_of_forget_take_the_lock(state, monkeypatch):
    taken = []
    real = msgraph.record_lock

    def spy():
        taken.append(1)
        return real()

    monkeypatch.setattr(msgraph, "record_lock", spy)

    class Store:
        def __init__(self):
            self.values = {}

        def set_password(self, service, username, value):
            self.values[(service, username)] = value

        def delete_password(self, service, username):
            del self.values[(service, username)]

    store = Store()
    profile = msgraph.account_profile(run_hint="x", env_prefix="ACCOUNT_MICROSOFT", user_agent="t", not_found="n", forbidden_hint="f")
    msgraph.write_record(profile, store, "text")
    msgraph.delete_record(profile, store)
    assert len(taken) == 2 and store.values == {}
