"""The tier-1 cover set of S41-11 (PR 1): `evals/interpreter/tier1-cover-v1.jsonl` and `tier1-cover-gaps.json`, built by `python3 scripts/interpreter_corpus.py tier1-cover` from today's code claimers.

What is checked, with this test's own literals and its own readers of the raw files: every item is well formed (the corpus tool's `check` against the served catalog and the pipeline's `item_problems`);
every gold slot value is a substring of its line (digits written as digits), so the rule cannot invent a span; the ids are the tier-1 range of the relabelled author and the lines add nothing
`dev-relabelled.jsonl` already covers; a fixed table of lines lands where the rule says (an item with its gold, or a gap with its class); the gaps file is internally consistent (every taken line is a
gap, covered or an added item; the counts equal a recount of the items; every gap operation is in the served `refused` list and none in its `ops`); the files are pinned by hash (their builder is deleted); and, at 0 calls, the pipeline decides 7 of the added items before any model unless its stage 3 is switched off, which is how M41-5 must run (README of
evals/interpreter/, "The tier-1 cover set"). Every guard has a vacuity case that fails on a planted wrong result. Offline, no model, no network.

PR 2a of S41-11 deleted the builder with the claimers it ran: the two files are frozen data (pinned by hash below), and the byte-for-byte test and the planted-claimer cases went with it; the other checks stay.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_tier1_cover.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

import pytest

import standin_tree as st

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
COVER = FOLDER / "tier1-cover-v1.jsonl"
GAPS = FOLDER / "tier1-cover-gaps.json"
RELABELLED = FOLDER / "dev-relabelled.jsonl"
CATALOG = ROOT / "runtime" / "interpreter_catalog.json"
ID = re.compile(r"^dev-(pt-br|en|es|fr|de|it|ja|mx)-(4[0-9]{4})$")
LANG_PART = {"pt-BR": "pt-br", "en": "en", "es": "es", "fr": "fr", "de": "de", "it": "it", "ja": "ja", "mixed": "mx"}
# the thirteen operations of the served catalog's `refused` list that today's forms take (the addendum's own measure), and the number of lines the rule found at this commit
GAP_OPS = {"approve": "D", "reject": "D", "release": "D", "go-ahead": "D", "give-consent": "G", "config": "G", "accept-config": "G", "deps": "G", "routine-approve": "G", "set-mode": "G",
           "set-model": "G", "source-add": "G", "source-import": "G"}
STAGE_3_DECIDES = 133      # the added items the pipeline's stage 3 (`natural.match`) decides before any model


def rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tool(name: str):
    """A file of scripts/ loaded by path (scripts/ is tooling: never imported from runtime/ code)."""
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def items():
    return rows(COVER)


@pytest.fixture(scope="module")
def gaps():
    return json.loads(GAPS.read_text(encoding="utf-8"))


def span_problems(item: dict) -> list:
    """This test's own reader: each slot value of an op gold is a piece of the line (an integer slot: digits written in it as a number)."""
    out = []
    gold = item["gold"]
    for slot, values in (gold.get("slots") or {}).items():
        for value in values:
            if not isinstance(value, str) or not value.strip() or value not in item["line"]:
                out.append(f"{item['id']}.{slot}: not in the line")
            elif re.fullmatch(r"[0-9]+", value) and not re.search(r"(?<![0-9])" + value + r"(?![0-9])", item["line"]):
                out.append(f"{item['id']}.{slot}: not a number of the line")
    return out


def accounting_problems(doc: dict) -> list:
    """This test's own reader of the gaps file: the accounting rule and the sums."""
    out = []
    total = {key: 0 for key in ("lines", "taken", "gap", "covered", "added")}
    for source, row in doc["universe"]["sources"].items():
        if row["taken"] != row["gap"] + row["covered"] + row["added"]:
            out.append(f"{source}: taken is not gap + covered + added")
        if row["taken"] > row["lines"]:
            out.append(f"{source}: more taken lines than lines")
        for key in total:
            total[key] += row[key]
    if {key: doc["universe"]["total"][key] for key in total} != total:
        out.append("the total is not the sum of the sources")
    if doc["gaps"]["lines"] != doc["universe"]["total"]["gap"] or sum(g["lines"] for g in doc["gaps"]["by_op"].values()) != doc["gaps"]["lines"]:
        out.append("the gap lines do not add up")
    for op, row in doc["gaps"]["by_op"].items():
        if sum(row["by_lang"].values()) != row["lines"] or sum(row["rows"].values()) != row["lines"]:
            out.append(f"{op}: by_lang or rows do not add up")
    return out


# --- the items ------------------------------------------------------------------------------------------------------------------------------

def test_every_item_is_well_formed_against_the_served_catalog_and_the_pipeline(items):
    format_ = tool("interpreter_corpus_format")
    pipeline = st.load("interpreter_pipeline")
    assert len(items) == 199
    assert format_.check_items(items, format_.load_catalog(CATALOG)) == []
    assert [i["id"] for i in items if pipeline.item_problems(i)] == []
    raw = COVER.read_text(encoding="utf-8").splitlines()
    assert raw == [json.dumps(i, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for i in items], "canonical, one object a line"
    ids = [i["id"] for i in items]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    for item in items:
        match = ID.match(item["id"])
        assert match and match.group(1) == LANG_PART[item["lang"]], item["id"]
        assert item["author"] == "relabel" and item["tags"] == ["relabel-op"] and item["hard"] is False and item["frame"] is None and item["also"] == []
        assert item["channel"] == "messaging" and item["forwarded"] is False and item["split"] == "dev"
        assert item["gold"]["outcome"] == "op" and "\n" not in item["line"] and item["line"].strip() == item["line"]


def test_the_ids_are_the_cover_range_of_the_relabelled_author_and_no_other_author_may_use_it():
    format_ = tool("interpreter_corpus_format")
    cat = format_.load_catalog(CATALOG)
    base = rows(COVER)[0]
    assert format_.item_problems(base, cat) == []
    assert any("id: 10000-49999" in p for p in format_.item_problems(dict(base, id="dev-en-50001"), cat)), "a relabelled id past the range"
    assert any("id: 10000-49999" in p for p in format_.item_problems(dict(base, author="opus"), cat)), "another author inside the range"
    old = rows(RELABELLED)[0]
    assert format_.item_problems(old, cat) == [], "the three older ranges still hold"


def test_every_gold_span_is_a_piece_of_its_line_so_the_rule_invents_none(items):
    full = [i for i in items if "slots" in i["gold"]]
    assert len(full) == 36 and all(set(i["gold"]) == {"outcome", "op", "slots"} for i in full)
    assert [p for i in items for p in span_problems(i)] == []
    assert all(set(i["gold"]) == {"outcome", "op", "scope"} and i["gold"]["scope"] == "op" for i in items if "slots" not in i["gold"])


def test_vacuity_a_planted_span_that_is_not_in_the_line_is_reported(items):
    full = next(i for i in items if "slots" in i["gold"])
    wrong = copy.deepcopy(full)
    wrong["gold"]["slots"] = {"id": ["99"]}
    assert span_problems(wrong) != []
    partial = copy.deepcopy(full)
    partial["line"] = "cancela o pedido 33"
    partial["gold"]["slots"] = {"id": ["3"]}
    assert span_problems(partial) != [], "the digit 3 is inside 33, not a number of the line"


def test_no_line_the_relabelled_corpus_already_covers_is_added_again(items):
    covered = {}
    for item in rows(RELABELLED):
        if item["frame"] is None:
            covered.setdefault(item["line"], []).append(item)
    for item in items:
        for old in covered.get(item["line"], []):
            same_op = old["gold"]["outcome"] == "op" and old["gold"].get("op") == item["gold"]["op"]
            reminder = item["gold"]["op"] == "remind" and old["gold"].get("scope") == "time"
            assert not (same_op or reminder), item["id"]


def test_a_fixed_table_of_lines_lands_where_the_rule_says(items, gaps):
    by_line = {i["line"]: i for i in items}
    # a closed form with the integer: the full gold names the one slot of the operation
    assert by_line["cancela o pedido 3"]["gold"] == {"outcome": "op", "op": "cancel", "slots": {"id": ["3"]}}
    assert by_line["cancel request 3"]["lang"] == "en" and by_line["cancela o pedido 3"]["lang"] == "pt-BR"
    # a closed form with no slot, an operation with optional slots, a write and a help line: the operation alone
    assert by_line["what files do you have?"]["gold"] == {"outcome": "op", "op": "sources", "scope": "op"}
    assert by_line["mostra minha agenda"]["gold"] == {"outcome": "op", "op": "items", "scope": "op"}
    assert by_line["muda para as 10h"]["gold"] == {"outcome": "op", "op": "event-change", "scope": "op"}
    assert by_line["ajuda"]["gold"] == {"outcome": "op", "op": "commands", "scope": "op"}
    # a decision and a consent are taken by code today and refused by the served catalog: gaps, never items
    for line in ("aprova o 1", "approve request 7", "rejeite a pergunta 25", "dou meu consentimento", "give my consent"):
        assert line not in by_line, line
    assert gaps["gaps"]["by_op"]["approve"]["class"] == "D" and gaps["gaps"]["by_op"]["give-consent"]["class"] == "G"


# --- the gap list and the accounting --------------------------------------------------------------------------------------------------------

def test_the_gap_list_is_the_thirteen_refused_operations_and_none_is_absent(gaps):
    served = json.loads(CATALOG.read_text(encoding="utf-8"))
    refused = {row["op"]: row["class"] for row in served["refused"]}
    offered = {row["op"] for row in served["ops"]}
    assert {op: row["class"] for op, row in gaps["gaps"]["by_op"].items()} == GAP_OPS
    assert all(refused[op] == cls and op not in offered for op, cls in GAP_OPS.items())
    assert gaps["gaps"]["by_kind"] == {"refused": 58} and gaps["gaps"]["lines"] == 58 and gaps["gaps"]["ops"] == 13
    assert gaps["catalog"]["v"] == 2 and served["v"] == 3 and gaps["catalog"]["ops"] == 70 == len(served["ops"]) - 1 and gaps["catalog"]["refused"] == 21 == len(served["refused"]), "the frozen gap list was drawn on the catalog of version 2; version 3 adds one served read (mail-ask) and no refused operation"
    assert {row["kind"] for row in gaps["gaps"]["by_op"].values()} == {"refused"}


def test_every_taken_line_is_a_gap_covered_or_an_added_item_and_the_counts_are_the_items(items, gaps):
    assert accounting_problems(gaps) == []
    assert gaps["added"]["items"] == len(items) == gaps["universe"]["total"]["added"]
    count = lambda values: {k: values.count(k) for k in sorted(set(values))}  # noqa: E731
    assert gaps["added"]["by_lang"] == count([i["lang"] for i in items])
    assert gaps["added"]["by_op"] == count([i["gold"]["op"] for i in items])
    assert gaps["added"]["by_scope"] == count(["full" if "slots" in i["gold"] else "op" for i in items])
    assert sum(gaps["added"]["by_row"].values()) == len(items)
    served_ops = {row["op"] for row in json.loads(CATALOG.read_text(encoding="utf-8"))["ops"]}
    assert set(gaps["added"]["by_op"]) <= served_ops


def test_vacuity_a_planted_count_that_does_not_add_up_is_reported(gaps):
    wrong = copy.deepcopy(gaps)
    wrong["universe"]["sources"]["entry"]["added"] += 1
    assert accounting_problems(wrong) != []
    wrong = copy.deepcopy(gaps)
    wrong["gaps"]["by_op"]["approve"]["lines"] += 1
    assert accounting_problems(wrong) != []
    wrong = copy.deepcopy(gaps)
    wrong["universe"]["total"]["lines"] += 1
    assert accounting_problems(wrong) != []


def test_the_private_share_is_counted_per_set_for_the_two_files_m41_5_measures(items, gaps):
    by_set = gaps["private"]["by_set"]
    assert set(by_set) == {"dev-relabelled.jsonl", "tier1-cover-v1.jsonl"}
    assert by_set["dev-relabelled.jsonl"]["items"] == 1344 and by_set["tier1-cover-v1.jsonl"]["items"] == len(items)
    for row in by_set.values():
        assert 0 < row["private"] <= row["items"] and sum(row["by_lang"].values()) == row["private"]


# --- the frozen files ---------------------------------------------------------------------------------------------------------------------------

PINNED_HASHES = json.loads((ROOT / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]


def test_the_two_files_are_frozen_data_their_builder_deleted_with_the_claimers():
    """S41-11 PR 2a deleted the builder with the claimers it ran: the two files are data now, pinned by hash (a change is a reviewed new version of the file, never an edit), and the verb is gone."""
    import hashlib
    assert hashlib.sha256(COVER.read_bytes()).hexdigest() == PINNED_HASHES["interpreter_tier1_cover_v1"]
    assert hashlib.sha256(GAPS.read_bytes()).hexdigest() == PINNED_HASHES["interpreter_tier1_cover_gaps"]
    assert not (ROOT / "scripts" / "interpreter_corpus_tier1.py").exists(), "the builder is deleted"
    assert "tier1-cover" not in (ROOT / "scripts" / "interpreter_corpus.py").read_text(encoding="utf-8").split("Items are one canonical JSON object", 1)[0], "the verb is not listed any more"


def test_vacuity_a_changed_byte_is_not_the_pinned_file():
    import hashlib
    assert hashlib.sha256(COVER.read_bytes().replace(b"cancel", b"cancle", 1)).hexdigest() != PINNED_HASHES["interpreter_tier1_cover_v1"]


# --- M41-5 ran with stage 3 off ----------------------------------------------------------------------------------------------------------------

STAGE_3_DECIDES = 7      # after S41-11 PR 2a stage 3 reads only the decisions said in words (the D operations) and the help form: 7 of the added items, none of the relabelled ones


def test_stage_3_of_the_pipeline_decides_only_the_closed_decisions_before_the_model_and_nothing_when_it_is_switched_off(items, monkeypatch):
    pipeline = st.load("interpreter_pipeline")
    relabelled = rows(RELABELLED)
    assert [i["id"] for i in relabelled if pipeline.pre_model(i) is not None] == [], "no relabelled item is decided before the model"
    decided = [i["id"] for i in items if (pipeline.pre_model(i) or {}).get("stage") == "tier1"]
    assert len(decided) == STAGE_3_DECIDES, decided
    monkeypatch.setattr(pipeline, "_tier1", lambda line: None)          # the one switch the maintainer's M41-5 script set, in its own process
    assert [i["id"] for i in items + relabelled if pipeline.pre_model(i) is not None] == [], "with stage 3 off every item reaches the model"
