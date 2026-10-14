"""Offline tests of the script vocabulary version 2 in skills/mkt-social-copy/scripts/check_script.py: the header, the roles,
the eleven rules (each with a passing and a failing script), the warnings, --beat-only, the legacy compatibility and the
equality of the vocabulary's two files for the `script` section. Every name, line and figure is fictional."""
import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "skills/mkt-social-copy/scripts/check_script.py"
PRESETS = REPO / "shared/references/video-presets.json"
PRESETS_MD = REPO / "shared/references/video-presets.md"

spec = importlib.util.spec_from_file_location("check_script_v2_under_test", SCRIPT)
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


def run(block=GOOD, fmt="reel", register="neutral", language="en", figures=MATERIAL, beat_only=False, vocab=None, max_items=None):
    beats, slots, problems, warnings, extra = cs.check(block, vocab or VOCAB, fmt, max_items, register, language, figures, beat_only)
    return {"ok": not problems, "beats": beats, "slots": slots, "problems": problems, "warnings": warnings, **extra}


def codes(out, key="problems"):
    return sorted(((p["beat"], p["field"], p["code"]) for p in out[key]), key=lambda t: (t[0] or 0, t[1], t[2]))


def has(out, beat, field, code, key="problems"):
    return (beat, field, code) in codes(out, key)


def edit(old, new, block=GOOD):
    assert old in block, old
    return block.replace(old, new, 1)


# ---------------------------------------------------------------- a version 2 script passes

def test_a_script_with_a_header_and_roles_passes_and_reports_its_roles():
    out = run()
    assert out["ok"] is True and out["problems"] == [] and out["mode"] == "v2", out
    assert out["header"]["hook_type"] == "number" and out["header"]["title"] == "Habits cut my spending"
    assert [b["role"] for b in out["beats"]] == ["hook", "setup", "point", "point", "point", "proof", "payoff", "cta"]
    assert [b["emphasis"] for b in out["beats"]] == [None] * 8


def test_the_only_warnings_of_the_good_script_are_two_visual_gaps_and_its_length():
    out = run()
    assert codes(out, "warnings") == [(None, "line", "length_short"), (4, "line", "visual_gap"), (7, "line", "visual_gap")]


def test_the_cli_prints_mode_header_roles_and_warnings(tmp_path):
    post = tmp_path / "post.md"
    post.write_text("# Post\n\n```script\n" + GOOD + "```\n", encoding="utf-8")
    material = tmp_path / "material.txt"
    material.write_text("3 habits, 340 euros", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--content", str(post), "--presets", str(PRESETS), "--format", "reel", "--language", "en",
                        "--register", "neutral", "--material", str(material)], capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout)
    assert r.returncode == 0 and out["ok"] and out["mode"] == "v2" and out["header"]["send_to"] == "a friend who wants to save"
    assert out["beats"][0]["role"] == "hook" and any(w["code"] == "length_short" for w in out["warnings"])
    r = subprocess.run([sys.executable, str(SCRIPT), "--content", str(post), "--presets", str(PRESETS), "--figure", "340"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and (1, "line", "invented_figure") in codes(json.loads(r.stdout))   # the 3 of the hook is not among the figures given


# ---------------------------------------------------------------- the header

@pytest.mark.parametrize("old, new, expected", [
    ("pattern: list\n", "pattern: list\nmood: calm\n", (None, "mood", "unknown_header_key")),
    ("pattern: list\n", "pattern: list\npattern: myth\n", (None, "pattern", "duplicate_field")),
    ("hook_type: number\n", "", (None, "hook_type", "missing_header")),
    ("title: Habits cut my spending\n", "", (None, "title", "missing_header")),
    ("cta_kind: send\n", "", (None, "cta_kind", "missing_header")),
    ("send_to: a friend who wants to save\n", "", (None, "send_to", "missing_header")),
    ("hook_type: number", "hook_type: shocking", (None, "hook_type", "bad_value")),
    ("cta_kind: send", "cta_kind: buy", (None, "cta_kind", "bad_value")),
    ("pattern: list", "pattern: ladder", (None, "pattern", "bad_value")),
    ("title: Habits cut my spending", "title: " + "x" * 41, (None, "title", "text_too_long")),
    ("send_to: a friend who wants to save", "send_to: " + "y" * 41, (None, "send_to", "text_too_long")),
    ("title: Habits cut my spending", "title: Habits at 0:12 cut", (None, "title", "time_value")),
])
def test_the_header_is_checked(old, new, expected):
    out = run(edit(old, new))
    assert expected in codes(out) and out["ok"] is False


def test_send_to_without_send_and_a_loop_value_are_checked():
    out = run(edit("cta_kind: send", "cta_kind: save"))
    assert has(out, None, "send_to", "send_to_without_send")
    out = run(edit("cta_kind: send", "cta_kind: save").replace("send_to: a friend who wants to save\n", ""))
    assert out["ok"] is True
    assert has(run(HEADER.replace("pattern: list", "loop: maybe") + "\n" + BEATS), None, "loop", "bad_value")
    assert run(HEADER.replace("pattern: list\n", "loop: no\n") + "\n" + BEATS)["ok"] is True


def test_the_header_is_for_a_video_not_for_images():
    out = run("title: One two three\n\nbeat: 1\nline: A slide of text.\n", fmt="carousel")
    assert has(out, None, "header", "header_in_image_format") and out["mode"] == "images"


def test_a_header_value_with_a_forbidden_character_is_refused_and_not_echoed():
    out = run(edit("title: Habits cut my spending", "title: Habits\u200b cut my spending"))
    assert any(p["code"] == "forbidden_character" for p in out["problems"]) and "Habits" not in json.dumps(out["problems"])


# ---------------------------------------------------------------- roles and emphasis

def test_role_and_emphasis_are_closed_values():
    out = run(edit("role: setup", "role: intro"))
    assert has(out, 2, "role", "bad_value")
    out = run(edit("role: hook", "emphasis: loud\nrole: hook"))
    assert has(out, 1, "emphasis", "bad_value")
    assert run(edit("role: hook", "emphasis: none\nrole: hook"))["ok"] is True
    for field in ("role", "emphasis"):
        assert field in cs.RESERVED


def test_every_beat_of_a_version_2_script_has_a_role_and_beat_1_is_the_hook():
    assert has(run(edit("role: setup\n", "")), 2, "role", "missing_role")
    assert has(run(edit("role: hook", "role: setup")), 1, "role", "first_beat_not_hook")
    assert has(run(edit("role: setup", "role: hook")), 2, "role", "hook_not_first")


def test_a_role_in_an_image_script_is_not_in_the_image_format():
    out = run("beat: 1\nrole: hook\nline: A slide.\n", fmt="carousel")
    assert has(out, 1, "role", "not_in_image_format")


# ---------------------------------------------------------------- rule 1: open with the promise

def test_rule_1_the_hook_has_at_most_18_words():
    long_hook = "3 habits cut my spending by 340 euros in one month and I can show every single one of them here today."
    assert len(long_hook.split()) > 18
    assert has(run(edit("3 habits cut my spending by 340 euros in one month.", long_hook)), 1, "line", "hook_too_long")
    at_limit = "3 habits cut my spending by 340 euros in one month and I can show all of them."
    assert len(at_limit.split()) == 18
    assert not has(run(edit("3 habits cut my spending by 340 euros in one month.", at_limit)), 1, "line", "hook_too_long")


@pytest.mark.parametrize("opener", ["Hey everyone, 3 habits cut my spending by 340 euros.", "Welcome back, 3 habits cut my spending by 340 euros.",
                                    "Today I show 3 habits that cut my spending by 340 euros.", "Hi, 3 habits cut my spending by 340 euros."])
def test_rule_1_a_hook_does_not_start_with_an_opener_phrase(opener):
    out = run(edit("3 habits cut my spending by 340 euros in one month.", opener))
    assert has(out, 1, "line", "hook_opener")


def test_rule_1_without_a_language_the_word_lists_are_skipped_with_a_warning():
    greeting = "Hey everyone, 3 habits cut my spending by 340 euros."
    out = run(edit("3 habits cut my spending by 340 euros in one month.", greeting), language=None)
    assert not has(out, 1, "line", "hook_opener") and has(out, None, "language", "language_unset", "warnings")
    out = run(edit("3 habits cut my spending by 340 euros in one month.", greeting), language="xx")
    assert has(out, None, "language", "language_data_missing", "warnings")


def test_rule_1_the_language_is_matched_by_code():
    greeting = "Oi pessoal, 3 habitos cortaram meu gasto em 340 euros."
    assert has(run(edit("3 habits cut my spending by 340 euros in one month.", greeting), language="pt-BR"), 1, "line", "hook_opener")
    assert has(run(edit("3 habits cut my spending by 340 euros in one month.", greeting), language="PT"), 1, "line", "hook_opener")
    assert has(run(edit("3 habits cut my spending by 340 euros in one month.", greeting), language="pt_br"), 1, "line", "hook_opener")
    assert not has(run(GOOD, language="en-US"), 1, "line", "hook_opener")


def test_rule_1_a_number_hook_has_a_digit_token_in_its_first_sentence():
    no_digit = "Three habits cut my spending by a lot. It was 340 euros in one month."
    out = run(edit("3 habits cut my spending by 340 euros in one month.", no_digit))
    assert has(out, 1, "line", "hook_type_number")
    assert not has(run(), 1, "line", "hook_type_number")


def test_rule_1_a_question_hook_ends_with_a_question_mark():
    out = run(edit("hook_type: number", "hook_type: question"))
    assert has(out, 1, "line", "hook_type_question")
    ok = edit("hook_type: number", "hook_type: question")
    ok = edit("3 habits cut my spending by 340 euros in one month.", "Can 3 habits cut your spending by 340 euros?", ok)
    assert not has(run(ok), 1, "line", "hook_type_question")


@pytest.mark.parametrize("kind", ["mistake", "contrarian"])
def test_rule_1_a_mistake_or_contrarian_hook_holds_a_negation_word(kind):
    block = edit("hook_type: number", "hook_type: " + kind)
    assert has(run(block), 1, "line", "hook_type_negation")
    never = edit("3 habits cut my spending by 340 euros in one month.", "Never skip these 3 habits to cut 340 euros.", block)
    assert not has(run(never.replace("title: Habits cut my spending", "title: Never skip these habits")), 1, "line", "hook_type_negation")
    dont = edit("3 habits cut my spending by 340 euros in one month.", "You don't need a budget to cut 340 euros in one month.", block)
    assert not has(run(dont.replace("title: Habits cut my spending", "title: You need a budget")), 1, "line", "hook_type_negation")


def test_rule_1_a_result_or_curiosity_hook_has_no_predicate():
    for kind in ("result", "curiosity", "story"):
        assert run(edit("hook_type: number", "hook_type: " + kind))["ok"] is True


# ---------------------------------------------------------------- rule 2: the title mirrors the key phrase

def test_rule_2_the_title_has_3_to_5_words_of_the_hook_line():
    assert has(run(edit("title: Habits cut my spending", "title: Habits cut")), None, "title", "title_length")
    assert has(run(edit("title: Habits cut my spending", "title: 3 habits cut my spending by")), None, "title", "title_length")
    assert run(edit("title: Habits cut my spending", "title: 3 habits cut my spending"))["ok"] is True
    assert has(run(edit("title: Habits cut my spending", "title: Habits slash my spending")), None, "title", "title_not_in_hook")


def test_rule_2_the_hook_beats_on_screen_text_holds_2_to_5_words_of_the_line():
    assert has(run(edit("on-screen: Habits cut spending", "on-screen: Savings")), 1, "on-screen", "hook_on_screen_mirror")
    assert has(run(edit("on-screen: Habits cut spending", "on-screen: Habits ahead")), 1, "on-screen", "hook_on_screen_mirror")
    assert has(run(edit("on-screen: Habits cut spending", "on-screen: 3 my by in cut one")), 1, "on-screen", "hook_on_screen_mirror")      # six words of the line
    assert not has(run(edit("on-screen: Habits cut spending", "on-screen: Cut my spending by 340")), 1, "on-screen", "hook_on_screen_mirror")      # five
    assert not has(run(), 1, "on-screen", "hook_on_screen_mirror")
    no_on_screen = edit("on-screen: Habits cut spending\npreset: keyword\n", "")
    assert not has(run(no_on_screen), 1, "on-screen", "hook_on_screen_mirror")


# ---------------------------------------------------------------- rule 3: open a loop, close it late

def test_rule_3_a_payoff_exists_after_half_of_the_beats_and_holds_a_word_of_the_title():
    assert has(run(edit("role: payoff", "role: point")), None, "role", "no_payoff")
    early = edit("role: payoff", "role: point").replace("role: setup", "role: payoff", 1)
    assert has(run(early), 2, "role", "payoff_too_early")
    no_word = edit("Small habits cut my spending because each one removes a decision I used to avoid.",
                   "Each one removes a decision I used to avoid, and the month gets quiet.")
    assert has(run(no_word), 7, "line", "payoff_misses_title")
    assert not has(run(), 7, "line", "payoff_misses_title")


def test_rule_3_exactly_half_is_too_early_so_a_script_with_a_cta_last_needs_five_beats():
    four = "beat: 1\nrole: hook\nline: 3 habits cut my spending by 340 euros in one month.\n\nbeat: 2\nrole: payoff\nline: Habits cut spending because each decision gets removed.\n\n" \
           "beat: 3\nrole: point\nline: Name every euro on the first of the month so each has a job.\n\nbeat: 4\nrole: cta\nline: Send this to a friend who wants to spend with intention.\n"
    block = HEADER.replace("pattern: list\n", "") + "\n" + four
    assert has(run(block), 2, "role", "payoff_too_early")
    swapped = block.replace("role: payoff", "role: TMP").replace("role: point", "role: payoff").replace("role: TMP", "role: point")
    assert has(run(swapped), 3, "role", "payoff_too_early")          # beat 3 of 4: two beats before it, exactly half, not more than half
    assert not has(run(), 7, "role", "payoff_too_early")             # beat 7 of 8


# ---------------------------------------------------------------- rule 4: one idea per beat

def test_rule_4_a_line_over_30_words_is_refused_and_one_under_8_warns_except_a_turn():
    thirty_one = " ".join(["word"] * 31)
    assert has(run(edit("I tracked every euro I spent for thirty days in a plain notebook.", thirty_one)), 2, "line", "line_too_long_words")
    thirty = " ".join(["word"] * 30)
    assert not has(run(edit("I tracked every euro I spent for thirty days in a plain notebook.", thirty)), 2, "line", "line_too_long_words")
    short = edit("I tracked every euro I spent for thirty days in a plain notebook.", "I tracked every euro.")
    assert has(run(short), 2, "line", "line_short", "warnings") and run(short)["ok"] is True
    turn = short.replace("role: setup", "role: turn")
    assert not has(run(turn), 2, "line", "line_short", "warnings")


# ---------------------------------------------------------------- rule 5: a visual event at least every 6 s

def test_rule_5_a_run_without_an_event_over_15_words_warns_and_a_punch_counts_as_an_event():
    out = run()
    assert has(out, 4, "line", "visual_gap", "warnings")                       # beats 4 and 5: 30 words, no preset
    punched = edit("beat: 4\nrole: point\n", "beat: 4\nrole: point\nemphasis: punch\n")
    assert not has(run(punched), 4, "line", "visual_gap", "warnings")
    assert run(punched)["ok"] is True
    thirty_one = "beat: 1\nrole: setup\nline: " + " ".join(["word"] * 15) + "\n\nbeat: 2\nrole: setup\nline: " + " ".join(["word"] * 16) + "\n"
    assert has(run("hook_type: result\ntitle: x y z\n\n" + thirty_one), 1, "line", "visual_gap", "warnings")      # 31 words in a row
    only_fifteen = "beat: 1\nrole: setup\nline: " + " ".join(["word"] * 15) + "\n"
    assert not has(run("hook_type: result\ntitle: x y z\n\n" + only_fifteen), 1, "line", "visual_gap", "warnings")   # 15 words is the limit


def test_rule_5_is_a_warning_and_never_a_refusal():
    flat = "\n".join(l for l in GOOD.splitlines() if not l.startswith(("preset:", "on-screen:", "value:")))
    out = run(flat)
    assert out["ok"] is True and has(out, 1, "line", "visual_gap", "warnings")


# ---------------------------------------------------------------- rule 6: vary presets

def test_rule_6_no_preset_on_more_than_half_of_the_beats():
    out = run(GOOD)
    assert not has(out, None, "preset", "preset_overused")
    heavy = GOOD
    heavy = edit("role: setup\n", "role: setup\non-screen: Plain notebook\npreset: keyword\n", heavy)
    heavy = edit("role: payoff\n", "role: payoff\non-screen: Small habits\npreset: keyword\n", heavy)
    heavy = edit("role: cta\n", "role: cta\non-screen: Send it\npreset: keyword\n", heavy)
    heavy = edit("role: point\nline: Second", "role: point\non-screen: Review\npreset: keyword\nline: Second", heavy)
    assert has(run(heavy), None, "preset", "preset_overused")      # 5 keywords on 8 beats


def test_rule_6_a_list_has_2_to_4_items():
    assert has(run(edit("on-screen: Name | Review | Cancel", "on-screen: Name")), 3, "on-screen", "list_items")
    assert not has(run(edit("on-screen: Name | Review | Cancel", "on-screen: Name | Review")), 3, "on-screen", "list_items")
    four = edit("on-screen: Name | Review | Cancel", "on-screen: a | b | c | d")
    assert run(four)["ok"] is True


def test_rule_6_a_number_value_is_a_digit_token_of_its_line_and_of_the_material():
    assert has(run(edit("value: 340", "value: 350")), 6, "value", "number_value_not_in_line")
    no_digit = edit("Together those habits saved me 340 euros, and the month felt calmer.", "Together those habits saved me about three hundred euros.")
    assert has(run(no_digit), 6, "value", "number_value_not_in_line")
    assert has(run(figures={"3"}), 6, "value", "figure_not_in_material")
    assert not has(run(), 6, "value", "number_value_not_in_line")


def test_the_digit_token_is_a_run_that_starts_with_a_digit_and_ends_without_punctuation():
    assert cs.digit_tokens("It cost 1,860 euros, then 1.520. Later 340.") == ["1,860", "1.520", "340"]
    assert cs.digit_tokens("R$ 1.500 and 3,5% in 2027-11-08") == ["1.500", "3,5", "2027", "11", "08"]
    assert cs.digit_tokens("no figures here") == []
    out = run(edit("Together those habits saved me 340 euros", "Together those habits saved me 340. euros"))
    assert not has(out, 6, "value", "number_value_not_in_line")


# ---------------------------------------------------------------- rule 7: match the pattern to the roles

def test_rule_7_a_list_pattern_needs_a_hook_a_payoff_or_cta_and_as_many_points_as_the_hook_digit():
    assert run()["ok"] is True                                               # hook promises 3, three point beats
    assert has(run(edit("role: point\nline: Third", "role: setup\nline: Third")), None, "pattern", "pattern_points_missing")
    no_end = GOOD.replace("role: payoff", "role: point").replace("role: cta", "role: point")
    assert has(run(no_end), None, "pattern", "pattern_role_missing")
    no_digit = edit("3 habits cut my spending by 340 euros in one month.", "Habits cut my spending by 340 euros in one month, and this works.").replace("hook_type: number", "hook_type: result")
    assert not has(run(no_digit), None, "pattern", "pattern_points_missing")


def test_rule_7_a_myth_pattern_needs_a_hook_a_turn_and_a_proof():
    myth = edit("pattern: list", "pattern: myth")
    assert has(run(myth), None, "pattern", "pattern_role_missing")
    with_turn = edit("role: setup", "role: turn", myth)
    assert run(with_turn)["ok"] is True
    assert has(run(edit("role: proof", "role: point", with_turn)), None, "pattern", "pattern_role_missing")


def test_rule_7_story_and_problem_solution_rows():
    story = edit("pattern: list", "pattern: story")
    assert has(run(story), None, "pattern", "pattern_role_missing")
    assert run(edit("role: setup", "role: turn", story))["ok"] is True
    assert run(edit("pattern: list", "pattern: problem-solution"))["ok"] is True
    assert run(edit("pattern: list", "pattern: steps"))["ok"] is True


def test_rule_7_before_after_needs_two_compare_beats_and_the_list_has_no_compare_preset_yet():
    block = edit("pattern: list", "pattern: before-after")
    out = run(block)
    assert has(out, None, "pattern", "pattern_preset_missing")
    vocab = copy.deepcopy(VOCAB)
    vocab["presets"]["compare"] = {"kind": "overlay", "summary": "before and after", "main": "after",
                                   "params": {"before": {"type": "text", "max": 24, "required": True}, "after": {"type": "text", "max": 24, "required": True}}}
    two = edit("role: setup\n", "role: setup\non-screen: Spent a lot\npreset: compare\nbefore: Spent a lot\n", block)
    two = edit("role: payoff\n", "role: payoff\non-screen: Spent less\npreset: compare\nbefore: Spent more\n", two)
    assert not has(run(two, vocab=vocab), None, "pattern", "pattern_preset_missing")
    assert has(run(two), 2, "preset", "unknown_preset")                      # until the preset list offers it, the list is closed


def test_rule_7_without_a_pattern_nothing_is_asked():
    assert run(GOOD.replace("pattern: list\n", "").replace("role: point\nline: Third", "role: setup\nline: Third"))["ok"] is True


# ---------------------------------------------------------------- rule 8: end on one CTA

def test_rule_8_exactly_one_cta_and_it_is_the_last_beat():
    assert has(run(edit("role: cta", "role: setup")), None, "role", "cta_count")
    two = edit("role: point\nline: Second", "role: cta\nline: Second")
    out = run(two)
    assert has(out, None, "role", "cta_count") and has(out, 4, "role", "cta_not_last")
    moved = edit("role: proof", "role: cta").replace("role: cta\nline: Send this", "role: setup\nline: Send this")
    assert has(run(moved), 6, "role", "cta_not_last") and not has(run(moved), None, "role", "cta_count")


def test_rule_8_the_cta_has_at_most_20_words():
    twenty_one = " ".join(["send"] * 21)
    assert has(run(edit("Send this to a friend who wants to spend with intention.", twenty_one)), 8, "line", "cta_too_long")
    twenty = " ".join(["send"] * 20)
    assert not has(run(edit("Send this to a friend who wants to spend with intention.", twenty)), 8, "line", "cta_too_long")


# ---------------------------------------------------------------- rule 9: the register leaves room

CALM_QUOTE = """beat: 1
role: hook
line: 3 habits cut my spending by 340 euros in one month.

beat: 2
role: setup
line: A friend who teaches maths said "what you do not name you spend" and it stuck with me.

beat: 3
role: point
line: Name every euro on the first of the month, so that each one has a job to do.

beat: 4
role: payoff
line: Small habits cut my spending because each one removes a decision I used to avoid.

beat: 5
role: cta
line: Send this to a friend who wants to spend with intention.
"""


def calm_script(extra=""):
    return HEADER.replace("pattern: list\n", "") + "\n" + CALM_QUOTE + extra


def test_rule_9_a_neutral_register_asks_nothing_more():
    assert run(calm_script(), register="neutral")["ok"] is True


def test_rule_9_calm_allows_one_preset_per_20_words():
    words_total = sum(len(l.split()) - 1 for l in CALM_QUOTE.splitlines() if l.startswith("line: "))
    assert 60 <= words_total < 80                                              # three presets at most
    three = calm_script()
    for role, text in (("setup", "Name every euro"), ("point", "Each euro a job"), ("payoff", "Small habits")):
        three = edit(f"role: {role}\n", f"role: {role}\non-screen: {text}\npreset: keyword\n", three)
    assert not has(run(three, register="calm"), None, "preset", "calm_preset_density")
    four = edit("role: cta\n", "role: cta\non-screen: Send it on\npreset: keyword\n", three)
    assert has(run(four, register="calm"), None, "preset", "calm_preset_density")
    assert not has(run(four, register="neutral"), None, "preset", "calm_preset_density")


def test_rule_9_calm_refuses_a_punch_on_a_turn_or_a_payoff():
    punched = edit("role: payoff\n", "role: payoff\nemphasis: punch\n", calm_script())
    assert has(run(punched, register="calm"), 4, "emphasis", "calm_emphasis")
    assert not has(run(punched, register="neutral"), 4, "emphasis", "calm_emphasis")
    punched_point = edit("role: point\n", "role: point\nemphasis: punch\n", calm_script())
    assert not has(run(punched_point, register="calm"), 3, "emphasis", "calm_emphasis")
    turn = edit("role: setup\n", "role: turn\nemphasis: punch\n", calm_script())
    assert has(run(turn, register="calm"), 2, "emphasis", "calm_emphasis")


def test_rule_9_calm_wants_a_quoted_span_in_a_quote_beat_with_its_author():
    assert has(run(calm_script(), register="calm"), 2, "preset", "calm_quote_preset")
    quoted = edit("role: setup\n", "role: setup\non-screen: What you do not name you spend\npreset: quote\n", calm_script())
    out = run(quoted, register="calm")
    assert not has(out, 2, "preset", "calm_quote_preset") and has(out, 2, "author", "calm_quote_author")
    ok = edit("preset: quote\n", "preset: quote\nauthor: A friend\n", quoted)
    assert not any(c[2].startswith("calm_quote") for c in codes(run(ok, register="calm")))
    short_quote = edit("said \"what you do not name you spend\"", "said \"free\"", calm_script())
    assert not has(run(short_quote, register="calm"), 2, "preset", "calm_quote_preset")      # a span of fewer than 3 words is not a quote


def test_quoted_spans_in_every_quote_style():
    assert cs.quoted_spans('He said "what you do not name you spend".', 3) == ["what you do not name you spend"]
    assert cs.quoted_spans("He said “what you do not name you spend”.", 3) == ["what you do not name you spend"]
    assert cs.quoted_spans("Ele disse «tres palavras aqui».", 3) == ["tres palavras aqui"]
    assert cs.quoted_spans('A "word" only.', 3) == []


# ---------------------------------------------------------------- rule 10: no invented facts

def test_rule_10_every_digit_token_of_a_line_is_in_the_material():
    assert run(figures={"3", "340"})["ok"] is True
    out = run(edit("for thirty days", "for 30 days"), figures={"3", "340"})
    assert has(out, 2, "line", "invented_figure") and out["ok"] is False
    assert run(edit("for thirty days", "for 30 days"), figures={"3", "340", "30"})["ok"] is True


def test_rule_10_without_material_it_is_skipped_with_a_warning():
    out = run(edit("for thirty days", "for 30 days"), figures=None)
    assert not has(out, 2, "line", "invented_figure") and has(out, None, "material", "material_missing", "warnings")


def test_rule_10_material_files_and_figure_tokens(tmp_path):
    f = tmp_path / "m.txt"
    f.write_text("I spent 1,860 euros and then 1,520 euros.", encoding="utf-8")
    assert cs.read_figures([str(f)], ["340"]) == {"1,860", "1,520", "340"}
    assert cs.read_figures([], []) is None
    with pytest.raises(OSError):
        cs.read_figures([str(tmp_path / "absent.txt")], [])


# ---------------------------------------------------------------- rule 11: length

def test_rule_11_length_is_a_warning_never_a_refusal():
    out = run()
    assert out["ok"] is True and has(out, None, "line", "length_short", "warnings")


def test_rule_11_the_bands_are_150_to_225_words_and_300_the_most():
    def with_total(target):
        base = sum(len(cs.words(l[6:])) for l in GOOD.splitlines() if l.startswith("line: "))
        extra = max(0, target - base)
        # spread the extra words over the lines so that no line passes 30 words
        lines = GOOD.splitlines()
        spread = [i for i, l in enumerate(lines) if l.startswith("line: ")]
        per = -(-extra // len(spread))
        for i in spread:
            lines[i] += " " + " ".join(["extra"] * min(per, extra))
            extra -= min(per, extra)
        return "\n".join(lines) + "\n"
    for target, expected in ((140, "length_short"), (150, None), (225, None), (226, "length_long"), (300, "length_long"), (301, "length_over_max")):
        out = run(with_total(target), figures=None)
        got = [w["code"] for w in out["warnings"] if w["code"].startswith("length_")]
        assert got == ([expected] if expected else []), (target, got, sum(len(cs.words(b["line"])) for b in [{"line": l[6:]} for l in with_total(target).splitlines() if l.startswith("line: ")]))


# ---------------------------------------------------------------- emphasis: at most 1 per 3 beats, 25 words apart

def test_emphasis_punches_are_spaced_by_three_beats_and_25_words():
    two_apart = edit("role: setup\n", "role: setup\nemphasis: punch\n", edit("role: point\nline: First", "role: point\nemphasis: punch\nline: First"))
    assert has(run(two_apart), 3, "emphasis", "punch_too_dense")
    ok = edit("role: hook\n", "role: hook\nemphasis: punch\n", edit("role: point\nline: Second", "role: point\nemphasis: punch\nline: Second"))
    assert run(ok)["ok"] is True                                             # beats 1 and 4: far enough in beats and in words
    close = edit("role: hook\n", "role: hook\nemphasis: punch\n", edit("role: point\nline: Second", "role: point\nemphasis: punch\nline: Second"))
    close = close.replace("line: I tracked every euro I spent for thirty days in a plain notebook.", "line: Tracked it.").replace(
        "line: First, name every euro on the first of the month so each one has a job.", "line: Named it.")
    out = run(close)
    assert has(out, 4, "emphasis", "punch_too_close")


# ---------------------------------------------------------------- a loop ends with no goodbye

def test_a_loop_has_no_goodbye_in_its_last_line():
    looped = edit("pattern: list", "loop: yes")
    assert run(looped)["ok"] is True
    bye = edit("Send this to a friend who wants to spend with intention.", "Send this to a friend, thanks for watching and see you soon.", looped)
    assert has(run(bye), 8, "line", "loop_goodbye")
    assert not has(run(edit("loop: yes", "loop: no", bye)), 8, "line", "loop_goodbye")


# ---------------------------------------------------------------- --beat-only

ONE_BEAT = "beat: 1\nline: That habit saved me 340 euros in one month.\non-screen: saved in one month\npreset: number\nvalue: 340\n"


def test_beat_only_checks_a_single_beat_without_header_roles_or_script_rules():
    out = run(ONE_BEAT, beat_only=True, figures=None, language=None)
    assert out["ok"] is True and out["mode"] == "beat-only" and out["warnings"] == [], out
    assert run(ONE_BEAT, beat_only=False, figures=None)["ok"] is True        # as a script of its own it is legacy and passes with warnings


def test_beat_only_still_refuses_what_is_wrong_with_the_beat():
    assert has(run(ONE_BEAT.replace("value: 340", "value: 350"), beat_only=True), 1, "value", "number_value_not_in_line")
    assert has(run(ONE_BEAT.replace("preset: number", "preset: sparkle"), beat_only=True), 1, "preset", "unknown_preset")
    assert has(run(ONE_BEAT.replace("value: 340", "value: 34 0"), beat_only=True), 1, "value", "bad_pattern")
    assert has(run(ONE_BEAT + "start: 3\n", beat_only=True), 1, "start", "time_field")
    assert has(run(ONE_BEAT.replace("340 euros", "0:12 euros"), beat_only=True), 1, "line", "time_value")
    assert any(p["code"] == "forbidden_character" for p in run(ONE_BEAT.replace("That habit", "That\u200b habit"), beat_only=True)["problems"])
    assert has(run(ONE_BEAT + "role: boss\n", beat_only=True), 1, "role", "bad_value")
    assert has(run(ONE_BEAT.replace("on-screen: saved in one month", "on-screen: " + "x" * 41), beat_only=True), 1, "on-screen", "text_too_long")


def test_beat_only_applies_the_beat_level_rules_of_version_2():
    assert has(run("beat: 1\nline: A list of things I do each week.\non-screen: Only one\npreset: list\n", beat_only=True), 1, "on-screen", "list_items")
    assert has(run("beat: 1\nline: " + " ".join(["word"] * 31) + "\n", beat_only=True), 1, "line", "line_too_long_words")


def test_beat_only_ignores_a_header_and_does_not_need_roles_or_a_hook():
    out = run("title: x\n\nbeat: 1\nrole: payoff\nline: Okay.\n", beat_only=True)
    assert out["ok"] is True and out["header"] == {}
    assert not has(run("beat: 1\nline: x\n", beat_only=True), 1, "role", "missing_role")


def test_beat_only_cli_flag(tmp_path):
    post = tmp_path / "beat.md"
    post.write_text("```script\n" + ONE_BEAT + "```\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--content", str(post), "--presets", str(PRESETS), "--beat-only"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and json.loads(r.stdout)["mode"] == "beat-only"
    r = subprocess.run([sys.executable, str(SCRIPT), "--content", str(post), "--presets", str(PRESETS), "--help"], capture_output=True, text=True, timeout=60)
    assert "--beat-only" in r.stdout and "--register" in r.stdout and "--material" in r.stdout and "--language" in r.stdout


# ---------------------------------------------------------------- compatibility: a version 1 script keeps passing

V1_POST = """# Post: Three habits that changed how I handle money (a fictional fixture)

- Owner: mkt-social-copy
- Network: instagram
- Format: reel

## Script

```script
beat: 1
line: Hey, quick story about money.

beat: 2
line: Last year I tracked every expense for ninety days.

beat: 3
line: The first rule is simple: name every dollar.
on-screen: Name every dollar
preset: keyword
icon: coin

beat: 4
line: Then do three things each week: review, adjust, and celebrate.
on-screen: Review
preset: list
icon: check

beat: 5
line: That habit saved me three hundred forty dollars in one month.
on-screen: dollars saved in one month
preset: number
value: 340

beat: 6
line: A wise friend told me, small steps beat big plans.
on-screen: Small steps beat big plans.
preset: quote
author: A wise friend

beat: 7
line: Here is what my dashboard looked like.
on-screen: My dashboard
preset: cutaway
asset: a screenshot of the budgeting dashboard
fit: cover

beat: 8
line: Look at the chart while I walk you through it, because the shape of the month tells the whole story in one picture and nothing else matters more.
on-screen: Weekly savings
preset: pip
asset: a bar chart of weekly savings
position: top

beat: 9
line: Follow for more small steps.
```

## Post

```post
Three habits.
```
"""


def test_a_version_1_script_with_no_header_and_no_roles_still_passes(tmp_path):
    post = tmp_path / "v1.md"
    post.write_text(V1_POST, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--content", str(post), "--presets", str(PRESETS), "--format", "reel"], capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout)
    assert r.returncode == 0 and out["ok"] is True and out["problems"] == [] and out["mode"] == "legacy", r.stdout
    got = {w["code"] for w in out["warnings"]}
    # what is new in version 2 is said as a warning, with the same code, and nothing is refused
    assert {"legacy_script", "number_value_not_in_line", "list_items", "line_short", "material_missing", "length_short"} <= got


def test_every_new_rule_is_a_warning_in_a_legacy_script():
    stripped = "\n".join(l for l in GOOD.splitlines() if not l.startswith(("role:", "hook_type:", "title:", "cta_kind:", "send_to:", "pattern:")))
    out = run(stripped, figures={"340"}, register="calm")
    assert out["ok"] is True and out["mode"] == "legacy", out["problems"]
    assert has(out, None, "header", "legacy_script", "warnings")
    assert has(out, 1, "line", "invented_figure", "warnings")                # the 3 of the hook is not in the material
    over = edit("I tracked every euro I spent for thirty days in a plain notebook.", " ".join(["word"] * 31), stripped)
    out = run(over, figures={"3", "340"})
    assert out["ok"] is True and has(out, 2, "line", "line_too_long_words", "warnings")


def test_a_legacy_script_is_still_refused_for_what_version_1_refused():
    bad = V1_POST.replace("preset: keyword", "preset: sparkle")
    block = bad.split("```script\n")[1].split("```")[0]
    out = run(block)
    assert out["ok"] is False and has(out, 3, "preset", "unknown_preset")


def test_a_header_line_makes_the_script_version_2_and_a_role_does_too():
    assert run("hook_type: number\n\nbeat: 1\nline: 3 habits.\n")["mode"] == "v2"
    assert run("beat: 1\nrole: hook\nline: 3 habits.\n")["mode"] == "v2"
    assert run("beat: 1\nemphasis: none\nline: 3 habits.\n")["mode"] == "v2"
    assert run("beat: 1\nline: 3 habits.\n")["mode"] == "legacy"


# ---------------------------------------------------------------- the vocabulary file

def test_a_version_1_vocabulary_is_read_as_before_and_has_no_header_or_roles():
    v1 = copy.deepcopy(VOCAB)
    v1["version"] = 1
    del v1["script"]
    out = run("hook_type: number\n\nbeat: 1\nline: Hello there.\n", vocab=v1)
    assert has(out, None, "hook_type", "field_before_first_beat")
    out = run("beat: 1\nrole: hook\nline: Hello there.\n", vocab=v1)
    assert has(out, 1, "role", "parameter_without_preset")


def test_a_version_2_vocabulary_without_its_script_section_is_refused(tmp_path):
    bad = copy.deepcopy(VOCAB)
    del bad["script"]["limits"]["title_max"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        cs.load_vocabulary(str(path))
    bad = copy.deepcopy(VOCAB)
    bad["version"] = 3
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        cs.load_vocabulary(str(path))
    del bad["script"]
    bad["version"] = 2
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError):
        cs.load_vocabulary(str(path))


def test_the_speech_rate_is_one_constant_and_the_thresholds_follow_from_it():
    script = VOCAB["script"]
    assert script["speech_rate_words_per_second"] == 2.5
    rate = script["speech_rate_words_per_second"]
    limits = script["limits"]
    assert round(limits["visual_gap_seconds"] * rate) == 15 and round(limits["punch_gap_seconds"] * rate) == 25
    assert [round(s * rate) for s in limits["target_seconds"]] == [150, 225] and round(limits["max_seconds"] * rate) == 300


def test_the_language_data_starts_with_pt_br_and_english():
    langs = VOCAB["script"]["languages"]
    assert set(langs) == {"en", "pt-BR"}
    for data in langs.values():
        for key in ("openers", "negations", "number_words", "stop_words", "goodbyes"):
            assert data[key] and all(isinstance(w, str) and w == w.strip() for w in data[key])
    assert cs.language_data(VOCAB["script"], "pt") is langs["pt-BR"] and cs.language_data(VOCAB["script"], "fr") is None


def test_a_pt_br_hook_with_a_negation_and_one_without():
    block = edit("hook_type: number", "hook_type: mistake")
    hook = "Nunca guarde o recibo, 3 habitos cortaram 340 euros do meu mes."
    block = edit("3 habits cut my spending by 340 euros in one month.", hook, block).replace("title: Habits cut my spending", "title: guarde o recibo")
    assert not has(run(block, language="pt-BR"), 1, "line", "hook_type_negation")
    block2 = edit("Nunca guarde o recibo, 3 habitos", "Guarde o recibo, 3 habitos", block)
    assert has(run(block2, language="pt-BR"), 1, "line", "hook_type_negation")


# ---------------------------------------------------------------- the prose of the vocabulary is its data

def test_the_prose_of_the_vocabulary_names_every_value_of_the_script_section():
    md = PRESETS_MD.read_text(encoding="utf-8")
    script = VOCAB["script"]
    assert "2.5 words per second" in md
    for role in script["roles"]:
        assert f"`{role}`" in md, role
    for value in script["emphasis"]:
        assert f"`{value}`" in md, value
    for key in script["header"]["keys"]:
        assert f"`{key}`" in md, key
    for key in ("hook_type", "cta_kind", "loop", "pattern"):
        for value in script["header"][key]:
            assert value in md, (key, value)
    for lang in script["languages"]:
        assert lang in md, lang
    assert [str(n) for n in script["limits"]["title_words"]] == ["3", "5"] and "3 to 5 words" in md
    assert "at most 18 words" in md and "8 to 30 words" in md and "at most 20 words" in md
    assert "150 to 225 words" in md and "300 words" in md and "at most 40 characters" in md


def test_the_reference_of_the_skill_names_the_roles_the_rules_and_the_flags():
    ref = (REPO / "skills/mkt-social-copy/references/video-script.md").read_text(encoding="utf-8")
    for role in VOCAB["script"]["roles"]:
        assert f"`{role}`" in ref, role
    for number in range(1, 12):
        assert f"| {number} " in ref, number
    for flag in ("--language", "--register", "--material", "--figure"):
        assert flag in ref, flag
    skill = (REPO / "skills/mkt-social-copy/SKILL.md").read_text(encoding="utf-8")
    for flag in ("--language", "--register", "--material", "--figure", "What to pass to the checker"):
        assert flag in skill or flag in ref, flag
    assert "What to pass to the checker" in skill and "## What to pass to the checker" in ref
