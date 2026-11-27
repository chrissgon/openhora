#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The store of a video's licensed pictures and the rules around it (package V9b-3a, decisions D5, D9, D10, D12 and D14 of the V9b spec): the folder
`<data_dir>/media/<id>/stock/`, the set document the person approves, the approval, the credits and the retention. It calls no provider and runs no process:
the operations that search and fetch are runtime/ops_media_stock.py; the step kind reads the result through the media store (runtime/media.py names the files it may
read, `stock/...`), never through this module (limit L30).

The folder (mode 0700, every file 0600 or 0400, opened without following a link, as runtime/media.py does):

  prev-*            the previews a search brought (one per candidate; a source's own picture, at most 1 MiB)
  full-*            the full file of a pick, as the library gave it (never served, never rendered: the renderer normalises it)
  quarantine/       the files of the open web: the previews a web search brought and the files fetched from it (V9b-3b); a file leaves it only at the set approval
  asset-<sha12>.png or .mp4  the pictures and clips the renderer made from the picks, the only files a render may use
  sheet-preview.png and sheet.png    the contact sheets the renderer made of the previews and of the picks
  set.json          what `video-media-find` found and `video-media-fetch-picks` fetched (phase `found`, then `fetched`)
  approved.json     the approval of the set: its hash, the time, the sources in force, the assets, and `unverified` (each open-web asset's own approval)

The set document (`set_document`) is what the person approves and what `set_hash` hashes: `{"version", "task", "assets", "credits"}`, canonical JSON. An approval
holds for exactly that hash; a changed pick, a second find or a second fetch voids it. The licence policy is the tuples below (decision 3), the same as
providers/stock/_stock.py (a test compares them): an asset is used only when its licence is in LICENCES_ACCEPTED, or it is `unverified` and has its own approval.

No source is named here: the sources are the implementations of the class `stock:media` that providers/resolve.py lists and their data files
(providers/stock/sources/<name>.json), read as data. The default list, when a project names none, is every source whose file says it needs no key.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import captions  # noqa: E402
import media  # noqa: E402
import project_config  # noqa: E402

CLASS = "stock:media"
SOURCES = ("providers", "stock", "sources")
# The licence policy (the maintainer's decision 3, amended 2026-11-11 for CC BY 2.0 and 2.5). providers/stock/_stock.py holds the same two tuples; a test compares them. The two
# libraries' own licence ids are written whole; the grep test of providers/stock/tests/test_stock_registration.py strips them before it looks for a source's name.
LICENCES_ACCEPTED = ("pexels-license", "pixabay-content-license", "cc0-1.0", "pdm-1.0", "cc-by-4.0", "cc-by-3.0", "cc-by-2.5", "cc-by-2.0")
LICENCES_CREDIT = ("cc-by-4.0", "cc-by-3.0", "cc-by-2.5", "cc-by-2.0")
UNVERIFIED = "unverified"        # the licence id of a candidate whose licence nobody checked: never in LICENCES_ACCEPTED
TIERS = ("library", "per-item", "unverified")
SEARCH = captions.SEARCH
KINDS = captions.WANT_KINDS

MAX_SLOTS = captions.STOCK_SLOTS_MAX                  # at most 6 slots a video
PER_SOURCE = 2                                        # candidates one source gives a slot
PER_SLOT = 6                                          # candidates a slot keeps after the merge
MAX_PREVIEWS = 36                                     # previews of a video (the sheet's tiles)
MAX_FULL = 6
MAX_FULL_BYTES = 400 * 1024 * 1024                    # the full files of a video together
MAX_CALLS = 40                                        # API calls of a video
MIB = 1024 * 1024
KIND_BYTES = {"image": 16 * MIB, "clip": 64 * MIB}   # the clip cap = limits.asset_max_bytes of providers/renderer/renderer-presets.json (a test compares)
PREVIEW_MAX_SIDE = 8192                               # = limits.asset_max_side of providers/renderer/renderer-presets.json (a test compares)
PREVIEW_MAX_PIXELS = 40_000_000                       # = limits.asset_max_pixels of providers/renderer/renderer-presets.json (a test compares)
CLIP_SECONDS_MAX = 10.0                               # = providers/renderer/_media.py CLIP_MAX_SECONDS (a test compares)
SET, APPROVED, SHEET, SHEET_PREVIEW = "set.json", "approved.json", "sheet.png", "sheet-preview.png"
SCAN = "scan.json"                                    # P9-a: what the scan of the set's files read (text and QR codes): kept here, never served, never in the set document or its hash
SCAN_VERSION = 1
EXPLAINED = "scan-explained.json"                     # P9-a3: what the model that was asked to explain the text found said (the one route of limit L83): kept here beside `scan.json`, never served, never in the set document or its hash, never a name a step may read
EXPLAINED_VERSION = 1
EXPLAIN_SOURCES = ("text", "qr")                      # = skills/mkt-video-media-explain/scripts/check_explained.py SOURCES, CONCERNS, MAX_QUOTE, MAX_EXPLANATION, MAX_FINDINGS (a test compares)
EXPLAIN_CONCERNS = ("licence_mark", "contact", "link", "brand", "claim", "language", "sensitive", "none", "unclear")
EXPLAIN_QUOTE_MAX, EXPLAIN_TEXT_MAX, EXPLAIN_FINDINGS_MAX = 200, 240, 12
SCAN_LINES_MAX, SCAN_LINE_MAX, SCAN_CHARS_MAX, SCAN_QR_MAX, SCAN_QR_TEXT_MAX = 8, 160, 600, 4, 120      # validity: = providers/renderer/_scan.py TEXT_LINES_MAX, LINE_MAX, TEXT_CHARS_MAX, QR_MAX, QR_TEXT_MAX (a test compares)
SCAN_FRAMES_MAX = 601                                 # = providers/renderer/_host.py SCAN_FRAMES_MAX
QUARANTINE = media.STOCK_QUARANTINE
SET_VERSION = 1
DOC_LIMIT = 2 * MIB
ASSET_FILE = re.compile(r"asset-([0-9a-f]{12})\.(png|mp4)")
SERVED_ASSET = re.compile(r"asset-[0-9a-f]{12}\.png")   # a clip is never served: the page shows the sheet
PROVIDER_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,200}")      # the name a provider gave a file inside the folder
SHA256 = re.compile(r"[0-9a-f]{64}")
SOURCE_NAME = re.compile(r"[a-z][a-z0-9]{1,30}")
SERVED = (SHEET, SHEET_PREVIEW)                       # plus ASSET_FILE: the only files the page is given (the ones the container made)
CREDITS_FOLDER = "credits"
CREDIT_MAX = 600                                      # = runtime/deliver_document.py CREDIT_MAX (a test compares)
CREDITS_DAYS = 365
CREDITS_NAME = re.compile(r"[0-9]{1,9}\.json")
DAY = 86400.0
NOFOLLOW, DIRECTORY = getattr(os, "O_NOFOLLOW", 0), getattr(os, "O_DIRECTORY", 0)

SCAN_CODES = ("text_found", "qr_link", "qr_action", "qr_text", "qr_unreadable", "scan_partial")      # = providers/renderer/_scan.py SCAN_CODES (a test compares)
SCAN_REASONS = ("timeout", "container_failed", "container_result_invalid", "not_ready", "no_space")      # why a scan did not run: the closed words a row carries
SCAN_SCHEMES = ("tel", "mailto", "sms", "geo", "WIFI")
SCAN_HOST = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?){1,8}")      # = runtime/deliver_document.py HOST

CC_NAMES = {"cc0-1.0": ("CC0", "1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
            "pdm-1.0": ("Public Domain Mark", "1.0", "https://creativecommons.org/publicdomain/mark/1.0/")}
CC_BY_URL = "https://creativecommons.org/licenses/by/%s/"


class StockError(Exception):
    """A refusal of the store, with a closed `code`: usage, not_found, unreadable, no_space, too_many_slots, no_set, stale."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


# --- the licence tuples and the credit line ----------------------------------------------------------------------------------------------------


def licence_name(licence: str):
    """(name, version, url) of a licence id of the accepted tuple, or None: `cc-by-3.0` is ("CC BY", "3.0", "https://creativecommons.org/licenses/by/3.0/")."""
    if licence in CC_NAMES:
        return CC_NAMES[licence]
    found = re.fullmatch(r"cc-by-([0-9]\.[0-9])", licence or "")
    if found and licence in LICENCES_CREDIT:
        return ("CC BY", found.group(1), CC_BY_URL % found.group(1))
    return None


def credit_line(asset: dict) -> str:
    """The credit a credit licence asks for, built by code: `"<title or 'Untitled'>" by <author>, <licence name> <version> (<licence URL>), via <source> (<page link>)`
    (decision D12). `page` is the library's own page for the item, when it gave one."""
    name, version, url = licence_name(asset["licence"])
    one = lambda text, limit: " ".join(str(text or "").split())[:limit]      # noqa: E731  (one line, capped: every credit line fits CREDIT_MAX)
    title, author, page = one(asset.get("title"), 100) or "Untitled", one(asset.get("author"), 100), one(asset.get("page"), 300)
    line = lambda tail: "\"%s\" by %s, %s %s (%s), via %s%s" % (title, author, name, version, url, one(asset["source"], 31), tail)      # noqa: E731
    found = line(" (%s)" % page if page else "")
    return found if len(found) <= CREDIT_MAX else line("")


def credits_of(assets) -> list:
    """The credit lines of the assets whose licence asks for one, in the order of the assets (a CC0 or a library's own licence puts none)."""
    return [credit_line(a) for a in assets if a.get("licence") in LICENCES_CREDIT]


def needs_credit(licence) -> bool:
    return licence in LICENCES_CREDIT


# --- canonical documents ----------------------------------------------------------------------------------------------------------------------


def canonical(doc) -> bytes:
    """The canonical JSON bytes of a document: keys sorted, no spaces, non-ASCII kept as UTF-8 (what `set_hash` hashes, and what the step kind hashes again)."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


ASSET_KEYS = ("slot", "show", "search", "source", "item", "kind", "licence", "licence_url", "terms_read_on", "author", "title", "page", "licence_claim", "sha256",
              "width", "height", "seconds", "unverified")


def set_document(found: dict) -> dict:
    """The document the person approves, from a fetched set: `{"version", "task", "assets", "credits"}`. The `assets` are the picks the renderer normalised, in the order
    of their slots, each with its licence, its source, its sha256 and what the credit line needs; `credits` are the lines `credits_of` built when the files were fetched
    (the set keeps them, so the step kind hashes the same document without this module: runtime/step_media.py `stock_hash`, a test compares the two)."""
    assets = [{k: a.get(k) for k in ASSET_KEYS} for a in sorted(found.get("assets") or [], key=lambda a: a["slot"])]
    credits = found.get("credits")
    return {"version": SET_VERSION, "task": found["task"], "assets": assets, "credits": list(credits) if isinstance(credits, list) else credits_of(assets)}


def set_hash(doc: dict) -> str:
    """The sha256 of the set document's canonical JSON: the hash an approval binds."""
    return hashlib.sha256(canonical(doc)).hexdigest()


def approval_matches(found, approved) -> bool:
    """Whether `approved` (approved.json) is the approval of this fetched set: its hash equals the hash of the set's document."""
    return (isinstance(found, dict) and found.get("phase") == "fetched" and isinstance(approved, dict)
            and approved.get("hash") == set_hash(set_document(found)) and approved.get("task") == found.get("task"))


def pick_of(candidate: dict) -> str:
    """The pick string of a candidate: `<source>:<item>`."""
    return "%s:%s" % (candidate["source"], candidate["item"])


# --- the folder -------------------------------------------------------------------------------------------------------------------------------


def folder_of(data_dir: str, rid: str) -> str:
    """The stock folder of a recording: `<data_dir>/media/<id>/stock`."""
    return os.path.join(media.folder_of(data_dir, rid), media.STOCK_DIR)


def _stock_error(e: "media.MediaError") -> "StockError":
    return StockError(str(e), "not_found" if e.code == "not_found" else "usage" if e.code == "usage" else "unreadable")


@contextlib.contextmanager
def _open(data_dir: str, rid: str, create: bool = False):
    """The descriptor of the stock folder, opened without following a link; with `create` the folder is made (mode 0700) when it is not there. A folder that is not
    ours (a link, another mode) is refused."""
    if media.references.in_reference(folder_of(data_dir, rid)):
        raise StockError("a picture in a reference store is looked at, never used", "usage")
    try:
        top = media._open_folder(data_dir, rid)
    except media.MediaError as e:
        raise _stock_error(e) from None
    try:
        if create:
            try:
                os.mkdir(media.STOCK_DIR, 0o700, dir_fd=top)
            except FileExistsError:
                pass
            except OSError:
                raise StockError("the stock folder cannot be made", "unreadable") from None
        try:
            fd = os.open(media.STOCK_DIR, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=top)
        except FileNotFoundError:
            raise StockError("there is no stock folder", "not_found") from None
        except OSError:
            raise StockError("the stock folder cannot be opened", "unreadable") from None
    finally:
        os.close(top)
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise StockError("the stock folder is not ours", "unreadable")
        if info.st_mode & 0o077:
            os.fchmod(fd, 0o700)
        yield fd
    finally:
        os.close(fd)


def ensure_folder(data_dir: str, rid: str) -> str:
    """Make the stock folder (0700) of a recording when it is not there, and return its path. `not_found` for a recording that is not in the store."""
    with _open(data_dir, rid, create=True):
        pass
    return folder_of(data_dir, rid)


def _write_in(fd: int, name: str, data: bytes, mode: int) -> None:
    temporary = ".%s.part" % name
    try:
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | NOFOLLOW, 0o600, dir_fd=fd)
    except OSError:
        raise StockError("that file cannot be written", "unreadable") from None
    try:
        os.fchmod(out, mode)
        with os.fdopen(out, "wb", closefd=False) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temporary, dir_fd=fd)
        raise StockError("that file cannot be written", "no_space") from None
    finally:
        os.close(out)
    os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)


def write_doc(data_dir: str, rid: str, name: str, doc: dict) -> str:
    """Write `set.json`, `approved.json`, `scan.json` or `scan-explained.json` whole (a temporary file, then a rename, mode 0600). Returns the sha256 of the bytes."""
    if name not in (SET, APPROVED, SCAN, EXPLAINED):
        raise StockError("that is not a document of the stock folder", "usage")
    data = (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > DOC_LIMIT:
        raise StockError("that document is too large", "usage")
    with _open(data_dir, rid, create=True) as fd:
        _write_in(fd, name, data, 0o600)
    return hashlib.sha256(data).hexdigest()


def _read_scan_bytes(data_dir: str, rid: str, name: str = SCAN):
    """The bytes of `scan.json` or `scan-explained.json` (a plain file with one link, at most DOC_LIMIT), or None when it is not there or there is no stock folder."""
    try:
        with _open(data_dir, rid) as fd:
            try:
                handle = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                return None
            except OSError:
                raise StockError("that file cannot be read", "unreadable") from None
            try:
                info = os.fstat(handle)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > DOC_LIMIT:
                    raise StockError("that file cannot be read", "unreadable")
                with os.fdopen(handle, "rb", closefd=False) as f:
                    return f.read(DOC_LIMIT + 1)
            finally:
                os.close(handle)
    except StockError as e:
        if e.code == "not_found":
            return None
        raise


def read_doc(data_dir: str, rid: str, name: str):
    """`set.json`, `approved.json`, `scan.json` or `scan-explained.json` as a dict, or None when it is not there; `unreadable` for a file that is not JSON or not an object."""
    if name not in (SET, APPROVED, SCAN, EXPLAINED):
        raise StockError("that is not a document of the stock folder", "usage")
    try:
        data = _read_scan_bytes(data_dir, rid, name) if name in (SCAN, EXPLAINED) else media.read_work(data_dir, rid, "stock/" + name, DOC_LIMIT)      # scan.json is not a name a step may read (media.STOCK_FILE): only this module opens it
    except media.MediaError as e:
        if e.code == "not_found":
            return None
        raise _stock_error(e) from None
    if data is None:
        return None
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise StockError("that document cannot be read", "unreadable") from None
    if not isinstance(doc, dict):
        raise StockError("that document cannot be read", "unreadable")
    return doc


def _scan_text(value, limit: int) -> str:
    """One line of text the scan read, as the host keeps it: printable characters only (a control, bidi or zero-width character is not), whitespace collapsed, cut."""
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())[:limit] if isinstance(value, str) else ""


def _scan_int(value, high: int) -> int:
    return value if type(value) is int and 0 <= value <= high else 0


def clean_scan_entry(raw) -> "dict | None":
    """One file's entry of `scan.json` read as untrusted (P9-a): the closed codes, the counts, the QR kinds with a host or a scheme, and the text as at most 8 lines of 160 characters and 600 in all,
    each cleaned again. None when it is not an object."""
    if not isinstance(raw, dict):
        return None
    codes = [c for c in raw.get("codes") or [] if c in SCAN_CODES] if isinstance(raw.get("codes"), list) else []
    text = raw.get("text") if isinstance(raw.get("text"), dict) else {}
    lines, total = [], 0
    for line in (text.get("lines") if isinstance(text.get("lines"), list) else [])[:SCAN_LINES_MAX]:
        line = _scan_text(line, SCAN_LINE_MAX)
        if line and total + len(line) <= SCAN_CHARS_MAX:
            lines.append(line)
            total += len(line)
    qr = []
    for q in (raw.get("qr") if isinstance(raw.get("qr"), list) else [])[:SCAN_QR_MAX]:
        if not isinstance(q, dict) or q.get("kind") not in ("link", "action", "text"):
            continue
        host = q.get("host") if isinstance(q.get("host"), str) and SCAN_HOST.fullmatch(q["host"]) else None
        scheme = q.get("scheme") if q.get("scheme") in SCAN_SCHEMES else None
        qr.append({"kind": q["kind"], "host": host if q["kind"] == "link" else None, "scheme": scheme if q["kind"] == "action" else None,
                   "text": _scan_text(q.get("text"), SCAN_QR_TEXT_MAX) or None if q["kind"] == "text" else None,
                   "first_frame": _scan_int(q.get("first_frame"), SCAN_FRAMES_MAX), "frames": _scan_int(q.get("frames"), SCAN_FRAMES_MAX)})
    return {"kind": "clip" if raw.get("kind") == "clip" else "image", "frames": _scan_int(raw.get("frames"), SCAN_FRAMES_MAX), "frames_qr": _scan_int(raw.get("frames_qr"), SCAN_FRAMES_MAX),
            "frames_text": _scan_int(raw.get("frames_text"), SCAN_FRAMES_MAX), "frames_changed": _scan_int(raw.get("frames_changed"), SCAN_FRAMES_MAX), "partial": raw.get("partial") is True,
            "codes": sorted(set(codes)), "text": {"lines": lines, "chars": _scan_int(text.get("chars"), 10 ** 7), "cut": text.get("cut") is True}, "qr": qr}


def read_scan(data_dir: str, rid: str) -> dict:
    """`scan.json` of the stock folder, read as untrusted and cleaned: {"scanner": {...}, "assets": {sha256: entry}, "failed": a closed reason or None, "at"}; empty `assets` when there is none."""
    doc = read_doc(data_dir, rid, SCAN) or {}
    scanner = doc.get("scanner") if isinstance(doc.get("scanner"), dict) else {}
    assets = {}
    for digest, raw in (doc.get("assets") if isinstance(doc.get("assets"), dict) else {}).items():
        entry = clean_scan_entry(raw) if isinstance(digest, str) and SHA256.fullmatch(digest) else None
        if entry is not None:
            assets[digest] = entry
    return {"version": SCAN_VERSION, "scanner": {k: _scan_text(scanner.get(k), 80) for k in ("image", "lang", "tesseract", "opencv")}, "assets": assets,
            "failed": doc.get("failed") if doc.get("failed") in SCAN_REASONS else None, "at": _scan_text(doc.get("at"), 40)}


def scan_digest(doc: dict):
    """The sha256 of a scan document's canonical JSON, or None when it holds no file: what `approved.json` records of what the person was shown."""
    return hashlib.sha256(canonical(doc)).hexdigest() if doc.get("assets") else None


def explain_items(assets, doc: dict) -> list:
    """What the scan of the set's files read that a model could be asked to explain (P9-a3): for each asset (sorted by slot) whose entry of `read_scan`'s `doc` holds text lines (its code `text_found`) or QR
    items with a host, a scheme or a text, {"slot", "sha256", "source", "lines": [text], "qr": [{"kind": "link", "host"} | {"kind": "action", "scheme"} | {"kind": "text", "text"}]}; everything was cleaned
    when it was read. A link whose host could not be read, an unreadable code and a clean file give nothing. The picture, a frame, the slot's search words and the rest of the asset's record are never in it."""
    out = []
    for a in sorted(assets, key=lambda a: a["slot"]):
        entry = (doc.get("assets") or {}).get(a["sha256"])
        if entry is None:
            continue
        lines = list(entry["text"]["lines"]) if "text_found" in entry["codes"] else []
        qr, seen = [], set()
        for q in entry["qr"]:
            item = ({"kind": "link", "host": q["host"]} if q["kind"] == "link" and q["host"] else {"kind": "action", "scheme": q["scheme"]} if q["kind"] == "action" and q["scheme"]
                    else {"kind": "text", "text": q["text"]} if q["kind"] == "text" and q["text"] else None)
            if item is not None and tuple(sorted(item.items())) not in seen:
                seen.add(tuple(sorted(item.items())))
                qr.append(item)
        if lines or qr:
            out.append({"slot": a["slot"], "sha256": a["sha256"], "source": a["source"], "lines": lines, "qr": qr})
    return out


def clean_findings(raw) -> list:
    """The findings of one file of `scan-explained.json` read as untrusted (P9-a3): at most EXPLAIN_FINDINGS_MAX, each with a source and a concern from the closed lists, the quote and the explanation
    cleaned again and cut; a finding that is not of that shape is left out."""
    out = []
    for f in (raw if isinstance(raw, list) else [])[:EXPLAIN_FINDINGS_MAX]:
        if not (isinstance(f, dict) and f.get("source") in EXPLAIN_SOURCES and f.get("concern") in EXPLAIN_CONCERNS):
            continue
        quote, explanation = _scan_text(f.get("quote"), EXPLAIN_QUOTE_MAX), _scan_text(f.get("explanation"), EXPLAIN_TEXT_MAX)
        if quote and explanation:
            out.append({"source": f["source"], "quote": quote, "concern": f["concern"], "explanation": explanation})
    return out


def read_explained(data_dir: str, rid: str) -> dict:
    """`scan-explained.json` of the stock folder, read as untrusted and cleaned: {"model", "assets": {sha256: [finding]}, "at"}; empty `assets` when there is none. What a model said about the text
    a scan read (limit L83): shown on this computer's page as "not checked", never an input of anything."""
    doc = read_doc(data_dir, rid, EXPLAINED) or {}
    assets = {}
    for digest, raw in (doc.get("assets") if isinstance(doc.get("assets"), dict) else {}).items():
        found = clean_findings(raw) if isinstance(digest, str) and SHA256.fullmatch(digest) else []
        if found:
            assets[digest] = found
    return {"version": EXPLAINED_VERSION, "model": _scan_text(doc.get("model"), 80), "assets": assets, "at": _scan_text(doc.get("at"), 40)}


def read_served(data_dir: str, rid: str, name: str, limit: int = 32 * MIB) -> bytes:
    """The bytes of a file the page may be given: only `sheet-preview.png`, `sheet.png` and `asset-<sha12>.png` (the files the container made), never a preview, a full
    file or a file of the quarantine, whatever their names. A file that is not a PNG by its header is refused."""
    if not isinstance(name, str) or not (name in SERVED or SERVED_ASSET.fullmatch(name)):
        raise StockError("that file is not one the page may be given", "usage")
    try:
        data = media.read_work(data_dir, rid, "stock/" + name, limit)
    except media.MediaError as e:
        raise _stock_error(e) from None
    if len(data) > limit or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise StockError("that file is not a picture", "unreadable")
    return data


def asset_name(asset: dict) -> str:
    """The file name of an approved asset in the stock folder: `asset-<sha12>.mp4` for a clip, `asset-<sha12>.png` for a picture."""
    return "asset-%s.%s" % (asset["sha256"][:12], "mp4" if asset.get("kind") == "clip" else "png")


def names(data_dir: str, rid: str) -> list:
    """The names in the stock folder (files and folders), sorted; [] when there is none."""
    try:
        with _open(data_dir, rid) as fd:
            return sorted(os.listdir(fd))
    except StockError as e:
        if e.code == "not_found":
            return []
        raise


def file_facts(data_dir: str, rid: str, name: str):
    """(sha256, size) of a regular file of the stock folder (opened without following a link), or None when it is not there."""
    if not PROVIDER_FILE.fullmatch(name or ""):
        raise StockError("that is not a name of the stock folder", "usage")
    with _open(data_dir, rid) as fd:
        try:
            handle = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise StockError("that file cannot be read", "unreadable") from None
        try:
            info = os.fstat(handle)
            if not stat.S_ISREG(info.st_mode):
                raise StockError("that file is not a plain file", "unreadable")
            digest = hashlib.sha256()
            with os.fdopen(handle, "rb", closefd=False) as f:
                while True:
                    chunk = f.read(MIB)
                    if not chunk:
                        break
                    digest.update(chunk)
            return digest.hexdigest(), info.st_size
        finally:
            os.close(handle)


def _png_size(data: bytes):
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None


def _jpeg_size(data: bytes):
    if not data.startswith(b"\xff\xd8"):
        return None
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:                                  # fill byte
            i += 1
            continue
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:      # no length
            i += 2
            continue
        if marker in (0xD9, 0xDA):                          # end of image or start of scan before any frame header
            return None
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2:
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if length < 8 or i + 9 > n:
                return None
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + length
    return None


def image_size(data_dir: str, rid: str, name: str, quarantine: bool = False):
    """(width, height) of a PNG or JPEG file of the stock folder (or of its quarantine), read from the file's own header bytes, or None when the file is not one the reader
    understands (not a PNG or a JPEG, truncated, malformed). The file is opened without following a link and must be a regular file; at most KIND_BYTES["image"] bytes are read."""
    if not PROVIDER_FILE.fullmatch(name or ""):
        raise StockError("that is not a name of the stock folder", "usage")
    with _open(data_dir, rid) as fd:
        sub = None
        try:
            if quarantine:
                try:
                    sub = os.open(QUARANTINE, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=fd)
                except OSError:
                    raise StockError("that file cannot be read", "unreadable") from None
            try:
                handle = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=sub if sub is not None else fd)
            except FileNotFoundError:
                return None
            except OSError:
                raise StockError("that file cannot be read", "unreadable") from None
            try:
                if not stat.S_ISREG(os.fstat(handle).st_mode):
                    raise StockError("that file is not a plain file", "unreadable")
                with os.fdopen(handle, "rb", closefd=False) as f:
                    data = f.read(KIND_BYTES["image"])
            finally:
                os.close(handle)
        finally:
            if sub is not None:
                os.close(sub)
    return _png_size(data) or _jpeg_size(data)


def remove_where(data_dir: str, rid: str, wanted) -> int:
    """Remove every entry of the stock folder whose name `wanted(name)` accepts (a folder with its content; never a link followed). `set.json` and `approved.json` are
    never removed here. Returns how many entries went."""
    count = 0
    try:
        with _open(data_dir, rid) as fd:
            for name in sorted(os.listdir(fd)):
                if name in (SET, APPROVED) or name.startswith(".") and name.endswith(".part") or not wanted(name):
                    continue
                if media._remove_tree(fd, name):
                    count += 1
    except StockError as e:
        if e.code != "not_found":
            raise
    return count


def clear_candidates(data_dir: str, rid: str, keep=()) -> int:
    """Remove the previews, the full files, the contact sheets, the scratch folders and the quarantine, and every `asset-*` not in `keep` (a new find, a new fetch, the
    set approval). The set, the approval and the pictures in `keep` stay."""
    kept = set(keep)
    return remove_where(data_dir, rid, lambda n: n not in kept and (n.startswith(("prev-", "full-", ".work")) or n in SERVED or n == QUARANTINE
                                                                     or ASSET_FILE.fullmatch(n) is not None))


def clear_licensed(data_dir: str, rid: str) -> int:
    """What a new `video-media-find` removes (V9b-3b): the licensed previews, the full files, the contact sheets, the scratch folders and every `asset-*`. The quarantine stays (the web
    candidates of the set that are carried over)."""
    return remove_where(data_dir, rid, lambda n: n.startswith(("prev-", "full-", ".work")) or n in SERVED or n in (SCAN, EXPLAINED) or ASSET_FILE.fullmatch(n) is not None)


def clear_web(data_dir: str, rid: str) -> int:
    """What a new `video-media-websearch` removes (V9b-3b): the quarantine, the full files, the contact sheets, the scratch folders and every `asset-*`. The licensed previews stay (the
    licensed candidates of the set that are carried over)."""
    return remove_where(data_dir, rid, lambda n: n == QUARANTINE or n.startswith(("full-", ".work")) or n in SERVED or n in (SCAN, EXPLAINED) or ASSET_FILE.fullmatch(n) is not None)


def prune_quarantine(data_dir: str, rid: str, keep) -> int:
    """Remove every file of the quarantine whose name is not in `keep` (a preview no candidate of the merged set kept). Returns how many went; 0 when there is no quarantine."""
    kept, count = set(keep), 0
    try:
        with _open(data_dir, rid) as fd:
            try:
                sub = os.open(QUARANTINE, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=fd)
            except OSError:
                return 0
            try:
                for name in sorted(os.listdir(sub)):
                    if name not in kept and media._remove_tree(sub, name):
                        count += 1
            finally:
                os.close(sub)
    except StockError as e:
        if e.code != "not_found":
            raise
    return count


def void_approval(data_dir: str, rid: str) -> bool:
    """Remove the approval of the set (a pick changed, a second find or fetch). True when there was one."""
    try:
        with _open(data_dir, rid) as fd:
            try:
                os.stat(APPROVED, dir_fd=fd, follow_symlinks=False)
            except OSError:
                return False
            return media._remove_tree(fd, APPROVED)
    except StockError as e:
        if e.code == "not_found":
            return False
        raise


def remove_all(data_dir: str, rid: str) -> None:
    """Remove the whole stock folder of a recording (the recording's removal does it too: this is for a new set that starts over)."""
    try:
        top = media._open_folder(data_dir, rid)
    except media.MediaError:
        return
    try:
        media._remove_tree(top, media.STOCK_DIR)
    finally:
        os.close(top)


def make_scratch(data_dir: str, rid: str):
    """A new scratch folder `.work-<hex>` (0700) inside the stock folder, for a container's output: (name, path)."""
    name = ".work-%s" % os.urandom(6).hex()
    with _open(data_dir, rid, create=True) as fd:
        try:
            os.mkdir(name, 0o700, dir_fd=fd)
        except OSError:
            raise StockError("the scratch folder cannot be made", "unreadable") from None
    return name, os.path.join(folder_of(data_dir, rid), name)


def adopt(data_dir: str, rid: str, scratch: str, moves: dict) -> None:
    """Move files out of a scratch folder into the stock folder under their final names (`{scratch name: final name}`), each renamed inside the one filesystem; the
    scratch folder is then removed. A source that is not a regular file of the scratch folder is refused."""
    with _open(data_dir, rid) as fd:
        try:
            sub = os.open(scratch, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=fd)
        except OSError:
            raise StockError("the scratch folder cannot be opened", "unreadable") from None
        try:
            for source, final in sorted(moves.items()):
                try:
                    info = os.stat(source, dir_fd=sub, follow_symlinks=False)
                except OSError:
                    raise StockError("a file the renderer named is not there", "not_found") from None
                if not stat.S_ISREG(info.st_mode):
                    raise StockError("a file the renderer named is not a plain file", "unreadable")
                os.replace(source, final, src_dir_fd=sub, dst_dir_fd=fd)
        finally:
            os.close(sub)
        media._remove_tree(fd, scratch)


# --- the credits record -----------------------------------------------------------------------------------------------------------------------


def credits_folder(data_dir: str) -> str:
    return os.path.join(media.root_of(data_dir), CREDITS_FOLDER)


def write_credits(data_dir: str, task: int, doc: dict) -> None:
    """The credits record of a task, `<data_dir>/media/credits/<task>.json` (0600): the set document without `show` and `search`, the credits, and each open-web asset's page
    link and claimed licence. Kept CREDITS_DAYS after its last write (the set approval), apart from the recording's folder."""
    if type(task) is not int or task < 0:
        raise StockError("a task id is a whole number", "usage")
    root = media.root_of(data_dir)
    os.makedirs(root, mode=0o700, exist_ok=True)
    folder = credits_folder(data_dir)
    try:
        os.mkdir(folder, 0o700)
    except FileExistsError:
        pass
    except OSError:
        raise StockError("the credits folder cannot be made", "unreadable") from None
    try:
        fd = os.open(folder, os.O_RDONLY | DIRECTORY | NOFOLLOW)
    except OSError:
        raise StockError("the credits folder cannot be opened", "unreadable") from None
    try:
        if doc.get("delivered_at") is None and (read_credits(data_dir, task) or {}).get("delivered_at"):
            doc = dict(doc, delivered_at=read_credits(data_dir, task)["delivered_at"])      # an approval after the delivery keeps the delivery's time: the later of the two counts
        _write_in(fd, "%d.json" % task, (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"), 0o600)
    finally:
        os.close(fd)


def read_credits(data_dir: str, task: int):
    """The credits record of a task, or None when there is none (or it is not readable)."""
    try:
        fd = os.open(os.path.join(credits_folder(data_dir), "%d.json" % task), os.O_RDONLY | NOFOLLOW)
    except (OSError, TypeError):
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > DOC_LIMIT:
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            doc = json.loads(f.read(DOC_LIMIT + 1).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError):
        return None
    finally:
        os.close(fd)
    return doc if isinstance(doc, dict) else None


def credits_record(found: dict, document: dict, recording: str, now=None) -> dict:
    """The credits record: the set document without the words the person typed (`show`, `search`), plus, for each open-web asset, its page link and claimed licence
    (which the document itself does not bind: the delivery document holds only their host and the hash of the link)."""
    assets = [{k: v for k, v in a.items() if k not in ("show", "search")} for a in document["assets"]]
    return {"version": SET_VERSION, "task": document["task"], "recording": recording, "approved_at": now_stamp(now), "delivered_at": None,
            "providers": [{"source": s, "link": l} for s, l in sorted({a["source"]: a.get("source_link") or "" for a in found.get("assets") or []
                                                                         if a.get("licence") != UNVERIFIED}.items())], "assets": assets, "credits": list(document["credits"]),
            "web": [{"slot": a["slot"], "sha256": a["sha256"], "page": a.get("page") or "", "licence_claim": a.get("licence_claim") or ""}
                    for a in document["assets"] if a.get("licence") == UNVERIFIED]}


def purge_credits(data_dir: str, *, now: float) -> int:
    """Remove the credits records whose later of approval and delivery (`approved_at`, `delivered_at`; the file's own time for a record that has neither) was CREDITS_DAYS ago or
    more (the upkeep part `media` runs it, limit L77). Returns how many went."""
    folder, count = credits_folder(data_dir), 0
    try:
        fd = os.open(folder, os.O_RDONLY | DIRECTORY | NOFOLLOW)
    except OSError:
        return 0
    try:
        for name in sorted(os.listdir(fd)):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except OSError:
                continue
            if not CREDITS_NAME.fullmatch(name):
                continue
            doc = read_credits(data_dir, int(name[:-5])) or {}
            stamps = [media._epoch(doc.get(k)) for k in ("approved_at", "delivered_at")]
            base = max([t for t in stamps if t is not None] or [info.st_mtime])
            if now - base >= CREDITS_DAYS * DAY and media._remove_tree(fd, name):
                count += 1
    finally:
        os.close(fd)
    return count


# --- the sources ------------------------------------------------------------------------------------------------------------------------------


def source_path(root: str, name: str) -> str:
    """The data file of a source: `providers/stock/sources/<name>.json` of the workbench checkout `root`."""
    if not SOURCE_NAME.fullmatch(name or ""):
        raise StockError("that is not the name of a source", "usage")
    return os.path.join(root, *SOURCES, name + ".json")


def source_data(root: str, name: str):
    """A source's data file as a dict (read as data, never run), or None when it cannot be read."""
    try:
        fd = os.open(source_path(root, name), os.O_RDONLY | NOFOLLOW)
        with os.fdopen(fd, "rb") as f:
            data = json.loads(f.read(65537).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError, StockError):
        return None
    return data if isinstance(data, dict) else None


def shipped(root: str) -> list:
    """The sources the checkout ships: the implementations of the class `stock:media`, by providers/resolve.py."""
    return sorted(project_config.resolver(root).implementations(CLASS, root=root))


def default_sources(root: str) -> list:
    """The sources a project that names none uses: those whose data file says they need no key (`secret_in` is `none`). A source that needs a key is on only when the person
    lists it."""
    keyless = [n for n in shipped(root) if (source_data(root, n) or {}).get("secret_in") == "none"]
    return sorted(keyless, key=lambda n: (tier_of(root, n) != "unverified", n))      # the open-web tier first, then by name


def sources_of(cfg: dict) -> list:
    """The sources a project uses: `media.stock` when the configuration names it (`[]` is off), else the default. Only a project that has a `media` object has any: the
    default is offered where the person already set up videos."""
    media_cfg = cfg.get("media")
    if not isinstance(media_cfg, dict):
        return []
    listed = media_cfg.get("stock")
    return list(listed) if isinstance(listed, list) else default_sources(cfg["workbench"])


def tier_of(root: str, name: str):
    """The licence tier a source's data file names (`library`, `per-item` or `unverified`), or None."""
    found = (source_data(root, name) or {}).get("licence_tier")
    return found if found in TIERS else None


def licensed(root: str, names) -> list:
    """The sources of `names` that are licensed ones: their tier is not `unverified` (the open web is a source of another path)."""
    return [n for n in names if tier_of(root, n) in ("library", "per-item")]


def accepted_licences(root: str, name: str) -> list:
    """The licence ids a licensed source's items can carry: its one licence, or the accepted ids its table maps to."""
    data = source_data(root, name) or {}
    if data.get("licence_tier") == "library":
        found = [data.get("licence")]
    else:
        table = data.get("licences")
        found = sorted(set(table.values())) if isinstance(table, dict) else []
    return [x for x in found if x in LICENCES_ACCEPTED]


def merge(per_source: list, limit: int = PER_SLOT) -> list:
    """Round robin over the lists of candidates of the sources, in the order of the lists (the order of `media.stock`), at most `limit`: the first of each source, then the
    second of each, and so on. A candidate already taken (the same source and item) is skipped."""
    out, seen, depth = [], set(), 0
    while len(out) < limit and any(depth < len(rows) for rows in per_source):
        for rows in per_source:
            if depth < len(rows) and len(out) < limit:
                key = pick_of(rows[depth])
                if key not in seen:
                    seen.add(key)
                    out.append(rows[depth])
        depth += 1
    return out


# --- the open web (package V9b-3b) ------------------------------------------------------------------------------------------------------------------


WEB_SCHEMA = 1
WEB_MAX_TOTAL, WEB_MAX_PER_SLOT, WEB_MAX_URL = 18, 3, 2048      # = skills/mkt-video-media-search/scripts/check_candidates.py (MAX_TOTAL, MAX_PER_SLOT, MAX_URL); web.py PER_VIDEO["previews"] is 18
WEB_BOUNDS = {"title": 120, "licence_claim": 200, "site_terms": 200, "note": 200}
WEB_REQUIRED = ("slot", "kind", "media_url", "page_url", "title", "licence_claim", "screen_work")
WEB_OPTIONAL = ("thumb_url", "resolution", "site_terms")
WEB_OPEN_CODES = ("no_result", "no_search_tool", "scene_only")
WEB_OPEN_WITH_SLOT = ("no_result", "scene_only")
WEB_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
WEB_RESOLUTION = re.compile(r"[1-9][0-9]{1,4}x[1-9][0-9]{1,4}")


def web_source(cfg: dict):
    """The name of the source of the open-web tier a project uses (its data file says `unverified`), or None. No name is written here: the tier is read from the data file."""
    for name in sources_of(cfg):
        if tier_of(cfg["workbench"], name) == "unverified":
            return name
    return None


def websearch_limits(cfg: dict) -> dict:
    """The bounds of a web search of this project: `media.websearch` as the configuration holds it (each key checked by project_config), else the defaults."""
    found = (cfg.get("media") or {}).get("websearch")
    return dict(project_config.WEBSEARCH_DEFAULTS, **found) if isinstance(found, dict) else dict(project_config.WEBSEARCH_DEFAULTS)


def _url_problem(value) -> bool:
    """True when a link breaks the first rules of a reach to the web: https, no more than WEB_MAX_URL characters, no space or control character, no user info, port 443 only, a plain
    host name (no address, no trailing dot). The same rules as the skill's checker; the provider checks them again before any byte is fetched."""
    if not isinstance(value, str) or not value.startswith("https://") or len(value) > WEB_MAX_URL or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        return True
    authority = re.split(r"[/?#]", value[len("https://"):], maxsplit=1)[0]
    if not authority or "@" in authority or authority.startswith("["):
        return True
    host = authority
    if ":" in authority:
        host, _, port = authority.partition(":")
        if port != "443":
            return True
    if host.endswith(".") or len(host) > 253:
        return True
    labels = host.lower().split(".")
    return len(labels) < 2 or all(x.isdigit() for x in labels) or not all(WEB_LABEL.fullmatch(x) for x in labels) or labels[-1].isdigit()


def read_web_candidates(data, sent: dict) -> dict:
    """The rules of skills/mkt-video-media-search/scripts/check_candidates.py again, in code, on a candidates document that was parsed from a run's file, plus: every slot and kind is
    exactly one that was sent (`sent` is `{slot: kind}`), and no field is unknown. Returns `{"candidates": [dict...], "open": [dict...]}` with the fields as the run gave them (nothing
    cleaned: the caller turns text into a one-line form). `StockError(..., "candidates_invalid")` for the first rule broken, with nothing of the text in the message."""
    def bad(where: str):
        raise StockError("the candidates file breaks a rule (%s)" % where, "candidates_invalid")

    if not isinstance(data, dict) or set(data) - {"schema_version", "candidates", "open"}:
        bad("root")
    if data.get("schema_version") != WEB_SCHEMA or isinstance(data.get("schema_version"), bool):
        bad("schema_version")
    rows, opens = data.get("candidates"), data.get("open")
    if not isinstance(rows, list) or not isinstance(opens, list) or len(rows) > WEB_MAX_TOTAL:
        bad("lists")
    per_slot, seen = {}, set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - set(WEB_REQUIRED + WEB_OPTIONAL) or any(k not in row for k in WEB_REQUIRED):
            bad("candidate")
        slot = row["slot"]
        if not isinstance(slot, str) or slot not in sent or row["kind"] != sent[slot]:
            bad("slot")
        per_slot[slot] = per_slot.get(slot, 0) + 1
        if per_slot[slot] > WEB_MAX_PER_SLOT:
            bad("too_many_for_slot")
        for key in ("media_url", "page_url", "thumb_url"):
            if key in row and _url_problem(row[key]):
                bad(key)
        if row["media_url"] in seen:
            bad("duplicate")
        seen.add(row["media_url"])
        for key in ("title", "licence_claim", "site_terms"):
            if key in row and (not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > WEB_BOUNDS[key]):
                bad(key)
        if not isinstance(row["screen_work"], bool):
            bad("screen_work")
        if "resolution" in row and not (isinstance(row["resolution"], str) and WEB_RESOLUTION.fullmatch(row["resolution"])):
            bad("resolution")
    for item in opens:
        if not isinstance(item, dict) or set(item) - {"code", "slot", "note"} or item.get("code") not in WEB_OPEN_CODES:
            bad("open")
        if "slot" in item and (not isinstance(item["slot"], str) or item["slot"] not in sent):
            bad("open_slot")
        if item["code"] in WEB_OPEN_WITH_SLOT and "slot" not in item:
            bad("open_slot")
        if "note" in item and (not isinstance(item["note"], str) or not item["note"].strip() or len(item["note"]) > WEB_BOUNDS["note"]):
            bad("note")
    return {"candidates": rows, "open": opens}


# --- the slots of a video ---------------------------------------------------------------------------------------------------------------------


def stock_slots(review: dict, proposal_beats: dict) -> list:
    """The slots `video-media-find` searches: `[{"slot", "show", "search", "want"}]`. A script slot (`proposal_beats["slots"]`) with the choice `stock` and a search; an
    added layout that has a search and is not set to `none` (the picture is its whole point). A slot with no search is left out: it reads as `none` until the person gives
    words. In the order of the script, then of the added layouts."""
    found, choices, out = review["slot_searches"], review["empty_slots"], []
    for s in proposal_beats.get("slots") or []:
        if choices.get(s["slot"]) == "stock" and s["slot"] in found:
            out.append({"slot": s["slot"], "show": _show(s.get("description")), "search": found[s["slot"]]["search"], "want": found[s["slot"]]["want"]})
    for a in review["animations"]:
        if "asset_param" in a and a["id"] in found and choices.get(a["id"]) != "none":
            out.append({"slot": a["id"], "show": _show(a.get("show") or a["block"]), "search": found[a["id"]]["search"], "want": found[a["id"]]["want"]})
    return out


def _show(text) -> str:
    """Words for a slot's `show`: the text trimmed and cut to the bound, or a fixed word when there is none."""
    clean = " ".join(str(text or "").split())[:captions.SHOW[1]]
    return clean if len(clean) >= captions.SHOW[0] else "a picture"


def now_stamp(now=None) -> str:
    return time.strftime(media.STAMP_FORMAT, time.gmtime(time.time() if now is None else now))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
