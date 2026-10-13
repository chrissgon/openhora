#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Messenger provider for WhatsApp: an implementation of the class messenger:<platform> for the platform whatsapp,
through an unofficial WhatsApp Web client (whatsmeow, a Go library) in a small program built from source in
providers/messenger/whatsapp/ (providers/messenger/README.md holds the interface every messenger implements and the
WhatsApp section holds the risk, the setup and the privacy). This script is the thin side: it builds the program,
checks the build, runs its pairing commands, and, for `listen`, replaces itself with the program, which speaks the
listen protocol. It works only in the listen mode. Standard library only.

Verbs (JSON on stdout, diagnostics on stderr, input by flags, no prompt):
  capabilities --platform whatsapp
  build                               build the program with the local Go toolchain; record what was built
  pair --phone <digits>               link this computer as a device of the account of <digits>, with a pairing code
                                      (interactive: run it in a terminal)
  status                              print {"paired": bool, "phone": "<digits>" | null}; never connects
  whoami [--seconds 120]              print, in the terminal, the phone digits of whoever writes to the bridge's number
                                      meanwhile; refuses while a bridge runs
  listen --platform whatsapp          the long-lived verb (the protocol of providers/messenger/README.md)
  receive, send, ack                  exit 2: whatsapp works only in listen mode

The state is under the state folder (the environment variable OPENHORA_STATE_DIR, else an absolute XDG_STATE_HOME with
/openhora added, else ~/.local/state/openhora; the bridge's own --state-dir does not reach a provider): a real folder
of this user with no access for the group or others. In it, whatsapp/ (mode 0700) holds session.db (the WhatsApp
session: whoever holds it holds a linked device of the account), bin/whatsapp-bridge (the program) and build.json (what
was built). Everything is made under umask 077. The rule is written again here because a provider may not import
runtime/; a test holds the two equal.

build runs Go with GOENV=off (a `go env -w` setting of the person is ignored), GOFLAGS=-mod=readonly, GOWORK=off and
CGO_ENABLED=0, and without GOSUMDB, GONOSUMDB, GOPRIVATE, GONOPROXY and GOINSECURE, so the modules are verified against
go.sum (the checksum database is asked only about an entry go.sum lacks) and a newer toolchain that go.mod names is
downloaded and verified by the checksum database. It runs `go mod verify`, then `go build -trimpath -buildvcs=false
-mod=readonly`. build.json holds the sha256 of the program, of go.sum, and of go.mod, go.sum and every non-test .go
file together. listen refuses (error event of kind not-configured, exit 3) when the program is missing or differs from
build.json, or when the sources or go.sum differ from what was built (a stale build after an update). That is a check
for a stale or damaged build, not for tampering: whoever can rewrite build.json in a 0700 folder can already read the
session.

Exit codes: 0 ok, 1 failed, 2 usage (also: a bridge holds the platform's lock, in whoami), 3 not configured (not built,
a stale build, Go missing) or, in listen, the session is missing, unpaired or logged out (error event kind paused).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time

# The platforms this implementation serves. providers/resolve.py reads this one line as text, without importing the
# file, to choose among the implementations of messenger:<platform> (providers/CONTRACT.md).
PLATFORMS = ("whatsapp",)

EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
CAPABILITIES = {"max_text": 4096, "buttons": False, "max_buttons": 0, "max_button_label": 0, "lists": False,
                "max_list_rows": 0, "url_buttons": False, "reply_context": True, "documents": True, "listen": True}
HERE = os.path.dirname(os.path.abspath(__file__))
GO_DIR = os.path.join(HERE, "whatsapp")
STATE_ENV = "OPENHORA_STATE_DIR"
LOCK = "messaging-{platform}.lock"
FOLDER, BIN_FOLDER, BINARY, SESSION, BUILD_FILE = "whatsapp", "bin", "whatsapp-bridge", "session.db", "build.json"
PHONE = re.compile(r"[1-9][0-9]{5,14}")   # the same shape as phonePattern in the Go program
# Removed from the environment of every Go command: they would switch off, or point elsewhere, the checks of the modules.
GO_ENV_REMOVED = ("GOSUMDB", "GONOSUMDB", "GONOSUMCHECK", "GOPRIVATE", "GONOPROXY", "GOINSECURE", "GOFLAGS")
GO_ENV_SET = {"GOENV": "off", "GOFLAGS": "-mod=readonly", "GOWORK": "off", "CGO_ENABLED": "0"}
STATUS_SECONDS = 60
PAIR_COMMAND = "python3 providers/messenger/whatsapp.py pair --phone <digits>"
BUILD_COMMAND = "python3 providers/messenger/whatsapp.py build"


class Refusal(Exception):
    """The provider cannot go on. `kind` is the error event's kind (not-configured, paused or failed)."""

    def __init__(self, kind, reason):
        super().__init__(reason)
        self.kind, self.reason = kind, reason


# --- the state folder (the rule of runtime/messaging_ledger.py, written again: a provider may not import runtime/) ---------


def state_dir():
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def private_dir(path, what):
    """Make `path` (0700) when it is missing and check it: a real directory (not a link), owned by this user, with no access
    for the group or others. Refusal (not-configured) naming the path otherwise."""
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        found = os.lstat(path)
    except OSError as e:
        raise Refusal("not-configured", f"the {what} {path} cannot be made ({e.strerror or e.__class__.__name__})")
    if not stat.S_ISDIR(found.st_mode):
        raise Refusal("not-configured", f"the {what} {path} is not a real directory (a link or a file); remove it")
    if found.st_uid != os.getuid():
        raise Refusal("not-configured", f"the {what} {path} is not owned by this user")
    if found.st_mode & 0o077:
        raise Refusal("not-configured", f"the {what} {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); "
                                        "run chmod 700 on it")
    return path


def folders():
    """(state folder, whatsapp folder, bin folder), each made and checked."""
    state = private_dir(state_dir(), "state folder")
    own = private_dir(os.path.join(state, FOLDER), "WhatsApp folder")
    return state, own, private_dir(os.path.join(own, BIN_FOLDER), "WhatsApp program folder")


# --- what was built ----------------------------------------------------------------------------------------------------


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def source_files(go_dir=None):
    """go.mod, go.sum and every non-test .go file of the program, by name. Test files are not built, so a change to one
    is not a stale build."""
    go_dir = go_dir or GO_DIR
    names = [n for n in sorted(os.listdir(go_dir)) if n.endswith(".go") and not n.endswith("_test.go")]
    return ["go.mod", "go.sum"] + names


def sources_digest(go_dir=None):
    go_dir = go_dir or GO_DIR
    h = hashlib.sha256()
    for name in source_files(go_dir):
        with open(os.path.join(go_dir, name), "rb") as f:
            h.update(name.encode("utf-8") + b"\0" + f.read() + b"\0")
    return h.hexdigest()


def write_private_json(path, value):
    tmp = f"{path}.tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_build(own, binary, go_version, go_dir=None):
    go_dir = go_dir or GO_DIR
    write_private_json(os.path.join(own, BUILD_FILE), {
        "binary_sha256": sha256_file(binary),
        "go_sum_sha256": sha256_file(os.path.join(go_dir, "go.sum")),
        "sources_sha256": sources_digest(go_dir),
        "go_version": go_version,
        "built": time.strftime("%Y-%m-%d", time.gmtime()),
    })


def check_build(go_dir=None):
    """(program path, session path) when the build is whole and current; else a Refusal (not-configured) whose sentence
    names the build command."""
    go_dir = go_dir or GO_DIR
    state, own, bin_folder = folders()
    binary = os.path.join(bin_folder, BINARY)
    again = f"; run: {BUILD_COMMAND}"
    try:
        found = os.lstat(binary)
    except OSError:
        raise Refusal("not-configured", "the WhatsApp program is not built" + again)
    if not stat.S_ISREG(found.st_mode) or found.st_uid != os.getuid() or found.st_mode & 0o022 or not found.st_mode & 0o100:
        raise Refusal("not-configured", "the WhatsApp program is not a runnable file of this user, closed to others" + again)
    try:
        with open(os.path.join(own, BUILD_FILE), encoding="utf-8") as f:
            recorded = json.load(f)
        want = (recorded["binary_sha256"], recorded["go_sum_sha256"], recorded["sources_sha256"])
        if not all(isinstance(x, str) for x in want):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise Refusal("not-configured", "the record of the WhatsApp build is missing or unreadable" + again)
    try:
        if sha256_file(binary) != want[0]:
            raise Refusal("not-configured", "the WhatsApp program differs from what was built" + again)
        if sha256_file(os.path.join(go_dir, "go.sum")) != want[1] or sources_digest(go_dir) != want[2]:
            raise Refusal("not-configured", "the WhatsApp program is older than its sources (an update?)" + again)
    except OSError:
        raise Refusal("not-configured", "the WhatsApp program or its sources cannot be read" + again)
    return binary, os.path.join(own, SESSION)


def go_environment(base=None):
    env = dict(os.environ if base is None else base)
    for name in GO_ENV_REMOVED:
        env.pop(name, None)
    env.update(GO_ENV_SET)
    return env


def run_go(go, args, env, go_dir, timeout):
    return subprocess.run([go] + args, cwd=go_dir, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def cmd_build(args):
    go = shutil.which("go")
    if not go:
        say("Go is not installed. Install Go (any recent release will do: go.mod names the exact toolchain and Go downloads and "
            "verifies it), then run build again. See providers/messenger/README.md, WhatsApp.")
        return EXIT_NOT_CONFIGURED
    try:
        state, own, bin_folder = folders()
    except Refusal as e:
        say(e.reason)
        return EXIT_NOT_CONFIGURED
    env = go_environment()
    try:
        before = sources_digest()
        version = run_go(go, ["version"], env, GO_DIR, 600)
        if version.returncode != 0:
            say("Go could not report its version (the toolchain download may have failed): " + tail(version.stderr))
            return EXIT_SERVICE
        verify = run_go(go, ["mod", "verify"], env, GO_DIR, 900)
        if verify.returncode != 0:
            say("go mod verify failed: a module differs from go.sum. Do not use this build. " + tail(verify.stdout + verify.stderr))
            return EXIT_SERVICE
        target = os.path.join(bin_folder, BINARY)
        temporary = f"{target}.tmp-{os.getpid()}"
        built = run_go(go, ["build", "-trimpath", "-buildvcs=false", "-mod=readonly", "-o", temporary, "."], env, GO_DIR, 1800)
    except (OSError, subprocess.TimeoutExpired) as e:
        say("Go could not be run: " + e.__class__.__name__)
        return EXIT_SERVICE
    if built.returncode != 0:
        remove(temporary)
        say("go build failed: " + tail(built.stderr))
        return EXIT_SERVICE
    try:
        changed = sources_digest() != before
    except OSError:
        changed = True
    if changed:
        remove(temporary)
        say("the sources changed while Go was building; nothing was installed or recorded. Run build again")
        return EXIT_SERVICE
    try:
        os.chmod(temporary, 0o700)
        os.replace(temporary, target)
        go_version = " ".join(version.stdout.split())
        record_build(own, target, go_version)
    except OSError as e:
        remove(temporary)
        say("the program could not be installed: " + (e.strerror or e.__class__.__name__))
        return EXIT_SERVICE
    print(f"Built {target}\nGo: {go_version}\nRecorded in {os.path.join(own, BUILD_FILE)}")
    return EXIT_OK


# --- verbs that run the program ----------------------------------------------------------------------------------------


def say(text):
    print(text, file=sys.stderr, flush=True)


def tail(text, limit=600):
    return " ".join((text or "").split())[-limit:]


def remove(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def error_event(kind, reason):
    print(json.dumps({"event": "error", "kind": kind, "reason": reason}, ensure_ascii=True), flush=True)


def program_status(binary, session):
    """The program's `status` answer: {"paired": bool, "phone": str | None}. Refusal (failed) when it cannot be read."""
    try:
        done = subprocess.run([binary, "status", "--session", session], capture_output=True, text=True,
                              timeout=STATUS_SECONDS, check=False)
        found = json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise Refusal("failed", "the WhatsApp program could not report the session's state")
    if done.returncode != 0 or not isinstance(found, dict) or type(found.get("paired")) is not bool:
        raise Refusal("failed", "the WhatsApp program could not report the session's state")
    return found


def cmd_listen(args):
    try:
        binary, session = check_build()
        if not os.path.isfile(session):
            raise Refusal("paused", f"the WhatsApp session is missing; link this computer with: {PAIR_COMMAND}")
        if not program_status(binary, session)["paired"]:
            raise Refusal("paused", f"the WhatsApp session is not paired or was logged out; link this computer again with: {PAIR_COMMAND}")
    except Refusal as e:
        error_event(e.kind, e.reason)
        return EXIT_SERVICE if e.kind == "failed" else EXIT_NOT_CONFIGURED
    sys.stdout.flush()
    sys.stderr.flush()
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # the program exits on a write error; Python's ignore would be inherited
    os.execv(binary, [binary, "listen", "--session", session, "--platform", "whatsapp"])
    return EXIT_SERVICE   # not reached: execv replaced the process


def run_program(program_args, hold_lock=False):
    """Run the program with the terminal as its input and output, and return its exit code."""
    try:
        binary, session = check_build()
    except Refusal as e:
        say(e.reason)
        return EXIT_NOT_CONFIGURED
    lock = None
    if hold_lock:
        lock = take_lock(state_dir())
        if lock is None:
            return EXIT_USAGE
    try:
        return subprocess.call([binary] + program_args[:1] + ["--session", session] + program_args[1:])
    except OSError as e:
        say("the WhatsApp program could not be run: " + (e.strerror or e.__class__.__name__))
        return EXIT_SERVICE
    finally:
        if lock is not None:
            os.close(lock)


def take_lock(state):
    """The platform's lock, non-blocking, held while whoami runs (a bridge holds it for its life). The descriptor, or None
    after saying that a bridge runs."""
    path = os.path.join(state, LOCK.format(platform="whatsapp"))
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        say(f"the lock file {path} cannot be opened ({e.strerror or e.__class__.__name__})")
        return None
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode) or found.st_uid != os.getuid():
            raise OSError("not a regular file of this user")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        say(f"a messaging bridge for whatsapp is running on this machine (it holds {path}); stop it first, then run whoami")
        return None
    return fd


def cmd_pair(args):
    if not PHONE.fullmatch(args.phone or ""):
        say("--phone is the number of the account as digits with the country code and no plus sign, for example 5511900000000")
        return EXIT_USAGE
    return run_program(["pair", "--phone", args.phone])


def cmd_status(args):
    return run_program(["status"])


def cmd_whoami(args):
    if not sys.stdout.isatty():
        say("whoami prints phone numbers and so writes only to a terminal; run it in one, not into a pipe, a file or a log")
        return EXIT_USAGE
    if not 1 <= args.seconds <= 600:
        say("--seconds is a number from 1 to 600")
        return EXIT_USAGE
    return run_program(["whoami", "--seconds", str(args.seconds)], hold_lock=True)


def cmd_capabilities(args):
    print(json.dumps(CAPABILITIES))
    return EXIT_OK


def cmd_one_shot(args):
    say("whatsapp works only in listen mode")
    return EXIT_USAGE


def build_parser():
    p = argparse.ArgumentParser(description="Messenger provider for WhatsApp (providers/messenger/README.md).")
    sub = p.add_subparsers(dest="verb", required=True)
    for name, func in (("capabilities", cmd_capabilities), ("build", cmd_build), ("status", cmd_status), ("listen", cmd_listen)):
        sub.add_parser(name).set_defaults(func=func)
    pair = sub.add_parser("pair")
    pair.add_argument("--phone", required=True)
    pair.set_defaults(func=cmd_pair)
    who = sub.add_parser("whoami")
    who.add_argument("--seconds", type=int, default=120)
    who.set_defaults(func=cmd_whoami)
    for name in ("receive", "send", "ack"):
        one = sub.add_parser(name)
        one.set_defaults(func=cmd_one_shot, one_shot=True)
    for parser in sub.choices.values():
        parser.add_argument("--platform", default="whatsapp", choices=PLATFORMS)
    for name in ("receive", "send", "ack"):
        for flag in ("--offset", "--timeout", "--chat", "--message-file", "--action-ref"):
            sub.choices[name].add_argument(flag)
    return p


def main(argv=None):
    os.umask(0o077)   # the session database and the files SQLite writes beside it (-wal, -shm, -journal) are made 0600
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
