"""The catalogue rules of a port under the second contract (PF-a4) and what `_hf_host.prepare` builds from them, offline: the record is accepted only on a tier-B hf
`gsap` block.json, a `gsap` block counts on the ffmpeg engine only with it, the caption is resolved like the beats, and the page driver can close a page.
Written with the kit's FICTIONAL ports. No browser."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import renderer_kit as K
import hf_port_kit as P
import _blocks
import _cdp
import _hf_host
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
FACE = {"x": 240, "y": 300, "w": 600, "h": 480}
ROLES = DATA["theme"]["font_roles"]
EDL = {"fps": 30, "captions": {"position": "bottom"}, "theme": {"colors": dict(DATA["theme"]["colors"]), "fonts": {r: {"id": "default", "weight": 500} for r in ROLES}},
       "words": [{"index": 0, "text": "Name", "start": 0.0, "end": 0.4}, {"index": 1, "text": "dollar", "start": 0.4, "end": 0.8}]}


def refused(fn, *a, **k) -> Refusal:
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


@pytest.fixture()
def world(tmp_path, monkeypatch):
    rt = P.port_runtime(monkeypatch, tmp_path)
    runtime_sha = P.runtime_hash(rt)
    return {"rt": rt, "tmp": tmp_path, "sha": runtime_sha}


def edit_block(folder, short, change):
    path = Path(folder) / "hf" / short / "block.json"
    doc = json.loads(path.read_text())
    change(doc)
    path.write_text(json.dumps(doc, indent=1) + "\n")
    _blocks.write_pins(folder)


def test_the_record_is_accepted_on_a_tier_b_hf_gsap_block_and_the_catalogue_lists_ffmpeg_only_with_it(world):
    without = P.blocks_folder(world["tmp"], ("card", "caption"), None, engine_presets=False, name="a")
    with_record = P.blocks_folder(world["tmp"], ("card", "caption"), world["sha"], name="b")
    cat_a, cat_b = _blocks.load_catalogue(without), _blocks.load_catalogue(with_record)
    assert "determinism" not in cat_a["blocks"][P.CARD] and "determinism" in cat_b["blocks"][P.CARD]
    assert _blocks.engines_of(cat_a, cat_a["blocks"][P.CARD]) == ["hyperframes"] and "ffmpeg" in _blocks.engines_of(cat_b, cat_b["blocks"][P.CARD])
    assert _blocks.runtime_of(cat_b, cat_b["blocks"][P.CARD], "ffmpeg") == "gsap" and _blocks.runtime_of(cat_b, cat_b["blocks"][P.CARD], "hyperframes") == "gsap"
    assert refused(_blocks.runtime_of, cat_a, cat_a["blocks"][P.CARD], "ffmpeg").code == "block_not_on_engine"
    assert _blocks.resolve(cat_a, "hyperframes", "keyword", P.CARD, "beats.b1")["name"] == P.CARD          # the old engine still draws a port with no record


def test_an_engine_default_on_a_second_contract_runtime_without_a_record_is_block_schema(world):
    folder = P.blocks_folder(world["tmp"], ("card",), None, name="c")                # the kit names the port as the ffmpeg default
    assert refused(_blocks.load_catalogue, folder).code == "block_schema"


@pytest.mark.parametrize("change", [
    lambda d: d["determinism"].update(runs=3),
    lambda d: d["determinism"].update(blocked=1),
    lambda d: d["determinism"].update(extra=1),
    lambda d: d["determinism"].pop("image"),
    lambda d: d["determinism"].update(served_sha256="nope"),
    lambda d: d.update(tier="A"),
    lambda d: d.update(implementations={"gsap": "gsap.html", "renderat": "renderat.html"}),
])
def test_a_malformed_record_or_a_record_on_the_wrong_kind_of_block_is_block_schema(world, change):
    folder = P.blocks_folder(world["tmp"], ("card",), world["sha"], name="d")
    edit_block(folder, "oh-test-badge", change)
    assert refused(_blocks.load_catalogue, folder).code == "block_schema"


def test_a_record_on_an_oh_block_or_on_an_allowlist_entry_is_block_schema(world):
    folder = P.blocks_folder(world["tmp"], ("card",), world["sha"], name="e")
    path = Path(folder) / "oh" / "keyword" / "block.json"
    doc = json.loads(path.read_text())
    doc["determinism"] = json.loads((Path(folder) / "hf" / "oh-test-badge" / "block.json").read_text())["determinism"]
    path.write_text(json.dumps(doc, indent=1) + "\n")
    _blocks.write_pins(folder)
    assert refused(_blocks.load_catalogue, folder).code == "block_schema"


def test_a_tier_a_gsap_entry_is_never_usable_on_ffmpeg_even_with_a_record(world):
    eng = {"runtimes": ["renderat", "hf", "gsap"]}
    tier_a = {"implementations": {"gsap": "x.html"}, "files": {"x.html": "0" * 64}, "tier": "A", "determinism": {}}
    port = {"implementations": {"gsap": "gsap.html"}, "tier": "B", "determinism": {}}
    assert _blocks.usable(eng, tier_a, "gsap") is False and _blocks.usable(eng, port, "gsap") is True
    assert _blocks.usable({"runtimes": ["gsap", "renderat"]}, tier_a, "gsap") is True               # the old engine keeps its rule
    assert _blocks.usable(eng, {"implementations": {"gsap": "g.html"}, "tier": "B"}, "gsap") is False                 # no record
    assert _blocks.usable(eng, port, "renderat") is False


def test_the_caption_port_is_resolved_like_the_beats_and_is_never_loaded_as_a_page_of_the_first_contract(world):
    folder = P.blocks_folder(world["tmp"], ("card", "caption"), world["sha"], name="f")
    cat = _blocks.load_catalogue(folder)
    vocab = load_vocabulary(K.VOCABULARY)
    timeline = {"beats": [{"id": "b1", "preset": "keyword", "params": {"text": "Go"}}]}
    templates, names = _blocks.templates_for(cat, "ffmpeg", timeline, vocab, with_caption=True)
    assert templates == {"caption": None, P.CARD: None} and names == [] and timeline["beats"][0]["block"] == P.CARD
    # the default caption on ffmpeg is still the oh: page: it is loaded as before
    plain = _blocks.load_catalogue(str(K.BLOCKS))
    t2, n2 = _blocks.templates_for(plain, "ffmpeg", {"beats": []}, vocab, with_caption=True)
    assert t2["caption"] == "oh/caption/renderat.html" and n2 == ["oh/caption/renderat.html"]
    assert refused(_blocks.templates_for, cat, "ffmpeg", {"beats": [{"id": "b1", "preset": "keyword", "params": {"text": "a\u200bb"}}]}, vocab, False).code == "forbidden_character"


def prepare(world, kinds=("card", "caption"), record=True, runtime_hash=None, beats=True, captions=True):
    rt = world["rt"]
    folder = P.blocks_folder(world["tmp"], kinds, (runtime_hash or world["sha"]) if record else "b" * 64, name="p%d" % len(list(world["tmp"].iterdir())))
    cat = _blocks.load_catalogue(folder)
    timeline = {"beats": [], "captions": []}
    if beats and P.CARD in cat["blocks"]:
        timeline["beats"].append({"id": "b1", "preset": "keyword", "block": P.CARD, "params": {"text": "Name every dollar"}, "start_frame": 10, "end_frame": 40, "face": dict(FACE)})
    if captions:
        timeline["captions"] += [{"start_frame": 0, "end_frame": 12, "word_from": 0, "word_to": 0, "face": dict(FACE)},
                                 {"start_frame": 12, "end_frame": 30, "word_from": 1, "word_to": 1, "face": dict(FACE)}]
    return _hf_host.prepare(catalogue=cat, engine="ffmpeg", timeline=timeline, data=DATA, edl=EDL, font_serve={}, vendor=rt["vendor"], registry="/nonexistent",
                            shims=rt["runtime_dir"] + "/shims", browser_version="Chrome/1.0"), cat


def test_prepare_builds_a_page_per_caption_chunk_and_per_beat_with_the_proofs_of_the_two_ports(world):
    out, cat = prepare(world)
    assert out["pages"] == {"caption": {0: "/h/c0/index.html", 1: "/h/c1/index.html"}, P.CARD: {0: "/h/b0/index.html"}}
    assert set(out["serve"]) == {"/h/vendor/gsap.min.js", "/h/c0/index.html", "/h/c1/index.html", "/h/b0/index.html"}
    assert out["blocks"] == sorted([P.CARD, P.CAPTION]) and set(out["proofs"]) == {P.CARD, P.CAPTION}
    for name, proof in out["proofs"].items():
        assert proof["served_sha256"] == cat["blocks"][name]["determinism"]["served_sha256"] and proof["runtime_sha256"] == world["sha"]
    page = out["serve"]["/h/c1/index.html"][0].decode()
    assert '"text":"dollar"' in page and 'data-hf-zone="caption"' in page
    assert out["serve"]["/h/b0/index.html"][1] == "text/html; charset=utf-8"


def test_a_port_with_a_record_at_other_hashes_is_block_not_proven_and_a_card_port_alone_builds_only_beat_pages(world):
    assert refused(prepare, world, runtime_hash="e" * 64).code == "block_not_proven"
    assert refused(prepare, world, record=False).code in ("block_not_proven", "block_schema")
    out, _ = prepare(world, kinds=("card",), captions=False)
    assert list(out["pages"]) == [P.CARD] and out["blocks"] == [P.CARD]
    out, _ = prepare(world, kinds=("caption",), beats=False)
    assert list(out["pages"]) == ["caption"]


def test_a_timeline_with_no_second_contract_entry_prepares_nothing(world):
    folder = str(K.BLOCKS)
    cat = _blocks.load_catalogue(folder)
    out = _hf_host.prepare(catalogue=cat, engine="ffmpeg", timeline={"beats": [], "captions": [{"start_frame": 0, "end_frame": 3, "face": dict(FACE)}]}, data=DATA, edl=EDL,
                           font_serve={}, vendor=world["rt"]["vendor"], registry="", shims=world["rt"]["runtime_dir"] + "/shims", browser_version="Chrome/1.0")
    assert out["serve"] == {} and out["pages"] == {} and out["blocks"] == []


class Fake(_cdp.Chrome):
    def __init__(self, tmp_path, fail=False):
        super().__init__("/nonexistent", {}, str(tmp_path))
        self.sent, self.fail = [], fail

    def send(self, method, params=None, session=None, timeout=60):
        self.sent.append((method, params or {}, session))
        if method == "Target.closeTarget" and self.fail:
            raise _cdp.CDPError("gone")
        return {"targetId": "T", "sessionId": "S"}


def test_a_page_can_be_closed_and_a_page_that_is_already_gone_is_not_an_error(tmp_path):
    chrome = Fake(tmp_path)
    page = chrome.new_page(1080, 1920, contract="admitted")
    page.close()
    assert chrome.sent[-1] == ("Target.closeTarget", {"targetId": "T"}, None)
    gone = Fake(tmp_path, fail=True).new_page(1080, 1920, contract="admitted")
    gone.close()
