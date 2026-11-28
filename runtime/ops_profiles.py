#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""An agent's profile in the operations layer: the five operations over the file, the proposal an agent may make, what code adds when
the profile is read, and the block the conversation lane will receive (runtime/profiles.py holds the file and its checks).

A sibling of runtime/ops.py, which exposes `profile_read`, `profile_set`, `profile_propose`, `profile_accept` and `profile_reject` under
their names; no shell imports this file.

  profile          (read, with the terminal, the page and the MCP mode) the state of the file, what code adds (`added`), the open proposal
                   and, for a file that is not there, the template. It writes nothing.
  profile-set / profile-accept / profile-reject   (group `profile-edit`, the terminal and the page only: operations.PROFILE_CHANNELS, by
                   default, and no policy of today widens it; limit L40) the only writers of the file. `profile-set` replaces the whole
                   text; `profile-accept` writes the open proposal of the agent, named by its sha256; `profile-reject` drops it. No model
                   call, an atomic write under the project's write lock and a compare-and-set on the sha256 of the file the person read
                   (`none` for a file that was not there).
  profile-propose  (group `profile-edit` too, the terminal, the page and an MCP client) keeps one proposed text per agent, outside the
                   project, in `<data_dir>/profile-proposals/<agent>.json`; the file of the project is not touched. `propose` is the
                   library call an agent's own turn will use (`by` is `agent:<key>`). The checks run when the text is proposed and again
                   when it is accepted: it reaches the file only through the person's hash.
  lane_block       the block for the conversation lane (library; no caller yet but the tests).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import stat
import sys

import autonomy
import ops_core as core
import operations
import phrases
import plan
import profiles

BASE = re.compile(r"none|[0-9a-f]{64}")
NOT_HERE = "an agent's profile is written from the terminal or from the page, by default, and no channel policy widens it yet (limit L40)"
NO_AGENT = "no area agent is named {agent} in the configuration (area_agents)"
PROPOSERS = ("terminal", "page", "mcp")
STORE_DIR = "profile-proposals"
STORE_KEYS = {"v", "agent", "sha256", "base_sha256", "by", "at", "text"}
STORE_BYTES = 64 * 1024
UNREADABLE = "the stored proposal for {agent} cannot be read: make a new one with profile-propose"
CHANGED = ("{path} changed since you read it (its sha256 is now {now}, not {base}): read it again and repeat the change; nothing was written")


class StaleBase(core.OpsError):
    """The file is not the one whose hash was given (code 1): it changed since it was read."""

    def __init__(self, message: str):
        super().__init__(message, 1)


# --- what code adds ----------------------------------------------------------------------------------------------------------


def _agent(ctx: dict, agent) -> dict:
    """The configured area agents, after checking that `agent` is the key of one and may name a file; OpsError otherwise."""
    try:
        profiles.path_of(agent)
    except ValueError as e:
        raise core.OpsError(str(e), 2) from None
    agents = autonomy.agents(ctx["cfg"]["raw"].get("area_agents"))
    if agent not in agents:
        raise core.OpsError(NO_AGENT.format(agent=agent), 2)
    return agents


def added(ctx: dict, agent: str) -> dict:
    """What code adds to a profile: {"area": None (until the key exists, AC8), "skills": [the skills of the agent's pack], "colleagues":
    [{"agent", "display_name"}] (every other enabled agent, sorted)}. OpsError when the agent is not in area_agents."""
    agents = _agent(ctx, agent)
    try:
        skills = plan.agent_skills(ctx["cfg"], ctx["root"]).get(agent, [])
    except plan.PlanError as e:
        raise core.OpsError(str(e), 3) from None
    colleagues = []
    for other in sorted(agents):
        if other != agent and agents[other]["enabled"]:
            try:
                name = profiles.state(ctx["cfg"]["project"], other)
            except ValueError:
                name = {"problem": True}
            colleagues.append({"agent": other, "display_name": None if name["problem"] else name["display_name"]})
    return {"area": None, "skills": list(skills), "colleagues": colleagues}


def lane_block(project: str, agent: str, nonce=None) -> str:
    """The block of the agent's profile for the conversation lane (profiles.block with what code adds); OpsError (code 3) with the
    sentence when the file fails a check."""
    ctx = core.context(project)
    extra = added(ctx, agent)
    try:
        return profiles.block(ctx["cfg"]["project"], agent, extra, nonce=nonce)
    except profiles.Refused as e:
        raise core.OpsError(str(e), 3) from None


# --- the proposal's store ----------------------------------------------------------------------------------------------------


def _store_path(cfg: dict, agent: str) -> str:
    return os.path.join(cfg["data_dir"], STORE_DIR, f"{agent}.json")


def _kept(cfg: dict, agent: str):
    """None when there is no proposal; the stored object when it reads; {"problem": sentence} when it does not."""
    target = _store_path(cfg, agent)
    if not os.path.lexists(target):
        return None
    bad = {"problem": UNREADABLE.format(agent=agent)}
    try:
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return bad
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return bad
        data = os.read(fd, STORE_BYTES + 1)
    except OSError:
        return bad
    finally:
        os.close(fd)
    try:
        found = json.loads(data.decode("utf-8")) if len(data) <= STORE_BYTES else None
    except ValueError:
        return bad
    if not isinstance(found, dict) or set(found) != STORE_KEYS or found["v"] != 1 or found["agent"] != agent:
        return bad
    if not all(isinstance(found[k], str) for k in STORE_KEYS - {"v"}) or found["sha256"] != profiles.sha256(found["text"].encode("utf-8")):
        return bad
    return found


def _keep(cfg: dict, agent: str, found: dict) -> None:
    """Write the proposal: the folder 0700, a temporary file made new (0600), written, synced and moved over the old one."""
    folder = os.path.join(cfg["data_dir"], STORE_DIR)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    target = _store_path(cfg, agent)
    temporary = f"{target}.{os.getpid()}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(found, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, target)
    except BaseException:
        if os.path.lexists(temporary):
            os.unlink(temporary)
        raise


def _forget(cfg: dict, agent: str, digest: str) -> None:
    """Remove the stored proposal only when it is the one whose hash is `digest`: a newer one, made meanwhile, stays."""
    with core._write_lock(cfg):
        found = _kept(cfg, agent)
        if found is not None and found.get("sha256") == digest:
            try:
                os.unlink(_store_path(cfg, agent))
            except FileNotFoundError:
                pass


# --- the operations ----------------------------------------------------------------------------------------------------------


def profile_read(project: str, agent: str) -> dict:
    """The operation `profile`: profiles.state plus "added", "proposal" (the stored one with its "characters", None, or {"problem"}) and
    "template" (only for a file that is not there)."""
    ctx = core.context(project)
    extra = added(ctx, agent)
    out = profiles.state(ctx["cfg"]["project"], agent)
    kept = _kept(ctx["cfg"], agent)
    if kept is not None and "problem" not in kept:
        kept = dict(kept, characters=profiles.length(kept["text"]))
    out.update({"added": extra, "proposal": kept, "template": None if out["present"] else profiles.template(agent, ctx["cfg"])})
    return out


def _base(value) -> str:
    base = str(value or "").strip().lower()
    if not BASE.fullmatch(base):
        raise core.OpsError("base_sha256 is the sha256 of the file you read, or the word none for a file that was not there", 2)
    return base


def _clean(text) -> str:
    """The text as the file will hold it: line ends \\n, one final newline, nothing else changed; blank gives an empty file."""
    if not isinstance(text, str):
        raise core.OpsError("the text is text", 2)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n" if text.strip() else ""


def _current(project: str, agent: str):
    """The file's bytes now, or None when absent; OpsError (code 1) when it cannot be used."""
    found = profiles.read(project, agent)
    if found["present"] and found["data"] is None:
        raise core.OpsError(found["problem"] or profiles.sentence(agent, "cannot be read"), 1)
    return found["data"] if found["present"] else None


def _write(ctx: dict, agent: str, base: str, text: str) -> dict:
    """The one writer of the file: atomic, under the write lock, compared with the sha256 the person read. Refused: a file that changed,
    a path that is a link or leaves the project, a text that fails a check. The channel is checked by the caller."""
    project = ctx["cfg"]["project"]
    rel = profiles.path_of(agent)
    target = os.path.join(project, *rel.split("/"))
    text = _clean(text)
    why = profiles.check(agent, text)
    if why:
        raise core.OpsError(why, 2)
    with core._write_lock(ctx["cfg"]):
        data = _current(project, agent)
        now = profiles.sha256(data) if data is not None else None
        if (now or "none") != base:
            raise StaleBase(CHANGED.format(path=rel, now=now or "none", base=base))
        linked = profiles.folder_link(project, agent)
        if linked:
            raise core.OpsError(linked, 1)
        folder, root = os.path.dirname(target), os.path.realpath(project)
        nearest = folder
        while not os.path.exists(nearest):
            nearest = os.path.dirname(nearest)
        if not (os.path.realpath(nearest) + os.sep).startswith(root + os.sep) or os.path.islink(target):
            raise core.OpsError(profiles.sentence(agent, "sits in a folder that leaves the project, or is a link"), 1)
        os.makedirs(folder, exist_ok=True)
        out = text.encode("utf-8")
        temporary = f"{target}.{os.getpid()}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(out)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, target)
        except BaseException:
            if os.path.lexists(temporary):
                os.unlink(temporary)
            raise
    return {"agent": agent, "path": rel, "sha256": profiles.sha256(out), "characters": profiles.length(text), "cap": profiles.CAP,
            "written": True}


def _person(channel) -> None:
    if channel not in operations.PROFILE_CHANNELS:
        raise core.OpsError(NOT_HERE, 1)


def profile_set(project: str, agent: str, text: str, base_sha256: str, channel=None) -> dict:
    """The operation `profile-set`: replace the whole text of the agent's profile (an empty text leaves an empty file). Only from the
    terminal and the page; refused when the file is not the one whose hash was given."""
    _person(channel)
    ctx = core.context(project)
    _agent(ctx, agent)
    base = _base(base_sha256)
    return _write(ctx, agent, base, text)


def propose(ctx: dict, agent: str, text: str, base_sha256: str, by: str) -> dict:
    """Keep a proposed text for the agent's profile; the file is not touched. `by` is a channel (terminal, page, mcp) or `agent:<key>`
    of an area agent. Refused: a text that fails a check, a text equal to the file, a base that is not the file's hash now."""
    agents = _agent(ctx, agent)
    if by not in PROPOSERS:
        key = by[len("agent:"):] if isinstance(by, str) and by.startswith("agent:") else None
        if key is None or key not in agents or not profiles.NAME.fullmatch(key):
            raise core.OpsError(f"{by!r} is not a proposer: a channel ({', '.join(PROPOSERS)}) or agent:<key> of an area agent", 2)
    base = _base(base_sha256)
    clean = _clean(text)
    why = profiles.check(agent, clean)
    if why:
        raise core.OpsError(why, 2)
    project = ctx["cfg"]["project"]
    data = _current(project, agent)
    if data is not None and data == clean.encode("utf-8") or (data is None and not clean):
        raise core.OpsError(f"nothing to propose: the text is the profile of {agent} as it is", 2)
    now = profiles.sha256(data) if data is not None else None
    if (now or "none") != base:
        raise StaleBase(CHANGED.format(path=profiles.path_of(agent), now=now or "none", base=base))
    digest = profiles.sha256(clean.encode("utf-8"))
    with core._write_lock(ctx["cfg"]):
        replaced = _kept(ctx["cfg"], agent) is not None
        _keep(ctx["cfg"], agent, {"v": 1, "agent": agent, "sha256": digest, "base_sha256": base, "by": by,
                                  "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "text": clean})
    command = core._command("profile-accept", project, agent=agent, sha256=digest)
    return {"agent": agent, "sha256": digest, "base_sha256": base, "by": by, "replaced": replaced, "command": command,
            "text": phrases.text("PROFILE_PROPOSED", ctx["cfg"]).format(agent=agent) + "\n" + command}


def profile_propose(project: str, agent: str, text: str, base_sha256: str, channel=None) -> dict:
    """The operation `profile-propose`: `propose` for a channel. Nothing is written to the project."""
    by = channel or "terminal"
    if by not in PROPOSERS:
        raise core.OpsError(f"{by!r} is not one of the channels that may propose a profile change: {', '.join(PROPOSERS)}", 1)
    return propose(core.context(project), agent, text, base_sha256, by)


def _open(ctx: dict, agent: str, sha256: str) -> dict:
    """The stored proposal when it reads and `sha256` is its hash; OpsError (code 1) otherwise."""
    _agent(ctx, agent)
    found = _kept(ctx["cfg"], agent)
    if found is None:
        raise core.OpsError(f"there is no proposal for the profile of {agent}", 1)
    if "problem" in found:
        raise core.OpsError(found["problem"], 1)
    if found["sha256"] != str(sha256 or "").strip().lower():
        raise core.OpsError(f"the proposal for {agent} changed since you read it (its sha256 is now {found['sha256']}): read it again; "
                            "nothing was written", 1)
    return found


def profile_accept(project: str, agent: str, sha256: str, channel=None) -> dict:
    """The operation `profile-accept`: write the open proposal of the agent, named by its sha256. Only from the terminal and the page. The
    checks run again; a profile that changed after the proposal was made keeps the proposal and is not overwritten."""
    _person(channel)
    ctx = core.context(project)
    with core._write_lock(ctx["cfg"]):       # one lock around the read of the proposal, the write and the removal: a proposal made meanwhile waits
        found = _open(ctx, agent, sha256)
        try:
            out = _write(ctx, agent, found["base_sha256"], found["text"])
        except StaleBase:
            raise StaleBase(f"the profile of {agent} changed after this proposal was made: read both again; nothing was written and "
                            "the proposal is kept") from None
        _forget(ctx["cfg"], agent, found["sha256"])
    return dict(out, accepted=found["sha256"], by=found["by"])


def profile_reject(project: str, agent: str, sha256: str, channel=None) -> dict:
    """The operation `profile-reject`: drop the open proposal of the agent, named by its sha256. Only from the terminal and the page."""
    _person(channel)
    ctx = core.context(project)
    with core._write_lock(ctx["cfg"]):
        found = _open(ctx, agent, sha256)
        _forget(ctx["cfg"], agent, found["sha256"])
    return {"agent": agent, "rejected": found["sha256"]}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
