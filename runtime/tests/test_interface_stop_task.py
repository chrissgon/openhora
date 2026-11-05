"""R18, the page: a running task has Stop task, which asks to be confirmed (what the run used is spent, nothing it made is kept) before it sends
`POST /projects/{p}/tasks/{id}/stop`; the cancel dialog of a request with something running says the same. Offline, under Node with the fake document of test_interface_floor.py and a fake client.

Run: uv run --offline --with pytest python3 -m pytest runtime/tests/test_interface_stop_task.py -q
"""
from __future__ import annotations

from test_interface_floor import needs_node, run_node  # noqa: F401  (FAKE_DOM is written by run_node)

STOP = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createTaskActions } from "@JS@/floor/task-actions.js";
import { actionsFor } from "@JS@/floor/tasks-model.js";
import { cancelCount } from "@JS@/floor/cards.js";
import { cancelCount as lobbyCount } from "@JS@/views/lobby-model.js";
import { can as pageMay } from "@JS@/permissions.js";
import { stopTask } from "@JS@/api.js";

const calls = [];
const api = { stopTask: async (...args) => { calls.push(args.slice(0, 2)); return {}; } };
let redraws = 0;
const actions = createTaskActions({ project: "p", api, refresh() {}, redraw() { redraws += 1; }, can: (op) => pageMay({ id: "p", permissions: { allowed: ["status", "cancel", "stop-task"] } }, op) });
const running = { id: 9, state: "running", title: "R" };
const buttons = () => actions.nodes(running, { pending: [], links: {} }).filter((n) => n.tagName === "BUTTON");
const out = {};
out.kinds = actionsFor(running, []).map((a) => a.kind);
out.first = buttons().map((b) => b.textContent);
buttons()[0].click();
await settle();
out.afterFirst = { sent: calls.length, labels: buttons().map((b) => b.textContent),
  effect: actions.nodes(running, { pending: [], links: {} }).filter((n) => n.attrs && /wb-task-effect/.test(n.attrs.class || "")).map((n) => n.textContent) };
buttons().find((b) => /Keep/.test(b.textContent)).click();
out.kept = { sent: calls.length, labels: buttons().map((b) => b.textContent) };
buttons()[0].click();
buttons().find((b) => /Yes/.test(b.textContent)).click();
await settle();
out.sent = calls;
out.count = [cancelCount([{ state: "running" }, { state: "planned" }]), cancelCount([{ state: "waiting" }]), cancelCount([], { run_id: 1 }),
  lobbyCount({ tasks: [{ state: "running" }] }), lobbyCount({ tasks: [], routing: { run_id: 2 } }), lobbyCount({ tasks: [{ state: "done" }] })];
let url = null;
globalThis.fetch = async (u, init) => { url = [String(u), init && init.method]; return { ok: true, status: 200, json: async () => ({}) }; };
const { setToken } = await import("@JS@/token.js");
setToken("t".repeat(40));
await stopTask("0123456789ab", 7);
out.url = url;
console.log(JSON.stringify(out));
process.exit(0);
"""

NOTE = "the run is stopped, what it has used so far is spent, and nothing it made is kept."


@needs_node
def test_a_running_task_has_stop_task_that_asks_before_it_sends_and_a_brake_the_policy_does_not_withhold(tmp_path):
    got = run_node(tmp_path, STOP)
    assert got["kinds"] == ["stop"] and got["first"] == ["Stop task"]
    assert got["afterFirst"]["sent"] == 0, "the first click asks, it sends nothing"
    assert got["afterFirst"]["labels"] == ["Yes, stop task", "Keep it running"]
    assert got["afterFirst"]["effect"] == ["Stop this task? What it has used so far is spent, and nothing it made is kept. Retry resumes it."]
    assert got["kept"] == {"sent": 0, "labels": ["Stop task"]}, "Keep it running puts the question away"
    assert got["sent"] == [["p", 9]], "the second click sends one stop"


@needs_node
def test_the_cancel_dialogs_say_what_a_running_run_costs_and_only_then_and_the_client_posts_to_the_stop_route(tmp_path):
    got = run_node(tmp_path, STOP)
    assert got["count"][0].endswith(NOTE) and got["count"][0].startswith("2 tasks, 1 started")
    assert got["count"][1] == "1 task, 1 started", "a task that waits for the person runs nothing"
    assert got["count"][2].startswith("No task has been created yet.") and got["count"][2].endswith(NOTE), "the router's run is stopped too"
    assert got["count"][3].endswith(NOTE) and got["count"][4].endswith(NOTE) and got["count"][5] == "1 task, 1 started"
    assert got["url"][0].endswith("/projects/0123456789ab/tasks/7/stop") and got["url"][1] == "POST"
