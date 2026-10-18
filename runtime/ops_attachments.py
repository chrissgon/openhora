#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations over the files a listed sender sent through a messaging app (package ATT-1): list what is held, hold a file the bridge fetched,
add a held file as a version of a source, discard it. The limits, the sentences and the folders are runtime/attachments.py; the version itself is
made by runtime/ops_sources.py (import_bytes) like any other, with a provenance; the bridge's part is runtime/messaging_attach.py.

  attachments(project)                                   the held files, the latest decisions, the day's count and the limits (every channel
                                                         that lists the row; the bridge reads it for its checks before a fetch)
  attachment_hold(project, incoming, platform, ref, name, ...)   the messaging bridge's call, after it fetched a file into an incoming folder it made:
                                                         the intake bounds it, reads its type from its bytes and hashes it; the file is kept
                                                         under held/<id>/ and recorded; with the grant `add-sources-direct` it is added at once
  attachment_add(project, attachment_id)                 add a held file: a new source, or a new version of the source it names. The held file is
                                                         deleted whatever the result
  attachment_discard(project, attachment_id)             delete a held file

Who may call what is the table of operations (runtime/operations.py: the group `add-sources`, the grant `add-sources-direct`) and, for a messaging
sender, `ops_actor.guard` (the profile of THAT sender, read from the configuration loaded for this call). `attachment-hold` is the messaging bridge's
alone: the function refuses any other channel. Nothing here follows an instruction in a file or in its name or caption; the name is cleaned and cut,
the converted text reaches a model only through the catalog and the copies of a task, and a reply never carries the file's content.

A refusal is an OpsError whose message is the sentence the person reads (the bridge sends it as it is). A file the intake or the conversion refuses
is deleted and its row ends `refused` with a code of attachments.CODES; a problem of this machine that is not the file's (the sources folder is
not usable, another host holds its lease) leaves the file held, so that it can be added once that is mended.

Sibling of runtime/ops.py, which exposes the operations under their names. The shared names come from ops_core, read as `core.<name>` at call
time. It reaches no operation of ops.py. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import attachments as att  # noqa: E402
import intake  # noqa: E402
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402
import ops_sources  # noqa: E402
import sources  # noqa: E402

RECENT = 20
FILE_CODES = ("credential", "size", "type", "convert", "macro")     # the codes of a SourcesError that are the file's doing: the file is refused and deleted
                                                                      # (`convert` is the converter refusing the file's content; `converter`, the machine failing to run it, is not)
REASONS = {"credential": "it holds what looks like a credential", "size": "its text is too large for one source",
           "convert": "it could not be read as a document", "macro": "it holds macros, which are never converted", "type": "it is not a type that is read as a source",
           "changed": "it changed on this machine while it waited", "mismatch": "its bytes are not what it says", "target": "the source it names is not a file source"}
LIMITS = {"file_cap": att.FILE_CAP, "day_files": att.DAY_FILES, "day_bytes": att.DAY_BYTES, "held_max": att.HELD_MAX,
          "per_message": att.PER_MESSAGE, "held_days": att.HELD_DAYS}


def _fail(sentence: str, code: int = 1) -> "core.OpsError":
    return core.OpsError(sentence, code)


class MachineProblem(core.OpsError):
    """A problem of this machine that is not the file's (the data folder, the sources folder, a lease, a converter that cannot run). The message is for the
    terminal and the page, which may show a path; `phone` is the sentence a messaging app gets, with none."""

    def __init__(self, message: str, code: int = 1, phone: str = att.MACHINE):
        super().__init__(message, code)
        self.phone = phone


def _own(row: dict, channel, sender) -> None:
    """On a messaging app a sender decides only the files THEY sent: the row's platform and sender must be the acting sender's. A file of someone else is
    answered as one that does not exist, so that the answer tells nothing of it."""
    if channel != att.CHANNEL:
        return
    platform, ident = ops_actor.split(sender)
    if row["platform"] != platform or row["sender"] != ident:
        raise _fail(att.NO_SUCH.format(n=row["id"]))


def _held(ctx: dict, attachment_id, channel=None, sender=None) -> dict:
    """The held attachment of an id, or the refusal that says there is none waiting (and, from a messaging app, none of the sender's)."""
    if type(attachment_id) is not int or attachment_id < 1:
        raise _fail("an attachment is a whole number", 2)
    try:
        row = ctx["store"].attachment_get(ctx["conn"], attachment_id)
    except ctx["store"].StoreError:
        raise _fail(att.NO_SUCH.format(n=attachment_id)) from None
    _own(row, channel, sender)
    if row["status"] != "held":
        raise _fail(att.NOT_HELD.format(status=row["status"]))
    return row


def _decide(ctx: dict, row: dict, status: str, **fields) -> dict:
    return core._stored(ctx, ctx["store"].attachment_decide, row["id"], status, **fields)


def attachments(project: str, channel: str | None = None, sender: str | None = None) -> dict:
    """The files held for an answer (oldest first), the latest decisions (newest first) and the day's count. Returns {"held": [...], "recent": [...],
    "today": {"files", "bytes"}, "limits": {...}}; a row never carries the sender's id. From a messaging app (`channel`, and the `sender` who asks) the lists hold
    only the files THAT sender sent; the terminal and the page, which are the person's own, see them all. The bridge's own checks read the whole list with no
    channel (outside the policy, like `pending`)."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "attachments", channel, sender)
    store, conn = ctx["store"], ctx["conn"]
    held = core._stored(ctx, store.attachments_list, ["held"])
    recent = core._stored(ctx, store.attachments_list, ["added", "refused", "discarded", "expired"], RECENT)
    if channel == att.CHANNEL:
        platform, ident = ops_actor.split(sender)
        held, recent = [r for r in held if (r["platform"], r["sender"]) == (platform, ident)], [r for r in recent if (r["platform"], r["sender"]) == (platform, ident)]
    return {"held": [att.public(r) for r in held], "recent": [att.public(r) for r in reversed(recent)],
            "today": core._stored(ctx, store.attachments_since, att.day_start()), "limits": dict(LIMITS)}


def _registered(ctx: dict) -> dict:
    """The registry by id: {"id": {"type", "version" (the newest or None)}}."""
    return {r["id"]: r for r in sources.list_catalog(ctx, hashes=False)}


def _target(ctx: dict, wanted, name: str) -> tuple:
    """(source id, label) the file would become: the id the caption named, else an id made from the name that no source and no held file has.
    A caption naming a Notion or Drive source is refused (TARGET_TYPE). The label is `refresh` for a source that has a version, else `import`."""
    known = _registered(ctx)
    if wanted is not None:
        if wanted in known:
            if known[wanted]["type"] != "file":
                raise _fail(att.TARGET_TYPE.format(id=wanted, type=known[wanted]["type"]))
            return wanted, "refresh" if known[wanted]["version"] else "import"
        return wanted, "import"
    held_targets = [r["target"] for r in core._stored(ctx, ctx["store"].attachments_list, ["held"]) if r.get("target")]
    return sources.source_id_from_name(att.stem(name), list(known) + held_targets, "file"), "import"


def _record(ctx: dict, platform: str, digest: str, ident: str, profile: str, name: str, declared, declared_bytes, kind, sha, size, code: str) -> None:
    """Record a fetch that did not end held (a file a rule refused after its bytes arrived, or a fetch that failed): it counts against the day's files and
    bytes, because the bandwidth and the disk were spent. The row is `refused` with its code and keeps no file; it stores what a held row stores (the
    cleaned name, the platform's reference as a hash, the sender)."""
    try:
        ctx["store"].attachment_add(ctx["conn"], platform=platform, ref_sha256=digest, sender=ident, profile=profile, name=name, declared_type=declared,
                                    declared_bytes=declared_bytes, kind=kind, sha256=sha, size=size, target=None, label=None, status="refused",
                                    code=code, created_at=att.iso(att.utcnow()))
    except ctx["store"].StoreError:
        pass


def _refuse(ctx: dict, platform: str, digest: str, ident: str, profile: str, name: str, declared, declared_bytes, kind, sha, size, code: str,
            sentence: str) -> "core.OpsError":
    """_record, and the refusal to raise."""
    _record(ctx, platform, digest, ident, profile, name, declared, declared_bytes, kind, sha, size, code)
    return _fail(sentence)


def attachment_hold(project: str, incoming: str | None, platform: str, ref: str, name: str, declared_type: str | None = None,
                    declared_bytes: int | None = None, target: str | None = None, direct: bool = False, max_bytes: int | None = None,
                    failed: str | None = None, fetched_bytes: int | None = None, channel: str | None = None,
                    sender: str | None = None) -> dict:
    """Hold the file the messaging bridge fetched into the incoming folder `incoming` (attachments.make_incoming): bound by the intake (length, free
    space, one at a time with the page's uploads), its type read from its bytes and its hash made as it streams, compared with the type the platform
    declared, recorded, and kept under held/<id>/. `ref` is the platform's reference (only its hash is stored), `name` what the platform called the file
    (cleaned and cut), `target` the source id the caption named (`@<id>` alone) or None, `direct` true when the sender's profile has the grant
    `add-sources-direct` and the file is to be added at once (checked here against the profile). The incoming folder is removed whatever happens.
    `max_bytes` is the cap the fetch ran under (the provider's, the day's bytes left): the intake bounds the file by the least of it and the 25 MiB.
    With `failed` (a word of attachments.FAILED_FETCH) the fetch did not end in a file: nothing is held, the attempt is recorded as a refused row with
    `fetched_bytes` (what was allowed or written) so that it counts against the day's files and bytes, and {"recorded": True, "code"} is returned.
    Returns {"attachment": row, "held": True, "target", "label", "next_version", "card_sha256"} and, when `direct`, {"added": the add's answer}; a direct
    request for a source that already exists is held with a card instead ("direct_declined"): the grant makes new sources, never a new version."""
    if channel != att.CHANNEL:
        raise _fail("attachment-hold is the messaging bridge's call", 1)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    try:
        ops_actor.guard(ctx, "attachment-hold", channel, sender)
        if direct and not operations.granted("attachment-hold", channel, cfg["channels"], "direct", sender):
            raise _fail(operations.not_enabled("add-sources-direct", channel))
        who, ident = ops_actor.split(sender)
        if who != platform or not isinstance(ref, str) or not ref:
            raise _fail("the platform and the reference must be the sender's own", 2)
        if failed is not None:
            return _failed_fetch(ctx, platform, ref, att.clean_name(name), declared_type, declared_bytes, failed, fetched_bytes, ident, sender)
        try:
            folder = att.incoming_path(cfg["data_dir"], incoming)
        except att.FolderError:
            raise _fail(att.GONE.format(platform=platform)) from None
        return _hold(project, ctx, folder, platform, ref, att.clean_name(name), declared_type, declared_bytes, target, bool(direct), max_bytes, ident, sender)
    finally:
        if incoming is not None:
            att.remove_incoming(cfg["data_dir"], incoming)      # whatever happens, a refused call too: the folder is ours and a fetched file waits nowhere else


def _failed_fetch(ctx, platform, ref, name, declared, declared_bytes, failed, fetched_bytes, ident, sender) -> dict:
    """Record a fetch that ended with no file: the bridge reports it (gone, failed, over the cap, or refused after the provider answered), and the attempt counts
    against the day's files, with the bytes it was allowed or wrote."""
    if failed not in att.FAILED_FETCH:
        raise _fail(f"a failed fetch is one of {', '.join(att.FAILED_FETCH)}", 2)
    size = fetched_bytes if type(fetched_bytes) is int and fetched_bytes >= 0 else 0
    _record(ctx, platform, att.ref_digest(platform, ref, ident), ident, ops_actor.profile_of(ctx["cfg"], sender), name, att.media_type(declared) or None,
            declared_bytes if type(declared_bytes) is int and declared_bytes >= 0 else None, None, None, min(size, att.FILE_CAP), failed)
    return {"recorded": True, "code": failed}


def _hold(project, ctx, folder, platform, ref, name, declared, declared_bytes, wanted, direct, max_bytes, ident, sender) -> dict:
    store, cfg = ctx["store"], ctx["cfg"]
    profile = ops_actor.profile_of(cfg, sender)
    digest = att.ref_digest(platform, ref, ident)
    declared_kind = att.media_type(declared) or None
    declared_size = declared_bytes if isinstance(declared_bytes, int) and not isinstance(declared_bytes, bool) else None
    try:
        stream, length = att.open_content(folder)
    except att.FolderError:
        raise _fail(att.GONE.format(platform=platform)) from None
    with stream:
        later = {"platform": platform, "digest": digest, "ident": ident, "profile": profile, "name": name, "declared": declared_kind,
                 "declared_bytes": declared_size}

        def refuse(kind, sha, code, sentence):
            return _refuse(ctx, later["platform"], later["digest"], later["ident"], later["profile"], later["name"], later["declared"],
                           later["declared_bytes"], kind, sha, length, code, sentence)
        found = core._stored(ctx, store.attachment_held_by_ref, platform, digest)
        if found is not None:
            raise refuse(None, None, "duplicate", att.DUPLICATE.format(name=name, id=found["id"]))      # fetched twice (delivery is at least once): the second fetch counts
        problem = att.declared_problem({"type": declared, "size": declared_size}, att.FILE_CAP)      # what the bridge checked before the fetch, checked again by the authority
        if problem is not None:
            raise refuse(None, None, problem["code"], att.MEDIA if problem["code"] == "media" else att.TOO_LARGE.format(
                name=name, size=att.size_text(problem["size"]), cap=att.size_text(att.FILE_CAP)))
        today = core._stored(ctx, store.attachments_since, att.day_start())
        waiting = len(core._stored(ctx, store.attachments_list, ["held"]))
        if today["files"] >= att.DAY_FILES or today["bytes"] >= att.DAY_BYTES:
            raise refuse(None, None, "day", att.DAY.format(n=today["files"], size=att.size_text(today["bytes"])))
        if waiting >= att.HELD_MAX:
            raise refuse(None, None, "held_max", att.HELD_FULL.format(n=waiting))
        cap = min(att.FILE_CAP, max_bytes if type(max_bytes) is int and max_bytes >= 1 else att.FILE_CAP, max(1, att.DAY_BYTES - today["bytes"]))
        try:
            received = intake.stream_in(stream, length, folder, cap=cap, minimum=1, accept=sources.accept_type,
                                        lock_path=sources.upload_lock_path(cfg))
        except intake.IntakeError as e:
            if e.code == "refused":
                raise refuse(None, None, "busy", att.BUSY) from None      # the page is uploading: this fetch is over and counts, the file is sent again
            code = "type" if e.code == "type" else "size"
            raise refuse(None, None, code, att.REFUSED.format(name=name, reason=str(e).rstrip("."))) from None
    sniffed = received.type[1]
    if att.mismatch(declared, sniffed):
        raise refuse(sniffed, received.sha256, "mismatch", att.MISMATCH.format(name=name, declared=att.media_type(declared),
                                                                               sniffed=att.SUBTYPE_WORDS.get(sniffed, sniffed)))
    try:
        chosen, label = _target(ctx, wanted, name)
    except core.OpsError as e:
        raise refuse(sniffed, received.sha256, "target", str(e)) from None
    declined = False
    if direct and wanted is not None and wanted in _registered(ctx):
        direct, declined = False, True       # the grant makes new sources and never a new version of one that exists: that waits for a card
    try:
        row = store.attachment_add(ctx["conn"], platform=platform, ref_sha256=digest, sender=ident, profile=profile, name=name, declared_type=declared_kind,
                                   declared_bytes=later["declared_bytes"], kind=sniffed, sha256=received.sha256, size=received.size,
                                   target=chosen, label=label, direct=direct, created_at=att.iso(att.utcnow()))
    except store.StoreError as e:
        if "already held" in str(e):
            raise refuse(sniffed, received.sha256, "duplicate", att.DUPLICATE.format(name=name, id=(core._stored(ctx, store.attachment_held_by_ref, platform, digest)
                                                                                                      or {}).get("id", "?"))) from None
        raise _fail(str(e)) from None
    try:
        att.keep_held(cfg["data_dir"], row["id"], folder, os.path.basename(received.path))
    except att.FolderError as e:
        _decide(ctx, row, "refused", code="lost")
        raise MachineProblem(f"{name} could not be kept on this machine: {e}", 1, att.KEPT_FAILED.format(name=name)) from None
    known = _registered(ctx).get(chosen) or {}
    out = {"attachment": att.public(row), "held": True, "target": chosen, "label": label,
           "next_version": (known.get("versions") or 0) + 1, "card_sha256": att.card_sha256(received.sha256, chosen, label)}
    if declined:
        out["direct_declined"] = True
    if direct:
        with intake.Lock(att.lock_path(cfg)):
            out["added"] = _add(project, ctx, row, sender)
    return out


def _file_caused(error: "core.OpsError") -> str | None:
    """The code of the attachments a refusal of the import is the file's doing, or None for a problem of this machine (the sources folder, a lease,
    a converter that is not set up): then the file stays held."""
    why = getattr(error, "why", None)
    if why == "convert" and "the package holds macros" in str(error):       # the converter's refusal of a macro-enabled Office package (ATT-5)
        return "macro"
    return why if why in FILE_CODES else None


def _add(project: str, ctx: dict, row: dict, sender) -> dict:
    """Add a held file as a version of its source and end its hold: the file's bytes are read back and hashed against the row, the source it
    names is looked at again, and `ops_sources.import_bytes` makes the version with a provenance that names the platform and the profile and never
    the sender. The held file is deleted whatever the result (but a problem of this machine, which leaves it held)."""
    cfg, store = ctx["cfg"], ctx["store"]
    name = row["name"]
    if row["created_at"] < att.expired_before():
        _decide(ctx, row, "expired")
        att.delete_held(cfg["data_dir"], row["id"])
        raise _fail(att.EXPIRED.format(name=name, days=att.HELD_DAYS))
    data = att.read_held(cfg["data_dir"], row["id"])
    if data is None:
        _decide(ctx, row, "refused", code="lost")
        raise _fail(att.LOST)
    if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
        _decide(ctx, row, "refused", code="changed")
        att.delete_held(cfg["data_dir"], row["id"])
        raise _fail(att.REFUSED.format(name=name, reason=REASONS["changed"]))
    known = _registered(ctx).get(row["target"])
    if known is not None and known["type"] != "file":
        _decide(ctx, row, "refused", code="target")
        att.delete_held(cfg["data_dir"], row["id"])
        raise _fail(att.TARGET_TYPE.format(id=row["target"], type=known["type"]))
    if ("refresh" if known and known["version"] else "import") != row["label"]:
        raise _fail(att.TARGET_CHANGED.format(id=row["target"], n=row["id"]))
    provenance = {"channel": att.CHANNEL, "platform": row["platform"], "attachment": row["id"],
                  "profile": row["profile"] if row["profile"] and row["profile"] != "default" else None}
    try:
        done = ops_sources.import_bytes(project, row["target"], name, data, provenance, origin=name)
    except core.OpsError as e:
        code = _file_caused(e)
        if code is None:
            raise MachineProblem(str(e), e.code) from None
        _decide(ctx, row, "refused", code=code)
        att.delete_held(cfg["data_dir"], row["id"])
        raise _fail(att.REFUSED.format(name=name, reason=REASONS[code])) from None
    version = done["version"]
    _decide(ctx, row, "added", source_id=row["target"], version=version)
    att.delete_held(cfg["data_dir"], row["id"])
    warnings = list(done.get("warnings") or [])
    imported = bool(done.get("imported"))
    sentence = (att.ADDED if imported else att.ADDED_SAME).format(name=name, id=row["target"], n=version)
    return {"added": True, "imported": imported, "source": row["target"], "version": version, "label": row["label"], "warnings": warnings,
            "reply": "\n".join([sentence] + [f"Note: {w}" for w in warnings])}


def attachment_add(project: str, attachment_id: int, channel: str | None = None, sender: str | None = None) -> dict:
    """Add a held file as a source, or as the next version of the source it names (the one its caption named when it was sent, else a new source
    whose id is made from its name). The converter container, the credential scan of the converted text, the hidden-text flag and the size warning
    are the import's. Returns {"added": True, "imported", "source", "version", "label", "warnings", "reply"}; a refusal is an OpsError with the
    sentence (the file is then deleted and its row `refused`, but for a problem of this machine, which leaves it held)."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "attachment-add", channel, sender)
    with intake.Lock(att.lock_path(ctx["cfg"])):
        row = _held(ctx, attachment_id, channel, sender)
        return _add(project, ctx, row, sender)


def attachment_discard(project: str, attachment_id: int, channel: str | None = None, sender: str | None = None) -> dict:
    """Delete a held file and end its hold as `discarded`. Returns {"discarded": True, "attachment": row, "reply"}."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "attachment-discard", channel, sender)
    with intake.Lock(att.lock_path(ctx["cfg"])):
        row = _held(ctx, attachment_id, channel, sender)
        done = _decide(ctx, row, "discarded")
        att.delete_held(ctx["cfg"]["data_dir"], row["id"])
    return {"discarded": True, "attachment": att.public(done), "reply": att.DISCARDED.format(name=row["name"])}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
