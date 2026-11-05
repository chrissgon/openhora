"""The development set of the measurement of "a question about the card" (package ANY-QUESTION Q2): evals/interpreter/card-question-dev-v1.jsonl.

30 fictional lines the maintainer's harness (outside the repository, ix-card-model.py) sends with a card in view and grades against a gold: 20 questions about the card (`when`, `place`, `title`,
`approve`) and 10 lines about something else (the operations the model may name). This file holds the form and the counts the specification asks for, and nothing about any model: the set is dev
evidence written by the specification and not labelled blind (tuning is done against it, never against the blind set), and no model's answer is here. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_card_question_dev_set.py
"""
from __future__ import annotations

import collections
import copy
import datetime
import importlib.util
import json
import re
from pathlib import Path

import pytest

import standin_tree as st
from test_event_revise_flow import (CFG, LIVE, PT, Model, build, card_has, check, create, fresh, haircut_card, new_event_card, open_cards, refused_for_good, revise, status)  # noqa: F401  (`fresh` is autouse: without it the rate of ten a minute answers `pass` after ten tests)
from test_calendar_write import fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import OWNER  # noqa: F401

ops_card_revise = st.load("ops_card_revise")
ops_core = st.load("ops_core")

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
SET = FOLDER / "card-question-dev-v1.jsonl"      # evals/interpreter/card-question-dev-v1.jsonl, named literally so the test selector picks this test when the file changes
MAIN_SET = "question-dev-v1.jsonl"      # the one set whose lines this file may repeat (the main arm of the same measurement)
LANGS = {"pt-BR": 13, "en": 9, "es": 2, "fr": 2, "de": 2, "it": 2}
GROUPS = {"question": 20, "other": 10}
QUESTIONS_BY_LANG = {"pt-BR": 7, "en": 5, "es": 2, "fr": 2, "de": 2, "it": 2}
FIELDS = {"when": 9, "place": 5, "title": 3, "approve": 3}
KEYS = ["id", "lang", "group", "clock", "zone", "card", "line", "gold"]
CARD_KEYS = {"title", "start", "end", "location"}
STAMP = "%Y-%m-%dT%H:%M"
OVERLAP = {"que horas é esse evento?", "o card de ontem foi aprovado?", "você consegue mandar e-mail?", "que dia é hoje?"}      # validate: allow english-only -- the lines under test: the same question with and without a card in view


def tool(name="interpreter_corpus"):
    """A file of the tooling (scripts/ is loaded by path, never imported from runtime/ code)."""
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normal(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def file_rows(path: Path) -> list:
    return [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


def items():
    return file_rows(SET)


CATALOG = tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")


def problems(rows):
    """What is wrong with the set's form (the same reading the harness makes of any set, blind included)."""
    out = []
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids):
        out.append("an id twice")
    if len(rows) != 30:
        out.append("count")
    if dict(collections.Counter(r.get("lang") for r in rows)) != LANGS:
        out.append("languages")
    if dict(collections.Counter(r.get("group") for r in rows)) != GROUPS:
        out.append("groups")
    if dict(collections.Counter(r.get("lang") for r in rows if r.get("group") == "question")) != QUESTIONS_BY_LANG:
        out.append("questions by language")
    if dict(collections.Counter(r["gold"].get("field") for r in rows if r.get("group") == "question")) != FIELDS:
        out.append("fields")
    for r in rows:
        if list(r) != KEYS:
            out.append(f"{r.get('id')}: keys")
            continue
        if not re.fullmatch(r"card-q-dev-(pt|en|es|fr|de|it)-[0-9]{3}", r["id"]):
            out.append(f"{r['id']}: id")
        if r["clock"] != "2026-10-21T15:00" or r["zone"] != "America/Sao_Paulo":
            out.append(f"{r['id']}: clock or zone")
        if not set(r["card"]) <= CARD_KEYS or not {"title", "start", "end"} <= set(r["card"]):
            out.append(f"{r['id']}: card keys")
            continue
        for stamp in (r["clock"], r["card"]["start"], r["card"]["end"]):
            try:
                datetime.datetime.strptime(stamp, STAMP)
            except ValueError:
                out.append(f"{r['id']}: {stamp} is not a local moment")
        gold = r["gold"]
        if r["group"] == "question":
            if set(gold) != {"kind", "about", "field"} or gold["kind"] != "question" or gold["about"] != "card" or gold["field"] not in FIELDS:
                out.append(f"{r['id']}: question gold")
        elif r["group"] == "other":
            if set(gold) != {"kind", "ops"} or gold["kind"] != "other" or not isinstance(gold["ops"], list) or not all(op in CATALOG["ops"] for op in gold["ops"]):
                out.append(f"{r['id']}: other gold")
        else:
            out.append(f"{r['id']}: group")
    return out


def test_the_set_has_the_counts_the_specification_asks_for_and_a_well_formed_item_each():
    rows_ = items()
    assert len(rows_) == 30 and problems(rows_) == []
    assert dict(collections.Counter(r["lang"] for r in rows_)) == LANGS and dict(collections.Counter(r["group"] for r in rows_)) == GROUPS
    assert dict(collections.Counter(r["lang"] for r in rows_ if r["group"] == "question")) == QUESTIONS_BY_LANG
    assert dict(collections.Counter(r["gold"]["field"] for r in rows_ if r["group"] == "question")) == FIELDS
    assert len({r["id"] for r in rows_}) == 30
    assert all(r["zone"] == "America/Sao_Paulo" and r["clock"] == "2026-10-21T15:00" and list(r) == KEYS for r in rows_)
    assert all(re.fullmatch(r"card-q-dev-(pt|en|es|fr|de|it)-[0-9]{3}", r["id"]) for r in rows_)
    assert all(all(datetime.datetime.strptime(r["card"][k], STAMP) for k in ("start", "end")) for r in rows_)
    assert all(r["id"].split("-")[3] == {"pt-BR": "pt"}.get(r["lang"], r["lang"]) for r in rows_), "an id carries its language"


def test_a_question_gold_is_exactly_kind_about_and_field_an_other_gold_is_kind_and_ops_of_the_catalog_and_the_card_of_yesterday_is_an_other_line():
    rows_ = items()
    for r in rows_:
        gold = r["gold"]
        if r["group"] == "question":
            assert set(gold) == {"kind", "about", "field"} and gold["kind"] == "question" and gold["about"] == "card" and gold["field"] in ("when", "place", "title", "approve"), r["id"]
        else:
            assert set(gold) == {"kind", "ops"} and gold["kind"] == "other" and isinstance(gold["ops"], list), r["id"]
            assert all(op in CATALOG["ops"] for op in gold["ops"]), r["id"]
    yesterday = [r for r in rows_ if r["line"] == "o card de ontem foi aprovado?"]      # validate: allow english-only -- the line under test
    assert len(yesterday) == 1 and yesterday[0]["group"] == "other" and yesterday[0]["gold"] == {"kind": "other", "ops": ["pending", "status"]}


def test_a_place_question_is_on_a_card_with_no_location_and_on_a_card_with_one():
    rows_ = {r["id"]: r for r in items()}
    bare, placed = rows_["card-q-dev-pt-006"], rows_["card-q-dev-pt-002"]
    assert bare["gold"]["field"] == "place" and "location" not in bare["card"]
    assert placed["gold"]["field"] == "place" and placed["card"]["location"] == "Bistrô Ventura"


def test_the_overlap_with_the_main_set_is_exactly_the_four_lines_and_there_is_none_with_any_other_set():
    mine = {normal(r["line"]) for r in items()}
    main = {normal(r["line"]) for r in file_rows(FOLDER / MAIN_SET)}
    assert mine & main == {normal(line) for line in OVERLAP}, "the same question with and without a card in view"
    others = {normal(r["line"]) for path in sorted(FOLDER.glob("*.jsonl")) if path.name not in (SET.name, MAIN_SET) for r in file_rows(path)}
    assert not mine & others, mine & others


def test_every_line_reaches_the_model_on_its_card(world, monkeypatch):
    """`card_revise_check` is the product's own gate before the model: a line it returns None for (a greeting, a state question, a closed form, a reminder) never reaches the prompt, so a gold on it measures nothing."""
    build(world, monkeypatch, None)
    ctx = ops_core.context(world["path"])
    off = []
    for row in items():
        card = row["card"]
        extra = {"location": card["location"]} if card.get("location") else {}
        old, sha = create(world, title=card["title"], start=card["start"], end=card["end"], **extra)
        reaches = ops_card_revise.reaches_event_card(ctx, row["line"], OWNER)
        if reaches is not True or check(world, old, sha, row["line"]) != "event":
            off.append(row["id"])
    assert off == [], off


@pytest.mark.parametrize("plant", ["drop", "duplicate", "field", "op"])
def test_vacuity_a_planted_wrong_set_is_found(plant):
    rows_ = copy.deepcopy(items())
    assert problems(rows_) == []
    if plant == "drop":
        rows_.pop()
    elif plant == "duplicate":
        rows_[1]["id"] = rows_[0]["id"]
    elif plant == "field":
        next(r for r in rows_ if r["group"] == "question")["gold"]["field"] = "price"
    else:
        next(r for r in rows_ if r["group"] == "other")["gold"]["ops"] = ["fly-to-moon"]
    assert problems(rows_) != []
