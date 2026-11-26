"""The effects of V9a-3: the script's punches and the review's punch, flash, dip, mono and tint. How they are timed (`_edl.resolve_timeline`, whole
frames), how the ffmpeg engine's graph draws them (`_media`), (the HyperFrames page's and the face check's tests went with that engine, PF-b).
Offline: the edit list is a synthetic one made here; the tests that run ffmpeg uses the host's own on a synthetic test pattern and skips when there is none. Every name is fictional."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import subprocess

import pytest

import renderer_kit as K
import _edl
import _inner
import _media
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
FPS = 30
KEPT = [[0, 150], [200, 350], [400, 520]]          # output frames 0-149, 150-299 and 300-419
ANCHOR = (540.0, 760.0)
needs_media = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)


def synthetic_edl(kept=KEPT, zoom=None) -> dict:
    """An edit list with 28 words, one every half second (word i is spoken from 0.5 i + 0.1 to 0.5 i + 0.4), over three kept ranges."""
    frames = sum(b - a for a, b in kept)
    words = [{"index": i, "text": "word%d" % i, "start": round(0.5 * i + 0.1, 3), "end": round(0.5 * i + 0.4, 3)} for i in range(28)]
    colors = dict(DATA["theme"]["colors"])
    return {"schema_version": 2, "fps": FPS, "size": [1080, 1920], "kept": [list(r) for r in kept], "out_frames": frames, "words": words,
            "captions": {"position": "bottom", "chunks": [[i, i + 3] for i in range(0, 28, 4)]}, "theme": {"colors": colors, "fonts": {}},
            "face_box": dict(DATA["face_box_default"]), "source": {"has_audio": True},
            "zoom": zoom or {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}}


def beats_of(punches=(), effects=()) -> dict:
    doc = {"schema_version": 1, "threshold": 0.6, "overlays": [], "layouts": [], "slots": [], "report": [], "unmatched": [], "fallbacks": []}
    if punches:
        doc["punches"] = list(punches)
    if effects:
        doc["effects"] = list(effects)
    return doc


def punch(beat, first, last):
    return {"beat": beat, "word_from": first, "word_to": last, "score": 1.0}


def effect(ident, kind, first, last):
    return {"id": ident, "kind": kind, "word_from": first, "word_to": last}


def resolve(edl, beats, data=DATA):
    return _edl.resolve_timeline(edl, beats, VOCAB, data)


def refused(fn, *args):
    with pytest.raises(Refusal) as caught:
        fn(*args)
    return caught.value


# ---------------------------------------------------------------- no effect, no byte changes (golden)

def test_no_punch_keeps_the_zoom_filter_bytes():
    assert _media.zoom_filter(1.0, 1.0, 150, ANCHOR, 1080, 1920, 30) == "scale=1080:1920:flags=lanczos+accurate_rnd+bitexact"
    assert _media.zoom_filter(1.1, 1.1, 100, ANCHOR, 1080, 1920, 30) == \
        "zoompan=z='1.10000':x='1080.00*(1-1/zoom)':y='1520.00*(1-1/zoom)':d=1:s=1080x1920:fps=30"
    assert _media.zoom_filter(1.0, 1.02, 150, ANCHOR, 1080, 1920, 30) == \
        "zoompan=z='1.00000+0.000134*on':x='1080.00*(1-1/zoom)':y='1520.00*(1-1/zoom)':d=1:s=1080x1920:fps=30"
    assert _media.zoom_filter_linear(1.0, 1.0, 150, ANCHOR, 1080, 1920) == "scale=1080:1920:flags=lanczos+accurate_rnd+bitexact"
    linear = _media.zoom_filter_linear(1.1, 1.122, 150, ANCHOR, 1080, 1920)
    assert linear.startswith("perspective=x0='540.00*(1-1/(1.10000+0.000148*on))':y0='760.00*(1-1/(1.10000+0.000148*on))':x1=")
    assert "between" not in linear and _media.zoom_filter_linear(1.1, 1.122, 150, ANCHOR, 1080, 1920, ()) == linear
    assert _media.zoom_filter(1.1, 1.1, 100, ANCHOR, 1080, 1920, 30, 2, ()) == _media.zoom_filter(1.1, 1.1, 100, ANCHOR, 1080, 1920, 30)


PLAN = {"fps": 30, "size": [1080, 1920], "kept": KEPT, "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}, "fade": 0.015,
        "has_audio": True, "anchor": ANCHOR, "src_matrix": "bt709"}
GOLDEN_COMPOSE = "ef3d376504fe70ff3b87b80642ae8a445b7ad8a85994d39029a90f7f3cb81c64"      # the base graph of PLAN as it was before V9a-3
GOLDEN_REFERENCE = "cb2b4404ded72f45630029b94a29addbb0eb224768f9fa1c14d0018cfd0c7d87"    # the reference's graph of the last range (first_index 2), bilinear


def digest(graph) -> str:
    return hashlib.sha256("\n".join(graph).encode()).hexdigest()


def reference(plan, **more):
    return _media.base_graph(dict(plan, has_audio=False), source="[1:v:0]", prepare="fps=30:start_time=0,format=yuv420p", base=1, audio=False,
                             zoom_linear=True, first_index=2, **more)


def test_no_effect_keeps_the_base_graph_bytes():
    assert digest(_media.base_graph(PLAN)) == GOLDEN_COMPOSE
    assert digest(reference(PLAN)) == GOLDEN_REFERENCE
    assert digest(_media.base_graph(dict(PLAN, effects={}))) == GOLDEN_COMPOSE
    assert digest(_media.base_graph(dict(PLAN, effects={7: {"punches": [(1, 9, 1.2)], "grades": []}}))) == GOLDEN_COMPOSE      # a range the plan does not have
    assert _media.grade_filters([]) == []


def test_no_effect_keeps_the_timeline_empty_of_effects(tmp_path):
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of())
    assert timeline["punches"] == [] and timeline["grades"] == [] and timeline["effects_dropped"] == [] and _edl.range_effects(edl, timeline) == {}


# ---------------------------------------------------------------- punches

def test_a_punch_is_constant_and_capped_only_at_the_zoom_ceiling():
    edl = synthetic_edl()
    rows = resolve(edl, beats_of([punch(1, 12, 13)]))["punches"]       # words 12-13: 6.1 s to 7.4 s, in the second range (z 1.1 to 1.122)
    [row] = rows
    assert row["id"] == "p1" and row["range"] == 1
    base = 1.1 + 0.022 * (row["start_frame"] - 150) / 149.0
    assert row["zoom"] == pytest.approx(base * 1.12, abs=1e-5)
    wide = copy.deepcopy(DATA)
    wide["punch"]["factor"] = 1.6
    assert resolve(edl, beats_of([punch(1, 12, 13)]), wide)["punches"][0]["zoom"] == pytest.approx(base * 1.6, abs=1e-5)      # no taste cap: base x factor
    top = synthetic_edl(zoom={"mode": "alternate", "factor": _edl.ZOOM_MAX, "push_in": 0.0, "anchor_y": 0.25})
    timeline = resolve(top, beats_of([punch(1, 12, 13)]))                                              # a base at ZOOM_MAX cannot zoom in further
    assert timeline["punches"] == [] and timeline["effects_dropped"] == [{"id": "p1", "reason": "punch_capped"}]
    [(a, b, zp)] = _edl.range_effects(edl, resolve(edl, beats_of([punch(1, 12, 13)])))[1]["punches"]
    text = _media.zoom_filter(1.1, 1.122, 150, ANCHOR, 1080, 1920, 30, 2, [(a, b, zp)])
    assert "if(between(on,%d,%d),%.5f,1.10000+0.000148*on)" % (a, b - 1, zp) in text and text.startswith("zoompan=z='if(between")
    assert zp == row["zoom"]                      # one level over the whole span: the expression holds one number
    linear = _media.zoom_filter_linear(1.1, 1.122, 150, ANCHOR, 1080, 1920, [(a, b, zp)])
    assert "1/(if(between(on-1,%d,%d),%.5f,(1.10000+0.000148*on)))" % (a, b - 1, zp) in linear      # perspective counts `on` from 1
    plain = _media.zoom_filter(1.0, 1.0, 150, ANCHOR, 1080, 1920, 30, 2, [(5, 40, 1.12)])        # an unzoomed range with a punch needs a zoompan, not a scale
    assert plain.startswith("zoompan=z='if(between(on,5,39),1.12000,1.00000)'")


def test_a_punch_on_a_pushed_zoomed_range_is_drawn_at_base_times_the_factor():
    edl = synthetic_edl(zoom={"mode": "alternate", "factor": 1.25, "push_in": 0.03, "anchor_y": 0.25})
    timeline = resolve(edl, beats_of([punch(1, 12, 13)]))
    [row] = timeline["punches"]
    z0, z1 = _media.zoom_levels(edl["zoom"], 1, 150, FPS)
    base = z0 + (z1 - z0) * (row["start_frame"] - 150) / 149.0
    assert row["zoom"] == pytest.approx(base * 1.12, abs=1e-5) and row["zoom"] > 1.25 and timeline["effects_dropped"] == []


def test_a_punch_is_stretched_cut_and_never_crosses_a_range():
    edl = synthetic_edl()
    [short] = resolve(edl, beats_of([punch(1, 18, 18)]))["punches"]       # 9.1 s to 9.4 s (frames 273-282): stretched to 0.8 s
    assert (short["start_frame"], short["end_frame"]) == (273, 297)
    [long] = resolve(edl, beats_of([punch(1, 2, 12)]))["punches"]         # 1.1 s to 6.4 s: spans its words, cut at the range's end (frame 150)
    assert (long["start_frame"], long["end_frame"]) == (33, 150) and long["end_frame"] - long["start_frame"] > 90
    [four] = resolve(edl, beats_of([punch(1, 12, 20)]))["punches"]        # 6.1 s to 10.4 s of words (4 s and more): not cut at 3 s
    assert (four["start_frame"], four["end_frame"]) == (183, 300) and four["end_frame"] - four["start_frame"] > 90
    [crossing] = resolve(edl, beats_of([punch(1, 8, 11)]))["punches"]     # 4.1 s to 5.9 s: the range ends at frame 150
    assert (crossing["start_frame"], crossing["end_frame"]) == (123, 150) and crossing["range"] == 0
    [late] = resolve(edl, beats_of([punch(1, 19, 19)]))["punches"]        # 9.6 s: stretched to frame 312, cut at the range's end, 300
    assert late["end_frame"] == 300 and late["range"] == 1
    timeline = resolve(edl, beats_of([punch(1, 9, 9)]))                   # 4.6 s to 4.9 s: from frame 138 the range has 12 frames, exactly 0.4 s: kept
    assert [(p["start_frame"], p["end_frame"]) for p in timeline["punches"]] == [(138, 150)]
    timeline = resolve(edl, beats_of([punch(1, 10, 10)]))                 # 5.1 s: frame 153 to 177 in the second range
    assert [(p["start_frame"], p["range"]) for p in timeline["punches"]] == [(153, 1)]
    timeline = resolve(edl, beats_of([punch(1, 19, 19), punch(2, 18, 18)]))
    assert [(p["id"], p["start_frame"], p["end_frame"]) for p in timeline["punches"]] == [("p2", 273, 297), ("p1", 297, 300)]      # p1 starts where p2 ends and is left 3 frames: drawn, with advice
    assert timeline["effects_dropped"] == []
    assert timeline["advice"] == [{"code": "punch_short", "value": 0.1, "default": 0.4, "count": 1, "ids": ["p1"]}]


def test_two_punches_never_overlap():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of([punch(1, 2, 6), punch(2, 5, 8)]))
    first, second = timeline["punches"]
    assert first["end_frame"] <= second["start_frame"] and second["start_frame"] == first["end_frame"] and first["range"] == second["range"] == 0
    assert second["end_frame"] - second["start_frame"] >= 12
    by_range = {}
    for row in resolve(edl, beats_of([punch(1, 2, 6), punch(2, 5, 8), punch(3, 12, 14)], [effect("e1", "punch", 7, 9), effect("e2", "punch", 22, 23)]))["punches"]:
        by_range.setdefault(row["range"], []).append(row)
    for rows in by_range.values():
        assert all(a["end_frame"] <= b["start_frame"] for a, b in zip(rows, rows[1:]))
    review = resolve(edl, beats_of(effects=[effect("e1", "punch", 12, 13)]))["punches"]          # a review punch is a punch like the script's
    assert [p["id"] for p in review] == ["e1"]


def test_a_punch_row_without_a_preset_is_aligned(tmp_path):
    from test_renderer_script_v2 import v2_post
    post = v2_post().replace("emphasis: punch\n", "").replace("beat: 2\nrole: setup\n", "beat: 2\nrole: setup\nemphasis: punch\n")
    path = tmp_path / "post.md"
    path.write_text(post, encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", path, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 0, err
    beats = json.loads((tmp_path / "b.json").read_text())
    [row] = beats["punches"]
    assert row["beat"] == 2 and row["word_from"] < row["word_to"] and 0.6 <= row["score"] <= 1 and set(row) == {"beat", "word_from", "word_to", "score"}
    assert out["punches"] == 1 and beats["unmatched"] == [] and not any(e["beat"] == 2 for e in beats["overlays"] + beats["layouts"])
    _edl.check_beats(beats, {"words": [{"index": i} for i in range(200)]}, VOCAB)


def test_a_punch_row_with_a_preset_and_one_that_matches_nothing(tmp_path):
    from test_renderer_script_v2 import v2_post
    both = v2_post()                                                      # beats 3 and 7 carry `emphasis: punch` and a preset
    path = tmp_path / "post.md"
    path.write_text(both, encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    rc, out, err = K.run_verb("align", "--post", path, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json")
    assert rc == 0, err
    beats = json.loads((tmp_path / "b.json").read_text())
    assert sorted(p["beat"] for p in beats["punches"]) == [3, 7]
    words = [{"index": i, "text": t, "start": i * 0.3, "end": i * 0.3 + 0.2} for i, t in enumerate("alpha bravo charlie delta echo foxtrot".split())]
    rows = [{"beat": 1, "line": "quarterly revenue forecast", "emphasis": "punch", "preset": None},
            {"beat": 2, "line": "alpha bravo charlie", "emphasis": "punch", "preset": None},
            {"beat": 3, "line": "delta echo", "emphasis": None, "preset": None}]
    punches, missed = _inner.punch_rows(rows, [], [], words, 0.6)
    assert missed == [1] and [(p["beat"], p["word_from"], p["word_to"]) for p in punches] == [(2, 0, 2)]
    assert _inner.punch_rows(rows[2:], [], [], words, 0.6) == ([], [])


def test_the_checks_of_the_two_new_keys():      # T2
    edl = synthetic_edl()
    ok = beats_of([punch(1, 2, 3)], [effect("e1", "flash", 2, 2), effect("e2", "mono", 5, 6)])
    assert _edl.check_beats(ok, edl, VOCAB)["texts"] == []
    for bad, code in ((beats_of([punch(1, 2, 3), punch(1, 5, 6)]), "bad_beat"), (beats_of([punch(1, 30, 31)]), "bad_word_range"),
                      (beats_of([dict(punch(1, 2, 3), start=1.5)]), "unknown_key"), (beats_of([dict(punch(1, 2, 3), score=2)]), "bad_score"),
                      (beats_of(effects=[effect("e1", "spin", 2, 3)]), "bad_effect"), (beats_of(effects=[effect("e0", "flash", 2, 3)]), "bad_id"),
                      (beats_of(effects=[effect("e01", "flash", 2, 3)]), "bad_id"), (beats_of(effects=[effect("e100", "flash", 2, 3)]), "bad_id"),
                      (beats_of(effects=[effect("e1", "flash", 3, 2)]), "bad_word_range"), (beats_of(effects=[dict(effect("e1", "mono", 2, 3), seconds=2)]), "unknown_key"),
                      (beats_of(effects=[effect("e1", "flash", 2, 5), effect("e2", "tint", 5, 7)]), "effect_overlap"),
                      (beats_of(effects=[effect("e1", "dip", 2, 5), effect("e2", "flash", 5, 7)]), "effect_overlap"),
                      ):
        assert refused(_edl.check_beats, bad, edl, VOCAB).code == code, code
    assert refused(_edl.check_beats, dict(beats_of(), punches={}), edl, VOCAB).code == "not_list"
    many = beats_of([punch(k, k, k) for k in range(1, 14)])
    assert _edl.check_beats(many, edl, VOCAB)["advice"] == [{"code": "punches_over_default", "value": 13, "default": VOCAB["limits"]["beats_max"], "count": 1}]
    assert refused(_edl.check_beats, beats_of([punch(k, k % 28, k % 28) for k in range(1, 101)]), edl, VOCAB).code == "too_many_punches"
    assert _edl.check_beats(beats_of(effects=[effect("e%d" % k, "punch", k % 28, k % 28) for k in range(1, 100)]), edl, VOCAB)      # 99 review effects pass
    over = beats_of(effects=[effect("e%d" % k, "punch", 0, 0) for k in range(1, 100)] + [effect("e100", "punch", 0, 0)])
    assert refused(_edl.check_beats, over, edl, VOCAB).code == "too_many_effects"                                                 # the 100th is over the ceiling
    for kinds in (("mono", "tint"), ("mono", "mono"), ("mono", "flash"), ("dip", "mono")):                                       # mono is a filter: it may share words
        assert _edl.check_beats(beats_of(effects=[effect("e1", kinds[0], 2, 5), effect("e2", kinds[1], 4, 7)]), edl, VOCAB)
    assert _edl.check_beats(beats_of(effects=[effect("e1", "flash", 1, 1), effect("e2", "dip", 4, 4), effect("e3", "flash", 8, 8)]), edl, VOCAB)      # no flash count


# ---------------------------------------------------------------- grades

def test_grades_are_resolved_to_whole_frames_inside_their_range():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of(effects=[effect("e1", "flash", 3, 3), effect("e2", "dip", 9, 9), effect("e3", "mono", 12, 14), effect("e4", "tint", 22, 25)]))
    by_id = {g["id"]: g for g in timeline["grades"]}
    assert (by_id["e1"]["start_frame"], by_id["e1"]["end_frame"], by_id["e1"]["alphas"]) == (48, 52, [0.85, 0.6, 0.35, 0.1])      # 1.6 s: four frames
    assert (by_id["e2"]["start_frame"], by_id["e2"]["end_frame"]) == (138, 144) and by_id["e2"]["alphas"] == DATA["effects"]["dip_alphas"]
    assert (by_id["e3"]["start_frame"], by_id["e3"]["end_frame"]) == (183, 222)                                               # 6.1 s to 7.4 s: 1.3 s
    assert by_id["e4"]["kind"] == "tint" and by_id["e4"]["alpha"] == 0.18 and by_id["e4"]["color"] == DATA["theme"]["colors"]["accent"]
    assert (by_id["e4"]["start_frame"], by_id["e4"]["end_frame"]) == (333, 387)                                               # words 22-25: 11.1 s to 12.9 s
    for g in timeline["grades"]:
        assert isinstance(g["start_frame"], int) and isinstance(g["end_frame"], int) and g["start_frame"] < g["end_frame"]
        first, last = [r for r in _edl.range_table(edl)][g["range"]]
        assert first <= g["start_frame"] and g["end_frame"] <= last


def test_switches_are_whole_frames():
    edl = synthetic_edl()
    beats = beats_of([punch(1, 2, 3)], [effect("e1", "flash", 12, 12), effect("e2", "mono", 20, 21), effect("e3", "tint", 4, 5)])
    timeline = resolve(edl, beats)
    for row in timeline["punches"] + timeline["grades"]:
        assert isinstance(row["start_frame"], int) and isinstance(row["end_frame"], int)
    words = {w["index"]: w for w in edl["words"]}
    assert timeline["punches"][0]["start_frame"] == int(round(words[2]["start"] * FPS))
    flash = [g for g in timeline["grades"] if g["kind"] == "flash"][0]
    assert flash["start_frame"] == int(round(words[12]["start"] * FPS))
    table = _edl.range_effects(edl, timeline)
    graph = "\n".join(_media.base_graph(dict(PLAN, effects=table)))
    for ramp in range(4):
        assert re.search(r"lutyuv=y='val\*\(1-[0-9.]+\)\+235\.00\*[0-9.]+':u='[^']*':v='[^']*':enable='eq\(n,%d\)'" % (flash["start_frame"] - 150 + ramp), graph)
    for number in re.findall(r"between\(n,(\d+),(\d+)\)|eq\(n,(\d+)\)|between\(on,(\d+),(\d+)\)", graph):
        assert all(x == "" or x.isdigit() for x in number)


def test_a_grade_in_the_graph_is_in_its_ranges_own_frame_index_and_after_the_zoom():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of(effects=[effect("e1", "flash", 12, 12), effect("e2", "mono", 20, 20), effect("e3", "tint", 2, 2)]))
    graph = _media.base_graph(dict(PLAN, effects=_edl.range_effects(edl, timeline)))
    ranges = [line for line in graph if "trim=start_frame" in line]
    assert "lutyuv" in ranges[0] and "*0.180" in ranges[0] and "colorchannelmixer" not in ranges[0]
    assert "lutyuv=y='val*(1-0.850)+235.00*0.850'" in ranges[1] and "enable='eq(n,33)'" in ranges[1]
    assert "colorchannelmixer" in ranges[2] and "lutyuv" not in ranges[2] and ranges[2].index(_media.TO_RGB) < ranges[2].index("colorchannelmixer") < ranges[2].index(_media.FROM_RGB)
    for k, line in enumerate(ranges):
        if "lutyuv" in line or "colorchannelmixer" in line:
            assert line.index("lutyuv" if "lutyuv" in line else "colorchannelmixer") > line.index("setsar=1")      # a grade comes after the zoom
        assert line.endswith("format=yuv420p[v%d]" % k)


def test_grades_have_no_length_or_count_cap():
    edl = synthetic_edl()
    wide = copy.deepcopy(DATA)
    wide["effects"].update(flash_alphas=[0.9] * 9, dip_alphas=[0.5] * 12, tint_alpha=0.5, grade_min_seconds=0.5)
    timeline = resolve(edl, beats_of(effects=[effect("e1", "flash", 2, 2), effect("e2", "dip", 14, 14)]), wide)
    lengths = {g["kind"]: g["end_frame"] - g["start_frame"] for g in timeline["grades"]}
    assert lengths == {"flash": 9, "dip": 12}                                                 # one frame per alpha: no 4 and 6 frame cap
    cut = resolve(edl, beats_of(effects=[effect("e1", "dip", 9, 9)]), wide)["grades"][0]      # frame 138: the range ends at 150, 12 frames fit
    assert cut["end_frame"] == 150
    long = resolve(edl, beats_of(effects=[effect("e1", "mono", 0, 9)]))["grades"][0]           # 0.1 s to 4.9 s, 4.8 s of words
    assert long["end_frame"] - long["start_frame"] > int(4.0 * FPS) and long["end_frame"] <= 150
    short = resolve(edl, beats_of(effects=[effect("e1", "tint", 2, 2)]))["grades"][0]         # a word of 0.3 s: stretched to 0.5 s
    assert short["end_frame"] - short["start_frame"] == int(round(DATA["effects"]["grade_min_seconds"] * FPS))
    edge = resolve(edl, beats_of(effects=[effect("e1", "flash", 8, 8)]))["grades"][0]         # 4.1 s: frame 123, four frames, inside the first range
    assert edge["end_frame"] - edge["start_frame"] == 4
    closing = resolve(edl, beats_of(effects=[effect("e1", "dip", 10, 10)]))["grades"][0]
    assert closing["start_frame"] == 153
    strong = copy.deepcopy(DATA)
    strong["effects"].update(flash_alphas=[1.2, -0.1, 0.5], tint_alpha=0.5)
    graded = resolve(edl, beats_of(effects=[effect("e1", "flash", 2, 2), effect("e2", "tint", 14, 15)]), strong)["grades"]
    by = {g["kind"]: g for g in graded}
    assert by["flash"]["alphas"] == [1.0, 0.0, 0.5] and by["tint"]["alpha"] == 0.5          # clamped to 0-1, nothing else
    assert _edl.check_beats(beats_of(effects=[effect("e1", "flash", 1, 1), effect("e2", "dip", 3, 3), effect("e3", "flash", 5, 5)]), edl, VOCAB)


def test_a_grade_that_would_share_the_colour_layer_with_the_one_before_is_dropped_and_mono_is_not():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of(effects=[effect("e1", "tint", 2, 2), effect("e2", "flash", 3, 3), effect("e3", "mono", 3, 3)]))
    # the flash starts at frame 48; the tint (0.5 s from frame 33) ends at 48: they do not share a frame. A tint over words 2-3 would.
    assert {g["id"] for g in timeline["grades"]} == {"e1", "e2", "e3"}
    tight = resolve(edl, beats_of(effects=[effect("e1", "tint", 2, 2), effect("e2", "flash", 2, 2)]))
    assert [g["id"] for g in tight["grades"]] == ["e2"] and tight["effects_dropped"] == [{"id": "e1", "reason": "grade_overlap"}]      # the one that starts first (then ends first) stays


def test_the_mono_matrix_is_the_css_matrix():
    # the W3C filter-effects matrix of grayscale(amount) at amount 1 (rows R, G, B; columns R, G, B)
    a = 1.0
    css = [[0.2126 + 0.7874 * (1 - a), 0.7152 - 0.7152 * (1 - a), 0.0722 - 0.0722 * (1 - a)],
           [0.2126 - 0.2126 * (1 - a), 0.7152 + 0.2848 * (1 - a), 0.0722 - 0.0722 * (1 - a)],
           [0.2126 - 0.2126 * (1 - a), 0.7152 - 0.7152 * (1 - a), 0.0722 + 0.9278 * (1 - a)]]
    given = dict(item.split("=") for item in _media.MONO_MATRIX.split(":"))
    mixer = [[float(given[row + col]) for col in "rgb"] for row in "rgb"]
    assert [x for r in mixer for x in r] == pytest.approx([x for r in css for x in r], abs=1e-9) and all(abs(sum(r) - 1.0) < 1e-9 for r in mixer)
    assert "colorchannelmixer=" + _media.MONO_MATRIX in _media.grade_filters([{"kind": "mono", "a": 3, "b": 9, "alphas": None, "alpha": None, "color": None}])[1]


# ---------------------------------------------------------------- the whole composition, with the host's ffmpeg

@needs_media
def test_the_graph_runs_on_a_synthetic_picture_and_the_mono_frames_have_no_colour(tmp_path):
    w, h = 270, 480
    plan = {"fps": 30, "size": [w, h], "kept": [[0, 24], [30, 54]], "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.0, "anchor_y": 0.25},
            "fade": 0.0, "has_audio": False, "anchor": (135.0, 190.0)}
    effects = {0: {"first": 0, "frames": 24, "punches": [(4, 12, 1.2)], "grades": [{"kind": "flash", "a": 2, "b": 4, "alphas": [0.85, 0.6], "alpha": None, "color": None}]},
               1: {"first": 24, "frames": 24, "punches": [], "grades": [{"kind": "mono", "a": 6, "b": 16, "alphas": None, "alpha": None, "color": None}]}}
    sizes = {}
    for label, linear, fx in (("plain-zoompan", False, None), ("fx-zoompan", False, effects), ("fx-linear", True, effects)):
        graph = _media.base_graph(dict(plan, effects=fx or {}), source="[0:v:0]", prepare="format=yuv420p", base=1, audio=False, zoom_linear=linear)
        done = subprocess.run([K.FFMPEG, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=%dx%d:rate=30:duration=2" % (w, h), "-filter_complex", ";".join(graph),
                               "-map", "[cv]", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"], capture_output=True, timeout=300)
        assert done.returncode == 0, done.stderr.decode()[-400:]
        size = w * h * 3 // 2
        assert len(done.stdout) == 48 * size, label
        sizes[label] = done.stdout
    frames = sizes["fx-zoompan"]
    size = w * h * 3 // 2

    def chroma_spread(n):
        plane = frames[n * size + w * h:(n + 1) * size]
        return max(abs(b - 128) for b in plane)

    assert all(chroma_spread(24 + n) <= 3 for n in range(6, 16))                 # the mono frames: no chroma
    assert max(chroma_spread(24 + n) for n in (0, 3, 20)) > 20                  # the frames next to them keep their colour
    plain = sizes["plain-zoompan"]
    assert frames[0:size] == plain[0:size] and frames[10 * size:11 * size] != plain[10 * size:11 * size]       # frame 0 is untouched; a punched frame is not


# ---------------------------------------------------------------- review of PR 807: the frames both drawings switch on

def frames_of(raw: bytes, w: int, h: int) -> list:
    size = w * h * 3 // 2
    return [raw[i * size:(i + 1) * size] for i in range(len(raw) // size)]


def ffmpeg_frames(vf: str, w=270, h=480, seconds=2) -> list:
    done = subprocess.run([K.FFMPEG, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=%dx%d:rate=30:duration=%d" % (w, h, seconds), "-vf", vf,
                           "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"], capture_output=True, timeout=300)
    assert done.returncode == 0, done.stderr.decode()[-300:]
    return frames_of(done.stdout, w, h)


@needs_media
@pytest.mark.parametrize("where", ["start", "middle", "end"])
@pytest.mark.parametrize("linear", [True, False])
def test_both_drawings_of_a_punch_switch_on_the_frames_the_page_switches_on(where, linear):
    """The page punches frames a <= n < b (the rows' own rule). The ffmpeg filters must change exactly those frames: `perspective` counts `on` from 1 and
    `zoompan` from 0, and a punch drawn one frame early by the reference made the face check fail at the span's first and last frame (live, 2026-11-10)."""
    frames = 60
    a, b = {"start": (0, 9), "middle": (20, 29), "end": (51, 60)}[where]
    anchor = (135.0, 190.0)
    plain = ffmpeg_frames("format=yuv420p")[:frames]
    if linear:
        vf = _media.zoom_filter_linear(1.0, 1.0, frames, anchor, 270, 480, [(a, b, 1.3)])
    else:
        vf = _media.zoom_filter(1.0, 1.0, frames, anchor, 270, 480, 30, 1, [(a, b, 1.3)])
    punched = ffmpeg_frames("format=yuv420p," + vf)[:frames]
    changed = [n for n in range(frames) if punched[n] != plain[n]]
    assert changed == list(range(a, b))


@needs_media
def test_mono_under_a_tint_leaves_the_tint_coloured_as_the_page_does():
    """The page's mono is a filter on the video and its tint a layer above it, so a tinted frame that is also grey keeps the tint's colour; the graph
    must grey the picture first and tint after (it greyed the tint before the review)."""
    w, h = 270, 480
    rows = {"first": 0, "frames": 60, "punches": [], "grades": [{"kind": "mono", "a": 16, "b": 32, "alphas": None, "alpha": None, "color": None},
                                                                 {"kind": "tint", "a": 24, "b": 40, "alphas": None, "alpha": 0.18, "color": "#FFC93C"}]}
    line = [f for f in _media.grade_filters(rows["grades"])]
    assert line.index(_media.TO_RGB) < line.index(next(x for x in line if x.startswith("colorchannelmixer"))) < line.index(_media.FROM_RGB) < line.index(next(x for x in line if x.startswith("lutyuv")))
    frames = ffmpeg_frames("format=yuv420p," + ",".join(line))[:60]

    def spread(n):
        return max(abs(v - 128) for v in frames[n][w * h:])

    assert all(spread(n) <= 3 for n in range(16, 24))             # grey only
    assert all(spread(n) > 8 for n in range(24, 32))             # grey and tinted: the tint is coloured
    assert all(spread(n) > 8 for n in range(32, 40)) and spread(10) > 20


def test_a_punch_the_renderer_leaves_out_is_reported(tmp_path):
    edl = synthetic_edl()
    beats = beats_of([punch(1, 2, 8)], [effect("e1", "punch", 4, 4)])
    timeline = resolve(edl, beats)
    assert timeline["effects_dropped"] == [{"id": "e1", "reason": "punch_short"}]


def test_the_alphas_are_clamped_to_zero_and_one_and_not_to_the_specs_old_values():
    edl = synthetic_edl()
    wide = copy.deepcopy(DATA)
    wide["effects"].update(flash_alphas=[1.0, 7, -2, 0.5], dip_alphas=[1.0] * 6, tint_alpha=0.9)
    timeline = resolve(edl, beats_of(effects=[effect("e1", "flash", 2, 2), effect("e2", "dip", 9, 9), effect("e3", "tint", 14, 15)]), wide)
    by = {g["kind"]: g for g in timeline["grades"]}
    assert by["flash"]["alphas"] == [1.0, 1.0, 0.0, 0.5] and set(by["dip"]["alphas"]) == {1.0} and by["tint"]["alpha"] == 0.9


@needs_media
@pytest.mark.parametrize("alpha", [0.85, 0.35, 0.1])
@pytest.mark.parametrize("kind", ["flash", "dip"])
def test_a_flash_and_a_dip_are_the_rgb_alpha_blend_on_saturated_bars(kind, alpha):
    """On SMPTE bars (saturated chroma) the graph's blend equals the ideal, an sRGB alpha blend of white or black done in RGB: every plane within 4 levels inside a bar (the ideal's own RGB rounding and clipping; drawbox is off by 10 to 40).
    `drawbox` on yuv420p moves a bar's chroma about twice as far towards grey (U 147 to 130 where the blend gives 141 at alpha .35) and failed this."""
    w, h = 320, 64
    src = ("smptehdbars=size=%dx%d:rate=30:duration=0.2,format=yuv420p,setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv" % (w, h))
    color = "ffffff" if kind == "flash" else "000000"

    def run(vf):
        done = subprocess.run([K.FFMPEG, "-v", "error", "-nostdin", "-f", "lavfi", "-i", src, "-vf", vf, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"],
                              capture_output=True, timeout=120)
        assert done.returncode == 0, done.stderr.decode()[-300:]
        return done.stdout

    got = run(",".join(_media.grade_filters([{"kind": kind, "a": 0, "b": 1, "alphas": [alpha], "alpha": None, "color": None}])))
    flags = "accurate_rnd+full_chroma_int"
    want = run("scale=in_range=tv:in_color_matrix=bt709:out_range=pc:flags=%s,format=gbrp,drawbox=x=0:y=0:w=iw:h=ih:t=fill:color=0x%s@%.3f,"
               "scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=%s,format=yuv420p" % (flags, color, alpha, flags))
    assert len(got) == len(want) == w * h * 3 // 2
    plain = run("null")
    trip = run("scale=in_range=tv:in_color_matrix=bt709:out_range=pc:flags=%s,format=gbrp,scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=%s,format=yuv420p" % (flags, flags))
    planes = ((0, w, h), (w * h, w // 2, h // 2), (w * h + w * h // 4, w // 2, h // 2))
    checked = 0
    for start, pw, ph in planes:
        for y in range(ph):
            for x in range(3, pw - 3):
                row = plain[start + y * pw + x - 3:start + y * pw + x + 4]
                if len(set(row)) == 1 and abs(trip[start + y * pw + x] - plain[start + y * pw + x]) <= 1:      # inside a bar, and a colour RGB holds (the ideal clips what it cannot): the ideal's own chroma upsampling blurs only the pixels at a bar's edge
                    checked += 1
                    assert abs(got[start + y * pw + x] - want[start + y * pw + x]) <= 4, (start, x, y)
    assert checked > w * h // 2


def test_the_blend_of_a_colour_is_the_affine_blend_of_its_bt709_limited_planes():
    assert [round(v) for v in _media.yuv_limited_bt709("#FFFFFF")] == [235, 128, 128] and [round(v) for v in _media.yuv_limited_bt709("#000000")] == [16, 128, 128]
    text = _media.blend_filter("#FFFFFF", 0.35, "eq(n,4)")
    assert text == "lutyuv=y='val*(1-0.350)+235.00*0.350':u='val*(1-0.350)+128.00*0.350':v='val*(1-0.350)+128.00*0.350':enable='eq(n,4)'"


# ---------------------------------------------------------------- video P0: the taste caps are gone, the validity bounds stay

def test_the_zoom_check_has_only_validity_bounds():      # T4
    zoom = {"mode": "alternate", "factor": 1.5, "push_in": 0.1, "anchor_y": 0.25}
    _edl.check_zoom(DATA, zoom)
    for patch in ({"factor": 0.99}, {"factor": 10.01}, {"push_in": -0.01}, {"factor": 5.0, "push_in": 1.01}, {"factor": float("nan")},
                  {"push_in": float("nan")}, {"factor": float("inf")}, {"factor": True}, {"push_in": False}):
        assert refused(_edl.check_zoom, DATA, dict(zoom, **patch)).code == "bad_zoom", patch
    _edl.check_zoom(DATA, dict(zoom, factor=10.0, push_in=0.0))
    _edl.check_zoom(DATA, dict(zoom, factor=5.0, push_in=1.0))
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "d" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    advice = []
    edl, _ = _edl.build_base(doc, analysis, DATA, {}, zoom_factor=1.5, push_in=0.1, advice=advice)
    assert edl["zoom"]["factor"] == 1.5          # pinned: no taste cap, and a face box with little room at that zoom is advice, not a refusal (video P0b)


def test_schema_and_code_agree_and_the_taste_caps_are_gone():      # T5
    schema = json.load(open(K.RENDERER / "edl.schema.json"))
    effects = schema["$defs"]["beats"]["properties"]["effects"] if "$defs" in schema else None
    if effects is None:
        effects = schema["properties"]["beats"]["properties"]["effects"]
    assert effects["maxItems"] == _edl.EFFECTS_MAX == 99
    assert effects["items"]["properties"]["id"]["pattern"] == "^" + _edl.EFFECT_ID.pattern + "$"
    for name in ("FLASHES_MAX", "GRADE_SECONDS_MAX", "FLASH_FRAMES_MAX", "DIP_FRAMES_MAX", "FLASH_ALPHA_MAX", "TINT_ALPHA_MAX"):
        assert not hasattr(_edl, name), name
    assert _edl.ZOOM_MAX == 10.0
    assert "factor_max" not in DATA["zoom"] and "push_in_max" not in DATA["zoom"]
    assert "max_seconds" not in DATA["punch"] and "grade_max_seconds" not in DATA["effects"]
    text = (K.RENDERER / "renderer-presets.json").read_text()
    for key in ("factor_max", "push_in_max", "grade_max_seconds"):
        assert key not in text
    assert _edl.EFFECT_ID.fullmatch("e99") and not _edl.EFFECT_ID.fullmatch("e100") and not _edl.EFFECT_ID.fullmatch("e01") and not _edl.EFFECT_ID.fullmatch("e0")


# T5b: the same rows and bytes inside the old bounds. The literals were produced once at the base commit 6ca49fc0 (before video P0).
T5B_EFFECTS = [effect("e1", "flash", 3, 3), effect("e2", "dip", 9, 9), effect("e3", "mono", 12, 17), effect("e4", "tint", 22, 23)]
T5B_PUNCHES = [
    {
        "end_frame": 87,
        "face": {
            "h": 631,
            "w": 676,
            "x": 202,
            "y": 602
        },
        "id": "p1",
        "range": 0,
        "start_frame": 33,
        "zoom": 1.12496
    }
]
T5B_GRADES = [
    {
        "alphas": [
            0.85,
            0.6,
            0.35,
            0.1
        ],
        "end_frame": 52,
        "id": "e1",
        "kind": "flash",
        "range": 0,
        "start_frame": 48
    },
    {
        "alphas": [
            0.3,
            0.6,
            0.85,
            0.85,
            0.6,
            0.3
        ],
        "end_frame": 144,
        "id": "e2",
        "kind": "dip",
        "range": 0,
        "start_frame": 138
    },
    {
        "end_frame": 267,
        "id": "e3",
        "kind": "mono",
        "range": 1,
        "start_frame": 183
    },
    {
        "alpha": 0.18,
        "color": "#FFC93C",
        "end_frame": 357,
        "id": "e4",
        "kind": "tint",
        "range": 2,
        "start_frame": 333
    }
]
T5B_GRAPH = [
    "[0:v:0]fps=30:start_time=0,scale=2160:3840:force_original_aspect_ratio=increase:in_color_matrix=bt709:out_color_matrix=bt709:out_range=tv:flags=lanczos+accurate_rnd+bitexact,crop=2160:3840,setsar=1,format=yuv420p[sv]",
    "[sv]split=3[s0][s1][s2]",
    "[s0]trim=start_frame=0:end_frame=150,setpts=PTS-STARTPTS,zoompan=z='if(between(on,33,86),1.12496,1.00000+0.000134*on)':x='1080.00*(1-1/zoom)':y='1520.00*(1-1/zoom)':d=1:s=1080x1920:fps=30,setsar=1,lutyuv=y='val*(1-0.850)+235.00*0.850':u='val*(1-0.850)+128.00*0.850':v='val*(1-0.850)+128.00*0.850':enable='eq(n,48)',lutyuv=y='val*(1-0.600)+235.00*0.600':u='val*(1-0.600)+128.00*0.600':v='val*(1-0.600)+128.00*0.600':enable='eq(n,49)',lutyuv=y='val*(1-0.350)+235.00*0.350':u='val*(1-0.350)+128.00*0.350':v='val*(1-0.350)+128.00*0.350':enable='eq(n,50)',lutyuv=y='val*(1-0.100)+235.00*0.100':u='val*(1-0.100)+128.00*0.100':v='val*(1-0.100)+128.00*0.100':enable='eq(n,51)',lutyuv=y='val*(1-0.300)+16.00*0.300':u='val*(1-0.300)+128.00*0.300':v='val*(1-0.300)+128.00*0.300':enable='eq(n,138)',lutyuv=y='val*(1-0.600)+16.00*0.600':u='val*(1-0.600)+128.00*0.600':v='val*(1-0.600)+128.00*0.600':enable='eq(n,139)',lutyuv=y='val*(1-0.850)+16.00*0.850':u='val*(1-0.850)+128.00*0.850':v='val*(1-0.850)+128.00*0.850':enable='eq(n,140)',lutyuv=y='val*(1-0.850)+16.00*0.850':u='val*(1-0.850)+128.00*0.850':v='val*(1-0.850)+128.00*0.850':enable='eq(n,141)',lutyuv=y='val*(1-0.600)+16.00*0.600':u='val*(1-0.600)+128.00*0.600':v='val*(1-0.600)+128.00*0.600':enable='eq(n,142)',lutyuv=y='val*(1-0.300)+16.00*0.300':u='val*(1-0.300)+128.00*0.300':v='val*(1-0.300)+128.00*0.300':enable='eq(n,143)',format=yuv420p[v0]",
    "[0:a:0]aresample=async=1:first_pts=0,atrim=start=0.000000:end=5.000000,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.0150,afade=t=out:st=4.985000:d=0.0150[a0]",
    "[s1]trim=start_frame=200:end_frame=350,setpts=PTS-STARTPTS,zoompan=z='1.10000+0.000148*on':x='1080.00*(1-1/zoom)':y='1520.00*(1-1/zoom)':d=1:s=1080x1920:fps=30,setsar=1,scale=in_range=tv:in_color_matrix=bt709:out_range=pc:flags=lanczos+accurate_rnd+bitexact,format=gbrp,colorchannelmixer=rr=.2126:rg=.7152:rb=.0722:gr=.2126:gg=.7152:gb=.0722:br=.2126:bg=.7152:bb=.0722:enable='between(n,33,116)',scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=lanczos+accurate_rnd+bitexact,format=yuv420p,format=yuv420p[v1]",
    "[0:a:0]aresample=async=1:first_pts=0,atrim=start=6.666667:end=11.666667,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.0150,afade=t=out:st=4.985000:d=0.0150[a1]",
    "[s2]trim=start_frame=400:end_frame=520,setpts=PTS-STARTPTS,scale=1080:1920:flags=lanczos+accurate_rnd+bitexact,setsar=1,lutyuv=y='val*(1-0.180)+189.74*0.180':u='val*(1-0.180)+60.64*0.180':v='val*(1-0.180)+157.40*0.180':enable='between(n,33,56)',format=yuv420p[v2]",
    "[0:a:0]aresample=async=1:first_pts=0,atrim=start=13.333333:end=17.333333,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.0150,afade=t=out:st=3.985000:d=0.0150[a2]",
    "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[cv][ca]",
    "[ca]aformat=sample_rates=48000:channel_layouts=stereo[aout]"
]


def test_an_edit_inside_the_old_bounds_keeps_its_rows_and_bytes():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of([punch(1, 2, 5)], T5B_EFFECTS))
    assert timeline["punches"] == T5B_PUNCHES and timeline["grades"] == T5B_GRADES and timeline["effects_dropped"] == []
    assert _media.base_graph(dict(PLAN, effects=_edl.range_effects(edl, timeline))) == T5B_GRAPH
