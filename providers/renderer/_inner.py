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
  cover    --in MP4 --offset-ms N --out PNG                  one frame of a render
  still    --in VIDEO --at-ms N --out PNG                    one frame of a recording, framed as the render frames it (1080x1920)
  selfcheck                                  the versions of what the image holds, and that each tool starts

Every verb writes its result as one JSON object to `--result FILE` (before the verb; stdout when absent): the same object the
host prints. A refusal is {"ok": false, "code", "field", "problems"} and exit code 1 (3 for something not installed, 2 for a
usage error). The text of an input is never put in a result. The browser is the executable named by RENDERER_BROWSER (the
image sets it) or by --browser (the tests). Its own sandbox is on, except inside the image, where the container is the
boundary (_cdp.container_mode): the result says which (`browser_sandbox`).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import _align  # noqa: E402
import _cdp  # noqa: E402
import _edl  # noqa: E402
import _frames  # noqa: E402
import _media  # noqa: E402
import _preview  # noqa: E402
import _render  # noqa: E402
import _timeline  # noqa: E402
from _text import Refusal  # noqa: E402
from _vocab import SLOT_ID, load_data, load_vocabulary, read_json  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
REQUIRED_ENCODERS = ("libx264", "aac", "png")
REQUIRED_FILTERS = ("overlay", "alphamerge", "geq", "setparams", "concat", "trim", "atrim", "split", "scale", "crop", "fps",
                    "silencedetect", "aformat")


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
    allow = _frames.font_allowlist()
    colors = pairs(args.color, "--color")
    font_flags = {}
    for role, spec in pairs(args.font, "--font").items():
        font_id, _, weight = spec.partition(":")
        font_flags[role] = (font_id, int(weight) if weight.isdigit() else data["theme"]["default_font_weight"].get(role, 500))
    face = _edl.parse_face_box(args.face_box) if args.face_box else None
    edl, notes = _edl.build_base(transcript, analysis, data, allow, args.fps, args.gap, args.pad_head, args.pad_tail, args.caption_position,
                                 colors, font_flags, face, args.zoom, args.zoom_factor, args.push_in, set(args.confirm or []),
                                 args.long_cut, args.wordless_max, args.zoom_anchor_y)
    write_json(args.out, edl)
    return {"ok": True, "out": os.path.abspath(args.out), "fps": edl["fps"], "kept_ranges": len(edl["kept"]),
            "out_seconds": round(edl["out_frames"] / edl["fps"], 3), "source_seconds": edl["source"]["duration"],
            "words": len(edl["words"]), "caption_chunks": len(edl["captions"]["chunks"]), "normalisation": edl["normalisation"],
            "font_fallbacks": notes, "proposals": [{"id": p["id"], "kind": p["kind"], "seconds": p["seconds"], "confirmed": p["confirmed"]} for p in edl["proposals"]],
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
    _align.annotate(beats, rows, header)
    write_json(args.out, beats)
    return {"ok": True, "out": os.path.abspath(args.out), "beats": len(rows), "overlays": len(beats["overlays"]),
            "layouts": len(beats["layouts"]), "unmatched": beats["unmatched"], "slots": [s["slot"] for s in beats["slots"]],
            "fallbacks": beats["fallbacks"], "scores": {str(r["beat"]): r["score"] for r in beats["report"] if "score" in r},
            "reordered": [r["beat"] for r in beats["report"] if r.get("reordered")]}


def verb_check_documents(args) -> dict:
    data = load_data()
    vocab = load_vocabulary(args.vocabulary)
    platform = _render.read_platform(args.platform_file) if args.platform_file else None
    edl = read_json(args.edl, data["limits"]["json_max_bytes"])
    beats = read_json(args.beats, data["limits"]["json_max_bytes"])
    allow = _frames.font_allowlist()
    first = _edl.check_edl(edl, data, vocab, allow, platform)
    second = _edl.check_beats(beats, edl, vocab)
    return {"ok": True, "mentions": sorted(set(first["mentions"]) | set(second["mentions"])), "out_seconds": round(edl["out_frames"] / edl["fps"], 3),
            "words": len(edl["words"]), "overlays": len(beats["overlays"]), "layouts": len(beats["layouts"])}


def browser_path(args) -> str:
    path = args.browser or os.environ.get("RENDERER_BROWSER")
    if not path or not os.access(path, os.X_OK):
        raise NotConfigured("browser_not_found", "browser")
    return path


def verb_render(args) -> dict:
    _render.read_platform(args.platform_file)           # inputs are checked before any tool is looked for
    ffmpeg, ffprobe = tools(args)
    browser = {"path": None} if args.dry_run else {"path": browser_path(args)}
    asset_files = {slot_key(k): v for k, v in pairs(args.asset, "--asset").items()}
    asset_hashes = {slot_key(k): v for k, v in pairs(args.asset_sha256, "--asset-sha256").items()}
    if (args.cover_out is None) != (args.cover_offset_ms is None):
        raise Usage("--cover-out and --cover-offset-ms go together")
    return _render.render(edl_path=args.edl, beats_path=args.beats, src=args.input, out=args.out, platform_path=args.platform_file,
                          vocabulary_path=args.vocabulary, asset_files=asset_files, asset_sha256s=asset_hashes, ffmpeg=ffmpeg,
                          ffprobe=ffprobe, browser=browser, jobs=args.jobs, dry_run=args.dry_run, time_limit=args.time_limit,
                          cover_out=args.cover_out, cover_offset_ms=args.cover_offset_ms, scratch=args.scratch)


def verb_storyboard(args) -> dict:
    """A still per beat and a contact sheet from a post (`--post`, checked by the post-writing skill's own checker) or from one beat as
    JSON (`--beat`). No recording and no transcript: the words are synthetic (_preview). Everything is refused before a frame is drawn."""
    data = load_data()
    vocab = load_vocabulary(args.vocabulary)
    allow = _frames.font_allowlist()
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
                               tools=lambda: (tools(args)[0], browser_path(args)), jobs=args.jobs, out_dir=args.out, scratch=args.scratch)


def verb_cover(args) -> dict:
    ffmpeg, ffprobe = tools(args)
    facts = _media.probe(ffprobe, args.input)
    return dict(_render.make_cover(ffmpeg, args.input, args.out, args.offset_ms, facts["duration"]), ok=True)


def verb_still(args) -> dict:
    ffmpeg, ffprobe = tools(args)
    data = load_data()
    facts = _media.probe(ffprobe, args.input)
    if facts["duration"] > data["limits"]["input_seconds_max"]:
        raise Refusal("input_too_long", "input")
    frame = data["frame"]
    return dict(_render.make_still(ffmpeg, args.input, args.out, args.at_ms, facts, (frame["width"], frame["height"])), ok=True)


def verb_verify(args) -> dict:
    """Check a finished render, from outside the container that made it: its sha256 is the one the render reported, and ffprobe
    finds it inside the platform file's video spec (container, codec, audio codec, size, fps range, duration, bytes, faststart),
    tagged bt709 limited range, and as long as the edit list says."""
    platform = _render.read_platform(args.platform_file)
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


def verb_selfcheck(args) -> dict:
    """The versions of what this environment holds, and that each tool starts. The host's --check runs it in the container."""
    ffmpeg, ffprobe = tools(args)
    enc_out, _ = _media.run([ffmpeg, "-hide_banner", "-encoders"], 30)
    missing = [e for e in REQUIRED_ENCODERS if (" %s " % e) not in enc_out]
    missing += [f for f in REQUIRED_FILTERS if not _media.has_filter(ffmpeg, f)]
    path = browser_path(args)
    out = {"ok": not missing, "ffmpeg": _media.tool_version(ffmpeg), "ffprobe": _media.tool_version(ffprobe), "missing": missing,
           "python": sys.version.split()[0], "browser": _browser_version(path),
           "libass": _media.has_filter(ffmpeg, "subtitles") or _media.has_filter(ffmpeg, "ass"),
           "container": _cdp.container_mode(), "templates": sorted(_frames.template_pins())}
    if missing:
        raise NotConfigured("not_ready", ",".join(missing))
    return out


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
    sp.add_argument("--push-in", type=float, help="slow extra zoom over each range of 5 s or more, as a fraction up to 0.03 (default 0.02, 0 for none)")
    sp.add_argument("--zoom-anchor-y", type=float, help="the zoom's fixed point: this fraction of the face box's height down from its top (default 0.25)")
    sp.add_argument("--confirm", action="append", metavar="RETAKE-ID", help="cut this proposed retake (repeatable)")
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
    sp = sub.add_parser("storyboard")
    common(sp, browser=True)
    sp.add_argument("--post")
    sp.add_argument("--checker", help="the post-writing skill's script checker (check_script.py), with --post")
    sp.add_argument("--beat", help="one beat as JSON: {preset, params, line}")
    sp.add_argument("--vocabulary", required=True)
    sp.add_argument("--out", required=True, help="the folder that gets beat-<n>.png and sheet.png")
    sp.add_argument("--scratch", help="where the work files go (memory-backed in the container)")
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
         "render": verb_render, "storyboard": verb_storyboard, "cover": verb_cover, "still": verb_still}


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
