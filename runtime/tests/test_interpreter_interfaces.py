"""The interfaces the interpreter experiment shares (package IX-C0): the classification of the gated operations (runtime/gated_ops.json), the catalog
snapshot the interpreter is served (runtime/interpreter_catalog.py and its file), the protocol file, the frame schema, the taxonomy and the thresholds.

Every invariant is checked against the test's OWN literal lists (the 43 gated operations, the 16 widening, the 10 internal, the 17 operational, the 5 decisions),
read from the raw JSON files, never from the code under test; the groups are the one thing read from the module that owns them (`operations.GROUPS`), by the
rule "the first group whose operations hold the op". Each checker has a vacuity case: the same checker, run on a copy with one planted fault, must report it.

Offline, no model, no network. Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_interfaces.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import standin_tree as st
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
EVALS = REPO / "evals" / "interpreter"
catalog = st.load("interpreter_catalog")
natural = st.load("natural")
operations = st.load("operations")

GATED = [
    "give-consent", "set-mode", "set-model", "config", "accept-config", "routine-approve", "routine-resume", "instructions-set", "instructions-add",
    "source-add", "source-import", "source-refresh", "source-describe", "source-drive", "source-onedrive", "source-mail", "source-calendar", "flow-save",
    "stage-file", "sync", "hand-over", "dispatch", "verdict", "deps", "run-next", "run-task", "run-step", "proof", "approve-policy", "revoke-policy",
    "standing", "execute-under-policy", "contained-run", "poll", "handler", "pin", "stop-runs", "service-check", "route-queued", "attachment-hold",
    "conversation", "version", "artifact-raw"]
OPERATIONAL = ["routine-resume", "instructions-set", "instructions-add", "source-refresh", "source-describe", "flow-save", "stage-file", "sync", "hand-over",
               "dispatch", "verdict", "run-next", "run-task", "run-step", "proof", "revoke-policy", "stop-runs"]
WIDENING = ["give-consent", "set-mode", "set-model", "config", "accept-config", "routine-approve", "source-add", "source-import", "source-drive",
            "source-onedrive", "source-mail", "source-calendar", "approve-policy", "standing", "execute-under-policy", "deps"]
INTERNAL = ["contained-run", "poll", "handler", "pin", "service-check", "route-queued", "attachment-hold", "conversation", "version", "artifact-raw"]
DECISIONS = ["approve", "reject", "release", "answer", "go-ahead"]
NOT_SERVED = ["say", "request", "route"]
READS = ["status", "progress", "pending", "task", "agents", "skills", "costs", "artifacts", "artifact", "instructions", "routines", "sources", "attachments",
         "reminders", "flows", "flow-check", "connections", "commands", "items", "file-read", "research"]
NOTICES = ["remind", "reminder-forget", "reminder-restore"]
WRITES = ["cancel", "stop-task", "retry", "routine-pause", "routine-cancel", "routine-create", "routine-change", "attachment-add", "attachment-discard"]
EFFECTS = ["event-create", "event-change", "event-cancel", "mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash",
           "file-create", "file-replace", "file-save", "file-trash"]
KINDS = {"operational", "widening", "internal"}
SEVERITY = ["wrong_effect_unconfirmed", "wrong_card", "wrong_reminder_reading", "wrong_item_binding", "wrong_read", "wrong_route", "missed", "clarify", "correct"]
OBSERVED = ["executed", "card", "confirm", "remind_confirm", "read", "answer", "clarify", "route", "none", "refuse_d", "refuse_g", "refuse_policy",
            "forwarded", "outage"]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def first_group(op: str):
    return next((name for name, row in operations.GROUPS.items() if op in row["operations"]), None)


# --- the checkers (each one has a vacuity case below) --------------------------------------------------------------------------------------------

def gated_problems(doc: dict) -> list:
    """Everything wrong with a gated-operations document, by the test's own literal lists."""
    out = []
    if set(doc) != {"v", "rows"} or doc.get("v") != 1:
        out.append("keys")
    rows = doc.get("rows", [])
    if [r.get("op") for r in rows] != GATED:
        out.append("ops are not the literal list of 43, in order")
    for r in rows:
        if set(r) != {"op", "kind", "group", "why"}:
            out.append("%s: keys" % r.get("op"))
            continue
        want = "operational" if r["op"] in OPERATIONAL else "widening" if r["op"] in WIDENING else "internal" if r["op"] in INTERNAL else None
        if r["kind"] != want:
            out.append("%s: kind %s, want %s" % (r["op"], r["kind"], want))
        if r["group"] != first_group(r["op"]):
            out.append("%s: group %s, want %s" % (r["op"], r["group"], first_group(r["op"])))
        if not isinstance(r["why"], str) or not r["why"].strip():
            out.append("%s: why" % r["op"])
    return out


def snapshot_problems(snap: dict) -> list:
    """Everything wrong with a catalog snapshot, by the test's own lists (read from natural.NATURAL only for the text of `what` and the slots)."""
    out = []
    if set(snap) != {"v", "ops", "refused"} or snap.get("v") != 1:
        out.append("keys")
    names = [r["op"] for r in snap.get("ops", [])]
    refused = [r["op"] for r in snap.get("refused", [])]
    if len(names) != 65:
        out.append("ops count %d" % len(names))
    if len(refused) != 21:
        out.append("refused count %d" % len(refused))
    want_ops = set(READS + NOTICES + WRITES + EFFECTS + ["ask"] + OPERATIONAL)
    if set(names) != want_ops or len(set(names)) != len(names):
        out.append("ops are not the literal set")
    if set(refused) != set(DECISIONS + WIDENING) or len(set(refused)) != len(refused):
        out.append("refused are not the literal set")
    for name in INTERNAL + NOT_SERVED:
        if name in names or name in refused:
            out.append("%s is served" % name)
    for r in snap.get("ops", []):
        if set(r) != {"op", "class", "what", "slots"}:
            out.append("%s: row keys" % r.get("op"))
        want = ("R" if r["op"] in READS else "N" if r["op"] in NOTICES else "W" if r["op"] in WRITES else "E" if r["op"] in EFFECTS
                else "work" if r["op"] == "ask" else "G" if r["op"] in OPERATIONAL else None)
        if r.get("class") != want:
            out.append("%s: class %s, want %s" % (r.get("op"), r.get("class"), want))
    for r in snap.get("refused", []):
        if set(r) != {"op", "class", "what"}:
            out.append("%s: refused keys" % r.get("op"))
        want = "D" if r["op"] in DECISIONS else "G"
        if r.get("class") != want:
            out.append("%s: refused class" % r["op"])
    return out


# --- runtime/gated_ops.json ----------------------------------------------------------------------------------------------------------------------

def test_the_literal_lists_are_what_the_test_says_they_are():
    assert len(GATED) == 43 and len(set(GATED)) == 43
    assert len(OPERATIONAL) == 17 and len(WIDENING) == 16 and len(INTERNAL) == 10
    assert sorted(OPERATIONAL + WIDENING + INTERNAL) == sorted(GATED)
    assert len(DECISIONS) == 5


def test_the_gated_rows_are_exactly_the_43_ops_of_class_g():
    doc = load(RUNTIME / "gated_ops.json")
    assert gated_problems(doc) == []
    # the oracle's own list is the class G of the table, both ways
    assert [op for op, cls in natural.CLASSES.items() if cls == "G"] == GATED


def test_kind_and_group_of_every_row():
    doc = load(RUNTIME / "gated_ops.json")
    by = {r["op"]: r for r in doc["rows"]}
    assert {op for op, r in by.items() if r["kind"] == "operational"} == set(OPERATIONAL)
    assert {op for op, r in by.items() if r["kind"] == "widening"} == set(WIDENING)
    assert {op for op, r in by.items() if r["kind"] == "internal"} == set(INTERNAL)
    for op, r in by.items():
        assert r["group"] == first_group(op), op
    # the borderline rows, decided by recommendation (supervisor, reversible), pending the maintainer's confirmation (SPEC-IX-PHASE1 section 6, question 1)
    assert by["instructions-set"]["kind"] == by["instructions-add"]["kind"] == "operational"
    assert by["source-import"]["kind"] == by["deps"]["kind"] == by["config"]["kind"] == "widening"
    assert by["revoke-policy"]["kind"] == "operational"


def test_a_widening_row_names_its_reason_and_the_group_is_a_real_one_or_null():
    doc = load(RUNTIME / "gated_ops.json")
    by = {r["op"]: r for r in doc["rows"]}
    assert "installs code on the host" in by["deps"]["why"]
    assert "adds content the models read" in by["source-import"]["why"]
    assert "narrowing" in by["revoke-policy"]["why"]
    for op in WIDENING:
        if op not in ("config", "accept-config", "standing", "execute-under-policy"):
            assert "D10" in by[op]["why"] and "POL-1" in by[op]["why"], op
    for r in doc["rows"]:
        assert r["group"] is None or r["group"] in operations.GROUPS


def test_vacuity_a_flipped_kind_a_wrong_group_and_a_dropped_row_fail_the_checker():
    doc = load(RUNTIME / "gated_ops.json")
    flipped = copy.deepcopy(doc)
    flipped["rows"][0]["kind"] = "operational"        # give-consent is widening
    assert any("give-consent: kind" in p for p in gated_problems(flipped))
    regrouped = copy.deepcopy(doc)
    regrouped["rows"][1]["group"] = None
    assert any("set-mode: group" in p for p in gated_problems(regrouped))
    dropped = copy.deepcopy(doc)
    dropped["rows"].pop()
    assert gated_problems(dropped)
    extra_key = copy.deepcopy(doc)
    extra_key["rows"][2]["note"] = "x"
    assert any("keys" in p for p in gated_problems(extra_key))


# --- the served catalog ----------------------------------------------------------------------------------------------------------------------------

def test_the_served_file_equals_generate_and_the_counts_are_65_and_21():
    snap = load(RUNTIME / "interpreter_catalog.json")
    assert snap == catalog.generate()
    assert catalog.sha256(snap) == catalog.sha256(catalog.generate())
    assert snapshot_problems(snap) == []
    assert len(snap["ops"]) == 65 and len(snap["refused"]) == 21


def test_the_file_is_written_in_the_stated_form():
    raw = (RUNTIME / "interpreter_catalog.json").read_text(encoding="utf-8")
    snap = json.loads(raw)
    assert raw == json.dumps(snap, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def test_the_order_is_the_order_of_natural_with_ask_before_the_operational_gated_ops():
    snap = load(RUNTIME / "interpreter_catalog.json")
    names = [r["op"] for r in snap["ops"]]
    plain = [op for op in natural.NATURAL if op in READS + NOTICES + WRITES + EFFECTS]
    assert names == plain + ["ask"] + [op for op in natural.NATURAL if op in OPERATIONAL]
    assert [r["op"] for r in snap["refused"]] == [op for op in natural.NATURAL if op in DECISIONS] + [op for op in natural.NATURAL if op in WIDENING]


def test_a_row_carries_the_class_the_what_and_the_slot_kinds():
    snap = load(RUNTIME / "interpreter_catalog.json")
    by = {r["op"]: r for r in snap["ops"]}
    assert by["ask"]["class"] == "work"
    assert by["remind"] == {"op": "remind", "class": "N", "what": "a reminder sent back once at a time", "slots": {"text": "span", "when": "when"}}
    assert by["mail-archive"]["slots"] == {"messages": "ints"} and by["mail-archive"]["class"] == "E"
    assert by["status"]["slots"] == {} and by["cancel"]["slots"] == {"id": "int"}
    for r in snap["refused"]:
        assert set(r) == {"op", "class", "what"} and "slots" not in r
    assert {r["op"]: r["class"] for r in snap["refused"]}["approve"] == "D"
    assert {r["op"]: r["class"] for r in snap["refused"]}["deps"] == "G"


def test_no_internal_g_say_request_or_route_is_served():
    snap = load(RUNTIME / "interpreter_catalog.json")
    served = {r["op"] for r in snap["ops"]} | {r["op"] for r in snap["refused"]}
    for name in INTERNAL + NOT_SERVED:
        assert name not in served, name


def test_the_time_slots_are_the_three_pairs():
    assert catalog.TIME_SLOTS == (("remind", "when"), ("event-create", "time"), ("event-change", "time"))
    by = {r["op"]: r for r in load(RUNTIME / "interpreter_catalog.json")["ops"]}
    for op, slot in catalog.TIME_SLOTS:
        assert by[op]["slots"][slot] in ("when", "span")


def test_the_command_line_writes_checks_and_prints_the_hash(tmp_path):
    script = str(RUNTIME / "interpreter_catalog.py")
    check = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True, timeout=60)
    assert check.returncode == 0, check.stderr
    shown = subprocess.run([sys.executable, script, "--hash"], capture_output=True, text=True, timeout=60)
    assert shown.stdout.strip() == catalog.sha256(load(RUNTIME / "interpreter_catalog.json")) and len(shown.stdout.strip()) == 64
    help_ = subprocess.run([sys.executable, script, "--help"], capture_output=True, text=True, timeout=60)
    assert help_.returncode == 0 and "--write" in help_.stdout


def test_generate_follows_the_classification_it_is_given():
    rows = copy.deepcopy(load(RUNTIME / "gated_ops.json")["rows"])
    for r in rows:
        if r["op"] == "deps":
            r["kind"] = "operational"          # a planted reclassification moves the op from refused to ops
    moved = catalog.generate(rows)
    assert "deps" in [r["op"] for r in moved["ops"]] and "deps" not in [r["op"] for r in moved["refused"]]
    assert len(moved["ops"]) == 66 and len(moved["refused"]) == 20
    assert catalog.sha256(moved) != catalog.sha256(catalog.generate())


def test_vacuity_the_checker_catches_a_stale_file_and_planted_snapshots():
    snap = load(RUNTIME / "interpreter_catalog.json")
    extra = copy.deepcopy(snap)
    extra["ops"].append({"op": "fake-op", "class": "R", "what": "x", "slots": {}})
    assert snapshot_problems(extra)
    leaked = copy.deepcopy(snap)
    leaked["ops"].append({"op": "poll", "class": "G", "what": "x", "slots": {}})
    assert any("poll is served" in p for p in snapshot_problems(leaked))
    short = copy.deepcopy(snap)
    short["refused"].pop()
    assert any("refused count" in p for p in snapshot_problems(short))
    assert catalog.sha256(extra) != catalog.sha256(snap)        # the hash a stale file would have differs
    wrong_class = copy.deepcopy(snap)
    wrong_class["ops"][0]["class"] = "E"             # status is a read
    assert any("status: class E, want R" in p for p in snapshot_problems(wrong_class))
    wrong_g = copy.deepcopy(snap)
    next(r for r in wrong_g["ops"] if r["op"] == "sync")["class"] = "W"
    assert any("sync: class W, want G" in p for p in snapshot_problems(wrong_g))


# --- the other interface files ---------------------------------------------------------------------------------------------------------------------

def test_the_protocol_file_has_its_closed_keys():
    doc = load(RUNTIME / "interpreter_protocol.json")
    assert doc == {"v": 1, "protocol": 1, "params": {"temperature": 0, "max_tokens": 300, "reasoning": "off"}, "deadline_ms": 6000, "max_line_chars": 1000,
                   "max_output_bytes": 2048, "fence": "tolerated"}


def test_the_frame_schema_has_its_definitions_and_seven_rules():
    doc = load(EVALS / "frame.schema.json")
    assert set(doc) == {"$schema", "$id", "type", "additionalProperties", "required", "properties", "definitions", "x-rules"}
    assert doc["$id"] == "openhora:interpreter-frame:1" and doc["additionalProperties"] is False and doc["required"] == ["v", "items", "last"]
    assert set(doc["definitions"]) == {"id", "op", "slot", "words", "item", "last"}
    assert doc["properties"]["items"]["maxItems"] == 5
    assert doc["definitions"]["item"]["properties"]["kind"]["enum"] == ["write-draft", "reminder-confirm", "router-question", "choice", "plan-confirm"]      # BL2a: the fifth kind
    assert doc["definitions"]["item"]["properties"]["need"]["enum"] == ["slot", "confirm", "option", "text"]
    assert [r.split(" ")[0] for r in doc["x-rules"]] == ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]      # BL2a: R8, the plan-confirm item
    # every $ref resolves inside the document
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                refs.append(node["$ref"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(doc)
    assert refs and all(r.startswith("#/definitions/") and r.split("/")[-1] in doc["definitions"] for r in refs)


def test_the_taxonomy_has_its_lists_rules_metrics_and_one_example_per_rule():
    doc = load(EVALS / "taxonomy.json")
    assert set(doc) == {"v", "observed", "observed_meaning", "severity", "matching", "scopes", "rules", "metrics", "examples"} and doc["v"] == 1
    assert doc["observed"] == OBSERVED and set(doc["observed_meaning"]) == set(OBSERVED)
    assert doc["severity"] == SEVERITY
    assert [r["n"] for r in doc["rules"]] == list(range(1, 10))
    assert [r["category"] for r in doc["rules"]] == ["wrong_effect_unconfirmed", "wrong_card", "wrong_reminder_reading", "wrong_item_binding", "wrong_read",
                                                     "wrong_route", "clarify", "correct", "missed"]
    for r in doc["rules"]:
        assert r["category"] in SEVERITY
        assert r["observed"] == "any" or set(r["observed"]) <= set(OBSERVED)
    assert [m["name"] for m in doc["metrics"]] == ["N", "rate(c)", "correct_direct", "clarify_rate", "parse_failure_rate", "p95_latency_ms", "median_cost_usd",
                                                    "wrong_route_cost_usd"]
    assert len(doc["examples"]) == 32  # C0 wrote one per rule, first and in rule order; IX-1 added 23 when it froze the file
    nine = json.dumps(doc["examples"][:9], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(nine).hexdigest() == PINNED_HASHES["interpreter_interfaces_c0_nine_examples"]  # C0's nine, unchanged
    for e in doc["examples"]:
        assert set(e) == {"gold", "observed", "observed_detail", "category"}
        assert e["observed"] in OBSERVED and e["category"] in SEVERITY
    assert [e["category"] for e in doc["examples"][:9]] == [r["category"] for r in doc["rules"]]
    assert all(sum(e["category"] == r["category"] for e in doc["examples"]) >= 3 for r in doc["rules"])


def test_the_thresholds_have_their_values():
    doc = load(EVALS / "thresholds.json")
    assert set(doc) == {"v", "runs", "per_item", "wilson_z", "router_line_cost_usd", "languages", "overall", "per_language", "versus_current", "statements"}
    assert doc["runs"] == 2 and doc["wilson_z"] == 1.96 and doc["router_line_cost_usd"] == 0.0857 and doc["per_item"] == "worst-of-runs"
    assert doc["languages"] == ["pt-BR", "en", "es", "fr", "de", "it"]
    assert doc["overall"]["wrong_effect_unconfirmed_max"] == 0
    assert doc["overall"]["wilson_upper_max"] == {"wrong_card": 0.02, "wrong_read": 0.02, "wrong_reminder_reading": 0.02, "wrong_item_binding": 0.02}
    assert (doc["overall"]["clarify_rate_max"], doc["overall"]["p95_latency_ms_max"], doc["overall"]["median_cost_usd_max"]) == (0.15, 4000, 0.002)
    assert set(doc["per_language"]["correct_direct_min"]) == set(doc["languages"])
    assert doc["per_language"]["correct_direct_min"]["pt-BR"] == 0.85 and doc["per_language"]["correct_direct_min"]["it"] == 0.75
    assert doc["per_language"]["point_max"] == {"wrong_card": 0.03, "wrong_read": 0.03, "wrong_reminder_reading": 0.03, "wrong_item_binding": 0.03}
    assert doc["per_language"]["correct_direct_min"] == {"pt-BR": 0.85, "en": 0.85, "es": 0.75, "fr": 0.75, "de": 0.75, "it": 0.75}
    assert doc["statements"] == ["0 of n is reported as < 3/n by the rule of three", "at 50 items a per-language bound under 3% is unreachable"]
    assert doc["versus_current"] == {"correct_direct": "greater", "wrong_card": "not_greater"}


def test_every_file_is_canonical_json_of_its_own_kind_and_parses():
    for path in (RUNTIME / "gated_ops.json", RUNTIME / "interpreter_catalog.json", RUNTIME / "interpreter_protocol.json",
                 EVALS / "frame.schema.json", EVALS / "taxonomy.json", EVALS / "thresholds.json"):
        raw = path.read_text(encoding="utf-8")
        assert raw.endswith("\n") and not raw.endswith("\n\n"), path
        assert json.loads(raw) is not None


PROTOCOL = {"v": 1, "protocol": 1, "params": {"temperature": 0, "max_tokens": 300, "reasoning": "off"}, "deadline_ms": 6000, "max_line_chars": 1000,
            "max_output_bytes": 2048, "fence": "tolerated"}


def protocol_problems(doc: dict) -> list:
    return [] if doc == PROTOCOL else ["the protocol file differs from the literal"]


def severity_problems(doc: dict) -> list:
    return [] if doc.get("severity") == SEVERITY else ["severity differs from the literal order"]


def test_vacuity_a_file_with_an_unknown_key_or_a_changed_value_fails_its_checker():
    assert protocol_problems(load(RUNTIME / "interpreter_protocol.json")) == []
    assert protocol_problems(dict(PROTOCOL, extra=1))
    assert protocol_problems(dict(PROTOCOL, deadline_ms=7000))
    tax = load(EVALS / "taxonomy.json")
    assert severity_problems(tax) == []
    tax["severity"] = list(reversed(tax["severity"]))
    assert severity_problems(tax)


# --- an operational row never takes a path from words ------------------------------------------------------------------------------------------------

PATH_WORDS = ["file", "path", "dir", "directory", "folder", "file_name", "filename"]


def path_slot_problems(rows: list, natural_table: dict) -> list:
    """An operational row has no slot named like a path, and no slot whose parameter is, in `natural_table` ({op: {"slots": {slot: [kind, param]}}})."""
    out = []
    for r in rows:
        if r["kind"] != "operational":
            continue
        for slot, (kind, param) in natural_table.get(r["op"], {"slots": {}})["slots"].items():
            if slot in PATH_WORDS or param in PATH_WORDS or kind == "path":
                out.append("%s: slot %s is a path" % (r["op"], slot))
    return out


def test_no_operational_row_has_a_path_like_slot_and_the_file_rows_say_where_a_file_comes_from():
    rows = load(RUNTIME / "gated_ops.json")["rows"]
    assert path_slot_problems(rows, natural.NATURAL) == []
    # source-refresh, stage-file and hand-over take a host `file` argument in the table of operations: a line must never fill it
    file_rows = ["source-refresh", "stage-file", "hand-over"]
    by = {r["op"]: r for r in rows}
    for op in file_rows:
        args = next(r for r in operations.OPERATIONS if r["name"] == op)["args"]
        assert "file" in [a["name"] for a in args], op
        assert by[op]["kind"] == "operational" and natural.NATURAL[op]["slots"] == {}
        assert "the file only from the page or a held attachment, never a path from words" in by[op]["why"], op
    assert "read" in by["proof"]["why"] and "confirmation" not in by["proof"]["why"]


def test_vacuity_a_planted_path_slot_on_an_operational_row_fails_the_checker():
    rows = load(RUNTIME / "gated_ops.json")["rows"]
    planted = copy.deepcopy(dict(natural.NATURAL))
    planted["hand-over"] = {"slots": {"file": ["word", "file"]}}
    assert any("hand-over: slot file" in p for p in path_slot_problems(rows, planted))
    renamed = copy.deepcopy(dict(natural.NATURAL))
    renamed["stage-file"] = {"slots": {"what": ["word", "path"]}}
    assert path_slot_problems(rows, renamed)
    widening_planted = copy.deepcopy(dict(natural.NATURAL))
    widening_planted["source-add"] = {"slots": {"path": ["word", "path"]}}      # a widening row is not this checker's concern
    assert path_slot_problems(rows, widening_planted) == []
