"""The development set of the measurement of "the model sees the card" (package card-model-sees): evals/interpreter/card-model-dev-v1.jsonl.

96 fictional lines the maintainer's harness (outside the repository, ix-card-model.py) sends with a card in view and grades against a gold. This file holds the form and the counts the specification
asks for, and nothing about any model: the set is dev evidence (tuning is done against it, never against the blind set), and no model's answer is here. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_card_model_dev_set.py
"""
from __future__ import annotations

import collections
import copy
import datetime
import json
from pathlib import Path

import pytest

SET = Path(__file__).resolve().parents[2] / "evals" / "interpreter" / "card-model-dev-v1.jsonl"
LANGS = {"pt-BR": 40, "en": 24, "es": 8, "fr": 8, "de": 8, "it": 8}
GROUPS = {"title": 18, "time": 13, "day": 11, "place": 9, "duration": 9, "mixed": 6, "another": 6, "other": 7, "none": 4, "bait": 6, "reminder": 5, "newevent": 2}
STAMP = "%Y-%m-%dT%H:%M"
REPORT = ["Mude o titulo para: ", "Mude o titulo para ", "Mude o título para: ", "muda o título para ", "muda o titulo para: ", "troque o nome para ", "troque o nome para: "]      # validate: allow english-only -- the lines of the report


def items():
    return [json.loads(raw) for raw in SET.read_text(encoding="utf-8").splitlines() if raw.strip()]


def problems(rows):
    """What is wrong with the set's form (the same reading the harness makes of any set, blind included)."""
    out = []
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids):
        out.append("an id twice")
    if dict(collections.Counter(r.get("lang") for r in rows)) != LANGS:
        out.append("languages")
    if dict(collections.Counter(r.get("group") for r in rows)) != GROUPS:
        out.append("groups")
    for r in rows:
        for key in ("id", "lang", "group", "clock", "zone", "card", "line", "gold"):
            if key not in r:
                out.append(f"{r.get('id')}: no {key}")
        if out and out[-1].startswith(str(r.get("id"))):
            continue
        for stamp in (r["clock"], r["card"]["start"], r["card"]["end"], *[r["gold"][k] for k in ("start", "end") if k in r["gold"]]):
            try:
                datetime.datetime.strptime(stamp, STAMP)
            except ValueError:
                out.append(f"{r['id']}: {stamp} is not a local moment")
        if r["gold"].get("kind") not in ("change", "other") or (r["gold"]["kind"] == "change" and not {"title", "place", "start", "end"} & set(r["gold"])):
            out.append(f"{r['id']}: gold")
        if (r["group"] == "bait") != bool(r.get("bait")):
            out.append(f"{r['id']}: bait words")
    return out


def test_the_set_has_the_counts_the_specification_asks_for_and_a_well_formed_item_each():
    rows = items()
    assert len(rows) == 96 and problems(rows) == []
    assert all(r["zone"] == "America/Sao_Paulo" and r["clock"] == "2026-10-21T15:00" and r["id"].startswith("card-dev-") for r in rows)


def test_the_seven_lines_of_the_report_are_in_the_set_each_tagged_once():
    tagged = [r for r in items() if r.get("tag") == "report7"]
    assert len(tagged) == 7 and all(r["group"] == "title" and r["lang"] == "pt-BR" and r["gold"]["kind"] == "change" for r in tagged)
    assert [r["line"].startswith(prefix) for r, prefix in zip(tagged, REPORT)] == [True] * 7, "the seven shapes of the report, once each, in the order of the report"


def test_every_new_title_or_place_a_gold_names_is_a_piece_of_the_line_or_the_cards_own_text_changed():
    for r in items():
        gold = r["gold"]
        for key, old in (("title", r["card"]["title"]), ("place", r["card"].get("location", ""))):
            if key in gold:
                line = " ".join(r["line"].split())
                assert gold[key] in line or all(word in (line + " " + old).lower() for word in gold[key].lower().split()), (r["id"], key)


def test_a_bait_item_carries_the_bait_it_names_in_its_card():
    for r in items():
        if r["group"] == "bait":
            text = (r["card"]["title"] + " " + r["card"].get("location", "")).lower()
            assert any(word.lower() in text for word in r["bait"]), r["id"]


@pytest.mark.parametrize("plant", ["drop", "duplicate", "language", "stamp", "gold", "bait"])
def test_vacuity_a_planted_wrong_set_is_found(plant):
    rows = copy.deepcopy(items())
    if plant == "drop":
        rows.pop()
    elif plant == "duplicate":
        rows[1]["id"] = rows[0]["id"]
    elif plant == "language":
        rows[0]["lang"] = "en"
    elif plant == "stamp":
        rows[2]["card"]["start"] = "2026-10-24 08:00"
    elif plant == "gold":
        rows[3]["gold"] = {"kind": "change"}
    else:
        next(r for r in rows if r["group"] == "bait").pop("bait")
    assert problems(rows) != []


def test_every_line_that_is_not_a_change_names_the_operations_it_may_get_and_no_real_name_is_in_the_set():
    rows = items()
    others = [r for r in rows if r["gold"]["kind"] == "other"]
    assert len(others) == 27 and all(isinstance(r["gold"].get("ops"), list) for r in others), "an `ops` list on each (24 outside the bait group, 3 inside it), an empty list for a line no operation is right for"
    assert all(r["gold"]["ops"] == [] for r in others if r["group"] == "none") and all(r["gold"]["ops"] == ["event-change"] for r in others if r["group"] == "another")
    assert all(r["gold"]["ops"] == ["remind"] for r in others if r["group"] == "reminder") and all(r["gold"]["ops"] == ["event-create"] for r in others if r["group"] == "newevent")
    text = SET.read_text(encoding="utf-8")
    assert "Matheus" not in text and "Corte de Cabelo" not in text, "principle 8: the name of a real report line is not in the set"


def test_the_set_holds_the_bare_clock_lines_of_the_probe_in_pt_br_and_en():
    rows = {r["id"]: r for r in items()}
    pt = [r for r in rows.values() if r["lang"] == "pt-BR" and r["line"] == "muda para as 9h" and r["card"]["start"].endswith("T19:00")]      # validate: allow english-only -- the line under test
    en = [r for r in rows.values() if r["lang"] == "en" and r["line"] == "move it to 9:30" and r["card"]["start"].endswith("T19:00")]
    assert len(pt) == 1 and len(en) == 1 and pt[0]["gold"]["start"].endswith("T21:00") and en[0]["gold"]["start"].endswith("T21:30"), "an evening card and a clock with no am or pm: the model's reading wins"


def test_the_set_holds_the_six_real_changes_the_closed_list_had_dropped_and_the_reminders_and_new_events_said_while_a_card_waits():
    rows = items()
    lines = {r["line"] for r in rows}
    for line in ("passa para as 14h30", "marca para as 18h", "começa às 9h30", "décale à 14h", "spostalo alle 16:00", "appelle-le Déjeuner équipe et mets-le à 13h"):      # validate: allow english-only -- the lines under test
        assert line in lines, line
    reminders = [r for r in rows if r["group"] == "reminder"]
    assert {r["lang"] for r in reminders} == {"pt-BR", "en"} and len(reminders) == 5 and {r["lang"] for r in rows if r["group"] == "newevent"} == {"pt-BR", "en"}
