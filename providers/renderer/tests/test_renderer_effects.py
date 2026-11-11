"""The effects of V9a-3: the script's punches and the review's punch, flash, dip, mono and tint. How they are timed (`_edl.resolve_timeline`, whole
frames), how the ffmpeg engine's graph draws them (`_media`), how the HyperFrames page draws the same rows (`_hf_page`) and what the face check's
reference holds (`_hf_gate`). Offline: the edit list is a synthetic one made here, the page is read as text and one node script runs the page's own
drive code; the one test that runs ffmpeg uses the host's own on a synthetic test pattern and skips when there is none. Every name is fictional."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import subprocess

import pytest

import renderer_kit as K
import _edl
import _hf_gate
import _hf_page
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
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


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


def test_no_effect_keeps_the_page_and_the_timeline_empty_of_effects(tmp_path):
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of())
    assert timeline["punches"] == [] and timeline["grades"] == [] and timeline["effects_dropped"] == [] and _edl.range_effects(edl, timeline) == {}
    parts = _hf_page.build_parts(edl, fps=FPS)
    assert set(parts["vars"]) == {"duration", "fps", "zooms"} and not any(k.startswith("fx_") for k in parts)
    plain = _hf_page.render_page(parts, width=1080, height=1920, fps=FPS, background="#0B0F14")
    assert "PZ" not in plain and 'id="fx"' not in plain and "punched" not in plain
    assert _hf_page.render_page(_hf_page.build_parts(edl, fps=FPS, effects={}), width=1080, height=1920, fps=FPS, background="#0B0F14") == plain


# ---------------------------------------------------------------- punches

def test_a_punch_is_constant_and_capped():
    edl = synthetic_edl()
    rows = resolve(edl, beats_of([punch(1, 12, 13)]))["punches"]       # words 12-13: 6.1 s to 7.4 s, in the second range (z 1.1 to 1.122)
    [row] = rows
    assert row["id"] == "p1" and row["range"] == 1
    base = 1.1 + 0.022 * (row["start_frame"] - 150) / 149.0
    assert row["zoom"] == pytest.approx(base * 1.12, abs=1e-5) and row["zoom"] <= 1.25
    wide = copy.deepcopy(DATA)
    wide["punch"]["factor"] = 1.6
    assert resolve(edl, beats_of([punch(1, 12, 13)]), wide)["punches"][0]["zoom"] == 1.25            # capped at zoom.factor_max
    [(a, b, zp)] = _edl.range_effects(edl, resolve(edl, beats_of([punch(1, 12, 13)])))[1]["punches"]
    text = _media.zoom_filter(1.1, 1.122, 150, ANCHOR, 1080, 1920, 30, 2, [(a, b, zp)])
    assert "if(between(on,%d,%d),%.5f,1.10000+0.000148*on)" % (a, b - 1, zp) in text and text.startswith("zoompan=z='if(between")
    assert zp == row["zoom"]                      # one level over the whole span: the expression holds one number
    linear = _media.zoom_filter_linear(1.1, 1.122, 150, ANCHOR, 1080, 1920, [(a, b, zp)])
    assert "1/(if(between(on-1,%d,%d),%.5f,(1.10000+0.000148*on)))" % (a, b - 1, zp) in linear      # perspective counts `on` from 1
    plain = _media.zoom_filter(1.0, 1.0, 150, ANCHOR, 1080, 1920, 30, 2, [(5, 40, 1.12)])        # an unzoomed range with a punch needs a zoompan, not a scale
    assert plain.startswith("zoompan=z='if(between(on,5,39),1.12000,1.00000)'")


def test_a_punch_that_cannot_zoom_in_past_the_ranges_own_level_is_dropped():
    edl = synthetic_edl(zoom={"mode": "alternate", "factor": 1.25, "push_in": 0.03, "anchor_y": 0.25})
    timeline = resolve(edl, beats_of([punch(1, 12, 13)]))
    assert timeline["punches"] == [] and timeline["effects_dropped"] == [{"id": "p1", "reason": "punch_capped"}]


def test_a_punch_is_stretched_cut_and_never_crosses_a_range():
    edl = synthetic_edl()
    [short] = resolve(edl, beats_of([punch(1, 18, 18)]))["punches"]       # 9.1 s to 9.4 s (frames 273-282): stretched to 0.8 s
    assert (short["start_frame"], short["end_frame"]) == (273, 297)
    [long] = resolve(edl, beats_of([punch(1, 2, 12)]))["punches"]         # 1.1 s to 6.4 s: cut at 3 s
    assert long["end_frame"] - long["start_frame"] == 90 and long["end_frame"] <= 150
    [crossing] = resolve(edl, beats_of([punch(1, 8, 11)]))["punches"]     # 4.1 s to 5.9 s: the range ends at frame 150
    assert (crossing["start_frame"], crossing["end_frame"]) == (123, 150) and crossing["range"] == 0
    [late] = resolve(edl, beats_of([punch(1, 19, 19)]))["punches"]        # 9.6 s: stretched to frame 312, cut at the range's end, 300
    assert late["end_frame"] == 300 and late["range"] == 1
    timeline = resolve(edl, beats_of([punch(1, 9, 9)]))                   # 4.6 s to 4.9 s: from frame 138 the range has 12 frames, exactly 0.4 s: kept
    assert [(p["start_frame"], p["end_frame"]) for p in timeline["punches"]] == [(138, 150)]
    timeline = resolve(edl, beats_of([punch(1, 10, 10)]))                 # 5.1 s: frame 153 to 177 in the second range
    assert [(p["start_frame"], p["range"]) for p in timeline["punches"]] == [(153, 1)]
    timeline = resolve(edl, beats_of([punch(1, 19, 19), punch(2, 18, 18)]))
    assert [(p["id"], p["start_frame"], p["end_frame"]) for p in timeline["punches"]] == [("p2", 273, 297)]      # p1 starts where p2 ends and is left 3 frames
    assert timeline["effects_dropped"] == [{"id": "p1", "reason": "punch_short"}]


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


def test_the_checks_of_the_two_new_keys():
    edl = synthetic_edl()
    ok = beats_of([punch(1, 2, 3)], [effect("e1", "flash", 2, 2), effect("e2", "mono", 5, 6)])
    assert _edl.check_beats(ok, edl, VOCAB)["texts"] == []
    for bad, code in ((beats_of([punch(1, 2, 3), punch(1, 5, 6)]), "bad_beat"), (beats_of([punch(1, 30, 31)]), "bad_word_range"),
                      (beats_of([dict(punch(1, 2, 3), start=1.5)]), "unknown_key"), (beats_of([dict(punch(1, 2, 3), score=2)]), "bad_score"),
                      (beats_of(effects=[effect("e1", "spin", 2, 3)]), "bad_effect"), (beats_of(effects=[effect("e9", "flash", 2, 3)]), "bad_id"),
                      (beats_of(effects=[effect("e1", "flash", 3, 2)]), "bad_word_range"), (beats_of(effects=[dict(effect("e1", "mono", 2, 3), seconds=2)]), "unknown_key"),
                      (beats_of(effects=[effect("e1", "mono", 2, 5), effect("e2", "tint", 5, 7)]), "effect_overlap"),
                      (beats_of(effects=[effect("e1", "flash", 1, 1), effect("e2", "dip", 4, 4), effect("e3", "flash", 8, 8)]), "too_many_flashes"),
                      (beats_of(effects=[effect("e%d" % k, "punch", 3 * k, 3 * k) for k in range(1, 7)] + [effect("e1", "punch", 25, 25)]), "too_many_effects")):
        assert refused(_edl.check_beats, bad, edl, VOCAB).code == code, code
    assert refused(_edl.check_beats, dict(beats_of(), punches={}), edl, VOCAB).code == "not_list"
    many = beats_of([punch(k, k, k) for k in range(1, 14)])
    assert refused(_edl.check_beats, many, edl, VOCAB).code == "too_many_punches"
    assert _edl.check_beats(beats_of(effects=[effect("e%d" % k, "punch", 3 * k, 3 * k) for k in range(1, 7)]), edl, VOCAB)      # six review effects are fine


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
        assert re.search(r"drawbox=x=0:y=0:w=iw:h=ih:t=fill:color=0xFFFFFF@[0-9.]+:enable='eq\(n,%d\)'" % (flash["start_frame"] - 150 + ramp), graph)
    for number in re.findall(r"between\(n,(\d+),(\d+)\)|eq\(n,(\d+)\)|between\(on,(\d+),(\d+)\)", graph):
        assert all(x == "" or x.isdigit() for x in number)


def test_a_grade_in_the_graph_is_in_its_ranges_own_frame_index_and_after_the_zoom():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of(effects=[effect("e1", "flash", 12, 12), effect("e2", "mono", 20, 20), effect("e3", "tint", 2, 2)]))
    graph = _media.base_graph(dict(PLAN, effects=_edl.range_effects(edl, timeline)))
    ranges = [line for line in graph if "trim=start_frame" in line]
    assert "drawbox" in ranges[0] and "0xFFC93C@0.180" in ranges[0] and "colorchannelmixer" not in ranges[0]
    assert "drawbox" in ranges[1] and "color=0xFFFFFF@0.850:enable='eq(n,33)'" in ranges[1]
    assert "colorchannelmixer" in ranges[2] and "drawbox" not in ranges[2] and ranges[2].index(_media.TO_RGB) < ranges[2].index("colorchannelmixer") < ranges[2].index(_media.FROM_RGB)
    for k, line in enumerate(ranges):
        if "drawbox" in line or "colorchannelmixer" in line:
            assert line.index("drawbox" if "drawbox" in line else "colorchannelmixer") > line.index("setsar=1")      # a grade comes after the zoom
        assert line.endswith("format=yuv420p[v%d]" % k)


def test_grades_are_bounded():
    edl = synthetic_edl()
    wide = copy.deepcopy(DATA)
    wide["effects"].update(flash_alphas=[0.9] * 9, dip_alphas=[0.5] * 12, grade_max_seconds=30.0, grade_min_seconds=0.0)
    timeline = resolve(edl, beats_of(effects=[effect("e1", "flash", 2, 2), effect("e2", "dip", 14, 14)]), wide)
    lengths = {g["kind"]: g["end_frame"] - g["start_frame"] for g in timeline["grades"]}
    assert lengths == {"flash": _edl.FLASH_FRAMES_MAX, "dip": _edl.DIP_FRAMES_MAX} and (_edl.FLASH_FRAMES_MAX, _edl.DIP_FRAMES_MAX) == (4, 6)
    long = resolve(edl, beats_of(effects=[effect("e1", "mono", 0, 9)]), wide)["grades"][0]           # 0.1 s to 4.9 s, 4.8 s of words
    assert long["end_frame"] - long["start_frame"] <= int(_edl.GRADE_SECONDS_MAX * FPS)
    short = resolve(edl, beats_of(effects=[effect("e1", "tint", 2, 2)]))["grades"][0]               # a word of 0.3 s: stretched to 0.5 s
    assert short["end_frame"] - short["start_frame"] == int(round(DATA["effects"]["grade_min_seconds"] * FPS))
    edge = resolve(edl, beats_of(effects=[effect("e1", "flash", 8, 8)]))["grades"][0]                 # 4.1 s: frame 123, four frames, inside the first range
    assert edge["end_frame"] - edge["start_frame"] == 4
    cut = resolve(edl, beats_of(effects=[effect("e1", "dip", 9, 9)]))["grades"][0]                    # frame 138: the range ends at 150, six frames fit
    assert cut["end_frame"] == 144
    closing = resolve(edl, beats_of(effects=[effect("e1", "dip", 10, 10)]))["grades"][0]
    assert closing["start_frame"] == 153
    assert refused(_edl.check_beats, beats_of(effects=[effect("e1", "flash", 1, 1), effect("e2", "dip", 3, 3), effect("e3", "flash", 5, 5)]), edl, VOCAB).code == "too_many_flashes"
    assert refused(_edl.check_beats, beats_of(effects=[effect("e%d" % k, "punch", k, k) for k in range(1, 8)]), edl, VOCAB).code == "too_many_effects"


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
    page = _hf_page.FX_JS
    assert 'grayscale(1)' in page      # the page's mono is the CSS filter this matrix is copied from


# ---------------------------------------------------------------- one table, three drawings

def effects_edl():
    edl = synthetic_edl()
    beats = beats_of([punch(1, 12, 13)], [effect("e1", "flash", 3, 3), effect("e2", "mono", 20, 21), effect("e3", "tint", 24, 25), effect("e4", "punch", 2, 3)])
    return edl, resolve(edl, beats)


def test_the_page_and_the_reference_use_the_same_rows():
    edl, timeline = effects_edl()
    table = _edl.range_effects(edl, timeline)
    assert sorted(table) == [0, 1, 2] and all(table[k]["first"] == f for k, f in ((0, 0), (1, 150), (2, 300)))
    parts = _hf_page.build_parts(edl, fps=FPS, effects=table)
    punched = {row[0]: row for row in parts["vars"]["punched"]}
    ref = "\n".join(_hf_gate.reference_graph(edl, DATA, "[1:v:0]", effects=table))
    comp = "\n".join(_media.base_graph(dict(PLAN, effects=table)))
    for k, fx in table.items():
        for a, b, zp in fx["punches"]:
            assert [a, b, zp] in punched[k][6]
            assert "between(on-1,%d,%d),%.5f" % (a, b - 1, zp) in ref and "between(on,%d,%d),%.5f" % (a, b - 1, zp) in comp      # the reference's filter counts from 1
    grades = parts["vars"]["grades"]
    assert [g[0] for g in grades] == ["flash", "mono", "tint"]
    assert grades[0][1:3] == [timeline["grades"][0]["start_frame"], timeline["grades"][0]["end_frame"]]
    for kind in ("0xFFFFFF@0.850", "colorchannelmixer", "0xFFC93C@0.180"):
        assert kind in ref and kind in comp
    one = _hf_gate.reference_graph(edl, DATA, "[1:v:0]", only=1, effects=table)           # one range alone: the same rows by the range's number
    assert any("between(on-1,%d,%d)" % (a, b - 1) in line for line in one for a, b, _ in table[1]["punches"])
    nothing = _hf_gate.reference_graph(edl, DATA, "[1:v:0]", only=1)
    assert not any("between(on" in line for line in nothing)
    pixel = _hf_gate.pixel_argv_range("ffmpeg", "i.mov", "p.mp4", edl, DATA, _edl.range_faces(edl, DATA), 1, table)
    assert "between(on-1" in pixel[pixel.index("-filter_complex") + 1]


def test_the_page_draws_punches_from_the_frame_index_and_keeps_the_base_zoom_for_the_other_ranges():
    edl, timeline = effects_edl()
    parts = _hf_page.build_parts(edl, fps=FPS, effects=_edl.range_effects(edl, timeline))
    assert all(z[0] not in {r[0] for r in parts["vars"]["punched"]} for z in parts["vars"]["zooms"])      # a punched range has no GSAP zoom tween
    page = _hf_page.render_page(parts, width=1080, height=1920, fps=FPS, background="#0B0F14")
    assert page.count('<div id="fx"></div>') == 1 and "#fx {" in page and "var PZ" in page and page.index("var PZ") < page.index('window.__timelines["main"]')
    assert page.index('<div id="fx"></div>') > page.index('id="zw2"')                       # above the video wrappers
    assert "Date" not in page and "random" not in page and "setTimeout" not in page


NODE_DRIVE = r"""
var V = JSON.parse(process.argv[1]);
var calls = [], els = {};
var main = { fromTo: function (obj, from, to, pos) { calls.push(obj); } };
var document = { getElementById: function (id) { els[id] = els[id] || { style: {} }; return els[id]; } };
require('vm').runInThisContext(process.argv[2]);
var out = {};
JSON.parse(process.argv[3]).forEach(function (n) {
  calls.forEach(function (c) { c.at(n / V.fps); });
  out[n] = JSON.parse(JSON.stringify(els));
});
console.log(JSON.stringify(out));
"""


def drive(variables: dict, frames: list) -> dict:
    """What the page's drive code leaves in each element's style at each OUTPUT frame (the timeline's time is seconds, one second a range's own seconds
    added by the range's start in the real page: here the drive is called with the range's own time, so a range-local frame is a time n / fps)."""
    done = subprocess.run(["node", "-e", NODE_DRIVE, json.dumps(variables), _hf_page.FX_JS, json.dumps(frames)], capture_output=True, text=True, check=True)
    return {int(n): rows for n, rows in json.loads(done.stdout).items()}


@needs_node
def test_the_pages_drive_code_follows_the_same_piecewise_rule_as_the_filter():
    edl, timeline = effects_edl()
    table = _edl.range_effects(edl, timeline)
    variables = _hf_page.build_parts(edl, fps=FPS, effects=table)["vars"]
    [row] = [r for r in variables["punched"] if r[0] == 1]
    k, start, dur, z0, z1, frames, rows = row
    seen = drive(variables, list(range(frames)))                      # the punched range's drive is given its own frame index
    for n in range(frames):
        scale = float(re.search(r"scale\(([0-9.]+)\)", seen[n]["zw1"]["style"]["transform"]).group(1))
        want = z0 + (z1 - z0) * n / max(1, frames - 1)
        for a, b, zp in rows:
            if a <= n < b:
                want = zp
        assert scale == pytest.approx(want, abs=1e-5), n
    assert seen[0]["zw0"]["style"]["transform"].startswith("scale(1.0")                  # the other punched range moved too: both are driven


@needs_node
def test_the_pages_grade_code_draws_the_ramp_and_the_mono_filter_on_the_frames_of_the_rows():
    edl, timeline = effects_edl()
    variables = _hf_page.build_parts(edl, fps=FPS, effects=_edl.range_effects(edl, timeline))["vars"]
    flash = [g for g in variables["grades"] if g[0] == "flash"][0]
    mono = [g for g in variables["grades"] if g[0] == "mono"][0]
    tint = [g for g in variables["grades"] if g[0] == "tint"][0]
    seen = drive(variables, [flash[1] - 1, flash[1], flash[1] + 1, flash[2] - 1, flash[2], mono[1] - 1, mono[1], mono[2] - 1, mono[2], tint[1], tint[2]])
    opacity = {n: seen[n]["fx"]["style"]["opacity"] for n in seen}
    assert opacity[flash[1] - 1] == "0" and opacity[flash[1]] == "0.85" and opacity[flash[1] + 1] == "0.6" and opacity[flash[2] - 1] == "0.1" and opacity[flash[2]] == "0"
    assert seen[flash[1]]["fx"]["style"]["backgroundColor"] == "#ffffff"
    assert [seen[n]["zw%d" % mono[5]]["style"]["filter"] for n in (mono[1] - 1, mono[1], mono[2] - 1, mono[2])] == ["none", "grayscale(1)", "grayscale(1)", "none"]
    assert opacity[tint[1]] == "0.18" and seen[tint[1]]["fx"]["style"]["backgroundColor"] == tint[4] and opacity[tint[2]] == "0"


# ---------------------------------------------------------------- the face check

def test_the_crop_covers_every_punched_row():
    edl, timeline = effects_edl()
    faces = _edl.range_faces(edl, DATA)
    crops = _hf_gate.punched_faces(faces, timeline)
    assert [(a, b) for a, b, _ in crops] == [(a, b) for a, b, _ in faces]
    for p in timeline["punches"]:
        box, crop = p["face"], crops[p["range"]][2]
        assert crop["x"] <= box["x"] and crop["y"] <= box["y"] and crop["x"] + crop["w"] >= box["x"] + box["w"] and crop["y"] + crop["h"] >= box["y"] + box["h"]
        w, h, x, y = _hf_gate.crop_box(crop, 1080, 1920)
        assert x <= box["x"] and y <= box["y"] and x + w >= box["x"] + box["w"] - 2 and y + h >= box["y"] + box["h"] - 2
    untouched = _hf_gate.punched_faces(faces, resolve(edl, beats_of()))
    assert untouched is faces


def test_a_punched_frame_is_tested_against_the_punched_face_and_a_beat_in_a_punch_clears_it():
    edl, timeline = effects_edl()
    faces = _edl.range_faces(edl, DATA)
    by_zone = _hf_gate.faces_by_frame(timeline, faces, edl["out_frames"])
    for p in timeline["punches"]:
        for f in range(p["start_frame"], p["end_frame"]):
            assert by_zone["card"][f] == p["face"] or all(by_zone["card"][f][k] <= p["face"][k] for k in "xy")
    none = _hf_gate.faces_by_frame(resolve(edl, beats_of()), faces, edl["out_frames"])
    assert none["card"][160] == faces[1][2]
    p = timeline["punches"][0]
    outside = _edl.span_face(edl, DATA, p["start_frame"], p["end_frame"])
    inside = _edl.span_face(edl, DATA, p["start_frame"], p["end_frame"], timeline["punches"])
    assert inside["y"] <= outside["y"] and inside["y"] + inside["h"] >= outside["y"] + outside["h"]
    caption = timeline["captions"][0]
    assert caption["face"] == _edl.span_face(edl, DATA, caption["start_frame"], caption["end_frame"], timeline["punches"])


def test_the_explanation_of_a_refusal_names_the_effects_on_the_worst_frame():
    edl, timeline = effects_edl()
    p = timeline["punches"][0]
    values = [40.0] * (150 - 0)
    rows = _hf_gate.explain(1, edl, 150, 300, values[:150], p["start_frame"] - 150, timeline)
    drawn = [r for r in rows if r["code"] == "drawn_at_worst"][0]
    assert "punch" in drawn["field"]


def test_the_gate_constants_do_not_move_with_the_effects():
    assert _hf_gate.PIXEL_MIN_PSNR_DB == 30.0 and DATA["zones"]["card_min_height"] == 80 and DATA["zones"]["caption_bottom"] == 1560


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
    assert line.index(_media.TO_RGB) < line.index(next(x for x in line if x.startswith("colorchannelmixer"))) < line.index(_media.FROM_RGB) < line.index(next(x for x in line if x.startswith("drawbox")))
    frames = ffmpeg_frames("format=yuv420p," + ",".join(line))[:60]

    def spread(n):
        return max(abs(v - 128) for v in frames[n][w * h:])

    assert all(spread(n) <= 3 for n in range(16, 24))             # grey only
    assert all(spread(n) > 8 for n in range(24, 32))             # grey and tinted: the tint is coloured
    assert all(spread(n) > 8 for n in range(32, 40)) and spread(10) > 20


def parse_reference(graph: list, first_global: dict) -> list:
    """The grades a reference graph draws, as [kind, from, to] in OUTPUT frames, read from its filter text (flash and dip by their colour)."""
    found = []
    ranges = [line for line in graph if "trim=start_frame" in line]
    for k, line in enumerate(ranges):
        base = first_global[k]
        eq = {}
        for color, n in re.findall(r"drawbox=[^,;]*color=0x(FFFFFF|000000)@[0-9.]+:enable='eq\(n,(\d+)\)'", line):
            eq.setdefault("flash" if color == "FFFFFF" else "dip", []).append(base + int(n))
        for kind, frames in eq.items():
            found.append([kind, min(frames), max(frames) + 1])
        for color, a, b in re.findall(r"drawbox=[^,;]*color=0x([0-9A-F]{6})@[0-9.]+:enable='between\(n,(\d+),(\d+)\)'", line):
            found.append(["tint", base + int(a), base + int(b) + 1])
        for a, b in re.findall(r"colorchannelmixer=[^,;]*:enable='between\(n,(\d+),(\d+)\)'", line):
            found.append(["mono", base + int(a), base + int(b) + 1])
    return sorted(found)


def test_the_references_grade_frames_are_the_pages_grade_rows_with_mono_and_tint_adjacent():
    edl = synthetic_edl()
    beats = beats_of(effects=[effect("e1", "flash", 3, 3), effect("e2", "mono", 12, 13), effect("e3", "tint", 14, 15), effect("e4", "dip", 22, 22)])
    timeline = resolve(edl, beats)
    table = _edl.range_effects(edl, timeline)
    page = sorted([g[0], g[1], g[2]] for g in _hf_page.build_parts(edl, fps=FPS, effects=table)["vars"]["grades"])
    firsts = {k: f for k, (f, _) in enumerate(_edl.range_table(edl))}
    reference = parse_reference(_hf_gate.reference_graph(edl, DATA, "[1:v:0]", effects=table), firsts)
    compose = parse_reference(_media.base_graph(dict(PLAN, effects=table)), firsts)
    assert page == reference == compose
    mono = [g for g in page if g[0] == "mono"][0]
    tint = [g for g in page if g[0] == "tint"][0]
    assert 0 <= tint[1] - mono[2] <= 15            # the two are neighbours in the fixture


def test_a_punch_the_renderer_leaves_out_is_reported_and_reaches_the_page_result_and_the_runtime(tmp_path):
    import _docker
    edl = synthetic_edl()
    beats = beats_of([punch(1, 2, 8)], [effect("e1", "punch", 4, 4)])
    timeline = resolve(edl, beats)
    assert timeline["effects_dropped"] == [{"id": "e1", "reason": "punch_short"}]
    clean = _docker.sanitise({"ok": True, "page_sha256": "a" * 64, "vars_sha256": "b" * 64, "clips": 1, "zooms": 0, "duration": 1.0, "fps": 30, "layers": ["cuts"],
                              "effects_dropped": timeline["effects_dropped"]}, _docker.RESULT_SCHEMAS["hf-page"], "hf-page")
    assert clean["effects_dropped"] == [{"id": "e1", "reason": "punch_short"}]


def test_the_configuration_cannot_raise_the_alphas_past_the_specs_values():
    edl = synthetic_edl()
    wide = copy.deepcopy(DATA)
    wide["effects"].update(flash_alphas=[1.0, 7, -2, 0.5], dip_alphas=[1.0] * 6, tint_alpha=0.9)
    timeline = resolve(edl, beats_of(effects=[effect("e1", "flash", 2, 2), effect("e2", "dip", 9, 9), effect("e3", "tint", 14, 15)]), wide)
    by = {g["kind"]: g for g in timeline["grades"]}
    assert by["flash"]["alphas"] == [0.85, 0.85, 0.0, 0.5] and set(by["dip"]["alphas"]) == {0.85} and by["tint"]["alpha"] == 0.18
