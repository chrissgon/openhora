# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's ledger: what it sent, so that a restart sends nothing twice and a tapped button or a reply is
bound to the card the person saw (runtime/messaging.py).

One file, <data_dir of the first project>/messaging-<platform>.json, mode 0600, created with O_EXCL on the first write
(as the local service creates its token file) and rewritten atomically (a temporary file of mode 0600 made with O_EXCL,
then os.replace). It holds no text of a project: for each card the project's id, the pending decision's id and kind, the
content hash (a plan's hash, an effect's payload hash, else the sha256 of the card's decision text), the chat, the
platform's message id, the action ids made for it and the time it was sent; and the platform's next update offset.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import threading

VERSION = 1
FILE = "messaging-{platform}.json"


class LedgerError(Exception):
    """The ledger cannot be read or written; the message names the file, never its content."""


class Ledger:
    def __init__(self, folder: str, platform: str):
        self.path = os.path.join(folder, FILE.format(platform=platform))
        self.platform = platform
        self.lock = threading.Lock()
        self.data = self._read()

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {"version": VERSION, "offset": 0, "seq": 0, "cards": []}
        except (OSError, ValueError):
            raise LedgerError(f"{self.path} cannot be read as the bridge's ledger") from None
        if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("cards"), list):
            raise LedgerError(f"{self.path} is not a ledger of this version")
        return data

    def _write(self) -> None:
        folder = os.path.dirname(self.path)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        text = json.dumps(self.data, indent=1)
        if not os.path.exists(self.path):  # the first write creates the file, never following a link someone placed
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            return
        temporary = f"{self.path}.{os.getpid()}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, self.path)

    # --- the offset ---------------------------------------------------------------------------------------------

    @property
    def offset(self) -> int:
        return int(self.data.get("offset") or 0)

    def set_offset(self, offset: int) -> None:
        with self.lock:
            if offset != self.offset:
                self.data["offset"] = int(offset)
                self._write()

    # --- the cards ----------------------------------------------------------------------------------------------

    def sent(self, project: str, pending_id: int, content_sha256: str, chat: str) -> bool:
        """Whether this decision, with this content, has a card in this chat already."""
        with self.lock:
            return any(c["project"] == project and c["pending_id"] == pending_id and c["chat"] == chat
                       and c["content_sha256"] == content_sha256 for c in self.data["cards"])

    def next_seq(self) -> int:
        """The next number action ids are made from (persisted by the next `add`)."""
        with self.lock:
            self.data["seq"] = int(self.data.get("seq") or 0) + 1
            return self.data["seq"]

    def add(self, card: dict) -> None:
        with self.lock:
            self.data["cards"].append(card)
            self._write()

    def last_card(self, project: str, pending_id: int, chat: str):
        """The newest card of a decision in a chat, or None."""
        with self.lock:
            found = [c for c in self.data["cards"] if c["project"] == project and c["pending_id"] == pending_id
                     and c["chat"] == chat]
            return dict(found[-1]) if found else None

    def by_action(self, chat: str, action_id: str):
        """The card that made this action id, in this chat, or None."""
        with self.lock:
            for c in reversed(self.data["cards"]):
                if c["chat"] == chat and action_id in c["actions"]:
                    return dict(c)
            return None

    def by_message(self, chat: str, message_id: str):
        """The card the platform's message id names, in this chat, or None."""
        with self.lock:
            for c in reversed(self.data["cards"]):
                if c["chat"] == chat and c["message_id"] == message_id:
                    return dict(c)
            return None
