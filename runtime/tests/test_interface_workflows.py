"""Tests of the page's part of the workflows (P6a): the client's new calls (the parameters of a route, the hand-over for a request, saving a
workflow), the control "Save this plan as a workflow" under an approved plan, the parameters of a workflow in the New request form, and the
order of a request that names a file (hand it over, then route with its name). Run with Node over the real modules, a fake document and a
stand-in for the client or for `fetch`. No browser, no service, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_workflows.py
"""
from __future__ import annotations

from test_interface_lobby import needs_node, run_node  # noqa: F401  (the Node runner and the fake document the Lobby's tests use)

API = r"""
import { setToken } from "@JS@/token.js";

const seen = [];
globalThis.fetch = async (url, init) => { seen.push([init.method, url, init.body ? JSON.parse(init.body) : null]); return { ok: true, status: 200, json: async () => ({}) }; };
setToken("t".repeat(40));
const api = await import("@JS@/api.js");
await api.route("abc", 5, { flow: "survey", params: ["topic=dental", "survey=s.csv"] });
await api.route("abc", 5, { flow: "demo" });
await api.route("abc", 5, {});
await api.stageFile("abc", 5, "s.csv", "QQ==");
await api.flowSave("abc", { name: "my-flow", pendingId: 3, split: true });
await api.flowCheck("abc", "my-flow");
console.log(JSON.stringify(seen));
"""


@needs_node
def test_the_client_sends_the_parameters_of_a_route_the_file_for_a_request_and_the_save_of_a_workflow(tmp_path):
    got = run_node(tmp_path, API)
    base = "/api/v1/projects/abc"
    assert got[0] == ["POST", f"{base}/requests/5/route", {"flow": "survey", "params": ["topic=dental", "survey=s.csv"]}]
    assert got[1] == ["POST", f"{base}/requests/5/route", {"flow": "demo"}], "no parameter: the body is what it always was"
    assert got[2] == ["POST", f"{base}/requests/5/route", {}]
    assert got[3] == ["POST", f"{base}/requests/5/files", {"name": "s.csv", "content_base64": "QQ=="}]
    assert got[4] == ["POST", f"{base}/flows", {"name": "my-flow", "pending_id": 3, "split": True}]
    assert got[5][:2] == ["GET", f"{base}/flows/my-flow/check"]


SAVE = r"""
import { byClass, click, textOf } from "@FAKE@";
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0)); };
const tag = (root, name) => [...root.walk()].filter((n) => n.tagName === name.toUpperCase());
import { createSaveFlow, suggestName } from "@JS@/cards/save-flow.js";

const approved = { id: 31, kind: "plan", status: "resolved", resolution: "approved", title: "Study the dental market" };
const out = {};
out.names = [suggestName("Study the dental market"), suggestName("  Ünïcode -- and symbols!! "), suggestName(""), suggestName("x".repeat(80)).length];
const calls = [];
let answer = async (project, body) => { calls.push([project, body]); return { path: "docs/workbench/flows/study.json", split: Boolean(body.split) }; };
const make = (item, can = () => true) => createSaveFlow({ api: { flowSave: (p, b) => answer(p, b) }, project: "p", item, can });
out.none = [make({ ...approved, resolution: "rejected" }), make({ ...approved, kind: "effect" }), make(approved, (op) => op !== "flow-save"), make({ ...approved, status: "open", resolution: null })].map((x) => x === null);
const el = make(approved);
const input = tag(el, "input")[0];
const buttons = tag(el, "button");
out.start = { value: input.value, split: buttons[1].hidden, summary: textOf(tag(el, "summary")[0]) };
input.value = "Bad Name";
click(buttons[0]); await settle();
out.badName = { calls: calls.length, error: textOf(byClass(el, "wb-card-error")[0]), invalid: input.attrs["aria-invalid"] };
input.value = "dental-study";
click(buttons[0]); await settle();
out.saved = { calls: calls.slice(), done: textOf(tag(el, "p")[0]), splitShown: !buttons[1].hidden };
calls.length = 0;
answer = async (p, b) => { calls.push([p, b]); const e = Object.assign(new Error("the flow check refuses this workflow: task market requires the web; the code can split it: research with the web"), { name: "ApiError", status: 409, word: "refused" }); throw e; };
click(buttons[0]); await settle();
out.refused = { text: textOf(byClass(el, "wb-card-error")[0]), splitShown: !buttons[1].hidden, calls: calls.length };
answer = async (p, b) => { calls.push([p, b]); return { path: "docs/workbench/flows/dental-study.json", split: true }; };
click(buttons[1]); await settle();
out.split = { body: calls[calls.length - 1][1], done: textOf(tag(el, "p")[0]), splitShown: !buttons[1].hidden };
answer = async () => { throw Object.assign(new Error("exists: use replace"), { name: "ApiError", status: 409, word: "refused" }); };
click(buttons[0]); await settle();
out.exists = { text: textOf(byClass(el, "wb-card-error")[0]), splitShown: !buttons[1].hidden };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_control_to_save_an_approved_plan_sends_the_name_asks_for_the_split_only_when_the_service_offers_it_and_is_left_out_otherwise(tmp_path):
    got = run_node(tmp_path, SAVE)
    assert got["names"] == ["study-the-dental-market", "unicode-and-symbols", "workflow", 40]
    assert got["none"] == [True, True, True, True], "a rejected plan, another kind, a policy that withholds flow-save, an open plan: no control"
    assert got["start"] == {"value": "study-the-dental-market", "split": True, "summary": "Save this plan as a workflow"}
    assert got["badName"]["calls"] == 0 and "lowercase words joined by hyphens" in got["badName"]["error"] and got["badName"]["invalid"] == "true"
    assert got["saved"]["calls"] == [["p", {"name": "dental-study", "pendingId": 31, "split": None}]] or got["saved"]["calls"][0][1]["name"] == "dental-study"
    assert "Saved as docs/workbench/flows/study.json" in got["saved"]["done"] and got["saved"]["splitShown"] is False
    assert "the code can split it" in got["refused"]["text"] and got["refused"]["splitShown"] is True and got["refused"]["calls"] == 1
    assert got["split"]["body"]["split"] is True and "with the split made by code" in got["split"]["done"] and got["split"]["splitShown"] is False
    assert "exists" in got["exists"]["text"] and got["exists"]["splitShown"] is False, "a refusal that offers no split shows no second button"


FORM = r"""
import { click } from "@FAKE@";
import { createParams } from "@JS@/views/lobby-params.js";
import { createRequest, routeRequest } from "@JS@/views/lobby-actions.js";

const survey = { flow: "survey", params: [{ name: "topic", description: "the market", type: "text", required: false }, { name: "survey", description: "the export", type: "file", required: true }] };
const params = createParams();
const out = {};
out.hiddenAtStart = params.el.hidden;
params.show(survey);
const inputs = [...params.el.walk()].filter((n) => n.tagName === "INPUT");
out.shown = { hidden: params.el.hidden, inputs: inputs.length, types: inputs.map((n) => n.attrs.type) };
out.empty = params.problem();
const file = { name: "survey.csv", size: 10, arrayBuffer: async () => new Uint8Array([65, 66]).buffer };
inputs[1].files = [file];
out.filled = [params.problem(), params.list(), params.files().map((f) => [f.param, f.file.name])];
inputs[0].value = "dental clinics";
out.list = params.list();
inputs[1].files = [{ name: "bad name.csv", size: 10 }];
out.refusedName = params.problem();
params.show({ flow: "plain", params: [] });
out.plainHidden = params.el.hidden;

const log = [];
const api = {
  request: async (p, text, o) => { log.push(["request", text]); return { request: 7 }; },
  stageFile: async (p, id, name, b64) => { log.push(["stage", id, name, b64]); },
  route: async (p, id, o) => { log.push(["route", id, o.flow, o.params]); return { job: "j" }; },
};
const made = await createRequest(api, "p", { text: "go", flow: "survey", params: ["topic=dental"], files: [{ param: "survey", file }] });
out.created = { log: log.slice(), params: made.params, started: made.started };
log.length = 0;
const failing = { ...api, stageFile: async () => { throw Object.assign(new Error("a credential"), { name: "ApiError", status: 409, word: "refused" }); } };
const refused = await createRequest(failing, "p", { text: "go", flow: "survey", params: [], files: [{ param: "survey", file }] });
out.refused = { log: log.slice(), error: refused.error && refused.error.message, request: refused.request };
log.length = 0;
await createRequest(api, "p", { text: "go", flow: "demo" });
out.plain = log.slice();
log.length = 0;
await createRequest(api, "p", { text: "go", flow: "" });
out.auto = log.slice();
log.length = 0;
await routeRequest(api, "p", 7, "survey", { params: ["survey=survey.csv"] });
out.again = log.slice();
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_workflow_with_parameters_draws_one_field_each_and_a_file_is_handed_over_for_the_request_before_it_is_routed_with_its_name(tmp_path):
    got = run_node(tmp_path, FORM)
    assert got["hiddenAtStart"] is True
    assert got["shown"] == {"hidden": False, "inputs": 2, "types": ["text", "file"]}
    assert got["empty"] == "survey: choose a file."
    assert got["filled"] == ["", [], [["survey", "survey.csv"]]]
    assert got["list"] == ["topic=dental clinics"]
    assert got["refusedName"].startswith("survey: The file name may hold letters")
    assert got["plainHidden"] is True
    assert got["created"]["log"] == [["request", "go"], ["stage", 7, "survey.csv", "QUI="], ["route", 7, "survey", ["topic=dental", "survey=survey.csv"]]]
    assert got["created"]["params"] == ["topic=dental", "survey=survey.csv"]
    assert got["refused"]["log"] == [["request", "go"]] and got["refused"]["error"] == "a credential" and got["refused"]["request"] == 7, "no route after a hand-over that was refused"
    assert got["plain"] == [["request", "go"], ["route", 7, "demo", None]] or got["plain"][-1][:3] == ["route", 7, "demo"]
    assert got["auto"][-1][2] is None
    assert got["again"] == [["route", 7, "survey", ["survey=survey.csv"]]]
