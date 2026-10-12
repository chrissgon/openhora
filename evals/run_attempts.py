#!/usr/bin/env python3
"""The control of a run's attempts, as one module: the lab's runner (evals/eval_run.py) and the runtime's lab
facade (runtime/lab.py) both make the attempts of one model run through run() below.

It holds only control: waiting while the account is paused and taking a place of the shared lock; the fresh
folder outside the repository and its return to the run folder however an attempt ends; the base commit of the
copy and the settings check; the prompt, the index before the run, the adapter call and the changes after it;
the replacement of the passed values in everything an attempt left; the pause on the account limit, with the
attempt made again without counting; the classification of a failed attempt, in the lab's order; the retry rule,
the wait before a retry, and the folders that keep a failed attempt.

It measures nothing, and it is not a measurement file (it is not in FINGERPRINT_FILES of evals/eval_status.py):
the variants, the baseline and its checks, the case files, the grading, the evidence lines and the event's
records stay in evals/eval_run.py and evals/measure.py, and each caller adds its part through the hooks.

It imports nothing of the repository. Everything it needs of the runner it reads as an attribute of the object
it is given (`lab`), at the moment of the call: a name a test replaces on the runner is the one the loop uses.
The early-end rule and the replacement of values are names of evals/measure.py that the runner hands out.

Usage (a library, loaded by path by evals/eval_run.py, load_attempts()):
  python3 evals/run_attempts.py --help        print this text

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

EARLY_END_LIMIT = 200000  # characters of a reply the early-end rule reads: the lab's own limit

COUNT_KEYS = ("attempts", "early_ends", "timeouts", "refusals", "adapter_failures", "pauses", "redactions")
HOOKS = ("before_attempt", "build", "after_base", "stage", "before_run", "after_run", "judge")


def classify(lab, why, out_dir, refusal_markers, response, changed) -> tuple:
    """How one attempt failed, by the runner's functions and in the lab's order: (kind, detail). kind is
    "timeout", "refused", "auth", "adapter", "early_end", or None when the attempt is the run's result. why is
    what run_failure() returned; changed lists the files the attempt created, changed or deleted. The account
    limit is looked at before this, by run()."""
    if why and why.startswith("timeout"):
        return "timeout", None
    if why:
        refusal = lab.provider_refusal(out_dir, refusal_markers)
        if refusal:
            return "refused", refusal[:300]
        auth = lab.auth_refusal(out_dir)
        if auth:
            return "auth", auth
        return "adapter", None
    detail = lab.early_end(response[:EARLY_END_LIMIT], changed)
    return ("early_end", detail) if detail else (None, None)


def set_aside(lab, dest, prefix) -> str:
    """Keep what an attempt left in <dest>/<prefix>-<n>/ (the first n free) and clear the run folder for the next
    attempt, leaving the folders of lab.KEPT_PREFIXES where they are. Returns the folder it kept."""
    n = 1
    while os.path.exists(os.path.join(dest, f"{prefix}-{n}")):
        n += 1
    kept = os.path.join(dest, f"{prefix}-{n}")
    os.makedirs(kept)
    for item in os.listdir(dest):
        if not item.startswith(tuple(lab.KEPT_PREFIXES)):
            shutil.move(os.path.join(dest, item), os.path.join(kept, item))
    return kept


def _hook(hooks, name):
    return getattr(hooks, name, None) if hooks is not None else None


def attempt(lab, spec, hooks, counts) -> dict:
    """One attempt of a run, from the fresh folder to its return to spec["dest"]. Returns {"why", "carried",
    "delta", "changed", "staged"}: why is the adapter's failure (None when it exited 0), carried the first path of
    the copy that carries a tool's settings (the adapter was then not called), delta the changes of the copy when
    the adapter did not fail. counts["redactions"] is added to. after_run is called on every attempt in which the
    adapter was started, also when the call raised (why and delta are then None); when the attempt is already
    raising, an exception of after_run is dropped and the first one goes on. Whatever is raised, the passed values
    are replaced again and the folders return before it reaches the caller."""
    dest, values = spec["dest"], spec.get("values") or []
    pass_env = list(spec.get("pass_env") or [])
    root = lab.new_run_root(dest, names=tuple(spec.get("names") or ()))
    case_dir, out_tmp = os.path.join(root, "case"), os.path.join(root, "out")
    why, carried, delta, changed, staged, started, raised = None, None, None, [], [], False, False
    try:
        build = _hook(hooks, "build")
        if build:
            build(case_dir, root)
        env = lab.contained_env(root, pass_env)
        quiet = {"root": root, "network": "none"}  # the fixture commit: no secret, no network
        lab.isolate_git(case_dir, lab.contained_env(root), box=quiet)
        after_base = _hook(hooks, "after_base")
        if after_base:
            after_base(case_dir, root)
        carried = lab.settings_in(case_dir, spec.get("settings") or ())
        if not carried:
            stage = _hook(hooks, "stage")
            staged = list(stage(case_dir) or []) if stage else []
            prompt_path = os.path.join(root, "prompt.md")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(spec["prompt"])
            before_run = _hook(hooks, "before_run")
            if before_run:
                before_run(case_dir, root, staged)
            before = lab.file_index(case_dir, staged)
            web = bool(spec.get("web"))
            extra = spec.get("env_extra") or {}
            extra = dict((extra(root) if callable(extra) else extra) or {})
            env.update(extra)
            started = True
            why = lab.run_failure(spec["runner"], prompt_path, case_dir, spec["model"], out_tmp, env,
                                  spec.get("timeout"), spec.get("max_cost"), web, start_dir=root,
                                  box={"root": root, "runner": spec["runner"], "pass": pass_env + list(extra),
                                       "network": "open" if web else "proxy"})
            # Before anything is read or stored: each passed value is replaced by a marker, by exact value.
            counts["redactions"] += lab.redact_folder(case_dir, values, staged) + lab.redact_folder(out_tmp, values)
            if not why:
                delta = lab.changes(case_dir, before, staged)
                changed = delta["created"] + delta["modified"] + delta["deleted"]
    except BaseException:
        raised = True
        raise
    finally:
        try:
            after_run = _hook(hooks, "after_run")
            if started and after_run:
                try:
                    after_run(case_dir, root, why, delta, staged)
                except Exception:
                    if not raised:
                        raise
        finally:
            # Also when the attempt failed or was stopped: what it left goes to the run folder without the values.
            counts["redactions"] += lab.redact_folder(case_dir, values, staged) + lab.redact_folder(out_tmp, values)
            lab.return_run(root)
    return {"why": why, "carried": carried, "delta": delta, "changed": changed, "staged": staged}


def run(lab, spec, hooks=None) -> dict:
    """Every attempt of one run, until one is the run's result or the retries are spent.

    spec is a dictionary: "dest" (the run folder), "names" (what a temporary folder must not carry), "label" (the
    run in a pause's record), "runner", "model", "timeout", "max_cost", "web" (the adapter call), "account"
    ({"key", "markers", "probe"}), "refusal_markers", "settings", "pass_env", "values", "control", "tier",
    "retries", "prompt", "response_limit", and optionally "counts" (a dictionary updated in place) and
    "env_extra" ({name: value}, or a function of the attempt's fresh folder that returns one, called right before
    the adapter call: set in its environment and added to its box's passed names, never to the values replaced).

    hooks is an object whose attributes are optional callables: before_attempt(), build(case_dir, root),
    after_base(case_dir, root), stage(case_dir) -> list, before_run(case_dir, root, staged),
    after_run(case_dir, root, why, delta, staged), judge(info) -> object or None (info: {"why", "delta",
    "changed", "staged", "out"}).

    Returns {"status": "ok" | "failed" | "caller", "failure": None | {"kind", "reason", "detail"}, "why",
    "response", "delta", "changed", "staged", "counts", "events", "timing", "caller"}. Failure kinds: settings,
    stopped, auth, timeout, refused, adapter, early_end; reason is the adapter's failure as run_failure() gave it
    (None for settings, and when no adapter failed), detail the path that carries settings, the refusal or the
    early end. events lists {"event": "paused" | "retry" | "early_end", "kind", "attempt", "why", "detail",
    "kept"} in order. It prints nothing and builds no message, and it catches nothing: an exception of a hook or
    of the runner reaches the caller after the folders returned."""
    dest = spec["dest"]
    account = spec["account"]
    retries = spec["retries"]
    counts = spec.get("counts")
    if counts is None:
        counts = {}
    for key in COUNT_KEYS:
        counts.setdefault(key, 0)
    out = os.path.join(dest, "outputs")
    events = []
    result = {"status": "failed", "failure": None, "why": None, "response": "", "delta": None, "changed": [],
              "staged": [], "counts": counts, "events": events, "timing": {}, "caller": None}
    if os.path.isdir(dest) and any(not item.startswith(tuple(lab.KEPT_PREFIXES)) for item in os.listdir(dest)):
        set_aside(lab, dest, "before-resume")  # what an earlier call left in this run folder
    before_attempt = _hook(hooks, "before_attempt")

    def finish(status, kind=None, reason=None, detail=None):
        result["status"] = status
        result["failure"] = {"kind": kind, "reason": reason, "detail": detail} if kind else None
        result["response"] = lab.read_text(os.path.join(out, "response.md"), spec["response_limit"])
        return result

    while True:
        if before_attempt:
            before_attempt()
        lab.wait_while_paused(account["key"], account["probe"])
        counts["attempts"] += 1
        # The attempt happens outside the repository; its folders come back to dest when it ends, however it ends.
        with lab.Slots(spec["control"], spec["tier"], bool(spec.get("web"))):
            if before_attempt:  # called again: something may have changed while this run waited for its place
                before_attempt()
            made = attempt(lab, spec, hooks, counts)
        why, delta, changed = made["why"], made["delta"], made["changed"]
        result.update(why=why, delta=delta, changed=changed, staged=made["staged"])
        if made["carried"]:
            return finish("failed", "settings", None, made["carried"])
        if lab.STOPPING.is_set():
            return finish("failed", "stopped", why, None)
        if why and lab.account_limit(out, account["markers"]):
            # The account is exhausted: this is no result of the run. Everything on the account waits, and the run
            # starts again from its beginning afterwards: never retried into the limit, never counted as a timeout.
            counts["attempts"] -= 1
            counts["pauses"] += 1
            lab.start_pause(account["key"], spec["label"])
            events.append({"event": "paused", "kind": None, "attempt": counts["attempts"] + 1, "why": why,
                           "detail": None, "kept": None})
            events[-1]["kept"] = set_aside(lab, dest, "paused")
            continue
        judge = _hook(hooks, "judge")
        if judge:
            answer = judge({"why": why, "delta": delta, "changed": changed, "staged": made["staged"], "out": out})
            if answer is not None:
                result["caller"] = answer
                return finish("caller")
        response = lab.read_text(os.path.join(out, "response.md"), spec["response_limit"])
        kind, detail = classify(lab, why, out, spec.get("refusal_markers") or [], response, changed)
        if kind is None:
            break
        if kind == "auth":  # never retried: every later run with that key would meet the same refusal
            return finish("failed", "auth", why, detail)
        counts[lab.RETRY_KINDS[kind]] += 1
        if counts["attempts"] > retries:
            return finish("failed", kind, why, detail)
        kept = set_aside(lab, dest, "early-end" if kind == "early_end" else "failed")
        events.append({"event": "early_end" if kind == "early_end" else "retry", "kind": kind,
                       "attempt": counts["attempts"], "why": why, "detail": detail, "kept": kept})
        if kind == "adapter":  # a provider that is overloaded or limits the rate: not at once
            time.sleep(lab.RETRY_PAUSE * counts["attempts"])
    timing = {}
    try:
        with open(os.path.join(out, "timing.json"), encoding="utf-8") as f:
            timing = json.load(f)
    except (OSError, ValueError):
        pass
    if not isinstance(timing, dict):
        timing = {}
    timing.update(lab.run_ending(out))  # the stop reason and the turn count, beside the reply
    result.update(status="ok", failure=None, response=response, timing=timing)
    return result


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
