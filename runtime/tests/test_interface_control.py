"""Tests of the Control room of the local interface (interface/js/views/control*.js). No browser and no model: the pure
module (the band chip, the score that is never 0.00 when it is null, the same/differs chip, the chart and its table, the
filters, the cost words) runs under Node when it is installed, and so do the three tabs and the whole view, built under a fake
document with a fake `fetch` standing in for the service (so the reads the screen makes, the refused date, a failed read of one
tab and the rule that a secret is a name and never a value are checked end to end). The page itself was looked at in a browser
pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_control.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st
from interface_css import interface_css

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
VIEWS = JS / "views"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the pure modules are tested only by their text")


def run_node(tmp_path: Path, body: str) -> dict:
    """Run `body` (an ES module that prints one JSON line) with Node and return what it printed."""
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- the pure module -----------------------------------------------------------------------------------------------------------

MODEL_SCRIPT = r"""
import * as m from "@JS@/views/control-model.js";

const pair = (tier, band, score, extra = {}) => ({ tier, model: tier === "strong" ? "reference-model-1" : "floor-model-1", adapter: tier === "strong" ? "adapter-a" : "adapter-b", band, cause: null, score, mean: score, runs: 9, ...extra });
const skill = (name, area, strong, floor, extra = {}) => ({ name, version: "1.0.0", area, manifest: true, runs_here: 0, proof: [strong, floor], ...extra });
const skills = [
  skill("brand-voice", "brand", pair("strong", "reliable", 0.8657), pair("floor", "watch", 0.58, { cause: "pessimistic score under 0.70" })),
  skill("brand-identity", "brand", pair("strong", "watch", 0.66), pair("floor", "needs a test", null, { mean: null, runs: 0, cause: "no evidence on this model" })),
  skill("mkt-publish", "marketing", pair("strong", "reliable", 1), pair("floor", "needs a test", null, { mean: null, runs: 0 }), { manifest: false }),
];
const out = {};
// the chips: the library's classes by band, the score to two decimals, "-" for a null score (never 0.00)
out.chips = skills.map((s) => ["strong", "floor"].map((t) => { const c = m.chipOf(s, t); return [c.band, c.className, c.score]; }));
out.noPair = m.chipOf({ proof: [] }, "strong");
out.oddBand = m.bandClass("surprise");
out.scores = [m.scoreText(0), m.scoreText(0.126), m.scoreText(null), m.scoreText(undefined), m.scoreText("0.5"), m.scoreText(NaN)];
// the filters narrow the rows: area, band on either tier, the name case-insensitively
out.areas = m.areasOf(skills);
out.byArea = m.filterSkills(skills, { area: "brand" }).map((s) => s.name);
out.byBandReliable = m.filterSkills(skills, { band: "reliable" }).map((s) => s.name);
out.byBandWatch = m.filterSkills(skills, { band: "watch" }).map((s) => s.name);
out.byBandNeeds = m.filterSkills(skills, { band: "needs a test" }).map((s) => s.name);
out.byName = m.filterSkills(skills, { name: "  VOICE " }).map((s) => s.name);
out.byAll = m.filterSkills(skills, { area: "brand", band: "watch", name: "ident" }).map((s) => s.name);
out.none = m.filterSkills(skills, { name: "zzz" }).length;
// the open row: two sentences from the pairs; a null cause is "none"; a null mean is "-"
out.detail = m.detailLines(skills[0]);
out.detailUntested = m.detailLines(skills[1]);
out.detailOneRun = m.detailLine({ proof: [pair("strong", "watch", 0.5, { runs: 1 })] }, "strong", "Reference model");
out.detailMissing = m.detailLine({ proof: [] }, "floor", "Floor model");
out.manifest = [m.manifestText(skills[0]), m.manifestText(skills[2]), m.manifestText({})];
// the notice: shown when either check is not ok, both lines whole
out.noticeOk = m.checksNotice({ measurement: "ok", image: "ok" });
out.noticeImage = m.checksNotice({ measurement: "ok", image: "the image on this machine is not the one the evidence of 2 skill(s) was measured in" });
out.noticeMeasure = m.checksNotice({ measurement: "the gate file changed", image: "ok" });
out.noticeNone = m.checksNotice(undefined);
// the platform chip follows `same`: true same, false differs, null no chip; the page states no consequence
const plat = (same) => m.platformCard({ platform: { machine: "arm64", evidence: "linux/arm64", here: same === false ? "linux/amd64" : "linux/arm64", same } });
out.platform = [true, false, null].map((same) => { const p = plat(same); return [p.chip, p.tone, p.differs, p.here, p.evidence]; });
out.platformUnknown = m.platformCard({ platform: { machine: null, evidence: null, here: null, same: null } });
out.platformMissing = m.platformCard({});
out.image = [{ name: "wb:1", present: true, evidence: true }, { name: "wb:1", present: true, evidence: false }, { name: "wb:1", present: true, evidence: null }, { name: null, present: false, evidence: null }]
  .map((image) => { const c = m.imageCard({ image }); return [c.name, c.chip, c.tone, c.sentence]; });
// connections rows: a provider or "no provider found", needed-by whole, a secret is a name, a status and a place
out.classes = m.classRows({ classes: [{ class: "publisher:social", provider: null, found: false, note: "none", skills: ["mkt-publish", "mkt-engage"] }, { class: "integration:vcs", provider: "github", found: true, note: null, skills: ["eng-code-review"] }] });
out.secrets = m.secretRows({ secrets: [{ name: "CODE_HOST_TOKEN", found: true, where: "secret store", value: "never", masked: "xxx", length: 40 }, { name: "FLOOR_MODEL_KEY", found: false, where: null }] });
out.secretNames = out.secrets.map((r) => m.secretName(r));
// costs words
const row = (day, agent, runs, extra = {}) => ({ day, agent, model: "m", adapter: "a", runs, tokens: 1000 * runs, recorded_usd: null, recomputed_usd: 1.5, unknown_runs: 0, price: { source: "provider price page", date: "2026-09-30" }, ...extra });
out.recorded = [m.recordedCell(row("d", "x", 1)), m.recordedCell(row("d", "x", 1, { recorded_usd: 1.87 })), m.recordedCell(row("d", "x", 1, { recorded_usd: 0 }))];
out.recomputed = [
  m.recomputedCell(row("d", "x", 1, { recomputed_usd: 3.84 })),
  m.recomputedCell(row("d", "x", 1, { recomputed_usd: null, price: null })),
  m.recomputedCell(row("d", "x", 1, { recomputed_usd: null, unknown_runs: 1 })),
  m.recomputedCell(row("d", "x", 1, { recomputed_usd: null, unknown_runs: 3 })),
];
out.tokens = [m.tokensText(412300), m.tokensText(null), m.tokensText(0)];
out.agentLabel = [m.agentLabel(null), m.agentLabel("brand")];
out.newest = m.newestFirst([row("2026-10-06", "b", 1), row("2026-10-07", "a", 1), row("2026-10-06", "a", 1), row("2026-10-07", "b", 1)]).map((r) => `${r.day} ${r.agent}`);
out.footnote = m.footnote([row("d", "x", 1)]);
out.footnoteTwo = m.footnote([row("d", "x", 1), row("d", "y", 1, { price: { source: "other page", date: "2026-10-01" } })]);
out.footnoteNone = m.footnote([row("d", "x", 1, { price: null })]);
out.caps = m.capsLine([{ agent: "engineering", max_runs_per_day: 12, max_usd_per_day: 4 }, { agent: "marketing", max_runs_per_day: 6, max_usd_per_day: 3.5 }], [{ name: "engineering", runs_today: 5, usd_today: 1.87 }]);
out.capsNoAgents = m.capsLine([{ agent: "engineering", max_runs_per_day: 12, max_usd_per_day: 4 }], null).text;
out.capsNone = m.capsLine([], []);
// the chart: seven days up to the newest, never before `since`, a day with no runs an empty column, the scale the largest day
const rows = [
  row("2026-10-01", "engineering", 3), row("2026-10-01", "marketing", 1), row("2026-10-02", "engineering", 5), row("2026-10-04", "engineering", 6),
  row("2026-10-04", "brand", 2), row("2026-10-07", "engineering", 9), row("2026-10-07", "marketing", 2), row("2026-10-07", "brand", 1),
];
const chart = m.chartOf(rows, "2026-09-07");
out.chart = {
  days: chart.days.map((d) => [d.day, d.label, d.total, d.segments.map((s) => [s.series, s.runs])]),
  series: chart.series.map((s) => [s.key, s.className, s.runs]),
  max: chart.max, head: chart.head, body: chart.body,
  tops: chart.days.map((d) => Math.round(d.segments.reduce((sum, s) => sum + s.height, 0))),
  engineeringFirst: chart.days[6].segments[0].base, engineeringHeight: Math.round(chart.days[6].segments[0].height),
};
out.chartSince = m.chartOf(rows, "2026-10-05").days.map((d) => d.day);
out.chartOther = (() => {
  const many = ["a", "b", "c", "d", "e"].map((a, i) => row("2026-10-07", a, 10 - i));
  const c = m.chartOf(many, "2026-09-07");
  return { series: c.series.map((s) => [s.key, s.className, s.runs]), head: c.head, body: c.body };
})();
out.chartNone = [m.chartOf([], "2026-10-01"), m.chartOf([row("not a day", "x", 1)], null)];
out.chartNullAgent = m.chartOf([row("2026-10-07", null, 2)], null).head;
out.title = m.columnTitle(chart.days[6]);
out.labels = [m.dayLabel("2026-10-07"), m.dayLabel("2026-01-01"), m.addDays("2026-03-01", -1), m.addDays("2026-12-31", 1)];
out.tabs = [m.tabOf("costs"), m.tabOf("connections"), m.tabOf("nope"), m.tabOf(null), m.TABS.map((t) => t[1])];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_control_models_chips_filters_notice_platform_chart_and_words_follow_the_handoff(tmp_path):
    got = run_node(tmp_path, MODEL_SCRIPT)
    ok, muted, error = "pui-chip pui-success pui-soft", "pui-chip pui-muted pui-soft", "pui-chip pui-error pui-soft"
    assert got["chips"] == [
        [["reliable", ok, "0.87"], ["watch", muted, "0.58"]],
        [["watch", muted, "0.66"], ["needs a test", error, "-"]],
        [["reliable", ok, "1.00"], ["needs a test", error, "-"]],
    ], "the band is the operation's word with the library's class; a score is two decimals; an untested pair has no score: '-', never 0.00"
    assert got["noPair"] is None and got["oddBand"] == muted
    assert got["scores"] == ["0.00", "0.13", "-", "-", "-", "-"], "only a number is a score (a real 0 stays 0.00; a string, null and NaN are '-')"
    assert got["areas"] == ["brand", "marketing"]
    assert got["byArea"] == ["brand-voice", "brand-identity"] and got["none"] == 0
    assert got["byBandReliable"] == ["brand-voice", "mkt-publish"], "a band matches either tier"
    assert got["byBandWatch"] == ["brand-voice", "brand-identity"] and got["byBandNeeds"] == ["brand-identity", "mkt-publish"]
    assert got["byName"] == ["brand-voice"] and got["byAll"] == ["brand-identity"]
    assert got["detail"] == [
        "Reference model: reference-model-1, adapter-a, mean 0.87, 9 runs. Cause: none.",
        "Floor model: floor-model-1, adapter-b, mean 0.58, 9 runs. Cause: pessimistic score under 0.70.",
    ]
    assert got["detailUntested"][1] == "Floor model: floor-model-1, adapter-b, mean -, 0 runs. Cause: no evidence on this model."
    assert got["detailOneRun"] == "Reference model: reference-model-1, adapter-a, mean 0.50, 1 run. Cause: none."
    assert got["detailMissing"] == "Floor model: the service sent no proof for this model."
    assert got["manifest"] == ["yes", "no", "no"]
    assert got["noticeOk"] is None and got["noticeNone"] is None, "the notice is hidden when both checks are ok"
    assert got["noticeImage"] == {
        "title": "A check of the proof failed",
        "sentence": "These skills run as not proven: on the reference model and without autonomy.",
        "lines": ["Measurement check: ok", "Image check: the image on this machine is not the one the evidence of 2 skill(s) was measured in"],
    }
    assert got["noticeMeasure"]["lines"] == ["Measurement check: the gate file changed", "Image check: ok"], "either check shows it; both lines are always printed"
    assert got["platform"] == [["same", "pui-success", False, "linux/arm64", "linux/arm64"], ["differs", "pui-warn", True, "linux/amd64", "linux/arm64"], [None, "pui-warn", False, "linux/arm64", "linux/arm64"]], \
        "same true is 'same', false is 'differs', null is no chip; here and evidence are shown"
    assert got["platformUnknown"] == {"here": "not known", "evidence": "not known", "chip": None, "tone": "pui-warn", "differs": False}
    assert got["platformMissing"]["chip"] is None
    assert got["image"] == [
        ["wb:1", "present", "pui-success", "It is the image the evidence was measured in: yes"],
        ["wb:1", "present", "pui-success", "It is the image the evidence was measured in: no"],
        ["wb:1", "present", "pui-success", "It is the image the evidence was measured in: not known"],
        ["-", "missing", "pui-error", "It is the image the evidence was measured in: not known"],
    ]
    # R-54, E-15: the row also carries the skills as a list and their count (the tab shows `<n> skills` as a disclosure past four) and whether a provider exists
    assert got["classes"][0] == {"class": "publisher:social", "provider": "no provider found", "provided": False, "found": False, "status": "missing", "needed": "mkt-publish, mkt-engage",
                                 "skills": ["mkt-publish", "mkt-engage"], "count": 2, "note": "none"}
    assert got["classes"][1]["provider"] == "github" and got["classes"][1]["status"] == "found"
    assert got["secrets"] == [{"name": "CODE_HOST_TOKEN", "found": True, "status": "found", "where": "secret store"},
                              {"name": "FLOOR_MODEL_KEY", "found": False, "status": "missing", "where": "-"}], \
        "a secret row holds a name, a status and a place: never a value, a masked value or a length"
    assert got["secretNames"] == ["CODE_HOST_TOKEN, found, in the secret store", "FLOOR_MODEL_KEY, missing"]
    assert got["recorded"] == [{"text": "not recorded", "muted": True}, {"text": "$1.87", "muted": False}, {"text": "$0.00", "muted": False}]
    assert got["recomputed"] == [{"text": "$3.84", "muted": False}, {"text": "no price", "muted": True}, {"text": "unknown (1 run)", "muted": True}, {"text": "unknown (3 runs)", "muted": True}]
    assert got["tokens"] == ["412,300", "-", "0"] and got["agentLabel"] == ["no agent", "brand"]
    assert got["newest"] == ["2026-10-07 a", "2026-10-07 b", "2026-10-06 b", "2026-10-06 a"], "newest day first; within a day the operation's order stays"
    assert got["footnote"] == "Recomputed from token counts and the prices in the project's configuration (source: provider price page, 2026-09-30). A run whose usage is unknown shows unknown and is counted."
    assert "(source: provider price page, 2026-09-30; other page, 2026-10-01)" in got["footnoteTwo"]
    assert "source:" not in got["footnoteNone"] and "A model with no price shows no price." in got["footnoteNone"]
    assert got["caps"]["text"] == "Caps · engineering: runs 5 / 12, spend $1.87 / $4.00; marketing: runs - / 6, spend - / $3.50"
    assert "subscription or free credential" in got["caps"]["title"] and "metered credential" in got["caps"]["title"]
    assert got["capsNoAgents"] == "Caps · engineering: runs - / 12, spend - / $4.00" and got["capsNone"] is None
    chart = got["chart"]
    assert [d[0] for d in chart["days"]] == [f"2026-10-0{n}" for n in range(1, 8)], "seven days up to the newest day with rows, an empty column for a day with none"
    assert [d[1] for d in chart["days"]][0] == "Oct 1" and [d[2] for d in chart["days"]] == [4, 5, 0, 8, 0, 0, 12]
    assert chart["days"][3][3] == [["engineering", 6], ["brand", 2]] and chart["days"][2][3] == [], "the largest series is the lowest segment; no segment for no runs"
    assert chart["series"] == [["engineering", "wb-series-1", 23], ["brand", "wb-series-2", 3], ["marketing", "wb-series-3", 3]]
    assert chart["max"] == 12 and chart["tops"] == [33, 42, 0, 67, 0, 0, 100], "the scale is the largest day's total"
    assert chart["engineeringFirst"] == 0 and chart["engineeringHeight"] == 75
    assert chart["head"] == ["Day", "engineering", "brand", "marketing"]
    assert chart["body"][6] == ["Oct 7", 9, 1, 2] and chart["body"][2] == ["Oct 3", 0, 0, 0], "the table holds the same numbers as the chart"
    assert got["chartSince"] == ["2026-10-05", "2026-10-06", "2026-10-07"], "never before since"
    assert got["chartOther"]["series"] == [["a", "wb-series-1", 10], ["b", "wb-series-2", 9], ["c", "wb-series-3", 8], ["other", "wb-series-other", 13]]
    assert got["chartOther"]["head"] == ["Day", "a", "b", "c", "other"] and got["chartOther"]["body"][-1] == ["Oct 7", 10, 9, 8, 13] and len(got["chartOther"]["body"]) == 7
    assert got["chartNone"] == [None, None] and got["chartNullAgent"] == ["Day", "no agent"]
    assert got["title"] == "Oct 7: 12 runs (engineering 9, brand 1, marketing 2)"
    assert got["labels"] == ["Oct 7", "Jan 1", "2026-02-28", "2027-01-01"]
    assert got["tabs"] == ["costs", "connections", "skills", "skills", ["Skills", "Costs", "Connections"]]


# --- the three tabs and the whole view, under a fake document and a fake service --------------------------------------------------

FAKE_DOM = r"""
class FakeText { constructor(data) { this.data = String(data); this.parent = null; } get textContent() { return this.data; } }
class FakeNode {
  constructor(tag, ns = null) {
    this.tagName = tag.toUpperCase(); this.ns = ns; this.attrs = {}; this.children = []; this.parent = null; this.listeners = {};
    this.dataset = {}; this.props = {}; this.style = { setProperty: (name, value) => { if (name !== "--wb-share") throw new Error("a script wrote a style"); owner.props[name] = value; } }; this.title = ""; this.disabled = false; this.value = ""; this.open = false; this.scrollTop = 0;
    const owner = this;
    this.classList = {
      add: (...n) => { const s = new Set(owner.cls()); n.forEach((x) => s.add(x)); owner.attrs.class = [...s].join(" "); },
      remove: (...n) => { const s = new Set(owner.cls()); n.forEach((x) => s.delete(x)); owner.attrs.class = [...s].join(" "); },
      toggle: (n, on) => { const s = new Set(owner.cls()); const want = on === undefined ? !s.has(n) : on; want ? s.add(n) : s.delete(n); owner.attrs.class = [...s].join(" "); return want; },
      contains: (n) => owner.cls().includes(n),
    };
  }
  cls() { return (this.attrs.class || "").split(/\s+/).filter(Boolean); }
  get hidden() { return "hidden" in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get id() { return this.attrs.id || ""; }
  set id(v) { this.attrs.id = v; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  removeAttribute(n) { delete this.attrs[n]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  dispatchEvent() { return true; }
  removeEventListener() {}
  fire(type, event = {}) { for (const fn of this.listeners[type] || []) fn({ preventDefault() {}, defaultPrevented: false, ...event }); }
  append(...items) { for (const it of items) { const n = it instanceof FakeNode || it instanceof FakeText ? it : new FakeText(it); if (n.parent) n.parent.children = n.parent.children.filter((c) => c !== n); n.parent = this; this.children.push(n); } }
  replaceChildren(...items) { this.children.forEach((c) => { c.parent = null; c.dropped = (c.dropped || 0) + 1; }); this.children = []; this.append(...items); }
  insertBefore(node, ref) {
    if (node.parent) { node.parent.children = node.parent.children.filter((c) => c !== node); node.dropped = (node.dropped || 0) + 1; }
    node.parent = this;
    const at = ref ? this.children.indexOf(ref) : -1;
    if (at < 0) this.children.push(node); else this.children.splice(at, 0, node);
  }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; this.dropped = (this.dropped || 0) + 1; }
  focus() {}
  set textContent(v) { this.replaceChildren(String(v)); }
  get textContent() { return this.children.map((c) => (c.attrs && c.attrs["aria-hidden"] === "true" ? "" : c.textContent)).join(""); }
  *walk() { yield this; for (const c of this.children) if (c instanceof FakeNode) yield* c.walk(); }
  find(pred) { for (const n of this.walk()) if (pred(n)) return n; return null; }
  all(pred) { return [...this.walk()].filter(pred); }
}
globalThis.Node = FakeNode;
const document = new FakeNode("document");
document.createElement = (tag) => new FakeNode(tag);
document.createElementNS = (ns, tag) => new FakeNode(tag, ns);
document.createTextNode = (t) => new FakeText(t);
document.hidden = false;
const docListeners = {};
document.addEventListener = (type, fn) => { (docListeners[type] ||= []).push(fn); };
document.removeEventListener = (type, fn) => { docListeners[type] = (docListeners[type] || []).filter((f) => f !== fn); };
document.fireVisible = () => (docListeners.visibilitychange || []).forEach((fn) => fn({}));
globalThis.document = document;
const media = { matches: false, addEventListener() {}, removeEventListener() {} };
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
globalThis.window = { matchMedia: () => media, location: { hash: "#/" }, sessionStorage: { getItem: () => "t".repeat(40), setItem() {} } };
export const has = (n, cls) => n.cls().includes(cls);
export { FakeNode };
export const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0)); };
"""

TABS_SCRIPT = r"""
import { FakeNode, has, settle } from "@FAKE@";
import { createSkillsTab } from "@JS@/views/control-skills.js";
import { createConnectionsTab } from "@JS@/views/control-connections.js";
import { createCostsTab } from "@JS@/views/control-costs.js";

const pair = (tier, band, score, extra = {}) => ({ tier, model: tier === "strong" ? "reference-model-1" : "floor-model-1", adapter: tier === "strong" ? "adapter-a" : "adapter-b", band, cause: null, score, mean: score, runs: 9, ...extra });
const skill = (name, area, strong, floor, extra = {}) => ({ name, version: "1.2.0", area, manifest: true, runs_here: 3, proof: [strong, floor], ...extra });
const skillsData = {
  skills: [skill("brand-voice", "brand", pair("strong", "reliable", 0.86), pair("floor", "watch", 0.58, { cause: "pessimistic score under 0.70" })),
    skill("brand-identity", "brand", pair("strong", "watch", 0.66), pair("floor", "needs a test", null, { mean: null, runs: 0, cause: "no evidence on this model" })),
    skill("mkt-publish", "marketing", pair("strong", "reliable", 0.86), pair("floor", "needs a test", null, { mean: null, runs: 0 }))],
  checks: { measurement: "ok", image: "ok" },
};
const flat = (n) => (n.children === undefined ? n.data : n.children.filter((c) => !(c.attrs && c.attrs["aria-hidden"] === "true")).map(flat).join(" "));
const text = (n) => flat(n).replace(/\s+/g, " ").trim();
const out = {};

// --- Skills
const skills = createSkillsTab();
skills.set({ status: "loading" });
out.skillsLoading = text(skills.el);
const busy = skills.el.find((n) => n.attrs["aria-busy"] === "true");
out.skillsBusy = Boolean(busy);
skills.set({ status: "ready", data: skillsData });
// R-53: the table is a list of accordions in five columns (the chevron, the name, the version, the area, the two tiers); Manifest and Runs here are in the open row
const listNow = () => skills.el.find((n) => has(n, "wb-skill-list"));
out.headers = listNow().find((n) => has(n, "wb-skill-head")).children.map(text);
const rowsNow = () => listNow().all((n) => n.tagName === "DETAILS" && has(n, "wb-skill-row"));
out.rowCount = rowsNow().length;
out.firstChild = skills.el.children[0].attrs.class;           // no notice: the legend comes first
out.legend = text(skills.el.find((n) => has(n, "wb-legend")));
const labels = skills.el.all((n) => n.tagName === "LABEL").map((n) => text(n));
out.filterLabels = labels;
const search = skills.el.find((n) => n.tagName === "INPUT");
out.placeholder = search.getAttribute("placeholder");
const areaSelect = skills.el.all((n) => n.tagName === "SELECT")[0];
const bandSelect = skills.el.all((n) => n.tagName === "SELECT")[1];
out.areaOptions = areaSelect.all((n) => n.tagName === "OPTION").map(text);
out.bandOptions = bandSelect.all((n) => n.tagName === "OPTION").map(text);
out.filtersSummary = text(skills.el.find((n) => n.tagName === "SUMMARY"));
const cellsOf = (r) => r.children[0].children.map(text).slice(1);
out.firstRow = cellsOf(rowsNow()[0]);
out.untestedRow = cellsOf(rowsNow()[2]);
out.noZero = !text(skills.el).includes("0.00");
out.detailHiddenAtFirst = rowsNow().every((r) => !r.open);
const bodyOf = (r) => r.find((n) => has(n, "wb-skill-detail")).all((n) => n.tagName === "P").map(text);
out.detailText = bodyOf(rowsNow()[0]);
rowsNow()[0].open = true; rowsNow()[0].fire("toggle");
out.openAfter = rowsNow()[0].open;
// the cards of a phone: a details whose summary is the card and whose body holds the two sentences
const card = skills.el.all((n) => has(n, "wb-skill-card"))[0];
out.card = { summary: text(card.find((n) => n.tagName === "SUMMARY")), body: bodyOf(card) };
// the filters narrow the rows and nothing else
const names = () => rowsNow().map((r) => text(r.find((n) => n.tagName === "CODE")));
areaSelect.value = "marketing"; areaSelect.fire("change"); out.afterArea = names();
areaSelect.value = ""; areaSelect.fire("change");
bandSelect.value = "watch"; bandSelect.fire("change"); out.afterBand = names();
bandSelect.value = ""; bandSelect.fire("change");
search.value = "VOICE"; search.fire("input"); out.afterName = names();
search.value = "zzz"; search.fire("input"); out.afterNothing = text(skills.el.find((n) => has(n, "wb-empty-block")));
search.value = ""; search.fire("input"); out.afterReset = names();
// the notice: first, with both lines
skills.set({ status: "ready", data: { ...skillsData, checks: { measurement: "ok", image: "the eval image is not on this machine" } } });
out.searchKept = [search.parent !== null, search.dropped || 0];   // the search field was never taken out of the page by a redraw
out.noticeFirst = skills.el.children[0].attrs.class;
skills.set({ status: "ready", data: skillsData });
skills.set({ status: "ready", data: { ...skillsData, checks: { measurement: "ok", image: "the eval image is not on this machine" } } });
out.searchKeptAfterNotice = [search.dropped || 0, search.value];
out.notice = skills.el.children[0].all((n) => n.tagName === "STRONG" || n.tagName === "P").map(text);
out.noticeRole = skills.el.children[0].attrs.role;
skills.set({ status: "ready", data: { skills: [], checks: { measurement: "ok", image: "ok" } } });
out.empty = text(skills.el);
skills.set({ status: "failed", error: "the proof of x cannot be read: y" });
out.failed = [text(skills.el.find((n) => has(n, "wb-cnotice-title"))), text(skills.el.find((n) => has(n, "wb-cnotice-line")))];

// --- Connections
const conn = createConnectionsTab();
const connData = (platform, image) => ({
  classes: [{ class: "publisher:social", provider: null, found: false, note: "x", skills: ["mkt-publish"] }, { class: "integration:vcs", provider: "github", found: true, note: null, skills: ["eng-code-review", "ops-pull-request"] }],
  secrets: [{ name: "CODE_HOST_TOKEN", found: true, where: "secret store", value: "SECRET-VALUE-1", masked: "SECRET-MASK", length: 99 }, { name: "FLOOR_MODEL_KEY", found: false, where: null }],
  secrets_note: null, image, platform,
});
conn.set({ status: "ready", data: connData({ machine: "arm64", evidence: "linux/arm64", here: "linux/arm64", same: true }, { name: "workbench-runtime:local", present: true, evidence: false }) });
const tablesOf = (el) => el.all((n) => n.tagName === "TABLE").map((t) => ({ headers: t.all((n) => n.tagName === "TH").map(text), rows: t.all((n) => n.tagName === "TR" && n.parent.tagName === "TBODY").map((r) => r.all((n) => n.tagName === "TD").map(text)) }));
out.conn = tablesOf(conn.el);
out.eyebrows = conn.el.all((n) => has(n, "wb-sec-head")).map(text);
out.noValue = !JSON.stringify([...conn.el.walk()].map((n) => [n.textContent, n.attrs])).includes("SECRET");
const cards = () => conn.el.all((n) => has(n, "wb-ccard"));
out.imageCard = text(cards()[0]);
out.platformSame = text(cards()[1]);
out.sameWide = has(cards()[1], "is-wide");
conn.set({ status: "ready", data: connData({ machine: "arm64", evidence: "linux/arm64", here: "linux/amd64", same: false }, { name: "workbench-runtime:local", present: true, evidence: true }) });
out.platformDiffers = text(cards()[1]);
out.differsWide = has(cards()[1], "is-wide");
out.noConsequence = !text(conn.el).includes("not proven") && !text(conn.el).includes("measured on another platform");
conn.set({ status: "ready", data: connData({ machine: "arm64", evidence: null, here: "linux/arm64", same: null }, { name: "workbench-runtime:local", present: false, evidence: null }) });
out.platformNull = text(cards()[1]);
out.imageMissing = text(cards()[0]);
conn.set({ status: "ready", data: { ...connData({}, {}), secrets_note: "the secret resolver could not be used: KeyError" } });
out.secretsNote = text(conn.el.find((n) => has(n, "wb-note")));
conn.set({ status: "failed", error: "connections: the secret store did not answer within 5 s" });
out.connFailed = [text(conn.el.find((n) => has(n, "wb-cnotice-title"))), text(conn.el.find((n) => has(n, "wb-cnotice-line")))];
conn.set({ status: "loading" });
out.connLoading = text(conn.el);

// --- Costs
const sinceCalls = [];
const costs = createCostsTab({ onSince: (t) => sinceCalls.push(t) });
const price = { source: "provider price page", date: "2026-09-30" };
const crow = (day, agent, model, adapter, runs, tokens, recorded, recomputed, unknown, p) => ({ day, agent, model, adapter, runs, tokens, recorded_usd: recorded, recomputed_usd: recomputed, unknown_runs: unknown, price: p });
const costsData = {
  since: "2026-09-07",
  rows: [crow("2026-10-06", "engineering", "reference-model-1", "adapter-a", 4, 340100, null, null, 1, price), crow("2026-10-07", "engineering", "reference-model-1", "adapter-a", 5, 412300, null, 3.84, 0, price),
    crow("2026-10-07", "engineering", "floor-model-1", "adapter-b", 4, 301800, 1.87, null, 0, null), crow("2026-10-07", "marketing", "reference-model-1", "adapter-a", 2, 150000, null, 1.2, 0, price)],
  caps: [{ agent: "engineering", max_runs_per_day: 12, max_usd_per_day: 4 }],
};
costs.set({ status: "loading", fieldValue: null });
out.costsLoadingNoField = costs.el.all((n) => n.tagName === "INPUT").length;
costs.set({ status: "ready", data: costsData, agents: [{ name: "engineering", runs_today: 5, usd_today: 1.87 }], fieldValue: "2026-09-07" });
const input = costs.el.find((n) => n.tagName === "INPUT");
// a read in flight, a quiet re-read and a failed read redraw the tab without taking the field out of it
costs.set({ status: "loading", data: costsData, agents: null, fieldValue: "2026-09-07" });
costs.set({ status: "ready", data: costsData, agents: [{ name: "engineering", runs_today: 5, usd_today: 1.87 }], fieldValue: "2026-09-07" });
costs.set({ status: "failed", error: "x", agents: null, fieldValue: "2026-09-07" });
costs.set({ status: "ready", data: costsData, agents: [{ name: "engineering", runs_today: 5, usd_today: 1.87 }], fieldValue: "2026-09-07" });
out.sinceKept = [input.dropped || 0, input.parent !== null];
out.since = [input.value, input.getAttribute("type"), text(costs.el.find((n) => n.tagName === "LABEL"))];
const caps = costs.el.find((n) => has(n, "wb-caps"));
out.caps = [text(caps), caps.getAttribute("aria-label")];
out.chartHead = text(costs.el.find((n) => has(n, "wb-chart-head")));
const plot = costs.el.find((n) => has(n, "wb-plot"));
out.plot = { role: plot.attrs.role, label: plot.attrs["aria-label"], cols: plot.cls().filter((c) => c.startsWith("wb-cols")), svgs: plot.all((n) => n.tagName === "SVG").length,
  ns: plot.find((n) => n.tagName === "SVG").ns.endsWith("/2000/svg"), rects: plot.all((n) => n.tagName === "RECT").map((r) => [r.attrs.class, r.attrs.y, r.attrs.height]) };
out.plotLabels = text(costs.el.find((n) => has(n, "wb-plot-labels")));
const disclosure = costs.el.find((n) => has(n, "wb-chart-acc"));
out.disclosure = [text(disclosure.find((n) => n.tagName === "SUMMARY")), disclosure.open, disclosure.all((n) => n.tagName === "TH" && n.attrs.scope === "col").map(text), disclosure.all((n) => n.tagName === "TR" && n.parent.tagName === "TBODY").map((r) => r.children.map(text))];
const big = costs.el.find((n) => has(n, "wb-costs-table"));
out.costHeaders = big.all((n) => n.tagName === "TH").map(text);
out.costRows = big.all((n) => n.tagName === "TR" && n.parent.tagName === "TBODY").map((r) => r.all((n) => n.tagName === "TD").map(text));
out.footnote = text(costs.el.find((n) => has(n, "wb-foot")));
input.value = "2026-10-01"; input.fire("change");
out.sinceCalls = sinceCalls;
costs.set({ status: "refused", error: "since is a day: YYYY-MM-DD", agents: null, fieldValue: "2026-13-07" });
out.refused = [text(costs.el.find((n) => has(n, "wb-cnotice-title"))), text(costs.el.find((n) => has(n, "wb-cnotice-line"))), input.value, input.getAttribute("aria-invalid"), costs.el.all((n) => n.tagName === "TABLE").length];
costs.set({ status: "ready", data: { since: "2026-09-07", rows: [], caps: [] }, agents: [], fieldValue: "2026-09-07" });
out.costsEmpty = [text(costs.el.find((n) => has(n, "wb-empty-block"))), costs.el.all((n) => n.tagName === "TABLE").length, input.getAttribute("aria-invalid")];
costs.set({ status: "failed", error: "costs: the store did not answer", agents: null, fieldValue: "2026-09-07" });
out.costsFailed = [text(costs.el.find((n) => has(n, "wb-cnotice-title"))), text(costs.el.find((n) => has(n, "wb-cnotice-line")))];
costs.set({ status: "ready", data: { since: "2026-09-07", rows: [crow("2026-10-07", null, "m", "a", 1, null, null, null, 0, null)], caps: [] }, agents: [], fieldValue: "2026-09-07" });
out.nullAgentRow = [...costs.el.find((n) => has(n, "wb-costs-table")).all((n) => n.tagName === "TR" && n.parent.tagName === "TBODY")[0].all((n) => n.tagName === "TD").map(text)];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_three_tabs_show_what_the_operations_returned_in_the_columns_and_words_the_handoff_gives(tmp_path):
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FAKE_DOM, encoding="utf-8")
    got = run_node(tmp_path, TABS_SCRIPT.replace("@FAKE@", fake.as_uri()))
    # Skills
    assert got["skillsLoading"] == "Loading the proof, costs and connections..." and got["skillsBusy"] is True
    assert got["headers"] == ["", "Skill", "Version", "Area", "Reference model", "Floor model"], "R-53, E-13: five columns after the chevron; Manifest and Runs here moved into the open row"
    assert got["rowCount"] == 3, "R-53: three skills, each an accordion"
    assert got["firstChild"] == "wb-legend" and got["legend"] == "reliable watch needs a test band per model tier, with the score"
    assert got["filterLabels"] == ["Area All areas brand marketing", "Band All bands reliable watch needs a test", "Search by name"]
    assert got["placeholder"] is None, "the search field has no placeholder text"
    assert got["areaOptions"] == ["All areas", "brand", "marketing"] and got["bandOptions"] == ["All bands", "reliable", "watch", "needs a test"]
    assert got["filtersSummary"] == "Filters"
    assert got["firstRow"] == ["brand-voice", "1.2.0", "brand", "0.86 reliable", "0.58 watch"], "R-53, M-2: in a tier the score comes first, then the band's chip"
    assert got["untestedRow"] == ["mkt-publish", "1.2.0", "marketing", "0.86 reliable", "- needs a test"], "an untested pair shows '-' and never 0.00"
    assert got["noZero"] is True
    assert got["detailHiddenAtFirst"] is True and got["openAfter"] is True, "R-53: a row is a `details`: it opens and stays open"
    assert got["detailText"] == ["Manifest: yes", "Runs here: 3",
                                 "Reference model: reference-model-1, adapter-a, mean 0.86, 9 runs. Cause: none.",
                                 "Floor model: floor-model-1, adapter-b, mean 0.58, 9 runs. Cause: pessimistic score under 0.70."], "E-13: Manifest and Runs here, then the two sentences"
    assert got["card"]["summary"].startswith("brand-voice 1.2.0 · brand Manifest yes · 3 runs here Reference 0.86 reliable Floor 0.58 watch"), "R-53 on the phone's card: the score first"
    assert got["card"]["body"] == got["detailText"][2:], "the card says the manifest and the runs in its summary"
    assert got["afterArea"] == ["mkt-publish"] and got["afterBand"] == ["brand-voice", "brand-identity"] and got["afterName"] == ["brand-voice"]
    assert got["afterNothing"] == "No skill matches these filters." and got["afterReset"] == ["brand-voice", "brand-identity", "mkt-publish"]
    assert got["searchKept"] == [True, 0] and got["searchKeptAfterNotice"] == [0, "" ], "a redraw of the Skills tab never takes the search field out of the page: it keeps its focus"
    assert got["noticeFirst"] == "notice pui-soft pui-error wb-cnotice" and got["noticeRole"] == "alert", "R-54: the soft error style"
    assert got["notice"] == ["A check of the proof failed", "These skills run as not proven: on the reference model and without autonomy.",
                             "Measurement check: ok", "Image check: the eval image is not on this machine"]
    assert got["empty"] == "No skills are in scope of this project."
    assert got["failed"] == ["The read failed", "the proof of x cannot be read: y"]
    # Connections
    classes, secrets = got["conn"]
    assert classes["headers"] == ["Class", "Provider", "Status", "Needed by"]
    assert classes["rows"] == [["publisher:social", "no provider found", "missing", "mkt-publish"], ["integration:vcs", "github", "found", "eng-code-review, ops-pull-request"]]
    assert secrets["headers"] == ["Name", "Status", "Where"]
    assert secrets["rows"] == [["CODE_HOST_TOKEN", "found", "secret store"], ["FLOOR_MODEL_KEY", "missing", "-"]]
    assert got["eyebrows"] == ["Requirement classes", "Secrets (names only, never a value)", "Image", "Platform"], "the page's headings are `h3.wb-sec-head`"
    assert got["noValue"] is True, "a value, a masked value or a length the operation sent is never put in the page"
    assert got["imageCard"] == "Image workbench-runtime:local present It is the image the evidence was measured in: no"
    assert got["platformSame"] == "Platform This machine: linux/arm64 same Evidence: linux/arm64" and got["sameWide"] is False, "the page: the chip beside the first line"
    assert got["platformDiffers"] == "Platform This machine: linux/amd64 · Evidence: linux/arm64 differs" and got["differsWide"] is True, "the page writes the separator in the line"
    assert got["noConsequence"] is True, "the page states no rule about a difference of platform"
    assert got["platformNull"] == "Platform This machine: linux/arm64 Evidence: not known", "no chip when the operation could not compare"
    assert got["imageMissing"] == "Image workbench-runtime:local missing It is the image the evidence was measured in: not known"
    assert got["secretsNote"] == "the secret resolver could not be used: KeyError"
    assert got["connFailed"] == ["The read failed", "connections: the secret store did not answer within 5 s"]
    assert got["connLoading"] == "Loading the proof, costs and connections..."
    # Costs
    assert got["costsLoadingNoField"] == 0
    assert got["since"] == ["2026-09-07", "date", "Since"], "the field's value is the operation's own since; it is a date field (M-8: was a text field)"
    assert got["caps"][0] == "Agent Runs today Spend today engineering 5 / 12 $1.87 / $4.00", "R-52: the caps are rows with meters, under the KPI cards' words"
    assert got["caps"][1].startswith("Caps by agent.") and "subscription or free credential" in got["caps"][1]
    assert got["chartHead"] == "Runs per day by agent engineering marketing"
    plot = got["plot"]
    assert plot["role"] == "img" and plot["label"] == "Runs per day by agent, table below" and plot["cols"] == ["wb-cols-7"]
    assert plot["svgs"] == 7 and plot["ns"] is True, "seven days up to the newest day with rows: a column for each, empty or not"
    assert plot["rects"] == [["wb-seg wb-series-1", "63.636", "36.364"], ["wb-seg wb-series-1", "18.182", "81.818"], ["wb-seg wb-series-2", "0", "18.182"]], \
        "a segment per agent and day, the largest series from the bottom, heights in percent of the largest day"
    assert got["plotLabels"] == "Oct 1 Oct 2 Oct 3 Oct 4 Oct 5 Oct 6 Oct 7"
    assert got["disclosure"][:3] == ["The chart as a table", False, ["Day", "engineering", "marketing"]]
    assert got["disclosure"][3] == [["Oct 1", "0", "0"], ["Oct 2", "0", "0"], ["Oct 3", "0", "0"], ["Oct 4", "0", "0"], ["Oct 5", "0", "0"], ["Oct 6", "4", "0"], ["Oct 7", "9", "2"]]
    assert got["costHeaders"] == ["Day", "Agent", "Model", "Adapter", "Runs", "Tokens", "Recorded", "Recomputed"]
    assert got["costRows"] == [
        ["2026-10-07", "engineering", "reference-model-1", "adapter-a", "5", "412,300", "not recorded", "$3.84"],
        ["2026-10-07", "engineering", "floor-model-1", "adapter-b", "4", "301,800", "$1.87", "no price"],
        ["2026-10-07", "marketing", "reference-model-1", "adapter-a", "2", "150,000", "not recorded", "$1.20"],
        ["2026-10-06", "engineering", "reference-model-1", "adapter-a", "4", "340,100", "not recorded", "unknown (1 run)"],
    ], "newest day first; not recorded, no price and unknown (n run) are the cells' words"
    assert got["footnote"] == "Recomputed from token counts and the prices in the project's configuration (source: provider price page, 2026-09-30). A run whose usage is unknown shows unknown and is counted."
    assert got["sinceKept"] == [0, True], "a read of the Costs tab never takes the Since field out of the page: it keeps its focus"
    assert got["sinceCalls"] == ["2026-10-01"], "a change of the field asks the page to read costs again with the typed text"
    assert got["refused"] == ["Date refused", "since is a day: YYYY-MM-DD", "2026-13-07", "true", 0]
    assert got["costsEmpty"] == ["No runs since 2026-09-07.", 0, None]
    assert got["costsFailed"] == ["The read failed", "costs: the store did not answer"]
    assert got["nullAgentRow"] == ["2026-10-07", "no agent", "m", "a", "1", "-", "not recorded", "no price"]


VIEW_SCRIPT = r"""
import { FakeNode, has, settle } from "@FAKE@";
import { createControlView } from "@JS@/views/control.js";

const flat = (n) => (n.children === undefined ? n.data : n.children.filter((c) => !(c.attrs && c.attrs["aria-hidden"] === "true")).map(flat).join(" "));
const text = (n) => flat(n).replace(/\s+/g, " ").trim();
const calls = [];
const answers = {};
globalThis.fetch = async (url, init) => {
  const path = new URL(url, "http://127.0.0.1").pathname.replace("/api/v1/projects/aaaaaaaaaaaa/", "");
  const query = new URL(url, "http://127.0.0.1").search;
  calls.push([init.method, path + query]);
  const found = answers[path + query] || answers[path];
  if (!found) return { ok: false, status: 404, json: async () => ({ error: "not_found", message: "no route" }) };
  return { ok: found.status === undefined || found.status < 400, status: found.status || 200, json: async () => found.body };
};
const ok = (body) => ({ body });
answers.skills = ok({ skills: [{ name: "brand-voice", version: "1.0.0", area: "brand", manifest: true, runs_here: 0, proof: [] }], checks: { measurement: "ok", image: "ok" } });
answers.costs = ok({ since: "2026-09-08", rows: [{ day: "2026-10-07", agent: "engineering", model: "m", adapter: "a", runs: 2, tokens: 10, recorded_usd: null, recomputed_usd: 0.5, unknown_runs: 0, price: { source: "page", date: "2026-09-30" } }], caps: [{ agent: "engineering", max_runs_per_day: 12, max_usd_per_day: 4 }] });
answers["costs?since=2026-13-07"] = { status: 400, body: { error: "usage", message: "since is a day: YYYY-MM-DD" } };
answers["costs?since=2026-10-01"] = ok({ since: "2026-10-01", rows: [], caps: [] });
answers.agents = ok({ agents: [{ name: "engineering", runs_today: 5, usd_today: 1.87 }] });
answers.connections = { status: 500, body: { error: "internal", message: "connections: the secret store did not answer within 5 s" } };

const unavailable = [];
const frame = { main: new FakeNode("main"), sceneHost: new FakeNode("div"), noticeBox: new FakeNode("div"), insets: () => ({}), sceneUnavailable: (on) => unavailable.push(on) };
const view = createControlView(frame);
const out = {};
const tab = (id) => view.el.find((n) => n.attrs.id === `wb-tab-${id}`);
const panel = (id) => view.el.find((n) => n.attrs.id === `wb-tabpanel-${id}`);
out.mounted = frame.main.children.length;
out.noWebGL = [unavailable.at(-1)];
out.tablist = view.el.find((n) => n.attrs.role === "tablist").all((n) => n.attrs.role === "tab").map((n) => [n.textContent, n.attrs["aria-selected"], n.attrs.tabindex]);
out.title = [text(view.el.find((n) => has(n, "wb-panel-title"))), text(view.el.find((n) => has(n, "wb-panel-sub")))];
// before the page has read the project list: the loading line, and no read of the service
view.update({ loaded: false, known: false, accepted: false, projectId: "aaaaaaaaaaaa", tab: undefined });
out.beforeLoad = [text(view.el.find((n) => has(n, "wb-control-content"))).includes("Loading the proof"), calls.length];
// a first read of the project list that failed: nothing under the tabs (the frame's notice says why), and no read
view.update({ loaded: false, unread: true, known: false, accepted: false, projectId: "aaaaaaaaaaaa", tab: "skills" });
const bottom = view.el.find((n) => has(n, "wb-control-content")).children.at(-1);
out.unread = [bottom.children.length, calls.length];
// a project whose configuration is not accepted: its sentence, no read
view.update({ loaded: true, known: true, accepted: false, projectId: "aaaaaaaaaaaa", tab: "skills" });
out.notAccepted = [text(view.el.find((n) => has(n, "wb-control-content"))).includes("Waiting for the configuration to be accepted."), calls.length, panel("skills").hidden];
// accepted: the three reads and agents, once
view.update({ loaded: true, known: true, accepted: true, projectId: "aaaaaaaaaaaa", tab: "skills" });
await settle();
out.reads = calls.map((c) => c.join(" ")).sort();
out.allGet = calls.every((c) => c[0] === "GET");
out.skillsShown = [panel("skills").hidden, text(panel("skills")).includes("brand-voice")];
// the poll calls update again: nothing is read again
view.update({ loaded: true, known: true, accepted: true, projectId: "aaaaaaaaaaaa", tab: "skills" });
await settle();
out.readsAfterPoll = calls.length;
// a hash that names the costs tab: the tab changes, nothing is read again
view.update({ loaded: true, known: true, accepted: true, projectId: "aaaaaaaaaaaa", tab: "costs" });
out.costsTab = [panel("skills").hidden, panel("costs").hidden, tab("costs").attrs["aria-selected"], tab("skills").attrs["aria-selected"], tab("costs").attrs.tabindex, tab("skills").attrs.tabindex];
out.costsText = [text(panel("costs")).includes("engineering 5 / 12 $1.87 / $4.00"), text(panel("costs")).includes("Recomputed")];
// the Connections read failed: its own notice; the other tabs keep their data
view.update({ loaded: true, known: true, accepted: true, projectId: "aaaaaaaaaaaa", tab: "connections" });
out.connFailed = [text(panel("connections")).includes("The read failed"), text(panel("connections")).includes("connections: the secret store did not answer within 5 s"), text(panel("skills")).includes("brand-voice")];
// the keyboard: arrows move between tabs and the hash carries the tab; Home and End jump
const key = (id, k) => { let prevented = false; tab(id).fire("keydown", { key: k, preventDefault() { prevented = true; } }); return prevented; };
const hashes = [];
for (const [id, k] of [["connections", "ArrowRight"], ["skills", "ArrowLeft"], ["costs", "End"], ["costs", "Home"], ["costs", "x"]]) {
  window.location.hash = "";
  const prevented = key(id, k);
  hashes.push([k, window.location.hash, prevented]);
}
out.keys = hashes;
tab("costs").fire("click");
out.click = window.location.hash;
// a refused date: the field's text goes to the service as typed, the 400 shows as Date refused with the service's message
const input = panel("costs").find((n) => n.tagName === "INPUT");
input.value = "2026-13-07"; input.fire("change");
await settle();
out.refusedText = [text(panel("costs")).includes("Date refused"), text(panel("costs")).includes("since is a day: YYYY-MM-DD"), input.value];
input.value = "2026-10-01"; input.fire("change");
await settle();
out.emptyText = text(panel("costs")).includes("No runs since 2026-10-01.");
out.costsCalls = calls.filter((c) => c[1].startsWith("costs")).map((c) => c[1]);
// return from a hidden tab: the view reads nothing by itself (WP-9.13: the page reloads on return and gives the view a new stamp)
const before = calls.length;
document.fireVisible();
await settle();
out.visibleReads = calls.length - before;
view.dispose();
out.disposed = [frame.main.children.length];
const after = calls.length;
document.fireVisible();
out.afterDispose = calls.length - after;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_control_view_reads_once_per_entry_and_shows_each_tabs_own_state(tmp_path):
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FAKE_DOM, encoding="utf-8")
    got = run_node(tmp_path, VIEW_SCRIPT.replace("@FAKE@", fake.as_uri()))
    assert got["mounted"] == 1
    assert got["noWebGL"] == [True], "without WebGL the scene area says so and the tabs are the whole screen"
    assert got["tablist"] == [["Skills", "true", "0"], ["Costs", "false", "-1"], ["Connections", "false", "-1"]]
    assert got["title"] == ["Control room", "Skills, costs and connections of this project"], "E-10: the sub line follows the tab; before the project is known no name is made up"
    assert got["unread"] == [0, 0]
    assert got["beforeLoad"] == [True, 0] and got["notAccepted"] == [True, 0, True]
    assert got["reads"] == sorted(["GET agents", "GET connections", "GET costs", "GET skills"]), "the three reads and the agents read for the caps line"
    assert got["allGet"] is True, "no control on this screen writes"
    assert got["skillsShown"] == [False, True] and got["readsAfterPoll"] == 4, "an update from the page's poll reconciles and reads nothing"
    assert got["costsTab"] == [True, False, "true", "false", "0", "-1"]
    assert got["costsText"] == [True, True]
    assert got["connFailed"] == [True, True, True], "a tab whose read failed shows its own notice while the others show their data"
    assert got["keys"] == [["ArrowRight", "#/p/aaaaaaaaaaaa/control/skills", True], ["ArrowLeft", "#/p/aaaaaaaaaaaa/control/connections", True],
                           ["End", "#/p/aaaaaaaaaaaa/control/connections", True], ["Home", "#/p/aaaaaaaaaaaa/control/skills", True], ["x", "", False]]
    assert got["click"] == "#/p/aaaaaaaaaaaa/control/costs"
    assert got["refusedText"] == [True, True, "2026-13-07"]
    assert got["emptyText"] is True
    assert got["costsCalls"][-2:] == ["costs?since=2026-13-07", "costs?since=2026-10-01"] and got["costsCalls"][0] == "costs"
    assert got["visibleReads"] == 0
    assert got["disposed"] == [0] and got["afterDispose"] == 0


# --- rules read from the files ---------------------------------------------------------------------------------------------------


def control_files():
    return sorted(VIEWS.glob("control*.js"))


def test_the_control_room_modules_exist_and_the_pure_one_imports_no_document_or_network():
    names = {p.name for p in control_files()}
    assert names >= {"control.js", "control-model.js", "control-skills.js", "control-costs.js", "control-connections.js", "control-parts.js"}
    model = (VIEWS / "control-model.js").read_text(encoding="utf-8")
    assert re.findall(r'^import .* from "([^"]+)"', model, re.M) == ["../format.js"], "the pure module imports only the display words"
    code = "\n".join(line for line in model.splitlines() if not line.lstrip().startswith(("//", "*", "/**")))
    assert not re.search(r"\bdocument\b|\bwindow\b|\bfetch\b|\bapi\.", code)
    assert 'import("' not in model


def test_the_control_room_never_puts_a_secrets_value_anywhere():
    connections = (VIEWS / "control-connections.js").read_text(encoding="utf-8")
    model = (VIEWS / "control-model.js").read_text(encoding="utf-8")
    rows = model[model.index("export function secretRows"):model.index("/** The accessible name of a secret's row")]
    assert not re.search(r"\.(value|masked|length|token|secret)\b", rows), "no field other than name, found and where is read from a secret"
    assert not re.search(r"\.(value|masked|token|secret)\b", connections), "the tab reads no such field either"
    assert re.search(r'name: String\(s\.name\),\s*found: s\.found === true,\s*status:.*\s*where:', model), "a secret row is made of a name, a status and a place"


def test_the_control_room_builds_the_chart_as_same_origin_svg_with_a_table_and_no_literal_colour():
    costs = (VIEWS / "control-costs.js").read_text(encoding="utf-8")
    assert "createElementNS" in costs and 'preserveAspectRatio: "none"' in costs and "The chart as a table" in costs
    assert "https://" not in costs and "http://" not in costs, "the namespace name is written in parts: the file test refuses the text of an address"
    for path in control_files():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", text), f"{path.name} has a colour literal"
        # R-52: the caps' meters write the one custom property `--wb-share` through the CSS Object Model, as the KPI cards do (control-parts.js); no other style, no style attribute
        without_share = re.sub(r'\.style\.setProperty\("--wb-share", ', "", text)
        assert not re.search(r"\.style\b|\bstyle\s*:", without_share), f"{path.name} writes a style"
        if path.name != "control-parts.js":
            assert ".style.setProperty" not in text
    css = interface_css()
    series = dict(re.findall(r"\.(wb-series-[a-z0-9]+) \{ --wb-series: ([^;]+); \}", css))
    assert series == {"wb-series-1": "var(--pui-theme)", "wb-series-2": "var(--wb-tint-series)", "wb-series-3": "var(--pui-muted)", "wb-series-other": "var(--pui-bg-emphasis)"}
    root = re.findall(r"--wb-tint-series: ([^;]+);", css)
    assert root == ["color-mix(in srgb, var(--pui-theme) 38%, var(--wb-raised))"], "R-52: the second series is the brand colour at 38 percent, written once, from tokens"
    assert re.search(r"--wb-ink-error: color-mix\(in oklab, var\(--pui-error\), var\(--pui-text\) 25%\);", css)


# --- the server-room scene ------------------------------------------------------------------------------------------------------

SCENE_SCRIPT = r"""
import * as THREE from "@JS@/three.js";
import { createKit } from "@JS@/scene/kit.js";
import { BUILDERS } from "@JS@/scene/engine.js";
import { sceneModel, OPENS } from "@JS@/views/control-model.js";
import { buildServer } from "@JS@/views/control-scene.js";
import { serverTones } from "@JS@/scene/palette.js";
import { FRAME, RACK, SCREEN } from "@JS@/scene/server-room.js";

const c = (hex) => new THREE.Color(hex);
const T = { border: c(0x101010), theme: c(0x2020f0), success: c(0x10f010), error: c(0xf01010), emphasis: c(0x303030), text: c(0x404040), warn: c(0xf0a010), textMuted: c(0x505050) };
const palette = { dark: false, T, mix: (a, b, t) => a.clone().lerp(b, t), bg: c(0xfafafa), shell: c(0xf8f8f8), ink: c(0x202020), metal: c(0x606060), deskTop: c(0xd0d0d0), screenOff: c(0x181818), leafA: c(0x80c080), trunk: c(0x806040) };
const hex = (colour) => colour.getHex();

const conn = (classes, secrets, image) => ({
  classes: classes.map((found, i) => ({ class: `c${i}`, provider: found ? "p" : null, found, note: null, skills: [] })),
  secrets: secrets.map((found, i) => ({ name: `S${i}`, found, where: found ? "env" : null })),
  image: { name: "i", present: image, evidence: true }, platform: {},
});
const row = (day, runs) => ({ day, agent: "a", model: "m", adapter: "x", runs, tokens: null, recorded_usd: null, recomputed_usd: null, unknown_runs: 0, price: null });

// R-51: the room is baked into batches with a colour on every vertex, so the lights and the bars are read from the vertices of the rack and wall-screen meshes: a light is a quad (six vertices)
function count(model) {
  const kit = createKit(palette);
  const built = buildServer(kit, model);
  const S = serverTones(palette);
  const meshOf = (group) => { const out = []; group.traverse((o) => { if (o.isMesh) out.push(o); }); return out; };
  const quads = (mesh) => {
    const p = mesh.geometry.getAttribute("position"); const k = mesh.geometry.getAttribute("color"); const out = [];
    for (let i = 0; i + 5 < p.count; i += 6) {
      const xs = [], ys = [];
      for (let j = 0; j < 6; j++) { xs.push(p.getX(i + j)); ys.push(p.getY(i + j)); }
      out.push({ hex: new THREE.Color(k.getX(i), k.getY(i), k.getZ(i)).getHex(), x0: Math.min(...xs), y0: Math.min(...ys), y1: Math.max(...ys) });
    }
    return out;
  };
  const racks = built.hits.filter((h) => h.id.startsWith("rack")).flatMap((h) => meshOf(h.object).flatMap(quads));
  const wall = built.hits.filter((h) => h.id === "wall").flatMap((h) => meshOf(h.object).flatMap(quads));
  const of = (list, colour) => list.filter((q) => q.hex === hex(colour));
  const meshes = meshOf(built.group);
  const bars = of(wall, S.bar).map((q) => ({ x: +q.x0.toFixed(3), h: +(q.y1 - q.y0).toFixed(4) })).sort((a, b) => a.x - b.x);
  const out = { ok: of(racks, S.ledOk).length, bad: of(racks, S.ledBad).length, off: of(racks, S.ledOff).length, bars, hits: built.hits.map((h) => [h.id, h.tip]), labels: built.labels.length, beacons: built.beacons.length, markers: built.markers.length, meshes: meshes.length,
    moving: built.group.children.length > 0 };
  const box = new THREE.Box3().setFromObject(built.group);
  out.size = [+(box.max.x - box.min.x).toFixed(1), +(box.max.y - box.min.y).toFixed(1), +(box.max.z - box.min.z).toFixed(1)];
  kit.dispose();
  return out;
}

const out = {};
out.registered = BUILDERS.server === buildServer;
// seven classes (two missing), three secrets (one missing), the image present: 11 facts
const connections = conn([true, true, false, true, true, false, true], [true, false, true], true);
const costs = { since: "2026-09-08", rows: [row("2026-10-01", 3), row("2026-10-01", 1), row("2026-10-02", 5), row("2026-10-04", 8), row("2026-10-07", 12)] };
const full = sceneModel({ accepted: true, connections, costs });
out.model = { ready: full.ready, facts: full.facts, missing: full.missing, leds: full.leds.join(","), racks: full.racks.map((r) => [r.name, r.missing, r.tip]), bars: full.bars.map((v) => +v.toFixed(4)), label: full.label };
out.full = count(full);
// 21 facts and more: only the slots exist, the missing count is still every fact's
const many = sceneModel({ accepted: true, connections: conn(new Array(10).fill(true), new Array(13).fill(false), true), costs: null });
out.many = { facts: many.facts, missing: many.missing, off: many.leds.filter((l) => l === "off").length, leds: many.leds.length, built: count(many) };
// loading, then not accepted: every LED off, no bar, no read needed
out.loading = count(sceneModel({ accepted: true, connections: null, costs: null }));
out.loadingModel = (({ ready, label, facts }) => ({ ready, label, facts }))(sceneModel({ accepted: true }));
out.notAccepted = (({ ready, label }) => ({ ready, label }))(sceneModel({ accepted: false, connections, costs }));
out.notAcceptedBuilt = count(sceneModel({ accepted: false, connections, costs }));
// a window of two days sits at the right end of the seven bars
out.short = sceneModel({ accepted: true, connections, costs: { since: "2026-10-06", rows: [row("2026-10-06", 2), row("2026-10-07", 4)] } }).bars.map((v) => +v.toFixed(2));
out.opens = OPENS;
out.slot = [FRAME.sx, SCREEN.pitch, SCREEN.full, FRAME.sy];
out.unread = sceneModel({ accepted: true, connections: null }).racks.map((r) => r.tip);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_server_room_has_one_led_per_connection_fact_and_one_bar_per_summed_day_and_nothing_else_on_it(tmp_path):
    got = run_node(tmp_path, SCENE_SCRIPT)
    assert got["registered"] is True, "the scene kind is registered through the engine's BUILDERS"
    model = got["model"]
    assert model["ready"] is True and model["facts"] == 11 and model["missing"] == 3
    assert model["leds"] == ",".join(["ok", "ok", "bad", "ok", "ok", "bad", "ok", "ok", "bad", "ok", "ok"] + ["off"] * 10), \
        "each class, then each secret, then the image; the slots left over are off"
    # R-51: the page's tooltip names the racks as one object, "Connections · 2 missing · Connections tab" (control-room.html), with the count of every fact; each rack keeps its own count
    tip = "Connections · 3 missing · Connections tab"
    assert model["racks"] == [["store · tasks", 2, tip], ["integrations", 1, tip], ["vcs · publishers", 0, tip]]
    # days Oct 1 to Oct 7: 4, 5, 0, 8, 0, 0, 12 runs, each over the largest day
    assert model["bars"] == [0.3333, 0.4167, 0, 0.6667, 0, 0, 1]
    assert model["label"] == "Server room: 3 racks, 3 connections missing, runs of the last 7 days"
    full = got["full"]
    assert (full["ok"], full["bad"], full["off"]) == (8, 3, 10), "the LEDs drawn are the facts: 8 found, 3 missing, 10 slots with no fact"
    sx, pitch, high, sy = got["slot"]
    # R-51 changes the wall screen's bars (the page's: 0.925 of a page unit at most, a slot every 0.4, a cap on each bar) and so these two lines; the model's bars are the same
    assert [b["h"] for b in full["bars"]] == [round(high * sy * v, 4) for v in (0.3333, 0.4167, 0.6667, 1)], "a bar per day with runs, 0.925 of a page unit high at most"
    xs = [b["x"] for b in full["bars"]]
    assert [round((x - xs[0]) / (pitch * sx), 2) for x in xs] == [0, 1, 3, 6], "bars a slot (0.4) apart, an empty day draws none"
    assert [h[0] for h in full["hits"]] == ["rack-1", "rack-2", "rack-3", "wall", "console"]
    assert full["hits"][3][1] == "Runs by day · Costs tab" and full["hits"][4][1] == "Console · Skills tab"
    assert full["labels"] == 0 and full["beacons"] == 0 and full["markers"] == 0, "no label, no beacon, no marker: nothing in it moves or says anything"
    assert 5 <= full["meshes"] <= 20, "R-51: batched statics, a handful of meshes (it was a hundred and fifty boxes)"
    assert got["many"]["facts"] == 24 and got["many"]["missing"] == 13 and got["many"]["leds"] == 21 and got["many"]["off"] == 0
    assert (got["many"]["built"]["ok"], got["many"]["built"]["bad"], got["many"]["built"]["off"]) == (10, 11, 0), "21 slots, 24 facts: the first 21 are drawn"
    assert (got["loading"]["ok"], got["loading"]["bad"], got["loading"]["off"], got["loading"]["bars"]) == (0, 0, 21, []), "loading: every LED off and no bar"
    assert got["loadingModel"] == {"ready": False, "label": "Server room, loading", "facts": 0}
    assert got["notAccepted"] == {"ready": False, "label": "Server room, waiting for the configuration to be accepted"}
    assert (got["notAcceptedBuilt"]["ok"], got["notAcceptedBuilt"]["bad"], got["notAcceptedBuilt"]["bars"]) == (0, 0, []), "a project that is not accepted is dim"
    assert got["short"] == [0, 0, 0, 0, 0, 0.5, 1]
    assert got["unread"] == ["Connections · nothing read yet"] * 3, "before the connections are read the racks say so"
    assert got["opens"] == {"rack-1": "connections", "rack-2": "connections", "rack-3": "connections", "wall": "costs", "console": "skills"}


def test_the_server_room_builder_draws_with_the_engines_kit_holds_no_colour_and_moves_nothing():
    scene = (VIEWS / "control-scene.js").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|0x[0-9a-fA-F]{6}\b|\brgba?\(|\bhsla?\(", scene), "every colour is a token or a recipe of the palette"
    assert not re.search(r"requestAnimationFrame|setInterval|setTimeout|Math\.random|Math\.sin|\.style\b|createElement|innerHTML", scene), \
        "nothing moves, nothing random, no markup of its own, no style"
    assert "BUILDERS.server = buildServer" in scene and "createKit" not in scene, "the engine's kit and registry are used, not copied"
    # R-51: the room's tones are the recipes of the page's scene.css in palette.js (roomTones for the desk and the chair, serverTones for the racks and the wall screen), not tokens read one by one
    for token in ("roomTones(palette)", "serverTones(palette)", "buildGround(kit, 1)", "boxBrackets", "planeBrackets"):
        assert token in scene, f"the scene reads {token}"
    engine = (JS / "scene" / "engine.js").read_text(encoding="utf-8")
    assert "buildServer" not in engine and "server:" not in engine and '"server"' not in engine, "the engine names no server-room builder: the scene registers itself through BUILDERS (B3 edited the engine for the brackets, so this is a rule about the registry, not a ban on every edit)"
    control = (VIEWS / "control.js").read_text(encoding="utf-8")
    assert 'engine.show("server"' in control and "NoWebGL" in control and "frame.sceneUnavailable" in control and "frame.insets(panel.el)" in control
