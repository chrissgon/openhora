#!/usr/bin/env python3
"""The closed forms of a lab evidence file and the reading of its lines.

This module holds how an evidence line is read and checked: the regular expressions and helpers the forms
need, the keys of an event line and of a run line, `event_line_problems`, `run_line_problems`, the reading
of one file, and the walk over the evidence folders. It holds none of the gate (the configuration, the
baseline, the comparison) and none of the score or the bands: those are in evals/eval_status.py, which imports
this file by path and re-exports every name below, so the status script behaves as before and keeps every
name its importers use. It is not a measurement file (it is not in FINGERPRINT_FILES of eval_status.py): a
change to it asks for no new measurement version. Standard library only; runs on Python 3.9.

An evidence file is judged by itself (backlog T24), and a new one strictly
-------------------------------------------------------------------------
A committed evidence file is never edited, so it has to stay valid whatever the gate file says later. A file
already committed at the base of a change is therefore checked against what its own event line states, never
against today's gate file:

  1. "runs" is a whole number from RUNS_RANGE[0] to RUNS_RANGE[1] (the range the gate file's "runs" may take),
     and no case has more lines, on one model and one adapter, in one variant, than the event's "runs". A later
     change of "runs" in the gate file changes nothing here.
  2. A model id is valid when it is well formed (MODEL_RE) or the word "unknown". The ids an event line names
     are those of its "models", its "grader" and "unknown". The keys of its "counts" and "upstream" must be among
     them. The "model" of a run line must be one of the event's "models" (the word "unknown" only when the
     header names it); a run line is not allowed to name the grader. A model removed from the gate file's
     "models" later keeps its old lines valid. A malformed id is always refused.

A file that is new against the base of the change (scripts/validate.py reads the base the class checks read;
the runner checks the file it is about to copy into a skill) is read strictly, with `strict`, a dict
{"models": the ids of the gate file's "models", "runs": the gate file's configured runs}: every model id of the
event line and of the run lines is in that list (or "unknown"), so that a private model name never enters the
repository, and the event's "runs" equals the configured number, so that a trial or a forged event cannot enter
as evidence. Without a base (not a git checkout) every file is judged by its own event line, as the class checks
of the validator are skipped there too. The optional `models` argument of `event_line_problems` and
`run_line_problems` is that same allowlist, for a caller that wants the strict reading of one line.

Field evidence lines (scripts/evidence.py, `field_line_problems` of eval_status.py) have no event line to
state their models and keep being read against the gate file's list; that is outside this module.

The two shapes of the model header of an event line
---------------------------------------------------
  Old (every committed file): "models": {"strong": id[, "floor": id]} and "adapters": {"strong": folder[,
  "floor": folder]}, the same tier keys in both ("strong" is required).
  New (written by the model-keyed test event of a later package; this module only reads it): "models": a
  non-empty list of distinct ids, each a well-formed id or "unknown", and "adapters": {model id: adapter
  folder name} with exactly one key for each id of "models". In both shapes "adapter_sha256" is {adapter
  folder name: sha256 of its run-prompt.sh} with exactly the adapters named, and a run line's "adapter" is one
  of them.

`event_model_pairs(line)` returns, for either shape, the list of (model id, adapter folder name) the event
line names, in the order of the header ([] when the header is malformed), so callers never branch on the shape.
`tier_model(line, tier)` is the one reader of the old shape's tiers: the model written under a tier, None for the
new shape. It exists for the band logic that still compares the strong tier's model.

Usage (a library):
  python3 evals/evidence_lines.py --help        print this text
"""
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE_REL = os.path.join("evals", "evidence")
TIERS = ("strong", "floor")  # the tier keys of the old model header
RUNS_RANGE = (1, 10)  # the range an event's "runs" may take (the gate file's "runs" is held to the same range)

HEX64_RE = re.compile(r"[0-9a-f]{64}")
TEST_ID_RE = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
CASE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}")
VARIABLE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
TOOL_RE = re.compile(r"[A-Za-z0-9 ._()/+:,-]{1,80}")
KINDS, VARIANT_NAMES, OUTCOMES, BASELINES = ("full", "partial"), ("with", "without"), ("graded", "timeout"), ("run", "reused", "none")
COUNT_KEYS = ("retries", "refusals", "timeouts", "pauses", "early_ends", "resumes")
EVENT_REQUIRED = ("record", "skill", "test", "kind", "version", "content_sha256", "date", "models", "adapters",
                  "adapter_sha256", "grader", "runs", "timeout_seconds", "retries", "measurement_version",
                  "measurement_sha256", "image_digest", "image_platform", "grading_template_sha256", "tools", "cases",
                  "baseline", "web_cases", "counts", "extra_pass_env", "complete")
EVENT_OPTIONAL = ("gate", "upstream")
RUN_REQUIRED = ("record", "skill", "version", "content_sha256", "model", "adapter", "kind", "test", "date",
                "measurement_version", "measurement_sha256", "case", "case_sha256", "variant", "outcome", "score", "results")
RUN_OPTIONAL = ("context_sha256", "platform", "guard_failed", "cost_usd", "run_sha256")
GATE_KEYS = ("passed", "with", "baseline", "threshold", "tolerance")


def _is(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _number(value, low=0, high=1):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


def _count(value, low=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= low


def _model(value, models):
    return value == "unknown" or (_is(MODEL_RE, value) and (models is None or value in models))


def _case_id(value):
    return _count(value) or _is(CASE_ID_RE, value)


def _keys(line, required, optional):
    out = [f"unknown key {k!r}" for k in line if k not in required and k not in optional]
    return out + [f"missing key {k!r}" for k in required if k not in line]


def skill_names(root=ROOT):
    base = os.path.join(root, "skills")
    if not os.path.isdir(base):
        return []
    return sorted(d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "SKILL.md")))


# --- the model header of an event line, in both shapes ------------------------------------------------

MODELS_FORM = ("{\"strong\": model id[, \"floor\": model id]} or a non-empty list of distinct model ids, "
               "each a well-formed id or \"unknown\"")
LISTED = " in the gate file's model list"  # said when the strict reading (a models allowlist) is on
ADAPTERS_FORM_OLD = "an adapter's folder name for each tier of models"
ADAPTERS_FORM_NEW = "{model id: an adapter's folder name}, one for each model of models"


def _header(line, models=None):
    """(pairs, problems) of the "models" and "adapters" of an event line. pairs is [(model id, adapter)] and is
    empty when either key is malformed; problems holds at most one text for "models" and one for "adapters"."""
    tiers, adapters = line["models"], line["adapters"]
    problems, pairs = [], []
    adapters_ok = isinstance(adapters, dict) and all(_is(NAME_RE, v) for v in adapters.values())
    if isinstance(tiers, list):  # the new shape
        ok = (bool(tiers) and all(isinstance(v, str) and _model(v, models) for v in tiers) and len(set(tiers)) == len(tiers))
        if not ok:
            problems.append(f"models must be {MODELS_FORM}")
        if not (adapters_ok and (not ok or set(adapters) == set(tiers))):
            problems.append(f"adapters must be {ADAPTERS_FORM_NEW}")
        elif ok:
            pairs = [(v, adapters[v]) for v in tiers]
        return pairs, problems
    ok = (isinstance(tiers, dict) and bool(tiers) and "strong" in tiers and set(tiers) <= set(TIERS)
          and all(isinstance(v, str) and _model(v, models) for v in tiers.values()))
    if not ok:
        problems.append(f"models must be {MODELS_FORM}")
    if not (adapters_ok and (not ok or set(adapters) == set(tiers))):
        problems.append(f"adapters must be {ADAPTERS_FORM_OLD}")
    elif ok:
        pairs = [(tiers[t], adapters[t]) for t in TIERS if t in tiers]
    return pairs, problems


def event_model_pairs(line):
    """[(model id, adapter folder name)] an event line names, whichever header shape it has, in the order of the
    header; [] when the line is not a dict or its "models" or "adapters" is malformed."""
    if not isinstance(line, dict) or "models" not in line or "adapters" not in line:
        return []
    return _header(line)[0]


def tier_model(line, tier):
    """The model id an event line of the old shape writes under a tier ("strong", "floor"), None for a line of
    the new shape or without that tier."""
    models = line.get("models") if isinstance(line, dict) else None
    return models.get(tier) if isinstance(models, dict) else None


def event_line_problems(line, models=None):
    """Why an event line is outside its form. Its model ids are judged by what the line itself names (the
    module docstring); models is an optional set of known model ids, an extra allowlist that is None for the
    validator."""
    out = _keys(line, EVENT_REQUIRED, EVENT_OPTIONAL)
    if out:
        return out
    bad = lambda key, form: out.append(f"{key} must be {form}")
    if line["record"] != "test":
        bad("record", "\"test\"")
    if not _is(NAME_RE, line["skill"]):
        bad("skill", "a skill name")
    if not _is(TEST_ID_RE, line["test"]):
        bad("test", "a test id (YYYYMMDDTHHMMSSZ-8 hex)")
    if line["kind"] not in KINDS:
        bad("kind", "full or partial")
    if not _is(VERSION_RE, line["version"]):
        bad("version", "X.Y.Z")
    for key in ("content_sha256", "measurement_sha256", "grading_template_sha256"):
        if not _is(HEX64_RE, line[key]):
            bad(key, "64 hexadecimal characters")
    if not _date(line["date"]):
        bad("date", "YYYY-MM-DD")
    pairs, header = _header(line, models)
    out += header
    hashes = line["adapter_sha256"]
    if not (isinstance(hashes, dict) and all(_is(NAME_RE, k) and _is(HEX64_RE, v) for k, v in hashes.items())
            and (not isinstance(line["adapters"], dict) or set(hashes) == set(line["adapters"].values()))):
        bad("adapter_sha256", "the sha256 of the run-prompt.sh of each adapter named in adapters")
    if not (isinstance(line["grader"], str) and _model(line["grader"], models)):
        bad("grader", "a well-formed model id" + (LISTED if models is not None else "") + ", or \"unknown\"")
    # The ids the line names: its models, its grader and "unknown". While the header is malformed there is no
    # such list, and a model id is judged by its form alone, so that one fault is reported once.
    named = None
    if pairs and isinstance(line["grader"], str):
        named = {m for m, _ in pairs} | {line["grader"], "unknown"}
    for key, low in (("runs", 1), ("timeout_seconds", 1), ("retries", 0), ("measurement_version", 1)):
        if not _count(line[key], low):
            bad(key, f"a whole number, {low} or more")
    if _count(line["runs"], 1) and line["runs"] > RUNS_RANGE[1]:
        bad("runs", f"a whole number from {RUNS_RANGE[0]} to {RUNS_RANGE[1]}")
    if not (isinstance(line["image_digest"], str) and re.fullmatch(r"sha256:[0-9a-f]{64}", line["image_digest"])):
        bad("image_digest", "sha256:<64 hexadecimal characters>")
    if not (isinstance(line["image_platform"], str) and re.fullmatch(r"linux/[a-z0-9]+(/[a-z0-9]+)?", line["image_platform"])):
        bad("image_platform", "a platform such as linux/arm64")
    if not (isinstance(line["tools"], dict) and all(_is(NAME_RE, k) and _is(TOOL_RE, v) for k, v in line["tools"].items())):
        bad("tools", "{tool name: its version line}")
    cases = line["cases"]
    if not (isinstance(cases, dict) and cases and all(_is(CASE_ID_RE, k) and _is(HEX64_RE, v) for k, v in cases.items())):
        bad("cases", "{case id: the case's hash}, at least one")
        cases = {}
    if not (isinstance(line["baseline"], dict) and set(line["baseline"]) == set(cases or line["baseline"])
            and all(v in BASELINES for v in line["baseline"].values())):
        bad("baseline", "run, reused or none for each case of cases")
    if not (isinstance(line["web_cases"], list) and all(_case_id(v) and str(v) in (cases or {str(v): 1}) for v in line["web_cases"])):
        bad("web_cases", "a list of ids of cases")
    # A key of "counts" or "upstream" is a model id the line itself names (the header, the grader, "unknown").
    is_named = lambda key: isinstance(key, str) and _model(key, models) and (named is None or key in named)
    counts = line["counts"]
    ok = isinstance(counts, dict) and all(is_named(model) and isinstance(by, dict) and by and set(by) <= set(VARIANT_NAMES)
                                          for model, by in counts.items())
    for by in counts.values() if ok else []:
        for variant, c in by.items():
            allowed = COUNT_KEYS + (("invoked",) if variant == "with" else ())
            ok = ok and isinstance(c, dict) and set(COUNT_KEYS) <= set(c) and set(c) <= set(allowed) and all(_count(v) for v in c.values())
    if not ok:
        bad("counts", "{model id: {\"with\"|\"without\": {" + ", ".join(COUNT_KEYS) + "[, invoked]: whole numbers}}}, "
            "each model id one the line names")
    if not (isinstance(line["extra_pass_env"], list) and all(_is(VARIABLE_RE, v) for v in line["extra_pass_env"])):
        bad("extra_pass_env", "a list of variable names")
    if not isinstance(line["complete"], bool):
        bad("complete", "true or false")
    if "gate" in line:
        g = line["gate"]
        if line["kind"] != "full":
            out.append("gate belongs to a full test only: a partial test never evaluates the gate")
        elif not (isinstance(g, dict) and set(GATE_KEYS) <= set(g) and set(g) <= set(GATE_KEYS + ("note",))
                  and isinstance(g["passed"], bool) and _number(g["with"]) and (g["baseline"] is None or _number(g["baseline"]))
                  and _number(g["threshold"]) and _number(g["tolerance"]) and g.get("note", "baseline expired") == "baseline expired"):
            bad("gate", "{\"passed\": bool, \"with\": mean, \"baseline\": mean or null, \"threshold\", \"tolerance\"[, \"note\": \"baseline expired\"]}")
        elif line["complete"] is not True:
            out.append("gate is written by a complete full test only: an event closed as abandoned evaluates no gate")
    elif line["kind"] == "full" and line["complete"] is True:
        out.append("a complete full test carries its gate")
    if "upstream" in line and not (isinstance(line["upstream"], dict) and all(
            is_named(k) and _is(TOOL_RE, v) for k, v in line["upstream"].items())):
        bad("upstream", "{model id the line names: the upstream provider the key proxy's route pins}")
    return out


def run_line_problems(line, event=None, models=None):
    """Why a run line is outside its form, or disagrees with the event line of its file. Given the event line, the
    run's model is one of the event's models ("unknown" only when the event's header names it) and its adapter one
    of the event's adapters; models is the optional extra allowlist of event_line_problems."""
    out = _keys(line, RUN_REQUIRED, RUN_OPTIONAL)
    if out:
        return out
    bad = lambda key, form: out.append(f"{key} must be {form}")
    if line["record"] != "run":
        bad("record", "\"run\"")
    if not _is(NAME_RE, line["skill"]):
        bad("skill", "a skill name")
    if not _is(VERSION_RE, line["version"]):
        bad("version", "X.Y.Z")
    for key in ("content_sha256", "measurement_sha256", "case_sha256") + (("context_sha256",) if "context_sha256" in line else ()):
        if not _is(HEX64_RE, line[key]):
            bad(key, "64 hexadecimal characters")
    if not (isinstance(line["model"], str) and _model(line["model"], models)):
        bad("model", "a well-formed model id" + (LISTED if models is not None else "") + ", or \"unknown\"")
    if not _is(NAME_RE, line["adapter"]):
        bad("adapter", "an adapter's folder name")
    if line["kind"] not in KINDS:
        bad("kind", "full or partial")
    if not _is(TEST_ID_RE, line["test"]):
        bad("test", "a test id")
    if not _date(line["date"]):
        bad("date", "YYYY-MM-DD")
    if not _count(line["measurement_version"], 1):
        bad("measurement_version", "a whole number, 1 or more")
    if not _case_id(line["case"]):
        bad("case", "a case id")
    if line["variant"] not in VARIANT_NAMES:
        bad("variant", "with or without")
    if line["outcome"] not in OUTCOMES:
        bad("outcome", "graded or timeout")
    results = line["results"]
    if not (isinstance(results, list) and results and all(r in (0, 1) and not isinstance(r, bool) for r in results)):
        bad("results", "a list of 0 and 1, one per assertion")
        results = None
    if not _number(line["score"]):
        bad("score", "a number from 0 to 1")
    elif results and abs(line["score"] - sum(results) / len(results)) > 1e-9:
        out.append("score must be the share of results that are 1")
    if results and line["outcome"] == "timeout" and any(results):
        out.append("a timeout has score 0 and results all 0")
    if "cost_usd" in line and not (isinstance(line["cost_usd"], (int, float)) and not isinstance(line["cost_usd"], bool)
                                   and line["cost_usd"] >= 0):
        bad("cost_usd", "a number, 0 or more")
    if "run_sha256" in line and not _is(HEX64_RE, line["run_sha256"]):
        bad("run_sha256", "64 hexadecimal characters")
    if "platform" in line and not _is(NAME_RE, line["platform"]):
        bad("platform", "a platform name")
    elif "platform" in line and (line["kind"] != "partial" or line["variant"] != "with"):
        out.append("a line of a platform's case runs in a partial test, with the skill only")
    if "guard_failed" in line:
        failed = line["guard_failed"]
        if not (isinstance(failed, list) and failed and all(_count(v, 1) for v in failed) and len(set(failed)) == len(failed)
                and (results is None or all(v <= len(results) and results[v - 1] == 0 for v in failed))):
            bad("guard_failed", "a list of positions of assertions whose result is 0")
        elif line["variant"] != "with":
            out.append("guard_failed belongs to a with-skill run only")
    if event and not out:
        for key in ("skill", "test", "kind", "version", "content_sha256", "measurement_version", "measurement_sha256"):
            if line[key] != event.get(key):
                out.append(f"{key} differs from the event line of the file")
        pairs = event_model_pairs(event)
        if pairs and line["model"] not in {m for m, _ in pairs}:
            out.append("model is not one of the event's models")
        if pairs and line["adapter"] not in {a for _, a in pairs}:
            out.append("adapter is not one of the event's adapters")
        if isinstance(event.get("cases"), dict) and event["cases"].get(str(line["case"])) != line["case_sha256"]:
            out.append("case and case_sha256 are not a case of the event line")
    return out


def read_evidence_file(path):
    """(event line or None, run lines, problems) of one evidence file, each line parsed and not yet judged."""
    problems, lines = [], []
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read().split("\n")
    except (OSError, UnicodeDecodeError) as e:
        return None, [], [f"cannot be read: {e}"]
    if raw and raw[-1] == "":
        raw.pop()
    for n, text in enumerate(raw, 1):
        try:
            obj = json.loads(text)
        except ValueError:
            problems.append(f"line {n}: not valid JSON")
            continue
        if not isinstance(obj, dict):
            problems.append(f"line {n}: must be a JSON object")
            continue
        lines.append((n, obj))
    if not lines:
        return None, [], problems or ["the file is empty: an evidence file has an event line"]
    return lines[0][1], lines[1:], problems


def evidence_file_problems(path, root=None, skill=None, strict=None):
    """Why one lab evidence file is not valid; an empty list when it is. skill is the folder the file belongs
    to; by default it is read from a path .../skills/<name>/evals/evidence/<file>. The file is judged by its own
    event line (the module docstring, backlog T24); strict, {"models": ids, "runs": number} or None, is the
    strict reading of a file that is new against the base. root is accepted for the callers that pass it and is
    not read."""
    name = os.path.basename(path)
    parts = os.path.normpath(os.path.abspath(path)).split(os.sep)
    if skill is None and len(parts) >= 5 and parts[-3:-1] == ["evals", "evidence"] and parts[-5] == "skills":
        skill = parts[-4]
    m = re.fullmatch(r"lab-(" + TEST_ID_RE.pattern + r")\.jsonl", name)
    if not m:
        return [f"the name must be lab-<test id>.jsonl, not {name}"]
    event, runs, problems = read_evidence_file(path)
    if event is None:
        return problems
    models = set(strict["models"]) if strict else None
    first = event_line_problems(event, models)
    problems += [f"line 1: {p}" for p in first]
    if not first:
        if event["test"] != m.group(1):
            problems.append("line 1: test differs from the file's name")
        if skill is not None and event["skill"] != skill:
            problems.append(f"line 1: skill must be the folder's name, {skill}")
        if strict and event["runs"] != strict["runs"]:
            problems.append(f"line 1: runs is {event['runs']}, and the configured number is {strict['runs']} "
                            "(\"runs\" of evals/eval-gate.json): a new evidence file comes only from an event that used the "
                            "configured number; another number is a trial, and writes no evidence")
    for n, line in runs:
        problems += [f"line {n}: {p}" for p in run_line_problems(line, None if first else event, models)]
    if not first and not problems:
        problems += run_count_problems(event, [line for _, line in runs])
    return problems


def run_count_problems(event, runs):
    """Why the number of run lines of a case disagrees with the event's own "runs": a case has at most that many
    lines on one model and one adapter in one variant, with the skill or without it (a baseline never has more)."""
    out, seen = [], {}
    for line in runs:
        key = (str(line["case"]), line["model"], line["adapter"], line["variant"])
        seen[key] = seen.get(key, 0) + 1
    for (case, model, adapter, variant), n in sorted(seen.items()):
        if n > event["runs"]:
            out.append(f"case {case} has {n} lines {variant} the skill on {model} ({adapter}), more than the event's "
                       f"\"runs\", {event['runs']}")
    return out


def evidence_files(skill_dir):
    """The lab evidence files of a skill, oldest first (a test id starts with its time)."""
    folder = os.path.join(skill_dir, EVIDENCE_REL)
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.startswith("lab-") and n.endswith(".jsonl")]


def evidence_problems(root=ROOT, only=None, field_problems=None, strict_for=None):
    """({relative path: [problems]}, files checked) for the evidence folders of every skill, or of one. A file
    whose name is neither lab-<test id>.jsonl nor field-<id>.jsonl is a problem: nothing else belongs in that
    folder. field_problems(path, root, skill) judges a field-<id>.jsonl file, and strict_for(relative path)
    answers the `strict` argument of evidence_file_problems for a lab file (None: judge it by its own event
    line); both belong to eval_status.py, which passes them (without field_problems a field file is reported
    as unread)."""
    found, checked = {}, 0
    for name in [only] if only else skill_names(root):
        folder = os.path.join(root, "skills", name, EVIDENCE_REL)
        for entry in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            rel = os.path.relpath(os.path.join(folder, entry), root)
            checked += 1
            if entry.startswith("field-"):  # contributed field evidence (scripts/evidence.py import)
                if field_problems is None:
                    problems = ["a field evidence file is judged by eval_status.py, which passes its reader"]
                else:
                    problems = field_problems(os.path.join(folder, entry), root, name)
            else:
                problems = evidence_file_problems(os.path.join(folder, entry), root, name,
                                                  strict_for(rel) if strict_for else None)
            if problems:
                found[rel] = problems
    return found, checked


def main(argv):
    if any(a in ("-h", "--help") for a in argv) or not argv:
        print(__doc__)
        return 0
    print("This module is a library: run python3 evals/eval_status.py evidence to validate the evidence files.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
