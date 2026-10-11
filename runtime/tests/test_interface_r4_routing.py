"""R4-L1 (A-51): a request the router works on shows its run on the page. The runtime says it (`routing` on each request of `status`, `routing_request` in the
project list: runtime/tests/test_routing_read.py); the page draws it: the request line says `Routing...` with no `Route it`, no flow select and no `Cancel request`,
the tracking bar and the Building's "Running now" name the run ("Planning agent · routing request #2 · for 3 min"), the composer's run line names it, and the planning
agent's window and owl work. No browser and no model: the modules run under Node with a fake document, as the other interface tests do.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_routing.py
"""
from __future__ import annotations

from test_interface_floor import INTERFACE, needs_node
from test_interface_plates_meters import run_node

JS = INTERFACE / "js"

MODEL = r"""
import * as model from "@JS@/model.js";
import * as fm from "@JS@/floor-model.js";

const NOW = new Date("2026-10-10T12:00:00Z");
const P = "0123456789ab";
const run = { run_id: 3, skill: "core-orchestrator", started_at: "2026-10-10T11:57:00Z" };
const request = (id, state, extra = {}) => ({ id, title: `Request ${id}`, state, tasks: [], routing: null, ...extra });
const status = (requests) => ({ pending: [], requests, documents: [], held: [] });
const snapshot = (requests, running_task = null) => ({
  projects: [{ id: P, name: "northwind-shop", config: { accepted: true }, running_task, routing_request: null }], loaded: true,
  details: { [P]: { agents: [{ name: "planning", enabled: true }, { name: "brand", enabled: true }], status: status(requests) } }, tasks: {},
});
const out = {};

const routed = snapshot([request(1, "requested"), request(2, "requested", { routing: run })]);
const t = model.tracking(routed, P, NOW);
out.request = [t.request.id, t.request.title];
out.now = t.now;
out.others = t.requests.map((r) => [r.id, r.running]);
out.picked = model.pickRequest(routed.details[P].status).id;      // the request with a run is the one the bar follows, not the newest
out.words = [model.routingWords(routed.details[P].status.requests[1], NOW), model.routingWords(routed.details[P].status.requests[1]), model.routingRequest(routed.details[P].status).id,
  model.routingRequest(status([request(1, "requested")])), model.routingRequest(null)];
out.rows = fm.requestRows(routed.details[P].status, P).map((r) => [r.id, r.steps]);
out.cancellable = fm.requestRows(routed.details[P].status, P).map((r) => [r.id, r.cancellable]);

// no run: the bar says nothing is running, as before
out.quiet = model.tracking(snapshot([request(1, "requested")]), P, NOW).now;
// a task that runs wins over a routing flag (it cannot both happen: the runtime holds one run per project)
const both = model.tracking(snapshot([request(2, "ready", { routing: run, tasks: [{ id: 5, key: "k", title: "k", skill: "s", state: "running", agent: "brand" }] })]), P, NOW);
out.both = both.now.sub.startsWith("task #5");

// the Building's facts
const f = fm.facts({ id: P, running_task: null }, routed.details[P].status, true, false, NOW);
out.facts = f.running;
out.factsNoNow = fm.facts({ id: P, running_task: null }, routed.details[P].status, true, false).running.label;
out.factsQuiet = fm.facts({ id: P, running_task: null }, status([request(1, "requested")]), true, false).running;
out.factsTask = fm.facts({ id: P, running_task: 5 }, status([request(2, "ready", { tasks: [{ id: 5, key: "k", title: "build", state: "running", agent: "brand" }] })]), true, false).running;

// the planning agent works, so its window and its owl are lit; the other agent rests
const rows = fm.building(routed, P, NOW).rows.map((r) => [r.name, r.state, r.window.lit === undefined ? JSON.stringify(r.window) : r.window.lit]);
out.rows3 = rows;
out.state = [fm.stateOf({ name: "planning" }, routed.details[P].status), fm.stateOf({ name: "planning" }, status([request(1, "requested")]))];
const city = model.buildingOf(routed.projects[0], routed.details[P]);
out.city = city.floors.map((fl) => [fl.agent, JSON.stringify(fl.window)]);
const quietCity = model.buildingOf(routed.projects[0], { ...routed.details[P], status: status([request(1, "requested")]) });
out.cityQuiet = quietCity.floors.map((fl) => [fl.agent, JSON.stringify(fl.window)]);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_model_names_a_router_run_for_the_bar_the_building_and_the_planning_agent_s_window(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["request"] == [2, "Request 2"] and got["picked"] == 2, "the bar follows the request with a run, though request 1 was open first"
    assert got["now"]["running"] is True and got["now"]["state"] == "Running" and got["now"]["title"] == "Planning agent · routing request #2", \
        "A-51: the bar names the run instead of 'Nothing is running'"
    assert got["now"]["where"] == "Now on floor 0 · lobby" and got["now"]["sub"] == "for 3 min" and got["now"]["link"].endswith("/lobby/conversation/request/2")
    assert got["others"] == [[2, True], [1, False]], "the request list marks the one with a run as running"
    assert got["words"] == ["Planning agent · routing request #2 · for 3 min", "Planning agent · routing request #2", 2, None, None]
    assert got["rows"] == [[1, "0 of 0 steps done"], [2, "0 of 0 steps done · being routed"]]
    assert got["cancellable"] == [[1, True], [2, False]], "the Building's request row offers no Cancel request while a run holds the request"
    assert got["quiet"] is None, "without a run the bar says 'Nothing is running' as before (the model gives no card)"
    assert got["both"] is True, "a task that runs is shown before a routing flag"
    assert got["facts"] == {"id": 2, "title": "Request 2", "link": got["facts"]["link"], "label": "Planning agent · routing request #2 · for 3 min"} \
        and got["facts"]["link"].endswith("/lobby/conversation/request/2"), "the Building's Running now names the run and links to the request line"
    assert got["factsNoNow"] == "Planning agent · routing request #2", "no clock given: no duration is invented"
    assert got["factsQuiet"] is None and got["factsTask"]["id"] == 5 and "label" not in got["factsTask"], "no run: nothing is running; a task keeps its own line"
    assert got["state"] == ["working", "idle"], "R-21: the planning agent works while its router runs"
    planning = [r for r in got["rows3"] if r[0] == "planning"][0]
    brand = [r for r in got["rows3"] if r[0] == "brand"][0]
    assert planning[1] == "working" and brand[1] == "idle"
    assert dict(got["city"])["planning"] != dict(got["cityQuiet"])["planning"], "the City's window of the Lobby is lit by the run"
    assert dict(got["city"])["brand"] == dict(got["cityQuiet"])["brand"]


BLOCK = r"""
import { FakeNode, find, all, text } from "@FAKE@";
import { createBlock } from "@JS@/views/lobby-request.js";

const NOW = new Date("2026-10-10T12:00:00Z");
const flows = [{ flow: "design", title: "Design" }, { flow: "brand", title: "Brand" }];
const run = { run_id: 3, skill: "core-orchestrator", started_at: "2026-10-10T11:57:00Z" };
const routed = [];
const make = (extra = {}, row = {}) => createBlock({ api: {}, project: "p1", request: { id: 2, title: "Spring page", state: "requested", tasks: [], routing: null, ...row }, body: { pending: [] }, open: 0, now: NOW,
  onChanged: async () => {}, onCancel() {}, onRoute: (request, flow) => routed.push([request.id, flow]), routing: false, flows, ...extra });
const view = (block) => {
  const route = find(block.el, "button.wb-route-button");
  return { route: route ? [route.textContent, "disabled" in route.attrs, route.attrs["aria-label"], route.attrs.title || null] : null,
    select: find(block.el, "select.wb-route-flow") !== null, cancel: all(block.el, "button").filter((b) => /^Cancel request/.test(b.textContent)).length };
};
const out = {};
out.idle = view(make());
out.served = view(make({ routing: true }, { routing: run }));      // the service says a run holds the request (a reloaded page)
out.clicked = view(make({ routing: true }));                         // this page started the route and has not seen the service's read yet
out.final = view(make({}, { state: "done" }));
const served = make({ routing: true }, { routing: run });
find(served.el, "button.wb-route-button").click();
out.clicks = routed.length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_request_line_a_run_holds_says_routing_with_no_route_it_no_flow_select_and_no_cancel(tmp_path):
    got = run_node(tmp_path, BLOCK)
    assert got["idle"]["route"] == ["Route it", False, "Route request 2", None] and got["idle"]["select"] is True and got["idle"]["cancel"] == 1, "a request nobody routes keeps its line"
    for key in ("served", "clicked"):
        assert got[key]["route"][0] == "Routing..." and got[key]["route"][1] is True and got[key]["route"][2] == "Request 2 is being routed", key
        assert got[key]["select"] is False and got[key]["cancel"] == 0, f"{key}: no flow select, and no Cancel request (the store refuses it while a run holds the request)"
    assert got["served"]["route"][3] == "Planning agent · routing request #2 · for 3 min", "the button's tooltip names the run and how long it has lasted"
    assert got["clicked"]["route"][3] is None
    assert got["clicks"] == 0, "a second click is not sent"
    assert got["final"]["route"] is None


def test_the_lobby_reads_the_service_s_routing_for_its_blocks_its_owl_and_its_composer():
    thread = (JS / "views" / "lobby-thread.js").read_text(encoding="utf-8")
    assert "Boolean(request.routing)" in thread and "routing: routingNow" in thread, "a block is drawn as routing when the service says so, and drawn again when that changes"
    lobby = (JS / "views" / "lobby.js").read_text(encoding="utf-8")
    assert "model.routingRequest(status)" in lobby and lobby.count("model.routingRequest(status)") == 2, "the owl works and the composer names the run"
    assert "model.routingWords(routed, last.now)" in lobby
    building = (JS / "views" / "building.js").read_text(encoding="utf-8")
    assert "f.running.label ||" in building and "fm.building(snapshot, projectId, last.now)" in building, "the Building's Running now takes its words from the model"


TRACK = r"""
import { find } from "@FAKE@";
import * as model from "@JS@/model.js";
import { createTrack } from "@JS@/frame/track.js";

const NOW = new Date("2026-10-10T12:00:00Z");
const P = "0123456789ab";
const run = { run_id: 3, skill: "core-orchestrator", started_at: "2026-10-10T11:57:00Z" };
const snapshot = (routing) => ({ projects: [{ id: P, name: "northwind-shop", config: { accepted: true }, running_task: null }], loaded: true, tasks: {},
  details: { [P]: { agents: [{ name: "planning" }], status: { pending: [], requests: [{ id: 2, title: "Spring page", state: "requested", tasks: [], routing }] } } } });
const out = {};
const track = createTrack({ onOpenSteps() {}, onSelectRequest() {} });
const text = (n) => (n ? n.textContent : null);
track.set(model.tracking(snapshot(run), P, NOW), "ready");
out.routed = [text(find(track.el, ".wb-now-where")), text(find(track.el, ".wb-now-title")), text(find(track.el, ".wb-now-sub")), text(find(track.el, ".wb-chip-small")), text(find(track.el, ".wb-track-now-text"))];
track.set(model.tracking(snapshot(null), P, NOW), "ready");
out.quiet = [text(find(track.el, ".wb-now-where")), text(find(track.el, ".wb-now-sub"))];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_tracking_bar_names_the_router_s_run_and_says_nothing_is_running_when_there_is_none(tmp_path):
    got = run_node(tmp_path, TRACK)
    assert got["routed"][:4] == ["Now on floor 0 · lobby", "Planning agent · routing request #2", "for 3 min", "Running"], "A-51: the bar names the run"
    assert "Planning agent · routing request #2" in got["routed"][4], "the phone's line names it too"
    assert got["quiet"] == ["Nothing is running", "request #2 · requested"]
