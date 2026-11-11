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

OLD_PINS = {"caption": "12073fd5e467fc9439ee7f45dbb6e5c6e1466d13a5f697d5986e40f47da592aa", "cutaway": "e93e356119decf19925c0dd6c006db7c6db1094007352a069ab6c27cf840b97e",
            "keyword": "71efd9c9ad18f5cc6209cf507eea03b4c52df51aed2710438f4245f4d44447c4", "list": "c859d746969f9732d371b62661ccc9aa6e2aef8689b7bd1955f368c7dff5fa0f",
            "number": "7c8f593524d000e21bf23d1a90236b7dd396f849cced19e45d19740147a32e0f", "pip": "4163ba3f8d7f9ddb1fd89d5904bb406f33367c176b964b7d64c838e337244f34",
            "quote": "b31930150eccca9f366babf85d0079eb02ee5a17299fba4808353d79a43ee1fa"}


def sha(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def blocks_copy(tmp_path, name="b") -> str:
    folder = tmp_path / name
    shutil.copytree(BLOCKS, folder)
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
    assert set(OLD_PINS) == (set(DATA["presets"]) - set(DATA["review_presets"])) | {"caption"}      # the review-only blocks are new, with no old template
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


def test_the_ffmpeg_engine_maps_caption_and_every_vocabulary_preset_to_an_oh_block_it_can_draw():
    cat = _blocks.load_catalogue()
    presets = cat["engines"]["ffmpeg"]["presets"]
    assert set(presets) == set(VOCAB["presets"]) | {"caption"} and set(presets) == set(DATA["presets"]) | {"caption"}
    for preset, name in presets.items():
        assert name.startswith("oh:") and "ffmpeg" in _blocks.engines_of(cat, cat["blocks"][name]), preset


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
    ("may cross the face in the card band", lambda d: d.update(may_cross_face=True)),
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
    assert listed["hf:demo-pop"]["engines"] == ["hyperframes"] and listed["hf:demo-ring"]["engines"] == ["hyperframes"]
    assert listed["oh:keyword"]["engines"] == ["ffmpeg"] and listed["hf:demo-pop"]["tier"] == "A" and listed["hf:demo-ring"]["tier"] == "B"
    assert not any({"notice", "commit", "files"} & set(e) for e in listed.values())
    e = refused(_blocks.resolve, cat, "ffmpeg", "keyword", "hf:demo-pop", "beats.b1")
    assert (e.code, e.field) == ("block_not_on_engine", "oh:keyword")
    assert _blocks.resolve(cat, "hyperframes", "keyword", None, "beats.b1")["name"] == "hf:demo-pop"
    assert _blocks.implementation(cat, cat["blocks"]["hf:demo-pop"], "hyperframes") == "hf/demo-pop/demo-pop.html"
    bad_image = copy.deepcopy(K.HF_ENTRY)
    bad_image["params"]["picture"] = {"type": "image"}
    bad_cross = dict(copy.deepcopy(K.HF_ENTRY), kind="layout", band="frame", may_cross_face=True)
    for entry in (bad_image, bad_cross):
        assert refused(_blocks.check_block, entry, "hf:allowlist[0]", "hf", registry_commit="a" * 40).code == "block_schema"


CHECKER_CASES = [
    ("oh:keyword", {"text": "Name every dollar", "bogus": 1}, "undeclared_param"), ("oh:keyword", {"icon": "coin"}, "missing_param"),
    ("oh:keyword", ["text"], "params_not_object"), ("oh:keyword", {"text": "x" * 25}, "text_too_long"),
    ("oh:keyword", {"text": "Name", "icon": "rocket"}, "bad_icon"), ("oh:keyword", {"text": "Name", "color": "#12345"}, "bad_color"),
    ("hf:demo-pop", {"text": "Name", "bogus": 1}, "undeclared_param"), ("hf:demo-pop", {"scale": 1}, "missing_param"),
    ("hf:demo-pop", "text", "params_not_object"), ("hf:demo-pop", {"text": "x" * 25}, "text_too_long"),
    ("hf:demo-pop", {"text": "Name", "scale": True}, "bad_number"), ("hf:demo-pop", {"text": "Name", "scale": 3}, "bad_number"),
    ("hf:demo-pop", {"text": "Name", "scale": float("nan")}, "bad_number"),
]


@pytest.mark.parametrize("name,params,code", CHECKER_CASES, ids=["%s-%s" % (n, c) for n, _, c in CHECKER_CASES])
def test_the_renderer_side_checker_holds_every_bound(tmp_path, name, params, code):
    folder = blocks_copy(tmp_path)
    K.write_hf_fixture(folder)
    block = _blocks.load_catalogue(folder)["blocks"][name]
    assert refused(_blocks.check_params, block, params, VOCAB).code == code


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
    assert _blocks.resolve(cat, "ffmpeg", "keyword", None, "beats.b1")["name"] == "oh:keyword"


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
