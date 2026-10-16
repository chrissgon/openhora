#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Orphan containers of the eval harness, removed on recovery (package P-OPS, finding I6).

A run of the lab starts, for each run, a container (`wb-eval-run-<run id>`), a key proxy (`wb-eval-keys-<run id>`) and an
internal network (`wb-eval-held-<run id>`). When the process that started them dies, the container ends with its command
(`--rm`), but the key proxy and the network can stay. The executor labels everything it makes `wb.eval=1` and, for a run's own
three, `wb.eval.run=<run id>`. This module finds what a dead run left and removes it.

What is selected (and only this): a container or network whose NAME is a run's own, that is `wb-eval-run-<id>`, `wb-eval-keys-<id>`
(containers) or `wb-eval-held-<id>` (networks), with `<id>` exactly 16 hexadecimal characters. A label alone selects nothing: the
label `wb.eval.run=<id>` only says how the name was found (`via`: "label" when it agrees with the name, else "name", for what was
started before the label existed). The harness's long-lived shared objects are never selected, whatever their labels: its egress proxy
(`wb-eval-proxy-<tag>`), its networks (`wb-eval-net-<tag>`, `wb-eval-route-<name>-<tag>`, `wb-eval-open-...`) and its shared key holders
(`wb-eval-keys-<12 hex tag>`, `wb-eval-keys-strong-...`, `wb-eval-keys-net-...`, `wb-eval-strong-held-...`) are named after a hash of the
container definition, not a run id. `is_shared` says so, and a candidate is checked against it again just before its removal.

The automatic mode is conservative and reads no lock (no lock says whether a run is live: the lab's lock folder follows the
environment's temporary folder, so two processes of one machine can look at different ones). It removes only what cannot belong to a
run in progress:
  - a run container that has ended (`exited` or `dead`);
  - a key proxy whose run container no longer exists (in any state), past GRACE_SECONDS (30 minutes: the executor starts the proxy a
    moment before the container it serves, and a run's setup commands can take 15 minutes);
  - a network no container of its run is on any more, past the same grace.
A RUNNING run container is never removed automatically, whatever its age. The one way to remove one is the explicit command
`python3 runtime/upkeep.py containers --include-running`, which removes a running run container only when it is older than
RUNNING_GRACE_SECONDS (6 hours), and which a person types: a battery started with a longer timeout is the person's to judge.
An object whose age or state cannot be read is kept.

A stop (R18, runtime/run_stop.py) uses the same names for one more job, `remove_runs`: the objects of the runs a stopped process tree named, whatever their age or state, each shared object checked again before its removal.

The container tool is a function `tool(*args) -> (returncode, stdout)`; production passes the facade's `lab.container_tool`, a test passes a
fake. No test of this repository reaches the real docker.

Standard library only. Runs on Python 3.9: python3 runtime/orphans.py --help
"""
from __future__ import annotations

import datetime
import json
import re
import sys

RUN_ID = re.compile(r"[0-9a-f]{16}")
LABEL_RUN = "wb.eval.run"                    # the label the harness puts on a run's own objects
NAME_PREFIXES = {"container": ("wb-eval-run-", "wb-eval-keys-"), "network": ("wb-eval-held-",)}
SHARED_PREFIXES = ("wb-eval-proxy-", "wb-eval-net-", "wb-eval-route-", "wb-eval-keys-strong-", "wb-eval-keys-net-", "wb-eval-open-",
                   "wb-eval-strong-held-")                                  # the harness's shared proxy, networks and key holders
SHARED_KEYS = re.compile(r"wb-eval-keys-[0-9a-f]{12}")                      # a shared key holder: named after the definition's tag
GRACE_SECONDS = 1800
RUNNING_GRACE_SECONDS = 6 * 3600
ENDED = ("exited", "dead")


def is_shared(name: str) -> bool:
    """Whether a name is one of the harness's long-lived shared objects, never a run's: its proxy, its networks, a key holder named
    after the definition's tag. Never removed by the sweep."""
    return name.startswith(SHARED_PREFIXES) or bool(SHARED_KEYS.fullmatch(name))


def run_of_name(kind: str, name: str):
    """The run id a name carries (`wb-eval-run-<id>`, `wb-eval-keys-<id>`, `wb-eval-held-<id>`), or None: the tail must be exactly 16
    hexadecimal characters."""
    for prefix in NAME_PREFIXES[kind]:
        if name.startswith(prefix):
            tail = name[len(prefix):]
            return tail if RUN_ID.fullmatch(tail) else None
    return None


def _labels(text) -> dict:
    out = {}
    for part in str(text or "").split(","):
        key, _, value = part.partition("=")
        if key.strip():
            out[key.strip()] = value.strip()
    return out


def parse_created(text):
    """The creation time of `docker ps` / `docker network ls` ("2026-10-15 09:30:12 +0000 UTC", or an RFC 3339 time) as a POSIX
    time, or None when it cannot be read."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.\d+)?\s*(Z|[+-]\d{2}:?\d{2})?", str(text or "").strip())
    if not m:
        return None
    offset = m.group(3) or "Z"
    if offset == "Z":
        offset = "+0000"
    offset = offset.replace(":", "")
    try:
        return datetime.datetime.strptime(f"{m.group(1)} {m.group(2)} {offset}", "%Y-%m-%d %H:%M:%S %z").timestamp()
    except ValueError:
        return None


def _listing(tool, kind: str):
    """[{"name", "run", "via", "created", "state"}] of every container or network the sweep may select (a run's own name), or None when the
    tool failed. One record per line of `--format '{{json .}}'`; "state" is docker's, None for a network."""
    args = ("ps", "-a", "--no-trunc") if kind == "container" else ("network", "ls", "--no-trunc")
    code, text = tool(*args, "--format", "{{json .}}")
    if code != 0:
        return None
    found = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        name = str(row.get("Names") or row.get("Name") or "").split(",")[0].strip()
        run = run_of_name(kind, name) if name else None
        if run is None or is_shared(name):
            continue
        found.append({"name": name, "run": run, "via": "label" if _labels(row.get("Labels")).get(LABEL_RUN) == run else "name",
                      "created": parse_created(row.get("CreatedAt")), "state": (str(row.get("State")).lower() if kind == "container" and row.get("State") else None)})
    return found


def sweep(tool, *, now: float, dry_run: bool = False, include_running: bool = False) -> dict:
    """Remove what a dead run left. `tool` is the container tool, `now` a POSIX time. Returns {"removed": [{"kind", "name", "run", "via"}],
    "kept": [{"name", "why"}], "problem"}. `problem` is a sentence when the tool could not list (nothing is removed for what it could
    not list). dry_run lists and removes nothing. include_running is the explicit mode: a running run container older than
    RUNNING_GRACE_SECONDS is removed too; the automatic pass never sets it."""
    out = {"removed": [], "kept": [], "problem": None}
    listed = {}
    for kind in ("container", "network"):
        found = _listing(tool, kind)
        if found is None:
            out["problem"] = f"the container tool could not list the {kind}s: nothing was removed for them"
            continue
        listed[kind] = found
    containers, networks = listed.get("container", []), listed.get("network", [])
    old = lambda item, grace: item["created"] is not None and now - item["created"] >= grace   # noqa: E731
    doomed, kept_run = [], set()   # run containers to remove; the ids of run containers that stay
    for item in containers:
        if not item["name"].startswith("wb-eval-run-"):
            continue
        if item["state"] in ENDED:
            doomed.append(item)
        elif include_running and item["state"] == "running" and old(item, RUNNING_GRACE_SECONDS):
            doomed.append(item)
        else:
            kept_run.add(item["run"])
            out["kept"].append({"name": item["name"], "why": "it is running: only the explicit command removes a running run, and only a stuck one"
                                if item["state"] == "running" else "its state cannot be read or it has not ended"})
    for item in containers:
        if item["name"].startswith("wb-eval-run-"):
            continue
        if item["run"] in kept_run:
            out["kept"].append({"name": item["name"], "why": "its run's container still exists"})
        elif item["created"] is None:
            out["kept"].append({"name": item["name"], "why": "its age cannot be read"})
        elif not old(item, GRACE_SECONDS):
            out["kept"].append({"name": item["name"], "why": f"younger than {GRACE_SECONDS} s"})
        else:
            doomed.append(item)
    holders = {i["run"] for i in containers if i not in doomed}
    plan = [("container", i) for i in doomed]
    for item in networks:
        if item["run"] in holders:
            out["kept"].append({"name": item["name"], "why": "a container of its run still exists"})
        elif item["created"] is None:
            out["kept"].append({"name": item["name"], "why": "its age cannot be read"})
        elif not old(item, GRACE_SECONDS):
            out["kept"].append({"name": item["name"], "why": f"younger than {GRACE_SECONDS} s"})
        else:
            plan.append(("network", item))
    for kind, item in plan:
        name = item["name"]
        if is_shared(name):   # checked again just before the removal: a shared object is never removed
            continue
        if dry_run:
            out["removed"].append({"kind": kind, "name": name, "run": item["run"], "via": item["via"], "dry_run": True})
            continue
        code, _ = tool(*(("rm", "-f", name) if kind == "container" else ("network", "rm", name)))
        if code == 0:
            out["removed"].append({"kind": kind, "name": name, "run": item["run"], "via": item["via"]})
        else:
            out["kept"].append({"name": name, "why": "the tool could not remove it"})
    return out


def remove_runs(tool, run_ids, *, dry_run: bool = False) -> dict:
    """Remove what the runs named by run_ids left that is still there (R18: a run was stopped and its process may have been killed
    before it cleaned up): their run container and key proxy (`wb-eval-run-<id>`, `wb-eval-keys-<id>`), then their network
    (`wb-eval-held-<id>`). Only a name that is exactly a run's own and for one of these ids is selected, whatever its labels or state, and a
    shared object (`is_shared`) is checked again just before its removal and never touched. Nothing is guessed: a listing the tool
    could not give removes nothing for that kind. Returns {"removed": [{"kind", "name", "run"}], "kept": [{"name", "why"}],
    "problem"}."""
    wanted = {str(r) for r in run_ids if RUN_ID.fullmatch(str(r))}
    out = {"removed": [], "kept": [], "problem": None}
    if not wanted:
        return out
    plan = []
    for kind in ("container", "network"):
        found = _listing(tool, kind)
        if found is None:
            out["problem"] = f"the container tool could not list the {kind}s: nothing was removed for them"
            continue
        plan += [(kind, item) for item in found if item["run"] in wanted]
    plan.sort(key=lambda p: (p[0] == "network", not p[1]["name"].startswith("wb-eval-run-")))   # the run, its key proxy, then the network
    for kind, item in plan:
        name = item["name"]
        if is_shared(name):
            continue
        if dry_run:
            out["removed"].append({"kind": kind, "name": name, "run": item["run"], "dry_run": True})
            continue
        code, _ = tool(*(("rm", "-f", name) if kind == "container" else ("network", "rm", name)))
        if code == 0:
            out["removed"].append({"kind": kind, "name": name, "run": item["run"]})
        else:
            out["kept"].append({"name": name, "why": "the tool could not remove it"})
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--help", "-h"):
        print(__doc__)
        return 0
    print("error: this module is called by runtime/upkeep.py (the dispatcher's round, and `python3 runtime/upkeep.py containers`); see --help",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
