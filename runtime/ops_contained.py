#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The contained run (stage 7): one run of one skill of an area agent's pack, in the eval container, for a caller that is not a task (a
handler's agent run). A sibling of runtime/ops.py, which exposes `contained_run` under its name; the code moved here from ops.py with no
change of logic (package INSTRUCTIONS, to keep ops.py within its size budget). The pieces of a run it uses (`_budget`,
`_key_in_environment`, `_note`) are read as `ops_runs.<name>` (runtime/ops_runs.py), and the routing of a run is `ops_models.route`; this file
imports neither runtime/ops.py nor, at call time, any helper of it. contracts/runtime.md, "The contained run", is the contract.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys

import ops_core as core
import ops_instructions
import ops_models
import ops_runs
import lab
import manifest
import plan
import skill_meta
import workcopy



SKILL_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def _contained_scope(ctx: dict, skill: str) -> None:
    """Refuse a skill that is not a folder of the checkout's skills/, that the runtime knows nothing of (no whole runtime
    manifest), or that is in the pack of no enabled area agent of the configuration (a check of scope, not of mode). A
    configuration with no area agents puts no skill in scope: nothing is allowed unless a pack says so."""
    if not isinstance(skill, str) or not SKILL_NAME.fullmatch(skill) or \
            not os.path.isfile(os.path.join(core.ROOT, "skills", skill, "SKILL.md")):
        raise core.OpsError(f"{skill!r} is not a skill of this checkout", 2)
    try:
        packs = plan.agent_skills(ctx["cfg"], core.ROOT)
    except plan.PlanError as e:
        raise core.OpsError(str(e), 2) from None
    if not any(skill in names for names in packs.values()):
        raise core.OpsError(f"{skill} is in the pack of no enabled area agent of {ctx['cfg']['path']}: a contained run is "
                       "made only for a skill of an area agent's pack", 2)
    try:
        manifest.load(core.ROOT, skill)  # a skill the runtime knows nothing of does not run, here as in a task
    except manifest.ManifestError as e:
        raise core.OpsError(str(e), 2) from None


def _contained_folder(cfg: dict) -> tuple:
    """(n, folder): a new folder <data_dir>/contained-runs/<n>, claimed by creating it, so that two runs never share one."""
    base = os.path.join(cfg["data_dir"], core.CONTAINED_DIR)
    os.makedirs(base, mode=0o700, exist_ok=True)
    n = 1 + max([int(name) for name in os.listdir(base) if name.isdigit()] or [0])
    while True:
        folder = os.path.join(base, str(n))
        try:
            os.mkdir(folder, 0o700)
        except FileExistsError:
            n += 1
            continue
        return n, folder


def routed(ctx: dict, skill: str) -> tuple:
    """(meta, keys, routing) of a contained run of the skill: the model and the adapter come from the choice (ops_models.route: the
    project's default_model, else `auto`, with the keys as run_next passes them), never from what a caller asks. OpsError when the
    skill cannot be routed (3 for the lab's refusals and for a model with no key, else 1). Shared by `contained_run` and `ask`."""
    try:
        meta = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))
        keys = core._keys()
        routing = ops_models.route(ctx, skill, meta, keys)
        if routing["key_missing"]:
            raise core.OpsError(f"no key was found for {routing['model']}: {keys[routing['model']]['reason']}", 3)
    except (skill_meta.SkillError, lab.LabError, KeyError, ValueError, OSError) as e:
        raise core.OpsError(f"{skill} could not be routed: {e}", 3 if isinstance(e, lab.LabError) else 1) from None
    return meta, keys, routing


def execute(ctx: dict, skill: str, meta: dict, keys, routing: dict, prompt: str, *, platforms=(), timeout=None, dest: str,
            prepared_dir: str, max_cost, sourced=(), around=None, open_web: bool = False) -> dict:
    """The one run both callers make: the copy that holds the artifacts the skill declares (and, for `ask`, `sourced`: the copies of
    the sources code selected, [(path, relative path)] already written under `prepared_dir`), then one attempt in the facade's session,
    never on the open network, within `timeout` seconds, in the claimed folder `dest`. Returns lab.run_skill's result. The caller
    owns `prepared_dir` and removes it (`ask` still reads the copies after the run). `around` is a context manager that is entered inside
    the lab's session (`ask` gives the watcher that ends the run when its request is cancelled). `open_web` (slice R2-F1, the web research of
    runtime/ops_research.py) is the one other mode: the run is on the open network, the adapter's --allow-web, and NO file of the project enters the
    copy (a run that can reach the whole web sees none of the project's: not the state file, not an earlier brief); the caller has checked that the
    routed pair was measured with the web (routing["web"]). A LabError is OpsError 3 with its reason and the empty folder claimed for the run goes."""
    cfg = ctx["cfg"]
    if open_web:
        entered = {"files": []}      # nothing of the project enters a run on the open network (R2-F1)
    else:
        try:
            # web=True here is the copy's form, "the artifacts the skill declares" (L3); the run itself is web=False below.
            entered = workcopy.entering(cfg["project"], meta, web=True, cfg=cfg, settings_names=lab.settings_names(),
                                        prepared_dir=prepared_dir, sourced=sourced)
        except workcopy.CopyError as e:
            raise core.OpsError(f"the copy could not be built: {e}", 1) from None
    try:
        with core._LAB_GUARD, lab.session(), ops_runs._key_in_environment(routing, keys), around or contextlib.nullcontext():  # the lab's process-wide session: one at a time
            return lab.run_skill(skill, prompt, entered["files"], dest, web=bool(open_web), model=routing["model"],
                                 timeout=timeout, retries=0, platforms=list(platforms or ()), max_cost=max_cost)
    except lab.LabError as e:
        with contextlib.suppress(OSError):
            os.rmdir(dest)  # no run was made: the folder claimed for it is empty, and goes
        refused = core.OpsError(f"{e.kind}: {e.reason}", 3)
        refused.lab_kind = e.kind      # which kind of lab failure: read by ops_research and ops_ask to say "the environment is off" for `docker`
        raise refused from None


def contained_run(project: str, skill: str, prompt: str, out_dir: str, platforms=(), timeout=None) -> dict:
    """Run one skill once on one task text, in the eval container, for a caller that is not a task (a handler's agent run).

    1. The configuration's hash is the accepted one (context). The skill is a folder of this checkout's skills/, has a
       whole runtime manifest and is in the pack of an enabled area agent of the configuration: else OpsError 2.
    2. The model and the adapter come from the choice (ops_models.route: the project's default_model, else `auto`, with the
       keys as run_next passes them), never from what a handler asks: a skill that is not proven on the model runs supervised.
    3. What enters the copy is the artifacts the skill declares and nothing else (workcopy.entering in its form for a
       run that sees only declared artifacts, limit L3); the runtime's configuration is never in it, although a skill
       may declare it as an input. Nothing is added: no file drop, no AGENTS.md the skill does not declare.
    4. The run is one attempt (retries 0), in the facade's session, never on the open network (web False, whatever the
       skill requires), within `timeout` seconds (None: the gate file's), in a new folder <data_dir>/contained-runs/<n>.
       `platforms` names the platforms whose reference the run is given besides the ones the skill cites.
    5. Nothing is brought back: no file the run created or changed reaches the project; their number is
       `ignored_changes`.
    6. The reply leaves through the credential scan of limit L14 (workcopy.masked_reply) and is written to
       <out_dir>/response.md, as the scan leaves it; <out_dir>/timing.json holds total_tokens, duration_ms, exit_code (0
       when the model answered, else 1) and cost_usd, which is null unless the credential of the run is metered (a
       run on a subscription or a free credential has no billed cost). Those two files are all that is written outside the run folder.
    7. Returns {"status": "ok" | "failed", "failure": None | {"kind", "reason"}, "model", "adapter",
       "ignored_changes", "run_dir"}.

    A LabError (no image on this machine, a configuration the lab refuses, a platform with no reference) is OpsError 3
    with its reason: the eval image is never built here."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise core.OpsError("the prompt is empty", 2)
    if isinstance(platforms, str) or not all(isinstance(n, str) for n in platforms or ()):
        raise core.OpsError("platforms is a list of platform names", 2)
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0):
        raise core.OpsError("timeout is a number of seconds above 0", 2)
    ctx = core.context(project)
    cfg = ctx["cfg"]
    _contained_scope(ctx, skill)
    prompt = ops_instructions.contained_prompt(cfg["project"], prompt)   # the person's standing instructions, appended after the caller's text
    out_dir = os.path.abspath(out_dir)
    meta, keys, routing = routed(ctx, skill)
    number, dest = _contained_folder(cfg)
    prepared_dir = os.path.join(cfg["data_dir"], core.PREPARED_DIR, f"contained-{number}")
    try:
        result = execute(ctx, skill, meta, keys, routing, prompt, platforms=platforms, timeout=timeout, dest=dest,
                         prepared_dir=prepared_dir, max_cost=ops_runs._budget(ctx, None, routing, keys))
    finally:
        shutil.rmtree(prepared_dir, ignore_errors=True)
    changes = result["changes"] or {}
    ignored = len(changes.get("created") or []) + len(changes.get("modified") or [])
    answered = result["status"] == "ok"
    body, _masked = workcopy.masked_reply(result["response"])
    timing = result["timing"] if isinstance(result["timing"], dict) else {}
    number_of = lambda name: timing.get(name) if isinstance(timing.get(name), int) and not isinstance(timing.get(name), bool) \
        and timing.get(name) >= 0 else None
    cost = timing.get("cost_usd")
    cost = cost if routing["billing"] == "metered" and isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0 else None
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "response.md"), "w", encoding="utf-8", newline="") as f:
            f.write(body)
        with open(os.path.join(out_dir, "timing.json"), "w", encoding="utf-8") as f:
            json.dump({"total_tokens": number_of("total_tokens"), "duration_ms": number_of("duration_ms"),
                       "exit_code": 0 if answered else 1, "cost_usd": cost}, f)
            f.write("\n")
    except OSError as e:
        raise core.OpsError(f"the reply could not be written to {out_dir}: {e.strerror}", 1) from None
    failure = result["failure"]
    return {"status": result["status"], "failure": None if failure is None else
            {"kind": failure["kind"], "reason": ops_runs._note(failure["reason"])},
            "model": result["model"], "adapter": result["adapter"],
            "ignored_changes": ignored, "run_dir": dest}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
