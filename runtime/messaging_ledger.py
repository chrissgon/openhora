# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The messaging bridge's ledger: what it sent, so that a restart sends nothing twice and a tapped button or a reply is
bound to the card the person saw (runtime/messaging.py).

One file, <state folder>/messaging-<platform>.json (the per-user state folder; the first versions kept it in <data_dir of the first project>), mode 0600, written through a temporary file of mode 0600 (O_EXCL, random name, fsync) and published with os.link the first time
(refusing a path someone placed) and os.replace after. It holds no text of a project: for each card the project's id, the pending decision's id and kind, the
content hash (a plan's hash, an effect's payload hash, else the sha256 of the card's decision text), the chat, the
platform's message id, the action ids made for it and the time it was sent; and the platform's next update offset.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import threading
import uuid

VERSION = 1
FILE = "messaging-{platform}.json"
LOCK = "messaging-{platform}.lock"
STATE_ENV = "OPENHORA_STATE_DIR"
PLATFORM = re.compile(r"[a-z0-9][a-z0-9-]*")  # a platform names the lock and the ledger


class LedgerError(Exception):
    """The ledger cannot be read or written; the message names the file, never its content."""


class StateError(Exception):
    """The state folder cannot be used (not a real directory of this user, or open to others): the shell exits 2."""


class LockHeld(Exception):
    """Another bridge of this user holds the lock of the platform: the shell exits 4."""


_HELD = []  # the open lock files: a lock lives as long as its descriptor, which is the process's


def state_dir(flag=None) -> str:
    """The state folder's path: the flag, else OPENHORA_STATE_DIR, else $XDG_STATE_HOME/openhora (set and absolute),
    else ~/.local/state/openhora. Not created here."""
    chosen = flag or os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def prepare_state_dir(flag=None) -> str:
    """Create the state folder (0700) and check it: a real directory (not a link), owned by this user, with no access
    for the group or others. StateError, naming the path, otherwise."""
    path = state_dir(flag)
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        found = os.lstat(path)
    except OSError as e:
        raise StateError(f"the state folder {path} cannot be made ({e.strerror or e.__class__.__name__})") from None
    if not stat.S_ISDIR(found.st_mode):
        raise StateError(f"the state folder {path} is not a real directory (a link or a file); remove it or use --state-dir")
    if found.st_uid != os.getuid():
        raise StateError(f"the state folder {path} is not owned by this user")
    if found.st_mode & 0o077:
        raise StateError(f"the state folder {path} is open to other users (mode {stat.S_IMODE(found.st_mode):04o}); "
                         "run chmod 700 on it")
    return path


def take_lock(folder: str, platform: str) -> str:
    """Take the exclusive, non-blocking lock of a platform's bridge on this machine and keep it for the life of the
    process (the system releases it when the process ends, so a crash leaves none stale). LockHeld when another process
    holds it. Returns the lock file's path."""
    path = os.path.join(folder, LOCK.format(platform=platform))
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        raise StateError(f"the lock file {path} cannot be opened ({e.strerror or e.__class__.__name__})") from None
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode) or found.st_uid != os.getuid():
            raise StateError(f"the lock file {path} is not a regular file of this user")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LockHeld(f"another messaging bridge already serves {platform} on this machine (its lock: {path}); "
                           "stop it first") from None
    except BaseException:
        os.close(fd)
        raise
    _HELD.append(fd)
    return path


class Ledger:
    def __init__(self, folder: str, platform: str, legacy_folder=None, served=(), log=None):
        """`folder` is the state folder. `legacy_folder` (the data_dir of the first served project) and `served` (the ids
        of the projects this bridge serves) are for the one-time migration; `log` gets its one line."""
        self.path = os.path.join(folder, FILE.format(platform=platform))
        self.platform = platform
        self.lock = threading.Lock()
        self.data = self._read()
        if legacy_folder and not os.path.lexists(self.path):
            self._migrate(os.path.join(legacy_folder, FILE.format(platform=platform)), set(served), log)

    def _migrate(self, old: str, served: set, log) -> None:
        if os.path.abspath(old) == os.path.abspath(self.path):
            return
        try:
            with open(old, encoding="utf-8") as f:
                before = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            if log:
                log(f"the earlier ledger {old} cannot be read; it is not migrated")
            return
        if not isinstance(before, dict) or before.get("version") != VERSION or not isinstance(before.get("cards"), list):
            return
        mine = [dict(c, platform=self.platform) for c in before["cards"] if isinstance(c, dict) and c.get("project") in served]
        self.data = {"version": VERSION, "offset": int(before.get("offset") or 0), "seq": int(before.get("seq") or 0),
                     "cards": mine}
        self._write()
        if log:
            log(f"the ledger moved to {self.path} ({len(mine)} card(s) of the projects served here); "
                f"the earlier file {old} can be deleted; only the first project's earlier file is read, so a project whose "
            "earlier cards sat elsewhere may get its open decisions carded once more")

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
        """Always through a temporary file of mode 0600 (O_EXCL, a random name, fsync), then published: the first write
        with os.link, which refuses a path that already holds anything, a link someone placed included; the next ones
        with os.replace. A crash leaves the old ledger or none, never a truncated one, and a stale temporary file
        never blocks a write."""
        folder = os.path.dirname(self.path)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        temporary = f"{self.path}.{uuid.uuid4().hex}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.data, indent=1))
                f.flush()
                os.fsync(f.fileno())
            if os.path.lexists(self.path):
                os.replace(temporary, self.path)
            else:
                os.link(temporary, self.path)
                os.unlink(temporary)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

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
            return any(self._mine(c) and c["project"] == project and c["pending_id"] == pending_id and c["chat"] == chat
                       and c["content_sha256"] == content_sha256 for c in self.data["cards"])

    def next_seq(self) -> int:
        """The next number action ids are made from (persisted by the next `add`)."""
        with self.lock:
            self.data["seq"] = int(self.data.get("seq") or 0) + 1
            return self.data["seq"]

    def _mine(self, card: dict) -> bool:
        """Whether a card is this platform's (the file is the platform's already; the key is kept on each card)."""
        return card.get("platform", self.platform) == self.platform

    def add(self, card: dict) -> None:
        with self.lock:
            self.data["cards"].append(dict(card, platform=self.platform))
            self._write()

    def last_card(self, project: str, pending_id: int, chat: str):
        """The newest card of a decision in a chat, or None."""
        with self.lock:
            found = [c for c in self.data["cards"] if self._mine(c) and c["project"] == project
                     and c["pending_id"] == pending_id and c["chat"] == chat]
            return dict(found[-1]) if found else None

    def by_action(self, chat: str, action_id: str):
        """The card that made this action id, in this chat, or None."""
        with self.lock:
            for c in reversed(self.data["cards"]):
                if self._mine(c) and c["chat"] == chat and action_id in c["actions"]:
                    return dict(c)
            return None

    def by_message(self, chat: str, message_id: str):
        """The card the platform's message id names, in this chat, or None."""
        with self.lock:
            for c in reversed(self.data["cards"]):
                if self._mine(c) and c["chat"] == chat and c["message_id"] == message_id:
                    return dict(c)
            return None
