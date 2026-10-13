import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import edl as E  # noqa: E402
import presets as P  # noqa: E402

C = P.load_contract()


def err(preset, params):
    with self_assert_raises() as cm:
        P.validate_params(C, preset, params)
    return cm[0]


class self_assert_raises:
    def __enter__(self):
        self.box = []
        return self.box

    def __exit__(self, typ, exc, tb):
        if typ is None:
            raise AssertionError("no error raised")
        if not issubclass(typ, P.ParamError):
            return False
        self.box.append(exc)
        return True


class Params(unittest.TestCase):
    def test_valid_params_get_defaults(self):
        out = P.validate_params(C, "keyword", {"text": "Name it"})
        self.assertEqual(out["color"], "accent")
        self.assertEqual(out["position"], "center")

    def test_bad_colours(self):
        for bad in ("red", "#FFF", "#GGGGGG", "rgba(0,0,0,1)", "var(--x)", "url(x)", "#12345678", 5):
            self.assertEqual(err("keyword", {"text": "x", "color": bad}).code, "bad_color", bad)

    def test_good_colours(self):
        self.assertEqual(P.validate_params(C, "keyword", {"text": "x", "color": "#07b6f0"})["color"], "#07B6F0")
        self.assertEqual(P.validate_params(C, "keyword", {"text": "x", "color": "muted"})["color"], "muted")

    def test_undeclared_param_is_refused(self):
        self.assertEqual(err("keyword", {"text": "x", "html": "<b>"}).code, "undeclared_param")
        self.assertEqual(err("caption", {"position": "bottom", "size": 9}).code, "undeclared_param")

    def test_missing_required_param(self):
        self.assertEqual(err("keyword", {}).code, "missing_param")

    def test_control_and_format_characters_are_refused(self):
        for bad in ("a\nb", "a\rb", "a\tb", "a\x00b", "a" + chr(0x202E) + "b", "a" + chr(0x200B) + "b", "a" + chr(0x2028) + "b", "a" + chr(0x2029) + "b", "a\x1bb"):
            self.assertEqual(err("keyword", {"text": bad}).code, "forbidden_character", repr(bad))

    def test_text_is_nfc_and_bounded(self):
        out = P.validate_params(C, "keyword", {"text": "é"})
        self.assertEqual(out["text"], "é")
        self.assertEqual(err("keyword", {"text": "x" * 25}).code, "text_too_long")
        self.assertEqual(err("keyword", {"text": "   "}).code, "empty_text")

    def test_markup_is_accepted_as_plain_text_not_interpreted(self):
        out = P.validate_params(C, "keyword", {"text": "<b>x</b>"})
        self.assertEqual(out["text"], "<b>x</b>")      # drawn with textContent by the template

    def test_choice_icon_number_and_slot(self):
        self.assertEqual(err("keyword", {"text": "x", "position": "left"}).code, "bad_choice")
        self.assertEqual(err("keyword", {"text": "x", "icon": "skull"}).code, "bad_icon")
        self.assertEqual(err("number", {"value": "-1", "label": "x"}).code, "bad_figure")
        self.assertEqual(err("number", {"value": True, "label": "x"}).code, "bad_figure")
        self.assertEqual(err("number", {"value": 7, "label": "x"}).code, "bad_figure")
        self.assertEqual(err("number", {"value": "12345678901", "label": "x"}).code, "text_too_long")
        self.assertEqual(err("number", {"value": "1e5", "label": "x"}).code, "bad_figure")
        self.assertEqual(err("number", {"value": "340"}).code, "missing_param")
        self.assertEqual(P.validate_params(C, "number", {"value": "1.234,5", "label": "x"})["value"], "1.234,5")
        self.assertEqual(err("number", {"value": "7", "label": "x", "prefix": "$"}).code, "undeclared_param")
        self.assertEqual(err("list", {"item1": "a", "title": "t"}).code, "undeclared_param")
        self.assertEqual(err("pip", {"image": "a", "position": "top-right"}).code, "bad_choice")
        self.assertEqual(err("cutaway", {"image": "../../etc/passwd"}).code, "bad_slot")
        self.assertEqual(err("cutaway", {"image": "https://x.example/a.png"}).code, "bad_slot")
        self.assertEqual(P.validate_params(C, "cutaway", {"image": "dash-1"})["transition"], "slide")

    def test_unknown_preset(self):
        self.assertEqual(err("explode", {}).code, "unknown_preset")

    def test_error_never_echoes_the_text(self):
        e = err("keyword", {"text": "secret" + chr(0x202E) + ""})
        self.assertNotIn("secret", str(e))

    def test_theme_colours_must_be_rrggbb(self):
        self.assertEqual(P.validate_theme_colors(C, {"accent": "#07b6f0"}), {"accent": "#07B6F0"})
        for bad in ("rgba(255,255,255,.18)", "accent", "#FFF", "red; background:url(x)"):
            with self_assert_raises():
                P.validate_theme_colors(C, {"accent": bad})
        with self_assert_raises():
            P.validate_theme_colors(C, {"nope": "#FFFFFF"})


class Script(unittest.TestCase):
    def test_script_with_undeclared_slot_is_refused(self):
        script = {"beats": [{"id": "b1", "line": "hello there", "preset": "cutaway", "params": {"image": "ghost"}}],
                  "assets": {}}
        with self.assertRaises(E.EdlError):
            E.check_script(script, C)

    def test_beat_cannot_use_the_caption_preset(self):
        script = {"beats": [{"id": "b1", "line": "hello there", "preset": "caption", "params": {}}]}
        with self.assertRaises(E.EdlError):
            E.check_script(script, C)

    def test_transcript_words_are_hardened(self):
        tr = {"duration": 3.0, "words": [{"i": 0, "text": "ok" + chr(0x202E) + "", "start": 0.1, "end": 0.5, "segment": 0}]}
        with self.assertRaises(P.ParamError):
            E.check_transcript(tr)


if __name__ == "__main__":
    unittest.main()
