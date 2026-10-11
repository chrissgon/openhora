"""Tests of the round-4 polish of the Floor, the Lobby and the Control room (R4-P3): the disclosure lines of the cards, the card head on one row, the done card's inset, the
unknown agent's head, the Lobby's head with no line, the pointer's bold title, the Desk's "Lobby", the day column of the chart's table, the swipe between tabs on a phone
(A-77, `interface/js/swipe.js`) and the phone's text sizes (M-32). No browser, no model, no service: the pure parts and the bindings run under Node with small stand-ins, the
stylesheets and the sources are read as text.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_p3.py
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from interface_css import css_file, interface_css
from test_interface_adjustments import JS, run_node
from test_interface_floor import INTERFACE, needs_node, NODE

PHONE = re.compile(r"@media \(max-width: 899px\) \{")


def _blocks(css: str):
    """Every top-level rule of a stylesheet as (selector text, body, inside an @media text or None); comments gone."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, stack, pos = [], [], 0
    for m in re.finditer(r"[{}]", css):
        if m.group() == "{":
            stack.append(css[pos:m.start()].strip())
        else:
            body = css[pos:m.start()].strip()
            head = stack.pop()
            if body and not head.startswith("@"):
                media = next((s for s in stack if s.startswith("@media")), None)
                out.append((head, body, media))
        pos = m.end()
    return out


def _phone_text(css: str) -> str:
    return "\n".join(f"{h} {{ {b} }}" for h, b, media in _blocks(css) if media and "max-width: 899px" in media)


# --- the cards (F2-D1, F2-D3, F2-D4, F2-D5, F2-D6, F2-D11) ---------------------------------------------------------------------------------------

CARDS_JS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";

const client = { answer: async () => ({}), release: async () => ({}), route: async () => ({}), flows: async () => ({ flows: [{ flow: "code-change", title: "Code change" }] }), cancel: async () => ({}) };
const env = (extra = {}) => ({ project: "p", now: () => new Date("2026-10-09T12:00:00Z"), api: client, requestIds: new Set([6]), links: { floor: () => "#", lobby: () => "#/p/p/lobby", open: () => "#" }, reread: async () => null, changed() {}, gone() {}, ...extra });
const review = { id: 42, kind: "review", title: "R", body: "b", payload: { returned: [], kept: [] }, payload_sha256: null, status: "open", actions: ["released", "answered"], agent: "brand", task_id: 5, run_id: 4, created_at: "2026-10-09T09:00:00Z" };
const question = { id: 43, kind: "question", title: "Q", body: "b", payload: {}, status: "open", actions: ["answered"], agent: "brand", task_id: 5, created_at: "2026-10-09T09:00:00Z" };
const lost = { id: 44, kind: "question", title: "The route was not recognised", body: "b", payload: { actions: ["choose-flow", "cancel"], raw: "the reply" }, status: "open", actions: ["answered"], agent: null, task_id: 6, created_at: "2026-10-09T09:00:00Z" };
const out = {};
const card = createCard(review, env({ task: async () => null }));
await settle();
const kids = card.el.querySelector(".wb-card-content").children.filter((c) => c.tagName);
out.reviewOrder = kids.map((c) => (c.cls().includes("wb-verdict") ? "verdict" : c.cls().includes("wb-card-actions") ? "buttons" : c.tagName === "TEXTAREA" ? "textarea" : ""));
const verdict = find(card.el, "details.wb-verdict");
out.verdictClass = verdict.attrs.class;
out.verdictSummary = find(verdict, "summary").textContent;
const plain = createCard(question, env());
await settle();
out.plainOnQuestion = all(plain.el, "button.wb-card-plain").length;
out.headOrder = find(plain.el, ".wb-card-head").children.filter((c) => c.tagName).map((c) => c.cls().join(" "));
const route = createCard(lost, env());
await settle();
out.plainOnRoute = all(route.el, "button.wb-card-plain").length;
out.replyClass = find(route.el, "details.wb-raw-reply").attrs.class;
find(route.el, 'button[data-word="choose-flow"]').click();
await settle();
out.routeButton = find(route.el, 'button[data-word="route"]').attrs.class;
out.chooseButton = find(route.el, 'button[data-word="choose-flow"]').attrs.class;
console.log(JSON.stringify(out));
"""

DONE_JS = r"""
import { FakeNode, settle, find } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";

const client = { answer: async () => ({ state: { written: true } }) };
const question = { id: 43, kind: "question", title: "Strategy: who is the shop for?", body: "b", payload: {}, status: "open", actions: ["answered"], agent: "brand", task_id: 5, created_at: "2026-10-09T09:00:00Z" };
const card = createCard(question, { project: "p", now: () => new Date("2026-10-09T12:00:00Z"), api: client, requestIds: new Set(), links: { floor: () => "#", lobby: () => "#", open: () => "#" }, reread: async () => null, changed() {}, gone() {} });
await settle();
find(card.el, "textarea").value = "The price with tax.";
find(card.el, "textarea").listeners.input.forEach((fn) => fn());
find(card.el, 'button[data-word="answered"]').click();
await settle();
await settle();
const content = find(card.el, ".wb-card-content");
console.log(JSON.stringify({ done: Boolean(find(card.el, ".wb-card-done")), contentClass: content ? content.attrs.class : null }));
"""


@needs_node
def test_a_review_card_puts_its_verdict_line_before_its_buttons_and_every_disclosure_is_a_plain_line(tmp_path):
    got = run_node(tmp_path, CARDS_JS)
    assert got["reviewOrder"].index("verdict") < got["reviewOrder"].index("buttons"), "floor.html: Record a verdict stands between the comment and the buttons (F2-D3)"
    assert "wb-disclosure" in got["verdictClass"].split() and "pui-accordion-item" not in got["verdictClass"], "a plain line, not the library's bordered accordion (F2-D3, F2-D4)"
    assert got["verdictSummary"] == "Record a verdict"
    assert "wb-disclosure" in got["replyClass"].split() and "pui-accordion-item" not in got["replyClass"], "Show the agent's reply is a plain line too (F2-D4)"
    plan = (JS / "cards" / "plan.js").read_text(encoding="utf-8")
    assert "pui-accordion-item" not in plan and 'class: "wb-disclosure wb-plan-text"' in plan, "Plan as text is a plain line (F2-D4)"
    cards = (JS / "floor" / "cards.js").read_text(encoding="utf-8")
    assert "pui-accordion-item" not in cards


@needs_node
def test_the_route_question_has_no_plain_text_button_and_its_route_button_is_solid_while_other_cards_keep_theirs(tmp_path):
    got = run_node(tmp_path, CARDS_JS)
    assert got["plainOnQuestion"] == 1, "a question that renders Markdown keeps its Plain text (R-34)"
    assert got["plainOnRoute"] == 0, "lobby.html draws the route question without Plain text (F2-D11)"
    assert "pui-solid" in got["routeButton"].split() and "pui-outline" not in got["routeButton"].split(), "Route with this flow is the solid button (F2-D5)"
    assert "pui-outline" in got["chooseButton"].split(), "Choose a flow stays an outline button (E-20, kept as built)"
    assert "wb-card-kind" in got["headOrder"][0] and "wb-card-meta" in got["headOrder"][1] and "wb-card-plain" in got["headOrder"][2], "the head is the kind, the meta, then Plain text"


@needs_node
def test_the_done_card_adds_no_padding_of_its_own_around_the_done_line(tmp_path):
    got = run_node(tmp_path, DONE_JS)
    assert got["done"] and "is-done" in got["contentClass"].split(), "F2-D6: the done line is the card, its own padding the only inset"
    css = css_file("floor")
    assert re.search(r"\.wb-card-content\.is-done \{ padding: 0; \}", css)


def test_the_card_head_is_one_row_with_the_meta_cut_and_wraps_only_on_a_phone():
    css = css_file("floor")
    head = next(b for h, b, media in _blocks(css) if h == ".wb-card-head" and media is None)
    assert "flex-wrap: nowrap" in head, "F2-D1: floor.html keeps Plain text on the head's row"
    meta = next(b for h, b, media in _blocks(css) if h == ".wb-card-meta" and media is None)
    assert "text-overflow: ellipsis" in meta and "white-space: nowrap" in meta and "min-width: 0" in meta
    phone = _phone_text(css)
    assert re.search(r"\.wb-card-head \{ flex-wrap: wrap; \}", phone), "the phone's head wraps so that nothing of it is cut (R4-A4 review fix 5, kept)"
    assert re.search(r"\.wb-card-plain \{ flex: 1 1 100%", phone)


def test_a_disclosure_is_a_muted_line_with_the_native_marker_and_no_border():
    css = css_file("floor")
    rules = {h: b for h, b, media in _blocks(css) if media is None}
    box = rules[".wb-disclosure"]
    assert "border: 0" in box and "background: none" in box
    line = rules[".wb-disclosure > summary"]
    assert "color: var(--pui-text-muted)" in line and "display: list-item" in line, "the triangle is the browser's own marker (floor.html, lobby.html)"
    assert re.search(r"\.wb-plan-body \{[^}]*background-color: var\(--wb-raised\)", css), "the plan's text keeps its raised ground, the line above it none"


# --- the unknown agent, the Lobby's head and pointer, the Desk, the chart table (F2-D8, F2-D2, F2-D11, F2-D13, F2-D14) -----------------------------


def test_an_agent_that_is_not_in_the_configuration_has_a_head_with_its_name():
    floor = (JS / "views" / "floor.js").read_text(encoding="utf-8")
    assert re.search(r'const unknown = h\("div", \{ class: "wb-floor-unknown", hidden: true \},\s+h\("div", \{ class: "wb-panel-head" \}', floor), "F2-D8: the panel's head, then the sentence and the link"
    assert "unknownTitle.textContent" in floor and "Back to the building" in floor
    css = css_file("floor")
    assert re.search(r"\.wb-floor-unknown \{[^}]*grid-template-rows: auto minmax\(0, 1fr\)", css)


def test_the_lobby_panel_head_has_no_line_under_it_and_the_pointer_title_is_bold():
    css = css_file("lobby")
    assert re.search(r"\.wb-panel-lobby > \.wb-panel-head \{ padding-bottom: 4px; border-bottom: 0; \}", css), "F2-D2: the tabs sit directly under the head, as on the Floor"
    assert re.search(r"\.wb-lobby-tabbar \{[^}]*border-bottom", css), "the line under the tab bar stays (R-43)"
    assert re.search(r"\.wb-pointer-title \{[^}]*font-weight: 600", css) and "var(--pui-text)" in css[css.index(".wb-pointer-title"):css.index(".wb-pointer-title") + 160]
    request = (JS / "views" / "lobby-request.js").read_text(encoding="utf-8")
    assert 'h("strong", { class: "wb-pointer-title", text: item.title || "" })' in request, "F2-D11: the title is bold in the text colour, the date after it muted"


def test_a_document_no_agent_owns_is_named_lobby_in_the_lobby_desk_and_the_chart_days_have_no_tint():
    desk = (JS / "views" / "lobby-desk.js").read_text(encoding="utf-8")
    assert 'text: r.agent ? format.agentWord(r.agent) : "Lobby" }' in desk and '"—"' not in desk, "F2-D13: the Floor's wording for a document with no agent"
    rule = next(b for h, b, media in _blocks(css_file("control")) if h == ".wb-chart-table tbody th")
    assert "background-color: transparent" in rule, "F2-D14: the day column carries no tint of the table head"


def test_the_held_command_of_a_service_that_dispatches_nothing_is_labelled():
    tab = (JS / "floor" / "agent-tab.js").read_text(encoding="utf-8")
    assert '"dispatch off": "Run the next task from the terminal"' in tab, "F2-D7: floor.html labels the held command; the label says what the service's own command does"
    assert "sentence: HELD_COMMAND_LABEL[held.reason]" in tab


# --- A-77: swipe between tabs on a phone ----------------------------------------------------------------------------------------------------------

SWIPE_JS = r"""
import { swipeTarget, ownsTouch, bindSwipe, MIN_DISTANCE } from "@JS@/swipe.js";

class N {
  constructor(opts = {}) { Object.assign(this, { parentElement: null, scrollWidth: 100, clientWidth: 100, field: false, overflowX: "visible", cls: new Set(), listeners: {} }, opts); }
  matches() { return this.field; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  removeEventListener(type) { delete this.listeners[type]; }
  get classList() { const s = this.cls; return { add: (...n) => n.forEach((x) => s.add(x)), remove: (...n) => n.forEach((x) => s.delete(x)), contains: (n) => s.has(n) }; }
  get offsetWidth() { return 0; }
}
globalThis.getComputedStyle = (n) => ({ overflowX: n.overflowX });
let reduced = false;
globalThis.window = { matchMedia: (q) => ({ matches: /reduced-motion/.test(q) ? reduced : true }) };

const ids = ["agent", "inbox", "tasks", "desk"];
const out = {};
out.pure = [
  swipeTarget(ids, "inbox", -120, 5, 200), swipeTarget(ids, "inbox", 120, 5, 200),     // left goes next, right goes back
  swipeTarget(ids, "agent", 120, 0, 200), swipeTarget(ids, "desk", -120, 0, 200),      // no wrap
  swipeTarget(ids, "inbox", -(MIN_DISTANCE - 1), 0, 200),                              // too short
  swipeTarget(ids, "inbox", -100, 60, 200), swipeTarget(ids, "inbox", -100, 49, 200),  // not mostly horizontal / mostly
  swipeTarget(ids, "inbox", -120, 0, 900),                                             // too slow
  swipeTarget(ids, "nope", -120, 0, 200), swipeTarget([], "inbox", -120, 0, 200),      // unknown tab, no tabs
];

const root = new N();
const table = new N({ parentElement: root, scrollWidth: 400, clientWidth: 200, overflowX: "auto" });
const cell = new N({ parentElement: table });
const field = new N({ parentElement: root, field: true });
const text = new N({ parentElement: root });
const scrolled = new N({ parentElement: root, scrollWidth: 120, clientWidth: 100, overflowX: "hidden" });
out.owns = { cell: ownsTouch(cell, root), field: ownsTouch(field, root), text: ownsTouch(text, root), hiddenOverflow: ownsTouch(scrolled, root), rootItself: ownsTouch(root, root) };

let current = "inbox";
let enabled = true;
let phone = true;
const went = [];
const bound = bindSwipe(root, { ids: () => ids, current: () => current, go: (id) => { went.push(id); current = id; }, enabled: () => enabled, phone: () => phone });
const touch = (x, y) => ({ clientX: x, clientY: y });
const drag = (target, from, to, count = 1) => {
  root.listeners.touchstart({ target, touches: Array.from({ length: count }, () => touch(...from)) });
  root.listeners.touchend({ changedTouches: [touch(...to)] });
};
drag(text, [250, 100], [100, 110]); out.left = [...went]; out.slideLeft = [...root.cls];
drag(text, [100, 100], [250, 100]); out.right = [...went];
drag(cell, [250, 100], [100, 100]); out.table = [...went];
drag(field, [250, 100], [100, 100]); out.field = [...went];
drag(text, [250, 100], [100, 100], 2); out.twoFingers = [...went];
enabled = false; drag(text, [250, 100], [100, 100]); out.disabled = [...went]; enabled = true;
phone = false; drag(text, [250, 100], [100, 100]); out.desktop = [...went]; phone = true;
out.slideRight = [...root.cls];
reduced = true; root.cls.clear(); drag(text, [250, 100], [100, 100]); out.reducedClass = [...root.cls]; out.reducedWent = [...went];
bound.destroy();
out.destroyed = Object.keys(root.listeners).length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_swipe_moves_one_tab_only_when_it_is_long_quick_and_mostly_horizontal(tmp_path):
    got = run_node(tmp_path, SWIPE_JS)
    assert got["pure"] == ["tasks", "agent", None, None, None, None, "tasks", None, None, None]


@needs_node
def test_a_swipe_never_starts_on_a_field_a_sideways_scroller_or_a_second_finger_and_only_on_a_phone(tmp_path):
    got = run_node(tmp_path, SWIPE_JS)
    assert got["owns"] == {"cell": True, "field": True, "text": False, "hiddenOverflow": False, "rootItself": False}
    assert got["left"] == ["tasks"], "a swipe to the left goes to the next tab through the screen's own function"
    assert got["right"] == ["tasks", "inbox"], "a swipe to the right goes back"
    assert got["table"] == got["right"] and got["field"] == got["right"], "a table that scrolls sideways and a field keep their touch"
    assert got["twoFingers"] == got["right"] and got["disabled"] == got["right"] and got["desktop"] == got["right"]


@needs_node
def test_the_slide_is_drawn_without_reduced_motion_and_not_under_it_and_the_binding_can_be_removed(tmp_path):
    got = run_node(tmp_path, SWIPE_JS)
    assert got["slideLeft"] == ["is-swipe-next"] and got["slideRight"] == ["is-swipe-prev"], "the panel slides in from the side the swipe came from"
    assert got["reducedClass"] == [] and got["reducedWent"][-1] == "tasks", "under reduced motion the tab changes and nothing slides"
    assert got["destroyed"] == 0


def test_every_tab_bar_on_a_phone_binds_the_one_swipe_module_and_no_view_keeps_a_second_path_to_the_tab():
    for name, panel in (("floor.js", "tabpanel"), ("lobby.js", "panel.body"), ("control.js", "content")):
        source = (JS / "views" / name).read_text(encoding="utf-8")
        assert 'import { bindSwipe } from "../swipe.js";' in source, name
        assert f"bindSwipe({panel}," in source, f"{name} binds the swipe to its tab panel"
        assert "swipe.destroy()" in source, f"{name} lets go of it when the view goes"
    assert "window.location.hash = router.floorHash(project, agent, id)" in (JS / "views" / "floor.js").read_text(encoding="utf-8")
    assert "window.location.hash = router.lobbyHash(project, id)" in (JS / "views" / "lobby.js").read_text(encoding="utf-8")
    assert "go: (id) => go(id)" in (JS / "views" / "control.js").read_text(encoding="utf-8")
    swipe = (JS / "swipe.js").read_text(encoding="utf-8")
    assert "touchstart" in swipe and "{ passive: true }" in swipe and "preventDefault" not in swipe, "the swipe listens and never stops a scroll"
    assert "fetch(" not in swipe and "localStorage" not in swipe and "sessionStorage" not in swipe
    css = css_file("floor")
    assert "@keyframes wb-swipe-in-next" in css and re.search(r"@media \(prefers-reduced-motion: reduce\) \{ \.is-swipe-next, \.is-swipe-prev \{ animation: none; \} \}", css)


# --- M-32: the phone's text and fields in my three stylesheets ------------------------------------------------------------------------------------


def test_the_phones_fields_buttons_and_tabs_are_16_px_and_no_text_is_left_under_12_px():
    for name in ("floor", "lobby", "control"):
        css = css_file(name)
        phone = _phone_text(css)
        # every rule of the stylesheet that sets a size under 12 px is raised to at least 12 on a phone, selector for selector
        for head, body, media in _blocks(css):
            size = re.search(r"font-size:\s*([\d.]+)px", body)
            if media or not size or float(size.group(1)) >= 12:
                continue
            for part in (p.strip() for p in head.split(",")):
                raised = re.search(re.escape(part) + r"[^{}]*\{[^}]*font-size:\s*(\d+(?:\.\d+)?)px", phone)
                assert raised and float(raised.group(1)) >= 12, f"{name}.css: {part} is {size.group(1)} px and stays so on a phone"
    floor = _phone_text(css_file("floor"))
    assert re.search(r"\.wb-panel :is\(input, textarea, select\) \{ font-size: 16px; \}", floor), "every field is 16 px (and the page cannot be zoomed)"
    assert re.search(r"\.wb-panel :is\(button, \.pui-btn\) \{ font-size: 16px; \}", floor)
    assert re.search(r"\.wb-card-body, ", floor) and ".wb-card-line" in floor and ".wb-res-said" in floor
    assert re.search(r"\.wb-lobby-tab \{[^}]*font-size: 16px", _phone_text(css_file("lobby")))
    assert re.search(r"\.wb-control \.wb-tablist \.wb-tab \{ font-size: 16px; \}", _phone_text(css_file("control")))
    assert re.search(r"\.wb-bubble, ", _phone_text(css_file("lobby")))


def test_the_new_rules_name_colours_by_token_only():
    for name in ("floor", "lobby", "control"):
        css = css_file(name)
        start = css.find("A-77") if name == "floor" else css.find("M-32")
        assert start >= 0
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", css[start:]), f"{name}.css: the phone block names no literal colour"
