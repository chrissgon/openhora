#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operation `media-remove` (package media-remove): one recording removed from the media store for good, at the person's request. Without
`confirm` it removes nothing and says what would go; with `confirm` it removes the folder whole. It is refused while a task that has not ended
works on the recording: every task that names it must be `done`, `cancelled` or `failed`, and none may be running. Terminal and page; the page
needs the group `media`; it may cross the LAN socket (only an id crosses; it is not in operations.LAN_REFUSED_OPS). Nothing new is stored: the
answer says what was removed.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import fcntl
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import media  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media  # noqa: E402

OPERATION = "media-remove"
REMOVABLE = ("done", "cancelled", "failed")        # a task in one of these no longer works on its recording (ops_step_seams.MediaStore.bind: cancelled or failed may be replaced; done is final)
WARNING = ("this removes the recording for good, with its transcript, its work files, its still and its delivered video; it cannot be undone, "
           "and nothing is removed until it is confirmed")


def _held(cfg: dict, task_id: int) -> bool:
    """Whether a live process holds the lock of the task (<data_dir>/locks/task-<id>.lock): probed with a shared lock let go at once, as
    runtime/upkeep.py lock_held does. A missing file is not held; nothing is created or written."""
    path = os.path.join(cfg["data_dir"], "locks", f"task-{int(task_id)}.lock")
    try:
        fd = os.open(path, os.O_RDONLY | media.NOFOLLOW)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        os.close(fd)
    return False


def _holders(ctx: dict, rid: str, bound) -> list:
    """The task rows that name the recording: every step task of the kind `media` whose step_args name it, and the task the record binds
    (when it still exists and is not among them). Oldest first."""
    store = ctx["store"]
    rows = []
    for task in core._stored(ctx, store.tasks_list):
        args = task.get("step_args")
        if store.is_step_task(task) and task.get("step_kind") == ops_media.KIND and isinstance(args, dict) and args.get("media") == rid:
            rows.append(task)
    if bound is not None and not any(row["id"] == bound for row in rows):
        try:
            rows.append(core._stored(ctx, store.task_get, bound))
        except core.OpsError:
            pass
    return sorted(rows, key=lambda row: row["id"])


def media_remove(project: str, media_id, confirm=False, channel=None) -> dict:
    """Remove one recording from the media store for good. Without confirm: {"media", "removed": False, "bytes", "files", "created_at",
    "delivered_at", "tasks", "warning"} and nothing is removed. With confirm: {"media", "removed": True, "bytes", "files", "delivered_at",
    "tasks", "left"}. core.OpsError when the channel may not call it, the recording is unknown, or a task that has not ended works on it."""
    ctx = core.context(project)
    ops_media._channel(ctx, OPERATION, channel)
    if not (type(confirm) is bool or confirm is None):
        raise core.OpsError("confirm is true or false", 2)
    data_dir = ctx["cfg"]["data_dir"]
    try:
        record = media.load(data_dir, media.check_id(media_id))
    except media.MediaError as e:
        raise ops_media._media_error(e) from None
    holders = _holders(ctx, media_id, record["task"])
    for row in holders:
        if row["state"] not in REMOVABLE:
            raise core.OpsError(f"recording {media_id} is in task {row['id']} of request {row.get('parent_id')}, which is {row['state']}: "
                                "finish the video or cancel the request first", 1)
        if _held(ctx["cfg"], row["id"]):
            raise core.OpsError(f"recording {media_id} is in task {row['id']}, which is running now: wait until it stops", 1)
    tasks = [row["id"] for row in holders]
    delivered_at = (record["delivered"] or {}).get("at")
    try:
        if not confirm:
            measured = media.footprint(data_dir, media_id)
            return {"media": media_id, "removed": False, "bytes": measured["bytes"], "files": measured["files"],
                    "created_at": record["created_at"], "delivered_at": delivered_at, "tasks": tasks, "warning": WARNING}
        done = media.remove(data_dir, media_id, task=record["task"])
    except media.MediaError as e:
        raise ops_media._media_error(e) from None
    return {"media": media_id, "removed": True, "bytes": done["bytes"], "files": done["files"], "delivered_at": done["delivered_at"],
            "tasks": tasks, "left": done["left"]}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
