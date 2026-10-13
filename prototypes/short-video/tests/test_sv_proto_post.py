"""from_post: the shipped script format read through the real check_script.py, mapped to the prototype's presets."""
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
import cdp  # noqa: E402
import edl as E  # noqa: E402
import from_post as F  # noqa: E402
import presets as P  # noqa: E402
import render  # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "fictional-post.md")
DEMO_POST = os.path.join(ROOT, "demo", "post.md")
C = P.load_contract()
HAVE_CHECKER = os.path.isfile(os.path.join(F.REPO_ROOT, F.CHECKER)) and os.path.isfile(os.path.join(F.REPO_ROOT, F.VOCABULARY))
try:
    BROWSER = cdp.find_browser()
except cdp.CDPError:
    BROWSER = None


def by_id(script):
    return {b["id"]: b for b in script["beats"]}


def write(tmp, body, name="post.md", fmt="reel"):
    path = os.path.join(tmp, name)
    head = "# Post: x\n\n- Network: instagram\n" + ("- Format: %s\n" % fmt if fmt else "") + "\n## Script\n\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(head + "```script\n" + body + "\n```\n")
    return path


def png(w=8, h=8):
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x00" * (w * 3) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def jpeg(w, h):
    return (b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xc0\x00\x0b\x08" + struct.pack(">HH", h, w) + b"\x01\x01\x11\x00" + b"\xff\xd9")


@unittest.skipUnless(HAVE_CHECKER, "check_script.py is not in this checkout (merge the branch that ships it)")
class Mapping(unittest.TestCase):
    def build(self, files=(6, 7)):
        return F.build_script(FIXTURE, set(files))

    def test_every_preset_maps_to_the_prototype_templates(self):
        script, report = self.build()
        b = by_id(script)
        self.assertEqual(b["b2"]["params"], {"text": "Book boring first", "icon": "flag", "color": "chip_text"})
        self.assertEqual(b["b3"]["params"], {"item1": "Dates", "item2": "Budget", "item3": "One big thing",
                                             "icon": "star", "color": "accent"})
        self.assertNotIn("title", b["b3"]["params"])
        self.assertEqual(b["b4"]["params"], {"value": "1.234,5", "label": "euros for a whole trip", "color": "accent"})
        self.assertEqual(b["b5"]["params"], {"text": "Plan the days you hate, wing the rest.", "author": "My sister"})
        self.assertEqual(b["b6"]["params"], {"fit": "contain", "image": "beat6"})        # no on-screen: no label
        self.assertEqual(b["b7"]["params"], {"label": "Budget sheet", "position": "bottom", "image": "beat7"})
        self.assertEqual(b["b2"]["line"], "My one rule is to book the boring things first.")
        self.assertEqual(script["assets"], {"beat6": "a screenshot of the trip map", "beat7": "a photo of the budget sheet"})

    def test_mapped_script_is_accepted_by_the_prototype_validator(self):
        script, _ = self.build()
        beats = E.check_script(script, C)
        self.assertEqual([x["preset"] for x in beats], ["keyword", "list", "number", "quote", "cutaway", "pip"])
        for x in beats:     # every mapped parameter is one the prototype contract declares, defaults filled
            self.assertLessEqual(set(x["params"]), set(C["presets"][x["preset"]]["params"]))
        self.assertEqual(beats[4]["params"]["transition"], "slide")

    def test_a_beat_with_no_preset_is_caption_only_and_reported(self):
        script, report = self.build()
        self.assertEqual([x["id"] for x in script["beats"]], ["b2", "b3", "b4", "b5", "b6", "b7"])
        rows = {r["beat"]: r for r in report}
        self.assertEqual(rows[1]["outcome"], "caption only")
        self.assertEqual(rows[8]["outcome"], "caption only")

    def test_missing_asset_falls_back_to_a_keyword_with_its_label(self):
        script, report = self.build(files=(6,))            # beat 7 (pip, label "Budget sheet") has no file
        b = by_id(script)
        self.assertEqual(b["b7"]["preset"], "keyword")
        self.assertEqual(b["b7"]["params"], {"text": "Budget sheet"})
        self.assertNotIn("beat7", script["assets"])
        row = [r for r in report if r["beat"] == 7][0]
        self.assertEqual(row["outcome"], "fallback keyword")
        self.assertEqual(row["preset"], "pip")
        E.check_script(script, C)

    def test_missing_asset_without_a_usable_label_falls_back_to_caption_only(self):
        script, report = F.build_script(FIXTURE, set())    # beat 6 has no label; beat 7's label is fine
        b = by_id(script)
        self.assertNotIn("b6", b)
        self.assertEqual([r["outcome"] for r in report if r["beat"] == 6], ["fallback caption only"])
        self.assertEqual(b["b7"]["preset"], "keyword")
        tmp = tempfile.mkdtemp(prefix="sv-proto-")
        try:
            long_label = "x" * 30
            path = write(tmp, "beat: 1\nline: See this.\non-screen: %s\npreset: pip\nasset: a chart of sales" % long_label)
            script, report = F.build_script(path, set())
            self.assertEqual(script["beats"], [])
            self.assertEqual(report[0]["outcome"], "fallback caption only")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_file_for_a_beat_without_an_asset_slot_is_refused(self):
        with self.assertRaises(F.PostError):
            F.build_script(FIXTURE, {2})
        with self.assertRaises(F.PostError):
            F.build_script(FIXTURE, {99})

    def test_asset_flags_are_beat_numbers(self):
        self.assertEqual(F.parse_asset_flags(["6=a.png", "7=b.jpg"]), {6: "a.png", 7: "b.jpg"})
        for bad in (["dashboard=a.png"], ["6="], ["6=a.png", "6=b.png"], ["x"]):
            with self.assertRaises(F.PostError):
                F.parse_asset_flags(bad)

    def test_the_demo_post_maps_the_demo_beats(self):
        script, report = F.build_script(DEMO_POST, {7, 8})
        self.assertEqual([b["preset"] for b in script["beats"]], ["keyword", "list", "number", "quote", "cutaway", "pip"])
        self.assertTrue(all(r["outcome"] in ("ok", "caption only") for r in report))

    def test_a_list_of_four_and_one_item(self):
        tmp = tempfile.mkdtemp(prefix="sv-proto-")
        try:
            p4 = write(tmp, "beat: 1\nline: a b c d.\non-screen: A | B | C | D\npreset: list")
            self.assertEqual(sorted(F.build_script(p4)[0]["beats"][0]["params"]), ["item1", "item2", "item3", "item4"])
            p1 = write(tmp, "beat: 1\nline: just one.\non-screen: Only\npreset: list", "p1.md")
            self.assertEqual(F.build_script(p1)[0]["beats"][0]["params"], {"item1": "Only"})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_non_ascii_text_passes_through_nfc(self):
        tmp = tempfile.mkdtemp(prefix="sv-proto-")
        try:
            word = "café à noite"
            path = write(tmp, "beat: 1\nline: %s.\non-screen: %s\npreset: keyword" % (word, word))
            script, _ = F.build_script(path)
            self.assertEqual(script["beats"][0]["params"]["text"], word)
            self.assertEqual(script["beats"][0]["line"], word + ".")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(HAVE_CHECKER, "check_script.py is not in this checkout (merge the branch that ships it)")
class Refusal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sv-proto-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def refused(self, body, fmt="reel", needle=None):
        path = write(self.tmp, body, fmt=fmt)
        with self.assertRaises(F.PostError) as cm:
            F.build_script(path)
        return cm.exception

    def test_a_script_that_check_script_refuses_is_refused_with_codes_not_text(self):
        secret = "mysecretphrase"
        cases = {
            "unknown preset": "beat: 1\nline: %s here.\npreset: explode" % secret,
            "undeclared parameter": "beat: 1\nline: %s here.\non-screen: A | B\npreset: list\ntitle: Nope" % secret,
            "list of five": "beat: 1\nline: %s.\non-screen: A | B | C | D | E\npreset: list" % secret,
            "keyword too long": "beat: 1\nline: %s.\non-screen: %s\npreset: keyword" % (secret, "x" * 25),
            "number written as on-screen": "beat: 1\nline: %s.\non-screen: 340\npreset: number" % secret,
            "number needs a value": "beat: 1\nline: %s.\non-screen: dollars\npreset: number" % secret,
            "a time field": "beat: 1\nline: %s.\non-screen: Hi\npreset: keyword\nstart: 2" % secret,
            "a file name as asset": "beat: 1\nline: %s.\npreset: cutaway\nasset: shot.png" % secret,
            "a position the list lacks": "beat: 1\nline: %s.\npreset: pip\nasset: a chart of sales\nposition: left" % secret,
            "on-screen without a preset": "beat: 1\nline: %s.\non-screen: Hi" % secret,
            "no line": "beat: 1\non-screen: Hi\npreset: keyword",
            "beats out of order": "beat: 2\nline: %s." % secret,
        }
        for label, body in cases.items():
            with self.subTest(label):
                err = self.refused(body)
                self.assertTrue(err.problems, label)
                self.assertNotIn(secret, str(err))
                self.assertNotIn(secret, json.dumps(err.problems))

    def test_a_missing_or_doubled_script_block_is_refused(self):
        path = os.path.join(self.tmp, "none.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# Post\n\n- Format: reel\n\nNo block here.\n")
        with self.assertRaises(F.PostError):
            F.build_script(path)
        with self.assertRaises(F.PostError):
            F.build_script(os.path.join(self.tmp, "does-not-exist.md"))
        two = write(self.tmp, "beat: 1\nline: hi there.", "two.md")
        with open(two, "a", encoding="utf-8") as fh:
            fh.write("\n```script\nbeat: 1\nline: again.\n```\n")
        with self.assertRaises(F.PostError):
            F.build_script(two)

    def test_an_image_format_is_not_a_video(self):
        for fmt in ("carousel", "static", "text"):
            with self.assertRaises(F.PostError):
                F.build_script(write(self.tmp, "beat: 1\nline: hello there.", "i.md", fmt=fmt))

    def test_main_exits_2_on_a_refused_post_and_prints_no_script(self):
        path = write(self.tmp, "beat: 1\nline: hello.\npreset: explode")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = F.main(["--post", path])
        self.assertEqual(rc, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("check_script.py refused", err.getvalue())

    def test_render_refuses_a_bad_post_before_any_work(self):
        path = write(self.tmp, "beat: 1\nline: hello.\npreset: explode")
        err = io.StringIO()
        with redirect_stderr(err):
            rc = render.main(["--video", "/nonexistent.mp4", "--transcript", "/nonexistent.json", "--post", path,
                              "--out", os.path.join(self.tmp, "o.mp4"), "--workdir", os.path.join(self.tmp, "w")])
        self.assertEqual(rc, 2)
        self.assertIn("check_script.py refused", err.getvalue())      # not "cannot probe the source": the post comes first
        self.assertEqual(os.listdir(os.path.join(self.tmp, "w")), [])

    def test_post_and_script_cannot_both_be_given(self):
        with self.assertRaises(SystemExit):
            with redirect_stderr(io.StringIO()):
                render.main(["--video", "a", "--transcript", "b", "--post", "p", "--script", "s", "--out", "o", "--workdir", "w"])


class Assets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sv-proto-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_png_and_jpeg_are_read_by_their_bytes(self):
        self.assertEqual(render.image_facts(png(8, 5)), ("png", 8, 5))
        self.assertEqual(render.image_facts(jpeg(640, 480)), ("jpg", 640, 480))
        self.assertIsNone(render.image_facts(b"GIF89a" + b"\x00" * 40))
        self.assertIsNone(render.image_facts(b"\xff\xd8\xff" + b"\x00" * 40))
        self.assertIsNone(render.image_facts(b""))

    def test_load_assets_serves_each_with_its_own_type(self):
        a, b = self.put("a.png", png()), self.put("b.jpg", jpeg(100, 50))
        serve, names, urls = render.load_assets(C, ["beat6=" + a, "beat7=" + b])
        self.assertEqual(urls, {"beat6": "/assets/beat6.png", "beat7": "/assets/beat7.jpg"})
        self.assertEqual(serve["/assets/beat6.png"][1], "image/png")
        self.assertEqual(serve["/assets/beat7.jpg"][1], "image/jpeg")
        self.assertEqual(names["beat7"], b)

    def test_load_assets_refuses_other_files_missing_files_and_big_images(self):
        gif = self.put("c.png", b"GIF89a" + b"\x00" * 40)          # the extension does not decide
        for flag in ("beat6=" + gif, "beat6=" + os.path.join(self.tmp, "none.png"),
                     "beat6=" + self.put("big.png", png(9000, 2))):
            with self.assertRaises(render.RenderError):
                render.load_assets(C, [flag])
        ok = self.put("ok.png", png())
        with self.assertRaises(render.RenderError):
            render.load_assets(C, ["beat6=" + ok, "beat6=" + ok])


@unittest.skipUnless(BROWSER, "no Chromium found (search the Playwright cache, then Chrome)")
class NumberTemplate(unittest.TestCase):
    def test_the_count_up_keeps_the_written_shape_and_ends_on_the_exact_value(self):
        tmp = tempfile.mkdtemp(prefix="sv-proto-")
        try:
            serve, _ = render.load_templates(C)
            cfg = {"colors": render.DEFAULT_COLORS, "fonts": {}, "images": {}}
            with cdp.Chrome(BROWSER, serve, tmp, headless_flag="--headless") as ch:
                pg = ch.new_page(1080, 1920)
                pg.open("/t/number.html", cfg)

                def figure(value, t, duration=4.0):
                    sig = pg.frame(t, {"params": {"value": value, "label": "x", "color": "accent"}, "duration": duration})
                    start = sig.index('id="fig"')
                    return sig[sig.index(">", start) + 1:sig.index("<", start)]

                for value in ("340", "1.234", "3,5", "1.234,56", "7"):
                    self.assertEqual(figure(value, 3.5), value)           # the end shows the written value
                    self.assertNotEqual(figure(value, 0.4), value)         # in the middle it is still counting
                self.assertEqual(figure("1.234", 0.1), "0")
                mid = figure("1.234,56", 0.5)
                self.assertRegex(mid, r"^\d{1,3}(\.\d{3})*,\d\d$")        # thousands mark and decimal mark kept
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
