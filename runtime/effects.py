#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The external effects of the task runtime: what a skill with a confirmation gate showed at its gate, recovered
from what the run left, and (stage 4, WP-4.8) its execution by code once the person approved its hash.

A skill with a confirmation gate runs up to the gate (limit L16). The pull-request skill writes its payload, exactly
as it shows it, to payload.md in a folder from mktemp -d and states that file's path and sha256 in its reply. The
run's temporary folder comes back inside the run folder (runtime/lab.py, tmp_in_run), and the payload is taken from
there only when it is the file the reply hashed: the reply's text is never taken in its place, and nothing here
picks "the most likely" file.

When the person approves the hash of the effect document (effect.json in the run folder, which binds the repository
and the base of the configuration, the head the runtime named, the title and the body the skill showed, and every
file of the change set by its hash), code checks that nothing moved since, makes the one commit through the code
provider (commit-files, with the person's own git and signature) and opens the pull request (open-pr). The runtime
passes the provider no credential: it reads its own. No module of runtime/ runs git commit or git push itself.

What belongs to one kind of effect (its payload form, its document, what the person reads, its checks and its
execution) is a module of runtime/ with a fixed set of names (runtime/effect_pull_request.py states them), chosen by
the side-effect word the skill's manifest names in its gate. This module holds what no kind changes: recovering the
payload, the error, the effect file and its hash, the call of a provider, the row of the state file, and the registry.
A new kind is a module and a row of KINDS; runtime/ops.py does not change.

A kind may also be opened by a step task and not by a skill's gate (package P8, runtime/steps.py Gate): the STEP path. The kind
module then has STEP = True and its own document, check, title, body, describe, summary and execute (runtime/effect_write.py lists
them); the approval and the execution are runtime/ops_step_effects.py, called from ops.approve for an `effect` decision of a step
task. Its GATE and POLICY are False. Beside the names above, a STEP kind exposes the three that runtime/ops_step_effects.py asks of every
one, so that the approval names no platform: `preflight(cfg, doc, root)` ((exit code, sentence) when the project is not configured for
this effect now, else None), `caller(cfg, root)` (the `call(verb, args)` that reaches its provider) and `idempotency_key(doc, default)`
(the key the execution carries); and, optional, `is_long(doc)`, `FORGETS_KEYS` (False when the provider's ledger never forgets a key) and
`on_cards(doc)` (False when the whole effect cannot be on a messaging card). `write` is the write-back of a document (runtime/effect_write.py)
and `send` an e-mail from the project's outbox (runtime/effect_send.py).

The registry has one key per kind, and the key is a word of the side-effect vocabulary (contracts/environment.md,
SIDE_EFFECTS of scripts/validate.py): the gate path reads the word a skill's manifest names in its gate, the policy
path reads the word of the effect document a handler hands to ops.execute_under_policy, and both find the same module.
What a kind module exposes, in two groups:

    for both paths     describe(doc)                     one line that says what is approved or done: the state file's
                                                         row and the action's record
                       PROVIDER_CLASS                    the class of provider that executes it (providers/resolve.py)
                       GATE                              True when a skill's gate may name the kind's word; a
                                                         registered kind that is not GATE is no kind there (a review)
    for the gate path  refusal, head, prepare, parse, mismatch, document, body, title, summary, unconfigured, verify,
                       execute                           the names runtime/effect_pull_request.py lists and ops.py calls
    for the policy     POLICY                            True when the kind may run under a standing approval
    path               policy_platform(doc)              the platform the provider is resolved with, or None
                       policy_effect(doc)                {"kind", "target", "files", "items"}: what autonomy.covers
                                                         checks; its target, the resolved one, is the one recorded
                       policy_argv(doc)                  the verb and the document's args, without the flags in
                                                         RESERVED_FLAGS: the operation adds --allow per bound glob,
                                                         --idempotency-key, then --dry-run or --confirmed
                       resolve_targets(cfg, doc, resolve_call)   optional. For a kind whose bounds name a class of
                                                         targets (autonomy.TARGET_CLASSES): {class word: the set of
                                                         targets it holds now}, read from a recorded fact through
                                                         resolve_call(class, verb, args), the read-only call of a
                                                         provider; EffectError when the fact cannot be read. The
                                                         operation calls it before the write lock and hands the sets
                                                         to autonomy.covers; a kind without it resolves no class
                       policy_judgement(root, project, doc, run_script, policy_file, private, log=None, data_dir=None, now=None)
                                                         optional. (True, "", copies) or (False, why, {}): the checks a
                                                         kind owns that are not bounds, made after covers and before any
                                                         provider call, on the exact content (the engagement gate, run
                                                         through run_script, the credential scan). `private` is a folder
                                                         the operation made (0700) and removes; the kind writes there
                                                         the bytes it judged, and copies {flag: path} makes the
                                                         operation give the provider that path in place of the value
                                                         after the flag, so the content sent is the content judged.
                                                         `log` is None except in a replay, which names a copy of the log
                                                         the gate reads; `data_dir` is the project's data folder; `now`
                                                         is the operation's clock, ISO-8601 with its offset

A kind of one path alone has only that path's names. EFFECT_KEYS and RESERVED_FLAGS are the common shape of a
document a handler hands over and the flags the operation adds and a handler never may.

Public names: recover_payload(reply, tmp_dir, readable), EffectError, KINDS, EFFECT_KEYS, RESERVED_FLAGS,
module_for(kind), gate_kind(word, requires), policy_kinds(), write(run_dir, doc), read_document(effect_file, sha256),
provider_call(provider, args[, run]), approval_row(approval, doc).

Usage (a library): python3 runtime/effects.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import project_config  # noqa: E402  (the same folder: the resolver is loaded from here)

PAYLOAD_NAME = "payload.md"
CANDIDATES_MAX = 20
PAYLOAD_LINE = re.compile(r"^\s*Payload file:\s*`?(?P<path>[^`]+?)`?\s*,\s*sha256\s*`?(?P<sha>[0-9a-f]{64})`?\s*\.?\s*$")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def recover_payload(reply: str, tmp_dir, readable) -> dict:
    """The payload file a skill wrote at its gate: {"recovered": True, "file", "sha256", "text"} or {"recovered":
    False, "why"}. In order: (1) the reply holds exactly one line "Payload file: `<path>`, sha256 `<64 hex>`"; (2) the
    candidates are the regular files named payload.md under tmp_dir, found without following a link and each
    accepted by readable(tmp_dir, rel); none, or more than 20, is not recovered; (3) the chosen one is the candidate
    whose path ends with the stated path's last two parts, else the only candidate whose sha256 is the stated hash;
    (4) its bytes must have the stated hash."""
    lines = [m for m in (PAYLOAD_LINE.match(line) for line in (reply or "").splitlines()) if m]
    if not lines:
        return {"recovered": False, "why": "the reply names no payload file"}
    if len(lines) > 1:
        return {"recovered": False, "why": "the reply names more than one payload file"}
    stated, digest = lines[0].group("path").strip(), lines[0].group("sha")
    if not tmp_dir or not os.path.isdir(tmp_dir) or os.path.islink(tmp_dir):
        return {"recovered": False, "why": "the run left no temporary folder"}
    candidates = []
    for current, folders, files in os.walk(tmp_dir):  # never follows a link to a folder
        folders[:] = sorted(n for n in folders if not os.path.islink(os.path.join(current, n)))
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(current, name), tmp_dir).replace(os.sep, "/")
            if name == PAYLOAD_NAME and readable(tmp_dir, rel):
                candidates.append(rel)
    if not candidates:
        return {"recovered": False, "why": "no payload.md was found under the run's temporary folder"}
    if len(candidates) > CANDIDATES_MAX:
        return {"recovered": False, "why": f"more than {CANDIDATES_MAX} payload.md files under the run's temporary folder"}
    hashes = {}
    for rel in candidates:
        with open(os.path.join(tmp_dir, *rel.split("/")), "rb") as f:
            hashes[rel] = _sha(f.read())
    tail = "/".join(stated.replace("\\", "/").rstrip("/").split("/")[-2:])
    by_path = [rel for rel in candidates if rel == tail or rel.endswith("/" + tail)]
    by_hash = [rel for rel in candidates if hashes[rel] == digest]
    chosen = by_path[0] if len(by_path) == 1 else (by_hash[0] if not by_path and len(by_hash) == 1 else None)
    if chosen is None:
        return {"recovered": False, "why": "no single payload.md under the run's temporary folder is the one the reply names"}
    if hashes[chosen] != digest:
        return {"recovered": False, "why": "the file is not the one the reply hashed"}
    path = os.path.join(tmp_dir, *chosen.split("/"))
    with open(path, "rb") as f:
        data = f.read()
    return {"recovered": True, "file": path, "sha256": digest, "text": data.decode("utf-8", errors="replace")}


# --- the effect: approved by its hash, executed by code (WP-4.8; limits L15, L16, L17) -----------------------------

# The registry of the kinds of effect: a word of the side-effect vocabulary -> the module of runtime/ that holds the
# kind. For the gate path the word is the one a skill's manifest names in its gate (gate.effect); a word not here
# opens a review, never an effect. For the policy path it is the kind of the document a handler hands over.
KINDS = {"create": "effect_pull_request", "push": "effect_commit", "publish": "effect_reply", "write": "effect_write", "send": "effect_send"}

# The keys of the effect document a handler hands to ops.execute_under_policy, and no others; and the flags only the
# operation adds to the provider's verb, never a handler.
EFFECT_KEYS = ("policy", "kind", "target", "files", "items", "idempotency_key", "payload_sha256", "args")
RESERVED_FLAGS = ("--confirmed", "--dry-run", "--allow", "--idempotency-key")

EFFECT_FILE = "effect.json"
PROVIDER_TIMEOUT = 600


class EffectError(Exception):
    """kind is "deviation" (something moved since the gate), "provider" (the code provider failed), "not-configured"
    or "usage"; and, for a write-back (runtime/effect_write.py), "stale" (the target was edited since it was read) and
    "unknown" (the write call failed, so whether the target holds the content is not known)."""

    def __init__(self, kind: str, reason: str):
        super().__init__(reason)
        self.kind, self.reason = kind, reason


def module_for(kind):
    """The module of an effect kind, loaded by name from runtime/. An unknown kind is EffectError("usage")."""
    name = KINDS.get(kind) if isinstance(kind, str) else None
    if name is None:
        raise EffectError("usage", f"there is no effect kind {kind!r} (the kinds: {', '.join(sorted(KINDS))})")
    return importlib.import_module(name)


def gate_kind(word, requires):
    """The module of the effect kind a skill's confirmation gate names, or None. A side-effect word is shared by skills
    of different meaning (`create` is a pull request for the pull-request skill and a thing made in a design tool for a
    design skill), so the word alone never picks the kind: the module is the skill's only when it is a kind of the gate
    path (GATE) and the skill declares, among its `requires`, the class of provider that executes it (PROVIDER_CLASS).
    A skill that declares nothing, or another class, names no kind: its gate opens a review for the person to read and
    an effect is never opened, so nothing can run that the skill did not declare."""
    try:
        module = module_for(word)
    except EffectError:
        return None
    if getattr(module, "GATE", False) is not True or getattr(module, "PROVIDER_CLASS", None) not in (requires or ()):
        return None
    return module


def policy_kinds() -> list:
    """The words of the registry whose module may run under a standing approval (its POLICY), sorted."""
    return sorted(word for word in KINDS if getattr(module_for(word), "POLICY", False) is True)


def _text(doc: dict) -> bytes:
    return (json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=True) + "\n").encode("ascii")


def write(run_dir: str, doc: dict) -> tuple:
    """Write <run_dir>/effect.json (sorted keys, one-space indent, ASCII escapes, a final newline). Returns (path,
    sha256): the sha256 is the pending decision's payload_sha256, the hash the person types to approve."""
    data = _text(doc)
    path = os.path.join(run_dir, EFFECT_FILE)
    with open(path, "wb") as f:
        f.write(data)
    return path, _sha(data)


def read_document(effect_file: str, sha256: str) -> dict:
    """The effect document, only when the file's hash is the approved one. Raises EffectError("deviation")."""
    try:
        with open(effect_file, "rb") as f:
            data = f.read()
    except OSError as e:
        raise EffectError("deviation", f"the effect file cannot be read: {e.strerror}") from None
    if _sha(data) != sha256:
        raise EffectError("deviation", "the effect file is not the one approved: its hash changed")
    return json.loads(data.decode("ascii"))


def provider_call(provider: str, args: list, run=None) -> dict:
    """One verb of the provider script at the path `provider` (the code provider, found by its class in the
    operations layer), started by providers/resolve.py (resolve.invoke: the interpreter its header asks for): the one
    JSON object it printed. `run(argv)` starts the process (a stand-in in tests; _subprocess by default). Raises
    EffectError ("usage", "not-configured" or "provider")."""
    resolve = project_config.resolver(os.path.dirname(HERE))
    try:
        return resolve.invoke(provider, None, args, timeout=PROVIDER_TIMEOUT, run=run or _subprocess)
    except resolve.ProviderCallError as e:
        kind = {"usage": "usage", "not-configured": "not-configured"}.get(e.kind, "provider")
        raise EffectError(kind, f"{args[0]}: {e.reason}") from None


def _subprocess(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=PROVIDER_TIMEOUT, check=False)


def approval_row(approval: dict, doc: dict) -> list:
    """The generated copy of an approval for the state file's ## Approvals table (contracts/state.md): Scope, What,
    Payload hash, Approved, Expires, Status."""
    what = module_for(doc["effect"]).describe(doc)
    clean = lambda text: " ".join(str(text).replace("|", "/").split())
    return [approval["scope"], clean(what), f"sha256:{approval['payload_sha256']}", approval["approved_at"][:10],
            approval.get("expires_at") or "after execution", approval["status"]]


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
