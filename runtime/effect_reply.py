#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of a reply to a comment on one of the project's own posts, made by a publisher under a standing
approval.

It is the policy-path kind registered under the side-effect word `publish` (runtime/effects.py KINDS): the social
handler writes an effect document of that kind and hands it to ops.execute_under_policy, which checks the standing
approval of the engagement policy and runs the publisher's `comment` verb. This module answers what the operation asks
of a kind (the names are listed at the head of runtime/effects.py): that it may run under a policy, the class of
provider, the platform to resolve it with, the effect the approval is checked against, the verb and its arguments, the
line that says what was done, and, because the approval bounds a class of targets and not a list of them, the two
optional names that make the class a fact and add the judgement:

  resolve_targets   "a comment on a post this project published" is not read from the notification, whose text anyone
                    can write: the publisher's read-only verb `posts` lists the posts its ledger records (no token, no
                    request), the post ids are read back from their addresses by the platform's own template
                    (shared/references/platforms/<platform>.json), and a post is covered only when it is in that set.
                    A ledger that cannot be read, or lists nothing, covers nothing.
  policy_judgement  the checks a reply owns beyond the bounds, on the exact text: the file is read once, its bytes are
                    the ones the document hashed, they hold no credential (scripts/redact.py's formats, through
                    runtime/workcopy.py), and the engagement gate of mkt-engage (category, language, the daily and
                    per-person limits, sensitive topics, the reply rules, the sources) says `auto` with the idempotency
                    key the document carries. Those bytes are written to a private file (a folder the operation made,
                    0700, the file created exclusively, 0600); the gate reads that file and the operation gives the
                    publisher that path in place of --text-file, so the text sent is the text judged, whatever happens
                    to the run folder's file after the hash. The parent comment must be a comment on the post
                    (the platform's data file gives the form), and the run folder must be runs/<n> of the project's
                    data folder. The gate runs through runtime/isolated.py. Both conditions hold at once: the bound
                    (a standing approval, a class resolved from the ledger) and the judgement; the gate's `auto` is
                    never the approval.

The document. `args` are the publisher's own flags, each once: --platform, --post-id, --parent-comment-id, --text-file;
`target` is the post id; `items` is 1; `files` lists, as absolute paths in the folder of the text file, the four files the
judgement reads: comment.json (the comment, as the handler stored it), sources.json, decision.json ({"category",
"language"}, the agent's decision) and the text file itself. A document that does not fit is a usage error, and
nothing runs. `payload_sha256` is the sha256 of the text file.

No skill's confirmation gate names this word (GATE is False), so the gate path never opens an effect of this kind.

Usage (a library): python3 runtime/effect_reply.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import autonomy  # noqa: E402  (the same folder: the class of targets)
import effects  # noqa: E402
import isolated  # noqa: E402
import workcopy  # noqa: E402  (the credential formats, loaded from this checkout)

PROVIDER_CLASS = "publisher:<platform>"
GATE = False  # no skill's confirmation gate names this word: the gate path never opens an effect of this kind
POLICY = True
VERB = "comment"  # the publisher's verb that replies to a comment
TARGET_CLASS = autonomy.COMMENT_ON_PUBLISHED_POST
READ_VERB = "posts"  # the publisher's read-only verb: the posts its ledger records
FLAGS = ("--platform", "--post-id", "--parent-comment-id", "--text-file")
COMMENT, SOURCES, DECISION = "comment.json", "sources.json", "decision.json"  # the files beside the text
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")  # the resolver's name rule (providers/resolve.py)
EPOCH = "1970-01-01T00:00:00+00:00"  # posts since the beginning: a post stays one this project published
GATE_SKILL, GATE_SCRIPT = "mkt-engage", "policy_gate.py"
STATE, LOG, PROFILE = "docs/workbench/state.md", "docs/marketing/engagement-log.jsonl", "docs/brand/profile.md"
GATE_TIMEOUT = 300
HOLDS_CREDENTIAL = ("the drafted reply holds what looks like a credential ({label}); it cannot be sent: answer the "
                    "comment yourself")


def _usage(reason: str):
    return effects.EffectError("usage", reason)


def _parts(doc: dict) -> dict:
    """The document read for what it must hold: {"platform", "post", "parent", "text", "files": {file name: path}}.
    Anything else is a usage error: a flag the publisher's reply does not take (a --ledger would point the key's
    memory elsewhere), a flag twice or without a value, a target that is not the post, a number of items other than
    one, files that are not the four of the judgement in the text file's folder."""
    args = doc["args"]
    if len(args) != 2 * len(FLAGS):
        raise _usage(f"the arguments of a reply are exactly {', '.join(FLAGS)}, each once with a value")
    found = {}
    for flag, value in zip(args[0::2], args[1::2]):
        if flag not in FLAGS or flag in found or not value.strip() or value.startswith("--"):
            raise _usage(f"the arguments of a reply are exactly {', '.join(FLAGS)}, each once with a value")
        found[flag] = value
    if not NAME.fullmatch(found["--platform"]):
        raise _usage(f"the platform {found['--platform']!r} is not a name (lowercase letters, digits and hyphens)")
    if doc["target"] != found["--post-id"]:
        raise _usage("the target of a reply is the post id it comments on")
    if doc["items"] != 1:
        raise _usage("a reply is one item")
    text = found["--text-file"]
    names = {os.path.basename(path): path for path in doc["files"]}
    if len(names) != len(doc["files"]) or set(names) != {COMMENT, SOURCES, DECISION, os.path.basename(text)} \
            or len(names) != 4 or names.get(os.path.basename(text)) != text:
        raise _usage(f"the files of a reply are {COMMENT}, {SOURCES}, {DECISION} and its text file, each once")
    if not all(os.path.isabs(path) and os.path.dirname(path) == os.path.dirname(text) for path in names.values()):
        raise _usage("the files of a reply are absolute paths in the folder of its text file")
    return {"platform": found["--platform"], "post": found["--post-id"], "parent": found["--parent-comment-id"],
            "text": text, "files": names}


def policy_platform(doc: dict):
    """The platform the publisher is resolved with: the value of --platform."""
    return _parts(doc)["platform"]


def policy_effect(doc: dict) -> dict:
    """What the standing approval is checked against (autonomy.covers): the reply is one item on a post; it writes no
    file of the project, so its files are none. The target, once covered, is the one recorded."""
    return {"kind": doc["kind"], "target": _parts(doc)["post"], "files": [], "items": 1}


def policy_argv(doc: dict) -> list:
    """The publisher's verb and the document's own arguments, without the flags the operation adds."""
    _parts(doc)
    return [VERB, *doc["args"]]


def describe(doc: dict) -> str:
    """What is done, in one line."""
    return f"reply to a comment on post {doc['target']}"


def _platform_urls(cfg: dict, platform: str) -> tuple:
    """(the template of a post's address, the pattern of a post id) from the platform's data file."""
    path = os.path.join(cfg["workbench"], "shared", "references", "platforms", f"{platform}.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        template, pattern = data["post"]["url"]["template"], data["identifiers"]["post"]["pattern"]
        head, sep, tail = template.partition("{post_id}")
        if not sep or "{post_id}" in tail:
            raise ValueError("the template holds {post_id} once")
        return (head, tail), re.compile(pattern)
    except (OSError, ValueError, KeyError, TypeError, re.error) as e:
        raise effects.EffectError("not-configured", f"the data file of the platform {platform} cannot be read "
                                                    f"({type(e).__name__}): the posts cannot be recognised") from None


def resolve_targets(cfg: dict, doc: dict, resolve_call) -> dict:
    """{TARGET_CLASS: the set of post ids the publisher's ledger records as published}. resolve_call(class, verb, args)
    starts a verb of the provider of a class and returns the one JSON object it printed (an EffectError when it fails).
    The ledger is read through the publisher's `posts` verb, which reads the ledger and nothing else; each post's
    address is turned back into its id by the platform's template, and an entry whose address is not one of the
    platform's, or whose id is not a post id by the platform's pattern, is left out. EffectError when the ledger cannot
    be read or does not answer a list of posts; an empty ledger is an empty set, which covers nothing."""
    parts = _parts(doc)
    platform = parts["platform"]
    bad = _parent_of_post(cfg["workbench"], parts)
    if bad:
        raise effects.EffectError("usage", bad)
    (head, tail), pattern = _platform_urls(cfg, platform)
    try:
        answer = resolve_call(PROVIDER_CLASS.replace("<platform>", platform), READ_VERB,
                              ["--platform", platform, "--since", EPOCH])
    except effects.EffectError as e:
        raise effects.EffectError("provider", f"the publisher's ledger could not be read: {e.reason}") from None
    posts = answer.get("posts") if isinstance(answer, dict) else None
    if not isinstance(posts, list) or not all(isinstance(post, dict) for post in posts):
        raise effects.EffectError("provider", "the publisher's ledger could not be read: it did not answer a list of posts")
    ids = set()
    for post in posts:
        url = post.get("post_url")
        if isinstance(url, str) and url.startswith(head) and url.endswith(tail) and len(url) > len(head) + len(tail):
            found = url[len(head):len(url) - len(tail)] if tail else url[len(head):]
            if pattern.fullmatch(found):
                ids.add(found)
    return {TARGET_CLASS: ids}


def _parent_of_post(workbench: str, parts: dict) -> str:
    """"" when --parent-comment-id is a comment on --post-id, else why not. The platform's data file gives the forms of a
    comment id (identifiers.comment and identifiers.comment_short); the id embeds the post it is on (every group but the
    last, the comment's own number), which must be the post of the request, because the publisher addresses the request
    to the parent comment."""
    path = os.path.join(workbench, "shared", "references", "platforms", f"{parts['platform']}.json")
    try:
        with open(path, encoding="utf-8") as f:
            ids = json.load(f)["identifiers"]
        forms = [re.compile(ids[key]["pattern"]) for key in ("comment", "comment_short")]
    except (OSError, ValueError, KeyError, TypeError, re.error) as e:
        return f"the data file of the platform {parts['platform']} cannot be read ({type(e).__name__}): the parent comment cannot be checked"
    for form in forms:
        found = form.fullmatch(parts["parent"])
        if found:
            embedded = found.groups()[:-1]
            post = parts["post"]
            if post == ":".join(embedded) or (len(embedded) > 1 and post.endswith(":" + ":".join(embedded))):
                return ""
            return "the parent comment is not a comment on the post of the request"
    return "the parent comment is not an id of a comment of the platform"


def _regular(path: str) -> bool:
    return os.path.isfile(path) and not os.path.islink(path)


def policy_judgement(root: str, project: str, doc: dict, run_script, policy_file: str, private: str, log=None,
                     data_dir=None, now=None) -> tuple:
    """(True, "", copies) or (False, why, {}): the checks of a reply beyond the bounds, on the exact text, made before any
    provider call. In this order: the parent comment is a comment on the post; the run folder is runs/<n> of data_dir
    (not in a replay, which names `log` and executes nothing); every file of the document is a regular file (not a
    link); the text file is read once and its bytes are the ones the document hashed; they hold no credential; they are
    written to a private file in `private` (a folder the caller made, 0700, and removes), which the gate reads; the
    engagement gate (mkt-engage's policy_gate.py decide, started through run_script, the isolated runner, in the
    project's folder, on the approved policy file, at `now`) answers `auto` with the idempotency key of the document.
    copies is {"--text-file": the private path}: the caller gives the publisher that path in place of the document's, so
    the text sent is the text judged. why is what a person reads: the gate's reasons when it says inbox. `log` names
    another copy of the engagement log for the gate to read (a replay only)."""
    parts = _parts(doc)
    bad = _parent_of_post(root, parts)
    if bad:
        return False, bad, {}
    if data_dir is not None and log is None:
        folder = os.path.realpath(os.path.dirname(parts["text"]))
        if os.path.dirname(folder) != os.path.join(os.path.realpath(data_dir), "runs") or not os.path.basename(folder).isdigit():
            return False, "the files of a reply are in a run folder, runs/<n> of the project's data folder: nothing was sent", {}
    for name, path in sorted(parts["files"].items()):
        if not _regular(path):
            return False, f"{name} is not a regular file the judgement can read", {}
    with open(parts["text"], "rb") as f:
        data = f.read()
    if hashlib.sha256(data).hexdigest() != doc["payload_sha256"]:
        return False, "the reply text is not the one the document hashed (its sha256 changed): nothing was sent", {}
    held = workcopy.credential_findings(data.decode("utf-8", errors="replace"))
    if held:
        return False, HOLDS_CREDENTIAL.format(label=held[0]), {}
    copy = os.path.join(private, os.path.basename(parts["text"]))
    fd = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    try:
        with open(parts["files"][DECISION], encoding="utf-8") as f:
            decision = json.load(f)
        category, language = decision["category"], decision["language"]
        if set(decision) != {"category", "language"} or not all(isinstance(v, str) and v.strip() for v in (category, language)):
            raise ValueError("two texts")
    except (OSError, ValueError, KeyError, TypeError):
        return False, f"{DECISION} does not hold exactly a category and a language", {}
    args = ["decide", "--policy", policy_file, "--state", STATE, "--log", log or LOG,
            "--comment-file", parts["files"][COMMENT], "--category", category, "--language", language,
            "--profile", PROFILE, "--reply-file", copy, "--sources-file", parts["files"][SOURCES],
            "--skills-dir", os.path.join(root, "skills"), *(["--now", now] if now else [])]
    script = isolated.skill_script(root, GATE_SKILL, GATE_SCRIPT)
    try:
        done = run_script(script, args, cwd=project, timeout=GATE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"the engagement gate could not run ({type(e).__name__}): nothing was sent", {}
    if done.returncode != 0:
        return False, "the engagement gate failed: " + " ".join((done.stderr or "").split())[-300:], {}
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or answer.get("decision") not in ("auto", "inbox"):
        return False, "the engagement gate did not answer auto or inbox: nothing was sent", {}
    if answer["decision"] != "auto":
        reasons = answer.get("reasons") if isinstance(answer.get("reasons"), list) else []
        return False, "the engagement gate sends this reply to the inbox: " + "; ".join(str(r) for r in reasons), {}
    if answer.get("idempotency_key") != doc["idempotency_key"]:
        return False, (f"the engagement gate's key for this comment is {answer.get('idempotency_key')}, not the document's "
                       f"{doc['idempotency_key']}: nothing was sent"), {}
    return True, "", {"--text-file": copy}


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
