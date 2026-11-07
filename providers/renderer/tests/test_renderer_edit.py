"""What a person sees decided: retake proposals and their confirmation, the face box, the zoom, the anchors."""
from __future__ import annotations

import copy
import json

import pytest

import renderer_kit as K
import _align as A
import _edl
import _media
import _timeline as T
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))


def mk(text, t0=0.0, step=0.25, dur=0.2):
    out, t = [], t0
    for k, tok in enumerate(text.split()):
        out.append({"index": k, "text": tok, "start": round(t, 3), "end": round(t + dur, 3), "segment": 0, "estimated": False, "dropped": False})
        t += step
    return out


def refused(fn, *a, **k):
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


# ---------------------------------------------------------------- retakes

def test_a_run_of_four_words_that_recurs_proposes_dropping_the_earlier_take():
    w = mk("so the first rule is uh sorry the first rule is simple name every dollar")
    (p,) = T.detect_retakes(w)
    assert p["kind"] == "repeat" and p["confirmed"] is False and p["id"] == "retake-1"
    assert (p["word_from"], p["word_to"], p["keep_from"]) == (1, 6, 7)      # up to the word before the later take
    assert p["seconds"] == pytest.approx(1.45)


def test_a_sentence_cut_midway_and_restarted_is_a_restart():
    w = mk("then I went to the market. then I went home and slept.")
    w[5]["text"] = "market"                                # the first sentence has no sentence punctuation: it was cut off
    w[5]["end"] = w[5]["start"] + 0.2
    w[6]["start"] += 1.0
    for x in w[6:]:
        x["start"] += 1.0
        x["end"] += 1.0
    props = T.detect_retakes(w)
    assert [p["kind"] for p in props] in (["restart"], ["repeat"])        # either rule names the same earlier take
    assert props[0]["word_from"] == 0 and props[0]["keep_from"] == 6


def test_ordinary_speech_has_no_proposal_and_a_repeat_far_apart_is_not_one():
    assert T.detect_retakes([dict(w) for w in K.build_transcript()["words"] and mk("name every dollar then review adjust and celebrate each week")]) == []
    far = mk("name every dollar today") + mk("name every dollar today", t0=40.0)
    for k, w in enumerate(far):
        w["index"] = k
    assert T.detect_retakes(far) == []                         # 40 s apart, over the 20 s window
    near = mk("name every dollar today") + mk("name every dollar today", t0=6.0)
    for k, w in enumerate(near):
        w["index"] = k
    assert len(T.detect_retakes(near)) == 1


def test_proposals_never_overlap_and_carry_indices_only():
    w = mk("a b c d e f a b c d e f a b c d e f")
    props = T.detect_retakes(w)
    assert all(set(p) == _edl.PROPOSAL_KEYS for p in props)
    assert all(a["word_to"] < b["word_from"] for a, b in zip(props, props[1:]))
    assert not any(isinstance(v, str) and v not in ("repeat", "restart") and not v.startswith("retake-") for p in props for v in p.values())


def retake_transcript():
    doc = K.build_transcript([(1.0, "Today I want to talk about money and habits."), (1.0, "The first rule is uh sorry."),
                              (1.0, "The first rule is simple, name every dollar."), (1.0, "Follow for more small steps.")])
    return doc


def analysis_for(doc, silences=None):
    return {"facts": {"duration": doc["duration"], "sha256": "d" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": silences}


def test_a_proposal_is_not_applied_until_it_is_confirmed():
    doc = retake_transcript()
    edl, _ = _edl.build_base(doc, analysis_for(doc), DATA, {})
    assert edl["proposals"] and not any(p["confirmed"] for p in edl["proposals"])
    assert len(edl["words"]) == len(doc["words"])               # nothing dropped
    _edl.check_edl(edl, DATA, VOCAB, {})
    pid = edl["proposals"][0]["id"]
    done, _ = _edl.build_base(doc, analysis_for(doc), DATA, {}, confirm={pid})
    p = next(x for x in done["proposals"] if x["id"] == pid)
    assert p["confirmed"] and len(done["words"]) == len(doc["words"]) - (p["word_to"] - p["word_from"] + 1)
    assert not {w["index"] for w in done["words"]} & set(range(p["word_from"], p["word_to"] + 1))
    assert done["out_frames"] < edl["out_frames"]               # the take is really cut from the picture and the sound
    _edl.check_edl(done, DATA, VOCAB, {})


def test_confirming_a_proposal_that_does_not_exist_is_refused():
    doc = retake_transcript()
    assert refused(_edl.build_base, doc, analysis_for(doc), DATA, {}, confirm={"retake-99"}).code == "unknown_proposal"


def test_a_confirmed_proposal_whose_words_are_still_drawn_is_refused_by_check():
    doc = retake_transcript()
    edl, _ = _edl.build_base(doc, analysis_for(doc), DATA, {})
    bad = copy.deepcopy(edl)
    bad["proposals"][0]["confirmed"] = True
    assert refused(_edl.check_edl, bad, DATA, VOCAB, {}).code == "confirmed_drop_still_drawn"
    bad = copy.deepcopy(edl)
    bad["proposals"][0]["extra"] = "x"
    assert refused(_edl.check_edl, bad, DATA, VOCAB, {}).code == "unknown_key"
    bad = copy.deepcopy(edl)
    bad["proposals"][0]["keep_from"] = bad["proposals"][0]["word_to"]
    assert refused(_edl.check_edl, bad, DATA, VOCAB, {}).code == "bad_proposals"


def test_the_beat_aligner_can_leave_out_the_dropped_words(tmp_path):
    doc = retake_transcript()
    edl, _ = _edl.build_base(doc, analysis_for(doc), DATA, {}, confirm={"retake-1"})
    post = tmp_path / "post.md"
    post.write_text(K.POST.replace("line: The first rule is simple: name every dollar.", "line: The first rule is simple, name every dollar."), encoding="utf-8")
    kept_idx = {w["index"] for w in edl["words"]}
    rows = [r for r in A.read_beats(post.read_text(), VOCAB) if r["preset"]]
    tr = T.check_transcript(doc, DATA["limits"])
    words, _ = T.normalise_words(tr["words"], tr["segments"], tr["duration"])
    live = [w for w in words if w["index"] in kept_idx]
    res = A.align_beats(live, [r for r in rows if r["beat"] == 3])
    assert res[0]["matched"] and res[0]["word_from"] in kept_idx and res[0]["word_to"] in kept_idx


# ---------------------------------------------------------------- the face box

def test_the_face_box_must_be_inside_the_frame_and_leave_room_for_cards_and_captions():
    ok = {"x": 240, "y": 620, "w": 600, "h": 560}
    assert _edl.check_face(DATA, dict(ok)) == ok
    for bad, code in (({"x": -1, "y": 620, "w": 600, "h": 560}, "bad_face_box"), ({"x": 900, "y": 620, "w": 600, "h": 560}, "bad_face_box"),
                      ({"x": 240, "y": 620, "w": 50, "h": 560}, "bad_face_box"), ({"x": 240, "y": 620, "w": 600.5, "h": 560}, "bad_face_box"),
                      ({"x": 240, "y": 200, "w": 600, "h": 560}, "face_box_leaves_no_room"),      # no band above for a card
                      ({"x": 240, "y": 1000, "w": 600, "h": 700}, "face_box_leaves_no_room")):     # no band below for captions
        assert refused(_edl.check_face, DATA, bad).code == code, bad
    assert refused(_edl.check_face, DATA, {"x": 1, "y": 2, "w": 3}).code in ("missing_key", "unknown_key")
    assert _edl.parse_face_box("240,620,600,560") == ok
    assert refused(_edl.parse_face_box, "240,620,600").code == "bad_face_box"
    z = _edl.zones(DATA, ok)
    assert z["card"][1] <= ok["y"] and z["caption"][0] >= ok["y"] + ok["h"]


def test_the_base_list_keeps_the_face_box_the_person_gave():
    doc = K.build_transcript()
    edl, _ = _edl.build_base(doc, analysis_for(doc), DATA, {}, face_box={"x": 300, "y": 700, "w": 500, "h": 500})
    assert edl["face_box"] == {"x": 300, "y": 700, "w": 500, "h": 500}
    assert refused(_edl.build_base, doc, analysis_for(doc), DATA, {}, face_box={"x": 0, "y": 0, "w": 1080, "h": 1920}).code == "face_box_leaves_no_room"


def test_a_drawn_box_that_touches_the_face_box_is_found():
    import _frames
    face = {"x": 240, "y": 620, "w": 600, "h": 560}
    assert _frames.face_hit([{"zone": "card", "x": 100, "y": 200, "w": 800, "h": 380}], face) is None
    assert _frames.face_hit([{"zone": "card", "x": 100, "y": 200, "w": 800, "h": 440}], face) == "card"
    assert _frames.face_hit([{"zone": "caption", "x": 100, "y": 1100, "w": 800, "h": 200}], face) == "caption"
    assert _frames.face_hit([{"zone": "layout", "x": 0, "y": 0, "w": 1080, "h": 1920}], face) is None    # cutaway and pip are not in a zone
    assert _frames.face_hit([{"zone": "card", "x": 0, "y": 600, "w": 0, "h": 0}], face) is None          # nothing drawn


# ---------------------------------------------------------------- the zoom

def test_the_zoom_settings_are_bounded():
    for zoom in ({"mode": "alternate", "factor": 1.1, "push_in": 0.0, "anchor_y": 0.25}, {"mode": "none", "factor": 1.0, "push_in": 0.03, "anchor_y": 0.0}):
        _edl.check_zoom(DATA, zoom)
    for zoom, code in (({"mode": "wobble", "factor": 1.1, "push_in": 0, "anchor_y": 0.25}, "bad_choice"), ({"mode": "alternate", "factor": 1.5, "push_in": 0, "anchor_y": 0.25}, "bad_zoom"),
                       ({"mode": "alternate", "factor": 0.9, "push_in": 0, "anchor_y": 0.25}, "bad_zoom"), ({"mode": "alternate", "factor": 1.1, "push_in": 0.05, "anchor_y": 0.25}, "bad_zoom"),
                       ({"mode": "alternate", "factor": True, "push_in": 0, "anchor_y": 0.25}, "bad_zoom"), ({"mode": "alternate", "factor": 1.1, "push_in": 0}, "missing_key"),
                       ({"mode": "alternate", "factor": 1.1, "push_in": 0, "anchor_y": 1.5}, "bad_zoom")):
        assert refused(_edl.check_zoom, DATA, zoom).code == code, zoom


FACE = {"cx": 540, "cy": 900, "w": 600, "h": 560}
ANCHOR = (540.0, 620 + 0.25 * 560)          # the face's centre, a quarter of its height down from its top: (540, 760)
BOX = {"x": 240, "y": 620, "w": 600, "h": 560}


def test_the_zoom_is_about_a_fixed_point_on_a_picture_twice_the_output_size():
    assert _media.anchor_point(BOX, 0.25) == ANCHOR
    zoom = {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}
    assert _media.zoom_levels(zoom, 0, 300, 30) == (1.0, 1.0 * 1.02)                  # an even range is unzoomed, and a long one still pushes in
    assert _media.zoom_levels(zoom, 1, 300, 30)[0] == 1.1 and _media.zoom_levels(zoom, 1, 300, 30)[1] == pytest.approx(1.1 * 1.02)
    assert _media.zoom_levels(zoom, 1, 60, 30) == (1.1, 1.1)                           # a range under 5 s does not push
    assert _media.zoom_levels({**zoom, "mode": "none", "push_in": 0.0}, 1, 300, 30) == (1.0, 1.0)
    assert _media.zoom_filter(1.0, 1.0, 100, ANCHOR, 1080, 1920, 30) == "scale=1080:1920:flags=" + _media.SWS
    still = _media.zoom_filter(1.1, 1.1, 100, ANCHOR, 1080, 1920, 30)
    assert still == "zoompan=z='1.10000':x='1080.00*(1-1/zoom)':y='1520.00*(1-1/zoom)':d=1:s=1080x1920:fps=30"      # the anchor, doubled: the picture is cut at 2x
    push = _media.zoom_filter(1.0, 1.02, 100, ANCHOR, 1080, 1920, 30)
    assert push.startswith("zoompan=z='1.00000+0.000202*on'") and "d=1:s=1080x1920:fps=30" in push


def test_every_second_range_is_zoomed_on_the_face_and_stays_inside_the_frame():
    plan_ = plan()
    graph = _media.compose_argv("ffmpeg", plan_)
    graph = graph[graph.index("-filter_complex") + 1]
    assert "scale=2160:3840" in graph and "crop=2160:3840" in graph                    # the picture is cut at twice the output size
    ranges = [part for part in graph.split(";") if "trim=start_frame" in part]
    assert len(ranges) == 3 and "zoompan" not in ranges[0] and ranges[0].count("scale=1080:1920:flags=" + _media.SWS) == 1 and "zoompan=z='1.10000'" in ranges[1] and "zoompan" not in ranges[2]


def test_the_zoomed_box_is_the_face_box_grown_about_the_anchor():
    assert _media.zoomed_box(BOX, 1.0, 1.0, ANCHOR, 1080, 1920) == BOX
    box = _media.zoomed_box(BOX, 1.1, 1.1, ANCHOR, 1080, 1920)
    assert box == {"x": 210, "y": 606, "w": 660, "h": 616}                           # 240 -> 540 + (240-540)*1.1, 620 -> 760 + (620-760)*1.1
    grown = _media.zoomed_box(BOX, 1.1, 1.1 * 1.02, ANCHOR, 1080, 1920)
    assert grown["w"] > box["w"] and grown["h"] > box["h"] and grown["y"] <= box["y"]
    corner = _media.zoomed_box({"x": 0, "y": 0, "w": 300, "h": 300}, 1.25, 1.25, (150.0, 75.0), 1080, 1920)
    assert corner["x"] == 0 and corner["y"] == 0


def test_the_bubble_is_cut_around_the_face():
    side, x, y = _media.bubble_crop(FACE, 1080, 1920)
    assert side == 720 and 0 <= x <= 1080 - side and 0 <= y <= 1920 - side and abs((x + side / 2) - 540) <= 1


def plan(**over):
    base = {"src": "/in/recording", "fps": 30, "size": [1080, 1920], "has_audio": True, "src_matrix": "bt709", "kept": [[0, 60], [90, 150], [180, 240]],
            "layers": ["caption"], "frames_dir": "frames", "pips": [], "pip_size": 380, "out_frames": 180, "max_bytes": 300000000, "out_name": "out.mp4",
            "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.0, "anchor_y": 0.25}, "face": FACE, "anchor": ANCHOR, "fade": 0.015}
    base.update(over)
    return base


def test_the_audio_of_every_range_fades_a_few_milliseconds_at_both_ends_and_keeps_its_length():
    argv = _media.compose_argv("ffmpeg", plan())
    graph = argv[argv.index("-filter_complex") + 1]
    assert graph.count("afade=t=in:st=0:d=0.0150") == 3 and graph.count("afade=t=out:st=1.985000:d=0.0150") == 3
    assert "acrossfade" not in graph                                      # a fade, not an overlap: sound and picture stay in step
    one_frame = _media.compose_argv("ffmpeg", plan(fps=60, kept=[[0, 1], [30, 90]]))
    assert "afade=t=in:st=0:d=0.0083" in one_frame[one_frame.index("-filter_complex") + 1]    # never more than half a range


# ---------------------------------------------------------------- anchors and the verbs

def align_cli(tmp_path, *more, post=None):
    p = tmp_path / "post.md"
    p.write_text(post or K.POST, encoding="utf-8")
    tr = K.write_json(tmp_path / "t.json", K.build_transcript())
    return K.run_verb("align", "--post", p, "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "b.json", *more)


def test_an_anchor_places_a_beat_the_aligner_could_not_over_the_words_the_person_picked(tmp_path):
    lost = K.POST.replace("line: The first rule is simple: name every dollar.", "line: Quarterly revenue forecasts always disappoint auditors.")
    rc, out, err = align_cli(tmp_path, post=lost)
    assert rc == 0 and out["unmatched"] == [3]
    rc, out, err = align_cli(tmp_path, "--anchor", "3=15-19", post=lost)
    assert rc == 0, err
    assert out["unmatched"] == [] and out["scores"]["3"] == 1.0
    beats = json.loads((tmp_path / "b.json").read_text())
    entry = next(e for e in beats["overlays"] if e["beat"] == 3)
    assert (entry["word_from"], entry["word_to"], entry["score"]) == (15, 19, 1.0) and next(r for r in beats["report"] if r["beat"] == 3)["anchored"] is True


@pytest.mark.parametrize("flag", ["3=15", "x=1-2", "3=19-15", "3=9999-10000", "1=2-3", "7=5-"])
def test_a_bad_anchor_is_a_usage_error_and_writes_nothing(tmp_path, flag):
    rc, out, err = align_cli(tmp_path, "--anchor", flag)
    assert rc == 2 and err.startswith("usage:") and not (tmp_path / "b.json").exists()          # beat 1 has no preset: nothing to anchor


def test_base_confirms_a_retake_by_id_through_the_verb_and_refuses_an_unknown_id(tmp_path):
    doc = retake_transcript()
    tr = K.write_json(tmp_path / "t.json", doc)
    analysis = K.write_json(tmp_path / "a.json", analysis_for(doc))
    rc, out, err = K.run_verb("base", "--transcript", tr, "--analysis", analysis, "--out", tmp_path / "e.json")
    assert rc == 0 and out["proposals"] and out["proposals"][0]["confirmed"] is False
    rc, done, err = K.run_verb("base", "--transcript", tr, "--analysis", analysis, "--out", tmp_path / "e2.json", "--confirm", out["proposals"][0]["id"])
    assert rc == 0 and done["proposals"][0]["confirmed"] is True and done["out_seconds"] < out["out_seconds"]
    rc, _, err = K.run_verb("base", "--transcript", tr, "--analysis", analysis, "--out", tmp_path / "e3.json", "--confirm", "retake-42")
    assert rc == 1 and err.startswith("refused: unknown_proposal") and not (tmp_path / "e3.json").exists()
    rc, _, err = K.run_verb("base", "--transcript", tr, "--analysis", analysis, "--out", tmp_path / "e4.json", "--face-box", "1,2,3,4")
    assert rc == 1 and err.startswith("refused: bad_face_box")
