#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The configuration's acceptance in the operations layer: who may accept a change of docs/workbench/runtime.json, and
the two operations that change or accept it.

A change of the configuration takes effect only when its hash is the accepted one (contracts/runtime.md, "The
configuration, and who may accept a change of it"). The accepted hash has one writer, `_record_acceptance`, and three
paths reach it, each under the configuration lock (ops_core._config_lock):

  accept_config   the person, in the terminal, who typed the hash after reading the file: `by: "person"`
  set_mode        a move down the order of the modes (code, because it widens nothing): `by: "code:narrowing"`
  set_mode --accept   a move up the order, set and accepted in one step by the person, in the terminal only
                  (ACCEPT_CHANNELS): `by: "person"`, and only when the file was the accepted one before the call, so
                  the one difference this accepts is the mode the command names. A configuration with any other
                  unaccepted change is refused and nothing is written: the person reads the file and runs accept-config.

Functions:
  _record_acceptance(ctx, cfg, sha256, by)   record the accepted hash, who accepted it, and the state file's Checkpoints line
  write_checkpoints(cfg)                    the state file's "- Checkpoints:" line rewritten from the area agents
  accept_config(project, sha256)            the person accepts a hash
  set_mode(project, agent, mode[, accept, channel])   set one area agent's autonomy mode

Sibling of runtime/ops.py, which exposes the operations under their names; no shell imports this file. The shared
names come from ops_core (read as `core.<name>`, at call time). It reaches no operation of ops.py.
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

import operations
import ops_core as core
import autonomy
import path_rule
import project_config
import state_merge

ACCEPTED_BY = "config:accepted-by"  # the store's cursor that says who accepted the hash in ACCEPTED: "person" or "code:narrowing"
ACCEPT_CHANNELS = ("terminal",)     # the only channel that may pass `accept` to set_mode: the person, in the terminal


def _sha256(path: str):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _read(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _record_acceptance(ctx: dict, cfg: dict, sha256: str, by: str) -> dict:
    """Record sha256 as the accepted hash of cfg's file, and who accepted it, and rewrite the state file's Checkpoints
    line. The one writer of the accepted hash: accept_config (the person, in the terminal) and set_mode (code, for a
    move down the order of the modes, which widens nothing; the person, for a move up, with `accept` from the terminal)
    call it, and nothing else does. Returns {"previous", "checkpoints"}."""
    previous = core._stored(ctx, ctx["store"].cursor_get, project_config.ACCEPTED)
    core._stored(ctx, ctx["store"].cursor_set, ACCEPTED_BY, by)
    core._stored(ctx, ctx["store"].cursor_set, project_config.ACCEPTED, sha256)
    return {"previous": previous, "checkpoints": write_checkpoints(cfg)}


def accept_config(project: str, sha256: str) -> dict:
    """Record the hash of the project's configuration that the person accepts, after reading the file. The only
    operation that accepts any change of it (set_mode accepts a move down the order of the modes, and, for the person
    in the terminal, the one move up it sets), and the only one that runs on a configuration that was not accepted.
    Returns {"accepted", "previous", "path", "checkpoints"}."""
    ctx = core.context(project, check_config=False)
    cfg = ctx["cfg"]
    with core._config_lock(cfg):
        cfg = core._config_of(project)  # the file as it is now, under the lock
        if sha256 != cfg["sha256"]:
            raise core.OpsError(f"the file's hash is {cfg['sha256']} and you typed {sha256}: nothing was accepted", 1)
        done = _record_acceptance(ctx, cfg, sha256, "person")
    return {"accepted": sha256, "previous": done["previous"], "path": cfg["path"], "checkpoints": done["checkpoints"]}


def write_checkpoints(cfg: dict):
    """The state file's "- Checkpoints:" line rewritten from the area agents (autonomy.state_checkpoints): only its
    value changes, and only when the configuration has area agents and the file did not change between its read and
    the write (L12). Returns {"written", "value"}, or a text saying why nothing was written."""
    if cfg["raw"].get("area_agents") is None:
        return "no area agents are configured"
    target = os.path.join(cfg["project"], *path_rule.STATE.split("/"))
    with core._write_lock(cfg):  # inside the config lock when the acceptance calls it: config lock first, then the write lock
        if not os.path.isfile(target) or os.path.islink(target):
            return "the project has no state file"
        value = autonomy.state_checkpoints(cfg["area_agents"])
        before = _sha256(target)
        text, found = state_merge.with_checkpoints(_read(target), value)
        if not found:
            return "no line to write"
        if _sha256(target) != before:
            return "the state file changed while the line was being written; it is written at the next acceptance"
        temporary = f"{target}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, target)
        return {"written": True, "value": value}


def set_mode(project: str, agent: str, mode: str, accept: bool = False, channel=None) -> dict:
    """Set one area agent's autonomy mode: only area_agents.<agent>.mode of runtime.json changes (decision P1: the
    mode is the configuration's word). A move down the order of the modes (autonomy.MODES: stopped < supervised <
    milestones < autonomous < autonomous-with-policy) widens nothing, so code accepts the new hash at once, as the
    acceptance accept-config writes, recorded `code:narrowing`, and no operation refuses afterwards. A move up leaves
    the hash unaccepted: every operation then refuses until the person accepts it (accept-config), and `next` is the
    command, unless the person passes `accept` in the terminal: then the hash is accepted in the same locked step,
    recorded `person`, on one condition checked under the lock, that the configuration was the accepted one before
    this change (so the only difference accepted is this mode). Any other state (another unaccepted change, a file that
    moved since the call began) is refused and nothing is written: the person reads the file and runs accept-config.
    `accept` is refused (code 2, before anything is read) from any channel but ACCEPT_CHANNELS: the local page, the
    conversation and the MCP mode can never accept what widens an agent. A narrowing with `accept` behaves as without
    it. The same mode changes nothing. Returns {"agent", "mode", "config_sha256", "accepted", "by" ("code:narrowing",
    "person" or None), "next" (the command, or None)}, with "checkpoints" after an acceptance and "unchanged" true when
    the mode was the one set. Two calls at once, or a call and the terminal, never overlap (_config_lock), and a call
    that finds the file or the accepted hash moved since it began writes nothing and is refused (code 1): code never
    accepts a widening that a stale copy of the file would bring.
    The channel's policy (operations.refusal): from the page a move down is always done and a move up only when the
    page's policy lists the group `set-mode` (refused with code 1, before the lock and any write)."""
    if accept and channel not in ACCEPT_CHANNELS:
        raise core.OpsError("a mode is set and accepted in one step only by the person, in the terminal "
                            "(set-mode --accept); here, set the mode and accept it with accept-config in the terminal", 2)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    if mode not in autonomy.MODES:
        raise core.OpsError(f"a mode is one of {', '.join(autonomy.MODES)}", 2)
    if agent not in cfg["area_agents"]:
        raise core.OpsError(f"{agent!r} is not an agent of area_agents in {cfg['path']}", 2)
    old = cfg["area_agents"][agent]["mode"]
    # The page's brake (decisions M-12, M-13): a move DOWN the order of the modes is never withheld, a move up needs the group
    # `set-mode` in the page's policy. Read before the lock and before any write; the direction is known only here.
    if channel == "page" and old != mode and not autonomy.narrows(old, mode) \
            and not operations.policy_allows("set-mode", channel, cfg["channels"]):
        raise core.OpsError(operations.not_enabled("set-mode", channel), 1)
    with core._config_lock(cfg):
        # Under the lock, the file and the accepted hash are read again: another change (a request at the same time, the
        # terminal) may have finished since context() read them. This call writes the accepted copy plus its one word,
        # so it goes on only when the file is still that accepted copy; else it writes nothing, and the caller asks again.
        fresh = core._config_of(project)
        accepted = core._stored(ctx, ctx["store"].cursor_get, project_config.ACCEPTED)
        if fresh["sha256"] != cfg["sha256"] or accepted != cfg["sha256"]:
            raise core.OpsError("the configuration changed while this call was running: nothing was written; read it, "
                                "and ask again", 1)
        if old == mode:
            return {"agent": agent, "mode": mode, "config_sha256": cfg["sha256"], "accepted": True, "by": None,
                    "next": None, "unchanged": True}
        raw = json.loads(json.dumps(fresh["raw"]))
        raw["area_agents"][agent]["mode"] = mode
        text = json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
        new = hashlib.sha256(text.encode("utf-8")).hexdigest()  # the hash of the exact bytes written, taken before the file is replaced
        temporary = f"{cfg['path']}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, cfg["path"])
        out = {"agent": agent, "mode": mode, "config_sha256": new, "accepted": False, "by": None,
               "next": core._command("accept-config", cfg["project"], sha256=new)}
        narrowing = autonomy.narrows(old, mode)
        if narrowing or accept:
            try:
                written = project_config.load(project)
            except project_config.ConfigError as e:
                raise core.OpsError(str(e), 3) from None
            if written["sha256"] == new:  # nothing else changed the file between the write and this read
                by = "code:narrowing" if narrowing else "person"
                done = _record_acceptance(ctx, written, new, by)
                out.update(accepted=True, by=by, next=None, checkpoints=done["checkpoints"])
            else:  # the file is not the one this call wrote: nothing is accepted, and the hash to read and accept is the file's
                out.update(config_sha256=written["sha256"],
                           next=core._command("accept-config", cfg["project"], sha256=written["sha256"]))
    return out


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
