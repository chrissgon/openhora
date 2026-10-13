"""Retake detection: a repeated opening within a window drops the earlier take. Fictional text only."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import retakes as RT  # noqa: E402


def transcript(sentences):
    """sentences: [(start_time, text)] -> words, 0.3 s each, one segment per sentence."""
    words = []
    for seg, (t0, text) in enumerate(sentences):
        for k, tok in enumerate(text.split()):
            words.append({"i": len(words), "text": tok, "start": round(t0 + k * 0.3, 3), "end": round(t0 + k * 0.3 + 0.25, 3), "segment": seg})
    return words


class Detect(unittest.TestCase):
    def test_a_sentence_said_again_whole_drops_the_earlier_one(self):
        w = transcript([(1.0, "Many times the river looks calm from far away."),
                        (6.0, "Many times the river looks calm from the bridge today.")])
        r = RT.detect(w)
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["word_from"], r[0]["word_to"]), (0, 8))
        self.assertGreaterEqual(r[0]["run"], 4)
        self.assertEqual(r[0]["replaced_by"]["word_from"], 9)

    def test_a_sentence_that_stops_midway_and_restarts_is_found(self):
        w = transcript([(1.0, "Now think with me this is not very..."), (4.0, "Now think with me."), (5.5, "This is not very similar to the path.")])
        r = RT.detect(w)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["word_from"], 0)
        self.assertEqual(r[0]["word_to"], 7)

    def test_a_fuzzy_match_counts_like_muita_and_muito(self):
        w = transcript([(1.0, "Always you feel muita sorrow."), (6.0, "Always you feel muito sorrow again.")])
        self.assertEqual(len(RT.detect(w)), 1)

    def test_a_repeat_outside_the_window_is_not_a_retake(self):
        w = transcript([(1.0, "The main point is that nothing stays."), (60.0, "The main point is that everything changes.")])
        self.assertEqual(RT.detect(w), [])

    def test_a_short_shared_phrase_is_not_a_retake(self):
        w = transcript([(1.0, "We go to the market early."), (6.0, "We went into the park today.")])
        self.assertEqual(RT.detect(w, min_run=4), [])           # no run of four

    def test_an_opening_that_goes_somewhere_else_is_not_a_retake(self):
        w = transcript([(1.0, "We go to the market because the bread there is the best in the whole city."),
                        (8.0, "We go to the lake whenever winter ends and nobody complains about anything.")])
        self.assertEqual(RT.detect(w, min_run=4), [])           # a four-word opener, but the rest differs

    def test_a_shared_run_that_does_not_start_the_sentence_is_not_a_retake(self):
        w = transcript([(1.0, "So after all of that yesterday evening happened."), (6.0, "Then yesterday evening happened again somewhere.")])
        self.assertEqual(RT.detect(w, min_run=3, start_slack=1), [])

    def test_the_replaced_take_is_never_matched_again(self):
        w = transcript([(1.0, "Alpha beta gamma delta one."), (5.0, "Alpha beta gamma delta two."), (9.0, "Alpha beta gamma delta three.")])
        r = RT.detect(w)
        self.assertEqual([(x["word_from"], x["word_to"]) for x in r], [(0, 4), (5, 9)])   # the last take is kept

    def test_apply_flags_the_words_and_clears_old_flags(self):
        w = transcript([(1.0, "Alpha beta gamma delta one."), (5.0, "Alpha beta gamma delta two.")])
        RT.apply(w, RT.detect(w))
        self.assertEqual([x.get("dropped", False) for x in w], [True] * 5 + [False] * 5)
        RT.apply(w, [])
        self.assertFalse(any(x.get("dropped") for x in w))

    def test_report_lists_every_retake(self):
        w = transcript([(1.0, "Alpha beta gamma delta one."), (5.0, "Alpha beta gamma delta two.")])
        text = RT.format_report(RT.detect(w))
        self.assertIn("words 0-4", text)
        self.assertIn("1.00-", text)


if __name__ == "__main__":
    unittest.main()
