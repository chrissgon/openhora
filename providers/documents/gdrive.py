#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Documents provider on Google Drive: an implementation of the class integration:documents that serves the files a
person picked as SOURCES of a project (runtime/sources.py, decision D13), read only.

It reads files, never folders: the Drive scope is `drive.file`, under which a file the person picked in the Picker is
given to this app, and a picked folder is not (the folder's children stay out of reach). A Google Doc, Sheet or Slides
file is exported through the Drive API; every other file is downloaded as it is. The provider never parses a file: it
writes the bytes to `--out-dir` and prints their description, and the runtime hands them to the converter (a container
with no network) like any other source (limit L27). Nothing here writes to Drive: `write`, `notice` and `resolve` answer
"not supported" (exit 2) until the outputs package gives Drive a write-back, and `comments` too.

`drive.file` lets an app read AND write every file the person picked. It is not a read-only scope, and the access token
it gives could change those files. This provider uses it for GET requests only, and the tests show that no other method
is ever sent. Say so to anyone who asks what the token can do.

Usage:
  uv run providers/documents/gdrive.py --help
  uv run providers/documents/gdrive.py --check
  uv run providers/documents/gdrive.py stat --id <file id> --as-source
  uv run providers/documents/gdrive.py read --id <file id> --as-source --out-dir <folder> [--max-bytes <n>]
  uv run providers/documents/gdrive.py pick  [--no-browser]

  --check     refreshes the access token (the one network call) and checks its scope (the platform's four for the account token; drive.file and nothing wider for the legacy record);
              prints {"ok": true, "scope", "obtained_at"}. Exit 3 when there is no authorization or it was refused.
  stat        the file's name, type, size and `version`, and whether it can be read as a source (`supported`, with the
              `reason` when not). `version` changes when the file changes: it is the Drive `version` and `modifiedTime`
              together. One metadata call, no content.
  read        the file's bytes into <out-dir>/content (a folder that exists, no link; a new file, mode 0600), and
              {"id", "name", "mime_type", "version", "content", "exported_as", "bytes", "sha256", "file", "as_source"}.
              `content` is "markdown" (a Google Doc exported as text/markdown: text already) or "file" (anything else: the
              runtime sniffs the type from the bytes). --max-bytes bounds the content (default 25 MiB, the intake's cap).
  Both take --as-source, as the Notion provider's read does, so that the verbs of a later write-back keep their own flags.
  pick        opens Google's Picker for the person on a one-shot page on 127.0.0.1 (gdrive_auth.py pick, which see) and prints
              {"picked": [{"id", "name", "mime_type"}], "cancelled": bool}. It registers nothing and reads no file; the runtime does,
              with `stat` and `read`. The local address to open is printed on stderr. Needs the one-time `gdrive_auth.py authorize`.

What each Google type is exported to (Drive's own export, `files.export`, limited by Google to 10 MB of exported content):
  Google Doc        text/markdown; if the service answers 400 (it does not offer that format), the Word format
                    (application/vnd.openxmlformats-officedocument.wordprocessingml.document)
  Google Sheet      the Excel format (application/vnd.openxmlformats-officedocument.spreadsheetml.sheet): every sheet
  Google Slides     application/pdf
  any other Google file (a drawing, a form, a script, a site, a shortcut) and a folder: refused (exit 1), with the reason.
Every other file is downloaded (`alt=media`) when its size is within --max-bytes; the md5 Drive records is checked on
what arrived, and a file that changed meanwhile is refused.

Credentials (never from a flag or a file; contracts/secrets.md):
  GOOGLE_ACCOUNT_TOKEN  the account token, read first: one JSON record of the person's Google account (refresh token, the Desktop app client,
                        the scope, the address), made by providers/accounts/google_auth.py. It carries the platform's four scopes, `drive`
                        among them: it can read and change every file of the Drive, and this provider sends GET requests only. A token that
                        lacks one of the four or carries another is refused (exit 3).
  Legacy, for one cycle, used only when no account record exists (a warning on stderr says so, once per process):
  GDRIVE_SOURCES_TOKEN  one JSON record, read through providers/secrets/resolver.py (the environment, then the OS secret
                        store, username gdrive-sources): {"refresh_token", "client_id", "client_secret", "api_key",
                        "project_number", "scope", "obtained_at"}, written by providers/documents/gdrive_auth.py after the
                        person's consent. Printed nowhere.
Test overrides (tests only, loopback URLs only, both set together; the secret store is then never read):
  INTEGRATION_DOCUMENTS_GDRIVE_API_BASE    replaces https://www.googleapis.com
  INTEGRATION_DOCUMENTS_GDRIVE_TOKEN_URL   replaces https://oauth2.googleapis.com/token

No redirect is followed: every request carries a credential to an address that was checked. A verb never retries.
Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 failed (the service answered an error or could
not be reached; a file that is not found or not given to the app; a type that is not read), 2 usage (a missing or bad flag,
a verb that is not supported), 3 not configured (no authorization, one that expired or was revoked, a rejected client, a
token with a scope wider than drive.file).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_API_BASE = "https://www.googleapis.com"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
SOURCES_ONLY = True   # the contract tests of the class (providers/documents/tests) skip the write verbs for this implementation
SCOPE = "https://www.googleapis.com/auth/drive.file"   # the one scope: gdrive_auth.py asks for it and this file requires it
SECRET = "GDRIVE_SOURCES_TOKEN"
KEYRING_USERNAME = "gdrive-sources"
AUTH_COMMAND = "uv run providers/documents/gdrive_auth.py authorize"
ENV_BASE = "INTEGRATION_DOCUMENTS_GDRIVE_API_BASE"
ENV_TOKEN_URL = "INTEGRATION_DOCUMENTS_GDRIVE_TOKEN_URL"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
HTTP_TIMEOUT_SECONDS = 60
DEFAULT_MAX_BYTES = 25 * 1024 * 1024    # runtime/sources.py ORIGINAL_CAP: what the intake takes
HARD_MAX_BYTES = 256 * 1024 * 1024      # no --max-bytes goes past this
EXPORT_LIMIT_BYTES = 10 * 1024 * 1024   # Google's limit on exported content (files.export reference); a 403 names it
FILE_FIELDS = "id,name,mimeType,size,version,modifiedTime,md5Checksum,trashed"
FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,100}")
OUT_NAME = "content"
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3

GOOGLE_PREFIX = "application/vnd.google-apps."
FOLDER = GOOGLE_PREFIX + "folder"
DOC = GOOGLE_PREFIX + "document"
SHEET = GOOGLE_PREFIX + "spreadsheet"
SLIDES = GOOGLE_PREFIX + "presentation"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MARKDOWN = "text/markdown"
# Google type -> the export formats to try, in order (the next one only after a 400: the format is not offered).
EXPORTS = {DOC: (MARKDOWN, DOCX), SHEET: (XLSX,), SLIDES: ("application/pdf",)}


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def _google_module():
    """providers/_google.py, by path: next to this folder's parent first (the workbench), then next to this file (a copy)."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parents[1] / "_google.py", here.parent / "_google.py") if c.is_file()), None)
    if path is None:
        raise SystemExit("error: providers/_google.py is not next to this script's folder")
    spec = importlib.util.spec_from_file_location("providers_google_account", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# The account token (one record, the platform's scope set) is read first; the old record is the legacy fallback for one cycle.
_google = _google_module()


def one_line(text, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def emit(obj: dict) -> int:
    print(json.dumps(obj))
    return EXIT_OK


# --- configuration ---------------------------------------------------------------------------------------------------------


def endpoints() -> tuple[str, str, bool]:
    """(API base, token URL, test mode). The overrides are for tests and must be loopback URLs, both set together."""
    api, token = os.environ.get(ENV_BASE), os.environ.get(ENV_TOKEN_URL)
    if not api and not token:
        return DEFAULT_API_BASE, DEFAULT_TOKEN_URL, False
    if not (api and token):
        raise ProviderError(f"{ENV_BASE} and {ENV_TOKEN_URL} are for tests only and are set together", EXIT_USAGE)
    for name, value in ((ENV_BASE, api), (ENV_TOKEN_URL, token)):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
            raise ProviderError(f"{name} is for tests only and must be a loopback URL such as http://127.0.0.1:8080", EXIT_USAGE)
    return api.rstrip("/"), token, True


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy run from a job folder), then
    providers/secrets/resolver.py."""
    here = Path(__file__).resolve()
    candidates = (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py")
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RECORD_TEXTS = ("refresh_token", "client_id", "client_secret")


def parse_record(text: str) -> dict:
    """The authorization record from its JSON text; ProviderError (not configured) when it is unreadable or lacks what a refresh needs."""
    try:
        record = json.loads(text)
    except ValueError:
        record = None
    if not isinstance(record, dict) or not all(isinstance(record.get(k), str) and record[k] for k in RECORD_TEXTS):
        raise ProviderError(f"the stored Drive authorization is unreadable or incomplete; run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    for key in RECORD_TEXTS:
        if any(ch.isspace() or not ch.isprintable() for ch in record[key]):
            raise ProviderError(f"the Drive authorization holds a {key} with whitespace or control characters; run: {AUTH_COMMAND}",
                                EXIT_NOT_CONFIGURED)
    return record


def load_legacy_record(test_mode: bool) -> dict:
    """The legacy record (GDRIVE_SOURCES_TOKEN), with the Picker's key when it has one. The Picker needs it, so gdrive_auth.py reads this."""
    found = secret_resolver().resolve(SECRET, allow_store=not test_mode)
    if not found:
        raise ProviderError(f"no Drive authorization: run {AUTH_COMMAND}, or export {SECRET} (the JSON record)", EXIT_NOT_CONFIGURED)
    return parse_record(found[0])


def load_record(test_mode: bool) -> dict:
    """The record to sign in with: the account record (GOOGLE_ACCOUNT_TOKEN) first, else the legacy one for one cycle. The dict carries
    `kind` ("account" or "legacy"), which decides the scope rule of the refresh."""
    def legacy():
        found = secret_resolver().resolve(SECRET, allow_store=not test_mode)
        return (parse_record(found[0]), found[1]) if found else None

    loaded = _google.load_account_record(secret_resolver(), test_mode, legacy=(KEYRING_USERNAME, legacy, AUTH_COMMAND), error=ProviderError)
    return {**loaded.record, "kind": "legacy" if loaded.legacy else "account"}


# --- HTTP ------------------------------------------------------------------------------------------------------------------


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: every request carries a credential to an address that was checked."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        path = urllib.parse.urlparse(req.full_url).path
        raise ProviderError(f"refusing to follow a {code} redirect on {req.get_method()} {path}; the request carries a credential",
                            EXIT_SERVICE, code)


OPENER = urllib.request.build_opener(RefuseRedirect)


def http(method: str, url: str, headers: dict, body: bytes | None = None, limit: int = 1024 * 1024) -> tuple[int, bytes]:
    """One request; (status, at most limit + 1 bytes of the body) for any HTTP answer, ProviderError otherwise. Only GET is ever
    sent to the API (the token endpoint is the one POST)."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    path = urllib.parse.urlparse(url).path
    try:
        with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read(65536)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach Google on {method} {path}: {one_line(exc.reason, 120)}") from None
    except TimeoutError:
        raise ProviderError(f"Google timed out on {method} {path} after {HTTP_TIMEOUT_SECONDS} s") from None
    except OSError as exc:
        raise ProviderError(f"the connection to Google failed on {method} {path}: {type(exc).__name__}") from None


def token_request(token_url: str, form: dict) -> dict:
    """POST to the token endpoint, mapping OAuth errors to exit codes. Shared with gdrive_auth.py."""
    status, body = http("POST", token_url, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                        urllib.parse.urlencode(form).encode())
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        return data
    error = one_line(data.get("error"), 80) if isinstance(data, dict) else ""
    description = one_line(data.get("error_description"), 160) if isinstance(data, dict) else ""
    detail = f"{error}: {description}" if description else error or "no error code"
    if error == "invalid_grant":
        if form.get("grant_type") == "refresh_token":
            raise ProviderError(f"Google refused the refresh token ({detail}): the authorization expired or was revoked (a project "
                                f"left in \"Testing\" expires it after seven days; access removed in the Google Account does too). "
                                f"Run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
        raise ProviderError(f"Google refused the authorization code ({detail}); run it again", EXIT_SERVICE, status)
    if error in ("invalid_client", "unauthorized_client"):
        raise ProviderError(f"Google rejected the OAuth client ({detail}): check the client id and secret of a Desktop app client",
                            EXIT_NOT_CONFIGURED, status)
    if status == 200:
        raise ProviderError("the token response has no access_token", EXIT_SERVICE, status)
    raise ProviderError(f"the Google token endpoint returned {status} ({detail})", EXIT_SERVICE, status)


def check_scope(granted) -> None:
    """Refuse a token whose reported scope is anything but drive.file alone: a wider scope than this app asks for is a setup error to fix,
    not a token to use, and a response that reports no scope cannot be shown to be the narrow one."""
    scopes = set(str(granted or "").split())
    if scopes != {SCOPE}:
        extra = ", ".join(sorted(scopes - {SCOPE})) or "none"
        raise ProviderError(f"the token reports {', '.join(sorted(scopes)) or 'no scope'} where exactly {SCOPE} is wanted (extra: {extra}): "
                            f"nothing was read. Revoke the app's access in the Google Account and run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)


def refresh_access_token(token_url: str, record: dict) -> str:
    """A new access token (held in memory, used for this process) from the refresh token; checks the scope: the platform's set for the
    account record, exactly drive.file for the legacy one."""
    if record.get("kind") == "account":
        return _google.refresh_access_token(token_url, record, ProviderError)["access_token"]
    data = token_request(token_url, {"client_id": record["client_id"], "client_secret": record["client_secret"],
                                     "grant_type": "refresh_token", "refresh_token": record["refresh_token"]})
    check_scope(data.get("scope"))
    return data["access_token"]


class Drive:
    """The Drive API as this provider uses it: GET requests with one access token."""

    def __init__(self, base: str, access_token: str, command: str = AUTH_COMMAND):
        self.base, self.token, self.command = base, access_token, command

    def get(self, path: str, params: dict, limit: int) -> tuple[int, bytes]:
        url = self.base + path + "?" + urllib.parse.urlencode(params)
        return http("GET", url, {"Authorization": f"Bearer {self.token}", "Accept": "*/*", "User-Agent": "openhora-documents-gdrive"},
                    limit=limit)

    def failure(self, status: int, body: bytes, what: str) -> ProviderError:
        reasons, message = "", ""
        try:
            error = json.loads(body).get("error")
            if isinstance(error, dict):
                message = one_line(error.get("message"), 200)
                reasons = ",".join(one_line(e.get("reason"), 40) for e in error.get("errors", []) if isinstance(e, dict))
        except (ValueError, AttributeError):
            pass
        detail = f": {message}{f' [{reasons}]' if reasons else ''}" if message or reasons else ""
        if status == 401:
            return ProviderError(f"Drive rejected the access token ({what}){detail}; run: {self.command}", EXIT_NOT_CONFIGURED, status)
        if status == 404 and self.command != AUTH_COMMAND:   # the account token sees every file of the account: nothing to pick
            return ProviderError(f"Drive does not know the file for the authorized account ({what}){detail}: check the file id", EXIT_SERVICE,
                                 status)
        if status == 404:
            return ProviderError(f"Drive does not know the file, or this app was not given it ({what}){detail}: a file is given to the "
                                 "app when the person picks it; pick it again", EXIT_SERVICE, status)
        if status == 403 and "exportSizeLimitExceeded" in reasons:
            return ProviderError(f"the file is over Google's {EXPORT_LIMIT_BYTES // (1024 * 1024)} MB limit on exported content "
                                 f"({what}): split it or send a copy of the part you need", EXIT_SERVICE, status)
        if status == 403:
            return ProviderError(f"Drive refused the request ({what}){detail}; check that the Drive API is enabled in the Google Cloud "
                                 "project and that the file was picked", EXIT_SERVICE, status)
        return ProviderError(f"Drive returned {status} ({what}){detail}", EXIT_SERVICE, status)

    def meta(self, file_id: str) -> dict:
        status, body = self.get(f"/drive/v3/files/{file_id}", {"fields": FILE_FIELDS, "supportsAllDrives": "true"}, 1024 * 1024)
        if status != 200:
            raise self.failure(status, body, "files.get")
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if not isinstance(data, dict) or data.get("id") != file_id or not isinstance(data.get("mimeType"), str):
            raise ProviderError("Drive answered a file description this provider does not understand")
        return data


def open_drive() -> Drive:
    base, token_url, test_mode = endpoints()
    record = load_record(test_mode)
    return Drive(base, refresh_access_token(token_url, record), _google.AUTH_COMMAND if record["kind"] == "account" else AUTH_COMMAND)


# --- the verbs -------------------------------------------------------------------------------------------------------------


def file_id(value) -> str:
    if not isinstance(value, str) or not FILE_ID.fullmatch(value):
        raise ProviderError("--id is a Drive file id (letters, digits, hyphens and underscores)", EXIT_USAGE)
    return value


def version_of(meta: dict) -> str:
    """The version token: changes when the file changes. Drive's `version` is a counter of every change on the server; the modified
    time rides with it so that a token never repeats for two different states."""
    return f"{meta.get('version') or '0'}@{meta.get('modifiedTime') or ''}"


def reading_plan(meta: dict) -> tuple[bool, str]:
    """(supported, reason): whether the file is read as a source, and why not when it is not."""
    mime = meta["mimeType"]
    if meta.get("trashed"):
        return False, "the file is in the trash"
    if mime == FOLDER:
        return False, "a folder is not a source: under drive.file the files inside a picked folder are not given to the app; pick the files"
    if mime in EXPORTS:
        return True, ""
    if mime.startswith(GOOGLE_PREFIX):
        return False, f"a Google file of type {mime[len(GOOGLE_PREFIX):]} is not read as a source (documents, sheets and slides are)"
    return True, ""


def described(meta: dict) -> dict:
    supported, reason = reading_plan(meta)
    out = {"id": meta["id"], "name": one_line(meta.get("name"), 200), "mime_type": meta["mimeType"], "version": version_of(meta),
           "archived": bool(meta.get("trashed")), "supported": supported, "reason": reason}
    if "size" in meta:
        out["size"] = int(meta["size"]) if str(meta["size"]).isdigit() else None
    return out


def cmd_check(args: dict) -> int:
    _, token_url, test_mode = endpoints()
    record = load_record(test_mode)
    refresh_access_token(token_url, record)
    if record["kind"] == "account":
        return emit({"ok": True, "scope": sorted(_google.PLATFORM_SCOPES), "account": record.get("account"), "record": "account",
                     "obtained_at": record.get("obtained_at")})
    return emit({"ok": True, "scope": SCOPE, "obtained_at": record.get("obtained_at")})


def cmd_stat(args: dict) -> int:
    ident = file_id(args.get("--id"))
    return emit(described(open_drive().meta(ident)))


def max_bytes_of(args: dict) -> int:
    raw = args.get("--max-bytes")
    if raw is None:
        return DEFAULT_MAX_BYTES
    if not str(raw).isdigit() or not 1 <= int(raw) <= HARD_MAX_BYTES:
        raise ProviderError(f"--max-bytes is a whole number from 1 to {HARD_MAX_BYTES}", EXIT_USAGE)
    return int(raw)


def out_folder(value) -> str:
    """The folder the bytes go into: it exists, is a real folder (not a link) and is this user's."""
    if not value:
        raise ProviderError("--out-dir is required", EXIT_USAGE)
    try:
        info = os.lstat(value)
    except OSError:
        raise ProviderError("--out-dir must be a folder that exists", EXIT_USAGE) from None
    if not stat.S_ISDIR(info.st_mode) or (hasattr(os, "getuid") and info.st_uid != os.getuid()):
        raise ProviderError("--out-dir must be a real folder of this user, not a link", EXIT_USAGE)
    return value


def write_new(folder: str, name: str, data: bytes) -> None:
    fd = os.open(os.path.join(folder, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def export_of(drive: Drive, meta: dict, limit: int) -> tuple[bytes, str]:
    """The exported bytes and the format that served them: the formats of EXPORTS in order, the next only after a 400."""
    last = None
    for mime in EXPORTS[meta["mimeType"]]:
        status, body = drive.get(f"/drive/v3/files/{meta['id']}/export", {"mimeType": mime}, limit)
        if status == 200:
            if len(body) > limit:
                raise ProviderError(f"the exported file is over {limit} bytes: send the part you need")
            return body, mime
        if status == 400:
            last = drive.failure(status, body, f"files.export to {mime}")
            continue
        raise drive.failure(status, body, f"files.export to {mime}")
    raise last or ProviderError("Drive offers no export format this provider reads for the file")


def download_of(drive: Drive, meta: dict, limit: int) -> bytes:
    size = meta.get("size")
    if str(size or "").isdigit() and int(size) > limit:
        raise ProviderError(f"the file is {size} bytes, over the {limit} that one source may be: send the part you need")
    status, body = drive.get(f"/drive/v3/files/{meta['id']}", {"alt": "media", "supportsAllDrives": "true"}, limit)
    if status != 200:
        raise drive.failure(status, body, "files.get alt=media")
    if len(body) > limit:
        raise ProviderError(f"the file is over the {limit} bytes that one source may be: send the part you need")
    wanted = meta.get("md5Checksum")
    if wanted and hashlib.md5(body, usedforsecurity=False).hexdigest() != wanted:   # integrity, not security
        raise ProviderError("the file changed while it was being downloaded: read it again")
    return body


def cmd_read(args: dict) -> int:
    ident = file_id(args.get("--id"))
    folder = out_folder(args.get("--out-dir"))
    limit = max_bytes_of(args)
    drive = open_drive()
    meta = drive.meta(ident)
    supported, reason = reading_plan(meta)
    if not supported:
        raise ProviderError(reason)
    if meta["mimeType"] in EXPORTS:
        data, exported = export_of(drive, meta, limit)
    else:
        data, exported = download_of(drive, meta, limit), None
    try:
        write_new(folder, OUT_NAME, data)
    except OSError as exc:
        raise ProviderError(f"the content cannot be written in --out-dir: {exc.strerror}", EXIT_SERVICE) from None
    return emit({"id": ident, "name": one_line(meta.get("name"), 200), "mime_type": meta["mimeType"], "version": version_of(meta),
                 "content": "markdown" if exported == MARKDOWN else "file", "exported_as": exported, "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(), "file": OUT_NAME, "as_source": True})


def cmd_pick(args: dict) -> int:
    """The Picker, for the runtime: gdrive_auth.py's `pick` (it runs the one-shot page and prints the picks), through its own main so that its
    errors keep their exit codes."""
    path = Path(__file__).resolve().parent / "gdrive_auth.py"
    spec = importlib.util.spec_from_file_location("workbench_documents_gdrive_auth", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.main(["pick"] + (["--no-browser"] if args.get("--no-browser") else []))


def cmd_unsupported(args: dict) -> int:
    raise ProviderError("this verb is not supported by the Drive provider: it reads the files a person picked as sources and writes "
                        "nothing to Drive", EXIT_USAGE)


VERBS = {"stat": cmd_stat, "read": cmd_read, "pick": cmd_pick, "comments": cmd_unsupported, "write": cmd_unsupported, "notice": cmd_unsupported,
         "resolve": cmd_unsupported}
READS = ("stat", "read")
VALUE_FLAGS = ("--id", "--out-dir", "--max-bytes", "--config-file", "--path", "--markdown-file", "--idempotency-key", "--notice",
               "--text")
SWITCHES = ("--check", "--as-source", "--no-browser", "--dry-run", "--confirmed", "--not-created")


def parse_args(argv: list) -> tuple:
    verb, args, i = None, {}, 0
    while i < len(argv):
        word = argv[i]
        if word in VALUE_FLAGS:
            if i + 1 >= len(argv):
                raise ProviderError(f"{word} needs a value", EXIT_USAGE)
            args[word] = argv[i + 1]
            i += 2
        elif word in SWITCHES:
            args[word] = True
            i += 1
        elif verb is None and word in VERBS:
            verb = word
            i += 1
        else:
            raise ProviderError(f"unknown argument {one_line(word, 60)!r}; see --help", EXIT_USAGE)
    return verb, args


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("--help", "-h"):
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return EXIT_OK if argv else EXIT_USAGE
    try:
        verb, args = parse_args(argv)
        if args.get("--check"):
            if verb is not None:
                raise ProviderError("--check takes no verb", EXIT_USAGE)
            return cmd_check(args)
        if verb is None:
            raise ProviderError("give a verb or --check; see --help", EXIT_USAGE)
        if verb in READS and not args.get("--as-source"):
            raise ProviderError("the Drive provider serves sources only: give --as-source", EXIT_USAGE)
        if args.get("--as-source") and verb not in READS:
            raise ProviderError("--as-source is for the verbs stat and read only", EXIT_USAGE)
        if args.get("--no-browser") and verb != "pick":
            raise ProviderError("--no-browser is for the verb pick only", EXIT_USAGE)
        return VERBS[verb](args)
    except ProviderError as e:
        print(f"error: {_google.scrub(str(e))}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
