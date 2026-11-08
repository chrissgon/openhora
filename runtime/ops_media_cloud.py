#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operation of a recording that comes from a Google Drive link a listed sender sent from a messaging app (package V1d-3, decision 14, limit L70). The
operations layer decides; the messaging bridge (runtime/messaging_cloud.py) only calls it and says the answer.

  video_phone_fetch(project, text, channel=None, sender=None)    fetch the recording the Drive link in `text` names and keep it (`video-phone-fetch`)

The call is the bridge's: any channel but `messaging` is refused first, then the sender's profile must hold the group `media-phone` (runtime/ops_actor.py
guard). The link is read by runtime/cloud_fetch.py `file_id` (Google Drive only). The bound is the least of the media store's 1 GiB and the quota left, and it
is known before a byte is kept. With the project's Google account connected, the file is read through the documents provider (at most 256 MiB, held in
memory by that provider) into a folder made for it, which is removed whatever happens; otherwise the shared link is fetched by runtime/cloud_fetch.py over
https from its closed list of hosts, and the bytes go straight into the media store. The answer never holds the link, the file id or a path.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import attachments as att  # noqa: E402
import cloud_fetch  # noqa: E402
import media  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media  # noqa: E402
import ops_media_phone as phone  # noqa: E402
import project_config  # noqa: E402
import sources  # noqa: E402

OP = "video-phone-fetch"
ACCOUNT_MAX = 256 << 20            # the documents provider's own hard maximum: it holds the file in memory
NO_LINK = "send a Google Drive link to the file (drive.google.com/file/d/...)"


def _refused(code: str) -> "core.OpsError":
    return core.OpsError("refused: " + code, 1)


def _kept(record: dict, route: str) -> dict:
    return {"media": record["id"], "size": record["raw"]["size"], "type": record["raw"]["type"], "route": route}


def _by_account(cfg: dict, fid: str, cap: int) -> dict:
    """The file through the project's Google account: the documents provider writes it into a folder made for it, the store takes it from there."""
    data_dir = cfg["data_dir"]
    try:
        token, folder = att.make_incoming(data_dir)
    except att.FolderError:
        raise core.OpsError("the folder of a fetch could not be made", 1) from None
    try:
        flags = ["--id", fid, "--as-source", "--out-dir", folder, "--max-bytes", str(max(1, min(cap, ACCOUNT_MAX)))]
        try:
            out = sources.drive_call(cfg, "read", flags)
        except sources.SourcesError:
            raise _refused("account") from None
        if out.get("file") != att.CONTENT:
            raise _refused("account")
        try:
            record = media.receive_file(data_dir, os.path.join(folder, att.CONTENT))
        except media.MediaError as e:
            raise ops_media._media_error(e) from None
        except OSError:
            raise core.OpsError("the file could not be read; nothing was kept", 1) from None
        return _kept(record, "account")
    finally:
        att.remove_incoming(data_dir, token)


def _by_link(cfg: dict, fid: str, cap: int) -> dict:
    """The file from the shared link: fetched over https from the closed host list, into the store."""
    data_dir = cfg["data_dir"]
    try:
        record = cloud_fetch.fetch(cloud_fetch.download_url(fid), lambda stream, length: media.receive(data_dir, stream, length), cap)
    except cloud_fetch.CloudError as e:
        raise _refused(e.code) from None
    except media.MediaError as e:
        raise ops_media._media_error(e) from None
    except OSError:
        raise core.OpsError("the download ended before its declared length; nothing was kept", 1) from None
    return _kept(record, "link")


def video_phone_fetch(project: str, text, channel=None, sender=None) -> dict:
    """Fetch the recording the Google Drive link in `text` names and keep it in the media store. Returns {"media", "size", "type", "route"} where `route` is
    "account" (the project's Google account) or "link" (the shared link); never the link, the file id or a path. core.OpsError: code 2 when `text` holds no
    Drive link; "refused: <code>" (code 1) for a refusal of the fetch (the codes of runtime/cloud_fetch.py CODES, and `account` for the provider's); the store's own
    refusals as runtime/ops_media.py maps them."""
    ctx = phone._checked(project, OP, channel, sender)
    cfg = ctx["cfg"]
    fid = cloud_fetch.file_id(text)
    if fid is None:
        raise core.OpsError(NO_LINK, 2)
    cap = min(media.MEDIA_MAX_BYTES, phone._free_bytes(cfg))
    if cap < 1:
        raise _refused("too_large")
    if project_config.account_entry(cfg, "google") is not None:
        return _by_account(cfg, fid, cap)
    return _by_link(cfg, fid, cap)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
