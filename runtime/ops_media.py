#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations of the media store (runtime/media.py): `media-in`, `media-list` and `media-purge`, and the two helpers
the shells and the dispatcher's round call: `media_receive` (the local service's streaming route: a body that is a
stream, not a JSON argument) and `purge_round`.

A sibling of runtime/ops.py, which exposes each of them under its name; no shell imports this file. The names every module
of the layer shares are read as `core.<name>` (runtime/ops_core.py).

  media_in(project, recording, file, slot)   take a file of the person's from disk into the store, through the same function
                                   the page's route uses. With no recording a recording id is issued; with one, the file is
                                   attached to it; with a slot, it is that slot's asset. Returns the facts of the file.
  media_list(project, recording)   the recordings of the store with their status, their raw file's facts, their slots and the
                                   dates the retention reads, and the store's use of its limits; no file is read but records.
  media_purge(project, recording)  apply the retention now (D7): what is due goes, and the edit task's run folders with it; with
                                   a recording id, that recording whatever its age. No model is called.
  media_receive(project, stream, length, recording, slot, name)   the service's route; the page channel's policy is checked by
                                   the service before the body is read.
  purge_round(project)             the dispatcher's round calls it: media-purge, in code, with no model.

A refusal of the store (media.MediaError) becomes an OpsError that carries `kind`, the family of the refusal, so that the
local service answers 413 for a body over the limit, 415 for a type it does not take, 507 for a full disk, and so on.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import sys

import ops_core as core
import media


def _refusal(error: "media.MediaError") -> "core.OpsError":
    out = core.OpsError(str(error), 2 if error.kind in ("usage", "length") else 1)
    out.kind = error.kind
    return out


def media_in(project: str, recording: str | None = None, file: str | None = None, slot: str | None = None) -> dict:
    """Take the file `file` into the media store of the project, through media.receive_file."""
    if not file:
        raise core.OpsError("media-in needs --file <path>", 2)
    ctx = core.context(project)
    try:
        return media.receive_file(ctx["cfg"]["data_dir"], file, recording=recording, slot=slot)
    except media.MediaError as e:
        raise _refusal(e) from None


def media_receive(project: str, stream, length, recording: str | None = None, slot: str | None = None,
                  name: str | None = None) -> dict:
    """Take a body that arrives as a stream into the store (the local service's route), through media.receive."""
    ctx = core.context(project)
    try:
        return media.receive(ctx["cfg"]["data_dir"], stream, length, recording=recording, slot=slot, name=name)
    except media.MediaError as e:
        raise _refusal(e) from None


def _shown(record: dict) -> dict:
    """A record as the shells show it: the facts and the dates, no path."""
    return {k: record.get(k) for k in ("id", "status", "created_at", "updated_at", "ended_at", "raw", "posts", "slots",
                                       "frozen", "tasks", "purged")}


def media_list(project: str, recording: str | None = None) -> dict:
    """The recordings of the store and its use of its limits."""
    ctx = core.context(project)
    data_dir = ctx["cfg"]["data_dir"]
    try:
        if recording is not None:
            return {"recordings": [_shown(media.load(data_dir, media.check_id(recording)))], "usage": media.usage(data_dir)}
        return {"recordings": [_shown(r) for r in media.records(data_dir)], "usage": media.usage(data_dir),
                "retention": {"raw_days": media.RAW_DAYS, "render_days": media.RENDER_DAYS,
                              "abandoned_days": media.ABANDONED_DAYS},
                "limits": {"max_bytes": media.MEDIA_MAX_BYTES, "max_seconds": media.MAX_SECONDS}}
    except media.MediaError as e:
        raise _refusal(e) from None


def _run_dirs_of(ctx: dict):
    """The function purge calls for a recording: the run folders of its edit task (every attempt is inside them), or None
    while a run of that task is going."""
    store, cfg = ctx["store"], ctx["cfg"]

    def of(record: dict):
        task = (record.get("tasks") or {}).get("edit")
        if not task:
            return []
        try:
            runs = store.task_runs_list(ctx["conn"], task)
        except store.StoreError:
            return []
        if any(r.get("status") == "running" for r in runs):
            return None
        return media.run_dirs_inside(cfg["data_dir"], [r.get("run_dir") for r in runs])

    return of


def media_purge(project: str, recording: str | None = None) -> dict:
    """Apply the retention now, in code. With a recording id, that recording is removed whatever its age."""
    ctx = core.context(project)
    try:
        if recording is not None:
            media.load(ctx["cfg"]["data_dir"], media.check_id(recording))
        return media.purge(ctx["cfg"]["data_dir"], run_dirs_of=_run_dirs_of(ctx), only=recording)
    except media.MediaError as e:
        raise _refusal(e) from None


def purge_round(project: str) -> dict:
    """The retention, for a dispatcher round: the same as media_purge without a recording. An error of the store never
    stops the round (the caller records nothing on a failure)."""
    return media_purge(project)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
