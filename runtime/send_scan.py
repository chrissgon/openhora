#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What is sent is what is scanned (slice S18, limit L14): the credential scan of the bytes of a file that leaves as an attachment.

The converter of a source turns a file into the text a person reads (it drops scripts and styles, hidden sheets and slides, the properties of a document, embedded objects), and
that text is scanned before a preview is shown. A file that is SENT is its bytes, not that text, so this module scans the bytes by kind, with the standard library only, and
refuses what it cannot read to the end:

  check(data, subtype, scan, markdown=False)   None when the file may go; "secret" when the scan found what looks like a credential in any of it; "refused" when the file could not be
                                               read to the end (a cap was hit, a package holds an embedded object or a part that is not text and not a picture, a stream could not
                                               be inflated, an unknown structure). Both withhold the file. `scan` is workcopy.scan (bytes in; a reason or None out).

  text, csv, html, a Markdown export    the raw bytes, decoded with replacement (also with the NUL bytes of a UTF-16 text taken out)
  docx, xlsx, pptx, any zip package     every part that is XML or text, hidden sheets and slides, comments, the properties and the relationships included, each decompressed within
                                        bounds (PART_MAX per part, TOTAL_MAX in all, PARTS_MAX parts; a name with a `..`, a leading slash or a backslash, an encrypted part,
                                        an embedding, a macro project or any other part that is neither text nor a picture refuses the file); the zip comment too
  pdf                                   the raw bytes (the strings of the document information, the hex and octal escapes read, the NUL bytes of a UTF-16 string taken out), and every
                                        stream with the filter FlateDecode inflated within the same bounds and scanned; a stream that is a picture (/Subtype /Image or an image codec)
                                        is not; a stream with any other filter (ASCII85, LZW, run length, a chain this module does not read), a Flate stream that does not
                                        inflate to its end, an encrypted document, or a cap refuses the file

THE GAPS, said where the reader will look: a credential drawn inside a picture is not seen (an image sent as it is, the media of an Office package, an image stream of a PDF, the text chunks
of a PNG), and neither is a PDF stream compressed with an image codec; a credential that a PDF writer splits across text operators (`(ghp_) Tj (abc) Tj`) is seen only when the converter's
text joins it.

Nothing here keeps, logs or prints a name or a byte. Standard library only. Runs on Python 3.9: python3 runtime/send_scan.py --help
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
import zlib

WINDOW = 4 * 1024 * 1024        # bytes handed to the scan at a time (workcopy.SCAN_MAX is 5 MiB), the windows overlapping by OVERLAP
OVERLAP = 8 * 1024
PART_MAX = 32 * 1024 * 1024     # decompressed bytes of one part of a package, or of one stream of a PDF
TOTAL_MAX = 128 * 1024 * 1024   # decompressed bytes of all of them
PARTS_MAX = 5000                # parts of a package
STREAMS_MAX = 20000             # streams of a PDF
DICT_MAX = 64 * 1024            # the dictionary in front of a stream
TEXT_PARTS = (".xml", ".rels", ".txt", ".json", ".csv", ".vml", ".htm", ".html", ".svg", ".xsl", ".xsd", ".dtd", ".rdf", ".mod", ".xlf")      # parts that are text: scanned
PICTURE_PARTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".emf", ".wmf", ".webp", ".ico")      # parts that are pictures: sent unscanned, the stated gap
IMAGE_CODECS = {"DCTDecode", "DCT", "JPXDecode", "CCITTFaxDecode", "CCF", "JBIG2Decode"}
FLATE = {"FlateDecode", "Fl"}
TEXT_KINDS = ("text", "csv", "html")
PACKAGES = ("docx", "xlsx", "pptx", "ooxml")
ZLIB_HEADS = (b"x\x01", b"x\x5e", b"x\x9c", b"x\xda")
HEX_STRING = re.compile(rb"<([0-9A-Fa-f\s]{8,})>")
OCTAL = re.compile(rb"\\([0-7]{3})")
STREAM = re.compile(rb"(?<!end)stream(?:\r\n|\n|\r)")
OBJECT = re.compile(rb"\d+\s+\d+\s+obj\b")
FILTER = re.compile(rb"/Filter\s*(\[[^\]]*\]|/[^\s/<>\[\]()]+)")
PICTURE = re.compile(rb"/Subtype\s*/Image\b")
XREF = re.compile(rb"/Type\s*/XRef\b")
NAME = re.compile(rb"/([^\s/<>\[\]()]+)")


class Refused(Exception):
    """The file could not be read to the end."""


def _hit(scan, data: bytes) -> bool:
    """Whether the scan finds what looks like a credential in `data` (read in overlapping windows, so a size cap of the scan never lets a large file through unseen), also in the
    text that the NUL bytes of a UTF-16 string leave."""
    views = [data]
    if b"\x00" in data:
        views.append(data.replace(b"\x00", b""))
    for view in views:
        start = 0
        while True:
            if scan(view[start:start + WINDOW]) is not None:
                return True
            if start + WINDOW >= len(view):
                break
            start += WINDOW - OVERLAP
    return False


class _Budget:
    def __init__(self):
        self.total = 0

    def take(self, size: int) -> None:
        self.total += size
        if self.total > TOTAL_MAX:
            raise Refused("the file holds more than can be read")


def _text(scan, data: bytes) -> bool:
    return _hit(scan, data)


def _package(scan, data: bytes) -> bool:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, OSError):
        raise Refused("not a package") from None
    with archive:
        infos = archive.infolist()
        if len(infos) > PARTS_MAX:
            raise Refused("too many parts")
        if archive.comment and _hit(scan, archive.comment):
            return True
        budget = _Budget()
        for info in infos:
            name = info.filename
            lower = name.lower()
            if name.startswith("/") or "\\" in name or ".." in name.split("/") or "\x00" in name:
                raise Refused("a part name that leaves the package")
            if info.flag_bits & 0x1:
                raise Refused("an encrypted part")
            if info.is_dir():
                continue
            if "/embeddings/" in lower or lower.startswith("embeddings/") or "oleobject" in lower or "vbaproject" in lower or "activex" in lower:
                raise Refused("an embedded object")
            ending = "." + lower.rsplit(".", 1)[-1] if "." in lower.rsplit("/", 1)[-1] else ""
            if ending in PICTURE_PARTS:
                continue
            if ending not in TEXT_PARTS:
                raise Refused("a part that is neither text nor a picture")
            if info.file_size > PART_MAX:
                raise Refused("a part too large")
            try:
                with archive.open(info) as part:
                    body = part.read(PART_MAX + 1)
            except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, EOFError, OSError):
                raise Refused("a part that cannot be read") from None
            if len(body) > PART_MAX:
                raise Refused("a part too large")
            budget.take(len(body))
            if _hit(scan, body):
                return True
    return False


def _inflate(body: bytes, budget: _Budget) -> bytes:
    """The whole of a zlib stream, within bounds; Refused when it is cut short, is not zlib or inflates past the cap."""
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(body, PART_MAX + 1)
        if inflater.unconsumed_tail or len(out) > PART_MAX:
            raise Refused("a stream too large")
        out += inflater.flush()
    except zlib.error:
        raise Refused("a stream that does not inflate") from None
    if not inflater.eof:
        raise Refused("a stream cut short")
    budget.take(len(out))
    return out


def _strings(data: bytes) -> bytes:
    """What the strings of a PDF say, read: the hex strings decoded, the octal escapes turned into their bytes."""
    extra = []
    for found in HEX_STRING.finditer(data):
        digits = re.sub(rb"\s", b"", found.group(1))
        if len(digits) % 2:
            digits += b"0"
        extra.append(bytes.fromhex(digits.decode("ascii")))
    if OCTAL.search(data):
        extra.append(OCTAL.sub(lambda m: bytes([int(m.group(1), 8) & 0xFF]), data))
    return b"\n".join(extra)


def _pdf(scan, data: bytes) -> bool:
    if _hit(scan, data) or _hit(scan, _strings(data)):
        return True
    budget = _Budget()
    streams, last = 0, 0
    for opening in STREAM.finditer(data):
        if opening.start() < last:      # the word inside the body of a stream already read
            continue
        streams += 1
        if streams > STREAMS_MAX:
            raise Refused("too many streams")
        begin = opening.end()
        end = data.find(b"endstream", begin)
        if end < 0:
            raise Refused("a stream with no end")
        last = end
        head = data[max(0, opening.start() - DICT_MAX):opening.start()]
        starts = [m.start() for m in OBJECT.finditer(head)]
        dictionary = head[starts[-1]:] if starts else head
        if b"/Encrypt" in dictionary:
            raise Refused("an encrypted stream")
        body = data[begin:end]
        found = FILTER.search(dictionary)
        if found is None:
            if body[:2] in ZLIB_HEADS:      # no filter named (a key spelled with an escape, say) and a zlib head: read it as one
                try:
                    inflated = _inflate(body, budget)
                except Refused:
                    continue
                if _hit(scan, inflated) or _hit(scan, _strings(inflated)):
                    return True
            continue
        if b"#" in found.group(1):
            raise Refused("a filter spelled with an escape")
        filters = [m.group(1).decode("ascii", "replace") for m in NAME.finditer(found.group(1))]
        if filters and all(f in IMAGE_CODECS for f in filters):
            continue      # a picture codec: the stated gap
        if PICTURE.search(dictionary) and filters and filters[0] in FLATE:
            continue      # the picture's pixels, deflated: the stated gap
        if XREF.search(dictionary):
            continue      # offsets, not text (they are written with a predictor)
        if not filters or filters[0] not in FLATE:
            raise Refused("a stream with a filter this module does not read")
        if any(f not in FLATE and f not in IMAGE_CODECS for f in filters[1:]):
            raise Refused("a chain of filters this module does not read")
        if b"/Predictor" in dictionary:
            raise Refused("a stream with a predictor")
        inflated = _inflate(body, budget)
        if len(filters) == 1 and (_hit(scan, inflated) or _hit(scan, _strings(inflated))):
            return True
    return False


def check(data: bytes, subtype: str, scan, markdown: bool = False):
    """None when the file may go, "secret" when the scan found what looks like a credential in it, "refused" when it could not be read to the end (module text)."""
    try:
        if markdown or subtype in TEXT_KINDS:
            found = _text(scan, data)
        elif subtype == "pdf":
            found = _pdf(scan, data)
        elif subtype in PACKAGES:
            found = _package(scan, data)
        else:
            return "refused"
    except Refused:
        return "refused"
    except Exception:      # noqa: BLE001 - an unknown structure is a file that is not sent
        return "refused"
    return "secret" if found else None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
