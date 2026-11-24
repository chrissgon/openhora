"""Beat edges snap to the cuts of the output timeline (V9g): an end just before a cut is held to the cut, a start just after a cut moves back to it,
never across the one-track rule and never past the video's end; the aside's grey and echo and the review's mono and tint follow. Offline, on a
synthetic edit list; every name is fictional."""
from __future__ import annotations

import renderer_kit as K
import _edl
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
FPS = 30
KEPT = [[0, 150], [200, 350], [400, 520]]          # output frames 0-149, 150-299 and 300-419: the cuts are at output frames 150 and 300


def synthetic_edl(kept=KEPT) -> dict:
    """An edit list with 28 words, one every half second (word i is spoken from 0.5 i + 0.1 to 0.5 i + 0.4 s of the output), over three kept ranges."""
    frames = sum(b - a for a, b in kept)
    words = [{"index": i, "text": "word%d" % i, "start": round(0.5 * i + 0.1, 3), "end": round(0.5 * i + 0.4, 3)} for i in range(28)]
    return {"schema_version": 2, "fps": FPS, "size": [1080, 1920], "kept": [list(r) for r in kept], "out_frames": frames, "words": words,
            "captions": {"position": "bottom", "chunks": [[i, i + 3] for i in range(0, 28, 4)]}, "theme": {"colors": dict(DATA["theme"]["colors"]), "fonts": {}},
            "face_box": dict(DATA["face_box_default"]), "source": {"has_audio": True},
            "zoom": {"mode": "none", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}}


def entry(beat, preset, first, last, **params):
    return {"id": "b%d" % beat, "beat": beat, "preset": preset, "params": params, "word_from": first, "word_to": last, "score": 1.0}


def beats_of(overlays=(), effects=()) -> dict:
    doc = {"schema_version": 1, "threshold": 0.6, "overlays": list(overlays), "layouts": [], "slots": [], "report": [], "unmatched": [], "fallbacks": []}
    if effects:
        doc["effects"] = list(effects)
    return doc


def resolve(beats, edl=None):
    return _edl.resolve_timeline(edl or synthetic_edl(), beats, VOCAB, DATA)


def span(timeline, ident):
    e = next(e for e in timeline["beats"] if e["id"] == ident)
    return e["start_frame"], e["end_frame"]


def test_the_windows_are_named_and_the_cuts_are_the_starts_of_the_kept_ranges_after_the_first():
    assert (_edl.SNAP_END_SECONDS, _edl.SNAP_START_SECONDS) == (0.5, 0.25)
    assert _edl.cut_frames(synthetic_edl()) == [150, 300]
    assert _edl.cut_frames(synthetic_edl([[0, 400]])) == []


def test_an_aside_that_ends_just_before_a_cut_is_held_to_the_cut_with_its_grey_and_its_echo():
    # words 5-8 and the tail: 2.6 s to 4.5 s, frames 78-135; the cut is 15 frames (0.5 s) later
    tl = resolve(beats_of([entry(1, "aside", 5, 8)]))
    e = tl["beats"][0]
    assert (e["start_frame"], e["end_frame"]) == (78, 150) and e["snapped_end"] is True and "snapped_start" not in e
    assert [(g["start_frame"], g["end_frame"]) for g in tl["grades"] if g["id"] == "b1"] == [(78, 150)]
    assert [(r["start_frame"], r["end_frame"]) for r in tl["echoes"]] == [(78, 150)]


def test_an_end_further_from_the_cut_than_the_window_stays():
    tl = resolve(beats_of([entry(1, "aside", 5, 7)]))          # ends at 120: 30 frames before the cut
    assert span(tl, "b1") == (78, 120) and "snapped_end" not in tl["beats"][0]


def test_a_start_just_after_a_cut_moves_back_to_it_with_its_grey():
    tl = resolve(beats_of([entry(1, "aside", 10, 13)]))         # word 10 starts at 5.1 s, frame 153: 3 frames after the cut at 150
    e = tl["beats"][0]
    assert e["start_frame"] == 150 and e["snapped_start"] is True
    assert min(g["start_frame"] for g in tl["grades"] if g["id"] == "b1") == 150
    assert tl["echoes"][0]["start_frame"] == 150


def test_a_start_further_after_the_cut_than_the_window_stays():
    tl = resolve(beats_of([entry(1, "aside", 11, 13)]))         # word 11 starts at 5.6 s, frame 168: 18 frames (0.6 s) after the cut
    assert span(tl, "b1")[0] == 168 and "snapped_start" not in tl["beats"][0]


def test_an_end_never_runs_past_the_next_beats_start():
    # the aside would end at 135 and snap to 150, but the number starts at 138 (word 9, 4.6 s): it ends there, the beats touch, none overlaps
    tl = resolve(beats_of([entry(1, "aside", 5, 8), entry(2, "number", 9, 12)]))
    assert span(tl, "b1") == (78, 138) and span(tl, "b2")[0] == 138
    assert [(g["start_frame"], g["end_frame"]) for g in tl["grades"] if g["id"] == "b1"] == [(78, 138)]


def test_a_start_moved_back_onto_a_cut_ends_the_beat_before_it_there():
    # the quote runs to 162 (word 9 plus its tail), the one-track rule ends it at 153 where the aside starts; the aside moves back to the cut
    # at 150 and the quote ends on the cut too: no frame of the quote is left after the cut
    tl = resolve(beats_of([entry(1, "quote", 6, 9), entry(2, "aside", 10, 13)]))
    assert span(tl, "b1")[1] == 150 and span(tl, "b2")[0] == 150
    starts = sorted(e["start_frame"] for e in tl["beats"])
    for a, b in zip(sorted(tl["beats"], key=lambda e: e["start_frame"]), sorted(tl["beats"], key=lambda e: e["start_frame"])[1:]):
        assert a["end_frame"] <= b["start_frame"]
    assert starts == [93, 150]


def test_a_start_does_not_move_when_it_would_leave_the_beat_before_with_no_frame():
    # a beat that starts after the cut and a beat that starts between the cut and it: moving the second back to the cut would swallow the first
    edl = synthetic_edl()
    beats = beats_of([entry(1, "number", 10, 10), entry(2, "aside", 11, 13)])
    edl["words"][10]["start"], edl["words"][10]["end"] = 5.02, 5.05         # frame 151, one frame after the cut
    edl["words"][11]["start"] = 5.12                                          # frame 154, inside the window too
    tl = resolve(beats, edl)
    assert span(tl, "b1")[0] == 150 and span(tl, "b2")[0] == 154 and span(tl, "b1")[1] == 154


def test_the_last_beat_ends_on_the_video_end_at_most():
    tl = resolve(beats_of([entry(1, "aside", 24, 27)]))          # past the last cut: nothing to snap to, the video's end bounds it
    s, e = span(tl, "b1")
    assert e <= synthetic_edl()["out_frames"] and "snapped_end" not in tl["beats"][0]


def test_a_review_mono_and_tint_follow_the_cuts_of_their_range():
    effects = [{"id": "e1", "kind": "mono", "word_from": 5, "word_to": 9}, {"id": "e2", "kind": "tint", "word_from": 10, "word_to": 12}]
    tl = resolve(beats_of(effects=effects))
    rows = {g["id"]: (g["start_frame"], g["end_frame"]) for g in tl["grades"]}
    assert rows["e1"] == (78, 150)                                # ended at 147 (word 9, 4.9 s), 3 frames before its range's end
    assert rows["e2"][0] == 150                                   # started at 153, 3 frames after its range's start
    flash = resolve(beats_of(effects=[{"id": "e3", "kind": "flash", "word_from": 10, "word_to": 10}]))
    assert flash["grades"][0]["start_frame"] == 153               # a flash sits on its word: it never moves


def test_with_no_cut_nothing_moves():
    edl = synthetic_edl([[0, 420]])
    tl = resolve(beats_of([entry(1, "aside", 5, 8)]), edl)
    assert span(tl, "b1") == (78, 135) and "snapped_end" not in tl["beats"][0]
