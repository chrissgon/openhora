"""The class `stock:media`, shared by every source (package V9b-1, decisions D2 to D9 of the V9b spec): libraries of pictures and clips whose licence
allows reuse in a published video, searched by words through their API. A runtime-only class: no skill requires it.

An implementation (providers/stock/<name>.py) says only how to call its library's API and how to read its answer; this module is everything else:
the licence tuple, the source data file and its checks, the caps, the query rule, the 24-hour answer cache, the secret lookup, the candidate
schema and the verbs `--check`, `search` and `fetch`, with their closed refusal codes. Adding a source is one implementation file and one source
file (providers/stock/README.md).

The rules: a URL never comes from a person or a model (no verb takes one: `fetch` takes an item id and reads the file's URL from the library's own
answer); a key never leaves the provider's own call (never in an output, an error, the cache or a file); a licence outside LICENCES_ACCEPTED never
passes; the `unverified` tier is refused unless the caller says the project turned it on.

Standard library only; a secret is read through providers/secrets/resolver.py. Runs on Python 3.9 (the resolver itself needs a newer Python and
the OS secret store, which is why an implementation's header lists the keyring library, as the other providers that read a secret do).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _net  # noqa: E402

# The licence policy (decision D5 and the maintainer's decision 3). runtime/media_stock.py (V9b-3) holds the same two tuples; a test compares them.
LICENCES_ACCEPTED = ("pexels-license", "pixabay-content-license", "cc0-1.0", "pdm-1.0", "cc-by-4.0", "cc-by-3.0")
LICENCES_CREDIT = ("cc-by-4.0", "cc-by-3.0")
UNVERIFIED = "unverified"     # the licence id of a candidate of the `unverified` tier: never in LICENCES_ACCEPTED
TIERS = ("library", "per-item", "unverified")
KINDS = ("image", "clip")
SECRET_IN = ("header", "query", "none")

# The query rule (4.4): English, ASCII letters, 1 to 6 words; no @ . / : or digit.
SEARCH = re.compile(r"[A-Za-z][A-Za-z' -]{1,59}")
MAX_WORDS = 6
ITEM = re.compile(r"[A-Za-z0-9_-]{1,64}")
NAME = re.compile(r"[a-z][a-z0-9]{1,30}")
SECRET_NAME = re.compile(r"[A-Z][A-Z0-9_]{2,63}")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

MIB = 1024 * 1024
CAPS = {
    "max_count": 6,                 # candidates of one search
    "search_seconds": 15, "search_bytes": MIB,
    "preview_bytes": MIB,
    "image_bytes": 16 * MIB, "image_seconds": 60,
    "clip_bytes": 120 * MIB, "clip_seconds": 180,
    "text": 120,                    # characters of a title or an author
    "page": 300,
    "per_page_max": 18,
}
FLOOR = {"image": (1080, 1350), "clip_short_side": 1080, "clip_min_seconds": 2, "clip_max_seconds": 60}
TERMS_MAX_DAYS = 365
CACHE_MAX_SECONDS = 7 * 86400
CACHE_MAX_BYTES = 2 * MIB      # what cache_put writes and cache_get reads: one number
TYPES = {"image": ("image/jpeg", "image/png"), "clip": ("video/mp4",)}
PREVIEW_TYPES = ("image/jpeg", "image/png")
DEFAULT_JOBS = 3

# The closed refusal codes of the class (4.3) and the exit code each one has (providers/CONTRACT.md: 2 usage, 3 not configured, 1 anything else).
CODES = ("source_not_ready", "terms_stale", "no_key", "query_refused", "host_refused", "address_refused", "redirect_refused", "status", "no_length",
         "too_large", "type_refused", "licence_refused", "rate_limited", "network", "out_refused")
EXIT = {"source_not_ready": 3, "terms_stale": 3, "no_key": 3, "query_refused": 2, "out_refused": 2}

SOURCE_KEYS = ("source", "licence_tier", "licence", "licences", "licence_url", "terms_read_on", "secret", "secret_in", "api", "media_hosts",
               "redirect_hosts", "path_patterns", "rendition", "cache_seconds", "credit_line", "kinds")
OPEN_KEYS = ("source", "licence_tier", "secret_in", "kinds", "terms_read_on")      # the whole source file of an open-web source (sources/web.json)
API_KEYS = ("host", "search_image", "search_clip", "item_image", "item_clip")
KIND_KEYS = ("preview", "image", "clip")
API_PATH = re.compile(r"/[A-Za-z0-9/_.{}-]{0,99}")
RENDITION = re.compile(r"[A-Za-z0-9_/.+-]{1,40}")
MAX_SOURCE_BYTES = 64 * 1024
MAX_PATTERN = 200

# The seams a test replaces: the clock of the cache and the loader of the secret resolver.
SEAMS = {"now": time.time, "resolver": None, "sources": None}      # "sources": the folder a source file must be in (default: sources/ next to this file)


class Refusal(Exception):
    """A verb that stops: `code` is one of CODES, `fields` names the null fields of a source that is not ready (never a value)."""

    def __init__(self, code: str, reason: str = "", fields=()):
        super().__init__(reason or code)
        self.code, self.reason, self.fields = code, reason or code, list(fields)

    @property
    def exit_code(self) -> int:
        return EXIT.get(self.code, 1)


# --- the source data file --------------------------------------------------------------------------------------------------------------

def _text(value, limit=200) -> bool:
    return isinstance(value, str) and 0 < len(value) <= limit


def _empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def read_source(path, today, implementation=None, secret_name=None) -> dict:
    """The checked source file at `path`, as a dict with the compiled patterns under `_patterns`. Refusals, in this order: `source_not_ready`
    (exit 3, naming the fields that are null or empty for its tier and kinds, or wrongly shaped), `licence_refused` (a `library` licence or a value
    of `licences` outside LICENCES_ACCEPTED), `terms_stale` (`terms_read_on` more than 365 days before `today`)."""
    try:
        info = os.stat(path)
        if info.st_size > MAX_SOURCE_BYTES:
            raise ValueError("too big")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refusal("source_not_ready", "the source file cannot be read", ["file"]) from None
    if not isinstance(data, dict):
        raise Refusal("source_not_ready", "the source file is not an object", ["file"])
    if set(data) == set(OPEN_KEYS):
        return _read_open(data, implementation)
    odd = sorted(set(data) ^ set(SOURCE_KEYS))
    if odd:
        raise Refusal("source_not_ready", "the source file has unknown or missing keys", odd)
    problems = _missing(data, implementation, secret_name)
    if problems:
        raise Refusal("source_not_ready", "the source file is not filled: " + ", ".join(problems), problems)
    _check_licences(data)
    _check_terms(data, today)
    patterns = {k: re.compile(data["path_patterns"][k]) for k in KIND_KEYS if data["path_patterns"].get(k)}
    return dict(data, _patterns=patterns)


def _read_open(data, implementation) -> dict:
    """The source file of an open-web source (V9b-1c): exactly the five OPEN_KEYS, no API, no host list, no pattern, no key and no terms date (the open web has
    no terms to read; the risk is carried by the warning and the per-asset approval). It must say `unverified`, `none` and valid kinds, and `terms_read_on`
    stays null: a date would claim a reading that never happened. The answer has every key of SOURCE_KEYS, empty."""
    problems = []
    if not (isinstance(data["source"], str) and NAME.fullmatch(data["source"])) or (implementation and data["source"] != implementation):
        problems.append("source")
    if data["licence_tier"] != "unverified":
        problems.append("licence_tier")
    if data["secret_in"] != "none":
        problems.append("secret_in")
    kinds = data["kinds"]
    if not (isinstance(kinds, list) and kinds and len(set(kinds)) == len(kinds) and all(k in KINDS for k in kinds)):
        problems.append("kinds")
    if data["terms_read_on"] is not None:
        problems.append("terms_read_on")
    if problems:
        raise Refusal("source_not_ready", "the source file is not filled: " + ", ".join(problems), problems)
    return dict(data, licence=None, licences=None, licence_url=None, secret=None, api={}, media_hosts=[], redirect_hosts=[], path_patterns={},
                rendition={}, cache_seconds=0, credit_line=None, _patterns={})


def _missing(d, implementation, secret_name=None) -> list:
    out = []
    tier, kinds = d["licence_tier"], d["kinds"]
    if not (isinstance(d["source"], str) and NAME.fullmatch(d["source"])) or (implementation and d["source"] != implementation):
        out.append("source")
    if tier not in TIERS:
        out.append("licence_tier")
    if not (isinstance(kinds, list) and kinds and len(set(kinds)) == len(kinds) and all(k in KINDS for k in kinds)):
        out.append("kinds")
        kinds = []
    if tier == "library" and not _text(d["licence"], 60):
        out.append("licence")
    if tier != "library" and d["licence"] is not None:
        out.append("licence")
    if tier == "per-item":
        table = d["licences"]
        if not (isinstance(table, dict) and table and all(_text(k, 60) and _text(v, 60) for k, v in table.items())):
            out.append("licences")
    elif d["licences"] is not None:
        out.append("licences")
    if not _text(d["licence_url"], 300):
        out.append("licence_url")
    if not (isinstance(d["terms_read_on"], str) and DATE.fullmatch(d["terms_read_on"]) and _date(d["terms_read_on"])):
        out.append("terms_read_on")
    if d["secret_in"] not in SECRET_IN:
        out.append("secret_in")
    elif d["secret_in"] == "none":
        if d["secret"] is not None:
            out.append("secret")
    elif not (isinstance(d["secret"], str) and SECRET_NAME.fullmatch(d["secret"])) or (secret_name is not None and d["secret"] != secret_name):
        out.append("secret")      # the implementation names its own secret: a file cannot point a provider at another credential
    api = d["api"]
    if not isinstance(api, dict) or set(api) != set(API_KEYS):
        out.append("api")
    else:
        if not (_net.valid_host(api["host"])):
            out.append("api.host")
        for kind in kinds:
            if not (isinstance(api["search_" + kind], str) and API_PATH.fullmatch(api["search_" + kind])):
                out.append("api.search_" + kind)
            item = api["item_" + kind]
            if not (isinstance(item, str) and API_PATH.fullmatch(item) and item.count("{item}") == 1):
                out.append("api.item_" + kind)
    for name in ("media_hosts", "redirect_hosts"):
        hosts = d[name]
        good = isinstance(hosts, list) and len(hosts) <= 20 and all(h == h.lower() and _net.valid_host(h) for h in hosts)
        if not good or (name == "media_hosts" and not hosts):
            out.append(name)
    for name in ("path_patterns", "rendition"):
        block = d[name]
        if not isinstance(block, dict) or set(block) != set(KIND_KEYS):
            out.append(name)
            continue
        for key in ("preview",) + tuple(kinds):
            value = block[key]
            if name == "rendition":
                bad = not (isinstance(value, str) and RENDITION.fullmatch(value))
            else:
                bad = not (isinstance(value, str) and 0 < len(value) <= MAX_PATTERN and _compiles(value))
            if bad:
                out.append("%s.%s" % (name, key))
    seconds = d["cache_seconds"]
    if not (isinstance(seconds, int) and not isinstance(seconds, bool) and 0 <= seconds <= CACHE_MAX_SECONDS):
        out.append("cache_seconds")
    if tier == "per-item" and not _text(d["credit_line"], 400):
        out.append("credit_line")
    elif d["credit_line"] is not None and not _text(d["credit_line"], 400):
        out.append("credit_line")
    return out


def _compiles(pattern) -> bool:
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _date(text):
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None


def _check_licences(d):
    ids = [d["licence"]] if d["licence_tier"] == "library" else list((d["licences"] or {}).values())
    if any(i not in LICENCES_ACCEPTED for i in ids):
        raise Refusal("licence_refused", "a licence of the source file is outside the accepted list")


def _check_terms(d, today):
    read = _date(d["terms_read_on"])
    now = _date(today) if isinstance(today, str) and DATE.fullmatch(today) else None
    if now is None:
        raise Refusal("source_not_ready", "no valid --today", ["today"])
    if (now - read).days < 0:
        raise Refusal("source_not_ready", "terms_read_on is in the future", ["terms_read_on"])
    if (now - read).days > TERMS_MAX_DAYS:
        raise Refusal("terms_stale", "the terms were read more than %d days ago: they are read again before use" % TERMS_MAX_DAYS)


def pin_source(path, impl):
    """The source file must be the implementation's own, sources/<SOURCE>.json next to this folder's files (real paths compared): a caller's file could
    name other hosts and another secret. source_not_ready, naming `source_file`, otherwise."""
    folder = SEAMS["sources"] or str(HERE / "sources")
    want = os.path.realpath(os.path.join(folder, impl.SOURCE + ".json"))
    if not isinstance(path, str) or os.path.realpath(path) != want:
        raise Refusal("source_not_ready", "the source file is not providers/stock/sources/%s.json" % impl.SOURCE, ["source_file"])


def map_licence(table, own) -> "str | None":
    """A `per-item` implementation's helper: our licence id for an item's own licence string (its key of the source file's `licences`), or None."""
    return table.get(own) if isinstance(own, str) and isinstance(table, dict) else None


# --- the query, texts and candidates ---------------------------------------------------------------------------------------------------

def check_query(query) -> str:
    """The query when it is 1 to 6 words of ASCII letters, apostrophes and hyphens, no leading or trailing space; else query_refused."""
    if not isinstance(query, str) or query != query.strip() or not SEARCH.fullmatch(query) or len(query.split()) > MAX_WORDS:
        raise Refusal("query_refused", "the search words are 1 to 6 words of ASCII letters")
    return query


def clean_text(value, limit) -> str:
    """Third-party text kept as data: printable characters only, white space collapsed, at most `limit` characters; "" when it is not text."""
    if not isinstance(value, str):
        return ""
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())
    return text[:limit]


def clean_page(value) -> str:
    """A library page link kept as data: https, a plausible host, no user info, at most 300 characters; else ""."""
    if not isinstance(value, str) or len(value) > CAPS["page"]:
        return ""
    try:
        parts = urllib.parse.urlsplit(value)
        host = parts.hostname or ""
    except ValueError:
        return ""
    ok = parts.scheme == "https" and _net.valid_host(host) and "@" not in parts.netloc and all(ch.isprintable() and ch != " " for ch in value)
    return value if ok else ""


def admit_licence(tier, licence, author, allow_unverified=False) -> bool:
    """Whether a candidate may pass: its licence id is in LICENCES_ACCEPTED (and a licence that asks for credit has an author), or it is the
    `unverified` id of a source of that tier and the caller said the project turned that tier on."""
    if licence == UNVERIFIED:
        return tier == "unverified" and bool(allow_unverified)
    if licence not in LICENCES_ACCEPTED:
        return False
    return not (licence in LICENCES_CREDIT and not author)


def candidate(raw, src, kind, impl, allow_unverified):
    """(candidate, None) for a raw answer item the implementation read, or (None, reason) with reason one of too_small, too_long, licence, host."""
    item = raw.get("item")
    if not (isinstance(item, str) and ITEM.fullmatch(item)):
        return None, "host"
    tier = src["licence_tier"]
    licence = src["licence"] if tier == "library" else (UNVERIFIED if tier == "unverified" else raw.get("licence"))
    author = clean_text(raw.get("author"), CAPS["text"])
    if not admit_licence(tier, licence, author, allow_unverified):
        return None, "licence"
    width, height, seconds = raw.get("width"), raw.get("height"), raw.get("seconds")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (width, height)):
        return None, "too_small"
    if kind == "image":
        low = getattr(impl, "IMAGE_MIN", FLOOR["image"])
        if width < low[0] or height < low[1]:
            return None, "too_small"
        seconds = None
    else:
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds):
            return None, "too_small"
        if seconds > FLOOR["clip_max_seconds"]:
            return None, "too_long"
        if seconds < FLOOR["clip_min_seconds"] or not raw.get("file_url"):
            return None, "too_small"
        seconds = round(float(seconds), 3)
    patterns = src["_patterns"]
    for url, key in ((raw.get("preview_url"), "preview"), (raw.get("file_url"), kind)):
        try:
            host, _, path = _net.split_url(url, src["media_hosts"])
        except _net.NetError:
            return None, "host"
        if not patterns[key].fullmatch(path):
            return None, "host"
    return {"item": item, "kind": kind, "width": width, "height": height, "seconds": seconds, "author": author,
            "title": clean_text(raw.get("title"), CAPS["text"]), "licence": licence, "page": clean_page(raw.get("page")),
            "_preview_url": raw["preview_url"]}, None


# --- the answer cache (4.1) ------------------------------------------------------------------------------------------------------------

def state_dir(environ=None) -> str:
    """OPENHORA_STATE_DIR, else an absolute XDG_STATE_HOME + /openhora, else ~/.local/state/openhora."""
    environ = os.environ if environ is None else environ
    explicit = environ.get("OPENHORA_STATE_DIR")
    if explicit and os.path.isabs(explicit):
        return explicit
    xdg = environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def _cache_dir(source, environ):
    return os.path.join(state_dir(environ), "stock", "cache", source)


def cache_key(*parts) -> str:
    """The name of a cached answer: the hash of what the request asks for (never a key, never a URL)."""
    return hashlib.sha256(json.dumps(list(parts), sort_keys=True).encode("utf-8")).hexdigest()


def cache_get(source, key, seconds, environ=None, now=None):
    """The cached answer for `key` when `seconds` is above 0 and it is younger than that, else None."""
    if not seconds:
        return None
    now = SEAMS["now"]() if now is None else now
    path = os.path.join(_cache_dir(source, environ), key + ".json")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(CACHE_MAX_BYTES + 1)
        if len(raw) > CACHE_MAX_BYTES:
            return None
        data = json.loads(raw.decode("utf-8"), parse_constant=_net._constant)
        at = data["at"]
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not 0 <= now - at < seconds:
            return None
        return data["answer"]
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return None


def cache_put(source, key, answer, seconds, secret=None, environ=None, now=None) -> bool:
    """Keep an answer for `seconds` (0600 in a 0700 folder, atomically). Nothing is written when `seconds` is 0, or when the text holds the key."""
    if not seconds:
        return False
    try:
        text = json.dumps({"at": SEAMS["now"]() if now is None else now, "answer": answer}, sort_keys=True, ensure_ascii=False, allow_nan=False)
        data = text.encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        return False
    if (secret and secret in text) or len(data) > CACHE_MAX_BYTES:
        return False
    folder = _cache_dir(source, environ)
    try:
        _private_dirs(folder)
        temp = os.path.join(folder, ".tmp-%s" % hashlib.sha256(os.urandom(16)).hexdigest()[:12])
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temp, os.path.join(folder, key + ".json"))
    except OSError:
        return False
    return True


def _private_dirs(folder):
    missing = []
    here = folder
    while not os.path.isdir(here):
        missing.append(here)
        here = os.path.dirname(here)
    for path in reversed(missing):
        os.mkdir(path, 0o700)
        os.chmod(path, 0o700)


# --- the secret ------------------------------------------------------------------------------------------------------------------------

def secret_resolver():
    """The workbench's secret resolver, loaded by path (next to this folder's parent first)."""
    if SEAMS["resolver"] is not None:
        return SEAMS["resolver"]
    for path in (HERE.parent / "secrets" / "resolver.py", HERE / "resolver.py"):
        if path.is_file():
            spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
    raise Refusal("no_key", "providers/secrets/resolver.py is not in the workbench")


def find_secret(src):
    """(value, where) of the source's key, found only through the resolver; ("", "") for a source that needs none. `where` says where it was found
    (never the value). no_key (exit 3) when it is not found, is not registered or holds a character a header cannot carry."""
    if src["secret_in"] == "none":
        return "", ""
    name = src["secret"]
    resolver = secret_resolver()
    try:
        found = resolver.resolve(name)
    except KeyError:
        raise Refusal("no_key", "%s is not registered in the secret resolver" % name) from None
    except Exception:         # a locked store, an unsafe folder: the resolver's text is never kept
        raise Refusal("no_key", "the secret resolver could not answer for %s" % name) from None
    if not found or not found[0]:
        raise Refusal("no_key", "no key: set %s (contracts/secrets.md)" % name)
    value = found[0]
    if any(ch.isspace() or not ch.isprintable() or not ch.isascii() for ch in value):
        raise Refusal("no_key", "the key of %s has a character a request cannot carry" % name)
    return value, found[1]


# --- the verbs -------------------------------------------------------------------------------------------------------------------------

def _url(src, path, params, key=None, key_param=None):
    query = dict(params)
    if key is not None and key_param:
        query[key_param] = key
    return "https://%s%s%s" % (src["api"]["host"], path, "?" + urllib.parse.urlencode(sorted(query.items())) if query else "")


def _api(impl, src, path, params, cache_parts, environ):
    """(answer, requests, cached): the cached answer, or one API call with the key in the header or the query, cached when the source allows."""
    seconds = src["cache_seconds"]
    key = cache_key(impl.SOURCE, *cache_parts)
    hit = cache_get(impl.SOURCE, key, seconds, environ)
    if hit is not None:
        return hit, 0, True
    secret, _ = find_secret(src)
    headers, extra = impl.auth(src, secret) if secret else ({}, {})
    in_url = src["secret_in"] == "query"
    if secret and (bool(headers) == in_url or bool(extra) != in_url):
        raise Refusal("source_not_ready", "the source file says the key goes in the %s and the implementation puts it elsewhere" % src["secret_in"], ["secret_in"])
    url = _url(src, path, dict(params, **extra))
    answer = _net.get_json(url, headers, CAPS["search_bytes"], allowed_hosts=[src["api"]["host"]], timeout=CAPS["search_seconds"])
    cache_put(impl.SOURCE, key, answer, seconds, secret or None, environ)
    return answer, 1, False


def _allow(args, src):
    if src["licence_tier"] == "unverified" and not args.allow_unverified:
        raise Refusal("licence_refused", "a source of the unverified tier is refused unless the project turned that tier on")
    return bool(args.allow_unverified)


def _name(prefix, source, item, kind):
    return "%s-%s-%s%s" % (prefix, source, item, "-clip" if kind == "clip" else "")


def do_check(args, impl, environ):
    src = read_source(args.source_file, args.today, impl.SOURCE, getattr(impl, "SECRET", None))
    _, where = find_secret(src)
    return {"ok": True, "source": impl.SOURCE, "kinds": src["kinds"], "licence_tier": src["licence_tier"], "secret": where or "none"}


def do_search(args, impl, environ):
    src = read_source(args.source_file, args.today, impl.SOURCE, getattr(impl, "SECRET", None))
    kind = args.kind
    if kind not in src["kinds"]:
        raise Refusal("query_refused", "this source does not serve that kind")
    query = check_query(args.query)
    if not 1 <= args.count <= CAPS["max_count"]:
        raise Refusal("query_refused", "the count is 1 to %d" % CAPS["max_count"])
    out = _net.check_out(args.out)
    allow = _allow(args, src)
    per_page = min(CAPS["per_page_max"], args.count * 3)
    path, params = impl.search_request(src, kind, query, per_page)
    answer, requests, cached = _api(impl, src, path, params, ("search", kind, path, sorted(params.items())), environ)
    dropped = {"too_small": 0, "licence": 0, "host": 0, "too_long": 0}
    kept = []
    for raw in impl.read_search(src, kind, answer):
        found, why = candidate(raw, src, kind, impl, allow)
        if found is None:
            dropped[why] += 1
        elif len(kept) < args.count:
            kept.append(found)
    written = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            jobs = [pool.submit(_preview, src, c, out, written) for c in kept]
            results = []
            for job in jobs:
                try:
                    results.append(job.result())
                except Exception:
                    for other in jobs:
                        other.cancel()
                    raise
    except BaseException:
        for name in list(written):
            _unlink(os.path.join(out, name))
        raise
    for found, saved in zip(kept, results):
        found["preview"], found["preview_sha256"] = saved["file"], saved["sha256"]
        found.pop("_preview_url")
    return {"ok": True, "source": impl.SOURCE, "kind": kind, "candidates": kept, "dropped": dropped, "requests": requests, "cached": cached,
            "previews": len(kept)}


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _preview(src, cand, out, written):
    dest = os.path.join(out, _name("prev", src["source"], cand["item"], cand["kind"]))
    got = _net.download(cand["_preview_url"], CAPS["preview_bytes"], dest, PREVIEW_TYPES, allowed_hosts=src["media_hosts"],
                        redirect_hosts=src["redirect_hosts"], path_pattern=src["_patterns"]["preview"], timeout=CAPS["search_seconds"])
    written.append(os.path.basename(got["file"]))
    return {"file": os.path.basename(got["file"]), "sha256": got["sha256"]}


def do_fetch(args, impl, environ):
    src = read_source(args.source_file, args.today, impl.SOURCE, getattr(impl, "SECRET", None))
    kind = args.kind
    if kind not in src["kinds"]:
        raise Refusal("query_refused", "this source does not serve that kind")
    if not ITEM.fullmatch(args.item or ""):
        raise Refusal("query_refused", "the item is an id the library gave")
    if not isinstance(args.max_bytes, int) or args.max_bytes <= 0:
        raise Refusal("query_refused", "--max-bytes is a positive number")
    out = _net.check_out(args.out)
    allow = _allow(args, src)
    path, params = impl.item_request(src, kind, args.item)
    answer, requests, cached = _api(impl, src, path, params, ("item", kind, path, sorted(params.items())), environ)
    raw = impl.read_item(src, kind, answer)
    if not isinstance(raw, dict):
        raise Refusal("status", "the library's answer holds no such item")
    if raw.get("item") != args.item:
        raise Refusal("status", "the library's answer is for another item")
    found, why = candidate(raw, src, kind, impl, allow)
    if found is None:
        raise Refusal({"licence": "licence_refused", "host": "host_refused"}.get(why, "status"), "the item fails the %s check" % why)
    cap = min(args.max_bytes, CAPS[kind + "_bytes"])
    dest = os.path.join(out, _name("full", src["source"], args.item, kind))
    got = _net.download(raw["file_url"], cap, dest, TYPES[kind], allowed_hosts=src["media_hosts"], redirect_hosts=src["redirect_hosts"],
                        path_pattern=src["_patterns"][kind], timeout=CAPS[kind + "_seconds"])
    return {"ok": True, "source": impl.SOURCE, "item": args.item, "kind": kind, "file": os.path.basename(got["file"]), "bytes": got["bytes"],
            "sha256": got["sha256"], "licence": found["licence"], "author": found["author"], "title": found["title"], "page": found["page"],
            "seconds": found["seconds"], "requests": requests}


def parser(impl) -> argparse.ArgumentParser:
    doc = (impl.__doc__ or "").strip() or "A stock:media implementation."
    p = argparse.ArgumentParser(prog=os.path.basename(getattr(impl, "__file__", impl.SOURCE + ".py")), description=doc, allow_abbrev=False,
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Exit codes: 0 ok, 1 failed, 2 usage, 3 not configured. Every refusal prints {\"ok\": false, \"code\": <closed word>} on stdout.")
    p.add_argument("--check", action="store_true", help="the source file ready and its key found (printed as where, never the value)")
    p.add_argument("--source-file", required=False, help="providers/stock/sources/<name>.json")
    p.add_argument("--today", help="YYYY-MM-DD from `date +%%F`, never from memory")
    sub = p.add_subparsers(dest="verb")
    s = sub.add_parser("search", allow_abbrev=False, help="one API call (or the cache), then the preview of each candidate")
    s.add_argument("--kind", required=True, choices=KINDS)
    s.add_argument("--query", required=True, help="1 to 6 words, ASCII letters")
    s.add_argument("--count", type=int, default=CAPS["max_count"], help="candidates, 1 to %d" % CAPS["max_count"])
    s.add_argument("--out", required=True, help="a folder of this user, mode 0700, not inside a reference store")
    s.add_argument("--jobs", type=int, default=DEFAULT_JOBS, help="previews downloaded at once")
    s.add_argument("--allow-unverified", action="store_true", help="the project turned the unverified tier on")
    f = sub.add_parser("fetch", allow_abbrev=False, help="the full file of one item (the file's URL is read from the library's own answer)")
    f.add_argument("--kind", required=True, choices=KINDS)
    f.add_argument("--item", required=True, help="the item id a search answered")
    f.add_argument("--out", required=True, help="a folder of this user, mode 0700, not inside a reference store")
    f.add_argument("--max-bytes", type=int, required=True)
    f.add_argument("--allow-unverified", action="store_true", help="the project turned the unverified tier on")
    return p


def run(impl, argv=None, environ=None, out=None, err=None) -> int:
    """The verbs of an implementation: prints one JSON object on `out` and returns the exit code. A usage error is argparse's (exit 2, stdout empty)."""
    out, err = out or sys.stdout, err or sys.stderr
    environ = os.environ if environ is None else environ
    args = parser(impl).parse_args(argv)
    if bool(args.check) == bool(args.verb) or not args.source_file or not args.today:
        err.write("usage: --check, or search, or fetch, with --source-file and --today\n")
        return 2
    args_ok = _pin(args, impl)
    verb = do_check if args.check else (do_search if args.verb == "search" else do_fetch)
    try:
        if args_ok is not None:
            raise args_ok
        answer = verb(args, impl, environ)
        text = json.dumps(answer, sort_keys=True, allow_nan=False)
    except Refusal as stop:
        return _refuse(out, err, impl, stop.code, stop.reason, stop.fields, stop.exit_code)
    except _net.NetError as stop:
        return _refuse(out, err, impl, stop.code, stop.code, [], EXIT.get(stop.code, 1))
    except (RecursionError, ValueError, TypeError, KeyError, AttributeError, IndexError):      # a shape of the answer nobody foresaw: a bad answer, no text kept
        return _refuse(out, err, impl, "status", "the library's answer could not be read", [], 1)
    except Exception:          # anything else (a disk, a resolver): a fixed refusal, never the exception's text, which could hold a URL or a key
        return _refuse(out, err, impl, "network", "the verb failed", [], 1)
    out.write(text + "\n")
    return 0


def _pin(args, impl):
    try:
        pin_source(args.source_file, impl)
    except Refusal as stop:
        return stop
    return None


def _refuse(out, err, impl, code, reason, fields, exit_code) -> int:
    out.write(json.dumps({"ok": False, "code": code, "fields": fields}, sort_keys=True) + "\n")
    err.write("%s: %s\n" % (impl.SOURCE, reason))
    return exit_code
