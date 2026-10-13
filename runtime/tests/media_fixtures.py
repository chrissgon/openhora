"""Synthetic media for the tests of the media store (runtime/media.py): tiny MOV and MP4 files made with ffmpeg when it is
installed (fictional test patterns, never a real recording), and small image files written byte by byte. Not a test file.
"""
from __future__ import annotations

import io
import shutil
import struct
import subprocess
import zlib

import pytest

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg and ffprobe are not installed")


def encode(path, *, args, source="testsrc=size=64x64:rate=10:duration=1", audio=True, extra_inputs=()):
    """Run ffmpeg on a synthetic pattern (and a sine tone) into `path`; `args` are the output options."""
    argv = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", source]
    if audio:
        argv += ["-f", "lavfi", "-i", "sine=duration=1"]
    for item in extra_inputs:
        argv += ["-f", "lavfi", "-i", item]
    argv += list(args) + [str(path)]
    subprocess.run(argv, check=True, capture_output=True, timeout=120)
    return path


def make_mov(path):
    """A QuickTime file like an iPhone's: one H.264 video, one AAC audio, and a data stream (a timecode track), as Apple's
    files carry data streams a recording check must ignore."""
    return encode(path, args=["-timecode", "01:00:00:00", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-f", "mov"])


def make_mp4(path):
    return encode(path, args=["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-f", "mp4"])


def make_hdr(path):
    """A file tagged HLG (arib-std-b67), the transfer of an iPhone's HDR video."""
    return encode(path, audio=False, args=["-c:v", "libx264", "-x264-params", "transfer=arib-std-b67:colorprim=bt2020:colormatrix=bt2020nc", "-f", "mp4"])


def make_long(path, seconds):
    """A tiny file that lasts `seconds` seconds: 16x16 pixels at one frame a second."""
    return encode(path, audio=False, source=f"color=c=black:s=16x16:r=1:d={seconds}", args=["-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "mp4"])


def make_two_videos(path):
    return encode(path, audio=False, extra_inputs=("testsrc=size=32x32:rate=10:duration=1",),
                  args=["-map", "0:v", "-map", "1:v", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "mp4"])


def make_two_audios(path):
    return encode(path, audio=True, extra_inputs=("sine=frequency=880:duration=1",),
                  args=["-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-f", "mp4"])


def png(width=8, height=8, animated=False):
    """A valid PNG of the given header size (the pixels are zeros); animated puts an acTL chunk before the data."""
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    rows = (b"\x00" + b"\x00" * width) * min(height, 64)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    if animated:
        out += chunk(b"acTL", struct.pack(">II", 2, 0))
    return out + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def jpeg(width=8, height=8):
    """The head of a JPEG: SOI, an APP0 segment, a SOF0 header with the size and an EOI. Enough for a header check."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9" + b"\x00" * 16


def webp(width=8, height=8, animated=False):
    """A lossless-header WebP (VP8X when animated or extended): the header fields a size check reads."""
    if animated:
        body = b"VP8X" + struct.pack("<I", 10) + bytes([0x02, 0, 0, 0]) + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    else:
        bits = (width - 1) | ((height - 1) << 14)
        body = b"VP8L" + struct.pack("<I", 5) + b"\x2f" + bits.to_bytes(4, "little")
    body += b"\x00" * 16
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


def heic():
    return struct.pack(">I", 24) + b"ftypheic" + b"\x00" * 4 + b"mif1heic" + b"\x00" * 32


class Body(io.RawIOBase):
    """A request body that is generated, never held: `read(n)` returns up to n bytes after `head`, then zeros, until `total`
    bytes were given. `reads` counts the calls; `fail_after` raises OSError after that many bytes (a dropped connection)."""

    def __init__(self, total, head=b"", fail_after=None, stop_after=None):
        self.total, self.head, self.given, self.reads = total, head, 0, 0
        self.fail_after, self.stop_after = fail_after, stop_after

    def readable(self):
        return True

    def read(self, n=-1):
        self.reads += 1
        if self.fail_after is not None and self.given >= self.fail_after:
            raise OSError("the connection was reset")
        if self.stop_after is not None and self.given >= self.stop_after:
            return b""
        n = min(n if n and n > 0 else 1 << 20, self.total - self.given)
        if n <= 0:
            return b""
        start = self.given
        out = bytearray(n)
        if start < len(self.head):
            piece = self.head[start:start + n]
            out[:len(piece)] = piece
        self.given += n
        return bytes(out)


class Forbidden(io.RawIOBase):
    """A body that must never be read."""

    def readable(self):
        return True

    def read(self, n=-1):
        raise AssertionError("the body was read")
