#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of writing a file to the person's own Drive or OneDrive (package W4a): a new file in a folder the project lists, a new revision of a
file the person registered as a source, a file the person sent through a messaging app, or (slice R2-A) a file of the granted folders moved to the service's
trash, done once, after the person approved the hash of the exact document.

It is registered under the side-effect word `files` (runtime/effects.py KINDS; contracts/environment.md: a word that arrived with the runtime, not with a
skill) and is the STEP path of an effect, like the e-mail (runtime/effect_send.py): a step task of the kind `file-write` (runtime/step_files.py) writes this
module's document (runtime/files_document.py) and opens an `effect` decision whose hash is the document's; nothing in the engine or in the kind writes. The
write happens in one place, `execute`, which runtime/ops_step_effects.py calls from the operation `approve` and nowhere else (limit L55), with the approval the
person gave. This module is one of the four that may name a writer (`writer:files`: limit L58), and starts the writer of the document's own implementation,
never `auto`, only when that file declares `SERVES = "writer:files"`.

Execution (`execute`). It refuses unless `approval` is the person's approval of exactly this document (scope action, status pending-execution, payload_sha256
the hash of the document's canonical text) and `key` is the document's own. The content is the approved bytes: the text of the document; or a file of the
project read again, with no link on the way; or the held file read again from the hold. Its sha256 and size must be the ones the document states, else
`stale` and nothing is written. A copy is made in a private folder (0700; the file O_EXCL, 0600) and handed to the writer. For a replace the file is read again
with the writer's `file-meta` and compared with the base in the document (`stale` when it moved: nothing is written and the task starts over from the step that
reads); the writer reads it once more and refuses a moved base itself (its exit 1 `changed:` is `stale` too; limit L56). The writer is asked for a dry run
first, and what it prints must hash to the document's `dry_run_sha256` (a writer that would send something other than what was approved is a `deviation`); then
the verb is called with `--confirmed`. Results: `written`; `replayed` (an earlier attempt of this approval landed and its answer was lost: the writer found its
own mark and wrote nothing again); `unknown` (exit code 4, or a call that timed out: the file may or may not be there; the effect stays open and approving it
again meets the writer's ledger); or a refusal with nothing changed (the writer's exit 1 guarantees it). A replace never deletes: the earlier revision stays in
the service's history (Drive: marked keepForever before the write; OneDrive: the version history). A trash (R2-A) is the one removal, and it is a move to the service's
trash, from where the person restores the file: it carries no content, reads the file again (`file-meta`) and compares it with the base in the document (version, modified
time, type and folder on Drive; eTag, cTag, size and folder on OneDrive; `stale` when it moved), and the writer's `trash` verb reads it once more and refuses a moved base
itself. Before it, `preflight` asks the grant again: the folder the project lists under the document's name must still be the one the file was found under, and the file must
still be under it (runtime/ops_file_read.py `locate`, the walk the search makes). No verb of a writer deletes for good, and nothing here can name one (L57).

What a kind module of this path exposes, besides the names of runtime/effect_send.py:

    PROVIDER_CLASS, GATE, POLICY, STEP   writer:files; False and False (no skill's gate names `files`, and no standing approval covers it); True
    preflight(cfg, doc, root)            the account is listed in the project's `accounts`, its address is the document's, the folder is still the one the
                                         project lists under that name (limit L55), and the writer resolves and declares the class
    caller(cfg, root)                    the `call(verb, args, implementation)` that starts the writer with the one account secret and nothing else
    on_cards(doc)                        whether the whole write is on a messaging card: a text is, a save is (the card names the file, its size and its hash;
                                         the sender who sent it approves it), a file of the project that is not text is not
    held_attachment(doc)                 the number of the held file a save writes, else None (runtime/ops_grants.py asks it to bind the approval to its sender)

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
import effect_send  # noqa: E402  (read_project_file: a file of the project, no link on the way)
import effects  # noqa: E402
import files_document  # noqa: E402
import mail_address  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
from files_document import WORD, document, check, title, describe, summary, body, sha  # noqa: E402,F401  (the pure half, re-exported)

PROVIDER_CLASS = "writer:files"
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a file write: every one is approved by the hash of its exact content
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
FORGETS_KEYS = False      # the writer's ledger keeps a key for ever, so an old decision is no reason to refuse
APPROVAL_GROUP = "approve-effect-files"      # the group a project's policy grants to let a messaging app approve a file write
NOTHING_DONE = "nothing was written"      # the words ops_step_effects.py starts a refusal with
SECRETS = {"gdrive": "GOOGLE_ACCOUNT_TOKEN", "onedrive": "MICROSOFT_ACCOUNT_TOKEN"}      # the one secret the writer of each implementation reads
UNKNOWN_EXIT = 4          # the writer's exit code for "the file may or may not be there"
CALL_TIMEOUT = 300        # seconds: 25 MiB over a slow line
CHANGED = re.compile(r"\bchanged:")      # how a writer says, on its standard error, that the file moved since it was read (exit 1)
TAKEN = re.compile(r"\btaken:")        # ... and that a file of the name is in the folder now (exit 1)
UNKNOWN_NEXT = ("the outcome is unknown: look in the folder, or in the file's history. The effect stays open. Approving it again with the same hash first looks "
                "for the file this approval made (its private mark) and records it as replayed; if there is none it writes it")
STALE_NOTE = ("Nothing was written by this attempt: the file is not the one the task read (it was changed, or it is not the content the document states). The task "
              "starts over from the step that reads; start it again to be asked about the file as it is now.")


class StaleError(effects.EffectError):
    """The file or the content is not the one the task read."""

    def __init__(self, reason: str):
        super().__init__("stale", reason)
        self.answer = STALE_NOTE


class TakenError(StaleError):
    """A file of the name is in the folder now."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.answer = phrases.en("ACCT_FILE_TAKEN_ANSWER")


class UnknownError(effects.EffectError):
    """The outcome of the write is not known."""

    def __init__(self, reason: str):
        super().__init__("unknown", reason)
        self.next = UNKNOWN_NEXT


def is_long(doc) -> bool:
    """Whether the write is made without the project's write lock, under the lock of the decision: every one is (a transfer of up to 25 MiB takes seconds, and
    an answer or a cancel of the decision must wait for it)."""
    return isinstance(doc, dict)


def on_cards(doc) -> bool:
    """Whether the whole write can be on a messaging card: the text is; a save is (Q9: the card names the file, its size and its hash, the bytes are the ones the
    sender just sent, and only that sender approves it); a file of the project that is not text is not (the hash covers bytes the card does not carry)."""
    if isinstance(doc, dict) and doc.get("operation") == "trash":
        return doc.get("content") is None      # the card names the file, its folder, its account and where it goes: the whole effect is on it
    if not isinstance(doc, dict) or not isinstance(doc.get("content"), dict):
        return False
    return doc.get("operation") == "save" or doc["content"].get("kind") == "text"


def held_attachment(doc):
    """The number of the held file a save writes, or None."""
    content = doc.get("content") if isinstance(doc, dict) else None
    return content.get("attachment") if isinstance(content, dict) and content.get("kind") == "held" else None


def idempotency_key(doc: dict, default: str) -> str:
    """The document's own key (runtime/files_document.py key_of), not the pending decision's."""
    return doc["idempotency_key"]


def serves(root: str, implementation: str):
    """Whether providers/writer/<implementation>.py declares `SERVES = "writer:files"`, read as text (the file is never imported); the words of the refusal
    otherwise, or None."""
    if implementation not in SECRETS:
        return f"{implementation!r} is not a writer of files"
    path = os.path.join(root, "providers", "writer", f"{implementation}.py")
    if not os.path.isfile(path):
        return f"the writer {implementation} is not in this checkout"
    if not project_config.resolver(root).serves_class(PROVIDER_CLASS, implementation, root=root, strict=True):      # the one reader of the SERVES line (providers/resolve.py)
        return f"the writer {implementation} does not declare that it serves {PROVIDER_CLASS}"
    return None


def grant_problem(cfg: dict, doc: dict):
    """The words of why a file to trash is not provably under the folder the project grants now, or None: the walk the search makes (runtime/ops_file_read.py `locate`) from
    that folder must reach the file's id. A walk that was cut, or a folder that did not answer, proves nothing, so it is a problem too."""
    import ops_file_read  # noqa: PLC0415  (a reader of the person's own folders: loaded when a trash is approved)
    found = ops_file_read.locate(cfg, doc["account"], doc["base"]["root"], doc["target"]["id"])
    if found == "unproven":
        return "the folders could not be looked through to the end, so the file is not shown to be inside the granted folder"
    if found is None:
        return "the file is not inside the granted folder any more"
    return None


def preflight(cfg: dict, doc: dict, root: str):
    """(exit code, sentence) when the project is not configured for this write now, else None: the account is listed in `accounts`, its address is the one the
    document was prepared for, a new file's folder is still the one the project lists under that name (limit L55), and the writer resolves and serves the
    class. Nothing is written when it answers."""
    account = doc.get("account")
    entry = project_config.account_entry(cfg, account)
    if entry is None:
        return 3, phrases.en("ACCT_NOT_CONFIGURED").format(account=project_config.clean_name(account, 20)) + ": " + NOTHING_DONE
    try:
        same = mail_address.address_key(entry["address"]) == mail_address.address_key(doc.get("address") or "")
    except Exception:
        same = False
    if not same:
        return 1, "nothing was written: the account's address in the project's configuration is not the one the file was prepared for"
    target = doc.get("target") or {}
    if doc.get("operation") == "trash":      # the granted folder is the document's `root`: it must still be listed under its name, and the file must still be under it
        ident, why = project_config.account_target(cfg, account, "folders", target.get("label"))
        if why:
            return 1, f"nothing was changed: {why}"
        if ident != (doc.get("base") or {}).get("root"):
            return 1, "nothing was changed: the folder the project lists under that name is not the one the file was found under"
        problem = grant_problem(cfg, doc)
        if problem:
            return 1, f"nothing was changed: {problem}"
    elif doc.get("operation") != "replace":
        ident, why = project_config.account_target(cfg, account, "folders", target.get("label"))
        if why:
            return 1, f"nothing was written: {why}"
        if ident != target.get("id"):
            return 1, "nothing was written: the folder the project lists under that name is not the one the file was prepared for"
    problem = serves(root, doc.get("implementation") or "")
    if problem:
        return 3, f"nothing was written: {problem}"
    resolve = project_config.resolver(root)
    try:
        resolve.resolve(PROVIDER_CLASS, root=root, implementation=doc["implementation"])
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        return 3, f"nothing was written: the writer does not resolve: {e}"
    return None


def caller(cfg: dict, root: str):
    """The `call(verb, args, implementation)` that starts the writer of an implementation (always named, never `auto`) with the minimum environment and the one
    account secret of that implementation if it is in the environment: no other secret of this process reaches it. A call that timed out, or whose writer exited
    with UNKNOWN_EXIT, is `unknown`; the writer's `changed:` is `stale`; any other refusal is a failure with nothing written."""
    resolve = project_config.resolver(root)

    def call(verb, args, implementation):
        if implementation not in SECRETS:
            raise effects.EffectError("usage", f"{implementation!r} is not a writer of files")
        try:
            return resolve.call(PROVIDER_CLASS, verb, args, root=root, implementation=implementation, timeout=CALL_TIMEOUT,
                                env=resolve.provider_environment(PROVIDER_CLASS, None, (SECRETS[implementation],)))
        except resolve.ProviderCallError as e:
            if e.kind == "timeout" or e.exit_code == UNKNOWN_EXIT:
                raise UnknownError(f"{verb}: {e.reason}") from None
            if e.kind == "failed" and e.exit_code == 1 and TAKEN.search(e.reason or ""):
                raise TakenError(f"{verb}: {e.reason}") from None
            if e.kind == "failed" and e.exit_code == 1 and CHANGED.search(e.reason or ""):
                raise StaleError(f"{verb}: {e.reason}") from None
            raise effects.EffectError({"usage": "usage", "not-configured": "not-configured"}.get(e.kind, "provider"), f"{verb}: {e.reason}") from None
    return call


def _private_file(folder: str, name: str, data: bytes) -> str:
    path = os.path.join(folder, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def content_bytes(doc: dict, work_dir, project) -> bytes:
    """The approved bytes, read again from where they live: the text of the document; a file of the project (no link on the way); the held file. StaleError
    when they are not the ones the document states (the file was edited or is gone, the held file expired or was discarded)."""
    content = doc["content"]
    if content["kind"] == "text":
        data = content["text"].encode("utf-8")
    elif content["kind"] == "file":
        try:
            data = effect_send.read_project_file(project, content["path"], files_document.FILE_MAX) if project else None
        except (OSError, ValueError):
            data = None
    else:
        import attachments  # noqa: PLC0415  (the hold: loaded when a held file is written)
        data = attachments.read_held(work_dir, content["attachment"]) if work_dir else None
    if data is None or len(data) != content["bytes"] or sha(data) != content["sha256"]:
        raise StaleError("the content is not the file the task read (it changed, or it is gone)")
    return data


def _trash(doc: dict, call, implementation: str) -> dict:
    """The move of a file to the service's trash: the file is read again and compared with the base (StaleError when it moved; a read that cannot be made, or a file already in
    the trash, is left to the writer, which compares the base itself and knows by its ledger whether an earlier attempt of this approval made the move), the writer is asked for a
    dry run that must hash to the document's, and the verb is called with --confirmed."""
    try:
        meta = call("file-meta", files_document.meta_args(doc), implementation)
    except StaleError:
        raise
    except effects.EffectError:
        meta = None
    if isinstance(meta, dict):
        moved = files_document.unchanged(doc, meta)
        if moved and meta.get("in_trash") is not True:
            raise StaleError(f"the file is not the one the task read ({moved})")
    verb, args = files_document.provider_args(doc)
    shown = call(verb, args + ["--dry-run"], implementation)
    if not isinstance(shown, dict) or shown.get("would_sha256") != doc["dry_run_sha256"]:
        raise effects.EffectError("deviation", "the writer would send something other than what was approved: nothing was changed")
    done = call(verb, args + ["--confirmed"], implementation)
    if not isinstance(done, dict) or done.get("written") is not True or done.get("moved_to_trash") is not True:
        raise UnknownError("the writer's answer is not a file in the trash: the file may or may not be there")
    return files_document.facts(doc, done)


def execute(doc: dict, approval: dict, call, key: str, work_dir=None, project=None) -> dict:
    """The write, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope action, status
    pending-execution, and a payload_sha256 equal to the hash of the document's canonical text (EffectError deviation), and unless `key` is the document's own.
    Then the document is checked again, the content is read again and compared with its hash (StaleError), a replace re-reads the file and compares it with the
    base (StaleError), the writer's dry run must hash to the document's dry_run_sha256 (EffectError deviation), and the verb is called with --confirmed.
    `call(verb, args, implementation)` is the seam: the writer's one JSON object, or EffectError (UnknownError when the outcome is not known, StaleError when the
    file moved). `work_dir` is the project's data folder and `project` the project's folder. Returns files_document.facts."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is written")
    check(doc)
    if key != doc["idempotency_key"]:
        raise effects.EffectError("deviation", "the key is not the one this write derives: nothing is written")
    implementation = doc["implementation"]
    if doc["operation"] == "trash":
        return _trash(doc, call, implementation)
    data = content_bytes(doc, work_dir, project)
    if doc["operation"] == "replace":
        meta = call("file-meta", files_document.meta_args(doc), implementation)
        meta = meta if isinstance(meta, dict) else {}
        moved = files_document.unchanged(doc, meta)
        if moved and not files_document.landed(doc, meta, data):      # an earlier attempt of this very approval may have landed with its answer lost: the writer then answers `replayed`
            raise StaleError(f"the file is not the one the task read ({moved})")
    folder = tempfile.mkdtemp(prefix="openhora-files-", dir=work_dir)
    try:
        path = _private_file(folder, "content", data)
        verb, args = files_document.provider_args(doc, path)
        shown = call(verb, args + ["--dry-run"], implementation)
        if not isinstance(shown, dict) or shown.get("would_sha256") != doc["dry_run_sha256"]:
            raise effects.EffectError("deviation", "the writer would send something other than what was approved: nothing is written")
        done = call(verb, args + ["--confirmed"], implementation)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not isinstance(done, dict) or done.get("written") is not True:
        raise UnknownError("the writer's answer is not a written file: the file may or may not be there")
    return files_document.facts(doc, done)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
