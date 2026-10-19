#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""References to one item of a mail or calendar snapshot (package SNAP-IDX, SPEC-SECRETARY-WRITES 3.4). A request to change something in the
person's own mailbox or calendar says WHICH message or event by a reference, never by the words of its text:

  <source id>#<n>      the n-th item of the newest version of a registered `mail` or `calendar` source, as the snapshot's text numbers it
                       (a mail text prints `## 3. ...`; a calendar text prints `3. 09:00-10:00 · ...`, the numbers following the order of
                       snapshot_text.calendar_order, which is the order of the index)
  created:<number>     the event the runtime created when card <number> was approved (its provider id is in that effect's recorded result);
                       resolved by the calendar write path, through the `created` function this module is given

Code resolves a reference through the INDEX that runtime/sources_mail.py writes into the manifest of each snapshot version: {n, id, thread_id,
message_id, from_address, reply_to_address, subject, change_key} for a message, {n, id, etag, calendar, organizer_self, attendees_other,
recurring} for an event. The index is code's own record of what the provider printed; the text is another person's words and is never parsed
for an id. A reference to a snapshot older than REF_MAX_AGE (the age limit L53 allows an unattended task, 26 hours) is refused with "refresh
<id> first": a number from an old reading may name another item today. A version made before the index existed has none, and is refused the
same way.

What ties the index to the store. The manifest is a file of the sources folder, and the store does not record its hash; the TEXT is hashed (limit
L25: verify_version). So the sha256 of the index is a line of the text (snapshot_text.DIGEST_PREFIX, among its first lines), and read_index
refuses (`integrity`) an index whose digest is not that line, a text whose hash is not the store's record, a manifest that names another source,
version, text or origin than the store's row, and a calendar entry for a calendar the source's origin does not name. Every value of an entry is
read back through its closed shape too (an id or key by full match, an address of the plain shape, a subject cleaned like the write side does:
control, format and direction characters out, links replaced, cut at 120 characters).

Who may use a reference. A `<source id>#<n>` points into a snapshot of the person's mailbox or calendar, so it is usable only by a caller who may
read that snapshot: the terminal, the conversation and the page (as for `/ask @<id>`, runtime/ops_ask.py SNAPSHOT_ASKERS), and a messaging
sender whose profile lists the group `ask-mail` (SPEC-NATURAL-REQUESTS; no profile can list it before that group exists). Every other caller is
refused with `not_readable`, before anything is read. `channel` is required: a caller that has none says so with None, as the operations do.

External content is data: the index is another person's words and ids in a closed shape; nothing here calls a provider or writes anything. It
reads the sources folder through sources.Folder (limits L21 to L25: no link followed, the version's files hashed against the record first).

Result of resolve for `<source id>#<n>`: {"kind": "item", "source", "type" ("mail" or "calendar"), "implementation" (from the SOURCE ROW's origin:
"gmail", "outlook" or "google"), "calendar" (a calendar source: the calendar id of the origin) or "box" (a mail source: the box of the origin),
"version", "read_at" (when the snapshot was read), "age" (seconds), "n", "count", "entry"}. For `created:<number>`: {"kind": "created", "pending",
"type": "calendar", "entry"} as the `created` function answers. Every refusal is an ItemRefError with a stable `code` and a plain English
sentence; the operation that asked turns it into its reply.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import operations  # noqa: E402
import ops_actor  # noqa: E402
import snapshot_text as text  # noqa: E402
import sources  # noqa: E402
import sources_mail  # noqa: E402

REF_MAX_AGE = sources.SNAPSHOT_MAX_AGE            # seconds: 26 hours, the number of limit L53
MANIFEST_CAP = 4 * 1024 * 1024                    # the most a manifest file may hold (a hundred messages are a few hundred KiB)
INDEX_KEYS = {"mail": ("n", "id", "thread_id", "message_id", "from_address", "reply_to_address", "subject", "change_key"),
              "calendar": ("n", "id", "etag", "calendar", "organizer_self", "attendees_other", "recurring")}
COUNT_KEY = {"mail": "messages", "calendar": "events"}
SUBJECT_MAX = 120
# Who may use a reference into a snapshot (see the module's text): the actors that may name a snapshot with /ask @<id>, and the group that lets a
# messaging sender read one.
SNAPSHOT_READERS = (None, "terminal", "chat", "page")
READ_GROUP = "ask-mail"

ITEM_REF = re.compile(r"([a-z0-9][a-z0-9-]{0,39})#([0-9]{1,4})")
CREATED_REF = re.compile(r"created:([1-9][0-9]{0,8})")

# The closed shapes of an entry's values, the same as runtime/sources_mail.py writes (checked again on the way out).
ID = re.compile(r"[A-Za-z0-9_=+.-]{1,700}")
KEY = re.compile(r"[\x21-\x7e]{1,200}")
MESSAGE_ID = re.compile(r"[\x21-\x7e]{1,998}")
CALENDAR = re.compile(r"[A-Za-z0-9._%+#@=-]{1,256}")


class ItemRefError(Exception):
    """A reference that cannot be resolved. `code`: malformed, zero, not_readable, past_end, no_source, not_snapshot, wrong_kind, no_version, stale,
    no_index, integrity, created_unavailable, created_unknown."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# --- parsing ----------------------------------------------------------------------------------------------------------------------


def parse(value) -> dict:
    """The parts of a reference: {"kind": "item", "source", "n"} or {"kind": "created", "pending"}. ItemRefError (malformed, zero) for anything
    else: the grammar is closed, and a number with a leading zero or a sign is not one."""
    raw = value.strip() if isinstance(value, str) else ""
    found = CREATED_REF.fullmatch(raw)
    if found:
        return {"kind": "created", "pending": int(found.group(1))}
    found = ITEM_REF.fullmatch(raw)
    if found:
        source, digits = found.group(1), found.group(2)
        if int(digits) == 0:
            raise ItemRefError("zero", f"the numbers of a snapshot start at 1: {source}#1 is its first item, and {raw} names none")
        if digits != str(int(digits)):
            raise ItemRefError("malformed", f"{_show(raw)} is not a reference: write the number without a leading zero, for example {source}#{int(digits)}")
        return {"kind": "item", "source": source, "n": int(digits)}
    raise ItemRefError("malformed", f"{_show(raw)} is not a reference to an item: write <source id>#<number>, for example inbox#3, "
                                    "or created:<card number> for an event you created")


def _show(raw: str) -> str:
    """A reference that was refused, on one line and short, for a sentence (it is the asker's text, shown back and never used)."""
    one = text.one_line(raw, 60)
    return '"' + one + '"'


# --- who may use a reference ----------------------------------------------------------------------------------------------------------


def may_read(ctx: dict, channel, sender=None) -> bool:
    """Whether a caller may use a reference into a snapshot of the mailbox or the calendar: the terminal, the conversation and the page, a call with
    no channel (the operations' own), and a messaging sender whose groups list READ_GROUP. The MCP mode and any other caller may not."""
    cfg = ctx["cfg"]
    actor = ops_actor.label(cfg, channel, sender)
    if actor in SNAPSHOT_READERS:
        return True
    if channel == ops_actor.MESSAGING:
        groups = operations.effective_groups(ops_actor.MESSAGING, cfg.get("channels"), sender)
        return bool(groups) and READ_GROUP in groups
    return False


# --- reading the index ------------------------------------------------------------------------------------------------------------


def _shaped(pattern, value):
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _entry(kind: str, n: int, raw) -> dict:
    """A clean copy of one stored entry: only the keys of its kind, each value checked against its closed shape or null. The number must be the
    entry's place in the list."""
    if not isinstance(raw, dict) or raw.get("n") != n or type(raw.get("n")) is not int:
        raise ItemRefError("integrity", "the index of this snapshot does not match its numbering: refresh it, then ask again")
    if kind == "mail":
        return {"n": n, "id": _shaped(ID, raw.get("id")), "thread_id": _shaped(ID, raw.get("thread_id")),
                "message_id": _shaped(MESSAGE_ID, raw.get("message_id")), "from_address": text.plain_address(raw.get("from_address")),
                "reply_to_address": text.plain_address(raw.get("reply_to_address")),
                "subject": text.one_line(raw.get("subject"), SUBJECT_MAX) if isinstance(raw.get("subject"), str) else "",
                "change_key": _shaped(KEY, raw.get("change_key"))}
    others = raw.get("attendees_other")
    return {"n": n, "id": _shaped(ID, raw.get("id")), "etag": _shaped(KEY, raw.get("etag")), "calendar": _shaped(CALENDAR, raw.get("calendar")),
            "organizer_self": raw.get("organizer_self") is True, "attendees_other": others if type(others) is int and others >= 0 else None,
            "recurring": raw.get("recurring") is True}


def read_index(ctx: dict, source_id: str, *, channel, sender=None, kinds=None, evidence_base=None, clock=None) -> dict:
    """The index of the newest version of a registered mail or calendar source, after the checks a reference needs. Returns {"source", "type",
    "implementation", "calendar" or "box" (from the source row's origin), "version", "read_at" (the version's reading time), "age" (seconds),
    "entries": [clean entries, numbered from 1]}. `channel` and `sender` are the caller's (see may_read); `kinds` limits the types the caller accepts
    (("mail",) for an operation on messages). ItemRefError: not_readable, no_source, not_snapshot, wrong_kind, no_version, stale (older than
    REF_MAX_AGE, or a reading time that cannot be trusted), no_index (a version made before the index existed), integrity (the version's files do
    not hash to the record, the index does not match its digest, or the manifest does not belong to the store's row). SourcesError for the
    guardrails of the folder itself. `clock` is the seam of sources.snapshot_age."""
    if not may_read(ctx, channel, sender):
        raise ItemRefError("not_readable", f"{source_id} is a snapshot of your mailbox or calendar, and this channel may not read it: ask in the terminal "
                                           "or on the page, or have the project's configuration give the sender the group ask-mail")
    row = None
    try:
        row = sources._stored(ctx, "source_get", source_id)
    except sources.SourcesError:
        pass
    if row is None:
        raise ItemRefError("no_source", f"there is no source {source_id}: the references name a registered mail or calendar source")
    kind = row["type"]
    if kind not in sources.SNAPSHOT_TYPES:
        raise ItemRefError("not_snapshot", f"{source_id} is not a mail or calendar source: only those have numbered items")
    if kinds is not None and kind not in kinds:
        raise ItemRefError("wrong_kind", f"{source_id} is a {kind} source, and this needs {' or '.join(kinds)}")
    try:
        origin = sources_mail.origin_of(kind, row["origin"])
    except sources.SourcesError:
        raise ItemRefError("integrity", f"the origin of {source_id} is not one this runtime reads: {source_id} cannot be referred to") from None
    latest = sources._stored(ctx, "source_latest", source_id)
    if latest is None:
        raise ItemRefError("no_version", f"{source_id} has no snapshot yet: refresh {source_id} first")
    age = sources.snapshot_age(latest["imported_at"], clock)
    if age is None or age > REF_MAX_AGE:
        raise ItemRefError("stale", f"the newest snapshot of {source_id} was read at {latest['imported_at']}, more than {REF_MAX_AGE // 3600} hours ago "
                                    f"or at a time that cannot be trusted: refresh {source_id} first")
    version = str(latest["version"])
    with sources.Folder(ctx["cfg"], evidence_base) as folder:
        if not sources.verify_version(folder, latest)["ok"]:
            raise ItemRefError("integrity", f"the files of {source_id} (version {version}) were changed outside the runtime: refresh {source_id} first")
        try:
            manifest = json.loads(folder.read([source_id, version, "manifest.json"], MANIFEST_CAP).decode("utf-8"))
            converted = folder.read([source_id, version, latest["converted_name"]], sources.CONVERTED_CAP)
        except (sources.SourcesError, ValueError):
            raise ItemRefError("integrity", f"the manifest of {source_id} (version {version}) cannot be read: refresh {source_id} first") from None
    if hashlib.sha256(converted).hexdigest() != latest["converted_sha256"]:
        raise ItemRefError("integrity", f"{source_id} changed while it was being read: ask again")
    if not isinstance(manifest, dict) or manifest.get("source") != source_id or manifest.get("version") != latest["version"] \
            or (manifest.get("converted") or {}).get("sha256") != latest["converted_sha256"] or manifest.get("origin") != row["origin"]:
        raise ItemRefError("integrity", f"the manifest of {source_id} does not belong to its newest version: refresh {source_id} first")
    stored = manifest.get("index")
    digest = text.digest_of_text(converted.decode("utf-8", errors="replace"))
    if not isinstance(stored, list) or digest is None:
        raise ItemRefError("no_index", f"the newest snapshot of {source_id} was made before items could be referred to: refresh {source_id} first")
    if text.index_digest(stored) != digest:
        raise ItemRefError("integrity", f"the index of {source_id} is not the one its text records: refresh {source_id} first")
    if len(stored) != manifest.get(COUNT_KEY[kind]):
        raise ItemRefError("integrity", f"the index of {source_id} does not count the items its text lists: refresh {source_id} first")
    entries = [_entry(kind, number, raw) for number, raw in enumerate(stored, 1)]
    if kind == "calendar" and any(entry["calendar"] != origin["calendar"] for entry in entries):
        raise ItemRefError("integrity", f"the index of {source_id} names a calendar that its origin does not: refresh {source_id} first")
    where = {"calendar": origin["calendar"]} if kind == "calendar" else {"box": origin["box"]}
    return {"source": source_id, "type": kind, "implementation": origin["implementation"], **where, "version": latest["version"],
            "read_at": latest["imported_at"], "age": age, "entries": entries}


# --- resolving --------------------------------------------------------------------------------------------------------------------


def resolve(ctx: dict, value, *, channel, sender=None, kinds=None, evidence_base=None, clock=None, created=None) -> dict:
    """The item a reference names (the result's shape is in the module's text). `channel` and `sender` are the caller's (see may_read); a `created:`
    reference is not a snapshot and needs no reading right. `created(ctx, pending)` answers it (the calendar write path gives it: a dict of the
    event's recorded result, or None when card <number> created no event). ItemRefError otherwise (parse and read_index list the codes; past_end:
    the number is beyond the snapshot's items; created_unavailable: no `created` function was given; created_unknown: it answered None). The entry
    of an item whose id the index could not keep (null) is returned as it is: the caller refuses a write that needs the id."""
    ref = parse(value)
    if ref["kind"] == "created":
        if kinds is not None and "calendar" not in kinds:
            raise ItemRefError("wrong_kind", f"created:{ref['pending']} names an event, and this needs {' or '.join(kinds)}")
        if created is None:
            raise ItemRefError("created_unavailable", "a reference to an event you created is resolved by the calendar operations, not here")
        entry = created(ctx, ref["pending"])
        if not isinstance(entry, dict):
            raise ItemRefError("created_unknown", f"card {ref['pending']} did not create an event, or its result is not recorded")
        return {"kind": "created", "pending": ref["pending"], "type": "calendar", "entry": entry}
    snapshot = read_index(ctx, ref["source"], channel=channel, sender=sender, kinds=kinds, evidence_base=evidence_base, clock=clock)
    count = len(snapshot["entries"])
    if ref["n"] > count:
        raise ItemRefError("past_end", f"{ref['source']} has {count} item{'' if count == 1 else 's'} in its newest snapshot (read at "
                                       f"{snapshot['read_at']}), so {ref['source']}#{ref['n']} does not exist")
    shown = {key: snapshot[key] for key in ("source", "type", "implementation", "calendar", "box", "version", "read_at", "age") if key in snapshot}
    return {"kind": "item", **shown, "n": ref["n"], "count": count, "entry": snapshot["entries"][ref["n"] - 1]}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
