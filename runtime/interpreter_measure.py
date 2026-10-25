#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The measurement harness of the interpreter experiment (package IX-2c, plan `PLAN-NL-INTERPRETER-FINAL.md`): runs a corpus through the B-prime arm (runtime/interpreter_pipeline.py)
on one route, scores every run with the taxonomy's rules (runtime/interpreter_score.py) and writes the evidence file IX-E reads (runtime/interpreter_evidence.py).

    interpreter_measure.py --corpus FILE --route ID [--runs N] [--jobs N] [--sample N --seed S] [--sequential]
                           [--record DIR | --resume DIR | --replay DIR [--golds FILE]] [--evidence-dir DIR | --no-evidence] [--json]
    interpreter_measure.py --corpus FILE --route ID --local-aggregates [--evidence-dir DIR]

  --route         an id of runtime/interpreter_routes.json; --runs defaults to `runs` of evals/interpreter/thresholds.json; --jobs (default 4) calls at once
  --sample N --seed S   the first N items by sha256("<S>:<id>") order, in id order. With --sequential only items that reach the model are drawn (stages 0 to 3 are pure code,
                  run first for the whole corpus), so that every line of a sequential event is a call; --sequential alone runs every such item; it forces --jobs 1 and writes
                  `sequential: true` (latency and cost are read from those events)
  --record DIR    keep the model's raw answers in DIR/<test>.answers.jsonl, one line per call, as they arrive (the prompt is never written). --resume DIR continues the
                  matching file of DIR: it re-reads the pairs present, calls only the missing ones and writes the complete event. --replay DIR reads one answers file
                  whose header hashes equal this checkout's, makes NO call and writes no evidence: a regression check of the code, not a measurement
  --golds FILE    only with --replay: a labelled re-score. --corpus stays the file the answers were recorded on (the header check is unchanged); FILE must hold the same ids and,
                  for each, every key but `gold` and `also` equal to the corpus item, and the runs are scored with FILE's `gold` and `also`. The summary says `rescore: true` and
                  names the file and its sha256; nothing is ever written: a re-score is not a measurement and is no evidence
  --local-aggregates   the maintainer's own labelled lines (split local, ids local-NNNNN): one run, counts per language only; prints no id and no line
  Test split: the corpus bytes must hash to evals/interpreter/test-split.json, --runs must be the configured number, --sample needs --sequential, and one of --record, --resume
                  or --replay is required with a directory outside this checkout, so that the model's answers to held-out lines stay out of the repository until the split is committed.

The evidence file is written once, at the end, only when every (item, run) has a line, with an exclusive create. Standard output and standard error carry counts, categories, ids
(dev and test only) and E_ codes: never a line, a span, a frame, a model's answer or an exception message. Exit 0 done, 1 refused input or a fault, 2 usage.
Items of gold scope `time` write no line: they are scored by the time rule alone and printed as a count table.

Python 3.9, standard library only.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import interpreter  # noqa: E402  (the same folder)
import interpreter_evidence as evidence  # noqa: E402
import interpreter_pipeline as pipeline  # noqa: E402
import interpreter_route  # noqa: E402  (a call is `interpreter_route.complete`, looked up at the call: a replay never reaches it)
import interpreter_score as score  # noqa: E402
import prices  # noqa: E402

ROOT = os.path.dirname(HERE)
SPLIT_FILE = evidence.SPLIT_FILE
THRESHOLDS_FILE = score.THRESHOLDS_FILE
DEFAULT_JOBS = 4
CONFIG_FAULTS = ("E_KEY", "E_ROUTE", "E_USAGE")          # a call that fails like this fails every call: the run stops at once and spends nothing more
FIRST_CALL_FAULTS = ("E_HTTP",)          # a 401, 402 or 403 (a revoked key, no credits, forbidden) comes back as E_HTTP: when it is the first call's answer it is a configuration fault too
TRANSIENT = ("E_RATE", "E_TIMEOUT", "E_NETWORK", "E_UPSTREAM")          # a resume calls these again instead of serving them from the record
OUTAGE_MAX = 0.01          # more failed calls than this share of the calls and no evidence is written: the run is resumed, not published
ID_RE = re.compile(r"(dev|test)-(pt-br|en|es|fr|de|it|ja|mx)-[0-9]{5}")
LOCAL_RE = re.compile(r"local-[0-9]{5}")
ANSWERS_SUFFIX = ".answers.jsonl"


class Refused(Exception):
    """A refused input or a fault: the message holds fixed words, counts, ordinals and codes only (exit 1)."""


class Usage(Exception):
    """A combination of options that is not allowed (exit 2)."""


class ItemFault(Exception):
    def __init__(self, name: str, ordinal: int):
        super().__init__(name)
        self.name, self.ordinal = name, ordinal


class ConfigFault(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- the corpus -------------------------------------------------------------------------------------------------------------------------------------------

def load_corpus(path: str) -> tuple:
    """(items, bytes): the corpus file read and checked. Every fault names a line number and a field, never a value."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        raise Refused("the corpus file cannot be read") from None
    items, seen = [], set()
    for n, raw in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except ValueError:
            raise Refused(f"corpus line {n} is not JSON") from None
        problems = pipeline.item_problems(item)
        if problems:
            raise Refused(f"corpus line {n}: not in the form of the corpus ({', '.join(problems)})")
        if item["id"] in seen:
            raise Refused(f"corpus line {n}: an id appears twice")
        seen.add(item["id"])
        items.append(item)
    if not items:
        raise Refused("the corpus holds no item")
    return items, data


def split_of(items: list, local: bool) -> str:
    """"dev", "test" or "local": the one split every item states and whose id form every id has."""
    splits = {item["split"] for item in items}
    if len(splits) != 1 or next(iter(splits)) not in ("dev", "test", "local"):
        raise Refused("the corpus holds items of more than one split, or of an unknown one")
    split = next(iter(splits))
    for n, item in enumerate(items, 1):
        found = LOCAL_RE.fullmatch(item["id"]) if split == "local" else ID_RE.fullmatch(item["id"])
        if not found or (split != "local" and not item["id"].startswith(split + "-")):
            raise Refused(f"corpus item {n}: the id is not of the form of its split")
    if (split == "local") != local:
        raise Refused("local lines are measured with --local-aggregates, and only they")
    return split


def thresholds() -> dict:
    with open(THRESHOLDS_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def draw(items: list, n: int, seed: str, sequential: bool) -> list:
    """The first `n` items by sha256("<seed>:<id>") order, in id order. For a sequential event the pool is the items that reach the model (and write a line)."""
    pool = [i for i in items if not sequential or (i["gold"].get("scope", "full") != "time" and pipeline.pre_model(i) is None)]
    if not pool:
        raise Refused("no item of the corpus reaches the model")
    if sequential and n is None:
        return sorted(pool, key=lambda i: i["id"])
    if n > len(pool):
        raise Refused(f"the sample asks for {n} items and the pool holds {len(pool)}")
    ordered = sorted(pool, key=lambda i: hashlib.sha256(f"{seed}:{i['id']}".encode("utf-8")).hexdigest())
    return sorted(ordered[:n], key=lambda i: i["id"])


def load_golds(path: str, items: list) -> tuple:
    """(the corpus items with the gold and the also of the golds file, the sha256 of that file's bytes). The file holds exactly the corpus's ids and, per id, every key but
    `gold` and `also` equal to the corpus item; a fault names the first id and key, never a value."""
    other, data = load_corpus(path)
    mine, theirs = {i["id"]: i for i in items}, {i["id"]: i for i in other}
    for item_id in sorted(set(mine) | set(theirs)):
        if item_id not in theirs:
            raise Refused(f"the golds file lacks item {item_id}")
        if item_id not in mine:
            raise Refused(f"the golds file holds item {item_id}, which the corpus lacks")
        for key in sorted((set(mine[item_id]) | set(theirs[item_id])) - {"gold", "also"}):
            if mine[item_id].get(key) != theirs[item_id].get(key) or (key in mine[item_id]) != (key in theirs[item_id]):
                raise Refused(f"the golds file differs from the corpus at item {item_id} in {key}")
    widened = [dict(i, gold=theirs[i["id"]]["gold"], also=theirs[i["id"]]["also"]) for i in items]
    return widened, hashlib.sha256(data).hexdigest()


# --- the answers (record, resume, replay) -----------------------------------------------------------------------------------------------------------------

def header_of(test: str, route: dict, corpus: str, runs: int, sequential: bool, sample) -> dict:
    h = evidence.hashes(route)
    return {"record": "answers", "v": 1, "test": test, "route": route["id"], "route_sha256": h["route_sha256"], "prompt_sha256": h["prompt_sha256"],
            "catalog_sha256": h["catalog_sha256"], "protocol_sha256": h["protocol_sha256"], "corpus_sha256": corpus, "runs": runs, "sequential": sequential, "sample": sample}


HASH_FIELDS = ("route", "route_sha256", "prompt_sha256", "catalog_sha256", "protocol_sha256", "corpus_sha256")


def read_answers(path: str, repair: bool = False) -> tuple:
    """(header, {(item id, run): record}). A last line that an interruption cut short is left out; with `repair` it is removed from the file too, before it is appended to."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        raise Refused("the answers file cannot be read") from None
    if data and not data.endswith(b"\n"):          # a last line that an interruption cut short is not an answer
        data = data[:data.rfind(b"\n") + 1]
        if repair:
            with open(path, "wb") as handle:
                handle.write(data)
    header, found = None, {}
    for n, raw in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        try:
            line = json.loads(raw)
        except ValueError:
            raise Refused(f"answers line {n} is not JSON") from None
        if n == 1:
            if not isinstance(line, dict) or line.get("record") != "answers" or line.get("v") != 1:
                raise Refused("the answers file does not start with its header")
            header = line
        elif isinstance(line, dict) and isinstance(line.get("item"), str) and isinstance(line.get("run"), int) and isinstance(line.get("ok"), bool):
            found[(line["item"], line["run"])] = line
        else:
            raise Refused(f"answers line {n} is not an answer")
    if header is None:
        raise Refused("the answers file is empty")
    return header, found


def differing(header: dict, wanted: dict) -> str:
    return next((key for key in HASH_FIELDS if header.get(key) != wanted.get(key)), "")


def outside_checkout(directory: str) -> bool:
    top = os.path.realpath(ROOT)
    here = os.path.realpath(directory)
    return not (here == top or here.startswith(top + os.sep))


class Answers:
    """The answers of the calls of one run: the recorded ones are served first; a pair not recorded is called (live) or refused (replay), and what a call returned is
    appended to the file as it arrives."""

    def __init__(self, mode: str, header: dict, found: dict, path, retry: bool = False):
        self.mode, self.header, self.found, self.path = mode, header, dict(found), path
        self.redo = {k for k, r in found.items() if retry and not r["ok"] and r.get("code") in TRANSIENT}          # the pairs a resume calls again
        self.fault_code = None          # set by the first configuration fault: no thread calls after it
        self.lock, self.live_calls, self.handle = threading.Lock(), 0, None
        self.first, self.started = threading.Lock(), False          # the first call is made alone: the route's first use loads the secret resolver, which is not meant to be loaded twice at once
        if path is not None:
            fresh = not os.path.exists(path)
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | (os.O_EXCL if fresh else 0)
            self.handle = os.fdopen(os.open(path, flags, 0o600), "a", encoding="utf-8", newline="\n")
            if fresh:
                self.handle.write(evidence.dumps(header) + "\n")
                self.handle.flush()

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()

    def get(self, item_id: str, run: int):
        return self.found.get((item_id, run))

    def add(self, record: dict) -> None:
        with self.lock:
            self.found[(record["item"], record["run"])] = record
            self.redo.discard((record["item"], record["run"]))
            if self.handle is not None:
                self.handle.write(evidence.dumps(record) + "\n")
                self.handle.flush()


def _result_of(record: dict) -> dict:
    if record["ok"]:
        return {"ok": True, "text": record.get("text"), "finish": record.get("finish"), "usage": record.get("usage"), "latency_ms": record.get("latency_ms"),
                "upstream": record.get("upstream")}
    return {"ok": False, "code": record.get("code"), "latency_ms": record.get("latency_ms")}


def billing_of(route: dict) -> str:
    """How a route's calls are billed, from its kind: "subscription" for an account route (the maintainer's own account), else "metered"."""
    return "subscription" if route.get("kind") == "account" else "metered"


def _complete(route: dict, accepted: list, params: dict, system: str, user: str) -> dict:
    return interpreter_route.complete(route["id"], system, user, accepted=accepted, deadline_ms=interpreter.PROTOCOL["deadline_ms"], temperature=params["temperature"],
                                      max_tokens=params["max_tokens"], reasoning=params["reasoning"])


def make_call(answers: Answers, route: dict, item_id: str, run: int):
    """The `call(system, user)` of one (item, run): a recorded answer when there is one, else (live) the route's call, timed on the wall clock (what a person waits)."""
    accepted = [interpreter_route.route_sha256(route)]
    params = interpreter.PROTOCOL["params"]

    def call(system: str, user: str) -> dict:
        have = answers.get(item_id, run)
        if have is not None and (item_id, run) not in answers.redo:
            return _result_of(have)
        if answers.mode == "replay":
            raise Refused("the answers file lacks a call this run needs")
        if answers.fault_code:
            raise ConfigFault(answers.fault_code)
        started = time.monotonic()
        with (contextlib.nullcontext() if answers.started else answers.first):          # the first call alone, and checked again once the gate is ours
            if answers.fault_code:
                raise ConfigFault(answers.fault_code)
            first = not answers.started
            got = _complete(route, accepted, params, system, user)
            code = got.get("code")
            if not got.get("ok") and (code in CONFIG_FAULTS or (first and code in FIRST_CALL_FAULTS)):
                answers.fault_code = code
                raise ConfigFault(code)
            answers.started = True
        wall = int(round((time.monotonic() - started) * 1000))
        with answers.lock:
            answers.live_calls += 1
        record = {"item": item_id, "run": run, "ok": bool(got.get("ok")), "text": got.get("text") if got.get("ok") else None,
                  "code": None if got.get("ok") else got.get("code"), "finish": got.get("finish") if got.get("ok") else None,
                  "usage": got.get("usage") if got.get("ok") else None, "latency_ms": wall, "upstream": got.get("upstream") if got.get("ok") else None}
        answers.add(record)
        return _result_of(record)
    return call


# --- the run ----------------------------------------------------------------------------------------------------------------------------------------------

def run_all(items: list, runs: int, jobs: int, answers: Answers, route: dict) -> dict:
    """{(ordinal, run): Outcome} for every (item, run). A fault inside an item stops the run and is named by its ordinal and the exception's class."""
    stop = threading.Event()

    def one(ordinal: int, item: dict, run: int):
        if stop.is_set():
            return None
        try:
            return pipeline.run_item(item, run, make_call(answers, route, item["id"], run))
        except (ConfigFault, Refused):
            stop.set()
            raise
        except BaseException as e:          # noqa: BLE001 - named by class and ordinal, never by message
            stop.set()
            raise ItemFault(type(e).__name__, ordinal) from None

    done = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(one, n, item, run): (n, run) for n, item in enumerate(items, 1) for run in range(1, runs + 1)}
        try:
            for future in concurrent.futures.as_completed(futures):
                done[futures[future]] = future.result()
        except BaseException:
            stop.set()
            for future in futures:
                future.cancel()
            raise
    return done


def score_runs(items: list, runs: int, done: dict, route=None, table=None) -> tuple:
    """(rows of the scored runs, the time-scope results, the lines' inputs [(item, run, outcome, category)])."""
    rows, time_rows, scored = [], [], []
    for n, item in enumerate(items, 1):
        gold, also = item["gold"], item["also"]
        scope = gold.get("scope", "full")
        for run in range(1, runs + 1):
            outcome = done[(n, run)]
            if scope == "time":
                time_rows.append(score.time_result(gold, also, outcome["observed"], outcome["detail"]))
                continue
            category = score.categorize(gold, also, scope, outcome["observed"], outcome["detail"])
            call = outcome["call"]
            usage = call["usage"] if call else None
            rows.append({"item": item["id"], "run": run, "lang": item["lang"], "gold": gold["outcome"], "category": category, "observed": outcome["observed"],
                         "parse": outcome["parse"], "called": call is not None, "latency_ms": call["latency_ms"] if call else None, "usage": usage,
                         "error": outcome["error"], "stage": outcome["stage"], "why": outcome["why"], "time_disagree": outcome["time_disagree"],
                         "cost_usd": evidence.cost_usd(usage, route, table)})
            scored.append((item, run, outcome, category))
    return rows, time_rows, scored


# --- reports ----------------------------------------------------------------------------------------------------------------------------------------------

def text_report(result: dict, head: dict) -> str:
    m = result["measures"]
    lines = [" ".join(f"{k} {v}" for k, v in head.items() if v is not None),
             f"items {result['items']}, runs {result['runs']}, calls {result['calls']}",
             "categories (the worst run of each item): " + ", ".join(f"{c} {m['counts'][c]}" for c in score.SEVERITY if m["counts"][c])]

    def pct(value):
        return "n/a" if value is None else f"{value:.4f}"
    lines.append(f"correct_direct {pct(m['correct_direct'])}, clarify_rate {pct(m['clarify_rate'])}, parse_failure_rate {pct(result['parse_failure_rate'])}, "
                 f"p95_latency_ms {result['p95_latency_ms']}, median_cost_usd {result['median_cost_usd']}, wrong_route_cost_usd {result['wrong_route_cost_usd']:.4f}")
    lines.append("wilson upper bounds: " + ", ".join(f"{c} {pct(m['wilson'][c])}" for c in score.WRONG))
    for lang, lm in result["by_language"].items():
        lines.append(f"  {lang}: n {lm['n']}, correct_direct {pct(lm['correct_direct'])}, clarify_rate {pct(lm['clarify_rate'])}, "
                     + ", ".join(f"{c} {lm['counts'][c]}" for c in score.WRONG))
    lines.append("stages " + json.dumps(result["stages"]) + "; observed " + json.dumps(result["observed"]))
    lines.append(f"time_disagree {result['time_disagree']}, private-route {result['private_route']}, errors {json.dumps(result['errors'])}, scope time {json.dumps(result['scope_time'])}")
    return "\n".join(lines)


# --- the commands ----------------------------------------------------------------------------------------------------------------------------------------

def arguments(argv):
    p = argparse.ArgumentParser(prog=os.path.basename(__file__), description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--corpus", required=True)
    p.add_argument("--route", required=True)
    p.add_argument("--runs", type=int)
    p.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    p.add_argument("--sample", type=int)
    p.add_argument("--seed")
    p.add_argument("--sequential", action="store_true")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--record")
    mode.add_argument("--resume")
    mode.add_argument("--replay")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--evidence-dir")
    where.add_argument("--no-evidence", action="store_true")
    p.add_argument("--golds", help="with --replay: score the recorded answers with the gold and also of this file (a labelled re-score, never evidence)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--local-aggregates", action="store_true")
    return p.parse_args(argv)


def measure(args) -> int:
    th = thresholds()
    if args.sample is not None and not args.seed:
        raise Usage("--sample needs --seed")
    if args.jobs < 1 or (args.runs is not None and not 1 <= args.runs <= 10) or (args.sample is not None and args.sample < 1):
        raise Usage("--jobs and --sample are whole numbers from 1, --runs from 1 to 10")
    if args.local_aggregates and (args.record or args.resume or args.replay or args.sample is not None or args.sequential):
        raise Usage("--local-aggregates refuses --record, --resume, --replay, --sample and --sequential")
    if args.golds and not args.replay:
        raise Usage("--golds is a re-score of recorded answers: it needs --replay")
    if args.replay and (args.evidence_dir or args.record or args.resume):
        raise Usage("--replay writes no evidence and keeps no answers")
    try:
        route = interpreter_route.find(args.route)
    except interpreter_route.RouteError:
        raise Refused("no such route in runtime/interpreter_routes.json") from None
    items, data = load_corpus(args.corpus)
    split = split_of(items, args.local_aggregates)
    runs = 1 if split == "local" else (args.runs if args.runs is not None else th["runs"])
    if split == "local" and args.runs not in (None, 1):
        raise Usage("local lines run once")
    modes = [m for m in ("record", "resume", "replay") if getattr(args, m)]
    directory = getattr(args, modes[0]) if modes else None
    if split == "test":
        try:
            with open(SPLIT_FILE, encoding="utf-8") as handle:
                declared = json.load(handle)["sha256"]
        except (OSError, ValueError, KeyError, TypeError):
            raise Refused("evals/interpreter/test-split.json cannot be read") from None
        if hashlib.sha256(data).hexdigest() != declared:
            raise Refused("the corpus is not the test split (its hash differs from test-split.json)")
        if runs != th["runs"]:
            raise Refused(f"the test split is run {th['runs']} times (thresholds.json), not {runs}")
        if args.sample is not None and not args.sequential:
            raise Refused("a sample of the test split is never a band: --sample needs --sequential")
        if not modes:
            raise Refused("the test split needs --record, --resume or --replay with a directory outside this checkout")
        if not outside_checkout(directory):
            raise Refused("the answers directory is inside this checkout: the model's answers to held-out lines stay outside it")
    chosen = draw(items, args.sample, args.seed, args.sequential) if (args.sample is not None or args.sequential) else items
    jobs = 1 if args.sequential else args.jobs
    corpus = evidence.corpus_sha256(split, args.corpus, SPLIT_FILE)
    sample = {"n": args.sample, "seed": args.seed} if args.sample is not None else None
    # the answers
    test, found, path, mode = evidence.new_test_id(), {}, None, "live"
    if directory is not None:
        wanted = header_of("", route, corpus, runs, args.sequential, sample)
        if args.replay:
            files = sorted(f for f in os.listdir(directory) if f.endswith(ANSWERS_SUFFIX)) if os.path.isdir(directory) else []
            if len(files) != 1:
                raise Refused("the replay directory holds exactly one answers file")
            header, found = read_answers(os.path.join(directory, files[0]))
            bad = differing(header, wanted)
            if bad:
                raise Refused(f"the answers file differs from this checkout in {bad}")
            mode = "replay"
        else:
            os.makedirs(directory, exist_ok=True)
            mode = "live"
            if args.resume:
                for f in sorted((f for f in os.listdir(directory) if f.endswith(ANSWERS_SUFFIX)), reverse=True):
                    header, found = read_answers(os.path.join(directory, f))
                    if not differing(header, wanted) and all(header.get(k) == wanted.get(k) for k in ("runs", "sequential", "sample")):
                        test, path = header["test"], os.path.join(directory, f)
                        header, found = read_answers(path, repair=True)
                        break
                    found = {}
            if path is None:
                path = os.path.join(directory, test + ANSWERS_SUFFIX)
    answers = Answers(mode, header_of(test, route, corpus, runs, args.sequential, sample), found, path, retry=bool(args.resume))
    try:
        done = run_all(chosen, runs, jobs, answers, route)
    finally:
        answers.close()
    table = prices.load()
    metered = mode != "replay"          # a replay is not metered: no cost, no evidence
    golds_sha = None
    if args.golds:
        graded, golds_sha = load_golds(args.golds, items)
        by_id = {i["id"]: i for i in graded}
        chosen = [by_id[i["id"]] for i in chosen]          # the pipeline ran on the corpus's items; only the scoring below reads the golds file's gold and also
    rows, time_rows, scored = score_runs(chosen, runs, done, route if metered else None, table)
    head = {"route": route["id"], "test": test, "split": split, "mode": mode, "sequential": "yes" if args.sequential else None}
    if metered and (split == "local" or not args.no_evidence):
        failed, called = sum(1 for _, _, o, _ in scored if o["observed"] == "outage"), sum(1 for _, _, o, _ in scored if o["call"] is not None)
        if called and failed / called > OUTAGE_MAX:
            codes = score._count(o["error"] for _, _, o, _ in scored if o["observed"] == "outage")
            raise Refused(f"{failed} of {called} calls failed ({json.dumps(codes)}), over {OUTAGE_MAX:.0%}: no evidence was written; "
                          + (f"run the same command with --resume: it calls again the pairs recorded as {', '.join(TRANSIENT)}; any other recorded failure is kept and keeps blocking evidence"
                             if path else "keep the answers with --record to be able to resume"))
    if split == "local":
        return local_report(args, route, test, chosen, rows, items)
    result = score.summary(rows, th, sequential=args.sequential, time_rows=time_rows, extra={"live_calls": answers.live_calls, "route": route["id"], "test": test})
    written = None
    if metered and not args.no_evidence:
        folder = args.evidence_dir or evidence.EVIDENCE_DIR
        os.makedirs(folder, exist_ok=True)
        event = evidence.event_line(arm="bprime", split=split, test=test, date=evidence.utc_date(), route=route, runs=runs, items=len(items),
                                    sequential=args.sequential, billing=billing_of(route), corpus=corpus)
        lines = [event] + [evidence.item_line(test, item, run, outcome, category, route, table)
                           for item, run, outcome, category in sorted(scored, key=lambda t: (t[0]["id"], t[1]))]
        written = os.path.join(folder, f"ix-{test}.jsonl")
        try:
            evidence.write_exclusive(written, lines)
        except FileExistsError:
            raise Refused("the evidence file exists and is never overwritten") from None
    if args.golds:
        result.update({"golds_file": os.path.basename(args.golds), "golds_sha256": golds_sha, "rescore": True})
    if args.json:
        print(json.dumps(result, indent=1, sort_keys=True))
    else:
        if args.golds:
            print(f"re-score with golds {os.path.basename(args.golds)}: not a measurement, no evidence")
        print(text_report(result, head))
    print(f"evidence: {'not written' if written is None else 'written'}; answers: {'kept' if path else 'not kept'}", file=sys.stderr)
    return 0


def local_report(args, route: dict, test: str, chosen: list, rows: list, items: list) -> int:
    """The maintainer's own lines: the worst category of each item counted per language, written as aggregates; only counts are printed."""
    th = thresholds()
    worst = score.worst_of_runs(rows)
    by_lang = {}
    for item in chosen:
        if item["id"] in worst:
            by_lang.setdefault(item["lang"], []).append(worst[item["id"]])
    folder = args.evidence_dir or evidence.EVIDENCE_DIR
    os.makedirs(folder, exist_ok=True)
    event = evidence.event_line(arm="bprime", split="local", test=test, date=evidence.utc_date(), route=route, runs=1, items=len(items), sequential=False,
                                billing=billing_of(route), corpus=evidence.corpus_sha256("local", args.corpus, SPLIT_FILE))
    lines = [event] + [evidence.aggregate_line(test, lang, [r["category"] for r in group], sum(1 for r in group if r["parse"] == "invalid"))
                       for lang, group in sorted(by_lang.items())]
    try:
        evidence.write_exclusive(os.path.join(folder, f"ix-{test}.jsonl"), lines)
    except FileExistsError:
        raise Refused("the evidence file exists and is never overwritten") from None
    table = {lang: {"n": len(group), "counts": score.measures(group, th["wilson_z"])["counts"]} for lang, group in sorted(by_lang.items())}
    print(json.dumps({"route": route["id"], "languages": table}, indent=1, sort_keys=True) if args.json else
          "\n".join(f"{lang}: n {t['n']}, " + ", ".join(f"{c} {n}" for c, n in t["counts"].items() if n) for lang, t in table.items()))
    return 0


def main(argv=None) -> int:
    try:
        return measure(arguments(sys.argv[1:] if argv is None else argv))
    except Usage as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Refused as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ConfigFault as e:
        print(f"error: the route cannot be called ({e.code}); the run was stopped, and the answers already kept stay in the record", file=sys.stderr)
        return 1
    except ItemFault as e:
        print(f"error: {e.name} at item #{e.ordinal}", file=sys.stderr)
        return 1
    except SystemExit as e:          # argparse: --help (0) and a usage error (2)
        return e.code if isinstance(e.code, int) else 2
    except BaseException as e:          # noqa: BLE001 - the class alone: a message can hold a line
        print(f"error: {type(e).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
