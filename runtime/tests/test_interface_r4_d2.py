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


# --- the page asks for both readings -----------------------------------------------------------------------------------------------------------------------------

def test_the_building_offers_the_cards_other_reading_and_the_engine_and_frame_know_it():
    building = text("js/views/building.js")
    assert "frame.insets(panel, { notice: !(about && about.dim) })" in building, "the usual reading is asked as it was (R4-B4)"
    assert "cardsAbove: true" in building and "alternatives:" in building, "R4-D2: the other reading (the cards as a block at the top) is offered beside it"
    assert "frame.isPhone()" in building and building.index("frame.isPhone()") < building.index("cardsAbove: true"), "the phone has its own insets and offers nothing"
    engine = text("js/scene/engine.js")
    assert "bestFit(choices, fitOf)" in engine and "given.alternatives" in engine, "the engine keeps the reading that lets the subject stand larger"
    frame = text("js/frame/frame.js")
    assert "cardsAbove = false" in frame and "part === kpis.el" in frame, "the frame can read the cards as a block over the subject"
    assert "alternatives" in text("README.md") and "cardsAbove" in text("README.md"), "the README says what the Building offers the camera"
