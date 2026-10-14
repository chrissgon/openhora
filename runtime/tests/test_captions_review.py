"""The caption review (runtime/captions.py): how the words a person changes are re-mapped onto word indices, what a refusal leaves,
and what the view shows. Pure: no provider, no store, no file. Fictional words only (a speaker's Brazilian Portuguese as spoken).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_captions_review.py
"""
from __future__ import annotations

import copy

import pytest

import pipeline_kit as kit
import standin_tree as st

cap = st.load("captions")

TRANSCRIPT, _SILENCES = kit.build_transcript(misplace=False)
BEATS = {1, 2, 3, 4, 5, 6, 7}
SLOTS = {"beat7"}
PROPOSALS = {"retake-1": (28, 33)}


def fresh():
    return cap.start_edited(copy.deepcopy(TRANSCRIPT)), cap.new_review()


def apply(edits, edited=None, review=None, revision=None, proposals=PROPOSALS):
    edited, review = (edited, review) if edited is not None else fresh()
    return cap.apply_edits(edited, review, edits, revision=review["revision"] if revision is None else revision,
                           proposals=proposals, beats=BEATS, slots=SLOTS)


def index_of(edited, text):
    return next(w["index"] for w in edited["words"] if w["text"] == text)


# --- the words: edit, split, merge, delete ---------------------------------------------------------------------------------------


def test_an_edit_with_the_same_number_of_words_keeps_every_words_time():
    edited, _ = fresh()
    i = index_of(edited, "pra")  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
    before = edited["words"][i]
    out, review, counts = apply([{"op": "edit", "index": i, "text": "para"}])
    after = out["words"][i]
    assert (after["start"], after["end"]) == (before["start"], before["end"]) and after["text"] == "para" and after["edited"] is True
    assert not after.get("estimated") and counts == {"edited": 1, "split": 0, "merged": 0, "deleted": 0}
    assert [w["text"] for w in out["words"] if w["index"] != i] == [w["text"] for w in edited["words"] if w["index"] != i]
    assert review["revision"] == 1 and out["facts"]["revision"] == 1


def test_captions_are_written_as_spoken_and_never_respelled():
    edited, _ = fresh()
    i = index_of(edited, "pra")  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
    out, _, _ = apply([{"op": "edit", "index": i, "text": "pra"}, {"op": "edit", "index": index_of(edited, "tá"), "text": "tá"},  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
                       {"op": "edit", "index": index_of(edited, "gente"), "text": "a gente"}])
    texts = [w["text"] for w in out["words"]]
    assert "pra" in texts and "tá" in texts and "a" in texts and "gente" in texts  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
    assert "para" not in texts and "está" not in texts and "agente" not in texts  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said


def test_a_text_with_spaces_splits_the_word_and_shares_its_time_by_length_flagged_estimated():
    edited, _ = fresh()
    i = index_of(edited, "gente")
    original = edited["words"][i]
    out, _, counts = apply([{"op": "edit", "index": i, "text": "a gente"}])
    a, b = out["words"][i], out["words"][i + 1]
    assert (a["text"], b["text"]) == ("a", "gente") and a["estimated"] is True and b["estimated"] is True
    assert a["start"] == original["start"] and b["end"] == original["end"] and a["end"] == b["start"]
    assert a["start"] < a["end"] < b["end"] and (a["end"] - a["start"]) < (b["end"] - b["start"])   # one letter against five
    assert a["origin"] == b["origin"] == original["origin"] and counts["split"] == 1
    assert [w["index"] for w in out["words"]] == list(range(len(edited["words"]) + 1))
    assert all(w["segment"] == original["segment"] for w in out["words"][i:i + 2])


def test_split_names_the_parts_and_the_segment_after_it_is_renumbered():
    edited, _ = fresh()
    i = index_of(edited, "painel.")
    out, _, _ = apply([{"op": "split", "index": i, "parts": ["pai", "nel."]}])
    seg = edited["words"][i]["segment"]
    section = next(s for s in out["segments"] if s["index"] == seg)
    assert section["source"] == "edited" and section["last_word"] == i + 1 and section["text"].endswith("pai nel.")
    later = next(s for s in out["segments"] if s["index"] == seg + 1)
    assert later["source"] == "transcriber" and later["first_word"] == i + 2 and later["text"] == edited["segments"][seg + 1]["text"]


def test_merging_adjacent_words_gives_one_word_from_the_first_start_to_the_last_end():
    edited, _ = fresh()
    i = index_of(edited, "gasto")
    first, last = edited["words"][i], edited["words"][i + 1]
    out, _, counts = apply([{"op": "merge", "from": i, "to": i + 1}])
    word = out["words"][i]
    assert word["text"] == first["text"] + last["text"] and (word["start"], word["end"]) == (first["start"], last["end"])
    assert word["origin"] == [first["index"], last["index"]] and not word.get("estimated") and counts["merged"] == 2
    assert len(out["words"]) == len(edited["words"]) - 1
    renamed, _, _ = apply([{"op": "merge", "from": i, "to": i + 1, "text": "gastos"}])
    assert renamed["words"][i]["text"] == "gastos"


def test_deleting_a_word_removes_it_and_the_origin_keeps_the_gap():
    edited, _ = fresh()
    i = index_of(edited, "hábito")
    out, review, counts = apply([{"op": "delete", "index": i}])
    assert counts["deleted"] == 1 and len(out["words"]) == len(edited["words"]) - 1
    assert "hábito" not in [w["text"] for w in out["words"]]
    assert cap.span_current(out["words"], i, i) is None
    assert cap.span_current(out["words"], i - 1, i + 1) == (i - 1, i)


def test_edits_in_one_call_all_speak_of_the_numbering_the_person_read():
    edited, _ = fresh()
    a, b = index_of(edited, "gasto"), index_of(edited, "hábito")
    out, _, _ = apply([{"op": "delete", "index": a}, {"op": "edit", "index": b, "text": "costume"}])
    assert "gasto" not in [w["text"] for w in out["words"]] and "costume" in [w["text"] for w in out["words"]]
    assert "hábito" not in [w["text"] for w in out["words"]]


# --- a refusal changes nothing ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("edit", [
    {"op": "edit", "index": 3, "text": "um" + chr(0x200B) + "dois"},        # a zero-width space (Cf)
    {"op": "edit", "index": 3, "text": "um" + chr(0x202E) + "dois"},        # a right-to-left override (Cf)
    {"op": "edit", "index": 3, "text": "um\ndois"},             # a line break (Cc)
    {"op": "edit", "index": 3, "text": "um" + chr(0x2028) + "dois"},         # a line separator (Zl)
    {"op": "edit", "index": 3, "text": "um" + chr(0xE000) + "dois"},         # a private-use character (Co)
    {"op": "edit", "index": 3, "text": "   "},
    {"op": "edit", "index": 3, "text": "x" * 41},
    {"op": "edit", "index": 3, "text": None},
    {"op": "split", "index": 3, "parts": ["um", ""]},
    {"op": "split", "index": 3, "parts": ["so um"]},
])
def test_a_refused_character_or_text_leaves_the_transcript_and_the_review_unchanged(edit):
    edited, review = fresh()
    before = (copy.deepcopy(edited), copy.deepcopy(review))
    ok = {"op": "edit", "index": 4, "text": "valido"}
    with pytest.raises(cap.CaptionError) as caught:
        cap.apply_edits(edited, review, [ok, edit], revision=0, proposals=PROPOSALS, beats=BEATS, slots=SLOTS)
    assert (edited, review) == before, "the good edit before the bad one is not applied either"
    assert caught.value.code in ("forbidden_character", "empty_text", "text_too_long", "not_text", "bad_edit")
    assert not edit.get("text") or edit["text"] not in str(caught.value)


def test_the_refusal_names_a_code_and_a_field_and_never_the_text():
    edited, review = fresh()
    with pytest.raises(cap.CaptionError) as caught:
        cap.apply_edits(edited, review, [{"op": "edit", "index": 3, "text": "senha" + chr(0x200B) + "secreta"}], revision=0, proposals={}, beats=BEATS, slots=SLOTS)
    assert str(caught.value) == "forbidden_character:edits[0].text" and "senha" not in str(caught.value)


def test_decomposed_text_is_made_nfc_and_a_hyphen_or_an_apostrophe_stays():
    edited, _ = fresh()
    out, _, _ = apply([{"op": "edit", "index": 3, "text": "voce" + chr(0x302) + ""}])
    assert out["words"][3]["text"] == "você"  # validate: allow english-only -- a fictional speaker talking Brazilian Portuguese as it is spoken: a caption must stay as said
    out, _, _ = apply([{"op": "edit", "index": 3, "text": "d'água"}])
    assert out["words"][3]["text"] == "d'água"


@pytest.mark.parametrize("key", ["start", "end", "time", "at", "duration", "seconds", "offset", "ms", "t", "timestamp"])
def test_an_edit_that_carries_a_time_is_refused_not_ignored(key):
    edited, review = fresh()
    for edit in ({"op": "edit", "index": 3, "text": "oi", key: 1.5}, {"op": "delete", "index": 3, key: 0},
                 {"op": "retake", "id": "retake-1", "confirmed": True, key: 2}):
        with pytest.raises(cap.CaptionError) as caught:
            cap.apply_edits(edited, review, [edit], revision=0, proposals=PROPOSALS, beats=BEATS, slots=SLOTS)
        assert caught.value.code == "time_not_accepted"


def test_no_operation_of_the_review_has_a_field_for_a_word_time():
    for op, fields in cap.OPS.items():
        assert not (fields & cap.TIME_KEYS), op


def test_unknown_operations_fields_overlaps_and_ranges_are_refused():
    edited, review = fresh()
    cases = [([{"op": "stretch", "index": 1}], "unknown_edit"), ([{"op": "edit", "index": 1, "text": "a", "colour": "red"}], "unknown_field"),
             ([{"op": "delete", "index": 10_000}], "bad_index"), ([{"op": "delete", "index": -1}], "bad_index"),
             ([{"op": "delete", "index": True}], "bad_index"), ([{"op": "delete", "index": 4}, {"op": "edit", "index": 4, "text": "x"}], "overlapping_edits"),
             ([{"op": "merge", "from": 3, "to": 5}, {"op": "delete", "index": 4}], "overlapping_edits"), ([{"op": "merge", "from": 5, "to": 3}], "bad_index"),
             ([], "bad_edit"), ("delete", "bad_edit"), ([42], "bad_edit")]
    for edits, code in cases:
        with pytest.raises(cap.CaptionError) as caught:
            cap.apply_edits(edited, review, edits, revision=0, proposals=PROPOSALS, beats=BEATS, slots=SLOTS)
        assert caught.value.code == code, edits


def test_a_merge_across_two_segments_is_refused():
    edited, review = fresh()
    last_of_first = edited["segments"][0]["last_word"]
    with pytest.raises(cap.CaptionError) as caught:
        cap.apply_edits(edited, review, [{"op": "merge", "from": last_of_first, "to": last_of_first + 1}], revision=0, proposals={}, beats=BEATS, slots=SLOTS)
    assert caught.value.code == "merge_across_segments"


def test_a_stale_revision_is_refused_because_the_indices_moved():
    edited, review = fresh()
    out, review1, _ = apply([{"op": "delete", "index": 2}], edited, review)
    with pytest.raises(cap.CaptionError) as caught:
        apply([{"op": "delete", "index": 2}], out, review1, revision=0)
    assert caught.value.code == "stale_revision" and review1["revision"] == 1
    again, review2, _ = apply([{"op": "delete", "index": 2}], out, review1, revision=1)
    assert review2["revision"] == 2 and len(again["words"]) == len(out["words"]) - 1


def test_deleting_every_word_is_refused():
    edited, review = fresh()
    with pytest.raises(cap.CaptionError) as caught:
        cap.apply_edits(edited, review, [{"op": "delete", "index": i} for i in range(len(edited["words"]))], revision=0, proposals={}, beats=BEATS, slots=SLOTS)
    assert caught.value.code == "no_words"


# --- the decisions: retakes, anchors, overlays, slots, the face box, the cover ------------------------------------------------------


def test_a_retake_is_confirmed_by_the_range_it_drops_and_undone_by_its_id():
    out, review, _ = apply([{"op": "retake", "id": "retake-1", "confirmed": True}])
    assert review["confirmed_retakes"] == [{"id": "retake-1", "from": 28, "to": 33}] and out["words"] == fresh()[0]["words"]
    _, again, _ = apply([{"op": "retake", "id": "retake-1", "confirmed": False}], out, review, revision=1)
    assert again["confirmed_retakes"] == []
    with pytest.raises(cap.CaptionError) as caught:
        apply([{"op": "retake", "id": "retake-9", "confirmed": True}])
    assert caught.value.code == "unknown_retake"


def test_an_anchor_is_kept_in_the_numbering_of_the_transcript_and_survives_the_next_edit():
    edited, _ = fresh()
    a, b = index_of(edited, "hábito"), index_of(edited, "mês")
    out, review, _ = apply([{"op": "anchor", "beat": 5, "word_from": a, "word_to": b}])
    assert review["anchors"] == {"5": [a, b]}
    earlier = index_of(edited, "gasto")
    out2, review2, _ = apply([{"op": "delete", "index": earlier}], out, review, revision=1)
    now = cap.span_current(out2["words"], *review2["anchors"]["5"])
    assert now == (a - 1, b - 1) and out2["words"][now[0]]["text"] == "hábito" and out2["words"][now[1]]["text"] == "mês"
    _, cleared, _ = apply([{"op": "anchor", "beat": 5, "clear": True}], out2, review2, revision=2)
    assert cleared["anchors"] == {}


def test_an_anchor_over_a_merged_word_covers_every_original_word_it_stands_for():
    edited, _ = fresh()
    i = index_of(edited, "gasto")
    merged, review, _ = apply([{"op": "merge", "from": i, "to": i + 1}])
    out, review2, _ = apply([{"op": "anchor", "beat": 2, "word_from": i, "word_to": i}], merged, review, revision=1)
    assert review2["anchors"]["2"] == [i, i + 1]


def test_an_anchor_names_a_beat_that_has_an_overlay_and_a_range_that_is_there():
    for edit, code in (({"op": "anchor", "beat": 99, "word_from": 1, "word_to": 2}, "unknown_beat"),
                       ({"op": "anchor", "beat": 3, "word_from": 5, "word_to": 2}, "bad_index"),
                       ({"op": "anchor", "beat": 3, "word_from": 1, "word_to": 5_000}, "bad_index"),
                       ({"op": "anchor", "beat": 3, "word_from": 1, "word_to": 2, "clear": True}, "unknown_field")):
        with pytest.raises(cap.CaptionError) as caught:
            apply([edit])
        assert caught.value.code == code


def test_an_overlay_is_dropped_and_brought_back_and_a_slot_gets_its_choice():
    _, review, _ = apply([{"op": "overlay", "beat": 4, "dropped": True}, {"op": "overlay", "beat": 2, "dropped": True},
                          {"op": "slot", "slot": "beat7", "choice": "keyword"}])
    assert review["dropped_beats"] == [2, 4] and review["empty_slots"] == {"beat7": "keyword"}
    _, back, _ = apply([{"op": "overlay", "beat": 4, "dropped": False}, {"op": "slot", "slot": "beat7", "choice": None}], *fresh_with(review))
    assert back["dropped_beats"] == [2] and back["empty_slots"] == {}
    for edit in ({"op": "slot", "slot": "beat9", "choice": "none"}, {"op": "slot", "slot": "beat7", "choice": "video"}):
        with pytest.raises(cap.CaptionError):
            apply([edit])


def fresh_with(review):
    edited, _ = fresh()
    return edited, review, review["revision"]


def test_the_face_box_is_whole_numbers_with_a_size_inside_the_frame():
    _, review, _ = apply([{"op": "face_box", "x": 240, "y": 620, "w": 600, "h": 560}])
    assert review["face_box"] == {"x": 240, "y": 620, "w": 600, "h": 560}
    for box in ({"x": 0, "y": 0, "w": 0, "h": 10}, {"x": -1, "y": 0, "w": 10, "h": 10}, {"x": 1000, "y": 0, "w": 100, "h": 10},
                {"x": 0, "y": 1900, "w": 10, "h": 100}, {"x": 1.5, "y": 0, "w": 10, "h": 10}, {"x": 0, "y": 0, "w": 10, "h": "9"}):
        with pytest.raises(cap.CaptionError) as caught:
            apply([{"op": "face_box", **box}])
        assert caught.value.code == "bad_face_box"
    _, gone, _ = apply([{"op": "face_box", "clear": True}], *fresh_with(review))
    assert gone["face_box"] is None


def test_the_cover_offset_is_a_whole_number_of_milliseconds():
    _, review, _ = apply([{"op": "cover", "offset_ms": 1500}])
    assert review["cover_offset_ms"] == 1500
    for bad in (-1, 1.5, "3", 10_000_000):
        with pytest.raises(cap.CaptionError):
            apply([{"op": "cover", "offset_ms": bad}])


def test_a_review_that_is_stored_is_read_back_closed():
    review = cap.new_review()
    assert cap.check_review(review) == review
    for broken in ({**review, "extra": 1}, {**review, "revision": "1"}, {**review, "anchors": {"x": [1, 2]}},
                   {**review, "confirmed_retakes": [{"id": "retake-1"}]}, {**review, "face_box": {"x": 1}}, {**review, "empty_slots": {"a": "video"}}):
        with pytest.raises(cap.CaptionError):
            cap.check_review(broken)


# --- what the later steps are given -------------------------------------------------------------------------------------------------


def test_a_confirmed_retake_meets_the_new_proposal_that_drops_the_same_words_and_a_lost_one_is_counted():
    edited, review = fresh()
    review["confirmed_retakes"] = [{"id": "retake-1", "from": 28, "to": 33}]
    ids, lost = cap.confirmed_ids(review, edited, [{"id": "retake-4", "word_from": 28, "word_to": 33}, {"id": "retake-5", "word_from": 50, "word_to": 54}])
    assert ids == ["retake-4"] and lost == []
    ids, lost = cap.confirmed_ids(review, edited, [{"id": "retake-5", "word_from": 50, "word_to": 54}])
    assert ids == [] and len(lost) == 1
    out, _, _ = apply([{"op": "delete", "index": 2}], edited, cap.new_review())
    ids, lost = cap.confirmed_ids(review, out, [{"id": "retake-2", "word_from": 27, "word_to": 32}])
    assert ids == ["retake-2"] and lost == [], "the new proposal is numbered by the edited words, the range by the transcript's"


def test_an_anchor_becomes_the_live_edited_words_and_is_lost_when_none_is_left():
    edited, review = fresh()
    review["anchors"] = {"5": [40, 44], "3": [10, 12]}
    live = set(range(len(edited["words"]))) - {40, 41}
    found, lost = cap.anchors_current(review, edited, live)
    assert found == {3: (10, 12), 5: (42, 44)} and lost == []
    found, lost = cap.anchors_current(review, edited, {0, 1, 2})
    assert found == {} and lost == [3, 5]


# --- what the person sees -----------------------------------------------------------------------------------------------------------


def proposal_documents():
    edl = {"proposals": [{"id": "retake-1", "kind": "repeat", "word_from": 28, "word_to": 33, "keep_from": 34, "seconds": 2.4, "confirmed": False}],
           "captions": {"chunks": [[0, 2], [3, 5], [6, 8]]},
           "normalisation": {"retimed_words": [{"index": 0, "from": [0.2, 0.45], "to": [1.4, 1.5]}], "unplaced_words": [{"index": 9, "start": 0.1, "end": 0.2}],
                             "dropped_segments": []}}
    beats = {"threshold": 0.6, "slots": [{"slot": "beat7", "beat": 7, "param": "asset", "type": "image", "description": "a screenshot"}],
             "report": [{"beat": 1, "preset": None},
                        {"beat": 3, "preset": "keyword", "score": 0.95, "matched": True, "reordered": False, "word_from": 12, "word_to": 20},
                        {"beat": 5, "preset": "number", "score": 0.4, "matched": False, "reordered": False, "word_from": None, "word_to": None},
                        {"beat": 6, "preset": "quote", "score": 0.9, "matched": True, "reordered": True, "word_from": 5, "word_to": 8}]}
    return edl, beats


def test_the_view_shows_chunks_retakes_adjusted_timing_beats_and_what_was_left_out():
    edl, beats = proposal_documents()
    edited, review = fresh()
    shown = cap.view(edited, review, edl, beats, {"beat7": None})
    words = shown["words"]
    assert [c["words"] for c in shown["chunks"]][:2] == [[0, 1, 2], [3, 4, 5]] and shown["counts"]["words"] == len(edited["words"])
    assert words[0]["timing_adjusted"] is True and words[1]["timing_adjusted"] is False
    assert words[9]["left_out"] == "unplaced" and shown["unplaced"] == [{"index": 9, "word": 9, "start": 0.1, "end": 0.2}]
    assert words[40]["chunk"] is None
    assert shown["retakes"] == [{"id": "retake-1", "kind": "repeat", "seconds": 2.4, "word_from": 28, "word_to": 33, "keep_from": 34, "confirmed": False}]
    rows = {b["beat"]: b for b in shown["beats"]}
    assert set(rows) == {3, 5, 6}, "a beat with no preset has no overlay to check"
    assert rows[3]["below_threshold"] is False and rows[5]["below_threshold"] is True and rows[5]["word_from"] is None
    assert rows[6]["reordered"] is True and shown["counts"]["below_threshold"] == 1 and shown["counts"]["timing_adjusted"] == 1
    assert shown["slots"] == [{"slot": "beat7", "beat": 7, "param": "asset", "type": "image", "description": "a screenshot", "file": None, "choice": None}]


def test_the_view_follows_the_edits_confirmed_retakes_anchors_and_dropped_overlays():
    edl, beats = proposal_documents()
    edited, review = fresh()
    out, review, _ = apply([{"op": "delete", "index": 2}, {"op": "retake", "id": "retake-1", "confirmed": True},
                            {"op": "anchor", "beat": 5, "word_from": 40, "word_to": 44}, {"op": "overlay", "beat": 3, "dropped": True},
                            {"op": "slot", "slot": "beat7", "choice": "none"}])
    shown = cap.view(out, review, edl, beats, {"beat7": None})
    retake = shown["retakes"][0]
    assert retake["confirmed"] is True and (retake["word_from"], retake["word_to"]) == (27, 32), "the range is the same words, one index earlier"
    rows = {b["beat"]: b for b in shown["beats"]}
    assert rows[5]["anchored"] is True and rows[5]["score"] == 1.0 and rows[5]["matched"] is True and rows[5]["below_threshold"] is False
    assert (rows[5]["word_from"], rows[5]["word_to"]) == (39, 43) and rows[3]["dropped"] is True
    assert shown["slots"][0]["choice"] == "none" and shown["revision"] == 1
    assert shown["words"][1]["chunk"] == 0 and shown["words"][2]["chunk"] == 1, "word 2 went: the chunk of its neighbour now starts there"


# --- review round: a confirmed retake is carried over only to a proposal of about its size --------------------------------------------------------


def confirmed(entry):
    edited, review = fresh()
    review["confirmed_retakes"] = [entry]
    return edited, review


def proposal(first, last, seconds, ident="retake-9"):
    return {"id": ident, "word_from": first, "word_to": last, "seconds": seconds}


def test_a_confirmation_is_carried_to_a_proposal_that_contains_it_or_covers_most_of_it_and_is_not_much_longer():
    edited, review = confirmed({"id": "retake-1", "from": 30, "to": 39, "seconds": 3.0})
    assert cap.confirmed_ids(review, edited, [proposal(30, 39, 3.0)]) == (["retake-9"], [])
    assert cap.confirmed_ids(review, edited, [proposal(28, 41, 4.9)]) == (["retake-9"], []), "contains it, 1.9 s more"
    assert cap.confirmed_ids(review, edited, [proposal(33, 39, 2.0)]) == (["retake-9"], []), "covers 7 of 10 words"
    assert cap.confirmed_ids(review, edited, [proposal(36, 39, 1.0)])[0] == [], "covers 4 of 10 words: half or less"
    assert cap.confirmed_ids(review, edited, [proposal(35, 39, 1.0)])[0] == [], "exactly half is not more than half"


def test_a_confirmation_is_not_carried_to_a_much_larger_proposal_and_comes_back_as_lost():
    edited, review = confirmed({"id": "retake-1", "from": 30, "to": 39, "seconds": 3.0})
    ids, lost = cap.confirmed_ids(review, edited, [proposal(10, 60, 12.0)])
    assert ids == [] and lost == review["confirmed_retakes"], "a cut of 12 s was never what the person confirmed"
    ids, lost = cap.confirmed_ids(review, edited, [proposal(20, 45, 5.01)])
    assert ids == [] and len(lost) == 1
    again = cap.drop_confirmations(review, lost)
    assert again["confirmed_retakes"] == [] and again["revision"] == review["revision"] + 1 and review["confirmed_retakes"]


def test_a_confirmation_stored_without_its_time_is_judged_by_the_words_alone():
    edited, review = confirmed({"id": "retake-1", "from": 30, "to": 39})
    assert cap.confirmed_ids(review, edited, [proposal(10, 60, 12.0)])[0] == ["retake-9"]


def test_the_time_of_a_proposal_is_kept_with_the_confirmation_and_checked_when_the_review_is_read():
    _, review, _ = apply([{"op": "retake", "id": "retake-1", "confirmed": True}], proposals={"retake-1": (28, 33, 2.4)})
    assert review["confirmed_retakes"] == [{"id": "retake-1", "from": 28, "to": 33, "seconds": 2.4}] and cap.check_review(review) == review
    with pytest.raises(cap.CaptionError):
        cap.check_review({**review, "confirmed_retakes": [{"id": "retake-1", "from": 28, "to": 33, "seconds": "long"}]})


def test_reconcile_takes_the_transcripts_revision_only_when_it_is_exactly_one_ahead():
    edited, review = fresh()
    edited["facts"]["revision"] = 1
    assert cap.reconcile(edited, review)["revision"] == 1
    edited["facts"]["revision"] = 3
    with pytest.raises(cap.CaptionError, match="review_disagrees"):
        cap.reconcile(edited, review)
    assert cap.reconcile(*fresh()) == cap.new_review()


def test_a_merge_of_long_words_or_a_text_with_a_space_is_refused_when_it_is_made():
    edited, review = fresh()
    a = index_of(edited, "primeira")
    out, review1, _ = apply([{"op": "edit", "index": a, "text": "x" * 30}, {"op": "edit", "index": a + 1, "text": "y" * 20}])
    with pytest.raises(cap.CaptionError) as caught:
        apply([{"op": "merge", "from": a, "to": a + 1}], out, review1, revision=1)
    assert caught.value.code == "text_too_long"
    for edit in ({"op": "merge", "from": 1, "to": 2, "text": "dois mundos"}, {"op": "split", "index": 1, "parts": ["a b", "c"]}):
        with pytest.raises(cap.CaptionError) as caught:
            apply([edit])
        assert caught.value.code == "space_in_word"
    assert cap.harden_word("x" * 40, "w") and cap.harden_word("é", "w") == "é"
