"""Synthetic recordings for the tests of the media store (runtime/media.py): the first bytes of an MP4, a MOV and a PNG, and a request
body that is generated and never held. No tool is run and no real recording is read. Not a test file.
"""
from __future__ import annotations

import io

MP4_HEAD = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
MOV_HEAD = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  "
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def mp4_head() -> bytes:
    """The first bytes of an MP4 (an `ftyp` box with the brand `isom`)."""
    return MP4_HEAD


def mov_head() -> bytes:
    """The first bytes of a QuickTime file (an `ftyp` box with the brand `qt  `)."""
    return MOV_HEAD


def png_head() -> bytes:
    return PNG_HEAD


def body_of(head: bytes, total: int) -> bytes:
    """`total` bytes that start with `head` and go on with zeros."""
    return head + b"\x00" * (total - len(head))


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
