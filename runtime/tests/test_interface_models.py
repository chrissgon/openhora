"""Tests of the model section of the Agent tab (package P3, decision D38): a model that needs no consent is set with one button; one
that does shows the service's warning, an explicit "I consent" button and the terminal command; the button sends the model, the
agent's mode, the configuration's hash and the sha256 of the warning text as it is on the screen, and nothing else. Offline, with
the fake DOM of the other interface tests; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_models.py
"""
from __future__ import annotations

import hashlib
import json

from test_interface_adjustments import INTERFACE, run_node
from test_interface_floor import needs_node

WARNING = ("Your consent releases this agent's reviews without you on this model for every skill of the agent that is not proven on it; "
           "each run released because of your consent is recorded as autonomy by consent.")
CONFIG = "c" * 64

SCRIPT = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import * as fm from "@JS@/floor-model.js";
import { createAgentTab, sha256Hex } from "@JS@/floor/agent-tab.js";

const P = "0123456789ab";
const WARNING = @WARNING@;
const text = (n) => (n ? n.textContent : null);
const commands = [
  { model: "m", consent: true, command: "python3 /ck/cli.py set-model --project /work/shop --agent engineering --model m --consent --accept" },
  { model: "fm", consent: true, command: "python3 /ck/cli.py set-model --project /work/shop --agent engineering --model fm --consent --accept" },
  { model: "auto", consent: false, command: "python3 /ck/cli.py set-model --project /work/shop --agent engineering --model auto" },
  { model: "default", consent: false, command: "python3 /ck/cli.py set-model --project /work/shop --agent engineering --model default" },
];
const agent = (mode, extra = {}) => ({ name: "engineering", pack: "x", enabled: true, mode, acting_mode: mode, max_runs_per_day: 6, max_usd_per_day: 2, runs_today: 0, usd_today: 0,
  runs_without_cost: 0, queued: 0, held: 0, model: null, consent: null, consent_in_force: false, consent_needed: false, consent_warning: WARNING, config_sha256: "@CONFIG@",
  model_commands: commands, ...extra });
const task = { id: 4, key: "k", title: "T", skill: "s", state: "ready", note: null, agent: "engineering", requestId: 1, waiting_for: [] };
const view = (a, accepted = true) => fm.floor({ projects: [{ id: P, name: "n", config: { accepted } }], details: { [P]: { status: { requests: [{ id: 1, title: "R", state: "ready", tasks: [task] }], pending: [], held: [] }, agents: [a] } }, tasks: {}, loaded: true }, P, "engineering", {});

const calls = { give: [], set: [], refresh: 0 };
let allowed = true;
let fail = null;
const api = {
  setMode: async () => ({}), retry: async () => ({}), goAhead: async () => ({}), handOver: async () => ({}),
  setModel: async (...args) => { calls.set.push(args); },
  giveConsent: async (...args) => { if (fail) throw new Error(fail); calls.give.push(args); },
};
const tab = createAgentTab({ project: P, agent: "engineering", api, refresh() { calls.refresh += 1; }, now: () => new Date(), can: (op) => (op === "give-consent" ? allowed : true) });
const out = {};
const read = () => {
  const box = find(tab.el, ".wb-model-box");
  return { visible: (sel) => { const n = find(box, sel); return Boolean(n) && !n.hidden; } };
};
const state = () => {
  const r = read();
  return { warning: r.visible(".wb-wider-note"), consent: r.visible("button[data-key=give-consent]"), set: r.visible("button[data-key=set-model]"), code: r.visible("code[data-key=model-command]"),
    copy: r.visible("button[data-key=model-copy]"), line: text(find(tab.el, ".wb-model-consent-line")), failure: (() => { const n = find(tab.el, ".wb-model-box .wb-card-error"); return n && !n.hidden ? text(n) : null; })() };
};
const choose = async (model) => {
  const select = find(tab.el, ".wb-model-box select");
  select.value = model;
  (select.listeners.change || []).forEach((fn) => fn());
  await settle();
};

tab.update(view(agent("autonomous")));
await settle();
await choose("fm");
out.consentModel = state();
out.warningText = text(find(tab.el, ".wb-model-warning"));
await choose("auto");
out.autoModel = state();
await choose("fm");
find(tab.el, "button[data-key=give-consent]").click();
await settle();
out.gave = calls.give;
out.refreshed = calls.refresh;
out.setCalls = calls.set;
out.expectedHash = await sha256Hex(WARNING);
fail = "the warning the page showed is not the text this service holds";
find(tab.el, "button[data-key=give-consent]").click();
await settle();
out.failed = state().failure;
fail = null;
allowed = false;
tab.update(view(agent("autonomous", { model: "fm" })));
await settle();
await choose("m");
out.withheld = state();
allowed = true;
tab.update(view(agent("milestones", { model_commands: commands.map((c) => ({ ...c, consent: false })) })));
await settle();
await choose("fm");
out.below = (() => { const s = state(); return { consent: s.consent, set: s.set, warning: s.warning }; })();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_model_that_needs_the_consent_shows_the_warning_the_button_and_the_command_and_the_button_sends_the_four_values(tmp_path):
    script = SCRIPT.replace("@WARNING@", json.dumps(WARNING)).replace("@CONFIG@", CONFIG)
    got = run_node(tmp_path, script)
    c = got["consentModel"]
    assert c["warning"] and c["consent"] and not c["set"] and c["code"] and c["copy"], c
    assert got["warningText"] == WARNING, "the text on the screen is the service's, once"
    a = got["autoModel"]
    assert (a["consent"], a["warning"], a["code"], a["set"]) == (False, False, False, True), "a model that needs no consent is set with one button"
    expected = hashlib.sha256(WARNING.encode("utf-8")).hexdigest()
    assert got["expectedHash"] == expected
    assert got["gave"] == [["0123456789ab", "engineering", {"model": "fm", "mode": "autonomous", "config_sha256": CONFIG, "warning_sha256": expected}]]
    assert got["refreshed"] == 1 and got["setCalls"] == [], "the consent button sends the consent and no setModel"
    assert got["failed"] == "the warning the page showed is not the text this service holds", "the service's refusal is shown"
    w = got["withheld"]
    assert w["consent"] is False and w["warning"] is True and "give-consent" in (w["line"] or ""), "the policy withholds it from the page: the warning and the command stay, the button does not"
    b = got["below"]
    assert b["consent"] is False and b["warning"] is False and b["set"] is True, "below the autonomous modes a model needs no consent"


def test_the_page_builds_no_consent_of_its_own_it_hashes_the_text_it_shows_and_sends_what_the_service_gave():
    source = (INTERFACE / "js" / "floor" / "agent-tab.js").read_text(encoding="utf-8")
    assert "warnText.textContent" in source and "sha256Hex" in source
    assert "agent.config_sha256" in source and "agent.mode" in source
    api = (INTERFACE / "js" / "api.js").read_text(encoding="utf-8")
    assert "/consent`" in api and "warning_sha256" in api and "accept" not in api.split("export function giveConsent")[1].split("}\n")[0]


LABELS = r"""
import { agentModelLabel, communityWords, modelLabel, modelOptions } from "@JS@/models.js";

const price = { input: 0.14, output: 0.42, accessed: "2026-10-15", age_days: 0, stale: false };
const line = (model, extra = {}) => ({ model, skills: 5, reliable: 5, community_only: 0, expected_cost: 0.00042, band: "reliable", price, ...extra });
const out = {};
out.request = modelOptions([line("cheap"), line("dear", { reliable: 3, expected_cost: 0.0123 }), line("shared", { community_only: 5 }), line("bare", { price: null, expected_cost: null, reliable: 0 })], null, "cheap").map((o) => [o.value, o.label]);
out.noRecommendation = modelLabel(line("cheap"));
out.stale = modelLabel(line("old", { price: { ...price, stale: true, age_days: 106, accessed: "2026-07-01" } }));
out.community = [communityWords(line("a", { community_only: 1 })), communityWords(line("a", { community_only: 5 })), communityWords(line("a"))];
out.agent = [line("cheap"), line("dear", { reliable: 3 }), line("shared", { community_only: 5 }), { model: "auto" }, { model: "default" }, { model: "bare-old-service" }]
  .map((l) => agentModelLabel(l, "cheap"));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_pickers_say_each_models_band_its_cost_a_recommendation_and_that_a_community_only_pair_is_reviewed(tmp_path):
    got = run_node(tmp_path, LABELS)
    request = dict(got["request"])
    assert request[""].startswith("Chosen for you") and request["auto"].startswith("auto")
    assert request["cheap"] == ("cheap · reliable for 5 of 5 skills · about $0.00042 a run · $0.14 in, $0.42 out per million tokens (read 2026-10-15) · recommended"), request["cheap"]
    assert request["dear"].startswith("dear · reliable for 3 of 5 skills · about $0.01 a run") and "recommended" not in request["dear"]
    assert request["shared"].endswith("5 skills through community evidence alone: output reviewed") and "recommended" not in request["shared"]
    assert request["bare"] == "bare · reliable for 0 of 5 skills · no cost estimate: no price known · no price known"
    assert got["noRecommendation"].count("recommended") == 0
    assert "stale (106 days)" in got["stale"]
    assert got["community"] == ["one skill through community evidence alone: output reviewed", "5 skills through community evidence alone: output reviewed", ""]
    assert got["agent"] == ["cheap · reliable for 5 of 5 skills · about $0.00042 a run · recommended", "dear · reliable for 3 of 5 skills · about $0.00042 a run",
                            "shared · reliable for 5 of 5 skills · about $0.00042 a run · 5 skills through community evidence alone: output reviewed",
                            "auto (the cheapest model that is reliable for each skill)", "default (the request's, else the project's)", "bare-old-service"]


def test_the_models_module_decides_nothing_it_only_words_what_the_service_sent():
    source = (INTERFACE / "js" / "models.js").read_text(encoding="utf-8")
    assert "recommended_model" in source or "recommended" in source
    assert "Math.min" not in source and ".sort(" not in source, "no ranking on the page: the recommendation is the service's"
