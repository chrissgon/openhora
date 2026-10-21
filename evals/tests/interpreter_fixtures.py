"""What the interpreter evidence tests share: a small checkout written to a folder (the data files the status script reads, with the
text of the specification's forms) and builders for event and item lines. Every name, model and route is fictional. No model is called."""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The test's own literal lists (an oracle never reads the code under test).
LANGS = ["pt-BR", "en", "es", "fr", "de", "it"]
SEVERITY = ["wrong_effect_unconfirmed", "wrong_card", "wrong_reminder_reading", "wrong_item_binding", "wrong_read", "wrong_route",
            "missed", "clarify", "correct"]
OBSERVED = ["executed", "card", "confirm", "remind_confirm", "read", "answer", "clarify", "route", "none", "refuse_d", "refuse_g",
            "refuse_policy", "forwarded", "outage"]
TAXONOMY = {"v": 1, "observed": OBSERVED, "severity": SEVERITY}
THRESHOLDS = {"v": 1, "runs": 2, "per_item": "worst-of-runs", "wilson_z": 1.96, "router_line_cost_usd": 0.0857,
              "languages": LANGS,
              "overall": {"wrong_effect_unconfirmed_max": 0,
                          "wilson_upper_max": {"wrong_card": 0.02, "wrong_read": 0.02, "wrong_reminder_reading": 0.02,
                                               "wrong_item_binding": 0.02},
                          "clarify_rate_max": 0.15, "p95_latency_ms_max": 4000, "median_cost_usd_max": 0.002},
              "per_language": {"point_max": {"wrong_card": 0.03, "wrong_read": 0.03, "wrong_reminder_reading": 0.03,
                                             "wrong_item_binding": 0.03},
                               "correct_direct_min": {"pt-BR": 0.85, "en": 0.85, "es": 0.75, "fr": 0.75, "de": 0.75, "it": 0.75}},
              "versus_current": {"correct_direct": "greater", "wrong_card": "not_greater"},
              "statements": ["0 of n is reported as < 3/n by the rule of three"]}
PROTOCOL = {"v": 1, "protocol": 1, "params": {"temperature": 0, "max_tokens": 300, "reasoning": "off"}, "deadline_ms": 6000,
            "max_line_chars": 1000, "max_output_bytes": 2048, "fence": "tolerated"}
CATALOG = {"v": 1, "ops": [{"op": "remind", "class": "N", "what": "set a reminder", "slots": {"when": "time"}}], "refused": []}
CATALOG_2 = {"v": 1, "ops": [{"op": "remind", "class": "N", "what": "set a reminder for later", "slots": {"when": "time"}}], "refused": []}


def route_row(rid, model, upstream, pin, reference=False):
    return {"id": rid, "model": model, "upstream_model": upstream, "base_url": "https://llm.example/api/v1", "pin": pin,
            "allow_fallbacks": False, "data_collection": "deny", "zdr": False, "cache_breakpoint": reference,
            "key": "WB_RUNTIME_KEY_EXAMPLE", "reference": reference, "retention": "A fictional route."}


ROUTES = {"v": 1, "routes": [route_row("fx-cheap", "example/cheap-1", "cheap/cheap-1", "hostone"),
                             route_row("fx-ref", "example/strong-1", "strong/strong-1", "hosttwo", reference=True)]}
H = {c: c * 64 for c in "abcdef0123"}
TEST_IDS = ["20301001T010101Z-00000001", "20301002T010101Z-00000002", "20301003T010101Z-00000003", "20301004T010101Z-00000004",
            "20301005T010101Z-00000005", "20301006T010101Z-00000006"]


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(obj):
    return hashlib.sha256(canon(obj)).hexdigest()


def put(root, rel, obj, raw=False):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if raw else json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def checkout(root, routes=ROUTES, catalog=CATALOG, per_lang=100):
    """The data files of a checkout, as the status script reads them; returns the hashes an event states. The test split has
    per_lang items in each of the six languages."""
    put(root, "runtime/interpreter_routes.json", routes)
    put(root, "runtime/interpreter_protocol.json", PROTOCOL)
    put(root, "runtime/interpreter_prompt.txt", "Turn the line into one frame.\n", raw=True)
    put(root, "runtime/interpreter_catalog.json", catalog)
    put(root, "evals/interpreter/taxonomy.json", TAXONOMY)
    put(root, "evals/interpreter/thresholds.json", THRESHOLDS)
    put(root, "evals/interpreter/test-split.json", {"v": 1, "file": "ix-test-v1.jsonl", "items": per_lang * len(LANGS),
                                                    "counts": {"lang": {lang: per_lang for lang in LANGS}}})
    put(root, "evals/interpreter/epochs.json", epochs(sha(catalog)))
    (Path(root) / "evals/interpreter/evidence").mkdir(parents=True, exist_ok=True)
    return hashes(root)


def epochs(served, *others):
    rows = [{"catalog_sha256": served, "date": "2030-10-01", "state": "served"}] + [
        {"catalog_sha256": c, "date": "2030-10-02", "state": state} for c, state in others]
    return {"v": 1, "served": served, "epochs": rows}


def file_sha(root, rel):
    return hashlib.sha256((Path(root) / rel).read_bytes()).hexdigest()


def hashes(root):
    """What this checkout's files hash to (the test's own computation, from the bytes and the literal objects above)."""
    routes = json.loads((Path(root) / "runtime/interpreter_routes.json").read_text())
    out = {"protocol_sha256": sha(json.loads((Path(root) / "runtime/interpreter_protocol.json").read_text())),
           "prompt_sha256": file_sha(root, "runtime/interpreter_prompt.txt"),
           "catalog_sha256": sha(json.loads((Path(root) / "runtime/interpreter_catalog.json").read_text())),
           "corpus_sha256": file_sha(root, "evals/interpreter/test-split.json"),
           "taxonomy_sha256": sha(json.loads((Path(root) / "evals/interpreter/taxonomy.json").read_text())),
           "thresholds_sha256": sha(json.loads((Path(root) / "evals/interpreter/thresholds.json").read_text())),
           "harness_sha256": H["f"]}
    for r in routes["routes"]:
        sent = {"id": r["id"], "base_url": r["base_url"], "model": r["upstream_model"], "pin": r["pin"],
                "allow_fallbacks": r["allow_fallbacks"], "data_collection": r["data_collection"], "zdr": r["zdr"],
                "cache_breakpoint": r["cache_breakpoint"]}
        out["route_sha256:" + r["id"]] = sha(sent)
    return out


def event(test, hs, route="fx-cheap", model="example/cheap-1", **change):
    line = {"record": "event", "kind": "interpreter", "test": test, "date": "2030-10-01", "arm": "bprime", "split": "test",
            "model": model, "route": route, "route_sha256": hs.get("route_sha256:" + str(route)), "protocol": 1,
            "protocol_sha256": hs["protocol_sha256"], "prompt_sha256": hs["prompt_sha256"], "catalog_sha256": hs["catalog_sha256"],
            "corpus_sha256": hs["corpus_sha256"], "taxonomy_sha256": hs["taxonomy_sha256"],
            "thresholds_sha256": hs["thresholds_sha256"], "harness_sha256": hs["harness_sha256"], "runs": 2, "items": 600,
            "sequential": True, "billing": "metered"}
    line.update(change)
    return line


def current_event(test, hs, **change):
    base = {"arm": "current", "model": None, "route": None, "route_sha256": None, "prompt_sha256": None, "billing": "none"}
    base.update(change)
    return event(test, hs, **base)


def item_id(split, lang, n):
    code = {"pt-BR": "pt-br", "mixed": "mx"}.get(lang, lang)
    return f"{split}-{code}-{n:05d}"


def item(test, i, lang, category, run=1, observed=None, latency=800, cost=0.001, split="test", gold="op", **change):
    observed = observed or {"correct": "read", "clarify": "clarify", "wrong_effect_unconfirmed": "executed", "wrong_card": "card"}.get(
        category, "none")
    if gold == "clarify" and category == "correct":
        observed = "clarify"
    line = {"record": "item", "test": test, "item": item_id(split, lang, i), "run": run, "lang": lang, "hard": False, "gold": gold,
            "category": category, "observed": observed, "parse": "ok", "error": None, "time_source": None, "latency_ms": latency,
            "usage": {"input": 900, "output": 40, "cache_read": 0, "cache_write": 0}, "cost_usd": cost, "upstream": "hostone"}
    line.update(change)
    return line


def corpus(per_lang=100, plan=None):
    """{(lang, n): category} of the whole split: every item `correct` except what `plan` maps ({(lang, n): category})."""
    out = {(lang, n): "correct" for lang in LANGS for n in range(1, per_lang + 1)}
    out.update(plan or {})
    return out


def lines_of(test, cells, runs=2, split="test", later_runs=None, golds=None, **change):
    """Item lines for every cell and run. later_runs ({(lang, n): category}) gives the category of the second run of a cell, golds
    ({(lang, n): gold word}) the gold of a cell (default `op`)."""
    out = []
    for (lang, n), category in sorted(cells.items()):
        for run in range(1, runs + 1):
            cat = (later_runs or {}).get((lang, n), category) if run >= 2 else category
            out.append(item(test, n, lang, cat, run=run, split=split, gold=(golds or {}).get((lang, n), "op"), **change))
    return out


def write_file(root, event_line, lines):
    path = Path(root) / "evals/interpreter/evidence" / f"ix-{event_line['test']}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in [event_line] + lines), encoding="utf-8")
    return path


def aggregate(test, lang, n, **counts):
    rest = n - sum(counts.values())
    return {"record": "aggregate", "test": test, "lang": lang, "n": n, "counts": {**counts, "correct": rest}, "parse_invalid": 0}
