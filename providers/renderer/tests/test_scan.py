"""The `scan` verb (`_scan.py` inside the image, `_host.verb_scan` on the host; package P9-a1). Neither Tesseract nor OpenCV is on the host that runs these
tests: the four readers (`decode_frames`, `make_qr_reader`, `thumbnail`, `read_text`) are replaced by fakes through the module's seams, so the selection, the
cleaning, the QR payload forms, the budget and the host's checks are tested with no tool at all. Every text, host and name here is fictional.
"""
from __future__ import annotations

import json
import re
import time

import pytest

import renderer_kit as K
import docker_kit as DK
import _docker as D
import _host
import _scan
from _text import Refusal

REPO = K.REPO
HEX_A, HEX_B = "a" * 12, "b" * 12
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
MP4_HEAD = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 32


# ---------------------------------------------------------------- the constants that must equal the host's and the runtime's

def test_the_scan_constants_equal_the_ones_they_copy():
    stock = (REPO / "runtime" / "media_stock.py").read_text(encoding="utf-8")
    assert int(re.search(r"^MAX_FULL = (\d+)", stock, re.M).group(1)) == _scan.MAX_ASSETS == _host.SCAN_MAX_ASSETS
    documents = (REPO / "runtime" / "deliver_document.py").read_text(encoding="utf-8")
    assert re.search(r'^HOST = re\.compile\(r"(.*)"\)', documents, re.M).group(1) == _scan.HOST.pattern
    assert _scan.MAX_SIDE == 3840
    assert _host.SCAN_FRAMES_MAX == 601


def test_the_unsafe_characters_are_the_ones_the_host_refuses():
    for code in range(0x10000):
        ch = chr(code)
        assert bool(_scan.UNSAFE.fullmatch(ch)) == (D.SAFE_TEXT.fullmatch(ch) is None), hex(code)


def test_the_codes_are_closed_and_sorted():
    assert _scan.SCAN_CODES == ("text_found", "qr_link", "qr_action", "qr_text", "qr_unreadable", "scan_partial")
    assert _scan.ASSET_NAME.pattern == _host.ASSET_FILE.pattern.replace("([0-9a-f]{12})", "[0-9a-f]{12}")


# ---------------------------------------------------------------- which frames of a clip are read for text

CELLS = 64 * 36


def still(n, value=100):
    return [[value] * CELLS for _ in range(n)]


def with_caption(thumbs, first, last, cells=99, delta=30):
    """A caption box on a still picture: `cells` thumbnail cells move by `delta` on frames first..last (a measured one: 99 cells, a mean difference of 1.3 of 255)."""
    out = [list(t) for t in thumbs]
    for i in range(first, last + 1):
        for j in range(1000, 1000 + cells):
            out[i][j] += delta
    return out


def moving(n, seed=0):
    """A picture that moves: every cell changes a lot from one frame to the next."""
    return [[(j * 7 + (i + seed) * 53) % 256 for j in range(CELLS)] for i in range(n)]


def mean_diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


def read_every_window(chosen, n, span=12):
    return all(any(start <= c < start + span for c in chosen) for start in range(0, n - span + 1))


def test_a_still_clip_is_read_on_the_grid_the_first_and_the_last_frame_only():
    chosen, qualified = _scan.select_text_frames(still(100))
    assert chosen == [0, 30, 60, 90, 99] and qualified == 5


def test_a_caption_that_appears_on_a_still_picture_moves_the_mean_by_about_one_and_is_still_read():
    thumbs = with_caption(still(200), 120, 131)
    assert 1.0 < mean_diff(thumbs[120], thumbs[119]) < 1.6           # the live figure: 1.26 to 1.6 against a threshold of 6 that never fired
    chosen, qualified = _scan.select_text_frames(thumbs)
    assert 120 in chosen and 132 in chosen and qualified == len(chosen)
    assert [c for c in chosen if 120 <= c <= 131] == [120]            # read once, on the frame it appears; the frame it goes is read too (132)


def test_compression_noise_is_not_a_change_and_a_caption_of_too_few_cells_is_not_either():
    noisy = [[100 + (j + i) % 8 for j in range(CELLS)] for i in range(60)]          # every cell moves by up to 7, under CELL_DIFF
    assert _scan.select_text_frames(noisy)[0] == [0, 30, 59]
    assert _scan.select_text_frames(with_caption(still(60), 10, 20, cells=_scan.CELLS_MIN - 1))[0] == [0, 30, 59]
    assert 10 in _scan.select_text_frames(with_caption(still(60), 10, 20, cells=_scan.CELLS_MIN))[0]


def test_a_slow_fade_is_caught_against_the_last_read_frame_not_the_previous_one():
    thumbs = [[100 + min(i, 40) // 4 * 2 + (j < 40) * 0 for j in range(CELLS)] for i in range(40)]      # every cell rises 2 each 4 frames: each step is under 8, the drift is not
    assert any(0 < c < 30 for c in _scan.select_text_frames(thumbs)[0])


def test_a_moving_clip_is_sampled_evenly_at_a_step_that_cannot_skip_twelve_frames():
    for n in (120, 300, 601):
        chosen, qualified = _scan.select_text_frames(moving(n))
        assert qualified == n and len(chosen) == min(n, _scan.OCR_FRAMES_MAX) and chosen[0] == 0 and chosen[-1] == n - 1 and chosen == sorted(set(chosen))
        assert max(b - a for a, b in zip(chosen, chosen[1:])) <= 7 and read_every_window(chosen, n), n


def test_a_caption_on_a_moving_picture_is_read():
    thumbs = with_caption(moving(601), 300, 311, cells=200, delta=60)
    assert any(300 <= c <= 311 for c in _scan.select_text_frames(thumbs)[0])


def test_no_frames_give_nothing():
    assert _scan.select_text_frames([]) == ([], 0)


def test_the_worst_case_is_bounded_by_the_cap():
    assert _scan.OCR_FRAMES_MAX == 100 and _host.SCAN_FRAMES_MAX == 601 and (601 - 1) / float(_scan.OCR_FRAMES_MAX - 1) < 6.1
    assert 6 * (_scan.OCR_FRAMES_MAX + 1) <= 606                   # text reads of a six-clip set: 606 at most (about 0.5 s each live), against a 480 s inner budget


# ---------------------------------------------------------------- cleaning

def test_a_planted_line_comes_out_printable_and_short():
    line = "Sale\u202e now\u200b \ufeff50%\x07 off" + " word" * 80
    out = _scan.clean_line(line)
    assert out.startswith("Sale now 50% off word") and len(out) <= _scan.LINE_MAX == 160
    assert all(ch.isprintable() for ch in out) and not _scan.UNSAFE.search(out)
    assert "  " not in out
    assert _scan.clean_line("a b\tc") == "a bc"                       # a no-break space is a space; a control character is removed


def test_nine_lines_become_eight_and_say_it_was_cut():
    lines = ["line number %d" % n for n in range(9)]
    out = _scan.cut_text(lines)
    assert out["lines"] == lines[:8] and out["cut"] is True and out["chars"] == sum(len(x) for x in lines)


def test_the_character_cap_cuts_the_last_line_and_says_so():
    lines = ["x" * 160] * 5                                              # five identical lines are one line: make them differ
    lines = ["%d" % n + "x" * 159 for n in range(5)]
    out = _scan.cut_text(lines)
    assert sum(len(x) for x in out["lines"]) == _scan.TEXT_CHARS_MAX and out["chars"] == 800 and out["cut"] is True


def test_a_repeated_line_is_kept_once_and_a_short_text_is_not_cut():
    out = _scan.cut_text(["Hello there", "Hello there", "  ", "", "Visit us"])
    assert out == {"lines": ["Hello there", "Visit us"], "chars": 19, "cut": False}


def test_tesseract_words_are_kept_at_a_confidence_of_sixty_and_two_characters():
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = ["5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t96.5\tSAMPLE", "5\t1\t1\t1\t1\t2\t0\t0\t1\t1\t91\tPHOTO", "5\t1\t1\t1\t1\t3\t0\t0\t1\t1\t59\tnoise",
            "5\t1\t1\t1\t1\t4\t0\t0\t1\t1\t90\t|", "5\t1\t2\t1\t1\t1\t0\t0\t1\t1\t88\tCall", "5\t1\t2\t1\t1\t2\t0\t0\t1\t1\t88\t555", "4\t1\t2\t1\t1\t0\t0\t0\t1\t1\t-1\t", "5\t1\t3\t1\t1\t1\t0\t0\t1\t1\tx\tbad"]
    assert _scan.parse_tsv("\n".join([header] + rows)) == ["SAMPLE PHOTO", "Call 555"]


# ---------------------------------------------------------------- QR payloads

def test_a_link_gives_its_host_in_lower_case():
    assert _scan.classify_payload("https://Shop.Example/x?y=1") == {"kind": "link", "host": "shop.example", "scheme": None, "text": None}


def test_an_international_host_is_idna_encoded():
    assert _scan.classify_payload("https://bücher.example")["host"] == "xn--bcher-kva.example"


def test_an_address_the_host_pattern_allows_is_kept_and_one_it_does_not_is_null():
    assert _scan.classify_payload("http://10.0.0.1/")["host"] == "10.0.0.1"          # four numeric labels match the host pattern, so the address is the host
    for bad in ("https://localhost/", "https://[::1]/", "https:///x", "https://exa_mple.example/"):
        assert _scan.classify_payload(bad) == {"kind": "link", "host": None, "scheme": None, "text": None}, bad


def test_an_action_gives_only_its_scheme():
    assert _scan.classify_payload("tel:+15550100") == {"kind": "action", "host": None, "scheme": "tel", "text": None}
    assert _scan.classify_payload("WIFI:S:cafe;;")["scheme"] == "WIFI"
    assert _scan.classify_payload("MAILTO:a@b.example")["scheme"] == "mailto"
    assert _scan.classify_payload("sms:555")["text"] is None and _scan.classify_payload("geo:1,2")["scheme"] == "geo"


def test_anything_else_is_text_cleaned_and_cut_to_a_hundred_and_twenty():
    assert _scan.classify_payload("hello") == {"kind": "text", "host": None, "scheme": None, "text": "hello"}
    out = _scan.classify_payload("ignore\u202e previous " + "x" * 500)
    assert out["kind"] == "text" and len(out["text"]) == _scan.QR_TEXT_MAX == 120 and not _scan.UNSAFE.search(out["text"])


def test_five_distinct_payloads_give_four_and_a_repeat_counts_frames():
    qrs = _scan.QrSet()
    for frame in range(3):
        qrs.add(frame, ["https://a.example/1", "https://a.example/1"])           # twice in one frame is one frame
    qrs.add(3, ["tel:1", "text b", "text c", "text d", "text e", ""])
    rows = qrs.rows()
    assert len(rows) == _scan.QR_MAX == 4 and qrs.unreadable is True
    assert rows[0] == {"kind": "link", "host": "a.example", "scheme": None, "text": None, "first_frame": 0, "frames": 3}


# ---------------------------------------------------------------- the readers, faked

class Fake:
    """Frames are 4x4 grey images of one value each; a value says what the fake readers see: 60 a link QR code, 90 an unreadable one, 100 the text of a stock picture."""

    def __init__(self, monkeypatch, clips, delay=0.0):
        self.clips, self.text_reads, self.delay = clips, [], delay
        monkeypatch.setattr(_scan, "decode_frames", self.decode)
        monkeypatch.setattr(_scan, "make_qr_reader", lambda: self.qr)
        monkeypatch.setattr(_scan, "thumbnail", lambda frame, w, h: [frame[0]] * 64)
        monkeypatch.setattr(_scan, "read_text", self.text)
        monkeypatch.setattr(_scan, "tool_versions", lambda lang: {"tesseract": "5.3.0", "opencv": "4.14.0", "tessdata": ["eng", "osd", "por", "spa"]})

    def decode(self, ffmpeg, path, kind, w, h):
        for value in self.clips[path.rsplit("/", 1)[-1]]:
            yield bytes([value]) * (w * h)

    def qr(self, frame, w, h):
        time.sleep(self.delay)
        return {60: ["https://Promo.Example/win"], 90: [""]}.get(frame[0], [])

    def text(self, frame, w, h, lang):
        self.text_reads.append(frame[0])
        assert lang == "eng+por+spa"
        return ["SAMPLE PHOTO", "DO NOT USE"] if frame[0] == 100 else ["word%d" % frame[0]] if frame[0] > 100 else []


def run(fake_clips, monkeypatch, delay=0.0, **assets):
    fake = Fake(monkeypatch, fake_clips, delay)
    items = ["%s=/job/%s" % (slot, name) for slot, name in assets.items()]
    sizes = ["%s=4x4" % slot for slot in assets]
    return fake, _scan.scan(assets=items, sizes=sizes, lang="eng+por+spa", ffmpeg="ffmpeg")


def test_a_picture_with_text_and_a_clip_with_a_code_are_read_as_the_spec_says(monkeypatch):
    clips = {"asset-%s.png" % HEX_A: [100], "asset-%s.mp4" % HEX_B: [0, 60, 60, 0, 0, 0]}
    fake, out = run(clips, monkeypatch, pic="asset-%s.png" % HEX_A, clip="asset-%s.mp4" % HEX_B)
    assert out["ok"] and out["lang"] == "eng+por+spa" and out["versions"]["tessdata"] == ["eng", "osd", "por", "spa"]
    rows = {a["slot"]: a for a in out["assets"]}
    pic, clip = rows["pic"], rows["clip"]
    assert pic["kind"] == "image" and pic["frames"] == 1 and pic["codes"] == ["text_found"] and pic["text"] == {"lines": ["SAMPLE PHOTO", "DO NOT USE"], "chars": 22, "cut": False}
    assert clip["kind"] == "clip" and clip["frames"] == clip["frames_qr"] == 6 and clip["partial"] is False
    assert clip["qr"] == [{"kind": "link", "host": "promo.example", "scheme": None, "text": None, "first_frame": 1, "frames": 2}]
    assert clip["codes"] == ["qr_link"] and clip["frames_text"] == clip["frames_changed"] == 4          # frame 0, the two changes (1 and 3) and the last frame
    assert sorted(fake.text_reads) == [0, 0, 0, 60, 100]                                                # the picture once, the clip on four frames


def test_a_clean_picture_gives_no_code_and_a_qr_that_cannot_be_read_gives_qr_unreadable(monkeypatch):
    clips = {"asset-%s.png" % HEX_A: [50], "asset-%s.mp4" % HEX_B: [0, 90, 0]}
    _, out = run(clips, monkeypatch, pic="asset-%s.png" % HEX_A, clip="asset-%s.mp4" % HEX_B)
    rows = {a["slot"]: a for a in out["assets"]}
    assert rows["pic"]["codes"] == [] and rows["pic"]["text"] == {"lines": [], "chars": 0, "cut": False} and rows["pic"]["qr"] == []
    assert rows["clip"]["codes"] == ["qr_unreadable"] and rows["clip"]["qr"] == []


def test_every_changed_frame_is_read_up_to_the_cap_and_that_is_not_partial(monkeypatch):
    values = [101 + (i % 2) * 40 for i in range(41)]                        # every frame differs from the last read one
    fake, out = run({"asset-%s.mp4" % HEX_B: values}, monkeypatch, clip="asset-%s.mp4" % HEX_B)
    clip = out["assets"][0]
    assert clip["frames"] == 41 and clip["frames_text"] == 41 and clip["frames_changed"] == 41 and clip["partial"] is False and "scan_partial" not in clip["codes"]
    assert clip["text"]["lines"] == ["word101", "word141"]


def test_a_clip_whose_every_frame_changes_is_sampled_at_the_cap_and_says_so_by_the_counts_alone(monkeypatch):
    values = [101 + (i % 2) * 40 for i in range(250)]
    fake, out = run({"asset-%s.mp4" % HEX_B: values}, monkeypatch, clip="asset-%s.mp4" % HEX_B)
    clip = out["assets"][0]
    assert clip["frames_text"] == len(fake.text_reads) == _scan.OCR_FRAMES_MAX and clip["frames_changed"] == 250 and clip["partial"] is False and "scan_partial" not in clip["codes"]


def test_the_budget_marks_what_is_not_finished_partial(monkeypatch):
    monkeypatch.setattr(_scan, "SCAN_BUDGET_S", 0.25)
    clips = {"asset-%s.mp4" % HEX_B: [0] * 12}
    _, out = run(clips, monkeypatch, delay=0.1, clip="asset-%s.mp4" % HEX_B)
    clip = out["assets"][0]
    assert clip["partial"] is True and "scan_partial" in clip["codes"] and 0 < clip["frames"] < 12 and clip["frames_qr"] == clip["frames"] and clip["frames_text"] == 0


def test_a_file_that_gives_no_frame_is_not_called_clean(monkeypatch):
    with pytest.raises(Refusal) as caught:
        run({"asset-%s.png" % HEX_A: []}, monkeypatch, pic="asset-%s.png" % HEX_A)
    assert caught.value.code == "asset_unreadable"


def test_the_arguments_are_checked(monkeypatch):
    ok = ["a=/job/asset-%s.png" % HEX_A]
    good = _scan.parse_assets(ok, ["a=1080x1920"])
    assert good == [{"slot": "a", "file": "asset-%s.png" % HEX_A, "path": "/job/asset-%s.png" % HEX_A, "kind": "image", "w": 1080, "h": 1920}]
    bad = [(ok, []), (ok, ["a=0x10"]), (ok, ["a=4000x10"]), (ok, ["a=4x4", "a=4x4"]), (ok, ["b=4x4"]), (["A=/job/asset-%s.png" % HEX_A], ["A=4x4"]),
           (["a=/job/photo.png"], ["a=4x4"]), (["a=/job/asset-%s.gif" % HEX_A], ["a=4x4"]), (ok + ok, ["a=4x4"]), ([], []),
           (["s%d=/job/asset-%s.png" % (n, HEX_A) for n in range(7)], ["s%d=4x4" % n for n in range(7)])]
    for assets, sizes in bad:
        with pytest.raises(Refusal):
            _scan.parse_assets(assets, sizes)
    with pytest.raises(Refusal) as caught:
        _scan.scan(assets=ok, sizes=["a=4x4"], lang="eng;rm", ffmpeg="ffmpeg")
    assert caught.value.code == "bad_lang"


def test_a_missing_language_or_tool_is_not_ready():
    with pytest.raises(Refusal) as caught:
        _scan.raise_not_ready("scan:tessdata")
    assert (caught.value.code, caught.value.field) == ("not_ready", "scan:tessdata")


def test_the_decode_command_reads_one_stream_of_one_kind_with_one_thread_and_the_file_protocol():
    png = _scan.decode_argv("ffmpeg", "/job/asset-%s.png" % HEX_A, "image", 1080, 1920)
    mp4 = _scan.decode_argv("ffmpeg", "/job/asset-%s.mp4" % HEX_B, "clip", 1080, 1920)
    for argv in (png, mp4):
        assert argv[argv.index("-threads") + 1] == "1" and "-nostdin" in argv and argv[-1] == "-" and argv[argv.index("-f", argv.index("-vf")) + 1] == "rawvideo"
        assert argv[argv.index("-protocol_whitelist") + 1] == "file" and argv[argv.index("-map") + 1] == "0:v:0" and "-an" in argv and "-sn" in argv
        assert "scale=1080:1920" in argv[argv.index("-vf") + 1] and argv[argv.index("-vf") + 1].endswith("format=gray")
    assert png[png.index("-f") + 1] == "png_pipe" and mp4[mp4.index("-f") + 1] == "mov"


# ---------------------------------------------------------------- the host's reading of the answer

def good_answer():
    return {"ok": True, "lang": "eng+por+spa", "versions": {"tesseract": "5.3.0", "opencv": "4.14.0", "tessdata": ["eng", "osd", "por", "spa"]},
            "assets": [{"slot": "pic", "file": "asset-%s.png" % HEX_A, "kind": "image", "frames": 1, "frames_qr": 1, "frames_text": 1, "frames_changed": 1, "partial": False,
                        "codes": ["qr_link", "text_found"], "text": {"lines": ["SAMPLE PHOTO"], "chars": 12, "cut": False},
                        "qr": [{"kind": "link", "host": "shop.example", "scheme": None, "text": None, "first_frame": 0, "frames": 1}]},
                       {"slot": "clip", "file": "asset-%s.mp4" % HEX_B, "kind": "clip", "frames": 601, "frames_qr": 601, "frames_text": 30, "frames_changed": 41, "partial": True,
                        "codes": ["scan_partial"], "text": {"lines": [], "chars": 0, "cut": False}, "qr": []}]}


FILES = {"pic": "asset-%s.png" % HEX_A, "clip": "asset-%s.mp4" % HEX_B}
KINDS = {"pic": "image", "clip": "clip"}


def refused(answer, files=FILES, kinds=KINDS):
    with pytest.raises(Refusal) as caught:
        _host.check_scan_answer(D.sanitise(answer, D.RESULT_SCHEMAS["scan"], "scan"), files, kinds)
    assert caught.value.code == "container_result_invalid" and caught.value.field.startswith("scan")


def test_the_closed_schema_takes_a_good_answer_and_the_check_returns_it_sorted_by_slot():
    clean = D.sanitise(good_answer(), D.RESULT_SCHEMAS["scan"], "scan")
    rows = _host.check_scan_answer(clean, FILES, KINDS)
    assert [a["slot"] for a in rows] == ["clip", "pic"] and clean["assets"][0]["qr"][0]["host"] == "shop.example"


def test_a_planted_answer_that_is_wrong_is_refused():
    def planted(edit):
        answer = good_answer()
        edit(answer)
        refused(answer)
    planted(lambda a: a["assets"].append(dict(a["assets"][0], slot="extra")))                       # a slot nobody asked for
    planted(lambda a: a["assets"].pop())                                                           # a slot missing
    planted(lambda a: a["assets"][0].update(file="asset-%s.png" % HEX_B))                          # not the staged name
    planted(lambda a: a["assets"][0].update(kind="clip"))                                          # the kind is the file's own
    planted(lambda a: a["assets"][1].update(frames=602, frames_qr=602))                            # more frames than 10 s at 60 fps and one
    planted(lambda a: a["assets"][0].update(frames=2, frames_qr=2))                                # a picture has one frame
    planted(lambda a: a["assets"][0].update(frames_qr=0))                                          # QR codes are read on every frame unless partial
    planted(lambda a: a["assets"][0].update(frames_text=2))
    planted(lambda a: a["assets"][0].update(codes=["qr_link", "run_this"]))                        # a code outside SCAN_CODES
    planted(lambda a: a["assets"][0].update(codes=["text_found", "qr_link"]))                      # not sorted
    planted(lambda a: a["assets"][0]["text"].update(lines=["x" * 161]))                            # a line over 160
    planted(lambda a: a["assets"][0]["text"].update(lines=["line %d" % n for n in range(9)]))
    planted(lambda a: a["assets"][0]["qr"][0].update(host="not a host"))
    planted(lambda a: a["assets"][0]["qr"][0].update(scheme="tel"))
    planted(lambda a: a["assets"][0]["qr"][0].update(kind="action", host=None, scheme="ssh"))
    planted(lambda a: a["assets"][0]["qr"][0].update(kind="text", host=None, text=None))
    planted(lambda a: a["assets"][0]["qr"][0].update(first_frame=1))
    planted(lambda a: a.update(lang="eng"))
    planted(lambda a: a["assets"][0].pop("text"))
    planted(lambda a: a["assets"][0].update(text="a string"))
    over = good_answer()
    over["assets"][0]["text"] = {"lines": ["a" * 201], "chars": 201, "cut": True}                     # over the schema's own 200
    refused(over)


def test_a_string_with_a_bidi_override_never_passes_the_schema():
    answer = good_answer()
    answer["assets"][0]["text"]["lines"] = ["a\u202eb"]
    with pytest.raises(Refusal):
        D.sanitise(answer, D.RESULT_SCHEMAS["scan"], "scan")


# ---------------------------------------------------------------- the host verb, with the fake docker

@pytest.fixture
def world(tmp_path):
    (tmp_path / "home").mkdir()
    return DK.World(tmp_path)


def files_in(tmp_path):
    pic, clip = tmp_path / ("asset-%s.png" % HEX_A), tmp_path / ("asset-%s.mp4" % HEX_B)
    pic.write_bytes(PNG_HEAD)
    clip.write_bytes(MP4_HEAD)
    return pic, clip


def flags(pic, clip):
    return ["--asset", "pic=%s" % pic, "--asset", "clip=%s" % clip, "--size", "pic=1080x1920", "--size", "clip=1080x1920"]


def answer_as_file(world, answer):
    world.cfg.update(run="files", files={"result.json": {"kind": "text", "text": json.dumps(answer)}})
    world.save()


def test_the_host_runs_one_container_with_the_files_staged_and_prints_only_the_rebuilt_answer(world, tmp_path):
    pic, clip = files_in(tmp_path)
    answer_as_file(world, dict(good_answer(), assets=[good_answer()["assets"][0], dict(good_answer()["assets"][1], frames=300, frames_qr=300, partial=False, codes=[])]))
    world.cfg["files"]["result.json"]["text"] = json.dumps(dict(json.loads(world.cfg["files"]["result.json"]["text"]), extra="ignored"))
    world.save()
    rc, out, err = world.host("scan", *flags(pic, clip))
    assert rc == 0, err
    assert out["ok"] and out["lang"] == "eng+por+spa" and [a["slot"] for a in out["assets"]] == ["clip", "pic"] and "extra" not in out and out["image"]["tag"]
    runs = world.runs()
    assert len(runs) == 1
    argv = runs[0]["argv"]
    inner = argv[argv.index("scan") - 0:] if "scan" in argv else []
    assert inner[:3] == ["scan", "--lang", "eng+por+spa"] and "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "/job/asset-%s.png" % HEX_A in " ".join(inner) and "pic=1080x1920" in inner and "clip=1080x1920" in inner
    assert not any(name.endswith("recording") for name in argv)


def test_the_host_refuses_what_the_container_answers_wrongly_and_a_crash_is_a_closed_refusal(world, tmp_path):
    pic, clip = files_in(tmp_path)
    wrong = good_answer()
    wrong["assets"][0]["file"] = "asset-%s.png" % HEX_B
    answer_as_file(world, wrong)
    rc, out, err = world.host("scan", *flags(pic, clip))
    assert rc == 1 and err.startswith("refused: container_result_invalid scan")
    world.cfg.update(run="files", files={}, rc=137)
    world.save()
    rc, out, err = world.host("scan", *flags(pic, clip))
    assert rc == 1 and err.startswith(("refused: container_killed", "refused: container_failed"))


def test_the_host_takes_only_asset_files_of_the_set_with_a_size_each(world, tmp_path):
    pic, clip = files_in(tmp_path)
    other = tmp_path / "photo.png"
    other.write_bytes(PNG_HEAD)
    as_png = tmp_path / ("asset-%s.png" % ("c" * 12))
    as_png.write_bytes(MP4_HEAD)                                           # named a picture, a clip by its bytes
    cases = [(["--asset", "pic=%s" % other, "--size", "pic=4x4"], 1), (["--asset", "pic=%s" % as_png, "--size", "pic=4x4"], 1),
             (["--asset", "pic=%s" % pic], 2), (["--size", "pic=4x4"], 2), (["--asset", "pic=%s" % pic, "--size", "pic=9999x4"], 1),
             (["--asset", "Pic=%s" % pic, "--size", "Pic=4x4"], 1), ([], 2)]
    for extra, code in cases:
        rc, out, err = world.host("scan", *extra)
        assert rc == code, (extra, err)
    many = []
    for n in range(7):
        many += ["--asset", "s%d=%s" % (n, pic), "--size", "s%d=4x4" % n]
    rc, out, err = world.host("scan", *many)
    assert rc == 1 and "too_many_assets" in err
    assert world.runs() == []                                              # nothing reached a container


def test_a_file_of_a_reference_store_is_refused_before_a_container(world, tmp_path):
    root = tmp_path / "references"
    (root / "0123456789abcdef").mkdir(parents=True)
    (root / ".openhora-reference").write_text("x")
    kept = root / "0123456789abcdef" / ("asset-%s.png" % HEX_A)
    kept.write_bytes(PNG_HEAD)
    rc, out, err = world.host("scan", "--asset", "pic=%s" % kept, "--size", "pic=4x4")
    assert rc == 1 and err.startswith("refused: reference_refused") and world.runs() == []


def test_the_verb_is_a_common_one_and_the_helps_list_it():
    assert "scan" in _host.COMMON_HANDLERS and "scan" in _host.COMMON_VERBS
    import ffmpeg
    assert "scan" in ffmpeg.VERBS and "scan" in ffmpeg.parser().format_help()
    import _inner
    assert "scan" in _inner.VERBS and "scan" in _inner.parser().format_help()


# ---------------------------------------------------------------- the real decoder, with the host's ffmpeg (no Tesseract, no OpenCV, no container)

needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)


def tiny_clip(tmp_path, frames=5):
    import subprocess
    path = tmp_path / ("asset-%s.mp4" % HEX_B)
    done = subprocess.run([K.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=16x8:r=10:d=%g" % (frames / 10.0), "-pix_fmt", "yuv420p",
                           "-c:v", "libx264", str(path)], capture_output=True, timeout=60)
    if done.returncode != 0:
        pytest.skip("this ffmpeg has no libx264")
    return path


@needs_ffmpeg
def test_the_decoder_gives_grey_frames_of_the_size_asked_for_a_picture_and_a_clip(tmp_path):
    import struct
    import zlib

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    row = b"\x00" + bytes([200, 200, 200]) * 8
    png = tmp_path / ("asset-%s.png" % HEX_A)
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 4, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(row * 4)) + chunk(b"IEND", b""))
    frames = list(_scan.decode_frames(K.FFMPEG, str(png), "image", 8, 4))
    assert len(frames) == 1 and len(frames[0]) == 32 and set(frames[0]) <= set(range(190, 211))
    scaled = list(_scan.decode_frames(K.FFMPEG, str(png), "image", 16, 8))                     # a size that is not the file's is scaled to, never misread
    assert len(scaled) == 1 and len(scaled[0]) == 128
    clip = tiny_clip(tmp_path)
    got = list(_scan.decode_frames(K.FFMPEG, str(clip), "clip", 16, 8))
    assert len(got) == 5 and all(len(f) == 128 and set(f) <= set(range(120, 140)) for f in got)


@needs_ffmpeg
def test_a_file_the_decoder_cannot_read_is_a_closed_refusal_not_a_clean_picture(tmp_path):
    bad = tmp_path / ("asset-%s.png" % HEX_A)
    bad.write_bytes(b"not a picture at all")
    with pytest.raises(Refusal) as caught:
        list(_scan.decode_frames(K.FFMPEG, str(bad), "image", 8, 4))
    assert caught.value.code == "tool_failed"


@needs_ffmpeg
def test_the_real_decoder_feeds_the_selection_and_the_readers_a_still_clip_reads_two_frames(tmp_path, monkeypatch):
    clip = tiny_clip(tmp_path, frames=20)
    fake = Fake(monkeypatch, {})
    monkeypatch.setattr(_scan, "decode_frames", _REAL_DECODE)
    monkeypatch.setattr(_scan, "thumbnail", lambda frame, w, h: [sum(frame) // len(frame)] * 4)
    out = _scan.scan(assets=["c=%s" % clip], sizes=["c=16x8"], lang="eng+por+spa", ffmpeg=K.FFMPEG)
    row = out["assets"][0]
    assert row["frames"] == row["frames_qr"] == 20 and row["frames_text"] == 2 and row["partial"] is False and fake.text_reads == [128, 128]


_REAL_DECODE = _scan.decode_frames


def box_clip(tmp_path, background, frames=200):
    """A 1080x1920 clip with a caption-like box (a dark box and twenty white bars) on frames 120 to 131, made by the host's ffmpeg (no drawtext needed)."""
    import subprocess
    path = tmp_path / "caption.mp4"
    en = "enable='between(n,120,131)'"
    bars = ",".join("drawbox=x=%d:y=925:w=14:h=50:color=white:t=fill:%s" % (150 + k * 42, en) for k in range(20))
    vf = "drawbox=x=90:y=900:w=900:h=100:color=0x203040:t=fill:%s,%s,format=yuv420p" % (en, bars)
    done = subprocess.run([K.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", background, "-vf", vf, "-c:v", "libx264", "-crf", "16", "-frames:v", str(frames), str(path)],
                          capture_output=True, timeout=120)
    if done.returncode != 0:
        pytest.skip("this ffmpeg cannot make the clip")
    return path


def thumbs_of(path):
    import subprocess
    raw = subprocess.run([K.FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf", "scale=64:36:flags=area,format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, timeout=120).stdout
    return [list(raw[i:i + 2304]) for i in range(0, len(raw) - 2303, 2304)]


@needs_ffmpeg
def test_a_real_caption_on_a_still_clip_moves_the_mean_by_about_one_and_is_read(tmp_path):
    thumbs = thumbs_of(box_clip(tmp_path, "color=c=0x335577:s=1080x1920:r=30:d=7"))
    assert len(thumbs) == 200 and 1.0 < mean_diff(thumbs[120], thumbs[119]) < 1.6            # the live figure (1.26 to 1.6): a threshold of 6 on this never fires
    chosen, _ = _scan.select_text_frames(thumbs)
    assert 120 in chosen and not any(121 <= c <= 131 for c in chosen)


@needs_ffmpeg
def test_a_real_caption_on_a_moving_clip_is_read(tmp_path):
    thumbs = thumbs_of(box_clip(tmp_path, "gradients=s=1080x1920:r=30:d=7:speed=0.05"))
    chosen, qualified = _scan.select_text_frames(thumbs)
    assert any(120 <= c <= 131 for c in chosen) and len(chosen) <= _scan.OCR_FRAMES_MAX and qualified >= 1
