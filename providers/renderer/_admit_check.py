"""The determinism test of an admitted block (PF-a3, inside the container): what `admit-check` measures and the comparator that judges it.

A block of the second contract draws with the HyperFrames runtime, which reads clocks and timers by design (the virtual-time shim replaces them), so
the text lint of the first contract cannot vouch for it. What vouches is a test: for each sample of the entry, the block is drawn four times at
1080x1920 and the preset's fps, each time in a fresh browser (a fresh profile), and the sha256 of every frame of the beat is listed:

  - three runs seek forward, as a render does (several pages, each starting where its share of the frames starts);
  - one run seeks the last frame first, one page, every frame after the one that follows it in time.

The four lists must be identical. No request may have been blocked, no page exception thrown and no policy violation reported (the frame loop refuses
on any of them, with its own code, so a run that returns had none), at least one frame is drawn, and the exact gates of the second contract (the alpha
face gate and the caption-line gate) and the font check pass on the frames of the first run.

`compare_runs` is the pure judge over the four lists. `admit_check` runs the measurement. A page that draws from `Math.random` or from a clock the shim
does not replace gives frames that differ from run to run: the comparator refuses it with `determinism_failed` and the first frame that differs.

The record this returns is a fact about one pair of served files and one runtime (its hash covers GSAP, the runtime, the five shims as served, the
host's version and the browser's version string): a change of any of them leaves the block unproven until it is tested again. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time

import _blocks
import _cdp
import _edl
import _frames
import _hf_host
import _preview
import _render
from _text import Refusal
from _vocab import load_data, load_vocabulary

HEX64 = re.compile(r"[0-9a-f]{64}")
FORWARD_RUNS = 3
LINE = "pop the one word"            # the words of the synthetic beat: four words, spoken at the storyboard's rate
PROBE_NAME = "hf:admit-probe"


# ---------------------------------------------------------------- the comparator

def _lists(forward, reverse):
    if not isinstance(forward, (list, tuple)) or len(forward) != FORWARD_RUNS or not isinstance(reverse, (list, tuple)):
        raise Refusal("determinism_failed", "runs")
    runs = list(forward) + [reverse]
    for run in runs:
        if not isinstance(run, (list, tuple)) or not all(isinstance(h, str) and HEX64.fullmatch(h) for h in run):
            raise Refusal("determinism_failed", "runs")
    return runs


def compare_runs(forward, reverse, blocked: int = 0, exceptions: int = 0, csp: int = 0) -> int:
    """Judge the four lists of per-frame sha256 of one sample: `forward` is three lists, `reverse` the run that sought the last frame first, given in
    FRAME order (frame 0 first), like the others. Returns the number of frames. Refusals, with a closed code and a field:
    `blocked_request` (a request was blocked, or the page policy was violated), `block_failed` (the page threw), and `determinism_failed` with the
    field `runs` (not three forward lists and one reverse list of sha256 values), `frames` (no frame, or lists of different lengths) or `frame N`
    (the first frame, counted from the beat's start, where any list differs from the first run's)."""
    if blocked or csp:
        raise Refusal("blocked_request", "runs")
    if exceptions:
        raise Refusal("block_failed", "runs")
    runs = _lists(forward, reverse)
    count = len(runs[0])
    if count == 0 or any(len(r) != count for r in runs):
        raise Refusal("determinism_failed", "frames")
    for k in range(count):
        if any(r[k] != runs[0][k] for r in runs[1:]):
            raise Refusal("determinism_failed", "frame %d" % k)
    return count


# ---------------------------------------------------------------- the measurement

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def probe_blocks(blocks_src: str, blocks_sha256, scratch: str, entry: dict, runtime_sha256: str) -> tuple:
    """A copy of the staged blocks in `scratch` with the candidate entry as the one allowlist entry, under a name no block holds (the port of the same
    name is still there), the ffmpeg engine drawing the entry's preset with it, and a provisional determinism record at the real hashes (so that the
    render's own proof check passes: the measurement is what the real record will say). Returns (blocks folder, catalogue)."""
    _blocks.load_catalogue(blocks_src, blocks_sha256)           # the staged folder is the one the host pinned
    folder = os.path.join(scratch, "blocks")
    shutil.copytree(blocks_src, folder)
    probe = json.loads(json.dumps(entry))
    probe["name"] = PROBE_NAME
    probe["determinism"] = {"served_sha256": entry["served_sha256"], "runtime_sha256": runtime_sha256, "samples": 1, "frames": 1, "runs": 4, "blocked": 0,
                            "date": "2000-01-01", "image": "probe", "seconds": 0}
    allow_path = os.path.join(folder, "hf", "allowlist.json")
    with open(allow_path, encoding="utf-8") as fh:
        allow = json.load(fh)
    allow.update(registry_commit=entry["commit"], blocks=[probe])
    with open(allow_path, "w", encoding="utf-8") as fh:
        json.dump(allow, fh, indent=1)
    engine_path = os.path.join(folder, "engines", "ffmpeg.json")
    with open(engine_path, encoding="utf-8") as fh:
        engine = json.load(fh)
    engine["presets"][entry["preset"]] = PROBE_NAME
    with open(engine_path, "w", encoding="utf-8") as fh:
        json.dump(engine, fh, indent=1)
    _blocks.write_pins(folder)
    return folder, _blocks.load_catalogue(folder)


def stage_registry(entry: dict, component_dir: str, scratch: str) -> str:
    """The component's files, copied to where the render looks for them (`<registry>/<component>/<name>`): each file is read once, and the host
    page reads them again by the hashes the entry pins."""
    registry = os.path.join(scratch, "registry")
    target = os.path.join(registry, entry["component"])
    os.makedirs(target)
    for name in sorted(entry["files"]):
        with open(os.path.join(component_dir, name), "rb") as fh:
            raw = fh.read((1 << 20) + 1)
        if len(raw) > 1 << 20:
            raise Refusal("block_hash", ("hf:%s" % name)[:80])
        with open(os.path.join(target, name), "wb") as out:
            out.write(raw)
    return registry


def sample_state(entry: dict, sample: dict, catalogue: dict, data: dict, vocab: dict, allow: dict, vendor, registry: str, browser: str) -> dict:
    """One sample set up as a render would set it: the synthetic beat (the storyboard's words, the default face box and zones) resolved on the
    ffmpeg engine, the page the host builds for it, and the range of frames the beat owns."""
    rows = [_preview.beat_row(vocab, {"preset": entry["preset"], "params": sample, "line": LINE})]
    edl, beats, _notes, _transcript, _mentions = _preview.build_lists(rows, data, vocab, allow)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    if len(timeline["beats"]) != 1:
        raise Refusal("admit_unmeasurable", "beats")
    timeline["captions"] = []
    templates, _names = _blocks.templates_for(catalogue, _render.ENGINE, timeline, vocab, with_caption=False)
    font_serve, _used = _frames.load_fonts(edl["theme"]["fonts"], allow, data["limits"]["font_max_bytes"])
    admitted = _render.admit_blocks(catalogue, timeline, data, edl, font_serve, vendor, registry, browser)
    if not admitted["pages"]:
        raise Refusal("admit_unmeasurable", "pages")
    beat = timeline["beats"][0]
    serve = dict(font_serve)
    serve.update(admitted["serve"])
    return {"edl": edl, "timeline": timeline, "templates": templates, "font_urls": _render.font_urls_of(data, edl, font_serve), "admitted": admitted,
            "serve": serve, "start": beat["start_frame"], "end": min(beat["end_frame"], edl["out_frames"])}


def draw_once(state: dict, data: dict, browser: str, scratch: str, jobs: int, reverse: bool, limit: int) -> tuple:
    """One run in a fresh browser (its own profile folder): (the list of per-frame sha256 of the beat in frame order, the frames folder)."""
    work = tempfile.mkdtemp(prefix=".run-", dir=scratch)
    frames_dir = os.path.join(work, "frames")
    _frames.draw_frames(data=data, edl=state["edl"], timeline=state["timeline"], serve=state["serve"], theme_fonts_urls=state["font_urls"], assets={},
                        browser=browser, jobs_n=1 if reverse else max(1, jobs), frames_dir=frames_dir, workdir=work, time_limit=limit, templates=state["templates"],
                        png_blank=_render.blank_png, admitted=state["admitted"], reverse=reverse)
    hashes = [_sha256_file(os.path.join(frames_dir, "beat_%06d.png" % f)) for f in range(state["start"], state["end"])]
    return hashes, work


def admit_check(*, entry: dict, component_dir: str, vocabulary: str, blocks: str, blocks_sha256, scratch: str, browser: str, ffmpeg: str, vendor=None,
                jobs: int = 3, time_limit: int = 900, shims_dir=None) -> dict:
    """The whole measurement of one candidate entry (every sample, four runs each, the gates on the first run of each). Returns
    {served_sha256, runtime_sha256, samples, frames (summed over the samples, one run), runs 4, blocked 0, seconds, browser, per_sample [{frames, digest}]};
    refuses with the code of whatever failed (see `compare_runs`, `_frames.draw_frames` and the gates)."""
    started = time.time()
    data = load_data()
    vocab = load_vocabulary(vocabulary)
    allow = _frames.font_allowlist()
    here = os.path.dirname(os.path.abspath(__file__))
    version = _cdp.browser_version(browser)
    registry = stage_registry(entry, component_dir, scratch)
    shims = shims_dir or os.path.join(_hf_host.runtime_dir(here), "shims")
    vendor_dir = vendor or os.path.join(here, "vendor")
    fps = data["frame"]["fps"]
    runtime_sha256 = _hf_host.load_runtime(vendor_dir, shims, fps, version)["runtime_sha256"]
    _folder, catalogue = probe_blocks(blocks, blocks_sha256, scratch, entry, runtime_sha256)
    per_sample, total = [], 0
    for index, sample in enumerate(entry["samples"]):
        state = sample_state(entry, sample, catalogue, data, vocab, allow, vendor_dir, registry, browser)
        runs, gated = [], False
        for _ in range(FORWARD_RUNS):
            hashes, work = draw_once(state, data, browser, scratch, jobs, False, time_limit)
            if not gated:
                _render.check_admitted_layer(data, state["edl"], state["timeline"], state["admitted"], os.path.join(work, "frames"), ffmpeg)
                gated = True
            shutil.rmtree(work, ignore_errors=True)
            runs.append(hashes)
        reverse, work = draw_once(state, data, browser, scratch, 1, True, time_limit)
        shutil.rmtree(work, ignore_errors=True)
        try:
            count = compare_runs(runs, reverse)
        except Refusal as err:
            if err.code == "determinism_failed":
                err.field = ("sample %d %s" % (index + 1, err.field))[:80]
            raise
        total += count
        per_sample.append({"frames": count, "digest": hashlib.sha256("\n".join(runs[0]).encode("ascii")).hexdigest()})
    return {"ok": True, "served_sha256": entry["served_sha256"], "runtime_sha256": runtime_sha256, "samples": len(entry["samples"]), "frames": total,
            "runs": 4, "blocked": 0, "seconds": round(time.time() - started, 2), "browser": version, "per_sample": per_sample}
