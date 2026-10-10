"""Tests of round 4's frame and token prompt (R4-A1; rulings R-1 to R-15 of the plan folder's design/04-round-4-rulings.md): the top row of floating
controls, the two KPI cards, Back and the crumbs docked with the tracking bar, "Waiting for you" as a card on every screen, the phone's two-row bottom
bar, the soft error notice, the colour-mode button and the token prompt as a technical sheet with its owl. No browser and no model: the modules run
under Node with a fake document, as the other interface tests do; the served page was looked at in the browser pane by the package's report
(`reports/r4/R4-A1.md` of the plan folder).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_frame.py
"""
from __future__ import annotations

import json
import re

import standin_tree as st
from test_interface_adj_b1 import run_scene_dom
from test_interface_floor import INTERFACE, needs_node
from test_interface_plates_meters import run_node
from interface_css import interface_css

JS = INTERFACE / "js"
CSS = interface_css()

# --- the frame's regions ---------------------------------------------------------------------------------------------------------------

FRAME = r"""
import { FakeNode } from "@FAKE@";
import * as router from "@JS@/router.js";

document.querySelector = () => null;
const walkAll = (root) => [...root.walk()];
const kids = (n) => n.children.filter((c) => c instanceof FakeNode);
const cls = (n) => n.cls();
const byClass = (root, c) => walkAll(root).filter((n) => cls(n).includes(c));
const first = (root, c) => byClass(root, c)[0] || null;
const click = (n) => (n.listeners.click || []).forEach((fn) => fn({ target: n, preventDefault() {}, stopPropagation() {} }));
const press = (key) => (document.listeners.keydown || []).forEach((fn) => fn({ key, defaultPrevented: false, preventDefault() {} }));
const a = "aaaaaaaaaaaa";

async function build(phone, withPanel = true) {
  window.matchMedia = () => ({ matches: phone, addEventListener() {}, removeEventListener() {} });
  const { createFrame } = await import("@JS@/frame/frame.js?" + (phone ? "phone" : "desk") + (withPanel ? "p" : "n"));
  const root = new FakeNode("div");
  const calls = [];
  const el = new FakeNode("div");
  let open = false;
  const panel = { el, openAdd: () => { open = true; calls.push(["add"]); }, openLeave: (id) => { open = true; calls.push(["leave", id]); }, close: () => { open = false; calls.push(["close"]); }, isOpen: () => open, setProjects: (l) => calls.push(["projects", l.length]) };
  const frame = createFrame(root, { onSelectProject() {}, onForgetToken() {}, onRetry() {}, ...(withPanel ? { projectsPanel: panel } : {}) });
  return { frame, root, panel, calls };
}

const out = {};
const desk = await build(false);
const f = desk.frame;
out.children = kids(f.el).map((c) => cls(c)[0] || c.tagName);
out.noOldParts = [byClass(f.el, "wb-actions").length, byClass(f.el, "wb-header").length, byClass(f.el, "wb-wait-menu").length];
const top = first(f.el, "wb-topbar");
out.top = { tag: top.tagName, kids: kids(top).map((c) => cls(c)[0]), end: kids(first(top, "wb-topbar-end")).map((c) => cls(c).find((x) => ["wb-switcher", "wb-mode-btn", "wb-door"].includes(x))) };
const brand = first(top, "wb-brand");
out.brand = { mark: [first(brand, "wb-mark").attrs.width, first(brand, "wb-mark").attrs.alt], word: first(brand, "wb-wordmark").textContent, hidden: first(brand, "wb-wordmark").attrs["aria-hidden"] };
const dock = first(f.el, "wb-dock");
out.dock = kids(dock).map((c) => cls(c).includes("wb-navdock") ? "navdock:" + kids(first(c, "wb-nav")).map((x) => cls(x).find((y) => ["wb-back", "wb-crumb-nav"].includes(y))).join(",") : cls(c).includes("wb-track") ? "track" : cls(c)[0]);
out.kpis = { cards: byClass(first(f.el, "wb-kpis"), "wb-kpi").length, inScene: kids(first(f.el, "wb-scene-area")).some((c) => cls(c).includes("wb-kpis")) };
const bar = first(f.el, "wb-bottom-bar");
out.bar = kids(bar).map((row) => kids(row).map((c) => cls(c)[0]));
out.mode = { label: first(f.el, "wb-mode-btn").attrs["aria-label"], choice: first(f.el, "wb-mode-btn").attrs["data-choice"], icons: byClass(first(f.el, "wb-mode-btn"), "wb-mode-icon").length };

// the card: open on the City, closed on its header line on a project's screens, seated by the frame
f.setScreen(router.parse("#/city"), { projectName: "northwind-shop", projectId: a });
f.waitingCard.set([{ kind: "Question", title: "Who is it for?", where: "northwind-shop · Brand", age: "2 d", link: "#/x", name: "q" }], "ready");
out.cardCity = { collapsible: cls(f.waitingCard.el).includes("is-collapsible"), toggle: byClass(f.waitingCard.el, "wb-wait-toggle").length, rows: byClass(f.waitingCard.el, "wb-wait-row").length, id: f.waitingCard.el.attrs.id, order: byClass(f.waitingCard.el, "wb-wait-order").length };
f.dockWaiting();
out.dockedOnCity = f.waitingCard.el.parent === f.main;
f.setScreen(router.parse(`#/p/${a}`), { projectName: "northwind-shop", projectId: a });
f.dockWaiting();
out.cardProject = { parent: f.waitingCard.el.parent === f.main, collapsed: cls(f.waitingCard.el).includes("is-collapsed"), rows: byClass(f.waitingCard.el, "wb-wait-row").length, id: f.waitingCard.el.attrs.id || null,
  expanded: first(f.waitingCard.el, "wb-wait-toggle").attrs["aria-expanded"], chevron: cls(first(f.waitingCard.el, "wb-wait-up").children[0]).find((x) => x.startsWith("wb-icon-")), open: f.waitingCard.isOpen() };
click(first(f.waitingCard.el, "wb-wait-toggle"));
out.cardOpened = { open: f.waitingCard.isOpen(), collapsed: cls(f.waitingCard.el).includes("is-collapsed"), rows: byClass(f.waitingCard.el, "wb-wait-row").length,
  expanded: first(f.waitingCard.el, "wb-wait-toggle").attrs["aria-expanded"], chevron: cls(first(f.waitingCard.el, "wb-wait-up").children[0]).find((x) => x.startsWith("wb-icon-")),
  row: byClass(f.waitingCard.el, "wb-wait-row")[0].children.map((c) => cls(c)[0]) };
press("Escape");
out.afterEscape = { open: f.waitingCard.isOpen(), hash: window.location.hash };
click(first(f.waitingCard.el, "wb-wait-toggle"));
f.setScreen(router.parse(`#/p/${a}/lobby`), { projectName: "northwind-shop", projectId: a });
out.afterRoute = f.waitingCard.isOpen();
f.setScreen(router.parse("#/city"), { projectName: "northwind-shop", projectId: a });
out.backOnCity = { open: f.waitingCard.isOpen(), collapsible: cls(f.waitingCard.el).includes("is-collapsible"), id: f.waitingCard.el.attrs.id };

// the notice: an error is the library's soft style in the error colour; an information band is not
f.notice({ kind: "error", text: "The service could not be reached.", retry: true });
const err = first(f.el, "wb-notice");
out.noticeError = { cls: cls(err), role: err.attrs.role };
f.notice({ kind: "info", text: "Loading" });
out.noticeInfo = { cls: cls(first(f.el, "wb-notice")), role: first(f.el, "wb-notice").attrs.role };

// the switcher's foot opens the command panel the page handed over
out.panel = { classes: cls(desk.panel.el), role: desk.panel.el.attrs.role, label: desk.panel.el.attrs["aria-label"], inFrame: desk.panel.el.parent === f.el };
f.setScreen(router.parse(`#/p/${a}`), { projectName: "northwind-shop", projectId: a });
f.switcher.update({ projects: [{ id: a, name: "northwind-shop", accepted: true, badge: 0, sub: "" }], selectedId: a, heading: "Projects" });
click(first(f.switcher.el, "wb-add-row"));
click(first(f.switcher.el, "wb-leave-row"));
f.setProjects([{ id: a, name: "northwind-shop", folder: "/p" }]);
out.panelCalls = desk.calls.filter((c) => c[0] !== "close");          // a change of screen closes the panel too
desk.panel.close(); desk.calls.length = 0;
const nodePanel = await build(false, false);
click(first(nodePanel.frame.switcher.el, "wb-add-row"));
out.noPanel = [nodePanel.calls.length, "no handler: the rows do nothing and nothing throws"];
f.destroy();

// the phone: the tracking bar and the two KPI tiles float at the top; the bottom bar holds the controls in two rows
const phone = await build(true);
const p = phone.frame;
const floatOf = first(p.main, "wb-float");
out.phone = {
  float: kids(floatOf).map((c) => cls(c).join(" ")),
  top: kids(first(p.el, "wb-topbar-end")).length,
  rows: kids(first(p.el, "wb-bottom-bar")).map((row) => kids(row).map((c) => cls(c).find((x) => ["wb-switcher", "wb-wait-menu-wrap", "wb-mode-btn", "wb-nav", "wb-door"].includes(x)))),
  dock: kids(first(p.el, "wb-dock")).map((c) => cls(c)[0] + ":" + kids(c).length),
};
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_frame_has_the_top_row_the_dock_the_two_cards_the_bottom_bar_and_the_waiting_card_of_round_4(tmp_path):
    got = run_scene_dom(tmp_path, FRAME)
    assert got["top"] == {"tag": "HEADER", "kids": ["wb-brand", "wb-topbar-end"], "end": ["wb-switcher", "wb-mode-btn", "wb-door"]}, "R-1: the brand at the left; the switcher, the colour-mode button, the door at the right, in this order"
    assert got["noOldParts"] == [0, 0, 0], "the old header, the actions and the header button's menu are gone"
    assert got["brand"] == {"mark": ["28", "openhora"], "word": "openhora", "hidden": "true"}
    assert got["dock"] == ["navdock:wb-back,wb-crumb-nav", "track"], "R-2, R-8: Back and the crumbs above the tracking bar, in one dock"
    assert got["kpis"] == {"cards": 2, "inScene": True}, "R-5: two cards in the scene area"
    assert got["bar"] == [["wb-wait-menu-wrap"], []], "off a phone the bottom bar holds only the inbox button (hidden by the stylesheet) and an empty second row"
    assert got["mode"] == {"label": "Colour mode: System", "choice": "system", "icons": 3}, "R-4: one button, System first, three icons of which the stylesheet shows the chosen one"
    assert got["children"] == ["wb-skip", "wb-skip", "wb-sr", "wb-topbar", "wb-scene-area", "wb-main", "wb-dock", "wb-bottom-bar", "pui-modal", "pui-card"], "the frame's parts in their order; the command panel (a pui-card) is the last"
    city = got["cardCity"]
    assert city == {"collapsible": False, "toggle": 0, "rows": 1, "id": "wb-panel", "order": 0}, "R-7: open on the City, no toggle, no \"oldest first\" caption, and the City's card is the panel the skip link names"
    assert got["dockedOnCity"] is False, "the City's view seats its own card; the frame docks it only off the City"
    project = got["cardProject"]
    assert project == {"parent": True, "collapsed": True, "rows": 0, "id": None, "expanded": "false", "chevron": "wb-icon-chevron-up", "open": False}, \
        "R-7: on a project's screen the card is closed on its header line, with a chevron up (it opens upward), and the panel keeps its id"
    opened = got["cardOpened"]
    assert opened["open"] is True and opened["collapsed"] is False and opened["rows"] == 1 and opened["expanded"] == "true" and opened["chevron"] == "wb-icon-chevron-down"
    assert opened["row"] == ["pui-badge", "wb-wait-title", "wb-wait-where", "wb-wait-age", "wb-wait-chev"], "R-7: the row is the title with the kind badge after it, the place under it, the age and a chevron"
    assert got["afterEscape"]["open"] is False, "Escape closes the open card first"
    assert got["afterRoute"] is False, "a change of screen closes it"
    assert got["backOnCity"] == {"open": False, "collapsible": False, "id": "wb-panel"}
    assert got["noticeError"] == {"cls": ["wb-notice", "is-error", "pui-soft", "pui-error"], "role": "alert"}, "R-11: an error is the library's soft style in the error colour"
    assert got["noticeInfo"] == {"cls": ["wb-notice"], "role": "status"}
    assert got["panel"] == {"classes": ["pui-card", "wb-cmd-panel"], "role": "region", "label": "Add or leave a project", "inFrame": True}
    assert got["panelCalls"] == [["add"], ["leave", "aaaaaaaaaaaa"], ["projects", 1]], "A-35: Add and Leave open the command panel, Leave on the project the switcher shows; the frame hands it the projects"
    assert got["noPanel"][0] == 0
    phone = got["phone"]
    assert phone["float"] == ["pui-card wb-track", "wb-kpis"], "R-10: the tracking bar and the two KPI tiles float at the top of the scene"
    assert phone["top"] == 0 and phone["dock"] == ["wb-navdock:0"], "a phone's top row and dock are empty (the stylesheet does not draw them): the controls moved to the bottom bar"
    assert phone["rows"] == [["wb-switcher", "wb-wait-menu-wrap", "wb-mode-btn"], ["wb-nav", "wb-door"]], "R-10: the switcher, the inbox button, the colour mode; then Back with the crumbs, and the door"


# --- the tracking bar: the badge, no state word, how long ----------------------------------------------------------------------------

TRACK = r"""
import { FakeNode, find, all } from "@FAKE@";
import * as model from "@JS@/model.js";
import * as format from "@JS@/format.js";
import { createTrack } from "@JS@/frame/track.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const P = "0123456789ab";
const task = (id, key, state, agent, extra = {}) => ({ id, key, title: key, skill: "s", state, agent, ...extra });
const snapshot = {
  projects: [{ id: P, name: "northwind-shop", config: { accepted: true }, running_task: 4 }], loaded: true,
  details: { [P]: { agents: [{ name: "planning" }, { name: "brand" }, { name: "engineering" }], status: { pending: [], requests: [{ id: 7, title: "Spring sale page", state: "ready", tasks: [
    task(2, "voice", "done", "brand"), task(3, "draft", "waiting", "planning"), task(4, "build", "running", "engineering"), task(5, "post", "planned", "engineering", { waiting_for: [{ task_id: 4, request_id: null, reason: "waiting for #4: docs/x.md" }] })] }] } } },
  tasks: { [`${P}:4`]: { task: { id: 4 }, runs: [{ started_at: "2026-10-08T11:48:00Z" }], pending: [] } },
};
const out = {};
const t = model.tracking(snapshot, P, NOW);
out.steps = t.steps.map((s) => s.sub);
out.names = t.steps.map((s) => s.name);
out.now = t.now;
out.runningFor = [format.runningFor("2026-10-08T11:48:00Z", NOW), format.runningFor("2026-10-08T11:59:30Z", NOW), format.runningFor("2026-10-08T07:00:00Z", NOW), format.runningFor("2026-10-06T07:00:00Z", NOW), format.runningFor("", NOW), format.runningFor(undefined, NOW)];

const track = createTrack({ onOpenSteps() {}, onSelectRequest() {} });
track.set(t, "ready");
const text = (n) => (n ? n.textContent : null);
out.badge = [find(track.el, ".wb-track-project").cls(), text(find(track.el, ".wb-track-project"))];
out.stepSubs = all(track.el, ".wb-step-sub").map(text).slice(0, 4);
out.nowCard = [text(find(track.el, ".wb-now-where")), text(find(track.el, ".wb-now-sub"))];
out.phoneLine = text(find(track.el, ".wb-track-now-text"));
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_tracking_bar_shows_the_project_as_a_badge_steps_without_state_words_and_how_long_the_task_ran(tmp_path):
    got = run_node(tmp_path, TRACK)
    assert got["steps"] == ["Brand", "Lobby", "Engineering", "Engineering · waiting for #4"], "R-8: a step's line is its agent (and what it waits for): no state word"
    assert got["names"][2] == "build, Engineering, running", "the name a screen reader reads keeps the state"
    assert got["now"]["sub"] == "task #4 · for 12 min" and got["now"]["state"] == "Running", "R-8: how long the task has run, not since when"
    assert got["runningFor"] == ["for 12 min", "for under a minute", "for 5 h", "for 2 d", "", ""]
    assert got["badge"][0] == ["pui-badge", "pui-muted", "pui-soft", "wb-track-project"] and got["badge"][1] == "northwind-shop", "R-8: the followed project is a badge after the title"
    assert got["stepSubs"] == ["Brand", "Lobby", "Engineering", "Engineering · waiting for #4"]
    assert got["nowCard"] == ["Now on floor 2 · engineering", "task #4 · for 12 min"]
    assert "running" not in got["phoneLine"].lower() and "floor 2 · engineering" in got["phoneLine"], "R-8, R-10: the phone's line has no state word either"


# --- the token prompt -------------------------------------------------------------------------------------------------------------------

PROMPT = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { showTokenPrompt } from "@JS@/views/token-prompt.js";
import { createOwl } from "@JS@/views/token-owl.js";

const COMMANDS = { macos: "pbcopy < '/x/service.token'", linux: "cat '/x/service.token'", powershell: "Get-Content -LiteralPath '/x/service.token' | Set-Clipboard" };
const out = {};
const text = (n) => (n ? n.textContent : null);
const cls = (n) => (n ? n.cls() : null);
async function draw(tokenFile, extra = {}) {
  const root = new FakeNode("div");
  const view = showTokenPrompt(root, { message: null, onSubmit: async () => {}, platform: "MacIntel", tokenFile, copyEnv: { clipboard: { writeText: async () => {} }, select: () => false, later: () => {} }, ...extra });
  await settle();
  return { root, view };
}
const withPath = await draw(async () => ({ token_file: "/x", commands: COMMANDS }));
const r = withPath.root;
out.structure = {
  ground: [find(r, "svg.tk-grid") ? "svg" : null, all(r, "pattern").length, all(r, "circle").length > 0],
  frame: cls(find(r, ".tk-frame")), bar: [cls(find(r, ".tk-bar .wb-brand")), text(find(r, ".tk-meta")), find(r, ".tk-bar .wb-mode-btn") ? "mode button" : null],
  mark: [find(r, ".tk-bar img.wb-mark").attrs.width, find(r, ".tk-bar img.wb-mark").attrs.alt], word: text(find(r, ".tk-bar .wb-wordmark")),
  crosses: all(r, ".tk-cross").map((n) => n.cls()[1]), eyebrow: text(find(r, ".tk-eyebrow")), title: [find(r, "h1.tk-title").tagName, text(find(r, "h1.tk-title"))],
  side: all(r, "aside.tk-side svg.wb-owl").length, steps: all(r, ".tk-step").map((n) => [text(find(n, ".tk-num")), text(find(n, ".tk-cap"))]), two: cls(find(r, "footer.tk-steps")),
};
out.stepOne = { head: [text(find(r, ".tk-cmd-head .wb-token-label")), text(find(r, ".tk-cmd-head .wb-token-system"))], code: text(find(r, ".wb-command-code")), copy: [text(find(r, "button.wb-copy")), find(r, "button.wb-copy .wb-icon-copy") ? "icon" : null, find(r, "button.wb-copy").attrs["aria-label"]],
  help: text(find(r, ".wb-token-help")), how: cls(find(r, ".wb-token-how")) };
out.stepTwo = { label: [find(r, "label[for=token-field]").cls(), text(find(r, "label[for=token-field] span"))], field: [find(r, "#token-field").cls(), find(r, "#token-field").attrs.autocomplete], button: [text(find(r, "button[type=submit]")), cls(find(r, "button[type=submit]"))], help: text(find(r, "#token-help")), within: cls(find(r, ".tk-field")) };

// no path: the sentence and the three steps stand in
const noPath = await draw(async () => ({ token_file: null, commands: null }));
out.noPath = { how: cls(find(noPath.root, ".wb-token-how")), text: [cls(find(noPath.root, ".wb-token-how p")), text(find(noPath.root, ".wb-token-how p"))], label: text(find(noPath.root, "label[for=token-field] span")),
  steps: all(noPath.root, ".tk-step").map((n) => [text(find(n, ".tk-num")), text(find(n, ".tk-cap"))]), two: cls(find(noPath.root, "footer.tk-steps")), commandBlock: find(noPath.root, ".wb-command-block") ? "yes" : null };

// the refusals: the 401 message and the inline problem are the soft error style
const refused = new FakeNode("div");
showTokenPrompt(refused, { message: "The token was not accepted.", onSubmit: async () => {}, platform: "MacIntel" });
out.message = [cls(find(refused, "p.notice")), find(refused, "p.notice").attrs.role, text(find(refused, "p.notice"))];
const problem = find(refused, "form p.notice");
out.problem = [cls(problem), problem.attrs.role, problem.hidden];
const form = find(refused, "form");
find(refused, "#token-field").value = "short";
for (const fn of form.listeners.submit || []) await fn({ preventDefault() {} });
out.problemShown = [problem.hidden, text(problem)];

// the owl: the mark's drawing inline, eyes that can move, hidden from a screen reader, one clip path per eye with ids that never repeat
const owl = createOwl(168);
const other = createOwl(64);
out.owl = { tag: owl.tagName, cls: cls(owl), size: [owl.attrs.width, owl.attrs.height], viewBox: owl.attrs.viewBox, hidden: owl.attrs["aria-hidden"],
  moving: ["owl-pupil", "owl-lid", "owl-lidline"].map((c) => [...owl.walk()].filter((n) => n.cls && n.cls().includes(c)).length),
  clips: [...owl.walk()].filter((n) => n.tagName === "CLIPPATH").map((n) => n.attrs.id), others: [...other.walk()].filter((n) => n.tagName === "CLIPPATH").map((n) => n.attrs.id),
  forbidden: [...owl.walk()].flatMap((n) => Object.keys(n.attrs)).filter((k) => k === "style" || /^on/.test(k) || k === "href"),
  fills: [...new Set([...owl.walk()].flatMap((n) => [n.attrs.fill, n.attrs.stroke]).filter((v) => v && !v.startsWith("url") && v !== "none"))].sort() };
// text from the service is text
const hostile = await draw(async () => ({ token_file: "/x", commands: { macos: "pbcopy < '/x/<b>y</b>'" } }));
out.hostile = [text(find(hostile.root, ".wb-command-code")), all(hostile.root, "b").length];
withPath.view.destroy();
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_token_prompt_is_a_technical_sheet_with_two_steps_the_refusals_in_the_soft_style_and_the_owl_at_the_right(tmp_path):
    got = run_node(tmp_path, PROMPT)
    s = got["structure"]
    assert s["ground"] == ["svg", 1, True], "R-13: a ground of dots (a pattern; its colour is the stylesheet's)"
    assert s["frame"] == ["tk-frame"] and s["bar"] == [["wb-brand"], "local service · 127.0.0.1", "mode button"], "R-13: a bar with the mark, the wordmark, the local service and the colour-mode button"
    assert s["mark"] == ["24", ""] and s["word"] == "openhora", "the mark has no alt: the wordmark beside it names it"
    assert s["crosses"] == ["tk-tl", "tk-tr", "tk-bl", "tk-br"], "small crosses at the corners of the body"
    assert s["eyebrow"] == "01 · service token" and s["title"] == ["H1", "Paste the openhora service token"]
    assert s["side"] == 1, "R-15: the owl at the right of the form"
    assert s["steps"] == [["01", "copy the command, run it in a terminal"], ["02", "paste the token here"]] and "is-two" in s["two"], "R-13: numbered steps along the foot"
    one = got["stepOne"]
    assert one["head"] == ["1 · Run this in a terminal", "macOS"] and one["code"] == "pbcopy < '/x/service.token'", "R-14, R4D-4: the command as the service sent it, whole"
    assert one["copy"] == ["Copy", "icon", "Copy the command"] and one["how"] == ["wb-token-how", "tk-cmd"]
    assert one["help"] == "It copies the token to the clipboard. The token itself is never shown on this page."
    two = got["stepTwo"]
    assert two["label"] == [["tk-label"], "2 · Paste the token"] and two["field"][1] == "off" and "wb-token-field" in two["field"][0], "step 2 is the field"
    assert two["button"] == ["Continue", ["pui-btn", "pui-solid", "pui-theme"]] and two["within"] == ["tk-field"] and two["help"].startswith("It is kept in this browser tab")
    nopath = got["noPath"]
    assert nopath["how"] == ["wb-token-how"] and nopath["text"][0] == ["tk-text"] and nopath["text"][1].startswith("The token is in the file whose path the service printed"), "no path: the sentence about token_file stands in"
    assert nopath["label"] == "Access token" and nopath["commandBlock"] is None
    assert nopath["steps"] == [["01", "the service prints token_file"], ["02", "open that file"], ["03", "paste its one line"]] and "is-two" not in nopath["two"], "and the three steps"
    assert got["message"] == [["notice", "pui-soft", "pui-error"], "alert", "The token was not accepted."], "R-11: the 401 message is the soft error style"
    assert got["problem"] == [["notice", "pui-soft", "pui-error"], "alert", True] and got["problemShown"][0] is False and got["problemShown"][1].startswith("That does not look like the token")
    owl = got["owl"]
    assert owl["tag"] == "SVG" and owl["cls"] == ["wb-owl"] and owl["size"] == ["168", "168"] and owl["viewBox"] == "0 0 200 200" and owl["hidden"] == "true"
    assert owl["moving"] == [2, 2, 2], "R-15: both pupils, both lids and both lid lines are the parts the stylesheet moves"
    assert len(owl["clips"]) == 2 and len(set(owl["clips"] + owl["others"])) == 4, "one clip path for each eye, ids that never repeat"
    assert owl["forbidden"] == [], "no style, event or link attribute on the drawing"
    assert owl["fills"] == ["#1E1B2E", "#6B4429", "#A47551", "#E6D2BC", "#FCD34D", "#FFFFFF"], "the mark's own fixed palette, in the owl module and nowhere else"
    assert got["hostile"] == ["pbcopy < '/x/<b>y</b>'", 0]


# --- the stylesheet --------------------------------------------------------------------------------------------------------------------------

def top_level(css: str) -> str:
    """The stylesheet with its comments and its @media blocks taken out: what holds above every width."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = [], 0
    while i < len(css):
        at = css.find("@media", i)
        if at < 0:
            out.append(css[i:])
            break
        out.append(css[i:at])
        depth, j = 0, css.index("{", at)
        while j < len(css):
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
            if depth == 0:
                break
        i = j
    return "".join(out)


def rules_of(css: str) -> dict:
    out = {}
    for selector, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        out.setdefault(" ".join(selector.split()), {}).update({k.strip(): v.strip() for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);?", body)})
    return out


def test_the_stylesheet_has_the_rounds_tokens_and_the_frames_places():
    root = re.search(r"^:root \{\n(.*?)^\}", CSS, re.S | re.M).group(1)
    for token, value in (("--pui-radius", "0.625rem"), ("--wb-kpi-w", "208px"), ("--wb-kpi-top", "72px"), ("--wb-bar-h", "56px"), ("--wb-panel-narrow", "380px"), ("--wb-wait-w", "380px")):
        assert re.search(rf"{re.escape(token)}: {re.escape(value)};", root), f"R-1 to R-12: {token} is {value}"
    top = rules_of(top_level(CSS))
    bar = top[".wb-topbar"]
    assert bar["position"] == "absolute" and bar["height"] == "var(--wb-bar-h)" and bar["pointer-events"] == "none", "R-1: a top row 56 px high that takes no pointer where it holds no control"
    assert top[".wb-topbar .wb-brand"]["box-shadow"] == "var(--wb-elev)", "R-1: the brand is a raised box of its own, no strip behind"
    assert "background-color" not in bar and "border-bottom" not in bar
    assert top[".wb-dock"]["position"] == "absolute" and top[".wb-dock"]["bottom"] == "var(--wb-edge)", "R-2, R-8: Back, the crumbs and the tracking bar at the bottom left"
    assert top[".wb-waiting"]["right"] == "var(--wb-edge)" and top[".wb-waiting"]["bottom"] == "var(--wb-edge)" and top[".wb-waiting"]["width"] == "var(--wb-wait-w)", "R-7: the card at the bottom right, 380 px"
    assert top[".wb-camera-tools"]["flex-direction"] == "column" and "--wb-cam-top" in top[".wb-camera-tools"]["top"], "R-9: the camera buttons are a column under the KPI cards"
    panel = top[".wb-panel"]
    assert panel["bottom"] == "calc(var(--wb-edge) + var(--wb-wait-closed))" and panel["top"] == "var(--wb-kpi-top)", "R-27: a project's panel runs from under the top row to the closed card"
    assert top[".wb-wait-btn"]["display"] == "none", "R-7: the inbox button is the phone's"
    assert top[".wb-notice.is-error.pui-soft"]["border-color"] == "transparent" and "var(--wb-raised)" in top[".wb-notice.is-error.pui-soft"]["background-color"], \
        "R-11: the band's tint is mixed into the raised surface, so the drawing does not show through"
    assert top[".notice.pui-soft"]["border-color"] == "transparent", "R-11: a notice is the soft style, no line round it"
    assert ".notice.error" not in top and ".wb-notice.is-error" not in top, "the bordered error card is gone"
    for selector in (".wb-tab.is-selected, .wb-tab.pui-btn.is-selected", ".wb-tabs, .wb-tablist"):
        assert selector in top, f"R-33, R-43: the segmented control: {selector}"


def test_the_token_prompt_is_drawn_by_the_stylesheet_with_tokens_the_owls_cycle_is_8_seconds_and_reduced_motion_stills_it():
    top = rules_of(top_level(CSS))
    assert top[".tk-frame"]["width"] == "min(1040px, 100%)" and top[".tk-frame"]["border-inline"] == "1px solid var(--pui-border)", "R-13: a frame 1040 px wide with a line at each side"
    assert top[".tk-title"]["font-size"] == "52px", "R-13: the title at 52 px"
    assert "28%" in top[".tk-grid"]["fill"] and "20%" in top[".tk-grid"]["fill"] and "var(--pui-text)" in top[".tk-grid"]["fill"] and "light-dark(" in top[".tk-grid"]["fill"], \
        "R-13: the dots are the text colour at 28 percent in light and 20 percent in dark"
    assert top[".tk-body"]["grid-template-columns"] == "minmax(0, 1fr) 360px"
    for name in (".owl-pupil", ".owl-lid", ".owl-lidline"):
        assert "8s" in top[name]["animation"] and "infinite" in top[name]["animation"], f"R-15: {name} runs on an 8 s cycle"
    reduced = re.search(r"@media \(prefers-reduced-motion: reduce\) \{ \.owl-pupil, \.owl-lid, \.owl-lidline \{ animation: none; \} \}", CSS)
    assert reduced, "R-15: under reduced motion the owl is still"
    phone = "".join(re.findall(r"@media \(max-width: 639px\) \{\n  \.tk \{.*?\n\}\n", CSS, re.S))
    assert ".tk-side .wb-owl { width: 64px; height: 64px; }" in phone and ".tk-side { order: -1;" in phone and "place-content: start center" in phone, "R-13: on a phone the owl is 64 px, centred above the title"
    assert "@keyframes owl-look" in CSS and "@keyframes owl-lid" in CSS and "@keyframes owl-line" in CSS


def test_the_owls_palette_is_the_marks_and_lives_in_its_module_alone():
    owl = (JS / "views" / "token-owl.js").read_text(encoding="utf-8")
    assert sorted(set(re.findall(r'"(#[0-9A-Fa-f]{6})"', owl))) == ["#1E1B2E", "#6B4429", "#A47551", "#E6D2BC", "#FCD34D", "#FFFFFF"]
    for path in sorted(JS.rglob("*.js")):
        if path.name in ("token-owl.js", "owl.js"):   # R-41: the scene's owl (scene/owl.js, R4-B1) is the second module that names the mark's palette
            continue
        assert not re.search(r"#1E1B2E|#A47551|#FCD34D|#E6D2BC", path.read_text(encoding="utf-8"), re.I), f"{path.name} holds a colour of the owl: the palette lives in the owl's module"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", CSS.replace("light-dark(#6B4429, #C99A6E)", "")), "no colour literal in the stylesheet but the brand pair"


# --- svg(): the page's own drawings are built as h() builds an element -----------------------------------------------------------------------

SVG = r"""
import "@FAKE@";
import { svg } from "@JS@/dom.js";
const out = {};
for (const name of ["onclick", "onload", "style", "href", "xlink:href"]) {
  try { svg("circle", { [name]: name === "style" ? "fill: red" : "x" }); out[name] = "built"; } catch (e) { out[name] = e.message; }
}
const text = svg("text", { text: "<b>x</b>", x: 1, hidden: true, y: null, z: false }, "a", ["b", null], undefined);
out.text = [text.tagName, text.textContent, text.attrs.x, "hidden" in text.attrs, "y" in text.attrs, "z" in text.attrs];
out.child = svg("g", {}, svg("path", { d: "M0 0" })).children[0].attrs.d;
console.log(JSON.stringify(out));
"""


@needs_node
def test_svg_refuses_an_event_a_style_and_a_link_and_assigns_text_as_text(tmp_path):
    got = run_node(tmp_path, SVG)
    for name in ("onclick", "onload", "style"):
        assert "is not allowed" in got[name], f"{name} is refused"
    for name in ("href", "xlink:href"):
        assert "links to nothing" in got[name], f"{name} is refused: a drawing of the page links to nothing"
    assert got["text"] == ["TEXT", "<b>x</b>ab", "1", True, False, False], "`text` is a text node (never markup); strings and arrays of strings are text children; null and false attributes are skipped"
    assert got["child"] == "M0 0"


# --- the cascade: a phone rule that a later rule of the stylesheet beats is a rule that never applies -------------------------------------------

def _rules(css: str):
    """Every rule of the stylesheet in file order as (media conditions, selector, declarations); a selector list is split outside its parentheses."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []

    def walk(block: str, media: tuple):
        pos = 0
        while pos < len(block):
            found = re.compile(r"\s*([^{}]+)\{").match(block, pos)
            if not found:
                break
            head, depth, i = found.group(1).strip(), 1, found.end()
            while depth:
                depth += (block[i] == "{") - (block[i] == "}")
                i += 1
            body, pos = block[found.end():i - 1], i
            if head.startswith("@media"):
                walk(body, media + (head,))
            elif not head.startswith("@"):
                decls = {k.strip(): v.strip() for k, v in re.findall(r"([\w-]+)\s*:\s*([^;]+);?", body)}
                depth, start, parts = 0, 0, []
                for n, c in enumerate(head):
                    depth += (c == "(") - (c == ")")
                    if c == "," and depth == 0:
                        parts.append(head[start:n])
                        start = n + 1
                parts.append(head[start:])
                for part in parts:
                    out.append((media, " ".join(part.split()), decls))

    walk(css, ())
    return out


def _on_phone(media: tuple) -> bool:
    for m in media:
        low, high = re.search(r"min-width:\s*(\d+)px", m), re.search(r"max-width:\s*(\d+)px", m)
        if "prefers" in m or (low and int(low.group(1)) > 375) or (high and int(high.group(1)) < 375):
            return False
    return True


def phone_value(selector: str, prop: str):
    """What the cascade gives `prop` of exactly `selector` at 375 px: the last rule of the file that names it and applies there."""
    value = None
    for media, sel, decls in _rules(CSS):
        if sel == selector and prop in decls and _on_phone(media):
            value = decls[prop]
    return value


def test_the_command_panel_is_a_fixed_full_width_sheet_on_a_phone_and_no_tab_list_keeps_a_padding_a_later_rule_replaced():
    assert phone_value(".wb-cmd-panel", "position") == "fixed", "at 375 px the command panel is fixed, not the desktop's absolute"
    assert phone_value(".wb-cmd-panel", "width") == "auto" and phone_value(".wb-cmd-panel", "top") == "auto", "full width between 8 px margins, not 420 px at the desktop's place"
    assert (phone_value(".wb-cmd-panel", "left"), phone_value(".wb-cmd-panel", "right"), phone_value(".wb-cmd-panel", "bottom")) == ("8px", "8px", "96px")
    assert phone_value(".wb-tablist", "padding") == "3px", "the segmented control's padding is the last word at 375 px too (the earlier phone padding was dead)"


def test_no_phone_rule_of_the_stylesheet_is_beaten_by_a_later_rule_of_the_same_selector():
    rules = _rules(CSS)
    beaten = []
    for n, (media, sel, decls) in enumerate(rules):
        if not any("max-width: 639px" in m for m in media):
            continue
        for prop, value in decls.items():
            for media2, sel2, decls2 in rules[n + 1:]:
                if sel2 == sel and prop in decls2 and decls2[prop] != value and _on_phone(media2) and not any("max-width: 639px" in m for m in media2):
                    beaten.append((sel, prop, value, decls2[prop]))
    assert beaten == [], f"a phone rule that a later top-level rule beats never applies: move it after that rule: {beaten}"


# --- no colour literal in a module of the page but the brand's own drawings --------------------------------------------------------------------

PALETTE_MODULES = {"token-owl.js", "owl.js"}      # the owl's fixed palette is the brand's (R-15, R-41): the prompt's owl, and the scene's (R4-B1)


def test_no_module_of_the_page_names_a_colour_but_the_owls_palette_modules():
    literal = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
    found = {}
    for path in sorted(JS.rglob("*.js")):
        if path.name in PALETTE_MODULES:
            continue
        text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
        hits = literal.findall(text)
        if hits:
            found[str(path.relative_to(INTERFACE))] = hits
    assert found == {}, f"a colour is a token, read from the stylesheet: {found}"
