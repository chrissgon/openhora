"""The host page of the second contract, offline: the runtime and its shims are read against their pins, the entry's edits are the two there are and
nothing else, the values come from our parameters and our theme and nowhere else, the page is byte-for-byte what a golden says, and a planted value
cannot leave its attribute. Standard library and the repository's own code."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

import renderer_kit as K
import hf_second_kit as H
import _blocks
import _hf_host
from _text import Refusal
from _vocab import load_data

DATA = load_data()
GOLDEN = Path(__file__).parent / "golden" / "hf-admitted-page.sha256"
FACE = {"x": 240, "y": 300, "w": 600, "h": 480}
EDL = {"fps": 30, "theme": {"colors": dict(DATA["theme"]["colors"]), "fonts": {r: {"id": "default", "weight": DATA["theme"]["default_font_weight"][r]} for r in DATA["theme"]["font_roles"]}}}
FONTS = {"/fonts/display.ttf": (b"d", "font/ttf"), "/fonts/text.woff2": (b"t", "font/woff2")}


def refused(fn, *a, **k) -> Refusal:
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


@pytest.fixture()
def rt(tmp_path):
    return H.write_runtime(tmp_path)


def sample(tmp_path, rt, html=None, **over):
    html = html or H.component("clean")
    files = H.write_component(rt["registry"], html)
    served = H.served_of({H.FILE: html})
    shims = rt["runtime_dir"] + "/shims"
    runtime = _hf_host.load_runtime(rt["vendor"], shims, 30, "Chrome/1.0")
    block = H.entry(files, served, runtime["runtime_sha256"], **over)
    return block, runtime, _hf_host.check_edited(block, rt["registry"])


def test_the_runtime_is_read_against_its_pins_and_its_hash_covers_everything_that_can_change_what_is_drawn(rt):
    shims = rt["runtime_dir"] + "/shims"
    a = _hf_host.load_runtime(rt["vendor"], shims, 30, "Chrome/1.0")
    assert re.fullmatch(r"[0-9a-f]{64}", a["runtime_sha256"]) and len(a["shims"]) == 5 and b"__OH_FPS__" not in a["shims"][3] and b"= 30;" in a["shims"][3]
    assert _hf_host.load_runtime(rt["vendor"], shims, 30, "Chrome/1.0")["runtime_sha256"] == a["runtime_sha256"]
    assert len({a["runtime_sha256"], _hf_host.load_runtime(rt["vendor"], shims, 60, "Chrome/1.0")["runtime_sha256"],
                _hf_host.load_runtime(rt["vendor"], shims, 30, "Chrome/2.0")["runtime_sha256"]}) == 3
    assert refused(_hf_host.load_runtime, rt["vendor"], shims, 0, "x").code == "vendor_hash"


@pytest.mark.parametrize("victim", ["gsap.min.js", "hyperframe.runtime.iife.js", "hyperframe.manifest.json"])
def test_a_missing_or_changed_vendor_file_is_vendor_hash(rt, victim):
    shims = rt["runtime_dir"] + "/shims"
    path = Path(rt["vendor"]) / victim
    path.write_bytes(path.read_bytes() + b" ")
    e = refused(_hf_host.load_runtime, rt["vendor"], shims, 30, "x")
    assert (e.code, e.field) == ("vendor_hash", "vendor:" + victim)
    path.unlink()
    assert refused(_hf_host.load_runtime, rt["vendor"], shims, 30, "x").code == "vendor_hash"


@pytest.mark.parametrize("victim", list(H.FAKE_SHIMS))
def test_a_changed_shim_is_vendor_hash(rt, victim):
    path = Path(rt["runtime_dir"]) / "shims" / victim
    path.write_text(path.read_text() + "\n")
    e = refused(_hf_host.load_runtime, rt["vendor"], rt["runtime_dir"] + "/shims", 30, "x")
    assert (e.code, e.field) == ("vendor_hash", "shims:" + victim)


def test_the_committed_runtime_dir_is_the_image_s_and_only_test_mode_can_name_another(monkeypatch, tmp_path):
    here = str(K.RENDERER)
    monkeypatch.setenv("RENDERER_HF_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("RENDERER_TEST", raising=False)
    assert _hf_host.runtime_dir(here) == os.path.join(here, "hf-runtime")
    monkeypatch.setenv("RENDERER_TEST", "1")
    assert _hf_host.runtime_dir(here) == str(tmp_path)


def test_the_edits_are_e1_and_e2_and_a_count_that_differs_is_refused(rt):
    html = H.component("clean")
    files = {H.FILE: html.encode()}
    out = _hf_host.apply_edits(files, ["E1", "E2:Inter"], {"Inter": "oh-text"})[H.FILE].decode()
    assert _hf_host.CDN_GSAP not in out and _hf_host.LOCAL_GSAP in out and "Inter" not in out and "var(--font-body, oh-text, system-ui" in out
    assert out.count(_hf_host.LOCAL_GSAP) == 1 and _hf_host.apply_edits(files, [], {}) == files
    twice = {H.FILE: (html + _hf_host.CDN_GSAP).encode()}
    for bad, fmap in ((["E1"], {}),):
        assert refused(_hf_host.apply_edits, twice, bad, fmap).code == "block_edit"
    assert refused(_hf_host.apply_edits, {H.FILE: b"<p>no cdn</p>"}, ["E1"], {}).field == "E1"
    assert refused(_hf_host.apply_edits, {H.FILE: b"<p>no family</p>"}, ["E2:Inter"], {"Inter": "oh-text"}).code == "block_edit"
    assert refused(_hf_host.apply_edits, files, ["E3"], {}).code == "block_edit"
    assert refused(_hf_host.apply_edits, files, ["E2:Arial"], {"Inter": "oh-text"}).code == "block_edit"


def test_a_file_that_differs_from_what_the_entry_pinned_is_block_hash_before_anything_is_drawn(tmp_path, rt):
    block, runtime, files = sample(tmp_path, rt)
    assert _hf_host.served_digest(files) == block["served_sha256"]
    assert refused(_hf_host.check_edited, dict(block, served_sha256="3" * 64), rt["registry"]).code == "block_hash"
    path = Path(rt["registry"]) / H.COMPONENT_DIR / H.FILE
    path.write_text(path.read_text() + " ")
    assert refused(_hf_host.check_edited, block, rt["registry"]).code == "block_hash"
    path.unlink()
    assert refused(_hf_host.check_edited, block, rt["registry"]).code == "block_hash"


def test_the_recorded_test_must_be_at_these_hashes(tmp_path, rt):
    block, runtime, files = sample(tmp_path, rt)
    _hf_host.prove(block, block["served_sha256"], runtime["runtime_sha256"])
    _hf_host.prove(block, block["served_sha256"], None)
    assert refused(_hf_host.prove, block, block["served_sha256"], "0" * 64).code == "block_not_proven"
    assert refused(_hf_host.prove, block, "0" * 64, runtime["runtime_sha256"]).code == "block_not_proven"
    assert refused(_hf_host.prove, dict(block, determinism={}), block["served_sha256"], None).code == "block_not_proven"
    assert refused(_hf_host.prove, {k: v for k, v in block.items() if k != "determinism"}, block["served_sha256"], None).code == "block_not_proven"
    bad = dict(block["determinism"], blocked=1)
    assert refused(_hf_host.prove, dict(block, determinism=bad), block["served_sha256"], None).code == "block_not_proven"


THEME = (DATA["theme"]["colors"], {"display": "oh-display, x", "text": "oh-text, x", "mono": "mono"})


def test_every_declared_variable_gets_a_value_from_a_parameter_or_a_fixed_one_and_theme_variables_come_from_the_theme(tmp_path, rt):
    block, runtime, files = sample(tmp_path, rt)
    variables, css = _hf_host.values_for(block, files, {"text": "Hello", "color": "#112233"}, *THEME)
    assert variables == {"text": "Hello"} and css["--brand"] == "#112233" and css["--fg"] == DATA["theme"]["colors"]["text"] and css["--font-body"] == "oh-text, x"
    variables, css = _hf_host.values_for(block, files, {"text": "Hello"}, *THEME)
    assert "--brand" not in css                                                    # an optional parameter the beat left out: the component's own default
    unbound = dict(block, bind={"color": "css:--brand"}, params={"color": {"type": "color"}})
    assert (refused(_hf_host.values_for, unbound, files, {"color": "#112233"}, *THEME).code) == "admitted_unbound"
    assert refused(_hf_host.values_for, dict(block, bind={"text": "var:nope", "color": "css:--brand"}), files, {"text": "x"}, *THEME).code == "admitted_unbound"
    assert refused(_hf_host.values_for, dict(block, fixed={"nope": 1}), files, {"text": "x"}, *THEME).code == "admitted_unbound"


def test_a_palette_token_is_the_themes_colour_and_a_parameter_wins_over_the_themes_default_for_the_same_property(tmp_path, rt):
    block, runtime, files = sample(tmp_path, rt, theme_vars=dict(H.THEME_VARS, **{"--brand": "accent"}))
    colors = DATA["theme"]["colors"]
    assert _hf_host.values_for(block, files, {"text": "x"}, *THEME)[1]["--brand"] == colors["accent"]                  # no parameter given: the theme's default
    assert _hf_host.values_for(block, files, {"text": "x", "color": "muted"}, *THEME)[1]["--brand"] == colors["muted"]   # a token: the theme's colour for it
    assert _hf_host.values_for(block, files, {"text": "x", "color": "#112233"}, *THEME)[1]["--brand"] == "#112233"        # a hex value stays as it is


def test_the_background_variable_is_never_mapped_and_an_unknown_role_is_refused(tmp_path, rt):
    block, runtime, files = sample(tmp_path, rt)
    for tv in ({"--bg": "bg"}, {"--x": "nope"}, {"x": "text"}):
        assert refused(_hf_host.values_for, dict(block, theme_vars=tv), files, {"text": "x"}, *THEME).code == "admitted_unbound"
    assert refused(_hf_host.values_for, dict(block, bind={"text": "var:text", "color": "css:--bg"}), files, {"text": "x", "color": "#112233"}, *THEME).code == "admitted_unbound"
    assert refused(_hf_host.values_for, block, files, {"text": "x", "color": "#112233; background: red"}, *THEME).code == "param_out_of_bounds"


def test_a_number_outside_the_components_own_range_or_of_the_wrong_type_is_param_out_of_bounds(tmp_path, rt):
    html = H.component("clean").replace('"default": "New" }', '"default": "New" }, { "id": "scale", "type": "number", "default": 1, "min": 0.8, "max": 2 }')
    block, runtime, files = sample(tmp_path, rt, html, fixed={"scale": 1.5})
    assert _hf_host.values_for(block, files, {"text": "x"}, *THEME)[0] == {"text": "x", "scale": 1.5}
    for value in (3, 0.1, "1.5", True):
        assert refused(_hf_host.values_for, dict(block, fixed={"scale": value}), files, {"text": "x"}, *THEME).code == "param_out_of_bounds"
    assert refused(_hf_host.values_for, dict(block, fixed={}), files, {"text": "x"}, *THEME).code == "admitted_unbound"


def page(tmp_path, rt, text="Name every dollar"):
    block, runtime, files = sample(tmp_path, rt)
    variables, css = _hf_host.values_for(block, files, {"text": text}, *THEME)
    faces = _hf_host.theme_fonts(FONTS, {"display": {"weight": 800}, "text": {"weight": 500}, "mono": {"weight": 500}})
    box = _hf_host.box_of(DATA, FACE)
    return _hf_host.build_page(block, files, runtime, variables, css, box, faces, 2.0, 0), box, faces


def test_the_page_is_what_the_golden_says_and_the_runtime_comes_first_the_template_has_its_id_and_the_host_holds_the_box(tmp_path, rt):
    raw, box, faces = page(tmp_path, rt)
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == GOLDEN.read_text().strip(), "the page changed: if it is on purpose, write %s to %s" % (digest, GOLDEN)
    text = raw.decode()
    assert text.index("hyperframes://injected/early/0") < text.index("/h/vendor/gsap.min.js") < text.index("hyperframes://injected/runtime/0") < text.index('<template id="oh-test-pop-template">')
    assert text.index('id="oh-host"') < text.index("hyperframes://injected/late/0") and text.count('id="oh-host"') == 1
    assert (box["x"], box["y"], box["w"], box["h"]) == (65, 110, 950, 172) and "left:65px;top:110px;width:950px;height:172px" in text
    assert "@font-face{font-family:oh-display;src:url(/fonts/display.ttf) format('truetype');font-weight:800" in text and "oh-text" in text and "oh-mono" not in text.split("</style>")[0]
    assert [f["family"] for f in faces] == ["oh-display", "oh-text"] and _hf_host.fonts_spec(faces, DATA["theme"]["system_fallback"])["system"] == ["Menlo"]
    assert 'data-composition-variables=' in text.split("<head>")[0] and 'data-variable-values="{&quot;text&quot;: &quot;Name every dollar&quot;}"' in text


def test_a_planted_value_is_escaped_and_cannot_leave_its_attribute(tmp_path, rt):
    raw, box, faces = page(tmp_path, rt, text='\'"><script>alert(1)</script>')
    text = raw.decode()
    assert "<script>alert(1)" not in text and "&lt;script&gt;alert(1)" in text and "&#x27;" in text
    assert text.count("<script>") == len(re.findall(r"<script>", text)) and "alert(1)" not in text.replace("&lt;script&gt;alert(1)&lt;/script&gt;", "")


def test_prepare_builds_one_page_per_beat_the_proofs_and_only_for_blocks_that_run_on_the_second_contract(tmp_path, rt):
    block, runtime, files = sample(tmp_path, rt)
    blocks = H.blocks_folder(tmp_path, block)
    cat = _blocks.load_catalogue(blocks)
    plain = {"block": "oh:keyword", "params": {"text": "x"}, "face": FACE}
    drawn = {"block": H.NAME, "params": {"text": "Hello"}, "face": FACE}
    none = _hf_host.prepare(catalogue=cat, engine="ffmpeg", timeline={"beats": [plain]}, data=DATA, edl=EDL, font_serve={}, vendor=rt["vendor"], registry=rt["registry"],
                            shims=rt["runtime_dir"] + "/shims", browser_version="Chrome/1.0")
    assert none["pages"] == {} and none["serve"] == {} and none["blocks"] == [] and none["proofs"] == {}
    out = _hf_host.prepare(catalogue=cat, engine="ffmpeg", timeline={"beats": [plain, drawn, dict(drawn, params={"text": "Two"})]}, data=DATA, edl=EDL, font_serve=FONTS,
                           vendor=rt["vendor"], registry=rt["registry"], shims=rt["runtime_dir"] + "/shims", browser_version="Chrome/1.0")
    assert out["pages"] == {H.NAME: {1: "/h/b1/index.html", 2: "/h/b2/index.html"}} and set(out["serve"]) == {"/h/vendor/gsap.min.js", "/h/b1/index.html", "/h/b2/index.html"}
    assert out["proofs"][H.NAME] == {"served_sha256": block["served_sha256"], "runtime_sha256": runtime["runtime_sha256"]}
    assert b"Hello" in out["serve"]["/h/b1/index.html"][0] and b"Two" in out["serve"]["/h/b2/index.html"][0] and out["blocks"] == [H.NAME]
    assert out["fonts"]["faces"] == [["oh-display", "800", "normal"], ["oh-display", "500", "normal"], ["oh-text", "500", "normal"], ["oh-text", "800", "normal"]]      # the default theme is Inter (PF-b1, B2 (a)): a family carries every Inter file served
    dry = _hf_host.prepare(catalogue=cat, engine="ffmpeg", timeline={"beats": [drawn]}, data=DATA, edl=EDL, font_serve={}, vendor=rt["vendor"], registry=rt["registry"],
                           shims=rt["runtime_dir"] + "/shims", browser_version=None)
    assert dry["proofs"][H.NAME]["runtime_sha256"] == ""
