"""Offline tests of the effect preset `aside` in skills/mkt-social-copy/scripts/check_script.py: it passes on any role, the hook
included; it is refused a second time in one video, beside a layout on one beat, with emphasis `punch` and with an echo value outside
its list; it counts as a visual for rule 5. Every name, line and figure is fictional."""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "skills/mkt-social-copy/scripts/check_script.py"
PRESETS = REPO / "shared/references/video-presets.json"

spec = importlib.util.spec_from_file_location("check_script_aside_under_test", SCRIPT)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)
VOCAB = cs.load_vocabulary(str(PRESETS))

HEADER = """hook_type: story
title: I almost quit baking
cta_kind: save
"""

# beat 1 is a cold-open aside on the hook; beat 4 is a plain beat a mid-video aside can take
BEATS = """beat: 1
role: hook
line: Honestly, I almost quit baking bread after my fifth flat loaf.
preset: aside
echo: strong

beat: 2
role: setup
line: Every loaf came out dense because I rushed the proof on cold mornings.
on-screen: Rushed the proof
preset: keyword

beat: 3
role: point
line: So I started proofing the dough overnight in the fridge, slow and cold.

beat: 4
role: turn
line: Which, to be fair, took me way too long to figure out.

beat: 5
role: payoff
line: Now I keep baking bread every weekend and the crumb is open and soft every time.
on-screen: Proof overnight
preset: keyword

beat: 6
role: cta
line: Save this for your next bake.
"""

GOOD = HEADER + "\n" + BEATS


def run(block=GOOD, beat_only=False, register="neutral"):
    beats, slots, problems, warnings, extra = cs.check(block, VOCAB, "reel", None, register, "en", set(), beat_only)
    return {"ok": not problems, "beats": beats, "problems": problems, "warnings": warnings, **extra}


def codes(out, key="problems"):
    return {(p["beat"], p["field"], p["code"]) for p in out[key]}


def edit(old, new, block=GOOD):
    assert old in block, old
    return block.replace(old, new, 1)


def test_the_vocabulary_declares_aside_as_the_one_effect_preset():
    aside = VOCAB["presets"]["aside"]
    assert aside["kind"] == "effect" and aside["main"] == "label"
    assert aside["params"]["echo"] == {"type": "choice", "values": ["light", "strong"], "default": "light"}
    assert aside["params"]["label"]["type"] == "text" and aside["params"]["label"]["max"] == 40 and not aside["params"]["label"].get("required")
    assert [n for n, p in VOCAB["presets"].items() if p["kind"] == "effect"] == ["aside"]


def test_an_aside_on_the_hook_passes():
    out = run()
    assert out["ok"], out["problems"]
    assert out["mode"] == "v2" and out["beats"][0]["preset"] == "aside" and out["beats"][0]["role"] == "hook"


def test_an_aside_mid_video_with_a_label_and_the_default_echo_passes():
    block = edit("preset: aside\necho: strong\n", "")
    block = edit("line: Which, to be fair, took me way too long to figure out.\n",
                 "line: Which, to be fair, took me way too long to figure out.\non-screen: not my finest hour\npreset: aside\n", block)
    out = run(block)
    assert out["ok"], out["problems"]
    assert out["beats"][3]["preset"] == "aside" and out["beats"][3]["on_screen"] == "not my finest hour"


def test_a_second_aside_in_the_same_video_is_refused():
    block = edit("line: Which, to be fair, took me way too long to figure out.\n",
                 "line: Which, to be fair, took me way too long to figure out.\npreset: aside\n")
    out = run(block)
    assert not out["ok"] and (4, "preset", "effect_repeated") in codes(out)
    assert not any(p["beat"] == 1 and p["code"] == "effect_repeated" for p in out["problems"])   # the first one stands


def test_beat_only_checks_one_beat_and_does_not_count_asides():
    out = run(edit("line: Which, to be fair, took me way too long to figure out.\n",
                   "line: Which, to be fair, took me way too long to figure out.\npreset: aside\n"), beat_only=True)
    assert not any(p["code"] == "effect_repeated" for p in out["problems"]), out["problems"]


@pytest.mark.parametrize("layout", ["preset: cutaway\nasset: a photo of the flat loaf", "preset: pip\nasset: a photo of the flat loaf"])
def test_an_aside_with_a_layout_on_one_beat_is_refused(layout):
    out = run(edit("preset: aside\necho: strong\n", "preset: aside\n" + layout + "\n"))
    assert not out["ok"]
    assert (1, "preset", "effect_with_layout") in codes(out) and (1, "preset", "duplicate_field") in codes(out)


def test_a_layout_written_first_and_an_aside_second_is_refused_the_same_way():
    out = run(edit("preset: aside\necho: strong\n", "preset: cutaway\nasset: a photo of the flat loaf\npreset: aside\n"))
    assert (1, "preset", "effect_with_layout") in codes(out)


def test_an_aside_with_an_overlay_preset_is_one_preset_too_many_but_not_a_layout():
    out = run(edit("preset: aside\necho: strong\n", "preset: aside\npreset: keyword\n"))
    assert (1, "preset", "duplicate_field") in codes(out) and not any(p["code"] == "effect_with_layout" for p in out["problems"])


@pytest.mark.parametrize("value", ["medium", "Strong", "heavy", ""])
def test_an_echo_outside_its_list_is_refused(value):
    out = run(edit("echo: strong", "echo: " + value))
    assert not out["ok"] and (1, "echo", "bad_value") in codes(out)


def test_an_undeclared_parameter_on_an_aside_is_refused():
    out = run(edit("echo: strong", "echo: strong\ntransition: fade"))
    assert (1, "transition", "undeclared_parameter") in codes(out)


def test_a_label_over_40_characters_is_refused():
    out = run(edit("echo: strong", "echo: strong\non-screen: " + "x" * 41))
    assert (1, "on-screen", "text_too_long") in codes(out)


def test_an_aside_with_a_punch_on_the_same_beat_is_refused_in_every_mode():
    block = edit("preset: aside\necho: strong\n", "preset: aside\nemphasis: punch\n")
    assert (1, "emphasis", "effect_with_punch") in codes(run(block))
    assert (1, "emphasis", "effect_with_punch") in codes(run(block, beat_only=True))


def test_a_punch_on_another_beat_is_fine():
    out = run(edit("line: So I started proofing the dough overnight in the fridge, slow and cold.\n",
                   "line: So I started proofing the dough overnight in the fridge, slow and cold.\nemphasis: punch\n"))
    assert out["ok"], out["problems"]


def test_an_aside_counts_as_a_visual_event_for_rule_5():
    # without the keyword of beat 2, beats 2 to 4 hold 38 words with nothing drawn: a visual gap from beat 2
    plain = edit("on-screen: Rushed the proof\npreset: keyword\n", "")
    assert (2, "line", "visual_gap") in codes(run(plain), "warnings")
    # with the hook's aside moved to beat 3 (a keyword on the hook), it breaks the run as a preset or a punch does: 13 words
    # before it, 12 after, neither over 15
    with_aside = edit("line: So I started proofing the dough overnight in the fridge, slow and cold.\n",
                      "line: So I started proofing the dough overnight in the fridge, slow and cold.\npreset: aside\n",
                      edit("preset: aside\necho: strong\n", "on-screen: Almost quit baking\npreset: keyword\n", plain))
    out = run(with_aside)
    assert out["ok"], out["problems"]
    assert not any(w["code"] == "visual_gap" for w in out["warnings"]), out["warnings"]


def test_a_legacy_script_with_two_asides_is_still_refused():
    legacy = "\n\n".join(chunk for chunk in BEATS.split("\n\n"))
    legacy = "\n".join(ln for ln in legacy.splitlines() if not ln.startswith("role:"))
    legacy = edit("line: Which, to be fair, took me way too long to figure out.\n",
                  "line: Which, to be fair, took me way too long to figure out.\npreset: aside\n", legacy)
    out = run(legacy)
    assert out["mode"] == "legacy" and (4, "preset", "effect_repeated") in codes(out)


def test_an_aside_is_not_allowed_in_an_image_format():
    beats, slots, problems, warnings, extra = cs.check("beat: 1\nline: A plain caption for one picture.\npreset: aside\n", VOCAB, "static",
                                                        None, "neutral", "en", None, False)
    assert {"beat": 1, "field": "preset", "code": "not_in_image_format"} in problems
