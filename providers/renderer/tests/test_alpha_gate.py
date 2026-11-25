"""The exact pixel gates of an admitted page on synthetic RGBA frames: a row at the line refuses (a dot of alpha 1/255 is a hit, found on exactly its frames)
and one above passes, a layer with no pixel drawn and a frame that is not 8-bit RGBA of the frame's size refuse, a short caption chunk may draw nothing, and
nothing is refused for being on the speaker's face (the maintainer's decisions of 2026-11-24: the face box is a placement input, not a gate). Needs ffmpeg."""
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
FACE = {"x": 40.4, "y": 60.6, "w": 50, "h": 40}          # a speaker's face box: no pixel is refused for being in it
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


def check(folder, n, start=10, **kw):
    G.check_range(str(folder), start, start + n, LINE, W, H, K.FFMPEG, **kw)


DRAWN = {(5, 5): (255, 255, 255, 255)}              # a pixel somewhere harmless, so that the layer draws something


@needs_ffmpeg
def test_a_dot_of_one_over_255_below_the_line_is_found_on_exactly_its_frames(tmp_path):
    dot = {**DRAWN, **{(60, LINE + 5): (255, 255, 255, 1)}}
    write(tmp_path, [DRAWN, DRAWN, dot, dot, dot, DRAWN])
    with pytest.raises(Refusal) as e:
        check(tmp_path, 6)
    assert (e.value.code, e.value.field) == ("caption_below_line", "frame 12")
    write(tmp_path, [DRAWN, DRAWN, DRAWN, dot, DRAWN, DRAWN])
    with pytest.raises(Refusal) as e:
        check(tmp_path, 6)
    assert e.value.field == "frame 13"


@needs_ffmpeg
def test_pixels_on_the_speakers_face_are_not_refused_a_dot_a_block_and_a_whole_frame_of_them(tmp_path):
    on_face = {**DRAWN, **{(60, 80): (255, 255, 255, 1), (41, 61): (255, 0, 0, 255), (90, 100): (255, 0, 0, 255)}}
    write(tmp_path, [on_face, on_face])
    check(tmp_path, 2)
    everywhere = {(x, y): (0, 0, 0, 255) for x in range(W) for y in range(LINE)}
    write(tmp_path, [everywhere])
    check(tmp_path, 1)


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
def test_every_range_of_a_layer_is_judged_with_its_own_line_and_its_own_drawn_floor(tmp_path):
    write(tmp_path, [DRAWN] * 3 + [{}] * 3 + [{**DRAWN, **{(10, 120): (0, 255, 0, 255)}}] * 3, start=10)
    rows = [{"start": 10, "end": 13, "line_y": LINE}, {"start": 13, "end": 16, "line_y": LINE, "require_drawn": False}, {"start": 16, "end": 19, "line_y": 100}]
    with pytest.raises(Refusal) as e:
        G.check_layer(str(tmp_path), rows, W, H, K.FFMPEG)
    assert (e.value.code, e.value.field) == ("caption_below_line", "frame 16")      # the third range's line is 100: its pixel at 120 is below it
    G.check_layer(str(tmp_path), rows[:2], W, H, K.FFMPEG)                           # a short chunk may draw nothing
    with pytest.raises(Refusal) as e:
        G.check_layer(str(tmp_path), [{"start": 13, "end": 16, "line_y": LINE}], W, H, K.FFMPEG)
    assert e.value.code == "block_not_drawn"


@needs_ffmpeg
def test_a_caption_prefix_reads_cap_frames_and_a_caption_line_at_the_band_bottom_refuses_rows_from_it_down(tmp_path):
    for k, pixels in enumerate([DRAWN, {**DRAWN, **{(10, 250): (0, 255, 0, 255)}}]):
        (tmp_path / ("cap_%06d.png" % (10 + k))).write_bytes(png(W, H, pixels))
    G.check_range(str(tmp_path), 10, 11, 250, W, H, K.FFMPEG, "cap")
    with pytest.raises(Refusal) as e:
        G.check_range(str(tmp_path), 10, 12, 250, W, H, K.FFMPEG, "cap")
    assert (e.value.code, e.value.field) == ("caption_below_line", "frame 11")
    G.check_range(str(tmp_path), 10, 12, 251, W, H, K.FFMPEG, "cap")
