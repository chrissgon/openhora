import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import from_whisper as W  # noqa: E402
import edl as E  # noqa: E402


class Convert(unittest.TestCase):
    def test_invented_sample_in_the_documented_shape(self):
        sample = {"result": {"language": "en"}, "transcription": [
            {"offsets": {"from": 500, "to": 800}, "text": " Hello"},
            {"offsets": {"from": 850, "to": 1200}, "text": " there."},
            {"offsets": {"from": 1300, "to": 1500}, "text": " [BLANK_AUDIO]"},
            {"offsets": {"from": 3000, "to": 3300}, "text": " Next"},
            {"offsets": {"from": 3350, "to": 3600}, "text": " one"}]}
        tr = W.convert(sample, 4.0)
        self.assertEqual([w["text"] for w in tr["words"]], ["Hello", "there.", "Next", "one"])
        self.assertEqual([w["segment"] for w in tr["words"]], [0, 0, 1, 1])
        E.check_transcript(tr)     # the converted shape is accepted by the edit-list builder


if __name__ == "__main__":
    unittest.main()
