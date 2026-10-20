#!/usr/bin/env python3
"""The standing of the natural-language interpreter, computed from its evidence: bands per (model, route, language) and
the go computation (the reliability model, docs/architecture/reliability-model-2026-10-02.md, section 5 "Interpreter bands").

Usage:
  python3 evals/interpreter_status.py status [--json] [--root <folder>]     the table (or its JSON) of every route and language
  python3 evals/interpreter_status.py go [--root <folder>]                   the go computation as JSON; exit 0 when go

(evals/eval_status.py loads this file: its `status` command adds an "interpreter" section and its `interpreter` command
prints the same table and, with --go, the go computation.)

What it reads, all as data (nothing of runtime/ is imported; a file that is absent makes the rows `needs a run`, and the
cause names the file):
  runtime/interpreter_routes.json, interpreter_protocol.json, interpreter_prompt.txt, interpreter_catalog.json
  evals/interpreter/taxonomy.json, thresholds.json, test-split.json, epochs.json, evidence/ix-<test id>.jsonl

The evidence is the lines of evals/interpreter/evidence/ (evidence_lines.py holds their closed forms): an event line, then
one item line per item and run (split dev or test) or one aggregate line per language (split local, the maintainer's counts).

The band of one (model, route, language), by the rules below, in this order:
  - Current set: the events of arm bprime on split test whose model, route, route_sha256, protocol_sha256, prompt_sha256,
    taxonomy_sha256 and thresholds_sha256 equal this checkout's, whose catalog_sha256 is the served catalog of epochs.json
    ("served", and the served file's hash equals it) and whose corpus_sha256 is the sha256 of the bytes of test-split.json.
    A change of any of them empties the set. The set must cover the held-out split (test-split.json states its `items` and its
    `counts.lang`): every event states that number of items, the item ids held add up to it and to its count in each language,
    and every item has at least thresholds.runs runs; a sample of the split is `needs a run`, as is a set with no event run
    sequentially. The cause says which. The latency and the cost are read from the sequential events' calls, a sample whose size
    ("sequential": calls, items, of) is published beside the band; a p95 of fewer than 20 calls is the maximum.
  - Each item takes the worst category of its runs (thresholds.per_item, the severity order of taxonomy.json). The counts of
    an item are over the route's items, the counts of a language over that language's items.
  - `reliable` iff every overall condition but the cost holds for the (model, route) and the language's per-language conditions
    hold: wrong_effect_unconfirmed at most its maximum; the Wilson upper bound (z = thresholds.wilson_z) of each of wrong_card,
    wrong_read, wrong_reminder_reading and wrong_item_binding at most its maximum; the clarify rate and the p95 latency (the
    sequential events' calls) at most theirs; in the language, each of those four rates (a point rate; its Wilson upper bound
    is published too) at most point_max and correct_direct at least its minimum. Else `below the gate`, and the cause is the
    first condition that fails, in that order.
  - A local aggregate (split local) newer than the newest test event of the current set, with the same route, prompt,
    protocol, taxonomy, thresholds and catalog, whose point rate of one of the four is over its point_max demotes that
    language, and one that holds a wrong_effect_unconfirmed demotes every language and the overall band, from `reliable` to
    `below the gate` (cause `local lines`). It never promotes.
  - go: the languages that run are those where the reference route (runtime/interpreter_routes.json) is `reliable` (D3'); with
    none, no. A route qualifies only if its overall band is `reliable` (after the local lines), it is `reliable` in at least one
    of those languages (so its per-language conditions hold there), the median cost of a call (from the lines that report one)
    is at most median_cost_usd_max in the language, and thresholds.versus_current holds against the current pipeline's run
    (correct_direct greater, wrong_card rate not greater) on the same corpus, taxonomy, thresholds and served catalog, with the
    same completeness as the B-prime set. The cheapest qualifying route is chosen and serves the languages in which it
    qualifies ("route_languages"); the others of "languages" run on the reference route.

The correct_direct and clarify_rate denominators leave out the items whose gold is `clarify`; an item line states the outcome
word of its gold ("gold"), and a line without it is not valid evidence, so no band or go is computed from one. Standard library
only; runs on Python 3.9.
"""
import hashlib
import importlib.util
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTES_REL = os.path.join("runtime", "interpreter_routes.json")
PROTOCOL_REL = os.path.join("runtime", "interpreter_protocol.json")
PROMPT_REL = os.path.join("runtime", "interpreter_prompt.txt")
CATALOG_REL = os.path.join("runtime", "interpreter_catalog.json")
TAXONOMY_REL = os.path.join("evals", "interpreter", "taxonomy.json")
THRESHOLDS_REL = os.path.join("evals", "interpreter", "thresholds.json")
SPLIT_REL = os.path.join("evals", "interpreter", "test-split.json")
EPOCHS_REL = os.path.join("evals", "interpreter", "epochs.json")
EVIDENCE_REL = os.path.join("evals", "interpreter", "evidence")
BANDS = ("reliable", "below the gate", "needs a run")
WRONG = ("wrong_card", "wrong_read", "wrong_reminder_reading", "wrong_item_binding")
ROUTE_KEYS = ("id", "base_url", "upstream_model", "pin", "allow_fallbacks", "data_collection", "zdr", "cache_breakpoint")


# --- hashes (the canonical form of the reliability model) ---------------------------------------------------------

def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_obj(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()


def sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def route_sha256(route):
    """The hash of the object the provider receives for a route: {id, base_url, model: upstream_model, pin, allow_fallbacks,
    data_collection, zdr, cache_breakpoint}."""
    sent = {k: route.get(k) for k in ROUTE_KEYS}
    sent["model"] = sent.pop("upstream_model")
    return sha_obj(sent)


def wilson_upper(k, n, z=1.96):
    """The upper end of the Wilson score interval of k out of n at z (1.96: 95%)."""
    if n <= 0:
        return 1.0
    p = k / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def _evidence_lines():
    name = "workbench_evidence_lines"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence_lines.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


# --- the inputs, read as data --------------------------------------------------------------------------------------

def _json(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def thresholds_problems(th, langs):
    """Why a parsed thresholds.json cannot be read by the rules above; [] when it can (its frozen content is IX-1's)."""
    try:
        o, pl, vs = th["overall"], th["per_language"], th["versus_current"]
        ok = (isinstance(th["runs"], int) and th["runs"] >= 1 and th["per_item"] == "worst-of-runs" and _is_number(th["wilson_z"])
              and isinstance(th["languages"], list) and th["languages"] and all(l in langs for l in th["languages"])
              and all(_is_number(o[k]) for k in ("wrong_effect_unconfirmed_max", "clarify_rate_max", "p95_latency_ms_max", "median_cost_usd_max"))
              and all(_is_number(o["wilson_upper_max"][c]) and _is_number(pl["point_max"][c]) for c in WRONG)
              and all(_is_number(pl["correct_direct_min"][l]) for l in th["languages"])
              and vs["correct_direct"] in ("greater", "not_greater") and vs["wrong_card"] in ("greater", "not_greater"))
    except (KeyError, TypeError):
        ok = False
    return [] if ok else ["thresholds.json is not in the form the status script reads"]


def taxonomy_problems(tax, severity):
    return [] if isinstance(tax.get("severity"), list) and set(tax["severity"]) == set(severity) else \
        ["taxonomy.json severity is not the categories of the evidence lines"]


def split_problems(split):
    """Why a parsed test-split.json cannot give the completeness of a run; [] when it can: `items` (a whole number from 1) and
    counts.lang ({language: whole number}) adding up to it."""
    langs = _evidence_lines().IX_LANGS
    try:
        items, by_lang = split["items"], split["counts"]["lang"]
        ok = (isinstance(items, int) and not isinstance(items, bool) and items >= 1 and isinstance(by_lang, dict)
              and all(k in langs and isinstance(v, int) and not isinstance(v, bool) and v >= 1 for k, v in by_lang.items())
              and sum(by_lang.values()) == items)
    except (KeyError, TypeError):
        ok = False
    return [] if ok else ["test-split.json is not in the form the status script reads"]


def load_inputs(root=ROOT):
    """{"routes", "thresholds", "taxonomy", "protocol_sha256", "prompt_sha256", "taxonomy_sha256", "thresholds_sha256",
    "corpus_sha256", "served", "catalog_ok", "missing"}: the checkout's own hashes. "missing" is the first required file that
    is absent or not a well-formed object (its relative path), else None; the other keys are filled as far as files allow."""
    out = {"missing": None, "reason": None, "routes": [], "reference": None, "served": None, "epochs": None}
    need = []
    routes = _json(root, ROUTES_REL)
    if not (isinstance(routes, dict) and isinstance(routes.get("routes"), list)):
        need.append(ROUTES_REL)
    else:
        out["routes"] = [r for r in routes["routes"] if isinstance(r, dict) and isinstance(r.get("id"), str)]
        refs = [r["id"] for r in out["routes"] if r.get("reference") is True]
        out["reference"] = refs[0] if len(refs) == 1 else None
    for key, rel in (("thresholds", THRESHOLDS_REL), ("taxonomy", TAXONOMY_REL)):
        data = _json(root, rel)
        if not isinstance(data, dict):
            need.append(rel)
        else:
            out[key] = data
            out[key + "_sha256"] = sha_obj(data)
    protocol = _json(root, PROTOCOL_REL)
    if not isinstance(protocol, dict):
        need.append(PROTOCOL_REL)
    else:
        out["protocol_sha256"] = sha_obj(protocol)
    for key, rel in (("prompt_sha256", PROMPT_REL), ("corpus_sha256", SPLIT_REL)):
        try:
            out[key] = sha_file(os.path.join(root, rel))
        except OSError:
            need.append(rel)
    split = _json(root, SPLIT_REL)
    if isinstance(split, dict) and not split_problems(split):
        out["split"] = {"items": split["items"], "lang": dict(split["counts"]["lang"])}
    elif SPLIT_REL not in need and os.path.exists(os.path.join(root, SPLIT_REL)):
        need.append(SPLIT_REL)
        out["reason"] = f"{SPLIT_REL} does not state its items and its counts per language (items, counts.lang)"
    epochs = _json(root, EPOCHS_REL)
    problems = _evidence_lines().interpreter_epochs_problems(epochs) if isinstance(epochs, dict) else ["not an object"]
    if problems:
        need.append(EPOCHS_REL)
    else:
        out["epochs"], out["served"] = epochs, epochs["served"]
    catalog = _json(root, CATALOG_REL)
    if not isinstance(catalog, dict):
        need.append(CATALOG_REL)
    elif out["served"] is not None and sha_obj(catalog) != out["served"]:
        need.append(CATALOG_REL)
        out["reason"] = f"{CATALOG_REL} differs from the served catalog of {EPOCHS_REL}"
    lines = _evidence_lines()
    if isinstance(out.get("thresholds"), dict) and thresholds_problems(out["thresholds"], lines.IX_LANGS):
        need.append(THRESHOLDS_REL)
    if isinstance(out.get("taxonomy"), dict) and taxonomy_problems(out["taxonomy"], lines.IX_SEVERITY):
        need.append(TAXONOMY_REL)
    # the files are listed in a fixed order for the cause; the thresholds and taxonomy come first in their own checks
    order = [ROUTES_REL, PROTOCOL_REL, PROMPT_REL, CATALOG_REL, TAXONOMY_REL, THRESHOLDS_REL, SPLIT_REL, EPOCHS_REL]
    need = sorted(set(need), key=order.index)
    if need:
        out["missing"] = need[0]
        if need[0] not in (CATALOG_REL, SPLIT_REL):
            out["reason"] = None
    return out


def read_events(root=ROOT):
    """[(event line, [item lines], [aggregate lines])] of every valid interpreter evidence file, oldest test id first. A file
    that is not valid is left out (`evidence` reports it)."""
    lines = _evidence_lines()
    folder = os.path.join(root, EVIDENCE_REL)
    found = []
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        path = os.path.join(folder, name)
        if not lines.INTERPRETER_FILE_RE.fullmatch(name) or lines.interpreter_file_problems(path):
            continue
        event, rest, _ = lines.read_evidence_file(path)
        items = [line for _, line in rest if line.get("record") == "item"]
        aggregates = [line for _, line in rest if line.get("record") == "aggregate"]
        found.append((event, items, aggregates))
    return sorted(found, key=lambda e: e[0]["test"])


# --- the measures --------------------------------------------------------------------------------------------------

def worst_per_item(items, severity):
    """{item id: the line of its worst category} (the first run of the worst category)."""
    rank = {c: i for i, c in enumerate(severity)}
    worst = {}
    for line in items:
        held = worst.get(line["item"])
        if held is None or rank[line["category"]] < rank[held["category"]]:
            worst[line["item"]] = line
    return worst


def measures(worst, z=1.96):
    """The counts and rates of a set of items (each the line of its worst run); the Wilson bounds are at z."""
    counts = {}
    for line in worst:
        counts[line["category"]] = counts.get(line["category"], 0) + 1
    n = len(worst)
    gold_clarify = sum(1 for l in worst if l["gold"] == "clarify")  # the items that are not asked of the model to answer directly
    direct = n - gold_clarify
    correct_direct = sum(1 for l in worst if l["category"] == "correct" and l["gold"] != "clarify")
    return {"n": n, "counts": counts, "direct": direct,
            "rate": {c: (counts.get(c, 0) / n if n else None) for c in WRONG},
            "wilson": {c: wilson_upper(counts.get(c, 0), n, z) for c in WRONG},
            "correct_direct": (correct_direct / direct if direct else None),
            "clarify_rate": (counts.get("clarify", 0) / direct if direct else None)}


def p95(values):
    """The nearest-rank 95th percentile, or None for no value."""
    ordered = sorted(values)
    return ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)] if ordered else None


def median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _check(name, value, limit, ok, detail=None):
    return {"name": name, "ok": ok, "text": detail or f"{name} is {_show(value)}, over the limit {limit}"}


def _show(value):
    return "n/a" if value is None else (f"{value:.4g}" if isinstance(value, float) else str(value))


def overall_checks(m, p95_ms, thresholds):
    """The overall conditions but the cost, in the order the cause reads them: [{"name", "ok", "text"}]."""
    o = thresholds["overall"]
    out = [_check("wrong_effect_unconfirmed", m["counts"].get("wrong_effect_unconfirmed", 0), o["wrong_effect_unconfirmed_max"],
                  m["counts"].get("wrong_effect_unconfirmed", 0) <= o["wrong_effect_unconfirmed_max"])]
    for cat in WRONG:
        limit = o["wilson_upper_max"][cat]
        k = m["counts"].get(cat, 0)
        bound = m["wilson"][cat]
        zero = f" ({k} of {m['n']}: < 3/{m['n']} by the rule of three)" if k == 0 else f" ({k} of {m['n']})"
        out.append(_check(f"{cat} Wilson upper bound", bound, limit, bound <= limit,
                          f"{cat} Wilson upper bound is {bound:.4f}, over {limit}{zero}"))
    rate = m["clarify_rate"]
    out.append(_check("clarify_rate", rate, o["clarify_rate_max"], rate is not None and rate <= o["clarify_rate_max"]))
    out.append(_check("p95_latency_ms", p95_ms, o["p95_latency_ms_max"], p95_ms is not None and p95_ms <= o["p95_latency_ms_max"],
                      "p95_latency_ms is unknown (no sequential call reported a latency)" if p95_ms is None
                      else f"p95_latency_ms is {p95_ms}, over {o['p95_latency_ms_max']}"))
    return out


def language_checks(m, lang, thresholds):
    """The per-language conditions of one language's measures, in order."""
    pl = thresholds["per_language"]
    out = []
    for cat in WRONG:
        rate, limit = m["rate"][cat], pl["point_max"][cat]
        out.append(_check(f"{lang} {cat} rate", rate, limit, rate is not None and rate <= limit,
                          f"{lang} {cat} rate is {_show(rate)}, over {limit}"))
    floor, direct = pl["correct_direct_min"][lang], m["correct_direct"]
    out.append(_check(f"{lang} correct_direct", direct, floor, direct is not None and direct >= floor,
                      f"{lang} correct_direct is {_show(direct)}, under {floor}"))
    return out


def _first_failure(checks):
    for c in checks:
        if not c["ok"]:
            return c["text"]
    return None


# --- the current set and the rows ----------------------------------------------------------------------------------

def _hash_fields(route, inputs):
    """The event fields a bprime event must carry to count here, with this checkout's value for each."""
    return (("model", route.get("model")), ("route", route["id"]), ("route_sha256", route_sha256(route)),
            ("protocol_sha256", inputs["protocol_sha256"]), ("prompt_sha256", inputs["prompt_sha256"]),
            ("taxonomy_sha256", inputs["taxonomy_sha256"]), ("thresholds_sha256", inputs["thresholds_sha256"]),
            ("catalog_sha256", inputs["served"]))


def current_set(route, inputs, events):
    """[(event, items, aggregates)] of the current set of a route: bprime events of split test that match (module docstring)."""
    fields = _hash_fields(route, inputs)
    return [e for e in events if e[0]["arm"] == "bprime" and e[0]["split"] == "test"
            and all(e[0].get(k) == v for k, v in fields) and e[0]["corpus_sha256"] == inputs["corpus_sha256"]]


def stale_cause(route, inputs, events):
    """Why a route has no current event: which input changed since its newest test event, else that none ran."""
    mine = [e for e in events if e[0]["arm"] == "bprime" and e[0]["split"] == "test" and e[0]["route"] == route["id"]]
    if not mine:
        return "no test run of this route"
    newest = mine[-1][0]
    changed = [k for k, v in _hash_fields(route, inputs) + (("corpus_sha256", inputs["corpus_sha256"]),) if newest.get(k) != v]
    return ("changed since the newest test run: " + ", ".join(changed)) if changed else "no test run of this route"


def _needs(route, lang, cause):
    return {"model": route.get("model"), "route": route["id"], "lang": lang, "band": "needs a run", "cause": cause}


def coverage_cause(events, inputs):
    """Why a set of events does not cover the held-out test split; None when it does. Every event states the split's number of
    items (a sample is not the split), the item ids held add up to it and to its count in each language, and every item has at
    least thresholds.runs distinct runs."""
    split, th = inputs["split"], inputs["thresholds"]
    for event, _, _ in events:
        if event["items"] != split["items"]:
            return (f"event {event['test']} states {event['items']} items and the test split has {split['items']}: "
                    "a sample of the split is not the split")
    runs_of, lang_of = {}, {}
    for event, rows, _ in events:
        for line in rows:
            lang_of[line["item"]] = line["lang"]
            runs_of.setdefault(line["item"], set()).add((event["test"], line["run"]))
    if len(runs_of) != split["items"]:
        return f"{len(runs_of)} of {split['items']} items have a run"
    held = {}
    for lang in lang_of.values():
        held[lang] = held.get(lang, 0) + 1
    if held != split["lang"]:
        lang = sorted(l for l in set(held) | set(split["lang"]) if held.get(l, 0) != split["lang"].get(l, 0))[0]
        return f"{held.get(lang, 0)} items of language {lang} have a run, and the test split has {split['lang'].get(lang, 0)}"
    short = sorted(i for i, r in runs_of.items() if len(r) < th["runs"])
    if short:
        return f"item {short[0]} has {len(runs_of[short[0]])} run(s), fewer than {th['runs']}"
    return None


def route_status(route, inputs, events):
    """{"overall": {...}, "rows": [one row per language of thresholds.languages]} for one route. A row:
    {"model", "route", "lang", "band", "cause", ...figures}."""
    th, tax = inputs["thresholds"], inputs["taxonomy"]
    langs = th["languages"]
    mine = current_set(route, inputs, events)
    if not mine:
        why = stale_cause(route, inputs, events)
        return {"overall": {"band": "needs a run", "cause": why}, "rows": [_needs(route, l, why) for l in langs]}
    cause = coverage_cause(mine, inputs)
    if cause is None and not any(e["sequential"] for e, _, _ in mine):
        cause = "no sequential run (the latency and the cost are measured on one call at a time)"
    if cause:
        return {"overall": {"band": "needs a run", "cause": cause}, "rows": [_needs(route, l, cause) for l in langs]}
    worst = worst_per_item([l for _, rows, _ in mine for l in rows], tax["severity"])
    m = measures(list(worst.values()), th["wilson_z"])
    seq = [l for e, rows, _ in mine if e["sequential"] for l in rows]
    p95_ms = p95([l["latency_ms"] for l in seq if l["latency_ms"] is not None])
    cost = median([l["cost_usd"] for l in seq if l["cost_usd"] is not None])
    sample = {"calls": len(seq), "items": len({l["item"] for l in seq}), "of": inputs["split"]["items"]}  # p95 of fewer than 20 calls is the maximum
    checks = overall_checks(m, p95_ms, th)
    overall_fail = _first_failure(checks)
    rows = []
    for lang in langs:
        mine_lang = [l for l in worst.values() if l["lang"] == lang]
        if not mine_lang:
            rows.append(_needs(route, lang, f"no item of language {lang} in the test split"))
            continue
        lm = measures(mine_lang, th["wilson_z"])
        fail = overall_fail or _first_failure(language_checks(lm, lang, th))
        lang_cost = median([l["cost_usd"] for l in seq if l["lang"] == lang and l["cost_usd"] is not None])
        rows.append({"model": route.get("model"), "route": route["id"], "lang": lang, "band": "below the gate" if fail else "reliable",
                     "cause": fail or "every condition holds", "items": lm["n"], "correct_direct": lm["correct_direct"],
                     "rate": lm["rate"], "wilson": lm["wilson"], "median_cost_usd": lang_cost})
    overall = {"band": "below the gate" if overall_fail else "reliable", "cause": overall_fail or "every overall condition holds",
               "measures": m, "p95_latency_ms": p95_ms, "median_cost_usd": cost, "sequential": sample, "checks": checks}
    if demote_by_local_lines(route, inputs, events, mine, rows) and overall["band"] == "reliable":
        overall["band"], overall["cause"] = "below the gate", "local lines"
    return {"overall": overall, "rows": rows}


def demote_by_local_lines(route, inputs, events, mine, rows):
    """A local aggregate newer than the newest test event of the set, over a point rate in its language, turns a `reliable` row into
    `below the gate` (cause `local lines`); one with a wrong_effect_unconfirmed turns every row, and the overall band, into it. It
    never changes another band. Returns whether a wrong_effect_unconfirmed was found."""
    newest = max(e["test"] for e, _, _ in mine)
    pl = inputs["thresholds"]["per_language"]["point_max"]
    local = [e for e in events if e[0]["split"] == "local" and e[0]["arm"] == "bprime" and e[0]["test"] > newest
             and all(e[0].get(k) == v for k, v in _hash_fields(route, inputs))]
    effect = any(a["counts"].get("wrong_effect_unconfirmed", 0) > 0 for _, _, aggs in local for a in aggs)
    for row in rows:
        if row["band"] != "reliable":
            continue
        over = [a for _, _, aggs in local for a in aggs if a["lang"] == row["lang"]
                and any(a["counts"].get(c, 0) / a["n"] > pl[c] for c in WRONG)]
        if effect or over:
            row["band"], row["cause"] = "below the gate", "local lines"
    return effect


def current_pipeline(inputs, events):
    """(events of the current-pipeline arm, None), or (None, the cause) when it has not run on this test split: the same checks as
    the B-prime set (the corpus, taxonomy, thresholds and served catalog hashes, the completeness, the runs)."""
    mine = [e for e in events if e[0]["arm"] == "current" and e[0]["split"] == "test" and e[0]["corpus_sha256"] == inputs["corpus_sha256"]
            and e[0]["taxonomy_sha256"] == inputs["taxonomy_sha256"] and e[0]["thresholds_sha256"] == inputs["thresholds_sha256"]
            and e[0]["catalog_sha256"] == inputs["served"]]
    if not mine:
        return None, "no run of the current pipeline on this test split"
    cause = coverage_cause(mine, inputs)
    return (None, "needs a run of the current pipeline: " + cause) if cause else (mine, None)


def go_of(inputs, statuses, events):
    """The go computation (module docstring). {"go", "cause", "route", "model", "languages", "route_languages", "versus_current", ...}.
    `languages` are those where the reference route is reliable (D3'); `route_languages` those of them the chosen route serves."""
    th = inputs["thresholds"]
    out = {"go": False, "cause": None, "route": None, "model": None, "languages": [], "route_languages": [], "versus_current": None}
    ref = next((s for r, s in statuses if r["id"] == inputs["reference"]), None)
    langs = [row["lang"] for row in ref["rows"] if row["band"] == "reliable"] if ref else []
    if not langs:
        out["cause"] = "the reference route is not reliable in any language"
        return out
    out["languages"] = langs
    current, why = current_pipeline(inputs, events)
    if current is None:
        out["cause"] = why
        return out
    cur = measures(list(worst_per_item([l for _, rows, _ in current for l in rows], inputs["taxonomy"]["severity"]).values()), th["wilson_z"])
    limit, vs = th["overall"]["median_cost_usd_max"], th["versus_current"]
    reasons, priced = [], []
    for route, status in statuses:
        ov = status["overall"]
        served = [row for row in status["rows"] if row["band"] == "reliable" and row["lang"] in langs]
        if ov["band"] != "reliable":
            reasons.append(f"{route['id']}: {ov['cause']}")
        elif not served:
            reasons.append(f"{route['id']}: reliable in no language where the reference route is reliable")
        elif ov["median_cost_usd"] is None:
            reasons.append(f"{route['id']}: no call reported a cost (an unmetered run has none)")
        else:
            priced.append((ov["median_cost_usd"], route["id"], route, status, served))
    for cost, rid, route, status, served in sorted(priced, key=lambda t: (t[0], t[1])):
        m = status["overall"]["measures"]
        cheap = [row["lang"] for row in served if row["median_cost_usd"] is not None and row["median_cost_usd"] <= limit]
        if not cheap:
            reasons.append(f"{rid}: median cost {cost:.5f} over {limit} in every language it is reliable in")
            continue
        better = (m["correct_direct"] is not None and cur["correct_direct"] is not None
                  and (m["correct_direct"] > cur["correct_direct"] if vs["correct_direct"] == "greater" else True))
        not_worse = m["rate"]["wrong_card"] is not None and cur["rate"]["wrong_card"] is not None and (
            m["rate"]["wrong_card"] <= cur["rate"]["wrong_card"] if vs["wrong_card"] == "not_greater" else True)
        if better and not_worse:
            out.update(go=True, cause="every condition holds", route=rid, model=route.get("model"), median_cost_usd=cost,
                       route_languages=cheap, versus_current={"correct_direct": [m["correct_direct"], cur["correct_direct"]],
                                                              "wrong_card": [m["rate"]["wrong_card"], cur["rate"]["wrong_card"]]})
            return out
        reasons.append(f"{rid}: " + ("correct_direct is not greater than the current pipeline's" if not better
                                     else "wrong_card rate is greater than the current pipeline's"))
    out["cause"] = "; ".join(reasons) or "no route"
    return out


def status(root=ROOT):
    """{"reference", "rows": [one per route and language], "go", "epochs": {...}}: everything computed from the files, live."""
    inputs = load_inputs(root)
    out = {"reference": inputs["reference"], "rows": [], "go": None, "missing": inputs["missing"]}
    if not inputs["routes"]:
        out["note"] = inputs["missing"] and f"{inputs['missing']} is missing or has no route"
        return out
    langs = (inputs.get("thresholds") or {}).get("languages") or []
    if inputs["missing"]:
        cause = inputs["reason"] or f"{inputs['missing']} is missing or not valid"
        out["rows"] = [_needs(r, l, cause) for r in inputs["routes"] for l in langs or ["-"]]
        out["go"] = {"go": False, "cause": cause, "route": None, "model": None, "languages": [], "versus_current": None}
        return out
    events = read_events(root)
    statuses = [(r, route_status(r, inputs, events)) for r in inputs["routes"]]
    out["rows"] = [row for _, s in statuses for row in s["rows"]]
    out["go"] = go_of(inputs, statuses, events)
    out["epochs"] = {"served": inputs["served"], "states": [e["state"] for e in inputs["epochs"]["epochs"]]}
    return out


def table(result):
    """The status as text lines: a heading, then one line per route and language."""
    lines = ["Interpreter (model, route, language, band, cause)"]
    if not result["rows"]:
        return lines + ["  no route: " + str(result.get("note") or "runtime/interpreter_routes.json is missing")]
    for row in result["rows"]:
        star = " (reference)" if row["route"] == result["reference"] else ""
        lines.append(f"  {row['model']} | {row['route']}{star} | {row['lang']} | {row['band']} | {row['cause']}")
    go = result.get("go")
    if go:
        lines.append("  go: " + ("yes via " + str(go["route"]) + " for " + ", ".join(go["languages"]) if go["go"] else "no (" + str(go["cause"]) + ")"))
    return lines


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    cmd, rest, root, as_json, i = argv[0], argv[1:], ROOT, False, 0
    while i < len(rest):
        if rest[i] == "--json":
            as_json, i = True, i + 1
        elif rest[i] == "--root" and i + 1 < len(rest):
            root, i = rest[i + 1], i + 2
        else:
            print(f"Error: unknown option {rest[i]!r}. See --help.", file=sys.stderr)
            return 2
    if cmd not in ("status", "go"):
        print(f"Error: unknown command {cmd!r}. See --help.", file=sys.stderr)
        return 2
    result = status(root)
    if cmd == "go":
        print(json.dumps(result["go"], indent=2))
        return 0 if result["go"] and result["go"]["go"] else 1
    print(json.dumps(result, indent=2) if as_json else "\n".join(table(result)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
