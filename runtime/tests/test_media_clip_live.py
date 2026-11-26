"""A clip through the runtime and the renderer engine, in the real containers (package V9b-5c, live leg L1). Synthetic only, no network, no model, no real recording:
three counter clips made by the host's ffmpeg (2.5 s and 12 s at 1080x1920, 6 s at 1920x1080) go through the runtime's `fetch-picks` (a fake source copies the clip into
`full-*`; the renderer's own `asset-sheet` in the common image normalises it) and the approval, `step_media.fit_clip_entries` ends the cutaway of the contract lab's
recording with its clip, and the host's `render` draws it with the runtime's `.mp4` and its sha256.

Skipped unless both variables are set (the ones of providers/renderer/tests/test_engine_contract_live.py, whose lab and helpers this file reuses):

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 \\
    uv run --with pytest==9.1.1 pytest -q runtime/tests/test_media_clip_live.py

with no `-n`, after the image is built and recorded. If the runtime's engine call cannot reach the built images from here, stop and report (stop rule 9).
Asserted: the render is verified; for the cover clips, output frame `start + k` reads clip frame `k` for every `k` of the entry; a clip shorter than its
beat ends the entry at least two frames before the clip does, and the next frame does not read a clip frame; a clip longer than the beat leaves the beat as its words end it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import ops, step_media, world  # noqa: F401  (the fixture)
from media_stock_kit import LIBRARY, media_stock, ops_media_stock, pick, review_of, to_found

REPO = st.REPO
REAL_STATE = os.environ.get("OPENHORA_STATE_DIR")      # read at import: a fixture of the runtime tests points the variable at a temporary folder before each test
ENABLED = all(os.environ.get(v) for v in ("WB_RENDERER_DOCKER_TESTS", "OPENHORA_STATE_DIR"))
pytestmark = pytest.mark.skipif(not ENABLED, reason="real containers: set WB_RENDERER_DOCKER_TESTS=1 and OPENHORA_STATE_DIR (the image built and recorded first)")
CLIPS = {"short": (1080, 1920, 75), "long": (1080, 1920, 360), "glass": (1920, 1080, 180)}      # 2.5 s, 12 s and 6 s at 30 fps
SLOT = "beat2"


def put_renderer_on_path():
    for one in (REPO / "providers" / "renderer" / "tests", REPO / "providers" / "renderer"):
        if str(one) not in sys.path:
            sys.path.insert(0, str(one))


def render_with_hash(live, lab, engine, tag, rec, edl, beats, clip, digest):
    """The host's `render` the way `Lab.render` runs it, with `--asset-sha256` as the runtime passes it."""
    import renderer_kit as K
    lab.need(engine)
    env = dict(os.environ)
    out_dir = lab.folder / ("out-" + tag)
    args = ["render", "--edl", edl, "--beats", beats, "--in", rec, "--out", out_dir, "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY, "--cpus", 4, "--cpuset", "0-3",
            "--asset", "%s=%s" % (SLOT, clip), "--asset-sha256", "%s=%s" % (SLOT, digest)]
    args += ["--jobs", 2]
    rc, out, err = live.host(engine, *args, timeout=3600, env=env)
    assert rc == 0 and out["verified"] is True, (engine, tag, out, err[-2000:])
    live.assert_clean(out_dir, passed=True)
    return out


def through_the_runtime(world, monkeypatch, raw: Path):
    """The runtime's own path for one clip: found, picked, fetched by the fake source (which copies `raw`), normalised by the real renderer, approved. Returns the approved asset and its file."""
    found = to_found(world, monkeypatch, {"beat7": ("market stall", "clip")}, stock=["fakelib"], extra={"fakelib": LIBRARY})
    monkeypatch.setattr(ops_media_stock, "_engine_of", lambda ctx: ops_media_stock.SheetEngine(str(REPO), None))      # the real `asset-sheet`, not the kit's fake
    original = found["sources"]._fetch

    def fetch(source, flags):
        answer = original(source, flags)
        out, name = flags[flags.index("--out") + 1], "full-%s-%s-clip.mp4" % (source, answer["item"])
        data = raw.read_bytes()
        Path(out, name).write_bytes(data)
        os.remove(os.path.join(out, answer["file"]))
        import hashlib
        return dict(answer, file=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    found["sources"]._fetch = fetch
    data, rid = world["data"], world["rid"]
    beats = json.loads(ops_media_stock.media.read_work(data, rid, "proposal.beats.json", 1 << 20))
    beats["layouts"] = [{"id": "b7", "beat": 7, "preset": "cutaway", "block": "oh:cutaway", "params": {"asset": "beat7"}, "word_from": 0, "word_to": 3}]
    ops_media_stock.media.write_work(data, rid, "proposal.beats.json", json.dumps(beats).encode("utf-8"))
    edl = json.loads(ops_media_stock.media.read_work(data, rid, "proposal.edl.json", 1 << 20))
    ops_media_stock.media.write_work(data, rid, "proposal.edl.json", json.dumps(dict(edl, fps=30)).encode("utf-8"))
    done = ops.video_media_find(world["path"], found["task"], confirm=True)
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    ops.video_media_fetch_picks(world["path"], found["task"])
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    [asset] = shown["set"]["assets"]
    return asset, Path(media_stock.folder_of(data, rid)) / media_stock.asset_name(asset)


@pytest.mark.parametrize("shape", sorted(CLIPS))
def test_a_clip_through_the_runtime_is_drawn_and_ends_with_its_clip(shape, world, monkeypatch, tmp_path):
    monkeypatch.setenv("OPENHORA_STATE_DIR", REAL_STATE)      # the images and recordings the builds made live in the person's state folder
    put_renderer_on_path()
    import clip_kit as CK
    import _edl
    import renderer_kit as K
    from _vocab import load_data, load_vocabulary
    import test_engine_contract_live as live
    w, h, frames = CLIPS[shape]
    raw = Path(CK.counter_clip(tmp_path / ("raw-%s.mp4" % shape), w, h, frames))
    asset, clip = through_the_runtime(world, monkeypatch, raw)
    assert asset["kind"] == "clip" and 0 < asset["seconds"] <= 10.0 and clip.is_file()
    lab = live.Lab(tmp_path / "lab")
    transcript = K.build_transcript(live.CUTAWAY_SENTENCES)
    rec = lab.recording("cutaway", transcript)
    edl_file, beats_file, doc = lab.documents("cutaway", rec, transcript, live.CUTAWAY_POST)
    beats = json.loads(Path(beats_file).read_text())
    clip_frames = int(round(min(asset["seconds"], 10.0) * doc["fps"]))
    before = _edl.resolve_timeline(doc, json.loads(json.dumps(beats)), load_vocabulary(str(K.VOCABULARY)), load_data())
    long_before = next(e for e in before["beats"] if e["preset"] == "cutaway")
    shortened = step_media.fit_clip_entries(beats, doc, {SLOT: asset["seconds"]})
    assert bool(shortened) == (long_before["end_frame"] - long_before["start_frame"] > clip_frames - step_media.CLIP_SPARE_FRAMES)
    fitted = tmp_path / ("beats-%s.json" % shape)
    fitted.write_text(json.dumps(beats))
    timeline = _edl.resolve_timeline(doc, beats, load_vocabulary(str(K.VOCABULARY)), load_data())
    entry = next(e for e in timeline["beats"] if e["preset"] == "cutaway")
    count = entry["end_frame"] - entry["start_frame"]
    assert count <= clip_frames - 1
    engine = "ffmpeg"
    out = render_with_hash(live, lab, engine, "%s-%s" % (shape, engine), rec, edl_file, fitted, clip, asset["sha256"])
    if shape == "glass":      # drawn whole inside the frame over a blurred copy: the counter is not at 1:1, so only the verified render and the entry's length are checked here
        return
    numbers = live.counter_numbers(out["path"], entry["start_frame"], count)
    assert numbers == list(range(count)), "%s: a frame reads the wrong clip frame: %s" % (engine, [(k, n) for k, n in enumerate(numbers) if n != k][:12])
    if shortened:      # the entry ended before its clip: the next frame is the speaker's, not a clip frame (a held or continued clip would read `count`)
        assert count <= clip_frames - step_media.CLIP_SPARE_FRAMES
        assert live.counter_numbers(out["path"], entry["end_frame"], 1)[0] != count
