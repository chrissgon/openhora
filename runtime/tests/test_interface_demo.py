"""Tests of the interface's demo mode (R4-D1): the real interface with fictional data and no service, built by scripts/build_demo.py from
interface/ and interface/demo/. Offline: no browser, no model, no network. The world, the story and the bridge run headless under Node
with a fake clock and a fake scheduler; the fixtures are compared with what the real operations answer now (the stand-in tree of
standin_tree.py, through scripts/demo_fixtures.py). The built page was looked at in a browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_demo.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

import standin_tree as st

REPO = st.REPO
INTERFACE = REPO / "interface"
DEMO = INTERFACE / "demo"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the demo's modules are tested only by their text")
service = st.load("service")
ops = st.load("ops")


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_demo = load_script("build_demo")
demo_fixtures = load_script("demo_fixtures")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("built") / "site"
    build_demo.build(out)
    return out


def js_files(root: Path, skip=()):
    """The .js files under `root` except those under a skipped folder: each skip is the first parts of a path, such as ("vendor", "three")."""
    return [p for p in sorted(root.rglob("*.js")) if not any(p.relative_to(root).parts[:len(prefix)] == prefix for prefix in skip)]


# --- the built page makes no network call ---------------------------------------------------------------------------------------------

THREE = ("vendor", "three")      # the one exemption of the scan, by path (the reason is in the first test below)
NETWORK = re.compile(r"\bfetch\(|XMLHttpRequest|\bWebSocket\b|\bEventSource\b|sendBeacon|\bnew\s+Request\b|https?://|\bimport\(\s*[^\s\"'`]")


def test_the_built_tree_holds_no_network_call_and_its_transport_is_the_demos(built):
    # vendor/three/ is the one exception, by path: the 3D library carries loaders (file, image) that call the network and `http://` namespace
    # names; the page loads no model, texture or file with it (the scene is built in code), and the browser's request log in the package's
    # report shows the page asking for nothing but its own files. Every other JS file, the page's own and the demo's, holds none of these.
    offenders = []
    for path in js_files(built, skip=(THREE,)):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if NETWORK.search(line):
                offenders.append(f"{path.relative_to(built)}:{number}: {line.strip()[:80]}")
    # the same for the built page's styles and documents: no absolute URL, but the SVG namespace name that the vendored library's own data URIs hold
    for path in sorted(p for p in built.rglob("*") if p.suffix in (".css", ".html") and p.relative_to(built).parts[:len(THREE)] != THREE):
        text = path.read_text(encoding="utf-8")
        found = re.findall(r"https?:[^\s'\"]*", text)
        allowed = path.relative_to(built).parts[:2] == ("vendor", "perfectui") and all(f == "http://www.w3.org/2000/svg" for f in found)
        assert not found or allowed, f"{path.relative_to(built)} holds an absolute URL: {found[:2]}"
    assert offenders == []
    assert (built / "js" / "transport.js").read_bytes() == (DEMO / "transport.js").read_bytes(), "the built page's js/transport.js is the demo's"
    assert not (built / "README.md").exists() and not list(built.rglob("tests")), "the built copy has no README and no tests"
    # the page's policy stays default-src 'self': no inline script, no inline style, no handler attribute in the page
    page = (built / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\ssrc=)", page) and "style=" not in page and not re.search(r"\son[a-z]+=", page)
    assert page.index("./demo/boot.js") < page.index("./js/main.js"), "boot.js runs before main.js"
    assert '<link rel="stylesheet" href="./demo/demo.css">' in page


def test_every_url_of_the_built_page_is_relative_and_every_import_resolves(built):
    # the demo is served from any folder path: no absolute path in the page, and every module import names a file of the built tree
    page = (built / "index.html").read_text(encoding="utf-8")
    for url in re.findall(r'(?:src|href)="([^"]+)"', page):
        assert url.startswith("./"), url
    for path in js_files(built, skip=(("vendor",),)):
        for target in re.findall(r"""(?:import|export)[^;]*?from\s+["']([^"']+)["']|import\(\s*["']([^"']+)["']""", path.read_text(encoding="utf-8")):
            spec = target[0] or target[1]
            assert spec.startswith("."), f"{path.relative_to(built)} imports {spec}: only relative imports"
            assert (path.parent / spec).resolve().is_file(), f"{path.relative_to(built)} imports {spec}, which is not in the built tree"


@needs_node
def test_every_javascript_file_of_the_demo_parses():
    for path in js_files(DEMO):
        done = subprocess.run([NODE, "--check", str(path)], capture_output=True, text=True, timeout=30)
        assert done.returncode == 0, f"{path.name}: {done.stderr}"


def test_only_api_js_imports_the_transport_and_only_it_calls_it():
    # a second caller is caught here as a second `fetch(` was: transport.js is imported by api.js alone and `transport(` is called there alone
    allowed = {"js/api.js", "js/transport.js", "demo/transport.js"}
    importers, callers = [], []
    for path in js_files(INTERFACE, skip=(("vendor",),)):
        rel_path = path.relative_to(INTERFACE).as_posix()
        text = path.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(("//", "*", "/*")))
        if re.search(r"""from\s+["'](?:\./|\.\./)transport\.js["']|import\(\s*["'][^"']*transport\.js""", code):
            importers.append(rel_path)
        if re.search(r"\btransport\(", code):
            callers.append(rel_path)
    assert importers == ["js/api.js"], importers
    assert set(callers) <= allowed and "js/api.js" in callers, callers


def test_the_real_interface_has_one_transport_which_is_the_browsers_and_no_switch_to_the_demo():
    transport = (INTERFACE / "js" / "transport.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in transport.splitlines() if not line.lstrip().startswith("//"))
    assert code.count("fetch(") == 1 and "export function transport(url, init)" in code
    assert not re.search(r"localStorage|sessionStorage|location|URLSearchParams|import |demo", code), "nothing in the real transport can switch it"
    api = (INTERFACE / "js" / "api.js").read_text(encoding="utf-8")
    assert not re.search(r"\bfetch\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon", api) and len(re.findall(r"\btransport\(", api)) == 1
    for path in js_files(INTERFACE, skip=(("vendor",), ("demo",))):
        if path.name != "transport.js":
            assert not re.search(r"\bfetch\(|XMLHttpRequest|\bWebSocket\b|\bEventSource\b|sendBeacon", path.read_text(encoding="utf-8")), path.name
        if path.name != "transport.js":      # its comment says what the build does; its code is checked above
            assert "demo" not in path.read_text(encoding="utf-8").lower().replace("demonstrat", ""), f"{path.name} names the demo"
    page = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert "demo" not in page.lower(), "the real page does not load the demo"


# --- the service never serves the demo ------------------------------------------------------------------------------------------------


def test_the_service_never_serves_the_demos_files():
    held = types.SimpleNamespace(interface_dir=str(INTERFACE))
    assert service._static(held, "GET", "/js/transport.js")[0] == 200, "the real transport is served"
    for path in ("/demo/world.js", "/demo/boot.js", "/demo/fixtures/status.json", "/demo/demo.css", "/demo/../demo/world.js", "/DEMO/world.js",
                 "/Demo/fixtures/status.json", "/%64emo/world.js", "/demo/", "/demo"):
        assert service._static(held, "GET", path)[0] == 404, path


# --- what is in the demo is fictional ---------------------------------------------------------------------------------------------------

DOMAINS = {"northwind.example", "code.example", "prices.example"}
DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io|dev|app|ai|co|example|test|local|edu|gov)\b")
EMAIL = re.compile(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+")
HANDLE = re.compile(r"(?<![\w.])@[A-Za-z0-9_]{2,}")
# the words a real project or person would leave: built from pieces so that this file is not itself a hit
REAL = re.compile("|".join(["open" + "hora-brand", "bt" + "j", "tel" + "ar", "kyr" + "ios", "chris" + "sgon", "/Us" + "ers/", "/ho" + "me/(?!demo)"]), re.I)


def demo_texts():
    return [p for p in sorted(DEMO.rglob("*")) if p.is_file() and p.suffix in {".js", ".json", ".css"}]


def test_everything_in_the_demo_is_fictional():
    assert demo_texts()
    for path in demo_texts():
        text = path.read_text(encoding="utf-8")
        assert not REAL.search(text), f"{path.relative_to(INTERFACE)} names a real project, person or path"
        for domain in {m.group(0) for m in DOMAIN.finditer(text)}:
            assert domain in DOMAINS and domain.endswith((".example", ".test")), f"{path.relative_to(INTERFACE)}: the domain {domain} is not on the list of fictional ones"
        assert not EMAIL.findall(text) and (path.suffix == ".css" or not HANDLE.findall(text)), f"{path.relative_to(INTERFACE)} holds an address or a handle"
    # the only person is "Demo Person"; the projects are the three fictional ones
    content = (DEMO / "content.js").read_text(encoding="utf-8")
    assert 'PERSON = "Demo Person"' in content
    assert set(re.findall(r'name: "([a-z0-9-]+-[a-z]+)",\n    folder', content)) == {"northwind-shop", "tinykv-docs", "lumen-notes"}


def test_the_skills_fixture_is_the_workbenchs_own_list_with_its_snapshot_commit():
    fixture = json.loads((DEMO / "fixtures" / "skills.json").read_text(encoding="utf-8"))
    inventory = (REPO / "docs" / "inventory.md").read_text(encoding="utf-8")
    commit = re.search(r"Generated at commit `([0-9a-f]+)`", inventory).group(1)
    assert fixture["snapshot"]["commit"] == commit, "regenerate the fixtures: python3 scripts/demo_fixtures.py --write"
    names = {row["name"] for row in fixture["skills"]}
    assert names == {p.parent.name for p in (REPO / "skills").glob("*/SKILL.md")}
    for row in fixture["skills"]:
        assert [p["model"] for p in row["proof"]] == [m["model"] for m in fixture["models"]], "one pair per model the gate file lists, in its order"


# --- the fixtures are the operations' answers -------------------------------------------------------------------------------------------


def test_the_fixtures_have_the_keys_the_real_operations_answer_now():
    fixtures = demo_fixtures.build()
    assert demo_fixtures.differences(DEMO / "fixtures", fixtures) == [], "run: python3 scripts/demo_fixtures.py --write"
    # the shapes the page reads are really there: every kind of decision, a request a router run holds, a task that runs
    kinds = {fixtures[f"pending-{k}"]["kind"] for k in ("plan", "question", "review", "effect", "acceptance")}
    assert kinds == {"plan", "question", "review", "effect", "acceptance"}
    assert any(r["routing"] for r in fixtures["status-routing"]["requests"])
    assert any(t["state"] == "running" for r in fixtures["status-live"]["requests"] for t in r["tasks"])


def test_the_generator_refuses_nothing_it_was_not_given_and_prints_its_help():
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "demo_fixtures.py"), "--help"], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0 and "--write" in done.stdout and "--check" in done.stdout
    none = subprocess.run([sys.executable, str(REPO / "scripts" / "demo_fixtures.py")], capture_output=True, text=True, timeout=30)
    assert none.returncode == 2


# --- the build ----------------------------------------------------------------------------------------------------------------------------


def test_the_build_script_prints_its_sizes_refuses_a_full_folder_and_replaces_only_its_own_build(tmp_path):
    out = tmp_path / "site"
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "build_demo.py"), "--out", str(out)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report["total_bytes"] > report["vendor_three_bytes"] > 1_000_000 and report["files"] > 100 and report["out"] == str(out.resolve())
    again = subprocess.run([sys.executable, str(REPO / "scripts" / "build_demo.py"), "--out", str(out)], capture_output=True, text=True, timeout=60)
    assert again.returncode == 1 and "not empty" in again.stderr and again.stdout == ""
    assert subprocess.run([sys.executable, str(REPO / "scripts" / "build_demo.py"), "--out", str(out), "--replace"], capture_output=True, text=True, timeout=60).returncode == 0
    other = tmp_path / "mine"
    other.mkdir()
    (other / "notes.txt").write_text("not a build")
    refused = subprocess.run([sys.executable, str(REPO / "scripts" / "build_demo.py"), "--out", str(other), "--replace"], capture_output=True, text=True, timeout=60)
    assert refused.returncode == 1 and (other / "notes.txt").is_file(), "--replace removes only an earlier build of the demo"
    helped = subprocess.run([sys.executable, str(REPO / "scripts" / "build_demo.py"), "--help"], capture_output=True, text=True, timeout=30)
    assert helped.returncode == 0 and "--out" in helped.stdout
    assert subprocess.run([sys.executable, str(REPO / "scripts" / "build_demo.py")], capture_output=True, text=True, timeout=30).returncode == 2


# --- the world, the story and the bridge, headless --------------------------------------------------------------------------------------

HARNESS = r"""
import { createWorld } from "@DEMO@/world.js";
import { createAutopilot, STEPS } from "@DEMO@/scenario.js";
import { createBridge, commandOf } from "@DEMO@/bridge.js";

const P = "3f9a1c07d2b4";
let now = Date.UTC(2026, 9, 11, 12, 0, 0);
let timers = [];
let next = 1;
const schedule = (fn, ms) => { const id = next++; timers.push({ id, fn, due: now + ms }); return id; };
const cancel = (id) => { timers = timers.filter((t) => t.id !== id); };
let inflight = 0;
const nap = () => new Promise((resolve) => setTimeout(resolve, 3));
const settle = async () => { do { await nap(); } while (inflight > 0); await nap(); };
function watch(world) {
  for (const name of ["apply", "reset"]) {
    const original = world[name];
    world[name] = async (...args) => { inflight += 1; try { return await original(...args); } finally { inflight -= 1; } };
  }
  return world;
}
async function advance(ms) {
  const end = now + ms;
  for (;;) {
    await settle();
    const due = timers.filter((t) => t.due <= end).sort((a, b) => a.due - b.due || a.id - b.id)[0];
    if (!due) break;
    timers = timers.filter((t) => t !== due);
    now = Math.max(now, due.due);
    due.fn();
  }
  now = end;
  await settle();
}
const fresh = (clock = () => now) => watch(createWorld({ now: clock, later: schedule, cancelLater: cancel }));
const get = async (world, path, query = "") => (await world.handle("GET", "/api/v1" + path, new URLSearchParams(query))).body;
const post = async (world, path, body = {}) => world.handle("POST", "/api/v1" + path, new URLSearchParams(), body);
const summary = async (world) => {
  const d = await world.dump();
  return Object.fromEntries(Object.values(d.projects).map((p) => [p.name, {
    requests: p.tasks.filter((t) => t.parent_id === null).map((t) => [t.id, t.title, t.state]),
    tasks: p.tasks.filter((t) => t.parent_id !== null).map((t) => [t.id, t.parent_id, t.key, t.state]),
    pending: p.pending.map((i) => ({ id: i.id, kind: i.kind, status: i.status, actions: i.actions, task: i.task_id, hash: i.payload_sha256 || (i.payload && i.payload.plan_sha256) || null })),
    accepted: p.accepted, routing: p.routing, agents: p.agents.map((a) => [a.name, a.mode, a.runs]),
  }]));
};
const withoutGeneration = (d) => { const { generation, ...rest } = d; return JSON.stringify(rest); };
const out = {};

// 1. the whole story, headless: every step posted in order, the world after each, and the replay back to the first state
{
  const world = fresh(() => Date.UTC(2026, 9, 11, 12, 0, 0));      // a clock that stands still: the replay is compared with the first state
  const posts = [];
  const routes = [];
  const ap = createAutopilot({ world, setRoute: (h) => routes.push(h), schedule, cancel, post: (m) => posts.push(m), reduced: false });
  const first = withoutGeneration(await world.dump());
  const snaps = [];
  let seen = 0;
  let before = null;
  await ap.play();
  for (let i = 0; i < 800 && !posts.some((m) => m.type === "ended"); i++) {
    await advance(100);
    const state = (await summary(world))["northwind-shop"];
    while (seen < posts.length) {
      const m = posts[seen++];
      if (before && m.type === "step") snaps.push({ at: "end:" + before.id, route: null, state: before.state });
      snaps.push({ at: m.type + ":" + m.id, route: routes[routes.length - 1], state });
    }
    before = { id: posts.filter((m) => m.type === "step").pop().id, state };
  }
  out.posts = posts.slice(); out.snaps = snaps; out.routes = routes.slice();
  out.ticks = Math.round((now - Date.UTC(2026, 9, 11, 12, 0, 0)) / 1000);
  const last = withoutGeneration(await world.dump());
  out.changed = first !== last;
  await ap.replay();
  ap.pause();
  out.replayEqual = withoutGeneration(await world.dump()) === first;
  out.replayStatus = [ap.status, ap.index, routes[routes.length - 1]];
}

// 2. take over: the autopilot stops, nothing advances, play goes on from the step it stopped in
{
  const world = fresh();
  const posts = [];
  const ap = createAutopilot({ world, setRoute: () => {}, schedule, cancel, post: (m) => posts.push(m) });
  await ap.play();
  await advance(7000);
  const before = posts.length;
  out.tookOver = ap.takeOver();
  await advance(80000);
  out.afterTakeOver = [before, posts.length, ap.status, ap.index, ap.takeOver()];
  await ap.play();
  await advance(1000);
  out.resumed = [ap.status, ap.index, posts.length > before];
}

// 3. reduced motion: nothing advances by itself; play shows the next step at once; goto the step named, with what came before it
{
  const world = fresh();
  const posts = [];
  const routes = [];
  const ap = createAutopilot({ world, setRoute: (h) => routes.push(h), schedule, cancel, post: (m) => posts.push(m), reduced: true });
  await advance(60000);
  const idle = posts.length;
  await ap.play();
  await advance(60000);
  const afterOne = [posts.length, routes.length, timers.length];
  await ap.play();
  await ap.goto(5);
  const snap = (await summary(world))["northwind-shop"];
  await ap.goto(STEPS.length - 1);
  out.reduced = { idle, afterOne, ids: posts.map((m) => m.type + ":" + m.id), goto5: snap, timers: timers.length, status: ap.status, last: routes[routes.length - 1] };
}

// 4. the approvals: a hash that is not the content's is refused, the content's own is taken, an earlier approval covers nothing new
{
  const world = fresh();
  for (const op of ["type-request", "open-plan"]) await world.apply({ op });
  const plan = (await get(world, `/projects/${P}/pending`)).pending.find((i) => i.kind === "plan");
  const poll = async (job) => { await get(world, `/jobs/${job.job}`); return get(world, `/jobs/${job.job}`); };
  const badPlan = await post(world, `/projects/${P}/pending/${plan.id}/approve`, { sha256: "0".repeat(64) });
  const badPlanJob = await poll(badPlan.body);
  const goodPlan = await post(world, `/projects/${P}/pending/${plan.id}/approve`, { sha256: plan.plan.plan_sha256 });
  const goodPlanJob = await poll(goodPlan.body);
  for (const op of ["finish-build", "release-build", "open-effect"]) await world.apply({ op });
  const effect = (await get(world, `/projects/${P}/pending`)).pending.find((i) => i.kind === "effect");
  const item = await get(world, `/projects/${P}/pending/${effect.id}`);
  const bad = await post(world, `/projects/${P}/pending/${effect.id}/approve`, { sha256: plan.plan.plan_sha256 });
  const badJob = await poll(bad.body);
  const nothing = await post(world, `/projects/${P}/pending/${effect.id}/approve`, {});
  const stillOpen = (await get(world, `/projects/${P}/pending/${effect.id}`)).status;
  const good = await post(world, `/projects/${P}/pending/${effect.id}/approve`, { sha256: item.payload_sha256 });
  const goodJob = await poll(good.body);
  const again = await post(world, `/projects/${P}/pending/${effect.id}/approve`, { sha256: item.payload_sha256 });
  out.approvals = {
    badPlan: [badPlan.status, badPlanJob.state, badPlanJob.error && badPlanJob.error.error], goodPlan: [goodPlan.status, goodPlanJob.state, goodPlanJob.result.plan_sha256 === plan.plan.plan_sha256],
    effectHashIsInBody: item.body.includes(item.payload_sha256) && item.payload_sha256 !== plan.plan.plan_sha256, effectHash: item.payload_sha256,
    bad: [bad.status, badJob.state, badJob.error.error, badJob.error.message.includes(item.payload_sha256)], nothing: [nothing.status, (await poll(nothing.body)).state], stillOpen,
    good: [good.status, goodJob.state, goodJob.result.task_state], again: (await poll(again.body)).state,
    effectBody: item.body, hashLength: item.payload_sha256.length,
  };
}

// 5. every route and write answers with the keys the fixtures have; the demo's refusals have the service's shape
{
  const world = fresh();
  const answers = [];
  const note = (name, answer) => answers.push({ name, status: answer.status, body: answer.body });
  const read = async (path, query) => { const a = await world.handle("GET", "/api/v1" + path, new URLSearchParams(query || "")); if (a.status === 200) note("GET " + path.replace(/\/p?[0-9a-f]{12}/, "/{p}").replace(/\/[0-9]+$/, "/{id}"), a); return a; };
  const write = async (path, body, label) => { const a = await post(world, path, body); note("POST " + (label || path), a); if (a.status === 202) { await get(world, `/jobs/${a.body.job}`); note("GET /jobs/{id}", { status: 200, body: await get(world, `/jobs/${a.body.job}`) }); } return a; };
  const projectPaths = ["status", "pending", "agents", "conversation", "skills", "costs", "connections", "artifacts", "flows", "progress", "version", "commands", "tasks/2", "tasks/1", "pending/1", "artifact?path=docs/design/alt-text.md"];
  const readAll = async () => { await read("/projects"); await read("/versions"); for (const p of ["3f9a1c07d2b4", "a84e6b2f0c19", "5c27d90e81fa"]) for (const path of projectPaths) { const [bare, query] = path.split("?"); await read(`/projects/${p}/${bare}`, query); } };
  await readAll();
  const B = "a84e6b2f0c19";
  const C = "5c27d90e81fa";
  await write(`/projects/${C}/pending/1/answer`, { text: "Students." }, "answer");
  await write(`/projects/${B}/pending/1/release`, {}, "release");
  await write(`/projects/${B}/requests`, { text: "Write the backup page", flow: "write-docs" }, "request-flow");
  const plain = await write(`/projects/${B}/requests`, { text: "Add a size guide." }, "request");
  await write(`/projects/${B}/requests/${plain.body.request}/route`, {}, "route");
  await write(`/projects/${B}/conversation`, { text: "Hello there" }, "say");
  await write(`/projects/${B}/conversation`, { text: "/status" }, "say-command");
  await write(`/projects/${B}/agents/engineering/mode`, { mode: "stopped" }, "mode-down");
  const sayRequest = (await get(world, `/projects/${B}/conversation`)).messages.filter((m) => m.role === "assistant" && m.task_id).pop().task_id;
  await write(`/projects/${B}/requests/${sayRequest}/cancel`, {}, "cancel");
  for (const op of ["type-request", "open-plan"]) await world.apply({ op });
  const plan = (await get(world, `/projects/${P}/pending`)).pending.find((i) => i.kind === "plan");
  await write(`/projects/${P}/pending/${plan.id}/reject`, { note: "Not now." }, "reject");
  await readAll();
  for (const op of ["type-request", "open-plan", "approve-plan", "finish-build", "release-build", "open-effect"]) await world.apply({ op });
  await readAll();
  const effect = (await get(world, `/projects/${P}/pending`)).pending.find((i) => i.kind === "effect");
  await write(`/projects/${P}/pending/${effect.id}/reject`, {}, "reject-effect");
  const runs = (await get(world, `/projects/${P}/tasks/2`)).runs;
  await write(`/projects/${P}/runs/${runs[0].id}/verdict`, { word: "worked" }, "verdict");
  const refusals = {};
  for (const [label, path, body] of [["answer-empty", `/projects/${P}/pending/${effect.id}/answer`, { text: "" }], ["go-ahead", `/projects/${P}/tasks/3/go-ahead`, {}], ["hand-over", `/projects/${P}/tasks/3/files`, { name: "a.txt", content_base64: "AA==" }],
    ["sync", `/projects/${P}/sync`, {}], ["dispatch", `/projects/${P}/dispatch`, {}], ["retry-ready", `/projects/${P}/tasks/3/retry`, {}], ["unknown-project", "/projects/ffffffffffff/status", null], ["unknown-route", `/projects/${P}/nothing`, null]]) {
    const a = body === null ? await world.handle("GET", "/api/v1" + path) : await post(world, path, body);
    refusals[label] = [a.status, a.body.error, typeof a.body.message];
  }
  const raw = await world.handle("GET", `/api/v1/projects/${P}/artifact/raw`, new URLSearchParams("path=docs/x.png"));
  refusals.raw = [raw.status, raw.body.error, raw.body.message];
  const up = await post(world, `/projects/${P}/agents/engineering/mode`, { mode: "autonomous" });
  note("POST mode-up", up);
  const after = await world.handle("GET", `/api/v1/projects/${P}/status`);
  refusals.unaccepted = [after.status, after.body.error, after.body.next && after.body.next.includes("accept-config"), after.body.message.includes("accepted one is")];
  const list = (await get(world, "/projects")).projects.find((p) => p.id === P);
  const versions = (await get(world, "/versions")).versions[P];
  out.unaccepted = { upBody: up.body, list, versions, keepsOthers: (await world.handle("GET", `/api/v1/projects/${B}/status`)).status };
  await world.reset();
  out.afterReset = [(await world.handle("GET", `/api/v1/projects/${P}/status`)).status, (await get(world, "/versions")).versions[P].version];
  out.answers = answers;
  out.refusals = refusals;
}

// 7. a visitor who takes over and sends a request: the story still reaches its plan, on the request it made, and the visitor's router run ends
{
  const world = fresh();
  const routes = [];
  const ap = createAutopilot({ world, setRoute: (h) => routes.push(h), schedule, cancel, post: () => {} });
  await ap.play();
  await advance(7000);                      // the City step takes 6 s: now in the Lobby step, before the story types its request
  out.visitorTook = ap.takeOver();
  const sent = await post(world, `/projects/${P}/conversation`, { text: "Hello there" });
  await get(world, `/jobs/${sent.body.job}`);
  const mine = (await get(world, `/projects/${P}/conversation`)).messages.filter((m) => m.task_id).pop().task_id;
  await ap.play();                          // resumes the Lobby step
  await advance(14000);                     // through the plan step and its approval
  const d = await world.dump();
  const P1 = d.projects[P];
  const story = P1.tasks.find((t) => t.parent_id === null && t.title === "Spring sale page");
  out.visitor = {
    mine, story: story && story.id, routing: P1.routing, plan: routes.filter((r) => r.includes("/request/")).pop(),
    visitorRuns: P1.runs.filter((r) => r.task_id === mine).map((r) => r.status),
    visitorState: P1.tasks.find((t) => t.id === mine).state,
    storyTasks: P1.tasks.filter((t) => t.parent_id === (story && story.id)).map((t) => t.state),
    running: P1.runs.filter((r) => r.status === "running").map((r) => r.task_id),
  };
  // cancelling a request that a router run holds ends that run too
  const again = await post(world, `/projects/${P}/conversation`, { text: "Another line" });
  await get(world, `/jobs/${again.body.job}`);
  const theirs = (await world.dump()).projects[P];
  const held = theirs.routing && theirs.routing.request;
  await post(world, `/projects/${P}/requests/${held}/cancel`);
  const after = (await world.dump()).projects[P];
  out.cancelled = [Boolean(held), after.routing, after.runs.filter((r) => r.task_id === held).map((r) => r.status)];
}

// 6. the bridge: only the same origin and only the window that frames the demo are heard
{
  const heard = [];
  const handlers = [];
  const win = { addEventListener: (type, fn) => handlers.push(fn), removeEventListener: () => {} };
  const parent = { postMessage: (m, origin) => heard.push(["out", m, origin]) };
  const stranger = {};
  const ap = { play: () => heard.push("play"), pause: () => heard.push("pause"), replay: () => heard.push("replay"), goto: (n) => heard.push("goto" + n) };
  const bridge = createBridge({ win, parent, origin: "https://site.example", autopilot: ap });
  const send = (event) => handlers[0](event);
  send({ origin: "https://site.example", source: parent, data: { type: "play" } });
  send({ origin: "https://evil.example", source: parent, data: { type: "pause" } });
  send({ origin: "https://site.example", source: stranger, data: { type: "replay" } });
  send({ origin: "null", source: parent, data: { type: "replay" } });
  send({ origin: "https://site.example", source: parent, data: { type: "goto", step: 3 } });
  send({ origin: "https://site.example", source: parent, data: { type: "format-disk" } });
  send({ origin: "https://site.example", source: parent, data: "play" });
  send({ origin: "https://site.example", source: parent, data: null });
  send({ origin: "https://site.example", source: parent, data: { type: "goto", step: "3" } });
  bridge.post({ type: "ready", steps: 9 });
  const alone = createBridge({ win, parent: win, origin: "https://site.example", autopilot: ap });
  alone.post({ type: "ready" });
  const opaque = createBridge({ win, parent, origin: "null", autopilot: ap });
  handlers[2]({ origin: "null", source: parent, data: { type: "play" } });      // a page with an opaque origin hears nobody
  opaque.post({ type: "ready" });
  out.opaque = [heard.length, opaque.heard, bridge.heard];
  out.bridge = { heard, plain: [commandOf({ origin: "o", source: parent, data: { type: "pause" } }, "o", parent), commandOf({ origin: "o", source: parent, data: { type: "x" } }, "o", parent)] };
}

console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    if NODE is None:
        pytest.skip("node is not installed")
    folder = tmp_path_factory.mktemp("harness")
    script = folder / "harness.mjs"
    script.write_text(HARNESS.replace("@DEMO@", DEMO.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


STEP_IDS = ["city", "lobby", "plan", "building", "floor", "review", "effect", "request-done", "control-room"]


@needs_node
def test_the_story_has_the_storyboards_nine_steps_in_order_with_its_durations_and_a_caption_key_each(run):
    scenario = (DEMO / "scenario.js").read_text(encoding="utf-8")
    assert re.findall(r'\{\s*id: "([a-z-]+)", seconds: (\d+), caption: "tour\.([a-z-]+)"', scenario) == [
        (i, s, i) for i, s in zip(STEP_IDS, ["6", "6", "7", "6", "6", "6", "8", "6", "6"])]
    posts = run["posts"]
    assert [m["id"] for m in posts if m["type"] == "step"] == STEP_IDS
    assert [m["step"] for m in posts if m["type"] == "step"] == list(range(9)) and posts[-1]["type"] == "ended" and posts[-1]["id"] == "control-room"
    assert all(m["caption"] == f"tour.{m['id']}" for m in posts)
    assert 56 <= run["ticks"] <= 58, "about a minute: 57 seconds"
    assert run["routes"][0] == "#/city" and run["routes"][-1].endswith("/control/skills")


@needs_node
def test_the_story_moves_the_world_through_valid_states_and_ends_with_the_request_done(run):
    by = {s["at"]: s["state"] for s in run["snaps"]}
    spring = lambda s: next(r for r in s["requests"] if r[1] == "Spring sale page")  # noqa: E731
    tasks = lambda s: [t[3] for t in s["tasks"] if t[1] == spring(s)[0]]  # noqa: E731
    assert not any(r[1] == "Spring sale page" for r in by["step:city"]["requests"]), "the City shows the project before the request"
    assert spring(by["step:plan"])[2] == "requested" and any(p["kind"] == "plan" and p["status"] == "open" for p in by["step:plan"]["pending"])
    assert (spring(by["step:building"])[2], tasks(by["step:building"])) == ("planned", ["running", "planned"])
    assert tasks(by["step:floor"]) == ["running", "planned"]
    assert tasks(by["step:review"]) == ["waiting", "planned"] and any(p["kind"] == "review" and p["status"] == "open" for p in by["step:review"]["pending"])
    assert tasks(by["step:effect"]) == ["done", "running"], "the marketing task starts when the review is released"
    assert tasks(by["end:effect"]) == ["done", "done"] and any(p["kind"] == "effect" and p["status"] == "resolved" for p in by["end:effect"]["pending"]), "the effect is approved by the end of its step"
    assert tasks(by["step:request-done"]) == ["done", "done"] and any(p["kind"] == "acceptance" and p["status"] == "open" for p in by["step:request-done"]["pending"])
    assert any(p["kind"] == "effect" for p in by["end:effect"]["pending"]) and spring(by["step:request-done"])[2] == "planned", "all tasks done, the request waits for its acceptance"
    last = by["step:control-room"]
    assert spring(last)[2] == "done" and not [p for p in last["pending"] if p["status"] == "open"], "the request is done and nothing waits in the project"
    assert not [t for t in last["tasks"] if t[3] in ("running", "waiting", "ready")]
    assert run["changed"] and run["replayEqual"], "replay returns the world to its first state"
    assert run["replayStatus"][1] == 0 and run["replayStatus"][2] == "#/city"


@needs_node
def test_every_open_decision_has_the_action_words_of_its_kind_as_the_runtime_gives_them(run):
    spec = importlib.util.spec_from_file_location("store_under_test", REPO / "providers" / "store" / "sqlite.py")
    store = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = store
    spec.loader.exec_module(store)
    seen = set()
    for snap in run["snaps"]:
        for item in snap["state"]["pending"]:
            real = ops._actions(store, {"kind": item["kind"], "status": item["status"]})
            assert item["actions"] == real, (snap["at"], item["kind"], item["status"])
            seen.add(item["kind"])
    assert seen == {"plan", "review", "effect", "acceptance"}
    for answer in run["answers"]:
        body = answer["body"]
        if answer["name"].startswith("GET /projects/{p}/pending") and isinstance(body, dict) and "kind" in body:
            assert body["actions"] == ops._actions(store, {"kind": body["kind"], "status": body["status"]})


@needs_node
def test_an_approval_is_checked_against_the_hash_of_the_exact_content(run):
    a = run["approvals"]
    assert a["badPlan"] == [202, "failed", "refused"] and a["goodPlan"] == [202, "done", True]
    assert a["effectHashIsInBody"] and len(a["effectHash"]) == 64 and a["effectHash"] in a["effectBody"]
    # an approval of another content (the plan's hash, as an earlier approval would have left) covers nothing: the effect stays open
    assert a["bad"] == [202, "failed", "refused", True] and a["nothing"] == [202, "failed"] and a["stillOpen"] == "open"
    assert a["good"] == [202, "done", "done"] and a["again"] == "failed", "approved once, and not again"
    text = re.search(r"Post:\n(.+)\n", a["effectBody"]).group(1)
    import hashlib
    assert a["effectHash"] == hashlib.sha256(json.dumps({"account": "northwind-shop", "kind": "publish", "text": text}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@needs_node
def test_a_visitors_own_request_does_not_break_the_story(run):
    v = run["visitor"]
    assert run["visitorTook"] is True and v["mine"] == 4 and v["story"] == 5, "the visitor's request took the number the story had assumed"
    assert v["plan"].endswith("/request/5"), "the plan step opens the story's request, found by its title"
    assert v["routing"] is None and v["visitorRuns"] == ["ok"] and v["visitorState"] == "requested", "the visitor's router run ended; their request waits for its route"
    assert v["storyTasks"] == ["running", "planned"] and v["running"] == [6], "the story went on to its plan and its approval, and its first task runs"
    held, routing, runs = run["cancelled"]
    assert held and routing is None and runs == ["ok"], "cancelling a request ends the router run it held"


@needs_node
def test_taking_over_stops_the_autopilot_and_play_goes_on_from_the_step(run):
    assert run["tookOver"] is True
    before, after, status, index, again = run["afterTakeOver"]
    assert before == after and status == "paused" and index == 1 and again is False, "nothing advances after a take over"
    assert run["resumed"] == ["playing", 1, True]


@needs_node
def test_under_reduced_motion_the_autopilot_does_not_advance_by_itself(run):
    r = run["reduced"]
    assert r["idle"] == 0, "nothing at all until the parent moves it"
    assert r["afterOne"][0] == 1 and r["afterOne"][2] == 0, "play shows one step and leaves no timer"
    assert r["ids"][:2] == ["step:city", "step:lobby"] and r["ids"][-2:] == ["step:control-room", "ended:control-room"]
    assert r["timers"] == 0 and r["status"] == "ended" and r["last"].endswith("/control/skills")
    spring = next(t for t in r["goto5"]["tasks"] if t[2] == "build-page")
    assert spring[3] == "waiting", "goto the review step: the changes before it are there"


@needs_node
def test_the_bridge_hears_only_the_same_origin_and_the_window_that_frames_the_demo(run):
    heard = run["bridge"]["heard"]
    assert heard == ["play", "goto3", ["out", {"type": "ready", "steps": 9}, "https://site.example"]]
    assert run["bridge"]["plain"] == [{"type": "pause"}, None]
    assert run["opaque"] == [3, False, True], "an opaque origin hears nobody and says nothing; the bridge that heard a command says so"


@needs_node
def test_every_answer_and_write_of_the_world_has_only_keys_the_fixtures_have(run):
    fixtures = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (DEMO / "fixtures").glob("*.json")}
    sk = demo_fixtures.skeleton
    merged = demo_fixtures.merge

    def union(*names):
        out = None
        for name in names:
            out = merged(out, sk(fixtures[name]))
        return out

    item = union(*[f"pending-{k}" for k in ("plan", "question", "review", "effect", "acceptance")])
    shapes = {
        "GET /projects": union("projects"), "GET /versions": union("versions"), "GET /projects/{p}/status": {**union("status", "status-routing", "status-live"), "pending": union("pending")["pending"]},   # the same rows as `pending` (ops._listed)
        "GET /projects/{p}/pending": union("pending"), "GET /projects/{p}/pending/{id}": item, "GET /projects/{p}/agents": union("agents"),
        "GET /projects/{p}/conversation": union("conversation"), "GET /projects/{p}/skills": {"skills": sk(fixtures["skills"]["skills"]), "checks": sk(fixtures["skills"]["checks"]), "models": sk(fixtures["skills"]["models"]), "default_model": None, "recommended_model": None},
        "GET /projects/{p}/costs": union("costs"), "GET /projects/{p}/connections": union("connections"), "GET /projects/{p}/artifacts": union("artifacts"),
        "GET /projects/{p}/flows": union("flows"), "GET /projects/{p}/progress": union("progress"), "GET /projects/{p}/version": union("version"),
        "GET /projects/{p}/commands": union("commands"), "GET /projects/{p}/tasks/{id}": {**union("task", "task-live"), "pending": [item]}, "GET /jobs/{id}": union("job"),
        "GET /projects/{p}/artifact": union("artifact"),
    }
    writes = fixtures["writes"]
    posts = {"answer": "answer", "release": "release", "request-flow": "request-flow", "request": "request", "route": "route", "say": "say", "say-command": "say",
             "mode-down": "set-mode-down", "cancel": "cancel", "reject": "reject", "reject-effect": "release", "verdict": "verdict", "mode-up": "set-mode-up"}

    def within(answer, allowed, where):
        if allowed is None or where.endswith((".result", ".error", ".by_model", ".by_failure")):
            return      # a leaf of the fixture: the result of a job is the operation's own answer, checked below
        if where == "GET /versions.versions":      # keyed by project id: one entry of the fixture stands for each (or {error} for one not accepted)
            for entry in answer.values():
                assert set(entry) <= set(next(iter(allowed.values()))) | {"error"}
            return
        if isinstance(answer, dict):
            assert isinstance(allowed, dict), f"{where}: a table where the fixture has none"
            for key, value in answer.items():
                assert key in allowed, f"{where}: the key {key!r} is not one the operations give"
                within(value, allowed[key], f"{where}.{key}")
        elif isinstance(answer, list) and answer and allowed:
            for element in answer:
                within(element, allowed[0] if isinstance(allowed, list) else allowed, f"{where}[]")

    checked = set()
    for entry in run["answers"]:
        name = entry["name"]
        if name.startswith("POST "):
            allowed = sk(writes[posts[name[5:]]])
            assert entry["status"] in (200, 202), (name, entry)
            body = entry["body"]
            if entry["status"] == 202:
                within(body, union("job"), name)
                continue
        else:
            allowed = shapes[name]
            assert entry["status"] == 200, (name, entry["status"], entry["body"])
            body = entry["body"]
        within(body, allowed, name)
        checked.add(name)
    assert {n for n in shapes} <= checked, sorted(set(shapes) - checked)
    # jobs: the result of each job write has the keys of the operation's answer
    for entry in run["answers"]:
        if entry["name"] == "GET /jobs/{id}" and entry["body"]["state"] == "done":
            result = entry["body"]["result"]
            assert any(set(result) <= set(sk(writes[w])) for w in ("approve-plan", "approve-effect", "release", "route", "say", "set-mode-down")), result


@needs_node
def test_what_the_demo_does_not_support_is_refused_in_the_services_own_shape(run):
    refusals = run["refusals"]
    for label in ("go-ahead", "hand-over", "sync", "dispatch", "raw"):
        assert refusals[label][:2] == [409, "refused"], label
    assert "not part of the demo" in refusals["raw"][2]
    assert refusals["answer-empty"][:2] == [400, "usage"] and refusals["retry-ready"][:2] == [409, "refused"]
    assert refusals["unknown-project"][:2] == [404, "not_found"] and refusals["unknown-route"][:2] == [404, "not_found"]
    errors = json.loads((DEMO / "fixtures" / "errors.json").read_text(encoding="utf-8"))
    assert set(errors["refused"]) == {"error", "message"}
    word = {"refused": "refused", "usage": "usage", "not_found": "not_found"}
    assert all(errors[k]["error"] == word[k] for k in word)


@needs_node
def test_a_move_down_of_a_mode_applies_and_a_move_up_leaves_the_configuration_unaccepted_as_the_runtime_does(run):
    down = next(a for a in run["answers"] if a["name"] == "POST mode-down")["body"]
    assert (down["mode"], down["accepted"], down["by"], down["next"]) == ("stopped", True, "code:narrowing", None)
    up = run["unaccepted"]["upBody"]
    assert up["accepted"] is False and up["by"] is None and up["next"].startswith("python3 ") and "accept-config" in up["next"] and up["config_sha256"] in up["next"]
    assert run["refusals"]["unaccepted"] == [412, "not_configured", True, True]
    listed = run["unaccepted"]["list"]
    assert listed["config"]["accepted"] is False and "message" in listed and "open_pending" not in listed
    assert run["unaccepted"]["versions"] == {"error": "not_configured"} and run["unaccepted"]["keepsOthers"] == 200
    assert run["afterReset"][0] == 200 and run["afterReset"][1] >= 100000, "reset starts the world again, and the change signal keeps growing"
