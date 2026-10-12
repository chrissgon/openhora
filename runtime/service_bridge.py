# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge as a child of the local service (runtime/service.py --messaging <platform>): one start brings up
the page and the bridge. This module holds the child's whole life and imports the standard library only; the service
imports it and the bridge's own command (runtime/messaging.py) is the only program it starts.

What it starts. The service's own interpreter running `runtime/messaging.py --project <each project the service was given>..., --platform
<platform> --stop-on-stdin-eof` (and `--notice-every <s>` when given), with:
  - its own session (start_new_session), so a signal to the service's group does not reach it and one signal to its
    group reaches the bridge and everything the bridge started;
  - standard input a pipe the service holds open and never writes to: when the service dies for any reason the pipe
    closes and the bridge, started with --stop-on-stdin-eof, stops as a SIGTERM stops it;
  - standard output to /dev/null (the bridge's one JSON line is not needed) and standard error inherited, so its log
    lines and errors appear on the service's;
  - the environment the service had at the very start of main, before any thread or run (a snapshot): a key a run in
    progress wrote into the service's own environment never reaches the child.
The interpreter is the service's own (sys.executable), so a service started with `uv run --with keyring==25.7.0` starts
a bridge that can read the secret store.

Its exit, at any time. One line on the log with the code and what it means; the service keeps serving the page; nothing
restarts the bridge (version 1). The service's answer of GET /projects has a top-level field `messaging`:
{"platform", "state": "running" | "stopped", "exit_code": <n> | null}, or null without the option.

Its stop. `begin_stop` (the top of the service's `finally`, for any exit): close the child's standard input and send
SIGTERM to the child's process group. `finish_stop` (after the service ended its own runs): wait up to `stop_wait`
seconds (150, above the bridge's own 120 s wait for its jobs, so a bridge still stopping cleanly is not killed); if the
child is still alive send SIGKILL to the group and log one line. Only by the group id the child's own session made
(never by a name or a pattern).

`bridge_argv` (the program part of the command: the interpreter and the script), `stop_wait` and `environment` are
parameters of the service's serve function, which only tests change: no variable, file or configuration key names them.

Runs on Python 3.9.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_STOP_WAIT = 150.0
MEANINGS = {
    0: "it stopped",
    2: "usage error or an unsafe state folder (see the error above)",
    3: "the bridge stopped: the messenger is not configured, or another program reads this bot (see the error above)",
    4: "another bridge serves this platform on this machine (see the error above)",
}


def command(platform: str, paths, notice_every=None, program=None) -> list:
    """The bridge's command line. `program` replaces the interpreter and the script (tests only)."""
    argv = list(program) if program else [sys.executable, os.path.join(HERE, "messaging.py")]
    for path in paths:
        argv += ["--project", str(path)]
    argv += ["--platform", platform, "--stop-on-stdin-eof"]
    if notice_every is not None:
        argv += ["--notice-every", str(int(notice_every))]
    return argv


def describe(code: int) -> str:
    """What an exit code of the bridge means, in a sentence."""
    if code < 0:
        try:
            return f"it was ended by {signal.Signals(-code).name}"
        except ValueError:
            return f"it was ended by signal {-code}"
    return MEANINGS.get(code, "it failed (see the error above)")


class Child:
    """The bridge process of one service."""

    def __init__(self, platform: str, paths, environment, log, notice_every=None, program=None, stop_wait: float = BRIDGE_STOP_WAIT):
        self.platform, self.log, self.stop_wait = platform, log, float(stop_wait)
        self.argv = command(platform, paths, notice_every, program)
        self.environment = dict(environment)
        self.process = None
        self.group = None
        self.exit_code = None
        self.lock = threading.Lock()
        self.stopping = False
        self.watcher = None

    def start(self) -> bool:
        """Start the child. False (after one log line) when it cannot be started; the service goes on."""
        try:
            self.process = subprocess.Popen(self.argv, env=self.environment, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                            start_new_session=True, close_fds=True)
        except OSError as e:
            self.log(f"the messaging bridge could not be started ({e.__class__.__name__}); the page is served without it")
            with self.lock:
                self.exit_code = -1 if self.exit_code is None else self.exit_code
            return False
        try:
            self.group = os.getpgid(self.process.pid)
        except OSError:
            self.group = self.process.pid  # the child is the leader of the session it made
        self.watcher = threading.Thread(target=self._watch, name="bridge-watch", daemon=True)
        self.watcher.start()
        return True

    def _watch(self) -> None:
        code = self.process.wait()
        with self.lock:
            self.exit_code = code
        self.log(f"the messaging bridge ({self.platform}) exited with code {code}: {describe(code)}"
                 + ("; the page is still served and the bridge is not restarted" if not self.stopping else ""))

    def state(self) -> dict:
        """{"platform", "state", "exit_code"} for the service's GET /projects."""
        with self.lock:
            code = self.exit_code
        running = self.process is not None and code is None and self.process.poll() is None
        return {"platform": self.platform, "state": "running" if running else "stopped", "exit_code": None if running else code}

    def begin_stop(self) -> None:
        """Close the child's standard input and send SIGTERM to its group. Does not wait."""
        self.stopping = True
        if self.process is None:
            return
        try:
            self.process.stdin.close()
        except OSError:
            pass
        if self.process.poll() is None:
            self._signal(signal.SIGTERM)

    def finish_stop(self) -> None:
        """Wait up to `stop_wait` seconds for the child; SIGKILL to its group when it is still alive, and one line."""
        if self.process is None:
            return
        deadline = time.monotonic() + self.stop_wait
        while self.process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if self.process.poll() is None:
            self.log(f"the messaging bridge did not stop in {self.stop_wait:g} s and was killed; the model jobs it was running "
                     "(unknown: its output is not read) leave their containers, which stay until they are removed by hand "
                     "or by a later stop-runs --all")
            self._signal(signal.SIGKILL)
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.log("the messaging bridge is still not gone after SIGKILL")
        if self.watcher is not None:
            self.watcher.join(5)

    def _signal(self, number: int) -> None:
        """A signal to the child's process group, by the group id its own session made."""
        try:
            os.killpg(self.group, number)
        except OSError:  # already gone
            pass
