"""The page's part of the routines (P6b): the client's calls, the Routines section of the Building (the list, the approval of the exact content with its whole hash,
the consent's warning, the brakes, the policy), and "Schedule it" under "Save this plan as a workflow". Run with Node over the real modules, a fake document and a
stand-in client. No browser, no service, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_routines.py
"""
from __future__ import annotations

from test_interface_lobby import needs_node, run_node  # noqa: F401  (the Node runner and the fake document the Lobby's tests use)

API = r"""
import { setToken } from "@JS@/token.js";

const seen = [];
globalThis.fetch = async (url, init) => { seen.push([init.method, url, init.body ? JSON.parse(init.body) : null]); return { ok: true, status: 200, json: async () => ({}) }; };
setToken("t".repeat(40));
const api = await import("@JS@/api.js");
await api.routines("abc");
await api.routines("abc", { id: 4 });
await api.routineCreate("abc", { name: "morning", flow: "demo", every: "day", at: "08:00" });
await api.routineChange("abc", 4, { consent: true, warning_sha256: "w" });
await api.routineApprove("abc", 4, "h".repeat(64));
await api.routinePause("abc", 4);
await api.routineResume("abc", 4);
await api.routineCancel("abc", 4);
console.log(JSON.stringify(seen));
"""


@needs_node
def test_the_client_has_one_call_for_each_routine_verb(tmp_path):
    got = run_node(tmp_path, API)
    base = "/api/v1/projects/abc/routines"
    assert got[0] == ["GET", base, None] and got[1] == ["GET", base + "?routine_id=4", None]
    assert got[2] == ["POST", base, {"name": "morning", "flow": "demo", "every": "day", "at": "08:00"}]
    assert got[3] == ["POST", base + "/4/change", {"consent": True, "warning_sha256": "w"}]
    assert got[4] == ["POST", base + "/4/approve", {"sha256": "h" * 64}]
    assert [g[1] for g in got[5:]] == [base + "/4/pause", base + "/4/resume", base + "/4/cancel"] and all(g[0] == "POST" for g in got[5:])


SECTION = r"""
import { byClass, click, textOf } from "@FAKE@";
import { createRoutines, scheduleWords, stateWords, fireWords } from "@JS@/views/lobby-routines.js";
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0)); };
const tag = (root, name) => [...root.walk()].filter((n) => n.tagName === name.toUpperCase());
const labelled = (root, text) => tag(root, "button").find((b) => textOf(b) === text);

const HASH = "ab".repeat(32);
const WARNING = "Each run of this agent on its fixed model...";
let list = [
  { id: 1, name: "morning", flow: "demo", schedule: { every: "day", at: "08:00" }, state: "draft", current: false, model_word: "m", last_fire: null },
  { id: 2, name: "weekly", flow: "report", schedule: { every: "week", weekday: 1, at: "09:30" }, state: "active", current: true, model_word: "m", last_fire: { slot: "2026-10-12T09:30", status: "created" } },
  { id: 3, name: "changed", flow: "report", schedule: { every: "minutes", minutes: 30 }, state: "active", current: false, model_word: "m", last_fire: { slot: "x", status: "asked", reason: "its content changed" } },
  { id: 4, name: "held", flow: "report", schedule: { every: "day", at: "01:00" }, state: "paused", current: true, model_word: "m", last_fire: null }];
const CONTENT = { schedule: { every: "day", at: "08:00", window_seconds: 86400 }, workflow: { name: "demo", template_sha256: "t".repeat(64), params: { topic: "dental" } },
  skills: { "demo-asks": "0.1", "demo-writes": "0.1" }, image: "sha256:" + "1".repeat(64), model: "fm", consent: { given: false }, providers: [] };
let needed = true;
const calls = [];
const api = {
  routines: async (p, o) => {
    if (o && o.id) return { ...list.find((r) => r.id === o.id), content: CONTENT, approve: { sha256: HASH, consent_needed: needed, warning: WARNING, warning_sha256: "w".repeat(64), command: "routine-approve --id 1 --sha256 " + HASH } };
    return { routines: list };
  },
  flows: async () => ({ flows: [{ flow: "demo", title: "Demo" }, { flow: "survey", title: "Survey", params: [{ name: "f", type: "file" }] }, { flow: "bad", error: "x" }] }),
  routineApprove: async (p, id, sha) => { calls.push(["approve", id, sha]); },
  routineChange: async (p, id, f) => { calls.push(["change", id, f]); needed = false; return { id }; },
  routinePause: async (p, id) => { calls.push(["pause", id]); },
  routineResume: async (p, id) => { calls.push(["resume", id]); },
  routineCancel: async (p, id) => { calls.push(["cancel", id]); },
  routineCreate: async (p, f) => { calls.push(["create", f]); },
};
let policy = null;
const section = createRoutines({ api, project: "p", entry: () => policy, refresh: async () => {} });
const out = {};
out.words = [scheduleWords({ every: "day", at: "08:00" }), scheduleWords({ every: "week", weekday: 3, at: "10:00" }), scheduleWords({ every: "minutes", minutes: 45 }),
  stateWords(list[0]), stateWords(list[2]), stateWords(list[3]), fireWords(null), fireWords(list[2].last_fire)];
out.hiddenAtStart = section.el.hidden;
section.update({}, true);
await settle();
const items = byClass(section.el, "wb-rt-item");
out.items = items.map((i) => textOf(i));
out.buttons = items.map((i) => tag(i, "button").map(textOf));
out.shown = [section.el.hidden, byClass(section.el, "wb-rt-new").length];
await (async () => { click(labelled(items[0], "Review and approve")); await settle(); })();
const preview = byClass(section.el, "wb-rt-preview")[0];
out.content = tag(preview, "dd").map(textOf);
out.preview = { hidden: preview.hidden, hash: textOf(byClass(preview, "wb-hash")[0]), warning: textOf(tag(preview, "p").find((p) => p.attrs["data-key"] === "warning")), buttons: tag(preview, "button").map(textOf) };
click(labelled(preview, "Give this routine's consent")); await settle();
out.afterConsent = { calls: calls.slice(), warning: tag(byClass(section.el, "wb-rt-preview")[0], "p").some((p) => p.attrs["data-key"] === "warning") };
click(labelled(byClass(section.el, "wb-rt-preview")[0], "Approve this exact content")); await settle();
out.afterApprove = { calls: calls.slice(1), hidden: byClass(section.el, "wb-rt-preview")[0].hidden };
calls.length = 0;
click(labelled(byClass(section.el, "wb-rt-item")[1], "Pause")); await settle();
click(labelled(byClass(section.el, "wb-rt-item")[3], "Resume")); await settle();
click(labelled(byClass(section.el, "wb-rt-item")[2], "Cancel")); await settle();
out.brakes = calls.slice();
// the policy: the brakes stay, the rest is not drawn
policy = { permissions: { allowed: ["routines"] } };
section.update({}, true);
await settle();
const held = byClass(section.el, "wb-rt-item");
out.withheld = { held: held.map((i) => tag(i, "button").map(textOf)), form: byClass(section.el, "wb-rt-new")[0].hidden };
out.notShown = (() => { section.update(null, false); return section.el.hidden; })();
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_routines_section_lists_previews_the_whole_hash_with_the_consent_warning_and_sends_each_verb_once(tmp_path):
    got = run_node(tmp_path, SECTION)
    assert got["words"] == ["every day at 08:00", "every Wednesday at 10:00", "every 45 minutes", "draft: not approved",
                            "active, but its content changed since you approved it", "paused", "not fired yet", "x: asked (its content changed)"]
    assert got["hiddenAtStart"] is True and got["shown"] == [False, 1]
    assert len(got["items"]) == 4 and "morning" in got["items"][0] and "every Monday at 09:30" in got["items"][1] and "2026-10-12T09:30: created" in got["items"][1]
    assert got["buttons"] == [["Review and approve", "Cancel"], ["Pause", "Cancel"], ["Pause", "Cancel"], ["Resume", "Cancel"]]
    assert got["preview"]["hidden"] is False and got["preview"]["hash"] == "ab" * 32, "the hash is shown whole"
    assert got["content"] == ["every day at 08:00, a missed slot is made up for 86400 s", "demo (template " + "t" * 64 + ")", "topic=dental",
                              "demo-asks 0.1, demo-writes 0.1", "sha256:" + "1" * 64, "fm", "not given", "none"], "what the hash covers is shown beside it"
    assert got["preview"]["warning"].startswith("Each run of this agent") and "Give this routine's consent" in got["preview"]["buttons"]
    assert got["afterConsent"]["calls"] == [["change", 1, {"consent": True, "warning_sha256": "w" * 64}]] and got["afterConsent"]["warning"] is False
    assert got["afterApprove"]["calls"] == [["approve", 1, "ab" * 32]] and got["afterApprove"]["hidden"] is True
    assert got["brakes"] == [["pause", 2], ["resume", 4], ["cancel", 3]]
    assert got["withheld"]["held"] == [["Review and approve", "Cancel"], ["Pause", "Cancel"], ["Pause", "Cancel"], ["Cancel"]], \
        "a policy that withholds routine-resume leaves no Resume; the brakes stay"
    assert got["withheld"]["form"] is True and got["notShown"] is True


SCHEDULE = r"""
import { byClass, click, textOf } from "@FAKE@";
import { createSaveFlow } from "@JS@/cards/save-flow.js";
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0)); };
const tag = (root, name) => [...root.walk()].filter((n) => n.tagName === name.toUpperCase());
const approved = { id: 31, kind: "plan", status: "resolved", resolution: "approved", title: "Weekly report" };
const calls = [];
let refuse = false;
const api = { flowSave: async (p, b) => ({ path: "docs/workbench/flows/weekly-report.json", split: false }),
  routineCreate: async (p, f) => { calls.push(f); if (refuse) throw Object.assign(new Error("a routine on `auto` names the providers it may use"), { name: "ApiError", status: 409 }); } };
const out = {};
const el = createSaveFlow({ api, project: "p", item: approved });
const box = byClass(el, "wb-save-flow-scheduler")[0];
out.beforeSave = box.hidden;
click(tag(el, "button")[0]); await settle();
out.afterSave = box.hidden;
const inputs = tag(box, "input");
tag(box, "select")[0].value = "day";   // the fake document does not choose the first option
inputs[0].value = "07:15";
click(byClass(box, "wb-save-flow-schedule")[0]); await settle();
out.created = { calls: calls.slice(), said: textOf(tag(box, "p")[0]) };
refuse = true;
click(byClass(box, "wb-save-flow-schedule")[0]); await settle();
out.refused = textOf(byClass(box, "wb-card-error")[0]);
const without = createSaveFlow({ api, project: "p", item: approved, can: (op) => op !== "routine-create" });
out.noPolicy = byClass(without, "wb-save-flow-scheduler").length;
const plain = createSaveFlow({ api: { flowSave: api.flowSave }, project: "p", item: approved });
out.noClient = byClass(plain, "wb-save-flow-scheduler").length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_saved_plan_can_be_scheduled_on_the_same_screen_as_a_draft_routine_and_the_policy_and_the_service_are_obeyed(tmp_path):
    got = run_node(tmp_path, SCHEDULE)
    assert got["beforeSave"] is True and got["afterSave"] is False
    assert got["created"]["calls"] == [{"name": "weekly-report", "flow": "weekly-report", "every": "day", "at": "07:15"}]
    assert "The routine weekly-report is a draft" in got["created"]["said"] and "fires nothing before" in got["created"]["said"]
    assert "names the providers it may use" in got["refused"]
    assert got["noPolicy"] == 0 and got["noClient"] == 0
