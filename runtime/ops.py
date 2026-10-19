#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations layer of the task runtime: every operation a person or a scheduler can perform, once.

The terminal shell (runtime/cli.py), the conversation (runtime/chat.py) and later the local interface are shells over the
functions of this file: a shell parses what the person typed, calls one function here and prints what it
returns. No shell reaches the store, the lab facade or a project's files by itself. What a shell may call, with which
arguments and from which channel, is the table of operations (runtime/operations.py, re-exported here as
ops.operations): a shell derives its verbs and commands from it, and a text of this file that names a command is built
by it, never written out.

Every operation takes the project folder first, reads the project's configuration
(<project>/docs/workbench/runtime.json, runtime/project_config.py), refuses to act when that file names
another workbench checkout than the one this code runs from, opens the store (class store:runtime, through
providers/resolve.py) and returns a JSON-serialisable object. An operation that changes the store does it
through one function of the store, which is one transaction.

Operations of stage 1 of the platform plan:
  request(project, text, flow)     record a request and the tasks of the named flow file
  run_next(project[, model])       run the next ready task: one skill, once, in the eval container, on a copy
                                   of what may enter by limits L1 to L6 (runtime/workcopy.py); bring back what
                                   it left by the path rule; open the pending decision the task then waits on
  run_task(project, task_id[, model])   the same for one named task, in this process: what the dispatcher starts for each
                                   task it runs (several at once, one OS process each; runtime/ops_runs.py)
  pending(project[, pending_id])   what waits for the person
  answer(project, pending_id, text)   answer a pending decision: the task runs again with the answer
  release(project, pending_id)     release a delivery: the task is done, and what depended on it becomes ready
  retry(project, task_id)          make a failed or blocked task ready again
  cancel, stop_task                cancel a request, or stop one running task (it is blocked, `retry` resumes it), at any moment: ops_cancel.py
  status(project)                  requests, tasks, pending decisions
  proof(project[, skill])          the model each skill in use would run on when nothing chooses one, and its band on every model
                                   (runtime/proof.py); no model is called
  verdict(project, run_id, word)   record the person's verdict (worked, corrected, failed) on the use of a run,
                                   with the existing recorder (scripts/evidence.py)
  accept_config(project, sha256)   record the hash of docs/workbench/runtime.json the person accepts (runtime/ops_config.py);
                                   every other operation refuses a configuration whose hash is not the accepted one

Operations of stage 3:
  request(project, text)           without a flow: a request that waits for its route
  route(project, request_id[, flow])   one run of the router skill asked only for the route (runtime/router.py),
                                   or, with flow, the flow the person names; either way code builds the plan
                                   (runtime/plan.py) as a pending decision of kind `plan`; no task is created
  approve(project, pending_id[, sha256])   approve a plan (its tasks are created) or an acceptance
  reject(project, pending_id[, note])      reject a plan or an acceptance: the request is cancelled
  sync(project[, dry_run][, take, path])   mirror the tasks with the project's task board (runtime/board.py) and
                                   the documents with its documents platform (runtime/documents.py): what a person
                                   edited there comes in, what the store and the project hold goes out; a dry run
                                   reads nothing and shows every write; take and path settle a document that was not
                                   taken
  answer(..., with_comments=True)  the comments saved from the board for the task, and from the platform for the
                                   documents its skill owns, enter the answer
  hand_over(project, task_id, file)   put a file of the person's in a task's file drop (runtime/drop.py): it enters
                                   that task's runs, and the prompt lists it

Operations of stage 4:
  deps(project)                    install the project's declared dependency sets by code, with no model
                                   (runtime/deps.py); a run whose copy holds versioned files gets each set that
                                   applies, after its base commit, and never brings it back

Operations of stage 6:
  progress(project[, since])       where the work stands and what happened in a period (runtime/progress.py),
                                   computed from the store's records; it calls no model
  approve_policy(project, file, agent[, sha256, expires, what])   a standing approval of a policy file, bound by
                                   its hash, with an expiry: without the hash a preview; with it, the approvals table
                                   gets the row (an earlier one of the same policy and agent is revoked) and the state
                                   file's ## Approvals its generated copy, the row the engagement gate reads
  revoke_policy(project, approval_id)   end a standing approval; its row leaves the state file
  standing(project, policy)        whether an active standing approval covers the policy now: a read
  execute_under_policy(project, policy, effect_file[, replay_log])   the one place a policy effect is executed:
                                   checks the effect document against the standing approval's bounds (autonomy.covers,
                                   a class of targets resolved from a recorded fact first) holding the write lock, runs
                                   the kind's judgement, makes the provider's dry run and its confirmed call, records
                                   the action; with replay_log it does every check and nothing else
  set_mode(project, agent, mode[, accept, channel])   set one area agent's autonomy mode in runtime.json (runtime/ops_config.py;
                                   runtime/autonomy.py, the five modes, in the order stopped < supervised < milestones <
                                   autonomous < autonomous-with-policy). A move down that order is accepted by code at once
                                   (`code:narrowing`); a move up is accepted by the person (accept_config), or, with
                                   `accept` from the terminal only, in the same step (`person`), when the file was the accepted
                                   one before. Either rewrites the state file's Checkpoints line, a generated copy of the
                                   most careful enabled agent's mode
  route(project, request_id)       a request whose lines starting with "- " list several deliveries gets one router
                                   run per delivery and one plan of them all, a delivery starting after
                                   an earlier one only when it reads what that one writes (runtime/plan.py, combine); a route to the brief skill plans one brief task, and
                                   the delivery is routed again after the brief is released; every task names its
                                   area agent
  dispatch(project[, budget_seconds, wait])   the dispatcher's round (runtime/dispatcher.py decides): the handlers' ticks,
                                   the releases each agent's mode makes, the runs its mode, caps, slots and the files
                                   in use allow, each a process of its own
  poll(project)                    the short job: mirrors, expired approvals, the state file's generated lines, the
                                   releases a mode makes; it calls no model and starts no task
  handler_call(project, name, verb[, args])   one verb of a handler under runtime/handlers/, its JSON object
  pin(project)                     the pin of the dispatcher's two jobs: the accepted runtime.json's path and hash
  say(project, text[, channel])    one turn of the conversation with the planning agent (runtime/chat.py is its shell):
                                   a command, the answer to the router's question, or a new request with the memory
  release(project, pending_id)     also starts what a release starts: the brief's delivery routed again (its tasks
                                   wait in an acceptance), and, when the released task returned the product backlog,
                                   its todo tasks as sub-tasks inside the approved plan's limits (the others wait in
                                   an acceptance)

Operations of stage 7:
  ask(project, text[, channel, sender])                     one question answered from the project's sources (runtime/ops_ask.py)
  contained_run(project, skill, prompt, out_dir[, platforms, timeout])   one run of one skill of an area agent's
                                   pack, in the eval container, on the artifacts the skill declares and nothing else,
                                   for a caller that is not a task (a handler's agent run): nothing is brought back, only
                                   the reply, past the credential scan, in <out_dir>/response.md with <out_dir>/timing.json

Operations of stage 9 (the local service, runtime/service.py, is one more shell of this layer):
  config(project)                  the configuration's path and hash, whether the person accepted that hash, and the data
                                   folder: the one read that does not refuse a configuration that was not accepted
  task(project, task_id)           one task or request with its runs and its pending decisions of every status
  flows(project)                   the flow files of this checkout: name, title, number of tasks (or the error)
  stop_runs([project, every])      end the runs this process started (its children, and the lab's own stop); with every,
                                   the task runs of the project that a live process holds
  pending, status                  each pending decision carries "actions": the resolution words the store allows for it
                                   now, built from the store's tables (an open effect: approved and rejected)
  approve(..., channel)            an effect is approved from the terminal and from the local page, with its hash; any
                                   other channel, or none, is refused
  agents(project)                  each area agent: its configuration, the mode it acts in now, its use of today, the
                                   tasks queued for it and how many of them the last round held
  status(project)                  also "held": the ready tasks the last round did not start, each with its reason
                                   (runtime/dispatcher.py, REASONS), or "dispatch off" while the local service dispatches nothing
  service_check(project[, dispatch_every])   what the local service checks at its start (secret store, credential,
                                   docker, image, dispatch) and remembers for connections and status
  conversation(project[, conversation, after])   the messages of the project's conversation above an id, oldest first
  skills(project)                  the skills in scope with their version, area, whether they have a runtime manifest,
                                   their proof as runtime/proof.py gives it and their runs here, and the two checks
  costs(project[, since])          the runs by day, agent, model and adapter with the cost the store recorded and the
                                   cost recomputed from the token counts and model_prices (runtime/costs.py)
  connections(project)             which provider each requirement class of the skills in scope resolves to, which
                                   secrets are found and where (never a value), the eval image and the platform; no
                                   provider is started and nothing goes over the network; "service": what the local
                                   service found at its start, null in any other process
  artifacts(project), artifact(project, path)   the project's files under docs/ with their owner skill, and the text
                                   of one of them, read-only
  say, route                       while the router answers another request (it holds the route lock) a line, or a request to
                                   route, is queued (runtime/ops_say.py) instead of refused; route_queued answers the oldest

Code comes back as a change set (runtime/changeset.py, limits L9 and L11): a run of a code task (its skill is of a
code area, code_task) whose copy holds versioned files starts only when the project's tracked files have no
uncommitted change, from the project's files plus the newest unblocked change set of its request; what it did to
versioned files is kept in its run folder as one change set, never written into the project. A document task makes
no change set and is not held to clean tracked files; a versioned file it changed is listed in `kept`. The pending decision lists the change set, and a review whose change set is blocked
is not released: it is answered, or the request is cancelled.

A task whose skill's runtime manifest names a gate (the pull-request skill) runs up to its confirmation gate: its
copy holds the request's change set as one commit on a branch over its base (the configuration's code.base), as the
skill was measured; its temporary folder comes back in its run folder; the payload it wrote there is recovered only
when it is the file its reply hashed (runtime/effects.py), and kept as <run folder>/payload.md. When it parsed,
agrees with the configuration and the change set is not blocked, the task waits on an `effect`: the effect document
(<run folder>/effect.json) and its hash. approve(project, pending_id, sha256) with that hash records the approval
(the store's approvals table), checks that nothing moved, and code makes the one commit and opens the pull request
through the code provider; reject cancels the task and sends nothing; answer sends it back with a comment. Any
other case opens a review whose body starts with the reason no effect was opened.

A task whose skill's runtime manifest sets mandatory_milestone is a milestone whatever its flow file says; the review
its run opens when it ends `done` says so and carries "mandatory_milestone": true in its payload.

With a documents platform, run_next reads it first (documents.pull) and runs nothing while a document the task's
skill declares was edited there and not taken; after the run, the documents it returned are written to it
(documents.push), and a failed write never fails the task. A document the mirror imported from the platform (a
person's edit) since a task's last run is named to that task's next run, when its skill reads it, in one line of
its prompt (EDITED_LINE): the content is the person's, not external content.

Releasing is not approving: a released delivery stays a draft in the project's state file.

The pending decision a run opens: a `question` when the run wrote nothing and asks (ending `question`); a
`review` otherwise. A draft with open questions (ending `draft_with_questions`) opens a review: the person
releases it as it stands, its open questions left in it, or answers it, and the task runs again. A run that
stopped on a missing input that another skill writes (ending `blocked`) opens nothing: the task is `blocked`, with
the start of the reply as its note, until the person retries it.

The layer is seven files (CONS-1B; ADJ-R1 added ops_waits.py; R4-C3 added ops_config.py; PAR-4 added ops_runs.py, the runs of tasks and the dispatcher's round). The names every part shares (the checkout, the refusal, the project's context, the
locks, the runtime's own key, the data-folder names) live once in runtime/ops_core.py and are read as `core.<name>`
at call time, never bound at import, so that a test patching `ops_core.ROOT` reaches every reader. The conversation
(`say`, `chat_memory`) is runtime/ops_say.py and the reads of the local interface (`version`, `agents`, `skills`,
`costs`, `connections`, `artifacts`, ...) are runtime/ops_reads.py; both reach an operation that stays here at call
time, and this file exposes them under their names at its end, so a shell still imports `ops` only. The derived waits
(runtime/ops_waits.py) and the configuration's acceptance (`accept_config`, `set_mode`, the one writer of the accepted hash:
runtime/ops_config.py) reach no operation of this file. A test of size (runtime/tests/test_runtime_rules.py) caps it.

Usage (a library; the shell is runtime/cli.py): python3 runtime/ops.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import ast
import contextlib
import datetime
import hashlib
import json
import os
import re
import sys
import shutil
import subprocess
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ops_core as core  # noqa: E402  (the shared names: read as core.<name>, never bound at import)
import ops_cancel  # noqa: E402  (cancel and stop-task at any moment; a run asks it whether it was stopped; re-exported below)
import ops_reads  # noqa: E402  (the reads of the interface; this file re-exports them at its end)
import ops_runs  # noqa: E402  (the runs of tasks and the dispatcher's round; this file re-exports `run_task`, `dispatch` and `reap`)
import ops_say  # noqa: E402  (the conversation and its queue; this file re-exports `say` at its end)
import sources  # noqa: E402  (limit L26: the protected paths gain the sources folder when it sits inside the project)
import ops_sources  # noqa: E402  (the sources of the project: the ingest operations and the pieces the planner and a run ask of them)
import ops_step_effects  # noqa: E402  (the approval of an effect that a step task opened: the write-back)
import ops_grants  # noqa: E402  (the effect's word and whether it fits on a card: what the channel policy asks of an effect)
import policy_grants  # noqa: E402  (the grants a configuration asks for, the widening list and its hash)
import policy_widening  # noqa: E402  (what a configuration widens over the one accepted before: the cursors config reads)
import ops_actor  # noqa: E402  (who acted: the sender of a messaging app, its profile, and the record of both with a decision)
import ops_config  # noqa: E402  (the configuration's acceptance: accept_config, set_mode, set_model; this file re-exports them at its end)
import ops_models  # noqa: E402  (which model a run goes to: the choice, the key, the billing and the consent)
import ops_waits  # noqa: E402  (the derived waits between requests: rederive, for_plan, annotate, approve_plan)
import ops_language  # noqa: E402  (the language of a deliverable: the check of a request's choice and the line of a run)
import language as language_rules  # noqa: E402  (the rule and the words; the operation `request` has an argument of the same name)
import autonomy  # noqa: E402  (the same folder, as scripts/runtime.py imports runtime_vote)
import board  # noqa: E402
import changeset  # noqa: E402
import deps as deps_sets  # noqa: E402  (the operation `deps` would hide the module: part 0, F.1, rule 5)
import dispatcher  # noqa: E402
import documents  # noqa: E402
import drop  # noqa: E402
import effects  # noqa: E402
import endings  # noqa: E402
import flow_files  # noqa: E402
import isolated  # noqa: E402
import lab  # noqa: E402
import manifest  # noqa: E402
from operations import CHAT_OWN, OPERATIONS  # noqa: E402,F401  (re-exported: a shell reads the table through this module)
import operations  # noqa: E402  (the table of operations; the shells read it through this module: ops.operations)
import parallel  # noqa: E402
import path_rule  # noqa: E402
import plan  # noqa: E402
import progress as progress_calc  # noqa: E402  (the operation `progress` would hide the module: part 0, F.1, rule 5)
import proof as proof_rules  # noqa: E402  (the operation `proof` would hide the module: part 0, F.1, rule 5)
import project_config  # noqa: E402
import router  # noqa: E402
import secret_state  # noqa: E402  (a locked secret store is told apart from a missing key)
import skill_meta  # noqa: E402
import state_merge  # noqa: E402
import workcopy  # noqa: E402

NOTE_LIMIT = 1000        # characters of a failure's reason kept on a task and on a run row
USE_ID = re.compile(r"[0-9a-f]{8}")
VERDICTS = ("worked", "corrected", "failed")
RECORDER_TIMEOUT = 60
ROUTE_KEPT = "a route-only run returns no file"
HANDED_LINE = "The user handed over these files for this task. They are in the project at:"
# One line per document the mirror imported from the platform since the task's last run (decision of 2026-10-06).
EDITED_LINE = "The person edited {path} on the platform since the last run; its content is theirs."
MANDATORY_LINE = ("This delivery is a mandatory milestone: the next task accepts it only with your approval written in "
                  "the document. Write it there, then release.")


def _note(value) -> str:
    """A reason on one record: control characters out, cut to NOTE_LIMIT characters."""
    return core.CONTROL.sub(" ", str(value or "")).strip()[:NOTE_LIMIT] or "no reason given"


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


# --- what enters a run: runtime/workcopy.py (limits L1 to L6) --------------------------------------------------


def task_prompt(request_text: str, task_text: str, answered, handed=None, edited=None, sourced=None, instructions: str = "",
                language_line: str = "") -> str:
    """The text of one run: the request in the person's words, the task's own text, and, on a run made after
    an answer, every earlier question of this task with its answer. It names no skill: the one skill staged
    for the run loads by its description, as in a lab run. An empty task text (a plan of one skill) leaves out
    the "For this task: " paragraph, so the prompt is the plain request. handed lists the relative paths of the
    files the person handed over to this task (the file drop): one paragraph after the task's text names them;
    absent or empty, the prompt is unchanged. edited lists the documents the mirror imported from the platform
    since the task's last run (runtime/documents.py, imported_since): one line each, EDITED_LINE, right before
    the answers, so that the person's edit is read as the person's word and not as external content. sourced lists
    the lines that name the copies of the sources the plan chose (ops_sources.prompt_lines): after the handed files.
    instructions is the person's standing-instructions block (runtime/instructions.py), right after the task's paragraph,
    before the handed files; "" leaves the prompt as it was. Only code gives it, never a run's text. language_line is the paragraph
    that says which language the artifacts are written in (runtime/language.py), right after the task's paragraph and before the
    instructions; the call sites of a task run and of the router's run always give it, "" leaves it out."""
    parts = [request_text.strip()]
    if (task_text or "").strip():
        parts += ["", "For this task: " + task_text.strip()]
    if language_line:
        parts += ["", language_line]
    if instructions:
        parts += ["", instructions]
    if handed:
        parts += ["", HANDED_LINE, *[f"- {rel}" for rel in handed]]
    if sourced:
        parts += ["", *sourced]
    if edited:
        parts += ["", *[EDITED_LINE.format(path=rel) for rel in edited]]
    if answered:
        parts += ["", "In an earlier run of this task you stopped and asked the user. Your replies and the user's "
                      "answers are below, oldest first. Each answer is the user's decision: record it where the "
                      "skill says decisions are recorded, and do not ask it again."]
        for n, item in enumerate(answered, 1):
            parts += ["", f"--- your reply {n} ---", (item.get("body") or "").strip(), "",
                      f"--- the user's answer {n} ---", (item.get("answer") or "").strip()]
    return "\n".join(parts) + "\n"


# --- what comes back: runtime/workcopy.py (limits L7, L8, L12, L14) -------------------------------------------


def _count(value):
    """A count the lab reported, or None when it reported none."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _skill_loaded(timing: dict, skill: str):
    """Whether the run touched the skill: it is in `skills_loaded` (its SKILL.md was read) or in `skills_used` (a tool
    named its folder: a script run, a reference read, a listing; R12). None when the adapter reported neither list.
    No rule reads it yet."""
    lists = [timing.get(key) for key in ("skills_loaded", "skills_used") if isinstance(timing.get(key), list)]
    return any(skill in names for names in lists) if lists else None


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


# --- a use and a verdict, with the existing recorder; the runtime's own key for a model ----------------------------


def _recorder() -> str:
    return core.EVIDENCE or os.path.join(core.ROOT, "scripts", "evidence.py")


def _record(args: list) -> "subprocess.CompletedProcess":
    return subprocess.run([sys.executable, _recorder(), "record", *args], capture_output=True, text=True,
                          timeout=RECORDER_TIMEOUT, check=False)


def _use_start(ctx: dict, run_id: int, skill: str, routing: dict):
    """Record the start of a use of the skill with the recorder, with the model and adapter of the routing (the
    gate file's ids, never a model's own account), and keep its id in the cursor use:<run id>. Returns the id, or
    None when the use could not be recorded: that never stops a run."""
    try:
        done = _record(["--start", "--skill-dir", os.path.join(core.ROOT, "skills", skill), "--project", ctx["cfg"]["project"],
                        "--model", routing["model"], "--adapter", routing["adapter"]])
    except (OSError, subprocess.SubprocessError) as e:
        print(f"the use of run {run_id} could not be recorded: {type(e).__name__}", file=sys.stderr)
        return None
    use = done.stdout.strip()
    if done.returncode != 0 or not USE_ID.fullmatch(use):
        print(f"the use of run {run_id} could not be recorded: {done.stderr.strip()[-500:]}", file=sys.stderr)
        return None
    core._stored(ctx, ctx["store"].cursor_set, f"use:{run_id}", use)
    return use


def _route(ctx: dict, skill: str, meta: dict, keys, task=None, requested=None) -> dict:
    """The routing of one run (runtime/ops_models.py, route): proof.route for the model the request, the task, the agent or the
    project's default chose, with the key found for it (`keys`, ops_core.Keys), named by its source ("runtime" or "lab"), the
    billing of the credential the run would use (core._model_billing: "subscription", "metered", "free", or None when no
    manifest says), which the daily caps count by, and the autonomy of the pair ("proven", "consent" or "supervised")."""
    return ops_models.route(ctx, skill, meta, keys, task, requested)


@contextlib.contextmanager
def _key_in_environment(routing: dict, keys):
    """Around a run on the runtime's own key: the variable the gate file names for the model holds that key, and afterwards
    what was there before (the earlier value, or no variable). Nothing for a run on the lab's key, which the lab passes
    itself."""
    key = keys[routing["model"]]
    if key["source"] != "runtime" or key["value"] is None:
        yield
        return
    name = lab.reference(routing["model"])["pass_env"][0]
    with core._ENV_LOCK:  # the table of what is injected, with the variable itself: a child the dispatcher starts reads both
        before = os.environ.get(name)
        os.environ[name] = key["value"]
        core.ENV_INJECTED[name] = before
    try:
        yield
    finally:
        with core._ENV_LOCK:
            core.ENV_INJECTED.pop(name, None)
            if before is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = before


# --- the operations ----------------------------------------------------------------------------------------


def request(project: str, text: str, flow: str | None = None, title: str | None = None, after: int | None = None,
            model: str | None = None, language: str | None = None) -> dict:
    """Record a request. With a flow, plan it from the flow file the person names (flows/<flow>.json): the tasks
    without a dependency or wait (ops_waits.py) are ready at once, and it returns {"request", "flow", "state", "tasks":
    [{"id", "key", "skill", "state"}], "waits", "missing"}. Without one, the request waits for its route (route()):
    {"request", "state": "requested", "next": "route"}; its title is plan.title_of(text). after: run it after that request.
    model: a model id of the gate file, or "auto", for every task of the request (runtime/ops_models.py: a model named on a
    request has no evidence behind it, so its runs are supervised unless the pair is proven); without one the agent's fixed model,
    the project's default_model, or auto decides. language: the tag the deliverable is written in (runtime/language.py: two lower-case
    letters, optionally a hyphen and two upper-case letters), the person's own choice, recorded here and copied onto each task of
    the plan; without one the project's `language` setting decides (en when none is set)."""
    ctx = core.context(project)
    model = ops_models.check_word(model)
    language = ops_language.checked(language)
    if flow is None:
        said = core._text(text, "the request's text")
        out = core._stored(ctx, ctx["store"].request_add, title=core._text(plan.title_of(said, title),
                                                                 "the title").replace("\n", " "), text=said, after=after,
                           model=model, language=language)
        return {"request": out["request"], "state": out["state"], "next": "route"}
    loaded = ops_flows.direct(ctx, flow)   # a workbench flow of skills with no parameter; any other is planned (route)
    try:
        # A skill whose manifest makes it a mandatory milestone is one whatever the flow file says.
        tasks = [{**t, "milestone": bool(t.get("milestone")) or plan.mandatory(t["skill"], core.ROOT)} for t in loaded["tasks"]]
        language_rules.with_language(tasks, language)
    except manifest.ManifestError as e:
        raise core.OpsError(str(e), 1) from None
    out = ops_waits.request_flow(ctx, tasks, after, title=core._text(title or loaded["title"], "the title").replace("\n", " "),
                                 text=core._text(text, "the request's text"), flow=loaded["flow"], model=model, language=language)
    return {**out, "flow": loaded["flow"]}


def run_next(project: str, model: str | None = None) -> dict:
    """Run the next ready task of the project that the rules of the slots let in, in this process: one skill, once, on the
    model the choice gives (runtime/ops_models.py: the request's, the task's, the agent's fixed model, the project's
    default_model, else `auto`, the cheapest reliable pair). Other tasks may be running meanwhile (runtime/parallel.py decides
    which may). model, a model id of the gate file or "auto", is the person's own choice for this run and wins over all of
    those. Returns {"ran": None, "reason"} when there is nothing to run, else {"ran": task id, "skill",
    "run_id", "run_dir", "status", "ending" or None, "failure" or None, "task_state", "pending_id" or None,
    "returned", "kept", "left_out", "entered": {"kind", "agents_md", "files"} or None, "routing": the
    choice of proof.route, with "key" (the key of the run by name: "runtime" or "lab"), "billing" and "autonomy"
    ("proven", "consent" or "supervised"), or None}; "recovered" names the tasks an interrupted run had left running."""
    return ops_runs.run_next(project, ops_models.check_word(model))


def run_task(project: str, task_id: int, model: str | None = None) -> dict:
    """Run one named task in this process (what the dispatcher starts as a child process of its own, one per task; a
    person uses run_next). It takes the task's lock, ends what dead processes left, and admits and claims the task under
    the claim lock (runtime/ops_runs.py). model is as in run_next. Returns what run_next returns, or {"ran": None, "reason",
    "held"} for a task that was refused: the terminal exits 4 for that, unless the reason is a word of the held tasks
    (runtime/dispatcher.py)."""
    return ops_runs.run_task(project, task_id, requested=ops_models.check_word(model))


def _push_after_run(ctx: dict, out: dict) -> dict:
    """Write to the documents platform the documents a run returned. Never fails the task: a failure is listed."""
    rels = [r["path"] for r in out.get("returned") or [] if r.get("class") == "document"]
    if not rels:
        return documents.result()
    try:
        return documents.push(ctx, rels)
    except Exception as e:  # a failed push never fails the task; the next sync tries again
        return {**documents.result(), "failed": [{"path": rel, "reason": f"{type(e).__name__}: {e}"} for rel in rels]}


# What can go wrong before a run has its row: a skill the runtime knows nothing of, a lab that refuses, a store that does.
PREPARE_ERRORS = (skill_meta.SkillError, manifest.ManifestError, lab.LabError, core.OpsError, OSError, KeyError)


def _prepare_run(ctx: dict, task: dict, requested, keys) -> dict:
    """The slow part of a run's start, made before the claim lock: the skill's meta and manifest (a skill the runtime knows
    nothing of does not run), the routing (ops_models.route with the keys core._keys found, which the caller read from the
    secret store) and the skill's identity. A model with no key is a refusal: the run does not start."""
    skill = task["skill"]
    meta = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))
    known = manifest.load(core.ROOT, skill)
    routing = _route(ctx, skill, meta, keys, task, requested)
    if routing["key_missing"]:
        raise core.OpsError(f"no key was found for {routing['model']}: {keys[routing['model']]['reason']}", 3)
    return {"meta": meta, "known": known, "keys": keys, "routing": routing, "identity": lab.skill_identity(skill),
            "instructions": ops_instructions.guard(ctx, task)}   # the person's standing instructions, read once; a file that fails a check stops the run


def _run_start(ctx: dict, task: dict, prepared: dict) -> dict:
    """The run's start, under the claim lock: its spend limit (before the run's own row: its reservation is not in the
    day's spend yet) and the run row. Returns what _run_body takes."""
    routing, identity = prepared["routing"], prepared["identity"]
    budget = _budget(ctx, task.get("agent"), routing, prepared["keys"])
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
                attempts=attempts, image_digest=digest, run_dir=dest, error=_note(reason), task_note=_note(reason),
                redactions=redactions, **_reported_usage(reported, routing))
        out["failure"] = None if ops_cancel.cancelled_run(out, done) else {"kind": kind, "reason": _note(reason)}   # a stopped run is cancelled whatever it found (R18)
        return out

    out["use"] = _use_start(ctx, run_id, skill, routing)  # one use per run, also for a run made after an answer
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
        prompt = task_prompt(request_text, task["text"], answered,
                             handed=[rel for _source, rel in handed if rel in entered_rels], edited=edited,
                             sourced=[line for line in sourced["lines"] if not line.startswith("- ") or any(f"- {rel} " in line for rel in entered_rels)],
                             instructions=started["instructions"], language_line=ops_language.run_line(cfg, task))
        code = None
        if entered.get("tracked") and code_task(meta):
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
        with lab.session(), _key_in_environment(routing, keys):
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
                    _count(counts.get("redactions")), result.get("reported"))
    left = result["changes"]["created"] + result["changes"]["modified"]
    bound = manifest.bound_among(known, left)
    made = _changeset_of(ctx, task, run_id, dest, result, entered, code, bound) if code is not None else None
    with core._write_lock(cfg, wait=None):  # held from the check of the stop request to the finish: the stop request is written under it (L41)
        if ops_cancel.stop_requested(ctx, task["id"]):   # a stopped run returns nothing
            return fail("stopped", "stopped before it returned anything", counts["attempts"], result["image_digest"], _count(counts.get("redactions")), lab.reported_usage(dest))
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
        every = _reported_usage(lab.reported_usage(dest), routing)  # the usage of every attempt, the retried ones too (R4-C7b)
        finish = dict(status="ok", ending=ending, attempts=counts["attempts"],
                      cost_usd=every.get("cost_usd", number("cost_usd", (int, float)) if routing["billing"] == "metered" else None),
                      tokens=every.get("tokens", number("total_tokens", int)), duration_ms=number("duration_ms", int),
                      skill_loaded=_skill_loaded(timing, skill),
                      image_digest=result["image_digest"], run_dir=dest, redactions=_count(counts.get("redactions")))
        if ending == "blocked":
            # The skill stopped on a missing input that another skill writes: the task is blocked, with no pending
            # decision; the note is the first sentence of the masked reply that names the missing input (else its start),
            # and `retry` makes the task ready again.
            sentence = endings.missing_input_line(body, manifest.ending_facts(core.ROOT, skill))
            done = core._stored(ctx, store.task_run_finish, run_id, task_state="blocked", task_note=_note(sentence or body), **finish)
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


def _reported_usage(reported, routing: dict) -> dict:
    """The usage a failed run's attempts reported (lab.reported_usage), as the arguments that record it: tokens always, the
    cost only on a metered credential (only a metered run has a billed cost, as for a run that ended). Nothing when none
    was reported, so a failed run with a reported cost keeps it and the reservation does not stand in for it (A-57)."""
    reported = reported or {}
    out = {}
    if reported.get("total_tokens") is not None:
        out["tokens"] = int(reported["total_tokens"])
    if reported.get("cost_usd") is not None and routing.get("billing") == "metered":
        out["cost_usd"] = float(reported["cost_usd"])
    return out


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


def _provider_path(cfg: dict, cls: str, platform: str | None = None) -> str:
    """The provider script of a class, found through providers/resolve.py, with the implementation the configuration
    names for the code provider (code.provider) when the class is integration:vcs; never a path built here. A class
    with a parameter (publisher:<platform>) is written with its placeholder and resolved with the platform the kind
    names: the platform is part of the class, never a second argument of the resolver. A placeholder without a
    platform, and a platform for a class that takes none, are refused."""
    resolve = core._load("workbench_provider_resolve", os.path.join(core.ROOT, "providers", "resolve.py"))
    if bool(resolve.PLACEHOLDER.search(cls)) != (platform is not None):
        raise core.OpsError(f"the class {cls} and the platform {platform!r} do not fit: a class written with a placeholder "
                       f"needs a platform, and no other takes one", 3)
    if platform is not None:
        if not isinstance(platform, str) or not resolve.NAME.fullmatch(platform):  # the resolver's own name rule, before it is part of a class
            raise core.OpsError(f"the platform {platform!r} is not a name (lowercase letters, digits and hyphens)", 3)
        cls = resolve.PLACEHOLDER.sub(lambda _: platform, cls)
    implementation = cfg["code"]["provider"] if cls == "integration:vcs" and cfg.get("code") else None
    try:
        return resolve.resolve(cls, root=core.ROOT, implementation=implementation)["path"]
    except (resolve.UnknownClass, resolve.Unresolved) as e:
        raise core.OpsError(f"the {'code ' if cls == 'integration:vcs' else ''}provider does not resolve: {e}", 3) from None


def _approve_effect(ctx: dict, item: dict, sha256, actor=None) -> dict:
    """approve() for an `effect`: the approval row, then, holding the write lock, the checks and the execution by code,
    then the effect is done and the state file gets the generated row. Refused, before anything is executed, while a code
    task of the effect's request is running (the checks read the project's tracked files and the request's change set)."""
    store, cfg, pending_id = ctx["store"], ctx["cfg"], item["id"]
    if sha256 is None:
        raise core.OpsError(f"pending decision {pending_id} is an effect: approve it with --sha256 <the hash shown with it>", 2)
    if sha256 != item["payload_sha256"]:
        raise core.OpsError(f"the effect's hash is {item['payload_sha256']} and you typed {sha256}: nothing was approved", 1)
    if item["status"] != "open":
        raise core.OpsError(f"pending decision {pending_id} is {item['status']}, not open", 1)
    request_id = core._stored(ctx, store.task_get, item["task_id"])["parent_id"]
    stepped = ops_step_effects.step_effect_of(ctx, item)   # an effect a step task's gate opened (P8): its own execution
    with core._effect_lock(cfg, request_id):
        try:  # a second queued approval of the same effect must not execute it again: read the decision now, under the lock
            fresh = core._stored(ctx, store.pending_get, pending_id)
        except core.OpsError:
            fresh = item
        if fresh["status"] != "open":
            raise core.OpsError(f"pending decision {pending_id} is {fresh['status']}, not open: nothing was executed", 1)
        if stepped is not None:
            return _approve_step_effect(ctx, fresh, sha256, stepped, actor)
        # from here a code task of the request is not claimed (admit reads this lock)
        if request_id is not None:
            with core._claim_lock(cfg):  # a claim happens under this lock: either the code task is seen here or the lock is seen there
                if ops_runs.code_running(ctx, request_id):
                    raise core.OpsError("a code task of this request is running; approve when it ends", 1)
        return _execute_effect(ctx, item, sha256, actor)


def _approve_step_effect(ctx: dict, item: dict, sha256, stepped, actor=None) -> dict:
    """approve() for an `effect` that a step task's gate opened (package P8): runtime/ops_step_effects.py checks and executes it with the
    person's approval of the hash; here the state file gets the generated row of the executed approval, as for any effect."""
    done = ops_step_effects.approve(ctx, item, sha256, stepped, actor=actor)
    row = effects.approval_row(core._stored(ctx, ctx["store"].approval_get, done["approval"]["id"]), done["doc"])
    return {**done["done"], "approval_id": done["approval"]["id"], "result": done["result"],
            "state": _write_approval_row(ctx["cfg"], row)}


def _execute_effect(ctx: dict, item: dict, sha256, actor=None) -> dict:
    """The rest of _approve_effect, with the request's effect lock held: the document, the approval row, the checks and the
    execution under the write lock."""
    store, cfg, pending_id = ctx["store"], ctx["cfg"], item["id"]
    payload = item.get("payload") or {}
    try:
        with open(payload["effect_file"], "rb") as f:
            doc = json.loads(f.read().decode("ascii"))
        kind = effects.module_for(doc["effect"])
        if getattr(kind, "GATE", False) is not True:
            raise effects.EffectError("usage", f"the effect kind {doc['effect']!r} is not one a confirmation gate opens")
    except (OSError, KeyError, ValueError) as e:
        raise core.OpsError(f"the effect document of pending decision {pending_id} cannot be read: {e}", 1) from None
    except effects.EffectError as e:
        raise core.OpsError(f"the effect of pending decision {pending_id} cannot be approved: {e.reason}", 1) from None
    if kind.unconfigured(cfg):
        raise core.OpsError(kind.unconfigured(cfg), 3)
    what = kind.describe(doc)
    approval = core._stored(ctx, store.approval_add, scope="action", what=" ".join(what.split())[:1000], by="user",
                       payload_sha256=sha256, pending_id=pending_id, actor=actor)
    with core._write_lock(cfg):
        try:
            made = changeset.load(os.path.dirname(payload["changeset_dir"]))
            if made is None:
                raise effects.EffectError("deviation", "the change set is no longer in its run folder")
            paths = [f["path"] for f in made["files"]] + list(made["removed"])
            facts = {"versioned": changeset.versioned_in(cfg["project"], paths)}
            doc = kind.verify(effects.read_document(payload["effect_file"], sha256), made, facts, sources.protected_paths(cfg))
            key_prefix = f"wb-{hashlib.sha256(cfg['store_db'].encode('utf-8')).hexdigest()[:12]}-p{pending_id}"
            result = kind.execute(doc, made["dir"], os.path.join(cfg["data_dir"], core.EFFECTS_DIR, str(pending_id)),
                                  _provider_path(cfg, kind.PROVIDER_CLASS), key_prefix)
        except (effects.EffectError, changeset.ChangesetError) as e:
            raise core.OpsError(f"nothing was sent: {e.reason}; the effect stays open, and approving it again with the same "
                           f"hash tries again", 3 if getattr(e, "kind", "") == "not-configured" else 1) from None
        done = core._stored(ctx, store.effect_done, pending_id, approval["id"], by="user", result=result, actor=actor)
    row = effects.approval_row(core._stored(ctx, store.approval_get, approval["id"]), doc)
    return {**done, "approval_id": approval["id"], "commit": result["commit"], "pull_request": result["pull_request"],
            "replayed": result["replayed"], "state": _write_approval_row(cfg, row)}


def _write_approval_row(cfg: dict, row: list) -> dict:
    """The generated row in the state file's ## Approvals table (state_merge.write_generated), only when the file did
    not change between its read and the write (L12); otherwise it is written at the next write."""
    target = os.path.join(cfg["project"], *path_rule.STATE.split("/"))
    with core._write_lock(cfg):
        if not os.path.isfile(target) or os.path.islink(target):
            return {"written": False, "reason": "the project has no state file"}
        before = _sha256(target)
        try:
            text = state_merge.write_generated(_read(target), [row])
        except state_merge.Conflict as e:
            return {"written": False, "reason": str(e)}
        if _sha256(target) != before:
            return {"written": False, "reason": "the state file changed while the row was being written; it is written at the next write"}
        temporary = f"{target}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, target)
        return {"written": True}


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


def code_task(meta: dict) -> bool:
    """A code task: its skill is of a code area (workcopy.CODE_AREAS, the areas of the code-change flow's skills).
    Only a code task whose copy holds versioned files is held to clean tracked files and makes a change set
    (choice K4); a document task runs on a project whose tracked files carry uncommitted changes (a project
    initialised by core-project-init always has two), and a versioned file it changed is listed in `kept`."""
    return meta.get("area") in workcopy.CODE_AREAS


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


def deps(project: str) -> dict:
    """Install every dependency set the project's configuration declares, by code, with no model: {"dependencies":
    [{"recipe", "file", "applies", and when it applies "key", "cached", "duration_ms"}]}. A set whose files are not
    all in the project does not apply and installs nothing. It takes no project lock: an install that a run makes at the
    same time takes the same lock per cache key (runtime/deps.py), so the two never install one set twice."""
    ctx = core.context(project)
    cfg, out = ctx["cfg"], []
    for entry in cfg.get("dependencies") or []:
        files = deps_sets.files_for(entry, lambda rel: _project_bytes(cfg["project"], rel))
        row = {"recipe": entry["recipe"], "file": entry["file"], "applies": files is not None}
        if files is not None:
            try:
                done = deps_sets.ensure(cfg["data_dir"], entry, files, lab.image()["digest"])
            except deps_sets.DepsError as e:
                raise core.OpsError(f"dependencies: {e.reason}", 1) from None
            except lab.LabError as e:
                raise core.OpsError(f"dependencies: {e.kind}: {e.reason}", 1) from None
            row.update(key=done["key"], cached=done["cached"], duration_ms=done["duration_ms"])
        out.append(row)
    return {"dependencies": out}


EFFECT_APPROVED = "approved"  # the word of an effect that code executed: the store takes it from effect_done only


def _actions(store, item: dict) -> list:
    """The resolution words the store allows for an open pending decision of this kind, in the store's order, built
    from its own tables and from no table of this layer: a plan and an acceptance take the words of
    store.KIND_RESOLUTIONS; an effect is approved (effect_done's word, after code executed it) or rejected, and its
    comment (`answered`) is not offered as a button; a review takes every word of store.RESOLUTIONS, a question every
    word but the release only a review takes; a `your_document` takes none until the stage that builds its delivery.
    A decision that is not open takes none. The word-to-operation map belongs to the shell."""
    if item.get("status", "open") != "open":
        return []
    kind = item["kind"]
    words = [word for (of, word) in store.KIND_RESOLUTIONS if of == kind]
    if words:
        return words
    if kind == "effect":
        words = [EFFECT_APPROVED]
        words += [word for word in store.EFFECT_RESOLUTIONS if word != "answered"]
        return words
    if kind == "your_document":
        return []
    return [word for word in store.RESOLUTIONS if word != "released" or kind in store.RELEASABLE_KINDS]


def _agent_by_task(rows: list) -> dict:
    """{task id: the area agent the store recorded for it} for the tasks of a plan; a request has no agent, so it is
    not in the map, and a task of a project without area agents has None."""
    return {t["id"]: t.get("agent") for t in rows if t["parent_id"] is not None}


def _listed(item: dict, store=None, agents: dict | None = None) -> dict:
    """One pending decision as a list shows it; a plan also shows its tasks and the hash the person approves. With the
    store, also the words it may be resolved with (`actions`). With agents (_agent_by_task), also `agent`: the area
    agent of the decision's task, None for a decision on a request and when the project has no area agents."""
    out = {key: item[key] for key in ("id", "kind", "title", "task_id", "created_at")}
    if agents is not None:
        out["agent"] = agents.get(item["task_id"])
    if store is not None:
        out["actions"] = _actions(store, item)
    if item["kind"] == "plan":
        payload = item.get("payload") or {}
        out["plan"] = {"tasks": [{"key": t.get("key"), "skill": t.get("skill")} for t in payload.get("tasks") or []],
                       "plan_sha256": payload.get("plan_sha256")}
    return out


def pending(project: str, pending_id: int | None = None, channel: str | None = None, sender: str | None = None, reader: str | None = None) -> dict:
    """What waits for the person. Without an id: {"pending": [{"id", "kind", "title", "task_id", "agent",
    "created_at"}]}, oldest first, a plan with its tasks and its hash ("plan"). With one: that pending decision whole,
    with its body (the reply, or the plan's table) and its payload. Either way each carries "actions", the resolution
    words the store allows for it now (_actions), and "agent", the area agent of its task as the store recorded it
    (None for a decision on a request, such as a plan or a router question, and when the project has no area
    agents)."""
    ctx = core.context(project)
    agents = _agent_by_task(core._stored(ctx, ctx["store"].tasks_list))
    if pending_id is not None:
        item = core._stored(ctx, ctx["store"].pending_get, pending_id)
        known = ops_grants.effect_facts(ctx, item) if item["kind"] == "effect" else None   # POL-1: the word the policy is asked about, and whether a card can hold all of it
        return {**ops_grants.private_view(ctx, ops_actor.shown(item), channel, sender), "agent": agents.get(item["task_id"]), "actions": _actions(ctx["store"], item),
                **({"effect_word": known["word"], "effect_on_cards": known["on_cards"]} if known else {}),
                **(ops_grants.save_facts(ctx, item, reader) if known else {}),      # W4a: booleans for the card of a save of a held file; never the sender's id
                **({"plan_networked": bool(ops_waits.networked_steps(item))} if item["kind"] == "plan" else {})}   # a plan with a networked step needs a whole card to be approved off the terminal and the page
    return {"pending": [_listed(item, ctx["store"], agents) for item in core._stored(ctx, ctx["store"].pending_list)]}


COMMENTS_LINE = "Comments left on the platform:"
# An answer that is only one of these words would reach the resumed skill as its "yes": an effect is approved by hash.
APPROVAL_WORDS = re.compile(r"(?i)(yes|y|ok|okay|approved|approve|proceed|go)\.?")


def answer(project: str, pending_id: int, text: str, with_comments: bool = False, channel: str | None = None, sender: str | None = None,
           actor: str | None = None) -> dict:
    """Answer a pending decision. The task becomes ready, and its next run is given the answer. The answer to a
    question is also written by code into the project's state file, as a decision of the user (L10), so that the
    next run finds it where the skills look for decisions; "state" says whether it was written. A failure there
    never undoes the answer: the store has it, and the next run's prompt carries it. With with_comments (the
    person's command, never a default), the open comments saved from the platform for the task, and for the
    documents its skill owns (its declared outputs), are appended under COMMENTS_LINE, one per line, oldest first,
    and marked used by this pending decision ("comments": their ids)."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "answer", channel, sender)
    said = core._text(text, "the answer")
    if core._stored(ctx, ctx["store"].pending_get, pending_id)["kind"] == "effect" and \
            APPROVAL_WORDS.fullmatch(said.strip()):
        raise core.OpsError(f"pending decision {pending_id} is an effect: an approval is given with approve --id {pending_id} "
                       "--sha256 <its hash>, never as an answer (the next run would read it as the skill's yes)", 2)
    used = []
    if with_comments:
        item = core._stored(ctx, ctx["store"].pending_get, pending_id)
        saved = core._stored(ctx, ctx["store"].comments_list, task_id=item["task_id"])
        skill = core._stored(ctx, ctx["store"].task_get, item["task_id"])["skill"]
        if skill:
            try:
                owned = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))["outputs"]
            except skill_meta.SkillError as e:
                raise core.OpsError(f"the comments of {skill}'s documents cannot be found: {e}", 1) from None
            saved += [c for c in core._stored(ctx, ctx["store"].comments_list)
                      if c.get("document_path") and skill_meta.matches(owned, c["document_path"])]
            saved.sort(key=lambda c: c["id"])
        if saved:
            lines = [f"- {c.get('author') or 'unknown'}: {' '.join(str(c['text']).split())}" for c in saved]
            said = "\n".join([said, "", COMMENTS_LINE, *lines])
            used = [c["id"] for c in saved]
    with ops_step_effects.resolution_guard(ctx, core._stored(ctx, ctx["store"].pending_get, pending_id)):    # not while its write runs
        out = core._stored(ctx, ctx["store"].pending_resolve, pending_id, resolution="answered", by="user", answer=said,
                           actor=actor or ops_actor.label(ctx["cfg"], channel, sender))
    if used:
        core._stored(ctx, ctx["store"].comments_use, used, pending_id=pending_id)
        out = {**out, "comments": used}
    item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    if item["kind"] != "question":
        return out
    if core._stored(ctx, ctx["store"].task_get, item["task_id"])["parent_id"] is None:
        # A question of the router, on a request: the answer is given to the router's next run (route()), and is not
        # recorded as a decision of a skill.
        return {**out, "state": {"written": False, "reason": "an answer to the router is given to its next run, "
                                                               "not recorded as a decision"}}
    target = os.path.join(ctx["cfg"]["project"], *path_rule.STATE.split("/"))
    skill = core._stored(ctx, ctx["store"].task_get, item["task_id"])["skill"]
    try:
        with core._write_lock(ctx["cfg"]):
            current = _read(target) if os.path.isfile(target) and not os.path.islink(target) else None
            if current is None:
                return {**out, "state": {"written": False, "reason": "the project has no state file"}}
            try:
                text_after = state_merge.with_answer(current, date=datetime.date.today().isoformat(), skill=skill,
                                                     pending_id=pending_id, answer=said)
            except state_merge.Conflict as e:
                return {**out, "state": {"written": False, "reason": str(e)}}
            temporary = f"{target}.{os.getpid()}.tmp"
            with open(temporary, "w", encoding="utf-8") as f:
                f.write(text_after)
            os.replace(temporary, target)
    except core.OpsError as e:  # the files stayed busy: the answer is in the store and the next run's prompt carries it
        return {**out, "state": {"written": False, "reason": str(e)}}
    return {**out, "state": {"written": True}}


def release(project: str, pending_id: int, channel: str | None = None, sender: str | None = None) -> dict:
    """Release a delivery (a pending decision of kind review). The task is done; the tasks that depended on it
    become ready. The delivery stays a draft: releasing is not approving. What a release starts (stage 6,
    _after_release) follows in the same call: the brief's delivery routed again (one run of the router, holding the
    route lock, so the release is refused while the router answers another request), the backlog's sub-tasks; its result is
    under "after"."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "release", channel, sender)
    return _release(ctx, pending_id, by="user", actor=ops_actor.label(ctx["cfg"], channel, sender))


def _release(ctx: dict, pending_id: int, by: str, actor=None) -> dict:
    """pending_resolve(released) and then _after_release, for the person (by "user") and for a mode ("mode:<mode>")."""
    item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    made = (item.get("payload") or {}).get("changeset") or {}
    if item["kind"] == "review" and made.get("blocked"):
        refused = "; ".join(f"{r['path'] or 'the whole set'}: {r['reason']}" for r in made.get("refused") or [])
        raise core.OpsError(f"pending decision {pending_id}: its change set is blocked ({refused}): answer with what to change, "
                       "or cancel the request", 1)
    task = core._stored(ctx, ctx["store"].task_get, item["task_id"])
    lock = core._route_lock(ctx["cfg"]) if item["kind"] == "review" and _brief_delivery(ctx, task) else contextlib.nullcontext()
    with lock:
        out = ops_waits.settled(ctx, core._stored(ctx, ctx["store"].pending_resolve, pending_id, resolution="released", by=by, actor=actor))
        after = _after_release(ctx, item)
    return {**out, "after": after} if after else out


def retry(project: str, task_id: int, channel: str | None = None, sender: str | None = None) -> dict:
    """Make a failed or blocked task ready again. From a messaging app the sender's profile must cover `retry` (a task row has no actor: nothing is recorded)."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "retry", channel, sender)
    return ops_waits.retry(ctx, task_id)


def go_ahead(project: str, task_id: int, drop_after: bool = False) -> dict:
    """Go ahead on a task that waits for another request's task, or with drop_after on its `after` wait."""
    return ops_waits.go_ahead(core.context(project), task_id, drop_after)


def proof(project: str, skill: str | None = None) -> dict:
    """The model each skill would run on now when nothing chooses one (the project's default_model, else `auto`), by its proof,
    with the two checks and the band of the skill on every model: {"skills": {name: proof.route(...) with "key", "billing" and
    "autonomy", and "pairs": [one per model: the pair's figures, its price with its source, date and whether it is stale, its
    expected cost per run, and the source of its evidence], "recommended": the model `auto` would choose or None}}, for the
    named skill or for every skill of the packs in use (manifest.skills_in_use). It calls no model; it refreshes the proof file
    <data_dir>/proof.json where its inputs changed."""
    ctx = core.context(project)
    names = [skill] if skill else manifest.skills_in_use(core.ROOT)
    keys, out = core._keys(), {}
    for name in names:
        try:
            meta = skill_meta.declared(os.path.join(core.ROOT, "skills", name))
            read = ops_models.models_read(ctx, name)
            out[name] = {**_route(ctx, name, meta, keys), "pairs": read["pairs"], "recommended": read["recommended"]}
        except (skill_meta.SkillError, lab.LabError, OSError, KeyError) as e:
            raise core.OpsError(f"the proof of {name} cannot be read: {e}", 1) from None
    return {"skills": out}


def verdict(project: str, run_id: int, word: str) -> dict:
    """Record the person's verdict on the use of one run, with the recorder (scripts/evidence.py record --verdict):
    {"run_id", "use", "verdict"}. word is worked, corrected or failed. One verdict per run. The verdict is the
    person's: no code path calls this by itself, and nothing reads a verdict out of a model's reply."""
    if word not in VERDICTS:
        raise core.OpsError(f"a verdict is one of {', '.join(VERDICTS)}", 2)
    ctx = core.context(project)
    use = core._stored(ctx, ctx["store"].cursor_get, f"use:{run_id}")
    if not use:
        raise core.OpsError(f"run {run_id} has no recorded use", 1)
    given = core._stored(ctx, ctx["store"].cursor_get, f"verdict:{run_id}")
    if given:
        raise core.OpsError(f"run {run_id} already has the verdict {given}", 1)
    try:
        done = _record(["--verdict", word, "--use", use, "--project", ctx["cfg"]["project"]])
    except (OSError, subprocess.SubprocessError) as e:
        raise core.OpsError(f"the recorder could not be run: {type(e).__name__}", 1) from None
    if done.returncode != 0:
        lines = done.stderr.strip().splitlines()
        raise core.OpsError(lines[-1] if lines else f"the recorder exited {done.returncode}", 1)
    core._stored(ctx, ctx["store"].cursor_set, f"verdict:{run_id}", word)
    return {"run_id": run_id, "use": use, "verdict": word}


POLICY_EXPIRY_DAYS = 365  # a standing approval always has an expiry, at most this far ahead


def _policy_file(cfg: dict, file: str) -> tuple:
    """(relative path, absolute path) of a policy file: under docs/, a regular file whose real path is inside the
    project; else OpsError 2."""
    rel = (file or "").replace("\\", "/")
    parts = rel.split("/")
    if not rel or rel.startswith(("/", "~")) or any(p in ("", ".", "..") for p in parts) or parts[0] != "docs":
        raise core.OpsError(f"{file!r} is not a relative path under docs/ of the project", 2)
    target = os.path.join(cfg["project"], *parts)
    real = os.path.realpath(target)
    if not (real.startswith(cfg["project"] + os.sep)) or os.path.islink(target) or not os.path.isfile(real):
        raise core.OpsError(f"{rel} is not a regular file inside the project", 2)
    return rel, real


SIDE_EFFECTS_LINE = re.compile(r"^SIDE_EFFECTS = \(([^)]*)\)", re.M)


def _effect_words() -> tuple:
    """The closed vocabulary of side effects (contracts/environment.md), read from its one source in code, SIDE_EFFECTS
    of the checkout's scripts/validate.py, so the runtime keeps no copy of it."""
    found = SIDE_EFFECTS_LINE.search(_read(os.path.join(core.ROOT, "scripts", "validate.py")) or "")
    if not found:
        raise core.OpsError("the vocabulary of side effects (SIDE_EFFECTS of scripts/validate.py) cannot be read", 1)
    return tuple(word.strip().strip('"') for word in found.group(1).split(",") if word.strip())


def _bounds_words() -> tuple:
    """The side-effect words a standing approval's bounds may name: the vocabulary without the kinds that only a step task opens
    (effects.step_only_words: STEP and not POLICY): a write-back is approved by the hash of its exact content each time, and no bound covers it. The
    words of a write to the person's own accounts (project_config.ACCOUNT_EFFECT_WORDS) are never a bound's, whether or not their kind is registered yet."""
    return tuple(w for w in _effect_words() if w not in effects.step_only_words() and w not in project_config.ACCOUNT_EFFECT_WORDS)


def _policy_bounds(rel: str, real: str, agent: str) -> dict:
    """The bounds an approval of this file stores: a bounds file (.json) checked whole; else, for a Markdown policy that
    holds an ```engagement-policy block, the bounds derived from that block by code (autonomy.block_bounds: effects
    publish, the class of own published posts, the block's daily cap, one item a run); else {"policy": <file name
    without extension>, "agent"} (a file a skill's own gate reads). With "file", the path the approval binds: the
    file's hash binds the block too, so a changed block is derived again at the next approval."""
    name = os.path.splitext(os.path.basename(rel))[0]
    if rel.endswith(".json"):
        try:
            with open(real, encoding="utf-8") as f:
                data = json.load(f)
            bounds = autonomy.bounds_of(data, agent, _bounds_words())
        except (OSError, ValueError) as e:
            raise core.OpsError(f"{rel} is not a bounds file: {e}", 2) from None
    else:
        try:
            bounds = autonomy.block_bounds(name, _read(real) or "", agent)
        except ValueError as e:
            raise core.OpsError(f"{rel}: {e}", 2) from None
        bounds = bounds or {"policy": name, "agent": agent}
    return dict(bounds, file=rel)


def _standing_rows(ctx: dict) -> dict:
    """Write the standing rows of the state file from the store (state_merge.write_standing): one per policy file
    hash, the active approval else the newest expired one; only when the file did not change between its read and
    the write (L12). Returns {"state_rows", "superseded_rows"}, or {"written": false, "reason"}."""
    # T23: workaround 5, the copy a skill's gate reads until it reads the runtime's record
    cfg = ctx["cfg"]
    target = os.path.join(cfg["project"], *path_rule.STATE.split("/"))
    with core._write_lock(cfg):
        if not os.path.isfile(target) or os.path.islink(target):
            return {"written": False, "reason": "the project has no state file"}
        every = core._stored(ctx, ctx["store"].approvals_list, scope="standing")
        chosen = {}
        for row in every:
            if row["status"] not in ("active", "expired"):
                continue
            held = chosen.get(row["policy_sha256"])
            rank = lambda r: (r["status"] == "active", r["id"])  # the active one, else the newest
            if held is None or rank(row) > rank(held):
                chosen[row["policy_sha256"]] = row
        rows = [["standing", f"{row['what']} (runtime #{row['id']})", f"policy:{row['policy_sha256']}",
                 row["approved_at"][:10], (row["expires_at"] or "")[:10], row["status"]]
                for row in sorted(chosen.values(), key=lambda r: r["id"])]
        before = _sha256(target)
        try:
            text, written, superseded = state_merge.write_standing(
                _read(target), rows, {f"policy:{row['policy_sha256']}" for row in every if row["policy_sha256"]})
        except state_merge.Conflict as e:
            return {"written": False, "reason": str(e)}
        if _sha256(target) != before:
            return {"written": False, "reason": "the state file changed while the rows were being written; they are written at "
                                                "the next write"}
        temporary = f"{target}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(temporary, target)
        return {"state_rows": written, "superseded_rows": superseded}


def approve_policy(project: str, file: str, agent: str, sha256: str | None = None, expires: str | None = None,
                   what: str | None = None) -> dict:
    """A standing approval of a policy file for one area agent (limits L15, L17; contracts/environment.md, rule 7).
    Without sha256: a preview ({"file", "agent", "policy", "bounds", "sha256", "next"}), nothing written. With it:
    refused unless it is the file's hash now and expires is a date YYYY-MM-DD after today and at most 365 days ahead;
    then, in one transaction, an active approval of the same policy and agent is revoked and the new row added, and
    the state file's generated standing rows are rewritten. Never granted by default, never without an expiry."""
    ctx = core.context(project)
    cfg = ctx["cfg"]
    if agent not in cfg["area_agents"]:
        raise core.OpsError(f"{agent!r} is not an agent of area_agents in {cfg['path']}", 2)
    rel, real = _policy_file(cfg, file)
    bounds = _policy_bounds(rel, real, agent)
    now_hash = _sha256(real)
    if sha256 is None:
        return {"file": rel, "agent": agent, "policy": bounds["policy"], "bounds": bounds, "sha256": now_hash,
                "next": f"approve-policy --file {rel} --agent {agent} --sha256 {now_hash} --expires <YYYY-MM-DD>"}
    if sha256 != now_hash:
        raise core.OpsError(f"{rel} has the hash {now_hash} now, not {sha256}: nothing was approved", 1)
    today = datetime.date.today()
    try:
        until = datetime.date.fromisoformat(str(expires)) if isinstance(expires, str) and len(expires) == 10 else None
    except ValueError:
        until = None
    if until is None or until <= today or until > today + datetime.timedelta(days=POLICY_EXPIRY_DAYS):
        raise core.OpsError(f"a standing approval needs --expires, a date YYYY-MM-DD after today and at most "
                       f"{POLICY_EXPIRY_DAYS} days ahead: nothing was approved", 1)
    row = core._stored(ctx, ctx["store"].approval_standing_add, what=core._text(what or bounds["policy"], "what"), by="user",
                  policy_sha256=now_hash, bounds=bounds, expires_at=f"{until.isoformat()}T23:59:59Z")
    return {**row, **_standing_rows(ctx)}


def revoke_policy(project: str, approval_id: int) -> dict:
    """End a standing approval: the row becomes revoked and its generated row leaves the state file."""
    ctx = core.context(project)
    item = core._stored(ctx, ctx["store"].approval_get, approval_id)
    if item["scope"] != "standing" or item["status"] != "active":
        raise core.OpsError(f"approval {approval_id} is not an active standing approval", 2)
    row = core._stored(ctx, ctx["store"].approval_revoke, approval_id, by="user")
    return {**row, **_standing_rows(ctx)}


def _policy_hash(cfg: dict, approval: dict):
    """The hash of the bounds file an approval was given to, as it is now (None when the file is gone)."""
    rel = (approval.get("bounds") or {}).get("file")
    return _sha256(os.path.join(cfg["project"], *rel.split("/"))) if rel else None


def _standing(ctx: dict, policy: str) -> dict:
    """The answer of standing(): whether an active standing approval covers a policy now. Reads, executes nothing."""
    cfg = ctx["cfg"]
    now = datetime.datetime.now(datetime.timezone.utc)
    active = core._stored(ctx, ctx["store"].approvals_list, status="active", scope="standing")
    found = [row for row in active if (row.get("bounds") or {}).get("policy") == policy]
    approval = found[-1] if found else None
    executed = core._stored(ctx, ctx["store"].action_count, kind=policy, since=core._midnight())
    out = {"policy": policy, "covered": False, "why": "", "approval": None, "executed_today": executed, "mode": None}
    if approval is None:
        return {**out, "why": "no active standing approval names this policy"}
    agent = approval["bounds"].get("agent")
    out["approval"] = {key: approval.get(key) for key in ("id", "expires_at", "policy_sha256", "bounds")}
    out["approval"]["agent"] = agent
    out["mode"] = autonomy.mode_of(autonomy.facts(agent, cfg["area_agents"], active, now))
    if _policy_hash(cfg, approval) != approval["policy_sha256"]:
        return {**out, "why": "the policy file changed since it was approved, or is gone"}
    if datetime.datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00")) <= now:
        return {**out, "why": "the approval expired"}
    if out["mode"] != autonomy.POLICY_MODE:
        return {**out, "why": f"the agent {agent} acts in the mode {out['mode']}, not {autonomy.POLICY_MODE}"}
    return {**out, "covered": True}


def standing(project: str, policy: str) -> dict:
    """Whether an active standing approval covers a policy now: a read, it executes nothing. covered is true only
    when the row exists, its file hashes as approved, it has not expired and its agent acts in the mode
    autonomous-with-policy. executed_today counts today's actions of kind <policy> (the store's action_count)."""
    return _standing(core.context(project), policy)


def _effect_document(path: str, policy: str) -> dict:
    """The effect document a handler hands over, checked whole: exactly EFFECT_KEYS, the right types, the policy it
    was called for, a kind of the side-effect vocabulary whose module (effects.KINDS) may run under a policy, no
    reserved flag among args."""
    try:
        with open(path, "rb") as f:
            doc = json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        raise core.OpsError(f"the effect file cannot be read: {type(e).__name__}", 2) from None
    if not isinstance(doc, dict):
        raise core.OpsError("an effect file holds one JSON object", 2)
    for key in effects.EFFECT_KEYS:
        if key not in doc:
            raise core.OpsError(f"the effect file lacks the key {key}", 2)
    unknown = sorted(set(doc) - set(effects.EFFECT_KEYS))
    if unknown:
        raise core.OpsError(f"the effect file has the unknown key {unknown[0]} (known: {', '.join(effects.EFFECT_KEYS)})", 2)
    for key in ("policy", "kind", "target", "idempotency_key", "payload_sha256"):
        if not isinstance(doc[key], str) or not doc[key].strip():
            raise core.OpsError(f"{key} of the effect file is a non-empty text", 2)
    for key in ("files", "args"):
        if not isinstance(doc[key], list) or not all(isinstance(v, str) for v in doc[key]):
            raise core.OpsError(f"{key} of the effect file is a list of texts", 2)
    if isinstance(doc["items"], bool) or not isinstance(doc["items"], int) or doc["items"] < 0:
        raise core.OpsError("items of the effect file is a whole number", 2)
    if len(doc["target"]) > 512 or len(doc["idempotency_key"]) > 512:  # what the store can record: refused before anything runs
        raise core.OpsError("target and idempotency_key of the effect file are at most 512 characters", 2)
    if not re.fullmatch(r"[0-9a-f]{64}", doc["payload_sha256"]):
        raise core.OpsError("payload_sha256 of the effect file is 64 lowercase hexadecimal characters", 2)
    if doc["policy"] != policy:
        raise core.OpsError(f"the effect file is for the policy {doc['policy']!r}, not {policy!r}", 2)
    if doc["kind"] not in _effect_words():
        raise core.OpsError(f"kind of the effect file is one of {', '.join(_effect_words())}", 2)
    can = effects.policy_kinds()
    if doc["kind"] not in can:
        raise core.OpsError(f"the effect kind {doc['kind']!r} cannot run under a policy (it can: {', '.join(can)})", 2)
    reserved = [a for a in doc["args"] if a in effects.RESERVED_FLAGS]
    if reserved:
        raise core.OpsError(f"args of the effect file holds {reserved[0]}: the operation adds it, the handler never does", 2)
    module = effects.module_for(doc["kind"])
    try:  # the kind reads its own document: one that does not fit it is refused before anything else is checked
        module.policy_platform(doc), module.policy_effect(doc), module.policy_argv(doc)
    except effects.EffectError as e:
        raise core.OpsError(f"the effect file does not fit the effect kind {doc['kind']!r}: {e.reason}", 2) from None
    return doc


def _resolve_call(cls: str, verb: str, args: list) -> dict:
    """What a kind's resolve_targets is handed to read a recorded fact: one verb of the provider of a class, through
    providers/resolve.py, the one JSON object it printed; effects.EffectError when it fails."""
    resolve = core._load("workbench_provider_resolve", os.path.join(core.ROOT, "providers", "resolve.py"))
    try:
        return resolve.call(cls, verb, args, root=core.ROOT)
    except resolve.ProviderCallError as e:
        raise effects.EffectError("provider", f"{verb}: {e.reason}") from None


def execute_under_policy(project: str, policy: str, effect_file: str, replay_log: str | None = None) -> dict:
    """The one place an effect under a standing approval is executed (limit L15). A handler prepares the effect
    document and hands it over; it confirms nothing itself. The document is checked, the approval is checked
    (_standing; a class of targets in its bounds resolved from the kind's recorded fact, before the lock; then
    autonomy.covers on the whole row, the policy file's hash now, and today's count read again under the write lock),
    the kind's judgement is made on the exact content (policy_judgement; the bytes it judged are written to a private
    folder the operation removes, and the provider is given that file, so what is sent is what was judged), and only
    then the provider's verb runs: a dry run, then the confirmed call, with --allow for exactly the approval's file globs and the document's idempotency
    key; the action is recorded after it, with the target the kind resolved.
    Returns {"executed": false, "policy", "why"} when the approval does not cover the effect (nothing ran), else
    {"executed": true, "policy", "approval_id", "action": {"id", "created"}, "result": <what the provider printed>}.
    replay_log (the path of a copy of the engagement log, for the replay of stored runs before a cut-over) makes the
    call a check: every step up to the provider runs, the kind's judgement reads that copy, and nothing is executed or
    recorded, whatever the answer; it returns {"executed": false, "policy", "checked": true, "would_execute", "why"}."""
    ctx = core.context(project)
    cfg, store = ctx["cfg"], ctx["store"]
    doc = _effect_document(effect_file, policy)
    checked = {"checked": True} if replay_log is not None else {}
    refuse = lambda why: {"executed": False, "policy": policy, "why": why, **checked, **({"would_execute": False} if checked else {})}
    answer = _standing(ctx, policy)
    if not answer["covered"]:
        return refuse(answer["why"])
    module = effects.module_for(doc["kind"])  # _effect_document accepted the kind: its module may run under a policy
    resolved = None
    if any(word in autonomy.TARGET_CLASSES for word in answer["approval"]["bounds"].get("targets") or []) \
            and hasattr(module, "resolve_targets"):
        try:  # a class of targets is a fact the operation reads, not a word of the document
            resolved = module.resolve_targets(cfg, doc, _resolve_call)
        except effects.EffectError as e:
            return refuse(f"the target class could not be resolved, so nothing is covered: {e.reason}")
    private = tempfile.mkdtemp(prefix="wb-policy-")  # 0700: the bytes a kind judged, which the provider is then given
    try:
        with core._write_lock(cfg):
            row = core._stored(ctx, store.approval_get, answer["approval"]["id"])
            executed = core._stored(ctx, store.action_count, kind=policy, since=core._midnight())
            effect = module.policy_effect(doc)
            ok, why = autonomy.covers(row, _policy_hash(cfg, row), effect, executed,
                                      datetime.datetime.now(datetime.timezone.utc), resolved=resolved)
            if not ok:
                return refuse(why)
            copies = {}
            if hasattr(module, "policy_judgement"):  # the checks the kind owns beyond the bounds, on the exact content
                ok, why, copies = module.policy_judgement(
                    core.ROOT, cfg["project"], doc, isolated.run_script, row["bounds"]["file"], private, log=replay_log,
                    data_dir=cfg["data_dir"], now=datetime.datetime.now().astimezone().isoformat())
                if not ok:
                    return refuse(why)
            provider = _provider_path(cfg, module.PROVIDER_CLASS, platform=module.policy_platform(doc))
            argv = list(module.policy_argv(doc))
            added = [a for a in argv if a in effects.RESERVED_FLAGS]
            if added:  # exact equality is the rule, as for the document's args; the kind's own arguments never carry what only the operation adds (the bounds' globs, the key, the flag)
                raise core.OpsError(f"the arguments of the effect kind {doc['kind']!r} hold {added[0]}: the operation adds it", 1)
            for flag, path in copies.items():  # the provider gets the bytes that were judged, not the file they came from
                if argv.count(flag) != 1 or argv.index(flag) + 1 >= len(argv):
                    raise core.OpsError(f"the arguments of the effect kind {doc['kind']!r} lack {flag} once with a value", 1)
                argv[argv.index(flag) + 1] = path
            if replay_log is not None:
                return {"executed": False, "policy": policy, "checked": True, "would_execute": True, "why": ""}
            for glob in row["bounds"]["files"]:
                argv += ["--allow", glob]
            argv += ["--idempotency-key", doc["idempotency_key"]]
            try:
                effects.provider_call(provider, argv + ["--dry-run"])
            except effects.EffectError as e:
                raise core.OpsError(f"nothing was executed: {e.reason}", 1) from None
            try:
                printed = effects.provider_call(provider, argv + ["--confirmed"])
            except effects.EffectError as e:
                raise core.OpsError(f"the provider failed after the dry run: {e.reason}; the idempotency key lets the next "
                               f"call replay it", 1) from None
            action = core._stored(ctx, store.action_add, kind=policy, idempotency_key=doc["idempotency_key"],
                             target=effect["target"], payload_sha256=doc["payload_sha256"], result=printed)
    finally:
        shutil.rmtree(private, ignore_errors=True)
    return {"executed": True, "policy": policy, "approval_id": row["id"],
            "action": {"id": action["id"], "created": action["created"]}, "result": printed}


def status(project: str) -> dict:
    """{"config": {"file", "sha256"} (the configuration's file name and hash, never its path: a reply to a messaging app carries no home folder; `config` has the path), "requests": [{"id", "title", "flow", "state", "model" (the model id or "auto" the person chose for the request, or None), "tasks": [{"id", "key", "title",
    "agent", "skill", "state", "note", "waiting_for"}], "after", "routing"}], "pending": [... each with "agent" and "actions"], "documents": [{"path", "status", "note", "on_platform"}],
    "board": {"left_out_final"} or None, "held": [{"task_id", "agent", "reason", "at", "next"}]}: everything from the
    store's records. A task's "holds_slot" says whether it holds a slot of its agent now (running, waiting for the person, or
    ready after the person answered: runtime/parallel.py). "left_out_final" is the number of tasks the board never mirrors because they were final when it
    was configured (runtime/board.py). A task's "title" and "agent" are the store's: the agent is None when the project
    has no area agents. A request's "title" is plan.request_title: the one given, else its first sentence, else its
    first line cut at a word. "held" lists the ready tasks the last dispatcher round did not start, each with its
    reason (runtime/dispatcher.py, REASONS) and "at", the time of the round; while the local service dispatches nothing
    every ready task is held with `dispatch off`; "next" is the command that gets past the reason, or None. A request's "routing" is the router's run on it now (ops_reads.with_routing) or None."""
    ctx = core.context(project)
    rows = core._stored(ctx, ctx["store"].tasks_list)
    agents = _agent_by_task(rows)
    comments = {}
    for c in core._stored(ctx, ctx["store"].comments_list):
        if c.get("task_id") is not None:
            comments[c["task_id"]] = comments.get(c["task_id"], 0) + 1
    board_of = lambda t: {"on_board": bool(t.get("remote_id")), "open_comments": comments.get(t["id"], 0)}
    holders = {h["id"] for h in core._stored(ctx, ctx["store"].task_slot_holders)}
    requests = [{**{key: r[key] for key in ("id", "flow", "state", "model")}, "title": plan.request_title(r), **board_of(r),
                 "tasks": [{**{key: t[key] for key in ("id", "key", "title", "agent", "skill", "state", "note")}, **board_of(t),
                            "holds_slot": t["id"] in holders}
                           for t in rows if t["parent_id"] == r["id"]]}
                for r in rows if r["parent_id"] is None]
    return {"config": {"file": os.path.basename(ctx["cfg"]["path"]), "sha256": ctx["cfg"]["sha256"]}, "requests": ops_reads.with_routing(ctx, ops_waits.in_status(ctx, requests, rows)),
            "pending": [_listed(item, ctx["store"], agents) for item in core._stored(ctx, ctx["store"].pending_list)],
            "documents": [{"path": d["path"], "status": d["status"], "note": d["note"], "on_platform": bool(d["remote_id"])}
                          for d in core._stored(ctx, ctx["store"].documents_list)],
            "board": ({"left_out_final": len(core._stored(ctx, lambda _conn: board.left_out(ctx, rows)))}
                      if board.enabled(ctx["cfg"]) else None),
            "held": _held_listed(ctx, rows)}


def config(project: str) -> dict:
    """What a shell may know of a project's configuration, and the one read that never refuses an unaccepted one:
    {"path", "sha256", "accepted", "data_dir", "messaging", "channels", "policies", "channel_profiles", "language", "grants", "widening", "widening_sha256", "warnings"}. "accepted" says
    whether the file's hash is the one the person accepted last; "policies" are the profiles of the file; "language" is the key of that name (None when it is not set), which the messaging bridge reads to say its sentences in the project's language (runtime/phrases.py); "grants" are the widenings of operations.GRANTS
    the file lists ([{"channel", "group", "means"}], a sender's also "sender"); "widening" is every group a channel or a listed sender has in this file
    and did not effectively have in the one accepted before ([{"place", "channel", "group", "means"}], POL-1 and POL-2: a place is a channel or
    `<platform>:<sender id>`), "widening_sha256" the hash accept-config --widen takes for it (None when there is none). A configuration that cannot be read at all, or that names another checkout, is still refused
    (code 3): there is nothing to report."""
    ctx = core.context(project, check_config=False)
    cfg = ctx["cfg"]
    accepted = core._stored(ctx, ctx["store"].cursor_get, project_config.ACCEPTED)
    got = lambda name: core._stored(ctx, ctx["store"].cursor_get, name)
    return {"path": cfg["path"], "sha256": cfg["sha256"], "accepted": accepted == cfg["sha256"],
            "data_dir": cfg["data_dir"], "messaging": cfg["messaging"], "channels": cfg["channels"], "policies": cfg["policies"],
            "channel_profiles": cfg["channel_profiles"], "language": cfg.get("language"),
            **policy_grants.view(got(policy_widening.EFFECTIVE), got(policy_widening.LEGACY), cfg, accepted is not None, got(policy_widening.ACCOUNTS),
                                     got(policy_widening.KEY) or policy_widening.PENDING_SECRET)}   # POL-1/POL-2: grants, widening, its hash, warnings


def task(project: str, task_id: int, channel: str | None = None, sender: str | None = None) -> dict:
    """One task or request with what is known of it: {"task": the store's row, "drop": what a file handed to it
    needs to know (ops_reads.drop_note: whether its skill uses the web, the line to show), None for a request,
    "runs": its runs oldest first,
    "pending": its pending decisions of every status, oldest first, each with "agent" (the task's own) and
    "actions"}. For a request the runs are the router's and the decisions its plan's or its question's; for a task of
    a plan, its own. The row also carries "waiting_for" and "after" (ops_waits.task_row)."""
    ctx = core.context(project)
    store = ctx["store"]
    found = core._stored(ctx, store.task_get, task_id)
    return {"task": ops_waits.task_row(ctx, found), "drop": ops_reads.drop_note(found), "runs": ops_ask.with_asker(ctx, core._stored(ctx, store.task_runs_list, task_id)),
            "pending": [{**ops_grants.private_view(ctx, ops_actor.shown(item), channel, sender), "agent": found["agent"] if found["parent_id"] is not None else None,
                         "actions": _actions(store, item)}
                        for item in core._stored(ctx, store.pending_list, "all", task_id)]}


def progress(project: str, since: str | None = None) -> dict:
    """Where the work stands and what happened in a period, from the store's records only (runtime/progress.py): no
    model is called and no number is estimated. since is None (the last 7 days), "<n>d" or "YYYY-MM-DD". Returns
    {"progress", "summary", "text"}. The effects counted are the approvals code executed (status `executed`)."""
    ctx = core.context(project)
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        start, end = progress_calc.window(since, now)
    except ValueError as e:
        raise core.OpsError(str(e), 2) from None
    tasks = core._stored(ctx, ctx["store"].tasks_list)
    runs = [run for task in tasks for run in core._stored(ctx, ctx["store"].task_runs_list, task["id"])]
    pending_rows = [ops_actor.shown(row) for row in core._stored(ctx, ctx["store"].pending_list, "all")]   # who acted, by profile and platform: never the sender's id
    executed = core._stored(ctx, ctx["store"].approvals_list, status="executed")
    now_progress = progress_calc.progress([t for t in tasks if t["parent_id"] is None], tasks, pending_rows, now)
    period = progress_calc.summary(tasks, runs, pending_rows, executed, start, end)
    return {"progress": now_progress, "summary": period, "text": progress_calc.render(now_progress, period)}


# --- stage 3: the route, the plan, its approval ------------------------------------------------------------------


def _with_agents(cfg: dict, tasks: list) -> list:
    """The tasks of a plan the person named, each with its area agent (plan.agent_of) when area agents are
    configured; without them every agent is None (stages 1 to 4)."""
    skills = plan.agent_skills(cfg, core.ROOT)
    return [dict(t, agent=plan.agent_for(t, skills)) for t in tasks]


def _plan_pending(ctx: dict, request: dict, tasks: list, route_read, source: str, flow, bound=None) -> dict:
    """The pending decision of kind `plan` for these tasks: plan.build with the limits of the gate file and the past
    runs of the plan's skills in this store."""
    reference = lab.reference()  # the control of a run is the gate file's, the same for every model
    limits = {"max_running": ctx["cfg"]["max_running"], "timeout_seconds": reference["timeout_seconds"],
              "retries": reference["retries"]}
    past = []
    for skill in dict.fromkeys(t["skill"] for t in tasks if t.get("skill")):
        past += core._stored(ctx, ctx["store"].task_runs_of_skill, skill)
    ops_flows.vet(ctx, tasks)    # a step kind that vets its files (a project script) is checked when the plan is built (PlanError)
    tasks = language_rules.with_language([dict(t) for t in tasks], request.get("language"))   # the person's choice is a field of each task: the hash covers it
    built = plan.build(request, tasks, route_read, source, limits, past, flow=flow, bound=bound,
                       project_language=ops_language.project_of(ctx["cfg"]))
    return ops_waits.annotate(ctx, request, {"kind": "plan", **built})


def route(project: str, request_id: int, flow: str | None = None, channel: str | None = None, params: list | None = None) -> dict:
    """Plan a request that waits for its route. With flow, the flow the person names: its plan is opened at once,
    with no run and no route lock (it only opens a plan; an open question of the router is cancelled). Without, one run
    of the router skill (router.ROUTER_SKILL), as it is, asked only for the route: the reply's route line is checked
    against the flow files and the pack in scope, and a valid route becomes a plan; a reply that asks becomes a
    question; a direct turn (route none, shape direct) opens nothing and returns kind "direct" with the router's
    "next"; anything else opens a question with a sentence and the reply whole in its payload. While the router answers
    another request of the project (it holds the route lock; a run of a task never does) the request is queued, not refused, when `channel` is one that drains the queue
    (ops_say.QUEUING_CHANNELS, the local service): {"routed": false, "queued": true}, routed by route_queued when the
    lock is free; any other channel is refused (RunBusy) as it always was. Nothing the router's run left comes back. No task is created before the
    person approves the plan (approve()). params (with a flow): the repeated name=value of the flow's parameters (runtime/ops_flows.py:
    the flow is the workbench's or the project's, its parameters and dates are filled, a file parameter names a file stage-file handed
    over for the request). Returns {"routed": true or false, "pending_id", "source", ...}."""
    ctx = core.context(project)
    if flow is None and params:
        raise core.OpsError("--param fills the parameters of a flow: name the flow (--flow)", 2)
    if flow is None:
        try:
            if channel in ops_say.QUEUING_CHANNELS and ops_say.waiting(ctx):  # first in, first out
                raise core.RunBusy("older lines or requests wait for the planning agent", 1)
            return _route_request(ctx, request_id)
        except core.RunBusy:
            if channel not in ops_say.QUEUING_CHANNELS + (ops_say.DRAIN,):
                raise
            _routable(ctx, request_id)
            return ops_say.queue_route(ctx, request_id)
    _routable(ctx, request_id)
    try:
        loaded, bound = ops_flows.bound(ctx, flow, params, request_id)
        tasks = _with_agents(ctx["cfg"], plan.from_flow(loaded, core.ROOT, plan.pack_skills(ctx["cfg"], core.ROOT)))
        decision = _plan_pending(ctx, core._stored(ctx, ctx["store"].task_get, request_id), tasks, None, "named", loaded["flow"], bound)
    except (plan.PlanError, lab.LabError, ValueError) as e:
        raise core.OpsError(f"no plan can be built: {e}", 1) from None
    opened = core._stored(ctx, ctx["store"].plan_open, request_id, title=decision["title"], body=decision["body"],
                          payload=decision["payload"])
    return {"routed": True, "pending_id": opened["pending_id"], "source": "named", "flow": loaded["flow"],
            "cancelled": opened["cancelled"], "recovered": []}


def _routable(ctx: dict, request_id: int) -> dict:
    """The request's row, refused when it is a task or does not wait for its route."""
    request = core._stored(ctx, ctx["store"].task_get, request_id)
    if request["parent_id"] is not None:
        raise core.OpsError(f"task {request_id} is not a request: route the request it belongs to", 1)
    if request["state"] != "requested":
        raise core.OpsError(f"request {request_id} is {request['state']}: only a request that waits for its route is routed", 1)
    return request


def _route_request(ctx: dict, request_id: int) -> dict:
    """The router's run on a request, holding the route lock (RunBusy when the router answers another request): the body
    of route() without a flow, and what route_queued calls."""
    with core._route_lock(ctx["cfg"]):
        recovered = ops_runs._recover(ctx, holding_route=True)
        request = _routable(ctx, request_id)
        try:
            parts = plan.split(request["text"])
        except ValueError as e:
            raise core.OpsError(str(e), 2) from None
        if len(parts["items"]) > 1:
            return {**_route_deliveries(ctx, request, parts), "recovered": recovered["tasks"]}
        return {**_route_run(ctx, request), "recovered": recovered["tasks"]}


def _router_call(ctx: dict, request: dict, text: str, *, reroute: bool = False) -> dict:
    """One run of the router skill on a request, asked only for the route, with text as the request's words. Returns
    {"out", "failed"} and, for a run that did not fail, "response", "body", "finish" (the arguments of
    route_run_finish), "common" (the payload keys every decision of the run carries) and "read" (router.read_route).
    A failed run is finished here; a run that did not fail is finished by the caller, with its decision."""
    cfg, store, skill = ctx["cfg"], ctx["store"], router.ROUTER_SKILL
    try:
        meta = skill_meta.declared(os.path.join(core.ROOT, "skills", skill))
        keys = core._keys()
        routing = _route(ctx, skill, meta, keys)
        if routing["key_missing"]:
            raise core.OpsError(f"no key was found for {routing['model']}: {keys[routing['model']]['reason']}", 3)
        identity = lab.skill_identity(skill)
        with core._claim_lock(cfg):  # the budget and the run row are one step: two starts cannot pass the same cap
            budget = _budget(ctx, plan.PLANNING, routing, keys)
            run_id = core._stored(ctx, store.route_run_start, request["id"], skill=skill, model=routing["model"],
                                  adapter=routing["adapter"], skill_version=identity["version"],
                                  skill_sha256=identity["content_sha256"], web=False, reroute=reroute,
                                  billing=routing["billing"] or "unknown", autonomy=routing["autonomy"])["run_id"]
    except (skill_meta.SkillError, lab.LabError, OSError, KeyError) as e:
        raise core.OpsError(f"the router ({skill}) could not start: {e}", 1) from None
    dest = os.path.join(cfg["data_dir"], core.RUNS_DIR, str(run_id))
    out = {"routed": False, "request": request["id"], "source": "router", "run_id": run_id, "run_dir": dest,
           "status": "failed", "ending": None, "failure": None, "pending_id": None, "kind": None, "kept": [],
           "left_out": [], "entered": None, "routing": routing, "use": None}

    def fail(kind: str, reason: str, attempts: int = 0, digest=None, redactions=None, reported=None) -> dict:
        done = core._stored(ctx, store.route_run_finish, run_id, status="failed", failure=kind, attempts=attempts,
                image_digest=digest, run_dir=dest, error=_note(reason), redactions=redactions,
                **_reported_usage(reported, routing))
        out["failure"] = None if ops_cancel.cancelled_run(out, done) else {"kind": kind, "reason": _note(reason)}   # a request being cancelled: cancelled (R18)
        return {"out": out, "failed": True}

    held, why = ops_instructions.for_run(cfg["project"])   # the standing instructions; a file that fails a check stops the run, before a use is recorded
    if why:
        return fail("internal", why)
    out["use"] = _use_start(ctx, run_id, skill, routing)
    prepared_dir = os.path.join(cfg["data_dir"], core.PREPARED_DIR, str(run_id))
    try:
        try:
            entered = workcopy.entering(cfg["project"], meta, web=False, cfg=cfg, settings_names=lab.settings_names(),
                                        prepared_dir=prepared_dir)
        except workcopy.CopyError as e:
            return fail("internal", f"the copy could not be built: {e}")
        out["left_out"] = entered["left_out"]
        out["entered"] = {"kind": entered["kind"], "agents_md": entered["agents_md"], "files": len(entered["files"])}
        answered = [] if reroute else [p for p in core._stored(ctx, store.pending_list, "resolved", request["id"])
                                       if p["kind"] == "question" and p["resolution"] == "answered"]
        prompt = task_prompt(text, router.ROUTE_TASK_TEXT, answered, instructions=held, language_line=ops_language.router_line(cfg, request)) \
            + ops_sources.router_block(ctx, request["text"])
        # Two router runs of two projects in one service process share the lab's process-wide session (lab.session ends
        # every container of the process when it closes): the whole session is held under one guard. Task runs are
        # processes of their own and never take it.
        with core._LAB_GUARD, lab.session(), _key_in_environment(routing, keys), ops_cancel.watch(ctx, request["id"]):
            result = lab.run_skill(skill, prompt, entered["files"], dest, web=False, model=routing["model"],
                                   max_cost=budget)
    except lab.LabError as e:
        return fail("internal", f"{e.kind}: {e.reason}", getattr(e, "attempts", 0))  # attempts: how many began (A-57)
    except Exception as e:  # the run row never stays `running`: the error is recorded, then shown
        traceback.print_exc()
        return fail("internal", f"{type(e).__name__}: {e}", getattr(e, "attempts", 0))
    finally:
        shutil.rmtree(prepared_dir, ignore_errors=True)
    counts, timing = result["counts"], result["timing"]
    if result["status"] != "ok":
        failure = result["failure"]
        return fail(failure["kind"], failure["reason"], counts["attempts"], result["image_digest"],
                    _count(counts.get("redactions")), result.get("reported"))
    if ops_cancel.stop_requested(ctx, request["id"]):   # the request is being cancelled: its reply is not read, nothing is opened
        return fail("stopped", "cancelled while the router answered", counts["attempts"], result["image_digest"], _count(counts.get("redactions")), lab.reported_usage(dest))
    # Nothing a route-only run left comes back: the router's run sees only the router installed, so what it would
    # write (a line about a skill it finds missing) is wrong here by construction.
    facts = {"staged": result["staged"]}
    out["kept"] = [{"path": rel, "class": path_rule.classify(rel, facts), "reason": ROUTE_KEPT}
                   for rel in sorted(result["changes"]["created"] + result["changes"]["modified"])
                   if path_rule.classify(rel, facts) != "ignored"]
    body, masked = workcopy.masked_reply(result["response"])
    body = body.encode("utf-8")[:store.BODY_MAX].decode("utf-8", errors="ignore")
    number = lambda key, kind: timing.get(key) if isinstance(timing.get(key), kind) and not isinstance(timing.get(key), bool) else None
    every = _reported_usage(lab.reported_usage(dest), routing)  # the usage of every attempt, the retried ones too (R4-C7b)
    finish = dict(status="ok", attempts=counts["attempts"],
                  cost_usd=every.get("cost_usd", number("cost_usd", (int, float)) if routing["billing"] == "metered" else None),
                  tokens=every.get("tokens", number("total_tokens", int)), duration_ms=number("duration_ms", int),
                  skill_loaded=_skill_loaded(timing, skill),
                  image_digest=result["image_digest"], run_dir=dest, redactions=_count(counts.get("redactions")))
    common = {"run_dir": dest, "response_file": os.path.join(result["outputs"], "response.md"), "kept": out["kept"],
              "routing": routing, "use": out["use"], "body_masked": masked}
    return {"out": out, "failed": False, "response": result["response"], "body": body, "finish": finish,
            "common": common, "read": router.read_route(result["response"], ignore_language=bool(request.get("language")))}


def _checked(ctx: dict, read: dict) -> dict:
    """read_route() of a reply with "checked": router.check_route() against the flow files and the pack in scope."""
    return dict(read, checked=router.check_route(read, flow_files.names(core.ROOT), plan.pack_skills(ctx["cfg"], core.ROOT),
                                                 known_sources=ops_sources.known_ids(ctx)))


def _combined(ctx: dict, request: dict, routed: list) -> dict:
    """plan.combine for these routed deliveries, with the flow files they name, the agents' packs, the gate file's
    limits and the past runs of their skills. Raises plan.PlanError, ValueError, flow_files.FlowError."""
    cfg = ctx["cfg"]
    flows = {}
    for entry in routed:
        flow = ((entry.get("route") or {}).get("checked") or {}).get("flow")
        if flow and flow not in flows:
            flows[flow] = flow_files.load(flow, core.ROOT)
    reference = lab.reference()
    limits = {"max_running": cfg["max_running"], "timeout_seconds": reference["timeout_seconds"],
              "retries": reference["retries"]}
    skills = plan.agent_skills(cfg, core.ROOT)
    pack = plan.pack_skills(cfg, core.ROOT)
    forced = ops_sources.forced_for(ctx, request["text"])  # the sources an @mention names are in the plan whatever the router chose
    mine = ops_language.project_of(cfg)
    out = plan.combine(request, routed, flows, skills, core.ROOT, pack=pack, limits=limits, past=[], forced=forced, project_language=mine)
    ops_flows.vet(ctx, out["tasks"])
    past = []
    for skill in dict.fromkeys(t["skill"] for t in out["tasks"] if t.get("skill")):
        past += core._stored(ctx, ctx["store"].task_runs_of_skill, skill)
    return plan.combine(request, routed, flows, skills, core.ROOT, pack=pack, limits=limits, past=past, forced=forced,
                        project_language=mine) if past else out


def _route_run(ctx: dict, request: dict) -> dict:
    """One run of the router on a request of one delivery (stage 3's behaviour): a valid route becomes a plan (through
    plan.combine), a reply that asks a question, anything else a question that names the flow command."""
    store = ctx["store"]
    call = _router_call(ctx, request, request["text"])
    out = call["out"]
    if call["failed"]:
        return out
    read, body, finish, common = call["read"], call["body"], call["finish"], call["common"]
    why = read.get("why")
    if read["kind"] == "route":
        decision = None
        try:
            route_read = _checked(ctx, read)
            if route_read["checked"]["ok"]:
                combined = _combined(ctx, request, [{"item": request["text"], "route": route_read, "reply": body}])
                if combined["plan"] is not None:
                    decision = ops_waits.annotate(ctx, request, {"kind": "plan", **combined["plan"]})
                else:  # the route was valid and the plan was not: the one delivery was left out (plan.combine says why)
                    why = combined["unrouted"][0]["why"] if combined["unrouted"] else why
            else:
                why = route_read["checked"]["why"]
        except (flow_files.FlowError, plan.PlanError, ValueError) as e:
            decision, why = None, f"no plan can be built from the route: {e}"
        if decision is not None:
            decision["payload"] = {**decision["payload"], **common}
            done = core._stored(ctx, store.route_run_finish, out["run_id"], ending="done", pending=decision, **finish)
            out.update(status="ok", ending="done", routed=True, kind="plan", pending_id=done["pending_id"])
            return out
    if read["kind"] == "direct":  # a direct turn: nothing to plan and nothing to ask; the conversation answers it
        core._stored(ctx, store.route_run_finish, out["run_id"], ending="done", **finish)
        out.update(status="ok", ending="done", routed=False, kind="direct", next=read["next"])
        return out
    if read["kind"] == "question":
        decision = {"kind": "question", "title": "The router asks", "body": body,
                    "payload": {"ending": "question", **common}}
        ending = "question"
    else:
        decision = _not_recognised(store, request, body, why, common)
        ending = "unclassified"
    done = core._stored(ctx, store.route_run_finish, out["run_id"], ending=ending, pending=decision, **finish)
    out.update(status="ok", ending=ending, kind="question", pending_id=done["pending_id"])
    return out


def _not_recognised(store, request: dict, body: str, why, common: dict) -> dict:
    """The question of a reply that names no route: its body is one sentence, and the reply whole is in the payload
    (`raw`) with the two actions the page offers (`actions`: choose a flow, cancel the request)."""
    raw = body.encode("utf-8")[:ops_say.RAW_MAX].decode("utf-8", errors="ignore")
    return {"kind": "question", "title": "The route was not recognised",
            "body": ops_say.NOT_NAMED.format(request=request["id"]),      # stored in English; a card and the conversation say it in the language (phrases.body)
            "payload": {"ending": "unclassified", "why": why, "raw": raw, "actions": list(ops_say.NOT_NAMED_ACTIONS), **common}}


def _item_text(preamble: str, item: str) -> str:
    return f"{preamble}\n\n{item}" if preamble else item


def _route_deliveries(ctx: dict, request: dict, parts: dict) -> dict:
    """A request that lists several deliveries (decision P3): one router run per item, each with the text
    "<preamble>\n\n<item>"; then one plan of every routed delivery, a delivery starting after an earlier one only when it reads what that one writes (plan.combine),
    opened with the last run. An item whose reply asks, names no valid route or cannot be planned goes to the plan's
    "unrouted" with the whole reply. When no item was routed, the last run opens one question with every reply."""
    store = ctx["store"]
    routed, runs, last = [], [], None
    items = parts["items"]
    for k, item in enumerate(items, 1):
        call = _router_call(ctx, request, _item_text(parts["preamble"], item))
        if call["failed"]:
            return {**call["out"], "deliveries": len(items), "runs": runs + [call["out"]["run_id"]]}
        read = call["read"]
        entry = {"item": item, "route": None, "reply": call["body"]}
        if read["kind"] == "route":
            entry["route"] = _checked(ctx, read)
            ending = "done" if entry["route"]["checked"]["ok"] else "unclassified"
        else:
            entry["route"] = None if read["kind"] == "question" else read
            ending = "question" if read["kind"] == "question" else "unclassified"
        routed.append(entry)
        runs.append(call["out"]["run_id"])
        if k < len(items):
            core._stored(ctx, store.route_run_finish, call["out"]["run_id"], ending=ending, **call["finish"])
        else:
            last = (call, ending)
    call, ending = last
    out = call["out"]
    try:
        combined = _combined(ctx, request, routed)
        why = None
    except (flow_files.FlowError, plan.PlanError, ValueError) as e:
        combined, why = None, f"no plan can be built from the routes: {e}"
    if combined is not None and combined["plan"] is not None:
        decision = ops_waits.annotate(ctx, request, {"kind": "plan", **combined["plan"]})
        decision["payload"] = {**decision["payload"], **call["common"], "router_runs": runs}
        kind = "plan"
    else:
        replies = "\n\n".join(f"--- delivery {n}: {e['item']} ---\n{e['reply'].rstrip()}" for n, e in enumerate(routed, 1))
        decision = _not_recognised(store, request, (why or "No delivery of the request was routed.") + "\n\n" + replies,
                                   why or "no delivery was routed", {**call["common"], "router_runs": runs})
        decision["title"] = "No delivery was routed"
        kind = "question"
    done = core._stored(ctx, store.route_run_finish, out["run_id"], ending=ending, pending=decision, **call["finish"])
    out.update(status="ok", ending=ending, routed=kind == "plan", kind=kind, pending_id=done["pending_id"],
               deliveries=len(items), runs=runs,
               unrouted=len(combined["unrouted"]) if combined is not None else len(items))
    return out


# --- stage 6: what follows a release: the brief's delivery routed again, the backlog's sub-tasks ------------------


def _approved_plan(ctx: dict, request_id: int):
    """The payload of the request's approved `plan` pending decision (the newest), or None: the one source of the
    plan's deliveries and limits after its approval."""
    found = [p for p in core._stored(ctx, ctx["store"].pending_list, "resolved", request_id)
             if p["kind"] == "plan" and p["resolution"] == "approved"]
    return found[-1]["payload"] if found else None


def _brief_delivery(ctx: dict, task: dict):
    """(k, delivery, plan payload) when task is the brief after which a delivery of its approved plan is routed again,
    else None."""
    if task.get("parent_id") is None:
        return None
    approved = _approved_plan(ctx, task["parent_id"]) or {}
    for k, delivery in enumerate(approved.get("deliveries") or [], 1):
        if delivery.get("reroute_after") and delivery["reroute_after"] == task["key"]:
            return k, delivery, approved
    return None


def _after_release(ctx: dict, item: dict) -> dict:
    """What a release of a review starts, by the person or by a mode (WP-6.5): (a) the brief's delivery routed again,
    with the brief's path from the files the run returned (never from the reply); (b) the backlog's sub-tasks, when the
    task's skill owns the product backlog and the run returned it. Returns {"reroute": ..., "subtasks": ...}, each only
    when it applied. The caller holds the route lock when (a) applies."""
    out = {}
    if item["kind"] != "review":
        return out
    task = core._stored(ctx, ctx["store"].task_get, item["task_id"])
    returned = [r.get("path") for r in (item.get("payload") or {}).get("returned") or [] if isinstance(r, dict)]
    found = _brief_delivery(ctx, task)
    if found is not None:
        out["reroute"] = _reroute(ctx, task, returned, *found)
    if task.get("skill") and task["skill"] == plan.owner_of(plan.BACKLOG, core.ROOT) and plan.BACKLOG in returned:
        out["subtasks"] = _backlog_subtasks(ctx, task)
    return out


def _reroute(ctx: dict, task: dict, returned: list, k: int, delivery: dict, approved: dict) -> dict:
    """Route delivery k again, once, with the line "The brief is at <path>." added. A route to a flow or a skill opens
    an `acceptance` of kind subtasks with its tasks (keys d<k>-..., the first ones after the brief); a second route to
    the brief skill, a reply that asks or names no valid route, a missing brief or a failed run opens an `acceptance`
    of kind deliveries that shows the reason and the router's whole reply: the delivery reaches the person, never a
    third run."""
    store = ctx["store"]
    request = core._stored(ctx, store.task_get, task["parent_id"])
    briefs = [rel for rel in returned if rel and rel.startswith(plan.BRIEFS_DIR)]
    if not briefs:
        return _not_rerouted(ctx, request, k, delivery, "the brief task returned no file under " + plan.BRIEFS_DIR, "")
    parts = plan.split(request["text"])
    text = _item_text(parts["preamble"] if len(parts["items"]) > 1 else "", delivery["item"]) + \
        f"\n\nThe brief is at {briefs[0]}."
    call = _router_call(ctx, request, text, reroute=True)
    if call["failed"]:
        if call["out"]["status"] == "cancelled":   # the request is being cancelled: nothing is opened for it (R18)
            return {"delivery": k, "run_id": call["out"]["run_id"], "pending_id": None, "routed": False, "why": "cancelled"}
        return _not_rerouted(ctx, request, k, delivery, f"the router's run failed: {call['out']['failure']['reason']}",
                             "", run_id=call["out"]["run_id"])
    read, body = call["read"], call["body"]
    why, tasks = None, None
    if read["kind"] != "route":
        why = "the router asked" if read["kind"] == "question" else read.get("why") or "no route"
    else:
        route_read = _checked(ctx, read)
        checked = route_read["checked"]
        if not checked["ok"]:
            why = checked["why"]
        elif checked.get("skill") == plan.BRIEF_SKILL:
            why = "the router named the brief again: a delivery is routed again once"
        else:
            try:
                flows = {checked["flow"]: flow_files.load(checked["flow"], core.ROOT)} if "flow" in checked else {}
                tasks = plan.delivery_tasks(dict(route_read, title=plan.title_of(delivery["item"])), k, flows, core.ROOT,
                                            plan.pack_skills(ctx["cfg"], core.ROOT), prefix=True)
                skills = plan.agent_skills(ctx["cfg"], core.ROOT)
                inside = {t["key"] for t in tasks}
                for t in tasks:
                    if not [d for d in t["depends_on"] if d in inside]:
                        t["depends_on"] = [task["key"]] + t["depends_on"]
                    t["agent"] = plan.agent_for(t, skills)
                language_rules.with_language(tasks, request.get("language") or route_read.get("language"))
            except (flow_files.FlowError, plan.PlanError, ValueError) as e:
                why, tasks = f"no task can be planned from the route: {e}", None
    finish = call["finish"]
    if tasks is None:
        decision = _not_rerouted_decision(request, k, delivery, why, body, call["common"])
        ending = "question" if read["kind"] == "question" else "unclassified"
    else:
        lines = [f"Delivery {k} ({delivery['item']}) was routed again after its brief ({briefs[0]}): {read['line']}.",
                 "Accept to add these tasks to request " + str(request["id"]) + ":", ""]
        lines += [f"- {t['key']}: {t['title']} ({t.get('skill') or 'step ' + t['step']}, agent {t['agent'] or 'none'})" for t in tasks]
        lines += ["", language_rules.payload_line({"tasks": tasks, "project_language": ops_language.project_of(ctx["cfg"])})]
        decision = {"kind": "acceptance", "title": f"Accept the tasks of delivery {k}, routed after its brief",
                    "body": "\n".join(lines), "payload": {"what": "subtasks", "delivery": k, "brief": briefs[0],
                                                          "route": read["line"], "tasks": tasks, **call["common"]}}
        ending = "done"
    done = core._stored(ctx, store.route_run_finish, call["out"]["run_id"], ending=ending, pending=decision, **finish)
    return {"delivery": k, "run_id": call["out"]["run_id"], "pending_id": done["pending_id"],
            "routed": tasks is not None and not done["cancelled"], "why": why}


def _not_rerouted_decision(request: dict, k: int, delivery: dict, why: str, reply: str, common: dict) -> dict:
    body = (f"Delivery {k} of request {request['id']} ({delivery['item']}) was not planned after its brief: {why}. "
            "Accepting records that you read this; start a new request for this delivery when you want it.")
    if reply:
        body += "\n\nThe router's reply, whole:\n\n" + reply
    return {"kind": "acceptance", "title": f"Delivery {k} was not routed after its brief",
            "body": body, "payload": {"what": "deliveries", "delivery": k, "why": why, **common}}


def _not_rerouted(ctx: dict, request: dict, k: int, delivery: dict, why: str, reply: str, run_id=None) -> dict:
    decision = _not_rerouted_decision(request, k, delivery, why, reply, {})
    opened = core._stored(ctx, ctx["store"].acceptance_open, task_id=request["id"], what="deliveries",
                     title=decision["title"], body=decision["body"], payload=decision["payload"])
    return {"delivery": k, "run_id": run_id, "pending_id": opened["pending_id"], "routed": False, "why": why}


def _backlog_subtasks(ctx: dict, task: dict) -> dict:
    """The product backlog's todo tasks as sub-tasks of the request, within the limits of its approved plan (read from
    that plan's payload and nowhere else): those inside are added at once (tasks_add), the others wait in one
    `acceptance` of kind subtasks. A task the request already has is not proposed again."""
    store, request_id = ctx["store"], task["parent_id"]
    approved = _approved_plan(ctx, request_id) or {}
    limits = approved.get("limits") or {}
    try:
        proposed = plan.backlog_tasks(os.path.join(ctx["cfg"]["project"], *plan.BACKLOG.split("/")), core.ROOT)
    except ValueError as e:
        return {"error": str(e)}
    rows = [t for t in core._stored(ctx, store.tasks_list, request_id) if t["parent_id"] is not None]
    known = {t["key"] for t in rows if t.get("key")}
    planned = {t.get("key") for t in approved.get("tasks") or []}
    proposed = [p for p in proposed if p["key"] not in known]
    if not proposed:
        return {"created": [], "pending_id": None}
    language_rules.with_language(proposed, ops_language.of_plan(approved, core._stored(ctx, store.task_get, request_id), task))
    skills = plan.agent_skills(ctx["cfg"], core.ROOT)
    for p in proposed:
        try:
            p["agent"] = plan.agent_of(p["skill"], skills) if skills else None
        except ValueError:
            p["agent"] = None  # no agent owns it: it waits, and the person can run it by hand
    chosen = plan.subtasks(limits, len([t for t in rows if t.get("key") not in planned]), proposed, known)
    created = ops_waits.add_subtasks(ctx, request_id, chosen["create"])["tasks"] if chosen["create"] else []
    pending_id = None
    if chosen["ask"]:
        lines = [f"The product backlog proposes {len(chosen['ask'])} task(s) outside the approved plan's limits "
                 f"({limits.get('max_subtasks', 0)} sub-tasks of {', '.join(limits.get('subtask_skills') or []) or 'no skill'}):", ""]
        lines += [f"- {t['key']}: {t['title']}" + (f" (after {', '.join(t['depends_on'])})" if t["depends_on"] else "")
                  for t in chosen["ask"]]
        lines += ["", language_rules.payload_line({"tasks": chosen["ask"], "project_language": ops_language.project_of(ctx["cfg"])})]
        pending_id = core._stored(ctx, store.acceptance_open, task_id=request_id, what="subtasks",
                             title=f"Accept {len(chosen['ask'])} sub-task(s) of request {request_id}",
                             body="\n".join(lines), payload={"tasks": chosen["ask"]})["pending_id"]
    return {"created": [t["id"] for t in created], "pending_id": pending_id}


EFFECT_CHANNELS = operations.EFFECT_CHANNELS  # the channels an effect may be approved from (decision D8, extended); the source is operations.py


def approve(project: str, pending_id: int, sha256: str | None = None, channel: str | None = None, go_ahead=None,
            sender: str | None = None) -> dict:
    """Approve a pending decision of kind `plan` (its tasks are created as the plan lists them, and those with no
    dependency are ready) or `acceptance` (the request written on the task board is kept, and waits for its route).
    With sha256, a plan is approved only when it is the plan's hash. An `effect` (stage 4) is approved only with
    its hash, and code then executes it: the one commit through the code provider, then the pull request; nothing is
    sent when anything moved since the gate, and a failure leaves it open, approved again with the same hash. An
    effect is approved from the terminal or from the local page (decision D8, extended: both show the person
    the content's hash and take it back typed or clicked), or from a messaging app whose policy the accepted configuration
    grants that effect's word (POL-1: a card that carried the whole text, the same hash); the table of operations tells this
    function which channel called, and any other channel (the conversation, the MCP mode), or none, is refused before anything is
    executed or sent (the pending row is read first, to know its kind; the rule fails closed). go_ahead: a plan's task keys to go ahead on.
    sender (POL-2): who acted when the channel is a messaging app, `<platform>:<sender id>` (operations.sender_key), set by the bridge from the update the
    provider authenticated. The policy is asked for THAT sender (the profile the loaded configuration gives them, at this call), and the store records the
    actor with the decision (ops_actor.label)."""
    ops_actor.require(channel, sender)
    ctx = core.context(project)
    item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    facts = ops_grants.effect_facts(ctx, item) if item["kind"] == "effect" else None   # the effect's word and whether all of it fits on a card
    actor = ops_actor.label(ctx["cfg"], channel, sender)
    ops_waits.only_on_plans(item, go_ahead, sha256, channel, ctx["cfg"]["channels"], facts, sender)
    if item["kind"] == "effect":   # outside the terminal and the page only a granted word, a whole card and the hash (POL-1; fails closed)
        refused = ops_grants.effect_refusal(ctx, item, channel, facts, sender)
        if refused:
            raise core.OpsError(refused, 1)
    if item["kind"] == "plan":
        payload = item.get("payload") or {}
        stated = payload.get("plan_sha256")
        if plan.plan_hash(payload.get("tasks") or []) != stated:
            raise core.OpsError(f"pending decision {pending_id}: its tasks do not have the hash it states; nothing was approved", 1)
        if sha256 is not None and sha256 != stated:
            raise core.OpsError(f"the plan's hash is {stated} and you typed {sha256}: nothing was approved", 1)
        return {**ops_waits.approve_plan(ctx, item, go_ahead, actor), "plan_sha256": stated}
    if item["kind"] == "acceptance":
        return ops_waits.accept(ctx, item, actor)
    if item["kind"] == "effect":
        return _approve_effect(ctx, item, sha256, actor)
    raise core.OpsError(f"pending decision {pending_id} is a {item['kind']}: approve takes a plan, an acceptance or an effect; "
                   "a question or a review is answered or released", 2)


def sync(project: str, dry_run: bool = False, take: str | None = None, path: str | None = None) -> dict:
    """Mirror the project's task board (runtime/board.py) and its documents (runtime/documents.py), holding the write
    lock (every provider call has its timeout: board.TIMEOUT, documents.TIMEOUT). The board: pull (the board to the
    store; not on a dry run, which reads nothing), then push (the store to the board; with dry_run, every write the provider would make, and nothing changes). The documents, after the
    board: pull (the platform to the project; not on a dry run), then push of every project document a manifest
    entry mirrors. take ("page" or "project") with path settles a document that was not taken (documents.take),
    and does nothing else. Returns {"board": {"pulled", "created", "edited", "refused", "gone", "comments",
    "left_out_final", "pushed", "failed"[, "would"]} or None, "documents": {"imported", "not_taken", "conflicts", "rejected", "comments", "gone",
    "pushed", "failed"[, "would"]} or None}."""
    if take is not None and take not in ("page", "project"):
        raise core.OpsError("take is page or project", 2)
    if (take is None) != (path is None):
        raise core.OpsError("take and path go together", 2)
    ctx = core.context(project)
    out = {"board": None, "documents": None}
    with core._write_lock(ctx["cfg"]):
        if take is not None:
            if not documents.enabled(ctx["cfg"]):
                raise core.OpsError("take settles a document of the documents platform, and none is configured", 3)
            out["documents"] = _documents(ctx, documents.take, ctx, path, take)
            return out
        if board.enabled(ctx["cfg"]):
            try:
                pulled = ({"pulled": [], "created": [], "edited": [], "refused": [], "gone": [], "comments": 0,
                           "left_out_final": len(board.left_out(ctx))} if dry_run else ops_waits.settled(ctx, board.pull(ctx, defer=True)))
                out["board"] = {**pulled, **board.push(ctx, dry_run=dry_run)}
            except board.BoardError as e:
                raise core.OpsError(f"the task board: {e}", 3 if e.kind == "not configured" else 1) from None
            except ctx["store"].StoreError as e:
                raise core.OpsError(str(e), e.code) from None
        if documents.enabled(ctx["cfg"]):
            pulled = _documents(ctx, documents.pull, ctx, dry_run=dry_run)
            pushed = _documents(ctx, lambda: documents.push(ctx, documents.mirrored_paths(ctx), dry_run=dry_run))
            out["documents"] = documents.merged(pulled, pushed)
    return ops_cancel.after_sync(ctx, out)   # the cancels a person made on the board, now that the write lock is let go


def _documents(ctx: dict, function, *args, **kwargs):
    """Call one function of runtime/documents.py; its refusal becomes this layer's."""
    try:
        return function(*args, **kwargs)
    except documents.DocumentsError as e:
        raise core.OpsError(f"the documents platform: {e}", 3 if e.kind == "not configured" else 1) from None
    except ctx["store"].StoreError as e:
        raise core.OpsError(str(e), e.code) from None


def hand_over(project: str, task_id: int, file: str) -> dict:
    """Put one file of the person's in a task's file drop, <project>/.workbench-local/drop/<task id>/ (runtime/drop.py):
    it enters the runs of that task only, and their prompt lists it. Holds the write lock, and is refused while the task is
    running. Returns {"task", "path", "bytes", "sha256"}; refused (drop.DropError) with the reason."""
    ctx = core.context(project)
    with core._write_lock(ctx["cfg"]):
        task = core._stored(ctx, ctx["store"].task_get, task_id)
        if task["parent_id"] is None or not (task.get("skill") or task.get("step_kind")):
            raise core.OpsError(f"{task_id} is a request: a file is handed to one of its tasks", 1)
        if task["state"] == "running":
            raise core.OpsError(f"task {task_id} is running: hand the file over when its run ends", 1)
        try:   # a step task (the kind `ingest` reads its file from the drop) uses no web
            meta = {"web": False} if task.get("step_kind") else skill_meta.declared(os.path.join(core.ROOT, "skills", task["skill"]))
        except skill_meta.SkillError as e:
            raise core.OpsError(str(e), 1) from None
        try:
            return drop.hand_over(ctx["cfg"]["project"], {**task, "web": meta["web"] and not task.get("web_off")}, os.path.abspath(file),
                                  drop.WEB_TASK_TAKES_DROP)
        except drop.DropError as e:
            raise core.OpsError(str(e), 1) from None


def reject(project: str, pending_id: int, note: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """Reject a pending decision of kind `plan` or `acceptance`: the request is cancelled, with what is open under
    it. A note is kept on a rejected plan. An `effect` rejected cancels its task, and nothing is sent."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "reject", channel, sender)
    actor = ops_actor.label(ctx["cfg"], channel, sender)
    item = core._stored(ctx, ctx["store"].pending_get, pending_id)
    if item["kind"] == "plan":
        said = core._text(note, "the note") if note is not None else None
        out = core._stored(ctx, ctx["store"].plan_reject, pending_id, by="user", note=said, actor=actor)
        ops_flows.discard_staged(ctx, item["task_id"])      # and the files handed over for it
        return out
    if item["kind"] == "acceptance":
        return core._stored(ctx, ctx["store"].acceptance_resolve, pending_id, resolution="rejected", by="user", actor=actor)
    if item["kind"] == "effect":
        said = core._text(note, "the note") if note is not None else None
        with ops_step_effects.resolution_guard(ctx, item):    # refused while the write of an output runs: it would end with no record
            return ops_waits.settled(ctx, core._stored(ctx, ctx["store"].pending_resolve, pending_id, resolution="rejected",
                                                       by="user", answer=said, actor=actor))
    raise core.OpsError(f"pending decision {pending_id} is a {item['kind']}: reject takes a plan, an acceptance or an effect", 2)


# --- stage 6: the dispatcher's operations ----------------------------------------------------------------------------

DISPATCH_BUDGET = 2700     # seconds after which a round starts no new run (the worker's limit is 240 minutes)
HANDLER_TIMEOUT = 1800     # seconds a handler's verb may take
PER_RUN_USD = 0.5          # what a floor run of unknown cost counts at, when runtime.json names no max_cost_usd_per_run
# A run that failed so: the next run of the round would fail the same way, so the round stops.
STOPPING_FAILURES = ("auth", "settings")
STOPPING_REASONS = ("container:", "config:")  # a LabError of these kinds, recorded as an internal failure


def _midnight_utc() -> str:
    """The start of today, local time, as UTC ISO-8601: where a day's caps start counting."""
    local = datetime.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(datetime.timezone.utc).isoformat()


def _budget(ctx: dict, agent, routing: dict, keys=None):
    """lab.run_skill's max_cost: the spend limit of a run on a metered credential, or one no manifest could bill (autonomy.run_budget
    of the agent's day; the per-run limit when the agent has no caps or less is left, a start by hand not being capped); None else."""
    per_run = ctx["cfg"]["raw"].get("max_cost_usd_per_run", PER_RUN_USD)
    found = _agents_of_the_day(ctx, keys).get(agent)
    return None if routing["billing"] not in (None, "metered") else (found and autonomy.run_budget(found["entry"], found["spent"], per_run)) or per_run


def _agents_of_the_day(ctx: dict, keys=None) -> dict:
    """Each area agent's facts, a day's spend and entry, from the store and the configuration: {name: {"facts",
    "entry", "spent", "split", "in_use"}} (split: autonomy.spend_split, for the meters; in_use: core._caps_in_use; keys: the Keys found). The
    spend is by the billing each run recorded (autonomy.with_billing gives a run older than the column the rule of its model: a run on a metered model is metered). The day starts at local midnight (_midnight_utc), as the caps count it, and a run of the router
    (its task is a request, so its agent is None) counts against the planning agent, an answer run (ask) against the owner of the answer skill
    (ops_ask.run_owners). {} without area agents."""
    store, cfg = ctx["store"], ctx["cfg"]
    agents_checked = cfg["area_agents"]
    if not agents_checked:
        return {}
    now = datetime.datetime.now(datetime.timezone.utc)
    standing_rows = core._stored(ctx, store.approvals_list, status="active", scope="standing")
    runs = autonomy.with_billing(core.attributed(core._stored(ctx, store.runs_since, _midnight_utc()), ops_ask.run_owners(ctx)),
                                 core._metered_models())
    per_run, in_use = cfg["raw"].get("max_cost_usd_per_run", PER_RUN_USD), core._caps_in_use(runs, keys or core._keys())
    return {name: {"facts": autonomy.facts(name, agents_checked, standing_rows, now), "entry": entry,
                   "spent": autonomy.spend(runs, name, per_run), "split": autonomy.spend_split(runs, name, per_run),
                   "in_use": in_use}
            for name, entry in agents_checked.items()}


def _proven_on(ctx: dict, routed, task: dict, run) -> bool:
    """Whether the skill of a task is proven now on the model its run used (the proof of that model, read now); with no run
    (a review of a stand-in), on the model the task would run on."""
    try:
        return bool(routed(task["skill"], task, (run or {}).get("model")).get("proven"))
    except core.OpsError:
        return False


def _snapshot(ctx: dict, keys) -> dict:
    """What dispatcher.decide reads, from the store, the proof (proof.route through _route) and the runtime manifests:
    the tasks running (with the children started and not yet claimed), the slot holders, the ready tasks oldest first with
    the model each would run on and the code flag and footprint of their skill, the open reviews with their agent, whether
    the pair that ran is proven and whether the person's consent covers it, and mandatory flag, the tasks a child could not start lately (`refused`), the project's `max_running`, and each area
    agent's facts, a day's spend and its entry (_agents_of_the_day). A run of the router (its task is a request, so its
    agent is None) counts against the planning agent."""
    store, cfg = ctx["store"], ctx["cfg"]
    agents = cfg["area_agents"]
    tasks = ops_waits.current_tasks(ctx)  # the waits derived again first: a round decides from what is now
    by_id = {t["id"]: t for t in tasks}
    proofs = {}

    def routed(skill: str, task=None, requested=None) -> dict:
        slot = (skill, (task or {}).get("id"), requested)
        if slot not in proofs:
            proofs[slot] = _route(ctx, skill, skill_meta.declared(os.path.join(core.ROOT, "skills", skill)), keys, task, requested)
        return proofs[slot]

    cache = {}
    parallel_part = ops_runs.parallel_state(ctx, tasks, cache)
    starting = parallel_part.pop("starting")  # started and not yet claimed: counted as running, not decided again
    out = {**parallel_part,
           "ready": [{**t, "code": ops_runs.task_facts(t, cache)[1], "footprint": ops_runs.task_facts(t, cache)[0]}
                     for t in tasks if t["state"] == "ready" and t["parent_id"] is not None and t["id"] not in starting],
           "reviews": [], "agents": _agents_of_the_day(ctx, keys), "model": {}, "billing": {},
           "max_running": cfg["max_running"], "per_run_usd": cfg["raw"].get("max_cost_usd_per_run", PER_RUN_USD)}
    for item in core._stored(ctx, store.pending_list):
        task = by_id.get(item["task_id"])
        if item["kind"] != "review" or task is None or not task.get("skill"):
            continue
        runs = core._stored(ctx, store.task_runs_list, task["id"])
        run = runs[-1] if runs else None  # the run that opened this review
        proven, consent = ops_models.consent_for_review(ctx, run, agents.get(task.get("agent")),
                                                        _proven_on(ctx, routed, task, run))
        out["reviews"].append({"pending": item, "task": task, "agent": task.get("agent"), "proven": proven, "consent": consent,
                               "mandatory": plan.mandatory(task["skill"], core.ROOT)})
    for task in out["ready"]:
        if task.get("agent") in agents and task.get("skill"):
            try:
                routing = routed(task["skill"], task)
            except core.OpsError as e:  # a model the gate file does not list: the task is held, the round goes on
                out.setdefault("refused", {})[task["id"]] = str(e)
                continue
            out["model"][task["id"]], out["billing"][task["id"]] = routing["model"], routing["billing"]
    out["waits"] = ops_waits.waiting_for(ctx)  # a ready task with an open wait starts nowhere (dispatcher.decide)
    ops_steps.annotate(ctx, out)  # the brake of the step tasks, and which kinds the dispatcher may start (runtime/ops_steps.py)
    return out


def _mode_releases(ctx: dict, released: list, snapshot: dict, decided: dict, skip=None) -> list:
    """Apply the releases a decision lists, each as the mode of its agent (by "mode:<mode>"), with what a release starts
    (_after_release). A review skip(task) names is left for later (poll leaves the brief's release, which runs the
    router, to dispatch). When a release by a mode completes a request, one acceptance of kind deliveries lists every
    delivery a mode released in it (part 0, F.3). Returns [{"pending_id", "task_id", "by", ...}]."""
    reviews = {r["pending"]["id"]: r for r in snapshot["reviews"]}
    agents = snapshot["agents"]
    out = []
    for pending_id in decided["release"]:
        review = reviews[pending_id]
        if skip is not None and skip(review["task"]):
            continue
        by = "mode:" + autonomy.mode_of(agents[review["agent"]]["facts"])
        done = _release(ctx, pending_id, by=by)
        out.append({"pending_id": pending_id, "task_id": review["task"]["id"], "by": by,
                    **({"after": done["after"]} if done.get("after") else {})})
        released.append(pending_id)
        for request_id in done.get("completed") or []:
            out[-1]["acceptance"] = _deliveries_acceptance(ctx, request_id)
    return out


def _deliveries_acceptance(ctx: dict, request_id: int):
    """One acceptance of kind deliveries on a request a mode completed, listing every delivery a mode released in it;
    None when no delivery of it was released by a mode."""
    store = ctx["store"]
    tasks = {t["id"]: t for t in core._stored(ctx, store.tasks_list, request_id) if t["parent_id"] is not None}
    by_mode = [p for p in core._stored(ctx, store.pending_list, "resolved")
               if p["task_id"] in tasks and p["kind"] == "review" and p["resolution"] == "released"
               and str(p.get("resolved_by") or "").startswith("mode:")]
    if not by_mode:
        return None
    lines = [f"Request {request_id} is done, and an autonomy mode released these deliveries without you. Each stays a "
             "draft: read it, then accept (a note records what you think), or reject.", ""]
    lines += [f"- task {p['task_id']} ({tasks[p['task_id']]['skill']}): {tasks[p['task_id']]['title']}, released by "
              f"{p['resolved_by']}, pending decision {p['id']}" for p in by_mode]
    return core._stored(ctx, store.acceptance_open, task_id=request_id, what="deliveries",
                   title=f"Accept the deliveries of request {request_id}", body="\n".join(lines),
                   payload={"released": [p["id"] for p in by_mode]})["pending_id"]


def _stops_the_round(ran: dict):
    """The reason a round stops after this run, or None: a failure the next run would repeat."""
    failure = ran.get("failure") or {}
    if failure.get("kind") in STOPPING_FAILURES:
        return f"a run failed ({failure['kind']}): the next run would fail the same way"
    if failure.get("kind") == "internal" and str(failure.get("reason") or "").startswith(STOPPING_REASONS):
        return f"a run could not reach the container ({failure['reason'][:200]}): the next run would fail the same way"
    return None


def dispatch(project: str, budget_seconds=None, wait: bool | None = None, channel: str | None = None) -> dict:
    """The dispatcher (decision P5): one round (runtime/ops_runs.py). The handlers whose `dispatch` is true and whose agent
    is enabled get their tick; then the reviews each agent's mode releases are released (with what a release starts), and
    every ready task that the rules allow (its agent's mode and daily caps by the billing of its route's credential, the
    slots of its agent and of the project, the artifacts in use, one code task per request) is started as a child process
    of its own (`run-task`, one OS process per task run). No new run starts once budget_seconds (default DISPATCH_BUDGET)
    have passed, and a failure the next run would repeat stops the round. With wait (the default, and the terminal's and
    the scheduler's: their job kills what it leaves) the round keeps reaping and deciding until none of its children is
    alive; without it (the local service, whose loop and page start runs and return) it returns at once and the next round
    reports what ended. `wait` is taken from the channel when it is not given: the page does not wait. Returns
    {"handlers", "released", "started": [{"task_id", "started_at"}], "ran": [the runs that ended since the last report],
    "held", "stopped"}. Before a run starts, the credential of the model it would run on and the eval image are
    checked: a round that cannot start for either stops, and no task fails for it. The ready tasks the round held, each
    with its reason (dispatcher.held_of), are kept for `status` (HELD_CURSOR). One round of a project at a time
    (DispatchBusy)."""
    return ops_runs.dispatch(project, budget_seconds=budget_seconds, wait=(channel != "page") if wait is None else wait)


reap = ops_runs.reap  # an assignment, not a def: it is no operation (the local service reaps its children on every tick)


PIN_NAME = "dispatch-pin.json"


def pin(project: str) -> dict:
    """The pin of the dispatcher's two jobs, <data_dir>/dispatch-pin.json (mode 0600): the path and the hash of the
    project's runtime.json, which must be the accepted one. The scheduler's entry (runtime/dispatcher.py) refuses to
    load anything when the file differs from it. Returns {"pin", "runtime_json", "next"}."""
    ctx = core.context(project)
    cfg = ctx["cfg"]
    pinned = {"runtime_json": {"path": cfg["path"], "sha256": cfg["sha256"]},
              "pinned_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    os.makedirs(cfg["data_dir"], mode=0o700, exist_ok=True)
    target = os.path.join(cfg["data_dir"], PIN_NAME)
    temporary = f"{target}.{os.getpid()}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(pinned, indent=1) + "\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return {"pin": target, "runtime_json": pinned["runtime_json"],
            "next": f"dispatcher.py command-file --job poll|work --project {cfg['project']} --pin {target}, then schedule "
                    "each with the scheduler provider"}


def _configuration_moved(ctx: dict) -> bool:
    """Whether the configuration this round loaded is no longer the file or no longer the accepted one: the file's hash
    or the accepted hash differs from the one the round started with. The round then ends, so that a narrowing accepted
    in the middle of it (the page stopped an agent) stops the next start."""
    try:
        now = core._config_of(ctx["cfg"]["project"])
    except core.OpsError:
        return True
    accepted = core._stored(ctx, ctx["store"].cursor_get, project_config.ACCEPTED)
    return now["sha256"] != ctx["cfg"]["sha256"] or accepted != ctx["cfg"]["sha256"]


def _credential_stop(model: str | None = None):
    """(reason, why, missing) no run on the model can start from this process, or None: its credential is neither set
    nor found in the secret store (lab.credential_missing). The model is the default model (the first lab model) when none
    is named. The reason is `secret store` when this interpreter cannot read the store at all (the library is missing), else
    `credential`. Named with the interpreter, since a scheduled job's interpreter may not read the store (open point O1)."""
    model = lab.resolve_model(model)
    missing = lab.credential_missing(model)
    if not missing:
        return None
    reason = "credential" if dispatcher.store_readable() == "ok" else "secret store"
    locked = secret_state.unreadable_sentence(core.ROOT, names=missing) if reason == "credential" else ""   # a locked store is not a missing key (I3)
    return reason, (f"{locked}; the credential of {model} ({', '.join(missing)}) cannot be read" if locked else
                    f"the credential of {model} ({', '.join(missing)}) is neither set nor found in the secret store") + (
                    f" from {sys.executable} (Python {sys.version.split()[0]}): no run starts. See contracts/runtime.md, "
                    "\"The dispatcher's two jobs\""), list(missing)


def _image_stop():
    """("image", why) when the eval image is not on this machine although the lab runs in a container (a run would
    fail for it), else None. A machine the lab cannot look at (no container executor, no docker) says nothing."""
    seen = lab.image()
    if seen.get("problem"):
        return "image", f"the eval image cannot be looked up ({seen['problem']}): no run starts, and no task fails for it. See connections", []
    if seen.get("name") and not seen.get("digest"):
        return "image",f"the eval image {seen['name']} is not on this machine: no run starts, and no task fails for it. See connections", []
    return None


# --- why a ready task did not start (WP-9.14, A-10) ---------------------------------------------------------------

HELD_CURSOR = "dispatch:held"   # the store's cursor that holds the last round's held tasks (JSON), per project
HELD_KEPT = 20                  # tasks kept in the record: a cursor value is at most 4 KiB
SERVICE = {}                    # the local service's facts, by project folder: set by service_check in the service's process only


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _record_held(ctx: dict, held: list, missing=()) -> None:
    """Keep the last round's held tasks, [{"task_id", "agent", "reason"}], as the cursor HELD_CURSOR with the time they
    began to be held (at), and `missing`, the variables of the credential that were not found (names only). At most
    HELD_KEPT tasks; "more" counts the rest. A round that holds the same tasks for the same reasons writes nothing: a
    write moves the store's change counter, and every open page reloads for it."""
    kept, more, names = held[:HELD_KEPT], max(0, len(held) - HELD_KEPT), list(missing)[:HELD_KEPT]
    try:
        before = json.loads(core._stored(ctx, ctx["store"].cursor_get, HELD_CURSOR) or "null")
    except ValueError:
        before = None
    if isinstance(before, dict) and before.get("held") == kept and before.get("more") == more \
            and (before.get("missing") or []) == names:
        return
    record = {"at": _now_iso(), "held": kept, "more": more, "missing": names}
    core._stored(ctx, ctx["store"].cursor_set, HELD_CURSOR, json.dumps(record, separators=(",", ":")))


def _held_listed(ctx: dict, rows: list) -> list:
    """The held tasks `status` and `agents` show: [{"task_id", "agent", "reason", "at", "next", "commands"}] for the ready tasks
    among rows (the store's tasks). While the local service dispatches nothing, every ready task is held with `dispatch
    off`; otherwise the last round's record, kept only for tasks still ready. `next` is the sentence that gets past the
    reason, or None; `commands` is the same as fields, [{"name", "command"}], for the two reasons a command gets past
    (ops_reads.held_commands), else []."""
    ready = [t for t in rows if t["state"] == "ready" and t["parent_id"] is not None]
    if not ready:
        return []
    project = ctx["cfg"]["project"]
    service = SERVICE.get(os.path.realpath(project))
    if service is not None and service["dispatch"] == "off":
        return [{"task_id": t["id"], "agent": t.get("agent"), "reason": dispatcher.DISPATCH_OFF, "at": service["at"],
                 "next": core._command("run-next", project, uv=True), "commands": []} for t in ready]
    try:
        record = json.loads(core._stored(ctx, ctx["store"].cursor_get, HELD_CURSOR) or "null")
    except ValueError:
        record = None
    if not isinstance(record, dict):
        return []
    ids = {t["id"] for t in ready}
    out = []
    for h in record.get("held") or []:
        if h.get("task_id") in ids:
            out.append({**h, "at": record.get("at"), "next": ops_reads.held_next(project, h["reason"], record.get("missing")),
                        "commands": ops_reads.held_commands(project, h["reason"], record.get("missing"))})
    return out


def _ticks(ctx: dict, project: str) -> dict:
    """The tick of every handler whose `dispatch` is true and whose agent is enabled; a failure is recorded, never
    raised."""
    out = {}
    agents = ctx["cfg"]["area_agents"]
    for name, entry in sorted((ctx["cfg"].get("handlers") or {}).items()):
        agent = agents.get(entry.get("agent")) or {}
        if not entry.get("dispatch") or not agent.get("enabled") or agent.get("mode") == "stopped":
            continue
        try:
            out[name] = handler_call(project, name, "tick")
        except core.OpsError as e:
            out[name] = {"error": str(e), "code": e.code}
    return out


def poll(project: str) -> dict:
    """The short job (decision P5): mirror the task board and the documents when the project has them (an error is
    recorded, not raised), expire the standing approvals past their expiry, rewrite the state file's generated lines
    (the Checkpoints line, the standing rows) when they changed, and release what each agent's mode releases. It calls
    no model and starts no task: the release of a brief, which runs the router, is left to dispatch. Returns {"synced",
    "expired", "released", "state"}."""
    ctx = core.context(project)
    cfg, store = ctx["cfg"], ctx["store"]
    synced = None
    if board.enabled(cfg) or documents.enabled(cfg):
        try:
            synced = sync(project)
        except core.OpsError as e:
            synced = {"error": str(e), "code": e.code}
    expired = ops_waits.settled(ctx, core._stored(ctx, store.approvals_expire, datetime.datetime.now(datetime.timezone.utc).isoformat()))
    state = "unchanged"
    if expired:
        rows = _standing_rows(ctx)
        state = "written" if rows.get("state_rows") is not None else state
    if cfg["raw"].get("area_agents") is not None:
        target = os.path.join(cfg["project"], *path_rule.STATE.split("/"))
        current = _read(target) if os.path.isfile(target) and not os.path.islink(target) else None
        if current is not None:
            text, found = state_merge.with_checkpoints(current, autonomy.state_checkpoints(cfg["area_agents"]))
            if found and text != current and isinstance(ops_config.write_checkpoints(cfg), dict):
                state = "written"
    released = []
    if cfg["area_agents"]:
        snapshot = _snapshot(ctx, core._keys())
        decided = dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start, parallel.admit)
        released = _mode_releases(ctx, [], snapshot, decided, skip=lambda task: _brief_delivery(ctx, task) is not None)
    return {"synced": synced, "expired": expired, "released": released, "state": state}


def _handler_verbs(path: str) -> tuple:
    """The words of a handler's VERBS constant, read with ast, without importing the file."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "VERBS" for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, (tuple, list)) and all(isinstance(v, str) for v in value):
                return tuple(value)
    return ()


def handler_call(project: str, name: str, verb: str, args=None) -> dict:
    """Start one verb of a handler (runtime/handlers/<name with underscores>.py of the checkout) with this interpreter
    and --project, and return the one JSON object it printed, with "exit_code". name is a key of the configuration's
    handlers; verb is a word of the file's VERBS; args is {flag: value}, passed as --flag value. Anything else: OpsError
    2. Output that is not one JSON object: OpsError 1, with the end of its stderr."""
    ctx = core.context(project)
    handlers = ctx["cfg"].get("handlers") or {}
    if name not in handlers:
        raise core.OpsError(f"{name!r} is not a handler of {ctx['cfg']['path']}", 2)
    path = os.path.join(core.ROOT, "runtime", "handlers", name.replace("-", "_") + ".py")
    if not os.path.isfile(path) or os.path.islink(path):
        raise core.OpsError(f"the handler {name} has no file runtime/handlers/{os.path.basename(path)} in this checkout", 2)
    try:
        verbs = _handler_verbs(path)
    except (OSError, SyntaxError, ValueError) as e:
        raise core.OpsError(f"the handler {name}'s verbs cannot be read: {type(e).__name__}", 2) from None
    if verb not in verbs:
        raise core.OpsError(f"the handler {name} has no verb {verb!r} (its verbs: {', '.join(verbs) or 'none'})", 2)
    flags = []
    for flag, value in sorted((args or {}).items()):
        if not isinstance(flag, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", flag) or flag == "project":
            raise core.OpsError(f"{flag!r} is not a flag a handler takes", 2)
        flags += [f"--{flag}", str(value)]
    try:
        done = subprocess.run([sys.executable, path, verb, "--project", ctx["cfg"]["project"], *flags],
                              capture_output=True, text=True, timeout=HANDLER_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        raise core.OpsError(f"the handler {name} {verb} ran over {HANDLER_TIMEOUT} s", 1) from None
    except OSError as e:
        raise core.OpsError(f"the handler {name} could not be started: {type(e).__name__}", 1) from None
    try:
        printed = json.loads(done.stdout)
    except ValueError:
        printed = None
    if not isinstance(printed, dict):
        raise core.OpsError(f"the handler {name} {verb} printed no JSON object (exit {done.returncode}): "
                       f"{done.stderr.strip()[-300:]}", 1)
    return {**printed, "exit_code": done.returncode}


# --- the facade: what the sibling modules hold, under the names a shell and a test read ---------------------------------

OpsError = core.OpsError  # a shell catches ops.OpsError; the class has one home, runtime/ops_core.py
DispatchBusy = core.DispatchBusy  # the local service's loop catches it by this name

# The conversation (runtime/ops_say.py): the two operations, and the constants the shells and the tests read.
from ops_say import chat_memory, route_queued, say  # noqa: E402,F401
from ops_say import ASK_NEXT, CONVERSATION, MEMORY_CHARS, MEMORY_CUT, MEMORY_HEAD, MEMORY_TAIL, MEMORY_TURNS, PLAN_NEXT  # noqa: E402,F401
# The configuration's acceptance (runtime/ops_config.py): its two operations, and the names a shell and a test read.
from ops_config import accept_config, give_consent, set_mode, set_model  # noqa: E402,F401
# The sources of the project (runtime/ops_sources.py): the ingest operations.
from ops_sources import (source_add, source_calendar, source_describe, source_drive, source_import, source_mail, source_onedrive,  # noqa: E402,F401
                         source_refresh, sources_catalog)
# The files sent through a messaging app (runtime/ops_attachments.py): the held list, the hold, the add and the discard.
from ops_attachments import attachment_add, attachment_discard, attachment_hold, attachments  # noqa: E402,F401
# Reminders (runtime/ops_reminders.py): the three operations, and what the messaging bridge asks of the store to send them.
from ops_reminders import remind, reminder_forget, reminders_due, reminders_read, reminders_retry, reminders_sent  # noqa: E402,F401
# The person's own calendar (runtime/ops_calendar.py, package W1): create, change and remove an event; each one prepares a card and writes nothing.
from ops_calendar import event_cancel, event_change, event_create  # noqa: E402,F401
# Files in the person's own Drive and OneDrive (runtime/ops_files.py, package W4a): prepare a new file, a new revision or the saving of a file a sender sent.
from ops_files import file_create, file_replace, file_save  # noqa: E402,F401
import ops_steps  # noqa: E402  (the step task's run and its brake; this file re-exports `run_step` below)
from ops_steps import run_step  # noqa: E402,F401
from ops_cancel import cancel, stop_task  # noqa: E402,F401  (the operations `cancel` and `stop-task`)
# The flows (runtime/ops_flows.py): the list, the flow check, saving a plan as one, and a file staged for a request.
import ops_flows  # noqa: E402
from ops_flows import check_flow, flow_save, flows, stage_file  # noqa: E402,F401
import ops_instructions  # noqa: E402  (the standing instructions: three operations, the block of a prompt, the answer's proposal)
from ops_instructions import answer_proposing, instructions_add, instructions_read, instructions_set  # noqa: E402,F401
import ops_ask  # noqa: E402  (the answer from sources: `ask`, and the owners of the runs of a request)
from ops_ask import ask  # noqa: E402,F401
from ops_contained import contained_run  # noqa: E402,F401  (the contained run: a handler's agent run; moved out of this file, no change of logic)
# The routines (runtime/ops_routines.py): the schedule's flows, their approval by hash, the brakes and the tick a round calls.
import ops_routines  # noqa: E402
from ops_routines import (routine_approve, routine_cancel, routine_change, routine_create, routine_pause, routine_resume,  # noqa: E402,F401
                          routines_read)
# The reads of the local interface (runtime/ops_reads.py): the operations, and the one constant a test reads.
from ops_reads import agents, artifact, artifact_raw, artifacts, connections, conversation, costs, service_check, skills  # noqa: E402,F401
from ops_reads import commands, stop_runs, version  # noqa: E402,F401
from ops_reads import ARTIFACT_MAX_BYTES  # noqa: E402,F401


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
