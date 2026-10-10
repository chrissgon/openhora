"""Tests of WP-9.15b: the terminal-command component (A-18), Stop agent and Supervise (A-17), the not-accepted state that keeps the
last data read (A-16), the held reasons (A-10), the chips (A-12) and the meters' words (A-20). No browser and no model: the modules
run under Node with a fake document, a fake client and a fake clock, so what each part shows and what each button sends is checked.
The served page was looked at in a browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_plates_meters.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st
from test_interface_floor import FAKE_DOM as FLOOR_DOM
from test_interface_live import CLOCK
from test_interface_scene import FAKE_DOM as SCENE_DOM
from interface_css import interface_css

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the modules are tested only by their text")
P = "0123456789ab"
ACCEPT = f"python3 /ck/runtime/cli.py accept-config --project /work/shop --sha256 {'a' * 64}"
REFUSAL = f"the configuration /work/shop/docs/workbench/runtime.json has the hash {'a' * 64} and the accepted one is {'b' * 64}. Read the file; when it is what you want, run: {ACCEPT}"


def run_node(tmp_path: Path, body: str, dom: str | None = None) -> dict:
    """Run `body` (an ES module that prints one JSON line) with Node and return what it printed."""
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", (tmp_path / "fake-dom.mjs").as_uri()), encoding="utf-8")
    (tmp_path / "fake-dom.mjs").write_text(dom or FLOOR_DOM, encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- A-18: the terminal-command component ------------------------------------------------------------------------------------------

COMMAND = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import * as c from "@JS@/frame/command.js";

const out = {};
out.is = [c.isCommand(@COMMAND@), c.isCommand("uv run --with keyring==25.7.0 python3 /ck/runtime/service.py --project /p"), c.isCommand("/usr/bin/python3 x"), c.isCommand("The credential is in neither"), c.isCommand(""), c.isCommand(null)];

const log = [];
const clip = { writeText: async (t) => { log.push(["write", t]); } };
out.copied = await c.copyCommand("cmd one", { clipboard: clip, select: () => { log.push(["select"]); return false; } });
out.denied = await c.copyCommand("cmd two", { clipboard: { writeText: async () => { throw new Error("denied"); } }, select: () => { log.push(["select-denied"]); return false; } });
out.noClipboard = await c.copyCommand("cmd three", { clipboard: null, select: () => { log.push(["select-none"]); return false; } });
out.legacyCopy = await c.copyCommand("cmd four", { clipboard: null, select: () => { log.push(["select-legacy"]); return true; } });
out.log = log.slice();

// the block: the sentence, the command whole, a Copy button
const later = [];
const written = [];
const block = c.commandBlock({ command: @COMMAND@, sentence: "Accept the configuration in the terminal:" },
  { clipboard: { writeText: async (t) => { written.push(t); } }, select: () => false, later: (fn) => later.push(fn) });
const code = find(block, ".wb-command-code");
const button = find(block, "button.wb-copy");
out.block = { sentence: find(block, ".wb-command-sentence").textContent, code: code.textContent, tag: code.tagName, button: button.textContent, type: button.attrs.type,
  name: button.attrs["aria-label"] || "" };
button.click();
await settle();
out.afterClick = { written: written.slice(), button: button.textContent, status: find(block, ".wb-copy-status").textContent, later: later.length };
later.forEach((fn) => fn());
out.reset = { button: button.textContent, status: find(block, ".wb-copy-status").textContent };

// a block with no command is nothing; a command that came with markup is text
out.none = [c.commandBlock({ command: "" }) === null, c.commandBlock({ command: null, sentence: "x" }) === null];
const hostile = c.commandBlock({ command: "python3 /ck/<b>x</b>.py", sentence: "<i>go</i>" }, { clipboard: null, select: () => false, later: () => {} });
out.text = [find(hostile, ".wb-command-code").textContent, find(hostile, ".wb-command-sentence").textContent, all(hostile, "b").length, all(hostile, "i").length];

// without a sentence there is no sentence line
out.bare = find(c.commandBlock({ command: "x y" }, { clipboard: null, select: () => false, later: () => {} }), ".wb-command-sentence");
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_command_component_copies_whole_and_falls_back_to_selecting(tmp_path):
    body = COMMAND.replace("@REFUSAL@", json.dumps(REFUSAL)).replace("@COMMAND@", json.dumps(ACCEPT))
    got = run_node(tmp_path, body)
    assert got["is"] == [True, True, True, False, False, False], "a command starts with a runner; a sentence does not"
    assert (got["copied"], got["denied"], got["noClipboard"], got["legacyCopy"]) == ("copied", "selected", "selected", "copied"), \
        "the clipboard when the browser allows it; else the text is selected (and copied where the old command works)"
    assert got["log"] == [["write", "cmd one"], ["select-denied"], ["select-none"], ["select-legacy"]], "the text is selected only when the clipboard is not available"
    assert got["block"] == {"sentence": "Accept the configuration in the terminal:", "code": ACCEPT, "tag": "CODE", "button": "Copy", "type": "button", "name": "Copy the command"}
    assert got["afterClick"]["written"] == [ACCEPT] and got["afterClick"]["button"] == "Copied" and got["afterClick"]["later"] == 1
    assert got["afterClick"]["status"] == "Copied to the clipboard."
    assert got["reset"] == {"button": "Copy", "status": ""}, "the button goes back to Copy after a moment"
    assert got["none"] == [True, True]
    assert got["text"] == ["python3 /ck/<b>x</b>.py", "<i>go</i>", 0, 0], "text from the service is text, never markup"
    assert got["bare"] is None


# --- A-16: the last data read stays when the configuration is not accepted -------------------------------------------------------------

DATA = r"""
import { setToken } from "@JS@/token.js";
import { emptySnapshot, refresh } from "@JS@/data.js";

setToken("t".repeat(40));
const P = "0123456789ab";
const REFUSAL = @REFUSAL@;
const NEXT = @NEXT@;
const mode = { value: "good" };
globalThis.fetch = async (url, init) => {
  const path = url.replace("/api/v1", "");
  const refused = (mode.value === "refused-on-read" || mode.value === "never" || mode.value === "listed-unaccepted") && (path.endsWith("/status") || path.endsWith("/agents"));
  if (refused) return { ok: false, status: 412, json: async () => ({ error: "not_configured", message: REFUSAL, next: NEXT }) };
  let body = {};
  if (path === "/projects") body = { projects: [mode.value === "listed-unaccepted" || mode.value === "never"
    ? { id: P, name: "northwind-shop", config: { accepted: false }, message: REFUSAL } : { id: P, name: "northwind-shop", config: { accepted: true } }] };
  else if (path === `/projects/${P}/status`) body = { config: {}, pending: [], documents: [], held: [], requests: [{ id: 1, title: "R", state: "ready", flow: null, tasks: [{ id: 2, key: "a", title: "A", agent: "business", skill: "s", state: "ready", note: null }] }] };
  else if (path === `/projects/${P}/agents`) body = { agents: [{ name: "business", mode: "supervised" }] };
  return { ok: true, status: 200, json: async () => body };
};
const out = {};
const brief = (s) => ({ accepted: s.projects[0].config.accepted, status: Boolean(s.details[P] && s.details[P].status), agents: s.details[P] && s.details[P].agents ? s.details[P].agents.length : null,
  error: s.details[P] && s.details[P].error ? [s.details[P].error.status, s.details[P].error.message, s.details[P].error.next || null] : null, loaded: s.loaded });

const good = await refresh(emptySnapshot(), P);
out.good = brief(good);
mode.value = "listed-unaccepted";
const listed = await refresh(good, P);
out.listed = brief(listed);
out.listedSame = listed.details[P].status === good.details[P].status;
mode.value = "refused-on-read";
const read = await refresh(good, P);
out.read = brief(read);
const again = await refresh(read, P);
out.again = brief(again);
mode.value = "good";
const back = await refresh(again, P);
out.back = brief(back);
mode.value = "never";
const first = await refresh(emptySnapshot(), P);
out.never = brief(first);
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_project_that_is_not_accepted_keeps_the_last_status_and_agents_read_with_the_services_message(tmp_path):
    got = run_node(tmp_path, DATA.replace("@REFUSAL@", json.dumps(REFUSAL)).replace("@NEXT@", json.dumps(ACCEPT)))
    assert got["good"] == {"accepted": True, "status": True, "agents": 1, "error": None, "loaded": True}
    for key in ("listed", "read", "again"):
        assert got[key]["status"] is True and got[key]["agents"] == 1 and got[key]["error"] == [412, REFUSAL, ACCEPT] and got[key]["loaded"] is True, \
            f"{key}: the data stays, with the service's own sentence and its command"
    assert got["listed"]["accepted"] is False and got["read"]["accepted"] is True, "listed as not accepted, or listed as accepted and refused on the read: both keep the data"
    assert got["listedSame"] is True, "the same bodies, not a copy that could drift"
    assert got["back"] == {"accepted": True, "status": True, "agents": 1, "error": None, "loaded": True}, "accepted again: the error goes with the next reload"
    assert got["never"]["status"] is False and got["never"]["loaded"] is True, "nothing was ever read: there is nothing to keep"


MODEL = r"""
import * as model from "@JS@/model.js";
import * as fm from "@JS@/floor-model.js";
import * as format from "@JS@/format.js";

const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const REFUSAL = @REFUSAL@;
const agent = (name, extra = {}) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 3, usd_today: 0.5, runs_without_cost: 0, queued: 0, held: 0, ...extra });
const task = (id, state, agentName, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: agentName, ...extra });
const status = {
  requests: [{ id: 1, title: "Spring", state: "ready", tasks: [task(2, "done", "marketing"), task(3, "running", "engineering"), task(4, "ready", "marketing")] }],
  pending: [{ id: 10, kind: "question", title: "q", task_id: 3, agent: "marketing", created_at: "2026-10-08T08:00:00Z", actions: ["answered"] }],
  documents: [], held: [],
};
const agents = [agent("marketing", { queued: 1 }), agent("engineering")];
const accepted = { projects: [{ id: P, name: "northwind-shop", config: { accepted: true }, running_task: 3 }], details: { [P]: { status, agents } }, tasks: {}, loaded: true };
const kept = { projects: [{ id: P, name: "northwind-shop", config: { accepted: false }, message: REFUSAL }], details: { [P]: { status, agents, error: { status: 412, word: "not_configured", message: REFUSAL } } }, tasks: {}, loaded: true };
const empty = { projects: kept.projects, details: {}, tasks: {}, loaded: true };
const out = {};

const plain = fm.building(accepted, P);
const keep = fm.building(kept, P);
out.rows = [plain.rows.map((r) => r.name), keep.rows.map((r) => r.name)];
out.accepted = [plain.accepted, keep.accepted, keep.kept];
out.words = keep.rows.map((r) => [r.label, r.plateWord, r.decisions, r.done, r.running]);
out.states = keep.rows.map((r) => [r.name, r.state, r.window]);
out.facts = keep.facts;
out.listWord = keep.rows.map((r) => r.stateWord);
out.plate = fm.plateOf(keep.rows[1]);
out.noData = (() => { const v = fm.building(empty, P); return [v.accepted, v.kept, v.rows.map((r) => r.plateWord), v.rows.map((r) => r.stateWord)]; })();

const floor = fm.floor(kept, P, "marketing", {});
out.floor = { found: floor.found, notAccepted: Boolean(floor.notAccepted), unaccepted: floor.unaccepted, tasks: floor.tasks.map((t) => t.id), decisions: floor.decisions.length, title: floor.header.title, sub: floor.header.sub, canvas: floor.canvasLabel };
out.floorNoData = (() => { const f = fm.floor(empty, P, "marketing", {}); return [f.notAccepted, Boolean(f.unaccepted)]; })();
out.board = fm.boardOf(floor).title;

const b = model.buildingOf(kept.projects[0], kept.details[P]);
const a = model.buildingOf(accepted.projects[0], accepted.details[P]);
out.building = { floors: [a.floors.length, b.floors.length], waits: b.floors.map((f) => f.waits), windows: [a.floors.map((f) => f.window), b.floors.map((f) => f.window)], decisions: [a.decisions, b.decisions], accepted: b.accepted, tip: model.tooltipOf(b), sub: model.subOf(b) };
out.kpis = [model.kpiSums(accepted, null), model.kpiSums(kept, null)];
out.tracking = [model.tracking(accepted, P, NOW).total, model.tracking(kept, P, NOW).total, model.tracking(kept, P, NOW).now.title];
out.waiting = [model.waitingRows(accepted, NOW).length, model.waitingRows(kept, NOW).length];
out.sub = [model.projectSub(accepted, P), model.projectSub(kept, P)];
out.city = model.city(kept, NOW).buildings.map((x) => [x.accepted, x.floors.length]);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_models_keep_the_whole_building_the_floors_the_kpis_and_the_bar_when_the_configuration_is_not_accepted(tmp_path):
    got = run_node(tmp_path, MODEL.replace("@REFUSAL@", json.dumps(REFUSAL)))
    assert got["rows"][0] == got["rows"][1] == ["marketing", "engineering"], "the same floors, in the same order"
    assert got["accepted"] == [True, False, True]
    assert [w[:2] for w in got["words"]] == [["Marketing", "not accepted"], ["Engineering", "not accepted"]], "every plate's state word is 'not accepted' and keeps the agent's name"
    marketing = [w for w in got["words"] if w[0] == "Marketing"][0]
    assert marketing[2] == 1 and marketing[3] == 1, "its decision and its done task are still counted"
    assert dict((s[0], s[2]) for s in got["states"])["engineering"] == "grey", "a window is warm only in an accepted project: grey while the configuration is not accepted"
    assert got["facts"]["configuration"] == "Not accepted" and got["facts"]["request"] == {"id": 1, "title": "Spring"} and got["facts"]["waiting"] == 1
    assert got["facts"]["running"]["id"] == 3, "the list no longer says which task runs; the last status does"
    assert "Waiting for the configuration to be accepted." not in got["listWord"], "the list keeps the real state words"
    assert got["plate"]["word"] == "not accepted" and got["plate"]["runsText"] == "3 / 8" and got["plate"]["usdText"] == "$0.50 / $2.00", "the plate keeps its numbers"
    assert got["noData"][0:2] == [False, False] and set(got["noData"][2]) == {"not accepted"}, "no data was ever read: the old placeholder row"
    assert got["noData"][3] == ["Waiting for the configuration to be accepted."]
    assert got["floor"]["found"] is True and got["floor"]["notAccepted"] is False and got["floor"]["unaccepted"] is True, "the floor keeps its room and panel"
    assert got["floor"]["tasks"] == [4, 2] and got["floor"]["decisions"] == 1 and got["floor"]["title"] == "Marketing · Marketing agent"
    assert got["floor"]["sub"].endswith("not accepted") and "not accepted" in got["floor"]["canvas"]
    assert got["floorNoData"] == [True, False]
    assert got["board"] == "#4 Task 4 · current task"
    b = got["building"]
    assert b["floors"] == [2, 2] and b["windows"][1] == ["grey", "grey"] and b["decisions"] == [1, 1] and b["waits"].count(True) == 1
    assert b["accepted"] is False and b["tip"] == "northwind-shop: not accepted yet" and b["sub"] == "not accepted yet"
    assert got["kpis"][0] == got["kpis"][1] and got["kpis"][1]["runs"] == 6 and got["kpis"][1]["decisions"] == 1, "the KPI cards keep their last values"
    assert got["tracking"] == [3, 3, "Task 3"], "the tracking bar keeps its steps and its Now card"
    assert got["waiting"] == [1, 1] and got["sub"][1] == "Not accepted"
    assert got["city"] == [[False, 2]], "the City's building keeps its floors"


# --- A-10 and A-12: the held reasons and the chips ------------------------------------------------------------------------------------

HELD = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import * as model from "@JS@/model.js";
import * as fm from "@JS@/floor-model.js";
import { plateNode, rowNode } from "@JS@/scene/plates.js";

const P = "0123456789ab";
const RUNNEXT = "uv run --with keyring==25.7.0 python3 /ck/runtime/cli.py run-next --project /work/shop";
const agent = (name, extra = {}) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0, ...extra });
const task = (id, state, agentName) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: agentName });
const held = (id, agentName, reason, next = null) => ({ task_id: id, agent: agentName, reason, at: "2026-10-08T11:59:30Z", next });
const status = {
  requests: [{ id: 1, title: "R", state: "ready", tasks: [
    task(2, "done", "marketing"), task(3, "ready", "marketing"), task(4, "ready", "business"), task(5, "running", "engineering"), task(6, "ready", "engineering"),
    task(7, "ready", "design"), task(8, "done", "brand"), task(9, "planned", "brand"), task(10, "blocked", "brand"), task(11, "done", "brand"), task(12, "running", "brand"), task(13, "ready", "brand")] }],
  pending: [],
  held: [held(3, "marketing", "dispatch off", RUNNEXT), held(4, "business", "cap: runs per day"), held(6, "engineering", "job running"), held(7, "design", "stopped"), held(13, "brand", "secret store", "uv run service")],
};
const agents = [agent("marketing", { queued: 1, held: 1 }), agent("business", { queued: 1, held: 1 }), agent("engineering", { queued: 1, held: 1 }),
  agent("design", { mode: "stopped", acting_mode: "stopped", queued: 1, held: 1 }), agent("brand", { queued: 1, held: 1 })];
const snapshot = { projects: [{ id: P, name: "northwind-shop", config: { accepted: true }, running_task: 5 }], details: { [P]: { status, agents } }, tasks: {}, loaded: true };
const out = {};
const view = fm.building(snapshot, P);
out.words = Object.fromEntries(view.rows.map((r) => [r.name, r.plateWord]));
out.states = Object.fromEntries(view.rows.map((r) => [r.name, r.state]));
const b = model.buildingOf(snapshot.projects[0], snapshot.details[P]);
out.tip = model.tooltipOf(b);
out.link = model.linkNameOf(b);
out.heldCount = b.held;
const none = JSON.parse(JSON.stringify(snapshot));
none.details[P].status.held = [];
none.details[P].agents.forEach((a) => { a.held = 0; });
out.tipNone = model.tooltipOf(model.buildingOf(none.projects[0], none.details[P]));
out.wordsNone = Object.fromEntries(fm.building(none, P).rows.map((r) => [r.name, r.plateWord]));

// the floor's current task block
const floor = fm.floor(snapshot, P, "marketing", {});
out.current = floor.current.id;
out.heldCurrent = floor.heldCurrent;
out.heldStopped = fm.floor(snapshot, P, "business", {}).heldCurrent;
out.sentences = ["stopped", "cap: runs per day", "cap: usd per day", "credential", "secret store", "image", "dispatch off", "job running", "no enabled agent owns the task", "other", "a new word"].map(fm.heldSentence);

// the chips, in order, each only when non-zero
// R-25: a plate has no count chips; the row of the floors list has them under its name row
const chipsOf = (row) => all(rowNode(fm.plateOf(row), {}), ".wb-fl-chips .pui-badge").map((c) => c.textContent);
const brand = view.rows.find((r) => r.name === "brand");
out.brand = { chips: chipsOf(brand), done: brand.done, running: brand.running, queued: brand.queued, left: brand.left };
out.marketing = chipsOf(view.rows.find((r) => r.name === "marketing"));
out.allZero = chipsOf(fm.building({ ...snapshot, details: { [P]: { status: { ...status, requests: [] }, agents: [agent("brand")] } } }, P).rows.find((r) => r.name === "brand"));
out.plateWord = all(plateNode(fm.plateOf(view.rows.find((r) => r.name === "marketing")), {}), ".wb-plate-state").map((n) => n.textContent);
out.plateTones = Object.fromEntries(view.rows.filter((r) => ["marketing", "business", "engineering", "design"].includes(r.name)).map((r) => [r.name, r.plateTone]));
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_plates_say_why_a_ready_task_is_held_the_tooltip_counts_them_and_the_chips_are_done_running_queued_left(tmp_path):
    got = run_node(tmp_path, HELD)
    assert got["words"]["marketing"] == "held: dispatch off" and got["words"]["business"] == "held: cap: runs per day", "the service's reason, after 'held: ', instead of 'resting'"
    assert got["words"]["engineering"] == "working", "a floor whose task runs says working; the held ready task is on the Agent tab"
    assert got["words"]["design"] == "Off, mode is stopped", "an agent that is stopped keeps its own word"
    assert got["words"]["brand"] == "working", "brand has a task running too"
    assert got["wordsNone"]["marketing"] == "resting" and got["wordsNone"]["business"] == "resting", "no held task: resting, as before"
    assert got["heldCount"] == 5 and got["tip"] == "northwind-shop: 0 decisions waiting, task #5 running, 5 held", "the City's tooltip counts the held tasks"
    assert got["tipNone"] == "northwind-shop: 0 decisions waiting, task #5 running" and got["link"].endswith("5 held")
    assert got["current"] == 3
    assert got["heldCurrent"] == {"task_id": 3, "reason": "dispatch off", "sentence": "The service is not dispatching tasks.", "next": "uv run --with keyring==25.7.0 python3 /ck/runtime/cli.py run-next --project /work/shop"}
    assert got["heldStopped"]["reason"] == "cap: runs per day" and got["heldStopped"]["next"] is None
    assert got["sentences"][0] == "The agent is stopped, so it starts nothing." and got["sentences"][6] == "The service is not dispatching tasks."
    assert len(set(got["sentences"][:10])) == 10 and all(got["sentences"][:10]), "one sentence per reason of the service's closed list"
    assert got["sentences"][10] == "a new word", "a reason the page does not know is shown as it came"
    assert got["brand"] == {"chips": ["2 done", "1 running", "1 queued", "2 left"], "done": 2, "running": 1, "queued": 1, "left": 2}, \
        "done, running, queued, left (planned or blocked), in that order"
    assert got["marketing"] == ["1 done", "1 queued"], "a chip with a zero is left out"
    assert got["allZero"] == []
    assert got["plateWord"] == ["held: dispatch off"]
    assert got["plateTones"] == {"marketing": "pui-warn", "business": "pui-warn", "engineering": "pui-theme", "design": "pui-muted"}, "R-26: held is warn, working is the brand colour, off is muted"


# --- A-20: the meters say what they count ----------------------------------------------------------------------------------------------

METERS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import * as fm from "@JS@/floor-model.js";
import * as format from "@JS@/format.js";
import * as control from "@JS@/views/control-model.js";
import { createKpis } from "@JS@/frame/kpis.js";
import { plateNode } from "@JS@/scene/plates.js";

const agent = (extra = {}) => ({ name: "engineering", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0.14, runs_without_cost: 0, queued: 0, held: 0, ...extra });
const out = {};
const m = fm.meters(agent());
out.agent = { runs: [m.runs.label, m.runs.text, m.runs.tip], spend: [m.spend.label, m.spend.text, m.spend.tip], names: [m.runs.name, m.spend.name] };
out.words = format.METER_WORDS;
const row = fm.floorRow(agent({ runs_today: 3 }), null, { accepted: true, project: "p", number: 1 });
out.card = fm.cardOf(row).runsLine;
const plate = plateNode(fm.plateOf(row), {});
out.plate = all(plate, ".wb-plate-meter").map((n) => [n.textContent, n.attrs.title || ""]);

const kpis = createKpis();
kpis.update({ decisions: 1, runs: 17, runsCap: 70, usd: 4.9, usdCap: 21.5 });
out.kpis = all(kpis.el, ".pui-card").map((c) => [c.attrs["aria-label"], c.attrs.title || "", find(c, ".wb-kpi-long") ? find(c, ".wb-kpi-long").textContent : ""]);

out.caps = control.capsLine([{ agent: "engineering", max_runs_per_day: 12, max_usd_per_day: 4 }], [{ name: "engineering", runs_today: 5, usd_today: 1.87 }]);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_meters_say_which_model_they_count_and_the_caps_line_uses_the_same_words(tmp_path):
    got = run_node(tmp_path, METERS)
    assert got["words"] == {"runs": "Runs today", "spend": "Spend today"}
    assert got["agent"]["runs"][:2] == ["Runs today", "0 / 8"] and got["agent"]["spend"][:2] == ["Spend today", "$0.14 / $2.00"]
    assert "subscription or free credential" in got["agent"]["runs"][2] and "runs per day" in got["agent"]["runs"][2], "a tooltip sentence that says what the cap counts: the billing"
    assert "metered credential" in got["agent"]["spend"][2] and "dollars per day" in got["agent"]["spend"][2]
    assert got["agent"]["names"] == ["Runs today 0 / 8", "Spend today $0.14 / $2.00"]
    assert got["card"].startswith("runs 3 / 8 · spend $0.14 / $2.00")
    assert [t[0] for t in got["plate"]] == ["3 / 8 runs", "$0.14 / $2.00"] and all(t[1] for t in got["plate"]), "R-25, R-5/R-6: the plate names its meters `runs` and `$`; each keeps its sentence as the tooltip"
    assert [k[2] for k in got["kpis"]] == ["Runs today", "Spend today"], "R-5: two cards; the count of open decisions is on \"Waiting for you\""
    assert got["kpis"][0][0] == "Runs today 17 of 70" and got["kpis"][1][0] == "Spend today $4.90 of $21.50 cap"
    assert got["caps"]["text"] == "Caps · engineering: runs 5 / 12, spend $1.87 / $4.00"
    assert "subscription or free credential" in got["caps"]["title"] and "metered credential" in got["caps"]["title"]


# --- A-17: Stop agent and Supervise, A-18 in the tab, A-10 in the current-task block -----------------------------------------------------

AGENT = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
import * as fm from "@JS@/floor-model.js";

const calls = [];
let script = {};
const record = (name) => async (...args) => { calls.push([name, ...args]); return script[name] ? script[name](...args) : {}; };
let refreshed = 0;
const tab = createAgentTab({ project: "p", agent: "engineering", api: { setMode: record("setMode"), retry: record("retry"), handOver: record("handOver") }, refresh: () => { refreshed += 1; }, now: () => new Date() });
const P = "0123456789ab";
const RUNNEXT = "uv run --with keyring==25.7.0 python3 /ck/runtime/cli.py run-next --project /work/shop";
const agent = (extra = {}) => ({ name: "engineering", pack: "code", enabled: true, mode: "milestones", acting_mode: "milestones", max_runs_per_day: 12, max_usd_per_day: 4, runs_today: 5, usd_today: 1.87, runs_without_cost: 0, queued: 1, held: 1, ...extra });
const task = (id, state, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: "engineering", ...extra });
const snapshot = (agentRow, tasks, held = [], accepted = true, error = null) => ({ projects: [{ id: P, name: "northwind-shop", config: { accepted } }],
  details: { [P]: { status: { requests: [{ id: 1, title: "R", state: "ready", tasks }], pending: [], held }, agents: [agentRow], ...(error ? { error } : {}) } }, tasks: {}, loaded: true });
const view = (agentRow, tasks, held = [], accepted = true) => fm.floor(snapshot(agentRow, tasks, held, accepted, accepted ? null : { status: 412, message: "m" }), P, "engineering", {});
const buttons = () => ({ stop: find(tab.el, "button[data-key=stop-agent]"), supervise: find(tab.el, "button[data-key=supervise]") });
const out = {};

tab.update(view(agent(), [task(4, "ready")]));
out.select = all(tab.el, "select").length;
out.labels = [buttons().stop.textContent, buttons().supervise.textContent];
out.enabled = [buttons().stop.disabled, buttons().supervise.disabled];
out.wider = find(tab.el, ".wb-mode-form").textContent;
out.standing = find(tab.el, ".wb-notice-card").textContent;
out.meters = all(tab.el, ".wb-meter-cell").map((c) => c.attrs["aria-label"]);
out.meterTitles = all(tab.el, ".wb-meter-cell").map((c) => Boolean(c.attrs.title));

// Stop agent sends the word once, the runtime accepts a narrowing at once, the page reloads and shows no command
script = { setMode: async () => ({ agent: "engineering", mode: "stopped", config_sha256: "f".repeat(64), accepted: true, by: "code:narrowing", next: null }) };
buttons().stop.click();
await settle();
out.stop = { calls: calls.slice(), refreshed, result: find(tab.el, ".wb-result-box").textContent, commands: all(tab.el, ".wb-result-box .wb-command-code").length };
tab.update(view(agent({ mode: "stopped", acting_mode: "stopped" }), [task(4, "ready")]));
out.afterStop = [buttons().stop.disabled, buttons().supervise.disabled];
tab.update(view(agent({ mode: "supervised", acting_mode: "supervised" }), [task(4, "ready")]));
out.supervised = [buttons().stop.disabled, buttons().supervise.disabled];
calls.length = 0;
script = { setMode: async () => ({ agent: "engineering", mode: "supervised", accepted: true, by: "code:narrowing", next: null }) };
tab.update(view(agent({ mode: "milestones", acting_mode: "milestones" }), [task(4, "ready")]));
buttons().supervise.click();
await settle();
out.supervise = calls.slice();
out.busyWhileSending = null;

// a refusal is shown under the buttons; a result that was not accepted shows the command the service gave, with Copy
script = { setMode: async () => { throw Object.assign(new Error("the configuration changed while this call was running"), { name: "ApiError", status: 409, word: "refused" }); } };
buttons().stop.click();
await settle();
out.refused = find(tab.el, ".wb-form-error").textContent;
script = { setMode: async () => ({ agent: "engineering", mode: "stopped", accepted: false, next: "python3 /ck/runtime/cli.py accept-config --project /work/shop --sha256 " + "e".repeat(64) }) };
buttons().stop.click();
await settle();
out.notAccepted = { code: find(tab.el, ".wb-result-box .wb-command-code").textContent, copy: all(tab.el, ".wb-result-box button.wb-copy").length };

// a configuration that is not accepted: the controls are off, the data stays
tab.update(view(agent(), [task(4, "ready")], [], false));
out.unaccepted = { buttons: [buttons().stop.disabled, buttons().supervise.disabled], waitingLine: find(tab.el, ".wb-empty-line").hidden, meters: all(tab.el, ".wb-meter-cell").length, formHidden: find(tab.el, ".wb-mode-form").hidden };

// the current task block: the held reason as a sentence, with the command the service gave
tab.update(view(agent(), [task(4, "ready")], [{ task_id: 4, agent: "engineering", reason: "dispatch off", at: "x", next: RUNNEXT }]));
out.held = { text: find(tab.el, ".wb-held").textContent, code: find(tab.el, ".wb-held .wb-command-code").textContent, copy: all(tab.el, ".wb-held button.wb-copy").length };
tab.update(view(agent(), [task(4, "ready")], [{ task_id: 4, agent: "engineering", reason: "cap: usd per day", at: "x", next: null }]));
out.heldNoCommand = { text: find(tab.el, ".wb-held").textContent, code: all(tab.el, ".wb-held .wb-command-code").length };
tab.update(view(agent(), [task(4, "ready")], []));
out.heldGone = all(tab.el, ".wb-held").length;
console.log(JSON.stringify(out));
"""


# --- the Control room: the same words, and a service card with the commands the service gave ----------------------------------------------

CONTROL = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import * as model from "@JS@/views/control-model.js";
import { createConnectionsTab } from "@JS@/views/control-connections.js";

const START = "uv run --with keyring==25.7.0 python3 /ck/runtime/service.py --project /work/shop";
const service = { secret_store: "this interpreter cannot read the secret store: start with uv", credential: "the reference model's credential (KEY) is neither set nor found in the secret store", docker: "ok", image: "the eval image x is not on this machine", dispatch: "off", problems: ["lab: boom"], start: START, at: "2026-10-08T11:00:00Z" };
const out = {};
out.rows = model.serviceRows(service).map((r) => [r.what, r.sentence, r.command]);
out.ok = model.serviceRows({ ...service, secret_store: "ok", credential: "ok", image: "ok", dispatch: "every 30 s", problems: [] });
out.none = [model.serviceRows(null), model.serviceRows(undefined)];
const tab = createConnectionsTab();
tab.set({ status: "ready", data: { classes: [], secrets: [], secrets_note: null, image: { name: "x", present: false, evidence: null }, platform: { machine: "arm64", evidence: "linux/arm64", here: "linux/arm64", same: true }, service } });
out.card = { rows: all(tab.el, ".wb-service-row").length, codes: all(tab.el, ".wb-service-card .wb-command-code").map((c) => c.textContent), copies: all(tab.el, ".wb-service-card button.wb-copy").length };
tab.set({ status: "ready", data: { classes: [], secrets: [], secrets_note: null, image: { name: "x", present: false, evidence: null }, platform: { machine: "arm64", evidence: "linux/arm64", here: "linux/arm64", same: true }, service: null } });
out.cardNone = all(tab.el, ".wb-service-card").length;
console.log(JSON.stringify(out));
"""


# --- the page: a 412 after a good read keeps the screen, dims it, and puts the command in the band ------------------------------------------

MAIN = CLOCK + r"""
import { FakeNode } from "@FAKE@";

const clock = makeClock();
globalThis.setTimeout = (fn, ms) => clock.setTimer(fn, ms);
globalThis.clearTimeout = (id) => clock.clearTimer(id);
Date.now = () => clock.now();
const P = "0123456789ab";
const REFUSAL = @REFUSAL@;
const NEXT = @NEXT@;
const listeners = { window: {} };
window.addEventListener = (type, fn) => { (listeners.window[type] ||= []).push(fn); };
window.removeEventListener = () => {};
const store = { "workbench.session.credential": "t".repeat(40) };
window.sessionStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = v; }, removeItem: (k) => { delete store[k]; } };
window.location.hash = "#/p/" + P + "/floor/marketing@TAB@";
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const root = new FakeNode("div");
document.getElementById = () => root;
document.hidden = false;
const service = { version: 1, accepted: true };
const seen = [];
globalThis.fetch = async (url, init) => {
  const path = url.replace("/api/v1", "");
  seen.push(path);
  if (path === "/versions") return { ok: true, status: 200, json: async () => ({ versions: { [P]: { version: service.version, changed_at: "x" } } }) };
  if (path === "/projects") return { ok: true, status: 200, json: async () => ({ projects: [service.accepted
    ? { id: P, name: "northwind-shop", config: { sha256: "a".repeat(64), accepted: true } }
    : { id: P, name: "northwind-shop", config: { sha256: "a".repeat(64), accepted: false }, message: REFUSAL }] }) };
  if (!service.accepted && path.startsWith(`/projects/${P}/`)) return { ok: false, status: 412, json: async () => ({ error: "not_configured", message: REFUSAL, next: NEXT }) };
  let body = {};
  if (path === `/projects/${P}/status`) body = { config: {}, held: [], requests: [{ id: 2, title: "Sale page", state: "planned", flow: null, tasks: [{ id: 4, key: "a", title: "Build", agent: "marketing", skill: "s", state: "waiting", note: null }] }], pending: [{ id: 5, kind: "question", title: "Which colour?", task_id: 4, agent: "marketing", created_at: "2026-10-08T08:00:00Z", actions: ["answered"] }], documents: [] };
  else if (path === `/projects/${P}/agents`) body = { agents: [{ name: "marketing", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 6, max_usd_per_day: 3, runs_today: 4, usd_today: 1.5, runs_without_cost: 0, queued: 0, held: 0 }] };
  else if (path.startsWith(`/projects/${P}/tasks/`)) body = { task: { id: 4, state: "waiting" }, runs: [], pending: [] };
  else if (path.startsWith(`/projects/${P}/artifacts`)) body = { artifacts: [], truncated: false };
  return { ok: true, status: 200, json: async () => body };
};
const frameEl = () => [...root.walk()].find((n) => n.attrs && (n.attrs.class || "").split(/\s+/).includes("wb-frame"));
const classed = (cls) => [...root.walk()].filter((n) => n.attrs && (n.attrs.class || "").split(/\s+/).includes(cls));
const text = (cls) => classed(cls).map((n) => n.textContent).join(" | ");
const snap = () => ({
  dimmed: frameEl().classList.contains("is-unaccepted"),
  kpis: text("wb-kpi-figure"), title: text("wb-panel-title"), sub: text("wb-panel-sub"),
  decisions: text("wb-badge") , track: classed("wb-track").length,
  band: text("wb-notice"), sentence: classed("wb-command-sentence").map((n) => n.textContent).join(" "), codes: classed("wb-command-code").map((n) => n.textContent), copies: classed("wb-copy").length,
  inert: classed("wb-inbox").concat(classed("wb-tasks-tab")).map((n) => "inert" in n.attrs), asked: seen.filter((p) => /\/(tasks|artifacts)/.test(p)).length, skeleton: classed("wb-busy").length, tabs: classed("wb-tab").length, state: text("wb-state-row"), meters: text("wb-meter-cell"),
});
const out = {};
await import("@JS@/main.js");
await clock.advance(0);
await clock.advance(2000);
out.before = snap();
service.accepted = false;
service.version = 2;
await clock.advance(1000);
await clock.advance(1000);
const askedBefore = snap().asked;
service.version = 3;
await clock.advance(1000);
await clock.advance(1000);
await clock.advance(31000);
out.during = snap();
out.askedAgain = out.during.asked - askedBefore;
service.version = 2;
service.accepted = true;
service.version = 5;
await clock.advance(1000);
await clock.advance(1000);
out.after = snap();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_page_keeps_the_floor_dims_it_and_shows_the_command_in_the_band_while_the_configuration_is_not_accepted(tmp_path):
    got = run_node(tmp_path, MAIN.replace("@REFUSAL@", json.dumps(REFUSAL)).replace("@NEXT@", json.dumps(ACCEPT)).replace("@TAB@", ""), SCENE_DOM)
    before, during, after = got["before"], got["during"], got["after"]
    assert before["dimmed"] is False and before["codes"] == [] and before["title"] == "Marketing · Marketing agent"
    assert during["dimmed"] is True, "one class on the screen"
    assert during["title"] == before["title"] and during["kpis"] == before["kpis"] and during["track"] == before["track"], "the panel, the KPI cards and the bar are what they were"
    assert during["state"] == before["state"] and during["meters"] == before["meters"], "the Agent tab keeps its state row and its meters"
    assert during["skeleton"] == 0, "nothing is swapped for a skeleton"
    assert during["codes"] == [ACCEPT] and during["copies"] == 1, "the band carries the service's command whole, with Copy"
    assert "not accepted" in during["band"] and "Read the file" in during["band"]
    assert during["band"].count("accept-config") == 1, "the command is in the code block once: the sentence is the service's message without it"
    assert during["sentence"].endswith("when it is what you want, run:")
    assert after["dimmed"] is False and after["codes"] == [] and after["title"] == before["title"], "accepted again: the dim lifts and the band goes"


# --- the files ------------------------------------------------------------------------------------------------------------------------

def _css() -> str:
    return interface_css()


def _rule(css: str, selector: str) -> str:
    found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert found, f"no rule for {selector}"
    return found.group(1)


def test_the_command_is_drawn_wrapped_whole_and_selectable_never_scrolling_sideways():
    css = _css()
    code = _rule(css, ".wb-command-code")
    assert "white-space: pre-wrap" in code and "overflow-wrap: anywhere" in code and "user-select: all" in code
    assert "overflow-x" not in code and "overflow: auto" not in code and "text-overflow" not in code
    assert "var(--" in code, "its edge and ground are tokens"
    assert "min-width: 0" in code or "min-width: 0" in _rule(css, ".wb-command-row")


def test_the_not_accepted_dim_is_one_class_with_opacity_and_no_pointer_actions_on_the_scene():
    css = _css()
    assert re.search(r"\.wb-frame\.is-unaccepted[^{]*\.wb-scene[^{]*\{[^}]*pointer-events: none", css), "the scene takes no pointer actions"
    assert re.search(r"\.wb-frame\.is-unaccepted[^{]*\{[^}]*opacity: 0\.\d", css), "dimmed by opacity"
    assert not re.search(r"\.wb-frame\.is-unaccepted[^{]*\.wb-notice[^{]*\{[^}]*opacity", css), "the band that carries the command is never dimmed"


def test_every_notice_that_needs_the_terminal_uses_the_one_component_and_the_page_builds_no_command():
    for name in ("frame/frame.js", "floor/agent-tab.js", "views/control-connections.js"):
        assert "command.js" in (JS / name).read_text(encoding="utf-8"), f"{name} draws a command with the component"
    for path in JS.rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        # `keyring==` is the library's version pin, which every command of the service carries. A-22: the credential's commands are the fields
        # `held[].commands` the service gives (command.js no longer reads them out of a sentence), so no module holds a pattern of one.
        assert "cli.py" not in text and "keyring==" not in text and "accept-config --" not in text and "run-next --" not in text, f"{path.name}: a command is the service's, never built on the page"
    assert '"select"' not in (JS / "floor/agent-tab.js").read_text(encoding="utf-8"), "the mode select is gone"


@needs_node
def test_the_inbox_and_the_tasks_are_inert_while_not_accepted_and_a_refusing_project_is_not_asked_for_bodies_or_documents_again(tmp_path):
    for tab in ("/inbox", "/tasks"):
        got = run_node(tmp_path, MAIN.replace("@REFUSAL@", json.dumps(REFUSAL)).replace("@NEXT@", json.dumps(ACCEPT)).replace("@TAB@", tab), SCENE_DOM)
        before, during, after = got["before"], got["during"], got["after"]
        assert before["inert"] and not any(before["inert"]), f"{tab}: live while accepted"
        assert during["inert"] and all(during["inert"]), f"{tab}: the cards and the buttons take no click while the configuration is not accepted"
        assert after["inert"] and not any(after["inert"]), f"{tab}: live again once accepted"
        assert got["askedAgain"] == 0, f"{tab}: no task body or document is asked of a project that answers 412"


# --- A-20 completed (WP-9.14b): the two-segment spend meter, "All runs today: n" ----------------------------------------------------------

SPEND = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import * as fm from "@JS@/floor-model.js";
import * as model from "@JS@/model.js";
import * as format from "@JS@/format.js";
import * as control from "@JS@/views/control-model.js";
import { createKpis } from "@JS@/frame/kpis.js";
import { plateNode } from "@JS@/scene/plates.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";

const P = "0123456789ab";
const agent = (extra = {}) => ({ name: "engineering", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 1.64, usd_recorded: 0.14, usd_reserved: 1.5,
  runs_total_today: 3, runs_without_cost: 1, queued: 0, held: 0, wider: [], ...extra });
const out = {};
out.words = [format.spendNote(0.14, 1.5), format.spendNote(0.14, 0), format.spendNote(0, 0), format.spendNote(0, 1.5)];
const m = fm.meters(agent());
out.meter = { recorded: m.spend.recorded, reserved: m.spend.reserved, note: m.spend.note, shares: [m.spend.recordedShare, m.spend.reservedShare], total: m.runsTotal, text: m.spend.text };
const over = fm.meters(agent({ usd_today: 2.5, usd_recorded: 1, usd_reserved: 1.5, max_usd_per_day: 2 }));
out.over = [over.spend.recordedShare, over.spend.reservedShare];
const old = fm.meters({ name: "x", max_runs_per_day: 8, max_usd_per_day: 2, usd_today: 0.5, runs_today: 1, queued: 0 });
out.old = [old.spend.note, old.spend.recordedShare, old.spend.reservedShare, old.runsTotal];

// the plate
const row = fm.floorRow(agent(), null, { accepted: true, project: "p", number: 1 });
const plate = plateNode(fm.plateOf(row), {});
const track = all(plate, ".wb-plate-meter .wb-meter")[1];
// R-25: a plate has no caption sentence; the note of the spend meter is the end of its tooltip
out.plate = { note: [all(plate, ".wb-plate-meter")[1].attrs.title], fills: all(track, ".wb-meter-fill").length, reserved: all(track, ".wb-meter-reserved").length, has: track.classList.contains("has-reserved"),
  first: all(plate, ".wb-plate-meter .wb-meter")[0].querySelectorAll(".wb-meter-reserved").length };
out.cardLine = fm.cardOf(row).runsLine;
out.cardNote = fm.cardOf(row).runsNote;

// the KPI cards
const sums = model.kpiSums({ projects: [{ id: P }], details: { [P]: { agents: [agent(), agent({ name: "marketing", usd_today: 0.2, usd_recorded: 0.2, usd_reserved: 0, runs_total_today: 1 })] } } }, null);
out.sums = [sums.usd, sums.usdRecorded, sums.usdReserved, sums.runsTotal];
const kpis = createKpis();
kpis.update({ decisions: 0, runs: 3, runsCap: 16, usd: 1.84, usdCap: 4, usdRecorded: 0.34, usdReserved: 1.5, runsTotal: 4 });
const cards = all(kpis.el, ".pui-card");
out.kpi = { note: all(cards[1], ".wb-kpi-note").map((n) => n.textContent), reserved: all(cards[1], ".wb-meter-reserved").length, aria: cards[1].attrs["aria-label"], runsTitle: cards[0].title };
kpis.update({ decisions: 0, runs: 3, runsCap: 16, usd: 0.34, usdCap: 4, usdRecorded: 0.34, usdReserved: 0, runsTotal: 4 });
out.kpiNoReserve = all(all(kpis.el, ".pui-card")[1], ".wb-kpi-note").map((n) => n.textContent);

// the caps line
out.caps = control.capsLine([{ agent: "engineering", max_runs_per_day: 8, max_usd_per_day: 2 }], [agent({ runs_today: 5 })]);

// the Agent tab
const tab = createAgentTab({ project: "p", agent: "engineering", api: { setMode: async () => ({}), retry: async () => ({}), handOver: async () => ({}) }, refresh: () => {}, now: () => new Date() });
const snapshot = { projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [], pending: [], held: [] }, agents: [agent()] } }, tasks: {}, loaded: true };
tab.update(fm.floor(snapshot, P, "engineering", {}));
const cell = all(tab.el, ".wb-meter-cell")[1];
out.tab = { note: find(cell, ".wb-note").textContent, reserved: all(cell, ".wb-meter-reserved").length, total: find(tab.el, ".wb-runs-total").textContent, aria: cell.attrs["aria-label"] };
// not accepted and back: the identical meters are not drawn again, and the total must still be shown
tab.update(fm.floor({ projects: [{ id: P, name: "n", config: { accepted: false } }], details: {}, tasks: {}, loaded: true }, P, "engineering", {}));
out.during = find(tab.el, ".wb-runs-total").hidden;
tab.update(fm.floor(snapshot, P, "engineering", {}));
out.after = [find(tab.el, ".wb-runs-total").hidden, find(tab.el, ".wb-runs-total").textContent];

// the two notes together: runs of unknown cost that nothing is reserved for, beside the recorded spend
const unknown = agent({ usd_today: 0.14, usd_recorded: 0.14, usd_reserved: 0, runs_without_cost: 2 });
const urow = fm.floorRow(unknown, null, { accepted: true, project: "p", number: 1 });
out.unknown = { card: fm.cardOf(urow).runsNote, plate: [all(plateNode(fm.plateOf(urow), {}), ".wb-plate-meter")[1].attrs.title], tab: fm.meters(unknown).spend.notes,
  reserved: fm.meters(agent({ runs_without_cost: 2 })).spend.notes };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_spend_meter_has_two_segments_with_both_numbers_labelled_and_the_runs_total_is_a_plain_line(tmp_path):
    got = run_node(tmp_path, SPEND)
    assert got["words"] == ["$0.14 recorded · up to $1.50 reserved", "$0.14 recorded", "", "$0.00 recorded · up to $1.50 reserved"], "the reserved part only when something is reserved"
    assert got["meter"]["recorded"] == 0.14 and got["meter"]["reserved"] == 1.5 and got["meter"]["note"] == "$0.14 recorded · up to $1.50 reserved" and got["meter"]["text"] == "$1.64 / $2.00"
    assert got["meter"]["shares"] == [0.07, 0.75] and got["meter"]["total"] == "All runs today: 3", "the shares are the page's division of the service's two numbers; the total is the service's"
    assert got["over"][0] + got["over"][1] <= 1, "the two segments never pass the track"
    assert got["old"] == ["", 0.25, 0, None], "an entry with no split (an older service) is all recorded"
    p = got["plate"]
    assert p["note"][0].endswith("$0.14 recorded · up to $1.50 reserved") and p["fills"] == 1 and p["reserved"] == 1 and p["has"] is True and p["first"] == 0, "the second meter of the plate has the second segment"
    assert got["cardLine"].endswith("spend $1.64 / $2.00") and got["cardNote"] == "$0.14 recorded · up to $1.50 reserved", "the phone's card line is plain; the note is its tooltip"
    assert [round(x, 6) for x in got["sums"]] == [1.84, 0.34, 1.5, 4]
    assert got["kpi"]["note"] == ["$0.34 recorded · up to $1.50 reserved"] and got["kpi"]["reserved"] == 1 and "up to $1.50 reserved" in got["kpi"]["aria"]
    assert "All runs today: 4" in got["kpi"]["runsTitle"]
    assert got["kpiNoReserve"] == [""], "nothing reserved: no second number, the line is empty"
    assert got["caps"]["text"] == "Caps · engineering: runs 5 / 8, spend $1.64 / $2.00 ($0.14 recorded · up to $1.50 reserved), All runs today: 3"
    assert got["tab"] == {"note": "$0.14 recorded · up to $1.50 reserved", "reserved": 1, "total": "All runs today: 3", "aria": "Spend today $1.64 / $2.00"}
    assert got["during"] is True and got["after"] == [False, "All runs today: 3"], "the total is shown again after a not-accepted spell"
    both = "$0.14 recorded (+2 of unknown cost)"
    assert got["unknown"]["tab"] == both and got["unknown"]["plate"][0].endswith(both) and got["unknown"]["card"] == both, "both notes when both apply (the card keeps them as its line's tooltip)"
    assert got["unknown"]["reserved"] == "$0.14 recorded · up to $1.50 reserved", "when something is reserved the reservation already says so"


def test_the_reserved_segment_has_its_own_token_in_one_place_and_the_track_holds_both_segments():
    css = _css()
    assert len(re.findall(r"--wb-tint-reserved:", css)) == 1, "one definition, in :root"
    assert "var(--wb-tint-reserved)" in _rule(css, ".wb-meter-reserved")
    assert "display: flex" in _rule(css, ".wb-meter"), "the two segments sit on one line"
    assert not re.search(r"\.wb-meter-reserved[^{]*\{[^}]*(#[0-9a-fA-F]{3,8}|rgb\()", css), "no literal colour"


# --- the wider modes and the credential, from the service (WP-9.14b) -----------------------------------------------------------------------

WIDER = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
import * as fm from "@JS@/floor-model.js";

const P = "0123456789ab";
const tab = createAgentTab({ project: "p", agent: "engineering", api: { setMode: async () => ({}), retry: async () => ({}), handOver: async () => ({}) }, refresh: () => {}, now: () => new Date() });
const wider = (mode, names) => names.map((m) => ({ mode: m, command: `python3 /ck/runtime/cli.py set-mode --project /work/shop --agent engineering --mode ${m}` }));
const agent = (extra = {}) => ({ name: "engineering", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 1, held: 1, ...extra });
const task = { id: 4, key: "k", title: "T", skill: "s", state: "ready", note: null, agent: "engineering" };
const view = (a, held = []) => fm.floor({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 1, title: "R", state: "ready", tasks: [task] }], pending: [], held }, agents: [a] } }, tasks: {}, loaded: true }, P, "engineering", {});
const out = {};
tab.update(view(agent({ wider: wider("supervised", ["milestones", "autonomous", "autonomous-with-policy"]) })));
const form = find(tab.el, ".wb-mode-form");
out.three = { line: find(form, ".wb-wider").textContent, codes: all(form, ".wb-command-code").map((c) => c.textContent), sentences: all(form, ".wb-command-sentence").map((c) => c.textContent), copies: all(form, "button.wb-copy").length };
tab.update(view(agent({ mode: "autonomous-with-policy", acting_mode: "autonomous-with-policy", wider: [] })));
out.top = { wider: all(find(tab.el, ".wb-mode-form"), ".wb-wider").filter((n) => !n.hidden).length, codes: all(find(tab.el, ".wb-mode-form"), ".wb-command-code").length };
tab.update(view(agent({})));
out.none = { codes: all(find(tab.el, ".wb-mode-form"), ".wb-command-code").length, line: all(find(tab.el, ".wb-mode-form"), ".wb-wider").filter((n) => !n.hidden).length };

// the held reason credential (A-22): the sentence is text; each command is a field of the service's `commands` ([{name, command}]), drawn with Copy, and a name with no
// username registered (command null) is its name and "no username registered": nothing is read out of the sentence
const credential = "The credential is in neither the environment nor the secret store. Store it once, the value typed at a hidden prompt.";
const commands = [{ name: "KEY_A", command: "uv run --with keyring==25.7.0 keyring set openhora user-a" }, { name: "KEY_B", command: null }];
tab.update(view(agent({ wider: [] }), [{ task_id: 4, agent: "engineering", reason: "credential", at: "x", next: credential, commands }]));
const held = find(tab.el, ".wb-held");
out.credential = { text: held.textContent.slice(0, 120), codes: all(held, ".wb-command-code").map((c) => c.textContent), sentences: all(held, ".wb-command-sentence").map((c) => c.textContent), copies: all(held, "button.wb-copy").length,
  line: find(held, ".wb-held-line").textContent, details: all(held, ".wb-held-detail").map((c) => c.textContent) };
// a sentence that still holds a command inside it is text: the page does not take it out
tab.update(view(agent({ wider: [] }), [{ task_id: 4, agent: "engineering", reason: "credential", at: "y", next: "Store it: KEY_A: uv run --with keyring==25.7.0 keyring set openhora user-a.", commands: [] }]));
out.inline = { codes: all(find(tab.el, ".wb-held"), ".wb-command-code").length };
// the other reasons: a command in `next` is drawn as one command
tab.update(view(agent({ wider: [] }), [{ task_id: 4, agent: "engineering", reason: "job running", at: "z", next: "python3 /ck/runtime/cli.py run-next --project /work/shop", commands: [] }]));
out.single = { codes: all(find(tab.el, ".wb-held"), ".wb-command-code").map((c) => c.textContent) };
console.log(JSON.stringify(out));
"""

