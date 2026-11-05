"""The plan card lists each task's sources and highlights a web task that receives sources (P4, decision D16, manual use): the pure
rows of interface/js/cards/plan-rows.js and the markup of interface/js/cards/plan.js under the fake document. A plan that carries
no source is drawn exactly as before. No browser, no model, no service.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_sources.py
"""
from __future__ import annotations

import pytest

from test_interface_lobby import needs_node, run_node  # noqa: F401  (the Node runner and the fake document the Lobby's tests use)

ROWS = r"""
import * as rows from "@JS@/cards/plan-rows.js";

const hash = "0123456789abcdef".repeat(4);
const plan = { id: 22, kind: "plan", title: "Plan", body: "text", payload: { plan_sha256: hash, limits: {}, estimate: {},
  tasks: [{ key: "a", title: "Research", skill: "core-research", depends_on: [], milestone: false, web: true, sources: ["survey", "notes"] },
    { key: "b", title: "Analysis", skill: "biz-market-analysis", depends_on: ["a"], milestone: false, web: false, sources: ["survey"] },
    { key: "c", title: "Review", skill: "eng-review", depends_on: [], milestone: false, web: true },
    { key: "d", title: "Odd", skill: "x", depends_on: [], web: true, sources: "survey" },
    { key: "e", title: "Odder", skill: "x", depends_on: [], web: true, sources: [1, null, "", "ok"] }] } };
const table = rows.taskRows(plan);
const out = {};
out.rows = table.map((r) => [r.n, r.web, r.sources === undefined ? null : r.sources]);
out.keys = table.map((r) => Object.keys(r));
out.flags = table.map((r) => rows.webWithSources(r));
out.tails = table.map((r) => rows.stackedRow(r).tail);
out.sourcesOf = [rows.sourcesOf({}), rows.sourcesOf({ sources: null }), rows.sourcesOf({ sources: ["a", "b"] })];
out.note = rows.WEB_SOURCES_NOTE;
console.log(JSON.stringify(out));
"""

CARD = r"""
import { byClass, textOf } from "@FAKE@";
import { createPlanCard } from "@JS@/cards/plan.js";

const client = { approve: async () => ({ job: "j" }), reject: async () => ({}), pollJob: async () => ({ state: "done", result: {} }) };
const hash = "cd".repeat(32);
const item = (tasks) => ({ id: 9, kind: "plan", title: "Plan: x", body: "", payload: { plan_sha256: hash, tasks, limits: { timeout_seconds: 60, retries: 1 }, estimate: { runs_at_least: 1 } },
  payload_sha256: hash, status: "open", actions: ["approved", "rejected"], agent: null, task_id: 5, run_id: null, created_at: "2026-10-09T09:00:00Z" });
const build = (tasks) => createPlanCard({ api: client, project: "p", item: item(tasks), now: new Date("2026-10-09T12:00:00Z"), onChanged: async () => {}, signal: undefined, announce() {} });
const card = build([
  { key: "a", title: "Research", skill: "core-research", depends_on: [], web: true, sources: ["survey"] },
  { key: "b", title: "Analysis", skill: "biz-market-analysis", depends_on: ["a"], web: false, sources: ["survey", "notes"] },
  { key: "c", title: "Review", skill: "eng-review", depends_on: [], web: true }]);
const items = byClass(card.el, "wb-plan-task");
const out = {};
out.items = items.map((li) => ({ flagged: (li.attrs.class || "").includes("wb-plan-task-web-sources"), text: textOf(li) }));
out.badges = byClass(card.el, "wb-plan-web-sources").map((n) => [textOf(n), n.attrs.title]);
out.notes = byClass(card.el, "wb-plan-web-sources-note").map(textOf);
const plain = build([{ key: "a", title: "Build", skill: "eng-implement", depends_on: [], web: true }]);
out.plain = { flagged: byClass(plain.el, "wb-plan-task-web-sources").length, badges: byClass(plain.el, "wb-plan-web-sources").length, tail: textOf(byClass(plain.el, "wb-plan-task")[0]) };
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_task_that_receives_sources_lists_their_ids_and_a_task_with_none_has_the_row_it_always_had(tmp_path):
    got = run_node(tmp_path, ROWS)
    assert got["rows"] == [["1", "yes", ["survey", "notes"]], ["2", "no", ["survey"]], ["3", "yes", None], ["4", "yes", None], ["5", "yes", ["ok"]]]
    assert got["keys"][2] == ["n", "task", "skill", "agent", "after", "milestone", "web"], "no source: the keys are those of the row before P4"
    assert got["keys"][0][-1] == "sources"
    assert got["flags"] == [True, False, False, False, True], "a web task with sources is flagged; a task without the web, or without sources, is not"
    assert got["tails"][0] == "After - · Milestone no · Web yes · Sources survey, notes"
    assert got["tails"][2] == "After - · Milestone no · Web yes" and got["tails"][1].endswith("· Web no · Sources survey")
    assert got["sourcesOf"] == [[], [], ["a", "b"]]
    assert "open network" in got["note"] and "your choice" in got["note"]


@needs_node
def test_the_plan_card_highlights_a_web_task_that_receives_sources_with_the_reason_before_the_button(tmp_path):
    got = run_node(tmp_path, CARD)
    assert [i["flagged"] for i in got["items"]] == [True, False, False]
    assert "Sources survey" in got["items"][0]["text"] and "Sources survey, notes" in got["items"][1]["text"] and "Sources" not in got["items"][2]["text"]
    assert got["badges"] == [["Web task with sources", got["notes"][0]]] and len(got["notes"]) == 1
    assert "open network" in got["notes"][0]
    assert got["plain"]["flagged"] == 0 and got["plain"]["badges"] == 0 and "Sources" not in got["plain"]["tail"]
