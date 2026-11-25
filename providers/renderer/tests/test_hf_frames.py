"""The frame loop's second-contract path with a fake browser and fake pages: an admitted beat is drawn from its own page, every frame is written and none is
a link of another, the seek times are the entry's own, the first contract's path is not taken, the runs the pixel gates judge are the frames each admitted
beat owns, and what an admitted page does wrong is refused with its closed code. No browser, no ffmpeg."""
from __future__ import annotations

import os

import pytest

import renderer_kit as K
import _cdp
import _frames
import _render
from _text import Refusal
from _vocab import load_data

DATA = load_data()
FACE = {"x": 240, "y": 300, "w": 600, "h": 480}
PNG = b"\x89PNG-fake"


class Pages:
    opened, sought, closed = [], [], []


class FakeAdmittedPage:
    def __init__(self, fail=None):
        self.fail, self.n = fail, 0

    def open_admitted(self, path, ready, fonts, timeout_s=30):
        Pages.opened.append((path, ready, fonts))
        if self.fail == "open":
            raise _cdp.BlockFailed("never ready")

    def close(self):
        Pages.closed.append(self)

    def seek_admitted(self, t):
        Pages.sought.append(round(t, 4))
        self.n += 1
        if self.fail == "font":
            raise _cdp.CDPError("page: Error: font_not_allowed: family Georgia")
        if self.fail == "blocked":
            raise _cdp.RenderBlocked("blocked by the page policy")
        if self.fail == "timeout":
            raise _cdp.CDPError("timeout: Runtime.evaluate")
        return PNG + bytes([self.n % 256])


class FakeChrome:
    fail = None
    sandbox = "on"

    def __init__(self, browser, serve, workdir, time_limit=0, **kw):
        self.blocked, self.page_errors, self.proc = [], [], type("P", (), {"pid": 1})()
        self.pages = []

    def start(self):
        return {"product": "FakeChrome/1"}

    def send(self, method, params=None, session=None, timeout=60):
        return {"product": "FakeChrome/1"}

    def new_page(self, w, h, contract="renderat"):
        assert contract == "admitted"
        page = FakeAdmittedPage(FakeChrome.fail)
        self.pages.append(page)
        return page

    def close(self):
        pass


def timeline(entries, captions=()):
    return {"captions": list(captions), "beats": entries, "dropped": []}


def chunk(start, end, face=None):
    return {"start_frame": start, "end_frame": end, "word_from": 0, "word_to": 0, "face": dict(face or FACE)}


def entry(start, end, block="hf:demo", preset="keyword"):
    return {"id": "b%d" % start, "preset": preset, "block": block, "start_frame": start, "end_frame": end, "face": dict(FACE), "params": {"text": "x"}}


ADMITTED = {"pages": {"hf:demo": {0: "/h/b0/index.html"}}, "ready": "READY", "fonts": {"faces": [], "system": []}}


def draw(tmp_path, tl, admitted=ADMITTED, jobs_n=1, fail=None, **kw):
    Pages.opened, Pages.sought, Pages.closed = [], [], []
    FakeChrome.fail = fail
    edl = {"fps": 30, "size": [1080, 1920], "out_frames": 20, "words": [], "theme": {"colors": {}}}
    old = _frames._cdp.Chrome
    _frames._cdp.Chrome = FakeChrome
    try:
        return _frames.draw_frames(data=DATA, edl=edl, timeline=tl, serve={}, theme_fonts_urls={}, assets={}, browser="x", jobs_n=jobs_n, frames_dir=str(tmp_path / "f"),
                                   workdir=str(tmp_path), time_limit=60, templates={"hf:demo": None}, png_blank=_render.blank_png, admitted=admitted, **kw)
    finally:
        _frames._cdp.Chrome = old


def test_an_admitted_beat_is_drawn_from_its_own_page_every_frame_is_written_and_none_is_a_link(tmp_path):
    layers, facts = draw(tmp_path, timeline([entry(4, 9)]))
    assert layers == {"beat"} and facts["frames_rendered"] == 5 and facts["frames_reused"] == 0 and facts["frame_jobs"] == 5
    assert Pages.opened == [("/h/b0/index.html", "READY", {"faces": [], "system": []})] and Pages.sought == [0.0, round(1 / 30, 4), round(2 / 30, 4), round(3 / 30, 4), round(4 / 30, 4)]
    files = sorted(os.listdir(tmp_path / "f"))
    assert "beat_000004.png" in files and sum(f.startswith("beat_") for f in files) == 20 and "blank.png" in files
    assert [os.stat(tmp_path / "f" / f).st_nlink for f in files if f in ("beat_000004.png", "beat_000005.png", "beat_000008.png")] == [1, 1, 1]
    assert (tmp_path / "f" / "beat_000004.png").read_bytes()[:9] == PNG and (tmp_path / "f" / "beat_000005.png").read_bytes() != (tmp_path / "f" / "beat_000004.png").read_bytes()
    assert os.stat(tmp_path / "f" / "beat_000010.png").st_nlink >= 1 and (tmp_path / "f" / "beat_000010.png").stat().st_size == (tmp_path / "f" / "blank.png").stat().st_size


def test_each_worker_opens_its_own_page_and_the_same_entry_is_never_opened_twice_by_one_worker(tmp_path):
    draw(tmp_path, timeline([entry(0, 10)]), jobs_n=2)
    assert len(Pages.opened) == 2 and sorted(Pages.sought) == sorted([round(i / 30, 4) for i in range(10)])


def test_a_storyboard_draws_only_the_frames_it_names(tmp_path):
    draw(tmp_path, timeline([entry(4, 9)]), only={("beat", 6)}, check_all=True, backdrop=None)
    assert Pages.sought == [round(2 / 30, 4)] and sorted(os.listdir(tmp_path / "f")) == ["beat_000006.png"]


@pytest.mark.parametrize("fail,code", [("font", "font_not_allowed"), ("open", "block_failed"), ("timeout", "block_failed")])
def test_what_an_admitted_page_does_wrong_is_a_closed_code(tmp_path, fail, code):
    with pytest.raises(Refusal) as e:
        draw(tmp_path, timeline([entry(4, 9)]), fail=fail)
    assert e.value.code == code


def test_a_blocked_request_or_policy_violation_is_blocked_request(tmp_path):
    with pytest.raises(Refusal) as e:
        draw(tmp_path, timeline([entry(4, 9)]), fail="blocked")
    assert e.value.code == "blocked_request"


def test_admitted_call_maps_the_three_kinds_and_lets_a_block_pass():
    assert _frames.admitted_call(lambda a: a + 1, 1) == 2
    for exc, code in ((_cdp.CDPError("page: font_not_allowed: x"), "font_not_allowed"), (_cdp.BlockFailed("no"), "block_failed"), (_cdp.CDPError("timeout: x"), "block_failed")):
        with pytest.raises(Refusal) as e:
            _frames.admitted_call(lambda: (_ for _ in ()).throw(exc))
        assert e.value.code == code
    with pytest.raises(_cdp.RenderBlocked):
        _frames.admitted_call(lambda: (_ for _ in ()).throw(_cdp.RenderBlocked("x")))


def test_the_runs_the_gates_judge_are_the_frames_each_admitted_beat_owns_with_its_own_face_and_the_top_of_its_caption_band():
    plain, first, second = entry(0, 6, block="oh:keyword"), entry(8, 14), entry(20, 24)
    first["face"] = dict(FACE, y=310)
    tl = timeline([plain, first, second])
    admitted = {"pages": {"hf:demo": {1: "/h/b1/index.html", 2: "/h/b2/index.html"}}}
    rows = _render.admitted_ranges(DATA, tl, admitted, 30)
    assert [(r["start"], r["end"]) for r in rows] == [(8, 14), (20, 24)]
    assert rows[0]["line_y"] == 310 + 480 + DATA["zones"]["gap"] and rows[1]["line_y"] == 300 + 480 + DATA["zones"]["gap"]
    clipped = _render.admitted_ranges(DATA, timeline([entry(8, 14)]), {"pages": {"hf:demo": {0: "p"}}}, 10)
    assert [(r["start"], r["end"]) for r in clipped] == [(8, 10)]
    overlap = timeline([entry(8, 14), entry(11, 16, block="oh:keyword")])
    assert [(r["start"], r["end"]) for r in _render.admitted_ranges(DATA, overlap, {"pages": {"hf:demo": {0: "p"}}}, 30)] == [(8, 11)]      # a frame belongs to one entry


def test_the_layer_is_judged_once_with_the_edit_lists_face_as_the_default_and_before_anything_else(monkeypatch):
    seen = []
    monkeypatch.setattr(_render._alpha_gate, "check_layer", lambda *a: seen.append(a))
    edl = {"size": [1080, 1920], "out_frames": 30, "face_box": dict(FACE)}
    _render.check_admitted_layer(DATA, edl, timeline([entry(8, 14)]), {"pages": {"hf:demo": {0: "p"}}}, "/frames", "ffmpeg")
    assert len(seen) == 1 and seen[0][0] == "/frames" and seen[0][1][0]["start"] == 8 and seen[0][2:] == (1080, 1920, "ffmpeg", "beat")


# ---------------------------------------------------------------- the caption track (PF-a4)

CAPTIONS = {"pages": {"caption": {0: "/h/c0/index.html", 1: "/h/c1/index.html"}}, "ready": "READY", "fonts": {"faces": [], "system": []}}


def test_a_caption_chunk_of_the_second_contract_is_written_as_cap_frames_with_no_link_and_the_previous_page_of_the_track_is_closed(tmp_path):
    layers, facts = draw(tmp_path, timeline([], [chunk(2, 6), chunk(6, 9)]), admitted=CAPTIONS)
    assert layers == {"caption"} and facts["frames_rendered"] == 7 and facts["frames_reused"] == 0
    assert [o[0] for o in Pages.opened] == ["/h/c0/index.html", "/h/c1/index.html"] and len(Pages.closed) == 1      # the second page opened, the first closed
    files = sorted(os.listdir(tmp_path / "f"))
    assert sum(f.startswith("cap_") for f in files) == 20 and not any(f.startswith("beat_") for f in files)
    assert [os.stat(tmp_path / "f" / ("cap_%06d.png" % n)).st_nlink for n in (2, 3, 6)] == [1, 1, 1]
    assert Pages.sought[:4] == [0.0, round(1 / 30, 4), round(2 / 30, 4), round(3 / 30, 4)] and Pages.sought[4] == 0.0      # the second chunk starts at its own clock


def test_the_tracks_close_their_own_pages_and_a_beat_and_a_caption_on_together_close_nothing(tmp_path):
    both = {"pages": {"hf:demo": {0: "/h/b0/index.html"}, "caption": {0: "/h/c0/index.html"}}, "ready": "R", "fonts": {"faces": [], "system": []}}
    layers, _ = draw(tmp_path, timeline([entry(2, 8)], [chunk(2, 8)]), admitted=both)
    assert layers == {"beat", "caption"} and Pages.closed == [] and len(Pages.opened) == 2


def test_a_caption_chunk_with_no_page_in_a_timeline_that_has_a_page_for_a_beat_is_not_drawn_here(tmp_path):
    layers, _ = draw(tmp_path, timeline([entry(2, 8)], []), admitted={"pages": {"hf:demo": {0: "/h/b0/index.html"}}, "ready": "R", "fonts": {"faces": [], "system": []}})
    assert layers == {"beat"}


def test_caption_ranges_use_the_band_bottom_of_the_chunks_own_band_and_the_floor_of_six_frames():
    long_chunk, short_chunk, piece = chunk(0, 8), chunk(10, 14), chunk(14, 20, face=dict(FACE, y=400))
    piece["band"] = [1000, 1200]                          # a pip's or a split's band: the line is its own bottom
    tl = timeline([entry(22, 26)], [long_chunk, short_chunk, piece])
    admitted = {"pages": {"caption": {0: "p", 1: "p", 2: "p"}, "hf:demo": {0: "p"}}}
    rows = _render.admitted_ranges(DATA, tl, admitted, 30)
    by_start = {(r["prefix"], r["start"]): r for r in rows}
    assert by_start[("cap", 0)]["line_y"] == DATA["zones"]["caption_bottom"] and by_start[("cap", 0)]["require_drawn"] is True
    assert by_start[("cap", 10)]["require_drawn"] is False and by_start[("cap", 14)]["line_y"] == 1200
    assert not any("face" in r for r in rows)                      # nothing is judged against the face (2026-11-24)
    card = by_start[("beat", 22)]
    assert card["require_drawn"] is True and card["line_y"] == 300 + 480 + DATA["zones"]["gap"]


def test_each_prefix_is_judged_with_its_own_frames(monkeypatch):
    seen = []
    monkeypatch.setattr(_render._alpha_gate, "check_layer", lambda frames, rows, w, h, ff, prefix: seen.append((prefix, [r["start"] for r in rows])))
    edl = {"size": [1080, 1920], "out_frames": 30, "face_box": dict(FACE)}
    _render.check_admitted_layer(DATA, edl, timeline([entry(22, 26)], [chunk(0, 8)]), {"pages": {"caption": {0: "p"}, "hf:demo": {0: "p"}}}, "/frames", "ffmpeg")
    assert seen == [("beat", [22]), ("cap", [0])]
