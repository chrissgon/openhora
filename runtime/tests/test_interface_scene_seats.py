"""PAR-7: several owls on a floor, the desks in an L. A floor draws one workstation (desk, chair, owl) for each task that holds a slot of its agent, in a fixed L
at the room's open front corner (three seats on the left arm, one on the right), never an empty desk, every workstation the same size on every floor, an owl asleep sitting in
its chair, a waiting owl standing at a place of its own. The layout is pure arithmetic (`scene/seats-layout.js`), the choice of which task sits where is pure (`seats.js`), the
room draws what it is given (`fillFloor`) and the tower makes a room again when its seats change.

No browser and no model: the pure modules run under Node, the room builders with the real three.js and no WebGL, as the other scene tests do.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scene_seats.py
"""
from __future__ import annotations

import re
import sys

import standin_tree as st
from test_interface_parallel import COMMON as MODEL_COMMON
from test_interface_plates_meters import run_node as run_model_node
from test_interface_scene_r4_rooms import PLANTS_JS, ROOMS_JS
from test_interface_scene_round3 import needs_node, run_node

SCENE = st.REPO / "interface" / "js" / "scene"
JS = st.REPO / "interface" / "js"

SEATS_JS = PLANTS_JS + r"""
import * as layout from "@JS@/scene/seats-layout.js";
import { seatsOf } from "@JS@/seats.js";
import { fillFloor } from "@JS@/scene/building.js";
import { buildOwl, towardCamera } from "@JS@/scene/owl-build.js";
const r3 = (v) => Math.round(v * 1000) / 1000;
const roomOf = (seats, extra = {}) => {
  const kit = createKit(palette);
  const parent = new THREE.Group();
  const lists = { motions: [], markers: [], outlines: [] };
  const f = { name: "engineering", state: "working", window: "lit", decisions: 0, lobby: false, notes: [], documents: 0, seats, ...extra };
  const parts = fillFloor(kit, parent, f, { lot: "a", accepted: extra.accepted !== false, ...lists });
  return { kit, parent, parts, lists };
};
const stillVertices = (parent) => parent.children[0].children[0].geometry.getAttribute("position").count;
const seat = (n, pose) => ({ seat: n, pose, taskId: null });
"""


# --- the layout ---------------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_l_has_four_seats_and_a_corner_with_the_numbers_of_the_design(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const out = {};
out.seats = layout.seats().map((s) => ({ index: s.index, arm: s.arm, turn: s.turn, x: [r3(s.desk.x0), r3(s.desk.x1)], z: [r3(s.desk.z0), r3(s.desk.z1)], q: s.q.map(r3) }));
const cn = layout.corner();
out.corner = [r3(cn.x0), r3(cn.x1), r3(cn.z0), r3(cn.z1)];
out.constants = [layout.S, layout.C0, layout.TIP, layout.CORNER, r3(layout.DESK_LEN), r3(layout.DESK_DEP), layout.SEAT_COUNT, Object.isFrozen(layout.C0), Object.isFrozen(layout.TIP)];
console.log(JSON.stringify(out));
""")
    want = [
        (0, "swap", [4.417, 5.920], [4.768, 5.530], [5.169, 5.149]),
        (1, "none", [6.158, 6.920], [3.027, 4.530], [6.539, 3.779]),
        (2, "swap", [2.914, 4.417], [4.768, 5.530], [3.666, 5.149]),
        (3, "swap", [1.412, 2.914], [4.768, 5.530], [2.163, 5.149]),
    ]
    assert [s["index"] for s in got["seats"]] == [0, 1, 2, 3], "four seats, in the order they fill"
    for s, (index, turn, x, z, q) in zip(got["seats"], want):
        assert s["turn"] == turn, f"seat {index} turns {turn}"
        for a, b in zip(s["x"] + s["z"] + s["q"], x + z + q):
            assert abs(a - b) <= 0.005, f"seat {index}: the desk top and the seat centre are the design's ({s} against {x} {z} {q})"
    assert [s["arm"] for s in got["seats"]] == ["left", "right", "left", "left"]
    assert all(abs(a - b) <= 0.005 for a, b in zip(got["corner"], [5.920, 6.920, 4.530, 5.530])), "the corner top is a square of side 1 at the L's point"
    assert got["constants"][0] == 0.68 and got["constants"][1] == [5.895, 3.78] and got["constants"][2] == [6.92, 5.53] and got["constants"][3] == 1.0 and got["constants"][6] == 4, "the constants are the design's"
    assert got["constants"][4] == 1.503 and got["constants"][5] == 0.762 and got["constants"][7] is True and got["constants"][8] is True, "derived from 2.21 and 1.12 at 0.68, and frozen"


@needs_node
def test_a_seat_transform_maps_the_working_owl_and_the_chair_as_the_design(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const out = {};
const at = (i, p) => { const q = layout.seatPoint(layout.seat(i), [p[0], 0.5, p[1]]); return [q[0], q[1], q[2]].map(r3); };
out.owl = [0, 1, 2, 3].map((i) => at(i, SEAT.owl.working));
out.chair = [0, 1].map((i) => at(i, SEAT.chair));
out.work = layout.WORK_OWL;
out.working = SEAT.owl.working;
console.log(JSON.stringify(out));
""")
    owl = [[5.074, 4.377], [5.768, 3.684], [3.571, 4.377], [2.068, 4.377]]
    chair = [[5.101, 4.404], [5.795, 3.711]]
    for seat_no, (x, z) in enumerate(owl):
        a = got["owl"][seat_no]
        assert abs(a[0] - x) <= 0.005 and abs(a[2] - z) <= 0.005, f"the working owl at seat {seat_no} is at ({x}, {z})"
        assert abs(a[1] - 0.5 * 0.68) <= 0.005, "a height is scaled by 0.68"
    for seat_no, (x, z) in enumerate(chair):
        a = got["chair"][seat_no]
        assert abs(a[0] - x) <= 0.005 and abs(a[2] - z) <= 0.005, f"the chair at seat {seat_no} is at ({x}, {z})"
    assert got["work"] == got["working"], "the layout's working place is the furniture's"


@needs_node
def test_every_desk_and_the_corner_stand_inside_the_floor(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
import { desk, chair, cornerTop } from "@JS@/scene/furniture.js";
import { seatBatch } from "@JS@/scene/room-frame.js";
const tones = roomTones(light);
const record = () => {
  const log = [];
  const pb = { box: (t, x, y, z, w, h, d) => { log.push({ x0: x, x1: x + w, y0: y, y1: y + h, z0: z, z1: z + d }); return pb; },
    front: (t, x0, y0, x1, y1, z) => { log.push({ x0, x1, y0, y1, z0: z, z1: z }); return pb; }, side: (t, z0, y0, z1, y1, x) => { log.push({ x0: x, x1: x, y0, y1, z0, z1 }); return pb; },
    flat: (t, x0, z0, x1, z1, y) => { log.push({ x0, x1, y0: y, y1: y, z0, z1 }); return pb; } };
  return { pb, log };
};
const out = { seats: [] };
for (let i = 0; i < 4; i++) {
  const { pb, log } = record();
  const sb = seatBatch(pb, layout.seat(i));
  desk(sb, tones);
  chair(sb, tones);
  const lo = (k) => Math.min(...log.map((b) => b[k]));
  const hi = (k) => Math.max(...log.map((b) => b[k]));
  out.seats.push({ x0: lo("x0"), x1: hi("x1"), z0: lo("z0"), z1: hi("z1"), n: log.length });
}
{
  const { pb, log } = record();
  cornerTop(pb, tones);
  out.corner = { x0: Math.min(...log.map((b) => b.x0)), x1: Math.max(...log.map((b) => b.x1)), z0: Math.min(...log.map((b) => b.z0)), z1: Math.max(...log.map((b) => b.z1)), n: log.length };
}
// the legs of the right desk: its far corner
{
  const { pb, log } = record();
  desk(seatBatch(pb, layout.seat(1)), tones);
  out.rightLegs = Math.max(...log.filter((b) => b.y1 - b.y0 > 0.3 && b.y1 - b.y0 < 0.45 && b.x1 - b.x0 < 0.08).map((b) => b.x1));
}
console.log(JSON.stringify(out));
""")
    for i, s in enumerate(got["seats"]):
        assert s["n"] > 20, f"seat {i} draws its desk and its chair"
        assert 0.2 <= s["x0"] and s["x1"] <= 7 and 0.2 <= s["z0"] and s["z1"] <= 5.6, f"seat {i}: the desk and the chair stand inside the floor (the walls are 0.2 thick): {s}"
    c = got["corner"]
    assert 0.2 <= c["x0"] and c["x1"] <= 7 and 0.2 <= c["z0"] and c["z1"] <= 5.6 and c["n"] >= 2, f"the corner top stands inside the floor: {c}"
    assert got["rightLegs"] <= 6.95, "the legs of the right desk do not pass the floor's edge"


@needs_node
def test_four_standing_owls_are_each_at_least_one_unit_apart(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const out = {};
out.places = [0, 1, 2, 3].map((i) => layout.standAt(i).map(r3));
out.apart = [];
for (let a = 0; a < 4; a++) for (let b = a + 1; b < 4; b++) out.apart.push(Math.hypot(layout.standAt(a)[0] - layout.standAt(b)[0], layout.standAt(a)[1] - layout.standAt(b)[1]));
console.log(JSON.stringify(out));
""")
    for a, b in zip(got["places"], [[4.382, 3.508], [6.392, 2.179], [2.879, 3.508], [1.376, 3.508]]):
        assert abs(a[0] - b[0]) <= 0.005 and abs(a[1] - b[1]) <= 0.005, "the standing places are the design's"
    assert min(got["apart"]) >= 1.0, "any two standing owls are at least one unit apart on the floor"


def test_the_layout_has_a_place_for_every_slot_the_runtime_allows(tmp_path=None):
    sys.path.insert(0, str(st.REPO / "runtime"))
    import autonomy
    layout = (SCENE / "seats-layout.js").read_text(encoding="utf-8")
    found = re.findall(r"export const SEAT_COUNT\s*=\s*(\d+)", layout)
    assert found and int(found[0]) == autonomy.MAX_PARALLEL_CEILING, "the L is drawn for as many places as the runtime lets a floor hold: raising the cap fails here until the room is designed for more"


def test_the_cap_is_written_once():
    files = [p for p in (st.REPO / "runtime").rglob("*.py") if "tests" not in p.relative_to(st.REPO / "runtime").parts] + list((st.REPO / "interface" / "js").rglob("*.js"))
    hits = []
    for path in files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"MAX_PARALLEL_CEILING\s*=\s*\d", line):
                hits.append(f"{path.relative_to(st.REPO)}:{number}")
    assert len(hits) == 1 and hits[0].startswith("runtime/autonomy.py:"), f"the cap is one constant in runtime/autonomy.py: {hits}"
    for path in (st.REPO / "interface" / "js").rglob("*.js"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not re.search(r"max_parallel.*\b4\b", line), f"the interface writes no cap: {path.relative_to(st.REPO)}:{number}"


@needs_node
def test_no_standing_owl_covers_the_lobbys_door_or_its_plaque(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
import { PLAQUE } from "@JS@/scene/furniture.js";
const out = {};
const hull = (points) => { const p = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]); const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); const lo = []; for (const q of p) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); } const up = []; for (const q of [...p].reverse()) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); } return [...lo.slice(0, -1), ...up.slice(0, -1)]; };
const onScreen = (list) => list.map(([x, y, z]) => { const p = new THREE.Vector3(FRAME.X(x), FRAME.Y(y), FRAME.Z(z)).applyMatrix4(camera.matrixWorldInverse); return [p.x, p.y]; });
const boxHull = (x0, x1, y0, y1, z0, z1) => hull(onScreen([x0, x1].flatMap((x) => [y0, y1].flatMap((y) => [z0, z1].map((z) => [x, y, z])))));
const gap = (A, B) => { let best = -1e9; for (const P of [A, B]) for (let i = 0; i < P.length; i++) { const a = P[i]; const b = P[(i + 1) % P.length]; const n = [b[1] - a[1], a[0] - b[0]]; const l = Math.hypot(...n); n[0] /= l; n[1] /= l; const pa = A.map((p) => p[0] * n[0] + p[1] * n[1]); const pb = B.map((p) => p[0] * n[0] + p[1] * n[1]); best = Math.max(best, Math.max(Math.min(...pb) - Math.max(...pa), Math.min(...pa) - Math.max(...pb))); } return best; };
const S = layout.S;
const door = boxHull(0.2, 0.2, 0, DOOR.top, DOOR.z0, DOOR.z1);
const plaque = boxHull(PLAQUE.x, PLAQUE.x + 0.04 + PLAQUE.relief, PLAQUE.y0, PLAQUE.y1, PLAQUE.z0, PLAQUE.z1);
out.owls = [0, 1, 2, 3].map((i) => { const [x, z] = layout.standAt(i); const o = boxHull(x - 0.5 * S, x + 0.5 * S, 0, 1.4 * S, z - 0.5 * S, z + 0.5 * S); return { door: gap(o, door), plaque: gap(o, plaque) }; });
out.sitting = [0, 1, 2, 3].map((i) => { const [x, z] = layout.footAt(i, "working"); const o = boxHull(x - 0.5 * S, x + 0.5 * S, 0, 1.4 * S, z - 0.5 * S, z + 0.5 * S); return { door: gap(o, door), plaque: gap(o, plaque) }; });
out.desks = [2, 3].map((i) => { const d = layout.seats()[i].desk; const o = boxHull(d.x0, d.x1, 0, 1.4 * S, d.z0, d.z1); return { door: gap(o, door), plaque: gap(o, plaque) }; });
console.log(JSON.stringify(out));
""")
    for kind in ("owls", "sitting", "desks"):
        for i, r in enumerate(got[kind]):
            assert r["door"] > 0 and r["plaque"] > 0, f"{kind}[{i}] keeps a positive gap from the Lobby's door and its plaque ({r}); if seat 3's standing place fails, stop and report: it is not moved here"


# --- which owl sits where ------------------------------------------------------------------------------------------------------------------------

SEATS_ONLY = r"""
import { seatsOf } from "@JS@/seats.js";
const t = (id, state, extra = {}) => ({ id, state, holds_slot: true, ...extra });
const out = {};
"""


@needs_node
def test_a_floor_that_is_off_or_not_accepted_keeps_its_desks_and_no_owl(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
const tasks = [t(1, "running")];
out.off = seatsOf(tasks, { state: "off", accepted: true });
out.refused = seatsOf(tasks, { state: "working", accepted: false });
out.offIdle = seatsOf([], { state: "off", accepted: true });
console.log(JSON.stringify(out));
""")
    bare = [{"seat": 0, "pose": None, "taskId": None}]
    assert got == {"off": bare, "refused": bare, "offIdle": bare}, "an off agent and a project that is not accepted keep their desks (one with no max_parallel) and show no owl (PAR-7c, 11.1)"


@needs_node
def test_one_seat_per_task_that_holds_a_slot_ordered_by_id(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
const tasks = [t(9, "running"), t(3, "waiting"), t(5, "running"), { id: 2, state: "failed", holds_slot: false }, { id: 4, state: "done", holds_slot: false }];
out.seats = seatsOf(tasks, { state: "working", accepted: true });
console.log(JSON.stringify(out));
""")
    assert got["seats"] == [{"seat": 0, "pose": "waiting", "taskId": 3}, {"seat": 1, "pose": "working", "taskId": 5}, {"seat": 2, "pose": "working", "taskId": 9}], \
        "a seat for each holder, by id, from the first; a task that holds no slot has none"


@needs_node
def test_the_seats_refill_when_an_older_holder_ends(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
const all = [t(3, "running"), t(5, "running"), t(9, "running")];
out.before = seatsOf(all, { state: "working", accepted: true }).map((s) => [s.seat, s.taskId]);
out.after = seatsOf(all.slice(1), { state: "working", accepted: true }).map((s) => [s.seat, s.taskId]);
console.log(JSON.stringify(out));
""")
    assert got["before"] == [[0, 3], [1, 5], [2, 9]] and got["after"] == [[0, 5], [1, 9]], "when the oldest holder ends, the owls after it move one seat down"


@needs_node
def test_waiting_holders_stand_and_an_answered_one_is_ready(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
out.seats = seatsOf([t(1, "running"), t(2, "waiting"), t(3, "ready")], { state: "working", accepted: true }).map((s) => s.pose);
console.log(JSON.stringify(out));
""")
    assert got["seats"] == ["working", "waiting", "ready"], "a running task types, a waiting one stands, an answered one about to run again is awake at its desk"


@needs_node
def test_holders_come_from_every_request_of_the_agent(tmp_path):
    got = run_model_node(tmp_path, MODEL_COMMON + r"""
import { seatsOf } from "@JS@/seats.js";
const eng = (id, state, hold, extra = {}) => task(id, state, "engineering", { holds_slot: hold, ...extra });
const snap = snapshot([eng(4, "running", true), eng(5, "done", false), eng(6, "waiting", true)], [agent("planning"), agent("engineering", { max_parallel: 3, slots_held: 2, holders: [4, 6] })], { running_task: 4, running_tasks: [4] });
// a second request of the same project, with a holder of the same agent
snap.details[P].status.requests.push({ id: 2, title: "Autumn", state: "ready", tasks: [eng(11, "running", true, {}), eng(12, "failed", false)] });
const view = fm.building(snap, P);
const row = view.rows.find((r) => r.name === "engineering");
out.holders = row.holders;
out.seats = row.seats.map((s) => [s.seat, s.pose, s.taskId]);
const planning = view.rows.find((r) => r.name === "planning");
out.planning = [planning.holders, planning.seats];
const scene = fm.buildingScene(view, null, {});
out.scene = scene.floors.find((f) => f.name === "engineering").seats.length;
console.log(JSON.stringify(out));
""")
    assert got["holders"] == [{"id": 11, "state": "running", "holds_slot": True}, {"id": 6, "state": "waiting", "holds_slot": True}, {"id": 4, "state": "running", "holds_slot": True}], \
        "the holders are the agent's tasks of every request that hold a slot (newest first, as agentTasks gives them), each {id, state, holds_slot}"
    assert got["seats"] == [[0, "working", 4], [1, "waiting", 6], [2, "working", 11]], "and they sit by id"
    assert got["planning"][0] == [] and got["planning"][1][0]["taskId"] is None, "an agent with no holder has its one owl at seat 0"
    assert got["scene"] == 3, "the scene's floor object carries the seats"


@needs_node
def test_a_holder_of_another_request_has_a_seat(tmp_path):
    got = run_model_node(tmp_path, MODEL_COMMON + r"""
const snap = snapshot([task(4, "done", "engineering", { holds_slot: false })], [agent("planning"), agent("engineering", { slots_held: 1, holders: [21] })], {});
snap.details[P].status.requests.push({ id: 9, title: "Other", state: "ready", tasks: [task(21, "running", "engineering", { holds_slot: true })] });
const row = fm.building(snap, P).rows.find((r) => r.name === "engineering");
out.seats = row.seats.map((s) => [s.seat, s.pose, s.taskId]);
out.followed = row.notes;
console.log(JSON.stringify(out));
""")
    assert got["seats"] == [[0, "working", 21]], "a task of a request the page is not following still sits: the floor's desks are the agent's, not the request's"


@needs_node
def test_the_lobby_during_a_turn_recomputes_its_seats(tmp_path):
    got = run_model_node(tmp_path, MODEL_COMMON + r"""
import { worldModel } from "@JS@/world-model.js";
const snap = snapshot([task(4, "running", "engineering")], [agent("planning"), agent("engineering", { slots_held: 1, holders: [4] })], { running_task: 4, running_tasks: [4] });
const lobby = (model) => model.lots[0].floors.find((f) => f.name === "planning");
const quiet = worldModel(snap, NOW, { focus: P, floor: "planning", room: { tips: {}, board: null, door: true } });
const turn = worldModel(snap, NOW, { focus: P, floor: "planning", room: { tips: {}, board: null, door: true, state: "working", window: "lit" } });
const asks = worldModel(snap, NOW, { focus: P, floor: "planning", room: { tips: {}, board: null, door: true, state: "waiting" } });
out.quiet = [lobby(quiet).state, lobby(quiet).seats.map((s) => s.pose)];
out.turn = [lobby(turn).state, lobby(turn).seats.map((s) => [s.seat, s.pose])];
out.asks = [lobby(asks).state, lobby(asks).seats.map((s) => [s.seat, s.pose])];
console.log(JSON.stringify(out));
""")
    assert got["quiet"][0] == "idle" and got["quiet"][1] == ["idle"], "the Lobby at rest: one owl asleep"
    assert got["turn"] == ["working", [[0, "working"]]], "while the router runs and no task of the planning agent holds a slot, the Lobby has its one typing owl"
    assert got["asks"] == ["waiting", [[0, "waiting"]]], "and one standing when a plan or a router question waits on the person"


@needs_node
def test_a_lobby_that_waits_with_no_holder_shows_its_owl_waiting(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
out.waiting = seatsOf([], { state: "waiting", accepted: true });
console.log(JSON.stringify(out));
""")
    assert got["waiting"] == [{"seat": 0, "pose": "waiting", "taskId": None}], "a plan, an acceptance or a router question waits on a request, which holds no slot: its one owl stands"


@needs_node
def test_never_more_seats_than_the_layout_has(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
// one more holder than the L has places (an answered task back from a derived wait): no typing owl is dropped, never more than four are drawn
const many = [t(1, "waiting"), t(2, "waiting"), t(3, "running"), t(4, "waiting"), t(5, "running")];
out.five = seatsOf(many, { state: "working", accepted: true }).map((s) => [s.seat, s.taskId, s.pose]);
const none = [t(1, "waiting"), t(2, "waiting"), t(3, "waiting"), t(4, "waiting"), t(5, "waiting"), t(6, "ready")];
out.waiters = seatsOf(none, { state: "waiting", accepted: true }).map((s) => s.taskId);
console.log(JSON.stringify(out));
""")
    assert len(got["five"]) == 4 and [s[0] for s in got["five"]] == [0, 1, 2, 3], "four places, filled from the first"
    ids = [s[1] for s in got["five"]]
    assert 3 in ids and 5 in ids, "the running holders are kept first"
    assert ids == sorted(ids), "and the kept ones sit by id"
    assert got["waiters"] == [1, 2, 3, 4], "with no running holder, the oldest four"


@needs_node
def test_an_idle_floor_has_one_owl_asleep_at_seat_0(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
out.idle = seatsOf([], { state: "idle", accepted: true });
out.stale = seatsOf([{ id: 1, state: "done", holds_slot: false }], { state: "idle", accepted: true });
console.log(JSON.stringify(out))
""")
    assert got["idle"] == [{"seat": 0, "pose": "idle", "taskId": None}] and got["stale"] == got["idle"], "no task holds a slot: one owl, asleep"


@needs_node
def test_a_ready_floor_has_one_awake_owl_at_seat_0(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
out.ready = seatsOf([], { state: "ready", accepted: true });
console.log(JSON.stringify(out))
""")
    assert got["ready"] == [{"seat": 0, "pose": "ready", "taskId": None}], "a queued floor: one owl awake at its desk"


@needs_node
def test_the_lobby_routing_has_one_typing_owl(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
out.routing = seatsOf([], { state: "working", accepted: true });
out.withHolders = seatsOf([t(7, "running")], { state: "working", accepted: true });
console.log(JSON.stringify(out))
""")
    assert got["routing"] == [{"seat": 0, "pose": "working", "taskId": None}], "the router runs: the Lobby's one owl types"
    assert got["withHolders"] == [{"seat": 0, "pose": "working", "taskId": 7}], "when a task of the planning agent holds a slot, the holder sits and nothing more is drawn for the router"


# --- the room draws what it is given ---------------------------------------------------------------------------------------------------------------

@needs_node
def test_a_room_draws_one_desk_per_seat_and_no_empty_desk(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const out = {};
const pose = ["working", "waiting", "working", "ready"];
const lists = [[], [0], [0, 1], [0, 1, 2], [0, 1, 2, 3]];
out.owls = lists.map((l) => roomOf(l.map((i) => seat(i, pose[i]))).parts.owls.length);
out.vertices = lists.map((l) => stillVertices(roomOf(l.map((i) => seat(i, pose[i]))).parent));
out.none = roomOf([]).parts.agent === null;
out.off = roomOf([seat(0, null)], { state: "off", accepted: false }).parts.owls.length;
out.offDesks = [1, 2, 3].map((n) => stillVertices(roomOf(Array.from({ length: n }, (_, i) => seat(i, null)), { state: "off", accepted: false }).parent));
out.offAgent = roomOf([seat(0, null), seat(1, null), seat(2, null)], { state: "off" }).parts.agent === null;
const asleep = roomOf([seat(0, "idle"), seat(1, "idle"), seat(2, "idle")]);
const bare = roomOf([seat(0, null), seat(1, null), seat(2, null)]);
out.sameDesks = stillVertices(asleep.parent) === stillVertices(bare.parent);
out.disposed = (() => { bare.parts.dispose(); return true; })();
console.log(JSON.stringify(out));
""")
    assert got["owls"] == [0, 1, 2, 3, 4], "one owl for each seat"
    v = got["vertices"]
    desk = v[1] - v[0]
    assert desk > 0, "a seat draws a desk and a chair"
    assert v[3] - v[2] == desk and v[4] - v[3] == desk, "seats 2 and 3 add exactly one desk each, nothing more"
    assert v[2] - v[1] > desk, "seat 1 adds its desk and the corner top that joins the arms"
    assert got["none"] is True, "no seat: no owl, no group"
    assert got["off"] == 0 and got["offAgent"] is True, "a floor that is off or not accepted draws no owl, and no owls group"
    assert got["offDesks"][0] > 0 and got["offDesks"][1] > got["offDesks"][0] and got["offDesks"][2] > got["offDesks"][1], "but its desks stay, one for each seat the row carries"
    assert got["sameDesks"] is True and got["disposed"] is True, "three desks without owls are the same furniture as three desks with sleeping owls, and the room frees"


@needs_node
def test_the_corner_top_is_drawn_only_with_seats_0_and_1(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const v = (ids) => stillVertices(roomOf(ids.map((i) => seat(i, "working"))).parent);
const base = v([]);
const out = { zero: v([0]) - base, one: v([1]) - base, two: v([2]) - base, zeroTwo: v([0, 2]) - base, zeroOne: v([0, 1]) - base, all: v([0, 1, 2, 3]) - base };
console.log(JSON.stringify(out));
""")
    d = got["zero"]
    assert got["one"] == d and got["two"] == d and got["zeroTwo"] == 2 * d, "without both of seats 0 and 1 there is no corner top: a desk is a desk"
    assert got["zeroOne"] > 2 * d and got["all"] == got["zeroOne"] + 2 * d, "with seats 0 and 1 together the square top joins the arms"
    corner = got["zeroOne"] - 2 * d
    assert corner > 0 and got["all"] - 4 * d == corner, "once, whatever the other seats"


@needs_node
def test_an_owl_asleep_sits_where_it_types_and_a_waiting_owl_stands_at_its_place(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const out = {};
const pos = (i, pose) => { const g = roomOf([seat(i, pose)]).parts.owls[0].group; return [g.position.x, g.position.y, g.position.z].map(r3); };
const lift = (k) => { const v = towardCamera(THREE).multiplyScalar(k * layout.S); return v; };
const expect = (xz, k) => { const v = lift(k); return [FRAME.X(xz[0]) + v.x, FRAME.Y(0.01) + v.y, FRAME.Z(xz[1]) + v.z].map(r3); };
out.cases = [];
for (const i of [0, 1, 2, 3]) {
  out.cases.push({ i, working: pos(i, "working"), idle: pos(i, "idle"), ready: pos(i, "ready"), waiting: pos(i, "waiting"),
    wantSit: expect(layout.footAt(i, "working"), 0.7), wantStand: expect(layout.standAt(i), 0.3) });
}
console.log(JSON.stringify(out));
""")
    for c in got["cases"]:
        assert c["working"] == c["idle"] == c["ready"] == c["wantSit"], f"seat {c['i']}: working, ready and asleep owls are at the seat, asleep in the chair exactly where it types"
        assert c["waiting"] == c["wantStand"], f"seat {c['i']}: a waiting owl stands at its own place"
        assert c["waiting"] != c["working"], "and that is not the seat"


@needs_node
def test_the_left_arms_owls_are_mirrored_and_still_drawn(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const out = {};
const side = (i, pose) => { const owl = roomOf([seat(i, pose)]).parts.owls[0].group; const mats = new Set(); owl.traverse((n) => { if (n.material) [].concat(n.material).filter((m) => m.visible !== false).forEach((m) => mats.add(m.side)); });   // the invisible plane the pointer meets is not drawn
  return [owl.scale.x < 0, owl.scale.y > 0, [...mats].every((s) => s === THREE.DoubleSide)]; };
out.left = ["working", "ready", "waiting"].map((p) => [0, 2, 3].map((i) => side(i, p)));
out.right = ["working", "ready", "waiting"].map((p) => side(1, p));
console.log(JSON.stringify(out));
""")
    for row in got["left"]:
        assert all(c[0] and c[1] and c[2] for c in row), "an owl of the left arm is mirrored left to right (a negative x scale) and its materials show both faces"
    for c in got["right"]:
        assert c[0] is False and c[2] is True, "the right arm's owl is not mirrored"


@needs_node
def test_the_asleep_owl_is_never_mirrored(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const out = [0, 1, 2, 3].map((i) => roomOf([seat(i, "idle")]).parts.owls[0].group.scale.x > 0);
console.log(JSON.stringify({ out }));
""")
    assert got["out"] == [True] * 4, "the 'zz' of a sleeping owl would read backwards: it is not mirrored on any seat"


@needs_node
def test_the_owls_are_the_same_size_on_every_floor(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const out = {};
// a mirrored owl swaps its extents along the floor's two axes (the billboard stands at 45 degrees): compare the extents sorted
const size = (group) => { group.updateWorldMatrix(true, true); const b = new THREE.Box3().setFromObject(group); return [b.max.y - b.min.y, ...[b.max.x - b.min.x, b.max.z - b.min.z].sort((a, c) => a - c)].map((v) => Math.round(v * 1e5) / 1e5); };
const kit = createKit(palette);
out.sizes = {};
for (const pose of ["working", "waiting", "ready", "idle"]) {
  const reference = buildOwl(kit, pose, { scale: owlScale(FRAME) * layout.S, mix: palette.mix, floorTone: roomTones(palette).floor, handLift: pose === "working" ? 0.5 : 0 });
  const want = size(reference.group);
  const drawn = [[seat(0, pose)], [seat(0, pose), seat(1, pose)], [seat(0, pose), seat(1, pose), seat(2, pose), seat(3, pose)]].map((l) => roomOf(l).parts.owls.map((o) => size(o.group)));
  out.sizes[pose] = { want, same: drawn.flat().every((s) => s.every((v, k) => v === want[k])), n: drawn.flat().length };
}
const big = layout.S;
const old = buildOwl(kit, "working", { scale: owlScale(FRAME), mix: palette.mix, floorTone: roomTones(palette).floor, handLift: 0.5 });
out.ratio = [size(old.group)[0], out.sizes.working.want[0], big];
console.log(JSON.stringify(out));
""")
    for pose, s in got["sizes"].items():
        assert s["same"] is True and s["n"] == 7, f"a {pose} owl is the same size in a room of one seat, two seats and four seats: 0.68 of today's owl"
    assert abs(got["ratio"][1] / got["ratio"][0] - 0.68) < 0.01, "and that size is today's owl scaled by 0.68"


@needs_node
def test_a_room_rebuilds_when_its_seats_change_and_not_otherwise(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const withSeats = (seats) => lot("a", { floors: lot("a").floors.map((f, i) => (i === 3 ? { ...f, name: "engineering", state: "working", window: "lit", seats } : { ...f, seats: [] })) });
const { world } = make({ lots: [withSeats([seat(0, "working")]), lot("b"), lot("c")] });
world.setFocus("a", true);
const tower = world.towers.get("a");
const room = () => tower.parts[3];
const first = room();
const out = {};
tower.sync(withSeats([seat(0, "working")]));
out.same = room() === first;
tower.sync(withSeats([seat(0, "working"), seat(1, "waiting")]));
const second = room();
out.grown = [second !== first, second.owls.length];
tower.sync(withSeats([seat(0, "working"), seat(1, "waiting")]));
out.again = room() === second;
tower.sync(withSeats([seat(0, "working"), seat(1, "working")]));
out.pose = room() !== second;
const other = tower.parts[0];
out.otherRooms = tower.parts[0] === other;
console.log(JSON.stringify(out));
""")
    assert got["same"] is True and got["again"] is True, "the same seats make nothing again"
    assert got["grown"] == [True, 2], "a new owl at a new seat makes the room again"
    assert got["pose"] is True, "a pose that changes does too"


# --- the plants and the room around the L -----------------------------------------------------------------------------------------------------------

def test_the_scene_modules_state_the_layout_once():
    layout = (SCENE / "seats-layout.js").read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", layout)
    assert "import" not in code and "THREE" not in code and "document" not in code, "pure: no library and no page"
    building = re.sub(r"//.*", "", (SCENE / "building.js").read_text(encoding="utf-8"))
    assert "SEAT.owl" not in building, "the room no longer reads the single owl place"
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(|0x[0-9a-fA-F]{6}", layout), "no colour literal in the layout"


@needs_node
def test_a_room_with_seats_draws_the_slots_it_is_given_in_the_tower(tmp_path):
    got = run_node(tmp_path, SEATS_JS + r"""
const floors = lot("a").floors.map((f, i) => ({ ...f, seats: i === 1 ? [seat(0, "working"), seat(1, "waiting"), seat(2, "working")] : i === 2 ? [] : [seat(0, "idle")] }));
const { world } = make({ lots: [lot("a", { floors }), lot("b"), lot("c")] });
world.setFocus("a", true);
const tower = world.towers.get("a");
console.log(JSON.stringify({ owls: tower.parts.map((p) => p.owls.length), agent: tower.parts.map((p) => p.agent === null ? null : p.agent.children.length), pose: tower.parts.map((p) => p.pose) }));
""")
    assert got["owls"] == [1, 3, 0, 1] and got["agent"] == [1, 3, None, 1], "each floor of the Building has the owls of its seats, in one group for the pointer"
    assert got["pose"] == ["idle", "working", None, "idle"], "`pose` is the pose of seat 0"


# --- the busy slots on the plate and in the floors list (SPEC-PAR-7 section 10) ---------------------------------------------------------------------

PLATES = MODEL_COMMON + r"""
import { FakeNode, find, all } from "@FAKE@";
import { plateNode, rowNode, chipNodes } from "@JS@/scene/plates.js";
const eng = (id, state, hold) => task(id, state, "engineering", { holds_slot: hold });
const view = (max, held, tasks) => fm.building(snapshot(tasks, [agent("planning"), agent("engineering", { max_parallel: max, slots_held: held, holders: tasks.filter((t) => t.holds_slot).map((t) => t.id) })]), P);
const row = (max, held, tasks) => view(max, held, tasks).rows.find((r) => r.name === "engineering");
"""


@needs_node
def test_the_plate_and_the_row_say_the_busy_slots_of_a_floor_with_two_or_more(tmp_path):
    got = run_model_node(tmp_path, PLATES + r"""
const two = row(2, 1, [eng(4, "running", true), eng(5, "ready", false)]);
out.data = fm.plateOf(two).slots;
const plate = plateNode(fm.plateOf(two), {});
const meters = all(plate, ".wb-plate-meter");
out.plate = [meters.length, meters.map((m) => m.textContent), meters[meters.length - 1].attrs.title];
const list = rowNode(fm.plateOf(two), { href: "#" });
out.row = all(list, ".pui-badge").map((n) => n.textContent);
// the plate's meters row is two columns in the page's own grid: a third meter wraps under them and the plate is measured from the document, so it grows by one line
// a floor with one slot says nothing, on the plate or in the row
const one = row(1, 1, [eng(4, "running", true)]);
out.one = [fm.plateOf(one).slots, all(plateNode(fm.plateOf(one), {}), ".wb-plate-meter").length, all(rowNode(fm.plateOf(one), { href: "#" }), ".pui-badge").map((n) => n.textContent)];
// the tiny plate (more than eight floors) is the name row alone
out.tiny = all(plateNode({ ...fm.plateOf(two), tiny: true }, {}), ".wb-plate-meter").length;
// four of four slots
const full = row(4, 4, [eng(4, "running", true), eng(5, "waiting", true), eng(6, "waiting", true), eng(7, "waiting", true)]);
out.full = [fm.plateOf(full).slots.text, all(plateNode(fm.plateOf(full), {}), ".wb-plate-meter").pop().textContent];
console.log(JSON.stringify(out));
""")
    assert got["data"] == {"held": 1, "max": 2, "text": "1 of 2 slots"}, "plateOf carries the agent's slots"
    assert got["plate"][0] == 3 and got["plate"][1][-1] == "1 of 2 slots" and "Slots in use" in got["plate"][2], "the plate draws them as a third meter, with its sentence as the title"
    assert "1 of 2 slots" in got["row"], "the floors list row has them as a chip"
    assert got["one"][0] is None and got["one"][1] == 2 and "1 of 1 slots" not in got["one"][2] and not [t for t in got["one"][2] if "slots" in t], "a floor with the default one slot says nothing"
    assert got["tiny"] == 0, "the plate at its shortest is the name row alone"
    assert got["full"] == ["4 of 4 slots", "4 of 4 slots"]


# --- PAR-7c: a floor shows all its seats --------------------------------------------------------------------------------------------------------

@needs_node
def test_a_floor_shows_a_place_for_every_slot_with_the_free_ones_asleep(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
const pose = (seats) => seats.map((s) => [s.seat, s.pose, s.taskId]);
out.idle3 = pose(seatsOf([], { state: "idle", accepted: true, maxParallel: 3 }));
out.run3 = pose(seatsOf([t(4, "running")], { state: "working", accepted: true, maxParallel: 3 }));
out.wait2 = pose(seatsOf([t(4, "waiting")], { state: "waiting", accepted: true, maxParallel: 2 }));
out.off4 = pose(seatsOf([], { state: "off", accepted: true, maxParallel: 4 }));
out.refused4 = pose(seatsOf([], { state: "idle", accepted: false, maxParallel: 4 }));
out.absent = pose(seatsOf([], { state: "idle", accepted: true }));
out.bad = [pose(seatsOf([], { state: "idle", accepted: true, maxParallel: "3" })), pose(seatsOf([], { state: "idle", accepted: true, maxParallel: 2.5 })), pose(seatsOf([], { state: "idle", accepted: true, maxParallel: 0 }))];
out.excess = pose(seatsOf([t(1, "running"), t(2, "waiting"), t(3, "ready")], { state: "working", accepted: true, maxParallel: 2 }));
out.ready3 = pose(seatsOf([], { state: "ready", accepted: true, maxParallel: 3 }));
out.cap = pose(seatsOf([], { state: "idle", accepted: true, maxParallel: 9 }));
console.log(JSON.stringify(out));
""")
    assert got["idle3"] == [[0, "idle", None], [1, "idle", None], [2, "idle", None]], "max_parallel 3, nothing held: three owls asleep"
    assert got["run3"] == [[0, "working", 4], [1, "idle", None], [2, "idle", None]], "one running task wakes seat 0 only"
    assert got["wait2"] == [[0, "waiting", 4], [1, "idle", None]], "a waiting holder stands, the free place sleeps"
    assert got["off4"] == [[0, None, None], [1, None, None], [2, None, None], [3, None, None]] and got["refused4"] == got["off4"], "a stopped agent or a project not accepted keeps max_parallel desks and no owl (11.1)"
    assert got["absent"] == [[0, "idle", None]], "no max_parallel: one place"
    assert all(b == [[0, "idle", None]] for b in got["bad"]), "a max_parallel that is not a whole number of at least 1 means one place"
    assert got["excess"] == [[0, "working", 1], [1, "waiting", 2], [2, "ready", 3]], "more holders than places: all drawn, none idle"
    assert got["ready3"] == [[0, "ready", None], [1, "idle", None], [2, "idle", None]], "a queued floor: seat 0 awake, the others asleep"
    assert [s[0] for s in got["cap"]] == [0, 1, 2, 3], "never more places than the L has"


@needs_node
def test_the_row_passes_the_agents_max_parallel_to_the_seats(tmp_path):
    got = run_model_node(tmp_path, MODEL_COMMON + r"""
import { worldModel } from "@JS@/world-model.js";
const snap = snapshot([task(4, "done", "engineering", { holds_slot: false })], [agent("planning"), agent("engineering", { max_parallel: 3, slots_held: 0, holders: [] })], {});
const row = fm.building(snap, P).rows.find((r) => r.name === "engineering");
out.eng = row.seats.map((s) => [s.seat, s.pose]);
out.planning = fm.building(snap, P).rows.find((r) => r.name === "planning").seats.length;
console.log(JSON.stringify(out));
""")
    assert got["eng"] == [[0, "idle"], [1, "idle"], [2, "idle"]], "a floor of three slots with nothing running: three owls asleep"
    assert got["planning"] == 1, "an agent with one slot: one place"


@needs_node
def test_a_floor_going_from_off_to_idle_gains_owls_without_a_reload(tmp_path):
    got = run_model_node(tmp_path, SEATS_ONLY + r"""
const pose = (seats) => seats.map((s) => s.pose);
out.off = pose(seatsOf([], { state: "off", accepted: true, maxParallel: 3 }));
out.idle = pose(seatsOf([], { state: "idle", accepted: true, maxParallel: 3 }));
out.json = [JSON.stringify(seatsOf([], { state: "off", accepted: true, maxParallel: 3 })) !== JSON.stringify(seatsOf([], { state: "idle", accepted: true, maxParallel: 3 }))];
console.log(JSON.stringify(out));
""")
    assert got["off"] == [None, None, None] and got["idle"] == ["idle", "idle", "idle"] and got["json"] == [True], \
        "the seats differ, so the tower (which compares them) makes the room again and the owls appear"
