#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations over flows (flow files, P6a): list them, check one, save a plan as one, hand a file over for a request,
and the pieces the rest of the layer asks of them (binding a flow's parameters and dates, and moving a handed-over file into the
task that reads it).

A flow is a file read by code (runtime/flow_files.py): the workbench's own, flows/<name>.json, and the project's, which live in the
project at docs/workbench/flows/<name>.json. That folder is the person's: it is under docs/, so the project's git versions it
beside the other documents the person keeps; it is not under .workbench-local/, which is git-ignored and holds work data. A run can
never write there (the path rule, runtime/path_rule.py, class `other`), so only the person, through the operations below (the
terminal and the page), or by hand, changes a flow.

  flows(project)                       every flow with its title, number of tasks, origin, parameters, step kinds and the result
                                       of the flow check; a file that does not pass is listed with an `error`
  check_flow(project, flow)            the flow check of one flow (runtime/flow_check.py): its findings, the split it offers
  flow_save(project, name[, pending_id, flow, title, split, replace])
                                       save an approved plan (pending_id) or a flow already there (flow) as the project flow
                                       `name`: the flow check runs first, and a finding refuses the save unless split makes the
                                       code-made split; an existing file is replaced only with replace
  stage_file(project, request_id, file)
                                       copy a file of the person's into the staging folder of a request that waits for its plan,
                                       so that a flow with a file parameter can name it and carry its hash (see below)

For the rest of the layer:
  direct(ctx, name)                    the workbench flow a request may start without a plan (a project flow, a flow with a step or
                                       with parameters is planned: the refusal says how)
  bound(ctx, name, params, request_id) (flow with its placeholders filled, "bound" for the plan): flow_files.bind() with the clock
                                       and the hashes of the files handed over for the request; OpsError (2) otherwise
  before_approve(ctx, item), after_approve(ctx, item, done)
                                       a plan with an `ingest` step that names a file: before the approval, the file must be there
                                       with the hash the plan carries; after it, the file is moved into the drop of the task that
                                       reads it

How an ingest of a file gets its file and its hash (addendum 13 of the P6 spec). A step task reads its file from the task's own drop,
.workbench-local/drop/<task id>/, and requires the sha256 in its arguments (runtime/step_ingest.py); the task id does not exist
until the plan is approved. So the file is handed over first, for the request: `stage-file` copies it, with every check of a
hand-over (a regular file, a plain name, no credential, the project's git ignores the folder), to
.workbench-local/drop/request-<request id>/. The flow names it through a file parameter (`--param survey=survey.csv`), and bind()
puts the name and the hash of those bytes into the task's arguments, so the plan the person approves carries the hash of exactly that
file. Approving checks the staged file against the plan again, creates the tasks, and moves the file into the drop of each task that
names it; the step then checks the hash a third time before it reads a byte. A flow with a file parameter is never started by
anything that has no person to hand a file over (a routine's target has none: the flow check of P6b refuses it).

The shared names come from ops_core, read as `core.<name>` at call time. It reaches no operation of ops.py. Standard library only.
Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import drop  # noqa: E402
import flow_check  # noqa: E402
import flow_files  # noqa: E402
import ops_core as core  # noqa: E402
import ops_sources  # noqa: E402
import plan  # noqa: E402
import sources  # noqa: E402
import steps  # noqa: E402

STAGE_PREFIX = "request-"         # the staging folder of a request is .workbench-local/drop/request-<id>/ (no task has a non-numeric id)
PARAM = re.compile(r"([a-z][a-z0-9_]*)=(.*)", re.S)
PLAN_REQUEST = "request"          # the parameter a saved plan declares: the request's own words, which its tasks without a text use
MAX_HASHED = drop.MAX_BYTES


def now() -> datetime.datetime:
    """The clock a plan's dates are read from: the machine's local time, with its zone. A test replaces this function."""
    return datetime.datetime.now().astimezone()


def parse_params(items) -> dict:
    """{name: value} from the repeated --param name=value of a shell (a list of text), or from a dict. A repeated name, a
    word without `=` and a name that is not a parameter name are OpsErrors (usage)."""
    if items is None:
        return {}
    if isinstance(items, dict):
        return dict(items)
    out = {}
    for item in items:
        found = PARAM.fullmatch(item) if isinstance(item, str) else None
        if not found:
            raise core.OpsError(f"{item!r} is not name=value: a parameter is given as --param name=value", 2)
        if found.group(1) in out:
            raise core.OpsError(f"the parameter {found.group(1)} is given twice", 2)
        out[found.group(1)] = found.group(2)
    return out


def _project(ctx: dict) -> str:
    return ctx["cfg"]["project"]


def _loaded(ctx: dict, name: str) -> dict:
    try:
        return flow_files.load(name, core.ROOT, _project(ctx))
    except flow_files.FlowError as e:
        raise core.OpsError(str(e), 2) from None


def _summary(name: str, origin: str, ctx: dict) -> dict:
    project = _project(ctx)
    if origin == "project" and name in flow_files.names(core.ROOT):
        return {"flow": name, "title": None, "tasks": 0, "origin": origin,
                "error": f"docs/workbench/flows/{name}.json has the name of a workbench flow and is never read: rename it"}
    try:
        loaded = flow_files.load(name, core.ROOT, project)
    except flow_files.FlowError as e:
        return {"flow": name, "title": None, "tasks": 0, "origin": origin, "error": str(e)}
    found = flow_check.check(loaded, core.ROOT)
    return {"flow": name, "title": loaded["title"], "tasks": len(loaded["tasks"]), "origin": loaded["origin"],
            "params": [{"name": n, "description": s["description"], "type": s["type"], "required": "default" not in s}
                       for n, s in loaded["params"].items()],
            "steps": sorted({t["step"] for t in loaded["tasks"] if "step" in t}),
            "check": {"ok": found["ok"], "findings": found["findings"]}}


def flows(project: str) -> dict:
    """The flows of this checkout and of the project: {"flows": [{"flow", "title", "tasks": <number of tasks>, "origin":
    "workbench" or "project", "params": [{"name", "description", "type", "required"}], "steps": [kinds], "check": {"ok",
    "findings"}}]}, the workbench's first, each group sorted by name. A file that does not pass its checks is listed with "title"
    None, "tasks" 0 and an "error" text, so one bad file hides no other."""
    ctx = core.context(project)
    return {"flows": [_summary(name, origin, ctx) for name, origin in flow_files.all_names(core.ROOT, _project(ctx))]}


def check_flow(project: str, flow: str) -> dict:
    """The flow check of one flow, the workbench's or the project's: {"flow", "origin", "ok", "findings", "template_sha256", "next"}.
    A finding is {"task", "skill", "sources", "sentence", "split", "ask"}; `next` is the command that saves the code-made split
    when every finding offers one. A read: it writes nothing."""
    ctx = core.context(project)
    loaded = _loaded(ctx, flow)
    found = flow_check.check(loaded, core.ROOT)
    return {"flow": flow, "origin": loaded["origin"], "ok": found["ok"], "findings": found["findings"],
            "template_sha256": flow_files.template_sha256(loaded),
            "next": None if found["ok"] or not all(f["split"] for f in found["findings"]) else
            core._command("flow-save", project, flow=flow, name=f"{flow}-split", split=True)}


# --- saving a plan, or a flow, as a project flow ------------------------------------------------------------------------------


def _from_plan(ctx: dict, item: dict, name: str, title) -> dict:
    """The flow (loaded form, no origin) an approved plan stands for: its tasks as they were approved, the sources it chose pinned, a
    task without a text of its own carrying `{request}` (a parameter declared with the request's words as its default)."""
    payload = item.get("payload") or {}
    tasks = payload.get("tasks") or []
    request = core._stored(ctx, ctx["store"].task_get, item["task_id"])
    out, needs_request = [], False
    files = ((payload.get("bound") or {}).get("files") or {})      # {parameter: {"name", "sha256"}} of a plan built from a flow
    for t in tasks:
        one = {"key": t["key"]}
        if t.get("step"):
            one.update(step=t["step"], args=_with_file_parameters(t["step"], json.loads(json.dumps(t.get("args") or {})), files))
        else:
            one["skill"] = t["skill"]
        text = (t.get("text") or "").strip()
        if not text and not t.get("step"):
            text, needs_request = "{" + PLAN_REQUEST + "}", True
        one.update(title=t["title"], text=text or t["title"], depends_on=list(t.get("depends_on") or []),
                   milestone=bool(t.get("milestone")))
        if t.get("sources"):
            one["sources"] = list(t["sources"])
        if t.get("web_off"):
            one["web"] = False
        out.append(one)
    params = {}
    if needs_request:
        words = (request.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not words or len(words) > flow_files.MAX_PARAM:
            raise core.OpsError(f"the request's words are longer than a parameter holds ({flow_files.MAX_PARAM} characters): "
                                "the plan cannot be saved as a flow", 1)
        params[PLAN_REQUEST] = {"description": "what the flow is asked for, in your words", "type": "text", "default": words}
    for param in files:      # a file the plan carried stays a parameter: the flow is run again with another file, not with this one
        params[param] = {"description": "a file of yours, handed over for the request (stage-file)", "type": "file"}
    return {"flow": name, "title": " ".join((title or plan.request_title(request)).split()), "params": params, "tasks": out}


def _with_file_parameters(step: str, args: dict, files: dict) -> dict:
    """The arguments of a step with the name and the hash of a file the plan bound written back as `{param}` and `{param.sha256}`: the
    `file` and `sha256` arguments, and only those, of a kind that brings a source in (the kinds that read a file from the drop). Any
    other argument, a `source` equal to the file's name for one, is left as it is."""
    if step not in steps.sourcing_kinds():
        return args
    out = dict(args)
    for param, f in files.items():
        if out.get("file") == f.get("name"):
            out["file"] = "{" + param + "}"
        if out.get("sha256") == f.get("sha256"):
            out["sha256"] = "{" + param + ".sha256}"
    return out


def _validate_steps(flow: dict) -> None:
    """The kinds of the step tasks exist and accept their arguments, when the flow has no placeholder left to fill."""
    if flow_files.placeholders(flow):
        return
    for t in flow["tasks"]:
        if "step" in t:
            try:
                steps.plan_task(t["step"], t.get("args"), key=t["key"], title=t["title"], text=t["text"])
            except steps.StepFailure as e:
                raise core.OpsError(f"the step {t['key']}: {e}", 2) from None


def _write(ctx: dict, flow: dict, replace: bool) -> dict:
    """Write docs/workbench/flows/<name>.json: a temporary file of a name of its own beside it (so a stale one of a dead process is no
    obstacle), then a link (a new file) or a rename (a replacement), so that a file is never half written and an existing one is
    never overwritten by accident; on a filesystem with no hard links a new file is renamed into place when none is there. Any failure
    of the disk is an OpsError. Returns {"path", "sha256"}."""
    project = os.path.realpath(_project(ctx))
    folder = flow_files.project_folder(project)
    rel = f"{flow_files.PROJECT_DIR}/{flow['flow']}.json"
    body = (json.dumps(flow_files.to_file(flow), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(body) > flow_files.PROJECT_FILE_BYTES:
        raise core.OpsError(f"the flow is larger than {flow_files.PROJECT_FILE_BYTES} bytes", 1)
    for part in (os.path.join(project, "docs"), os.path.join(project, "docs", "workbench"), folder):
        if os.path.islink(part):
            raise core.OpsError(f"{os.path.relpath(part, project)} is a link: no flow is written through it", 1)
    final = os.path.join(folder, flow["flow"] + ".json")
    temp = None
    try:
        os.makedirs(folder, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=f".{flow['flow']}.", suffix=".tmp", dir=folder)
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        os.chmod(temp, 0o644)
        if replace:
            os.replace(temp, final)
        else:
            try:
                os.link(temp, final)
            except FileExistsError:
                raise core.OpsError(f"{rel} exists: use replace to change it", 1) from None
            except OSError:      # no hard links on this filesystem: rename, when nothing is there (the write lock is held)
                if os.path.lexists(final):
                    raise core.OpsError(f"{rel} exists: use replace to change it", 1) from None
                os.rename(temp, final)
    except OSError as e:
        raise core.OpsError(f"{rel} could not be written: {type(e).__name__}", 1) from None
    finally:
        if temp is not None and os.path.lexists(temp):
            try:
                os.unlink(temp)
            except OSError:
                pass
    return {"path": rel, "sha256": hashlib.sha256(body).hexdigest()}


def flow_save(project: str, name: str, pending_id: int | None = None, flow: str | None = None, title: str | None = None,
              split: bool = False, replace: bool = False) -> dict:
    """Save a flow into the project (docs/workbench/flows/<name>.json) from an approved plan (pending_id: the plan decision, kind
    `plan`, resolved `approved`, so the person has seen and approved exactly these tasks) or from a flow already there (flow: its
    name, for a flow written by hand that the check refused, to save it split). Exactly one of the two. The name is a flow name that
    no workbench flow has. The flow is checked as a file (flow_files.problems) and by the flow check (runtime/flow_check.py): a
    finding refuses the save and names it, with the split when one is offered; with split the code-made split is made first (it fails
    when a finding offers none). Nothing is written on a refusal. An existing file is replaced only with replace.
    Returns {"flow", "path", "sha256", "tasks", "params", "split", "next"}."""
    if (pending_id is None) == (flow is None):
        raise core.OpsError("name a plan (pending_id) or a flow (flow), one of the two", 2)
    ctx = core.context(project)
    if not isinstance(name, str) or not flow_files.NAME.fullmatch(name):
        raise core.OpsError(f"{name!r} is not a flow name: lowercase words joined by hyphens", 2)
    if name in flow_files.names(core.ROOT):
        raise core.OpsError(f"{name} is the name of a workbench flow: a project flow takes another name", 2)
    with core._write_lock(ctx["cfg"]):
        if pending_id is not None:
            item = core._stored(ctx, ctx["store"].pending_get, pending_id)
            if item["kind"] != "plan" or item["status"] != "resolved" or item.get("resolution") != "approved":
                raise core.OpsError(f"pending decision {pending_id} is not an approved plan: approve the plan, then save it", 1)
            draft = _from_plan(ctx, item, name, title)
        else:
            draft = dict(_loaded(ctx, flow), flow=name)
            draft.pop("origin", None)
            if title:
                draft["title"] = " ".join(title.split())
        try:
            made = flow_files.normalise(flow_files.to_file(draft), name, core.ROOT)
        except flow_files.FlowError as e:
            raise core.OpsError(str(e), 2) from None
        _validate_steps(made)
        found = flow_check.check(made, core.ROOT)
        did = False
        if not found["ok"]:
            if not split:
                lines = [f["sentence"] + ("." if f["split"] else ". " + f["ask"]) for f in found["findings"]]
                offer = ("; the code can split it: research with the web and no source, then the skill without the web, with the "
                         "sources and the brief (run the same command with split)") if all(f["split"] for f in found["findings"]) else ""
                raise core.OpsError("the flow check refuses this flow: " + " ".join(lines) + offer, 1)
            try:
                made = flow_check.apply_split(made, core.ROOT)
            except flow_files.FlowError as e:
                raise core.OpsError(str(e), 1) from None
            did = True
        written = _write(ctx, made, replace)
    return {"flow": name, "tasks": len(made["tasks"]), "params": sorted(made["params"]), "split": did, **written,
            "next": f"request the flow: record a request, then route --request <id> --flow {name}"
                    + "".join(f" --param {p}=<value>" for p, s in made["params"].items() if "default" not in s)}


# --- binding a flow when a plan is built ------------------------------------------------------------------------------------------------


def _stage_id(request_id) -> str:
    return f"{STAGE_PREFIX}{request_id}"


def _hash_of(project: str, request_id, name: str) -> str:
    """The sha256 of a regular file of a request's staging folder, read through the folder's descriptors (drop.open_folder, drop.read_file:
    no link anywhere on the way, a regular file, at most MAX_HASHED bytes); OpsError when it is none."""
    try:
        dir_fd = drop.open_folder(project, _stage_id(request_id))
        try:
            data = drop.read_file(dir_fd, name, MAX_HASHED)
        finally:
            os.close(dir_fd)
    except (OSError, drop.DropError):
        raise core.OpsError(f"{name} is not a regular file in the staging folder", 1) from None
    if len(data) > MAX_HASHED:
        raise core.OpsError(f"{name} is not a regular file of at most {MAX_HASHED} bytes", 1)
    return hashlib.sha256(data).hexdigest()


def staged(project: str, request_id: int) -> dict:
    """{file name: sha256} of the files handed over for a request (stage_file), read now."""
    return {os.path.basename(path): _hash_of(project, request_id, os.path.basename(path))
            for path, _rel in drop.files(project, _stage_id(request_id))}


def stage_file(project: str, request_id: int, file: str) -> dict:
    """Copy one file of yours into the staging folder of a request that waits for its plan (.workbench-local/drop/request-<id>/):
    every check of a hand-over holds (a regular file, a plain name, a size cap, no credential, a project whose git ignores the
    folder, a name not taken: it never replaces a file). The flow then names it with a file parameter, and the plan carries its hash.
    Returns {"request", "name", "path", "bytes", "sha256", "next"}."""
    ctx = core.context(project)
    with core._write_lock(ctx["cfg"]):
        row = core._stored(ctx, ctx["store"].task_get, request_id)
        if row["parent_id"] is not None:
            raise core.OpsError(f"{request_id} is a task: a file is staged for a request; hand a file to a task with hand-over", 1)
        if row["state"] != "requested":
            raise core.OpsError(f"request {request_id} is {row['state']}: a file is staged for a request that waits for its plan", 1)
        try:
            done = drop.hand_over(_project(ctx), {"id": f"{STAGE_PREFIX}{request_id}", "state": "requested", "web": False},
                                  os.path.abspath(file), True)
        except drop.DropError as e:
            raise core.OpsError(str(e), 1) from None
    name = os.path.basename(done["path"])
    return {"request": request_id, "name": name, "path": done["path"], "bytes": done["bytes"], "sha256": done["sha256"],
            "next": core._command("route", project, request_id=request_id, flow="<flow>", params=[f"<parameter>={name}"])}


def direct(ctx: dict, name: str) -> dict:
    """The workbench flow `request --flow` may start at once, as it always did. A flow of the project, a flow with a step and a flow
    with parameters are planned: the person approves the plan by its hash. OpsError (2) says how."""
    if name in flow_files.project_names(_project(ctx)) and name in flow_files.names(core.ROOT):
        raise core.OpsError(f"docs/workbench/flows/{name}.json has the name of a workbench flow and is never read: rename it", 2)
    try:
        loaded = flow_files.load(name, core.ROOT)
    except flow_files.FlowError as e:
        if name in flow_files.project_names(_project(ctx)):
            raise core.OpsError(f"{name} is a flow of this project: record the request, then route it with "
                                f"route --request <id> --flow {name}, so that you approve its plan", 2) from None
        raise core.OpsError(str(e), 2) from None
    if flow_files.needs_plan(loaded):
        raise core.OpsError(f"the flow {name} has parameters, steps, sources or a task that runs without the web: record the request, "
                            f"then route it with route --request <id> --flow {name} (and --param name=value), so that you approve its "
                            "plan", 2)
    return loaded


def bound(ctx: dict, name: str, params, request_id: int) -> tuple:
    """(flow, bound) for a plan the person named: the flow (workbench or project) with its parameters and dates filled
    (flow_files.bind), the clock being now() and the hashes those of the files handed over for the request. `bound` is the dict the
    plan shows (flow_files.bind's), or None for a flow with no parameter and no date, whose plan stays as it was. OpsError (2) when
    a parameter is missing, unknown or refused, or a file is not handed over."""
    loaded = _loaded(ctx, name)
    if name in flow_files.project_names(_project(ctx)) and name in flow_files.names(core.ROOT):
        raise core.OpsError(f"docs/workbench/flows/{name}.json has the name of a workbench flow and is never read: rename it", 2)
    given = parse_params(params)
    if not loaded["params"] and not flow_files.placeholders(loaded):
        if given:
            raise core.OpsError(f"the flow {name} has no parameter; it was given {', '.join(given)}", 2)
        _check_sources(ctx, loaded)
        return loaded, None
    files = {}
    for p in flow_files.file_params(loaded):
        if given.get(p):
            files = staged(_project(ctx), request_id)
            break
    try:
        got = flow_files.bind(loaded, given, now(), files)
    except (flow_files.FlowError, ValueError) as e:
        raise core.OpsError(str(e), 2) from None
    _check_sources(ctx, got["flow"])
    return got["flow"], got["bound"]


def _check_sources(ctx: dict, flow: dict) -> None:
    """The sources a bound flow's skill tasks list are source ids, and each is a source the project holds (it has a version) or one a
    step of the flow brings in (as the router's choice is checked, runtime/router.py check_route). OpsError (2) otherwise: a parameter
    can fill a source id, and the plan is not built on a word that is no source."""
    brought = {t["args"]["source"] for t in flow["tasks"] if t.get("step") in steps.sourcing_kinds() and isinstance((t.get("args") or {}).get("source"), str)}
    held = set(ops_sources.known_ids(ctx))
    for t in flow["tasks"]:
        for ident in t.get("sources") or []:
            try:
                sources.check_id(ident)
            except sources.SourcesError:
                raise core.OpsError(f"the task {t['key']} lists {ident!r}, which is not a source id (lowercase letters, digits and hyphens, "
                                    "at most 40)", 2) from None
            if ident not in held and ident not in brought:
                raise core.OpsError(f"the task {t['key']} receives the source {ident}, which the project does not hold (register it with "
                                    "source-import first) and no step of the flow brings in", 2)


# --- a file named by a plan reaches the task that reads it --------------------------------------------------------------------------


def _needs(payload: dict) -> list:
    """[(task key, file name, sha256)] for each ingest step of an approved plan that names a file."""
    return [(t["key"], t["args"]["file"], t["args"]["sha256"]) for t in (payload or {}).get("tasks") or []
            if t.get("step") == flow_files.INGEST and isinstance(t.get("args"), dict) and t["args"].get("file")]


def _strict(payload: dict) -> set:
    """The names of the files a plan built from a flow carries as handed over for the request (its `bound` block): for these the
    plan promised the person a file, so approving without it is refused. A plan made another way (a router's, a test's) that names a
    file keeps the P5 path: the person hands the file to the task after the approval (hand-over --task), and the step checks its hash."""
    return {f["name"] for f in ((payload or {}).get("bound") or {}).get("files", {}).values()}


def before_approve(ctx: dict, item: dict) -> None:
    """Refuse (OpsError 1, nothing approved) a plan whose ingest step names a file when the file staged for the request has other
    bytes than the plan carries, or, for a plan built from a flow (it bound the file at the planning), when the file is no longer
    staged: the person hands the file over (stage-file) and plans again."""
    payload = item.get("payload")
    need = _needs(payload)
    if not need:
        return
    have = staged(_project(ctx), item["task_id"])
    strict = _strict(payload)
    for key, file, digest in need:
        if (file in have and have[file] != digest) or (file not in have and file in strict):
            why = "is not handed over for this request" if file not in have else "is not the file the plan carries (its hash changed)"
            raise core.OpsError(f"the task {key} reads the file {file} (sha256 {digest}), and it {why}: nothing was approved. Hand the "
                                "file over (stage-file) and plan the flow again (route)", 1)


def discard_staged(ctx: dict, request_id) -> None:
    """Remove what was handed over for a request (.workbench-local/drop/request-<id>/): regular files and links, then the folder, through
    the drop's descriptors (drop.discard). It follows nothing and never fails (a file that cannot be removed stays; the folder is the
    person's own, git-ignored)."""
    drop.discard(_project(ctx), _stage_id(request_id))


def _hand_over(ctx: dict, task_id):
    """The command that hands the file to the task by hand, after a placement that failed."""
    return core._command("hand-over", _project(ctx), task_id=task_id, file="<path>") if task_id else None


def after_approve(ctx: dict, item: dict, done: dict):
    """Move the staged files into the drop of the tasks that read them: for each ingest step that names a file staged for the request,
    a copy of the staged bytes (checked against the plan's hash) at .workbench-local/drop/<task id>/<name>. Whatever else was handed
    over for the request is then removed, the files the plan names and those it does not. This runs after the approval is committed:
    it never fails it. Returns {"placed": [{"task", "file"}], "failed": [{"task", "file", "reason"}]} (a failure leaves the task to
    fail at its step with `file_missing`, and the person hands the file to the task: hand-over --task <id> --file <path>), or None
    when nothing was staged and nothing was promised."""
    payload = item.get("payload")
    need = _needs(payload)
    project = os.path.realpath(_project(ctx))
    out = {"placed": [], "failed": []}
    ids = {t["key"]: t["id"] for t in done.get("tasks") or []}
    try:
        have = staged(project, item["task_id"])
    except (OSError, core.OpsError) as e:      # a file over the cap, or one that vanished: the files cannot be read now
        have = {}
        out["failed"] += [{"task": ids.get(key), "file": file, "reason": type(e).__name__, "next": _hand_over(ctx, ids.get(key))}
                          for key, file, _digest in need]
        need = []
    strict = _strict(payload)
    for key, file, digest in need:
        if file not in have and file not in strict:
            continue
        try:
            if have.get(file) != digest:
                raise OSError("the staged file is missing or changed")
            dir_fd = drop.open_folder(project, _stage_id(item["task_id"]))
            try:
                data = drop.read_file(dir_fd, file, MAX_HASHED)
            finally:
                os.close(dir_fd)
            if hashlib.sha256(data).hexdigest() != digest:
                raise OSError("the staged file changed while it was read")
            target = drop.open_folder(project, ids[key], create=True)   # one part at a time, none of them a link
            try:
                drop.write_new(target, file, data)
            finally:
                os.close(target)
            out["placed"].append({"task": ids[key], "file": file})
        except (OSError, drop.DropError, core.OpsError, KeyError) as e:
            out["failed"].append({"task": ids.get(key), "file": file, "reason": type(e).__name__, "next": _hand_over(ctx, ids.get(key))})
    discard_staged(ctx, item["task_id"])
    return out if out["placed"] or out["failed"] else None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
