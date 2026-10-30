#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The start and the body of a task run, and the gate where a run's effect becomes a pending approval (44-C4a).

A sibling of runtime/ops.py, which re-exports the names under their own for the shells and the tests; no shell imports this file. The
names every module of the layer shares are read as `core.<name>` (runtime/ops_core.py). What a run takes in and gives back (`_budget`)
and the use it records (`_use_start`) are read as `ops_runs.<name>`, the routing of the run as `ops_models.route`, the stop request of a
run as `ops_cancel.<name>`. `ops_runs.run_task` and `ops_runs._start` reach `_run_body`, `_prepare_run`, `_run_start` and
`PREPARE_ERRORS` at call time, through `ops_runs._task_run_module()`, because this file imports `ops_runs` (the pieces of a run) and
`ops_runs` must not import it back.

A run starts in two parts. `PREPARE_ERRORS` names what can go wrong before a run has its row; `_prepare_run` is the slow part, made
before the claim lock (the skill's meta and manifest, the routing, the skill's identity, the person's standing instructions), and
`_run_start` is the part under the claim lock (the spend limit and the run row). `_run_body` is the run itself: the copy that enters
by limits L1 to L6, the lab, the return of what the run left under the write lock (limits L7, L8, L10, L12 of runtime/workcopy.py),
with the stop request read first under that lock (L41), the change set the run made (`_changeset_of`, `_code_state`: L9, L11), the
dependency sets, and the pending decision. The gate is principle 11: `_gate_payload` recovers the payload the skill showed
(`effects.recover_payload`, limit L16) and keeps it as `payload.md`, and `_effect_or_review` opens an `effect` whose `payload_sha256`
is the hash of the effect document `effect.json` it wrote (limits L15 and L17), or a `review` with its reason; a run executes
nothing and changes nothing outside its copy. Approving an effect and executing it stay in runtime/ops.py (`approve`,
`_approve_effect`, `_execute_effect`): they read the hash this file stores and are not moved.

These bodies moved from runtime/ops.py with no change of logic; the one line that differs is the route of `_prepare_run`, which
calls `ops_models.route` where ops.py called its `_route`, the same call.

Standard library only. Runs on Python 3.9: python3 runtime/ops_task_run.py --help
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import traceback

import ops_core as core
import ops_cancel
import ops_instructions
import ops_language
import ops_models
import ops_runs
import ops_sources
import changeset
import deps as deps_sets  # the name ops.py gives it: its operation `deps` would hide the module; the bodies read it so
import documents
import drop
import effects
import endings
import lab
import manifest
import path_rule
import skill_meta
import sources
import workcopy


# --- a file read as text (the same lines as the _read of ops.py and ops_config.py; 44-C4a) ---------------------------------------


def _read(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


# --- the start and the body of a run (moved from runtime/ops.py by 44-C4a, no change of logic) -----------------------------------


MANDATORY_LINE = ("This delivery is a mandatory milestone: the next task accepts it only with your approval written in "
                  "the document. Write it there, then release.")


# What can go wrong before a run has its row: a skill the runtime knows nothing of, a lab that refuses, a store that does.
PREPARE_ERRORS = (skill_meta.SkillError, manifest.ManifestError, lab.LabError, core.OpsError, OSError, KeyError)


def _prepare_run(ctx: dict, task: dict, requested, keys) -> dict:
    """The slow part of a run's start, made before the claim lock: the skill's meta and manifest (a skill the runtime knows
    nothing of does not run), the routing (ops_models.route with the keys core._keys found, which the caller read from the
    secret store) and the skill's identity. A model with no key is a refusal: the run does not start."""
    skill = task["skill"]
    meta = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))
    known = manifest.load(core.ROOT, skill)
    routing = ops_models.route(ctx, skill, meta, keys, task, requested)
    if routing["key_missing"]:
        raise core.OpsError(f"no key was found for {routing['model']}: {keys[routing['model']]['reason']}", 3)
    return {"meta": meta, "known": known, "keys": keys, "routing": routing, "identity": lab.skill_identity(skill),
            "instructions": ops_instructions.guard(ctx, task)}   # the person's standing instructions, read once; a file that fails a check stops the run


def _run_start(ctx: dict, task: dict, prepared: dict) -> dict:
    """The run's start, under the claim lock: its spend limit (before the run's own row: its reservation is not in the
    day's spend yet) and the run row. Returns what _run_body takes."""
    routing, identity = prepared["routing"], prepared["identity"]
    budget = ops_runs._budget(ctx, task.get("agent"), routing, prepared["keys"])
    run_id = core._stored(ctx, ctx["store"].task_run_start, task["id"], skill=task["skill"], model=routing["model"],
                          adapter=routing["adapter"], skill_version=identity["version"],
                          skill_sha256=identity["content_sha256"], web=routing["web"],
                          billing=routing["billing"] or "unknown", autonomy=routing["autonomy"])["run_id"]
    return {**prepared, "task": task, "budget": budget, "run_id": run_id}


def _run_body(ctx: dict, started: dict) -> dict:
    """The run itself, after its row was opened (_run_start): the copy, the lab, the return of what the run left, the
    pending decision. The return into the project's files is made under the write lock."""
    cfg, store, task = ctx["cfg"], ctx["store"], started["task"]
    skill, meta, known, keys = task["skill"], started["meta"], started["known"], started["keys"]
    routing, budget, run_id = started["routing"], started["budget"], started["run_id"]
    dest = os.path.join(cfg["data_dir"], core.RUNS_DIR, str(run_id))
    out = {"ran": task["id"], "skill": skill, "run_id": run_id, "run_dir": dest, "status": "failed", "ending": None,
           "failure": None, "task_state": "failed", "pending_id": None, "returned": [], "kept": [], "left_out": [],
           "entered": None, "state": None, "routing": routing, "use": None}

    def fail(kind: str, reason: str, attempts: int = 0, digest=None, redactions=None, reported=None) -> dict:
        done = core._stored(ctx, store.task_run_finish, run_id, status="failed", failure=kind, task_state="failed",
                attempts=attempts, image_digest=digest, run_dir=dest, error=ops_runs._note(reason), task_note=ops_runs._note(reason),
                redactions=redactions, **ops_runs._reported_usage(reported, routing))
        out["failure"] = None if ops_cancel.cancelled_run(out, done) else {"kind": kind, "reason": ops_runs._note(reason)}   # a stopped run is cancelled whatever it found (R18)
        return out

    out["use"] = ops_runs._use_start(ctx, run_id, skill, routing)  # one use per run, also for a run made after an answer
    # Outside the run folder: the facade sets aside whatever it finds there.
    prepared_dir = os.path.join(cfg["data_dir"], core.PREPARED_DIR, str(run_id))
    try:
        handed = drop.files(cfg["project"], task["id"])
        refused = []
        if handed and routing["web"] and not drop.WEB_TASK_TAKES_DROP:
            refused = [{"path": rel, "reason": drop.WEB_REFUSAL} for _source, rel in handed]
            handed = []
        try:   # decision D29: the newest version of each source the plan chose, as of this start; the rows say which
            sourced = ops_sources.copies_for(ctx, task, prepared_dir, started.get("unattended", True))
        except ops_sources.SourcesRefused as e:
            return fail("internal", str(e))
        try:
            entered = workcopy.entering(cfg["project"], meta, web=routing["web"], cfg=cfg,
                                        settings_names=lab.settings_names(), prepared_dir=prepared_dir, handed=handed,
                                        sourced=sourced["files"])
        except workcopy.CopyError as e:
            return fail("internal", f"the copy could not be built: {e}")
        ops_sources.record_copies(ctx, run_id, task, sourced["records"])   # only the copies the run received (entering() took them all)
        if sourced["records"]:   # a task with no source returns what it always returned
            out["sources"] = [{k: r[k] for k in ("source", "version", "sha256")} for r in sourced["records"]]
        files, base, out["left_out"] = entered["files"], entered["base"], entered["left_out"] + refused
        entered_rels = {rel for _source, rel in files}
        out["entered"] = {"kind": entered["kind"], "agents_md": entered["agents_md"], "files": len(files)}
        base_state = _read(os.path.join(cfg["project"], *path_rule.STATE.split("/")))
        request = core._stored(ctx, store.task_get, task["parent_id"])
        request_text = request["text"]
        answered = [p for p in core._stored(ctx, store.pending_list, "resolved", task["id"]) if p["resolution"] == "answered"]
        earlier = [r for r in core._stored(ctx, store.task_runs_list, task["id"]) if r["id"] != run_id]
        edited = [rel for rel in documents.imported_since(cfg, earlier[-1]["started_at"] if earlier else None)
                  if rel in entered_rels and skill_meta.matches(meta["inputs"], rel)]
        prompt = ops_runs.task_prompt(request_text, task["text"], answered,
                             handed=[rel for _source, rel in handed if rel in entered_rels], edited=edited,
                             sourced=[line for line in sourced["lines"] if not line.startswith("- ") or any(f"- {rel} " in line for rel in entered_rels)],
                             instructions=started["instructions"], language_line=ops_language.run_line(cfg, task))
        code = None
        if entered.get("tracked") and ops_runs.code_task(meta):
            code = _code_state(ctx, task)
            if code.get("refused"):
                return fail("internal", code["refused"])
        current = (code or {}).get("current")
        gate = known.get("gate")
        # the module of the gate's effect kind; None when the word or the skill names none
        kind = _effect_kind(gate, meta["requires"])
        if kind is not None:
            refused = kind.refusal(cfg, current)
            if refused:
                return fail("internal", refused)
        try:
            installed = _dependencies(cfg, entered, read=_reader(cfg, current))
        except deps_sets.DepsError as e:
            return fail("internal", f"dependencies: {e.reason}")

        def prepare(copy, root):
            if kind is not None:
                # T23: a skill runs only up to its gate; a runtime mode in the skills with an external effect replaces this
                kind.prepare(current, copy, root, cfg, task, request["title"])
            elif current is not None:
                changeset.apply(current, copy)  # the earlier work of the request, as an uncommitted change
            for r in installed:
                deps_sets.place(r, copy)

        finish = (lambda copy, _root: [deps_sets.remove(copy, r["produces"]) for r in installed]) if installed else None
        if current is None and not installed and not gate:
            prepare = None
        with lab.session(), ops_runs._key_in_environment(routing, keys):
            result = lab.run_skill(skill, prompt, files, dest, web=routing["web"], model=routing["model"],
                                   prepare=prepare, finish=finish, tmp_in_run=bool(gate),
                                   max_cost=budget)
    except lab.LabError as e:
        return fail("internal", f"{e.kind}: {e.reason}", getattr(e, "attempts", 0))  # attempts: how many began (A-57)
    except Exception as e:  # the task never stays `running`: the error is recorded, then shown
        traceback.print_exc()
        return fail("internal", f"{type(e).__name__}: {e}", getattr(e, "attempts", 0))
    finally:
        shutil.rmtree(prepared_dir, ignore_errors=True)
    counts, timing = result["counts"], result["timing"]
    if result["status"] != "ok":
        failure = result["failure"]
        return fail(failure["kind"], failure["reason"], counts["attempts"], result["image_digest"],
                    ops_runs._count(counts.get("redactions")), result.get("reported"))
    left = result["changes"]["created"] + result["changes"]["modified"]
    bound = manifest.bound_among(known, left)
    made = _changeset_of(ctx, task, run_id, dest, result, entered, code, bound) if code is not None else None
    with core._write_lock(cfg, wait=None):  # held from the check of the stop request to the finish: the stop request is written under it (L41)
        if ops_cancel.stop_requested(ctx, task["id"]):   # a stopped run returns nothing
            return fail("stopped", "stopped before it returned anything", counts["attempts"], result["image_digest"], ops_runs._count(counts.get("redactions")), lab.reported_usage(dest))
        returned, kept, state_report = workcopy.returning(cfg["project"], result, base, base_state, skill, bound=bound,
                                                           versioned=(made or {}).get("versioned", ()),
                                                           tracked=entered.get("tracked") or () if code is None else (),
                                                           cfg=cfg)
        gate_files = _tmp_files(result.get("tmp"))
        ending, why = _ending(result, meta, skill, [rel for rel, _size in gate_files])
        gate_found = _gate_payload(result, dest, gate_files, kind) if known.get("gate") else None
        body, masked = workcopy.masked_reply(result["response"])
        if state_report is not None:
            out["state"] = {"accepted": len(state_report["accepted"]), "rejected": state_report["rejected"]}
        number = lambda key, kind: timing.get(key) if isinstance(timing.get(key), kind) and not isinstance(timing.get(key), bool) else None
        # Only a metered run has a cost that is billed, whatever the model; a subscription or free run keeps none (costs.py recomputes it).
        every = ops_runs._reported_usage(lab.reported_usage(dest), routing)  # the usage of every attempt, the retried ones too (R4-C7b)
        finish = dict(status="ok", ending=ending, attempts=counts["attempts"],
                      cost_usd=every.get("cost_usd", number("cost_usd", (int, float)) if routing["billing"] == "metered" else None),
                      tokens=every.get("tokens", number("total_tokens", int)), duration_ms=number("duration_ms", int),
                      skill_loaded=ops_runs._skill_loaded(timing, skill),
                      image_digest=result["image_digest"], run_dir=dest, redactions=ops_runs._count(counts.get("redactions")))
        if ending == "blocked":
            # The skill stopped on a missing input that another skill writes: the task is blocked, with no pending
            # decision; the note is the first sentence of the masked reply that names the missing input (else its start),
            # and `retry` makes the task ready again.
            sentence = endings.missing_input_line(body, manifest.ending_facts(core.ROOT, skill))
            done = core._stored(ctx, store.task_run_finish, run_id, task_state="blocked", task_note=ops_runs._note(sentence or body), **finish)
            out.update(status="ok", ending=ending, task_state="blocked", pending_id=None, returned=returned, kept=kept)
            return out
        mandatory = ending == "done" and bool(known.get("mandatory_milestone"))
        if made is not None:
            body = body.rstrip("\n") + "\n\n" + made["text"]
        if mandatory:
            body = body.rstrip("\n") + "\n\n" + MANDATORY_LINE
        cut = len(body.encode("utf-8")) > store.BODY_MAX
        # A run that wrote nothing and asks opens a question, which is answered. A run that wrote a declared output
        # opens a review, a draft with open questions included: its body is the whole reply, so the person reads the
        # questions and either releases the draft as it stands (its open questions stay in it, its row stays a
        # draft) or answers it, and the next run is given the answer. A run that stopped at its confirmation gate
        # (ending `gate`) opens a review too until stage 4 of the platform plan turns it into an `effect`.
        decision = {"kind": "question" if ending == "question" else "review",
                    "title": f"{skill}: {ending.replace('_', ' ')}",
                    "body": body.encode("utf-8")[:store.BODY_MAX].decode("utf-8", errors="ignore") if cut else body,
                    "payload": {"ending": ending, "why": why, "returned": returned, "kept": kept, "run_dir": dest,
                                "entered": out["entered"], "left_out": out["left_out"], "state": out["state"],
                                "routing": routing, "use": out["use"],
                                "response_file": os.path.join(result["outputs"], "response.md"), "body_cut": cut,
                                "body_masked": masked}}
        if made is not None:
            decision["payload"]["changeset"] = made["summary"]
        if gate_found is not None:
            decision["payload"]["gate"] = gate_found if ending == "gate" else {**gate_found, "recovered": False,
                                                                                "why": f"the run ended {ending}, not at its gate"}
        if ending == "gate" and gate_found is not None:
            decision = _effect_or_review(ctx, task, request, dest, decision, gate_found, made, code,
                                         known["gate"]["effect"], meta["requires"])
        if mandatory:
            decision["payload"]["mandatory_milestone"] = True
            if cut:  # the sentence stays at the end of a body that was cut
                tail = "\n\n" + MANDATORY_LINE
                room = store.BODY_MAX - len(tail.encode("utf-8"))
                decision["body"] = body.encode("utf-8")[:room].decode("utf-8", errors="ignore") + tail
        done = core._stored(ctx, store.task_run_finish, run_id, task_state="waiting", pending=decision, **finish)
        out.update(status="ok", ending=ending, task_state="waiting", pending_id=done["pending_id"], returned=returned, kept=kept)
        return out



# --- what comes back (runtime/workcopy.py: limits L7, L8, L12, L14) and the gate: the payload, then the effect or the review (principle 11) ---


def _ending(result: dict, meta: dict, skill: str, gate_files=()) -> tuple:
    """(ending, why) of a completed run, from runtime/endings.py, with the skill's facts (manifest.ending_facts),
    the declared outputs without a placeholder that the copy held, unchanged, after the run, and the files found
    under the run's returned temporary folder (gate_files)."""
    cwd, changes = result["cwd"], result["changes"]
    written = [p for p in changes["created"] + changes["modified"] if skill_meta.matches(meta["outputs"], p)]
    after = set(changes["created"] + changes["modified"] + changes["unchanged"])
    fixed = [p for p in meta["outputs"] if "<" not in p and not p.endswith("/")]
    missing = [p for p in fixed if p not in after]
    texts = [(_read(os.path.join(cwd, *p.split("/"))) or "") if lab.readable(cwd, p) else "" for p in written]
    facts = dict(manifest.ending_facts(core.ROOT, skill), outputs_present=[p for p in fixed if p in set(changes["unchanged"])],
                 gate_files=list(gate_files))
    return endings.classify(result["response"], changes, written, missing, texts, facts=facts)


def _effect_kind(gate, requires):
    """The module of the effect kind a manifest's gate names (gate.effect, through effects.gate_kind), or None when
    there is no gate, its word names no kind, the kind is not one of the gate path (GATE), or the skill does not
    declare the class of provider that executes the kind (`requires`): a design skill's `create` is no pull request.
    A task with no kind runs up to its gate and opens a review, never an effect."""
    return effects.gate_kind(gate["effect"], requires) if gate else None


def _effect_or_review(ctx: dict, task: dict, request: dict, dest: str, decision: dict, gate_found: dict, made, code,
                      effect: str, requires) -> dict:
    """The pending decision a run that stopped at its gate opens: an `effect` (the effect document's hash in
    payload_sha256) when the payload was recovered and parsed, its base and head are the configuration's, the
    configuration has code, and the change set it would commit is not blocked; else the review, its body starting
    with the reason. The classifier never guesses, and neither does this."""
    cfg = ctx["cfg"]
    kind = _effect_kind({"effect": effect}, requires)
    parsed = None
    if kind is not None and gate_found.get("payload_file"):
        with open(gate_found["payload_file"], encoding="utf-8", errors="replace") as f:
            parsed = kind.parse(f.read())
    stored = (made or {}).get("summary") or {}
    reason, chosen = None, None
    if kind is None:
        reason = f"the gate's effect {effect!r} names no kind of effect"
    elif not gate_found.get("recovered"):
        reason = f"the payload was not recovered: {gate_found.get('why')}"
    elif parsed is None:
        reason = "the payload is not in the form its kind of effect reads"
    elif kind.mismatch(parsed, cfg, task):
        reason = kind.mismatch(parsed, cfg, task)
    elif stored.get("blocked"):
        reason = "the change set is blocked"
    else:
        try:
            chosen = changeset.load(dest) if stored.get("file") else (code or {}).get("current")
        except changeset.ChangesetError as e:
            reason = f"the change set: {e.reason}"
        if reason is None and (chosen is None or chosen.get("blocked") or not (chosen["files"] or chosen["removed"])):
            reason = "there is no unblocked change set for the effect"
    if reason is not None:
        cut = decision["body"].encode("utf-8")[:ctx["store"].BODY_MAX - 2048].decode("utf-8", errors="ignore")
        return {**decision, "body": f"No effect was opened: {reason}.\n\n{cut}",
                "payload": {**decision["payload"], "effect": {"opened": False, "why": reason}}}
    doc = kind.document(effect, cfg, request, parsed, chosen, task, gate_found["payload_sha256"])
    path, digest = effects.write(dest, doc)
    payload = {**decision["payload"], "effect_file": path, "changeset_file": os.path.join(chosen["dir"], changeset.JSON_FILE),
               "changeset_dir": chosen["dir"], "payload_file": gate_found["payload_file"],
               "effect": {"opened": True, **kind.summary(doc)}}
    return {"kind": "effect", "title": kind.title(doc)[:200], "body": kind.body(doc, digest),
            "payload": payload, "payload_sha256": digest}


def _tmp_files(tmp) -> list:
    """[(relative path, bytes)] of the regular files under a run's returned temporary folder, no link followed."""
    out = []
    if not tmp or not os.path.isdir(tmp) or os.path.islink(tmp):
        return out
    for current, folders, files in os.walk(tmp):
        folders[:] = sorted(n for n in folders if not os.path.islink(os.path.join(current, n)))
        for name in sorted(files):
            path = os.path.join(current, name)
            if not os.path.islink(path) and os.path.isfile(path):
                out.append((os.path.relpath(path, tmp).replace(os.sep, "/"), os.path.getsize(path)))
    return out


def _gate_payload(result: dict, dest: str, tmp_files, kind) -> dict:
    """The payload a gate run wrote, recovered (runtime/effects.py) and kept as <dest>/payload.md; everything else
    under the returned temporary folder is deleted, and only its names and sizes are kept. Returns {"recovered",
    "why", "payload_file", "payload_sha256", "parsed", "tmp_left"}."""
    found = effects.recover_payload(result.get("response") or "", result.get("tmp"), lab.readable)
    out = {"recovered": found["recovered"], "why": found.get("why"), "payload_file": None, "payload_sha256": None,
           "parsed": False, "tmp_left": [{"name": rel, "bytes": size} for rel, size in tmp_files]}
    if found["recovered"]:
        kept = os.path.join(dest, "payload.md")
        shutil.copyfile(found["file"], kept)
        out.update(payload_file=kept, payload_sha256=found["sha256"],
                   parsed=kind is not None and kind.parse(found["text"]) is not None)
    if result.get("tmp") and os.path.isdir(result["tmp"]) and not os.path.islink(result["tmp"]):
        shutil.rmtree(result["tmp"])
    return out



# --- the code of a run: git in the project, the change set, the dependency sets ------------------------------------------------


def _git(project: str, *args) -> "subprocess.CompletedProcess":
    """git in the project (the person's own repository, run by the host); never in a copy a run touched."""
    return subprocess.run(["git", "-C", project, *args], capture_output=True, text=True, timeout=120, check=False)


def _request_run_dirs(ctx: dict, request_id: int) -> list:
    """The run folders of the completed runs of a request's tasks, newest first."""
    runs = []
    for t in core._stored(ctx, ctx["store"].tasks_list, request_id):
        if t["parent_id"] is not None:
            runs += [r for r in core._stored(ctx, ctx["store"].task_runs_list, t["id"]) if r["status"] == "ok" and r["run_dir"]]
    return [r["run_dir"] for r in sorted(runs, key=lambda r: r["id"], reverse=True)]


def _code_state(ctx: dict, task: dict) -> dict:
    """What a run whose copy holds versioned files starts from: {"project_commit", "current"}, or {"refused": why}.
    A change set is made against one commit of the project (choice K4): the run is refused while the project's
    tracked files have uncommitted changes, and when the request's current change set was made against another
    commit. The state file is left out of that check: it never travels in a change set (the path rule's class
    `state`), and code writes into it (an answer, an approval row) between the runs of a request."""
    project = ctx["cfg"]["project"]
    try:
        dirty = _git(project, "status", "--porcelain", "-z", "--untracked-files=no")
        head = _git(project, "rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError) as e:
        return {"refused": f"git could not be run in the project: {type(e).__name__}"}
    if dirty.returncode != 0 or head.returncode != 0:
        return {"refused": f"git failed in the project: {(dirty.stderr or head.stderr).strip()[:300]}"}
    if [entry for entry in dirty.stdout.split("\0") if entry and entry[3:] != path_rule.STATE]:
        return {"refused": "commit or stash the changes to tracked files first: a change set is made against a commit"}
    commit = head.stdout.strip()
    try:
        current = changeset.current(_request_run_dirs(ctx, task["parent_id"]))
    except changeset.ChangesetError as e:
        return {"refused": f"the request's change set: {e.reason}"}
    if current is not None and current.get("project_commit") != commit:
        return {"refused": f"the request's change set was made against the commit {current.get('project_commit')} and the "
                           f"project is at {commit}: cancel the request, or put the project back on that commit"}
    return {"project_commit": commit, "current": current}


def _reader(cfg: dict, current):
    """read(rel) of a dependency file as the next run sees it: the request's current change set's when it holds or
    removes the file, else the project's."""
    def read(rel):
        if current is not None:
            if rel in (current.get("removed") or []):
                return None
            for item in current.get("files") or []:
                if item["path"] == rel:
                    with open(os.path.join(current["dir"], "files", *rel.split("/")), "rb") as f:
                        return f.read()
        return _project_bytes(cfg["project"], rel)
    return read


EMPTY_CHANGESET = changeset.canonical_sha256([], [])


def _changeset_of(ctx: dict, task: dict, run_id: int, dest: str, result: dict, entered: dict, code: dict, bound) -> dict:
    """The change set a completed run left, stored in its run folder when it differs from the one it started from:
    {"summary" (for the pending decision's payload), "text" (for its body), "versioned" (the paths that never come
    back as loose files)}."""
    checks = {"readable": lab.readable, "scan": workcopy.scan, "settings": lab.carries_settings}
    facts = {"staged": list(result["staged"]) + [path_rule.DROP_DIR], "bound": list(bound)}
    try:
        made = changeset.compute(dest, result.get("base_commit"), entered["tracked"], facts, checks,
                                 protected=sources.protected_paths(ctx["cfg"]))
    except changeset.ChangesetError as e:
        why = f"the change set could not be computed: {e.reason.splitlines()[0] if e.reason else e.kind}"
        return {"summary": {"error": why}, "text": why[0].upper() + why[1:] + ".", "versioned": []}
    current = code.get("current")
    file = None
    if made["refused"] or made["sha256"] != (current["sha256"] if current else EMPTY_CHANGESET):
        made.update(request=task["parent_id"], task=task["id"], run=run_id, project_commit=code["project_commit"])
        file = changeset.store(dest, made)
    summary = {"file": file, "sha256": made["sha256"], "files": len(made["files"]), "removed": len(made["removed"]),
               "blocked": made["blocked"], "refused": made["refused"]}
    lines = [f"Change set: {len(made['files'])} file(s), {len(made['removed'])} removed"
             + (", blocked" if made["blocked"] else "") + (f", sha256 {made['sha256']}" if file else ", unchanged")]
    lines += [f"- {item['change']}: {item['path']}" + (" (executable)" if item["executable"] else "") for item in made["files"]]
    lines += [f"- removed: {rel}" for rel in made["removed"]]
    lines += [f"- refused: {item['path'] or '(the whole set)'}: {item['reason']}" for item in made["refused"]]
    return {"summary": summary, "text": "\n".join(lines), "versioned": made["versioned"]}


def _project_bytes(project: str, rel: str):
    """The bytes of a project's file at rel, or None when it is not a regular file inside the project."""
    path = os.path.join(project, *rel.split("/"))
    real = os.path.realpath(path)
    if os.path.islink(path) or not os.path.isfile(path) or not real.startswith(os.path.realpath(project) + os.sep):
        return None
    with open(path, "rb") as f:
        return f.read()


def _dependencies(cfg: dict, entered: dict, read=None) -> list:
    """The installed folders a run gets: for a run whose copy holds versioned files, each declared dependency set
    whose files are all there (read(rel), default the project's own file), installed or taken from the cache
    (runtime/deps.py). Empty for a run without versioned files. Raises deps.DepsError."""
    if not entered.get("tracked"):
        return []
    read = read or (lambda rel: _project_bytes(cfg["project"], rel))
    out = []
    for entry in cfg.get("dependencies") or []:
        files = deps_sets.files_for(entry, read)
        if files is not None:
            out.append(deps_sets.ensure(cfg["data_dir"], entry, files, lab.image()["digest"]))
    return out



if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
