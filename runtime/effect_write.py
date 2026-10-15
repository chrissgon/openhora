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
is `stale`: nothing is written, the effect is answered with the reason, and the step task starts over from the step that reads, so
the person is asked again about the page as it is now. A target that cannot be read is a provider failure: nothing is written.
Between that read and the write is the platform's own gap; the write replaces the whole document and merges nothing (the
documents contract), so the gap is as wide as a call and is said here, not hidden.

Which platform. Nothing here names one: the provider is the class `integration:documents` the project's configuration chose, and
`read` and `write` are two verbs of its contract (providers/CONTRACT.md). A provider that cannot write answers exit 2 and the effect
fails with nothing written (the Google Drive provider is sources-only today).

Usage (a library): python3 runtime/effect_write.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402
import operations  # noqa: E402
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

WORD = "write"
PROVIDER_CLASS = "integration:documents"
GATE = False      # no skill's confirmation gate names this word
POLICY = False    # no standing approval covers a write-back: every one is approved by the hash of its exact content
STEP = True       # opened by a step task (runtime/steps.py, Gate) and approved through runtime/ops_step_effects.py
CONTENT_MAX = 256 * 1024     # bytes: the preview shows all of it, and a decision's body holds 1 MiB (providers/store/sqlite.py BODY_MAX)
KEYS = ("effect", "task", "provider", "target", "base", "content", "content_sha256", "bytes")
SHA256 = re.compile(r"[0-9a-f]{64}")
TARGET_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{5,127}")
PROVIDER = re.compile(r"[a-z][a-z0-9-]{0,39}")
DOC_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\.md")


def sha(data) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _usage(reason: str):
    return effects.EffectError("usage", reason)


def document(*, task_id: int, provider: str, target_id: str, path: str, content: str, base_text_sha256: str, base_version) -> dict:
    """The effect document, checked. EffectError usage when a piece is not in its form, the content is over CONTENT_MAX, empty, holds a
    NUL, or holds what looks like a credential."""
    data = content.encode("utf-8") if isinstance(content, str) else b""
    doc = {"effect": WORD, "task": task_id, "provider": provider, "target": {"id": target_id, "path": path},
           "base": {"text_sha256": base_text_sha256, "version": base_version if isinstance(base_version, str) else None},
           "content": content, "content_sha256": sha(data), "bytes": len(data)}
    check(doc)
    return doc


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the write."""
    if not isinstance(doc, dict) or set(doc) != set(KEYS) or doc["effect"] != WORD:
        raise _usage("the effect document of a write-back has exactly its keys")
    target, base, content = doc["target"], doc["base"], doc["content"]
    if not isinstance(doc["task"], int) or isinstance(doc["task"], bool) or doc["task"] < 1:
        raise _usage("task is a task id")
    if not isinstance(doc["provider"], str) or not PROVIDER.fullmatch(doc["provider"]):
        raise _usage("provider is the name of an implementation")
    if not isinstance(target, dict) or set(target) != {"id", "path"} or not isinstance(target["id"], str) \
            or not TARGET_ID.fullmatch(target["id"]) or not isinstance(target["path"], str) or not DOC_PATH.fullmatch(target["path"]) \
            or ".." in target["path"].split("/") or target["path"].endswith(".comments.md"):
        raise _usage("the target is an identifier and a project-relative path that ends in .md")
    if not isinstance(base, dict) or set(base) != {"text_sha256", "version"} or not isinstance(base["text_sha256"], str) \
            or not SHA256.fullmatch(base["text_sha256"]) or not (base["version"] is None or isinstance(base["version"], str)):
        raise _usage("base is the hash of the text the task read and the version it saw")
    if not isinstance(content, str) or not content.strip() or "\x00" in content:
        raise _usage("the content is non-empty text without a NUL character")
    data = content.encode("utf-8")
    if len(data) > CONTENT_MAX:
        raise _usage(f"the content is {len(data)} bytes, over the {CONTENT_MAX} one write-back takes: split it")
    if doc["content_sha256"] != sha(data) or doc["bytes"] != len(data):
        raise _usage("the content is not the one whose hash the document states")
    why = workcopy.scan(data)
    if why:
        raise _usage(f"the content {why}: it is not written anywhere")
    return doc


def title(doc: dict) -> str:
    """The title of the pending decision."""
    return f"Write back: {doc['target']['path']}"


def describe(doc: dict) -> str:
    """What is approved, in one line."""
    return f"write {doc['bytes']} bytes over the document {doc['target']['id']} ({doc['target']['path']})"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the content."""
    return {"target": doc["target"]["id"], "path": doc["target"]["path"], "bytes": doc["bytes"], "content_sha256": doc["content_sha256"]}


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving, the content whole: where it goes, what it replaces, the hash, the command that approves,
    and the text exactly as it will be written. (A decision's body holds 1 MiB and the content at most CONTENT_MAX.)"""
    lines = ["Code writes this text over a document of your platform after your approval, and nothing else. The document is replaced "
             "whole; nothing of it is kept or merged.", "",
             f"Target: the document {doc['target']['id']} (provider {doc['provider']}), titled by {doc['target']['path']}",
             f"Content: {doc['bytes']} bytes, sha256 {doc['content_sha256']}",
             f"The document held, when it was read, text with sha256 {doc['base']['text_sha256']}"
             + (f" (version {doc['base']['version']})" if doc["base"]["version"] else ""),
             "If its text is not that when you approve, nothing is written and you are asked again about the document as it is then.",
             "", f"Hash of this effect (it covers the target's id and the content): {digest}",
             "Approve exactly this: " + operations.command_line("approve", "<project>", pending_id="<this pending decision's id>",
                                                                sha256=digest),
             "Or answer with what to change, or reject it: nothing is written until you approve.",
             "", "----- the content, exactly as it will be written -----", doc["content"].rstrip("\n"), "----- end of the content -----"]
    return "\n".join(lines) + "\n"


def verify(doc: dict, current: dict) -> dict:
    """The target was not edited since it was read: `current` is what the provider's `read` printed just now; its Markdown must have the
    sha256 the task recorded. EffectError stale otherwise, and provider when the answer holds no text."""
    text = current.get("markdown") if isinstance(current, dict) else None
    if not isinstance(text, str):
        raise effects.EffectError("provider", "the provider's read printed no text for the target")
    if sha(text) != doc["base"]["text_sha256"]:
        raise effects.EffectError("stale", "the document was edited since it was read")
    return doc


def execute(doc: dict, approval: dict, call, key: str, work_dir=None) -> dict:
    """The write, and the only place it is made. It refuses unless `approval` is the person's approval of exactly this document: scope
    action, status pending-execution, and a payload_sha256 equal to the hash of the document's canonical text (EffectError deviation).
    Then the document is checked again, the target is read and compared with what the task read (verify), and the provider's `write`
    is called with --confirmed on a private file holding the exact content. `call(verb, args)` is the seam: the provider's one JSON
    object, or EffectError. Returns {"written": True, "id", "version", "bytes", "content_sha256", "replayed": False}."""
    if not isinstance(approval, dict) or approval.get("scope") != "action" or approval.get("status") != "pending-execution" \
            or approval.get("payload_sha256") != sha(effects._text(doc)):
        raise effects.EffectError("deviation", "there is no approval of this exact content: nothing is written")
    check(doc)
    target = doc["target"]
    verify(doc, call("read", ["--id", target["id"]]))
    folder = tempfile.mkdtemp(prefix="openhora-write-back-", dir=work_dir)
    try:
        path = os.path.join(folder, "content.md")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(doc["content"].encode("utf-8"))
        written = call("write", ["--id", target["id"], "--path", target["path"], "--markdown-file", path, "--idempotency-key", key,
                                 "--confirmed"])
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not isinstance(written, dict) or not isinstance(written.get("id"), str):
        raise effects.EffectError("provider", "the provider's write printed no document id")
    return {"written": True, "id": written["id"], "version": written.get("version") if isinstance(written.get("version"), str) else None,
            "bytes": doc["bytes"], "content_sha256": doc["content_sha256"], "replayed": False}


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
