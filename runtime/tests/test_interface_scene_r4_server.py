"""Tests of the server room (R4-B3, R-51): the Control room's scene drawn in the City's style, every object a fact. The racks with their seven units and the fact's light, the wall screen
with the seven capped bars and their ticks, the console with two screens off, keyboards, a mouse and an office chair (no plant), the corner brackets of the object of the open tab, the dark
tooltip of every object, the room made in a few batches and freed when it is made again.

No browser and no model: the pure modules run under Node when it is installed (the builder with the real three.js, no WebGL; the engine with a renderer that draws nothing); what only a browser
can show was looked at in the browser pane by the package's report.

Run: uv run --offline --no-project --with pytest python -m pytest runtime/tests/test_interface_scene_r4_server.py
"""
from __future__ import annotations

import re

import standin_tree as st
from test_interface_scene_round3 import ENGINE_PAGE_JS, needs_node, run_node, run_node_engine
from test_interface_scene_r4_rooms import ROOMS_JS

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
SCENE = JS / "scene"
VIEWS = JS / "views"

# What these tests share: the room's modules, the tones in light and in dark, the connections and the costs the page reads, and the helpers that read a mesh's quads.
SERVER_JS = ROOMS_JS + r"""
import { serverTones } from "@JS@/scene/palette.js";
import * as room from "@JS@/scene/server-room.js";
import { buildServer } from "@JS@/views/control-scene.js";
import { sceneModel } from "@JS@/views/control-model.js";

export const conn = (classes, secrets, image) => ({
  classes: classes.map((found, i) => ({ class: `c${i}`, provider: found ? "p" : null, found, note: null, skills: [] })),
  secrets: secrets.map((found, i) => ({ name: `S${i}`, found, where: found ? "env" : null })),
  image: { name: "i", present: image, evidence: true }, platform: {},
});
export const row = (day, runs) => ({ day, agent: "a", model: "m", adapter: "x", runs, tokens: null, recorded_usd: null, recomputed_usd: null, unknown_runs: 0, price: null });
// the quads of a batch mesh (six vertices each): {hex, x0, x1, y0, y1, z0, z1}
export function quads(mesh) {
  const p = mesh.geometry.getAttribute("position"); const k = mesh.geometry.getAttribute("color"); const out = [];
  for (let i = 0; i + 5 < p.count; i += 6) {
    const xs = [], ys = [], zs = [];
    for (let j = 0; j < 6; j++) { xs.push(p.getX(i + j)); ys.push(p.getY(i + j)); zs.push(p.getZ(i + j)); }
    out.push({ hex: new THREE.Color(k.getX(i), k.getY(i), k.getZ(i)).getHexString(), x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys), z0: Math.min(...zs), z1: Math.max(...zs) });
  }
  return out;
}
export const meshOf = (group) => { const out = []; group.traverse((n) => { if (n.isMesh) out.push(n); }); return out; };
export const r = (v) => Math.round(v * 1000) / 1000;
// the scene's own frame, in page units back to the world: the page's room on the room's scale
export const FR = room.FRAME;
export const build = (model, tones = light) => { const kit = createKit(tones); return { kit, built: buildServer(kit, model) }; };
const facts = (n) => [...Array.from({ length: n }, (_, i) => i % 3 !== 1)];
export const modelOf = (found, extra = {}) => sceneModel({ accepted: true, connections: conn(found, [], true), costs: null, ...extra });
"""

TONES_SCRIPT = SERVER_JS + r"""
const L = serverTones(light);
const N = serverTones(night);
const mix = (a, b, t) => hex(mixSrgb(a, b, t));
const out = {};
const t = (name, f) => { out[name] = f(); };
// light: the recipes of scene.css as the later rule of each class writes them
out.rack = [hex(L.rack.top), mix(T2.textMuted, T2.emphasis, 0.35), hex(L.rack.left), mix(T2.textMuted, T2.text, 0.35), hex(L.rack.right), mix(T2.textMuted, T2.text, 0.12)];
out.rackDark = [hex(N.rack.top), mix(DK.emphasis, DK.textMuted, 0.5), hex(N.rack.left), mix(DK.emphasis, DK.textMuted, 0.22), hex(N.rack.right), mix(DK.emphasis, DK.textMuted, 0.36)];
out.base = [hex(L.rackBase), mix(T2.text, T2.textMuted, 0.4), hex(N.rackBase), hex(DK.bgToken)];
out.unit = [hex(L.unit), mix(T2.text, T2.textMuted, 0.18), hex(N.unit), hex(DK.bgToken)];
out.ear = [hex(L.ear), mix(T2.textMuted, T2.emphasis, 0.3), hex(N.ear), mix(DK.emphasis, DK.textMuted, 0.55)];
out.bay = [hex(L.bay), mix(T2.text, T2.textMuted, 0.6), hex(N.bay), mix(DK.emphasis, DK.textMuted, 0.16)];
out.leds = [hex(L.ledOk), hex(T2.success), hex(L.ledBad), hex(T2.error), hex(N.ledOk), hex(DK.success), hex(L.ledOff), mix(T2.textMuted, T2.text, 0.3), hex(N.ledOff), mix(DK.emphasis, DK.textMuted, 0.3)];
out.dim = [hex(L.ledDim), mix(T2.textMuted, T2.emphasis, 0.4), hex(N.ledDim), mix(DK.emphasis, DK.textMuted, 0.6)];
out.door = [hex(L.rackDoor), mix(T2.text, T2.textMuted, 0.55), hex(N.rackDoor), mix(DK.bgToken, DK.emphasis, 0.55)];
// a vent is a stroke at 55 percent over the face it is on
out.vents = [hex(L.ventTop), mix(L.rack.top, mixSrgb(T2.text, T2.textMuted, 0.3), 0.55), hex(N.ventSide), mix(N.rack.left, DK.bgToken, 0.55)];
out.screen = [hex(L.wsScreen), mix(T2.text, T2.textMuted, 0.25), hex(N.wsScreen), hex(DK.bgToken)];
// the grid and the lines are the surface (light) or the text (dark) at 16 and 45 percent over the screen
out.lines = [hex(L.wsGrid), mix(L.wsScreen, light.bg, 0.16), hex(L.wsLine), mix(L.wsScreen, light.bg, 0.45), hex(N.wsLine), mix(N.wsScreen, DK.text, 0.45)];
out.bars = [hex(L.bar), hex(T2.theme), hex(L.barCap), mix(T2.theme, light.bg, 0.45), hex(N.barCap), mix(DK.theme, DK.text, 0.4)];
out.led = [hex(L.wsLed), hex(T2.success)];
out.face = [hex(L.screenFace), mix(T2.text, T2.textMuted, 0.12), hex(N.screenFace), hex(DK.bgToken)];
out.back = [hex(L.workBack), mix(T2.emphasis, T2.textMuted, 0.62), hex(N.workBack), mix(DK.emphasis, DK.textMuted, 0.28)];
out.tray = [hex(L.tray.top), mix(T2.emphasis, T2.textMuted, 0.5), hex(L.tray.left), mix(T2.textMuted, T2.emphasis, 0.2), hex(N.tray.top), mix(DK.emphasis, DK.textMuted, 0.46)];
out.body = [hex(L.body.top), mix(T2.textMuted, T2.emphasis, 0.25), hex(L.body.left), mix(T2.textMuted, T2.text, 0.35), hex(L.mount), mix(T2.textMuted, T2.text, 0.35), hex(L.bezel), mix(T2.text, T2.textMuted, 0.5)];
out.distinct = [Object.keys(L).length, new Set(["rackBase", "unit", "ear", "bay", "ledDim", "ledOff", "grille", "rackDoor", "wsScreen", "bezel", "screenFace"].map((k) => hex(L[k]))).size];
// a stand-in palette with no dark-scheme tokens still gives every tone
out.bare = Object.keys(serverTones({ dark: false, T, mix: (a, b, t) => a.clone().lerp(b, t), bg: c(0xfafafa) })).length === Object.keys(L).length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_server_rooms_tones_are_the_recipes_of_scene_css_in_light_and_in_dark(tmp_path):
    got = run_node(tmp_path, TONES_SCRIPT)
    for name in ("rack", "rackDark"):
        a = got[name]
        assert a[0] == a[1] and a[2] == a[3] and a[4] == a[5], f"R-51: a rack's top, front and side are the three tones of `.m-rack` ({name})"
    assert got["base"][0] == got["base"][1] and got["base"][2] == got["base"][3], "the plinth is the text with a muted mix in light and the page colour in dark"
    assert got["unit"][0] == got["unit"][1] and got["unit"][2] == got["unit"][3], "R-51: a unit is a dark slot (`.m-unit`: the last of its two rules)"
    assert got["ear"][0] == got["ear"][1] and got["ear"][2] == got["ear"][3] and got["bay"][0] == got["bay"][1] and got["bay"][2] == got["bay"][3], "the ears and the bays of a unit"
    leds = got["leds"]
    assert leds[0] == leds[1] and leds[2] == leds[3] and leds[4] == leds[5], "R-51: the fact's light is the success colour when found and the error colour when missing, the tokens themselves"
    assert leds[6] == leds[7] and leds[8] == leds[9], "the light of a unit with no fact is a muted mix (dim)"
    assert got["dim"][0] == got["dim"][1] and got["dim"][2] == got["dim"][3], "the activity dot is dim"
    assert got["door"][0] == got["door"][1] and got["door"][2] == got["door"][3], "the rack's framed front"
    assert got["vents"][0] == got["vents"][1] and got["vents"][2] == got["vents"][3], "a vent is a stroke at 55 percent over the face it is on, so it is one flat tone"
    assert got["screen"][0] == got["screen"][1] and got["screen"][2] == got["screen"][3], "the wall screen's face"
    assert got["lines"][0] == got["lines"][1] and got["lines"][2] == got["lines"][3] and got["lines"][4] == got["lines"][5], "the grid (16 percent) and the head and base lines (45 percent) over the screen"
    assert got["bars"][0] == got["bars"][1] and got["bars"][2] == got["bars"][3] and got["bars"][4] == got["bars"][5], "R-51: a bar is the brand colour, its cap lighter (the surface in light, the text in dark)"
    assert got["led"][0] == got["led"][1], "the wall screen's light is the success colour"
    assert got["face"][0] == got["face"][1] and got["face"][2] == got["face"][3] and got["back"][0] == got["back"][1] and got["back"][2] == got["back"][3], "a screen that is off, the desk's back panel"
    assert got["tray"][0] == got["tray"][1] and got["tray"][2] == got["tray"][3] and got["tray"][4] == got["tray"][5], "the cable tray"
    assert got["body"][0] == got["body"][1] and got["body"][2] == got["body"][3] and got["body"][4] == got["body"][5] and got["body"][6] == got["body"][7], "the wall screen's body, its mounts and its bezel"
    assert got["distinct"][1] == 11, "each of the racks' and the screen's parts has a tone of its own (the counts below tell one part from another by it)"
    assert got["bare"] is True


MEASURES_SCRIPT = SERVER_JS + r"""
const out = {};
out.scale = [r(FR.sx), r(FR.sy), r(FR.sz), r(FR.X(0)), r(FR.X(7)), r(FR.Z(0)), r(FR.Z(5.6)), r(FR.Y(0)), r(FR.Y(-0.309))];
out.racks = [room.RACK.units, room.RACK.z.map(r), r(room.RACK.pitch), r(room.RACK.unitPitch), r(room.RACK.unitHeight)];
out.wall = [room.SCREEN.slots, r(room.SCREEN.pitch), r(room.SCREEN.barWidth), r(room.SCREEN.full), r(room.SCREEN.base)];
out.brackets = Object.fromEntries(Object.entries(room.BRACKETS).map(([k, v]) => [k, v]));
out.ledge = room.LEDGE;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_room_is_the_pages_room_in_its_own_units_with_the_measures_taken_off_control_room_html(tmp_path):
    got = run_node(tmp_path, MEASURES_SCRIPT)
    sx = 6.4 / 7
    assert got["scale"] == [round(sx, 3), round(sx, 3), round(sx, 3), -3.2, 3.2, -2.56, 2.56, round(0.309 * sx, 3), 0.0], \
        "the page's room is 7 by 5.6 units on every axis alike (the page's isometric has three equal axes), so the room is not squashed; the ledge's foot stands at the ground"
    assert got["racks"] == [7, [0.686, 2.086, 3.486], 1.4, 0.264, 0.215], "R-51: three racks 1.4 apart against the left wall, seven units each, 0.264 apart and 0.215 high (decoded from the page's paths)"
    assert got["wall"] == [7, 0.4, 0.26, 0.925, 1.073], "R-51: seven bar slots 0.4 apart, 0.26 wide, up to 0.925 high from the base line"
    br = got["brackets"]
    assert br["racks"]["arm"] == 0.42 and br["racks"]["rise"] == 0.42 and br["racks"]["drop"] == 0.42 and br["console"]["rise"] == 0.42, "the page's brackets: an arm of 0.42, and a short line up at the base and down at the top"
    assert (br["racks"]["x0"], br["racks"]["x1"], br["racks"]["z0"], br["racks"]["z1"], br["racks"]["y1"]) == (0.224, 1.327, 0.56, 4.855, 2.66), "one box round the three racks"
    assert (br["console"]["x0"], br["console"]["x1"], br["console"]["z0"], br["console"]["z1"], br["console"]["y1"]) == (3.225, 6.42, 2.725, 5.135, 1.84), "one box round the desk and its chair"
    assert br["wall"]["plane"] == "z" and (br["wall"]["a0"], br["wall"]["a1"], br["wall"]["y0"], br["wall"]["y1"], br["wall"]["arm"]) == (2.391, 6.03, 0.598, 2.559, 0.392), "four corners in the wall's plane round the screen"
    assert got["ledge"] == {"x0": -0.418, "z0": -0.418, "w": 7.838, "d": 6.437, "h": 0.309}, "the slab under the room stands 0.418 out of it on every side (the page's ledge)"


STRUCTURE_SCRIPT = SERVER_JS + r"""
const out = {};
const mdl = modelOf([true, false, true, true, false, true, true, true]);
const { kit, built } = build(mdl);
out.hits = built.hits.map((h) => [h.id, h.tip, Boolean(h.marks), Boolean(h.anchor)]);
out.shared = [built.hits[0].marks === built.hits[1].marks, built.hits[1].marks === built.hits[2].marks, built.hits[3].marks === built.hits[0].marks, built.hits[4].marks === built.hits[3].marks];
out.holders = built.hits.map((h) => [h.marks.visible, h.marks.userData.brackets === true]);
out.noOutline = [built.outlines.length, built.selected, built.labels.length, built.beacons.length, built.markers.length, (built.motions || []).length];
out.open = built.open;
// the anchors are the top of each object's box
built.group.updateWorldMatrix(true, true);
out.anchors = built.hits.map((h) => { const b = new THREE.Box3().setFromObject(h.object); return [r(h.anchor.x - (b.min.x + b.max.x) / 2), r(h.anchor.y - b.max.y), r(h.anchor.z - (b.min.z + b.max.z) / 2)]; });
// what the camera frames: the room with its ledge, not the city round it
const box = built.subject();
out.subject = [r(box.min.x), r(box.max.x), r(box.min.z), r(box.max.z), box.min.y, r(box.max.y)];
// the meshes: the ground (five), the shell, three racks, the wall screen, the console, three sets of brackets
const meshes = meshOf(built.group);
out.meshes = meshes.length;
out.visible = meshes.filter((m) => { for (let n = m; n; n = n.parent) if (!n.visible) return false; return true; }).length;
out.instanced = meshes.filter((m) => m.isInstancedMesh).length;
out.perHit = built.hits.map((h) => meshOf(h.object).length);
// the words, apart from the room: a model that changes only them changes the tips
const words = built.text(modelOf([true, true, true, true, true, true, true, true], { tab: "costs" }));
out.words = [[...words.tips.keys()], words.labels.length, words.open];
out.structure = [JSON.stringify(buildServer.structure(mdl)) === JSON.stringify(buildServer.structure({ ...mdl, open: ["wall"], tips: {} })), buildServer.structure(mdl).ready];
// every picked object is made of meshes that stay in its own group
out.noPlant = !meshes.some((m) => m.geometry && /Icosahedron|Sphere/.test(m.geometry.type));
kit.dispose();
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_server_room_has_three_racks_a_wall_screen_and_a_console_each_with_its_tooltip_its_brackets_and_nothing_else(tmp_path):
    got = run_node(tmp_path, STRUCTURE_SCRIPT)
    assert [h[0] for h in got["hits"]] == ["rack-1", "rack-2", "rack-3", "wall", "console"], "R-51: the three racks, the wall screen and the console are what the pointer meets"
    assert all(h[2] and h[3] for h in got["hits"]), "every object has its brackets and the place of its tooltip"
    assert [h[1] for h in got["hits"][:3]] == ["Connections · 2 missing · Connections tab"] * 3 and got["hits"][3][1] == "Runs by day · Costs tab" and got["hits"][4][1] == "Console · Skills tab", "the tooltips are the page's: the racks one object (Connections, with the count of every fact), the wall screen, the console"
    assert got["shared"] == [True, True, False, False], "R-51: the racks are one object for the mark (one box round the three), the wall screen and the console each their own"
    assert all(h == [False, True] for h in got["holders"]), "the brackets are built hidden and are drawn, never picked"
    assert got["noOutline"] == [0, None, 0, 0, 0, 0], "R-51: no room outline, no label, nothing that moves"
    assert got["open"] == ["console"], "the model without a tab opens on Skills: the console"
    assert all(a == [0, 0, 0] for a in got["anchors"]), "a tooltip stands over the middle of the top of its object"
    assert got["subject"] == [-3.582, 3.584, -2.942, 2.943, 0.2, 2.915], "the camera frames the room with its slab, from the block it stands on up to the walls' top"
    assert got["meshes"] <= 20 and got["visible"] <= 12 and got["instanced"] == 3, "R-51: batched statics: the ground's six (its trees are three instanced meshes since M-5, R4-B4), the shell, a rack each, the wall screen, the console, the open tab's brackets"
    assert got["perHit"] == [1, 1, 1, 1, 1], "one mesh for each object"
    assert got["words"][0] == ["rack-1", "rack-2", "rack-3", "wall", "console"] and got["words"][1] == 0 and got["words"][2] == ["wall"], "the words and the tab's object are apart from the room"
    assert got["structure"] == [True, True], "a change of tab or of words alone builds nothing again"
    assert got["noPlant"] is True, "R-51: no plant, it carried no fact"


LEDS_SCRIPT = SERVER_JS + r"""
// 12 facts (eleven classes and the image): found, missing, found, found, missing, found, found | found, missing, found, found, found | no more
const mdl = modelOf([true, false, true, true, false, true, true, true, false, true, true]);
const { built } = build(mdl);
const rack = (k) => meshOf(built.hits[k].object)[0];
const hexOf = (col) => col.getHexString();
const S = serverTones(light);
const lights = (k) => {
  const q = quads(rack(k));
  const pick = (tone) => q.filter((x) => x.hex === hexOf(tone)).map((x) => r(x.y0)).sort((a, b) => b - a);
  const count = (tone) => q.filter((x) => x.hex === hexOf(tone)).length;
  return { ok: pick(S.ledOk), bad: pick(S.ledBad), off: pick(S.ledOff), dim: count(S.ledDim), units: count(S.unit), ears: count(S.ear), bays: count(S.bay), door: count(S.rackDoor), grille: count(S.grille), base: count(S.rackBase), vents: count(S.ventTop) + count(S.ventSide) };
};
const out = { racks: [0, 1, 2].map(lights) };
// the unit a light is on, from the top: the unit k from the top of a rack has its bottom at 0.266 + (6 - k) * 0.264 of the page and its light 0.065 above that
out.unitsFromTop = [0, 1, 2, 3, 4, 5, 6].map((k) => r(FR.Y(0.266 + (6 - k) * 0.264 + 0.065)));
// before the connections are read every light is the dim kind
const none = build(sceneModel({ accepted: true, connections: null, costs: null })).built;
out.none = [0, 1, 2].map((k) => { const q = quads(meshOf(none.hits[k].object)[0]); return [q.filter((x) => x.hex === hexOf(S.ledOff)).length, q.filter((x) => x.hex === hexOf(S.ledOk) || x.hex === hexOf(S.ledBad)).length]; });
// 24 facts and more: only the 21 slots are drawn
const many = build(sceneModel({ accepted: true, connections: conn(new Array(10).fill(true), new Array(13).fill(false), true), costs: null })).built;
out.many = [0, 1, 2].map((k) => { const q = quads(meshOf(many.hits[k].object)[0]); return [q.filter((x) => x.hex === hexOf(S.ledOk)).length, q.filter((x) => x.hex === hexOf(S.ledBad)).length, q.filter((x) => x.hex === hexOf(S.ledOff)).length]; });
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_racks_units_are_seven_slots_with_ears_bays_an_activity_dot_and_the_facts_light_filled_from_the_top_of_the_first_rack(tmp_path):
    got = run_node(tmp_path, LEDS_SCRIPT)
    a, b, c = got["racks"]
    top = got["unitsFromTop"]
    for rack in got["racks"]:
        assert rack["units"] == 7 and rack["ears"] == 14 and rack["bays"] == 21 and rack["dim"] == 7 and rack["door"] == 1 and rack["grille"] == 1, \
            "R-51: a rack has a framed front, a grille and seven units, each a slot with two ears, three drive bays and an activity dot"
        assert rack["base"] >= 1 and rack["vents"] == 5 + 12, "and a plinth, five vents on the top and twelve on the side"
        assert len(rack["ok"]) + len(rack["bad"]) + len(rack["off"]) == 7, "every unit has the fact's light, found, missing or dim"
    assert (len(a["ok"]), len(a["bad"]), len(a["off"])) == (5, 2, 0), "the first seven facts fill the first rack: five found, two missing"
    assert (len(b["ok"]), len(b["bad"]), len(b["off"])) == (4, 1, 2), "the next five fill the second rack from the top: four found, one missing; two units carry none and are dim"
    assert (len(c["ok"]), len(c["bad"]), len(c["off"])) == (0, 0, 7), "a rack with no fact has seven dim lights"
    assert a["ok"][0] == top[0] and a["bad"] == [top[1], top[4]], "the first fact (found) is on the top unit of the first rack, the second (missing) on the unit under it, the fifth (missing) on the fifth"
    assert b["ok"][0] == top[0] and b["bad"] == [top[1]] and b["off"] == [top[5], top[6]], "the second rack goes on from its top unit, and its last two units are dim"
    assert got["none"] == [[7, 0], [7, 0], [7, 0]], "before the connections are read every light is dim"
    assert got["many"] == [[7, 0, 0], [3, 4, 0], [0, 7, 0]], "21 slots and 24 facts: the first 21 are drawn (ten classes found, eleven secrets missing)"


WALL_SCRIPT = SERVER_JS + r"""
const S = serverTones(light);
const hexOf = (col) => col.getHexString();
const wallOf = (bars) => { const mdl = { ...modelOf([true]), bars }; const { built } = build(mdl); return meshOf(built.hits[3].object)[0]; };
const read = (bars) => {
  const q = quads(wallOf(bars));
  const of = (tone) => q.filter((x) => x.hex === hexOf(tone));
  const bar = of(S.bar).sort((a, b) => a.x0 - b.x0);
  const cap = of(S.barCap).sort((a, b) => a.x0 - b.x0);
  return { bars: bar.map((x) => [r(x.x0), r(x.y1 - x.y0)]), caps: cap.map((x) => [r(x.x0), r(x.y1 - x.y0), r(x.y1)]), tops: bar.map((x) => r(x.y1)), ticks: of(S.wsLine).length, grid: of(S.wsGrid).length, led: of(S.wsLed).length, face: of(S.wsScreen).length, bezel: of(S.bezel).length, body: q.filter((x) => x.hex === hexOf(S.body.top) || x.hex === hexOf(S.mount)).length };
};
const unit = r(FR.sy);
const out = {};
out.full = read([0.3333, 0.4167, 0, 0.6667, 0, 0, 1]);
out.none = read([0, 0, 0, 0, 0, 0, 0]);
out.tiny = read([0, 0, 0, 0, 0, 0.02, 1]);
out.pitch = r(room.SCREEN.pitch * FR.sx);
out.width = r(room.SCREEN.barWidth * FR.sx);
out.fullHeight = r(room.SCREEN.full * FR.sy);
out.base = r(FR.Y(room.SCREEN.base));
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_wall_screen_has_a_capped_bar_for_each_day_with_runs_a_tick_under_every_day_and_nothing_for_an_empty_day(tmp_path):
    got = run_node(tmp_path, WALL_SCRIPT)
    full = got["full"]
    sx = 6.4 / 7
    assert [b[0] for b in full["bars"]] == [round(-3.2 + (2.879 + i * 0.4) * sx, 3) for i in (0, 1, 3, 6)], "R-51: a bar for each day with runs at its slot (the empty days draw none)"
    assert [b[1] for b in full["bars"]] == [round(0.925 * v * sx, 3) for v in (0.3333, 0.4167, 0.6667, 1)], "a bar is its share of the largest day, up to 0.925 of the plot"
    assert len(full["caps"]) == 4 and [c[1] for c in full["caps"]] == [round(0.05 * sx, 3)] * 4, "each bar has a lighter cap 0.05 high"
    assert [c[2] for c in full["caps"]] == full["tops"], "the cap is the top of its bar"
    assert full["ticks"] >= 7 + 2 and full["grid"] >= 3, "a tick under each of the seven days, the head line and the base line; grid lines"
    assert full["led"] == 1 and full["face"] == 1 and full["bezel"] == 1, "the screen, its bezel and its light"
    assert got["none"]["bars"] == [] and got["none"]["caps"] == [] and got["none"]["ticks"] == full["ticks"], "no runs: no bar, the ticks stay"
    assert got["tiny"]["bars"][0][1] < 0.05 * sx and got["tiny"]["caps"][0][1] <= got["tiny"]["bars"][0][1] + 1e-9, "a bar shorter than its cap is all cap"
    assert got["pitch"] == round(0.4 * sx, 3) and got["width"] == round(0.26 * sx, 3) and got["fullHeight"] == round(0.925 * sx, 3), "the page's slot, width and height"


CONSOLE_SCRIPT = SERVER_JS + r"""
const S = serverTones(light); const R = roomTones(light);
const hexOf = (col) => col.getHexString();
const { built } = build(modelOf([true]));
const mesh = meshOf(built.hits[4].object)[0];
const q = quads(mesh);
const of = (...tones) => q.filter((x) => tones.some((t) => x.hex === hexOf(t)));
const box = (list) => [r(Math.min(...list.map((x) => x.x0))), r(Math.max(...list.map((x) => x.x1))), r(Math.min(...list.map((x) => x.y0))), r(Math.max(...list.map((x) => x.y1))), r(Math.min(...list.map((x) => x.z0))), r(Math.max(...list.map((x) => x.z1)))];
const out = {};
const world = (px, pz) => [r(FR.X(px)), r(FR.Z(pz))];
const desk = of(R.work.top, R.work.left, R.work.right);
out.deskTop = box(of(R.work.top));
out.legs = of(R.workLeg.top).length;
out.back = of(S.workBack).length;
out.ped = of(R.ped.top, R.ped.left, R.ped.right).length;
out.drawers = of(R.pedDrawer).length;
out.handles = of(R.handle).filter((x) => x.x1 - x.x0 < 0.5).length;   // the desk's top is the same light tone in light: a handle is the narrow one
out.faces = of(S.screenFace).map((x) => [r(x.x0), r(x.x1), r(x.y0), r(x.y1)]);
out.screens = of(R.screen.top, R.screen.left, R.screen.right).length;
out.stands = of(R.stand.top).length;
out.keyboards = of(R.keyb.top, R.keyb.left, R.keyb.right).length;
out.keys = of(R.keyLine).length;
// the chair's base is the same dark tone: the mouse is the top at 0.041 over the desk
out.mouse = of(R.mouse.top).filter((x) => Math.abs(x.y0 - FR.Y(0.881)) < 0.001).map((x) => [r(x.x0), r(x.z0)]);
out.chair = of(R.chair.top).length;
out.chairBase = of(R.chairBase.top).length;   // six boxes (two bars, a column, a post and two armrest posts) of three faces in one tone
out.pad = of(R.chairPad).length;
const keyb = of(R.keyb.top);
out.keybX = keyb.map((x) => r(x.x0)).sort((a, b) => a - b);
out.keybZ = keyb.map((x) => r(x.z0));
// the chair is on the near side (+z) of the desk, the keyboards before the screens (+z of them), the mouse between the keyboards
const chairs = of(R.chair.top);   // the seat, the back and the two armrests
out.chairNear = [Math.min(...chairs.map((x) => x.z0)) > FR.Z(3.9), Math.max(...of(R.work.top).map((x) => x.z1)) <= FR.Z(4.01)];
out.screenZ = of(S.screenFace).map((x) => r(x.z0));
out.mouseBetween = out.mouse[0][0] > Math.max(...keyb.map((x) => x.x0).filter((v) => v < out.mouse[0][0])) && out.mouse[0][0] < Math.min(...keyb.map((x) => x.x0).filter((v) => v > out.mouse[0][0]));
// a tone that is not a screen's glow: the screens are off
out.off = of(S.screenFace).length === 2 && !q.some((x) => x.hex === hexOf(light.T.theme));
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_console_is_a_desk_on_panel_legs_with_two_screens_off_a_keyboard_before_each_a_mouse_and_an_office_chair_on_the_near_side(tmp_path):
    got = run_node(tmp_path, CONSOLE_SCRIPT)
    assert got["legs"] == 6 and got["back"] == 3 and got["ped"] == 3 and got["drawers"] == 3 and got["handles"] == 3, \
        "R-51: a desk on panel legs with a back panel and a drawer unit (three drawers with their handles)"
    assert len(got["faces"]) == 2, "two screens"
    assert got["off"] is True, "off: the face of a screen is dark, nothing lights it"
    assert got["stands"] == 4 and got["screens"] == 6, "each screen stands on a stand (a foot and a stem: four tops)"
    assert got["keybX"] == sorted(got["keybX"]) and len(got["keybX"]) == 2 and got["keys"] >= 8, "a keyboard before each screen, with its rows of keys"
    assert len(got["mouse"]) == 1 and got["mouseBetween"] is True, "a mouse, between the keyboards"
    assert got["chair"] == 4 and got["chairBase"] >= 18 and got["pad"] == 2, "R-51: an office chair: a star base and a column, a seat and a back, two armrests, the pads of the seat and the back"
    assert got["chairNear"] == [True, True], "on the near side of the desk"
    assert all(z < min(k for k in got["keybZ"]) for z in got["screenZ"]), "the keyboards stand before the screens"


BRACKETS_SCRIPT = ENGINE_PAGE_JS + SERVER_JS.replace('import { createKit }', 'import { createKit }') + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
await import("@JS@/views/control-scene.js");
const host = document.createElement("div");
const engine = createEngine(host, { label: "scene", getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0 }), onOpen() {}, onHover() {} });
const canvas = engine.canvas;
const m = (tab, found = [true, false, true]) => sceneModel({ accepted: true, connections: conn(found, [], true), costs: null, tab });
const shown = () => canvas.wbMarks().filter(([, on]) => on).map(([id]) => id);
const out = {};
engine.show("server", m("skills"), "Server room");
out.start = canvas.wbMarks();
out.skills = shown();
const builds = canvas.wbStats().builds;
engine.show("server", m("costs"), "Server room");
out.costs = shown();
engine.show("server", m("connections"), "Server room");
out.connections = shown();
engine.show("server", m("skills"), "Server room");
out.back = shown();
out.rebuilt = canvas.wbStats().builds - builds;
out.relabels = canvas.wbStats().relabels;
// a tab the screen does not have is Skills; the Costs tab with a hover on the console: the console wears its brackets as well
engine.show("server", m("nowhere"), "Server room");
out.unknown = shown();
engine.show("server", m("costs"), "Server room");
engine.highlight("console");
out.hoverConsole = shown();
engine.highlight("rack-2");
out.hoverRack = shown();
engine.clearHover();
out.cleared = shown();
// an LED that changes builds the room again and the open tab's object keeps its brackets
engine.show("server", m("costs", [true, true, true]), "Server room");
out.afterBuild = shown();
out.builds = canvas.wbStats().builds - builds;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_object_of_the_open_tab_wears_its_brackets_the_console_on_skills_the_wall_screen_on_costs_the_racks_on_connections(tmp_path):
    got = run_node_engine(tmp_path, BRACKETS_SCRIPT)
    ids = ["rack-1", "rack-2", "rack-3", "wall", "console"]
    assert [x[0] for x in got["start"]] == ids, "every object registers its brackets"
    assert got["skills"] == ["console"] and got["costs"] == ["wall"] and got["connections"] == ["rack-1", "rack-2", "rack-3"], \
        "R-51: the console on Skills, the wall screen on Costs, the racks on Connections"
    assert got["back"] == ["console"] and got["rebuilt"] == 0 and got["relabels"] >= 3, "a change of tab moves the brackets and builds nothing again"
    assert got["unknown"] == ["console"], "a tab this screen does not have is Skills"
    assert got["hoverConsole"] == ["wall", "console"] and got["hoverRack"] == ["rack-1", "rack-2", "rack-3", "wall"], \
        "a picked object wears its brackets as the Floor's does (R-31); the racks are marked together, with the open tab's object"
    assert got["cleared"] == ["wall"], "leaving it leaves the open tab's"
    assert got["afterBuild"] == ["wall"] and got["builds"] == 1, "a room made again (a light changed) keeps the open tab's object marked"


DEPTH_SCRIPT = SERVER_JS + r"""
import { boxBrackets } from "@JS@/scene/marks.js";
const out = {};
const mdl = modelOf([true, false, true]);
const { kit, built } = build(mdl);
const marks = (id) => built.hits.find((h) => h.id === id).marks;
const size = (id) => { const b = new THREE.Box3().setFromObject(marks(id)); return [r(b.max.x - b.min.x), r(b.max.y - b.min.y), r(b.max.z - b.min.z)]; };
const verts = (id) => marks(id).children[0].geometry.getAttribute("position").count;
out.racks = [size("rack-1"), verts("rack-1")];
out.console = [size("console"), verts("console")];
out.wall = [size("wall"), verts("wall")];
// the racks' box: 1.103 by 2.66 by 4.295 page units plus the arms' own width; the wall screen's four corners lie in one plane
out.depth = kit.vertexMaterial.depthTest !== false && kit.vertexMaterial.depthWrite !== false;
// `rise` is off by default: B2's rooms keep their brackets
const plain = boxBrackets(kit, (b) => pageBatch(b, FR), { x0: 0, x1: 2, z0: 0, z1: 2, y0: 0, y1: 2, arm: 0.45, drop: 0.5, tone: roomTones(light).bracket });
const rising = boxBrackets(kit, (b) => pageBatch(b, FR), { x0: 0, x1: 2, z0: 0, z1: 2, y0: 0, y1: 2, arm: 0.45, drop: 0.5, rise: 0.5, tone: roomTones(light).bracket });
out.rise = [plain.geometry.getAttribute("position").count, rising.geometry.getAttribute("position").count];
const tone = (id) => [...colours(marks(id).children[0])];
out.colour = [tone("rack-1"), tone("wall"), tone("console")].every((c) => c.length === 1 && c[0] === hex(roomTones(light).bracket));
out.top = [r(new THREE.Box3().setFromObject(marks("racks" in {} ? "x" : "rack-1")).max.y), r(FR.Y(2.66))];
console.log(JSON.stringify(out));
"""


@needs_node
def test_round_a_box_the_corners_are_solids_so_the_depth_hides_those_behind_it_and_the_wall_screen_has_four_in_its_plane(tmp_path):
    got = run_node(tmp_path, DEPTH_SCRIPT)
    assert got["racks"][1] == 240 and got["console"][1] == 240, "R-51: eight Ls, a short line down at each top corner and one up at each base corner (the page's racks and console)"
    assert got["wall"][1] == 48 and got["wall"][0][2] == 0, "four corners in the wall's plane, as on the task board: no depth"
    assert got["depth"] is True, "real solids tested against the depth: the corners behind the object are drawn before it, only the nearest over it"
    assert got["rise"] == [168, 240], "`rise` adds the base lines and is off by default, so the rooms of the Building and the Floor keep their brackets"
    assert got["colour"] is True, "in the brand colour"
    assert got["top"][0] >= got["top"][1], "the racks' brackets reach the wall's height"


DISPOSE_SCRIPT = SERVER_JS + r"""
const made = new Set(); const gone = new Set(); const mats = new Set(); const matGone = new Set();
const setAttribute = THREE.BufferGeometry.prototype.setAttribute; const dispose = THREE.BufferGeometry.prototype.dispose;
THREE.BufferGeometry.prototype.setAttribute = function (...a) { made.add(this); return setAttribute.apply(this, a); };
THREE.BufferGeometry.prototype.dispose = function () { gone.add(this); return dispose.call(this); };
const matDispose = THREE.Material.prototype.dispose;
THREE.Material.prototype.dispose = function () { matGone.add(this); return matDispose.call(this); };
const out = { rounds: 0 };
let live = 0;
for (const found of [[true, false], [true, true, false], [false], []]) {
  const kit = createKit(palette);
  const built = buildServer(kit, modelOf(found));
  out.rounds += 1;
  const alive = new Set(); built.group.traverse((n) => { if (n.geometry) alive.add(n.geometry); });
  live = alive.size;
  kit.dispose();   // what the engine does when the scene is made again
}
out.leaked = [...made].filter((g) => !gone.has(g)).length;
out.live = live;
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_server_room_made_again_frees_every_geometry_and_material_it_made(tmp_path):
    got = run_node(tmp_path, DISPOSE_SCRIPT)
    assert got["rounds"] == 4 and got["leaked"] == 0, "R-51: the room is made through the engine's kit, so freeing the kit frees every geometry it made"
    assert 5 <= got["live"] <= 40, "and a room is a handful of geometries, not one for every box"


def test_the_model_names_the_object_of_the_open_tab_and_the_screen_passes_the_tab():
    model = (VIEWS / "control-model.js").read_text(encoding="utf-8")
    assert "export const OPEN_OF = " in model or "OPEN_BY_TAB" in model, "the model says which object a tab opens on"
    control = (VIEWS / "control.js").read_text(encoding="utf-8")
    assert re.search(r"model\.sceneModel\(\{[^}]*\btab\b", control, re.S), "the screen gives the model the open tab (a one-line change of Track A's file, listed in the report)"
    assert "select(tab);\n    drawScene();" in control, "and draws the scene again when the tab changes, as it did"


def test_the_server_room_holds_no_colour_literal_no_text_no_motion_no_plant_and_edits_no_core_of_the_engine():
    for name in ("server-room.js",):
        text = (SCENE / name).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|0x[0-9A-Fa-f]{6}\b|rgba?\(|hsla?\(", text), f"{name} writes no colour: the tones are the palette's"
        assert "fillText" not in text and "CanvasTexture" not in text and "TextGeometry" not in text, f"{name}: text is HTML, never drawn in the scene"
        assert not re.search(r"requestAnimationFrame|setInterval|setTimeout|Math\.random|Math\.sin", text), f"{name}: nothing moves"
    scene = re.sub(r"//.*", "", (VIEWS / "control-scene.js").read_text(encoding="utf-8"))   # the code of the builder, its comments left out
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|0x[0-9A-Fa-f]{6}\b|rgba?\(|hsla?\(", scene) and "plant" not in scene and "createKit" not in scene, "no colour of its own, no plant, the engine's kit"
    assert not re.search(r"requestAnimationFrame|setInterval|setTimeout|Math\.random|Math\.sin|\.style\b|createElement|innerHTML", scene), "nothing moves, nothing random, no markup of its own"
    assert "BUILDERS.server = buildServer" in scene and "kit.box(" not in scene and "kit.cyl(" not in scene, "registered through the engine's registry; drawn in batches, not a mesh for every box"
    props = (SCENE / "props.js").read_text(encoding="utf-8")
    assert "export function plant" not in props, "R-51: the plant is gone"
    palette = (SCENE / "palette.js").read_text(encoding="utf-8")
    assert "export function serverTones" in palette, "the recipes of the server room are in the palette"
    css = (INTERFACE / "scene.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", css), "scene.css writes no colour literal"


PICK_SCRIPT = SERVER_JS + r"""
import { pickableMeshes, pickList } from "@JS@/scene/pick.js";
// a group with the edge lines of its boxes (what the Control room drew before R-51) and the brackets of a hit: the pick takes meshes only, and never the brackets
const kit = createKit(palette);
const g = new THREE.Group();
kit.box(1, 1, 1, 0, 0, 0, palette.T.theme, { parent: g, edges: true });
const marks = new THREE.Group();
marks.userData.brackets = true;
const batch = kit.batch();
batch.box(1, 1, 1, 3, 0, 0, palette.T.theme);
batch.mesh(marks, { cast: false });
g.add(marks);
const out = { all: [], meshes: pickableMeshes(g).length };
g.traverse((n) => out.all.push(n.isMesh ? "mesh" : n.isLineSegments ? "line" : "group"));
out.list = pickList([{ object: g, id: "x" }]).meshes.length;
// the real room: what the pointer meets is the meshes of its five objects, never a line and never a bracket, whichever brackets are shown
const { built } = build(modelOf([true, false, true]));
const meshes = (object) => pickableMeshes(object).length;
const before = built.hits.map((h) => meshes(h.object));
for (const h of built.hits) h.marks.visible = true;
out.room = [before, built.hits.map((h) => meshes(h.object)), pickList(built.hits).meshes.length];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_pick_takes_the_meshes_of_the_five_objects_only_never_a_line_and_never_a_bracket(tmp_path):
    got = run_node(tmp_path, PICK_SCRIPT)
    assert got["all"].count("line") >= 1 and got["meshes"] == 1 and got["list"] == 1, "a line (the edges of a box) is never pickable, nor are the brackets of a hit: the cause the old Control room's wrong tooltip had (the third rack named the first)"
    assert got["room"] == [[1, 1, 1, 1, 1], [1, 1, 1, 1, 1], 5], "R-51: one mesh for each of the room's five objects, with every set of brackets shown or not"


QUIET_SCRIPT = ENGINE_PAGE_JS + SERVER_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
const out = {};
// the model: no object is named while the room is loading (connections not read) or the project is not accepted
const ready = sceneModel({ accepted: true, connections: conn([true, false], [], true), costs: null, tab: "costs" });
out.model = [ready.open, sceneModel({ accepted: true, connections: null, costs: null, tab: "costs" }).open, sceneModel({ accepted: false, connections: conn([true], [], true), costs: null, tab: "connections" }).open];
const engineAt = (width) => {
  const host = document.createElement("div");
  host.clientWidth = width;
  const engine = createEngine(host, { label: "scene", getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0 }), onOpen() {}, onHover() {} });
  return { engine, host, canvas: engine.canvas };
};
const shown = (canvas) => canvas.wbMarks().filter(([, on]) => on).map(([id]) => id);
// a desktop: the open tab's object and the pointer's
{
  const { engine, canvas } = engineAt(1280);
  engine.show("server", ready, "Server room");
  out.desktop = shown(canvas);
  engine.highlight("console");
  out.desktopHover = shown(canvas);
  // loading: the same room with nothing read, and then not accepted: no brackets, the pointer's included
  engine.clearHover();
  const loading = sceneModel({ accepted: true, connections: null, costs: null, tab: "costs" });
  engine.show("server", loading, "Server room, loading");
  out.loading = shown(canvas);
  engine.highlight("wall");
  out.loadingHover = shown(canvas);
  engine.clearHover();
  engine.show("server", sceneModel({ accepted: false, connections: null, costs: null, tab: "skills" }), "waiting");
  engine.highlight("rack-1");
  out.notAccepted = shown(canvas);
  engine.clearHover();
  engine.show("server", ready, "Server room");
  out.back = shown(canvas);
}
// a phone (under 900 px, M-3): none, the pointer's included, and they come back when the canvas grows
{
  const { engine, host, canvas } = engineAt(375);
  engine.show("server", ready, "Server room");
  out.phone = shown(canvas);
  engine.highlight("console");
  out.phoneHover = shown(canvas);
  engine.clearHover();
  host.clientWidth = 900;
  engine.refit();
  out.at900 = shown(canvas);
  host.clientWidth = 899;
  engine.refit();
  out.at899 = shown(canvas);
}
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_page_draws_no_brackets_on_a_phone_while_loading_or_not_accepted_so_the_room_wears_none_there_the_pointers_included(tmp_path):
    got = run_node_engine(tmp_path, QUIET_SCRIPT)
    assert got["model"] == [["wall"], [], []], "the model names no object while the room is loading or the project is not accepted (the page's loading and not-accepted frames draw no brackets)"
    assert got["desktop"] == ["wall"] and got["desktopHover"] == ["wall", "console"], "on a desktop the open tab's object and the pointer's wear them"
    assert got["loading"] == [] and got["loadingHover"] == [], "loading: none, and the pointer's stand down with them"
    assert got["notAccepted"] == [], "not accepted: none"
    assert got["back"] == ["wall"], "and they return when the room is read"
    assert got["phone"] == [] and got["phoneHover"] == [], "under 900 px (a phone, M-3: the page's phone frames draw none): none, the pointer's included"
    assert got["at900"] == ["wall"] and got["at899"] == [], "the limit is 900 px (M-3, was 640), and a resize across it moves them"
