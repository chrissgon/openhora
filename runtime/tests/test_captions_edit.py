"""The review edits of the media set (package V9b-3a, runtime/captions.py): the choice `stock`, `slot_search`, `slot_asset`, the layouts an `animation` edit adds with a picture slot of
their own, and what the review keeps. The check of an added block is a stand-in; nothing is called and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_captions_edit.py
"""
from __future__ import annotations

import copy

import pytest

import standin_tree as st

captions = st.load("captions")


def doc(n=6):
    words = [{"index": i, "text": "w%d" % i, "start": i * 0.5, "end": i * 0.5 + 0.4, "segment": 0, "origin": [i, i], "edited": False} for i in range(n)]
    return {"schema_version": 1, "words": words, "segments": [{"index": 0, "start": 0, "end": 3, "text": "x", "first_word": 0, "last_word": n - 1, "source": "transcriber"}], "facts": {"revision": 0}}


def apply(edits, review=None, slots=("beat7", "beat8"), stock=None, animate=None, revision=None):
    review = review or captions.new_review()
    return captions.apply_edits(doc(), review, edits, revision=review["revision"] if revision is None else revision, proposals={}, beats=set(), slots=set(slots), animate=animate, stock=stock)


def code(edits, **kw):
    with pytest.raises(captions.CaptionError) as raised:
        apply(edits, **kw)
    return raised.value.code, raised.value.field


def layout_checker(block, params, where):
    return {"block": block, "preset": "cutaway", "params": dict(params), "asset_param": "asset"}


def test_the_choice_stock_is_a_choice_of_a_known_slot_and_clears_like_the_others():
    _, review, _ = apply([{"op": "slot", "slot": "beat7", "choice": "stock"}])
    assert review["empty_slots"] == {"beat7": "stock"} and "stock" in captions.SLOT_CHOICES
    _, review, _ = apply([{"op": "slot", "slot": "beat7", "choice": None}], review)
    assert review["empty_slots"] == {}
    assert code([{"op": "slot", "slot": "beat9", "choice": "stock"}]) == ("unknown_slot", "edits[0].slot")
    assert code([{"op": "slot", "slot": "beat7", "choice": "photo"}]) == ("bad_choice", "edits[0].choice")


def test_slot_search_takes_one_to_six_words_of_ascii_letters_and_a_kind():
    _, review, _ = apply([{"op": "slot_search", "slot": "beat7", "search": "market stall", "want": "image"}])
    assert review["slot_searches"] == {"beat7": {"search": "market stall", "want": "image"}} and review["revision"] == 1
    for bad in ("", " market", "market ", "a", "x" * 61, "one two three four five six seven", "market stall 2", "café", "http://x.example", "the аpple", "a@b", "dog; rm"):
        assert code([{"op": "slot_search", "slot": "beat7", "search": bad, "want": "image"}]) == ("search_refused", "edits[0].search"), bad
    assert code([{"op": "slot_search", "slot": "beat7", "search": "market", "want": "video"}]) == ("bad_choice", "edits[0].want")
    assert code([{"op": "slot_search", "slot": "beat7", "search": "market"}]) == ("bad_choice", "edits[0].want")
    assert code([{"op": "slot_search", "slot": "nope", "search": "market", "want": "clip"}]) == ("unknown_slot", "edits[0].slot")
    assert code([{"op": "slot_search", "slot": "beat7", "search": "market", "want": "clip", "extra": 1}]) == ("unknown_field", "edits[0]")
    assert code([{"op": "slot_search", "slot": "beat7", "search": "market", "want": "clip", "start": 1}]) == ("time_not_accepted", "edits[0]")
    _, again, _ = apply([{"op": "slot_search", "slot": "beat7", "search": "fruit crate", "want": "clip"}], review)
    assert again["slot_searches"]["beat7"] == {"search": "fruit crate", "want": "clip"}


def test_at_most_six_slots_take_words_or_a_pick():
    slots = tuple("s%d" % n for n in range(7))
    edits = [{"op": "slot_search", "slot": s, "search": "market", "want": "image"} for s in slots[:6]]
    _, review, _ = apply(edits, slots=slots)
    assert len(review["slot_searches"]) == 6
    assert code([{"op": "slot_search", "slot": "s6", "search": "market", "want": "image"}], review=review, slots=slots) == ("too_many_slots", "edits[0]")
    assert apply([{"op": "slot_search", "slot": "s0", "search": "fruit", "want": "image"}], review=review, slots=slots)[1]["slot_searches"]["s0"]["search"] == "fruit"
    stock = {s: {"shelf:%s" % s} for s in slots}
    _, picked, _ = apply([{"op": "slot_asset", "slot": s, "pick": "shelf:%s" % s} for s in slots[:6]], slots=slots, stock=stock)
    assert len(picked["slot_assets"]) == 6
    assert code([{"op": "slot_asset", "slot": "s6", "pick": "shelf:s6"}], review=picked, slots=slots, stock=stock) == ("too_many_slots", "edits[0]")


def test_slot_asset_names_a_candidate_of_the_set_for_that_slot_or_clears_the_pick():
    stock = {"beat7": {"shelf:item-1", "shelf:item-2"}, "beat8": {"shelf:item-3"}}
    _, review, _ = apply([{"op": "slot_asset", "slot": "beat7", "pick": "shelf:item-2"}], stock=stock)
    assert review["slot_assets"] == {"beat7": "shelf:item-2"}
    assert code([{"op": "slot_asset", "slot": "beat7", "pick": "shelf:item-3"}], stock=stock) == ("asset_not_found", "edits[0].pick")      # a candidate of another slot
    assert code([{"op": "slot_asset", "slot": "beat7", "pick": "shelf:item-1"}], stock=None) == ("asset_not_found", "edits[0].pick")      # no set was found
    assert code([{"op": "slot_asset", "slot": "beat7", "pick": "../../etc"}], stock=stock) == ("bad_choice", "edits[0].pick")
    assert code([{"op": "slot_asset", "slot": "beat7", "pick": "shelf:item-1", "clear": True}], stock=stock) == ("unknown_field", "edits[0]")
    assert code([{"op": "slot_asset", "slot": "beat9", "pick": "shelf:item-1"}], stock=stock) == ("unknown_slot", "edits[0].slot")
    _, cleared, _ = apply([{"op": "slot_asset", "slot": "beat7", "clear": True}], review)
    assert cleared["slot_assets"] == {} and cleared["revision"] == 2
    pick = "web:q-%s" % ("a" * 12)
    assert apply([{"op": "slot_asset", "slot": "beat7", "pick": pick}], stock={"beat7": {pick}})[1]["slot_assets"]["beat7"] == pick      # a file of the quarantine is named by its hash


def test_a_layout_animation_takes_a_slot_of_its_own_with_the_words_that_say_what_it_shows():
    edit = {"op": "animation", "block": "oh:cutaway", "params": {"fit": "cover"}, "word_from": 1, "word_to": 3, "show": "a busy market", "search": "market stall", "want": "image"}
    _, review, _ = apply([edit], animate=layout_checker)
    [item] = review["animations"]
    assert item["id"] == "a1" and item["asset_param"] == "asset" and "asset" not in item["params"] and item["show"] == "a busy market"
    assert (item["search"], item["want"]) == ("market stall", "image") and review["slot_searches"]["a1"] == {"search": "market stall", "want": "image"}
    assert captions.check_review(review) == review      # the stored shape reads back
    _, picked, _ = apply([{"op": "slot_asset", "slot": "a1", "pick": "shelf:item-1"}, {"op": "slot", "slot": "a1", "choice": "stock"}], review, stock={"a1": {"shelf:item-1"}})
    assert picked["slot_assets"] == {"a1": "shelf:item-1"} and picked["empty_slots"] == {"a1": "stock"}
    _, gone, _ = apply([{"op": "animation", "id": "a1", "remove": True}], picked)
    assert gone["animations"] == [] and gone["slot_searches"] == {} and gone["slot_assets"] == {} and gone["empty_slots"] == {}      # it takes its slot with it


def test_the_same_edit_batch_may_add_a_layout_and_ask_for_its_picture_and_the_checks_hold():
    edits = [{"op": "animation", "block": "oh:cutaway", "params": {}, "word_from": 0, "word_to": 1}, {"op": "slot_search", "slot": "a1", "search": "fruit crate", "want": "clip"}]
    _, review, _ = apply(edits, animate=layout_checker)
    assert review["slot_searches"] == {"a1": {"search": "fruit crate", "want": "clip"}}
    bad = {"op": "animation", "block": "oh:cutaway", "params": {}, "word_from": 0, "word_to": 1}
    assert code([dict(bad, search="market")], animate=layout_checker) == ("bad_edit", "edits[0]")      # a search needs its kind
    assert code([dict(bad, search="market", want="video")], animate=layout_checker) == ("bad_choice", "edits[0].want")
    assert code([dict(bad, search="http://x.example", want="image")], animate=layout_checker) == ("search_refused", "edits[0].search")
    assert code([dict(bad, show="ab")], animate=layout_checker) == ("show_refused", "edits[0].show")
    assert code([dict(bad, show="x" * 81)], animate=layout_checker) == ("show_refused", "edits[0].show")
    assert code([dict(bad, show="line\nbreak here")], animate=layout_checker) == ("show_refused", "edits[0].show")
    overlay = lambda block, params, where: {"block": block, "preset": "keyword", "params": dict(params)}      # noqa: E731
    assert code([{"op": "animation", "block": "oh:keyword", "params": {"text": "x"}, "word_from": 0, "word_to": 1, "search": "x y", "want": "image"}], animate=overlay) == ("bad_edit", "edits[0]")


def test_a_review_with_no_stock_keys_reads_as_empty_and_a_bad_stored_shape_is_refused():
    review = captions.new_review()
    old = {k: v for k, v in review.items() if k not in ("slot_searches", "slot_assets")}
    assert captions.check_review(old) == review and captions.REVIEW_VERSION == 1      # no version bump: an absent key reads as {}
    for field, value in (("slot_searches", {"beat7": {"search": "x", "want": "image"}}), ("slot_searches", {"beat7": {"search": "market stall", "want": "video"}}),
                         ("slot_searches", {"BAD": {"search": "market", "want": "image"}}), ("slot_assets", {"beat7": "no-colon"}), ("slot_assets", {"beat7": 3}),
                         ("slot_assets", {"s%d" % n: "shelf:x" for n in range(7)}), ("slot_searches", [])):
        with pytest.raises(captions.CaptionError) as raised:
            captions.check_review(dict(copy.deepcopy(review), **{field: value}))
        assert raised.value.code == "review_unreadable" and raised.value.field == field
    layout = {"id": "a1", "block": "oh:cutaway", "preset": "cutaway", "params": {}, "from": 0, "to": 1, "asset_param": "asset", "show": "a market", "search": "market", "want": "image"}
    assert captions.check_review(dict(review, animations=[layout]))["animations"] == [layout]
    for broken in (dict(layout, want="video"), dict(layout, search="2 apples"), dict(layout, show="x"), {k: v for k, v in layout.items() if k != "asset_param"},
                   dict(layout, asset_param="asset", params={"asset": "x"}), {k: v for k, v in layout.items() if k != "want"}):
        with pytest.raises(captions.CaptionError):
            captions.check_review(dict(review, animations=[broken]))


def test_the_view_lists_the_slots_with_their_words_and_picks_and_the_layouts_slots_too():
    edits = [{"op": "animation", "block": "oh:cutaway", "params": {}, "word_from": 1, "word_to": 3, "show": "a busy market", "search": "market stall", "want": "image"},
             {"op": "slot_search", "slot": "beat7", "search": "fruit crate", "want": "clip"}]
    edited, review, _ = apply(edits, animate=layout_checker)
    review["slot_assets"] = {"a1": "shelf:item-1"}
    view = captions.view(edited, review, {}, {"slots": [{"slot": "beat7", "beat": 7, "param": "asset", "type": "image", "description": "a screenshot"}]},
                         {"a1": {"name": "asset-%s.png" % ("1" * 12), "type": "png", "sha256": "1" * 64}})
    rows = {r["slot"]: r for r in view["slots"]}
    assert rows["beat7"]["search"] == "fruit crate" and rows["beat7"]["want"] == "clip" and rows["beat7"]["pick"] is None
    assert rows["a1"]["animation"] == "a1" and rows["a1"]["beat"] is None and rows["a1"]["description"] == "a busy market" and rows["a1"]["pick"] == "shelf:item-1"
    assert rows["a1"]["file"]["sha256"] == "1" * 64 and view["animations"][0]["slot"] == "a1" and view["animations"][0]["asset_param"] == "asset"
