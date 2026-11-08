"""The composed page of the HyperFrames engine (`_hf_compose.py`): the base page plus the captions and the beats, in ONE root composition.
Offline: the page is written and read as text (no browser, no HyperFrames, no docker). The edit list is made from the kit's fictional
transcript, the beats from its fictional post (no cutaway and no pip: this engine does not draw them), the blocks folder is a copy of the committed
one with a test engines file and a fictional tier-B block. Every input is synthetic."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess

import pytest

import renderer_kit as K
import _blocks
import _edl
import _hf_compose as C
import _hf_page
import _layout
import _payload
from _text import Refusal

HF_RENDER = K.RENDERER / "hyperframes-image" / "hf_render.py"
spec = importlib.util.spec_from_file_location("hf_render_for_compose", HF_RENDER)
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    return K.hf_documents(tmp_path_factory.mktemp("docs"))


def blocks_folder(tmp_path, mixed=False, name="blocks"):
    folder = tmp_path / name
    shutil.copytree(K.BLOCKS, folder)
    K.write_hf_compose_blocks(folder, mixed=mixed)
    return str(folder)


def catalogue_of(tmp_path, mixed=False):
    return _blocks.load_catalogue(blocks_folder(tmp_path, mixed))


def write(docs, catalogue, folder, **over):
    data, edl, beats, vocab = (over.get(k, v) for k, v in zip(("data", "edl", "beats", "vocab"), copy.deepcopy(docs)))
    os.makedirs(folder, exist_ok=True)
    return C.write_page(data, edl, beats, vocab, catalogue, str(folder), edl["fps"])


def refused(docs, catalogue, folder, **over) -> Refusal:
    with pytest.raises(Refusal) as caught:
        write(docs, catalogue, folder, **over)
    return caught.value


def text_of(folder, name="index.html") -> str:
    return (folder / name).read_text(encoding="utf-8")


def files_of(folder) -> dict:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def texts_of(docs) -> list:
    """Every word of the transcript and every text parameter of the beats that is drawn."""
    _, edl, beats, _ = docs
    found = {w["text"] for w in edl["words"]}
    for e in beats["overlays"]:
        for value in e["params"].values():
            if isinstance(value, str) and len(value) > 4:
                found.update(part.strip() for part in value.split("|"))
    return sorted(t for t in found if len(t) >= 6)                      # a short word occurs inside markup names ("name", "card"); these do not


# ---------------------------------------------------------------- the page is the same bytes and holds no text

@pytest.mark.parametrize("mixed", [False, True])
def test_two_calls_write_the_same_bytes_in_the_same_files(tmp_path, docs, mixed):
    catalogue = catalogue_of(tmp_path, mixed)
    one, two = write(docs, catalogue, tmp_path / "a"), write(docs, catalogue, tmp_path / "b")
    assert one == two
    assert files_of(tmp_path / "a") == files_of(tmp_path / "b")
    assert set(files_of(tmp_path / "a")) == {"index.html", "vars.json", "blocks/oh-caption.html", "blocks/oh-list.html", "blocks/oh-number.html",
                                              "blocks/oh-quote.html"} | (set() if mixed else {"blocks/oh-keyword.html"})


def test_no_text_value_is_in_index_html_and_every_text_is_in_vars_json(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    write(docs, catalogue, tmp_path / "p")
    page, variables = text_of(tmp_path / "p"), text_of(tmp_path / "p", "vars.json")
    words = texts_of(docs)
    assert len(words) > 10 and "Name every dollar" in words and "Review" in words
    for word in words:
        assert word not in page, word
        assert word in variables, word
    for name in ("oh-caption.html", "oh-list.html", "oh-number.html", "oh-quote.html"):
        for word in words:
            assert word not in text_of(tmp_path / "p", "blocks/" + name)


def test_the_variables_hold_the_payloads_the_ffmpeg_engine_gives_its_pages(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    result = write(docs, catalogue, tmp_path / "p")
    variables = json.loads(text_of(tmp_path / "p", "vars.json"))
    data, edl, beats, vocab = copy.deepcopy(docs)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    by_index = {w["index"]: w for w in edl["words"]}
    assert variables["ra"]["caption"] == [json.loads(json.dumps(_payload.caption_data(data, edl, c, by_index, edl["fps"]))) for c in timeline["captions"]]
    keyword = [e for e in timeline["beats"] if e["preset"] == "keyword"]
    assert variables["inst"] == [json.loads(json.dumps(_payload.beat_data(data, e, edl["fps"], edl))) for e in keyword]
    assert result["captions_drawn"] == len(timeline["captions"]) and result["beats_drawn"] == len(timeline["beats"])
    assert set(variables) == {"duration", "fps", "zooms", "inst", "ra"}
    assert variables["zooms"] == json.loads(text_of(tmp_path / "p", "vars.json"))["zooms"]


def test_the_defaults_in_the_page_are_numbers_only_and_the_base_parts_are_the_base_pages(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    write(docs, catalogue, tmp_path / "p")
    page = text_of(tmp_path / "p")
    defaults = re.search(r"var V = Object\.assign\((\{.*?\}),\n", page, re.S).group(1)
    doc = json.loads(defaults)
    assert doc["inst"] == [] and doc["ra"] == {} and set(doc) == {"duration", "fps", "zooms", "inst", "ra"}
    base = tmp_path / "base"
    base.mkdir()
    edl = docs[1]
    _hf_page.write_page(edl, str(base), width=1080, height=1920, fps=edl["fps"], background="#0B0F14")
    assert text_of(base).count('class="zw"') == page.count('class="zw"') and text_of(base).count("<video ") == page.count("<video ")


# ---------------------------------------------------------------- gsap instances

def test_every_gsap_instance_is_clipped_to_its_band_and_scoped_to_itself(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    result = write(docs, catalogue, tmp_path / "p")
    page = text_of(tmp_path / "p")
    data, edl, beats, vocab = copy.deepcopy(docs)
    keyword = [e for e in _edl.resolve_timeline(edl, beats, vocab, data)["beats"] if e["preset"] == "keyword"]
    instances = re.findall(r'<div id="hf-inst-(\d+)" class="hf-inst" data-hf-zone="(\w+)" data-hf-block="([^"]+)" style="([^"]+)"', page)
    assert len(instances) == len(keyword) == 1 and result["runtimes"]["hf:demo-pop"] == "gsap"
    for (n, zone, block, style), entry in zip(instances, keyword):
        band = _layout.zones(data, entry["face"])["card"]
        assert zone == "card" and block == "hf:demo-pop"
        assert "contain:paint; overflow:clip" in style and "visibility:hidden" in style
        assert "top:%spx" % C.px(band[0]) in style and "height:%spx" % C.px(band[1] - band[0]) in style and "left:0" in style and "width:1080px" in style
        assert "@scope (#hf-inst-%s) {" % n in page
        start = entry["start_frame"] / float(edl["fps"])
        assert 'main.add(tl_%s, %s);' % (n, _hf_page.num(start)) in page
        assert 'main.set("#hf-inst-%s", {visibility:"visible"}, %s);' % (n, _hf_page.num(start)) in page
        assert 'main.set("#hf-inst-%s", {visibility:"hidden"}, %s);' % (n, _hf_page.num(entry["end_frame"] / float(edl["fps"]))) in page
        assert re.search(r'const tl_%s = gsap\.timeline\(\); build_0\(document\.getElementById\("hf-inst-%s"\), tl_%s, V\.inst\[%s\], ' % (n, n, n, n), page)


def test_the_blocks_script_is_emitted_once_per_block_under_its_own_name(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    write(docs, catalogue, tmp_path / "p")
    page = text_of(tmp_path / "p")
    assert page.count("function build_0(root, tl, data, ctx)") == 1 and "function build(" not in page
    assert page.index("function build_0") < page.index("const tl_0")
    assert page.index('window.__timelines["main"] = main;') > page.index("main.set(\"#hf-inst-0\"")
    assert page.count('window.__timelines["main"]') == 1


def test_the_card_layer_is_below_the_caption_layer_and_the_instances_are_inside_the_root(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    write(docs, catalogue, tmp_path / "p")
    page = text_of(tmp_path / "p")
    root = page[page.index('<div id="root"'):page.index("</div>\n<script>")]
    assert '<div id="hf-inst-0"' in root and 'data-hf-key="caption"' in root and root.count("<iframe") == 4
    assert page.index('data-hf-zone="card" data-hf-block="hf:demo-pop"') < page.index('data-hf-key="caption"')
    assert '[data-hf-zone="card"]{z-index:1}' in page and '[data-hf-zone="caption"]{z-index:2}' in page


# ---------------------------------------------------------------- renderat pages

def test_a_renderat_block_is_one_iframe_driven_by_one_getter_setter_tween(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=False)
    result = write(docs, catalogue, tmp_path / "p")
    page = text_of(tmp_path / "p")
    keys = ["caption", "oh:keyword", "oh:list", "oh:number", "oh:quote"]
    assert [m for m in re.findall(r'data-hf-key="([^"]+)"', page)] == keys and result["runtimes"] == {
        "oh:caption": "renderat", "oh:keyword": "renderat", "oh:list": "renderat", "oh:number": "renderat", "oh:quote": "renderat"}
    for j, key in enumerate(keys):
        assert 'drive(%s, v)' % json.dumps(key) in page and "main.fromTo(D_%d, {at: 0}, {at: " % j in page and 'ease: "none", immediateRender: true}, 0);' in page
    ranges = json.loads(re.search(r"var RA = (\{.*\});", page).group(1))
    assert list(ranges) == sorted(ranges) and set(ranges) == set(keys)
    variables = json.loads(text_of(tmp_path / "p", "vars.json"))
    assert {k: len(v) for k, v in variables["ra"].items()} == {k: len(v) for k, v in ranges.items()}
    assert all(a < b for spans in ranges.values() for a, b in spans)
    assert "build_" not in page and "@scope" not in page


def test_a_renderat_page_is_the_blocks_page_with_the_guard_the_theme_and_the_fonts_after_its_charset(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=False)
    write(docs, catalogue, tmp_path / "p")
    out = text_of(tmp_path / "p", "blocks/oh-keyword.html")
    original = (K.BLOCKS / "oh" / "keyword" / "renderat.html").read_text(encoding="utf-8")
    head, tail = original.split('<meta charset="utf-8">', 1)
    assert out.startswith(head + '<meta charset="utf-8">\n<style>\n@font-face') and out.endswith(tail)
    assert out.index('<meta charset="utf-8">') < 100
    for forbidden in ("Date.now = boom", "Math.random = boom", "window.setTimeout = boom", "window.requestAnimationFrame = boom", "window.fetch = boom",
                      "window.XMLHttpRequest = function", "window.WebSocket = function", "window.Worker = function"):
        assert forbidden in out
    assert 'rs.setProperty("--c-accent", "#FFC93C")' in out and 'rs.setProperty("--font-display", "\\"Inter\\", sans-serif")' in out
    assert 'src:url("../fonts/inter-800.woff2")' in out and "window.__frame = function (t, data) { window.renderAt(t, data); };" in out
    assert out.index("Date.now = boom") < out.index("window.renderAt = function")            # the guard is up before the page's own script


def test_a_page_without_a_head_is_refused_and_one_with_no_charset_line_gets_the_insert_after_its_head():
    pairs = [("--c-bg", "#0B0F14")]
    fonts = {"display": C.FONT_FILES["inter-800"]}
    assert C.renderat_page("<html><head>\n<style></style></head></html>", "oh:x", pairs, fonts).startswith("<html><head>\n<style>\n@font-face")
    with pytest.raises(Refusal) as caught:
        C.renderat_page("<html><body></body></html>", "oh:x", pairs, fonts)
    assert (caught.value.code, caught.value.field) == ("block_lint", "oh:x head")


def test_a_block_with_both_runtimes_is_drawn_with_gsap_first(tmp_path, docs):
    folder = blocks_folder(tmp_path, mixed=True)
    port = json.loads(open(os.path.join(folder, "hf", "demo-pop", "block.json")).read())
    both = dict(port, name="hf:demo-both", implementations={"renderat": "renderat.html", "gsap": "gsap.html"})
    os.mkdir(os.path.join(folder, "hf", "demo-both"))
    shutil.copy(os.path.join(folder, "hf", "demo-pop", "gsap.html"), os.path.join(folder, "hf", "demo-both", "gsap.html"))
    shutil.copy(os.path.join(K.BLOCKS, "oh", "keyword", "renderat.html"), os.path.join(folder, "hf", "demo-both", "renderat.html"))
    (open(os.path.join(folder, "hf", "demo-both", "block.json"), "w")).write(json.dumps(both))
    gsap = open(os.path.join(folder, "hf", "demo-both", "gsap.html")).read().replace("hf:demo-pop", "hf:demo-both")
    open(os.path.join(folder, "hf", "demo-both", "gsap.html"), "w").write(gsap)
    engine = json.loads(open(os.path.join(folder, "engines", "hyperframes.json")).read())
    engine["presets"]["keyword"] = "hf:demo-both"
    open(os.path.join(folder, "engines", "hyperframes.json"), "w").write(json.dumps(engine))
    _blocks.write_pins(folder)
    result = write(docs, _blocks.load_catalogue(folder), tmp_path / "p")
    assert result["runtimes"]["hf:demo-both"] == "gsap" and not (tmp_path / "p" / "blocks" / "hf-demo-both.html").exists()


# ---------------------------------------------------------------- fonts

def test_the_fonts_are_the_three_allow_listed_files_and_the_theme_never_names_a_system_font(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    result = write(docs, catalogue, tmp_path / "p")
    page = text_of(tmp_path / "p")
    assert result["fonts_used"] == {"display": "inter-800.woff2", "mono": "jetbrains-mono-500.woff2", "text": "inter-500.woff2"}
    for needle in ("-apple-system", "Helvetica", "Arial", "Menlo", "system-ui"):
        assert needle not in page
    assert page.count("@font-face") == 3 and '--font-display:"Inter", sans-serif' in page and '--font-mono:"JetBrains Mono", monospace' in page
    assert "--weight-display:800" in page and "--c-accent:#FFC93C" in page


def test_the_font_table_is_the_allow_list_file():
    rows = json.loads((K.RENDERER / "assets" / "fonts" / "allowlist.json").read_text())["fonts"]
    assert C.FONT_FILES == {row["id"]: (row["family"], row["weight"], row["file"]) for row in rows}
    assert set(C.DEFAULT_FONT.values()) <= set(C.FONT_FILES) and set(C.DEFAULT_FONT) == {"display", "text", "mono"}
    assert set(R.FONT_FILES) == {row[2] for row in C.FONT_FILES.values()}
    assert {row["file"]: row["sha256"] for row in rows} == R.FONT_FILES


@pytest.mark.parametrize("font_id,weight", [("inter-800", 800), ("inter-500", 500), ("jetbrains-mono-500", 500)])
def test_each_allow_listed_id_maps_to_its_file(tmp_path, docs, font_id, weight):
    edl = copy.deepcopy(docs[1])
    edl["theme"]["fonts"]["display"] = {"id": font_id, "weight": weight}
    used = C.map_fonts(edl)
    assert used["display"] == C.FONT_FILES[font_id]


def test_default_maps_to_inter_and_jetbrains_by_role_and_an_unknown_id_or_a_wrong_weight_is_refused(tmp_path, docs):
    edl = copy.deepcopy(docs[1])
    for role in edl["theme"]["fonts"]:
        edl["theme"]["fonts"][role]["id"] = "default"
    assert {r: f[2] for r, f in C.map_fonts(edl).items()} == {"display": "inter-800.woff2", "text": "inter-500.woff2", "mono": "jetbrains-mono-500.woff2"}
    catalogue = catalogue_of(tmp_path, mixed=True)
    changes = [("display", {"id": "no-such-font", "weight": 800}), ("text", {"id": "inter-500", "weight": 600}), ("mono", {"id": "default", "weight": 700})]
    for role, spec_ in changes:
        edl2 = copy.deepcopy(docs[1])
        edl2["theme"]["fonts"][role] = spec_
        err = refused(docs, catalogue, tmp_path / ("f-" + role), edl=edl2)
        assert (err.code, err.field) == ("font_not_on_engine", "edl.theme.fonts.%s" % role)
        assert not os.listdir(tmp_path / ("f-" + role))


def test_the_composed_page_and_every_block_page_pass_the_image_font_guard(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    write(docs, catalogue, tmp_path / "p")
    R.check_fonts(text_of(tmp_path / "p"))
    for name in sorted(os.listdir(tmp_path / "p" / "blocks")):
        R.check_fonts(text_of(tmp_path / "p", "blocks/" + name), "blocks:" + name)
    R.check_project(str(_with_media(tmp_path / "p")))


def _with_media(project):
    (project / "media").mkdir(exist_ok=True)
    (project / "media" / "proxy.mp4").write_bytes(b"\0" * 8)
    return project


# ---------------------------------------------------------------- the engine, tiers and presets

def tier_a_blocks(tmp_path, caption=False):
    """A copy of the blocks with one fictional tier-A overlay for the keyword preset (and, when `caption`, a tier-A caption block, which the
    composer must refuse), on an engine that runs gsap and renderat."""
    folder = tmp_path / "tier-a"
    shutil.copytree(K.BLOCKS, folder)
    entry = dict(K.HF_ENTRY, params={"text": {"type": "text", "max": 24, "required": True}, "icon": {"type": "icon"}}, samples=[{"text": "Name every dollar"}])
    blocks, presets = [entry], dict(K.OH_PRESETS, keyword="hf:demo-pop")
    if caption:
        blocks.append(dict(entry, name="hf:demo-caption", kind="caption", preset="caption", band="caption", natural_duration=None, params={},
                           samples=[{}], implementations={"gsap": "demo-caption.html"}, files={"demo-caption.html": "c" * 64}))
        presets["caption"] = "hf:demo-caption"
    allow = json.loads((folder / "hf" / "allowlist.json").read_text())
    allow.update(registry_commit="a" * 40, blocks=blocks)
    (folder / "hf" / "allowlist.json").write_text(json.dumps(allow, indent=1))
    (folder / "engines" / "hyperframes.json").write_text(json.dumps(
        {"schema_version": 1, "engine": "hyperframes", "note": "a fictional engine for the tests", "runtimes": ["gsap", "renderat"], "presets": presets}, indent=1))
    _blocks.write_pins(str(folder))
    return _blocks.load_catalogue(str(folder))


def test_a_tier_a_beat_is_a_placeholder_and_a_row_of_instances_json_and_its_parameters_are_in_vars_json(tmp_path, docs):
    catalogue = tier_a_blocks(tmp_path)
    data, edl, beats, vocab = copy.deepcopy(docs)
    edl["captions"]["chunks"] = []
    beats["overlays"] = [e for e in beats["overlays"] if e["preset"] == "keyword"]
    result = write(docs, catalogue, tmp_path / "p", edl=edl, beats=beats)
    files = files_of(tmp_path / "p")
    assert set(files) == {"index.html", "vars.json", "instances.json"}
    page = text_of(tmp_path / "p")
    first = beats["overlays"][0]
    assert 'id="hf-inst-0" class="hf-inst" data-hf-zone="card" data-hf-tier-a="0"' in page and "try { __hfTierA[0](main, V, gsap); } catch (e) { if (!window.__hfEscape) throw e; }" in page
    assert "<template" not in page and first["params"]["text"] not in page
    timeline = _edl.resolve_timeline(copy.deepcopy(edl), copy.deepcopy(beats), vocab, data)
    entry = [e for e in timeline["beats"] if e["id"] == first["id"]][0]
    rows = json.loads(text_of(tmp_path / "p", "instances.json"))
    top, bottom = _layout.zones(data, entry["face"])["card"]
    assert rows == {"0": {"name": "hf:demo-pop", "files": {"demo-pop.html": "b" * 64}, "implementation": "demo-pop.html", "start": entry["start_frame"] / float(edl["fps"]),
                          "end": entry["end_frame"] / float(edl["fps"]), "band": [top, bottom - top]}}
    variables = json.loads(text_of(tmp_path / "p", "vars.json"))
    assert variables["inst"] == [first["params"]] and variables["ra"] == {}
    assert result["runtimes"] == {"hf:demo-pop": "gsap"} and result["beats_drawn"] == 1 and result["captions_drawn"] == 0
    assert result["blocks"] == {"hf:demo-pop": C.tier_a_digest(catalogue["blocks"]["hf:demo-pop"])}
    assert result["blocks"]["hf:demo-pop"] == hashlib.sha256(("%s  demo-pop.html\n" % ("b" * 64)).encode()).hexdigest()
    assert files == files_of(_write_again(tmp_path, docs, catalogue, edl, beats))


def _write_again(tmp_path, docs, catalogue, edl, beats):
    write(docs, catalogue, tmp_path / "q", edl=edl, beats=beats)
    return tmp_path / "q"


def test_a_tier_a_caption_block_is_refused_caption_tier_b_only_and_nothing_is_written(tmp_path, docs):
    catalogue = tier_a_blocks(tmp_path, caption=True)
    err = refused(docs, catalogue, tmp_path / "p")
    assert (err.code, err.field) == ("caption_tier_b_only", "edl.captions") and os.listdir(tmp_path / "p") == []


def test_a_beat_of_a_preset_the_engine_does_not_list_is_refused_and_nothing_is_written(tmp_path, docs):
    catalogue = catalogue_of(tmp_path)
    data, edl, beats, vocab = copy.deepcopy(docs)
    beats["layouts"] = [{"id": "L1", "beat": 7, "preset": "cutaway", "params": {"asset": "beat7", "fit": "cover"}, "word_from": edl["words"][0]["index"],
                         "word_to": edl["words"][1]["index"], "score": 1.0}]
    err = refused(docs, catalogue, tmp_path / "p", beats=beats)
    assert (err.code, err.field) == ("preset_not_on_engine", "beats.L1") and os.listdir(tmp_path / "p") == []


def test_a_render_with_no_engines_file_is_refused_engine_unknown(tmp_path, docs):
    folder = tmp_path / "bare"
    shutil.copytree(K.BLOCKS, folder)
    os.unlink(folder / "engines" / "hyperframes.json")
    _blocks.write_pins(str(folder))
    catalogue = _blocks.load_catalogue(str(folder))
    err = refused(docs, catalogue, tmp_path / "p")
    assert (err.code, err.field) == ("engine_unknown", "hyperframes")


def test_a_block_the_engine_cannot_run_is_refused_block_not_on_engine(tmp_path, docs):
    folder = blocks_folder(tmp_path, mixed=True)
    engine = json.loads(open(os.path.join(folder, "engines", "hyperframes.json")).read())
    engine["runtimes"] = ["renderat"]
    engine["presets"]["keyword"] = "oh:keyword"
    open(os.path.join(folder, "engines", "hyperframes.json"), "w").write(json.dumps(engine))
    _blocks.write_pins(folder)
    data, edl, beats, vocab = copy.deepcopy(docs)
    beats["overlays"][0]["block"] = "hf:demo-pop"
    err = refused(docs, _blocks.load_catalogue(folder), tmp_path / "p", beats=beats)
    assert err.code == "block_not_on_engine" and os.listdir(tmp_path / "p") == []


def test_a_block_of_the_wrong_preset_and_a_beat_with_bad_params_are_refused(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    _, _, beats, _ = copy.deepcopy(docs)
    first = next(e for e in beats["overlays"] if e["preset"] == "list")
    first["block"] = "hf:demo-pop"
    assert refused(docs, catalogue, tmp_path / "a", beats=beats).code == "block_preset_mismatch"
    _, _, beats, _ = copy.deepcopy(docs)
    next(e for e in beats["overlays"] if e["preset"] == "number")["params"]["bogus"] = 1
    assert refused(docs, catalogue, tmp_path / "b", beats=beats).code == "undeclared_param"


def test_a_text_the_checker_would_clean_is_refused_before_anything_is_written(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    _, _, beats, _ = copy.deepcopy(docs)
    quote = next(e for e in beats["overlays"] if e["preset"] == "quote")
    quote["params"]["text"] = "Small steps beat big plans.  "
    err = refused(docs, catalogue, tmp_path / "p", beats=beats)
    assert err.code in ("text_not_clean", "text_too_long", "forbidden_character") and os.listdir(tmp_path / "p") == []


def test_a_caption_word_with_a_hidden_character_is_refused(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    _, edl, _, _ = copy.deepcopy(docs)
    edl["words"][3]["text"] = "word" + chr(0x202E)
    err = refused(docs, catalogue, tmp_path / "p", edl=edl)
    assert (err.code, err.field) == ("text_not_clean", "edl.words")


# ---------------------------------------------------------------- limits

def test_a_vars_file_over_its_cap_and_a_page_over_its_cap_are_refused_after_nothing_was_written(tmp_path, docs, monkeypatch):
    catalogue = catalogue_of(tmp_path, mixed=True)
    monkeypatch.setattr(C, "MAX_VARS_BYTES", 1000)
    err = refused(docs, catalogue, tmp_path / "a")
    assert (err.code, err.field) == ("vars_too_large", "vars.json") and os.listdir(tmp_path / "a") == []
    monkeypatch.undo()
    monkeypatch.setattr(C, "MAX_PAGE_BYTES", 1000)
    err = refused(docs, catalogue, tmp_path / "b")
    assert (err.code, err.field) == ("page_too_large", "index.html") and os.listdir(tmp_path / "b") == []


def test_a_block_page_over_its_cap_and_too_many_block_pages_are_refused(tmp_path, docs, monkeypatch):
    catalogue = catalogue_of(tmp_path, mixed=False)
    monkeypatch.setattr(C, "MAX_BLOCK_PAGE_BYTES", 1000)
    assert refused(docs, catalogue, tmp_path / "a").code == "page_too_large"
    monkeypatch.undo()
    monkeypatch.setattr(C, "MAX_BLOCK_PAGES", 2)
    assert refused(docs, catalogue, tmp_path / "b").code == "page_too_large"


def test_a_band_with_no_height_is_refused(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    data, edl, _, _ = copy.deepcopy(docs)
    data["zones"]["caption_bottom"] = 100
    err = refused(docs, catalogue, tmp_path / "p", data=data)
    assert err.code == "band_too_small"


def test_a_gsap_fragment_that_breaks_the_contract_is_refused_before_anything_is_written(tmp_path, docs):
    folder = blocks_folder(tmp_path, mixed=True)
    path = os.path.join(folder, "hf", "demo-pop", "gsap.html")
    open(path, "w").write(K.POP_GSAP.replace("root.querySelector(\".label\")", "window.top.document.body"))
    _blocks.write_pins(folder)
    err = refused(docs, _blocks.load_catalogue(folder), tmp_path / "p")
    assert (err.code, err.field) == ("block_lint", "hf:demo-pop page_reach") and os.listdir(tmp_path / "p") == []


def test_a_block_file_that_changed_after_the_catalogue_was_loaded_is_refused(tmp_path, docs):
    folder = blocks_folder(tmp_path, mixed=True)
    catalogue = _blocks.load_catalogue(folder)
    open(os.path.join(folder, "hf", "demo-pop", "gsap.html"), "a").write("\n")
    err = refused(docs, catalogue, tmp_path / "p")
    assert err.code == "block_hash"


def test_a_folder_with_anything_in_it_or_none_is_refused_and_a_bad_background_too(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x").write_text("x")
    assert refused(docs, catalogue, tmp_path / "full").code == "page_dir_not_empty"
    data = copy.deepcopy(docs[0])
    data["theme"]["colors"]["bg"] = "red"
    assert refused(docs, catalogue, tmp_path / "bg", data=data).code == "bad_color"


# ---------------------------------------------------------------- the result

def test_the_result_names_what_was_drawn_with_what(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    result = write(docs, catalogue, tmp_path / "p")
    assert result["layers"] == ["cuts", "zoom", "captions", "beats"] and result["fps"] == docs[1]["fps"]
    assert result["blocks_sha256"] == catalogue["sha256"] and set(result["blocks"]) == set(result["runtimes"])
    assert result["blocks"]["hf:demo-pop"] == catalogue["files"]["hf/demo-pop/gsap.html"] and result["blocks"]["oh:list"] == catalogue["files"]["oh/list/renderat.html"]
    assert result["page_sha256"] == __import__("hashlib").sha256((tmp_path / "p" / "index.html").read_bytes()).hexdigest()
    assert result["vars_sha256"] == __import__("hashlib").sha256((tmp_path / "p" / "vars.json").read_bytes()).hexdigest()
    assert oct((tmp_path / "p" / "index.html").stat().st_mode & 0o777) == "0o600" and oct((tmp_path / "p" / "blocks").stat().st_mode & 0o777) == "0o700"


def test_with_no_captions_and_no_beats_the_layers_are_the_cuts_and_the_zoom(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    data, edl, beats, vocab = copy.deepcopy(docs)
    edl["captions"]["chunks"] = []
    beats["overlays"] = []
    result = write(docs, catalogue, tmp_path / "p", edl=edl, beats=beats)
    assert result["layers"] == ["cuts", "zoom"] and result["captions_drawn"] == 0 and result["beats_drawn"] == 0 and result["runtimes"] == {}
    assert "iframe" not in text_of(tmp_path / "p") and not (tmp_path / "p" / "blocks").exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed for the syntax check of the generated script (a syntax check runs no HyperFrames command)")
@pytest.mark.parametrize("mixed", [False, True])
def test_the_generated_scripts_parse(tmp_path, docs, mixed):
    catalogue = catalogue_of(tmp_path, mixed)
    write(docs, catalogue, tmp_path / "p")
    sources = [("root.js", re.findall(r"<script>(.*?)</script>", text_of(tmp_path / "p"), re.S)[0])]
    for name in sorted(os.listdir(tmp_path / "p" / "blocks")):
        sources += [("%s-%d.js" % (name, k), body) for k, body in enumerate(re.findall(r"<script>(.*?)</script>", text_of(tmp_path / "p", "blocks/" + name), re.S))]
    for name, body in sources:
        (tmp_path / name).write_text(body)
        done = subprocess.run(["node", "--check", str(tmp_path / name)], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, (name, done.stderr[-600:])


def test_json_files_are_byte_stable_sorted_compact_and_end_with_one_newline(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    write(docs, catalogue, tmp_path / "p")
    raw = (tmp_path / "p" / "vars.json").read_bytes()
    assert raw.endswith(b"}\n") and not raw.endswith(b"\n\n") and b"\r" not in raw and raw.isascii()
    assert json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")) + "\n" == raw.decode()


def test_the_post_of_the_live_test_passes_the_posts_checker_and_every_beat_is_one_the_engine_draws(tmp_path):
    doc = K.build_transcript(K.SHORT_SENTENCES)
    K.write_json(tmp_path / "transcript.json", doc)
    (tmp_path / "post.md").write_text(K.HF_POST, encoding="utf-8")
    rc, out, err = K.run_verb("align", "--post", tmp_path / "post.md", "--transcript", tmp_path / "transcript.json", "--checker", K.CHECKER,
                              "--vocabulary", K.VOCABULARY, "--out", tmp_path / "beats.json")
    assert rc == 0, err
    beats = json.loads((tmp_path / "beats.json").read_text())
    assert [e["preset"] for e in beats["overlays"]] == ["keyword", "number", "list", "quote"] and beats["layouts"] == []


def test_every_used_font_is_requested_before_the_first_tween_and_the_promise_is_kept(tmp_path, docs):
    """V3b-4: the gsap blocks' text was blank in the HyperFrames image because nothing asked for the fonts in the main page (font-display: block, no system
    font). One `document.fonts.load` per used face, ahead of the first `main.` call, so `document.fonts.ready` waits for them."""
    catalogue = catalogue_of(tmp_path, mixed=True)
    result = write(docs, catalogue, tmp_path / "p")
    page = text_of(tmp_path / "p")
    used = {(family, weight) for family, weight, file in (C.FONT_FILES[i] for i in C.FONT_FILES) if file in set(result["fonts_used"].values())}
    assert used
    loads = re.findall(r'document\.fonts\.load\("(\d+) 20px \\"([^"\\]+)\\""\)', page)
    assert sorted((family, int(weight)) for weight, family in loads) == sorted(used)         # exactly one load per used face
    assert "window.__hfFontsReady = (document.fonts && document.fonts.load) ? Promise.all([" in page
    first_load = page.index("document.fonts.load(")
    for needle in ("main.set(\"#hf-inst", "main.add(tl_", "main.fromTo(D_"):
        if needle in page:
            assert first_load < page.index(needle), needle


def test_the_theme_custom_properties_are_also_set_inline_on_the_root_element(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=True)
    write(docs, catalogue, tmp_path / "p")
    page = text_of(tmp_path / "p")
    for prop in ("--font-display", "--weight-display", "--c-accent", "--c-text"):
        assert 'rs.setProperty("%s", ' % prop in page, prop
    assert page.index("rs.setProperty(") < page.index("document.fonts.load(")


def test_every_font_url_of_the_composed_pages_names_a_file_the_image_stages_with_its_pinned_sha256(tmp_path, docs):
    catalogue = catalogue_of(tmp_path, mixed=False)
    write(docs, catalogue, tmp_path / "p")
    staged = {}
    for name, digest in R.FONT_FILES.items():
        raw = (K.RENDERER / "hyperframes-image" / "fonts" / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest, name
        staged[name] = digest
    seen = 0
    for rel, prefix in (("index.html", "fonts/"),) + tuple(("blocks/" + n, "../fonts/") for n in sorted(os.listdir(tmp_path / "p" / "blocks"))):
        for url in re.findall(r'url\("([^"]+)"\)', text_of(tmp_path / "p", rel)):
            assert url.startswith(prefix) and url[len(prefix):] in staged, (rel, url)
            seen += 1
    assert seen >= 4
