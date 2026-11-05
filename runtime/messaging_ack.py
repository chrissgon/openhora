#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""One short acknowledgement when a reply takes time (slice S19): a small helper of the messaging bridge, never a gate.

A plain line on a messaging app that has not been answered after `ACK_DELAY` seconds gets ONE short sentence in the chat's language ("Vou ver seus e-mails...", "Procurando
o arquivo...") and then, when it is ready, the real reply. The sentence is chosen by code, with no model call, from the stage the job had reached when the time ran out
(runtime/line_stage.py: a closed list the operations layer sets where the work begins); a line whose stage is not known gets the generic sentence. It never quotes the
person's words. The rules:

  - a line that is answered within `ACK_DELAY` seconds gets nothing (an answer of code is never announced);
  - a line that begins with `/` (a typed command) and a line that is, whole, an approve or reject word (runtime/card_words.py) never get one;
  - one handle sends at most once: never twice for one line, and never after the reply: `stop` is called before anything of the reply is sent and nothing starts after it;
  - the send is made on a thread of its own, from the timer: the reply path never waits for it (`stop` only sets a flag, it does not wait for a send that is already in
    flight, so the one case in which the two reach the platform close together is a send that began just before the reply; a reply never waits for the courtesy);
  - every failure of the send is ignored with no log (the text of a failure may hold a chat id): the reply is as it would have been.

The sentence is `ACK_<STAGE>` of runtime/phrases.py (`ACK_GENERIC` for none); the bridge builds and sends it (`Bridge.acknowledge`), this module only decides when.

Standard library only. Runs on Python 3.9: python3 runtime/messaging_ack.py --help
"""
from __future__ import annotations

import sys
import threading

import card_words
import line_stage

ACK_DELAY = 2.0         # seconds a line waits for its reply before the acknowledgement is sent


def key(stage) -> str:
    """The key of the phrase table for a stage: `ACK_<STAGE>`, or `ACK_GENERIC` for a stage that is none of the closed list."""
    return "ACK_" + (stage.upper() if stage in line_stage.STAGES else "GENERIC")


class Ack:
    """One acknowledgement for one line. `send(chat, stage)` sends the sentence (the bridge's `acknowledge`); `begin(chat, text)` returns a handle whose `stop()` is idempotent."""

    def __init__(self, send, delay=None):
        self.send = send
        self.delay = ACK_DELAY if delay is None else delay

    def wanted(self, text) -> bool:
        """Whether a line may get the acknowledgement: a plain line, not a typed command, not an approve or reject word."""
        if not isinstance(text, str) or not text.strip() or text.lstrip().startswith("/"):
            return False
        return card_words.card_word(text) is None

    def begin(self, chat, text):
        """Start the timer for a line, on the thread that runs it (the stage is published from this thread). An unwanted line gets an inert handle."""
        handle = _Handle(self, chat, text)
        try:
            if self.wanted(text):
                handle.start()
        except Exception:      # a thread that cannot start is no acknowledgement: never a lost reply
            handle.stop()
        return handle


class _Handle:
    def __init__(self, owner: Ack, chat, text=None):
        self.owner, self.chat, self.text = owner, chat, text
        self.done = threading.Event()
        self.gate = threading.Lock()      # makes "send or not" and "stop" one decision: after `stop` returns no send begins
        self.slot = None
        self.sent = False

    def start(self) -> None:
        self.slot = line_stage.watch()
        threading.Thread(target=self.run, name="ack", daemon=True).start()

    def run(self) -> None:
        if self.done.wait(self.owner.delay):
            return
        with self.gate:
            if self.done.is_set() or self.sent:
                return
            self.sent = True
            stage = self.slot.stage if self.slot is not None else None
        try:
            self.owner.send(self.chat, stage)
        except Exception:      # silent: the acknowledgement is a courtesy
            pass

    def stop(self) -> None:
        with self.gate:      # held for an instant only: never for the send
            self.done.set()
        line_stage.release(self.slot)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
