"""The zoom level changes no more often than `_media.ZOOM_SPACING_SECONDS` (V9g): `alternate` keeps the level at a cut too close to the last change and
never gives a range shorter than the spacing a level of its own; a punch that ends just before a cut is held to the cut, and one that would start too soon
after a change of level is dropped (`punch_spacing`). Offline, on synthetic edit lists; every name is fictional."""
from __future__ import annotations

import renderer_kit as K  # noqa: F401  (puts the renderer on the path)
import _edl
import _media
from _vocab import load_data

DATA = load_data()
FPS = 30
ALT = {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}


def kept_of(seconds) -> list:
    """Kept ranges (source frames, 10 frames cut between two) of the given output lengths in seconds."""
    out, pos = [], 0
    for s in seconds:
        n = int(round(s * FPS))
        out.append([pos, pos + n])
        pos += n + 10
    return out


def levels(seconds, zoom=ALT) -> list:
    kept = kept_of(seconds)
    return [_media.zoom_levels(zoom, k, b - a, FPS, kept)[0] for k, (a, b) in enumerate(kept)]


def test_the_spacing_is_named():
    assert _media.ZOOM_SPACING_SECONDS == 3.0


def test_a_two_second_range_never_gets_its_own_level_and_the_alternation_goes_on_after_it():
    # the ranges of a reviewed reel: 4.17 s, 8.33, 5.17, 9.27, 5.77, a 2.07 s range, then 10.77 s. Before V9g the 2.07 s range was zoomed in and the
    # level flipped back 2 s later; now it keeps the level before it and the next range flips (7.8 s after the last change)
    assert levels([4.17, 8.33, 5.17, 9.27, 5.77, 2.07, 10.77]) == [1.0, 1.1, 1.0, 1.1, 1.0, 1.0, 1.1]
    assert levels([4.0, 8.0, 2.0, 6.0]) == [1.0, 1.1, 1.1, 1.0]          # a short range after a zoomed one stays zoomed


def test_a_cut_too_soon_after_the_last_change_keeps_the_level():
    assert levels([2.0, 4.0, 4.0]) == [1.0, 1.0, 1.1]          # the first cut is 2 s after the start: no flip; the second, 6 s after, flips
    assert levels([5.0, 4.0, 1.0, 1.0, 4.0]) == [1.0, 1.1, 1.1, 1.1, 1.0]


def test_no_alternation_zooms_nothing_and_the_old_signature_keeps_its_rule():
    none = dict(ALT, mode="none")
    assert levels([2.0, 4.0, 4.0], none) == [1.0, 1.0, 1.0]
    assert _media.zoom_levels(ALT, 1, 60, FPS) == (1.1, 1.1)           # without the list: every second range, as before V9g


def edl_of(seconds, words=None) -> dict:
    kept = kept_of(seconds)
    frames = sum(b - a for a, b in kept)
    n = words if words is not None else int(frames / FPS / 0.5)
    return {"schema_version": 2, "fps": FPS, "size": [1080, 1920], "kept": kept, "out_frames": frames,
            "words": [{"index": i, "text": "word%d" % i, "start": round(0.5 * i + 0.1, 3), "end": round(0.5 * i + 0.4, 3)} for i in range(n)],
            "captions": {"position": "bottom", "chunks": []}, "theme": {"colors": dict(DATA["theme"]["colors"]), "fonts": {}},
            "face_box": dict(DATA["face_box_default"]), "source": {"has_audio": True}, "zoom": dict(ALT)}


def test_the_face_of_each_range_is_drawn_at_the_same_levels_as_the_picture():
    edl = edl_of([4.17, 8.33, 5.17, 9.27, 5.77, 2.07, 10.77])
    anchor = _media.anchor_point(edl["face_box"], ALT["anchor_y"])
    for k, (first, last, box) in enumerate(_edl.range_faces(edl, DATA)):
        a, b = edl["kept"][k]
        z0, z1 = _media.zoom_levels(edl["zoom"], k, b - a, FPS, edl["kept"])
        assert box == _media.zoomed_box(edl["face_box"], z0, z1, anchor, 1080, 1920)
    assert _edl.range_faces(edl, DATA)[5][2] == _media.zoomed_box(edl["face_box"], 1.0, 1.0, anchor, 1080, 1920)      # the 2 s range: unzoomed


def punches(edl, *spans):
    beats = {"punches": [{"beat": i + 1, "word_from": a, "word_to": b} for i, (a, b) in enumerate(spans)]}
    return _edl.resolve_punches(edl, beats, DATA)


def test_a_punch_that_ends_just_before_a_cut_ends_on_the_cut():
    edl = edl_of([5.0, 10.0, 6.0])         # cuts at output frames 150 and 450; range 1 zoomed in from 150
    # words 24-29: 12.1 s to 14.9 s, frames 363-447, 3 frames (0.1 s) before the cut at 450: held to it, so the level changes once there
    (row,), dropped = punches(edl, (24, 29))
    assert (row["start_frame"], row["end_frame"]) == (363, 450) and dropped == []
    (row,), _ = punches(edl, (24, 27))     # ends at frame 417, 1.1 s before the cut: stays
    assert row["end_frame"] == 417


def test_a_punch_too_soon_after_a_change_of_level_is_dropped():
    edl = edl_of([5.0, 10.0, 6.0])
    rows, dropped = punches(edl, (11, 13))  # starts at 5.6 s, frame 168: 18 frames after the zoom in at 150
    assert rows == [] and dropped == [{"id": "p1", "reason": "punch_spacing"}]
    rows, dropped = punches(edl, (16, 18), (22, 24))      # the second starts 1.3 s after the first ends (a change of level too)
    assert [r["id"] for r in rows] == ["p1"] and dropped == [{"id": "p2", "reason": "punch_spacing"}]
