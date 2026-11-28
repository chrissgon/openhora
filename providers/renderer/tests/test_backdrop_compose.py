"""P4b: the blurred shot on the ffmpeg engine, the compose side. The stage's text (`_media.blur_stage`, `_media.blur_filter`) and what it leaves alone, proved frame by
frame on the host's own ffmpeg (framemd5 of `[vout]`, before the encoder) on a synthetic pattern whose pixels change on every frame. C5: the speaker's picture is changed
only on the frames the edit list names, and a card or a caption drawn over the blurred span is as sharp as without it. Offline; the host's ffmpeg is not the image's, so
every check compares frames within one run of one binary and never fixed bytes. Every name is fictional."""
from __future__ import annotations

import copy
import re
import subprocess

import pytest

import renderer_kit as K
import _media
from _vocab import load_data
from test_transitions_compose import FPS, KEPT, OUT, band_layer, graph_of, make_source, needs_media, plan_of, row_for, run_md5

DATA = load_data()
BG = DATA["theme"]["colors"]["bg"]
LOOK = DATA["backdrop"]["blur"]
SPAN = (60, 100)


def blur_row(a=SPAN[0], b=SPAN[1], rid="a1", params=None):
    return {"id": rid, "start_frame": a, "end_frame": b, "params": dict(params or LOOK), "color": BG}


def with_blurs(rows, **more):
    return plan_of("/in/rec", [], blurs=rows, **more)


# ---------------------------------------------------------------- the text of the graph (offline, no ffmpeg)

def test_a_plan_without_blurs_gives_the_graph_it_always_gave():
    for layers in ([], ["beat"], ["beat", "caption"]):
        base = plan_of("/in/rec", [], layers=layers)
        graph = graph_of(_media.compose_argv("ffmpeg", base))
        assert "bk_" not in graph and graph == graph_of(_media.compose_argv("ffmpeg", dict(base, blurs=[])))
    assert graph_of(_media.compose_argv("ffmpeg", plan_of("/in/rec", []))).endswith("[cvt]%s[vout]" % _media.TAGS)      # the plain path, byte for byte
    with_rows = graph_of(_media.compose_argv("ffmpeg", with_blurs([blur_row()])))
    assert "bk_" in with_rows and with_rows.endswith("[bk_out]scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=%s,format=yuv420p,%s[vout]" % (_media.SWS, _media.TAGS))


def test_the_stage_is_drawn_on_base_first_and_every_label_it_writes_starts_with_bk():
    split = {"start_frame": 20, "end_frame": 40, "crop": {"x": 0, "y": 420, "w": 1080, "h": 960}, "at": {"x": 0, "y": 0}}
    rows = [row_for("glitch", 50)]
    graph = graph_of(_media.compose_argv("ffmpeg", plan_of("/in/rec", rows, layers=["beat", "caption"], splits=[split], blurs=[blur_row()])))
    pieces = graph.split(";")
    at = {name: next(i for i, p in enumerate(pieces) if name in p) for name in ("[base]", "[bk_s0]", "[bk_out]", "[sb0]", "[tr_s0]", "[l_caption]")}
    assert at["[base]"] < at["[bk_s0]"] < at["[bk_out]"] < at["[sb0]"] < at["[tr_s0]"] < at["[l_caption]"]      # under the splits, the cards, the transitions and the captions
    assert "[bk_out]split=2[sb0][sk0]" in graph
    stage, _ = _media.blur_stage("base", [blur_row()], FPS, OUT)
    assert all(p in pieces for p in stage)      # the stage's own pieces are the graph's, in order
    for piece in stage:
        for label in re.findall(r"\[([^\]]+)\]", piece):
            assert label.startswith("bk_") or label == "base", label
    assert "enable=" not in graph.split("[bk_out]")[0] and "between(" not in graph.split("[bk_out]")[0]      # constants only: no time expression in the stage
    other = set(re.findall(r"\[([^\]]+)\]", ";".join(p for p in pieces if "bk_" not in p)))
    assert not {l for l in other if l.startswith("bk_")} - {"bk_out"}


def test_one_segment_per_span_and_plain_runs_between_and_no_empty_run_at_either_end():
    g, label = _media.blur_stage("base", [blur_row(60, 100), blur_row(120, 130, "a2")], FPS, OUT)
    assert label == "bk_out" and g[0] == "[base]split=5[bk_s0][bk_s1][bk_s2][bk_s3][bk_s4]"
    assert g[1] == "[bk_s0]trim=start_frame=0:end_frame=60,setpts=PTS-STARTPTS[bk_p0]"
    assert g[2] == "[bk_s1]trim=start_frame=60:end_frame=100,setpts=PTS-STARTPTS[bk_t1]" and g[3].startswith("[bk_t1]gblur=sigma=40:steps=3,") and g[3].endswith("[bk_p1]")
    assert g[-1] == "[bk_p0][bk_p1][bk_p2][bk_p3][bk_p4]concat=n=5:v=1:a=0,settb=1/30,setpts=N[bk_out]"
    edge, _ = _media.blur_stage("base", [blur_row(0, 10), blur_row(130, OUT, "a2")], FPS, OUT)
    assert edge[0].startswith("[base]split=3[") and "trim=start_frame=10:end_frame=130" in "".join(edge)
    spans = [tuple(int(x) for x in m) for m in re.findall(r"trim=start_frame=(\d+):end_frame=(\d+)", "".join(edge))]
    assert spans == [(0, 10), (10, 130), (130, OUT)]
    whole, _ = _media.blur_stage("base", [blur_row(0, OUT)], FPS, OUT)
    assert whole[0] == "[base]split=1[bk_s0]"


def test_the_filter_text_is_constants_only_and_the_saturation_is_a_mix_of_the_identity_and_the_mono_matrix():
    text = _media.blur_filter("x", LOOK, BG, "y")
    assert text.startswith("[x]gblur=sigma=40:steps=3,colorchannelmixer=") and text.endswith("[y]") and "lutrgb=" in text
    assert "enable" not in text and "(t," not in text
    matrix = dict(kv.split("=") for kv in re.search(r"colorchannelmixer=([^,]+)", text).group(1).split(":"))
    assert set(matrix) == {a + b for a in "rgb" for b in "rgb"}
    mono = (.2126, .7152, .0722)
    for i, a in enumerate("rgb"):
        for j, b in enumerate("rgb"):
            assert float(matrix[a + b]) == pytest.approx(0.5 * mono[j] + (0.5 if i == j else 0), abs=1e-9)
        assert sum(float(matrix[a + b]) for b in "rgb") == pytest.approx(1.0)      # a grey stays grey: each row sums to 1
    grey = _media.blur_filter("x", dict(LOOK, saturation=0), BG, "y")
    assert re.search(r"colorchannelmixer=rr=0.2126:rg=0.7152:rb=0.0722:gr=0.2126", grey)      # saturation 0 is the mono matrix
    assert "(1-" not in text and "0.5" in text.split("lutrgb=")[1]


def test_with_saturation_one_the_text_is_the_blur_to_card_frame_text_at_full_intensity():
    cfg = DATA["transitions"]["kinds"]["blur_to_card"]
    frame = 77
    more, label = _media.transition_frame_filters(row_for("blur_to_card", 80, color=BG), frame, 1.0, "tr_t0", (1080, 1920))
    assert len(more) == 1 and label == "tr_f77"
    mine = _media.blur_filter("tr_t0", {"sigma": cfg["sigma"], "darken": cfg["darken"], "saturation": 1}, BG, label)
    assert mine == more[0] and "colorchannelmixer" not in mine


def test_the_graph_is_refused_past_the_kernels_limit_with_the_longer_graph(monkeypatch):
    plan = with_blurs([blur_row(10 * k, 10 * k + 5, "a%d" % k) for k in range(1, 12)])
    size = len(graph_of(_media.compose_argv("ffmpeg", plan)).encode())
    monkeypatch.setattr(_media, "GRAPH_MAX_BYTES", size - 1)
    with pytest.raises(Exception) as caught:
        _media.compose_argv("ffmpeg", plan)
    assert getattr(caught.value, "code", None) == "graph_too_long"


def test_the_filter_the_stage_needs_is_the_one_the_image_check_lists():
    import _inner
    for name in ("gblur", "colorchannelmixer", "lutrgb", "concat", "trim", "split"):
        assert name in _inner.REQUIRED_FILTERS


# ---------------------------------------------------------------- frame by frame, on the host's ffmpeg

@pytest.fixture(scope="module")
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp("bk")
    src = folder / "rec.mp4"
    make_source(src)
    frames = folder / "frames"
    frames.mkdir()
    band_layer(frames, "beat", 1000, 1100)        # a card's pixels: over the blurred shot
    band_layer(frames, "cap", 1700, 1800)         # the captions' pixels: over it too
    return folder, src


def md5_of_graph(plan, graph, cwd) -> list:
    argv = _media.compose_argv(K.FFMPEG, plan)
    cut = argv.index("-filter_complex")
    cmd = argv[:cut + 1] + [graph, "-map", "[vout]", "-frames:v", str(plan["out_frames"]), "-f", "framemd5", "-"]
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-800:]
    return [l.rsplit(",", 1)[1].strip() for l in done.stdout.splitlines() if l and not l.startswith("#")]


@needs_media
def test_c5_frames_outside_the_span_are_the_frames_of_the_render_without_it_and_every_frame_inside_differs(media):
    """A caption layer on both, so that both take the RGB path: the md5 of every frame outside the span is that of the same render with no blur, every frame inside differs,
    the count is the edit list's and the same plan twice gives one list. Spans start at 60 (0 mod 3) and 121 (1 mod 3), end at 100 (1 mod 3) and 142 (OUT is 140: clamped)."""
    folder, src = media
    rows = [blur_row(60, 100), blur_row(121, OUT, "a2")]
    plain = run_md5(plan_of(src, [], layers=["caption"]), folder)
    drawn = run_md5(plan_of(src, [], layers=["caption"], blurs=rows), folder)
    again = run_md5(plan_of(src, [], layers=["caption"], blurs=rows), folder)
    assert len(plain) == len(drawn) == OUT and drawn == again
    inside = set(range(60, 100)) | set(range(121, OUT))
    for f in range(OUT):
        assert (drawn[f] != plain[f]) == (f in inside), f
    assert len({plain[f] for f in range(56, 60)}) > 1        # the source changes on every frame, so an edge a frame off would show


@needs_media
def test_every_frame_inside_the_span_is_the_filter_applied_to_the_plain_frame(media):
    """The reference is one whole-clip pass of `blur_filter` over the plain picture (the same two RGB conversions as the compose's), compared on the span's frames."""
    folder, src = media
    plan = plan_of(src, [], blurs=[blur_row(60, 100)])
    drawn = run_md5(plan, folder)
    plain_plan = plan_of(src, [])
    plain_graph = graph_of(_media.compose_argv(K.FFMPEG, plain_plan))
    tail = "[cvt]%s[vout]" % _media.TAGS
    assert plain_graph.endswith(tail)
    ref_graph = (plain_graph[:-len(tail)] + "[cvt]scale=in_range=tv:in_color_matrix=bt709:out_range=pc:flags=%s,format=gbrp[rb];" % _media.SWS
                 + _media.blur_filter("rb", LOOK, BG, "rbb")
                 + ";[rbb]scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=%s,format=yuv420p,%s[vout]" % (_media.SWS, _media.TAGS))
    reference = md5_of_graph(plain_plan, ref_graph, folder)
    assert len(reference) == len(drawn) == OUT
    for f in range(60, 100):
        assert drawn[f] == reference[f], f
    assert len({reference[f] for f in range(60, 70)}) == 10


@needs_media
def test_the_cards_and_the_captions_stay_sharp_over_the_blurred_span(media):
    """The beat layer's band and the caption layer's band are the same bytes inside the span as on the render with no blur; the rest of the picture is not."""
    folder, src = media
    layers = ["beat", "caption"]
    rows = [blur_row(60, 100)]
    for crop, same in (((1080, 60, 0, 1720), True), ((1080, 60, 0, 1020), True), ((1080, 100, 0, 300), False)):      # inside the bands: the chroma at a band's edge follows the rows beside it
        plain = run_md5(plan_of(src, [], layers=layers), folder, crop=crop)
        drawn = run_md5(plan_of(src, [], layers=layers, blurs=rows), folder, crop=crop)
        for f in (60, 61, 80, 99):
            assert (drawn[f] == plain[f]) == same, (crop, f)
        assert drawn[59] == plain[59] and drawn[100] == plain[100]


@needs_media
def test_a_blur_over_the_first_frames_of_a_split_keeps_the_splits_edges(tmp_path):
    """The split of `test_split_layout.py` (edges 31 and 92), with a blur over 31 to 91: the moved half is on exactly the frames of the split, as without the blur
    (R3-11), and the half is drawn from the blurred shot."""
    src = tmp_path / "rec.mp4"
    make_source(src)
    first, last = 31, 92
    split = {"start_frame": first, "end_frame": last, "crop": {"x": 0, "y": 420, "w": 1080, "h": 960}, "at": {"x": 0, "y": 0}}
    plain, drawn = plan_of(src, [], splits=[split]), plan_of(src, [], splits=[split], blurs=[blur_row(first, last)])
    a, b = run_md5(plain, tmp_path), run_md5(drawn, tmp_path)
    assert len(a) == len(b) == OUT
    assert {f for f in range(OUT) if a[f] != b[f]} == set(range(first, last))
