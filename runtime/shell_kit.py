#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the two network-free shells of the operations layer share: the local service (runtime/service.py) and the MCP
mode (runtime/mcp.py). One source for the pieces both used to carry as copies, and nothing else:

  - project_id, projects_of: the id a project has in a URL or a tool argument, and the project list checked at start;
  - STATUS_OF_CODE, status_of: the one mapping of an OpsError code to the status and the word a shell answers with;
  - EXPOSED_KINDS: the argument kinds of a row of the table that a shell can carry in JSON;
  - Jobs: the job registry (start, poll, keep, end the runs) and the project list of the `projects` answer;
  - Busy, Stopping: what a start of a job raises, for a shell to turn into its own answer.

It holds no rule about the work (which words a decision takes, what a state leads to, which channel may approve an
effect are the operations layer's and the store's), no request rule of a shell (the service's Host, Origin and token
checks, the MCP mode's channel) and reads no project file. It imports nothing of the runtime: the operations object a
shell works with (the module ops, or a stand-in) is given to it, and the layer map lets a shell import ops.py and this
module only. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import sys
import threading
import time
import traceback

JOBS_KEPT = 200                                           # finished jobs kept in memory
STOP_WAIT = 120.0                                         # seconds the shutdown waits for the threads of the jobs
EXPOSED_KINDS = ("int", "str", "text", "flag", "choice", "list")  # the argument kinds a route or a tool can carry in JSON
INTERNAL = "internal error"                               # what a job's failure shows when it is not the operation's own
STATUS_OF_CODE = {1: (409, "refused"), 2: (400, "usage"), 3: (412, "not_configured")}
JOB_FIELDS = ("job", "op", "project", "state", "result", "error", "started_at", "ended_at")


class Busy(Exception):
    """A job that calls a model is already running for the project."""


class Stopping(Exception):
    """The shell is stopping: no job starts."""


def project_id(path: str) -> str:
    """The id a project has in a URL or a tool argument: the first 12 hexadecimal characters of the sha256 of its real
    path. A path never appears in either."""
    return hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()[:12]


def status_of(error) -> tuple:
    """(status, word) of an exception of the operations layer: its code, as the shells map it; any other is
    (500, "internal")."""
    return STATUS_OF_CODE.get(getattr(error, "code", None), (500, "internal"))


def projects_of(paths, ops_module) -> list:
    """[{"id", "name", "path", "data_dir"}] for the project folders, each checked with the `config` operation (an
    unaccepted configuration is not a refusal). Raises the operations layer's OpsError for a folder that is not a
    configured project."""
    out, seen = [], set()
    for given in paths:
        path = os.path.abspath(given)
        if project_id(path) in seen:
            continue
        found = ops_module.config(path)
        seen.add(project_id(path))
        out.append({"id": project_id(path), "name": os.path.basename(os.path.realpath(path)) or path, "path": path,
                    "data_dir": found.get("data_dir")})
    return out


def default_log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Jobs:
    """What a shell is served from, in the part both shells share: the operations object (the module ops, or a
    stand-in), the projects, the log, and the jobs. A shell subclasses it and adds its own state."""

    def __init__(self, ops_module, projects, log=None):
        self.ops = ops_module
        self.projects = [dict(p) for p in projects]
        self.by_id = {p["id"]: p for p in self.projects}
        self.log = log or default_log
        self.lock = threading.Lock()
        self.jobs = {}
        self.counter = 0
        self.exclusive = {}      # project id -> what holds the project's model slot
        self.threads = []
        self.stopping = threading.Event()

    def running(self, project: str, ignoring=()) -> bool:
        """True when a job of the project is running; the jobs of the operations named in `ignoring` do not count."""
        with self.lock:
            return any(j["state"] == "running" and j["project"] == project and j["op"] not in ignoring
                       for j in self.jobs.values())

    def public(self, job: dict) -> dict:
        """A job as a shell shows it. The caller holds the lock when the job may still change."""
        return {key: job[key] for key in JOB_FIELDS}

    def start_job(self, project: str, op: str, call, queues: bool = False) -> tuple:
        """Start an operation that calls a model or a platform in a thread and return (the job, its thread, its public
        form as it was before the thread started). `project` is the project's id, `op` the verb of its row, `call` a
        function with no argument that makes the one call. An operation whose row says it calls a model (`model` not
        false) takes the project's model slot: Busy when another job or the dispatch loop holds it. With `queues` (the
        row's key: the operation queues its call while the router answers another request) a held slot is not a refusal:
        the job starts without the slot, and the operation itself finds the route lock held and queues the call. A row
        with `exclusive` false (dispatch, run-task) takes no slot. Stopping when the shell is shutting down."""
        row = self.ops.operations.by_name(op)
        exclusive = bool(row.get("exclusive", bool(row["model"])))
        with self.lock:
            if self.stopping.is_set():
                raise Stopping()
            if exclusive and project in self.exclusive:
                if not queues:
                    raise Busy(f"{self.exclusive[project]} is running for this project: a second one starts when it ends")
                exclusive = False
            self.counter += 1
            job = {"job": self.counter, "op": op, "project": project, "state": "running", "result": None,
                   "error": None, "started_at": now(), "ended_at": None}
            self.jobs[job["job"]] = job
            if exclusive:
                self.exclusive[project] = f"job {job['job']}"
            thread = threading.Thread(target=self._run_job, args=(job, call, exclusive), daemon=True)
            self.threads = [t for t in self.threads if t.is_alive()] + [thread]
            shown = self.public(job)
        thread.start()
        return job, thread, shown

    def job_shown(self, number: int):
        """The public form of the job with this number, or None."""
        with self.lock:
            job = self.jobs.get(number)
            return self.public(job) if job else None

    def _run_job(self, job: dict, call, exclusive: bool) -> None:
        result, error, state = None, None, "done"
        try:
            result = call()
        except Exception as e:  # a job never takes the shell down; its failure is the job's
            state = "failed"
            if isinstance(e, self.ops.OpsError):
                status, word = status_of(e)
                error = {"error": word, "message": str(e) if word != "internal" else INTERNAL, "status": status}
                if word != "internal" and getattr(e, "next", None):
                    error["next"] = e.next
            else:
                self.log(f"job {job['job']} ({job['op']}) failed:\n" + traceback.format_exc())
                error = {"error": "internal", "message": INTERNAL, "status": 500}
        with self.lock:
            job.update(state=state, result=result, error=error, ended_at=now())
            if exclusive and self.exclusive.get(job["project"]) == f"job {job['job']}":
                del self.exclusive[job["project"]]
            finished = [n for n, j in self.jobs.items() if j["state"] != "running"]
            for n in finished[:-JOBS_KEPT]:
                del self.jobs[n]
        self.job_ended(job)

    def job_ended(self, job: dict) -> None:
        """Called by the job's thread when the job ended and its slot is free, outside the lock. A shell overrides it (the messaging bridge starts the
        next waiting line there); an exception it raises ends the thread, so an override handles its own."""

    def end_runs(self, threads=(), wait: float = STOP_WAIT) -> int:
        """End the runs this process started and wait for the threads that held them (the jobs' and the `threads`
        given); the number still alive after `wait` seconds. ops.stop_runs is called at least once and is waited for;
        it is called again while a thread lives, because a job that was starting its run when the first call ended may
        have begun one."""
        deadline = time.monotonic() + wait
        while True:
            try:
                self.ops.stop_runs()
            except Exception:
                self.log("stop_runs failed:\n" + traceback.format_exc())
            with self.lock:
                alive = [t for t in list(threads) + self.threads
                         if t.is_alive() and t is not threading.current_thread()]
            if not alive or time.monotonic() > deadline:
                return len(alive)
            for thread in alive:
                thread.join(0.5)

    def projects_list(self) -> dict:
        """{"projects": [...]}: each project with its `folder` (the absolute path the shell was given, which is the word
        a `--project` takes: the page writes the restart line with it), its configuration's hash and whether it was
        accepted, and, when it was, the number of pending decisions, the tasks that run (`running_tasks`, their ids;
        `running_task` is the oldest, kept for a page that reads one) and the request a router run holds (`routing_request`, from `routing` of each request of `status`; null when none). A project whose
        configuration is not accepted (or cannot be read) is listed with accepted false, the operation's refusal as
        `message` and no counts: never refused."""
        out = []
        for project in self.projects:
            entry = {"id": project["id"], "name": project["name"], "folder": project["path"], "config": {"accepted": False}}
            try:
                found = self.ops.config(project["path"])
            except self.ops.OpsError as e:
                entry["message"] = str(e)
                out.append(entry)
                continue
            entry["config"] = {"sha256": found["sha256"], "accepted": bool(found["accepted"])}
            try:
                state = self.ops.status(project["path"])
            except self.ops.OpsError as e:
                entry["message"] = str(e)
            else:
                entry["open_pending"] = len(state["pending"])
                entry["running_tasks"] = sorted(t["id"] for r in state["requests"] for t in r["tasks"] if t["state"] == "running")
                entry["running_task"] = entry["running_tasks"][0] if entry["running_tasks"] else None
                entry["routing_request"] = next((r["id"] for r in state["requests"] if r.get("routing")), None)
            out.append(entry)
        return {"projects": out}
