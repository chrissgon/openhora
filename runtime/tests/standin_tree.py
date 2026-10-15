"""A stand-in workbench tree for the tests of runtime/: an adapter that is a shell script, two invented skills
and one flow file, so that a run executes on this machine with no container and no model. Not a test file.

The stand-in adapter "h" is told what to do by files beside its script (adapters/h/), which a test writes:
  fail-times   a number: the first <n> calls fail as fail-kind says, the next ones behave
  fail-kind    timeout | adapter | refused | auth | limit | early
Each model call is appended to adapters/h/calls.txt as "<the skill staged, or none> <attempt number>".
Otherwise it acts by the skill staged in the copy:
  demo-asks    with no answer in the prompt it asks, with the skills' asking template, and writes nothing;
               with an answer it writes docs/business/market.md and a line in docs/workbench/state.md
  demo-writes  writes docs/business/icp.md from docs/business/market.md; without that input it says so
  demo-code    runs adapters/h/code.sh in the copy, when a test wrote one (with the attempt number as $1), and
               replies that it changed the files
  demo-design  a design skill with the side effect create and a gate (R4-C6): writes docs/design/design-system.md; when
               a test wrote adapters/h/design-gate it also stops at its gate with a payload in a folder from mktemp -d
  demo-gate    a skill with a confirmation gate: records the copy's branches, log and status in its output folder,
               writes payload.md in a folder from mktemp -d and replies in the pull-request skill's form; when a test
               wrote adapters/h/gate.sh it runs that instead (in the copy, with the output folder as $1)
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import threading
from pathlib import Path

from sources_fixture import sources_path  # noqa: E402  (the same folder: the mandatory key sources_dir of every test project)

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"

EVAL_JSON = {"skills_dir": ".h/skills", "settings": [".h", "h-settings.json"],
             "account_limit": ["usage limit reached"], "refusal_markers": ["safeguards flagged this message"]}

ADAPTER = r'''
here="$(dirname "$0")"; prompt="$2"; cwd="$4"; out="$8"
if grep -q "Reply with the single word: ok" "$prompt"; then echo probe >> "$here/probes.txt"; echo ok > "$out/response.md"; exit 0; fi
skill=none
for name in demo-asks demo-writes; do [ -d "$cwd/.h/skills/$name" ] && skill="$name"; done
[ -d "$cwd/.h/skills/demo-code" ] && skill=demo-code
[ -d "$cwd/.h/skills/demo-gate" ] && skill=demo-gate
[ -d "$cwd/.h/skills/demo-design" ] && skill=demo-design
n=1; while ! mkdir "$here/call-$skill.$n" 2>/dev/null; do n=$((n + 1)); done
echo "$skill $n" >> "$here/calls.txt"
(cd "$cwd" && find . -path ./.git -prune -o -type f -print | sort) > "$out/files.txt"
echo "{\"total_tokens\": 100, \"duration_ms\": 5, \"cost_usd\": 0.01, \"skills_loaded\": [\"$skill\"]}" > "$out/timing.json"
if [ -f "$here/fail-times" ] && [ "$n" -le "$(cat "$here/fail-times")" ]; then
  case "$(cat "$here/fail-kind")" in
    timeout) sleep 30 ;;
    adapter) echo "the provider is down" >&2; exit 1 ;;
    refused) echo "safeguards flagged this message" > "$out/response.md"; exit 1 ;;
    auth) [ -f "$here/auth-reports-usage" ] || rm -f "$out/timing.json"; echo "API Error: 401 Unauthorized" >&2; exit 1 ;;   # a refused key reports no usage
    limit) echo "usage limit reached" >&2; exit 1 ;;
    early) echo "Let me just read the template first." > "$out/response.md"; exit 0 ;;
  esac
fi
if [ -n "${STANDIN_KEY:-}" ]; then echo "the key is $STANDIN_KEY" > "$cwd/leak.txt"; echo "key: $STANDIN_KEY" >> "$out/stderr.log"; fi
case "$skill" in
  demo-asks)
    if grep -q "the user's answer" "$prompt"; then
      mkdir -p "$cwd/docs/business" "$cwd/docs/workbench"
      printf '# Market analysis\n\n- Owner: demo-asks\n- Status: draft\n' > "$cwd/docs/business/market.md"
      echo "- 2026-10-05: decision recorded by demo-asks. (demo-asks)" >> "$cwd/docs/workbench/state.md"
      echo "{}" > "$cwd/docs/business/market.lint.json"
      echo "x" > "$cwd/notes.txt"
      printf -- '- Analysis: docs/business/market.md (Status: draft)\n- Next: demo-writes\n' > "$out/response.md"
    else
      printf 'Nothing was searched or written yet: the scope below is your decision.\n\n1. Which country? Recommended: yours, because you sell there.\n' > "$out/response.md"
    fi ;;
  demo-writes)
    if [ -f "$cwd/docs/business/market.md" ]; then
      printf '# Ideal customer profile\n\n- Owner: demo-writes\n- Status: hypothesis\n' > "$cwd/docs/business/icp.md"
      printf -- '- Primary profile: clinics\n- Next: interviews\n' > "$out/response.md"
    else
      echo "There is no market analysis (docs/business/market.md)." > "$out/response.md"
    fi ;;
  demo-code)
    if [ -f "$here/code.sh" ]; then (cd "$cwd" && sh "$here/code.sh" "$n"); fi
    echo "Changed the files the request names." > "$out/response.md" ;;
  demo-gate)
    if [ -f "$here/gate.sh" ]; then (cd "$cwd" && sh "$here/gate.sh" "$out"); else
      head=$(git -C "$cwd" branch --show-current)
      base=$(git -C "$cwd" for-each-ref --format='%(refname:short)' refs/heads | grep -vx "$head" | head -1)
      echo "$base $head" > "$out/gate-branches.txt"
      git -C "$cwd" log --format=%s > "$out/gate-log.txt"
      git -C "$cwd" status --porcelain > "$out/gate-status.txt"
      echo "$TMPDIR" > "$out/gate-tmpdir.txt"
      d=$(mktemp -d "${TMPDIR:-/tmp}/tmp.XXXXXXXX")  # GNU mktemp -d (the container's) uses TMPDIR; BSD needs the template
      printf 'Repository: example-org/web
Base ← head: %s ← %s
Commits:
- 0000000 %s
Title: Carry the providers
Body:
What changes, and why.
' "$base" "$head" "$(git -C "$cwd" log -1 --format=%s)" > "$d/payload.md"
      sha=$( (sha256sum "$d/payload.md" 2>/dev/null || shasum -a 256 "$d/payload.md") | cut -d' ' -f1)
      printf 'Nothing was pushed or created yet. This is what will be sent:

(the payload)

Payload file: `%s/payload.md`, sha256 `%s`
Temporary folder: %s

Proceed? (yes/no)
' "$d" "$sha" "$TMPDIR" > "$out/response.md"
    fi ;;
  demo-design)
    mkdir -p "$cwd/docs/design"
    printf '# Design system\n\n- Owner: demo-design\n- File: none available\n' > "$cwd/docs/design/design-system.md"
    if [ -f "$here/design-gate" ]; then
      d=$(mktemp -d "${TMPDIR:-/tmp}/tmp.XXXXXXXX")
      printf 'Tool: a design tool\nFile: Demo\nCreate: variables\n' > "$d/payload.md"
      sha=$( (sha256sum "$d/payload.md" 2>/dev/null || shasum -a 256 "$d/payload.md") | cut -d' ' -f1)
      printf 'Nothing is created in the file before an explicit yes.\n\nPayload file: `%s/payload.md`, sha256 `%s`\n\nBuild these in the file? (yes/no)\n' "$d" "$sha" > "$out/response.md"
    else
      printf -- '- Design system: docs/design/design-system.md\n- Design tool: none available, nothing built\n' > "$out/response.md"
    fi ;;
  *) echo "ok" > "$out/response.md" ;;
esac
'''


# The project's state file, in the form of contracts/state.md; ## Decisions is last, so that a line the
# stand-in adapter appends to the file lands in it.
STATE = ("# Workbench state\n\n- Project: demo\n- Docs in git: none\n\n## Autonomy\n\n- Checkpoints: milestones\n\n"
         "## Artifacts\n\n| Artifact | Owner skill | Status | Updated |\n|----------|-------------|--------|---------|\n\n"
         "## Open questions\n\n## Approvals\n\n| Scope | What | Payload hash | Approved | Expires | Status |\n"
         "|-------|------|--------------|----------|---------|--------|\n\n## Decisions\n\n")


STANDIN_IMAGE = "sha256:" + "5" * 64

# The stand-in adapter's manifest (adapters/h/adapter.json): how its credentials are billed, which the daily caps count by
# (runtime/billing.py). The harness holds a login of its own, declared subscription (a tier that passes no variable), and the
# invented variables the tests pass are listed: EXAMPLE_API_KEY and STANDIN_FLOOR_PASS are metered, the others subscription.
# A variable a test passes that is not here has no billing (the dispatcher holds such a task, as it does for a real one).
SECRETS = {"EXAMPLE_API_KEY": "metered", "STANDIN_FLOOR_PASS": "metered", "EXAMPLE_REFERENCE_KEY": "subscription",
           "EXAMPLE_KEY_A": "subscription", "EXAMPLE_KEY_B": "subscription", "INVENTED_MODEL_KEY": "subscription"}
MANIFEST = {"harness": "h", "login_billing": "subscription", "secrets": [
    {"name": name, "purpose": "invented", "permission": "invented", "billing": billing,
     "readers": ["adapters/h/run-prompt.sh"]} for name, billing in SECRETS.items()]}

# A stand-in code provider (class integration:vcs, implementation "github"): it records each call in calls.jsonl
# beside it, with the sha256 of every --file it is handed, and answers as providers/vcs/github.py prints, from
# answers.json beside it ({"base_commit", "branch_exists", "fail": {"<verb>": [exit code, last line]}}). A key it
# committed or opened replays. No network, no git, no push.
VCS = r'''import hashlib, json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
verb = argv[0]
pairs = [(argv[i], argv[i + 1]) for i in range(1, len(argv) - 1) if argv[i].startswith("--")]
files = {}
for flag, value in pairs:
    if flag == "--file":
        path, local = value.split("=", 1)
        files[path] = hashlib.sha256(open(local, "rb").read()).hexdigest()
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": argv, "files": files, "env_token": bool(os.environ.get("VCS_GITHUB_TOKEN"))}) + "\n")
answers = json.load(open(os.path.join(here, "answers.json"))) if os.path.isfile(os.path.join(here, "answers.json")) else {}
state_file = os.path.join(here, "state.json")
state = json.load(open(state_file)) if os.path.isfile(state_file) else {}
key = dict(pairs).get("--idempotency-key")
failing = (answers.get("fail") or {}).get(verb)
if failing and "--dry-run" not in argv:
    print(failing[1], file=sys.stderr)
    sys.exit(failing[0])
if verb == "commit-files" and "--dry-run" in argv:
    print(json.dumps({"dry_run": True, "existing_status": "committed" if key in state else None,
                      "base_commit": answers.get("base_commit"), "branch_exists": bool(answers.get("branch_exists"))}))
elif verb == "commit-files":
    replayed = key in state
    state[key] = "c" * 40
    print(json.dumps({"idempotency_key": key, "commit": state[key], "pushed": not replayed, "replayed": replayed}))
elif verb == "open-pr":
    replayed = key in state
    state[key] = 7
    print(json.dumps({"idempotency_key": key, "number": 7, "url": "https://code.example/example-org/web/pull/7",
                      "replayed": replayed}))
json.dump(state, open(state_file, "w"))
'''


def load(name: str):
    """A module of runtime/, imported the way the modules import each other (runtime/ first on the path), so
    that a test and the module under test see the same module objects."""
    if str(RUNTIME) not in sys.path:
        sys.path.insert(0, str(RUNTIME))
    return importlib.import_module(name)


def skill(tree: Path, name: str, inputs: str, outputs: str, area: str = "business") -> Path:
    folder = tree / "skills" / name
    (folder / "evals").mkdir(parents=True)
    (folder / "scripts" / "tests").mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: invented\nlicense: MIT\nmetadata:\n  area: {area}\n  kind: capability\n"
        f"  inputs: [{inputs}]\n  outputs: [{outputs}]\n  updates: [docs/workbench/state.md]\n  requires: []\n"
        f"  side_effects: []\n  version: \"0.1.0\"\n---\n# {name}\n", encoding="utf-8")
    (folder / "evals" / "evals.json").write_text("{}", encoding="utf-8")
    documents = [{"path": p.strip(), "checks": [], "platform": "read_only", "bound_to_approval": False}
                 for p in outputs.split(",") if p.strip() and "<" not in p]
    (folder / "evals" / "runtime-manifest.json").write_text(json.dumps({
        "skill": name, "documents": documents, "machine_files": [], "mandatory_milestone": False,
        "asking_openings": ["Nothing was written yet"], "gate": None}), encoding="utf-8")
    (folder / "scripts" / "check.py").write_text("print(1)\n", encoding="utf-8")
    (folder / "scripts" / "tests" / "test_check_demo.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return folder


def gate_skill(tree: Path) -> Path:
    """demo-gate: a skill with the side effect create and a gate whose payload is under the temporary folder."""
    folder = skill(tree, "demo-gate", "docs/workbench/state.md", "", area="delivery")
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    # like the real pull-request skill: it declares the class of provider that executes its kind of effect (R4-C6)
    (folder / "SKILL.md").write_text(text.replace("  side_effects: []", "  side_effects: [create]").replace(
        "  requires: []", "  requires: [integration:vcs]"), encoding="utf-8")
    data = json.loads((folder / "evals" / "runtime-manifest.json").read_text(encoding="utf-8"))
    data.update(asking_openings=["Nothing was pushed or created yet. This is what will be sent"],
                gate={"effect": "create", "payload_file": "<tmp>/payload.md"})
    (folder / "evals" / "runtime-manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


def design_skill(tree: Path) -> Path:
    """demo-design: what design-system and design-execute declare (R4-C6): area design, side effect create, a gate whose
    payload is under the temporary folder, and the design-tool class as its requirement, not the code provider's."""
    folder = skill(tree, "demo-design", "docs/workbench/state.md", "docs/design/design-system.md", area="design")
    text = (folder / "SKILL.md").read_text(encoding="utf-8")
    (folder / "SKILL.md").write_text(text.replace("  side_effects: []", "  side_effects: [create]").replace(
        "  requires: []", "  requires: [integration:design-tool]"), encoding="utf-8")
    data = json.loads((folder / "evals" / "runtime-manifest.json").read_text(encoding="utf-8"))
    data.update(asking_openings=["Nothing is created in the file before an explicit yes"],
                gate={"effect": "create", "payload_file": "<tmp>/payload.md"})
    (folder / "evals" / "runtime-manifest.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


_RUNNER = []


def load_runner():
    """The lab's own runner, evals/eval_run.py, loaded once by path: the parity tests run it beside the facade.
    It binds the execution kit's names and shares the kit's module with the facade."""
    if not _RUNNER:
        import importlib.util
        spec = importlib.util.spec_from_file_location("workbench_eval_run_for_runtime_tests", REPO / "evals" / "eval_run.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RUNNER.append(module)
    return _RUNNER[0]


class FinishedChild:
    """What a child process the dispatcher started looks like once it has ended: a pid, poll() and returncode."""

    pid = 0

    def __init__(self, code: int):
        self.returncode = code

    def poll(self):
        return self.returncode


def serial_spawn(runs):
    """The seam ops_runs.spawn replaced by a run made in the calling thread, one after the other: the task runs to its end
    inside the call and the child it returns has ended. The tests of the dispatcher that predate the parallel runs read a
    round as 'the runs it made'; a test of the runs that overlap installs its own spawn (test_parallel_runs.py)."""
    def spawn(cfg, project, task_id):
        try:
            out = runs.run_task(project, task_id)
            code = 4 if out.get("ran") is None and not out.get("held") else 0
        except Exception as e:  # the process would have exited with the refusal's code, or 1
            code = getattr(e, "code", 1)
        child = FinishedChild(code)
        with runs.SPAWNED_LOCK:
            runs.SPAWNED.append((project, task_id, child))
        return child
    return spawn


def build(tmp_path: Path, monkeypatch, lab) -> dict:
    """The tree, a project and the patches that point the lab facade at them. Returns {"tree", "project",
    "data", "db", "adapter"} as paths. The runner executes on this machine (EXECUTOR "host"), its lock folder is
    the test's own, and nothing waits before a retry."""
    tree, project = tmp_path / "bench-tree", tmp_path / "project"
    adapter = tree / "adapters" / "h"
    adapter.mkdir(parents=True)
    (adapter / "eval.json").write_text(json.dumps(EVAL_JSON), encoding="utf-8")
    (adapter / "run-prompt.sh").write_text(ADAPTER, encoding="utf-8")
    (adapter / "adapter.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    skill(tree, "demo-asks", "docs/workbench/state.md, docs/workbench/research/<topic>.md, AGENTS.md", "docs/business/market.md")
    skill(tree, "demo-writes", "docs/workbench/state.md, docs/business/market.md", "docs/business/icp.md")
    skill(tree, "demo-code", "docs/workbench/state.md", "", area="engineering")  # a code task (ops.code_task)
    gate_skill(tree)
    design_skill(tree)
    (tree / "flows").mkdir()
    (tree / "flows" / "demo.json").write_text(json.dumps({"flow": "demo", "title": "Demo flow", "tasks": [
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "do the market analysis."},
        {"key": "profile", "skill": "demo-writes", "title": "Profile", "text": "choose the profile.",
         "depends_on": ["market"], "milestone": True}]}), encoding="utf-8")
    (tree / "flows" / "gate-demo.json").write_text(json.dumps({"flow": "gate-demo", "title": "Gate demo", "tasks": [
        {"key": "change", "skill": "demo-code", "title": "Change", "text": "make the change."},
        {"key": "pull-request", "skill": "demo-gate", "title": "Pull request", "text": "prepare it.",
         "depends_on": ["change"], "milestone": True}]}), encoding="utf-8")
    (tree / "flows" / "code-demo.json").write_text(json.dumps({"flow": "code-demo", "title": "Code demo", "tasks": [
        {"key": "first", "skill": "demo-code", "title": "First change", "text": "make the first change."},
        {"key": "second", "skill": "demo-code", "title": "Second change", "text": "make the second change.",
         "depends_on": ["first"]}]}), encoding="utf-8")
    for rel in ("providers/resolve.py", "providers/store/sqlite.py"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, tree / rel)
    (tree / "providers" / "vcs").mkdir(parents=True, exist_ok=True)
    (tree / "providers" / "vcs" / "github.py").write_text(VCS, encoding="utf-8")
    (project / "docs" / "workbench").mkdir(parents=True)
    data, db = tmp_path / "data", tmp_path / "store" / "tasks.sqlite"
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps(
        {"workbench": str(tree), "data_dir": str(data), "store_db": str(db), "sources_dir": sources_path(tmp_path)}), encoding="utf-8")
    (project / "docs" / "workbench" / "state.md").write_text(STATE, encoding="utf-8")
    (project / "AGENTS.md").write_text("# Project\n", encoding="utf-8")
    er = lab.load()
    monkeypatch.setattr(er, "ROOT", str(tree))
    monkeypatch.setattr(er, "EXECUTOR", "host")
    monkeypatch.setattr(er, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er, "RETRY_PAUSE", 0)
    monkeypatch.setattr(er, "PAUSE_POLL", 0.05)
    monkeypatch.setattr(er, "PROBE_SECONDS", 0)
    runner = load_runner()  # the runner's own copies of the names the kit reads for itself
    monkeypatch.setattr(runner, "ROOT", str(tree))
    monkeypatch.setattr(runner, "EXECUTOR", "host")
    monkeypatch.setattr(runner, "RETRY_PAUSE", 0)
    set_models(monkeypatch, lab)
    # The proof of the stand-in skills (runtime/proof.py): the model "m" is reliable, with a measured usage and a price, the
    # model "fm" has no evidence, the measurement files are the recorded ones and the image is the evidence's.
    monkeypatch.setattr(lab, "standing", lambda skill: {
        "skill": skill, "version": "0.1.0", "lab_models": ["m", "fm"], "adapters": {"m": "h", "fm": "h"},
        "models": {"m": {"band": "reliable", "cause": None, "score": 0.9, "mean": 0.95, "runs": 6, "web_measured": False,
                         "usage_mean": {"input": 1000.0, "output": 200.0, "cache_read": 0.0, "cache_write": 0.0}, "source": "lab"}},
        "local": {}, "web_cases": [], "evidence_images": [STANDIN_IMAGE]})
    monkeypatch.setattr(load("prices"), "load", lambda path=None: {"models": {"m": {
        "input_usd_per_mtok": 1.0, "output_usd_per_mtok": 5.0, "cache_read_usd_per_mtok": 0.1, "cache_write_usd_per_mtok": 1.25,
        "source": "https://prices.example/models", "accessed": "2026-10-01"}}})
    monkeypatch.setattr(lab, "local_evidence_base", lambda: str(tmp_path / "local-evidence"))  # the stand-in tree holds no status script
    monkeypatch.setattr(lab, "proof_inputs", lambda skill: "standin-" + skill)
    monkeypatch.setattr(lab, "measurement_problem", lambda: None)
    monkeypatch.setattr(lab, "image", lambda: {"name": "standin", "digest": STANDIN_IMAGE, "platform": "linux/arm64"})
    runs = load("ops_runs")  # the dispatcher starts no process here: a child is a run made in the calling thread, in turn
    real_spawn = runs.spawn
    monkeypatch.setattr(runs, "spawn", serial_spawn(runs))
    monkeypatch.setattr(runs, "SPAWNED", [])
    monkeypatch.setattr(runs, "STOPPING", threading.Event())
    monkeypatch.setattr(runs, "WAIT_STEP", 0.01)
    return {"tree": tree, "project": project, "data": data, "db": db, "adapter": adapter, "real_spawn": real_spawn,
            "sources": Path(sources_path(tmp_path))}


def set_models(monkeypatch, lab, passes=None, adapters=None) -> None:
    """The models of the stand-in gate file, for the lab facade: {"m": the first lab model, "fm": a second one}, each with the
    variables its credential passes (names only; passes maps a model to its list, the default is none) and its adapter
    ("h"). A test that needs the billing of a model to differ calls this again with its own passes. Patches lab.models,
    default_model, resolve_model, names_of and reference."""
    passes = {"m": [], "fm": [], **(passes or {})}
    adapters = {"m": "h", "fm": "h", **(adapters or {})}
    control = {"total_jobs": 2, "web_jobs": {"m": 1, "fm": 1}, "web_jobs_default": 1}

    def resolve_model(model=None):
        if model is None:
            return "m"
        if model not in passes:
            raise lab.LabError("config", f"{model!r} is not a model of evals/eval-gate.json: the lab runs the models the file lists")
        return model
    monkeypatch.setattr(lab, "models", lambda: list(passes))
    monkeypatch.setattr(lab, "default_model", lambda: "m")
    monkeypatch.setattr(lab, "resolve_model", resolve_model)
    monkeypatch.setattr(lab, "names_of", lambda model: [model])
    monkeypatch.setattr(lab, "reference", lambda model=None: {
        "model": resolve_model(model), "adapter": adapters[resolve_model(model)], "pass_env": list(passes[resolve_model(model)]),
        "route": None, "price_source": None, "timeout_seconds": 60, "retries": 2, "control": control})


def cheaper_second_model(monkeypatch, lab, passes=None) -> None:
    """The model "fm" becomes reliable for every stand-in skill, with a measured usage, and cheaper than "m" in the price
    table, so that `auto` chooses it when its key is found. passes maps a model to the variables its credential passes."""
    set_models(monkeypatch, lab, passes=passes)
    current = lab.standing
    prices = load("prices")
    table = prices.load()
    table["models"]["fm"] = dict(table["models"]["m"], input_usd_per_mtok=0.1, output_usd_per_mtok=0.5)

    def standing(skill):
        found = current(skill)
        found["models"]["fm"] = dict(found["models"]["m"])
        return found
    monkeypatch.setattr(lab, "standing", standing)
    monkeypatch.setattr(prices, "load", lambda path=None: table)


def calls(adapter: Path) -> list:
    path = adapter / "calls.txt"
    return path.read_text().split("\n")[:-1] if path.is_file() else []


def fail(adapter: Path, kind: str, times: int) -> None:
    (adapter / "fail-kind").write_text(kind + "\n")
    (adapter / "fail-times").write_text(f"{times}\n")
