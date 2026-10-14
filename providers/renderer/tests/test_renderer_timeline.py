"""The transcript's shapes, the cuts, the captions and the output timeline."""
from __future__ import annotations

import copy

import pytest

import renderer_kit as K
import _edl
import _timeline as T
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
FPS = 30


def words(spans, seg=0):
    return [{"index": k, "text": "w%d" % k, "start": s, "end": e, "segment": seg, "estimated": False, "dropped": False} for k, (s, e) in enumerate(spans)]


def refused(fn, *a):
    with pytest.raises(Refusal) as e:
        fn(*a)
    return e.value


# ---------------------------------------------------------------- the transcript of the transcriber

def test_the_transcribers_format_is_read_and_every_word_is_hardened():
    tr = T.check_transcript(K.build_transcript(), DATA["limits"])
    assert tr["words"][0]["text"] == "Hey," and len(tr["segments"]) == len(K.SENTENCES)
    bad = K.build_transcript()
    bad["words"][2]["text"] = "ok\u202e"
    assert refused(T.check_transcript, bad, DATA["limits"]).code == "forbidden_character"
    for key, value, code in (("schema_version", 2, "transcript_schema"), ("duration", 0, "transcript_duration"), ("words", [], "transcript_words")):
        doc = K.build_transcript()
        doc[key] = value
        assert refused(T.check_transcript, doc, DATA["limits"]).code == code
    doc = K.build_transcript()
    doc["words"][1]["index"] = 7
    assert refused(T.check_transcript, doc, DATA["limits"]).code == "word_index"
    doc = K.build_transcript()
    del doc["words"][0]["index"]
    doc["words"][0]["i"] = 0
    assert refused(T.check_transcript, doc, DATA["limits"]).code == "word_index"


def test_a_transcript_with_too_many_words_is_refused():
    doc = K.build_transcript()
    limits = dict(DATA["limits"], words_max=5)
    assert refused(T.check_transcript, doc, limits).code == "too_many_words"


# ---------------------------------------------------------------- the shapes of a real transcript

def normalised(doc):
    tr = T.check_transcript(doc, DATA["limits"])
    return T.normalise_words(tr["words"], tr["segments"], tr["duration"])


def test_zero_length_words_are_spread_between_their_start_and_the_next_start_and_flagged():
    doc = K.real_shape_transcript()
    out, report = normalised(doc)
    run = [out[i] for i in (2, 3, 4)]
    assert all(w["estimated"] for w in run)
    nxt = out[5]["start"]
    assert run[0]["start"] == pytest.approx(doc["words"][2]["start"], abs=1e-3)
    # even slots, each at least 40 ms, in order, ending where the next word starts (or where the minimum ran past it)
    slots = [w["end"] - w["start"] for w in run]
    assert all(s >= 0.04 - 1e-9 for s in slots) and max(slots) - min(slots) < 1e-3
    assert run[0]["end"] == pytest.approx(run[1]["start"]) and run[2]["end"] <= nxt + 1e-3
    assert report["spread_runs"] >= 2 and report["zero_length_words"] >= 5
    assert all(w["end"] > w["start"] for w in out if not w["dropped"])


def test_a_start_that_goes_back_in_time_is_clamped():
    doc = K.real_shape_transcript()
    out, report = normalised(doc)
    live = [w for w in out if not w["dropped"]]
    assert all(b["start"] >= a["start"] for a, b in zip(live, live[1:]))
    assert report["clamped_starts"] >= 1
    assert out[14]["start"] == out[13]["start"] or out[14]["start"] > out[13]["start"]


def test_a_repeated_sentence_squeezed_into_a_fraction_of_a_second_is_dropped_and_reported():
    doc = K.real_shape_transcript()
    out, report = normalised(doc)
    dropped = [w for w in out if w["dropped"]]
    assert len(dropped) == 21 and report["dropped_words"] == 21
    assert report["dropped_segments"][0]["words"] == 21 and report["dropped_segments"][0]["seconds"] == pytest.approx(0.4)
    assert not any(w["dropped"] for w in out[:-21])
    assert [w["index"] for w in out] == list(range(len(doc["words"])))        # indices are never renumbered


def test_a_normal_fast_segment_is_not_dropped_and_a_short_one_never_is():
    doc = K.build_transcript()
    out, report = normalised(doc)
    assert report["dropped_words"] == 0
    # two words in 0.01 s are under the 3-word minimum
    tiny = K.build_transcript([(0.5, "hi there"), (0.5, "bye now friend")])
    tiny["segments"][0]["end"] = tiny["segments"][0]["start"] + 0.01
    out, report = normalised(tiny)
    assert report["dropped_words"] == 0


def test_the_base_list_of_a_real_shaped_transcript_has_no_refused_word_and_drops_the_repeat(tmp_path):
    doc = K.real_shape_transcript()
    analysis = {"facts": {"duration": doc["duration"] + 0.1, "sha256": "a" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": []}
    analysis["silences"] = [{"start": 0.0, "end": 0.7}, {"start": doc["words"][-22]["end"] + 0.2, "end": doc["duration"] + 0.1}]
    edl, notes = _edl.build_base(doc, analysis, DATA, {})
    assert len(edl["words"]) == len(doc["words"]) - 21
    assert edl["normalisation"]["dropped_words"] == 21
    assert all(w["end"] > w["start"] for w in edl["words"])
    assert any(w.get("estimated") for w in edl["words"])
    _edl.check_edl(edl, DATA, VOCAB, {})        # the base list passes its own check
    assert sum(b - a for a, b in edl["kept"]) == edl["out_frames"]


# ---------------------------------------------------------------- cuts

def test_leading_and_trailing_silence_are_cut_with_a_margin():
    kept = T.kept_ranges(words([(2.0, 2.4), (2.5, 3.0)]), 6.0, FPS)
    assert len(kept) == 1
    assert kept[0][0] == pytest.approx(1.90 * FPS, abs=1.5) and kept[0][1] == pytest.approx(3.14 * FPS, abs=1.5)


def test_without_audio_a_gap_over_the_threshold_is_cut_and_a_short_gap_is_kept():
    kept = T.kept_ranges(words([(1.0, 1.4), (1.6, 2.0), (3.5, 3.9)]), 5.0, FPS)
    assert len(kept) == 2 and kept[0][1] / FPS == pytest.approx(2.14, abs=0.04) and kept[1][0] / FPS == pytest.approx(3.4, abs=0.04)


def test_no_word_is_ever_cut():
    w = words([(0.5, 0.9), (2.2, 2.6), (4.5, 4.9)])
    for silences in (None, [(0.0, 0.45), (0.95, 2.15), (2.65, 4.45), (4.95, 6.0)]):
        kept = T.kept_ranges(w, 6.0, FPS, silences)
        for word in w:
            assert any(a / FPS <= word["start"] and word["end"] <= b / FPS for a, b in kept), silences


def test_silence_is_the_cut_signal_a_short_pause_is_cut_where_the_old_gap_rule_kept_it():
    w = words([(1.0, 1.6), (2.0, 2.6)])
    kept = T.kept_ranges(w, 4.0, FPS, silences=[(0.0, 0.9), (1.6, 2.0), (2.6, 4.0)])
    assert len(kept) == 2 and kept[0][1] / FPS == pytest.approx(1.74, abs=0.04) and kept[1][0] / FPS == pytest.approx(1.9, abs=0.04)
    assert len(T.kept_ranges(w, 4.0, FPS, silences=None)) == 1          # a 0.4 s gap is under the word-gap threshold


def test_no_silence_found_means_no_cut_and_words_only_protect_speech():
    w = words([(1.0, 1.4), (3.0, 3.4)])
    assert len(T.kept_ranges(w, 4.0, FPS, silences=[])) == 1
    kept = T.kept_ranges(w, 4.0, FPS, silences=[(1.8, 2.6)])
    assert len(kept) == 2 and kept[0][1] / FPS == pytest.approx(1.94, abs=0.04) and kept[1][0] / FPS == pytest.approx(2.5, abs=0.04)
    soft = words([(1.0, 1.5)])
    assert len(T.kept_ranges(soft, 3.0, FPS, silences=[(1.2, 1.4)])) == 1   # a word is not cut for silence the detector hears inside it


def test_a_stretched_word_is_cut_inside_its_span_where_there_is_silence():
    w = [{"index": 0, "text": "dollars", "start": 1.0, "end": 3.2, "segment": 0, "estimated": False, "dropped": False},
         {"index": 1, "text": "next", "start": 3.3, "end": 3.7, "segment": 0, "estimated": False, "dropped": False}]
    assert T.protected_spans(w)[0][1] < 2.0                              # protected only for the time the word takes
    kept = T.kept_ranges(w, 5.0, FPS, silences=[(0.0, 0.9), (1.8, 3.2), (3.8, 5.0)])
    assert len(kept) == 2 and kept[0][1] / FPS == pytest.approx(1.94, abs=0.04) and kept[1][0] / FPS == pytest.approx(3.1, abs=0.04)


def test_no_kept_range_is_shorter_than_four_tenths_of_a_second():
    w = words([(1.0, 1.1), (3.0, 3.5)])
    kept = T.kept_ranges(w, 4.0, FPS, silences=[(0.0, 1.0), (1.1, 2.9), (3.6, 4.0)])
    assert all((b - a) / FPS >= 0.4 - 1e-9 for a, b in kept) and len(kept) == 2
    assert kept[0][0] < 27                                               # the short range took the frames it lacked from the shorter cut
    # a range with no word in it is cut, never joined
    kept = T.kept_ranges(words([(1.0, 1.5)]), 4.0, FPS, silences=[(0.0, 0.9), (1.6, 3.8)])
    assert all((b - a) / FPS >= 0.4 - 1e-9 for a, b in kept)


def test_a_forced_cut_is_made_whatever_is_in_it_and_is_never_joined_back():
    w = words([(1.0, 1.4), (1.5, 1.9), (2.0, 2.4), (2.5, 2.9)])
    kept = T.kept_ranges(w, 4.0, FPS, silences=[(0.0, 0.9), (3.0, 4.0)], forced=[(1.45, 2.45)])
    assert len(kept) == 2 and kept[0][1] / FPS == pytest.approx(1.45, abs=0.04) and kept[1][0] / FPS == pytest.approx(2.45, abs=0.04)


def test_ranges_are_on_the_frame_grid_ordered_and_not_empty():
    kept = T.kept_ranges(words([(1.013, 1.9), (3.0071, 3.9)]), 5.0, FPS)
    assert all(isinstance(a, int) and isinstance(b, int) and a < b for a, b in kept)
    assert all(x[1] <= y[0] for x, y in zip(kept, kept[1:]))


def test_a_sliver_left_by_a_silence_that_stops_early_is_cut_but_a_long_unconfirmed_stretch_stays():
    w = words([(1.0, 1.4)])
    kept = T.kept_ranges(w, 4.0, FPS, silences=[(0.0, 0.8), (1.6, 3.9)], long_cut=0)      # 0.18 s left at the end
    assert len(kept) == 1 and kept[0][1] / FPS == pytest.approx(1.74, abs=0.04)
    kept = T.kept_ranges(w, 4.0, FPS, silences=[(0.0, 0.8)], long_cut=0)                  # 2.6 s the detector did not confirm: kept
    assert kept[-1][1] == int(4.0 * FPS)


def test_the_output_timeline_maps_and_snaps():
    kept = [[30, 60], [120, 165]]
    assert T.out_frames_of(kept) == 75
    assert T.src_to_out_seconds(kept, FPS, 1.5) == pytest.approx(0.5)
    assert T.src_to_out_seconds(kept, FPS, 4.5) == pytest.approx(1.5)
    assert T.src_to_out_seconds(kept, FPS, 3.9) == pytest.approx(1.0)       # inside a cut: the nearest kept edge
    assert T.src_to_out_seconds(kept, FPS, 2.1) == pytest.approx(1.0)


# ---------------------------------------------------------------- captions

def test_captions_split_on_punctuation_pauses_and_limits_not_on_the_transcripts_segments():
    live = [dict(w, dropped=False, estimated=False) for w in K.build_transcript()["words"]]
    out_words = [{"index": w["index"], "text": w["text"], "start": w["start"], "end": w["end"]} for w in live]
    chunks = T.caption_chunks(out_words, 4, 26, 0.6)
    assert all(b - a < 4 for a, b in chunks)
    assert chunks[0][0] == 0 and chunks[-1][1] == len(out_words) - 1
    assert all(chunks[k][1] + 1 == chunks[k + 1][0] for k in range(len(chunks) - 1))
    # in the one-word-per-segment mode every word has its own segment, and the chunks are the same
    ml1 = K.build_transcript()
    for w in ml1["words"]:
        w["segment"] = w["index"]
    assert [list(c) for c in chunks] == T.caption_chunks(out_words, 4, 26, 0.6)


def test_chunk_times_touch_when_close_and_hold_when_far():
    by = {0: {"start": 1.0, "end": 1.3}, 1: {"start": 1.4, "end": 1.8}, 2: {"start": 3.5, "end": 3.9}}
    times = T.chunk_times([[0, 0], [1, 1], [2, 2]], by, 5.0, 0.25)
    assert times[0] == (1.0, 1.4) and times[1][1] == pytest.approx(2.05) and times[2][1] == pytest.approx(4.15)


# ---------------------------------------------------------------- the timeline the render draws

def small_edl():
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "b" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, {})
    return edl


def entry(bid, preset, params, a, b, kind="overlays"):
    return kind, {"id": bid, "beat": int(bid[1:]), "preset": preset, "params": params, "word_from": a, "word_to": b, "score": 1.0}


def beats_of(*entries):
    beats = {"schema_version": 1, "threshold": 0.6, "overlays": [], "layouts": [], "slots": [], "report": [], "unmatched": [], "fallbacks": []}
    for kind, e in entries:
        beats[kind].append(e)
    return beats


def test_a_beat_over_words_either_side_of_a_cut_is_one_continuous_range_of_output_frames():
    edl = small_edl()
    assert len(edl["kept"]) > 3                                   # the fixture has cuts between sentences
    by = {w["index"]: w for w in edl["words"]}
    a, b = 6, 14                                                  # words of two sentences, with cuts between them
    tl = _edl.resolve_timeline(edl, beats_of(entry("b1", "list", {"items": "One | Two"}, a, b)), VOCAB, DATA)
    (e,) = tl["beats"]
    assert e["start_frame"] == round(by[a]["start"] * FPS)
    assert e["end_frame"] - e["start_frame"] <= round((by[b]["end"] - by[a]["start"] + DATA["presets"]["list"]["tail"]) * FPS) + 1
    assert e["end_frame"] <= edl["out_frames"]


def test_overlapping_beats_end_where_the_next_starts_and_an_empty_one_is_dropped():
    edl = small_edl()
    beats = beats_of(entry("b1", "quote", {"text": "A long one"}, 6, 20), entry("b2", "keyword", {"text": "Next"}, 9, 12),
                     entry("b3", "keyword", {"text": "Same"}, 9, 12))
    tl = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
    starts = [(e["id"], e["start_frame"], e["end_frame"]) for e in tl["beats"]]
    assert all(x[2] > x[1] for x in starts)
    first, second = tl["beats"][0], tl["beats"][1]
    assert first["end_frame"] <= second["start_frame"] and first.get("clipped")
    assert set(tl["dropped"]) | {e["id"] for e in tl["beats"]} == {"b1", "b2", "b3"}


def test_a_keyword_starts_at_the_word_that_matches_its_text():
    edl = small_edl()
    text = edl["words"][8]["text"].strip(".,:").lower()
    by = {w["index"]: w for w in edl["words"]}
    tl = _edl.resolve_timeline(edl, beats_of(entry("b1", "keyword", {"text": text}, 5, 12)), VOCAB, DATA)
    assert tl["beats"][0]["start_frame"] >= round((by[8]["start"] - 0.05) * FPS) - 1


def test_captions_have_a_frame_range_each_and_nothing_is_lifted_any_more():
    edl = small_edl()
    tl = _edl.resolve_timeline(edl, beats_of(entry("b1", "pip", {"asset": "beat1", "position": "bottom"}, 6, 12, "layouts")), VOCAB, DATA)
    assert tl["captions"] and all("lift" not in c and c["end_frame"] > c["start_frame"] for c in tl["captions"])
    assert [c["start_frame"] for c in tl["captions"]] == sorted(c["start_frame"] for c in tl["captions"])


# ---------------------------------------------------------------- the wordless sound at the edge of a long cut

def lw(index, text, start, end):
    return {"index": index, "text": text, "start": start, "end": end, "segment": 0, "estimated": False, "dropped": False}


# The shape of a real recording (fictional words): a 15 s pause, then a breath and a head turning back to the camera, 1 s of sound
# that holds no word, then the first word of the next part; and the same at the end of a part before the next long pause.
LONG_PAUSE = [lw(0, "This", 87.0, 87.5), lw(1, "ends.", 88.5, 89.3), lw(2, "For", 105.66, 105.9), lw(3, "example", 105.95, 106.5), lw(4, "end.", 107.0, 107.4)]
LONG_PAUSE_SILENCES = [(0.0, 86.9), (89.47, 104.63), (108.0, 110.0)]


def seconds(kept):
    return [[round(a / FPS, 2), round(b / FPS, 2)] for a, b in kept]


def test_a_range_after_a_long_cut_starts_at_its_first_word_not_at_the_breath_before_it():
    kept = T.kept_ranges(LONG_PAUSE, 110.0, FPS, LONG_PAUSE_SILENCES)
    assert kept[1][0] / FPS == pytest.approx(105.66 - 0.10, abs=0.04)             # the sound from 104.63 to 105.66 holds no word
    off = T.kept_ranges(LONG_PAUSE, 110.0, FPS, LONG_PAUSE_SILENCES, long_cut=0)
    assert off[1][0] / FPS == pytest.approx(104.53, abs=0.06)                     # the rule can be turned off


def test_a_range_before_a_long_cut_ends_at_its_last_word_when_wordless_sound_follows_it():
    words = [lw(0, "one", 1.0, 1.4), lw(1, "end.", 2.0, 2.4), lw(2, "after", 20.0, 20.5)]
    sil = [(0.0, 0.9), (3.5, 19.9), (21.0, 22.0)]                                 # 1.1 s of sound after "end." (a breath), then 16 s of nothing
    kept = T.kept_ranges(words, 22.0, FPS, sil)
    assert kept[0][1] / FPS == pytest.approx(2.4 + 0.14, abs=0.04)
    assert T.kept_ranges(words, 22.0, FPS, sil, long_cut=0)[0][1] / FPS == pytest.approx(3.64, abs=0.04)


def test_a_short_wordless_stretch_or_a_short_cut_is_left_alone_and_the_thresholds_are_flags():
    near = [lw(0, "This", 87.0, 87.5), lw(1, "ends.", 88.5, 89.3), lw(2, "For", 105.0, 105.3), lw(3, "end.", 105.4, 105.8)]
    kept = T.kept_ranges(near, 110.0, FPS, LONG_PAUSE_SILENCES)                   # 0.37 s of sound before "For": over 0.3, so it is trimmed ...
    assert kept[1][0] / FPS == pytest.approx(104.92, abs=0.04)
    loose = T.kept_ranges(near, 110.0, FPS, LONG_PAUSE_SILENCES, wordless_max=0.5)  # ... and not with a looser threshold
    assert loose[1][0] / FPS == pytest.approx(104.53, abs=0.06)
    short_cut = T.kept_ranges(LONG_PAUSE, 110.0, FPS, LONG_PAUSE_SILENCES, long_cut=20)   # the cut is 15 s, under a 20 s "long"
    assert short_cut[1][0] / FPS == pytest.approx(104.53, abs=0.06)


def test_a_word_that_runs_across_the_edge_of_a_range_keeps_the_edge():
    words = [lw(0, "one", 1.0, 1.4), lw(1, "stretched", 103.0, 106.5), lw(2, "end.", 107.0, 107.4)]
    kept = T.kept_ranges(words, 110.0, FPS, [(0.0, 0.9), (1.5, 102.0), (108.0, 110.0)])
    assert all(r[0] / FPS <= 103.0 or r[0] / FPS >= 107.0 for r in kept)


def test_the_cut_settings_are_flags_of_base_and_refused_when_not_numbers(tmp_path):
    doc = K.build_transcript()
    analysis = K.write_json(tmp_path / "a.json", {"facts": {"duration": doc["duration"], "sha256": "d" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None})
    tr = K.write_json(tmp_path / "t.json", doc)
    rc, out, err = K.run_verb("base", "--transcript", tr, "--analysis", analysis, "--out", tmp_path / "e.json", "--long-cut", "1.5", "--wordless-max", "0.2")
    assert rc == 0, err
    rc, out, err = K.run_verb("base", "--transcript", tr, "--analysis", analysis, "--out", tmp_path / "f.json", "--long-cut", "-1")
    assert rc == 1 and err.startswith("refused: bad_cut_setting")


# ---------------------------------------------------------------- phantom words and breaths

def test_a_word_the_transcriber_put_into_silence_protects_nothing_and_the_silence_is_cut():
    """A transcriber spreads the first words over the quiet start of a recording: words that silence covers have no energy."""
    words = [lw(0, "This", 0.0, 0.41), lw(1, "starts", 0.41, 0.9), lw(2, "late", 0.9, 1.3), lw(3, "really", 2.0, 2.5), lw(4, "now.", 2.6, 3.0)]
    sil = [(0.0, 1.9), (3.4, 5.0)]
    assert [w["text"] for w in T.real_words(words, sil)] == ["really", "now."]
    kept = T.kept_ranges(words, 5.0, FPS, sil)
    assert kept[0][0] / FPS == pytest.approx(1.8, abs=0.04) and kept[0][1] / FPS == pytest.approx(3.54, abs=0.06)
    assert T.kept_ranges(words, 5.0, FPS, [])[0][0] == 0                       # with no silence found the words decide, and nothing is cut


def test_a_short_range_with_no_real_word_is_not_speech_and_is_cut_but_one_with_a_word_stays():
    words = [lw(0, "first", 1.0, 1.5), lw(1, "second", 8.0, 8.5)]
    sil = [(0.0, 0.9), (1.7, 5.0), (6.2, 7.9), (8.7, 10.0)]                   # 1.2 s of sound between two silences, no word in it: a cough
    kept = T.kept_ranges(words, 10.0, FPS, sil, long_cut=0)
    assert [[round(a / FPS), round(b / FPS)] for a, b in kept] == [[1, 2], [8, 9]]
    loose = T.kept_ranges(words, 10.0, FPS, sil, long_cut=0, wordless_keep=1.0)
    assert len(loose) == 3                                                    # the threshold is a number that can be changed


def test_a_soft_first_word_that_silence_covers_still_sets_where_a_range_after_a_long_cut_starts():
    """The transcriber puts "Por" at 105.66 and silencedetect calls 105.58 to 106.00 silent (the word starts soft): the range after the
    long cut starts at that word less the head pad, and is not cut as a range with no real word, so the first word is not clipped."""
    words = [lw(0, "end.", 88.5, 89.3), lw(1, "Por", 105.66, 105.83), lw(2, "example,", 105.83, 106.34), lw(3, "we", 106.34, 106.62)]
    sil = [(0.0, 88.4), (89.45, 104.735), (105.577, 106.001), (106.9, 110.0)]
    assert [w["text"] for w in T.real_words(words, sil)] == ["end.", "example,", "we"]      # "Por" is a phantom to the cut planner ...
    kept = T.kept_ranges(words, 110.0, FPS, sil)
    assert kept[1][0] / FPS == pytest.approx(105.66 - 0.10, abs=0.04)                      # ... and still keeps its attack


def test_a_range_a_few_frames_short_takes_them_from_the_shorter_cut_and_no_long_cut_is_given_up():
    words = [lw(0, "x", 20.0, 20.05)]
    kept = T.kept_ranges(words, 40.0, FPS, [(0.0, 19.99), (20.06, 40.0)], long_cut=0)      # two cuts of about 20 s around a 0.3 s range
    assert len(kept) == 1 and kept[0][1] - kept[0][0] == 12                                 # 0.4 s: the missing frames came from a cut, which stays
    assert kept[0][0] / FPS > 19.0 and kept[0][1] / FPS < 21.0


def test_the_first_word_after_a_long_cut_is_not_cut_by_the_next_cut():
    words = [lw(0, "end.", 88.5, 89.3), lw(1, "Por", 105.66, 105.83), lw(2, "example,", 105.83, 106.34), lw(3, "we", 106.34, 106.62)]
    sil = [(0.0, 88.4), (89.45, 104.735), (105.255, 105.539), (105.577, 106.001), (106.9, 110.0)]       # the soft word sits in a silence the detector found
    kept = T.kept_ranges(words, 110.0, FPS, sil)
    assert kept[1][0] / FPS == pytest.approx(105.66 - 0.10, abs=0.04) and kept[1][1] / FPS > 106.5


def test_touching_silences_are_one_silence():
    words = [lw(0, "a", 3.0, 3.4)]
    one = T.kept_ranges(words, 6.0, FPS, [(0.0, 1.5), (1.5, 2.0), (4.0, 6.0)])
    split = T.kept_ranges(words, 6.0, FPS, [(0.0, 2.0), (4.0, 6.0)])
    assert one == split and one[0][0] / FPS == pytest.approx(1.9, abs=0.04)


def transcript_of(spans, duration):
    """A transcript with one segment per run of words: spans is [(text, start, end)]."""
    return {"schema_version": 1, "language": "en", "duration": duration, "facts": K.facts_block(),
            "words": [{"index": k, "text": t, "start": a, "end": b, "segment": 0} for k, (t, a, b) in enumerate(spans)],
            "segments": [{"index": 0, "start": spans[0][1], "end": spans[-1][2], "text": " ".join(t for t, _, _ in spans), "first_word": 0,
                          "last_word": len(spans) - 1}]}


def base_of(spans, silences, duration):
    analysis = {"facts": {"duration": duration, "sha256": "a" * 64, "width": 1080, "height": 1920, "has_audio": True},
                "silences": [{"start": a, "end": b} for a, b in silences]}
    edl, _ = _edl.build_base(transcript_of(spans, duration), analysis, DATA, {})
    return edl


def test_opening_words_squeezed_into_the_leading_silence_are_retimed_after_it_and_keep_their_captions():
    """The transcriber put the opening hook (3 words) into the leading silence, 0.0 to 1.2 s; the person said it after 2.0 s. The words keep
    their captions and indices, are moved into the voiced span after the silence (up to the next live word), and the first caption
    is the first word."""
    spans = [("You", 0.0, 0.4), ("know", 0.4, 0.8), ("what", 0.8, 1.2), ("Naruto", 3.0, 3.4), ("said.", 3.45, 3.9)]
    edl = base_of(spans, [(0.0, 2.0), (4.2, 6.0)], 6.0)
    assert [w["index"] for w in edl["words"]] == [0, 1, 2, 3, 4]
    assert edl["captions"]["chunks"][0][0] == 0
    moved = edl["normalisation"]["retimed_words"]
    assert [m["index"] for m in moved] == [0, 1, 2] and edl["normalisation"]["unplaced_words"] == []
    assert moved[0]["from"] == [0.0, 0.4] and moved[0]["to"][0] == pytest.approx(2.0) and moved[-1]["to"][1] <= 3.0 + 1e-6
    assert all(m["to"][1] - m["to"][0] >= 0.12 - 1e-6 for m in moved)                           # the minimum word length
    by = {w["index"]: w for w in edl["words"]}
    assert by[0]["start"] < by[1]["start"] < by[2]["start"] < by[3]["start"] and by[0]["start"] < 0.3         # on the output timeline, near its start
    assert all(w["end"] > w["start"] for w in edl["words"])
    _edl.check_edl(edl, DATA, VOCAB, {})


def test_a_run_of_words_squeezed_into_a_pause_in_the_middle_of_speech_is_retimed_after_the_pause():
    spans = [("Hello", 0.6, 1.0), ("there", 1.0, 1.4), ("ok", 2.0, 2.3), ("again", 3.9, 4.3), ("friend.", 4.35, 4.8)]
    edl = base_of(spans, [(0.0, 0.5), (1.55, 3.4), (5.0, 6.0)], 6.0)
    assert [w["text"] for w in edl["words"]] == ["Hello", "there", "ok", "again", "friend."]
    assert edl["normalisation"]["retimed_words"] == [{"index": 2, "from": [2.0, 2.3], "to": [3.4, 3.9]}]
    assert edl["normalisation"]["unplaced_words"] == []
    by = {w["index"]: w for w in edl["words"]}
    assert by[1]["end"] <= by[2]["start"] <= by[3]["start"]                                       # in order on the output timeline
    _edl.check_edl(edl, DATA, VOCAB, {})


def test_a_word_with_no_voiced_span_in_its_range_is_dropped_and_reported():
    spans = [("Hello", 0.6, 1.0), ("there.", 1.0, 1.58), ("bye", 4.0, 4.3)]
    edl = base_of(spans, [(0.0, 0.5), (1.6, 6.0)], 6.0)
    assert [w["text"] for w in edl["words"]] == ["Hello", "there."]
    assert edl["normalisation"]["unplaced_words"] == [{"index": 2, "start": 4.0, "end": 4.3}] and edl["normalisation"]["retimed_words"] == []
    _edl.check_edl(edl, DATA, VOCAB, {})


def test_a_word_squeezed_into_a_pause_with_voiced_sound_before_it_goes_before_the_pause_when_nothing_follows():
    ws = [lw(0, "end", 1.0, 1.3), lw(1, "ok", 3.0, 3.3)]
    moved, unplaced = T.retime_misplaced(ws, [(1.5, 6.0)])
    assert unplaced == [] and moved == [{"index": 1, "from": [3.0, 3.3], "to": [1.3, 1.5]}]
    assert (ws[1]["start"], ws[1]["end"], ws[1]["retimed"]) == (1.3, 1.5, True)
    assert T.retime_misplaced([lw(0, "x", 1.0, 1.3)], None) == ([], [])


def test_a_confirmed_retake_that_an_extended_long_cut_swallows_keeps_its_forced_flag():
    """A long cut that extends to the first word after it takes a later cut that lies inside the extension; if that cut was a confirmed
    retake, the merged cut stays forced, so the short-range rule never gives frames back to it."""
    ws = [lw(0, "second", 10.6, 11.0)]
    cuts = [(52, 297, False), (300, 312, True)]
    out = T.trim_wordless(cuts, ws, FPS, 0.10, 0.14, 2.0, 0.3)
    assert out == [(52, 315, True)]
    assert T.trim_wordless([(52, 297, False), (300, 312, False)], ws, FPS, 0.10, 0.14, 2.0, 0.3) == [(52, 315, False)]


def test_an_edit_list_of_version_one_is_refused_with_its_own_code():
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "a" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, {})
    assert edl["schema_version"] == 2
    old = copy.deepcopy(edl)
    old["schema_version"] = 1
    assert refused(_edl.check_edl, old, DATA, VOCAB, {}).code == "edl_schema_outdated"
    old["schema_version"] = 3
    assert refused(_edl.check_edl, old, DATA, VOCAB, {}).code == "schema_version"


def test_an_edit_list_of_version_one_is_refused_with_its_own_code():
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "a" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, {})
    assert edl["schema_version"] == 2
    old = copy.deepcopy(edl)
    old["schema_version"] = 1
    assert refused(_edl.check_edl, old, DATA, VOCAB, {}).code == "edl_schema_outdated"
    old["schema_version"] = 3
    assert refused(_edl.check_edl, old, DATA, VOCAB, {}).code == "schema_version"


def test_when_the_next_live_word_is_timed_before_the_sound_starts_the_run_takes_it_in_until_there_is_room():
    """The shape of a real opening: five words squeezed into the leading silence, and the next word timed at 1.94, six milliseconds before
    the silence ends: there is no span between the silence and it, so the words that follow are moved too, until the run has room."""
    ws = [lw(0, "a", 0.0, 0.4), lw(1, "b", 0.4, 0.8), lw(2, "c", 0.8, 1.2), lw(3, "next", 1.94, 2.47), lw(4, "after", 2.47, 2.98), lw(5, "then", 2.98, 3.76)]
    moved, unplaced = T.retime_misplaced(ws, [(0.0, 1.946)])
    assert unplaced == [] and [m["index"] for m in moved] == [0, 1, 2, 3]                        # the three, and the word timed too early
    assert ws[0]["start"] == pytest.approx(1.946, abs=1e-3) and ws[3]["end"] == pytest.approx(2.47, abs=1e-3) and ws[4]["start"] == 2.47
    assert all(a["end"] <= b["start"] + 1e-6 and b["end"] - b["start"] >= 0.12 for a, b in zip(ws, ws[1:]))


def test_a_run_retimed_into_sound_the_old_times_would_have_cut_is_kept_whole_by_the_cuts():
    """Three words squeezed into a long silence (3.0 to 3.9 s) that are really said right after it (10.0 s): with their old times the
    cut planner thought the sound after the long cut was wordless (the next word is at 11.0) and trimmed 10.0 to 10.8 away. Re-timed
    before the cuts are planned, the range after the cut starts at the sound."""
    def make():
        return [lw(0, "start.", 1.0, 1.4), lw(1, "ok", 3.0, 3.3), lw(2, "go", 3.3, 3.6), lw(3, "now", 3.6, 3.9), lw(4, "later", 11.0, 11.4), lw(5, "end.", 11.45, 11.9)]
    sil = [(0.0, 0.8), (1.5, 10.0), (12.1, 14.0)]
    old = T.kept_ranges(make(), 14.0, FPS, sil)
    assert old[1][0] / FPS == pytest.approx(10.9, abs=0.05)                           # the sound 10.0 to 10.9 would be cut
    ws = make()
    moved, unplaced = T.retime_misplaced(ws, sil)
    assert [m["index"] for m in moved] == [1, 2, 3] and unplaced == [] and ws[1]["start"] == pytest.approx(10.0)
    kept = T.kept_ranges(ws, 14.0, FPS, sil)
    assert kept[1][0] / FPS == pytest.approx(9.9, abs=0.04) and kept[1][1] / FPS > 11.9       # kept from the sound, 0.10 s head pad
    doc = transcript_of([("start.", 1.0, 1.4), ("ok", 3.0, 3.3), ("go", 3.3, 3.6), ("now", 3.6, 3.9), ("later", 11.0, 11.4), ("end.", 11.45, 11.9)], 14.0)
    analysis = {"facts": {"duration": 14.0, "sha256": "a" * 64, "width": 1080, "height": 1920, "has_audio": True},
                "silences": [{"start": a, "end": b} for a, b in sil]}
    edl, _ = _edl.build_base(doc, analysis, DATA, {})
    assert any(a / FPS <= 10.0 < b / FPS for a, b in edl["kept"])                    # and the base list keeps it


def test_a_short_word_in_a_short_pause_between_two_words_stays_where_it_is():
    """"a" in "working a seu favor": 0.08 s long, inside a 0.35 s pause between two words. It is a soft word in its place, not a misplaced
    one: it keeps its times and is neither moved nor dropped."""
    ws = [lw(0, "trabalhando", 187.82, 188.71), lw(1, "a", 188.71, 188.79), lw(2, "seu", 188.86, 189.15), lw(3, "favor?", 189.15, 190.16)]
    moved, unplaced = T.retime_misplaced(ws, [(188.689, 189.042)])
    assert moved == [] and unplaced == [] and (ws[1]["start"], ws[1]["end"]) == (188.71, 188.79)
    # the same word, 0.08 s long, in a long pause, is misplaced; and so is a long word in a short pause
    ws = [lw(0, "x", 1.0, 1.4), lw(1, "a", 2.0, 2.08), lw(2, "y", 4.0, 4.4)]
    assert [m["index"] for m in T.retime_misplaced(ws, [(1.5, 3.9)])[0]] == [1]
    ws = [lw(0, "x", 1.0, 1.4), lw(1, "word", 1.45, 1.8), lw(2, "y", 2.0, 2.4)]
    assert [m["index"] for m in T.retime_misplaced(ws, [(1.42, 1.85)])[0]] == [1]
