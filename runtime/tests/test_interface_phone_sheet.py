"""Tests of the phone layout of the local interface (ADJ-I1, rows A-27 and A-28): the bottom sheet (interface/js/frame/drawer.js: its
positions, its drag, its keyboard, its memory), the handle on the markup of every screen that has a panel, the frame's part (the cards that
float over the scene, the pause while the sheet covers it), the anchor of the Building's floor card at the bottom, and the stylesheet's phone
rules. No browser, no model and no service: the pure functions and the bindings run under Node with the fake document of the frame's tests; the
page itself was looked at in a browser pane at the phone size, against the real service, by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_phone_sheet.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st
from test_interface_scene import FAKE_DOM
from test_interface_scene_round3 import ENGINE_PAGE_JS, PRODUCT_JS, run_node_engine
from interface_css import interface_css

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
FRAME = JS / "frame"
VIEWS = JS / "views"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the sheet's logic is tested only by its text")

CSS = interface_css()


def run_node(tmp_path: Path, body: str) -> dict:
    """Run `body` (an ES module that prints one JSON line) under the fake document and return what it printed."""
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FAKE_DOM, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def media_blocks(css: str, query: str) -> list[str]:
    """The bodies of every `@media <query> { ... }` block of the stylesheet (the braces balanced)."""
    blocks = []
    for match in re.finditer(r"@media\s*\(" + re.escape(query) + r"\)\s*\{", css):
        depth, at = 1, match.end()
        while at < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[at], 0)
            at += 1
        blocks.append(css[match.end():at - 1])
    return blocks


def without_media(css: str) -> str:
    """The stylesheet with every `@media` block (and `@keyframes`) taken out: the rules that hold at every width."""
    out, at = [], 0
    for match in re.finditer(r"@(?:media|keyframes)[^{]*\{", css):
        if match.start() < at:
            continue
        out.append(css[at:match.start()])
        depth, at = 1, match.end()
        while at < len(css) and depth:
            depth += {"{": 1, "}": -1}.get(css[at], 0)
            at += 1
    out.append(css[at:])
    return "".join(out)


def rules(block: str) -> list[tuple[str, dict[str, str]]]:
    """The (selector, declarations) pairs of a block of flat rules."""
    out = []
    block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", block):
        declarations = {}
        for part in body.split(";"):
            if ":" in part:
                name, value = part.split(":", 1)
                declarations[name.strip()] = value.strip()
        out.append((" ".join(selector.split()), declarations))
    return out


# --- the sheet's position logic (pure) -------------------------------------------------------------------------------------------

LOGIC = r"""
import * as d from "@JS@/frame/drawer.js";
const out = {};
out.positions = d.POSITIONS;
out.defaults = [d.defaultPosition("city"), d.defaultPosition("lobby"), d.defaultPosition("floor"), d.defaultPosition("building"), d.defaultPosition("control")];
out.cycle = [d.cycle("half"), d.cycle("full"), d.cycle("collapsed"), d.cycle("nonsense")];
out.up = ["collapsed", "half", "full"].map((p) => d.step(p, "up"));
out.down = ["collapsed", "half", "full"].map((p) => d.step(p, "down"));
out.walk = [];
let p = "collapsed";
for (let i = 0; i < 4; i += 1) { p = d.step(p, "up"); out.walk.push(p); }
for (let i = 0; i < 4; i += 1) { p = d.step(p, "down"); out.walk.push(p); }
// settle(start, startPx, dyPx, spanPx): the span is 700 px; half is 350 px
out.tap = [d.settle("half", 350, 0, 700), d.settle("half", 350, 23, 700), d.settle("half", 350, -23, 700), d.settle("half", 350, NaN, 700)];
out.nearest = [d.settle("half", 350, -330, 700), d.settle("half", 350, 330, 700), d.settle("collapsed", 90, -300, 700), d.settle("full", 700, 300, 700), d.settle("full", 700, 600, 700)];
out.step = [d.settle("half", 350, -40, 700), d.settle("half", 350, 40, 700), d.settle("collapsed", 90, -30, 700), d.settle("full", 700, -40, 700), d.settle("collapsed", 90, 40, 700)];
out.bounds = [d.settle("half", 350, -5000, 700), d.settle("half", 350, 5000, 700)];
out.label = [d.gripLabel("full"), d.valid("full"), d.valid("up")];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_sheet_cycles_steps_and_settles_inside_its_three_positions(tmp_path):
    got = run_node(tmp_path, LOGIC)
    assert got["positions"] == ["collapsed", "half", "full"]
    assert got["defaults"] == ["collapsed", "half", "half", "half", "half"], "the City's lists open collapsed, every panel at half"
    assert got["cycle"] == ["full", "half", "half", "half"], "half goes to full, full back to half, collapsed up to half"
    assert got["up"] == ["half", "full", "full"] and got["down"] == ["collapsed", "collapsed", "half"], "an arrow moves one position and stops at the ends"
    assert got["walk"] == ["half", "full", "full", "full", "half", "collapsed", "collapsed", "collapsed"]
    assert got["tap"] == ["half"] * 4, "a move under 24 px (or none, or not a number) leaves the sheet where it was"
    assert got["nearest"] == ["full", "collapsed", "half", "half", "collapsed"], "a long drag ends at the position nearest the height it was dragged to"
    assert got["step"] == ["full", "collapsed", "half", "full", "collapsed"], "a short deliberate drag still moves one step in its direction (and stops at the ends)"
    assert got["bounds"] == ["full", "collapsed"], "a drag beyond the span stays inside the three positions"
    assert got["label"] == ["Panel size, full", "full", None]


# --- the binding: classes, keyboard, drag, memory, the event ---------------------------------------------------------------------

BIND = r"""
import { FakeNode } from "@FAKE@";
const mqls = [];     // every media query list the sheets asked for: a test moves the viewport by changing one and calling its listeners
window.matchMedia = () => {
  const m = { matches: true, listeners: [], addEventListener(type, fn) { m.listeners.push(fn); }, removeEventListener(type, fn) { m.listeners = m.listeners.filter((x) => x !== fn); } };
  mqls.push(m);
  return m;
};
const d = await import("@JS@/frame/drawer.js");

const events = [];
const wl = {};     // what the window hears: a drag's moves and its end are listened to there, not on the sheet
window.addEventListener = (type, fn) => { (wl[type] ||= []).push(fn); };
window.removeEventListener = (type, fn) => { wl[type] = (wl[type] || []).filter((x) => x !== fn); };
function sheet(screen, height = 350) {
  const state = { height, props: {} };
  const el = new FakeNode("section");
  const grip = d.createGrip();
  const head = new FakeNode("div");
  head.attrs.class = "wb-panel-head";
  const body = new FakeNode("div");
  body.attrs.class = "wb-panel-body";
  const button = new FakeNode("button");
  head.append(button);
  el.append(grip, head, body);
  el.parentElement = { clientHeight: 700 };
  el.getBoundingClientRect = () => ({ height: state.height });
  el.style = { setProperty: (k, v) => { state.props[k] = v; } };
  el.dispatchEvent = (ev) => { events.push(ev.detail); return true; };
  // what a target answers to `closest`: the handle (the grip, the header line), and a control (a button)
  const aim = (node, handle, control) => { node.closest = (sel) => (sel.startsWith("button") ? control : handle); return node; };
  aim(grip, grip, grip);
  aim(head, head, null);
  aim(button, head, button);
  aim(body, null, null);
  const bound = d.bindDrawer(el, { screen, grip });
  const fire = (node, type, init) => (type === "pointerdown" ? (el.listeners[type] || []) : [...(wl[type] || [])]).forEach((fn) => fn({ target: node, pointerId: 1, button: 0, timeStamp: 1000, ...init }));
  return { el, grip, head, body, button, bound, state, fire, cls: () => el.cls(), key: (k) => { let stopped = false; (grip.listeners.keydown || []).forEach((fn) => fn({ key: k, preventDefault() { stopped = true; } })); return stopped; },
    click: () => (grip.listeners.click || []).forEach((fn) => fn({ timeStamp: 5000 })) };
}
const settled = () => new Promise((resolve) => setTimeout(resolve, 0));
const out = {};

// a new sheet opens at its screen's default, tells the frame once, and carries the handle's name
const a = sheet("lobby");
await settled();
out.open = { cls: a.cls().filter((c) => c.startsWith("is-")), label: a.grip.attrs["aria-label"], expanded: a.grip.attrs["aria-expanded"], events: events.splice(0) };

// the handle: a tap cycles half -> full -> half; Enter and Space are clicks of a button
a.click(); const full = { pos: a.bound.position(), cls: a.cls().filter((c) => c.startsWith("is-")), event: events.splice(0) };
a.click(); const back = a.bound.position();
out.tap = { full, back };

// the keyboard: the arrows move one position at a time and the page's default is stopped; other keys are left alone
out.keys = [a.key("ArrowUp"), a.bound.position(), a.key("ArrowUp"), a.bound.position(), a.key("ArrowDown"), a.key("ArrowDown"), a.bound.position(), a.key("ArrowDown"), a.bound.position(), a.key("Tab"), a.bound.position()];
events.splice(0);

// the position is kept per screen, in memory: a sheet made again for the same screen opens where it was left, another screen does not
a.bound.set("full");
a.bound.destroy();
const again = sheet("lobby");
const other = sheet("floor");
out.memory = { again: again.bound.position(), other: other.bound.position() };
events.splice(0);

// a drag that starts on the handle: up 330 px from half goes to full, writes one custom property while it lasts, and sends a click that is not a tap
const g = sheet("building");
await settled(); events.splice(0);
g.fire(g.grip, "pointerdown", { clientY: 500 });
g.fire(g.grip, "pointermove", { clientY: 400 });
const during = { cls: g.cls().includes("is-dragging"), prop: g.state.props["--wb-drawer-drag"], onWindow: (wl.pointermove || []).length, dragging: events.length ? events[events.length - 1].dragging : null };
g.fire(g.grip, "pointermove", { clientY: 170 });
g.fire(g.grip, "pointerup", { clientY: 170, timeStamp: 2000 });
const afterDrag = { pos: g.bound.position(), dragging: g.cls().includes("is-dragging"), prop: g.state.props["--wb-drawer-drag"], last: events[events.length - 1], onWindow: (wl.pointermove || []).length + (wl.pointerup || []).length + (wl.pointercancel || []).length };
g.click();     // a click seconds later is a tap
out.dragGrip = { during, afterDrag, tapLater: g.bound.position() };

// the click a browser sends right after a drag is not a tap
const g2 = sheet("control");
g2.fire(g2.grip, "pointerdown", { clientY: 500 });
g2.fire(g2.grip, "pointermove", { clientY: 100 });
g2.fire(g2.grip, "pointerup", { clientY: 100, timeStamp: 3000 });
const posAfterDrag = g2.bound.position();
(g2.grip.listeners.click || []).forEach((fn) => fn({ timeStamp: 3010 }));
out.clickAfterDrag = [posAfterDrag, g2.bound.position()];

// a drag that starts on the header works; on a button of the header or on the scrolled body it does not start
const h1 = sheet("floor");
h1.fire(h1.head, "pointerdown", { clientY: 500 });
h1.fire(h1.head, "pointermove", { clientY: 800 });
h1.fire(h1.head, "pointerup", { clientY: 800, timeStamp: 100 });
const h2 = sheet("lobby");
h2.bound.set("half");
h2.fire(h2.button, "pointerdown", { clientY: 500 }); h2.fire(h2.button, "pointermove", { clientY: 800 }); h2.fire(h2.button, "pointerup", { clientY: 800 });
const h3 = sheet("control");
h3.bound.set("half");
h3.fire(h3.body, "pointerdown", { clientY: 500 }); h3.fire(h3.body, "pointermove", { clientY: 800 }); h3.fire(h3.body, "pointerup", { clientY: 800 });
out.starts = { header: h1.bound.position(), button: h2.bound.position(), body: h3.bound.position(), bodyDragging: h3.cls().includes("is-dragging") };

// a tap on the header raises a collapsed sheet to half and does nothing to the others
const t1 = sheet("tap-a"); t1.bound.set("collapsed");
t1.fire(t1.head, "pointerdown", { clientY: 500 }); t1.fire(t1.head, "pointerup", { clientY: 500 });
const t2 = sheet("tap-b"); t2.bound.set("full");
t2.fire(t2.head, "pointerdown", { clientY: 500 }); t2.fire(t2.head, "pointerup", { clientY: 500 });
out.headerTap = [t1.bound.position(), t2.bound.position()];

// a cancelled drag puts the sheet back; the event says it covers the scene only at full, and a sheet that is gone covers nothing
const c = sheet("cancel");
c.fire(c.grip, "pointerdown", { clientY: 500 }); c.fire(c.grip, "pointermove", { clientY: 100 }); c.fire(c.grip, "pointercancel", {});
out.cancel = { pos: c.bound.position(), dragging: c.cls().includes("is-dragging") };
events.splice(0);
c.bound.set("full"); c.bound.set("half"); c.bound.set("full"); c.bound.destroy();
out.covering = events.map((e) => [e.position, e.covering]);

// the viewport leaves the phone width while the sheet is full: the event says it covers nothing, and says so again when the phone width comes back
const q = sheet("viewport");
q.bound.set("full");
const mq = mqls[mqls.length - 1];
events.splice(0);
mq.matches = false; mq.listeners.forEach((fn) => fn());
const left = events.splice(0).map((e) => [e.position, e.covering]);
mq.matches = true; mq.listeners.forEach((fn) => fn());
const came = events.splice(0).map((e) => [e.position, e.covering]);
q.bound.destroy();
out.viewport = { left, came, listenersAfterDestroy: mq.listeners.length };

// while a drag lasts the sheet covers nothing (the scene is drawn as the sheet comes down), and `rising` says when the sheet is taller than it was
const r = sheet("rising");
r.bound.set("half");
events.splice(0);
r.fire(r.grip, "pointerdown", { clientY: 100 }); r.fire(r.grip, "pointermove", { clientY: 300 });
const down = events[events.length - 1];
r.fire(r.grip, "pointermove", { clientY: 40 });
const up = events[events.length - 1];
r.fire(r.grip, "pointerup", { clientY: 40, timeStamp: 9000 });
out.dragState = { down: [down.dragging, down.covering, down.rising], up: [up.dragging, up.covering, up.rising], end: events[events.length - 1] };

// a gesture whose end is never heard does not hold the sheet; a cancel and a destroy in the middle of a drag let the window go
const heard = () => (wl.pointermove || []).length + (wl.pointerup || []).length + (wl.pointercancel || []).length;
const w = sheet("window");
w.fire(w.grip, "pointerdown", { clientY: 500 }); w.fire(w.grip, "pointermove", { clientY: 400 });
const mid = { heard: heard(), dragging: w.cls().includes("is-dragging") };
w.fire(w.grip, "pointerdown", { clientY: 300, pointerId: 2 });     // the end of pointer 1 was lost
const fresh = { heard: heard(), dragging: w.cls().includes("is-dragging"), prop: w.state.props["--wb-drawer-drag"] };
w.fire(w.grip, "pointermove", { clientY: 200, pointerId: 2 });
w.fire(w.grip, "pointercancel", { pointerId: 2 });
const cancelled = { heard: heard(), dragging: w.cls().includes("is-dragging"), prop: w.state.props["--wb-drawer-drag"] };
w.fire(w.grip, "pointerdown", { clientY: 500 }); w.fire(w.grip, "pointermove", { clientY: 380 });
const heardMid = heard();
w.bound.destroy();
out.window = { mid, fresh, cancelled, during: heardMid, destroyed: { heard: heard(), dragging: w.cls().includes("is-dragging"), prop: w.state.props["--wb-drawer-drag"] } };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_sheet_binds_the_handle_the_keyboard_the_drag_and_the_memory(tmp_path):
    got = run_node(tmp_path, BIND)
    assert got["open"]["cls"] == ["is-half"] and got["open"]["label"] == "Panel size, half" and got["open"]["expanded"] == "true"
    assert got["open"]["events"] == [{"position": "half", "covering": False, "dragging": False, "rising": False}], "the frame hears once where a sheet opens"
    assert got["tap"]["full"]["pos"] == "full" and got["tap"]["full"]["cls"] == ["is-full"], "the position is a class on the sheet"
    assert got["tap"]["full"]["event"] == [{"position": "full", "covering": True, "dragging": False, "rising": False}] and got["tap"]["back"] == "half"
    assert got["keys"] == [True, "full", True, "full", True, True, "collapsed", True, "collapsed", False, "collapsed"], \
        "ArrowUp and ArrowDown move one position and stop at the ends; any other key is left alone"
    assert got["memory"] == {"again": "full", "other": "half"}, "the position is kept per screen for as long as the page lives"
    drag = got["dragGrip"]
    assert drag["during"] == {"cls": True, "prop": "450px", "onWindow": 1, "dragging": True}, "a drag follows the pointer through one custom property, heard on the window"
    assert drag["afterDrag"]["pos"] == "full" and drag["afterDrag"]["dragging"] is False and drag["afterDrag"]["prop"] == "", "the drag ends on a position and removes the property"
    assert drag["afterDrag"]["last"] == {"position": "full", "covering": True, "dragging": False, "rising": False} and drag["afterDrag"]["onWindow"] == 0, "the window is let go"
    assert drag["tapLater"] == "half", "a tap on the handle after the drag cycles it again"
    assert got["clickAfterDrag"] == ["full", "full"], "the click a browser sends right after a drag is not a tap"
    assert got["starts"] == {"header": "collapsed", "button": "half", "body": "half", "bodyDragging": False}, \
        "a drag starts on the handle or on a header line, never on a button of the header or on the scrolled body"
    assert got["headerTap"] == ["half", "full"], "a tap on a header raises a collapsed sheet and leaves the others"
    assert got["cancel"] == {"pos": "half", "dragging": False}
    assert got["covering"] == [["full", True], ["half", False], ["full", True], ["full", False]], "only a sheet at full covers the scene; a destroyed one covers nothing"
    assert got["viewport"] == {"left": [["full", False]], "came": [["full", True]], "listenersAfterDestroy": 0}, \
        "the viewport leaving the phone width while the sheet is full releases the pause (the event says covering false), and the sheet lets the query go when it is destroyed"
    assert got["dragState"]["down"] == [True, False, False] and got["dragState"]["up"] == [True, False, True], \
        "a sheet being dragged covers nothing; rising says it is taller than it was"
    assert got["dragState"]["end"]["covering"] is True and got["dragState"]["end"]["dragging"] is False and got["dragState"]["end"]["rising"] is False
    w = got["window"]
    assert w["mid"] == {"heard": 3, "dragging": True} and w["fresh"] == {"heard": 3, "dragging": False, "prop": ""}, \
        "a press while a gesture's end was never heard starts afresh: the old one is let go, the window holds one gesture"
    assert w["cancelled"] == {"heard": 0, "dragging": False, "prop": ""} and w["during"] == 3, "a cancel lets the window go and clears the drag"
    assert w["destroyed"] == {"heard": 0, "dragging": False, "prop": ""}, "destroying the sheet in the middle of a drag lets the window go and clears the drag"


# --- the handle is on the markup of every screen that has a panel; no inline style; the position is a class -------------------

PANELS = r"""
import { FakeNode } from "@FAKE@";
import { createPanel } from "@JS@/frame/panel.js";
const out = {};
const names = (node) => [...node.walk()].filter((n) => n instanceof FakeNode).map((n) => n.attrs.class || "");
for (const screen of ["lobby", "control"]) {
  const panel = createPanel({ screen, title: "T", subtitle: "S", width: "wide" });
  const grip = [...panel.el.walk()].find((n) => n.tagName === "BUTTON" && (n.attrs.class || "").includes("wb-grip"));
  out[screen] = { grip: Boolean(grip), first: panel.el.children[0] === grip, name: grip && grip.attrs["aria-label"], cls: panel.el.cls().includes("wb-drawer"), destroy: typeof panel.drawer.destroy, style: Object.keys(grip.attrs).includes("style") };
}
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_panel_builder_of_the_lobby_and_the_control_room_puts_the_handle_first(tmp_path):
    got = run_node(tmp_path, PANELS)
    for screen in ("lobby", "control"):
        assert got[screen] == {"grip": True, "first": True, "name": "Panel size, half", "cls": True, "destroy": "function", "style": False}, screen


def test_the_handle_is_in_the_markup_builder_of_every_screen_that_has_a_panel_and_the_screen_lets_it_go():
    """The Building, the Floor and the City build their own markup; the Lobby and the Control room share `createPanel`. Each makes the handle,
    binds the sheet under its own screen's name, and destroys the binding before the panel leaves the page (the frame then hears that nothing
    covers the scene)."""
    panel = (FRAME / "panel.js").read_text(encoding="utf-8")
    assert "createGrip()" in panel and "bindDrawer(el, { screen: spec.screen, grip })" in panel and "wb-drawer" in panel
    for name, screen in (("building", "building"), ("floor", "floor"), ("city", "city")):
        text = (VIEWS / f"{name}.js").read_text(encoding="utf-8")
        assert 'from "../frame/drawer.js"' in text and "createGrip()" in text, f"{name}.js makes the handle"
        assert re.search(r"bindDrawer\(\w+, \{ screen: \"" + screen + r"\", grip", text), f"{name}.js binds the sheet under its own screen's name"
        assert "wb-drawer" in text and re.search(r"h\([^)]*\"[^\"]*wb-drawer[^\"]*\"[^)]*\bgrip\b", text, re.S), f"{name}.js has the handle among the sheet's children"
        dispose = text[text.index("dispose()"):]
        assert dispose.index("drawer.destroy()") < dispose.index(".remove()"), f"{name}.js destroys the sheet's binding before it removes the sheet"
    for name, screen in (("lobby", "lobby"), ("control", "control")):
        text = (VIEWS / f"{name}.js").read_text(encoding="utf-8")
        assert f'createPanel({{ screen: "{screen}"' in text, f"{name}.js names its screen to the panel"
        dispose = text[text.index("dispose()"):]
        assert dispose.index("panel.drawer.destroy()") < dispose.index("panel.el.remove()"), f"{name}.js destroys the sheet's binding before it removes the panel"
    # the City's sheet holds "Waiting for you" alone (R-22: the Projects list is the scene's keyboard twin, no part of the sheet), and its header starts a drag
    city = (VIEWS / "city.js").read_text(encoding="utf-8")
    assert 'handles: ".wb-wait-head"' in city and "frame.waitingCard.el" in city


def test_the_sheet_uses_no_inline_style_and_the_position_is_a_class_of_the_stylesheet():
    drawer = (FRAME / "drawer.js").read_text(encoding="utf-8")
    assert not re.search(r"""setAttribute\(\s*["']style|\.cssText\b|\.style\.\w+\s*=|\.style\s*=""", drawer), "no inline style"
    assert re.findall(r"\.style\.(\w+)\(", drawer) == ["setProperty"] * 3, "the only thing written to a style is the one custom property"
    assert set(re.findall(r'setProperty\("(--[\w-]+)"', drawer)) == {"--wb-drawer-drag"}
    assert "sessionStorage" not in drawer and "localStorage" not in drawer, "the position is kept in memory, not in a store of the browser"
    for position in ("collapsed", "half", "full"):
        assert re.search(r"\.wb-drawer\.is-" + position + r"\b", CSS), f"is-{position} is a rule of the stylesheet"
        assert f"is-${{name}}" in drawer or f"`is-{position}`" in drawer or "is-${name}" in drawer, "the position's class is built from its name"
    assert ".wb-drawer.is-dragging" in CSS and "var(--wb-drawer-drag" in CSS


# --- the stylesheet: no fixed scene height on the phone; the handle is the phone's; the desktop and the tablet are as they were ------------

PHONE = media_blocks(CSS, "max-width: 899px")   # M-3: the phone is up to 899 px


def test_no_phone_rule_gives_the_scene_a_fixed_height():
    assert "--wb-scene-phone" not in CSS, "the fixed height of the scene is gone"
    fixed = re.compile(r"^(?:-?\d+(?:\.\d+)?(?:px|rem|em|vh|dvh|svh|lvh|vw)|calc\(.*\)|var\(--wb-(?!drawer)[\w-]*\)|\d+%)$")
    scene_selectors = (".wb-scene", ".wb-scene-area", ".wb-canvas", ".wb-frame", ".wb-main")
    found = []
    for block in PHONE:
        for selector, declarations in rules(block):
            if not any(re.search(re.escape(s) + r"(?![\w-])", selector) for s in scene_selectors):
                continue
            for name in ("height", "min-height", "max-height", "flex-basis", "block-size"):
                if name in declarations and fixed.match(declarations[name]):
                    found.append((selector, name, declarations[name]))
            rows = declarations.get("grid-template-rows")
            if rows and selector.endswith(".wb-frame"):
                tracks = re.findall(r"minmax\([^)]*\)|[^\s]+", rows)
                if not tracks or tracks[0] != "minmax(0, 1fr)":
                    found.append((selector, "grid-template-rows", rows))
    assert found == [], f"a phone rule fixes the scene's height: {found}"
    # the scene's row is the one flexible row of the frame: the cards and the sheet are laid over it; the bottom bar is the second row (R-10)
    frame_rule = next(d for block in PHONE for sel, d in rules(block) if sel == ".wb-frame")
    assert frame_rule["grid-template-rows"] == "minmax(0, 1fr) auto" and frame_rule["grid-template-columns"] == "minmax(0, 1fr)"


def test_the_handle_is_the_phones_and_the_desktop_rules_are_as_they_were():
    top = without_media(CSS)
    assert re.search(r"\.wb-grip \{ display: none; \}", CSS), "the handle is not drawn above the phone width"
    phone = "\n".join(PHONE)
    assert re.search(r"\.wb-grip \{[^}]*display: flex;", phone) and "touch-action: none" in phone, "the phone draws the handle and stops the browser's pan on it"
    assert re.search(r"\.wb-city-drawer, \.wb-drawer-scroll, \.wb-float \{ display: contents; \}", CSS), "elsewhere the City's wrapper and the stack of cards take no box"
    # the desktop panel is placed as before: absolute at the right of the scene, at its fixed width
    panel = next(d for sel, d in rules(top) if sel == ".wb-panel")
    assert panel["position"] == "absolute" and panel["right"] == "var(--wb-edge)" and panel["width"] == "var(--wb-panel-narrow)"
    assert next(d for sel, d in rules(top) if sel == ".wb-dock")["position"] == "absolute", "R-8, M-4: the tracking bar stands at the bottom left in the dock (Back and the crumbs are in the top row)"
    assert "position" not in next(d for sel, d in rules(top) if sel == ".wb-track")
    assert next(d for sel, d in rules(top) if sel == ".wb-kpis")["position"] == "absolute"
    # the sheet's rules sit in the phone block alone
    for selector in (".wb-drawer.is-half", ".wb-drawer.is-full", ".wb-drawer.is-collapsed", ".wb-drawer.is-dragging"):
        assert selector in phone and selector not in "".join(b for b in media_blocks(CSS, "min-width: 900px") + media_blocks(CSS, "min-width: 1024px"))


def test_the_phone_puts_the_cards_over_the_scene_from_the_top_and_the_two_kpi_tiles_in_one_line_each():
    phone = "\n".join(PHONE)
    main = next(d for block in PHONE for sel, d in rules(block) if sel == ".wb-main")
    assert main["display"] == "flex" and main["flex-direction"] == "column" and "justify-content" not in main and main["grid-area"] == "1 / 1", \
        "R-10: the main area is laid over the scene's cell, a stack from the top down (the notice, the tracking bar, the KPI tiles), the sheet at the bottom"
    assert re.search(r"\.wb-frame\.is-sheet-full \.wb-float, \.wb-frame\.is-sheet-rising \.wb-float \{ display: none; \}", phone), \
        "the KPI cards and the tracking bar are hidden at full, and while a drag has the sheet rising"
    assert ".wb-kpi-note, .wb-kpi-unit { display: none; }" in phone, "the tile is one line: the unit that would be cut mid-word is not drawn (the title and the name carry the sentence)"
    kpi = next(d for block in PHONE for sel, d in rules(block) if sel == ".wb-kpi")
    assert kpi["font-size"] == "12px" and kpi["display"] == "block"
    assert ".wb-kpi-long { display: none; }" in phone and ".wb-kpi-short { display: inline; }" in phone and "white-space: nowrap" in phone
    assert next(d for block in PHONE for sel, d in rules(block) if sel == ".wb-kpis")["grid-template-columns"] == "repeat(2, minmax(0, 1fr))", "R-5, R-10: two tiles in one row"
    # the bottom bar stays (R-10): two rows, whatever the sheet's position: the switcher, the inbox button and the colour mode; then Back, the crumbs and the door
    bar = next(d for block in PHONE for sel, d in rules(block) if sel == ".wb-bottom-bar")
    assert bar["display"] == "grid" and "border-top" in bar and ".wb-bottom-row" in phone
    assert next(d for sel, d in rules(without_media(CSS)) if sel == ".wb-wait-btn")["display"] == "none", "the inbox button is the phone's: elsewhere the card is the list"
    assert re.search(r"\.wb-topbar, \.wb-dock \{ display: none; \}", phone), "a phone has no top row and no dock: their controls are in the bottom bar"
    # the sheet's collapsed state keeps a header line (a panel's head, the City's "Waiting for you" head: R-22 took the Projects head out of the sheet) and nothing else
    assert ".wb-drawer.is-collapsed:not(.is-dragging) > :not(.wb-grip, .wb-panel-head, .wb-floor-normal, .wb-drawer-scroll) { display: none; }" in phone
    assert ".wb-buildings > :not(.wb-buildings-head)" not in phone and ".wb-wait-body > :not(.wb-wait-head)" in phone, \
        "collapsed hides all but a header line, and not while a drag raises it: the content is there as the sheet comes up"
    # no panel on the phone is a free-flowing section of the page any more: the Floor and the Control room scroll inside the sheet
    assert ".wb-floor-normal { display: block; height: auto; }" not in "\n".join(media_blocks(CSS, "max-width: 899px"))


# --- the frame: the float stack, the event of the sheet, the pause --------------------------------------------------------------------

FRAME_SCRIPT = r"""
import { FakeNode } from "@FAKE@";
const out = {};
async function build(phone) {
  window.matchMedia = () => ({ matches: phone, addEventListener() {}, removeEventListener() {} });
  const { createFrame } = await import("@JS@/frame/frame.js?" + (phone ? "phone" : "desk"));
  const root = new FakeNode("div");
  const frame = createFrame(root, { onSelectProject() {}, onForgetToken() {}, onRetry() {} });
  return frame;
}
const kids = (n) => n.children.filter((c) => c instanceof FakeNode);
const cls = (n) => n.cls();
const desk = await build(false);
const phone = await build(true);
const floatOf = (frame) => kids(frame.main).find((c) => cls(c).includes("wb-float"));
out.desk = { float: kids(floatOf(desk)).length, kpisInScene: kids(desk.el).some((c) => cls(c).includes("wb-scene-area") && c.children.includes(desk.kpis.el)), trackInDock: kids(desk.el).some((c) => cls(c).includes("wb-dock") && c.children.includes(desk.track.el)) };
out.phone = { float: kids(floatOf(phone)).map((c) => cls(c).join(" ")), kpisInScene: kids(phone.el).some((c) => cls(c).includes("wb-scene-area") && c.children.includes(phone.kpis.el)), trackInDock: kids(phone.el).some((c) => cls(c).includes("wb-dock") && c.children.includes(phone.track.el)) };
out.order = kids(phone.main).map((c) => cls(c)[0] || c.tagName);

// the sheet's event: at full the frame says so (a class), and the scene it holds is paused; a sheet that goes un-covers it
const listener = (phone.main.listeners["wb-drawer"] || [])[0];
out.hasListener = typeof listener === "function";
const sceneArea = kids(phone.el).find((c) => cls(c).includes("wb-scene-area"));
listener({ detail: { position: "full", covering: true } });
const full = [cls(phone.el).includes("is-sheet-full"), sceneArea.inert];
listener({ detail: { position: "half", covering: false, dragging: true, rising: true } });
const rising = [cls(phone.el).includes("is-sheet-full"), cls(phone.el).includes("is-sheet-rising"), sceneArea.inert];
listener({ detail: { position: "half", covering: false } });
out.sheetFull = [full[0], cls(phone.el).includes("is-sheet-full")];
out.inert = { full: full[1], rising: rising, after: [cls(phone.el).includes("is-sheet-rising"), sceneArea.inert] };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_frame_stacks_the_cards_over_the_scene_on_a_phone_and_hears_the_sheet(tmp_path):
    got = run_node(tmp_path, FRAME_SCRIPT)
    assert got["desk"] == {"float": 0, "kpisInScene": True, "trackInDock": True}, "off the phone the KPI cards stand in the scene area and the tracking bar in the dock (R-8)"
    assert got["phone"]["kpisInScene"] is False and got["phone"]["trackInDock"] is False
    assert got["phone"]["float"] == ["pui-card wb-track", "wb-kpis"], "R-10: on the phone they float at the top of the scene, the tracking bar first, then the two KPI tiles"
    assert got["order"][:2] == ["wb-sr", "wb-notice-box"] and got["order"][-1] == "wb-float"
    assert got["hasListener"] is True and got["sheetFull"] == [True, False], "the frame marks 'full' while the sheet covers the scene"
    assert got["inert"] == {"full": True, "rising": [False, True, False], "after": [False, False]}, \
        "the scene area is inert while the sheet covers it (the camera buttons and the canvas leave the tab order); a rising drag puts the cards away and the scene is live"


def test_the_frame_pauses_the_scene_while_the_sheet_covers_it_and_the_control_room_pauses_its_own():
    frame = (FRAME / "frame.js").read_text(encoding="utf-8")
    assert "main.addEventListener(DRAWER_EVENT" in frame and "world.setPaused(covering)" in frame and "if (covering) world.setPaused(true)" in frame, \
        "the frame's world is paused by the sheet's event, and a world made while the sheet covers is paused as it is made"
    engine = (JS / "scene" / "engine.js").read_text(encoding="utf-8")
    assert "setPaused(on)" in engine and "loop.setHidden(document.hidden || paused)" in engine, "the pause is the tab-hidden rule with one more reason"
    control = (VIEWS / "control.js").read_text(encoding="utf-8")
    assert "panel.el.addEventListener(DRAWER_EVENT" in control and "engine.setPaused(" in control, "the Control room draws its own scene and pauses it itself"
    # the camera is fitted in what the cards and the sheet leave: the phone's insets come from their rectangles, not from a constant
    assert "const stack = float.getBoundingClientRect()" in frame and 'main.querySelectorAll(".wb-drawer")' in frame and "Math.min(...sheets.map" in frame, \
        "R-10: the cards float at the top (the top inset) and the sheet is at the bottom (the bottom inset)"
    for name in ("city", "building", "floor", "lobby-scene", "control"):
        text = (VIEWS / f"{name}.js").read_text(encoding="utf-8")
        assert "new ResizeObserver(() => { if (engine) engine.refit(); })" in text, f"{name}: a resize recomputes the fit"
    for name in ("city", "building", "floor"):
        text = (VIEWS / f"{name}.js").read_text(encoding="utf-8")
        assert not re.search(r"bottom: \d+, pad", text) or name == "building", f"{name}.js sets no constant for the room the cards and the sheet take"


# --- the Building's floor card hangs at the bottom on the phone --------------------------------------------------------------------

CORNER = r"""
import { cornerPosition, fitInsets } from "@JS@/scene/labels.js";
const out = {};
// the phone's card: bottom left, hung from its point, and the diorama is fitted above it
out.bottom = cornerPosition({ w: 375, h: 600 }, { right: 70, top: 8, bottom: 100, cornerRight: 10, cornerLeft: 10, cornerBottom: 160 });
out.bottomDefault = cornerPosition({ w: 375, h: 600 }, { cornerBottom: 160 });
out.fit = [fitInsets({ top: 8, bottom: 100, right: 70, cornerRight: 10, cornerBottom: 160 }, 78, 8), fitInsets({ bottom: 100, cornerBottom: 160 }, 0)];
// the older shapes are as they were
out.top = [cornerPosition({ w: 375, h: 300 }, { right: 70, top: 80, cornerRight: 10 }), cornerPosition({ w: 800, h: 600 }, { right: 300, top: 64 })];
out.topFit = [fitInsets({ top: 80, right: 70, cornerRight: 10 }, 78, 8), fitInsets({ top: 64, right: 300 }, 90), fitInsets(undefined, 50)];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_floor_card_of_the_building_hangs_from_a_point_at_the_bottom_and_the_older_anchors_are_unchanged(tmp_path):
    got = run_node(tmp_path, CORNER)
    assert got["bottom"] == {"x": 10, "y": 440, "bottom": True}, "bottom left, 160 px above the scene's foot"
    assert got["bottomDefault"] == {"x": 10, "y": 440, "bottom": True}
    assert got["fit"][0] == {"top": 8, "bottom": 246, "right": 70, "cornerRight": 10, "cornerBottom": 160}, "the diorama is fitted above the card: 160 + 78 + 8"
    assert got["fit"][1] == {"bottom": 100, "cornerBottom": 160}
    assert got["top"] == [{"x": 365, "y": 80}, {"x": 500, "y": 64}]
    assert got["topFit"] == [{"top": 166, "right": 70, "cornerRight": 10}, {"top": 64, "right": 300}, {}]
    building = (VIEWS / "building.js").read_text(encoding="utf-8")
    assert "cornerBottom: level + PHONE_TOOLS_H" in building and "cornerLeft: 10" in building and "cornerRight: 10" in building
    assert re.search(r"\.wb-corner-card\.is-bottom \{ transform: translate\(0, -100%\); \}", CSS)
    assert re.search(r"\.wb-floor-steps \{[^}]*translate: 0 calc\(0px - var\(--wb-y, 10px\)\)", "\n".join(PHONE) + CSS), "the floor steps stand level with the camera buttons"


# --- the engine: a sheet that covers the scene pauses it as a hidden tab does, and the fit is left alone meanwhile ---------------------------------------

PAUSE = ENGINE_PAGE_JS + PRODUCT_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
const host = document.createElement("div");
let insets = { left: 0, right: 0, top: 0, bottom: 0, pad: 1.04 };
let insetReads = 0;
const engine = createEngine(host, { label: "City", getInsets: () => { insetReads += 1; return insets; }, onOpen() {}, onHover() {}, onUnavailable() {} });
const stats = () => engine.canvas.wbStats();
engine.show("world", models.city(), "City");
frame(34); frame(34);
const out = { start: stats().hidden };
const view0 = engine.canvas.wbStats().view;
engine.setPaused(true);
out.paused = stats().hidden;
engine.zoomBy(1.5);
out.framesWhilePaused = frame(34) + frame(34);
const reads = insetReads;
insets = { ...insets, bottom: 300 };
engine.refit();                                           // the sheet's size changed while it covers the scene
out.readsWhilePaused = insetReads - reads;
document.hidden = false;
(document.listeners.visibilitychange || []).forEach((fn) => fn());   // the tab is shown again: a sheet that still covers keeps it paused
out.afterVisible = stats().hidden;
engine.setPaused(true);                                   // the same again is no change
out.twice = stats().hidden;
engine.setPaused(false);
out.resumed = stats().hidden;
out.readsOnResume = insetReads - reads;                    // the one fit that was left, in the room the page has now
out.framesAfter = frame(34);
document.hidden = true;
engine.setPaused(false);
(document.listeners.visibilitychange || []).forEach((fn) => fn());
out.tabHidden = stats().hidden;
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_scene_paused_by_the_sheet_draws_nothing_leaves_the_fit_and_resumes_with_one_fit(tmp_path):
    got = run_node_engine(tmp_path, PAUSE)
    assert got["start"] is False and got["paused"] is True, "setPaused(true) hides the loop as a hidden tab does"
    assert got["framesWhilePaused"] == 0, "a render asked for while the sheet covers the scene is not drawn"
    assert got["readsWhilePaused"] == 0, "the fit is left as it was while the sheet covers the scene (the person's zoom and pan are not re-clamped to a room they will not have)"
    assert got["afterVisible"] is True and got["twice"] is True, "a tab shown again does not draw a scene the sheet still covers"
    assert got["resumed"] is False and got["readsOnResume"] == 1 and got["framesAfter"] >= 1, "setPaused(false) draws again, with the one fit that was left, in the room it has now"
    assert got["tabHidden"] is True, "a hidden tab stays hidden whatever the sheet says"


KPI = r"""
import { FakeNode } from "@FAKE@";
import { createKpis } from "@JS@/frame/kpis.js";
const k = createKpis();
const cards = () => [...k.el.walk()].filter((n) => n instanceof FakeNode && (n.attrs.class || "").includes("pui-card"));
k.update({ decisions: 1, runs: 3, runsCap: 20, usd: 1.2, usdCap: 5 }, "ready");
const one = cards().map((c) => [c.title, c.attrs["aria-label"]]);
console.log(JSON.stringify({ one, count: cards().length }));
"""


@needs_node
def test_the_two_kpi_tiles_keep_the_cap_in_their_name_since_the_phone_does_not_draw_it(tmp_path):
    got = run_node(tmp_path, KPI)
    assert got["count"] == 2, "R-5: two cards, runs and spend; the card of open decisions is gone"
    assert got["one"][0][1] == "Runs today 3 of 20" and got["one"][1][1].startswith("Spend today $1.20 of $5.00"), \
        "the runs and the spend tiles keep the cap in their name when the phone does not draw it"
