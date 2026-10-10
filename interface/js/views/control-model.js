// What the Control room shows, worked out from what the service returned: pure functions with no document and no
// network, so they run under a test. The inputs are the bodies of the operations `skills`, `costs`, `connections` and
// `agents`. Nothing is decided here: a band is the operation's word, a score is the operation's number (a score that is
// null is "-", never 0.00), a status is found or missing as the operation says. Handoff control-room.md is the authority
// for every word below.

import * as format from "../format.js";

export const TABS = Object.freeze([["skills", "Skills"], ["costs", "Costs"], ["connections", "Connections"]]);
export const NOT_ACCEPTED = "Waiting for the configuration to be accepted.";
export const LOADING = "Loading the proof, costs and connections...";

/** The tab a route names: skills when the hash names none or one this screen does not have. */
export function tabOf(name) {
  return TABS.some(([id]) => id === name) ? name : "skills";
}

/**
 * The panel's sub line (E-10): skills and costs are the project's, only the connections are the machine's. `name` is the project's name as the crumbs show it;
 * without one the line says "this project" (nothing is made up).
 */
export function subtitleOf(tab, name) {
  const whose = tabOf(tab) === "connections" ? "this machine" : (typeof name === "string" && name ? name : "this project");
  return `Skills, costs and connections of ${whose}`;
}

// --- the Skills tab -------------------------------------------------------------------------------------------------------

export const BANDS = Object.freeze(["reliable", "watch", "needs a test"]);
export const NEEDED_LIST = 4;       // E-15: up to four skills the list is shown as it is; past four it is a count and a disclosure
const BAND_TONE = Object.freeze({ reliable: "pui-success", watch: "pui-muted", "needs a test": "pui-error" });
export const TIER_COLUMNS = Object.freeze([["strong", "Reference model"], ["floor", "Floor model"]]);

/** The library classes of a band's chip; a word that is not one of the three is drawn like "watch" (muted), with its own word. */
export function bandClass(band) {
  return `pui-chip ${BAND_TONE[band] || "pui-muted"} pui-soft`;
}

/** A number to two decimals; null, a missing value or anything that is not a finite number is "-" (never 0.00). */
export function scoreText(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "-";
}

/** The pair of a skill for a tier ("strong" is the reference model, "floor" the floor model), or null. */
export function pairOf(skill, tier) {
  const proof = skill && Array.isArray(skill.proof) ? skill.proof : [];
  return proof.find((pair) => pair && pair.tier === tier) || null;
}

/** What a table cell or a card shows for a tier: {band, className, score} or null when the operation sent no pair. */
export function chipOf(skill, tier) {
  const pair = pairOf(skill, tier);
  if (!pair) return null;
  const band = typeof pair.band === "string" && pair.band ? pair.band : "-";
  return { band, className: bandClass(band), score: scoreText(pair.score) };
}

/** The distinct areas of the skills, sorted: the options of the Area filter. */
export function areasOf(skills) {
  const seen = new Set();
  for (const skill of Array.isArray(skills) ? skills : []) if (skill && typeof skill.area === "string" && skill.area) seen.add(skill.area);
  return [...seen].sort();
}

/**
 * The skills that pass the filters: area ("" is all), band ("" is all; a skill passes when either of its tiers has the
 * band, OPEN-27, so a row never hides a chip the person can read in it) and a name search (the typed text, trimmed,
 * case-insensitive, anywhere in the skill's name). Display only: nothing is written.
 */
export function filterSkills(skills, { area = "", band = "", name = "" } = {}) {
  const needle = String(name || "").trim().toLowerCase();
  return (Array.isArray(skills) ? skills : []).filter((skill) => {
    if (!skill) return false;
    if (area && skill.area !== area) return false;
    if (band && !(Array.isArray(skill.proof) && skill.proof.some((pair) => pair && pair.band === band))) return false;
    if (needle && !String(skill.name || "").toLowerCase().includes(needle)) return false;
    return true;
  });
}

/** "9 runs", "1 run" (the singular is the page's: the handoff writes "<runs> runs"). */
function runsWord(n) {
  const count = format.count(n);
  return `${count} ${count === 1 ? "run" : "runs"}`;
}

/** The sentence under an open row for one tier, built from the pair: "<column>: <model>, <adapter>, mean <mean>, <runs> runs. Cause: <cause or none>." */
export function detailLine(skill, tier, column) {
  const pair = pairOf(skill, tier);
  if (!pair) return `${column}: the service sent no proof for this model.`;
  const model = typeof pair.model === "string" && pair.model ? pair.model : "-";
  const adapter = typeof pair.adapter === "string" && pair.adapter ? pair.adapter : "-";
  const cause = typeof pair.cause === "string" && pair.cause ? pair.cause : "none";
  return `${column}: ${model}, ${adapter}, mean ${scoreText(pair.mean)}, ${runsWord(pair.runs)}. Cause: ${cause}.`;
}

/** The two sentences of an open row, reference model first. */
export function detailLines(skill) {
  return TIER_COLUMNS.map(([tier, column]) => detailLine(skill, tier, column));
}

/**
 * The lines of an open row (R-53, E-13): "Manifest: yes", "Runs here: 3" (a dash when the operation sent none), then the two sentences. The phone's card says the manifest
 * and the runs in its summary, so its body is `detailLines` alone.
 */
export function openLines(skill) {
  return [`Manifest: ${manifestText(skill)}`, `Runs here: ${skill && skill.runs_here !== undefined && skill.runs_here !== null ? skill.runs_here : "-"}`, ...detailLines(skill)];
}

/** "yes" or "no" for the Manifest column (only `true` is yes). */
export function manifestText(skill) {
  return skill && skill.manifest === true ? "yes" : "no";
}

/**
 * The checks notice, or null when it is not shown. It is shown when either check is not "ok"; both lines are always
 * printed, whole, as the operation words them.
 */
export function checksNotice(checks) {
  if (!checks || typeof checks !== "object") return null;
  const measurement = checks.measurement;
  const image = checks.image;
  if (measurement === "ok" && image === "ok") return null;
  const word = (value) => (typeof value === "string" && value ? value : "not known");
  return {
    title: "A check of the proof failed",
    sentence: "These skills run as not proven: on the reference model and without autonomy.",
    lines: [`Measurement check: ${word(measurement)}`, `Image check: ${word(image)}`],
  };
}

// --- the Connections tab --------------------------------------------------------------------------------------------------

/** The Requirement classes rows: {class, provider, provided, found, status, needed, skills, count, note}. `needed` is every skill, comma separated; past NEEDED_LIST skills the tab shows `<count> skills` as a disclosure (E-15, R-54). */
export function classRows(connections) {
  const list = connections && Array.isArray(connections.classes) ? connections.classes : [];
  return list.map((c) => ({
    class: String(c.class),
    provider: typeof c.provider === "string" && c.provider ? c.provider : "no provider found",
    provided: typeof c.provider === "string" && c.provider !== "",
    found: c.found === true,
    status: c.found === true ? "found" : "missing",
    needed: Array.isArray(c.skills) ? c.skills.join(", ") : "",
    skills: Array.isArray(c.skills) ? c.skills.map(String) : [],
    count: Array.isArray(c.skills) ? c.skills.length : 0,
    note: typeof c.note === "string" ? c.note : "",
  }));
}

/** The Secrets rows: {name, found, status, where}. A name, a status and a place; the operation holds no value and this reads none. */
export function secretRows(connections) {
  const list = connections && Array.isArray(connections.secrets) ? connections.secrets : [];
  return list.map((s) => ({
    name: String(s.name),
    found: s.found === true,
    status: s.found === true ? "found" : "missing",
    where: typeof s.where === "string" && s.where ? s.where : "-",
  }));
}

/** The accessible name of a secret's row: "CODE_HOST_TOKEN, found, in the secret store" / "FLOOR_MODEL_KEY, missing". */
export function secretName(row) {
  return row.found ? `${row.name}, found${row.where === "-" ? "" : `, in ${row.where.startsWith("the ") ? row.where : `the ${row.where}`}`}` : `${row.name}, missing`;
}

/** The Image card: {name, present, chip, tone, sentence}. */
export function imageCard(connections) {
  const image = (connections && connections.image) || {};
  const present = image.present === true;
  const measured = image.evidence === true ? "yes" : image.evidence === false ? "no" : "not known";
  return {
    name: typeof image.name === "string" && image.name ? image.name : "-",
    present,
    chip: present ? "present" : "missing",
    tone: present ? "pui-success" : "pui-error",
    sentence: `It is the image the evidence was measured in: ${measured}`,
  };
}

/**
 * The Platform card: {here, evidence, chip, tone, differs}. `here` is the platform the eval image runs as on this machine
 * and `evidence` the platform the lab evidence was made on; the chip follows `same` (true "same", false "differs", null
 * none). The page states no consequence of a difference.
 */
export function platformCard(connections) {
  const platform = (connections && connections.platform) || {};
  const text = (value) => (typeof value === "string" && value ? value : "not known");
  const same = platform.same;
  return {
    here: text(platform.here),
    evidence: text(platform.evidence),
    chip: same === true ? "same" : same === false ? "differs" : null,
    tone: same === true ? "pui-success" : "pui-warn",
    differs: same === false,
  };
}

// --- the Costs tab --------------------------------------------------------------------------------------------------------

/** "no agent" for a null agent (a project without area agents). */
export function agentLabel(agent) {
  return typeof agent === "string" && agent ? agent : "no agent";
}

/** The rows newest day first (a display sort, DIFF-68); within a day the operation's order stays. */
export function newestFirst(rows) {
  const list = (Array.isArray(rows) ? rows : []).map((row, index) => ({ row, index }));
  list.sort((a, b) => (a.row.day === b.row.day ? a.index - b.index : String(b.row.day).localeCompare(String(a.row.day))));
  return list.map((item) => item.row);
}

/** "412,300"; null is "-". */
export function tokensText(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("en-US") : "-";
}

/** The Recorded cell: {text, muted}. A null `recorded_usd` is "not recorded". */
export function recordedCell(row) {
  if (row.recorded_usd === null || row.recorded_usd === undefined) return { text: "not recorded", muted: true };
  return { text: format.dollars(row.recorded_usd), muted: false };
}

/** The Recomputed cell: dollars; else "no price" when the model has no price; else "unknown (N run|runs)" from `unknown_runs`. */
export function recomputedCell(row) {
  if (typeof row.recomputed_usd === "number") return { text: format.dollars(row.recomputed_usd), muted: false };
  if (row.price === null || row.price === undefined) return { text: "no price", muted: true };
  const unknown = format.count(row.unknown_runs);
  return { text: unknown > 0 ? `unknown (${unknown} ${unknown === 1 ? "run" : "runs"})` : "unknown", muted: true };
}

/** The footnote under the table. The price source and date come from the rows' `price`; without any, the words say what the cells mean. */
export function footnote(rows) {
  const seen = [];
  for (const row of Array.isArray(rows) ? rows : []) {
    const price = row && row.price;
    if (price && typeof price.source === "string" && !seen.some((p) => p.source === price.source && p.date === price.date)) seen.push(price);
  }
  const tail = "A run whose usage is unknown shows unknown and is counted.";
  if (!seen.length) {
    return `Recomputed from token counts and the prices in the project's configuration. A model with no price shows no price. ${tail}`;
  }
  const source = seen.map((p) => (p.date ? `${p.source}, ${p.date}` : p.source)).join("; ");
  return `Recomputed from token counts and the prices in the project's configuration (source: ${source}). ${tail}`;
}

/**
 * The caps line: "Caps · engineering: runs 5 / 12, spend $1.87 / $4.00". The limits are `costs.caps`; what was used today is
 * `runs_today` and `usd_today` of `agents` (a second read). "runs" count the runs on a subscription or free credential and "spend" the dollars
 * of runs on a metered one, said in the title and the accessible name. A part whose cap is not in use for the agent (`caps_in_use`, A-38) is
 * left out. Returns {text, title} or null when there is no cap.
 * `agents` may be null (that read failed): the used amounts are then "-", and both parts are shown.
 */
export function capsLine(caps, agents) {
  const list = Array.isArray(caps) ? caps : [];
  if (!list.length) return null;
  const used = new Map((Array.isArray(agents) ? agents : []).map((a) => [a.name, a]));
  const amount = (value) => (typeof value === "number" && Number.isFinite(value) ? String(value) : "-");
  const money = (value) => (typeof value === "number" && Number.isFinite(value) ? format.dollars(value) : "-");
  const parts = list.map((cap) => {
    const now = used.get(cap.agent);
    const note = now && typeof now.usd_reserved === "number" ? format.spendNote(now.usd_recorded, now.usd_reserved) : "";
    const total = now && typeof now.runs_total_today === "number" ? `, All runs today: ${now.runs_total_today}` : "";
    const use = format.metersInUse(now);
    const shown = [use.runs ? `runs ${now ? amount(now.runs_today) : "-"} / ${amount(cap.max_runs_per_day)}` : "",
      use.spend ? `spend ${now ? money(now.usd_today) : "-"} / ${money(cap.max_usd_per_day)}${note ? ` (${note})` : ""}` : ""].filter(Boolean);
    return `${agentLabel(cap.agent)}: ${shown.join(", ")}${total}`;
  });
  return { text: `Caps · ${parts.join("; ")}`, title: `${format.METER_TIPS.runs} ${format.METER_TIPS.spend}` };
}

/**
 * The caps as rows (R-52, E-16): one row per agent of `costs.caps` with the day's use from `agents` (null when that read failed: the used amounts are "-").
 * {title, runs, spend, rows: [{agent, total, runs: {text, share, full} | null, spend: {text, recordedShare, reservedShare, note, full} | null}]}.
 * `runs` and `spend` say whether any row has that meter (a meter whose cap is not in use for an agent, `caps_in_use`, is null in its row; one that no agent uses has no column).
 * `total` is the agent's runs of every model today (`runs_total_today`), null when the read has none: it is the muted "Runs today: n" under the name.
 * The words and the sentences are the KPI cards': `format.METER_WORDS` and `format.METER_TIPS`. Returns null when there is no cap.
 */
export function capsRows(caps, agents) {
  const list = Array.isArray(caps) ? caps : [];
  if (!list.length) return null;
  const used = new Map((Array.isArray(agents) ? agents : []).map((a) => [a.name, a]));
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const share = (value, cap) => (finite(value) && finite(cap) && cap > 0 ? Math.max(0, Math.min(1, value / cap)) : 0);
  const rows = list.map((cap) => {
    const now = used.get(cap.agent);
    const use = format.metersInUse(now);
    const runs = !use.runs ? null : {
      text: `${now && finite(now.runs_today) ? now.runs_today : "-"} / ${finite(cap.max_runs_per_day) ? cap.max_runs_per_day : "-"}`,
      share: now ? share(now.runs_today, cap.max_runs_per_day) : 0,
    };
    if (runs) runs.full = runs.share >= 1;
    let spend = null;
    if (use.spend) {
      const total = now ? share(now.usd_today, cap.max_usd_per_day) : 0;
      // the recorded part and the part reserved for runs whose cost is not recorded yet (A-20); when the read says nothing of the split the whole is "recorded"
      const split = now && finite(now.usd_recorded) && finite(now.usd_reserved);
      const recordedShare = split ? share(now.usd_recorded, cap.max_usd_per_day) : total;
      const reservedShare = split ? Math.min(1 - recordedShare, share(now.usd_reserved, cap.max_usd_per_day)) : 0;
      spend = {
        text: `${now && finite(now.usd_today) ? format.dollars(now.usd_today) : "-"} / ${finite(cap.max_usd_per_day) ? format.dollars(cap.max_usd_per_day) : "-"}`,
        recordedShare, reservedShare, full: total >= 1,
        note: now && finite(now.usd_reserved) ? format.spendNote(now.usd_recorded, now.usd_reserved) : "",
      };
    }
    return { agent: agentLabel(cap.agent), total: now && finite(now.runs_total_today) ? now.runs_total_today : null, runs, spend };
  });
  return {
    title: `Caps by agent. ${format.METER_TIPS.runs} ${format.METER_TIPS.spend}`,
    runs: rows.some((r) => r.runs), spend: rows.some((r) => r.spend), rows,
  };
}

// --- the service card ----------------------------------------------------------------------------------------------------

/**
 * The verdicts the local service made at its start (`connections.service`) that are not "ok": [{what, sentence, command}], in the order
 * secret store, credential, docker, image, dispatch, then each problem. The sentences and the command (`start`) are the service's; a verdict
 * that has no command in the terminal has none here. A null service (any process but the local service) has no rows.
 */
export function serviceRows(service) {
  if (!service || typeof service !== "object") return [];
  const rows = [];
  const bad = (value) => typeof value === "string" && value !== "ok";
  const start = typeof service.start === "string" && service.start ? service.start : null;
  if (bad(service.secret_store)) rows.push({ what: "Secret store", sentence: service.secret_store, command: start });
  if (bad(service.credential)) rows.push({ what: "Credential", sentence: service.credential, command: null });
  if (bad(service.docker)) rows.push({ what: "Docker", sentence: service.docker, command: null });
  if (bad(service.image)) rows.push({ what: "Image", sentence: service.image, command: null });
  if (service.dispatch === "off") rows.push({ what: "Dispatch", sentence: "Dispatch is off: the service starts no task by itself. Start it again without --no-dispatch:", command: start });
  for (const problem of Array.isArray(service.problems) ? service.problems : []) rows.push({ what: "Problem", sentence: String(problem), command: null });
  return rows;
}

// --- the chart ---------------------------------------------------------------------------------------------------------

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const CHART_DAYS = 7;
export const SERIES_CLASSES = Object.freeze(["wb-series-1", "wb-series-2", "wb-series-3"]);
export const OTHER_CLASS = "wb-series-other";

/** The day n days after `day` (YYYY-MM-DD), by calendar arithmetic in UTC (no time zone). */
export function addDays(day, n) {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** "Oct 7" for a day; a text that is not a day is returned as it came. */
export function dayLabel(day) {
  if (!DAY.test(day)) return String(day);
  return `${MONTHS[Number(day.slice(5, 7)) - 1]} ${Number(day.slice(8, 10))}`;
}

/**
 * The chart of the runs per day by agent (OPEN-29, OPEN-30), summed from the rows' `runs`: the window is the last seven
 * calendar days up to the newest day with rows and never before `since`; a day with no runs is an empty column; the scale is
 * the largest day's total. The three agents with the most runs in the rows keep a treatment (the theme, a tint of it, a
 * neutral), the rest are summed as "other". Returns null when no row has a day.
 *
 * {days: [{day, label, total, segments: [{series, label, className, runs, base, height}]}], series: [{key, label,
 * className, runs}], max, head: ["Day", ...labels], body: [[label, runs...]]}; base and height are percents of the plot.
 */
export function chartOf(rows, since) {
  const valid = (Array.isArray(rows) ? rows : []).filter((row) => row && DAY.test(String(row.day)) && format.count(row.runs) > 0);
  if (!valid.length) return null;
  const totals = new Map();
  for (const row of valid) totals.set(agentLabel(row.agent), (totals.get(agentLabel(row.agent)) || 0) + format.count(row.runs));
  const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const kept = ranked.length > SERIES_CLASSES.length ? ranked.slice(0, SERIES_CLASSES.length) : ranked;
  const rest = ranked.slice(kept.length);
  const series = kept.map(([label, runs], i) => ({ key: label, label, className: SERIES_CLASSES[i], runs }));
  if (rest.length) series.push({ key: "other", label: "other", className: OTHER_CLASS, runs: rest.reduce((sum, [, runs]) => sum + runs, 0) });
  const keyOf = (agent) => (series.some((s) => s.key === agentLabel(agent) && s.key !== "other") ? agentLabel(agent) : "other");

  const newest = valid.map((row) => row.day).sort().pop();
  let start = addDays(newest, -(CHART_DAYS - 1));
  if (typeof since === "string" && DAY.test(since) && since > start) start = since;
  const days = [];
  for (let day = start; day <= newest; day = addDays(day, 1)) days.push(day);

  const cells = days.map((day) => {
    const byKey = new Map();
    for (const row of valid) if (row.day === day) byKey.set(keyOf(row.agent), (byKey.get(keyOf(row.agent)) || 0) + format.count(row.runs));
    return { day, byKey, total: [...byKey.values()].reduce((a, b) => a + b, 0) };
  });
  const max = Math.max(1, ...cells.map((c) => c.total));
  const columns = cells.map((cell) => {
    let base = 0;
    const segments = [];
    for (const s of series) {
      const runs = cell.byKey.get(s.key) || 0;
      if (!runs) continue;
      const height = (runs / max) * 100;
      segments.push({ series: s.key, label: s.label, className: s.className, runs, base, height });
      base += height;
    }
    return { day: cell.day, label: dayLabel(cell.day), total: cell.total, segments };
  });
  return {
    days: columns,
    series,
    max,
    head: ["Day", ...series.map((s) => s.label)],
    body: cells.map((cell, i) => [columns[i].label, ...series.map((s) => cell.byKey.get(s.key) || 0)]),
  };
}

/** The sentence a chart column reads aloud in its tooltip: "Oct 7: 9 runs (engineering 5, marketing 4)". */
export function columnTitle(column) {
  const parts = column.segments.map((s) => `${s.label} ${s.runs}`).join(", ");
  return `${column.label}: ${column.total} ${column.total === 1 ? "run" : "runs"}${parts ? ` (${parts})` : ""}`;
}

// --- the small scene -----------------------------------------------------------------------------------------------------

export const RACKS = Object.freeze([
  { id: "rack-1", name: "store · tasks", z: -1.7 },
  { id: "rack-2", name: "integrations", z: -0.6 },
  { id: "rack-3", name: "vcs · publishers", z: 0.5 },
]);
export const UNITS = 7;
export const SLOTS = RACKS.length * UNITS;
export const OPENS = Object.freeze({ "rack-1": "connections", "rack-2": "connections", "rack-3": "connections", wall: "costs", console: "skills" });
/**
 * The object of each tab, the one the scene marks with its corner brackets while the tab is open (R-51): the console on Skills, the wall screen on Costs, the racks on Connections.
 * It is the grouping of `OPENS` (one list, not two that must agree), in the order of `OPENS`.
 */
const OBJECTS_OF = {};
for (const [object, tab] of Object.entries(OPENS)) (OBJECTS_OF[tab] = OBJECTS_OF[tab] || []).push(object);
export const OPEN_OF = Object.freeze(Object.fromEntries(Object.entries(OBJECTS_OF).map(([tab, objects]) => [tab, Object.freeze(objects)])));

/**
 * What the scene shows, from what the page has read: {ready, leds: [21 of "ok"|"bad"|"off"], facts, missing, racks: [{id, name,
 * missing, tip}], bars: [7 numbers from 0 to 1], tips: {wall, console}, label}. `ready` is false while the proof is loading,
 * for a project that is not accepted or before the connections have been read: every LED is then off and there are no bars.
 * An LED has one fact: the first 21 facts fill the racks from the top unit down; `missing` counts every fact the operation gave. `open` is the ids of the objects of the open `tab`
 * (a name this screen does not have is Skills), which the scene marks with corner brackets (R-51); none while the room is loading or not accepted, as the page draws it. `failed`
 * (the view's: the read of the connections failed) keeps the brackets on, as the page draws "A read that failed" (B3-5); the lights stay off and the bars empty.
 */
export function sceneModel({ accepted = true, connections = null, costs = null, tab = "skills", failed = false } = {}) {
  const facts = [];
  if (accepted && connections) {
    for (const row of classRows(connections)) facts.push(row.found);
    for (const row of secretRows(connections)) facts.push(row.found);
    facts.push(Boolean(connections.image && connections.image.present));
  }
  const missing = facts.filter((ok) => !ok).length;
  const leds = Array.from({ length: SLOTS }, (_, i) => (i < facts.length ? (facts[i] ? "ok" : "bad") : "off"));
  const read = Boolean(accepted && connections);
  // R-51, the page's tooltip: the racks are one object (one set of corner brackets, one way into Connections) and say "Connections · 2 missing · Connections tab"; each rack still has its own count
  const rackTip = !read ? "Connections · nothing read yet" : missing ? `Connections · ${missing} missing · Connections tab` : "Connections · all found · Connections tab";
  const racks = RACKS.map((rack, r) => {
    const here = facts.slice(r * UNITS, (r + 1) * UNITS);
    const gone = here.filter((ok) => !ok).length;
    return { id: rack.id, name: rack.name, missing: gone, tip: rackTip };
  });
  const bars = Array.from({ length: 7 }, () => 0);
  if (accepted && costs && Array.isArray(costs.rows)) {
    const chart = chartOf(costs.rows, costs.since);
    if (chart) {
      const days = chart.days.slice(-7);
      days.forEach((day, i) => { bars[7 - days.length + i] = chart.max > 0 ? day.total / chart.max : 0; });
    }
  }
  const ready = Boolean(accepted && connections);
  const label = ready
    ? `Server room: ${RACKS.length} racks, ${missing} ${missing === 1 ? "connection" : "connections"} missing, runs of the last 7 days`
    : accepted ? (failed ? "Server room, connections not read" : "Server room, loading") : "Server room, waiting for the configuration to be accepted";   // A6-13: a failed read says nothing was read; the page's label would claim nothing is missing
  // B3-5: a failed read of the connections draws the room as the page does, the lights off and the open tab's object marked (no data was read, but the person is on that tab); loading and not accepted draw no brackets
  const marked = ready || Boolean(accepted && failed);
  return { ready, failed: Boolean(accepted && failed && !connections), leds, facts: facts.length, missing, racks, bars, tips: { wall: "Runs by day · Costs tab", console: "Console · Skills tab" }, label, open: marked ? [...(OPEN_OF[tabOf(tab)] || [])] : [] };
}
