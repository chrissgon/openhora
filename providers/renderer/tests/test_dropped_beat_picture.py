"""A picture whose beat the timeline dropped (V9b-3d). One beat track: of two beats that start on the same word, the shorter is cut to nothing and dropped; the runtime
hands over the picture of every layout slot its `beats.json` lists, so the engine meets a picture whose beat is not on the timeline. It is not loaded, not drawn and
not staged, and the answer lists its slot as `assets_dropped`; a slot no beat uses at all is still `asset_unused`, a kept beat's slot with no file still `asset_missing`.

Offline: the documents are the kit's fictional post, the pictures are made in the test, the recording check is stood in for. No ffmpeg, no browser, no docker."""
from __future__ import annotations

import copy
import json

import pytest

import renderer_kit as K
import _docker as D
import _edl
import _hf_compose as C
import _blocks
import _render
from _text import Refusal

NOT_A_PNG = b"these bytes are not a picture and must never be read"


def layout(ident, number, slot, word_from, word_to):
    return {"id": ident, "beat": number, "preset": "cutaway", "params": {"asset": slot}, "word_from": word_from, "word_to": word_to, "score": 1.0}


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    """(data, edl, beats, vocab, folder): the post's overlays b3 to b6 (b4 is words 22-31) and no layout, written as files in `folder`."""
    folder = tmp_path_factory.mktemp("dropped")
    data, edl, beats, vocab = K.hf_documents(folder)
    return data, edl, beats, vocab, folder


def with_layouts(docs, rows):
    data, edl, beats, vocab, folder = docs
    return data, edl, with_slots(copy.deepcopy(beats), rows), vocab


def with_slots(beats, rows):
    """`beats` with the layouts `rows` and a described slot for each (the document check wants one)."""
    beats["layouts"] = rows
    beats["slots"] = [{"slot": r["params"]["asset"], "beat": r["beat"], "param": "asset", "type": "image|clip", "description": "a flat colour picture"} for r in rows]
    return beats


def files_for(docs, rows, tmp_path):
    """The edit list and beats written under tmp_path, for the verbs that read files."""
    data, edl, beats, vocab = with_layouts(docs, rows)
    (tmp_path / "edl.json").write_text(json.dumps(edl))
    (tmp_path / "beats.json").write_text(json.dumps(beats))
    return tmp_path / "edl.json", tmp_path / "beats.json"


def run_render(docs, rows, tmp_path, monkeypatch, assets, **over):
    """`_render.render` as a dry run, the recording check stood in for."""
    edl, beats = files_for(docs, rows, tmp_path)
    monkeypatch.setattr(_render, "check_recording", lambda *a, **k: {})
    files = {}
    for slot, raw in assets.items():
        path = tmp_path / ("%s.png" % slot)
        path.write_bytes(raw)
        files[slot] = str(path)
    args = dict(edl_path=str(edl), beats_path=str(beats), src="unused.mp4", out=str(tmp_path / "out"), platform_path=str(K.INSTAGRAM),
                vocabulary_path=str(K.VOCABULARY), asset_files=files, asset_sha256s={}, ffmpeg="ffmpeg", ffprobe="ffprobe", browser={"path": "chrome"}, dry_run=True)
    args.update(over)
    return _render.render(**args)


def a_png(rgb=(30, 120, 200)):
    from test_cutaway_look import png
    return png(8, 8, lambda x, y: rgb)


# the picture layouts a1 and a0 start together on word 22 (V9b-3e: a picture wins over a text overlay, so b4 yields to both; of two pictures the shorter, a1, is dropped)
TIED = [layout("a1", 7, "s1", 22, 24), layout("a0", 8, "s0", 22, 27)]


def test_the_timeline_drops_the_shorter_of_two_pictures_that_start_on_the_same_word(docs):
    data, edl, beats, vocab = with_layouts(docs, TIED)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    assert timeline["dropped"] == ["a1"] and {"a0", "b4"} <= {e["id"] for e in timeline["beats"]}
    used, dropped_only = _edl.classify_slots(beats, timeline, vocab, {"s0": 0, "s1": 1, "ghost": 2})
    assert used == {"s0"} and dropped_only == {"s1"}                 # `ghost` is in neither: the caller refuses it


def test_a_slot_a_kept_beat_also_uses_is_drawn_and_not_dropped(docs):
    rows = TIED + [layout("a2", 9, "s1", 53, 59)]
    data, edl, beats, vocab = with_layouts(docs, rows)
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    used, dropped_only = _edl.classify_slots(beats, timeline, vocab, {"s0": 0, "s1": 1})
    assert timeline["dropped"] == ["a1"] and used == {"s0", "s1"} and dropped_only == set()


def test_ffmpeg_a_picture_of_a_dropped_beat_is_not_read_not_drawn_and_listed(docs, tmp_path, monkeypatch):
    result = run_render(docs, TIED, tmp_path, monkeypatch, {"s1": NOT_A_PNG, "s0": a_png()})      # the bytes are no picture: a file that was read would be `asset_type`
    assert result["ok"] and result["dry_run"] is True and result["assets_dropped"] == ["s1"]
    assert "a1" in result["beats_dropped"] and "a1" not in [b["id"] for b in result["beats_drawn"]]


def test_ffmpeg_a_render_with_no_dropped_picture_has_no_assets_dropped_key(docs, tmp_path, monkeypatch):
    result = run_render(docs, [layout("a1", 7, "s1", 53, 59)], tmp_path, monkeypatch, {"s1": a_png()})
    assert "assets_dropped" not in result and [b["id"] for b in result["beats_drawn"]].count("a1") == 1


def test_ffmpeg_a_slot_no_beat_uses_is_still_asset_unused_and_a_kept_slot_with_no_file_is_still_asset_missing(docs, tmp_path, monkeypatch):
    with pytest.raises(Refusal) as unused:
        run_render(docs, TIED, tmp_path, monkeypatch, {"s1": NOT_A_PNG, "s0": a_png(), "ghost": a_png()})
    assert (unused.value.code, unused.value.field) == ("asset_unused", "ghost")
    with pytest.raises(Refusal) as missing:
        run_render(docs, [layout("a1", 7, "s1", 53, 59)], tmp_path, monkeypatch, {})
    assert (missing.value.code, missing.value.field) == ("asset_missing", "s1")


# the live shape: overlays b1 (0-4), b2 (5-13), b3 (14-21), b4 (22-31) and layouts a1 (1-4), a2 (8-18), a3 (22-27); a3 and b4 start on word 22
def live_shape(docs):
    data, edl, beats, vocab, _ = docs
    beats = copy.deepcopy(beats)
    keyword = {"text": "Name every dollar", "icon": "coin"}
    beats["overlays"] = [{"id": "b%d" % n, "beat": n, "preset": preset, "params": params, "word_from": a, "word_to": b, "score": 1.0}
                         for n, (preset, params, a, b) in enumerate([("keyword", keyword, 0, 4), ("keyword", keyword, 5, 13), ("keyword", keyword, 14, 21),
                                                                     ("list", {"items": "Review | Adjust | Celebrate", "icon": "check"}, 22, 31)], 1)]
    beats = with_slots(beats, [layout("a1", 5, "s1", 1, 4), layout("a2", 6, "s2", 8, 18), layout("a3", 7, "s3", 22, 27)])
    return data, edl, beats, vocab


def test_the_live_shape_with_a_longer_picture_beside_a3_drops_a3_and_the_dry_run_hands_back_its_slot(docs, tmp_path, monkeypatch):
    data, edl, beats, vocab = live_shape(docs)
    beats = with_slots(beats, beats["layouts"] + [layout("a4", 8, "s4", 22, 31)])          # a picture that starts with a3 and is longer: of two pictures the shorter loses
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    assert "a3" in timeline["dropped"] and "a4" not in timeline["dropped"]      # b1, b2 and b4 are dropped under pictures too
    (tmp_path / "edl.json").write_text(json.dumps(edl))
    (tmp_path / "beats.json").write_text(json.dumps(beats))
    monkeypatch.setattr(_render, "check_recording", lambda *a, **k: {})
    files = {}
    for slot, raw in (("s1", a_png()), ("s2", a_png((200, 30, 30))), ("s3", NOT_A_PNG), ("s4", a_png((30, 200, 30)))):
        (tmp_path / (slot + ".png")).write_bytes(raw)
        files[slot] = str(tmp_path / (slot + ".png"))
    result = _render.render(edl_path=str(tmp_path / "edl.json"), beats_path=str(tmp_path / "beats.json"), src="unused.mp4", out=str(tmp_path / "out"),
                            platform_path=str(K.INSTAGRAM), vocabulary_path=str(K.VOCABULARY), asset_files=files, asset_sha256s={}, ffmpeg="ffmpeg", ffprobe="ffprobe",
                            browser={"path": "chrome"}, dry_run=True)
    assert result["assets_dropped"] == ["s3"] and "a3" in result["beats_dropped"] and "a4" not in result["beats_dropped"]      # b1, b2 and b4 are dropped under pictures too


# ---------------------------------------------------------------- the HyperFrames compose

@pytest.fixture(scope="module")
def catalogue():
    return _blocks.load_catalogue()


def compose(docs, catalogue, folder, rows, assets):
    data, edl, beats, vocab = with_layouts(docs, rows)
    folder.mkdir(parents=True, exist_ok=True)
    return C.write_page(data, edl, beats, vocab, catalogue, str(folder), edl["fps"], assets)


def test_hf_a_picture_of_a_dropped_beat_is_not_in_the_page_and_is_listed(docs, catalogue, tmp_path):
    out = tmp_path / "page"
    result = compose(docs, catalogue, out, TIED, {"s1": "a" * 64, "s0": "b" * 64})
    assert result["assets_dropped"] == ["s1"] and result["beats_drawn"] == 5            # b3 to b6 and a0
    assert "s1" not in json.dumps(json.loads((out / "vars.json").read_text())) and (out / "blocks" / "oh-cutaway.html").exists()


def test_hf_a_page_with_no_dropped_picture_has_no_assets_dropped_key(docs, catalogue, tmp_path):
    result = compose(docs, catalogue, tmp_path / "page", [layout("a1", 7, "s1", 53, 59)], {"s1": "a" * 64})
    assert "assets_dropped" not in result


def test_hf_the_refusals_are_unchanged(docs, catalogue, tmp_path):
    for rows, assets, expected in ((TIED, {"s0": "c" * 64, "s1": "a" * 64, "ghost": "b" * 64}, ("asset_unused", "ghost")),
                                   ([layout("a1", 7, "s1", 53, 59)], {}, ("asset_missing", "s1"))):
        with pytest.raises(Refusal) as caught:
            compose(docs, catalogue, tmp_path / ("p%d" % len(assets)), rows, assets)
        assert (caught.value.code, caught.value.field) == expected


# ---------------------------------------------------------------- the answer schema

PAGE = {"ok": True, "page_sha256": "a" * 64, "vars_sha256": "b" * 64, "clips": 1, "zooms": 0, "duration": 1.0, "fps": 30, "layers": ["cuts"]}
RENDER = {"ok": True, "dry_run": True, "out_seconds": 3.0, "out_frames": 90, "frame_jobs": 1, "jobs": 1, "time_limit_seconds": 60, "layers": ["cuts"], "beats_drawn": [],
          "beats_dropped": ["a1"], "unmatched_beats": [], "mentions": [], "fonts": {}, "blocks": {}, "blocks_sha256": "a" * 64, "estimated_bytes": 1,
          "sha256": "c" * 64, "bytes": 1, "output": {"container": "mp4", "codec": "h264", "width": 1080, "height": 1920, "fps": 30.0, "duration": 3.0, "bytes": 1,
                                                       "faststart": True, "color": []},
          "seconds": {}, "frames_rendered": 1, "frames_reused": 0}


@pytest.mark.parametrize("verb, row", (("render", RENDER), ("hf-page", PAGE)))
def test_the_answer_schema_keeps_assets_dropped_as_a_list_of_slots_and_refuses_anything_else(verb, row):
    schema = D.RESULT_SCHEMAS[verb]
    assert D.sanitise(dict(row, assets_dropped=["a3", "s1"]), schema, verb)["assets_dropped"] == ["a3", "s1"]
    assert "assets_dropped" not in D.sanitise(row, schema, verb)
    for bad in ("s1", {"s1": 1}, [1], [["s1"]], ["s1"] * 37):
        with pytest.raises(Refusal) as caught:
            D.sanitise(dict(row, assets_dropped=bad), schema, verb)
        assert caught.value.code == "container_result_invalid"


@pytest.mark.parametrize("verb, row", (("render", RENDER), ("hf-page", PAGE)))
def test_the_effects_dropped_list_holds_the_effects_ceiling_and_the_beats_ceiling(verb, row):      # T6
    beats_max = json.load(open(K.VOCABULARY))["limits"]["beats_max"]
    assert 111 == _edl.EFFECTS_MAX + beats_max
    schema = D.RESULT_SCHEMAS[verb]
    rows = [{"id": "e%d" % k, "reason": "grade_short"} for k in range(1, 112)]
    assert len(D.sanitise(dict(row, effects_dropped=rows), schema, verb)["effects_dropped"]) == 111
    with pytest.raises(Refusal) as caught:
        D.sanitise(dict(row, effects_dropped=rows + [{"id": "e112", "reason": "grade_short"}]), schema, verb)
    assert caught.value.code == "container_result_invalid"
