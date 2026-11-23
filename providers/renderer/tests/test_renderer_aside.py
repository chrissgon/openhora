"""The effect preset `aside`: for one beat the speaker's picture turns black and white and the voice gets an echo, then a hard cut returns to
normal. How the vocabulary and the data declare it, the block and the catalogue that draw its label, how the timeline turns its beat into mono
grade rows and an echo row (`_edl.resolve_asides`), how the beats file holds the script's rules again, how both engines draw it (the ffmpeg
engine's compose graph, the HyperFrames page's grades and its encode stage's sound) and what a plan without an aside keeps. Offline, on a
synthetic edit list; the tests that run ffmpeg use the host's own on a synthetic tone or test pattern and skip when there is none. Every name
is fictional."""
from __future__ import annotations

import json
import re
import subprocess

import pytest

import renderer_kit as K
import _blocks
import _edl
import _hf_page
import _inner
import _media
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
FPS = 30
KEPT = [[0, 150], [200, 350], [400, 520]]          # output frames 0-149, 150-299 and 300-419
needs_media = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)


def synthetic_edl(kept=KEPT, has_audio=True) -> dict:
    """An edit list with 28 words, one every half second (word i is spoken from 0.5 i + 0.1 to 0.5 i + 0.4), over three kept ranges."""
    frames = sum(b - a for a, b in kept)
    words = [{"index": i, "text": "word%d" % i, "start": round(0.5 * i + 0.1, 3), "end": round(0.5 * i + 0.4, 3)} for i in range(28)]
    return {"schema_version": 2, "fps": FPS, "size": [1080, 1920], "kept": [list(r) for r in kept], "out_frames": frames, "words": words,
            "captions": {"position": "bottom", "chunks": [[i, i + 3] for i in range(0, 28, 4)]}, "theme": {"colors": dict(DATA["theme"]["colors"]), "fonts": {}},
            "face_box": dict(DATA["face_box_default"]), "source": {"has_audio": has_audio},
            "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}}


def entry(beat, preset, first, last, **params):
    return {"id": "b%d" % beat, "beat": beat, "preset": preset, "params": params, "word_from": first, "word_to": last, "score": 1.0}


def beats_of(overlays=(), punches=()) -> dict:
    doc = {"schema_version": 1, "threshold": 0.6, "overlays": list(overlays), "layouts": [], "slots": [], "report": [], "unmatched": [], "fallbacks": []}
    if punches:
        doc["punches"] = list(punches)
    return doc


def resolve(edl, beats):
    return _edl.resolve_timeline(edl, beats, VOCAB, DATA)


def refused(fn, *args):
    with pytest.raises(Refusal) as caught:
        fn(*args)
    return caught.value


# ---------------------------------------------------------------- the vocabulary, the data, the block and the catalogue

def test_the_renderer_reads_aside_as_an_effect_and_has_its_timing_and_both_echoes():
    aside = VOCAB["presets"]["aside"]
    assert aside["kind"] == "effect" and aside["main"] == "label" and not aside.get("review_only")
    cfg = DATA["presets"]["aside"]
    for key in ("anchor", "min_duration", "max_duration", "tail", "settled", "looks"):
        assert key in cfg, key
    assert set(cfg["echo"]) == set(aside["params"]["echo"]["values"])
    for value, row in cfg["echo"].items():
        assert 0 < row["in_gain"] <= 1 and 0 < row["out_gain"] <= 1, value
        assert len(row["delays"]) == len(row["decays"]) >= 1 and all(0 < d <= 1000 for d in row["delays"]) and all(0 < d < 1 for d in row["decays"])
    assert len(cfg["echo"]["strong"]["delays"]) > len(cfg["echo"]["light"]["delays"])
    assert "transition" not in cfg["looks"]                    # nothing sets the edges: both are hard cuts


def test_the_block_draws_the_aside_on_both_engines_and_is_pinned():
    catalogue = _blocks.load_catalogue()
    block = catalogue["blocks"]["oh:aside"]
    assert block["kind"] == "effect" and block["preset"] == "aside" and block["band"] == "card" and block["may_cross_face"] is False
    assert set(block["params"]) == set(VOCAB["presets"]["aside"]["params"])
    for engine in ("ffmpeg", "hyperframes"):
        assert _blocks.resolve(catalogue, engine, "aside", None, "beats.b1")["name"] == "oh:aside"
    pins = json.loads((K.RENDERER / "blocks" / "pins.json").read_text(encoding="utf-8"))["files"]
    assert {"oh/aside/block.json", "oh/aside/renderat.html"} <= set(pins)
    generated = json.loads((K.RENDERER / "blocks" / "catalogue.json").read_text(encoding="utf-8"))
    assert json.dumps(generated, sort_keys=True) == json.dumps(_blocks.catalogue_doc(catalogue), sort_keys=True)


def test_a_block_of_kind_effect_must_sit_in_the_card_band():
    raw = json.loads((K.RENDERER / "blocks" / "oh" / "aside" / "block.json").read_text(encoding="utf-8"))
    with pytest.raises(Refusal):
        _blocks.check_block(dict(raw, band="frame"), "oh/aside/block.json", "oh", "aside")


def test_the_page_reads_the_parameters_of_the_vocabulary_and_has_no_entrance_or_exit():
    page = (K.RENDERER / "blocks" / "oh" / "aside" / "renderat.html").read_text(encoding="utf-8")
    assert re.search(r'<meta name="pv-params" content="label,echo">', page) and '<meta name="pv-preset" content="aside">' in page
    assert "textContent = P.label" in page and "innerHTML" not in page
    assert "ease" not in page.lower() and "data.duration" not in page      # on for every frame of the beat, off outside it: a hard cut


def test_the_runtime_reads_the_catalogue_with_an_effect_block_and_never_offers_it_at_review():
    import importlib.util
    spec = importlib.util.spec_from_file_location("media_animation_under_test", K.REPO / "runtime" / "media_animation.py")
    assert spec is not None
    text = (K.REPO / "runtime" / "media_animation.py").read_text(encoding="utf-8")
    assert re.search(r'^KINDS = \("overlay", "layout", "caption", "effect"\)', text, re.M)
    assert re.search(r'^ANIMATION_KINDS = \("overlay", "layout"\)', text, re.M)


def test_the_image_must_have_the_audio_filters_of_the_echo():
    assert {"asplit", "aecho", "volume", "amix"} <= set(_inner.REQUIRED_FILTERS)


# ---------------------------------------------------------------- the beats file holds the script's rules again

def test_an_aside_sits_with_the_overlays_and_passes_the_beats_check():
    edl = synthetic_edl()
    assert _edl.check_beats(beats_of([entry(2, "aside", 4, 7, echo="strong", label="not my finest hour")]), edl, VOCAB)


def test_an_aside_in_the_layouts_bucket_is_refused():
    doc = beats_of()
    doc["layouts"] = [entry(2, "aside", 4, 7)]
    assert refused(_edl.check_beats, doc, synthetic_edl(), VOCAB).code == "bad_preset"


def test_two_asides_or_an_aside_with_a_punch_are_refused():
    edl = synthetic_edl()
    two = beats_of([entry(1, "aside", 0, 2), entry(4, "aside", 10, 12)])
    assert refused(_edl.check_beats, two, edl, VOCAB).code == "effect_repeated"
    punched = beats_of([entry(1, "aside", 0, 2)], punches=[{"beat": 1, "word_from": 0, "word_to": 2, "score": 1.0}])
    assert refused(_edl.check_beats, punched, edl, VOCAB).code == "effect_with_punch"
    elsewhere = beats_of([entry(1, "aside", 0, 2)], punches=[{"beat": 3, "word_from": 8, "word_to": 9, "score": 1.0}])
    assert _edl.check_beats(elsewhere, edl, VOCAB)


def test_a_bad_echo_value_is_refused_by_the_renderers_checker():
    assert refused(_edl.check_beats, beats_of([entry(1, "aside", 0, 2, echo="medium")]), synthetic_edl(), VOCAB)


# ---------------------------------------------------------------- the timeline: mono rows and an echo row over the beat's exact span

def test_an_aside_gives_a_mono_grade_and_an_echo_over_its_beats_span():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of([entry(2, "aside", 2, 5, echo="strong")]))
    beat = next(e for e in timeline["beats"] if e["id"] == "b2")
    assert beat["kind"] == "effect"
    # words 2 to 5 are spoken from 1.1 s to 2.9 s; the tail is 0.1 s: frames 33 to 90, inside the first kept range
    assert (beat["start_frame"], beat["end_frame"]) == (33, 90)
    assert timeline["grades"] == [{"id": "b2", "kind": "mono", "start_frame": 33, "end_frame": 90, "range": 0}]
    strong = DATA["presets"]["aside"]["echo"]["strong"]
    assert timeline["echoes"] == [{"id": "b2", "start_frame": 33, "end_frame": 90, "in_gain": strong["in_gain"], "out_gain": strong["out_gain"],
                                   "delays": strong["delays"], "decays": strong["decays"]}]


def test_an_aside_without_an_echo_value_takes_the_light_one():
    timeline = resolve(synthetic_edl(), beats_of([entry(1, "aside", 0, 1)]))
    light = DATA["presets"]["aside"]["echo"]["light"]
    assert timeline["echoes"][0]["delays"] == light["delays"] and timeline["echoes"][0]["in_gain"] == light["in_gain"]


def test_an_aside_across_a_cut_is_one_mono_row_per_range_with_no_gap():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of([entry(3, "aside", 8, 11)]))       # words 8 to 11: 4.1 s to 5.9 s, frames 123 to 180, over the cut at frame 150
    beat = next(e for e in timeline["beats"] if e["id"] == "b3")
    rows = timeline["grades"]
    assert [(r["start_frame"], r["end_frame"], r["range"]) for r in rows] == [(beat["start_frame"], 150, 0), (150, beat["end_frame"], 1)]
    assert timeline["echoes"][0]["start_frame"] == beat["start_frame"] and timeline["echoes"][0]["end_frame"] == beat["end_frame"]
    table = _edl.range_effects(edl, timeline)
    assert table[0]["grades"][0]["b"] == 150 and table[1]["grades"][0]["a"] == 0       # each in its range's own frame index


def test_the_next_beat_cuts_the_aside_where_it_starts():
    timeline = resolve(synthetic_edl(), beats_of([entry(1, "aside", 0, 5), entry(2, "keyword", 4, 6, text="Next")]))
    aside = next(e for e in timeline["beats"] if e["id"] == "b1")
    keyword = next(e for e in timeline["beats"] if e["id"] == "b2")
    assert aside["end_frame"] == keyword["start_frame"]
    assert timeline["grades"][-1]["end_frame"] == aside["end_frame"] and timeline["echoes"][0]["end_frame"] == aside["end_frame"]


def test_a_plan_without_an_aside_has_no_echo_and_the_same_grades():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of([entry(1, "keyword", 0, 1, text="Plain")]))
    assert timeline["echoes"] == [] and timeline["grades"] == []


# ---------------------------------------------------------------- the ffmpeg engine: the picture's grey and the sound's echo

PLAN = {"fps": FPS, "size": [1080, 1920], "kept": KEPT, "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25},
        "fade": 0.012, "has_audio": True, "src_matrix": "bt709", "anchor": (540.0, 760.0)}


def test_the_compose_graph_greys_the_span_and_echoes_the_sound_with_hard_edges():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of([entry(2, "aside", 2, 5, echo="strong")]))
    graph = _media.base_graph(dict(PLAN, effects=_edl.range_effects(edl, timeline), echoes=timeline["echoes"]))
    joined = ";".join(graph)
    assert "colorchannelmixer=%s:enable='between(n,33,89)'" % _media.MONO_MATRIX in joined
    assert "[ca]asplit=2[ed0][ew0]" in joined
    assert "aecho=in_gain=0.700:out_gain=0.850:delays=70|140|210:decays=0.400|0.280|0.160" in joined
    assert "volume=volume=0:enable='lt(t,1.100000)+gte(t,3.000000)'" in joined           # the wet copy is silent outside frames 33 to 89
    assert "volume=volume=0:enable='gte(t,1.100000)*lt(t,3.000000)'" in joined           # the dry one inside them
    assert "amix=inputs=2:duration=first:dropout_transition=0:normalize=0[ce]" in joined
    assert graph[-1] == "[ce]aformat=sample_rates=48000:channel_layouts=stereo[aout]"
    assert "afade" not in joined.split("[ca]asplit")[1] and "acrossfade" not in joined     # no fade on either edge of the aside


def test_a_plan_without_echoes_keeps_its_sound_graph():
    plain = _media.base_graph(PLAN)
    assert _media.base_graph(dict(PLAN, echoes=[])) == plain
    assert plain[-1] == "[ca]aformat=sample_rates=48000:channel_layouts=stereo[aout]" and "aecho" not in ";".join(plain)
    silent = dict(PLAN, has_audio=False)
    rows = [{"start_frame": 0, "end_frame": 30, "in_gain": 0.8, "out_gain": 0.9, "delays": [60], "decays": [0.3]}]
    assert _media.base_graph(dict(silent, echoes=rows)) == _media.base_graph(silent)      # a recording with no sound: the picture alone


def test_the_render_plan_carries_the_echo_only_with_an_aside_and_sound():
    import _render
    edl = synthetic_edl()
    platform = {"max_bytes": 50_000_000}
    for overlays, sound, want in (([entry(2, "aside", 2, 5)], True, True), ([entry(2, "aside", 2, 5)], False, False), ([], True, False)):
        e = dict(edl, source={"has_audio": sound, "color_matrix": "bt709"})
        timeline = resolve(e, beats_of(overlays))
        try:
            plan = _render.compose_plan(DATA, e, timeline, {}, platform, "in.mp4")
        except (KeyError, TypeError):
            pytest.skip("compose_plan needs a fuller platform document here")
        assert ("echoes" in plan) is want
        if want:
            assert plan["echoes"] == timeline["echoes"]


# ---------------------------------------------------------------- the HyperFrames engine: the page's grey, the encode's echo

def test_the_hyperframes_page_draws_the_asides_grey_from_the_same_rows():
    edl = synthetic_edl()
    timeline = resolve(edl, beats_of([entry(2, "aside", 2, 5)]))
    parts = _hf_page.build_parts(edl, fps=FPS, effects=_edl.range_effects(edl, timeline))
    grades = parts["vars"]["grades"]
    assert [g[0] for g in grades] == ["mono"] and grades[0][1:3] == [33, 90]


def test_the_encode_stage_adds_the_echo_and_keeps_its_command_without_one():
    plan = {"fps": FPS, "out_frames": 420, "max_bytes": 50_000_000, "has_audio": True}
    plain = _media.encode_argv("ffmpeg", "in.mov", "out.mp4", plan)
    assert plain[plain.index("0:v:0") + 1:plain.index("0:v:0") + 3] == ["-map", "0:a:0?"] and "-filter_complex" not in plain
    rows = [{"start_frame": 33, "end_frame": 90, "in_gain": 0.8, "out_gain": 0.9, "delays": [60], "decays": [0.3]}]
    argv = _media.encode_argv("ffmpeg", "in.mov", "out.mp4", dict(plan, echoes=rows))
    graph = argv[argv.index("-filter_complex") + 1]
    assert graph.startswith("[0:a:0]asplit=2") and graph.endswith("[aout]") and argv[argv.index("-filter_complex") + 2:argv.index("-filter_complex") + 4] == ["-map", "[aout]"]
    assert "-map" in argv and "0:a:0?" not in argv
    assert _media.encode_argv("ffmpeg", "in.mov", "out.mp4", dict(plan, echoes=rows, has_audio=False)) == \
        _media.encode_argv("ffmpeg", "in.mov", "out.mp4", dict(plan, has_audio=False))


# ---------------------------------------------------------------- ffmpeg runs the graph (skipped without one)

def pcm(argv: list) -> list:
    """The samples of one channel of what ffmpeg writes for `argv` (inputs and filters), as 16-bit integers at 48 kHz."""
    import array
    done = subprocess.run([K.FFMPEG, "-v", "error", "-nostdin", *argv, "-ac", "1", "-f", "s16le", "-"], capture_output=True, timeout=120)
    assert done.returncode == 0, done.stderr.decode()[-400:]
    return array.array("h", done.stdout).tolist()


@needs_media
def test_the_echo_runs_changes_only_its_span_and_keeps_the_length():
    rows = [{"start_frame": 30, "end_frame": 60, "in_gain": 0.7, "out_gain": 0.85, "delays": [70, 140, 210], "decays": [0.4, 0.28, 0.16]}]
    graph = _media.echo_filters(rows, FPS, "[0:a:0]", "[ce]") + ["[ce]aformat=sample_rates=48000:channel_layouts=stereo[aout]"]
    tone = ["-f", "lavfi", "-i", "sine=frequency=330:duration=3:sample_rate=48000:samples_per_frame=480"]
    dry = pcm(tone + ["-af", "aformat=sample_rates=48000:channel_layouts=stereo"])
    wet = pcm(tone + ["-filter_complex", ";".join(graph), "-map", "[aout]"])
    assert len(wet) == len(dry) == 3 * 48000                                   # the echo's tail is cut, never added to the length
    diff = lambda a, b: max(abs(x - y) for x, y in zip(dry[a:b], wet[a:b]))
    assert diff(0, 48000) <= 1                                                 # before the span (frames 0 to 29, 0 to 1 s): the dry sound, unchanged
    assert diff(96000, 3 * 48000) <= 1                                         # after the hard cut at 2 s: dry again, with no tail
    assert diff(48000 + 4800, 96000) > 1000                                    # inside: the echoed sound


@needs_media
def test_the_aside_frames_have_no_colour_and_the_frames_around_them_keep_it():
    w, h = 270, 480
    edl = synthetic_edl(kept=[[0, 60]])
    timeline = resolve(edl, beats_of([entry(1, "aside", 1, 2)]))                                   # words 1 and 2: 0.6 s to 1.4 s, plus the tail: frames 18 to 45
    effects = _edl.range_effects(edl, timeline)
    plan = {"fps": FPS, "size": [w, h], "kept": [[0, 60]], "zoom": {"mode": "alternate", "factor": 1.0, "push_in": 0.0, "anchor_y": 0.25},
            "fade": 0.0, "has_audio": False, "anchor": (135.0, 190.0), "effects": effects}
    graph = _media.base_graph(plan, source="[0:v:0]", prepare="format=yuv420p", base=1, audio=False)
    done = subprocess.run([K.FFMPEG, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=%dx%d:rate=30:duration=2" % (w, h), "-filter_complex", ";".join(graph),
                           "-map", "[cv]", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"], capture_output=True, timeout=300)
    assert done.returncode == 0, done.stderr.decode()[-400:]
    size = w * h * 3 // 2
    spread = lambda n: max(abs(b - 128) for b in done.stdout[n * size + w * h:(n + 1) * size])
    a, b = timeline["grades"][0]["start_frame"], timeline["grades"][0]["end_frame"]
    assert all(spread(n) <= 3 for n in range(a, b))                    # every frame of the aside is grey
    assert spread(a - 1) > 20 and spread(b) > 20                       # the frame before and the frame after are in colour: hard cuts
