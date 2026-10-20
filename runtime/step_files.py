#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `file-write`: put a file in the person's own Drive or OneDrive, as an external effect the person approves (package W4a). The kind prepares; it
never writes. Two steps, as in an e-mail:

  prepare   checks the arguments, takes the account's address and (for a new file) the folder from the project's accepted `accounts` (limit L55: only what the
            file lists is a target), reads what the service holds through the read-only seam (a folder and whether the name is taken; or the file to replace, its
            revision and the version of the source the person looked at), takes the content (the person's text; a file of the project under docs/, no link on the
            way; or a file a sender sent, held by the messaging bridge), and writes the effect document (runtime/files_document.py) through the effect-files
            service to <data_dir>/step-effects/<task id>/<cycle>/effect.json, 0600 in a 0700 folder.
  approve   the gate (runtime/steps.py, Gate): it has no executor. It opens an `effect` decision whose hash is the hash of the effect document and whose card is
            its lines (the account, the file, the folder or the revision it replaces, the text whole or the file's size and hash, the hash); the task waits. The
            person approves the hash in the terminal or on the page (a messaging app, when the project's policy grants it the word `files`, from a card that carries
            the whole text; a save only by the sender who sent the file), and then runtime/ops_step_effects.py calls the effect module (runtime/effect_files.py),
            which reads the content and the file again and writes once. A file that moved meanwhile answers the decision, writes nothing and sends the task back to
            `prepare`.

Arguments (checked when the task is planned, so the plan's hash covers exactly what will be asked about):

  {"operation": "create", "account": "google"|"microsoft", "name": "<name>.md|.txt|.docx" (or "<name>.gdoc", a Google Doc made from Markdown text),
   "content": "<text>" | "from": "docs/<path>", ["folder": "<a name the project lists under accounts.<account>.folders>"]}   a NEW file: it never replaces one
  {"operation": "replace", "account": ..., "file": "<a source id of a file of that account>", "content": "<text>" | "from": "docs/<path>"}   a new revision
  {"operation": "save", "account": ..., "attachment": <a held file's number>, ["name": "<name>"], ["folder": "<name>"]}   the file a sender sent

The text is at most 64 KiB; a file of the project at most 25 MiB. The sender of a saved file is never an argument: it is in the store alone (limit L48).

Limit L30, in the structure of this file: it imports no module that calls a provider. What it needs it asks of `ctx.services` (runtime/ops_step_seams.py), where
`files_read` has one verb, a read, and `effect_files` writes and reads the effect document and does not execute it. The only code that writes is
runtime/effect_files.py `execute`, which this file cannot reach. The kind is not `unattended`: a file write starts when the person starts it and ends at the
person's approval. It writes no file of the project (its footprint is empty).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import files_document as fd  # noqa: E402
import phrases  # noqa: E402
import steps  # noqa: E402
import workcopy  # noqa: E402  (the credential formats: a text that holds one is refused before the service is asked anything)

KEYS = ("operation", "account", "folder", "name", "content", "from", "file", "attachment")
SERVICE_CODES = {"not_configured": "not_configured", "provider_failed": "provider_failed", "refused": "refused", "gone": "gone"}
GATE_STEP = "approve"
SOURCE_TYPE = {"google": "drive", "microsoft": "onedrive"}
SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")      # runtime/sources.py SOURCE_ID: a test compares
FOLDER_NAME = re.compile(r"[a-z0-9-]{1,32}")           # runtime/project_config.py ACCOUNT_NAME: a test compares
TEXT_EXTENSIONS = ("md", "txt", "csv")
HELD_KINDS = {"md": ("text",), "txt": ("text",), "csv": ("csv", "text"), "pdf": ("pdf",), "docx": ("docx", "ooxml"), "xlsx": ("xlsx", "ooxml"),
              "pptx": ("pptx", "ooxml")}      # what the bytes of a held file may be, by the extension of the name it is saved as (the sniffed subtype of the hold)
FREE_NAME_TRIES = 9      # `name (2)` to `name (10)`: the most names tried for a file that was sent when its own is taken
HEIC_BRANDS = ("heic", "heix", "heim", "heis", "hevc", "hevx", "mif1", "msf1")      # runtime/attachments.py HEIC_BRANDS: a test compares
HELD_KINDS.update({"png": ("png",), "jpg": ("jpeg",), "jpeg": ("jpeg",), "webp": ("webp",), "gif": ("gif",),
                   "heic": HEIC_BRANDS, "heif": HEIC_BRANDS})      # an image is saved only when its bytes are the image its name says (package ATT-3)
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _bad(field: str, hint: str = "") -> "steps.StepFailure":
    return steps.StepFailure("bad_args", field, "", hint[:200])


def check(args) -> dict:
    """The arguments of a file-write, checked and normalised (line ends of a text as LF)."""
    if not isinstance(args, dict) or set(args) - set(KEYS):
        raise steps.StepFailure("bad_args", "args")
    operation, account = args.get("operation"), args.get("account")
    if operation not in fd.OPERATIONS:
        raise _bad("operation", "the operation is create, replace or save")
    if account not in fd.IMPLEMENTATION:
        raise _bad("account", "the account is google or microsoft")
    allowed = {"create": {"operation", "account", "folder", "name", "content", "from"}, "replace": {"operation", "account", "file", "content", "from"},
               "save": {"operation", "account", "attachment", "name", "folder"}}[operation]
    extra = sorted(set(args) - allowed)
    if extra:
        raise _bad(extra[0], f"a {operation} does not take {extra[0]}")
    out = {"operation": operation, "account": account}
    if operation != "save":
        has_text, has_file = args.get("content") is not None, args.get("from") is not None
        if has_text == has_file:
            raise _bad("content", phrases.en("ACCT_FILE_ONE_CONTENT"))
        if has_text:
            if not isinstance(args["content"], str):
                raise _bad("content")
            text = fd.lines_as_lf(args["content"])
            problem = fd.text_problem(text)
            if problem:
                raise _bad("content", problem)
            leak = workcopy.scan(text.encode("utf-8"))
            if leak:
                raise _bad("content", f"the text {leak}: it is not written anywhere")
            out["content"] = text
        else:
            path = args["from"]
            if not isinstance(path, str) or not steps.REL_PATH.fullmatch(path) or not fd.DOCS_PATH.fullmatch(path) or ".." in path.split("/") \
                    or path.endswith(".comments.md"):
                raise _bad("from", "give a file under docs/")
            out["from"] = path
    if operation == "replace":
        if not isinstance(args.get("file"), str) or not SOURCE_ID.fullmatch(args["file"]):
            raise _bad("file", "give the id of a source that is a file of that account")
        out["file"] = args["file"]
        return out
    if args.get("folder") is not None:
        if not isinstance(args["folder"], str) or not FOLDER_NAME.fullmatch(args["folder"]):
            raise _bad("folder", "give a name the project lists under accounts.<account>.folders")
        out["folder"] = args["folder"]
    if operation == "create":
        name = args.get("name")
        problem = fd.name_problem(name, fd.CREATE_EXTENSIONS + (fd.GDOC_WORD,))
        if problem:
            raise _bad("name", problem)
        if fd.extension_of(name) == fd.GDOC_WORD and account != "google":
            raise _bad("name", "a Google Doc is made in a Google Drive")
        out["name"] = name
        return out
    attachment = args.get("attachment")
    if type(attachment) is not int or attachment < 1:
        raise _bad("attachment", "give the number of a file a sender sent")
    out["attachment"] = attachment
    if args.get("name") is not None:
        problem = fd.name_problem(args["name"], fd.SAVE_EXTENSIONS)
        if problem:
            raise _bad("name", problem)
        out["name"] = args["name"]
    return out


def _service(ctx: steps.Context, name: str):
    found = ctx.services.get(name)
    if found is None:
        raise steps.StepFailure("not_configured", name)
    return found


def _asked(call, *args, field: str = "", provider: str = "", next: str = ""):
    """A service call whose failure is a closed code of the step. The service's own words never enter a state: `next` is fixed text."""
    try:
        return call(*args)
    except steps.StepFailure:
        raise
    except Exception as e:      # the services raise errors that carry a `code`; anything else is a provider failure
        raise steps.StepFailure(SERVICE_CODES.get(getattr(e, "code", ""), "provider_failed"), field, provider, next) from None


def _target(accounts, account: str, name):
    """The id of a folder the project lists. The sentence of a refusal is the project's own words about its own file (project_config.account_target), with the name
    cleaned: it names the folders the file lists, so that the person can choose one."""
    try:
        return accounts.target(account, "folders", name)
    except Exception as e:
        raise steps.StepFailure("target_refused", "folder", "", str(getattr(e, "reason", ""))[:300]) from None


def _stamp(now: str) -> str:
    found = STAMP.match(now or "")
    if not found:
        raise steps.StepFailure("clock", "read_at")
    return found.group(0) + "Z"


def _read_project(ctx: steps.Context, rel: str, limit: int) -> bytes:
    try:
        return steps.read_file(ctx, rel, limit)
    except steps.StepFailure as e:
        code = {"missing": "file_missing", "too_large": "file_too_large"}.get(e.code, e.code)
        raise steps.StepFailure(code, "from", "", "write the file first, then start this task" if code == "file_missing" else "") from None


def _text_of(data: bytes, field: str) -> str:
    try:
        text = fd.lines_as_lf(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise _bad(field, "the file is not UTF-8 text") from None
    problem = fd.text_problem(text)
    if problem:
        raise _bad(field, problem)
    return text


def _content_for(ctx: steps.Context, wanted: str, word: str, *, gdoc: bool = False) -> dict:
    """The content of a create or a replace for a target of the media type `wanted` (`word` names it for the person). A text goes in the document whole; a file of
    the project goes in by its path and hash. A text cannot be written into a file that is not text, and a file of the project must be of the target's type."""
    args = ctx.args
    if args.get("content") is not None:
        if wanted not in fd.TEXT_TYPES:
            raise steps.StepFailure("type_mismatch", "content", "", phrases.en("ACCT_FILE_TYPE").format(given="text", wanted=word))
        return fd.content_of("text", args["content"].encode("utf-8"), wanted, text=args["content"], gdoc=gdoc)
    rel = args["from"]
    ext = fd.extension_of(rel)
    given = fd.MEDIA_TYPES.get(ext)
    if wanted in fd.TEXT_TYPES:
        if ext not in TEXT_EXTENSIONS:
            raise steps.StepFailure("type_mismatch", "from", "", phrases.en("ACCT_FILE_TYPE").format(given=ext or "file", wanted=word))
        data = _read_project(ctx, rel, fd.TEXT_MAX + 1)
        text = _text_of(data, "from")
        return fd.content_of("text", text.encode("utf-8"), wanted, text=text, path=rel, gdoc=gdoc)
    if given != wanted:
        raise steps.StepFailure("type_mismatch", "from", "", phrases.en("ACCT_FILE_TYPE").format(given=ext or "file", wanted=word))
    data = _read_project(ctx, rel, fd.FILE_MAX)
    if not data:
        raise _bad("from", "the file is empty")
    return fd.content_of("file", data, wanted, path=rel)


def _owned(account: str, meta: dict, name: str) -> None:
    """A replace is made only of a file the account owns (Drive: ownedByMe and may edit; OneDrive: in the account's own drive); the card names the account."""
    if meta.get("owned") is not True:
        raise steps.StepFailure("not_owned", "file", "", phrases.en("ACCT_FILE_NOT_OWNED").format(service=fd.SERVICE_NAME[account]))


def _target_media(account: str, meta: dict) -> tuple:
    """(the media type the new revision is written as, the word that names the target's type, the base of the document, its version token) for a file the
    writer described; StepFailure when the item is not a file this platform writes."""
    if account == "google":
        if meta.get("in_trash") or meta.get("folder"):
            raise steps.StepFailure("not_a_file", "file", "", phrases.en("ACCT_FILE_NOT_FILE").format(reason="it is in the trash, or is a folder"))
        mime = meta.get("mime_type")
        native = bool(meta.get("native"))
        if native and mime != fd.DOC_MIME:
            raise steps.StepFailure("kind_refused", "file", "", phrases.en("ACCT_FILE_KIND").format(kind=fd.clean_display(mime.rsplit(".", 1)[-1], 40)))
        if native:
            media, word = "text/markdown", "Google Doc"
        else:
            ext = fd.extension_of(meta.get("name") or "")
            media = fd.MEDIA_TYPES.get(ext) or (mime if mime in fd.MEDIA_TYPES.values() else None)
            word = ext or "file"
        if media is None:
            raise steps.StepFailure("kind_refused", "file", "", phrases.en("ACCT_FILE_KIND").format(kind=fd.clean_display(mime, 40)))
        version = f"{meta.get('version') or '0'}@{meta.get('modified') or ''}"
        base = {"version": str(meta.get("version") or ""), "modified": str(meta.get("modified") or ""), "mime": mime, "md5": meta.get("md5"),
                "head_revision": meta.get("head_revision"), "source_version": version}
        return media, word, base, version
    if meta.get("kind") != "file" or meta.get("writable") is not True:
        raise steps.StepFailure("not_a_file", "file", "", phrases.en("ACCT_FILE_NOT_FILE").format(reason=fd.clean_display(meta.get("reason") or meta.get("kind"), 80)))
    ext = fd.extension_of(meta.get("name") or "")
    media = fd.MEDIA_TYPES.get(ext)
    if media is None:
        raise steps.StepFailure("kind_refused", "file", "", phrases.en("ACCT_FILE_KIND").format(kind=fd.clean_display(ext or "unknown", 40)))
    base = {"etag": str(meta.get("etag") or ""), "ctag": str(meta.get("ctag") or ""), "size": meta.get("size") if isinstance(meta.get("size"), int) else -1,
            "modified": str(meta.get("modified") or ""), "source_version": str(meta.get("ctag") or "")}
    return media, ext, base, str(meta.get("ctag") or "")


def _prepare(ctx: steps.Context, state: dict) -> dict:
    args = ctx.args
    operation, account = args["operation"], args["account"]
    accounts, reader = _service(ctx, "accounts"), _service(ctx, "files_read")
    address = _asked(accounts.address, account, field="account", next=phrases.en("ACCT_NOT_CONFIGURED").format(account=account))
    read_at = _stamp(ctx.now())
    name, base, gdoc = None, None, False
    if operation == "replace":
        source = _asked(_service(ctx, "file_source").lookup, args["file"], field="file")
        if source is None or source.get("type") != SOURCE_TYPE[account]:
            raise steps.StepFailure("source_mismatch", "file", "", phrases.en("ACCT_FILE_SOURCE").format(source=args["file"], service=fd.SERVICE_NAME[account]))
        meta = _asked(reader.meta, account, ["--id", source["origin"]], field="file", provider=fd.IMPLEMENTATION[account],
                      next="the file could not be read: check that the account is authorized (the authorize command of the account), then start this task again")
        _owned(account, meta, meta.get("name"))
        wanted, word, base, version = _target_media(account, meta)
        if source.get("origin_version") != version:
            raise steps.StepFailure("source_behind", "file", "", phrases.en("ACCT_FILE_BEHIND").format(
                source=args["file"], read=fd.clean_display(source.get("origin_version") or "none", 80), now=fd.clean_display(version, 80)))
        name = fd.clean_display(meta.get("name")) or args["file"]
        content = _content_for(ctx, wanted, word)
        target = {"kind": "file", "label": args["file"], "id": source["origin"]}
    else:
        folder_name = args.get("folder") or "default"
        folder = _target(accounts, account, folder_name)
        target = {"kind": "folder", "label": folder_name, "id": folder}
        if operation == "create":
            name = args["name"]
            gdoc = fd.extension_of(name) == fd.GDOC_WORD
            if gdoc:
                name = name.rsplit(".", 1)[0]
                content = _content_for(ctx, "text/markdown", "Google Doc", gdoc=True)
            else:
                ext = fd.extension_of(name)
                content = _content_for(ctx, fd.MEDIA_TYPES[ext], ext)
        else:
            held = _asked(_service(ctx, "held_files").meta, args["attachment"], field="attachment", next=phrases.en("ATT_NOT_HELD").format(status="gone"))
            given_name = args.get("name") is not None
            name = args.get("name") or fd.safe_name(held["name"])          # the name a sender's file came with, made one this platform writes (a character it refuses becomes `_`)
            problem = fd.name_problem(name, fd.SAVE_EXTENSIONS)
            if problem:
                raise steps.StepFailure("bad_args", "name", "", problem[:200])
            ext = fd.extension_of(name)
            if held.get("kind") not in HELD_KINDS[ext]:
                raise steps.StepFailure("type_mismatch", "name", "", phrases.en("ACCT_FILE_TYPE").format(given=fd.clean_display(held.get("kind"), 20), wanted=ext))
            content = {"kind": "held", "bytes": held["bytes"], "sha256": held["sha256"], "media_type": fd.SAVE_TYPES[ext], "text": None, "path": None,
                       "attachment": held["id"], "gdoc": False}
        looked = _asked(reader.meta, account, ["--folder", folder, "--name", name], field="folder", provider=fd.IMPLEMENTATION[account],
                        next="the folder could not be read: check that the account is authorized and that the folder is still there, then start this task again")
        if looked.get("exists") and operation == "save" and not given_name:          # a file that was sent is saved beside the one of its name, as `name (2).ext`
            for n in range(2, FREE_NAME_TRIES + 2):
                candidate = fd.numbered(name, n)
                if not _asked(reader.meta, account, ["--folder", folder, "--name", candidate], field="folder", provider=fd.IMPLEMENTATION[account],
                              next="the folder could not be read: check that the account is authorized and that the folder is still there, then start this task again").get("exists"):
                    name, looked = candidate, {}
                    break
        if looked.get("exists"):
            raise steps.StepFailure("name_taken", "name", "", phrases.en("ACCT_FILE_NAME_TAKEN"))
    if state.get("pinned_target") not in (None, target["id"]):      # a start over after a stale prepares the same target, or refuses
        raise steps.StepFailure("target_changed", "file" if operation == "replace" else "folder", "", phrases.en("ACCT_FILE_RETARGET"))
    try:
        doc = fd.document(task_id=ctx.task_id, operation=operation, account=account, address=address, target=target, name=name, content=content, base=base,
                          read_at=read_at)
    except Exception as e:      # an EffectError of the document: its reason names a limit, never the content
        raise steps.StepFailure("content_refused", "content", "", str(getattr(e, "reason", ""))[:200]) from None
    written = _asked(_service(ctx, "effect_files").write, ctx.task_id, int(state.get("cycle", 0)), doc)
    state["pinned_target"] = target["id"]
    return {"effect_sha256": written, "operation": operation, "bytes": doc["content"]["bytes"]}


def _open(ctx: steps.Context, state: dict) -> dict:
    """The effect decision of the gate: the effect document read back by the hash `prepare` recorded, its card, its hash."""
    recorded = state["steps"]["prepare"]["result"]["effect_sha256"]
    doc = _service(ctx, "effect_files").read(ctx.task_id, int(state.get("cycle", 0)), recorded)
    fd.check(doc)
    lines = fd.card_lines(doc, recorded)
    return {"title": fd.title(doc)[:200], "body": fd.body(doc, recorded), "payload_sha256": recorded, "payload": {"effect": fd.summary(doc), "card": lines}}


KIND = steps.register(steps.Kind(
    name="file-write",
    order=("prepare", GATE_STEP),
    executors={"prepare": _prepare},
    gates={GATE_STEP: steps.Gate(word=fd.WORD, open=_open, redo="prepare")},
    footprint=lambda args: (),
    check=check,
    unattended=False,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
