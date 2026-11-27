"""The edit kind `transition` of the caption review (runtime/captions.py, package P1b): a glitch, bloom, zoom blur, blur to card or dip at a join, or a slide or
zoom on a cutaway beat, kept in the review by origin word or by beat number, removed by id, and the way they reach beats.json (runtime/step_media.py). Pure but
for the step tests, which run the media step over the kit's fake engine. The words are the fictional ones of media_kit.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_captions_transitions.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import (flag, media, open_items, ops, run_task, step_media, to_review, transcript, work_file, world)  # noqa: F401  (world is a fixture)

cap = st.load("captions")
REPO = Path(__file__).resolve().parents[2]


def fresh():
    return cap.start_edited(transcript()), cap.new_review()


def word(kind, i):
    return {"op": "transition", "kind": kind, "word": i}


def beat(kind, n):
    return {"op": "transition", "kind": kind, "beat": n}


def apply(edited, review, edits):
    return cap.apply_edits(edited, review, edits, revision=review["revision"], proposals={}, beats={1, 2, 3}, slots=set())


def refusal(edited, review, edits):
    with pytest.raises(cap.CaptionError) as caught:
        apply(edited, review, edits)
    return caught.value


def test_a_transition_is_added_by_word_and_by_beat_and_removed():
    edited, review = fresh()
    _, one, counts = apply(edited, review, [word("glitch", 4), beat("slide", 2)])
    assert one["transitions"] == [{"id": "t1", "kind": "glitch", "word": 4}, {"id": "t2", "kind": "slide", "beat": 2}]
    assert one["revision"] == review["revision"] + 1 and counts == {"edited": 0, "split": 0, "merged": 0, "deleted": 0}
    _, gone, _ = apply(edited, one, [{"op": "transition", "id": "t1", "remove": True}])
    assert [t["id"] for t in gone["transitions"]] == ["t2"]
    _, again, _ = apply(edited, gone, [word("dip", 0)])
    assert [t["id"] for t in again["transitions"]] == ["t1", "t2"]                  # the first free number is used again
    assert cap.view(edited, one, {}, {}, {})["counts"]["transitions"] == 2
    assert cap.check_review(one)["transitions"] == one["transitions"]


def test_a_word_is_stored_in_origin_numbering_and_follows_the_edit():
    edited, review = fresh()
    edited, review, _ = apply(edited, review, [{"op": "delete", "index": 0}])        # edited word 3 is now origin word 4
    edited, review, _ = apply(edited, review, [word("bloom", 3)])
    assert review["transitions"] == [{"id": "t1", "kind": "bloom", "word": 4}]
    edited, review, _ = apply(edited, review, [{"op": "split", "index": 1, "parts": ["to", "the"]}])      # the words before it grow by one
    [row] = cap.view(edited, review, {}, {}, {})["transitions"]
    assert (row["word"], row["lost"]) == (4, False)      # origin word 4: edited word 3 before the split, 4 after it
    placed, lost = cap.transitions_current(review, edited, set(range(20)), {})
    assert lost == [] and placed == [{"id": "t1", "kind": "bloom", "word": 4}]
    placed, lost = cap.transitions_current(review, edited, {0, 1, 2}, {})
    assert placed == [] and lost == ["t1"]


@pytest.mark.parametrize("edit, code", [
    (word("spin", 1), "unknown_transition"),
    ({"op": "transition", "id": "t9", "remove": True}, "unknown_transition"),
    (word("glitch", 99), "transition_words"),
    (word("glitch", -1), "transition_words"),
    (word("glitch", "1"), "transition_words"),
    (word("slide", 1), "transition_needs_beat"),
    (word("zoom", 1), "transition_needs_beat"),
    (beat("slide", 9), "unknown_beat"),
    (beat("slide", 1003), "unknown_beat"),
    (beat("slide", "1"), "unknown_beat"),
    ({"op": "transition", "kind": "glitch"}, "bad_edit"),
    ({"op": "transition", "kind": "glitch", "word": 1, "beat": 1}, "bad_edit"),
    ({"op": "transition", "id": "t1", "remove": False}, "bad_edit"),
])
def test_each_refusal_has_its_code(edit, code):
    edited, review = fresh()
    _, one, _ = apply(edited, review, [word("dip", 2)])
    assert refusal(edited, one, [edit]).code == code


def test_a_time_is_not_accepted_and_an_added_animation_is_a_beat():
    edited, review = fresh()
    assert refusal(edited, review, [dict(word("glitch", 1), seconds=2)]).code == "time_not_accepted"
    assert refusal(edited, review, [beat("slide", 1001)]).code == "unknown_beat"
    assert apply(edited, review, [beat("glitch", 1)])[1]["transitions"] == [{"id": "t1", "kind": "glitch", "beat": 1}]
    note = {"op": "animation", "block": "oh:caption", "params": {}, "word_from": 1, "word_to": 2}
    with_animation = cap.apply_edits(edited, review, [note, beat("slide", 1001)], revision=0, proposals={}, beats={1}, slots=set(),
                                     animate=lambda block, params, where: {"block": block, "preset": "caption", "params": params})[1]
    assert with_animation["transitions"] == [{"id": "t1", "kind": "slide", "beat": 1001}]


def test_one_transition_to_a_join_and_at_most_ninety_nine():
    edited, review = fresh()
    _, one, _ = apply(edited, review, [word("glitch", 3), beat("dip", 1)])
    assert refusal(edited, one, [word("bloom", 3)]).code == "transition_anchor_taken"
    assert refusal(edited, one, [beat("slide", 1)]).code == "transition_anchor_taken"
    assert refusal(edited, review, [word("glitch", 3), word("dip", 3)]).code == "transition_anchor_taken"
    rows = [{"id": "t%d" % k, "kind": "glitch", "word": k} for k in range(1, 100)]
    full = cap.check_review(dict(review, transitions=rows))
    assert cap.TRANSITIONS_MAX == 99 and len(full["transitions"]) == 99
    assert refusal(edited, full, [word("dip", 0)]).code == "too_many_transitions"
    many = [word("glitch", k % 8) for k in range(100)]
    assert refusal(edited, review, many).code in ("transition_anchor_taken", "too_many_transitions")


def test_a_merge_that_brings_two_transitions_into_one_word_is_refused_and_changes_nothing():
    edited, review = fresh()
    _, two, _ = apply(edited, review, [word("glitch", 2), word("dip", 3)])
    err = refusal(edited, two, [{"op": "merge", "from": 2, "to": 3}])
    assert (err.code, err.field) == ("transition_anchor_taken", "edits")
    _, fine, _ = apply(edited, two, [{"op": "merge", "from": 0, "to": 1}])
    assert len(fine["transitions"]) == 2


def test_an_old_review_reads_with_no_transitions_and_a_broken_one_is_refused():
    edited, review = fresh()
    old = {k: v for k, v in review.items() if k != "transitions"}
    assert cap.check_review(old)["transitions"] == []
    _, one, _ = apply(edited, old, [word("zoom_blur", 1)])
    assert one["transitions"][0]["kind"] == "zoom_blur"
    good = cap.check_review(one)
    first = good["transitions"][0]
    broken = [dict(first, id="t100"), dict(first, id="t0"), dict(first, id="e1"), dict(first, kind="spin"), dict(first, extra=1), dict(first, kind="slide"),
              dict(first, word=-1), {"id": "t1", "kind": "glitch"}, {"id": "t1", "kind": "glitch", "word": 1, "beat": 1},
              {"id": "t1", "kind": "slide", "beat": 0}, {"id": "t1", "kind": "slide", "beat": 100}, {"id": "t1", "kind": "slide", "beat": 1000},
              {"id": "t1", "kind": "slide", "beat": 1100}]
    for item in broken:
        with pytest.raises(cap.CaptionError) as caught:
            cap.check_review(dict(good, transitions=[item]))
        assert (caught.value.code, caught.value.field) == ("review_unreadable", "transitions"), item
    for bad in ({"transitions": [first, dict(first)]}, {"transitions": "x"}, {"transitions": [first] * 100}):
        with pytest.raises(cap.CaptionError) as caught:
            cap.check_review(dict(good, **bad))
        assert caught.value.code == "review_unreadable"


def test_the_view_lists_transitions_and_marks_the_words_that_open_a_shot():
    edited, review = fresh()
    proposal = {"kept": [[0, 30], [60, 120], [150, 210]], "fps": 30, "out_frames": 150,
                "words": [{"index": i, "start": round(0.5 + 0.4 * i, 3)} for i in range(12)]}
    shown = cap.view(edited, review, proposal, {"report": [{"beat": 1, "preset": "cutaway"}]}, {})
    opening = [w["index"] for w in shown["words"] if w["opens_shot"]]
    assert opening == [2, 7]      # frames 15 + 12 i: words 0-1 fall in the first range, 2-6 in the second, 7 on in the third
    assert not any(w["opens_shot"] for w in cap.view(edited, review, {}, {}, {})["words"])             # no kept ranges: no cut to name
    _, held, _ = apply(edited, review, [word("glitch", 3), beat("slide", 1), word("dip", 5)])
    gone, gone_review, _ = apply(edited, held, [{"op": "delete", "index": 5}])
    rows = cap.view(gone, gone_review, proposal, {"report": [{"beat": 1, "preset": "cutaway"}]}, {})["transitions"]
    assert rows == [{"id": "t1", "kind": "glitch", "word": 3, "lost": False}, {"id": "t2", "kind": "slide", "beat": 1, "lost": False},
                    {"id": "t3", "kind": "dip", "word": None, "lost": True}]
    _, dropped, _ = apply(edited, held, [{"op": "overlay", "beat": 1, "dropped": True}])
    assert cap.view(edited, dropped, proposal, {"report": [{"beat": 1, "preset": "cutaway"}]}, {})["transitions"][1]["lost"] is True


def test_the_constants_equal_the_renderers_own():
    source = (REPO / "providers" / "renderer" / "_edl.py").read_text(encoding="utf-8")
    for name in ("TRANSITION_KINDS", "PAGE_TRANSITIONS"):
        found = re.search(r"^%s = \((.*)\)(?: +#.*)?$" % name, source, re.M)
        if name == "TRANSITION_KINDS":      # the renderer builds it from the two lists
            ffmpeg = re.search(r"^FFMPEG_TRANSITIONS = \((.*?)\)", source, re.M).group(1)
            page = re.search(r"^PAGE_TRANSITIONS = \((.*?)\)", source, re.M).group(1)
            assert tuple(re.findall(r'"(\w+)"', ffmpeg + "," + page)) == cap.TRANSITION_KINDS
        else:
            assert tuple(re.findall(r'"(\w+)"', found.group(1))) == cap.PAGE_TRANSITIONS
    assert re.search(r"^TRANSITIONS_MAX = (\d+)", source, re.M).group(1) == str(cap.TRANSITIONS_MAX)
    assert re.search(r'^TRANSITION_ID = re.compile\(r"(.*)"\)$', source, re.M).group(1) == cap.TRANSITION_ID.pattern


# ---------------------------------------------------------------- the step: transitions reach beats.json

def with_entries(world, entries):
    """The fake engine's final `align` also writes the overlay entries the engine would have drawn."""
    engine = world["engine"]
    plain = engine._align

    def align(args):
        done = plain(args)
        if str(flag(args, "--out")).endswith("/beats.json"):
            path = Path(flag(args, "--out"))
            doc = json.loads(path.read_text())
            doc["overlays"] = entries
            path.write_text(json.dumps(doc))
        return done

    engine._align = align


def entry(ident, number, preset="cutaway"):
    return {"id": ident, "beat": number, "preset": preset, "params": {}, "word_from": 1, "word_to": 2, "score": 1.0}


def release(world, task):
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    return run_task(world, task)


def test_transitions_reach_beats_json_by_word_and_by_beat(world):
    task = to_review(world)
    review = cap.new_review()
    review["transitions"] = [{"id": "t1", "kind": "glitch", "word": 4}, {"id": "t2", "kind": "slide", "beat": 2}]
    work_file(world, "review.json").write_text(json.dumps(review))
    with_entries(world, [entry("b2", 2)])
    out = release(world, task)
    assert out["ok"] is True and out.get("stopped") == "deliver", out
    beats = json.loads(work_file(world, "beats.json").read_text())
    assert beats["transitions"] == [{"id": "t1", "kind": "glitch", "word": 4}, {"id": "t2", "kind": "slide", "beat": "b2"}]


def test_a_review_with_no_transition_leaves_beats_json_as_the_engine_wrote_it(world):
    task = to_review(world)
    assert release(world, task).get("stopped") == "deliver"
    assert "transitions" not in json.loads(work_file(world, "beats.json").read_text())


def test_a_transition_whose_word_is_not_live_stops_the_align_step_with_transition_lost(world):
    task = to_review(world)
    review = cap.new_review()
    review["transitions"] = [{"id": "t1", "kind": "dip", "word": 40}]
    work_file(world, "review.json").write_text(json.dumps(review))
    out = release(world, task)
    assert out["ok"] is False and "transition_lost" in json.dumps(out)


def test_a_transition_on_a_beat_the_engine_did_not_draw_or_the_person_dropped_is_lost(world):
    task = to_review(world)
    review = cap.new_review()
    review["transitions"] = [{"id": "t1", "kind": "slide", "beat": 2}]
    work_file(world, "review.json").write_text(json.dumps(review))
    out = release(world, task)
    assert out["ok"] is False and "transition_lost" in json.dumps(out)
    kept, lost = cap.transitions_current(review, cap.start_edited(transcript()), set(range(12)), {"overlays": [entry("b2", 2)]})
    assert kept == [{"id": "t1", "kind": "slide", "beat": "b2"}] and lost == []
    kept, lost = cap.transitions_current(review, cap.start_edited(transcript()), set(range(12)), {"layouts": [entry("b3", 3)]})
    assert kept == [] and lost == ["t1"]


def test_the_runtime_keeps_the_renders_dropped_transitions_as_closed_rows():
    got = step_media._effects_dropped({"effects_dropped": [{"id": "t1", "reason": "transition_overlap"}, {"id": "t12", "reason": "transition_beat_dropped"},
                                                          {"id": "t3", "reason": "punch_short"}, {"id": "t100", "reason": "transition_overlap"},
                                                          {"id": "t4", "reason": "because"}]})
    assert got == [{"id": "t1", "reason": "transition_overlap"}, {"id": "t12", "reason": "transition_beat_dropped"}, {"id": "t3", "reason": "punch_short"}]
    left = step_media._left_out({}, {}, {}, got[:2])
    assert [(r["id"], r["kind"], r["reason"]) for r in left] == [("t1", "effect", "transition_overlap"), ("t12", "effect", "transition_beat_dropped")]
