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

The folder as the person sees it (S17b): a folder named in the line ("da pasta /openhora", "in the folder openhora") is matched from any folder the walk reached, with or without slashes, case and
accents folded, and never through the alias the configuration gives a folder; a configured folder is also meant by its real name (a Google folder's through one `stat` of its id per search, a
OneDrive path's last name) and by the alias. A folder none of the walked ones carries does not stop the search: the file is looked for in all of them and the reply adds a note; a path that points
outside (`..`, the root, an item id) is refused and nothing is listed. Every reply names a folder by its real name (the service's own name when it could not be read), never the alias.

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

The file itself (S18): when the sender holds the group `send-files` (beside `read-files`) and the bridge says the messaging app can carry a file (`extras["can_send"]`, the messenger's
capabilities: the most it takes, the most it takes as a photo, the image types it shows as a photo, the types it takes), the reply of a found file carries the file as
`extras["attachment"]` = {"name", "kind": "photo" | "document", "data"}: a photo for a jpeg or png image under the photo limit, a document otherwise. A readable text file keeps today's
preview as the message text. Before it, in code: the right and the folder grant are asked again (a pick reads the configuration in force now), the size and the type are checked against
what the app takes (a file over the limit gets one sentence, and the preview when it has text), and the text of every file the converter turns into text, a PDF or an Office file
included, passes the credential scan (limit L14): a hit withholds the file AND the preview. A file with no text to scan (an image, or a document the converter gives no text for) is sent
as it is (its bytes pass `runtime/send_scan.py`: a credential in the raw bytes of a text file, in any XML part of an Office package, or in a PDF's strings or inflated streams withholds the file, and so does a
package with an embedding or a PDF it cannot read to the end). The bytes live in memory for the length of the call and then in the bridge's one temporary file for the length of the send (runtime/messaging_bridge.py); nothing is
stored, logged or kept here, and the neutral word the conversation keeps is the same. Without the group, or on a page or a terminal, nothing changes: the reply is the text it always was.

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
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intake  # noqa: E402
import line_stage  # noqa: E402
import natural  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import operations  # noqa: E402
import phone_refusal  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import send_scan  # noqa: E402
import sources  # noqa: E402
import sources_onedrive  # noqa: E402

MAX_DEPTH = 5            # levels of subfolders walked below a configured folder (S17)
MAX_ITEMS = 2000         # items listed in all before the walk stops (S17)
MAX_SECONDS = 10.0       # seconds the walk may take in all (S17)
LABEL_MAX = 120          # characters of a folder's or file's name that are kept
LIST_WINDOW_S = 600      # seconds after a list of files in which a bare number picks one
PATH_JOIN = " › "        # between the names of the folders of a path, as the reply shows it
REST_MAX = 12            # words after a word for "folder" that may name it
ROOT_NAME_SECONDS = 2.0  # seconds the read of the configured folders' real names may take (S17b); a name not back is the service's name
ID_LIKE = re.compile(r"(?=[^0-9]*[0-9])(?=[^A-Za-z]*[A-Za-z])[A-Za-z0-9_!-]{20,}")      # a Drive or OneDrive item id: a long run of letters and digits with both
GENERIC = {"drive"}      # a word for a cloud folder that names no service
FOLDER_WORDS = {"pasta", "folder", "directory", "carpeta", "dossier", "repertoire", "ordner", "verzeichnis", "cartella"}      # the closed words for "folder" a line may be written with  # validate: allow english-only -- the closed words of the languages a line may be written in
TEXT_MAX = 3500          # characters of a file's text shown in one reply (this slice's choice: a messaging app's message holds 4,096)
LIST_MAX = 8             # matches listed when several files carry the name
FOLDER_TOP = 200         # items one folder's listing asks for (the providers' own ceiling)
WORKERS = 4              # folders listed at the same time
SERVICES = ("google", "microsoft")
SERVICE_PHRASE = {"google": "FR_GOOGLE", "microsoft": "FR_MICROSOFT"}
EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
CONTENT = "content"      # the name of the file a provider writes in its --out-dir
SEND_GROUP = "send-files"      # S18: the group that lets the file itself leave with the reply
PHOTO = "photo"          # the kind of attachment the messenger sends as a photo; every other is a "document"
EXTENSIONS = {"pdf": "pdf", "docx": "docx", "xlsx": "xlsx", "pptx": "pptx", "html": "html", "csv": "csv", "text": "txt", "png": "png", "jpeg": "jpg", "webp": "webp", "gif": "gif"}      # the ending a sent file gets when its name has none (a Google Doc has none)

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


def _root_name(cfg: dict, service: str, ident: str, timeout):
    """The real name of a configured folder, as the person sees it, or None. Google: `stat` of the folder id (one GET; "root" is the person's Drive); OneDrive: the last name of the
    configured path (`/Documentos` -> Documentos), no call; a OneDrive id has no name here. A failure is None: the service's own name is shown instead."""
    if service == "google":
        if ident == "root":
            return phrases.text("FR_DRIVE_ROOT", cfg)
        try:
            name = sources.drive_call(cfg, "stat", ["--id", ident], call=provider_call, timeout=timeout).get("name")
        except Exception:      # noqa: BLE001 - another service's text is never kept
            return None
        return _label(name) if isinstance(name, str) and name.strip() else None
    names = [part for part in ident.split("/") if part] if ident.startswith("/") else []
    return _label(urllib.parse.unquote(names[-1])) if names else None


def _walk(cfg: dict, account=None, names_only: bool = False, only_root=None) -> dict:
    """The tree under the configured folders, breadth first: {"roots": [(service, real name or None)], "info": {(service, folder id): {"alias", "real", "lead"}], "files": [{"service",
    "path", "root", "id", "name", "supported"}], "dirs": [(service, path, root)], "failed": folders that could not be listed, "truncated": folders listed in part, "cut": the first limit that
    stopped the walk or None ("depth", "items", "time")}. `path` is the tuple of folder names from the configured folder down, the first one the folder's REAL name as the person sees it
    (`lead`: read once from the provider, else the service's own name; the configuration's alias is never shown and only helps to match) and `root` the configured folder's id. With `only_root` (R2-A) only the configured folder with that id is walked. A folder
    is listed only when it is a configured one or an item of kind folder found in a folder that was listed. The limits are MAX_DEPTH, MAX_ITEMS (counted item by item, so the walk stops at the
    item that reaches it, inside a listing too) and MAX_SECONDS (read from the module at call time): each listing is asked with a timeout of at most the time left, and a listing that is not
    back when the time is spent is given up. With `names_only` nothing is listed (a line that is refused still names the folders by their real names)."""
    services = [account] if account in SERVICES else list(SERVICES)
    jobs = [(service, name, ident) for service in services for name, ident in ((project_config.account_entry(cfg, service) or {}).get("folders") or {}).items()
            if only_root is None or ident == only_root]
    out = {"roots": [], "info": {}, "files": [], "dirs": [], "failed": 0, "truncated": 0, "cut": None}
    started = clock()

    def one(node, timeout):
        try:
            return _children(cfg, node[0], node[1], timeout)
        except Exception:      # noqa: BLE001 - a provider's failure is another service's text: it is counted, never kept
            return None
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS)
    try:
        wait = min(ROOT_NAME_SECONDS, MAX_SECONDS / 4)          # the names never take more than a quarter of the time
        asked = {(service, ident): pool.submit(_root_name, cfg, service, ident, wait) for service, _, ident in jobs}
        concurrent.futures.wait(list(asked.values()), timeout=wait)
        for service, alias, ident in jobs:
            future = asked[(service, ident)]
            real = future.result() if future.done() and not future.cancelled() and future.exception() is None else None
            out["info"][(service, ident)] = {"alias": alias, "real": real, "lead": real or _label_of(cfg, service)}
            out["roots"].append((service, real))
        frontier = [(service, ident, (out["info"][(service, ident)]["lead"],), 0, ident) for service, _, ident in jobs]
        reached = {(service, ident) for service, _, ident in jobs}
        walked = 0
        stop = names_only
        while frontier and not stop:
            level, frontier = frontier, []
            for at in range(0, len(level), WORKERS):
                left = MAX_SECONDS - (clock() - started)
                if left <= 0 or walked >= MAX_ITEMS:
                    out["cut"] = out["cut"] or ("time" if left <= 0 else "items")
                    stop = True
                    break
                chunk = level[at:at + WORKERS]
                futures = [pool.submit(one, node, left) for node in chunk]
                done, _ = concurrent.futures.wait(futures, timeout=left)
                for node, future in zip(chunk, futures):
                    got = future.result() if future in done else None
                    if future not in done:
                        out["cut"] = out["cut"] or "time"
                    service, _, path, depth, root = node
                    out["dirs"].append((service, path, root))
                    if got is None:
                        out["failed"] += 1
                        continue
                    out["truncated"] += 1 if got["truncated"] else 0
                    for item in got["items"]:
                        if walked >= MAX_ITEMS:
                            out["cut"] = out["cut"] or "items"
                            stop = True
                            break
                        walked += 1
                        ident, label = item.get("id"), item.get("name")
                        if not isinstance(ident, str) or not isinstance(label, str):
                            continue
                        if item.get("kind") == "file":
                            out["files"].append({"service": service, "path": path, "root": root, "id": ident, "name": _label(label), "supported": item.get("supported") is True,
                                             "size": item.get("size") if type(item.get("size")) is int and item["size"] >= 0 else None, "modified": _label(item.get("modified") or "")})
                        elif item.get("kind") == "folder" and (service, ident) not in reached:
                            reached.add((service, ident))
                            if depth + 1 > MAX_DEPTH:
                                out["cut"] = out["cut"] or "depth"
                            else:
                                frontier.append((service, ident, path + (_label(label),), depth + 1, root))
                    if stop:
                        break
                if stop:
                    break
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
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


def _accounts_of_line(said: str, wanted: str) -> set:
    """The accounts (`google`, `microsoft`) the line names outside the name span, by the closed lists of the language tables (`services`): a phrase of two words or more names an
    account alone ("google drive"), one word needs a word that introduces it ("no onedrive"). The bare word "drive" (GENERIC) names none: it is what a person calls their cloud
    folder, not a service ("do meu drive" is searched in both accounts)."""
    from event_lookup import LEADS      # the words that introduce an account, as the calendar's reading uses them (S11)
    tables = natural._tables(None)
    found = set()
    for account in SERVICES:
        for phrase in _phrases(tables, account):
            n = len(phrase)
            if n == 1 and phrase[0] in GENERIC:
                continue
            for words in _pieces(said, wanted):
                for i in range(len(words) - n + 1):
                    if tuple(words[i:i + n]) == phrase and (n >= 2 or (i and words[i - 1] in LEADS)):
                        found.add(account)
    return found


def _outside(raw: str) -> bool:
    """Whether the token after a word for "folder" clearly points outside the configured folders: a `..` or `.` step, the root of a drive (`/`, `~`), or an item id (a long run of
    letters and digits). Anything else that is not a walked folder is only a name that is not there (`_search` looks everywhere and says so)."""
    parts = [part for part in raw.split("/")]
    return any(part in ("..", ".") for part in parts) or raw.strip("/") == "" or raw.startswith("~") or any(ID_LIKE.fullmatch(part) for part in parts)


def _folder_from(text: str, span: str):
    """{"rest", "whole", "shown", "outside"} for the folder `text` names outside `span`, or None. A word for "folder" followed by a path with a slash ("da pasta /openhora/2026") gives the
    folded names of the path and whole=True: all of them must be the end of a folder's path, from any folder of the walk and never through the configuration's alias. Followed by words it
    gives the folded words after it as one string and whole=False: which of them are the name is decided against the folders the walk found (`_named_dirs`), so a name of several words
    needs no quotes. `shown` is what the reply repeats (the path as typed, or the first word)."""
    bare = re.sub(re.escape(span), " ", text, flags=re.IGNORECASE) if span.strip() else text
    token = re.search(r"(?<!\w)(?:" + "|".join(sorted(FOLDER_WORDS)) + r")\s+\"?([^\s\"]+)", bare, flags=re.IGNORECASE)
    if token is None:
        return None
    raw = token.group(1).rstrip(".,;:!?")
    if _outside(raw):
        return {"rest": "", "whole": True, "shown": raw[:LABEL_MAX], "outside": True}
    if "/" in raw:
        names = [natural.normal(n) for n in raw.split("/")]
        return {"rest": " ".join(n for n in names if n), "whole": True, "shown": raw.strip("/")[:LABEL_MAX], "outside": False}
    for words in _pieces(text, span):
        for i, word in enumerate(words):
            if word in FOLDER_WORDS and i + 1 < len(words):
                return {"rest": " ".join(words[i + 1:i + 1 + REST_MAX]), "whole": False, "shown": raw[:LABEL_MAX], "outside": False}
    return None


def _folder_of_line(said: str, wanted: str):
    return _folder_from(said, wanted)


def _embedded(wanted: str):
    """(name, folder) when the span itself ends with a folder phrase ("Plano da pasta coral"), else None: the model may have taken the whole tail as the name."""
    from event_lookup import LEADS
    words = natural.normal(wanted).split()
    for i, word in enumerate(words):
        if i and word in FOLDER_WORDS and i + 1 < len(words):
            head = words[:i]
            while head and head[-1] in LEADS:
                head.pop()
            folder = _folder_from(wanted, "")
            if head and folder is not None:
                return " ".join(head), folder
    return None


def _named_dirs(tree: dict, folder: dict) -> list:
    """The folders of the walk that the folder named in the line means, as (service, path, root): the longest tail of a folder's names that the words begin with, at a word boundary
    (with `whole`, that they are exactly). A tail is counted from any folder of the walk, so "openhora" and "/openhora" mean a folder "openhora" at any depth and "/openhora/x" the chain
    openhora > x; a configured folder is also meant by its real name or by the alias the configuration gives it, and the alias is never needed. The folders that tie are all kept. Only
    folders the walk reached are looked at. Empty when none is named."""
    rest, whole = folder["rest"], folder["whole"]
    best, hits = 0, []
    for service, path, root in tree["dirs"]:
        info = tree["info"][(service, root)]
        lists = [[natural.normal(p) for p in path], [natural.normal(info["alias"])] + [natural.normal(p) for p in path[1:]]]
        if info["real"]:
            lists.append([natural.normal(info["real"])] + [natural.normal(p) for p in path[1:]])
        for names in lists:
            for k in range(len(names)):
                key = " ".join(n for n in names[k:] if n)
                size = len(key.split())
                if key and (rest == key or (not whole and rest.startswith(key + " "))) and size >= best:
                    if size > best:
                        best, hits = size, []
                    if (service, path, root) not in hits:
                        hits.append((service, path, root))
                    break
    return hits


def _find(tree: dict, wanted: str, folder) -> dict:
    """{"matches": [file records, nearest folders first], "no_folder": bool}: the files of the tree that fit `wanted`, inside the folders `folder` ((rest, whole), see `_folder_of_line`)
    names when it is given (a folder that is none of those walked leaves no match and sets `no_folder`). A file whose whole name is the span wins over the files that only hold its words."""
    inside, no_folder = tree["files"], False
    if folder is not None:
        named = _named_dirs(tree, folder)
        no_folder = not named
        inside = [f for f in tree["files"] if any(f["service"] == s and f["root"] == r and f["path"][:len(p)] == p for s, p, r in named)]
    fits = [f for f in inside if _fits(wanted, f["name"])]
    exact = [f for f in fits if _same_name(wanted, f["name"])]
    key = lambda f: (len(f["path"]), [natural.normal(p) for p in f["path"]], natural.normal(f["name"]), f["service"])  # noqa: E731
    return {"matches": [dict(f, exact=bool(exact)) for f in sorted(exact or fits, key=key)], "no_folder": no_folder}


def _matches_of(found: list) -> list:
    return [{"service": f["service"], "folder": PATH_JOIN.join(f["path"]), "root": f["root"], "id": f["id"], "name": f["name"], "supported": f["supported"],
             "size": f["size"], "modified": f["modified"], "exact": f["exact"]} for f in found]


def _search(cfg: dict, wanted: str, account=None, said=None) -> dict:
    """{"folders": [(service, real folder name or None)] searched, "matches": [{"service", "folder" (the real names, " › " between them), "root", "id", "name", "supported"}], "failed",
    "truncated", "cut", "no_folder", "folder_missing", "incomplete"}. `account` google or microsoft narrows the search to one account; `said` is the line the folder named in it comes from
    (None: no folder). Only files under the folders the configuration lists are returned. A folder named in the line that none of the walked folders carries does not stop the search: the file
    is looked for in the whole walked tree and `folder_missing` is the name the person typed (the reply says so); `no_folder` (a refusal) is only for a folder that points outside, see `_outside`."""
    tries = [(wanted, _folder_of_line(said, wanted) if said else None)]
    inner = _embedded(wanted)
    if inner:
        tries.append(inner)
    outside = tries[0][1] is not None and tries[0][1]["outside"]
    tree = _walk(cfg, account, names_only=outside)
    out = {"folders": tree["roots"], "matches": [], "failed": tree["failed"], "truncated": tree["truncated"], "cut": tree["cut"], "no_folder": False, "all_failed": False,
           "folder_missing": None, "incomplete": bool(tree["cut"] or tree["truncated"] or tree["failed"])}          # a file that fits may be in a part of the folders that was not seen
    if not tree["roots"]:
        return out
    if outside:
        out["no_folder"] = True          # nothing was listed: a path that points outside is not walked
        return out
    out["all_failed"] = not tree["files"] and tree["failed"] >= len(tree["roots"])
    missing = []
    for name, folder in tries:
        got = _find(tree, name, folder)
        if got["matches"]:
            out["matches"] = _matches_of(got["matches"])
            return out
        if folder is not None and got["no_folder"]:
            missing.append(folder)
    if missing and len(missing) == len([1 for _, folder in tries if folder is not None]):          # every reading of the line names a folder the walk did not find: look everywhere, and say so
        for name, _ in tries:
            got = _find(tree, name, None)
            if got["matches"]:
                out["matches"] = _matches_of(got["matches"])
                out["folder_missing"] = missing[0]["shown"]
                return out
    return out


def locate(cfg: dict, service: str, root: str, ident: str):
    """The file with this id under the configured folder with this id, by the same walk the search makes (R2-A: the grant asked again when a file is to be trashed): its record
    ({"service", "folder" (the real names, " › " between them), "root", "id", "name", "size", "modified"}), None when the walk finished and the file is not under that folder, or
    "unproven" when it did not finish (cut, a folder that did not answer) and the file was not met: a file is trashed only when it was seen under the folder."""
    if service not in SERVICES:
        return None
    tree = _walk(cfg, service, only_root=root)
    for f in tree["files"]:
        if f["service"] == service and f["root"] == root and f["id"] == ident:
            return {"service": service, "folder": PATH_JOIN.join(f["path"]), "root": root, "id": ident, "name": f["name"], "size": f["size"], "modified": f["modified"]}
    return "unproven" if tree["cut"] or tree["truncated"] or tree["failed"] or not tree["roots"] else None


# --- the read ----------------------------------------------------------------------------------------------------------------------------------


def _read_bytes(cfg: dict, service: str, ident: str, out_dir: str) -> dict:
    args = ["--id", ident, "--as-source", "--out-dir", out_dir, "--max-bytes", str(sources.ORIGINAL_CAP)]
    if service == "google":
        return sources.drive_call(cfg, "read", args, call=provider_call)
    return sources_onedrive.onedrive_call(cfg, "read", args, call=provider_call)


def _read_text(cfg: dict, service: str, ident: str) -> str:
    """The text of one file the search found, as a source's import converts it, and nothing is registered. Unreadable (code) when it cannot be shown."""
    return _read(cfg, service, ident)["text"]


def _read(cfg: dict, service: str, ident: str, send=None) -> dict:
    """{"text", "data", "type", "markdown"} of one file the search found: its text as a source's import converts it (None when there is none to show), and, with `send` (S18: the
    messenger's limits), the file's bytes and its type (kind, subtype) read from them. Nothing is registered. Unreadable (code) when it cannot be shown or sent: "kind" (a type
    that is not read, or not on the list the app takes), "size", "secret" (limit L14: the text looks like a credential: neither is shown), "empty" (no text, without `send`), "service"."""
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
        found = intake.sniff(data[:intake.SNIFF_BYTES])
        if send is not None:
            if info.get("content") == "markdown":
                found = ("document", "text")
            elif found is not None and found[0] == "image" and found[1] in send["types"]:
                return {"text": None, "data": data, "type": found, "markdown": False}      # nothing to scan: an image is sent as it is
            elif found is None or found[1] not in send["types"]:
                raise Unreadable("kind")
        if info.get("content") == "markdown":
            try:
                text = sources.strip_embedded_images(data.decode("utf-8"))[0]
            except UnicodeDecodeError:
                raise Unreadable("kind") from None
            converted = text.encode("utf-8")
        else:
            converted = _converted(cfg, data, path, out)
            text = converted.decode("utf-8", "replace")
        if "\x00" in text or (not text.strip() and send is None):
            raise Unreadable("empty" if not text.strip() else "kind")
        if sources._workcopy().scan(converted):      # limit L14: what looks like a credential is never shown, and never sent
            raise Unreadable("secret")
        if send is not None and send_scan.check(data, found[1], sources._workcopy().scan, markdown=info.get("content") == "markdown"):      # what is SENT is what is scanned: the bytes, not only the converter's text
            raise Unreadable("secret")
        return {"text": text if text.strip() else None, "data": data if send is not None else None, "type": found, "markdown": info.get("content") == "markdown"}
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


def _file_name(name: str, found, exported: bool) -> str:
    """The name a sent file carries: the file's own, with an ending added when it has none (a Google Doc has none): md for a Doc exported as text, else the ending of its type."""
    if EXTENSION.search(name):
        return name
    ending = "md" if exported else EXTENSIONS.get(found[1] if found else "")
    return f"{name}.{ending}" if ending else name


def _attachment(match: dict, got: dict, send: dict):
    """({"name", "kind", "data"}, why) for a file that was read to be sent: why is "" when it goes, "send-size" when it is over what the app takes. A photo only for a type the
    app shows as a photo and under its photo limit; a document otherwise."""
    data, found = got["data"], got["type"]
    if len(data) > send["max_bytes"]:
        return None, "send-size"
    photo = found[0] == "image" and found[1] in send["photo_types"] and len(data) <= send["photo_max_bytes"]
    return {"name": _file_name(match["name"], found, got["markdown"]), "kind": PHOTO if photo else "document", "data": data}, ""


def _read_match(cfg: dict, match: dict, send=None) -> dict:
    """The outcome of reading the one file chosen: {"status": "text", ...} | {"status": "unreadable", "name", "account", "why"}. With `send` (the messenger's limits, S18) a file that
    goes carries "attach" ({"name", "kind", "data"}), a text file keeps its preview, a file with no text is {"status": "sent", ...}, and `sending` is true in every outcome so that
    the sentences are the ones about sending."""
    flag = {"sending": True} if send is not None else {}
    if not match["supported"]:
        return {"status": "unreadable", "name": match["name"], "account": match["service"], "why": "kind", **flag}
    try:
        got = _read(cfg, match["service"], match["id"], send)
    except Unreadable as e:
        return {"status": "unreadable", "name": match["name"], "account": match["service"], "why": e.code, **flag}
    shown, remaining = _cut(got["text"]) if got["text"] else ("", 0)
    base = {"name": match["name"], "folder": match["folder"], "account": match["service"]}
    if send is None:
        return dict(base, status="text", text=shown, remaining=remaining)
    attach, why = _attachment(match, got, send)
    if attach is None:
        if not shown:
            return {"status": "unreadable", "name": match["name"], "account": match["service"], "why": why, **flag}
        return dict(base, status="text", text=shown, remaining=remaining, too_big=True, **flag)
    if not shown:
        return dict(base, status="sent", attach=attach, **flag)
    return dict(base, status="text", text=shown, remaining=remaining, attach=attach, **flag)


def _find_and_read(cfg: dict, wanted: str, account=None, said=None, send=None) -> dict:
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
    notes = {**({"incomplete": True} if found["incomplete"] else {}), **({"folder_missing": found["folder_missing"]} if found["folder_missing"] else {})}
    if len(matches) > 1:
        shown = matches[:LIST_MAX]
        return {"status": "several", "matches": [{k: m[k] for k in ("name", "folder", "service")} for m in shown], "count": len(matches), "refs": shown, **notes}
    return dict(_read_match(cfg, matches[0], send), **notes)


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


def _remember(ctx: dict, channel, sender, items: list, incomplete: bool = False, purpose: str = "read") -> None:
    now = _natural()._clock()
    with _lock:
        for old in [k for k, v in _LISTS.items() if (now - v["at"]).total_seconds() > LIST_WINDOW_S]:
            del _LISTS[old]
        _LISTS[_slot(ctx, channel, sender)] = {"at": now, "items": list(items), "incomplete": incomplete, "purpose": purpose, "seen": 0, "pending": importlib.import_module("event_lookup")._last_pending(ctx)}


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


def _limits(caps) -> dict | None:
    """The messenger's limits for a file it carries, checked and bounded by what this layer reads (sources.ORIGINAL_CAP), or None when they are not well formed:
    {"max_bytes", "photo_max_bytes", "photo_types", "types"}. The bridge builds them from the provider's capabilities, and a call that names none sends no file."""
    if not isinstance(caps, dict):
        return None
    number = lambda value: type(value) is int and value >= 0  # noqa: E731
    texts = lambda value: isinstance(value, list) and all(isinstance(v, str) for v in value)  # noqa: E731
    if not (number(caps.get("max_bytes")) and caps["max_bytes"] > 0 and number(caps.get("photo_max_bytes")) and texts(caps.get("photo_types")) and texts(caps.get("types"))):
        return None
    return {"max_bytes": min(caps["max_bytes"], sources.ORIGINAL_CAP), "photo_max_bytes": caps["photo_max_bytes"], "photo_types": list(caps["photo_types"]), "types": list(caps["types"])}


def _sending(ctx: dict, channel, sender, extras: dict):
    """The limits of the file to send with this reply (`_limits`), or None: the file goes only on a messaging app, when the bridge named the app's limits for this call and the
    sender's profile in the configuration in force NOW holds `send-files` and `read-files` (the group is asked again at every send, a pick included)."""
    if channel != "messaging" or not isinstance(sender, str):
        return None
    channels = ctx["cfg"].get("channels")
    if not (operations.holds(SEND_GROUP, "messaging", channels, sender) and operations.holds("read-files", "messaging", channels, sender)):
        return None
    return _limits(extras.get("can_send"))


def _finish(cfg: dict, got: dict, extras: dict, pick: bool = True) -> str:
    """The sentence for an outcome; the file that goes with it (if any) is handed to the caller in `extras["attachment"]`, in memory, and nowhere else."""
    attach = got.pop("attach", None)
    text = _render(cfg, got, pick)
    if attach is not None:
        extras["attachment"] = attach
    return text


def take(project: str, ctx: dict, said: str, channel, sender, extras: dict):
    """The reply to a number said right after a list of files ("o 2", "2", "the 2nd"), or None when the line is not one (no live list for this sender, a line that is no bare
    number, a number the list did not show). Any line ends the list, so a pick is used once. The sender's right to read files is asked again, and so is the grant: the configured
    folder the file was found under must still be one of the configuration in force, else the plain no-folder sentence and nothing is read. The file is read as `reply` reads it."""
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
    if record.get("purpose") == "trash":      # R2-A: the list was of files to move to the trash: the number opens that file's card (runtime/ops_file_trash.py)
        return importlib.import_module("ops_file_trash").pick(project, ctx, record["items"][form["n"] - 1], channel, sender, extras)
    refused = operations.refusal("file-read", "messaging", cfg["channels"], sender=sender)
    if refused:
        return phone_refusal.said(refused, channel, cfg)
    match = record["items"][form["n"] - 1]
    folders = [(service, None) for service in SERVICES if (project_config.account_entry(cfg, service) or {}).get("folders")]          # the real names are not read again for a refusal
    granted = {(service, ident) for service in SERVICES for ident in ((project_config.account_entry(cfg, service) or {}).get("folders") or {}).values()}
    extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    if (match["service"], match["root"]) not in granted:          # the folder the file was found under is not configured any more: it is not read
        return _render(cfg, {"status": "no-folder", "folders": folders, "cut": None} if folders else {"status": "no-folders"})
    return _finish(cfg, dict(_read_match(cfg, match, _sending(ctx, channel, sender, extras)), **({"incomplete": True} if record["incomplete"] else {})), extras)


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


def _render(cfg: dict, got: dict, pick: bool = True) -> str:
    """The sentence a chat is told for an outcome of find_and_read, in the project's language. `pick` says the reader can answer a list with a number (a messaging app); the page and the
    terminal are told to use the full name. A found file or a list is followed by FR_INCOMPLETE when the search was cut, listed a folder in part or could not list one."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    status = got["status"]
    notes = ([t("FR_FOLDER_MISSING", folder=got["folder_missing"])] if got.get("folder_missing") else []) + ([t("FR_INCOMPLETE")] if got.get("incomplete") else [])
    if status == "text":
        head = t("FR_HEAD", name=got["name"], account=_label_of(cfg, got["account"]), folder=got["folder"])
        more = "\n\n" + t("FR_MORE", remaining=got["remaining"]) if got["remaining"] else ""
        large = "\n\n" + t("FS_TOO_BIG", name=got["name"], account=_label_of(cfg, got["account"])) if got.get("too_big") else ""
        return f"{head}\n\n{got['text']}{more}{large}" + "".join("\n\n" + n for n in notes)
    if status == "sent":
        return t("FS_SENT", name=got["name"], account=_label_of(cfg, got["account"]), folder=got["folder"]) + "".join("\n\n" + n for n in notes)
    if status == "several":
        rows = [t("FR_ITEM", n=n, name=m["name"], folder=m["folder"], account=_label_of(cfg, m["service"])) for n, m in enumerate(got["matches"], 1)]
        return "\n".join([t("FR_SEVERAL_PICK" if pick else "FR_SEVERAL_NAME", count=got["count"])] + rows + notes)
    if status in ("none", "no-folder"):
        named = []          # the real names of the configured folders; one whose name could not be read is the service's own name, once
        for service, real in got["folders"]:
            row = t("FR_FOLDER", folder=real, account=_label_of(cfg, service)) if real else _label_of(cfg, service)
            if row not in named:
                named.append(row)
        folders = ", ".join(named)
        partial = " " + t("FR_PARTIAL") if status == "none" and (got["truncated"] or got["failed"]) else ""
        cut = " " + t("FR_CUT") if got.get("cut") else ""
        return t("FR_NONE_SUB" if status == "none" else "FR_NO_SUCH_FOLDER", folders=folders) + partial + cut
    if status == "unreadable":
        words = {"secret": "FS_WITHHELD", "size": "FS_TOO_BIG", "send-size": "FS_TOO_BIG", "kind": "FS_KIND"} if got.get("sending") else {"secret": "FR_WITHHELD", "size": "FR_TOO_BIG", "empty": "FR_EMPTY"}
        return t(words.get(got["why"], "FR_UNREADABLE"), name=got["name"], account=_label_of(cfg, got["account"])) \
            + "".join(" " + n for n in notes)
    if status == "no-folders":
        return t("FR_NO_FOLDERS")
    return t("FR_UNAVAILABLE")


def line_target(cfg: dict, args: dict, said: str) -> tuple:
    """(the name span, the account or None, the ask-again sentence or None) of a line that names a file: the name is checked to be a span of the line; the service word (when there
    is one) must name exactly one service and agree with the account the line itself names; "drive" alone names none (both accounts are searched)."""
    wanted = args.get("file")
    word = args.get("account")
    if not isinstance(wanted, str) or not natural.normal(wanted) or natural.normal(wanted) not in natural.normal(said) or len(wanted) > natural.SPAN_MAX:
        return None, None, phrases.text("IX_ASK_AGAIN", cfg)
    named = _accounts_of_line(said, wanted)
    if word and natural.ascii_normal(str(word)) in GENERIC:
        word = None          # "drive" alone names no service: both accounts are searched
    account = _service_of(word) if word else (next(iter(named)) if len(named) == 1 else None)
    if word and (account is None or (named and named != {account})):          # a word no table reads, or one that does not agree with the line (a line that names both accounts agrees with neither)
        return None, None, phrases.text("IX_ASK_AGAIN", cfg)
    return wanted, account, None


def reply(project: str, ctx: dict, args: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply of `file-read` chosen by a tier or by the interpreter (runtime/ops_natural.py `run` has already asked the policy). The name is checked to be a span of the
    line; the service word (when there is one) must name exactly one service and agree with the account the line itself names ("do google drive"; a line that names both searches both,
    and a word that is only "drive" names none); a folder named in the line
    narrows the search. Else the fixed ask-again sentence and nothing is listed. The conversation keeps a neutral word."""
    cfg = ctx["cfg"]
    extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    wanted, account, again = line_target(cfg, args, said)
    if again:
        return again
    line_stage.publish("file")      # S19: the name is checked, the folders are searched
    got = _find_and_read(cfg, wanted, account, said, _sending(ctx, channel, sender, extras))
    if got["status"] == "several" and channel == "messaging":
        _remember(ctx, channel, sender, got["refs"], bool(got.get("incomplete")))
    return _finish(cfg, got, extras, channel == "messaging")


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
