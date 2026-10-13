"""The transcriber reader: the repairs of a provider's raw output, each reported. Fictional words only."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import from_transcriber as FT  # noqa: E402


def raw(words, segments=None, duration=30.0):
    """words: [(text, start, end, segment)]"""
    ws = [{"index": k, "text": t, "start": s, "end": e, "segment": g, "probability": 0.9} for k, (t, s, e, g) in enumerate(words)]
    if segments is None:
        segments = []
        for g in sorted({w["segment"] for w in ws}):
            sw = [w for w in ws if w["segment"] == g]
            segments.append({"index": g, "start": sw[0]["start"], "end": sw[-1]["end"], "first_word": sw[0]["index"],
                             "last_word": sw[-1]["index"], "text": " ".join(w["text"] for w in sw)})
    return {"schema_version": 1, "language": "xx", "duration": duration, "words": ws, "segments": segments}


class ZeroLengthRuns(unittest.TestCase):
    def test_a_run_is_spread_evenly_up_to_the_next_words_start(self):
        r = raw([("one", 1.0, 1.4, 0), ("alpha", 5.0, 5.0, 1), ("beta", 5.0, 5.0, 1), ("gamma", 5.0, 5.0, 1), ("delta", 6.2, 6.8, 1)])
        tr, fixes = FT.normalise(r)
        w = tr["words"]
        self.assertTrue(all(x["estimated"] for x in w[1:4]))
        self.assertFalse(w[0]["estimated"])
        self.assertAlmostEqual(w[1]["start"], 5.0)               # the run spreads from where the model put it ...
        self.assertAlmostEqual(w[3]["end"], 6.2, places=3)      # ... to the next word's start
        slots = [x["end"] - x["start"] for x in w[1:4]]
        self.assertAlmostEqual(max(slots), min(slots), places=2)  # evenly
        self.assertEqual([f["fix"] for f in fixes], ["spread_zero_length_run"])
        self.assertEqual(fixes[0]["words"], 3)

    def test_with_no_room_each_word_gets_at_least_forty_milliseconds_before_the_next(self):
        r = raw([("aa", 1.0, 1.4, 0), ("bb", 4.0, 4.0, 1), ("cc", 4.0, 4.0, 1), ("dd", 4.0, 4.5, 1)])
        tr, _ = FT.normalise(r)
        w = tr["words"]
        for x in w[1:3]:
            self.assertGreaterEqual(x["end"] - x["start"], 0.04 - 1e-6)
        self.assertLessEqual(w[2]["end"], w[3]["start"] + 1e-6)
        self.assertAlmostEqual(w[2]["end"], 4.0, places=2)
        self.assertLess(w[1]["start"], 4.0)                     # it is placed before, in the pause

    def test_a_run_never_starts_before_the_previous_word_ends(self):
        r = raw([("aa", 1.0, 3.9, 0), ("bb", 4.0, 4.0, 1), ("cc", 4.0, 4.0, 1), ("dd", 4.0, 4.5, 1)])
        tr, _ = FT.normalise(r)
        self.assertGreaterEqual(tr["words"][1]["start"], tr["words"][0]["end"] - 1e-6)

    def test_a_trailing_run_is_given_a_slot_each(self):
        r = raw([("aa", 1.0, 1.4, 0), ("bb", 9.0, 9.0, 1), ("cc", 9.0, 9.0, 1)])
        tr, _ = FT.normalise(r)
        self.assertGreater(tr["words"][2]["end"], tr["words"][1]["end"] - 1e-9)
        self.assertTrue(all(x["end"] > x["start"] for x in tr["words"]))


class Clamping(unittest.TestCase):
    def test_times_become_monotonic_and_non_overlapping(self):
        r = raw([("aa", 1.0, 2.0, 0), ("bb", 1.5, 2.5, 0), ("cc", 2.4, 2.9, 0)])
        tr, fixes = FT.normalise(r)
        w = tr["words"]
        for a, b in zip(w, w[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-9)
        self.assertTrue(all(x["end"] - x["start"] >= 0.04 - 1e-9 for x in w))
        self.assertTrue(any(f["fix"] == "clamped" for f in fixes))

    def test_nothing_runs_past_the_recording(self):
        r = raw([("aa", 29.5, 31.0, 0)], duration=30.0)
        tr, _ = FT.normalise(r)
        self.assertLessEqual(tr["words"][0]["end"], 30.0)


class ImpossibleSegments(unittest.TestCase):
    def test_a_segment_over_eight_words_a_second_is_dropped_and_reported(self):
        good = [("w%d" % k, 1.0 + k * 0.4, 1.3 + k * 0.4, 0) for k in range(6)]
        loop = [("x%d" % k, 20.0, 20.0, 1) for k in range(10)]
        r = raw(good + loop, segments=[{"index": 0, "start": 1.0, "end": 3.3, "first_word": 0, "last_word": 5, "text": "a"},
                                       {"index": 1, "start": 20.0, "end": 20.5, "first_word": 6, "last_word": 15, "text": "b"}])
        tr, fixes = FT.normalise(r)
        self.assertEqual(len(tr["words"]), 6)
        drop = [f for f in fixes if f["fix"] == "dropped_segment"]
        self.assertEqual(len(drop), 1)
        self.assertEqual((drop[0]["src_from"], drop[0]["src_to"], drop[0]["words"]), (6, 15, 10))
        self.assertGreater(drop[0]["rate"], 8)

    def test_a_short_fast_segment_of_two_words_is_kept(self):
        r = raw([("aa", 1.0, 1.4, 0), ("bb", 5.0, 5.05, 1), ("cc", 5.05, 5.1, 1)],
                segments=[{"index": 0, "start": 1.0, "end": 1.4, "first_word": 0, "last_word": 0, "text": "a"},
                          {"index": 1, "start": 5.0, "end": 5.1, "first_word": 1, "last_word": 2, "text": "b c"}])
        tr, fixes = FT.normalise(r)
        self.assertEqual(len(tr["words"]), 3)
        self.assertFalse([f for f in fixes if f["fix"] == "dropped_segment"])

    def test_indices_and_segments_are_renumbered_without_holes(self):
        r = raw([("a%d" % k, 1.0 + k * 0.5, 1.4 + k * 0.5, 0) for k in range(3)]
                + [("l%d" % k, 9.0, 9.0, 1) for k in range(5)]
                + [("b%d" % k, 12.0 + k * 0.5, 12.4 + k * 0.5, 2) for k in range(3)],
                segments=[{"index": 0, "start": 1.0, "end": 2.4, "first_word": 0, "last_word": 2, "text": ""},
                          {"index": 1, "start": 9.0, "end": 9.3, "first_word": 3, "last_word": 7, "text": ""},
                          {"index": 2, "start": 12.0, "end": 13.4, "first_word": 8, "last_word": 10, "text": ""}])
        tr, _ = FT.normalise(r)
        self.assertEqual([w["i"] for w in tr["words"]], list(range(6)))
        self.assertEqual(sorted({w["segment"] for w in tr["words"]}), [0, 1])
        self.assertEqual(tr["words"][3]["src_index"], 8)


class Retiming(unittest.TestCase):
    def test_words_the_model_put_inside_silence_are_placed_over_the_speech(self):
        # the model timed the first sentence over the leading silence; the audio has speech from 4.0 to 6.0 only
        words = [("one", 0.0, 0.5, 0), ("two", 0.5, 1.0, 0), ("three", 1.0, 1.5, 0), ("four", 4.2, 4.8, 0),
                 ("five", 5.0, 5.8, 0), ("six", 10.0, 10.5, 1)]
        tr, fixes = FT.normalise(raw(words, duration=12.0), silences=[(0.0, 4.0), (6.0, 9.9)])
        self.assertTrue([f for f in fixes if f["fix"] == "retimed_segment"])
        for w in tr["words"][:5]:
            self.assertGreaterEqual(w["start"], 4.0 - 1e-6)
            self.assertLessEqual(w["end"], 6.3)
            self.assertTrue(w["retimed"])
        self.assertFalse(tr["words"][5]["retimed"])

    def test_no_retiming_without_silences(self):
        words = [("one", 0.0, 0.5, 0), ("two", 0.5, 1.0, 0), ("three", 1.0, 1.5, 0)]
        tr, fixes = FT.normalise(raw(words))
        self.assertFalse([f for f in fixes if f["fix"] == "retimed_segment"])

    def test_a_word_never_straddles_a_silence(self):
        words = [("aaaa", 0.0, 0.0, 0)] * 0
        words = [("w%d" % k, 0.0, 0.0, 0) for k in range(8)] + [("end", 3.0, 3.5, 0)]
        tr, _ = FT.normalise(raw(words, duration=8.0), silences=[(0.0, 1.0), (2.0, 2.6)])
        for w in tr["words"]:
            self.assertFalse(w["start"] < 2.0 - 1e-6 and w["end"] > 2.0 + 1e-6 and w["end"] < 2.6)


class Shape(unittest.TestCase):
    def test_malformed_input_is_refused(self):
        with self.assertRaises(FT.TranscriptError):
            FT.normalise({"words": []})
        with self.assertRaises(FT.TranscriptError):
            FT.normalise({"duration": 3, "words": [{"text": "a"}]})

    def test_the_output_passes_the_transcript_check_of_the_edit_list(self):
        import edl as E
        r = raw([("one", 1.0, 1.4, 0), ("two", 2.0, 2.0, 1), ("three", 2.0, 2.0, 1), ("four", 2.5, 3.0, 1)])
        tr, _ = FT.normalise(r)
        E.check_transcript(tr)

    def test_cli_writes_the_transcript_and_the_fixes(self):
        with tempfile.TemporaryDirectory() as d:
            src, out = os.path.join(d, "raw.json"), os.path.join(d, "t.json")
            with open(src, "w") as fh:
                json.dump(raw([("one", 1.0, 1.4, 0), ("two", 2.0, 2.0, 1), ("three", 2.0, 2.5, 1)]), fh)
            self.assertEqual(FT.main(["--raw", src, "--out", out]), 0)
            with open(out) as fh:
                tr = json.load(fh)
            self.assertEqual(len(tr["words"]), 3)
            self.assertTrue(tr["fixes"])
            self.assertEqual(FT.main(["--raw", os.path.join(d, "none.json"), "--out", out]), 2)


if __name__ == "__main__":
    unittest.main()
