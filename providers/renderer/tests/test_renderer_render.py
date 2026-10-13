"""The render, end to end on the host with a local Chromium (the container entry point, `_inner.py`): a fictional recording is
cut, drawn over and composed, and every hard limit of the render has a test. Skipped with a reason where ffmpeg or Chromium is absent."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

import renderer_kit as K
import _media

needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason=K.SKIP_MEDIA + "; " + K.SKIP_BROWSER)
INSTAGRAM = json.loads(K.INSTAGRAM.read_text())


@pytest.fixture(scope="module")
def short(tmp_path_factory):
    """A 4-sentence recording taken through analyse, base and align, and rendered once."""
    tmp = tmp_path_factory.mktemp("short")
    files = K.pipeline(tmp, K.build_transcript(K.SHORT_SENTENCES), K.SHORT_POST)
    files["slots"] = (3, 4)
    out = tmp / "out"
    started = time.time()
    rc, result, err = K.run_verb(*K.render_args(files, out, "--jobs", "2", "--cover-out", tmp / "cover.png", "--cover-offset-ms", "1500", slots=files["slots"]))
    assert rc == 0, err
    files.update(out=out, result=result, seconds=time.time() - started)
    return files


@needs_all
def test_the_render_is_a_content_addressed_immutable_file_that_passes_the_platforms_spec(short):
    r = short["result"]
    path = Path(r["path"])
    assert path.name == "render-%s.mp4" % r["sha256"][:12] and path.parent == short["out"]
    assert _media.sha256_file(str(path)) == r["sha256"] and stat.S_IMODE(path.stat().st_mode) == 0o400
    spec = _media.check_output(K.FFPROBE, str(path), INSTAGRAM)
    assert spec["failures"] == [] and (spec["facts"]["width"], spec["facts"]["height"]) == (1080, 1920) and spec["facts"]["codec"] == "h264"
    assert spec["facts"]["audio_codec"] == "aac" and spec["facts"]["faststart"] and spec["facts"]["fps"] == 30.0
    assert spec["facts"]["color"] == ["bt709", "bt709", "bt709", "tv"]
    assert not any(p.name.startswith(".render-") for p in short["out"].iterdir())      # the work folder is gone
    assert r["browser_sandbox"] == "on" and r["browser"].startswith(("HeadlessChrome", "Chrome")) and r["seconds"]["total"] > 0
    assert r["bytes"] == path.stat().st_size and r["unmatched_beats"] == [] and r["fonts"]["display"] == "system default"


@needs_all
def test_the_cut_removes_the_silences_and_an_overlaid_frame_differs_from_the_source(short, tmp_path):
    r = short["result"]
    assert r["output"]["duration"] < json.load(open(short["analysis"]))["facts"]["duration"] - 2
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    drawn = [e for e in r["beats_drawn"] if e["preset"] == "keyword"][0]
    t = (drawn["start_frame"] + 8) / 30
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-ss", "%.3f" % t, "-i", r["path"], "-frames:v", "1", str(a)], check=True)
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-ss", "0", "-i", str(short["src"]), "-frames:v", "1", str(b)], check=True)
    assert a.read_bytes() != b.read_bytes()


@needs_all
def test_the_cover_frame_is_a_png_at_the_offset_and_an_offset_past_the_end_is_refused(short, tmp_path):
    cover = Path(short["result"]["cover"]["path"])
    assert cover.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and stat.S_IMODE(cover.stat().st_mode) == 0o600
    rc, out, err = K.run_verb("cover", "--in", short["result"]["path"], "--offset-ms", "2000", "--out", tmp_path / "c.png")
    assert rc == 0 and (tmp_path / "c.png").exists()
    for offset in ("999999", "-5"):
        rc, out, err = K.run_verb("cover", "--in", short["result"]["path"], "--offset-ms", offset, "--out", tmp_path / "d.png")
        assert rc == 1 and err.startswith("refused: bad_cover_offset") and not (tmp_path / "d.png").exists()


@needs_all
def test_a_second_render_of_the_same_bytes_is_the_same_file_and_never_rewrites(short):
    rc, again, err = K.run_verb(*K.render_args(short, short["out"], "--jobs", "3", slots=short["slots"]))
    assert rc == 0, err
    assert again["sha256"] == short["result"]["sha256"] and again["path"] == short["result"]["path"] and again["replayed"] is True   # repeatable bytes
    path = Path(short["result"]["path"])
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    # an existing file of that name with other bytes is refused and left alone
    other = short["out"].parent / "other"
    other.mkdir()
    fake = other / path.name
    fake.write_bytes(b"not the same")
    rc, out, err = K.run_verb(*K.render_args(short, other, slots=short["slots"]))
    assert rc == 1 and err.startswith("refused: name_collision") and fake.read_bytes() == b"not the same"


@needs_all
def test_jobs_one_and_many_draw_the_same_frames(short, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    one = K.run_verb(*K.render_args(short, a, "--jobs", "1", slots=short["slots"]))[1]
    many = K.run_verb(*K.render_args(short, b, "--jobs", "4", slots=short["slots"]))[1]
    assert one["sha256"] == many["sha256"] == short["result"]["sha256"]


@needs_all
def test_dry_run_writes_nothing_and_prints_the_one_ffmpeg_command(short, tmp_path):
    out = tmp_path / "never"
    rc, result, err = K.run_verb(*K.render_args(short, out, "--dry-run", slots=short["slots"]))
    assert rc == 0 and result["dry_run"] is True and not out.exists()
    argv = result["ffmpeg_argv"]
    assert argv[0].endswith("ffmpeg") and "-fs" in argv and argv[argv.index("-i") - 4:argv.index("-i")] == ["-f", "mov", "-protocol_whitelist", "file"]
    assert result["frame_jobs"] > 0 and result["time_limit_seconds"] <= 1800


@needs_all
def test_the_recording_must_be_the_one_the_list_was_made_from(short, tmp_path):
    other = tmp_path / "other.mp4"
    K.make_source(other, K.build_transcript(K.SHORT_SENTENCES), rate=25)
    rc, out, err = K.run_verb("render", "--edl", short["edl"], "--beats", short["beats"], "--in", other, "--out", tmp_path / "o", "--platform-file", K.INSTAGRAM,
                              "--vocabulary", K.VOCABULARY, "--asset", "3=%s" % short["asset"], "--asset", "4=%s" % short["asset"])
    assert rc == 1 and err.startswith("refused: recording_changed") and not (tmp_path / "o").exists()


@needs_all
def test_every_asset_slot_needs_a_file_and_every_file_a_slot_and_the_bytes_are_checked(short, tmp_path):
    base = ["render", "--edl", short["edl"], "--beats", short["beats"], "--in", short["src"], "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY]
    rc, out, err = K.run_verb(*base, "--out", tmp_path / "o1", "--asset", "3=%s" % short["asset"])
    assert rc == 1 and err.startswith("refused: asset_missing beat4")
    rc, out, err = K.run_verb(*base, "--out", tmp_path / "o2", "--asset", "3=%s" % short["asset"], "--asset", "4=%s" % short["asset"], "--asset", "9=%s" % short["asset"])
    assert rc == 1 and err.startswith("refused: asset_unused beat9")
    rc, out, err = K.run_verb(*base, "--out", tmp_path / "o3", "--asset", "3=%s" % short["asset"], "--asset", "4=%s" % short["asset"], "--asset-sha256", "3=" + "0" * 64)
    assert rc == 1 and err.startswith("refused: asset_hash beat3")
    notimg = tmp_path / "x.png"
    notimg.write_bytes(b"GIF89a" + b"\0" * 64)
    rc, out, err = K.run_verb(*base, "--out", tmp_path / "o4", "--asset", "3=%s" % notimg, "--asset", "4=%s" % short["asset"])
    assert rc == 1 and err.startswith("refused: asset_type beat3")
    link = tmp_path / "link.png"
    os.symlink(short["asset"], link)
    rc, out, err = K.run_verb(*base, "--out", tmp_path / "o5", "--asset", "3=%s" % link, "--asset", "4=%s" % short["asset"])
    assert rc == 1 and err.startswith("refused: asset_unreadable")
    assert not any((tmp_path / n).exists() for n in ("o1", "o2", "o3", "o4", "o5"))


@needs_all
def test_a_list_for_another_platform_than_it_fits_is_refused_before_anything_is_drawn(short, tmp_path):
    for field, value, code in (("fps_min", 40, "fps_outside_platform"), ("max_seconds", 5, "longer_than_platform")):
        platform = json.loads(K.INSTAGRAM.read_text())
        platform["video"][field] = value
        pf = tmp_path / ("p-%s.json" % field)
        pf.write_text(json.dumps(platform))
        rc, out, err = K.run_verb("render", "--edl", short["edl"], "--beats", short["beats"], "--in", short["src"], "--out", tmp_path / ("o-" + field), "--platform-file", pf,
                                  "--vocabulary", K.VOCABULARY, "--asset", "3=%s" % short["asset"], "--asset", "4=%s" % short["asset"])
        assert rc == 1 and err.startswith("refused: " + code), err
        assert not (tmp_path / ("o-" + field)).exists()


@needs_all
def test_a_render_that_fails_the_platform_spec_after_the_fact_leaves_no_file(short, tmp_path):
    platform = json.loads(K.INSTAGRAM.read_text())
    platform["video"]["codecs"] = ["h265"]
    pf = tmp_path / "p.json"
    pf.write_text(json.dumps(platform))
    out = tmp_path / "out"
    rc, _, err = K.run_verb("render", "--edl", short["edl"], "--beats", short["beats"], "--in", short["src"], "--out", out, "--platform-file", pf,
                            "--vocabulary", K.VOCABULARY, "--asset", "3=%s" % short["asset"], "--asset", "4=%s" % short["asset"])
    assert rc == 1 and err.startswith("refused: platform_spec codec")
    assert not list(out.glob("render-*")) and not any(p.name.startswith(".render-") for p in out.iterdir())


@needs_all
def test_a_render_past_its_time_limit_is_stopped_with_the_browser_and_ffmpeg_and_leaves_nothing(short, tmp_path):
    out = tmp_path / "out"
    started = time.time()
    rc, _, err = K.run_verb(*K.render_args(short, out, "--time-limit", "10", "--jobs", "1", slots=short["slots"]), timeout=120)
    assert time.time() - started < 60
    assert rc == 1 and err.startswith("refused:") and (err.split()[1] in ("time_limit", "browser_failed", "frame_failed")), err
    assert not list(out.glob("render-*")) and not any(p.name.startswith(".render-") for p in out.iterdir())
    leftovers = subprocess.run(["pgrep", "-f", str(out)], capture_output=True, text=True).stdout.split()
    assert leftovers == []


@needs_all
def test_the_frame_budget_is_bounded(short, tmp_path):
    edl = json.load(open(short["edl"]))
    edl["out_frames"] = 27001
    bad = tmp_path / "edl.json"
    bad.write_text(json.dumps(edl))
    rc, _, err = K.run_verb("check", "--edl", bad, "--beats", short["beats"], "--vocabulary", K.VOCABULARY)
    assert rc == 1 and err.startswith("refused: bad_out_frames")


@needs_all
def test_every_frame_the_browser_writes_is_rgba_so_ffmpeg_never_reconfigures_its_graph(tmp_path):
    import _cdp, _edl, _frames, _render
    from _vocab import load_data, load_vocabulary
    data, vocab = load_data(), load_vocabulary(str(K.VOCABULARY))
    doc = K.build_transcript(K.SHORT_SENTENCES)
    edl, _ = _edl.build_base(doc, {"facts": {"duration": doc["duration"], "sha256": "f" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}, data, {})
    asset = tmp_path / "a.png"
    K.make_asset(asset)
    assets = _frames.load_assets({"beat1": str(asset)}, {}, data["limits"])
    beats = {"schema_version": 1, "threshold": 0.6, "slots": [{"slot": "beat1", "beat": 1, "param": "asset", "type": "image", "description": "a chart"}],
             "report": [], "unmatched": [], "fallbacks": [], "overlays": [],
             "layouts": [{"id": "b1", "beat": 1, "preset": "cutaway", "params": {"asset": "beat1"}, "word_from": 0, "word_to": 5, "score": 1.0}]}
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    serve, _ = _frames.load_templates(["cutaway.html", "caption.html"])
    serve.update({"/assets/beat1.png": (assets["beat1"]["data"], "image/png")})
    frames = tmp_path / "frames"
    _frames.draw_frames(data=data, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls={}, assets=assets, browser=K.BROWSER, jobs_n=2, frames_dir=str(frames),
                        workdir=str(tmp_path / "w"), time_limit=120, templates={"caption": "caption.html", "cutaway": "cutaway.html"}, png_blank=_render.blank_png)
    kinds = {open(frames / n, "rb").read(30)[25] for n in os.listdir(frames) if n.endswith(".png")}
    assert kinds == {6}                                                  # colour type 6: RGBA, the cutaway's opaque frames included


CAPTION_ONLY = """# Post: Two lines (a fictional fixture)

- Network: instagram
- Format: reel

```script
beat: 1
line: Hey, quick story about money.

beat: 2
line: Last year I tracked every expense for ninety days.
```

```post
Two lines.
```
"""


@needs_all
def test_a_4k_60fps_hevc_recording_comes_out_1080x1920_at_30_fps(tmp_path):
    doc = K.build_transcript(K.SENTENCES[:2])
    src = tmp_path / "iphone.mov"
    K.make_source(src, doc, size="3840x2160", rate=60, codec="libx265", timecode=True)       # landscape, 60 fps, HEVC, with a timecode data stream
    (tmp_path / "post.md").write_text(CAPTION_ONLY)
    files = {"src": src}
    for verb, args in (("analyse", ["--in", src, "--out", tmp_path / "analysis.json"]),
                       ("base", ["--transcript", K.write_json(tmp_path / "t.json", doc), "--analysis", tmp_path / "analysis.json", "--out", tmp_path / "edl.json"]),
                       ("align", ["--post", tmp_path / "post.md", "--transcript", tmp_path / "t.json", "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY,
                                  "--out", tmp_path / "beats.json"])):
        rc, out, err = K.run_verb(verb, *args)
        assert rc == 0, (verb, err)
    facts = json.load(open(tmp_path / "analysis.json"))["facts"]
    assert (facts["width"], facts["height"], round(facts["fps"])) == (3840, 2160, 60)
    rc, out, err = K.run_verb("render", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--in", src, "--out", tmp_path / "out",
                              "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY, "--jobs", "2")
    assert rc == 0, err
    assert (out["output"]["width"], out["output"]["height"], out["output"]["fps"]) == (1080, 1920, 30.0) and out["output"]["codec"] == "h264"


@needs_all
def test_a_transcript_with_the_shapes_of_a_real_one_renders(tmp_path):
    doc = K.real_shape_transcript()
    src = tmp_path / "s.mp4"
    K.make_source(src, {"duration": doc["duration"], "words": [w for w in doc["words"] if w["index"] < 38]})
    (tmp_path / "post.md").write_text(CAPTION_ONLY.replace("Hey, quick story about money.", "Hello again, this is a short story about a lost umbrella.")
                                      .replace("Last year I tracked every expense for ninety days.", "I left it on the bus, then I went back to look for it."))
    tr = K.write_json(tmp_path / "t.json", doc)
    assert K.run_verb("analyse", "--in", src, "--out", tmp_path / "analysis.json")[0] == 0
    rc, base, err = K.run_verb("base", "--transcript", tr, "--analysis", tmp_path / "analysis.json", "--out", tmp_path / "edl.json")
    assert rc == 0, err
    assert base["normalisation"]["dropped_words"] == 21 and base["normalisation"]["spread_runs"] >= 2 and base["normalisation"]["clamped_starts"] >= 1
    assert K.run_verb("align", "--post", tmp_path / "post.md", "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "beats.json")[0] == 0
    rc, out, err = K.run_verb("render", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--in", src, "--out", tmp_path / "out",
                              "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY)
    assert rc == 0, err
    assert out["output"]["duration"] > 5


@needs_all
def test_the_face_box_zoom_and_confirmed_retakes_change_the_picture_and_the_length(tmp_path):
    doc = K.build_transcript(K.SHORT_SENTENCES)
    src = tmp_path / "s.mp4"
    K.make_source(src, doc)
    tr = K.write_json(tmp_path / "t.json", doc)
    (tmp_path / "post.md").write_text(CAPTION_ONLY)
    assert K.run_verb("analyse", "--in", src, "--out", tmp_path / "analysis.json")[0] == 0
    sizes = {}
    for name, flags in (("zoom", []), ("flat", ["--zoom", "none"])):
        rc, base, err = K.run_verb("base", "--transcript", tr, "--analysis", tmp_path / "analysis.json", "--out", tmp_path / (name + ".json"), *flags)
        assert rc == 0, err
        assert K.run_verb("align", "--post", tmp_path / "post.md", "--transcript", tr, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY,
                          "--out", tmp_path / (name + "-beats.json"))[0] == 0
        rc, out, err = K.run_verb("render", "--edl", tmp_path / (name + ".json"), "--beats", tmp_path / (name + "-beats.json"), "--in", src,
                                  "--out", tmp_path / name, "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY)
        assert rc == 0, err
        sizes[name] = out
    assert sizes["zoom"]["sha256"] != sizes["flat"]["sha256"] and sizes["zoom"]["output"]["duration"] == pytest.approx(sizes["flat"]["output"]["duration"], abs=0.05)
    frame = {}
    for name in sizes:                                                    # the second kept range is the zoomed one: its first frame differs
        edl = json.load(open(tmp_path / (name + ".json")))
        second_start = (edl["kept"][0][1] - edl["kept"][0][0] + 3) / 30.0
        png = tmp_path / (name + ".png")
        subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-ss", "%.3f" % second_start, "-i", sizes[name]["path"], "-frames:v", "1", "-vf", "crop=1080:400:0:0", str(png)], check=True)
        frame[name] = png.read_bytes()
    assert frame["zoom"] != frame["flat"]
