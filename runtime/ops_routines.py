#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations over routines (package P6b; decisions D23, D24, D31 to D35, findings S3, S10, I5, F4, F12) and the tick that fires them.

A routine is a workflow started by a schedule, with no one at the plan card. It is created as a draft, from the terminal or the page
(from messaging only when the project's `channels.messaging` grants the group `routine-edit`, and never for a workflow that holds a
networked script or that a standing effect policy covers: limit L33), and it is active only when the person has approved the sha256 of
its exact content (runtime/routines.py, `content`). It carries no mode, cap, policy or standing approval of its own: the tasks a fire
creates are the area agents' tasks, count against their daily caps and follow their modes.

  routines(project[, routine_id])                  the routines with their state, content, hash now and last fire; with an id, its fires and,
                                                   for a draft, what approving it needs (the preview)
  routine_create(project, name, flow, ...)         a draft; the workflow must pass the flow check and take no file (nobody is there to hand one over)
  routine_change(project, routine_id, ...)         change fields; the approval is cleared and the routine is a draft again
  routine_approve(project, routine_id[, sha256])   without sha256 a preview (the content, its hash, the consent warning when one is needed);
                                                   with it, refused unless it is the hash of the content now
  routine_pause / routine_resume / routine_cancel  the brakes; cancel is final, a routine is never deleted

tick(ctx) is what a dispatcher round calls (runtime/ops_runs.py): for each active routine, the slots due (runtime/routines.py: the
catch-up rule), and for the one to fire:
  1. the workflow is read and passes the flow check again (D27); its content is recomputed and its hash must equal the approved one,
     else the routine stops and asks: a stopped routine, and one request with a question that says what differs, which messaging
     notifies like any pending decision;
  2. the dates are filled from the clock, the plan is built as for a manual request, and each task is an ordinary task of its area
     agent: the dispatcher's rules (modes, caps, kinds that may start unattended, the runtime's brake) apply to it;
  3. the fire is written once, with its request, in one transaction keyed by (routine, slot), under the claim lock (finding I5).
For `auto` the cheapest reliable pair inside the approved providers chooses each task's model; a better candidate outside them stops the
routine and asks (D35). A fixed model the lab has no evidence for runs unattended only with the routine's own consent (D34): the
warning is the agent consent's text (autonomy.CONSENT_WARNING), the consent enters the hash, a change of the model clears it, and the
agent's consent (D38) is never read for a routine's task (runtime/ops_models.py).

The shared names come from ops_core, read as `core.<name>` at call time. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import autonomy  # noqa: E402
import flow_check  # noqa: E402
import flow_files  # noqa: E402
import lab  # noqa: E402
import operations  # noqa: E402
import ops_core as core  # noqa: E402
import ops_flows  # noqa: E402
import ops_models  # noqa: E402
import ops_waits  # noqa: E402
import plan  # noqa: E402
import routines  # noqa: E402
import skill_meta  # noqa: E402
import steps  # noqa: E402

AUTO = ops_models.AUTO
DIRECT = "direct"        # the word for a model the gate file routes to no provider (proof: provider None)
FIELDS = ("flow", "params", "schedule", "model", "consent", "providers", "window_seconds")


# --- the content -----------------------------------------------------------------------------------------------------------------------


def _project(ctx: dict) -> str:
    return ctx["cfg"]["project"]


def _flow(ctx: dict, name: str) -> dict:
    try:
        return flow_files.load(name, core.ROOT, _project(ctx))
    except flow_files.FlowError as e:
        raise core.OpsError(str(e), 2) from None


def effective_model(ctx: dict, record: dict) -> str:
    """The word that chooses the model of a routine's tasks: its own, else the project's default_model, else `auto`; an alias is written
    as the id it names (the hash covers the id). Written into every request a fire makes, so that no agent's fixed model decides for a
    routine. OpsError (2) when the word is no model of the gate file."""
    return ops_models.check_word(record.get("model") or ctx["cfg"].get("default_model") or AUTO) or AUTO


class ImageUnavailable(core.OpsError):
    """The eval image cannot be looked up or is not on this machine: its digest is unknown, so a hash cannot be computed or approved.
    A fire defers its slot for it, never stops the routine."""


def _xy(skill: str) -> str:
    try:
        version = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))["version"] or ""
    except skill_meta.SkillError as e:
        raise core.OpsError(str(e), 2) from None
    return ".".join(version.split(".")[:2])


def content_of(ctx: dict, record: dict, loaded: dict | None = None) -> dict:
    """The content an approval covers (routines.content) for the record as it is now, with the workflow, the skills' X.Y and the image
    read now. OpsError (2) when the workflow cannot be read."""
    loaded = loaded or _flow(ctx, record["flow"])
    word = effective_model(ctx, record)
    skills = {t["skill"]: _xy(t["skill"]) for t in loaded["tasks"] if "skill" in t}
    seen = lab.image()
    if not seen.get("digest"):      # docker is down, or the image is not pulled yet: a digest of None must never be hashed or approved
        raise ImageUnavailable("the eval image cannot be looked up (" + str(seen.get("problem") or "it is not on this machine; pull it: the setup step of the doctor")
                               + "): the routine's content cannot be hashed now", 3)
    return routines.content(
        schedule=record["schedule"], window_seconds=record.get("window_seconds"), flow=loaded["flow"],
        template_sha256=flow_files.template_sha256(loaded), params=record["params"], skills=skills, image=seen["digest"],
        model=word, consent=bool(record.get("consent")) and word != AUTO, warning_sha256=autonomy.CONSENT_WARNING_SHA256,
        providers=record.get("providers") or [] if word == AUTO else [])


def _preview(ctx: dict, record: dict) -> dict:
    body = content_of(ctx, record)
    return {"content": body, "sha256": routines.sha256_of(body)}


# --- the hard limit of S10 ---------------------------------------------------------------------------------------------------------------


def local_reason(ctx: dict, loaded: dict):
    """Why a workflow may be made a routine, or a routine changed, only from the terminal or the page (limit L33), or None: it holds a
    step of a kind that reaches the network (Kind.networked: the project script of package P9), or it holds a skill with a side effect
    that a standing approval of its area agent covers. Computed from the checkout and the store, never from what a channel says."""
    for t in loaded["tasks"]:
        if "step" in t:
            try:
                if steps.kind_of(t["step"]).networked:
                    return f"the task {t['key']} is a {t['step']} step, which reaches the network"
            except steps.StepFailure:      # a limit refuses what it cannot read, never skips it
                return f"the task {t['key']} is a step of a kind ({t['step']}) this checkout does not have, so it cannot be shown not to reach the network"
    cfg = ctx["cfg"]
    if not cfg.get("area_agents"):
        return None
    covered = {(a.get("bounds") or {}).get("agent") for a in core._stored(ctx, ctx["store"].approvals_list, status="active", scope="standing")}
    if not covered:
        return None
    agents = plan.agent_skills(cfg, core.ROOT)
    for t in loaded["tasks"]:
        if "skill" not in t:
            continue
        try:
            effects = skill_meta.declared(os.path.join(core.ROOT, "skills", t["skill"]))["side_effects"]
            owner = plan.agent_of(t["skill"], agents)
        except (skill_meta.SkillError, ValueError):
            continue
        if effects and owner in covered:
            return f"the task {t['key']} ({t['skill']}) has a side effect that a standing approval of {owner} covers"
    return None


def _require_local(ctx: dict, channel, *flows) -> None:
    if channel in operations.ROUTINE_LOCAL_CHANNELS or channel is None:
        return
    for loaded in flows:
        reason = local_reason(ctx, loaded)
        if reason:
            raise core.OpsError(f"a routine whose workflow holds a networked script, or that a standing effect policy covers, is made and "
                                f"changed only in the terminal or on the page, whatever the project's policy grants: {reason}", 1)


# --- validating a record ---------------------------------------------------------------------------------------------------------------


def _check_workflow(ctx: dict, name: str, params: dict) -> dict:
    loaded = _flow(ctx, name)
    for t in loaded["tasks"]:
        if "step" in t:
            try:
                steps.kind_of(t["step"])
            except steps.StepFailure:
                raise core.OpsError(f"the task {t['key']} of the workflow {name} is a step of a kind ({t['step']}) this checkout does not have", 2) from None
    if flow_files.file_params(loaded):
        raise core.OpsError(f"the workflow {name} takes a file ({', '.join(flow_files.file_params(loaded))}): nobody is there to hand a "
                            "file over when a routine fires, so it cannot be a routine's target", 2)
    try:
        flow_files.bind(loaded, params, ops_flows.now(), {})
    except (flow_files.FlowError, ValueError) as e:
        raise core.OpsError(str(e), 2) from None
    found = flow_check.check(loaded, core.ROOT)
    if not found["ok"]:
        raise core.OpsError("the flow check refuses this workflow as a routine's target: " + " ".join(f["sentence"] + "." for f in found["findings"])
                            + " Save a split of it (flow-save --split) or change it.", 1)
    return loaded


def _default(ctx: dict) -> str:
    """The project's default model as an id of the gate file, or `auto`."""
    return ops_models.check_word(ctx["cfg"].get("default_model") or AUTO) or AUTO


def _providers_known() -> set:
    return {lab.reference(m).get("route") or DIRECT for m in lab.models()}


def _check_providers(word: str, providers) -> list:
    known = _providers_known()
    chosen = sorted(set(providers or []))
    unknown = [p for p in chosen if p not in known]
    if unknown:
        raise core.OpsError(f"{', '.join(unknown)} is not a provider of the gate file's models; they are: {', '.join(sorted(known))}", 2)
    if word == AUTO and not chosen:
        raise core.OpsError("a routine on `auto` names the providers it may use (--provider, repeated): the cheapest reliable pair inside "
                            "them is chosen, and a better candidate outside them stops the routine and asks", 2)
    return chosen


def _schedule(old: dict | None, given: dict) -> dict:
    fields = {k: v for k, v in given.items() if v is not None}
    base = {} if (old is None or "every" in fields) else dict(old)
    try:
        return routines.check_schedule({**base, **fields})
    except ValueError as e:
        raise core.OpsError(str(e), 2) from None


def _consent_given(channel, consent, warning_sha256, word: str) -> bool:
    """Whether the routine's consent (D34) is given by this call: the terminal's flag, or the page's with the hash of the warning it
    showed; never from messaging, never for `auto` (which releases only proven pairs)."""
    if not consent:
        return False
    if word == AUTO:
        raise core.OpsError("a routine on `auto` needs no consent: it releases only the pairs the evidence proves", 2)
    if channel == "page":
        if warning_sha256 != autonomy.CONSENT_WARNING_SHA256:
            raise core.OpsError("the page gives the consent with the hash of the warning it showed", 2)
    elif channel not in (None, "terminal"):
        raise core.OpsError("the consent of a routine is given in the terminal or on the page, never from a messaging channel", 1)
    return True


# --- the operations ---------------------------------------------------------------------------------------------------------------------


def _row(ctx: dict, routine_id: int) -> dict:
    return core._stored(ctx, ctx["store"].routine_get, routine_id)


def _view(ctx: dict, record: dict) -> dict:
    out = {k: v for k, v in record.items() if k != "approved_content"}
    try:
        shown = _preview(ctx, record)
        out.update(sha256=shown["sha256"], content=shown["content"], current=shown["sha256"] == record.get("approved_sha256"))
    except core.OpsError as e:
        out.update(sha256=None, content=None, current=False, problem=str(e))
    out["model_word"] = effective_model(ctx, record)
    return out


def routines_read(project: str, routine_id: int | None = None) -> dict:
    """The routines, each with its state, its approved hash, the hash of its content now and whether they are equal, and its last fire.
    With an id: that routine with its fires (newest first) and, while it is not approved, `approve`: what approving it needs
    ({"sha256", "consent_needed", "warning", "warning_sha256", "command"})."""
    ctx = core.context(project)
    if routine_id is None:
        return {"routines": [_view(ctx, r) for r in core._stored(ctx, ctx["store"].routines_list)]}
    record = _row(ctx, routine_id)
    out = _view(ctx, record)
    out["fires"] = core._stored(ctx, ctx["store"].routine_fires_list, routine_id, 50)
    if record["state"] in ("draft", "stopped") and out.get("sha256"):
        needed = _consent_needed(ctx, record)
        out["approve"] = {"sha256": out["sha256"], "consent_needed": needed,
                          "warning": autonomy.CONSENT_WARNING if needed else None,
                          "warning_sha256": autonomy.CONSENT_WARNING_SHA256 if needed else None,
                          "command": core._command("routine-approve", project, routine_id=routine_id, sha256=out["sha256"])}
    return out


def _consent_needed(ctx: dict, record: dict) -> bool:
    """Whether the model is fixed and unproven for a skill of the workflow, so that the routine's tasks wait at their first review
    unless the routine carries its consent (D34)."""
    word = effective_model(ctx, record)
    if word == AUTO or record.get("consent"):
        return False
    keys = core._keys()
    try:
        loaded = _flow(ctx, record["flow"])
        for skill in sorted({t["skill"] for t in loaded["tasks"] if "skill" in t}):
            meta = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))
            if ops_models.route(ctx, skill, meta, keys, None, word)["autonomy"] != "proven":
                return True
    except (core.OpsError, skill_meta.SkillError):
        return False
    return False


def routine_create(project: str, name: str, flow: str, params: list | None = None, every: str | None = None, at: str | None = None,
                   weekday: int | None = None, minutes: int | None = None, model: str | None = None, providers: list | None = None,
                   window_seconds: int | None = None, consent: bool = False, warning_sha256: str | None = None,
                   channel: str | None = None) -> dict:
    """Create a routine as a draft (it fires nothing until routine_approve). `flow` is the workflow (a workbench's or the project's); `params`
    its fixed arguments, "name=value" (the dates are filled at each fire); the schedule is every day at HH:MM, every week on a weekday at
    HH:MM, or every N minutes; `model` is a model id of the gate file, `auto` or nothing (the project's default); `providers` the
    approved set for `auto`; `consent` the routine's own consent for a fixed model (D34). Returns the routine and what approving it needs."""
    ctx = core.context(project)
    fixed = ops_flows.parse_params(params)
    loaded = _check_workflow(ctx, flow, fixed)
    _require_local(ctx, channel, loaded)
    schedule = _schedule(None, {"every": every, "at": at, "weekday": weekday, "minutes": minutes})
    chosen = ops_models.check_word(model)
    word = chosen or _default(ctx)
    given = _consent_given(channel, consent, warning_sha256, word)
    if given and chosen is None:      # the consent is for a model: the one the project's default names is written on the record
        chosen = word
    record = core._stored(ctx, ctx["store"].routine_add, name=name, flow=flow, params=fixed, schedule=schedule, model=chosen, consent=given,
                          providers=_check_providers(word, providers) if word == AUTO else [], window_seconds=window_seconds)
    return routines_read(project, record["id"])


def routine_change(project: str, routine_id: int, flow: str | None = None, params: list | None = None, every: str | None = None,
                   at: str | None = None, weekday: int | None = None, minutes: int | None = None, model: str | None = None,
                   providers: list | None = None, window_seconds: int | None = None, consent: bool = False,
                   warning_sha256: str | None = None, channel: str | None = None) -> dict:
    """Change a routine: what is given replaces what is there. The approval is cleared and the routine is a draft until the person
    approves the new content's hash. A change of the model clears the consent unless it is given again."""
    ctx = core.context(project)
    old = _row(ctx, routine_id)
    new_flow = flow or old["flow"]
    fixed = ops_flows.parse_params(params) if params is not None else old["params"]
    loaded = _check_workflow(ctx, new_flow, fixed)
    _require_local(ctx, channel, loaded, _flow(ctx, old["flow"]))
    fields = {"flow": new_flow, "params": fixed}
    if any(v is not None for v in (every, at, weekday, minutes)):
        fields["schedule"] = _schedule(old["schedule"], {"every": every, "at": at, "weekday": weekday, "minutes": minutes})
    if model is not None:
        fields["model"] = ops_models.check_word(model)
    if window_seconds is not None:
        fields["window_seconds"] = window_seconds
    word = fields.get("model", old["model"]) or _default(ctx)
    changed_model = "model" in fields and fields["model"] != old["model"]
    fields["consent"] = _consent_given(channel, consent, warning_sha256, word) or (bool(old["consent"]) and not changed_model and word != AUTO)
    if fields["consent"] and fields.get("model", old["model"]) is None:      # the consent is for a model: the project's default is written on the record
        fields["model"] = word
    fields["providers"] = _check_providers(word, providers if providers is not None else old["providers"]) if word == AUTO else []
    core._stored(ctx, ctx["store"].routine_change, routine_id, **fields)
    _close_stops(ctx, routine_id)
    return routines_read(project, routine_id)


def routine_approve(project: str, routine_id: int, sha256: str | None = None) -> dict:
    """Without sha256, the preview (routines_read with the id). With it: refused unless it is the sha256 of the content now; then the
    routine is active, with that content on record, and a request an earlier stop left open is cancelled."""
    ctx = core.context(project)
    record = _row(ctx, routine_id)
    if record["state"] == "cancelled":
        raise core.OpsError(f"routine {routine_id} is cancelled: it is not approved", 1)
    if sha256 is None:
        return routines_read(project, routine_id)
    shown = _preview(ctx, record)
    if sha256 != shown["sha256"]:
        raise core.OpsError(f"the routine's content has the hash {shown['sha256']} now, not {sha256}: nothing was approved", 1)
    core._stored(ctx, ctx["store"].routine_approve, routine_id, sha256=sha256, by="user", content=shown["content"])
    _close_stops(ctx, routine_id)
    return routines_read(project, routine_id)


def _close_stops(ctx: dict, routine_id: int) -> None:
    """Cancel the requests that earlier stops of the routine left open (the question of a stop): approving, changing or cancelling the
    routine answers them."""
    for fire in core._stored(ctx, ctx["store"].routine_fires_list, routine_id, 20):
        if fire["status"] == "asked" and fire["request_id"]:
            try:
                core._stored(ctx, ctx["store"].request_cancel, fire["request_id"], by="user")
            except core.OpsError:
                pass      # already answered, cancelled or gone


def routine_pause(project: str, routine_id: int) -> dict:
    """Pause an active routine: no slot fires while it is paused, and the slots it passes are not made up (the window is not kept)."""
    ctx = core.context(project)
    core._stored(ctx, ctx["store"].routine_move, routine_id, "pause")
    return routines_read(project, routine_id)


def routine_resume(project: str, routine_id: int) -> dict:
    """Resume a paused routine. Its approval stands; a fire still compares the hash."""
    ctx = core.context(project)
    core._stored(ctx, ctx["store"].routine_move, routine_id, "resume")
    return routines_read(project, routine_id)


def routine_cancel(project: str, routine_id: int) -> dict:
    """Cancel a routine for good (a routine is never deleted; its fires stay on record)."""
    ctx = core.context(project)
    core._stored(ctx, ctx["store"].routine_move, routine_id, "cancel")
    _close_stops(ctx, routine_id)
    return routines_read(project, routine_id)


# --- the tick ----------------------------------------------------------------------------------------------------------------------------


def _since(record: dict):
    """The local time (naive) from which a routine counts its slots: its approval or its last resume, whichever is later. What passed
    while it was paused or a draft is not owed."""
    import datetime
    zone = ops_flows.now().tzinfo
    moments = []
    for key in ("approved_at", "resumed_at"):
        if record.get(key):
            moment = datetime.datetime.fromisoformat(record[key].replace("Z", "+00:00"))
            moments.append(moment.astimezone(zone).replace(tzinfo=None) if moment.tzinfo else moment)
    return max(moments) if moments else datetime.datetime.fromisoformat(record["created_at"].replace("Z", "+00:00")).astimezone(zone).replace(tzinfo=None)


def tick(ctx: dict, now=None) -> list:
    """Fire what is due. For each active routine: the slots after its newest fire row, its approval or its last resume, whichever is
    latest, up to now; the newest is fired if it is younger than the window and every older one is recorded skipped (the catch-up rule);
    all are skipped otherwise. Returns [{"routine", "slot", "status", "reason", "request"}] with status created, asked, skipped,
    deferred (the eval image cannot be looked up: no row is written, the next tick tries again) or inactive (the routine was paused,
    changed or approved again while this tick worked: nothing is written); a routine whose handling raises gives one
    {"routine", "error"} line and never keeps the others from firing."""
    now = now or ops_flows.now()
    local = now.replace(tzinfo=None)
    out = []
    for record in core._stored(ctx, ctx["store"].routines_list):
        if record["state"] != "active" or not record.get("approved_sha256"):
            continue
        try:
            out += _tick_one(ctx, record, now, local)
        except Exception as e:      # one routine's failure is its own line; the others still fire
            out.append({"routine": record["name"], "error": f"{type(e).__name__}: {e}"[:300]})
    return out


def _tick_one(ctx: dict, record: dict, now, local) -> list:
    out = []
    last = record.get("last_fire") or {}
    found = routines.due(record["schedule"], last.get("slot"), _since(record), local, record.get("window_seconds"))
    if not found["fire"] and not found["skipped"]:
        return out
    for slot in found["skipped"]:
        with core._claim_lock(ctx["cfg"]):
            made = core._stored(ctx, ctx["store"].routine_fire, routine_id=record["id"], slot=slot, status="skipped",
                                approved_sha256=record["approved_sha256"],
                                reason=f"missed: not made up (the newest slot is {'fired' if found['fire'] else 'older than the window of ' + str(found['window']) + ' s'}"
                                       + (f"; {found['skipped_count']} slots were missed in all" if found["skipped_count"] > len(found["skipped"]) else "") + ")")
        if made.get("inactive"):
            return out + [{"routine": record["name"], "slot": slot, "status": "inactive", "reason": "the routine changed while this tick worked", "request": None}]
        out.append({"routine": record["name"], "slot": slot, "status": "skipped", "reason": "missed", "request": None})
    if found["fire"]:
        out.append(fire(ctx, record, found["fire"], now))
    return out


def _ask(ctx: dict, record: dict, slot: str, why: str, extra: dict | None = None) -> dict:
    """Stop the routine and ask: one fire row `asked`, one request with a question, the routine `stopped`; under the claim lock."""
    title = f"Routine {record['name']} stopped at {slot}"[:200]
    command = core._command("routine-approve", ctx["cfg"]["project"], routine_id=record["id"])
    body = (f"The routine {record['name']} did not start its tasks for the slot {slot}: {why}.\n\nIt is stopped. Read it with "
            f"`routines --id {record['id']}`, and when you accept its content as it is now, approve it: {command} (then --sha256 with the hash it prints). "
            "Answering this question only closes it; approving the routine cancels this request.")
    with core._claim_lock(ctx["cfg"]):
        made = core._stored(ctx, ctx["store"].routine_fire, routine_id=record["id"], slot=slot, status="asked", reason=why[:900],
                            approved_sha256=record["approved_sha256"],
                            question={"title": title, "body": body, "payload": {"routine": record["id"], "slot": slot, **(extra or {})}},
                            state="stopped")
    if made.get("inactive"):
        return {"routine": record["name"], "slot": slot, "status": "inactive", "reason": "the routine changed while this tick worked", "request": None}
    return {"routine": record["name"], "slot": slot, "status": "asked", "reason": why, "request": made.get("request")}


def _models_for(ctx: dict, record: dict, tasks: list):
    """For `auto`: every skill task is pinned to the cheapest reliable pair inside the approved providers (its `model` is set, so that no
    default of the project or of an agent can send it elsewhere), or the sentence of why none can be: no reliable pair inside the set,
    or a better candidate that only a provider outside it offers. Returns (tasks, None) or (None, why)."""
    approved = {None if p == DIRECT else p for p in record.get("providers") or []}
    keys, chosen = core._keys(), {}
    for skill in sorted({t["skill"] for t in tasks if t.get("skill")}):
        meta = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))
        inside = ops_models.route(ctx, skill, meta, keys, None, AUTO, approved=approved)
        open_ = ops_models.route(ctx, skill, meta, keys, None, AUTO)
        if open_["mode"] == AUTO and open_["model"] != inside["model"] and open_["model"] in (inside.get("outside_provider") or []):
            return None, (f"for {skill} a better candidate is {open_['model']}, from a provider the routine was not approved for "
                          f"(it may use: {', '.join(record.get('providers') or [])})")
        if inside["mode"] != AUTO:
            return None, (f"for {skill} no reliable pair with a key and a price is inside the providers the routine was approved for "
                          f"({', '.join(record.get('providers') or [])}); the model that would run otherwise is {inside['model']}")
        chosen[skill] = inside["model"]
    return [dict(t, model=chosen[t["skill"]]) if t.get("skill") else t for t in tasks], None


def fire(ctx: dict, record: dict, slot: str, now) -> dict:
    """Fire one slot of one routine, once (module text). Returns {"routine", "slot", "status": created|asked|deferred|inactive|duplicate,
    "reason", "request"}."""
    store, cfg = ctx["store"], ctx["cfg"]
    try:
        loaded = _flow(ctx, record["flow"])
        found = flow_check.check(loaded, core.ROOT)
        if not found["ok"]:
            return _ask(ctx, record, slot, "the flow check refuses the workflow now: " + " ".join(f["sentence"] for f in found["findings"]))
        now_content = content_of(ctx, record, loaded)
        digest = routines.sha256_of(now_content)
        if digest != record["approved_sha256"]:
            differs = routines.differences(record.get("approved_content") or {}, now_content)
            return _ask(ctx, record, slot, "its content changed since you approved it (" + ", ".join(differs) + ")",
                        {"approved_sha256": record["approved_sha256"], "sha256": digest})
        bound = flow_files.bind(loaded, record["params"], now, {})
        ops_flows._check_sources(ctx, bound["flow"])
        agents = plan.agent_skills(cfg, core.ROOT)
        tasks = plan.from_flow(bound["flow"], core.ROOT, plan.pack_skills(cfg, core.ROOT))
        tasks = [dict(t, agent=plan.agent_for(t, agents)) for t in tasks]
        word = effective_model(ctx, record)
        if word == AUTO:
            tasks, why = _models_for(ctx, record, tasks)
            if why:
                return _ask(ctx, record, slot, why)
        waits = ops_waits.for_plan(ctx, tasks, None)["store"]
    except ImageUnavailable as e:      # not the routine's fault: the slot is tried again at the next tick (and skipped if the window passes first)
        return {"routine": record["name"], "slot": slot, "status": "deferred", "reason": str(e), "request": None}
    except (core.OpsError, flow_files.FlowError, plan.PlanError, ValueError, skill_meta.SkillError, lab.LabError) as e:
        return _ask(ctx, record, slot, f"it cannot be planned now ({type(e).__name__}): {e}")
    request = {"title": f"{record['name']} · {slot}"[:200], "text": f"Routine {record['name']}, slot {slot}. Dates: today {bound['bound']['dates']['today']}, "
                                                                f"week {bound['bound']['dates']['week']} ({bound['bound']['dates']['zone']}).",
               "flow": bound["flow"]["flow"], "tasks": tasks, "waits": waits, "model": None if word == AUTO else word}
    with core._claim_lock(cfg):
        made = core._stored(ctx, store.routine_fire, routine_id=record["id"], slot=slot, status="created", reason=None, request=request,
                            approved_sha256=record["approved_sha256"])
    if made.get("inactive"):
        return {"routine": record["name"], "slot": slot, "status": "inactive", "reason": "the routine was paused, changed or approved again while this tick worked", "request": None}
    if not made.get("fired"):
        return {"routine": record["name"], "slot": slot, "status": "duplicate", "reason": "this slot was already fired", "request": None}
    ops_waits.rederive(ctx)
    return {"routine": record["name"], "slot": slot, "status": "created", "reason": None, "request": made["request"]}


# --- what a routine's task asks (the consent) --------------------------------------------------------------------------------------------


def routine_of_task(ctx: dict, task: dict | None):
    """The routine whose fire made the request a task belongs to, or None."""
    if task is None or task.get("parent_id") is None:
        return None
    found = ctx["store"].routine_of_request(ctx["conn"], task["parent_id"])
    return found["routine"] if found else None


def consent_in_force(record: dict | None, model) -> bool:
    """Whether a routine's own consent (D34) holds for a run on `model`: the routine is active, carries the consent, and its fixed model is
    that one. A routine on `auto` or on the default has none to give."""
    if not record or record["state"] != "active" or not record.get("consent") or not record.get("model") or record["model"] == AUTO:
        return False
    try:
        return lab.resolve_model(record["model"]) == model
    except lab.LabError:
        return False


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
