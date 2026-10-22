#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The numbered items of the mail and calendar snapshots (package NR-5a): the read that gives "o e-mail 3" and "o evento 2" something to point to on a phone.

  items(project[, kind, source])   for each registered mail (or calendar) source, the items of its newest snapshot, numbered as the references `<source>#<n>` number them
                                   (runtime/item_refs.py): a message by its sender and subject, an event by its line as the snapshot prints it

It reads only what a reference reads, with the same rights: the terminal, the conversation and the page, and a messaging sender whose profile lists the group `ask-mail`
(item_refs.may_read); the MCP mode has no row. The lines are another person's words, so the reply is private: it goes to the chat that asked, and the conversation stores a neutral
word for it (runtime/ops_natural.py). Every value is read back through the closed shapes of runtime/item_refs.py; the text of an event is read only after the index and the
text were checked against the store's record, and only its numbered lines are taken. Nothing is written anywhere, no provider is called and no model is.

Sibling of runtime/ops.py, which exposes it under its name. Standard library only. Runs on Python 3.9: python3 runtime/ops_items.py --help
"""
from __future__ import annotations

import hashlib
import re
import sys

import item_refs
import ops_actor
import ops_core as core
import phrases
import snapshot_text
import sources

LINE_MAX = 120          # characters of one line
ITEMS_MAX = 100         # items of one snapshot (the sources keep at most this many)
SHOWN_MAX = 20          # items of one source the reply prints (`render`); runtime/event_lookup.py ITEMS_SHOWN is the same number
EVENT_LINE = re.compile(r"([0-9]{1,4})\. (.+)")
KINDS = ("mail", "calendar")
SNAPSHOT_CLOCK = None          # the clock the age of a snapshot is read against (None: the real one); a test replaces it


def _event_lines(ctx: dict, source_id: str, version) -> dict:
    """{n: the line of the event as the snapshot prints it} of the version `read_index` read the index of: the text is read only when the newest version is still that one
    and its hash is the one the store records, so that the number and the line always come from the same snapshot (else nothing: the lines are blank)."""
    latest = sources._stored(ctx, "source_latest", source_id)
    if latest is None or latest["version"] != version:
        return {}
    with sources.Folder(ctx["cfg"], None) as folder:
        raw = folder.read([source_id, str(version), latest["converted_name"]], sources.CONVERTED_CAP)
    if hashlib.sha256(raw).hexdigest() != latest["converted_sha256"]:
        return {}
    text = raw.decode("utf-8", errors="replace")
    out = {}
    for line in text.splitlines():
        found = EVENT_LINE.fullmatch(line.strip())
        if found:
            out[int(found.group(1))] = snapshot_text.one_line(snapshot_text.clean_text(found.group(2)), LINE_MAX)
    return out


def items(project: str, kind: str | None = None, source: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """The numbered items of the newest snapshots. Returns {"sources": [{"source", "type", "read_at", "items": [{"n", "line"}]}], "refused": [{"source", "why"}]}: a source
    whose snapshot cannot be read (older than 26 hours, no index) is in `refused` with the reference sentence. OpsError when the caller may not read a snapshot (1) or `kind`
    is not mail or calendar (2)."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "items", channel, sender)
    if kind is not None and kind not in KINDS:
        raise core.OpsError("the kind of item is mail or calendar", 2)
    if not item_refs.may_read(ctx, channel, sender):
        raise core.OpsError(phrases.en("NW_REF_NOT_READABLE"), 1)
    found, refused = [], []
    for row in sources.list_catalog(ctx, hashes=False):
        if row["type"] not in KINDS or (kind and row["type"] != kind) or (source and row["id"] != source):
            continue
        try:
            snapshot = item_refs.read_index(ctx, row["id"], channel=channel, sender=sender, kinds=(row["type"],), clock=SNAPSHOT_CLOCK)
        except item_refs.ItemRefError as e:
            refused.append({"source": row["id"], "why": str(e)})
            continue
        if row["type"] == "mail":
            rows = [{"n": e["n"], "line": snapshot_text.one_line(f"{e.get('from_address') or '?'} · {e.get('subject') or ''}", LINE_MAX)} for e in snapshot["entries"][:ITEMS_MAX]]
        else:
            lines = _event_lines(ctx, row["id"], snapshot["version"])
            rows = [{"n": e["n"], "line": lines.get(e["n"], "")} for e in snapshot["entries"][:ITEMS_MAX]]
        found.append({"source": row["id"], "type": row["type"], "read_at": snapshot["read_at"], "items": rows})
    return {"sources": found, "refused": refused}


def render(out: dict, cfg: dict, limit: int = SHOWN_MAX) -> str:
    """The reply for a phone or a terminal: one heading for each source, then `n. line` for the first items."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    lines = []
    for entry in out["sources"]:
        lines.append(t("NW_ITEMS_HEAD", source=entry["source"], read_at=entry["read_at"][:16].replace("T", " ")))
        lines += [f"{i['n']}. {i['line']}" for i in entry["items"][:limit]]
        if len(entry["items"]) > limit:
            lines.append(t("NW_ITEMS_MORE", n=len(entry["items"]) - limit))
    for entry in out["refused"]:
        lines.append(f"{entry['source']}: {entry['why']}")
    return "\n".join(lines) or t("NW_ITEMS_NONE")


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
