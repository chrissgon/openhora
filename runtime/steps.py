#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step engine: how a step task runs, one step after another, resumably, with stops for the person (package P5).

A step task is a task of a request that runs no skill (providers/store/sqlite.py, "the step task"): code runs it, in a process of
its own, and no model is involved. Its *kind* is a word of the registry below, and the kind declares everything that is specific
to the work: the steps in the order they run, which of them stop for the person, the function that executes each step, the files
the task may write (its footprint, which the admission rule weighs against the files other tasks write) and how its arguments are
checked. The engine knows none of that: it imports no module of any feature (no captions, no media, no theme, no converter), so a
kind is a module of its own, `runtime/step_<kind>.py`, that registers itself, and adding a kind adds a file and edits no step of
the engine. The kinds registered today: `ingest` (runtime/step_ingest.py), which wraps `sources.import_version`. The kinds that
write a file (P8) and the media pipeline of the short-video rebase register the same way.

  Kind(name, order, executors, stops=(), decisions={}, footprint=..., check=..., cleanup={}, side_steps={}, errors=(), prepared=None,
       rejected={}, unattended=False, brings_source=False)
  register(kind) / kind_of(name) / load_builtin()   the registry; load_builtin imports every runtime/step_*.py
  plan_task(kind, args, key=, title=, text=, ...)   a plan's task for a step: the kind, its checked arguments (canonical, so the plan
                                                    hash covers them) and the footprint the kind derived. StepFailure when the kind is
                                                    unknown or the arguments are refused
  add_task(store, conn, kind, args, key=, ...)      the same, added to a request through store.step_task_add
  new_state(kind) / summary(kind, state) / next_step(kind, state)   the engine's progress, kept in the task row (`step_state`)
  run(ctx, kind, state)                             run the steps from the first that is not done, until a stop, a failure or the end
  prepare_again(ctx, kind, state, step)             start over from a step: it and every later one become pending and the files they made
                                                    are removed by the kind's cleanup
  write_file(ctx, path, data)                       the one way a kind writes a file in the project: inside its declared footprint only,
                                                    never in or into the sources folder, through O_NOFOLLOW at every step

Nothing creates a step task today but tests and the store's own functions: the flow files learn the key `step` with P6, and a plan
that carries a step task is built by plan.from_flow from a flow that has one.

Rules that hold here, each with a test (runtime/tests/test_steps_engine.py):

  - A step already done is not run again. A step that fails leaves the task `failed` and resumable at that step: a retry of the task
    starts there, with the earlier results kept.
  - Every result is recorded as closed words and numbers (a code, a count, a hash, a name, an id). The text of a document, a page or a
    tool's output is never in the state, in a task's note or in a decision's body: a refusal is read for its closed code only.
  - A stop opens one pending decision of kind `question` on the task and leaves it `waiting`. The answer makes the task ready again, and
    the next run goes on after the stop only if the answer is the verdict `continue`: the word `stop` ends the step `failed` (code
    `rejected`, the kind's `rejected` hook first), and any other text is no verdict, so the person is asked again. A decision is bound to
    the stop and to the cycle it was opened in (its payload names the kind, the step and the cycle, which prepare_again advances), so
    an answer given before a step was prepared again never passes the stop of the new cycle, and a decision already handled passes
    nothing a second time.
  - The only stop is `review`. An `approval` of exact content is not a stop of this engine: it needs the effect gate (the content's
    hash, the terminal and the page only), which P8 brings with the kinds that write.
  - The request of the task cancelled: the engine stops without a word of failure (Cancelled).
  - Nothing here runs a model, and nothing leaves the machine unless a kind's executor does it.

The engine is given a Context by the process that runs the task (runtime/ops_steps.py): `move`, `save`, `alive`, `decisions`, `now` and
the services a kind asks for. It calls the store through those callbacks and nothing else.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import dataclasses
import errno
import hashlib
import importlib
import os
import re
import sys
from typing import Callable

HERE = os.path.dirname(os.path.abspath(__file__))

OWNER = "runtime"                         # the agent of every step task (a copy of the store's STEP_OWNER; a test holds them equal)
STOPS = ("review",)                       # the words a kind's stops may use: the person reviews what was made. No `approval`: see the module text
CONTINUE, STOP_WORD = "continue", "stop"  # the verdicts of a stop; any other answer is no verdict
VERDICTS = (CONTINUE, STOP_WORD)
LINK_ERRNOS = (errno.ELOOP, errno.ENOTDIR)  # what O_NOFOLLOW | O_DIRECTORY answers for a link where a folder must be (the platform's own numbers)
PLACEHOLDER = re.compile(r"<[^<>/]*>")
REL_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
VERDICT_LINE = "Answer `continue` to go on, or `stop` to end this step. Any other answer is no verdict: you will be asked again."
NOT_A_VERDICT = "Your last answer was neither `continue` nor `stop`, so nothing went on. "
STATE_VERSION = 1
KIND_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
STEP_NAME = re.compile(r"[a-z][a-z0-9-]{0,30}")
CODE = re.compile(r"[a-z][a-z0-9_]{1,40}")
FIELD = re.compile(r"[A-Za-z0-9_.\[\]-]{0,40}")
FOOTPRINT_MAX = 20                        # paths a kind may declare for one task (the store's STEP_FOOTPRINT_MAX)
BUILTIN = re.compile(r"step_[a-z0-9_]+\.py")


class StepFailure(Exception):
    """A step that stopped: a closed `code`, the `field` it names (never text), the `provider` word and what to do next
    (`next`: a command the person runs, or one fixed sentence)."""

    def __init__(self, code: str, field: str = "", provider: str = "", next: str = ""):
        super().__init__(f"{code} {field}".strip())
        self.code, self.field, self.provider, self.next = code, field, provider, next


class Cancelled(Exception):
    """The request of the task was cancelled: the engine stops without a word of failure."""


@dataclasses.dataclass(frozen=True)
class Kind:
    """What a step kind declares.

    name        lowercase words joined by hyphens: the word the task row carries (`step_kind`)
    order       the names of the steps, in the order they run
    executors   {step: function(ctx, state) -> dict}: it does the step and returns its result, closed words and numbers; a step
                that stops for the person has no executor
    stops       the steps (a subset of STOPS) where the task waits for the person; each needs a decision builder
    decisions   {stop: function(ctx, state) -> {"title", "body"[, "payload"]}}: the question the person answers, in fixed words
    footprint   function(args) -> the project paths a task of this kind may write, as declared paths (a placeholder is a wildcard):
                derived from the kind, never from free text
    check       function(args) -> the arguments, checked and normalised; StepFailure("bad_args", field) when they are refused
    cleanup     {step: function(ctx, state)}: removes the files the step made, when it is prepared again
    side_steps  {step: function(state) -> bool}: a step that runs when it is due, is recorded like the others, never fails the task
                (its failure is recorded `skipped`) and is not listed in the summary
    errors      exception classes of the kind's own modules whose `code` and `field` become a StepFailure
    prepared    function(ctx, state, index): called after a step is prepared again, with the index of the first step reset
    rejected    {stop: function(ctx, state)}: what the kind does when the person answers `stop` at that stop (before the step fails with
                the code `rejected`); a stop with no hook only fails
    unattended  whether the dispatcher may start a task of this kind on its own (a routine, a round): False unless the kind says so; a
                task of a kind that is not unattended starts only by the person's own start (run-next, run-step)
    brings_source  whether the kind's `source` argument names a source the tasks after it receive (`ingest`): a workflow's task that
                depends on such a step receives that source (flow_files.sources_of), and the flow check counts it (runtime/flow_check.py)
    """

    name: str
    order: tuple
    executors: dict
    stops: tuple = ()
    decisions: dict = dataclasses.field(default_factory=dict)
    footprint: Callable = lambda args: ()
    check: Callable = lambda args: args
    cleanup: dict = dataclasses.field(default_factory=dict)
    side_steps: dict = dataclasses.field(default_factory=dict)
    errors: tuple = ()
    prepared: Callable = None
    rejected: dict = dataclasses.field(default_factory=dict)
    unattended: bool = False
    brings_source: bool = False

    def steps(self) -> tuple:
        """The steps the summary lists: the order, without the side steps."""
        return tuple(n for n in self.order if n not in self.side_steps)


@dataclasses.dataclass
class Context:
    """What the process that runs the task gives the engine.

    move(word, note, pending, resolve, state)   move the task (`running`, `waiting` with a pending decision, `failed` or `done`) and
                                                store the engine's state with the move; returns {"pending_id"}; raises Cancelled when
                                                the request was cancelled
    save(state)                                 store the engine's state without moving the task; raises Cancelled likewise
    alive()                                     raises Cancelled when the request of the task was cancelled
    decisions()                                 the task's pending decisions, [{"id", "status", "resolution", "answer", "payload"}]
    now()                                       the time as text (ISO 8601)
    footprint                                   the paths the task may write, as its kind declared them (write_file reads it)
    protected(path)                             whether a path may never be written (the sources folder): write_file refuses it
    services                                    {name: what a kind asks for}: the seams a test replaces
    """

    task_id: int
    request_id: int
    project: str
    args: dict
    move: Callable
    save: Callable
    alive: Callable
    decisions: Callable
    now: Callable
    footprint: tuple = ()
    protected: Callable = lambda path: False
    services: dict = dataclasses.field(default_factory=dict)


# --- the registry ------------------------------------------------------------------------------------------------------------

REGISTRY = {}


def check_kind(kind: Kind) -> None:
    """A kind is well formed or ValueError says how it is not: a name, an order of distinct step names, an executor for every step
    that does not stop, a decision for every stop, stops from the closed list, side steps that are steps."""
    if not isinstance(kind.name, str) or not KIND_NAME.fullmatch(kind.name) or len(kind.name) > 40:
        raise ValueError(f"step kind {kind.name!r}: a name is lowercase words joined by hyphens, at most 40 characters")
    order = tuple(kind.order)
    if not order or len(set(order)) != len(order) or not all(isinstance(n, str) and STEP_NAME.fullmatch(n) for n in order):
        raise ValueError(f"step kind {kind.name}: its order is a list of distinct step names")
    unknown = [s for s in kind.stops if s not in STOPS or s not in order]
    if unknown:
        raise ValueError(f"step kind {kind.name}: a stop is one of {', '.join(STOPS)} and a step of its order: {unknown[0]}")
    for name in order:
        if name in kind.stops:
            if name not in kind.decisions:
                raise ValueError(f"step kind {kind.name}: the stop {name} has no decision")
        elif name not in kind.executors:
            raise ValueError(f"step kind {kind.name}: the step {name} has no executor")
    extra = [n for n in list(kind.executors) + list(kind.decisions) + list(kind.side_steps) + list(kind.cleanup) if n not in order]
    if extra:
        raise ValueError(f"step kind {kind.name}: {extra[0]} is not a step of its order")
    if any(n in kind.stops for n in kind.side_steps) or len(kind.side_steps) == len(order):
        raise ValueError(f"step kind {kind.name}: a side step is not a stop, and some step is not a side step")


def register(kind: Kind) -> Kind:
    """Add a kind to the registry. A name taken, or a kind that is not well formed: ValueError."""
    check_kind(kind)
    if kind.name in REGISTRY:
        raise ValueError(f"step kind {kind.name} is registered already")
    REGISTRY[kind.name] = kind
    return kind


def load_builtin() -> list:
    """Import every runtime/step_*.py so that its kind registers itself; returns the kind names registered. The modules are
    the checkout's own: the engine names none of them."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    for name in sorted(os.listdir(HERE)):
        if BUILTIN.fullmatch(name):
            found = getattr(importlib.import_module(name[:-3]), "KIND", None)    # a module already imported registered itself once
            if isinstance(found, Kind) and found.name not in REGISTRY:
                register(found)
    return sorted(REGISTRY)


def sourcing_kinds() -> tuple:
    """The names of the registered kinds that bring a source in (Kind.brings_source), sorted."""
    load_builtin()
    return tuple(sorted(n for n, k in REGISTRY.items() if k.brings_source))


def kind_of(name) -> Kind:
    """The registered kind of that name, or StepFailure(unknown_kind): a task whose kind this checkout does not have fails."""
    if name not in REGISTRY:
        load_builtin()
    if name not in REGISTRY:
        raise StepFailure("unknown_kind", "step")
    return REGISTRY[name]


# --- the task a plan or a request adds -----------------------------------------------------------------------------------------


def footprint_of(kind: Kind, args: dict) -> list:
    """The paths a task of this kind with these arguments may write, as the kind declares them: sorted, distinct, at most
    FOOTPRINT_MAX. A kind that declares something else than relative paths is refused by the store's checks."""
    found = list(kind.footprint(args) or ())
    if len(found) > FOOTPRINT_MAX or not all(isinstance(p, str) for p in found):
        raise StepFailure("bad_footprint", "footprint")
    return sorted(set(found))


def plan_task(kind_name: str, args, *, key: str, title: str, text: str, depends_on=(), milestone: bool = False) -> dict:
    """A plan's task for a step: {"key", "step", "args", "footprint", "agent", "title", "text", "depends_on", "milestone",
    "web"}. The arguments are the kind's checked ones, so the plan hash (runtime/plan.py plan_hash) covers exactly what will run;
    the footprint is derived from the kind and the arguments. StepFailure when the kind is unknown or the arguments are refused."""
    kind = kind_of(kind_name)
    checked = kind.check(args if args is not None else {})
    if not isinstance(checked, dict):
        raise StepFailure("bad_args", "args")
    return {"key": key, "step": kind.name, "args": checked, "footprint": footprint_of(kind, checked), "agent": OWNER,
            "title": title, "text": text, "depends_on": list(depends_on), "milestone": bool(milestone), "web": False}


def add_task(store, conn, kind_name: str, args, *, key: str, title: str, text: str, request_id=None, depends_on=None,
             milestone: bool = False) -> dict:
    """Add a step task through the store (store.step_task_add) with the arguments the kind checked and the footprint it derived.
    Returns the store's {"request", "task", "state"}."""
    planned = plan_task(kind_name, args, key=key, title=title, text=text, depends_on=depends_on or (), milestone=milestone)
    return store.step_task_add(conn, key=key, title=title, text=text, step=planned["step"], args=planned["args"],
                               footprint=planned["footprint"], request_id=request_id, depends_on=depends_on, milestone=milestone)


# --- the state ------------------------------------------------------------------------------------------------------------------


def new_state(kind: Kind) -> dict:
    return {"version": STATE_VERSION, "kind": kind.name, "steps": {}, "failure": None, "decisions": {}, "cycle": 0, "handled": {}}


def state_of(kind: Kind, stored) -> dict:
    """The engine's state of a task: new when the task never ran, else the stored one. StepFailure(state_unreadable) when what is
    stored is not the state of this kind."""
    if stored is None:
        return new_state(kind)
    if not isinstance(stored, dict) or stored.get("version") != STATE_VERSION or stored.get("kind") != kind.name \
            or not isinstance(stored.get("steps"), dict) or not isinstance(stored.get("decisions"), dict):
        raise StepFailure("state_unreadable", "step_state")
    return stored


def step_status(state: dict, name: str) -> str:
    return (state["steps"].get(name) or {}).get("status", "pending")


def summary(kind: Kind, state: dict) -> dict:
    """Every step and its status, in order: what a shell shows of the task."""
    return {name: step_status(state, name) for name in kind.steps()}


def next_step(kind: Kind, state: dict):
    """The first step that is not done, or None."""
    for name in kind.steps():
        if step_status(state, name) != "done":
            return name
    return None


# --- what a failure is -----------------------------------------------------------------------------------------------------------


def failure_record(name: str, failure: StepFailure, at: str) -> dict:
    code = failure.code if CODE.fullmatch(failure.code or "") else "failed"
    return {"step": name, "code": code, "field": failure.field if FIELD.fullmatch(failure.field or "") else "",
            "provider": failure.provider if CODE.fullmatch(failure.provider or "") else "", "next": failure.next, "at": at}


def note_of(step: str, failure: StepFailure) -> str:
    """The task's note for a failed step: the step, the closed code, the field it names and the sentence that says what to do."""
    record = failure_record(step, failure, "")
    text = f"{step}: {record['code']}" + (f" {record['field']}" if record["field"] else "")
    return text + (f" -- {failure.next}" if failure.next else "")


# --- running -------------------------------------------------------------------------------------------------------------------


def _execute(ctx: Context, kind: Kind, state: dict, name: str) -> dict:
    """One step's executor; whatever goes wrong inside it is a StepFailure with a closed code. Cancelled passes through."""
    try:
        outcome = kind.executors[name](ctx, state)
    except (StepFailure, Cancelled):
        raise
    except kind.errors as e:
        raise StepFailure(getattr(e, "code", "failed"), getattr(e, "field", "")) from None
    except OSError:   # a full disk, a folder that cannot be written: a closed word, never the system's message
        raise StepFailure("io_error", "") from None
    except (KeyError, TypeError, AttributeError, ValueError, IndexError, RecursionError):   # a result that has not the shape its step promises
        raise StepFailure("step_output_invalid", name[:40]) from None
    except Exception:   # a bug of the kind: the failure is a closed record on the step, never its message
        raise StepFailure("step_error", name[:40]) from None
    if not isinstance(outcome, dict):
        raise StepFailure("step_output_invalid", name[:40])
    return outcome


def verdict_of(answer):
    """The verdict an answer is: `continue` or `stop` when the whole answer is that word (case and a closing full stop aside), else None.
    Free text is never a verdict."""
    text = (answer or "").strip().rstrip(".").strip().casefold()
    return text if text in VERDICTS else None


def _decision_of(ctx: Context, kind: Kind, state: dict, name: str):
    """The newest pending decision of this task that is for this stop of this kind in the stop's current cycle and that no run has
    handled yet, or None. A decision names its kind, step and cycle in its payload, so it is found again whatever the state recorded,
    and a decision of an earlier cycle (before prepare_again) or one already handled is never found."""
    want = {"kind": kind.name, "step": name}
    cycle, handled = state.get("cycle", 0), (state.get("handled") or {}).get(name, 0)
    mine = [d for d in ctx.decisions() if (d.get("payload") or {}).get("step") == want
            and (d.get("payload") or {}).get("cycle", 0) == cycle and d["id"] > handled]
    return max(mine, key=lambda d: d["id"]) if mine else None


def _guarded(name: str, build: Callable, *args):
    """Call a kind's function for a step; whatever it raises but a StepFailure or Cancelled is a closed failure of the step."""
    try:
        return build(*args)
    except (StepFailure, Cancelled):
        raise
    except Exception:
        raise StepFailure("step_error", name[:40]) from None


def _stop_at(ctx: Context, kind: Kind, state: dict, name: str):
    """A stop. The person answered its decision with `continue`: the step is done and None is returned, the run goes on. With `stop`:
    the kind's hook, then the step fails (`rejected`). With any other text: no verdict, a new decision says so. Otherwise the decision is
    opened (the task becomes `waiting` with it, and any other open decision of the task is cancelled) and the stop is returned."""
    found = _decision_of(ctx, kind, state, name)
    lead = ""
    if found is not None and found.get("status") == "resolved" and found.get("resolution") == "answered":
        state.setdefault("handled", {})[name] = found["id"]          # one decision passes or ends the stop once
        verdict = verdict_of(found.get("answer"))
        if verdict == CONTINUE:
            state["steps"][name] = {"status": "done", "at": ctx.now(), "result": {}}
            state["decisions"].pop(name, None)
            state["failure"] = None
            ctx.save(state)
            return None
        if verdict == STOP_WORD:
            if name in kind.rejected:
                _guarded(name, kind.rejected[name], ctx, state)
            raise StepFailure("rejected", name[:40], "", "retry the task to be asked again, or prepare the step again")
        lead = NOT_A_VERDICT
    built = _guarded(name, kind.decisions[name], ctx, state)
    pending = {"kind": "question", "title": built["title"], "body": lead + built["body"] + "\n\n" + VERDICT_LINE,
               "payload": {**(built.get("payload") or {}), "step": {"kind": kind.name, "step": name},
                           "cycle": state.get("cycle", 0), "verdicts": list(VERDICTS)}}
    state["steps"][name] = {"status": "waiting", "at": ctx.now(), "result": {}}
    state["failure"] = None
    moved = ctx.move("waiting", None, pending, None, state)
    state["decisions"][name] = moved["pending_id"]
    ctx.save(state)
    return {"ok": True, "stopped": name, "pending": moved["pending_id"]}


def _side_step(ctx: Context, kind: Kind, state: dict, name: str) -> None:
    """Run a side step when it is due and not done. A failure is recorded as `skipped` with its closed code and field and nothing
    else moves: not the task, not a decision that may be open, not the failure of the task."""
    if step_status(state, name) == "done" or not kind.side_steps[name](state):
        return
    ctx.alive()
    try:
        outcome = _execute(ctx, kind, state, name)
    except StepFailure as failure:
        state["steps"][name] = {"status": "skipped", "at": ctx.now(), "result": {
            "code": failure_record(name, failure, "")["code"], "field": failure_record(name, failure, "")["field"]}}
    else:
        state["steps"][name] = {"status": "done", "at": ctx.now(), "result": outcome}
    ctx.save(state)


def run(ctx: Context, kind: Kind, state: dict) -> dict:
    """Run the steps from the first that is not done, until a stop, a failure or the end. The task is `running` while this runs
    (the process that runs it claimed it). Returns {"ok": True, "done": True, "steps"} at the end (the task is `done`),
    {"ok": True, "stopped": step, "pending": id, "steps"} at a stop (the task is `waiting`), or {"ok": False, "failed": step,
    "code", "field", "next", "steps"} (the task is `failed` and resumes at that step); a cancelled request gives {"ok": False,
    "failed": None, "code": "cancelled", ...}. It never raises for a step."""
    name, result = None, {"ok": True, "done": True}
    try:
        for name in kind.order:
            if name in kind.side_steps:
                _side_step(ctx, kind, state, name)
                continue
            if step_status(state, name) == "done":
                continue
            ctx.alive()
            if name in kind.stops:
                stopped = _stop_at(ctx, kind, state, name)
                if stopped is not None:
                    result = stopped
                    break
                continue
            outcome = _execute(ctx, kind, state, name)
            state["steps"][name] = {"status": "done", "at": ctx.now(), "result": outcome}
            state["failure"] = None
            ctx.save(state)
        else:
            ctx.alive()
            state["failure"] = None
            ctx.move("done", None, None, None, state)
    except StepFailure as failure:
        name = name or kind.order[0]
        state["steps"][name] = {"status": "failed", "at": ctx.now(), "result": {}}
        state["failure"] = failure_record(name, failure, ctx.now())
        try:
            ctx.move("failed", note_of(name, failure), None, None, state)
        except Cancelled:
            return {"ok": False, "failed": None, "code": "cancelled", "field": "", "next": "", "steps": summary(kind, state)}
        return {"ok": False, "failed": name, "code": state["failure"]["code"], "field": state["failure"]["field"],
                "next": failure.next, "steps": summary(kind, state)}
    except Cancelled:
        return {"ok": False, "failed": None, "code": "cancelled", "field": "", "next": "", "steps": summary(kind, state)}
    return {**result, "steps": summary(kind, state)}


def prepare_again(ctx: Context, kind: Kind, state: dict, step: str) -> dict:
    """Start the task over from `step`: that step and every later one become pending, the files they made are removed (the kind's
    cleanup), and a decision recorded for them is forgotten. A side step is not prepared here. The caller moves the task
    (a failed task is retried); this changes only the engine's state. Returns {"reset": the steps that were reset}."""
    if step not in kind.order or step in kind.side_steps:
        raise StepFailure("unknown_step", "step")
    start = kind.order.index(step)
    reset = [n for n in kind.order[start:] if n in state["steps"]]
    for name in kind.order[start:]:
        if name in kind.cleanup:
            kind.cleanup[name](ctx, state)
        state["steps"].pop(name, None)
        state["decisions"].pop(name, None)
    state["cycle"] = state.get("cycle", 0) + 1       # a decision of the cycle before never passes a stop of this one
    if kind.prepared is not None:
        kind.prepared(ctx, state, start)
    state["failure"] = None
    ctx.save(state)
    return {"reset": reset}


def _segment(pattern: str):
    return re.compile("[^/]+".join(re.escape(p) for p in PLACEHOLDER.split(pattern)))


def in_footprint(footprint, rel: str) -> bool:
    """Whether the relative path is one a task may write: it matches a declared path of its footprint, a placeholder standing for one
    path segment, or lies under a declared folder (a path ending in "/")."""
    parts = rel.split("/")
    for declared in footprint:
        folder = declared.endswith("/")
        want = declared.rstrip("/").split("/")
        if (len(parts) > len(want) if folder else len(parts) == len(want)) and \
                all(_segment(w).fullmatch(have) for w, have in zip(want, parts)):
            return True
    return False


def write_file(ctx: Context, rel: str, data: bytes) -> dict:
    """Write one file in the project: the one way a kind writes. The path is relative and plain (letters, digits, dots, hyphens and
    underscores in segments), must lie inside the footprint the kind declared for the task, and may not be, or lie inside, what the
    context protects (the sources folder, limits L23 and L26). Every folder on the way is opened with O_NOFOLLOW (a link anywhere is
    refused) and the file is made under a temporary name and renamed over its place, so a reader never sees half a file. Returns
    {"path", "bytes", "sha256"}. StepFailure: bad_path, outside_footprint, protected_path, path_unsafe, io_error."""
    import hashlib
    if not isinstance(rel, str) or not REL_PATH.fullmatch(rel) or any(p in (".", "..") for p in rel.split("/")) \
            or not isinstance(data, (bytes, bytearray)):
        raise StepFailure("bad_path", "path")
    if not in_footprint(ctx.footprint, rel):
        raise StepFailure("outside_footprint", "path")
    root = os.path.realpath(ctx.project)
    parts = rel.split("/")
    if ctx.protected(os.path.join(root, *parts)):
        raise StepFailure("protected_path", "path")
    opened = []
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        opened.append(fd)
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o755, dir_fd=fd)
            except FileExistsError:
                pass
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            opened.append(fd)
        temporary = f".tmp-{os.getpid()}-{os.urandom(4).hex()}"
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
        try:
            with os.fdopen(out, "wb") as f:
                f.write(bytes(data))
            os.replace(temporary, parts[-1], src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=fd)
            except OSError:
                pass
            raise
    except OSError as e:
        raise StepFailure("path_unsafe" if e.errno in LINK_ERRNOS else "io_error", "path") from None
    finally:
        for descriptor in opened:
            os.close(descriptor)
    return {"path": rel, "bytes": len(data), "sha256": hashlib.sha256(bytes(data)).hexdigest()}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
