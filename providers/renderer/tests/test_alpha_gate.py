"""The exact pixel gates of an admitted page on synthetic RGBA frames: a dot of alpha 1/255 is found on exactly the frames it is on, a dot one pixel
outside the rounded face box passes, a row at the line refuses and one above passes, a layer with no pixel drawn and a frame that is not 8-bit RGBA
of the frame's size refuse. Needs ffmpeg."""
from __future__ import annotations

import os
import struct
import zlib

import pytest

import renderer_kit as K
import _alpha_gate as G
from _text import Refusal

needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
W, H = 200, 300
FACE = {"x": 40.4, "y": 60.6, "w": 50, "h": 40}          # rounded outward: x 40..91 (width 51), y 60..101 (height 41)
LINE = 200


def png(width, height, pixels, colour=6):
    """pixels: {(x, y): (r, g, b, a)}; every other pixel transparent (or black for RGB)."""
    channels = 4 if colour == 6 else 3
    rows = []
    for y in range(height):
        row = bytearray(width * channels)
        for (px, py), value in pixels.items():
            if py == y:
                row[px * channels:(px + 1) * channels] = bytes(value[:channels])
        rows.append(b"\x00" + bytes(row))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 1)) + chunk(b"IEND", b""))


def write(folder, frames, start=10, **kw):
    for k, pixels in enumerate(frames):
        with open(os.path.join(folder, "beat_%06d.png" % (start + k)), "wb") as fh:
            fh.write(png(W, H, pixels, **kw))


def check(folder, n, start=10):
    G.check_range(str(folder), start, start + n, FACE, LINE, W, H, K.FFMPEG)


DRAWN = {(5, 5): (255, 255, 255, 255)}              # a pixel somewhere harmless, so that the layer draws something


@needs_ffmpeg
def test_a_dot_of_one_over_255_in_the_face_box_is_found_on_exactly_its_frames(tmp_path):
    dot = {**DRAWN, **{(60, 80): (255, 255, 255, 1)}}
    write(tmp_path, [DRAWN, DRAWN, dot, dot, dot, DRAWN])
    with pytest.raises(Refusal) as e:
        check(tmp_path, 6)
    assert (e.value.code, e.value.field) == ("overlay_hits_face", "frame 12")
    write(tmp_path, [DRAWN, DRAWN, DRAWN, dot, DRAWN, DRAWN])
    with pytest.raises(Refusal) as e:
        check(tmp_path, 6)
    assert e.value.field == "frame 13"


@needs_ffmpeg
def test_the_face_box_is_rounded_outward_so_the_pixel_just_outside_it_passes_and_the_one_on_its_edge_does_not(tmp_path):
    assert G.box_pixels(FACE, W, H) == (40, 60, 51, 41)
    outside = {**DRAWN, **{(39, 80): (255, 0, 0, 255), (91, 80): (255, 0, 0, 255), (60, 59): (255, 0, 0, 255), (60, 101): (255, 0, 0, 255)}}
    write(tmp_path, [outside])
    check(tmp_path, 1)
    for edge in ((40, 80), (90, 80), (60, 60), (60, 100)):
        write(tmp_path, [{**DRAWN, **{edge: (255, 0, 0, 1)}}])
        with pytest.raises(Refusal) as e:
            check(tmp_path, 1)
        assert e.value.code == "overlay_hits_face", edge


@needs_ffmpeg
def test_a_row_at_the_line_refuses_and_one_above_it_passes(tmp_path):
    write(tmp_path, [{**DRAWN, **{(10, LINE - 1): (0, 255, 0, 255)}}])
    check(tmp_path, 1)
    write(tmp_path, [{**DRAWN, **{(10, LINE): (0, 255, 0, 1)}}])
    with pytest.raises(Refusal) as e:
        check(tmp_path, 1)
    assert (e.value.code, e.value.field) == ("caption_below_line", "frame 10")


@needs_ffmpeg
def test_a_layer_with_nothing_drawn_refuses_and_so_does_a_frame_that_is_not_8_bit_rgba_of_the_frames_size(tmp_path):
    write(tmp_path, [{}, {}])
    with pytest.raises(Refusal) as e:
        check(tmp_path, 2)
    assert e.value.code == "block_not_drawn"
    write(tmp_path, [DRAWN, DRAWN], colour=2)
    with pytest.raises(Refusal) as e:
        check(tmp_path, 2)
    assert (e.value.code, e.value.field) == ("frame_not_rgba", "frame 10")
    (tmp_path / "beat_000010.png").write_bytes(png(W + 1, H, DRAWN))
    (tmp_path / "beat_000011.png").write_bytes(png(W, H, DRAWN))
    with pytest.raises(Refusal) as e:
        check(tmp_path, 2)
    assert e.value.code == "frame_not_rgba"
    os.unlink(tmp_path / "beat_000011.png")
    (tmp_path / "beat_000010.png").write_bytes(png(W, H, DRAWN))
    with pytest.raises(Refusal) as e:
        check(tmp_path, 2)
    assert (e.value.code, e.value.field) == ("frame_not_rgba", "frame 11")


@needs_ffmpeg
def test_every_range_of_a_layer_is_judged_with_its_own_face_and_line(tmp_path):
    write(tmp_path, [DRAWN] * 6, start=10)
    other = {"x": 0, "y": 0, "w": 20, "h": 20}                  # this range's face box covers the harmless pixel
    rows = [{"start": 10, "end": 13}, {"start": 13, "end": 16, "face": other}]
    with pytest.raises(Refusal) as e:
        G.check_layer(str(tmp_path), rows, FACE, LINE, W, H, K.FFMPEG)
    assert (e.value.code, e.value.field) == ("overlay_hits_face", "frame 13")
    G.check_layer(str(tmp_path), rows[:1], FACE, LINE, W, H, K.FFMPEG)
