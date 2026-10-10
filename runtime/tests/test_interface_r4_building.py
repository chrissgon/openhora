"""Tests of round 4's Building screen (R4-A3; rulings R-25 to R-29 of the plan folder's design/04-round-4-rulings.md, `design/screens/building.md` with its (R-n) marks, the
page `building.html`): the plate beside a floor (one size, the state as a soft badge, the two meters named `runs` and `$`, the name row alone with more than eight floors), the
panel (the project's name with Project state as an icon button, `Requests (n)` with `Cancel request`, `Documents (n)`, `Floors`), a floor marked in three places, the
work-order tag as a badge, the phone's card and the states of the page. No browser and no model: the view runs under Node with a fake document, as the other interface tests
do; the served page was looked at beside the page by the package's report (`reports/r4/R4-A3.md` of the plan folder).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_building.py
"""
from __future__ import annotations

import re

import pytest

from test_interface_floor import INTERFACE, needs_node
from test_interface_live import VIEW_HEAD
from test_interface_phone_sheet import media_blocks, rules, without_media
from test_interface_plates_meters import run_node
from interface_css import interface_css

JS = INTERFACE / "js"
CSS = interface_css()
PHONE = "\n".join(media_blocks(CSS, "max-width: 639px"))
TOP = without_media(CSS)

# --- the model: the state badge, the dot, the plate's size, the rows of "Requests (n)" -----------------------------------------------------------------

MODEL = r"""
import * as fm from "@JS@/floor-model.js";
import * as model from "@JS@/model.js";

const P = "0123456789ab";
const agent = (name, extra = {}) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 6, max_usd_per_day: 2, runs_today: 1, usd_today: 0, runs_without_cost: 0, queued: 0, ...extra });
const task = (id, state, agentName, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: agentName, ...extra });
const status = {
  requests: [
    { id: 7, title: "Spring sale page", state: "running", tasks: [task(10, "done", "planning"), task(11, "done", "brand"), task(12, "running", "engineering"), task(13, "waiting", "marketing"), task(14, "planned", "engineering")] },
    { id: 9, title: "", state: "planned", tasks: [task(20, "waiting", "brand"), task(21, "ready", "design")] },
    { id: 3, title: "Old", state: "done", tasks: [] },
    { id: 5, title: "Dropped", state: "cancelled", tasks: [] },
    { id: 11, title: "Not routed", state: "requested", tasks: [] },
  ],
  pending: [{ id: 1, kind: "question", title: "Q", task_id: 13, agent: "marketing", created_at: "2026-10-10T08:00:00Z", actions: ["answered"] },
    { id: 2, kind: "review", title: "R", task_id: 20, agent: "brand", created_at: "2026-10-10T08:00:00Z", actions: ["approved"] }],
  held: [{ task_id: 21, agent: "design", reason: "dispatch off", at: "2026-10-10T08:00:00Z", next: null }],
};
const agents = [agent("planning"), agent("business"), agent("brand"), agent("design"), agent("engineering", { runs_today: 3 }), agent("marketing", { mode: "milestones" }), agent("support", { mode: "stopped", acting_mode: "stopped" })];
const snapshot = (accepted = true, st = status) => ({ projects: [{ id: P, name: "northwind-shop", config: { accepted } }], details: { [P]: { status: st, agents } }, tasks: {}, loaded: true });
const out = {};
const view = fm.building(snapshot(), P);
const by = Object.fromEntries(view.rows.map((r) => [r.name, r]));
out.words = Object.fromEntries(view.rows.map((r) => [r.name, [r.plateWord, r.plateTone, r.plateDot]]));
out.cardWords = Object.fromEntries(view.rows.map((r) => [r.name, fm.cardOf(r).word]));
out.cardTones = Object.fromEntries(view.rows.map((r) => [r.name, fm.cardOf(r).tone]));
out.modeLines = [by.engineering.modeLine, by.marketing.modeLine, by.support.modeLine];
const plate = fm.plateOf(by.marketing);
out.plate = { word: plate.word, tone: plate.tone, modeLine: plate.modeLine, tiny: plate.tiny === undefined ? null : plate.tiny, dot: plate.dot };
out.sceneTiny = fm.buildingScene(view, null).floors.map((f) => f.plate.tiny);
const many = fm.building({ ...snapshot(), details: { [P]: { status, agents: [...agents, ...["a", "b", "c", "d"].map((n) => agent(n))] } } }, P);
out.manyTiny = [many.more, [...new Set(fm.buildingScene(many, null).floors.map((f) => f.plate.tiny))]];
// the state words of a project that is not accepted
const refused = fm.building({ ...snapshot(false), details: { [P]: { status, agents } } }, P);
out.refused = Object.fromEntries(refused.rows.slice(0, 3).map((r) => [r.name, [r.plateWord, r.plateTone, fm.cardOf(r).word, fm.cardOf(r).tone]]));
// the rows of Requests (n)
out.requests = fm.requestRows(status, P).map((r) => [r.id, r.title, r.state, r.tone, r.steps, r.selected, r.cancellable, r.link, r.name]);
model.chooseRequest(P, 9);
out.chosen = fm.requestRows(status, P).map((r) => [r.id, r.selected]);
model.resetRequestChoices();
out.none = [fm.requestRows({ requests: [] }, P), fm.requestRows(null, P)];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_state_is_a_soft_badge_working_brand_resting_muted_waiting_held_and_not_accepted_warn(tmp_path):
    got = run_node(tmp_path, MODEL)
    w = got["words"]
    assert w["engineering"] == ["working", "pui-theme", "theme"], "R-26: working in the brand colour"
    assert w["brand"] == ["waiting for you", "pui-warn", "theme"] and w["marketing"] == ["waiting for you", "pui-warn", "theme"], \
        "R-26: `waiting for you` is a state of the plate and the row, in the warn colour; the floor is lit, so its dot is the brand colour (R-21)"
    assert w["design"] == ["held: dispatch off", "pui-warn", "muted"], "R-26: held: <reason> in the warn colour"
    assert w["business"] == ["resting", "pui-muted", "muted"] and w["support"] == ["Off, mode is stopped", "pui-muted", "border"], "R-26: resting and off are muted"
    assert got["cardWords"]["engineering"] == "Running" and got["cardWords"]["brand"] == "Waiting for you" and got["cardWords"]["business"] == "Idle" and got["cardWords"]["support"] == "Off, mode is stopped", \
        "the phone's card keeps its own words (building.html at 375 px: `Running`)"
    assert got["cardTones"]["engineering"] == "pui-theme" and got["cardTones"]["brand"] == "pui-warn" and got["cardTones"]["business"] == "pui-muted"
    assert all(v[0] == "not accepted" and v[1] == "pui-warn" and v[2] == "not accepted" and v[3] == "pui-warn" for v in got["refused"].values()), "R-26: `not accepted` in the warn colour, on the plate, the row and the card"
    assert got["modeLines"] == ["Every review reaches you", "Reviews reach you at milestones, the rest are released when the skill is proven", "Off, starts nothing"], "C-5: the mode's one line is the mode word's tooltip"
    assert got["plate"] == {"word": "waiting for you", "tone": "pui-warn", "modeLine": got["modeLines"][1], "tiny": None, "dot": "theme"}


@needs_node
def test_a_plate_is_the_name_row_alone_with_more_than_eight_floors(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["sceneTiny"] == [False] * 7, "R-25: one size: the name row and the two meters"
    assert got["manyTiny"] == [3, [True]], "R-25: with more than eight floors every plate is its name row alone (eleven agents: three more than the scene draws)"


@needs_node
def test_requests_n_lists_the_open_requests_by_number_from_the_lowest_with_the_steps_line_and_the_followed_one_selected(tmp_path):
    got = run_node(tmp_path, MODEL)
    ids = [r[0] for r in got["requests"]]
    assert ids == [7, 9, 11], "the requests that are not done or cancelled, from the lowest number, as building.html lists them (the tracking bar's own list stays newest first)"
    by = {r[0]: r for r in got["requests"]}
    assert by[7][1:6] == ["Spring sale page", "Running", "pui-theme pui-soft", "2 of 5 steps done · now on Engineering", True], "R-27: the title, the state chip in the state's colour, the steps line with where it is"
    assert by[9][1:6] == ["Request 9", "Planned", "pui-muted pui-soft", "0 of 2 steps done · waiting for you", False], "a request with no title is `Request <n>`; a waiting task reads `waiting for you`"
    assert by[11][4] == "0 of 0 steps done" and by[11][2] == "Requested"
    assert all(r[6] is True for r in got["requests"]) and by[7][7] == "#/p/0123456789ab/lobby/conversation/request/7", "every open request can be cancelled; the chevron goes to its line in the Lobby"
    assert by[7][8] == "Request 7, Spring sale page, Running, 2 of 5 steps done · now on Engineering"
    assert got["chosen"] == [[7, False], [9, True], [11, False]], "the request the tracking bar shows (the person's choice) is the selected row"
    assert got["none"] == [[], []]


# --- the nodes: the plate, the row, the tag --------------------------------------------------------------------------------------------------------

NODES = r"""
import { FakeNode, find, all } from "@FAKE@";
import { plateNode, rowNode, tagNode, floorCardNode } from "@JS@/scene/plates.js";

const p = { name: "marketing", label: "Marketing", dot: "theme", decisions: 1, word: "waiting for you", tone: "pui-warn", mode: "milestones", modeLine: "Reviews reach you at milestones", actingLine: "acting as supervised",
  done: 1, running: 0, left: 1, queued: 1, waits: { text: "waiting for #10", title: "task #4 waits" }, runsText: "2 / 6", runsShare: 0.33, usdText: "$0.03 / $2.00", usdShare: 0.015,
  usdRecordedShare: 0.015, usdReservedShare: 0.25, usdNote: "$0.03 recorded · up to $0.50 reserved", usdReserved: 0.5, unknown: 0, selected: false, off: false, inUse: { runs: true, spend: true } };
const out = {};
const plate = plateNode(p);
out.plate = { tag: plate.tagName, classes: plate.cls(), floor: plate.attrs["data-floor"], parts: plate.children.map((c) => c.cls().join(" ")),
  row: find(plate, ".wb-plate-row").children.map((c) => c.cls().join(" ")), name: find(plate, ".wb-plate-name").textContent, badge: all(plate, ".pui-badge")[0].textContent,
  badgeLabel: all(plate, ".pui-badge")[0].attrs["aria-label"], mode: find(plate, ".wb-plate-mode").textContent, modeTitle: find(plate, ".wb-plate-mode").attrs.title,
  state: find(plate, ".wb-plate-state .wb-st").textContent, stateClasses: find(plate, ".wb-plate-state .wb-st").cls(), stateTitle: find(plate, ".wb-plate-state .wb-st").attrs.title,
  meters: all(plate, ".wb-plate-meter").map((m) => [m.textContent, m.attrs.title, all(m, ".wb-meter").length, all(m, ".wb-meter-reserved").length]),
  noChips: all(plate, ".wb-plate-chips").length + all(plate, ".wb-plate-note").length + all(plate, ".wb-pip").length + all(plate, ".wb-mode-plate").length };
const tiny = plateNode({ ...p, tiny: true });
out.tiny = { classes: tiny.cls(), parts: tiny.children.map((c) => c.cls().join(" ")) };
const one = plateNode({ ...p, inUse: { runs: true, spend: false } });
out.oneMeter = all(one, ".wb-plate-meter").map((m) => m.textContent);
out.off = plateNode({ ...p, off: true, word: "Off, mode is stopped", tone: "pui-muted", dot: "border", decisions: 0, mode: "stopped" }).cls();
const row = rowNode(p, { href: "#/p/x/floor/marketing", "aria-label": "Marketing, waiting for you" });
out.row = { tag: row.tagName, href: row.attrs.href, floor: row.attrs["data-floor"], parts: row.children.map((c) => c.cls().join(" ")), title: find(row, ".wb-fl-title").children.map((c) => c.cls().join(" ")),
  mode: find(row, ".wb-fl-mode").textContent, state: find(row, ".wb-fl-state .wb-st").textContent, chips: all(row, ".wb-fl-chips .pui-badge").map((c) => c.textContent),
  chev: find(row, ".wb-fl-chev .wb-icon-chevron-right") !== null, noMeters: all(row, ".wb-plate-meter").length };
const plain = rowNode({ ...p, done: 0, left: 0, queued: 0, waits: null, actingLine: "" }, { href: "#/p/x/floor/marketing" });
out.rowPlain = plain.children.map((c) => c.cls().join(" "));
const tag = tagNode({ text: "#7" });
out.tag = { tag: tag.tagName, classes: tag.cls(), text: tag.textContent, title: tag.attrs.title };
const card = floorCardNode({ name: "marketing", label: "Marketing", dot: "theme", decisions: 1, word: "Waiting for you", tone: "pui-warn", mode: "milestones", modeLine: "x", runsLine: "runs 2 / 6 · spend $0.03 / $2.00", off: false });
out.card = [card.textContent, find(card, ".wb-fc-runs").textContent];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_plate_is_one_size_the_name_row_and_two_meters_side_by_side_with_the_state_as_a_badge(tmp_path):
    got = run_node(tmp_path, NODES)
    p = got["plate"]
    assert p["tag"] == "DIV" and "wb-plate" in p["classes"] and p["floor"] == "marketing" and p["parts"] == ["wb-plate-row", "wb-plate-meters"], "R-25: the name row and the meters"
    assert p["row"] == ["wb-dot is-theme", "wb-plate-name", "pui-badge pui-warn pui-soft pui-rounded-full", "wb-plate-mode", "wb-plate-state"], "R-25: the state dot, the name, the decisions badge, the mode word, the state"
    assert (p["name"], p["badge"], p["badgeLabel"], p["mode"], p["state"]) == ("Marketing", "1", "1 decision waiting", "milestones", "waiting for you")
    assert p["modeTitle"] == "Reviews reach you at milestones; acting as supervised", "C-5: the mode's one line is the title (and the acting mode, which the plate has no room to draw)"
    assert {"pui-badge", "pui-soft", "pui-warn", "wb-st"} <= set(p["stateClasses"]) and p["stateTitle"] == "waiting for you", "R-26: the state is a soft badge with its whole text as the tooltip"
    assert [m[0] for m in p["meters"]] == ["2 / 6 runs", "$0.03 / $2.00"], "R-25, R-5/R-6: the meters are named `runs` and `$`"
    assert p["meters"][0][1].startswith("Counted against the cap of runs per day"), "each meter's tooltip says what the cap counts"
    assert p["meters"][1][1].endswith("$0.03 recorded · up to $0.50 reserved"), "the note under the spend meter is the end of its tooltip, the plate has no caption sentence"
    assert [m[2] for m in p["meters"]] == [1, 1] and [m[3] for m in p["meters"]] == [0, 1], "the spend track keeps its reserved segment"
    assert p["noChips"] == 0, "R-25, C-5: no count chips, no note, no pips, no mode plate on a plate"
    assert got["tiny"] == {"classes": ["wb-plate", "is-short"], "parts": ["wb-plate-row"]}, "R-25: with more than eight floors the name row alone"
    assert got["oneMeter"] == ["2 / 6 runs"], "A-38: a meter only for a cap in use"
    assert "is-off" in got["off"]


@needs_node
def test_a_row_of_the_floors_list_is_the_name_the_badge_and_the_mode_word_on_one_line_with_the_state_badge_at_the_right_and_the_chips_under(tmp_path):
    got = run_node(tmp_path, NODES)
    r = got["row"]
    assert r["tag"] == "A" and r["href"] == "#/p/x/floor/marketing" and r["floor"] == "marketing"
    assert r["parts"] == ["wb-dot is-theme", "wb-fl-title", "wb-fl-state", "wb-fl-chips", "wb-fl-chev"], "R-27: the dot, the title line, the state badge at the right, the chips under, the chevron"
    assert r["title"] == ["wb-fl-name", "pui-badge pui-warn pui-soft pui-rounded-full", "wb-fl-mode"] and r["mode"] == "milestones" and r["state"] == "waiting for you"
    assert r["chips"] == ["1 done", "1 queued", "1 left", "waiting for #10", "acting as supervised"], "the chips of A-12 in their order, the wait, then the acting mode: the row has the room the plate has not"
    assert r["chev"] is True and r["noMeters"] == 0, "C-2: a compact row has no meters (the plates measure, the panel lists)"
    assert got["rowPlain"] == ["wb-dot is-theme", "wb-fl-title", "wb-fl-state", "wb-fl-chev"], "R-27: the count chips only when there are any"


@needs_node
def test_the_work_order_tag_is_a_brand_badge_and_the_phones_card_has_the_mode_and_the_figures_on_one_line(tmp_path):
    got = run_node(tmp_path, NODES)
    t = got["tag"]
    assert t["tag"] == "SPAN" and {"wb-label", "wb-tag", "pui-badge", "pui-theme", "pui-solid"} <= set(t["classes"]) and t["text"] == "#7" and t["title"] == "Request 7 is on this floor", \
        "R-29: an HTML badge `#7` in the brand colour"
    assert got["card"][1] == "milestones · runs 2 / 6 · spend $0.03 / $2.00"


# --- the view: the panel and its sections ------------------------------------------------------------------------------------------------------------

BUILDING = VIEW_HEAD + r"""
import { createBuildingView } from "@JS@/views/building.js";
import { plateNode } from "@JS@/scene/plates.js";
import * as fm from "@JS@/floor-model.js";

const kids = (n) => n.children.filter((c) => c instanceof FakeNode);
const cls = (n) => n.cls();
const byClass = (root, c) => [...root.walk()].filter((n) => cls(n).includes(c));
const highlights = [];
let selected = [];
let refreshed = 0;
const frame = makeFrame();
frame.sceneHost.querySelectorAll = FakeNode.prototype.querySelectorAll;
let sceneOpts = null;
frame.acquireWorld = (opts) => (sceneOpts = opts, { flyTo: () => Promise.resolve(false), stats: () => ({}), highlight: (id, source) => highlights.push([id, source]), setCorner() {}, show() {}, refit() {}, setOptions() {} });
const view = createBuildingView(frame, { refresh: async () => { refreshed += 1; }, selectRequest: (project, id) => selected.push([project, id]) });
const snap = JSON.parse(JSON.stringify(snapshot));
snap.details[P].agents = [agent("planning"), agent("business"), agent("brand"), agent("engineering"), agent("marketing")];
snap.details[P].status = { requests: [
    { id: 2, title: "Sale page", state: "running", tasks: [task(4, "done", "planning"), task(5, "running", "engineering"), task(6, "waiting", "marketing")] },
    { id: 3, title: "Autumn catalogue", state: "planned", tasks: [task(7, "planned", "brand")] },
    { id: 1, title: "Done long ago", state: "done", tasks: [] }],
  pending: [{ id: 8, kind: "question", title: "Which colour?", task_id: 6, agent: "marketing", created_at: "2026-10-08T08:00:00Z", actions: ["answered"] }], documents: [], held: [] };
const route = router.parse(`#/p/${P}`);
const show = (stamp = 1, s = snap) => view.update({ snapshot: s, route, now: NOW, reload: stamp });

// before anything is read
view.update({ snapshot: { ...snap, loaded: false, projects: [], details: {} }, route, now: NOW, reload: 0 });
out.loading = { line: byClass(frame.main, "wb-muted").filter((n) => n.tagName === "P" && !n.hidden).map((n) => n.textContent), sections: byClass(frame.main, "wb-sec").map((n) => n.hidden) };

show(1);
await settle();
const panel = byClass(frame.main, "wb-panel-building")[0];
out.panel = { classes: cls(panel), label: panel.attrs["aria-labelledby"], head: kids(byClass(panel, "wb-panel-head")[0]).map((c) => cls(c).join(" ")), title: byClass(panel, "wb-panel-title")[0].textContent,
  sub: byClass(panel, "wb-panel-sub")[0].textContent };
const stateButton = byClass(panel, "wb-state-btn")[0];
out.stateButton = { tag: stateButton.tagName, classes: cls(stateButton), label: stateButton.attrs["aria-label"], title: stateButton.attrs.title, icon: kids(stateButton).map((c) => cls(c).join(" ")), text: stateButton.textContent };
const body = byClass(panel, "wb-panel-body")[0];
out.body = kids(body).filter((n) => !n.hidden).map((n) => n.tagName + "." + cls(n).join("."));
out.facts = byClass(panel, "wb-facts")[0].children.map((c) => c.textContent);
out.sections = byClass(panel, "wb-sec").map((n) => [n.attrs.id || "", cls(n).join(" "), n.hidden, kids(n).filter((c) => !c.hidden).map((c) => c.tagName)]);
out.requestsHeading = byClass(panel, "wb-sec-head").map((n) => n.textContent);
const items = byClass(panel, "wb-rq");
out.requests = items.map((li) => ({ classes: cls(li), id: li.attrs["data-request"], main: kids(byClass(li, "wb-rq-main")[0]).map((c) => c.tagName + ":" + c.textContent), current: byClass(li, "wb-rq-main")[0].attrs["aria-current"] || null,
  name: byClass(li, "wb-rq-main")[0].attrs["aria-label"], open: [byClass(li, "wb-rq-open")[0].attrs.href, byClass(li, "wb-rq-open")[0].attrs["aria-label"]],
  cancel: [byClass(li, "wb-rq-cancel")[0].textContent, byClass(li, "wb-rq-cancel")[0].attrs["aria-label"], byClass(li, "wb-rq-cancel")[0].tagName, cls(byClass(li, "wb-rq-cancel")[0]).join(" ")],
  order: kids(li).map((c) => cls(c).find((k) => k.startsWith("wb-rq-"))) }));
const docs = byClass(panel, "wb-docs-link")[0];
out.docs = { href: docs.attrs.href, text: docs.textContent, icons: kids(docs).map((c) => cls(c).join(" ")) };
out.floors = { heading: byClass(byClass(panel, "wb-sec")[2], "wb-sec-head")[0].textContent, label: byClass(panel, "wb-fl-list")[0].attrs["aria-label"], rows: byClass(panel, "wb-fl-row").map((a) => [a.attrs["data-floor"], a.attrs.href, a.attrs["aria-label"]]),
  more: byClass(panel, "wb-sec-empty").filter((n) => !n.hidden).map((n) => n.textContent) };

// a request row: the main button follows it; the chevron is a link; Cancel request asks first
byClass(items[0], "wb-rq-main")[0].click();
out.selected = selected.slice();
const cancel = byClass(items[1], "wb-rq-cancel")[0];
const dialogs = () => [...frame.el.walk()].filter((n) => n.tagName === "DIALOG");
out.dialogsBefore = dialogs().length;
cancel.click();
const asked = dialogs().find((d) => cls(d).includes("wb-dialog"));
out.asked = { open: asked.open, sub: [...asked.walk()].find((n) => cls(n).includes("wb-card-note")).textContent, title: [...asked.walk()].find((n) => cls(n).includes("wb-card-title")).textContent,
  buttons: [...asked.walk()].filter((n) => n.tagName === "BUTTON").map((n) => n.textContent), focus: document.activeElement && document.activeElement.textContent };
const fetched = seen.length;
const confirm = [...asked.walk()].filter((n) => n.tagName === "BUTTON")[1];
confirm.click();
await settle();
out.cancelled = { sent: seen.slice(fetched).filter((s) => s.startsWith("POST")), refreshed, open: asked.open };

// the row's pointer and focus mark the floor in three places: the scene (engine.highlight), the plate and the row
const rows = byClass(panel, "wb-fl-row");
const plateOf = (name) => { const row = fm.building(snap, P).rows.find((r) => r.name === name); return plateNode(fm.plateOf(row)); };
const plateA = plateOf("engineering");
const plateB = plateOf("brand");
frame.sceneHost.append(plateA, plateB);
const engRow = rows.find((a) => a.attrs["data-floor"] === "engineering");
const fire = (node, type, extra = {}) => (node.listeners[type] || []).forEach((fn) => fn({ target: node, ...extra }));
fire(engRow, "pointerenter");
out.enter = { engine: highlights.slice(), plate: cls(plateA).includes("is-hover"), other: cls(plateB).includes("is-hover"), row: cls(engRow).includes("is-hover"), others: rows.filter((r) => r !== engRow).some((r) => cls(r).includes("is-hover")) };
fire(engRow, "pointerleave");
out.leave = { engine: highlights.slice(-1)[0], plate: cls(plateA).includes("is-hover"), row: cls(engRow).includes("is-hover") };
fire(engRow, "focus");
out.focus = { engine: highlights.slice(-1)[0], plate: cls(plateA).includes("is-hover"), row: cls(engRow).includes("is-hover") };
// two slots: the pointer on another row and away again leaves the keyboard's mark where it is
const brandRow = rows.find((a) => a.attrs["data-floor"] === "brand");
fire(brandRow, "pointerenter");
out.twoSlots = { over: highlights.slice(-1)[0], engRow: cls(engRow).includes("is-hover"), brandRow: cls(brandRow).includes("is-hover") };
fire(brandRow, "pointerleave");
out.twoSlotsAfter = { engine: highlights.slice(-1)[0], plate: cls(plateA).includes("is-hover"), engRow: cls(engRow).includes("is-hover"), brandRow: cls(brandRow).includes("is-hover") };
// Escape after the keyboard's focus: the engine clears its brackets and tells the page, which clears the plate and the row with them
const told = highlights.length;
sceneOpts.onHover(null, "clear");
out.escape = { plate: cls(plateA).includes("is-hover"), row: cls(engRow).includes("is-hover"), engineTold: highlights.length - told };
fire(engRow, "blur");
// the pointer on a plate
const hovered = (plate) => ({ target: { closest: () => plate } });
(frame.sceneHost.listeners.pointerover || []).forEach((fn) => fn(hovered(plateB)));
out.plateOver = { engine: highlights.slice(-1)[0], plate: cls(plateB).includes("is-hover"), row: cls(rows.find((a) => a.attrs["data-floor"] === "brand")).includes("is-hover") };
(frame.sceneHost.listeners.pointerout || []).forEach((fn) => fn(hovered(plateB)));
out.plateOut = { engine: highlights.slice(-1)[0], plate: cls(plateB).includes("is-hover") };

// Project state: the icon button opens the viewer on docs/workbench/state.md
const before = seen.length;
stateButton.click();
await settle();
out.state = { read: seen.slice(before), dialog: dialogs().find((d) => d.attrs["aria-label"] === "Project state").open };
out.beforeDispose = dialogs().length;
view.dispose();
out.afterDispose = { dialogs: dialogs().length, panels: byClass(frame.main, "wb-panel-building").length };
console.log(JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def building(tmp_path_factory):
    return run_node(tmp_path_factory.mktemp("building"), BUILDING)


@needs_node
def test_the_panel_is_the_head_with_project_state_as_an_icon_button_the_facts_requests_documents_and_floors(building):
    g = building
    assert g["panel"]["classes"][:3] == ["pui-card", "wb-panel", "wb-drawer"] and "wb-bpanel" in g["panel"]["classes"] and g["panel"]["label"] == "wb-building-title"
    assert g["panel"]["head"] == ["wb-tile pui-soft pui-theme", "wb-panel-titles", "pui-btn pui-soft pui-muted wb-state-btn"], "R-27: the head with the project's name and, at its right, Project state"
    assert g["panel"]["title"] == "northwind-shop" and g["panel"]["sub"] == "Project · one floor per area agent"
    s = g["stateButton"]
    assert s["tag"] == "BUTTON" and s["label"] == "Project state" and s["title"] == "Project state" and s["text"] == "" and s["icon"] == ["wb-icon wb-icon-info wb-i16"], \
        "R-27: an icon button (information; soft, muted), named Project state, no text"
    assert g["facts"][:2] == ["Configuration", "Accepted"] and g["facts"][2] == "Running now", "C-2: Configuration and Running now only"
    assert "Request" not in g["facts"] and "Waiting for you" not in g["facts"], "C-2: the request followed is the selected row, the decisions' count is the KPI card"
    assert [x[0] for x in g["sections"]] == ["", "", "wb-scene-list"] and [x[2] for x in g["sections"]] == [False, False, False]
    assert g["requestsHeading"] == ["Requests (2)", "Floors"], "R-27: `Requests (n)` and `Floors` (not `Floors, top to bottom`)"
    assert g["floors"]["heading"] == "Floors" and g["floors"]["label"] == "Floors, top to bottom", "the list keeps its accessible name"


@needs_node
def test_a_request_row_is_the_number_the_title_and_the_state_chip_the_steps_line_the_chevron_and_cancel_request_on_a_line_of_its_own(building):
    r = building["requests"]
    assert [x["id"] for x in r] == ["2", "3"], "the open requests, from the lowest number; the finished one is not listed"
    followed = r[0]
    assert "is-selected" in followed["classes"] and followed["current"] == "true" and r[1]["current"] is None, "R-27: the followed request takes the emphasis ground (aria-current)"
    assert followed["main"][:3] == ["SPAN:#2", "STRONG:Sale page", "SPAN:Running"], "R-27: the number, the title and the state chip"
    assert followed["main"][3].startswith("SPAN:1 of 3 steps done · now on Engineering"), "the steps line under the title: where the request is"
    assert followed["open"] == ["#/p/0123456789ab/lobby/conversation/request/2", "Open request #2 in the Lobby conversation"], "the chevron goes to the request's line in the Lobby"
    assert followed["cancel"][:2] == ["Cancel request", "Cancel request 2"] and followed["cancel"][2] == "BUTTON" and "pui-link" in followed["cancel"][3] and "pui-error" in followed["cancel"][3], \
        "R-27: `Cancel request` is a link-style error button"
    assert followed["order"] == ["wb-rq-main", "wb-rq-open", "wb-rq-cancel"], "the row holds the main button, the chevron and Cancel"
    assert r[1]["main"][3].endswith("0 of 1 steps done")


@needs_node
def test_documents_n_takes_the_full_width_and_opens_the_lobbys_desk_and_the_floors_list_has_a_row_for_each_floor_top_down(building):
    g = building
    assert g["docs"]["href"] == "#/p/0123456789ab/lobby/desk" and g["docs"]["text"] == "Documents (1)" and g["docs"]["icons"][0] == "wb-icon wb-icon-file-text wb-i16", \
        "R-27: `Documents (n)`, the count of the artifacts read, goes to the Lobby's Desk"
    assert [r[0] for r in g["floors"]["rows"]] == ["marketing", "engineering", "brand", "business", "planning"], "the top floor first, the Lobby last"
    assert g["floors"]["rows"][1][2].startswith("Engineering, working, supervised mode"), "the row's accessible name"
    assert g["floors"]["more"] == [], "five floors: no `+n more floors` line"
    assert g["loading"]["line"] == ["Loading the floors..."] and all(g["loading"]["sections"]), "while nothing is read: the one line, no section"


@needs_node
def test_a_request_row_follows_the_request_and_cancel_request_asks_first_with_the_lobbys_dialog_and_sends_the_cancel(building):
    g = building
    assert g["selected"] == [["0123456789ab", 2]], "a click on a request's row asks the page to follow it (the tracking bar shows it)"
    a = g["asked"]
    assert g["dialogsBefore"] == 1 and a["open"] is True, "the dialog is the Lobby's, opened by the row's button (the state viewer's is the other dialog)"
    assert a["title"] == "Cancel this request and what is still open under it?" and a["sub"] == "Request #3: Autumn catalogue · 1 task, none started", "the Lobby's confirmation, kept as built"
    assert a["buttons"] == ["Keep it", "Cancel request"] and a["focus"] == "Keep it", "the focus starts on `Keep it`"
    assert g["cancelled"]["sent"] == ["POST /requests/3/cancel"] and g["cancelled"]["refreshed"] == 1 and g["cancelled"]["open"] is False, "confirming sends the cancel once and the page reloads"


@needs_node
def test_a_floor_is_marked_in_three_places_by_a_pointer_or_the_focus_on_its_row_or_its_plate(building):
    g = building
    assert g["enter"] == {"engine": [["floor:engineering", "pointer"]], "plate": True, "other": False, "row": True, "others": False}, \
        "R-28: the pointer on a row marks the scene (the engine's brackets), the plate and the row"
    assert g["leave"]["plate"] is False and g["leave"]["row"] is False and g["leave"]["engine"][0] is None, "leaving clears the three"
    assert g["focus"]["engine"] == ["floor:engineering", "keyboard"] and g["focus"]["plate"] is True and g["focus"]["row"] is True, "the focus on a row marks the three, as a keyboard focus"
    assert g["plateOver"] == {"engine": ["floor:brand", "pointer"], "plate": True, "row": True}, "the pointer on a plate marks the scene, the plate and its row"
    assert g["plateOut"]["engine"][0] is None and g["plateOut"]["plate"] is False


@needs_node
def test_the_focus_survives_the_pointer_leaving_another_row_and_escape_clears_the_scene_the_plate_and_the_row_together(building):
    g = building
    assert g["twoSlots"] == {"over": ["floor:brand", "pointer"], "engRow": False, "brandRow": True}, "the pointer's floor is the one marked while it is over one"
    assert g["twoSlotsAfter"] == {"engine": ["floor:engineering", "keyboard"], "plate": True, "engRow": True, "brandRow": False}, \
        "a pointer leaving a row does not clear the mark of the row that has the focus: the engine is told the focus's floor again"
    assert g["escape"] == {"plate": False, "row": False, "engineTold": 0}, "Escape: the engine clears its brackets and tells the page (onHover(null, \"clear\")), which clears the plate and the row"
    engine = (JS / "scene" / "engine.js").read_text(encoding="utf-8")
    assert engine.count('if (options.onHover) options.onHover(null, "clear");') == 2, "clearSelection and clearHover both tell the page"


@needs_node
def test_a_disposed_view_leaves_no_dialog_and_no_panel_in_the_frame(building):
    assert building["beforeDispose"] == 2 and building["afterDispose"] == {"dialogs": 0, "panels": 0}, "the state viewer's dialog and the cancel dialog the view added to the frame go with it"


@needs_node
def test_project_state_opens_the_viewer_on_the_state_file(building):
    assert building["state"]["dialog"] is True and any("state.md" in s for s in building["state"]["read"]), "the icon button opens the viewer on docs/workbench/state.md"


# --- the states of the page ------------------------------------------------------------------------------------------------------------------------

STATES = VIEW_HEAD + r"""
import { createBuildingView } from "@JS@/views/building.js";

const kids = (n) => n.children.filter((c) => c instanceof FakeNode);
const cls = (n) => n.cls();
const byClass = (root, c) => [...root.walk()].filter((n) => cls(n).includes(c));
const shows = [];
const mk = () => {
  const frame = makeFrame();
  frame.acquireWorld = () => ({ flyTo: () => Promise.resolve(false), stats: () => ({}), highlight() {}, setCorner() {}, show: (kind, model, label) => shows.push([kind, model.lots.length, label]), refit() {}, setOptions() {} });
  return frame;
};
const run = async (snap, route = router.parse(`#/p/${P}`)) => {
  const frame = mk();
  const view = createBuildingView(frame, { refresh: async () => {}, selectRequest() {} });
  view.update({ snapshot: snap, route, now: NOW, reload: 1 });
  await settle();
  const panel = byClass(frame.main, "wb-panel-building")[0];
  const shown = { panelHidden: panel.hidden, sections: byClass(panel, "wb-sec").map((n) => [n.hidden, byClass(n, "wb-sec-head").map((h) => h.textContent)]), rows: byClass(panel, "wb-fl-row").length,
    empties: byClass(panel, "wb-sec-empty").filter((n) => !n.hidden).map((n) => n.textContent), facts: byClass(panel, "wb-facts")[0].children.map((c) => c.textContent),
    states: byClass(panel, "wb-fl-state").map((n) => n.textContent), docs: byClass(panel, "wb-docs")[0].hidden };
  view.dispose();
  return shown;
};
const base = JSON.parse(JSON.stringify(snapshot));
base.details[P].agents = [agent("planning"), agent("engineering")];
base.details[P].status = { requests: [], pending: [], held: [], documents: [] };
out.noRequests = await run(base);
const refused = JSON.parse(JSON.stringify(base));
refused.projects[0].config.accepted = false;
refused.details[P].status.requests = [{ id: 2, title: "Sale page", state: "running", tasks: [task(5, "running", "engineering")] }];
out.keptData = await run(refused);
const never = JSON.parse(JSON.stringify(base));
never.projects[0].config.accepted = false;
never.details = {};
out.neverRead = await run(never);
const lone = JSON.parse(JSON.stringify(base));
lone.details[P].agents = [];
out.noAgents = await run(lone);
const many = JSON.parse(JSON.stringify(base));
many.details[P].agents = ["planning", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j"].map((n) => agent(n));
out.many = await run(many);
const unknown = JSON.parse(JSON.stringify(base));
shows.length = 0;
out.unknown = await run(unknown, router.parse("#/p/ffffffffffff"));
out.unknownShows = shows.slice();
out.loadingShows = (async () => { shows.length = 0; await run({ ...base, loaded: false, projects: [], details: {} }); return shows.slice(); })();
out.loadingShows = await out.loadingShows;
out.unknownPanelHiddenThenKnown = out.noRequests.panelHidden;
console.log(JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def states(tmp_path_factory):
    return run_node(tmp_path_factory.mktemp("states"), STATES)


@needs_node
def test_building_html_states_no_request_open_a_project_not_accepted_with_and_without_data_no_agents_and_more_than_eight_floors(states):
    g = states
    assert g["noRequests"]["empties"] == ["No request is open"] and g["noRequests"]["sections"][0] == [False, ["Requests (0)"]], "no request is open: `Requests (0)` and the line"
    assert g["keptData"]["facts"][:2] == ["Configuration", "Not accepted"] and set(g["keptData"]["states"]) == {"not accepted"}, "A-16: the last data read stays; every floor says `not accepted`"
    assert g["keptData"]["sections"][0] == [False, ["Requests (1)"]], "with the data kept, Requests (n) stays"
    assert g["neverRead"]["sections"][0][0] is True and g["neverRead"]["docs"] is True and g["neverRead"]["facts"] == ["Configuration", "Not accepted"], \
        "a project never read: only Configuration; Requests (n) and Documents (n) are absent"
    assert g["noAgents"]["empties"][-1] == "This project has no area agents in its configuration." and g["noAgents"]["rows"] == 1, "the Lobby alone, with the line under the list"
    assert g["many"]["rows"] == 11 and "+3 more floors" in g["many"]["empties"], "every agent has a row; the scene draws eight and the list says how many more"
    assert g["unknown"]["panelHidden"] is True and g["unknownPanelHiddenThenKnown"] is False, "building.html \"No such project\": no panel (the band says why); a project the service holds has its panel"
    assert g["unknownShows"][-1] == ["world", 0, "Building"], "an empty scene named `Building`, not the City behind the band"
    assert g["loadingShows"][-1][2] == "Building, loading", "loading: the canvas label `Building, loading`"


# --- the stylesheet: the places and the tokens ----------------------------------------------------------------------------------------------------------

def test_the_stylesheet_draws_the_plate_the_rows_the_requests_and_the_tag_as_the_page_does():
    flat = rules(TOP)

    def has(selector, *parts):
        found = [decl for sel, decl in flat if sel == selector]
        assert found, f"{selector} has no rule"
        text = " ".join(f"{k}: {v}" for decl in found for k, v in decl.items())
        for part in parts:
            assert part in text, f"{selector}: {part}"

    has(".wb-plate", "width: var(--wb-plate-w)", "border-radius: calc(var(--pui-radius) * 1.2)", "padding: 8px 12px")
    assert "--wb-plate-w: 276px" in TOP, "R-25: the plate is 276 px"
    has(".wb-plate.is-hover", "border-color: var(--pui-theme)", "color-mix(in oklab, var(--pui-theme) 8%, var(--wb-raised))")
    has(".wb-fl-row.is-hover", "border-color: var(--pui-theme)")
    has(".wb-plate-meters", "grid-template-columns: repeat(2, minmax(0, 1fr))")
    has(".wb-plate.is-short, .wb-plate.is-tiny", "padding: 6px 12px")
    has(".wb-plate", "margin-left: 28px")
    assert "PLATE_SHIFT = 28" in (JS / "views" / "building.js").read_text(encoding="utf-8"), "the fit keeps the room of the plate's margin"
    has(".wb-st", "text-overflow: ellipsis", "font-size: 11px")
    has(".wb-rq.is-selected", "background-color: var(--pui-bg-emphasis)")
    has(".wb-rq-cancel", "grid-column: 1 / -1", "margin: -2px 0 6px 44px")
    has(".wb-rq-main", 'grid-template-areas: "n title chip" "n sub sub"')
    has(".wb-fl-row", 'grid-template-areas: "dot title state chev" ". chips chips chev"')
    has(".wb-docs-link", "display: flex")
    has(".wb-state-btn", "width: 32px", "margin-left: auto")
    has(".wb-bpanel > .wb-panel-body", "padding: 14px 12px 28px")     # R-27: some space after the last row
    has(".wb-label.wb-tag", "font-variant-numeric: tabular-nums")
    assert re.search(r"\.wb-icon-info \{[^}]*icons/info\.svg", CSS), "the information icon is a file of icons/"
    assert (INTERFACE / "icons" / "info.svg").exists() and '"info"' in (JS / "frame" / "icons.js").read_text(encoding="utf-8")
    assert re.search(r"@media \(prefers-reduced-motion: reduce\) \{ \.wb-plate, \.wb-fl-row \{ transition: none; \} \}", CSS), "the hover mark's transition goes under reduced motion"
    for gone in ("wb-plate-chips", "wb-plate-note", "wb-label-tag", "wb-list-heading", "wb-state-link", "wb-floor-row", "wb-floor-item"):
        assert gone not in CSS, f"{gone} is gone"


def test_the_buildings_phone_rows_are_at_least_44_px_and_the_sheet_keeps_space_after_the_last_row():
    phone = rules(PHONE)
    assert any(sel == ".wb-fl-row, .wb-rq-main" and decl.get("min-height") == "44px" for sel, decl in phone), "R-10: rows are at least 44 px high on a phone"
    assert any(sel == ".wb-bpanel > .wb-panel-body" and decl.get("padding") == "12px 12px 28px" for sel, decl in phone)


def test_a_plate_has_no_compact_pass_in_the_stacking():
    labels = (JS / "scene" / "labels.js").read_text(encoding="utf-8")
    assert "is-compact" not in labels and "compact" not in labels.split("function placeColumn")[1].split("export function placeLabels")[0], "R-25: one size; the only short form is the name row alone"


def test_the_building_passes_the_requests_selection_to_the_page_and_the_view_makes_the_cancel_dialog_only_when_asked():
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert "createBuildingView(frame, { refresh: () => reloaded(), selectRequest })" in main and "onSelectRequest: selectRequest" in main, "one handler for the tracking bar and the Building's rows"
    view = (JS / "views" / "building.js").read_text(encoding="utf-8")
    assert "createCancelDialog({ api, project: projectId" in view and "cancelCount(request)" in view, "the Lobby's own dialog and its own count line"
    assert 'api.cancel' not in view, "the dialog is the one that sends the cancel"
    assert "innerHTML" not in view
