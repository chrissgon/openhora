"""The five tier-B blocks ported from the HyperFrames registry (V3b-4) and the HyperFrames engine's final defaults. Offline: the committed blocks are
loaded and linted as text, each sample is composed through the page stage (`_hf_compose`, no browser, no docker), and the licence text and the notice
are read as files. The sample texts are fictional; the source hashes below are the hashes of the registry files at the pinned commit, which the
ports were written from (the files themselves are not in the repository)."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import importlib.util
import subprocess

import pytest

import renderer_kit as K
import _blocks
import _gsap_lint
import _hf_compose as C
from _text import Refusal

COMMIT = "b4cc674f7f312e77ded32e0b53006cc0bad6723b"
LICENSE_SHA256 = "4259155fb06f127687ee7b0a8a3682d45132db0f2da26cbc0b7a2d1e796436b8"
HF_DIR = K.BLOCKS / "hf"
IMAGE_DIR = K.RENDERER / "hyperframes-image"
NOTICE = "Apache-2.0; adapted from the HyperFrames registry at b4cc674f; notices in providers/renderer/hyperframes-image/NOTICE.md"
# name -> (preset, registry component, sha256 of the registry file the port was written from)
PORTS = {
    "caption-highlight": ("caption", "caption-highlight", "769a0c2012088525b75401079bfae45e774fa39decdc37194d7f7e607c5c908e"),
    "caption-pill-karaoke": ("caption", "caption-pill-karaoke", "cdbbc72af7fbac440c0bf5750cf9e3d4ded20f26588b00ac79399342ca60b3e3"),
    "count-up": ("number", "count-up", "6b34b9873a243fedb060d23f4eb5cef1b61a5b169ec1ae064030b70b48beea66"),
    "testimonial-card": ("quote", "testimonial-card", "7edb7eaa573f8331a3f5c76c689d47989ccccbfb6027b7ac072de22df52f0510"),
    "spring-pop": ("keyword", "spring-pop", "542423b2d98bb48400280b621e7421b16ae026c2abc1ee8f64d5cca18fd8f51d"),
}
DEFAULTS = {"caption": "hf:caption-highlight", "keyword": "hf:spring-pop", "list": "oh:list", "number": "hf:count-up", "quote": "hf:testimonial-card"}
CAPTION_PORTS = [n for n, (preset, _, _) in PORTS.items() if preset == "caption"]
MAKER = "hey" + "gen"            # the registry's maker may be named in NOTICE.md and the licence file only (V0 section 8): this test never spells it out


def text_of(short: str) -> str:
    return (HF_DIR / short / "gsap.html").read_text(encoding="utf-8")


def block_doc(short: str) -> dict:
    return json.loads((HF_DIR / short / "block.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalogue():
    return _blocks.load_catalogue(str(K.BLOCKS))


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    return K.hf_documents(tmp_path_factory.mktemp("docs"))


def with_default(tmp_path, preset: str, name: str) -> dict:
    """A copy of the committed blocks whose HyperFrames engine draws `preset` with `name`; pinned again."""
    folder = tmp_path / "blocks"
    shutil.copytree(K.BLOCKS, folder)
    engine = json.loads((folder / "engines" / "hyperframes.json").read_text())
    engine["presets"][preset] = name
    (folder / "engines" / "hyperframes.json").write_text(json.dumps(engine, indent=1))
    _blocks.write_pins(str(folder))
    return _blocks.load_catalogue(str(folder))


def compose(docs, catalogue, folder, beats=None):
    data, edl, beats0, vocab = copy.deepcopy(docs)
    os.makedirs(folder, exist_ok=True)
    result = C.write_page(data, edl, beats if beats is not None else beats0, vocab, catalogue, str(folder), edl["fps"])
    return result, (folder / "index.html").read_text(encoding="utf-8"), (folder / "vars.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------- the files

def test_the_folder_holds_exactly_the_five_ports_and_in_each_only_two_files():
    assert sorted(p.name for p in HF_DIR.iterdir() if p.is_dir()) == sorted(PORTS)
    assert (HF_DIR / "allowlist.json").is_file()
    for short in PORTS:
        assert sorted(p.name for p in (HF_DIR / short).iterdir()) == ["block.json", "gsap.html"], short        # never a renderat page: an hf: block draws on one engine


@pytest.mark.parametrize("short", sorted(PORTS))
def test_a_port_loads_as_a_tier_b_block_with_the_pinned_commit_and_only_a_gsap_page(catalogue, short):
    preset, _, _ = PORTS[short]
    block = catalogue["blocks"]["hf:" + short]
    assert block["tier"] == "B" and block["commit"] == COMMIT and "files" not in block
    assert block["implementations"] == {"gsap": "gsap.html"}
    assert block["license"] == ["Apache-2.0"] and block["source"] == "hyperframes-registry" and block["may_cross_face"] is False
    assert block["notice"] == NOTICE and len(block["notice"]) < 200 and MAKER not in block["notice"].lower()
    assert block["preset"] == preset and block["band"] == ("caption" if preset == "caption" else "card")
    assert block["natural_duration"] is None if preset == "caption" else block["natural_duration"] >= 0.2
    assert _blocks.engines_of(catalogue, block) == ["hyperframes"]
    assert not any(k in spec["type"] for spec in block["params"].values() for k in ("image", "clip"))


@pytest.mark.parametrize("short", sorted(PORTS))
def test_a_port_passes_the_gsap_lint_and_is_plain_ascii_with_no_fallback_glyph(short):
    _gsap_lint.check(text_of(short), "hf:" + short)
    for name in ("gsap.html", "block.json"):
        raw = (HF_DIR / short / name).read_bytes()
        assert raw.isascii(), (short, name)               # the rating stars of one source fell back to a system font: a port draws no such character


@pytest.mark.parametrize("short", sorted(PORTS))
def test_a_ports_header_names_the_component_the_commit_and_the_notice_and_never_the_maker(short):
    preset, component, digest = PORTS[short]
    text = text_of(short)
    header = re.match(r"\s*<!--(.*?)-->", text, re.S).group(1)
    assert header.startswith(" hf:%s:" % short)
    assert "component %s " % component in header and "file %s.html" % component in header and digest in header and COMMIT in header
    assert "Apache-2.0" in header and "providers/renderer/hyperframes-image/NOTICE.md" in header and "changes:" in header
    assert MAKER not in text.lower() and MAKER not in (HF_DIR / short / "block.json").read_text().lower()
    assert "<template data-hf-block=\"hf:%s\">" % short in text


@pytest.mark.parametrize("short", sorted(PORTS))
def test_a_ports_params_are_exactly_its_presets_and_its_samples_pass_the_checker(catalogue, short):
    preset = PORTS[short][0]
    block, oh = catalogue["blocks"]["hf:" + short], catalogue["blocks"]["oh:" + preset]
    assert block["params"] == oh["params"]
    vocab = _blocks_vocab()
    assert set(block["params"]) == (set() if preset == "caption" else set(vocab["presets"][preset]["params"]))
    for sample in block["samples"]:
        assert _blocks.check_params(block, sample, vocab) == sample
    assert block["samples"] and all(set(s) <= set(block["params"]) for s in block["samples"])


def _blocks_vocab():
    from _vocab import load_vocabulary
    return load_vocabulary(str(K.VOCABULARY))


@pytest.mark.parametrize("short", [n for n in sorted(PORTS) if PORTS[n][0] != "caption"])
def test_a_card_port_uses_every_parameter_it_declares_in_its_build(short):
    script = _gsap_lint.parse(text_of(short), "hf:" + short)["script"]
    for name in block_doc(short)["params"]:
        assert re.search(r"\bP\.%s\b" % name, script) and "var P = data.params;" in script, (short, name)


@pytest.mark.parametrize("short", CAPTION_PORTS)
def test_a_caption_port_reads_the_words_the_anchor_and_the_band(short):
    script = _gsap_lint.parse(text_of(short), "hf:" + short)["script"]
    for use in ("data.words", "data.anchor", "ctx.band.height", "ctx.duration"):
        assert use in script, (short, use)
    assert block_doc(short)["params"] == {}


# ---------------------------------------------------------------- every sample composes offline and draws its values from the variables

@pytest.mark.parametrize("short", [n for n in sorted(PORTS) if PORTS[n][0] != "caption"])
def test_each_sample_of_a_card_port_composes_and_its_values_are_in_vars_json_only(tmp_path, docs, short):
    preset, _, _ = PORTS[short]
    catalogue = with_default(tmp_path, preset, "hf:" + short)
    sample_count = 0
    for k, sample in enumerate(catalogue["blocks"]["hf:" + short]["samples"]):
        beats = copy.deepcopy(docs[2])
        beat = next(e for e in beats["overlays"] if e["preset"] == preset)
        beat["params"] = dict(sample)
        result, page, variables = compose(docs, catalogue, tmp_path / ("p%d" % k), beats)
        assert result["runtimes"]["hf:" + short] == "gsap" and result["beats_drawn"] >= 1
        drawn = json.loads(variables)["inst"]
        assert any(entry.get("params") == sample for entry in drawn), short
        for value in sample.values():
            assert value in variables, (short, value)
            if len(value) >= 6:
                assert value not in page, (short, value)             # index.html holds structure and numbers only
        sample_count += 1
    assert sample_count >= 1


@pytest.mark.parametrize("short", CAPTION_PORTS)
def test_a_caption_port_composes_every_chunk_and_the_words_are_in_vars_json_only(tmp_path, docs, short):
    catalogue = with_default(tmp_path, "caption", "hf:" + short)
    result, page, variables = compose(docs, catalogue, tmp_path / "p")
    assert result["runtimes"]["hf:" + short] == "gsap" and result["captions_drawn"] >= 10
    words = sorted({w["text"] for w in docs[1]["words"] if len(w["text"]) >= 6})
    assert words
    for word in words:
        assert word in variables and word not in page, word
    assert f'data-hf-block="hf:{short}"' in page and page.count("@scope (#hf-inst-") >= result["captions_drawn"]


def test_the_committed_defaults_compose_with_four_ports_and_oh_list_and_pass_the_image_font_guard(tmp_path, docs, catalogue):
    result, page, _ = compose(docs, catalogue, tmp_path / "p")
    assert result["runtimes"] == {"hf:caption-highlight": "gsap", "hf:count-up": "gsap", "hf:spring-pop": "gsap", "hf:testimonial-card": "gsap",
                                  "oh:list": "renderat"}
    spec = importlib.util.spec_from_file_location("hf_render_for_ports", K.RENDERER / "hyperframes-image" / "hf_render.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    R.check_fonts(page)
    for name in sorted(os.listdir(tmp_path / "p" / "blocks")):
        R.check_fonts((tmp_path / "p" / "blocks" / name).read_text(encoding="utf-8"), "blocks:" + name)


# ---------------------------------------------------------------- the caption ports keep every glyph above the band's bottom

def _number(text: str, pattern: str) -> float:
    found = re.search(pattern, text)
    assert found, pattern
    return float(found.group(1))


@pytest.mark.parametrize("short", CAPTION_PORTS)
def test_a_caption_ports_declared_numbers_keep_the_lowest_line_box_above_the_band_bottom(short):
    text = text_of(short)
    parts = _gsap_lint.parse(text, "hf:" + short)
    pad = _number(parts["script"], r"\bPAD_BOTTOM = (\d+)")
    css_pad = _number(parts["style"], r"\.stage \{[^}]*inset: 0 0 (\d+)px 0;")      # the stage ends PAD_BOTTOM above the band bottom, so no element box reaches 1560
    line_height = _number(parts["style"], r"line-height: ([0-9.]+);")
    assert pad == css_pad and pad >= 24                              # the bottom padding of the stage: what is left under the last line
    assert line_height >= 1.21                                       # the glyph rectangle of Inter (1.21 em) sits inside the line box: nothing hangs below it
    assert re.search(r"\.stage \{[^}]*justify-content: flex-end;", parts["style"])          # bottom-anchored by default
    assert 'data.anchor === "center" ? "center" : "flex-end"' in parts["script"]
    scales = [float(v) for v in re.findall(r"scale[XY]?\s*:\s*([0-9.]+)", parts["script"])]
    assert all(v <= 1.03 for v in scales), scales                    # a word never grows past a hair, so no glyph leaves its box
    assert not re.search(r"\by:\s*[1-9]", parts["script"])           # nothing starts lower than its place
    assert re.search(r"lines \* fs \*", parts["script"]) and "ctx.band.height" in parts["script"]       # the type is shrunk until the lines and the padding fit the band


@pytest.mark.parametrize("short", CAPTION_PORTS)
def test_every_caption_instance_ends_at_the_caption_bottom_line_and_is_clipped_to_its_band(tmp_path, docs, short):
    catalogue = with_default(tmp_path, "caption", "hf:" + short)
    result, page, _ = compose(docs, catalogue, tmp_path / "p")
    data = docs[0]
    bottom = data["zones"]["caption_bottom"]
    rows = re.findall(r'<div id="hf-inst-\d+" class="hf-inst" data-hf-zone="caption" data-hf-block="hf:%s" style="position:absolute; left:0; top:(\d+)px; '
                      r'width:1080px; height:(\d+)px; contain:paint; overflow:clip; visibility:hidden">' % short, page)
    assert len(rows) == result["captions_drawn"] and rows
    for top, height in rows:
        assert int(top) + int(height) == bottom == 1560


# ---------------------------------------------------------------- the engines file, the ffmpeg engine and the licence texts

def test_the_hyperframes_engine_runs_both_runtimes_and_its_defaults_are_the_ports_and_oh_list(catalogue):
    engine = catalogue["engines"]["hyperframes"]
    assert engine["runtimes"] == ["gsap", "renderat"] and engine["presets"] == DEFAULTS
    assert "cutaway" not in engine["presets"] and "pip" not in engine["presets"]
    for preset, name in DEFAULTS.items():
        block = _blocks.resolve(catalogue, "hyperframes", preset, None, "beats.b1")
        assert block["name"] == name and block["preset"] == preset
    assert _blocks.resolve(catalogue, "hyperframes", "keyword", "oh:keyword", "beats.b1")["name"] == "oh:keyword"      # an oh: block stays selectable by name


@pytest.mark.parametrize("short", sorted(PORTS))
def test_an_hf_port_is_refused_on_the_ffmpeg_engine_naming_the_blocks_it_does_draw(catalogue, short):
    preset = PORTS[short][0]
    with pytest.raises(Refusal) as caught:
        _blocks.resolve(catalogue, "ffmpeg", preset, "hf:" + short, "beats.b1")
    assert caught.value.code == "block_not_on_engine" and caught.value.field == "oh:" + preset
    assert catalogue["engines"]["ffmpeg"]["presets"] == {"caption": "oh:caption", "cutaway": "oh:cutaway", "keyword": "oh:keyword", "list": "oh:list",
                                                         "number": "oh:number", "pip": "oh:pip", "quote": "oh:quote"}


def test_the_registry_licence_text_is_the_file_with_the_pinned_hash_and_travels_beside_the_notice():
    raw = (IMAGE_DIR / "LICENSE-registry-Apache-2.0.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == LICENSE_SHA256
    assert b"Apache License" in raw and b"Version 2.0, January 2004" in raw


def test_the_notice_has_one_entry_per_port_with_its_source_hash_the_commit_and_the_licence_text():
    notice = (IMAGE_DIR / "NOTICE.md").read_text(encoding="utf-8")
    assert "## Blocks adapted from the HyperFrames registry" in notice
    assert COMMIT in notice and LICENSE_SHA256 in notice and "LICENSE-registry-Apache-2.0.txt" in notice
    section = notice.split("## Blocks adapted from the HyperFrames registry", 1)[1]
    for short, (preset, component, digest) in PORTS.items():
        rows = [line for line in section.splitlines() if line.startswith("| `hf:%s` |" % short)]
        assert len(rows) == 1, short
        row = rows[0]
        assert "`%s` / `%s.html`" % (component, component) in row and digest in row and "Apache-2.0" in row and "Copyright 2026 " in row
        assert "`blocks/hf/%s/gsap.html`" % short in row
    assert "caption-kinetic-slam" in section                         # said once: it is not ported


def test_the_pins_file_and_the_catalogue_are_what_the_generator_writes(tmp_path):
    folder = tmp_path / "blocks"
    shutil.copytree(K.BLOCKS, folder)
    _blocks.write_pins(str(folder))
    _blocks.write_catalogue(str(folder))
    for name in ("pins.json", "catalogue.json"):
        assert (K.BLOCKS / name).read_bytes() == (folder / name).read_bytes(), name


def test_the_maker_is_named_nowhere_in_the_blocks_folder():
    for path in sorted(K.BLOCKS.rglob("*")):
        if path.is_file():
            assert MAKER not in path.read_text(encoding="utf-8").lower(), path


def test_the_composed_scripts_of_the_ports_parse_when_node_exists(tmp_path, docs, catalogue):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    _, page, _ = compose(docs, catalogue, tmp_path / "p")
    scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
    assert scripts
    source = tmp_path / "scripts.js"
    source.write_text("\n".join(scripts), encoding="utf-8")
    done = subprocess.run([node, "--check", str(source)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[:500]


@pytest.mark.parametrize("short", sorted(PORTS))
def test_each_ports_gsap_page_is_pinned_with_the_sha256_of_its_bytes(short):
    import _frames
    pins = _frames.template_pins()
    rel = "hf/%s/gsap.html" % short
    assert pins[rel] == hashlib.sha256((HF_DIR / short / "gsap.html").read_bytes()).hexdigest()


NODE_STUB = r"""
function el(cls) {
  const o = {cls, kids: [], text: "", style: {setProperty() {}}, removed: false};
  o.querySelector = (sel) => { const c = sel.slice(1); if (o.cls === c) return o; for (const k of o.kids) { if (k.cls === c) return k; } const k = el(c); o.kids.push(k); return k; };
  o.cloneNode = () => el(o.cls);
  o.appendChild = (k) => { o.kids.push(k); return k; };
  o.remove = () => { o.removed = true; };
  o.querySelectorAll = () => [];
  Object.defineProperty(o, "textContent", {get() { return o.text; }, set(v) { o.text = v; }});
  return o;
}
const root = el("root");
const tl = {fromTo() {}, to() {}, set() {}};
const data = JSON.parse(process.argv[2]);
build(root, tl, data, {fps: 30, duration: 1.2, band: {top: 1240, height: 320}});
const texts = [];
(function walk(o) { if (o.removed) return; if (o.text) texts.push(o.text); o.kids.forEach(walk); })(root);
console.log(JSON.stringify(texts));
"""


@pytest.mark.parametrize("short", CAPTION_PORTS)
def test_a_caption_ports_build_puts_every_word_of_a_chunk_into_the_page_as_text(tmp_path, short):
    """Runs the fragment's `build` in node against a minimal stand-in for the elements it touches: every word of the chunk must end up as non-empty
    text in the line it builds. Fails when a caption port draws a chunk that has words and no text."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = _gsap_lint.parse(text_of(short), "hf:" + short)["script"]
    words = [{"text": "Alpha", "start": 0.0, "end": 0.4}, {"text": "beta", "start": 0.4, "end": 0.8}, {"text": "Gamma", "start": 0.8, "end": 1.1}]
    data = {"words": words, "anchor": "bottom", "duration": 1.2, "zones": {"caption": [1240, 1560]}, "margin": 14}
    program = tmp_path / "build_stub.js"
    program.write_text(script + "\n" + NODE_STUB, encoding="utf-8")
    done = subprocess.run([node, str(program), json.dumps(data)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[:500]
    shown = json.loads(done.stdout)
    assert shown and all(t for t in shown)
    for word in ("Alpha", "beta", "Gamma"):
        assert word in shown, (short, shown)
