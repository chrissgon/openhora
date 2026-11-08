"""The edit kind `animation` of the caption review (runtime/captions.py, package V1b3, VD15): a catalogue block over a word range, stored as a review-only beat,
the check of its parameters handed in by the caller. Pure: no provider, no store, no file but the two committed ones a constant is compared with. The words
are the fictional ones of media_kit.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_captions_animation.py
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import transcript

cap = st.load("captions")
REPO = Path(__file__).resolve().parents[2]
ADD = {"op": "animation", "block": "oh:keyword", "params": {"text": "Every step counts"}, "word_from": 1, "word_to": 3}


def fresh():
    return cap.start_edited(transcript()), cap.new_review()


def animate(block, params, where):
    return {"block": block, "preset": "keyword", "params": dict(params)}


def apply(edited, review, edits, *, animate=animate, beats=(1, 2, 3), revision=None):
    return cap.apply_edits(edited, review, edits, revision=review["revision"] if revision is None else revision, proposals={}, beats=set(beats),
                           slots=set(), animate=animate)


def add_one(edited, review, **kw):
    return apply(edited, review, [dict(ADD)], **kw)


def refusal(edited, review, edits, **kw):
    with pytest.raises(cap.CaptionError) as caught:
        apply(edited, review, edits, **kw)
    return caught.value


def test_an_add_stores_one_item_with_the_origin_range_and_what_the_checker_returned():
    edited, review = fresh()
    out_edited, out_review, counts = add_one(edited, review)
    assert out_review["animations"] == [{"id": "a1", "block": "oh:keyword", "preset": "keyword", "params": {"text": "Every step counts"}, "from": 1, "to": 3}]
    assert out_review["revision"] == review["revision"] + 1
    assert [w["text"] for w in out_edited["words"]] == [w["text"] for w in edited["words"]] and counts == {"edited": 0, "split": 0, "merged": 0, "deleted": 0}


def test_a_remove_takes_an_animation_out_by_its_id_and_refuses_what_is_not_one():
    edited, review = fresh()
    _, one, _ = add_one(edited, review)
    _, gone, _ = apply(edited, one, [{"op": "animation", "id": "a1", "remove": True}])
    assert gone["animations"] == []
    assert refusal(edited, one, [{"op": "animation", "id": "a9", "remove": True}]).code == "unknown_animation"
    assert refusal(edited, one, [{"op": "animation", "id": "a1", "remove": False}]).code == "bad_edit"
    assert refusal(edited, one, [{"op": "animation", "id": "a1", "remove": True, "block": "oh:keyword"}]).code == "bad_edit"
    assert refusal(edited, one, [{"op": "animation", "id": "a1"}]).code == "bad_edit"


def test_without_a_checker_an_add_is_refused_and_a_remove_still_works():
    edited, review = fresh()
    assert refusal(edited, review, [dict(ADD)], animate=None).code == "animation_unavailable"
    _, one, _ = add_one(edited, review)
    _, gone, _ = apply(edited, one, [{"op": "animation", "id": "a1", "remove": True}], animate=None)
    assert gone["animations"] == []


def test_the_shape_of_an_add_is_closed():
    edited, review = fresh()
    assert refusal(edited, review, [{k: v for k, v in ADD.items() if k != "params"}]).code == "bad_edit"
    assert refusal(edited, review, [dict(ADD, colour="red")]).code == "unknown_field"
    assert refusal(edited, review, [dict(ADD, word_from=3, word_to=1)]).code == "bad_index"
    assert refusal(edited, review, [dict(ADD, word_to=99)]).code == "bad_index"
    assert refusal(edited, review, [dict(ADD, start=1.5)]).code == "time_not_accepted"


def test_the_cap_counts_the_script_beats_that_are_not_dropped_and_the_ceiling_is_twelve():
    edited, review = fresh()
    for _ in range(9):
        edited, review, _ = add_one(edited, review)
    assert len(review["animations"]) == 9
    assert refusal(edited, review, [dict(ADD)]).code == "too_many_animations"
    edited, review, _ = apply(edited, review, [{"op": "overlay", "beat": 1, "dropped": True}])
    edited, review, _ = add_one(edited, review)
    assert len(review["animations"]) == 10
    edited, review = fresh()
    for _ in range(cap.ANIMATIONS_MAX):
        edited, review, _ = add_one(edited, review, beats=())
    assert len(review["animations"]) == 12
    assert refusal(edited, review, [dict(ADD)], beats=()).code == "too_many_animations"


def test_a_refusal_of_the_checker_propagates_and_changes_neither_input():
    edited, review = fresh()
    before = copy.deepcopy((edited, review))

    def bad(block, params, where):
        raise cap.CaptionError("undeclared_param", f"{where}.params.size")
    err = refusal(edited, review, [dict(ADD)], animate=bad)
    assert (err.code, err.field) == ("undeclared_param", "edits[0].params.size")
    assert (edited, review) == before


def test_the_first_free_number_is_used_again():
    edited, review = fresh()
    edited, review, _ = apply(edited, review, [dict(ADD), dict(ADD, word_from=4, word_to=5)])
    assert [a["id"] for a in review["animations"]] == ["a1", "a2"]
    edited, review, _ = apply(edited, review, [{"op": "animation", "id": "a1", "remove": True}])
    edited, review, _ = add_one(edited, review)
    assert sorted(a["id"] for a in review["animations"]) == ["a1", "a2"]


def test_an_animation_keeps_its_words_when_the_words_before_it_are_split():
    edited, review = fresh()
    edited, review, _ = apply(edited, review, [dict(ADD, word_from=5, word_to=6)])
    edited, review, _ = apply(edited, review, [{"op": "split", "index": 1, "parts": ["to", "the"]}])
    shown = cap.view(edited, review, {}, {}, {})
    [row] = shown["animations"]
    assert (row["word_from"], row["word_to"], row["lost"]) == (6, 7, False)


def stored(edited, review):
    _, out, _ = add_one(edited, review)
    return out


def test_a_stored_review_reads_back_and_each_malformed_field_is_refused():
    edited, review = fresh()
    good = stored(edited, review)
    assert cap.check_review(good)["animations"] == good["animations"]
    item = good["animations"][0]
    old = {k: v for k, v in good.items() if k != "animations"}
    assert cap.check_review(old)["animations"] == []
    broken = [dict(item, id="a13"), dict(item, id="b1"), dict(item, block="xx:key"), dict(item, preset="Key"), dict(item, params={"text": True}),
              dict(item, params={"text": "x" * 241}), dict(item, params={"Text": "x"}), dict(item, params={"n": float("inf")}), dict(item, **{"from": 4, "to": 2}),
              dict(item, extra=1), dict(item, params=[]), dict(item, **{"from": -1})]
    for one in broken:
        with pytest.raises(cap.CaptionError) as caught:
            cap.check_review(dict(good, animations=[one]))
        assert (caught.value.code, caught.value.field) == ("review_unreadable", "animations"), one
    for many in ([item, dict(item)], [dict(item, id=f"a{k}") for k in range(1, 13)] + [dict(item, id="a1")], "x"):
        with pytest.raises(cap.CaptionError) as caught:
            cap.check_review(dict(good, animations=many))
        assert caught.value.code == "review_unreadable"
    thirteen = [dict(item, id=f"a{k % 12 + 1}") for k in range(13)]
    with pytest.raises(cap.CaptionError):
        cap.check_review(dict(good, animations=thirteen))


def test_an_animation_is_shrunk_to_the_live_words_and_lost_when_none_is_left():
    edited, review = fresh()
    _, one, _ = add_one(edited, review)                  # words 1 to 3
    placed, gone = cap.animations_current(one, edited, {3, 4, 5})
    assert gone == [] and [(a["id"], a["word_from"], a["word_to"]) for a in placed] == [("a1", 3, 3)]
    assert placed[0]["block"] == "oh:keyword" and placed[0]["preset"] == "keyword" and placed[0]["params"] == {"text": "Every step counts"}
    placed, gone = cap.animations_current(one, edited, {0, 5})
    assert placed == [] and gone == ["a1"]
    _, two, _ = apply(edited, one, [dict(ADD, word_from=0, word_to=0)])
    placed, gone = cap.animations_current(two, edited, set(range(9)))
    assert [(a["id"], a["word_from"]) for a in placed] == [("a2", 0), ("a1", 1)]


def test_the_view_rows_carry_the_range_the_lost_flag_and_the_overlap_with_a_script_beat():
    edited, review = fresh()
    _, one, _ = add_one(edited, review)
    proposal = {"threshold": 0.5, "report": [{"beat": 1, "preset": "keyword", "word_from": 3, "word_to": 4, "matched": True, "score": 0.9}], "slots": []}
    shown = cap.view(edited, one, {}, proposal, {})
    [row] = shown["animations"]
    assert (row["id"], row["word_from"], row["word_to"], row["lost"], row["overlaps_beat"]) == ("a1", 1, 3, False, True)
    assert shown["counts"]["animations"] == 1
    _, dropped, _ = apply(edited, one, [{"op": "overlay", "beat": 1, "dropped": True}])
    assert cap.view(edited, dropped, {}, proposal, {})["animations"][0]["overlaps_beat"] is False
    _, away, _ = apply(edited, one, [dict(ADD, word_from=6, word_to=6)])
    assert [r["overlaps_beat"] for r in cap.view(edited, away, {}, proposal, {})["animations"]] == [True, False]
    cut_edited, cut_review, _ = apply(edited, one, [{"op": "delete", "index": i} for i in (1, 2, 3)])
    [gone] = cap.view(cut_edited, cut_review, {}, {}, {})["animations"]
    assert gone["lost"] is True and gone["word_from"] is None and gone["overlaps_beat"] is False


def test_the_constants_equal_the_renderers_own():
    vocabulary = json.loads((REPO / "shared" / "references" / "video-presets.json").read_text(encoding="utf-8"))
    assert cap.BEATS_MAX == vocabulary["limits"]["beats_max"]
    source = (REPO / "providers" / "renderer" / "_blocks.py").read_text(encoding="utf-8")
    short = re.search(r'^_SHORT = r"(.*)"$', source, re.M).group(1)
    assert cap.BLOCK_NAME.pattern == "(oh|hf):" + short
    assert re.search(r'^PRESET = re.compile\(r"(.*)"\)$', source, re.M).group(1) == cap.PRESET_NAME.pattern
    assert re.search(r'^PARAM_NAME = re.compile\(r"(.*)"\)$', source, re.M).group(1) == cap.PARAM_NAME.pattern
    catalogue = json.loads((REPO / "providers" / "renderer" / "blocks" / "catalogue.json").read_text(encoding="utf-8"))
    assert all(cap.BLOCK_NAME.fullmatch(b["name"]) for b in catalogue["blocks"])
