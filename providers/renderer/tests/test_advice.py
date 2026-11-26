"""Advice, not refusal (video P0b): the closed rows, the room and the text and the span rules that report instead of refusing, and the layout fallbacks.
Every document is generated here; no recording, no image."""
from __future__ import annotations

import copy
import json

import pytest

import renderer_kit as K
import _advice as A
import _align as AL
import _docker
import _edl
import _layout
import _timeline as T
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
ALLOW = {"fixture-800": {"id": "fixture-800"}}


# ---------------------------------------------------------------- T1: the rows

def test_a_merge_keeps_the_worst_value_of_a_max_code_and_of_a_min_code():
    rows = []
    A.add(rows, "caption_below_line", 1570, 1560, "c1")
    A.add(rows, "caption_below_line", 1600, 1560, "c2")
    A.add(rows, "caption_below_line", 1580, 1560, "c3")
    assert rows == [{"code": "caption_below_line", "value": 1600, "default": 1560, "count": 3, "ids": ["c1", "c2", "c3"]}]
    low = []
    A.add(low, "card_room_small", 60, 80)
    A.add(low, "card_room_small", 40, 80)
    A.add(low, "card_room_small", 70, 80)
    assert low == [{"code": "card_room_small", "value": 40, "default": 80, "count": 3}]


def test_an_id_seen_again_is_the_same_item_and_ids_stop_at_twelve():
    rows = []
    A.add(rows, "text_over_default", 30, 24, "b1")
    A.add(rows, "text_over_default", 40, 24, "b1")
    assert rows[0]["count"] == 1 and rows[0]["value"] == 40 and rows[0]["ids"] == ["b1"]
    many = []
    for k in range(20):
        A.add(many, "beat_shorter_than_default", 0.5, 1.0, "b%d" % k)
    assert many[0]["count"] == 20 and len(many[0]["ids"]) == 12
    A.add(many, "beat_shorter_than_default", 0.5, 1.0, "Not An Id")      # an id outside the closed pattern is left out
    assert len(many[0]["ids"]) == 12


def test_an_unknown_code_or_a_number_that_is_not_finite_is_a_value_error():
    with pytest.raises(ValueError):
        A.add([], "made_up", 1, 1)
    with pytest.raises(ValueError):
        A.add([], "punch_short", float("nan"), 0.4)
    with pytest.raises(ValueError):
        A.add([], "punch_short", True, 0.4)


def test_rows_of_nothing_is_an_empty_list_and_rows_are_sorted_by_code():
    assert A.rows([]) == [] and A.rows(None) == []
    found = []
    A.add(found, "punch_short", 0.3, 0.4)
    A.add(found, "aside_repeated", 2, 1)
    assert [r["code"] for r in A.rows(found)] == ["aside_repeated", "punch_short"]


def test_merge_joins_lists_and_refuses_a_row_that_is_not_closed():
    a, b = [], []
    A.add(a, "block_not_drawn", 6, 0, "b1")
    A.add(b, "block_not_drawn", 9, 0, "b2")
    got = A.merge(a, b, None)
    assert got == [{"code": "block_not_drawn", "value": 9, "default": 0, "count": 2, "ids": ["b1", "b2"]}]
    for bad in ({"code": "block_not_drawn", "value": 1, "default": 0}, {"code": "x", "value": 1, "default": 0, "count": 1},
                {"code": "block_not_drawn", "value": 1, "default": 0, "count": 0}, {"code": "block_not_drawn", "value": 1, "default": 0, "count": 1, "ids": ["A"]},
                {"code": "block_not_drawn", "value": 1, "default": 0, "count": 1, "extra": 1}):
        with pytest.raises(ValueError):
            A.merge([bad])


def test_every_code_has_a_unit_and_a_worst():
    assert len(A.CODES) == 16
    for code, (worst, unit) in A.CODES.items():
        assert worst in ("max", "min") and unit


# ---------------------------------------------------------------- T2: the room

HIGH_FACE = {"x": 240, "y": 150, "w": 600, "h": 500}      # 150 - 18 - 110 = 22 px above it


def test_a_face_box_high_in_the_frame_passes_and_reports_the_room():
    advice = []
    assert _edl.check_face(DATA, dict(HIGH_FACE), advice=advice) == HIGH_FACE
    assert advice == [{"code": "card_room_small", "value": 22, "default": 80, "count": 1}]
    low = []
    _edl.check_face(DATA, {"x": 240, "y": 1000, "w": 600, "h": 500}, advice=low)
    assert [r["code"] for r in low] == ["caption_room_small"] and low[0]["default"] == 120


def test_a_face_box_with_ample_room_gives_no_advice_and_the_zones_it_always_gave():
    advice = []
    _edl.check_face(DATA, dict(DATA["face_box_default"]), advice=advice)
    assert advice == []
    f = DATA["face_box_default"]
    assert _layout.zones(DATA, f) == {"card": [110, f["y"] - 18], "caption": [f["y"] + f["h"] + 18, 1560]}


def test_the_zones_clamp_a_band_to_its_minimum():
    z = _layout.zones(DATA, HIGH_FACE)
    assert z["card"] == [110, 190]                # card_top + card_min_height
    z = _layout.zones(DATA, {"x": 240, "y": 1000, "w": 600, "h": 500})
    assert z["caption"] == [1440, 1560]           # caption_bottom - caption_min_height


def test_a_face_box_that_is_not_a_box_is_still_refused():
    for bad in ({"x": 0, "y": 0, "w": 50, "h": 500}, {"x": 900, "y": 0, "w": 600, "h": 500}, {"x": 1, "y": 1, "w": 600}):
        with pytest.raises(Refusal):
            _edl.check_face(DATA, bad)


def test_the_base_with_a_high_face_box_is_built_and_reports():
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    advice = []
    edl, notes = _edl.build_base(doc, analysis, DATA, ALLOW, face_box=dict(HIGH_FACE), retake_mode="propose", advice=advice)
    assert isinstance(notes, list) and edl["face_box"] == HIGH_FACE
    assert advice and advice[0]["code"] == "card_room_small"


# ---------------------------------------------------------------- T6 and T8: beats, punches, asides, texts, spans

def make():
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, ALLOW, retake_mode="propose")
    rows = [r for r in AL.read_beats(K.POST, VOCAB) if r["preset"]]
    tr = T.check_transcript(doc, DATA["limits"])
    words, _ = T.normalise_words(tr["words"], tr["segments"], tr["duration"])
    beats = AL.build_beats(rows, AL.align_beats([w for w in words if not w["dropped"]], rows), VOCAB, 0.6, {})
    return edl, beats


def more_beats(beats, total):
    out = copy.deepcopy(beats)
    base = out["overlays"][0]
    n = len(out["overlays"]) + len(out["layouts"])
    for k in range(total - n):
        out["overlays"].append(dict(base, id="x%d" % k))
    return out


def test_more_beats_than_the_vocabulary_says_pass_with_advice_up_to_the_ceiling():
    edl, beats = make()
    limit = VOCAB["limits"]["beats_max"]
    assert "advice" not in _edl.check_beats(beats, edl, VOCAB)
    over = _edl.check_beats(more_beats(beats, limit + 1), edl, VOCAB)
    assert {"code": "beats_over_default", "value": limit + 1, "default": limit, "count": 1} in over["advice"]
    _edl.check_beats(more_beats(beats, _edl.BEATS_CEILING), edl, VOCAB)
    with pytest.raises(Refusal) as e:
        _edl.check_beats(more_beats(beats, _edl.BEATS_CEILING + 1), edl, VOCAB)
    assert e.value.code == "too_many_beats"


def test_punches_past_the_default_pass_with_advice_and_the_hundredth_is_refused():
    edl, beats = make()
    index = edl["words"][0]["index"]

    def punches(n):
        out = copy.deepcopy(beats)
        out["punches"] = [{"beat": k + 1, "word_from": index, "word_to": index, "score": 0.9} for k in range(n)]
        return out
    limit = VOCAB["limits"]["beats_max"]
    got = _edl.check_beats(punches(limit + 1), edl, VOCAB)
    assert {"code": "punches_over_default", "value": limit + 1, "default": limit, "count": 1} in got["advice"]
    _edl.check_beats(punches(99), edl, VOCAB)
    with pytest.raises(Refusal) as e:
        _edl.check_beats(punches(100), edl, VOCAB)
    assert e.value.code == "too_many_punches"


def aside_beats(beats, edl, asides=1, punched=False):
    out = copy.deepcopy(beats)
    n = max(e["beat"] for e in out["overlays"] + out["layouts"])
    word = edl["words"][0]["index"]
    for k in range(asides):
        out["overlays"].append({"id": "as%d" % k, "beat": n + 1 + k, "preset": "aside", "params": {}, "word_from": word, "word_to": word, "score": 0.9})
    if punched:
        out["punches"] = [{"beat": n + 1, "word_from": word, "word_to": word, "score": 0.9}]
    return out


@pytest.mark.skipif("aside" not in VOCAB["presets"], reason="the vocabulary has no aside")
def test_two_asides_and_a_punch_on_an_aside_are_advice():
    edl, beats = make()
    two = _edl.check_beats(aside_beats(beats, edl, asides=2), edl, VOCAB)
    assert {"code": "aside_repeated", "value": 2, "default": 1, "count": 2, "ids": ["as0", "as1"]} in two["advice"]
    one = _edl.check_beats(aside_beats(beats, edl, punched=True), edl, VOCAB)
    assert {"code": "aside_with_punch", "value": 1, "default": 0, "count": 1, "ids": ["as0"]} in one["advice"]
    assert not any(r["code"] == "aside_repeated" for r in one["advice"])


def test_a_text_over_its_max_is_advice_up_to_240_and_refused_over_it():
    edl, beats = make()
    spec = VOCAB["presets"]["keyword"]["params"]["text"]
    key = next(e for e in beats["overlays"] if e["preset"] == "keyword")

    def with_text(n):
        out = copy.deepcopy(beats)
        row = next(e for e in out["overlays"] if e["id"] == key["id"])
        row["params"]["text"] = "a" * n
        return out
    got = _edl.check_beats(with_text(spec["max"] + 6), edl, VOCAB)
    assert {"code": "text_over_default", "value": spec["max"] + 6, "default": spec["max"], "count": 1, "ids": [key["id"]]} in got["advice"]
    assert not any(r["code"] == "text_over_default" for r in _edl.check_beats(with_text(spec["max"]), edl, VOCAB).get("advice", []))
    _edl.check_beats(with_text(240), edl, VOCAB)
    with pytest.raises(Refusal) as e:
        _edl.check_beats(with_text(241), edl, VOCAB)
    assert e.value.code == "text_too_long"
    bad = with_text(5)
    next(x for x in bad["overlays"] if x["id"] == key["id"])["params"]["text"] = "ab\ncd"
    with pytest.raises(Refusal) as e:
        _edl.check_beats(bad, edl, VOCAB)
    assert e.value.code == "forbidden_character"
    blank = with_text(5)
    next(x for x in blank["overlays"] if x["id"] == key["id"])["params"]["text"] = "   "
    with pytest.raises(Refusal) as e:
        _edl.check_beats(blank, edl, VOCAB)
    assert e.value.code == "empty_text"


def test_the_callers_that_pass_no_ceiling_keep_the_refusal_at_the_max():
    spec = VOCAB["presets"]["keyword"]["params"]["text"]
    with pytest.raises(Refusal) as e:
        __import__("_vocab").check_params(VOCAB, "keyword", {"text": "a" * (spec["max"] + 1)})
    assert e.value.code == "text_too_long"


def test_a_punch_with_frames_left_is_drawn_and_one_with_none_is_dropped():
    edl, beats = make()
    word = edl["words"][2]["index"]
    short = dict(beats, punches=[{"beat": 1, "word_from": word, "word_to": word, "score": 0.9}])
    advice = []
    rows, dropped = _edl.resolve_punches(edl, short, DATA, advice)
    assert rows or dropped
    for r in rows:
        assert r["end_frame"] > r["start_frame"]
    assert all(d["reason"] in ("punch_short", "punch_capped") for d in dropped)
    for a in advice:
        assert a["code"] == "punch_short" and a["value"] < _edl.PUNCH_SHORT_SECONDS and a["default"] == _edl.PUNCH_SHORT_SECONDS


def test_resolve_timeline_has_no_advice_key_inside_the_old_bounds():
    edl, beats = make()
    assert "advice" not in _edl.resolve_timeline(edl, beats, VOCAB, DATA)


# ---------------------------------------------------------------- T9: layout fallbacks

FACE_LOW = {"x": 240, "y": 900, "w": 600, "h": 560}
FACE_TALL = {"x": 240, "y": 200, "w": 600, "h": 1300}      # leaves no stretch of 120 rows clear for a caption band


def asset_row():
    return {"s1": {"width": 1200, "height": 675}}


def test_a_pip_with_too_little_room_is_drawn_over_the_face_with_advice():
    tl = {"beats": [{"id": "b1", "preset": "pip", "params": {"asset": "s1"}, "start_frame": 30, "end_frame": 90, "face": dict(FACE_LOW)}],
          "captions": [], "dropped": []}
    advice = []
    assert _layout.pip_cards(DATA, tl, asset_row(), advice=advice) == []
    card = tl["beats"][0]["card"]
    assert tl["dropped"] == [] and card["h"] <= DATA["pip"]["card_min_height"] and card["y"] + card["h"] == DATA["zones"]["caption_bottom"]
    assert advice[0]["code"] == "pip_card_over_face" and advice[0]["default"] == DATA["pip"]["card_min_height"] and advice[0]["ids"] == ["b1"]
    easy = {"beats": [{"id": "b1", "preset": "pip", "params": {"asset": "s1"}, "start_frame": 30, "end_frame": 90, "face": {"x": 240, "y": 300, "w": 600, "h": 400}}],
            "captions": [], "dropped": []}
    quiet = []
    _layout.pip_cards(DATA, easy, asset_row(), advice=quiet)
    assert quiet == [] and "dropped_reasons" in easy and easy["dropped_reasons"] == []


@pytest.mark.parametrize("side", ["top", "bottom", "left", "right"])
def test_a_split_with_no_free_band_is_drawn_with_the_fallback_band_and_advice(side):
    tl = {"beats": [{"id": "b1", "preset": "split", "params": {"asset": "s1", "side": side}, "start_frame": 30, "end_frame": 90, "face": dict(FACE_TALL)}],
          "captions": [{"start_frame": 40, "end_frame": 60, "face": dict(FACE_TALL)}], "dropped": []}
    advice = []
    assert _layout.split_layouts(DATA, tl, advice=advice) == []
    geom = tl["beats"][0]["split"]
    z = DATA["zones"]
    assert tl["dropped"] == [] and geom["band"] is not None
    if side in ("top", "bottom"):
        assert geom["band"] == [z["caption_bottom"] - z["caption_min_height"], z["caption_bottom"]]
    else:
        assert geom["band"][0] == z["caption_bottom"] - z["caption_min_height"] and geom["band"][1] - geom["band"][0] <= DATA["split"]["bar_height"]
        assert geom["bar"] == geom["band"]
    assert advice[0]["code"] == "split_band_over_face" and advice[0]["default"] == z["caption_min_height"] and advice[0]["value"] < z["caption_min_height"]


def test_the_storyboard_way_keeps_a_split_with_no_band_as_it_was():
    tl = {"beats": [{"id": "b1", "preset": "split", "params": {"asset": "s1", "side": "bottom"}, "start_frame": 30, "end_frame": 90, "face": dict(FACE_TALL)}],
          "captions": [], "dropped": []}
    advice = []
    _layout.split_layouts(DATA, tl, drop=False, advice=advice)
    assert tl["beats"][0]["split"]["band"] is None and advice == []


# ---------------------------------------------------------------- the schema

def row(**kw):
    return dict({"code": "punch_short", "value": 0.3, "default": 0.4, "count": 1}, **kw)


@pytest.mark.parametrize("verb", ["base", "check", "render"])
def test_the_three_result_schemas_take_24_advice_rows_and_refuse_25(verb):
    schema = _docker.RESULT_SCHEMAS[verb]
    keys = schema[1]
    assert "advice" in keys
    rows = [row(code=c) for c in list(A.CODES)] + [row(code="punch_short") for _ in range(8)]
    ok = _docker.sanitise(rows[:24], keys["advice"])
    assert len(ok) == 24
    with pytest.raises(Refusal):
        _docker.sanitise(rows[:16] + [row()] * 9, keys["advice"])


def test_the_advice_schema_refuses_a_bad_code_a_non_finite_number_and_13_ids():
    adv = _docker.ADVICE
    for bad in (row(code="made_up"), row(value=float("inf")), row(value="1"), row(ids=["b%d" % k for k in range(13)])):
        with pytest.raises(Refusal):
            _docker.sanitise([bad], adv)
    assert _docker.sanitise([row(ids=["b1", "b2"])], adv) == [row(ids=["b1", "b2"])]


def test_effects_dropped_takes_297_rows_in_render_and_refuses_298():
    schema = _docker.RESULT_SCHEMAS["render"][1]["effects_dropped"]
    rows = [{"id": "e1", "reason": "punch_short"}] * 297
    assert len(_docker.sanitise(rows, schema)) == 297
    with pytest.raises(Refusal):
        _docker.sanitise(rows + [rows[0]], schema)


def test_the_schema_description_names_the_default():
    text = open(K.RENDERER / "edl.schema.json").read()
    assert "at most 99" in text


# ---------------------------------------------------------------- the push-in default (M5)

def test_the_push_in_minimum_is_a_preset_default_with_the_same_value_and_the_same_zoom_levels():
    import _media
    assert DATA["zoom"]["push_min_seconds"] == 5.0 and _media.push_min_seconds() == 5.0
    zoom = {"mode": "none", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}
    assert _media.zoom_levels(zoom, 0, 149, 30) == (1.0, 1.0)             # 4.97 s: no push
    assert _media.zoom_levels(zoom, 0, 150, 30) == (1.0, 1.02)            # 5 s: the slow push-in, as before
    assert _media.zoom_levels(dict(zoom, push_min_seconds=2.0), 0, 90, 30) == (1.0, 1.02)
