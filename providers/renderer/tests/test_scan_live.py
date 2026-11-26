"""The `scan` verb in a real container (package P9-a1, the supervisor's live legs L1 and L2). Gated like the other live files:

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest -s providers/renderer/tests/test_scan_live.py

and they never build: the image is built first (`OPENHORA_STATE_DIR=<folder> python3 providers/renderer/ffmpeg.py build --confirmed`, with `wheel-pin.json` filled)
and these tests use what it left. Every picture and clip is made here, with the image's own ffmpeg (drawtext in DejaVu) and OpenCV's QR encoder, from invented
words and a `.example` address; nothing is committed. The pictures go through the host's own `asset-sheet --mode full`, which names them as the scan takes them.
`-s` shows the timings the test prints for the decision file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

import renderer_kit as K
import _docker as D

pytestmark = pytest.mark.skipif(os.environ.get("WB_RENDERER_DOCKER_TESTS") != "1",
                                reason="a real container: set WB_RENDERER_DOCKER_TESTS=1 (the renderer image must be built first)")

REAL_STATE_DIR = os.environ.get("OPENHORA_STATE_DIR")
HOST = str(K.HOST)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SIZE = "1080x1920"
QR_PYTHON = """
import cv2, numpy, sys
text, out = sys.argv[1], sys.argv[2]
code = cv2.QRCodeEncoder.create().encode(text)
code = cv2.resize(code, None, fx=12, fy=12, interpolation=cv2.INTER_NEAREST)
code = cv2.copyMakeBorder(code, 48, 48, 48, 48, cv2.BORDER_CONSTANT, value=255)
canvas = numpy.full((1920, 1080), 255, numpy.uint8)
y, x = (1920 - code.shape[0]) // 2, (1080 - code.shape[1]) // 2
canvas[y:y + code.shape[0], x:x + code.shape[1]] = code
cv2.imwrite(out, canvas)
"""


@pytest.fixture
def real_state(monkeypatch):
    if not REAL_STATE_DIR:
        pytest.fail("set OPENHORA_STATE_DIR to the folder the build wrote its record into, for the build and for pytest")
    monkeypatch.setenv("OPENHORA_STATE_DIR", REAL_STATE_DIR)


def host(*args, timeout=1500):
    done = subprocess.run([sys.executable, HOST, *map(str, args)], capture_output=True, text=True, timeout=timeout)
    try:
        out = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        out = None
    return done.returncode, out, done.stderr


def in_image(image, args, folder, entrypoint):
    """One command of the image's own tools, with no network, on a folder mounted at /out."""
    argv = ["docker", "run", "--rm", "--network", "none", "--entrypoint", entrypoint, "-v", "%s:/out:rw" % folder]
    if sys.platform.startswith("linux"):
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    done = subprocess.run([*argv, image["id"], *args], capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stderr[-2000:]


def drawtext(text, enable=""):
    """52 px: "SAMPLE PHOTO DO NOT USE" in DejaVu Bold at 72 px is wider than the 1080 px frame and the picture cuts its first and last letters (live leg, 2026-11-26)."""
    return "drawtext=fontfile=%s:text='%s':fontsize=52:fontcolor=white:box=1:boxcolor=0x203040:x=(w-text_w)/2:y=900%s" % (FONT, text, enable)


@pytest.fixture
def fixtures(real_state, tmp_path_factory):
    """Seven fictional files in a folder: a picture with text, a QR link, a QR phone action, a clean gradient, a 30 fps clip whose caption shows on frames 120 to 131 over a still
    background, the same caption over a moving background, and a 60 fps clip with a QR code on frames 300 to 305."""
    image = D.check_image()
    folder = tmp_path_factory.mktemp("scan-fixtures")
    base = ["-hide_banner", "-loglevel", "error", "-y"]
    in_image(image, base + ["-f", "lavfi", "-i", "color=c=0x335577:s=%s" % SIZE, "-vf", drawtext("SAMPLE PHOTO DO NOT USE"), "-frames:v", "1", "/out/text.png"], folder, "ffmpeg")
    in_image(image, ["-I", "-c", QR_PYTHON, "https://shop.example/promo", "/out/qr-link.png"], folder, "python3")
    in_image(image, ["-I", "-c", QR_PYTHON, "tel:+15550100", "/out/qr-tel.png"], folder, "python3")
    in_image(image, ["-I", "-c", QR_PYTHON, "https://clip.example/win", "/out/qr-clip.png"], folder, "python3")
    in_image(image, base + ["-f", "lavfi", "-i", "color=c=gray:s=%s" % SIZE, "-vf", "format=gray,geq=lum='255*X/W'", "-frames:v", "1", "/out/clean.png"], folder, "ffmpeg")
    in_image(image, base + ["-f", "lavfi", "-i", "color=c=0x335577:s=%s:r=30:d=10" % SIZE, "-vf", drawtext("CLIP SAMPLE TEXT", ":enable='between(n,120,131)'") + ",format=yuv420p",
                            "-c:v", "libx264", "/out/text-clip.mp4"], folder, "ffmpeg")
    in_image(image, base + ["-f", "lavfi", "-i", "gradients=s=%s:r=30:d=10:speed=0.05" % SIZE, "-vf", drawtext("MOVING SAMPLE TEXT", ":enable='between(n,120,131)'") + ",format=yuv420p",
                            "-c:v", "libx264", "/out/move-clip.mp4"], folder, "ffmpeg")
    in_image(image, base + ["-f", "lavfi", "-i", "color=c=0x335577:s=%s:r=60:d=10" % SIZE, "-i", "/out/qr-clip.png", "-filter_complex",
                            "[0:v][1:v]overlay=enable='between(n,300,305)',format=yuv420p", "-c:v", "libx264", "/out/qr-clip.mp4"], folder, "ffmpeg")
    names = {"text": "text.png", "link": "qr-link.png", "tel": "qr-tel.png", "clean": "clean.png", "textclip": "text-clip.mp4", "movclip": "move-clip.mp4", "qrclip": "qr-clip.mp4"}
    return {slot: folder / name for slot, name in names.items()}


@pytest.fixture
def normalised(fixtures, tmp_path):
    """The six files as `asset-sheet --mode full` writes them: {slot: (path, "WxH")}. The 60 fps clip is normalised at 60 (its own call), the others at the default 30."""
    flags = []
    for slot, path in fixtures.items():
        if slot != "qrclip":
            flags += ["--asset", "%s:1=%s" % (slot, path)]
    made = {}
    for extra, more in (([], flags), (["--fps", "60"], ["--asset", "qrclip:1=%s" % fixtures["qrclip"]])):
        rc, out, err = host("asset-sheet", *more, *extra, "--mode", "full", "--out", tmp_path / "set")
        assert rc == 0, err
        made.update({a["row"]: (a["path"], "%dx%d" % (a["width"], a["height"])) for a in out["assets"]})
    return made


def scan(normalised, *slots):
    flags = []
    for slot in slots:
        flags += ["--asset", "%s=%s" % (slot, normalised[slot][0]), "--size", "%s=%s" % (slot, normalised[slot][1])]
    started = time.monotonic()
    rc, out, err = host("scan", *flags)
    return rc, out, err, time.monotonic() - started


def test_every_planted_picture_and_clip_gives_the_rows_expected(normalised):
    rc, out, err, seconds = scan(normalised, "text", "link", "tel", "clean", "textclip", "movclip")
    assert rc == 0, err
    rows = {a["slot"]: a for a in out["assets"]}
    print("\nscan of six assets: %.1f s; versions %s" % (seconds, out["versions"]))
    for a in out["assets"]:
        print("  %-8s %-5s frames=%d text_frames=%d candidates=%d partial=%s codes=%s lines=%s" % (a["slot"], a["kind"], a["frames"], a["frames_text"], a["frames_changed"], a["partial"], a["codes"], a["text"]["lines"]))
    assert set(out["versions"]["tessdata"]) >= {"eng", "por", "spa"} and out["lang"] == "eng+por+spa"
    assert "text_found" in rows["text"]["codes"] and any("SAMPLE PHOTO DO NOT USE" in line.upper() for line in rows["text"]["text"]["lines"])
    assert rows["link"]["codes"] == ["qr_link"] and rows["link"]["qr"][0]["host"] == "shop.example"
    assert rows["tel"]["codes"] == ["qr_action"] and rows["tel"]["qr"][0]["scheme"] == "tel"
    assert rows["clean"]["codes"] == [] and rows["clean"]["text"]["lines"] == [] and rows["clean"]["qr"] == []
    # a caption that shows for 12 frames (0.4 s at 30 fps) in the middle of a clip is read, on a still background and on a moving one
    for slot, words in (("textclip", "CLIP SAMPLE TEXT"), ("movclip", "MOVING SAMPLE TEXT")):
        assert rows[slot]["kind"] == "clip" and "text_found" in rows[slot]["codes"] and rows[slot]["partial"] is False, (slot, rows[slot])
        assert any("SAMPLE" in line.upper() for line in rows[slot]["text"]["lines"]), (slot, rows[slot]["text"])


def test_a_clip_with_a_qr_code_on_six_frames_of_six_hundred_finds_it(normalised):
    rc, out, err, seconds = scan(normalised, "qrclip")
    assert rc == 0, err
    row = out["assets"][0]
    qr = row["qr"]
    print("\nqrclip alone: %.1f s" % seconds)
    assert row["codes"] == ["qr_link"] and qr[0]["host"] == "clip.example" and 300 <= qr[0]["first_frame"] <= 305 and qr[0]["frames"] == 6, qr
    assert row["frames"] == 600 and row["frames_qr"] == 600 and row["partial"] is False


def test_two_runs_give_the_same_answer_byte_for_byte(normalised):
    first = scan(normalised, "text", "link", "movclip")
    second = scan(normalised, "text", "link", "movclip")
    assert first[0] == second[0] == 0
    assert json.dumps(first[1]["assets"], sort_keys=True) == json.dumps(second[1]["assets"], sort_keys=True)


def test_the_timings_of_a_picture_a_300_frame_clip_and_a_600_frame_clip_are_printed(normalised):
    for slot in ("text", "textclip", "movclip", "qrclip"):
        rc, out, err, seconds = scan(normalised, slot)
        assert rc == 0, err
        print("\n%s alone: %.1f s (%d frames)" % (slot, seconds, out["assets"][0]["frames"]))
