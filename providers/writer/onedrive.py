#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Writer provider on OneDrive (class writer:files, package W4a): create a file in a folder of the person's OneDrive, and write a new version of a file
they have, after the runtime showed them the exact content and they approved its hash. Nothing here is called by a skill or a step: only the runtime's
effect module for the word `files` (runtime/effect_files.py) starts it, and a read-only seam (`file-meta`) before that.

What it never does (limits L57 and L58): it never deletes an item, never moves, renames or shares one, and never writes to an item or a folder it was
not asked for. Its constant ALLOWED lists the only requests its one request function will send; the content a write sends is the bytes of
`--content-file`, checked against the byte count and the sha256 the flags state.

Usage:
  uv run providers/writer/onedrive.py --help
  uv run providers/writer/onedrive.py --check
  uv run providers/writer/onedrive.py file-meta --id <drive id>/<item id>
  uv run providers/writer/onedrive.py file-meta --folder <folder item id | /folder/path> --name <file name>
  uv run providers/writer/onedrive.py create --folder <folder item id | /folder/path> --name <file name> --media-type <type> --content-file <abs path>
        --bytes <n> --sha256 <hex> --idempotency-key <key> (--dry-run | --confirmed)
  uv run providers/writer/onedrive.py replace --id <drive id>/<item id> --media-type <type> --content-file <abs path> --bytes <n> --sha256 <hex>
        --base-etag <eTag> --base-ctag <cTag> --base-size <n> --idempotency-key <key> (--dry-run | --confirmed)

  --check     refreshes the access token (the only network call) and checks that the account token carries the platform's permissions; prints
              {"ok", "account_kind", "tenant", "scope", "rotation"}. Exit 3 when there is no account authorization or it was refused.
  file-meta   one read. By id: {"id", "name", "etag", "ctag", "size", "modified", "mime_type", "kind", "writable", "reason"}. By folder and name:
              the folder (it must exist and be a folder) and whether an item of that name is in it (`exists`, `match`). Names are another person's
              text in principle: cleaned to one line, shown, never used as a path.
  create      a NEW file in the folder: `PUT .../content` with @microsoft.graph.conflictBehavior=fail, so a file of that name makes Graph answer 409
              and the verb exit 1 whatever its content (it never overwrites). At most 25 MiB (Graph takes 250 MB in one PUT).
  replace     a NEW VERSION of an existing file, through an upload session created with `If-Match: <eTag>`: Graph answers 412 when the file moved
              since the runtime read it, and the verb exits 1 `changed:` with nothing written. The file is read again before the session is made
              and its eTag, cTag and size must be the base. OneDrive keeps the earlier version in the file's version history (retention is the
              service's own setting). The upload address Graph names is a bearer credential: it must be https and on a host of the closed list
              (api.onedrive.com, 1drv.com, sharepoint.com; to verify live), is called with no Authorization header, and is never printed.

The dry run (`--dry-run`) reads no credential, opens no connection and prints {"dry_run": true, "requests": [...], "would_sha256", "ledger"}: the
exact list of requests `--confirmed` sends, in order, and the sha256 of its canonical text. `--confirmed` sends exactly that list.

Credentials (never from a flag or a file; contracts/secrets.md):
  MICROSOFT_ACCOUNT_TOKEN  the account record (see providers/accounts/README.md), read through providers/secrets/resolver.py. The runtime passes this
                           one secret and nothing else of the secrets. The token carries the platform's permissions; one that lacks one or carries
                           another is refused (exit 3). There is no legacy record for a writer. The rotation of the refresh token is written back
                           into this record under the lock the readers use (providers/_msgraph.py store_rotation).
Test overrides (tests only, loopback URLs and names only, all three set together; the secret store is then never read or written):
  WRITER_ONEDRIVE_API_BASE       replaces https://graph.microsoft.com/v1.0
  WRITER_ONEDRIVE_TOKEN_URL      replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token
  WRITER_ONEDRIVE_UPLOAD_HOSTS   replaces the list of upload hosts (comma-separated loopback names)

No redirect is followed with a credential. A verb never retries. Prints one JSON object on stdout; diagnostics on stderr. Exit codes: 0 ok;
1 refused with nothing changed (including `changed:`, a moved base, and a service answer that is an error); 2 usage; 3 not configured; 4 unknown (the
request may have landed: the connection failed or timed out, or the service answered a server error; the key stays pending and a later attempt looks
for its own write first).
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import sys
import unicodedata
import urllib.parse
from pathlib import Path

SERVES = "writer:files"
IMPLEMENTATION = "onedrive"
ENV_UPLOAD_HOSTS = "WRITER_ONEDRIVE_UPLOAD_HOSTS"
UPLOAD_HOST_SUFFIXES = ("api.onedrive.com", "1drv.com", "sharepoint.com")      # to verify live; providers/writer/README.md says what was seen
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
UPLOAD_PATH = "/upload-session"       # how a request to the pre-authenticated upload address is named for the allow-list: its own path is Graph's and secret
ITEM_FIELDS = "id,name,eTag,cTag,size,file,folder,package,remoteItem,deleted,malware,parentReference,lastModifiedDateTime,createdDateTime"
FOLDER_FIELDS = "id,name,folder,deleted"
NAME_MAX = 120
NAME_EXTRA = " ._-()"
RESPONSE_LIMIT = 1024 * 1024
ID_PART = re.compile(r"[A-Za-z0-9!._-]{1,200}")
ETAG = re.compile(r'[A-Za-z0-9{}",=_:-]{1,200}')
CLOCK_SLACK = datetime.timedelta(seconds=90)      # between this machine's clock and the service's, when a lost answer is looked for

# Limit L58: the only requests this writer sends. A segment is percent-encoded, holds no `/` or `:` and is not only dots. There is no DELETE, no move
# or rename (PATCH), no copy, no permission or sharing call, and no call on the recycle bin.
SEG = r"(?!\.+(?:[/:]|$))[A-Za-z0-9_%.~=-]{1,600}"
ALLOWED = (
    ("GET", r"/me/drive/items/" + SEG),
    ("GET", r"/me/drive/items/" + SEG + r":/" + SEG),
    ("GET", r"/me/drive/root:(/" + SEG + r")+"),
    ("GET", r"/drives/" + SEG + r"/items/" + SEG),
    ("PUT", r"/me/drive/items/" + SEG + r":/" + SEG + r":/content"),
    ("PUT", r"/me/drive/root:(/" + SEG + r")+:/content"),
    ("POST", r"/drives/" + SEG + r"/items/" + SEG + r"/createUploadSession"),
    ("PUT", UPLOAD_PATH),
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
msgraph = _load("providers_msgraph", (HERE.parents[1] / "_msgraph.py", HERE.parent / "_msgraph.py"))
WriterError, one_line, emit = common.WriterError, common.one_line, common.emit
EXIT_REFUSED, EXIT_USAGE, EXIT_NOT_CONFIGURED, EXIT_UNKNOWN = common.EXIT_REFUSED, common.EXIT_USAGE, common.EXIT_NOT_CONFIGURED, common.EXIT_UNKNOWN
PROFILE = msgraph.account_profile(
    run_hint="uv run providers/writer/onedrive.py", env_prefix="WRITER_ONEDRIVE", user_agent="openhora-writer-onedrive",
    not_found="OneDrive does not know the item or the folder, or it is not in the person's own OneDrive",
    forbidden_hint="check that the account token carries the platform's whole set (Files.ReadWrite) and that the item is the person's own")


def converted(call, *args, **kwargs):
    """Run a function of providers/_msgraph.py, whose error type is its own, and raise ours with the same words, exit code and status."""
    try:
        return call(*args, **kwargs)
    except msgraph.ProviderError as e:
        raise WriterError(str(e), e.code, e.status) from None


# --- configuration and the session ------------------------------------------------------------------------------------------------------


def secret_resolver():
    return msgraph.secret_resolver(__file__)


def endpoints() -> tuple:
    """(API base, token URL or None for the tenant's own, upload hosts, test mode). The overrides are for tests, name loopback addresses only and are set
    all together."""
    base, token_url, _, test_mode = converted(msgraph.endpoints, PROFILE, ())
    hosts = os.environ.get(ENV_UPLOAD_HOSTS)
    if not test_mode:
        if hosts:
            raise WriterError(f"{ENV_UPLOAD_HOSTS} is for tests only and is set with the other two overrides", EXIT_USAGE)
        return base, token_url, UPLOAD_HOST_SUFFIXES, False
    listed = tuple(h.strip().lower() for h in (hosts or "").split(",") if h.strip())
    if not listed or any(h not in LOOPBACK_HOSTS for h in listed):
        raise WriterError(f"{ENV_UPLOAD_HOSTS} is for tests only, is set with the other two overrides and lists loopback names such as 127.0.0.1", EXIT_USAGE)
    return base, token_url, listed, True


class Session:
    def __init__(self, client, upload_hosts: tuple, test_mode: bool):
        self.client, self.upload_hosts, self.test_mode = client, upload_hosts, test_mode


def open_session() -> Session:
    base, token_url, hosts, test_mode = endpoints()
    found = converted(msgraph.find_account_record, secret_resolver(), PROFILE, test_mode)
    if not found:
        raise WriterError(f"no Microsoft account authorization: run {PROFILE.auth_command}, or export {PROFILE.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    record = converted(msgraph.parse_account_record, PROFILE, found[0])
    access, rotated = converted(msgraph.refresh_access_token, PROFILE, token_url or msgraph.TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    msgraph.store_rotation(PROFILE, record, rotated, found[1], test_mode, lambda: secret_resolver(), lambda mode: msgraph.keyring_module(PROFILE, mode))
    return Session(msgraph.GraphClient(PROFILE, base, access, test_mode), hosts, test_mode)


# --- one request, through the allow-list -------------------------------------------------------------------------------------------------


def enc(value: str) -> str:
    """An id, a name or a path segment as it enters a path: percent-encoded, nothing kept (the contract of providers/CONTRACT.md for the writers)."""
    return urllib.parse.quote(value, safe="")


def query_string(query: dict) -> str:
    return "&".join(f"{key}={urllib.parse.quote(value, safe=',')}" for key, value in sorted(query.items()))      # the keys are ours ($select, @microsoft...)


def failure(session: Session, status: int, headers, body: bytes, what: str) -> WriterError:
    e = session.client.failure(status, headers, body, what)
    return WriterError(str(e), e.code, e.status)


def send(session: Session, step: dict, body: bytes | None = None, extra: dict | None = None) -> tuple:
    """Send one request of a plan to Graph: (status, headers, at most RESPONSE_LIMIT bytes). Refused unless ALLOWED lists the method and the path (L58)."""
    method, path = step["method"], step["path"]
    common.guarded(ALLOWED, method, path)
    client = session.client
    url = client.base + path + (("?" + query_string(step["query"])) if step.get("query") else "")
    headers = {"Authorization": f"Bearer {client.token}", "Accept": "application/json", "User-Agent": PROFILE.user_agent, **(extra or {})}
    return converted(msgraph.http, method, url, headers, body, RESPONSE_LIMIT, what="Microsoft Graph")


def checked_upload_address(address, session: Session) -> str:
    """The upload address Graph named, when it is one this writer may send bytes to: https (http to a loopback host in test mode), no user or password, the
    default port, and a host of the closed list or a subdomain of one. WriterError otherwise, naming the host and never the rest (it is a bearer credential)."""
    if not isinstance(address, str) or not address or any(not "!" <= ch <= "~" for ch in address):
        raise WriterError("Graph named an upload address with characters an address does not hold: nothing was uploaded")
    try:
        parsed = urllib.parse.urlparse(address)
        host, port = (parsed.hostname or "").lower(), parsed.port
    except ValueError:
        raise WriterError("Graph named an upload address this provider cannot read: nothing was uploaded") from None
    if session.test_mode:
        allowed = parsed.scheme in ("http", "https") and host in session.upload_hosts
    else:
        allowed = (parsed.scheme == "https" and port in (None, 443) and not parsed.username and not parsed.password
                   and any(host == s or host.endswith("." + s) for s in session.upload_hosts))
    if not allowed:
        raise WriterError(f"refusing to upload to {one_line(host, 100) or 'an address without a host'}: it is not an OneDrive upload host "
                          f"({', '.join(UPLOAD_HOST_SUFFIXES)}) or not https: nothing was uploaded")
    return address


def send_upload(session: Session, address: str, data: bytes) -> tuple:
    """The bytes to the upload session, with no Authorization header (the address carries the permission), in one request."""
    common.guarded(ALLOWED, "PUT", UPLOAD_PATH)
    headers = {"Content-Length": str(len(data)), "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}", "User-Agent": PROFILE.user_agent,
               "Accept": "application/json"}
    return converted(msgraph.http, "PUT", address, headers, data, RESPONSE_LIMIT, what="the OneDrive upload host")


def read_json(session: Session, step: dict, what: str) -> dict:
    status, headers, body = send(session, step)
    if status != 200:
        raise failure(session, status, headers, body, what)
    return as_object(body, what)


def as_object(body: bytes, what: str) -> dict:
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if not isinstance(data, dict) or len(body) > RESPONSE_LIMIT:
        raise WriterError(f"Graph answered something this provider does not understand ({what})")
    return data


# --- the checked arguments --------------------------------------------------------------------------------------------------------------


def split_id(value, flag: str = "--id") -> tuple:
    parts = value.split("/") if isinstance(value, str) else []
    if len(parts) != 2 or not all(ID_PART.fullmatch(p) and set(p) != {"."} for p in parts):
        raise WriterError(f"{flag} is \"<drive id>/<item id>\" (letters, digits and ! . _ - in each part)", EXIT_USAGE)
    return parts[0], parts[1]


def check_name(value) -> str:
    """A file name: 1 to 120 characters, letters and digits of any script and ` ._-()`, no leading or trailing space, no trailing dot, no `..`, in the NFC
    form, not starting with a hyphen."""
    if (not isinstance(value, str) or not 1 <= len(value) <= NAME_MAX or value != unicodedata.normalize("NFC", value) or value != value.strip(" ")
            or ".." in value or value.endswith(".") or value.startswith("-") or not any(c.isalnum() for c in value)
            or not all(c.isalnum() or c in NAME_EXTRA for c in value)):
        raise WriterError("--name is 1 to 120 characters: letters, digits, spaces and . _ - ( ), not ending in a dot or starting with a hyphen", EXIT_USAGE)
    return value


def folder_ref(value) -> tuple:
    """(kind, text): ("id", the item id) or ("path", the folder path from the root). The id is the character set of a OneDrive item id; the path is made of
    segments of the character set of a name."""
    if isinstance(value, str) and value.startswith("/"):
        segments = value[1:].split("/") if value != "/" else []
        if not segments or len(value) > 400 or not all(0 < len(s) <= 100 and s != "." and s != ".." and s == s.strip(" ") and not s.endswith(".")
                                                       and all(c.isalnum() or c in NAME_EXTRA for c in s) for s in segments):
            raise WriterError("--folder is a folder path made of names (letters, digits, spaces and . _ - ( )) or a folder item id", EXIT_USAGE)
        return "path", value
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_=!-]{1,200}", value) or set(value) == {"-"}:
        raise WriterError("--folder is a folder item id (letters, digits and _ = ! -) or a folder path that starts with /", EXIT_USAGE)
    return "id", value


def folder_path(ref: tuple) -> str:
    """The path of the folder itself (a GET)."""
    kind, text = ref
    return f"/me/drive/items/{enc(text)}" if kind == "id" else "/me/drive/root:/" + "/".join(enc(s) for s in text[1:].split("/"))


def child_path(ref: tuple, name: str, tail: str = "") -> str:
    """The path of the item called `name` in the folder: `<folder>:/<name>` for an id, and for a path the name is one more segment; `tail` follows (`:/content`)."""
    kind, text = ref
    if kind == "id":
        return f"/me/drive/items/{enc(text)}:/{enc(name)}" + tail
    return "/me/drive/root:/" + "/".join(enc(s) for s in text[1:].split("/")) + f"/{enc(name)}" + tail


def item_path(drive: str, item: str) -> str:
    return f"/drives/{enc(drive)}/items/{enc(item)}"


def check_etag(value, flag: str) -> str:
    if not isinstance(value, str) or not ETAG.fullmatch(value):
        raise WriterError(f"{flag} is the eTag or cTag Graph named", EXIT_USAGE)
    return value


# --- the plans: the exact requests of each verb -------------------------------------------------------------------------------------------


def media(media_type: str, count: int, sha: str) -> dict:
    return {"bytes": count, "content_type": media_type, "sha256": sha}


def plan_create(ref: tuple, name: str, media_type: str, count: int, sha: str) -> list:
    return [
        {"method": "GET", "path": folder_path(ref), "query": {"$select": FOLDER_FIELDS}, "body": None},
        {"method": "PUT", "path": child_path(ref, name, ":/content"), "query": {"@microsoft.graph.conflictBehavior": "fail"},
         "body": {"media": media(media_type, count, sha)}},
    ]


def plan_replace(drive: str, item: str, media_type: str, count: int, sha: str, etag: str) -> list:
    base = item_path(drive, item)
    return [
        {"method": "GET", "path": base, "query": {"$select": ITEM_FIELDS}, "body": None},
        {"method": "POST", "path": base + "/createUploadSession", "query": {}, "if_match": etag,
         "body": {"item": {"@microsoft.graph.conflictBehavior": "replace"}}},
        {"method": "PUT", "path": UPLOAD_PATH, "query": {}, "body": {"content_range": f"bytes 0-{count - 1}/{count}", "media": media(media_type, count, sha)}},
    ]


# --- what the service says an item is ------------------------------------------------------------------------------------------------------


def facet(meta: dict, key: str) -> bool:
    return isinstance(meta.get(key), dict)


def kind_of(meta: dict) -> str:
    for key, word in (("deleted", "deleted"), ("malware", "malware"), ("remoteItem", "shared-from-another-drive"), ("package", "package"),
                      ("folder", "folder"), ("file", "file")):
        if facet(meta, key):
            return word
    return "other"


def described(meta: dict) -> dict:
    kind = kind_of(meta)
    parent = meta.get("parentReference") if isinstance(meta.get("parentReference"), dict) else {}
    drive = parent.get("driveId") if isinstance(parent.get("driveId"), str) and ID_PART.fullmatch(parent["driveId"]) else None
    size = meta.get("size")
    ident = meta.get("id") if isinstance(meta.get("id"), str) and ID_PART.fullmatch(meta["id"]) else None
    mime = meta["file"].get("mimeType") if facet(meta, "file") and isinstance(meta["file"].get("mimeType"), str) else ""
    writable = kind == "file"
    reason = "" if writable else {"deleted": "the item is deleted", "malware": "OneDrive flagged the file as malware",
                                  "shared-from-another-drive": "the item is shared from another drive", "package": "a package (a OneNote notebook) is not a file",
                                  "folder": "a folder is not a file", "other": "the item is not a file"}[kind]
    return {"id": f"{drive}/{ident}" if drive and ident else ident, "name": one_line(meta.get("name"), 200), "etag": str(meta.get("eTag") or ""),
            "ctag": str(meta.get("cTag") or ""), "size": size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None,
            "modified": str(meta.get("lastModifiedDateTime") or ""), "created": str(meta.get("createdDateTime") or ""), "mime_type": mime, "kind": kind,
            "writable": writable, "reason": reason}


def moment(text):
    """A Graph time as an aware datetime, or None."""
    try:
        return datetime.datetime.strptime(re.sub(r"\.\d+", "", str(text)), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def not_before(text, since) -> bool:
    """Whether the Graph time `text` is at or after the time the key was claimed (with a slack for the two clocks)."""
    seen, claimed = moment(text), moment(since)
    return seen is not None and claimed is not None and seen >= claimed - CLOCK_SLACK


def landed(meta: dict, expect: dict) -> dict:
    """The answer to a write, checked against what was sent: an id, the name when it is known, and the size. A difference is `unknown` (the write may have
    landed as something else), never a success."""
    out = described(meta)
    if not out["id"]:
        raise WriterError("Graph's answer to the write holds no item id: the outcome is unknown", EXIT_UNKNOWN)
    if expect.get("name") is not None and out["name"].casefold() != expect["name"].casefold():
        raise WriterError("Graph's answer to the write names another item: the outcome is unknown", EXIT_UNKNOWN)
    if out["size"] is not None and out["size"] != expect["bytes"]:
        raise WriterError("Graph's answer to the write has another size than the content sent: the outcome is unknown", EXIT_UNKNOWN)
    return out


def result_of(meta: dict, replayed: bool, **more) -> dict:
    return {"written": True, "replayed": replayed, "id": meta["id"], "name": meta["name"], "etag": meta["etag"], "ctag": meta["ctag"],
            "bytes": meta["size"], "modified": meta["modified"], **more}


# --- the verbs -------------------------------------------------------------------------------------------------------------------------


def cmd_check(a) -> int:
    base, token_url, _, test_mode = endpoints()
    found = converted(msgraph.find_account_record, secret_resolver(), PROFILE, test_mode)
    if not found:
        raise WriterError(f"no Microsoft account authorization: run {PROFILE.auth_command}, or export {PROFILE.secret} (the JSON record)", EXIT_NOT_CONFIGURED)
    record = converted(msgraph.parse_account_record, PROFILE, found[0])
    _, rotated = converted(msgraph.refresh_access_token, PROFILE, token_url or msgraph.TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    rotation = msgraph.store_rotation(PROFILE, record, rotated, found[1], test_mode, lambda: secret_resolver(),
                                      lambda mode: msgraph.keyring_module(PROFILE, mode))
    return emit({"ok": True, "record": "account", "scope": " ".join(PROFILE.scopes), "account_kind": record.get("account_kind"), "tenant": record["tenant"],
                 "rotation": rotation, "implementation": IMPLEMENTATION})


def cmd_file_meta(a) -> int:
    if (a.id is None) == (a.folder is None):
        raise WriterError("give --id, or --folder with --name", EXIT_USAGE)
    if a.id is not None:
        if a.name is not None:
            raise WriterError("--name goes with --folder", EXIT_USAGE)
        drive, item = split_id(a.id)
        session = open_session()
        meta = read_json(session, {"method": "GET", "path": item_path(drive, item), "query": {"$select": ITEM_FIELDS}}, "driveItem get")
        out = described(meta)
        out["id"] = f"{drive}/{item}"
        return emit(out)
    ref, name = folder_ref(a.folder), check_name(a.name)
    session = open_session()
    folder = read_json(session, {"method": "GET", "path": folder_path(ref), "query": {"$select": FOLDER_FIELDS}}, "driveItem get (folder)")
    if not facet(folder, "folder") or facet(folder, "deleted"):
        raise WriterError("the folder is not a folder of the account, or it is deleted")
    step = {"method": "GET", "path": child_path(ref, name), "query": {"$select": ITEM_FIELDS}}
    status, headers, body = send(session, step)
    if status == 404:
        return emit({"folder": {"name": one_line(folder.get("name"), 200)}, "exists": False, "match": None})
    if status != 200:
        raise failure(session, status, headers, body, "driveItem get (name)")
    found = described(as_object(body, "driveItem get (name)"))
    return emit({"folder": {"name": one_line(folder.get("name"), 200)}, "exists": True, "match": {"id": found["id"], "name": found["name"], "kind": found["kind"]}})


def unknown_after(error: WriterError) -> WriterError:
    """The error of a request that changes the account: a 4xx answer changed nothing; no answer at all, or a server error, may have landed."""
    if error.code == EXIT_NOT_CONFIGURED or (error.status is not None and 300 <= error.status < 500):
        return error
    return WriterError(f"{error} (the outcome is unknown: the request may have landed)", EXIT_UNKNOWN, error.status)


def dry_run(steps: list, key: str) -> int:
    entry = common.Ledger(IMPLEMENTATION).peek(key)
    return emit({"dry_run": True, "requests": steps, "would_sha256": common.would_sha256(steps), "ledger": (entry or {}).get("state", "absent")})


def cmd_create(a) -> int:
    ref, name = folder_ref(a.folder), check_name(a.name)
    media_type, count, sha = common.check_media_type(a.media_type), common.check_count(a.bytes, "--bytes"), common.check_sha256(a.sha256, "--sha256")
    key = common.check_key(a.idempotency_key)
    steps = plan_create(ref, name, media_type, count, sha)
    if a.dry_run:
        return dry_run(steps, key)
    data = common.read_content(a.content_file, count, sha)
    ledger = common.Ledger(IMPLEMENTATION)
    claim = ledger.claim(key, common.would_sha256(steps))
    if claim["state"] == "done":
        return emit({**claim["result"], "replayed": True})
    try:
        session = open_session()
        folder = read_json(session, steps[0], "driveItem get (folder)")
        if not facet(folder, "folder") or facet(folder, "deleted"):
            raise WriterError("the folder is not a folder of the account, or it is deleted: nothing was written")
        try:
            status, headers, answer = send(session, steps[1], data, {"Content-Type": media_type, "Content-Length": str(len(data))})
        except WriterError as e:
            raise unknown_after(e) from None
        if status == 409:       # a file of that name is there: ours when an earlier attempt of this approval made it, else a refusal
            probe = {"method": "GET", "path": child_path(ref, name), "query": {"$select": ITEM_FIELDS}}
            pstatus, pheaders, pbody = send(session, probe)
            present = described(as_object(pbody, "driveItem get (name)")) if pstatus == 200 else None
            if present and claim["state"] == "pending" and present["kind"] == "file" and present["size"] == count and not_before(present["created"], claim["since"]):
                out = result_of(present, True)
                ledger.done(key, out)
                return emit(out)
            raise WriterError(f"a file named {name!r} is already in the folder: create never replaces a file, nothing was written")
        if status not in (200, 201):
            raise unknown_after(failure(session, status, headers, answer, "driveItem put content"))
        try:
            out = result_of(landed(as_object(answer, "driveItem put content"), {"name": name, "bytes": count}), False)
        except WriterError as e:
            raise WriterError(str(e), EXIT_UNKNOWN) from None
    except WriterError as e:
        if e.code != EXIT_UNKNOWN and claim["state"] == "new":      # a key an earlier attempt left pending stays pending: that attempt may have landed
            ledger.release(key)
        raise
    ledger.done(key, out)
    return emit(out)


def cmd_replace(a) -> int:
    drive, item = split_id(a.id)
    media_type, count, sha = common.check_media_type(a.media_type), common.check_count(a.bytes, "--bytes"), common.check_sha256(a.sha256, "--sha256")
    key = common.check_key(a.idempotency_key)
    etag, ctag = check_etag(a.base_etag, "--base-etag"), check_etag(a.base_ctag, "--base-ctag")
    if not a.base_size or not a.base_size.isdigit():
        raise WriterError("--base-size is the size in bytes the runtime read", EXIT_USAGE)
    steps = plan_replace(drive, item, media_type, count, sha, etag)
    if a.dry_run:
        return dry_run(steps, key)
    data = common.read_content(a.content_file, count, sha)
    ledger = common.Ledger(IMPLEMENTATION)
    claim = ledger.claim(key, common.would_sha256(steps))
    if claim["state"] == "done":
        return emit({**claim["result"], "replayed": True})
    try:
        session = open_session()
        current = described(read_json(session, steps[0], "driveItem get"))
        if not current["writable"]:
            raise WriterError(f"changed: the item is no longer a file this provider writes ({current['reason']}): nothing was written")
        moved = [field for field, now, then in (("eTag", current["etag"], etag), ("cTag", current["ctag"], ctag), ("size", str(current["size"]), a.base_size))
                 if now != then]
        if moved:
            if claim["state"] == "pending" and current["size"] == count and not_before(current["modified"], claim["since"]):
                out = result_of(current, True)          # the earlier attempt of this approval landed and its answer was lost
                ledger.done(key, out)
                return emit(out)
            raise WriterError("changed: the file is not the one the runtime read (" + ", ".join(moved) + "): nothing was written")
        status, headers, answer = send(session, steps[1], json.dumps(steps[1]["body"]).encode("ascii"),
                                       {"Content-Type": "application/json", "If-Match": etag})
        if status == 412:
            raise WriterError("changed: the file moved after the runtime read it (Graph answered 412 to the upload session): nothing was written")
        if status != 200:
            raise failure(session, status, headers, answer, "createUploadSession")
        address = checked_upload_address(as_object(answer, "createUploadSession").get("uploadUrl"), session)
        try:
            status, headers, answer = send_upload(session, address, data)
        except WriterError as e:
            raise unknown_after(e) from None
        if status not in (200, 201):
            raise unknown_after(failure(session, status, headers, answer, "upload"))
        try:
            out = result_of(landed(as_object(answer, "upload"), {"name": None, "bytes": count}), False)
        except WriterError as e:
            raise WriterError(str(e), EXIT_UNKNOWN) from None
    except WriterError as e:
        if e.code != EXIT_UNKNOWN and claim["state"] == "new":      # a key an earlier attempt left pending stays pending: that attempt may have landed
            ledger.release(key)
        raise
    ledger.done(key, out)
    return emit(out)


# --- the command line --------------------------------------------------------------------------------------------------------------------


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise WriterError(message, EXIT_USAGE)


def build_parser() -> Parser:
    p = Parser(prog="onedrive.py", add_help=False)
    p.add_argument("verb", nargs="?", choices=["file-meta", "create", "replace"])
    p.add_argument("--check", action="store_true")
    for flag in ("id", "folder", "name", "media-type", "content-file", "bytes", "sha256", "idempotency-key", "base-etag", "base-ctag", "base-size"):
        p.add_argument("--" + flag)
    for flag in ("dry-run", "confirmed"):
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
        if a.verb in ("create", "replace"):
            if a.dry_run == a.confirmed:
                raise WriterError("give exactly one of --dry-run and --confirmed", EXIT_USAGE)
            if not a.content_file and not a.dry_run:
                raise WriterError("--content-file is required with --confirmed", EXIT_USAGE)
            for flag in ("media_type", "bytes", "sha256", "idempotency_key"):
                if getattr(a, flag) is None:
                    raise WriterError(f"--{flag.replace('_', '-')} is required", EXIT_USAGE)
        return {"file-meta": cmd_file_meta, "create": cmd_create, "replace": cmd_replace}[a.verb](a)
    except WriterError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
