#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Publisher provider for LinkedIn: publish a post, and comment on it, as the authenticated member.

Sources (official LinkedIn documentation, all accessed 2026-09-26):
- Posts API (request body, 201 + x-restli-id response, w_member_social):
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-09
- Images API (initializeUpload request and response, value.uploadUrl, value.image):
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api?view=li-lms-2026-09
- Image byte upload (PUT to uploadUrl with the OAuth token in Authorization), linked from the Images API page:
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/vector-asset-api?view=li-lms-2026-09#upload-the-image
- little Text Format (reserved characters, backslash escaping, the HashtagTemplate
  {hashtag|\\#|MyTestTag} of its Posts API example) used by the commentary field:
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format?view=li-lms-2026-09
- Comments API (accessed 2026-09-29): POST /rest/socialActions/{shareUrn|ugcPostUrn|commentUrn}/comments,
  body actor/object/message.text, parentComment for a nested reply, x-restli-id and commentUrn in the
  answer, comment URN urn:li:comment:(<thread urn>,<id>), 429 "Comment create throttled". The comment
  message is text plus attributes, not little text, so it is sent unescaped:
  https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api?view=li-lms-2026-09
- Getting access (accessed 2026-09-29): the open w_member_social scope covers "Post, comment and like
  posts on behalf of an authenticated member"; the Comments API page lists w_member_social_feed:
  https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- API versioning (latest version header 202609, versions supported at least one year):
  https://learn.microsoft.com/en-us/linkedin/marketing/versioning
- Sign In with LinkedIn using OpenID Connect (GET /v2/userinfo returns sub, name):
  https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2
- Share on LinkedIn product (grants w_member_social; author is urn:li:person:{sub}):
  https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin
- Authorization code flow (60-day access tokens; programmatic refresh only for a limited set of partners):
  https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow

At most one post, or one comment, per idempotency key: the key is recorded as pending in the
local ledger, under a file lock, before anything is sent, and as published with the post or
comment URN after the answer. A pending key whose outcome is unknown (a timeout, a crash) blocks every new attempt
until `resolve` records what happened. Redirects are refused, so the bearer token is only
ever sent to the URL that was checked.

The ledger lives in a data folder (~/Library/Application Support/ai-workbench/ on macOS,
$XDG_DATA_HOME/ai-workbench/ or ~/.local/share/ai-workbench/ elsewhere), next to the scheduler's jobs.
It used to live in the cache folder, where clearing the cache lost the record of what was already
published; the first verb that writes the ledger copies the old one to the new place (a note on stderr says
so) and never deletes it. A dry run reads the old ledger while the new one does not exist, and writes nothing. Jobs scheduled before this change run a copy of the old provider and keep writing to the
old location, so they must be scheduled again after upgrading.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import mimetypes
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LINKEDIN_VERSION = "202609"
RESTLI_PROTOCOL_VERSION = "2.0.0"
DEFAULT_API_BASE = "https://api.linkedin.com"
KEYRING_SERVICE = "openhora"
KEYRING_USERNAME = "publisher-linkedin"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif"}
EXPIRY_WARNING_DAYS = 7
IMAGE_URN_PLACEHOLDER = "<image URN returned by initializeUpload>"
UPLOAD_URL_PLACEHOLDER = "<uploadUrl returned by initializeUpload>"
AUTHOR_PLACEHOLDER = "urn:li:person:<sub from /v2/userinfo, read at publish time>"
POST_URN_PLACEHOLDER = "<post URN returned by the Posts API>"
FIRST_COMMENT_SUFFIX = ".first-comment"
# Both URNs go into a URL path, so their shape is checked strictly before they are used.
POST_URN_RE = re.compile(r"urn:li:(?:share|ugcPost|activity):\d+")
COMMENT_URN_RE = re.compile(r"urn:li:comment:\((urn:li:(?:activity|share|ugcPost):\d+),(\d+)\)")
SHORT_COMMENT_URN_RE = re.compile(r"^urn:li:comment:\((activity|share|ugcPost):(\d+),(\d+)\)$")
COMMENT_SCOPE_HINT = (
    "the token may lack the permission to comment as the member: LinkedIn's getting-access page says the "
    "w_member_social scope covers commenting, while the Comments API page lists w_member_social_feed; "
    "check the app's products and scopes, then rerun auth.py --provider linkedin"
)
HTTP_TIMEOUT_SECONDS = 60
LOCK_TIMEOUT_SECONDS = 10
# 4xx answers that do not say the request was refused: 408 (the service gave up waiting, after a request that
# may have been taken) and 429 (a limit, which a gateway can answer for a request already accepted behind it).
# After one of them the key stays pending, like after a timeout; every other 4xx releases it.
UNKNOWN_OUTCOME_STATUSES = (408, 429)

# Reserved characters of the little text format. Backslash comes first so that the
# escapes added for the other characters are not escaped twice.
LITTLE_RESERVED = "\\|{}@[]()<>#*_~"
# A hashtag in post commentary: "#" not preceded by a word character, then ASCII letters, digits or
# underscores with at least one letter, not followed by another word character. "#café" or
# "#1" do not match and stay plain text.
HASHTAG_RE = re.compile(r"(?<!\w)#(?=[A-Za-z0-9_]*[A-Za-z])([A-Za-z0-9_]+)(?!\w)")

EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
# The platforms this implementation serves. providers/resolve.py reads this one line as text, without
# importing the file, to choose among the implementations of publisher:<platform> (providers/CONTRACT.md).
PLATFORMS = ("linkedin",)

HELP_EPILOG = f"""\
verbs:
  publish   Publish one post as the authenticated member. Needs
            --idempotency-key and --confirmed (or --dry-run). Refuses --at in
            the future: scheduling belongs to the scheduler class, not to this
            provider. The dry run reads no token and calls nothing. The text
            is escaped for the little text format, except that a #word (ASCII
            letters, digits, _) becomes a hashtag; @name stays plain text.
            --first-comment-file <f> also posts that file as a comment on the
            post, with the key <post key>{FIRST_COMMENT_SUFFIX}: one command, one approval.
            If the post goes out and the comment fails, the JSON has the
            post_urn and first_comment_error and the exit code is 1; rerunning
            the same command replays the post and retries only the comment.
  comment   Comment on a post as the authenticated member: --text-file <f>,
            --idempotency-key <k>, and the post by --on-key <the post's
            publish key> (it must be published) or --post-id <urn:li:share:N,
            urn:li:ugcPost:N or urn:li:activity:N>. --parent-comment-id
            <urn:li:comment:(urn:li:activity:N,N)> makes it a reply. Needs
            --confirmed (or --dry-run). The text is sent as written: comments
            do not use the little text format.
  resolve   Settle a key left pending by a timeout or a crash, after checking
            the member's recent posts or the post's comments: --post-id <urn>
            (the post was published), --comment-id <urn> (the comment was) or
            --not-published (it was not; the key may be used again). Needs
            --confirmed; with --dry-run it prints what it would record and
            changes nothing.
  posts     List the published posts the ledger records: --since <ISO-8601
            with an offset> (a time without one is refused). Read-only: it
            reads the ledger and nothing else, no token and no request, and
            writes nothing. A post is an entry whose status is published and
            whose kind is not comment; published_at is the ledger's created_at
            (the time the platform accepted the post). A published post with
            no readable created_at (an entry written before the ledger's
            version 2) is listed by key under "undated", whatever --since,
            and no time is derived for it.

identifiers:
  --post-id, --comment-id and --parent-comment-id are the generic names of
  the publisher class (providers/CONTRACT.md): a caller passes the value it
  was given and never builds one. Here a post id is a post URN and a comment
  id a comment URN. --post-urn, --comment-urn and --parent-comment, the names
  in use before 2026-10-02, are accepted as aliases.

idempotency:
  Each key publishes one post or one comment at most once. It is recorded as pending in the ledger
  before the request and as published after it, under a file lock; a pending
  key refuses every new attempt until resolve settles it. A key holds one
  content: the ledger keeps the sha256 of what was sent (the text, and the
  image), and the same key with other content is refused (exit 1, nothing
  sent); an entry written before the hash was kept replays as before. A key
  is released when nothing was sent, or when LinkedIn refused the request with
  a 4xx answer other than 408 and 429; after a timeout, a dropped connection,
  a 5xx, a 408 or a 429 the outcome is unknown and the key stays pending.

credentials (never from files or flags):
  The access token is read from the OS secret store (service "{KEYRING_SERVICE}",
  username "{KEYRING_USERNAME}"), written there by:
      uv run providers/publisher/auth.py --provider linkedin
  LINKEDIN_ACCESS_TOKEN        optional; an access token taken from the
                               environment instead of the secret store.
  LINKEDIN_TOKEN_EXPIRES_AT    optional; ISO-8601 expiry of LINKEDIN_ACCESS_TOKEN.

other environment variables:
  PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS  seconds to wait before each retry of a first comment that
                               LinkedIn answers with 404 right after the post is created (it does, for
                               a few seconds, longer with an image). Default: 5,15,30,60. Other
                               refusals are not retried.
  PUBLISHER_LINKEDIN_LEDGER    path of the idempotency ledger (JSON). A scheduler does not pass this
                               variable on to its jobs: a command that runs later carries --ledger
                               <the "ledger" its dry run printed> instead, and is refused when
                               this variable then names another file. Default, in a data folder:
                               ~/Library/Application Support/ai-workbench/publisher-linkedin.json
                               on macOS; elsewhere $XDG_DATA_HOME/ai-workbench/publisher-linkedin.json,
                               or ~/.local/share/ai-workbench/publisher-linkedin.json. A ledger at
                               its old place ($XDG_CACHE_HOME/ai-workbench/ or ~/.cache/ai-workbench/)
                               is copied there by the first verb that writes the ledger and never
                               deleted; a dry run reads it there and writes nothing.
  LINKEDIN_API_BASE            tests only. Replaces {DEFAULT_API_BASE} with a
                               loopback URL (http://127.0.0.1:<port>). Any other
                               host is refused. When set, the secret store is not
                               read; the token must come from LINKEDIN_ACCESS_TOKEN.
  LINKEDIN_HTTP_TIMEOUT        tests only, with LINKEDIN_API_BASE: seconds before
                               a request times out (default {HTTP_TIMEOUT_SECONDS}).

output:
  every dry run: "ledger", the path of the idempotency ledger this environment uses.
  publish: JSON on stdout with post_urn, post_url, token_expires_at,
  token_expires_in_days, idempotency_key, replayed, and with
  --first-comment-file, first_comment (comment_urn, idempotency_key, replayed)
  or first_comment_error.
  comment: comment_urn, post_urn, parent_comment, idempotency_key, replayed,
  token_expires_at, token_expires_in_days.
  posts: {{"platform", "since", "ledger", "posts": [{{"idempotency_key",
  "post_url", "published_at"}}, ...] (at or after --since, oldest first),
  "undated": [<key>, ...]}}.
  Diagnostics on stderr. Tokens are never printed.

exit codes: 0 success, 1 provider or service error, 2 usage error (also --check
with a verb, and a flag the verb does not read: --media with comment, --on-key
with publish, --since with any verb but posts), 3 not configured.

LinkedIn API version pinned: {LINKEDIN_VERSION}. Access tokens last 60 days and
there is no refresh token for self-serve apps: rerun auth.py before expiry.

examples:
  uv run providers/publisher/linkedin.py --check [--platform linkedin]
  uv run providers/publisher/linkedin.py publish --platform linkedin \\
      --text-file post.txt --media cover.png --idempotency-key launch-2026-10 --dry-run
  uv run providers/publisher/linkedin.py publish --platform linkedin \\
      --text-file post.txt --idempotency-key launch-2026-10 --confirmed
  uv run providers/publisher/linkedin.py publish --platform linkedin \\
      --text-file post.txt --first-comment-file link.txt \\
      --idempotency-key launch-2026-10 --confirmed
  uv run providers/publisher/linkedin.py comment --platform linkedin \\
      --text-file reply.txt --idempotency-key reply-1 --on-key launch-2026-10 \\
      --parent-comment-id 'urn:li:comment:(urn:li:activity:123,456)' --dry-run
  uv run providers/publisher/linkedin.py resolve --idempotency-key launch-2026-10 \\
      --not-published --confirmed
  uv run providers/publisher/linkedin.py posts --platform linkedin \\
      --since 2026-10-01T00:00:00+00:00
"""


class ProviderError(Exception):
    """An error with an exit code and a one-line message for stderr."""

    def __init__(self, message: str, code: int = EXIT_SERVICE, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status  # the HTTP status the service answered with, when it answered


def log(message: str) -> None:
    print(message, file=sys.stderr)


def escape_little_text(text: str) -> str:
    """Escape every reserved character of the little text format with a backslash."""
    return "".join("\\" + ch if ch in LITTLE_RESERVED else ch for ch in text)


def post_commentary(text: str) -> str:
    """Post text in little text format: each #word becomes the documented HashtagTemplate
    ({hashtag|\\#|word}); every other reserved character, @ included, is escaped."""
    out, last = [], 0
    for match in HASHTAG_RE.finditer(text):
        out.append(escape_little_text(text[last:match.start()]))
        out.append("{hashtag|\\#|" + escape_little_text(match.group(1)) + "}")
        last = match.end()
    out.append(escape_little_text(text[last:]))
    return "".join(out)


def parse_iso(value: str) -> datetime:
    """Parse ISO-8601; a trailing Z means UTC; a value without offset is local time."""
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


# --- configuration -----------------------------------------------------------


def api_base() -> tuple[str, bool]:
    """Return (base URL, test mode). Test mode accepts only loopback hosts."""
    override = os.environ.get("LINKEDIN_API_BASE")
    if not override:
        return DEFAULT_API_BASE, False
    parsed = urllib.parse.urlparse(override)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ProviderError(
            "LINKEDIN_API_BASE is for tests only and must be a loopback URL such as http://127.0.0.1:8080",
            EXIT_USAGE,
        )
    return override.rstrip("/"), True


def secret_resolver():
    """The workbench's one secret resolver, imported by path: resolver.py next to this file first (a
    scheduled job runs a copy of this script from its job folder, with resolver.py in the same
    snapshot), then providers/secrets/resolver.py in the workbench."""
    here = Path(__file__).resolve()
    candidates = (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py")
    path = next((c for c in candidates if c.is_file()), None)
    if path is None:
        raise ProviderError(
            "providers/secrets/resolver.py is not next to this script nor in the workbench; a scheduled job "
            "must list it in its snapshot (providers/scheduler/README.md)", EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def load_token(test_mode: bool) -> dict:
    """Return {"access_token": str, "expires_at": str|None}. Raise EXIT_NOT_CONFIGURED if absent or expired."""
    # The resolver reads LINKEDIN_ACCESS_TOKEN from the environment, then the OS secret store, where
    # auth.py keeps a JSON record; tests never read the store.
    found = secret_resolver().resolve("LINKEDIN_ACCESS_TOKEN", allow_store=not test_mode)
    token, source = found if found else (None, "")
    expires_at = os.environ.get("LINKEDIN_TOKEN_EXPIRES_AT")
    if token and source == "secret store":
        stored, token, expires_at = token, None, None
        if stored:
            try:
                data = json.loads(stored)
                token, expires_at = data.get("access_token"), data.get("expires_at")
            except (ValueError, AttributeError):
                raise ProviderError(
                    "the stored LinkedIn credential is unreadable; rerun auth.py --provider linkedin",
                    EXIT_NOT_CONFIGURED,
                )
    if not token:
        raise ProviderError(
            "no LinkedIn access token; run: uv run providers/publisher/auth.py --provider linkedin",
            EXIT_NOT_CONFIGURED,
        )
    if expires_at:
        try:
            expiry = parse_iso(expires_at)
        except ValueError:
            raise ProviderError("the stored token expiry is not ISO-8601", EXIT_NOT_CONFIGURED)
        if expiry <= datetime.now(timezone.utc):
            raise ProviderError(
                f"the LinkedIn access token expired on {expiry.date().isoformat()}; "
                "run: uv run providers/publisher/auth.py --provider linkedin",
                EXIT_NOT_CONFIGURED,
            )
        expires_at = expiry.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"access_token": token, "expires_at": expires_at}


def days_until(expires_at: str | None) -> int | None:
    if not expires_at:
        return None
    return int((parse_iso(expires_at) - datetime.now(timezone.utc)).total_seconds() // 86400)


LEDGER_NAME = "publisher-linkedin.json"


def data_home() -> Path:
    """The folder for state that must outlive cache cleaning: the one the scheduler providers use."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ai-workbench"
    data = os.environ.get("XDG_DATA_HOME")
    base = Path(data) if data and os.path.isabs(data) else Path.home() / ".local" / "share"
    return base / "ai-workbench"


# The ledger --ledger pins, set by main(). A command that runs later (a scheduled job) carries the path of the
# ledger it was approved with: a scheduler does not pass on the variable that selects another ledger, and a
# key looked up in the wrong ledger is a post published twice.
PINNED_LEDGER: Path | None = None


def ledger_path() -> Path:
    override = os.environ.get("PUBLISHER_LINKEDIN_LEDGER")
    chosen = Path(override).expanduser() if override else None
    if PINNED_LEDGER is not None:
        if chosen is not None and os.path.abspath(chosen) != os.path.abspath(PINNED_LEDGER):
            raise ProviderError(
                f"--ledger pins the idempotency ledger {PINNED_LEDGER}, and PUBLISHER_LINKEDIN_LEDGER names "
                f"another one ({chosen}). A key recorded in one is unknown to the other, so nothing was sent: "
                "unset the variable, or run the command with the ledger it was approved with", EXIT_USAGE)
        return PINNED_LEDGER
    return chosen or data_home() / LEDGER_NAME


def old_ledger_path() -> Path | None:
    """Where the ledger lived before it moved to the data folder; None when another ledger was chosen
    (PUBLISHER_LINKEDIN_LEDGER, or --ledger with a path that is not the default one)."""
    if os.environ.get("PUBLISHER_LINKEDIN_LEDGER"):
        return None
    if PINNED_LEDGER is not None and os.path.abspath(PINNED_LEDGER) != os.path.abspath(data_home() / LEDGER_NAME):
        return None
    cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(cache) / "ai-workbench" / LEDGER_NAME


def ledger_folder_ready(path: Path) -> None:
    """Create the ledger's folder (0700). The provider's own data folder is set to 0700 even when it exists with
    wider permissions; a folder the user chose (PUBLISHER_LINKEDIN_LEDGER, or --ledger elsewhere) is theirs and
    keeps its mode, while the ledger and its lock inside it are 0600."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.path.abspath(path.parent) == os.path.abspath(data_home()):
        os.chmod(path.parent, 0o700)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ledger_migrate() -> None:
    """First use after the move: copy the old ledger to the new place, so no recorded key is lost.

    Runs before every read made under the lock (only a verb that writes the ledger takes it; a dry run never
    does), and does something only while the new ledger does not exist and the old one does. The copy appears under its final name in one step (a hard link, which fails when the name
    exists), so two runs at once cannot overwrite each other. The old file is never changed or deleted.
    """
    path, old = ledger_path(), old_ledger_path()
    if old is None or path.exists() or not old.is_file():
        return
    try:
        content = old.read_bytes()
        json.loads(content.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ProviderError(f"the idempotency ledger at {old} cannot be copied to {path}: {exc}", EXIT_SERVICE)
    ledger_folder_ready(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".publisher-linkedin.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        os.chmod(tmp, 0o600)
        try:
            os.link(tmp, path)
        except FileExistsError:
            return  # another run copied it first
    finally:
        os.unlink(tmp)
    print(f"note: the idempotency ledger moved: copied {old} to {path}; the old file is kept and no longer read",
          file=sys.stderr)


def ledger_read() -> dict:
    """The ledger's content. It writes nothing: while the new ledger does not exist, the old one is read where it
    is, and only ledger_locked(), which a verb that writes takes, copies it."""
    path = ledger_path()
    if not path.exists():
        old = old_ledger_path()
        if old is None or not old.is_file():
            return {"version": 2, "entries": {}}
        path = old
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ProviderError(f"the idempotency ledger at {path} is not valid JSON", EXIT_SERVICE)
    data.setdefault("entries", {})
    return data


def ledger_save(data: dict) -> None:
    path = ledger_path()
    data["version"] = 2
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".publisher-linkedin.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())  # on disk before it replaces the ledger: a crash leaves the old one or the new one
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def ledger_locked():
    """Hold an exclusive lock on the ledger while reading and changing it."""
    path = ledger_path()
    ledger_folder_ready(path)
    fd = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise ProviderError(f"the idempotency ledger {path} stayed locked for {LOCK_TIMEOUT_SECONDS} s")
                time.sleep(0.05)
        ledger_migrate()
        yield ledger_read()
    finally:
        os.close(fd)  # closing the descriptor releases the lock


def entry_status(entry: dict) -> str:
    # Entries written before version 2 have no status; they were written after a 201.
    return entry.get("status") or ("published" if entry.get("post_urn") else "pending")


def entry_kind(entry: dict) -> str:
    # Post entries carry no kind (the ledger format before comments); comment entries say "comment".
    return entry.get("kind") or "post"


def payload_digest(text: str, media: bytes | None = None) -> str:
    """The sha256 of what a request sends: its text as sent, and the sha256 of the image when there is one."""
    doc = {"text": text, "media_sha256": hashlib.sha256(media).hexdigest() if media is not None else None}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def check_same_payload(key: str, existing: dict, digest: str, kind: str) -> None:
    """A key holds one content. An entry written before the hash was recorded has none and replays as before."""
    held = existing.get("payload_sha256")
    if held and held != digest:
        raise ProviderError(
            f"idempotency key {key!r} already holds a {kind} with other content (sha256 {held[:12]}..., this "
            f"one {digest[:12]}...); nothing was sent. One key per {kind}: use a new key for new content",
            EXIT_SERVICE)


def ledger_claim(key: str, extra: dict | None = None) -> dict | None:
    """Record key as pending (with extra fields) and return None, or return the entry that already holds it."""
    with ledger_locked() as data:
        existing = data["entries"].get(key)
        if existing:
            return existing
        data["entries"][key] = {**(extra or {}), "status": "pending", "started_at": now_iso()}
        ledger_save(data)
    return None


def ledger_update(key: str, entry: dict | None) -> None:
    """Replace key's entry; None removes it."""
    with ledger_locked() as data:
        if entry is None:
            data["entries"].pop(key, None)
        else:
            data["entries"][key] = entry
        ledger_save(data)


def refused(exc: ProviderError) -> bool:
    """Whether the service's answer says it did not take the request: a 4xx other than 408 and 429."""
    return exc.status is not None and 400 <= exc.status < 500 and exc.status not in UNKNOWN_OUTCOME_STATUSES


def after_unknown(key: str, kind: str) -> str:
    """What to do after an answer that leaves the outcome unknown."""
    where, flag = (("the comments on the post", "--comment-id <urn>") if kind == "comment"
                   else ("the member's recent posts", "--post-id <urn>"))
    return (f"check {where}, then run linkedin.py resolve --idempotency-key {key} with {flag} if it is there or "
            "--not-published if it is not, and --confirmed; after --not-published the same command may run again")


def pending_message(key: str, entry: dict) -> str:
    if entry_kind(entry) == "comment":
        where = f"the comments on {entry.get('post_urn') or 'the post'}"
        flag = "--comment-id <urn>"
    else:
        where, flag = "the member's recent posts", "--post-id <urn>"
    return (
        f"idempotency key {key!r} has a pending attempt from {entry.get('started_at', 'an unknown time')} whose "
        f"outcome is unknown (a timeout or a crash); nothing was sent this time. Check {where}, "
        f"then run linkedin.py resolve --idempotency-key {key} with {flag} if it was published or "
        "--not-published if it was not, and --confirmed"
    )


# --- HTTP --------------------------------------------------------------------


def rest_headers(token: str | None, json_body: bool = True) -> dict:
    headers = {
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": RESTLI_PROTOCOL_VERSION,
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the request carries the bearer token to a URL that was checked."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        path = urllib.parse.urlparse(req.full_url).path
        raise ProviderError(f"refusing to follow a {code} redirect on {req.get_method()} {path}; "
                            "the request carries the access token", EXIT_SERVICE, code)


OPENER = urllib.request.build_opener(RefuseRedirect)


def http_timeout() -> float:
    override = os.environ.get("LINKEDIN_HTTP_TIMEOUT")
    if override and os.environ.get("LINKEDIN_API_BASE"):  # test mode only; api_base() checked it
        return float(override)
    return HTTP_TIMEOUT_SECONDS


def http(method: str, url: str, headers: dict, body: bytes | None = None) -> tuple[int, dict, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    path = urllib.parse.urlparse(url).path
    try:
        with OPENER.open(request, timeout=http_timeout()) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        message = ""
        try:
            message = json.loads(payload).get("message", "")
        except (ValueError, AttributeError):
            pass
        detail = f": {message}" if message else ""
        if exc.code == 401:
            raise ProviderError(
                f"LinkedIn rejected the token (401 on {method} {path}){detail}; "
                "run: uv run providers/publisher/auth.py --provider linkedin",
                EXIT_NOT_CONFIGURED,
                401,
            )
        raise ProviderError(f"LinkedIn returned {exc.code} on {method} {path}{detail}", EXIT_SERVICE, exc.code)
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach LinkedIn on {method} {path}: {exc.reason}", EXIT_SERVICE)
    except TimeoutError:
        raise ProviderError(f"LinkedIn timed out on {method} {path} after {http_timeout():g} s", EXIT_SERVICE)
    except OSError as exc:  # the connection dropped after the request was sent
        raise ProviderError(f"the connection to LinkedIn failed on {method} {path}: {type(exc).__name__}", EXIT_SERVICE)


def userinfo(base: str, token: str) -> dict:
    # /v2/userinfo is an OpenID Connect endpoint: bearer token only, no version headers.
    status, _, body = http("GET", f"{base}/v2/userinfo", {"Authorization": f"Bearer {token}"})
    try:
        data = json.loads(body)
    except ValueError:
        raise ProviderError(f"unexpected /v2/userinfo response (status {status})")
    if not data.get("sub"):
        raise ProviderError("the /v2/userinfo response has no sub; the token lacks the openid scope")
    return data


def check_upload_url(url: str, base: str, test_mode: bool) -> None:
    """The upload receives the bearer token, so only send it to LinkedIn (or the test server)."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if test_mode and host == urllib.parse.urlparse(base).hostname:
        return
    if parsed.scheme == "https" and (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return
    raise ProviderError(f"refusing to upload to an unexpected host: {host or url}")


# --- publish -----------------------------------------------------------------


def post_body(author: str, commentary: str, image_urn: str | None) -> dict:
    body = {
        "author": author,
        "commentary": commentary,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        body["content"] = {"media": {"id": image_urn}}
    return body


def post_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/"


def check_platform(args) -> None:
    if args.platform not in PLATFORMS:
        raise ProviderError(f"--platform {args.platform!r} is not served by this provider; "
                            f"use {' or '.join(PLATFORMS)}", EXIT_USAGE)


def read_text_file(path_arg: str, flag: str) -> str:
    path = Path(path_arg)
    if not path.is_file():
        raise ProviderError(f"{flag} not found: {path}", EXIT_USAGE)
    text = path.read_text(encoding="utf-8").strip("\n")
    if not text.strip():
        raise ProviderError(f"{flag} is empty", EXIT_USAGE)
    return text


def validate_publish_args(args) -> tuple[str, Path | None, str | None]:
    check_platform(args)
    text = read_text_file(args.text_file, "--text-file")
    first_comment = read_text_file(args.first_comment_file, "--first-comment-file") if args.first_comment_file else None
    media = args.media or []
    if len(media) > 1:
        raise ProviderError("this provider publishes at most one image per post; pass one --media", EXIT_USAGE)
    image = None
    if media:
        image = Path(media[0])
        if not image.is_file():
            raise ProviderError(f"--media not found: {image}", EXIT_USAGE)
        if image.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ProviderError("--media must be a JPG, PNG or GIF image", EXIT_USAGE)
    if args.at:
        try:
            when = parse_iso(args.at)
        except ValueError:
            raise ProviderError(f"--at is not ISO-8601: {args.at}", EXIT_USAGE)
        if when > datetime.now(timezone.utc):
            raise ProviderError(
                "--at is in the future; the LinkedIn member Posts API has no scheduling. "
                "Scheduling belongs to the scheduler class, not to this provider: schedule a "
                "later call of this command without --at.",
                EXIT_USAGE,
            )
    if not (args.idempotency_key or "").strip():
        raise ProviderError(
            "publish needs --idempotency-key <k>: one key per post, reused on every retry of that post",
            EXIT_USAGE,
        )
    return text, image, first_comment


def token_fields(token: dict) -> dict:
    return {"token_expires_at": token["expires_at"], "token_expires_in_days": days_until(token["expires_at"])}


def warn_expiry(token: dict) -> None:
    days = days_until(token["expires_at"])
    if days is not None and days < EXPIRY_WARNING_DAYS:
        log(f"warning: the LinkedIn token expires in {days} days; rerun auth.py")


def result(urn: str, token: dict, key: str | None, replayed: bool) -> dict:
    return {
        "platform": "linkedin",
        "post_urn": urn,
        "post_url": post_url(urn),
        **token_fields(token),
        "idempotency_key": key,
        "replayed": replayed,
    }


def member_urn_reader(base: str, token: dict):
    """Return a function that reads the member URN from /v2/userinfo once, when first needed."""
    cache: dict = {}

    def member_urn() -> str:
        if "urn" not in cache:
            cache["urn"] = f"urn:li:person:{userinfo(base, token['access_token'])['sub']}"
        return cache["urn"]

    return member_urn


def publish_post(base: str, test_mode: bool, token: dict, member_urn, commentary: str,
                 image: Path | None, key: str) -> tuple[str, bool]:
    """Publish the post at most once per key; return (post URN, replayed)."""
    media = image.read_bytes() if image else None
    digest = payload_digest(commentary, media)
    existing = ledger_claim(key, {"payload_sha256": digest})
    if existing:
        if entry_kind(existing) != "post":
            raise ProviderError(f"idempotency key {key!r} belongs to a comment, not a post; use another key",
                                EXIT_USAGE)
        if entry_status(existing) == "published":
            check_same_payload(key, existing, digest, "post")
            log(f"idempotency key {key!r} already published; returning the existing post")
            return existing["post_urn"], True
        raise ProviderError(pending_message(key, existing), EXIT_SERVICE)

    sent = False  # True once the Posts API request may have reached LinkedIn
    try:
        access = token["access_token"]
        author = member_urn()

        image_urn = None
        if image:
            init_body = {"initializeUploadRequest": {"owner": author}}
            _, _, raw = http(
                "POST",
                f"{base}/rest/images?action=initializeUpload",
                rest_headers(access),
                json.dumps(init_body).encode(),
            )
            try:
                value = json.loads(raw)["value"]
                upload_url, image_urn = value["uploadUrl"], value["image"]
            except (ValueError, KeyError, TypeError):
                raise ProviderError("unexpected initializeUpload response: no value.uploadUrl or value.image")
            check_upload_url(upload_url, base, test_mode)
            http(
                "PUT",
                upload_url,
                {"Authorization": f"Bearer {access}", "Content-Type": "application/octet-stream"},
                media,
            )
            log(f"uploaded {image.name} as {image_urn}")

        sent = True
        status, headers, _ = http(
            "POST",
            f"{base}/rest/posts",
            rest_headers(access),
            json.dumps(post_body(author, commentary, image_urn)).encode(),
        )
    except ProviderError as exc:
        # A 4xx answer other than 408 and 429 means LinkedIn refused the post; anything else after sending is
        # unknown, and the key stays pending until resolve settles it.
        if not sent or refused(exc):
            ledger_update(key, None)
        else:
            ledger_update(key, {"status": "pending", "started_at": now_iso(), "error": str(exc),
                                "payload_sha256": digest})
            if exc.status in UNKNOWN_OUTCOME_STATUSES:
                raise ProviderError(f"{exc}; that answer does not say whether the post was taken, so the key "
                                    f"stays pending: {after_unknown(key, 'post')}", EXIT_SERVICE, exc.status) from None
        raise
    except BaseException:
        if not sent:
            ledger_update(key, None)
        raise
    urn = headers.get("x-restli-id")
    if status != 201 or not urn:
        error = f"unexpected Posts API response: status {status}, no x-restli-id header"
        ledger_update(key, {"status": "pending", "started_at": now_iso(), "error": error, "payload_sha256": digest})
        raise ProviderError(error + "; the key stays pending until resolve settles it")
    ledger_update(key, {"status": "published", "post_urn": urn, "created_at": now_iso(), "payload_sha256": digest})
    return urn, False


def cmd_publish(args) -> int:
    global LEGACY_V2
    # The first comment goes where the comment verb would send it: --legacy-v2 is honoured here too.
    LEGACY_V2 = args.comments_endpoint != "rest" or bool(args.legacy_v2)
    text, image, first_comment = validate_publish_args(args)
    # A setting the first comment needs is read before anything is sent: found malformed only after the
    # post was public, it left a post without its comment for a mistake no request could have caused.
    delays = first_comment_delays() if first_comment is not None else None
    if not args.dry_run and not args.confirmed:
        raise ProviderError(
            "refusing to publish without --confirmed; the calling skill must pass its confirmation gate "
            "first (use --dry-run to preview)",
            EXIT_USAGE,
        )
    base, test_mode = api_base()
    commentary = post_commentary(text)
    key = args.idempotency_key

    if args.dry_run:
        return dry_run(base, commentary, image, key, first_comment)

    token = load_token(test_mode)
    member_urn = member_urn_reader(base, token)
    urn, replayed = publish_post(base, test_mode, token, member_urn, commentary, image, key)
    out = result(urn, token, key, replayed)
    if first_comment is not None:
        comment_key = key + FIRST_COMMENT_SUFFIX
        try:
            if not POST_URN_RE.fullmatch(urn):
                raise ProviderError(f"the post URN {urn!r} has an unexpected shape; not commenting on it")
            done = first_comment_with_retries(base, token, member_urn, urn, first_comment, comment_key, delays)
        except ProviderError as exc:
            # The post is out; only its first comment failed. Rerunning the same command replays the
            # post (its key is published) and retries only the comment.
            out["first_comment"] = None
            out["first_comment_error"] = str(exc)
            log(f"error: the post is published ({urn}) but its first comment failed: {exc}. "
                "Rerun the same command: the post is not published again, only the comment is retried.")
            print(json.dumps(out, indent=2))
            return EXIT_SERVICE
        out["first_comment"] = {
            "comment_urn": done["comment_urn"],
            "idempotency_key": comment_key,
            "replayed": done["replayed"],
        }
    warn_expiry(token)
    print(json.dumps(out, indent=2))
    return EXIT_OK


# --- comment -----------------------------------------------------------------


def first_comment_delays() -> list:
    """Seconds to wait before each retry of a first comment that LinkedIn answered with 404."""
    raw = os.environ.get("PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS", "5,15,30,60")
    try:
        delays = [float(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise ProviderError("PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS must be comma-separated seconds", EXIT_USAGE)
    if any(d < 0 or d > 300 for d in delays) or len(delays) > 8:
        raise ProviderError("PUBLISHER_LINKEDIN_COMMENT_RETRY_DELAYS: at most 8 delays of 0 to 300 seconds", EXIT_USAGE)
    return delays


def first_comment_with_retries(base: str, token: dict, member_urn, post_urn: str, text: str, key: str,
                               delays: list) -> dict:
    """The first comment of a post published a moment ago. LinkedIn answers 404 ("Unable to obtain activity")
    for a few seconds after a post is created, longer when it carries an image, so a 404 is retried after each
    delay. A refused comment leaves no ledger entry, so each retry is a fresh attempt under the same key; any
    other answer is raised at once. The delays were read and checked before the post was sent."""
    for attempt in range(len(delays) + 1):
        try:
            return create_comment(base, token, member_urn, post_urn, None, text, key)
        except ProviderError as exc:
            if exc.status != 404 or attempt == len(delays):
                raise
            log(f"the post is not available for comments yet (404); retrying the first comment in "
                f"{delays[attempt]:g} s ({attempt + 1} of {len(delays)})")
            time.sleep(delays[attempt])


def comment_body(actor: str, post_urn: str, text: str, parent: str | None) -> dict:
    body = {"actor": actor, "object": post_urn, "message": {"text": text}}
    if parent:
        body["parentComment"] = parent
    return body


# Comments go to the unversioned /v2/socialActions endpoint by default, decided by the user on 2026-09-30 after a
# real test with the member token (w_member_social): the versioned /rest endpoint answered "403 Not enough
# permissions to access: partnerApiSocialActions.CREATE" (partner access) and /v2 created the reply. The current
# docs do not describe /v2 for members, so it may change; --comments-endpoint rest keeps the versioned path.
LEGACY_V2 = True


def comment_url(base: str, target: str) -> str:
    # The target (a post URN, or the parent comment URN for a reply) is URL-encoded in the path.
    root = "v2" if LEGACY_V2 else "rest"
    return f"{base}/{root}/socialActions/{urllib.parse.quote(target, safe='')}/comments"


def comment_headers(token: str | None) -> dict:
    headers = rest_headers(token)
    if LEGACY_V2:
        headers.pop("LinkedIn-Version", None)
    return headers


def comment_result(entry: dict, token: dict, key: str, replayed: bool) -> dict:
    return {
        "platform": "linkedin",
        "comment_urn": entry.get("comment_urn"),
        "post_urn": entry.get("post_urn"),
        "parent_comment": entry.get("parent_comment"),
        **token_fields(token),
        "idempotency_key": key,
        "replayed": replayed,
    }


def create_comment(base: str, token: dict, member_urn, post_urn: str, parent: str | None,
                   text: str, key: str) -> dict:
    """Post one comment at most once per key; return the comment result."""
    claim = {"kind": "comment", "post_urn": post_urn, "parent_comment": parent, "payload_sha256": payload_digest(text)}
    existing = ledger_claim(key, claim)
    if existing:
        if entry_kind(existing) != "comment":
            raise ProviderError(f"idempotency key {key!r} belongs to a post, not a comment; use another key",
                                EXIT_USAGE)
        if entry_status(existing) != "published":
            raise ProviderError(pending_message(key, existing), EXIT_SERVICE)
        if existing.get("post_urn") != post_urn or existing.get("parent_comment") != parent:
            raise ProviderError(
                f"idempotency key {key!r} already holds a comment on {existing.get('post_urn')} "
                f"(parent {existing.get('parent_comment')}); one key per comment, use another key", EXIT_USAGE)
        check_same_payload(key, existing, claim["payload_sha256"], "comment")
        log(f"idempotency key {key!r} already published; returning the existing comment")
        return comment_result(existing, token, key, True)

    sent = False  # True once the comment request may have reached LinkedIn
    try:
        actor = member_urn()
        sent = True
        status, headers, raw = http(
            "POST",
            comment_url(base, parent or post_urn),
            comment_headers(token["access_token"]),
            json.dumps(comment_body(actor, post_urn, text, parent)).encode(),
        )
    except ProviderError as exc:
        # A 4xx answer other than 408 and 429 means LinkedIn refused the comment; anything else after sending
        # is unknown, and the key stays pending until resolve settles it.
        if not sent or refused(exc):
            ledger_update(key, None)
        else:
            ledger_update(key, {**claim, "status": "pending", "started_at": now_iso(), "error": str(exc)})
        if exc.status == 403:
            raise ProviderError(f"{exc}; {COMMENT_SCOPE_HINT}", EXIT_SERVICE, 403) from None
        if sent and exc.status in UNKNOWN_OUTCOME_STATUSES:
            limit = ("LinkedIn limits how many comments a member creates per minute. " if exc.status == 429 else "")
            raise ProviderError(f"{exc}; {limit}That answer does not say whether the comment was taken, so the "
                                f"key stays pending: {after_unknown(key, 'comment')}", EXIT_SERVICE, exc.status) from None
        raise
    except BaseException:
        if not sent:
            ledger_update(key, None)
        raise
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    comment_id = headers.get("x-restli-id") or data.get("id")
    urn = data.get("commentUrn")
    if not urn and comment_id and data.get("object"):
        # The Comments API page: a comment's key is its object field and its id.
        urn = f"urn:li:comment:({data['object']},{comment_id})"
    if status not in (200, 201) or not (urn or comment_id):
        error = f"unexpected Comments API response: status {status}, no comment id"
        ledger_update(key, {**claim, "status": "pending", "started_at": now_iso(), "error": error})
        raise ProviderError(error + "; the key stays pending until resolve settles it")
    if not urn:
        log(f"warning: LinkedIn returned comment id {comment_id} without a commentUrn")
    entry = {**claim, "status": "published", "comment_urn": urn, "comment_id": str(comment_id or ""),
             "created_at": now_iso()}
    ledger_update(key, entry)
    return comment_result(entry, token, key, False)


def validate_comment_args(args) -> tuple[str, str | None, str | None]:
    check_platform(args)
    text = read_text_file(args.text_file, "--text-file")
    if not (args.idempotency_key or "").strip():
        raise ProviderError(
            "comment needs --idempotency-key <k>: one key per comment, reused on every retry of that comment",
            EXIT_USAGE,
        )
    if bool(args.on_key) == bool(args.post_urn):
        raise ProviderError("comment needs exactly one of --on-key <post idempotency key> or --post-id <urn>",
                            EXIT_USAGE)
    if args.post_urn and not POST_URN_RE.fullmatch(args.post_urn):
        raise ProviderError("--post-id must look like urn:li:share:<digits>, urn:li:ugcPost:<digits> or "
                            "urn:li:activity:<digits>", EXIT_USAGE)
    if args.parent_comment:
        # A link copied from LinkedIn carries the short form urn:li:comment:(activity:N,N) (seen 2026-09-30);
        # the API documents the full form, which is what is sent.
        args.parent_comment = SHORT_COMMENT_URN_RE.sub(r"urn:li:comment:(urn:li:\1:\2,\3)", args.parent_comment)
    if args.parent_comment and not COMMENT_URN_RE.fullmatch(args.parent_comment):
        raise ProviderError("--parent-comment-id must look like urn:li:comment:(urn:li:activity:<digits>,<digits>)",
                            EXIT_USAGE)
    return text, args.post_urn, args.parent_comment


def post_urn_of_key(on_key: str, required: bool) -> str | None:
    """The URN of the published post recorded under on_key; None (dry run only) when it is not published yet."""
    entry = ledger_read()["entries"].get(on_key)
    if entry and entry_kind(entry) == "post" and entry_status(entry) == "published" and entry.get("post_urn"):
        urn = entry["post_urn"]
        if not POST_URN_RE.fullmatch(urn):
            raise ProviderError(f"the ledger holds {urn!r} for --on-key {on_key!r}, which is not a post URN this "
                                "provider accepts; pass --post-id instead", EXIT_USAGE)
        return urn
    if not required:
        return None
    state = "a comment" if entry and entry_kind(entry) == "comment" else (entry_status(entry) if entry else "absent")
    raise ProviderError(f"--on-key {on_key!r} is {state} in the ledger, not a published post; publish the post "
                        "first (a comment needs its URN) or pass --post-id", EXIT_USAGE)


def cmd_comment(args) -> int:
    global LEGACY_V2
    LEGACY_V2 = args.comments_endpoint != "rest" or bool(args.legacy_v2)
    text, post_urn, parent = validate_comment_args(args)
    if not args.dry_run and not args.confirmed:
        raise ProviderError(
            "refusing to comment without --confirmed; the calling skill must pass its confirmation gate "
            "first (use --dry-run to preview)",
            EXIT_USAGE,
        )
    base, test_mode = api_base()
    key = args.idempotency_key
    if not post_urn:
        post_urn = post_urn_of_key(args.on_key, required=not args.dry_run)

    if args.dry_run:
        return comment_dry_run(base, post_urn, parent, text, key, args.on_key)

    token = load_token(test_mode)
    out = create_comment(base, token, member_urn_reader(base, token), post_urn, parent, text, key)
    warn_expiry(token)
    print(json.dumps(out, indent=2))
    return EXIT_OK


# --- resolve -----------------------------------------------------------------


def cmd_resolve(args) -> int:
    key = (args.idempotency_key or "").strip()
    if not key:
        raise ProviderError("resolve needs --idempotency-key <k>", EXIT_USAGE)
    if sum(bool(x) for x in (args.post_urn, args.comment_urn, args.not_published)) != 1:
        raise ProviderError("resolve needs exactly one of --post-id <urn> (a post), --comment-id <urn> "
                            "(a comment) or --not-published", EXIT_USAGE)
    # The same full-value patterns as comment: the value is recorded, and a later --on-key puts it in a URL path.
    if args.post_urn and not POST_URN_RE.fullmatch(args.post_urn):
        raise ProviderError("--post-id must look like urn:li:share:<digits>, urn:li:ugcPost:<digits> or "
                            "urn:li:activity:<digits>", EXIT_USAGE)
    match = COMMENT_URN_RE.fullmatch(args.comment_urn) if args.comment_urn else None
    if args.comment_urn and not match:
        raise ProviderError("--comment-id must look like urn:li:comment:(urn:li:activity:<digits>,<digits>)",
                            EXIT_USAGE)
    if not args.confirmed and not args.dry_run:
        raise ProviderError("refusing to resolve without --confirmed; the user decides what happened "
                            "(use --dry-run to preview)", EXIT_USAGE)

    def check(entry: dict | None) -> None:
        if not entry or entry_status(entry) != "pending":
            state = entry_status(entry) if entry else "absent"
            raise ProviderError(f"idempotency key {key!r} is {state}, not pending; nothing to resolve", EXIT_USAGE)
        kind = entry_kind(entry)
        if kind == "comment" and args.post_urn:
            raise ProviderError(f"idempotency key {key!r} is a comment; use --comment-id <urn>", EXIT_USAGE)
        if kind == "post" and args.comment_urn:
            raise ProviderError(f"idempotency key {key!r} is a post; use --post-id <urn>", EXIT_USAGE)

    if args.dry_run:
        # A dry run does nothing, also when --confirmed is given with it: the entry is read and left as it is.
        entry = ledger_read()["entries"].get(key)
        check(entry)
        print(json.dumps({"dry_run": True, "idempotency_key": key, "ledger": str(ledger_path()),
                          "pending_entry": entry,
                          "would_record": "published" if (args.post_urn or args.comment_urn) else "released",
                          "post_urn": args.post_urn, "comment_urn": args.comment_urn}, indent=2))
        return EXIT_OK
    with ledger_locked() as data:
        entry = data["entries"].get(key)
        check(entry)
        # The hash of what the pending attempt sent stays with the key, so a later call with other content is refused.
        sent = {"payload_sha256": entry["payload_sha256"]} if entry.get("payload_sha256") else {}
        if args.post_urn:
            data["entries"][key] = {"status": "published", "post_urn": args.post_urn,
                                    "created_at": now_iso(), "resolved": True, **sent}
        elif args.comment_urn:
            data["entries"][key] = {"kind": "comment", "post_urn": entry.get("post_urn"),
                                    "parent_comment": entry.get("parent_comment"), "status": "published",
                                    "comment_urn": args.comment_urn, "comment_id": match.group(2),
                                    "created_at": now_iso(), "resolved": True, **sent}
        else:
            del data["entries"][key]
        ledger_save(data)
    published = bool(args.post_urn or args.comment_urn)
    out = {"idempotency_key": key, "status": "published" if published else "released"}
    if args.post_urn:
        out["post_urn"], out["post_url"] = args.post_urn, post_url(args.post_urn)
    if args.comment_urn:
        out["comment_urn"] = args.comment_urn
    print(json.dumps(out, indent=2))
    return EXIT_OK


# --- dry runs ------------------------------------------------------------------


def redacted_headers() -> dict:
    shown = rest_headers(None)
    shown["Authorization"] = "Bearer <redacted>"
    return shown


def comment_request(base: str, post_urn: str | None, parent: str | None, text: str) -> dict:
    target = parent or post_urn
    return {
        "method": "POST",
        "url": comment_url(base, target) if target else
               f"{base}/{'v2' if LEGACY_V2 else 'rest'}/socialActions/<URL-encoded post URN>/comments",
        "headers": {k: v for k, v in redacted_headers().items() if not (LEGACY_V2 and k == "LinkedIn-Version")},
        "body": comment_body(AUTHOR_PLACEHOLDER, post_urn or POST_URN_PLACEHOLDER, text, parent),
    }


def existing_fields(key: str, prefix: str = "") -> dict:
    existing = ledger_read()["entries"].get(key)
    urn_field = "comment_urn" if existing and entry_kind(existing) == "comment" else "post_urn"
    return {
        f"{prefix}existing_status": entry_status(existing) if existing else None,
        f"{prefix}existing_{urn_field}": existing.get(urn_field) if existing else None,
    }


def dry_run(base: str, commentary: str, image: Path | None, key: str, first_comment: str | None = None) -> int:
    # A dry run does nothing: no credential is read and no request is sent, so the author
    # URN, which only /v2/userinfo knows, is shown as a placeholder.
    author = AUTHOR_PLACEHOLDER
    shown = redacted_headers()
    requests = []
    if image:
        requests.append({
            "method": "POST",
            "url": f"{base}/rest/images?action=initializeUpload",
            "headers": shown,
            "body": {"initializeUploadRequest": {"owner": author}},
        })
        requests.append({
            "method": "PUT",
            "url": UPLOAD_URL_PLACEHOLDER,
            "headers": {"Authorization": "Bearer <redacted>", "Content-Type": "application/octet-stream"},
            "body": f"<{image.stat().st_size} bytes of {image}>",
        })
    requests.append({
        "method": "POST",
        "url": f"{base}/rest/posts",
        "headers": shown,
        "body": post_body(author, commentary, IMAGE_URN_PLACEHOLDER if image else None),
    })
    out = {"dry_run": True, "platform": "linkedin", "requests": requests, "idempotency_key": key,
           "ledger": str(ledger_path())}
    out.update(existing_fields(key))
    if first_comment is not None:
        # The post URN is known only once the post exists; a replayed post shows its real URN.
        posted = out.get("existing_post_urn") if out["existing_status"] == "published" else None
        requests.append(comment_request(base, posted, None, first_comment))
        out["first_comment_idempotency_key"] = key + FIRST_COMMENT_SUFFIX
        out.update(existing_fields(key + FIRST_COMMENT_SUFFIX, "first_comment_"))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return EXIT_OK


def comment_dry_run(base: str, post_urn: str | None, parent: str | None, text: str, key: str,
                    on_key: str | None) -> int:
    # Reads no credential and sends nothing; the actor is a placeholder. With --on-key, a post that
    # is not published yet is shown as a placeholder (the confirmed call refuses it).
    out = {"dry_run": True, "platform": "linkedin", "requests": [comment_request(base, post_urn, parent, text)],
           "idempotency_key": key, "post_urn": post_urn, "on_key": on_key, "parent_comment": parent,
           "ledger": str(ledger_path())}
    out.update(existing_fields(key))
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return EXIT_OK


# --- posts -------------------------------------------------------------------


def parse_iso_with_offset(value: str, flag: str) -> datetime:
    """An ISO-8601 time that states its offset (or Z); a time without one is a usage error, never read as local."""
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw)
    except ValueError:
        raise ProviderError(f"{flag} is not ISO-8601: {value}", EXIT_USAGE) from None
    if parsed.tzinfo is None:
        raise ProviderError(f"{flag} has no offset: {value}; give one (for example +00:00 or Z)", EXIT_USAGE)
    return parsed


def cmd_posts(args) -> int:
    """The published posts of the ledger. Reads the ledger only (no token, no request, no write): a post is an
    entry whose status is published and whose kind is not comment, and its time is the ledger's created_at, the
    time the platform accepted it. A published post without a readable created_at is listed by key under
    "undated", whatever --since: no time is derived for it."""
    since = parse_iso_with_offset(args.since, "--since")
    listed, undated = [], []
    for key, entry in sorted(ledger_read()["entries"].items()):
        if not isinstance(entry, dict) or entry_status(entry) != "published" or entry_kind(entry) != "post":
            continue
        urn = entry.get("post_urn")
        if not isinstance(urn, str) or not urn:
            raise ProviderError(f"the ledger's published post {key!r} holds no post id; nothing was listed",
                                EXIT_SERVICE)
        created = entry.get("created_at")
        try:
            at = parse_iso_with_offset(created, "created_at") if isinstance(created, str) else None
        except ProviderError:
            at = None
        if at is None:
            undated.append(key)
            continue
        if at >= since:
            listed.append((at, key, {"idempotency_key": key, "post_url": post_url(urn), "published_at": created}))
    listed.sort(key=lambda item: (item[0], item[1]))
    print(json.dumps({"platform": args.platform, "since": args.since, "ledger": str(ledger_path()),
                      "posts": [item[2] for item in listed], "undated": undated}, indent=2, ensure_ascii=False))
    return EXIT_OK


# --- check -------------------------------------------------------------------


def cmd_check() -> int:
    base, test_mode = api_base()
    # The contract's one reading of --check: 3 when the person has something to do (no token, an expired
    # one, a token the service rejects), 1 when the service could not be asked. load_token and http say which.
    token = load_token(test_mode)
    info = userinfo(base, token["access_token"])
    days = days_until(token["expires_at"])
    out = {
        "ready": True,
        "platform": "linkedin",
        "member_name": info.get("name"),
        "person_urn": f"urn:li:person:{info['sub']}",
        "token_expires_at": token["expires_at"],
        "token_expires_in_days": days,
        "api_version": LINKEDIN_VERSION,
    }
    if days is None:
        log("warning: token expiry unknown")
    elif days < EXPIRY_WARNING_DAYS:
        out["warning"] = f"token expires in {days} days"
        log(f"warning: the LinkedIn token expires in {days} days; rerun auth.py --provider linkedin")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return EXIT_OK


# --- entry point ---------------------------------------------------------------


# Each flag by its destination, and the verbs that read it. A flag given to a verb that does not read it is a usage
# error, so a caller learns that it was ignored; --check takes no verb and no flag but --platform.
FLAG_NAMES = {
    "platform": "--platform", "text_file": "--text-file", "first_comment_file": "--first-comment-file",
    "media": "--media", "at": "--at", "idempotency_key": "--idempotency-key", "post_urn": "--post-id",
    "on_key": "--on-key", "parent_comment": "--parent-comment-id", "comments_endpoint": "--comments-endpoint",
    "legacy_v2": "--legacy-v2", "comment_urn": "--comment-id", "not_published": "--not-published",
    "ledger": "--ledger", "dry_run": "--dry-run", "confirmed": "--confirmed", "since": "--since",
}
VERB_FLAGS = {
    "publish": {"platform", "text_file", "first_comment_file", "media", "at", "idempotency_key", "comments_endpoint",
                "legacy_v2", "ledger", "dry_run", "confirmed"},
    "comment": {"platform", "text_file", "idempotency_key", "post_urn", "on_key", "parent_comment",
                "comments_endpoint", "legacy_v2", "ledger", "dry_run", "confirmed"},
    "resolve": {"platform", "idempotency_key", "post_urn", "comment_urn", "not_published", "ledger", "dry_run",
                "confirmed"},
    "posts": {"platform", "since", "ledger"},  # read-only: no --dry-run or --confirmed to give
    None: {"platform"},  # --check
}


def check_flags(args) -> None:
    if args.check and args.verb:
        raise ProviderError(f"--check takes no verb: run --check alone, or {args.verb} without --check", EXIT_USAGE)
    if not args.check and not args.verb:
        return
    given = [dest for dest in FLAG_NAMES if getattr(args, dest) not in (None, False)]
    extra = [FLAG_NAMES[dest] for dest in given if dest not in VERB_FLAGS[args.verb]]
    if extra:
        raise ProviderError(f"{', '.join(extra)}: not a flag of {args.verb or '--check'}; nothing was done "
                            "(see --help)", EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin.py",
        description="Publisher provider for LinkedIn: publishes a post, and comments on posts, as the "
        "authenticated member through the versioned Posts and Comments APIs, and lists the published posts its "
        "ledger records.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("verb", nargs="?", choices=["publish", "comment", "resolve", "posts"],
                        help="the action to run")
    parser.add_argument("--check", action="store_true", help="verify the token and print the member; no side effects")
    parser.add_argument("--platform", help="must be linkedin")
    parser.add_argument("--text-file", help="UTF-8 file with the post or comment text")
    parser.add_argument("--first-comment-file", help="with publish: UTF-8 file posted as the post's first comment")
    parser.add_argument("--media", action="append", help="one JPG, PNG or GIF image to attach")
    parser.add_argument("--at", help="ISO-8601 time; a future time is refused (use the scheduler class)")
    parser.add_argument("--idempotency-key", help="required: publish at most once per key (recorded in the local ledger)")
    # The identifiers are the class's generic ones (providers/CONTRACT.md): a caller passes the value it was
    # given and never builds one. On this platform they are URNs. The names in use before 2026-10-02
    # (--post-urn, --comment-urn, --parent-comment) stay as aliases, for commands written with them.
    parser.add_argument("--post-id", "--post-urn", dest="post_urn",
                        help="with comment: the post to comment on; with resolve: the pending post was published "
                             "as this id (a post URN). Alias: --post-urn")
    parser.add_argument("--on-key", help="with comment: the publish idempotency key of the post to comment on")
    parser.add_argument("--parent-comment-id", "--parent-comment", dest="parent_comment",
                        help="with comment: reply to the comment with this id (a comment URN). "
                             "Alias: --parent-comment")
    parser.add_argument("--comments-endpoint", choices=["v2", "rest"],
                        help="comments: v2 (default; works with a member's w_member_social token, checked "
                             "2026-09-30) or rest (the versioned endpoint; needs LinkedIn partner access)")
    parser.add_argument("--legacy-v2", action="store_true",
                        help="with comment, or publish's first comment: use the unversioned /v2/socialActions "
                             "endpoint (the default; an alias kept from its trial, and it wins over "
                             "--comments-endpoint rest)")
    parser.add_argument("--comment-id", "--comment-urn", dest="comment_urn",
                        help="with resolve: the pending comment was published as this id (a comment URN). "
                             "Alias: --comment-urn")
    parser.add_argument("--not-published", action="store_true", help="with resolve: the pending attempt was not published")
    parser.add_argument("--ledger", metavar="PATH",
                        help="the absolute path of the idempotency ledger to use, as a dry run printed it; refused "
                             "when PUBLISHER_LINKEDIN_LEDGER names another one. For commands that run later")
    parser.add_argument("--dry-run", action="store_true", help="print the exact request bodies (with resolve: what "
                        "it would record) and do nothing else")
    parser.add_argument("--confirmed", action="store_true", help="required to publish or comment; set by the calling "
                        "skill's gate")
    parser.add_argument("--since", help="with posts: list the posts published at or after this ISO-8601 time, "
                        "which must state its offset")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)  # the ledger, its lock and its folder are private to the user
    parser = build_parser()
    args = parser.parse_args(argv)
    global PINNED_LEDGER
    try:
        check_flags(args)
        if args.ledger is not None:
            if not os.path.isabs(args.ledger):
                raise ProviderError("--ledger must be an absolute path", EXIT_USAGE)
            PINNED_LEDGER = Path(args.ledger)
            ledger_path()  # refuse a different ledger in the environment before anything else happens
        if args.check:
            if args.platform:  # --check --platform <p>: "do you serve this one, and are you ready for it"
                check_platform(args)
            return cmd_check()
        if args.verb == "publish":
            if not args.platform or not args.text_file:
                raise ProviderError("publish needs --platform linkedin and --text-file <f>", EXIT_USAGE)
            return cmd_publish(args)
        if args.verb == "comment":
            if not args.platform or not args.text_file:
                raise ProviderError("comment needs --platform linkedin and --text-file <f>", EXIT_USAGE)
            return cmd_comment(args)
        if args.verb == "resolve":
            return cmd_resolve(args)
        if args.verb == "posts":
            if not args.platform or not args.since:
                raise ProviderError("posts needs --platform linkedin and --since <ISO-8601 with an offset>",
                                    EXIT_USAGE)
            check_platform(args)
            return cmd_posts(args)
        raise ProviderError("give a verb (publish, comment, resolve, posts) or --check; see --help", EXIT_USAGE)
    except ProviderError as exc:
        log(f"error: {exc}")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
