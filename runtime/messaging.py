#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge: the operations layer of runtime/ops.py reached from a messaging app the person already uses,
with no model between the app and the operations. A shell like the terminal's, the local service's and the MCP mode's:
it holds no rule about the work. What it adds is the channel `messaging` (runtime/operations.py), a provider of the class
messenger:<platform> (providers/messenger/README.md) for each platform, and the logic of runtime/messaging_*.py.

Usage:
  uv run --with keyring==25.7.0 python3 runtime/messaging.py --project <dir> [--project <dir>]... --platform <platform>
                                                            [--notice-every 60] [--state-dir <dir>] [--stop-on-stdin-eof]
  python3 runtime/messaging.py --help

  --project       a project folder (runtime/project_config.py); repeat for several. Its configuration must be accepted
                  (`accept-config` in the terminal) and name who may write to the bot:
                  "messaging": {"senders": {"<platform>": ["<sender id>"]}, "notices": "text" | "count", "page_url": null}
  --platform      the messaging platform, such as telegram; the provider that serves it is chosen by the class
                  messenger:<platform> (providers/resolve.py). Its credential is read by the provider from the secret
                  store (contracts/secrets.md); this process never sees it
  --notice-every  seconds between two looks at what waits for the person, and between two re-checks of the projects that
                  are skipped (default 60)
  --state-dir     the per-user state folder, which holds the ledger and the lock (default $OPENHORA_STATE_DIR, else
                  $XDG_STATE_HOME/openhora when that is set and absolute, else ~/.local/state/openhora; made 0700 and
                  checked: a real directory of this user with no group or other access, else exit 2). Nothing in it
                  enters a repository
  --stop-on-stdin-eof
                  stop, as SIGTERM does, when standard input ends. Off by default: a bridge started by hand under nohup,
                  &, launchd or systemd has its standard input at /dev/null and must not stop at once. The local service
                  (runtime/service.py --messaging) starts the bridge with it and holds the pipe open

One bridge per platform and user: the process takes an exclusive lock on <state folder>/messaging-<platform>.lock before
anything else and holds it for its life (the system releases it when the process ends, so a crash leaves none stale);
another bridge of the same platform and user exits 4 with the lock's path.

The person starts this process and it runs until SIGINT or SIGTERM; it then stops polling and ends the runs it started
(ops.stop_runs). One JSON line is printed at the start: the platform and the projects (their ids and names), never a sender
or a token. Standard error gets a log of events with no sender id, no text and no result.

What it does. Every notice period, each decision that waits gets one card in the chat of each listed sender (a
platform-neutral message: header, body, actions), once per content. A tap or a typed command is bound to the card
the person saw; free text goes to the planning agent (`say`). Who may write is the accepted configuration's list; any
other sender, and any chat that is not private, is dropped. What the channel may do is the table's ceiling narrowed by the
project's policy (`channels.messaging`, closed by default: read, talk, answer); an effect is never approved from here.

A project whose configuration is not accepted, or whose accepted configuration lists no sender for the platform, is skipped
(one log line naming it and why, when its state changes) and looked at again every notice period; it is served from its
accepted file the moment it is ready. With every project skipped the bridge keeps running.

Exit codes: 0 stopped, 2 usage error (also a state folder that is not safe), 3 a folder given is not a configured project, or
the messenger provider is not configured (also: another program reads the same bot's updates, or a webhook is set; the
error above says which), 4 another bridge already serves the platform for this user.
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ops  # noqa: E402  (the same folder: the operations layer)
import shell_kit  # noqa: E402  (the same folder: the kit the shells share)
import messaging_bridge as bridge  # noqa: E402  (its own modules: runtime/messaging_*.py)
import messaging_ledger as ledgers  # noqa: E402
import messaging_provider as providers  # noqa: E402

PLATFORM = re.compile(r"[a-z0-9][a-z0-9-]*")  # a platform names the lock and the ledger files
DEFAULT_NOTICE_EVERY = 60
MIN_NOTICE_EVERY = 5


class Stop(BaseException):
    """A signal asked the bridge to stop."""


class Refused(Exception):
    pass


def parse(argv) -> dict:
    """{"projects", "platform", "notice_every", "state_dir", "stop_on_stdin_eof"} of the command line. Refused for an
    unknown argument, a flag without its value, no project, no platform or a platform that is not a lowercase word."""
    projects, platform, every, state, eof, args = [], None, DEFAULT_NOTICE_EVERY, None, False, list(argv)
    while args:
        flag = args.pop(0)
        if flag == "--stop-on-stdin-eof":
            eof = True
            continue
        if flag not in ("--project", "--platform", "--notice-every", "--state-dir"):
            raise Refused(f"unknown argument {flag!r}")
        if not args:
            raise Refused(f"{flag} needs a value")
        value = args.pop(0)
        if flag == "--project":
            projects.append(value)
        elif flag == "--platform":
            platform = value
        elif flag == "--state-dir":
            state = value
        else:
            if not (value.isascii() and value.isdigit()) or int(value) < MIN_NOTICE_EVERY:
                raise Refused(f"--notice-every is a whole number of seconds, {MIN_NOTICE_EVERY} or more")
            every = int(value)
    if not projects:
        raise Refused("give at least one --project <dir>")
    if not platform:
        raise Refused("give --platform <platform>")
    if not PLATFORM.fullmatch(platform):
        raise Refused("--platform is a lowercase word of letters, digits and hyphens, such as telegram")
    return {"projects": projects, "platform": platform, "notice_every": every, "state_dir": state, "stop_on_stdin_eof": eof}


def serve(argv_projects, platform: str, notice_every: float = DEFAULT_NOTICE_EVERY, ops_module=None, messenger=None,
          log=None, stop=None, poll: int = bridge.POLL_SECONDS, out=None, state_dir: str = None) -> int:
    """Check that each folder is a configured project, open the ledger in `state_dir` (the state folder; main() made and
    locked it; None: the default one, made and checked here), print the start line, then poll and notify until `stop` is
    set or a signal arrives (Stop); a project not yet ready is skipped and looked at again each notice period. Then end the
    runs the bridge started (ops.stop_runs, waited for). Returns the exit code."""
    ops_module = ops_module or ops
    log = log or shell_kit.default_log
    out = out or sys.stdout
    stop = stop or threading.Event()
    try:
        found = shell_kit.projects_of(argv_projects, ops_module)
        if not found:
            raise ops_module.OpsError("no project was given", 2)
        state_dir = state_dir or ledgers.prepare_state_dir()
        ledger = ledgers.Ledger(state_dir, platform, legacy_folder=found[0]["data_dir"], served=[p["id"] for p in found], log=log)
        messenger = messenger or providers.Messenger(platform)
        messenger.capabilities()
    except (Refused, ledgers.StateError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ops_module.OpsError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    except (providers.MessengerError, ledgers.LedgerError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 3 if getattr(e, "kind", "") == "not-configured" else 1
    server = bridge.Bridge(ops_module, found, messenger, ledger, platform, log)
    print(json.dumps({"platform": platform, "projects": [{"id": p["id"], "name": p["name"]} for p in found]}), file=out, flush=True)
    code = 0
    try:
        getattr(messenger, "open_session", lambda log: None)(log)   # a provider that listens is started here, once
        server.serve_loop(stop, notice_every, poll)
    except Stop:
        pass
    except bridge.Fatal as e:
        print(f"error: {e}", file=sys.stderr)
        code = 3
    finally:
        server.stopping.set()
        left = server.end_runs()
        if left:
            log(f"stopped with {left} job thread(s) still ending")
        getattr(messenger, "close_session", lambda: None)()   # after the jobs: their replies still need the provider
    return code


def watch_stdin(stream, on_end) -> threading.Thread:
    """With --stop-on-stdin-eof: a thread reads the stream and, when it ends, calls `on_end` (main: a SIGTERM to this
    process, so the stop is the one a signal makes). What is read is dropped."""
    def read():
        try:
            source = getattr(stream, "buffer", stream)
            while source.read(4096):
                pass
        except (OSError, ValueError):
            pass
        on_end()
    thread = threading.Thread(target=read, name="stdin-watch", daemon=True)
    thread.start()
    return thread


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    try:
        given = parse(argv)
    except Refused as e:
        print(f"error: {e}. See --help.", file=sys.stderr)
        return 2

    try:
        folder = ledgers.prepare_state_dir(given["state_dir"])
        ledgers.take_lock(folder, given["platform"])
    except ledgers.StateError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ledgers.LockHeld as e:
        print(f"error: {e}", file=sys.stderr)
        return 4

    def on_signal(signum, _frame):
        if getattr(on_signal, "seen", False):
            return
        on_signal.seen = True
        raise Stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, on_signal)
    if given["stop_on_stdin_eof"]:
        watch_stdin(sys.stdin, lambda: os.kill(os.getpid(), signal.SIGTERM))
    try:
        return serve(given["projects"], given["platform"], given["notice_every"], state_dir=folder)
    except Stop:
        return 0   # a signal that landed outside serve's own try (just after the start line, say): nothing was started, so there is nothing to end


if __name__ == "__main__":
    sys.exit(main())
