"""V9a-1: the three review-only presets (`mark`, `sticker`, `nametag`): merged into the vocabulary the renderer reads, never nameable by a script,
drawn by one `oh:` page each on both engines. Offline: the pages are linted and their pure geometry runs in node (skipped where node is not
installed); no browser. All texts are fictional."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

import pytest

import renderer_kit as K
import _align
import _blocks
import _lint
import _vocab
from _text import Refusal
from _vocab import load_data, load_vocabulary, review_only

NAMES = ("mark", "nametag", "sticker")
VOCAB = load_vocabulary(str(K.VOCABULARY))
DATA = load_data()
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed")
GLYPHS = ["check", "star", "bolt", "arrow-up", "heart", "flag", "clock", "coin", "bulb", "question", "exclaim", "eye"]


@pytest.fixture(scope="module")
def catalogue():
    return _blocks.load_catalogue(str(K.BLOCKS))


def refused(fn, *a, **k) -> Refusal:
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


def page_of(name: str) -> str:
    return (K.BLOCKS / "oh" / name / "renderat.html").read_text(encoding="utf-8")


def test_the_vocabulary_merges_the_three_review_presets_marked():
    for name in NAMES:
        assert name in VOCAB["presets"] and VOCAB["presets"][name]["review_only"] is True and review_only(VOCAB, name)
        assert VOCAB["presets"][name]["kind"] == "overlay" and VOCAB["presets"][name]["main"] in VOCAB["presets"][name]["params"]
    for name in ("keyword", "list", "number", "quote", "cutaway", "pip"):
        assert not review_only(VOCAB, name) and "review_only" not in VOCAB["presets"][name], name
    assert not review_only(VOCAB, "explode") and not review_only(VOCAB, None)
    shared = json.loads(K.VOCABULARY.read_text(encoding="utf-8"))
    assert not set(NAMES) & set(shared["presets"])             # the shared vocabulary file, and so the skill's checker, never holds them
    assert set(DATA["review_presets"]) == set(NAMES) and set(NAMES) <= set(DATA["presets"])      # each has its timing beside the others


def test_a_clash_with_a_vocabulary_preset_is_refused(monkeypatch):
    clashing = dict(DATA, review_presets=dict(DATA["review_presets"], keyword=DATA["review_presets"]["mark"]))
    monkeypatch.setattr(_vocab, "load_data", lambda name="renderer-presets.json": clashing)
    err = refused(load_vocabulary, str(K.VOCABULARY))
    assert err.code == "vocabulary_clash" and err.field == "keyword"


def test_a_malformed_review_preset_is_refused(monkeypatch):
    bad = dict(DATA, review_presets={"mark": {"kind": "overlay", "summary": "x", "main": "nothing", "params": {}}})
    monkeypatch.setattr(_vocab, "load_data", lambda name="renderer-presets.json": bad)
    assert refused(load_vocabulary, str(K.VOCABULARY)).code == "not_a_vocabulary"


def test_a_vocabulary_written_back_out_loads_again(tmp_path):
    path = tmp_path / "v.json"
    path.write_text(json.dumps(VOCAB), encoding="utf-8")
    again = load_vocabulary(str(path))
    assert all(review_only(again, n) for n in NAMES)


SCRIPT_TEMPLATE = "# Post\n\n```script\nbeat: 1\nline: Here is the first rule of money.\non-screen: %s\npreset: %s\n%s\n\nbeat: 2\nline: Follow for more.\n```\n"


@pytest.mark.parametrize("preset,main,extra", [("mark", "Name every dollar", "mark: circle"), ("sticker", "bulb", "side: left"), ("nametag", "Aster Lane", "color: accent")])
def test_a_script_naming_a_review_preset_is_refused(preset, main, extra):
    err = refused(_align.read_script, SCRIPT_TEMPLATE % (main, preset, extra), VOCAB)
    assert err.code == "preset_review_only" and err.field == "beat1"
    _align.read_script(SCRIPT_TEMPLATE % ("Name every dollar", "keyword", "icon: coin"), VOCAB)       # a script preset still reads


@pytest.mark.parametrize("name", NAMES)
def test_each_new_block_is_card_band_and_never_crosses_the_face(catalogue, name):
    block = catalogue["blocks"]["oh:" + name]
    assert block["kind"] == "overlay" and block["band"] == "card" and block["may_cross_face"] is False
    assert block["license"] == ["MIT"] and block["source"] == "openhora" and block["preset"] == name
    assert "dataset.zone = 'card'" in page_of(name) or "dataset.zone = 'card';" in page_of(name)
    assert list(block["implementations"]) == ["renderat"]
    assert _lint.lint(page_of(name)) == []
    assert block["natural_duration"] == {"mark": 1.2, "sticker": 0.8, "nametag": 2.5}[name]


@pytest.mark.parametrize("name", NAMES)
def test_each_new_block_params_equal_its_review_preset(catalogue, name):
    block = catalogue["blocks"]["oh:" + name]
    assert block["params"] == DATA["review_presets"][name]["params"] == VOCAB["presets"][name]["params"]
    html = page_of(name)
    assert set(filter(None, re.search(r'<meta name="pv-params" content="([^"]*)">', html).group(1).split(","))) == set(block["params"])
    assert re.search(r'<meta name="pv-preset" content="([^"]*)">', html).group(1) == name
    assert set(re.findall(r"\bP\.([a-z0-9_]+)", html)) <= set(block["params"])
    assert set(re.findall(r"\bP\.([a-z0-9_]+)", html)) == set(block["params"])           # the page reads every parameter it declares
    assert "innerHTML" not in html and DATA["presets"][name]["looks"] == {}


@pytest.mark.parametrize("name", NAMES)
def test_each_sample_passes_the_checker(catalogue, name):
    block = catalogue["blocks"]["oh:" + name]
    assert 1 <= len(block["samples"]) <= 3
    for sample in block["samples"]:
        assert _blocks.check_params(block, sample, VOCAB) == sample
        assert _vocab.check_params(VOCAB, name, sample) == sample


def test_the_sticker_glyphs_are_the_twelve_names(catalogue):
    values = catalogue["blocks"]["oh:sticker"]["params"]["glyph"]["values"]
    assert values == GLYPHS and values[:8] == VOCAB["icons"]
    table = re.search(r"const ICONS = \{(.*?)\n\};", page_of("sticker"), re.S).group(1)
    assert re.findall(r"^  '([a-z-]+)':", table, re.M) == GLYPHS
    assert refused(_vocab.check_params, VOCAB, "sticker", {"glyph": "skull"}).code == "bad_choice"
    assert refused(_vocab.check_params, VOCAB, "sticker", {}).code == "missing_param"
    assert refused(_vocab.check_params, VOCAB, "mark", {"text": "x" * 25}).code == "text_too_long"
    assert refused(_vocab.check_params, VOCAB, "mark", {"text": "ok", "mark": "wave"}).code == "bad_choice"
    assert refused(_vocab.check_params, VOCAB, "nametag", {"name": "x" * 33}).code == "text_too_long"


def test_both_engines_map_the_three(catalogue):
    for engine in ("ffmpeg", "hyperframes"):
        presets = catalogue["engines"][engine]["presets"]
        for name in NAMES:
            assert presets[name] == "oh:" + name
            assert _blocks.resolve(catalogue, engine, name, None, "beats.b1")["name"] == "oh:" + name
        assert list(presets) == sorted(presets)                 # alphabetical, as the files are
    for engine in ("ffmpeg", "hyperframes"):
        path = K.BLOCKS / "engines" / (engine + ".json")
        assert json.loads(path.read_text(encoding="utf-8"))["presets"].keys() >= set(NAMES)
    assert set(catalogue["engines"]["ffmpeg"]["presets"]) == set(VOCAB["presets"]) | {"caption"}


def test_the_skill_checker_does_not_know_them(tmp_path):
    post = tmp_path / "post.md"
    post.write_text(SCRIPT_TEMPLATE % ("Name every dollar", "mark", "mark: circle"), encoding="utf-8")
    done = subprocess.run([sys.executable, str(K.CHECKER), "--content", str(post), "--presets", str(K.VOCABULARY)], capture_output=True, text=True)
    report = json.loads(done.stdout)
    assert report["ok"] is False
    assert {"beat": 1, "field": "preset", "code": "unknown_preset"} in report["problems"]


# ---------------------------------------------------------------- the geometry of the pages, in node

def page_script(name: str) -> str:
    return re.search(r"<script>(.*?)</script>", page_of(name), re.S).group(1)


def run_node(program: str, tmp_path, payload=None):
    path = tmp_path / "p.js"
    path.write_text(program, encoding="utf-8")
    done = subprocess.run([NODE, str(path), json.dumps(payload)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[:800]
    return json.loads(done.stdout)


def mark_pure(tmp_path, body: str, payload):
    """The page's pure functions (everything before `window.renderAt`), then `body`, which reads `input`."""
    pure = page_script("mark").split("window.renderAt")[0]
    return run_node(pure + "\nconst input = JSON.parse(process.argv[2]);\n" + body, tmp_path, payload)


@needs_node
def test_the_mark_page_sizes_its_text_by_the_keyword_rule(tmp_path):
    out = mark_pure(tmp_path, "console.log(JSON.stringify(input.map(function (c) { return fit(c[0], c[1], c[2]); })));",
                    [["Name every dollar", 492, 950], ["Save money", 492, 950], ["Go", 492, 950], ["Name every dollar", 492, 820]])
    assert out[0]["lines"] == ["Name every", "dollar"] and round(out[0]["size"], 1) == 110.5
    assert out[1]["lines"] == ["Save money"] and round(out[1]["size"], 1) == 110.5
    assert out[2]["size"] == 140                                              # FS_MAX of the mark page
    assert out[3]["size"] < out[0]["size"] or out[3]["size"] == out[0]["size"] == 950 / 8.6 and round(out[3]["size"], 1) <= 110.5


@needs_node
def test_the_mark_paths_are_fixed_finite_and_hold_the_room_they_declare(tmp_path):
    body = """
const out = {};
['underline', 'circle', 'arrow', 'none'].forEach(function (m) { out[m] = [markPath(m, 620, 240), markPath(m, 620, 240), extent(m, 620, 240)]; });
console.log(JSON.stringify(out));
"""
    out = mark_pure(tmp_path, body, None)
    for mark, (first, again, room) in out.items():
        assert first == again, mark                                            # no randomness: the same text every time
        assert not re.search(r"NaN|Infinity|undefined", first), mark
    assert out["none"][0] == "" and out["none"][2] == {"l": 0, "r": 0, "t": 0, "b": 0}
    assert out["underline"][0] == "M 0 254 C 186.0 244, 434.0 264, 620 252"
    assert out["arrow"][0].startswith("M -120 330 Q -110 110.0, -16 120.0 M -36 102.0 L -16 120.0 L -38 134.0") and out["arrow"][2]["l"] == 130
    circle = out["circle"][0]
    assert circle.startswith("M ") and circle.count(" C ") == 4
    assert out["circle"][2]["l"] == out["circle"][2]["r"] and out["circle"][2]["t"] == out["circle"][2]["b"] > 28


# ---------------------------------------------------------------- the other two pages keep to their bands

def test_the_sticker_and_nametag_pages_state_their_numbers():
    sticker, nametag = page_script("sticker"), page_script("nametag")
    assert "left: { x: 150, tilt: -8 }" in sticker and "center: { x: 540, tilt: 0 }" in sticker and "right: { x: 930, tilt: 8 }" in sticker
    assert "easeOutBack(clamp(t / 0.3), 1.7)" in sticker and "0.4 + 0.6 *" in sticker and "const SIZE = 220" in sticker
    assert "NAME_PX = 52, ROLE_PX = 34, MAX_TEXT = 900" in nametag and "BOTTOM_GAP = 24" in nametag and "left:60px" in page_of("nametag")
    assert "clamp(t / 0.3)" in nametag and "clamp((data.duration - t) / 0.25)" in nametag and "-40 *" in nametag
    assert "var(--c-bg)" in page_of("nametag") and "font-weight:var(--weight-display)" in page_of("nametag")
