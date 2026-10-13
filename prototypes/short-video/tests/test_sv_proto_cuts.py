"""Silence-first cuts: silence is the primary signal, words only protect speech. Fictional timings."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import cuts as C  # noqa: E402

FPS = 30


def words(spans, seg=0):
    return [{"i": k, "text": "w%d" % k, "start": s, "end": e, "segment": seg} for k, (s, e) in enumerate(spans)]


def contains(kept, a, b):
    return any(s <= a + 1e-6 and b <= e + 1e-6 for s, e in kept)


class SilenceFirst(unittest.TestCase):
    def test_a_silence_is_cut_with_a_tail_before_it_and_an_attack_after_it(self):
        w = words([(1.0, 2.0), (4.0, 5.0)])
        r = C.plan(w, [(0.0, 0.9), (2.1, 3.9), (5.2, 6.0)], 6.0, FPS, pad_head=0.10, pad_tail=0.14)
        kept = r["kept"]
        self.assertEqual(len(kept), 2)
        self.assertAlmostEqual(kept[0][0], 0.9 - 0.10, delta=1.5 / FPS)       # attack of the first word
        self.assertAlmostEqual(kept[0][1], 2.1 + 0.14, delta=1.5 / FPS)       # tail of the word before the silence
        self.assertAlmostEqual(kept[1][0], 3.9 - 0.10, delta=1.5 / FPS)
        self.assertAlmostEqual(kept[1][1], 5.2 + 0.14, delta=1.5 / FPS)

    def test_the_outer_edges_of_the_leading_and_trailing_silence_are_cut_without_a_margin(self):
        r = C.plan(words([(1.0, 2.0)]), [(0.0, 0.9), (2.1, 5.0)], 5.0, FPS)
        self.assertEqual({c["reason"] for c in r["cuts"]}, {"lead", "trail"})
        self.assertAlmostEqual(r["cuts"][0]["start"], 0.0)
        self.assertAlmostEqual(r["cuts"][-1]["end"], 5.0)

    def test_a_pause_shorter_than_what_a_cut_would_leave_is_kept(self):
        w = words([(1.0, 2.0), (2.4, 3.0)])
        r = C.plan(w, [(2.05, 2.35)], 4.0, FPS, min_cut=0.25)
        self.assertEqual(len(r["kept"]), 1)

    def test_a_word_with_energy_is_never_cut(self):
        # silencedetect found a quiet stretch inside a normal word (it is soft speech): the word's span is protected
        w = words([(1.0, 1.6), (3.0, 3.5)])
        r = C.plan(w, [(1.2, 2.9)], 4.0, FPS)
        for word in w:
            self.assertTrue(contains(r["kept"], word["start"], word["end"]), word)
        self.assertEqual(r["clipped_words"], [])

    def test_a_stretched_word_is_cut_where_the_audio_is_silent(self):
        # the model spread one word over 8 s; the audio has speech only at its start and its end
        w = words([(1.0, 9.0), (10.0, 10.5)])
        r = C.plan(w, [(2.0, 8.5), (0.0, 0.5)], 12.0, FPS)
        self.assertFalse(contains(r["kept"], 3.0, 7.0))
        self.assertTrue(contains(r["kept"], 1.0, 1.9))
        self.assertEqual(len(r["cuts_inside_long_words"]), 1)

    def test_a_word_lying_inside_a_silence_protects_nothing(self):
        w = words([(1.0, 1.4), (2.0, 2.3), (4.0, 4.4)])      # the middle word is timed inside a silence: a phantom
        r = C.plan(w, [(1.6, 3.8)], 6.0, FPS)
        self.assertFalse(contains(r["kept"], 2.0, 2.3))

    def test_no_kept_range_is_shorter_than_min_keep_and_a_word_in_it_is_kept(self):
        # a short blip of speech between two silences, holding a word: with the margins it would leave 0.36 s
        w = words([(1.0, 2.0), (2.99, 3.08), (4.2, 5.0)])
        sil = [(2.1, 2.98), (3.1, 4.1)]
        r = C.plan(w, sil, 6.0, FPS, min_keep=0.4)
        self.assertTrue(all(b - a >= 0.4 - 1e-6 for a, b in r["kept"]), r["kept"])
        self.assertTrue(contains(r["kept"], 2.99, 3.08))
        self.assertTrue(r["notes"])

    def test_a_fragment_with_no_word_is_cut_away(self):
        w = words([(1.0, 2.0), (6.0, 7.0)])
        sil = [(2.1, 2.98), (3.1, 5.9)]      # a short noise between two silences, no word in it
        r = C.plan(w, sil, 8.0, FPS, min_keep=0.4)
        self.assertTrue(all(b - a >= 0.4 - 1e-6 for a, b in r["kept"]))
        self.assertFalse(contains(r["kept"], 2.95, 3.2))

    def test_a_short_stretch_with_no_transcribed_word_is_not_speech_and_is_cut(self):
        # the speaker moves between two sentences: 0.9 s of noise, no word, between two silences
        w = words([(1.0, 2.0), (8.0, 9.0)])
        sil = [(0.0, 0.9), (2.1, 4.0), (4.9, 7.9), (9.1, 10.0)]
        r = C.plan(w, sil, 10.0, FPS, wordless=1.5)
        self.assertFalse(contains(r["kept"], 4.1, 4.8))
        self.assertTrue(contains(r["kept"], 1.0, 2.0))
        self.assertTrue(contains(r["kept"], 8.0, 9.0))
        self.assertTrue(any("no speech" in n for n in r["notes"]))
        long_keep = C.plan(w, sil, 10.0, FPS, wordless=0.5)         # over the limit: kept, it may be speech the model missed
        self.assertTrue(contains(long_keep["kept"], 4.1, 4.8))

    def test_kept_ranges_are_on_the_frame_grid_ordered_and_apart(self):
        w = words([(1.013, 2.0), (4.0071, 5.0)])
        r = C.plan(w, [(0.0, 0.97), (2.113, 3.9), (5.2, 6.0)], 6.0, FPS)
        for s, e in r["kept"]:
            self.assertAlmostEqual(s * FPS, round(s * FPS), places=6)
            self.assertAlmostEqual(e * FPS, round(e * FPS), places=6)
        self.assertTrue(all(a[1] < b[0] for a, b in zip(r["kept"], r["kept"][1:])))


class Retakes(unittest.TestCase):
    def test_an_earlier_take_is_cut_from_the_silence_before_it_to_the_silence_before_the_later_one(self):
        w = words([(1.0, 2.0), (4.0, 5.0), (7.0, 8.0)])      # word 1 is the abandoned take
        rt = [{"word_from": 1, "word_to": 1}]
        sil = [(2.1, 3.9), (5.1, 6.9)]
        r = C.plan(w, sil, 9.0, FPS, retakes=rt)
        self.assertFalse(contains(r["kept"], 3.0, 5.0))      # the whole take and the pauses around it are gone
        self.assertTrue(contains(r["kept"], 1.0, 2.0))
        self.assertTrue(contains(r["kept"], 7.0, 8.0))
        self.assertIn("retake", {c["reason"] for c in r["cuts"]})
        # what is left between the two kept words is a short pause (a tail and an attack), not three seconds
        self.assertLess(r["kept"][1][0] - r["kept"][0][1], 0.0 + 1e-6 + 5.0)

    def test_without_silences_around_it_a_retake_is_cut_by_its_words(self):
        w = words([(1.0, 2.0), (2.1, 3.0), (3.1, 4.0)])
        r = C.plan(w, [], 5.0, FPS, retakes=[{"word_from": 1, "word_to": 1}], min_keep=0.4)
        self.assertFalse(contains(r["kept"], 2.2, 2.9))
        self.assertTrue(contains(r["kept"], 1.0, 2.0))
        self.assertTrue(contains(r["kept"], 3.1, 4.0))

    def test_dropped_words_protect_nothing(self):
        w = words([(1.0, 2.0), (2.5, 3.0), (5.0, 6.0)])
        w[1]["dropped"] = True
        r = C.plan(w, [(2.2, 4.9)], 7.0, FPS)
        self.assertFalse(contains(r["kept"], 2.5, 3.0))


class Report(unittest.TestCase):
    def test_the_report_lists_the_numbers_used(self):
        r = C.plan(words([(1.0, 2.0)]), [(0.0, 0.9), (2.1, 4.0)], 4.0, FPS)
        text = C.format_report(r, {"silence_db": -38.0, "silence_min": 0.35})
        self.assertIn("silence_db=-38.0", text)
        self.assertIn("kept ranges", text)


if __name__ == "__main__":
    unittest.main()
