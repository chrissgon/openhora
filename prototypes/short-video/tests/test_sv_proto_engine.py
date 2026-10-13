"""Browser and ffmpeg tests. Skipped with a reason where no Chromium or ffmpeg is found."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
import cdp  # noqa: E402
import edl as E  # noqa: E402
import media  # noqa: E402
import presets as P  # noqa: E402
import render  # noqa: E402

try:
    BROWSER = cdp.find_browser()
except cdp.CDPError:
    BROWSER = None
FF = os.path.exists(media.FFMPEG) and os.path.exists(media.FFPROBE)
C = P.load_contract()
CFG = {"colors": {"accent": "#07B6F0"}, "fonts": {}, "images": {}}


def page_html(body):
    return ("<!doctype html><meta charset=utf-8><body><div id=a></div><script>%s</script>" % body).encode()


@unittest.skipUnless(BROWSER, "no Chromium found (search the Playwright cache, then Chrome)")
class Engine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sv-proto-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def chrome(self, serve):
        return cdp.Chrome(BROWSER, serve, self.tmp, headless_flag="--headless")

    def test_markup_in_data_is_drawn_as_text(self):
        serve = {"/t/x.html": (page_html("window.renderAt=(t,d)=>{document.getElementById('a').textContent=d.text}"), "text/html")}
        with self.chrome(serve) as ch:
            pg = ch.new_page(200, 200)
            pg.open("/t/x.html", CFG)
            sig = pg.frame(0, {"text": "<img src=x onerror=alert(1)>"})
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;", sig)
            self.assertNotIn("<img", sig)

    def test_a_network_or_file_request_fails_the_render(self):
        for url in ("https://example.com/a.png", "http://127.0.0.1:9/a.png", "file:///etc/hosts", "https://render.invalid/not-served.png"):
            body = "var i=new Image();i.src=%s;window.renderAt=()=>{}" % json.dumps(url)
            serve = {"/t/x.html": (page_html(body), "text/html")}
            with self.chrome(serve) as ch:
                pg = ch.new_page(200, 200)
                # file: is refused by the browser itself from an https page; either way it draws nothing
                # and, for every other URL, the Fetch layer fails the request and the render
                if url.startswith("file:"):
                    try:
                        pg.open("/t/x.html", CFG)
                    except cdp.RenderBlocked:
                        pass
                    self.assertFalse(any(k.startswith("/") for k in serve if "etc" in k))
                else:
                    with self.assertRaises(cdp.RenderBlocked):
                        pg.open("/t/x.html", CFG)

    def test_timers_clock_and_random_throw(self):
        serve = {"/t/x.html": (page_html("window.renderAt=()=>{}"), "text/html")}
        with self.chrome(serve) as ch:
            pg = ch.new_page(200, 200)
            pg.open("/t/x.html", CFG)
            for expr in ("setTimeout(()=>{},1)", "Date.now()", "new Date()", "Math.random()", "performance.now()",
                         "requestAnimationFrame(()=>{})", "fetch('x')"):
                with self.assertRaises(cdp.CDPError, msg=expr):
                    pg.evaluate(expr)

    def test_a_running_css_animation_fails_the_assertion(self):
        body = ("var s=document.createElement('style');s.textContent='@keyframes k{from{opacity:0}to{opacity:1}}"
                "#a{animation:k 1s infinite}';document.head.appendChild(s);window.renderAt=()=>{}")
        serve = {"/t/x.html": (page_html(body), "text/html")}
        with self.chrome(serve) as ch:
            pg = ch.new_page(200, 200)
            pg.open("/t/x.html", CFG)
            with self.assertRaises(cdp.CDPError):
                pg.frame(0, {})

    def test_a_missing_font_or_image_fails_before_frame_zero(self):
        serve = {"/t/x.html": (page_html("window.renderAt=()=>{}"), "text/html")}
        with self.chrome(serve) as ch:
            pg = ch.new_page(200, 200)
            cfg = {"colors": {}, "fonts": {"display": {"url": cdp.ORIGIN + "/fonts/none.woff2", "weight": 800, "fallback": "serif"}}, "images": {}}
            with self.assertRaises((cdp.CDPError, cdp.RenderBlocked)):
                pg.open("/t/x.html", cfg)
        with self.chrome(serve) as ch:
            pg = ch.new_page(200, 200)
            cfg = {"colors": {}, "fonts": {}, "images": {"s": cdp.ORIGIN + "/assets/none.png"}}
            with self.assertRaises((cdp.CDPError, cdp.RenderBlocked)):
                pg.open("/t/x.html", cfg)

    def test_the_browser_group_is_killed_on_close(self):
        serve = {"/t/x.html": (page_html("window.renderAt=()=>{}"), "text/html")}
        with self.chrome(serve) as ch:
            pid = ch.proc.pid
            ch.new_page(200, 200).open("/t/x.html", CFG)
        import subprocess
        import time
        time.sleep(0.3)
        out = subprocess.run(["ps", "-o", "pid=", "-g", str(pid)], capture_output=True, text=True).stdout.strip()
        self.assertEqual(out, "")

    def test_a_hung_browser_is_killed_past_the_limit(self):
        serve = {"/t/x.html": (page_html("window.renderAt=()=>{}"), "text/html")}
        import time
        ch = cdp.Chrome(BROWSER, serve, self.tmp, headless_flag="--headless", time_limit=1)
        ch.start()
        pid = ch.proc.pid
        time.sleep(1.8)
        self.assertIsNotNone(ch.proc.poll())
        ch.close()
        self.assertTrue(pid)

    def test_two_browsers_give_identical_frames(self):
        serve = {"/t/x.html": (page_html("window.renderAt=(t,d)=>{var a=document.getElementById('a');a.textContent='t'+t.toFixed(2);a.style.cssText='font:60px sans-serif;color:#07b6f0;position:absolute;left:'+Math.round(t*40)+'px;top:10px'}"), "text/html")}
        shots = []
        for _ in range(2):
            with self.chrome(serve) as ch:
                pg = ch.new_page(400, 200)
                pg.open("/t/x.html", CFG)
                pg.frame(0.5, {})
                shots.append(hashlib.sha256(pg.screenshot()).hexdigest())
        self.assertEqual(shots[0], shots[1])


def tiny_edl(contract):
    words, t = [], 0.4
    for k, tok in enumerate("save every single dollar you earn and review it each week".split()):
        words.append({"i": k, "text": tok, "start": round(t, 3), "end": round(t + 0.3, 3), "segment": 0 if k < 5 else 1})
        t += 0.35
    tr = {"duration": round(t + 0.4, 3), "words": words}
    script = {"assets": {}, "beats": [
        {"id": "b1", "line": "every single dollar", "preset": "keyword", "params": {"text": "Every dollar"}},
        {"id": "b2", "line": "review it each week", "preset": "list", "params": {"item1": "Review", "item2": "Adjust"}}]}
    return E.build_edl(tr, script, contract)


@unittest.skipUnless(BROWSER and FF, "needs Chromium and ffmpeg")
class FrameLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sv-proto-")
        self.serve, _ = render.load_templates(C)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def frames(self, name, jobs, dedupe):
        edl = tiny_edl(C)
        d = os.path.join(self.tmp, name)
        render.render_frames(C, edl, self.serve, render.DEFAULT_COLORS, render.DEFAULT_FONTS, BROWSER, jobs, d,
                             os.path.join(self.tmp, name + "-work"), False, dedupe, 300)
        hashes = {}
        for f in sorted(os.listdir(d)):
            with open(os.path.join(d, f), "rb") as fh:
                hashes[f] = hashlib.sha256(fh.read()).hexdigest()
        return edl, hashes

    def test_jobs_render_the_same_frames_and_dedupe_changes_nothing(self):
        edl, one = self.frames("j1", 1, True)
        _, three = self.frames("j3", 3, True)
        _, raw = self.frames("raw", 2, False)
        self.assertEqual(one, three)
        self.assertEqual(one, raw)
        n = edl["out_frames"]
        self.assertEqual(len([f for f in one if f.startswith("cap_")]), n)
        self.assertEqual(len([f for f in one if f.startswith("beat_")]), n)
        self.assertGreater(len(set(one.values())), 5)    # frames differ from one another


@unittest.skipUnless(BROWSER and FF, "needs Chromium and ffmpeg")
class Integration(unittest.TestCase):
    def test_five_second_synthetic_source_renders(self):
        tmp = tempfile.mkdtemp(prefix="sv-proto-")
        try:
            src = os.path.join(tmp, "src.mp4")
            media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=5",
                       "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", "-shortest", src])
            words = [{"i": k, "text": t, "start": 1.0 + k * 0.4, "end": 1.3 + k * 0.4, "segment": 0}
                     for k, t in enumerate("small steps beat big plans".split())]
            tr = {"duration": 5.0, "words": words}
            script = {"assets": {}, "beats": [{"id": "b1", "line": "small steps beat big plans", "preset": "keyword",
                                               "params": {"text": "Small steps"}}]}
            with open(os.path.join(tmp, "t.json"), "w") as fh:
                json.dump(tr, fh)
            with open(os.path.join(tmp, "s.json"), "w") as fh:
                json.dump(script, fh)
            out = os.path.join(tmp, "out.mp4")
            rc = render.main(["--source", src, "--transcript", os.path.join(tmp, "t.json"), "--script", os.path.join(tmp, "s.json"),
                              "--out", out, "--workdir", os.path.join(tmp, "w"), "--keep-frames"])
            self.assertEqual(rc, 0)
            info = media.probe_output(out)
            self.assertEqual(info["codec"], "h264")
            self.assertEqual(info["size"], "1080x1920")
            self.assertEqual(info["audio"], "aac")
            self.assertTrue(render.faststart_ok(out))
            self.assertLess(info["duration"], 5.0)   # the leading and trailing silence were cut
            # an overlaid frame differs from the same frame of the cut video
            a = os.path.join(tmp, "a.png")
            b = os.path.join(tmp, "b.png")
            media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.0", "-i", out, "-frames:v", "1", a])
            media.run([media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", "1.0", "-i", os.path.join(tmp, "w", "cut.mov"), "-frames:v", "1", b])
            with open(a, "rb") as fa, open(b, "rb") as fb:
                self.assertNotEqual(fa.read(), fb.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
