"""Tests of R4-N1 (A-53, M-13 of the plan folder): the project switcher and Back to the building.

Two bugs, found on the served page. (1) After a Floor, the world hides every building but the open one; when the open building changed (the top switcher went to
another project) the new one was never shown again, so Back to the building drew the panel, the plates and the request line over an empty block. (2) The switcher
opened the same Floor in the other project even when that project has no such area agent: it now opens the target's Building, and keeps every screen that exists in
every project (the Lobby, the Control room) and a Floor the target has. No browser and no model: the world and the engine run under Node as the scene tests do.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_nav.py
"""
from __future__ import annotations

from test_interface_scene_round3 import ENGINE_PAGE_JS, PRODUCT_JS, WORLD_JS, JS, needs_node, run_node, run_node_engine


@needs_node
def test_the_world_shows_the_new_open_building_again_when_the_open_one_changes_after_a_floor(tmp_path):
    # root cause: `hideSurroundings` put away "every tower but the focus" with `visible = !on`, so a tower that was put away and then became the focus was never reset
    got = run_node(tmp_path, WORLD_JS + r"""
const { world } = make();
world.setFocus("a", true);
world.setFloors("business", null, true);
world.hideSurroundings(true);
const visible = () => ["a", "b", "c"].map((id) => world.towers.get(id).root.visible);
const out = { onFloor: visible() };
world.setFocus("b", true);               // the switcher went to another project; its Floor is not there, so no floor is chosen
world.setFloors(null, null, true);
world.hideSurroundings(false);
out.backOnB = visible();
world.setFocus("c", true);
world.setFloors("design", null, true);
world.hideSurroundings(true);            // a Floor of the third project: the others are put away, the open one stays
out.floorOfC = visible();
world.setFocus("a", true);
world.setFloors("design", null, true);
world.hideSurroundings(true);            // a Floor of the first, straight from the third's
out.floorOfA = visible();
console.log(JSON.stringify(out));
""")
    assert got["onFloor"] == [True, False, False], "on a Floor the other buildings are put away (as before)"
    assert got["backOnB"] == [True, True, True], "when the focus moves to a building that was put away and no floor is chosen, every building is drawn, the new focus first of all"
    assert got["floorOfC"] == [False, False, True] and got["floorOfA"] == [True, False, False], "a Floor puts away every building but its own, whichever it is"


@needs_node
def test_the_engine_draws_the_tower_of_the_other_project_after_a_missing_floor_and_after_back(tmp_path):
    # the page's sequence: Floor of project A, the switcher to B (its Floor is missing: the world is B's, no floor), then Back to the building (B's Building)
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + PRODUCT_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
const host = document.createElement("div");
const engine = createEngine(host, { label: "scene", getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0 }), onOpen() {}, onHover() {} });
const settle = () => { for (let i = 0; i < 90; i++) frame(40); };
const out = {};
engine.show("world", models.floor([], "marketing"), "Floor"); settle();
out.floorOfA = engine.canvas.wbStats().towers;
const missing = worldModel(snapshot, NOW, { selectedId: B, focus: B, floor: null, room: null, documents: null });
engine.show("world", missing, "Floor, agent not in the configuration"); settle();
out.missing = { towers: engine.canvas.wbStats().towers, samples: engine.canvas.wbSamples().length };
const building = worldModel(snapshot, NOW, { selectedId: B, focus: B, documents: null });
engine.show("world", building, "Building of docs"); settle();
out.back = { towers: engine.canvas.wbStats().towers, samples: engine.canvas.wbSamples().length };
// the same Building shown by a visit that never saw a Floor
const fresh = createEngine(document.createElement("div"), { label: "scene", getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0 }), onOpen() {}, onHover() {} });
fresh.show("world", building, "Building of docs"); settle();
out.fresh = { samples: fresh.canvas.wbSamples().length };
console.log(JSON.stringify(out));
""")
    assert got["missing"]["towers"]["bbbbbbbbbbbb"] == 1 and got["back"]["towers"]["bbbbbbbbbbbb"] == 1, "the new open building is open"
    assert got["missing"]["samples"] > 0, "the missing Floor's scene already shows B's building (its floors can be picked)"
    assert got["back"]["samples"] > 0 and got["fresh"]["samples"] > 0, "Back to the building draws the tower and its floors, as a first visit to the Building does (the counts differ by what the camera shows)"


# --- the switcher (M-13) -----------------------------------------------------------------------------------------------------------------------------

SWITCH_JS = r"""
import * as router from "@JS@/router.js";
import * as fm from "@JS@/floor-model.js";

const P = "0123456789ab", Q = "ba9876543210", R = "00000000000f";
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 6, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0 });
const detail = (names) => ({ status: { requests: [], pending: [] }, agents: names.map(agent) });
const snapshot = {
  loaded: true, tasks: {},
  projects: [{ id: P, name: "alpha", config: { accepted: true } }, { id: Q, name: "bravo", config: { accepted: true } }, { id: R, name: "charlie", config: { accepted: false } }],
  details: { [P]: detail(["planning", "engineering", "marketing"]), [Q]: detail(["planning", "engineering", "brand"]), [R]: { error: { status: 412, message: "not accepted" } } },
};
// what the page does on a choice: the route it is on, the project chosen, whether that project has the route's floor
const go = (hash, to) => { const route = router.parse(hash); return router.switchHash(route, to, route.agent ? fm.hasFloor(snapshot, to, route.agent) : true); };
const out = {
  hasFloor: [fm.hasFloor(snapshot, P, "marketing"), fm.hasFloor(snapshot, Q, "marketing"), fm.hasFloor(snapshot, Q, "engineering"), fm.hasFloor(snapshot, R, "marketing"),
    fm.hasFloor(snapshot, "ffffffffffff", "marketing"), fm.hasFloor(snapshot, Q, "planning")],
  floorMissing: go(`#/p/${P}/floor/marketing`, Q),
  floorMissingOnTab: go(`#/p/${P}/floor/marketing/inbox/7`, Q),
  floorBoth: go(`#/p/${P}/floor/engineering`, Q),
  floorBothOnTab: go(`#/p/${P}/floor/engineering/inbox/7`, Q),
  floorDesk: go(`#/p/${P}/floor/engineering/desk/${encodeURIComponent("docs/a.md")}`, Q),
  floorNotAccepted: go(`#/p/${P}/floor/marketing`, R),
  lobby: go(`#/p/${P}/lobby`, Q),
  lobbyTab: go(`#/p/${P}/lobby/inbox/3`, Q),
  control: go(`#/p/${P}/control`, Q),
  controlTab: go(`#/p/${P}/control/costs`, Q),
  building: go(`#/p/${P}`, Q),
};
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_switcher_keeps_the_floor_only_when_the_target_project_has_that_area_agent(tmp_path):
    got = run_node(tmp_path, SWITCH_JS)
    P, Q, R = "0123456789ab", "ba9876543210", "00000000000f"
    assert got["hasFloor"] == [True, False, True, True, False, False], \
        "a project has the floor of an area agent it lists; a project not accepted keeps its (waiting) floors; an unknown project and the planning agent (its floor is the Lobby) have none"
    assert got["floorMissing"] == f"#/p/{Q}" and got["floorMissingOnTab"] == f"#/p/{Q}", "no such floor in the target: its Building, whatever tab or decision the floor was on"
    assert got["floorBoth"] == f"#/p/{Q}/floor/engineering", "a floor both projects have stays a floor (as before)"
    assert got["floorBothOnTab"] == f"#/p/{Q}/floor/engineering" and got["floorDesk"] == f"#/p/{Q}/floor/engineering", "a tab, a decision or a document belongs to the floor of the project left: the floor opens on its own tab"
    assert got["floorNotAccepted"] == f"#/p/{R}/floor/marketing", "a project that is not accepted answers for every floor with its waiting line: the floor is kept"
    assert got["lobby"] == f"#/p/{Q}/lobby" and got["lobbyTab"] == f"#/p/{Q}/lobby" and got["control"] == f"#/p/{Q}/control" and got["controlTab"] == f"#/p/{Q}/control", \
        "the Lobby and the Control room exist in every project: kept, on their first tab"
    assert got["building"] == f"#/p/{Q}", "a Building stays a Building"


def test_the_page_chooses_the_hash_of_a_project_switch_through_the_routers_rule():
    main = (JS / "main.js").read_text(encoding="utf-8")
    start = main.index("function selectProject(id)")
    body = main[start:main.index("\n}\n", start)]
    assert "router.switchHash(route, id," in body and "fm.hasFloor(snapshot, id, route.agent)" in body, "the page asks the floor model whether the target has the floor, and the router for the hash"
    assert "router.floorHash(id, route.agent)" not in body, "no more floor kept without asking"
