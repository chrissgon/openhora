#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Read a file by its name from the folders the project lists for the person's own accounts (slice S8): `file-read`, a class R operation.

  file_read(project, file, [account], [channel, sender])   the operation (the typed command, the page, a messaging app): {"status", ...}, below
  reply(project, ctx, args, said, channel, sender, extras) the reply a line in words gets (runtime/ops_natural.py `run` calls it for `file-read`)

What it searches, and nothing else: the folders under `accounts.<google|microsoft>.folders` of the project's configuration (project_config `account_target`
is the rule of every write; this is the rule of this read), the DIRECT contents of each one. The providers do not walk subfolders (`children` lists one folder), so a
file in a subfolder is not found; a folder that holds more than 200 items is listed to its first 200 and the reply says so when nothing was found. A file outside the
listed folders is never listed, never named and never read, whatever the token could reach. Both accounts are searched unless the line names one.

The match is on the name, folded as every name of the platform is (`natural.normal`: case, accents, punctuation), with the extension optional. One match is read; several
are listed (name, configured folder name, account) so the person can say which; none gets one sentence naming the folders searched by the names the configuration gives
them (never an id or a path).

The read goes through the providers of `integration:documents` that already read the files of a source (`sources.drive_call`, `sources_onedrive.onedrive_call`: `read`,
with `children` for the listing), the same intake, the same converter and the same credential scan (limit L14) as a source, and registers nothing: no source, no version,
no catalog row, no copy. The bytes live in a private staging folder for the length of the call and are removed. The text is cut at TEXT_MAX characters and the reply says
how many remain.

What is kept (limits L50, L61 and L63): the conversation stores a neutral word for the reply (`extras["stored"]`) and the interpreter stores the line as a neutral word, so
the file's text, its name and the folder's name are in the reply to the chat that asked and nowhere else; nothing here logs, prints or stores a name, a folder or a text, and a
provider's failure is a fixed sentence (its text is another service's). No model ever reads the file: the interpreter decides the operation and the name from the person's
line alone. A question about the file is NOT answered from it: the answer from sources (`ask`) reads registered sources only, and this slice registers none, so the text is shown.

Sibling of runtime/ops.py, which exposes `file_read` under its name. The shared names come from ops_core, read as `core.<name>`. Standard library only. Runs on Python 3.9:
python3 runtime/ops_file_read.py --help
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import secrets
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intake  # noqa: E402
import line_stage  # noqa: E402
import natural  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import sources  # noqa: E402
import sources_onedrive  # noqa: E402

TEXT_MAX = 3500          # characters of a file's text shown in one reply (this slice's choice: a messaging app's message holds 4,096)
LIST_MAX = 8             # matches listed when several files carry the name
FOLDER_TOP = 200         # items one folder's listing asks for (the providers' own ceiling)
WORKERS = 4              # folders listed at the same time
SERVICES = ("google", "microsoft")
SERVICE_PHRASE = {"google": "FR_GOOGLE", "microsoft": "FR_MICROSOFT"}
EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,5}$")
CONTENT = "content"      # the name of the file a provider writes in its --out-dir

provider_call = None     # a test replaces it: call(cls, verb, args, root=, implementation=, timeout=, env=) -> dict, as providers/resolve.py `call`
converter = None         # a test replaces it: convert(input_path, subtype, out_dir) -> info; None is the provider of converter:document


class Unreadable(Exception):
    """The file cannot be shown; `code` is one of "kind", "size", "secret", "empty", "service"."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- the search --------------------------------------------------------------------------------------------------------------------------------


def _stem(name: str) -> str:
    return EXTENSION.sub("", name)


def _same_name(wanted: str, found: str) -> bool:
    """Whether a file called `found` is the one the person called `wanted`: the names are equal once folded, and the extension is optional (a name typed with its
    ending also matches a file that has none, as a Google Doc has none). Never a part of a name."""
    asked, asked_stem, name, name_stem = natural.normal(wanted), natural.normal(_stem(wanted)), natural.normal(found), natural.normal(_stem(found))
    if not asked or not name:
        return False
    if _stem(wanted) == wanted:      # typed without an ending: the file's ending is optional
        return asked in (name, name_stem)
    return asked == name or (_stem(found) == found and asked_stem == name)


def _children(cfg: dict, service: str, ident: str) -> dict:
    """{"items": [...], "truncated": bool} of one configured folder, through the provider of the service (`children`). Any failure is an exception for the caller to count."""
    if service == "google":
        got = sources.drive_call(cfg, "children", ["--id", ident, "--top", str(FOLDER_TOP)], call=provider_call)
    else:
        where = ["--path", ident] if ident.startswith("/") else ["--folder-id", ident]
        got = sources_onedrive.onedrive_call(cfg, "children", where + ["--top", str(FOLDER_TOP)], call=provider_call)
    items = got.get("items")
    if not isinstance(items, list):
        raise ValueError("the provider's list is not one this runtime reads")
    return {"items": [i for i in items if isinstance(i, dict)], "truncated": bool(got.get("truncated"))}


def _search(cfg: dict, wanted: str, account=None) -> dict:
    """{"folders": [(service, folder name)] searched, "matches": [{"service", "folder", "id", "name", "supported"}], "failed": folders that could not be listed,
    "truncated": folders listed in part}. `account` google or microsoft narrows the search to one account. Only the folders the configuration lists are listed."""
    services = [account] if account in SERVICES else list(SERVICES)
    jobs = [(service, name, ident) for service in services for name, ident in ((project_config.account_entry(cfg, service) or {}).get("folders") or {}).items()]
    out = {"folders": [(service, name) for service, name, _ in jobs], "matches": [], "failed": 0, "truncated": 0}

    def one(job):
        try:
            return _children(cfg, job[0], job[2])
        except Exception:      # noqa: BLE001 - a provider's failure is another service's text: it is counted, never kept
            return None
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        listed = list(pool.map(one, jobs))
    seen = set()
    for (service, name, _), got in zip(jobs, listed):
        if got is None:
            out["failed"] += 1
            continue
        out["truncated"] += 1 if got["truncated"] else 0
        for item in got["items"]:
            ident, label = item.get("id"), item.get("name")
            if item.get("kind") != "file" or not isinstance(ident, str) or not isinstance(label, str) or (service, ident) in seen or not _same_name(wanted, label):
                continue
            seen.add((service, ident))
            out["matches"].append({"service": service, "folder": name, "id": ident, "name": " ".join(label.split())[:200], "supported": item.get("supported") is True})
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


def _find_and_read(cfg: dict, wanted: str, account=None) -> dict:
    """The outcome of one request, as data: {"status": "no-folders"} | {"status": "none", "folders", "failed", "truncated"} | {"status": "several", "matches"} |
    {"status": "text", "name", "folder", "account", "text", "remaining"} | {"status": "unreadable", "name", "account", "why"} | {"status": "unavailable"}."""
    found = _search(cfg, wanted, account)
    if not found["folders"]:
        return {"status": "no-folders"}
    matches = found["matches"]
    if not matches:
        if found["failed"] == len(found["folders"]):
            return {"status": "unavailable"}
        return {"status": "none", "folders": found["folders"], "failed": found["failed"], "truncated": found["truncated"]}
    if len(matches) > 1:
        return {"status": "several", "matches": [{k: m[k] for k in ("name", "folder", "service")} for m in matches[:LIST_MAX]], "count": len(matches)}
    match = matches[0]
    if not match["supported"]:
        return {"status": "unreadable", "name": match["name"], "account": match["service"], "why": "kind"}
    try:
        shown, remaining = _cut(_read_text(cfg, match["service"], match["id"]))
    except Unreadable as e:
        return {"status": "unreadable", "name": match["name"], "account": match["service"], "why": e.code}
    return {"status": "text", "name": match["name"], "folder": match["folder"], "account": match["service"], "text": shown, "remaining": remaining}


def file_read(project: str, file: str, account: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """The operation `file-read`. From a messaging app the sender's profile must hold the group `read-files` (the sentence the bridge uses otherwise); the page and the
    terminal follow the table of operations. Returns find_and_read's outcome."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "file-read", channel, sender)
    if not isinstance(file, str) or not natural.normal(file) or len(file) > natural.SPAN_MAX:
        raise core.OpsError("--file is the name of a file (1 to 300 characters)", 2)
    if account is not None and account not in SERVICES:
        raise core.OpsError("--account is google or microsoft", 2)
    return _find_and_read(ctx["cfg"], file, account)


# --- the reply to a line in words ---------------------------------------------------------------------------------------------------------------


def _service_of(word):
    """`google` or `microsoft` for a word the language tables list for exactly one service ("onedrive", "drive"), or None; a typed `google` or `microsoft` is itself."""
    if word in SERVICES:
        return word
    folded = natural.ascii_normal(str(word))
    from natural_writes import listed      # at call time: the closed lists of the language tables
    hits = [s for s in SERVICES if folded in listed(natural._tables(None), "services", s)]
    return hits[0] if len(hits) == 1 else None


def _label(cfg: dict, service: str) -> str:
    return phrases.text(SERVICE_PHRASE[service], cfg)


def _render(cfg: dict, got: dict) -> str:
    """The sentence a chat is told for an outcome of find_and_read, in the project's language."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    status = got["status"]
    if status == "text":
        head = t("FR_HEAD", name=got["name"], account=_label(cfg, got["account"]), folder=got["folder"])
        more = "\n\n" + t("FR_MORE", remaining=got["remaining"]) if got["remaining"] else ""
        return f"{head}\n\n{got['text']}{more}"
    if status == "several":
        rows = [t("FR_ITEM", n=n, name=m["name"], folder=m["folder"], account=_label(cfg, m["service"])) for n, m in enumerate(got["matches"], 1)]
        return "\n".join([t("FR_SEVERAL", count=got["count"])] + rows)
    if status == "none":
        folders = ", ".join(t("FR_FOLDER", folder=folder, account=_label(cfg, service)) for service, folder in got["folders"])
        partial = " " + t("FR_PARTIAL") if got["truncated"] or got["failed"] else ""
        return t("FR_NONE", folders=folders) + partial
    if status == "unreadable":
        return t({"secret": "FR_WITHHELD", "size": "FR_TOO_BIG", "empty": "FR_EMPTY"}.get(got["why"], "FR_UNREADABLE"), name=got["name"], account=_label(cfg, got["account"]))
    if status == "no-folders":
        return t("FR_NO_FOLDERS")
    return t("FR_UNAVAILABLE")


def reply(project: str, ctx: dict, args: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply of `file-read` chosen by a tier or by the interpreter (runtime/ops_natural.py `run` has already asked the policy). The name is checked to be a span of the
    line, the service word (when there is one) to name exactly one service; else the fixed ask-again sentence and nothing is listed. The conversation keeps a neutral word."""
    cfg = ctx["cfg"]
    extras["stored"] = phrases.text("NAT_READ_REPLY", cfg)
    wanted = args.get("file")
    word = args.get("account")
    account = _service_of(word) if word else None
    if not isinstance(wanted, str) or not natural.normal(wanted) or natural.normal(wanted) not in natural.normal(said) or len(wanted) > natural.SPAN_MAX \
            or (word and account is None):
        return phrases.text("IX_ASK_AGAIN", cfg)
    line_stage.publish("file")      # S19
    return _render(cfg, _find_and_read(cfg, wanted, account))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
