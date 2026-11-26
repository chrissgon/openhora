# The entry point of the renderer's container image (providers/renderer/Dockerfile): `python3 -I /opt/renderer/_inner.py <verb>`.
# Not a provider (a file whose name starts with an underscore is not an implementation); the host side is ffmpeg.py.
# Also run directly on the host by the tests, with a local Chromium in RENDERER_BROWSER (there the browser keeps its own sandbox).
"""Inside the container: the renderer's verbs, run on files under /job (read-only), /in (the recording, read-only), /out (the
only writable mount) and /scratch (memory-backed), with no network.

  analyse  --in VIDEO --out FILE            ffprobe facts, the recording's sha256, silencedetect intervals
  base     --transcript T --analysis A --out EDL ...           the code-generated base edit list
  align    --post FILE --transcript T --checker SCRIPT --vocabulary V --out BEATS ...   the beats, aligned
  check    --edl EDL --beats BEATS --vocabulary V [--platform-file F]        schema, bounds, hardening, credential shapes
  render   --edl EDL --beats BEATS --in VIDEO --out DIR --platform-file F --vocabulary V ...    the video
  storyboard (--post FILE --checker SCRIPT | --beat FILE) --vocabulary V --out DIR   a still per beat and a contact sheet, no recording
  verify   --in MP4 --platform-file F --sha256 H [--expect-seconds S]   a finished render against the platform's spec
  preview  --in MP4 --sha256 H --out FILE.mp4             a 720x1280 copy of a finished render, at most 15 MiB, one encoder thread
  cover    --in MP4 --offset-ms N --out PNG                  one frame of a render
  asset-sheet --asset ROW:COL=FILE ... --mode preview|full [--fps N] --out DIR   the pictures and clips to pick from, checked and tiled; in full mode normalised too
  still    --in VIDEO --at-ms N --out PNG                    one frame of a recording, framed as the render frames it (1080x1920)
  admit-check (--entry FILE --component-dir DIR | --port hf:NAME) --vocabulary V --blocks DIR --blocks-sha256 H --scratch DIR [--jobs N]   the determinism test of a candidate
           HyperFrames block, or of one of our own ports of the staged blocks (three forward runs and one reverse run per sample, each in a fresh browser, identical frame hashes; the exact gates; the font check)
  selfcheck                                  the versions of what the image holds, and that each tool starts

Every verb writes its result as one JSON object to `--result FILE` (before the verb; stdout when absent): the same object the
host prints. A refusal is {"ok": false, "code", "field", "problems"} and exit code 1 (3 for something not installed, 2 for a
usage error). The text of an input is never put in a result. The browser is the executable named by RENDERER_BROWSER (the
image sets it) or by --browser (the tests). Its own sandbox is on, except inside the image, where the container is the
boundary (_cdp.container_mode): the result says which (`browser_sandbox`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _advice  # noqa: E402
import _align  # noqa: E402
import _asset_sheet  # noqa: E402
import _assets  # noqa: E402
import _blocks  # noqa: E402
import _edl  # noqa: E402
import _media  # noqa: E402
import _output  # noqa: E402
import _timeline  # noqa: E402
from _text import Refusal  # noqa: E402
from _vocab import SLOT_ID, load_data, load_vocabulary, read_json  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
REQUIRED_ENCODERS = ("libx264", "aac", "png")
REQUIRED_FILTERS = ("overlay", "alphamerge", "geq", "setparams", "concat", "trim", "atrim", "split", "scale", "crop", "fps",
                    "silencedetect", "aformat", "asplit", "aecho", "volume", "amix",
                    "lutrgb", "gblur", "blend", "mix", "rgbashift")      # asides' echo (the four before); the transitions' chains (the last five)


class Usage(Exception):
    pass


class NotConfigured(Refusal):
    """Something the image should hold is missing (exit 3)."""


def emit(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


def write_json(path: str, obj) -> None:
    """Write a JSON file atomically, mode 0600 (it may hold a transcript's words)."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def tools(args) -> tuple:
    ffmpeg = getattr(args, "ffmpeg", None) or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    ffprobe = getattr(args, "ffprobe", None) or shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    for path in (ffmpeg, ffprobe):
        if not os.access(path, os.X_OK):
            raise NotConfigured("tool_missing", os.path.basename(path))
    return ffmpeg, ffprobe


def pairs(items, field: str, allow_empty_value=False) -> dict:
    out = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep or not key or (not value and not allow_empty_value) or key in out:
            raise Usage("%s takes KEY=VALUE, once per key" % field)
        out[key] = value
    return out


def slot_key(key: str) -> str:
    """A beat number is read as the slot id `beat<N>` the alignment gives it."""
    return "beat%s" % key if key.isdigit() else key


# ---------------------------------------------------------------- verbs

def verb_analyse(args) -> dict:
    ffmpeg, ffprobe = tools(args)
    data = load_data()
    facts = _media.probe(ffprobe, args.input)
    if facts["duration"] > data["limits"]["input_seconds_max"]:
        raise Refusal("input_too_long", "input")
    facts["sha256"] = _media.sha256_file(args.input)
    silences = _media.silencedetect(ffmpeg, args.input, facts["duration"], args.noise_db, args.min_silence) if facts["has_audio"] else None
    doc = {"schema_version": 1, "facts": facts, "silences": silences, "noise_db": args.noise_db, "min_silence": args.min_silence}
    if args.out:
        write_json(args.out, doc)
        return {"ok": True, "out": os.path.abspath(args.out), "duration": facts["duration"], "sha256": facts["sha256"],
                "silences": None if silences is None else len(silences), "has_audio": facts["has_audio"]}
    return dict(doc, ok=True)


def verb_base(args) -> dict:
    data = load_data()
    limits = data["limits"]
    transcript = read_json(args.transcript, limits["json_max_bytes"])
    analysis = read_json(args.analysis, limits["json_max_bytes"])
    allow = _assets.font_allowlist()
    colors = pairs(args.color, "--color")
    font_flags = {}
    for role, spec in pairs(args.font, "--font").items():
        font_id, _, weight = spec.partition(":")
        font_flags[role] = (font_id, int(weight) if weight.isdigit() else data["theme"]["default_font_weight"].get(role, 500))
    face = _edl.parse_face_box(args.face_box) if args.face_box else None
    advice = []
    edl, notes = _edl.build_base(transcript, analysis, data, allow, args.fps, args.gap, args.pad_head, args.pad_tail, args.caption_position,
                                 colors, font_flags, face, args.zoom, args.zoom_factor, args.push_in, set(args.confirm or []),
                                 args.long_cut, args.wordless_max, args.zoom_anchor_y, set(args.keep or []), args.retakes, advice)
    write_json(args.out, edl)
    return {**({"advice": _advice.rows(advice)} if advice else {}), "ok": True, "out": os.path.abspath(args.out), "fps": edl["fps"], "kept_ranges": len(edl["kept"]),
            "out_seconds": round(edl["out_frames"] / edl["fps"], 3), "source_seconds": edl["source"]["duration"],
            "words": len(edl["words"]), "caption_chunks": len(edl["captions"]["chunks"]), "normalisation": edl["normalisation"],
            "font_fallbacks": notes, "proposals": [{"id": p["id"], "kind": p["kind"], "seconds": p["seconds"], "confirmed": p["confirmed"], "default": p["default"], "reason": p["reason"]}
                          for p in edl["proposals"]],
            "face_box": edl["face_box"], "zoom": edl["zoom"]}


def verb_align(args) -> dict:
    data = load_data()
    limits = data["limits"]
    vocab = load_vocabulary(args.vocabulary)
    try:
        with open(args.post, "r", encoding="utf-8") as fh:
            text = fh.read(2 * 1024 * 1024)
    except (OSError, UnicodeDecodeError):
        raise Refusal("unreadable_file", "post") from None
    fmt = _align.post_format(text)
    if fmt not in _align.VIDEO_FORMATS:
        raise Refusal("post_format", "post")
    _align.run_checker(args.checker, args.post, args.vocabulary, fmt)       # refuses a post it does not pass
    header, rows = _align.read_script(text, vocab)
    tr = _timeline.check_transcript(read_json(args.transcript, limits["json_max_bytes"]), limits)
    words, _ = _timeline.normalise_words(tr["words"], tr["segments"], tr["duration"])
    live = [w for w in words if not w["dropped"]]
    if args.edl:
        edl_words = {w["index"] for w in read_json(args.edl, limits["json_max_bytes"])["words"]}
        live = [w for w in live if w["index"] in edl_words]
    with_preset = [r for r in rows if r["preset"]]
    results = _align.align_beats(live, with_preset, args.threshold)
    live_indices = {w["index"] for w in live}
    for beat, span in pairs(args.anchor, "--anchor").items():
        lo, sep, hi = span.partition("-")
        if not beat.isdigit() or not (sep and lo.isdigit() and hi.isdigit()) or int(lo) > int(hi) or not {int(lo), int(hi)} <= live_indices:
            raise Usage("--anchor takes BEAT=WORD_FROM-WORD_TO, two live word indices")
        target = [k for k, r in enumerate(with_preset) if r["beat"] == int(beat)]
        if not target:
            raise Usage("--anchor names a beat that has no preset")
        results[target[0]] = {"score": 1.0, "word_from": int(lo), "word_to": int(hi), "matched": True, "reordered": False, "anchored": True}
    empty = {slot_key(k): v for k, v in pairs(args.empty_slot, "--empty-slot").items()}
    if any(v not in ("keyword", "none") for v in empty.values()):
        raise Usage("--empty-slot takes SLOT=keyword or SLOT=none")
    beats = _align.build_beats(with_preset, results, vocab, args.threshold, empty)
    beats["report"] = sorted(beats["report"] + [{"beat": r["beat"], "preset": None} for r in rows if not r["preset"]],
                             key=lambda x: x["beat"])
    punches, missed = punch_rows(rows, with_preset, results, live, args.threshold)
    if punches:
        beats["punches"] = punches        # only when the script has a matched punch: a post without one gives the file it always gave
    if missed:
        beats["unmatched"] = sorted(set(beats["unmatched"]) | set(missed))
    _align.annotate(beats, rows, header)
    write_json(args.out, beats)
    done = {"ok": True, "out": os.path.abspath(args.out), "beats": len(rows), "overlays": len(beats["overlays"]),
            "layouts": len(beats["layouts"]), "unmatched": beats["unmatched"], "slots": [s["slot"] for s in beats["slots"]],
            "fallbacks": beats["fallbacks"], "scores": {str(r["beat"]): r["score"] for r in beats["report"] if "score" in r},
            "reordered": [r["beat"] for r in beats["report"] if r.get("reordered")]}
    if punches or missed:
        done["punches"] = len(punches)
    return done


def punch_rows(rows: list, with_preset: list, results: list, live: list, threshold: float) -> tuple:
    """(punches, missed): the script's punches (a beat whose `emphasis` is `punch`) as beats.json rows {beat, word_from, word_to, score}, and the
    numbers of the punch beats with no preset that matched no words. A punch beat with a preset reuses the alignment of that beat (an anchor included);
    one with no preset is aligned by `_align.align_beats` with the same threshold, apart from the beats that have a preset, so no preset beat's
    result moves. A punch beat with a preset that did not match is already in the beats' own `unmatched`."""
    bare = [r for r in rows if r["emphasis"] == "punch" and not r["preset"]]
    found = dict(zip((id(r) for r in bare), _align.align_beats(live, bare, threshold))) if bare else {}
    found.update({id(r): res for r, res in zip(with_preset, results) if r["emphasis"] == "punch"})
    punches, missed = [], []
    for r in rows:
        res = found.get(id(r))
        if res is None:
            continue
        if res["matched"]:
            punches.append({"beat": r["beat"], "word_from": res["word_from"], "word_to": res["word_to"], "score": res["score"]})
        elif not r["preset"]:
            missed.append(r["beat"])
    return punches, missed


def verb_check_documents(args) -> dict:
    data = load_data()
    vocab = load_vocabulary(args.vocabulary)
    platform = _output.read_platform(args.platform_file) if args.platform_file else None
    edl = read_json(args.edl, data["limits"]["json_max_bytes"])
    beats = read_json(args.beats, data["limits"]["json_max_bytes"])
    allow = _assets.font_allowlist()
    first = _edl.check_edl(edl, data, vocab, allow, platform)
    second = _edl.check_beats(beats, edl, vocab)
    out = {"ok": True, "mentions": sorted(set(first["mentions"]) | set(second["mentions"])), "out_seconds": round(edl["out_frames"] / edl["fps"], 3),
           "words": len(edl["words"]), "overlays": len(beats["overlays"]), "layouts": len(beats["layouts"])}
    if first.get("advice") or second.get("advice"):
        out["advice"] = _advice.merge(first.get("advice"), second.get("advice"))
    return out


def browser_path(args) -> str:
    path = args.browser or os.environ.get("RENDERER_BROWSER")
    if not path or not os.access(path, os.X_OK):
        raise NotConfigured("browser_not_found", "browser")
    return path


def verb_render(args) -> dict:
    import _render        # the drawing part: imported only by the verbs that draw (a test holds that the others never load it)
    _output.read_platform(args.platform_file)           # inputs are checked before any tool is looked for
    ffmpeg, ffprobe = tools(args)
    browser = {"path": None} if args.dry_run else {"path": browser_path(args)}
    asset_files = {slot_key(k): v for k, v in pairs(args.asset, "--asset").items()}
    asset_hashes = {slot_key(k): v for k, v in pairs(args.asset_sha256, "--asset-sha256").items()}
    if (args.cover_out is None) != (args.cover_offset_ms is None):
        raise Usage("--cover-out and --cover-offset-ms go together")
    if (args.vendor or args.hf_registry) and os.environ.get("RENDERER_TEST") != "1":
        raise Usage("--vendor and --hf-registry are for the tests: the image's folders are the only ones a render reads")
    return _render.render(edl_path=args.edl, beats_path=args.beats, src=args.input, out=args.out, platform_path=args.platform_file,
                          vocabulary_path=args.vocabulary, asset_files=asset_files, asset_sha256s=asset_hashes, ffmpeg=ffmpeg,
                          ffprobe=ffprobe, browser=browser, jobs=args.jobs, dry_run=args.dry_run, time_limit=args.time_limit,
                          cover_out=args.cover_out, cover_offset_ms=args.cover_offset_ms, scratch=args.scratch,
                          blocks_dir=args.blocks, blocks_sha256=args.blocks_sha256, vendor=args.vendor, hf_registry=args.hf_registry)


def verb_storyboard(args) -> dict:
    """A still per beat and a contact sheet from a post (`--post`, checked by the post-writing skill's own checker) or from one beat as
    JSON (`--beat`). No recording and no transcript: the words are synthetic (_preview). Everything is refused before a frame is drawn."""
    import _preview       # the drawing part, imported only here
    data = load_data()
    vocab = load_vocabulary(args.vocabulary)
    allow = _assets.font_allowlist()
    if bool(args.post) == bool(args.beat) or bool(args.post) != bool(args.checker):
        raise Usage("storyboard takes --post FILE with --checker SCRIPT, or --beat FILE, not both")
    if args.post:
        try:
            with open(args.post, "r", encoding="utf-8") as fh:
                text = fh.read(2 * 1024 * 1024)
        except (OSError, UnicodeDecodeError):
            raise Refusal("unreadable_file", "post") from None
        fmt = _align.post_format(text)
        if fmt not in _align.VIDEO_FORMATS:
            raise Refusal("post_format", "post")
        _align.run_checker(args.checker, args.post, args.vocabulary, fmt)      # refuses a post it does not pass
        rows = _align.read_beats(text, vocab)
    else:
        rows = [_preview.beat_row(vocab, read_json(args.beat, data["limits"]["json_max_bytes"]))]
    font_flags = {}
    for role, spec in pairs(args.font, "--font").items():
        font_id, _, weight = spec.partition(":")
        font_flags[role] = (font_id, int(weight) if weight.isdigit() else data["theme"]["default_font_weight"].get(role, 500))
    face = _edl.parse_face_box(args.face_box) if args.face_box else None
    return _preview.storyboard(rows=rows, data=data, vocab=vocab, allow=allow, colors=pairs(args.color, "--color"), font_flags=font_flags, face=face,
                               tools=lambda: (tools(args)[0], browser_path(args)), jobs=args.jobs, out_dir=args.out, scratch=args.scratch,
                               blocks_dir=args.blocks, blocks_sha256=args.blocks_sha256)


def verb_admit_check(args) -> dict:
    """The determinism test of a candidate block of the second contract (PF-a3). The entry is the host's, files already hashed and edited on its side;
    this verb checks them again (the host page refuses a file that is not the pinned one) and measures. It reads no recording and no transcript."""
    import _admit_check   # the drawing part: imported only by this verb
    if args.vendor and os.environ.get("RENDERER_TEST") != "1":
        raise Usage("--vendor is for the tests: the image's folder is the only one a measurement reads")
    if args.port and (args.entry or args.component_dir):
        raise Usage("--port is exclusive with --entry and --component-dir")
    if not args.port and (not args.entry or not args.component_dir):
        raise Usage("admit-check needs --entry and --component-dir, or --port")
    ffmpeg, _ffprobe = tools(args)   # after every usage check: a usage error is never reported as a missing tool
    if args.port:
        return _admit_check.admit_port_check(port=args.port, vocabulary=args.vocabulary, blocks=args.blocks, blocks_sha256=args.blocks_sha256,
                                             scratch=args.scratch or tempfile.gettempdir(), browser=browser_path(args), ffmpeg=ffmpeg, vendor=args.vendor,
                                             jobs=max(1, min(args.jobs, 8)), time_limit=args.time_limit)
    entry = read_json(args.entry, 1 << 20)
    if not isinstance(entry, dict) or not isinstance(entry.get("samples"), list) or not isinstance(entry.get("files"), dict) \
            or not isinstance(entry.get("served_sha256"), str):
        raise Refusal("admit_entry", "entry")
    return _admit_check.admit_check(entry=entry, component_dir=args.component_dir, vocabulary=args.vocabulary, blocks=args.blocks,
                                    blocks_sha256=args.blocks_sha256, scratch=args.scratch or tempfile.gettempdir(), browser=browser_path(args), ffmpeg=ffmpeg,
                                    vendor=args.vendor, jobs=max(1, min(args.jobs, 8)), time_limit=args.time_limit)


def verb_asset_sheet(args) -> dict:
    """The pictures of `--asset ROW:COL=FILE` checked and tiled onto `sheet.png` in `--out`; with `--mode full` each is also normalised to
    `asset-<sha12>.png` (`_asset_sheet`). The host checks the answer again."""
    ffmpeg, ffprobe = tools(args)
    return _asset_sheet.asset_sheet(items=pairs(args.asset, "--asset"), mode=args.mode, out_dir=args.out, ffmpeg=ffmpeg, ffprobe=ffprobe, fps=args.fps)


def verb_cover(args) -> dict:
    ffmpeg, ffprobe = tools(args)
    facts = _media.probe(ffprobe, args.input)
    return dict(_output.make_cover(ffmpeg, args.input, args.out, args.offset_ms, facts["duration"]), ok=True)


def verb_still(args) -> dict:
    ffmpeg, ffprobe = tools(args)
    data = load_data()
    facts = _media.probe(ffprobe, args.input)
    if facts["duration"] > data["limits"]["input_seconds_max"]:
        raise Refusal("input_too_long", "input")
    frame = data["frame"]
    return dict(_output.make_still(ffmpeg, args.input, args.out, args.at_ms, facts, (frame["width"], frame["height"])), ok=True)


def verb_verify(args) -> dict:
    """Check a finished render, from outside the container that made it: its sha256 is the one the render reported, and ffprobe
    finds it inside the platform file's video spec (container, codec, audio codec, size, fps range, duration, bytes, faststart),
    tagged bt709 limited range, and as long as the edit list says."""
    platform = _output.read_platform(args.platform_file)
    ffmpeg, ffprobe = tools(args)
    if _media.sha256_file(args.input) != args.sha256:
        raise Refusal("render_differs", "render")
    verdict = _media.check_output(ffprobe, args.input, platform)
    failures = list(verdict["failures"])
    facts = verdict["facts"]
    if facts and facts.get("color") != ["bt709", "bt709", "bt709", "tv"]:
        failures.append("color_tags")
    if facts and args.expect_seconds is not None and abs(facts["duration"] - args.expect_seconds) > 0.3:
        failures.append("duration_mismatch")
    if failures:
        raise Refusal("platform_spec", ",".join(failures))
    return {"ok": True, "sha256": args.sha256, "output": facts}


def verb_preview(args) -> dict:
    """A smaller copy of a finished render for a phone (renderer-presets.json `preview`): the render is the file the host named by its
    sha256 and at most the input limit long; the copy is spec width x height, at most spec max_bytes, as long as the render within
    spec duration_tolerance_seconds, with audio exactly when the render has it, and its index first. Written to --out (0600). Refusals:
    `render_differs`, `render_too_long`, `preview_too_long`, `preview_too_large`, `preview_mismatch`."""
    ffmpeg, ffprobe = tools(args)
    data = load_data()
    spec = data["preview"]
    started = time.time()
    if _media.sha256_file(args.input) != args.sha256:
        raise Refusal("render_differs", "render")
    facts = _media.probe(ffprobe, args.input)
    if facts["duration"] > data["limits"]["input_seconds_max"] + 1:
        raise Refusal("render_too_long", "render")
    video_kbps = _media.preview_rate(facts["duration"], spec, facts["has_audio"])
    if video_kbps is None:
        raise Refusal("preview_too_long", "render")
    out = os.path.abspath(args.out)
    folder = os.path.dirname(out)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".preview-", dir=folder)
    try:
        part = os.path.join(work, "preview.mp4")
        _media.run(_media.preview_argv(ffmpeg, args.input, part, spec, video_kbps=video_kbps, has_audio=facts["has_audio"]), spec["encode_seconds"])
        size = os.path.getsize(part)
        if size > spec["max_bytes"]:
            raise Refusal("preview_too_large", "preview")
        made = _media.probe(ffprobe, part)
        if (made["width"], made["height"]) != (spec["width"], spec["height"]) or made["has_audio"] != facts["has_audio"] \
                or abs(made["duration"] - facts["duration"]) > spec["duration_tolerance_seconds"] or not _media.faststart(part):
            raise Refusal("preview_mismatch", "preview")
        digest = _media.sha256_file(part)
        os.chmod(part, 0o600)
        os.replace(part, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, "sha256": digest, "from_sha256": args.sha256, "bytes": size, "width": made["width"], "height": made["height"],
            "duration": made["duration"], "has_audio": made["has_audio"], "video_kbps": video_kbps,
            "audio_kbps": spec["audio_kbps"] if facts["has_audio"] else 0, "seconds": round(time.time() - started, 2)}


def verb_selfcheck(args) -> dict:
    """The versions of what this environment holds, and that each tool starts. The host's --check runs it in the container."""
    ffmpeg, ffprobe = tools(args)
    enc_out, _ = _media.run([ffmpeg, "-hide_banner", "-encoders"], 30)
    missing = [e for e in REQUIRED_ENCODERS if (" %s " % e) not in enc_out]
    missing += [f for f in REQUIRED_FILTERS if not _media.has_filter(ffmpeg, f)]
    import _cdp           # the drawing part: selfcheck reports what the drawing engine holds, so it loads it here and nowhere else
    path = browser_path(args)
    out = {"ok": not missing, "ffmpeg": _media.tool_version(ffmpeg), "ffprobe": _media.tool_version(ffprobe), "missing": missing,
           "python": sys.version.split()[0], "browser": _browser_version(path),
           "libass": _media.has_filter(ffmpeg, "subtitles") or _media.has_filter(ffmpeg, "ass"),
           "container": _cdp.container_mode()}
    if missing:
        raise NotConfigured("not_ready", ",".join(missing))
    explicit = getattr(args, "vendor", None) or getattr(args, "hf_registry", None)
    if _cdp.container_mode() or explicit:      # the image holds the runtime; a host that was not asked to look does not have it
        out["hf_runtime"] = check_hf_runtime(HERE, getattr(args, "vendor", None) or os.path.join(HERE, "vendor"),
                                             getattr(args, "hf_registry", None) or os.path.join(HERE, "hf-registry"))
    return out


def _sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def check_hf_runtime(here: str, vendor: str, registry: str) -> dict:
    """The HyperFrames runtime and GSAP the image fetched at build (`hf-runtime/fetch_hf.py`), read again and compared with the pins: the three
    vendor files against `hf-runtime/npm-pins.json`, every file of the registry folder against `hf-runtime/registry.sha256`, and the five shims
    against `hf-runtime/shims/SHA256SUMS`. A missing, extra or different file is `vendor_hash`; nothing is repaired. Returns the counts."""
    base = os.path.join(here, "hf-runtime")
    pins = read_json(os.path.join(base, "npm-pins.json"))
    wanted = {}      # {base name: sha256} of the vendor folder
    for pkg in pins["packages"]:
        for member, digest in pkg["files"].items():
            wanted[os.path.basename(member)] = digest
    rows = {}
    with open(os.path.join(base, "registry.sha256"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                digest, name = line.split(None, 1)
                rows[name.strip()] = digest
    shims = {}
    with open(os.path.join(base, "shims", "SHA256SUMS"), encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                digest, name = line.split(None, 1)
                shims[name.strip()] = digest

    def compare(folder: str, expected: dict, label: str) -> None:
        found = {}
        for root, _, names in os.walk(folder):
            for name in names:
                found[os.path.relpath(os.path.join(root, name), folder)] = os.path.join(root, name)
        for name in sorted(set(found) | set(expected)):
            if name not in found or name not in expected or _sha256_file(found[name]) != expected[name]:
                raise Refusal("vendor_hash", "%s/%s" % (label, name)[:80])
    compare(vendor, wanted, "vendor")
    compare(registry, rows, "hf-registry")
    compare(os.path.join(base, "shims"), dict(shims, **{"SHA256SUMS": _sha256_file(os.path.join(base, "shims", "SHA256SUMS"))}), "shims")
    return {"vendor": len(wanted), "registry": len(rows), "shims": len(shims)}


def _browser_version(path: str) -> str:
    try:
        out, _ = _media.run([path, "--version"], 30)
    except Refusal:
        return "unknown"
    return out.strip() or "unknown"


# ---------------------------------------------------------------- command line

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb")

    p.add_argument("--result", help="write the result object to this file instead of stdout")

    def common(sp, browser=False):
        sp.add_argument("--ffmpeg", help="ffmpeg executable (default: on PATH)")
        sp.add_argument("--ffprobe", help="ffprobe executable (default: on PATH)")
        if browser:
            sp.add_argument("--browser", help="a browser executable (default: RENDERER_BROWSER)")

    sp = sub.add_parser("selfcheck")
    common(sp, browser=True)
    sp.add_argument("--vendor", help="the folder of the HyperFrames runtime and GSAP to check (default: /opt/renderer/vendor in the image; the tests)")
    sp.add_argument("--hf-registry", help="the folder of the registry files to check (default: /opt/renderer/hf-registry in the image; the tests)")
    sp = sub.add_parser("analyse")
    common(sp)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--out")
    sp.add_argument("--noise-db", type=float, default=load_data()["cuts"]["noise_db"])
    sp.add_argument("--min-silence", type=float, default=load_data()["cuts"]["min_silence"])
    sp = sub.add_parser("base")
    sp.add_argument("--transcript", required=True)
    sp.add_argument("--analysis", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--fps", type=int)
    sp.add_argument("--gap", type=float, help="no audio: cut word gaps longer than this (seconds)")
    sp.add_argument("--pad-head", type=float, help="seconds of speech kept before the first word after a silence (default 0.10)")
    sp.add_argument("--pad-tail", type=float, help="seconds of speech kept after the last word before a silence (default 0.14)")
    sp.add_argument("--long-cut", type=float, help="a cut this long (seconds) also takes the wordless sound at its edges")
    sp.add_argument("--wordless-max", type=float, help="seconds of sound with no word that a long cut does not leave at an edge")
    sp.add_argument("--caption-position", default="bottom")
    sp.add_argument("--face-box", help="X,Y,W,H in frame pixels (1080x1920): where the speaker's face is; given once per recording")
    sp.add_argument("--zoom", choices=("alternate", "none"))
    sp.add_argument("--zoom-factor", type=float)
    sp.add_argument("--push-in", type=float, help="slow extra zoom over each range of 5 s or more, as a fraction, 0 for none (default 0.02)")
    sp.add_argument("--zoom-anchor-y", type=float, help="the zoom's fixed point: this fraction of the face box's height down from its top (default 0.25)")
    sp.add_argument("--confirm", action="append", metavar="RETAKE-ID", help="cut this proposed retake (repeatable)")
    sp.add_argument("--keep", action="append", metavar="RETAKE-ID", help="keep this proposed retake that the rule would cut (repeatable)")
    sp.add_argument("--retakes", choices=("auto", "propose"), default="auto", help="auto: cut the proposals the rule says to cut; propose: cut only --confirm")
    sp.add_argument("--color", action="append", metavar="TOKEN=#RRGGBB")
    sp.add_argument("--font", action="append", metavar="ROLE=ID[:WEIGHT]")
    sp = sub.add_parser("align")
    sp.add_argument("--post", required=True)
    sp.add_argument("--transcript", required=True)
    sp.add_argument("--checker", required=True, help="the post-writing skill's script checker (check_script.py)")
    sp.add_argument("--vocabulary", required=True, help="shared/references/video-presets.json")
    sp.add_argument("--out", required=True)
    sp.add_argument("--threshold", type=float, default=_align.DEFAULT_THRESHOLD)
    sp.add_argument("--empty-slot", action="append", metavar="SLOT=keyword|none")
    sp.add_argument("--anchor", action="append", metavar="BEAT=WORD_FROM-WORD_TO")
    sp.add_argument("--edl", help="the edit list whose confirmed retakes are left out of the alignment")
    sp = sub.add_parser("check")
    sp.add_argument("--edl", required=True)
    sp.add_argument("--beats", required=True)
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--platform-file")
    sp = sub.add_parser("render")
    common(sp, browser=True)
    sp.add_argument("--edl", required=True)
    sp.add_argument("--beats", required=True)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--out", required=True)
    sp.add_argument("--platform-file", required=True)
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--asset", action="append", metavar="SLOT=FILE")
    sp.add_argument("--asset-sha256", action="append", metavar="SLOT=HEX")
    sp.add_argument("--jobs", type=int, default=3)
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--time-limit", type=int)
    sp.add_argument("--cover-out")
    sp.add_argument("--cover-offset-ms", type=int)
    sp.add_argument("--scratch", help="where the frames and work files go (memory-backed in the container)")
    sp.add_argument("--blocks", default=_blocks.BLOCKS_DIR, help="the staged blocks folder (default: the one next to this file)")
    sp.add_argument("--blocks-sha256", help="the sha256 of the staged pins.json, computed by the host on its copy")
    sp.add_argument("--vendor", help="the folder of the runtime and GSAP of an admitted block (the image's; another folder only when RENDERER_TEST=1)")
    sp.add_argument("--hf-registry", help="the folder of the registry files of an admitted block (the image's; another folder only when RENDERER_TEST=1)")
    sp = sub.add_parser("admit-check")
    common(sp, browser=True)
    sp.add_argument("--entry", help="the candidate allowlist entry as JSON, with `samples` and `served_sha256`, no `determinism`")
    sp.add_argument("--component-dir", help="the folder holding the component's files, named as the entry's `files`")
    sp.add_argument("--port", help="one of our own tier-B ports, hf:<name>, read from the staged blocks by its pin (instead of --entry and --component-dir)")
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--blocks", required=True, help="the staged blocks folder")
    sp.add_argument("--blocks-sha256", required=True, help="the sha256 of the staged pins.json, computed by the host on its copy")
    sp.add_argument("--scratch", help="where the work files go (memory-backed in the container)")
    sp.add_argument("--jobs", type=int, default=3)
    sp.add_argument("--time-limit", type=int, default=900)
    sp.add_argument("--vendor", help="the folder of the runtime and GSAP (the image's; another folder only when RENDERER_TEST=1)")
    sp = sub.add_parser("storyboard")
    common(sp, browser=True)
    sp.add_argument("--post")
    sp.add_argument("--checker", help="the post-writing skill's script checker (check_script.py), with --post")
    sp.add_argument("--beat", help="one beat as JSON: {preset, params, line}")
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--out", required=True, help="the folder that gets beat-<n>.png and sheet.png")
    sp.add_argument("--scratch", help="where the work files go (memory-backed in the container)")
    sp.add_argument("--blocks", default=_blocks.BLOCKS_DIR, help="the staged blocks folder (default: the one next to this file)")
    sp.add_argument("--blocks-sha256", help="the sha256 of the staged pins.json, computed by the host on its copy")
    sp.add_argument("--jobs", type=int, default=3)
    sp.add_argument("--face-box", help="X,Y,W,H in frame pixels (1080x1920); the default face box otherwise")
    sp.add_argument("--color", action="append", metavar="TOKEN=#RRGGBB")
    sp.add_argument("--font", action="append", metavar="ROLE=ID[:WEIGHT]")
    sp = sub.add_parser("verify")
    common(sp)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--platform-file", required=True)
    sp.add_argument("--sha256", required=True)
    sp.add_argument("--expect-seconds", type=float)
    sp = sub.add_parser("preview")
    common(sp)
    sp.add_argument("--in", dest="input", required=True, help="the finished render (an MP4)")
    sp.add_argument("--sha256", required=True, help="the render's sha256, as the host hashed it")
    sp.add_argument("--out", required=True, help="the preview file (.mp4), inside the writable folder")
    sp = sub.add_parser("asset-sheet")
    common(sp)
    sp.add_argument("--asset", action="append", metavar="ROW:COL=FILE")
    sp.add_argument("--mode", required=True, choices=("preview", "full"))
    sp.add_argument("--fps", default=str(_media.CLIP_FPS_DEFAULT), help="the constant frame rate a clip is written at in full mode, 24 to 60")
    sp.add_argument("--out", required=True, help="the folder that gets sheet.png and, in full mode, asset-<sha12>.png (or .mp4 for a clip)")
    sp = sub.add_parser("cover")
    common(sp)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--offset-ms", type=int, required=True)
    sp.add_argument("--out", required=True)
    sp = sub.add_parser("still")
    common(sp)
    sp.add_argument("--in", dest="input", required=True)
    sp.add_argument("--at-ms", type=int, required=True)
    sp.add_argument("--out", required=True)
    return p


VERBS = {"verify": verb_verify, "selfcheck": verb_selfcheck, "analyse": verb_analyse, "base": verb_base, "align": verb_align, "check": verb_check_documents,
         "render": verb_render, "storyboard": verb_storyboard, "cover": verb_cover, "still": verb_still,
         "preview": verb_preview, "asset-sheet": verb_asset_sheet,
         "admit-check": verb_admit_check}


def write_result(path, obj) -> None:
    if path:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
            fh.write("\n")
    else:
        emit(obj)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    result_path = None
    try:
        args = parser().parse_args(argv)
        result_path = args.result
        if args.verb is None:
            parser().print_help(sys.stderr)
            return EXIT_USAGE
        write_result(result_path, VERBS[args.verb](args))
        return EXIT_OK
    except SystemExit as err:                 # argparse's own usage error
        return EXIT_USAGE if err.code else EXIT_OK
    except Usage as err:
        print("usage: %s" % err, file=sys.stderr)
        return EXIT_USAGE
    except Refusal as err:
        print("refused: %s %s" % (err.code, err.field), file=sys.stderr)
        for p in getattr(err, "problems", []):
            print("  beat %s %s %s" % (p.get("beat"), p.get("field"), p.get("code")), file=sys.stderr)
        if os.environ.get("RENDERER_DEBUG") == "1":
            print("  detail: %s" % (getattr(err, "tail", "") or getattr(err, "detail", "")), file=sys.stderr)
        out = {"ok": False, "code": err.code, "field": err.field, "problems": getattr(err, "problems", [])}
        if getattr(err, "reason", ""):
            out["reason"] = err.reason
            print("  reason: %s" % err.reason, file=sys.stderr)
        write_result(result_path, out)
        return EXIT_NOT_CONFIGURED if isinstance(err, NotConfigured) else EXIT_FAILED
    except Exception:                       # anything not foreseen: a closed code, never a traceback (it could carry a word of the transcript)
        print("refused: internal", file=sys.stderr)
        try:
            write_result(result_path, {"ok": False, "code": "internal", "field": "", "problems": []})
        except OSError:
            pass
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
