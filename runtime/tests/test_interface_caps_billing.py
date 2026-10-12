"""Tests of the page for package ADJ-R3 (row A-38): the two meters are named by what they count ("Runs today", "Spend today"), say the
billing in their tooltip, and a meter is drawn only when its cap is in use for the project (`caps_in_use` of the `agents` read; both
when the service sends none). No browser and no model: the modules run under Node with a fake document, as the other page tests do.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_caps_billing.py
"""
from __future__ import annotations

import pytest

from test_interface_plates_meters import NODE, needs_node, run_node
import standin_tree as st

JS = st.REPO / "interface" / "js"

WORDS = r"""
import * as format from "@JS@/format.js";

const out = {};
out.words = format.METER_WORDS;
out.tips = format.METER_TIPS;
out.frozen = [Object.isFrozen(format.METER_WORDS), Object.isFrozen(format.METER_TIPS)];
out.use = [
  format.metersInUse(undefined), format.metersInUse({}), format.metersInUse({ caps_in_use: { runs: true, spend: false } }),
  format.metersInUse({ caps_in_use: { runs: false, spend: true } }), format.metersInUse({ caps_in_use: { runs: true, spend: true } }),
  format.metersInUse({ caps_in_use: { runs: false, spend: false } }), format.metersInUse({ caps_in_use: "yes" }),
];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_meters_are_named_by_what_they_count_and_the_tooltips_say_the_billing(tmp_path):
    got = run_node(tmp_path, WORDS)
    assert got["words"] == {"runs": "Runs today", "spend": "Spend today"}
    assert got["tips"] == {
        "runs": "Counted against the cap of runs per day: runs on a subscription or free credential.",
        "spend": "Counted against the cap of dollars per day: runs on a metered credential (an API key); a run whose cost is not recorded yet counts at the per-run limit."}
    assert got["frozen"] == [True, True]


@needs_node
def test_a_meter_is_in_use_unless_the_service_says_it_is_not(tmp_path):
    both, only_runs, only_spend, neither = ({"runs": True, "spend": True}, {"runs": True, "spend": False},
                                            {"runs": False, "spend": True}, {"runs": False, "spend": False})
    got = run_node(tmp_path, WORDS)["use"]
    assert got == [both, both, only_runs, only_spend, both, neither, both], \
        "no caps_in_use (an older service) shows both; only an explicit false hides a meter"


FLOOR = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import * as fm from "@JS@/floor-model.js";
import * as model from "@JS@/model.js";
import * as format from "@JS@/format.js";
import * as control from "@JS@/views/control-model.js";
import { createKpis } from "@JS@/frame/kpis.js";
import { plateNode } from "@JS@/scene/plates.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";

const P = "0123456789ab";
const agent = (extra = {}) => ({ name: "engineering", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2,
  runs_today: 3, usd_today: 0.14, usd_recorded: 0.14, usd_reserved: 0, runs_total_today: 3, runs_without_cost: 0, queued: 0, held: 0, wider: [],
  billing: { runs: ["subscription", "free"], spend: ["metered"] }, ...extra });
const USE = { both: { runs: true, spend: true }, runs: { runs: true, spend: false }, spend: { runs: false, spend: true } };
const names = (m) => ({ runs: m.runs ? [m.runs.label, m.runs.text] : null, spend: m.spend ? [m.spend.label, m.spend.text] : null });
const out = {};

// the Agent tab's meters (floor-model.meters): one meter when the other cap is not in use, both when both are, both from an older service
out.meters = {};
for (const [key, use] of Object.entries(USE)) out.meters[key] = names(fm.meters(agent({ caps_in_use: use })));
out.meters.older = names(fm.meters(agent()));
out.metersIn = fm.meters(agent({ caps_in_use: USE.runs })).inUse;

// the plate, the floors list row and the compact card
const rowOf = (use) => fm.floorRow(agent({ caps_in_use: use }), null, { accepted: true, project: "p", number: 1 });
const plateMeters = (use) => all(plateNode(fm.plateOf(rowOf(use)), {}), ".wb-plate-meter").map((n) => n.textContent);
out.plate = { both: plateMeters(USE.both), runs: plateMeters(USE.runs), spend: plateMeters(USE.spend), older: plateMeters(undefined) };
out.card = { both: fm.cardOf(rowOf(USE.both)).runsLine, runs: fm.cardOf(rowOf(USE.runs)).runsLine, spend: fm.cardOf(rowOf(USE.spend)).runsLine };
out.row = { runs: [rowOf(USE.runs).tip, rowOf(USE.runs).linkName, rowOf(USE.runs).meters], spend: [rowOf(USE.spend).tip, rowOf(USE.spend).linkName, rowOf(USE.spend).meters],
  both: [rowOf(USE.both).tip, rowOf(USE.both).linkName, rowOf(USE.both).meters] };

// the KPI sums and the cards
const detail = (...agents) => ({ projects: [{ id: P }], details: { [P]: { agents } } });
out.sums = {
  both: model.kpiSums(detail(agent({ caps_in_use: USE.both })), null).inUse,
  runs: model.kpiSums(detail(agent({ caps_in_use: USE.runs }), agent({ name: "design", caps_in_use: USE.runs })), null).inUse,
  mixed: model.kpiSums(detail(agent({ caps_in_use: USE.runs }), agent({ name: "design", caps_in_use: USE.spend })), null).inUse,
  older: model.kpiSums(detail(agent()), null).inUse,
  none: model.kpiSums(detail(), null).inUse,
};
const kpis = createKpis();
const cards = () => all(kpis.el, ".pui-card");
const shown = (sums) => { kpis.update(sums); return cards().map((c) => [c.attrs["aria-label"], c.hidden]); };
const base = { decisions: 2, runs: 3, runsCap: 8, usd: 0.14, usdCap: 2, usdRecorded: 0.14, usdReserved: 0, runsTotal: 3 };
out.kpis = { both: shown({ ...base, inUse: USE.both }), runs: shown({ ...base, inUse: USE.runs }), spend: shown({ ...base, inUse: USE.spend }), older: shown(base) };
out.kpiLoading = (() => { kpis.update(null, "loading"); return cards().map((c) => c.hidden); })();

// the Agent tab, drawn
const tab = createAgentTab({ project: "p", agent: "engineering", api: { setMode: async () => ({}), retry: async () => ({}), handOver: async () => ({}) }, refresh: () => {}, now: () => new Date() });
const tabCells = (use) => {
  const snapshot = { projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [], pending: [], held: [] }, agents: [agent({ caps_in_use: use })] } }, tasks: {}, loaded: true };
  tab.update(fm.floor(snapshot, P, "engineering", {}));
  return all(tab.el, ".wb-meter-cell").map((c) => c.attrs["aria-label"]);
};
out.tab = { both: tabCells(USE.both), runs: tabCells(USE.runs), spend: tabCells(USE.spend), both_again: tabCells(USE.both) };

// the Control room's caps line
const caps = [{ agent: "engineering", max_runs_per_day: 12, max_usd_per_day: 4 }, { agent: "marketing", max_runs_per_day: 6, max_usd_per_day: 3.5 }];
const bare = { usd_recorded: undefined, usd_reserved: undefined, runs_total_today: undefined };      // no split, no total: the plain line
const used = (use) => [agent({ runs_today: 5, usd_today: 1.87, ...bare, caps_in_use: use }), agent({ name: "marketing", runs_today: 2, usd_today: 0.5, ...bare, caps_in_use: use })];
out.caps = { both: control.capsLine(caps, used(USE.both)), runs: control.capsLine(caps, used(USE.runs)), spend: control.capsLine(caps, used(USE.spend)),
  noAgents: control.capsLine(caps, null), none: control.capsLine([], used(USE.both)) };
out.total = fm.meters(agent()).runsTotal;
out.capsTotal = control.capsLine(caps.slice(0, 1), [agent({ runs_today: 5, usd_today: 1.87, usd_recorded: undefined, usd_reserved: undefined, caps_in_use: USE.both })]).text;
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def floor(tmp_path_factory):
    if NODE is None:
        pytest.skip("node is not installed")
    return run_node(tmp_path_factory.mktemp("caps"), FLOOR)


def test_the_agent_tab_draws_a_meter_only_for_a_cap_in_use(floor):
    m = floor["meters"]
    assert m["both"] == {"runs": ["Runs today", "3 / 8"], "spend": ["Spend today", "$0.14 / $2.00"]}
    assert m["runs"] == {"runs": ["Runs today", "3 / 8"], "spend": None}
    assert m["spend"] == {"runs": None, "spend": ["Spend today", "$0.14 / $2.00"]}
    assert m["older"] == m["both"], "an older service sends no caps_in_use: both meters"
    assert floor["metersIn"] == {"runs": True, "spend": False}
    assert [c.split(" ")[0] + " " + c.split(" ")[1] for c in floor["tab"]["both"]] == ["Runs today", "Spend today", "Queued 0"]
    assert floor["tab"]["runs"] == ["Runs today 3 / 8", "Queued 0"] and floor["tab"]["spend"] == ["Spend today $0.14 / $2.00", "Queued 0"]
    assert floor["tab"]["both_again"] == floor["tab"]["both"], "a meter that was hidden is drawn again when its cap comes into use"


def test_the_plate_the_row_and_the_card_follow_caps_in_use(floor):
    assert [len(floor["plate"][k]) for k in ("both", "runs", "spend", "older")] == [2, 1, 1, 2]
    # R-25, R-5/R-6: the plate's meters are named as the round names them: "3 / 8 runs" and "$0.14 / $2.00" (the sentence of what each counts is the tooltip)
    assert floor["plate"]["runs"][0] == "3 / 8 runs" and floor["plate"]["spend"][0] == "$0.14 / $2.00"
    # building.html at 375 px: the card's line is the runs and the spend alone (the recorded note is the line's tooltip)
    assert floor["card"]["both"] == "runs 3 / 8 · spend $0.14 / $2.00"
    assert floor["card"]["runs"] == "runs 3 / 8" and floor["card"]["spend"] == "spend $0.14 / $2.00"
    row = floor["row"]
    assert row["both"][0].endswith("3 of 8 runs") and "of 8 runs, $0.14 of $2.00" in row["both"][1] and row["both"][2] == "runs 3 / 8 · $0.14 of $2.00"
    assert row["runs"][0].endswith("3 of 8 runs") and row["runs"][1].endswith("3 of 8 runs") and "$" not in row["runs"][1] and row["runs"][2] == "runs 3 / 8"
    assert row["spend"][0].endswith("$0.14 of $2.00") and row["spend"][1].endswith("$0.14 of $2.00") and " runs" not in row["spend"][1]
    assert row["spend"][2] == "$0.14 of $2.00"


def test_the_kpi_cards_hide_the_card_of_a_cap_not_in_use(floor):
    k = floor["kpis"]
    hidden = lambda state: [h for _, h in state]
    # R-5: two cards (Runs today, Spend today); "Open decisions" is gone, its count is on "Waiting for you"
    assert hidden(k["both"]) == [False, False] and hidden(k["older"]) == [False, False]
    assert hidden(k["runs"]) == [False, True] and hidden(k["spend"]) == [True, False]
    assert k["runs"][0][0] == "Runs today 3 of 8" and k["spend"][1][0] == "Spend today $0.14 of $2.00 cap"
    assert floor["kpiLoading"] == [False, False], "while loading nothing is hidden: the cards read as loading"


def test_the_sums_are_in_use_when_any_agent_has_the_cap_in_use(floor):
    s = floor["sums"]
    both, runs = {"runs": True, "spend": True}, {"runs": True, "spend": False}
    assert s["both"] == both and s["runs"] == runs and s["older"] == both and s["none"] == both
    assert s["mixed"] == both, "one agent's dollar meter is enough for the project's card"


def test_the_caps_line_names_runs_and_spend_and_leaves_out_a_part_not_in_use(floor):
    c = floor["caps"]
    assert c["both"]["text"] == "Caps · engineering: runs 5 / 12, spend $1.87 / $4.00; marketing: runs 2 / 6, spend $0.50 / $3.50"
    assert c["runs"]["text"] == "Caps · engineering: runs 5 / 12; marketing: runs 2 / 6"
    assert c["spend"]["text"] == "Caps · engineering: spend $1.87 / $4.00; marketing: spend $0.50 / $3.50"
    assert c["noAgents"]["text"] == "Caps · engineering: runs - / 12, spend - / $4.00; marketing: runs - / 6, spend - / $3.50"
    assert c["none"] is None
    assert c["both"]["title"] == "Counted against the cap of runs per day: runs on a subscription or free credential. Counted against the cap of dollars per day: runs on a metered credential (an API key); a run whose cost is not recorded yet counts at the per-run limit."


def test_the_page_names_no_tier_for_a_cap_and_the_state_words_say_runs_and_spend():
    text = "\n".join((JS / name).read_text(encoding="utf-8") for name in
                     ("format.js", "floor-model.js", "frame/kpis.js", "scene/plates.js", "floor/agent-tab.js", "views/control-model.js"))
    for old in ("Reference-model runs", "Floor-model spend", "reference-model runs", "floor-model spend"):
        assert old not in text, old
    model = (JS / "floor-model.js").read_text(encoding="utf-8")
    assert '"cap: runs per day": "The agent used all its runs for today."' in model
    assert '"cap: usd per day": "The agent used all its spend for today."' in model


def test_the_plain_total_is_named_all_runs_today_so_it_does_not_share_the_meters_name(floor):
    assert floor["total"] == "All runs today: 3"
    assert floor["capsTotal"] == "Caps · engineering: runs 5 / 12, spend $1.87 / $4.00, All runs today: 3"
