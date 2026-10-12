#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The mirror of documents to and from the project's documents platform (class integration:documents).

A document is mirrored only when a `documents[]` entry of a skill's runtime manifest lists its path (placeholders
read as wildcards) and the path rule calls it a document: the entry gives the owning skill, `platform` (editable or
read_only) and `checks` (the skill's own checker commands). A path no manifest lists, a machine file and a document
bound to an approval are never sent. Only code talks to the platform: a run never sees it. Each document has one
record in the store (store.document_put): the page's id, the hash of what the runtime last wrote (written_sha256),
the hash of what it last read from the page (read_sha256), the page's version and a status (mirrored, read_only,
rejected) with a note.

  pull(ctx)            the platform to the project. A page whose version did not change is never read: its own
                       open comments are listed (the provider's `comments`, one call) and the new ones saved, since
                       the version covers the content and a comment may not move it. A page read has all its open
                       comments saved (store.comments_save); a person's edit of an editable document
                       replaces the whole project document, only when the project's file is still what was last
                       written and the skill's checker passes on a scratch copy; otherwise neither side changes and
                       the record is `rejected`, with the reason. An edit of a read_only document cannot be
                       imported: it is kept aside in <data_dir>/documents/not-taken/, the page is left as the person
                       left it, and the record is `rejected` (READ_ONLY_CHANGED) until `take` settles it.
  push(ctx, rels)      the project to the platform: a page is written only when the project's file changed since the
                       last write, after its open comments are saved; a page that changed since the runtime last
                       wrote it is never written over, read_only or not (pull's rules settle it). The hashes kept are
                       those of what the platform returns, so a difference the conversion makes is never taken for an
                       edit. A read_only page carries NOTICE as its first block: written with the page, or added once
                       (the provider's `notice`) to a page that has none; it is never part of what is read.
  blocked(ctx, meta)   the rejected records among a skill's declared inputs, outputs and updates: a run does not
                       start on a document the person edited and the agents would not read (decision D11).
  imported_since(cfg, since)  the documents imported (a person's edit, recorded in <data_dir>/documents/imported.json
                       at each import) after a task's last run started, while the project's file is still that text:
                       the next run of a task that reads one is told so in its prompt (ops.task_prompt).
  take(ctx, rel, side) settles a rejected record: "page" takes the page's text (when the checker passes), or, for a
                       read_only type, keeps the page as it is and leaves the file unmirrored until it changes again;
                       "project" writes the project's file over the page, the page's text kept aside first.

Nothing here merges two versions of a document: a write replaces the whole document, on either side. The bounds of
the writes are the configuration's documents object (runtime/project_config.py, bounds_problem).

Usage (a library; the shell is runtime/cli.py sync): python3 runtime/documents.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project_config  # noqa: E402  (the same folder: the resolver is loaded, and the bounds read, from here)
import isolated  # noqa: E402
import manifest  # noqa: E402
import path_rule  # noqa: E402
import skill_meta  # noqa: E402

CLASS = "integration:documents"
KEY = "documents"
TIMEOUT = 180
CHECK_TIMEOUT = 120
OUTPUT_CHARS = 2000
NOT_TAKEN = os.path.join("documents", "not-taken")
IMPORTED = os.path.join("documents", "imported.json")  # {rel: {"sha256", "at"}}: the last import of each document
NOTICES = os.path.join("documents", "notices.json")  # {rel: page id}: the read_only pages known to carry NOTICE
BOTH_CHANGED = "both changed"
READ_ONLY_CHANGED = ("the page changed since the last write; the type is read-only on the platform, so the edit cannot "
                     "be imported: `take page` keeps the page as it is and marks the file as not mirrored until the "
                     "file changes again, `take project` writes the file over the page")
KEPT_AS_IS = "the page is kept as the person left it (take page); the file is not mirrored until it changes again"
NOTICE = ("Read-only on the platform: edits made here are not imported into the project. Answer through the runtime "
          "(a pending decision, a comment taken into an answer, or the chat). An edit made here is kept: the next "
          "write to this page is refused while the page differs from what the runtime last wrote.")
STATUS_OF = {"editable": "mirrored", "read_only": "read_only"}


class DocumentsError(Exception):
    """A call to the documents provider failed, or a request cannot be done: kind is "not configured" (exit 3),
    "failed", "bounds" or "refused"."""

    def __init__(self, kind: str, detail: str):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def enabled(cfg: dict) -> bool:
    return cfg.get(KEY) is not None


def call(cfg: dict, root: str, verb: str, args: list, timeout: int = TIMEOUT) -> dict:
    """One verb of the provider the configuration names, through providers/resolve.py (resolve.call)."""
    try:
        resolve = project_config.resolver(root)
    except project_config.ConfigError as e:
        raise DocumentsError("not configured", str(e)) from None
    try:
        return resolve.call(CLASS, verb, args, root=root, implementation=cfg[KEY]["provider"], config=cfg[KEY],
                            timeout=timeout)
    except resolve.ProviderCallError as e:
        raise DocumentsError("not configured" if e.kind == "not-configured" else "failed", e.reason) from None


def _sha(data) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def result() -> dict:
    """The form of what pull, push and take return, so that their results add up."""
    return {"imported": [], "not_taken": [], "conflicts": [], "rejected": [], "comments": 0, "gone": [],
            "pushed": [], "failed": [], "notices": []}


def _entries(root: str) -> list:
    """Every documents[] entry of every runtime manifest of <root>/skills, with its skill and its machine files."""
    out = []
    folder = os.path.join(root, "skills")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not os.path.isfile(manifest.path(root, name)):
            continue
        try:
            data = manifest.load(root, name)
        except manifest.ManifestError as e:
            raise DocumentsError("failed", str(e)) from None
        for doc in data["documents"]:
            out.append({**doc, "skill": name, "machine_files": list(data["machine_files"])})
    return out


def entry_for(root: str, rel: str):
    """The manifest entry that mirrors the project path rel, or None: the path is a document by the path rule, a
    documents[] entry lists it, and it is neither bound to an approval nor a machine file of its skill."""
    if path_rule.classify(rel) != "document":
        return None
    for entry in _entries(root):
        if skill_meta.matches([entry["path"]], rel):
            if entry["bound_to_approval"] or skill_meta.matches(entry["machine_files"], rel):
                return None
            return entry
    return None


def _project_file(project: str, rel: str) -> str:
    """The project's path of rel, refused when it is a link or leaves the project."""
    target = os.path.join(project, *rel.split("/"))
    folder = os.path.dirname(target)
    while not os.path.exists(folder):
        folder = os.path.dirname(folder)
    real = os.path.realpath(folder)
    if os.path.islink(target) or not (real == project or real.startswith(project + os.sep)):
        raise DocumentsError("refused", f"{rel}: the project's path is a link or leaves the project")
    return target


def _read_project(project: str, rel: str):
    """The bytes of the project's regular file rel, or None."""
    target = os.path.join(project, *rel.split("/"))
    if os.path.islink(target) or not os.path.isfile(target):
        return None
    with open(target, "rb") as f:
        return f.read()


def _write_project(project: str, rel: str, data: bytes) -> None:
    target = _project_file(project, rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temporary = f"{target}.{os.getpid()}.tmp"
    with open(temporary, "wb") as f:
        f.write(data)
    os.replace(temporary, target)


def _docs_files(project: str) -> list:
    """Every regular file under the project's docs/, as relative paths: no link, real path inside the project."""
    out = []
    top = os.path.join(project, "docs")
    if not os.path.isdir(top) or os.path.islink(top):
        return out
    for current, names, files in os.walk(top):
        names[:] = sorted(n for n in names if not os.path.islink(os.path.join(current, n)))
        for name in sorted(files):
            path = os.path.join(current, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            if not os.path.realpath(path).startswith(project + os.sep):
                continue
            out.append(os.path.relpath(path, project).replace(os.sep, "/"))
    return out


def check_edit(root: str, project: str, entry: dict, rel: str, markdown) -> tuple:
    """(True, "") when an edit of the document rel passes its skill's checker, else (False, the reason). The
    checker runs on a scratch copy of the project's docs/ with the edit written at rel, never in the project; each
    command of entry["checks"] is `<root>/skills/<skill>/scripts/<script> <arguments>`, with {path} read as rel, run
    from the scratch root by runtime/isolated.py (an isolated interpreter with a scrubbed environment). With no checker, the edit passes when it is not empty and is
    valid UTF-8."""
    if not isinstance(markdown, str) or not markdown.strip():
        return False, "the page is empty"
    try:
        data = markdown.encode("utf-8")
    except UnicodeEncodeError:
        return False, "the page is not valid UTF-8"
    if not entry["checks"]:
        return True, ""
    scratch = tempfile.mkdtemp(prefix="wb-check-")
    try:
        for name in _docs_files(project):
            if name == path_rule.CONFIG:
                continue
            target = os.path.join(scratch, *name.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(project, *name.split("/")), target)
        target = os.path.join(scratch, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as f:
            f.write(data)
        for check in entry["checks"]:
            script = isolated.skill_script(root, entry["skill"], check[0])
            try:
                done = isolated.run_script(script, [a.replace("{path}", rel) for a in check[1:]], cwd=scratch,
                                           timeout=CHECK_TIMEOUT)
            except subprocess.TimeoutExpired:
                return False, f"{check[0]} did not finish in {CHECK_TIMEOUT} seconds"
            except OSError as e:
                return False, f"{check[0]} could not be run: {e.strerror or e}"
            if done.returncode != 0:
                said = (done.stdout + done.stderr).strip()[:OUTPUT_CHARS]
                return False, f"{check[0]} failed: {said or f'exit {done.returncode}'}"
        return True, ""
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _keep_aside(cfg: dict, rel: str, markdown: str) -> str:
    """Save a page's text that was not taken: <data_dir>/documents/not-taken/<rel>.<UTC time>.md."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = os.path.join(cfg["data_dir"], NOT_TAKEN, *rel.split("/"))
    os.makedirs(os.path.dirname(base), mode=0o700, exist_ok=True)
    target, n = f"{base}.{stamp}.md", 1
    while os.path.exists(target):
        n += 1
        target = f"{base}.{stamp}-{n}.md"
    with open(target, "w", encoding="utf-8") as f:
        f.write(markdown)
    return target


def _save_comments(ctx: dict, rel: str, page: dict) -> int:
    comments = page.get("comments") or []
    if not comments:
        return 0
    return ctx["store"].comments_save(ctx["conn"], comments, provider=ctx["cfg"][KEY]["provider"], subject="document",
                                      document_path=rel)["saved"]


def _put(ctx: dict, rel: str, **fields) -> dict:
    return ctx["store"].document_put(ctx["conn"], rel, provider=ctx["cfg"][KEY]["provider"], **fields)


def _read_page(ctx: dict, record: dict, out: dict) -> dict:
    page = call(ctx["cfg"], ctx["root"], "read", ["--id", record["remote_id"]])
    out["comments"] += _save_comments(ctx, record["path"], page)
    if "notice" in page and page["notice"] is None:
        _notice_seen(ctx["cfg"], record["path"], None)  # the page has none (any more): the next push adds it
    return page


def _notices(cfg: dict) -> dict:
    """{rel: page id} of the read_only pages known to carry NOTICE; {} when there is none or it cannot be read."""
    try:
        with open(os.path.join(cfg["data_dir"], NOTICES), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _notice_seen(cfg: dict, rel: str, ident) -> None:
    """Record that the page ident of rel carries NOTICE (ident None: that it does not)."""
    data = _notices(cfg)
    if data.get(rel) == ident:
        return
    if ident is None:
        data.pop(rel, None)
    else:
        data[rel] = ident
    path = os.path.join(cfg["data_dir"], NOTICES)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(temporary, path)


def _ensure_notice(ctx: dict, rel: str, record: dict, out: dict, dry_run: bool) -> None:
    """Add NOTICE to a read_only page that is not known to carry it (the provider's `notice` touches nothing else
    of the page). Its version then moves; the next pull reads the page once, finds the same text, and records it."""
    ident = record.get("remote_id")
    if not ident or record.get("status") == "rejected" or _notices(ctx["cfg"]).get(rel) == ident:
        return
    if dry_run:
        out["would"].append({"path": rel, "verb": "notice", "id": ident})
        return
    try:
        done = call(ctx["cfg"], ctx["root"], "notice", ["--id", ident, "--text", NOTICE, "--confirmed"])
    except DocumentsError as e:
        out["failed"].append({"path": rel, "reason": f"the notice: {e}"})
        return
    _notice_seen(ctx["cfg"], rel, ident)
    if done.get("added"):
        out["notices"].append(rel)


def _settle(ctx: dict, record: dict, entry, page: dict, out: dict) -> str:
    """Steps 3 to 7 of pull for a page that was read: what the page holds against what the runtime last read.
    Returns what happened: "unchanged", "not_taken", "conflict", "rejected" or "imported"."""
    rel, markdown, version = record["path"], page.get("markdown") or "", page.get("version")
    digest = _sha(markdown)
    if record.get("read_sha256") is None or digest == record["read_sha256"]:
        # Only the version moved (a comment), or there is no earlier look to compare with: the page is the base.
        fields = {"read_sha256": digest, "remote_version": version}
        if record.get("status") == "rejected" and record.get("read_sha256") is not None:
            fields.update(status=STATUS_OF[entry["platform"]] if entry else "read_only", note=None)
        _put(ctx, rel, **fields)
        return "unchanged"
    if entry is None or entry["platform"] == "read_only":
        # Never imported, and never written over while it differs (WP-3.21): the person settles it with take.
        _keep_aside(ctx["cfg"], rel, markdown)
        _put(ctx, rel, status="rejected", note=READ_ONLY_CHANGED, remote_version=version)
        out["rejected"].append({"path": rel, "note": READ_ONLY_CHANGED})
        return "rejected"
    current = _read_project(ctx["cfg"]["project"], rel)
    if current is None or _sha(current) != record.get("written_sha256"):
        _put(ctx, rel, status="rejected", note=BOTH_CHANGED)
        out["conflicts"].append(rel)
        return "conflict"
    ok, reason = check_edit(ctx["root"], ctx["cfg"]["project"], entry, rel, markdown)
    if not ok:
        _put(ctx, rel, status="rejected", note=reason, remote_version=version)
        out["rejected"].append({"path": rel, "note": reason})
        return "rejected"
    _import(ctx, rel, markdown, version)
    out["imported"].append(rel)
    return "imported"


def _import(ctx: dict, rel: str, markdown: str, version) -> None:
    """Write a page's text over the project's file and set both hashes to it, so that the next push sees nothing
    to write and the person's edit is not sent back through the conversion. The import is recorded (IMPORTED), so
    the next run of a task that reads the document is told the content is the person's (ops.task_prompt)."""
    data = markdown.encode("utf-8")
    _write_project(ctx["cfg"]["project"], rel, data)
    _put(ctx, rel, status="mirrored", note=None, written_sha256=_sha(data), read_sha256=_sha(data),
         remote_version=version)
    _record_import(ctx["cfg"], rel, _sha(data))


def _now() -> str:
    """The time in the store's own form (fixed-width UTC, to the microsecond), so it compares as text with a run's
    started_at."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _imports(cfg: dict) -> dict:
    """The record of imports, {rel: {"sha256", "at"}}; {} when there is none or it cannot be read."""
    try:
        with open(os.path.join(cfg["data_dir"], IMPORTED), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_import(cfg: dict, rel: str, digest: str) -> None:
    path = os.path.join(cfg["data_dir"], IMPORTED)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    data = _imports(cfg)
    data[rel] = {"sha256": digest, "at": _now()}
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(temporary, path)


def imported_since(cfg: dict, since) -> list:
    """The documents the mirror imported from the platform (a person's edit) after `since` (a time in the store's
    form, the start of a task's last run; None for a task's first run: any import), sorted, each only while the
    project's file is still what was imported. Read from the record of imports alone: never from a run's text."""
    out = []
    for rel, item in sorted(_imports(cfg).items()):
        if path_rule.normal(rel) != rel or not isinstance(item, dict) or not isinstance(item.get("at"), str) \
                or not isinstance(item.get("sha256"), str):
            continue
        if since is not None and item["at"] <= since:
            continue
        current = _read_project(cfg["project"], rel)
        if current is not None and _sha(current) == item["sha256"]:
            out.append(rel)
    return out


def pull(ctx: dict, dry_run: bool = False) -> dict:
    """The platform to the project (see the module's text), for every record that has a page. A dry run reads
    nothing. A call that fails raises DocumentsError: the platform cannot be read."""
    out = result()
    if dry_run:
        return out
    store, conn = ctx["store"], ctx["conn"]
    for record in store.documents_list(conn):
        if not record.get("remote_id"):
            continue
        seen = call(ctx["cfg"], ctx["root"], "stat", ["--id", record["remote_id"]])
        if seen.get("archived"):
            out["gone"].append(record["path"])
            continue
        if seen.get("version") == record.get("remote_version"):
            # No read: what keeps the conversion from wearing the document down. The version covers the content and
            # a comment may not move it (measured, N3), so the page's own comments are listed whatever the version.
            listed = call(ctx["cfg"], ctx["root"], "comments", ["--id", record["remote_id"]])
            out["comments"] += _save_comments(ctx, record["path"], listed)
            continue
        page = _read_page(ctx, record, out)
        _settle(ctx, record, entry_for(ctx["root"], record["path"]), page, out)
    return out


def _key(cfg: dict, rel: str, digest: str) -> str:
    store_hash = hashlib.sha256(cfg["store_db"].encode("utf-8")).hexdigest()[:12]
    return f"doc:{store_hash}:{rel}:{digest[:16]}"


def push(ctx: dict, rels, dry_run: bool = False) -> dict:
    """The project to the platform (see the module's text), for each path given that a manifest entry mirrors. A
    failed call for one path does not stop the others: it is listed in "failed" and its record is left as it was,
    so that the next sync tries again. With dry_run nothing is read and nothing changes: "would" holds what the
    provider printed for each write it would make."""
    cfg, store, conn, root = ctx["cfg"], ctx["store"], ctx["conn"], ctx["root"]
    out = result()
    if dry_run:
        out["would"] = []
    bounds = None if dry_run else project_config.bounds_problem(cfg, key=KEY)
    for rel in sorted(dict.fromkeys(rels)):
        entry = entry_for(root, rel)
        if entry is None:
            continue
        data = _read_project(cfg["project"], rel)
        if data is None:
            continue
        digest = _sha(data)
        record = store.document_get(conn, rel) or {}
        read_only = entry["platform"] == "read_only"
        if record.get("written_sha256") == digest:
            if read_only and not bounds:
                _ensure_notice(ctx, rel, record, out, dry_run)
            continue  # no write when the content did not change
        if record.get("status") == "rejected":
            continue  # waits for the person to settle it (take); pull reports it
        if bounds:
            out["failed"].append({"path": rel, "reason": bounds})
            continue
        try:
            if record.get("remote_id") and not dry_run:
                # Before every write: the page against what the runtime last wrote there. The text's hash is the
                # guard (a version is rounded to the minute, N1); a page that changed is never written over.
                page = _read_page(ctx, record, out)
                if record.get("read_sha256") is not None and _sha(page.get("markdown") or "") != record["read_sha256"]:
                    _settle(ctx, record, entry, page, out)
                    continue
            fd, markdown_file = tempfile.mkstemp(prefix="document-", suffix=".md")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                args = (["--id", record["remote_id"]] if record.get("remote_id") else []) + [
                    "--path", rel, "--markdown-file", markdown_file, "--idempotency-key", _key(cfg, rel, digest)] + (
                    ["--notice", NOTICE] if read_only else []) + ["--dry-run" if dry_run else "--confirmed"]
                written = call(cfg, root, "write", args)
            finally:
                try:
                    os.unlink(markdown_file)
                except OSError:
                    pass
            if dry_run:
                out["would"].append({"path": rel, **written})
                continue
            if not isinstance(written.get("id"), str) or not written["id"]:
                raise DocumentsError("failed", "the provider's write printed no id")
            if read_only:
                _notice_seen(cfg, rel, written["id"])
            try:
                back = call(cfg, root, "read", ["--id", written["id"]])
            except DocumentsError as e:
                # Written, and not read back: no base to compare a later page with; the next pull takes the page
                # as it is then as the base.
                _put(ctx, rel, remote_id=written["id"], written_sha256=digest, read_sha256=None, remote_version=None,
                     status=STATUS_OF[entry["platform"]], note=None)
                out["failed"].append({"path": rel, "reason": f"written, and not read back: {e}"})
                continue
            _put(ctx, rel, remote_id=written["id"], written_sha256=digest, read_sha256=_sha(back.get("markdown") or ""),
                 remote_version=back.get("version"), status=STATUS_OF[entry["platform"]], note=None)
        except DocumentsError as e:
            out["failed"].append({"path": rel, "reason": str(e)})
            continue
        out["pushed"].append(rel)
    return out


def mirrored_paths(ctx: dict) -> list:
    """Every file of the project's docs/ that a manifest entry mirrors."""
    return [rel for rel in _docs_files(ctx["cfg"]["project"]) if entry_for(ctx["root"], rel) is not None]


def blocked(ctx: dict, meta: dict) -> list:
    """[{"path", "note"}] of the rejected records among the declared inputs, outputs and updates of a skill
    (meta is skill_meta.declared())."""
    declared = list(meta["inputs"]) + list(meta["outputs"]) + list(meta["updates"])
    return [{"path": r["path"], "note": r.get("note")} for r in ctx["store"].documents_list(ctx["conn"])
            if r.get("status") == "rejected" and skill_meta.matches(declared, r["path"])]


def take(ctx: dict, rel: str, side: str) -> dict:
    """Settle a rejected record. side "page": the page's text replaces the project's file when the checker passes
    on it (when it fails, the record stays rejected with the new reason). side "project": the page's text is kept
    aside with its open comments saved, and the project's file is written over the page."""
    if side not in ("page", "project"):
        raise DocumentsError("refused", "take is page or project")
    record = ctx["store"].document_get(ctx["conn"], rel)
    if record is None or not record.get("remote_id") or record.get("status") != "rejected":
        raise DocumentsError("refused", f"{rel} has no rejected record: only a document that was not taken is settled")
    entry = entry_for(ctx["root"], rel)
    if entry is None:
        raise DocumentsError("refused", f"{rel} is not mirrored: no runtime manifest lists it")
    out = result()
    page = _read_page(ctx, record, out)
    markdown = page.get("markdown") or ""
    if side == "page":
        if entry["platform"] != "editable":
            # Never imported: the page stays as the person left it, and the file is not written over it until the
            # file itself changes again (the written hash is the file's own).
            current = _read_project(ctx["cfg"]["project"], rel)
            _put(ctx, rel, status=STATUS_OF[entry["platform"]], note=KEPT_AS_IS, read_sha256=_sha(markdown),
                 written_sha256=None if current is None else _sha(current), remote_version=page.get("version"))
            out["not_taken"].append(rel)
            return out
        ok, reason = check_edit(ctx["root"], ctx["cfg"]["project"], entry, rel, markdown)
        if not ok:
            _put(ctx, rel, status="rejected", note=reason, remote_version=page.get("version"))
            out["rejected"].append({"path": rel, "note": reason})
            return out
        _import(ctx, rel, markdown, page.get("version"))
        out["imported"].append(rel)
        return out
    _keep_aside(ctx["cfg"], rel, markdown)
    out["not_taken"].append(rel)
    _put(ctx, rel, written_sha256=None, read_sha256=_sha(markdown), remote_version=page.get("version"),
         status=STATUS_OF[entry["platform"]], note=None)
    pushed = push(ctx, [rel])
    for key in ("pushed", "failed", "conflicts", "rejected", "not_taken", "imported", "notices"):
        out[key] += [v for v in pushed[key] if v not in out[key]]
    out["comments"] += pushed["comments"]
    return out


def merged(*results) -> dict:
    """Several results of pull, push or take as one."""
    out = result()
    for one in results:
        for key, value in (one or {}).items():
            if key == "comments":
                out[key] += value
            else:
                out.setdefault(key, [])
                out[key] = out[key] + list(value)
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
