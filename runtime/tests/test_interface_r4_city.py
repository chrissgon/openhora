"""Tests of round 4's City screen (R4-A2; rulings R-7 and R-22 of the plan folder's design/04-round-4-rulings.md, C-7 of `design/screens/city.md`): "Waiting for you"
open at the bottom right and alone in a phone's sheet, no box of project controls and no per-row Leave button (Add, Leave and Forget are the switcher's foot),
the Projects list as the scene's keyboard twin (clipped until something in it has the focus, drawn where the page draws it), the states of the page's city.html
(loading, empty, one project, not accepted, network error, no WebGL, the phone's sheet collapsed and at half). No browser and no model: the view runs under Node with a
fake document, as the other interface tests do; the served page was looked at in the browser pane by the package's report (`reports/r4/R4-A2.md` of the plan folder).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_city.py
"""
from __future__ import annotations

import re

from test_interface_adj_b1 import run_scene_dom
from test_interface_floor import INTERFACE, needs_node
from test_interface_phone_sheet import media_blocks, rules, without_media
from test_interface_plates_meters import run_node
from interface_css import interface_css

JS = INTERFACE / "js"
CSS = interface_css()
PHONE = "\n".join(media_blocks(CSS, "max-width: 639px"))
DOCKED = "\n".join(media_blocks(CSS, "min-width: 640px) and (max-width: 899px"))
TOP = without_media(CSS)

# --- the view's markup: a sheet with the waiting card alone, the list as a twin, no project controls -------------------------------------------

CITY = r"""
import { FakeNode } from "@FAKE@";
import { createCityView } from "@JS@/views/city.js";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const el = () => new FakeNode("div");
const all = (root) => [...root.walk()];
const cls = (n) => n.cls();
const byClass = (root, c) => all(root).filter((n) => cls(n).includes(c));
const kids = (n) => n.children.filter((c) => c instanceof FakeNode);
const labels = [];
const frame = {
  main: el(), sceneHost: el(), track: { el: el() }, kpis: { el: el() }, noticeBox: el(),
  waitingCard: { el: (() => { const n = new FakeNode("section"); n.setAttribute("class", "pui-card wb-waiting"); return n; })(), set() {} },
  insets: () => ({}), sceneUnavailable() {},
  acquireWorld: () => ({ highlight() {}, show(kind, model, label) { labels.push(label); }, flyTo: () => Promise.resolve(false), setOptions() {}, stats() { return {}; } }),
};
const view = createCityView(frame);
const b = (id, name, extra = {}) => ({ id, name, accepted: true, decisions: 0, runningTask: null, sub: "no task running", ...extra });
const snapshot = { projects: [], details: {}, tasks: {}, loaded: true };
const NOW = new Date("2026-10-10T09:00:00Z");
view.update({ city: { buildings: [b("aaaaaaaaaaaa", "northwind-shop", { decisions: 2, runningTask: 2, sub: "task #2 running" }), b("bbbbbbbbbbbb", "tinykv-docs", { accepted: false, sub: "not accepted yet" })], waiting: [], canvasLabel: "City" }, selectedId: null, state: "ready", snapshot, now: NOW });

const out = {};
out.main = kids(frame.main).map((c) => cls(c).filter((x) => x.startsWith("wb-")).join(" "));
const sheet = byClass(frame.main, "wb-city-drawer")[0];
out.sheet = kids(sheet).map((c) => cls(c).join(" "));
out.scroll = kids(byClass(sheet, "wb-drawer-scroll")[0]).map((c) => cls(c).join(" "));
out.sheetHasList = byClass(sheet, "wb-buildings").length + byClass(sheet, "wb-building-link").length;
out.noBox = [byClass(frame.main, "wb-city-projects").length, byClass(frame.main, "wb-leave-project").length, byClass(frame.main, "wb-add-project").length,
  all(frame.main).filter((n) => n.tagName === "BUTTON" && /Add a project|Leave/.test(n.textContent)).length,
  all(frame.main).filter((n) => /Projects of the service/.test(n.attrs["aria-label"] || "")).length];
const list = byClass(frame.main, "wb-buildings")[0];
out.list = { id: list.attrs.id, tabindex: list.attrs.tabindex, head: byClass(list, "wb-buildings-head")[0].textContent, label: byClass(list, "wb-building-list")[0].attrs["aria-label"] };
out.rows = byClass(list, "wb-building-item").map((li) => kids(li).map((c) => c.tagName + ":" + (c.attrs["aria-label"] || "")));
out.rowParts = byClass(list, "wb-building-link").map((a) => kids(a).map((c) => cls(c)[0]));
out.empty = kids(byClass(frame.main, "wb-empty-card")[0]).map((c) => c.tagName + "." + cls(c).join(" ") + ":" + c.textContent);
const none = { buildings: [], waiting: [], canvasLabel: "City with no project" };
view.update({ city: none, selectedId: null, state: "loading", snapshot, now: NOW });
out.loading = [byClass(list, "wb-empty")[0].textContent, labels[labels.length - 1], byClass(frame.main, "wb-empty-card")[0].hidden];
view.update({ city: none, selectedId: null, state: "error", snapshot, now: NOW });
out.failed = [byClass(list, "wb-empty")[0].textContent, labels[labels.length - 1], byClass(frame.main, "wb-empty-card")[0].hidden];
view.update({ city: none, selectedId: null, state: "ready", snapshot, now: NOW });
out.emptied = [byClass(list, "wb-empty")[0].textContent, labels[labels.length - 1], byClass(frame.main, "wb-empty-card")[0].hidden];
out.labels = labels.slice(0, 1);
out.buttons = all(frame.main).filter((n) => n.tagName === "BUTTON").map((n) => cls(n).join(" "));
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_city_has_no_box_of_project_controls_and_no_leave_button_and_the_sheet_holds_the_waiting_card_alone(tmp_path):
    got = run_node(tmp_path, CITY)
    assert got["main"] == ["wb-drawer wb-city-drawer", "wb-buildings", "wb-empty-card"], "R-22: the sheet, the list as a part of the screen of its own, the empty card; no box of controls"
    assert got["sheet"] == ["wb-grip", "wb-drawer-scroll"] and got["scroll"] == ["pui-card wb-waiting"], "R-22: on a phone the sheet holds \"Waiting for you\" alone (the handle and the card)"
    assert got["sheetHasList"] == 0, "R-22: no Projects list in the sheet"
    assert got["noBox"] == [0, 0, 0, 0, 0], "R-22, A-35: no box, no \"Add a project\" or \"Leave a project\" button, no per-row Leave; the switcher's foot has them"
    assert got["empty"] == ["P.wb-empty:The service has no project. Start it with --project <folder>."], "the empty card of city.html: one muted line in the card"
    assert got["labels"] == ["City"] and got["loading"] == ["Loading the projects...", "City, loading", True], "city.html \"Loading\": the list line, the canvas label \"City, loading\", no empty card"
    assert got["failed"] == ["The projects could not be read.", "City with no project", True], "the first read failed: the list's line; the empty card is never claimed after a failed read"
    assert got["emptied"] == ["The service has no project.", "City with no project", False], "a read that answered with no project: the line, the label and the empty card"
    assert got["buttons"] == ["wb-grip"], "the handle is the only button the City's view draws"
    assert got["list"] == {"id": "wb-scene-list", "tabindex": "-1", "head": "Projects", "label": "Projects"}, "the keyboard twin is still what \"Skip to the scene list\" names"
    assert got["rows"] == [["A:northwind-shop, 2 decisions waiting, task #2 running"], ["A:tinykv-docs, not accepted yet"]], "a row is one link with its name for a screen reader, and nothing else"
    assert got["rowParts"] == [["wb-dot", "wb-building-name", "pui-badge", "wb-building-sub", "wb-icon"], ["wb-dot", "wb-building-name", "pui-chip", "wb-building-sub", "wb-icon"]], \
        "the row of city.html: the dot, the name, the count (or the chip \"Not accepted\"), the sub line, the chevron"


def test_the_city_view_does_not_make_the_command_panel_and_its_drawer_is_dragged_by_the_waiting_head_alone():
    city = (JS / "views" / "city.js").read_text(encoding="utf-8")
    assert "city-projects" not in city, "R-22, A-35: the command panel is the frame's (the switcher's foot opens it on every screen); the City makes none"
    assert not re.search(r"Leave|Add a project|wb-city-projects|wb-wait-h(?![\w-])|boxObserver|projectsBox", city), "no remnant of the box, the per-row button or the box's height"
    assert 'handles: ".wb-wait-head"' in city, "the sheet's one header line starts a drag"
    assert "frame.main.append(sheet, buildings, empty)" in city, "the list is a part of the screen, not of the sheet"
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert "createProjectsPanel" in main and "projectsPanel," in main, "the one command panel is made by the page and drawn by the frame"


DIMS = r"""
import * as model from "@JS@/model.js";
const ok = (id) => ({ id, name: id, config: { accepted: true } });
const no = (id) => ({ id, name: id, config: { accepted: false } });
console.log(JSON.stringify({
  all: model.cityDims([ok("a"), ok("b")], {}),
  one: model.cityDims([ok("a"), no("b")], {}),
  refused: model.cityDims([ok("a"), ok("b")], { b: { error: { status: 412 } } }),
  otherError: model.cityDims([ok("a")], { a: { error: { status: 500 } } }),
  none: model.cityDims([], {}),
  notAList: model.cityDims(null, null),
}));
"""


@needs_node
def test_the_city_dims_its_cards_and_the_tracking_bar_while_any_project_is_not_accepted(tmp_path):
    got = run_node(tmp_path, DIMS)
    assert got == {"all": False, "one": True, "refused": True, "otherError": False, "none": False, "notAList": False}, \
        "city.html \"A project not accepted\": the cards' sums span every project, so one project that is not accepted dims them, whichever project is followed"
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert 'route.screen === "city" ? model.cityDims(projects, snapshot.details)' in main, "only the City reads the rule; a project's screens dim for that project (A-16)"
    assert re.search(r"\.wb-frame\.is-unaccepted \.wb-kpis, \.wb-frame\.is-unaccepted \.wb-track \{ opacity: 0\.55; \}", CSS), "the cards and the bar dim by one class and one opacity"


BAND = r"""
import { FakeNode } from "@FAKE@";

document.querySelector = () => null;
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
const { createFrame } = await import("@JS@/frame/frame.js");
const kids = (n) => n.children.filter((c) => c instanceof FakeNode);
const describe = (n) => n.tagName + "." + n.cls().join(".") + (n.textContent ? ":" + n.textContent : "");
let retried = 0;
const f = createFrame(new FakeNode("div"), { onSelectProject() {}, onForgetToken() {}, onRetry() { retried += 1; } });
f.notice({ kind: "error", lead: "The service could not be reached. Is it still running?", retry: true });
const band = [...f.noticeBox.walk()].find((n) => n.cls().includes("wb-notice"));
const out = { lead: kids(band).map(describe) };
(kids(band)[1].listeners.click || []).forEach((fn) => fn({}));
out.retried = retried;
f.notice({ kind: "error", text: "A sentence", retry: true });
out.text = kids([...f.noticeBox.walk()].find((n) => n.cls().includes("wb-notice"))).map(describe);
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_first_read_that_failed_is_the_bands_lead_with_try_again_under_it_as_the_page_draws_it(tmp_path):
    got = run_scene_dom(tmp_path, BAND)
    assert got["lead"] == ["P.wb-notice-lead:The service could not be reached. Is it still running?", "BUTTON.pui-btn.pui-surface.pui-outline.wb-small-button:Try again"], \
        "city.html \"First read failed\": the lead, then the small button; no empty sentence between them"
    assert got["retried"] == 1, "Try again reads everything again"
    assert got["text"] == ["P.wb-notice-text:A sentence", "BUTTON.pui-btn.pui-surface.pui-outline.wb-small-button:Try again"], "a band that has a sentence of its own keeps it"
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert 'return { kind: "error", lead, retry: true };' in main, "the failure of the first read is said as the lead"


NOTICE = r"""
import { FakeNode } from "@FAKE@";

document.querySelector = () => null;
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
const { createFrame } = await import("@JS@/frame/frame.js");
const f = createFrame(new FakeNode("div"), { onSelectProject() {}, onForgetToken() {}, onRetry() {} });
const writes = [];
f.el.style.setProperty = (name, value) => writes.push([name, value]);
f.noticeBox.getBoundingClientRect = () => ({ top: 72, bottom: 326, height: 254 });
f.el.getBoundingClientRect = () => ({ top: 0 });
const mark = () => ({ has: f.el.cls().includes("has-notice"), last: writes.filter((w) => w[0] === "--wb-notice-bottom").slice(-1)[0] || null });
const out = { before: mark() };
f.notice({ kind: "error", lead: "tinykv-docs is not accepted yet", text: "the configuration has a hash", command: "python3 cli.py accept-config", mono: true });
out.shown = mark();
f.notice({ kind: "error", lead: "The service could not be reached. Is it still running?", retry: true });
out.other = mark();
f.sceneUnavailable(true);
out.noScene = f.el.cls().filter((c) => c === "no-scene" || c === "has-notice");
f.notice(null);
out.gone = mark();
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_band_over_a_scene_with_no_webgl_is_measured_so_that_the_twin_list_can_stand_under_it(tmp_path):
    got = run_scene_dom(tmp_path, NOTICE)
    assert got["before"] == {"has": False, "last": None}, "no band, nothing written"
    assert got["shown"] == {"has": True, "last": ["--wb-notice-bottom", "326px"]}, "a band: the frame says so with a class and writes where the band ends"
    assert got["other"]["has"] is True, "another band keeps the class"
    assert sorted(got["noScene"]) == ["has-notice", "no-scene"], "no WebGL and a band: the two classes the stylesheet's rule reads, on one frame"
    assert got["gone"] == {"has": False, "last": ["--wb-notice-bottom", "0px"]}, "the band goes: the class and the number go"
    css = CSS
    assert re.search(r"\.wb-frame\.no-scene\.has-notice \.wb-buildings \{ top: calc\(var\(--wb-notice-bottom, 0px\) \+ 12px \+ 52px\); \}", css), \
        "no WebGL and a band: the list stands 12 px under the band, and 52 px lower than the line that says there is no WebGL"
    assert re.search(r'\.wb-frame\[data-screen="city"\]\.no-scene\.has-notice \.wb-scene-fallback \{ top: calc\(var\(--wb-notice-bottom, 0px\) \+ 12px\); \}', css), \
        "the line that says there is no WebGL stands under the band too, not under it by chance"


# --- the stylesheet --------------------------------------------------------------------------------------------------------------------------

def test_the_projects_list_is_the_scenes_keyboard_twin_clipped_until_it_has_the_focus_and_drawn_where_the_page_draws_it():
    base = next(d for sel, d in rules(TOP) if sel == ".wb-buildings")
    assert base["position"] == "absolute" and "clip-path" in base and base["width"] == "1px" and base["height"] == "1px", "clipped to a pixel while nothing in it has the focus"
    assert base["top"] == "var(--wb-kpi-top)" and base["left"] == "calc(var(--wb-kpi-w) + var(--wb-edge) + 16px)" and "bottom" not in base, \
        "R-22 (city.html): at the top, 16 px right of the KPI column (240 px from the left, 72 px from the top at 1280)"
    focus = next(d for sel, d in rules(TOP) if sel == ".wb-buildings:focus-within")
    assert focus["width"] == "260px" and focus["height"] == "auto" and focus["clip-path"] == "none" and focus["overflow-y"] == "auto", "the page draws the focused list 260 px wide; many projects scroll inside it"
    assert next(d for sel, d in rules(TOP) if sel == ".wb-building-name")["font-weight"] == "600", "the row's name is drawn at 600 (city.html), not the browser's bold"
    nogl = next(d for sel, d in rules(TOP) if sel == ".wb-frame.no-scene .wb-buildings")
    assert nogl["width"] == "260px" and nogl["top"] == "calc(var(--wb-kpi-top) + 52px)" and nogl["clip-path"] == "none", "no WebGL: the list in full under the line that says so (city.html)"
    line = next(d for sel, d in rules(TOP) if sel == '.wb-frame[data-screen="city"].no-scene .wb-scene-fallback')
    assert line["top"] == "var(--wb-kpi-top)" and line["left"] == "calc(var(--wb-kpi-w) + var(--wb-edge) + 16px)" and line["translate"] == "none" and line["text-align"] == "left", \
        "no WebGL on the City: one line at the top, beside the KPI column, as the page draws it"


def test_a_phone_draws_the_list_over_the_scene_only_while_it_has_the_focus_and_the_sheet_has_the_waiting_head_alone():
    focus = next(d for sel, d in rules(PHONE) if sel == ".wb-buildings:focus-within")
    assert focus["top"] == "8px" and focus["left"] == "8px" and focus["right"] == "8px" and focus["width"] == "auto" and focus["z-index"] == "6", \
        "R-22: the list is no part of the sheet: while it has the focus it floats over the scene, above the cards"
    nogl = next(d for sel, d in rules(PHONE) if sel == ".wb-frame.no-scene .wb-buildings")
    assert nogl["position"] == "static" and nogl["width"] == "auto", "no WebGL on a phone: the list in the flow of the main area, under the cards (the clip is lifted by the rule of every width)"
    assert "wb-buildings" not in "".join(sel for sel, _ in rules(PHONE) if sel.startswith(".wb-drawer") or sel.startswith(".wb-drawer-scroll")), "no rule of the sheet names the list"
    head = next(d for sel, d in rules(PHONE) if sel == ".wb-drawer-scroll > .wb-waiting .wb-wait-head")
    assert head["padding"] == "10px 16px" and head["border-bottom-width"] == "0", "R-7, R-22 (city.html): the sheet's one line, \"Waiting for you\" and its count, no rule under it"
    tile = next(d for sel, d in rules(PHONE) if sel == ".wb-drawer-scroll > .wb-waiting .wb-wait-head .wb-kpi-tile")
    assert tile["display"] == "none", "the phone's line has no tile (city.html)"
    card = next(d for sel, d in rules(PHONE) if sel == ".wb-drawer-scroll > .wb-waiting")
    assert "border-top" not in card, "nothing stands above the card in the sheet: no rule between the two lists"


def test_the_band_over_the_city_is_at_most_620_px_wide_beside_the_kpi_column_as_the_page_draws_it():
    band = next(d for sel, d in rules(TOP) if sel == ".wb-notice-box")
    assert band["left"] == "calc(var(--wb-kpi-w) + var(--wb-edge) + 12px)" and band["max-width"] == "620px" and band["top"] == "var(--wb-kpi-top)", \
        "city.html \"A project not accepted\": the band stands 12 px right of the KPI column, at the top, 620 px wide (it was 632 at 1280 px)"
    assert "max-width: none" in PHONE and "max-width: none" in DOCKED, "a phone and the docked band keep the band as wide as they were"


def test_the_empty_card_is_centred_on_what_the_cards_leave_free():
    card = next(d for sel, d in rules(TOP) if sel == ".wb-empty-card")
    assert card["top"] == "50%" and card["left"] == "42%" and card["translate"] == "-50% -50%" and card["max-width"] == "26rem", "city.html \"Empty\": the card at 42 percent across and half down"


def test_the_docked_band_keeps_the_list_a_twin_too_and_nothing_names_the_removed_box():
    assert ".wb-buildings" not in DOCKED, "R-22: the list is the scene's keyboard twin at every width: the docked band (not drawn: R4D-6) no longer docks it in full, the switcher holds the projects"
    for gone in (".wb-city-projects", ".wb-city-projects-bar", ".wb-leave-project", r"--wb-wait-h(?![\w-])", ".wb-city-drawer > .wb-city-projects"):
        assert not re.search(gone.replace(".", r"\.") if gone.startswith(".") else gone, CSS), f"{gone}: the box of project controls is gone (R-22)"
    assert ".wb-add-project" in CSS, "the frame's command panel keeps its own rules"
