"""The storyboard verb: a still per beat and a contact sheet, before any recording. Fictional fixtures only (renderer_kit's post and
words). The host side runs against the fake docker; the draw runs with a local Chromium and ffmpeg, and those tests skip with a reason
where either is absent."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

import pytest

import renderer_kit as K
import docker_kit as DK
import _cdp
import _docker as D
import _edl
import _frames
import _preview
import _render
from _text import Refusal
from _vocab import load_data, load_vocabulary

needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason=K.SKIP_MEDIA + "; " + K.SKIP_BROWSER)
DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
ALLOW = _frames.font_allowlist()

TWO = """# Post: Two cards (a fictional fixture)

- Owner: mkt-social-copy
- Network: instagram
- Format: reel

```script
beat: 1
line: The first rule is simple: name every dollar.
on-screen: Name every dollar
preset: keyword
icon: coin

beat: 2
line: A wise friend told me, small steps beat big plans.
on-screen: Small steps beat big plans.
preset: quote
author: A wise friend
```

```post
Two cards.
```
"""
BEAT_KEYWORD = {"preset": "keyword", "params": {"text": "Name every dollar", "icon": "coin"}, "line": "The first rule is simple: name every dollar."}
BEAT_QUOTE = {"preset": "quote", "params": {"text": "Small steps beat big plans.", "author": "A wise friend"}, "line": "A wise friend told me, small steps beat big plans."}


def write(tmp, name, text):
    path = Path(tmp) / name
    path.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
    return path


def storyboard_args(out, post=None, beat=None, *more):
    args = ["storyboard", "--vocabulary", K.VOCABULARY, "--out", out]
    args += ["--post", post, "--checker", K.CHECKER] if post else ["--beat", beat]
    return [*args, *more]


def shas(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).iterdir()) if p.suffix == ".png"}


def rows_of(text):
    import _align
    return _align.read_beats(text, VOCAB)


def lists_of(rows, **kw):
    edl, beats, notes, transcript, mentions = _preview.build_lists(rows, DATA, VOCAB, ALLOW, **kw)
    return edl, beats


# ---------------------------------------------------------------- what is refused, and before what

def test_a_script_the_checker_refuses_gives_no_stills_and_starts_no_browser(tmp_path):
    bad = write(tmp_path, "bad.md", TWO.replace("preset: keyword", "preset: confetti"))
    marker = tmp_path / "started"
    fake = tmp_path / "fake-browser"
    fake.write_text("#!/bin/sh\ntouch %s\nexit 1\n" % marker)
    fake.chmod(0o755)
    out = tmp_path / "out"
    rc, _, err = K.run_verb(*storyboard_args(out, bad), env={"RENDERER_BROWSER": str(fake)})
    assert rc == 1 and err.startswith("refused: script_refused post"), err
    assert not marker.exists() and (not out.exists() or not list(out.iterdir()))
    rc, _, err = K.run_verb(*storyboard_args(out, write(tmp_path, "empty.md", "- Format: reel\n")), env={"RENDERER_BROWSER": str(fake)})
    assert rc == 1 and err.startswith("refused:") and not marker.exists()
    notvideo = write(tmp_path, "note.md", TWO.replace("Format: reel", "Format: post"))
    rc, _, err = K.run_verb(*storyboard_args(out, notvideo), env={"RENDERER_BROWSER": str(fake)})
    assert rc == 1 and err.startswith("refused: post_format post") and not marker.exists()


def test_a_credential_shape_in_a_beat_is_refused_by_the_checks_before_anything_is_drawn(tmp_path):
    marker = tmp_path / "started"
    fake = tmp_path / "fake-browser"
    fake.write_text("#!/bin/sh\ntouch %s\nexit 1\n" % marker)
    fake.chmod(0o755)
    token = "ghp_" + "b2" * 18
    for beat in (dict(BEAT_QUOTE, params={"text": "key " + token}), dict(BEAT_KEYWORD, line="Paste " + token + " now")):
        out = tmp_path / "out"
        rc, _, err = K.run_verb(*storyboard_args(out, None, write(tmp_path, "beat.json", beat)), env={"RENDERER_BROWSER": str(fake)})
        assert rc == 1 and err.startswith("refused: credential_shaped"), err
        assert token not in err and not marker.exists() and (not out.exists() or not list(out.iterdir()))
    with pytest.raises(Refusal) as e:                                    # the same through the shared code: nothing but the checks ran
        lists_of([_preview.beat_row(VOCAB, dict(BEAT_QUOTE, params={"text": "key " + token}))])
    assert e.value.code == "credential_shaped"


def test_a_range_outside_the_words_or_a_beat_with_no_word_is_refused_by_the_render_checks():
    edl, beats = lists_of(rows_of(TWO))
    last = edl["words"][-1]["index"]
    for field, value in (("word_to", last + 5), ("word_from", -1), ("word_from", None)):
        broken = json.loads(json.dumps(beats))
        broken["overlays"][0][field] = value
        with pytest.raises(Refusal) as e:
            _render.check_documents(DATA, edl, broken, None, VOCAB, ALLOW)
        assert e.value.code == "bad_word_range"
    with pytest.raises(Refusal) as e:                                    # a line with no word has none to put the beat on
        _preview.synthetic_words([{"beat": 1, "line": "   ", "preset": "keyword", "params": {}, "slots": {}}], DATA["storyboard"])
    assert e.value.code == "beat_without_words"


def test_the_beat_json_is_closed_and_its_values_are_checked():
    for bad, code in (([], "not_object"), ({"preset": "keyword", "params": {}}, "missing_key"), (dict(BEAT_KEYWORD, extra=1), "unknown_key"),
                      (dict(BEAT_KEYWORD, preset="confetti"), "unknown_preset"), (dict(BEAT_KEYWORD, params={"nope": "x"}), "undeclared_param"),
                      (dict(BEAT_KEYWORD, params=[]), "params_not_object"), (dict(BEAT_KEYWORD, line=""), "empty_text")):
        with pytest.raises(Refusal) as e:
            _preview.beat_row(VOCAB, bad)
        assert e.value.code == code, bad
    for params, code in (({"text": "x" * 25}, "text_too_long"), ({"icon": "coin"}, "missing_param"), ({"text": "ok", "icon": "skull"}, "bad_icon")):
        with pytest.raises(Refusal) as e:
            lists_of([_preview.beat_row(VOCAB, dict(BEAT_KEYWORD, params=params))])
        assert e.value.code == code, params
    row = _preview.beat_row(VOCAB, {"preset": "cutaway", "params": {"asset": "a screenshot of the dashboard", "fit": "cover"}, "line": "Look at this."})
    assert row["slots"] == {"asset": "a screenshot of the dashboard"} and row["params"] == {"fit": "cover"}


def test_the_synthetic_words_run_at_the_configured_rate_with_a_fixed_gap_and_the_rate_is_in_the_presets_file():
    cfg = DATA["storyboard"]
    assert cfg["words_per_second"] == 2.5
    transcript, analysis, ranges = _preview.synthetic_words(rows_of(TWO), cfg)
    words = transcript["words"]
    assert all(abs((w["end"] - w["start"]) - 0.4) < 1e-9 for w in words) and ranges == {1: (0, 7), 2: (8, 17)}
    assert abs(words[8]["start"] - (words[7]["end"] + cfg["beat_gap"])) < 1e-9
    assert abs(transcript["duration"] - (words[-1]["end"] + cfg["trail"])) < 1e-9 and analysis["facts"]["has_audio"] is False
    assert all(int(round(x * 30 * 1000)) % 1000 == 0 for x in (0.4, cfg["beat_gap"], cfg["trail"]))      # every beat starts on a frame at 30 fps


def test_the_synthetic_list_has_no_cut_no_zoom_and_its_beats_never_clip_each_other():
    edl, beats = lists_of(rows_of(K.POST))
    assert len(edl["kept"]) == 1 and edl["kept"][0][0] == 0 and edl["zoom"]["mode"] == "none" and edl["zoom"]["push_in"] == 0.0
    assert edl["face_box"] == DATA["face_box_default"] and edl["source"]["has_audio"] is False
    timeline = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
    assert timeline["dropped"] == [] and not any(e.get("clipped") for e in timeline["beats"]) and len(timeline["beats"]) == 6
    for e in timeline["beats"]:
        f = _preview.rest_frame(e, DATA, edl["fps"])
        cfg = DATA["presets"][e["preset"]]
        assert e["start_frame"] < f < e["end_frame"] and f - e["start_frame"] <= int(-(-cfg["settled"] * 30 // 1))
        assert e["end_frame"] - f >= int(round(cfg["tail"] * 30)) + 1


# ---------------------------------------------------------------- the host side: what the container gets

def test_the_container_gets_no_recording_and_no_in_flag_only_the_staged_job_and_the_output_folder(tmp_path):
    (tmp_path / "home").mkdir()
    world = DK.World(tmp_path)
    world.cfg["run"] = "files"
    world.cfg["files"] = {"result.json": {"text": json.dumps({"ok": False, "code": "script_refused", "field": "post", "problems": []})}}
    world.cfg["rc"] = 1
    world.save()
    post = write(tmp_path, "p.md", TWO)
    rc, out, err = world.host(*storyboard_args(tmp_path / "o", post))
    assert rc == 1 and err.startswith("refused: script_refused post"), err
    argv = world.runs()[0]["argv"]
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert len(mounts) == 2 and mounts[0].endswith(":/job:ro") and mounts[1].endswith(":/out:rw") and not any("/in/recording" in m for m in mounts)
    inner = argv[argv.index("storyboard"):]
    assert "--in" not in inner and "--transcript" not in inner and "--analysis" not in inner and "--network" in argv
    assert argv[argv.index("--network") + 1] == "none" and not (tmp_path / "o").exists()
    assert "--beat" not in inner and "--post" in inner


def test_post_and_beat_are_exclusive_and_the_checker_goes_with_the_post(tmp_path):
    (tmp_path / "home").mkdir()
    world = DK.World(tmp_path)
    post, beat = write(tmp_path, "p.md", TWO), write(tmp_path, "b.json", BEAT_KEYWORD)
    for args in (["storyboard", "--vocabulary", K.VOCABULARY, "--out", tmp_path / "o"],
                 ["storyboard", "--vocabulary", K.VOCABULARY, "--out", tmp_path / "o", "--post", post],
                 ["storyboard", "--vocabulary", K.VOCABULARY, "--out", tmp_path / "o", "--post", post, "--checker", K.CHECKER, "--beat", beat],
                 ["storyboard", "--vocabulary", K.VOCABULARY, "--out", tmp_path / "o", "--beat", beat, "--checker", K.CHECKER]):
        rc, _, err = world.host(*args)
        assert rc == 2 and err.startswith("usage:"), (args, err)
    assert world.runs() == []


def test_the_storyboard_result_is_rebuilt_from_a_closed_schema_and_a_png_that_is_not_one_is_refused(tmp_path):
    (tmp_path / "home").mkdir()
    world = DK.World(tmp_path)
    still = tmp_path / "fake.png"
    still.write_bytes(b"GIF89a" + b"\0" * 64)
    digest = hashlib.sha256(still.read_bytes()).hexdigest()
    result = {"ok": True, "beats": [{"beat": 1, "preset": "keyword", "file": "beat-1.png", "sha256": digest, "frame": 3}], "skipped": [], "words": 8, "frame_jobs": 1, "frames_checked": 1,
              "jobs": 1, "sheet": {"file": "sheet.png", "sha256": digest, "tiles": 1, "columns": 1, "width": 282, "height": 492},
              "face_box": {"x": 240, "y": 620, "w": 600, "h": 560}, "fonts": {}, "templates": {}, "font_fallbacks": [], "mentions": [], "planted": "x"}
    world.cfg["run"] = "files"
    world.cfg["files"] = {"result.json": {"text": json.dumps(result)}, "beat-1.png": {"text": still.read_text(encoding="latin-1")},
                          "sheet.png": {"text": still.read_text(encoding="latin-1")}}
    world.save()
    rc, out, err = world.host(*storyboard_args(tmp_path / "o", write(tmp_path, "p.md", TWO)))
    assert rc == 1 and err.startswith("refused: container_file_not_png"), err
    assert not (tmp_path / "o").exists()                                 # nothing is named before every file has passed
    result["beats"][0]["file"] = "../../beat-1.png"
    world.cfg["files"]["result.json"] = {"text": json.dumps(result)}
    world.save()
    rc, out, err = world.host(*storyboard_args(tmp_path / "o", write(tmp_path, "p.md", TWO)))
    assert rc == 1 and err.startswith("refused: container_result_invalid")


def test_the_output_folder_may_hold_a_still_per_beat_and_no_more(tmp_path):
    assert D.STORYBOARD_OUT_ENTRIES >= load_vocabulary(str(K.VOCABULARY))["limits"]["beats_max"] + 2 > D.MAX_OUT_ENTRIES
    many = tmp_path / "many"
    many.mkdir()
    for k in range(D.STORYBOARD_OUT_ENTRIES):
        (many / ("f%d" % k)).write_text("x")
    D.check_out_folder(str(many), D.STORYBOARD_OUT_ENTRIES)
    with pytest.raises(Refusal):
        D.check_out_folder(str(many))
    (many / "one-more").write_text("x")
    with pytest.raises(Refusal):
        D.check_out_folder(str(many), D.STORYBOARD_OUT_ENTRIES)


# ---------------------------------------------------------------- drawn

@pytest.fixture(scope="module")
def drawn(tmp_path_factory):
    """The six-preset post stored once, through the fake docker (the host side and the container's entry point end to end)."""
    tmp = tmp_path_factory.mktemp("storyboard")
    (tmp / "home").mkdir()
    world = DK.World(tmp)
    post = write(tmp, "post.md", K.POST)
    out = tmp / "out"
    rc, result, err = world.host(*storyboard_args(out, post))
    assert rc == 0, err
    return {"world": world, "post": post, "out": out, "result": result, "tmp": tmp}


@needs_all
def test_a_still_per_beat_with_a_preset_and_a_sheet_are_written_read_only_and_checked(drawn):
    r, out = drawn["result"], drawn["out"]
    assert [b["beat"] for b in r["beats"]] == [3, 4, 5, 6, 7, 8] and r["skipped"] == [1, 2, 9] and r["frame_jobs"] == 6
    assert sorted(p.name for p in out.iterdir()) == sorted(["beat-%d.png" % n for n in (3, 4, 5, 6, 7, 8)] + ["sheet.png"])
    for b in r["beats"]:
        path = out / b["file"]
        facts = _frames.image_facts(path.read_bytes())
        assert facts == ("png", 1080, 1920) and hashlib.sha256(path.read_bytes()).hexdigest() == b["sha256"] and stat.S_IMODE(path.stat().st_mode) == 0o400
    sheet = out / "sheet.png"
    assert _frames.image_facts(sheet.read_bytes()) == ("png", r["sheet"]["width"], r["sheet"]["height"]) and r["sheet"]["tiles"] == 6
    assert r["sheet"]["columns"] == 4 and r["sheet"]["width"] == 4 * 282 and r["sheet"]["height"] == 2 * 492
    assert r["out_dir"] == str(out) and r["replayed"] is False and r["browser_sandbox"] == "on"


@needs_all
def test_the_same_inputs_give_the_same_bytes_again_at_any_core_count_and_job_count(drawn):
    first = shas(drawn["out"])
    runs = []
    for ncpu, jobs in ((2, "1"), (14, "8")):                             # the cores Docker reports change the CPU quota and the page workers
        tmp = Path(str(drawn["tmp"])) / ("again-%d" % ncpu)
        tmp.mkdir()
        (tmp / "home").mkdir()
        world = DK.World(tmp, ncpu=ncpu)
        out = tmp / "o"
        rc, result, err = world.host(*storyboard_args(out, drawn["post"]), "--jobs", jobs)
        assert rc == 0, err
        argv = world.runs()[0]["argv"]
        assert argv[argv.index("--cpus") + 1] == str(min(ncpu, D.DEFAULT_CPUS))
        runs.append(shas(out))
        assert result["jobs"] == min(int(jobs), 2 * min(ncpu, D.DEFAULT_CPUS))
    assert runs[0] == runs[1] == first and len(first) == 7
    again = drawn["world"].host(*storyboard_args(drawn["out"], drawn["post"]))          # into the folder it already is: a replay, nothing rewritten
    assert again[0] == 0 and again[1]["replayed"] is True and shas(drawn["out"]) == first


@needs_all
def test_a_still_equals_the_frame_the_render_loop_draws_for_the_same_list_at_that_instant(tmp_path):
    cfg = DATA["storyboard"]
    edl, beats = lists_of(rows_of(TWO))
    (tmp_path / "a").mkdir()
    shown = _preview.draw_rest_frames(data=DATA, vocab=VOCAB, allow=ALLOW, edl=edl, beats=beats, browser=K.BROWSER, jobs=2, work=str(tmp_path / "a"), time_limit=120)
    timeline = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
    timeline["captions"] = []
    templates = {e["preset"]: DATA["presets"][e["preset"]]["template"] for e in timeline["beats"]}
    serve, _ = _frames.load_templates(sorted(set(templates.values())))
    font_serve, _ = _frames.load_fonts(edl["theme"]["fonts"], ALLOW, DATA["limits"]["font_max_bytes"])
    serve.update(font_serve)
    full = tmp_path / "full"
    _, facts = _frames.draw_frames(data=DATA, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls=_render.font_urls_of(DATA, edl, font_serve), assets={},
                                   browser=K.BROWSER, jobs_n=3, frames_dir=str(full), workdir=str(tmp_path / "w"), time_limit=300, templates=templates,
                                   png_blank=_render.blank_png, backdrop={"color": cfg["backdrop"], "slot_fill": cfg["slot_fill"]})
    assert facts["frame_jobs"] > 100 and shown["facts"]["frames_rendered"] == 2 and shown["facts"]["frame_jobs"] > 2
    for n, f in shown["rest"].items():
        assert Path(shown["frames"][n]).read_bytes() == (full / ("beat_%06d.png" % f)).read_bytes()


@needs_all
def test_only_the_chosen_frames_are_drawn_and_a_full_loop_without_a_filter_is_unchanged(tmp_path, monkeypatch):
    edl, beats = lists_of(rows_of(TWO))
    timeline = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
    timeline["captions"] = []
    templates = {e["preset"]: DATA["presets"][e["preset"]]["template"] for e in timeline["beats"]}
    serve, _ = _frames.load_templates(sorted(set(templates.values())))
    font_serve, _ = _frames.load_fonts(edl["theme"]["fonts"], ALLOW, DATA["limits"]["font_max_bytes"])
    serve.update(font_serve)
    seen = []
    real = _cdp.Page.frame

    def spy(self, t, data):
        seen.append(round(t, 4))
        return real(self, t, data)

    monkeypatch.setattr(_cdp.Page, "frame", spy)
    common = dict(data=DATA, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls=_render.font_urls_of(DATA, edl, font_serve), assets={},
                  browser=K.BROWSER, jobs_n=2, workdir=str(tmp_path / "w"), time_limit=300, templates=templates, png_blank=_render.blank_png)
    _, all_jobs = _frames.frame_jobs(timeline, edl["out_frames"])
    pick = {("beat", all_jobs[10][0]), ("beat", all_jobs[-5][0])}
    _, subset = _frames.draw_frames(frames_dir=str(tmp_path / "subset"), only=pick, **common)
    assert subset["frame_jobs"] == 2 and len(seen) == 2 and sorted(os.listdir(tmp_path / "subset")) == sorted("beat_%06d.png" % f for _, f in pick)
    seen.clear()
    _, full = _frames.draw_frames(frames_dir=str(tmp_path / "full"), **common)        # no filter: every frame of the entries, then the filler of the render
    assert full["frame_jobs"] == len(all_jobs) == len(seen) and len(os.listdir(tmp_path / "full")) == edl["out_frames"] + 1
    for _, f in pick:                                                     # the same frame, the same bytes, with or without the filter
        assert (tmp_path / "subset" / ("beat_%06d.png" % f)).read_bytes() == (tmp_path / "full" / ("beat_%06d.png" % f)).read_bytes()


@needs_all
def test_the_in_process_storyboard_draws_exactly_one_frame_per_beat_with_a_preset(tmp_path, monkeypatch):
    calls = []
    real = _cdp.Page.screenshot
    monkeypatch.setattr(_cdp.Page, "screenshot", lambda self, *a, **k: calls.append(1) or real(self, *a, **k))
    out = tmp_path / "o"
    result = _preview.storyboard(rows=rows_of(K.POST), data=DATA, vocab=VOCAB, allow=ALLOW, tools=lambda: (K.FFMPEG, K.BROWSER), jobs=3, out_dir=str(out),
                                 scratch=str(tmp_path))
    assert len(calls) == 6 == result["frame_jobs"] and len(result["beats"]) == 6 and result["frames_checked"] > 100
    assert not any(p.name.startswith(".storyboard-") for p in tmp_path.iterdir())


@needs_all
def test_beat_and_post_give_the_same_still_for_the_same_beat(tmp_path):
    out_post, out_a, out_b = tmp_path / "post", tmp_path / "a", tmp_path / "b"
    assert K.run_verb(*storyboard_args(out_post, write(tmp_path, "p.md", TWO)))[0] == 0
    assert K.run_verb(*storyboard_args(out_a, None, write(tmp_path, "a.json", BEAT_KEYWORD)))[0] == 0
    assert K.run_verb(*storyboard_args(out_b, None, write(tmp_path, "b.json", BEAT_QUOTE)))[0] == 0
    post = shas(out_post)
    assert shas(out_a)["beat-1.png"] == post["beat-1.png"]
    assert shas(out_b)["beat-1.png"] == post["beat-2.png"] and shas(out_a)["sheet.png"] != post["sheet.png"]


@needs_all
def test_the_theme_and_the_face_box_change_the_stills(tmp_path):
    beat = write(tmp_path, "b.json", BEAT_KEYWORD)
    assert K.run_verb(*storyboard_args(tmp_path / "base", None, beat))[0] == 0
    base = shas(tmp_path / "base")
    for name, flags in (("color", ["--color", "accent=#07B6F0", "--color", "bg=#102030"]), ("face", ["--face-box", "240,700,600,500"])):
        rc, out, err = K.run_verb(*storyboard_args(tmp_path / name, None, beat, *flags))
        assert rc == 0, err
        assert shas(tmp_path / name)["beat-1.png"] != base["beat-1.png"], name
    rc, out, err = K.run_verb(*storyboard_args(tmp_path / "font", None, beat, "--font", "display=nope:800"))
    assert rc == 0 and out["font_fallbacks"] == [{"role": "display", "asked": "nope", "used": "default", "reason": "not in the font allow-list"}]
    for flags in (["--color", "sky=#FFFFFF"], ["--color", "accent=red"], ["--face-box", "1,2,3"]):
        rc, out, err = K.run_verb(*storyboard_args(tmp_path / "bad", None, beat, *flags))
        assert rc == 1 and not (tmp_path / "bad").exists() or not list((tmp_path / "bad").iterdir()), flags


@needs_all
def test_a_card_that_touches_the_face_box_gives_overlay_hits_face_and_a_nonzero_exit_and_no_still(tmp_path):
    """The templates keep a card in the band the face box leaves, so a hit is made here by a copy of the renderer whose keyword template
    puts the card at a fixed height (as the engine's own face test does); the real templates fit every preset above the default box."""
    import subprocess, sys
    copy = tmp_path / "r"
    shutil.copytree(K.RENDERER, copy, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    html = (copy / "templates" / "keyword.html").read_text()
    bad = html.replace("pos.style.top = z[0] + 'px';", "pos.style.top = '650px';")
    assert bad != html
    (copy / "templates" / "keyword.html").write_text(bad)
    _frames.write_pins(str(copy / "templates"))
    out = tmp_path / "o"
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "RENDERER_BROWSER": K.BROWSER}
    done = subprocess.run([sys.executable, str(copy / "_inner.py"), "storyboard", "--beat", str(write(tmp_path, "k.json", BEAT_KEYWORD)), "--vocabulary", str(K.VOCABULARY),
                           "--out", str(out)], capture_output=True, text=True, env=env, timeout=300)
    assert done.returncode == 1 and done.stderr.startswith("refused: overlay_hits_face"), done.stderr
    assert not out.exists() or not list(out.iterdir())


@needs_all
def test_the_real_templates_keep_every_preset_clear_of_a_face_box_that_leaves_the_least_room(tmp_path):
    items = " | ".join("x" * 30 for _ in range(4))
    for name, beat in (("list", {"preset": "list", "params": {"items": items, "icon": "star"}, "line": "Go."}),
                       ("quote", {"preset": "quote", "params": {"text": "q" * 120, "author": "a" * 40}, "line": "Go."})):
        rc, out, err = K.run_verb(*storyboard_args(tmp_path / name, None, write(tmp_path, name + ".json", beat), "--face-box", "240,210,600,560"))
        assert rc == 0, (name, err)


LARGEST = [("keyword", {"text": "k" * 24, "icon": "coin"}), ("list", {"items": " | ".join("x" * 30 for _ in range(4)), "icon": "star"}),
           ("number", {"value": "1,234,567", "label": "n" * 40}), ("quote", {"text": "q" * 120, "author": "a" * 40}),
           ("cutaway", {"asset": "a flat picture", "label": "c" * 40}), ("pip", {"asset": "a flat chart", "label": "p" * 40})]


def draw_frames_of(tmp, preset, edl, bl, frames):
    """The frames `frames` of the one beat of a list, through the render's loop with the storyboard's backdrop (nothing but the PNGs)."""
    timeline = _edl.resolve_timeline(edl, bl, VOCAB, DATA)
    timeline["captions"] = []
    template = DATA["presets"][preset]["template"]
    serve, _ = _frames.load_templates([template])
    font_serve, _ = _frames.load_fonts(edl["theme"]["fonts"], ALLOW, DATA["limits"]["font_max_bytes"])
    serve.update(font_serve)
    slot = timeline["beats"][0]["params"].get("asset")
    assets = {}
    if slot:
        Path(tmp, "a").mkdir(exist_ok=True)
        Path(tmp, "a", slot + ".png").write_bytes(_preview.flat_png(1080, 1920, DATA["storyboard"]["slot_fill"]))
        assets = _frames.load_assets({slot: str(Path(tmp, "a", slot + ".png"))}, {}, DATA["limits"])
        serve["/assets/%s.png" % slot] = (assets[slot]["data"], "image/png")
    folder = Path(tmp) / ("frames-%d" % len(list(Path(tmp).glob("frames-*"))))
    _frames.draw_frames(data=DATA, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls=_render.font_urls_of(DATA, edl, font_serve), assets=assets,
                        browser=K.BROWSER, jobs_n=1, frames_dir=str(folder), workdir=str(Path(tmp) / "w"), time_limit=120, templates={preset: template},
                        png_blank=_render.blank_png, only={("beat", f) for f in frames},
                        backdrop={"color": DATA["storyboard"]["backdrop"], "slot_fill": DATA["storyboard"]["slot_fill"]})
    return {f: (folder / ("beat_%06d.png" % f)).read_bytes() for f in frames}


@needs_all
@pytest.mark.parametrize("preset,params", LARGEST, ids=[p for p, _ in LARGEST])
def test_the_overlay_is_settled_at_the_chosen_frame_for_every_preset_at_its_largest_parameters(tmp_path, preset, params):
    """A long beat is drawn at `settled` seconds: the picture must not change on the frames after it. A short beat (the shortest line the
    vocabulary allows) is drawn at its end less its tail: the picture must not change on the frame before. The failing message names the
    constant of renderer-presets.json that moved."""
    for kind, line in (("long", " ".join(["Go"] * 40)), ("short", "Go.")):
        row = _preview.beat_row(VOCAB, {"preset": preset, "params": params, "line": line})
        edl, bl = lists_of([row])
        entry = _edl.resolve_timeline(edl, bl, VOCAB, DATA)["beats"][0]
        rest = _preview.rest_frame(entry, DATA, edl["fps"])
        settled_frame = entry["start_frame"] + int(-(-DATA["presets"][preset]["settled"] * 30 // 1))
        neighbours = [f for f in (rest + 1, rest + 2) if f < entry["end_frame"] - 9]            # before any template's exit (the longest is 0.3 s)
        assert neighbours and rest > entry["start_frame"], (preset, kind)
        (tmp_path / kind).mkdir()
        pics = draw_frames_of(tmp_path / kind, preset, edl, bl, [rest] + neighbours)
        constant = "renderer-presets.json presets.%s.settled" % preset if rest == settled_frame else "renderer-presets.json presets.%s.tail or min_duration" % preset
        for f in neighbours:
            assert pics[f] == pics[rest], "%s (%s beat): the picture still changes %+d frames after the chosen one; raise %s" % (preset, kind, f - rest, constant)
        if kind == "long":
            assert rest == settled_frame, preset


@needs_all
def test_a_card_that_overshoots_onto_the_face_box_while_it_pops_in_is_refused_although_clear_at_rest(tmp_path):
    """Every frame of a beat goes through the page and the face-box check (the render's check), and only the chosen frame is written. A
    copy of the renderer whose keyword card sits over the face box for its first 0.2 s (a stand-in for a pop-in overshoot) is refused."""
    import subprocess, sys
    copy = tmp_path / "r"
    shutil.copytree(K.RENDERER, copy, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    html = (copy / "templates" / "keyword.html").read_text()
    bad = html.replace("pos.style.top = z[0] + 'px';", "pos.style.top = (window.__t < 0.2 ? 650 : z[0]) + 'px';")
    bad = bad.replace("window.renderAt = function (t, data) {", "window.renderAt = function (t, data) {\n  window.__t = t;", 1)
    assert bad != html and "window.__t = t" in bad
    (copy / "templates" / "keyword.html").write_text(bad)
    _frames.write_pins(str(copy / "templates"))
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "RENDERER_BROWSER": K.BROWSER}
    args = [sys.executable, str(copy / "_inner.py"), "storyboard", "--beat", str(write(tmp_path, "k.json", BEAT_KEYWORD)), "--vocabulary", str(K.VOCABULARY)]
    done = subprocess.run([*args, "--out", str(tmp_path / "o")], capture_output=True, text=True, env=env, timeout=300)
    assert done.returncode == 1 and done.stderr.startswith("refused: overlay_hits_face"), done.stderr
    assert not (tmp_path / "o").exists() or not list((tmp_path / "o").iterdir())
    edl, bl = lists_of([_preview.beat_row(VOCAB, BEAT_KEYWORD)])                      # the frame it is drawn at is clear: only the check on every frame sees it
    rest = _preview.rest_frame(_edl.resolve_timeline(edl, bl, VOCAB, DATA)["beats"][0], DATA, edl["fps"])
    assert rest / 30.0 - _edl.resolve_timeline(edl, bl, VOCAB, DATA)["beats"][0]["start_frame"] / 30.0 > 0.2


@needs_all
def test_a_layout_slot_is_a_flat_generated_image_and_never_a_file_of_the_person(drawn):
    assert _frames.image_facts(_preview.flat_png(1080, 1920, "#59626F")) == ("png", 1080, 1920)
    assert _preview.flat_png(8, 8, "#59626F") == _preview.flat_png(8, 8, "#59626F")
    sources = (K.RENDERER / "_preview.py").read_text()
    assert "--asset" not in sources and "asset_files" not in sources
    inner = drawn["world"].runs()[0]["argv"]
    assert "--asset" not in inner and not any(a.startswith("assets/") for a in inner)


def test_the_sheet_command_is_one_ffmpeg_call_with_the_renders_bitexact_flags_and_draws_no_text():
    argv = _preview.sheet_argv("ffmpeg", ["/w/a.png", "/w/b.png", "/w/c.png"], DATA["storyboard"], "sheet.png")
    graph = argv[argv.index("-filter_complex") + 1]
    assert "lanczos+accurate_rnd+bitexact" in graph and "xstack=inputs=3" in graph and "layout=0_0|282_0|564_0" in graph
    assert "drawtext" not in graph and "+bitexact" in argv and argv[argv.index("-map_metadata") + 1] == "-1" and argv.count("-i") == 3
    assert argv[argv.index("-filter_threads") + 1] == "4"
    one = _preview.sheet_argv("ffmpeg", ["/w/a.png"], DATA["storyboard"], "sheet.png")
    assert "xstack" not in one[one.index("-filter_complex") + 1] and "[out]" in one[one.index("-filter_complex") + 1]
    assert _preview.sheet_geometry(5, DATA["storyboard"]) == {"columns": 4, "rows": 2, "cell_w": 282, "cell_h": 492, "width": 1128, "height": 984}
    assert _preview.sheet_geometry(12, DATA["storyboard"])["rows"] == 3 and _preview.sheet_geometry(2, DATA["storyboard"])["columns"] == 2


def test_the_storyboard_rate_equals_the_vocabulary_rate_once_the_vocabulary_has_one():
    vocab = json.loads(K.VOCABULARY.read_text())
    rate = (vocab.get("limits") or {}).get("words_per_second") or vocab.get("words_per_second")
    if rate is None:
        pytest.skip("shared/references/video-presets.json has no speaking rate yet (P3b / P5c-0 put it there)")
    assert rate == DATA["storyboard"]["words_per_second"]


def test_a_script_that_would_run_too_long_is_refused_with_its_own_code_before_anything_else():
    row = _preview.beat_row(VOCAB, {"preset": "keyword", "params": {"text": "Long", "icon": "coin"}, "line": " ".join(["w"] * 100)})
    rows = [dict(row, beat=k) for k in range(1, 13)]
    transcript, _, _ = _preview.synthetic_words(rows, DATA["storyboard"])
    assert transcript["duration"] > DATA["limits"]["input_seconds_max"]
    with pytest.raises(Refusal) as e:
        _preview.build_lists(rows, DATA, VOCAB, ALLOW)
    assert e.value.code == "script_too_long"


def test_a_platform_file_that_is_not_an_object_is_refused_by_render_verify_and_check_and_storyboard_needs_none(tmp_path):
    for text in ("null", "[]", "3", '"x"'):
        path = write(tmp_path, "platform.json", text)
        with pytest.raises(Refusal) as e:
            _render.read_platform(str(path))
        assert e.value.code == "bad_platform"
    null = write(tmp_path, "null.json", "null")
    nowhere = str(tmp_path / "no-such-tool")                 # the tools are named and missing: the platform must be refused before they are looked for
    for name in ("e.json", "b.json"):
        write(tmp_path, name, "{}")
    (tmp_path / "s.mp4").write_bytes(b"x")
    for args in (["render", "--edl", tmp_path / "e.json", "--beats", tmp_path / "b.json", "--in", tmp_path / "s.mp4", "--out", tmp_path / "o", "--platform-file", null,
                  "--vocabulary", K.VOCABULARY, "--ffmpeg", nowhere, "--ffprobe", nowhere],
                 ["verify", "--in", tmp_path / "s.mp4", "--platform-file", null, "--sha256", "0" * 64, "--ffmpeg", nowhere, "--ffprobe", nowhere],
                 ["check", "--edl", tmp_path / "e.json", "--beats", tmp_path / "b.json", "--vocabulary", K.VOCABULARY, "--platform-file", null]):
        rc, _, err = K.run_verb(*args)
        assert rc == 1 and err.startswith("refused: bad_platform platform"), (args[0], err)
    rc, _, err = K.run_verb("verify", "--in", tmp_path / "s.mp4", "--platform-file", write(tmp_path, "ok.json", "{}"), "--sha256", "0" * 64, "--ffmpeg", nowhere, "--ffprobe", nowhere)
    assert rc == 3 and err.startswith("refused: tool_missing")           # with an object, the next thing refused is the missing tool
    assert _render.check_documents.__doc__ and "storyboard" in _render.check_documents.__doc__


def good_result(files):
    return {"ok": True, "beats": [{"beat": 1, "preset": "keyword", "file": "beat-1.png", "sha256": "a" * 64, "frame": 3},
                                  {"beat": 2, "preset": "list", "file": "beat-2.png", "sha256": "b" * 64, "frame": 9}],
            "sheet": {"file": "sheet.png", "sha256": "c" * 64, "tiles": 2, "columns": 2, "width": 564, "height": 492}}


def test_the_host_trusts_nothing_the_container_says_about_its_files():
    import ffmpeg as H
    wanted = H.storyboard_files(good_result(None), DATA)
    assert wanted == [("beat-1.png", "a" * 64, (1080, 1920)), ("beat-2.png", "b" * 64, (1080, 1920)), ("sheet.png", "c" * 64, (564, 492))]
    cases = {}

    def broken(label, edit):
        doc = json.loads(json.dumps(good_result(None)))
        edit(doc)
        cases[label] = doc

    broken("no beats key", lambda d: d.pop("beats"))
    broken("no sheet key", lambda d: d.pop("sheet"))
    broken("empty beats", lambda d: d.update(beats=[]))
    broken("beat without file", lambda d: d["beats"][0].pop("file"))
    broken("beat without sha256", lambda d: d["beats"][0].pop("sha256"))
    broken("beat without number", lambda d: d["beats"][0].pop("beat"))
    broken("a name that is not its beat's", lambda d: d["beats"][0].update(file="beat-2.png"))
    broken("a name outside the folder", lambda d: d["beats"][0].update(file="../beat-1.png"))
    broken("the same beat twice", lambda d: d["beats"][1].update(beat=1, file="beat-1.png"))
    broken("a hash that is not one", lambda d: d["beats"][0].update(sha256="xyz"))
    broken("sheet without width", lambda d: d["sheet"].pop("width"))
    broken("sheet without sha256", lambda d: d["sheet"].pop("sha256"))
    broken("sheet with a huge declared size", lambda d: d["sheet"].update(width=60000, height=60000))
    broken("sheet larger than its grid", lambda d: d["sheet"].update(width=1128, height=984))
    broken("sheet with another tile count", lambda d: d["sheet"].update(tiles=5))
    broken("sheet with another name", lambda d: d["sheet"].update(file="other.png"))
    broken("a beat that is not an object", lambda d: d["beats"].__setitem__(0, 7))
    for label, doc in cases.items():
        with pytest.raises(Refusal) as e:
            H.storyboard_files(doc, DATA)
        assert e.value.code == "container_result_invalid", label


def test_a_png_whose_header_is_larger_than_the_frame_or_the_grid_is_refused_by_the_host(tmp_path):
    """A small file with a header that declares a huge size (a decode bomb for whoever opens it) never reaches the output folder."""
    import struct, zlib
    (tmp_path / "home").mkdir()
    world = DK.World(tmp_path)

    def png(w, h):
        def chunk(tag, body):
            return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00")) + chunk(b"IEND", b"")

    for still_size, sheet_size, code in (((1080, 1920), (282, 492), None), ((60000, 60000), (282, 492), "container_file_not_png"),
                                         ((1080, 1920), (30000, 30000), "container_file_not_png"), ((1080, 1919), (282, 492), "container_file_not_png")):
        still, sheet = png(*still_size), png(*sheet_size)
        result = {"ok": True, "beats": [{"beat": 1, "preset": "keyword", "file": "beat-1.png", "sha256": hashlib.sha256(still).hexdigest(), "frame": 3}],
                  "skipped": [], "words": 8, "frame_jobs": 1, "frames_checked": 5, "jobs": 1,
                  "sheet": {"file": "sheet.png", "sha256": hashlib.sha256(sheet).hexdigest(), "tiles": 1, "columns": 1, "width": 282, "height": 492},
                  "face_box": {"x": 240, "y": 620, "w": 600, "h": 560}, "fonts": {}, "templates": {}, "font_fallbacks": [], "mentions": []}
        world.cfg["run"] = "files"
        world.cfg["files"] = {"result.json": {"text": json.dumps(result)}, "beat-1.png": {"kind": "hex", "hex": still.hex()}, "sheet.png": {"kind": "hex", "hex": sheet.hex()}}
        world.save()
        out = tmp_path / ("o-%d" % still_size[1] + "-%d" % sheet_size[0])
        rc, res, err = world.host(*storyboard_args(out, write(tmp_path, "p.md", TWO)))
        if code is None:
            assert rc == 0, err
        else:
            assert rc == 1 and err.startswith("refused: " + code), err
            assert not out.exists()


def test_the_contact_sheet_works_in_the_scratch_folder_and_leaves_nothing_in_the_output_folder(tmp_path, monkeypatch):
    made = []
    real = tempfile_mkdtemp = __import__("tempfile").mkdtemp
    monkeypatch.setattr(_preview.tempfile, "mkdtemp", lambda *a, **k: made.append(k.get("dir")) or real(*a, **k))
    if not K.HAVE_FFMPEG:
        pytest.skip(K.SKIP_MEDIA)
    scratch, out = tmp_path / "scratch", tmp_path / "out"
    scratch.mkdir()
    out.mkdir()
    tile = scratch / "t.png"
    tile.write_bytes(_preview.flat_png(1080, 1920, "#112233"))
    result = _preview.contact_sheet(K.FFMPEG, [str(tile)], DATA["storyboard"], str(out / "sheet.png"), str(scratch))
    assert made == [str(scratch)] and result["tiles"] == 1 and sorted(p.name for p in out.iterdir()) == ["sheet.png"]
    assert [p for p in scratch.iterdir() if p.name.startswith(".sheet-")] == []
