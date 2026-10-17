# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's access to a messenger provider (class messenger:<platform>, providers/messenger/README.md):
the four verbs as methods, started through providers/resolve.py, the one function that resolves a class and runs a
provider's verb. The bridge names no implementation: the class, and the platform as a parameter, choose it.

The neutral message is handed to the provider in a file of mode 0600 that is removed afterwards. The provider reads its
own credential; nothing here sees or passes one.

A provider that declares `listen: true` is not called once per verb: the Messenger starts its `listen` verb once and keeps
it (`ListenSession`, the protocol in providers/messenger/README.md). Updates arrive from its output, a send is a request
on its input answered on its output, and a provider that exits is started again with a backoff, or stops the bridge when
it says it is not configured.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import os
import queue
import signal
import sys
import tempfile
import threading
import time
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CAPABILITY_KEYS = {"max_text": int, "buttons": bool, "max_buttons": int, "max_button_label": int, "lists": bool,
                   "max_list_rows": int, "url_buttons": bool, "reply_context": bool, "documents": bool}
OPTIONAL_KEYS = {"listen": bool, "actions_need_reply": bool}   # a capability a provider may leave out; absent is stored as False
# actions_need_reply: the bridge acts on a typed approve, reject or release only when the update is a reply to the card of that decision
# (e-mail: an address proves little, and a reply that names the card's random Message-ID also proves the card reached the person)
SEND_SECONDS = 60
MAX_LINE = 1 << 20                 # the longest line of the listen protocol, either way, without its newline
READY_SECONDS = 180                # the first start of a provider with pinned dependencies installs them
BACKOFF = (1.0, 300.0)             # the first wait before a restart and its ceiling; each wait doubles the last
RESET_AFTER = 600.0                # a provider ready this long has earned the first wait again
MAX_STARTS = 200                   # starts per rolling window: a platform may reset a credential that connects too often
START_WINDOW = 86400.0
STDIN_WAIT, TERM_WAIT = 10.0, 5.0  # the stop: after stdin ends, then after SIGTERM, before SIGKILL
UPDATE_QUEUE = 1000
STDERR_TAIL = 300
ERROR_KINDS = ("usage", "not-configured", "failed", "paused")
ANSWER_KINDS = ("usage", "not-configured", "failed", "deferred")   # "paused" is an error-event kind only: a send answer cannot be paused today; the kinds of a send that did not go out; "deferred" is not an error: the platform cannot take it yet and the bridge keeps the card
PAUSED_WAIT = 300.0                # a provider that exits 3 after an error event of kind "paused" (its session is gone) is asked again after this
PAUSED_REPEAT = 86400.0            # the line that says it is paused is written again this often while it stays paused


class Sent(str):
    """The id of the message a send answered, a str as it always was, with `document_failed`: true when the text went out and the document that
    was to follow it did not (the provider's answer says so). A card whose approval needs its whole text delivered reads it
    (messaging_bridge.send_card): the id alone never said the document arrived."""

    def __new__(cls, value, document_failed: bool = False):
        found = super().__new__(cls, value)
        found.document_failed = bool(document_failed)
        return found


class MessengerError(Exception):
    """A provider verb failed. `kind` is the resolver's word (usage, not-configured, failed, timeout)."""

    def __init__(self, kind: str, reason: str):
        super().__init__(f"{kind}: {reason}")
        self.kind, self.reason = kind, reason


def resolver(root: str = ROOT):
    path = os.path.join(root, "providers", "resolve.py")
    name = "workbench_messaging_resolve"
    module = sys.modules.get(name)
    if module is None or getattr(module, "__file__", None) != path:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


class Messenger:
    def __init__(self, platform: str, root: str = ROOT, implementation=None, session_options=None):
        self.platform, self.root, self.implementation = platform, root, implementation
        self.module = resolver(root)
        self._caps = None
        self.session = None                  # a ListenSession, once open_session started one
        self.session_options = session_options or {}

    def _call(self, verb: str, args: list, timeout: int = SEND_SECONDS) -> dict:
        try:
            return self.module.call(f"messenger:{self.platform}", verb, ["--platform", self.platform, *args], root=self.root,
                                    implementation=self.implementation, timeout=timeout)
        except self.module.ProviderCallError as e:
            raise MessengerError(e.kind, e.stderr_tail or e.reason) from None

    def capabilities(self) -> dict:
        """The provider's capabilities, read once and checked: every key present with the right type."""
        if self._caps is None:
            found = self._call("capabilities", [])
            for key, kind in CAPABILITY_KEYS.items():
                if type(found.get(key)) is not kind:
                    raise MessengerError("failed", f"capabilities lacks {key}")
            for key, kind in OPTIONAL_KEYS.items():
                if key in found and type(found[key]) is not kind:
                    raise MessengerError("failed", f"capabilities has a {key} that is not a {kind.__name__}")
            self._caps = {key: found[key] for key in CAPABILITY_KEYS}
            self._caps.update({key: found.get(key, False) for key in OPTIONAL_KEYS})
        return self._caps

    def open_session(self, log=None) -> None:
        """For a provider that listens: start its long-lived verb. A provider that does not listen: nothing."""
        if self.session is None and self.capabilities()["listen"]:
            self.session = ListenSession(self.module, self.platform, self.root, self.implementation, log=log, **self.session_options)
            self.session.start()

    def close_session(self) -> None:
        if self.session is not None:
            self.session.close()

    def receive(self, offset: int, timeout: int) -> dict:
        if self.session is not None:
            raise MessengerError("usage", "a provider that listens delivers its updates on its own; receive does not apply")
        found = self._call("receive", ["--offset", str(int(offset)), "--timeout", str(int(timeout))], timeout=int(timeout) + 60)
        if not isinstance(found.get("updates"), list) or type(found.get("next_offset")) is not int:
            raise MessengerError("failed", "receive did not return updates and next_offset")
        return found

    def send(self, chat: str, message: dict) -> str:
        if self.session is not None:
            return self.session.send(chat, message)
        fd, path = tempfile.mkstemp(prefix="messenger-message-", suffix=".json")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(message, f)
            found = self._call("send", ["--chat", str(chat), "--message-file", path])
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if not isinstance(found.get("message_id"), str):
            raise MessengerError("failed", "send did not return a message_id")
        return Sent(found["message_id"], found.get("document_failed") is True)

    def ack(self, action_ref: str) -> None:
        if self.session is not None:
            return   # a provider that listens acknowledges its own taps at once and has no ack request
        self._call("ack", ["--action-ref", str(action_ref)])



_REDACT = []


def redact_module():
    """scripts/redact.py of this checkout (the credential formats the scan and the skills share), loaded by path."""
    if not _REDACT:
        spec = importlib.util.spec_from_file_location("workbench_messaging_redact", os.path.join(ROOT, "scripts", "redact.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _REDACT.append(module)
    return _REDACT[0]


def line_of(value: dict) -> bytes:
    """One protocol line: ASCII JSON and a newline (what the bridge writes; the provider writes the same way)."""
    return json.dumps(value, ensure_ascii=True).encode("ascii") + b"\n"


def valid_update(raw):
    """The update the bridge handles, or None when `raw` is not one: a private chat, a non-empty sender and chat, and text,
    action and reply_to each a string or null. `action_ref` is always null here: the provider has already acknowledged."""
    if not isinstance(raw, dict) or raw.get("private") is not True:
        return None
    for key in ("sender", "chat"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            return None
    for key in ("text", "action", "reply_to"):
        if raw.get(key) is not None and not isinstance(raw[key], str):
            return None
    return {"sender": raw["sender"], "chat": raw["chat"], "private": True, "text": raw.get("text"), "action": raw.get("action"),
            "action_ref": None, "reply_to": raw.get("reply_to")}


class Run:
    """One start of the provider process, with the state only that start has."""

    def __init__(self, proc):
        self.proc = proc
        self.out = queue.Queue()      # (request id, line) for the writer thread; None ends it (stdin closes)
        self.ready_at = None
        self.code = None              # the exit code, once the process has exited
        self.reason = None            # the reason of the last error event it wrote
        self.kind = None              # and its kind (a word of ERROR_KINDS, else "other")
        self.tail = ""                # the last STDERR_TAIL characters it wrote to stderr
        self.threads = []
        self.stale = False            # set once the run has ended: a reader still stuck on its pipe feeds nothing

    @property
    def ready(self) -> bool:
        return self.ready_at is not None and self.code is None

    @property
    def exited(self) -> bool:
        return self.code is not None


class ListenSession:
    """One long-lived provider process that receives and sends (`listen`), kept running for as long as the bridge does.

    Threads per start: a writer (the only one that touches stdin), a reader (parses stdout, never blocks and never takes the
    writer's queue), a drain of stderr (keeps the last 300 characters, never logs them) and a watcher on `proc.wait()`
    (an exit is the leader's, never the end of stdout: a grandchild may keep that open). One supervisor thread starts the
    process, waits for `ready`, and decides after an exit: 2 or 3 stops the bridge (`fatal`), anything else starts again
    after a backoff. Delivery is at least once: a send in flight when the process dies fails, and the bridge sends the card
    again after the next ready. The options are injectable so tests need no clock."""

    def __init__(self, module, platform, root, implementation, log=None, ready_seconds=READY_SECONDS, send_seconds=SEND_SECONDS,
                 backoff=BACKOFF, reset_after=RESET_AFTER, stdin_wait=STDIN_WAIT, term_wait=TERM_WAIT, max_starts=MAX_STARTS,
                 window=START_WINDOW, clock=time.monotonic, queue_size=UPDATE_QUEUE, env=None, join_wait=5.0,
                 paused_wait=PAUSED_WAIT, paused_repeat=PAUSED_REPEAT):
        self.module, self.platform, self.root, self.implementation = module, platform, root, implementation
        self.log = log or (lambda text: print(text, file=sys.stderr, flush=True))
        self.ready_seconds, self.send_seconds, self.backoff, self.reset_after = ready_seconds, send_seconds, backoff, reset_after
        self.stdin_wait, self.term_wait, self.max_starts, self.window = stdin_wait, term_wait, max_starts, window
        self.clock, self.env, self.join_wait = clock, env, join_wait
        self.paused_wait, self.paused_repeat, self.paused_logged = paused_wait, paused_repeat, None
        self.queue_size = queue_size
        self.inbox = deque()                     # the updates, bounded by queue_size
        self.inbox_cv = threading.Condition()    # its own lock: the reader takes it for an instant and never waits on it
        self.woken = False
        self.cv = threading.Condition()          # guards run, closing, fatal, generation
        self.run = None
        self.closing = threading.Event()
        self.fatal = None                        # the sentence that stops the bridge, once there is one
        self.generation = 0                      # how many `ready` events have been seen
        self.waiting = {}                        # request id -> [Event, answer]
        self.waiting_lock = threading.Lock()     # its own lock: the reader never waits for anyone else's
        self.ids = itertools.count(1)            # keeps counting across restarts
        self.starts = deque()
        self.delay = backoff[0]
        self.full_noted = False
        self.thread = None

    # --- the bridge's side -------------------------------------------------------------------------------------

    def start(self) -> None:
        self.thread = threading.Thread(target=self.supervise, name="listen-supervisor", daemon=True)
        self.thread.start()

    def is_ready(self) -> bool:
        with self.cv:
            return self.run is not None and self.run.ready and self.fatal is None

    def next_update(self, timeout: float):
        """The next update, or None when none came within `timeout` or the session's state changed (look again)."""
        with self.inbox_cv:
            if not self.inbox and not self.woken:
                self.inbox_cv.wait(max(0.0, timeout))
            self.woken = False
            return self.inbox.popleft() if self.inbox else None

    def wake(self) -> None:
        with self.inbox_cv:
            self.woken = True
            self.inbox_cv.notify_all()

    def send(self, chat: str, message: dict) -> str:
        with self.cv:
            run = self.run
            if self.closing.is_set() or run is None or not run.ready:
                raise MessengerError("failed", "the messenger provider is not ready")
        number = next(self.ids)
        line = line_of({"id": number, "op": "send", "chat": str(chat), "message": message})
        if len(line) - 1 > MAX_LINE:
            raise MessengerError("usage", "the message is over the limit of one protocol line")
        entry = [threading.Event(), None]
        with self.waiting_lock:
            self.waiting[number] = entry
        if run.exited or self.closing.is_set():   # exit_loop and close() set their flag before they fail the waiting requests, so one of them sees this request
            with self.waiting_lock:
                self.waiting.pop(number, None)
            raise MessengerError("failed", "the messenger provider exited or is stopping")
        run.out.put((number, line))
        if not entry[0].wait(self.send_seconds):
            with self.waiting_lock:
                self.waiting.pop(number, None)
            raise MessengerError("failed", "the messenger provider did not answer in time")
        answer = entry[1]
        if answer.get("ok") is True:
            return Sent(answer["message_id"], answer.get("document_failed") is True)
        raise MessengerError(answer.get("kind", "failed"), answer.get("reason", "the send failed"))

    def close(self) -> None:
        """Stop: close the provider's stdin, wait stdin_wait, SIGTERM to its group, wait term_wait, SIGKILL, by group only.
        The worst case is stdin_wait + term_wait + 2 s after the kill + 2 s for the supervisor: 19 s with the defaults, so
        the jobs' 120 s and this fit the service's 150 s (runtime/service_bridge.py)."""
        with self.cv:
            self.closing.set()
            run = self.run
            self.cv.notify_all()
        if run is not None and not run.exited:
            run.out.put(None)
            for sig, wait in ((None, self.stdin_wait), (signal.SIGTERM, self.term_wait), (signal.SIGKILL, 2.0)):
                if sig is not None:
                    self.signal_group(run, sig)
                if self.wait_exit(run, wait):
                    break
        if self.thread is not None:
            self.thread.join(2.0)
        self.fail_waiting("the messenger provider was stopped")

    # --- the process -------------------------------------------------------------------------------------------

    def signal_group(self, run: Run, sig) -> None:
        try:
            os.killpg(run.proc.pid, sig)   # its own session: the group id is its pid
        except (ProcessLookupError, PermissionError):
            pass

    def wait_exit(self, run: Run, seconds: float) -> bool:
        end = self.clock() + seconds
        with self.cv:
            while not run.exited:
                left = end - self.clock()
                if left <= 0:
                    return False
                self.cv.wait(min(left, 0.2))
        return True

    def fail_waiting(self, reason: str) -> None:
        with self.waiting_lock:
            pending, self.waiting = self.waiting, {}
        for entry in pending.values():
            entry[1] = {"ok": False, "kind": "failed", "reason": reason}
            entry[0].set()

    def answer(self, number, answer: dict) -> bool:
        with self.waiting_lock:
            entry = self.waiting.pop(number, None)
        if entry is None:
            return False
        entry[1] = answer
        entry[0].set()
        return True

    def allow_start(self) -> bool:
        now = self.clock()
        while self.starts and now - self.starts[0] >= self.window:
            self.starts.popleft()
        if len(self.starts) >= self.max_starts:
            return False
        self.starts.append(now)
        return True

    def supervise(self) -> None:
        while not self.closing.is_set():
            if not self.allow_start():
                self.stop_bridge(f"the messenger provider was started {self.max_starts} times in 24 hours; the bridge stops so "
                                 "that the platform does not reset the bot's credential. Find why it keeps ending, then start the bridge again")
                return
            with self.cv:
                if self.closing.is_set():
                    return
                try:
                    proc = self.module.start(f"messenger:{self.platform}", "listen", ["--platform", self.platform], root=self.root,
                                             implementation=self.implementation, env=self.env)
                except self.module.ProviderCallError as e:
                    if e.kind == "not-configured":
                        self.fatal = e.reason
                        self.cv.notify_all()
                        self.wake()
                        return
                    proc = None
                    self.log(f"the messenger provider could not be started ({e.kind})")
                if proc is not None:
                    self.run = run = self.launch(proc)
            if proc is None:
                if not self.pause():
                    return
                continue
            self.watch(run)
            if self.closing.is_set():
                return
            code = run.code
            if run.ready_at is not None:
                self.paused_logged = None   # it was connected: the next pause is news again
            if code == 3 and run.kind == "paused":
                if not self.wait_paused(run):
                    return
                continue
            if code in (2, 3):
                self.stop_bridge(run.reason or run.tail or f"the messenger provider exited with {code}")
                return
            self.log(f"the messenger provider exited ({code}); starting it again")
            self.settle_delay(run)
            if not self.pause():
                return

    def wait_paused(self, run: Run) -> bool:
        """The provider's session is gone (exit 3 after an error event of kind "paused"): not fatal. This start is not charged to
        the ceiling, the backoff is left as it is, the reason is logged (again every paused_repeat seconds while it stays
        paused, never more often) and the provider is asked again after paused_wait seconds. False when the session is closing."""
        if self.starts:
            self.starts.pop()   # the timestamp of this start: the last one allow_start added
        now = self.clock()
        if self.paused_logged is None or now - self.paused_logged >= self.paused_repeat:
            self.paused_logged = now
            reason = redact_module().mask_secret_line(" ".join(str(run.reason or "no reason given").split()), limit=STDERR_TAIL)
            self.log(f"the messenger provider is paused and is asked again every {int(self.paused_wait)} seconds: {reason}")
        return not self.closing.wait(self.paused_wait)

    def settle_delay(self, run: Run) -> None:
        """The backoff starts again from its first wait only when the provider stayed ready for reset_after."""
        if run.ready_at is not None and self.clock() - run.ready_at >= self.reset_after:
            self.delay = self.backoff[0]

    def pause(self) -> bool:
        """The backoff before a restart. False when the session is closing."""
        wait, self.delay = self.delay, min(self.backoff[1], self.delay * 2)
        return not self.closing.wait(wait)

    def stop_bridge(self, reason: str) -> None:
        with self.cv:
            # the reason is shown to the person: whatever the provider wrote, credential formats and long key-like runs are masked
            text = redact_module().mask_secret_line(" ".join(str(reason).split()), limit=STDERR_TAIL)
            self.fatal = text or "the messenger provider stopped"
            self.cv.notify_all()
        self.wake()

    def launch(self, proc) -> Run:
        run = Run(proc)
        for target in (self.write_loop, self.read_loop, self.drain_loop, self.exit_loop):
            run.threads.append(threading.Thread(target=target, args=(run,), name="listen-" + target.__name__, daemon=True))
        for thread in run.threads:
            thread.start()
        return run

    def watch(self, run: Run) -> None:
        """Wait for ready (up to ready_seconds; missing it is a crash) and then for the exit; join the readers."""
        end, killed = self.clock() + self.ready_seconds, False
        with self.cv:
            while not run.exited and not self.closing.is_set():
                left = end - self.clock()
                if run.ready_at is None and not killed and left <= 0:
                    self.log("the messenger provider did not become ready in time; stopping it")
                    self.signal_group(run, signal.SIGKILL)
                    killed = True
                self.cv.wait(0.5 if run.ready_at is not None or killed else max(0.01, min(left, 0.5)))
        if run.exited and not self.closing.is_set():   # while closing there is no time for joins (see close)
            for thread in run.threads:
                thread.join(self.join_wait)
            run.stale = True
            if not any(t.is_alive() for t in run.threads):
                for stream in (run.proc.stdout, run.proc.stderr):
                    stream.close()

    def exit_loop(self, run: Run) -> None:
        code = run.proc.wait()
        self.signal_group(run, signal.SIGKILL)   # whatever it left behind
        with self.cv:
            run.code = code
            self.cv.notify_all()
        self.fail_waiting("the messenger provider exited")
        run.out.put(None)   # the writer ends and closes stdin
        self.wake()

    def write_loop(self, run: Run) -> None:
        stdin = run.proc.stdin
        while True:
            item = run.out.get()
            if item is None:
                break
            number, line = item
            if run.exited:
                self.answer(number, {"ok": False, "kind": "failed", "reason": "the messenger provider exited"})
                continue
            try:
                stdin.write(line)
                stdin.flush()
            except (OSError, ValueError):
                self.answer(number, {"ok": False, "kind": "failed", "reason": "the messenger provider's input is closed"})
        try:
            stdin.close()
        except (OSError, ValueError):
            pass

    def drain_loop(self, run: Run) -> None:
        stream = run.proc.stderr
        while True:
            try:
                chunk = stream.read1(4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            run.tail = " ".join((run.tail + " " + chunk.decode("utf-8", "replace")).split())[-STDERR_TAIL:]

    def read_loop(self, run: Run) -> None:
        stream = run.proc.stdout
        while True:
            try:
                line = stream.readline(MAX_LINE + 1)
            except (OSError, ValueError):
                return
            if not line:
                return
            if not line.endswith(b"\n"):
                if len(line) > MAX_LINE:
                    self.log("a line over the limit was dropped")
                    while line and not line.endswith(b"\n"):   # the rest of it, up to the next newline
                        try:
                            line = stream.readline(MAX_LINE + 1)
                        except (OSError, ValueError):
                            return
                    continue
                self.log("a line that did not end was dropped")
                return
            self.take(run, line[:-1])

    def take(self, run: Run, raw: bytes) -> None:
        """One line from the provider. Logged by class, never by content."""
        if run.stale:
            return
        try:
            found = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            self.log("a line that is not JSON was dropped")
            return
        if not isinstance(found, dict):
            self.log("a line that is not an object was dropped")
            return
        event = found.get("event")
        if event == "ready":
            with self.cv:
                run.ready_at = self.clock()
                self.generation += 1
                self.cv.notify_all()
            self.wake()
        elif event == "update":
            update = valid_update(found.get("update"))
            if update is None:
                self.log("an update that is not valid was dropped")
                return
            with self.inbox_cv:
                room = len(self.inbox) < self.queue_size
                if room:
                    self.inbox.append(update)
                    self.inbox_cv.notify_all()
            if room:
                self.full_noted = False
            elif not self.full_noted:
                self.full_noted = True
                self.log("the update queue is full; the newest updates are dropped")
        elif event == "error":
            kind = found.get("kind") if found.get("kind") in ERROR_KINDS else "other"
            run.kind = kind
            if isinstance(found.get("reason"), str):
                run.reason = " ".join(found["reason"].split())[:STDERR_TAIL]
            self.log(f"the messenger provider reported an error ({kind})")
        elif event is not None:
            self.log("an event of a kind that is not known was dropped")
        elif type(found.get("id")) is int and type(found.get("ok")) is bool:
            if found["ok"]:
                answer = {"ok": True, "message_id": found.get("message_id"), "document_failed": found.get("document_failed") is True}
                if not isinstance(answer["message_id"], str):
                    answer = {"ok": False, "kind": "failed", "reason": "the answer to a send has no message_id"}
            else:
                reason = found.get("reason") if isinstance(found.get("reason"), str) else "the send failed"
                answer = {"ok": False, "kind": found.get("kind") if found.get("kind") in ANSWER_KINDS else "failed",
                          "reason": " ".join(reason.split())[:STDERR_TAIL]}
            if not self.answer(found["id"], answer):
                self.log("an answer to a request that is not waiting was dropped")
        else:
            self.log("an object that is neither an event nor an answer was dropped")
