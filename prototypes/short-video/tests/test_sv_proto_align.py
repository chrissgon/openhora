import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import edl as E  # noqa: E402


def mk(text):
    out, t = [], 0.0
    for k, tok in enumerate(text.split()):
        out.append({"i": k, "text": tok, "start": t, "end": t + 0.2, "segment": 0})
        t += 0.25
    return out


def align(line, transcript_text, threshold=0.6):
    w = mk(transcript_text)
    r = E.align_line(line, E.flatten_words(w), threshold)
    if r["matched"]:
        r["word_from"], r["word_to"] = E.expand_digit_words(w, r["word_from"], r["word_to"])
    return r, w


class Alignment(unittest.TestCase):
    def test_exact_line_is_found_inside_longer_speech(self):
        r, w = align("name every dollar", "so the first rule is simple name every dollar and that is it")
        self.assertTrue(r["matched"])
        self.assertEqual([w[r["word_from"]]["text"], w[r["word_to"]]["text"]], ["name", "dollar"])
        self.assertAlmostEqual(r["score"], 1.0)

    def test_normalisation_nfkc_casefold_punctuation(self):
        r, w = align("Don't WAIT, act now!", "dont wait act now")
        self.assertAlmostEqual(r["score"], 1.0)
        r, _ = align("café ＯＫ", "CAFÉ ok")   # NFKC folds fullwidth; combining accent composes
        self.assertTrue(r["matched"])

    def test_fast_speech_with_dropped_and_misrecognised_words(self):
        r, w = align("then do three things each week review adjust and celebrate",
                     "um then do three thing each week review adjust celebrate right")
        self.assertTrue(r["matched"])
        self.assertGreater(r["score"], 0.7)
        self.assertEqual(w[r["word_to"]]["text"], "celebrate")

    def test_ad_lib_inside_the_line(self):
        r, w = align("small steps beat big plans", "small steps honestly really beat big plans")
        self.assertTrue(r["matched"])
        self.assertEqual([w[r["word_from"]]["text"], w[r["word_to"]]["text"]], ["small", "plans"])
        self.assertLess(r["score"], 1.0)

    def test_unmatched_line_is_reported(self):
        r, _ = align("quarterly revenue forecast", "name every dollar and keep going")
        self.assertFalse(r["matched"])

    def test_retake_goes_to_the_last_occurrence(self):
        r, w = align("name every dollar", "name every dollar uh sorry name every dollar now")
        self.assertTrue(r["matched"])
        self.assertEqual(r["word_from"], 5)
        self.assertEqual(r["word_to"], 7)

    def test_better_earlier_take_beats_a_worse_later_one(self):
        r, w = align("name every dollar", "name every dollar uh sorry name a dollar now")
        self.assertEqual(r["word_from"], 0)

    def test_numbers_are_excluded_from_scoring(self):
        r, w = align("that habit saved me 340 dollars in one month",
                     "that habit saved me three hundred forty dollars in one month")
        self.assertTrue(r["matched"])
        r2, w2 = align("that habit saved me 340 dollars in one month", "that habit saved me 340 dollars in one month")
        self.assertAlmostEqual(r2["score"], 1.0)
        self.assertEqual(w2[r2["word_to"]]["text"], "month")

    def test_a_figure_next_to_the_window_is_included(self):
        r, w = align("it grew by", "it grew by 30")
        self.assertEqual(w[r["word_to"]]["text"], "30")

    def test_line_of_only_figures_never_matches(self):
        r, _ = align("2024", "in 2024 we grew")
        self.assertFalse(r["matched"])

    def test_threshold(self):
        r, _ = align("one two three four five six", "one two zzz yyy xxx six", threshold=0.9)
        self.assertFalse(r["matched"])

    def test_reordered_beats_are_flagged(self):
        w = mk("alpha beta gamma delta epsilon zeta eta theta")
        beats = [{"id": "b1", "line": "epsilon zeta eta"}, {"id": "b2", "line": "alpha beta gamma"}]
        res = E.align_beats(w, beats)
        self.assertFalse(res[0]["reordered"])
        self.assertTrue(res[1]["reordered"])
        self.assertTrue(res[1]["matched"])


if __name__ == "__main__":
    unittest.main()
