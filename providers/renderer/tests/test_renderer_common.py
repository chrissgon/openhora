"""The common part of the renderer apart from the drawing (V1a-3): the modules both engines need import nothing of the browser, the
frames or the storyboard; the verbs that need no browser load none of them; the host verbs are the ones `_host.py` exports; and the
bottom of the caption band is 1560 (VD12): a drawn caption below it fails the render with `caption_below_line`.

Every input is synthetic. The frame loop is driven with a stand-in for the browser, so these tests need no Chromium.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys

import pytest

import renderer_kit as K
import _docker as D
import _edl
import _frames
import _host
import _image
import _layout
import _render
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
FOLDER = K.RENDERER

COMMON = ("_align", "_assets", "_blocks", "_edl", "_hf_page", "_layout", "_media", "_output", "_redact", "_text", "_timeline", "_vocab")
DRAWING = ("_cdp", "_frames", "_lint", "_preview", "_render", "_browser")
HOST = ("_docker", "_host", "_image", "ffmpeg")
needs_media = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)


def imported_names(tree) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


# ---------------------------------------------------------------- import isolation

def test_no_common_module_imports_a_drawing_or_a_host_module():
    for name in COMMON:
        tree = ast.parse((FOLDER / (name + ".py")).read_text(encoding="utf-8"))
        bad = imported_names(tree) & set(DRAWING + HOST)
        assert not bad, (name, sorted(bad))


def test_the_inner_entry_point_imports_the_drawing_part_only_inside_the_verbs_that_draw_or_report_it():
    tree = ast.parse((FOLDER / "_inner.py").read_text(encoding="utf-8"))
    top = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            top |= imported_names(ast.Module(body=[node], type_ignores=[]))
    assert not top & set(DRAWING + HOST), sorted(top & set(DRAWING + HOST))
    inside = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            names = set()
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)):
                        names |= imported_names(ast.Module(body=[sub], type_ignores=[]))
            if names & set(DRAWING):
                inside[node.name] = sorted(names & set(DRAWING))
    assert set(inside) == {"verb_render", "verb_storyboard", "verb_selfcheck"}, inside


PROBE = r"""
import json, sys
sys.path.insert(0, %r)
import _inner
rc = _inner.main(sys.argv[1:])
print(json.dumps({"rc": rc, "loaded": sorted(m for m in sys.modules if m in %r)}), file=sys.stderr)
"""


def run_in_fresh_process(args):
    done = subprocess.run([sys.executable, "-c", PROBE % (str(FOLDER), DRAWING + HOST), *map(str, args)], capture_output=True, text=True, timeout=300,
                          env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")})
    report = json.loads(done.stderr.strip().splitlines()[-1])
    return report["rc"], report["loaded"], done.stdout


def test_importing_the_inner_entry_point_loads_none_of_the_drawing_modules():
    done = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import _inner; print(sorted(m for m in sys.modules if m in %r))" % (str(FOLDER), DRAWING + HOST)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]", done.stdout


@needs_media
def test_verify_cover_and_still_run_without_loading_a_drawing_or_a_host_module(tmp_path):
    src = tmp_path / "rec.mp4"
    subprocess.run([K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=3", "-c:a", "aac", "-c:v", "libx264", "-preset", "veryfast",
                    "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                    "-movflags", "+faststart", str(src)], check=True, timeout=120)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    for args in (("cover", "--in", src, "--offset-ms", "1000", "--out", tmp_path / "cover.png"),
                 ("still", "--in", src, "--at-ms", "1000", "--out", tmp_path / "still.png"),
                 ("verify", "--in", src, "--platform-file", K.INSTAGRAM, "--sha256", digest)):
        rc, loaded, out = run_in_fresh_process(args)
        assert loaded == [], (args[0], loaded)
        if args[0] == "verify":
            assert json.loads(out)["code"] in ("platform_spec",) if rc else json.loads(out)["ok"] is True      # the verdict is not this test's subject
        else:
            assert rc == 0, (args[0], out)
    for args in (("analyse", "--in", src, "--out", tmp_path / "analysis.json"),
                 ("check", "--edl", K.write_json(tmp_path / "e.json", {}), "--beats", K.write_json(tmp_path / "b.json", {}), "--vocabulary", K.VOCABULARY)):
        rc, loaded, out = run_in_fresh_process(args)
        assert loaded == [], (args[0], loaded)


def test_a_refused_verb_still_loads_no_drawing_module(tmp_path):
    rc, loaded, out = run_in_fresh_process(("verify", "--in", tmp_path / "missing.mp4", "--platform-file", K.INSTAGRAM, "--sha256", "0" * 64))
    assert rc != 0 and loaded == []


# ---------------------------------------------------------------- the moved functions keep their names where they were

def test_a_moved_function_is_still_found_under_its_old_module_and_is_the_same_object():
    import _assets
    import _output
    for name in ("font_allowlist", "fonts_dir", "load_fonts", "read_regular", "image_facts", "load_assets", "FONT_MAGIC", "FONT_ID"):
        assert getattr(_frames, name) is getattr(_assets, name), name
    for name in ("read_platform", "make_cover", "make_still", "png_size", "write_once"):
        assert getattr(_render, name) is getattr(_output, name), name
    assert _edl.zones is _layout.zones and _frames.face_hit is _layout.face_hit and _frames.caption_hit is _layout.caption_hit
    assert not hasattr(_frames, "_edl_zones")


def test_the_image_manifest_lists_the_new_common_modules_and_the_host_module_stays_out_of_the_image():
    files = set(json.loads((FOLDER / "image-manifest.json").read_text(encoding="utf-8"))["files"])
    assert {"_layout.py", "_assets.py", "_output.py"} <= files
    assert "_host.py" in D.HOST_ONLY and "_host.py" not in files
    ignore = (FOLDER / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert {"!_layout.py", "!_assets.py", "!_output.py"} <= set(ignore) and "!_host.py" not in ignore
    assert _image.image_tag().startswith("openhora-renderer:")


# ---------------------------------------------------------------- the host verbs

def test_the_host_exports_the_common_verbs_and_the_ffmpeg_engine_serves_them_beside_its_drawing_verbs():
    import argparse
    import ffmpeg
    assert _host.COMMON_VERBS == ("analyse", "base", "align", "check", "cover", "still", "verify")
    assert tuple(_host.COMMON_HANDLERS) == _host.COMMON_VERBS
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="verb")
    _host.add_common_parsers(sub)
    assert tuple(sub.choices) == _host.COMMON_VERBS
    assert set(ffmpeg.VERBS) == set(_host.COMMON_VERBS) | {"build", "pin-browser", "reap", "pin-blocks", "block-params", "render", "storyboard"}
    for verb in _host.COMMON_VERBS:
        assert ffmpeg.VERBS[verb] is _host.COMMON_HANDLERS[verb]


def test_the_host_verify_flags_name_the_stored_render_the_platform_file_and_optionally_the_hash_and_the_edit_list():
    import argparse
    p = argparse.ArgumentParser()
    _host.add_common_parsers(p.add_subparsers(dest="verb"))
    args = p.parse_args(["verify", "--in", "r.mp4", "--platform-file", "p.json"])
    assert (args.input, args.platform_file, args.sha256, args.edl) == ("r.mp4", "p.json", None, None)
    with pytest.raises(SystemExit):
        p.parse_args(["verify", "--in", "r.mp4"])


# ---------------------------------------------------------------- 1560 (VD12)

def test_the_caption_band_ends_at_1560_and_the_presets_say_why():
    assert DATA["zones"]["caption_bottom"] == 1560
    assert "VD12" in DATA["zones"]["note"] and "1560" in DATA["zones"]["note"]
    face = DATA["face_box_default"]
    assert _layout.zones(DATA, face)["caption"][1] == 1560


def test_a_caption_box_ending_at_1560_is_inside_the_band_and_one_ending_at_1561_is_not():
    band = _layout.zones(DATA, DATA["face_box_default"])
    assert _layout.caption_hit({"zone": "caption", "x": 100, "y": 1460, "w": 800, "h": 100}, band) is False
    assert _layout.caption_hit({"zone": "caption", "x": 100, "y": 1461, "w": 800, "h": 100}, band) is True
    assert _layout.caption_hit({"zone": "caption", "x": 100, "y": 1400, "w": 800, "h": 160}, band) is False


class FakePage:
    def __init__(self, bottom):
        self.bottom = bottom

    def open(self, path, cfg):
        pass

    def evaluate(self, js):
        pass

    def set_backdrop(self, color):
        pass

    def frame(self, t, payload):
        return {"html": "<p>caption</p>", "boxes": [{"zone": "caption", "x": 100, "y": self.bottom - 100, "w": 800, "h": 100}]}

    def screenshot(self):
        return b"\x89PNG\r\n\x1a\n"


class FakeChrome:
    """Stands in for the pinned browser: every page answers one caption box whose bottom is `bottom`."""
    bottom = 1560

    def __init__(self, browser, serve, workdir, time_limit=None):
        self.blocked, self.page_errors, self.sandbox, self.log_path = [], [], "on", workdir + "/log"
        self.proc = type("P", (), {"pid": 1})()

    def start(self):
        return {"product": "fake"}

    def new_page(self, w, h):
        return FakePage(type(self).bottom)

    def close(self):
        pass


def caption_timeline():
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "e" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, {})
    beats = {"schema_version": 1, "threshold": 0.6, "slots": [], "report": [], "unmatched": [], "fallbacks": [], "layouts": [], "overlays": []}
    return edl, _edl.resolve_timeline(edl, beats, VOCAB, DATA)


def draw(tmp_path, monkeypatch, bottom):
    edl, timeline = caption_timeline()
    assert timeline["captions"]
    monkeypatch.setattr(_frames._cdp, "Chrome", type("C", (FakeChrome,), {"bottom": bottom}))
    return _frames.draw_frames(data=DATA, edl=edl, timeline=timeline, serve={}, theme_fonts_urls={}, assets={}, browser="unused", jobs_n=1,
                               frames_dir=str(tmp_path / "frames"), workdir=str(tmp_path), time_limit=60,
                               templates={"caption": "oh/caption/renderat.html"}, png_blank=_render.blank_png)


def test_a_caption_drawn_ending_at_1560_passes_the_frame_loop(tmp_path, monkeypatch):
    layers, facts = draw(tmp_path, monkeypatch, 1560)
    assert layers == {"caption"} and facts["frames_rendered"] > 0


def test_a_caption_drawn_ending_at_1561_is_refused_with_caption_below_line_and_names_the_frame_and_the_bottom(tmp_path, monkeypatch):
    with pytest.raises(Refusal) as e:
        draw(tmp_path, monkeypatch, 1561)
    assert e.value.code == "caption_below_line"
    assert e.value.field.startswith("frame ") and e.value.field.endswith(" bottom 1561")
    assert D.FIELD.fullmatch(e.value.field)               # the host can pass it on as a closed field
