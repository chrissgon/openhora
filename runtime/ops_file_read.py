#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Find and read a file by words of its name under the folders the project lists for the person's own accounts, subfolders included (slices S8 and S17): `file-read`, a class R operation.

  file_read(project, file, [account], [channel, sender])   the operation (the typed command, the page, a messaging app): {"status", ...}, below
  reply(project, ctx, args, said, channel, sender, extras) the reply a line in words gets (runtime/ops_natural.py `run` calls it for `file-read`)
  take(project, ctx, said, channel, sender, extras)        the reply to a bare number said right after a list of files ("o 2"), or None (runtime/ops_natural.py `take`)
  begin_turn(ctx, channel, sender)                         called at the start of every line (runtime/ops_say.py): a list is valid for the line right after it

What it searches, and nothing else (S8, widened by S17): the folders under `accounts.<google|microsoft>.folders` of the project's configuration (project_config `account_target`
is the rule of every write; this is the rule of this read) AND THEIR SUBFOLDERS, walked breadth first through the providers' `children` (one folder's direct contents; the
providers add nothing and no new scope): at most MAX_DEPTH levels below a configured folder, MAX_ITEMS items listed and MAX_SECONDS seconds in all, and a search that was cut
says so. A folder is only ever reached from a configured one, so a file outside the listed folders is never listed, never named and never read, whatever the token could reach.
Both accounts are searched unless the line names one ("do google drive", "no onedrive"); a folder named in the line ("da pasta /openhora") narrows the search to it and what is under
it, and a folder that is not under a configured one is refused in one sentence.

The match (S17): the name span is cut into the words code folds as every name of the platform is (`natural.normal`: case, accents, punctuation), and a file fits when every word
occurs in its name (the extension optional; a typed extension must be the file's when the file has one). A file whose whole name is the span (S8's rule) wins over files that only
contain its words. One match is read; several are listed (a number, name, folder path, account) and the sender's next line "o 2" picks one (`take`, below); none gets one sentence
naming the configured folders searched, by the names the configuration gives them (never an id or a path), and that their subfolders were included.

The read goes through the providers of `integration:documents` that already read the files of a source (`sources.drive_call`, `sources_onedrive.onedrive_call`: `read`,
with `children` for the listing), the same intake, the same converter and the same credential scan (limit L14) as a source, and registers nothing: no source, no version,
no catalog row, no copy. The bytes live in a private staging folder for the length of the call and are removed. The text is cut at TEXT_MAX characters and the reply says
how many remain.

What is kept (limits L50, L61 and L63): the conversation stores a neutral word for the reply (`extras["stored"]`) and the interpreter stores the line as a neutral word, so
the file's text, its name and the folder's name are in the reply to the chat that asked and nowhere else; nothing here logs, prints or stores a name, a folder or a text, and a
provider's failure is a fixed sentence (its text is another service's). The one thing held is the list a pick answers: the ids, names and folder paths of the files a list showed,
in the process's memory for the sender's next line (LIST_WINDOW_S at most), dropped by that line whatever it is; nothing of it is written, logged or sent. No model ever reads the file: the interpreter decides the operation and the name from the person's
line alone. A question about the file is NOT answered from it: the answer from sources (`ask`) reads registered sources only, and this slice registers none, so the text is shown.

Sibling of runtime/ops.py, which exposes `file_read` under its name. The shared names come from ops_core, read as `core.<name>`. Standard library only. Runs on Python 3.9:
python3 runtime/ops_file_read.py --help
"""
from __future__ import annotations

import concurrent.futures
import importlib
import os
import re
import secrets
import shutil
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intake  # noqa: E402
import natural  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import operations  # noqa: E402
import phone_refusal  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import sources  # noqa: E402
import sources_onedrive  # noqa: E402

MAX_DEPTH = 5            # levels of subfolders walked below a configured folder (S17)
MAX_ITEMS = 2000         # items listed in all before the walk stops (S17)
MAX_SECONDS = 10.0       # seconds the walk may take in all (S17)
LABEL_MAX = 120          # characters of a folder's or file's name that are kept
LIST_WINDOW_S = 600      # seconds after a list of files in which a bare number picks one
PATH_JOIN = " › "        # between the names of the folders of a path, as the reply shows it
REST_MAX = 12            # words after a word for "folder" that may name it
FOLDER_WORDS = {"pasta", "folder", "directory", "carpeta", "dossier", "repertoire", "ordner", "verzeichnis", "cartella"}      # the closed words for "folder" a line may be written with  # validate: allow english-only -- the closed words of the languages a line may be written in
TEXT_MAX = 3500          # characters of a file's text shown in one reply (this slice's choice: a messaging app's message holds 4,096)
LIST_MAX = 8             # matches listed when several files carry the name
FOLDER_TOP = 200         # items one folder's listing asks for (the providers' own ceiling)
WORKERS = 4              # folders listed at the same time
SERVICES = ("google", "microsoft")
SERVICE_PHRASE = {"google": "FR_GOOGLE", "microsoft": "FR_MICROSOFT"}
EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
CONTENT = "content"      # the name of the file a provider writes in its --out-dir

provider_call = None     # a test replaces it: call(cls, verb, args, root=, implementation=, timeout=, env=) -> dict, as providers/resolve.py `call`
clock = time.monotonic   # a test replaces it: seconds, as time.monotonic
converter = None         # a test replaces it: convert(input_path, subtype, out_dir) -> info; None is the provider of converter:document


class Unreadable(Exception):
    """The file cannot be shown; `code` is one of "kind", "size", "secret", "empty", "service"."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- the search --------------------------------------------------------------------------------------------------------------------------------


def _stem(name: str) -> str:
    return EXTENSION.sub("", name)


def _ending(name: str) -> str:
    found = EXTENSION.search(name)
    return natural.normal(found.group(0)) if found else ""


def _same_name(wanted: str, found: str) -> bool:
    """Whether a file called `found` is the one the person called `wanted`: the names are equal once folded, and the extension is optional (a name typed with its
    ending also matches a file that has none, as a Google Doc has none). Never a part of a name."""
    asked, asked_stem, name, name_stem = natural.normal(wanted), natural.normal(_stem(wanted)), natural.normal(found), natural.normal(_stem(found))
    if not asked or not name:
        return False
    if _stem(wanted) == wanted:      # typed without an ending: the file's ending is optional
        return asked in (name, name_stem)
    return asked == name or (_stem(found) == found and asked_stem == name)


def _fits(wanted: str, found: str) -> bool:
    """Whether a file called `found` fits the words of `wanted`: every word of the span, folded, occurs in the name's stem (a part of a word counts: "contrat" fits "Contrato de
    locacao"). An ending typed in the span must be the file's ending, or the file has none (a Google Doc has none)."""
    words = natural.normal(_stem(wanted)).split()
    if not words:
        return False
    if _stem(wanted) != wanted and _stem(found) != found and _ending(wanted) != _ending(found):
        return False
    name = natural.normal(_stem(found))
    return bool(name) and all(word in name for word in words)


def _children(cfg: dict, service: str, ident: str, timeout=None) -> dict:
    """{"items": [...], "truncated": bool} of one folder (a configured one or a subfolder found under it), through the provider of the service (`children`). Any failure is an exception for the caller to count."""
    extra = {} if timeout is None else {"timeout": timeout}
    if service == "google":
        got = sources.drive_call(cfg, "children", ["--id", ident, "--top", str(FOLDER_TOP)], call=provider_call, **extra)
    else:
        where = ["--path", ident] if ident.startswith("/") else ["--folder-id", ident]
        got = sources_onedrive.onedrive_call(cfg, "children", where + ["--top", str(FOLDER_TOP)], call=provider_call, **extra)
    items = got.get("items")
    if not isinstance(items, list):
        raise ValueError("the provider's list is not one this runtime reads")
    return {"items": [i for i in items if isinstance(i, dict)], "truncated": bool(got.get("truncated"))}


def _label(text) -> str:
    return " ".join(str(text).split())[:LABEL_MAX]


def _walk(cfg: dict, account=None) -> dict:
    """The tree under the configured folders, breadth first: {"roots": [(service, folder name)], "files": [{"service", "path", "id", "name", "supported"}], "dirs": [(service,
    path)], "failed": folders that could not be listed, "truncated": folders listed in part, "cut": the first limit that stopped the walk or None ("depth", "items", "time")}. `path`
    is the tuple of folder names from the configured folder's own name down. A folder is listed only when it is a configured one or an item of kind folder found in a folder
    that was listed; the limits are MAX_DEPTH, MAX_ITEMS and MAX_SECONDS (read from the module at call time)."""
    services = [account] if account in SERVICES else list(SERVICES)
    jobs = [(service, name, ident) for service in services for name, ident in ((project_config.account_entry(cfg, service) or {}).get("folders") or {}).items()]
    out = {"roots": [(service, name) for service, name, _ in jobs], "files": [], "dirs": [], "failed": 0, "truncated": 0, "cut": None}
    started = clock()
    frontier = [(service, ident, (name,), 0) for service, name, ident in jobs]
    reached = {(service, ident) for service, _, ident in jobs}
    walked = 0

    def one(node, timeout):
        try:
            return _children(cfg, node[0], node[1], timeout)
        except Exception:      # noqa: BLE001 - a provider's failure is another service's text: it is counted, never kept
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        while frontier:
            level, frontier = frontier, []
            for at in range(0, len(level), WORKERS):
                left = MAX_SECONDS - (clock() - started)
                if left <= 0 or walked >= MAX_ITEMS:
                    out["cut"] = out["cut"] or ("time" if left <= 0 else "items")
                    break
                chunk = level[at:at + WORKERS]
                for node, got in zip(chunk, list(pool.map(lambda n: one(n, max(1, int(left) + 1)), chunk))):
                    service, _, path, depth = node
                    out["dirs"].append((service, path))
                    if got is None:
                        out["failed"] += 1
                        continue
                    out["truncated"] += 1 if got["truncated"] else 0
                    walked += len(got["items"])
                    for item in got["items"]:
                        ident, label = item.get("id"), item.get("name")
                        if not isinstance(ident, str) or not isinstance(label, str):
                            continue
                        if item.get("kind") == "file":
                            out["files"].append({"service": service, "path": path, "id": ident, "name": _label(label), "supported": item.get("supported") is True})
                        elif item.get("kind") == "folder" and (service, ident) not in reached:
                            reached.add((service, ident))
                            if depth + 1 > MAX_DEPTH:
                                out["cut"] = out["cut"] or "depth"
                            else:
                                frontier.append((service, ident, path + (_label(label),), depth + 1))
    return out


# --- the line's account and folder ------------------------------------------------------------------------------------------------------------


def _phrases(tables, account: str) -> list:
    from natural_writes import listed      # at call time: the closed lists of the language tables
    return [tuple(natural.normal(p).split()) for p in listed(tables, "services", account)]


def _pieces(said: str, wanted: str) -> list:
    """The folded words of the line in the pieces around the name span (the span itself is left out: a name that holds "drive" or "pasta" names no account and no folder)."""
    words, asked = natural.normal(said).split(), natural.normal(wanted).split()
    at = next((i for i in range(len(words) - len(asked) + 1) if words[i:i + len(asked)] == asked), None) if asked else None
    return [words] if at is None else [words[:at], words[at + len(asked):]]


def _account_of_line(said: str, wanted: str):
    """`google`, `microsoft` or None: the account the line names outside the name span, by the closed lists of the language tables (`services`): a phrase of two words or more names
    an account alone ("google drive"), one word needs a word that introduces it ("no onedrive", "do drive"). Both accounts, or neither, are None (both are searched)."""
    from event_lookup import LEADS      # the words that introduce an account, as the calendar's reading uses them (S11)
    tables = natural._tables(None)
    found = set()
    for account in SERVICES:
        for phrase in _phrases(tables, account):
            n = len(phrase)
            for words in _pieces(said, wanted):
                for i in range(len(words) - n + 1):
                    if tuple(words[i:i + n]) == phrase and (n >= 2 or (i and words[i - 1] in LEADS)):
                        found.add(account)
    return next(iter(found)) if len(found) == 1 else None


def _folder_of_line(said: str, wanted: str):
    """(rest, whole) for the folder a line names, or None. A word for "folder" followed by a path with a slash ("da pasta /openhora/2026") gives the folded names of the path and
    whole=True: all of them must be a folder's path. A word for "folder" followed by words gives the folded words after it, as one string, and whole=False: which of them are the
    name is decided against the folders the walk found (`_named_dirs`), so a name of several words needs no quotes."""
    bare = re.sub(re.escape(wanted), " ", said, flags=re.IGNORECASE)
    path = re.search(r"(?<!\w)(?:" + "|".join(sorted(FOLDER_WORDS)) + r")\s+\"?([^\s\"]*/[^\s\"]*)", bare, flags=re.IGNORECASE)
    if path:
        names = [natural.normal(n) for n in path.group(1).split("/")]
        return " ".join(n for n in names if n), True
    for words in _pieces(said, wanted):
        for i, word in enumerate(words):
            if word in FOLDER_WORDS and i + 1 < len(words):
                return " ".join(words[i + 1:i + 1 + REST_MAX]), False
    return None


def _embedded(wanted: str):
    """(name, rest) when the span itself ends with a folder phrase ("Plano da pasta coral"), else None: the model may have taken the whole tail as the name."""
    from event_lookup import LEADS
    words = natural.normal(wanted).split()
    for i, word in enumerate(words):
        if i and word in FOLDER_WORDS and i + 1 < len(words):
            head = words[:i]
            while head and head[-1] in LEADS:
                head.pop()
            if head:
                return " ".join(head), (" ".join(words[i + 1:i + 1 + REST_MAX]), False)
    return None


def _named_dirs(tree: dict, rest: str, whole: bool = False) -> list:
    """The folders of the walk the words `rest` name, as (service, path): the longest tail of a folder's path (its own name, or its name with the names above it) that `rest`
    begins with, at a word boundary (with `whole`, that `rest` is exactly); the folders that tie are all kept. Empty when none of the walked folders is named."""
    best, hits = 0, []
    for service, path in tree["dirs"]:
        names = [natural.normal(p) for p in path]
        for k in range(len(names)):
            key = " ".join(n for n in names[k:] if n)
            size = len(key.split())
            if key and (rest == key or (not whole and rest.startswith(key + " "))) and size >= best:
                if size > best:
                    best, hits = size, []
                hits.append((service, path))
                break
    return hits


def _find(tree: dict, wanted: str, folder) -> dict:
    """{"matches": [file records, nearest folders first], "no_folder": bool}: the files of the tree that fit `wanted`, inside the folders `folder` ((rest, whole), see `_folder_of_line`)
    names when it is given (a folder that is none of those walked leaves no match and sets `no_folder`). A file whose whole name is the span wins over the files that only hold its words."""
    inside, no_folder = tree["files"], False
    if folder is not None:
        named = _named_dirs(tree, *folder)
        no_folder = not named
        inside = [f for f in tree["files"] if any(f["service"] == s and f["path"][:len(p)] == p for s, p in named)]
    fits = [f for f in inside if _fits(wanted, f["name"])]
    exact = [f for f in fits if _same_name(wanted, f["name"])]
    key = lambda f: (len(f["path"]), [natural.normal(p) for p in f["path"]], natural.normal(f["name"]), f["service"])  # noqa: E731
    return {"matches": sorted(exact or fits, key=key), "no_folder": no_folder}


def _search(cfg: dict, wanted: str, account=None, said=None) -> dict:
    """{"folders": [(service, folder name)] searched, "matches": [{"service", "folder" (the path, " › " between the names), "id", "name", "supported"}], "failed", "truncated", "cut",
    "no_folder"}. `account` google or microsoft narrows the search to one account; `said` is the line the folder named in it comes from (None: no folder). Only files under the folders
    the configuration lists are returned."""
    tree = _walk(cfg, account)
    out = {"folders": tree["roots"], "matches": [], "failed": tree["failed"], "truncated": tree["truncated"], "cut": tree["cut"], "no_folder": False, "all_failed": False}
    if not tree["roots"]:
        return out
    out["all_failed"] = not tree["files"] and tree["failed"] >= len(tree["roots"])
    tries = [(wanted, _folder_of_line(said, wanted) if said else None)]
    inner = _embedded(wanted)
    if inner:
        tries.append(inner)
    refused = []
    for name, folder in tries:
        got = _find(tree, name, folder)
        if got["matches"]:
            out["matches"] = [{"service": f["service"], "folder": PATH_JOIN.join(f["path"]), "id": f["id"], "name": f["name"], "supported": f["supported"]} for f in got["matches"]]
            return out
        refused.append(got["no_folder"])
    out["no_folder"] = all(refused)          # a folder is refused only when every reading of the line names one that is not under a configured folder
    return out


# --- the read ----------------------------------------------------------------------------------------------------------------------------------


def _read_bytes(cfg: dict, service: str, ident: str, out_dir: str) -> dict:
    args = ["--id", ident, "--as-source", "--out-dir", out_dir, "--max-bytes", str(sources.ORIGINAL_CAP)]
    if service == "google":
        return sources.drive_call(cfg, "read", args, call=provider_call)
    return sources_onedrive.onedrive_call(cfg, "read", args, call=provider_call)


def _read_text(cfg: dict, service: str, ident: str) -> str:
    """The text of one file the search found, as a source's import converts it, and nothing is registered. Unreadable (code) when it cannot be shown."""
    try:
        stage = sources._make_staging(cfg["data_dir"], secrets.token_hex(8))
    except Exception:      # noqa: BLE001
        raise Unreadable("service") from None
    try:
        into, out = os.path.join(stage, "in"), os.path.join(stage, "out")
        try:
            info = _read_bytes(cfg, service, ident, into)
            path = os.path.join(into, CONTENT)
            stream, length, closer = sources._stream_of(path)
            with closer:
                if length > sources.ORIGINAL_CAP:
                    raise Unreadable("size")
                data = stream.read(sources.ORIGINAL_CAP + 1)
        except Unreadable:
            raise
        except Exception:      # noqa: BLE001 - the provider's reason is another service's text; the file is not shown
            raise Unreadable("service") from None
        if len(data) != info.get("bytes") or sources._sha(data) != info.get("sha256"):
            raise Unreadable("service")
        if info.get("content") == "markdown":
            try:
                text = sources.strip_embedded_images(data.decode("utf-8"))[0]
            except UnicodeDecodeError:
                raise Unreadable("kind") from None
            converted = text.encode("utf-8")
        else:
            converted = _converted(cfg, data, path, out)
            text = converted.decode("utf-8", "replace")
        if "\x00" in text or not text.strip():
            raise Unreadable("empty" if not text.strip() else "kind")
        if sources._workcopy().scan(converted):      # limit L14: what looks like a credential is never shown
            raise Unreadable("secret")
        return text
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _converted(cfg: dict, data: bytes, path: str, out_dir: str) -> bytes:
    """The text of the bytes a provider wrote: a text or csv file as it is, any other kind through the converter of converter:document (the same container as a source's)."""
    try:
        found = intake.sniff(data[:intake.SNIFF_BYTES])
        sources.accept_type(found)
    except intake.IntakeError:
        raise Unreadable("kind") from None
    subtype = found[1]
    if subtype in ("text", "csv"):
        return data[3:] if data[:3] == b"\xef\xbb\xbf" else data
    try:
        (converter or sources.provider_convert(cfg))(path, subtype, out_dir)
        done = sources.collect_outputs(out_dir)
    except Exception:      # noqa: BLE001 - the converter's reason is not kept
        raise Unreadable("service") from None
    names = [n for n in ("converted.md", "converted.csv") if n in done]
    if len(names) != 1:
        raise Unreadable("kind")
    return done[names[0]]


def _cut(text: str) -> tuple:
    """(shown, remaining characters): the text with its newlines normalised, cut at TEXT_MAX on the end of a word, and how many characters were left out."""
    whole = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(whole) <= TEXT_MAX:
        return whole, 0
    head = whole[:TEXT_MAX]
    space = max(head.rfind(" "), head.rfind("\n"))
    if space > TEXT_MAX * 0.8:
        head = head[:space]
    head = head.rstrip()
    return head, len(whole) - len(head)


# --- the operation -----------------------------------------------------------------------------------------------------------------------------


def _read_match(cfg: dict, match: dict) -> dict:
    """The outcome of reading the one file chosen: {"status": "text", ...} | {"status": "unreadable", "name", "account", "why"}."""
    if not match["supported"]:
        return {"status": "unreadable", "name": match["name"], "account": match["service"], "why": "kind"}
    try:
        shown, remaining = _cut(_read_text(cfg, match["service"], match["id"]))
    except Unreadable as e:
        return {"status": "unreadable", "name": match["name"], "account": match["service"], "why": e.code}
    return {"status": "text", "name": match["name"], "folder": match["folder"], "account": match["service"], "text": shown, "remaining": remaining}


def _find_and_read(cfg: dict, wanted: str, account=None, said=None) -> dict:
    """The outcome of one request, as data: {"status": "no-folders"} | {"status": "none", "folders", "failed", "truncated", "cut"} | {"status": "no-folder", "folders", "cut"} |
    {"status": "several", "matches", "count", "refs"} | {"status": "text", ...} | {"status": "unreadable", ...} | {"status": "unavailable"}. `refs` (the ids the pick "o 2" reads) never
    leave this module's callers: the typed operation drops it."""
    found = _search(cfg, wanted, account, said)
    if not found["folders"]:
        return {"status": "no-folders"}
    matches = found["matches"]
    if not matches:
        if found["no_folder"]:
            return {"status": "no-folder", "folders": found["folders"], "cut": found["cut"]}
        if found["all_failed"]:
            return {"status": "unavailable"}
        return {"status": "none", "folders": found["folders"], "failed": found["failed"], "truncated": found["truncated"], "cut": found["cut"]}
    if len(matches) > 1:
        shown = matches[:LIST_MAX]
        return {"status": "several", "matches": [{k: m[k] for k in ("name", "folder", "service")} for m in shown], "count": len(matches), "refs": shown, "cut": found["cut"]}
    return _read_match(cfg, matches[0])


def file_read(project: str, file: str, account: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """The operation `file-read`. From a messaging app the sender's profile must hold the group `read-files` (the sentence the bridge uses otherwise); the page and the
    terminal follow the table of operations. Returns find_and_read's outcome (the subfolders of the configured folders are searched; the typed operation names no folder)."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "file-read", channel, sender)
    if not isinstance(file, str) or not natural.normal(file) or len(file) > natural.SPAN_MAX:
        raise core.OpsError("--file is the name of a file (1 to 300 characters)", 2)
    if account is not None and account not in SERVICES:
        raise core.OpsError("--account is google or microsoft", 2)
    return {k: v for k, v in _find_and_read(ctx["cfg"], file, account).items() if k != "refs"}


# --- the list a pick answers ("o 2") ---------------------------------------------------------------------------------------------------------------

_LISTS = {}          # (project key, channel, sender) -> {"at", "items": [match], "seen", "pending"}: in process memory only, for the next line; never written, logged or sent anywhere
_lock = threading.Lock()


def forget_lists() -> None:
    """Drop every record (a test, and a process that stops)."""
    with _lock:
        _LISTS.clear()


def _natural():
    return importlib.import_module("ops_natural")


def _slot(ctx: dict, channel, sender) -> tuple:
    return (_natural().project_key(ctx["cfg"]["project"]), channel, sender or "")


def _remember(ctx: dict, channel, sender, items: list) -> None:
    now = _natural()._clock()
    with _lock:
        for old in [k for k, v in _LISTS.items() if (now - v["at"]).total_seconds() > LIST_WINDOW_S]:
            del _LISTS[old]
        _LISTS[_slot(ctx, channel, sender)] = {"at": now, "items": list(items), "seen": 0, "pending": importlib.import_module("event_lookup")._last_pending(ctx)}


def _drop(ctx: dict, channel, sender) -> None:
    with _lock:
        _LISTS.pop(_slot(ctx, channel, sender), None)


def begin_turn(ctx: dict, channel, sender) -> None:
    """Called by `ops_say.say` at the start of every line of a messaging sender: the list is valid only for the line right after it (as the list of events is, S11)."""
    if channel == "messaging":
        with _lock:
            found = _LISTS.get(_slot(ctx, channel, sender))
            if found is not None:
                found["seen"] += 1


def _live(ctx: dict, channel, sender):
    now = _natural()._clock()
    with _lock:
        found = _LISTS.get(_slot(ctx, channel, sender))
    if found is not None and ((now - found["at"]).total_seconds() > LIST_WINDOW_S or found["seen"] > 1 or importlib.import_module("event_lookup")._last_pending(ctx) > found["pending"]):
        _drop(ctx, channel, sender)
        return None
    return found


def take(project: str, ctx: dict, said: str, channel, sender, extras: dict):
    """The reply to a number said right after a list of files ("o 2", "2", "the 2nd"), or None when the line is not one (no live list for this sender, a line that is no bare
    number, a number the list did not show). Any line ends the list, so a pick is used once. The sender's right to read files is asked again; the file is read as `reply` reads it."""
    if channel != "messaging":
        return None
    record = _live(ctx, channel, sender)
    if record is None:
        return None
    _drop(ctx, channel, sender)
    form = importlib.import_module("event_lookup")._number_form(said)          # the closed number forms of S11: "o 2", "#2", "the 2nd"; a verb with it is not a pick
    if form is None or form["verb"] is not None or not 1 <= form["n"] <= len(record["items"]):
        return None
    cfg = ctx["cfg"]
    refused = operations.refusal("file-read", "messaging", cfg["channels"], sender=sender)
    if refused:
        return phone_refusal.said(refused, channel, cfg)
    extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    return _render(cfg, _read_match(cfg, record["items"][form["n"] - 1]))


# --- the reply to a line in words ---------------------------------------------------------------------------------------------------------------


def _service_of(word):
    """`google` or `microsoft` for a word the language tables list for exactly one service ("onedrive", "drive", "google drive"), or None; a typed `google` or `microsoft` is itself."""
    if word in SERVICES:
        return word
    folded = natural.ascii_normal(str(word))
    from natural_writes import listed      # at call time: the closed lists of the language tables
    hits = [s for s in SERVICES if folded in listed(natural._tables(None), "services", s)]
    return hits[0] if len(hits) == 1 else None


def _label_of(cfg: dict, service: str) -> str:
    return phrases.text(SERVICE_PHRASE[service], cfg)


def _render(cfg: dict, got: dict) -> str:
    """The sentence a chat is told for an outcome of find_and_read, in the project's language."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    status = got["status"]
    if status == "text":
        head = t("FR_HEAD", name=got["name"], account=_label_of(cfg, got["account"]), folder=got["folder"])
        more = "\n\n" + t("FR_MORE", remaining=got["remaining"]) if got["remaining"] else ""
        return f"{head}\n\n{got['text']}{more}"
    if status == "several":
        rows = [t("FR_ITEM", n=n, name=m["name"], folder=m["folder"], account=_label_of(cfg, m["service"])) for n, m in enumerate(got["matches"], 1)]
        return "\n".join([t("FR_SEVERAL_PICK", count=got["count"])] + rows + ([t("FR_CUT")] if got.get("cut") else []))
    if status in ("none", "no-folder"):
        folders = ", ".join(t("FR_FOLDER", folder=folder, account=_label_of(cfg, service)) for service, folder in got["folders"])
        partial = " " + t("FR_PARTIAL") if status == "none" and (got["truncated"] or got["failed"]) else ""
        cut = " " + t("FR_CUT") if got.get("cut") else ""
        return t("FR_NONE_SUB" if status == "none" else "FR_NO_SUCH_FOLDER", folders=folders) + partial + cut
    if status == "unreadable":
        return t({"secret": "FR_WITHHELD", "size": "FR_TOO_BIG", "empty": "FR_EMPTY"}.get(got["why"], "FR_UNREADABLE"), name=got["name"], account=_label_of(cfg, got["account"]))
    if status == "no-folders":
        return t("FR_NO_FOLDERS")
    return t("FR_UNAVAILABLE")


def reply(project: str, ctx: dict, args: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply of `file-read` chosen by a tier or by the interpreter (runtime/ops_natural.py `run` has already asked the policy). The name is checked to be a span of the
    line; the service word (when there is one) must name exactly one service and agree with the account the line itself names ("do google drive"); a folder named in the line
    narrows the search. Else the fixed ask-again sentence and nothing is listed. The conversation keeps a neutral word."""
    cfg = ctx["cfg"]
    extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    wanted = args.get("file")
    word = args.get("account")
    if not isinstance(wanted, str) or not natural.normal(wanted) or natural.normal(wanted) not in natural.normal(said) or len(wanted) > natural.SPAN_MAX:
        return phrases.text("IX_ASK_AGAIN", cfg)
    named = _account_of_line(said, wanted)
    account = _service_of(word) if word else named
    if word and (account is None or (named and named != account)):
        return phrases.text("IX_ASK_AGAIN", cfg)
    got = _find_and_read(cfg, wanted, account, said)
    if got["status"] == "several" and channel == "messaging":
        _remember(ctx, channel, sender, got["refs"])
    return _render(cfg, got)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
