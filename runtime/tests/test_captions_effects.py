"""The edit kind `effect` of the caption review (runtime/captions.py, package V9a-3): a punch, flash, dip, mono or tint over a word range, kept in the
review by origin words, the script's punches the person dropped, and the way both reach beats.json (runtime/step_media.py). Pure but for the step test,
which runs the media step over the kit's fake engine. The words are the fictional ones of media_kit.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_captions_effects.py
"""
from __future__ import annotations

import copy
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


def effect(kind, first, last):
    return {"op": "effect", "kind": kind, "word_from": first, "word_to": last}


def apply(edited, review, edits, *, punches=None, revision=None):
    return cap.apply_edits(edited, review, edits, revision=review["revision"] if revision is None else revision, proposals={}, beats={1, 2, 3},
                           slots=set(), punches=punches)


def refusal(edited, review, edits, **kw):
    with pytest.raises(cap.CaptionError) as caught:
        apply(edited, review, edits, **kw)
    return caught.value


def test_an_effect_is_added_and_removed():
    edited, review = fresh()
    _, one, counts = apply(edited, review, [effect("flash", 1, 2), effect("mono", 4, 6)])
    assert one["effects"] == [{"id": "e1", "kind": "flash", "from": 1, "to": 2}, {"id": "e2", "kind": "mono", "from": 4, "to": 6}]
    assert one["revision"] == review["revision"] + 1 and counts == {"edited": 0, "split": 0, "merged": 0, "deleted": 0}
    _, gone, _ = apply(edited, one, [{"op": "effect", "id": "e1", "remove": True}])
    assert [e["id"] for e in gone["effects"]] == ["e2"]
    _, again, _ = apply(edited, gone, [effect("tint", 0, 0)])
    assert sorted(e["id"] for e in again["effects"]) == ["e1", "e2"]                 # the first free number is used again
    assert refusal(edited, one, [{"op": "effect", "id": "e5", "remove": True}]).code == "unknown_effect"
    assert refusal(edited, one, [effect("spin", 1, 2)]).code == "unknown_effect"
    for bad in (effect("flash", 3, 2), effect("flash", -1, 2), effect("flash", 1, 99), dict(effect("flash", 1, 2), word_from="1")):
        assert refusal(edited, review, [bad]).code == "effect_words"
    for bad in (dict(effect("flash", 1, 2), start=1.5), dict(effect("flash", 1, 2), seconds=2), {"op": "effect", "kind": "flash"},
                {"op": "effect", "id": "e1", "remove": False}, {"op": "effect", "id": "e1", "remove": True, "kind": "flash"}):
        assert refusal(edited, one, [bad]).code in ("time_not_accepted", "bad_edit", "unknown_field")
    assert cap.view(edited, one, {}, {}, {})["counts"]["effects"] == 2


def test_effects_go_up_to_the_ceiling():      # T7
    edited, review = fresh()
    top = [effect("punch", 0, 0) for _ in range(99)]
    _, full, _ = apply(edited, review, top)
    assert [e["id"] for e in full["effects"]] == ["e%d" % k for k in range(1, 100)]
    assert refusal(edited, full, [effect("punch", 7, 7)]).code == "too_many_effects"                      # the 100th, over two requests
    assert refusal(edited, review, top + [effect("punch", 7, 7)]).code == "too_many_effects"              # and in one request
    assert cap.EFFECTS_MAX == 99 and cap.ANIMATIONS_MAX == 99 and cap.BEATS_CEILING == 99 and cap.BEATS_MAX == 12      # the ceilings are 99 (video P0b); 12 is the usual count, a default


def test_overlapping_grades_are_refused():      # T8
    edited, review = fresh()
    _, one, _ = apply(edited, review, [effect("mono", 2, 4)])
    for kind in ("flash", "dip", "mono", "tint"):                                                # mono is a filter: every kind may share its words
        assert [e["kind"] for e in apply(edited, one, [effect(kind, 4, 5)])[1]["effects"]].count(kind) >= 1 and len(apply(edited, one, [effect(kind, 4, 5)])[1]["effects"]) == 2
    for first in ("flash", "dip", "tint"):
        _, over, _ = apply(edited, review, [effect(first, 2, 4)])
        for kind in ("flash", "dip", "tint"):
            assert refusal(edited, over, [effect(kind, 4, 5)]).code == "effect_overlap", (first, kind)
        assert len(apply(edited, over, [effect("mono", 4, 5)])[1]["effects"]) == 2               # over a colour-layer grade only mono passes
    _, ok, _ = apply(edited, one, [effect("punch", 3, 3), effect("tint", 5, 6)])                # a punch is no grade: it may share words
    assert len(ok["effects"]) == 3
    _, three, _ = apply(edited, review, [effect("flash", 1, 1), effect("dip", 3, 3), effect("flash", 6, 6)])
    assert len(three["effects"]) == 3                                                            # no count of flashes and dips
    _, four, _ = apply(edited, review, [effect("flash", 1, 1), effect("dip", 3, 3), effect("mono", 6, 7), effect("tint", 0, 0)])
    assert len(four["effects"]) == 4


def test_a_script_punch_is_dropped_and_kept_dropped():
    edited, review = fresh()
    _, one, _ = apply(edited, review, [{"op": "effect", "id": "p3", "remove": True}], punches={3, 5})
    assert one["dropped_punches"] == [3]
    _, two, _ = apply(edited, one, [{"op": "effect", "id": "p5", "remove": True}, effect("flash", 1, 1)], punches={3, 5})
    assert two["dropped_punches"] == [3, 5]
    _, same, _ = apply(edited, two, [{"op": "effect", "id": "p3", "remove": True}], punches={3, 5})        # dropping again changes nothing
    assert same["dropped_punches"] == [3, 5]
    _, after, _ = apply(edited, two, [{"op": "edit", "index": 0, "text": "Hello"}], punches={3, 5})
    assert after["dropped_punches"] == [3, 5]                                                                # an edit of the words keeps what was dropped
    assert refusal(edited, review, [{"op": "effect", "id": "p4", "remove": True}], punches={3, 5}).code == "unknown_effect"
    _, loose, _ = apply(edited, review, [{"op": "effect", "id": "p4", "remove": True}])                      # the caller gave no list: any beat number
    assert loose["dropped_punches"] == [4]
    assert refusal(edited, review, [{"op": "effect", "id": "p100", "remove": True}]).code == "unknown_effect"
    assert refusal(edited, review, [{"op": "effect", "id": "p0", "remove": True}]).code == "unknown_effect"
    assert cap.check_review(two)["dropped_punches"] == [3, 5]
    view = cap.view(edited, two, {}, {"threshold": 0.6, "report": [], "slots": [], "punches": [{"beat": 3, "word_from": 2, "word_to": 3, "score": 1.0},
                                                                                              {"beat": 4, "word_from": 5, "word_to": 6, "score": 1.0}]}, {})
    assert [(p["id"], p["word_from"], p["word_to"], p["dropped"]) for p in view["punches"]] == [("p3", 2, 3, True), ("p4", 5, 6, False)]


def test_an_old_review_reads_with_no_effects():
    edited, review = fresh()
    old = {k: v for k, v in review.items() if k not in ("effects", "dropped_punches")}
    read = cap.check_review(old)
    assert read["effects"] == [] and read["dropped_punches"] == []
    _, one, _ = apply(edited, old, [effect("dip", 1, 2)])
    assert one["effects"][0]["kind"] == "dip"
    good = cap.check_review(one)
    many = [dict(good["effects"][0], id="e%d" % k) for k in range(7, 41)]                      # T10: a stored review with e7..e40 reads
    assert len(cap.check_review(dict(good, effects=many))["effects"]) == 34
    broken = [dict(good["effects"][0], id="e100"), dict(good["effects"][0], id="e0"), dict(good["effects"][0], id="e01"), dict(good["effects"][0], id="a1"), dict(good["effects"][0], kind="spin"), dict(good["effects"][0], extra=1),
              dict(good["effects"][0], **{"from": 5, "to": 2}), dict(good["effects"][0], **{"from": -1})]
    for one_item in broken:
        with pytest.raises(cap.CaptionError) as caught:
            cap.check_review(dict(good, effects=[one_item]))
        assert (caught.value.code, caught.value.field) == ("review_unreadable", "effects"), one_item
    for bad in ({"effects": [good["effects"][0], dict(good["effects"][0])]}, {"effects": "x"}, {"dropped_punches": [0]}, {"dropped_punches": [3, 3]},
                {"dropped_punches": [100]}, {"dropped_punches": ["3"]}, {"dropped_punches": list(range(1, 101))}):
        with pytest.raises(cap.CaptionError) as caught:
            cap.check_review(dict(good, **bad))
        assert caught.value.code == "review_unreadable"


def test_an_effect_keeps_its_words_when_the_words_before_it_are_split_and_is_lost_when_they_are_cut():
    edited, review = fresh()
    edited, review, _ = apply(edited, review, [effect("tint", 5, 6)])
    edited, review, _ = apply(edited, review, [{"op": "split", "index": 1, "parts": ["to", "the"]}])
    [row] = cap.view(edited, review, {}, {}, {})["effects"]
    assert (row["word_from"], row["word_to"], row["lost"]) == (6, 7, False)
    placed, gone = cap.effects_current(review, edited, set(range(12)))
    assert gone == [] and placed == [{"id": "e1", "kind": "tint", "word_from": 6, "word_to": 7}]
    placed, gone = cap.effects_current(review, edited, {0, 1, 2})
    assert placed == [] and gone == ["e1"]
    cut, cut_review, _ = apply(edited, review, [{"op": "delete", "index": 6}, {"op": "delete", "index": 7}])
    assert cap.view(cut, cut_review, {}, {}, {})["effects"][0]["lost"] is True


def test_the_constants_equal_the_renderers_own():
    source = (REPO / "providers" / "renderer" / "_edl.py").read_text(encoding="utf-8")
    kinds = re.search(r"^EFFECT_KINDS = \((.*)\)$", source, re.M).group(1)
    assert tuple(re.findall(r'"(\w+)"', kinds)) == cap.EFFECT_KINDS
    assert re.search(r"^EFFECTS_MAX = (\d+)", source, re.M).group(1) == str(cap.EFFECTS_MAX)
    assert re.search(r"^TRANSITIONS_MAX = (\d+)", source, re.M).group(1) == str(cap.TRANSITIONS_MAX)                # P1a: the closed bound the left-out list reads
    assert re.search(r"^OVERLAY_GRADES = \((.*?)\)", source, re.M).group(1).replace('"', "").replace(" ", "").split(",") == list(cap.OVERLAY_GRADES)
    assert "FLASHES_MAX" not in source and not hasattr(cap, "FLASHES_MAX")                                  # T9: the flash count is gone from both
    assert re.search(r'^EFFECT_ID = re.compile\(r"(.*)"\)$', source, re.M).group(1) == cap.EFFECT_ID.pattern


# ---------------------------------------------------------------- the step: effects reach beats.json

def aligned_with(world, rows):
    """The fake engine's final `align` also writes the script's punches the engine would have found."""
    engine = world["engine"]
    plain = engine._align

    def align(args):
        done = plain(args)
        if str(flag(args, "--out")).endswith("/beats.json"):
            path = Path(flag(args, "--out"))
            doc = json.loads(path.read_text())
            doc["punches"] = copy.deepcopy(rows)
            path.write_text(json.dumps(doc))
        return done

    engine._align = align


def test_effects_reach_beats_json(world):
    task = to_review(world)
    review = cap.new_review()
    review["effects"] = [{"id": "e1", "kind": "flash", "from": 2, "to": 2}, {"id": "e2", "kind": "mono", "from": 4, "to": 5}]
    review["dropped_punches"] = [3]
    work_file(world, "review.json").write_text(json.dumps(review))
    aligned_with(world, [{"beat": 2, "word_from": 1, "word_to": 2, "score": 0.9}, {"beat": 3, "word_from": 5, "word_to": 6, "score": 1.0}])
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    out = run_task(world, task)
    assert out["ok"] is True and out.get("stopped") == "deliver", out
    beats = json.loads(work_file(world, "beats.json").read_text())
    assert beats["effects"] == [{"id": "e1", "kind": "flash", "word_from": 2, "word_to": 2}, {"id": "e2", "kind": "mono", "word_from": 4, "word_to": 5}]
    assert beats["punches"] == [{"beat": 2, "word_from": 1, "word_to": 2, "score": 0.9}]         # the script's punch of beat 3 was dropped at review


def test_a_review_with_no_effect_leaves_beats_json_as_the_engine_wrote_it(world):
    task = to_review(world)
    aligned_with(world, [])
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    assert run_task(world, task).get("stopped") == "deliver"
    beats = json.loads(work_file(world, "beats.json").read_text())
    assert "effects" not in beats and beats["punches"] == []


def test_every_punch_dropped_removes_the_key_and_an_effect_with_no_live_word_stops_the_step(world):
    task = to_review(world)
    review = cap.new_review()
    review["dropped_punches"] = [2]
    work_file(world, "review.json").write_text(json.dumps(review))
    aligned_with(world, [{"beat": 2, "word_from": 1, "word_to": 2, "score": 0.9}])
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    assert run_task(world, task).get("stopped") == "deliver"
    assert "punches" not in json.loads(work_file(world, "beats.json").read_text())


def test_an_effect_with_no_live_word_stops_the_align_step_with_effect_lost(world):
    task = to_review(world)
    review = cap.new_review()
    review["effects"] = [{"id": "e1", "kind": "dip", "from": 40, "to": 41}]
    work_file(world, "review.json").write_text(json.dumps(review))
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    out = run_task(world, task)
    assert out["ok"] is False and "effect_lost" in json.dumps(out)


# ---------------------------------------------------------------- review of PR 807

def test_a_merge_that_would_bring_two_grades_into_one_word_is_refused_and_changes_nothing():
    edited, review = fresh()
    _, two, _ = apply(edited, review, [effect("flash", 2, 2), effect("tint", 3, 3)])
    err = refusal(edited, two, [{"op": "merge", "from": 2, "to": 3}])
    assert (err.code, err.field) == ("effect_overlap", "edits")
    _, fine, _ = apply(edited, two, [{"op": "merge", "from": 0, "to": 1}])               # a merge elsewhere is fine
    assert [e["kind"] for e in fine["effects"]] == ["flash", "tint"]
    _, punches, _ = apply(edited, review, [effect("punch", 2, 2), effect("mono", 3, 3)])      # a punch may share a word with a grade
    _, merged, _ = apply(edited, punches, [{"op": "merge", "from": 2, "to": 3}])
    assert len(merged["effects"]) == 2
    _, grades, _ = apply(edited, review, [effect("mono", 2, 2), effect("tint", 3, 3)])               # a merge that brings a mono and a tint into one word passes
    _, both, _ = apply(edited, grades, [{"op": "merge", "from": 2, "to": 3}])
    assert len(both["effects"]) == 2


def test_the_runtime_reads_the_renders_dropped_effects_as_closed_rows():
    got = step_media._effects_dropped({"effects_dropped": [{"id": "e1", "reason": "punch_short"}, {"id": "p2", "reason": "grade_overlap"}, {"id": "x1", "reason": "punch_short"},
                                                          {"id": "e3", "reason": "because"}, "e4", {"id": "e5"}]})
    assert got == [{"id": "e1", "reason": "punch_short"}, {"id": "p2", "reason": "grade_overlap"}]
    assert step_media._effects_dropped({}) == [] and step_media._effects_dropped({"effects_dropped": "x"}) == []


def test_the_renders_dropped_effects_are_not_cut_and_the_left_out_bound_follows_the_ceilings():      # T10
    rows = [{"id": "e%d" % k, "reason": "grade_short"} for k in range(1, 21)]
    assert step_media._effects_dropped({"effects_dropped": rows}) == rows                                  # 20 rows: none cut at 12
    dd = st.load("deliver_document")
    assert dd.LEFT_OUT_MAX == cap.EFFECTS_MAX + cap.TRANSITIONS_MAX + 2 * cap.BEATS_CEILING == 396
    left = step_media._left_out({}, {}, {}, step_media._effects_dropped({"effects_dropped": rows}))
    assert len(left) == 20 and {r["kind"] for r in left} == {"effect"}                                      # all 20 reach the left-out rows
    ok = [{"id": "e%03d" % k, "kind": "effect", "reason": "grade_short"} for k in range(396)]
    dd._check_left_out({"left_out": ok})                                                                    # 396 rows are accepted
    with pytest.raises(ValueError):
        dd._check_left_out({"left_out": ok + [{"id": "e999", "kind": "effect", "reason": "grade_short"}]})   # 397 are refused
