#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Documents provider on OneDrive: an implementation of the class integration:documents that serves the files a person chose as
SOURCES of a project (runtime/sources.py), read only.

It reads files of the person's own OneDrive, never folders, packages, items shared from another drive, items flagged as malware
or deleted ones. The OAuth scope is the delegated Microsoft Graph permission `Files.Read` (and `offline_access`, for the refresh
token) and nothing else. Microsoft has no scope that is granted per chosen file, so `Files.Read` lets the token READ EVERY FILE of
the person's own OneDrive, not only the chosen ones, and it writes nothing. Narrowing to the chosen files is this runtime's: only
registered item ids are read and no verb lists a folder for a run. Say so to anyone who asks what the token can do.

The provider never parses a file: it writes the bytes to `--out-dir` and prints their description, and the runtime hands them to
the converter (a container with no network) like any other source (limit L27). Nothing here writes to OneDrive: `write`, `notice`,
`resolve` and `comments` answer "not supported" (exit 2). Only GET requests are sent to Graph; the token endpoint is the one POST.

Usage:
  uv run providers/documents/onedrive.py --help
  uv run providers/documents/onedrive.py --check
  uv run providers/documents/onedrive.py stat --id <drive id>/<item id> --as-source
  uv run providers/documents/onedrive.py read --id <drive id>/<item id> --as-source --out-dir <folder> [--max-bytes <n>]
  uv run providers/documents/onedrive.py search --query <text> [--top <n, at most 25>]
  uv run providers/documents/onedrive.py children --path <folder path in OneDrive> [--top <n, at most 200>]

  --check     refreshes the access token (the one network call) and checks that it carries Files.Read and nothing wider; prints
              {"ok": true, "scope", "account_kind", "tenant", "obtained_at", "rotation"}. Exit 3 when there is no authorization or it
              was refused (an expired or revoked one, a work tenant whose admin has not approved the app, a token with a wider scope).
  stat        the item's name, type, size and `version`, and whether it can be read as a source (`supported`, with the `reason`
              when not). `version` is the item's cTag, which changes when the CONTENT changes and not when only metadata does; the
              eTag is printed as `etag`. One metadata call, no content.
  read        the file's bytes into <out-dir>/content (a folder that exists, no link; a new file, mode 0600), and {"id", "name",
              "mime_type", "version", "etag", "content", "exported_as", "bytes", "sha256", "file", "as_source"}. `content` is always
              "file" (OneDrive holds the file as it is; the runtime sniffs its type from the bytes). --max-bytes bounds the content
              (default 25 MiB, the intake's cap; at most 256 MiB). The size Graph reports is checked before the bytes are asked for;
              after the download the item is read again and a changed cTag refuses ("the file changed while it was read").
  search      for the person's terminal: up to 25 items of the person's OneDrive whose name or content matches the text, each with
              {"id" ("<drive id>/<item id>"), "name", "kind", "path", "size", "modified", "supported", "reason"}. It registers nothing.
  children    for the person's terminal: the items of one folder (a path from the root of the OneDrive; "/" is the root), in the same
              shape. Names, paths and search results are another person's text in principle: they are cleaned to one line and shown,
              never used as a path or run.
  stat and read take --as-source, as the Notion and Drive providers' do, so that the verbs of a later write-back keep their own flags.

What `read` refuses (a closed list of reasons; `stat` describes the item and says `supported: false`): a folder; a package (a
OneNote notebook); an item shared from another drive (`remoteItem`: outside `Files.Read`); an item with a `malware` or a `deleted`
facet; a legacy Office file (.doc, .xls, .ppt: save it as .docx, .xlsx or .pptx). Every other file is downloaded as it is.

The download: Graph answers `/content` with a 302 to a preauthenticated URL that needs no Authorization header and may expire in
minutes. The provider reads the Location, requires https and a host of the closed list (files.1drv.com, sharepoint.com, and their
subdomains), sends the request with NO Authorization header and no cookie, follows no further redirect and reads at most
--max-bytes + 1. The URL is a bearer credential: it is never printed, logged or stored (an error names its host only).

Credentials (never from a flag or a file; contracts/secrets.md):
  ONEDRIVE_SOURCES_TOKEN  one JSON record, read through providers/secrets/resolver.py (the environment, then the credentials
                          directory, then the OS secret store, username onedrive-sources): {"refresh_token", "client_id", "tenant",
                          "scope", "account_kind", "obtained_at"}, written by providers/documents/onedrive_auth.py after the person's
                          consent. There is no client secret: the app is a public client. Printed nowhere.
  Microsoft replaces the refresh token on every use. When the record was found in the OS secret store, this provider writes the
  new refresh token back to that one record (the one exception to "a provider never writes the store", contracts/secrets.md rule
  1); when the write fails it carries on with the old token and says so on stderr. A record found in the environment or in the
  credentials directory is never rewritten: it ages 90 days from the consent.
Test overrides (tests only, loopback URLs only, all three set together; the secret store is then never read or written):
  INTEGRATION_DOCUMENTS_ONEDRIVE_API_BASE        replaces https://graph.microsoft.com/v1.0
  INTEGRATION_DOCUMENTS_ONEDRIVE_TOKEN_URL       replaces https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token
  INTEGRATION_DOCUMENTS_ONEDRIVE_DOWNLOAD_HOSTS  replaces the list of download hosts (comma-separated loopback names)

No redirect is followed with a credential. A verb never retries: a 429 or 503 is reported with its Retry-After. Prints one JSON
object on stdout; diagnostics on stderr. Exit codes: 0 ok, 1 failed (Graph answered an error or could not be reached; an item that
is not found or not read), 2 usage (a missing or bad flag, a verb that is not supported), 3 not configured (no authorization, one
that expired or was revoked, a rejected app registration, a tenant that needs its admin's approval, a token with a scope wider
than Files.Read).
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

DEFAULT_API_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
DOWNLOAD_HOST_SUFFIXES = ("files.1drv.com", "sharepoint.com")   # to verify live; README "OneDrive" says what was seen
SOURCES_ONLY = True   # the contract tests of the class (providers/documents/tests) skip the write verbs for this implementation
SCOPE = "Files.Read"                                              # the one scope: onedrive_auth.py asks for it and this file requires it
SCOPE_PREFIX = "https://graph.microsoft.com/"
REFRESH_SCOPE = f"{SCOPE_PREFIX}{SCOPE} offline_access"          # what the authorization and every refresh name
IGNORED_SCOPES = ("offline_access", "openid", "profile", "email")   # reported next to Files.Read and grant no access to a file
SECRET = "ONEDRIVE_SOURCES_TOKEN"
KEYRING_SERVICE = "openhora"
KEYRING_USERNAME = "onedrive-sources"
AUTH_COMMAND = "uv run providers/documents/onedrive_auth.py authorize"
ENV_BASE = "INTEGRATION_DOCUMENTS_ONEDRIVE_API_BASE"
ENV_TOKEN_URL = "INTEGRATION_DOCUMENTS_ONEDRIVE_TOKEN_URL"
ENV_DOWNLOAD_HOSTS = "INTEGRATION_DOCUMENTS_ONEDRIVE_DOWNLOAD_HOSTS"
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
HTTP_TIMEOUT_SECONDS = 60
DEFAULT_MAX_BYTES = 25 * 1024 * 1024    # runtime/sources.py ORIGINAL_CAP: what the intake takes
HARD_MAX_BYTES = 256 * 1024 * 1024      # no --max-bytes goes past this
SEARCH_TOP_MAX, CHILDREN_TOP_MAX, LIST_TOP_DEFAULT = 25, 200, 25
ITEM_FIELDS = ("id,name,size,cTag,eTag,file,folder,package,remoteItem,malware,deleted,parentReference,lastModifiedDateTime")
ID_PART = re.compile(r"[A-Za-z0-9!._-]{1,200}")     # a personal item id holds "!" ("0123ABCD!101")
TENANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,99}")   # common, organizations, consumers, a tenant id or a verified domain
OUT_NAME = "content"
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
LEGACY_EXTENSIONS = (".doc", ".xls", ".ppt")
LEGACY_TYPES = ("application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint")
CONSENT_CODES = ("AADSTS65001", "AADSTS90094", "AADSTS65004")   # "not consented" / "admin consent required" (to verify live)
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


def one_line(text, limit: int = 300) -> str:
    return " ".join(str(text or "").split())[:limit]


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(obj: dict) -> int:
    print(json.dumps(obj))
    return EXIT_OK


# --- configuration ---------------------------------------------------------------------------------------------------------


def endpoints() -> tuple[str, str | None, tuple, bool]:
    """(API base, token URL or None for the tenant's own, download hosts, test mode). The overrides are for tests, must name loopback
    addresses only and are set all together; in test mode the secret store is never read or written."""
    api, token, hosts = os.environ.get(ENV_BASE), os.environ.get(ENV_TOKEN_URL), os.environ.get(ENV_DOWNLOAD_HOSTS)
    if not api and not token and not hosts:
        return DEFAULT_API_BASE, None, DOWNLOAD_HOST_SUFFIXES, False
    if not (api and token and hosts):
        raise ProviderError(f"{ENV_BASE}, {ENV_TOKEN_URL} and {ENV_DOWNLOAD_HOSTS} are for tests only and are set together", EXIT_USAGE)
    for name, value in ((ENV_BASE, api), (ENV_TOKEN_URL, token)):
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
            raise ProviderError(f"{name} is for tests only and must be a loopback URL such as http://127.0.0.1:8080", EXIT_USAGE)
    names = tuple(h.strip().lower() for h in hosts.split(",") if h.strip())
    if not names or any(h not in LOOPBACK_HOSTS for h in names):
        raise ProviderError(f"{ENV_DOWNLOAD_HOSTS} is for tests only and must list loopback names such as 127.0.0.1", EXIT_USAGE)
    return api.rstrip("/"), token, names, True


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


def keyring_module(test_mode: bool):
    """The OS secret store. Test mode never touches it: tests replace this function with a fake store. Used to write: the rotated
    refresh token here, the record of an authorization in onedrive_auth.py."""
    if test_mode:
        raise ProviderError("test mode (the INTEGRATION_DOCUMENTS_ONEDRIVE_* overrides) never uses the OS secret store", EXIT_USAGE)
    try:
        import keyring
    except ImportError:
        raise ProviderError("the keyring package is missing; run with: uv run providers/documents/onedrive.py", EXIT_NOT_CONFIGURED) from None
    return keyring


def bad_text(value) -> bool:
    return not isinstance(value, str) or not value or any(ch.isspace() or not ch.isprintable() for ch in value)


def parse_record(text: str) -> dict:
    """The authorization record from its JSON text; ProviderError (not configured) when it is unreadable or lacks what a refresh needs.
    A record without a tenant is read as `common`."""
    try:
        record = json.loads(text)
    except ValueError:
        record = None
    if not isinstance(record, dict) or bad_text(record.get("refresh_token")) or bad_text(record.get("client_id")):
        raise ProviderError(f"the stored OneDrive authorization is unreadable or incomplete; run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    tenant = record.get("tenant") or "common"
    if not isinstance(tenant, str) or not TENANT.fullmatch(tenant):
        raise ProviderError(f"the OneDrive authorization holds a tenant that is not a tenant name; run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    return {**record, "tenant": tenant}


def load_record(test_mode: bool) -> tuple[dict, str]:
    """(record, where it was found): "environment", "credentials directory" or "secret store"."""
    found = secret_resolver().resolve(SECRET, allow_store=not test_mode)
    if not found:
        raise ProviderError(f"no OneDrive authorization: run {AUTH_COMMAND}, or export {SECRET} (the JSON record)", EXIT_NOT_CONFIGURED)
    return parse_record(found[0]), found[1]


# --- HTTP ------------------------------------------------------------------------------------------------------------------


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: a 3xx comes back as an answer, and each caller decides what it means (a refusal for every request that
    carries a credential, the Location of /content to be checked for the download)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def http(method: str, url: str, headers: dict, body: bytes | None = None, limit: int = 1024 * 1024, *, what: str) -> tuple[int, object, bytes]:
    """One request; (status, headers, at most limit + 1 bytes of the body) for any HTTP answer, ProviderError otherwise. `what` names the
    request in an error (never the URL: the download address is a credential)."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with OPENER.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, response.headers, response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.headers, exc.read(65536)
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach {what}: {one_line(exc.reason, 120)}") from None
    except TimeoutError:
        raise ProviderError(f"{what} timed out after {HTTP_TIMEOUT_SECONDS} s") from None
    except OSError as exc:
        raise ProviderError(f"the connection to {what} failed: {type(exc).__name__}") from None


def token_request(token_url: str, form: dict) -> dict:
    """POST to the token endpoint, mapping OAuth errors to exit codes. Shared with onedrive_auth.py."""
    status, _, body = http("POST", token_url, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                           urllib.parse.urlencode(form).encode(), what="the Microsoft token endpoint")
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    if status == 200 and isinstance(data, dict) and data.get("access_token"):
        return data
    error = one_line(data.get("error"), 80) if isinstance(data, dict) else ""
    description = one_line(data.get("error_description"), 200) if isinstance(data, dict) else ""
    detail = f"{error}: {description}" if description else error or "no error code"
    if consent_blocked(error, description):
        raise ProviderError(f"Microsoft needs a consent this account has not given ({detail}): your Microsoft 365 admin must approve the app. "
                            f"Ask them, then run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
    if error == "invalid_grant":
        if form.get("grant_type") == "refresh_token":
            raise ProviderError(f"Microsoft refused the refresh token ({detail}): the authorization expired (90 days unused), was revoked, "
                                f"or the password changed. Run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
        raise ProviderError(f"Microsoft refused the authorization code ({detail}); run it again", EXIT_SERVICE, status)
    if error in ("invalid_client", "unauthorized_client", "invalid_request") and "AADSTS" in description:
        raise ProviderError(f"Microsoft rejected the app registration ({detail}): check the Application (client) ID, that the redirect URI "
                            "http://localhost is on the \"Mobile and desktop applications\" platform, and that no client secret is needed",
                            EXIT_NOT_CONFIGURED, status)
    if status == 200:
        raise ProviderError("the token response has no access_token", EXIT_SERVICE, status)
    raise ProviderError(f"the Microsoft token endpoint returned {status} ({detail})", EXIT_SERVICE, status)


def consent_blocked(error: str, description: str) -> bool:
    """Whether an OAuth error means the account (or its tenant's admin) has not allowed the app: asked in the person's words."""
    return error in ("consent_required", "interaction_required") or any(code in description for code in CONSENT_CODES)


def scopes_of(granted) -> set:
    """The scopes of a token response, the Graph prefix removed and compared without case; the ones that grant no file access ignored."""
    names = set()
    for word in str(granted or "").split():
        word = word[len(SCOPE_PREFIX):] if word.lower().startswith(SCOPE_PREFIX) else word
        if word.lower() not in IGNORED_SCOPES:
            names.add(word)
    return names


def check_scope(granted) -> str:
    """Refuse a token whose reported scope is anything but Files.Read (plus the scopes that grant no file access): a wider scope than
    this app asks for is a setup error to fix (a permission left on the registration), not a token to use, and a response that reports no
    scope cannot be shown to be the narrow one. Returns SCOPE."""
    names = scopes_of(granted)
    if {n.lower() for n in names} != {SCOPE.lower()}:
        extra = ", ".join(sorted(n for n in names if n.lower() != SCOPE.lower())) or "none"
        raise ProviderError(f"the token reports {', '.join(sorted(names)) or 'no scope'} where exactly {SCOPE} is wanted (extra: {extra}): "
                            "nothing was read. Remove the other permissions from the app registration (API permissions), revoke the app's "
                            f"access in your Microsoft account, and run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED)
    return SCOPE


def refresh_access_token(token_url: str, record: dict) -> tuple[str, str | None]:
    """(a new access token held in memory for this process, the refresh token Microsoft issued with it or None); checks the scope. The
    request names its scope so that the access token is no wider than asked, and sends no client secret: the app is a public client."""
    data = token_request(token_url, {"client_id": record["client_id"], "grant_type": "refresh_token", "refresh_token": record["refresh_token"],
                                     "scope": REFRESH_SCOPE})
    check_scope(data.get("scope"))
    rotated = data.get("refresh_token")
    return data["access_token"], rotated if isinstance(rotated, str) and not bad_text(rotated) else None


def store_rotation(record: dict, rotated: str | None, where: str, test_mode: bool) -> str:
    """Microsoft replaces the refresh token on every use (the old one stays valid until it expires). When the record was found in the OS
    secret store, write the new token into that one record; when the write fails, carry on with the old token and say so. Returns what
    happened: "stored", "not rotated", "not stored (<why>)"."""
    if not rotated or rotated == record["refresh_token"]:
        return "not rotated"
    if test_mode or where != "secret store":
        return "not stored: the record comes from the environment or the credentials directory"
    try:
        keyring_module(test_mode).set_password(KEYRING_SERVICE, KEYRING_USERNAME, json.dumps({**record, "refresh_token": rotated}))
    except Exception as exc:   # a locked or missing store, headless: the old token still works until it expires
        log(f"warning: Microsoft issued a new refresh token and it could not be stored ({type(exc).__name__}); carrying on with the old one, "
            f"which works until it expires. If a later call is refused, run: {AUTH_COMMAND}")
        return f"not stored ({type(exc).__name__})"
    return "stored"


class Graph:
    """Microsoft Graph as this provider uses it: GET requests with one access token, to one base address."""

    def __init__(self, base: str, access_token: str, hosts: tuple, test_mode: bool):
        self.base, self.token, self.hosts, self.test_mode = base, access_token, hosts, test_mode

    def get(self, path: str, params: dict | None, limit: int = 1024 * 1024) -> tuple[int, object, bytes]:
        query = "&".join(f"{key}={urllib.parse.quote(value, safe=',')}" for key, value in (params or {}).items())   # the keys are ours ($select, $top)
        url = self.base + path + ("?" + query if query else "")
        return http("GET", url, {"Authorization": f"Bearer {self.token}", "Accept": "application/json", "User-Agent": "openhora-documents-onedrive"},
                    limit=limit, what="Microsoft Graph")

    def json(self, path: str, params: dict | None, what: str) -> dict:
        status, headers, body = self.get(path, params)
        if status != 200:
            raise self.failure(status, headers, body, what)
        try:
            data = json.loads(body)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise ProviderError("Graph answered something this provider does not understand")
        return data

    def failure(self, status: int, headers, body: bytes, what: str) -> ProviderError:
        code, message = "", ""
        try:
            error = json.loads(body).get("error")
            if isinstance(error, dict):
                code, message = one_line(error.get("code"), 60), one_line(error.get("message"), 200)
        except (ValueError, AttributeError):
            pass
        detail = f": {message}{f' [{code}]' if code else ''}" if message or code else ""
        if status in REDIRECT_STATUSES:
            return ProviderError(f"refusing to follow a {status} redirect on {what}; the request carries a credential", EXIT_SERVICE, status)
        if status == 401:
            return ProviderError(f"Graph rejected the access token ({what}){detail}; run: {AUTH_COMMAND}", EXIT_NOT_CONFIGURED, status)
        if status == 404:
            return ProviderError(f"OneDrive does not know the item, or it is not in the person's own OneDrive ({what}){detail}", EXIT_SERVICE, status)
        if status in (429, 503):
            wait = str((headers.get("Retry-After") if headers is not None else "") or "").strip()
            after = f"; retry after {wait} seconds" if wait.isdigit() else "; try again later"
            return ProviderError(f"Graph is busy or limiting requests ({status} on {what}){after}{detail}", EXIT_SERVICE, status)
        if status == 403:
            return ProviderError(f"Graph refused the request ({what}){detail}; check that the app has Files.Read and that the item is the person's own",
                                 EXIT_SERVICE, status)
        return ProviderError(f"Graph returned {status} ({what}){detail}", EXIT_SERVICE, status)

    def meta(self, drive: str, item: str) -> dict:
        data = self.json(item_path(drive, item), {"$select": ITEM_FIELDS}, "driveItem get")
        if not isinstance(data.get("id"), str) or data["id"].lower() != item.lower():
            raise ProviderError("Graph answered an item description this provider does not understand")
        return data

    def content_location(self, drive: str, item: str) -> str:
        """The preauthenticated download address Graph answers /content with, a bearer credential: returned, never printed."""
        status, headers, body = self.get(item_path(drive, item) + "/content", None, 65536)
        if status == 200:
            raise ProviderError("Graph answered the content request with the bytes and not the redirect this provider expects")
        if status not in REDIRECT_STATUSES:
            raise self.failure(status, headers, body, "driveItem content")
        location = headers.get("Location") if headers is not None else None
        if not isinstance(location, str) or not location:
            raise ProviderError("Graph answered the content request with a redirect that has no Location")
        return location


def open_graph() -> Graph:
    base, token_url, hosts, test_mode = endpoints()
    record, where = load_record(test_mode)
    access, rotated = refresh_access_token(token_url or TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    store_rotation(record, rotated, where, test_mode)
    return Graph(base, access, hosts, test_mode)


# --- the verbs -------------------------------------------------------------------------------------------------------------


def split_id(value) -> tuple[str, str]:
    """(drive id, item id) from "<drive id>/<item id>". Neither part is empty, only dots, or outside the characters an id holds."""
    parts = value.split("/") if isinstance(value, str) else []
    if len(parts) != 2 or not all(ID_PART.fullmatch(p) and set(p) != {"."} for p in parts):
        raise ProviderError("--id is \"<drive id>/<item id>\" (letters, digits and ! . _ - in each part)", EXIT_USAGE)
    return parts[0], parts[1]


def item_path(drive: str, item: str) -> str:
    return f"/drives/{urllib.parse.quote(drive, safe='!')}/items/{urllib.parse.quote(item, safe='!')}"


def facet_kind(meta: dict) -> str:
    """One word for what the item is: deleted, malware, shared-from-another-drive, package, folder, file or other."""
    for facet, word in (("deleted", "deleted"), ("malware", "malware"), ("remoteItem", "shared-from-another-drive"), ("package", "package"),
                        ("folder", "folder"), ("file", "file")):
        if facet in meta and meta[facet] is not None:
            return word
    return "other"


REFUSED = {
    "deleted": "the item is deleted",
    "malware": "OneDrive flagged the file as malware",
    "shared-from-another-drive": "the item is shared from another drive: outside Files.Read, which reads the person's own OneDrive",
    "package": "a package (a OneNote notebook) is not a source",
    "folder": "a folder is not a source: choose the files in it",
    "other": "the item is not a file",
}


def reading_plan(meta: dict) -> tuple[bool, str]:
    """(supported, reason): whether the item is read as a source, and why not when it is not."""
    kind = facet_kind(meta)
    if kind in REFUSED:
        return False, REFUSED[kind]
    name = str(meta.get("name") or "").lower()
    mime = str((meta.get("file") or {}).get("mimeType") or "").lower()
    if name.endswith(LEGACY_EXTENSIONS) or mime in LEGACY_TYPES:
        return False, "a legacy Office file (.doc, .xls, .ppt) is not read: save it as .docx, .xlsx or .pptx"
    return True, ""


def version_of(meta: dict) -> str:
    """The version token: the cTag, which changes when the content changes and not when only the metadata does."""
    return str(meta.get("cTag") or "")


def size_of(meta: dict):
    size = meta.get("size")
    return size if isinstance(size, int) and not isinstance(size, bool) and size >= 0 else None


def described(meta: dict, drive: str, item: str) -> dict:
    supported, reason = reading_plan(meta)
    out = {"id": f"{drive}/{item}", "name": one_line(meta.get("name"), 200), "mime_type": str((meta.get("file") or {}).get("mimeType") or ""),
           "version": version_of(meta), "etag": str(meta.get("eTag") or ""), "archived": facet_kind(meta) == "deleted",
           "supported": supported, "reason": reason}
    out["size"] = size_of(meta)
    return out


def cmd_check(args: dict) -> int:
    _, token_url, _, test_mode = endpoints()
    record, where = load_record(test_mode)
    _, rotated = refresh_access_token(token_url or TOKEN_URL_TEMPLATE.format(tenant=record["tenant"]), record)
    return emit({"ok": True, "scope": SCOPE, "account_kind": record.get("account_kind"), "tenant": record["tenant"],
                 "obtained_at": record.get("obtained_at"), "rotation": store_rotation(record, rotated, where, test_mode)})


def cmd_stat(args: dict) -> int:
    drive, item = split_id(args.get("--id"))
    return emit(described(open_graph().meta(drive, item), drive, item))


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


def checked_location(location: str, hosts: tuple, test_mode: bool) -> str:
    """The download address, when it is one this provider may fetch: https (http only to a loopback host in test mode), no user or
    password in it, the default port, and a host of the closed list or one of its subdomains. ProviderError otherwise, naming the host
    and never the rest of the address."""
    try:
        parsed = urllib.parse.urlparse(location)
        host, port = (parsed.hostname or "").lower(), parsed.port
    except ValueError:
        raise ProviderError("Graph named a download address this provider cannot read; nothing was fetched") from None
    if test_mode:
        allowed = parsed.scheme in ("http", "https") and host in hosts
    else:
        allowed = (parsed.scheme == "https" and port in (None, 443) and not parsed.username and not parsed.password
                   and any(host == s or host.endswith("." + s) for s in hosts))
    if not allowed:
        raise ProviderError(f"refusing to download from {one_line(host, 100) or 'an address without a host'}: it is not a OneDrive download host "
                            f"({', '.join(hosts)}) or not https; nothing was fetched")
    return location


def fetch_download(url: str, limit: int) -> bytes:
    """GET the preauthenticated address with NO Authorization header and no cookie (this opener has no cookie handler), follow no
    redirect, read at most limit + 1 bytes. Nothing in an error holds the address."""
    status, _, body = http("GET", url, {"Accept": "*/*", "User-Agent": "openhora-documents-onedrive"}, limit=limit, what="the OneDrive download host")
    if status in REDIRECT_STATUSES:
        raise ProviderError(f"the download host answered a {status} redirect; not followed")
    if status != 200:
        raise ProviderError(f"the download host answered {status}; the address may have expired: read the item again")
    if len(body) > limit:
        raise ProviderError(f"the file is over the {limit} bytes that one source may be: send the part you need")
    return body


def cmd_read(args: dict) -> int:
    drive, item = split_id(args.get("--id"))
    folder = out_folder(args.get("--out-dir"))
    limit = max_bytes_of(args)
    graph = open_graph()
    meta = graph.meta(drive, item)
    supported, reason = reading_plan(meta)
    if not supported:
        raise ProviderError(reason)
    version, size = version_of(meta), size_of(meta)
    if not version:
        raise ProviderError("Graph answered an item without a cTag, so a change of it cannot be told; nothing was read")
    if size is not None and size > limit:
        raise ProviderError(f"the file is {size} bytes, over the {limit} that one source may be: send the part you need")
    url = checked_location(graph.content_location(drive, item), graph.hosts, graph.test_mode)
    data = fetch_download(url, limit)
    again = graph.meta(drive, item)   # the item as it is after the bytes arrived
    if version_of(again) != version or (size is not None and len(data) != size):
        raise ProviderError("the file changed while it was read: read it again")
    try:
        write_new(folder, OUT_NAME, data)
    except OSError as exc:
        raise ProviderError(f"the content cannot be written in --out-dir: {exc.strerror}", EXIT_SERVICE) from None
    return emit({"id": f"{drive}/{item}", "name": one_line(meta.get("name"), 200), "mime_type": str((meta.get("file") or {}).get("mimeType") or ""),
                 "version": version, "etag": str(meta.get("eTag") or ""), "content": "file", "exported_as": None, "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(), "file": OUT_NAME, "as_source": True})


def top_of(args: dict, ceiling: int) -> int:
    raw = args.get("--top")
    if raw is None:
        return min(LIST_TOP_DEFAULT, ceiling)
    if not str(raw).isdigit() or not 1 <= int(raw) <= ceiling:
        raise ProviderError(f"--top is a whole number from 1 to {ceiling}", EXIT_USAGE)
    return int(raw)


def folder_of(meta: dict) -> str:
    """The folder path of an item, from its parentReference ("/drive/root:/Documents/Reports" -> "/Documents/Reports"), on one line."""
    path = str((meta.get("parentReference") or {}).get("path") or "")
    return one_line(path.split(":", 1)[1] if ":" in path else "", 300) or "/"


def listing(graph: Graph, path: str, top: int, what: str) -> int:
    data = graph.json(path, {"$top": str(top), "$select": ITEM_FIELDS}, what)
    entries = data.get("value")
    if not isinstance(entries, list):
        raise ProviderError("Graph answered a list this provider does not understand")
    items = []
    for meta in entries[:top]:
        drive = (meta.get("parentReference") or {}).get("driveId") if isinstance(meta, dict) else None
        if not isinstance(drive, str) or not ID_PART.fullmatch(drive) or not isinstance(meta.get("id"), str) or not ID_PART.fullmatch(meta["id"]):
            continue
        supported, reason = reading_plan(meta)
        items.append({"id": f"{drive}/{meta['id']}", "name": one_line(meta.get("name"), 200), "kind": facet_kind(meta), "path": folder_of(meta),
                      "size": size_of(meta), "modified": one_line(meta.get("lastModifiedDateTime"), 40), "supported": supported, "reason": reason})
    return emit({"items": items, "count": len(items), "truncated": "@odata.nextLink" in data or len(entries) > top})


def cmd_search(args: dict) -> int:
    text = " ".join(str(args.get("--query") or "").split())
    if not text or len(text) > 200 or any(not ch.isprintable() for ch in text):
        raise ProviderError("--query is 1 to 200 printable characters", EXIT_USAGE)
    top = top_of(args, SEARCH_TOP_MAX)
    quoted = urllib.parse.quote(text.replace("'", "''"), safe="")
    return listing(open_graph(), f"/me/drive/root/search(q='{quoted}')", top, "drive search")


def folder_route(value) -> str:
    """The Graph path of the children of a folder named by its path in OneDrive. No `..`, no empty or dotted segment, none of the
    characters OneDrive does not allow in a name (and the colon that delimits a path in the address)."""
    raw = str(value or "").strip().strip("/")
    if raw == "":
        return "/me/drive/root/children"
    segments = raw.split("/")
    if len(raw) > 400 or any(s in ("", ".", "..") or any(ch in '\\:*?"<>|' or not ch.isprintable() for ch in s) for s in segments):
        raise ProviderError("--path is a folder path from the root of the OneDrive, such as /Documents/Reports (no .., no empty part, none "
                            "of \\ : * ? \" < > |)", EXIT_USAGE)
    return f"/me/drive/root:/{urllib.parse.quote('/'.join(segments), safe='/')}:/children"


def cmd_children(args: dict) -> int:
    route, top = folder_route(args.get("--path")), top_of(args, CHILDREN_TOP_MAX)
    return listing(open_graph(), route, top, "folder children")


def cmd_unsupported(args: dict) -> int:
    raise ProviderError("this verb is not supported by the OneDrive provider: it reads the files a person chose as sources and writes "
                        "nothing to OneDrive", EXIT_USAGE)


VERBS = {"stat": cmd_stat, "read": cmd_read, "search": cmd_search, "children": cmd_children, "comments": cmd_unsupported,
         "write": cmd_unsupported, "notice": cmd_unsupported, "resolve": cmd_unsupported}
FLAGS_OF = {"stat": ("--id", "--as-source"), "read": ("--id", "--as-source", "--out-dir", "--max-bytes"), "search": ("--query", "--top"),
            "children": ("--path", "--top")}
VALUE_FLAGS = ("--id", "--out-dir", "--max-bytes", "--query", "--top", "--config-file", "--path", "--markdown-file", "--idempotency-key",
               "--notice", "--text", "--parent")
SWITCHES = ("--check", "--as-source", "--dry-run", "--confirmed", "--not-created")


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
        if verb in FLAGS_OF:
            for flag in args:
                if flag not in FLAGS_OF[verb]:
                    raise ProviderError(f"{flag} is not a flag of {verb}", EXIT_USAGE)
            if verb in ("stat", "read") and not args.get("--as-source"):
                raise ProviderError("the OneDrive provider serves sources only: give --as-source", EXIT_USAGE)
        elif args.get("--as-source"):
            raise ProviderError("--as-source is for the verbs stat and read only", EXIT_USAGE)
        return VERBS[verb](args)
    except ProviderError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code


if __name__ == "__main__":
    sys.exit(main())
