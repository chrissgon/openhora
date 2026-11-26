"""P1a: the transitions at joins on the ffmpeg engine, the compose side. The stage's text (`_media.transition_stage`), the five chains, and what they
leave alone, proved frame by frame on the host's own ffmpeg (framemd5 of `[vout]`, before the encoder) on a synthetic pattern whose pixels change on
every frame. C5: the speaker's picture is changed only on the frames the edit list names. Offline; the host's ffmpeg is not the image's, so every check
compares frames within one run of one binary and never fixed bytes. Every name is fictional."""
from __future__ import annotations

import copy
import re
import struct
import subprocess
import zlib

import pytest

import renderer_kit as K
import _edl
import _media
from _text import Refusal
from _vocab import load_data

DATA = load_data()
KINDS = _edl.FFMPEG_TRANSITIONS
FPS = 30
KEPT = [[0, 50], [60, 150]]          # the cut is at output frame 50
OUT = 140
needs_media = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
ZOOM_NONE = {"mode": "none", "factor": 1.0, "push_in": 0.0, "anchor_y": 0.25}


def row_for(kind, anchor, rid="t1", color="#101820"):
    """The plan's row of a transition of `kind` anchored on output frame `anchor`: the frames the kind's defaults give, as `_edl.resolve_transitions` writes them."""
    cfg = DATA["transitions"]["kinds"][kind]
    first = anchor - cfg["lead"]
    frames = [[first + i, float(v)] for i, v in enumerate(cfg["intensity"])]
    row = {"id": rid, "kind": kind, "start_frame": frames[0][0], "end_frame": frames[-1][0] + 1, "frames": frames, "anchor": "word", "params": copy.deepcopy(cfg)}
    if kind == "blur_to_card":
        row["color"] = color
    return row


def plan_of(src, rows, layers=(), kept=KEPT, out=OUT, **more):
    plan = {"src": str(src), "fps": FPS, "size": [1080, 1920], "has_audio": False, "src_matrix": "auto", "kept": kept, "layers": list(layers), "frames_dir": "frames",
            "pips": [], "out_frames": out, "max_bytes": 300000000, "out_name": "out.mp4", "zoom": ZOOM_NONE, "face": {"cx": 540, "cy": 500, "w": 600, "h": 400},
            "anchor": (540.0, 400.0), "fade": 0.015}
    if rows:
        plan["transitions"] = rows
    plan.update(more)
    return plan


def graph_of(argv):
    return argv[argv.index("-filter_complex") + 1]


def png_rgba(width, height, row_of) -> bytes:
    """A PNG whose row y is `row_of(y)` (RGBA bytes of the whole row)."""
    raw = b"".join(b"\x00" + row_of(y) for y in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def band_layer(path_dir, prefix, y0, y1, out=OUT):
    """A layer of `out` frames: transparent, but for an opaque band with a horizontal gradient over rows y0 to y1 (the pixels a glitch can move)."""
    clear = bytes(4 * 1080)
    gradient = b"".join(bytes((x * 255 // 1079, 255 - x * 255 // 1079, 128, 255)) for x in range(1080))
    still = png_rgba(1080, 1920, lambda y: gradient if y0 <= y < y1 else clear)
    for n in range(out):
        (path_dir / ("%s_%06d.png" % (prefix, n + 1))).write_bytes(still)


def make_source(path, seconds=6):
    """A recording whose pixels change on every frame: red is the frame number mod 16 times 16, green a horizontal ramp, blue a vertical one with a bright band."""
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=1080x1920:r=30:d=%d,format=gbrp,geq=r='mod(N,16)*16':g='mod(X,256)':b='if(gte(Y,700),200,Y/8)',format=yuv420p" % seconds,
                    "-pix_fmt", "yuv420p", str(path)], check=True)


def run_md5(plan, cwd, crop=None, graph_edit=None) -> list:
    """The md5 of every frame of `[vout]`, from the compose argv with its encoder replaced by `framemd5` (the graph is the render's). `crop` (w, h, x, y) is added
    after the whole picture is composed, so that one region of it can be compared."""
    argv = _media.compose_argv(K.FFMPEG, plan)
    g = graph_of(argv)
    if crop:
        assert g.endswith("[vout]")
        g = g[:-len("[vout]")] + ",crop=%d:%d:%d:%d[vout]" % crop
    cut = argv.index("-filter_complex")
    cmd = argv[:cut + 1] + [g, "-map", "[vout]", "-frames:v", str(plan["out_frames"]), "-f", "framemd5", "-"]
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-800:]
    lines = [l for l in done.stdout.splitlines() if l and not l.startswith("#")]
    return [l.rsplit(",", 1)[1].strip() for l in lines]


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp("tr")
    src = folder / "rec.mp4"
    make_source(src)
    frames = folder / "frames"
    frames.mkdir()
    band_layer(frames, "beat", 1000, 1100)        # a card's pixels: under the transitions
    band_layer(frames, "cap", 1700, 1800)         # the captions' pixels: over them
    return folder, src


# ---------------------------------------------------------------- the text of the graph (offline, no ffmpeg)

def test_a_plan_without_transitions_gives_the_argv_it_always_gave():
    base = plan_of("/in/rec", [], layers=["beat", "caption"])
    assert "transitions" not in base
    graph = graph_of(_media.compose_argv("ffmpeg", base))
    assert "tr_" not in graph
    assert graph == graph_of(_media.compose_argv("ffmpeg", dict(base, transitions=[])))
    plain = graph_of(_media.compose_argv("ffmpeg", plan_of("/in/rec", [])))
    assert plain.endswith("[cvt]%s[vout]" % _media.TAGS)        # no layer and no transition: the plain path, byte for byte


def test_the_stage_sits_between_the_beat_layer_and_the_caption_layer_and_every_label_starts_with_tr():
    rows = [row_for("glitch", 50), row_for("dip", 100, "t2")]
    graph = graph_of(_media.compose_argv("ffmpeg", plan_of("/in/rec", rows, layers=["beat", "caption"])))
    pieces = graph.split(";")
    at = {name: next(i for i, p in enumerate(pieces) if name in p) for name in ("[c_beat]", "[tr_s0]", "[tr_out]", "[l_caption]")}
    assert at["[c_beat]"] < at["[tr_s0]"] < at["[tr_out]"] < at["[l_caption]"]
    assert "[tr_out][l_caption]overlay=0:0:format=gbrp[c_caption]" in graph
    stage = [p for p in pieces if "tr_" in p and "l_caption" not in p]
    for piece in stage:        # every label that is written inside the stage is its own
        for label in re.findall(r"\[([^\]]+)\]", piece):
            assert label.startswith("tr_") or label == "c_beat", label
    assert "concat=n=" in graph and ",settb=1/30,setpts=N[tr_out]" in graph
    assert "enable=" not in graph and "between(" not in graph       # constants only: no time expression


def test_one_segment_per_transition_frame_and_plain_runs_between():
    rows = [row_for("glitch", 50), row_for("dip", 100, "t2")]       # 3 frames each
    g, label = _media.transition_stage("base", rows, FPS, OUT, (1080, 1920))
    assert label == "tr_out"
    assert g[0] == "[base]split=9" + "".join("[tr_s%d]" % k for k in range(9))      # 3 plain runs and 6 frames
    assert "trim=start_frame=0:end_frame=49" in g[1] and "trim=start_frame=52:end_frame=99" in "".join(g)
    assert "trim=start_frame=49:end_frame=50" in "".join(g) and "trim=start_frame=51:end_frame=52" in "".join(g)
    assert g[-1].endswith("concat=n=9:v=1:a=0,settb=1/30,setpts=N[tr_out]")


def test_a_transition_at_the_very_first_and_last_frames_adds_no_empty_segment():
    rows = [dict(row_for("dip", 1), frames=[[0, 0.6], [1, 1.0], [2, 0.6]]), dict(row_for("dip", 139, "t2"), frames=[[138, 0.6], [139, 0.6]])]
    g, _ = _media.transition_stage("base", rows, FPS, OUT, (1080, 1920))
    assert g[0].startswith("[base]split=6[")           # frames 0-2, a run, frames 138-139: no empty run at either end
    spans = [tuple(int(x) for x in m) for m in re.findall(r"trim=start_frame=(\d+):end_frame=(\d+)", "".join(g))]
    assert spans and all(a < b for a, b in spans) and spans[0][0] == 0 and spans[-1][1] == OUT


def test_the_glitch_with_its_terms_folded_is_the_same_expression_as_the_unfolded_one():
    for frame, i in ((49, 0.6), (50, 1.0), (7, 0.6)):
        folded, unfolded = _media.glitch_expressions(frame, i, True), _media.glitch_expressions(frame, i, False)
        assert folded != unfolded and len(folded[0]) < len(unfolded[0]) + 20
        assert "%d" % (frame * 83492791) in folded[0] and "83492791" in unfolded[0] and "%d" % (frame * 83492791) not in unfolded[0]


def test_the_graph_is_refused_past_the_kernels_limit_on_one_argument(monkeypatch):
    assert _media.GRAPH_MAX_BYTES == 131071
    plan = plan_of("/in/rec", [row_for("bloom", 50)])
    size = len(graph_of(_media.compose_argv("ffmpeg", plan)).encode())
    monkeypatch.setattr(_media, "GRAPH_MAX_BYTES", size)
    assert graph_of(_media.compose_argv("ffmpeg", plan))        # exactly the limit: drawn
    monkeypatch.setattr(_media, "GRAPH_MAX_BYTES", size - 1)
    with pytest.raises(Refusal) as caught:
        _media.compose_argv("ffmpeg", plan)
    assert caught.value.code == "graph_too_long"


def test_every_kind_has_a_chain_of_constants_only():
    for kind in KINDS:
        more, label = _media.transition_frame_filters(row_for(kind, 50), 49, 0.6, "tr_t0", (1080, 1920))
        text = ";".join(more)
        assert label in text and text.count("[tr_t0]") == 1
        assert "enable" not in text and "(t," not in text and "N," not in text.replace("mod(", "")      # no time or frame-number expression in a chain but the glitch's own `s`
        for name in {"glitch": ("geq",), "bloom": ("lutrgb", "gblur", "blend"), "zoom_blur": ("mix", "rgbashift"), "blur_to_card": ("gblur", "lutrgb"), "dip": ("lutrgb",)}[kind]:
            assert name in text, (kind, name)
    assert not set(_media.transition_frame_filters(row_for("dip", 5), 4, 0.6, "tr_t0", (1080, 1920))[0]) - {"[tr_t0]lutrgb=r='val*0.4':g='val*0.4':b='val*0.4'[tr_f4]"}


def test_the_filters_the_chains_need_are_the_ones_the_image_check_lists():
    import _inner
    for name in ("lutrgb", "gblur", "blend", "mix", "rgbashift"):
        assert name in _inner.REQUIRED_FILTERS


# ---------------------------------------------------------------- frame by frame, on the host's ffmpeg

@needs_media
def test_the_folded_glitch_draws_the_same_frame_as_the_unfolded_one(tmp_path):
    def draw(exprs):
        graph = "testsrc2=s=270x480:r=30:d=1,format=gbrp,trim=end_frame=1,%s,%s" % exprs
        done = subprocess.run([K.FFMPEG, "-loglevel", "error", "-f", "lavfi", "-i", graph, "-frames:v", "1", "-f", "md5", "-"], capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr[-400:]
        return done.stdout
    for frame, i in ((49, 0.6), (50, 1.0)):
        assert draw(_media.glitch_expressions(frame, i, True)) == draw(_media.glitch_expressions(frame, i, False))


@needs_media
def test_c5_frames_outside_the_rows_are_the_cut_source_frames_and_every_frame_inside_a_row_differs(media):
    """T-3. One transition of each kind, at anchors 49 (the join is 50: 2 mod 3), 70, 91, 112 (1 mod 3) and 130 (1 mod 3 again) so that R3-11's edges are all met: the frame
    count is the edit list's, the md5 of every frame outside the rows is that of the same render with no rows (a caption layer on both, so that both take the RGB path), and
    every frame inside differs. The same plan twice gives one list (T-6)."""
    folder, src = media
    rows = [row_for("glitch", 50, "t1"), row_for("bloom", 70, "t2"), row_for("zoom_blur", 91, "t3"), row_for("blur_to_card", 112, "t4"), row_for("dip", 131, "t5")]
    plain = run_md5(plan_of(src, [], layers=["caption"]), folder)
    drawn = run_md5(plan_of(src, rows, layers=["caption"]), folder)
    again = run_md5(plan_of(src, rows, layers=["caption"]), folder)
    assert len(plain) == len(drawn) == OUT
    assert drawn == again
    inside = {f for r in rows for f, _ in r["frames"]}
    assert len(inside) == 15
    for f in range(OUT):
        assert (drawn[f] != plain[f]) == (f in inside), f


@needs_media
def test_the_captions_stay_sharp_over_the_transition_and_a_card_under_it_is_drawn_with_it(media):
    """T-4 and T-5. The caption layer's band is the same bytes on a glitch frame as on the frame of the render with no transition, and the beat layer's band is not."""
    folder, src = media
    rows = [row_for("glitch", 50)]
    layers = ["beat", "caption"]
    cwd = folder
    for crop, same in (((1080, 60, 0, 1720), True), ((1080, 60, 0, 1020), False)):      # inside the bands: the chroma at a band's edge follows the rows beside it
        plain = run_md5(plan_of(src, [], layers=layers), cwd, crop=crop)
        drawn = run_md5(plan_of(src, rows, layers=layers), cwd, crop=crop)
        for f in (49, 50, 51):
            assert (drawn[f] == plain[f]) == same, (crop, f)
        assert drawn[48] == plain[48] and drawn[52] == plain[52]


@needs_media
def test_a_transition_on_the_first_frame_of_a_split_keeps_its_edges(tmp_path):
    """T-9. The split of `test_split_layout.py` (edges 31 and 92: 1 and 2 mod 3), with a dip over frames 30 to 32: only those frames differ from the render with no
    transition, and the moved half is on exactly the frames of the split on every frame outside the dip, as without it (R3-11)."""
    src = tmp_path / "rec.mp4"
    make_source(src)
    first, last = 31, 92
    split = {"start_frame": first, "end_frame": last, "crop": {"x": 0, "y": 420, "w": 1080, "h": 960}, "at": {"x": 0, "y": 0}}
    rows = [row_for("dip", first)]
    inside = {f for f, _ in rows[0]["frames"]}
    assert inside == {first - 1, first, first + 1}
    plain, drawn = plan_of(src, [], splits=[split]), plan_of(src, rows, splits=[split])
    whole_plain, whole_drawn = run_md5(plain, tmp_path), run_md5(drawn, tmp_path)
    assert len(whole_drawn) == len(whole_plain) == OUT
    assert {f for f in range(OUT) if whole_drawn[f] != whole_plain[f]} == inside
    half_plain, half_drawn = run_md5(plain, tmp_path, crop=(2, 2, 540, 400)), run_md5(drawn, tmp_path, crop=(2, 2, 540, 400))
    assert {f for f in range(OUT) if half_drawn[f] != half_plain[f]} == inside
    assert len({half_plain[f] for f in range(first - 4, first)}) > 1        # the source changes on every frame, so an edge a frame off would show
