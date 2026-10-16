#!/usr/bin/env python3
"""The closed forms of a lab evidence file and the reading of its lines.

This module holds how an evidence line is read and checked: the regular expressions and helpers the forms
need, the keys of an event line and of a run line, `event_line_problems`, `run_line_problems`, the reading
of one file, and the walk over the evidence folders. It holds none of the gate (the configuration, the
baseline, the comparison) and none of the score or the bands: those are in evals/eval_status.py, which imports
this file by path and re-exports every name below, so the status script behaves as before and keeps every
name its importers use. It is not a measurement file (it is not in FINGERPRINT_FILES of eval_status.py): a
change to it asks for no new measurement version. Standard library only; runs on Python 3.9.

An evidence file is judged by itself, and a new one strictly
-----------------------------------------------------------
(Backlog T24, removed on 2026-10-15; `git show bc830832:docs/backlog.md`.)
A committed evidence file is never edited, so it has to stay valid whatever the gate file says later. A file
already committed at the base of a change is therefore checked against what its own event line states, never
against today's gate file:

  1. "runs" is a whole number from RUNS_RANGE[0] to RUNS_RANGE[1] (the range the gate file's "runs" may take),
     and no case has more lines, on one model and one adapter, in one variant, than the event's "runs". A later
     change of "runs" in the gate file changes nothing here.
  2. A model id is valid when it is well formed (MODEL_RE) or the word "unknown". The ids an event line names
     are those of its "models", its "grader" and "unknown". The keys of its "counts", "upstream" and "local_model" must be among
     them. The "model" of a run line must be one of the event's "models" (the word "unknown" only when the
     header names it); a run line is not allowed to name the grader. A model removed from the gate file's
     "models" later keeps its old lines valid. A malformed id is always refused.

A file that is new against the base of the change (scripts/validate.py reads the base the class checks read;
the runner checks the file it is about to copy into a skill) is read strictly. A file that exists at the base
with other bytes than the base's is refused unread: committed evidence is never edited. With `strict`, a dict
{"models": the ids of the gate file's "models", "runs": the gate file's configured runs}: every model id of the
event line and of the run lines is in that list (or "unknown"), so that a private model name never enters the
repository, and the event's "runs" equals the configured number, so that a trial or a forged event cannot enter
as evidence. Without a base (not a git checkout) every file is judged by its own event line, as the class checks
of the validator are skipped there too. The optional `models` argument of `event_line_problems` and
`run_line_problems` is that same allowlist, for a caller that wants the strict reading of one line.

With `strict["lab"]`, {model id: its configured adapter or None} (eval_status.lab_pairs: the gate file's "lab_models" and
the adapter each one's entry names), a new file also needs every model of its header to be one of those, through that
adapter (D18): evidence of any other model, or of a lab model through another adapter, is a person's own and stays in
the local evidence folder.

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
new shape. It reads old events (the single gate of an old header is its strong tier's, `event_gates`); the band logic
of eval_status.py reads no tier.

The gate of an event line, in both shapes
-----------------------------------------
  Old (every committed file): "gate": {"passed", "with", "baseline", "threshold", "tolerance"[, "note"]}, the
  result of the event's strong tier, which `event_gates` reads as the gate of that tier's model.
  New (the model-keyed test event): "gate": {model id: that same object}, at least one key and each key a model
  of the event's "models". Only a header that is a list of models carries the keyed gate, and only the old header
  carries the single one, so that a gate always says whose it is. `event_gates(line)` returns {model id: gate} for
  either shape, so callers never branch on it. A model that has no gate in the event (no baseline of its own ran
  or was in force for it) has no key.

Completion, model by model
--------------------------
An event line may carry "complete_models": the models of its header (a list header only) whose runs in the event were
all graded, and whose baseline ran or was in force. The runner writes it on every new event. `event_complete_models(line)`
returns it, or, for a line without it, the event's "complete" read as its lead model's (an old event's strong tier, the
first model of a list header), so callers never branch. A complete event is complete for its lead model. A full test
counts in a model's selection (its newest full test, X.Y, Y count, stored gate: eval_status.py) only when it is complete
for that model; an abandoned event (not complete) keeps its lead model's lines, as it always did.

The usage of a run
------------------
A run line may carry "usage": {"input", "output", "cache_read", "cache_write"}, whole numbers of 0 or more, the
four kinds of tokens a run used (runtime/costs.py KINDS). Optional, and never a guess: it is written when the
run's tokens could be read (eval_run.py run_usage), otherwise the key is absent.

Community evidence (the plan's decision D19, package P10)
---------------------------------------------------------
A contributor runs the official reusable workflow (.github/workflows/community-eval.yml) in their fork; the workflow
attests the evidence file, and the contributor's pull request adds three files to the skill's evidence folder, named
after the fork's run: community-<repository id>-<run id>-<run attempt>.jsonl (the evidence), .manifest.json (what the
run was, attested with the file) and .sigstore.json (the attestation bundle). The event line of the evidence file
carries the closed marker "source": "community" (SOURCES); a lab file, and a person's local file, never carries it.
Everything else about the lines is the lab form (the list header, the run lines, the usage). A community file names
one model, its image is the published one, and a new file is read strictly: the model is one of the gate file's
listed models with a route (so that its key was held by a key proxy) and it ran through the adapter its entry names.
community_file_problems checks the shape and the agreement of the three files with one another without a network
call; the signature itself is verified by scripts/verify_community.py, in CI, on the pull request that adds the
files. The manifest is a closed form with no free text (MANIFEST_KEYS).

Usage (a library):
  python3 evals/evidence_lines.py --help        print this text
"""
import datetime
import hashlib
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
EVENT_OPTIONAL = ("gate", "upstream", "image_source", "complete_models", "source", "local_model")
# "local_model" describes, for each model of a local-model test (an id local/<name>@<12 hex of the weights' sha256>), what served
# it: {model id: {"weights_sha256", "file_type", "context", "accelerator", "server_image", "server_version",
# "server_args_sha256"}}, each value in a closed form. The file types are llama.cpp's llama_ftype names, as
# evals/local_models.py FILE_TYPES lists them (a test keeps the two equal), and "unknown".
LOCAL_MODEL_KEYS = ("weights_sha256", "file_type", "context", "accelerator", "server_image", "server_version", "server_args_sha256")
LOCAL_FILE_TYPES = (
    "ALL_F32", "MOSTLY_BF16", "MOSTLY_F16", "MOSTLY_IQ1_M", "MOSTLY_IQ1_S", "MOSTLY_IQ2_M", "MOSTLY_IQ2_S", "MOSTLY_IQ2_XS",
    "MOSTLY_IQ2_XXS", "MOSTLY_IQ3_M", "MOSTLY_IQ3_S", "MOSTLY_IQ3_XS", "MOSTLY_IQ3_XXS", "MOSTLY_IQ4_NL", "MOSTLY_IQ4_XS",
    "MOSTLY_MXFP4_MOE", "MOSTLY_NVFP4", "MOSTLY_Q1_0", "MOSTLY_Q2_0", "MOSTLY_Q2_K", "MOSTLY_Q2_K_S", "MOSTLY_Q3_K_L",
    "MOSTLY_Q3_K_M", "MOSTLY_Q3_K_S", "MOSTLY_Q4_0", "MOSTLY_Q4_1", "MOSTLY_Q4_K_M", "MOSTLY_Q4_K_S", "MOSTLY_Q5_0",
    "MOSTLY_Q5_1", "MOSTLY_Q5_K_M", "MOSTLY_Q5_K_S", "MOSTLY_Q6_K", "MOSTLY_Q8_0", "MOSTLY_TQ1_0", "MOSTLY_TQ2_0", "unknown")
LOCAL_ACCELERATORS = ("cpu", "cuda")
LOCAL_ID_RE = re.compile(r"local/[a-z0-9][a-z0-9._-]{0,63}@([0-9a-f]{12})")
RUN_REQUIRED = ("record", "skill", "version", "content_sha256", "model", "adapter", "kind", "test", "date",
                "measurement_version", "measurement_sha256", "case", "case_sha256", "variant", "outcome", "score", "results")
# "platform" names a social platform; "cpu_platform" the CPU platform the run's container ran on (linux/arm64, linux/amd64).
RUN_OPTIONAL = ("context_sha256", "platform", "guard_failed", "cost_usd", "run_sha256", "cpu_platform", "usage")
# "usage" is the tokens a run used by kind, whole numbers: the key proxy's count when the run went through one,
# otherwise the model usage of the run's raw output (eval_run.py run_usage). Optional: a run with no readable count has none.
USAGE_KEYS = ("input", "output", "cache_read", "cache_write")
IMAGE_SOURCES = ("published", "local")
CPU_PLATFORM_RE = re.compile(r"linux/[a-z0-9]+(/[a-z0-9]+)?")
GATE_KEYS = ("passed", "with", "baseline", "threshold", "tolerance")
SOURCES = ("community",)  # the closed list of the event line's "source" marker; absent in a lab file and in a local one
COMMUNITY_FILE_RE = re.compile(r"community-([0-9]{1,20})-([0-9]{1,20})-([0-9]{1,4})(\.jsonl|\.manifest\.json|\.sigstore\.json)")
# The manifest of a community run says what the run was. It is attested with the evidence file (one attestation, two
# subjects), so its values are the workflow's and not the contributor's. No free text: every value has a form below.
MANIFEST_KEYS = ("record", "repository", "repository_id", "run_id", "run_attempt", "run_number", "workflow", "commit",
                 "skill", "model", "evidence_sha256", "run_runner_group")
# "run_runner_group" is added by the attestation job, which reads this run attempt's jobs through the API and requires the
# `run` job to have run in the group of GitHub's own runners: the one proof, beside the attest job's own certificate, that
# the job that ran the model was not on a self-hosted runner. The pack step writes the manifest without it (partial).
RUNNER_GROUP = "GitHub Actions"
# The one file name a fork's caller workflow has; a manifest that names another is flagged (the run numbers of a
# workflow count per file, so one file per fork keeps the count whole).
CALLER_WORKFLOW = ".github/workflows/openhora-community.yml"
REPOSITORY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
WORKFLOW_PATH_RE = re.compile(r"\.github/workflows/[A-Za-z0-9._-]{1,100}\.ya?ml")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
BUNDLE_MAX_BYTES = 1_000_000


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


def _gate_ok(g):
    """True when g is one gate result: {"passed", "with", "baseline", "threshold", "tolerance"[, "note"]}."""
    return (isinstance(g, dict) and set(GATE_KEYS) <= set(g) and set(g) <= set(GATE_KEYS + ("note",))
            and isinstance(g["passed"], bool) and _number(g["with"]) and (g["baseline"] is None or _number(g["baseline"]))
            and _number(g["threshold"]) and _number(g["tolerance"]) and g.get("note", "baseline expired") == "baseline expired")


def event_gates(line):
    """{model id: gate} an event line carries, whichever shape its "gate" has: the keyed gate of a list header as it
    stands, the single gate of an old header as the gate of its strong tier's model. {} for a line with no gate or a
    malformed one (event_line_problems says why)."""
    g = line.get("gate") if isinstance(line, dict) else None
    if not isinstance(g, dict) or not g:
        return {}
    if isinstance(line.get("models"), list):
        return dict(g) if all(isinstance(k, str) and _gate_ok(v) for k, v in g.items()) else {}
    model = tier_model(line, "strong")
    return {model: g} if isinstance(model, str) and _gate_ok(g) else {}


def event_complete_models(line):
    """[model id] an event line says it is complete for: every run of the model in the event was graded (and, for a full
    test, its baseline ran or was in force). "complete_models" when the line has it (the list header's events write it);
    otherwise the event's own "complete" read as its lead model's: an old event's strong tier, a list header's first
    model. [] for an event that is not complete or whose header is malformed."""
    if not isinstance(line, dict):
        return []
    given = line.get("complete_models")
    if isinstance(given, list):
        return [m for m in given if isinstance(m, str)]
    pairs = event_model_pairs(line)
    return [pairs[0][0]] if pairs and line.get("complete") is True else []


def lead_model(line):
    """The model an event is a test of before any other: the first of its header (an old event's strong tier), or None."""
    pairs = event_model_pairs(line)
    return pairs[0][0] if pairs else None


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
    if "image_source" in line and line["image_source"] not in IMAGE_SOURCES:
        bad("image_source", "\"published\" (a pulled image, its digest the platform manifest's) or \"local\" (built here, its digest the image id)")
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
    if "complete_models" in line:
        done = line["complete_models"]
        ids = [m for m, _ in pairs]
        if not (isinstance(line["models"], list) and isinstance(done, list) and len(set(map(str, done))) == len(done)
                and all(isinstance(m, str) and (not ids or m in ids) for m in done)):
            bad("complete_models", "a list of distinct models of the event's models (a list header only): those whose "
                "runs in the event were all graded")
        elif line["complete"] is True and ids and ids[0] not in done:
            out.append("a complete event is complete for its lead model, the first of models: complete_models must hold it")
    if "gate" in line:
        g = line["gate"]
        keyed = isinstance(line["models"], list)  # a list header carries a gate for each model, an old one a single gate
        if line["kind"] != "full":
            out.append("gate belongs to a full test only: a partial test never evaluates the gate")
        elif keyed and not (isinstance(g, dict) and g and all(is_named(k) and (named is None or k in {m for m, _ in pairs})
                                                               and (not isinstance(line.get("complete_models"), list)
                                                                    or k in line["complete_models"])
                                                               and _gate_ok(v) for k, v in g.items())):
            bad("gate", "{model id of the event's models (and of complete_models, when the line has it): {\"passed\": bool, "
                "\"with\": mean, \"baseline\": mean or null, \"threshold\", \"tolerance\"[, \"note\": \"baseline expired\"]}}, "
                "at least one")
        elif not keyed and not _gate_ok(g):
            bad("gate", "{\"passed\": bool, \"with\": mean, \"baseline\": mean or null, \"threshold\", \"tolerance\"[, \"note\": \"baseline expired\"]}")
        elif line["complete"] is not True:
            out.append("gate is written by a complete full test only: an event closed as abandoned evaluates no gate")
    elif line["kind"] == "full" and line["complete"] is True:
        out.append("a complete full test carries its gate")
    if "source" in line and line["source"] not in SOURCES:
        bad("source", "\"community\" (the marker the community workflow's pack step writes; a lab or local file has none)")
    if "upstream" in line and not (isinstance(line["upstream"], dict) and all(
            is_named(k) and _is(TOOL_RE, v) for k, v in line["upstream"].items())):
        bad("upstream", "{model id the line names: the upstream provider the key proxy's route pins}")
    if "local_model" in line:
        local = line["local_model"]
        if not (isinstance(local, dict) and local and all(is_named(k) and _local_model_ok(k, v) for k, v in local.items())):
            bad("local_model", "{model id the line names, local/<name>@<12 hex>: {\"weights_sha256\": 64 hexadecimal characters the id starts "
                "with, \"file_type\": one of llama.cpp's file types or \"unknown\", \"context\": a whole number, \"accelerator\": cpu or "
                "cuda, \"server_image\": sha256:<64 hex>, \"server_version\": a version line, \"server_args_sha256\": 64 hexadecimal "
                "characters}}")
    return out


def _local_model_ok(model, value):
    """Whether one entry of an event line's "local_model" is in its closed form, and the model id is the local id of its weights."""
    m = LOCAL_ID_RE.fullmatch(model) if isinstance(model, str) else None
    return bool(m and isinstance(value, dict) and set(value) == set(LOCAL_MODEL_KEYS) and _is(HEX64_RE, value["weights_sha256"])
                and value["weights_sha256"].startswith(m.group(1)) and value["file_type"] in LOCAL_FILE_TYPES
                and _count(value["context"], 1) and value["accelerator"] in LOCAL_ACCELERATORS
                and _is(re.compile(r"sha256:[0-9a-f]{64}"), value["server_image"]) and _is(TOOL_RE, value["server_version"])
                and _is(HEX64_RE, value["server_args_sha256"]))


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
    if "usage" in line and not (isinstance(line["usage"], dict) and set(line["usage"]) == set(USAGE_KEYS)
                                and all(_count(v) for v in line["usage"].values())):
        bad("usage", "{" + ", ".join(f'"{k}"' for k in USAGE_KEYS) + "}: whole numbers of 0 or more, the tokens the run used by kind")
    if "run_sha256" in line and not _is(HEX64_RE, line["run_sha256"]):
        bad("run_sha256", "64 hexadecimal characters")
    if "cpu_platform" in line and not (isinstance(line["cpu_platform"], str) and CPU_PLATFORM_RE.fullmatch(line["cpu_platform"])):
        bad("cpu_platform", "the CPU platform the run's container ran on, such as linux/arm64 or linux/amd64")
    elif "cpu_platform" in line and event is not None and line["cpu_platform"] != event.get("image_platform"):
        out.append("cpu_platform must equal the image_platform of the event line: the run ran in that image")
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
    event line (the module docstring, backlog T24, removed on 2026-10-15; `git show bc830832:docs/backlog.md`);
    strict, {"models": ids, "runs": number} or None, is the
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
        for model, adapter in event_model_pairs(event) if strict and "lab" in strict else []:
            if model not in strict["lab"]:
                problems.append(f"line 1: {model} is not one of the gate file's lab models ({', '.join(sorted(strict['lab']))}): "
                                "evidence of any other model stays on the machine that made it (the local evidence folder), "
                                "never in the repository")
            elif strict["lab"][model] is not None and adapter != strict["lab"][model]:
                problems.append(f"line 1: {model} ran through the adapter {adapter}, and the one its entry in the gate file "
                                f"names is {strict['lab'][model]}: evidence in the repository is of the configured pair")
        if "source" in event:
            problems.append("line 1: source belongs to a community evidence file (community-<run id>.jsonl) only: a lab file, "
                            "and a person's local file, never carries it")
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


# --- community evidence (the module docstring) --------------------------------------------------------------

def community_ids(name):
    """(repository id, run id, run attempt, suffix) of a community file name, else None; the suffix is .jsonl,
    .manifest.json or .sigstore.json."""
    m = COMMUNITY_FILE_RE.fullmatch(name)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)) if m else None


def manifest_problems(manifest, partial=False):
    """Why a community manifest is outside its closed form (MANIFEST_KEYS); [] when it is valid. partial leaves out
    "run_runner_group", which the attestation job adds: only the pack step reads a manifest that way."""
    if not isinstance(manifest, dict):
        return ["must be a JSON object"]
    keys = tuple(k for k in MANIFEST_KEYS if not (partial and k == "run_runner_group"))
    out = _keys(manifest, keys, ())
    if out:
        return out
    bad = lambda key, form: out.append(f"{key} must be {form}")
    if manifest["record"] != "community-manifest":
        bad("record", "\"community-manifest\"")
    if not _is(REPOSITORY_RE, manifest["repository"]):
        bad("repository", "owner/name of the fork the run ran in")
    for key in ("repository_id", "run_id", "run_attempt", "run_number"):
        if not _count(manifest[key], 1):
            bad(key, "a whole number, 1 or more")
    if not _is(WORKFLOW_PATH_RE, manifest["workflow"]):
        bad("workflow", "the path of the caller's workflow file (.github/workflows/<file>.yml)")
    if not _is(COMMIT_RE, manifest["commit"]):
        bad("commit", "the 40 hexadecimal characters of the official workflow's commit")
    if not _is(NAME_RE, manifest["skill"]):
        bad("skill", "a skill name")
    if not (isinstance(manifest["model"], str) and _model(manifest["model"], None) and manifest["model"] != "unknown"):
        bad("model", "a well-formed model id")
    if not _is(HEX64_RE, manifest["evidence_sha256"]):
        bad("evidence_sha256", "64 hexadecimal characters")
    if not partial and manifest["run_runner_group"] != RUNNER_GROUP:
        bad("run_runner_group", f"\"{RUNNER_GROUP}\", the runner group of GitHub's own runners: the job that ran the model "
            "was not shown to be on one")
    return out


def bundle_problems(data):
    """Why the bytes of a .sigstore.json file cannot be an attestation bundle. The shape only: the signature is
    verified by scripts/verify_community.py with the GitHub CLI."""
    if len(data) > BUNDLE_MAX_BYTES:
        return [f"is larger than {BUNDLE_MAX_BYTES} bytes"]
    try:
        bundle = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ["is not JSON"]
    if not (isinstance(bundle, dict) and isinstance(bundle.get("mediaType"), str)
            and bundle["mediaType"].startswith("application/vnd.dev.sigstore.bundle") and "verificationMaterial" in bundle
            and ("dsseEnvelope" in bundle or "messageSignature" in bundle)):
        return ["is not a Sigstore bundle (mediaType, verificationMaterial and a signed envelope)"]
    return []


def community_companion_problems(path):
    """Why a .manifest.json or .sigstore.json file has no place in the folder: its evidence file is not there."""
    name = os.path.basename(path)
    ids = community_ids(name)
    stem = name[:-len(ids[3])] if ids else name
    if not os.path.isfile(os.path.join(os.path.dirname(path), stem + ".jsonl")):
        return [f"{stem}.jsonl is not in the folder: a manifest and a bundle belong to their evidence file"]
    return []


def community_file_problems(path, root=None, skill=None, strict=None):
    """Why one community evidence file is not valid (its manifest and bundle included); [] when it is. The shape of
    the three files and their agreement with one another, with no network call. skill is the folder the file belongs
    to (by default read from the path). strict, {"models": ids, "runs": number, "entries": {model id: its adapter}} or
    None, is the strict reading of a file that is new against the base: the model is one of "entries" (a listed model
    with a route) and ran through the adapter its entry names, the event's "runs" is the configured number. root is
    accepted for the callers that pass it and is not read."""
    name = os.path.basename(path)
    parts = os.path.normpath(os.path.abspath(path)).split(os.sep)
    if skill is None and len(parts) >= 5 and parts[-3:-1] == ["evals", "evidence"] and parts[-5] == "skills":
        skill = parts[-4]
    ids = community_ids(name)
    if not ids or ids[3] != ".jsonl":
        return [f"the name must be community-<repository id>-<run id>-<run attempt>.jsonl, not {name}"]
    stem, folder = name[:-len(".jsonl")], os.path.dirname(path)
    problems = []
    for suffix in (".jsonl", ".manifest.json", ".sigstore.json"):
        if os.path.islink(os.path.join(folder, stem + suffix)):
            return [f"{stem}{suffix} is a link: a community file is a plain file (a link could read what is not evidence)"]
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return [f"cannot be read: {e}"]
    manifest = None
    try:
        with open(os.path.join(folder, stem + ".manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    except OSError:
        problems.append(f"{stem}.manifest.json is missing: the manifest is what the attestation covers beside the file")
    except ValueError:
        problems.append(f"{stem}.manifest.json is not valid JSON")
    if manifest is not None:
        found = manifest_problems(manifest)
        problems += [f"manifest: {p}" for p in found]
        if not found:
            if (manifest["repository_id"], manifest["run_id"], manifest["run_attempt"]) != ids[:3]:
                problems.append("manifest: repository_id, run_id and run_attempt are not the ones the file's name carries")
            if manifest["evidence_sha256"] != hashlib.sha256(data).hexdigest():
                problems.append("manifest: evidence_sha256 is not the sha256 of the file")
            if skill is not None and manifest["skill"] != skill:
                problems.append(f"manifest: skill must be the folder's name, {skill}")
    try:
        with open(os.path.join(folder, stem + ".sigstore.json"), "rb") as f:
            problems += [f"bundle: {p}" for p in bundle_problems(f.read())]
    except OSError:
        problems.append(f"{stem}.sigstore.json is missing: a community file is evidence only with its attestation bundle")
    event, runs, read = read_evidence_file(path)
    problems += read
    if event is None:
        return problems
    models = set(strict["models"]) if strict else None
    first = event_line_problems(event, models)
    problems += [f"line 1: {p}" for p in first]
    if not first:
        if event.get("source") != "community":
            problems.append("line 1: source must be \"community\" in a community evidence file")
        if skill is not None and event["skill"] != skill:
            problems.append(f"line 1: skill must be the folder's name, {skill}")
        if event.get("image_source") != "published":
            problems.append("line 1: image_source must be \"published\": a community run uses the published eval image, "
                            "pulled by the digest of the lock file")
        pairs = event_model_pairs(event)
        if len(pairs) != 1:
            problems.append("line 1: a community file tests one model: models must name exactly one")
        elif isinstance(manifest, dict) and not manifest_problems(manifest) and pairs[0][0] != manifest["model"]:
            problems.append("line 1: the model is not the one the manifest names")
        elif strict and "entries" in strict:
            model, adapter = pairs[0]
            if model not in strict["entries"]:
                problems.append(f"line 1: {model} is not a model of the gate file with a route: a community run tests a listed "
                                "model whose key a key proxy held (a pull request adds the model to the gate file first)")
            elif strict["entries"][model] != adapter:
                problems.append(f"line 1: {model} ran through the adapter {adapter}, and the one its entry in the gate file "
                                f"names is {strict['entries'][model]}")
        if strict and event["runs"] != strict["runs"]:
            problems.append(f"line 1: runs is {event['runs']}, and the configured number is {strict['runs']} "
                            "(\"runs\" of evals/eval-gate.json)")
    for n, line in runs:
        found = run_line_problems(line, None if first else event, models)
        problems += [f"line {n}: {p}" for p in found]
        if not found and isinstance(manifest, dict) and not manifest_problems(manifest) and line["model"] != manifest["model"]:
            problems.append(f"line {n}: model is not the one the manifest names")
    if not first and not problems:
        problems += run_count_problems(event, [line for _, line in runs])
    return problems


def evidence_files(skill_dir):
    """The lab evidence files of a skill, oldest first (a test id starts with its time)."""
    folder = os.path.join(skill_dir, EVIDENCE_REL)
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.startswith("lab-") and n.endswith(".jsonl")]


def evidence_problems(root=ROOT, only=None, field_problems=None, strict_for=None, community_problems=None,
                      community_for=None):
    """({relative path: [problems]}, files checked) for the evidence folders of every skill, or of one. A file
    whose name is neither lab-<test id>.jsonl, field-<id>.jsonl nor one of the three files of a community run
    (community-<repository id>-<run id>-<attempt>.jsonl, .manifest.json, .sigstore.json) is a problem: nothing else
    belongs in that folder. field_problems(path, root, skill) judges a field-<id>.jsonl file, and strict_for(relative
    path) answers, for a lab file, the `strict` argument of evidence_file_problems (None: judge it by its own event
    line), or a text, in which case the file is refused with that text and not read; both belong to
    eval_status.py, which passes them (without field_problems a field file is reported as unread).
    community_problems(path, root, skill, strict) judges a community .jsonl file and community_for(relative path)
    answers, for any of the three files, the `strict` argument of community_file_problems or a text (a file
    that is edited), as strict_for does for a lab file."""
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
            elif entry.startswith("community-"):  # contributed community evidence (scripts/verify_community.py)
                ids = community_ids(entry)
                reading = community_for(rel) if community_for else None
                if ids is None:
                    problems = [f"the name must be community-<repository id>-<run id>-<run attempt>.jsonl, .manifest.json "
                                f"or .sigstore.json, not {entry}"]
                elif isinstance(reading, str):
                    problems = [reading]
                elif ids[3] != ".jsonl":
                    problems = community_companion_problems(os.path.join(folder, entry))
                elif community_problems is None:
                    problems = ["a community evidence file is judged by eval_status.py, which passes its reader"]
                else:
                    problems = community_problems(os.path.join(folder, entry), root, name, reading)
            else:
                reading = strict_for(rel) if strict_for else None
                problems = ([reading] if isinstance(reading, str)
                            else evidence_file_problems(os.path.join(folder, entry), root, name, reading))
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
