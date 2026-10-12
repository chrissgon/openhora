"""Tests of the round-4 polish of the scene (R4-P1): the City's and the Building's defects the final check found (F1-D1 to F1-D9, F1-D11, F2-D15) and A-81, the open building's
facade that fades smoothly. No browser and no model: the world runs under Node with the real three.js and no GPU, the rules of the stylesheets are read as text; what only a
browser shows was looked at in the served page by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_p1.py
"""
from __future__ import annotations

import re

import standin_tree as st
from interface_css import css_file, interface_css
from test_interface_phone_sheet import media_blocks, rules, without_media
from test_interface_scene_round3 import WORLD_JS, needs_node, run_node

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
CSS = interface_css()
SCENE_CSS = (INTERFACE / "scene.css").read_text(encoding="utf-8")


def text(path) -> str:
    return (INTERFACE / path).read_text(encoding="utf-8")


def rule(css: str, selector: str) -> dict:
    found = {}
    for sel, declarations in rules(css):
        if selector in [s.strip() for s in sel.split(",")]:
            found.update(declarations)
    return found


# --- A-81: the facade fades smoothly on the open and the close -------------------------------------------------------------------------------------------------------

SHELL_JS = WORLD_JS + r"""
const { world } = make();
const tower = world.towers.get("a");
// the shell's materials: the walls of every floor and the roof (each tower has clones of its own)
const shell = []; tower.floorGroups.forEach((g) => g.children[0].traverse((n) => { if (n.material) shell.push(n.material); }));
const roof = []; tower.group.children.forEach((ch) => { if (!tower.floorGroups.includes(ch) && ch !== tower.silhouette) ch.traverse((n) => { if (n.isMesh && n.material && n.material.color && n !== tower.beacon?.ring) roof.push(n.material); }); });
const shown = (list) => Math.min(...list.map((m) => (m.transparent ? m.opacity : 1)));
"""


@needs_node
def test_the_open_fades_the_whole_facade_over_many_frames_with_no_step(tmp_path):
    # A-81: the shell (walls, windows, ledges, the door, the canopy) and the roof read their fade over the whole of the opening, not over its first quarter second, and the fade is
    # continuous across the edge where the shell stops being drawn opaque (SOLID): no frame loses more than a tenth of what the one before showed
    got = run_node(tmp_path, SHELL_JS + r"""
world.setFocus("a");
const rows = [[shown(shell), shown(roof)]];
for (let f = 0; f < 120; f++) { world.step(1 / 60); rows.push([shown(shell), shown(roof)]); }
const walls = rows.map((r) => r[0]), roofs = rows.map((r) => r[1]);
console.log(JSON.stringify({ walls, roofs, same: walls.every((w, i) => Math.abs(w - roofs[i]) < 1e-9) }));
""")
    walls = got["walls"]
    assert walls[0] == 1, "closed, the shell is whole"
    drops = [a - b for a, b in zip(walls, walls[1:])]
    assert min(drops) >= -1e-9, "the shell only fades while it opens: it never comes back a little"
    assert max(drops) <= 0.12, f"no frame of the open takes more than a tenth of the facade at once (the largest step is {max(drops):.3f})"
    first_gone = next(i for i, w in enumerate(walls) if w < 0.05)
    assert first_gone >= 30, f"the facade is still there half a second into the open (it was gone at frame {first_gone}: a quarter of a second reads as a cut)"
    assert got["same"] is True, "the roof and the canopy fade with the walls (M-16)"


@needs_node
def test_the_close_brings_the_facade_back_in_as_many_frames_and_ends_solid(tmp_path):
    got = run_node(tmp_path, SHELL_JS + r"""
world.setFocus("a", true);
world.setFocus(null);
const rows = [];
for (let f = 0; f < 200; f++) { const moving = world.step(1 / 60); rows.push([shown(shell), shell.every((m) => m.transparent === false && m.depthWrite === true)]); if (!moving) break; }
console.log(JSON.stringify({ walls: rows.map((r) => r[0]), solid: rows.map((r) => r[1]) }));
""")
    walls = got["walls"]
    rises = [b - a for a, b in zip(walls, walls[1:])]
    assert max(rises) <= 0.12, "no frame of the close adds more than a tenth of the facade"
    assert walls[-1] == 1 and got["solid"][-1] is True, "closed again, the shell is opaque, writes depth and is whole (A-75, B5's clean close)"
    solid_from = next(i for i, s in enumerate(got["solid"]) if s)
    assert all(got["solid"][solid_from:]), "once the walls are solid they stay so to the last frame: no translucent shell after the edge"


@needs_node
def test_a_material_that_turns_translucent_asks_for_a_new_program_and_only_then(tmp_path):
    # A-81: a program is compiled with OPAQUE (alpha forced to 1) while `transparent` is false and is not compiled again when `transparent` alone changes, so a shell first drawn closed
    # stayed whole while it faded. The flip bumps the material's version (`needsUpdate`), and nothing else does: not every frame
    got = run_node(tmp_path, SHELL_JS + r"""
const all = [...new Set([...shell, ...roof])];
const log = [];
const state = all.map((m) => ({ m, before: m.version, was: m.transparent }));
const sample = () => {
  for (const s of state) {
    log.push({ flipped: s.m.transparent !== s.was, bumped: s.m.version > s.before });
    s.before = s.m.version; s.was = s.m.transparent;
  }
};
world.setFocus("a");
for (let f = 0; f < 120; f++) { world.step(1 / 60); sample(); }
world.setFocus(null);
for (let f = 0; f < 240; f++) { const moving = world.step(1 / 60); sample(); if (!moving) break; }
console.log(JSON.stringify({ log, count: all.length, roofs: roof.length }));
""")
    assert got["roofs"] >= 1 and got["count"] > got["roofs"], "the shell and the roof are both checked"
    log = got["log"]
    flips = [row for row in log if row["flipped"]]
    assert len(flips) >= 2, "the shell goes translucent on the open and solid again on the close"
    assert all(row["bumped"] for row in flips), "every flip of `transparent` bumps the material's version"
    assert not any(row["bumped"] and not row["flipped"] for row in log), "a frame that does not flip it asks for no new program"


# --- F1-D7: the City's other buildings go while a building is open and no floor is entered ---------------------------------------------------------------------------

@needs_node
def test_the_other_buildings_shrink_away_in_the_building_and_come_back_with_a_floor(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
const { world } = make();
const others = () => ["b", "c"].map((id) => world.towers.get(id).visTarget.every((v) => v === 0));
const out = { city: ["b", "c"].map((id) => world.towers.get(id).visTarget.every((v) => v === 1)) };
world.setFocus("a", true);
out.building = others();
out.hidden = ["b", "c"].map((id) => world.towers.get(id).floorGroups.every((g) => !g.visible));
world.setFloors("planning", null, true);
out.floor = ["b", "c"].map((id) => world.towers.get(id).visTarget.every((v) => v === 1));
out.shownAgain = ["b", "c"].map((id) => world.towers.get(id).floorGroups.every((g) => g.visible));
world.setFloors(null, null, true);
out.back = others();
world.setFocus(null, true);
out.closed = ["b", "c"].map((id) => world.towers.get(id).visTarget.every((v) => v === 1));
console.log(JSON.stringify(out));
""")
    assert got["city"] == [True, True], "the City draws every building"
    assert got["building"] == [True, True] and got["hidden"] == [True, True], "the Building draws none beside the open one (building.html)"
    assert got["floor"] == [True, True] and got["shownAgain"] == [True, True], "the Floor and the Lobby keep theirs (M-15)"
    assert got["back"] == [True, True], "back from the floor to the Building they go again"
    assert got["closed"] == [True, True], "and they are back in the City"


# --- F1-D3: the empty City is framed on a lot, not on nothing --------------------------------------------------------------------------------------------------------

@needs_node
def test_a_world_with_no_lot_has_a_box_to_frame(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
const kit = createKit(palette);
const world = buildWorld(kit, model({ lots: [] }));
const box = world.subject();
console.log(JSON.stringify({ empty: box.isEmpty(), size: [box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z], ground: world.group.children.length }));
""")
    assert got["empty"] is False, "an empty City has a subject: the streets and the blocks are drawn behind the line that says so"
    assert min(got["size"]) > 1, "and it is the size of a lot"
    assert got["ground"] >= 1, "the ground is built"


# --- F1-D1: the trees ---------------------------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_a_park_holds_eight_to_twelve_trees_and_a_plaza_two_to_four_spread_over_the_block(tmp_path):
    got = run_node(tmp_path, r"""
import { treesOf, blockKind, PAVED_W, PAVED_D } from "@JS@/scene/city.js";
const parks = [], plazas = [], gaps = [], inside = [];
for (let col = -6; col < 8; col++) for (let row = -5; row <= 5; row++) {
  const kind = blockKind(col, row, 2);
  if (kind === "lot") continue;
  const trees = treesOf(kind, col, row);
  (kind === "park" ? parks : plazas).push(trees.length);
  for (let i = 0; i < trees.length; i++) {
    inside.push(Math.abs(trees[i][0]) < PAVED_W / 2 && Math.abs(trees[i][1]) < PAVED_D / 2);
    for (let j = i + 1; j < trees.length; j++) gaps.push(Math.hypot(trees[i][0] - trees[j][0], trees[i][1] - trees[j][1]));
  }
}
const again = JSON.stringify(treesOf("park", 3, 2)) === JSON.stringify(treesOf("park", 3, 2));
console.log(JSON.stringify({ parks: [Math.min(...parks), Math.max(...parks)], plazas: [Math.min(...plazas), Math.max(...plazas)], gap: Math.min(...gaps), inside: inside.every(Boolean), again }));
""")
    assert got["parks"][0] >= 8 and got["parks"][1] <= 12, "a park holds 8 to 12 trees (city.html)"
    assert got["plazas"][0] >= 2 and got["plazas"][1] <= 4, "a plaza holds 2 to 4"
    assert got["gap"] >= 0.8, "no two trees stand on one spot"
    assert got["inside"] is True and got["again"] is True, "every tree is on its block's paving, and the city is the same every time"


# --- F1-D1: the Building is framed to fill the free height ---------------------------------------------------------------------------------------------------------

def test_the_building_is_framed_without_padding_and_below_only_the_tracking_bar():
    source = text("js/views/building.js")
    assert re.search(r"return \{ \.\.\.base, bottom, pad: 1,", source), "the Building's fit adds no padding to its box (building.html fills the free height)"
    assert "frame.track.el.getBoundingClientRect()" in source, "the room below is the tracking bar's, not the dock's with the Back and the crumbs"
    tower = text("js/scene/tower.js")
    assert "+ 0.3);" in tower and "mix(1.2, 0.5)" in tower, "the open box is the room's wall and the mark's head, with no tenth of the height left empty"


# --- F1-D2: the shadow has no speckle ----------------------------------------------------------------------------------------------------------------------------

def test_the_sun_shadow_filter_is_not_wide_enough_to_speckle():
    assert re.search(r"sun\.shadow\.radius = 1;", text("js/scene/engine.js")), "the filter turns its five taps by a noise per pixel: a wide radius is a speckle on a pale plaza"


# --- F1-D5: the City's tooltip is a light card ------------------------------------------------------------------------------------------------------------------

def test_a_buildings_tooltip_is_a_light_card_and_a_rooms_stays_dark():
    css = SCENE_CSS
    dark = rule(css, ".wb-tooltip.pui-tooltip")
    card = rule(css, ".wb-tooltip.pui-tooltip.is-card")
    assert dark.get("background-color") == "var(--pui-text)", "what a room holds keeps the dark tooltip (R-31)"
    assert card.get("background-color") == "var(--wb-raised)" and card.get("color") == "var(--pui-text)", "a building's is the label's own light card"
    assert card.get("border") == "1px solid var(--pui-border)" and int(card.get("z-index", "0")) > 5, "with the label's border, over every label"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", str(card)), "no colour literal"
    assert 'classList.toggle("is-card", Boolean(result.hit.brackets))' in text("js/scene/engine.js"), "only a building of the City (the hit with brackets) takes the card"


# --- F1-D6: a long mode word never pushes the state out of the plate ----------------------------------------------------------------------------------------------

def test_the_plate_cuts_the_mode_word_and_keeps_the_state_badge():
    css = css_file("building")
    mode = rule(css, ".wb-plate-mode")
    state = rule(css, ".wb-plate-state")
    inner = rule(css, ".wb-plate-state .wb-st")
    name = rule(css, ".wb-plate-name")
    assert mode.get("text-overflow") == "ellipsis" and mode.get("overflow") == "hidden" and mode.get("max-width") == "9em" and mode.get("flex") == "0 100 auto" and mode.get("min-width") == "2em", "PAR-7d: the mode word is cut at nine ems with an ellipsis and is the first to shrink when the row is full"
    assert name.get("min-width") == "0" and name.get("text-overflow") == "ellipsis", "PAR-7d: the name gives way after the mode word"
    assert state.get("flex") == "0 0 auto" and "min-width" not in state, "PAR-7d: the state badge never shrinks"
    assert inner.get("overflow") == "visible" and inner.get("max-width") == "none" and inner.get("text-overflow") == "clip", "PAR-7d: the plate's state word is whole, never cut with an ellipsis"


# --- F1-D8: the phone's room is framed between the buttons, the card hangs from the sheet -------------------------------------------------------------------------

def test_the_phone_building_frames_the_room_beside_the_steps_and_the_card_hangs_from_the_sheet():
    source = text("js/views/building.js")
    assert "PHONE_TOOLS_H" not in source, "the camera buttons are under the KPI tiles now: the floor card no longer hangs above them"
    assert re.search(r"left: 8, right: PHONE_COLUMN, top: base\.top,.*cornerBottom: level \}", source), "the room is framed beside the floor steps (the camera row stands over the corner a diamond leaves empty), and the card hangs from the sheet's edge"


# --- F1-D9, M-32: no WebGL on a phone ---------------------------------------------------------------------------------------------------------------------------

def test_the_line_for_no_webgl_is_a_card_at_the_top_of_a_phones_scene_in_reading_text():
    phone = "\n".join(media_blocks(SCENE_CSS, "max-width: 899px"))
    plain = rule(phone, ".wb-frame[data-screen].no-scene .wb-scene-fallback")
    assert plain.get("left") == "12px" and plain.get("right") == "12px" and plain.get("translate") == "none", "it spans the width of the page"
    assert "var(--wb-cam-top" in plain.get("top", "") and "--wb-notice-bottom" in plain.get("top", ""), "under the KPI tiles and under a band"
    assert plain.get("font-size") == "16px", "reading text on a phone is 16 px (M-32)"
    noticed = rule(phone, ".wb-frame[data-screen].no-scene.has-notice .wb-scene-fallback")
    assert noticed.get("left") == "12px", "the City's own rule for a band does not put it back at the right"


# --- M-32 -------------------------------------------------------------------------------------------------------------------------------------------------------

def sizes(css: str, selectors: list[str], query: str = "max-width: 899px") -> dict:
    block = "\n".join(media_blocks(css, query))
    out = {}
    for selector in selectors:
        out[selector] = rule(block, selector).get("font-size")
    return out


def test_the_building_panel_reads_at_16_px_on_a_phone_and_nothing_goes_under_12():
    css = css_file("building")
    got = sizes(css, [".wb-facts", ".wb-facts dt", ".wb-rq-title", ".wb-rq-n", ".wb-rq-sub", ".wb-docs-link", ".wb-fl-name", ".wb-sec-head", ".wb-sec-empty", ".wb-rq-cancel", ".wb-fc-name"])
    assert set(got.values()) == {"16px"}, got
    small = sizes(css, [".wb-fl-mode", ".wb-fl-chips", ".wb-st", ".wb-acting", ".wb-floor-counter", ".wb-fc-runs", ".wb-label-board .wb-label-sub"])
    assert set(small.values()) == {"12px"}, "chips, badges, counters and the mode word are meta: 12 px, never below, inside the phone's query"
    for path in ("css/building.css", "css/city.css"):
        for value in re.findall(r"font-size:\s*(\d+)px", text(path)):
            assert int(value) >= 11, f"{path}: a size under 11 px outside the phone's query"
    outside = without_media(css)
    assert rule(outside, ".wb-st").get("font-size") == "11px", "the desktop's badge is unchanged"


def test_the_city_list_names_a_project_at_16_px_on_a_phone():
    got = sizes(css_file("city"), [".wb-building-name"])
    assert got[".wb-building-name"] == "16px"
    assert rule(without_media(css_file("city")), ".wb-building-sub").get("font-size") == "12px", "its line under it is a meta line"


# --- F2-D15: the server room stands beside the accept band, not under it ---------------------------------------------------------------------------------------------

@needs_node
def test_the_room_stands_in_the_strip_beside_a_tall_band_below_the_cards(tmp_path):
    got = run_node(tmp_path, r"""
import { insetsBesideBand, MIN_STRIP } from "@JS@/scene/band.js";
const rect = (left, top, right, bottom) => ({ left, top, right, bottom, width: right - left, height: bottom - top });
const scene = rect(0, 0, 1280, 800);
const counted = { left: 564, right: 715, top: 68, bottom: 70, pad: 1.04 };
const free = { left: 240, right: 715, top: 68, bottom: 70, pad: 1.04 };
const kpis = rect(16, 72, 224, 245);
const tall = rect(236, 72, 548, 693);
const out = {
  tall: insetsBesideBand({ counted, free, band: tall, scene, kpis }),
  none: insetsBesideBand({ counted, free, band: null, scene, kpis }) === free,
  wide: insetsBesideBand({ counted, free, band: rect(236, 70, 1000, 120), scene, kpis }) === counted,
  narrow: insetsBesideBand({ counted, free, band: rect(150, 72, 400, 693), scene, kpis }) === free,
  min: MIN_STRIP,
};
console.log(JSON.stringify(out));
""")
    assert got["tall"] == {"left": 8, "right": 1280 - 236 + 12, "top": 257, "bottom": 70, "pad": 1.04}, "the strip left of the band (8 px to 12 px before it), under the KPI cards, above the dock"
    assert got["none"] is True and got["wide"] is True, "no band: the page's insets; a strip along the top: the page's own, which put the drawing under it"
    assert got["narrow"] is True, "no strip worth having beside it: the band floats over the drawing"
    source = text("js/views/control.js")
    assert "insetsBesideBand({ counted, free: frame.insets(panel.el, { notice: false })" in source and "frame.isPhone()" in source, "the Control room asks for it, never on a phone (the page's band always counts there)"
