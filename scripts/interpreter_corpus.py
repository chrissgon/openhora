#!/usr/bin/env python3
"""The corpus tooling of the interpreter experiment (package IX-1): build, label, resolve and freeze the items of
evals/interpreter/ (the dev split) and of the held-out test split. evals/interpreter/README.md is the guide: the
folder map, the formats of every input file, the procedure and the labelling rules L1-L10.

Usage: python3 scripts/interpreter_corpus.py <verb> [options]   (each verb takes --help)

  generate     items from templates and slot values, times resolved by code from the item clock
  adversarial  items derived from base items by fixed rules (typo, no-accents, tempt-d, multi-intent, ...)
  view         the labeller's view: opaque ids, shuffled, no gold, author, tags or template key
  diff         where the labels disagree with the author's intent (`<id> <path>` per disagreement)
  resolve      the final gold of every item from intent, labels and the resolver's decisions
  freeze       final ids, `hard`, the canonical file and its sha256 (for test, also test-split.json)
  relabel      the dev relabelling of the three corpora of runtime/tests (mechanical)
  similarity   PASS or FAIL of the 0.80 similarity rule against a file of real lines (never printed)
  sample       a Markdown table of N items of one language for the maintainer's review
  hashes       the sha256 of every frozen file, the catalog and the three interface files
  check        every item of the files against the item format and the catalog

Items are one canonical JSON object per line, sorted by id (canonical = json.dumps(ensure_ascii=False,
sort_keys=True, separators=(",", ":"))). The catalog is read as data (runtime/interpreter_catalog.json by
default); nothing of runtime/ is imported. Data goes to stdout, diagnostics to stderr; no message carries the text
of a line. Exit codes: 0 ok, 1 a problem found (check, diff, similarity FAIL), 2 a usage or input error.
Standard library only; Python 3.9.
"""
from __future__ import annotations

import argparse
import datetime
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the two siblings below, however this file is loaded

from interpreter_corpus_format import (  # noqa: E402
    CATALOG, CHANNELS, FOLDER, ID_RE, LANGS, LINE_KEYS, OPAQUE_RE, RELABEL_AGE_S, RELABEL_BASE, RELABEL_CLOCK,
    RELABEL_RANGE, RELABEL_ZONE, ROOT, RULE_RE, SIMILARITY_THRESHOLD, SOURCES, UsageError, VIEW_KEYS,
    by_id, canonical, check_items, corpus_bytes, count_by, hard_of, load_catalog, make_id, normal, opaque, read_json,
    read_jsonl, read_many, require_valid, rng_for, sha256_bytes, union, write_bytes)
from interpreter_corpus_build import cmd_adversarial, cmd_generate  # noqa: E402


# ------------------------------------------------------------------------------------------- view, diff and resolve

VIEW_SEED_RE = re.compile(r"^[0-9a-f]{32,}$")


def view_seed(seed: str) -> str:
    """The view's seed: fresh random hex, at least 32 characters (`python3 -c "import secrets; print(secrets.token_hex(16))"`),
    kept out of everything the labeller reads. A short or reused seed (the generators' dates) would let the opaque ids be
    walked back to the provisional ids, and so to the authorship buckets."""
    if not VIEW_SEED_RE.match(seed or ""):
        raise UsageError("--seed of view, diff and resolve is fresh random hex of at least 32 characters, never a generator's seed")
    return seed


def cmd_view(args):
    view_seed(args.seed)
    items = read_many(args.in_)
    by_id(items, "the input files")
    rows, seen = [], {}
    for item in items:
        if not isinstance(item.get("id"), str) or not ID_RE.match(item["id"]):
            raise UsageError("an input item has no valid id")
        wid = opaque(args.seed, item["id"])
        if wid in seen:
            raise UsageError(f"opaque ids collide for {seen[wid]} and {item['id']}; use another --seed")
        seen[wid] = item["id"]
        missing = [k for k in VIEW_KEYS if k not in item]
        if missing:
            raise UsageError(f"{item['id']}: no {', '.join(missing)}")
        rows.append(dict({"id": wid}, **{k: item[k] for k in VIEW_KEYS}))
    digest = write_bytes(args.out, corpus_bytes(rows))
    print(f"{digest}  {args.out}  {len(rows)} items")


def gold_disagreements(a, b) -> list:
    try:
        return _disagreements(a, b)
    except (TypeError, AttributeError, KeyError):
        return ["gold (malformed)"]


def _disagreements(a, b) -> list:
    """The paths where two golds disagree: outcome, op, class, item, scope, the slot set, the answer's keys, and slot
    values, spans and times that share no accepted value (values compared by natural.normal, times exactly)."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return ["gold"]
    if a.get("outcome") != b.get("outcome"):
        return ["gold.outcome"]
    out = []
    for key in ("op", "class", "item", "scope", "option", "confirm", "slot"):
        if a.get(key) != b.get(key):
            out.append(f"gold.{key}")
    outcome = a["outcome"]
    if outcome == "clarify":
        return [p for p in out if p == "gold.scope"]  # an informational slot or ops is not scored
    if outcome == "op":
        sa, sb = a.get("slots") or {}, b.get("slots") or {}
        if set(sa) != set(sb):
            out.append("gold.slots")
        else:
            for slot in sorted(sa):
                if not {normal(v) for v in sa[slot]} & {normal(v) for v in sb[slot]}:
                    out.append(f"gold.slots.{slot}")
    if outcome == "answer":
        if set(a) != set(b):
            out.append("gold.keys")
        elif "span" in a and not {normal(v) for v in a["span"]} & {normal(v) for v in b["span"]}:
            out.append("gold.span")
    if ("time" in a or "time" in b) and not set(a.get("time") or []) & set(b.get("time") or []):
        out.append("gold.time")
    return out


def _pairs(intents, labels, seed):
    """(intent id, intent, label or None) for every intent, and the opaque ids of labels that match no intent."""
    view_seed(seed)
    by_wid = {}
    for label in labels:
        wid = label.get("id")
        if not isinstance(wid, str) or not OPAQUE_RE.match(wid):
            raise UsageError("a label's id is w-<8 hex>")
        if wid in by_wid:
            raise UsageError(f"label {wid} appears twice")
        by_wid[wid] = label
    pairs, used = [], set()
    for key in sorted(intents):
        wid = opaque(seed, key)
        used.add(wid)
        pairs.append((key, intents[key], by_wid.get(wid)))
    return pairs, sorted(set(by_wid) - used)


def item_disagreements(intent, label) -> list:
    """The gold's disagreements, and `also` when the label's alternatives are not the intent's: the resolver decides those
    too (an agreed item keeps the intent's alternatives)."""
    paths = gold_disagreements(intent.get("gold"), label.get("gold"))
    mine = sorted(canonical(a) for a in intent.get("also") or [])
    theirs = sorted(canonical(a) for a in label.get("also") or []) if isinstance(label.get("also") or [], list) else None
    return paths + (["also"] if mine != theirs else [])


def cmd_diff(args):
    intents = by_id(read_many(args.intent), "the intent files")
    labels = read_jsonl(args.labels)
    pairs, strays = _pairs(intents, labels, args.seed)
    found = 0
    for key, intent, label in pairs:
        paths = ["label-missing"] if label is None else item_disagreements(intent, label)
        for path in paths:
            print(f"{key} {path}")
        found += bool(paths)
    for wid in strays:
        print(f"{wid} intent-missing")
    print(f"{len(pairs)} items, {len(pairs) - found} agree, {found} disagree, {len(strays)} labels without an intent", file=sys.stderr)
    return 1 if found or strays else 0


def _merged_gold(a, b):
    """The gold of an agreed item: the intent's, with the union of both sides' accepted values and times."""
    out = json.loads(json.dumps(a))
    for slot, spans in (out.get("slots") or {}).items():
        out["slots"][slot] = union(spans, (b.get("slots") or {}).get(slot) or [])
    for key in ("span", "time"):
        if key in out:
            out[key] = union(out[key], b.get(key) or [])
    return out


def cmd_resolve(args):
    cat = load_catalog(args.catalog)
    intents = by_id(read_many(args.intent), "the intent files")
    lines = by_id(read_many(args.lines), "the line files") if args.lines else {}
    labels = read_jsonl(args.labels)
    decisions = by_id(read_jsonl(args.decisions), str(args.decisions))
    pairs, strays = _pairs(intents, labels, args.seed)
    if strays:
        raise UsageError(f"{len(strays)} label(s) match no intent, the first {strays[0]}")
    unknown = sorted(set(decisions) - set(intents))
    if unknown:
        raise UsageError(f"a decision names {unknown[0]}, which is not an intent id")
    out, dropped, missing, total = [], {}, [], {}
    for key, intent, label in pairs:
        base = dict(lines.get(key) or {}, **{k: v for k, v in intent.items() if k not in ("gold", "also")})
        if set(LINE_KEYS) - set(base):
            raise UsageError(f"{key}: no line fields (pass the author's lines with --lines)")
        total[base["author"]] = total.get(base["author"], 0) + 1
        decision = decisions.get(key)
        disagree = label is None or bool(item_disagreements(intent, label))
        if decision is None:
            if disagree:
                missing.append(key)
                continue
            gold = _merged_gold(intent["gold"], label["gold"])
            also = list(intent.get("also") or [])
        else:
            action = decision.get("action")
            if action not in ("keep-intent", "keep-label", "edit", "drop") or not RULE_RE.match(str(decision.get("rule"))):
                raise UsageError(f"decision {key}: action keep-intent|keep-label|edit|drop and rule L1..L10")
            if action == "drop":
                dropped[base["author"]] = dropped.get(base["author"], 0) + 1
                continue
            if action == "keep-label" and label is None:
                raise UsageError(f"decision {key}: keep-label without a label")
            if action == "edit" and "gold" not in decision:
                raise UsageError(f"decision {key}: edit carries the gold")
            source = {"keep-intent": intent, "keep-label": label, "edit": decision}[action]
            gold, also = source["gold"], list(source.get("also") or [])
        out.append(dict(base, gold=gold, also=also))
    if missing:
        raise UsageError(f"{len(missing)} disagreement(s) without a decision, the first {missing[0]}")
    require_valid(out, cat, "the resolved items")
    digest = write_bytes(args.out, corpus_bytes(out))
    rates = {a: round(dropped.get(a, 0) / n, 4) for a, n in sorted(total.items())}
    print(canonical({"out": str(args.out), "sha256": digest, "items": len(out), "bucket": dict(sorted(total.items())),
                     "dropped": dict(sorted(dropped.items())), "drop_rate": rates,
                     "over_15_percent": sorted(a for a, r in rates.items() if r > 0.15)}))


# ------------------------------------------------------------------------------------------------------------- freeze

def cmd_freeze(args):
    cat = load_catalog(args.catalog)
    items = read_many(args.in_)
    by_id(items, "the input files")
    for item in items:
        if item.get("split") != args.split:
            raise UsageError(f"{item.get('id')}: split is {item.get('split')!r}, not {args.split}")
    renamed, numbers = {}, {}
    fresh = sorted((i for i in items if i.get("author") != "relabel"),
                   key=lambda i: (str(i.get("lang")), hashlib.sha256(str(i["id"]).encode("utf-8")).hexdigest()))
    for item in fresh:
        lang = item.get("lang")
        renamed[item["id"]] = make_id(args.split, lang, numbers.get(lang, 0))
        numbers[lang] = numbers.get(lang, 0) + 1
    out = []
    for item in items:
        new = dict(item, id=renamed.get(item["id"], item["id"]), hard=hard_of(item.get("tags")))
        if "base" in new:
            match = ID_RE.match(str(new["base"]))
            relabelled = bool(match) and RELABEL_RANGE[0] <= int(match.group(3)) <= RELABEL_RANGE[1]
            if new["base"] not in renamed and not relabelled:
                raise UsageError(f"{item['id']}: its base {new['base']} is not in the split")
            new["base"] = renamed.get(new["base"], new["base"])  # a relabelled base keeps its id (dev-relabelled.jsonl)
        out.append(new)
    by_id(out, "the frozen items")
    require_valid(out, cat, "the frozen items")
    data = corpus_bytes(out)
    digest = write_bytes(args.out, data)
    print(f"{digest}  {args.out}  {len(out)} items, {sum(i['hard'] for i in out)} hard")
    if args.split == "test":
        golds = [i["gold"] for i in out]
        summary = {"v": 1, "file": Path(args.out).name, "sha256": digest, "items": len(out),
                   "counts": {"lang": count_by(i["lang"] for i in out), "author": count_by(i["author"] for i in out),
                              "outcome": count_by(g["outcome"] for g in golds),
                              "op": count_by(g["op"] for g in golds if g["outcome"] == "op" and g.get("op")),
                              "tags": count_by(t for i in out for t in i["tags"])},
                   "frozen": args.date or datetime.date.today().isoformat()}
        target = Path(args.split_file) if args.split_file else Path(args.out).with_name("test-split.json")
        write_bytes(target, (json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8"))
        print(f"{sha256_bytes(target.read_bytes())}  {target}")


# ------------------------------------------------------------------------------------------------------------ relabel

def _relabel_item(source, number, lang, line, clock, tags, frame, gold, also=()) -> dict:
    tags = sorted(tags)
    return {"id": make_id("dev", lang, RELABEL_BASE[source] + number), "split": "dev", "lang": lang, "author": "relabel",
            "tags": tags, "hard": hard_of(tags), "clock": clock, "zone": RELABEL_ZONE, "channel": "messaging",
            "forwarded": False, "frame": frame, "line": line, "gold": gold, "also": list(also)}


def _outside(moment: str, now: datetime.datetime) -> bool:
    when = datetime.datetime.strptime(moment, "%Y-%m-%dT%H:%M")
    return when <= now or when - now > datetime.timedelta(days=366)


def relabel(natural_rows, writes_rows, mail_rows) -> list:
    """The dev relabelling (spec IX-1, "Relabel"): code only, one item per source line, ids by the line's place in its file.
    A moment outside (clock, clock + 366 days] is no acceptable reading (the interpreter's time-past and time-far): an
    expected one makes the gold clarify, tagged past or far-future; an accepted alternative there is left out."""
    out = []
    for n, row in enumerate(natural_rows):
        expected, clock = row["expected"], (row.get("clock") or "").replace(" ", "T") or RELABEL_CLOCK
        kind, now = expected.get("kind"), datetime.datetime.strptime(clock, "%Y-%m-%dT%H:%M")
        tags = {"relabel-time"} | ({"past"} if expected.get("why") == "past" else set())
        due = (expected.get("due") or "").replace(" ", "T")
        if kind == "time" and _outside(due, now):
            kind = "ask"
            tags.add("past" if due <= clock else "far-future")
        times = [t for t in [due] if kind == "time"] + [t.replace(" ", "T") for t in row.get("also_ok") or []
                                                         if not _outside(t.replace(" ", "T"), now)]
        if row.get("timeonly"):
            frame = {"v": 1, "items": [{"id": "i1", "kind": "reminder-confirm", "op": "remind", "need": "slot", "slot": "when",
                                        "age_s": RELABEL_AGE_S}], "last": None}
            gold = ({"outcome": "answer", "item": "i1", "slot": "when", "time": times}
                    if kind == "time" else {"outcome": "clarify"})
            out.append(_relabel_item("natural", n, row["language"], row["text"], clock, tags | {"multi-turn"}, frame, gold))
            continue
        if kind == "time":
            gold, also = {"outcome": "op", "op": None, "time": times, "scope": "time"}, []
        else:
            gold = {"outcome": "clarify", "scope": "time"}
            also = [{"outcome": "op", "op": None, "time": times}] if times else []
        out.append(_relabel_item("natural", n, row["language"], row["text"], clock, tags, None, gold, also))
    for source, rows in (("writes", writes_rows), ("mail", mail_rows)):
        for n, row in enumerate(rows):
            gold = {"outcome": "route"} if row["op"] == "work" else {"outcome": "op", "op": row["op"], "scope": "op"}
            out.append(_relabel_item(source, n, row["lang"], row["line"], RELABEL_CLOCK, {"relabel-op"}, None, gold))
    return out


def cmd_relabel(args):
    items = relabel(read_jsonl(args.natural), read_jsonl(args.writes), read_jsonl(args.mail))
    by_id(items, "the relabelled items")
    digest = write_bytes(args.out, corpus_bytes(items))
    counts = {"items": len(items), "lang": count_by(i["lang"] for i in items),
              "outcome": count_by(i["gold"]["outcome"] + ("/" + i["gold"]["scope"] if "scope" in i["gold"] else "") for i in items)}
    print(f"{digest}  {args.out}  {canonical(counts)}")


# ------------------------------------------------------------------------------------------------- similarity, sample

QUOTES = "\"'`\u201c\u201d\u2018\u2019\u00ab\u00bb "


def _candidates(raw: str) -> list:
    """The pieces of one line of the real file that may be a line a person typed: each cell of a Markdown table row, or
    the line; heading, quote, bullet and numbering markers, emphasis and quote marks removed; a short `label:` prefix
    also dropped (both forms kept)."""
    cells = raw.strip().strip("|").split("|") if raw.lstrip().startswith("|") else [raw]
    out = []
    for cell in cells:
        text = re.sub(r"^\s*(?:[#>]+\s*)*(?:[-*+]\s+|[0-9]+[.)]\s+)?", "", cell).replace("**", "").replace("__", "")
        text = text.strip().strip(QUOTES)
        out.append(text)
        head, sep, rest = text.partition(":")
        if sep and rest.strip() and len(head.split()) <= 3:
            out.append(rest.strip().strip(QUOTES))
    return out


def _real_lines(path) -> list:
    """The folded candidate lines of the real file, lines under two words skipped. Nothing of it is ever printed."""
    try:
        text = Path(path).read_bytes().decode("utf-8", errors="replace")
    except OSError:
        raise UsageError("cannot read the --real file")
    out = []
    for raw in text.splitlines():
        for line in _candidates(raw):
            folded = normal(line)
            if len(folded.split()) >= 2 and folded not in out:
                out.append(folded)
    return out


def similar_ids(corpus, real, threshold) -> list:
    """The ids of corpus items whose folded line has a difflib ratio >= threshold with some real line (either order)."""
    pending = [(i["id"], normal(i.get("line") or "")) for i in corpus]
    pending = [(key, a) for key, a in pending if a]
    flagged = set()
    matcher = difflib.SequenceMatcher(None, autojunk=False)
    for b in real:
        matcher.set_seq2(b)  # the real line is analysed once; every corpus line is compared with it
        for key, a in pending:
            if key in flagged or 2.0 * min(len(a), len(b)) / (len(a) + len(b)) < threshold:
                continue
            matcher.set_seq1(a)
            if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
                continue
            if matcher.ratio() >= threshold or difflib.SequenceMatcher(None, b, a, autojunk=False).ratio() >= threshold:
                flagged.add(key)
    return sorted(flagged)


def cmd_similarity(args):
    """Fail closed: a threshold outside (0, 1], a real file with fewer than --min-real lines, or a corpus file that does not
    pass check stops with exit 2 and one sentence that names no line and no id."""
    if not 0 < args.threshold <= 1:
        raise UsageError("--threshold is a number in (0, 1]")
    corpus = read_many(args.corpus)
    problems = check_items(corpus, load_catalog(args.catalog))
    if problems:
        raise UsageError(f"the --corpus files have {len(problems)} problem(s) under check; run check on them first")
    real = _real_lines(args.real)
    if len(real) < args.min_real:
        raise UsageError(f"the --real file gave {len(real)} line(s), fewer than --min-real {args.min_real}: is it the right file?")
    flagged = similar_ids(corpus, real, args.threshold)
    if not flagged:
        print("PASS")
        return 0
    print(f"FAIL {len(flagged)}")
    if args.ids:
        for key in flagged:
            print(key)
    return 1


def frame_words(frame) -> str:
    if frame is None:
        return "nothing open"
    parts = []
    for item in frame.get("items") or []:
        what = f"{item.get('id')} {item.get('kind')}" + (f" of {item['op']}" if item.get("op") else "")
        need = item.get("need")
        what += f", needs {item['slot']}" if need == "slot" else f", needs {need}"
        if item.get("options"):
            what += f" ({item['options']} options)"
        parts.append(what)
    last = frame.get("last")
    if last:
        words = ", ".join(f"{k}: {v}" for k, v in sorted((last.get("words") or {}).items()))
        parts.append(f"last request {last.get('op')}" + (f" ({words})" if words else ""))
    return "; ".join(parts) or "nothing open"


def gold_words(gold) -> str:
    outcome = gold.get("outcome")
    if outcome == "op":
        text = f"do {gold.get('op') or '(time only)'}"
        slots = "; ".join(f"{k} = {' / '.join(v)}" for k, v in sorted((gold.get("slots") or {}).items()))
        text += f": {slots}" if slots else ""
    elif outcome == "answer":
        text = f"answer {gold.get('item')}"
        for key in ("option", "confirm", "slot"):
            if key in gold:
                text += f", {key} {gold[key]}"
        if gold.get("span"):
            text += f" = {' / '.join(gold['span'])}"
    elif outcome == "refuse":
        text = f"refuse ({gold.get('class')})"
    else:
        text = str(outcome)
    if gold.get("time"):
        text += f"; at {' or '.join(gold['time'])}"
    return text


def cmd_sample(args):
    items = [i for i in read_many(args.corpus) if i.get("lang") == args.lang]
    items.sort(key=lambda i: str(i.get("id")))
    if len(items) < args.n:
        raise UsageError(f"{len(items)} items in {args.lang}, fewer than --n {args.n}")
    chosen = sorted(rng_for("sample", args.seed, args.lang).sample(items, args.n), key=lambda i: i["id"])

    def cell(text):
        return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")

    rows = ["| id | line | open items | gold | ok? |", "|---|---|---|---|---|"]
    for item in chosen:
        gold = gold_words(item["gold"]) + "".join(f"; also {gold_words(a)}" for a in item.get("also") or [])
        rows.append(f"| {item['id']} | {cell(item['line'])} | {cell(frame_words(item.get('frame')))} | {cell(gold)} | |")
    header = (f"# Sample of {args.n} {args.lang} items\n\nMark each row `ok` or `wrong` in the last column (a wrong row is "
              "relabelled or dropped before freeze). Times are local, in the item's zone, at its clock.\n\n")
    write_bytes(args.out, (header + "\n".join(rows) + "\n").encode("utf-8"))
    print(f"{len(chosen)} rows  {args.out}")


# ------------------------------------------------------------------------------------------------------ hashes, check

FROZEN = ("evals/interpreter/dev.jsonl", "evals/interpreter/dev-relabelled.jsonl", "evals/interpreter/test-split.json")
INTERFACES = ("evals/interpreter/frame.schema.json", "evals/interpreter/taxonomy.json", "evals/interpreter/thresholds.json")


def cmd_hashes(args):
    root, missing = Path(args.root), 0
    rows = [(p, ("bytes",)) for p in FROZEN] + [(p, ("bytes", "canonical")) for p in INTERFACES]
    rows.append(("runtime/interpreter_catalog.json", ("canonical", "bytes")))
    if args.test:
        rows.append((args.test, ("bytes",)))
    for rel, forms in rows:
        path = root / rel if not Path(rel).is_absolute() else Path(rel)
        if not path.is_file():
            print(f"missing  {rel}")
            missing += 1
            continue
        for form in forms:
            digest = sha256_bytes(path.read_bytes()) if form == "bytes" else sha256_bytes(canonical(read_json(path)).encode("utf-8"))
            print(f"{digest}  {rel}  {form}")
    return 1 if missing else 0


def cmd_check(args):
    cat = load_catalog(args.catalog)
    items = read_many(args.in_)
    problems = check_items(items, cat, args.lines)
    for line in problems:
        print(line)
    print(f"{len(items)} items, {len(problems)} problem(s)", file=sys.stderr)
    return 1 if problems else 0


# --------------------------------------------------------------------------------------------------------------- main

def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="interpreter_corpus.py", description=__doc__.split("\n\n")[0],
                                  formatter_class=argparse.RawDescriptionHelpFormatter, epilog="See evals/interpreter/README.md.")
    verbs = top.add_subparsers(dest="verb", metavar="<verb>")
    verbs.required = True

    def verb(name, text):
        return verbs.add_parser(name, help=text, description=text)

    def catalog(p):
        p.add_argument("--catalog", default=str(CATALOG), help="the served catalog (default runtime/interpreter_catalog.json)")

    p = verb("generate", "Items from templates and slot values (author gen); times resolved by code from --clock.")
    p.add_argument("--templates", required=True)
    p.add_argument("--values", required=True)
    catalog(p)
    p.add_argument("--lang", required=True, choices=sorted(LANGS))
    p.add_argument("--count", required=True, type=int)
    p.add_argument("--seed", required=True)
    p.add_argument("--split", required=True, choices=("dev", "test"))
    p.add_argument("--start", type=int, default=0, help="the first id number (keeps the authors' provisional ids apart)")
    p.add_argument("--clock", default=RELABEL_CLOCK)
    p.add_argument("--zone", default=RELABEL_ZONE)
    p.add_argument("--channel", default="messaging", choices=CHANNELS)
    p.add_argument("--out", required=True)
    p.set_defaults(run=cmd_generate)

    p = verb("adversarial", "Items derived from base items by the rules and plan of an adversarial.json (author adv).")
    p.add_argument("--rules", required=True)
    p.add_argument("--in", dest="in_", required=True)
    p.add_argument("--seed", required=True)
    p.add_argument("--start", type=int, default=0)
    catalog(p)
    p.add_argument("--out", required=True)
    p.set_defaults(run=cmd_adversarial)

    p = verb("view", "The labeller's view: id w-<8hex>, lang, clock, zone, channel, forwarded, frame, line; shuffled.")
    p.add_argument("--in", dest="in_", required=True, nargs="+")
    p.add_argument("--seed", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(run=cmd_view)

    p = verb("diff", "`<id> <path>` per disagreement between intent and labels; exit 1 when there is one.")
    p.add_argument("--intent", required=True, nargs="+")
    p.add_argument("--labels", required=True)
    p.add_argument("--seed", required=True, help="the seed the view was made with")
    p.set_defaults(run=cmd_diff)

    p = verb("resolve", "Final items from intent, labels and decisions; prints the drop rate per authorship bucket.")
    p.add_argument("--intent", required=True, nargs="+")
    p.add_argument("--labels", required=True)
    p.add_argument("--decisions", required=True)
    p.add_argument("--seed", required=True, help="the seed the view was made with")
    p.add_argument("--lines", nargs="+", default=[], help="the author's line files, when an intent file holds id, gold, also only")
    catalog(p)
    p.add_argument("--out", required=True)
    p.set_defaults(run=cmd_resolve)

    p = verb("freeze", "Final ids, hard, the canonical file and its sha256; for test also test-split.json.")
    p.add_argument("--in", dest="in_", required=True, nargs="+")
    p.add_argument("--split", required=True, choices=("dev", "test"))
    p.add_argument("--out", required=True)
    p.add_argument("--split-file", help="where test-split.json goes (default: beside --out)")
    p.add_argument("--date", help="the frozen date (default today)")
    catalog(p)
    p.set_defaults(run=cmd_freeze)

    p = verb("relabel", "The dev relabelling of the three corpora of runtime/tests (code only).")
    p.add_argument("--natural", default=str(SOURCES / "natural_corpus.jsonl"))
    p.add_argument("--writes", default=str(SOURCES / "natural_writes_corpus.jsonl"))
    p.add_argument("--mail", default=str(SOURCES / "natural_writes_mail_corpus.jsonl"))
    p.add_argument("--out", default=str(FOLDER / "dev-relabelled.jsonl"))
    p.set_defaults(run=cmd_relabel)

    p = verb("similarity", "PASS (exit 0) or FAIL <count> (exit 1); --ids adds the corpus ids. A real line is never printed.")
    p.add_argument("--corpus", required=True, action="append")
    p.add_argument("--real", required=True)
    p.add_argument("--threshold", type=float, default=SIMILARITY_THRESHOLD)
    p.add_argument("--min-real", type=int, default=20, help="the fewest lines the real file must give (default 20)")
    p.add_argument("--ids", action="store_true")
    catalog(p)
    p.set_defaults(run=cmd_similarity)

    p = verb("sample", "A Markdown table of --n items of --lang (id, line, open items, gold, a blank ok? column).")
    p.add_argument("--corpus", required=True, action="append")
    p.add_argument("--lang", required=True, choices=sorted(LANGS))
    p.add_argument("--n", required=True, type=int)
    p.add_argument("--seed", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(run=cmd_sample)

    p = verb("hashes", "The sha256 of the frozen files, the three interface files and the catalog; exit 1 when one is missing.")
    p.add_argument("--root", default=str(ROOT))
    p.add_argument("--test", help="the held-out test file, hashed over its bytes")
    p.set_defaults(run=cmd_hashes)

    p = verb("check", "Every item against the item format and the catalog: `<id> <problem>` per problem, exit 1 when any.")
    p.add_argument("--in", dest="in_", required=True, nargs="+")
    p.add_argument("--lines", action="store_true", help="the items carry no gold and no also (an author's line file)")
    catalog(p)
    p.set_defaults(run=cmd_check)
    return top


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.run(args) or 0
    except UsageError as exc:
        print(f"interpreter_corpus {args.verb}: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # no traceback: a frame of it could hold a line
        print(f"interpreter_corpus {args.verb}: internal error ({type(exc).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
