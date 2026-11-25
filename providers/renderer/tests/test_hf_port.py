"""The page of one of our own ports under the second contract (PF-a4), offline: a golden of the page of a FICTIONAL tier-B fragment, the escaping of the payload,
the text checks, the band and the duration of an entry (a card, a caption chunk, a chunk over a pip's band and a piece cut at a split edge), the pin and the two
lints of the fragment, the digest and the colours. No browser, no ffmpeg. The fragments are the kit's (written for the tests, nothing copied from a port)."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

import renderer_kit as K
import hf_port_kit as P
import _blocks
import _hf_host
import _hf_port
import _layout
from _text import Refusal
from _vocab import load_data

DATA = load_data()
GOLDEN = Path(__file__).parent / "golden" / "hf-port-page.sha256"
FACE = {"x": 240, "y": 300, "w": 600, "h": 480}
ROLES = DATA["theme"]["font_roles"]
EDL = {"fps": 30, "captions": {"position": "bottom"}, "theme": {"colors": dict(DATA["theme"]["colors"]),
                                                                  "fonts": {r: {"id": "default", "weight": DATA["theme"]["default_font_weight"][r]} for r in ROLES}},
       "words": [{"index": 0, "text": "Name", "start": 0.0, "end": 0.4}, {"index": 1, "text": "every", "start": 0.4, "end": 0.8}, {"index": 2, "text": "dollar", "start": 0.8, "end": 1.2}]}
STACKS = {r: DATA["theme"]["system_fallback"][r] for r in ROLES}
BEAT = {"id": "b1", "preset": "keyword", "params": {"text": "Name every dollar"}, "start_frame": 10, "end_frame": 40, "face": dict(FACE)}
CHUNK = {"start_frame": 0, "end_frame": 36, "word_from": 0, "word_to": 2, "face": dict(FACE)}
BY_INDEX = {w["index"]: w for w in EDL["words"]}


def refused(fn, *a, **k) -> Refusal:
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


@pytest.fixture()
def world(tmp_path, monkeypatch):
    rt = P.port_runtime(monkeypatch, tmp_path)
    runtime = _hf_host.load_runtime(rt["vendor"], rt["runtime_dir"] + "/shims", 30, "Chrome/1.0")
    folder = P.blocks_folder(tmp_path, ("card", "caption"), runtime["runtime_sha256"])
    catalogue = _blocks.load_catalogue(folder)
    return {"rt": rt, "runtime": runtime, "folder": folder, "catalogue": catalogue, "tmp": tmp_path}


def page(w, kind="card", entry=None, edl=None, data=None, **over):
    block = w["catalogue"]["blocks"][P.CARD if kind == "card" else P.CAPTION]
    fragment = _hf_port.read_fragment(w["catalogue"], block)
    track = "beat" if kind == "card" else "caption"
    kw = dict(block=block, fragment=fragment, runtime=w["runtime"], faces=[], stacks=STACKS, data=data or DATA, edl=edl or EDL,
              entry=entry or (BEAT if kind == "card" else CHUNK), track=track, index=3, by_index=BY_INDEX)
    kw.update(over)
    return _hf_port.page_for(**kw).decode("utf-8")


def test_the_page_of_a_card_is_byte_for_byte_what_the_golden_says(world):
    digest = _hf_host._sha256(page(world).encode("utf-8"))
    assert digest == GOLDEN.read_text().strip()


def test_the_page_is_built_like_the_registry_page_a_template_a_host_root_the_five_shims_and_a_clipped_instance(world):
    text = page(world)
    assert text.count("<template id=\"oh-port-template\">") == 1 and 'id="oh-host" data-composition-id="oh-port" data-composition-src="/h/b3/oh-port.html"' in text
    assert text.count("hyperframes://injected/early") == 3 and text.count("hyperframes://injected/late") == 2 and "hyperframes://injected/runtime/0" in text
    top, bottom = _layout.zones(DATA, FACE)["card"]
    assert 'class="hf-inst" data-hf-zone="card" data-hf-block="%s" style="position:absolute; left:0; top:%dpx; width:1080px; height:%dpx; contain:paint; overflow:clip"' % (
        P.CARD, top, bottom - top) in text
    assert "@scope (#oh-inst) {" in text and 'window.__timelines["oh-port"] = tl' in text and "function build(root, tl, data, ctx)" in text
    assert "background:transparent" in text and "--c-accent:" in text and "--font-display:" in text and "--weight-display:" in text


def test_the_css_of_the_theme_and_the_fragment_is_in_the_page_head_and_never_inside_the_template_the_runtime_rewrites(world):
    """PF-a4d. The runtime rewrites every selector of a `<style>` it finds in a mounted composition under `[data-composition-id="oh-port"]` (and `:root`
    into that root), which can never match inside `@scope (#oh-inst)`: a port drawn so had no style at all. The CSS is in the page's own head, where the
    runtime leaves it as written; the template holds the markup and the script only."""
    text = page(world)
    template = text[text.index("<template id=\"oh-port-template\">"):text.index("</template>")]
    head = text[:text.index("<template id=\"oh-port-template\">")]
    assert "<style" not in template and "@scope" not in template and ":root" not in template
    assert ":root{--c-accent:" in head and ".hf-inst{position:absolute;display:block}" in head and "@scope (#oh-inst) {\n" in head
    assert ".badge { padding: 10px 22px;" in head.split("@scope (#oh-inst) {")[1]
    assert "[data-composition-id" not in head.split("<style>")[-1]


def test_a_caption_chunk_page_is_at_c_with_its_own_zone_band_and_the_old_engines_payload(world):
    text = page(world, "caption")
    assert 'data-composition-src="/h/c3/oh-port.html"' in text and 'data-hf-zone="caption"' in text
    top, bottom = _layout.zones(DATA, FACE)["caption"]
    assert "top:%dpx; width:1080px; height:%dpx" % (top, bottom - top) in text
    m = re.search(r"var OH_DATA = (.*);\nvar OH_CTX = (.*);\n", text)
    data, ctx = json.loads(m.group(1)), json.loads(m.group(2))
    assert [w["text"] for w in data["words"]] == ["Name", "every", "dollar"] and data["anchor"] == "bottom" and data["duration"] == 1.2
    assert ctx == {"fps": 30, "duration": 1.2, "band": {"top": top, "height": bottom - top}}


def test_the_duration_is_the_entrys_own_and_never_the_blocks_natural_one(world):
    text = page(world)                                    # the beat is 30 frames: 1.0 s; the block's natural duration is 1.0 too, so use another length
    longer = dict(BEAT, end_frame=70)
    text2 = page(world, entry=longer)
    assert 'data-duration="1.0"' in text and 'data-duration="2.0"' in text2 and "tl.set({}, {}, 2.0)" in text2
    assert _hf_port.ctx_for(DATA, longer, "card", 30)["duration"] == 2.0


@pytest.mark.parametrize("hostile", ["</script><script>x", "<!-- a", "a & b > c", "</SCRIPT >"])
def test_a_planted_text_cannot_close_the_script_or_open_a_comment(world, hostile):
    clean = page(world, "caption")
    edl = copy.deepcopy(EDL)
    edl["words"][1]["text"] = hostile
    text = page(world, "caption", edl=edl, by_index={w["index"]: w for w in edl["words"]})
    assert text.count("<script") == clean.count("<script") and text.count("</script") == clean.count("</script")
    assert text.count("<!--") == clean.count("<!--")
    m = re.search(r"var OH_DATA = (.*);\nvar OH_CTX", text)
    assert json.loads(m.group(1))["words"][1]["text"] == hostile and all(ord(c) < 128 for c in m.group(1))


def test_a_text_that_is_not_clean_is_text_not_clean_on_a_caption_word_and_on_a_parameter(world):
    edl = copy.deepcopy(EDL)
    edl["words"][0]["text"] = "é"                   # not NFC
    assert refused(page, world, "caption", edl=edl, by_index={w["index"]: w for w in edl["words"]}).code == "text_not_clean"
    assert refused(page, world, entry=dict(BEAT, params={"text": "a\u200bb"})).code == "text_not_clean"


@pytest.mark.parametrize("entry,band", [
    (dict(CHUNK, band=[1000, 1200]), [1000, 1200]),                                        # a caption over a pip's card
    (dict(CHUNK, start_frame=12, end_frame=24, band=[900, 1100], face=dict(FACE, y=200)), [900, 1100]),       # a piece cut at a split edge (the band the split gives)
    (dict(CHUNK), None),
])
def test_a_caption_chunk_is_clipped_to_its_own_band_not_the_default_one(world, entry, band):
    ctx = _hf_port.ctx_for(DATA, entry, "caption", 30)
    want = band or _layout.zones(DATA, entry["face"])["caption"]
    assert ctx["band"] == {"top": want[0], "height": want[1] - want[0]}
    assert 'top:%dpx; width:1080px; height:%dpx' % (want[0], want[1] - want[0]) in page(world, "caption", entry=entry)


def test_a_band_with_no_height_is_band_too_small(world):
    e = refused(_hf_port.ctx_for, DATA, dict(CHUNK, band=[900, 900]), "caption", 30)
    assert e.code == "band_too_small"
    _hf_port.ctx_for(DATA, dict(BEAT, face=dict(FACE, y=-50)), "card", 30)      # a face with no room above it: the band is clamped to its minimum (video P0b), not refused


def test_a_changed_or_unpinned_fragment_is_block_hash_and_a_missing_pin_is_template_not_pinned(world):
    block = world["catalogue"]["blocks"][P.CARD]
    path = Path(world["folder"]) / "hf" / "oh-test-badge" / "gsap.html"
    path.write_bytes(path.read_bytes() + b" ")
    assert refused(_hf_port.read_fragment, world["catalogue"], block).code == "block_hash"
    cat = copy.deepcopy(world["catalogue"])
    cat["files"].pop("hf/oh-test-badge/gsap.html")
    assert refused(_hf_port.read_fragment, cat, block).code == "template_not_pinned"


@pytest.mark.parametrize("extra", ["window", "random"])
def test_the_fragment_lint_refuses_a_page_reach_and_a_clock_whatever_the_pin_says(tmp_path, monkeypatch, extra):
    """The fragment lint (`_gsap_lint`) and the escape lint (`_hf_lint`) both run: a fragment that breaks either is `block_lint`, whatever its pin says."""
    rt = P.port_runtime(monkeypatch, tmp_path)
    folder = P.blocks_folder(tmp_path, ("card",), "d" * 64)
    path = Path(folder) / "hf" / "oh-test-badge" / "gsap.html"
    text = path.read_text().replace("badge.textContent = String(data.params.text);", "badge.textContent = String(data.params.text) + " + ("window.name" if "window" in extra else "Math.random()") + ";")
    path.write_text(text)
    _blocks.write_pins(folder)
    cat = _blocks.load_catalogue(folder)
    assert refused(_hf_port.read_fragment, cat, cat["blocks"][P.CARD]).code == "block_lint"


def test_the_escape_lint_alone_refuses_a_fragment_the_fragment_lint_passes(tmp_path, monkeypatch):
    P.port_runtime(monkeypatch, tmp_path)
    folder = P.blocks_folder(tmp_path, ("card",), "d" * 64)
    path = Path(folder) / "hf" / "oh-test-badge" / "gsap.html"
    path.write_text(path.read_text().replace("badge.textContent = String(data.params.text);", "badge.textContent = String(data.params.text); var f = new FontFace('x', 'y');"))
    _blocks.write_pins(folder)
    cat = _blocks.load_catalogue(folder)
    from _gsap_lint import check as gsap_check
    gsap_check(path.read_text(), P.CARD)                  # the first contract's lint lets it pass
    assert refused(_hf_port.read_fragment, cat, cat["blocks"][P.CARD]).code == "block_lint"


def test_the_digest_covers_the_fragment_and_the_version_of_the_page_shape(monkeypatch):
    raw = P.fragment().encode()
    a = _hf_port.served_digest(raw)
    assert re.fullmatch(r"[0-9a-f]{64}", a) and _hf_port.served_digest(raw + b" ") != a
    monkeypatch.setattr(_hf_port, "PORT_HOST_VERSION", _hf_port.PORT_HOST_VERSION + "x")
    assert _hf_port.served_digest(raw) != a


def test_a_colour_that_is_not_hex_is_bad_color_with_its_token(world):
    edl = copy.deepcopy(EDL)
    edl["theme"]["colors"]["accent"] = "red"
    e = refused(page, world, edl=edl)
    assert (e.code, e.field) == ("bad_color", "edl.theme.colors.accent")
