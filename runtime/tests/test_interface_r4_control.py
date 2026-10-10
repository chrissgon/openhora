"""Tests of the Control room screen that look at its presentation (R4-S): the classes its modules build against the stylesheet and the Connections tab's rows. A package
for the Control room edits this file and `test_interface_control.py`, `interface/css/control.css` and `interface/js/views/control*.js`; the tests of the shared files
(`test_interface_files.py`: routes, writes, text as text) stay where they are. The tests below were moved here from the shared files with their names and their
assertions unchanged; each reads what it needs through the module it came from.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_control.py
"""
from __future__ import annotations

import re

from interface_css import css_file, interface_css
from test_interface_files import INTERFACE, control_modules
from test_interface_plates_meters import CONTROL, needs_node, run_node


# --- moved from test_interface_files.py ------------------------------------------------------------------------------------------


def test_every_wb_class_the_control_room_builds_is_a_rule_of_the_stylesheet():
    css = interface_css()
    defined = set(re.findall(r"\.(wb-[a-z0-9-]+)", css))
    markers = {"is-open", "is-wide", "is-selected"}  # state words, not classes of their own
    for path in control_modules():
        text = path.read_text(encoding="utf-8")
        for group in re.findall(r"class: `?\"?([^\"`]+)[\"`]", text):
            for name in re.findall(r"\bwb-[a-z0-9-]+", group.split("${")[0]):
                if name.endswith("-"):
                    continue
                assert name in defined or name in markers, f"{path.name} builds the class {name}, which the stylesheets do not draw"
    # the three tab words the hash carries are the router's, and the page reaches the screen from its one router
    main = (INTERFACE / "js" / "main.js").read_text(encoding="utf-8")
    assert 'import { createControlView } from "./views/control.js";' in main and 'route.screen === "control"' in main
    model = (INTERFACE / "js" / "views" / "control-model.js").read_text(encoding="utf-8")
    assert re.search(r'TABS = Object\.freeze\(\[\["skills", "Skills"\], \["costs", "Costs"\], \["connections", "Connections"\]\]\)', model)

# --- moved from test_interface_plates_meters.py ----------------------------------------------------------------------------------


@needs_node
def test_the_connections_tab_shows_each_problem_the_service_found_at_its_start_and_the_command_that_starts_it_again(tmp_path):
    got = run_node(tmp_path, CONTROL)
    whats = [r[0] for r in got["rows"]]
    assert whats == ["Secret store", "Credential", "Image", "Dispatch", "Problem"], "one row per verdict that is not ok, in this order"
    commands = {r[0]: r[2] for r in got["rows"]}
    assert commands["Secret store"].startswith("uv run --with keyring==25.7.0 python3 /ck/runtime/service.py"), "the service's `start`, verbatim"
    assert commands["Dispatch"] == commands["Secret store"], "dispatch off is started again the same way"
    assert commands["Credential"] is None and commands["Image"] is None and commands["Problem"] is None, "no command exists for these: the sentence only"
    assert got["ok"] == [] and got["none"] == [[], []]
    assert got["card"]["rows"] == 5 and len(got["card"]["codes"]) == 2 and got["card"]["copies"] == 2
    assert got["cardNone"] == 0


# =====================================================================================================================================
# R4-A6: the Control room as `control-room.html` draws it (R-50, R-52 to R-55, B3-5). New behaviour, tested here first.
# =====================================================================================================================================

import json
import subprocess
import sys

import pytest

from test_interface_control import FAKE_DOM, JS, NODE, VIEWS, needs_node as needs_node_here


def node(tmp_path, body: str) -> dict:
    """Run an ES module under Node with the Control room's fake document and return the one JSON line it prints."""
    (tmp_path / "fake-dom.mjs").write_text(FAKE_DOM, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", (tmp_path / "fake-dom.mjs").as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


HELPERS = r"""
import { FakeNode, has, settle } from "@FAKE@";
const flat = (n) => (n.children === undefined ? n.data : n.children.filter((c) => !(c.attrs && c.attrs["aria-hidden"] === "true")).map(flat).join(" "));
const text = (n) => flat(n).replace(/\s+/g, " ").trim();
const pair = (tier, band, score, extra = {}) => ({ tier, model: tier === "strong" ? "reference-model-1" : "floor-model-1", adapter: tier === "strong" ? "adapter-a" : "adapter-b", band, cause: null, score, mean: score, runs: 9, ...extra });
const skill = (name, area, strong, floor, extra = {}) => ({ name, version: "1.2.0", area, manifest: true, runs_here: 3, proof: [strong, floor].filter(Boolean), ...extra });
const skillsData = {
  skills: [skill("brand-voice", "brand", pair("strong", "reliable", 0.86), pair("floor", "watch", 0.58, { cause: "pessimistic score under 0.70" })),
    skill("brand-identity", "brand", pair("strong", "watch", 0.66), pair("floor", "needs a test", null, { mean: null, runs: 0, cause: "no evidence on this model" }), { runs_here: 0 }),
    skill("mkt-publish", "marketing", pair("strong", "needs a test", null, { mean: null, runs: 0 }), null, { manifest: false, runs_here: null })],
  checks: { measurement: "ok", image: "ok" },
};
"""

SKILLS_R4 = HELPERS + r"""
import { createSkillsTab } from "@JS@/views/control-skills.js";
const out = {};
const tab = createSkillsTab();
tab.set({ status: "ready", data: skillsData });
out.tables = tab.el.all((n) => n.tagName === "TABLE").length;
const list = tab.el.find((n) => has(n, "wb-skill-list"));
out.group = [list.attrs.role, list.attrs["aria-label"]];
out.head = [list.find((n) => has(n, "wb-skill-head")).attrs["aria-hidden"], list.find((n) => has(n, "wb-skill-head")).children.map(text)];
const rowsOf = () => tab.el.find((n) => has(n, "wb-skill-list")).all((n) => n.tagName === "DETAILS" && has(n, "wb-skill-row"));
out.rows = rowsOf().map((r) => {
  const sum = r.children[0];
  return { cls: r.cls(), parts: sum.children.map((c) => c.cls().join(" ")), cells: sum.children.map(text), body: r.find((n) => has(n, "wb-skill-detail")).children.map(text), open: r.open, label: sum.attrs["aria-label"] };
});
// the score comes first, then the band's chip (M-2, R-53), in the list
const band = rowsOf()[0].children[0].children[4].find((n) => has(n, "wb-band"));
out.order = band.children.flatMap((c) => c.cls().filter((x) => x === "wb-score" || x === "pui-chip"));
// the chevron is the accordion's, drawn by the stylesheet from an icon
out.chevron = rowsOf()[0].children[0].children[0].cls();
// an open row stays open through a read and the same skill's phone card follows it
const cards = () => tab.el.all((n) => has(n, "wb-skill-card"));
rowsOf()[0].open = true; rowsOf()[0].fire("toggle");
out.afterToggle = [cards()[0].open, cards()[1].open];
tab.set({ status: "ready", data: skillsData });
out.keptOpen = [rowsOf()[0].open, cards()[0].open, rowsOf()[1].open];
cards()[1].open = true; cards()[1].fire("toggle");
out.cardToRow = [rowsOf()[1].open, rowsOf()[2].open];
// the card of a phone: name and "version · area", the manifest and runs, the two tiers with the score first; opened: the two sentences only
out.cards = cards().map((c) => ({ summary: text(c.children[0]), body: c.find((n) => has(n, "wb-skill-detail")).children.map(text) }));
const tier = cards()[0].find((n) => has(n, "wb-sc-3"));
out.cardOrder = tier.all((n) => has(n, "wb-band"))[0].children.flatMap((c) => c.cls().filter((x) => x === "wb-score" || x === "pui-chip"));
// a filter that matches nothing and a read with no skill
const area = tab.el.all((n) => n.tagName === "SELECT")[0];
area.value = "marketing"; area.fire("change");
out.afterArea = rowsOf().map((r) => text(r.children[0].children[1]));
console.log(JSON.stringify(out));
"""


@needs_node_here
def test_the_skills_tab_is_a_list_of_accordions_in_five_columns_with_the_score_before_the_chip(tmp_path):
    """R-53 and (a) 5: the table is a list of accordions (the chevron, the name, the version, the area, the two tiers); opened: Manifest, Runs here and the two sentences;
    in a tier the score comes first, then the band's chip, in the list and on the phone's card (M-2)."""
    got = node(tmp_path, SKILLS_R4)
    assert got["tables"] == 0, "R-53: no table on this tab"
    assert got["group"] == ["group", "Skills in scope, with their band and score on the reference model and the floor model"]
    assert got["head"] == ["true", ["", "Skill", "Version", "Area", "Reference model", "Floor model"]], "the head row names the five columns (hidden from a screen reader: each row names itself)"
    first, second, third = got["rows"]
    assert first["parts"] == ["wb-acc-chev", "wb-code wb-skill-name", "wb-muted wb-skill-ver", "wb-muted wb-skill-area", "wb-skill-tier", "wb-skill-tier"]
    assert first["cells"] == ["", "brand-voice", "1.2.0", "brand", "0.86 reliable", "0.58 watch"], "the score first, then the chip's word"
    assert second["cells"][4:] == ["0.66 watch", "- needs a test"], "an untested pair has no score: '-', never 0.00"
    assert third["cells"][4:] == ["- needs a test", "-"], "no pair for a tier: '-' alone"
    assert first["body"] == ["Manifest: yes", "Runs here: 3",
                             "Reference model: reference-model-1, adapter-a, mean 0.86, 9 runs. Cause: none.",
                             "Floor model: floor-model-1, adapter-b, mean 0.58, 9 runs. Cause: pessimistic score under 0.70."]
    assert third["body"][:2] == ["Manifest: no", "Runs here: -"] and third["body"][-1] == "Floor model: the service sent no proof for this model."
    assert first["label"].startswith("brand-voice, version 1.2.0, brand, reference model 0.86 reliable, floor model 0.58 watch"), "a row names its cells, since the head is hidden"
    assert [r["open"] for r in got["rows"]] == [False, False, False]
    assert got["order"] == ["wb-score", "pui-chip"], "the score before the chip (R-53)"
    assert got["chevron"] == ["wb-acc-chev"]
    assert got["afterToggle"] == [True, False], "opening a row of the list opens the same skill's card (one set of names)"
    assert got["keptOpen"] == [True, True, False], "an open row stays open through a read"
    assert got["cardToRow"] == [True, False]
    assert got["cards"][0]["summary"] == "brand-voice 1.2.0 · brand Manifest yes · 3 runs here Reference 0.86 reliable Floor 0.58 watch", "R-55: one card per skill, the score first"
    assert got["cards"][0]["body"] == ["Reference model: reference-model-1, adapter-a, mean 0.86, 9 runs. Cause: none.",
                                       "Floor model: floor-model-1, adapter-b, mean 0.58, 9 runs. Cause: pessimistic score under 0.70."], "the card says Manifest and Runs here in its summary: its body holds the two sentences"
    assert got["cardOrder"] == ["wb-score", "pui-chip"]
    assert got["afterArea"] == ["mkt-publish"]


NOTICES = HELPERS + r"""
import { createSkillsTab } from "@JS@/views/control-skills.js";
import { createConnectionsTab } from "@JS@/views/control-connections.js";
import { createCostsTab } from "@JS@/views/control-costs.js";
const out = {};
const shape = (n) => ({ cls: n.cls(), role: n.attrs.role, icon: Boolean(n.find((x) => has(x, "wb-icon-triangle-alert"))), title: text(n.find((x) => has(x, "wb-cnotice-title"))), lines: n.all((x) => has(x, "wb-cnotice-line")).map((x) => [text(x), x.cls().includes("mono")]) });
const skills = createSkillsTab();
skills.set({ status: "ready", data: { ...skillsData, checks: { measurement: "ok", image: "the image on this machine is not the one the evidence of 2 skill(s) was measured in" } } });
out.checks = shape(skills.el.children[0]);
out.checksFirst = [skills.el.children[0].cls().includes("wb-cnotice"), has(skills.el.children[1], "wb-legend")];
skills.set({ status: "failed", error: "the proof of x cannot be read: y" });
out.skillsFailed = shape(skills.el.children[0]);
const conn = createConnectionsTab();
conn.set({ status: "failed", error: "connections: the service did not answer in 10 s" });
out.connFailed = shape(conn.el.children[0]);
const costs = createCostsTab({ onSince() {} });
costs.set({ status: "refused", error: "since is a day: YYYY-MM-DD", agents: null, fieldValue: "2026-13-07" });
out.refused = shape(costs.el.find((n) => has(n, "wb-cnotice")));
out.refusedOrder = costs.el.children.map((c) => c.cls()[0]);
costs.set({ status: "failed", error: "costs: the store did not answer", agents: null, fieldValue: "2026-09-07" });
out.costsFailed = shape(costs.el.find((n) => has(n, "wb-cnotice")));
costs.set({ status: "loading", fieldValue: "2026-09-07" });
out.loading = [costs.el.children.at(-1).cls(), costs.el.children.at(-1).attrs["aria-busy"], text(costs.el.children.at(-1)), Boolean(costs.el.children.at(-1).find((n) => has(n, "wb-ring")))];
console.log(JSON.stringify(out));
"""


@needs_node_here
def test_the_checks_notice_date_refused_and_the_failed_read_are_the_soft_error_style_with_an_icon(tmp_path):
    """R-54 and (a) 8: the checks notice, "Date refused" and "The read failed" are the library's soft error style with an icon (R-11); loading is the dashed block with the ring."""
    got = node(tmp_path, NOTICES)
    base = ["notice", "pui-soft", "pui-error", "wb-cnotice"]
    for key in ("checks", "skillsFailed", "connFailed", "refused", "costsFailed"):
        assert got[key]["cls"] == base and got[key]["role"] == "alert" and got[key]["icon"] is True, key
    assert got["checks"]["title"] == "A check of the proof failed"
    assert [line[0] for line in got["checks"]["lines"]] == ["These skills run as not proven: on the reference model and without autonomy.", "Measurement check: ok",
                                                          "Image check: the image on this machine is not the one the evidence of 2 skill(s) was measured in"]
    assert got["checksFirst"] == [True, True], "the notice is first in the tab, above the legend"
    assert got["skillsFailed"]["title"] == "The read failed" and got["skillsFailed"]["lines"] == [["the proof of x cannot be read: y", True]], "the service's message in the mono face"
    assert got["connFailed"]["lines"] == [["connections: the service did not answer in 10 s", True]]
    assert got["refused"]["title"] == "Date refused" and got["refused"]["lines"] == [["since is a day: YYYY-MM-DD", True]]
    assert got["refusedOrder"] == ["pui-field-group", "notice"], "the field stays, the notice under it, nothing else"
    assert got["costsFailed"]["title"] == "The read failed"
    assert got["loading"][0][:2] == ["wb-empty-block", "wb-loading"] and got["loading"][1] == "true" and got["loading"][2] == "Loading the proof, costs and connections..." and got["loading"][3] is True


COSTS_R4 = HELPERS + r"""
import { createCostsTab } from "@JS@/views/control-costs.js";
const out = {};
const costs = createCostsTab({ onSince() {} });
const price = { source: "provider price page", date: "2026-09-30" };
const crow = (day, agent, runs) => ({ day, agent, model: "m", adapter: "a", runs, tokens: 10, recorded_usd: null, recomputed_usd: 1, unknown_runs: 0, price });
const data = { since: "2026-09-09", rows: [crow("2026-10-06", "engineering", 4), crow("2026-10-07", "engineering", 5), crow("2026-10-07", "marketing", 2)],
  caps: [{ agent: "engineering", max_runs_per_day: 12, max_usd_per_day: 4 }, { agent: "marketing", max_runs_per_day: 6, max_usd_per_day: 2 }, { agent: "brand", max_runs_per_day: 6, max_usd_per_day: 2 }] };
const agents = [
  { name: "engineering", runs_today: 5, usd_today: 1.87, usd_recorded: 1.4, usd_reserved: 0.47, runs_total_today: 7 },
  { name: "marketing", runs_today: 2, usd_today: 0.31, usd_recorded: 0.31, usd_reserved: 0, runs_total_today: 4, caps_in_use: { runs: true, spend: false } },
];
costs.set({ status: "ready", data, agents, fieldValue: "2026-09-09" });
out.order = costs.el.children.map((c) => c.cls().filter((x) => ["pui-field-group", "wb-caps", "wb-chart", "wb-tcard", "wb-foot"].includes(x))[0]);
const caps = costs.el.find((n) => has(n, "wb-caps"));
out.caps = { role: caps.attrs.role, label: caps.attrs["aria-label"], card: caps.cls().includes("pui-card") };
const rows = caps.all((n) => has(n, "wb-cap-row"));
out.head = [rows[0].attrs.role, rows[0].children.map((c) => [c.attrs.role, text(c)])];
const share = (row) => row.all((n) => has(n, "wb-meter-fill") || has(n, "wb-meter-reserved")).map((n) => [n.cls().filter((c) => c.startsWith("wb-meter-")).join(" "), n.props["--wb-share"]]);
out.rows = rows.slice(1).map((r) => ({ role: r.attrs.role, cells: r.children.map(text), shares: share(r), meters: r.all((n) => has(n, "wb-meter")).map((m) => m.cls()) }));
out.agentCell = [rows[1].children[0].find((n) => n.tagName === "STRONG").textContent, rows[1].children[0].find((n) => has(n, "wb-muted")).textContent];
out.cellClasses = rows[1].children.slice(1).map((c) => [c.cls(), c.children.map((x) => x.cls()[0])]);
// the words of the KPI cards, not "Reference-model runs today" and "Floor-model spend today"
out.noOldWords = !text(costs.el).includes("Reference-model") && !text(costs.el).includes("Floor-model");
// the chart's table sits inside the chart's card, under the plot
const chart = costs.el.find((n) => has(n, "wb-chart"));
out.chartParts = chart.children.map((c) => c.cls()[0]);
const acc = chart.find((n) => has(n, "wb-chart-acc"));
out.acc = [acc.cls(), text(acc.children[0]), Boolean(acc.find((n) => n.tagName === "TABLE"))];
// the runs table is in a card of its own, a table of the page's look; numbers are right-aligned
const table = costs.el.find((n) => has(n, "wb-tcard")).find((n) => n.tagName === "TABLE");
out.table = [table.cls(), table.all((n) => n.tagName === "TH" && n.cls().includes("wb-num")).map(text)];
// the agents read failed: the used amounts are "-"
costs.set({ status: "ready", data, agents: null, fieldValue: "2026-09-09" });
out.noAgents = caps.parent === null ? "replaced" : "kept";
const capsAgain = costs.el.find((n) => has(n, "wb-caps"));
out.noAgentsRows = capsAgain.all((n) => has(n, "wb-cap-row")).slice(1).map((r) => r.children.map(text));
// no cap, no caps card
costs.set({ status: "ready", data: { ...data, caps: [] }, agents, fieldValue: "2026-09-09" });
out.noCaps = costs.el.all((n) => has(n, "wb-caps")).length;
// no runs since the date: the caps (today's figures) stay above the field, then the dashed block (M-9, which supersedes A6-4: the page's co-empty frame has no caps)
costs.set({ status: "ready", data: { ...data, rows: [] }, agents, fieldValue: "2026-09-09" });
out.emptyParts = costs.el.children.map((c) => c.cls().find((x) => ["wb-caps", "pui-field-group", "wb-empty-block"].includes(x)));
// M-9: the order of the tab's children in each state; the caps are kept while a read is in flight, failed or refused, when they were read
const kinds = ["wb-caps", "pui-field-group", "wb-empty-block", "notice", "wb-chart", "wb-tcard", "wb-foot"];
const parts = (tab) => tab.el.children.map((c) => c.cls().find((x) => kinds.includes(x)));
const fresh = createCostsTab({ onSince() {} });
const states = {};
fresh.set({ status: "loading", fieldValue: "2026-09-09" });
states.loadingFirst = parts(fresh);
fresh.set({ status: "ready", data, agents, fieldValue: "2026-09-09" });
fresh.set({ status: "loading", data, agents: null, fieldValue: "2026-09-09" });
states.loading = parts(fresh);
fresh.set({ status: "failed", error: "x", data, agents: null, fieldValue: "2026-09-09" });
states.failed = parts(fresh);
fresh.set({ status: "refused", error: "since is a day: YYYY-MM-DD", agents: null, fieldValue: "" });
states.refused = parts(fresh);
fresh.set({ status: "ready", data: { ...data, caps: [] }, agents, fieldValue: "2026-09-09" });
fresh.set({ status: "loading", fieldValue: "2026-09-09" });
states.noCaps = parts(fresh);
out.states = states;
// runs only for every agent: the spend column is not drawn at all
costs.set({ status: "ready", data: { ...data, caps: data.caps.slice(1, 2) }, agents, fieldValue: "2026-09-09" });
out.runsOnly = costs.el.find((n) => has(n, "wb-caps")).cls().filter((c) => c.startsWith("is-"));
console.log(JSON.stringify(out));
"""


@needs_node_here
def test_the_costs_caps_are_rows_with_meters_and_the_chart_holds_its_table(tmp_path):
    """R-52 and (a) 6, 7, (b) 1: the caps as rows (the agent with `Runs today: n` under its name, `Runs today` and `Spend today` as a value in 600 weight over a meter, the recorded and
    reserved note under the spend); "The chart as a table" inside the chart's card, under the plot."""
    got = node(tmp_path, COSTS_R4)
    assert got["order"] == ["wb-caps", "pui-field-group", "wb-chart", "wb-tcard", "wb-foot"], "M-9: the caps card (today's figures) first, then the Since field, then what the field filters: the chart, the runs table, the footnote"
    assert got["caps"]["role"] == "table" and got["caps"]["card"] is True
    assert got["caps"]["label"].startswith("Caps by agent.") and "subscription or free credential" in got["caps"]["label"] and "metered credential" in got["caps"]["label"], "the two sentences of the cap words move to the table's name"
    assert got["head"] == ["row", [["columnheader", "Agent"], ["columnheader", "Runs today"], ["columnheader", "Spend today"]]]
    eng, mkt, brand = got["rows"]
    assert eng["role"] == "row" and eng["cells"] == ["engineering Runs today: 7", "5 / 12", "$1.87 / $4.00 $1.40 recorded · up to $0.47 reserved"]
    assert got["agentCell"] == ["engineering", "Runs today: 7"]
    assert eng["shares"] == [["wb-meter-fill", "42%"], ["wb-meter-fill", "35%"], ["wb-meter-reserved", "12%"]], "runs over their cap; the spend's recorded part and the part reserved for a run whose cost is not recorded yet"
    assert eng["meters"] == [["wb-meter"], ["wb-meter", "has-reserved"]]
    assert mkt["cells"] == ["marketing Runs today: 4", "2 / 6", ""], "a meter that is not in use for the agent has no cell content"
    assert brand["cells"] == ["brand", "- / 6", "- / $2.00"], "an agent the read has no use for: the used amounts are '-' and no note"
    assert brand["shares"] == [["wb-meter-fill", "0%"], ["wb-meter-fill", "0%"]]
    assert got["cellClasses"] == [[["wb-cap-m"], ["wb-cap-val", "wb-meter"]], [["wb-cap-m"], ["wb-cap-val", "wb-meter", "wb-muted"]]]
    assert got["noOldWords"] is True
    assert got["chartParts"] == ["wb-chart-head", "wb-plot", "wb-plot-labels", "wb-acc"], "R-52: the table is inside the chart's card, under the plot"
    assert got["acc"] == [["wb-acc", "wb-chart-acc"], "The chart as a table", True]
    assert got["table"][0] == ["pui-table", "wb-ctable", "wb-stackable", "wb-costs-table"] and got["table"][1] == ["Runs", "Tokens"]
    assert got["noAgentsRows"] == [["engineering", "- / 12", "- / $4.00"], ["marketing", "- / 6", "- / $2.00"], ["brand", "- / 6", "- / $2.00"]]
    assert got["noCaps"] == 0
    assert got["emptyParts"] == ["wb-caps", "pui-field-group", "wb-empty-block"], "M-9 (supersedes A6-4): the caps show whatever Since returns, so on 'no runs since' they stay above the field"
    assert got["states"] == {"loadingFirst": ["pui-field-group", "wb-empty-block"], "loading": ["wb-caps", "pui-field-group", "wb-empty-block"], "failed": ["wb-caps", "pui-field-group", "notice"],
                             "refused": ["wb-caps", "pui-field-group", "notice"], "noCaps": ["pui-field-group", "wb-empty-block"]}, "M-9: while loading, failed or refused the caps stay if they were read; with none read there is no card"
    assert got["runsOnly"] == ["is-runs-only"]


CONNECTIONS_R4 = HELPERS + r"""
import { createConnectionsTab } from "@JS@/views/control-connections.js";
import * as model from "@JS@/views/control-model.js";
const out = {};
const skills = (n) => Array.from({ length: n }, (_, i) => `skill-${i + 1}`);
const data = (extra = {}) => ({
  classes: [
    { class: "store:tasks", provider: "provider-a", found: true, note: null, skills: skills(2) },
    { class: "integration:web-search", provider: "provider-b", found: true, note: "chosen by name", skills: skills(5) },
    { class: "vcs:code-host", provider: "provider-c", found: true, note: null, skills: skills(4) },
    { class: "publisher:social", provider: null, found: false, note: "none", skills: [] },
  ],
  secrets: [{ name: "CODE_HOST_TOKEN", found: true, where: "the secret store" }, { name: "FLOOR_MODEL_KEY", found: false, where: null }],
  secrets_note: null, image: { name: "image:1", present: true, evidence: true }, platform: { here: "linux/arm64", evidence: "linux/arm64", same: true }, service: null, ...extra,
});
const tab = createConnectionsTab();
tab.set({ status: "ready", data: data() });
out.order = tab.el.children.map((c) => `${c.tagName}.${c.cls()[0] || ""}`);
out.heads = tab.el.all((n) => n.tagName === "H3").map((n) => [n.cls(), text(n)]);
const classRows = tab.el.all((n) => n.tagName === "TR" && n.parent.tagName === "TBODY").slice(0, 4);
out.needed = classRows.map((r) => {
  const cell = r.children[3];
  const details = cell.find((n) => n.tagName === "DETAILS");
  return { text: text(cell), disclosure: Boolean(details), cls: details ? details.cls() : null, summary: details ? [text(details.children[0]), details.children[0].attrs["aria-label"]] : null, open: details ? details.open : null };
});
out.table = tab.el.find((n) => n.tagName === "TABLE").cls();
out.card = tab.el.find((n) => has(n, "wb-tcard")).cls();
const cards = tab.el.all((n) => has(n, "wb-ccard"));
out.cards = cards.map((c) => [c.cls(), text(c)]);
out.cardsGrid = tab.el.find((n) => has(n, "wb-ccards")).cls();
tab.set({ status: "ready", data: data({ platform: { here: "linux/amd64", evidence: "linux/arm64", same: false }, service: { secret_store: "the secret store cannot be read by this process", start: "uv run x", credential: "ok", docker: "the Docker daemon did not answer", image: "ok", dispatch: "off", problems: [] } }) });
const after = tab.el.all((n) => has(n, "wb-ccard"));
out.differs = after.map((c) => [c.cls(), text(c)]);
out.serviceHead = tab.el.all((n) => n.tagName === "H3").map(text);
console.log(JSON.stringify(out));
"""


@needs_node_here
def test_needed_by_past_four_skills_is_a_disclosure_and_the_connections_cards_are_the_pages(tmp_path):
    """R-54 and (b) 2: "Needed by" past four skills is `<n> skills`, a disclosure in the theme colour with the list under the count (E-15); up to four the list stays as it was; the
    section headings, the tables' cards and the Image and Platform cards are the page's (control-room.html)."""
    got = node(tmp_path, CONNECTIONS_R4)
    assert got["order"] == ["H3.wb-sec-head", "DIV.pui-card", "H3.wb-sec-head", "DIV.pui-card", "DIV.wb-ccards"]
    assert [h[1] for h in got["heads"]] == ["Requirement classes", "Secrets (names only, never a value)", "Image", "Platform"]
    assert got["needed"][0] == {"text": "skill-1, skill-2", "disclosure": False, "cls": None, "summary": None, "open": None}
    assert got["needed"][1]["disclosure"] is True and got["needed"][1]["cls"] == ["wb-need"] and got["needed"][1]["open"] is False
    assert got["needed"][1]["summary"][0] == "5 skills" and got["needed"][1]["summary"][1] == "5 skills: skill-1, skill-2, skill-3, skill-4, skill-5", "the full list stays in the control's accessible name"
    assert got["needed"][1]["text"] == "5 skills skill-1, skill-2, skill-3, skill-4, skill-5", "opened, the list sits under the count"
    assert got["needed"][2]["disclosure"] is False and got["needed"][2]["text"] == "skill-1, skill-2, skill-3, skill-4", "four skills: the list as it was"
    assert got["needed"][3]["text"] == "-"
    assert got["table"] == ["pui-table", "wb-ctable", "wb-stackable"] and got["card"] == ["pui-card", "wb-tcard"]
    assert [c[0] for c in got["cards"]] == [["pui-card", "wb-ccard"], ["pui-card", "wb-ccard"]]
    assert got["cards"][0][1] == "Image image:1 present It is the image the evidence was measured in: yes"
    assert got["cards"][1][1] == "Platform This machine: linux/arm64 same Evidence: linux/arm64"
    assert got["cardsGrid"] == ["wb-ccards"]
    service, image, platform = got["differs"]
    assert platform[0] == ["pui-card", "wb-ccard", "is-wide"] and platform[1] == "Platform This machine: linux/amd64 · Evidence: linux/arm64 differs", "the platforms differ: the card spans the width and says both on one line"
    assert service[0][:2] == ["pui-card", "wb-ccard"] and "wb-service-card" in service[0] and image[1].startswith("Image ")
    assert got["serviceHead"] == ["Requirement classes", "Secrets (names only, never a value)", "Service", "Image", "Platform"], "the service card has its heading above it"


SCENE_R4 = HELPERS + r"""
import { sceneModel, OPENS, OPEN_OF } from "@JS@/views/control-model.js";
const out = {};
const conn = { classes: [{ class: "c", provider: "p", found: true, note: null, skills: [] }], secrets: [], image: { name: "i", present: true, evidence: true }, platform: {} };
const rack = ["rack-1", "rack-2", "rack-3"];
out.ready = ["skills", "costs", "connections"].map((tab) => sceneModel({ accepted: true, connections: conn, tab }).open);
out.failed = ["skills", "costs", "connections"].map((tab) => { const m = sceneModel({ accepted: true, connections: null, failed: true, tab }); return [m.open, m.ready, m.failed, m.leds.every((l) => l === "off"), m.bars.every((b) => b === 0)]; });
out.loading = sceneModel({ accepted: true, connections: null, tab: "connections" }).open;
out.notAccepted = sceneModel({ accepted: false, connections: conn, failed: true, tab: "connections" }).open;
out.flag = [sceneModel({ accepted: true, connections: conn }).failed, sceneModel({ accepted: true, connections: null, failed: true }).failed];
// OPEN_OF is the grouping of OPENS: one list, not two that must agree
const grouped = {};
for (const [object, tab] of Object.entries(OPENS)) (grouped[tab] ||= []).push(object);
out.derived = [JSON.stringify(OPEN_OF) === JSON.stringify(grouped), Object.isFrozen(OPEN_OF), Object.isFrozen(OPEN_OF.connections)];
out.rack = rack;
console.log(JSON.stringify(out));
"""


@needs_node_here
def test_the_racks_keep_their_brackets_on_a_failed_read_and_the_open_of_map_is_derived_from_opens(tmp_path):
    """B3-5: the page draws the racks' brackets on "A read that failed"; the code drew none because a failed read counted as not ready. The view tells the model that the read failed. B3's review: `OPEN_OF` is derived from `OPENS`."""
    got = node(tmp_path, SCENE_R4)
    assert got["ready"] == [["console"], ["wall"], got["rack"]]
    assert got["failed"] == [[["console"], False, True, True, True], [["wall"], False, True, True, True], [got["rack"], False, True, True, True]], \
        "a failed read keeps the open tab's object marked; the lights stay off and the bars empty (nothing was read)"
    assert got["loading"] == [] and got["notAccepted"] == [], "the page draws no brackets while loading or while the project is not accepted, a failed read or not"
    assert got["flag"] == [False, True]
    assert got["derived"] == [True, True, True]


SCENE_BUILD = r"""
import * as THREE from "@JS@/three.js";
import { createKit } from "@JS@/scene/kit.js";
import { sceneModel } from "@JS@/views/control-model.js";
import { buildServer } from "@JS@/views/control-scene.js";
const c = (hex) => new THREE.Color(hex);
const T = { border: c(0x101010), theme: c(0x2020f0), success: c(0x10f010), error: c(0xf01010), emphasis: c(0x303030), text: c(0x404040), warn: c(0xf0a010), textMuted: c(0x505050) };
const palette = { dark: false, T, mix: (a, b, t) => a.clone().lerp(b, t), bg: c(0xfafafa), shell: c(0xf8f8f8), ink: c(0x202020), metal: c(0x606060), deskTop: c(0xd0d0d0), screenOff: c(0x181818), leafA: c(0x80c080), trunk: c(0x806040) };
const out = {};
const kit = createKit(palette);
const failed = buildServer(kit, sceneModel({ accepted: true, connections: null, failed: true, tab: "connections" }));
const loading = buildServer(kit, sceneModel({ accepted: true, connections: null, tab: "connections" }));
out.failed = [failed.open, failed.noMarks, failed.text(sceneModel({ accepted: true, connections: null, failed: true, tab: "connections" })).noMarks];
out.loading = [loading.open, loading.noMarks];
out.structureSame = JSON.stringify(buildServer.structure(sceneModel({ accepted: true, connections: null, failed: true, tab: "costs" }))) === JSON.stringify(buildServer.structure(sceneModel({ accepted: true, connections: null, tab: "costs" })));
out.moves = failed.text(sceneModel({ accepted: true, connections: null, failed: true, tab: "costs" })).open;
console.log(JSON.stringify(out));
"""


@needs_node_here
def test_the_server_room_builder_marks_the_open_tabs_object_on_a_failed_read_without_building_again(tmp_path):
    got = node(tmp_path, SCENE_BUILD)
    assert got["failed"] == [["rack-1", "rack-2", "rack-3"], False, False], "the builder and its words agree: the brackets of a failed read are not suppressed"
    assert got["loading"] == [[], True]
    assert got["structureSame"] is True, "a failed read is a change of words (the brackets), not of the room: nothing is built again"
    assert got["moves"] == ["wall"]


VIEW_R4 = HELPERS + r"""
import { createControlView } from "@JS@/views/control.js";
const answers = {};
globalThis.fetch = async (url, init) => {
  const path = new URL(url, "http://127.0.0.1").pathname.replace("/api/v1/projects/aaaaaaaaaaaa/", "");
  const found = answers[path];
  if (!found) return { ok: false, status: 404, json: async () => ({ error: "not_found", message: "no route" }) };
  return { ok: found.status === undefined || found.status < 400, status: found.status || 200, json: async () => found.body };
};
answers.skills = { body: skillsData };
answers.costs = { body: { since: "2026-09-08", rows: [], caps: [] } };
answers.agents = { body: { agents: [] } };
answers.connections = { status: 500, body: { error: "internal", message: "connections: the secret store did not answer within 5 s" } };
const frame = { main: new FakeNode("main"), sceneHost: new FakeNode("div"), noticeBox: new FakeNode("div"), insets: () => ({}), sceneUnavailable() {} };
const view = createControlView(frame);
const sub = () => text(view.el.find((n) => has(n, "wb-panel-sub")));
const out = { start: sub() };
const state = (tab, extra = {}) => ({ loaded: true, known: true, accepted: true, projectId: "aaaaaaaaaaaa", projectName: "northwind-shop", tab, reload: 1, ...extra });
view.update(state("skills")); await settle();
out.skills = sub();
view.update(state("costs")); out.costs = sub();
view.update(state("connections")); out.connections = sub();
view.update(state("skills")); out.back = sub();
view.update(state("skills", { projectName: "" })); out.noName = sub();
out.tabs = view.el.find((n) => has(n, "wb-tablist")).all((n) => n.attrs.role === "tab").length;
out.noDash = !JSON.stringify([...view.el.walk()].map((n) => n.textContent)).includes("undefined");
console.log(JSON.stringify(out));
"""


@needs_node_here
def test_the_sub_line_follows_the_tab_and_names_the_project(tmp_path):
    """R-50 and E-10: "Skills, costs and connections of <project>" on Skills and Costs, "of this machine" on Connections, because skills and costs are the project's and only the connections the machine's."""
    got = node(tmp_path, VIEW_R4)
    assert got["start"] == "Skills, costs and connections of this project", "before the project is known: no name is made up"
    assert got["skills"] == "Skills, costs and connections of northwind-shop" and got["costs"] == got["skills"]
    assert got["connections"] == "Skills, costs and connections of this machine"
    assert got["back"] == got["skills"] and got["noName"] == "Skills, costs and connections of this project"
    assert got["tabs"] == 3 and got["noDash"] is True


# --- the stylesheet: what the page draws, by the page's own words -------------------------------------------------------------------


def rules(css: str, selector: str) -> list[str]:
    """The declaration blocks of every rule whose selector list contains `selector` exactly."""
    found = []
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for match in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
        names = [s.strip() for s in match.group(1).split(",")]
        if selector in names:
            found.append(match.group(2))
    return found


def control_css() -> str:
    return css_file("control")


def test_the_panel_is_700_px_and_the_closed_card_under_it_is_as_wide_and_the_tabs_fill_the_panel():
    """R-50 and (a) 1, 4, 9: the panel 700 px, the closed "Waiting for you" as wide (A1-4 set it), no tracking bar, the three tabs a segmented control filling the panel's width."""
    css = interface_css()
    own = control_css()
    assert re.search(r"--wb-panel-wide: 700px;", css)
    assert re.search(r'\.wb-frame\[data-screen="control"\] \.wb-waiting \{ width: var\(--wb-panel-wide\); \}', own), "the closed card is as wide as the panel"
    assert rules(own, '.wb-frame[data-screen="control"] .wb-track') and "display: none" in rules(own, '.wb-frame[data-screen="control"] .wb-track')[0], "no tracking bar on this screen"
    fill = rules(own, ".wb-control .wb-tablist .wb-tab")
    assert fill and "flex: 1 1 0" in fill[0] and "justify-content: center" in fill[0], "the tabs fill the panel's width in equal parts"
    head = rules(own, '.wb-frame[data-screen="control"] .wb-panel-head')
    assert head and "border-bottom: 0" in head[0], "no line under the head (R-33)"
    assert 'panel.sub' in (VIEWS / "control.js").read_text(encoding="utf-8")


def test_the_chart_series_are_the_brand_colour_at_38_percent_with_a_1_px_border_and_the_muted_neutral_by_token():
    """R-52 and (b) 3: the second series is the brand colour mixed to 38 percent with a 1 px border (E-8), the third the muted neutral, by token."""
    own = control_css()
    tint = re.findall(r"--wb-tint-series: ([^;]+);", own)
    assert tint == ["color-mix(in srgb, var(--pui-theme) 38%, var(--wb-raised))"]
    assert re.search(r"\.wb-series-2 \{ --wb-series: var\(--wb-tint-series\); \}", own) and re.search(r"\.wb-series-3 \{ --wb-series: var\(--pui-muted\); \}", own)
    outline = " ".join(rules(own, ".wb-seg.wb-series-2") + rules(own, ".wb-swatch.wb-series-2"))
    assert "var(--pui-border)" in outline, "the second series has a 1 px border in the border token, on its segments and its swatch"


def test_the_notice_the_meters_the_accordion_and_the_phone_follow_the_page_in_the_screens_own_stylesheet():
    """R-54, R-52, R-53, R-55: the soft notice with an icon, the caps rows' meters, the accordion rows and the phone's cards are built scoped in control.css (P-2)."""
    own = control_css()
    css = interface_css()
    for selector in (".wb-cnotice", ".wb-cap-row", ".wb-skill-sum", ".wb-skill-head", ".wb-need > summary", ".wb-ccards", ".wb-icon-triangle-alert"):
        assert rules(own, selector), f"control.css draws {selector}"
    assert "grid-template-columns: auto minmax(0, 1fr)" in rules(own, ".wb-cnotice")[0]
    assert "var(--pui-theme)" in rules(own, ".wb-need > summary")[0], "the disclosure is in the theme colour"
    assert "grid-template-columns: minmax(0, 1fr) 190px 190px" in rules(own, ".wb-cap-row")[0]
    assert re.search(r'url\("\.\./icons/triangle-alert\.svg"\)', css), "the notice's icon is a clean file of the icon set"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", own), "no colour literal"
    phone = own[own.index("@media (max-width: 899px) {\n  .wb-control-content"):]  # M-3: the phone's layout runs up to 899 px
    assert ".wb-skill-list { display: none; }" in phone.replace("\n", " ") or re.search(r"\.wb-skill-list \{ display: none; \}", phone), "on a phone the list gives way to one card per skill"
    assert re.search(r"\.wb-skill-cards \{ display: grid;", phone)


def test_a_focused_summary_has_its_ring_inside_the_row_and_the_closed_card_follows_the_panel_in_the_in_between_band():
    """Review nits 3 and 4 of PR 294: the lists clip their corners, so a summary draws its ring inside; at 900 to 1023 px the panel is narrower than 700 px and the closed
    "Waiting for you" is as wide as the panel (R-50)."""
    own = control_css()
    for selector in (".wb-skill-row > summary:focus-visible", ".wb-filters > summary:focus-visible", ".wb-chart-acc > summary:focus-visible", ".wb-need > summary:focus-visible"):
        found = rules(own, selector)
        assert found and "outline: 2px solid var(--pui-theme)" in found[0] and "outline-offset: -2px" in found[0], selector
    band = own[own.index("@media (min-width: 900px) and (max-width: 1023px)"):]
    band = band[:band.index("\n}")]
    panel = re.search(r'\.wb-frame\[data-screen="control"\] \.wb-panel-wide, \.wb-frame\[data-screen="control"\] \.wb-waiting \{ width: (calc\([^;]+\)); \}', band)
    assert panel and panel.group(1) == "calc(100vw - var(--wb-kpi-w) - var(--wb-edge) * 3)", "the panel and the closed card take the same width in the band"
    assert "wb-footnote" not in own


FAILED_LABEL = HELPERS + r"""
import { sceneModel } from "@JS@/views/control-model.js";
const conn = { classes: [], secrets: [], image: { name: "i", present: true, evidence: true }, platform: {} };
console.log(JSON.stringify([sceneModel({ accepted: true, connections: null, failed: true }).label, sceneModel({ accepted: true, connections: null }).label,
  sceneModel({ accepted: false, connections: null, failed: true }).label, sceneModel({ accepted: true, connections: conn }).label]));
"""


@needs_node_here
def test_the_scene_says_the_connections_were_not_read_when_the_read_failed(tmp_path):
    """A6-13: a failed read says nothing was read; the page's label ("... 0 connections missing") would claim nothing is missing."""
    got = node(tmp_path, FAILED_LABEL)
    assert got == ["Server room, connections not read", "Server room, loading", "Server room, waiting for the configuration to be accepted",
                   "Server room: 3 racks, 0 connections missing, runs of the last 7 days"]


# --- R4-A6b: the Since field is a date (M-8, A-47) ---------------------------------------------------------------------------------

SINCE_DATE = HELPERS + r"""
import { createCostsTab } from "@JS@/views/control-costs.js";
const sent = [];
const costs = createCostsTab({ onSince: (value) => sent.push(value) });
const price = { source: "page", date: "2026-09-30" };
const data = { since: "2026-09-09", rows: [{ day: "2026-10-07", agent: "engineering", model: "m", adapter: "a", runs: 2, tokens: 5, recorded_usd: null, recomputed_usd: 1, unknown_runs: 0, price }], caps: [] };
costs.set({ status: "ready", data, agents: [], fieldValue: "2026-09-09" });
const input = costs.el.find((n) => n.tagName === "INPUT");
const label = costs.el.find((n) => n.tagName === "LABEL");
const out = { type: input.getAttribute("type"), label: text(label), attrs: Object.keys(input.attrs).sort(), value: input.value, cls: input.cls() };
// a date chosen is sent as the value, YYYY-MM-DD; cleared, it sends what an empty field sent before: the empty text
input.value = "2026-10-01"; input.fire("change");
input.value = ""; input.fire("change");
out.sent = sent;
// a re-read keeps the field's value and the same node (the one the person is in keeps its focus)
costs.set({ status: "loading", data, agents: null, fieldValue: "2026-10-01" });
costs.set({ status: "ready", data, agents: [], fieldValue: "2026-10-01" });
out.kept = [input.value, input.parent !== null, input.dropped || 0];
// a refusal: the field keeps what was chosen, is marked invalid and described by the notice
costs.set({ status: "refused", error: "since is a day: YYYY-MM-DD", agents: null, fieldValue: "" });
out.refused = [input.value, input.getAttribute("aria-invalid"), input.getAttribute("aria-describedby"), costs.el.find((n) => n.attrs.id === "wb-since-notice") !== null];
costs.set({ status: "ready", data, agents: [], fieldValue: "2026-10-01" });
out.cleared = [input.getAttribute("aria-invalid"), input.getAttribute("aria-describedby")];
console.log(JSON.stringify(out));
"""


@needs_node_here
def test_the_since_field_is_a_date_input_with_the_same_label_trigger_and_read(tmp_path):
    """M-8, A-47: `input type="date"`, labelled "Since"; a change sends its value (always YYYY-MM-DD or empty); the notice's description and the value through a re-read stay;
    no `min` and no `max`."""
    got = node(tmp_path, SINCE_DATE)
    assert got["type"] == "date" and got["label"] == "Since" and got["value"] == "2026-09-09"
    assert "min" not in got["attrs"] and "max" not in got["attrs"] and "spellcheck" not in got["attrs"] and "placeholder" not in got["attrs"]
    assert got["sent"] == ["2026-10-01", ""], "a date is sent as the value; an empty field sends the empty text, as it did"
    assert got["kept"] == ["2026-10-01", True, 0]
    assert got["refused"] == ["", "true", "wb-since-notice", True]
    assert got["cleared"] == [None, None]


def test_the_date_field_follows_the_colour_mode_through_color_scheme_scoped_to_the_field():
    """M-8: the library sets `color-scheme` on the root from its mode attribute, and the page's mode button sets that attribute; the field inherits it so the browser's picker and
    its calendar icon follow the mode (a scoped rule makes it explicit); same height as the other fields."""
    own = control_css()
    found = rules(own, '.wb-since input[type="date"]')
    assert found and "color-scheme: inherit" in found[0] and "height: 31.5px" in found[0]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", own)
    library = (INTERFACE / "vendor" / "perfectui" / "css" / "core.css").read_text(encoding="utf-8")
    assert "[data-pui-mode=light]{color-scheme:light}" in library and "[data-pui-mode=dark]{color-scheme:dark}" in library


CLEARED = HELPERS + r"""
import { createControlView } from "@JS@/views/control.js";
const calls = [];
globalThis.fetch = async (url, init) => {
  const u = new URL(url, "http://127.0.0.1");
  const path = u.pathname.replace("/api/v1/projects/aaaaaaaaaaaa/", "");
  calls.push(path + u.search);
  const bad = u.searchParams.has("since") && u.searchParams.get("since") === "";
  const body = { skills: skillsData, agents: { agents: [] }, connections: { classes: [], secrets: [], image: {}, platform: {} },
    costs: { since: "2026-09-10", rows: [], caps: [] } }[path];
  if (bad) return { ok: false, status: 400, json: async () => ({ error: "usage", message: "since is a day: YYYY-MM-DD" }) };
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body || { error: "not_found", message: "x" } };
};
const frame = { main: new FakeNode("main"), sceneHost: new FakeNode("div"), noticeBox: new FakeNode("div"), insets: () => ({}), sceneUnavailable() {} };
const view = createControlView(frame);
view.update({ loaded: true, known: true, accepted: true, projectId: "aaaaaaaaaaaa", projectName: "x", tab: "costs", reload: 1 });
await settle();
const panel = view.el.find((n) => n.attrs.id === "wb-tabpanel-costs");
const input = panel.find((n) => n.tagName === "INPUT");
const before = calls.length;
input.value = ""; input.fire("change");
await settle();
console.log(JSON.stringify({ calls: calls.slice(before), notice: panel.all((n) => has(n, "wb-cnotice")).length, text: text(panel).includes("Date refused"), value: input.value, invalid: input.getAttribute("aria-invalid") }));
"""


@needs_node_here
def test_a_cleared_since_date_reads_the_default_window_and_shows_no_refusal(tmp_path):
    """M-8, decided by the supervisor for A6b-3: "empty means no date": the read goes without `since`, the service has nothing to refuse, and the field shows the window's first day."""
    got = node(tmp_path, CLEARED)
    assert got["calls"] == ["costs", "agents"] or got["calls"] == ["agents", "costs"], "the read without a query (no `since=`), with the agents read that feeds the caps"
    assert got["notice"] == 0 and got["text"] is False and got["invalid"] is None
    assert got["value"] == "2026-09-10", "the field shows the operation's own window"
