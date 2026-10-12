#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The router step of the task runtime: what code reads of one run of the router skill asked only for the route.

A request with no flow is routed by one run of the router skill (ROUTER_SKILL), as it is, with ROUTE_TASK_TEXT as
the task's text, so that the skill returns the route and starts nothing. Code reads only two things of the reply:
the route line and whether the reply asks. The route line is the first line of the skill's output template:

  Route: <name> (<capability or flow>, <ready or pending>)

A reply that asks (a line `Q<n>: ...`, also on the template's `Next:` line) is a question for the person, whatever
its route line says. A reply with exactly one route line is a route; anything else (no route line, `Route: none`,
a name in prose, two route lines) is unclassified and reaches the person whole. Nothing here guesses.

A reply whose route line carries the shape word `direct` (`Route: none (direct)`, or a name with `(direct, ready)`) is
the skill's answer for a one-step request that no skill is needed for: a direct turn. Code reads it as such, with the
text of the template's `Next:` line, and the person is answered from the project's records (runtime/ops_say.py).

Functions:
  read_route(reply)                             {"kind": "question"} | {"kind": "direct", "next"} | {"kind": "route", ...} | {"kind": "unclassified", "why"}
  check_route(route, flow_names, pack_skills)   {"ok": true, "flow" | "skill"} | {"ok": false, "why"}

Pure: text in, a route out. It imports nothing of the lab or the store and calls no model.

Usage (a library; the shell is runtime/cli.py, verb route): python3 runtime/router.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import roles  # noqa: E402  (the same folder)

ROUTER_SKILL = roles.load()["router"]  # runtime/roles.json
# The task's text of a router run. "I only want the route" makes the skill's stop rule for a request that asks only
# for the route apply: it names the route and hands nothing over.
ROUTE_TASK_TEXT = ("tell me which skill or flow would handle the request above, and whether it has what it needs. "
                   "I only want the route: do not start it and do not do any of its work.")
ROUTE_RE = re.compile(r"^Route: ([a-z0-9]+(?:-[a-z0-9]+)*) \((capability|flow), (ready|pending)\)$")
# The template writes each question as `Q<n>: <question> Recommended: ...` on its own line; replies of the corpus
# also write the first one on the `Next:` line (`Next: Q1: ...`).
QUESTION_RE = re.compile(r"^(?:Next: )?Q[0-9]+: ")
# The direct shape (skills/core-orchestrator/SKILL.md, step 2): `Route: none (direct)`, or a name with the shape word
# and a status. The template's `Next:` line is what the planner proposes to do.
DIRECT_RE = re.compile(r"^Route: (?:none|[a-z0-9]+(?:-[a-z0-9]+)*) \(direct(?:, (?:ready|pending))?\)$")
NEXT_RE = re.compile(r"^Next: (.*\S)\s*$")
DIRECT_SHAPE = "direct"
FLOW_PREFIX = "flow-"
NO_ROUTE = "none"  # `Route: none`: the skill's stop rule for a request nothing installed can handle


def read_route(reply: str) -> dict:
    """What the reply of a router run says, read from its lines only."""
    lines = [line.rstrip() for line in (reply or "").splitlines()]
    if any(QUESTION_RE.match(line) for line in lines):
        return {"kind": "question"}
    if sum(1 for line in lines if DIRECT_RE.match(line)) == 1 and not any(ROUTE_RE.match(line) for line in lines):
        proposed = next((m.group(1) for m in map(NEXT_RE.match, lines) if m), "")
        return {"kind": "direct", "next": proposed}
    found = [(line, ROUTE_RE.match(line)) for line in lines]
    found = [(line, m) for line, m in found if m]
    if len(found) != 1:
        return {"kind": "unclassified", "why": "no route line" if not found else f"{len(found)} route lines"}
    line, m = found[0]
    if m.group(1) == NO_ROUTE:
        return {"kind": "unclassified", "why": "the router names no route"}
    return {"kind": "route", "name": m.group(1), "shape": m.group(2), "status": m.group(3), "line": line}


def check_route(route: dict, flow_names, pack_skills) -> dict:
    """Whether a route can be planned here: a flow route names `flow-<name>` with a flow file flows/<name>.json; a
    capability route names a skill of the pack in scope. The status word is not read: the router's run sees only the
    router installed, so it cannot know what is."""
    name, shape = route.get("name") or "", route.get("shape")
    if shape == "flow":
        if not name.startswith(FLOW_PREFIX):
            return {"ok": False, "why": f"the flow route {name!r} does not start with {FLOW_PREFIX!r}"}
        flow = name[len(FLOW_PREFIX):]
        if flow not in list(flow_names):
            return {"ok": False, "why": f"the flow has no flow file: flows/{flow}.json"}
        return {"ok": True, "flow": flow}
    if shape == "capability":
        if name not in list(pack_skills):
            return {"ok": False, "why": f"the skill {name} is not in the pack of the agents in scope"}
        return {"ok": True, "skill": name}
    return {"ok": False, "why": f"the route's shape {shape!r} is neither capability nor flow"}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
