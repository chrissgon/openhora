"""Fictional fixtures and helpers for the renderer's tests. Everything here is invented: the people, the sentences, the
figures; the video is a synthetic test pattern with a tone that is silent between the sentences.

Not a test file. Standard library only (ffmpeg builds the media).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RENDERER = HERE.parent
REPO = RENDERER.parent.parent
sys.path.insert(0, str(RENDERER))

import hashlib  # noqa: E402
import _blocks  # noqa: E402
import _frames  # noqa: E402
import _media  # noqa: E402

BLOCKS = RENDERER / "blocks"
BLOCKS_SHA256 = hashlib.sha256((BLOCKS / "pins.json").read_bytes()).hexdigest()


def template_of(preset: str) -> str:
    """The page the ffmpeg engine draws a preset with, as a path inside blocks/ ("oh/keyword/renderat.html")."""
    cat = _blocks.load_catalogue(str(BLOCKS))
    return _blocks.implementation(cat, cat["blocks"][cat["engines"]["ffmpeg"]["presets"][preset]], "ffmpeg")


HF_ENTRY = {"name": "hf:demo-pop", "kind": "overlay", "preset": "keyword", "band": "card", "may_cross_face": False, "license": ["Apache-2.0"],
            "source": "hyperframes-registry", "use_when": "a fictional pop for one short phrase, used by the tests only",
            "params": {"text": {"type": "text", "max": 24, "required": True}, "scale": {"type": "number", "min": 0.5, "max": 2}},
            "samples": [{"text": "Name every dollar", "scale": 1}], "natural_duration": 1.2, "implementations": {"gsap": "demo-pop.html"},
            "tier": "A", "commit": "a" * 40, "notice": "Copyright 2026 Example Authors", "files": {"demo-pop.html": "b" * 64}}
HF_PORT = {"schema_version": 1, "name": "hf:demo-ring", "kind": "overlay", "preset": "quote", "band": "card", "may_cross_face": False,
           "license": ["Apache-2.0"], "source": "hyperframes-registry", "use_when": "a fictional ring for a quotation, used by the tests only",
           "params": {"text": {"type": "text", "max": 120, "required": True}}, "samples": [{"text": "Small steps."}], "natural_duration": 2.0,
           "implementations": {"gsap": "gsap.html"}, "tier": "B", "commit": "a" * 40, "notice": "Copyright 2026 Example Authors"}


def write_hf_fixture(folder) -> None:
    """In a copy of the blocks: a fictional tier-A hf: block (an allowlist entry), a fictional tier-B port (a folder) and an engine that runs
    the gsap runtime only, then pin again. The code of _blocks does not change for any of it."""
    folder = Path(folder)
    allow = json.loads((folder / "hf" / "allowlist.json").read_text())
    allow.update(registry_commit="a" * 40, blocks=[HF_ENTRY])
    (folder / "hf" / "allowlist.json").write_text(json.dumps(allow, indent=1))
    (folder / "hf" / "demo-ring").mkdir()
    (folder / "hf" / "demo-ring" / "block.json").write_text(json.dumps(HF_PORT, indent=1))
    (folder / "hf" / "demo-ring" / "gsap.html").write_text("<!doctype html><title>demo</title>\n")
    (folder / "engines" / "hyperframes.json").write_text(json.dumps(
        {"schema_version": 1, "engine": "hyperframes", "note": "a fictional engine for the tests", "runtimes": ["gsap"], "presets": {"keyword": "hf:demo-pop"}}, indent=1))
    _blocks.write_pins(str(folder))

POP_GSAP = """<!-- hf:demo-pop: a fictional pop card, used by the tests only. -->
<template data-hf-block="hf:demo-pop">
  <style>
    :scope { display: block; }
    .card { position: absolute; left: 65px; right: 65px; top: 0; height: 100%; display: flex; align-items: center; justify-content: center;
            font-family: var(--font-display); font-weight: var(--weight-display); color: var(--c-text); }
  </style>
  <div class="card"><span class="label"></span></div>
  <script data-hf-build>
    function build(root, tl, data, ctx) {
      root.querySelector(".label").textContent = data.params.text;
      tl.fromTo(root.querySelector(".card"), { scale: 0.5, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.3, ease: "back.out(2)" }, 0);
    }
  </script>
</template>
"""
POP_BLOCK = {"schema_version": 1, "name": "hf:demo-pop", "kind": "overlay", "preset": "keyword", "band": "card", "may_cross_face": False, "license": ["Apache-2.0"],
             "source": "hyperframes-registry", "use_when": "a fictional pop card for one short phrase, used by the tests only",
             "params": {"text": {"type": "text", "max": 24, "required": True}, "icon": {"type": "icon"}},
             "samples": [{"text": "Name every dollar"}], "natural_duration": 1.2, "implementations": {"gsap": "gsap.html"},
             "tier": "B", "commit": "a" * 40, "notice": "Apache-2.0; adapted from a fictional registry at aaaaaaaa; notices in the image folder"}
OH_PRESETS = {"caption": "oh:caption", "keyword": "oh:keyword", "list": "oh:list", "number": "oh:number", "quote": "oh:quote"}


def write_hf_compose_blocks(folder, mixed=False) -> None:
    """In a copy of the blocks: the HyperFrames engine's own file and, when `mixed`, a fictional tier-B gsap block `hf:demo-pop` that draws the
    keyword preset. Without `mixed` the engine runs the renderat runtime only and draws the oh: pages (the one-file measurement's setup:
    no cutaway and no pip, which this engine does not draw). Pinned again."""
    folder = Path(folder)
    runtimes, presets = ["renderat"], dict(OH_PRESETS)
    if mixed:
        (folder / "hf" / "demo-pop").mkdir()
        (folder / "hf" / "demo-pop" / "block.json").write_text(json.dumps(POP_BLOCK, indent=1))
        (folder / "hf" / "demo-pop" / "gsap.html").write_text(POP_GSAP)
        runtimes, presets["keyword"] = ["gsap", "renderat"], "hf:demo-pop"
    (folder / "engines" / "hyperframes.json").write_text(json.dumps(
        {"schema_version": 1, "engine": "hyperframes", "note": "a fictional engine for the tests", "runtimes": runtimes, "presets": presets}, indent=1))
    _blocks.write_pins(str(folder))


# --- planted blocks: fictional, test-only blocks that break a rule, for the gates of the HyperFrames engine (never committed)
PLANTED_BLOCK = {"schema_version": 1, "license": ["Apache-2.0"], "source": "hyperframes-registry", "may_cross_face": False, "tier": "B", "commit": "a" * 40,
                 "notice": "Apache-2.0; adapted from a fictional registry at aaaaaaaa; notices in the image folder", "implementations": {"gsap": "gsap.html"}}
PLANTED_FRAGMENT = """<template data-hf-block="%(name)s">
  <style>
    :scope { display: block; }
    .line { position: absolute; left: 65px; font-family: var(--font-display); font-weight: var(--weight-display); color: var(--c-text); font-size: 48px; }
  </style>
  <div class="line"><span class="words"></span></div>
  <script data-hf-build>
    function build(root, tl, data, ctx) {
      var band = data.zones.%(zone)s;
      root.querySelector(".line").style.top = (band[1] - band[0] + %(down)d) + "px";
      root.querySelector(".words").textContent = %(text)s;
      tl.fromTo(root.querySelector(".line"), { opacity: 0 }, { opacity: 1, duration: 0.1 }, 0);
    }
  </script>
</template>
"""


def planted_blocks(tmp_path, which):
    """A copy of the committed blocks plus the HyperFrames engine's file and one fictional test-only block that breaks a rule, never committed:
    `hf:demo-cover` (the keyword card) puts its text 20 px into the face box (the card band's bottom, the 18 px gap and 20 px), `hf:demo-low`
    (the caption) puts its words 20 px under the caption band's bottom. Both sit inside an instance that clips what it draws to its band, so the
    refusal comes from the text's own rectangles, which the page reports unclipped."""
    folder = tmp_path / ("blocks-" + which)
    shutil.copytree(BLOCKS, folder)
    name, preset, band, zone, down, text = {
        "demo-cover": ("hf:demo-cover", "keyword", "card", "card", 38, "data.params.text"),
        "demo-low": ("hf:demo-low", "caption", "caption", "caption", 20, 'data.words.map(function (w) { return w.text; }).join(" ")'),
    }[which]
    block = dict(PLANTED_BLOCK, name=name, kind="caption" if preset == "caption" else "overlay", preset=preset, band=band,
                 use_when="a fictional block that breaks a rule, used by the live tests only", samples=[{} if preset == "caption" else {"text": "Name every dollar"}],
                 params={} if preset == "caption" else {"text": {"type": "text", "max": 24, "required": True}, "icon": {"type": "icon"}}, natural_duration=None if preset == "caption" else 1.2)
    (folder / "hf" / which).mkdir()
    (folder / "hf" / which / "block.json").write_text(json.dumps(block, indent=1))
    (folder / "hf" / which / "gsap.html").write_text(PLANTED_FRAGMENT % {"name": name, "zone": zone, "down": down, "text": text})
    presets = dict(OH_PRESETS)
    presets[preset] = name
    (folder / "engines" / "hyperframes.json").write_text(json.dumps(
        {"schema_version": 1, "engine": "hyperframes", "note": "a fictional engine for the tests", "runtimes": ["gsap", "renderat"], "presets": presets}, indent=1))
    _blocks.write_pins(str(folder))
    return folder


def hf_documents(tmp):
    """(data, edl, beats, vocab) of the fictional post for the HyperFrames engine: the base edit list of the kit's transcript, the post's beats
    without the cutaway and the pip (which this engine does not draw). Written under `tmp` for the `align` verb."""
    import _edl
    from _vocab import load_data, load_vocabulary
    data, vocab = load_data(), load_vocabulary(str(VOCABULARY))
    doc = build_transcript()
    spans = speech_spans(doc["words"], join=0.6)
    silences = [{"start": round(a[1], 3), "end": round(b[0], 3)} for a, b in zip(spans, spans[1:]) if b[0] - a[1] > 0.5]
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": silences}
    edl, _ = _edl.build_base(doc, analysis, data, {})
    tmp = Path(tmp)
    write_json(tmp / "transcript.json", doc)
    (tmp / "post.md").write_text(POST, encoding="utf-8")
    rc, out, err = run_verb("align", "--post", tmp / "post.md", "--transcript", tmp / "transcript.json", "--checker", CHECKER, "--vocabulary", VOCABULARY,
                            "--out", tmp / "beats.json")
    assert rc == 0, err
    beats = json.loads((tmp / "beats.json").read_text())
    beats["layouts"] = []
    return data, edl, beats, vocab


FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
HAVE_FFMPEG = os.access(FFMPEG, os.X_OK) and os.access(FFPROBE, os.X_OK)
def _find_browser():
    import glob
    for pattern in ("~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell",
                    "~/.cache/ms-playwright/chromium_headless_shell-*/chrome-linux/headless_shell"):
        for hit in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):
            if os.access(hit, os.X_OK):
                return hit
    return os.environ.get("RENDERER_BROWSER") if os.access(os.environ.get("RENDERER_BROWSER") or "/nonexistent", os.X_OK) else None


BROWSER = _find_browser()
VOCABULARY = REPO / "shared" / "references" / "video-presets.json"
INSTAGRAM = REPO / "shared" / "references" / "platforms" / "instagram.json"
TIKTOK = REPO / "shared" / "references" / "platforms" / "tiktok.json"
CHECKER = REPO / "skills" / "mkt-social-copy" / "scripts" / "check_script.py"
SCRIPT = RENDERER / "_inner.py"          # the container entry point, run on the host here with a local Chromium
HOST = RENDERER / "ffmpeg.py"            # the host side (docker)
SKIP_MEDIA = "ffmpeg and ffprobe are needed"
SKIP_BROWSER = "no headless Chromium is installed (the Playwright cache, or RENDERER_BROWSER)"

# (pause before the sentence in seconds, sentence)
SENTENCES = [
    (1.0, "Hey, quick story about money."),
    (1.1, "Last year I tracked every expense for ninety days."),
    (0.9, "The first rule is simple: name every dollar."),
    (1.2, "Then do three things each week: review, adjust, and celebrate."),
    (0.8, "That habit saved me three hundred forty dollars in one month."),
    (1.0, "A wise friend told me, small steps beat big plans."),
    (1.1, "Here is what my dashboard looked like."),
    (0.9, "Look at the chart while I walk you through it."),
    (1.0, "Follow for more small steps."),
]
TAIL = 1.3

POST = """# Post: Three habits that changed how I handle money (a fictional fixture)

- Owner: mkt-social-copy
- Status: draft
- Network: instagram
- Format: reel

## Script

```script
beat: 1
line: Hey, quick story about money.

beat: 2
line: Last year I tracked every expense for ninety days.

beat: 3
line: The first rule is simple: name every dollar.
on-screen: Name every dollar
preset: keyword
icon: coin

beat: 4
line: Then do three things each week: review, adjust, and celebrate.
on-screen: Review | Adjust | Celebrate
preset: list
icon: check

beat: 5
line: That habit saved me three hundred forty dollars in one month.
on-screen: dollars saved in one month
preset: number
value: 340

beat: 6
line: A wise friend told me, small steps beat big plans.
on-screen: Small steps beat big plans.
preset: quote
author: A wise friend

beat: 7
line: Here is what my dashboard looked like.
on-screen: My dashboard
preset: cutaway
asset: a screenshot of the budgeting dashboard
fit: cover

beat: 8
line: Look at the chart while I walk you through it.
on-screen: Weekly savings
preset: pip
asset: a bar chart of weekly savings
position: top

beat: 9
line: Follow for more small steps.
```

## Post

```post
Three habits that changed how I handle money. What is the first one you would try?

#money #habits
```
"""


SHORT_SENTENCES = SENTENCES[:4]
SHORT_POST = """# Post: Money habits, short (a fictional fixture)

- Owner: mkt-social-copy
- Status: draft
- Network: instagram
- Format: reel

```script
beat: 1
line: Hey, quick story about money.
on-screen: Money story
preset: keyword
icon: coin

beat: 2
line: Last year I tracked every expense for ninety days.
on-screen: ninety days of expenses
preset: number
value: 90

beat: 3
line: The first rule is simple: name every dollar.
on-screen: My dashboard
preset: cutaway
asset: a screenshot of the budgeting dashboard

beat: 4
line: Then do three things each week: review, adjust, and celebrate.
on-screen: Weekly savings
preset: pip
asset: a bar chart of weekly savings
position: bottom
```

```post
Money habits. What would you track first?
```
"""


HF_POST = """# Post: Money habits, for the HyperFrames engine (a fictional fixture)

- Owner: mkt-social-copy
- Status: draft
- Network: instagram
- Format: reel

```script
beat: 1
line: Hey, quick story about money.
on-screen: Money story
preset: keyword
icon: coin

beat: 2
line: Last year I tracked every expense for ninety days.
on-screen: ninety days of expenses
preset: number
value: 90

beat: 3
line: The first rule is simple: name every dollar.
on-screen: Review | Adjust | Celebrate
preset: list
icon: check

beat: 4
line: Then do three things each week: review, adjust, and celebrate.
on-screen: Small steps beat big plans.
preset: quote
author: A wise friend
```

```post
Money habits. What would you track first?
```
"""


def facts_block() -> dict:
    return {"provider": "fixture", "whisper_cpp_tag": "v0", "whisper_cpp_commit": "0" * 40, "image_id": "sha256:fixture",
            "cpu_arch": "arm64", "cpu_flags": "none", "model": {"name": "fixture", "file": "fixture.bin", "sha256": "0" * 64},
            "timestamps": "word", "flags": [], "language_requested": "en", "language_detected": "en", "segment_unit": "sentence",
            "input_duration": 0.0, "wall_seconds": 0.0, "words_without_timing": 0, "clamped_words": 0, "dropped_annotations": 0}


def build_transcript(sentences=SENTENCES, tail=TAIL) -> dict:
    """A transcript in the transcriber's format (words with `index`, segments), one segment per sentence."""
    words, segments, t = [], [], 0.0
    for seg, (pause, sentence) in enumerate(sentences):
        t += pause
        first = len(words)
        seg_start = t
        for tok in sentence.split():
            dur = round(0.10 + 0.045 * sum(ch.isalpha() for ch in tok), 3)
            words.append({"index": len(words), "text": tok, "start": round(t, 3), "end": round(t + dur, 3), "segment": seg})
            t += dur + 0.07
            if tok.endswith(","):
                t += 0.15
            if tok.endswith(":"):
                t += 0.75
        segments.append({"index": seg, "start": round(seg_start, 3), "end": words[-1]["end"], "text": sentence, "first_word": first,
                         "last_word": len(words) - 1})
    duration = round(words[-1]["end"] + tail, 3)
    return {"schema_version": 1, "language": "en", "duration": duration, "words": words, "segments": segments, "facts": facts_block()}


def real_shape_transcript() -> dict:
    """The shapes a real transcript had (fictional words): runs of zero-length words sharing a start, starts that go back in
    time, and a sentence repeated in a 0.4 s final segment (21 words)."""
    sentences = [(0.8, "Hello again, this is a short story about a lost umbrella."),
                 (0.9, "I left it on the bus, then I went back to look for it."),
                 (1.0, "The driver kept it safe, and that is the end of the story.")]
    doc = build_transcript(sentences, tail=0.6)
    words = doc["words"]
    # a run of three zero-length words sharing one start (segment 0, words 2..4)
    start = words[2]["start"]
    for i in (2, 3, 4):
        words[i]["start"] = start
        words[i]["end"] = start
    # a start that goes back in time (segment 1)
    words[14]["start"] = round(words[13]["start"] - 0.08, 3)
    # a second run of two zero-length words at the very end of segment 2
    for i in (len(words) - 2, len(words) - 1):
        words[i]["start"] = words[len(words) - 3]["end"]
        words[i]["end"] = words[len(words) - 3]["end"]
    # a hallucinated repeat of the last sentence: 21 words squeezed into 0.4 s as one more segment
    last_end = words[-1]["end"]
    repeat = "The driver kept it safe and that is the end of the story the driver kept it safe and that is".split()[:21]
    seg = len(doc["segments"])
    first = len(words)
    for k, tok in enumerate(repeat):
        s = round(last_end + 0.02 * k, 3)
        words.append({"index": first + k, "text": tok, "start": s, "end": round(s + 0.02, 3), "segment": seg})
    doc["segments"].append({"index": seg, "start": round(last_end, 3), "end": round(last_end + 0.4, 3), "text": " ".join(repeat),
                            "first_word": first, "last_word": len(words) - 1})
    doc["duration"] = round(last_end + 0.7, 3)
    return doc


def speech_spans(words, join=0.3):
    spans = []
    for w in words:
        if spans and w["start"] - spans[-1][1] <= join:
            spans[-1][1] = w["end"]
        else:
            spans.append([w["start"], w["end"]])
    return spans


def make_source(path, transcript, size="1080x1920", rate=30, codec="libx264", timecode=False, audio_offset=0.0) -> None:
    """A synthetic vertical source: a test pattern, and a tone that sounds only while the words are spoken. With `audio_offset` the
    audio stream starts that many seconds after the video (its content is shifted back, so the tone still sounds at the words'
    times on the container's clock)."""
    d = transcript["duration"]
    terms = ["between(t+%.3f,%.3f,%.3f)*0.3*sin(2*PI*%d*t)" % (audio_offset, a, b, 180 + 35 * (k % 5)) for k, (a, b) in enumerate(speech_spans(transcript["words"]))]
    argv = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=%s:rate=%d:duration=%.3f" % (size, rate, d)]
    if audio_offset:
        argv += ["-itsoffset", "%.3f" % audio_offset]
    argv += ["-f", "lavfi", "-i", "aevalsrc='%s':s=48000:c=stereo:d=%.3f" % ("+".join(terms), d - audio_offset)]
    argv += ["-vf", "format=yuv420p", "-c:v", codec, "-pix_fmt", "yuv420p"]
    argv += ["-preset", "ultrafast"] if codec == "libx265" else ["-preset", "veryfast", "-crf", "16"]
    if codec == "libx265":
        argv += ["-tag:v", "hvc1"]
    argv += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-c:a", "aac", "-b:a", "128k"]
    if timecode:
        argv += ["-timecode", "01:00:00:00"]
    subprocess.run(argv + ["-movflags", "+faststart", str(path)], check=True, timeout=300)


def make_asset(path) -> None:
    """A drawn 1080x1920 PNG (bars on a gradient)."""
    chain = ["drawbox=x=70:y=420:w=940:h=1140:color=0x0B0F14@0.55:t=fill"]
    for k, h in enumerate([260, 340, 300, 460, 400, 560, 640]):
        chain.append("drawbox=x=%d:y=%d:w=95:h=%d:color=0xFFC93C:t=fill" % (110 + k * 125, 1500 - h, h))
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "gradients=size=1080x1920:c0=0x14213D:c1=0x3A0CA3:x0=0:y0=0:x1=1080:y1=1920:nb_colors=2:duration=1:rate=1",
                    "-vf", ",".join(chain), "-frames:v", "1", str(path)], check=True, timeout=120)


def write_json(path, obj) -> str:
    Path(path).write_text(json.dumps(obj, indent=1), encoding="utf-8")
    return str(path)


def run_verb(*args, env=None, timeout=900):
    """Run the container entry point (_inner.py) as a subprocess on the host. Returns (returncode, parsed stdout or None, stderr)."""
    e = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), **({"RENDERER_BROWSER": BROWSER} if BROWSER else {}), **(env or {})}
    done = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True, timeout=timeout, env=e)
    try:
        out = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        out = None
    return done.returncode, out, done.stderr


def pipeline(tmp, transcript=None, post_text=POST, jobs=2, extra_render=()):
    """analyse, base, align, render a fictional recording end to end; returns the files and the render summary."""
    tmp = Path(tmp)
    tr = transcript or build_transcript()
    src = tmp / "source.mp4"
    make_source(src, tr)
    asset = tmp / "asset.png"
    make_asset(asset)
    post = tmp / "post.md"
    post.write_text(post_text, encoding="utf-8")
    files = {"src": src, "asset": asset, "post": post, "transcript": write_json(tmp / "transcript.json", tr)}
    rc, out, err = run_verb("analyse", "--in", src, "--out", tmp / "analysis.json")
    assert rc == 0, err
    rc, out, err = run_verb("base", "--transcript", files["transcript"], "--analysis", tmp / "analysis.json", "--out", tmp / "edl.json")
    assert rc == 0, err
    rc, out, err = run_verb("align", "--post", post, "--transcript", files["transcript"], "--checker", CHECKER, "--vocabulary", VOCABULARY,
                            "--out", tmp / "beats.json")
    assert rc == 0, err
    files.update(analysis=tmp / "analysis.json", edl=tmp / "edl.json", beats=tmp / "beats.json")
    return files


def render_args(files, out_dir, *more, slots=(7, 8)):
    args = ["render", "--edl", files["edl"], "--beats", files["beats"], "--in", files["src"], "--out", out_dir, "--platform-file", INSTAGRAM,
            "--vocabulary", VOCABULARY]
    for slot in slots:
        args += ["--asset", "%s=%s" % (slot, files["asset"])]
    return [*args, *more]
