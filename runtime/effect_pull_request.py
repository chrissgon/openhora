#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The effect kind of the pull-request skill: one commit made by the code provider, then the pull request opened.

A kind is a module of runtime/ with these names, and a row of the registry runtime/effects.py KINDS (the key is the
side-effect word the skill's manifest names in its gate, gate.effect). The approval path of runtime/ops.py calls them
and knows nothing else of the kind:

    PROVIDER_CLASS                       the class of provider that executes it (found through providers/resolve.py)
    refusal(cfg, current)                why a task of this kind cannot start, or None
    head(cfg, task)                      the head branch the runtime names for the task
    prepare(current, copy, root, cfg, task, message)   puts the work copy in the form the skill was measured in
    parse(payload_text)                  the fields of the payload the skill showed at its gate, or None
    mismatch(parsed, cfg, task)          why the payload disagrees with the configuration, or None
    document(effect, cfg, request, payload, changeset, task, payload_file_sha256)   the effect document
    body(doc, sha256)                    what the person reads before approving
    title(doc), describe(doc)            the pending decision's title; one line that says what is approved
    summary(doc)                         what the pending decision's payload records of the effect
    unconfigured(cfg)                    why the configuration cannot carry the effect, or None
    verify(doc, changeset, facts, protected)   before execution: nothing moved since the gate
    execute(doc, changeset_dir, work_dir, provider, key_prefix, run=None)   the effect, by code

Usage (a library): python3 runtime/effect_pull_request.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import changeset as changesets  # noqa: E402  (the same folder)
import effects  # noqa: E402
import operations  # noqa: E402  (the table of operations: the one place that spells the terminal's command)

PROVIDER_CLASS = "integration:vcs"
GATE = True  # a skill's confirmation gate can name its word (runtime/effects.py)
POLICY = False  # a gate kind: the person approves its exact content, never a standing approval (runtime/effects.py)
FENCE = re.compile(r"^\s*(```|~~~)")
BASE_HEAD = re.compile(r"^Base ← head:\s*(?P<base>\S+)\s*←\s*(?P<head>\S+)\s*$")
EffectError = effects.EffectError


def unconfigured(cfg: dict):
    """Why the configuration cannot carry this effect, or None."""
    return None if cfg.get("code") else "the configuration has no code: no pull request can be opened"


def refusal(cfg: dict, current):
    """Why a task whose skill has this gate cannot start, or None: it needs the configuration's code (the base
    branch) and a change set of its request to show."""
    if not cfg.get("code"):
        return "the configuration has no code (provider, repo, base): a task with a confirmation gate needs it"
    if current is None or not (current.get("files") or current.get("removed")):
        return "there is no change to open a pull request for"
    return None


def head(cfg: dict, task: dict) -> str:
    """The head branch of a request's pull request: <branch_prefix>request-<request id> (choice K10)."""
    return f"{cfg['code']['branch_prefix']}request-{task['parent_id']}"


def prepare(current: dict, copy: str, root: str, cfg: dict, task: dict, message: str) -> None:
    """T23: a skill runs only up to its gate, in the form it was measured in: its branch with one commit on top of
    the base, and no remote."""
    changesets.as_branch(current, copy, root, base=cfg["code"]["base"], head=head(cfg, task), message=message)


def mismatch(parsed: dict, cfg: dict, task: dict):
    """Why the payload disagrees with the configuration, or None."""
    if unconfigured(cfg):
        return unconfigured(cfg)
    wanted_head = head(cfg, task)
    if (parsed["base"], parsed["head"]) != (cfg["code"]["base"], wanted_head):
        return (f"the payload's base and head ({parsed['base']} ← {parsed['head']}) are not the configuration's "
                f"({cfg['code']['base']} ← {wanted_head})")
    return None


def title(doc: dict) -> str:
    """The title of the pending decision."""
    return f"Pull request: {doc['title']}"


def summary(doc: dict) -> dict:
    """What the pending decision's payload records of the effect."""
    return {"repo": doc["repo"], "base": doc["base"], "head": doc["head"]}


def describe(doc: dict) -> str:
    """What is approved, in one line."""
    return f"pull request {doc['head']} into {doc['base']} of {doc['repo']}: {doc['title']}"


def parse(text: str):
    """{"repository", "base", "head", "title", "body"} of a payload in the pull-request skill's form, or None. The
    form, line by line: "Repository: ..."; "Base ← head: <base> ← <head>"; optionally "Commits:" and its "- ..."
    lines; "Title: <title>"; "Body:"; then the body, everything after it. One leading and one trailing code-fence
    line are dropped. Anything else is None."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    if lines and FENCE.match(lines[0]):
        lines = lines[1:]
    if lines and FENCE.match(lines[-1]):
        lines = lines[:-1]
    if len(lines) < 4 or not lines[0].startswith("Repository:"):
        return None
    repository = lines[0][len("Repository:"):].strip()
    found = BASE_HEAD.match(lines[1])
    if not repository or not found:
        return None
    i = 2
    if lines[i] == "Commits:":
        i += 1
        while i < len(lines) and lines[i].startswith("- "):
            i += 1
    if i + 1 >= len(lines) or not lines[i].startswith("Title: ") or lines[i + 1] != "Body:":
        return None
    title = lines[i][len("Title: "):].strip()
    body = "\n".join(lines[i + 2:])
    if not title or not body.strip():
        return None
    return {"repository": repository, "base": found.group("base"), "head": found.group("head"), "title": title,
            "body": body}


def document(effect: str, cfg: dict, request: dict, payload: dict, changeset: dict, task: dict, payload_file_sha256: str) -> dict:
    """The effect document: the exact content the person approves, bound by one hash. repo and base come from the
    project's configuration (cfg["code"]), never from the payload; head is the branch the runtime named
    (<branch_prefix>request-<id>); title and body are the parsed payload's, as the skill showed them; the files and
    the removed paths are the change set's, each file by its hash."""
    code_cfg = cfg["code"]
    return {"effect": effect, "provider": code_cfg["provider"], "repo": code_cfg["repo"],
            "base": code_cfg["base"], "head": head(cfg, task), "title": payload["title"], "body": payload["body"],
            "commit_message": payload["title"] + "\n", "payload_file_sha256": payload_file_sha256,
            "project_commit": changeset["project_commit"], "changeset_sha256": changeset["sha256"],
            "files": [{"path": f["path"], "sha256": f["sha256"], "executable": bool(f["executable"])}
                      for f in sorted(changeset["files"], key=lambda f: f["path"])],
            "removed": sorted(changeset["removed"])}


def body(doc: dict, sha256: str) -> str:
    """What the person reads before approving: the repository, base and head, the title, the body whole, each file
    with its hash, each removed path, the hash, and the command that approves."""
    lines = ["Code opens this pull request after your approval, and nothing else:", "",
             f"Repository: {doc['repo']}", f"Base ← head: {doc['base']} ← {doc['head']}",
             f"Commit: one commit, made by the code provider with your own git and signature, over {doc['project_commit']}",
             f"Title: {doc['title']}", "Body:", doc["body"].rstrip("\n"), "", "Files:"]
    lines += [f"- {f['path']}" + (" (executable)" if f["executable"] else "") + f" sha256 {f['sha256']}" for f in doc["files"]]
    if doc["removed"]:
        lines += ["Removed:"] + [f"- {rel}" for rel in doc["removed"]]
    lines += ["", f"Hash of this effect: {sha256}",
              "Approve exactly this: " + operations.command_line(
                  "approve", "<project>", pending_id="<this pending decision's id>", sha256=sha256),
              "Or answer with what to change, or reject it: nothing is sent until you approve."]
    return "\n".join(lines) + "\n"


def verify(doc: dict, changeset: dict, facts: dict, protected) -> dict:
    """Before execution, the document's hash being the approved one already (effects.read_document): every stored
    file of the change set still has its hash (changeset.load() did it, and the document's files are the change
    set's); the change set still passes changeset.verify_for_commit with the project's versioned paths now and the
    protected paths accepted now. Returns the document. Raises EffectError("deviation")."""
    stored = [{"path": f["path"], "sha256": f["sha256"], "executable": bool(f["executable"])}
              for f in sorted(changeset["files"], key=lambda f: f["path"])]
    if (doc.get("files") != stored or doc.get("removed") != sorted(changeset["removed"])
            or doc.get("changeset_sha256") != changeset["sha256"]):
        raise EffectError("deviation", "the change set is not the one the effect names")
    try:
        changesets.verify_for_commit(changeset, facts, protected)
    except changesets.ChangesetError as e:
        raise EffectError("deviation", e.reason) from None
    return doc


def execute(doc: dict, changeset_dir: str, work_dir: str, provider: str, key_prefix: str, run=None) -> dict:
    """Run the code provider's verbs, as scripts/runtime_vote.py starts the same verb (the interpreter the script's header asks for, then the verb): the
    runtime passes no credential, the provider reads its own. In order: write the commit message, the title and the
    body into work_dir (a private folder); a dry run of commit-files, whose base commit must be the document's
    project_commit and whose branch must not exist yet (unless the key already committed); commit-files, one commit
    of exactly the change set's files, modes and removals; then, only when it succeeded, open-pr. Each verb has its
    own idempotency key (<key_prefix>-commit, <key_prefix>-pr): approving again after a failure replays what was
    done. Returns {"commit", "pushed", "pull_request": {"number", "url"}, "replayed"}. Raises EffectError."""
    os.makedirs(work_dir, mode=0o700, exist_ok=True)
    files = {}
    for name, text in (("message.txt", doc["commit_message"]), ("title.txt", doc["title"] + "\n"), ("body.md", doc["body"])):
        files[name] = os.path.join(work_dir, name)
        with open(files[name], "w", encoding="utf-8") as f:
            f.write(text)
    commit = ["commit-files", "--repo", doc["repo"], "--branch", doc["head"], "--from-branch", doc["base"],
              "--message-file", files["message.txt"]]
    for item in doc["files"]:
        commit += ["--file", f"{item['path']}={os.path.join(changeset_dir, 'files', *item['path'].split('/'))}",
                   "--mode", f"{item['path']}={'755' if item['executable'] else '644'}"]
    for rel in doc["removed"]:
        commit += ["--delete", rel]
    for rel in [item["path"] for item in doc["files"]] + doc["removed"]:
        commit += ["--allow", rel]
    commit += ["--idempotency-key", f"{key_prefix}-commit"]
    seen = effects.provider_call(provider, commit + ["--dry-run"], run)
    if seen.get("existing_status") != "committed":
        if seen.get("base_commit") != doc["project_commit"]:
            raise EffectError("deviation", "the base branch moved since the change was made: it is at "
                                           f"{seen.get('base_commit')}, the change was made against {doc['project_commit']}")
        if seen.get("branch_exists"):
            raise EffectError("deviation", f"the branch {doc['head']} already exists on the remote and is not this request's")
    made = effects.provider_call(provider, commit + ["--confirmed"], run)
    opened = effects.provider_call(provider, ["open-pr", "--repo", doc["repo"], "--head", doc["head"], "--base", doc["base"],
                                      "--title-file", files["title.txt"], "--body-file", files["body.md"],
                                      "--idempotency-key", f"{key_prefix}-pr", "--confirmed"], run)
    return {"commit": made.get("commit"), "pushed": bool(made.get("pushed")),
            "pull_request": {"number": opened.get("number"), "url": opened.get("url")},
            "replayed": bool(made.get("replayed")) and bool(opened.get("replayed"))}


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
