"""The project's theme for the renderer (package P4g of the short-video plan, A6.3): runtime/theme.py reads the closed `brand-tokens`
block of the identity and maps it to the renderer's `--color` and `--font` roles. Offline: no renderer, no model, no network. The
identity, its colours, its fonts and its text are invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_theme.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import pathlib
import re
import tempfile

import pytest

import standin_tree as st

REPO = st.REPO
theme = st.load("theme")
tokens = st.load("check_brand_tokens")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contrast = _load("contrast_of_brand_identity", "skills/brand-identity/scripts/contrast.py")
notion_blocks = _load("notion_blocks_for_theme", "providers/documents/notion_blocks.py")
PRESETS = json.loads((REPO / "providers" / "renderer" / "renderer-presets.json").read_text(encoding="utf-8"))["theme"]
ALLOWLIST = json.loads((REPO / "providers" / "renderer" / "assets" / "fonts" / "allowlist.json").read_text(encoding="utf-8"))["fonts"]

BLOCK = {
    "version": 1, "status": "approved", "mode_default": "dark",
    "color": {"bg": {"dark": "#0A1220", "light": "#FFFFFF"}, "fg": {"dark": "#F4F7FB", "light": "#101820"},
              "muted": {"dark": "#A9B4C4", "light": "#566275"}, "accent": {"dark": "#3DDC97", "light": "#0E7A4D"}},
    "font": {"display": {"family": "Inter", "weight": 800}, "body": {"family": "Inter", "weight": 500},
             "mono": {"family": "JetBrains Mono", "weight": 500}},
}
PROSE = "Orchard Studio keeps one green accent and nothing else on its covers."


def identity(block=BLOCK, status="approved (2026-10-01)", prose=PROSE):
    text = block if isinstance(block, str) else json.dumps(block, indent=1)
    return ("# Visual identity: Orchard Studio\n\n- Owner: brand-identity\n- Status: %s\n\n## In one sentence\n%s\n\n## Tokens\n```brand-tokens\n%s\n```\n\n"
            "## Sources\n1. nothing\n" % (status, prose, text))


def project(tmp_path, text=None, name=None):
    """A project folder with docs/brand/, and the identity when `text` is given; a new folder each call unless a name is given."""
    root = pathlib.Path(tempfile.mkdtemp(dir=tmp_path)) if name is None else tmp_path / name
    (root / "docs" / "brand").mkdir(parents=True, exist_ok=name is None)
    if text is not None:
        (root / "docs" / "brand" / "identity.md").write_text(text, encoding="utf-8")
    return str(root)


def block_with(**changes):
    """BLOCK with dotted paths replaced (`color.accent`), `...` removing the key."""
    block = copy.deepcopy(BLOCK)
    for path, value in changes.items():
        parts = path.split("__")
        node = block
        for key in parts[:-1]:
            node = node[key]
        if value is ...:
            del node[parts[-1]]
        else:
            node[parts[-1]] = value
    return block


def pairs(args, flag):
    out = {}
    for i, a in enumerate(args):
        if a == flag:
            key, _, value = args[i + 1].partition("=")
            assert key not in out
            out[key] = value
    return out


def refused(tmp_path, text, **kw):
    with pytest.raises(theme.ThemeError) as e:
        theme.theme_args(project(tmp_path, text), **kw)
    return e.value


# --- the mapping: every renderer token is mapped, derived or kept, and every role of the block goes somewhere ----------------------


def test_each_colour_token_of_the_renderer_is_mapped_derived_or_kept_and_a_test_names_it(tmp_path):
    mapped = {token for _, token in theme.COLOR_MAP}
    derived = {"chip_border", "chip_text"}           # chip_border from accent; chip_text from accent or fg by contrast
    kept = {"chip_fill"}                             # from `surface` when the block has one, else the renderer's own default
    assert mapped == {"bg", "text", "muted", "accent"} and mapped | derived | kept == set(PRESETS["colors"])
    args, record = theme.theme_args(project(tmp_path, identity()))
    assert set(pairs(args, "--color")) == mapped | derived, "with no surface the renderer's chip_fill stays"
    surfaced = block_with(color__surface={"dark": "#17233A", "light": "#E6ECF5"})
    args, _ = theme.theme_args(project(tmp_path, identity(surfaced), "with-surface"))
    assert set(pairs(args, "--color")) == mapped | derived | kept and pairs(args, "--color")["chip_fill"] == "#17233A"
    assert record["colors"] == pairs(theme.theme_args(project(tmp_path, identity(), "again"))[0], "--color")


def test_every_role_of_the_closed_block_maps_to_a_token_or_font_role_the_renderer_has(tmp_path):
    assert {token for _, token in theme.COLOR_MAP} <= set(PRESETS["colors"])
    assert {role for _, role in theme.FONT_MAP} <= set(PRESETS["font_roles"]) and {role for _, role in theme.FONT_MAP} == set(PRESETS["font_roles"])
    assert {role for role, _ in theme.COLOR_MAP} | {"surface"} == set(tokens.COLOR_ROLES + tokens.OPTIONAL_COLOR_ROLES)
    assert {role for role, _ in theme.FONT_MAP} == set(tokens.FONT_ROLES + tokens.OPTIONAL_FONT_ROLES)
    assert {token for token, _ in theme.PAIRS} <= set(PRESETS["colors"]), "the pairs checked name tokens that exist"


def test_the_dark_column_is_read_and_a_role_with_one_value_uses_it(tmp_path):
    args, record = theme.theme_args(project(tmp_path, identity()))
    colors = pairs(args, "--color")
    assert colors == {"bg": "#0A1220", "text": "#F4F7FB", "muted": "#A9B4C4", "accent": "#3DDC97", "chip_border": "#3DDC97", "chip_text": "#3DDC97"}
    assert record["colors"] == colors and all(re.fullmatch(r"#[0-9A-F]{6}", v) for v in colors.values())
    one = block_with(color__muted={"light": "#a9b4c4"})
    args, _ = theme.theme_args(project(tmp_path, identity(one), "one"))
    assert pairs(args, "--color")["muted"] == "#A9B4C4", "a lower-case value is passed in capitals, the renderer's own form"


def test_chip_text_is_the_accent_when_it_reaches_4_5_to_1_on_the_chip_fill_else_the_text_colour(tmp_path):
    fill = PRESETS["colors"]["chip_fill"]
    assert theme.ratio("#3DDC97", fill) >= 4.5
    args, _ = theme.theme_args(project(tmp_path, identity()))
    assert pairs(args, "--color")["chip_text"] == "#3DDC97"
    dim = block_with(color__accent={"dark": "#2A3A5A"})              # an accent too dark to read on the chip fill
    assert theme.ratio("#2A3A5A", fill) < 4.5
    args, _ = theme.theme_args(project(tmp_path, identity(dim), "dim"))
    colors = pairs(args, "--color")
    assert colors["chip_text"] == "#F4F7FB" and colors["accent"] == "#2A3A5A" and colors["chip_border"] == "#2A3A5A"


def test_the_fonts_are_passed_as_an_allow_listed_id_with_the_weight_of_the_block(tmp_path):
    ids = {(r["family"], r["weight"]): r["id"] for r in ALLOWLIST}
    assert ids[("Inter", 800)] == "inter-800" and ids[("JetBrains Mono", 500)] == "jetbrains-mono-500"
    args, record = theme.theme_args(project(tmp_path, identity()))
    assert pairs(args, "--font") == {"display": "inter-800:800", "text": "inter-500:500", "mono": "jetbrains-mono-500:500"}
    assert record["fonts"] == pairs(args, "--font") and record["notes"] == []


def test_a_weight_or_family_the_allow_list_does_not_have_falls_back_to_the_default_with_a_note(tmp_path):
    odd = block_with(font__display={"family": "Inter", "weight": 700}, font__body={"family": "Orchard Sans", "weight": 400})
    args, record = theme.theme_args(project(tmp_path, identity(odd)))
    assert pairs(args, "--font") == {"mono": "jetbrains-mono-500:500"}
    assert record["notes"] == [{"role": "display", "asked": "Inter 700", "used": "default", "reason": "not_on_allow_list"},
                               {"role": "text", "asked": "Orchard Sans 400", "used": "default", "reason": "not_on_allow_list"}]
    assert pairs(args, "--font").get("display") is None, "a weight the block asked for is never guessed from a near one"
    no_mono = block_with(font__mono=...)
    args, record = theme.theme_args(project(tmp_path, identity(no_mono), "no-mono"))
    assert "mono" not in pairs(args, "--font") and record["notes"] == []


def test_the_weight_comes_from_the_block_not_from_the_default_of_the_role(tmp_path):
    light = block_with(font__body={"family": "Inter", "weight": 800})
    args, _ = theme.theme_args(project(tmp_path, identity(light)))
    assert pairs(args, "--font")["text"] == "inter-800:800", "the body asked for 800: the default of the role is 500"


# --- what is refused, with a closed code and a fixed sentence ----------------------------------------------------------------------


@pytest.mark.parametrize("path,value,field", [
    ("color__accent", {"dark": "teal"}, "color.accent.dark"), ("color__accent", {"dark": "#FFF"}, "color.accent.dark"),
    ("color__fg", {"dark": "rgba(255,255,255,.9)"}, "color.fg.dark"), ("color__bg", {"dark": "#0A1220;}"}, "color.bg.dark"),
    ("color__bg", {"dark": 123456}, "color.bg.dark")])
def test_a_colour_that_is_not_hex_is_refused_before_it_reaches_the_renderer(tmp_path, path, value, field):
    e = refused(tmp_path, identity(block_with(**{path: value})))
    assert (e.code, e.field) == ("theme_bad_color", field) and e.sentence == theme.SENTENCES["theme_bad_color"]
    assert "teal" not in str(e) + e.sentence and "rgba" not in str(e) + e.sentence


def test_an_unknown_colour_role_and_a_fourth_font_role_are_refused(tmp_path):
    e = refused(tmp_path, identity(block_with(color__chip_text={"dark": "#FFFFFF"})))
    assert (e.code, e.field) == ("theme_unknown_role", "color.chip_text")
    e = refused(tmp_path, identity(block_with(font__chip={"family": "Inter", "weight": 500})))
    assert (e.code, e.field) == ("theme_unknown_role", "font.chip")
    legacy = {"version": 1, "status": "approved", "mode_default": "dark", "color": {"bg": {"dark": "#000000"}, "text": {"dark": "#FFFFFF"}}, "font": {}}
    assert refused(tmp_path, identity(legacy)).code == "theme_unknown_role", "`text` is a renderer token, not a role of the identity (`fg` is)"


@pytest.mark.parametrize("spec", [{"family": "Inter", "weight": 750}, {"family": "In;ter", "weight": 500}, "Inter", {"family": "Inter"}])
def test_a_bad_font_is_refused(tmp_path, spec):
    e = refused(tmp_path, identity(block_with(font__display=spec)))
    assert e.code == "theme_bad_font" and e.field.startswith("font.display")


def test_a_block_that_is_not_json_or_has_the_wrong_shape_is_refused(tmp_path):
    for k, text in enumerate(("{not json", "[1, 2]", json.dumps(block_with(color__bg=...)), json.dumps(block_with(version=2)),
                              json.dumps(dict(BLOCK, extra=1)), json.dumps(block_with(mode_default="accent")))):
        e = refused(tmp_path, identity(text))
        assert e.code == "theme_block_invalid" and e.sentence == theme.SENTENCES["theme_block_invalid"], (text, e.code)
    two = identity() + "\n" + identity()
    assert refused(tmp_path, two).code == "theme_block_invalid" and refused(tmp_path, identity(dict(BLOCK, pad="x" * 9000))).code == "theme_block_invalid"


def test_an_oversize_linked_or_unreadable_identity_file_is_refused(tmp_path):
    big = identity() + "x" * theme.IDENTITY_LIMIT
    e = refused(tmp_path, big)
    assert (e.code, e.field) == ("identity_unreadable", "identity") and e.sentence == theme.SENTENCES["identity_unreadable"]
    real = tmp_path / "elsewhere.md"
    real.write_text(identity(), encoding="utf-8")
    linked = project(tmp_path, None, "linked")
    os.symlink(real, os.path.join(linked, "docs", "brand", "identity.md"))
    with pytest.raises(theme.ThemeError) as e:
        theme.theme_args(linked)
    assert e.value.code == "identity_unreadable"
    out = project(tmp_path, None, "leaves")
    folder = tmp_path / "outside" / "brand"
    folder.mkdir(parents=True)
    (folder / "identity.md").write_text(identity(), encoding="utf-8")
    os.rmdir(os.path.join(out, "docs", "brand"))
    os.symlink(folder, os.path.join(out, "docs", "brand"))
    with pytest.raises(theme.ThemeError) as e:
        theme.theme_args(out)
    assert e.value.code == "identity_unreadable", "a folder that leads out of the project is not read"
    folder_instead = project(tmp_path, None, "folder")
    os.mkdir(os.path.join(folder_instead, "docs", "brand", "identity.md"))
    with pytest.raises(theme.ThemeError) as e:
        theme.theme_args(folder_instead)
    assert e.value.code == "identity_unreadable"
    binary = project(tmp_path, None, "binary")
    open(os.path.join(binary, "docs", "brand", "identity.md"), "wb").write(b"\xff\xfe\x00")
    with pytest.raises(theme.ThemeError) as e:
        theme.theme_args(binary)
    assert e.value.code == "identity_unreadable"


def test_a_draft_identity_is_refused_with_its_sentence_never_used_silently(tmp_path):
    e = refused(tmp_path, identity(block_with(status="draft"), status="draft"))
    assert (e.code, e.field) == ("theme_draft", "status")
    assert e.sentence.startswith("the identity is a draft: approve it, or choose the default theme (in a terminal: prepare-again --step review, then captions-edit")
    assert e.sentence.endswith("then captions-done)") and '"choice": "default"' in e.sentence
    assert refused(tmp_path, identity(block_with(status="draft"), status="rascunho")).code == "theme_draft", "the Portuguese word for draft is read"
    assert refused(tmp_path, identity(BLOCK, status="rascunho")).code == "theme_draft", "a Status line that says draft is read even when the block says approved"
    assert refused(tmp_path, identity(BLOCK, status="draft")).code == "theme_draft"
    assert refused(tmp_path, identity(block_with(status="draft"), status="aprovado (2026-10-01)")).code == "theme_draft", "the block's own status also stops a render"
    old_but_draft = identity('{"mode_default": "dark"}', status="rascunho")
    assert refused(tmp_path, old_but_draft).code == "theme_draft", "a draft with an open block is refused too"
    for k, word in enumerate(("aprovado (2026-10-01)", "aprovada (2026-10-01)", "approved (2026-10-01)")):
        args, _ = theme.theme_args(project(tmp_path, identity(BLOCK, status=word), "pt-approved%d" % k))
        assert args, "an approved identity written in the document's language is read"


def test_a_status_line_the_list_does_not_have_is_refused_and_never_replaced_by_the_blocks_status(tmp_path):
    e = refused(tmp_path, identity(BLOCK, status="final (2026-10-01)"))
    assert (e.code, e.field) == ("theme_status_unknown", "status") and e.sentence == theme.SENTENCES["theme_status_unknown"]
    assert "choose the default theme" in e.sentence
    assert refused(tmp_path, identity('{"mode_default": "dark"}', status="borrador")).code == "theme_status_unknown"


def test_a_text_pair_under_4_5_to_1_stops_with_the_pair_named_and_nothing_is_picked_for_the_person(tmp_path):
    # the muted text on the chip fill: a mid grey on the renderer's dark fill
    low = block_with(color__muted={"dark": "#4A5160"})
    value = contrast.ratio("#4A5160", PRESETS["colors"]["chip_fill"])
    assert value < 4.5
    e = refused(tmp_path, identity(low))
    assert (e.code, e.field) == ("theme_low_contrast", "muted_on_chip_fill")
    assert e.sentence == theme.LOW_CONTRAST_SENTENCE % ("muted on chip fill", "%.2f" % value)
    assert "choose the default theme" in e.sentence and "%.2f:1" % value in e.sentence
    dark_text = block_with(color__fg={"dark": "#202830"})
    e = refused(tmp_path, identity(dark_text))
    assert (e.code, e.field) == ("theme_low_contrast", "text_on_chip_fill")
    light_only = block_with(color__fg={"light": "#101820"})           # one value: used, and a dark text on the dark chip fill fails
    assert refused(tmp_path, identity(light_only)).code == "theme_low_contrast"
    surfaced = block_with(color__surface={"dark": "#E6ECF5"})        # a light surface under light text
    e = refused(tmp_path, identity(surfaced))
    assert (e.code, e.field) == ("theme_low_contrast", "text_on_chip_fill")


def test_the_contrast_is_the_one_the_brand_identity_script_computes(tmp_path):
    cases = [("#FFFFFF", "#000000"), ("#0092CD", "#FFFFFF"), ("#3DDC97", "#1B1F2A"), ("#4A5160", "#1B1F2A"), ("#A9B4C4", "#1B1F2A"),
             ("#07B6F0", "#011B24"), ("#6BC9F5", "#011B24"), ("#202830", "#1B1F2A"), ("#9CA3AF", "#1B1F2A")]
    for fg, bg in cases:
        assert round(theme.ratio(fg, bg), 2) == round(contrast.ratio(fg, bg), 2), (fg, bg)
        assert (theme.ratio(fg, bg) >= 4.5) == (contrast.ratio(fg, bg) >= 4.5)
    assert theme.MIN_TEXT_RATIO == contrast.MIN["text"]


def test_the_choice_of_the_default_theme_is_recorded_and_the_identity_is_not_even_read(tmp_path):
    for k, text in enumerate((identity(block_with(status="draft"), status="draft"), identity(block_with(color__muted={"dark": "#4A5160"})), "{broken")):
        args, record = theme.theme_args(project(tmp_path, text, "chosen%d" % k), use_default=True)
        assert args == [] and (record["source"], record["reason"], record["colors"], record["fonts"]) == ("default", "chosen", {}, {})


# --- what is never a refusal: the default theme, and the record says why -----------------------------------------------------------


def test_no_identity_no_block_or_an_open_block_gives_the_default_theme_and_says_so(tmp_path):
    args, record = theme.theme_args(project(tmp_path, None))
    assert args == [] and (record["source"], record["reason"]) == ("default", "no_identity")
    args, record = theme.theme_args(project(tmp_path, "# Visual identity: Orchard Studio\n\n- Status: approved\n", "noblock"))
    assert args == [] and record["reason"] == "no_tokens_block"
    open_block = {"mode_default": "dark", "color": {"bg": {"dark": "#0B0B0C", "light": "#FFFFFF"}, "fg": {"dark": "#F4F4F5"}, "accent": {"dark": "#FBBF24"}},
                  "font": {"body": "system-ui"}}
    args, record = theme.theme_args(project(tmp_path, identity(open_block), "open"))
    assert args == [] and (record["source"], record["reason"]) == ("default", "open_block")
    shape_of_a_real_one = {"mode_default": "dark", "color": {"dark": {"bg": "#000000", "text": "#FFFFFF", "accent": "#07B6F0"}},
                           "font": {"display": {"family": "Inter", "weight": 800}, "chip": {"family": "JetBrains Mono", "weight": 500}}}
    args, record = theme.theme_args(project(tmp_path, identity(shape_of_a_real_one, status="aprovado (2026-10-14)"), "legacy"))
    assert args == [] and record["reason"] == "open_block", "a block with the roles of the first template is open: the default, said plainly"
    

def test_the_record_holds_closed_words_and_numbers_and_a_hash_that_follows_the_effective_theme(tmp_path):
    args, record = theme.theme_args(project(tmp_path, identity()))
    assert set(record) == {"source", "reason", "colors", "fonts", "notes", "hash"} and re.fullmatch(r"[0-9a-f]{64}", record["hash"])
    assert json.loads(json.dumps(record)) == record
    text = json.dumps(record)
    assert "Orchard" not in text and "green accent" not in text, "no word of the identity's prose"
    same, again = theme.theme_args(project(tmp_path, identity(prose="Another sentence, the same tokens."), "prose"))
    assert again["hash"] == record["hash"], "the prose of the identity is not the theme"
    recoloured = block_with(color__accent={"dark": "#E9C46A"})
    assert theme.theme_args(project(tmp_path, identity(recoloured), "recoloured"))[1]["hash"] != record["hash"]
    assert theme.theme_args(project(tmp_path, None, "none"))[1]["hash"] != record["hash"]
    assert theme.theme_args(project(tmp_path, identity(), "chosen"), use_default=True)[1]["hash"] != theme.theme_args(project(tmp_path, None, "none2"))[1]["hash"], \
        "no identity and the choice of the default are two different records"
    assert theme.theme_args(project(tmp_path, identity(), "same"))[1]["hash"] == record["hash"], "the same identity gives the same hash"


def test_the_arguments_are_the_renderers_own_flags_in_a_fixed_order(tmp_path):
    args, _ = theme.theme_args(project(tmp_path, identity()))
    assert args[0::2] == ["--color"] * 6 + ["--font"] * 3
    assert [a.partition("=")[0] for a in args[1:12:2]] == sorted(a.partition("=")[0] for a in args[1:12:2])
    assert all(re.fullmatch(r"[a-z_]+=#[0-9A-F]{6}", a) for a in args[1:12:2]) and all(re.fullmatch(r"[a-z]+=[a-z0-9-]+:\d00", a) for a in args[13::2])


def test_a_refusal_carries_only_a_closed_code_a_closed_field_and_a_fixed_sentence(tmp_path):
    secret_looking = block_with(color__accent={"dark": "sk-" + "a" * 40})
    e = refused(tmp_path, identity(secret_looking))
    assert theme.FIELD.fullmatch(e.field) and e.sentence in theme.SENTENCES.values()
    assert "sk-" not in str(e) + e.sentence + e.field
    e = theme.ThemeError("theme_bad_color", "../../etc/passwd")
    assert e.field == "", "a field that is not a path of key names is dropped"


def test_the_block_survives_the_documents_providers_round_trip_and_is_read_the_same(tmp_path):
    text = identity()
    assert notion_blocks.round_trip(text).count("```brand-tokens") == 1
    back = notion_blocks.round_trip(text)
    first = theme.theme_args(project(tmp_path, text))
    second = theme.theme_args(project(tmp_path, back, "roundtrip"))
    assert second == first and first[0]
    assert tokens.check_text(back) == []


def test_the_runtime_copy_of_the_checker_is_the_shared_source(tmp_path):
    assert (REPO / "runtime" / "check_brand_tokens.py").read_bytes() == (REPO / "shared" / "scripts" / "check_brand_tokens.py").read_bytes()
    assert (REPO / "skills" / "brand-identity" / "scripts" / "check_brand_tokens.py").read_bytes() == (REPO / "shared" / "scripts" / "check_brand_tokens.py").read_bytes()


def test_the_text_on_the_background_is_a_checked_pair_and_the_message_names_the_pair_that_fails(tmp_path):
    light_bg = block_with(color__bg={"dark": "#D8DEE9"})                 # a light page behind white-ish text: fine on the chip fill, not on the page
    value = contrast.ratio("#F4F7FB", "#D8DEE9")
    assert value < 4.5 and contrast.ratio("#F4F7FB", PRESETS["colors"]["chip_fill"]) >= 4.5
    e = refused(tmp_path, identity(light_bg))
    assert (e.code, e.field) == ("theme_low_contrast", "text_on_bg")
    assert e.sentence == theme.LOW_CONTRAST_SENTENCE % ("text on bg", "%.2f" % value) and "text on bg contrast is %.2f:1" % value in e.sentence
    assert ("text", "bg") in theme.PAIRS and ("chip_text", "chip_fill") in theme.PAIRS
    e = refused(tmp_path, identity(block_with(color__surface={"dark": "#E6ECF5"})))
    assert e.field == "text_on_chip_fill" and "text on chip fill" in e.sentence, "the pair that really fails is the one named"


def test_every_refusal_sentence_names_the_way_to_the_default_theme_and_the_review_edit_exists():
    captions = st.load("captions")
    for code, sentence in theme.SENTENCES.items():
        assert "choose the default theme" in sentence and "captions-edit" in sentence and "captions-done" in sentence, code
    assert "choose the default theme" in theme.LOW_CONTRAST_SENTENCE and "captions-edit" in theme.LOW_CONTRAST_SENTENCE
    assert "theme" in captions.OPS and captions.OPS["theme"] == {"choice"} and captions.THEME_CHOICES == ("identity", "default")
    edit = json.loads(theme.CHOICE.split("--text '")[1].split("'")[0])
    assert edit == [{"op": "theme", "choice": "default"}], "the command the sentence shows is the edit the review takes"


def test_a_fence_that_is_indented_or_tilde_is_read_and_one_that_is_cut_or_odd_is_refused(tmp_path):
    base = identity()
    for k, text in enumerate((base.replace("```brand-tokens", "~~~brand-tokens").replace("\n```\n", "\n~~~\n"),
                              base.replace("```brand-tokens", "  ```brand-tokens"))):
        args, record = theme.theme_args(project(tmp_path, text))
        assert args and record["source"] == "identity", k
    assert refused(tmp_path, base.replace("\n```\n", "\n")).code == "theme_block_invalid", "an unclosed fence is never ignored"
    assert refused(tmp_path, base.replace("```brand-tokens", "```brand-tokens json")).code == "theme_block_invalid"


def test_a_key_written_twice_in_the_block_is_refused(tmp_path):
    text = json.dumps(BLOCK).replace('"version": 1', '"version": 1, "version": 1')
    assert text != json.dumps(BLOCK) and refused(tmp_path, identity(text)).code == "theme_block_invalid"


def test_the_sentence_for_a_default_theme_says_why_in_one_fixed_line(tmp_path):
    for reason in ("no_identity", "no_tokens_block", "open_block", "chosen"):
        assert theme.describe({"source": "default", "reason": reason}).startswith("default theme: ")
    assert "old format" in theme.describe({"source": "default", "reason": "open_block"})
    assert theme.describe({"source": "identity", "reason": None}) == "" and theme.describe({}) == ""


PT_BR = """# Identidade visual: Estúdio Pomar

- Responsável: brand-identity
- Status: %s
- Data: 2026-10-14

## Em uma frase
Verde e escuro, uma só cor de destaque.

## Tokens
```brand-tokens
%s
```

## Perguntas em aberto
1. Nenhuma.
"""   # validate: allow english-only -- a fictional identity written in Brazilian Portuguese, the shape of a document in the artifact language


def test_a_document_in_brazilian_portuguese_is_read_by_its_own_status_words(tmp_path):
    draft = PT_BR % ("rascunho", json.dumps(block_with(status="draft")))
    e = refused(tmp_path, draft)
    assert e.code == "theme_draft"
    approved = PT_BR % ("aprovado (2026-10-14)", json.dumps(BLOCK))
    args, record = theme.theme_args(project(tmp_path, approved))
    assert record["source"] == "identity" and pairs(args, "--color")["accent"] == "#3DDC97"
    assert tokens.check_text(approved) == [] and [p["code"] for p in tokens.check_text(PT_BR % ("aprovado", json.dumps(block_with(status="draft"))))] == ["status_mismatch"]
    assert refused(tmp_path, PT_BR % ("pendente", json.dumps(BLOCK))).code == "theme_status_unknown"
