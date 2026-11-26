"""P1a: the transitions at joins, the edit-list side. The row of `beats.json` `transitions` and its refusals (`_edl.check_transitions`), the defaults' bounds
(`_edl.check_transition_config`), and how a row becomes frames of the output timeline (`_edl.resolve_transitions`): the anchor, the rule that a transition never
starts inside a word, the overlap, the cutaway's own look. No count and no limit on the face (the maintainer, 2026-11-26: D4 is withdrawn for transitions).
Offline, synthetic, fictional."""
from __future__ import annotations

import copy
import json

import pytest

import renderer_kit as K
import _edl
import _render
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
FPS = 30
KEPT = [[0, 150], [200, 350], [400, 520]]          # output frames 0-149, 150-299 and 300-419


def synthetic_edl(kept=KEPT) -> dict:
    """28 words, one every half second (word i is spoken from 0.5 i + 0.1 to 0.5 i + 0.4), over three kept ranges."""
    frames = sum(b - a for a, b in kept)
    words = [{"index": i, "text": "word%d" % i, "start": round(0.5 * i + 0.1, 3), "end": round(0.5 * i + 0.4, 3)} for i in range(28)]
    return {"schema_version": 2, "fps": FPS, "size": [1080, 1920], "kept": [list(r) for r in kept], "out_frames": frames, "words": words,
            "captions": {"position": "bottom", "chunks": [[i, i + 3] for i in range(0, 28, 4)]}, "theme": {"colors": dict(DATA["theme"]["colors"]), "fonts": {}},
            "face_box": dict(DATA["face_box_default"]), "source": {"has_audio": True, "color_matrix": "bt709"},
            "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}}


def beats_of(transitions=None, overlays=(), layouts=()) -> dict:
    doc = {"schema_version": 1, "threshold": 0.6, "overlays": list(overlays), "layouts": list(layouts), "slots": [], "report": [], "unmatched": [], "fallbacks": []}
    if transitions is not None:
        doc["transitions"] = list(transitions)
    return doc


def tr(ident, kind, **anchor):
    return dict({"id": ident, "kind": kind}, **anchor)


def entry(bid, preset, params, a, b):
    return {"id": bid, "beat": int(bid[1:]), "preset": preset, "params": params, "word_from": a, "word_to": b, "score": 1.0}


def refused(fn, *args):
    with pytest.raises(Refusal) as caught:
        fn(*args)
    return caught.value


def check(rows, presets=None, index_set=None):
    return _edl.check_transitions(rows, index_set if index_set is not None else set(range(28)), presets or {})


# ---------------------------------------------------------------- the row and its refusals

def test_the_kinds_are_five_for_ffmpeg_and_two_for_the_cutaway_page():
    assert _edl.FFMPEG_TRANSITIONS == ("glitch", "bloom", "zoom_blur", "blur_to_card", "dip")
    assert _edl.PAGE_TRANSITIONS == ("slide", "zoom")
    assert _edl.TRANSITION_KINDS == _edl.FFMPEG_TRANSITIONS + _edl.PAGE_TRANSITIONS and _edl.TRANSITIONS_MAX == 99
    assert "transitions" in _edl.BEATS_KEYS


def test_a_good_row_by_word_and_by_beat_is_accepted_and_beats_without_the_key_still_read():
    check([tr("t1", "glitch", word=4), tr("t2", "slide", beat="b3"), tr("t99", "dip", beat="b9")], {"b3": "cutaway", "b9": "keyword"})
    check([])
    edl = synthetic_edl()
    assert "advice" not in _edl.check_beats(beats_of(), edl, VOCAB)
    assert "advice" not in _edl.check_beats(beats_of([tr("t1", "bloom", word=3)]), edl, VOCAB)


@pytest.mark.parametrize("row,code", [
    ({"id": "t1", "kind": "glitch"}, "bad_transition"),                                        # no anchor
    ({"id": "t1", "kind": "glitch", "word": 3, "beat": "b1"}, "bad_transition"),               # two anchors
    ({"id": "t1", "kind": "wipe", "word": 3}, "bad_transition"),                                # unknown kind
    ({"id": "t1", "kind": "glitch", "word": 3, "extra": 1}, "unknown_key"),
    ({"kind": "glitch", "word": 3}, "missing_key"),
    ({"id": "x1", "kind": "glitch", "word": 3}, "bad_id"),
    ({"id": "t0", "kind": "glitch", "word": 3}, "bad_id"),
    ({"id": "t100", "kind": "glitch", "word": 3}, "bad_id"),
    ({"id": "t1", "kind": "glitch", "word": 99}, "bad_transition_anchor"),                      # not a word of the edit list
    ({"id": "t1", "kind": "glitch", "word": True}, "bad_transition_anchor"),
    ({"id": "t1", "kind": "glitch", "beat": "nope"}, "bad_transition_anchor"),
    ({"id": "t1", "kind": "slide", "word": 3}, "transition_not_drawable"),                      # a page kind needs a cutaway beat
    ({"id": "t1", "kind": "zoom", "beat": "k1"}, "transition_not_drawable"),                    # k1 is a keyword
])
def test_each_malformed_row_is_refused_with_its_code(row, code):
    assert refused(check, [row], {"b1": "cutaway", "k1": "keyword"}).code == code


def test_a_duplicate_id_two_rows_on_one_anchor_and_too_many_rows_are_refused():
    assert refused(check, [tr("t1", "glitch", word=3), tr("t1", "dip", word=4)]).code == "bad_id"
    assert refused(check, [tr("t1", "glitch", word=3), tr("t2", "dip", word=3)]).code == "transition_anchor_taken"
    assert refused(check, [tr("t1", "glitch", beat="b1"), tr("t2", "slide", beat="b1")], {"b1": "cutaway"}).code == "transition_anchor_taken"
    check([tr("t1", "glitch", word=3), tr("t2", "dip", beat="b1")], {"b1": "keyword"})          # a word and a beat are two anchors
    ids = ["t%d" % k for k in range(1, 100)]
    check([tr(i, "dip", word=k % 28) if k < 28 else tr(i, "dip", beat="b%d" % k) for k, i in enumerate(ids)], {"b%d" % k: "keyword" for k in range(99)})
    assert refused(check, [tr("t1", "dip", word=0)] * 100).code == "too_many_transitions"
    assert refused(check, "x").code == "not_list"


def test_beats_that_carry_a_bad_transition_are_refused_by_the_beats_check():
    edl = synthetic_edl()
    assert refused(_edl.check_beats, beats_of([tr("t1", "glitch", word=99)]), edl, VOCAB).code == "bad_transition_anchor"


def test_the_schema_and_the_key_set_name_the_same_document():
    schema = json.loads((K.RENDERER / "edl.schema.json").read_text(encoding="utf-8"))
    beats = schema["$defs"]["beats"]
    assert set(beats["properties"]) == _edl.BEATS_KEYS
    item = beats["properties"]["transitions"]["items"]
    assert set(item["properties"]) == _edl.TRANSITION_KEYS and item["properties"]["kind"]["enum"] == list(_edl.TRANSITION_KINDS)
    assert beats["properties"]["transitions"]["maxItems"] == _edl.TRANSITIONS_MAX


# ---------------------------------------------------------------- the defaults' bounds (validity)

def config_with(mutate):
    data = copy.deepcopy(DATA)
    mutate(data["transitions"]["kinds"])
    return data


def test_the_committed_defaults_are_inside_every_bound_and_carry_no_face_limit():
    _edl.check_transition_config(DATA)
    assert set(DATA["transitions"]["kinds"]) == set(_edl.FFMPEG_TRANSITIONS) and "face" not in DATA["transitions"]


@pytest.mark.parametrize("mutate,field", [
    (lambda k: k["glitch"].update(intensity=[]), "transitions.glitch.intensity"),
    (lambda k: k["glitch"].update(intensity=[0.5, -1]), "transitions.glitch.intensity"),
    (lambda k: k["glitch"].update(intensity=[0.5, float("inf")]), "transitions.glitch.intensity"),
    (lambda k: k["glitch"].update(intensity=[2.5]), "transitions.glitch.intensity"),             # Q = 256/(256-124 I) is defined only up to 2.06
    (lambda k: k["glitch"].update(lead=4), "transitions.glitch.lead"),
    (lambda k: k["glitch"].update(lead=-1), "transitions.glitch.lead"),
    (lambda k: k["bloom"].update(threshold=256), "transitions.bloom.threshold"),
    (lambda k: k["bloom"].update(sigma=2000), "transitions.bloom.sigma"),
    (lambda k: k["bloom"].update(opacity=1.5), "transitions.bloom.opacity"),
    (lambda k: k["zoom_blur"].update(copies=1), "transitions.zoom_blur.copies"),
    (lambda k: k["zoom_blur"].update(copies=32768), "transitions.zoom_blur.copies"),
    (lambda k: k["zoom_blur"].update(spread=20), "transitions.zoom_blur.spread"),
    (lambda k: k["zoom_blur"].update(shift_px=5000), "transitions.zoom_blur.shift_px"),
    (lambda k: k["blur_to_card"].update(darken=2), "transitions.blur_to_card.darken"),
    (lambda k: k["blur_to_card"].update(sigma=-1), "transitions.blur_to_card.sigma"),
    (lambda k: k["dip"].update(intensity=[1.5]), "transitions.dip.intensity"),
])
def test_a_default_outside_a_bound_is_refused_and_names_it(mutate, field):
    err = refused(_edl.check_transition_config, config_with(mutate))
    assert (err.code, err.field) == ("bad_transition_config", field)


def test_a_default_inside_a_bound_but_far_from_the_usual_is_accepted():
    _edl.check_transition_config(config_with(lambda k: (k["glitch"].update(intensity=[1.9] * 9, lead=9), k["zoom_blur"].update(copies=32767), k["bloom"].update(threshold=0))))


# ---------------------------------------------------------------- how a row becomes frames

def resolve(rows, edl=None, entries=(), beats=None):
    return _edl.resolve_transitions(edl or synthetic_edl(), beats or beats_of(rows), list(entries), DATA)


def test_a_word_that_opens_a_kept_range_is_the_cut_and_the_frames_surround_it():
    rows, dropped = resolve([tr("t1", "glitch", word=10)])         # word 10 is spoken from 5.1 s: the first word of range 1, which starts at output frame 150
    assert dropped == []
    (r,) = rows
    assert (r["kind"], r["anchor"], r["start_frame"], r["end_frame"]) == ("glitch", "cut", 149, 152)
    assert r["frames"] == [[149, 0.6], [150, 1.0], [151, 0.6]]


def test_a_word_inside_a_shot_is_its_own_first_frame_and_a_second_word_of_a_range_is_not_a_cut():
    rows, _ = resolve([tr("t1", "bloom", word=3), tr("t2", "dip", word=11)])
    by = {r["id"]: r for r in rows}
    assert by["t1"]["anchor"] == "word" and by["t1"]["frames"][1][0] == 48          # 1.6 s
    assert by["t2"]["anchor"] == "word" and by["t2"]["frames"][1][0] == 168         # word 11 is the second word of range 1: 5.6 s


def test_the_frames_follow_the_kinds_defaults_and_blur_to_card_carries_the_themes_background():
    for kind, cfg in DATA["transitions"]["kinds"].items():
        (r,), _ = resolve([tr("t1", kind, word=3)])
        assert [v for _, v in r["frames"]] == cfg["intensity"] and r["frames"][cfg["lead"]][0] == 48
        assert ("color" in r) == (kind == "blur_to_card") and (r.get("color") in (None, DATA["theme"]["colors"]["bg"]))


def test_a_transition_at_the_start_and_at_the_end_is_cut_to_the_video():
    first, _ = resolve([tr("t1", "dip", word=0)], beats=None)               # word 0 starts at frame 3: the lead frame is 2, inside the video
    assert first[0]["frames"][0][0] == 2
    edl = synthetic_edl()
    edl["words"][0].update(start=0.0, end=0.2)
    (head,), _ = resolve([tr("t1", "dip", word=0)], edl=edl)
    assert head["frames"] == [[0, 1.0], [1, 0.6]] and head["start_frame"] == 0              # frame -1 does not exist
    end = _edl.resolve_transitions(edl, beats_of([tr("t1", "dip", word=27)]), [], DATA)[0][0]
    assert end["frames"][-1][0] <= edl["out_frames"] - 1


def custom_edl(words, frames=150):
    edl = synthetic_edl([[0, frames]])
    edl["words"] = [{"index": i, "text": "w%d" % i, "start": s, "end": e} for i, (s, e) in enumerate(words)]
    return edl


@pytest.mark.parametrize("x,starts_at", [(0.4, 60), (0.5, 59), (0.6, 59)])
def test_the_lead_frame_is_dropped_only_when_it_is_inside_a_word(x, starts_at):
    """The word before ends `x` frames before the anchor frame 60: its half-frame margin keeps the frame it ends on out of it, so the lead frame 59 is inside
    only when x is under half a frame."""
    edl = custom_edl([(0.1, (60 - x) / FPS), (2.0, 2.3)])
    (r,), _ = resolve([tr("t1", "glitch", word=1)], edl=edl)
    assert r["frames"][0][0] == starts_at and [f for f, _ in r["frames"]][-1] == 61
    assert len(r["frames"]) == (2 if starts_at == 60 else 3)


def test_an_anchor_inside_a_word_moves_to_the_first_frame_after_it_and_its_lead_is_dropped():
    """A word runs across the cut (4.667 s to 5.333 s) and the word that opens range 1 comes after it, so the cut, frame 150, is inside a word: the anchor moves to
    frame 160, the first that is not inside it (5.333 s), and the lead frame 159 (inside it too) is dropped from the front."""
    edl = custom_edl([(0.1, 0.4), (4.667, 5.333), (5.4, 5.7)])
    edl["kept"], edl["out_frames"] = [[0, 150], [200, 350]], 300
    (r,), _ = resolve([tr("t1", "glitch", word=2)], edl=edl)
    assert r["anchor"] == "cut" and r["frames"] == [[160, 1.0], [161, 0.6]] and (r["start_frame"], r["end_frame"]) == (160, 162)


def test_two_transitions_that_meet_keep_the_earlier_and_drop_the_later_with_a_reason():
    edl = custom_edl([(0.1, 0.4), (1.6, 1.64), (1.65, 1.9)])         # frames 48 and 50: the second's lead frame 49 is before the first's last frame
    rows, dropped = resolve([tr("t1", "glitch", word=1), tr("t2", "dip", word=2)], edl=edl)
    assert [r["id"] for r in rows] == ["t1"] and dropped == [{"id": "t2", "reason": "transition_overlap"}]
    rows, dropped = resolve([tr("t1", "glitch", word=1), tr("t2", "dip", word=2)], edl=custom_edl([(0.1, 0.4), (1.6, 1.64), (2.0, 2.2)]))
    assert [r["id"] for r in rows] == ["t1", "t2"] and dropped == []


def test_rows_are_resolved_in_id_order_and_listed_by_first_frame():
    rows, _ = resolve([tr("t10", "dip", word=3), tr("t2", "dip", word=20)])
    assert [r["id"] for r in rows] == ["t10", "t2"]


def test_a_beat_anchor_is_the_entrys_first_frame_a_dropped_beat_drops_its_row():
    edl = synthetic_edl()
    one = beats_of([tr("t1", "glitch", beat="b1")], overlays=[entry("b1", "keyword", {"text": "word3"}, 3, 4)])
    tl = _edl.resolve_timeline(edl, one, VOCAB, DATA)
    (e,) = tl["beats"]
    (r,) = tl["transitions"]
    assert (r["anchor"], r["frames"][1][0]) == ("beat", e["start_frame"]) and tl["effects_dropped"] == []
    same = beats_of([tr("t1", "glitch", beat="b1")], overlays=[entry("b1", "keyword", {"text": "word3"}, 3, 4), entry("b2", "keyword", {"text": "word3"}, 3, 4)])
    tl = _edl.resolve_timeline(edl, same, VOCAB, DATA)
    assert tl["dropped"] == ["b1"] and "transitions" not in tl
    assert tl["effects_dropped"] == [{"id": "t1", "reason": "transition_beat_dropped"}]


def cutaway_timeline(kind, transition_rows=None):
    edl = synthetic_edl()
    layout = entry("b1", "cutaway", {"asset": "s1", "label": "x"}, 3, 5)
    beats = beats_of(transition_rows if transition_rows is not None else [tr("t1", kind, beat="b1")], layouts=[layout])
    beats["slots"] = [{"slot": "s1", "beat": 1, "param": "asset", "type": "image", "description": "a picture"}]
    return _edl.resolve_timeline(edl, beats, VOCAB, DATA)


def test_an_ffmpeg_kind_on_a_cutaway_beat_makes_the_page_draw_a_cut_and_a_page_kind_is_the_pages_own():
    for kind in _edl.FFMPEG_TRANSITIONS:
        tl = cutaway_timeline(kind)
        assert tl["beats"][0]["transition"] == "cut" and tl["transitions"][0]["kind"] == kind
    for kind in _edl.PAGE_TRANSITIONS:
        tl = cutaway_timeline(kind)
        assert tl["beats"][0]["transition"] == kind
        (r,) = tl["transitions"]
        assert r["frames"] == [] and r["start_frame"] == r["end_frame"] == tl["beats"][0]["start_frame"]
    assert "transition" not in cutaway_timeline(None, [])["beats"][0]                      # no row: the theme's own look


def test_a_dropped_ffmpeg_row_leaves_the_cutaway_look_alone():
    edl = custom_edl([(0.1, 0.4), (1.6, 1.64), (1.65, 1.9)])
    layout = entry("b1", "cutaway", {"asset": "s1", "label": "x"}, 2, 2)
    entries = [dict(layout, preset="cutaway", kind="layout", start_frame=50, end_frame=80)]
    rows, dropped = _edl.resolve_transitions(edl, beats_of([tr("t1", "glitch", word=1), tr("t2", "dip", beat="b1")]), entries, DATA)
    assert [r["id"] for r in rows] == ["t1"] and dropped == [{"id": "t2", "reason": "transition_overlap"}] and "transition" not in entries[0]


def test_a_timeline_with_no_transition_has_no_key_and_is_what_it_always_was():
    edl = synthetic_edl()
    plain = _edl.resolve_timeline(edl, beats_of(), VOCAB, DATA)
    empty = _edl.resolve_timeline(edl, beats_of([]), VOCAB, DATA)
    assert "transitions" not in plain and json.dumps(plain, sort_keys=True) == json.dumps(empty, sort_keys=True)
    assert set(plain) == {"captions", "beats", "dropped", "punches", "grades", "echoes", "effects_dropped"}
    assert _edl.resolve_transitions(edl, beats_of(), [], DATA) == ([], [])


def test_the_effects_dropped_list_carries_the_transitions_rows_sorted_by_id():
    edl = custom_edl([(0.1, 0.4), (1.6, 1.64), (1.65, 1.9)])
    edl["captions"]["chunks"] = [[0, 2]]
    tl = _edl.resolve_timeline(edl, beats_of([tr("t1", "glitch", word=1), tr("t2", "dip", word=2)]), VOCAB, DATA)
    assert tl["effects_dropped"] == [{"id": "t2", "reason": "transition_overlap"}]


# ---------------------------------------------------------------- what the compose is given, and what the render answers

def test_the_compose_plan_carries_the_ffmpeg_rows_with_their_numbers_and_never_the_page_kinds():
    plan = _render.compose_plan(DATA, synthetic_edl(), {"beats": [], "captions": [], "dropped": [], "punches": [], "grades": [],
                                                       "transitions": [{"id": "t1", "kind": "bloom", "start_frame": 47, "end_frame": 50, "frames": [[47, 0.6], [48, 1.0], [49, 0.6]], "anchor": "word"},
                                                                       {"id": "t2", "kind": "slide", "start_frame": 80, "end_frame": 80, "frames": [], "anchor": "beat"}]}, {}, {}, "/in/rec")
    assert [t["id"] for t in plan["transitions"]] == ["t1"] and plan["transitions"][0]["params"] == DATA["transitions"]["kinds"]["bloom"]
    none = _render.compose_plan(DATA, synthetic_edl(), {"beats": [], "captions": [], "dropped": [], "punches": [], "grades": []}, {}, {}, "/in/rec")
    assert "transitions" not in none


def test_the_render_answer_names_each_transition_drawn_and_only_when_there_is_one():
    assert _render._transition_summary({}) == {} and _render._transition_summary({"transitions": []}) == {}
    row = {"id": "t1", "kind": "dip", "start_frame": 47, "end_frame": 50, "frames": [[47, 0.6]], "anchor": "word"}
    assert _render._transition_summary({"transitions": [row]}) == {"transitions_drawn": [{"id": "t1", "kind": "dip", "start_frame": 47, "end_frame": 50}]}
