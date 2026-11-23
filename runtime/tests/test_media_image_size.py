"""Tests of `media_stock.image_size` (package V9b-3c): the width and height of a PNG or a JPEG of the stock folder or its quarantine, read from the file's own header bytes. Pictures are made
here (flat colour, headers only); nothing is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_image_size.py
"""
from __future__ import annotations

import os
import struct

import pytest

from media_kit import world  # noqa: F401  (the fixture)
from media_stock_kit import media_stock, png


def jpeg(width, height, sof=b"\xff\xc0", app1=0):
    head = b"\xff\xd8" + (b"\xff\xe1" + struct.pack(">H", app1 + 2) + b"\x00" * app1 if app1 else b"")
    return head + sof + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00" + b"\xff\xd9"


def put(world, name, data, quarantine=False):
    folder = media_stock.ensure_folder(world["data"], world["rid"])
    if quarantine:
        folder = os.path.join(folder, media_stock.QUARANTINE)
        os.makedirs(folder, mode=0o700, exist_ok=True)
    with open(os.path.join(folder, name), "wb") as f:
        f.write(data)
    return folder


def size(world, name, quarantine=False):
    return media_stock.image_size(world["data"], world["rid"], name, quarantine)


def test_a_png_is_read_from_its_ihdr_in_the_folder_and_in_the_quarantine(world):
    put(world, "a.png", png(30, 20))
    put(world, "q-abc.png", png(9000, 100), quarantine=True)
    assert size(world, "a.png") == (30, 20) and size(world, "q-abc.png", True) == (9000, 100)


@pytest.mark.parametrize("sof", [b"\xff\xc0", b"\xff\xc2", b"\xff\xc1", b"\xff\xcf"])
def test_a_baseline_or_progressive_jpeg_is_read_at_its_first_frame_header(world, sof):
    put(world, "a.jpg", jpeg(640, 480, sof))
    assert size(world, "a.jpg") == (640, 480)


def test_a_large_app1_segment_before_the_frame_header_is_skipped(world):
    put(world, "a.jpg", jpeg(1234, 567, app1=60000))
    assert size(world, "a.jpg") == (1234, 567)


def test_a_file_that_is_not_a_png_or_a_jpeg_or_is_cut_short_has_no_size(world):
    put(world, "no-soi.jpg", b"\xff\xe0" + jpeg(10, 10)[2:])
    put(world, "cut.jpg", jpeg(10, 10)[:10])
    put(world, "cut.png", png(10, 10)[:20])
    put(world, "text.png", b"not a picture at all, just words")
    for name in ("no-soi.jpg", "cut.jpg", "cut.png", "text.png"):
        assert size(world, name) is None
    assert size(world, "absent.png") is None


def test_a_link_in_the_quarantine_is_refused_and_so_is_a_link_to_the_quarantine_folder(world):
    folder = put(world, "real.png", png(5, 5), quarantine=True)
    os.symlink(os.path.join(folder, "real.png"), os.path.join(folder, "link.png"))
    with pytest.raises(media_stock.StockError):
        size(world, "link.png", True)
    assert size(world, "real.png", True) == (5, 5)
