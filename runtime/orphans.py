#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Orphan containers of the eval harness, removed on recovery (package P-OPS, finding I6).

A run of the lab starts, for each run, a container (`wb-eval-run-<run id>`), a key proxy (`wb-eval-keys-<run id>`) and an
internal network (`wb-eval-held-<run id>`). When the process that started them dies, the container ends with its command
(`--rm`), but the key proxy and the network can stay. The executor (evals/executor.py) labels everything it makes `wb.eval=1`
and, for a run's own three, `wb.eval.run=<run id>`, so that an orphan is found by label. This module finds and removes them.

What is selected (and only this):
  1. by label: a container or network whose label `wb.eval.run` holds a run id (16 hexadecimal characters);
  2. by name, for what was started before the label existed: `wb-eval-run-<16 hex>`, `wb-eval-keys-<16 hex>` (containers) and
     `wb-eval-held-<16 hex>` (networks). A name with any other tail is not a run's: the shared key holders and proxies of a
     harness (`wb-eval-keys-<12 hex tag>`, `wb-eval-proxy-<tag>`, `wb-eval-net-<tag>`, `wb-eval-route-<name>-<tag>`) are named after
     a hash of the container definition, not a run id, and are never selected, whatever their labels. `is_shared` says so, and a
     candidate is checked against it again just before its removal.

When a run is live (its objects are kept). The harness holds no lock per run, so liveness is read from the locks it does hold:
a run of the runtime holds the task's lock (`task-<id>.lock`, `route.lock`, `effect-<id>.lock` in the project's locks folder) and a
place of the lab's `total` lock (evals/execution.py `Slots`, one file per place in the lab's lock folder) around every attempt.
`busy()` is whether any of those is held by a process that is alive now (a probe takes the lock shared and lets it go; a dead
process holds nothing). Then:
  - busy: only what is older than BUSY_GRACE_SECONDS (6 hours: far over a run's timeout, 30 minutes, with its retries) is removed;
  - idle: what is older than IDLE_GRACE_SECONDS (30 minutes: over the 15 minutes an install of dependencies may take, a command that
    holds no place of the lab's lock, possibly of another project's runtime on this machine) is removed;
  - an object whose age cannot be read is kept.
The order of removal is the run's container, then its key proxy, then its network (a network with a container on it is not removed).

The container tool is a function `tool(*args) -> (returncode, stdout)`; production passes the facade's `lab.container_tool`, a test passes a fake. No
test of this repository reaches the real docker.

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
SHARED_PREFIXES = ("wb-eval-proxy-", "wb-eval-net-", "wb-eval-route-")   # the harness's shared proxy and networks
SHARED_KEYS = re.compile(r"wb-eval-keys-[0-9a-f]{12}")                    # a shared key holder: named after the definition's tag
BUSY_GRACE_SECONDS = 6 * 3600
IDLE_GRACE_SECONDS = 1800


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
    """[{"name", "run", "via", "created"}] of every container or network the sweep may select, or None when the tool failed. A
    container is listed with `ps -a`; one record per line of `--format '{{json .}}'`."""
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
        labelled = _labels(row.get("Labels")).get(LABEL_RUN, "")
        by_label = labelled if RUN_ID.fullmatch(labelled) else None
        by_name = run_of_name(kind, name)
        run = by_label or by_name
        if not name or run is None or is_shared(name):
            continue
        found.append({"name": name, "run": run, "via": "label" if by_label else "name",
                      "created": parse_created(row.get("CreatedAt"))})
    return found


def sweep(tool, *, now: float, busy: bool, dry_run: bool = False) -> dict:
    """Remove the orphans of the harness. `tool` is the container tool, `now` a POSIX time, `busy` whether a live process holds a lock
    of a run (busy() of the caller). Returns {"removed": [{"kind", "name", "run", "via"}], "kept": [{"name", "why"}], "problem"}.
    `problem` is a sentence when the tool could not list (the sweep does nothing then, and says so); dry_run lists and removes
    nothing."""
    grace = BUSY_GRACE_SECONDS if busy else IDLE_GRACE_SECONDS
    out = {"removed": [], "kept": [], "problem": None, "busy": busy, "grace_seconds": grace}
    listed = {}
    for kind in ("container", "network"):
        found = _listing(tool, kind)
        if found is None:
            out["problem"] = f"the container tool could not list the {kind}s: nothing was removed for them"
            continue
        listed[kind] = found
    # a run's container first, its key proxy next, its network last: a network with a container on it is not removed
    order = sorted(listed.get("container", []), key=lambda c: 0 if c["name"].startswith("wb-eval-run-") else 1)
    for kind, items in (("container", order), ("network", listed.get("network", []))):
        for item in items:
            name = item["name"]
            if is_shared(name):   # checked again just before the removal: a shared object is never removed
                continue
            if item["created"] is None:
                out["kept"].append({"name": name, "why": "its age cannot be read"})
            elif now - item["created"] < grace:
                out["kept"].append({"name": name, "why": f"younger than {int(grace)} s while " + ("a run holds a lock" if busy else "nothing runs")})
            elif dry_run:
                out["removed"].append({"kind": kind, "name": name, "run": item["run"], "via": item["via"], "dry_run": True})
            else:
                args = ("rm", "-f", name) if kind == "container" else ("network", "rm", name)
                code, _ = tool(*args)
                if code == 0:
                    out["removed"].append({"kind": kind, "name": name, "run": item["run"], "via": item["via"]})
                else:
                    out["kept"].append({"name": name, "why": "the tool could not remove it"})
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in ("--help", "-h"):
        print(__doc__)
        return 0
    print("error: this module is called by runtime/upkeep.py; see --help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
