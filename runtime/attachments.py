#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Files a listed sender sends through a messaging app (package ATT-1): the limits, the sentences, the checks that need no store, and the
folders where such a file waits. The operations are runtime/ops_attachments.py; the bridge's part is runtime/messaging_attach.py.

A file a listed sender sends is held, checked and shown on a card; it becomes a source only when a person adds it (or a profile with the
grant `add-sources-direct` sent it). A channel without the group `add-sources` takes nothing: nothing is downloaded.

The hold (limit L48). A file waits in `<data_dir>/attachments/` and nowhere else: `incoming/<token>/` while it is fetched (the provider writes
`content` there), then `held/<id>/original` (mode 0400) once the intake has bounded it, read its type from its bytes and hashed it. That folder
is inside the project's data folder, which the sources folder is disjoint from (limit L22), and outside the project: a held file never enters a
run copy, the sources folder or a prompt until `attachment-add` makes it a version. It is deleted when it is added, refused, discarded or
expired (HELD_DAYS); the project's versioned files and the sources folder never hold the sender's id (the store's `attachments` row does).
Every folder is made and opened through descriptors with O_NOFOLLOW, the pattern of sources._private_dir.

The limits are constants, fixed in code (a key of runtime.json may narrow them later, never widen):

  FILE_CAP      the most one file may be: the intake's ORIGINAL_CAP, or the provider's own cap when it is lower (`max_attachment_bytes`)
  DAY_FILES     20 files and DAY_BYTES 100 MiB for the project in a UTC day, every platform together; a file counts when its bytes were fetched, a
                refused one included (the bandwidth and the disk were spent)
  HELD_MAX      10 files held for the project at once
  PER_MESSAGE   5 files taken from one message
  HELD_DAYS     7 days without an answer, then the file is deleted and the row ends `expired`

What the platform declared is checked before a byte is fetched (declared_problem): a photo, a voice note, a video, an audio file or a sticker is
refused (no OCR and no transcription yet), and so is a declared size over the cap. What the bytes are is read from the bytes (the sources
sniffers); a declared type that names one of the converter's types and says another one than the bytes do is refused (mismatch).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import re
import secrets
import stat
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intake  # noqa: E402
import phrases  # noqa: E402
import sources  # noqa: E402

CHANNEL = "messaging"
FILE_CAP = sources.ORIGINAL_CAP
DAY_FILES = 20
DAY_BYTES = 100 * 1024 * 1024
HELD_MAX = 10
PER_MESSAGE = 5
HELD_DAYS = 7
NAME_MAX = 100
INCOMING_KEPT_SECONDS = 24 * 3600      # an incoming folder older than this is a crash's leftover
FOLDER, INCOMING, HELD = "attachments", "incoming", "held"
CONTENT = "content"                    # the one file a provider writes in the incoming folder
ORIGINAL = "original"                  # the held file inside held/<id>/
TOKEN = re.compile(r"[0-9a-f]{16}")
LOCK_NAME = "attachments.lock"         # <data_dir>/locks/: one add or discard at a time
MEDIA_KINDS = ("photo", "voice", "video", "audio", "sticker")    # what a provider names a medium it has no type for
CODES = ("off", "media", "too_large", "day", "held_max", "gone", "mismatch", "type", "size", "credential", "convert", "macro", "target", "changed", "lost",
         "fetch", "busy", "duplicate")
FAILED_FETCH = ("gone", "fetch", "size")      # the codes of a fetch that did not end held, as the bridge reports it (attachment_hold, failed=)

# The sentences a person reads. English constants kept under their old names (an operation raises them as the text of an OpsError and the terminal shows them
# as they are); the phrase table (runtime/phrases.py) is their source, and the messaging bridge says them on a phone in the project's language (package LR-1).
# `{name}` is the cleaned name, never the file's content.
OFF = phrases.en("ATT_OFF")
NO_FILES = phrases.en("ATT_NO_FILES")
MEDIA = phrases.en("ATT_MEDIA")
TOO_LARGE = phrases.en("ATT_TOO_LARGE")
DAY = phrases.en("ATT_DAY")
HELD_FULL = phrases.en("ATT_HELD_FULL")
GONE = phrases.en("ATT_GONE")
MISMATCH = phrases.en("ATT_MISMATCH")
REFUSED = phrases.en("ATT_REFUSED")
DUPLICATE = phrases.en("ATT_DUPLICATE")
CAPTION_IGNORED = phrases.en("ATT_CAPTION_IGNORED")
OVER_MESSAGE = phrases.en("ATT_OVER_MESSAGE")
BUSY = phrases.en("ATT_BUSY")
FETCH_FAILED = phrases.en("ATT_FETCH_FAILED")
ADDED = phrases.en("ATT_ADDED")
ADDED_SAME = phrases.en("ATT_ADDED_SAME")
TARGET_TYPE = phrases.en("ATT_TARGET_TYPE")
TARGET_CHANGED = phrases.en("ATT_TARGET_CHANGED")
DISCARDED = phrases.en("ATT_DISCARDED")
NOT_HELD = phrases.en("ATT_NOT_HELD")
NO_SUCH = phrases.en("ATT_NO_SUCH")
EXPIRED = phrases.en("ATT_EXPIRED")
LOST = phrases.en("ATT_LOST")
KEPT_FAILED = phrases.en("ATT_KEPT_FAILED")
MACHINE = phrases.en("ATT_MACHINE")
WORD_SIZES = (("MiB", 1024 * 1024), ("KiB", 1024))


def utcnow() -> datetime.datetime:
    """The clock (a test replaces it)."""
    return datetime.datetime.now(datetime.timezone.utc)


def iso(moment: datetime.datetime) -> str:
    """Fixed-width UTC ISO-8601, the form the store compares as text."""
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def day_start(moment=None) -> str:
    """The start of the UTC day of `moment` (now), as the store's text: what the day's limit counts from."""
    moment = moment or utcnow()
    return iso(moment.astimezone(datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))


def expiry(created_at: str):
    """When a file held since `created_at` expires, as the store's text, or None for a time that is not one."""
    try:
        made = datetime.datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None
    return iso(made + datetime.timedelta(days=HELD_DAYS))


def expired_before() -> str:
    """The time before which a held file has waited HELD_DAYS."""
    return iso(utcnow() - datetime.timedelta(days=HELD_DAYS))


def size_text(count: int) -> str:
    """A size for a person: `812 bytes`, `3.5 KiB`, `12.0 MiB`."""
    for word, unit in WORD_SIZES:
        if count >= unit:
            return f"{count / unit:.1f} {word}"
    return f"{count} bytes"


def ref_digest(platform: str, ref: str, sender: str = "") -> str:
    """The hash under which a platform's reference is remembered, for the sender who sent it (the reference itself is what the platform fetches the file by, and
    is never stored). It names the sender, so that a file one sender holds never blocks the same reference sent by another, and the second is never told the
    first's number."""
    return hashlib.sha256(f"{platform}\n{sender}\n{ref}".encode("utf-8")).hexdigest()


def card_sha256(file_sha256: str, target: str, label: str) -> str:
    """What a card is bound to: the file's own hash, the source it would become a version of, and whether that is a new source or a refresh."""
    return hashlib.sha256(f"attachment\n{file_sha256}\n{target}\n{label}".encode("utf-8")).hexdigest()


def clean_name(raw, fallback: str = "file") -> str:
    """A file's name for the store and for a reply: the last part of any path, control, format and separator characters out (a bidirectional
    override cannot disguise an extension), white space collapsed, at most NAME_MAX characters. A name that leaves nothing is `fallback`. It is
    shown as text (the providers escape what they render) and is never the name of a file on this machine: the stored original's name comes from
    the sniffed kind."""
    text = raw if isinstance(raw, str) else ""
    text = text.replace("\\", "/").rsplit("/", 1)[-1]
    text = "".join(c if unicodedata.category(c) not in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp") else " " for c in text)
    text = " ".join(text.split())
    if len(text) > NAME_MAX:
        text = text[:NAME_MAX - 1].rstrip() + "…"
    if text.startswith(sources.DRIVE_PREFIX):      # a file source's origin never starts so (that marks a Drive source)
        text = "file-" + text
    return text or fallback


def stem(name: str) -> str:
    """A name without its extension, the text a source id is made from."""
    base = name.rsplit(".", 1)[0] if "." in name.strip(".") else name
    return base or name


def caption_target(text, count: int):
    """(target, ignored) for the text sent with the files of a message. The only caption read is exactly `@<source id>`, on a message of ONE
    file: it names the source the file becomes a version of. Any other text is not read (ignored is true), and a message of several files
    names no target. The caption never reaches a model or a command."""
    said = text.strip() if isinstance(text, str) else ""
    if not said:
        return None, False
    found = sources.MENTION.fullmatch(said) if said.startswith("@") else None
    if found and count == 1:
        return found.group(1), False
    return None, True


# --- what the platform declared, before a byte is fetched ------------------------------------------------------------------------


GENERIC_TYPES = ("", "application/octet-stream", "binary/octet-stream", "application/x-binary", "application/zip", "application/x-zip-compressed")
TEXT_LIKE = ("text", "csv", "html")        # what a client calls text/plain, text/csv or text/html is any of these: the bytes decide which
TEXT_TYPES = {kind: TEXT_LIKE for kind in ("text/plain", "text/markdown", "text/csv", "application/csv", "text/html", "application/xhtml+xml")}
OFFICE_TYPES = {"application/pdf": ("pdf",),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("docx", "ooxml"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("xlsx", "ooxml"),
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": ("pptx", "ooxml")}
SUBTYPE_WORDS = {kind: phrases.en("ATT_SUBTYPE_" + kind.upper()) for kind in ("pdf", "docx", "xlsx", "pptx", "ooxml", "html", "csv", "text")}


def media_type(declared) -> str:
    """The declared type, lower case and without its parameters (`text/plain; charset=utf-8` is `text/plain`); "" when none was declared."""
    return declared.split(";", 1)[0].strip().lower() if isinstance(declared, str) else ""


def is_media(declared) -> bool:
    """Whether the platform named the file a photo, a voice note, a video, an audio file or a sticker (a word of MEDIA_KINDS, or an image, audio
    or video media type)."""
    kind = media_type(declared)
    return kind in MEDIA_KINDS or kind.split("/", 1)[0] in ("image", "audio", "video")


def declared_problem(attachment: dict, cap: int):
    """The reason to refuse an attachment on what the platform declared, or None: {"code": "media"} for a medium, {"code": "too_large", "size":
    <declared>} for a declared size over `cap`. Nothing is fetched to decide it."""
    if is_media(attachment.get("type")):
        return {"code": "media"}
    declared = attachment.get("size")
    if isinstance(declared, int) and not isinstance(declared, bool) and declared > cap:
        return {"code": "too_large", "size": declared}
    return None


def mismatch(declared, sniffed: str) -> bool:
    """Whether the type the platform declared contradicts the bytes. A declared type that is absent or generic
    (octet-stream, a bare archive type) goes by the bytes; a declared type of the converter's list must be what the bytes are (a text type
    takes text, csv and html; an Office type takes its own kind or an Office package the converter has not yet told apart)."""
    kind = media_type(declared)
    if kind in GENERIC_TYPES:
        return False
    allowed = TEXT_TYPES.get(kind) or OFFICE_TYPES.get(kind)
    return allowed is not None and sniffed not in allowed


def precheck(attachments: list, *, cap: int, today: dict, held: list, platform: str, sender: str = ""):
    """The checks made on a message's attachments before anything is fetched, from what the store reports: `today` is {"files", "bytes"}, `held`
    the held rows (each with `ref_sha256`, which names its sender: a duplicate is the same platform, sender and reference). Returns a list of decisions, one for each attachment taken or refused, in order, each
    {"index", "attachment", "refuse": {"code", ...} or None, "duplicate": the held row or None}; at most PER_MESSAGE are looked at (the
    rest are returned as {"index", "over": True}). The budget of the day and the held ceiling count the files of this message that were
    taken before it, so a message of five cannot pass a limit each of its files would pass alone."""
    out = []
    files, used, waiting = today.get("files", 0), today.get("bytes", 0), len(held)
    known = {row["ref_sha256"]: row for row in held}
    seen = set()
    for index, attachment in enumerate(attachments):
        if index >= PER_MESSAGE:
            out.append({"index": index, "attachment": attachment, "over": True, "refuse": None, "duplicate": None})
            continue
        entry = {"index": index, "attachment": attachment, "over": False, "refuse": declared_problem(attachment, cap), "duplicate": None}
        digest = ref_digest(platform, attachment["ref"], sender)
        if digest in seen:
            entry["refuse"], entry["duplicate"] = None, {"id": None}        # the same reference twice in one message is one file: fetched once
            out.append(entry)
            continue
        seen.add(digest)
        if entry["refuse"] is None and digest in known:
            entry["duplicate"] = known[digest]
        elif entry["refuse"] is None and (files >= DAY_FILES or used >= DAY_BYTES):
            entry["refuse"] = {"code": "day", "files": files, "bytes": used}
        elif entry["refuse"] is None and waiting >= HELD_MAX:
            entry["refuse"] = {"code": "held_max", "n": waiting}
        if entry["refuse"] is None and entry["duplicate"] is None:
            files, used, waiting = files + 1, used + (attachment.get("size") or 0), waiting + 1
        out.append(entry)
    return out


def fetch_budget(cap: int, today: dict) -> int:
    """The most the next fetch may bring: the cap, or what is left of the day's bytes, whichever is less (at least 1, so a fetch of a
    file the platform declared small still runs; the day's count is checked first)."""
    return max(1, min(cap, DAY_BYTES - today.get("bytes", 0)))


def refusal_text(refuse: dict, attachment: dict, platform: str, cap: int, cfg=None) -> str:
    """The sentence for a refusal of precheck, in the language of `cfg` (runtime/phrases.py; English when none)."""
    name = clean_name(attachment.get("name"))
    code = refuse["code"]
    if code == "media":
        return phrases.text("ATT_MEDIA", cfg)
    if code == "too_large":
        return phrases.text("ATT_TOO_LARGE", cfg, name=name, size=size_text(refuse["size"]), cap=size_text(cap))
    if code == "day":
        return phrases.text("ATT_DAY", cfg, n=refuse["files"], size=size_text(refuse["bytes"]))
    if code == "held_max":
        return phrases.text("ATT_HELD_FULL", cfg, n=refuse["n"])
    return phrases.text("ATT_REFUSED", cfg, name=name, reason=code)


# --- the folders -----------------------------------------------------------------------------------------------------------------


class FolderError(Exception):
    """A folder of the hold cannot be made or opened as a plain private folder of this user."""


def _open_data(data_dir: str) -> int:
    try:
        return os.open(data_dir, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as e:
        raise FolderError(f"the data folder {data_dir} cannot be opened: {e.strerror}") from None


def _private(parent_fd: int, name: str, what: str) -> int:
    try:
        return sources._private_dir(parent_fd, name, what)
    except sources.SourcesError as e:
        raise FolderError(str(e)) from None


def make_incoming(data_dir: str) -> tuple:
    """A new incoming folder for one fetch, <data_dir>/attachments/incoming/<token>/, each level made through its parent's descriptor with
    O_NOFOLLOW, this user's, mode 0700. Returns (token, path). FolderError when a level is a link, a file or another user's."""
    try:
        os.makedirs(data_dir, mode=0o700, exist_ok=True)
    except OSError as e:
        raise FolderError(f"the data folder {data_dir} cannot be made: {e.strerror}") from None
    top = _open_data(data_dir)
    opened = [top]
    try:
        base = _private(top, FOLDER, "the attachments folder")
        opened.append(base)
        incoming = _private(base, INCOMING, "the incoming folder")
        opened.append(incoming)
        token = secrets.token_hex(8)
        opened.append(_private(incoming, token, "the folder of this fetch"))
    finally:
        for fd in opened:
            os.close(fd)
    return token, os.path.join(data_dir, FOLDER, INCOMING, token)


def incoming_path(data_dir: str, token) -> str:
    """The path of an incoming folder the bridge made, after checking the token's shape and that the folder is a real folder (no link). FolderError otherwise."""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise FolderError("the incoming folder's name is not one this runtime made")
    path = os.path.join(data_dir, FOLDER, INCOMING, token)
    try:
        info = os.lstat(path)
    except OSError:
        raise FolderError("the incoming folder is gone") from None
    if not stat.S_ISDIR(info.st_mode):
        raise FolderError("the incoming folder is not a plain folder")
    return path


def open_content(path: str):
    """(stream, size) of the file a provider wrote in an incoming folder: opened with O_NOFOLLOW, a regular file, its size from fstat.
    FolderError when there is none or it is not one."""
    try:
        fd = os.open(os.path.join(path, CONTENT), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise FolderError("the provider left no file") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise FolderError("the provider's file is not a regular file")
        if info.st_nlink != 1:
            raise FolderError("the provider's file has another name")        # a hard link may be a file of someone else's, written through
        return os.fdopen(fd, "rb"), info.st_size
    except BaseException:
        os.close(fd)
        raise


def remove_incoming(data_dir: str, token) -> None:
    """Remove an incoming folder and what is in it (ours: a plain removal through descriptors, never following a link). Quiet when it is gone."""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        return
    try:
        top = _open_data(data_dir)
    except FolderError:
        return
    try:
        fd = None
        try:
            base = os.open(FOLDER, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=top)
            try:
                fd = os.open(INCOMING, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base)
            finally:
                os.close(base)
            sources._remove_in(fd, token)
        except OSError:
            pass
        finally:
            if fd is not None:
                os.close(fd)
    finally:
        os.close(top)


def keep_held(data_dir: str, attachment_id: int, from_dir: str, part_name: str) -> str:
    """Move the intake's temporary file `part_name` of the incoming folder `from_dir` to <data_dir>/attachments/held/<id>/original (mode 0400):
    the folder is made through descriptors, the file is renamed from folder to folder (the same file system, never a copy through a path).
    Returns the file's path. FolderError on any failure; nothing is left in held/ then."""
    top = _open_data(data_dir)
    opened = [top]
    made = None
    try:
        base = _private(top, FOLDER, "the attachments folder")
        opened.append(base)
        held = _private(base, HELD, "the held folder")
        opened.append(held)
        mine = _private(held, str(int(attachment_id)), "the folder of this file")
        opened.append(mine)
        made = (held, str(int(attachment_id)))
        src = os.open(from_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        opened.append(src)
        try:
            os.rename(part_name, ORIGINAL, src_dir_fd=src, dst_dir_fd=mine)
            kept = os.open(ORIGINAL, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=mine)
            try:
                os.fchmod(kept, 0o400)
            finally:
                os.close(kept)
        except OSError as e:
            raise FolderError(f"the file cannot be kept: {e.strerror}") from None
        made = None
    except BaseException:
        if made is not None:
            sources._remove_in(*made)
        raise
    finally:
        for fd in opened:
            os.close(fd)
    return os.path.join(data_dir, FOLDER, HELD, str(int(attachment_id)), ORIGINAL)


def read_held(data_dir: str, attachment_id: int):
    """The held file's bytes, read through descriptors with O_NOFOLLOW and compared with nothing here (the caller hashes them), or None when the
    file or a folder above it is gone."""
    try:
        top = _open_data(data_dir)
    except FolderError:
        return None
    opened = [top]
    try:
        for name in (FOLDER, HELD, str(int(attachment_id))):
            opened.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=opened[-1]))
        fd = os.open(ORIGINAL, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=opened[-1])
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None
            with os.fdopen(fd, "rb") as f:
                fd = None
                return f.read(FILE_CAP + 1)
        finally:
            if fd is not None:
                os.close(fd)
    except OSError:
        return None
    finally:
        for fd in opened:
            os.close(fd)


def delete_held(data_dir: str, attachment_id: int) -> None:
    """Delete the folder of a held file (the file with it). Quiet when it is gone."""
    try:
        top = _open_data(data_dir)
    except FolderError:
        return
    opened = [top]
    try:
        for name in (FOLDER, HELD):
            opened.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=opened[-1]))
        sources._remove_in(opened[-1], str(int(attachment_id)))
    except OSError:
        pass
    finally:
        for fd in opened:
            os.close(fd)


FetchBusy = intake.IntakeError      # what fetch_lock raises when another upload or fetch holds the lock


def fetch_lock(data_dir: str):
    """The lock one fetch holds, taken without waiting: the one the page's uploads take (sources.upload_lock_path), so that one file at a time is brought to
    a project and the free-space count is not made twice. Release it with `.release()`. FetchBusy when another holder has it."""
    return intake.one_at_a_time(sources.upload_lock_path({"data_dir": data_dir}))


def lock_path(cfg: dict) -> str:
    """The lock that makes one add or discard at a time (a tap and a typed command at once)."""
    folder = os.path.join(cfg["data_dir"], sources.LOCKS)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    return os.path.join(folder, LOCK_NAME)


def public(row: dict) -> dict:
    """An attachment as a shell reads it: what the file is and where it stands, never the sender's id (the profile and the platform are what a
    shell and a catalog may name)."""
    out = {key: row.get(key) for key in ("id", "platform", "profile", "name", "declared_type", "kind", "sha256", "bytes", "target", "label",
                                         "direct", "status", "code", "source_id", "version", "created_at", "decided_at", "ref_sha256")}
    out["expires_at"] = expiry(row.get("created_at")) if row.get("status") == "held" else None
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
