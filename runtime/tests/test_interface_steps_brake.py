"""Tests of the brake of the step tasks on the page (P5c): the Building's panel shows the runtime's mode (the `steps` of the agents read) with the one control the
page's policy allows (Stop step tasks is a narrowing the page may always do, Resume step tasks needs the group `set-mode`, else a line points to the terminal), sends
exactly one request (`POST /agents/runtime/mode`), shows a refusal, and draws nothing when the read carried no brake. The data module keeps the read's `steps`. No
browser and no model: the view runs under Node with a fake document, as the other interface tests do.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_steps_brake.py
"""
from __future__ import annotations

import pytest

from test_interface_floor import needs_node
from test_interface_live import VIEW_HEAD
from test_interface_plates_meters import run_node

BRAKE = VIEW_HEAD + r"""
import { createBuildingView } from "@JS@/views/building.js";
import { ON as STEPS_ON, OFF as STEPS_OFF, RESUME_NOTE as STEPS_RESUME_NOTE } from "@JS@/views/lobby-steps-brake.js";

const byClass = (root, c) => [...root.walk()].filter((n) => n.cls().includes(c));
const posts = [];
let refuse = false;
const base = globalThis.fetch;
globalThis.fetch = async (url, init) => {
  if (init.method === "POST") {
    posts.push([url.replace(`/api/v1/projects/${P}`, ""), init.body]);
    if (refuse) return { ok: false, status: 409, json: async () => ({ error: "refused", message: "The page's policy does not list set-mode." }) };
  }
  return base(url, init);
};
const allowed = { down: true, up: true };
let refreshed = 0;
const frame = makeFrame();
frame.sceneHost.querySelectorAll = FakeNode.prototype.querySelectorAll;
frame.acquireWorld = () => ({ flyTo: () => Promise.resolve(false), stats: () => ({}), highlight() {}, setCorner() {}, show() {}, refit() {}, setOptions() {} });
const view = createBuildingView(frame, { refresh: async () => { refreshed += 1; }, selectRequest() {} });
const route = router.parse(`#/p/${P}`);
const snap = (steps) => {       // the policy is the project entry's `permissions`, as GET /projects answers it
  const s = JSON.parse(JSON.stringify(snapshot));
  if (steps) s.details[P].steps = steps;
  s.projects[0].permissions = { channel: "page", allowed: ["status", ...(allowed.down ? ["set-mode:down"] : []), ...(allowed.up ? ["set-mode:up"] : [])] };
  return s;
};
const show = (steps, stamp) => view.update({ snapshot: snap(steps), route, now: NOW, reload: stamp });
const section = () => byClass(frame.main, "wb-steps-sec")[0];
const drawn = () => { const s = section(); const b = byClass(s, "wb-steps-btn")[0]; const note = byClass(s, "wb-steps-note")[0];
  return { hidden: s.hidden, head: byClass(s, "wb-steps-head")[0].textContent, line: byClass(s, "wb-steps-line")[0].textContent, button: b.hidden ? null : b.textContent, disabled: b.disabled, note: note.hidden ? null : note.textContent }; };

show(null, 1);                                   // a read that carried no brake (an older service)
await settle();
out.none = section().hidden;

show({ agent: "runtime", mode: "autonomous" }, 2);
await settle();
out.on = drawn();
byClass(section(), "wb-steps-btn")[0].click();
await settle();
out.stopSent = { posts: posts.slice(), refreshed };

show({ agent: "runtime", mode: "stopped" }, 3);
await settle();
out.off = drawn();
byClass(section(), "wb-steps-btn")[0].click();
await settle();
out.resumeSent = posts.slice(1);

allowed.up = false;                              // the policy withholds a widening: no button, a line that points to the terminal
show({ agent: "runtime", mode: "stopped" }, 4);
await settle();
out.offNoResume = drawn();

allowed.up = true; allowed.down = false;         // the stop is a brake, but a page that cannot ask it draws no control for it
show({ agent: "runtime", mode: "autonomous" }, 5);
await settle();
out.onNoStop = drawn();

allowed.down = true;
refuse = true;
show({ agent: "runtime", mode: "autonomous" }, 6);
await settle();
byClass(section(), "wb-steps-btn")[0].click();
await settle();
out.refused = { text: byClass(section(), "wb-form-error")[0].textContent, disabled: byClass(section(), "wb-steps-btn")[0].disabled };
out.words = [STEPS_ON, STEPS_OFF, STEPS_RESUME_NOTE];
view.dispose();
console.log(JSON.stringify(out));
process.exit(0);
"""

DATA = r"""
import { setToken } from "@JS@/token.js";
import { emptySnapshot, refresh } from "@JS@/data.js";

setToken("t".repeat(40));
const P = "0123456789ab";
let steps = { agent: "runtime", mode: "stopped" };
let failAgents = 0;
globalThis.fetch = async (url) => {
  const path = new URL(url, "http://127.0.0.1").pathname.replace("/api/v1", "");
  if (path === "/projects") return { ok: true, status: 200, json: async () => ({ projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }] }) };
  if (path.endsWith("/status")) return { ok: true, status: 200, json: async () => ({ requests: [], pending: [], documents: [], held: [] }) };
  if (path.endsWith("/agents")) {
    if (failAgents) return { ok: false, status: 409, json: async () => ({ error: "busy", message: "busy" }) };
    return { ok: true, status: 200, json: async () => ({ agents: [], ...(steps ? { steps } : {}) }) };
  }
  return { ok: true, status: 200, json: async () => ({}) };
};
const out = {};
const first = await refresh(emptySnapshot(), P);
out.read = first.details[P].steps;
failAgents = 1;
const kept = await refresh(first, P);
out.kept = [kept.details[P].steps, Boolean(kept.details[P].error)];
failAgents = 0;
steps = null;
out.absent = (await refresh(first, P)).details[P].steps;
console.log(JSON.stringify(out));
process.exit(0);
"""


@pytest.fixture(scope="module")
def brake(tmp_path_factory):
    return run_node(tmp_path_factory.mktemp("brake"), BRAKE)


@needs_node
def test_the_panel_draws_nothing_when_the_read_carried_no_brake(brake):
    assert brake["none"] is True


@needs_node
def test_the_runtime_running_shows_its_state_and_one_stop_button_that_sends_one_request_and_reloads(brake):
    on = brake["on"]
    assert on == {"hidden": False, "head": "Step tasks", "line": brake["words"][0], "button": "Stop step tasks", "disabled": False, "note": None}
    assert brake["stopSent"]["posts"] == [["/agents/runtime/mode", '{"mode":"stopped"}']] and brake["stopSent"]["refreshed"] == 1


@needs_node
def test_the_runtime_stopped_says_so_and_offers_resume_which_sends_autonomous(brake):
    off = brake["off"]
    assert off["line"] == brake["words"][1] and off["button"] == "Resume step tasks" and off["note"] is None
    assert brake["resumeSent"] == [["/agents/runtime/mode", '{"mode":"autonomous"}']]


@needs_node
def test_the_policy_withholds_a_resume_with_a_line_that_names_the_terminal_command_and_a_stop_the_page_may_not_ask_has_no_button(brake):
    assert brake["offNoResume"]["button"] is None and brake["offNoResume"]["note"] == brake["words"][2]
    assert "set-mode --agent runtime --mode autonomous" in brake["words"][2]
    assert brake["onNoStop"]["button"] is None and brake["onNoStop"]["note"] is None


@needs_node
def test_a_refusal_is_shown_and_the_button_is_enabled_again(brake):
    assert brake["refused"]["text"] == "The page's policy does not list set-mode." and brake["refused"]["disabled"] is False


@needs_node
def test_the_data_module_keeps_the_brake_of_the_agents_read_and_the_last_one_when_a_read_is_refused(tmp_path):
    got = run_node(tmp_path, DATA)
    assert got["read"] == {"agent": "runtime", "mode": "stopped"}
    assert got["kept"][0] == {"agent": "runtime", "mode": "stopped"} and got["kept"][1] is True
    assert got["absent"] is None
