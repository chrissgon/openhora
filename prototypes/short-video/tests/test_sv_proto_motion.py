"""Browser and ffmpeg tests of the placement and motion: nothing overlaps the face, a frame depends on t and data only,
the cut keeps picture and sound the same length. Fictional fixtures; skipped where Chromium or ffmpeg are absent."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import cdp  # noqa: E402
import edl as E  # noqa: E402
import framing as F  # noqa: E402
import media  # noqa: E402
import presets as P  # noqa: E402
import render  # noqa: E402
import zones as Z  # noqa: E402

try:
    BROWSER = cdp.find_browser()
except cdp.CDPError:
    BROWSER = None
FF = os.path.exists(media.FFMPEG) and os.path.exists(media.FFPROBE)
C = P.load_contract()
FACE = (238, 326, 756, 941)
ZONES = Z.compute(FACE, (1080, 1920), 1.10, 0.02, 0.25)
CFG = {"colors": render.DEFAULT_COLORS, "fonts": {r: {k: v for k, v in f.items() if k in ("url", "weight", "fallback")}
                                                  for r, f in render.DEFAULT_FONTS.items()}, "images": {}}


def beat(preset, **params):
    return {"params": params, "duration": 3.0, "zone": {"top": ZONES["top_band"][0], "bottom": ZONES["top_band"][1]}}


SAMPLES = {
    "keyword": beat("keyword", text="Nobody ever told him why", icon="check", color="accent", position="center"),
    "list": beat("list", item1="Trust", item2="He loves us", item3="He is here", icon="check", color="accent"),
    "number": beat("number", value="1.234", label="visits in a month", color="accent"),
    "quote": beat("quote", text="A long quotation that has to fit the band above the speaker's face", author="Someone", color="accent"),
}
CAPTION = {"params": {"position": "bottom"}, "duration": 1.5,
           "words": [{"text": "hope", "start": 0.0, "end": 0.4}, {"text": "in", "start": 0.45, "end": 0.6}, {"text": "God?", "start": 0.65, "end": 1.2}],
           "zone": {"top": ZONES["caption_zone"][0], "bottom": ZONES["caption_zone"][1]}}


@unittest.skipUnless(BROWSER, "no Chromium found (search the Playwright cache, then Chrome)")
class Placement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sv-proto-")
        self.serve, _ = render.load_templates(C)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def page(self, ch, template):
        pg = ch.new_page(1080, 1920)
        pg.open("/t/" + template, CFG)
        return pg

    def test_cards_stay_in_the_band_above_the_face_at_every_moment(self):
        with cdp.Chrome(BROWSER, self.serve, self.tmp, headless_flag="--headless") as ch:
            for name, data in SAMPLES.items():
                pg = self.page(ch, name + ".html")
                for t in (0.0, 0.1, 0.25, 0.4, 1.0, 2.0, 2.8, 2.95):
                    pg.frame(t, data)
                    for rect in pg.rects():
                        Z.check_rect(rect, ZONES, name)                       # never the face
                        self.assertGreaterEqual(rect[1], 0, (name, t, rect))
                        self.assertLessEqual(rect[0] + rect[2], 1080 + 1, (name, t, rect))
                        self.assertGreaterEqual(rect[0], -1, (name, t, rect))
                        self.assertLessEqual(rect[1] + rect[3], ZONES["top_band"][1] + 12, (name, t, rect))   # a pop may overshoot a little

    def test_captions_stay_below_the_face_and_inside_the_frame(self):
        with cdp.Chrome(BROWSER, self.serve, self.tmp, headless_flag="--headless") as ch:
            pg = self.page(ch, "caption.html")
            for t in (0.0, 0.05, 0.2, 0.5, 0.7, 1.0, 1.4):
                pg.frame(t, CAPTION)
                for rect in pg.rects():
                    Z.check_rect(rect, ZONES, "caption")
                    self.assertGreaterEqual(rect[0], 0, (t, rect))
                    self.assertLessEqual(rect[0] + rect[2], 1080, (t, rect))
                    self.assertLessEqual(rect[1] + rect[3], 1920 - 250, (t, rect))

    def test_a_frame_depends_on_t_and_data_only_not_on_the_frame_before(self):
        with cdp.Chrome(BROWSER, self.serve, self.tmp, headless_flag="--headless") as ch:
            for name, data in list(SAMPLES.items()) + [("caption", CAPTION)]:
                pg = self.page(ch, name + ".html")
                pg.frame(0.9, data)
                a = pg.frame(0.5, data)
                ra = pg.rects()
                pg2 = self.page(ch, name + ".html")
                b = pg2.frame(0.5, data)
                rb = pg2.rects()
                self.assertEqual(a, b, name)
                self.assertEqual(ra, rb, name)
                # a very different frame (another text) before it changes nothing either
                other = dict(data, params=dict(data["params"]))
                pg2.frame(2.0, other)
                self.assertEqual(pg2.frame(0.5, data), b, name)

    def test_the_active_word_of_a_caption_is_in_the_accent_colour_and_scaled(self):
        with cdp.Chrome(BROWSER, self.serve, self.tmp, headless_flag="--headless") as ch:
            pg = self.page(ch, "caption.html")
            pg.frame(0.5, CAPTION)
            spans = pg.evaluate("[...document.querySelectorAll('.w')].map(s => [s.textContent, getComputedStyle(s).color, s.style.transform])")
            self.assertEqual([s[0] for s in spans], ["hope", "in", "God?"])
            self.assertEqual(spans[1][1], "rgb(255, 201, 60)")          # the default accent, on the word being said (t=0.5)
            self.assertIn("scale(", spans[1][2])
            self.assertEqual(spans[0][2], "")
            self.assertEqual(spans[2][2], "")

    def test_entrances_overshoot_and_settle(self):
        # keyword: ease-out-back, the card goes past its final size and settles at 1
        with cdp.Chrome(BROWSER, self.serve, self.tmp, headless_flag="--headless") as ch:
            pg = self.page(ch, "keyword.html")
            scales = []
            for t in (0.0, 0.1, 0.2, 0.3, 0.4, 1.0):
                pg.frame(t, SAMPLES["keyword"])
                scales.append(float(pg.evaluate("document.getElementById('card').style.transform.match(/scale\\(([0-9.]+)\\)/)[1]")))
            self.assertLess(scales[0], 0.6)
            self.assertGreater(max(scales), 1.0)
            self.assertAlmostEqual(scales[-1], 1.0, places=3)

    def test_list_items_enter_one_after_another(self):
        with cdp.Chrome(BROWSER, self.serve, self.tmp, headless_flag="--headless") as ch:
            pg = self.page(ch, "list.html")
            pg.frame(0.25, SAMPLES["list"])
            op = pg.evaluate("[...document.querySelectorAll('.chip')].map(c => parseFloat(c.style.opacity))")
            self.assertGreater(op[0], op[1])
            self.assertGreater(op[1], op[2] - 1e-9)
            self.assertEqual(op[2], 0.0)

    def test_the_renderer_refuses_an_overlay_that_intersects_the_face(self):
        words = [{"i": k, "text": t, "start": round(0.4 + k * 0.35, 3), "end": round(0.7 + k * 0.35, 3), "segment": 0}
                 for k, t in enumerate("every single dollar you earn".split())]
        script = {"assets": {}, "beats": [{"id": "b1", "line": "every single dollar", "preset": "keyword", "params": {"text": "Every dollar"}}]}
        edl = E.build_edl({"duration": 3.0, "words": words}, script, C, face=FACE)
        d = os.path.join(self.tmp, "f")
        render.render_frames(C, edl, self.serve, render.DEFAULT_COLORS, render.DEFAULT_FONTS, BROWSER, 1, d,
                             os.path.join(self.tmp, "w1"), False, True, 300)          # in its band: fine
        # the same edit list with a face box that reaches up into the band: the overlay now intersects it
        edl["zones"] = dict(edl["zones"], face_expanded=[0, 0, 1080, 800])
        with self.assertRaises(render.RenderError) as cm:
            render.render_frames(C, edl, self.serve, render.DEFAULT_COLORS, render.DEFAULT_FONTS, BROWSER, 1,
                                 os.path.join(self.tmp, "g"), os.path.join(self.tmp, "w2"), False, True, 300)
        self.assertIn("intersects the face box", str(cm.exception))


@unittest.skipUnless(FF, "needs ffmpeg")
class CutKeepsSync(unittest.TestCase):
    def test_picture_and_sound_have_the_same_length_after_many_cuts_with_zoom_and_push(self):
        tmp = tempfile.mkdtemp(prefix="sv-proto-")
        try:
            src = os.path.join(tmp, "src.mp4")
            media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=60:duration=20",
                       "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=20", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", "-shortest", src])
            kept = [(0.0, 1.5), (2.0, 9.0), (9.7, 10.4), (11.0, 18.0)]        # frame grid at 30 fps
            fr = F.plan(kept, 1.10, 0.03, 5.0)
            out = os.path.join(tmp, "cut.mov")
            media.run(render.cut_argv(src, kept, 30, (540, 960), True, out, fr, (270.0, 280.0), 15))
            info = media.probe_output(out)
            total = sum(b - a for a, b in kept)
            self.assertEqual(info["size"], "540x960")
            self.assertAlmostEqual(info["duration"], total, delta=0.05)
            a_out, _ = media.run([media.FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "csv=p=0", out])
            v_out, _ = media.run([media.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", out])
            self.assertAlmostEqual(float(a_out), float(v_out), delta=0.04)     # no drift, whatever the number of cuts
            self.assertAlmostEqual(float(v_out), total, delta=0.04)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_cut_has_no_click(self):
        # a steady tone cut at an arbitrary phase: the largest sample step around the cut stays near the tone's own
        tmp = tempfile.mkdtemp(prefix="sv-proto-")
        try:
            src = os.path.join(tmp, "src.mp4")
            media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=270x480:rate=30:duration=6",
                       "-f", "lavfi", "-i", "sine=frequency=200:sample_rate=48000:duration=6", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src])
            kept = [(0.0, 2.0), (3.003, 5.0)]                 # a cut at an arbitrary phase
            out = os.path.join(tmp, "c.mov")
            media.run(render.cut_argv(src, kept, 30, (270, 480), True, out, None, None, 15))
            raw = os.path.join(tmp, "a.raw")
            media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", out, "-vn", "-ac", "1", "-f", "s16le", raw])
            import struct
            with open(raw, "rb") as fh:
                data = fh.read()
            xs = struct.unpack("<%dh" % (len(data) // 2), data)
            cut = int(2.0 * 48000)
            window = xs[cut - 600:cut + 600]
            jump = max(abs(a - b) for a, b in zip(window, window[1:]))
            # the tone's own largest step is about 107; a hard splice at this phase would jump by about 2400
            self.assertLess(jump, 300)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
