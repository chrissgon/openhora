"""The entry of the fetcher's container: `python3 -I _fetcher_inner.py [--result <file>] <verb> ...`. Four verbs, one per kind of container:

  fetch      run the pinned tool once, on an internal network whose only other member is the proxy; keep only what the host may
             take (`info.json` cut to a few fields, at most four subtitle files, one video) and write result.json;
  measure    no network: the facts of the reference mounted at /in (providers/fetcher/_measure.py) into /out/facts.json;
  proxy      the only container with a way out (providers/fetcher/_proxy.py);
  selfcheck  the versions of python, ffmpeg and the tool, and the filters ffmpeg has; run once by the image's build.

The tool's argument list is built here, by code, from a closed list of option names (ALLOWED) and from values this file checks; a final
check refuses any word that starts with `-` and is not in ALLOWED, so an option that gives the tool a credential, a config file, a program
to run or a place to write can never be passed, whatever a platform's fetch file says. Standard library only; written for Python 3.9.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TOOL = os.path.join(HERE, "yt-dlp")
VERSIONS = os.path.join(HERE, "versions.json")
ALLOWED = ("--ignore-config", "--no-playlist", "--no-cache-dir", "--no-mtime", "--restrict-filenames", "--no-color", "--use-extractors",
           "--proxy", "--socket-timeout", "--retries", "--match-filter", "--paths", "-o", "--skip-download", "--write-info-json",
           "--clean-info-json", "--write-subs", "--write-auto-subs", "--sub-format", "--sub-langs", "-S", "-f", "--max-filesize",
           "--print-to-file")
EXTRACTOR = re.compile(r"[A-Za-z0-9_]{1,40}")
LANG_PATTERN = re.compile(r"[A-Za-z0-9_.*-]{1,40}")
PROXY_URL = re.compile(r"http://openhora-fetch-proxy-[0-9a-f]{12}:8888")
SUBTITLE_FILE = re.compile(r"ref\.([A-Za-z]{2,3})(?:[-_.][A-Za-z0-9_-]+)?\.vtt")
VIDEO_EXTENSIONS = ("mp4", "webm", "mov")
INFO_KEYS = ("id", "extractor_key", "duration", "width", "height", "fps", "upload_date", "title", "description", "view_count", "like_count",
             "comment_count")
MAX_SUBTITLE_FILES, MAX_SUBTITLE_BYTES, MAX_INFO_BYTES = 4, 1 << 20, 1 << 20
TITLE_MAX, DESCRIPTION_MAX = 300, 2000
STAGES = ("meta", "video")
CODES = ("fetch_failed", "time_limit", "too_large", "measure_failed")
FILTERS = ("scdet", "vidstabdetect", "palettegen", "edgedetect", "blackdetect", "tblend", "signalstats")


class Refusal(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# --- the tool's argument list ---------------------------------------------------------------------------------------------------------


def check_extractors(extractors):
    if not isinstance(extractors, (list, tuple)) or not extractors or not all(isinstance(e, str) and EXTRACTOR.fullmatch(e) for e in extractors):
        raise Refusal("bad_extractors")
    return ",".join(extractors)


def check_langs(langs):
    if not isinstance(langs, (list, tuple)) or not all(isinstance(x, str) and LANG_PATTERN.fullmatch(x) and not x.startswith("-") for x in langs):
        raise Refusal("bad_langs")
    return ",".join(langs)


def ytdlp_argv(stage, url, extractors, proxy, max_seconds, max_bytes, langs):
    """The tool's arguments (without the program) for one stage. `langs` is a list of subtitle language patterns, [] for none."""
    if stage not in STAGES or not isinstance(url, str) or not url.startswith("https://") or not PROXY_URL.fullmatch(proxy or ""):
        raise Refusal("bad_arguments")
    if not all(isinstance(n, int) and not isinstance(n, bool) and n > 0 for n in (max_seconds, max_bytes)):
        raise Refusal("bad_arguments")
    # The meta stage only looks (a live stream is refused); the length is judged by the host, which tells the person what it read.
    match = "!is_live & duration <=? %d" % max_seconds if stage == "video" else "!is_live"
    argv = ["--ignore-config", "--no-playlist", "--no-cache-dir", "--no-mtime", "--restrict-filenames", "--no-color",
            "--use-extractors", check_extractors(extractors), "--proxy", proxy, "--socket-timeout", "30", "--retries", "2",
            "--match-filter", match, "--paths", "temp:/scratch", "-o", "/out/ref.%(ext)s"]
    if stage == "meta":
        argv += ["--skip-download", "--write-info-json", "--clean-info-json"]
        joined = check_langs(langs)
        if joined:
            argv += ["--write-subs", "--write-auto-subs", "--sub-format", "vtt", "--sub-langs", joined]
    else:
        argv += ["-S", "res:1280", "-f", "bv*[filesize<?%d]/b[filesize<?%d]" % (max_bytes, max_bytes), "--max-filesize", str(max_bytes)]
    argv.append(url)
    return check_argv(argv)


def check_argv(argv):
    """The final check: every word that starts with `-` is an option of ALLOWED. Returns the list or raises Refusal("option_refused")."""
    for word in argv:
        if not isinstance(word, str) or (word.startswith("-") and word not in ALLOWED):
            raise Refusal("option_refused")
    return list(argv)


# --- what the fetch leaves ------------------------------------------------------------------------------------------------------------


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def sanitise_info(raw, subtitles):
    """info.json: only INFO_KEYS (strings cut), plus `subtitles` (manual, auto or none); no URL, uploader or format list."""
    out = {}
    for key in INFO_KEYS:
        value = raw.get(key) if isinstance(raw, dict) else None
        if key in ("title", "description"):
            out[key] = value[:TITLE_MAX if key == "title" else DESCRIPTION_MAX] if isinstance(value, str) else ""
        elif key in ("id", "extractor_key", "upload_date"):
            out[key] = value[:80] if isinstance(value, str) else None
        else:
            out[key] = number(value)
    out["subtitles"] = subtitles
    return out


def read_info(path):
    try:
        if os.path.getsize(path) > 32 * MAX_INFO_BYTES:
            return {}
        with open(path, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def tidy(out_dir, stage, max_bytes):
    """Keep only the allowed files of /out, renamed; returns None when all is well or a code of CODES. Everything else is removed."""
    names = sorted(os.listdir(out_dir))
    kept_subtitles, seen = 0, set()
    manual = False
    info_raw = read_info(os.path.join(out_dir, "ref.info.json")) if "ref.info.json" in names else {}
    for name in names:
        path = os.path.join(out_dir, name)
        match = SUBTITLE_FILE.fullmatch(name)
        if stage == "meta" and match and os.path.isfile(path) and not os.path.islink(path):
            lang = match.group(1).lower()
            if lang not in seen and kept_subtitles < MAX_SUBTITLE_FILES and os.path.getsize(path) <= MAX_SUBTITLE_BYTES:
                os.rename(path, os.path.join(out_dir, "subs.%s.vtt" % lang))
                seen.add(lang)
                kept_subtitles += 1
                continue
        ext = name.rsplit(".", 1)[-1]
        if stage == "video" and name == "ref." + ext and ext in VIDEO_EXTENSIONS and os.path.isfile(path) and not os.path.islink(path):
            if os.path.getsize(path) > max_bytes:
                os.unlink(path)
                return "too_large"
            os.rename(path, os.path.join(out_dir, "video." + ext))
            continue
        if name in ("result.json",):
            continue
        if os.path.islink(path) or os.path.isfile(path):
            os.unlink(path)
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
    if stage == "meta":
        manual = bool(info_raw.get("subtitles")) if isinstance(info_raw.get("subtitles"), dict) else False
        state = "none" if kept_subtitles == 0 else ("manual" if manual else "auto")
        if info_raw:
            with open(os.path.join(out_dir, "info.json"), "w", encoding="utf-8") as f:
                json.dump(sanitise_info(info_raw, state), f)
    return None


def write_result(path, ok, code=None, exit_code=None):
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ok": bool(ok), "code": code, "exit": exit_code}, f)


def verb_fetch(args):
    argv = ytdlp_argv(args.stage, args.url, args.extractors.split(","), args.proxy_url, args.max_seconds, args.max_bytes,
                      [x for x in args.langs.split(",") if x])
    out_dir = os.path.dirname(args.result) if args.result else "/out"
    try:
        done = subprocess.run([sys.executable, "-I", TOOL] + argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        tidy(out_dir, args.stage, args.max_bytes)
        write_result(args.result, False, "time_limit", None)
        return 1
    problem = tidy(out_dir, args.stage, args.max_bytes)
    produced = os.listdir(out_dir)
    have = any(n.startswith("video.") for n in produced) if args.stage == "video" else "info.json" in produced
    if problem:
        write_result(args.result, False, problem, done.returncode)
        return 1
    if done.returncode != 0 or not have:
        write_result(args.result, False, "fetch_failed", done.returncode)
        return 1
    write_result(args.result, True, None, done.returncode)
    return 0


def verb_measure(args):
    import _measure
    try:
        versions = json.load(open(VERSIONS, encoding="utf-8")) if os.path.isfile(VERSIONS) else {}
        facts = _measure.build_facts(args.input, args.reference, args.platform, versions)
        with open(os.path.join(args.out, "facts.json"), "w", encoding="utf-8") as f:
            json.dump(facts, f, ensure_ascii=False)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        write_result(args.result, False, "measure_failed", None)
        return 1
    write_result(args.result, True, None, 0)
    return 0


def verb_proxy(args):
    import _proxy
    proxy = _proxy.Proxy(args.allow_host, args.allow_suffix, args.max_bytes, args.deadline, args.out, port=args.port)
    proxy.serve()
    return 0


def command_line(*argv):
    done = subprocess.run(list(argv), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    return (done.stdout or done.stderr or "").strip()


def verb_selfcheck(args):
    ffmpeg = command_line("ffmpeg", "-version").split("\n")[0]
    filters = command_line("ffmpeg", "-hide_banner", "-filters")
    have = {name: bool(re.search(r"\s%s\s" % name, filters)) for name in FILTERS}
    tool = command_line(sys.executable, "-I", TOOL, "--version").split("\n")[0]
    out = {"ok": bool(ffmpeg and tool), "python": sys.version.split()[0], "ffmpeg": ffmpeg, "ffprobe": command_line("ffprobe", "-version").split("\n")[0],
           "yt_dlp": tool, "filters": have}
    if args.expect_version and tool != args.expect_version:
        out["ok"] = False
    if args.result:
        with open(args.result, "w", encoding="utf-8") as f:
            json.dump(out, f)
    return 0 if out["ok"] else 1


def parser():
    p = argparse.ArgumentParser(prog="_fetcher_inner.py")
    p.add_argument("--result")
    sub = p.add_subparsers(dest="verb", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--stage", required=True, choices=STAGES)
    f.add_argument("--url", required=True)
    f.add_argument("--extractors", required=True)
    f.add_argument("--proxy-url", dest="proxy_url", required=True)
    f.add_argument("--max-seconds", dest="max_seconds", type=int, required=True)
    f.add_argument("--max-bytes", dest="max_bytes", type=int, required=True)
    f.add_argument("--langs", default="")
    f.add_argument("--timeout", type=int, required=True)
    m = sub.add_parser("measure")
    m.add_argument("--reference", required=True)
    m.add_argument("--platform", required=True)
    m.add_argument("--in", dest="input", default="/in")
    m.add_argument("--out", default="/out")
    x = sub.add_parser("proxy")
    x.add_argument("--allow-host", action="append", default=[])
    x.add_argument("--allow-suffix", action="append", default=[])
    x.add_argument("--max-bytes", type=int, required=True)
    x.add_argument("--deadline", type=float, required=True)
    x.add_argument("--port", type=int, default=8888)
    x.add_argument("--out", default="/out")
    s = sub.add_parser("selfcheck")
    s.add_argument("--expect-version", dest="expect_version", default="")
    return p


VERBS = {"fetch": verb_fetch, "measure": verb_measure, "proxy": verb_proxy, "selfcheck": verb_selfcheck}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return VERBS[args.verb](args)
    except Refusal as e:
        write_result(getattr(args, "result", None), False, "fetch_failed", None)
        print("refused: %s" % e.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
