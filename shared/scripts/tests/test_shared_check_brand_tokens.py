"""Tests for shared/scripts/check_brand_tokens.py: the closed `brand-tokens` block of a visual identity. One source for the copy
that brand-identity runs in its self-check and the copy the task runtime's theme reader imports (runtime/theme.py). Offline; every
name and colour below is fictional.

Run: uv run --with pytest pytest shared/scripts/tests
"""
from __future__ import annotations

import copy
import importlib.util
import json

import pytest

from shared_helpers import SOURCES, clean_usage_error, run

SCRIPT = "check_brand_tokens.py"
spec = importlib.util.spec_from_file_location("check_brand_tokens_source", SOURCES / SCRIPT)
cbt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cbt)

GOOD = {
    "version": 1, "status": "approved", "mode_default": "dark",
    "color": {"bg": {"dark": "#101418", "light": "#FFFFFF"}, "fg": {"dark": "#F5F7FA", "light": "#14181C"},
              "muted": {"dark": "#9AA4B2", "light": "#5B6573"}, "accent": {"dark": "#2EC4B6", "light": "#0B7A70"},
              "surface": {"dark": "#1B2128", "light": "#E8EEF2"}},
    "font": {"display": {"family": "Inter", "weight": 800}, "body": {"family": "Inter", "weight": 500},
             "mono": {"family": "JetBrains Mono", "weight": 500}},
}


def document(block, status="approved (2026-10-01)", fence="brand-tokens"):
    text = block if isinstance(block, str) else json.dumps(block, indent=1)
    return "# Visual identity: Example Studio\n\n- Owner: brand-identity\n- Status: %s\n\n## Tokens\n```%s\n%s\n```\n\n## Sources\n" % (status, fence, text)


def mutated(path, value):
    """GOOD with the value at `path` (a list of keys) replaced; `...` removes the key."""
    block = copy.deepcopy(GOOD)
    node = block
    for key in path[:-1]:
        node = node[key]
    if value is ...:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return block


def codes(block, **kw):
    return [(p["code"], p["field"]) for p in cbt.check_text(document(block, **kw))]


def test_a_closed_valid_block_passes_through_the_command_line(tmp_path):
    f = tmp_path / "identity.md"
    f.write_text(document(GOOD), encoding="utf-8")
    r = run(SCRIPT, "--file", str(f))
    assert r.returncode == 0 and json.loads(r.stdout) == {"ok": True, "problems": []}


def test_the_command_line_prints_each_problem_as_a_code_and_a_field_and_exits_1(tmp_path):
    f = tmp_path / "identity.md"
    f.write_text(document(mutated(["color", "accent", "dark"], "teal")), encoding="utf-8")
    r = run(SCRIPT, "--file", str(f))
    assert r.returncode == 1 and json.loads(r.stdout) == {"ok": False, "problems": [{"code": "bad_color", "field": "color.accent.dark"}]}
    assert "teal" not in r.stdout, "a value of the file is never printed back"


def test_only_one_role_of_each_kind_may_be_left_out_and_a_role_may_have_one_column():
    assert codes(mutated(["color", "surface"], ...)) == []
    assert codes(mutated(["font", "mono"], ...)) == []
    assert codes(mutated(["color", "accent"], {"light": "#0B7A70"})) == []
    assert codes(mutated(["color", "accent"], {"dark": "#2EC4B6"})) == []
    assert codes(mutated(["color", "accent"], ...)) == [("missing_role", "color.accent")]
    assert codes(mutated(["color", "bg"], ...)) == [("missing_role", "color.bg")]
    assert codes(mutated(["font", "body"], ...)) == [("missing_role", "font.body")]
    assert codes(mutated(["font", "display"], ...)) == [("missing_role", "font.display")]


@pytest.mark.parametrize("value", ["#FFF", "#12345G", "red", "rgb(1,2,3)", "rgba(255,255,255,.18)", "#1234567", "2EC4B6", "#2EC4B6;", 12, None, ["#2EC4B6"], ""])
def test_a_colour_that_is_not_six_hex_digits_is_refused(value):
    assert codes(mutated(["color", "accent", "dark"], value)) == [("bad_color", "color.accent.dark")]


def test_a_colour_role_with_no_column_or_an_unknown_column_or_not_an_object_is_refused():
    assert codes(mutated(["color", "muted"], {})) == [("bad_color", "color.muted")]
    assert codes(mutated(["color", "muted"], "#9AA4B2")) == [("bad_color", "color.muted")]
    assert codes(mutated(["color", "muted"], {"dark": "#9AA4B2", "accent": "#000000"})) == [("unknown_mode", "color.muted.accent")]
    assert codes(mutated(["color"], ["#000000"])) == [("bad_color", "color")]


def test_an_unknown_role_a_fourth_font_role_and_an_unknown_key_are_refused():
    block = mutated(["color", "chip_text"], {"dark": "#FFFFFF"})
    assert codes(block) == [("unknown_role", "color.chip_text")]
    block = mutated(["font", "chip"], {"family": "Inter", "weight": 500})
    assert codes(block) == [("unknown_role", "font.chip")]
    block = mutated(["handle"], {"text": "@example"})
    assert codes(block) == [("unknown_key", "handle")]


@pytest.mark.parametrize("spec", [{"family": "Inter", "weight": 750}, {"family": "Inter", "weight": "800"}, {"family": "Inter", "weight": True},
                                  {"family": "Inter", "weight": 1000}, {"family": "Inter", "weight": 0}, {"family": "Inter"},
                                  {"family": "In;ter", "weight": 500}, {"family": "x" * 41, "weight": 500}, {"family": "", "weight": 500},
                                  {"family": 5, "weight": 500}, {"family": "Inter", "weight": 500, "style": "italic"}, "Inter", ["Inter", 500]])
def test_a_font_that_is_not_a_plain_family_and_a_weight_in_steps_of_100_is_refused(spec):
    [(code, field)] = codes(mutated(["font", "display"], spec))
    assert code == "bad_font" and field.startswith("font.display")


def test_the_version_the_status_and_the_default_mode_are_closed():
    assert codes(mutated(["version"], 2)) == [("block_version", "version")]
    assert codes(mutated(["version"], True)) == [("block_version", "version")]
    assert codes(mutated(["status"], "final")) == [("bad_status", "status")]
    assert codes(mutated(["mode_default"], "accent")) == [("bad_mode", "mode_default")]
    assert codes(mutated(["status"], ...)) == [("missing_key", "status")]
    assert codes(mutated(["font"], ...)) == [("missing_key", "font")]


def test_a_block_with_no_version_is_open_and_is_told_apart_from_a_closed_block_that_is_wrong():
    old = {"mode_default": "dark", "color": {"bg": {"dark": "#000000", "light": "#FFFFFF"}}, "font": {"body": "system-ui"}}
    assert codes(old) == [("block_open", "")]
    assert codes(mutated(["color", "bg", "dark"], "black")) == [("bad_color", "color.bg.dark")]


def test_a_missing_repeated_oversize_or_unreadable_block_is_a_code():
    assert [p["code"] for p in cbt.check_text("# Visual identity\n\nno block here\n")] == ["block_missing"]
    assert [p["code"] for p in cbt.check_text(document(GOOD) + document(GOOD))] == ["block_repeated"]
    assert [p["code"] for p in cbt.check_text(document("{not json"))] == ["block_not_json"]
    assert [p["code"] for p in cbt.check_text(document("[1, 2]"))] == ["block_not_object"]
    assert [p["code"] for p in cbt.check_text(document(dict(GOOD, pad="x" * 9000)))] == ["block_too_large"]
    assert [p["code"] for p in cbt.check_text(document(GOOD, fence="json"))] == ["block_missing"], "only the brand-tokens fence is the block"


def test_the_status_line_is_compared_only_when_it_is_written_in_english():
    assert codes(GOOD, status="draft") == [("status_mismatch", "status")]
    assert codes(dict(GOOD, status="draft"), status="approved (2026-10-01)") == [("status_mismatch", "status")]
    assert codes(dict(GOOD, status="draft"), status="draft") == []
    assert codes(dict(GOOD, status="draft"), status="rascunho") == [], "the document's language is not guessed: the block's own status stands"
    assert codes(GOOD, status="aprovado (2026-10-01)") == []
    assert cbt.status_line("- Status: Draft\n") == "draft" and cbt.status_line("- Status: approved (2026-10-01)\n") == "approved"
    assert cbt.status_line("- Status: rascunho\n") is None and cbt.status_line("no line") is None


def test_a_key_that_is_not_a_short_word_is_never_echoed_in_a_field():
    block = mutated(["color", "<script>alert(1)</script>"], {"dark": "#000000"})
    assert codes(block) == [("unknown_role", "color.?")]
    assert codes(dict(GOOD, **{"x" * 40: 1})) == [("unknown_key", "?")]


def test_the_fence_must_open_and_close_on_a_line_of_its_own():
    assert cbt.blocks("```brand-tokens\n{}\n```\n") == ["{}"]
    assert cbt.blocks("  ```brand-tokens\n{}\n```\n") == []
    assert cbt.blocks("```brand-tokens\n{}\n") == []
    assert cbt.blocks("```brand-tokens   \n{}\n```   \n") == ["{}"]


def test_the_roles_the_module_names_are_the_ones_the_docstring_and_the_skill_promise():
    assert cbt.COLOR_ROLES + cbt.OPTIONAL_COLOR_ROLES == ("bg", "fg", "muted", "accent", "surface")
    assert cbt.FONT_ROLES + cbt.OPTIONAL_FONT_ROLES == ("display", "body", "mono")
    assert cbt.MODES == ("dark", "light") and cbt.VERSION == 1


def test_usage_errors_and_unreadable_files_exit_2_with_a_message_and_no_traceback(tmp_path):
    assert clean_usage_error(run(SCRIPT))
    assert clean_usage_error(run(SCRIPT, "--file"))
    assert clean_usage_error(run(SCRIPT, "--file", str(tmp_path / "missing.md")))
    assert clean_usage_error(run(SCRIPT, "--bogus", "x"))
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00bad")
    assert clean_usage_error(run(SCRIPT, "--file", str(binary)))
    big = tmp_path / "big.md"
    big.write_bytes(b"x" * (cbt.FILE_LIMIT + 1))
    assert clean_usage_error(run(SCRIPT, "--file", str(big)))
    helped = run(SCRIPT, "--help")
    assert helped.returncode == 0 and "brand-tokens" in helped.stdout
