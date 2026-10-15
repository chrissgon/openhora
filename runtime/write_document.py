#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of a write-back, and nothing that writes (package P8): what the step kind `write-back` builds and the effect kind `write`
approves. The effect document (its keys, its checks, the credential scan of its content), the title and the preview the person reads, the
one line that says what is approved, and the closed facts a decision's payload records. It holds no function that calls a provider or
executes an effect: that is runtime/effect_write.py, reached from the operation `approve` only. The step kind imports this module and
not that one, so a step kind has no function in reach that could write (limit L30; docs/architecture/platform/outputs.md).

Standard library only, plus the credential scan of runtime/workcopy.py and the error class of runtime/effects.py. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import operations  # noqa: E402  (the command line the preview shows)
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

WORD = "write"
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
