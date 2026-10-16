#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The document of a post to publish, and nothing that publishes (package PUBLISH-EFFECT): what the step kind `publish-post` builds and the effect
kind `publish` approves on the step path. The effect document (its keys, its checks, the credential scan of the text), the title and the preview
the person reads, the one line that says what is approved, the closed facts a decision's payload records, and the arguments of the publisher's
`publish` verb. It holds no function that calls a provider, runs the publishing skill's script or executes an effect: that is
runtime/publish_payload.py (the script) and runtime/effect_publish.py (the execution, reached from the operation `approve` only). The step kind
imports this module and not those, so a step kind has no function in reach that could publish (limit L30; docs/architecture/platform/outputs.md).

The document. `effect` ("publish"), `operation` ("post": the word that tells this document from the reply of a standing approval, which has no
such key), `task` (the step task that prepared it), `provider` (the implementation of the class publisher:<platform> the project resolved to: the
publication is refused if it resolves to another now), `platform`, `content` (the post's file under docs/marketing/content/), `slot` (the time the
file names; the post is published now and not then), `text` and `text_sha256` (the post exactly as the publishing skill's own script wrote it for
the publisher), `comment` and `comment_sha256` (the first comment, or null), `image` (null, or `{source, name, bytes, sha256}`: the file is not in
the document, only its hash), `checks` (the content file's own line about its check, or null), `token_expires_at` (what the provider's check said, or
null), `ledger` (the path of the publisher's ledger, as its dry run printed it, or null: the file whose record of keys makes a post go out once),
`dry_run` (what the provider's dry run printed, without what changes with the ledger or the private folder) and `idempotency_key`.

The key is the one the publishing skill uses: the content file's name without `.md` (skills/mkt-publish/scripts/payload.py). The publisher's ledger
holds a key for one content and publishes it once, so a post that the skill's job already published is never published again by this path (a job
that is scheduled and has not run has written nothing to the ledger yet: if this path publishes first, the job is replayed when it runs), and one
published by this path is never published again by the skill's job: the same key, the same texts, the same image, the same ledger. This module
keeps the ledger's path in the document so that the approval covers it and the execution can tell a ledger that moved.

Standard library only, plus the credential scan of runtime/workcopy.py and the error class of runtime/effects.py. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effects  # noqa: E402  (the error class only)
import operations  # noqa: E402  (the command line the preview shows)
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

WORD = "publish"
OPERATION = "post"
KEYS = ("effect", "operation", "task", "provider", "platform", "content", "slot", "text", "text_sha256", "comment", "comment_sha256", "image",
        "checks", "token_expires_at", "ledger", "dry_run", "idempotency_key")
IMAGE_KEYS = ("source", "name", "bytes", "sha256")
CONTENT_DIR = "docs/marketing/content/"
KEY = re.compile(r"[a-z0-9][a-z0-9.-]{0,79}")           # the publishing skill's own rule for a key (payload.py KEY)
CONTENT_PATH = re.compile(r"docs/marketing/content/(?P<key>[a-z0-9][a-z0-9.-]{0,79})\.md")
PLATFORM = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")        # the resolver's name rule (providers/resolve.py) and payload.py's
PROVIDER = re.compile(r"[a-z][a-z0-9-]{0,39}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SLOT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:\d{2}|Z)")
IMAGE_SOURCE = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
IMAGE_NAME = re.compile(r"image\.[a-z0-9]{2,5}")
FENCE = re.compile(r"^```[\w-]*\s*$")
STATUS_LINE = re.compile(r"^\s*-\s*Status:\s*(.*?)\s*$", re.I)
CHECK_LINE = re.compile(r"^\s*-\s*check_post\.py:\s*(.*?)\s*$")
CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f\x85  ]")      # a text may have a line break (\n) and a tab, no other control character
TEXT_MAX = 30000               # characters of a post; the platform's own limit (its data file) is far lower and payload.py enforces it
COMMENT_MAX = 10000
CHECKS_MAX = 200
IMAGE_MAX = 20 * 1024 * 1024   # bytes: a sanity cap; the platform's data file holds the real one
DRY_RUN_MAX = 64 * 1024        # bytes of the dry run, as JSON
CONTENT_MAX = 256 * 1024       # bytes of the content file the task reads
STABLE_DROP = ("ledger",)      # the dry run's keys that say where the ledger is; the ones with "existing_" say what it holds now
POST_MARK = "<existing-post-id>"      # where a dry run of a published key names the post it holds (its address, its id): the same in every form
WILDCARD_MAX = 200      # characters of a document's placeholder that a post id may stand for


def sha(data) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _usage(reason: str):
    return effects.EffectError("usage", reason)


def content_key(content) -> str:
    """The key of a content file: its name without `.md`, as the publishing skill derives it. EffectError usage when the path is not one."""
    found = CONTENT_PATH.fullmatch(content) if isinstance(content, str) else None
    if not found or found.group("key").endswith(".comments"):      # a `.comments.md` file holds the comments on a document, never a post
        raise _usage(f"the post is a file {CONTENT_DIR}<name>.md, with a name of lowercase letters, digits, dots and hyphens")
    return found.group("key")


def platform_name(value) -> str:
    """The platform's name in lowercase; EffectError usage when it is not a name."""
    name = value.strip().lower() if isinstance(value, str) else ""
    if not PLATFORM.fullmatch(name):
        raise _usage("the platform is a name of lowercase letters, digits and hyphens")
    return name


def header_facts(text: str) -> dict:
    """What a content file says about itself, outside its fenced blocks: `blocked` (its `- Status:` line starts with the word blocked) and `checks`
    (the value of its `- check_post.py:` line, or None when there is none or it holds a control character or is over CHECKS_MAX characters).
    Both are the drafting step's own words and decide nothing but the refusal of a blocked post; the person reads the second one on the card."""
    blocked, checks, fenced = False, None, False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        found = STATUS_LINE.match(line)
        if found and found.group(1).lower().startswith("blocked"):
            blocked = True
        found = CHECK_LINE.match(line)
        if found and checks is None and found.group(1) and len(found.group(1)) <= CHECKS_MAX and not CONTROL.search(found.group(1)):
            checks = found.group(1)
    return {"blocked": blocked, "checks": checks}


def stable_dry_run(answer, folders=()) -> dict:
    """What the provider's dry run printed, without what is not about the post: the keys that name the ledger or say what it holds now, and every
    private folder's path (the dry run names the image file it was given), written `<private>`. The result is what the document keeps and what
    the execution compares the second dry run with. EffectError usage when it is not one JSON object or is over DRY_RUN_MAX bytes."""
    if not isinstance(answer, dict):
        raise _usage("the provider's dry run is one JSON object")
    kept = {k: v for k, v in answer.items() if k not in STABLE_DROP and "existing_" not in k}
    text = json.dumps(kept, sort_keys=True, ensure_ascii=True)
    held = answer.get("existing_post_urn")      # once a key is published, a dry run puts the post it holds into the first comment's request
    if isinstance(held, str) and held:
        for form in sorted({held, urllib.parse.quote(held, safe=""), urllib.parse.quote(held)}, key=len, reverse=True):
            text = text.replace(json.dumps(form)[1:-1], POST_MARK)
    for folder in sorted({f for path in folders for f in (path, os.path.realpath(path))}, key=len, reverse=True):
        if folder:
            text = text.replace(json.dumps(folder, ensure_ascii=True)[1:-1], "<private>")
    if len(text.encode("utf-8")) > DRY_RUN_MAX:
        raise _usage(f"the provider's dry run is over {DRY_RUN_MAX} bytes")
    return json.loads(text)


def _wildcard(expected: str, shown: str) -> bool:
    """Whether `shown`, which names the post a published key holds (POST_MARK), is `expected`, a dry run made before the post existed, with a
    placeholder where the mark is: the text around each mark is equal, and the placeholder is at most WILDCARD_MAX characters."""
    parts = shown.split(POST_MARK)
    if not expected.startswith(parts[0]) or not expected.endswith(parts[-1]) or len(expected) < len(parts[0]) + len(parts[-1]):
        return False
    position, end = len(parts[0]), len(expected) - len(parts[-1])
    for middle in parts[1:-1]:
        found = expected.find(middle, position, end)
        if found < 0 or found - position > WILDCARD_MAX:
            return False
        position = found + len(middle)
    return end - position <= WILDCARD_MAX


def same_dry_run(expected, shown) -> bool:
    """Whether the dry run now (stable_dry_run's result) is the one in the document. They are equal, except that where the dry run now names the post
    a published key holds (POST_MARK), the document, made before the post existed, has the provider's placeholder: the first comment's request
    names the post it comments on. Everything else, the text of the comment included, must be equal."""
    if isinstance(expected, dict) and isinstance(shown, dict):
        return set(expected) == set(shown) and all(same_dry_run(expected[k], shown[k]) for k in expected)
    if isinstance(expected, list) and isinstance(shown, list):
        return len(expected) == len(shown) and all(same_dry_run(a, b) for a, b in zip(expected, shown))
    if isinstance(expected, str) and isinstance(shown, str):
        return expected == shown or (POST_MARK in shown and _wildcard(expected, shown))
    return type(expected) is type(shown) and expected == shown


def _checked_text(value, what: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\r" in value or CONTROL.search(value) or len(value) > limit:
        raise _usage(f"the {what} is non-empty text of at most {limit} characters, with line breaks written \\n and no control character")
    return value


def document(*, task_id: int, provider: str, platform: str, content: str, slot: str, text: str, comment, image, checks, token_expires_at,
             ledger, dry_run: dict) -> dict:
    """The effect document, checked. `image` is None or {source, name, bytes, sha256}; `dry_run` is stable_dry_run's result. EffectError usage when
    a piece is not in its form, a limit is passed, or the text or the comment holds what looks like a credential."""
    doc = {"effect": WORD, "operation": OPERATION, "task": task_id, "provider": provider, "platform": platform, "content": content, "slot": slot,
           "text": text, "text_sha256": sha(text) if isinstance(text, str) else "", "comment": comment,
           "comment_sha256": sha(comment) if isinstance(comment, str) else None, "image": image, "checks": checks,
           "token_expires_at": token_expires_at, "ledger": ledger, "dry_run": dry_run, "idempotency_key": content_key(content)}
    check(doc)
    return doc


def check(doc) -> dict:
    """The document is in its form, or EffectError usage. Run when it is made and again just before the publication."""
    if not isinstance(doc, dict) or set(doc) != set(KEYS) or doc["effect"] != WORD or doc["operation"] != OPERATION:
        raise _usage("the effect document of a post has exactly its keys")
    if not isinstance(doc["task"], int) or isinstance(doc["task"], bool) or doc["task"] < 1:
        raise _usage("task is a task id")
    if not isinstance(doc["provider"], str) or not PROVIDER.fullmatch(doc["provider"]):
        raise _usage("provider is the name of an implementation")
    if platform_name(doc["platform"]) != doc["platform"]:
        raise _usage("the platform is a name of lowercase letters, digits and hyphens")
    key = content_key(doc["content"])
    if doc["idempotency_key"] != key or not KEY.fullmatch(key):
        raise _usage("the key is the content file's name without .md")
    if not isinstance(doc["slot"], str) or not SLOT.fullmatch(doc["slot"]):
        raise _usage("slot is the time the content file names, with its offset")
    text = _checked_text(doc["text"], "post", TEXT_MAX)
    if doc["text_sha256"] != sha(text):
        raise _usage("the text is not the one whose hash the document states")
    if doc["comment"] is None:
        if doc["comment_sha256"] is not None:
            raise _usage("a post without a first comment has no comment hash")
        comment = ""
    else:
        comment = _checked_text(doc["comment"], "first comment", COMMENT_MAX)
        if doc["comment_sha256"] != sha(comment):
            raise _usage("the first comment is not the one whose hash the document states")
    image = doc["image"]
    if image is not None:
        if not isinstance(image, dict) or set(image) != set(IMAGE_KEYS):
            raise _usage("an image has exactly its keys")
        if not isinstance(image["source"], str) or not IMAGE_SOURCE.fullmatch(image["source"]) or ".." in image["source"].split("/"):
            raise _usage("the image is a file of the project, given by a plain relative path")
        if not isinstance(image["name"], str) or not IMAGE_NAME.fullmatch(image["name"]):
            raise _usage("the image's name is image and its extension")
        if not isinstance(image["bytes"], int) or isinstance(image["bytes"], bool) or not 0 < image["bytes"] <= IMAGE_MAX \
                or not isinstance(image["sha256"], str) or not SHA256.fullmatch(image["sha256"]):
            raise _usage("an image has its size and its sha256")
    checks = doc["checks"]
    if checks is not None and (not isinstance(checks, str) or not checks or len(checks) > CHECKS_MAX or CONTROL.search(checks)):
        raise _usage("checks is the content file's one line, or null")
    expires = doc["token_expires_at"]
    if expires is not None and (not isinstance(expires, str) or not expires or len(expires) > 40 or CONTROL.search(expires)):
        raise _usage("token_expires_at is the provider's time, or null")
    ledger = doc["ledger"]
    if ledger is not None and (not isinstance(ledger, str) or not os.path.isabs(ledger) or len(ledger) > 1000 or CONTROL.search(ledger)):
        raise _usage("ledger is the absolute path the publisher's dry run printed, or null")
    dry = doc["dry_run"]
    if not isinstance(dry, dict) or stable_dry_run(dry) != dry:
        raise _usage("dry_run is the provider's dry run without the ledger and what it holds now")
    why = workcopy.scan((doc["text"] + "\n" + comment).encode("utf-8"))
    if why:
        raise _usage(f"the post or its first comment {why}: it is not published anywhere")
    return doc


def title(doc: dict) -> str:
    """The title of the pending decision."""
    first = doc["text"].strip().splitlines()[0] if doc["text"].strip() else ""
    return f"Publish now on {doc['platform']}: {first[:80]}"


def describe(doc: dict) -> str:
    """What is approved, in one line."""
    first = " ".join(doc["text"].split())
    return f"publish a post on {doc['platform']} ({doc['idempotency_key']}): {first[:120]}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect: closed words and numbers, never the text."""
    return {"platform": doc["platform"], "key": doc["idempotency_key"], "characters": len(doc["text"]), "first_comment": doc["comment"] is not None,
            "image": doc["image"] is not None, "text_sha256": doc["text_sha256"]}


def facts(doc: dict, done: dict) -> dict:
    """What the execution records of a publication that landed: `done` is {"replayed", "post_url", "first_comment"}."""
    return {"published": True, "replayed": done.get("replayed") is True, "post_url": done["post_url"], "first_comment": done["first_comment"],
            "idempotency_key": doc["idempotency_key"]}


def body(doc: dict, digest: str) -> str:
    """What the person reads before approving, the whole post: the platform and when it goes out first, then the text exactly as written, the first
    comment, the image by name, size and hash, what the provider's dry run says it will send, and the hash of the effect with the command that
    approves it."""
    comment, image = doc["comment"], doc["image"]
    lines = ["Code publishes this post after your approval, once, as it is below, and nothing else.", "",
             f"Platform: {doc['platform']} (publisher: {doc['provider']})",
             f"It is published NOW, when you approve, and not at its slot ({doc['slot']}): scheduling stays with the publishing skill.",
             f"Content file: {doc['content']}",
             f"Key: {doc['idempotency_key']} (the publisher publishes a key once, and the publishing skill uses the same key: a post that went out by "
             "either path is not published again by the other)",
             f"Token: valid until {doc['token_expires_at']}" if doc["token_expires_at"] else "Token: the provider states no expiry",
             f"The content file's own check line: {doc['checks'] or 'none recorded'}",
             f"Ledger (the publisher's record of the keys it published): {doc['ledger'] or 'the provider names none'}", "",
             "----- the post, exactly as written -----", doc["text"].rstrip("\n"), "----- end of the post -----", ""]
    if comment is None:
        lines += ["First comment: (none)", ""]
    else:
        lines += [f"First comment (published right after the post, under the key {doc['idempotency_key']}.first-comment):",
                  "----- the first comment, exactly as written -----", comment.rstrip("\n"), "----- end of the first comment -----", ""]
    if image is None:
        lines += ["Image: (none)", ""]
    else:
        lines += [f"Image: {image['name']}, {image['bytes']} bytes, sha256 {image['sha256']} (a copy of {image['source']}, published only if it is still the "
                  "same file)", "The image itself is not on this card: look at it in the project before you approve.", ""]
    lines += ["----- what the provider's dry run says it will send (the ledger's own lines left out) -----",
              json.dumps(doc["dry_run"], indent=1, sort_keys=True, ensure_ascii=False), "----- end of the dry run -----", "",
              f"Hash of this effect (it covers the text, the first comment, the image, the ledger and the dry run): {digest}",
              "Approve exactly this: " + operations.command_line("approve", "<project>", pending_id="<this pending decision's id>", sha256=digest),
              "It is published once, whatever the number of approvals of this hash. Or answer with what to change, or reject it: nothing is published "
              "until you approve."]
    return "\n".join(lines) + "\n"


def provider_args(platform: str, key: str, text_file: str, comment_file=None, image_file=None) -> list:
    """The flags of the publisher's `publish`, without --dry-run or --confirmed: the platform, the text, the first comment and the image as files
    (the last two or None), and the key. No --at (a post is published now) and no --ledger (both paths use the provider's own)."""
    args = ["--platform", platform, "--text-file", text_file]
    if comment_file is not None:
        args += ["--first-comment-file", comment_file]
    if image_file is not None:
        args += ["--media", image_file]
    return args + ["--idempotency-key", key]
