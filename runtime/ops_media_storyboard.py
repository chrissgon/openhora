#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The storyboard of a short-video post (package V5-1, VD14): a still per beat of the post's ```script block and a contact sheet, drawn by the
renderer's `storyboard` verb over a neutral placeholder, with no recording and no transcript. Advisory: the video may look different.

  video_storyboard(project, post, channel=None)            draw it (or replay it) for one post; returns the key, the sheet, a row per beat
  video_storyboard_file(project, key, file, channel=None)  the bytes of one PNG of a storyboard folder, for the page

The rules of this module:

  * The engine is always the ffmpeg one, whatever `media.renderer` says: HyperFrames has no `storyboard` verb, and the ffmpeg image is the one
    every HyperFrames project already builds (decision D2). For a beat, `drawn_block` is the ffmpeg engine's block for the preset and
    `video_block` is the block of the project's own engine (None when that engine draws no block for the preset).
  * A folder is `<data_dir>/media/storyboards/<key>/`; `<key>` is the first 16 hex characters of the sha256 of the post's bytes, the theme's
    flags and blocks/pins.json. The same key is a replay: nothing is called (the verb gives the same bytes for the same inputs), the folder's
    modification time is touched so the retention (runtime/upkeep.py, 30 days) counts from the last use.
  * Read-only to the person's project; it writes only inside `<data_dir>/media/storyboards/`. It crosses the LAN socket (VD18): it is not in
    operations.LAN_REFUSED_OPS; the stills hold the script's on-screen text, which is project data, never a recording.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import media_animation  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media  # noqa: E402
import ops_step_seams  # noqa: E402
import phrases  # noqa: E402
import step_media  # noqa: E402
import steps  # noqa: E402
import theme  # noqa: E402

CLASS, VERB = "renderer:video", "storyboard"
DRAW_ENGINE = "ffmpeg"                              # the one engine that has the verb
TIMEOUT = 300
KEY = re.compile(r"[0-9a-f]{16}")
FILE = re.compile(r"beat-[0-9]{1,2}\.png|sheet\.png")
RESULT = "result.json"                              # what a drawing recorded (never served: the file route's pattern does not match it)
RESULT_LIMIT = 64 * 1024
PNG_LIMIT = 16 * 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FOLDERS = ("media", "storyboards")                  # under the data folder
DIRECTORY, NOFOLLOW = getattr(os, "O_DIRECTORY", 0), getattr(os, "O_NOFOLLOW", 0)
ADVISORY_KEY, NO_SCRIPT_KEY = "VID_STORYBOARD_ADVISORY", "VID_STORYBOARD_NO_SCRIPT"


def _engine_of(ctx: dict):
    """The engine that draws a storyboard: always the ffmpeg one (a seam: a test puts a fake in its place)."""
    return ops_step_seams.MediaEngine(ops_step_seams.MediaStore(ctx).root(), DRAW_ENGINE)


def _storyboards_root(data_dir: str) -> str:
    return os.path.join(data_dir, *FOLDERS)


def _fail(code: str, text: str, status: int = 1) -> "core.OpsError":
    return core.OpsError(f"{code}: {text}", status)


def _read_post(project: str, post) -> bytes:
    """The post's bytes, through the engine's own reader (no link, a regular file, at most POST_LIMIT), after the publishing rule's name check.
    core.OpsError `bad_post` or `no_script`."""
    if not step_media._is_post(post):
        raise _fail("bad_post", "give a post file docs/marketing/content/<name>.md", 2)
    ctx = steps.Context(0, 0, os.path.abspath(project), {}, None, None, lambda: None, lambda: [], lambda: "")
    try:
        data = steps.read_file(ctx, post, step_media.POST_LIMIT)
    except steps.StepFailure as e:
        raise _fail("bad_post", {"missing": "the post file is not there", "too_large": "the post file is too large"}.get(e.code, "the post file cannot be read")) from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _fail("bad_post", "the post file is not text") from None
    if not step_media.has_script(text):
        raise _fail("no_script", phrases.en(NO_SCRIPT_KEY))
    return data


def _theme_flags(project: str) -> list:
    try:
        flags, _ = theme.theme_args(os.path.abspath(project))
    except theme.ThemeError as e:
        raise _fail(e.code, e.sentence or e.code.replace("_", " ")) from None
    return list(flags)


def _key(post_bytes: bytes, flags: list, pins: bytes) -> str:
    digest = hashlib.sha256()
    for part in (post_bytes, "\0".join(flags).encode("utf-8"), pins):
        digest.update(hashlib.sha256(part).digest())      # each part hashed first, so no part can run into the next
    return digest.hexdigest()[:16]


def _pins(root: str) -> bytes:
    try:
        with open(os.path.join(root, *media_animation.PINS), "rb") as f:
            return f.read(media_animation.CATALOGUE_MAX)
    except OSError:
        return b""


def _recorded(folder: str):
    """The beats a drawing recorded in `folder`, or None when it has no complete drawing (the sheet or the record is missing or unreadable)."""
    try:
        if not os.path.isfile(os.path.join(folder, "sheet.png")):
            return None
        fd = os.open(os.path.join(folder, RESULT), os.O_RDONLY | NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            doc = json.loads(f.read(RESULT_LIMIT + 1).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return None
    beats = doc.get("beats") if isinstance(doc, dict) else None
    return _clean_beats(beats) if isinstance(beats, list) else None


def _clean_beats(beats) -> list:
    """[{"beat", "preset", "file"}] from what the verb reported, or core.OpsError when a row is not what the verb writes."""
    out = []
    for row in beats:
        number = row.get("beat") if isinstance(row, dict) else None
        preset, name = (row.get("preset"), row.get("file")) if isinstance(row, dict) else (None, None)
        if not isinstance(number, int) or isinstance(number, bool) or not isinstance(preset, str) or not isinstance(name, str) \
                or not FILE.fullmatch(name) or name == "sheet.png":
            raise _fail("engine_refused", "the renderer's storyboard is not what was asked for")
        out.append({"beat": number, "preset": preset, "file": name})
    return out


def _write_record(folder: str, beats: list) -> None:
    path = os.path.join(folder, RESULT)
    temporary = f"{path}.{os.getpid()}.new"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"beats": beats}, f, sort_keys=True)
    os.replace(temporary, path)


def _rows(root: str, implementation, beats: list) -> list:
    """The beats with `drawn_block` (the ffmpeg engine's block for the preset) and `video_block` (the project's engine's, or None)."""
    found = media_animation.read_catalogue(root)["engines"]
    video = media_animation.engine_name(root, implementation)
    drawn = (found.get(DRAW_ENGINE) or {}).get("presets") or {}
    own = ((found.get(video) or {}).get("presets") or {}) if video is not None else {}
    return [{"beat": b["beat"], "preset": b["preset"], "file": b["file"], "drawn_block": drawn.get(b["preset"]), "video_block": own.get(b["preset"])} for b in beats]


def video_storyboard(project: str, post, channel=None) -> dict:
    """Draw the storyboard of `post` (or replay it). Returns {"key", "sheet": "sheet.png", "beats": [{"beat", "preset", "file", "drawn_block",
    "video_block"}], "engine": "ffmpeg", "advisory": the fixed sentence}; the terminal also gets "sheet_path", the absolute path of the sheet.
    core.OpsError, its message starting with a closed code: `bad_post`, `no_script`, `not_configured` (with step_media.ENGINE_NEXT),
    `engine_refused`, `engine_failed`, a theme's code, or `catalogue_unreadable`."""
    ctx = core.context(project)
    ops_media._channel(ctx, "video-storyboard", channel)
    data = _read_post(project, post)
    store = ops_step_seams.MediaStore(ctx)
    root = store.root()
    flags = _theme_flags(project)
    key = _key(data, flags, _pins(root))
    folder = os.path.join(_storyboards_root(ctx["cfg"]["data_dir"]), key)
    beats = _recorded(folder)
    if beats is not None:
        os.utime(folder, None)                        # the retention counts from the last use
    else:
        beats = _draw(ctx, project, post, flags, folder)
    try:
        rows = _rows(root, store.renderer(), beats)
    except media_animation.CatalogueError as e:
        raise _fail(e.code, "the catalogue of animations cannot be read") from None
    out = {"key": key, "sheet": "sheet.png", "beats": rows, "engine": DRAW_ENGINE, "advisory": phrases.en(ADVISORY_KEY)}
    if channel in (None, "terminal"):
        out["sheet_path"] = os.path.join(folder, "sheet.png")
    return out


def _draw(ctx: dict, project: str, post: str, flags: list, folder: str) -> list:
    """One call of the renderer's `storyboard` verb into `folder`; the beats it reports, recorded for the replay."""
    os.makedirs(_storyboards_root(ctx["cfg"]["data_dir"]), mode=0o700, exist_ok=True)
    args = ["--post", os.path.join(os.path.realpath(project), *post.split("/")),
            "--checker", ops_step_seams.MediaStore(ctx).checker(),
            "--vocabulary", ops_step_seams.MediaStore(ctx).reference(step_media.VOCABULARY),
            "--out", folder] + flags
    try:
        done = _engine_of(ctx).call(CLASS, VERB, args, TIMEOUT)
    except ops_step_seams.StepServiceError as e:
        if e.code == "not_configured":
            raise _fail("not_configured", step_media.ENGINE_NEXT["not_configured"]) from None
        if e.code == "refused":
            raise _fail("engine_refused", "the renderer refused this post's script") from None
        raise _fail("engine_failed", "the renderer could not draw the storyboard") from None
    reported = done.get("beats") if isinstance(done, dict) else None
    if not isinstance(reported, list) or not reported or not os.path.isfile(os.path.join(folder, "sheet.png")):
        raise _fail("engine_refused", "the renderer's storyboard is not what was asked for")
    beats = _clean_beats(reported)
    _write_record(folder, beats)
    return beats


def _open_png(data_dir: str, key: str, name: str) -> bytes:
    """The bytes of one PNG of a storyboard folder, every folder opened from the one before without following a link. OSError when it is not there."""
    opened = []
    try:
        fd = os.open(data_dir, os.O_RDONLY | DIRECTORY)
        opened.append(fd)
        for part in FOLDERS + (key,):
            fd = os.open(part, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=fd)
            opened.append(fd)
        last = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=fd)
        opened.append(last)
        if os.fstat(last).st_mode & 0o170000 != 0o100000:
            raise OSError("not a regular file")
        with os.fdopen(os.dup(last), "rb") as f:
            data = f.read(PNG_LIMIT + 1)
    finally:
        for descriptor in opened:
            os.close(descriptor)
    if len(data) > PNG_LIMIT:
        raise OSError("too large")
    return data


def video_storyboard_file(project: str, key, file, channel=None) -> dict:
    """One PNG of a storyboard folder: {"media_type": "image/png", "data": the bytes}. The key is 16 hex characters and the file `beat-<n>.png` or
    `sheet.png`; anything else, a link and a file that is not a PNG are refused. core.OpsError."""
    ctx = core.context(project)
    ops_media._channel(ctx, "video-storyboard-file", channel)
    if not isinstance(key, str) or not KEY.fullmatch(key) or not isinstance(file, str) or not FILE.fullmatch(file):
        raise _fail("bad_file", "give a storyboard key (16 hexadecimal characters) and beat-<n>.png or sheet.png", 2)
    try:
        data = _open_png(ctx["cfg"]["data_dir"], key, file)
    except OSError:
        raise _fail("not_found", "there is no such storyboard file") from None
    if not data.startswith(PNG_MAGIC):
        raise _fail("bad_file", "the file is not a PNG image")
    return {"media_type": "image/png", "data": data}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
