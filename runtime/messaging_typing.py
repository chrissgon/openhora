#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The "typing..." indicator while a reply is prepared (slice S10): a small helper of the messaging bridge, never a gate.

A plain line of a sender goes to a job that may take a while (the interpreter, the router, a read of the person's accounts). On a platform that declares the capability
`typing` (Telegram today) the bridge shows the platform's typing indicator when the job has run for `START_DELAY` seconds, asks again every `INTERVAL` seconds, and stops when
the reply is sent or after `LIMIT` seconds, whichever is first. Nothing else is done with it:

  - a line that begins with `/` (a typed command: its reply is code, instant) never shows it; a plain line does, because the bridge cannot tell beforehand that code will
    answer it, but a job that ends within `START_DELAY` seconds (a tier-1 form, a greeting: code answers in milliseconds) shows nothing and is not held up by it;
  - a platform that does not declare `typing`, and a messenger with no `typing` method, are not asked anything;
  - the calls are made on a thread of their own and every failure is ignored with no log (the text of a failure may hold a chat id): the indicator never delays and never
    blocks the reply. `stop` does not wait for the thread: it only sets a flag, and a call that was already in flight when the reply went out is the one late indicator the
    platform clears by itself in a few seconds; no call is made after the flag is set.

Standard library only. Runs on Python 3.9: python3 runtime/messaging_typing.py --help
"""
from __future__ import annotations

import sys
import threading

START_DELAY = 0.5       # seconds a job runs before the first indicator: an answer of code is never announced
INTERVAL = 4.0          # seconds between two indicators (Telegram shows one for about five)
LIMIT = 60.0            # seconds after which the indicator is not asked again


class Typing:
    """One indicator for one chat while one reply is prepared. `begin(chat, text)` returns a handle; its `stop()` is idempotent."""

    def __init__(self, messenger, interval=None, limit=None, delay=None):
        self.messenger = messenger
        self.interval, self.limit, self.delay = (INTERVAL if interval is None else interval), (LIMIT if limit is None else limit), (START_DELAY if delay is None else delay)

    def wanted(self, text) -> bool:
        """Whether a line shows the indicator: a plain line, on a messenger that declares `typing`."""
        if not isinstance(text, str) or not text.strip() or text.lstrip().startswith("/") or not callable(getattr(self.messenger, "typing", None)):
            return False
        try:
            return self.messenger.capabilities().get("typing") is True
        except Exception:      # a messenger that cannot say what it can do is not asked
            return False

    def begin(self, chat, text):
        handle = _Handle(self, chat)
        try:
            if self.wanted(text):
                handle.start()
        except Exception:      # a thread that cannot start is no indicator: never a lost reply
            handle.done.set()
        return handle


class _Handle:
    def __init__(self, owner: Typing, chat):
        self.owner, self.chat = owner, chat
        self.done = threading.Event()
        self.thread = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name="typing", daemon=True)
        self.thread.start()

    def run(self) -> None:
        if self.done.wait(self.owner.delay):
            return
        waited = 0.0
        while True:
            if self.done.is_set():      # a late start after stop is a no-op
                return
            try:
                self.owner.messenger.typing(self.chat)
            except Exception:      # silent: the indicator is a courtesy
                pass
            if self.done.wait(self.owner.interval):
                return
            waited += self.owner.interval
            if waited >= self.owner.limit:
                return

    def stop(self) -> None:
        self.done.set()


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
