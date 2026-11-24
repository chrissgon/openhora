"""Offline tests of lint_social_profiles.py: the fixtures hold their own small platform data files."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "lint_social_profiles.py"
FIX = HERE / "fixtures"
GOOD = (FIX / "profiles_ok.md").read_text(encoding="utf-8")
ZWJ = chr(0x200D)  # the zero-width joiner, built here so that no invisible character is in the file
BIO_OK = "Software that works for people.\nLume and Pico, by Ana."


def lint(tmp_path, text=GOOD, extra=(), voice=True, profile=True, links=True):
    f = tmp_path / "social-profiles.md"
    f.write_text(text, encoding="utf-8")
    cmd = [sys.executable, str(SCRIPT), "--file", str(f), "--platforms-dir", str(FIX / "platforms")]
    if voice:
        cmd += ["--voice", str(FIX / "voice.md")]
    if profile:
        cmd += ["--profile", str(FIX / "profile.md")]
    if links:
        cmd += ["--links-from", str(FIX / "strategy.md")]
    r = subprocess.run(cmd + list(extra), capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def codes(out):
    return [p["code"] for p in out["problems"]]


def with_bio(text, new, network="photonet"):
    """Replace the proposed text of the first bio block after the network's Platform line."""
    start = text.index("- Platform: %s" % network)
    block = text.index("```proposed\n", start) + len("```proposed\n")
    end = text.index("\n```", block)
    return text[:block] + new + text[end:]


def test_a_good_two_network_artifact_passes(tmp_path):
    code, out, err = lint(tmp_path)
    assert code == 0 and out["ok"] is True and out["problems"] == []
    assert out["voice"] == "checked" and out["sensitive"] == "checked"
    assert out["networks"]["photonet"]["limits"] == "checked"
    assert out["networks"]["photonet"]["pieces"]["bio"] == {"length": 54, "limit": 150, "unit": "code points"}
    assert out["length_lines"]["photonet.bio"] == "54 of 150 (code points)"
    assert out["length_lines"]["clipnet.bio"] == "31 of 80 (utf-16)"


def test_a_151_character_bio_fails_and_a_150_passes(tmp_path):
    code, out, _ = lint(tmp_path, with_bio(GOOD, "a" * 151))
    assert code == 1 and "over_limit" in codes(out)
    assert out["length_lines"]["photonet.bio"] == "151 of 150 (code points)"
    code, out, _ = lint(tmp_path, with_bio(GOOD, "a" * 150))
    assert code == 0 and out["ok"]


def test_an_81_unit_bio_on_the_short_network_fails_and_an_80_passes(tmp_path):
    code, out, _ = lint(tmp_path, with_bio(GOOD, "b" * 81, "clipnet"))
    assert code == 1 and codes(out) == ["over_limit"]
    code, out, _ = lint(tmp_path, with_bio(GOOD, "b" * 80, "clipnet"))
    assert code == 0


def test_a_joined_emoji_is_one_for_the_voice_and_its_length_is_code_points(tmp_path):
    family = "\U0001F468" + ZWJ + "\U0001F469" + ZWJ + "\U0001F467"  # 5 code points, one emoji
    text = with_bio(GOOD, "Hi " + family + " there")
    code, out, _ = lint(tmp_path, text)
    assert code == 0, out["problems"]
    assert out["networks"]["photonet"]["pieces"]["bio"]["length"] == len("Hi " + family + " there")
    two = with_bio(GOOD, "Hi " + family + family)
    code, out, _ = lint(tmp_path, two)
    assert code == 1 and "too_many_emojis" in codes(out)


def test_utf16_units_count_a_character_outside_the_basic_plane_twice(tmp_path):
    text = with_bio(GOOD, "\U0001F600" * 41, "clipnet")  # 41 code points, 82 UTF-16 units
    code, out, _ = lint(tmp_path, text, voice=False)
    assert "over_limit" in codes(out)
    assert out["networks"]["clipnet"]["pieces"]["bio"] == {"length": 82, "limit": 80, "unit": "utf-16"}


def test_a_platform_without_a_profile_key_is_not_checked_and_passes(tmp_path):
    text = GOOD.replace("- Platform: clipnet", "- Platform: plainnet")
    text = with_bio(text, "x" * 500, "plainnet")
    code, out, _ = lint(tmp_path, text, voice=False)
    assert code == 0, out["problems"]
    assert out["networks"]["plainnet"]["limits"] == "not checked"
    assert out["networks"]["plainnet"]["pieces"]["bio"]["limit"] == "not checked"
    assert out["length_lines"]["plainnet.bio"] == "500 of not checked (code points)"


def test_a_piece_whose_limit_is_null_is_not_checked(tmp_path):
    text = GOOD.replace("### Links (`links`)", "### Name (`name`)")
    code, out, _ = lint(tmp_path, text.replace("links.example/anacosta", "A very long name " * 20), links=False)
    assert code == 0, out["problems"]
    assert out["networks"]["photonet"]["pieces"]["name"]["limit"] == "not checked"


def test_an_under_limit_username_and_an_unknown_piece(tmp_path):
    text = GOOD.replace("### Links (`links`)", "### Username (`username`)").replace("links.example/anacosta", "ab")
    code, out, _ = lint(tmp_path, text, links=False)
    assert "under_limit" in codes(out)
    text = GOOD.replace("### Links (`links`)", "### Pinned (`pinned`)")
    code, out, _ = lint(tmp_path, text)
    assert "unknown_piece" in codes(out)


def test_an_address_that_is_not_in_the_strategy_is_refused(tmp_path):
    text = with_bio(GOOD, "Find me at old.example/home")
    code, out, _ = lint(tmp_path, text)
    assert code == 1 and "link_not_allowed" in codes(out)
    text = with_bio(GOOD, "Lume: https://www.LUME.example/start")
    code, out, _ = lint(tmp_path, text)
    assert code == 0, out["problems"]


def test_a_file_name_or_a_product_name_is_not_an_address(tmp_path):
    code, out, _ = lint(tmp_path, with_bio(GOOD, "I write Node.js and README.md tools"))
    assert code == 0, out["problems"]


def test_too_many_links_in_a_links_piece(tmp_path):
    text = GOOD.replace("links.example/anacosta", "links.example/anacosta\nlume.example\npico.example")
    code, out, _ = lint(tmp_path, text)
    assert code == 1 and "too_many_links" in codes(out)


def test_a_banned_phrase(tmp_path):
    code, out, _ = lint(tmp_path, with_bio(GOOD, "A code guru for hire"))
    assert code == 1 and "banned_phrase" in codes(out)


def test_exclamations_and_an_emoji_at_a_line_start(tmp_path):
    code, out, _ = lint(tmp_path, with_bio(GOOD, "Hello! World!"))
    assert "too_many_exclamations" in codes(out)
    code, out, _ = lint(tmp_path, with_bio(GOOD, "Hello\n\U0001F680 launch"))
    assert "emoji_line_start" in codes(out)


def test_a_bio_is_not_a_post_so_a_hashtag_or_a_missing_question_is_no_problem(tmp_path):
    code, out, _ = lint(tmp_path, with_bio(GOOD, "Notes on #design, no question here"))
    assert code == 0, out["problems"]


def test_a_sensitive_hit_and_the_same_text_with_an_exception(tmp_path):
    text = with_bio(GOOD, "Writing about therapy for engineers")
    code, out, _ = lint(tmp_path, text)
    assert code == 1 and "sensitive" in codes(out)
    code, out, _ = lint(tmp_path, text, extra=["--exception", "health"])
    assert code == 0, out["problems"]


def test_without_voice_or_profile_the_checks_are_unchecked_never_a_pass(tmp_path):
    code, out, _ = lint(tmp_path, voice=False, profile=False)
    assert code == 0 and out["voice"] == "unchecked" and out["sensitive"] == "unchecked"


@pytest.mark.parametrize("line", [
    "- Approved: yes",
    "- Approved: yes, 2030-01-02",
    '- Approved: yes, "that one"',
    "- Applied: yes",
    "- Applied: yes, 2030-01-03",
])
def test_a_yes_needs_a_date_and_the_persons_words(tmp_path, line):
    text = GOOD.replace("- Approved: no\n- Applied: no\n\n### Links", line + "\n- Applied: no\n\n### Links", 1) \
        if line.startswith("- Approved") else GOOD.replace("- Applied: no\n\n### Links", line + "\n\n### Links", 1)
    code, out, _ = lint(tmp_path, text)
    assert code == 1 and "approved_without_words" in codes(out)


def test_a_change_with_no_proposed_text(tmp_path):
    text = GOOD.replace("```proposed\nlinks.example/anacosta\n```\n", "")
    code, out, _ = lint(tmp_path, text)
    assert code == 1 and "change_without_proposal" in codes(out)


def test_a_missing_section_and_a_status(tmp_path):
    code, out, _ = lint(tmp_path, GOOD.replace("## Superseded", "## Replaced"))
    assert code == 1 and [p["where"] for p in out["problems"] if p["code"] == "missing_section"] == ["Superseded"]
    code, out, _ = lint(tmp_path, GOOD.replace("Status: draft", "Status: final"))
    assert code == 1 and "status" in codes(out)
    code, out, _ = lint(tmp_path, GOOD.replace("Status: draft", "Estado: rascunho"),
                        extra=["--status-label", "Estado", "--status-words", "rascunho"])
    assert code == 0, out["problems"]


def test_translated_labels_and_headings(tmp_path):
    text = (GOOD.replace("- Platform:", "- Plataforma:").replace("- Approved:", "- Aprovado:")
            .replace("- Applied:", "- Aplicado:").replace("yes,", "sim,")
            .replace("## Across networks", "## Entre redes").replace("## Superseded", "## Substituido"))
    extra = ["--platform-label", "Plataforma", "--approved-label", "Aprovado", "--applied-label", "Aplicado",
             "--yes-word", "sim", "--required-headings", "Entre redes,Substituido"]
    code, out, _ = lint(tmp_path, text, extra=extra)
    assert code == 0, out["problems"]


def test_the_link_page_section_gets_the_checks_that_need_no_platform(tmp_path):
    page = "\n## Link page\n\n### Bio (`bio`)\n- Verdict: change\n```proposed\nA rockstar page\n```\n- Approved: no\n"
    text = GOOD.replace("\n## Across networks", page + "\n## Across networks")
    code, out, _ = lint(tmp_path, text)
    assert code == 1 and "banned_phrase" in codes(out)
    assert "link page" not in out["networks"] and set(out["networks"]) == {"photonet", "clipnet"}


def test_no_network_section(tmp_path):
    code, out, _ = lint(tmp_path, GOOD.replace("- Platform:", "- Network:"))
    assert code == 1 and "no_network" in codes(out)


def test_help_exits_0():
    r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "end_with_question" in r.stdout


def test_a_bad_path_or_a_bad_argument_exits_2(tmp_path):
    cmd = [sys.executable, str(SCRIPT), "--platforms-dir", str(FIX / "platforms")]
    r = subprocess.run(cmd + ["--file", str(tmp_path / "missing.md")], capture_output=True, text=True)
    assert r.returncode == 2 and r.stdout == "" and "cannot read" in r.stderr
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 2
    f = tmp_path / "a.md"
    f.write_text(GOOD, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--file", str(f), "--platforms-dir", str(tmp_path / "nope")],
                       capture_output=True, text=True)
    assert r.returncode == 2
    r = subprocess.run(cmd + ["--file", str(f), "--voice", str(f)], capture_output=True, text=True)
    assert r.returncode == 2 and "voice-rules" in r.stderr
