"""A rendered video for the tests of the video routes and operations (runtime/video.py, runtime/ops_video.py): a recording of the
media store with a post file, a render written the way the renderer writes it (`render-<sha12>.mp4`, mode 0400, its name the first 12
hex characters of its sha256), the pipeline's `render.json` and a cover PNG. The bytes are an MP4 header and pseudo-random padding,
no encoder, so these tests need no ffmpeg. Every name is invented. Not a test file.
"""
from __future__ import annotations

import hashlib
import json
import os
import types

import pytest

import standin_tree as st
from media_fixtures import png
from test_service import PORT, TOKEN

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
service = st.load("service")
media = st.load("media")
video = st.load("video")

POST = "docs/marketing/content/2026-10-14-demo-reel.md"
CAPTION = "Three habits that made our mornings easier.\n\nSave this for Monday.\n#northwind #mornings"
LAN = "192.168.1.20"


def mp4_bytes(seed: str, size: int = 300_000) -> bytes:
    """A file that sniffs as an MP4 (an ftyp box with the brand mp42) and is `size` bytes of deterministic padding after it."""
    head = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    out = bytearray(head)
    block = hashlib.sha256(seed.encode()).digest()
    while len(out) < size:
        block = hashlib.sha256(block).digest()
        out += block
    return bytes(out[:size])


def post_text(caption: str = CAPTION) -> str:
    return ("# Reel: three habits\n\n- Network: instagram\n- Format: reel\n- Slot: 2026-10-14T10:00:00-03:00\n- Approval: plan\n\n"
            f"```script\nBeat one. Beat two.\n```\n\n```post\n{caption}\n```\n")


def write_render(data: str, rid: str, seed: str = "one", size: int = 300_000, result: bool = True, cover: bool = True) -> dict:
    """Write one render of the recording (and, by default, the pipeline's render.json and the cover); returns its facts."""
    folder = media.folder_of(data, rid)
    payload = mp4_bytes(seed, size)
    sha = hashlib.sha256(payload).hexdigest()
    path = os.path.join(folder, f"render-{sha[:12]}.mp4")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
    facts = {"sha": sha, "bytes": payload, "path": path, "cover": None}
    cover_bytes = png(9, 16)
    cover_sha = hashlib.sha256(cover_bytes).hexdigest()
    if cover:
        with open(os.path.join(folder, f"cover-{sha[:12]}.png"), "wb") as f:
            f.write(cover_bytes)
        facts["cover"] = cover_bytes
    if result:
        doc = {"ok": True, "sha256": sha, "bytes": len(payload), "out_seconds": 41.5,
               "output": {"container": "mp4", "codec": "h264", "width": 1080, "height": 1920, "fps": 30, "duration": 41.5,
                          "bytes": len(payload), "audio_codec": "aac"},
               "cover": {"offset_ms": 1200, "sha256": cover_sha}, "path": "/somewhere/else/render.mp4"}
        with open(os.path.join(folder, "render.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f)
    return facts


def write_post(project: str, caption: str = CAPTION) -> None:
    path = os.path.join(project, POST)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(post_text(caption))


def caption_sha(caption: str = CAPTION) -> str:
    return hashlib.sha256(caption.encode("utf-8")).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    projects = [{"id": service.project_id(project), "name": "p", "path": project}]
    svc = service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None)
    data = str(built["data"])
    write_post(project)
    record = media.create(data, posts={"instagram": POST})
    rid = record["id"]
    return types.SimpleNamespace(svc=svc, project=project, pid=projects[0]["id"], data=data, rid=rid, tmp=tmp_path,
                                 folder=media.folder_of(data, rid))


def headers(*, host=f"127.0.0.1:{PORT}", origin="default", token=True, **extra):
    out = {"Host": host}
    if origin == "default":
        out["Origin"] = f"http://{host}"
    elif origin is not None:
        out["Origin"] = origin
    if token is True:
        out["Authorization"] = f"Bearer {TOKEN}"
    elif token:
        out["Authorization"] = f"Bearer {token}"
    out.update({k.replace("_", "-"): v for k, v in extra.items() if v is not None})
    return out
