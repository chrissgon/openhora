#!/usr/bin/env python3
"""Write the fixtures of the interface's demo mode (interface/demo/fixtures/) from the real operations.

The demo (interface/demo/) answers every route the page calls from an in-memory world. The shapes of those answers must be the
service's own, so this script seeds a scratch project the way the runtime tests do (the stand-in tree of
runtime/tests/standin_tree.py: invented skills, a stand-in adapter, no model call, no network), drives the real operations of
runtime/ops.py through a small story (a request, a plan, a question, a review, an effect, an acceptance, a task that runs, a
request a router run holds), writes down what each read operation answered, rewrites the scratch names to fictional ones
(`northwind-shop`, `Demo Person`) and writes one JSON file for each kind of answer. The world clones those answers as
templates, so a key the operations add shows up here first.

Usage:
  python3 scripts/demo_fixtures.py --write [--out <dir>]    write the fixtures (default: interface/demo/fixtures/)
  python3 scripts/demo_fixtures.py --check [--out <dir>]    exit 1 and name each file whose keys differ from the operations'
  python3 scripts/demo_fixtures.py --help

`--check` compares the shape of each answer (its keys, at every depth; the values are not compared), so a change of a value
(a timestamp, a hash) never fails it, and an operation that gains or loses a key does until `--write` is run again. The skills
fixture is the one exception to "invented": its rows are the workbench's own skills, versions and bands, read from the snapshot
in docs/inventory.md (the commit it names is written in the fixture's `snapshot` key, which the page ignores).

Data goes to stdout (the names written, or the files that differ); diagnostics go to stderr.
Exit codes: 0 ok, 1 --check found a difference, 2 usage error or a source that cannot be read.
Standard library only. Runs on Python 3.9 or later.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "runtime"
TESTS = RUNTIME / "tests"
DEFAULT_OUT = REPO / "interface" / "demo" / "fixtures"
INVENTORY = REPO / "docs" / "inventory.md"

PROJECT_NAME = "northwind-shop"
HOME = "/home/demo"
STAMP = "2026-10-01T09:00:00Z"
DAY = "2026-10-01"
TOKEN = "demo-token-" + "0" * 24 + "-fictional"
# The scratch names the story uses, and the fictional names they are rewritten to (longest first).
SKILLS = {"demo-asks": "biz-market-analysis", "demo-writes": "mkt-social-copy", "demo-code": "eng-implement",
          "demo-gate": "ops-pull-request", "demo-design": "design-execute"}
AREA_OF = {"biz": "business", "brand": "brand", "core": "core", "design": "design", "eng": "engineering", "flow": "core",
           "mkt": "marketing", "ops": "delivery", "product": "product", "ai": "ai"}
PACKS = {"planning": ["demo-asks"], "design": ["demo-design"], "engineering": ["demo-code", "demo-gate"], "marketing": ["demo-writes"]}
AGENTS = {"planning": {"pack": "planning", "mode": "supervised", "max_runs_per_day": 12, "max_usd_per_day": 5},
          "design": {"pack": "design", "mode": "supervised", "max_runs_per_day": 6, "max_usd_per_day": 3},
          "engineering": {"pack": "engineering", "mode": "milestones", "max_runs_per_day": 8, "max_usd_per_day": 4},
          "marketing": {"pack": "marketing", "mode": "supervised", "max_runs_per_day": 6, "max_usd_per_day": 2}}
PRICES = {"m": {"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0, "cache_read_usd_per_mtok": 0.3,
                "cache_write_usd_per_mtok": 3.75, "source": "https://prices.example/models", "date": "2026-10-01"}}
CODE = {"provider": "github", "repo": "example-org/web", "base": "main"}
GIT = ["git", "-c", "user.name=Demo Person", "-c", "user.email=demo@example.test", "-c", "commit.gpgsign=false"]
# The file each fixture is written to, and the order they are listed in.
NAMES = ("projects", "versions", "version", "status", "status-routing", "status-live", "pending", "pending-plan", "pending-question",
         "pending-review", "pending-effect", "pending-acceptance", "task", "task-live", "agents", "conversation", "skills",
         "costs", "connections", "artifacts", "artifact", "commands", "flows", "progress", "job", "errors", "writes")


class Monkey:
    """The little of pytest's monkeypatch that the stand-in tree needs."""

    def __init__(self):
        self.undo = []

    def setattr(self, obj, name, value):
        self.undo.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def restore(self):
        for obj, name, old in reversed(self.undo):
            setattr(obj, name, old)


def _git(folder, *args):
    return subprocess.run(GIT + ["-C", str(folder), *args], check=True, capture_output=True, text=True).stdout


def seed(scratch: Path) -> dict:
    """Drive the real operations in a scratch project and return what each read answered, before any rewrite."""
    for path in (str(RUNTIME), str(TESTS)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import standin_tree as st  # noqa: PLC0415  (a test helper: invented skills and a stand-in adapter)
    lab = st.load("lab")
    ops = st.load("ops")
    ops_core = st.load("ops_core")
    plan = st.load("plan")
    service = st.load("service")
    mp = Monkey()
    try:
        tree = st.build(scratch, mp, lab)
        mp.setattr(ops_core, "ROOT", str(tree["tree"]))
        mp.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS.get(pack, [])))
        mp.setattr(lab, "reference", lambda tier="strong": {
            "tier": tier, "model": {"strong": "m", "floor": "fm"}[tier], "adapter": "h", "pass_env": [], "timeout_seconds": 60,
            "retries": 2, "control": {"total_jobs": 2, "web_jobs": {"strong": 1, "floor": 1}}})
        for rel in ("providers/secrets/resolver.py", "runtime/secrets.json"):
            if (REPO / rel).is_file():
                (tree["tree"] / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / rel, tree["tree"] / rel)
        (tree["tree"] / "scripts").mkdir(exist_ok=True)  # the recorder of a use: nothing to record in a scratch tree
        (tree["tree"] / "scripts" / "evidence.py").write_text("print('0123abcd')\n", encoding="utf-8")
        project = tree["project"]
        path = str(project)
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("v1\n")
        (project / ".gitignore").write_text(".workbench-local/\n")
        config = project / "docs" / "workbench" / "runtime.json"
        raw = json.loads(config.read_text())
        raw.update(area_agents=AGENTS, code=CODE, model_prices=PRICES)
        config.write_text(json.dumps(raw))
        _git(project, "init", "-q")
        _git(project, "add", "-A")
        _git(project, "commit", "-q", "-m", "start")
        ops.accept_config(path, ops.project_config.load(path)["sha256"])
        (tree["tree"] / "providers" / "vcs" / "answers.json").write_text(json.dumps(
            {"base_commit": _git(project, "rev-parse", "HEAD").strip(), "branch_exists": False}))
        (tree["adapter"] / "code.sh").write_text("echo v2 > src/app.py\n")
        out, writes = {}, {}

        # A request, its plan, the plan approved, a question asked and answered, a review.
        writes["request"] = ops.request(path, "Do the market analysis.")
        first = writes["request"]["request"]
        planned = writes["route"] = ops.route(path, first, "demo")
        out["pending-plan"] = ops.pending(path, planned["pending_id"])
        out["pending"] = ops.pending(path)
        writes["approve-plan"] = ops.approve(path, planned["pending_id"], out["pending-plan"]["payload"]["plan_sha256"])
        asked = ops.run_next(path)
        out["pending-question"] = ops.pending(path, asked["pending_id"])
        writes["answer"] = ops.answer(path, asked["pending_id"], "Small online shops.")
        reviewed = ops.run_next(path)
        out["pending-review"] = ops.pending(path, reviewed["pending_id"])
        writes["release"] = ops.release(path, reviewed["pending_id"])
        ops.run_next(path)  # the second task of the flow asks nothing: a review again, released below
        for item in ops.pending(path)["pending"]:
            ops.release(path, item["id"])
        writes["say"] = ops.say(path, "/status")

        # A code request run up to its gate: an effect.
        writes["request-flow"] = ops.request(path, "Carry the providers a skill needs.", "gate-demo", title="Carry the providers")
        done = ops.run_next(path)
        ops.release(path, done["pending_id"])
        gated = ops.run_next(path)
        out["pending-effect"] = ops.pending(path, gated["pending_id"])

        # An acceptance on a request that is planned, and a request whose reroute is open.
        ctx = ops_core.context(path)
        store, conn = ctx["store"], ctx["conn"]
        one = ops.request(path, "Plan two deliveries.", "code-demo", title="Two deliveries")["request"]
        store.acceptance_open(conn, task_id=one, what="deliveries", title="Accept the deliveries",
                              body="Two deliveries are proposed.", payload={"deliveries": []})
        acceptance_id = next(p["id"] for p in ops.pending(path)["pending"] if p["kind"] == "acceptance")
        out["pending-acceptance"] = ops.pending(path, acceptance_id)

        # A request a router run holds, then a task that runs.
        waiting = ops.request(path, "Name the app.")["request"]
        run = store.route_run_start(conn, waiting, skill="demo-asks", model="m", adapter="h", skill_version="0.1.0", billing="subscription")
        out["status-routing"] = ops.status(path)
        store.route_run_finish(conn, run["run_id"], status="ok", ending="done", attempts=1)
        claimed = store.task_claim_next(conn)
        running = None
        if claimed["task"]:
            running = claimed["task"]["id"]
            store.task_run_start(conn, running, skill="demo-code", model="m", adapter="h", skill_version="0.1.0", billing="subscription")
        out["status-live"] = ops.status(path)
        out["task-live"] = ops.task(path, running) if running else ops.task(path, first)
        live_run = out["task-live"]["runs"][-1]["id"] if running else None
        out["task"] = ops.task(path, first)
        out["status"] = ops.status(path)
        out["pending"] = {"pending": out["pending"]["pending"] + ops.pending(path)["pending"]}
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for cost in (0.4, 0.15):
            conn.execute("INSERT INTO task_runs (task_id, skill, model, adapter, status, started_at, cost_usd, billing) "
                         "VALUES (?, 'demo-code', 'm', 'h', 'ok', ?, ?, 'metered')", (out["task"]["task"]["id"], now, cost))
        conn.commit()
        for name in ("agents", "conversation", "skills", "costs", "connections", "artifacts", "commands", "flows", "progress", "version"):
            out[name] = getattr(ops, name)(path)
        first_doc = out["artifacts"]["artifacts"][0]["path"] if out["artifacts"]["artifacts"] else "docs/business/market.md"
        out["artifact"] = ops.artifact(path, first_doc)

        # The service's own answers: the project list, the change signal, a job, the refusals.
        svc = service.Service(ops, [{"id": "0" * 12, "name": project.name, "path": path, "data_dir": str(tree["data"])}], TOKEN, 8765)
        out["projects"] = svc.projects_list()
        out["versions"] = service._versions(svc)
        job, thread, _ = svc.start_job("0" * 12, "status", lambda: {"ok": True})
        thread.join(10)
        out["job"] = svc.job_shown(job["job"])
        out["errors"] = {
            "refused": json.loads(service._error(409, "refused", "the operation refused")[2]),
            "not_configured": json.loads(service._error(412, "not_configured", "the configuration is not accepted", next="python3 runtime/cli.py accept-config --sha256 0")[2]),
            "not_found": json.loads(service._error(404, "not_found")[2]),
            "usage": json.loads(service._error(400, "usage", "the request is malformed")[2]),
        }
        # The writes that change what the reads answer, last: a request cancelled, a task retried, a plan rejected, an effect
        # approved (the stand-in code provider records the call and sends nothing), a mode set down and a mode set up.
        writes["verdict"] = ops.verdict(path, 1, "worked")
        writes["cancel"] = ops.cancel(path, waiting)
        if running:
            store.task_run_finish(conn, live_run, status="failed", task_state="failed", failure="timeout", attempts=1)
            writes["retry"] = ops.retry(path, running)
        other = ops.request(path, "Draft the launch notes.")["request"]
        writes["reject"] = ops.reject(path, ops.route(path, other, "demo")["pending_id"], "Not now.")
        writes["approve-effect"] = ops.approve(path, gated["pending_id"], out["pending-effect"]["payload_sha256"], channel="page")
        writes["set-mode-down"] = ops.set_mode(path, "design", "stopped", channel="page")
        writes["set-mode-up"] = ops.set_mode(path, "engineering", "autonomous", channel="page")
        out["writes"] = writes

        out["_scratch"] = {"project": path, "tree": str(tree["tree"]), "data": str(tree["data"]), "root": str(scratch)}
        return out
    finally:
        mp.restore()


def inventory_rows() -> tuple:
    """([(skill, version, band, score, mean, runs)], {skill: {tier: (band, cause, score, mean, runs)}}, commit) from the
    snapshot in docs/inventory.md: the band table (reference model) and the model table (the reference model first, then the
    floor model)."""
    text = INVENTORY.read_text(encoding="utf-8")
    block = text.split("<!-- eval-status:begin -->")[1].split("<!-- eval-status:end -->")[0]
    commit = re.search(r"Generated at commit `([0-9a-f]+)`", block).group(1)
    bands, models = [], {}
    for line in block.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) == 9 and re.fullmatch(r"[a-z]+-[a-z0-9-]+", cells[0]) and re.fullmatch(r"\d+\.\d+\.\d+", cells[1]):
            bands.append((cells[0], cells[1], cells[2], cells[4], cells[5], cells[6]))
        elif len(cells) == 10 and re.fullmatch(r"[a-z]+-[a-z0-9-]+", cells[0]) and "/" in cells[1] or (len(cells) == 10 and cells[1].startswith("claude")):
            models.setdefault(cells[0], []).append((cells[2], None if cells[3] in ("-", "") else cells[3], cells[5], cells[6], cells[7]))
    return bands, models, commit


def number(text):
    try:
        return float(text)
    except ValueError:
        return None


def skills_fixture(shape: dict) -> dict:
    """The skills answer with the workbench's own rows, in the shape the operation gave."""
    bands, models, commit = inventory_rows()
    template = shape["skills"][0]
    rows = []
    for name, version, _band, _score, _mean, _runs in bands:
        tiers = models.get(name, [])
        proof = []
        for tier, (reference, model, adapter) in zip(("strong", "floor"), (("strong", "reference-model", "adapter"), ("floor", "floor-model", "adapter"))):
            found = tiers[0 if tier == "strong" else 1] if len(tiers) > (0 if tier == "strong" else 1) else None
            row = dict(template["proof"][0])
            if found:
                band, cause, score, mean, runs = found
                row.update(tier=tier, model=model, adapter=adapter, band=band, cause=cause, score=number(score), mean=number(mean), runs=int(runs))
            else:
                row.update(tier=tier, model=model, adapter=adapter, band="needs a test", cause="no evidence on this model", score=None, mean=None, runs=0)
            proof.append(row)
        rows.append({**template, "name": name, "version": version, "area": AREA_OF.get(name.split("-")[0], "core"), "proof": proof, "runs_here": 0})
    return {"skills": rows, "checks": dict(shape["checks"]), "snapshot": {"commit": commit, "source": "docs/inventory.md"}}


class Rewriter:
    """The scratch names to the fictional ones, timestamps to a fixed stamp, hashes to stable ones."""

    def __init__(self, scratch: dict):
        root = scratch["root"]
        roots = {os.path.realpath(root), root, "/private" + root if not root.startswith("/private") else root[len("/private"):]}
        self.pairs = []
        for r in sorted(roots, key=len, reverse=True):
            self.pairs += [(os.path.join(r, "project"), f"{HOME}/{PROJECT_NAME}"), (os.path.join(r, "bench-tree"), f"{HOME}/openhora"),
                           (os.path.join(r, "data"), f"{HOME}/.openhora/data/{PROJECT_NAME}"), (os.path.join(r, "store"), f"{HOME}/.openhora/store"), (r, f"{HOME}/scratch")]
        self.pairs += [(k, v) for k, v in SKILLS.items()]
        self.hashes = {}

    def text(self, s: str) -> str:
        for old, new in self.pairs:
            s = s.replace(old, new)
        s = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", STAMP, s)
        s = re.sub(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", lambda m: self.hashes.setdefault(m.group(0), hashlib.sha256(f"fixture-{len(self.hashes)}".encode()).hexdigest()), s)
        s = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", DAY, s)
        s = re.sub(r"tmp\.[A-Za-z0-9]{8}", "tmp.AbCd1234", s)
        return s.replace("bench-tree", "openhora").replace("example-org/web", "example-org/northwind-shop")

    def value(self, v):
        if isinstance(v, str):
            return self.text(v)
        if isinstance(v, list):
            return [self.value(x) for x in v]
        if isinstance(v, dict):
            return {self.text(k): self.value(x) for k, x in v.items()}
        return v


def build() -> dict:
    """Every fixture, rewritten, by file name."""
    with tempfile.TemporaryDirectory() as tmp:
        raw = seed(Path(tmp).resolve())
    scratch = raw.pop("_scratch")
    skills_shape = raw["skills"]
    rewrite = Rewriter(scratch)
    out = {name: rewrite.value(raw[name]) for name in NAMES if name != "skills"}
    out["skills"] = skills_fixture(rewrite.value(skills_shape))
    return {name: out[name] for name in NAMES}


def skeleton(value):
    """The keys of an answer at every depth: a dict maps its keys to theirs, a list holds the union of its elements' skeletons
    (an empty list is []), a leaf is None. Values are not compared."""
    if isinstance(value, dict):
        return {k: skeleton(v) for k, v in value.items()}
    if isinstance(value, list):
        merged = None
        for item in value:
            merged = merge(merged, skeleton(item))
        return [] if merged is None else [merged]
    return None


def merge(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for k, v in b.items():
            out[k] = merge(out.get(k), v) if k in out else v
        return out
    if isinstance(a, list) and isinstance(b, list):
        if not a:
            return b
        if not b:
            return a
        return [merge(a[0], b[0])]
    return a


def write(out_dir: Path, fixtures: dict) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.json"):
        if stale.stem not in fixtures:
            stale.unlink()
    for name, value in fixtures.items():
        (out_dir / f"{name}.json").write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return sorted(fixtures)


def differences(out_dir: Path, fixtures: dict) -> list:
    """The names whose committed file is missing or has other keys than the operations give now."""
    found = []
    for name, value in fixtures.items():
        path = out_dir / f"{name}.json"
        if not path.is_file():
            found.append(f"{name}: missing")
        elif name == "skills":
            kept = json.loads(path.read_text(encoding="utf-8"))
            if skeleton(kept.get("skills", [])) != skeleton(value["skills"]) or kept.get("checks", {}).keys() != value["checks"].keys():
                found.append(f"{name}: keys differ")
        elif skeleton(json.loads(path.read_text(encoding="utf-8"))) != skeleton(value):
            found.append(f"{name}: keys differ")
    extra = sorted(p.stem for p in out_dir.glob("*.json") if p.stem not in fixtures) if out_dir.is_dir() else []
    return found + [f"{name}: not an answer any more" for name in extra]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write or check the fixtures of the interface's demo mode, from the real operations.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the fixtures")
    mode.add_argument("--check", action="store_true", help="exit 1 when a committed fixture has other keys than the operations give")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="the folder of the fixtures (default: interface/demo/fixtures/)")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    try:
        fixtures = build()
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as e:
        print(f"the fixtures could not be built: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if args.write:
        for name in write(out_dir, fixtures):
            print(name)
        return 0
    found = differences(out_dir, fixtures)
    for line in found:
        print(line)
    if found:
        print("run: python3 scripts/demo_fixtures.py --write", file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
