#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of writing a document back to the platform that holds the project's documents (package P8, decision D17,
direction 2): the text a step task prepared replaces, whole, a document that lives on the platform (a Notion page today), after the
person approved the exact content.

It is registered under the side-effect word `write` (runtime/effects.py KINDS; contracts/environment.md) and is the third path an
effect takes, after the gate path (a skill's confirmation gate, a change set committed) and the policy path (a standing approval):
the STEP path. A step task of the kind `write-back` (runtime/step_write_back.py) reads the target, writes this module's document
and opens an `effect` decision whose hash is the document's; nothing in the engine or in the kind writes to the platform. The
write happens in one place, `execute`, which runtime/ops_step_effects.py calls from the operation `approve` and nowhere else, with
the approval the person gave. What a kind module of this path exposes:

    PROVIDER_CLASS, GATE, POLICY, STEP   the class of provider; False and False (no skill's gate names `write`, and no standing
                                         approval covers it); True
    document(...)                        the effect document: what is approved, whole, and the hash of its canonical text
    check(doc)                           the document is in its form (EffectError usage)
    title(doc), body(doc, digest), describe(doc)   what the person reads and the state file's row
    verify(doc, current)                 the target was not edited since it was read (EffectError stale)
    execute(doc, approval, call, key, work_dir)    the write: refuses unless the approval is of this document's hash

The document. `effect` ("write"), `task` (the step task that prepared it), `provider` (the name the project's documents object
carries: the write is refused if the configuration names another now), `target` ({"id": the document's identifier on the platform,
"path": the project-relative Markdown path the provider titles it by}), `base` ({"text_sha256": the sha256 of the text the target
held when the task read it, "version": the platform's opaque version then}), `content` (the Markdown to write, the exact text),
`content_sha256` and `bytes`. The target's id is inside the document and so inside the hash the person approves (finding S9): a
document aimed at another target has another hash, and the approval of the first covers nothing of the second.

Not edited since it was read. The platform's version is rounded and may not move for a small edit (documents.py N1), so the guard is
the text: just before the write the target is read again, and its text must have the sha256 the task recorded. A text that differs
is `stale` and nothing is written, with two exceptions the same read tells apart. If the text is exactly what this write would leave
(the provider's dry run prints the sha256 of its own round trip of the content, `expected_sha256`), an earlier attempt of this
approval landed and its answer was lost: nothing is written again and the write is recorded as replayed. And if the write call itself
fails, nobody knows whether the page was replaced (a lost answer; a replace that appended the new blocks and failed before deleting the
old): the effect says `unknown`, stays open, and approving again reads the page first. A `stale` effect is answered with the reason
and the step task starts over from the step that reads, so the person is asked again about the page as it is now; a page left half
written by a failed replace matches neither text and comes back this way, with the message saying that it may be an earlier attempt.
A target that cannot be read is a provider failure: nothing is written. Between the read and the write is the platform's own gap; the
write replaces the whole document and merges nothing (the documents contract), so the gap is as wide as a call and is said here.

Which platform. Nothing here names one: the provider is the class `integration:documents` the project's configuration chose, and
`read` and `write` are two verbs of its contract (providers/CONTRACT.md). A provider that cannot write answers exit 2 and the effect
fails with nothing written (the Google Drive provider is sources-only today).

Four operations, one word (package NOTION-OUT). The document says which: `operation`. `update_page` is the write-back above (runtime/
write_document.py). `create_page`, `create_table` and `append_rows` make something new (runtime/output_document.py holds their document, the
hash fields and the preview); `execute` dispatches on the operation and the approval it demands is the same: the hash of the exact document.
They differ in what is read again just before the write and in what a second approval of the same hash does:

  create_page    the parent page is read (`stat`: it exists and is not in the trash). The provider's `page-create` records the document's own
                 idempotency key before the creation, so an approval that runs again finds the page the first one made (or, if its answer was
                 lost, looks for it among the parent's children) and finishes its body; it never makes a second page. A failed call is
                 `unknown`: the page may or may not exist now.
  create_table   the same for the parent; `table-create` makes the database once for the key and fills its rows once each (a ledger row key
                 under the data source: a row done is skipped, a row of unknown outcome is looked for in the table before it is written).
  append_rows    the table is read again (`table-read`): its columns hashed, its row count and the time of its newest edit must be what the
                 task read, else `stale` and nothing is written (the task starts over from the step that reads). The exception is a
                 re-approval of rows already begun (the provider's dry run says some rows of this key are done or of unknown outcome): then
                 the columns must be unchanged and the row count must be the base's plus the rows done, and up to as many more as rows of
                 unknown outcome (the time of the newest edit is not compared: this document's own rows move it), and the rows missing are
                 written. A person's row added in that window is told from this document's only when no row is of unknown outcome. When
                 every row is already there nothing is called and the result says `replayed`.

The idempotency key of these three is the document's own (derived from the task, the operation, the target, the title, the content and the
base), not the pending decision's: the same document is written once, however many decisions reach it. A call that fails after the first
write call is `unknown` for all three, and approving again checks what is there and writes only what is missing.

Usage (a library): python3 runtime/effect_write.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402

PROVIDER_CLASS = "integration:documents"
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a write-back: every one is approved by the hash of its exact content
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
import output_document  # noqa: E402  (the pure half of the operations that make something new)
import write_document  # noqa: E402  (the pure half of update_page)
from write_document import (CONTENT_MAX, DOC_PATH, KEYS, PROVIDER, SHA256, TARGET_ID, WORD, document,  # noqa: E402,F401
                            sha)  # the pure half, re-exported: the names of an effect kind of the step path


class StaleError(effects.EffectError):
    """The target is not the one the task read. rows_written: how many rows of this task the table already holds from earlier attempts
    (the answer to the decision must not say that nothing was written when some were)."""

    def __init__(self, reason: str, rows_written: int = 0):
        super().__init__("stale", reason)
        self.rows_written = rows_written


def is_long(doc) -> bool:
    """Whether the write of this document takes long (an output: a page body, a table of up to 500 rows one call a row), so that
    runtime/ops_step_effects.py makes it without the project's write lock."""
    return _output(doc)


def _output(doc) -> bool:
    """Whether the document is of one of the operations that make something new (else it is, or fails as, an update_page)."""
    return isinstance(doc, dict) and doc.get("operation") in output_document.OPERATIONS


def check(doc: dict) -> dict:
    return output_document.check(doc) if _output(doc) else write_document.check(doc)


def title(doc: dict) -> str:
    return output_document.title_of(doc) if _output(doc) else write_document.title(doc)


def describe(doc: dict) -> str:
    return output_document.describe(doc) if _output(doc) else write_document.describe(doc)


def summary(doc: dict) -> dict:
    return output_document.summary(doc) if _output(doc) else write_document.summary(doc)


def body(doc: dict, digest: str) -> str:
    return output_document.body(doc, digest) if _output(doc) else write_document.body(doc, digest)


def verify(doc: dict, current: dict, expected=None) -> str:
    """Where the target stands against the document, from what the provider's `read` printed just now (`current`): "unchanged" when
    its Markdown has the sha256 the task recorded (go on and write), "written" when it is exactly what this write leaves (the sha256
    of the provider's own round trip of this content, `expected()`: an earlier attempt of this approval landed and its answer was lost,
    so there is nothing to write), else EffectError stale (an edit, or an earlier attempt that did not finish; the message says both).
    EffectError provider when the answer holds no text."""
    text = current.get("markdown") if isinstance(current, dict) else None
    if not isinstance(text, str):
        raise effects.EffectError("provider", "the provider's read printed no text for the target")
    now = sha(text)
    if now == doc["base"]["text_sha256"]:
        return "unchanged"
    if expected is not None and now == expected():
        return "written"
    raise effects.EffectError("stale", "the document is not the one the task read, and not the one this write would leave: it was edited, "
                                       "or an earlier attempt of this write did not finish")


def execute(doc: dict, approval: dict, call, key: str, work_dir=None) -> dict:
    """The write, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope
    action, status pending-execution, and a payload_sha256 equal to the hash of the document's canonical text (EffectError deviation).
    Then the document is checked again and the target is read and compared (verify): its text as the task read it, the write is made;
    its text as this write would leave it (a replay: the answer of an earlier attempt was lost, or the provider replaced the page and
    then failed to say so), nothing is written and the write is recorded as replayed; anything else is stale and nothing is written.
    The provider's `write` is called with --confirmed on a private file holding the exact content; if that call fails the outcome is
    unknown (EffectError unknown): the page may or may not hold the content, and approving again reads it first. `call(verb, args)` is
    the seam: the provider's one JSON object, or EffectError. Returns {"written": True, "id", "version", "bytes", "content_sha256",
    "replayed"}."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is written")
    check(doc)
    if _output(doc):
        return _execute_output(doc, call, work_dir)
    target = doc["target"]
    folder = tempfile.mkdtemp(prefix="openhora-write-back-", dir=work_dir)
    try:
        path = os.path.join(folder, "content.md")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(doc["content"].encode("utf-8"))
        args = ["--id", target["id"], "--path", target["path"], "--markdown-file", path, "--idempotency-key", key]

        def expected():
            would = call("write", args + ["--dry-run"])
            sha_found = (would.get("would") or {}).get("expected_sha256") if isinstance(would, dict) else None
            if not isinstance(sha_found, str) or not SHA256.fullmatch(sha_found):
                raise effects.EffectError("provider", "the provider's dry run printed no expected hash for this content")
            return sha_found

        current = call("read", ["--id", target["id"]])
        if verify(doc, current, expected) == "written":
            return {"written": True, "id": target["id"], "version": current.get("version") if isinstance(current.get("version"), str) else None,
                    "bytes": doc["bytes"], "content_sha256": doc["content_sha256"], "replayed": True}
        try:
            written = call("write", args + ["--confirmed"])
        except effects.EffectError as e:
            raise effects.EffectError("unknown", f"the write call failed ({e.reason}): the document may or may not hold the content now") from None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not isinstance(written, dict) or not isinstance(written.get("id"), str):
        raise effects.EffectError("unknown", "the provider's write printed no document id: the document may or may not hold the content now")
    return {"written": True, "id": written["id"], "version": written.get("version") if isinstance(written.get("version"), str) else None,
            "bytes": doc["bytes"], "content_sha256": doc["content_sha256"], "replayed": False}


def _private_file(folder: str, name: str, data: bytes) -> str:
    path = os.path.join(folder, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def _confirmed(call, verb: str, args: list, what: str) -> dict:
    """The write call of an output. A failure after it began is `unknown` (what it makes may exist now); one the provider raised before
    it began to write (it is not configured for this, or the call is not in its form) is passed on as it is, nothing written."""
    try:
        done = call(verb, args + ["--confirmed"])
    except effects.EffectError as e:
        if e.kind in ("not-configured", "usage"):
            raise
        raise effects.EffectError("unknown", f"the {verb} call failed ({e.reason}): {what} may or may not hold some or all of the "
                                             "content now") from None
    if not isinstance(done, dict) or not isinstance(done.get("id"), str):
        raise effects.EffectError("unknown", f"the provider's {verb} printed no id: {what} may or may not hold the content now")
    return done


def _parent_reachable(call, parent: str) -> None:
    """The parent page exists, the integration reaches it and it is not in the trash (the provider's `stat`); else EffectError."""
    seen = call("stat", ["--id", parent])
    if not isinstance(seen, dict) or seen.get("archived") is not False:
        raise effects.EffectError("provider", "the parent page is in the trash or cannot be read: nothing is written")


def _number(value, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise effects.EffectError("provider", f"the provider's answer has no {name}")
    return value


def _url(done: dict):
    return done.get("url") if isinstance(done.get("url"), str) else None


def _execute_output(doc: dict, call, work_dir) -> dict:
    """create_page, create_table and append_rows (the approval and the document were checked by `execute`)."""
    operation, target, key = doc["operation"], doc["target"], doc["idempotency_key"]
    folder = tempfile.mkdtemp(prefix="openhora-output-", dir=work_dir)
    facts = {"written": True, "operation": operation, "bytes": doc["bytes"], "content_sha256": doc["content_sha256"]}
    try:
        if operation == "create_page":
            _parent_reachable(call, target["id"])
            path = _private_file(folder, "content.md", doc["content"].encode("utf-8"))
            args = ["--parent", target["id"], "--title", doc["title"], "--markdown-file", path, "--idempotency-key", key]
            done = _confirmed(call, "page-create", args, "the page")
            return {**facts, "id": done["id"], "url": _url(done), "version": done.get("version") if isinstance(done.get("version"), str) else None,
                    "replayed": bool(done.get("replayed"))}
        path = _private_file(folder, "table.json", output_document.content_bytes(operation, doc["content"]))
        total = len(doc["content"]["rows"])
        if operation == "create_table":
            _parent_reachable(call, target["id"])
            args = ["--parent", target["id"], "--title", doc["title"], "--table-file", path, "--idempotency-key", key,
                    "--scope", output_document.scope_of(doc["store"], doc["task"])]
            done = _confirmed(call, "table-create", args, "the table")
            made, again = _number(done.get("rows_created"), "rows_created"), _number(done.get("rows_replayed"), "rows_replayed")
            return {**facts, "id": done["id"], "data_source_id": done.get("data_source_id"), "url": _url(done), "version": None,
                    "rows": total, "rows_created": made, "rows_replayed": again, "replayed": made == 0}
        args = ["--id", target["id"], "--table-file", path, "--idempotency-key", key,
                "--scope", output_document.scope_of(doc["store"], doc["task"])]
        current = call("table-read", ["--id", target["id"]])
        # The rows the ledger holds as written count only if the table lists them now (a row a person trashed is a row to write): that is
        # `rows-state`, which reads the table, and not the dry run of rows-append, which reads the ledger alone.
        state = call("rows-state", args)
        if not isinstance(current, dict) or not isinstance(state, dict) or state.get("verified") is not True:
            raise effects.EffectError("provider", "the provider's table-read or rows-state printed no facts about the table")
        done_before, pending = _number(state.get("rows_done"), "rows_done"), _number(state.get("rows_pending"), "rows_pending")
        if done_before == total:      # every row is already there: there is nothing to compare and nothing to write
            return {**facts, "id": target["id"], "url": None, "version": None, "rows": total, "rows_created": 0, "rows_replayed": total,
                    "replayed": True}
        base = doc["base"]
        if current.get("schema_sha256") != base["schema_sha256"]:
            raise StaleError("the table is not the one the task read: its columns changed", done_before)
        # The rows this document's own attempts wrote are the rows the ledger holds now beyond the ones the task counted when it read
        # the table (base.rows_done: written by an EARLIER approval of the same task). With none of them and none of unknown outcome the
        # table must be exactly as it was read; otherwise its row count must be the base's plus those, and up to as many more as rows
        # of unknown outcome (a row of unknown outcome may or may not have landed). The time of the newest edit is not compared then:
        # this document's own rows move it. The gap, stated: with a row of unknown outcome pending, one row added by a person in the
        # same window is not told from it.
        if done_before < base["rows_done"]:      # the task counted rows that are no longer there (trashed) or no longer in the ledger
            raise StaleError("the table is not the one the task read: fewer of this task's rows are in it than when the task counted them "
                             "(a person removed some, or the provider's ledger lost them)", done_before)
        count, written = current.get("row_count"), done_before - base["rows_done"]
        if written + pending == 0:
            moved = count != base["row_count"] or current.get("last_edited") != base["version"]
        else:
            low = base["row_count"] + written
            moved = not isinstance(count, int) or isinstance(count, bool) or not low <= count <= low + pending
        if moved:
            raise StaleError("the table is not the one the task read: its rows changed (a row was added, removed or edited), or an "
                             "earlier attempt of this write did not finish", done_before)
        done = _confirmed(call, "rows-append", args + ["--schema-sha256", base["schema_sha256"]], "the table")
        made, again = _number(done.get("rows_created"), "rows_created"), _number(done.get("rows_replayed"), "rows_replayed")
        return {**facts, "id": done["id"], "url": None, "version": None, "rows": total, "rows_created": made, "rows_replayed": again,
                "replayed": made == 0}
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
