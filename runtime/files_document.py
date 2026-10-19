#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of a write to the person's own Drive or OneDrive, and nothing that writes (package W4a): what the step kind `file-write` builds and the
effect kind `files` approves. A new file in a folder (`create`), a new revision of a file the person registered as a source (`replace`), and a file the
person sent through a messaging app, saved to a folder (`save`). The effect document (its keys, its checks, the credential scan of a text), the lines of
its card, the hash of the requests the writer will send (the dry run), the key the writer's ledger keeps, and the arguments of the writer's verbs. It holds
no function that calls a provider or executes an effect: that is runtime/effect_files.py, reached from the operation `approve` only. The step kind imports
this module and not that one, so a step kind has no function in reach that could write (limit L30; docs/architecture/platform/outputs.md).

The document. `effect` ("files"), `operation` (create, replace, save), `task` (the step task that prepared it), `account` (google or microsoft),
`implementation` (gdrive or onedrive: the writer the account maps to), `address` (the account's address from the project's `accounts`), `target`
({"kind": "folder", "label": the name `accounts` lists, "id": the folder's id or, on OneDrive, its /path} for a new file; {"kind": "file", "label": the
source id, "id": the Drive file id or the OneDrive "<drive id>/<item id>"} for a new revision), `name` (the name of the new file, or the current name of the
file), `content` ({"kind": text, file or held; "bytes"; "sha256"; "media_type"; "text" (the text itself, kind text only); "path" (a file of the project's
docs/: the file of kind `file`, or where a text came from); "attachment" (the held file's number, kind held only); "gdoc" (a Google Doc made from
Markdown)}), `base` (the state of the file when it was read, for a replace: Drive version, modified time, type, md5 and head revision; OneDrive eTag, cTag
and size; and `source_version`, the version of the source the person looked at; null for a new file), `read_at`, `dry_run_sha256` and `idempotency_key`.

The hash the person approves is the hash of this document, so it covers the account, the writer, the target (the folder's id or the file's id), the name,
every byte of the content (by its sha256, and the text itself when it is text), the base, and the exact list of requests the writer will send: the writer
refuses `--confirmed` unless its own dry run hashes to `dry_run_sha256` (limit L55). `requests(doc)` builds that list and must equal the writer's dry run
byte for byte (a test starts each writer's `--dry-run` and compares).

Standard library only, plus the credential scan of runtime/workcopy.py, the error class of runtime/effects.py and the phrase table. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unicodedata
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import operations  # noqa: E402  (the command line the card shows)
import phrases  # noqa: E402
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

WORD = "files"
OPERATIONS = ("create", "replace", "save")
IMPLEMENTATION = {"google": "gdrive", "microsoft": "onedrive"}
SERVICE_NAME = {"google": "Google Drive", "microsoft": "OneDrive"}
KEYS = ("effect", "operation", "task", "account", "implementation", "address", "target", "name", "content", "base", "read_at", "dry_run_sha256",
        "idempotency_key")
TEXT_MAX = 64 * 1024                  # bytes of a text that is typed or read from the project: it is shown whole on the card
FILE_MAX = 25 * 1024 * 1024           # bytes of a file of the project or a held file (what the writers send in one request)
NAME_MAX = 120
NAME_EXTRA = " ._-()"                 # besides the letters and digits of any script
# The media type each extension is written as (providers/writer/_files_common.py MEDIA_TYPES holds the same table: a test compares).
MEDIA_TYPES = {"md": "text/markdown", "txt": "text/plain", "csv": "text/csv", "pdf": "application/pdf",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
               "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
               "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
TEXT_TYPES = ("text/markdown", "text/plain", "text/csv")
CREATE_EXTENSIONS = ("md", "txt", "docx")      # plus the word `gdoc`, which makes a Google Doc from Markdown text
SAVE_EXTENSIONS = tuple(MEDIA_TYPES)
GDOC_WORD = "gdoc"
TITLE_KEY = {"create": "TITLE_FILE_CREATE", "replace": "TITLE_FILE_REPLACE", "save": "TITLE_FILE_SAVE"}
SHA256 = re.compile(r"[0-9a-f]{64}")
KEY = re.compile(r"files-[0-9a-f]{32}")
LABEL = re.compile(r"[a-z0-9-]{1,32}")                       # the name `accounts` lists for a folder, or a source id (project_config.ACCOUNT_NAME, sources.SOURCE_ID)
DRIVE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
MS_FOLDER_ID = re.compile(r"[A-Za-z0-9_=!-]{1,200}")
MS_ITEM_PART = re.compile(r"[A-Za-z0-9!._-]{1,200}")
DOCS_PATH = re.compile(r"docs/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ETAG = re.compile(r'[A-Za-z0-9{}",=_:-]{1,200}')
REVISION = re.compile(r"[A-Za-z0-9_~-][A-Za-z0-9_~.-]{0,127}")
MD5 = re.compile(r"[0-9a-f]{32}")
HIDDEN = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")                # control, format, separators, surrogate, private use: never in a card field, except \n and \t in a text
GOOGLE_PREFIX = "application/vnd.google-apps."
DOC_MIME = GOOGLE_PREFIX + "document"
FOLDER_MIME = GOOGLE_PREFIX + "folder"
# The fields a Drive answer is asked for (providers/writer/gdrive.py FILE_FIELDS, PARENT_FIELDS, LIST_FIELDS), and a OneDrive item's.
DRIVE_FILE_FIELDS = "id,name,mimeType,version,modifiedTime,md5Checksum,headRevisionId,size,parents,trashed,appProperties,ownedByMe,capabilities/canEdit"
DRIVE_PARENT_FIELDS = "id,name,mimeType,trashed"
DRIVE_LIST_FIELDS = "files(id,name,appProperties)"
DRIVE_MARK = "openhora_key"
ONEDRIVE_ITEM_FIELDS = "id,name,eTag,cTag,size,file,folder,package,remoteItem,deleted,malware,parentReference,lastModifiedDateTime,createdDateTime"
ONEDRIVE_FOLDER_FIELDS = "id,name,folder,deleted"
UPLOAD_PATH = "/upload-session"


def sha(data) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _usage(reason: str):
    return effects.EffectError("usage", reason)


# --- names and text -------------------------------------------------------------------------------------------------------------------------


def name_problem(name, extensions) -> str:
    """Why a file name is not one the platform writes, or "" when it is: 1 to 120 characters, letters and digits of any script and ` ._-()`, in the NFC
    form, no leading or trailing space, no `..`, not starting with a hyphen, not ending in a dot, with an extension of `extensions`."""
    if not isinstance(name, str) or not 1 <= len(name) <= NAME_MAX or name != unicodedata.normalize("NFC", name) or name != name.strip(" ") \
            or ".." in name or name.startswith("-") or name.endswith(".") or not any(c.isalnum() for c in name) \
            or not all(c.isalnum() or c in NAME_EXTRA for c in name):
        return phrases.en("ACCT_FILE_NAME_BAD")
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in extensions:
        return phrases.en("ACCT_FILE_NAME_EXT").format(extensions=", ".join("." + e for e in extensions))
    return ""


def extension_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def clean_display(value, width: int = 200) -> str:
    """A name a service gave (another person's text in principle), as a card line may show it: one line, no control, format or separator character (each
    becomes `?`), at most `width` characters."""
    text = value if isinstance(value, str) else ""
    text = "".join("?" if unicodedata.category(c) in HIDDEN else c for c in " ".join(text.split()))
    return text[:width]


def text_problem(text) -> str:
    """Why a text cannot be written as it is shown on a card, or "": it is not empty, holds no NUL, no control character but the line end and the tab,
    and no format, separator, surrogate or private-use character (a card with one is no card: a hidden character could make a line say what it does
    not); at most TEXT_MAX bytes."""
    if not isinstance(text, str) or not text.strip():
        return phrases.en("ACCT_FILE_TEXT_EMPTY")
    if len(text.encode("utf-8", errors="replace")) > TEXT_MAX:
        return phrases.en("ACCT_FILE_TEXT_BIG").format(max=TEXT_MAX)
    for c in text:
        if c in "\n\t":
            continue
        if unicodedata.category(c) in HIDDEN:
            return phrases.en("ACCT_FILE_TEXT_HIDDEN")
    if any(frame_like(line) for line in text.split("\n")):
        return phrases.en("ACCT_FILE_TEXT_FRAME")
    return ""


FRAME_MARK = "-----"
DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u2500\u2501\ufe58\ufe63\uff0d\u00ad"      # look-alikes of a hyphen that NFKC leaves alone
MARKDOWN = " \t#>*_`~|+:"      # what a Markdown renderer strips or turns into a style before a line's visible text
BULLET = re.compile(r"(?:[-+*]|\d+[.)])\s+")


def frame_like(line: str) -> bool:
    """Whether the visible form of a line of the person's text starts with the mark of the card's frame rules (five hyphens), as a phone shows it after a
    Markdown renderer made a heading, a quote, a bold span or a list item of it: NFKC, the look-alike dashes read as hyphens, the Markdown markers and a list
    bullet stripped. Such a line could look like the end of the text (the card also puts a mark in front of every line of the text, so this is the second
    guard)."""
    seen = unicodedata.normalize("NFKC", line)
    seen = "".join("-" if unicodedata.category(c) == "Pd" or c in DASHES else c for c in seen)
    for _ in range(8):
        stripped = seen.lstrip(MARKDOWN)
        found = BULLET.match(stripped)
        stripped = stripped[found.end():] if found else stripped
        if stripped == seen:
            break
        seen = stripped
    return seen.startswith(FRAME_MARK)


GUTTER = "\u2502"      # the mark in front of every line of the text on the card: a line of the text can never be taken for a line of the card


def guttered(text: str) -> str:
    """The text as the card shows it: every line behind the gutter mark, an empty line too, the last line break dropped. A renderer that reads Markdown finds a
    line that begins with the mark, never a heading, a quote, a rule or a fence."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(f"{GUTTER} {line}" if line else GUTTER for line in lines)


def lines_as_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --- the document ------------------------------------------------------------------------------------------------------------------------------


def key_of(doc: dict) -> str:
    """The idempotency key: `files-` and 32 hex digits of the sha256 of the task, the operation, the account, the writer, the target, the name, the
    content (by its hash) and the base, so one write is made once however many decisions reach it."""
    pieces = {"task": doc["task"], "operation": doc["operation"], "account": doc["account"], "implementation": doc["implementation"],
              "target": doc["target"], "name": doc["name"], "content": doc["content"]["sha256"], "gdoc": doc["content"]["gdoc"], "base": doc["base"]}
    return "files-" + sha(json.dumps(pieces, sort_keys=True, ensure_ascii=True))[:32]


def document(*, task_id: int, operation: str, account: str, address: str, target: dict, name: str, content: dict, base, read_at: str) -> dict:
    """The effect document, checked. EffectError usage when a piece is not in its form. The writer is the account's; the dry run and the key derive from the
    other fields."""
    doc = {"effect": WORD, "operation": operation, "task": task_id, "account": account, "implementation": IMPLEMENTATION.get(account), "address": address,
           "target": target, "name": name, "content": content, "base": base, "read_at": read_at, "dry_run_sha256": "0" * 64, "idempotency_key": "files-" + "0" * 32}
    _shape(doc)
    doc["idempotency_key"] = key_of(doc)
    doc["dry_run_sha256"] = dry_run_sha256(doc)
    return check(doc)


def content_of(kind: str, data: bytes, media_type: str, *, text=None, path=None, attachment=None, gdoc: bool = False) -> dict:
    """The `content` piece of a document for bytes: the text itself (kind text) or only its hash."""
    return {"kind": kind, "bytes": len(data), "sha256": sha(data), "media_type": media_type, "text": text, "path": path, "attachment": attachment, "gdoc": gdoc}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _shape(doc) -> None:
    """The form of every piece, before the derived values (the key and the dry run) are checked."""
    if not isinstance(doc, dict) or set(doc) != set(KEYS) or doc["effect"] != WORD:
        raise _usage("the effect document of a file write has exactly its keys")
    if doc["operation"] not in OPERATIONS:
        raise _usage("operation is create, replace or save")
    if not _is_int(doc["task"]) or doc["task"] < 1:
        raise _usage("task is a task id")
    if doc["account"] not in IMPLEMENTATION or doc["implementation"] != IMPLEMENTATION[doc["account"]]:
        raise _usage("the account is google or microsoft, and the writer is the one the account maps to")
    if not isinstance(doc["address"], str) or not 3 <= len(doc["address"]) <= 254 or any(unicodedata.category(c) in HIDDEN for c in doc["address"]):
        raise _usage("address is the account's address")
    if not isinstance(doc["read_at"], str) or not STAMP.fullmatch(doc["read_at"]):
        raise _usage("read_at is a UTC time: YYYY-MM-DDTHH:MM:SSZ")
    operation, account = doc["operation"], doc["account"]
    _target(doc["target"], operation, account)
    _content(doc, operation, account)
    _base(doc["base"], operation, account)
    if operation == "replace":
        if not isinstance(doc["name"], str) or not 1 <= len(doc["name"]) <= 200 or clean_display(doc["name"]) != doc["name"]:      # the current name is a service's word, shown cleaned
            raise _usage("the name of the file is one line without a control or invisible character")
        return
    gdoc = doc["content"]["gdoc"]
    # A Google Doc has no extension: its name is checked as if it were Markdown.
    problem = name_problem(doc["name"] + ".md", ("md",)) if gdoc else name_problem(doc["name"], CREATE_EXTENSIONS if operation == "create" else SAVE_EXTENSIONS)
    if problem:
        raise _usage(problem)
    if not gdoc and MEDIA_TYPES[extension_of(doc["name"])] != doc["content"]["media_type"]:
        raise _usage("the media type of the content is the one the extension of the name says")


def _target(target, operation: str, account: str) -> None:
    kind = "file" if operation == "replace" else "folder"
    if not isinstance(target, dict) or set(target) != {"kind", "label", "id"} or target["kind"] != kind or not isinstance(target["label"], str) \
            or not LABEL.fullmatch(target["label"]) or not isinstance(target["id"], str):
        raise _usage(f"the target of a {operation} is a {kind}: its kind, the name the project lists (or the source id) and its id")
    ident = target["id"]
    if kind == "folder":
        ok = DRIVE_ID.fullmatch(ident) if account == "google" else (MS_FOLDER_ID.fullmatch(ident) and set(ident) != {"-"}) or _ms_path(ident)
    elif account == "google":
        ok = DRIVE_ID.fullmatch(ident)
    else:
        parts = ident.split("/")
        ok = len(parts) == 2 and all(MS_ITEM_PART.fullmatch(p) and set(p) != {"."} for p in parts)
    if not ok:
        raise _usage("the target's id is not an id of that service")


def _ms_path(value: str) -> bool:
    if not value.startswith("/") or len(value) > 400 or value == "/":
        return False
    return all(0 < len(s) <= 100 and s not in (".", "..") and s == s.strip(" ") and not s.endswith(".") and all(c.isalnum() or c in NAME_EXTRA for c in s)
               for s in value[1:].split("/"))


def _content(doc: dict, operation: str, account: str) -> None:
    content = doc["content"]
    keys = {"kind", "bytes", "sha256", "media_type", "text", "path", "attachment", "gdoc"}
    if not isinstance(content, dict) or set(content) != keys or content["kind"] not in ("text", "file", "held"):
        raise _usage("content is text, a file of the project or a held file")
    if not _is_int(content["bytes"]) or not 1 <= content["bytes"] <= FILE_MAX or not isinstance(content["sha256"], str) \
            or not SHA256.fullmatch(content["sha256"]) or content["media_type"] not in MEDIA_TYPES.values() or not isinstance(content["gdoc"], bool):
        raise _usage("the content states its size, its sha256 and its media type")
    kind = content["kind"]
    if kind == "text":
        text = content["text"]
        if not isinstance(text, str) or content["attachment"] is not None or content["media_type"] not in TEXT_TYPES:
            raise _usage("a text content holds the text, a text media type and no attachment")
        data = text.encode("utf-8")
        if content["bytes"] != len(data) or content["sha256"] != sha(data):
            raise _usage("the text is not the one whose size and hash the document states")
        problem = text_problem(text)
        if problem:
            raise _usage(problem)
        if content["path"] is not None and not (isinstance(content["path"], str) and DOCS_PATH.fullmatch(content["path"]) and ".." not in content["path"].split("/")):
            raise _usage("a text read from the project comes from a file under docs/")
        why = workcopy.scan(data)
        if why:
            raise _usage(f"the text {why}: it is not written anywhere")
        if content["bytes"] > TEXT_MAX:
            raise _usage(f"the text is over {TEXT_MAX} bytes")
    elif kind == "file":
        if content["text"] is not None or content["attachment"] is not None or not isinstance(content["path"], str) or not DOCS_PATH.fullmatch(content["path"]) \
                or ".." in content["path"].split("/") or content["media_type"] in TEXT_TYPES:
            raise _usage("a file of the project is named by its path under docs/ and holds no text in the document")
    else:
        if content["text"] is not None or content["path"] is not None or not _is_int(content["attachment"]) or content["attachment"] < 1:
            raise _usage("a held file is named by its number")
        if operation != "save":
            raise _usage("a held file is only saved, never written over a file")
    if operation == "save" and kind != "held":
        raise _usage("a save writes a file the person sent")
    if operation != "save" and kind == "held":
        raise _usage("only a save writes a held file")
    if content["gdoc"] and (account != "google" or operation != "create" or kind != "text" or content["media_type"] != "text/markdown"):
        raise _usage("a Google Doc is made from Markdown text, in a Google Drive, by a create")


def _base(base, operation: str, account: str) -> None:
    if operation != "replace":
        if base is not None:
            raise _usage("a new file has no base")
        return
    if account == "google":
        keys = {"version", "modified", "mime", "md5", "head_revision", "source_version"}
        if not isinstance(base, dict) or set(base) != keys or not all(isinstance(base[k], str) and 0 < len(base[k]) <= 200 and base[k].isprintable()
                                                                      for k in ("version", "modified", "mime", "source_version")):
            raise _usage("the base of a Drive file is its version, modified time, type, checksum, head revision and the source's version")
        native = base["mime"].startswith(GOOGLE_PREFIX)
        if native and (base["md5"] is not None or base["head_revision"] is not None):
            raise _usage("a Google-native file has no checksum and no binary head revision")
        if not native and not (isinstance(base["md5"], str) and MD5.fullmatch(base["md5"]) and isinstance(base["head_revision"], str)
                               and REVISION.fullmatch(base["head_revision"])):
            raise _usage("a file with binary content has a checksum and a head revision")
    else:
        keys = {"etag", "ctag", "size", "modified", "source_version"}
        if not isinstance(base, dict) or set(base) != keys or not all(isinstance(base[k], str) and ETAG.fullmatch(base[k]) for k in ("etag", "ctag")) \
                or not _is_int(base["size"]) or base["size"] < 0 or not all(isinstance(base[k], str) and 0 < len(base[k]) <= 200 and base[k].isprintable()
                                                                           for k in ("source_version", "modified")):
            raise _usage("the base of a OneDrive file is its eTag, cTag, size, modified time and the source's version")


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the write."""
    _shape(doc)
    if not isinstance(doc["idempotency_key"], str) or not KEY.fullmatch(doc["idempotency_key"]) or doc["idempotency_key"] != key_of(doc):
        raise _usage("the key is the one the content derives")
    if not isinstance(doc["dry_run_sha256"], str) or not SHA256.fullmatch(doc["dry_run_sha256"]) or doc["dry_run_sha256"] != dry_run_sha256(doc):
        raise _usage("dry_run_sha256 is the hash of the requests the writer will send")
    return doc


# --- the requests the writer will send (its dry run) ---------------------------------------------------------------------------------------------


def enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _quoted(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _media(doc: dict) -> dict:
    content = doc["content"]
    return {"bytes": content["bytes"], "content_type": content["media_type"], "sha256": content["sha256"]}


def _ms_folder_path(folder: str) -> str:
    return f"/me/drive/items/{enc(folder)}" if not folder.startswith("/") else "/me/drive/root:/" + "/".join(enc(s) for s in folder[1:].split("/"))


def _ms_child_path(folder: str, name: str, tail: str = "") -> str:
    if not folder.startswith("/"):
        return f"/me/drive/items/{enc(folder)}:/{enc(name)}" + tail
    return "/me/drive/root:/" + "/".join(enc(s) for s in folder[1:].split("/")) + f"/{enc(name)}" + tail


def requests(doc: dict) -> list:
    """The exact list of requests the writer sends for this document, in order: [{"method", "path", "query", "body"[, "if_match"]}]. Equal to what the
    writer's `--dry-run` prints (providers/writer/README.md; a test starts the writer and compares)."""
    operation, key, ident = doc["operation"], doc["idempotency_key"], doc["target"]["id"]
    if doc["implementation"] == "gdrive":
        if operation in ("create", "save"):
            gdoc = doc["content"]["gdoc"]
            return [
                {"method": "GET", "path": f"/drive/v3/files/{enc(ident)}", "query": {"fields": DRIVE_PARENT_FIELDS}, "body": None},
                {"method": "GET", "path": "/drive/v3/files",
                 "query": {"fields": DRIVE_LIST_FIELDS, "pageSize": "10",
                           "q": f"{_quoted(ident)} in parents and name = {_quoted(doc['name'])} and trashed = false"}, "body": None},
                {"method": "POST", "path": "/upload/drive/v3/files", "query": {"fields": DRIVE_FILE_FIELDS, "uploadType": "multipart"},
                 "body": {"media": _media(doc),
                          "metadata": {"appProperties": {DRIVE_MARK: key}, "mimeType": DOC_MIME if gdoc else doc["content"]["media_type"], "name": doc["name"],
                                       "parents": [ident]}}},
            ]
        base = doc["base"]
        native = base["mime"].startswith(GOOGLE_PREFIX)
        steps = [{"method": "GET", "path": f"/drive/v3/files/{enc(ident)}", "query": {"fields": DRIVE_FILE_FIELDS}, "body": None}]
        if not native:
            steps.append({"method": "PATCH", "path": f"/drive/v3/files/{enc(ident)}/revisions/{enc(base['head_revision'])}", "query": {},
                          "body": {"keepForever": True}})
        steps.append({"method": "PATCH", "path": f"/upload/drive/v3/files/{enc(ident)}", "query": {"fields": DRIVE_FILE_FIELDS, "uploadType": "multipart"},
                      "body": {"media": _media(doc), "metadata": {"appProperties": {DRIVE_MARK: key}}}})
        return steps
    if operation in ("create", "save"):
        return [
            {"method": "GET", "path": _ms_folder_path(ident), "query": {"$select": ONEDRIVE_FOLDER_FIELDS}, "body": None},
            {"method": "PUT", "path": _ms_child_path(ident, doc["name"], ":/content"), "query": {"@microsoft.graph.conflictBehavior": "fail"},
             "body": {"media": _media(doc)}},
        ]
    drive, item = ident.split("/")
    base_path = f"/drives/{enc(drive)}/items/{enc(item)}"
    count = doc["content"]["bytes"]
    return [
        {"method": "GET", "path": base_path, "query": {"$select": ONEDRIVE_ITEM_FIELDS}, "body": None},
        {"method": "POST", "path": base_path + "/createUploadSession", "query": {}, "if_match": doc["base"]["etag"],
         "body": {"item": {"@microsoft.graph.conflictBehavior": "replace"}}},
        {"method": "PUT", "path": UPLOAD_PATH, "query": {}, "body": {"content_range": f"bytes 0-{count - 1}/{count}", "media": _media(doc)}},
    ]


def dry_run_sha256(doc: dict) -> str:
    """The sha256 of the canonical text of requests(doc): sorted keys, no spaces, ASCII escapes (providers/writer/_files_common.py would_sha256)."""
    return sha(json.dumps(requests(doc), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii"))


def provider_args(doc: dict, content_file=None) -> tuple:
    """(the writer's verb, its flags) for this document, without --dry-run or --confirmed. `content_file` is the absolute path of the private copy of the
    content (omitted for a dry run, which reads no file)."""
    content, target, base = doc["content"], doc["target"], doc["base"]
    common = ["--media-type", content["media_type"]] + (["--content-file", content_file] if content_file else []) \
        + ["--bytes", str(content["bytes"]), "--sha256", content["sha256"], "--idempotency-key", doc["idempotency_key"], "--account", doc["address"]]
    if doc["operation"] != "replace":
        return "create", ["--folder", target["id"], "--name", doc["name"], *(["--gdoc"] if content["gdoc"] else []), *common]
    if doc["implementation"] == "gdrive":
        extra = (["--base-md5", base["md5"]] if base["md5"] else []) + (["--base-head-revision", base["head_revision"]] if base["head_revision"] else [])
        return "update", ["--id", target["id"], "--base-version", base["version"], "--base-modified", base["modified"], "--base-mime", base["mime"], *extra,
                          *common]
    return "replace", ["--id", target["id"], "--base-etag", base["etag"], "--base-ctag", base["ctag"], "--base-size", str(base["size"]), *common]


def meta_args(doc: dict) -> list:
    """The flags of the writer's read-only verb `file-meta` that reads the target again just before the write (replace only)."""
    flags = ["--id", doc["target"]["id"], "--account", doc["address"]]
    return flags


def unchanged(doc: dict, meta: dict) -> str:
    """"" when what the writer's `file-meta` printed is the file the document was made from; else the words of what moved. Replace only."""
    base = doc["base"]
    if doc["implementation"] == "gdrive":
        pairs = (("version", meta.get("version"), base["version"]), ("modified time", meta.get("modified"), base["modified"]), ("type", meta.get("mime_type"), base["mime"]),
                 ("checksum", meta.get("md5"), base["md5"]), ("head revision", meta.get("head_revision"), base["head_revision"]))
    else:
        pairs = (("eTag", meta.get("etag"), base["etag"]), ("cTag", meta.get("ctag"), base["ctag"]), ("size", meta.get("size"), base["size"]))
    gone = meta.get("in_trash") is True or meta.get("folder") is True or meta.get("writable") is False
    unowned = meta.get("owned") is not True
    moved = [name for name, now, then in pairs if now != then] + (["it is in the trash, or is not a file"] if gone else []) \
        + (["it is not owned by the account"] if unowned else [])
    return ", ".join(moved)


def content_matches(meta: dict, data: bytes):
    """Whether the hash the service reports for a file (OneDrive `file.hashes`: sha256Hash where it has one, else sha1Hash) is the hash of `data`: True or False,
    or None when the service reported none this code can compare (quickXorHash alone), which proves nothing."""
    if isinstance(meta.get("sha256"), str) and meta["sha256"]:
        return meta["sha256"].lower() == sha(data)
    if isinstance(meta.get("sha1"), str) and meta["sha1"]:
        return meta["sha1"].lower() == hashlib.sha1(data).hexdigest()      # integrity of a file against the service's own report, not security
    return None


def landed(doc: dict, meta: dict, data: bytes) -> bool:
    """Whether what the writer's `file-meta` printed is the write of THIS document, made by an earlier attempt whose answer was lost: on Drive the private mark
    of the document's key; on OneDrive the file's own content hash equal to the approved bytes (a file that moved to other bytes is the person's edit, and one
    whose hash cannot be compared proves nothing). Replace only."""
    if doc["implementation"] == "gdrive":
        return meta.get("key") == doc["idempotency_key"]
    return content_matches(meta, data) is True


# --- what the person reads --------------------------------------------------------------------------------------------------------------------


def title(doc: dict) -> str:
    """The title of the pending decision: a phrase of the table, written by code (runtime/account_start.py checks it)."""
    return phrases.en(TITLE_KEY[doc["operation"]])


def size_text(count: int) -> str:
    """A size as a unit symbol, the same in every language: `812 B`, `3.5 KiB`, `12.0 MiB`."""
    for symbol, unit in (("MiB", 1024 * 1024), ("KiB", 1024)):
        if count >= unit:
            return f"{count / unit:.1f} {symbol}"
    return f"{count} B"


def kept_line(doc: dict) -> str:
    """The key of the line that says what becomes of the replaced revision, true of the service and the type of file: a Drive file with binary content keeps
    it for ever (up to the service's 200), a Google Doc keeps its own history, OneDrive keeps versions by its retention settings."""
    if doc["account"] == "microsoft":
        return "CARD_FILE_KEPT_ONEDRIVE"
    return "CARD_FILE_KEPT_DOC" if doc["base"]["mime"].startswith(GOOGLE_PREFIX) else "CARD_FILE_KEPT_DRIVE"


def card_lines(doc: dict, digest: str) -> list:
    """The card, line by line: [[phrase key, {field: text}], ...], every key of the family CARD_ (runtime/phrases.py). The values are the person's or a
    service's words and are never translated."""
    content, target, operation = doc["content"], doc["target"], doc["operation"]
    service = SERVICE_NAME[doc["account"]]
    lines = [[{"create": "CARD_FILE_CODE_NEW", "save": "CARD_FILE_CODE_SAVE"}.get(operation, "CARD_FILE_CODE_REPLACE"),
              {"read_at": doc["read_at"].replace("T", " ").replace("Z", " UTC")} if operation == "replace" else {}],
             ["CARD_ACCOUNT", {"account": doc["account"], "address": doc["address"]}],
             ["CARD_FILE_NAME", {"name": doc["name"], "service": service}]]
    lines.append(["CARD_FILE_SOURCE", {"source": target["label"]}] if operation == "replace" else ["CARD_FILE_FOLDER", {"folder": target["label"]}])
    if operation == "replace":
        base = doc["base"]
        revision = base["version"] if doc["account"] == "google" else base["etag"]
        lines.append(["CARD_FILE_OWNED", {"address": doc["address"]}])
        lines.append(["CARD_FILE_BASE", {"revision": clean_display(revision), "modified": clean_display(base["modified"])}])
        lines.append([kept_line(doc), {}])
    else:
        lines.append(["CARD_FILE_NEW", {}])
    if content["gdoc"]:
        lines.append(["CARD_FILE_GDOC", {}])
    short = content["sha256"][:12]
    if operation == "save":
        lines.append(["CARD_FILE_SAVE", {"name": doc["name"], "size": size_text(content["bytes"]), "sha_short": short}])
    elif content["kind"] == "file":
        lines.append(["CARD_FILE_PROJECT", {"path": content["path"], "size": size_text(content["bytes"]), "sha_short": short}])
    else:
        lines.append(["CARD_FILE_TEXT", {"content": guttered(content["text"])}])
    lines.append(["CARD_FILE_HASH", {"sha": digest}])
    lines.append(["CARD_FILE_APPROVE", {"command": operations.command_line("approve", "<project>", pending_id="<this pending decision's id>", sha256=digest)}])
    return lines


def body(doc: dict, digest: str) -> str:
    """What the terminal and the page show of the decision, and what is stored as its body: the card's lines in English."""
    return phrases.card_text(card_lines(doc, digest))


def describe(doc: dict) -> str:
    """What is approved, in one line (the state file's row and the approval's record)."""
    where = f"the folder {doc['target']['label']}" if doc["operation"] != "replace" else f"the source {doc['target']['label']}"
    verb = {"create": "create the file", "save": "save the file the person sent as", "replace": "write a new revision of the file"}[doc["operation"]]
    return f"{verb} {doc['name']} ({doc['content']['bytes']} bytes, sha256 {doc['content']['sha256'][:12]}) in {SERVICE_NAME[doc['account']]}, {where}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the text."""
    return {"operation": doc["operation"], "account": doc["account"], "target": doc["target"]["kind"], "bytes": doc["content"]["bytes"],
            "content_sha256": doc["content"]["sha256"], "dry_run_sha256": doc["dry_run_sha256"]}


def facts(doc: dict, result: dict) -> dict:
    """What the execution records of a write that landed: closed words, numbers and the service's ids."""
    return {"written": True, "replayed": bool(result.get("replayed")), "operation": doc["operation"], "account": doc["account"], "id": result.get("id"),
            "name": clean_display(result.get("name")), "bytes": result.get("bytes"), "sha256": doc["content"]["sha256"], "idempotency_key": doc["idempotency_key"]}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
