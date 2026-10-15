#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The configuration's acceptance in the operations layer: who may accept a change of docs/workbench/runtime.json, and
the three operations that change or accept it.

A change of the configuration takes effect only when its hash is the accepted one (contracts/runtime.md, "The
configuration, and who may accept a change of it"). The accepted hash has one writer, `_record_acceptance`, and three
paths reach it, each under the configuration lock (ops_core._config_lock):

  accept_config   the person, in the terminal, who typed the hash after reading the file: `by: "person"`
  set_mode        a move down the order of the modes (code, because it widens nothing): `by: "code:narrowing"`
  set_mode --accept   a move up the order, set and accepted in one step by the person, in the terminal only
                  (ACCEPT_CHANNELS): `by: "person"`, and only when the file was the accepted one before the call, so
                  the one difference this accepts is the mode the command names. A configuration with any other
                  unaccepted change is refused and nothing is written: the person reads the file and runs accept-config.
  give_consent    the consent of one agent given on the page (`by: "person:page"`), on the same condition: the file was the
                  accepted one, and the hash the page read is that file's.
  set_model       the model an agent is fixed to (or `auto`, or the project's default again). Fixing a model on an
                  agent in an autonomous mode, or raising an agent with a model fixed to one, is the person's consent
                  (decisions D34 and D38): it shows autonomy.CONSENT_WARNING and is given with `consent`, a flag of its
                  own, distinct from `accept` (which accepts the hash), in the terminal; the consent is stored with
                  the agent and names the model and the mode, so changing either asks again. A move DOWN the order of
                  the modes is never withheld and never asks.
  give_consent    the same consent, given on the page: the page sends the model, the mode, the hash of the configuration
                  it read and the hash of the warning it showed; the call checks all four, writes the model and the
                  consent of that one agent and accepts that one change (`by: "person:page"`). A messaging channel and
                  the MCP mode have neither operation: they can never consent.

Functions:
  _record_acceptance(ctx, cfg, sha256, by)   record the accepted hash, who accepted it, and the state file's Checkpoints line
  write_checkpoints(cfg)                    the state file's "- Checkpoints:" line rewritten from the area agents
  accept_config(project, sha256)            the person accepts a hash
  set_mode(project, agent, mode[, accept, channel, consent])   set one area agent's autonomy mode
  set_model(project, agent, model[, accept, channel, consent])  fix one area agent's model, and record the consent that needs
  give_consent(project, agent, model, mode, config_sha256, warning_sha256[, channel])  the page's consent

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
import ops_models
import lab
import path_rule
import project_config
import sources
import state_merge

ACCEPTED_BY = "config:accepted-by"  # the store's cursor that says who accepted the hash in ACCEPTED: "person" or "code:narrowing"
ACCEPT_CHANNELS = ("terminal",)     # the only channel that may pass `accept` to set_mode: the person, in the terminal
CONSENT_CHANNELS = ("terminal",)    # the only channel that may pass `consent` to set_mode and set_model; the page has give_consent
PAGE_CONSENT_BY = "person:page"     # the store's record of who accepted the hash a page's consent made


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
    try:
        try:
            evidence = lab.local_evidence_base()
        except lab.LabError:
            evidence = None  # a checkout without its lab runs nothing: every later use of the folder asks again and needs the lab
        sources.ready_for_acceptance(cfg, evidence)  # limit L21: the sources folder is dedicated, 0700, marked
    except sources.SourcesError as e:
        raise core.OpsError(f"the configuration was not accepted: the sources folder is refused ({e})", 1) from None
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


def _consent_refusal(project: str, agent: str, what: str, **command) -> "core.OpsError":
    """The refusal of a change that needs the person's consent and was not given it: the warning, once (autonomy.CONSENT_WARNING),
    and the one command that gives the consent, in the terminal, with `--consent` (the consent) and `--accept` (the hash, in
    the same step); the page draws the command with Copy and builds none, and gives the consent itself with give_consent."""
    return core.OpsError(f"{what} {autonomy.CONSENT_WARNING} To consent, run this command in the terminal: "
                         f"{core._command(command.pop('verb'), project, agent=agent, consent=True, accept=True, **command)}", 2)


def _change_agent(ctx: dict, cfg: dict, project: str, agent: str, edit, unchanged: bool, narrowing: bool, accept: bool,
                  answer: dict, person: str = "person") -> dict:
    """The locked step the two operations share. Under the configuration lock the file and the accepted hash are read again:
    another change (a request at the same time, the terminal) may have finished since context() read them. The call writes
    the accepted copy plus the edit of one agent's entry, so it goes on only when the file is still that accepted copy; else
    it writes nothing, and the caller asks again. `edit(entry)` changes the agent's entry in the copy to be written;
    `unchanged` says the entry already holds what the call asks (nothing is written); `narrowing` says the change widens
    nothing (code accepts the new hash); `accept` is the person's, in the terminal. Returns `answer` with config_sha256,
    accepted, by, next, and checkpoints after an acceptance."""
    with core._config_lock(cfg):
        fresh = core._config_of(project)
        accepted = core._stored(ctx, ctx["store"].cursor_get, project_config.ACCEPTED)
        if fresh["sha256"] != cfg["sha256"] or accepted != cfg["sha256"]:
            raise core.OpsError("the configuration changed while this call was running: nothing was written; read it, "
                                "and ask again", 1)
        if unchanged:
            return {**answer, "config_sha256": cfg["sha256"], "accepted": True, "by": None, "next": None, "unchanged": True}
        raw = json.loads(json.dumps(fresh["raw"]))
        edit(raw["area_agents"][agent])
        text = json.dumps(raw, indent=2, ensure_ascii=False) + "\n"
        new = hashlib.sha256(text.encode("utf-8")).hexdigest()  # the hash of the exact bytes written, taken before the file is replaced
        temporary = f"{cfg['path']}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, cfg["path"])
        out = {**answer, "config_sha256": new, "accepted": False, "by": None,
               "next": core._command("accept-config", cfg["project"], sha256=new)}
        if narrowing or accept:
            try:
                written = project_config.load(project)
            except project_config.ConfigError as e:
                raise core.OpsError(str(e), 3) from None
            if written["sha256"] == new:  # nothing else changed the file between the write and this read
                by = "code:narrowing" if narrowing else person
                done = _record_acceptance(ctx, written, new, by)
                out.update(accepted=True, by=by, next=None, checkpoints=done["checkpoints"])
            else:  # the file is not the one this call wrote: nothing is accepted, and the hash to read and accept is the file's
                out.update(config_sha256=written["sha256"],
                           next=core._command("accept-config", cfg["project"], sha256=written["sha256"]))
    return out


def set_mode(project: str, agent: str, mode: str, accept: bool = False, channel=None, consent: bool = False) -> dict:
    """Set one area agent's autonomy mode: only area_agents.<agent>.mode of runtime.json changes, and the consent stored with
    the agent (decision P1: the mode is the configuration's word). A move down the order of the modes (autonomy.MODES:
    stopped < supervised < milestones < autonomous < autonomous-with-policy) widens nothing, so code accepts the new hash at
    once, as the acceptance accept-config writes, recorded `code:narrowing`, and no operation refuses afterwards. A move up
    leaves the hash unaccepted: every operation then refuses until the person accepts it (accept-config), and `next` is the
    command, unless the person passes `accept` in the terminal: then the hash is accepted in the same locked step,
    recorded `person`, on one condition checked under the lock, that the configuration was the accepted one before
    this change (so the only difference accepted is this mode). Any other state (another unaccepted change, a file that
    moved since the call began) is refused and nothing is written: the person reads the file and runs accept-config.
    `accept` is refused (code 2, before anything is read) from any channel but ACCEPT_CHANNELS: the local page, the
    conversation and the MCP mode can never accept what widens an agent. A narrowing with `accept` behaves as without
    it. The same mode changes nothing.
    A mode that releases reviews without the person (autonomy.CONSENT_MODES) on an agent fixed to a model (decision D38)
    needs the person's consent, given by `consent`, a flag of its own (not `accept`, which accepts the hash) and the
    terminal's alone (CONSENT_CHANNELS, code 2 from any other channel), after the warning (autonomy.CONSENT_WARNING): without
    it a move up or the same mode is refused (code 2) with the warning and the command, and nothing is written. With it, the
    consent is stored with the agent, names the model and the mode, and the answer carries the warning ("warning"), which
    the terminal prints. A move DOWN is never withheld and never asks: from one consent mode to the other (autonomous-with-policy
    to autonomous) a valid consent for the higher mode is carried to the lower one; to any other mode it is dropped.
    An agent with no model fixed stores none, and a consent that no longer names the agent's model and mode is removed.
    Returns {"agent", "mode", "consent" ({"model", "mode"} as stored, or None), "config_sha256", "accepted", "by"
    ("code:narrowing", "person" or None), "next" (the command, or None)}, with "checkpoints" after an acceptance, "warning"
    when this call gave the consent and "unchanged" true when the mode was the one set. Two calls at once, or a
    call and the terminal, never overlap (_config_lock), and a call that finds the file or the accepted hash moved since it
    began writes nothing and is refused (code 1): code never accepts a widening that a stale copy of the file would bring.
    The channel's policy (operations.refusal): from the page a move down is always done and a move up only when the
    page's policy lists the group `set-mode` (refused with code 1, before the lock and any write)."""
    if accept and channel not in ACCEPT_CHANNELS:
        raise core.OpsError("a mode is set and accepted in one step only by the person, in the terminal "
                            "(set-mode --accept); here, set the mode and accept it with accept-config in the terminal", 2)
    if consent and channel not in CONSENT_CHANNELS:
        raise core.OpsError("the consent that a mode releasing reviews needs is given by the person, in the terminal "
                            "(set-mode --consent); on the page it is given with the model (give-consent)", 2)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    if mode not in autonomy.MODES:
        raise core.OpsError(f"a mode is one of {', '.join(autonomy.MODES)}", 2)
    if agent not in cfg["area_agents"]:
        raise core.OpsError(f"{agent!r} is not an agent of area_agents in {cfg['path']}", 2)
    entry = cfg["area_agents"][agent]
    old = entry["mode"]
    # The page's brake (decisions M-12, M-13): a move DOWN the order of the modes is never withheld, a move up needs the group
    # `set-mode` in the page's policy. Read before the lock and before any write; the direction is known only here.
    if channel == "page" and old != mode and not autonomy.narrows(old, mode) \
            and not operations.policy_allows("set-mode", channel, cfg["channels"]):
        raise core.OpsError(operations.not_enabled("set-mode", channel), 1)
    after = {**entry, "mode": mode}
    needs = autonomy.consent_needed(after)
    down = old != mode and autonomy.narrows(old, mode)
    valid_before = autonomy.consent_valid(entry, entry.get("model"))  # the consent in force for the mode the agent is in now
    asked = False
    if needs and down:
        # A move down is never withheld and never asks: the consent for the higher consent mode follows to the lower one.
        carried = valid_before
    elif needs:
        carried = autonomy.consent_valid({**after, "consent": entry.get("consent")}, after["model"])
        if not carried and not consent:
            raise _consent_refusal(project, agent, f"{agent} is fixed to the model {after['model']}, and {mode} releases its "
                                   "reviews without you.", verb="set-mode", mode=mode)
        asked = not carried
    else:
        carried = False
    target = {"model": after["model"], "mode": mode} if needs and (carried or asked) else None

    def edit(raw_entry):
        raw_entry["mode"] = mode
        if target is not None:
            raw_entry["consent"] = dict(target)
        else:
            raw_entry.pop("consent", None)

    answer = {"agent": agent, "mode": mode, "consent": target}
    if asked:
        answer["warning"] = autonomy.CONSENT_WARNING
    return _change_agent(ctx, cfg, project, agent, edit, old == mode and entry.get("consent") == target, down, accept, answer)


def set_model(project: str, agent: str, model: str, accept: bool = False, channel=None, consent: bool = False) -> dict:
    """Fix one area agent to a model: only area_agents.<agent>.model of runtime.json changes, and the consent stored with the
    agent. model is a model id of the gate file (an alias is written as its id), "auto" (the agent's tasks are routed by the
    evidence and the price) or "default" (the agent keeps no model of its own: the request's, else the project's default_model
    or auto, decides).
    Fixing a model on an agent in an autonomous mode (autonomy.CONSENT_MODES) is the person's consent (decisions D34 and
    D38): the reviews of that agent's runs on a model with no reliable evidence are released by the mode, and each such run is
    recorded as autonomy by consent. It is given with `consent`, a flag of its own and distinct from `accept` (which accepts
    the hash), after the warning (autonomy.CONSENT_WARNING), in the terminal only (CONSENT_CHANNELS, code 2 from any other
    channel; the page gives it with give_consent); without it the call is refused (code 2) with the warning and the command,
    and nothing is written; with it the answer carries the warning ("warning"), which the terminal prints. The consent is
    stored with the agent and names the model and the mode: changing either asks again, and a consent that no longer names
    the agent's model and mode is removed. Like set_mode, a change that fixes a model leaves the hash unaccepted until the
    person accepts it (accept-config, or `accept` here in the terminal, on the same condition as set_mode); going back to
    the default widens nothing and is accepted by code.
    Returns {"agent", "model" (the id, "auto" or None), "consent" (what is stored: {"model", "mode"} or None),
    "config_sha256", "accepted", "by", "next"}, with "warning" when this call gave the consent and "unchanged" true when
    nothing changes."""
    if accept and channel not in ACCEPT_CHANNELS:
        raise core.OpsError("a model is fixed and accepted in one step only by the person, in the terminal "
                            "(set-model --accept); here, fix the model and accept it with accept-config in the terminal", 2)
    if consent and channel not in CONSENT_CHANNELS:
        raise core.OpsError("the consent that a model on an autonomous agent needs is given by the person, in the terminal "
                            "(set-model --consent); on the page, with give-consent", 2)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    if agent not in cfg["area_agents"]:
        raise core.OpsError(f"{agent!r} is not an agent of area_agents in {cfg['path']}", 2)
    if not isinstance(model, str) or not model.strip():
        raise core.OpsError("model is a model id of the gate file, \"auto\", or \"default\"", 2)
    word = None if model == "default" else ops_models.check_word(model)
    # The page's policy: from the page, fixing a model needs the group `set-mode` (going back to the default or to auto never
    # does: it widens nothing). Read before the lock and before any write.
    if channel == "page" and word not in (None, autonomy.AUTO_MODEL) and not operations.policy_allows("set-model", channel, cfg["channels"]):
        raise core.OpsError(operations.not_enabled("set-model", channel), 1)
    entry = cfg["area_agents"][agent]
    after = {**entry}
    after.pop("model", None)
    if word is not None:
        after["model"] = word
    needs = autonomy.consent_needed(after)
    valid = needs and autonomy.consent_valid({**after, "consent": entry.get("consent")}, after["model"])
    if needs and not valid and not consent:
        raise _consent_refusal(project, agent, f"{agent} is in {entry['mode']} mode, and fixing {word} on it means its reviews are "
                               "released without you.", verb="set-model", model=word)

    def edit(raw_entry):
        if word is None:
            raw_entry.pop("model", None)
        else:
            raw_entry["model"] = word
        if needs:
            raw_entry["consent"] = {"model": word, "mode": entry["mode"]}
        else:
            raw_entry.pop("consent", None)

    stored = {"model": word, "mode": entry["mode"]} if needs else None
    unchanged = entry.get("model") == word and entry.get("consent") == stored
    answer = {"agent": agent, "model": word, "consent": stored}
    if needs and not valid:
        answer["warning"] = autonomy.CONSENT_WARNING
    return _change_agent(ctx, cfg, project, agent, edit, unchanged, word in (None, autonomy.AUTO_MODEL), accept, answer)


def give_consent(project: str, agent: str, model: str, mode: str, config_sha256: str, warning_sha256: str,
                 channel=None) -> dict:
    """The person's consent, given on the page (decision D38: on the page or in the terminal). The page shows the warning
    (autonomy.CONSENT_WARNING) and an explicit button; it sends the model, the mode, the hash of the configuration it read and
    the sha256 of the warning text it showed. The call writes the model and the consent of that one agent, accepts that one
    change (`by: "person:page"`), and nothing else, on these conditions, each refused with nothing written:
    the channel is the page (code 2: the terminal has `set-model --consent`; messaging and the MCP mode have no such operation);
    the page's policy lists the group `set-mode` (code 1); the warning's hash is the sha256 of the text this service holds
    (code 2: the page did not show the exact text); the model is a model id of the gate file, not `auto` or `default`
    (code 2: they need no consent); the agent exists and its mode is `mode`, one of autonomy.CONSENT_MODES (code 2: the
    consent names the mode the agent is in); config_sha256 is the hash of the configuration as it is now, and that hash is
    the accepted one (code 1 when the file moved since the page read it; code 3 when the configuration was not accepted:
    nothing is accepted here but this consent). Returns {"agent", "model", "mode", "consent" ({"model", "mode"}), "warning",
    "config_sha256", "accepted", "by" ("person:page"), "next"}, with "unchanged" true when that consent is already stored."""
    if channel != "page":
        raise core.OpsError("this consent is given on the page; in the terminal use set-model --consent (set-mode --consent for a "
                            "mode), and messaging and the MCP mode can never give it", 2)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    if not operations.policy_allows("give-consent", channel, cfg["channels"]):
        raise core.OpsError(operations.not_enabled("give-consent", channel), 1)
    if warning_sha256 != autonomy.CONSENT_WARNING_SHA256:
        raise core.OpsError("the warning the page showed is not the text this service holds: nothing was written; reload the page "
                            "and read the warning again", 2)
    if agent not in cfg["area_agents"]:
        raise core.OpsError(f"{agent!r} is not an agent of area_agents in {cfg['path']}", 2)
    word = ops_models.check_word(model) if isinstance(model, str) else None
    if word in (None, autonomy.AUTO_MODEL) or model == "default":
        raise core.OpsError("a consent names a model id of the gate file; auto and default need none", 2)
    entry = cfg["area_agents"][agent]
    if mode not in autonomy.CONSENT_MODES or entry["mode"] != mode:
        raise core.OpsError(f"{agent} is in {entry['mode']} mode now and the consent names {mode!r}: a consent names the mode the "
                            f"agent is in, one of {', '.join(autonomy.CONSENT_MODES)}; nothing was written", 2)
    if config_sha256 != cfg["sha256"]:
        raise core.OpsError("the configuration changed since the page read it: nothing was written; reload the page", 1)
    stored = {"model": word, "mode": mode}

    def edit(raw_entry):
        raw_entry["model"] = word
        raw_entry["consent"] = dict(stored)

    out = _change_agent(ctx, cfg, project, agent, edit, entry.get("model") == word and entry.get("consent") == stored, False,
                        True, {"agent": agent, "model": word, "mode": mode, "consent": stored,
                               "warning": autonomy.CONSENT_WARNING}, person=PAGE_CONSENT_BY)
    return out


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
