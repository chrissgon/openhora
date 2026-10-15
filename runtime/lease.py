#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""One host writes the sources folder at a time, and no database or lock lives in a synced folder (package P-OPS, finding I4).

The sources folder (runtime/sources.py) is the one place of a project the person may keep in a synced drive or a repository, so
that two machines can see it. The runtime on each machine writes into it, and a sync client merges two writers' files into
conflicts. Two things keep that from happening in silence (limit L28):

  The lease. A host that writes the sources folder first takes its lease: a small file, `.openhora-lease`, written through the
  descriptor of the folder with `O_NOFOLLOW`, holding the host id, the host's name, the pid, the time it was taken and when it ends.
  A second host that finds a live lease of another host refuses to write and names that host and the time the lease ends; an
  expired lease is taken over; a lease of the same host (any process) is renewed. The lease is taken always, not only when the
  folder is known to be synced, because a synced folder cannot be recognised in general (a mounted share, a repository pulled by
  hand, a sync client this code has never heard of) and the cost is one small file renewed by each write. It lasts
  LEASE_SECONDS (5 minutes) after the last write, so it still stands when the other machine's sync client brings it over a
  little late; it is not removed when the write ends, for the same reason. Where the lease cannot protect: a sync that takes
  longer than that to bring the lease over, and two hosts that start in the same instant, before either file reaches the other.
  It catches the common mistake (the runtime left running on two machines against one folder), not every race, and says so.

  The host id. A random identifier made once and kept in `<data_dir>/host-id` (mode 0600), so it belongs to the machine's own
  local folder, never to the synced one. `data_dir` is a machine's own folder (run folders and locks).

  Nothing else lives in a synced folder. `data_dir` and the store's database are refused when they sit in one (`synced_reason`,
  read by project_config.load): SQLite and a lock file do not survive a sync client. A folder is taken as synced when a component of
  its real path is the name of a sync client's folder (iCloud Drive, Dropbox, OneDrive, Google Drive, Nextcloud...) or a parent
  holds a marker file one of them leaves (`.dropbox`, `.stfolder`...). A closed list: a client it does not know is not detected, and the
  refusal says what it saw.

Standard library only. Runs on Python 3.9: python3 runtime/lease.py --help
"""
from __future__ import annotations

import datetime
import json
import os
import re
import secrets
import socket
import stat
import sys

LEASE_NAME = ".openhora-lease"
HOST_ID_NAME = "host-id"
LEASE_SECONDS = 300
LEASE_MAX_BYTES = 4096
HOST_ID = re.compile(r"[0-9a-f]{16}")

# Names of the folders sync clients keep (compared in lower case, by prefix, as a client adds the account: "OneDrive - Company").
SYNC_FOLDER_PREFIXES = ("mobile documents", "cloudstorage", "icloud", "dropbox", "onedrive", "google drive", "googledrive",
                        "my drive", "box sync", "nextcloud", "pcloud", "megasync")
# Files a sync client leaves in the folder it syncs (checked in the path and each of its parents).
SYNC_MARKERS = (".dropbox", ".dropbox.cache", ".stfolder", ".csync_journal.db", ".owncloudsync.log", ".nextcloudsync.log")


class LeaseError(Exception):
    """Another host holds a live lease on the sources folder. `holder` is {"host_id", "host_name", "pid", "expires_at"}."""

    def __init__(self, message: str, holder=None):
        super().__init__(message)
        self.holder = holder or {}


def synced_reason(path: str):
    """A sentence saying why `path` looks like it is in a synced folder, or None. The real path is read (a link into a synced drive is
    in it), and each parent is looked at for a marker file of a sync client."""
    real = os.path.realpath(path)
    parts = [p for p in real.split(os.sep) if p]
    for part in parts:
        lowered = part.lower()
        if lowered.startswith(SYNC_FOLDER_PREFIXES):
            return f"{real} is inside a folder named {part!r}, which a sync client keeps"
    current = real
    while True:
        for marker in SYNC_MARKERS:
            try:
                os.lstat(os.path.join(current, marker))
            except OSError:
                continue
            return f"{current} holds {marker}, which a sync client leaves in the folder it syncs"
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def host_identity(data_dir: str) -> dict:
    """{"id", "name"}: the host id kept in `<data_dir>/host-id` (made once, mode 0600, opened with O_NOFOLLOW), and the machine's
    name for people to read. A file that is not an id is replaced."""
    os.makedirs(data_dir, mode=0o700, exist_ok=True)
    path = os.path.join(data_dir, HOST_ID_NAME)
    name = (socket.gethostname() or "this host")[:64]
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, os.O_RDONLY | nofollow)
        try:
            text = os.read(fd, 64).decode("ascii", errors="replace").strip()
        finally:
            os.close(fd)
        if HOST_ID.fullmatch(text):
            return {"id": text, "name": name}
    except OSError:
        pass
    host_id = secrets.token_hex(8)
    temporary = f"{path}.{secrets.token_hex(4)}.new"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(host_id + "\n")
    os.replace(temporary, path)
    return {"id": host_id, "name": name}


def read(folder_fd: int):
    """The lease in the folder as a dict, or None when there is none or it cannot be read as one (a lease a sync client damaged is
    taken as expired, never trusted). Opened with O_NOFOLLOW from the folder's descriptor, at most LEASE_MAX_BYTES."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        info = os.stat(LEASE_NAME, dir_fd=folder_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            return None
        fd = os.open(LEASE_NAME, os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0), dir_fd=folder_fd)
    except OSError:
        return None
    try:
        data = os.read(fd, LEASE_MAX_BYTES + 1)
    finally:
        os.close(fd)
    try:
        value = json.loads(data.decode("utf-8"))
    except ValueError:
        return None
    ok = (isinstance(value, dict) and isinstance(value.get("host_id"), str) and HOST_ID.fullmatch(value["host_id"])
          and isinstance(value.get("expires_at"), (int, float)) and not isinstance(value.get("expires_at"), bool))
    return value if ok else None


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def take(folder_fd: int, data_dir: str, *, now: float, pid=None, seconds: int = LEASE_SECONDS) -> dict:
    """Take or renew the lease of the open sources folder (its descriptor), or refuse. Another host's live lease: LeaseError naming
    the host. Otherwise the lease is written whole into a new file and renamed into place, through the folder's descriptor. Returns
    {"host_id", "host_name", "pid", "taken_at", "expires_at", "took_over": the old holder's name or None}."""
    me = host_identity(data_dir)
    old = read(folder_fd)
    took_over = None
    if old is not None and old["host_id"] != me["id"]:
        if old["expires_at"] > now:
            who = str(old.get("host_name") or old["host_id"])[:64]
            raise LeaseError(f"the sources folder is being written by another host, {who} (pid {old.get('pid')}), whose lease lasts "
                             f"until {_iso(old['expires_at'])}: this host does not write while it lasts. Stop the runtime on {who}, "
                             "or wait for the lease to end", holder={k: old.get(k) for k in ("host_id", "host_name", "pid", "expires_at")})
        took_over = str(old.get("host_name") or old["host_id"])[:64]
    lease = {"host_id": me["id"], "host_name": me["name"], "pid": os.getpid() if pid is None else pid,
             "taken_at": _iso(now), "expires_at": now + seconds, "expires": _iso(now + seconds)}
    temporary = f"{LEASE_NAME}.{secrets.token_hex(4)}.new"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=folder_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(lease, sort_keys=True) + "\n")
        os.rename(temporary, LEASE_NAME, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=folder_fd)
        except OSError:
            pass
        raise
    return {**lease, "took_over": took_over}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--help", "-h"):
        print(__doc__)
        return 0
    print("error: this module is a library of runtime/sources.py and runtime/project_config.py; see --help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
