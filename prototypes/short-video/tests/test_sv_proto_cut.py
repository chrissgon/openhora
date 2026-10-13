import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import edl as E  # noqa: E402

FPS = 30


def words(spans):
    return [{"i": k, "text": "w%d" % k, "start": s, "end": e, "segment": 0} for k, (s, e) in enumerate(spans)]


class KeptRanges(unittest.TestCase):
    def test_leading_and_trailing_silence_are_cut_with_a_margin(self):
        w = words([(2.0, 2.4), (2.5, 3.0)])
        kept = E.kept_ranges(w, 6.0, FPS)
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(kept[0][0], 1.85, delta=1 / FPS)   # first word minus the 0.15 margin
        self.assertAlmostEqual(kept[0][1], 3.15, delta=1 / FPS)   # last word plus the margin

    def test_gap_over_threshold_is_cut_and_short_gap_is_kept(self):
        w = words([(1.0, 1.4), (1.6, 2.0), (3.5, 3.9)])
        kept = E.kept_ranges(w, 5.0, FPS)
        self.assertEqual(len(kept), 2)                       # the 1.5 s gap is cut, the 0.2 s gap is not
        self.assertAlmostEqual(kept[0][1], 2.15, delta=1 / FPS)
        self.assertAlmostEqual(kept[1][0], 3.35, delta=1 / FPS)

    def test_no_word_is_ever_cut(self):
        w = words([(0.5, 0.9), (2.2, 2.6), (4.5, 4.9)])
        kept = E.kept_ranges(w, 6.0, FPS)
        for word in w:
            self.assertTrue(any(s <= word["start"] and word["end"] <= e for s, e in kept))

    def test_silence_list_confirms_cuts(self):
        w = words([(1.0, 1.4), (3.0, 3.4)])
        # the gap 1.4-3.0 is only partly confirmed as silence: 1.8-2.6
        kept = E.kept_ranges(w, 4.0, FPS, silences=[(1.8, 2.6)])
        self.assertEqual(len(kept), 2)
        self.assertAlmostEqual(kept[0][1], 1.8, delta=1 / FPS)
        self.assertAlmostEqual(kept[1][0], 2.6, delta=1 / FPS)

    def test_unconfirmed_gap_is_not_cut(self):
        w = words([(1.0, 1.4), (3.0, 3.4)])
        kept = E.kept_ranges(w, 4.0, FPS, silences=[])
        self.assertEqual(len(kept), 1)

    def test_ranges_are_on_the_frame_grid_and_ordered(self):
        w = words([(1.013, 1.4), (3.0071, 3.4)])
        kept = E.kept_ranges(w, 5.0, FPS)
        for s, e in kept:
            self.assertAlmostEqual(s * FPS, round(s * FPS), places=6)
            self.assertAlmostEqual(e * FPS, round(e * FPS), places=6)
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(kept, kept[1:])))

    def test_margin_too_large_for_the_gap_is_refused(self):
        with self.assertRaises(E.EdlError):
            E.kept_ranges(words([(1.0, 1.4)]), 3.0, FPS, gap=0.3, margin=0.15)


class OutputTimeline(unittest.TestCase):
    def test_map_and_snap(self):
        kmap = E.build_map([(1.0, 2.0), (4.0, 5.5)])
        self.assertAlmostEqual(kmap[-1]["out_end"], 2.5)
        self.assertAlmostEqual(E.src_to_out(kmap, 1.5), 0.5)
        self.assertAlmostEqual(E.src_to_out(kmap, 4.5), 1.5)
        self.assertAlmostEqual(E.src_to_out(kmap, 3.9), 1.0)   # inside a cut: snaps to the next kept edge
        self.assertAlmostEqual(E.src_to_out(kmap, 2.1), 1.0)

    def test_captions_are_on_the_output_timeline(self):
        w = [{"i": 0, "text": "one", "start": 1.0, "end": 1.4, "segment": 0},
             {"i": 1, "text": "two", "start": 5.0, "end": 5.4, "segment": 1}]
        kmap = E.build_map(E.kept_ranges(w, 7.0, FPS))
        chunks = E.caption_chunks(w, kmap)
        self.assertEqual(len(chunks), 2)
        self.assertLess(chunks[1]["start"], 5.0)               # the 3.6 s cut moved it earlier
        self.assertLessEqual(chunks[0]["end"], chunks[1]["start"] + 1e-9)


if __name__ == "__main__":
    unittest.main()
