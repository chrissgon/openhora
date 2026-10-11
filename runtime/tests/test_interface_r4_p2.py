"""Tests of the frame's polish after the round-4 final check (R4-P2): the defects F1-D3, F1-D4, F1-D5b, F1-D10, F1-D12, F1-D13, F1-D14, F2-D9 and F2-D10 against the
prototype's frame, and M-32 (no zoom on the phone, fields at 16 px, reading text at 16 px, chips and meta lines at 12 px at least). No browser and no model: the modules run
under Node with a fake document, as the other interface tests do; the served page was looked at by the package's report (`reports/r4/R4-P2.md` of the plan folder).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_p2.py
"""
from __future__ import annotations

import re

from interface_css import css_file, interface_css
from test_interface_adj_b1 import run_scene_dom, run_view
from test_interface_adjustments import run_node
from test_interface_floor import INTERFACE, needs_node

JS = INTERFACE / "js"
CSS = interface_css()
HTML = (INTERFACE / "index.html").read_text(encoding="utf-8")


def phone_blocks(css: str) -> list[str]:
    """The bodies of every `@media (max-width: 899px)` block of `css`, by brace matching."""
    out = []
    for found in re.finditer(r"@media \(max-width: 899px\)\s*\{", css):
        depth, i = 1, found.end()
        while depth and i < len(css):
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append(css[found.end():i - 1])
    return out


def outside_phone(css: str) -> str:
    """`css` without its phone blocks and without its comments."""
    for body in phone_blocks(css):
        css = css.replace(body, "")
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# --- M-32: the phone cannot be zoomed and its text is readable without zoom --------------------------------------------------------------

def test_the_viewport_stops_zoom_and_the_phone_has_no_double_tap_zoom():
    viewport = re.search(r'<meta name="viewport" content="([^"]+)"', HTML).group(1)
    assert "maximum-scale=1" in viewport and "user-scalable=no" in viewport and "initial-scale=1" in viewport, "M-32: the page cannot be zoomed"
    base = css_file("base")
    base_phone = "\n".join(phone_blocks(base))
    assert re.search(r"html, body \{ touch-action: manipulation; \}", base_phone), "M-32: a tap is a tap, with no double-tap zoom, on the phone"
    assert "touch-action: manipulation" not in outside_phone(base), "only the phone has it"
    assert ".wb-canvas { display: block; width: 100%; height: 100%; cursor: grab; touch-action: none; }" in css_file("frame"), "the scene's canvas keeps its own pan"


def test_the_phone_sets_the_librarys_base_size_and_the_fields_to_16px():
    base = css_file("base")
    base_phone = "\n".join(phone_blocks(base))
    assert re.search(r":root \{ --pui-font-size: 1rem; \}", base_phone), "every button, tab, field and row of the library is 16 px on the phone"
    assert re.search(r"\.pui-input, \.wb-field-input, \.wb-select, \.wb-file, input, textarea, select \{ font-size: 16px; \}", base_phone), "a field is 16 px: a phone's browser does not zoom into it"
    assert "--pui-font-size" not in outside_phone(base), "the library's size is not touched above the phone"


def test_the_reading_text_is_16px_and_the_small_text_stays_at_12px_or_more_on_the_phone():
    base = "\n".join(phone_blocks(css_file("base")))
    frame = "\n".join(phone_blocks(css_file("frame")))
    token = "\n".join(phone_blocks(css_file("token")))
    for selector in (".wb-field", ".wb-field-label", ".wb-tab", ".wb-viewer-body", ".wb-md", ".wb-refusal"):
        assert re.search(rf"[ ,]{re.escape(selector)}[,\s][^{{]*\{{ font-size: 16px; \}}", base), f"{selector} is 16 px on the phone"
    assert re.search(r"\.wb-md h1 \{ font-size: 20px; \}", base) and re.search(r"\.wb-plan-body \.wb-md \{ font-size: 16px; \}", base)
    for selector in (".wb-frame { font-size: 16px; }", ".wb-bottom-bar .wb-crumb-nav { font-size: 16px; }", ".wb-req-option { font-size: 16px; }"):
        assert selector in frame, f"the frame on the phone: {selector}"
    assert re.search(r"\.wb-empty, \.wb-notice, \.wb-foot-row, .*\.wb-wait-title, .*\.wb-track-title.* \{ font-size: 16px; \}", frame), "the list rows, the cards and the notice are 16 px"
    assert ".tk-text { font-size: 16px; }" in token and ".tk-cap { font-size: 12px;" in token, "the token prompt's text is 16 px and its captions 12 px"
    # no text of these three stylesheets goes under 12 px on the phone
    for name, body in (("base", base), ("frame", frame), ("token", token)):
        small = [m for m in re.findall(r"font-size: (\d+)px", body) if int(m) < 12]
        assert not small, f"{name}.css has a phone font size under 12 px: {small}"


# --- F1-D3, F1-D4: the switcher ------------------------------------------------------------------------------------------------------------

SWITCHER = r"""
import { FakeNode, find, all } from "@FAKE@";
import { createSwitcher } from "@JS@/frame/switcher.js";

const sw = createSwitcher({ onSelect() {}, onForgetToken() {}, onOpen() {}, onAdd() {}, onLeave() {} });
const root = new FakeNode("div");
root.append(sw.el);
const tx = (n) => (n ? n.textContent : null);
const group = () => find(sw.el, ".wb-switch-group");
const project = (id, name) => ({ id, name, accepted: true, badge: 0, sub: "No request is open" });
const out = {};

// loading: the main button is shown, disabled, with its swap icon, and the group is marked (F1-D4)
sw.update({ projects: [], selectedId: null, heading: "Projects", loading: true });
const main = find(sw.el, ".wb-switch-main");
out.loading = { tag: main.tagName, disabled: main.disabled, marked: group().cls().includes("is-loading"), swap: !!find(main, ".wb-switch-swap"), name: tx(find(main, ".wb-switch-name")), label: main.getAttribute("aria-label"), chevron: find(sw.el, ".wb-switch-chevron").disabled };
// the read answered with none: a label, not marked, the card has its foot alone (F1-D3)
sw.update({ projects: [], selectedId: null, heading: "Projects: choose", loading: false });
out.none = { tag: find(sw.el, ".wb-switch-main").tagName, marked: group().cls().includes("is-loading"), headHidden: find(sw.el, ".wb-listbox-head").hidden, listHidden: find(sw.el, ".wb-listbox").hidden, emptyRow: !!find(sw.el, ".wb-listbox-empty"), foot: all(sw.el, "button.wb-foot-row").length };
// with projects: the head is back, the button cycles
sw.update({ projects: [project("a", "northwind-shop"), project("b", "tinykv-docs")], selectedId: "a", heading: "Projects: choose", loading: false });
out.two = { tag: find(sw.el, ".wb-switch-main").tagName, disabled: find(sw.el, ".wb-switch-main").disabled, headHidden: find(sw.el, ".wb-listbox-head").hidden, head: tx(find(sw.el, ".wb-listbox-head")), marked: group().cls().includes("is-loading") };
// a project already shown is never dimmed by a later loading flag
sw.update({ projects: [project("a", "northwind-shop"), project("b", "tinykv-docs")], selectedId: "a", heading: "Projects", loading: true });
out.keeps = { disabled: find(sw.el, ".wb-switch-main").disabled, marked: group().cls().includes("is-loading") };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_switcher_is_muted_and_disabled_while_loading_and_the_card_is_its_foot_alone_with_no_project(tmp_path):
    got = run_view(tmp_path, SWITCHER)
    assert got["loading"] == {"tag": "BUTTON", "disabled": True, "marked": True, "swap": True, "name": "No project", "label": "No project, loading the projects", "chevron": False}, \
        "frame.html Loading: the name, the swap icon and the chevron muted, the button disabled; the chevron stays usable (Forget the token is the way out of a read that never ends)"
    assert got["none"]["tag"] != "BUTTON" and got["none"]["marked"] is False and got["none"]["headHidden"] is True and got["none"]["listHidden"] is True \
        and got["none"]["emptyRow"] is False and got["none"]["foot"] == 3, "frame.html No project (C-20): the card is its foot alone, with no header and no \"No project\" row"
    assert got["two"] == {"tag": "BUTTON", "disabled": False, "headHidden": False, "head": "Projects: choose", "marked": False}
    assert got["keeps"] == {"disabled": False, "marked": False}, "the loading look is for a switcher with no project"
    css = css_file("frame")
    assert ".wb-switch-group.is-loading .wb-switch-main .wb-icon" in css and ".wb-switch-group.is-loading .wb-switch-chevron { color: var(--pui-text-muted); }" in css


def test_the_row_the_arrow_keys_are_on_has_its_ring_only_for_the_keyboard():
    css = css_file("frame")
    assert ".wb-listbox:focus-visible .wb-option.is-active, .wb-listbox-card.is-keyboard .wb-option.is-active { box-shadow: inset 0 0 0 2px var(--pui-theme); }" in css, \
        "F1-D13: the ring is drawn while the list has the focus by keyboard (:focus-visible, or the class the switcher sets when a key opened or drove it)"
    assert "wb-listbox-empty" not in css, "the empty row is not drawn any more, so its rule is gone"
    assert not re.search(r"(^|\n)\.wb-option\.is-active \{", css), "no ring for the active row on a click"
    assert ".wb-listbox:focus-visible { outline: none; }" in css


# --- F1-D12, F1-D4: the request list and the loading line; F2-D9: nothing waits ---------------------------------------------------------------

TRACK = r"""
import { FakeNode, find, all } from "@FAKE@";
import { createTrack } from "@JS@/frame/track.js";

const track = createTrack({ onOpenSteps() {}, onSelectRequest() {} });
const root = new FakeNode("div");
root.append(track.el);
const out = {};
track.set(null, "loading");
out.loading = { line: !!find(track.el, ".wb-track-loading"), inLeft: !!find(track.el, ".wb-track-left"), text: find(track.el, ".wb-track-loading") ? find(track.el, ".wb-track-loading").textContent : null };
const r = (id, selected = false) => ({ id, title: `Request ${id}`, state: "running", running: false, selected });
const model = { request: { id: 7, title: "Spring", state: "running", project: "shop", projectId: "p1" }, requests: [r(9), r(7, true), r(1)], steps: [], doneCount: 0, total: 0, now: null };
track.set(model, "ready");
const lists = all(track.el, ".wb-req-menu").map((l) => all(l, ".wb-req-option").map((o) => o.getAttribute("data-request")));       // the desktop's list and the phone's
out.order = lists[0];
out.same = lists.length === 2 && lists[0].join() === lists[1].join();
out.model = model.requests.map((q) => q.id);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_request_list_is_oldest_first_and_the_loading_bar_is_one_line(tmp_path):
    got = run_view(tmp_path, TRACK)
    assert got["order"] == ["1", "7", "9"] and got["same"] is True, "F1-D12: frame.html lists the open requests oldest first, in the desktop's bar and the phone's"
    assert got["model"] == [9, 7, 1], "the model keeps its newest-first order for the pages that read it; only the selector sorts its own copy"
    assert got["loading"] == {"line": True, "inLeft": False, "text": "Loading the request..."}, "F1-D4: the loading line is the card's only content, 46 px high"
    assert ".wb-track-loading { grid-column: 1 / -1; }" in css_file("frame")


WAITING = r"""
import { FakeNode, find } from "@FAKE@";
import { createWaitingCard } from "@JS@/frame/waiting.js";

const out = {};
const row = (i) => ({ name: `Row ${i}`, link: `#/${i}`, kind: "Question", title: `Row ${i}`, where: "shop", age: "2 h" });
function shape(card) {
  const root = new FakeNode("div");
  root.append(card.el);
  const none = find(card.el, ".wb-wait-none");
  const chip = find(card.el, ".wb-wait-head .pui-badge") || find(card.el, ".pui-badge");
  return { none: none ? none.textContent : null, chip: chip ? chip.textContent : null };
}
const city = createWaitingCard();
city.set([], "ready");
out.cityZero = shape(city);
city.set([row(1), row(2)], "ready");
out.cityTwo = shape(city);
const floor = createWaitingCard();
floor.setCollapsible(true);
floor.set([], "ready");
out.floorZero = shape(floor);
floor.set([], "loading");
out.floorLoading = shape(floor);
console.log(JSON.stringify(out));
"""


@needs_node
def test_waiting_for_you_says_nothing_waits_instead_of_a_zero_chip(tmp_path):
    got = run_view(tmp_path, WAITING)
    for key in ("cityZero", "floorZero"):
        assert got[key]["none"] == "nothing waits" and got[key]["chip"] is None, f"F2-D9: {key}: the card reads \"nothing waits\", no \"0\" chip"
    assert got["cityTwo"]["none"] is None and got["cityTwo"]["chip"] == "2", "the count chip stays for one or more"
    assert got["floorLoading"]["none"] is None and got["floorLoading"]["chip"] == "...", "while it is read the chip says so"


# --- F1-D4, F1-D5b, F1-D10: the frame's states and the City's fit under the band ---------------------------------------------------------

FRAME = r"""
import { FakeNode } from "@FAKE@";
import * as router from "@JS@/router.js";
import { createFrame } from "@JS@/frame/frame.js";

const root = new FakeNode("div");
const frame = createFrame(root, { onSelectProject() {}, onSelectRequest() {}, onForgetToken() {}, onRetry() {} });
const parts = [...frame.el.walk()];
const byClass = (c) => parts.find((n) => n.cls().includes(c));
const out = {};
frame.setState({ loading: true });
out.loading = [frame.el.cls().includes("is-loading"), frame.el.cls().includes("is-unknown")];
frame.setState({ unknown: true });
out.unknown = [frame.el.cls().includes("is-loading"), frame.el.cls().includes("is-unknown")];
frame.setState();
out.cleared = [frame.el.cls().includes("is-loading"), frame.el.cls().includes("is-unknown")];

// insets: the City under a project that is not accepted is fitted as the Building is (the band does not count); a band for any other reason counts
const rect = (left, top, right, bottom) => ({ left, top, right, bottom, width: right - left, height: bottom - top });
FakeNode.prototype.getBoundingClientRect = () => rect(0, 0, 0, 0);       // a part that is not given a place takes nothing
const scene = frame.sceneHost.parent;
scene.getBoundingClientRect = () => rect(0, 0, 1280, 800);
byClass("wb-topbar").getBoundingClientRect = () => rect(0, 0, 1280, 56);
frame.kpis.el.getBoundingClientRect = () => rect(16, 72, 224, 215);
byClass("wb-dock").getBoundingClientRect = () => rect(16, 700, 880, 784);
frame.noticeBox.getBoundingClientRect = () => rect(236, 72, 856, 345);
frame.noticeBox.hidden = false;
frame.setScreen(router.parse("#/city"), { projectName: null, projectId: null, leaf: null });
const top = () => frame.insets(frame.waitingCard.el).top;
out.cityBand = top();
frame.el.classList.add("is-unaccepted");
out.cityUnaccepted = top();
frame.setScreen(router.parse("#/p/aaaaaaaaaaaa"), { projectName: "shop", projectId: "aaaaaaaaaaaa", leaf: null });
out.buildingUnaccepted = top();                       // a project's screen keeps the rule it asks for: the default counts the band
out.buildingAsked = frame.insets(frame.waitingCard.el, { notice: false }).top;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_frame_marks_loading_and_unknown_and_fits_the_city_under_the_not_accepted_band_as_the_building(tmp_path):
    got = run_scene_dom(tmp_path, FRAME)
    assert got["loading"] == [True, False] and got["unknown"] == [False, True] and got["cleared"] == [False, False], "setState sets the two classes the stylesheet reads"
    assert got["cityBand"] == 357, "a band that is not the not-accepted one (a read that failed) still counts on the City: the scene is fitted below it"
    assert got["cityUnaccepted"] == 68, "F1-D10: the City under a project that is not accepted keeps the buildings' size: the band floats over them (city.html), the header is what counts"
    assert got["buildingUnaccepted"] == 357 and got["buildingAsked"] == 68, "the Building's own call (building.js) is unchanged: its default counts the band, `notice: false` does not"
    css = css_file("frame")
    assert re.search(r"\.wb-frame\.is-loading \.wb-kpis, \.wb-frame\.is-loading \.wb-track, \.wb-frame\.is-unknown \.wb-kpis, \.wb-frame\.is-unknown \.wb-track, \.wb-frame\.is-unknown \.wb-waiting \{ display: none; \}", css), \
        "F1-D4, F1-D5b: a project's screen that is loading draws no cards and no bar; an unknown project draws the band and the camera buttons alone"
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert 'frame.setState({ loading: loading && route.screen !== "city", unknown: !known });' in main, "the City draws its own loading line and cards"
    assert "    loading,\n    projects:" in main, "the switcher is told the read is not back"


def test_the_camera_buttons_follow_the_tiles_when_the_tracking_bar_above_them_changes_height():
    frame = (JS / "frame" / "frame.js").read_text(encoding="utf-8")
    assert "cameraWatch.observe(float);" in frame, "F1-D11: on a phone the stack's height moves the tiles without resizing them; the camera column is placed again when it changes"
    assert 'frame.style.setProperty("--wb-cam-top", bottom > 0 ? `${Math.round(bottom + 10)}px` : "");' in frame, "no card on the page: the stylesheet's own place stands"


def test_the_band_on_a_phone_keeps_within_the_screen():
    phone = "\n".join(phone_blocks(css_file("frame")))
    assert re.search(r"\.wb-notice-box \{ max-height: 40dvh; overflow-y: auto; overscroll-behavior: contain;", phone), "F1-D10: at most 40 percent of the screen, scrolling inside itself"


def test_the_phones_crumbs_drop_the_city_on_the_floor_the_lobby_and_the_control_room():
    phone = "\n".join(phone_blocks(css_file("frame")))
    screens = r'\.wb-frame:is\(\[data-screen="floor"\], \[data-screen="lobby"\], \[data-screen="control"\]\)'
    assert re.search(screens + r" \.wb-bottom-bar \.wb-crumb-item:first-child,\s*" + screens + r" \.wb-bottom-bar \.wb-crumb-item:nth-child\(2\) > \.wb-crumb-sep \{ display: none; \}", phone), \
        "F2-D10, README Floor (b) 6: `northwind-shop / Lobby`; the Building keeps `City / northwind-shop`"


# --- F1-D14: the start line the panel reads ------------------------------------------------------------------------------------------------

PANEL = r"""
import { FakeNode, settle, find, all, textOf } from "@FAKE@";
import { createProjectsPanel } from "@JS@/views/city-projects.js";

const START = "uv run --with keyring==25.7.0 python3 /opt/ck/runtime/service.py --project /work/shop";
const projects = [{ id: "a".repeat(12), name: "shop", folder: "/work/shop" }, { id: "b".repeat(12), name: "blog", folder: "/work/blog" }];
const copy = { clipboard: null, select: () => false, later: () => {} };
const out = {};
const codes = (p) => all(p.el, ".wb-command-code").map(textOf);
const notes = (p) => all(p.el, ".wb-card-note").map(textOf);

// a slow answer: the panel says it is reading and shows no command with a placeholder
let release;
let reads = 0;
const slow = createProjectsPanel({ readStart: () => { reads += 1; return new Promise((resolve) => { release = () => resolve(START); }); }, copy });
slow.setProjects(projects);
slow.openLeave(projects[1].id);
await settle();
out.reading = { codes: codes(slow), notes: notes(slow), reading: !!find(slow.el, ".wb-reading") };
release();
await settle();
out.read = { codes: codes(slow), reading: !!find(slow.el, ".wb-reading"), couldNot: notes(slow).some((n) => n.includes("could not read")) };
slow.close();
slow.openLeave(projects[1].id);
await settle();
out.reopened = { reads, codes: codes(slow) };

// an answer that was empty (no accepted project yet) is asked again the next time
let answers = ["", START];
let asked = 0;
const late = createProjectsPanel({ readStart: async () => { asked += 1; return answers.shift(); }, copy });
late.setProjects(projects);
late.openLeave(projects[1].id);
await settle();
out.first = { codes: codes(late), couldNot: notes(late).some((n) => n.includes("could not read")) };
late.close();
late.openLeave(projects[1].id);
await settle();
out.second = { asked, codes: codes(late), couldNot: notes(late).some((n) => n.includes("could not read")) };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_command_panel_says_it_is_reading_the_start_line_and_asks_again_after_an_empty_answer(tmp_path):
    got = run_node(tmp_path, PANEL)
    assert got["reading"]["codes"] == [] and got["reading"]["reading"] is True and not any("could not read" in n for n in got["reading"]["notes"]), \
        "F1-D14: while the service answers (a second or two) the panel shows no command and no \"could not read\""
    assert got["read"]["codes"] == ["uv run --with keyring==25.7.0 python3 /opt/ck/runtime/service.py --project /work/shop"] and got["read"]["reading"] is False and got["read"]["couldNot"] is False, \
        "the service's own `uv run` start line is the head of the restart line"
    assert got["reopened"] == {"reads": 1, "codes": got["read"]["codes"]}, "a head that was read stays: no second read"
    assert got["first"]["couldNot"] is True and got["first"]["codes"][0].startswith("python3 <the workbench folder>/runtime/service.py"), "an empty answer ends in the placeholder and the note"
    assert got["second"]["asked"] == 2 and got["second"]["couldNot"] is False and got["second"]["codes"] == got["read"]["codes"], "an empty answer is asked again when the panel opens again"


# --- the review of #325 ---------------------------------------------------------------------------------------------------------------------------

KEYBOARD = r"""
import { FakeNode, find } from "@FAKE@";
import { createSwitcher } from "@JS@/frame/switcher.js";

const sw = createSwitcher({ onSelect() {}, onForgetToken() {}, onOpen() {} });
const root = new FakeNode("div");
root.append(sw.el);
const p = (id) => ({ id, name: id, accepted: true, badge: 0, sub: "" });
sw.update({ projects: [p("a"), p("b")], selectedId: "a", heading: "Projects" });
const chevron = find(sw.el, ".wb-switch-chevron");
const card = find(sw.el, ".wb-listbox-card");
const fire = (n, type, event = {}) => (n.listeners[type] || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {}, ...event }));
const out = {};
fire(chevron, "pointerdown");
chevron.click();
out.pointer = [!card.hidden, card.cls().includes("is-keyboard"), find(sw.el, ".is-active") !== null];
chevron.click();
fire(chevron, "keydown", { key: "ArrowDown" });
out.key = [!card.hidden, card.cls().includes("is-keyboard"), find(sw.el, ".is-active") !== null];
chevron.click();       // closed
fire(chevron, "keydown", { key: "Enter" });
chevron.click();       // Enter on a button is a click
out.enter = [!card.hidden, card.cls().includes("is-keyboard")];
chevron.click();
fire(chevron, "pointerdown");
chevron.click();
out.pointerAgain = [!card.hidden, card.cls().includes("is-keyboard")];
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_list_opened_from_the_keyboard_marks_itself_so_the_ring_shows_in_every_browser(tmp_path):
    got = run_view(tmp_path, KEYBOARD)
    assert got["pointer"] == [True, False, True], "a click opens it with the active row set and no keyboard class: no ring"
    assert got["key"] == [True, True, True], "ArrowDown on the chevron opens it with the active row set and the keyboard class"
    assert got["enter"] == [True, True], "Enter or Space (a click after a key) counts as the keyboard"
    assert got["pointerAgain"] == [True, False], "a later click clears it"


NOTICE = r"""
import { FakeNode } from "@FAKE@";
import { createFrame } from "@JS@/frame/frame.js";

const root = new FakeNode("div");
const frame = createFrame(root, { onSelectProject() {}, onSelectRequest() {}, onForgetToken() {}, onRetry() {} });
const rect = (left, top, right, bottom) => ({ left, top, right, bottom, width: right - left, height: bottom - top });
const written = [];
frame.el.style.setProperty = (name, value) => written.push([name, value]);
frame.el.getBoundingClientRect = () => rect(0, 0, 375, 800);
frame.sceneHost.parent.getBoundingClientRect = () => rect(0, 0, 375, 700);
let tilesTop = 100;
frame.kpis.el.getBoundingClientRect = () => rect(8, tilesTop, 367, tilesTop + 32);
const out = {};
frame.notice(null);
out.none = written.filter((w) => w[0] === "--wb-cam-top").slice(-1)[0];
// the band appears and pushes the tiles down: the camera is placed again by the same call, at once
tilesTop = 300;
frame.noticeBox.getBoundingClientRect = () => rect(8, 8, 367, 290);
frame.noticeBox.scrollHeight = 600;
frame.noticeBox.clientHeight = 280;
frame.notice({ kind: "error", lead: "tinykv-docs is not accepted yet", text: "long", command: "uv run x" });
out.band = written.filter((w) => w[0] === "--wb-cam-top").slice(-1)[0];
out.scroller = [frame.noticeBox.getAttribute("tabindex"), frame.noticeBox.getAttribute("role"), frame.noticeBox.getAttribute("aria-label")];
// a band that fits is not a tab stop
frame.noticeBox.scrollHeight = 100;
frame.noticeBox.clientHeight = 100;
frame.notice({ kind: "error", lead: "short", retry: true });
out.fits = [frame.noticeBox.getAttribute("tabindex"), frame.noticeBox.getAttribute("role"), frame.noticeBox.getAttribute("aria-label")];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_camera_is_placed_again_when_the_band_appears_and_a_scrolling_band_is_a_tab_stop(tmp_path):
    got = run_scene_dom(tmp_path, NOTICE)
    assert got["band"] == ["--wb-cam-top", "342px"], "F1-D11 and the review: the band moves the tiles, and the same notice() call writes where the camera goes (tiles' bottom 332 + 10)"
    assert got["scroller"] == ["0", "region", "Notice, scrolls"], "a capped band that scrolls can be scrolled from the keyboard in Safari too"
    assert got["fits"] == [None, None, None]
    frame = (JS / "frame" / "frame.js").read_text(encoding="utf-8")
    assert "cameraWatch.observe(noticeBox);" in frame
    css = css_file("frame")
    assert re.search(r"\.wb-camera-tools \{ left: auto; right: 8px; flex-direction: row; \}", "\n".join(phone_blocks(css))), \
        "on the phone the camera buttons are a row at the right edge, clear of the Building's floor card and plates at the left"


PANEL_SLOW = r"""
import { FakeNode, settle, find, all, textOf } from "@FAKE@";
import { createProjectsPanel } from "@JS@/views/city-projects.js";

const START = "uv run --with keyring==25.7.0 python3 /opt/ck/runtime/service.py --project /work/shop";
const projects = [{ id: "a".repeat(12), name: "shop", folder: "/work/shop" }, { id: "b".repeat(12), name: "blog", folder: "/work/blog" }];
const copy = { clipboard: null, select: () => false, later: () => {} };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const codes = (p) => all(p.el, ".wb-command-code").map(textOf);
const notes = (p) => all(p.el, ".wb-card-note").map(textOf);
const out = {};

// a read that never answers: the panel gives up after startWaitMs, shows the placeholder and its note, and a second opening reads again
let reads = 0;
const never = createProjectsPanel({ readStart: () => { reads += 1; return new Promise(() => {}); }, startWaitMs: 30, copy });
never.setProjects(projects);
never.openLeave(projects[1].id);
await settle();
out.during = { reading: !!find(never.el, ".wb-reading"), codes: codes(never).length };
await wait(80);
out.gaveUp = { reading: !!find(never.el, ".wb-reading"), couldNot: notes(never).some((n) => n.includes("could not read")), code: codes(never)[0] };
never.close();
never.openLeave(projects[1].id);
await wait(5);
out.again = { reads, reading: !!find(never.el, ".wb-reading") };

// an answer that comes after the panel gave up is still taken
let release;
const late = createProjectsPanel({ readStart: () => new Promise((resolve) => { release = () => resolve(START); }), startWaitMs: 20, copy });
late.setProjects(projects);
late.openLeave(projects[1].id);
await wait(60);
out.beforeLate = codes(late)[0];
release();
await wait(20);
out.afterLate = codes(late)[0];

// the person types the folder while the read is out: the field keeps its focus and caret when it lands
let done;
const typing = createProjectsPanel({ readStart: () => new Promise((resolve) => { done = () => resolve(START); }), startWaitMs: 500, copy });
typing.setProjects(projects);
typing.openAdd();
const folder = () => find(typing.el, "input[data-key=project-folder]");
folder().focus();
folder().value = "/work/new";
folder().listeners.input.forEach((fn) => fn());
await settle();
done();
await wait(20);
out.typing = { focus: document.activeElement === folder(), value: folder().value, codes: codes(typing).length };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_command_panel_gives_up_on_a_read_that_never_answers_and_keeps_the_typing_focus(tmp_path):
    got = run_node(tmp_path, PANEL_SLOW)
    assert got["during"] == {"reading": True, "codes": 0}
    assert got["gaveUp"]["reading"] is False and got["gaveUp"]["couldNot"] is True and got["gaveUp"]["code"].startswith("python3 <the workbench folder>/runtime/service.py"), \
        "a read that never answers ends in the placeholder and its note, not in \"Reading...\" for the session"
    assert got["again"] == {"reads": 2, "reading": True}, "opened again, it asks again"
    assert got["beforeLate"].startswith("python3 <the workbench folder>") and got["afterLate"].startswith("uv run --with keyring==25.7.0 python3 /opt/ck/runtime/service.py"), "a late answer is taken"
    assert got["typing"] == {"focus": True, "value": "/work/new", "codes": 1}, "the field keeps its focus and its text when the read lands, and the line is drawn"
