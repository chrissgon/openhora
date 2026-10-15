// The check for the website hand-off (docs/design/handoff/website.md, Acceptance).
// Run from the repository root:  node --test site/tests/website.test.mjs
// One page only:                  node --test --test-name-pattern="^home " site/tests/website.test.mjs
// Needs Node 24, Python 3 and Chromium or Chrome (CHROMIUM=/path to override /usr/bin/chromium and the macOS Chrome). No package is installed.
// The demo of the Interface page is not committed: the tests build it first with scripts/build_demo.py into a temporary folder and serve that
// folder at /demo/, so they test what the deploy (netlify.toml) serves.
//
// For every page of the hand-off it asserts:
//   1. the page file exists in site/ and is served at the route the flows give it (IA-1 to IA-11);
//   2. its text matches the hand-off's exported page (fixtures/handoff/<page>.html, the unmodified
//      source.html of the archive), apart from the edits the hand-off itself orders (TEXT_EDITS below);
//   3. at 1280 and 375 px wide, in light and in dark, no horizontal scroll appears: not on the page,
//      and not in any element that scrolls sideways (a code block must wrap).
import { test, describe, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SITE = path.resolve(HERE, "..");
const FIXTURES = path.join(HERE, "fixtures", "handoff");
const REPO = path.resolve(SITE, "..");
const CHROMIUM = process.env.CHROMIUM || ["/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find((p) => fs.existsSync(p)) || "/usr/bin/chromium";
// The headers the deploy sends, read from netlify.toml, so that every test runs under the same policy.
const HEADERS = (() => {
  const toml = fs.readFileSync(path.join(REPO, "netlify.toml"), "utf8");
  const out = {};
  for (const m of toml.matchAll(/^\s*([A-Za-z][A-Za-z-]+)\s*=\s*"((?:[^"\\]|\\.)*)"\s*$/gm)) if (/^(Content-Security-Policy|X-Content-Type-Options|Referrer-Policy)$/.test(m[1])) out[m[1]] = m[2];
  return out;
})();
// The demo, built from the interface of this checkout by the script the deploy runs; set by before().
let DEMO = null;
function buildDemo() {
  const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "site-demo-")), "demo");
  const r = spawnSync("python3", [path.join(REPO, "scripts", "build_demo.py"), "--out", out], { cwd: REPO, encoding: "utf8" });
  assert.equal(r.status, 0, `scripts/build_demo.py failed: ${r.stderr}`);
  return out;
}

// fixture = the export folder's name in the hand-off; file = the page file in site/; route = the address.
const PAGES = [
  { fixture: "home", file: "index.html", route: "/" },
  { fixture: "proof", file: "proof.html", route: "/proof" },
  { fixture: "first-steps", file: "first-steps.html", route: "/first-steps" },
  { fixture: "how-its-built", file: "how-it-is-built.html", route: "/how-it-is-built" },
  { fixture: "interface", file: "interface.html", route: "/interface" },
  { fixture: "glossary", file: "glossary.html", route: "/glossary" },
  { fixture: "404", file: "404.html", route: "/404.html" },
];
const WIDTHS = [
  { width: 1280, height: 900, mobile: false },
  { width: 375, height: 812, mobile: true },
];
const MODES = ["light", "dark"];

// Edits to the exported text that the hand-off orders (Deviations marked "fix in code", and the
// pieces it says are not handed off). `match` is one entry or a run of consecutive entries; it must
// occur exactly `count` times (default once), so the table cannot go stale.
//   replace: the matched entries become `with` (an entry or a list; an empty list removes them);
//   insertAfter: the matched entries are followed by `with`.
// M-42 (decided by the person, 2026-10-11): the navigation link reads "How it's built" in the header and in the footer
// (two links per page); the page's own heading and title keep "How openhora is built".
const NAV_LABEL = "How it's built";
const NAV_EDIT = { op: "replace", ref: "M-42: the navigation link \"How openhora is built\" reads \"How it's built\" in the header and the footer", count: 2,
  match: ["First steps", "How openhora is built", "Interface"], with: ["First steps", NAV_LABEL, "Interface"] };
// The hand-off's link to its screenshots' notes points at a document that is not in the repository; the site links the interface's own description instead.
const SHOTS_EDIT = (count) => ({ op: "replace", ref: "The link text \"interface-shots\" reads \"interface/README.md\": it links interface/README.md, which is in the repository", count,
  match: ["interface-shots"], with: ["interface/README.md"] });
// P3b (decision D34, principle 10): the pages name no reference model, floor model or tier, and publish the bands the evidence gives. Each entry is the run of text
// entries of the hand-off (after the edits above it) that the page now words differently; the new text is in site/*.html.
const P3B_EDITS = {
  "home": [
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["One tick per skill. Outer ring, reference model claude-sonnet-5-5: 48 reliable, 0 watch, 0 needs a test. Inner ring, floor model openrouter/deepseek/deepseek-v4.1-flash: 43 reliable, 2 watch, 3 needs a test. Snapshot 2026-10-10.", "reference model · claude-sonnet-5-5", "floor model · openrouter/deepseek/deepseek-v4.1-flash", "outer", "reliable 48", "watch 0", "needs a test 0"], "with": ["One tick per skill. Outer ring, lab model claude-sonnet-5-5: 0 reliable, 0 watch, 48 needs a test. Inner ring, lab model openrouter/deepseek/deepseek-v4.1-flash: 0 reliable, 0 watch, 48 needs a test. Snapshot 2026-10-15.", "lab model · claude-sonnet-5-5", "lab model · openrouter/deepseek/deepseek-v4.1-flash", "outer", "reliable 0", "watch 0", "needs a test 48"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["reliable 43", "watch 2", "needs a test 3", "one tick per skill · of 48 skills · snapshot 2026-10-10"], "with": ["reliable 0", "watch 0", "needs a test 48", "one tick per skill · of 48 skills · snapshot 2026-10-15"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["decides which model runs a skill and what may run unattended."], "with": ["decides what may run unattended and which model", "auto", "picks for a skill."]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["Reference model"], "with": ["Lab model"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["reliable", "of 48 skills · 2026-10-10", "reliable 48"], "with": ["needs a test", "of 48 skills · 2026-10-15", "reliable 0"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["needs a test 0", "Floor model"], "with": ["needs a test 48", "needs a test", "47 skills: guard assertions have no run in the current set", "needs a test", "mkt-social-copy: no full test of version 2.x", "Lab model"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["43", "reliable", "of 48 skills · 2026-10-10", "reliable 43", "watch 2", "needs a test 3", "watch", "core-skill-creator, eng-docs"], "with": ["48"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["design-ux-flows, eng-codebase-map, mkt-social-copy"], "with": ["of 48 skills · 2026-10-15", "reliable 0", "watch 0", "needs a test 48", "needs a test", "47 skills: no baseline in force on this model", "needs a test", "mkt-social-copy: no full test of version 2.x"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["2026-10-10"], "with": ["2026-10-15"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["549 per model"], "with": ["141 per model"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": [": \"reliable\","], "with": [": \"needs a test\","]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["\"needs a test\"", ": 0,"], "with": ["\"needs a test\"", ": 48,"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": [": 48"], "with": [": 0"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["status · floor model"], "with": ["status · lab model"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": [": \"mkt-social-copy\","], "with": [": \"biz-icp-positioning\","]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": [": \"guard assertion(s) 2.3 failed in the current set\","], "with": [": \"no baseline in force on openrouter/deepseek/deepseek-v4.1-flash for case(s) 1, 2, 3\","]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["In openhora, recorded test evidence, not a person's opinion, decides which model runs a skill and what may happen without a person."], "with": ["In openhora, recorded test evidence, not a person's opinion, decides what may happen without a person and which model", "auto", "picks for a skill; a model you name runs supervised until it is proven or you consent."]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["lines 2 to 13"], "with": ["lines 2 to 7"]},
    {"op": "remove", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["\"strong_model\"", ": \"claude-sonnet-5-5\",", "4", "\"floor_model\"", ": \"openrouter/deepseek/deepseek-v4.1-flash\",", "8"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": [": \"claude-sonnet-5-5\",", "9"], "with": [": \"claude-sonnet-5-5\",", "3"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["10", "\"strong_tolerance\""], "with": ["4", "\"tolerance\""]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["13"], "with": ["7"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["reliable", "claude-sonnet-5-5 · reference model · snapshot 2026-10-10"], "with": ["needs a test", "claude-sonnet-5-5 · lab model · snapshot 2026-10-15"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["86 files, 2,005 run lines at the snapshot of 2026-10-10.", "Floor model · 2026-10-10 · not reliable", "watch", "core-skill-creator", "watch", "eng-docs"], "with": ["86 files, 2,005 run lines at the snapshot of 2026-10-15.", "Lab models · 2026-10-15 · not reliable"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["design-ux-flows"], "with": ["claude-sonnet-5-5: 47 skills, guard assertions have no run in the current set"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["eng-codebase-map"], "with": ["openrouter/deepseek/deepseek-v4.1-flash: 47 skills, no baseline in force on this model"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; one ring and one figure for each lab model, with the bands the evidence of 2026-10-15 gives (decision D34, principle 10)", "match": ["mkt-social-copy"], "with": ["mkt-social-copy: no full test of version 2.x"]},
  ],
  "proof": [
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["In openhora, recorded test evidence, not a person's opinion, decides which model runs a skill and what may happen without a person."], "with": ["In openhora, recorded test evidence, not a person's opinion, decides what may happen without a person and which model", "auto", "picks for a skill; a model you name runs supervised until it is proven or you consent."]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["reference model", "reliable 48"], "with": ["lab model", "reliable 0"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["needs a test 0"], "with": ["needs a test 48"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["floor model", "reliable 43", "watch 2", "needs a test 3", "of 48 skills · snapshot 2026-10-10 · last full tests 2026-10-04 · 549 current-set runs per model"], "with": ["lab model", "reliable 0", "watch 0", "needs a test 48", "of 48 skills · snapshot 2026-10-15 · last full tests 2026-10-04 · 141 current-set runs per model"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["reference model, floor model, grader, threshold 0.8, tolerance 0.05, 3 runs per case"], "with": ["lab models, grader, threshold 0.8, tolerance 0.05, 3 runs per case"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["Pick one of the 48 skills. The runtime runs a skill on the floor model only while its band there is"], "with": ["Pick one of the 48 skills. A band is kept for each lab model. A model you name runs there, supervised unless the skill is proven on it or you consented for the agent;", "auto", "picks the cheapest model whose band is"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["; otherwise on the reference model ("], "with": ["("]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["2.2.0"], "with": ["2.3.0"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["mkt-social-copy", "1.0.0", "mkt-vote-round", "1.0.0"], "with": ["mkt-social-copy", "2.0.0", "mkt-vote-round", "1.1.0"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["v1.0.0 · last full test 2026-10-04, passed"], "with": ["v2.0.0 · last full test none"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["reference · claude-code", "reliable", "0.77", "0.92", "12", "passed, 0.97 vs 0.57"], "with": ["claude-code", "needs a test", "no evidence on this model", "n/a", "n/a", "0", "-"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["floor · agents-dir"], "with": ["agents-dir"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["guard assertion(s) 2.3 failed in the current set", "0.70", "0.87", "12", "passed, 0.91 vs 0.65", "The runtime runs it on", "claude-sonnet-5-5", "reference model"], "with": ["no evidence on this model", "n/a", "n/a", "0", "-", "Released without review on", "no lab model", "supervised"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["the band on the floor model is needs a test."], "with": ["no lab model has a reliable band for it: a run waits for your review, whichever model you name."]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["7b67e014416f", "; the bands agree with the snapshot of 2026-10-10 (", "facts.md", ")."], "with": ["55fb026c55ed", "; the bands agree with the snapshot of 2026-10-15."]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["A full test passes when the mean with the skill on the reference model is at the threshold (0.8) or above and is not below the mean of the baselines by more than the tolerance (0.05); both means are taken per case first. Move the runs."], "with": ["A full test passes when the mean with the skill on a lab model is at the threshold (0.8) or above and is not below the mean of the baselines by more than the tolerance (0.05); both means are taken per case first. Move the runs."]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["floor model", "watch", "core-skill-creator, eng-docs"], "with": ["lab model"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["design-ux-flows, eng-codebase-map, mkt-social-copy", "2,005 run lines, 2026-10-03 to 2026-10-07 · snapshot 2026-10-10"], "with": ["47 skills: no baseline in force on this model", "claude-sonnet-5-5", "lab model", "needs a test", "47 skills: guard assertions have no run in the current set", "needs a test", "mkt-social-copy, on both: no full test of version 2.x", "2,005 run lines, 2026-10-03 to 2026-10-07 · snapshot 2026-10-15"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["# 86 files, 2,005 run lines at the snapshot of 2026-10-10"], "with": ["# 86 files, 2,005 run lines at the snapshot of 2026-10-15"]},
    {"op": "replace", "ref": "P3b: no reference model and no floor model; the bands of each lab model from the evidence of 2026-10-15, and the rule of model choice as P3 made it (decision D34, principle 10)", "match": ["the per-model table: the floor model's watch and needs a test rows beside the reliable ones"], "with": ["the per-model table: one row for each skill and lab model, with its band and its cause"]},
  ],
  "glossary": [
    {"op": "replace", "ref": "P3b: the entries reference model and floor model give way to lab model and model choice (decision D34)", "match": ["reference model", "floor model"], "with": ["lab model", "model choice"]},
    {"op": "replace", "ref": "P3b: the entries reference model and floor model give way to lab model and model choice (decision D34)", "match": ["The rule a full test passes or fails: on the reference model the mean with the skill is at the threshold (0.8) or above and is not below the mean without the skill by more than the tolerance (0.05). A partial test never moves the gate."], "with": ["The rule a full test passes or fails: on a lab model the mean with the skill is at the threshold (0.8) or above and is not below the mean without the skill by more than the tolerance (0.05). A partial test never moves the gate."]},
    {"op": "replace", "ref": "P3b: the entries reference model and floor model give way to lab model and model choice (decision D34)", "match": ["reference model", "The model the bands and the gate are computed on, named in", "evals/eval-gate.json", "("], "with": ["lab model", "A model the lab measures, listed in", "lab_models", "of", "evals/eval-gate.json", "with the adapter that runs it ("]},
    {"op": "replace", "ref": "P3b: the entries reference model and floor model give way to lab model and model choice (decision D34)", "match": ["at the snapshot)."], "with": ["and", "openrouter/deepseek/deepseek-v4.1-flash", "at the snapshot). Every lab model gets its own band, gate and score for each skill, computed by the same rules; none is ranked above another."]},
    {"op": "replace", "ref": "P3b: the entries reference model and floor model give way to lab model and model choice (decision D34)", "match": ["the reference model"], "with": ["a measured model"]},
    {"op": "replace", "ref": "P3b: the entries reference model and floor model give way to lab model and model choice (decision D34)", "match": ["floor model", "An inexpensive hosted open-weight model measured the same way (", "openrouter/deepseek/deepseek-v4.1-flash", "at the snapshot). Its results decide only where the runtime may run a skill: on the floor model only while the skill's band on it is", "reliable", "."], "with": ["model choice", "Which model runs a task. A model named on a request, a task or an agent runs there; it runs supervised and marked unproven unless the skill is proven on it or the agent holds your consent.", "auto", "picks the cheapest model whose band for the skill is", "reliable", ". A band informs and ranks; it does not stop a model you chose."]},
    {"op": "replace", "ref": "P3b: the entries reference model and floor model give way to lab model and model choice (decision D34)", "match": ["the lower-cost model"], "with": ["choosing a model"]},
  ],
  "how-its-built": [
    {"op": "replace", "ref": "P3b: no reference model; auto picks the cheapest proven model (decision D34)", "match": ["the reference model's API-key credential route is not held by a key proxy, so limit L6 does not hold for it."], "with": ["the API-key credential route of a lab model's harness is not held by a key proxy, so limit L6 does not hold for it."]},
    {"op": "replace", "ref": "P3b: no reference model; auto picks the cheapest proven model (decision D34)", "match": ["the proof decides which model runs each skill, the cheapest proven"], "with": ["the proof decides which model", "auto", "picks for each skill, the cheapest proven"]},
  ],
  "interface": [
    {"op": "replace", "ref": "P3b: the Skills tab shows the band of each lab model, not of a model tier (decision D34)", "match": ["[alt] The Control room, Skills tab: the workbench's own skills with version, area and the band of each model tier, at the captured commit.", "[alt] The Control room, Skills tab: the workbench's own skills with version, area and the band of each model tier, at the captured commit.", "[alt] The Control room, Skills tab: the workbench's own skills with version, area and the band of each model tier, at the captured commit.", "[alt] The Control room, Skills tab: the workbench's own skills with version, area and the band of each model tier, at the captured commit."], "with": ["[alt] The Control room, Skills tab: the workbench's own skills with version, area and the band of each lab model, at the captured commit.", "[alt] The Control room, Skills tab: the workbench's own skills with version, area and the band of each lab model, at the captured commit.", "[alt] The Control room, Skills tab: the workbench's own skills with version, area and the band of each lab model, at the captured commit.", "[alt] The Control room, Skills tab: the workbench's own skills with version, area and the band of each lab model, at the captured commit."]},
  ],
};
const TEXT_EDITS = {
  home: [NAV_EDIT,
    { op: "replace", ref: "The Replay control is gone: the teaser's badge reads \"fictional project\"", match: ["Replay · fictional project"], with: ["fictional project"] },
    ...P3B_EDITS.home],
  proof: [NAV_EDIT, SHOTS_EDIT(1), ...P3B_EDITS.proof], "first-steps": [NAV_EDIT, SHOTS_EDIT(1)], "how-its-built": [NAV_EDIT, ...P3B_EDITS["how-its-built"]], glossary: [NAV_EDIT, ...P3B_EDITS.glossary], "404": [NAV_EDIT],
  interface: [NAV_EDIT, SHOTS_EDIT(5), ...P3B_EDITS.interface,
    { op: "insertAfter", ref: "DEV-7: the sentence that the interface runs on the person's machine and that the tour is a demo on fictional data",
      match: ["A person opens a local page and sees their projects as a small low-poly city: one building per project, one floor per area agent, an owl at a desk on each floor, and a card for whatever is waiting for the person. It is the view onto the task runtime, not a separate product."],
      with: ["The real interface is a local page that the openhora runtime serves on your own machine, at 127.0.0.1 only. The tour below is a demo of it on fictional data."] },
    { op: "replace", ref: "DEV-7: the frame's chrome label is \"demo · fictional data\"",
      match: ["local service · 127.0.0.1", "Replay · fictional project"], with: ["demo · fictional data", "fictional project"] },
    { op: "replace", ref: "Reference and shipping: the tour-still image is not used (the demo frame replaces it)",
      match: ["[alt] ", "Start the tour"], with: ["Start the tour"] },
    { op: "remove", ref: "Reference and shipping: the progress row ol.tour-steps and the caption p.tour-cap are not used",
      match: ["City", "Lobby", "Plan", "Building", "Floor", "Review", "Effect", "Control room", "01 \u00b7 City", "An isometric plot: one building per project, in flat low-poly faces"] },
    // M-41 (decided by the person, 2026-10-11): the tour frame has no Pause, Take over or Replay and no bottom bar; the visitor uses the demo itself.
    { op: "remove", ref: "M-41: the frame's controls and its bottom bar hint are removed",
      match: ["Pause", "Take over", "Replay", "Replay \u00b7 fictional project \u00b7 autopilot"] },
    // M-43 (decided by the person, 2026-10-11): no message appears under the tour when the visitor takes over the demo.
    { op: "remove", ref: "M-43: the take-over message under the tour is removed", match: ["You have the controls. The story is paused."] },
    // M-40 (decided by the person, 2026-10-11): the owls are drawn inline, so the crops' alt text goes, and the Off state goes with its aside.
    { op: "remove", ref: "M-40: the aside of the owl section names the Off state, which is removed", match: ["off means no owl"] },
    ...[["waiting", "faces the person; one wing raised and waving. No question mark.", "Waiting"],
      ["working", "turned three-quarters to its desk; both wings on the keyboard, tapping in turn.", "Working"],
      ["idle", "standing, eyes shut, breathing slowly, three small z rising.", "Idle"]].map(([pose, line, name]) => (
      { op: "replace", ref: `M-40: the ${pose} owl is an inline drawing, not an image with alt text`,
        match: [`[alt] The owl, ${pose}: ${line}`, `[alt] The owl, ${pose}: ${line}`, name], with: [name] })),
    { op: "remove", ref: "M-40: the Off state and its card are removed", match: ["\u2014", "Off", "agent stopped, or project not accepted: no owl in the room."] },
  ],
};

// ---------------------------------------------------------------- static server
function serve() {
  const types = { ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".webp": "image/webp", ".woff2": "font/woff2", ".mjs": "text/javascript" };
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://x");
    let rel = decodeURIComponent(url.pathname);
    let root = SITE;
    if (rel.startsWith("/__handoff__/")) { root = FIXTURES; rel = "/" + rel.slice("/__handoff__/".length); }
    else if (rel === "/demo" || rel.startsWith("/demo/")) { root = DEMO; rel = rel === "/demo" ? "/" : rel.slice("/demo".length); }
    const candidates = rel === "/" ? ["index.html"] : [rel.slice(1), rel.slice(1) + ".html", path.join(rel.slice(1), "index.html")];
    for (const c of candidates) {
      const file = path.resolve(root, c);
      if (!file.startsWith(root) || !fs.existsSync(file) || !fs.statSync(file).isFile()) continue;
      res.writeHead(200, { ...HEADERS, "content-type": types[path.extname(file)] || "application/octet-stream" });
      return fs.createReadStream(file).pipe(res);
    }
    const nf = path.join(SITE, "404.html");
    res.writeHead(404, { ...HEADERS, "content-type": "text/html; charset=utf-8" });
    res.end(fs.existsSync(nf) ? fs.readFileSync(nf) : "not found");
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

// ---------------------------------------------------------------- Chromium over the DevTools protocol
class Browser {
  async start() {
    this.dir = fs.mkdtempSync(path.join(os.tmpdir(), "site-test-"));
    this.proc = spawn(CHROMIUM, ["--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run", "--remote-debugging-port=0", `--user-data-dir=${this.dir}`, "about:blank"], { stdio: "ignore" });
    const portFile = path.join(this.dir, "DevToolsActivePort");
    for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await new Promise((r) => setTimeout(r, 100));
    assert.ok(fs.existsSync(portFile), "Chromium did not start (set CHROMIUM to its path)");
    const [port, wsPath] = fs.readFileSync(portFile, "utf8").trim().split("\n");
    this.ws = new WebSocket(`ws://127.0.0.1:${port}${wsPath}`);
    this.id = 0; this.pending = new Map(); this.listeners = [];
    await new Promise((resolve, reject) => { this.ws.onopen = resolve; this.ws.onerror = reject; });
    this.ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.id && this.pending.has(msg.id)) { const { resolve, reject } = this.pending.get(msg.id); this.pending.delete(msg.id); msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result); }
      else this.listeners.forEach((l) => l(msg));
    };
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  async newPage() {
    const { targetId } = await this.send("Target.createTarget", { url: "about:blank" });
    const { sessionId } = await this.send("Target.attachToTarget", { targetId, flatten: true });
    await this.send("Page.enable", {}, sessionId);
    return new Page(this, sessionId);
  }
  async stop() {
    try { this.ws.close(); } catch {}
    const gone = new Promise((resolve) => { this.proc.once("exit", resolve); setTimeout(resolve, 5000); });
    this.proc.kill();
    await gone;
    fs.rmSync(this.dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
}
class Page {
  constructor(b, sessionId) { this.b = b; this.s = sessionId; }
  async setup({ width, height, mobile }, mode, { reduced = false } = {}) {
    await this.b.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile }, this.s);
    await this.b.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: mode }, { name: "prefers-reduced-motion", value: reduced ? "reduce" : "no-preference" }] }, this.s);
  }
  async mouseClick(x, y) {
    for (const type of ["mousePressed", "mouseReleased"]) await this.b.send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 }, this.s);
  }
  async key(key, code, vk) {
    for (const type of ["keyDown", "keyUp"]) await this.b.send("Input.dispatchKeyEvent", { type, key, code, windowsVirtualKeyCode: vk, ...(type === "keyDown" && key === "Enter" ? { text: "\r" } : {}) }, this.s);
  }
  async waitFor(expression, ms = 20000) {
    const end = Date.now() + ms;
    while (Date.now() < end) { if (await this.eval(expression)) return true; await new Promise((r) => setTimeout(r, 100)); }
    return false;
  }
  async blockDemo(on) {
    if (!on) { this.b.listeners = this.b.listeners.filter((l) => l !== this.blocker); await this.b.send("Fetch.disable", {}, this.s); return; }
    this.blocker = (m) => { if (m.sessionId === this.s && m.method === "Fetch.requestPaused") this.b.send("Fetch.failRequest", { requestId: m.params.requestId, errorReason: "ConnectionRefused" }, this.s); };
    this.b.listeners.push(this.blocker);
    await this.b.send("Fetch.enable", { patterns: [{ urlPattern: "*/demo/index.html" }] }, this.s);
  }
  // Collect every securitypolicyviolation of the page and of its frames, and every console error, in window.__violations of the top page.
  async watchViolations() {
    await this.b.send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => { const top = window.top; top.__violations = top.__violations || [];
      document.addEventListener("securitypolicyviolation", (e) => top.__violations.push(e.violatedDirective + " " + e.blockedURI)); })()` }, this.s);
  }
  async scripts(on) { await this.b.send("Emulation.setScriptExecutionDisabled", { value: !on }, this.s); }
  async goto(url, { scripts = true } = {}) {
    const loaded = new Promise((resolve) => { const l = (m) => { if (m.sessionId === this.s && m.method === "Page.loadEventFired") { this.b.listeners = this.b.listeners.filter((x) => x !== l); resolve(); } }; this.b.listeners.push(l); });
    await this.b.send("Page.navigate", { url }, this.s);
    await loaded;
    if (!scripts) { await new Promise((r) => setTimeout(r, 500)); return; }
    await this.eval("document.fonts.ready.then(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 250))))");
  }
  async eval(expression) {
    const r = await this.b.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, this.s);
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  }
}

// ---------------------------------------------------------------- in-page probes
// Text entries of a page as served, without running its scripts: the title, the images' alt text and every text node.
const TEXT_ENTRIES = `(async (url) => {
  const html = await (await fetch(url)).text();
  const doc = new DOMParser().parseFromString(html, "text/html");
  const out = ["[title] " + doc.title.replace(/\\s+/g, " ").trim()];
  const walk = (n) => {
    for (const c of n.childNodes) {
      if (c.nodeType === 3) { const s = c.nodeValue.replace(/\\s+/g, " ").trim(); if (s) out.push(s); }
      else if (c.nodeType === 1) {
        const tag = c.tagName.toLowerCase();
        if (tag === "script" || tag === "style" || tag === "template") continue;
        if (tag === "img" && c.hasAttribute("alt")) out.push("[alt] " + c.getAttribute("alt").replace(/\\s+/g, " ").trim());
        walk(c);
      }
    }
  };
  walk(doc.body);
  return out;
})`;

const OVERFLOW = `(() => {
  const de = document.documentElement, vw = de.clientWidth;
  const wide = [];
  for (const el of document.querySelectorAll("body *")) {
    const cs = getComputedStyle(el);
    const scrolls = (cs.overflowX === "auto" || cs.overflowX === "scroll") && el.scrollWidth > el.clientWidth + 1;
    if (scrolls) wide.push("scrolls sideways: " + el.tagName.toLowerCase() + (el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\\s+/).join(".") : ""));
  }
  return { mode: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light", inner: innerWidth, client: vw, docScroll: de.scrollWidth, bodyScroll: document.body.scrollWidth, wide: wide.slice(0, 5) };
})()`;

function applyEdits(page, entries) {
  let out = entries.slice();
  for (const e of TEXT_EDITS[page] || []) {
    const hits = [];
    for (let i = 0; i + e.match.length <= out.length; i++) if (e.match.every((t, k) => out[i + k] === t)) hits.push(i);
    const want = e.count || 1;
    assert.equal(hits.length, want, `${page}: the hand-off edit "${e.ref}" must match ${want} run(s) of text entries (${JSON.stringify(e.match)}), found ${hits.length}`);
    const n = e.match.length;
    for (const at of hits.reverse()) {
      if (e.op === "replace") out.splice(at, n, ...e.with);
      else if (e.op === "remove") out.splice(at, n);
      else if (e.op === "insertAfter") out.splice(at + n, 0, ...e.with);
    }
  }
  return out;
}

// ---------------------------------------------------------------- the tests
let server, browser, page, base;
before(async () => {
  DEMO = buildDemo();
  server = await serve();
  base = `http://127.0.0.1:${server.address().port}`;
  browser = new Browser();
  await browser.start();
  page = await browser.newPage();
});
after(async () => { try { await browser?.stop(); } finally { server?.close(); if (DEMO) fs.rmSync(path.dirname(DEMO), { recursive: true, force: true }); } });

for (const p of PAGES) {
  describe(`${p.fixture} (${p.route})`, () => {
    test(`${p.fixture} page file ${p.file} exists and is served at ${p.route}`, async () => {
      assert.ok(fs.existsSync(path.join(SITE, p.file)), `site/${p.file} does not exist`);
      const status = await new Promise((resolve, reject) => http.get(base + p.route, (r) => { r.resume(); resolve(r.statusCode); }).on("error", reject));
      assert.equal(status, 200, `${p.route} did not answer 200`);
    });

    test(`${p.fixture} text matches the hand-off`, async () => {
      assert.ok(fs.existsSync(path.join(SITE, p.file)), `site/${p.file} does not exist`);
      await page.setup(WIDTHS[0], "light");
      await page.goto(base + "/__handoff__/" + p.fixture + ".html");
      const want = applyEdits(p.fixture, await page.eval(`${TEXT_ENTRIES}(${JSON.stringify("/__handoff__/" + p.fixture + ".html")})`));
      const got = await page.eval(`${TEXT_ENTRIES}(${JSON.stringify(p.route)})`);
      const n = Math.min(want.length, got.length);
      let i = 0;
      while (i < n && want[i] === got[i]) i++;
      assert.ok(i === want.length && i === got.length,
        `${p.fixture}: text differs from the hand-off at entry ${i} of ${want.length}: expected ${JSON.stringify(want[i])}, got ${JSON.stringify(got[i])}`);
    });

    for (const size of WIDTHS) {
      for (const mode of MODES) {
        test(`${p.fixture} no horizontal scroll at ${size.width} px, ${mode}`, async () => {
          assert.ok(fs.existsSync(path.join(SITE, p.file)), `site/${p.file} does not exist`);
          await page.setup(size, mode);
          await page.goto(base + p.route);
          const m = await page.eval(OVERFLOW);
          assert.equal(m.mode, mode, `the emulated scheme is ${m.mode}, not ${mode}`);
          assert.ok(m.docScroll <= m.client && m.bodyScroll <= m.client && m.wide.length === 0,
            `${p.fixture} at ${size.width} px, ${mode}: page scrolls sideways (document ${m.docScroll}, body ${m.bodyScroll}, viewport ${m.client}) ${m.wide.join("; ")}`);
        });
      }
    }
  });
}

// ---------------------------------------------------------------- the owl's three states (M-40, Interface page)
// The three owls are inline SVG drawn from the interface's own owl (interface/js/scene/owl.js, owl-motion.js), animated by CSS only.
const OWL_PALETTE = { ink: "rgb(30, 27, 46)", brown: "rgb(107, 68, 41)", tan: "rgb(164, 117, 81)", cream: "rgb(230, 210, 188)", white: "rgb(255, 255, 255)", yellow: "rgb(252, 211, 77)" };
const OWL_COPY = {
  waiting: ["Waiting", "faces the person; one wing raised and waving. No question mark."],
  working: ["Working", "turned three-quarters to its desk; both wings on the keyboard, tapping in turn."],
  idle: ["Idle", "standing, eyes shut, breathing slowly, three small z rising."],
};
const SECTION = `document.querySelector('section[aria-labelledby="owl-t"]')`;

describe("interface: the owl's three states", () => {
  const open = async (size = WIDTHS[0], mode = "light", opts = {}) => { await page.setup(size, mode, opts); await page.goto(base + "/interface"); };

  test("interface owls: three inline drawings in the order waiting, working, idle, each with its name and line, and no Off", async () => {
    await open();
    const got = await page.eval(`(() => {
      const sec = ${SECTION};
      return { owls: [...sec.querySelectorAll("svg[data-owl]")].map((svg) => { const li = svg.closest("li"); return [svg.dataset.owl, li.querySelector(".ow-n")?.textContent.trim(), li.querySelector(".ow-d")?.textContent.trim()]; }),
        items: sec.querySelectorAll("ul.owls > li").length, images: sec.querySelectorAll("img").length, off: /\\boff\\b/i.test(sec.textContent) || !!sec.querySelector(".off, .empty") };
    })()`);
    assert.deepEqual(got.owls, Object.entries(OWL_COPY).map(([pose, [name, line]]) => [pose, name, line]), "the owls, their names and their lines");
    assert.equal(got.items, 3, `the section lists ${got.items} owls, not 3`);
    assert.equal(got.images, 0, "the section still shows an image");
    assert.equal(got.off, false, "the section still mentions or draws the Off state");
  });

  test("interface owls: they stand on the page, not in cards", async () => {
    await open();
    const cards = await page.eval(`[...${SECTION}.querySelectorAll("ul.owls, ul.owls > li, ul.owls > li > *")].map((el) => { const cs = getComputedStyle(el);
      return { el: el.tagName.toLowerCase() + "." + el.className, border: cs.borderTopWidth, bg: cs.backgroundColor, shadow: cs.boxShadow }; })
      .filter((c) => c.border !== "0px" || c.bg !== "rgba(0, 0, 0, 0)" || c.shadow !== "none")`);
    assert.deepEqual(cards, [], "an owl or its text sits in a box (border, background or shadow)");
  });

  test("interface owls: side by side at 1280 px", async () => {
    await open();
    const r = await page.eval(`[...${SECTION}.querySelectorAll("svg[data-owl]")].map((s) => { const b = s.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), Math.round(b.top)]; })`);
    assert.equal(r.length, 3);
    assert.ok(r[0][2] === r[1][2] && r[1][2] === r[2][2], `the owls are not on one row: ${JSON.stringify(r)}`);
    assert.ok(r[0][1] <= r[1][0] && r[1][1] <= r[2][0], `the owls overlap: ${JSON.stringify(r)}`);
  });

  test("interface owls: only the owl's own fixed palette is used, as vector shapes", async () => {
    await open();
    const shapes = await page.eval(`${SECTION}.querySelectorAll("svg[data-owl] :is(path, ellipse, circle, rect, line, polygon)").length`);
    const bad = await page.eval(`[...${SECTION}.querySelectorAll("svg[data-owl] :is(path, ellipse, circle, rect, line, polygon)")].map((el) => { const cs = getComputedStyle(el); return [el.tagName, el.getAttribute("class"), cs.fill, cs.stroke]; })
      .filter(([, , f, s]) => ![f, s].every((c) => c === "none" || ${JSON.stringify(Object.values(OWL_PALETTE))}.includes(c)) || (f === "none" && s === "none"))`);
    assert.deepEqual(bad, [], "a shape has a colour outside the owl's palette");
    assert.ok(shapes > 60, `only ${shapes} shapes found in the owls`);
  });

  test("interface owls: each pose has its own parts", async () => {
    await open();
    const has = await page.eval(`Object.fromEntries([...${SECTION}.querySelectorAll("svg[data-owl]")].map((s) => [s.dataset.owl,
      [...new Set([...s.querySelectorAll("[data-motion]")].map((m) => m.dataset.motion))].sort().concat(s.querySelectorAll('[data-motion="zz"]').length === 3 ? ["three z"] : [])]))`);
    assert.deepEqual(has, { waiting: ["wave"], working: ["hand-far", "hand-near"], idle: ["breath", "zz", "three z"] });
  });

  test("interface owls: they move with CSS alone: wave, tap in turn, breathe, z rise", async () => {
    await open();
    await page.scripts(false);
    try {
      await page.goto(base + "/interface", { scripts: false });
      const m = await page.eval(`Object.fromEntries([...${SECTION}.querySelectorAll("svg[data-owl] [data-motion]")].map((el, i) => { const cs = getComputedStyle(el);
        const b = el.getBoundingClientRect(); return [el.dataset.motion + (el.dataset.motion === "zz" ? i : ""), [cs.animationName !== "none", cs.animationDuration, cs.animationDelay, cs.animationIterationCount, b.width > 0 && b.height > 0]]; }))`);
      const keys = Object.keys(m);
      assert.equal(keys.length, 7, `moving parts with scripts off: ${keys.join(", ")}`);
      for (const [k, v] of Object.entries(m)) assert.ok(v[0] && v[3] === "infinite" && v[4], `${k} does not animate or does not show with scripts off: ${JSON.stringify(v)}`);
      assert.equal(m["wave"][1], "1.6s");
      assert.equal(m["hand-near"][1], "0.36s");
      assert.equal(m["hand-far"][1], "0.36s");
      assert.equal(m["hand-far"][2], "-0.18s", "the far wing is half a beat behind");
      assert.equal(m["breath"][1], "3.2s");
      const zDelays = Object.entries(m).filter(([k]) => k.startsWith("zz")).map(([, v]) => v[2]);
      assert.deepEqual(zDelays, ["0s", "0.5s", "1s"], "each z starts half a second after the one before");
    } finally { await page.scripts(true); }
  });

  for (const mode of MODES) {
    test(`interface owls: under reduced motion every owl is still in its pose, ${mode}`, async () => {
      await open(WIDTHS[0], mode, { reduced: true });
      const r = await page.eval(`(() => { const sec = ${SECTION};
        return { running: sec.getAnimations({ subtree: true }).length, named: [...sec.querySelectorAll("svg[data-owl], svg[data-owl] *")].filter((e) => getComputedStyle(e).animationName !== "none").length,
          zOpacity: [...sec.querySelectorAll('[data-motion="zz"]')].map((z) => getComputedStyle(z).opacity), zShapes: sec.querySelectorAll('svg[data-owl="idle"] [data-motion="zz"] :is(path, polygon)').length,
          wing: sec.querySelectorAll('svg[data-owl="waiting"] [data-motion="wave"]').length, hands: sec.querySelectorAll('svg[data-owl="working"] [data-motion^="hand"]').length }; })()`);
      assert.equal(r.running, 0, "an animation runs under reduced motion");
      assert.equal(r.named, 0, "an element still has an animation name under reduced motion");
      assert.deepEqual(r.zOpacity, ["1", "1", "1"], "the three z are shown under reduced motion");
      assert.ok(r.zShapes >= 3 && r.wing === 1 && r.hands === 2, "a pose lost its parts under reduced motion");
    });
  }

  test("interface owls: nothing is cut off by the drawing's box", async () => {
    await open(WIDTHS[0], "light", { reduced: true });
    assert.equal(await page.eval(`${SECTION}.querySelectorAll("svg[data-owl] g.owl-all").length`), 3, "each owl is wrapped in g.owl-all");
    const cut = await page.eval(`[...${SECTION}.querySelectorAll("svg[data-owl]")].map((s) => { const vb = s.viewBox.baseVal, b = s.querySelector("g.owl-all").getBBox(), m = 4;
      return [s.dataset.owl, b.x - m >= vb.x, b.y - m >= vb.y, b.x + b.width + m <= vb.x + vb.width, b.y + b.height + m <= vb.y + vb.height]; }).filter((r) => r.slice(1).includes(false))`);
    assert.deepEqual(cut, [], "an owl's drawing reaches past its viewBox");
  });

  for (const size of WIDTHS) {
    for (const mode of MODES) {
      test(`interface owls: no horizontal scroll at ${size.width} px, ${mode}`, async () => {
        await open(size, mode);
        const m = await page.eval(`(() => { const sec = ${SECTION}, vw = document.documentElement.clientWidth;
          const out = [...sec.querySelectorAll("svg[data-owl], .ow-n, .ow-d")].map((e) => e.getBoundingClientRect()).filter((b) => b.left < 0 || b.right > vw + 0.5).length;
          return { section: sec.scrollWidth <= sec.clientWidth + 1, outside: out, doc: document.documentElement.scrollWidth <= vw, body: document.body.scrollWidth <= vw, svgs: sec.querySelectorAll("svg[data-owl]").length }; })()`);
        assert.ok(m.svgs === 3 && m.section && m.doc && m.body && m.outside === 0, `owls at ${size.width} px, ${mode}: ${JSON.stringify(m)}`);
      });
    }
  }

  test("interface owls: the owl-state crops are gone from site/assets/img and from the page", async () => {
    const left = fs.readdirSync(path.join(SITE, "assets", "img")).filter((f) => /^owl-(waiting|working|idle)-/.test(f));
    assert.deepEqual(left, [], "owl-state crops are still in site/assets/img");
    assert.ok(!/owl-(waiting|working|idle)-(light|dark)/.test(fs.readFileSync(path.join(SITE, "interface.html"), "utf8")), "interface.html still points at an owl-state crop");
  });
});

// ---------------------------------------------------------------- the tour frame without its controls (M-41, Interface page)
// The visitor takes over by using the demo itself (any click or key pauses its autopilot); the demo's own "Start over" restarts it.
const TOUR = `document.querySelector("#tour-player")`;

// Where, in the page's pixels, the centre of an element of the demo is: the demo's own coordinates times the frame's scale.
const demoPoint = (sel) => `(() => { const fr = ${TOUR}.querySelector("iframe"), f = fr.getBoundingClientRect(), k = f.width / fr.offsetWidth, e = fr.contentDocument.querySelector(${JSON.stringify(sel)});
  const b = e ? e.getBoundingClientRect() : null; return b ? [Math.round(f.left + (b.left + b.width / 2) * k), Math.round(f.top + (b.top + b.height / 2) * k)] : [Math.round(f.left + f.width / 2), Math.round(f.top + f.height / 2)]; })()`;

describe("interface: the tour frame", () => {
  const open = async (size = WIDTHS[0], mode = "light", opts = {}) => { await page.setup(size, mode, opts); await page.goto(base + "/interface"); };

  for (const route of ["/interface", "/"]) {
    test(`tour ${route}: no Pause, Take over, Replay or Play control and no bottom bar`, async () => {
      await open();
      await page.goto(base + route);
      const r = await page.eval(`(() => { const t = document.querySelector(".tour");
        return { bar: !!document.querySelector(".tour-bar, .tour-controls"), hooks: !!document.querySelector("[data-tour-pause], [data-tour-take], [data-tour-replay]"),
          buttons: [...document.querySelectorAll(".tour button, .tour a")].map((b) => b.textContent.replace(/\\s+/g, " ").trim()).filter((x) => /^(pause|play|take over|replay)$/i.test(x)),
          hint: /autopilot/i.test(t.parentElement.textContent) }; })()`);
      assert.deepEqual(r, { bar: false, hooks: false, buttons: [], hint: false }, "the frame still has a control or its bottom bar");
    });
  }

  for (const route of ["/interface", "/"]) {
    test(`tour ${route}: the top-bar badge reads "fictional project"`, async () => {
      await open();
      await page.goto(base + route);
      const badge = await page.eval(`document.querySelector(".tour-badge")?.textContent.replace(/\\s+/g, " ").trim()`);
      assert.equal(badge, "fictional project");
    });
  }

  test("tour: the top bar with \"demo \u00b7 fictional data\" and its badge stay; the poster and Start the tour show first", async () => {
    await open();
    const r = await page.eval(`(() => { const t = ${TOUR}; const txt = (s) => t.querySelector(s)?.textContent.replace(/\\s+/g, " ").trim();
      return { addr: txt(".tour-addr"), badge: txt(".tour-badge"), start: txt("[data-tour-start] b"), state: t.dataset.state, poster: getComputedStyle(t.querySelector(".tour-poster")).display !== "none" }; })()`);
    assert.deepEqual(r, { addr: "demo \u00b7 fictional data", badge: "fictional project", start: "Start the tour", state: "poster", poster: true });
  });

  test("tour: Start loads the demo and it plays; a click inside it takes over; its own Start over plays again", async () => {
    await open();
    await page.eval(`${TOUR}.scrollIntoView({ block: "center" })`);
    await page.eval(`${TOUR}.querySelector("[data-tour-start]").click()`);
    assert.ok(await page.waitFor(`${TOUR}.dataset.state === "playing"`), `the tour did not reach "playing" (state ${await page.eval(`${TOUR}.dataset.state`)})`);
    assert.ok(await page.waitFor(`!!${TOUR}.querySelector("iframe").contentDocument?.querySelector(".wb-demo-ribbon")`), "the demo did not draw");
    const at = (sel) => demoPoint(sel);
    const [x, y] = await page.eval(at("#app"));
    await page.mouseClick(x, y);
    assert.ok(await page.waitFor(`${TOUR}.dataset.state === "takeover"`), "a visitor's click inside the demo did not put the frame in the takeover state");
    assert.equal(await page.eval(`!!${TOUR}.querySelector(".tour-takeover") || /story is paused|You have the controls/i.test(${TOUR}.textContent)`), false, "a take-over message appears after a click inside the demo");
    const [sx, sy] = await page.eval(at(".wb-demo-ribbon button:last-child"));
    await page.mouseClick(sx, sy);
    assert.ok(await page.waitFor(`${TOUR}.dataset.state === "playing"`), "the demo's own Start over did not put the frame back to playing");
  });

  test("tour: a demo that cannot be fetched ends in the could-not-load state, with Try again", async () => {
    await open();
    await page.blockDemo(true);
    try {
      await page.eval(`${TOUR}.querySelector("[data-tour-start]").click()`);
      assert.ok(await page.waitFor(`${TOUR}.dataset.state === "error"`, 10000), "the frame did not show could-not-load");
      const r = await page.eval(`(() => { const e = ${TOUR}.querySelector(".tour-state.error"); return [getComputedStyle(e).display, e.querySelector("[data-tour-retry]")?.textContent.trim(), e.querySelector(".ts-h").textContent.trim()]; })()`);
      assert.deepEqual(r, ["grid", "Try again", "The interface could not load."]);
    } finally { await page.blockDemo(false); }
  });
});

// ---------------------------------------------------------------- the demo is the build (scripts/build_demo.py, run by netlify.toml)
// The demo is generated at deploy time and git-ignored. The tests serve a fresh build of this checkout at /demo/; a second fresh build must be
// byte for byte the same (the build is deterministic), and the deploy's command must be that script writing into site/demo.
describe("interface: the demo is a fresh build", () => {
  const hashes = (dir) => { const found = {}; const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const full = path.join(d, e.name);
    if (e.isDirectory()) walk(full); else found[path.relative(dir, full).split(path.sep).join("/")] = crypto.createHash("sha256").update(fs.readFileSync(full)).digest("hex");
  } }; walk(dir); return found; };
  test("demo: /demo/ serves a build that equals a second build of the same checkout", () => {
    assert.ok(fs.existsSync(path.join(DEMO, "index.html")), "the built demo has no index.html");
    assert.ok(fs.existsSync(path.join(DEMO, "demo", "boot.js")), "the built demo has no demo/boot.js");
    const second = buildDemo();
    try { assert.deepEqual(hashes(second), hashes(DEMO)); } finally { fs.rmSync(path.dirname(second), { recursive: true, force: true }); }
  });
  test("demo: the demo's transport is the one that answers from memory, never the service's", () => {
    assert.equal(fs.readFileSync(path.join(DEMO, "js", "transport.js"), "utf8"), fs.readFileSync(path.join(REPO, "interface", "demo", "transport.js"), "utf8"));
  });
  test("netlify.toml: the [[headers]] table that holds the policy applies to every path (for = \"/*\")", () => {
    const toml = fs.readFileSync(path.join(REPO, "netlify.toml"), "utf8");
    const tables = toml.split(/^\s*\[\[headers\]\]\s*$/m).slice(1);
    const own = tables.filter((s) => /^\s*Content-Security-Policy\s*=/m.test(s));
    assert.equal(own.length, 1, "exactly one [[headers]] table holds the Content-Security-Policy");
    assert.match(own[0], /^\s*for\s*=\s*"\/\*"\s*$/m);
    assert.match(own[0], /^\s*\[headers\.values\]\s*$/m, "the policy is under [headers.values]");
  });
  test("demo: netlify.toml publishes site/ and builds the demo into site/demo with scripts/build_demo.py; site/demo is not committed", () => {
    const toml = fs.readFileSync(path.join(REPO, "netlify.toml"), "utf8");
    assert.match(toml, /^\s*publish\s*=\s*"site"\s*$/m);
    assert.match(toml, /^\s*command\s*=\s*"python3 scripts\/build_demo\.py --out site\/demo\b/m);
    assert.match(fs.readFileSync(path.join(REPO, ".gitignore"), "utf8"), /^site\/demo\/$/m);
  });
});

// ---------------------------------------------------------------- the pages obey the deploy's policy (netlify.toml)
describe("headers: every page and the tour run under the deploy's Content-Security-Policy", () => {
  test("netlify.toml sets a policy that allows only the site's own origin for scripts, styles, fonts, images, frames and requests, and the other two headers", () => {
    const csp = HEADERS["Content-Security-Policy"];
    assert.ok(csp, "netlify.toml has no Content-Security-Policy");
    const directive = (n) => (csp.split(";").map((s) => s.trim().split(/\s+/)).find((d) => d[0] === n) || []).slice(1).join(" ");
    for (const n of ["script-src", "style-src", "font-src", "frame-src", "connect-src"]) assert.equal(directive(n), "'self'", n);
    assert.equal(directive("img-src"), "'self' data:", "data: images are the second allowance (marks drawn in CSS)");
    assert.equal(directive("frame-ancestors"), "'self'");
    assert.equal(directive("default-src"), "'none'");
    assert.equal(directive("style-src-attr"), "'unsafe-inline'", "style attributes only set custom properties; this is the one allowance");
    assert.equal(HEADERS["X-Content-Type-Options"], "nosniff");
    assert.equal(HEADERS["Referrer-Policy"], "same-origin");
  });
  test("no page has an inline script, an inline style element or an inline handler", () => {
    for (const p of PAGES) {
      const html = fs.readFileSync(path.join(SITE, p.file), "utf8");
      assert.ok(!/<script(?![^>]*\bsrc=)[^>]*>/i.test(html), `${p.file}: an inline script`);
      assert.ok(!/<style[\s>]/i.test(html), `${p.file}: a style element`);
      assert.ok(!/\son[a-z]+\s*=/i.test(html.replace(/<pre[\s\S]*?<\/pre>/gi, "")), `${p.file}: an inline handler`);
    }
  });
  test("every page, at 1280 and 375 px, raises no policy violation and no console error", async () => {
    const errors = [];
    const l = (m) => { if (m.sessionId === page.s && m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.text); };
    browser.listeners.push(l);
    await page.watchViolations();
    try {
      for (const w of WIDTHS) for (const p of PAGES) {
        await page.setup(w, "light");
        await page.goto(base + p.route);
        const v = await page.eval("(window.__violations || []).slice()");
        assert.deepEqual(v, [], `${p.route} at ${w.width}: policy violations`);
      }
      assert.deepEqual(errors, [], "uncaught errors");
    } finally { browser.listeners = browser.listeners.filter((x) => x !== l); }
  });
  test("the tour plays under the policy: the framed demo loads, draws and raises no violation", async () => {
    await page.setup(WIDTHS[0], "light");
    await page.goto(base + "/interface");
    await page.eval(`window.__violations = []`);
    await page.eval(`${TOUR}.scrollIntoView({ block: "center" })`);
    await page.eval(`${TOUR}.querySelector("[data-tour-start]").click()`);
    assert.ok(await page.waitFor(`!!${TOUR}.querySelector("iframe").contentDocument?.querySelector(".wb-demo-ribbon")`), "the demo did not draw under the policy");
    await new Promise((r) => setTimeout(r, 4000));
    assert.deepEqual(await page.eval("window.__violations.slice()"), [], "policy violations in the tour");
  });
});

// ---------------------------------------------------------------- the tour frame shows the desktop layout, scaled (Interface page)
// From 900 px up the demo is laid out at 1280 by 800 CSS pixels and scaled by a CSS transform to the screen's inner width (16:10); under 900 px it keeps
// its own phone layout, unscaled. The scale follows the screen when the window is resized; pointer and keyboard input go through the transform.
describe("interface: the tour frame is scaled", () => {
  const SIZES = { 1280: WIDTHS[0], 1100: { width: 1100, height: 900, mobile: false }, 900: { width: 900, height: 900, mobile: false }, 899: { width: 899, height: 900, mobile: false }, 375: WIDTHS[1] };
  const start = async (width, mode = "light") => {
    await page.setup(SIZES[width], mode);
    await page.goto(base + "/interface");
    await page.eval(`${TOUR}.scrollIntoView({ block: "center" })`);
    await page.eval(`${TOUR}.querySelector("[data-tour-start]").click()`);
    assert.ok(await page.waitFor(`${TOUR}.dataset.state === "playing"`), `the tour did not reach "playing" at ${width} px`);
    assert.ok(await page.waitFor(`!!${TOUR}.querySelector("iframe").contentDocument?.querySelector(".wb-demo-ribbon")`), `the demo did not draw at ${width} px`);
  };
  const FRAME = `(() => { const fr = ${TOUR}.querySelector("iframe"), s = ${TOUR}.querySelector(".tour-screen"), r = fr.getBoundingClientRect(), d = fr.contentDocument.documentElement;
    return { w: fr.offsetWidth, h: fr.offsetHeight, vw: r.width, vh: r.height, left: r.left - s.getBoundingClientRect().left, top: r.top - s.getBoundingClientRect().top,
      screenW: s.clientWidth, screenH: s.clientHeight, transform: getComputedStyle(fr).transform, demoViewport: d.clientWidth, demoScroll: d.scrollWidth,
      screenScroll: [s.scrollWidth - s.clientWidth, s.scrollLeft], pageScroll: [document.documentElement.scrollWidth - document.documentElement.clientWidth, scrollX] }; })()`;
  const scaleOf = (t) => { const m = /^matrix\(([-\d.e]+), 0, 0, ([-\d.e]+), 0, 0\)$/.exec(t); assert.ok(m && m[1] === m[2], `the frame's transform is not a plain scale: ${t}`); return Number(m[1]); };
  const near = (a, b, msg) => assert.ok(Math.abs(a - b) <= 1, `${msg}: ${a} is not ${b}`);

  for (const width of [1280, 1100, 900]) {
    test(`tour at ${width} px: the demo is laid out at 1280 by 800 and scaled to the screen's width, 16:10`, async () => {
      await start(width);
      const f = await page.eval(FRAME), k = scaleOf(f.transform);
      assert.deepEqual([f.w, f.h], [1280, 800], "the iframe is not 1280 by 800 CSS pixels");
      assert.equal(f.demoViewport, 1280, "the demo does not see a 1280 px wide window");
      near(f.vw, f.screenW, "the scaled frame's width and the screen's inner width");
      near(f.vh, f.screenH, "the scaled frame's height and the screen's");
      near(f.screenW / f.screenH, 1.6, "the screen's ratio");
      near(k, f.screenW / 1280, "the scale");
      assert.ok(k < 1 && k > 0.4, `the scale ${k} is out of range`);
      near(f.left, 0, "the frame's left edge in the screen"); near(f.top, 0, "the frame's top edge in the screen");
    });
  }

  for (const width of [899, 375]) {
    test(`tour at ${width} px: the demo keeps its phone layout, unscaled`, async () => {
      await start(width);
      const f = await page.eval(FRAME);
      assert.equal(f.transform, "none", "the frame is transformed");
      near(f.w, f.screenW, "the frame's width and the screen's"); near(f.h, f.screenH, "the frame's height and the screen's");
      assert.equal(f.demoViewport, f.w, "the demo's window is not the frame's size");
      assert.ok(f.demoViewport < 900, "the demo is not under its phone breakpoint");
    });
  }

  test("tour: the scale is recomputed when the window is resized, and dropped under 900 px", async () => {
    await start(1280);
    const seen = [];
    for (const width of [1100, 900, 899, 1280]) {
      await page.setup(SIZES[width], "light");
      const t = width >= 900 ? "scaled" : "none";
      assert.ok(await page.waitFor(`(getComputedStyle(${TOUR}.querySelector("iframe")).transform === "none") === ${t === "none"}`), `the frame is not ${t} after the window went to ${width} px`);
      assert.ok(await page.waitFor(`(() => { const fr = ${TOUR}.querySelector("iframe"); return Math.abs(fr.getBoundingClientRect().width - ${TOUR}.querySelector(".tour-screen").clientWidth) <= 1; })()`), `the frame does not fill the screen at ${width} px`);
      const f = await page.eval(FRAME);
      seen.push(width >= 900 ? scaleOf(f.transform) : 1);
      if (width >= 900) assert.deepEqual([f.w, f.h], [1280, 800]);
    }
    assert.ok(seen[0] > seen[1] && seen[1] < seen[3] && seen[2] === 1, `the scales do not follow the window: ${seen}`);
    near(seen[0], seen[3], "the scale back at 1280 px");
  });

  for (const width of [1280, 1100]) {
    test(`tour at ${width} px: a click inside the scaled demo lands where it was aimed and takes over; its Start over plays again`, async () => {
      await start(width);
      assert.equal(await page.eval(`${TOUR}.querySelector("iframe").offsetWidth / ${TOUR}.querySelector("iframe").getBoundingClientRect().width > 1`), true, "the demo is not scaled down, so the click proves nothing");
      await page.eval(`(() => { const d = ${TOUR}.querySelector("iframe").contentDocument; window.__hits = []; d.addEventListener("pointerdown", (e) => window.__hits.push([e.clientX, e.clientY, e.target.id || e.target.tagName]), true); })()`);
      const [x, y] = await page.eval(demoPoint("#app"));
      const want = await page.eval(`(() => { const e = ${TOUR}.querySelector("iframe").contentDocument.querySelector("#app").getBoundingClientRect(); return [e.left + e.width / 2, e.top + e.height / 2]; })()`);
      await page.mouseClick(x, y);
      assert.ok(await page.waitFor(`${TOUR}.dataset.state === "takeover"`), "a click inside the scaled demo did not reach it");
      const [hit] = await page.eval("window.__hits");
      assert.ok(hit, "the demo heard no pointer");
      near(hit[0], want[0], "the pointer's x in the demo's own pixels"); near(hit[1], want[1], "the pointer's y in the demo's own pixels");
      const [sx, sy] = await page.eval(demoPoint(".wb-demo-ribbon button:last-child"));
      await page.mouseClick(sx, sy);
      assert.ok(await page.waitFor(`${TOUR}.dataset.state === "playing"`), "the demo's own Start over, clicked through the scale, did not play again");
    });
  }

  test("tour at 1280 px: the keyboard works inside the scaled demo", async () => {
    await start(1280);
    await page.eval(`${TOUR}.querySelector("iframe").contentWindow.focus()`);
    await page.key("Tab", "Tab", 9);
    assert.ok(await page.waitFor(`${TOUR}.dataset.state === "takeover"`), "a key inside the demo did not take over");
    await page.eval(`${TOUR}.querySelector("iframe").contentDocument.querySelector(".wb-demo-ribbon button:last-child").focus()`);
    await page.key("Enter", "Enter", 13);
    assert.ok(await page.waitFor(`${TOUR}.dataset.state === "playing"`), "Enter on the demo's Start over did not play again");
  });

  for (const width of [1280, 1100, 900, 375]) {
    for (const mode of MODES) {
      test(`tour at ${width} px, ${mode}: nothing scrolls sideways with the demo running`, async () => {
        await start(width, mode);
        const m = await page.eval(OVERFLOW), f = await page.eval(FRAME);
        assert.equal(m.mode, mode);
        assert.ok(m.docScroll <= m.client && m.bodyScroll <= m.client && m.wide.length === 0, `the page scrolls sideways (document ${m.docScroll}, body ${m.bodyScroll}, viewport ${m.client}) ${m.wide.join("; ")}`);
        assert.deepEqual([f.pageScroll[0] <= 0, f.pageScroll[1], f.screenScroll[0] <= 1, f.screenScroll[1]], [true, 0, true, 0], `the page or the tour screen has sideways overflow or is scrolled: ${JSON.stringify([f.pageScroll, f.screenScroll])}`);
        assert.ok(f.demoScroll <= f.demoViewport, `the demo scrolls sideways (${f.demoScroll} in ${f.demoViewport})`);
      });
    }
  }
});

// ---------------------------------------------------------------- the navigation label (M-42, every page)
const NAV_LINKS = `(() => [...document.querySelectorAll('a[href="/how-it-is-built"]')].map((a) => ({ text: a.textContent.trim(), where: a.closest("header") ? "header" : a.closest("footer") ? "footer" : "body", visible: a.getBoundingClientRect().width > 0 })))()`;

describe("navigation label \"How it's built\" (M-42)", () => {
  for (const p of PAGES) {
    test(`${p.fixture} the link reads "${NAV_LABEL}" in the header and in the footer, and nowhere else`, async () => {
      await page.setup(WIDTHS[0], "light");
      await page.goto(base + p.route);
      const links = await page.eval(NAV_LINKS);
      assert.deepEqual(links.map((l) => [l.where, l.text]), [["header", NAV_LABEL], ["footer", NAV_LABEL]], `${p.fixture}: links to /how-it-is-built are ${JSON.stringify(links)}`);
    });
  }

  test("how-its-built the page's own heading and title keep the full name", async () => {
    await page.setup(WIDTHS[0], "light");
    await page.goto(base + "/how-it-is-built");
    const got = await page.eval(`({ title: document.title, kicker: document.querySelector(".ph-kicker")?.textContent.trim(), current: document.querySelector('a[aria-current="page"][href="/how-it-is-built"]')?.textContent.trim() })`);
    assert.equal(got.title, "How openhora is built \u00b7 openhora");
    assert.equal(got.kicker, "How openhora is built");
    assert.equal(got.current, NAV_LABEL, "the current-page link in the navigation");
  });

  test("the phone's opened navigation shows the link as \"How it's built\" and nothing scrolls sideways at 375 px", async () => {
    for (const mode of MODES) {
      await page.setup(WIDTHS[1], mode);
      await page.goto(base + "/");
      await page.eval(`(() => { const t = document.getElementById("nav-toggle"); t.checked = true; t.dispatchEvent(new Event("change", { bubbles: true })); })()`);
      const got = await page.eval(`(() => { const a = document.querySelector('.site-nav a[href="/how-it-is-built"]'); const b = a.getBoundingClientRect(); const de = document.documentElement;
        return { text: a.textContent.trim(), shown: b.width > 0 && b.height > 0, right: Math.round(b.right), client: de.clientWidth, docScroll: de.scrollWidth, bodyScroll: document.body.scrollWidth }; })()`);
      assert.equal(got.text, NAV_LABEL);
      assert.ok(got.shown, `the link is not shown in the opened navigation (${mode})`);
      assert.ok(got.right <= got.client && got.docScroll <= got.client && got.bodyScroll <= got.client, `375 px, ${mode}, navigation open: ${JSON.stringify(got)}`);
    }
  });

  // the header holds on one row: every link of the navigation on one line, the navigation clear of the tools, the header no taller than at 1280
  for (const width of [900, 1100, 1280]) {
    for (const mode of MODES) {
      test(`the header fits on one row at ${width} px, ${mode}, on every page`, async () => {
        for (const p of PAGES) {
          await page.setup({ width, height: 900, mobile: false }, mode);
          await page.goto(base + p.route);
          const h = await page.eval(`(() => { const rect = (el) => el.getBoundingClientRect(); const de = document.documentElement;
            const links = [...document.querySelectorAll(".site-header .site-nav ul a")].map(rect);
            const nav = rect(document.querySelector(".site-header .site-nav")), tools = rect(document.querySelector(".site-header .header-tools")), brand = rect(document.querySelector(".site-header .brandlink")), header = rect(document.querySelector(".site-header"));
            return { links: links.length, tops: [...new Set(links.map((r) => Math.round(r.top)))].length, heights: [...new Set(links.map((r) => Math.round(r.height)))], navLeft: Math.round(nav.left), navRight: Math.round(nav.right), toolsLeft: Math.round(tools.left), brandRight: Math.round(brand.right),
              toolsRight: Math.round(tools.right), header: Math.round(header.height), client: de.clientWidth, docScroll: de.scrollWidth }; })()`);
          const where = `${p.fixture} at ${width} px, ${mode}: ${JSON.stringify(h)}`;
          assert.equal(h.links, 6, where);
          assert.equal(h.tops, 1, `the navigation links are not on one row. ${where}`);
          assert.ok(h.heights.every((x) => x <= 48), `a navigation link wraps. ${where}`);
          assert.ok(h.brandRight <= h.navLeft && h.navRight <= h.toolsLeft, `the navigation overlaps the brand or the tools. ${where}`);
          assert.ok(h.toolsRight <= h.client && h.docScroll <= h.client, `the header overflows. ${where}`);
          assert.ok(h.header <= 72, `the header is taller than one row. ${where}`);
        }
      });
    }
  }
});

// ================================================================ the hand-off's open items (DEV-16 to DEV-28)
// Items: 1 contrast (DEV-21, M-37), 2 radii (DEV-23), 3 tokens (DEV-24, DEV-17), 4 header (DEV-22), 5 owls and SVG (DEV-16, DEV-28),
// 6 the Which-model list (DEV-26), 8 links and routes (DEV-20, DEV-25).
const read = (...p) => fs.readFileSync(path.join(SITE, ...p), "utf8");
const SRC_CSS = read("assets", "css", "src", "site.css");
const PAGE_FILES = PAGES.map((p) => p.file);

// Strip the comments, then split a stylesheet into [selector, body] leaf rules (at-rules other than @font-face are flattened to their rules).
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, "");
function rulesOf(css) {
  const out = [];
  const walk = (text) => {
    let i = 0;
    while (i < text.length) {
      const j = text.indexOf("{", i);
      if (j < 0) return;
      const head = text.slice(i, j).trim();
      let depth = 1, k = j + 1;
      while (k < text.length && depth) { depth += { "{": 1, "}": -1 }[text[k]] || 0; k++; }
      const body = text.slice(j + 1, k - 1);
      if (/^@(media|supports)/.test(head)) walk(body); else out.push([head.replace(/\s+/g, " "), body]);
      i = k;
    }
  };
  walk(stripComments(css));
  return out;
}

// ---------------------------------------------------------------- item 1: text colour (DEV-21, M-37)
// Every visible text, in light and dark, with the colour it is set in against the background it sits on: WCAG AA, 4.5:1 small, 3:1 large
// (24 px, or 18.66 px and bold). A background that is an image or a gradient cannot be computed here: such a text must be on UNMEASURABLE below.
const CONTRAST = `(() => {
  const cv = document.createElement("canvas"); cv.width = cv.height = 1;
  const cx = cv.getContext("2d", { willReadFrequently: true });
  const rgba = (css) => { cx.fillStyle = "#123456"; cx.fillStyle = css; if (cx.fillStyle === "#123456" && !/^#?123456$/i.test(css)) throw new Error("colour not understood: " + css);
    cx.clearRect(0, 0, 1, 1); cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const over = (t, b) => { const a = t[3] + b[3] * (1 - t[3]); return a === 0 ? [0, 0, 0, 0] : [0, 1, 2].map((i) => (t[i] * t[3] + b[i] * b[3] * (1 - t[3])) / a).concat(a); };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const name = (el) => el.tagName.toLowerCase() + (typeof el.className === "string" && el.className.trim() ? "." + el.className.trim().split(/\\s+/).join(".") : "");
  const pageBg = rgba(getComputedStyle(document.body).backgroundColor);
  const colours = (img) => (img.match(/rgba?\\([^)]*\\)|color\\([^)]*\\)/g) || []).map(rgba);
  const out = { checked: 0, fail: [], unmeasurable: [], decorative: [] };
  const one = (el, fgCss, text) => {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (cs.visibility !== "visible" || r.width <= 1 || r.height <= 1) return;
    let op = 1; for (let n = el; n && n.nodeType === 1; n = n.parentElement) op *= parseFloat(getComputedStyle(n).opacity);
    if (op < 0.02) return;
    let fg = rgba(fgCss);
    const hidden = !!el.closest('[aria-hidden="true"]');
    if (fg[3] < 0.05) { // outlined or clipped glyphs: the stroke carries the text; a decoration hidden from assistive technology is listed, not measured
      const sw = parseFloat(cs.webkitTextStrokeWidth);
      if (hidden) { out.decorative.push(name(el) + ": " + text.slice(0, 20)); return; }
      if (!(sw > 0)) { out.fail.push(name(el) + " has no fill and no stroke: " + JSON.stringify(text.slice(0, 20))); return; }
      fg = rgba(cs.webkitTextStrokeColor);
    }
    const under = [], gradients = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const c = getComputedStyle(n);
      if (c.backgroundImage !== "none") {
        const solid = /^linear-gradient\\(((?:rgba?|color)\\([^)]*\\)), \\1\\)/.exec(c.backgroundImage); // a flat fill drawn as a gradient (gradient border buttons)
        if (solid) { under.push(rgba(solid[1])); break; }
        gradients.push({ at: name(n), stops: colours(c.backgroundImage), colour: rgba(c.backgroundColor) }); break;
      }
      under.push(rgba(c.backgroundColor));
      if (under[under.length - 1][3] >= 0.999) break;
    }
    const flatten = (stack, ground) => stack.reduceRight((acc, l) => over(l, acc), ground);
    // The grounds a gradient gives: its opaque stops, each alone and each under every translucent stop; the plain ground only where the gradient fades to nothing.
    const groundsOf = (g) => { const base = over(g.colour, pageBg), opaque = g.stops.filter((c) => c[3] >= 0.99), part = g.stops.filter((c) => c[3] >= 0.05 && c[3] < 0.99), clear = g.stops.some((c) => c[3] < 0.05);
      const bases = opaque.length ? opaque : [base]; const list = opaque.slice(); for (const t of part) for (const b of bases) list.push(over(t, b)); if ((clear && opaque.length === 0) || !list.length) list.push(base); return list; };
    const grounds = gradients.length ? groundsOf(gradients[0]) : [pageBg];
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700, large = size >= 24 || (size >= 18.66 && bold), need = large ? 3 : 4.5;
    let worst = Infinity;
    for (const g of grounds) { const bg = flatten(under, g); const f = over([fg[0], fg[1], fg[2], fg[3] * op], bg); worst = Math.min(worst, ratio(f, bg)); }
    out.checked++;
    if (gradients.length) out.unmeasurable.push(name(el) + " on " + gradients[0].at + " (worst stop " + worst.toFixed(2) + ":1): " + text.slice(0, 30));
    if (worst < need - 0.005) out.fail.push(name(el) + " " + size + "px" + (bold ? " bold" : "") + " " + worst.toFixed(2) + ":1 (needs " + need + ")" + (gradients.length ? " on the gradient of " + gradients[0].at : "") + " " + JSON.stringify(text.slice(0, 40)));
  };
  for (const el of document.body.querySelectorAll("*")) {
    if (el.closest("script, style, template, iframe, noscript")) continue;
    const mine = [...el.childNodes].filter((n) => n.nodeType === 3 && n.nodeValue.trim()).map((n) => n.nodeValue.trim()).join(" ");
    if (!mine) continue;
    const cs = getComputedStyle(el);
    one(el, el instanceof SVGElement ? cs.fill : cs.color, mine);
  }
  for (const el of document.body.querySelectorAll("input[placeholder], textarea[placeholder]")) one(el, getComputedStyle(el, "::placeholder").color, el.placeholder);
  for (const k of ["fail", "unmeasurable", "decorative"]) out[k] = [...new Set(out[k])];
  return out;
})()`;

// A text over a gradient is measured against every colour stop of the gradient, composited on the page ground (the pessimistic bound), and fails when any stop fails.
// A text outlined or clipped to a gradient is a decoration: it must be aria-hidden, and is listed in the report, not measured. A text over a screenshot is on UNMEASURABLE_OK.
const UNMEASURABLE_OK = [/tour-overlay/];

describe("text contrast, WCAG AA, light and dark (DEV-21, M-37)", () => {
  for (const p of PAGES) {
    for (const mode of MODES) {
      test(`${p.fixture} every text pair passes at ${mode}`, async () => {
        await page.setup(WIDTHS[0], mode, { reduced: true });
        await page.goto(base + p.route);
        const r = await page.eval(CONTRAST);
        assert.ok(r.checked > 20, `only ${r.checked} texts were measured`);
        assert.deepEqual(r.fail, [], `${p.fixture} ${mode}: text pairs under AA`);
      });
    }
  }

  test("home: every claim of the picker passes in light and dark", async () => {
    for (const mode of MODES) {
      await page.setup(WIDTHS[0], mode, { reduced: true });
      await page.goto(base + "/");
      const n = await page.eval(`document.querySelectorAll(".claim > input").length`);
      assert.equal(n, 7);
      for (let i = 0; i < n; i++) {
        await page.eval(`document.querySelectorAll(".claim > input")[${i}].click()`);
        const r = await page.eval(CONTRAST);
        assert.deepEqual(r.fail, [], `home claim ${i + 1}, ${mode}: text pairs under AA`);
      }
    }
  });

  test("proof: the gate by hand passes and fails with every text at AA, in light and dark", async () => {
    for (const mode of MODES) {
      await page.setup(WIDTHS[0], mode, { reduced: true });
      await page.goto(base + "/proof");
      for (const state of ["fail", "pass"]) {
        await page.eval(`(() => { const g = document.querySelector("[data-gate]"); g.querySelectorAll("input[type=range]:not([data-base])").forEach((r) => { r.value = ${state === "pass" ? 1 : 0}; }); g.dispatchEvent(new Event("input", { bubbles: true })); })()`);
        const verdict = await page.eval(`document.querySelector("[data-verdict]").className`);
        assert.ok(verdict.includes("is-" + state), `the gate did not reach ${state}: ${verdict}`);
        const r = await page.eval(CONTRAST);
        assert.deepEqual(r.fail, [], `proof gate ${state}, ${mode}: text pairs under AA`);
      }
    }
  });

  test("a state is never colour alone: a band word or label has the text colour and a coloured dot beside it", async () => {
    const SEL = ".band-word, .limit .tag, .hold.code, .hold.guard, .sc-real, .ext-term .term-bar .meta";
    for (const mode of MODES) for (const p of PAGES) {
      await page.setup(WIDTHS[0], mode, { reduced: true });
      await page.goto(base + p.route);
      const bad = await page.eval(`(() => { const probe = document.createElement("span"); probe.style.color = "var(--pui-text)"; document.body.append(probe); const text = getComputedStyle(probe).color; probe.remove();
        return [...document.querySelectorAll(${JSON.stringify(SEL)})].map((el) => { const cs = getComputedStyle(el), b = getComputedStyle(el, "::before");
          const dot = b.content !== "none" && b.content !== "normal" && parseFloat(b.width) >= 6 && b.backgroundColor !== "rgba(0, 0, 0, 0)";
          return { el: el.className + " " + el.textContent.trim().slice(0, 24), colour: cs.color === text, dot, display: cs.display }; }).filter((x) => !x.colour || !x.dot); })()`);
      assert.deepEqual(bad, [], `${p.fixture} ${mode}: a state word is not in the text colour beside a dot`);
    }
  });

  test("the success and warning colours are never a text colour in the stylesheet", () => {
    const bad = rulesOf(SRC_CSS).filter(([sel, body]) => !/^:root/.test(sel))
      .filter(([sel]) => !/\bsvg$/.test(sel)) // an icon is a graphic: 3:1
      .flatMap(([sel, body]) => body.split(";").map((d) => d.trim()).filter((d) => /^color\s*:\s*var\(--pui-(success|warn)\)/.test(d)).map((d) => `${sel} { ${d} }`));
    assert.deepEqual(bad, []);
  });
});

// ---------------------------------------------------------------- item 2: the radius scale (DEV-23)
// 6 (control), 12 (card, code block), 16 (panel, hero), 9999 (pill); a circle is 50%. 1 to 4 px stays on thin bars, cells and inline marks only (user, 2026-10-11).
const RADIUS_OK = new Set(["0", "0px", "6px", "12px", "16px", "9999px", "50%", "inherit", "var(--pui-radius)", "var(--site-radius-card)", "var(--site-radius-panel)", "var(--site-radius-pill)"]);
const THIN = [".cells i", ".rp-dots button i", ".pw-pips i", ".marker", ".tour-state .bar", ".tour-state .bar i", ".scan::after", ".effect-hash .hx", "mark.inj", ".go-thr"];
describe("radius scale 6, 12, 16, 9999 (DEV-23)", () => {
  test("the stylesheet has no radius off the scale, the focus ring included", () => {
    const bad = [];
    for (const [sel, body] of rulesOf(SRC_CSS)) {
      for (const d of body.split(";")) {
        const m = /^\s*(border(?:-(?:top|bottom)-(?:left|right))?-radius)\s*:\s*(.+?)\s*(!important)?\s*$/.exec(d.replace(/\s+/g, " "));
        if (!m) continue;
        const values = m[2].replace(/var\((--[\w-]+)\)/g, "var($1)").split(" ").filter(Boolean);
        const off = values.filter((v) => !RADIUS_OK.has(v));
        if (off.length && !THIN.some((t) => sel.split(",").every((s) => s.trim().endsWith(t) || s.trim() === t))) bad.push(`${sel} { ${m[1]}: ${m[2]} }`);
      }
    }
    assert.deepEqual(bad, [], "radii off the scale");
    const focus = rulesOf(SRC_CSS).filter(([sel]) => sel === ":focus-visible").map(([, b]) => /border-radius\s*:\s*([^;]+)/.exec(b)?.[1].trim());
    assert.deepEqual(focus.map((v) => v === "var(--pui-radius)" || v === "6px"), [true], `the focus ring's radius is ${focus}`);
  });

  test("the radii in use on every page are on the scale", async () => {
    for (const p of PAGES) {
      await page.setup(WIDTHS[0], "light", { reduced: true });
      await page.goto(base + p.route);
      const bad = await page.eval(`(() => { const thin = ${JSON.stringify(THIN.filter((t) => !t.includes("::")))}; const ok = new Set(["0px", "6px", "12px", "16px", "50%"]); const seen = {};
        for (const el of document.body.querySelectorAll("*")) { if (el.closest("svg")) continue; const cs = getComputedStyle(el);
          for (const k of ["borderTopLeftRadius", "borderTopRightRadius", "borderBottomRightRadius", "borderBottomLeftRadius"]) { const v = cs[k].split(" ")[0];
            const pill = parseFloat(v) >= 9999 || ok.has(v); if (pill || thin.some((t) => el.matches(t))) continue;
            seen[el.tagName.toLowerCase() + "." + el.className + " " + k + "=" + v] = 1; } }
        return Object.keys(seen).slice(0, 12); })()`);
      assert.deepEqual(bad, [], `${p.fixture}: elements with a radius off the scale`);
    }
  });
});

// ---------------------------------------------------------------- item 3: tokens (DEV-24, DEV-17)
describe("no colour literal outside the token table (DEV-24); alias tokens mapped (DEV-17)", () => {
  const colourLiteral = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|(?<![\w-])(?:white|black|red|green|blue|gray|grey)(?![\w-])/g;
  test("components use tokens: no hex, rgb(), hsl() or colour name in a rule outside :root and the owl's palette", () => {
    const bad = [];
    for (const [sel, body] of rulesOf(SRC_CSS)) {
      if (/^:root(\[.*\])?$/.test(sel)) continue;
      const clean = body.replace(/url\("data:[^"]*"\)/g, "url()").replace(/transparent/g, "");
      for (const d of clean.split(";")) {
        if (/^\s*--owl-/.test(d) || /^\s*\.?owl-fig/.test(sel)) continue;
        const hit = d.match(colourLiteral);
        if (hit) bad.push(`${sel} { ${d.trim().slice(0, 80)} } -> ${hit.join(" ")}`);
      }
    }
    assert.deepEqual(bad, []);
  });

  test("the generated page stylesheets carry no literal either, beyond :root and the owl's palette", () => {
    for (const f of fs.readdirSync(path.join(SITE, "assets", "css")).filter((x) => x.endsWith(".css"))) {
      const bad = [];
      for (const [sel, body] of rulesOf(read("assets", "css", f))) {
        if (/^:root(\[.*\])?$/.test(sel) || /owl-fig/.test(sel) || /^@font-face/.test(sel)) continue;
        const clean = body.replace(/url\("data:[^"]*"\)/g, "url()").replace(/transparent/g, "");
        const hit = clean.match(colourLiteral);
        if (hit) bad.push(`${sel} -> ${hit.join(" ")}`);
      }
      assert.deepEqual(bad, [], `${f}`);
    }
  });

  test("the pages carry no colour literal in a style attribute or in a shape that is not the owl", () => {
    for (const f of PAGE_FILES) {
      const html = read(f);
      const styles = [...html.matchAll(/\sstyle="([^"]*)"/g)].map((m) => m[1]).filter((s) => colourLiteral.test(s)); colourLiteral.lastIndex = 0;
      assert.deepEqual(styles, [], `${f}: a style attribute holds a colour`);
    }
  });

  test("the aliases the hand-off maps are gone, and the design system's names are defined", () => {
    const root = rulesOf(SRC_CSS).filter(([sel]) => sel === ":root").map(([, b]) => b).join(";");
    const defined = new Set([...root.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
    for (const alias of ["--rail", "--r-control", "--r-card", "--r-panel", "--r-pill", "--elev", "--gutter", "--header-h"]) assert.ok(!defined.has(alias), `${alias} is still defined`);
    assert.ok(/--pui-radius\s*:/.test(read("assets", "vendor", "perfectui", "perfectui.css")), "the library no longer defines --pui-radius");
    for (const name of ["--site-radius-card", "--site-radius-panel", "--site-radius-pill", "--site-elev-raised", "--site-header-height"]) assert.ok(defined.has(name), `${name} is not defined`);
    const css = stripComments(SRC_CSS);
    for (const alias of ["--rail", "--r-control", "--r-card", "--r-panel", "--r-pill", "--elev", "--gutter", "--header-h"]) assert.ok(!new RegExp(`var\\(${alias}\\)`).test(css), `${alias} is still used`);
  });
});

// ---------------------------------------------------------------- item 4: the header is 64 px at every width (DEV-22)
describe("the header is 64 px at every width (DEV-22)", () => {
  for (const width of [375, 600, 899, 900, 1100, 1280]) {
    test(`the header is 64 px tall at ${width} px on every page, and the opened menu starts under it`, async () => {
      for (const p of PAGES) {
        await page.setup({ width, height: 900, mobile: width < 768 }, "light", { reduced: true });
        await page.goto(base + p.route);
        const h = await page.eval(`(() => { const hd = document.querySelector(".site-header"); const nav = document.querySelector(".site-nav"); const t = document.getElementById("nav-toggle"); if (t) { t.checked = true; t.dispatchEvent(new Event("change", { bubbles: true })); }
          return { header: hd.getBoundingClientRect().height, navTop: nav.getBoundingClientRect().top - hd.getBoundingClientRect().top }; })()`);
        assert.equal(h.header, 64, `${p.fixture} at ${width} px: the header is ${h.header} px tall`);
        if (width < 900) assert.equal(h.navTop, 64, `${p.fixture} at ${width} px: the opened menu starts ${h.navTop} px under the header's top`);
      }
    });
  }
});

// ---------------------------------------------------------------- item 5: owls and SVG (DEV-16, DEV-28)
// The lockup is the brand file; an id never repeats on a page; a decorative SVG is aria-hidden and has no role; a meaningful one has role="img" and a name.
describe("owls and SVG: ids, names, the brand mark (DEV-16, DEV-28)", () => {
  test("the header and footer lockup of every page is the brand file assets/img/openhora-mark.svg, byte for byte", () => {
    const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");
    const mark = fs.readFileSync(path.join(SITE, "assets", "img", "openhora-mark.svg"));
    const brand = path.resolve(SITE, "..", "interface", "brand", "openhora-mark.svg");
    if (fs.existsSync(brand)) assert.equal(sha(mark), sha(fs.readFileSync(brand)), "assets/img/openhora-mark.svg differs from interface/brand/openhora-mark.svg");
    assert.equal(mark.length, 2137, "the brand file is 2,137 bytes (the mockup's copy with a C2PA block is 9,911)");
    assert.ok(!/c2pa|jumbf/i.test(mark.toString("latin1")), "the mark carries a provenance block");
    for (const f of PAGE_FILES) {
      const html = read(f);
      const lockups = [...html.matchAll(/<a class="brandlink"[^>]*>(.*?)<\/a>/g)].map((m) => m[1]);
      assert.equal(lockups.length, 2, `${f}: header and footer lockups`);
      for (const l of lockups) assert.ok(/<img src="\/assets\/img\/openhora-mark\.svg" alt="openhora"/.test(l) && !/<svg/.test(l), `${f}: a lockup is not the brand file: ${l.slice(0, 80)}`);
    }
  });

  test("no id repeats on any page, the owls' clip paths included", async () => {
    for (const p of PAGES) {
      await page.setup(WIDTHS[0], "light");
      await page.goto(base + p.route);
      const dup = await page.eval(`(() => { const seen = {}, dup = []; for (const el of document.querySelectorAll("[id]")) { if (seen[el.id]) dup.push(el.id); seen[el.id] = 1; } return dup; })()`);
      assert.deepEqual(dup, [], `${p.fixture}: repeated ids`);
      const inline = fs.readFileSync(path.join(SITE, p.file), "utf8");
      const clips = [...inline.matchAll(/<clipPath id="([^"]+)"/g)].map((m) => m[1]);
      assert.equal(new Set(clips).size, clips.length, `${p.fixture}: an owl's clip path id repeats`);
    }
  });

  test("every SVG is hidden from assistive technology without a role, or is role=img with a name; no empty name on a role=img; no alt=\"\" with role=img", async () => {
    for (const p of PAGES) {
      await page.setup(WIDTHS[0], "light");
      await page.goto(base + p.route);
      const bad = await page.eval(`(() => { const out = []; const nameOf = (el) => { const l = el.getAttribute("aria-label"); if (l && l.trim()) return l.trim();
          const by = el.getAttribute("aria-labelledby"); if (by) { const t = by.split(/\\s+/).map((id) => document.getElementById(id)?.textContent.trim() || "").join(" ").trim(); if (t) return t; }
          const ti = el.querySelector(":scope > title"); return ti ? ti.textContent.trim() : ""; };
        for (const el of document.querySelectorAll("svg")) { if (el.parentElement.closest("svg")) continue;
          const hidden = el.getAttribute("aria-hidden") === "true" || !!el.parentElement.closest('[aria-hidden="true"]'), role = el.getAttribute("role"), desc = el.getAttribute("class") || el.outerHTML.slice(0, 40);
          if (role === "img") { if (!nameOf(el)) out.push("role=img without a name: " + desc); if (hidden) out.push("role=img inside aria-hidden: " + desc); }
          else if (role) out.push("unexpected role " + role + ": " + desc);
          else if (!hidden) out.push("neither aria-hidden nor role=img: " + desc);
          else if (el.getAttribute("aria-label") === "") out.push("empty aria-label: " + desc); }
        for (const el of document.querySelectorAll('[role="img"]')) { if (el.tagName.toLowerCase() === "svg") continue; if (!nameOf(el)) out.push("role=img without a name: " + el.className); }
        for (const el of document.querySelectorAll('img[role="img"][alt=""], [role="img"][aria-label=""]')) out.push("empty name with role=img: " + (el.className || el.tagName));
        for (const el of document.querySelectorAll("img")) if (el.getAttribute("alt") === null) out.push("img without alt: " + el.src);
        return out; })()`);
      assert.deepEqual(bad, [], `${p.fixture}: SVG and image names`);
    }
  });

  test("the hero owl's blink-and-look loop stays (8 s, infinite) and is still under reduced motion", async () => {
    for (const [route, sel] of [["/", ".dial-owl"], ["/404.html", ".nf-owl"]]) {
      await page.setup(WIDTHS[0], "light");
      await page.goto(base + route);
      const on = await page.eval(`(() => { const o = document.querySelector(${JSON.stringify(sel)}); return [...o.querySelectorAll(".owl-pupil, .owl-lid, .owl-lidline")].map((e) => { const cs = getComputedStyle(e); return [cs.animationName !== "none", cs.animationDuration, cs.animationIterationCount]; }); })()`);
      assert.ok(on.length >= 4 && on.every((x) => x[0] && x[1] === "8s" && x[2] === "infinite"), `${route}: the loop is not 8 s infinite: ${JSON.stringify(on)}`);
      await page.setup(WIDTHS[0], "light", { reduced: true });
      await page.goto(base + route);
      const still = await page.eval(`document.querySelector(${JSON.stringify(sel)}).getAnimations({ subtree: true }).length + [...document.querySelectorAll(${JSON.stringify(sel + " *")})].filter((e) => getComputedStyle(e).animationName !== "none").length`);
      assert.equal(still, 0, `${route}: the owl moves under reduced motion`);
    }
  });
});

// ---------------------------------------------------------------- item 6: "Which model runs this skill?" (DEV-26)
// A plain list of buttons: the search field, the list and its buttons, the selected skill marked with aria-current, one Tab stop per button, ArrowUp and ArrowDown between them.
describe("proof: the skill list is a list of buttons with no half listbox (DEV-26)", () => {
  const open = async () => { await page.setup(WIDTHS[0], "light"); await page.goto(base + "/proof"); await page.waitFor(`document.querySelector(".mr-name")?.textContent === "mkt-social-copy"`); };

  test("no listbox or option role is left, and every skill is a button in a list item", async () => {
    await open();
    const r = await page.eval(`(() => { const ul = document.getElementById("sk-list"); return { listbox: document.querySelectorAll('[role="listbox"], [role="option"]').length, ul: ul.tagName, role: ul.getAttribute("role"), label: ul.getAttribute("aria-label"),
      items: [...ul.children].every((li) => li.tagName === "LI" && !li.hasAttribute("role") && li.children.length === 1 && li.firstElementChild.tagName === "BUTTON" && !li.firstElementChild.hasAttribute("role") && li.firstElementChild.type === "button"),
      buttons: ul.querySelectorAll("button").length, current: [...ul.querySelectorAll('[aria-current="true"]')].map((b) => b.dataset.skill), selected: ul.querySelectorAll("[aria-selected]").length }; })()`);
    assert.deepEqual(r, { listbox: 0, ul: "UL", role: null, label: "Skills", items: true, buttons: 48, current: ["mkt-social-copy"], selected: 0 });
  });

  test("without script the list shows the same skill as the result", async () => {
    await page.setup(WIDTHS[0], "light");
    await page.scripts(false);
    try {
      await page.goto(base + "/proof", { scripts: false });
      const r = await page.eval(`({ name: document.querySelector(".mr-name").textContent, current: [...document.querySelectorAll('#sk-list [aria-current="true"]')].map((b) => b.dataset.skill) })`);
      assert.deepEqual(r, { name: "mkt-social-copy", current: ["mkt-social-copy"] });
    } finally { await page.scripts(true); }
  });

  test("keyboard: the field reaches the first match with ArrowDown, ArrowUp and ArrowDown move between skills, Enter picks one, the mark follows", async () => {
    await open();
    await page.eval(`document.getElementById("sk-q").focus()`);
    await page.key("ArrowDown", "ArrowDown", 40);
    assert.equal(await page.eval(`document.activeElement.dataset.skill`), "biz-icp-positioning");
    await page.key("ArrowDown", "ArrowDown", 40);
    const second = await page.eval(`document.activeElement.dataset.skill`);
    assert.equal(second, "biz-market-analysis");
    await page.key("ArrowUp", "ArrowUp", 38);
    assert.equal(await page.eval(`document.activeElement.dataset.skill`), "biz-icp-positioning");
    await page.key("ArrowDown", "ArrowDown", 40);
    await page.key("Enter", "Enter", 13);
    assert.ok(await page.waitFor(`document.querySelector(".mr-name").textContent === ${JSON.stringify(second)}`), "Enter on a skill did not show its result");
    assert.deepEqual(await page.eval(`[...document.querySelectorAll('#sk-list [aria-current="true"]')].map((b) => b.dataset.skill)`), [second], "the mark did not follow");
  });

  test("the search field narrows the list; Enter in the field picks the first match", async () => {
    await open();
    await page.eval(`(() => { const q = document.getElementById("sk-q"); q.focus(); q.value = "mkt-vote"; q.dispatchEvent(new Event("input", { bubbles: true })); })()`);
    const shown = await page.eval(`[...document.querySelectorAll("#sk-list li")].filter((li) => !li.hidden).map((li) => li.firstElementChild.dataset.skill)`);
    assert.ok(shown.length >= 1 && shown.every((s) => s.includes("mkt-vote")), `shown: ${shown}`);
    await page.key("Enter", "Enter", 13);
    assert.ok(await page.waitFor(`document.querySelector(".mr-name").textContent === ${JSON.stringify(shown[0])}`));
  });
});

// ---------------------------------------------------------------- item 8: links and routes (DEV-20, DEV-25)
const ROUTES = ["/", "/proof", "/first-steps", "/how-it-is-built", "/interface", "/glossary"];
describe("links and routes match the flows (DEV-20); GitHub links are checked by tools/check_links.py (DEV-25)", () => {
  test("every internal link of every page is a route of the flows (with an anchor that exists), an asset, or an anchor on its own page", () => {
    const ids = {};
    for (const f of PAGE_FILES) ids[f] = new Set([...read(f).matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]));
    const routeFile = { "/": "index.html", "/proof": "proof.html", "/first-steps": "first-steps.html", "/how-it-is-built": "how-it-is-built.html", "/interface": "interface.html", "/glossary": "glossary.html" };
    const bad = [];
    for (const f of PAGE_FILES) {
      for (const m of read(f).matchAll(/<a\b[^>]*?\shref="([^"]*)"/g)) {
        const href = m[1];
        if (/^https?:\/\//.test(href)) continue;
        if (href.startsWith("#")) { if (!ids[f].has(href.slice(1))) bad.push(`${f}: ${href} names no element of its page`); continue; }
        const [route, frag] = href.split("#");
        if (!ROUTES.includes(route)) { bad.push(`${f}: ${href} is not a route of the flows`); continue; }
        if (frag && !ids[routeFile[route]].has(frag)) bad.push(`${f}: ${href}: ${routeFile[route]} has no #${frag}`);
      }
    }
    assert.deepEqual(bad, []);
  });

  test("no page, script or stylesheet of the site links to a .html file", () => {
    const files = [...PAGE_FILES.map((f) => read(f)), ...fs.readdirSync(path.join(SITE, "assets", "js")).map((f) => read("assets", "js", f))];
    const bad = files.flatMap((t) => [...t.matchAll(/(?:href|src|location(?:\.href)?\s*=)\s*[="']\s*"?\/?[\w./-]*\.html\b[^"']*/g)].map((m) => m[0])).filter((x) => !/demo\/index\.html|404\.html/.test(x));
    assert.deepEqual(bad, []);
  });

  test("the seven differentiator anchors of the Proof page exist and the Home teasers link to them", () => {
    const proof = read("proof.html"), home = read("index.html");
    const anchors = [...new Set([...home.matchAll(/href="\/proof#([^"]+)"/g)].map((m) => m[1]))];
    assert.equal(anchors.length, 7);
    for (const a of anchors) assert.ok(new RegExp(`\\sid="${a}"`).test(proof), `proof.html has no #${a}`);
  });

  const CHECK = path.join(SITE, "tools", "check_links.py");
  const run = (args, cwd = SITE) => new Promise((resolve) => { const c = spawn("python3", [CHECK, ...args], { cwd }); let o = "", e = ""; c.stdout.on("data", (d) => (o += d)); c.stderr.on("data", (d) => (e += d)); c.on("close", (code) => resolve({ code, o, e })); });

  test("every GitHub link of the pages names a path that this checkout has (tools/check_links.py reports none missing)", async () => {
    const r = await run(["--only-missing"]);
    assert.equal(r.code, 0, r.o + r.e);
    assert.match(r.o, /SUMMARY\tchecked=\d+\tmissing=0/);
  });

  test("tools/check_links.py: --help works, and it lists the missing /blob/main and /tree/main targets of a fixture, offline", async () => {
    assert.ok(fs.existsSync(CHECK), "site/tools/check_links.py does not exist");
    const h = await run(["--help"]);
    assert.equal(h.code, 0); assert.ok(/--site/.test(h.o) && /--files/.test(h.o), "--help does not list --site and --files");
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "links-"));
    try {
      fs.writeFileSync(path.join(dir, "a.html"), `<a href="https://github.com/chrissgon/openhora/blob/main/README.md">r</a> <a href="https://github.com/chrissgon/openhora/blob/main/docs/missing.md#L3">m</a>
        <a href="https://github.com/chrissgon/openhora/tree/main/runtime/">t</a> <a href="https://github.com/chrissgon/openhora/tree/main/nowhere">n</a> <a href="https://github.com/chrissgon/openhora">repo</a> <a href="https://github.com/chrissgon/openhora/blob/main/docs/missing.md">dup</a> <a href="https://example.com/blob/main/x">other host</a>`);
      fs.writeFileSync(path.join(dir, "files.txt"), "README.md\nruntime/cli.py\nsite/index.html\n");
      const r = await run(["--site", dir, "--files", path.join(dir, "files.txt")]);
      const lines = r.o.trim().split("\n");
      assert.equal(r.code, 1, "exit code is 1 when a link is missing");
      assert.deepEqual(lines.filter((l) => l.startsWith("MISSING")).map((l) => l.split("\t").slice(0, 3)), [["MISSING", "blob", "docs/missing.md"], ["MISSING", "tree", "nowhere"]]);
      assert.ok(lines.some((l) => /^OK\tblob\tREADME\.md/.test(l)) && lines.some((l) => /^OK\ttree\truntime/.test(l)), "found links are listed as OK");
      assert.ok(lines.some((l) => l.startsWith("SUMMARY") && l.includes("checked=4") && l.includes("missing=2")), `summary line: ${r.o}`);
      const ok = await run(["--site", dir, "--files", path.join(dir, "files.txt"), "--only-missing"]);
      assert.ok(!/^OK/m.test(ok.o), "--only-missing lists no OK line");
    } finally { fs.rmSync(dir, { recursive: true, force: true }); }
  });
});

// ---------------------------------------------------------------- the social preview and the canonical links
// Static check of the page source (no browser): every page carries the Open Graph and Twitter card tags with absolute URLs, and the image they name exists.
describe("social preview", () => {
  const ORIGIN = "https://openhora.dev";
  const CANONICAL = { "index.html": "/", "proof.html": "/proof", "first-steps.html": "/first-steps", "how-it-is-built.html": "/how-it-is-built", "interface.html": "/interface", "glossary.html": "/glossary", "404.html": null };
  const IMAGE = `${ORIGIN}/assets/img/og-openhora.png`;
  const IMAGE_FILE = path.join(SITE, "assets", "img", "og-openhora.png");
  const metaOf = (html) => {
    const m = {};
    for (const t of html.matchAll(/<meta\s+(?:property|name)="([^"]+)"\s+content="([^"]*)">/g)) m[t[1]] = t[2];
    return m;
  };
  const decode = (s) => s.replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">");

  test("og-openhora.png exists, is 1200x630, is under 300 KB and has no metadata chunk", () => {
    assert.ok(fs.existsSync(IMAGE_FILE), "site/assets/img/og-openhora.png does not exist");
    const buf = fs.readFileSync(IMAGE_FILE);
    assert.ok(buf.length < 300 * 1024, `the image is ${buf.length} bytes, not under 300 KB`);
    assert.equal(buf.subarray(1, 4).toString(), "PNG");
    assert.equal(buf.readUInt32BE(16), 1200, "width");
    assert.equal(buf.readUInt32BE(20), 630, "height");
    const chunks = [];
    for (let i = 8; i < buf.length; i += 12 + buf.readUInt32BE(i)) chunks.push(buf.subarray(i + 4, i + 8).toString());
    const allowed = new Set(["IHDR", "PLTE", "IDAT", "IEND", "tRNS"]);
    assert.deepEqual(chunks.filter((c) => !allowed.has(c)), [], "the image carries a chunk that is not pixel data");
  });

  for (const [file, route] of Object.entries(CANONICAL)) {
    test(`${file} has the Open Graph and Twitter card tags with absolute URLs${route === null ? "" : " and a canonical link"}`, () => {
      const html = fs.readFileSync(path.join(SITE, file), "utf8");
      const m = metaOf(html);
      const title = decode(html.match(/<title>(.*?)<\/title>/)[1]);
      const description = decode(m.description);
      assert.ok(description, "the page has a meta description");
      assert.equal(m["og:type"], "website");
      assert.equal(m["og:site_name"], "openhora");
      assert.equal(decode(m["og:title"]), title);
      assert.equal(decode(m["og:description"]), description);
      assert.equal(m["og:image"], IMAGE);
      assert.equal(m["og:image:width"], "1200");
      assert.equal(m["og:image:height"], "630");
      assert.ok(m["og:image:alt"] && m["og:image:alt"].length > 10, "og:image:alt");
      assert.equal(m["twitter:card"], "summary_large_image");
      assert.equal(decode(m["twitter:title"]), title);
      assert.equal(decode(m["twitter:description"]), description);
      assert.equal(m["twitter:image"], IMAGE);
      const canonical = [...html.matchAll(/<link rel="canonical" href="([^"]*)">/g)].map((x) => x[1]);
      if (route === null) {
        assert.ok(!("og:url" in m), "the 404 page has no og:url");
        assert.deepEqual(canonical, [], "the 404 page has no canonical link");
      } else {
        assert.equal(m["og:url"], ORIGIN + route);
        assert.deepEqual(canonical, [ORIGIN + route], "exactly one canonical link, the page's absolute URL");
      }
    });
  }
});
