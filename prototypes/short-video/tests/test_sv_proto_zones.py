"""Zones (face box, top band, caption zone), framing at the cuts, anchors, caption chunks, and the cut command."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import edl as E  # noqa: E402
import framing as F  # noqa: E402
import presets as P  # noqa: E402
import render  # noqa: E402
import zones as Z  # noqa: E402

C = P.load_contract()
FACE = (238, 326, 756, 941)


class FaceBox(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(Z.parse_box("238,326,756,941"), FACE)
        for bad in ("1,2,3", "a,b,c,d", "0,0,0,5", "-1,0,5,5", ""):
            with self.assertRaises(Z.ZoneError):
                Z.parse_box(bad)

    def test_the_expanded_face_covers_the_most_zoomed_moment(self):
        ex = Z.expanded_face(FACE, 1.10, 0.02, 0.25)
        k = 1.10 * 1.02
        self.assertAlmostEqual(ex[2], FACE[2] * k, places=3)
        self.assertAlmostEqual(ex[3], FACE[3] * k, places=3)
        # the fixed point stays put
        px, py = Z.anchor_point(FACE, 0.25)
        self.assertAlmostEqual(ex[0] + (px - ex[0]), px)
        self.assertLessEqual(ex[0], FACE[0])
        self.assertLessEqual(ex[1], FACE[1])
        self.assertGreaterEqual(ex[1] + ex[3], FACE[1] + FACE[3])

    def test_the_bands_sit_above_and_below_the_expanded_face(self):
        z = Z.compute(FACE, (1080, 1920), 1.10, 0.02, 0.25)
        self.assertLess(z["top_band"][1], z["face_expanded"][1])
        self.assertGreater(z["caption_zone"][0], z["face_expanded"][1] + z["face_expanded"][3])
        self.assertLessEqual(z["caption_zone"][1], 1920)

    def test_a_face_too_high_for_a_band_is_refused_with_the_reason(self):
        with self.assertRaises(Z.ZoneError):
            Z.compute((100, 150, 700, 900), (1080, 1920), 1.10, 0.02, 0.25)

    def test_no_face_gives_fixed_bands_and_refuses_nothing(self):
        z = Z.compute(None, (1080, 1920), 1.0, 0.0, 0.5)
        self.assertIsNone(z["face_expanded"])
        Z.check_rect((0, 0, 1080, 1920), z)

    def test_a_rectangle_that_intersects_the_face_is_refused(self):
        z = Z.compute(FACE, (1080, 1920), 1.10, 0.02, 0.25)
        with self.assertRaises(Z.ZoneError):
            Z.check_rect((300, 800, 100, 100), z)
        with self.assertRaises(Z.ZoneError):                       # touching the expanded edge from inside
            Z.check_rect((0, z["face_expanded"][1] - 5, 1080, 40), z)
        Z.check_rect((65, z["top_band"][0], 950, z["top_band"][1] - z["top_band"][0]), z)   # the band itself is fine
        Z.check_rect((65, z["caption_zone"][0], 950, 150), z)

    def test_intersects(self):
        self.assertTrue(Z.intersects((0, 0, 10, 10), (5, 5, 10, 10)))
        self.assertFalse(Z.intersects((0, 0, 10, 10), (10, 0, 10, 10)))
        self.assertTrue(Z.intersects((0, 0, 10, 10), (12, 0, 10, 10), margin=3))


class Framing(unittest.TestCase):
    def test_ranges_alternate_between_full_frame_and_punch_in(self):
        f = F.plan([(0, 3), (4, 6), (7, 9), (10, 12)], zoom=1.10, push=0.02, push_min=5.0)
        self.assertEqual([x["z0"] for x in f], [1.0, 1.1, 1.0, 1.1])

    def test_a_push_goes_into_long_ranges_only_and_never_over_three_percent(self):
        f = F.plan([(0, 3), (4, 12)], zoom=1.10, push=0.03, push_min=5.0)
        self.assertEqual(f[0]["z1"], f[0]["z0"])
        self.assertAlmostEqual(f[1]["z1"] / f[1]["z0"], 1.03, places=3)
        with self.assertRaises(ValueError):
            F.plan([(0, 3)], push=0.05)
        with self.assertRaises(ValueError):
            F.plan([(0, 3)], zoom=2.0)

    def test_the_edit_list_carries_the_framing_and_the_zones(self):
        words = [{"i": k, "text": "w%d" % k, "start": 1.0 + k, "end": 1.6 + k, "segment": 0} for k in range(8)]
        sil = [(0.0, 0.9), (2.7, 3.9), (6.7, 7.9), (9.7, 12.0)]
        edl = E.build_edl({"duration": 12.0, "words": words}, {"beats": [], "assets": {}}, C, silences=sil,
                          cut={}, retake_cfg=None, face=FACE)
        self.assertEqual(len(edl["kept"]), 3)
        self.assertEqual([r["z0"] for r in edl["kept"]], [1.0, 1.1, 1.0])
        self.assertEqual(edl["zones"]["face"], list(FACE))
        off = E.build_edl({"duration": 12.0, "words": words}, {"beats": [], "assets": {}}, C, silences=sil,
                          cut={}, retake_cfg=None, face=FACE, frame_cfg={"enabled": False})
        self.assertEqual({r["z0"] for r in off["kept"]}, {1.0})


class Anchors(unittest.TestCase):
    def words(self):
        return [{"i": k, "text": t, "start": 1.0 + k * 0.4, "end": 1.3 + k * 0.4, "segment": 0}
                for k, t in enumerate("alpha beta gamma delta epsilon zeta eta theta iota kappa".split())]

    def script(self):
        return {"assets": {}, "beats": [{"id": "b3", "line": "something nobody ever said", "preset": "keyword",
                                         "params": {"text": "Anchored"}}]}

    def test_parse(self):
        beats = E.check_script(self.script(), C)
        self.assertEqual(E.parse_anchors(["3=2-5"], beats, 10), {"b3": (2, 5)})
        self.assertEqual(E.parse_anchors(["b3=2-5"], beats, 10), {"b3": (2, 5)})
        for bad in (["9=1-2"], ["3=5-2"], ["3=2-10"], ["3=a-b"], ["3=1-2", "3=3-4"]):
            with self.assertRaises(E.EdlError):
                E.parse_anchors(bad, beats, 10)

    def test_an_unmatched_beat_is_placed_where_the_person_put_it(self):
        tr = {"duration": 8.0, "words": self.words()}
        plain = E.build_edl(tr, self.script(), C)
        self.assertEqual(plain["unmatched"], ["b3"])
        edl = E.build_edl({"duration": 8.0, "words": self.words()}, self.script(), C, anchors={"b3": (3, 6)})
        self.assertEqual(edl["unmatched"], [])
        entry = edl["overlays"][0]
        self.assertEqual((entry["word_from"], entry["word_to"]), (3, 6))
        self.assertTrue(entry["anchored"])
        self.assertEqual(entry["score"], 1.0)
        self.assertEqual(edl["anchors"], {"b3": [3, 6]})
        self.assertGreaterEqual(entry["start"], 0.0)


class Captions(unittest.TestCase):
    def test_chunks_have_one_to_three_words_break_on_sentences_and_skip_dropped_words(self):
        toks = "one two three four. five six seven eight nine ten".split()
        words = [{"i": k, "text": t, "start": 1.0 + k * 0.3, "end": 1.25 + k * 0.3, "segment": 0} for k, t in enumerate(toks)]
        words[5]["dropped"] = True
        kmap = E.build_map([(0.5, 5.0)])
        chunks = E.caption_chunks(words, kmap)
        self.assertTrue(all(1 <= len(c["words"]) <= 3 for c in chunks))
        texts = [[w["text"] for w in c["words"]] for c in chunks]
        self.assertIn(["four."], texts[1:2] + texts[:3])        # a sentence ends a chunk
        self.assertNotIn("six", [w for t in texts for w in t])
        for a, b in zip(chunks, chunks[1:]):
            self.assertLessEqual(a["end"], b["start"] + 1e-9)

    def test_a_chunk_never_spans_a_cut(self):
        words = [{"i": k, "text": "w%d" % k, "start": 1.0 + k * 0.3 + (3.0 if k >= 2 else 0.0), "end": 1.25 + k * 0.3 + (3.0 if k >= 2 else 0.0),
                  "segment": 0} for k in range(4)]
        kmap = E.build_map([(0.5, 2.0), (4.0, 6.0)])
        chunks = E.caption_chunks(words, kmap)
        self.assertEqual([len(c["words"]) for c in chunks], [2, 2])

    def test_words_cut_away_get_no_caption(self):
        words = [{"i": 0, "text": "kept", "start": 1.0, "end": 1.3, "segment": 0},
                 {"i": 1, "text": "gone", "start": 3.0, "end": 3.3, "segment": 0}]
        chunks = E.caption_chunks(words, E.build_map([(0.5, 2.0)]))
        self.assertEqual([w["text"] for c in chunks for w in c["words"]], ["kept"])


class RetakesInTheEditList(unittest.TestCase):
    def transcript(self):
        text = [(1.0, "Now think with me this is not very..."), (6.0, "Now think with me."), (7.5, "This is not very similar to the path.")]
        words = []
        for seg, (t0, line) in enumerate(text):
            for k, tok in enumerate(line.split()):
                words.append({"i": len(words), "text": tok, "start": round(t0 + k * 0.3, 3), "end": round(t0 + k * 0.3 + 0.25, 3), "segment": seg})
        return {"duration": 12.0, "words": words}

    def test_the_earlier_take_is_cut_reported_and_has_no_caption_and_no_beat(self):
        script = {"assets": {}, "beats": [{"id": "b1", "line": "now think with me this is not very similar", "preset": "keyword", "params": {"text": "Think"}}]}
        sil = [(0.0, 0.9), (3.4, 5.9), (6.9, 7.4), (10.0, 12.0)]
        edl = E.build_edl(self.transcript(), script, C, silences=sil, cut={}, retake_cfg={})
        self.assertEqual([(r["word_from"], r["word_to"]) for r in edl["retakes"]], [(0, 7)])
        shown = [w["i"] for c in edl["captions"] for w in c["words"]]
        self.assertFalse(any(i <= 7 for i in shown))
        self.assertEqual(edl["overlays"][0]["word_from"] >= 8, True)       # the beat is placed on the later take
        self.assertIn("retake", {c["reason"] for c in edl["cuts"]["cuts"]})

    def test_a_retake_can_be_kept_and_detection_can_be_off(self):
        script = {"assets": {}, "beats": []}
        kept = E.build_edl(self.transcript(), script, C, retake_cfg={"keep": [0]})
        self.assertEqual(kept["retakes"], [])
        off = E.build_edl(self.transcript(), script, C, retake_cfg=None)
        self.assertEqual(off["retakes"], [])


class CutCommand(unittest.TestCase):
    def argv(self, **kw):
        kept = [(0.0, 3.0), (4.0, 12.0), (13.0, 14.0)]
        framing = F.plan(kept)
        return render.cut_argv("/w/src.mp4", kept, 30, (1080, 1920), True, "/w/cut.mov", framing, (576.0, 561.0), kw.get("xf", 15))

    def graph(self, argv):
        return argv[argv.index("-filter_complex") + 1]

    def test_the_audio_of_each_range_fades_at_both_edges_and_nothing_overlaps(self):
        g = self.graph(self.argv())
        self.assertEqual(g.count("afade=t=in"), 3)
        self.assertEqual(g.count("afade=t=out"), 3)
        self.assertNotIn("acrossfade", g)          # it would shorten the audio at every cut and drift from the picture
        self.assertIn("afade=t=in:st=0:d=0.0150", g)

    def test_the_fade_is_a_flag_and_never_longer_than_a_quarter_of_a_range(self):
        g = self.graph(self.argv(xf=500))
        self.assertIn("d=0.2500", g)               # the 1 s range: a quarter of it

    def test_alternate_ranges_are_zoomed_about_the_fixed_point_and_the_others_are_plain_scales(self):
        g = self.graph(self.argv())
        self.assertEqual(g.count("zoompan="), 1)
        self.assertIn("zoompan=z='1.10000+", g.replace("1.10000+", "1.10000+"))
        self.assertIn("x='1152.00*(1-1/zoom)'", g)     # the anchor's x in the base picture (twice the output)
        self.assertIn("y='1122.00*(1-1/zoom)'", g)
        self.assertEqual(g.count("scale=1080:1920:flags=lanczos"), 2)

    def test_the_picture_is_cut_from_a_base_twice_the_output_so_a_zoom_never_upscales(self):
        g = self.graph(self.argv())
        self.assertIn("scale=2160:3840:force_original_aspect_ratio=increase", g)
        self.assertIn("crop=2160:3840", g)


if __name__ == "__main__":
    unittest.main()
