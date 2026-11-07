"""The base page of the HyperFrames engine (`_hf_page.py`): the cuts and the zoom, numbers only, the same bytes for the same edit list.
The edit list is made from the kit's fictional transcript and a synthetic analysis; no media tool is needed."""
from __future__ import annotations

import html.parser
import json
import os
import re

import pytest

import renderer_kit as K
import _edl
import _hf_page
from _text import Refusal
from _vocab import load_data

DATA = load_data()
EMPTY_BEATS = {"schema_version": 1, "threshold": 0.6, "slots": [], "report": [], "unmatched": [], "fallbacks": [], "layouts": [], "overlays": []}


def make_edl(has_audio=True):
    doc = K.build_transcript()
    spans = K.speech_spans(doc["words"], join=0.6)
    silences = [{"start": round(a[1], 3), "end": round(b[0], 3)} for a, b in zip(spans, spans[1:]) if b[0] - a[1] > 0.5]
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": has_audio},
                "silences": silences if has_audio else None}
    edl, _ = _edl.build_base(doc, analysis, DATA, {})
    return doc, edl


def write(edl, folder, **over):
    folder.mkdir(exist_ok=True)
    args = dict(width=1080, height=1920, fps=edl["fps"], background="#0B0F14")
    args.update(over)
    return _hf_page.write_page(edl, str(folder), **args)


class Texts(html.parser.HTMLParser):
    """Every text node outside <script> and <style>."""

    def __init__(self):
        super().__init__()
        self.stack, self.found = [], []

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack.pop() != tag:
                pass

    def handle_data(self, data):
        if data.strip() and not (self.stack and self.stack[-1] in ("script", "style")):
            self.found.append(data.strip())


def test_two_calls_write_the_same_bytes(tmp_path):
    _, edl = make_edl()
    one, two = write(edl, tmp_path / "a"), write(edl, tmp_path / "b")
    assert one == two
    for name in ("index.html", "vars.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert one["layers"] == ["cuts", "zoom"] and one["fps"] == edl["fps"]


def test_the_page_names_no_font_and_holds_no_text_node(tmp_path):
    _, edl = make_edl()
    write(edl, tmp_path / "p")
    page = (tmp_path / "p" / "index.html").read_text(encoding="utf-8")
    assert "font-family" not in page and "@font-face" not in page and "font:" not in page
    texts = Texts()
    texts.feed(page)
    assert texts.found == []


def test_no_word_of_the_transcript_reaches_the_page_or_the_variables(tmp_path):
    doc, edl = make_edl()
    write(edl, tmp_path / "p")
    both = ((tmp_path / "p" / "index.html").read_text() + (tmp_path / "p" / "vars.json").read_text()).lower()
    words = {re.sub(r"[^a-z]", "", w["text"].lower()) for w in doc["words"]}
    for word in sorted(w for w in words if len(w) >= 6):         # short words occur inside markup names (for example "money" is not, "video" is)
        assert word not in both, word


def test_the_variables_are_numbers_and_lists_of_numbers_only(tmp_path):
    _, edl = make_edl()
    write(edl, tmp_path / "p")
    doc = json.loads((tmp_path / "p" / "vars.json").read_text())
    assert set(doc) == {"duration", "fps", "zooms"}

    def numbers_only(value):
        if isinstance(value, list):
            return all(numbers_only(v) for v in value)
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    assert all(numbers_only(v) for v in doc.values())
    assert doc["duration"] == pytest.approx(edl["out_frames"] / edl["fps"])


def test_there_is_one_zoom_wrapper_per_kept_range_and_the_zooms_follow_the_zoom_module(tmp_path):
    _, edl = make_edl()
    assert len(edl["kept"]) >= 2
    result = write(edl, tmp_path / "p")
    page = (tmp_path / "p" / "index.html").read_text()
    assert page.count('class="zw"') == len(edl["kept"]) == result["clips"]
    assert page.count("<video ") == len(edl["kept"]) and page.count('src="media/proxy.mp4"') == len(edl["kept"])
    levels = [_edl._media.zoom_levels(edl["zoom"], k, b - a, edl["fps"]) for k, (a, b) in enumerate(edl["kept"])]
    assert result["zooms"] == sum(1 for z0, z1 in levels if abs(z0 - 1) > 1e-9 or abs(z1 - 1) > 1e-9) > 0
    assert 'data-composition-id="main"' in page and 'window.__timelines["main"] = main' in page
    assert 'data-width="1080"' in page and 'data-height="1920"' in page and "paused: true" in page


def test_the_cuts_carry_their_times_and_the_volume_lanes_fade_at_each_cut(tmp_path):
    _, edl = make_edl()
    write(edl, tmp_path / "p")
    page = (tmp_path / "p" / "index.html").read_text()
    fps = float(edl["fps"])
    first = re.search(r'data-start="([^"]+)" data-duration="([^"]+)" data-media-start="([^"]+)" data-track-index="0" data-automation=\'([^\']+)\'', page)
    a, b = edl["kept"][0]
    assert float(first.group(1)) == 0.0 and float(first.group(2)) == pytest.approx((b - a) / fps) and float(first.group(3)) == pytest.approx(a / fps)
    points = json.loads(first.group(4))["lanes"][0]["points"]
    assert points[0] == {"t": 0, "v": 0} and points[1]["v"] == 1 and points[1]["t"] == pytest.approx(DATA["zoom"]["audio_fade_seconds"])
    assert 'data-has-audio="true"' in page


def test_a_recording_without_audio_says_so(tmp_path):
    _, edl = make_edl(has_audio=False)
    write(edl, tmp_path / "p")
    page = (tmp_path / "p" / "index.html").read_text()
    assert 'data-has-audio="false"' in page and 'data-has-audio="true"' not in page


@pytest.mark.parametrize("color", ["red", "#fff", "#GGGGGG", "0B0F14", "#0B0F14 ", "", None, "#0B0F14;}</style>"])
def test_a_background_that_is_not_a_hex_colour_is_refused(tmp_path, color):
    _, edl = make_edl()
    with pytest.raises(Refusal) as caught:
        write(edl, tmp_path / "p", background=color)
    assert caught.value.code == "bad_color"


def test_a_folder_with_anything_in_it_or_none_is_refused(tmp_path):
    _, edl = make_edl()
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x").write_text("x")
    with pytest.raises(Refusal) as caught:
        write(edl, tmp_path / "full")
    assert caught.value.code == "page_dir_not_empty"
    with pytest.raises(Refusal) as caught:
        _hf_page.write_page(edl, str(tmp_path / "absent"), width=1080, height=1920, fps=30, background="#0B0F14")
    assert caught.value.code == "page_dir_not_empty"
    assert (tmp_path / "full" / "x").read_text() == "x"


def verb(tmp_path, edl, *more):
    K.write_json(tmp_path / "edl.json", edl)
    K.write_json(tmp_path / "beats.json", EMPTY_BEATS)
    return K.run_verb("hf-page", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--vocabulary", K.VOCABULARY,
                      "--platform-file", K.INSTAGRAM, "--out", tmp_path / "page", *more)


def test_the_verb_without_base_only_refuses_overlays_not_built(tmp_path):
    _, edl = make_edl()
    rc, out, err = verb(tmp_path, edl)
    assert rc == 1 and out["code"] == "overlays_not_built" and out["field"] == "hf-page"
    assert not (tmp_path / "page").exists()


def test_the_verb_writes_the_page_and_its_result_passes_the_closed_schema(tmp_path):
    import _docker as D
    _, edl = make_edl()
    rc, out, err = verb(tmp_path, edl, "--base-only")
    assert rc == 0, err
    assert sorted(os.listdir(tmp_path / "page")) == ["index.html", "vars.json"]
    clean = D.sanitise(out, D.RESULT_SCHEMAS["hf-page"], "hf-page")
    assert clean["clips"] == len(edl["kept"]) and clean["fps"] == edl["fps"] and clean["layers"] == ["cuts", "zoom"]


def test_the_verb_checks_the_documents_before_it_writes(tmp_path):
    _, edl = make_edl()
    edl["kept"] = [[0, 0]]
    rc, out, err = verb(tmp_path, edl, "--base-only")
    assert rc == 1 and out["ok"] is False
    assert not (tmp_path / "page").exists()
