"""Offline tests of the `split` layout preset in skills/mkt-social-copy/scripts/check_script.py: the vocabulary entry, the checker's rules
for its parameters, its place in the whole-script rules and the prose that lists it. Every name, line and figure is fictional."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "skills/mkt-social-copy/scripts/check_script.py"
PRESETS = REPO / "shared/references/video-presets.json"
PRESETS_MD = REPO / "shared/references/video-presets.md"
SCRIPT_DOC = REPO / "skills/mkt-social-copy/references/video-script.md"

spec = importlib.util.spec_from_file_location("check_script_split_under_test", SCRIPT)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)
VOCAB = cs.load_vocabulary(str(PRESETS))

HEADER = """hook_type: number
title: Habits cut my spending
cta_kind: send
send_to: a friend who wants to save
pattern: list
"""

BEATS = """beat: 1
role: hook
line: 3 habits cut my spending by 340 euros in one month.
on-screen: Habits cut spending
preset: keyword

beat: 2
role: setup
line: I tracked every euro I spent for thirty days in a plain notebook.

beat: 3
role: point
line: First, name every euro on the first of the month so each one has a job.
on-screen: Name | Review | Cancel
preset: list

beat: 4
role: point
line: Second, review the plan for ten minutes every Sunday and move what is left over.

beat: 5
role: point
line: Third, cancel one subscription a month, starting with the one you forgot you had.

beat: 6
role: proof
line: Together those habits saved me 340 euros, and the month felt calmer.
on-screen: euros saved in one month
preset: number
value: 340

beat: 7
role: payoff
line: Small habits cut my spending because each one removes a decision I used to avoid.

beat: 8
role: cta
line: Send this to a friend who wants to spend with intention.
"""

GOOD = HEADER + "\n" + BEATS
MATERIAL = {"3", "340"}

SPLIT_BEAT = ("beat: 1\nrole: proof\nline: Here is the receipt next to my notes, and you can see the total drop.\n"
              "on-screen: The receipt\npreset: split\nasset: a photo of the grocery receipt beside the notebook\nside: bottom\nfit: cover\n")


def run(block, fmt="reel", register="neutral", language="en", figures=None, beat_only=False):
    beats, slots, problems, warnings, extra = cs.check(block, VOCAB, fmt, None, register, language, figures, beat_only)
    return {"ok": not problems, "beats": beats, "slots": slots, "problems": problems, "warnings": warnings, **extra}


def has(out, beat, field, code, key="problems"):
    return (beat, field, code) in {(p["beat"], p["field"], p["code"]) for p in out[key]}


def test_the_split_entry_is_the_one_the_request_names_and_has_the_shape_of_the_other_layouts():
    split, cutaway, pip = (VOCAB["presets"][n] for n in ("split", "cutaway", "pip"))
    assert split["kind"] == "layout" and split["main"] == "label"
    assert split["summary"] == ("the frame splits in two: the speaker stays in one half while a picture or a clip the person uploads "
                                "fills the other half")
    assert list(split["params"]) == ["asset", "side", "fit", "label"]
    assert split["params"]["side"] == {"type": "choice", "values": ["top", "bottom", "left", "right"], "default": "bottom"}
    assert split["params"]["asset"] == cutaway["params"]["asset"] == pip["params"]["asset"]
    assert split["params"]["label"] == cutaway["params"]["label"] == pip["params"]["label"]
    assert split["params"]["fit"] == cutaway["params"]["fit"]
    assert set(split) == set(cutaway) == set(pip)
    assert json.loads(PRESETS.read_text(encoding="utf-8"))["version"] == 2


def test_a_valid_split_beat_passes_and_lists_its_slot():
    out = run(SPLIT_BEAT, beat_only=True)
    assert out["ok"] and out["problems"] == []
    assert out["beats"][0]["preset"] == "split" and out["beats"][0]["on_screen"] == "The receipt"
    assert out["slots"] == [{"beat": 1, "param": "asset", "type": "image|clip",
                             "description": "a photo of the grocery receipt beside the notebook"}]


@pytest.mark.parametrize("side", ["top", "bottom", "left", "right", None])
def test_every_side_and_the_defaults_pass(side):
    if side is None:
        block = SPLIT_BEAT.replace("side: bottom\n", "").replace("fit: cover\n", "")
    else:
        block = SPLIT_BEAT.replace("side: bottom", "side: " + side)
    out = run(block, beat_only=True)
    assert out["ok"] and out["problems"] == [], out["problems"]


def test_a_split_beat_without_an_asset_is_refused():
    out = run(SPLIT_BEAT.replace("asset: a photo of the grocery receipt beside the notebook\n", ""), beat_only=True)
    assert not out["ok"] and has(out, 1, "asset", "missing_parameter")


@pytest.mark.parametrize("asset, code", [
    ("see shots.example", "slot_link"),
    ("www.chart.org", "slot_link"),
    ("file:dashboard", "slot_link"),
    ("https://shots.example/chart", "slot_path"),
])
def test_a_link_or_a_path_in_the_asset_is_refused(asset, code):
    out = run(SPLIT_BEAT.replace("a photo of the grocery receipt beside the notebook", asset), beat_only=True)
    assert not out["ok"] and has(out, 1, "asset", code)


@pytest.mark.parametrize("value", ["middle", "center", "Top"])
def test_a_side_outside_the_list_is_refused(value):
    out = run(SPLIT_BEAT.replace("side: bottom", "side: " + value), beat_only=True)
    assert not out["ok"] and has(out, 1, "side", "bad_value")


def test_a_label_over_40_characters_is_refused():
    out = run(SPLIT_BEAT.replace("on-screen: The receipt", "on-screen: " + "x" * 41), beat_only=True)
    assert not out["ok"] and has(out, 1, "on-screen", "text_too_long")
    out = run(SPLIT_BEAT.replace("on-screen: The receipt", "on-screen: " + "x" * 40), beat_only=True)
    assert out["ok"], out["problems"]


def test_the_label_is_written_once_and_fit_is_closed():
    out = run(SPLIT_BEAT + "label: The receipt\n", beat_only=True)
    assert has(out, 1, "label", "main_parameter_written_twice")
    out = run(SPLIT_BEAT.replace("fit: cover", "fit: stretch"), beat_only=True)
    assert has(out, 1, "fit", "bad_value")


def test_a_time_in_the_asset_is_refused_as_for_every_slot():
    out = run(SPLIT_BEAT.replace("a photo of the grocery receipt beside the notebook", "the first 5 seconds of my demo"), beat_only=True)
    assert has(out, 1, "asset", "time_value")


def test_the_split_example_of_the_script_reference_passes():
    text = SCRIPT_DOC.read_text(encoding="utf-8")
    m = re.search(r"^Example of a `split` beat.*\n\n```\n(.*?)```", text, re.S | re.M)
    assert m, "the example block is missing"
    out = run(m.group(1).replace("beat: 4", "beat: 1"), beat_only=True)
    assert out["ok"] and out["problems"] == [], out["problems"]
    assert out["beats"][0]["preset"] == "split"


def test_the_prose_lists_split_among_the_layouts():
    md, doc = PRESETS_MD.read_text(encoding="utf-8"), SCRIPT_DOC.read_text(encoding="utf-8")
    assert "(`cutaway`, `pip`, `split`)" in md and "(`cutaway`, `pip`, `split`)" in doc
    assert "### split\n" in md


SPLIT_LINES = "preset: split\nasset: a photo of the weekly budget sheet\nside: right\n"


def test_a_split_beat_is_a_visual_event_for_rule_5():
    out = run(GOOD, figures=MATERIAL)
    assert has(out, 4, "line", "visual_gap", "warnings")
    edited = GOOD.replace("beat: 4\nrole: point\n", "beat: 4\nrole: point\n" + SPLIT_LINES, 1)
    assert edited != GOOD
    out = run(edited, figures=MATERIAL)
    assert out["ok"], out["problems"]
    assert not has(out, 4, "line", "visual_gap", "warnings") and not has(out, 5, "line", "visual_gap", "warnings")


def test_split_beats_count_toward_the_preset_share():
    ins = "preset: split\nasset: a photo of the budget notebook\n"
    block = GOOD.replace("role: setup\n", "role: setup\n" + ins, 1)
    block = block.replace("role: point\nline: Second", "role: point\n" + ins + "line: Second", 1)
    block = block.replace("role: point\nline: Third", "role: point\n" + ins + "line: Third", 1)
    block = block.replace("role: payoff\n", "role: payoff\n" + ins, 1)
    block = block.replace("role: cta\n", "role: cta\n" + ins, 1)
    assert block.count("preset: split") == 5
    out = run(block, figures=MATERIAL)
    assert has(out, None, "preset", "preset_overused")


CALM_SCRIPT = HEADER + """
beat: 1
role: hook
line: 3 habits cut my spending by 340 euros in one month.
on-screen: Habits cut spending
preset: keyword

beat: 2
role: point
line: First, name every euro on the first of the month.
on-screen: Name | Review | Cancel
preset: list

beat: 3
role: point
line: Second, review the plan for ten minutes every Sunday.
preset: split
asset: a photo of the weekly budget sheet
side: right

beat: 4
role: point
line: Third, cancel one subscription you forgot you had.

beat: 5
role: proof
line: Together those habits saved me 340 euros.
on-screen: euros saved in one month
preset: number
value: 340

beat: 6
role: payoff
line: Small habits cut my spending because each removes a decision.

beat: 7
role: cta
line: Send this to a friend who wants to save.
"""


def test_split_counts_in_the_calm_density():
    lines = re.findall(r"^line: (.*)$", CALM_SCRIPT, re.M)
    total = sum(len(cs.words(t)) for t in lines)
    assert total == 64 and max(1, total // 20) == 3          # 3 presets allowed in a calm script of 64 words
    out = run(CALM_SCRIPT, register="calm", figures=MATERIAL)
    assert has(out, None, "preset", "calm_preset_density")   # keyword, list, split, number: 4 > 3
    without = CALM_SCRIPT.replace("preset: split\nasset: a photo of the weekly budget sheet\nside: right\n", "")
    assert without != CALM_SCRIPT
    out = run(without, register="calm", figures=MATERIAL)
    assert not has(out, None, "preset", "calm_preset_density")   # 3 presets: within the limit, so the split is what tips it
