#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""OneDrive files as sources of a project (package O2): the origin check, the calls to the provider, the import, the version-first refresh
and the listings for the person's terminal. It is the block beside runtime/sources.py that the Drive block of that module is the pattern
of. A OneDrive source is one FILE of the person's own OneDrive that the person chose in the terminal (`source-onedrive`): a
folder, a package (a OneNote notebook), an item shared from another drive, an item OneDrive flagged as malware and a deleted item are
never sources. The registry's type column admits `onedrive` since migration 19: a OneDrive source is a row of type `onedrive` whose origin
is "<drive id>/<item id>" (each part letters, digits and ! . _ -; a personal item id holds a `!`).

The provider is `providers/documents/onedrive.py` (class integration:documents, implementation onedrive), run as a process through
providers/resolve.py with the minimum environment plus the one secret it reads (ONEDRIVE_SOURCES_TOKEN). Its OAuth scope is the
delegated `Files.Read` and nothing else; Microsoft has no scope per chosen file, so the token can READ every file of the person's own
OneDrive and writes none. The narrowing to the chosen files is this module's and the runtime's: only a registered item id is read, and
no verb of a run lists a folder (`search` and `children` serve the person's terminal, through `onedrive_candidates`, and register
nothing). The provider writes the downloaded bytes into a folder of the runtime's private staging area and prints their description; they
go through the same intake, converter, credential scan and rows as a file of the person's, never parsed here (limit L27). The refresh
compares the provider's `version` (the item's cTag, which moves with the CONTENT and not with a share or a rename) with the one recorded
with the newest version (`origin_version`) before it reads anything. The eTag is kept in the manifest as `etag`.

External content is data: a file's name, its path and every search result are another person's text in principle. They are cleaned to
one line, shown to the person in the terminal, and never executed or used as a path; the content reaches a run only as converted text
after the scan (sources rules 8 and 11).

A credential never reaches a run, a manifest or the catalog: the provider's process gets `provider_environment` plus the one secret, and
this module never reads or stores a token, an upload address or an account.

Imports `sources` (the registry, the versions, the guardrails of the folder) and nothing of the operations layer. `sources.register`
loads this module for the origin check of its type. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import shutil
import secrets as _secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources  # noqa: E402
from sources import SourcesError, _clean  # noqa: E402

ONEDRIVE_CLASS = "integration:documents"
ONEDRIVE_IMPLEMENTATION = "onedrive"
ONEDRIVE_SECRET = "ONEDRIVE_SOURCES_TOKEN"   # providers/secrets/resolver.py: the one record (refresh token, client id, tenant); read by the provider alone
ONEDRIVE_TIMEOUT = 300
ONEDRIVE_PART = re.compile(r"[A-Za-z0-9!._-]{1,200}")    # a drive id or an item id (providers/documents/onedrive.py ID_PART)
ONEDRIVE_CONTENT = "content"                              # the name of the file the provider writes in its --out-dir
ONEDRIVE_QUERY_MAX = 200                                  # the longest search text (the provider's bound)
ONEDRIVE_PATH_MAX = 400                                   # the longest folder path (the provider's bound)
ONEDRIVE_LIST_MAX = 25                                    # candidates shown for a search
ONEDRIVE_FOLDER_LIST_MAX = 200                            # items shown for a folder
ONEDRIVE_NAME_CHARS, ONEDRIVE_PATH_CHARS, ONEDRIVE_REASON_CHARS = 200, 300, 300


def onedrive_origin(text) -> str:
    """The origin of a OneDrive source from "<drive id>/<item id>". SourcesError (usage) for anything else: an address is not accepted,
    since the ids are what `source-onedrive --search` prints and the provider checks the file by them."""
    raw = text.strip() if isinstance(text, str) else ""
    parts = raw.split("/")
    if len(parts) != 2 or not all(ONEDRIVE_PART.fullmatch(p) and set(p) != {"."} for p in parts):
        raise SourcesError("a OneDrive item is \"<drive id>/<item id>\" (letters, digits and ! . _ - in each part; "
                           "`source-onedrive --search` prints it)", "usage")
    return raw


def onedrive_call(cfg: dict, verb: str, args: list, *, call=None, timeout: int = ONEDRIVE_TIMEOUT) -> dict:
    """One verb of the OneDrive provider, through providers/resolve.py, in a process that has the minimum environment and the one secret.
    `call(cls, verb, args, implementation=, root=, timeout=, env=)` is the seam a test replaces. SourcesError (onedrive) on any failure,
    with the provider's reason (cleaned to one line: it is another service's text)."""
    resolver = None
    if call is None:
        resolver = sources._lazy("workbench_sources_resolve", os.path.join(cfg["workbench"], "providers", "resolve.py"))
        call = resolver.call
    extra = {"env": sources._provider_env(cfg, ONEDRIVE_CLASS, (ONEDRIVE_SECRET,))} if resolver is not None else {}
    try:
        out = call(ONEDRIVE_CLASS, verb, args, root=cfg["workbench"], implementation=ONEDRIVE_IMPLEMENTATION, timeout=timeout, **extra)
    except Exception as e:
        kind = getattr(e, "kind", None)
        reason = getattr(e, "reason", None) or str(e)
        raise SourcesError(f"the OneDrive file could not be read ({kind or type(e).__name__}): {_clean(reason, 300)}", "onedrive") from None
    if not isinstance(out, dict):
        raise SourcesError("the OneDrive provider answered no object", "onedrive")
    return out


def onedrive_id_of(source: dict) -> str:
    """The "<drive id>/<item id>" of a source row."""
    row = sources.public_row(source)
    if row.get("type") != "onedrive":
        raise SourcesError(f"{source.get('id')} is not a OneDrive source", "usage")
    return onedrive_origin(row["origin"])


def onedrive_stat(cfg: dict, item_id: str, *, call=None) -> dict:
    """The provider's `stat`: {"id", "name", "mime_type", "version" (the cTag), "etag", "size", "supported", "reason", ...}. One metadata
    call. `supported` is checked BEFORE `version`: an item the runtime must refuse (a folder, a package) prints no version at all, and its
    reason is what the person is told."""
    out = onedrive_call(cfg, "stat", ["--id", onedrive_origin(item_id), "--as-source"], call=call)
    if not isinstance(out.get("supported"), bool):
        raise SourcesError("the OneDrive provider's answer does not say whether the item can be read", "onedrive")
    if out["supported"] and (not isinstance(out.get("version"), str) or not out["version"]):
        raise SourcesError("the OneDrive provider's answer has no version", "onedrive")
    return out


def onedrive_import(ctx, source: dict, *, convert, label: str, call=None, clock=None, evidence_base=None) -> dict:
    """Read a OneDrive file through the provider and import it as a version of `source`. The provider writes the bytes into a folder of
    the runtime's staging area; they go through import_version's intake and the converter like a file of the person's (OneDrive gives no
    Markdown, so there is nothing to strip). The cTag of the file the provider read is recorded with the new version (origin_version)
    and its eTag in the manifest. Returns import_version's answer. SourcesError on any refusal, with nothing kept."""
    cfg = ctx["cfg"]
    item_id = onedrive_id_of(source)
    sources.check_folder(cfg, evidence_base)   # a folder that cannot be used is found before the file is read, not after
    stage = sources._make_staging(cfg["data_dir"], _secrets.token_hex(8))
    try:
        out_dir = os.path.join(stage, "out")
        info = onedrive_call(cfg, "read", ["--id", item_id, "--as-source", "--out-dir", out_dir, "--max-bytes", str(sources.ORIGINAL_CAP)],
                             call=call)
        if info.get("content") != "file" or not isinstance(info.get("version"), str) or not info["version"]:
            raise SourcesError("the OneDrive provider's answer is not one this runtime reads", "onedrive")
        path = os.path.join(out_dir, ONEDRIVE_CONTENT)
        stream, length, closer = sources._stream_of(path)   # a regular file, opened without following a link
        with closer:
            if length > sources.ORIGINAL_CAP:
                raise SourcesError(f"the file is larger than {sources.ORIGINAL_CAP} bytes", "size")
            data = stream.read(sources.ORIGINAL_CAP + 1)
        if sources._sha(data) != info.get("sha256") or len(data) != info.get("bytes"):
            raise SourcesError("what the OneDrive provider wrote is not what it described; nothing was kept", "onedrive")
        name = _clean(info.get("name") or "", ONEDRIVE_NAME_CHARS) or None
        etag = _clean(info.get("etag") or "", 100)
        return sources.import_version(ctx, source, data, convert=convert, label=label, origin_version=info["version"], clock=clock,
                                      evidence_base=evidence_base, name=name, manifest_extra={"etag": etag} if etag else None)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def onedrive_refresh(ctx, source: dict, *, convert, call=None, clock=None, evidence_base=None, info=None) -> dict:
    """A refresh of a OneDrive source. The provider's `stat` is asked first: when its version (the cTag) is the one recorded with the
    newest version, nothing is read and no version is made (the files in the folder are still checked against the record, limit L25).
    When it differs, the file is read and imported; bytes already held make no version either. Returns {"imported", "unchanged", "read"
    (whether the file was read), "remote_version", "version", ...}. `info` is a `stat` answer the caller has just asked for (not asked twice)."""
    cfg = ctx["cfg"]
    info = info if info is not None else onedrive_stat(cfg, onedrive_id_of(source), call=call)
    if not info["supported"]:
        raise SourcesError(f"{source['id']} is not read: {_clean(info.get('reason') or 'OneDrive says it cannot be read', ONEDRIVE_REASON_CHARS)}",
                           "onedrive")
    latest = sources._stored(ctx, "source_latest", source["id"])
    if latest is not None and latest.get("origin_version") == info["version"]:
        done = sources.recheck(ctx, source, convert=convert, clock=clock, evidence_base=evidence_base)
        if done.get("changed"):
            return {**done, "read": False, "remote_version": info["version"]}
        return {"imported": False, "unchanged": True, "read": False, "source": source["id"], "version": latest["version"],
                "remote_version": info["version"]}
    done = onedrive_import(ctx, source, convert=convert, label="refresh" if latest else "import", call=call, clock=clock,
                           evidence_base=evidence_base)
    return {**done, "read": True}


def onedrive_source_id(name: str, taken) -> str:
    """A source id for a chosen OneDrive file, from its name (sources.source_id_from_name, with `onedrive-file` for a name that leaves nothing)."""
    return sources.source_id_from_name(name, taken, "onedrive-file")


# --- choosing files: the person's terminal (search and children register nothing) -----------------------------------------------------


def _one_line_query(text) -> str:
    one = " ".join(str(text or "").split())
    if not one or len(one) > ONEDRIVE_QUERY_MAX or any(not ch.isprintable() for ch in one):
        raise SourcesError(f"--search is 1 to {ONEDRIVE_QUERY_MAX} printable characters", "usage")
    return one


def _folder_path(text) -> str:
    raw = str(text or "").strip()
    if not raw or len(raw) > ONEDRIVE_PATH_MAX or any(not ch.isprintable() for ch in raw):
        raise SourcesError(f"--folder is a folder path from the root of the OneDrive, such as /Documents/Reports (1 to {ONEDRIVE_PATH_MAX} "
                           "printable characters; \"/\" is the root)", "usage")
    return raw


def onedrive_candidates(cfg: dict, *, search=None, folder=None, call=None) -> dict:
    """The items the person can choose from, for the terminal: up to 25 matches of a search text, or the items of one folder. Nothing is
    registered and nothing is read but names and descriptions. Every text in the answer is another person's, cleaned to one line.
    Returns {"mode": "search"|"folder", "query"|"folder", "candidates": [{"n", "id", "name", "kind", "path", "size", "modified",
    "supported", "reason"}], "count", "truncated"}. SourcesError (usage) for a missing or both of search and folder."""
    if (search is None) == (folder is None):
        raise SourcesError("give exactly one of --search (a text to look for) and --folder (a folder path)", "usage")
    if search is not None:
        text = _one_line_query(search)
        got = onedrive_call(cfg, "search", ["--query", text, "--top", str(ONEDRIVE_LIST_MAX)], call=call)
        head, limit = {"mode": "search", "query": text}, ONEDRIVE_LIST_MAX
    else:
        where = _folder_path(folder)
        got = onedrive_call(cfg, "children", ["--path", where, "--top", str(ONEDRIVE_FOLDER_LIST_MAX)], call=call)
        head, limit = {"mode": "folder", "folder": where}, ONEDRIVE_FOLDER_LIST_MAX
    items = got.get("items")
    if not isinstance(items, list):
        raise SourcesError("the OneDrive provider's list is not one this runtime reads", "onedrive")
    candidates = []
    for item in items[:limit]:
        try:
            item_id = onedrive_origin(item.get("id")) if isinstance(item, dict) else None
        except SourcesError:
            item_id = None
        if item_id is None:
            continue
        size = item.get("size")
        candidates.append({"n": len(candidates) + 1, "id": item_id, "name": _clean(item.get("name") or "", ONEDRIVE_NAME_CHARS),
                           "kind": _clean(item.get("kind") or "", 40), "path": _clean(item.get("path") or "", ONEDRIVE_PATH_CHARS),
                           "size": size if isinstance(size, int) and not isinstance(size, bool) else None,
                           "modified": _clean(item.get("modified") or "", 40), "supported": item.get("supported") is True,
                           "reason": _clean(item.get("reason") or "", ONEDRIVE_REASON_CHARS)})
    return {**head, "candidates": candidates, "count": len(candidates), "truncated": bool(got.get("truncated")) or len(items) > limit}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
