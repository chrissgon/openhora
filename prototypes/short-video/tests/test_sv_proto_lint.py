import glob
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
import lint  # noqa: E402
import render  # noqa: E402
import presets as P  # noqa: E402

C = P.load_contract()
TEMPLATES = sorted(glob.glob(os.path.join(ROOT, "templates", "*.html")))


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


class TemplateLint(unittest.TestCase):
    def test_every_template_is_clean(self):
        self.assertTrue(TEMPLATES)
        for path in TEMPLATES:
            self.assertEqual(lint.lint(read(path)), [], path)

    def test_each_forbidden_construct_is_refused(self):
        cases = {
            "css-keyframes": "<style>@keyframes a{}</style>",
            "css-transition": "<style>p{transition: all 1s}</style>",
            "css-animation": "<style>p{animation: a 1s}</style>",
            "date": "<script>new Date()</script>",
            "performance-now": "<script>performance.now()</script>",
            "math-random": "<script>Math.random()</script>",
            "raf": "<script>requestAnimationFrame(f)</script>",
            "timers": "<script>setTimeout(f,1)</script>",
            "media-element": "<video></video>",
            "network": "<script>fetch('x')</script>",
            "worker": "<script>new Worker('w.js')</script>",
            "dynamic-import": "<script>import('x')</script>",
            "external-src": '<img src="https://x.example/a.png">',
            "markup-injection": "<script>el.innerHTML = x</script>",
        }
        for rule, html in cases.items():
            self.assertIn(rule, lint.lint(html), rule)
        for html in ("<audio></audio>", "<iframe></iframe>", "<script>new XMLHttpRequest()</script>",
                     "<script>new WebSocket('x')</script>", "<style>p{background:url(x)}</style>",
                     "<script>setInterval(f,1)</script>", "<script>document.write('x')</script>",
                     '<a href="file:///etc/hosts">x</a>'):
            self.assertTrue(lint.lint(html), html)

    def test_a_template_that_breaks_the_contract_is_not_served(self):
        # render.load_templates lints before it serves; here: the lint refuses, so nothing would be served
        self.assertTrue(lint.lint("<script>setTimeout(()=>{},0)</script>"))


class ContractEquality(unittest.TestCase):
    def test_presets_templates_and_declared_params_are_equal(self):
        files = {os.path.basename(p) for p in TEMPLATES}
        self.assertEqual(files, {s["template"] for s in C["presets"].values()})
        for name, spec in C["presets"].items():
            html = read(os.path.join(ROOT, "templates", spec["template"]))
            meta = re.search(r'<meta name="pv-params" content="([^"]*)">', html).group(1)
            self.assertEqual(set(meta.split(",")), set(spec["params"]), name)
            self.assertEqual(re.search(r'<meta name="pv-preset" content="([^"]*)">', html).group(1), name)

    def test_templates_read_only_declared_params(self):
        for name, spec in C["presets"].items():
            html = read(os.path.join(ROOT, "templates", spec["template"]))
            used = set(re.findall(r"\bP\.([a-z0-9_]+)", html))
            self.assertLessEqual(used, set(spec["params"]), name)

    def test_every_param_type_is_known(self):
        for spec in C["presets"].values():
            for p in spec["params"].values():
                self.assertIn(p["type"], {"text", "icon", "color", "image", "choice", "figure"})

    def test_text_templates_never_use_innerhtml(self):
        for path in TEMPLATES:
            self.assertNotIn("innerHTML", read(path))


class ComposeArgv(unittest.TestCase):
    def edl(self):
        return {"fps": 30, "size": [1080, 1920], "out_duration": 10.0, "out_frames": 300,
                "layouts": [{"preset": "pip", "asset": "chart", "start_frame": 30, "end_frame": 120,
                             "params": {"position": "top"}}], "overlays": []}

    def test_compose_is_a_list_with_expected_pieces(self):
        argv = render.compose_argv(C, self.edl(), "/w/cut.mov", "/w/frames", "/w/mask.png", {"chart": "/w/a.png"},
                                   True, {"beat", "caption"}, "/w/out.mp4")
        self.assertIsInstance(argv, list)
        graph = argv[argv.index("-filter_complex") + 1]
        for piece in ("alphamerge", "enable='between(t,1.0000,4.0000)'", "out_color_matrix=bt709", "overlay=350:285"):
            self.assertIn(piece, graph)
        self.assertIn("+faststart", argv)
        self.assertIn("-fs", argv)
        self.assertNotIn("-protocol_whitelist", argv)   # only the recording input carries it (cut_argv)

    def test_cut_argv_reads_the_recording_as_mov_with_a_file_whitelist(self):
        argv = render.cut_argv("/w/src.mp4", [(0.0, 1.0), (2.0, 3.0)], 30, (1080, 1920), True, "/w/cut.mov")
        i = argv.index("-i")
        self.assertEqual(argv[i - 4:i], ["-f", "mov", "-protocol_whitelist", "file"])
        self.assertEqual(argv.count("-filter_complex"), 1)


if __name__ == "__main__":
    unittest.main()
