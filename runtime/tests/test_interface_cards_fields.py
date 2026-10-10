"""Tests of WP-9.15a, the Lobby's request line and its cards, the fields, the token field and the document viewer's Close
(interface/js/views/lobby-request.js, lobby-thread.js, floor/inbox.js, floor/viewer.js, frame/origin.js, interface/css/*.css).

Items of design/INTERFACE-ADJUSTMENTS.md: A-1 (the request line is one ellipsised line, the whole text on a tooltip and an expand),
A-4 (a failed route stays on the request's line), A-5 (the resolved line is one surface with the panel's radius), A-11 (the token
field is not a password field), A-14 (no `.wb-*` rule gives a field a ground), A-19 (the viewer's Close and Escape go back to the tab the
document was opened from). The pure modules and the real views run in Node under a fake document with the real client over a stand-in for
`fetch`; the stylesheet and the token prompt are read as text. No browser, no model, no service: the served page was looked at in the
browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_cards_fields.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st
from test_interface_floor import FAKE_DOM as FLOOR_DOM
from test_interface_lobby import VIEW_EXTRA
from interface_css import stylesheets

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
CSS = stylesheets()
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the views are tested only by their text")


def run_node(tmp_path: Path, body: str) -> dict:
    """Run `body` (an ES module that prints one JSON line) under the Floor's fake document and return what it printed."""
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FLOOR_DOM + VIEW_EXTRA, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- the stylesheet, as text -----------------------------------------------------------------------------------------------

def css_rules() -> list[tuple[str, dict[str, str]]]:
    """Every rule of the stylesheets as (selector text, {property: value}), at any depth of @media nesting."""
    text = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    rules = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        selector = " ".join(match.group(1).split())
        if selector.startswith("@"):
            continue
        declarations = {}
        for part in match.group(2).split(";"):
            if ":" in part:
                name, value = part.split(":", 1)
                declarations[name.strip()] = value.strip()
        rules.append((selector, declarations))
    return rules


def field_classes() -> set[str]:
    """The classes the page's code gives to an input, a textarea or a select (the library's own `pui-` ones are the library's)."""
    found: set[str] = set()
    for source in JS.rglob("*.js"):
        text = source.read_text(encoding="utf-8")
        for match in re.finditer(r'h\("(?:input|textarea|select)",\s*\{[^}]*class:\s*"([^"]+)"', text):
            found.update(c for c in match.group(1).split() if not c.startswith("pui-"))
    return found


def test_no_wb_rule_sets_a_background_on_a_field():
    """A-14: the library's inputs carry no ground and need none; a `.wb-*` rule that painted a field made it darker than its card."""
    classes = field_classes() | {"wb-field", "wb-field-input", "wb-select", "wb-file", "wb-lobby-field"}
    assert {"wb-field-input", "wb-select", "wb-file", "wb-lobby-field"} <= classes, "the scan finds the classes the page puts on its fields"
    offenders = []
    for selector, declarations in css_rules():
        names = [s.strip() for s in selector.split(",")]
        on_field = [s for s in names if re.search(r"(^|[\s>+~])(input|textarea|select)\b", s) or any(re.search(rf"\.{re.escape(c)}(?![\w-])", s) for c in classes)]
        if on_field and any(p.startswith("background") for p in declarations):
            offenders.append(selector)
    assert offenders == [], f"a rule gives a field a background: {offenders}"


def test_a_field_keeps_the_muted_edge():
    """A-14 keeps `--pui-edge` where the edge token is wanted: only the ground goes."""
    edges = [selector for selector, declarations in css_rules() if declarations.get("--pui-edge") == "var(--pui-muted)"]
    assert any(".wb-lobby-field" in s for s in edges) and any(".wb-field-input" in s for s in edges)


def test_the_token_field_is_a_masked_text_field_where_the_browser_can_mask_it_and_never_named_password():
    """A-11: type=password inside a form is what a browser offers to save; the token changes at every start and must not be saved.
    Where the browser cannot mask a text field by CSS the field falls back to type=password (a token in clear is the worse failure)."""
    prompt = (JS / "views" / "token-prompt.js").read_text(encoding="utf-8")
    assert "password" not in re.findall(r'name:\s*"([^"]+)"', prompt)
    assert prompt.count('autocomplete: "off"') >= 2, "the form and the field both say so"
    assert 'CSS.supports("-webkit-text-security", "disc")' in prompt, "the mask is feature-tested, not assumed"
    assert "wb-token-field" in prompt
    rule = next(d for s, d in css_rules() if ".wb-token-field" in s and ("-webkit-text-security" in d or "text-security" in d))
    assert rule.get("-webkit-text-security") == "disc", "the mask is drawn by the stylesheet, so the field keeps hiding the token"


TOKEN = r"""
import { FakeNode } from "@FAKE@";
import { showTokenPrompt } from "@JS@/views/token-prompt.js";
const out = {};
const field = (supports) => {
  if (supports === undefined) delete globalThis.CSS; else globalThis.CSS = { supports: (p, v) => supports && p === "-webkit-text-security" && v === "disc" };
  const root = new FakeNode("div");
  showTokenPrompt(root, { onSubmit() {} });
  const f = [...root.walk()].find((n) => n.attrs.id === "token-field");
  const form = [...root.walk()].find((n) => n.tagName === "FORM");
  return { type: f.attrs.type, name: f.attrs.name, field: f.attrs.autocomplete, form: form.attrs.autocomplete };
};
out.masked = field(true);
out.unsupported = field(false);
out.noCss = field(undefined);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_token_field_falls_back_to_a_password_field_where_the_browser_cannot_mask_text(tmp_path):
    got = run_node(tmp_path, TOKEN)
    assert got["masked"] == {"type": "text", "name": "service-token", "field": "off", "form": "off"}
    assert got["unsupported"]["type"] == "password" and got["noCss"]["type"] == "password", "a browser without the mask would show the token in clear"
    assert got["unsupported"]["name"] == "service-token" and got["unsupported"]["field"] == "off"


# --- A-1 and A-4: the request line, under a fake document ------------------------------------------------------------------

LINE = r"""
import { FakeNode, find, all, text } from "@FAKE@";
import * as router from "@JS@/router.js";
import { createBlock } from "@JS@/views/lobby-request.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const walk = (root) => [...root.walk()];
const byClass = (root, name) => walk(root).filter((n) => n.cls && n.cls().includes(name));
const click = (n) => (n.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {}, target: n }));
const LONG = "Marlowe is the brand of a small studio that makes calm, readable software for shops. It needs a name system, a voice, a logo brief and a launch plan that a weak model can follow without guessing, written as one request.";
const make = (request, extra = {}) => createBlock({ api: {}, project: "p1", request, body: extra.body === undefined ? null : extra.body, open: 0, now: NOW, onChanged: async () => {},
  onCancel: () => {}, onRoute: (r) => extra.routed && extra.routed.push(r.id), routing: false, routeNotice: extra.notice || null });
const out = {};

// 1. the line: number, the title, the state chip, the actions; the title is one control whose tooltip holds the whole text
const request = { id: 16, title: LONG, state: "requested", tasks: [] };
const body = { task: { id: 16, text: LONG + "\nA second paragraph that the title never holds." }, pending: [] };
let block = make(request, { body });
const line = byClass(block.el, "wb-lobby-request-line")[0];
out.order = line.children.map((n) => (n.cls().includes("pui-badge") ? "number" : n.cls().includes("wb-lobby-request-title") ? "title" : n.cls().includes("pui-chip") ? "state" : "action"));
const title = byClass(block.el, "wb-lobby-request-title")[0];
out.title = { tag: title.tagName, text: title.textContent, tip: title.attrs.title, name: title.attrs["aria-label"], expanded: title.attrs["aria-expanded"], type: title.attrs.type };
const full = byClass(block.el, "wb-lobby-request-full")[0];
out.fullBefore = { hidden: full.hidden, text: full.textContent, after: block.el.children.indexOf(full) === block.el.children.indexOf(line) + 1 };
click(title);
out.fullOpen = { hidden: full.hidden, expanded: title.attrs["aria-expanded"], text: full.textContent };
click(title);
out.fullClosed = { hidden: full.hidden, expanded: title.attrs["aria-expanded"] };

// 1b. a rebuilt block (a poll changed what it shows) keeps the text open when it was open
const reopened = createBlock({ api: {}, project: "p1", request, body, open: 0, now: NOW, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {}, routing: false, expanded: true });
const reTitle = byClass(reopened.el, "wb-lobby-request-title")[0];
out.reopened = { expanded: reTitle.attrs["aria-expanded"], hidden: byClass(reopened.el, "wb-lobby-request-full")[0].hidden };
const toggles = [];
const watched = createBlock({ api: {}, project: "p1", request, body, open: 0, now: NOW, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {}, routing: false, onExpand: (open) => toggles.push(open) });
click(byClass(watched.el, "wb-lobby-request-title")[0]); click(byClass(watched.el, "wb-lobby-request-title")[0]);
out.toggles = toggles;

// 2. what the title is: the request's title, else the plan title the service gives, else the text; never "Request 16: Request 16"
const named = (r, b) => { const bl = make(r, { body: b }); return byClass(bl.el, "wb-lobby-request-title")[0]; };
out.fromTitle = named({ id: 3, title: "Add a sale page", state: "requested", tasks: [] }, null).textContent;
out.planTitleIgnored = named({ id: 3, title: "", plan_title: "Plan: sale page", state: "planned", tasks: [] }, null).textContent;
out.fromText = named({ id: 3, title: "", state: "requested", tasks: [] }, { task: { id: 3, text: "Add a sale page\nwith a banner" }, pending: [] }).textContent;
out.fromNothing = named({ id: 3, title: "", state: "requested", tasks: [] }, null).textContent;

// 3. the notice of a route that failed sits under the request's line, in the same element the composer used, with "Route it" on the line
const routed = [];
const notice = { title: "Not routed yet", text: 'Request #16 was created. The flow names skills outside the pack in scope. Use "Route it" on its request line.' };
block = make({ id: 16, title: "Add a sale page", state: "requested", tasks: [] }, { notice, routed });
const children = block.el.children;
const lineAt = children.indexOf(byClass(block.el, "wb-lobby-request-line")[0]);
const noticeNode = byClass(block.el, "wb-lobby-notice-card")[0];
out.notice = { present: Boolean(noticeNode), under: children.indexOf(noticeNode) > lineAt, role: noticeNode.attrs.role, text: noticeNode.textContent };
const routeButton = walk(block.el).find((n) => n.tagName === "BUTTON" && n.textContent === "Route it");
click(routeButton);
out.routeAgain = routed.slice();
out.noNotice = byClass(make({ id: 16, title: "x", state: "requested", tasks: [] }).el, "wb-lobby-notice-card").length;
console.log(JSON.stringify(out));
"""


VIEW_A4 = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createLobbyView } from "@JS@/views/lobby.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = (type, fn) => { document.listeners[type] = (document.listeners[type] || []).filter((f) => f !== fn); };
const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const sent = [];
const answers = new Map();
globalThis.fetch = async (url, init) => {
  sent.push({ method: init.method, url });
  const key = url.includes("/conversation") ? "GET conversation" : `${init.method} ${url.split("?")[0]}`;
  let answer = answers.get(key) || { status: 200, body: {} };
  if (typeof answer === "function") answer = answer();
  return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
};
const A = (path) => `/api/v1/projects/${P}${path}`;
answers.set("GET conversation", { status: 200, body: { messages: [] } });
answers.set(`GET ${A("/flows")}`, { status: 200, body: { flows: [{ flow: "design", title: "Design", tasks: 3 }] } });
answers.set(`GET ${A("/tasks/2")}`, { status: 200, body: { task: { id: 2, text: "Add a sale page, linked from the home page." }, runs: [], pending: [] } });
answers.set(`POST ${A("/requests")}`, { status: 200, body: { request: 2, state: "requested", next: "route" } });
let routeAnswer = { status: 409, body: { error: "refused", message: "the flow design names skills outside the pack in scope: biz-market-analysis" } };
answers.set(`POST ${A("/requests/2/route")}`, () => routeAnswer);
answers.set("GET /api/v1/jobs/7", { status: 200, body: { job: 7, state: "done", result: { routed: true, pending_id: 5 } } });
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0 });
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("planning")], status: { requests: [{ id: 2, title: "Add a sale page", state: "requested", tasks: [] }], pending: [] } } } };
const frame = { el: new FakeNode("div"), main: new FakeNode("main"), sceneHost: new FakeNode("div"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), sceneUnavailable() {}, announce() {},
  acquireWorld: () => ({ show() {}, setOptions() {}, flyTo: () => Promise.resolve(false), stats() { return {}; } }), kpis: { el: new FakeNode("div") } };
const byClass = (root, name) => [...root.walk()].filter((n) => n.cls && n.cls().includes(name));
const click = (n) => (n.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {}, target: n }));
const out = {};
window.location.hash = `#/p/${P}/lobby`;
const view = createLobbyView(frame, { project: P, onChanged: async () => {} });
const update = () => view.update({ snapshot, route: router.parse(`#/p/${P}/lobby`), now: NOW, projectName: "northwind-shop" });
update();
await settle(); await settle();
const where = () => {
  const block = byClass(frame.main, "wb-request-block")[0];
  const inBlock = block ? byClass(block, "wb-lobby-notice-card").filter((n) => !n.hidden).map((n) => n.textContent) : [];
  const composer = byClass(byClass(frame.main, "wb-composer-wrap")[0], "wb-lobby-notice-card").filter((n) => !n.hidden).map((n) => n.textContent);
  return { inBlock, composer };
};
// "Create request" with a flow: the request is made, `route` is refused (scope): the notice is on the request's line
const form = byClass(frame.main, "wb-new-request")[0];
byClass(form, "wb-lobby-field")[0].value = "Add a sale page, linked from the home page.";
byClass(form, "wb-lobby-field")[1].value = "design";
(find(form, "form").listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
await new Promise((r) => setTimeout(r, 300)); await settle();
update(); await settle();
out.afterCreate = where();
out.routeButton = [...frame.main.walk()].filter((n) => n.tagName === "BUTTON" && n.textContent === "Route it").length;
// "Route it" repeats the route and, refused again, the notice stays on the line
const before = sent.filter((s) => s.url === A("/requests/2/route")).length;
click([...frame.main.walk()].find((n) => n.tagName === "BUTTON" && n.textContent === "Route it"));
await new Promise((r) => setTimeout(r, 300)); await settle();
update(); await settle();
out.routeCalls = sent.filter((s) => s.url === A("/requests/2/route")).length - before;
out.afterAgain = where();
// the configuration was accepted: the route starts and the notice goes
routeAnswer = { status: 202, body: { job: 7 } };
click([...frame.main.walk()].find((n) => n.tagName === "BUTTON" && n.textContent === "Route it"));
await new Promise((r) => setTimeout(r, 400)); await settle();
update(); await settle();
out.afterRouted = where();
view.dispose();
console.log(JSON.stringify(out));
process.exit(0);
"""


# --- A-19: the viewer's Close and Escape ----------------------------------------------------------------------------------------

FLOOR = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createFloorView } from "@JS@/views/floor.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = (type, fn) => { document.listeners[type] = (document.listeners[type] || []).filter((f) => f !== fn); };
const P = "0123456789ab";
const DOC = "docs/engineering/designs/order-history.md";
const NOW = new Date("2026-10-08T12:00:00Z");
const answers = new Map();
globalThis.fetch = async (url, init) => {
  const key = `${init.method} ${url.split("?")[0]}`;
  const answer = answers.get(key) || { status: 200, body: {} };
  return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
};
const A = (path) => `/api/v1/projects/${P}${path}`;
const review = { id: 7, kind: "review", title: "Review: order-history", body: "Two issues.", task_id: 7, agent: "engineering", status: "open", created_at: "2026-10-08T08:00:00Z", run_id: null,
  actions: ["answered", "released"], payload: { returned: [{ path: DOC, class: "document" }], kept: [], ending: "draft_with_questions", why: "w", changeset: { blocked: false } } };
answers.set(`GET ${A("/artifacts")}`, { status: 200, body: { artifacts: [{ path: DOC, owner: "eng-docs", agent: "engineering", size: 10, modified_at: "2026-10-08T09:00:00Z", bound: false }], truncated: false } });
answers.set(`GET ${A("/artifact")}`, { status: 200, body: { path: DOC, text: "# Order history", size: 10, modified_at: "2026-10-08T09:00:00Z" } });
answers.set(`GET ${A("/pending/7")}`, { status: 200, body: review });
answers.set(`GET ${A("/tasks/7")}`, { status: 200, body: { task: { id: 7 }, runs: [], pending: [review] } });
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0 });
const status = { requests: [{ id: 1, title: "Spring", state: "ready", tasks: [{ id: 7, key: "k7", title: "Review", skill: "s", state: "waiting", note: null, agent: "engineering" }] }],
  pending: [{ id: 7, kind: "review", title: review.title, task_id: 7, agent: "engineering", created_at: review.created_at, actions: review.actions }], documents: [] };
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("engineering"), agent("planning")], status } } };
const makeFrame = () => ({ el: new FakeNode("div"), main: new FakeNode("main"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), isPhone: () => false, sceneUnavailable() {}, announce() {},
  acquireWorld: () => ({ show() {}, setOptions() {}, refit() {}, stats() { return {}; } }) });
const walk = (root) => [...root.walk()];
const click = (n, errs) => { try { (n.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {}, target: n })); } catch (e) { errs.push(String(e.message)); } };
const out = {};

async function session(first) {
  const frame = makeFrame();
  const errs = [];
  window.location.hash = first;
  const view = createFloorView(frame, { refresh() {} });
  const go = async (hash) => { window.location.hash = hash; view.update({ snapshot, route: router.parse(hash), now: NOW }); await settle(); await settle(); };
  const closeButton = () => walk(frame.main).find((n) => n.attrs["data-key"] === "close");
  const rowOf = () => walk(frame.main).find((n) => n.attrs["data-path"] === DOC);
  const openLink = () => walk(frame.main).find((n) => n.tagName === "A" && n.attrs["aria-label"] === `Open ${DOC}`);
  const shown = () => { const host = walk(frame.main).find((n) => n.cls && n.cls().includes("wb-viewer-host")); return Boolean(host) && !host.hidden; };
  await go(first);
  return { frame, view, errs, go, closeButton, rowOf, openLink, shown, hash: () => window.location.hash, focused: () => document.activeElement };
}
const base = `#/p/${P}/floor/engineering`;
const docHash = `${base}/desk/${encodeURIComponent(DOC)}`;

// 1. a Desk row: Close goes back to the Desk and the focus returns to the row
let s = await session(`${base}/desk`);
click(s.rowOf(), s.errs);
await s.go(window.location.hash);
out.deskOpened = { hash: s.hash(), viewer: s.shown() };
click(s.closeButton(), s.errs);
out.deskClose = { hash: s.hash(), errors: s.errs.slice() };
await s.go(s.hash());
await new Promise((r) => setTimeout(r, 20));
out.deskFocus = { path: s.focused() && s.focused().attrs["data-path"], viewerShown: s.shown() };
s.view.dispose();

// 2. the Inbox card's "Open": Close goes back to the Inbox and the focus returns to that card's "Open"
s = await session(`${base}/inbox`);
const link = s.openLink();
out.inboxLink = link ? link.attrs.href : null;
await s.go(link.attrs.href);
click(s.closeButton(), s.errs);
out.inboxClose = { hash: s.hash(), errors: s.errs.slice() };
await s.go(s.hash());
await new Promise((r) => setTimeout(r, 20));
const again = s.openLink();
out.inboxFocus = { sameLink: Boolean(again) && s.focused() === again, focused: s.focused() ? `${s.focused().tagName} ${s.focused().attrs["aria-label"] || s.focused().attrs.class || ""}` : null, linkDrawn: Boolean(again) };
s.view.dispose();

// 3. a direct hash: Close goes to the Desk
s = await session(docHash);
click(s.closeButton(), s.errs);
out.directClose = { hash: s.hash(), errors: s.errs.slice() };
s.view.dispose();

// 3b. from a selected decision, and from the Agent tab: back to exactly there
s = await session(`${base}/inbox/7`);
await s.go(s.openLink().attrs.href);
click(s.closeButton(), s.errs);
out.selectedClose = { hash: s.hash(), errors: s.errs.slice() };
s.view.dispose();
s = await session(`${base}/agent`);
await s.go(docHash);
click(s.closeButton(), s.errs);
out.agentClose = { hash: s.hash(), errors: s.errs.slice() };
s.view.dispose();

// 4. on a phone the document is a dialog: its own close (Escape, or the dialog's cancel) goes where Close goes
window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} });
s = await session(`${base}/inbox`);
await s.go((s.openLink() || { attrs: { href: docHash } }).attrs.href);
const dialog = walk(s.frame.el).find((n) => n.tagName === "DIALOG");
out.phoneOpen = dialog.open;
dialog.open = false;
(dialog.listeners.close || []).forEach((fn) => fn({}));
out.phoneClose = s.hash();
s.view.dispose();
console.log(JSON.stringify(out));
process.exit(0);
"""


LOBBY = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createLobbyView } from "@JS@/views/lobby.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = (type, fn) => { document.listeners[type] = (document.listeners[type] || []).filter((f) => f !== fn); };
const P = "0123456789ab";
const DOC = "docs/notes/a.md";
const NOW = new Date("2026-10-08T12:00:00Z");
const answers = new Map();
globalThis.fetch = async (url, init) => {
  const key = url.includes("/conversation") ? "GET conversation" : `${init.method} ${url.split("?")[0]}`;
  const answer = answers.get(key) || { status: 200, body: {} };
  return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
};
const A = (path) => `/api/v1/projects/${P}${path}`;
const review = { id: 8, kind: "review", title: "Review: cart totals", body: "One issue.", task_id: 2, agent: null, status: "open", created_at: "2026-10-08T08:00:00Z", run_id: null,
  actions: ["answered", "released"], payload: { returned: [{ path: DOC, class: "document" }], kept: [], ending: "draft_with_questions", why: "w", changeset: { blocked: false } } };
answers.set("GET conversation", { status: 200, body: { messages: [] } });
answers.set(`GET ${A("/flows")}`, { status: 200, body: { flows: [] } });
answers.set(`GET ${A("/artifacts")}`, { status: 200, body: { artifacts: [{ path: DOC, owner: null, agent: null, size: 4, modified_at: "2026-10-08T09:00:00Z", bound: false }], truncated: false } });
answers.set(`GET ${A("/artifact")}`, { status: 200, body: { path: DOC, text: "text", size: 4, modified_at: "2026-10-08T09:00:00Z" } });
answers.set(`GET ${A("/pending/8")}`, { status: 200, body: review });
answers.set(`GET ${A("/tasks/2")}`, { status: 200, body: { task: { id: 2 }, runs: [], pending: [review] } });
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0 });
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("planning")], status: { requests: [{ id: 2, title: "Cart totals", state: "ready", tasks: [] }],
    pending: [{ id: 8, kind: "review", title: review.title, task_id: 2, agent: null, created_at: review.created_at, actions: review.actions }] } } } };
const makeFrame = () => ({ el: new FakeNode("div"), main: new FakeNode("main"), sceneHost: new FakeNode("div"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), sceneUnavailable() {}, announce() {},
  acquireWorld: () => ({ show() {}, setOptions() {}, flyTo: () => Promise.resolve(false), stats() { return {}; } }), kpis: { el: new FakeNode("div") } });
const walk = (root) => [...root.walk()];
const click = (n, errs) => { try { (n.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {}, target: n })); } catch (e) { errs.push(String(e.message)); } };
const out = {};
const base = `#/p/${P}/lobby`;
const docHash = `${base}/desk/${encodeURIComponent(DOC)}`;

async function session(first) {
  const frame = makeFrame();
  const errs = [];
  window.location.hash = first;
  const view = createLobbyView(frame, { project: P, onChanged: async () => {} });
  const go = async (hash) => { window.location.hash = hash; view.update({ snapshot, route: router.parse(hash), now: NOW, projectName: "northwind-shop" }); await settle(); await settle(); };
  const closeButton = () => walk(frame.main).find((n) => n.attrs["data-key"] === "close");
  const rowOf = () => walk(frame.main).find((n) => n.attrs["data-path"] === DOC);
  const openLink = () => walk(frame.main).find((n) => n.tagName === "A" && n.attrs["aria-label"] === `Open ${DOC}`);
  const shown = () => { const host = walk(frame.main).find((n) => n.cls && n.cls().includes("wb-viewer-host")); return Boolean(host) && !host.hidden; };
  await go(first);
  return { frame, view, errs, go, closeButton, rowOf, openLink, shown, hash: () => window.location.hash, focused: () => document.activeElement };
}

// 1. a Desk row
let s = await session(`${base}/desk`);
click(s.rowOf(), s.errs);
await s.go(window.location.hash);
click(s.closeButton(), s.errs);
out.deskClose = { hash: s.hash(), errors: s.errs.slice() };
await s.go(s.hash());
await new Promise((r) => setTimeout(r, 20));
out.deskFocus = s.focused() && s.focused().attrs["data-path"];
s.view.dispose();

// 2. the Inbox card's "Open", after a row of the Desk was opened earlier (the focus must not go to that stale row)
s = await session(`${base}/desk`);
click(s.rowOf(), s.errs);
await s.go(window.location.hash);
click(s.closeButton(), s.errs);
await s.go(`${base}/inbox`);
const link = s.openLink();
out.inboxLink = link ? link.attrs.href : null;
await s.go(link.attrs.href);
click(s.closeButton(), s.errs);
out.inboxClose = { hash: s.hash(), errors: s.errs.slice() };
await s.go(s.hash());
await new Promise((r) => setTimeout(r, 20));
const again = s.openLink();
out.inboxFocus = { sameLink: Boolean(again) && s.focused() === again, focused: s.focused() ? `${s.focused().tagName} ${s.focused().attrs["aria-label"] || s.focused().attrs.class || ""}` : null, linkDrawn: Boolean(again) };
s.view.dispose();

// 3. a direct hash
s = await session(docHash);
click(s.closeButton(), s.errs);
out.directClose = { hash: s.hash(), errors: s.errs.slice() };
s.view.dispose();

// 3b. from a selected decision, and from the Agent tab: back to exactly there
s = await session(`${base}/inbox/8`);
await s.go(s.openLink().attrs.href);
click(s.closeButton(), s.errs);
out.selectedClose = { hash: s.hash(), errors: s.errs.slice() };
s.view.dispose();
s = await session(`${base}/agent`);
await s.go(docHash);
click(s.closeButton(), s.errs);
out.agentClose = { hash: s.hash(), errors: s.errs.slice() };
s.view.dispose();

// 4. a sheet clicked in the room, from the Conversation: back to the Conversation
s = await session(base);
s.view.open(`sheet:${DOC}`);
await s.go(window.location.hash);
click(s.closeButton(), s.errs);
out.sheetClose = s.hash();
s.view.dispose();

// 5. on a phone: the dialog's own close goes back to the Inbox
window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} });
s = await session(`${base}/inbox`);
await s.go(s.openLink().attrs.href);
const dialog = walk(s.frame.el).find((n) => n.tagName === "DIALOG" && (n.attrs.class || "").includes("wb-viewer-dialog"));
out.phoneOpen = dialog.open;
dialog.open = false;
(dialog.listeners.close || []).forEach((fn) => fn({}));
out.phoneClose = s.hash();
s.view.dispose();
console.log(JSON.stringify(out));
process.exit(0);
"""


# --- the origin of an open document, as a pure module, and Escape --------------------------------------------------------------

ORIGIN = r"""
import * as origin from "@JS@/frame/origin.js";
import { escapeStep } from "@JS@/frame/escape.js";
import * as router from "@JS@/router.js";
const P = "0123456789ab";
const r = (h) => router.parse(`#/p/${P}${h}`);
const DOC = encodeURIComponent("docs/a.md");
const out = {};
const seq = (list) => { origin.reset(); const last = []; for (const h of list) { origin.track(r(h)); last.push(origin.current()); } return last; };

out.fromInbox = seq([`/floor/engineering/inbox`, `/floor/engineering/desk/${DOC}`, `/floor/engineering/desk/${DOC}`, `/floor/engineering/desk`]);
out.fromSelected = seq([`/floor/engineering/inbox/7`, `/floor/engineering/desk/${DOC}`]);
out.fromAgent = seq([`/floor/engineering/agent`, `/floor/engineering/desk/${DOC}`]);
out.fromTasks = seq([`/floor/engineering/tasks`, `/floor/engineering/desk/${DOC}`]);
out.fromFloorDefault = seq([`/floor/engineering`, `/floor/engineering/desk/${DOC}`]);
out.fromDesk = seq([`/floor/engineering/desk`, `/floor/engineering/desk/${DOC}`]);
out.direct = seq([`/floor/engineering/desk/${DOC}`]);
out.otherAgent = seq([`/floor/marketing/inbox`, `/floor/engineering/desk/${DOC}`]);
out.otherScreen = seq([`/lobby/inbox`, `/floor/engineering/desk/${DOC}`]);
out.lobbyInbox = seq([`/lobby/inbox/9`, `/lobby/desk/${DOC}`]);
out.lobbyConversation = seq([`/lobby`, `/lobby/desk/${DOC}`]);
out.cleared = seq([`/lobby/inbox`, `/lobby/desk/${DOC}`, `/lobby/inbox`, `/lobby/desk/${DOC}`]);
const at = (screen, from) => origin.closeHash(r(screen === "lobby" ? `/lobby/desk/${DOC}` : `/floor/engineering/desk/${DOC}`), from);
out.hashes = {
  floorInbox: at("floor", { tab: "inbox", pending: null }), floorSelected: at("floor", { tab: "inbox", pending: 7 }), floorAgent: at("floor", { tab: "agent", pending: null }),
  floorTasks: at("floor", { tab: "tasks", pending: null }), floorDefault: at("floor", { tab: null, pending: null }), floorNone: at("floor", null),
  lobbyInbox: at("lobby", { tab: "inbox", pending: 9 }), lobbyDesk: at("lobby", { tab: "desk", pending: null }), lobbyDefault: at("lobby", { tab: null, pending: null }), lobbyNone: at("lobby", null),
};
const doc = (screen) => r(screen === "lobby" ? `/lobby/desk/${DOC}` : `/floor/engineering/desk/${DOC}`);
out.escape = {
  floorInbox: escapeStep({ route: doc("floor"), origin: { tab: "inbox", pending: null } }), floorDefault: escapeStep({ route: doc("floor") }),
  lobbyInbox: escapeStep({ route: doc("lobby"), origin: { tab: "inbox", pending: 9 } }), dialogFirst: escapeStep({ route: doc("lobby"), origin: { tab: "inbox", pending: null }, dialog: true }),
  pendingStill: escapeStep({ route: r(`/lobby/inbox/4`), origin: null }), floorAgent: escapeStep({ route: doc("floor"), origin: { tab: "agent", pending: null } }),
};
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_documents_origin_is_the_tab_and_the_decision_of_the_route_before_it_in_the_same_room(tmp_path):
    got = run_node(tmp_path, ORIGIN)
    inbox = {"tab": "inbox", "pending": None}
    assert got["fromInbox"] == [None, inbox, inbox, None], "the origin survives a poll of the same route and goes with the document"
    assert got["fromSelected"] == [None, {"tab": "inbox", "pending": 7}], "a document opened from a selected decision remembers the decision"
    assert got["fromAgent"][-1] == {"tab": "agent", "pending": None} and got["fromTasks"][-1] == {"tab": "tasks", "pending": None}, "any tab of the room is the origin"
    assert got["fromFloorDefault"][-1] == {"tab": None, "pending": None}, "the room's default tab is an origin too"
    assert got["fromDesk"][-1] == {"tab": "desk", "pending": None} and got["direct"] == [None]
    assert got["otherAgent"] == [None, None] and got["otherScreen"] == [None, None], "a tab of another room is not this document's origin"
    assert got["lobbyInbox"][-1] == {"tab": "inbox", "pending": 9} and got["lobbyConversation"][-1] == {"tab": None, "pending": None}
    assert got["cleared"] == [None, {"tab": "inbox", "pending": None}, None, {"tab": "inbox", "pending": None}]
    p = "#/p/0123456789ab"
    assert got["hashes"] == {
        "floorInbox": f"{p}/floor/engineering/inbox", "floorSelected": f"{p}/floor/engineering/inbox/7", "floorAgent": f"{p}/floor/engineering/agent",
        "floorTasks": f"{p}/floor/engineering/tasks", "floorDefault": f"{p}/floor/engineering", "floorNone": f"{p}/floor/engineering/desk",
        "lobbyInbox": f"{p}/lobby/inbox/9", "lobbyDesk": f"{p}/lobby/desk", "lobbyDefault": f"{p}/lobby", "lobbyNone": f"{p}/lobby/desk"}


@needs_node
def test_escape_goes_where_close_goes(tmp_path):
    got = run_node(tmp_path, ORIGIN)
    p = "#/p/0123456789ab"
    assert got["escape"]["floorInbox"] == {"step": "document", "hash": f"{p}/floor/engineering/inbox"}
    assert got["escape"]["floorAgent"] == {"step": "document", "hash": f"{p}/floor/engineering/agent"}
    assert got["escape"]["floorDefault"] == {"step": "document", "hash": f"{p}/floor/engineering/desk"}
    assert got["escape"]["lobbyInbox"] == {"step": "document", "hash": f"{p}/lobby/inbox/9"}
    assert got["escape"]["dialogFirst"] == {"step": "dialog"}, "a dialog still closes first"
    assert got["escape"]["pendingStill"] == {"step": "document", "hash": f"{p}/lobby/inbox"}, "a selected decision still closes back to the Inbox list"


def test_the_frame_hands_escape_the_origin_of_the_open_document_and_no_view_has_a_close_of_its_own():
    frame = (JS / "frame" / "frame.js").read_text(encoding="utf-8")
    assert re.search(r"escapeStep\(\{[^}]*origin: ", frame, re.S), "the frame passes the origin to the one Escape handler"
    for name in ("floor.js", "lobby.js"):
        source = (JS / "views" / name).read_text(encoding="utf-8")
        assert "origin.track(" in source or "track(route" in source, f"{name} tells the origin module every route it shows"
    floor = (JS / "views" / "floor.js").read_text(encoding="utf-8")
    assert "closeViewer" not in floor or re.search(r"(function|const) closeViewer\b", floor), "a function that is called is defined"


# --- a card that a later draw moves keeps the focus it had (A-19: the focus goes back to the "Open" link, and stays) ---------------------

FOCUS = r"""
import { FakeNode, settle } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createInbox } from "@JS@/floor/inbox.js";

// A browser drops the focus of an element that is removed from the page or moved, even when it is put back: the fake document does the same.
const dropsFocus = (node) => { const a = document.activeElement; if (a && a !== document && node.contains && node.contains(a)) document.activeElement = null; };
const append = FakeNode.prototype.append;
FakeNode.prototype.append = function (...items) { for (const it of items) if (it && it.parent) dropsFocus(it); return append.apply(this, items); };
const replace = FakeNode.prototype.replaceChildren;
FakeNode.prototype.replaceChildren = function (...items) { for (const c of this.children) dropsFocus(c); return replace.apply(this, items); };

setToken("t".repeat(40));
const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const item = (id, title, files) => ({ id, kind: "review", title, body: "Text.", task_id: 7, agent: "engineering", status: "open", created_at: "2026-10-08T08:00:00Z", run_id: null, actions: ["answered", "released"],
  payload: { returned: files.map((path) => ({ path, class: "document" })), kept: [], ending: "draft_with_questions", why: "w", changeset: { blocked: false } } });
const items = { 7: item(7, "First review", ["docs/a.md"]), 9: item(9, "Second review", ["docs/b.md"]) };
const delays = { 7: 5, 9: 120 };
globalThis.fetch = async (url) => {
  const id = Number(url.split("/pending/")[1]);
  await new Promise((r) => setTimeout(r, delays[id]));
  return { ok: true, status: 200, json: async () => items[id] };
};
const root = new FakeNode("div");
const inbox = createInbox({ project: P, now: () => NOW, api: {}, refresh() {}, links: { open: (it, path) => `#/open/${path}`, floor: () => "#/f", lobby: () => "#/l", parent: () => "#/" } });
root.append(inbox.el);
inbox.focusOpen("docs/a.md");
inbox.update({ decisions: [{ id: 7 }, { id: 9 }], requests: [], resolved: [], selected: null, loading: false });
const links = () => [...root.walk()].filter((n) => n.tagName === "A" && (n.attrs["aria-label"] || "").startsWith("Open "));
const out = {};
await new Promise((r) => setTimeout(r, 60));
out.afterFirstCard = { links: links().map((n) => n.attrs["aria-label"]), focusOnA: document.activeElement === links()[0] };
await new Promise((r) => setTimeout(r, 200));
out.afterSecondCard = { links: links().map((n) => n.attrs["aria-label"]), focusOnA: document.activeElement === links().find((n) => n.attrs["aria-label"] === "Open docs/a.md") };
console.log(JSON.stringify(out));
process.exit(0);
"""

