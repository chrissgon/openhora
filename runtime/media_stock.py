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
  quarantine/       the files of the open web (a later package); a file leaves it only at the set approval
  asset-<sha12>.png the pictures the renderer made from the picks, PNG, the only files a render may use
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
KIND_BYTES = {"image": 16 * MIB, "clip": 120 * MIB}
SET, APPROVED, SHEET, SHEET_PREVIEW = "set.json", "approved.json", "sheet.png", "sheet-preview.png"
QUARANTINE = media.STOCK_QUARANTINE
SET_VERSION = 1
DOC_LIMIT = 2 * MIB
ASSET_FILE = re.compile(r"asset-([0-9a-f]{12})\.png")
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
    """Write `set.json` or `approved.json` whole (a temporary file, then a rename, mode 0600). Returns the sha256 of the bytes."""
    if name not in (SET, APPROVED):
        raise StockError("that is not a document of the stock folder", "usage")
    data = (json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > DOC_LIMIT:
        raise StockError("that document is too large", "usage")
    with _open(data_dir, rid, create=True) as fd:
        _write_in(fd, name, data, 0o600)
    return hashlib.sha256(data).hexdigest()


def read_doc(data_dir: str, rid: str, name: str):
    """`set.json` or `approved.json` as a dict, or None when it is not there; `unreadable` for a file that is not JSON or not an object."""
    if name not in (SET, APPROVED):
        raise StockError("that is not a document of the stock folder", "usage")
    try:
        data = media.read_work(data_dir, rid, "stock/" + name, DOC_LIMIT)
    except media.MediaError as e:
        if e.code == "not_found":
            return None
        raise _stock_error(e) from None
    try:
        doc = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise StockError("that document cannot be read", "unreadable") from None
    if not isinstance(doc, dict):
        raise StockError("that document cannot be read", "unreadable")
    return doc


def read_served(data_dir: str, rid: str, name: str, limit: int = 32 * MIB) -> bytes:
    """The bytes of a file the page may be given: only `sheet-preview.png`, `sheet.png` and `asset-<sha12>.png` (the files the container made), never a preview, a full
    file or a file of the quarantine, whatever their names. A file that is not a PNG by its header is refused."""
    if not isinstance(name, str) or not (name in SERVED or ASSET_FILE.fullmatch(name)):
        raise StockError("that file is not one the page may be given", "usage")
    try:
        data = media.read_work(data_dir, rid, "stock/" + name, limit)
    except media.MediaError as e:
        raise _stock_error(e) from None
    if len(data) > limit or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise StockError("that file is not a picture", "unreadable")
    return data


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
    return {"version": SET_VERSION, "task": document["task"], "recording": recording, "approved_at": now_stamp(now), "delivered_at": None, "assets": assets, "credits": list(document["credits"]),
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
