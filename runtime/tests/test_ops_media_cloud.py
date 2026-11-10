"""Tests of the operation of a recording from a Google Drive link (runtime/ops_media_cloud.py, package V1d-3, limit L70): the channel and the group first, a text
with no Drive link, the shared link's route and the connected account's route (each with a fake in place of the socket and of the provider), the bound, the refusals
and what is never in an answer. The store of recordings is the real one; every name and id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_media_cloud.py
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from media_fixtures import body_of, mp4_head, png_head
from media_kit import media, ops_core, world  # noqa: F401
import standin_tree as st
from test_ops_media_phone import IDENT, OTHER, SENDER, STRANGER, configure, refused

ops_media_cloud = st.load("ops_media_cloud")
cloud_fetch = st.load("cloud_fetch")
sources = st.load("sources")
project_config = st.load("project_config")
attachments = st.load("attachments")
FID = "FAKEfileID0123456789"
LINK = f"here it is https://drive.google.com/file/d/{FID}/view?usp=sharing"
MP4 = body_of(mp4_head(), 64)


def kit(world):
    configure(world)
    return world["path"]


def call(path, text=LINK, sender=SENDER, channel="messaging"):
    return ops_media_cloud.video_phone_fetch(path, text, channel=channel, sender=sender)


def recordings(world) -> int:
    return len(media.records(world["data"]))


def link_fetch(monkeypatch, data=MP4, seen=None):
    """A fake `cloud_fetch.fetch` that feeds the bytes to `receive` as the socket would, and records what it was asked."""
    def fake(url, receive, cap, **seams):
        if seen is not None:
            seen.append((url, cap, seams))
        return receive(io.BytesIO(data), len(data))
    monkeypatch.setattr(cloud_fetch, "fetch", fake)


def with_account(monkeypatch, entry=None):
    entry = {"address": "ana@mail.example"} if entry is None else entry
    monkeypatch.setattr(project_config, "account_entry", lambda cfg, account: entry if account == "google" else None)


# 1. the channel, then the group


def test_limit_70_the_call_is_the_bridges_and_needs_the_group(world, monkeypatch):
    path = kit(world)
    link_fetch(monkeypatch)
    before = recordings(world)
    for channel in (None, "terminal", "page", "mcp"):
        err = refused(call, path, channel=channel)
        assert err.code == 1 and "messaging bridge's call" in str(err), (channel, str(err))
    err = refused(call, path, sender=STRANGER)             # a sender whose profile lacks the group: the guard's own sentence
    assert err.code == 1 and "messaging bridge's call" not in str(err) and str(err)
    err = refused(call, path, sender=None)
    assert err.code == 1
    assert recordings(world) == before, "nothing was fetched or kept"


def test_nothing_is_fetched_before_the_guard_answers(world, monkeypatch):
    path = kit(world)
    seen = []
    link_fetch(monkeypatch, seen=seen)
    refused(call, path, sender=STRANGER)
    refused(call, path, channel="page")
    assert seen == []


# 2. the text


def test_a_text_with_no_drive_link_is_code_2_and_fetches_nothing(world, monkeypatch):
    path = kit(world)
    seen = []
    link_fetch(monkeypatch, seen=seen)
    for text in ("no link", "https://evil.example/file/d/" + FID, "http://drive.google.com/file/d/" + FID + "/view", "", None, 5):
        err = refused(call, path, text)
        assert err.code == 2 and "drive.google.com/file/d/" in str(err), text
    assert seen == [] and recordings(world) == 1


# 3. the shared link


def test_without_an_account_the_shared_link_is_fetched_and_kept(world, monkeypatch):
    path = kit(world)
    seen = []
    link_fetch(monkeypatch, seen=seen)
    got = call(path)
    assert set(got) == {"media", "size", "type", "route"} and got["route"] == "link" and got["size"] == 64 and got["type"] == "mp4"
    assert media.ID.fullmatch(got["media"]) and media.load(world["data"], got["media"])["raw"]["size"] == 64
    [(url, cap, seams)] = seen
    assert url == cloud_fetch.download_url(FID) and seams == {}, "the real socket seams, not a test's"
    assert cap == media.MEDIA_MAX_BYTES
    assert FID not in repr(got) and "drive.google.com" not in repr(got) and str(world["tmp"]) not in repr(got), "never the link, the id or a path"


def test_the_cap_is_the_least_of_the_store_and_the_quota_left(world, monkeypatch):
    path = kit(world)
    seen = []
    link_fetch(monkeypatch, seen=seen)
    call(path)
    assert seen[-1][1] == media.MEDIA_MAX_BYTES
    monkeypatch.setattr(media, "QUOTA_BYTES", media.usage(world["data"]) + 1000)
    call(path)
    assert seen[-1][1] == 1000
    monkeypatch.setattr(media, "QUOTA_BYTES", media.usage(world["data"]))
    before = recordings(world)
    err = refused(call, path)
    assert err.code == 1 and str(err) == "refused: too_large" and len(seen) == 2 and recordings(world) == before


def test_a_cloud_error_becomes_a_refusal_with_its_code_and_nothing_is_kept(world, monkeypatch):
    path = kit(world)
    before = recordings(world)
    for code in cloud_fetch.CODES:
        def fake(url, receive, cap, _code=code, **seams):
            raise cloud_fetch.CloudError(_code)
        monkeypatch.setattr(cloud_fetch, "fetch", fake)
        err = refused(call, path)
        assert err.code == 1 and str(err) == f"refused: {code}", code
    assert recordings(world) == before


def test_the_stores_refusals_are_mapped_as_the_page_upload_maps_them(world, monkeypatch):
    path = kit(world)
    before = recordings(world)
    link_fetch(monkeypatch, body_of(png_head(), 64))
    err = refused(call, path)
    assert err.code == 2 and str(err).endswith("(type)")
    def short(url, receive, cap, **seams):
        return receive(io.BytesIO(MP4[:10]), 64)                 # the stream ends before its declared length
    monkeypatch.setattr(cloud_fetch, "fetch", short)
    err = refused(call, path)
    assert err.code == 2 and str(err).endswith("(size)")
    def reset(url, receive, cap, **seams):
        raise ConnectionResetError("reset")
    monkeypatch.setattr(cloud_fetch, "fetch", reset)
    assert "nothing was kept" in str(refused(call, path))
    assert recordings(world) == before


# 4. the connected account


def test_with_an_account_the_documents_provider_reads_the_file_and_the_incoming_folder_is_gone(world, monkeypatch):
    path = kit(world)
    with_account(monkeypatch)
    asked, seen = [], []

    def drive(cfg, verb, args, **kw):
        asked.append((verb, list(args)))
        folder = args[args.index("--out-dir") + 1]
        seen.append(folder)
        Path(folder, "content").write_bytes(MP4)
        return {"id": FID, "name": "take.mp4", "mime_type": "video/mp4", "content": "file", "exported_as": None, "bytes": 64, "file": "content", "as_source": True}
    monkeypatch.setattr(sources, "drive_call", drive)
    monkeypatch.setattr(cloud_fetch, "fetch", lambda *a, **k: pytest.fail("the shared link must not be fetched with an account"))
    got = call(path)
    assert got["route"] == "account" and got["size"] == 64 and got["type"] == "mp4" and media.load(world["data"], got["media"])["raw"]["size"] == 64
    [(verb, args)] = asked
    assert verb == "read" and args[:3] == ["--id", FID, "--as-source"] and args[3] == "--out-dir"
    assert args[-2:] == ["--max-bytes", str(256 << 20)]
    assert not os.path.exists(seen[0]), "the incoming folder is removed"
    assert FID not in repr(got) and str(world["tmp"]) not in repr(got)


def test_the_accounts_bound_is_at_most_256_mib_and_at_least_the_quota_left(world, monkeypatch):
    path = kit(world)
    with_account(monkeypatch)
    limits = []

    def drive(cfg, verb, args, **kw):
        limits.append(int(args[args.index("--max-bytes") + 1]))
        Path(args[args.index("--out-dir") + 1], "content").write_bytes(MP4)
        return {"file": "content"}
    monkeypatch.setattr(sources, "drive_call", drive)
    call(path)
    assert limits[-1] == 256 << 20
    monkeypatch.setattr(media, "QUOTA_BYTES", media.usage(world["data"]) + 5000)
    call(path)
    assert limits[-1] == 5000


def test_a_provider_failure_or_an_unexpected_answer_is_refused_account_and_the_folder_is_gone(world, monkeypatch):
    path = kit(world)
    with_account(monkeypatch)
    folders = []

    def failing(cfg, verb, args, **kw):
        folders.append(args[args.index("--out-dir") + 1])
        raise sources.SourcesError("the Drive file could not be read (forbidden): " + FID, "drive")
    monkeypatch.setattr(sources, "drive_call", failing)
    err = refused(call, path)
    assert err.code == 1 and str(err) == "refused: account" and FID not in str(err)

    def odd(cfg, verb, args, **kw):
        folders.append(args[args.index("--out-dir") + 1])
        return {"file": "elsewhere"}
    monkeypatch.setattr(sources, "drive_call", odd)
    assert str(refused(call, path)) == "refused: account"
    assert not any(os.path.exists(f) for f in folders) and recordings(world) == 1


def test_an_account_file_the_store_refuses_is_told_and_the_folder_is_gone(world, monkeypatch):
    path = kit(world)
    with_account(monkeypatch)
    folders = []

    def drive(cfg, verb, args, **kw):
        folder = args[args.index("--out-dir") + 1]
        folders.append(folder)
        Path(folder, "content").write_bytes(body_of(png_head(), 64))
        return {"file": "content"}
    monkeypatch.setattr(sources, "drive_call", drive)
    err = refused(call, path)
    assert err.code == 2 and str(err).endswith("(type)") and not os.path.exists(folders[0]) and recordings(world) == 1


def test_a_project_with_no_google_account_uses_the_link(world, monkeypatch):
    path = kit(world)
    with_account(monkeypatch, entry=None)
    monkeypatch.setattr(project_config, "account_entry", lambda cfg, account: None)
    monkeypatch.setattr(sources, "drive_call", lambda *a, **k: pytest.fail("no account: the provider is not asked"))
    link_fetch(monkeypatch)
    assert call(path)["route"] == "link"


def test_the_module_starts_on_its_own():
    flags = ["--help"]
    done = subprocess.run([sys.executable, "-I", str(st.RUNTIME / "ops_media_cloud.py"), *flags], capture_output=True, text=True, timeout=60, env={})
    assert done.returncode == 0 and "media-phone" in done.stdout
    other = ["--nope"]
    assert subprocess.run([sys.executable, "-I", str(st.RUNTIME / "ops_media_cloud.py"), *other], capture_output=True, text=True, timeout=60, env={}).returncode == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
