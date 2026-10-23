#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Writer provider on Google Drive (class writer:files, package W4a): create a file in a folder of the person's Drive, write a new revision of a
file they have, and (slice R2-A) move a file they own to the Drive trash, after the runtime showed them the exact content or the exact file and they approved
its hash. Nothing here is called by a skill or a step: only the
runtime's effect module for the word `files` (runtime/effect_files.py) starts it, and a read-only seam (`file-meta`) before that.

What it never does (limits L57 and L58): it never deletes a file for good (Drive's call that deletes for good is not in its allow-list), never
empties the trash, never changes a file's name, parents or sharing, and never writes to a file or a folder it was not asked for. The one removal it has is
`trash`: `PATCH /drive/v3/files/{id}` with the body `{"trashed": true}` and nothing else, which moves a file the account owns to the trash, where the person can
restore it (R2-A; the body is a module constant, TRASH_BODY, and the allow-list scan of runtime/tests/test_limits_account_writes.py honours it only there). Its constant ALLOWED lists the only requests its one request function will send;
the content a write sends is the bytes of `--content-file`, checked against the byte count and the sha256 the flags state.

Usage:
  uv run providers/writer/gdrive.py --help
  uv run providers/writer/gdrive.py --check
  uv run providers/writer/gdrive.py file-meta --account <address> --id <file id>
  uv run providers/writer/gdrive.py file-meta --account <address> --folder <folder id> --name <file name>
  uv run providers/writer/gdrive.py create --folder <folder id> --name <file name> --media-type <type> [--gdoc] --content-file <abs path>
        --bytes <n> --sha256 <hex> --idempotency-key <key> --account <address> (--dry-run | --confirmed)
  uv run providers/writer/gdrive.py update --id <file id> --media-type <type> --content-file <abs path> --bytes <n> --sha256 <hex>
        --base-version <v> --base-modified <time> --base-mime <type> [--base-md5 <hex>] [--base-head-revision <id>]
        --idempotency-key <key> --account <address> (--dry-run | --confirmed)
  uv run providers/writer/gdrive.py trash --id <file id> --base-version <v> --base-modified <time> --base-mime <type> --base-parent <folder id>
        --idempotency-key <key> --account <address> (--dry-run | --confirmed)

  --account   the address of the account the document names. Every verb but --check reads it and compares it with the account of the token record: another
              account's token reads and writes nothing (exit 1).
  --check     refreshes the access token (the only network call) and checks that the account token carries the platform's four scopes; prints
              {"ok", "account", "scope", "record"}. Exit 3 when there is no account authorization or it was refused.
  file-meta   one read. By id: {"id", "name", "mime_type", "version", "modified", "md5", "head_revision", "size", "in_trash", "native", "folder",
              "key", "owned"} (owned: the account owns the file and may edit it; only such a file is replaced). By folder and name: the folder (it must exist, be a folder and not be in the trash) and whether a file of that name is in it
              (`exists`, `matches`). Names are another person's text in principle: cleaned to one line, shown, never used as a path.
  create      a NEW file in the folder: it is refused (exit 1) when a file of that name is already there, whatever its content (it never
              overwrites). `--gdoc` makes a Google Doc from Markdown text (Drive converts it on import; to verify live). The file carries the
              private mark appProperties.openhora_key, which is how an approval that runs again finds the file an earlier attempt made.
  update      a NEW REVISION of an existing file. The file is read again first: its version, modified time, md5 and head revision must be the
              base the runtime read, else exit 1 `changed:` and nothing is written. For a file with binary content the head revision it replaces
              is marked keepForever BEFORE the content is written (Drive purges an old revision after 30 days otherwise; at most 200 revisions per
              file can be kept); a Google-native file keeps its own history. Drive v3 has no precondition on a media update, so the gap between the
              read and the write is a few hundred milliseconds wide and is said in providers/writer/README.md.
  trash       move ONE file to the trash (R2-A). The file is read again first: its version, modified time, type and parent must be the base the runtime
              read, it must be a file (not a folder), owned by the account and not already in the trash, else exit 1 `changed:` and nothing is changed. Then
              one `PATCH` sets `trashed` to true. The file is not deleted: Drive keeps it in the trash, from where the owner restores it (Drive's help says
              a trashed file is deleted for good after 30 days; to verify live). A lost answer is found again: a key an earlier attempt left pending, and a
              file that is in the trash now, is the earlier attempt's own and is answered `replayed`.

The dry run (`--dry-run`) reads no credential, opens no connection and prints {"dry_run": true, "requests": [...], "would_sha256", "ledger"}: the
exact list of requests `--confirmed` sends, in order, and the sha256 of its canonical text. `--confirmed` sends exactly that list.

Credentials (never from a flag or a file; contracts/secrets.md):
  GOOGLE_ACCOUNT_TOKEN  the account token, one JSON record of the person's Google account made by providers/accounts/google_auth.py, read
                        through providers/secrets/resolver.py. The runtime passes this one secret and nothing else of the secrets. The token carries
                        the platform's four scopes; a token that lacks one or carries another is refused (exit 3). There is no legacy record for
                        a writer.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read):
  WRITER_GDRIVE_API_BASE     replaces https://www.googleapis.com
  WRITER_GDRIVE_TOKEN_URL    replaces https://oauth2.googleapis.com/token

No redirect is followed with a credential. A verb never retries. Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok;
1 refused with nothing changed (including `changed:`, a moved base, and a service answer that is an error); 2 usage; 3 not configured (no
authorization, one that expired or was revoked, a token that lacks or carries a scope); 4 unknown (the request may have landed: the connection
failed or timed out, or the service answered a server error; the key stays pending and a later attempt looks for its own mark first).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SERVES = "writer:files"
IMPLEMENTATION = "gdrive"
DEFAULT_API_BASE = "https://www.googleapis.com"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
ENV_BASE = "WRITER_GDRIVE_API_BASE"
ENV_TOKEN_URL = "WRITER_GDRIVE_TOKEN_URL"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
USER_AGENT = "openhora-writer-gdrive"
HTTP_TIMEOUT_SECONDS = 60
GOOGLE_PREFIX = "application/vnd.google-apps."
FOLDER_MIME = GOOGLE_PREFIX + "folder"
DOC_MIME = GOOGLE_PREFIX + "document"
FILE_FIELDS = "id,name,mimeType,version,modifiedTime,md5Checksum,headRevisionId,size,parents,trashed,appProperties,ownedByMe,capabilities/canEdit"
PARENT_FIELDS = "id,name,mimeType,trashed"
LIST_FIELDS = "files(id,name,appProperties)"
MARK = "openhora_key"
ID = r"[A-Za-z0-9_-]{1,128}"
REVISION = r"[A-Za-z0-9_~-][A-Za-z0-9_~.-]{0,127}"
ID_RE = re.compile(ID)
REVISION_RE = re.compile(REVISION)
NAME_MAX = 120
NAME_EXTRA = " ._-()"       # besides letters and digits of any script
RESPONSE_LIMIT = 4 * 1024 * 1024
TRASH_BODY = {"trashed": True}      # the whole body of the one request that moves a file to the trash (R2-A): the file stays in the trash, restorable by its owner

# Limit L58: the only requests this writer sends. Every one is on a path under /drive/v3/files or /upload/drive/v3/files. There is no DELETE (Drive's
# call that deletes for good), no call on the trash (no emptying it), no change of a file's metadata outside the media upload's own mark and the one PATCH that
# moves a file to the trash (TRASH_BODY), and no permission call.
ALLOWED = (
    ("GET", r"/drive/v3/files"),
    ("GET", r"/drive/v3/files/" + ID),
    ("PATCH", r"/drive/v3/files/" + ID),
    ("PATCH", r"/drive/v3/files/" + ID + r"/revisions/" + REVISION),
    ("POST", r"/upload/drive/v3/files"),
    ("PATCH", r"/upload/drive/v3/files/" + ID),
)


def _load(name: str, candidates):
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        raise SystemExit(f"error: {candidates[0].name} is not next to this script's folder")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve()
common = _load("providers_writer_files_common", (HERE.parent / "_files_common.py",))
_google = _load("providers_google_account", (HERE.parents[1] / "_google.py", HERE.parent / "_google.py"))
WriterError, one_line, emit = common.WriterError, common.one_line, common.emit
EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = common.EXIT_REFUSED, common.EXIT_USAGE, common.EXIT_NOT_CONFIGURED, common.EXIT_UNKNOWN


# --- configuration and the session -----------------------------------------------------------------------------------------------------


def endpoints() -> tuple:
    """(API base, token URL, test mode). The overrides are for tests, must be loopback URLs and are set together."""
    api, token = os.environ.get(ENV_BASE), os.environ.get(ENV_TOKEN_URL)
    if not api and not token:
        return DEFAULT_API_BASE, DEFAULT_TOKEN_URL, False
    if not (api and token):
        raise WriterError(f"{ENV_BASE} and {ENV_TOKEN_URL} are for tests only and are set together", EXIT_USAGE)
    for name, value in ((ENV_BASE, api), (ENV_TOKEN_URL, token)):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
            raise WriterError(f"{name} is for tests only and must be a loopback URL such as http://127.0.0.1:8080", EXIT_USAGE)
    return api.rstrip("/"), token, True


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy run from a job folder), then providers/secrets/resolver.py."""
    candidates = (HERE.parent / "resolver.py", HERE.parents[1] / "secrets" / "resolver.py")
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        raise WriterError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Session:
    """One access token and the address it is sent to."""

    def __init__(self, base: str, token: str, record: dict):
        self.base, self.token, self.record = base, token, record


ADDRESS = re.compile(r"[^@\s]{1,64}@[^@\s]{1,253}")


def check_account_flag(value) -> str:
    if not isinstance(value, str) or not ADDRESS.fullmatch(value):
        raise WriterError("--account is the address of the account the document names", EXIT_USAGE)
    return value


def open_session(expected: str) -> Session:
    """The session of the account token, only when the token belongs to the account the document names (`--account`): a token of another account writes
    nothing (exit 1)."""
    base, token_url, test_mode = endpoints()
    loaded = _google.load_account_record(secret_resolver(), test_mode, legacy=None, error=WriterError)
    mine = loaded.record.get("account")
    if not isinstance(mine, str) or mine.casefold() != expected.casefold():
        raise WriterError("the account token belongs to another account than the one the document names: nothing was written", EXIT_REFUSED)
    data = _google.refresh_access_token(token_url, loaded.record, WriterError)
    return Session(base, data["access_token"], loaded.record)


# --- one request, through the allow-list -------------------------------------------------------------------------------------------------


def encode(value: str) -> str:
    """An id or a name as it enters a path: percent-encoded, nothing kept (limit L58; the contract of providers/CONTRACT.md)."""
    return urllib.parse.quote(value, safe="")


def query_string(query: dict) -> str:
    return urllib.parse.urlencode(sorted(query.items()), quote_via=urllib.parse.quote, safe="")


def failure(status: int, headers, body: bytes, what: str) -> WriterError:
    """The error for a service answer that is not the one wanted. A 401 is a setup problem (exit 3); 5xx is `unknown` only where the caller says so."""
    message, reasons = "", ""
    try:
        error = json.loads(body).get("error")
        if isinstance(error, dict):
            message = one_line(error.get("message"), 200)
            reasons = ",".join(one_line(e.get("reason"), 40) for e in error.get("errors", []) if isinstance(e, dict))
    except (ValueError, AttributeError):
        pass
    detail = f": {message}{f' [{reasons}]' if reasons else ''}" if message or reasons else ""
    if status == 401:
        return WriterError(f"Drive rejected the access token ({what}){detail}; run: {_google.AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
    if status in (429, 503):
        wait = str((headers.get("Retry-After") if headers is not None else "") or "").strip()
        after = f"; retry after {wait} seconds" if wait.isdigit() else "; try again later"
        return WriterError(f"Drive is busy or limiting requests ({status} on {what}){after}{detail}", EXIT_REFUSED, status)
    if status == 404:
        return WriterError(f"Drive does not know the file or the folder ({what}){detail}", EXIT_REFUSED, status)
    if status == 403:
        return WriterError(f"Drive refused the request ({what}){detail}; check that the Drive API is enabled for the Google Cloud project", EXIT_REFUSED, status)
    return WriterError(f"Drive returned {status} ({what}){detail}", EXIT_REFUSED, status)


def send(session: Session, step: dict, body: bytes | None = None, extra: dict | None = None) -> tuple:
    """Send one request of a plan: (status, headers, at most RESPONSE_LIMIT bytes). Refused unless ALLOWED lists the method and the path (L58). A
    connection that failed or timed out is a WriterError with status None."""
    method, path = step["method"], step["path"]
    common.guarded(ALLOWED, method, path)
    url = session.base + path + (("?" + query_string(step["query"])) if step.get("query") else "")
    headers = {"Authorization": f"Bearer {session.token}", "Accept": "application/json", "User-Agent": USER_AGENT, **(extra or {})}
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with _google.OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.headers, response.read(RESPONSE_LIMIT + 1)
    except _google.AccountError as exc:       # a redirect: never followed with a credential
        raise WriterError(str(exc), EXIT_REFUSED, exc.status) from None
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.headers, exc.read(65536)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        raise WriterError(f"cannot reach Google on {method} {path.split('/')[1]}: {one_line(exc.reason, 120)}") from None
    except TimeoutError:
        raise WriterError(f"Google timed out on {method} {path.split('/')[1]} after {HTTP_TIMEOUT_SECONDS} s") from None
    except OSError as exc:
        raise WriterError(f"the connection to Google failed: {type(exc).__name__}") from None
    except Exception as exc:                  # a header the library refuses or an answer that is not HTTP: the kind only (a message can hold the token)
        raise WriterError(f"the request could not be made or read ({type(exc).__name__})") from None


def read_json(session: Session, step: dict, what: str) -> dict:
    """A read: the JSON object the service answered with 200, else the error (nothing was changed by a read)."""
    status, headers, body = send(session, step)
    if status != 200:
        raise failure(status, headers, body, what)
    return as_object(body, what)


def as_object(body: bytes, what: str) -> dict:
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if not isinstance(data, dict) or len(body) > RESPONSE_LIMIT:
        raise WriterError(f"Drive answered something this provider does not understand ({what})")
    return data


# --- the checked arguments --------------------------------------------------------------------------------------------------------------


def drive_id(value, flag: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise WriterError(f"{flag} is a Drive id (letters, digits, hyphens and underscores)", EXIT_USAGE)
    return value


def check_name(value) -> str:
    """A file name: 1 to 120 characters, letters and digits of any script and ` ._-()`, no leading or trailing space, no `..`, in the NFC form."""
    if (not isinstance(value, str) or not 1 <= len(value) <= NAME_MAX or value != unicodedata.normalize("NFC", value) or value != value.strip(" ")
            or ".." in value or value.startswith("-") or not all(c.isalnum() or c in NAME_EXTRA for c in value)):
        raise WriterError("--name is 1 to 120 characters: letters, digits, spaces and . _ - ( ), and does not start with a hyphen", EXIT_USAGE)
    return value


def quoted(text: str) -> str:
    """A string in a Drive query: backslash and quote escaped."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


# --- the plans: the exact requests of each verb -------------------------------------------------------------------------------------------


def media(media_type: str, count: int, sha: str) -> dict:
    return {"bytes": count, "content_type": media_type, "sha256": sha}


def folder_step(folder: str) -> dict:
    return {"method": "GET", "path": f"/drive/v3/files/{encode(folder)}", "query": {"fields": PARENT_FIELDS}, "body": None}


def name_step(folder: str, name: str) -> dict:
    return {"method": "GET", "path": "/drive/v3/files",
            "query": {"fields": LIST_FIELDS, "pageSize": "10", "q": f"{quoted(folder)} in parents and name = {quoted(name)} and trashed = false"}, "body": None}


def plan_create(folder: str, name: str, media_type: str, count: int, sha: str, key: str, gdoc: bool) -> list:
    """folder check, name check, upload. A Google Doc is made from Markdown text: the metadata names the Google type and the media is text/markdown."""
    kind = DOC_MIME if gdoc else media_type
    return [
        folder_step(folder),
        name_step(folder, name),
        {"method": "POST", "path": "/upload/drive/v3/files", "query": {"fields": FILE_FIELDS, "uploadType": "multipart"},
         "body": {"media": media(media_type, count, sha),
                  "metadata": {"appProperties": {MARK: key}, "mimeType": kind, "name": name, "parents": [folder]}}},
    ]


def plan_update(file_id: str, media_type: str, count: int, sha: str, key: str, native: bool, head_revision) -> list:
    """file read, [keep the head revision], upload. A Google-native file has no binary head revision to keep: Docs keeps its own history."""
    steps = [{"method": "GET", "path": f"/drive/v3/files/{encode(file_id)}", "query": {"fields": FILE_FIELDS}, "body": None}]
    if not native:
        steps.append({"method": "PATCH", "path": f"/drive/v3/files/{encode(file_id)}/revisions/{encode(head_revision)}", "query": {},
                      "body": {"keepForever": True}})
    steps.append({"method": "PATCH", "path": f"/upload/drive/v3/files/{encode(file_id)}", "query": {"fields": FILE_FIELDS, "uploadType": "multipart"},
                  "body": {"media": media(media_type, count, sha), "metadata": {"appProperties": {MARK: key}}}})
    return steps


def plan_trash(file_id: str) -> list:
    """file read, then the one PATCH that moves it to the trash."""
    return [{"method": "GET", "path": f"/drive/v3/files/{encode(file_id)}", "query": {"fields": FILE_FIELDS}, "body": None},
            {"method": "PATCH", "path": f"/drive/v3/files/{encode(file_id)}", "query": {"fields": FILE_FIELDS}, "body": TRASH_BODY}]


def multipart(boundary: str, metadata: dict, media_type: str, data: bytes) -> bytes:
    head = f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode("ascii")
    mid = f"\r\n--{boundary}\r\nContent-Type: {media_type}\r\n\r\n".encode("ascii")
    return head + json.dumps(metadata, sort_keys=True).encode("ascii") + mid + data + f"\r\n--{boundary}--\r\n".encode("ascii")


def boundary_of(key: str, sha: str) -> str:
    return "oh" + hashlib.sha256(f"{key}\n{sha}".encode("ascii")).hexdigest()[:30]


def upload_headers(boundary: str, length: int) -> dict:
    return {"Content-Type": f"multipart/related; boundary={boundary}", "Content-Length": str(length)}


# --- what the service says a file is ------------------------------------------------------------------------------------------------------


def described(meta: dict) -> dict:
    mime = meta.get("mimeType") if isinstance(meta.get("mimeType"), str) else ""
    size = meta.get("size")
    props = meta.get("appProperties") if isinstance(meta.get("appProperties"), dict) else {}
    parents = meta.get("parents") if isinstance(meta.get("parents"), list) else []
    return {"id": meta.get("id"), "name": one_line(meta.get("name"), 200), "mime_type": mime, "version": str(meta.get("version") or ""),
            "modified": str(meta.get("modifiedTime") or ""), "md5": meta.get("md5Checksum") if isinstance(meta.get("md5Checksum"), str) else None,
            "head_revision": meta.get("headRevisionId") if isinstance(meta.get("headRevisionId"), str) else None,
            "size": int(size) if str(size or "").isdigit() else None, "in_trash": bool(meta.get("trashed")),
            "parents": [p for p in parents if isinstance(p, str)][:5], "native": mime.startswith(GOOGLE_PREFIX), "folder": mime == FOLDER_MIME,
            "key": props.get(MARK) if isinstance(props.get(MARK), str) else None,
            "owned": meta.get("ownedByMe") is True and isinstance(meta.get("capabilities"), dict) and meta["capabilities"].get("canEdit") is True}


def landed(meta: dict, expect: dict) -> dict:
    """The answer to a write, checked against what was sent: an id, the name, and for a binary file the size and the md5 of the bytes. A difference is
    `unknown` (the write may have landed as something else), never a success."""
    out = described(meta)
    if not out["id"] or not ID_RE.fullmatch(str(out["id"])):
        raise WriterError("Drive's answer to the write holds no file id: the outcome is unknown", EXIT_UNKNOWN)
    if expect.get("name") is not None and out["name"] != expect["name"]:
        raise WriterError("Drive's answer to the write names another file: the outcome is unknown", EXIT_UNKNOWN)
    if not out["native"] and not expect.get("gdoc"):
        if out["md5"] is not None and out["md5"] != expect["md5"]:
            raise WriterError("Drive's answer to the write has another checksum than the content sent: the outcome is unknown", EXIT_UNKNOWN)
        if out["size"] is not None and out["size"] != expect["bytes"]:
            raise WriterError("Drive's answer to the write has another size than the content sent: the outcome is unknown", EXIT_UNKNOWN)
    return out


def result_of(meta: dict, replayed: bool, **more) -> dict:
    return {"written": True, "replayed": replayed, "id": meta["id"], "name": meta["name"], "mime_type": meta["mime_type"], "version": meta["version"],
            "modified": meta["modified"], "md5": meta["md5"], "bytes": meta["size"], **more}


# --- the verbs -------------------------------------------------------------------------------------------------------------------------


def cmd_check(a) -> int:
    _, token_url, test_mode = endpoints()
    loaded = _google.load_account_record(secret_resolver(), test_mode, legacy=None, error=WriterError)
    _google.refresh_access_token(token_url, loaded.record, WriterError)
    return emit({"ok": True, "account": loaded.record.get("account"), "record": "account", "scope": sorted(_google.PLATFORM_SCOPES),
                 "implementation": IMPLEMENTATION})


def cmd_file_meta(a) -> int:
    if (a.id is None) == (a.folder is None):
        raise WriterError("give --id, or --folder with --name", EXIT_USAGE)
    if a.id is not None:
        if a.name is not None:
            raise WriterError("--name goes with --folder", EXIT_USAGE)
        session = open_session(check_account_flag(a.account))
        meta = read_json(session, {"method": "GET", "path": f"/drive/v3/files/{encode(drive_id(a.id, '--id'))}", "query": {"fields": FILE_FIELDS}},
                         "files.get")
        return emit(described(meta))
    folder, name = drive_id(a.folder, "--folder"), check_name(a.name)
    session = open_session(check_account_flag(a.account))
    parent = described(read_json(session, folder_step(folder), "files.get (folder)"))
    if not parent["folder"] or parent["in_trash"]:
        raise WriterError("the folder is not a folder of the account, or it is in the trash")
    listing = read_json(session, name_step(folder, name), "files.list")
    files = [f for f in (listing.get("files") or []) if isinstance(f, dict)]
    return emit({"folder": {"id": parent["id"], "name": parent["name"]}, "exists": bool(files),
                 "matches": [{"id": f.get("id"), "name": one_line(f.get("name"), 200)} for f in files[:2]]})


def unknown_after(error: WriterError) -> WriterError:
    """The error of a request that changes the account: an answer of the service that says no (a 4xx) changed nothing; no answer at all, or a server
    error, may have landed and is `unknown`."""
    if error.code == EXIT_NOT_CONFIGURED or (error.status is not None and 300 <= error.status < 500):
        return error
    return WriterError(f"{error} (the outcome is unknown: the request may have landed)", EXIT_UNKNOWN, error.status)


def write_request(session: Session, step: dict, body: bytes, headers: dict, what: str) -> dict:
    """The one request that changes a file. Returns the JSON object of a 200 answer; WriterError otherwise, `unknown` unless the service refused it."""
    try:
        status, answer_headers, answer = send(session, step, body, headers)
    except WriterError as e:
        raise unknown_after(e) from None
    if status != 200:
        raise unknown_after(failure(status, answer_headers, answer, what))
    try:
        return as_object(answer, what)
    except WriterError as e:
        raise WriterError(str(e), EXIT_UNKNOWN) from None


def dry_run(steps: list, key: str) -> int:
    entry = common.Ledger(IMPLEMENTATION).peek(key)
    return emit({"dry_run": True, "requests": steps, "would_sha256": common.would_sha256(steps), "ledger": (entry or {}).get("state", "absent")})


def cmd_create(a) -> int:
    folder, name = drive_id(a.folder, "--folder"), check_name(a.name)
    media_type, count, sha = common.check_media_type(a.media_type, images=True), common.check_count(a.bytes, "--bytes"), common.check_sha256(a.sha256, "--sha256")
    key = common.check_key(a.idempotency_key)
    if a.gdoc and media_type != "text/markdown":
        raise WriterError("--gdoc makes a Google Doc from Markdown text: --media-type is text/markdown", EXIT_USAGE)
    steps = plan_create(folder, name, media_type, count, sha, key, bool(a.gdoc))
    if a.dry_run:
        return dry_run(steps, key)
    data = common.read_content(a.content_file, count, sha)
    plan_sha = common.would_sha256(steps)
    ledger = common.Ledger(IMPLEMENTATION)
    claim = ledger.claim(key, plan_sha)
    if claim["state"] == "done":
        return emit({**claim["result"], "replayed": True})
    try:
        session = open_session(check_account_flag(a.account))
        parent = described(read_json(session, steps[0], "files.get (folder)"))
        if not parent["folder"] or parent["in_trash"]:
            raise WriterError("the folder is not a folder of the account, or it is in the trash: nothing was written")
        listing = read_json(session, steps[1], "files.list")
        same = [described(f) for f in (listing.get("files") or []) if isinstance(f, dict) and str(f.get("name", "")).casefold() == name.casefold()]
        ours = [m for m in same if m["key"] == key]
        if ours:                                        # an earlier attempt of this very approval landed and its answer was lost
            out = result_of(ours[0], True, folder=folder)
            ledger.done(key, out)
            return emit(out)
        if same:
            raise WriterError(f"taken: a file named {name!r} is already in the folder: create never replaces a file, nothing was written")
        boundary = boundary_of(key, sha)
        body = multipart(boundary, steps[2]["body"]["metadata"], media_type, data)
        answer = write_request(session, steps[2], body, upload_headers(boundary, len(body)), "files.create")
        out = result_of(landed(answer, {"name": name, "gdoc": bool(a.gdoc), "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(), "bytes": count}),
                        False, folder=folder)
    except WriterError as e:
        if e.code != EXIT_UNKNOWN and claim["state"] == "new":      # nothing changed: a key this run claimed goes back (an unknown outcome, and a key an
            ledger.release(key)                                      # earlier attempt left pending, stay pending: that attempt may have landed)
        raise
    ledger.done(key, out)
    return emit(out)


def cmd_update(a) -> int:
    file_id = drive_id(a.id, "--id")
    media_type, count, sha = common.check_media_type(a.media_type), common.check_count(a.bytes, "--bytes"), common.check_sha256(a.sha256, "--sha256")
    key = common.check_key(a.idempotency_key)
    base_mime = a.base_mime if isinstance(a.base_mime, str) and 3 <= len(a.base_mime) <= 120 and a.base_mime.isprintable() else None
    if base_mime is None or not a.base_version or not a.base_modified:
        raise WriterError("--base-version, --base-modified and --base-mime state the file as the runtime read it", EXIT_USAGE)
    native = base_mime.startswith(GOOGLE_PREFIX)
    head = a.base_head_revision
    if not native and (not isinstance(head, str) or not REVISION_RE.fullmatch(head)):
        raise WriterError("--base-head-revision is the head revision of a file with binary content", EXIT_USAGE)
    if a.base_md5 is not None and not re.fullmatch(r"[0-9a-f]{32}", a.base_md5):
        raise WriterError("--base-md5 is 32 hexadecimal digits", EXIT_USAGE)
    steps = plan_update(file_id, media_type, count, sha, key, native, head)
    if a.dry_run:
        return dry_run(steps, key)
    data = common.read_content(a.content_file, count, sha)
    plan_sha = common.would_sha256(steps)
    ledger = common.Ledger(IMPLEMENTATION)
    claim = ledger.claim(key, plan_sha)
    if claim["state"] == "done":
        return emit({**claim["result"], "replayed": True})
    try:
        session = open_session(check_account_flag(a.account))
        current = described(read_json(session, steps[0], "files.get"))
        if current["key"] == key:                       # this very approval wrote it already (its answer was lost, or the key was released late)
            out = result_of(current, True)
            ledger.done(key, out)
            return emit(out)
        moved = [field for field, now, then in (("version", current["version"], a.base_version), ("modified time", current["modified"], a.base_modified),
                                                ("type", current["mime_type"], base_mime), ("checksum", current["md5"], a.base_md5),
                                                ("head revision", current["head_revision"], head)) if now != then]
        if current["in_trash"] or current["folder"] or not current["owned"] or moved:
            raise WriterError("changed: the file is not the one the runtime read ("
                              + (", ".join(moved) if moved else "it is in the trash, is a folder, or is not owned by the account") + "): nothing was written")
        position = 1
        if not native:
            try:
                kept = write_request(session, steps[position], json.dumps(steps[position]["body"]).encode("ascii"), {"Content-Type": "application/json"},
                                     "revisions.update (keepForever)")
            except WriterError as e:
                if e.status in (400, 403):
                    raise WriterError(f"{e}; Drive keeps at most 200 revisions of a file for ever, so the replaced revision may not be keepable: nothing was written",
                                      EXIT_REFUSED, e.status) from None
                raise
            if kept.get("keepForever") is not True:
                raise WriterError("Drive did not keep the replaced revision: nothing was written")
            position += 1
        boundary = boundary_of(key, sha)
        body = multipart(boundary, steps[position]["body"]["metadata"], media_type, data)
        answer = write_request(session, steps[position], body, upload_headers(boundary, len(body)), "files.update")
        out = result_of(landed(answer, {"name": None, "gdoc": native, "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(), "bytes": count}),
                        False, kept_revision=head if not native else None)
    except WriterError as e:
        if e.code != EXIT_UNKNOWN and claim["state"] == "new":
            ledger.release(key)
        raise
    ledger.done(key, out)
    return emit(out)


def cmd_trash(a) -> int:
    file_id = drive_id(a.id, "--id")
    key = common.check_key(a.idempotency_key)
    base_mime = a.base_mime if isinstance(a.base_mime, str) and 3 <= len(a.base_mime) <= 120 and a.base_mime.isprintable() else None
    parent = drive_id(a.base_parent, "--base-parent") if a.base_parent else None
    if base_mime is None or not a.base_version or not a.base_modified or parent is None:
        raise WriterError("--base-version, --base-modified, --base-mime and --base-parent state the file as the runtime read it", EXIT_USAGE)
    steps = plan_trash(file_id)
    if a.dry_run:
        return dry_run(steps, key)
    ledger = common.Ledger(IMPLEMENTATION)
    claim = ledger.claim(key, common.would_sha256(steps))
    if claim["state"] == "done":
        return emit({**claim["result"], "replayed": True})
    try:
        session = open_session(check_account_flag(a.account))
        current = described(read_json(session, steps[0], "files.get"))
        if current["in_trash"] and claim["state"] == "pending":      # an earlier attempt of this very approval landed and its answer was lost
            out = {"written": True, "replayed": True, "id": current["id"], "moved_to_trash": True, "version": current["version"], "modified": current["modified"]}
            ledger.done(key, out)
            return emit(out)
        moved = [field for field, now, then in (("version", current["version"], a.base_version), ("modified time", current["modified"], a.base_modified),
                                                ("type", current["mime_type"], base_mime), ("folder", current["parents"], [parent])) if now != then]
        if current["in_trash"] or current["folder"] or not current["owned"] or moved:
            raise WriterError("changed: the file is not the one the runtime read ("
                              + (", ".join(moved) if moved else "it is in the trash, is a folder, or is not owned by the account") + "): nothing was changed")
        answer = write_request(session, steps[1], json.dumps(steps[1]["body"]).encode("ascii"), {"Content-Type": "application/json"}, "files.update (trash)")
        done = described(answer)
        if done["id"] != file_id or not done["in_trash"]:
            raise WriterError("Drive's answer does not say the file is in the trash: the outcome is unknown", EXIT_UNKNOWN)
        out = {"written": True, "replayed": False, "id": done["id"], "moved_to_trash": True, "version": done["version"], "modified": done["modified"]}
    except WriterError as e:
        if e.code != EXIT_UNKNOWN and claim["state"] == "new":
            ledger.release(key)
        raise
    ledger.done(key, out)
    return emit(out)


# --- the command line --------------------------------------------------------------------------------------------------------------------


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise WriterError(message, EXIT_USAGE)


def build_parser() -> Parser:
    p = Parser(prog="gdrive.py", add_help=False)
    p.add_argument("verb", nargs="?", choices=["file-meta", "create", "update", "trash"])
    p.add_argument("--check", action="store_true")
    for flag in ("account", "id", "folder", "name", "media-type", "content-file", "bytes", "sha256", "idempotency-key", "base-version", "base-modified", "base-mime",
                 "base-md5", "base-head-revision", "base-parent"):
        p.add_argument("--" + flag)
    for flag in ("gdoc", "dry-run", "confirmed"):
        p.add_argument("--" + flag, action="store_true")
    return p


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--help", "-h"):
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return common.EXIT_OK if argv else EXIT_USAGE
    try:
        a = build_parser().parse_args(argv)
        if a.check:
            if a.verb is not None:
                raise WriterError("--check takes no verb", EXIT_USAGE)
            return cmd_check(a)
        if a.verb is None:
            raise WriterError("give a verb or --check; see --help", EXIT_USAGE)
        if a.verb == "file-meta" and a.account is None:
            raise WriterError("--account is required", EXIT_USAGE)
        if a.verb == "trash":
            if a.account is None and not a.dry_run:
                raise WriterError("--account is required with --confirmed", EXIT_USAGE)
            if a.dry_run == a.confirmed:
                raise WriterError("give exactly one of --dry-run and --confirmed", EXIT_USAGE)
            if a.idempotency_key is None or a.id is None:
                raise WriterError("--id and --idempotency-key are required", EXIT_USAGE)
        if a.verb in ("create", "update"):
            if a.account is None and not a.dry_run:
                raise WriterError("--account is required with --confirmed", EXIT_USAGE)
            if a.dry_run == a.confirmed:
                raise WriterError("give exactly one of --dry-run and --confirmed", EXIT_USAGE)
            if not a.content_file and not a.dry_run:
                raise WriterError("--content-file is required with --confirmed", EXIT_USAGE)
            for flag in ("media_type", "bytes", "sha256", "idempotency_key"):
                if getattr(a, flag) is None:
                    raise WriterError(f"--{flag.replace('_', '-')} is required", EXIT_USAGE)
        return {"file-meta": cmd_file_meta, "create": cmd_create, "update": cmd_update, "trash": cmd_trash}[a.verb](a)
    except WriterError as e:
        print(f"error: {_google.scrub(str(e))}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
