#!/usr/bin/env python3
"""The tier-1 cover set of the interpreter experiment (package S41-11, PR 1): what today's code claimers take, as items of the corpus, and what has no item to be.

This is the ONE-TIME builder behind `python3 scripts/interpreter_corpus.py tier1-cover`. It runs the claimers of the natural-language layer offline, the same ones the messaging bridge and the
operations layer call before any model, over a closed universe of lines, and writes two files: `evals/interpreter/tier1-cover-v1.jsonl` (items of the lines no earlier corpus holds) and
`evals/interpreter/tier1-cover-gaps.json` (the accounting of the whole universe and the gap list). It reads runtime/natural.py, runtime/natural_time.py and runtime/natural_writes.py by path
(the layer map lists this one script for that), and it is deleted with the claimers it runs (PR 2a of S41-11): after that the two files are frozen data, like evals/interpreter/dev-relabelled.jsonl.

THE RULE (the same text is in evals/interpreter/README.md, section "The tier-1 cover set"):

 1. Universe. The distinct lines of (a) the three corpora of runtime/tests (natural_corpus, natural_writes_corpus, natural_writes_mail_corpus); (b) every scenario of the entry corpus
    (base and entry_ext/) whose recorded trace holds one of the six rows S41-11 retires (write-form, reminder-form, help-in-words, tier-1-form, write-form-ops, closed-form-without-slot);
    (c) the form lines of runtime/tests/test_natural_table.py (SAMPLES, ARE_FORMS) and of runtime/tests/test_commands_in_words.py (the english and portuguese columns of its parametrized
    tests, `{id}` filled with 3). A line that is empty or starts with "/" is a typed command and is never read.
 2. Taken. A line is taken by the first of these, in the order the turn takes a line: help-in-words (`natural.match` says `commands`), write-form (`natural_writes.candidate`),
    reminder-form (`natural.claim`), tier-1-form (`natural.match`; closed-form-without-slot when the operation is a D or W class). The claimers run with no scope open: the interpreter is off
    for the sender, so a line that repeats is claimed by the closed form, as it was before the catalog of version 2 was served.
 3. The operation is the one the claimer named (the calendar event is `event-create`). An operation the served catalog lists in `ops` gives an item; one it lists in `refused` (a D operation or
    a widening G operation) or does not list at all gives NO item: it goes to the gap list (kind `refused` or `absent`), because the request works today and would stop working.
 4. The gold. Outcome `op` with that operation. The slots are those the claimer gave and only a form gives any: the integer written in the line, written as digits in it; a slot value is a
    gold span only when it is a substring of the line. The gold is full (it names the slots) only when the claimer's slots are the whole slot set of the operation's served row; in every other
    case the gold has scope `op` (the operation alone, as the writes and mail items of dev-relabelled.jsonl have), so a model that also reads an optional slot is not scored wrong for it.
    A reminder or a write line is always scope `op`: no span is invented for it.
 5. The item. Author `relabel` (a mechanical relabelling, by code), tag `relabel-op`, no frame, the relabelling's clock, zone and channel, id `dev-<lang>-4NNNN` where NNNN is the place of the
    line in the sorted list of added lines. The language is the one table whose own claim equals the whole claim; when no table or both tables give it, `mixed`.
 6. Covered. A line that dev-relabelled.jsonl already holds, with no frame and a gold of the same operation (a reminder line: any scope-time item), is covered and adds no item.
 7. Every line of the universe that is taken is exactly one of: a gap, covered, or an added item. The accounting is in the gaps file.

Python 3.9, standard library plus the three pure runtime modules above; no network, no model.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from interpreter_corpus_format import (  # noqa: E402
    RELABEL_BASE, RELABEL_CLOCK, RELABEL_ZONE, ROOT, UsageError, canonical, corpus_bytes, load_catalog, make_id, read_json, read_jsonl, require_valid, sha256_bytes)

COVER_FILE = "tier1-cover-v1.jsonl"
GAPS_FILE = "tier1-cover-gaps.json"
RETIRED_ROWS = ("write-form", "reminder-form", "help-in-words", "tier-1-form", "write-form-ops", "closed-form-without-slot")
ROWS = ("help-in-words", "write-form", "reminder-form", "tier-1-form", "closed-form-without-slot")      # the rows that take a line, as `taken` names them
PRIVATE_ROWS = ("write-form", "reminder-form")      # a write to the person's accounts and a reminder asked in words: the lines OPEN-41-7 lets reach the daily route
ID_FILL = "3"      # what `{id}` stands for in a parametrized form line
NATURAL_CORPORA = (("natural", "natural_corpus.jsonl", "text"), ("writes", "natural_writes_corpus.jsonl", "line"), ("mail", "natural_writes_mail_corpus.jsonl", "line"))
EXT_PACKAGES_DIR = "entry_ext"
BASE_TIER1 = RELABEL_BASE.get("tier1", 40000)


class Claimers:
    """The three pure runtime modules, loaded once (the folder `runtime/` is put on the path here, never at import)."""

    def __init__(self, root: Path = ROOT):
        sys.path.insert(0, str(Path(root) / "runtime"))
        import natural  # noqa: E402
        import natural_time  # noqa: E402
        import natural_writes  # noqa: E402
        self.natural, self.writes, self.tables = natural, natural_writes, natural_time.languages()

    def taken(self, line, tables=None):
        """None, or {"row", "op", "args"}: what the first claimer that takes the line says (rule 2). `tables` restricts every claimer to those language tables."""
        if not isinstance(line, str) or not line.strip() or line.lstrip().startswith("/"):
            return None
        natural = self.natural
        match = natural.match(line, tables)
        if match is not None and match["op"] == "commands":
            return {"row": "help-in-words", "op": "commands", "args": {}}
        written = self.writes.candidate(line, tables)
        if written:
            return {"row": "write-form", "op": written["op"], "args": {}}
        named = natural.claim(line, tables)
        if named:
            return {"row": "reminder-form", "op": natural.operation_of(named["op"]), "args": {}}
        if match is not None:
            row = "closed-form-without-slot" if natural.class_of(match["op"]) in ("D", "W") else "tier-1-form"
            return {"row": row, "op": match["op"], "args": dict(match["args"])}
        return None

    def language(self, line, found) -> tuple:
        """(language tag, tags) of rule 5: the table whose own claim equals the whole claim, else `mixed`."""
        tags = []
        for table in self.tables:
            own = self.taken(line, [table])
            if own is not None and (own["row"], own["op"]) == (found["row"], found["op"]):
                tags.append(table["tag"])
        return (tags[0] if len(tags) == 1 else "mixed"), tags

    def slots_of(self, found) -> dict:
        """{served slot name: parameter value} the claimer gave: only a tier-1 form gives one (the integer), through the operation's own row of `natural.NATURAL`."""
        row = self.natural.NATURAL.get(found["op"], {}).get("slots", {})
        return {slot: found["args"][spec[1]] for slot, spec in row.items() if spec[0] == "int" and spec[1] in found["args"]}


# ----------------------------------------------------------------------------------------------------------------------------------------- the universe

def corpus_lines(root: Path) -> list:
    """[(source, line)] of the three corpora, in file order."""
    out = []
    for name, file, key in NATURAL_CORPORA:
        for row in read_jsonl(Path(root) / "runtime" / "tests" / file):
            out.append((f"corpus:{name}", row.get("text") if key == "text" else row.get("line")))
    return out


def entry_lines(root: Path) -> list:
    """[("entry", text)] of every scenario (base and entry_ext/) whose recorded trace holds a retired row, in file order."""
    tests = Path(root) / "runtime" / "tests"
    pairs = [(tests / "entry_corpus.jsonl", tests / "entry_golden.jsonl")]
    for scenarios in sorted((tests / EXT_PACKAGES_DIR).glob("*.scenarios.jsonl")):
        pairs.append((scenarios, scenarios.with_name(scenarios.name.replace(".scenarios.", ".golden."))))
    out = []
    for scenarios, golden in pairs:
        traces = {row["id"]: row["outcome"]["trace"] for row in read_jsonl(golden) if not row.get("header")}
        for row in read_jsonl(scenarios):
            if any(name in RETIRED_ROWS for name in traces.get(row["id"], [])):
                out.append(("entry", row["text"]))
    return out


def _assigned(tree, names):
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return found


def form_lines(root: Path) -> list:
    """[(source, line)] of the form lines the two test files hold as literals: read from their source, never by running them."""
    tests = Path(root) / "runtime" / "tests"
    out = []
    table = ast.parse((tests / "test_natural_table.py").read_text(encoding="utf-8"))
    held = _assigned(table, ("SAMPLES", "ARE_FORMS"))
    if set(held) != {"SAMPLES", "ARE_FORMS"}:
        raise UsageError("test_natural_table.py: SAMPLES and ARE_FORMS are not literals any more")
    for lines in held["SAMPLES"].values():
        out += [("form:natural_table", line) for line in lines]
    out += [("form:natural_table", line) for line in held["ARE_FORMS"]]
    words = ast.parse((tests / "test_commands_in_words.py").read_text(encoding="utf-8"))
    for node in ast.walk(words):
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call) and getattr(deco.func, "attr", "") == "parametrize" and len(deco.args) >= 2
                    and isinstance(deco.args[0], ast.Constant) and isinstance(deco.args[0].value, str)):
                continue
            names = [n.strip() for n in deco.args[0].value.split(",")]
            columns = [i for i, n in enumerate(names) if n in ("english", "portuguese")]
            if len(columns) != 2:
                continue
            for row in ast.literal_eval(deco.args[1]):
                out += [("form:commands_in_words", row[i].replace("{id}", ID_FILL)) for i in columns]
    return out


def universe(root: Path) -> list:
    """[(source, line)], the first source of a distinct line kept, in the order of rule 1."""
    seen, out = set(), []
    for source, line in corpus_lines(root) + entry_lines(root) + form_lines(root):
        if isinstance(line, str) and line not in seen:
            seen.add(line)
            out.append((source, line))
    return out


# ------------------------------------------------------------------------------------------------------------------------------------------ the rule

def digits_written(line: str, digits: str) -> bool:
    return re.search(r"(?<![0-9])" + re.escape(digits) + r"(?![0-9])", line) is not None


def gold_of(found: dict, slots: dict, row_slots: dict, line: str) -> dict:
    """The gold of rule 4. `slots` is {slot: value}, `row_slots` the slots of the operation's served row."""
    op = found["op"]
    spans = {slot: [str(value)] for slot, value in slots.items() if digits_written(line, str(value))}
    if spans and len(spans) == len(slots) and set(spans) == set(row_slots):
        return {"outcome": "op", "op": op, "slots": spans}
    return {"outcome": "op", "op": op, "scope": "op"}


def covered(line: str, op: str, relabelled_by_line: dict) -> bool:
    for item in relabelled_by_line.get(line, []):
        gold = item["gold"]
        if item["frame"] is None and ((gold["outcome"] == "op" and gold.get("op") == op) or (op == "remind" and gold.get("scope") == "time")):
            return True
    return False


def build(root: Path = ROOT, catalog_path=None, relabelled_path=None, claimers=None) -> tuple:
    """(items, gaps document) of the rule, deterministic: the same files give the same bytes."""
    root = Path(root)
    catalog_path = Path(catalog_path) if catalog_path else root / "runtime" / "interpreter_catalog.json"
    relabelled_path = Path(relabelled_path) if relabelled_path else root / "evals" / "interpreter" / "dev-relabelled.jsonl"
    claimers = claimers or Claimers(root)
    served = load_catalog(catalog_path)
    raw = read_json(catalog_path)
    by_line = {}
    for item in read_jsonl(relabelled_path):
        by_line.setdefault(item["line"], []).append(item)
    sources, added, gap_rows = {}, [], {}
    for source, line in universe(root):
        account = sources.setdefault(source, {"lines": 0, "taken": 0, "gap": 0, "covered": 0, "added": 0, "private": 0})
        account["lines"] += 1
        found = claimers.taken(line)
        if found is None:
            continue
        account["taken"] += 1
        lang, tags = claimers.language(line, found)
        account["private"] += found["row"] in PRIVATE_ROWS
        op = found["op"]
        if op not in served["ops"]:
            kind = "refused" if op in served["refused"] else "absent"
            account["gap"] += 1
            row = gap_rows.setdefault(op, {"kind": kind, "class": served["refused"].get(op) or claimers.natural.class_of(op), "rows": {}, "lines": 0, "by_lang": {}})
            row["lines"] += 1
            row["rows"][found["row"]] = row["rows"].get(found["row"], 0) + 1
            row["by_lang"][lang] = row["by_lang"].get(lang, 0) + 1
            continue
        if covered(line, op, by_line):
            account["covered"] += 1
            continue
        account["added"] += 1
        added.append({"line": line, "found": found, "lang": lang, "gold": gold_of(found, claimers.slots_of(found), served["ops"][op]["slots"], line)})
    added.sort(key=lambda row: row["line"])
    items = []
    for number, row in enumerate(added):
        items.append({"id": make_id("dev", row["lang"], BASE_TIER1 + number), "split": "dev", "lang": row["lang"], "author": "relabel", "tags": ["relabel-op"], "hard": False,
                      "clock": RELABEL_CLOCK, "zone": RELABEL_ZONE, "channel": "messaging", "forwarded": False, "frame": None, "line": row["line"], "gold": row["gold"], "also": []})
    require_valid(items, served, "the tier-1 cover items")
    measured = {"dev-relabelled.jsonl": [i for group in by_line.values() for i in group], COVER_FILE: items}
    return items, gaps_document(catalog_path, raw, served, sources, added, gap_rows, private_by_set(claimers, measured))


def _count(values) -> dict:
    out = {}
    for value in values:
        out[value] = out.get(value, 0) + 1
    return dict(sorted(out.items()))


def kind_lines(gap_rows) -> dict:
    out = {}
    for row in gap_rows.values():
        out[row["kind"]] = out.get(row["kind"], 0) + row["lines"]
    return dict(sorted(out.items()))


def private_by_set(claimers, measured) -> dict:
    """{file: {"items", "private", "by_lang"}}: an item is private when the claimers, with no frame, take its line as a write or a reminder (rule 2), whatever its own context."""
    out = {}
    for name, items in measured.items():
        private = [i for i in items if (claimers.taken(i["line"]) or {}).get("row") in PRIVATE_ROWS]
        out[name] = {"items": len(items), "private": len(private), "by_lang": _count(i["lang"] for i in private)}
    return out


def gaps_document(catalog_path, raw, served, sources, added, gap_rows, private) -> dict:
    total = {key: sum(a[key] for a in sources.values()) for key in ("lines", "taken", "gap", "covered", "added", "private")}
    return {
        "v": 1,
        "catalog": {"v": raw.get("v"), "sha256": sha256_bytes(canonical(raw).encode("utf-8")), "ops": len(served["ops"]), "refused": len(served["refused"])},
        "rule": "scripts/interpreter_corpus_tier1.py, the text of its module and evals/interpreter/README.md, section The tier-1 cover set",
        "universe": {"sources": dict(sorted(sources.items())), "total": total},
        "added": {"items": len(added), "by_lang": _count(row["lang"] for row in added), "by_row": _count(row["found"]["row"] for row in added),
                  "by_op": _count(row["found"]["op"] for row in added), "by_scope": _count(("full" if "slots" in row["gold"] else "op") for row in added)},
        "gaps": {"lines": total["gap"], "ops": len(gap_rows), "by_kind": kind_lines(gap_rows),
                 "by_op": dict(sorted(gap_rows.items())),
                 "decision": "each gap is a request that works today and would stop working: the maintainer accepts it or the catalog gains the operation (a dated entry and its own measurement); it blocks the deletion until then"},
        "private": {"by_set": private, "note": "an item whose line the claimers take as write-form or reminder-form: what OPEN-41-7 lets reach the daily route (M41-5 reports the share)"},
    }


def gaps_bytes(doc: dict) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def outputs(root: Path = ROOT, **kwargs) -> tuple:
    """(cover bytes, gaps bytes)."""
    items, doc = build(root, **kwargs)
    return corpus_bytes(items), gaps_bytes(doc)


def run(out, gaps, root=ROOT, catalog=None, relabelled=None, check=False) -> int:
    cover, gap_bytes = outputs(root, catalog_path=catalog, relabelled_path=relabelled)
    out, gaps = Path(out), Path(gaps)
    if check:
        same = out.is_file() and gaps.is_file() and out.read_bytes() == cover and gaps.read_bytes() == gap_bytes
        print("tier1-cover: " + ("the committed files equal what the claimers give" if same else "the committed files differ from what the claimers give"), file=sys.stderr)
        return 0 if same else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(cover)
    gaps.write_bytes(gap_bytes)
    doc = json.loads(gap_bytes.decode("utf-8"))
    print(f"{sha256_bytes(cover)}  {out}  {doc['added']['items']} items")
    print(f"{sha256_bytes(gap_bytes)}  {gaps}  {doc['gaps']['lines']} gap lines of {doc['gaps']['ops']} operations")
    return 0


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
