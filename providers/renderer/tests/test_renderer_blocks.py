"""The catalogue of animation blocks (V3b0): the seven oh: blocks are the old templates byte for byte, every file is pinned, the catalogue
is generated and every sample passes the renderer-side checker, an engine refuses a block it cannot draw, and a job stages the pinned
blocks and hashes the copy. Offline: no browser, no docker, no ffmpeg."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil

import pytest

import renderer_kit as K
import _blocks
import _host
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
BLOCKS = str(K.BLOCKS)

OLD_PINS = {"caption": "12073fd5e467fc9439ee7f45dbb6e5c6e1466d13a5f697d5986e40f47da592aa", "cutaway": "b04f56dc10e0fd1c5f3ee7a093cdc37d0f46baada842cb57694c7893602ecc67",
            "keyword": "71efd9c9ad18f5cc6209cf507eea03b4c52df51aed2710438f4245f4d44447c4", "list": "c859d746969f9732d371b62661ccc9aa6e2aef8689b7bd1955f368c7dff5fa0f",
            "number": "7c8f593524d000e21bf23d1a90236b7dd396f849cced19e45d19740147a32e0f", "pip": "efa437aae6e25cc2376bdf795b9abf68a777cb7b9bda2598d3ae11ad17234226",
            "quote": "b31930150eccca9f366babf85d0079eb02ee5a17299fba4808353d79a43ee1fa",
            "split": "79ca2047045fcac8d7873ccc4a51675f04ec2686a65c1f3e03791afaaaebfe20"}      # V9f: new, no old template; its own page


def sha(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def blocks_copy(tmp_path, name="b") -> str:
    folder = tmp_path / name
    shutil.copytree(K.oh_blocks(), folder)
    return str(folder)


def edit_json(folder, rel, change) -> None:
    path = os.path.join(folder, rel)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    change(doc)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
    _blocks.write_pins(folder)


def refused(fn, *args, **kw) -> Refusal:
    with pytest.raises(Refusal) as e:
        fn(*args, **kw)
    return e.value


def test_every_oh_block_is_its_old_template_byte_for_byte():
    new = {"aside"}                       # blocks made after the templates moved into blocks/ (the effect preset), with no old template either
    assert set(OLD_PINS) == (set(DATA["presets"]) - set(DATA["review_presets"]) - new) | {"caption"}      # the review-only blocks are new, with no old template
    for name, digest in OLD_PINS.items():
        assert sha(os.path.join(BLOCKS, "oh", name, "renderat.html")) == digest, name


def test_every_file_under_blocks_is_pinned_and_every_pin_names_a_file():
    found = set()
    for root, dirs, names in os.walk(BLOCKS):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in names:
            if not name.startswith("."):
                found.add(os.path.relpath(os.path.join(root, name), BLOCKS).replace(os.sep, "/"))
    assert found - set(_blocks.UNPINNED) == set(_blocks.read_pins()[1])


# M2 (PF-a4f): the ffmpeg engine's defaults that are ports; every other preset defaults to its oh: page
PORT_DEFAULTS = {"caption": "hf:caption-highlight", "keyword": "hf:spring-pop", "number": "hf:count-up", "quote": "hf:testimonial-card"}


def test_the_ffmpeg_engine_maps_caption_and_every_vocabulary_preset_to_a_block_it_can_draw():
    cat = _blocks.load_catalogue()
    presets = cat["engines"]["ffmpeg"]["presets"]
    assert set(presets) == set(VOCAB["presets"]) | {"caption"} and set(presets) == set(DATA["presets"]) | {"caption"}
    for preset, name in presets.items():
        assert (name == "oh:" + preset or name in PORT_DEFAULTS.values()) and "ffmpeg" in _blocks.engines_of(cat, cat["blocks"][name]), preset


def test_an_oh_block_declares_its_presets_kind_and_parameters_and_the_page_reads_no_other():
    cat = _blocks.load_catalogue()
    for preset, cfg in DATA["presets"].items():
        block = cat["blocks"]["oh:" + preset]
        assert block["params"] == VOCAB["presets"][preset]["params"] and block["kind"] == VOCAB["presets"][preset]["kind"], preset
        html = open(os.path.join(BLOCKS, K.template_of(preset)), encoding="utf-8").read()
        names = set(filter(None, re.search(r'<meta name="pv-params" content="([^"]*)">', html).group(1).split(",")))
        assert names == set(block["params"]) and re.search(r'<meta name="pv-preset" content="([^"]*)">', html).group(1) == preset
        assert cfg["min_duration"] <= block["natural_duration"] <= (cfg["max_duration"] or 60), preset
    caption = cat["blocks"]["oh:caption"]
    assert caption["params"] == {} and caption["kind"] == "caption" and caption["natural_duration"] is None
    html = open(os.path.join(BLOCKS, K.template_of("caption")), encoding="utf-8").read()
    assert re.search(r'<meta name="pv-params" content="([^"]*)">', html).group(1) == "" and 'name="pv-preset" content="caption"' in html


def test_every_catalogue_entry_has_a_sample_and_every_sample_passes_the_checker(tmp_path):
    cat = _blocks.load_catalogue()
    listed = json.load(open(os.path.join(BLOCKS, "catalogue.json"), encoding="utf-8"))["blocks"]
    assert {e["name"] for e in listed} == set(cat["blocks"])
    for entry in listed:
        assert entry["samples"], entry["name"]
        for sample in entry["samples"]:
            assert _blocks.check_params(cat["blocks"][entry["name"]], sample, VOCAB, "sample") == sample, entry["name"]
    folder = blocks_copy(tmp_path)
    edit_json(folder, "oh/keyword/block.json", lambda d: d.update(samples=[]))
    assert refused(_blocks.load_catalogue, folder).code == "block_schema"


def test_the_catalogue_file_is_what_the_generator_writes():
    assert (K.BLOCKS / "catalogue.json").read_bytes() == _blocks.catalogue_bytes(_blocks.load_catalogue())
    for entry in json.load(open(os.path.join(BLOCKS, "catalogue.json"), encoding="utf-8"))["blocks"]:
        assert not {"notice", "commit", "files"} & set(entry)


def test_the_schema_file_and_the_loader_name_the_same_keys():
    schema = json.load(open(os.path.join(BLOCKS, "block.schema.json"), encoding="utf-8"))["$defs"]
    assert set(schema["block"]["properties"]) == _blocks.BLOCK_KEYS | {"schema_version"}
    assert set(schema["block"]["required"]) == _blocks.BLOCK_REQUIRED
    assert set(schema["param"]["properties"]) == _blocks.PARAM_KEYS


def test_a_changed_file_a_link_an_unknown_file_or_another_pins_hash_is_refused(tmp_path):
    folder = blocks_copy(tmp_path)
    with open(os.path.join(folder, "oh", "list", "renderat.html"), "ab") as fh:
        fh.write(b"\n")
    e = refused(_blocks.load_catalogue, folder)
    assert e.code == "block_hash" and e.field == "oh:list:renderat.html"
    folder = blocks_copy(tmp_path, "c")
    page = os.path.join(folder, "oh", "pip", "renderat.html")
    os.unlink(page)
    os.symlink("/etc/hosts", page)
    assert refused(_blocks.load_catalogue, folder).code == "blocks_unreadable"
    folder = blocks_copy(tmp_path, "d")
    with open(os.path.join(folder, "oh", "keyword", "notes.txt"), "w") as fh:
        fh.write("not a block file")
    e = refused(_blocks.write_pins, folder)
    assert e.code == "block_file_unknown" and e.field == "oh:keyword:notes.txt"
    assert refused(_blocks.load_catalogue, BLOCKS, expect_sha256="0" * 64).code == "blocks_changed"
    assert _blocks.load_catalogue(BLOCKS, expect_sha256=K.BLOCKS_SHA256)["sha256"] == K.BLOCKS_SHA256


def _long(n):
    return "x" * n


MALFORMED = [
    ("an unknown key", lambda d: d.update(extra=1)),
    ("another name", lambda d: d.update(name="oh:other")),
    ("another namespace", lambda d: d.update(name="xx:keyword")),
    ("a kind that does not give the band", lambda d: d.update(kind="layout")),
    ("a licence outside the list", lambda d: d.update(license=["GPL-3.0"])),
    ("the registry as the source of an oh: block", lambda d: d.update(source="hyperframes-registry")),
    ("a use_when of 121 characters", lambda d: d.update(use_when=_long(121))),
    ("a use_when with a newline", lambda d: d.update(use_when="one line\nand another")),
    ("a natural duration of 0", lambda d: d.update(natural_duration=0)),
    ("a sample with an undeclared key", lambda d: d.update(samples=[{"text": "x", "bogus": 1}])),
    ("a sample without the required text", lambda d: d.update(samples=[{"icon": "coin"}])),
    ("an implementation that is not pinned", lambda d: d.update(implementations={"renderat": "missing.html"})),
    ("a tier on an oh: block", lambda d: d.update(tier="B")),
    ("a number whose min is above its max", lambda d: d["params"].update(scale={"type": "number", "min": 2, "max": 1})),
    ("a text with no max", lambda d: d["params"].update(extra={"type": "text"})),
]


@pytest.mark.parametrize("change", [c for _, c in MALFORMED], ids=[n for n, _ in MALFORMED])
def test_a_malformed_block_is_refused(tmp_path, change):
    folder = blocks_copy(tmp_path)
    edit_json(folder, "oh/keyword/block.json", change)
    assert refused(_blocks.load_catalogue, folder).code == "block_schema"


def test_an_hf_block_fits_the_schema_unchanged_and_is_refused_on_ffmpeg_naming_the_oh_block(tmp_path):
    folder = blocks_copy(tmp_path)
    K.write_hf_fixture(folder)
    cat = _blocks.load_catalogue(folder)
    listed = {e["name"]: e for e in json.loads(_blocks.catalogue_bytes(cat))["blocks"]}
    assert listed["hf:demo-pop"]["engines"] == ["twin"] and listed["hf:demo-ring"]["engines"] == ["twin"]
    assert listed["oh:keyword"]["engines"] == ["ffmpeg"] and listed["hf:demo-pop"]["tier"] == "A" and listed["hf:demo-ring"]["tier"] == "B"
    assert not any({"notice", "commit", "files"} & set(e) for e in listed.values())
    e = refused(_blocks.resolve, cat, "ffmpeg", "keyword", "hf:demo-pop", "beats.b1")
    assert (e.code, e.field) == ("block_not_on_engine", "oh:keyword")
    assert _blocks.resolve(cat, "twin", "keyword", None, "beats.b1")["name"] == "hf:demo-pop"
    assert _blocks.implementation(cat, cat["blocks"]["hf:demo-pop"], "twin") == "hf/demo-pop/demo-pop.html"
    bad_image = copy.deepcopy(K.HF_ENTRY)
    bad_image["params"]["picture"] = {"type": "image"}
    for entry in (bad_image,):
        assert refused(_blocks.check_block, entry, "hf:allowlist[0]", "hf", registry_commit="a" * 40).code == "block_schema"


CHECKER_CASES = [
    ("oh:keyword", {"text": "Name every dollar", "bogus": 1}, "undeclared_param"), ("oh:keyword", {"icon": "coin"}, "missing_param"),
    ("oh:keyword", ["text"], "params_not_object"), ("oh:keyword", {"text": "x" * 241}, "text_too_long"),
    ("oh:keyword", {"text": "Name", "icon": "rocket"}, "bad_icon"), ("oh:keyword", {"text": "Name", "color": "#12345"}, "bad_color"),
    ("hf:demo-pop", {"text": "Name", "bogus": 1}, "undeclared_param"), ("hf:demo-pop", {"scale": 1}, "missing_param"),
    ("hf:demo-pop", "text", "params_not_object"), ("hf:demo-pop", {"text": "x" * 241}, "text_too_long"),
    ("hf:demo-pop", {"text": "Name", "scale": True}, "bad_number"), ("hf:demo-pop", {"text": "Name", "scale": 3}, "bad_number"),
    ("hf:demo-pop", {"text": "Name", "scale": float("nan")}, "bad_number"),
]


@pytest.mark.parametrize("name,params,code", CHECKER_CASES, ids=["%s-%s" % (n, c) for n, _, c in CHECKER_CASES])
def test_the_renderer_side_checker_holds_every_bound(tmp_path, name, params, code):
    folder = blocks_copy(tmp_path)
    K.write_hf_fixture(folder)
    block = _blocks.load_catalogue(folder)["blocks"][name]
    assert refused(_blocks.check_params, block, params, VOCAB).code == code


@pytest.mark.parametrize("name", ["oh:keyword", "hf:demo-pop"])
def test_a_text_over_the_blocks_max_passes_with_advice_up_to_240_characters(tmp_path, name):
    folder = blocks_copy(tmp_path)
    K.write_hf_fixture(folder)
    block = _blocks.load_catalogue(folder)["blocks"][name]
    limit = block["params"]["text"]["max"]
    advice = []
    out = _blocks.check_params(block, {"text": "x" * (limit + 6)}, VOCAB, advice=advice, aid="b1")
    assert out == {"text": "x" * (limit + 6)}
    assert advice == [{"code": "text_over_default", "value": limit + 6, "default": limit, "count": 1, "ids": ["b1"]}]
    assert _blocks.check_params(block, {"text": "x" * limit}, VOCAB, advice=[]) == {"text": "x" * limit}
    assert _blocks.check_params(block, {"text": "x" * 240}, VOCAB)["text"] == "x" * 240      # no list to report in: still accepted up to the ceiling


def test_the_checker_passes_a_value_inside_its_bounds_and_does_not_fill_defaults(tmp_path):
    folder = blocks_copy(tmp_path)
    K.write_hf_fixture(folder)
    cat = _blocks.load_catalogue(folder)
    assert _blocks.check_params(cat["blocks"]["hf:demo-pop"], {"text": "Name", "scale": 1}, VOCAB) == {"text": "Name", "scale": 1}
    assert _blocks.check_params(cat["blocks"]["oh:cutaway"], {"asset": "beat1"}, VOCAB) == {"asset": "beat1"}


def test_resolve_refuses_an_unknown_block_another_preset_and_an_unknown_engine():
    cat = _blocks.load_catalogue()
    assert refused(_blocks.resolve, cat, "ffmpeg", "keyword", "oh:nothere", "beats.b1").code == "block_unknown"
    assert refused(_blocks.resolve, cat, "ffmpeg", "keyword", "keyword", "beats.b1").code == "block_unknown"
    assert refused(_blocks.resolve, cat, "ffmpeg", "keyword", "oh:list", "beats.b1").code == "block_preset_mismatch"
    assert refused(_blocks.resolve, cat, "nothere", "keyword", None, "beats.b1").code == "engine_unknown"
    assert refused(_blocks.resolve, cat, "ffmpeg", "unknown_preset", None, "beats.b1").code == "preset_not_on_engine"
    assert _blocks.resolve(cat, "ffmpeg", "keyword", None, "beats.b1")["name"] == "hf:spring-pop"      # M2 (PF-a4f): the default of keyword is the port


class StubJob:
    stage = _host.Job.stage

    def __init__(self, in_dir):
        self.in_dir = str(in_dir)
        self.staged = {}


def test_stage_blocks_copies_only_the_pinned_files_and_hashes_the_copy(tmp_path):
    folder = blocks_copy(tmp_path)
    with open(os.path.join(folder, "oh", "keyword", "notes.txt"), "w") as fh:      # put there after pinning: never copied
        fh.write("not pinned")
    job = StubJob(tmp_path / "in")
    os.mkdir(job.in_dir)
    flags = _host.stage_blocks(job, folder)
    assert flags == ["--blocks", "/job/blocks", "--blocks-sha256", sha(os.path.join(folder, "pins.json"))]
    staged = os.path.join(job.in_dir, "blocks")
    assert not os.path.exists(os.path.join(staged, "oh", "keyword", "notes.txt")) and not os.path.exists(os.path.join(staged, "catalogue.json"))
    assert os.path.isfile(os.path.join(staged, "oh", "keyword", "renderat.html")) and sha(os.path.join(staged, "pins.json")) == flags[-1]
    changed = blocks_copy(tmp_path, "c")
    with open(os.path.join(changed, "oh", "list", "renderat.html"), "ab") as fh:
        fh.write(b"\n")
    other = StubJob(tmp_path / "in2")
    os.mkdir(other.in_dir)
    assert refused(_host.stage_blocks, other, changed).code == "block_hash"


# ---------------------------------------------------------------- the cutaway on both engines, the screenshot block and the engines' asset kinds (V9b-2)

def test_the_catalogue_names_what_each_engine_draws_as_a_picture():
    cat = _blocks.load_catalogue()
    assert cat["engines"]["ffmpeg"]["asset_kinds"] == ["image", "clip"] and cat["engines"]["hyperframes"]["asset_kinds"] == ["image", "clip"]
    doc = json.load(open(os.path.join(BLOCKS, "catalogue.json"), encoding="utf-8"))
    assert doc["asset_kinds_by_engine"] == {"ffmpeg": ["image", "clip"], "hyperframes": ["image", "clip"]}
    assert doc["engines"]["hyperframes"]["presets"]["cutaway"] == "oh:cutaway" and "pip" not in doc["engines"]["hyperframes"]["presets"]
    assert doc["engines"]["ffmpeg"]["presets"]["pip"] == "oh:pip"


def test_an_engine_file_without_asset_kinds_draws_images_only_and_a_bad_list_is_refused(tmp_path):
    folder = blocks_copy(tmp_path)
    edit_json(folder, "engines/ffmpeg.json", lambda d: d.pop("asset_kinds"))
    cat = _blocks.load_catalogue(folder)
    assert _blocks.catalogue_doc(cat)["asset_kinds_by_engine"]["ffmpeg"] == ["image"]
    edit_json(folder, "engines/ffmpeg.json", lambda d: d.update(asset_kinds=["image", "clip"]))
    assert _blocks.catalogue_doc(_blocks.load_catalogue(folder))["asset_kinds_by_engine"]["ffmpeg"] == ["image", "clip"]
    for bad in ([], ["video"], ["image", "image"], "image", [1]):
        edit_json(folder, "engines/ffmpeg.json", lambda d, bad=bad: d.update(asset_kinds=bad))
        assert refused(_blocks.load_catalogue, folder).code == "block_schema", bad


def test_the_screenshot_block_has_the_cutaways_parameters_and_draws_the_cutaway_preset_on_both_engines():
    cat = _blocks.load_catalogue()
    shot, cut = cat["blocks"]["oh:screenshot"], cat["blocks"]["oh:cutaway"]
    assert shot["params"] == cut["params"] == VOCAB["presets"]["cutaway"]["params"]
    assert (shot["preset"], shot["kind"], shot["band"], shot["may_cross_face"], shot["license"], shot["source"]) == ("cutaway", "layout", "frame", True, ["MIT"], "openhora")
    assert len(shot["samples"]) == 1 and shot["natural_duration"] == 1.5 and _blocks.engines_of(cat, shot) == ["ffmpeg", "hyperframes"]
    for engine in ("ffmpeg", "hyperframes"):
        assert _blocks.resolve(cat, engine, "cutaway", "oh:screenshot", "beats.b1")["name"] == "oh:screenshot"
        assert _blocks.resolve(cat, engine, "cutaway", None, "beats.b1")["name"] == "oh:cutaway"                  # the default stays the cutaway
    assert _blocks.check_params(shot, {"asset": "slot-1", "fit": "contain", "label": "The page on screen"}, VOCAB) == {"asset": "slot-1", "fit": "contain", "label": "The page on screen"}
    assert refused(_blocks.check_params, shot, {"asset": "slot-1", "position": "top"}, VOCAB).code == "undeclared_param"
    assert refused(_blocks.check_params, shot, {"fit": "cover"}, VOCAB).code == "missing_param"


def test_the_screenshot_page_declares_the_cutaways_parameters_reads_only_them_and_names_no_font_or_colour_outside_the_theme():
    html = open(os.path.join(BLOCKS, "oh", "screenshot", "renderat.html"), encoding="utf-8").read()
    assert re.search(r'<meta name="pv-preset" content="([^"]*)">', html).group(1) == "cutaway"
    assert set(re.search(r'<meta name="pv-params" content="([^"]*)">', html).group(1).split(",")) == set(DATA["presets"]["cutaway"] and VOCAB["presets"]["cutaway"]["params"])
    looks = set(filter(None, re.search(r'<meta name="pv-looks" content="([^"]*)">', html).group(1).split(",")))
    assert looks <= set(DATA["presets"]["cutaway"]["looks"]) and set(re.findall(r"\bL\.([a-z0-9_]+)", html)) <= looks
    assert set(re.findall(r"\bP\.([a-z0-9_]+)", html)) <= set(VOCAB["presets"]["cutaway"]["params"])
    from _lint import lint
    assert lint(html) == [] and "innerHTML" not in html
    assert not re.search(r"font-family\s*:\s*(?!var\()", html)               # the families come from the theme's tokens only
    assert "background:var(--c-bg)" in html.replace(" ", "")


def test_the_cutaway_page_the_screenshot_page_follows_keeps_its_image_path_byte_for_byte():
    """V9b-5a changed the cutaway page (a clip branch: the page draws only the label chip for a clip), so its whole-file hash moved (`OLD_PINS["cutaway"]` is the new one).
    What this test was for stays: the drawing code an image goes through, which the screenshot page follows, is the V9b-2 page's, line for line (indentation aside:
    it now sits in the `else` of the clip branch). The golden-frames test of `test_clip_cutaway.py` draws both pages and proves the frames are the same bytes."""
    def code(path):
        text = open(path, encoding="utf-8").read()
        start = text.index("const img = window.__imgs[P.asset];")
        end = text.index("layer.style.opacity = opacity.toFixed(3);") + len("layer.style.opacity = opacity.toFixed(3);")
        return [line.strip() for line in text[start:end].splitlines()]
    now = os.path.join(BLOCKS, "oh", "cutaway", "renderat.html")
    assert sha(now) == OLD_PINS["cutaway"]
    assert code(now) == code(os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden", "cutaway-renderat-v9b2.html"))


def test_a_beat_naming_the_screenshot_block_is_drawn_by_its_page_on_the_ffmpeg_engine_and_the_cutaway_by_its_own_by_default():
    cat = _blocks.load_catalogue(K.oh_blocks())      # the caption of the committed engine is a port since M2: a page of the second contract has no `renderat` template
    entry = {"id": "b1", "preset": "cutaway", "block": "oh:screenshot", "params": {"asset": "slot-1", "fit": "contain"}}
    templates, names = _blocks.templates_for(cat, "ffmpeg", {"beats": [entry]}, VOCAB, with_caption=False)
    assert templates == {"caption": "oh/caption/renderat.html", "oh:screenshot": "oh/screenshot/renderat.html"} and names == ["oh/screenshot/renderat.html"]
    assert entry["block"] == "oh:screenshot"
    plain = {"id": "b2", "preset": "cutaway", "params": {"asset": "slot-1"}}
    templates, names = _blocks.templates_for(cat, "ffmpeg", {"beats": [plain]}, VOCAB, with_caption=False)
    assert templates["oh:cutaway"] == "oh/cutaway/renderat.html" and plain["block"] == "oh:cutaway"


# ---------------------------------------------------------------- the second page contract's allowlist entries (PF-a2)

def hf_folder(tmp_path, name="hf", **over):
    import hf_second_kit as H
    files = {H.FILE: "a" * 64}
    return H.blocks_folder(tmp_path, H.entry(files, "b" * 64, "c" * 64, **over), name)


def test_the_committed_allowlist_is_still_empty_and_the_ffmpeg_engine_runs_the_renderat_and_the_hf_runtimes():
    allow = json.load(open(os.path.join(BLOCKS, "hf", "allowlist.json"), encoding="utf-8"))
    assert allow["blocks"] == [] and allow["registry_commit"] is None
    assert json.load(open(os.path.join(BLOCKS, "engines", "ffmpeg.json"), encoding="utf-8"))["runtimes"] == ["renderat", "hf", "gsap"]
    assert _blocks.RUNTIMES == ("renderat", "gsap", "hf")
    cat = _blocks.load_catalogue(BLOCKS)
    assert not [b for b in cat["blocks"].values() if "hf" in b["implementations"]]


def test_a_valid_entry_of_the_second_contract_loads_runs_on_the_ffmpeg_engine_only_and_is_drawn_by_no_pinned_page(tmp_path):
    import hf_second_kit as H
    cat = _blocks.load_catalogue(hf_folder(tmp_path))
    block = cat["blocks"][H.NAME]
    assert _blocks.engines_of(cat, block) == ["ffmpeg"] and _blocks.runtime_of(cat, block, "ffmpeg") == "hf"
    assert block["bind"] == {"text": "var:text", "color": "css:--brand"} and block["determinism"]["runs"] == 4
    entry = [b for b in _blocks.catalogue_doc(cat)["blocks"] if b["name"] == H.NAME][0]
    assert entry["runtimes"] == ["hf"] and not {"bind", "files", "edits", "determinism", "served_sha256", "component"} & set(entry)
    timeline = {"beats": [{"id": "b1", "preset": "keyword", "params": {"text": "Name every dollar"}}]}
    templates, names = _blocks.templates_for(cat, "ffmpeg", timeline, VOCAB, with_caption=True)
    assert templates[H.NAME] is None and names == [templates["caption"]]
    assert refused(_blocks.templates_for, cat, "ffmpeg", {"beats": [{"id": "b1", "preset": "keyword", "params": {"icon": "coin", "text": "x"}}]}, VOCAB, with_caption=False).code == "undeclared_param"


@pytest.mark.parametrize("key", ["component", "edits", "font_map", "served_sha256", "bind", "fixed", "theme_vars", "determinism"])
def test_an_entry_of_the_second_contract_without_one_of_its_keys_is_refused_and_so_is_one_that_has_them_without_the_runtime(tmp_path, key):
    import hf_second_kit as H
    e = H.entry({H.FILE: "a" * 64}, "b" * 64, "c" * 64)
    del e[key]
    assert refused(_blocks.check_block, e, "hf:allowlist[0]", "hf", registry_commit=H.COMMIT).code == "block_schema"
    e = H.entry({H.FILE: "a" * 64}, "b" * 64, "c" * 64)
    e["implementations"] = {"gsap": H.FILE}
    assert refused(_blocks.check_block, e, "hf:allowlist[0]", "hf", registry_commit=H.COMMIT).code == "block_schema"


@pytest.mark.parametrize("change", [
    lambda e: e["determinism"].update(runs=3),
    lambda e: e["determinism"].update(blocked=1),
    lambda e: e["determinism"].update(date="24-11-2026"),
    lambda e: e["determinism"].update(extra=1),
    lambda e: e["determinism"].pop("seconds"),
    lambda e: e["params"].update(picture={"type": "image"}),
    lambda e: e["params"].update(picture={"type": ["image", "clip"]}),
    lambda e: e["params"].pop("color"),                                       # `bind` names a parameter the entry does not declare
    lambda e: e["bind"].update(color="var:text"),                             # two parameters on one target
    lambda e: e["bind"].update(color="css:brand"),
    lambda e: e["theme_vars"].update({"--bg": "bg"}),
    lambda e: e["theme_vars"].update({"--x": "Text"}),
    lambda e: e["edits"].append("E3"),
    lambda e: e["edits"].append("E1"),
    lambda e: e["edits"].append("E2:Arial"),                                  # a family with no entry in `font_map`
    lambda e: e["font_map"].update(Inter="oh-serif"),
    lambda e: e["fixed"].update(text="x"),                                    # a variable a parameter already reaches
    lambda e: e.update(natural_duration=None),
    lambda e: e.update(kind="caption", preset="caption", band="caption"),
    lambda e: e.update(implementations={"hf": "other.html"}),
    lambda e: e.update(served_sha256="x"),
])
def test_an_entry_of_the_second_contract_that_breaks_a_rule_is_block_schema(change):
    import hf_second_kit as H
    e = H.entry({H.FILE: "a" * 64}, "b" * 64, "c" * 64)
    change(e)
    assert refused(_blocks.check_block, e, "hf:allowlist[0]", "hf", registry_commit=H.COMMIT).code == "block_schema"
    assert _blocks.check_block(H.entry({H.FILE: "a" * 64}, "b" * 64, "c" * 64), "hf:allowlist[0]", "hf", registry_commit=H.COMMIT)["name"] == H.NAME


def test_an_engine_that_runs_gsap_cannot_draw_an_entry_that_runs_on_the_second_contract_only(tmp_path):
    import hf_second_kit as H
    folder = hf_folder(tmp_path)
    with open(os.path.join(folder, "engines", "twin.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema_version": 1, "engine": "twin", "note": "a fictional engine for the tests", "runtimes": ["gsap", "renderat"], "asset_kinds": ["image", "clip"],
                   "presets": {"keyword": H.NAME}}, fh, indent=1)
    _blocks.write_pins(folder)
    assert refused(_blocks.load_catalogue, folder).code == "block_schema"


def test_a_staged_entry_validates_and_the_catalogue_never_loads_it(tmp_path):
    import hf_second_kit as H
    import _admit
    entry = H.entry({H.FILE: "a" * 64}, "b" * 64, "c" * 64)
    staged = tmp_path / "hf-runtime" / "staged"
    staged.mkdir(parents=True)
    path = staged / "oh-test-pop.json"
    path.write_text(json.dumps(entry))
    assert _admit.read_staged(str(path), H.COMMIT)["name"] == H.NAME
    assert refused(_admit.read_staged, str(path), "d" * 40).code == "block_schema"                  # another registry commit than the one the file's own `commit` names
    path.write_text(json.dumps(dict(entry, bind={})))
    assert refused(_admit.read_staged, str(path), H.COMMIT).code == "block_schema"
    cat = _blocks.load_catalogue(str(K.BLOCKS))
    assert H.NAME not in cat["blocks"]                                                              # the committed folders hold no staged file, and the catalogue reads blocks/ only
    folder = tmp_path / "blocks"
    shutil.copytree(K.BLOCKS, folder)
    (folder / "hf" / "oh-test-pop.json").write_text(json.dumps(entry))
    assert refused(_blocks.write_pins, str(folder)).code == "block_file_unknown"                    # a staged file put among the pinned ones is refused, not pinned
