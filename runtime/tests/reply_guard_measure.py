"""The measurement of the reply set (CANDIDATE-OUT PR 1): what the new engine does with each pair, the two bars and the agreement. Not a test file.

The set is runtime/tests/reply_guard_lines.jsonl (built by reply_guard_build.py, labelled by a blind labeller, frozen by reply_guard_split.json before the guard existed). Each pair is replayed with no
model call: the draft is made by the pair's recipe at the pinned clock, `turn_gate.complete_reminder` (the product's one call, `natural.complete` with the guard's verdict) is run on the line, and the
result is classed like the old one was: None is `new`, the same draft asked once more is `retry`, anything else is `answer`.

Bars, on the test split, over the pairs whose gold is not `unclear` (those are excluded from both bars and counted):
  B1 (hard)  no pair with gold `answer`, old `answer` or `retry` and new `new`: no answer that the old engine kept becomes a new request;
  B2         the pairs with gold `new` that the new engine takes as `answer` are no more than the old engine's; every such pair is listed, and so is every `retry` of a gold `new` ("asked once more").
Agreement: old against new class on every labelled pair (the dev split too), with n and a Wilson 95% band, by language and by question kind.

Run (one command, no model, no network): python3 runtime/tests/reply_guard_measure.py --print
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import reply_guard_build as rgb  # noqa: E402  (the same folder: the recipes of the drafts, the clock and the classing of an outcome)

SPLIT_FILE = HERE / "reply_guard_split.json"


def wilson(hits: int, total: int, z: float = 1.96) -> list:
    """The Wilson score interval of `hits` in `total`, as [low, high] rounded to 3 places ([0, 1] for no trial)."""
    if total == 0:
        return [0.0, 1.0]
    p = hits / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def file_sha256() -> str:
    return hashlib.sha256(rgb.LINES.read_bytes()).hexdigest()


def outcome_of(natural, draft: dict, got) -> str:
    """The class of a result of `complete`: None is a new line, the same draft asked once more is a retry, anything else an answer."""
    if got is None:
        return "new"
    ask = got.get("ask") if isinstance(got, dict) else None
    if ask is not None and ask == {**draft, "retries": draft.get("retries", 0) + 1}:
        return "retry"
    return "answer"


def new_outcome(natural, turn_gate, phrases, row: dict, complete=None) -> str:
    """What the engine does with the pair now. `complete` is the call under test (default: the product's `turn_gate.complete_reminder`); a test plants another to prove the bars can fail."""
    draft = rgb.make_draft(natural, phrases, row["draft_seed"], row["lang"])
    call = complete or turn_gate.complete_reminder
    return outcome_of(natural, draft, call(copy.deepcopy(draft), row["line"], rgb.now_clock()))


def measure(rows: list, natural, turn_gate, phrases, complete=None) -> dict:
    """The figures of the set: for every labelled pair its new class, the bars on the test split, the agreement tables. `rows` are the pairs of the file."""
    given = []
    for row in rows:
        given.append({**row, "new": new_outcome(natural, turn_gate, phrases, row, complete)})
    labelled = [r for r in given if r["gold"] != "unclear"]
    test = [r for r in labelled if r["split"] == "test"]
    b1 = [r["id"] for r in test if r["gold"] == "answer" and r["old"] in ("answer", "retry") and r["new"] == "new"]
    old_missed = [r for r in test if r["gold"] == "new" and r["old"] == "answer"]
    new_missed = [r for r in test if r["gold"] == "new" and r["new"] == "answer"]
    new_retried = [r for r in test if r["gold"] == "new" and r["new"] == "retry"]
    old_retried = [r for r in test if r["gold"] == "new" and r["old"] == "retry"]

    def listing(items):
        return [{"id": r["id"], "lang": r["lang"], "need": r["need"], "line": r["line"], "old": r["old"], "new": r["new"]} for r in items]

    def agreement(items):
        total = len(items)
        same = sum(1 for r in items if r["old"] == r["new"])
        return {"n": total, "same": same, "rate": round(same / total, 3) if total else None, "wilson95": wilson(same, total)}

    by_lang = {lang: agreement([r for r in labelled if r["lang"] == lang]) for lang in rgb.LANGS}
    by_need = {need: agreement([r for r in labelled if r["need"] == need]) for need in rgb.NEEDS}
    transitions = {}
    for r in labelled:
        key = f"{r['old']}->{r['new']}"
        transitions[key] = transitions.get(key, 0) + 1
    return {
        "set_sha256": file_sha256(), "pairs": len(given),
        "unclear": {"all": sum(1 for r in given if r["gold"] == "unclear"), "test": sum(1 for r in given if r["gold"] == "unclear" and r["split"] == "test")},
        "labelled": {"all": len(labelled), "test": len(test), "dev": len(labelled) - len(test)},
        "b1": {"violations": len(b1), "ids": b1, "pairs_at_risk": sum(1 for r in test if r["gold"] == "answer" and r["old"] in ("answer", "retry"))},
        "b2": {"old_takes_new_as_answer": len(old_missed), "new_takes_new_as_answer": len(new_missed), "passes": len(new_missed) <= len(old_missed),
               "gold_new_pairs": sum(1 for r in test if r["gold"] == "new"),
               "new_listed": listing(new_missed), "new_asked_once_more": listing(new_retried), "old_asked_once_more_count": len(old_retried)},
        "agreement": {"all": agreement(labelled), "test": agreement(test), "by_lang": by_lang, "by_need": by_need, "transitions": dict(sorted(transitions.items()))},
        "gold_vs_new_on_test": {
            "answer_kept": sum(1 for r in test if r["gold"] == "answer" and r["new"] in ("answer", "retry")),
            "answer_total": sum(1 for r in test if r["gold"] == "answer"),
            "new_dropped": sum(1 for r in test if r["gold"] == "new" and r["new"] == "new"),
            "new_total": sum(1 for r in test if r["gold"] == "new"),
        },
    }


def load_modules():
    natural, phrases, st = rgb.load_modules()
    return natural, st.load("turn_gate"), phrases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Replay the reply set with the product's guard and print the figures of the bars and of the agreement (no model call).")
    parser.add_argument("--print", action="store_true", help="print the figures as JSON")
    args = parser.parse_args(argv)
    natural, turn_gate, phrases = load_modules()
    _header, rows = rgb.read_rows()
    figures = measure(rows, natural, turn_gate, phrases)
    if args.print:
        print(json.dumps(figures, indent=1, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
