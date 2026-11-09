"""The kit of the engine contract (V3c): the synthetic inputs both renderer engines are tested with, the closed schema of the report the
Mac legs write, the memory sampler and the helpers that say where two outputs differ. Everything is invented: the words are the kit's
fictional ones (renderer_kit), the recordings are test patterns that the common image's own ffmpeg makes (`source_args`), nothing is
downloaded and no real recording is touched.

Not a test file. Standard library only. The functions that need a container take the runner of one ffmpeg command as an argument
(`run(args, folder)`), so the live file passes its `in_image` and the offline tests pass the host's ffmpeg.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import renderer_kit as K
import _blocks
import _edl
import _media
import _retakes
from _vocab import load_data

# ---------------------------------------------------------------- the frame band (5.2)

BAND_BITS = 14                                  # 14 cells: frame numbers up to 16383, above the 9000 frames of the longest input
CELL = 72                                       # pixels per cell
BAND_W, BAND_H = BAND_BITS * CELL, 96           # 1008 x 96 at (0, 0), above `zones.card_top` (110): no card covers it
ONE = 128                                       # a read byte of 128 or more is a 1


def band_cells(index: int) -> list:
    """The 14 cell values (0 or 255) that draw frame number `index`, least significant bit on the left."""
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < 1 << BAND_BITS:
        raise ValueError("a frame number the band cannot hold")
    return [255 if (index >> b) & 1 else 0 for b in range(BAND_BITS)]


def band_index(cells) -> int:
    """The frame number 14 read bytes (or values) stand for."""
    if len(cells) != BAND_BITS:
        raise ValueError("a band has %d cells" % BAND_BITS)
    return sum(1 << b for b, v in enumerate(cells) if v >= ONE)


def read_band(raw: bytes) -> list:
    """The frame number of every frame in `raw`, 14 bytes per frame (what `band_read_args` writes)."""
    if len(raw) % BAND_BITS:
        raise ValueError("the band file is not a whole number of frames")
    return [band_index(raw[i:i + BAND_BITS]) for i in range(0, len(raw), BAND_BITS)]


def expected_sources(kept) -> list:
    """The source frame every output frame must be, in order, from the kept ranges of an edit list."""
    return [f for a, b in kept for f in range(a, b)]


def band_filter() -> str:
    """The filter graph that draws the band over a test pattern: a 1008x96 gray source made by `geq` from the frame number `N` and the
    pixel column `X`, laid at (0, 0)."""
    return ("[1:v]format=gray,geq=lum='255*mod(floor(N/pow(2,floor(X/%d))),2)',format=yuv420p[band];"
            "[0:v][band]overlay=0:0,format=yuv420p[v]" % CELL)


def tone_terms(transcript: dict) -> list:
    """The tone of `renderer_kit.make_source`: it sounds only while words are spoken, so `analyse` finds silences and `base` cuts ranges."""
    return ["between(t,%.3f,%.3f)*0.3*sin(2*PI*%d*t)" % (a, b, 180 + 35 * (k % 5)) for k, (a, b) in enumerate(K.speech_spans(transcript["words"]))]


def source_args(transcript: dict, out_name: str, rate: int = 30) -> list:
    """The ffmpeg arguments (no program name) that make the recording of `transcript`: 1080x1920 at `rate` fps, the band over the test
    pattern, the gated tone, H.264 and AAC tagged bt709 limited, faststart. `out_name` is the output path as the runner sees it."""
    d = transcript["duration"]
    return ["-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=%d:duration=%.3f" % (rate, d),
            "-f", "lavfi", "-i", "color=c=black:size=%dx%d:rate=%d:duration=%.3f" % (BAND_W, BAND_H, rate, d),
            "-f", "lavfi", "-i", "aevalsrc='%s':s=48000:c=stereo:d=%.3f" % ("+".join(tone_terms(transcript)), d),
            "-filter_complex", band_filter(), "-map", "[v]", "-map", "2:a:0",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "16",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_name]


def band_read_args(in_name: str, out_name: str) -> list:
    """The ffmpeg arguments that write the band of every frame of `in_name` to `out_name`: 14 gray bytes per frame."""
    return ["-y", "-hide_banner", "-loglevel", "error", "-i", in_name, "-an",
            "-vf", "crop=%d:%d:0:0,scale=%d:1:flags=area,format=gray" % (BAND_W, BAND_H, BAND_BITS), "-f", "rawvideo", out_name]


def long_recording_args(out_name: str, seconds: int = 301) -> list:
    """A recording of `seconds` seconds, small (320x568 at 5 fps) and with a tone: only its duration, its hash and its audio matter."""
    return ["-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=320x568:rate=5:duration=%d" % seconds,
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=%d" % seconds,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "30",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
            "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", out_name]


def unzoomed_ranges(edl: dict) -> list:
    """The numbers of the kept ranges the picture is drawn at exactly 1.0 from first frame to last (no zoom, no push-in): the only ranges whose
    frame band is unchanged in the output."""
    fps = edl["fps"]
    return [k for k, (a, b) in enumerate(edl["kept"]) if _media.zoom_levels(edl["zoom"], k, b - a, fps) == (1.0, 1.0)]


def compare_frames(edl: dict, got: list, only_unzoomed: bool = False) -> dict:
    """The band read from an output (`got`, one source frame number per output frame) against what the kept ranges say, exactly:
    {checked, bad, largest_offset, first_bad, frames}. With `only_unzoomed` the ranges drawn zoomed are skipped (their band is scaled by the
    zoom): used by the real-size legs, whose edit list keeps the real shape, zoom included. `frames` is the number of frames read."""
    want = expected_sources(edl["kept"])
    use = set(unzoomed_ranges(edl)) if only_unzoomed else set(range(len(edl["kept"])))
    checked, bad, largest, first_bad, at = 0, 0, 0, None, 0
    for k, (a, b) in enumerate(edl["kept"]):
        for i in range(at, at + (b - a)):
            if k in use:
                checked += 1
                seen = got[i] if i < len(got) else None
                if seen != want[i]:
                    bad += 1
                    largest = max(largest, abs(seen - want[i]) if seen is not None else 1 << BAND_BITS)
                    first_bad = i if first_bad is None else first_bad
        at += b - a
    return {"checked": checked, "bad": bad, "largest_offset": largest, "first_bad": first_bad, "frames": len(got)}


# ---------------------------------------------------------------- the transcripts (5.1, 5.3)

SHORT = K.SHORT_SENTENCES
PLAIN_POST = """# Post: Money habits, no overlays (a fictional fixture)

- Owner: mkt-social-copy
- Status: draft
- Network: instagram
- Format: reel

```script
beat: 1
line: Hey, quick story about money.

beat: 2
line: Last year I tracked every expense for ninety days.

beat: 3
line: The first rule is simple: name every dollar.

beat: 4
line: Then do three things each week: review, adjust, and celebrate.
```

```post
Money habits. What would you track first?
```
"""

# Fictional filler sentences (6-10 words each, no repeated opening), after K.SENTENCES. The pauses cycle through PAUSES (0.9-1.6 s).
PAUSES = [0.9, 1.1, 1.3, 1.0, 1.6, 1.2, 0.95, 1.45]
FILLER_LONG = [
    "Our neighbour records every purchase inside a weathered notebook.",
    "She illustrates each column with tiny drawings of vegetables.",
    "Sunday evenings bring the whole family around the kitchen table.",
    "Some weeks the totals surprise everyone, while others change nothing.",
    "The garden budget expands slowly, exactly like tomatoes growing.",
    "Last spring a broken ladder cost considerably more than seeds.",
    "Gradually everyone learned to question whatever purchase replaces something working.",
    "A ceramic jar upon the shelf collects forgotten coins patiently.",
    "Rainy afternoons make the quiet accounts look suspiciously cheerful somehow.",
    "My cousin recommends envelopes labelled with seasonal names.",
    "Another envelope covers winter boots, birthday celebrations, and unexpected visitors.",
    "Whenever an envelope empties prematurely, relatives assemble for discussion.",
    "Decisions are counted using dried beans dropped into pottery bowls.",
    "That pottery survived several relocations and one extremely curious kitten.",
    "Every autumn we weigh the ceramic jar and estimate treasure.",
    "Grandmother once predicted the complete amount within some pennies.",
    "She insists patience remains the cheapest instrument inside any workshop.",
    "Workshops demonstrate that repairing beats replacing nearly every single time.",
    "Mended jackets still protect travellers against stubborn northern breezes.",
    "Borrowed paperbacks returned punctually never accumulate embarrassing penalties.",
    "Neighbours celebrate every monthly milestone with warm bread and honey.",
    "Honey gets measured in teaspoons and recorded within identical ledgers.",
    "Tidy handwriting makes tomorrow's decisions feel noticeably lighter and friendlier.",
    "Margin notes remind everybody why particular directions seemed sensible originally.",
    "Harvest festivals attract cheerful crowds and wildly unpredictable seasonal prices.",
    "Vendors displaying honest scales always collect remarkably patient customer queues.",
]
FILLER_SHORT = [
    "Lanterns glow along the harbour every evening.",
    "Fishermen mend their nets before the tide returns.",
    "A baker counts loaves while the oven cools.",
    "Children trade paper boats beside the fountain.",
    "The librarian stamps each card with careful hands.",
    "Cobblers repair boots for travellers heading north.",
    "A clockmaker winds forty clocks every Monday.",
    "Violin lessons echo above the sleepy bakery.",
    "Painters mix colours borrowed from the morning sky.",
    "Gardeners prune the hedges into friendly shapes.",
    "The ferry captain whistles an old marching tune.",
    "Pigeons gather around the weathered stone bench.",
    "Postal carriers deliver letters before the sun climbs.",
    "A potter shapes bowls from the river clay.",
    "Weavers share patterns across three neighbouring villages.",
    "The mapmaker redraws the coastline after each storm.",
    "Orchard keepers label every basket by variety.",
    "A shepherd counts clouds when the sheep are quiet.",
    "Beekeepers listen to the hives at dusk.",
    "Carpenters sand the benches until they gleam.",
    "Bakers swap recipes for jam on festival days.",
    "Travelling musicians rest under the old plane tree.",
    "The lighthouse keeper polishes the lens each sunrise.",
    "Tailors measure twice and cut only once.",
    "Market clerks chalk the daily prices on slate.",
    "A stonemason carves initials into the bridge rail.",
]


def _with_filler(texts) -> dict:
    sentences = list(K.SENTENCES) + [(PAUSES[i % len(PAUSES)], t) for i, t in enumerate(texts)]
    return K.build_transcript(sentences)


def short_transcript() -> dict:
    """The short case: the first four sentences of the kit, which `K.HF_POST` is made from."""
    return K.build_transcript(SHORT)


def real_size_transcript() -> dict:
    """The real shape, in fictional words: 195.9 s and 37 kept ranges in the base edit list (the real one was 192.66 s and 35 ranges)."""
    return _with_filler(FILLER_LONG)


def max_transcript() -> dict:
    """The input limit: 298.6 s (the limit is 300) and 61 kept ranges."""
    return _with_filler(FILLER_LONG + FILLER_SHORT)


def silences_of(doc: dict) -> list:
    """The silences `analyse` would find in the recording of `doc` (a gap of more than 0.5 s between spans of speech joined at 0.6 s)."""
    spans = K.speech_spans(doc["words"], join=0.6)
    return [{"start": round(a[1], 3), "end": round(b[0], 3)} for a, b in zip(spans, spans[1:]) if b[0] - a[1] > 0.5]


def base_of(doc: dict, data=None, **kwargs) -> dict:
    """The base edit list of `doc` as `base` writes it, from silences computed from the words (offline: nothing is analysed)."""
    data = data or load_data()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": silences_of(doc)}
    return _edl.build_base(doc, analysis, data, {}, **kwargs)[0]


def retake_proposals(doc: dict, data=None) -> list:
    data = data or load_data()
    sil = [(s["start"], s["end"]) for s in silences_of(doc)]
    return _retakes.detect_retakes(doc["words"], doc["language"], data["retakes"], sil)


# ---------------------------------------------------------------- the planted blocks (5.4)

PLANTS = {
    "cover": ("oh/keyword/renderat.html", "  pos.style.top = z[0] + 'px';", "  pos.style.top = '650px';"),
    "low": ("oh/caption/renderat.html", "  stage.style.top = z[0] + 'px';", "  stage.style.top = (z[1] - 40) + 'px';"),
}


def planted_renderat(tmp, which: str) -> Path:
    """A copy of the committed blocks with the HyperFrames engine on the renderat runtime and the `oh:` presets (so both engines draw
    the same pages) and one edit that breaks a rule, pinned again: `cover` puts the keyword card at y 650 (the face box is y 620-1180),
    `low` puts the caption 40 px under the caption band's bottom. Used with RENDERER_TEST=1 and RENDERER_BLOCKS_DIR=<the folder>."""
    rel, old, new = PLANTS[which]
    folder = Path(tmp) / ("renderat-" + which)
    shutil.rmtree(str(folder), ignore_errors=True)               # both engines' legs ask for the same folder in one lab
    shutil.copytree(K.BLOCKS, folder)
    K.write_hf_compose_blocks(folder)
    path = folder / rel
    html = path.read_text(encoding="utf-8")
    assert html.count(old) == 1, "the line to edit is not in %s exactly once" % rel
    edited = html.replace(old, new)
    assert edited != html
    path.write_text(edited, encoding="utf-8")
    _blocks.write_pins(str(folder))
    return folder


def planted_blank(tmp) -> Path:
    """HyperFrames only: a copy of the committed blocks plus a fictional caption block, `hf:demo-blank`, whose words are drawn at
    `font-size: 0px`, set as the engine's caption. The gates must refuse it `caption_not_drawn`."""
    folder = Path(tmp) / "blocks-blank"
    shutil.rmtree(str(folder), ignore_errors=True)
    shutil.copytree(K.BLOCKS, folder)
    name = "hf:demo-blank"
    block = dict(K.PLANTED_BLOCK, name=name, kind="caption", preset="caption", band="caption", params={}, samples=[{}], natural_duration=None,
                 use_when="a fictional caption whose words have no size, used by the live tests only")
    fragment = K.PLANTED_FRAGMENT % {"name": name, "zone": "caption", "down": 0,
                                     "text": 'data.words.map(function (w) { return w.text; }).join(" ")'}
    blank = fragment.replace("font-size: 48px;", "font-size: 0px;")
    assert blank != fragment
    (folder / "hf" / "demo-blank").mkdir()
    (folder / "hf" / "demo-blank" / "block.json").write_text(json.dumps(block, indent=1), encoding="utf-8")
    (folder / "hf" / "demo-blank" / "gsap.html").write_text(blank, encoding="utf-8")
    presets = dict(K.OH_PRESETS)
    presets["caption"] = name
    (folder / "engines" / "hyperframes.json").write_text(json.dumps(
        {"schema_version": 1, "engine": "hyperframes", "note": "a fictional engine for the tests", "runtimes": ["gsap", "renderat"], "presets": presets}, indent=1),
        encoding="utf-8")
    _blocks.write_pins(str(folder))
    return folder


def pins_sha256(folder) -> str:
    return hashlib.sha256((Path(folder) / "pins.json").read_bytes()).hexdigest()


# ---------------------------------------------------------------- where two outputs differ (copied from test_renderer_docker_live.py)

def decoded_frames(run, name: str, folder) -> list:
    """The md5 line of every decoded video frame of `folder/name`, in order. `run(args, folder)` runs one ffmpeg command on the folder."""
    text = run(["-v", "error", "-i", "/out/" + name, "-map", "0:v:0", "-f", "framemd5", "-"], folder)
    return [x.split(",")[-1].strip() for x in text.splitlines() if x and not x.startswith("#")]


def streams_report(run, name: str, folder) -> dict:
    """For each stream the packet count and a hash of the packets' own checksums (`-c copy`: what the encoder wrote), and the same for the
    decoded frames."""
    report = {}
    for stream, label in (("0:v:0", "video"), ("0:a:0", "audio")):
        for mode, extra in (("packets", ["-c", "copy"]), ("decoded", [])):
            text = run(["-v", "error", "-i", "/out/" + name, "-map", stream, *extra, "-f", "framemd5", "-"], folder)
            lines = [x for x in text.splitlines() if x and not x.startswith("#")]
            report["%s %s" % (label, mode)] = {"count": len(lines), "hash": hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16],
                                              "first": lines[0] if lines else "", "last": lines[-1] if lines else ""}
    return report


def mismatch_report(run, runs: list) -> dict:
    """What the live file prints when two renders of the same input differ: `runs` is [(label, folder, name, sha256)]. The streams report of the
    first run and of the first that differs, and the first decoded frame that differs."""
    first = runs[0]
    other = next(r for r in runs if r[3] != first[3])
    report = {"sha256": [r[3] for r in runs], "streams": {r[0]: streams_report(run, r[2], r[1]) for r in (first, other)}}
    frames = [decoded_frames(run, r[2], r[1]) for r in (first, other)]
    report["first differing decoded video frame"] = {"index": next((k for k, (x, y) in enumerate(zip(*frames)) if x != y), None), "frames": [len(f) for f in frames]}
    return report


# ---------------------------------------------------------------- the memory sampler (6.2)

MIB = {"B": 1.0 / (1 << 20), "KIB": 1.0 / 1024, "KB": 1.0 / 1024, "MIB": 1.0, "MB": 1.0, "GIB": 1024.0, "GB": 1024.0, "TIB": 1024.0 ** 2}
USAGE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)")
HF_PREFIX, COMMON_PREFIX = "openhora-hyperframes-", "openhora-renderer-"


def parse_mib(text: str):
    """The first quantity of a `docker stats` MemUsage field ("512.3MiB / 6GiB") in MiB, or None."""
    m = USAGE.match(text.strip())
    if not m or m.group(2).upper() not in MIB:
        return None
    return float(m.group(1)) * MIB[m.group(2).upper()]


def read_stats(lines) -> dict:
    """The largest usage of each family in one `docker stats --no-stream --format "{{.Name}} {{.MemUsage}}"` output."""
    found = {"hf": None, "common": None}
    for line in lines:
        name, _, usage = line.strip().partition(" ")
        value = parse_mib(usage)
        family = "hf" if name.startswith(HF_PREFIX) else "common" if name.startswith(COMMON_PREFIX) else None
        if family and value is not None:
            found[family] = value if found[family] is None else max(found[family], value)
    return found


class Sampler:
    """A thread that, once a second, samples the memory of the renderer containers and keeps the maximum of each family. `run` stands where
    `subprocess.run` stands (a test's seam). Memory here is what `docker stats` reports (usage less the inactive file cache on cgroup v2): a
    one-second sample can miss a short peak."""

    def __init__(self, run=subprocess.run, interval: float = 1.0):
        self.run, self.interval = run, interval
        self.max = {"hf": None, "common": None}
        self._stop = threading.Event()
        self._thread = None
        self.started = None

    def sample(self) -> None:
        try:
            done = self.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return
        if done.returncode != 0:
            return
        for family, value in read_stats(done.stdout.splitlines()).items():
            if value is not None:
                self.max[family] = value if self.max[family] is None else max(self.max[family], value)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.interval)

    def __enter__(self):
        self.started = int(time.time())
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=60)
        return False

    def figures(self) -> dict:
        """{hf_sampled_max_mib, common_sampled_max_mib}: whole MiB, None when no container of the family was ever seen."""
        return {"hf_sampled_max_mib": None if self.max["hf"] is None else int(round(self.max["hf"])),
                "common_sampled_max_mib": None if self.max["common"] is None else int(round(self.max["common"]))}


def count_oom(run, since: int, until: int) -> int:
    """The number of OOM kills `docker events` reports between two instants (epoch seconds)."""
    done = run(["docker", "events", "--since", str(since), "--until", str(until), "--filter", "event=oom", "--format", "{{.ID}}"],
               capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError("docker events failed: %s" % done.stderr[-300:])
    return len([x for x in done.stdout.splitlines() if x.strip()])


# ---------------------------------------------------------------- the report (6)

CASES = ("short", "real", "max")
ENGINE_NAMES = ("ffmpeg", "hyperframes")
STAGES = ("render", "page", "proxy", "hf", "encode", "measure", "pixel")
MEMORY_KEYS = ("hf_cgroup_peak_mib", "hf_sampled_max_mib", "common_sampled_max_mib", "oom_events")
GATE_KEYS = ("frames", "boxes", "lowest_caption_bottom", "pixel_min_psnr_db", "pixel_ranges")
SHA = re.compile(r"[0-9a-f]{64}")
HEX12 = re.compile(r"[0-9a-f]{12}")
COMMIT = re.compile(r"[0-9a-f]{40}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
CPUSET = re.compile(r"[0-9]+-[0-9]+")
CODE = re.compile(r"[a-z_]{1,40}")
VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")
REPORT_NAME = re.compile(r"engine-contract-([0-9]{4}-[0-9]{2}-[0-9]{2})-(arm64|amd64)\.json")


class ReportError(ValueError):
    pass


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and abs(x) < 1e12 and x == x


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and 0 <= x < 1 << 62


def _keys(doc, keys, where: str) -> None:
    if not isinstance(doc, dict) or set(doc) != set(keys):
        raise ReportError("%s: the keys are not exactly %s" % (where, sorted(keys)))


def _match(value, pattern, where: str) -> None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ReportError("%s: a string outside its pattern" % where)


def _nullable(value, test, where: str) -> None:
    if value is not None and not test(value):
        raise ReportError("%s: the wrong type" % where)


def _no_free_text(value, where: str = "report") -> None:
    """No string anywhere that looks like a path or is longer than a closed word: the report holds no path, no word of a transcript."""
    if isinstance(value, str):
        if "/" in value or "\\" in value or len(value) > 64 or value.startswith("~"):
            raise ReportError("%s: a path-like or free-text string" % where)
    elif isinstance(value, dict):
        for k, v in value.items():
            _no_free_text(k, where)
            _no_free_text(v, where + "." + str(k))
    elif isinstance(value, list):
        for v in value:
            _no_free_text(v, where)


def check_report(doc) -> dict:
    """The one closed schema of `providers/renderer/reports/engine-contract-<date>-<arch>.json`: hashes, numbers, closed words, bools and a date;
    no path, no word of a transcript, no host name. Raises ReportError, returns the document."""
    _keys(doc, ("schema", "date", "commit", "arch", "machine", "images", "hyperframes_version", "cases"), "report")
    if doc["schema"] != 1 or isinstance(doc["schema"], bool):
        raise ReportError("schema: only 1")
    _match(doc["date"], DATE, "date")
    _match(doc["commit"], COMMIT, "commit")
    if doc["arch"] not in ("arm64", "amd64"):
        raise ReportError("arch: arm64 or amd64")
    _keys(doc["machine"], ("docker_cpus", "docker_memory_mib"), "machine")
    if not all(_int(doc["machine"][k]) for k in doc["machine"]):
        raise ReportError("machine: whole numbers")
    _keys(doc["images"], ("common", "hyperframes"), "images")
    for k in ("common", "hyperframes"):
        _match(doc["images"][k], HEX12, "images." + k)
    if doc["hyperframes_version"] is not None:
        _match(doc["hyperframes_version"], VERSION, "hyperframes_version")
    if not isinstance(doc["cases"], list) or not doc["cases"]:
        raise ReportError("cases: a list of at least one")
    for n, case in enumerate(doc["cases"]):
        where = "cases[%d]" % n
        _keys(case, ("case", "input_seconds", "kept_ranges", "out_frames", "words", "runs", "same_sha256"), where)
        if case["case"] not in CASES:
            raise ReportError(where + ".case: closed words")
        if not _num(case["input_seconds"]) or not all(_int(case[k]) for k in ("kept_ranges", "out_frames", "words")):
            raise ReportError(where + ": numbers")
        _keys(case["same_sha256"], ENGINE_NAMES, where + ".same_sha256")
        for e in ENGINE_NAMES:
            _nullable(case["same_sha256"][e], lambda v: isinstance(v, bool), where + ".same_sha256")
        if not isinstance(case["runs"], list) or not case["runs"]:
            raise ReportError(where + ".runs: a list of at least one")
        for m, run in enumerate(case["runs"]):
            check_run(run, "%s.runs[%d]" % (where, m))
    _no_free_text(doc)
    return doc


def check_run(run, where: str) -> None:
    _keys(run, ("engine", "cpus", "cpuset", "outcome", "code", "sha256", "bytes", "frames_ok", "wall_seconds", "stage_seconds", "memory", "gate"), where)
    if run["engine"] not in ENGINE_NAMES:
        raise ReportError(where + ".engine: closed words")
    if not _int(run["cpus"]):
        raise ReportError(where + ".cpus: a whole number")
    _match(run["cpuset"], CPUSET, where + ".cpuset")
    if run["outcome"] not in ("ok", "refused"):
        raise ReportError(where + ".outcome: ok or refused")
    if run["code"] is not None:
        _match(run["code"], CODE, where + ".code")
    if run["sha256"] is not None:
        _match(run["sha256"], SHA, where + ".sha256")
    _nullable(run["bytes"], _int, where + ".bytes")
    _nullable(run["frames_ok"], lambda v: isinstance(v, bool), where + ".frames_ok")
    if not _num(run["wall_seconds"]):
        raise ReportError(where + ".wall_seconds: a number")
    for key, keys, test in (("stage_seconds", STAGES, _num), ("memory", MEMORY_KEYS, _num), ("gate", GATE_KEYS, _num)):
        block = run[key]
        if block is None:
            continue
        if not isinstance(block, dict) or not set(block) <= set(keys):
            raise ReportError("%s.%s: an unknown key" % (where, key))
        for k, v in block.items():
            _nullable(v, test, "%s.%s.%s" % (where, key, k))
    if run["outcome"] == "ok" and run["sha256"] is None:
        raise ReportError(where + ": an ok run has a sha256")


def placeholder_report() -> dict:
    """The example of the spec (section 6.2), the right types and no result: what the schema's tests start from."""
    run = {"engine": "hyperframes", "cpus": 8, "cpuset": "0-7", "outcome": "ok", "code": None, "sha256": "a" * 64, "bytes": 115000000, "frames_ok": True,
           "wall_seconds": 1200.5, "stage_seconds": {"page": 1.0, "proxy": 30.0, "hf": 500.0, "encode": 600.0, "measure": 40.0, "pixel": 170.0},
           "memory": {"hf_cgroup_peak_mib": 6144, "hf_sampled_max_mib": 3100, "common_sampled_max_mib": 900, "oom_events": 0},
           "gate": {"frames": 3773, "boxes": 50000, "lowest_caption_bottom": 1516.0, "pixel_min_psnr_db": 48.2, "pixel_ranges": 35}}
    return {"schema": 1, "date": "2026-11-10", "commit": "b" * 40, "arch": "arm64", "machine": {"docker_cpus": 14, "docker_memory_mib": 26000},
            "images": {"common": "c" * 12, "hyperframes": "d" * 12}, "hyperframes_version": "0.9.19",
            "cases": [{"case": "real", "input_seconds": 192.6, "kept_ranges": 35, "out_frames": 3773, "words": 410, "runs": [run],
                       "same_sha256": {"ffmpeg": None, "hyperframes": None}}]}


def run_row(engine: str, cpus: int, cpuset: str, result, code, wall: float, memory, frames_ok=None) -> dict:
    """One row of a case's `runs`, from what a render printed: `result` is its JSON when it succeeded (else None) and `code` the closed code of a
    refusal. `memory` is {hf_sampled_max_mib, common_sampled_max_mib, oom_events}."""
    ok = isinstance(result, dict) and result.get("ok") is True
    row = {"engine": engine, "cpus": cpus, "cpuset": cpuset, "outcome": "ok" if ok else "refused", "code": None if ok else code,
           "sha256": result["sha256"] if ok else None, "bytes": result.get("bytes") if ok else None, "frames_ok": frames_ok if ok else None,
           "wall_seconds": round(wall, 1), "stage_seconds": None, "memory": None, "gate": None}
    if ok and engine == "ffmpeg":
        row["stage_seconds"] = {"render": (result.get("seconds") or {}).get("total")}
    if ok and engine == "hyperframes":
        row["stage_seconds"] = {k: v for k, v in (result.get("stage_seconds") or {}).items() if k in STAGES}
        gate = result.get("gate") or {}
        row["gate"] = {k: gate.get(k) for k in GATE_KEYS}
        peak = result.get("memory_peak_bytes")
        memory = dict(memory or {}, hf_cgroup_peak_mib=None if peak is None else int(peak) // (1 << 20))
    if memory is not None:
        row["memory"] = {k: memory.get(k) for k in MEMORY_KEYS}
    return row


def case_row(name: str, transcript: dict, edl: dict, runs: list) -> dict:
    """One element of the report's `cases`: the facts of the input and the runs, with, for each engine, whether every ok run has the same sha256
    (None when fewer than two ok runs)."""
    same = {}
    for engine in ENGINE_NAMES:
        shas = [r["sha256"] for r in runs if r["engine"] == engine and r["outcome"] == "ok"]
        same[engine] = None if len(shas) < 2 else len(set(shas)) == 1
    return {"case": name, "input_seconds": round(transcript["duration"], 1), "kept_ranges": len(edl["kept"]), "out_frames": edl["out_frames"],
            "words": len(transcript["words"]), "runs": runs, "same_sha256": same}
