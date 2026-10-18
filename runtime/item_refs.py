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

External content is data: the index is read back with every value checked again against the closed shapes (ids and keys by full match, an
address, a subject cut at 120 characters), so a manifest edited outside the runtime cannot put anything else in front of a write. This module
calls no provider and writes nothing; it reads the sources folder through sources.Folder (limits L21 to L25: no link followed, the version's
files hashed against the record first).

Every refusal is an ItemRefError with a stable `code` and a plain English sentence; the operation that asked turns it into its reply.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sources  # noqa: E402

REF_MAX_AGE = sources.SNAPSHOT_MAX_AGE            # seconds: 26 hours, the number of limit L53
MANIFEST_CAP = 4 * 1024 * 1024                    # the most a manifest file may hold (a hundred messages are a few hundred KiB)
NUMBER_MAX = 9999
INDEX_KEYS = {"mail": ("n", "id", "thread_id", "message_id", "from_address", "reply_to_address", "subject", "change_key"),
              "calendar": ("n", "id", "etag", "calendar", "organizer_self", "attendees_other", "recurring")}
COUNT_KEY = {"mail": "messages", "calendar": "events"}
SUBJECT_MAX = 120

ITEM_REF = re.compile(r"([a-z0-9][a-z0-9-]{0,39})#([0-9]{1,4})")
CREATED_REF = re.compile(r"created:([1-9][0-9]{0,8})")

# The closed shapes of an entry's values, the same as runtime/sources_mail.py writes (checked again on the way out).
ID = re.compile(r"[A-Za-z0-9_=+.-]{1,700}")
KEY = re.compile(r"[\x21-\x7e]{1,200}")
MESSAGE_ID = re.compile(r"[\x21-\x7e]{1,998}")
ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9][A-Za-z0-9.-]{0,251}")
CALENDAR = re.compile(r"[A-Za-z0-9._%+#@=-]{1,256}")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]")


class ItemRefError(Exception):
    """A reference that cannot be resolved. `code`: malformed, zero, past_end, no_source, not_snapshot, wrong_kind, no_version, stale, no_index,
    integrity, created_unavailable, created_unknown."""

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
    one = " ".join(CONTROL.sub(" ", raw).split())
    return '"' + (one if len(one) <= 60 else one[:59] + "…") + '"'


# --- reading the index ------------------------------------------------------------------------------------------------------------


def _text(value, limit: int):
    if not isinstance(value, str) or CONTROL.search(value):
        return None
    one = " ".join(value.split())
    return one[:limit]


def _shaped(pattern, value):
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _entry(kind: str, n: int, raw) -> dict:
    """A clean copy of one stored entry: only the keys of its kind, each value checked against its closed shape or null. The number must be the
    entry's place in the list."""
    if not isinstance(raw, dict) or raw.get("n") != n or type(raw.get("n")) is not int:
        raise ItemRefError("integrity", "the index of this snapshot does not match its numbering: refresh it, then ask again")
    if kind == "mail":
        return {"n": n, "id": _shaped(ID, raw.get("id")), "thread_id": _shaped(ID, raw.get("thread_id")),
                "message_id": _shaped(MESSAGE_ID, raw.get("message_id")), "from_address": _shaped(ADDRESS, raw.get("from_address")),
                "reply_to_address": _shaped(ADDRESS, raw.get("reply_to_address")), "subject": _text(raw.get("subject"), SUBJECT_MAX) or "",
                "change_key": _shaped(KEY, raw.get("change_key"))}
    others = raw.get("attendees_other")
    return {"n": n, "id": _shaped(ID, raw.get("id")), "etag": _shaped(KEY, raw.get("etag")), "calendar": _shaped(CALENDAR, raw.get("calendar")),
            "organizer_self": raw.get("organizer_self") is True, "attendees_other": others if type(others) is int and others >= 0 else None,
            "recurring": raw.get("recurring") is True}


def read_index(ctx: dict, source_id: str, *, kinds=None, evidence_base=None, clock=None) -> dict:
    """The index of the newest version of a registered mail or calendar source, after the checks a reference needs. Returns {"source", "type",
    "version", "read_at" (the version's reading time), "age" (seconds), "entries": [clean entries, numbered from 1]}. `kinds` limits the types
    the caller accepts (("mail",) for an operation on messages). ItemRefError: no_source, not_snapshot, wrong_kind, no_version, stale (older than
    REF_MAX_AGE, or a reading time that cannot be trusted), no_index (a version made before the index existed), integrity (the version's files do
    not hash to the record, or the manifest does not belong to it). `clock` is the seam of sources.snapshot_age."""
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
    latest = sources._stored(ctx, "source_latest", source_id)
    if latest is None:
        raise ItemRefError("no_version", f"{source_id} has no snapshot yet: refresh {source_id} first")
    age = sources.snapshot_age(latest["imported_at"], clock)
    if age is None or age > REF_MAX_AGE:
        raise ItemRefError("stale", f"the newest snapshot of {source_id} was read at {latest['imported_at']}, more than {REF_MAX_AGE // 3600} hours ago "
                                    f"or at a time that cannot be trusted: refresh {source_id} first")
    with sources.Folder(ctx["cfg"], evidence_base) as folder:
        if not sources.verify_version(folder, latest)["ok"]:
            raise ItemRefError("integrity", f"the files of {source_id} (version {latest['version']}) were changed outside the runtime: refresh {source_id} first")
        try:
            manifest = json.loads(folder.read([source_id, str(latest["version"]), "manifest.json"], MANIFEST_CAP).decode("utf-8"))
        except (sources.SourcesError, ValueError):
            raise ItemRefError("integrity", f"the manifest of {source_id} (version {latest['version']}) cannot be read: refresh {source_id} first") from None
    if not isinstance(manifest, dict) or manifest.get("source") != source_id or manifest.get("version") != latest["version"] \
            or (manifest.get("converted") or {}).get("sha256") != latest["converted_sha256"]:
        raise ItemRefError("integrity", f"the manifest of {source_id} does not belong to its newest version: refresh {source_id} first")
    stored = manifest.get("index")
    if not isinstance(stored, list):
        raise ItemRefError("no_index", f"the newest snapshot of {source_id} was made before items could be referred to: refresh {source_id} first")
    if len(stored) != manifest.get(COUNT_KEY[kind]):
        raise ItemRefError("integrity", f"the index of {source_id} does not count the items its text lists: refresh {source_id} first")
    entries = [_entry(kind, number, raw) for number, raw in enumerate(stored, 1)]
    return {"source": source_id, "type": kind, "version": latest["version"], "read_at": latest["imported_at"], "age": age, "entries": entries}


# --- resolving --------------------------------------------------------------------------------------------------------------------


def resolve(ctx: dict, value, *, kinds=None, evidence_base=None, clock=None, created=None) -> dict:
    """The item a reference names. Returns {"kind": "item", "source", "type", "version", "read_at", "age", "n", "count", "entry"} for
    `<source id>#<n>`, where `entry` is the clean index entry and `count` the number of items of the snapshot; or {"kind": "created", "pending",
    "type": "calendar", "entry": ...} for `created:<number>`, which `created(ctx, pending)` answers (the calendar write path gives it: a dict
    of the event's recorded result, or None when card <number> created no event). ItemRefError otherwise (parse and read_index list the codes;
    past_end: the number is beyond the snapshot's items; created_unavailable: no `created` function was given; created_unknown: it answered
    None). The entry of an item whose id the index could not keep (null) is returned as it is: the caller refuses a write that needs the id."""
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
    snapshot = read_index(ctx, ref["source"], kinds=kinds, evidence_base=evidence_base, clock=clock)
    count = len(snapshot["entries"])
    if ref["n"] > count:
        raise ItemRefError("past_end", f"{ref['source']} has {count} item{'' if count == 1 else 's'} in its newest snapshot (read at "
                                       f"{snapshot['read_at']}), so {ref['source']}#{ref['n']} does not exist")
    return {"kind": "item", "source": ref["source"], "type": snapshot["type"], "version": snapshot["version"], "read_at": snapshot["read_at"],
            "age": snapshot["age"], "n": ref["n"], "count": count, "entry": snapshot["entries"][ref["n"] - 1]}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
