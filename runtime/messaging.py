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
                                                            [--notice-every 60]
  python3 runtime/messaging.py --help

  --project       a project folder (runtime/project_config.py); repeat for several. Its configuration must be accepted
                  (`accept-config` in the terminal) and name who may write to the bot:
                  "messaging": {"senders": {"<platform>": ["<sender id>"]}, "notices": "text" | "count", "page_url": null}
  --platform      the messaging platform, such as telegram; the provider that serves it is chosen by the class
                  messenger:<platform> (providers/resolve.py). Its credential is read by the provider from the secret
                  store (contracts/secrets.md); this process never sees it
  --notice-every  seconds between two looks at what waits for the person (default 60)

The person starts this process and it runs until SIGINT or SIGTERM; it then stops polling and ends the runs it started
(ops.stop_runs). One JSON line is printed at the start: the platform and the projects (their ids and names), never a sender
or a token. Standard error gets a log of events with no sender id, no text and no result.

What it does. Every notice period, each decision that waits gets one card in the chat of each listed sender (a
platform-neutral message: header, body, actions), once per content. A tap or a typed command is bound to the card
the person saw; free text goes to the planning agent (`say`). Who may write is the accepted configuration's list; any
other sender, and any chat that is not private, is dropped. What the channel may do is the table's ceiling narrowed by the
project's policy (`channels.messaging`, closed by default: read, talk, answer); an effect is never approved from here.

Exit codes: 0 stopped, 2 usage error (also a project whose accepted configuration lists no sender for the platform),
3 a project is not configured or its configuration is not accepted, or the messenger provider is not configured.
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
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

DEFAULT_NOTICE_EVERY = 60
MIN_NOTICE_EVERY = 5


class Stop(BaseException):
    """A signal asked the bridge to stop."""


class Refused(Exception):
    pass


def parse(argv) -> dict:
    """{"projects", "platform", "notice_every"} of the command line. Refused for an unknown argument, a flag without its
    value, no project or no platform."""
    projects, platform, every, args = [], None, DEFAULT_NOTICE_EVERY, list(argv)
    while args:
        flag = args.pop(0)
        if flag not in ("--project", "--platform", "--notice-every"):
            raise Refused(f"unknown argument {flag!r}")
        if not args:
            raise Refused(f"{flag} needs a value")
        value = args.pop(0)
        if flag == "--project":
            projects.append(value)
        elif flag == "--platform":
            platform = value
        else:
            if not (value.isascii() and value.isdigit()) or int(value) < MIN_NOTICE_EVERY:
                raise Refused(f"--notice-every is a whole number of seconds, {MIN_NOTICE_EVERY} or more")
            every = int(value)
    if not projects:
        raise Refused("give at least one --project <dir>")
    if not platform:
        raise Refused("give --platform <platform>")
    return {"projects": projects, "platform": platform, "notice_every": every}


def check_projects(found: list, platform: str, ops_module) -> None:
    """Every project must have an accepted configuration that lists at least one sender for the platform."""
    for project in found:
        settings = ops_module.config(project["path"])
        if not settings.get("accepted"):
            raise ops_module.OpsError(f"{project['name']}: the configuration is not accepted; run accept-config in the terminal "
                                      "first (the senders it lists are read only from an accepted file)", 3)
        senders = ((settings.get("messaging") or {}).get("senders") or {}).get(platform)
        if not senders:
            raise Refused(f"{project['name']}: runtime.json messaging.senders.{platform} lists no sender; add the id of "
                          "the person who may write to the bot and accept the configuration")


def serve(argv_projects, platform: str, notice_every: float = DEFAULT_NOTICE_EVERY, ops_module=None, messenger=None,
          log=None, stop=None, poll: int = bridge.POLL_SECONDS, out=None) -> int:
    """Check the projects, print the start line, then poll and notify until `stop` is set or a signal arrives (Stop);
    then end the runs the bridge started (ops.stop_runs, waited for). Returns the exit code."""
    ops_module = ops_module or ops
    log = log or shell_kit.default_log
    out = out or sys.stdout
    stop = stop or threading.Event()
    try:
        found = shell_kit.projects_of(argv_projects, ops_module)
        if not found:
            raise ops_module.OpsError("no project was given", 2)
        check_projects(found, platform, ops_module)
        ledger = ledgers.Ledger(found[0]["data_dir"], platform)
        messenger = messenger or providers.Messenger(platform)
        messenger.capabilities()
    except Refused as e:
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
    return code


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

    def on_signal(signum, _frame):
        if getattr(on_signal, "seen", False):
            return
        on_signal.seen = True
        raise Stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, on_signal)
    return serve(given["projects"], given["platform"], given["notice_every"])


if __name__ == "__main__":
    sys.exit(main())
