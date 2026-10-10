"""Tests of the page's behaviour changes of ADJ-B1 (the journeys review, before the new design): the City route (the one-project entry rule was reversed by M-1 of R4-DECISIONS: the page always opens on the City), the
request line's route and the Lobby's Desk, the two-step hand-over, the board's words, the age word, the switcher with no project, the phone's
list dialog that follows the reloads, the effect card's tab stops, the flow beside "Route it", the vendored typefaces, the light/dark preference
and the README's lines. No browser, no model and no service: the modules run under Node with a fake document, as the other interface tests do.
The served page was looked at in the browser pane by the package's report (`reports/ADJ-B1.md` of the plan folder).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_adj_b1.py
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import json
from pathlib import Path

import standin_tree as st
from test_interface_adjustments import run_node
from test_interface_floor import FAKE_DOM as FLOOR_DOM, INTERFACE, needs_node, NODE
from test_interface_lobby import VIEW_EXTRA
from test_interface_scene import FAKE_DOM as SCENE_DOM, run_node as run_pure
from interface_css import stylesheets

JS = INTERFACE / "js"
CSS = stylesheets()
README = INTERFACE / "README.md"
FONTS = INTERFACE / "vendor" / "fonts"
service = st.load("service")


def run_scene_dom(tmp_path: Path, body: str) -> dict:
    """Run `body` under the fake document of the frame's tests (the one the City, the frame and the Escape tests use)."""
    fake = tmp_path / "scene-dom.mjs"
    fake.write_text(SCENE_DOM, encoding="utf-8")
    return run_pure(tmp_path, body.replace("@FAKE@", fake.as_uri()))


def run_view(tmp_path: Path, body: str) -> dict:
    """Run `body` under the fake document of the Floor with what the Lobby's view needs added."""
    fake = tmp_path / "view-dom.mjs"
    fake.write_text(FLOOR_DOM + VIEW_EXTRA, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- row 1, C-1: the City has its own route; M-1 reversed the one-project entry: the City opens first and Escape always goes up -----------

ROUTER = r"""
import * as router from "@JS@/router.js";
import { escapeStep } from "@JS@/frame/escape.js";

const id = "0123456789ab", other = "ba9876543210";
const out = {};
const use = (name, ...args) => (typeof router[name] === "function" ? router[name](...args) : `missing:${name}`);
const brief = (r) => [r.screen, r.project, r.tab, r.pending, r.request === undefined ? "missing" : r.request];
out.city = { parsed: router.parse("#/city").screen, hash: router.cityHash(), up: router.parentHash(router.parse(`#/p/${id}`)), slash: router.parse("#/city/").screen };
// M-1 (reverses D-4 / C-1): no entry rule and no home Building are left in the router
out.removed = [typeof router.entryHash, typeof router.isHomeBuilding];
const building = router.parse(`#/p/${id}`);
const floor = router.parse(`#/p/${id}/floor/engineering`);
out.escape = [escapeStep({ route: building }), escapeStep({ route: building, selection: true }), escapeStep({ route: building, menu: true }),
  escapeStep({ route: floor }), escapeStep({ route: router.parse(`#/p/${id}/lobby`) }), escapeStep({ route: router.parse(`#/p/${id}/control`) }),
  escapeStep({ route: router.parse("#/city") }),
  escapeStep({ route: building, home: true })];     // a stale `home` flag changes nothing: the exception is gone
// M-1: from a Floor the City is two Escapes away, from the Building one
const walk = (route) => { const steps = []; let r = route; while (steps.length < 5) { const s = escapeStep({ route: r }); if (s.step !== "up") break; steps.push(s.hash); r = router.parse(s.hash); } return steps; };
out.walk = { floor: walk(floor), lobby: walk(router.parse(`#/p/${id}/lobby`)), building: walk(building), city: walk(router.parse("#/")) };
out.root = [router.parse("#/").screen, router.parse("").screen, router.parse("#").screen];
// C-2: the segment `request` after the tab is a request, a bare number is still a decision
out.request = {
  route: brief(router.parse(`#/p/${id}/lobby/conversation/request/9`)),
  decision: brief(router.parse(`#/p/${id}/lobby/conversation/9`)),
  onInbox: brief(router.parse(`#/p/${id}/lobby/inbox/request/9`)),
  word: brief(router.parse(`#/p/${id}/lobby/conversation/request/x`)),
  bare: brief(router.parse(`#/p/${id}/lobby/conversation/request`)),
  building: brief(building),
  hash: use("requestHash", id, 9),
  roundTrip: router.parse(String(use("requestHash", id, 9))).request,
};
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_city_has_its_own_route_and_no_entry_rule_sends_a_one_project_service_to_its_building(tmp_path):
    got = run_pure(tmp_path, ROUTER)
    assert got["city"] == {"parsed": "city", "hash": "#/city", "up": "#/city", "slash": "city"}, "C-1: the crumb, Back and Escape lead to #/city"
    assert got["removed"] == ["undefined", "undefined"], "M-1: the router has no entryHash (the one-project entry) and no isHomeBuilding"
    assert got["root"] == ["city", "city", "city"], "M-1: `#/`, an empty hash and `#` are the City; `#/city` stays as an alias of it"
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert not re.search(r"entryHash|isHomeBuilding|location\.replace|\bentered\b|\benter\(", main), "M-1: main.js has no entry rule that replaces the hash"


@needs_node
def test_escape_goes_up_one_level_everywhere_the_building_included_even_with_one_project(tmp_path):
    got = run_pure(tmp_path, ROUTER)
    a = "0123456789ab"
    assert got["escape"] == [
        {"step": "up", "hash": "#/city"}, {"step": "selection"}, {"step": "menu"},
        {"step": "up", "hash": f"#/p/{a}"}, {"step": "up", "hash": f"#/p/{a}"}, {"step": "up", "hash": f"#/p/{a}"},
        {"step": "none"}, {"step": "up", "hash": "#/city"},
    ], "M-1: the Building goes up to the City with one project too (a stale home flag changes nothing); a selection and a menu still close first"
    assert got["walk"] == {"floor": [f"#/p/{a}", "#/city"], "lobby": [f"#/p/{a}", "#/city"], "building": ["#/city"], "city": []}, \
        "M-1: the City is two Escapes from a Floor or the Lobby, one from the Building, and Escape does nothing on the City"


@needs_node
def test_the_request_segment_names_a_request_and_a_bare_number_stays_a_decision(tmp_path):
    got = run_pure(tmp_path, ROUTER)
    a = "0123456789ab"
    r = got["request"]
    assert r["route"] == ["lobby", a, "conversation", None, 9], "the Conversation at request 9, no decision"
    assert r["decision"] == ["lobby", a, "conversation", 9, None], "a number after the tab is a decision, as before"
    assert r["onInbox"][3:] == [None, None] and r["word"][3:] == [None, None] and r["bare"][3:] == [None, None], "only the Conversation takes `request/<n>`, and n is a number"
    assert r["building"][4] is None
    assert r["hash"] == f"#/p/{a}/lobby/conversation/request/9" and r["roundTrip"] == 9


FRAME = r"""
import { FakeNode } from "@FAKE@";
import { createFrame } from "@JS@/frame/frame.js";
import * as router from "@JS@/router.js";

const a = "aaaaaaaaaaaa";
const root = new FakeNode("div");
const frame = createFrame(root, { onSelectProject() {}, onForgetToken() {}, onRetry() {} });
const nodes = () => [...root.walk()];
const back = () => nodes().find((n) => (n.attrs.class || "").includes("wb-back"));
const crumbs = () => nodes().filter((n) => n.tagName === "A" && (n.attrs.class || "") === "wb-crumb").map((n) => n.attrs.href);
document.querySelector = () => null;
document.querySelectorAll = () => [];
const press = (key) => (document.listeners.keydown || []).forEach((fn) => fn({ key, defaultPrevented: false, preventDefault() {} }));
const out = {};
window.location.hash = `#/p/${a}`;
frame.setScreen(router.parse(`#/p/${a}`), { projectName: "northwind-shop", projectId: a });
out.several = { back: back().disabled, crumbs: crumbs() };
back().listeners.click.forEach((fn) => fn({}));
out.severalBack = window.location.hash;
window.location.hash = `#/p/${a}`;
press("Escape");
out.severalEscape = window.location.hash;
window.location.hash = `#/p/${a}`;
frame.setScreen(router.parse(`#/p/${a}`), { projectName: "northwind-shop", projectId: a, home: true });   // a stale flag: it changes nothing (M-1)
out.home = { back: back().disabled, crumbs: crumbs() };
press("Escape");
out.homeEscape = window.location.hash;
frame.setScreen(router.parse(`#/p/${a}/floor/engineering`), { projectName: "northwind-shop", projectId: a, leaf: "Engineering", home: true });
out.floor = { back: back().disabled, crumbs: crumbs() };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_city_crumb_and_back_lead_to_the_city_route_and_back_is_never_disabled_on_the_building(tmp_path):
    got = run_scene_dom(tmp_path, FRAME)
    a = "aaaaaaaaaaaa"
    assert got["several"] == {"back": False, "crumbs": ["#/city"]}, "the City crumb is #/city"
    assert got["severalBack"] == "#/city" and got["severalEscape"] == "#/city", "Back and Escape from the Building lead to #/city"
    assert got["home"] == {"back": False, "crumbs": ["#/city"]}, "M-1: Back is not disabled on the Building of a one-project service; the City is its crumb"
    assert got["homeEscape"] == "#/city", "M-1: Escape on the Building of a one-project service goes up to the City"
    assert got["floor"] == {"back": False, "crumbs": ["#/city", f"#/p/{a}"]}, "a floor of a one-project service still goes up to the Building"


SWITCHER = r"""
import { FakeNode, find, all, text } from "@FAKE@";
import { createSwitcher } from "@JS@/frame/switcher.js";

const calls = [];
const sw = createSwitcher({
  onSelect: (id) => calls.push(["select", id]), onForgetToken: () => calls.push(["forget"]), onOpen() {},
  onAdd: () => calls.push(["add"]), onLeave: (id) => calls.push(["leave", id]),
});
const root = new FakeNode("div");
root.append(sw.el);
const main = () => find(sw.el, ".wb-switch-main");
const project = (id, name) => ({ id, name, accepted: true, badge: 0, sub: "No request is open" });
const out = {};
const tx = (n) => (n ? n.textContent : null);

// one project: the main button is a label (C-1)
sw.update({ projects: [project("a", "northwind-shop")], selectedId: "a", heading: "Projects" });
main().click();
out.one = { tag: main().tagName, title: main().getAttribute("title"), pos: find(sw.el, ".wb-switch-pos") ? tx(find(sw.el, ".wb-switch-pos")) : "", name: tx(find(sw.el, ".wb-switch-name")), calls: calls.slice(), chevron: find(sw.el, ".wb-switch-chevron").disabled };
// two projects: the button cycles as before
sw.update({ projects: [project("a", "northwind-shop"), project("b", "tinykv-docs")], selectedId: "a", heading: "Projects" });
main().click();
out.two = { tag: main().tagName, title: main().getAttribute("title"), pos: tx(find(sw.el, ".wb-switch-pos")), label: main().getAttribute("aria-label"), calls: calls.slice() };

// no project (C-20): the chevron is enabled and the card opens with its foot alone
calls.length = 0;
sw.update({ projects: [], selectedId: null, heading: "Projects" });
const chevron = find(sw.el, ".wb-switch-chevron");
const card = find(sw.el, ".wb-listbox-card");
out.none = { chevron: chevron.disabled, name: tx(find(sw.el, ".wb-switch-name")), closed: card.hidden };
chevron.click();
out.none.open = !card.hidden;
out.none.focus = document.activeElement === find(sw.el, ".wb-forget");
out.none.line = tx(find(sw.el, ".wb-listbox-empty"));
out.none.lineHidden = find(sw.el, ".wb-listbox-empty") ? find(sw.el, ".wb-listbox-empty").hidden : null;
out.none.options = all(sw.el, "[role=option]").length;
out.none.foot = !!find(sw.el, ".wb-forget");
if (find(sw.el, ".wb-forget")) find(sw.el, ".wb-forget").click();
out.none.calls = calls.slice();
(card.listeners.keydown || []).forEach((fn) => fn({ key: "Escape", stopPropagation() {}, preventDefault() {} }));
out.none.closedAgain = card.hidden;
// with projects again the empty line is gone
sw.update({ projects: [project("a", "northwind-shop")], selectedId: "a", heading: "Projects" });
out.back = { lineHidden: find(sw.el, ".wb-listbox-empty") ? find(sw.el, ".wb-listbox-empty").hidden : null, options: all(sw.el, "[role=option]").length };

// R-3, A-35: the foot has three rows with icons; the two that remove are in the error colour; Add and Leave open the frame's command panel
calls.length = 0;
chevron.click();
const foot = find(sw.el, ".wb-listbox-foot");
const rows = all(foot, "button.wb-foot-row");
const iconOf = (r) => find(r, ".wb-icon").cls().find((c) => c.startsWith("wb-icon-"));
out.foot = { rows: rows.map((r) => [tx(r), r.cls().includes("pui-error"), iconOf(r)]), separator: !!find(foot, "[role=separator]"), modeControl: !!find(sw.el, "[role=radiogroup]") };
rows[0].click();
out.foot.afterAdd = [calls.slice(), card.hidden];
chevron.click();
rows[1].click();
out.foot.afterLeave = [calls.slice(), card.hidden];
sw.update({ projects: [], selectedId: null, heading: "Projects" });
out.foot.leaveWithNone = find(sw.el, ".wb-leave-row").disabled;
sw.update({ projects: [project("a", "northwind-shop"), project("b", "tinykv-docs")], selectedId: "b", heading: "Projects" });
const options = all(sw.el, "[role=option]");
out.options = options.map((o) => [o.cls().includes("is-selected"), find(o, ".wb-check").cls().includes("is-on"), find(o, ".wb-check").cls().includes("pui-success"), o.children.map((c) => c.cls().find((x) => x.startsWith("wb-option-text") || x.startsWith("pui-badge") || x.startsWith("wb-check")))]);
out.swap = [!!find(main(), ".wb-switch-swap .wb-icon-arrow-left-right")];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_switcher_main_button_is_a_label_with_one_project_and_the_foot_opens_with_none(tmp_path):
    got = run_view(tmp_path, SWITCHER)
    one = got["one"]
    assert one["tag"] != "BUTTON" and one["title"] is None and one["pos"] == "" and one["name"] == "northwind-shop", "C-1: a label: no title, no place 1/1"
    assert one["calls"] == [], "a click on the label chooses nothing"
    two = got["two"]
    assert two["tag"] == "BUTTON" and two["title"] == "Go to the next project" and two["pos"] == "1/2"
    assert two["label"] == "northwind-shop, project 1 of 2, go to the next project" and two["calls"] == [["select", "b"]], "two projects: the button cycles as before"
    none = got["none"]
    assert none["chevron"] is False and none["name"] == "No project" and none["closed"] is True, "C-20: the chevron stays enabled"
    assert none["open"] is True and none["focus"] is True, "the card opens with the foot, and the foot has the keyboard focus"
    assert none["line"] == "No project" and none["lineHidden"] is False and none["options"] == 0 and none["foot"] is True
    assert none["calls"] == [["forget"]], "Forget the token is reachable with no project"
    assert none["closedAgain"] is True, "Escape closes the card"
    assert got["back"] == {"lineHidden": True, "options": 1}, "with a project the empty line goes"


@needs_node
def test_the_switchers_foot_has_three_rows_with_icons_that_open_the_command_panel_and_the_selected_row_has_a_check(tmp_path):
    got = run_view(tmp_path, SWITCHER)
    foot = got["foot"]
    assert foot["rows"] == [["Add a project\u2026", False, "wb-icon-folder-plus"], ["Leave this project\u2026", True, "wb-icon-folder-minus"], ["Forget the token", True, "wb-icon-key-round"]], \
        "R-3, A-35: the foot's rows have their icons; the two that remove (Leave, Forget) are in the error colour"
    assert foot["separator"] is True and foot["modeControl"] is False, "R-4: the colour mode is not in the foot any more"
    assert foot["afterAdd"] == [[["add"]], True] and foot["afterLeave"] == [[["add"], ["leave", "a"]], True], "Add and Leave close the card and open the command panel; Leave acts on the project the switcher shows"
    assert foot["leaveWithNone"] is True, "with no project there is nothing to leave"
    assert got["options"][0][:3] == [False, False, True] and got["options"][1][:3] == [True, True, True], "R-3: the selected row has the check in a soft success box at its end"
    assert got["options"][1][3] == ["wb-option-text", "pui-badge", "wb-check"], "the row is the name, the badge, then the check"
    assert got["swap"] == [True], "R-3: the main button ends in a swap icon"


# --- row 11, D-2: the preference, the module that keeps it and the scene that follows ---------------------------------------------

MODE = r"""
import * as mode from "@JS@/mode.js";
import { FakeNode, find, all } from "@FAKE@";
import { createModeButton } from "@JS@/frame/mode-button.js";

// nothing is stored: any touch of a store of the browser fails this run
const touched = [];
for (const name of ["localStorage", "sessionStorage"]) Object.defineProperty(globalThis, name, { get() { touched.push(name); throw new Error("storage touched"); } });
const makeRoot = () => ({ attrs: {}, setAttribute(n, v) { this.attrs[n] = v; }, removeAttribute(n) { delete this.attrs[n]; }, getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; } });
const root = makeRoot();
const out = { order: mode.ORDER, attr: mode.ATTRIBUTE, words: mode.WORDS, icons: mode.ICON_OF };
out.init = [mode.initMode({ root }), { ...root.attrs }, mode.currentMode(root)];
out.cycle = [1, 2, 3, 4].map(() => [mode.cycleMode({ root }), { ...root.attrs }, mode.currentMode(root)]);
out.next = [mode.nextMode("system"), mode.nextMode("light"), mode.nextMode("dark"), mode.nextMode("purple"), mode.nextMode(undefined)];
out.set = [mode.setMode("dark", { root }), { ...root.attrs }, mode.setMode("purple", { root }), { ...root.attrs }];
const stale = makeRoot();
stale.attrs["data-pui-mode"] = "dark";
out.stale = [mode.initMode({ root: stale }), { ...stale.attrs }];
const heard = [];
const stop = mode.onMode((m) => heard.push(m));
mode.setMode("light", { root });
stop();
mode.setMode("dark", { root });
out.heard = heard;

// the button: one control, the icon of the chosen mode, the name of the mode, a click cycles; two buttons follow each other
document.documentElement = new FakeNode("html");
mode.initMode();
const one = createModeButton();
const two = createModeButton();
const shown = (b) => [b.el.getAttribute("data-choice"), b.el.getAttribute("aria-label"), b.el.getAttribute("title")];
out.button = { tag: one.el.tagName, type: one.el.attrs.type, initial: shown(one), icons: all(one.el, ".wb-mode-icon").map((n) => [n.attrs["data-icon"], find(n, ".wb-icon").cls().find((c) => c.startsWith("wb-icon-"))]) };
one.el.click();
out.button.afterOne = [shown(one), shown(two), document.documentElement.getAttribute("data-pui-mode")];
one.el.click();
out.button.afterTwo = [shown(one), document.documentElement.getAttribute("data-pui-mode")];
one.el.click();
out.button.afterThree = [shown(one), document.documentElement.getAttribute("data-pui-mode")];
one.destroy();
two.el.click();
out.button.afterDestroy = [shown(one)[0], shown(two)[0]];
out.touched = touched;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_mode_module_cycles_system_light_dark_on_the_library_attribute_and_stores_nothing(tmp_path):
    got = run_node(tmp_path, MODE)
    assert got["order"] == ["system", "light", "dark"] and got["attr"] == "data-pui-mode" and got["words"] == {"system": "System", "light": "Light", "dark": "Dark"}
    assert got["icons"] == {"system": "monitor", "light": "sun", "dark": "moon"}, "R-4: the icon says which"
    assert got["init"] == ["system", {}, "system"], "System is the default: no attribute, the system decides"
    assert got["cycle"] == [["light", {"data-pui-mode": "light"}, "light"], ["dark", {"data-pui-mode": "dark"}, "dark"], ["system", {}, "system"], ["light", {"data-pui-mode": "light"}, "light"]], \
        "R-4: a click goes System, Light, Dark, System; System removes the attribute"
    assert got["next"] == ["light", "dark", "system", "light", "light"], "a word that is not a mode is read as System"
    assert got["set"] == ["dark", {"data-pui-mode": "dark"}, "system", {}]
    assert got["stale"] == ["system", {}], "the page starts on System, whatever the root held"
    assert got["heard"] == ["light"], "a listener hears the mode applied until it stops"
    assert got["touched"] == [], "R4D-3, R-4: nothing is stored: no read or write of a browser store"
    button = got["button"]
    assert button["tag"] == "BUTTON" and button["type"] == "button" and button["initial"] == ["system", "Colour mode: System", "Colour mode: System"]
    assert button["icons"] == [["system", "wb-icon-monitor"], ["light", "wb-icon-sun"], ["dark", "wb-icon-moon"]]
    assert button["afterOne"] == [["light", "Colour mode: Light", "Colour mode: Light"], ["light", "Colour mode: Light", "Colour mode: Light"], "light"], "the second button follows the first"
    assert button["afterTwo"] == [["dark", "Colour mode: Dark", "Colour mode: Dark"], "dark"]
    assert button["afterThree"] == [["system", "Colour mode: System", "Colour mode: System"], None]
    assert button["afterDestroy"] == ["system", "light"], "a destroyed button stops following"


PALETTE = r"""
import { watchScheme } from "@JS@/scene/palette.js";

const query = { handlers: [], addEventListener(type, fn) { this.handlers.push([type, fn]); }, removeEventListener(type, fn) { this.handlers = this.handlers.filter((h) => h[1] !== fn); } };
const seen = { observe: null, disconnected: false, callback: null };
class Observer { constructor(callback) { seen.callback = callback; } observe(element, options) { seen.observe = [element === root, options]; } disconnect() { seen.disconnected = true; } }
const root = {};
const out = {};
let changes = 0;
const stop = watchScheme(() => { changes += 1; }, { query, root, Observer });
out.registered = query.handlers.map((h) => h[0]);
query.handlers.forEach(([, fn]) => fn());
seen.callback([{ attributeName: "data-pui-mode" }]);
out.changes = changes;
out.observe = seen.observe;
stop();
out.after = [query.handlers.length, seen.disconnected];
// no observer in the environment: the media query alone
const q2 = { handlers: [], addEventListener(type, fn) { this.handlers.push(fn); }, removeEventListener() { this.handlers = []; } };
let n2 = 0;
const stop2 = watchScheme(() => { n2 += 1; }, { query: q2, root, Observer: null });
q2.handlers.forEach((fn) => fn());
stop2();
out.noObserver = [n2, q2.handlers.length];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_scene_reads_its_palette_again_when_the_mode_attribute_or_the_system_scheme_changes(tmp_path):
    got = run_pure(tmp_path, PALETTE)
    assert got["registered"] == ["change"] and got["changes"] == 2, "the media query and the attribute both ask for a new palette"
    assert got["observe"] == [True, {"attributes": True, "attributeFilter": ["data-pui-mode"]}], "only the library's attribute on the root element"
    assert got["after"] == [0, True], "stopping takes both listeners away"
    assert got["noObserver"] == [1, 0]
    engine = (JS / "scene" / "engine.js").read_text(encoding="utf-8")
    assert "watchScheme" in engine and "darkQuery" not in engine, "the engine follows the scheme through the palette's watcher"


def test_no_module_of_the_page_touches_local_storage_and_the_mode_module_keeps_nothing():
    mode = (JS / "mode.js").read_text(encoding="utf-8")
    assert not re.search(r"Storage|document\.cookie|openhora-mode", mode), "R4D-3, R-4: the colour mode is not stored: no storage, no cookie, no key"
    for path in sorted(JS.rglob("*.js")):
        assert "localStorage" not in path.read_text(encoding="utf-8"), f"{path.name}: no module of the page touches localStorage (the colour mode's exception of ADJ-B1 is gone)"
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert re.search(r'import \{[^}]*\binitMode\b[^}]*\} from "\./mode\.js";', main) and "initMode()" in main, "the page starts on System when it starts"
    assert not re.search(r"perfectui/js/mode", "".join(p.read_text(encoding="utf-8") for p in INTERFACE.glob("*.html") if p.name != "")), "the library's cookie helper is not loaded"
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert "mode.js" not in html


# --- row 7, C-22: the phone's list dialog follows the reloads ----------------------------------------------------------------------

DIALOG = r"""
import { FakeNode, find, all, text } from "@FAKE@";
window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} });
const { createFrame } = await import("@JS@/frame/frame.js");

const root = new FakeNode("div");
const frame = createFrame(root, { onSelectProject() {}, onForgetToken() {}, onRetry() {} });
const row = (id, title) => ({ project: "p", id, kind: "Question", title, where: "northwind-shop · Lobby", link: `#/p/p/lobby/inbox/${id}`, createdAt: `2026-10-09T0${id}:00:00Z`, age: "now", name: `Question, ${title}` });
const dialog = frame.sheet.el;
const links = () => all(dialog, "a.wb-wait-row").map((a) => a.attrs.href);
const out = {};
frame.waitingMenu.set([row(1, "one"), row(2, "two"), row(3, "three")], "ready");
frame.waitingMenu.button.click();
out.opened = { open: dialog.open, links: links() };
// the focus is on the second row; a reload brings one row fewer, the focused row still there
find(dialog, "a.wb-wait-row[href=\"#/p/p/lobby/inbox/2\"]").focus();
frame.waitingMenu.set([row(2, "two"), row(3, "three")], "ready");
out.sameRows = { links: links(), focus: document.activeElement && document.activeElement.attrs.href, connected: dialog.contains(document.activeElement) };
// the row that had the focus is resolved: it leaves, the dialog keeps a focus inside it
frame.waitingMenu.set([row(3, "three")], "ready");
out.resolved = { links: links(), inside: dialog.contains(document.activeElement) };
// every row resolved: the empty sentence
frame.waitingMenu.set([], "ready");
out.empty = { links: links(), words: all(dialog, ".wb-empty").map(text), title: text(find(dialog, ".wb-sheet-title")) };
// a row arrives while it is open
frame.waitingMenu.set([row(4, "four")], "ready");
out.arrived = links();
// closed: a reload does not open it again, and the next opening shows the rows of that moment
dialog.close();
frame.waitingMenu.set([row(5, "five"), row(6, "six")], "ready");
out.closed = { open: dialog.open, links: links() };
frame.waitingMenu.button.click();
out.reopened = links();
// a list the dialog shows for another purpose (the steps of a request) is not replaced by the waiting rows
dialog.close();
frame.sheet.open("Request 7, Spring", find(root, ".wb-empty") || new FakeNode("p"), null);
frame.waitingMenu.set([row(7, "seven")], "ready");
out.steps = { title: text(find(dialog, ".wb-sheet-title")), links: links() };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_waiting_list_dialog_of_a_phone_is_redrawn_while_open_and_keeps_the_focus_where_the_row_still_is(tmp_path):
    got = run_view(tmp_path, DIALOG)
    r = lambda i: f"#/p/p/lobby/inbox/{i}"
    assert got["opened"] == {"open": True, "links": [r(1), r(2), r(3)]}
    assert got["sameRows"] == {"links": [r(2), r(3)], "focus": r(2), "connected": True}, "C-22: a resolved row leaves; the focus stays on the row that is still there"
    assert got["resolved"]["links"] == [r(3)] and got["resolved"]["inside"] is True, "the focus does not fall out of the open dialog"
    assert got["empty"] == {"links": [], "words": ["Nothing waits for you."], "title": "Waiting for you"}
    assert got["arrived"] == [r(4)]
    assert got["closed"] == {"open": False, "links": [r(4)]}, "a closed dialog is not opened or redrawn by a reload"
    assert got["reopened"] == [r(5), r(6)]
    assert got["steps"]["title"] == "Request 7, Spring" and got["steps"]["links"] == [], "another list in the dialog is left alone"


# --- row 2, C-2: the request line's route, the plan row that opens it, the Lobby's Desk ---------------------------------------------

WAITING = r"""
import * as model from "@JS@/model.js";

const a = "0123456789ab", b = "ba9876543210";
const NOW = new Date("2026-10-09T12:00:00Z");
const item = (id, kind, task_id, agent, created) => ({ id, kind, title: `${kind} ${id}`, task_id, agent, created_at: created });
const snapshot = { loaded: true, projects: [{ id: a, name: "northwind-shop", config: { accepted: true } }, { id: b, name: "tinykv-docs", config: { accepted: true } }], tasks: {},
  details: {
    [a]: { agents: [], status: { requests: [], pending: [
      item(1, "plan", 14, null, "2026-10-09T08:00:00Z"), item(2, "question", 14, null, "2026-10-09T08:01:00Z"), item(3, "plan", 15, "planning", "2026-10-09T08:02:00Z"),
      item(4, "review", 7, "engineering", "2026-10-09T08:03:00Z"), item(5, "plan", null, null, "2026-10-09T08:04:00Z"), item(6, "acceptance", 14, null, "2026-10-09T08:05:00Z") ] } },
    [b]: { agents: [], status: { requests: [], pending: [ item(1, "plan", 3, null, "2026-10-09T09:00:00Z") ] } } } };
const rows = model.waitingRows(snapshot, NOW);
console.log(JSON.stringify(rows.map((r) => [r.project === a ? "a" : "b", r.id, r.link])));
"""


@needs_node
def test_the_waiting_row_of_a_plan_opens_the_request_line_and_every_other_row_opens_where_it_did(tmp_path):
    got = run_pure(tmp_path, WAITING)
    a, b = "0123456789ab", "ba9876543210"
    rows = {(p, i): link for p, i, link in got}
    assert rows[("a", 1)] == f"#/p/{a}/lobby/conversation/request/14", "J-6: a plan opens the Conversation at its request's line"
    assert rows[("a", 3)] == f"#/p/{a}/lobby/conversation/request/15", "a plan marked as the planning agent's is the same"
    assert rows[("b", 1)] == f"#/p/{b}/lobby/conversation/request/3"
    assert rows[("a", 2)] == f"#/p/{a}/lobby/inbox/2", "a question stays in the Inbox"
    assert rows[("a", 6)] == f"#/p/{a}/lobby/inbox/6", "an acceptance stays in the Inbox"
    assert rows[("a", 4)] == f"#/p/{a}/floor/engineering/inbox/4", "a floor's decision opens its floor"
    assert rows[("a", 5)] == f"#/p/{a}/lobby/inbox/5", "a plan with no request number has nothing to open"


DESK = r"""
import { FakeNode, find, all, text, settle } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createDeskTab, NONE_OF_ITS_OWN } from "@JS@/floor/desk-tab.js";
import { lobbyDocuments } from "@JS@/views/lobby-model.js";
import { createLobbyDesk } from "@JS@/views/lobby-desk.js";

setToken("t".repeat(40));
const P = "0123456789ab";
const rows = [
  { path: "docs/a.md", owner: "eng-docs", agent: "engineering", size: 12, modified_at: "2026-10-09T09:00:00Z", kind: "markdown", bound: false },
  { path: "docs/b.md", owner: null, agent: null, size: 30, modified_at: "2026-10-09T08:00:00Z", kind: "markdown", bound: false },
  { path: "docs/c.md", owner: "brand-name", agent: "brand", size: 5, modified_at: "2026-10-09T07:00:00Z", kind: "text", bound: false },
  { path: "docs/d.md", owner: "biz-icp", agent: "planning", size: 5, modified_at: "2026-10-09T06:00:00Z", kind: "text", bound: false },
];
const out = {};
out.all = lobbyDocuments(rows).map((d) => d.path);
out.junk = [lobbyDocuments(undefined), lobbyDocuments(null), lobbyDocuments([null, { path: "x", agent: null }]).length];

// the desk table: the Lobby's has the Agent column after the owner skill, a floor's keeps its four
const heads = (tab) => all(tab.el, "th").map(text);
const floorTab = createDeskTab({ project: P, agent: "engineering", open() {} });
floorTab.update({ documents: rows.slice(0, 1), truncated: false, loading: false, error: null });
out.floor = { heads: heads(floorTab), cells: all(floorTab.el, "td").map((c) => c.attrs["data-label"]) };
const lobbyTab = createDeskTab({ project: P, agent: "planning", open() {}, agentColumn: true });
lobbyTab.update({ documents: rows, truncated: false, loading: false, error: null });
out.lobby = { heads: heads(lobbyTab), agents: all(lobbyTab.el, "td").filter((c) => c.attrs["data-label"] === "Agent").map(text), rows: all(lobbyTab.el, "tr.wb-desk-row").length };

// the filter still matches the owner skill and the path; the agent is a column, not a filter key
lobbyTab.el.querySelector("input").value = "brand";
(lobbyTab.el.querySelector("input").listeners.input || []).forEach((fn) => fn());
out.filtered = all(lobbyTab.el, "tr.wb-desk-row").length;

// the sentence of a floor with none of its own
out.sentence = NONE_OF_ITS_OWN;
floorTab.update({ documents: [], truncated: false, loading: false, error: null, elsewhere: 3 });
out.floorEmpty = all(floorTab.el, ".wb-state-block").map(text);

// the Lobby's desk reads every document of the project
globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => ({ artifacts: rows, truncated: false }) });
let changed = 0;
const desk = createLobbyDesk({ project: P, open() {}, changed: () => { changed += 1; } });
desk.update({ tab: "desk", ready: true });
await settle();
out.lobbyDesk = { rows: desk.rows().map((d) => d.path), table: all(desk.el, "tr.wb-desk-row").length, heads: heads(desk), changed: changed > 0 };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_lobby_desk_lists_every_document_with_the_agent_after_the_owner_skill_and_a_floor_keeps_its_own(tmp_path):
    got = run_node(tmp_path, DESK)
    assert got["all"] == ["docs/a.md", "docs/b.md", "docs/c.md", "docs/d.md"], "C-2: the filter by agent is gone"
    assert got["junk"] == [[], [], 1], "an unread list is empty, and a row that is not an object is dropped"
    assert got["floor"]["heads"] == ["Path", "Owner skill", "Size", "Modified"], "a floor's table is as it was"
    assert got["lobby"]["heads"] == ["Path", "Owner skill", "Agent", "Size", "Modified"]
    assert got["lobby"]["agents"] == ["engineering", "—", "brand", "planning"], "the agent of the row as the service gave it, a dash when null (rows are newest first)"
    assert got["lobby"]["rows"] == 4 and got["filtered"] == 1
    assert got["sentence"] == "No documents of this agent. Every document is on the Lobby's desk."
    assert got["floorEmpty"] == [got["sentence"]]
    assert got["lobbyDesk"]["rows"] == ["docs/a.md", "docs/b.md", "docs/c.md", "docs/d.md"] and got["lobbyDesk"]["table"] == 4
    assert got["lobbyDesk"]["heads"] == ["Path", "Owner skill", "Agent", "Size", "Modified"] and got["lobbyDesk"]["changed"] is True


REQUEST_ROUTE = r"""
import { FakeNode, find, all, text, settle } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createLobbyView } from "@JS@/views/lobby.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = (type, fn) => { document.listeners[type] = (document.listeners[type] || []).filter((f) => f !== fn); };
const scrolled = [];
FakeNode.prototype.scrollIntoView = function (options) { scrolled.push([this.attrs.id || this.attrs.class, options || null]); };
const P = "0123456789ab";
const NOW = new Date("2026-10-09T12:00:00Z");
const sent = [];
const flows = [{ flow: "design", title: "Design" }, { flow: "broken", error: "no" }, { flow: "brand", title: "Brand of a product" }];
globalThis.fetch = async (url, init) => {
  sent.push({ method: init.method, url, body: init.body === undefined ? null : JSON.parse(init.body) });
  let body = {};
  if (url.includes("/conversation")) body = { messages: [] };
  else if (url.endsWith("/flows")) body = { flows };
  else if (/\/tasks\/\d+$/.test(url)) body = { task: { id: Number(url.split("/").pop()) }, runs: [], pending: [] };
  else if (url.endsWith("/route")) return { ok: true, status: 202, json: async () => ({ job: 7 }) };
  else if (url.includes("/jobs/7")) body = { job: 7, state: "done", result: { routed: true } };
  return { ok: true, status: 200, json: async () => body };
};
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0 });
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("planning")], status: { requests: [{ id: 2, title: "Sale page", state: "requested", tasks: [] }, { id: 3, title: "Docs page", state: "requested", tasks: [] }], pending: [] } } } };
const frame = { el: new FakeNode("div"), main: new FakeNode("main"), sceneHost: new FakeNode("div"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), sceneUnavailable() {}, announce() {},
  acquireWorld: () => ({ show() {}, setOptions() {}, flyTo: () => Promise.resolve(false), stats() { return {}; } }), kpis: { el: new FakeNode("div") } };
const route = (rest) => router.parse(`#/p/${P}/lobby${rest}`);
const view = createLobbyView(frame, { project: P, onChanged: async () => {} });
const out = {};

// the route names request 3: the Conversation opens at its line and the focus is on its title
view.update({ snapshot, route: route("/conversation/request/3"), now: NOW, projectName: "northwind-shop" });
await settle();
const block = (id) => find(frame.main, `#wb-request-${id}`);
out.ids = [block(2) !== null, block(3) !== null];
const titleOf = (id) => (block(id) ? block(id).querySelector(".wb-lobby-request-title") : null);
out.focus = [titleOf(3) !== null && document.activeElement === titleOf(3), titleOf(2) !== null && document.activeElement === titleOf(2)];
out.scrolled = scrolled.map((s) => s[0]);
out.title = titleOf(3) ? titleOf(3).attrs["aria-label"] : null;
// a draw that builds the block again (its title changed) keeps the focus on the new title
const renamed = { ...snapshot, details: { [P]: { ...snapshot.details[P], status: { requests: [{ id: 2, title: "Sale page", state: "requested", tasks: [] }, { id: 3, title: "Docs page, renamed", state: "requested", tasks: [] }], pending: [] } } } };
view.update({ snapshot: renamed, route: route("/conversation/request/3"), reload: 1, now: NOW, projectName: "northwind-shop" });
await settle();
out.rebuilt = [titleOf(3) !== null ? titleOf(3).attrs["aria-label"] : null, titleOf(3) !== null && document.activeElement === titleOf(3)];
// a reload with the same route does not take the focus again
document.activeElement = null;
view.update({ snapshot, route: route("/conversation/request/3"), reload: 1, now: NOW, projectName: "northwind-shop" });
await settle();
out.again = [document.activeElement === null, scrolled.length];
// another request: the focus follows
view.update({ snapshot, route: route("/conversation/request/2"), reload: 1, now: NOW, projectName: "northwind-shop" });
await settle();
out.second = [titleOf(2) !== null && document.activeElement === titleOf(2), scrolled.map((s) => s[0]).slice(-1)[0]];
// a request that is not there: nothing moves and nothing breaks
document.activeElement = null;
view.update({ snapshot, route: route("/conversation/request/99"), reload: 1, now: NOW, projectName: "northwind-shop" });
await settle();
out.missing = document.activeElement === null;
// the plain Conversation route does not move the focus
view.update({ snapshot, route: route("/conversation"), reload: 1, now: NOW, projectName: "northwind-shop" });
await settle();
out.plain = document.activeElement === null;
view.dispose();
console.log(JSON.stringify(out));
process.exit(0);
"""


# --- row 9, E-20: the flow beside "Route it" ---------------------------------------------------------------------------------------

ROUTE_BLOCK = r"""
import { FakeNode, find, all, text, settle } from "@FAKE@";
import { createBlock } from "@JS@/views/lobby-request.js";

const NOW = new Date("2026-10-09T12:00:00Z");
const flows = [{ flow: "design", title: "Design" }, { flow: "broken", error: "no" }, { flow: "brand", title: "Brand of a product" }, { flow: "plain" }];
const routed = [];
const kept = [];
const make = (extra = {}) => createBlock({ api: {}, project: "p1", request: { id: 20, title: "From the form", state: "requested", tasks: [] }, body: { pending: [] }, open: 0, now: NOW,
  onChanged: async () => {}, onCancel() {}, onRoute: (request, flow) => routed.push([request.id, flow]), routing: false, flows, ...extra });
const out = {};
const block = make();
const select = find(block.el, "select.wb-route-flow") || new FakeNode("select");
out.options = all(select, "option").map((o) => [o.attrs.value, text(o)]);
out.label = [select.attrs["aria-label"] || null, find(block.el, "button.wb-route-button").attrs["aria-label"]];
out.order = [...find(block.el, ".wb-lobby-request-line").walk()].filter((n) => /wb-route-flow|wb-route-button/.test(n.attrs.class || "")).map((n) => n.attrs.class.split(" ").pop());
find(block.el, "button.wb-route-button").click();           // the first option: the planning agent routes it
select.value = "brand";
(select.listeners.change || []).forEach((fn) => fn());
find(block.el, "button.wb-route-button").click();
out.routed = routed.slice();
// a block built again by a reload is given the choice back
const again = make({ flow: "design", onFlow: (value) => kept.push(value) });
out.restored = find(again.el, "select.wb-route-flow") ? find(again.el, "select.wb-route-flow").value : null;
const s2 = find(again.el, "select.wb-route-flow") || new FakeNode("select");
s2.value = "brand";
(s2.listeners.change || []).forEach((fn) => fn());
out.kept = kept.slice();
// not shown: the flows are not read yet or the project has none, the flow is remembered from the form, the request is routing, the request is not waiting for a route
out.none = [find(make({ flows: null }).el, "select.wb-route-flow") === null, find(make({ flows: [] }).el, "select.wb-route-flow") === null,
  find(make({ flows: [{ flow: "x", error: "no" }] }).el, "select.wb-route-flow") === null];
const remembered = make({ remembered: "design" });
out.remembered = find(remembered.el, "select.wb-route-flow") === null;
find(remembered.el, "button.wb-route-button").click();
out.rememberedRoute = routed.slice(-1)[0];
const busy = find(make({ routing: true }).el, "select.wb-route-flow");
out.routing = busy === null || "disabled" in busy.attrs;
const running = createBlock({ api: {}, project: "p1", request: { id: 21, title: "Running", state: "running", tasks: [] }, body: { pending: [] }, open: 0, now: NOW, onChanged: async () => {}, onCancel() {}, onRoute() {}, routing: false, flows });
out.notWaiting = find(running.el, "select.wb-route-flow") === null && find(running.el, "button.wb-route-button") === null;
console.log(JSON.stringify(out));
process.exit(0);
"""


ROUTE_VIEW = r"""
import { FakeNode, find, all, text, settle } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createLobbyView } from "@JS@/views/lobby.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = (type, fn) => { document.listeners[type] = (document.listeners[type] || []).filter((f) => f !== fn); };
const P = "0123456789ab";
const NOW = new Date("2026-10-09T12:00:00Z");
const sent = [];
globalThis.fetch = async (url, init) => {
  sent.push({ method: init.method, url, body: init.body === undefined ? null : JSON.parse(init.body) });
  let body = {};
  if (url.includes("/conversation")) body = { messages: [] };
  else if (url.endsWith("/flows")) body = { flows: [{ flow: "design", title: "Design" }] };
  else if (/\/tasks\/\d+$/.test(url)) body = { task: { id: 2 }, runs: [], pending: [] };
  else if (url.endsWith("/route")) return { ok: true, status: 202, json: async () => ({ job: 7 }) };
  else if (url.includes("/jobs/7")) body = { job: 7, state: "done", result: { routed: true } };
  return { ok: true, status: 200, json: async () => body };
};
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0 });
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("planning")], status: { requests: [{ id: 2, title: "Sale page", state: "requested", tasks: [] }], pending: [] } } } };
const makeFrame = () => ({ el: new FakeNode("div"), main: new FakeNode("main"), sceneHost: new FakeNode("div"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), sceneUnavailable() {}, announce() {},
  acquireWorld: () => ({ show() {}, setOptions() {}, flyTo: () => Promise.resolve(false), stats() { return {}; } }), kpis: { el: new FakeNode("div") } });
const bodies = () => sent.filter((s) => s.method === "POST" && s.url.endsWith("/requests/2/route")).map((s) => s.body);
const out = {};
for (const choose of [null, "design"]) {
  sent.length = 0;
  const frame = makeFrame();
  const view = createLobbyView(frame, { project: P, onChanged: async () => {} });
  view.update({ snapshot, route: router.parse(`#/p/${P}/lobby`), now: NOW, projectName: "northwind-shop" });
  await settle();
  const select = find(frame.main, "select.wb-route-flow");
  out[`select${choose}`] = select ? all(select, "option").map((o) => o.attrs.value) : null;
  if (choose && select) {
    select.value = choose;
    (select.listeners.change || []).forEach((fn) => fn());
  }
  find(frame.main, "button.wb-route-button").click();
  await settle();
  out[`sent${choose}`] = bodies();
  out[`text${choose}`] = sent.filter((s) => s.url.endsWith("/requests")).length;
  view.dispose();
}
console.log(JSON.stringify(out));
process.exit(0);
"""


# --- row 3, C-17: a file is handed over in two steps -----------------------------------------------------------------------------

HAND_CARD = r"""
import { FakeNode, settle, find, all, textOf } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";

const calls = [];
const client = { answer: async () => ({}), release: async () => ({}), handOver: async (...args) => { calls.push(args.slice(0, 3)); return { path: "docs/inputs/logo.png", bytes: 3 }; } };
const env = (extra = {}) => ({ project: "p", now: () => new Date("2026-10-09T12:00:00Z"), api: client, requestIds: new Set([6]), links: { floor: () => "#", lobby: () => "#/p/p/lobby", open: () => "#" }, reread: async () => null, changed() {}, gone() {}, ...extra });
const review = { id: 42, kind: "review", title: "R", body: "b", payload: { returned: [], kept: [] }, payload_sha256: null, status: "open", actions: ["released", "answered"], agent: "brand", task_id: 5, run_id: 4, created_at: "2026-10-09T09:00:00Z" };
const card = createCard(review, env({ task: async (id) => ({ task: { id }, runs: [], pending: [], drop: { web: true, takes: true, line: "this file will be visible to a run with the open network" } }) }));
await settle();
const hand = () => find(card.el, ".wb-card-hand");
const out = {};
const tx = (n) => (n ? n.textContent : null);
const input = () => find(card.el, "input.wb-file");
const file = { name: "logo.png", size: 3, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
out.before = { button: all(hand(), "button.wb-hand-button").length, chosen: all(hand(), ".wb-hand-chosen").length };
input().files = [file];
input().listeners.change.forEach((fn) => fn());
await settle();
out.afterChange = { calls: calls.length, chosen: tx(find(card.el, ".wb-hand-chosen")), button: tx(find(card.el, "button.wb-hand-button")), name: find(card.el, "button.wb-hand-button") ? find(card.el, "button.wb-hand-button").attrs["aria-label"] : null, line: tx(find(hand(), ".wb-drop-line")) };
if (find(card.el, "button.wb-hand-button")) find(card.el, "button.wb-hand-button").click();
await settle();
out.afterButton = { calls: calls.slice(), result: tx(find(card.el, ".wb-card-hand .wb-card-line")), button: all(card.el, "button.wb-hand-button").length, chosen: all(card.el, ".wb-hand-chosen").length };

// a name the service would refuse is said at once and no button is offered
input().files = [{ name: "bad name.png", size: 3, arrayBuffer: async () => new ArrayBuffer(3) }];
input().listeners.change.forEach((fn) => fn());
await settle();
out.bad = { text: tx(find(card.el, ".wb-card-hand .wb-notice-card")), button: all(card.el, "button.wb-hand-button").length, calls: calls.length };
// a file chosen and then another: the button names the last
input().files = [file];
input().listeners.change.forEach((fn) => fn());
await settle();
input().files = [{ name: "second.png", size: 3, arrayBuffer: async () => new Uint8Array([4, 5, 6]).buffer }];
input().listeners.change.forEach((fn) => fn());
await settle();
out.second = tx(find(card.el, ".wb-hand-chosen"));
if (find(card.el, "button.wb-hand-button")) find(card.el, "button.wb-hand-button").click();
await settle();
out.secondCalls = calls.slice(1).map((c) => [c[1], c[2]]);
// a failure leaves the file chosen so that the button can be pressed again
const failing = { ...client, handOver: async () => { throw Object.assign(new Error("The file is too large for this task."), { name: "ApiError", status: 413, word: "refused" }); } };
const card2 = createCard({ ...review, id: 43 }, env({ api: failing, task: async (id) => ({ task: { id }, runs: [], pending: [], drop: { web: false, takes: true, line: null } }) }));
await settle();
const input2 = find(card2.el, "input.wb-file");
input2.files = [file];
input2.listeners.change.forEach((fn) => fn());
await settle();
if (find(card2.el, "button.wb-hand-button")) find(card2.el, "button.wb-hand-button").click();
await settle();
out.failed = { text: tx(find(card2.el, ".wb-card-hand .wb-notice-card")), button: all(card2.el, "button.wb-hand-button").length, chosen: tx(find(card2.el, ".wb-hand-chosen")) };
console.log(JSON.stringify(out));
process.exit(0);
"""


HAND_TAB = r"""
import { FakeNode, settle, find, all, textOf } from "@FAKE@";
import * as fm from "@JS@/floor-model.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";

const P = "0123456789ab";
const NOW = new Date("2026-10-09T12:00:00Z");
const calls = [];
const api = { handOver: async (...args) => { calls.push(args.slice(0, 3)); return { path: "docs/inputs/logo.png", bytes: 3 }; }, retry: async () => ({}), goAhead: async () => ({}), setMode: async () => ({}) };
const agent = { name: "design", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0, wider: [] };
const task = (id, state, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "design-system", state, note: null, agent: "design", requestId: 2, waiting_for: [], ...extra });
const drop = { web: true, takes: true, line: "this file will be visible to a run with the open network" };
const view = (tasks) => fm.floor({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 2, title: "R", state: "planned", tasks }], pending: [], held: [] }, agents: [agent] } }, tasks: {}, loaded: true }, P, "design",
  Object.fromEntries(tasks.map((t) => [t.id, { task: { id: t.id }, runs: [], pending: [], drop }])));
const tab = createAgentTab({ project: P, agent: "design", api, refresh() {}, now: () => NOW, task: async (id) => ({ task: { id }, drop: { web: true, takes: true, line: "this file will be visible to a run with the open network" } }) });
tab.update(view([task(11, "blocked", { note: "n" })]));
await settle();
const hand = () => find(tab.el, ".wb-hand");
const input = () => find(hand(), "input.wb-file");
const file = { name: "logo.png", size: 3, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
const out = {};
const tx = (n) => (n ? n.textContent : null);
out.before = all(hand(), "button.wb-hand-button").length;
input().files = [file];
input().listeners.change.forEach((fn) => fn());
await settle();
out.afterChange = { calls: calls.length, chosen: tx(find(hand(), ".wb-hand-chosen")), button: tx(find(hand(), "button.wb-hand-button")), line: tx(find(hand(), ".wb-drop-line")) };
// a poll that draws the same target again leaves the choice; one that moves the target does not change the task the file was chosen for
tab.update(view([task(11, "blocked", { note: "n" })]));
await settle();
out.afterPoll = { chosen: tx(find(hand(), ".wb-hand-chosen")), button: tx(find(hand(), "button.wb-hand-button")) };
tab.update(view([task(12, "failed", { note: "x" }), task(11, "blocked", { note: "n" })]));
await settle();
out.otherTarget = tx(find(hand(), "button.wb-hand-button"));
out.hintAfterMove = tx(find(hand(), ".wb-hint"));
if (find(hand(), "button.wb-hand-button")) find(hand(), "button.wb-hand-button").click();
await settle();
out.afterButton = { calls: calls.slice(), result: tx(find(hand(), ".wb-card-line")), button: all(hand(), "button.wb-hand-button").length };
// a refusal at the choice
input().files = [{ name: "x".repeat(300), size: 3, arrayBuffer: async () => new ArrayBuffer(3) }];
input().listeners.change.forEach((fn) => fn());
await settle();
out.bad = { text: tx(find(hand(), ".wb-notice-card")), button: all(hand(), "button.wb-hand-button").length, calls: calls.length };
console.log(JSON.stringify(out));
process.exit(0);
"""


# --- the links that were "#/" when "#/" was the City: they name the Building or the City now --------------------------------------

BACKLINK = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createFloorView } from "@JS@/views/floor.js";
import { createComposer } from "@JS@/views/lobby-composer.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = () => {};
const P = "0123456789ab";
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0 });
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("engineering"), agent("planning")], status: { requests: [], pending: [], documents: [] } } } };
const frame = { el: new FakeNode("div"), main: new FakeNode("main"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), isPhone: () => false, sceneUnavailable() {}, announce() {},
  acquireWorld: () => ({ show() {}, setOptions() {}, refit() {}, stats() { return {}; } }) };
const out = {};
const view = createFloorView(frame, { refresh() {} });
const link = () => find(frame.main, ".wb-floor-unknown a");
out.before = link().attrs.href;
view.update({ snapshot, route: router.parse(`#/p/${P}/floor/ghost`), now: new Date("2026-10-09T12:00:00Z") });
await settle();
out.unknownAgent = link().attrs.href;
view.dispose();
// the fallbacks of a module built with no links
const composer = createComposer({ onSend() {} });
out.composerRun = find(composer.el, "a.wb-lobby-run-link").attrs.href;
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_back_to_the_building_names_the_building_and_the_fallback_links_no_longer_stand_for_the_old_city_hash(tmp_path):
    got = run_view(tmp_path, BACKLINK)
    assert got["before"] == "#/city" and got["unknownAgent"] == "#/p/0123456789ab", "the link of an agent that is not in the configuration goes to the Building"
    assert got["composerRun"] == "#/city"
    for name, needle in (("floor/agent-tab.js", 'inbox: () => router.cityHash()'), ("floor/cards.js", "router.cityHash()")):
        assert needle in (JS / name).read_text(encoding="utf-8"), f"{name}: the fallback names the City by its own route"
    for path in sorted(JS.rglob("*.js")):
        assert 'href: "#/"' not in path.read_text(encoding="utf-8"), f'{path.name}: no link is "#/", which is the entry and not the City'


# --- row 4 (C-18), row 5 (C-19), row 8 (K-5) ---------------------------------------------------------------------------------------

BOARD = r"""
import * as fm from "@JS@/floor-model.js";

const P = "0123456789ab";
const task = (id, title, state, extra = {}) => ({ id, key: `k${id}`, title, skill: "eng-implement", state, note: null, agent: "engineering", requestId: 2, waiting_for: [], ...extra });
const agent = { name: "engineering", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0, wider: [] };
const snap = (tasks, bodies) => ({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 2, title: "R", state: "running", tasks }], pending: [], held: [] }, agents: [agent] } }, tasks: {}, loaded: true });
const board = (tasks, bodies) => fm.boardOf(fm.floor(snap(tasks), P, "engineering", bodies));
const run = (extra) => ({ id: 3, skill: "eng-implement", skill_version: "1.0.0", model: "m", status: "done", attempts: 1, ending: "done", duration_ms: 42000, tokens: 1200, started_at: "2026-10-09T10:00:00Z", ...extra });
const out = {};
out.running = board([task(9, "Open the pull request", "running")], { 9: { task: { id: 9 }, runs: [run({ cost_usd: 0.0123 })], pending: [] } });
out.unknown = board([task(9, "Open the pull request", "running")], { 9: { task: { id: 9 }, runs: [run({})], pending: [] } });
out.noRun = board([task(9, "Open the pull request", "ready")], {});
out.untitled = board([task(10, "", "ready", { title: "" })], {});
out.none = board([], {});
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_wall_board_names_the_task_with_its_number_and_says_it_is_the_current_one_and_a_cost_not_recorded_is_unknown(tmp_path):
    got = run_pure(tmp_path, BOARD)
    assert got["running"]["title"] == "#9 Open the pull request · current task", "C-18 (E-24)"
    assert got["noRun"]["title"] == "#9 Open the pull request · current task"
    assert got["untitled"]["title"] == "#10 k10 · current task", "no title: the key stands in"
    assert got["none"]["title"] == "No task yet", "no current task: the board is as it was"
    assert got["running"]["lines"][2] == "attempt 1 · 42 s · 1,200 tokens · $0.0123 · m"
    assert got["unknown"]["lines"][2] == "attempt 1 · 42 s · 1,200 tokens · unknown · m", "C-18 (E-27): one word, as in the run block"
    assert "recorded: not available" not in json.dumps(got)


AGES = r"""
import { FakeNode, find, all, textOf } from "@FAKE@";
import * as format from "@JS@/format.js";
import * as fm from "@JS@/floor-model.js";
import { createInbox } from "@JS@/floor/inbox.js";

const NOW = new Date("2026-10-09T12:00:00Z");
const at = (s) => new Date(NOW.getTime() - s * 1000).toISOString();
const out = {};
out.words = typeof format.agoPhrase === "function" ? ["now", "12 min", "5 h", "2 d", "", undefined].map((s) => format.agoPhrase(s)) : "missing";
const bodies = { 4: { task: { id: 4 }, runs: [], pending: [
  { id: 30, kind: "review", status: "resolved", resolution: "released", title: "Fresh", created_at: at(3600), resolved_at: at(10) },
  { id: 31, kind: "effect", status: "cancelled", resolution: null, title: "Old", created_at: at(7200), resolved_at: at(600) } ] } };
const lines = fm.resolvedLines(bodies, [4], NOW);
out.ages = lines.map((l) => l.age);
const inbox = createInbox({ project: "p", now: () => NOW, api: {}, refresh() {}, links: { open: () => "#", floor: () => "#", lobby: () => "#", parent: () => "#" } });
inbox.update({ decisions: [], requests: [], resolved: lines, selected: null, loading: false });
out.summary = all(inbox.el, "summary.wb-resolved").map((s) => textOf(s));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_line_resolved_within_the_minute_says_just_now_never_now_ago(tmp_path):
    got = run_node(tmp_path, AGES)
    assert got["ages"] == ["now", "10 min"]
    assert "now ago" not in "".join(got["summary"]), "C-19: a line resolved within the minute never reads 'now ago'"
    assert got["summary"] == ["Review releasedFresh · just now", "Effect cancelledOld · 10 min ago"]
    assert got["words"] == ["just now", "12 min ago", "5 h ago", "2 d ago", "", ""], "one helper words an age"
    for path in JS.rglob("*.js"):
        assert not re.search(r"\$\{[^}]*age[^}]*\} ago", path.read_text(encoding="utf-8")), f"{path.name} builds an age phrase by hand: use format.agoPhrase"


EFFECT = r"""
import { FakeNode, settle, find, all, textOf } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";
import { createPlanCard } from "@JS@/cards/plan.js";

const HASH = "ab".repeat(32);
const calls = [];
const client = { approve: async (...args) => { calls.push(args); return { job: "j" }; }, reject: async () => ({}), pollJob: async () => ({ state: "done", result: {} }) };
const env = { project: "p", now: () => new Date("2026-10-09T12:00:00Z"), api: client, requestIds: new Set(), links: { floor: () => "#", lobby: () => "#", open: () => "#" }, reread: async () => null, changed() {}, gone() {} };
const effect = { id: 8, kind: "effect", title: "Publish the post", body: "Hello world", payload: {}, payload_sha256: HASH, status: "open", actions: ["approved", "rejected"], agent: "marketing", task_id: 5, run_id: null, created_at: "2026-10-09T09:00:00Z" };
const card = createCard(effect, env);
await settle();
const content = find(card.el, "pre.wb-pre");
const hash = find(card.el, "code.wb-hash");
const out = { content: [content.attrs.tabindex, content.attrs["aria-label"], textOf(content)], hash: [hash.attrs.tabindex, hash.attrs["aria-label"], hash.attrs.role || null, textOf(hash)] };
// the plan card's hash block, on the Floor's card and on the Lobby's: a tab stop named "Plan hash" that still shows the whole hash
const PHASH = "cd".repeat(32);
const planItem = { id: 9, kind: "plan", title: "Plan: x", body: "", payload: { plan_sha256: PHASH, tasks: [{ key: "a", title: "Build", skill: "eng-implement", depends_on: [] }], limits: { timeout_seconds: 60, retries: 1 }, estimate: { runs_at_least: 1 } }, payload_sha256: PHASH, status: "open", actions: ["approved", "rejected"], agent: "engineering", task_id: 5, run_id: null, created_at: "2026-10-09T09:00:00Z" };
const floorPlan = createCard(planItem, env);
await settle();
const fh = find(floorPlan.el, "code.wb-hash");
const lobbyPlan = createPlanCard({ api: client, project: "p", item: { ...planItem, agent: null }, now: new Date("2026-10-09T12:00:00Z"), onChanged: async () => {}, signal: undefined, announce() {} });
const lh = find(lobbyPlan.el, "code.wb-plan-hash");
out.plan = { floor: [fh.attrs.tabindex, fh.attrs["aria-label"], textOf(fh)], lobby: [lh.attrs.tabindex, lh.attrs["aria-label"], textOf(lh)] };
// the hash approved is still the one the page shows
all(card.el, "button.wb-card-button").find((b) => b.attrs["data-word"] === "approved").click();
await settle();
out.sent = calls.map((c) => c.slice(0, 3));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_effect_cards_content_and_hash_blocks_are_tab_stops_with_a_name(tmp_path):
    got = run_node(tmp_path, EFFECT)
    hash_ = "ab" * 32
    assert got["content"] == ["0", "Exact content of the publish", "Hello world"], "the content block was a tab stop already; its name says what it is"
    assert got["hash"][0] == "0" and got["hash"][1] == "Hash of this content" and got["hash"][3] == hash_, "K-5: the hash block is a tab stop with a name, and shows the whole hash"
    ph = "cd" * 32
    assert got["plan"] == {"floor": ["0", "Plan hash", ph], "lobby": ["0", "Plan hash", ph]}, "the plan card's hash block is a tab stop with a name, on the Floor and on the Lobby"
    assert got["sent"] == [["p", 8, hash_]], "the approval still sends the hash the page shows"


# --- row 10, C-13 and D-1: the brand typefaces, vendored ---------------------------------------------------------------------------

FONT_FILES = ("inter-400.woff2", "inter-600.woff2", "jetbrains-mono-400.woff2", "jetbrains-mono-700.woff2", "space-grotesk-500.woff2")
FONT_LICENCES = ("LICENSE-inter.txt", "LICENSE-jetbrains-mono.txt", "LICENSE-space-grotesk.txt")


def test_the_five_woff2_files_and_their_licences_are_vendored_with_a_recorded_hash():
    present = {p.name for p in FONTS.iterdir() if p.is_file()}
    assert present == set(FONT_FILES) | set(FONT_LICENCES) | {"README.md"}, f"nothing but the five files, their licences and the README: {sorted(present)}"
    for name in FONT_FILES:
        data = (FONTS / name).read_bytes()
        assert data[:4] == b"wOF2", f"{name} is a woff2 file"
    assert sum((FONTS / n).stat().st_size for n in FONT_FILES) < 120_000, "the files are small subsets (about 105 KB), so the page preloads nothing"
    for name in FONT_LICENCES:
        text = (FONTS / name).read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE Version 1.1" in text and "Copyright" in text, f"{name} holds the licence and the copyright line"
    readme = (FONTS / "README.md").read_text(encoding="utf-8")
    assert re.search(r"^- Licence: SIL OFL 1\.1", readme, re.M)
    for name in FONT_FILES + FONT_LICENCES:
        digest = hashlib.sha256((FONTS / name).read_bytes()).hexdigest()
        assert f"| `{name}` | {(FONTS / name).stat().st_size} | `{digest}` |" in readme, f"{name} has its size and hash in the README"


def test_every_font_face_loads_a_same_origin_file_of_the_vendored_folder_and_the_stacks_name_the_families():
    css = CSS.read_text(encoding="utf-8")
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", css)
    assert len(faces) == 5, "one @font-face for each of the five files"
    sources = []
    for face in faces:
        assert "font-display: swap" in face, "the text shows at once in the fallback"
        urls = re.findall(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", face)
        assert len(urls) == 1 and re.fullmatch(r"\.\./vendor/fonts/[a-z0-9-]+\.woff2", urls[0]), f"the source is a path under vendor/fonts/ (the stylesheet stands in interface/css/): {urls}"
        assert (INTERFACE / "css" / urls[0]).resolve().is_file(), f"{urls[0]} exists"
        assert not re.search(r"https?:|//|data:", face)
        sources.append(urls[0].rsplit("/", 1)[1])
    assert sorted(sources) == sorted(FONT_FILES)
    families = sorted((re.search(r"font-family:\s*\"([^\"]+)\"", f).group(1), re.search(r"font-weight:\s*(\d+)", f).group(1)) for f in faces)
    assert families == [("Inter", "400"), ("Inter", "600"), ("JetBrains Mono", "400"), ("JetBrains Mono", "700"), ("Space Grotesk", "500")]
    assert re.search(r"--wb-font-system:\s*\"Inter\", system-ui,", css), "text: Inter, then the system stack"
    assert re.search(r"--wb-font-mono:\s*\"JetBrains Mono\", ui-monospace,", css), "code, hashes and commands: JetBrains Mono, then the system monospace"
    assert re.search(r"--wb-font-brand:\s*\"Space Grotesk\",", css)
    brand_uses = re.findall(r"([^{}]+)\{[^{}]*font-family:\s*var\(--wb-font-brand\)", css)
    assert [u.strip() for u in brand_uses] == [".wb-wordmark"], f"Space Grotesk is for the wordmark on the token prompt only: {brand_uses}"
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert "preload" not in html and "woff2" not in html, "index.html preloads nothing"
    assert service.TYPES[".woff2"] == "font/woff2", "the service serves the files with their type"


# --- row 12 and the README -----------------------------------------------------------------------------------------------------------

def test_the_readme_says_what_the_page_does_now():
    text = README.read_text(encoding="utf-8")
    assert "is that same card (`floorCardNode`)" not in text and "a row (`rowNode`, `views/building.js`), not a plate" in text, "R-27: the floors list rows are drawn by rowNode (building.js), no longer by plateNode"
    assert "shows the placeholder" not in text, "the unread project's placeholder is unreachable: the sentence is gone"
    assert "desktop from 1024" not in text
    assert "1100" in text and "639" in text and "899" in text and "1099" in text, "the four bands (R-1, R-10: the mark's breakpoint of 712 px is gone with the top bar's strip)"
    assert "`#/city`" in text and "js/mode.js" in text, "the City route and the colour mode are described"
    assert "vendor/fonts" in text and "provisional" not in text.split("`js/mode.js`")[1].split("|")[0], "the typefaces; R-4 gives the colour-mode button its place, so it is no longer provisional"
    rule = re.search(r"- \*\*The token lives in memory and in `sessionStorage`[^\n]*\n(?:  [^\n]*\n)*", text)
    assert rule and "openhora-mode" not in rule.group(0) and "localStorage" in rule.group(0) and "nothing is stored" in text, "R4D-3: the storage rule has no exception: the colour mode is not stored"
