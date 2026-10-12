"""Tests of MSG-3c: the page draws only what its channel policy allows (interface/js/permissions.js and the controls that ask it).

The static part is offline and needs no Node: the module exists and has no network call, every write function of js/api.js is
either named in OPS (its controls ask `can`) or in EXEMPT (with its reason), every file that sends a write asks `can`, and the changed
files hold no innerHTML, no inline style and no colour literal. The behaviour part runs the real modules under Node with the fake
document of test_interface_floor.py and a fake client: what each control draws and sends under a policy, the keyboard paths that send
without a button, and the redraw when the allowed list changes. No browser and no model: the page was looked at in a browser pane
against a seeded fictional project by the package's report.

Run: uv run --offline --with pytest python3 -m pytest runtime/tests/test_interface_msg3c.py -q
"""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from test_interface_floor import FAKE_DOM, INTERFACE, NODE, needs_node, run_node  # noqa: F401  (FAKE_DOM is written by run_node)

JS = INTERFACE / "js"
CHANGED = [
    "permissions.js", "floor/cards.js", "floor/inbox.js", "floor/task-actions.js", "floor/tasks-tab.js", "floor/agent-tab.js", "floor/widgets.js",
    "cards/plan.js", "cards/plan-waits.js", "views/floor.js", "views/lobby.js", "views/lobby-composer.js", "views/lobby-request.js",
    "views/lobby-thread.js", "views/lobby-actions.js", "views/lobby-inbox.js", "views/lobby-agent.js",
]
# the files that send a write on a person's click or key, each of which must ask `can` before it draws the control
CALLERS = ["floor/cards.js", "cards/plan.js", "cards/plan-waits.js", "floor/task-actions.js", "floor/agent-tab.js", "views/lobby.js", "views/lobby-composer.js", "views/lobby-request.js"]


def text(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


def keys_of(block_name: str) -> set[str]:
    source = text("permissions.js")
    body = re.search(r"export const " + block_name + r" = Object\.freeze\(\{(.*?)\n\}\);", source, re.S)
    assert body, block_name
    return set(re.findall(r"^\s+([A-Za-z]+):", body.group(1), re.M))


# --- static --------------------------------------------------------------------------------------------------------------------------

def test_permissions_module_exists_has_no_network_and_covers_absent_null_list_and_pairs():
    source = text("permissions.js")
    assert not re.search(r"\bfetch\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon|import .* from \"\./(api|transport|data)\.js\"", source)
    assert not re.search(r"innerHTML|document\.|window\.", source), "the module only reads a list"
    for name in ("can", "withheld", "OPS", "EXEMPT", "lineText", "fingerprint", "reader"):
        assert re.search(rf"export (function|const) {name}\b", source), name
    for rule in ("permissions", "Array.isArray(found.allowed)", "`${op}:${kind}`", "startsWith(`${op}:`)"):
        assert rule in source, rule


def test_every_write_function_of_api_is_gated_or_exempt_with_a_reason():
    api = text("api.js")
    posts = set()
    for chunk in api.split("\nexport function ")[1:]:
        body = chunk.split("\n}\n", 1)[0]
        if 'send("POST"' in body:
            posts.add(re.match(r"\w+", chunk).group(0))
    # the transport helpers that are not operations carry no route of their own
    assert posts == {"answer", "release", "approve", "reject", "request", "route", "cancel", "retry", "goAhead", "handOver", "verdict", "setMode", "say", "sync", "dispatch"}
    ops, exempt = keys_of("OPS"), keys_of("EXEMPT")
    # a write that does not spell send("POST") the usual way (a method key, a verb in a variable) is found too
    wrote = {re.match(r"\w+", chunk).group(0) for chunk in api.split("\nexport function ")[1:]
             if re.search(r"\bPOST\b|\bPUT\b|\bDELETE\b|\bPATCH\b|\bmethod:", chunk.split("\n}\n", 1)[0])}
    assert wrote <= ops | exempt | {"transport"}, f"api.js functions that write and are in neither list: {sorted(wrote - ops - exempt)}"
    assert not ops & exempt, "a function is gated or exempt, not both"
    assert ops | exempt == posts, f"api.js writes {sorted(posts)}; permissions.js names {sorted(ops | exempt)}"
    reasons = re.findall(r"^\s+(?:cancel|setMode|sync|dispatch): \"(.+)\",$", text("permissions.js"), re.M)
    assert len(reasons) == 4 and all(len(r) > 10 for r in reasons)
    for name in ("cancel", "setMode"):
        assert "brake" in re.search(rf"{name}: \"(.*)\"", text("permissions.js")).group(1)


def test_every_file_that_calls_a_gated_write_asks_can():
    ops = keys_of("OPS")
    callers = set()
    for path in sorted(JS.rglob("*.js")):
        rel = path.relative_to(JS).as_posix()
        if rel.startswith(("scene/", "demo/")) or rel in ("api.js", "floor/actions.js"):
            continue
        source = path.read_text(encoding="utf-8")
        if any(re.search(rf"\b(api|env\.api|api\(\))\.{name}\(", source) for name in ops):
            callers.add(rel)
    assert callers == {"floor/cards.js", "cards/plan.js", "floor/task-actions.js", "floor/agent-tab.js", "views/lobby-actions.js"}, sorted(callers)
    for rel in CALLERS:
        source = text(rel)
        assert "permissions.js" in source or rel in ("views/lobby-composer.js", "views/lobby.js", "views/lobby-request.js"), rel
        assert re.search(r"\bcan\b|\bmay\(|reader\(|\bmayTalk\b", source), f"{rel} never asks whether the page may"
    # lobby-actions only builds the calls: lobby.js decides whether to make them
    assert re.search(r"may\(\"say\"\)", text("views/lobby.js")) and re.search(r"may\(\"request\"\)", text("views/lobby.js")) and re.search(r"may\(\"route\"\)", text("views/lobby.js"))
    # the keyboard paths: press() and the composer's submit() ask too, not only the code that draws the buttons
    assert "if (!permits(word)) return;" in text("floor/cards.js")
    assert "!mayTalk" in text("views/lobby-composer.js")
    assert "if (!can(OPERATION[kind])) return;" in text("floor/task-actions.js")


def test_the_changed_files_hold_no_markup_string_no_inline_style_and_no_colour_literal():
    for rel in CHANGED:
        source = text(rel)
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", source), rel
        assert not re.search(r"\.style\b|\bstyle\s*[=:]\s*[\"'`]|setAttribute\(\s*[\"']style", source), rel
        assert not re.search(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|\b(?:rgba?|hsla?)\(", source), rel


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_node_check_passes_on_every_changed_file():
    for rel in CHANGED:
        done = subprocess.run([NODE, "--check", str(JS / rel)], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, f"{rel}: {done.stderr}"


# --- the rules --------------------------------------------------------------------------------------------------------------------------

RULES = r"""
import { can, withheld, lineText, fingerprint, reader, OPS, EXEMPT } from "@JS@/permissions.js";
const list = (allowed) => ({ id: "p", permissions: { channel: "page", allowed } });
const out = {};
out.absent = [can({ id: "p" }, "release"), can({ id: "p" }, "approve", "plan"), can(null, "say"), can(undefined, "say")];
out.nullOnes = [can({ id: "p", permissions: null }, "release"), can({ id: "p", permissions: null }, "approve", "effect")];
out.notUnderstood = [can({ id: "p", permissions: {} }, "release"), can({ id: "p", permissions: { allowed: "all" } }, "release"), can({ id: "p", permissions: "x" }, "release")];
const read = list(["status", "approve:plan", "cancel", "set-mode:down", "answer"]);
out.plain = [can(read, "answer"), can(read, "release"), can(read, "say"), can(read, "cancel")];
out.pairs = [can(read, "approve", "plan"), can(read, "approve", "acceptance"), can(read, "approve", "effect"), can(read, "approve", "go-ahead"), can(read, "set-mode", "down"), can(read, "set-mode", "up")];
out.approveWithoutKind = [can(read, "approve"), can(list(["answer"]), "approve")];
out.emptyList = [can(list([]), "answer"), can(list([]), "approve", "plan")];
out.withheld = withheld(read, ["answer", "release", ["approve", "go-ahead"], "approve:acceptance", "approve:effect", "release", "say"]);
out.withheldAllowed = withheld(null, ["release", "say"]);
out.line = lineText(["route", "approve", "say", "reject", "approve", "request"]);
const mine = (op) => op === "say";
out.fingerprint = [fingerprint(() => true), fingerprint(() => false), fingerprint(mine)];
out.reader = [reader({}) ("x"), reader({ can: () => false })("x"), reader(null)("x")];
out.keys = [Object.keys(OPS).sort(), Object.keys(EXEMPT).sort(), Object.isFrozen(OPS), Object.isFrozen(EXEMPT), OPS.goAhead, OPS.handOver];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_rules_for_absent_null_a_list_and_pairs(tmp_path):
    got = run_node(tmp_path, RULES)
    assert got["absent"] == [True, True, True, True], "no key (an older service): everything shows as before"
    assert got["nullOnes"] == [True, True], "null (not accepted): the page is under the 412 band, every write answers with the command"
    assert got["notUnderstood"] == [True, True, True], "a shape the page does not know hides nothing"
    assert got["plain"] == [True, False, False, True]
    assert got["pairs"] == [True, False, False, False, True, False]
    assert got["approveWithoutKind"] == [True, False]
    assert got["emptyList"] == [False, False]
    assert got["withheld"] == ["release", "go-ahead", "approve", "say"], "the words are operation names, each once, in the order asked"
    assert got["withheldAllowed"] == []
    assert got["line"] == "Turned off for the page: approve, reject, say, request, route. Use the terminal."
    assert got["fingerprint"][0] != got["fingerprint"][1] != got["fingerprint"][2] and got["fingerprint"][0] != got["fingerprint"][2]
    assert got["reader"] == [True, False, True]
    assert got["keys"][0] == sorted(["answer", "release", "approve", "reject", "request", "route", "retry", "goAhead", "handOver", "verdict", "say"])
    assert got["keys"][1] == sorted(["cancel", "setMode", "sync", "dispatch"])
    assert got["keys"][2:] == [True, True, "go-ahead", "hand-over"]


# --- the cards ----------------------------------------------------------------------------------------------------------------------------

CARDS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";
import { createPlanCard } from "@JS@/cards/plan.js";
import { can as pageMay } from "@JS@/permissions.js";

const HASH = "a".repeat(64);
const PLAN_HASH = "b".repeat(64);
const calls = [];
let policy = null;                    // the allowed list the project entry holds; null: no key
const entry = () => (policy === null ? { id: "p" } : { id: "p", permissions: { channel: "page", allowed: policy } });
const may = (op, kind) => pageMay(entry(), op, kind);
const client = () => {
  const record = (name) => async (...args) => { calls.push([name, ...args.slice(0, 3)]); return name === "approve" || name === "release" ? { job: 1 } : {}; };
  return { answer: record("answer"), release: record("release"), approve: record("approve"), reject: record("reject"), verdict: record("verdict"), cancel: record("cancel"), route: record("route"),
    handOver: record("handOver"), flows: async () => ({ flows: [{ flow: "design", title: "Design" }] }), pollJob: async () => ({ state: "done", result: {} }) };
};
const env = (extra = {}) => ({
  project: "p", now: () => new Date("2026-10-12T12:00:00Z"), api: client(), requestIds: new Set([1]), can: may,
  links: { floor: (a) => `#/p/p/floor/${a}`, lobby: () => "#/p/p/lobby", open: (item, path) => `#/open/${path}`, parent: () => "#/p/p" },
  reread: async () => null, changed() {}, gone() {}, task: async () => ({ drop: { web: false, takes: true } }), ...extra });
const item = (kind, actions, extra = {}) => ({ id: 21, kind, title: `T ${kind}`, body: "body", payload: {}, payload_sha256: null, status: "open", actions, agent: "marketing", task_id: 7, run_id: null, created_at: "2026-10-12T09:00:00Z", ...extra });
const words = (card) => all(card.el, "button.wb-card-button").map((b) => b.attrs["data-word"]);
const line = (card) => { const n = find(card.el, "[data-key=withheld]"); return n ? n.textContent : null; };
const planPayload = { tasks: [{ key: "a", title: "A", skill: "s" }, { key: "b", title: "B", skill: "s", depends_on: ["a"] }], limits: { timeout_seconds: 60, retries: 1 }, plan_sha256: PLAN_HASH,
  waits: [{ task_key: "b", task_id: 5, reason: "waits for A" }] };
const out = {};

// the project may only approve a plan (channels.page: read, approve-plans)
policy = ["status", "approve:plan", "cancel", "set-mode:down"];
const plain = createCard(item("plan", ["approved", "rejected"], { payload: { ...planPayload, waits: [] } }), env());
out.planPlain = { words: words(plain), line: line(plain) };
const plan = createCard(item("plan", ["approved", "rejected"], { payload: planPayload }), env());
out.plan = { words: words(plan), boxes: all(plan.el, "input.wb-checkbox").length, line: line(plan), tick: all(plan.el, ".wb-card-note").map((n) => n.textContent).filter((t) => t.startsWith("Tick")).length, waitsText: find(plan.el, ".wb-waits").textContent.includes("B waits:") };
out.acceptance = (() => { const c = createCard(item("acceptance", ["accepted", "rejected"]), env()); return { words: words(c), line: line(c) }; })();
out.effect = (() => { const c = createCard(item("effect", ["approved", "rejected"], { payload_sha256: HASH }), env()); return { words: words(c), line: line(c), note: all(c.el, "input.wb-field-input").length }; })();
out.question = (() => { const c = createCard(item("question", ["answered"]), env()); return { words: words(c), area: all(c.el, "textarea").length, line: line(c) }; })();
const review = createCard(item("review", ["released", "answered"], { run_id: 4 }), env());
await settle();
out.review = { words: words(review), area: all(review.el, "textarea").length, verdicts: all(review.el, "button.wb-verdict-button").length, hand: all(review.el, "input.wb-file").length, line: line(review) };
const lost = createCard(item("question", ["answered"], { payload: { actions: ["choose-flow", "cancel"], raw: "x" } }), env());
out.lost = { words: words(lost), line: line(lost) };

// the project may approve acceptances only
policy = ["approve:acceptance", "cancel"];
out.acceptanceOnly = (() => { const c = createCard(item("acceptance", ["accepted", "rejected"]), env()); return { words: words(c), line: line(c) }; })();

// everything allowed (the list holds every word) and no key at all: the cards draw as before, no line
policy = ["answer", "release", "reject", "verdict", "hand-over", "route", "approve:plan", "approve:acceptance", "approve:effect", "approve:go-ahead", "cancel"];
const open = createCard(item("review", ["released", "answered"], { run_id: 4 }), env());
await settle();
out.open = { words: words(open), verdicts: all(open.el, "button.wb-verdict-button").length, hand: all(open.el, "input.wb-file").length, line: line(open) };
const openPlan = createCard(item("plan", ["approved", "rejected"], { payload: planPayload }), env());
out.openPlan = { words: words(openPlan), boxes: all(openPlan.el, "input.wb-checkbox").length, line: line(openPlan) };
policy = null;
out.noKey = (() => { const c = createCard(item("plan", ["approved", "rejected"], { payload: planPayload }), env()); return { words: words(c), boxes: all(c.el, "input.wb-checkbox").length, line: line(c) }; })();
// an env without `can` (every existing test): everything shows
const bare = env(); delete bare.can;
out.bare = (() => { const c = createCard(item("acceptance", ["accepted", "rejected"]), bare); return { words: words(c), line: line(c) }; })();

// the keyboard path: Ctrl+Enter in an answer sends without a button, and press() asks too
policy = ["answer"];
const ask = createCard(item("question", ["answered"]), env());
const area = find(ask.el, "textarea");
area.value = "yes";
area.listeners.input.forEach((fn) => fn());
policy = [];      // the policy changed since the card was drawn, and it was not drawn again
calls.length = 0;
area.listeners.keydown.forEach((fn) => fn({ ctrlKey: true, key: "Enter", preventDefault() {} }));
await settle();
out.keyBlocked = calls.length;
policy = ["answer"];
area.listeners.keydown.forEach((fn) => fn({ ctrlKey: true, key: "Enter", preventDefault() {} }));
await settle();
out.keySent = calls.filter((c) => c[0] === "answer").length;

// a card is drawn again when what the page may do changes (redraw), and keeps what was typed
policy = ["answer"];
const rd = createCard(item("review", ["released", "answered"]), env());
const comment = find(rd.el, "textarea");
comment.value = "typed";
comment.listeners.input.forEach((fn) => fn());
out.beforeRedraw = words(rd);
policy = ["answer", "release"];
rd.redraw();
out.afterRedraw = { words: words(rd), kept: find(rd.el, "textarea").value, line: line(rd) };

// the request line: Cancel request is a brake and shows under any policy
policy = [];
const { createRequestLine } = await import("@JS@/floor/cards.js");
const requestLine = createRequestLine({ id: 1, title: "R", state: "running", tasks: [] }, env());
out.cancel = all(requestLine.el, "button").map((b) => b.textContent);
// a route question's "Cancel the request" is the same brake
out.lostCancel = all(lost.el, "button[data-word=cancel-request]").length;

// the Lobby's plan card: the same rule
const api = { approve: async () => ({ job: 1 }), reject: async () => ({}), pollJob: async () => ({ state: "done" }) };
const lobby = (allowed) => createPlanCard({ api, project: "p", item: { ...item("plan", ["approved", "rejected"], { payload: planPayload }), agent: null }, now: new Date("2026-10-12T12:00:00Z"), onChanged: async () => {}, can: (op, kind) => pageMay({ id: "p", permissions: { allowed } }, op, kind) });
const lp = lobby(["approve:plan"]);
out.lobbyPlan = { buttons: all(lp.el, "button.wb-card-button").map((b) => b.textContent), boxes: all(lp.el, "input.wb-checkbox").length, line: find(lp.el, "[data-key=withheld]").textContent, note: all(lp.el, "input.wb-field-input").length };
const lpAll = lobby(["approve:plan", "reject", "approve:go-ahead"]);
out.lobbyPlanAll = { buttons: all(lpAll.el, "button.wb-card-button").map((b) => b.textContent), boxes: all(lpAll.el, "input.wb-checkbox").length, line: find(lpAll.el, "[data-key=withheld]") };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_cards_draw_only_what_the_policy_allows_and_say_what_is_turned_off(tmp_path):
    got = run_node(tmp_path, CARDS)
    sentence = lambda words: f"Turned off for the page: {words}. Use the terminal."  # noqa: E731
    # channels.page: read, approve-plans
    assert got["planPlain"] == {"words": ["approved"], "line": sentence("reject")}, "Approve shows, Reject is gone, the line names it"
    assert got["plan"]["words"] == ["approved"] and got["plan"]["boxes"] == 0 and got["plan"]["tick"] == 0
    assert got["plan"]["line"] == sentence("reject, go-ahead") and got["plan"]["waitsText"], "the go-ahead boxes are left out, the wait stays as a sentence"
    assert got["acceptance"] == {"words": [], "line": sentence("approve, reject")}, "an acceptance card has no Approve"
    assert got["effect"] == {"words": [], "line": sentence("approve, reject"), "note": 0}, "the note of a reject has no field when reject is off"
    assert got["question"] == {"words": [], "area": 0, "line": sentence("answer")}
    assert got["review"] == {"words": [], "area": 0, "verdicts": 0, "hand": 0, "line": sentence("answer, release, verdict, hand-over")}
    assert got["lost"] == {"words": ["cancel-request"], "line": sentence("answer, route")}
    assert got["lostCancel"] == 1, "cancelling the request is a brake: its button shows under any policy"
    assert got["acceptanceOnly"] == {"words": ["accepted"], "line": sentence("reject")}
    assert got["open"] == {"words": ["released", "answered"], "verdicts": 3, "hand": 1, "line": None}
    assert got["openPlan"] == {"words": ["approved", "rejected"], "boxes": 1, "line": None}
    assert got["noKey"] == {"words": ["approved", "rejected"], "boxes": 1, "line": None}, "no permissions key: as before"
    assert got["bare"] == {"words": ["accepted", "rejected"], "line": None}, "an environment without can allows everything"
    assert got["keyBlocked"] == 0 and got["keySent"] == 1, "Ctrl+Enter sends only while the page may answer"
    assert got["beforeRedraw"] == ["answered"] and got["afterRedraw"] == {"words": ["released", "answered"], "kept": "typed", "line": None}
    assert got["cancel"] == ["Cancel request"]
    assert got["lobbyPlan"] == {"buttons": ["Approve this plan"], "boxes": 0, "line": sentence("reject, go-ahead"), "note": 0}
    assert got["lobbyPlanAll"] == {"buttons": ["Approve this plan", "Reject"], "boxes": 1, "line": None}


# --- the tasks' actions and the Agent tab -----------------------------------------------------------------------------------------------

TASKS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createTaskActions } from "@JS@/floor/task-actions.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
import * as fm from "@JS@/floor-model.js";
import { can as pageMay } from "@JS@/permissions.js";

let policy = null;
const may = (op, kind) => pageMay(policy === null ? { id: "p" } : { id: "p", permissions: { allowed: policy } }, op, kind);
const calls = [];
const record = (name) => async (...args) => { calls.push([name, ...args.slice(0, 3)]); return {}; };
const api = { retry: record("retry"), goAhead: record("goAhead"), setMode: record("setMode"), handOver: record("handOver") };
const out = {};
const failed = { id: 5, state: "failed", title: "F" };
const planned = { id: 6, state: "planned", title: "P", waiting_for: [{ task_id: 5, reason: "needs 5" }, { task_id: null, request_id: 2, reason: "after request #2" }] };
const names = (nodes) => nodes.map((n) => n.attrs["data-key"] || n.attrs.role || n.tagName);
const labels = (nodes) => nodes.filter((n) => n.tagName === "BUTTON").map((n) => n.attrs["aria-label"]);
const lineOf = (nodes) => { const n = nodes.find((x) => x.attrs["data-key"] === "withheld"); return n ? n.textContent : null; };

const actions = createTaskActions({ project: "p", api, refresh() {}, redraw() {}, can: may });
policy = ["retry", "cancel"];
let nodes = actions.nodes(failed, { pending: [], links: {} });
out.retryOnly = { labels: labels(nodes), line: lineOf(nodes) };
nodes = actions.nodes(planned, { pending: [], links: {} });
out.goAheadOff = { labels: labels(nodes), line: lineOf(nodes) };
policy = ["go-ahead", "cancel"];
nodes = actions.nodes(failed, { pending: [], links: {} });
out.retryOff = { labels: labels(nodes), line: lineOf(nodes) };
nodes = actions.nodes(planned, { pending: [], links: {} });
out.goAheadOn = { labels: labels(nodes), line: lineOf(nodes) };
// a stale button pressed after the policy changed sends nothing
const stale = actions.nodes(failed, { pending: [], links: {} });
policy = ["go-ahead"];
calls.length = 0;
policy = [];
nodes = actions.nodes(failed, { pending: [], links: {} });
out.none = { labels: labels(nodes), line: lineOf(nodes) };
const before = actions.signature();
policy = ["retry"];
const afterSig = actions.signature();
out.signatureMoves = JSON.stringify(before) !== JSON.stringify(afterSig);
const staleRetry = createTaskActions({ project: "p", api, refresh() {}, redraw() {}, can: may });
policy = ["retry"];
const pressable = staleRetry.nodes(failed, { pending: [], links: {} }).find((n) => n.tagName === "BUTTON");
policy = [];
calls.length = 0;
pressable.click();
await settle();
out.staleSent = calls.length;
policy = ["retry"];
pressable.click();
await settle();
out.freshSent = calls.filter((c) => c[0] === "retry").length;
const bare = createTaskActions({ project: "p", api, refresh() {}, redraw() {} });
out.bare = labels(bare.nodes(failed, { pending: [], links: {} })).length + labels(bare.nodes(planned, { pending: [], links: {} })).length;

// the Agent tab: Stop agent and Supervise are brakes (never withheld), Retry and the hand-over follow the policy
const P = "0123456789ab";
const NOW = new Date("2026-10-12T12:00:00Z");
const agent = { name: "design", pack: "x", enabled: true, mode: "autonomous", acting_mode: "autonomous", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0, wider: [] };
const task = (id, state, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "design-system", state, note: null, agent: "design", requestId: 2, waiting_for: [], ...extra });
const drop = { web: true, takes: true, line: "visible to a run with the open network" };
const view = (tasks) => fm.floor({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 2, title: "R", state: "planned", tasks }], pending: [], held: [] }, agents: [agent] } }, tasks: {}, loaded: true }, P, "design",
  Object.fromEntries(tasks.map((t) => [t.id, { task: { id: t.id }, runs: [], pending: [], drop }])));
policy = ["status", "cancel", "set-mode:down"];
const tab = createAgentTab({ project: P, agent: "design", api, refresh() {}, now: () => NOW, can: may, task: async (id) => ({ task: { id }, drop }) });
tab.update(view([task(11, "failed")]));
await settle();
const hand = () => find(tab.el, ".wb-hand");
out.agentOff = {
  stop: find(tab.el, "button[data-key=stop-agent]").disabled, supervise: find(tab.el, "button[data-key=supervise]").disabled,
  retry: all(tab.el, "button[data-key=retry-11]").length, taskLine: all(find(tab.el, ".wb-current"), "[data-key=withheld]").map((n) => n.textContent), handLine: all(hand(), "[data-key=withheld]").map((n) => n.textContent),
  chooser: all(hand(), "input.wb-file").map((n) => n.hidden || n.disabled), handHidden: find(hand(), ".wb-hint").hidden,
};
find(tab.el, "button[data-key=stop-agent]").click();
await settle();
out.stopSent = calls.filter((c) => c[0] === "setMode").map((c) => c.slice(2));
policy = ["retry", "hand-over", "cancel", "set-mode:down"];
tab.update(view([task(11, "failed")]));
await settle();
out.agentOn = { retry: all(tab.el, "button[data-key=retry-11]").length, taskLine: all(tab.el, "[data-key=withheld]").map((n) => n.textContent), handHidden: find(hand(), ".wb-hint").hidden, handDisabled: find(hand(), "input.wb-file").disabled };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_task_actions_and_the_agent_tab_follow_the_policy(tmp_path):
    got = run_node(tmp_path, TASKS)
    sentence = lambda words: f"Turned off for the page: {words}. Use the terminal."  # noqa: E731
    assert got["retryOnly"] == {"labels": ["Retry task 5"], "line": None}
    assert got["goAheadOff"] == {"labels": [], "line": sentence("go-ahead")}, "Go ahead and Drop the after are one operation, go-ahead"
    assert got["retryOff"] == {"labels": [], "line": sentence("retry")}
    assert got["goAheadOn"] == {"labels": ["Go ahead on task 6", "Drop the after of task 6"], "line": None}
    assert got["none"] == {"labels": [], "line": sentence("retry")}
    assert got["signatureMoves"], "the actions' signature changes with the policy, so a tab draws again"
    assert got["staleSent"] == 0 and got["freshSent"] == 1
    assert got["bare"] == 3, "without can every action shows"
    off = got["agentOff"]
    assert off["stop"] is False and off["supervise"] is False, "Stop agent and Supervise narrow a mode: they are drawn and enabled whatever the policy holds"
    assert off["retry"] == 0 and off["taskLine"] == [sentence("retry")]
    assert off["chooser"] == [True] and off["handHidden"] is True and off["handLine"] == [sentence("hand-over")]
    assert got["stopSent"] == [["design", "stopped"]], "Stop agent is a brake: it sends whatever the policy holds"
    assert got["agentOn"]["retry"] == 1 and got["agentOn"]["taskLine"] == [] and got["agentOn"]["handHidden"] is False


# --- the Lobby ------------------------------------------------------------------------------------------------------------------------

LOBBY = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createComposer } from "@JS@/views/lobby-composer.js";
import { createBlock } from "@JS@/views/lobby-request.js";
import { createRequest } from "@JS@/views/lobby-actions.js";
import { can as pageMay } from "@JS@/permissions.js";

const out = {};
const sent = [];
let news = 0;
const composer = createComposer({ onSend: (t) => sent.push(t), onNew: () => { news += 1; } });
const field = () => find(composer.el, "textarea");
const sendButton = () => find(composer.el, "button.wb-send");
const newButton = () => find(composer.el, "button.wb-new-btn");
const line = () => { const n = find(composer.el, "[data-key=withheld]"); return n ? n.textContent : null; };
const state = () => ({ send: sendButton().hidden, news: newButton().hidden, readOnly: field().readOnly === true, line: line(), hint: find(composer.el, "small").hidden });
out.before = state();
composer.set({ sending: false, notice: null, disabled: false, say: false, request: false });
out.off = state();
field().value = "hello";
field().listeners.keydown.forEach((fn) => fn({ key: "Enter", preventDefault() {} }));
find(composer.el, "form").listeners.submit.forEach((fn) => fn({ preventDefault() {} }));
newButton().click();
out.offSent = [sent.length, news];
// a set that leaves the keys out keeps them (the Lobby's send() sets only sending and the notice)
composer.set({ sending: true, notice: null, disabled: false });
out.keeps = state();
composer.set({ sending: false, notice: null, disabled: false, say: true, request: false });
out.requestOff = state();
composer.set({ sending: false, notice: null, disabled: false, say: true, request: true });
out.on = state();
field().listeners.keydown.forEach((fn) => fn({ key: "Enter", preventDefault() {} }));
newButton().click();
out.onSent = [sent.length, news];

// the request block: Route it is withheld with a line, Cancel request stays
const NOW = new Date("2026-10-12T12:00:00Z");
const block = (allowed) => createBlock({ api: {}, project: "p1", request: { id: 20, title: "From the form", state: "requested", tasks: [] }, body: { pending: [] }, open: 0, now: NOW,
  onChanged: async () => {}, onCancel() {}, onRoute() {}, routing: false, flows: null, can: (op, kind) => pageMay({ id: "p1", permissions: { allowed } }, op, kind) });
const names = (b) => ({ route: all(b.el, "button.wb-route-button").length, cancel: all(b.el, "button.wb-lobby-cancel-link").length, line: (find(b.el, "[data-key=withheld]") || { textContent: null }).textContent });
out.blockOff = names(block(["status", "cancel"]));
out.blockOn = names(block(["status", "cancel", "route"]));

// createRequest: without route the second call is not made
const calls = [];
const api = { request: async (p, text) => { calls.push("request"); return { request: 9 }; }, route: async () => { calls.push("route"); return { job: 1 }; } };
out.unrouted = await createRequest(api, "p", { text: "do it" }, { route: false });
out.routed = (await createRequest(api, "p", { text: "do it" })).request;
out.calls = calls;
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_lobby_composer_and_request_line_follow_the_policy(tmp_path):
    got = run_node(tmp_path, LOBBY)
    assert got["before"] == {"send": False, "news": False, "readOnly": False, "line": None, "hint": False}
    assert got["off"] == {"send": True, "news": True, "readOnly": True, "line": "Turned off for the page: say, request. Use the terminal.", "hint": True}
    assert got["offSent"] == [0, 0], "Enter in the field, the form and New request send and open nothing while they are withheld"
    assert got["keeps"] == got["off"], "a set that names neither key keeps both"
    assert got["requestOff"]["send"] is False and got["requestOff"]["news"] is True and got["requestOff"]["line"] == "Turned off for the page: request. Use the terminal."
    assert got["on"] == got["before"]
    assert got["onSent"] == [1, 1]
    assert got["blockOff"] == {"route": 0, "cancel": 1, "line": "Turned off for the page: route. Use the terminal."}
    assert got["blockOn"] == {"route": 1, "cancel": 1, "line": None}
    assert got["unrouted"] == {"request": 9, "unrouted": True} and got["routed"] == 9
    assert got["calls"] == ["request", "request", "route"]


# --- the plumbing -----------------------------------------------------------------------------------------------------------------------

def test_the_floor_and_the_lobby_read_the_project_entry_at_every_draw_and_the_commands_are_read_again_on_a_reload():
    floor = text("views/floor.js")
    lobby = text("views/lobby.js")
    for source in (floor, lobby):
        assert re.search(r'import \{ can as pageMay[^}]*\} from "\.\./permissions\.js";', source)
        assert "(last.snapshot.projects || []).find((p) => p.id === project)" in source, "the getter reads the entry of the current snapshot, not a copy"
    for part in ("createAgentTab({", "createInbox({", "createTasksTab({"):
        assert re.search(re.escape(part) + r".{0,400}?can: may", floor, re.S), part
    for part in ("createThread({", "createLobbyInbox({", "createLobbyAgent({", "createTasksTab({"):
        assert re.search(re.escape(part) + r".{0,400}?can: may", lobby, re.S), part
    assert "allowedKey !== commandsKey" in lobby and "seq === commandsSeq" in lobby, "the \"/\" list is read again only when what the page may do changes, and a late answer is dropped"
    assert "commandsAsked = false;      // the policy" not in lobby, "not on every reload stamp"
    inbox = text("floor/inbox.js")
    assert "card.redraw()" in inbox and "fingerprint(can)" in inbox, "the Inbox draws its cards again when what the page may do changes"
    assert "fingerprint(can)" in text("floor/task-actions.js") and "fingerprint(can)" in text("views/lobby-thread.js")
    for rel in ("views/lobby-inbox.js", "views/lobby-agent.js"):
        assert "can: env.can" in text(rel)


def test_the_readme_says_what_the_page_withholds_and_that_the_service_still_refuses():
    readme = (INTERFACE / "README.md").read_text(encoding="utf-8")
    assert "permissions.js" in readme and "Turned off for the page" in readme and "409" in readme and "brake" in readme


EXTRA = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createForm } from "@JS@/views/lobby-form.js";
import { createPlanCard } from "@JS@/cards/plan.js";
import { createThread } from "@JS@/views/lobby-thread.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
import * as fm from "@JS@/floor-model.js";
import { can as pageMay } from "@JS@/permissions.js";

FakeNode.prototype.insertBefore = function (n, ref) {      // the fake document has no insertBefore, which the thread uses
  if (n.parent) n.parent.children = n.parent.children.filter((c) => c !== n);
  n.parent = this;
  const at = ref ? this.children.indexOf(ref) : -1;
  if (at < 0) this.children.push(n); else this.children.splice(at, 0, n);
  return n;
};
Object.defineProperty(FakeNode.prototype, "lastElementChild", { get() { return this.children[this.children.length - 1] || null; } });
const out = {};
// the New request form: without route the Flow select is left out, no flow is sent, a line says so
const created = [];
const form = createForm({ onCreate: (v) => created.push(v) });
const flowLabel = () => all(form.el, "label").find((l) => l.textContent.startsWith("Flow"));
find(form.el, "select").value = "design";
out.formOn = { hidden: flowLabel().hidden, line: find(form.el, "[data-key=withheld]") ? 1 : 0 };
form.setRoute(false);
find(form.el, "textarea").value = "x";
find(form.el, "form").listeners.submit.forEach((fn) => fn({ preventDefault() {} }));
out.formOff = { hidden: flowLabel().hidden, line: find(form.el, "[data-key=withheld]").textContent, sent: created[0] };
form.setRoute(true);
out.formBack = { hidden: flowLabel().hidden, line: find(form.el, "[data-key=withheld]") ? 1 : 0 };

// the Lobby's plan card keeps a typed reject note when the thread builds it again
const allowed = { v: ["approve:plan", "reject"] };
const item = { id: 9, kind: "plan", title: "Plan", body: "", payload: { plan_sha256: "c".repeat(64), tasks: [{ key: "a", title: "A", skill: "s", depends_on: [] }], limits: { timeout_seconds: 60, retries: 1 } }, payload_sha256: "c".repeat(64), status: "open", actions: ["approved", "rejected"], agent: null, task_id: 4, run_id: null, created_at: "2026-10-12T09:00:00Z" };
const can = (op, kind) => pageMay({ id: "p", permissions: { allowed: allowed.v } }, op, kind);
const thread = createThread({ api: {}, project: "p", signal: undefined, onChanged: async () => {}, onCancel() {}, onRoute() {}, can });
const state = { messages: [{ id: 1, role: "agent", text: "Plan", created_at: "2026-10-12T09:00:00Z" }], requests: [{ id: 4, title: "R", state: "planned", tasks: [] }], pending: [item], bodies: { 4: { pending: [item] } }, now: new Date("2026-10-12T12:00:00Z"), loading: false, routing: new Set(), notices: new Map(), flows: null, remembered: new Map() };
thread.update({ ...state, messages: [{ id: 1, role: "assistant", text: "Plan for request 4", created_at: "2026-10-12T09:00:00Z", task_id: 4 }] });
const noteField = () => all(thread.el, "input.wb-field-input")[0];
out.noteBefore = noteField() ? 1 : 0;
if (noteField()) { noteField().value = "not now"; noteField().listeners.input.forEach((fn) => fn()); }
allowed.v = ["approve:plan"];
thread.update({ ...state, messages: [{ id: 1, role: "assistant", text: "Plan for request 4", created_at: "2026-10-12T09:00:00Z", task_id: 4 }] });
out.noteAfter = noteField() ? 1 : 0;
allowed.v = ["approve:plan", "reject"];
thread.update({ ...state, messages: [{ id: 1, role: "assistant", text: "Plan for request 4", created_at: "2026-10-12T09:00:00Z", task_id: 4 }] });
out.noteBack = noteField() ? noteField().value : null;

// the Agent tab: the hand-over line only when there is a task to hand a file to
const P = "0123456789ab";
const agent = { name: "design", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0, wider: [] };
const view = (tasks) => fm.floor({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: tasks.length ? [{ id: 2, title: "R", state: "planned", tasks }] : [], pending: [], held: [] }, agents: [agent] } }, tasks: {}, loaded: true }, P, "design", {});
const tab = createAgentTab({ project: P, agent: "design", api: {}, refresh() {}, now: () => new Date(), can: (op) => op !== "hand-over" });
tab.update(view([]));
await settle();
out.noTarget = all(find(tab.el, ".wb-hand"), "[data-key=withheld]").length;
tab.update(view([{ id: 11, key: "k", title: "T", skill: "s", state: "failed", note: null, agent: "design", requestId: 2, waiting_for: [] }]));
await settle();
out.target = all(find(tab.el, ".wb-hand"), "[data-key=withheld]").length;
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_review_fixes_form_flow_plan_note_and_hand_line(tmp_path):
    got = run_node(tmp_path, EXTRA)
    assert got["formOn"] == {"hidden": False, "line": 0}
    assert got["formOff"] == {"hidden": True, "line": "Turned off for the page: route. Use the terminal.", "sent": {"text": "x", "flow": "", "title": ""}}
    assert got["formBack"] == {"hidden": False, "line": 0}
    assert got["noteBefore"] == 1 and got["noteAfter"] == 0 and got["noteBack"] == "not now", "the typed note survives the card being built again"
    assert got["noTarget"] == 0 and got["target"] == 1, "the line is drawn only when there is a target"
