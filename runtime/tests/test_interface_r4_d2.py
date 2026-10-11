"""Tests of R4-D2 (A-84): a Building that opened with the camera far away.

The cause was in the camera's fit, not in a project's data: two cards of KPIs stand in a column at the left, and the fit read a column as a strip that takes the whole left
side (`obstacleInset`), though the cards cover only the top of it. On a page too narrow to hold that strip, the panel and the column of plates (a 948 px window: 240 + 640 of 948)
the free rectangle was a hundred pixels wide and a tower of four floors stood in it, small, with its plates over the middle of the scene. A project with one card (the second
card is shown only for a cap in use) was read as a block at the top and had room, so the neighbours "opened fine". The fix: the Building offers the cards' other reading beside the first
(`alternatives`), and the camera keeps the reading that lets the tower stand larger. No browser and no model: the pure fit, the frame's insets and the real engine run under Node.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_d2.py
"""
from __future__ import annotations

import standin_tree as st
from test_interface_scene_round3 import ENGINE_PAGE_JS, PRODUCT_JS, needs_node, run_node, run_node_engine

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"


def text(path) -> str:
    return (INTERFACE / path).read_text(encoding="utf-8")


# --- the pure choice ---------------------------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_fit_keeps_the_first_reading_unless_another_lets_the_subject_stand_clearly_larger(tmp_path):
    got = run_node(tmp_path, r"""
import { bestFit, BETTER_FIT } from "@JS@/scene/fit.js";
const frustum = (w) => ({ left: -w / 2, right: w / 2, top: 5, bottom: -5 });
const fitOf = (ins) => frustum(ins.w);
const pick = (...ws) => bestFit(ws.map((w) => ({ w })), fitOf).index;
console.log(JSON.stringify({
  one: pick(10), alone: bestFit([{ w: 10 }], fitOf).frustum.right,
  tie: pick(10, 10), slightly: pick(10, 9.9), clearly: pick(10, 5), worse: pick(10, 20),
  third: pick(10, 9.9, 4), better: BETTER_FIT,
}));
""")
    assert got["one"] == 0 and got["alone"] == 5, "one reading is the fit"
    assert got["tie"] == 0 and got["slightly"] == 0 and got["worse"] == 0, "a tie, a gain of a few percent or a worse reading keeps the first: the usual fit does not move"
    assert got["clearly"] == 1 and got["third"] == 2, "a reading that lets the subject stand much larger wins, whichever place it is in"
    assert 0.9 <= got["better"] < 1


# --- the frame's other reading of the cards ---------------------------------------------------------------------------------------------------------------------

FRAME_JS = ENGINE_PAGE_JS + r"""
import { createFrame } from "@JS@/frame/frame.js";
const root = document.createElement("div");
const fr = createFrame(root, { onSelectProject() {}, onForgetToken() {}, onRetry() {} });
const rect = (left, top, w, h) => ({ left, top, width: w, height: h, right: left + w, bottom: top + h });
const cards = (r) => { fr.kpis.el.getBoundingClientRect = () => r; };
const side = (ins) => ({ left: ins.left, top: ins.top });
"""


@needs_node
def test_two_cards_in_a_column_take_the_left_by_default_and_the_top_when_read_as_a_block(tmp_path):
    got = run_node(tmp_path, FRAME_JS + r"""
const out = {};
cards(rect(16, 72, 208, 144));                      // the two cards of a 948 px window: a column 208 by 144, taller than it is wide against the scene
out.twoPlain = side(fr.insets(null));
out.twoAbove = side(fr.insets(null, { cardsAbove: true }));
cards(rect(16, 72, 208, 72));                       // one card: already a block at the top
out.onePlain = side(fr.insets(null));
out.oneAbove = side(fr.insets(null, { cardsAbove: true }));
cards(rect(16, 62, 480, 62));                       // a row of cards (the tablet layout): the top either way
out.rowPlain = side(fr.insets(null));
out.rowAbove = side(fr.insets(null, { cardsAbove: true }));
console.log(JSON.stringify(out));
""")
    assert got["twoPlain"] == {"left": 240, "top": 16}, "read as a strip, a column of two cards takes the whole left side (its right edge and 16 px)"
    assert got["twoAbove"] == {"left": 16, "top": 228}, "read as a block, it takes the top: the subject may stand under it from the left margin"
    assert got["onePlain"] == got["oneAbove"] and got["onePlain"]["left"] == 16, "a single card is a block at the top already, the other reading is the same one"
    assert got["rowPlain"] == got["rowAbove"] and got["rowPlain"]["left"] == 16, "a row of cards takes the top whichever way it is read"


# --- the engine keeps the larger tower ----------------------------------------------------------------------------------------------------------------------------

ENGINE_BUILDING_JS = ENGINE_PAGE_JS + PRODUCT_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
// the Building of the shop in a canvas of 1280 by 720, with the free rectangle a page leaves it: `give(alternatives)` is what `getInsets` answers
async function widthOf(base, alternatives) {
  const host = document.createElement("div");
  const engine = createEngine(host, { label: "Building", getInsets: () => ({ ...base, pad: 1, alternatives }), onOpen() {}, onHover() {} });
  engine.show("world", models.building(null), "Building");
  for (let i = 0; i < 200; i++) frame(1000 / 30);
  const v = engine.canvas.wbStats().view;
  return +(v.right - v.left).toFixed(4);
}
"""


@needs_node
def test_a_building_beside_a_column_of_cards_takes_the_reading_that_gives_the_tower_room(tmp_path):
    got = run_node_engine(tmp_path, ENGINE_BUILDING_JS + r"""
// a narrow page: the strip at the left (240), the panel and the plates at the right (640) leave 400 of 1280 here, and the tower is also tall; the other reading, the cards over the top
const strip = { left: 240, right: 880, top: 16, bottom: 16 };
const block = { left: 16, right: 880, top: 228, bottom: 16, pad: 1 };
const out = { plain: await widthOf(strip, []), offered: await widthOf(strip, [block]) };
// a roomy page: the same offer is no better, so the first reading stays and the camera does not move
const roomy = { left: 240, right: 300, top: 16, bottom: 16 };
const roomyBlock = { left: 16, right: 300, top: 228, bottom: 16, pad: 1 };
out.roomyPlain = await widthOf(roomy, []);
out.roomyOffered = await widthOf(roomy, [roomyBlock]);
console.log(JSON.stringify(out));
""")
    assert got["offered"] < got["plain"] * 0.9, f"with the cards offered as a block the tower stands larger (the view is {got['offered']} wide, not {got['plain']})"
    assert got["roomyOffered"] == got["roomyPlain"], "where the plain reading already gives the tower its room, the camera is where it always was"


# --- the plates keep the first reading's top ---------------------------------------------------------------------------------------------------------------------

@needs_node
def test_a_reading_that_moves_the_camera_top_leaves_the_plates_column_and_the_corner_where_they_stood(tmp_path):
    got = run_node(tmp_path, r"""
import { placeLabels, cornerPosition } from "@JS@/scene/labels.js";
const node = () => { const style = {}; return { style: { setProperty: (k, v) => { style[k] = v; } }, _style: style, classList: { toggle() {}, add() {}, remove() {}, contains: () => false }, offsetWidth: 230, offsetHeight: 66 }; };
const column = (insets) => {
  const entries = [0, 1, 2].map((i) => ({ spec: { place: "column", anchor: { y: 10 + i } }, node: node(), width: 230, height: 66 }));
  placeLabels(entries, (a) => ({ x: 300, y: a.y }), { insets, size: { w: 948, h: 627 } });
  return entries.map((e) => e.node._style["--wb-y"]);
};
const size = { w: 948, h: 627 };
const base = { left: 240, right: 640, top: 16, bottom: 16, plateRight: 270 };
const block = { ...base, left: 16, top: 228 };
console.log(JSON.stringify({
  base: column(base), block: column(block), kept: column({ ...block, plateTop: base.top }),
  cornerBase: cornerPosition(size, base), cornerBlock: cornerPosition(size, block), cornerKept: cornerPosition(size, { ...block, plateTop: base.top }),
}));
""")
    assert got["block"] != got["base"], "without `plateTop` the block reading pushes the plates' column down with the camera's top (the defect this guards)"
    assert got["kept"] == got["base"], "with `plateTop` the plates' column stands where the first reading puts it"
    assert got["cornerKept"] == got["cornerBase"] and got["cornerBlock"] != got["cornerBase"], "and so does the corner slot"


# --- the Building's two readings, from its own function --------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_buildings_insets_offer_one_alternative_for_two_cards_and_none_for_one_with_the_base_sides_shared(tmp_path):
    got = run_node(tmp_path, r"""
import { desktopInsets, PLATE_GAP_X, PLATE_SHIFT } from "@JS@/views/building.js";
const rect = (top, bottom, h) => ({ top, bottom, height: h });
const make = (cardsReading) => ({
  main: { getBoundingClientRect: () => rect(0, 700, 700) }, track: { el: { getBoundingClientRect: () => rect(600, 700, 100) } },
  plateWidth: () => 230,
  insets: (panel, opts) => (opts.cardsAbove ? cardsReading : { left: 240, right: 356, top: 16, bottom: 130, pad: 1.04 }),
});
const base = { left: 240, right: 356, top: 16, bottom: 130, pad: 1.04 };
const two = desktopInsets(make({ left: 16, right: 356, top: 228, bottom: 130, pad: 1.04 }), {}, { dim: false }, base);
const one = desktopInsets(make(base), {}, { dim: false }, base);
console.log(JSON.stringify({ two, one, plates: 230 + PLATE_GAP_X + PLATE_SHIFT, shift: PLATE_SHIFT }));
""")
    assert got["one"]["alternatives"] == [], "one card reads the same either way: nothing is offered"
    two, alt = got["two"], got["two"]["alternatives"]
    assert len(alt) == 1 and alt[0]["left"] == 16 and alt[0]["top"] == 228, "two cards: the block reading is offered"
    assert two["right"] == alt[0]["right"] == 356 + got["plates"] and two["plateRight"] == alt[0]["plateRight"] == 356 + got["shift"], "the panel and the plates take the same room in both readings"
    assert two["bottom"] == alt[0]["bottom"] == 116, "the tracking bar bounds both from below (700 - 600 + 16)"
    assert two["pad"] == alt[0]["pad"] == 1 and alt[0]["plateTop"] == two["top"] == 16, "no padding in either, and the plates' column keeps the first reading's top"


# --- a tower with room under the cards keeps the block reading -------------------------------------------------------------------------------------------------------

@needs_node
def test_at_1280_by_720_with_two_cards_a_tower_of_one_floor_stands_larger_under_the_cards_and_clear_of_them(tmp_path):
    # a tower of one floor is wide and low: the first reading leaves it the width between the strip (240) and the panel and plates (628), the block reading from the margin (16).
    # Looked at in the served page (R4-D2 report, shots `real-solo-1280x720-*`): the tower stands below the cards (their bottom edge is 216, the block's top 228) and to the
    # right of the camera buttons, so the larger reading is kept, here and wherever it is better by the margin
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + PRODUCT_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
snapshot.details[A].agents = snapshot.details[A].agents.filter((a) => a.name === "planning");   // one agent: one floor
async function widthOf(alternatives) {
  const host = document.createElement("div");
  const engine = createEngine(host, { label: "Building", getInsets: () => ({ left: 240, right: 628, top: 16, bottom: 16, pad: 1, alternatives }), onOpen() {}, onHover() {} });
  engine.show("world", models.building(null), "Building");
  for (let i = 0; i < 200; i++) frame(1000 / 30);
  const v = engine.canvas.wbStats().view;
  return { width: +(v.right - v.left).toFixed(4), towers: engine.canvas.wbStats().towers[A] };
}
console.log(JSON.stringify({ plain: await widthOf([]), offered: await widthOf([{ left: 16, right: 628, top: 228, bottom: 16, pad: 1, plateTop: 16 }]) }));
""")
    assert got["plain"]["towers"] == 1 and got["offered"]["towers"] == 1, "the one-floor building opens"
    assert got["offered"]["width"] < got["plain"]["width"] * 0.9, f"a tower of one floor stands clearly larger in the block reading ({got['offered']['width']} against {got['plain']['width']} of view)"


# --- the page asks for both readings -----------------------------------------------------------------------------------------------------------------------------

def test_the_building_offers_the_cards_other_reading_and_the_engine_and_frame_know_it():
    building = text("js/views/building.js")
    assert "frame.insets(panel, { notice: !(about && about.dim) })" in building, "the usual reading is asked as it was (R4-B4)"
    assert "cardsAbove: true" in building and "alternatives:" in building, "R4-D2: the other reading (the cards as a block at the top) is offered beside it"
    getter = building[building.index("getInsets: (about) =>"):]
    assert "frame.isPhone()" in getter and getter.index("frame.isPhone()") < getter.index("desktopInsets("), "the phone has its own insets and offers nothing: only the desktop and tablet path calls desktopInsets"
    engine = text("js/scene/engine.js")
    assert "bestFit(choices, fitOf)" in engine and "given.alternatives" in engine, "the engine keeps the reading that lets the subject stand larger"
    frame = text("js/frame/frame.js")
    assert "cardsAbove = false" in frame and "part === kpis.el" in frame, "the frame can read the cards as a block over the subject"
    assert "alternatives" in text("README.md") and "cardsAbove" in text("README.md"), "the README says what the Building offers the camera"
