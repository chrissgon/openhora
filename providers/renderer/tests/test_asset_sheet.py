"""The `asset-sheet` verb (`_asset_sheet.py`, package V9b-2): what it accepts, what it refuses and what it writes. Every picture is made here: a flat-colour
PNG built with `zlib` (never a real picture), a JPEG and a clip made by the host's ffmpeg (these tests are skipped without it). No docker, no browser, no
network. The host side (`_host.verb_asset_sheet`) is run against the fake docker of `docker_kit.py`. Names are fictional.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

import renderer_kit as K
import docker_kit as DK
import _asset_sheet as A
import _assets
import _docker as D
import _host
from _text import Refusal
from _vocab import load_data

needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
DATA = load_data()
BACKGROUND = tuple(int(DATA["theme"]["colors"]["bg"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def png_bytes(w: int, h: int, rgb=(200, 60, 40), extra=(), alpha=False) -> bytes:
    """A flat-colour PNG (colour type 2, or 6 with `alpha`), built with zlib. `extra` is a list of (chunk kind, body) put before the image data."""
    pixel = bytes(rgb) + (b"\xff" if alpha else b"")
    row = b"\x00" + pixel * w
    head = struct.pack(">IIBBBBB", w, h, 8, 6 if alpha else 2, 0, 0, 0)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
    for kind, body in extra:
        out += chunk(kind, body)
    return out + chunk(b"IDAT", zlib.compress(row * h, 9)) + chunk(b"IEND", b"")


def write(tmp: Path, name: str, raw: bytes) -> str:
    path = tmp / name
    path.write_bytes(raw)
    return str(path)


def ffmpeg(*args):
    subprocess.run([K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True, timeout=300)


def jpeg_of(tmp: Path, name: str, w: int, h: int) -> str:
    src = write(tmp, "src-" + name + ".png", png_bytes(w, h, (30, 120, 200)))
    out = str(tmp / name)
    ffmpeg("-i", src, "-c:v", "mjpeg", "-q:v", "3", out)
    return out


def chunks_of(raw: bytes) -> list:
    pos, out = 8, []
    while pos < len(raw):
        length, kind = struct.unpack(">I4s", raw[pos:pos + 8])
        out.append(kind.decode("ascii"))
        pos += 12 + length
    return out


def run(tmp: Path, items: dict, mode="full", out="out"):
    return A.asset_sheet(items=items, mode=mode, out_dir=str(tmp / out), ffmpeg=K.FFMPEG, data=DATA)


def code_of(call, *args, **kwargs) -> tuple:
    with pytest.raises(Refusal) as caught:
        call(*args, **kwargs)
    return caught.value.code, caught.value.field


def pixels_of(path: str) -> tuple:
    """(width, height, raw rgb24 bytes) of a PNG decoded by ffmpeg."""
    w, h = _assets.image_facts(Path(path).read_bytes())[1:]
    raw = subprocess.run([K.FFMPEG, "-hide_banner", "-loglevel", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True, timeout=120).stdout
    return w, h, raw


def pixel(raw: bytes, w: int, x: int, y: int) -> tuple:
    i = (y * w + x) * 3
    return tuple(raw[i:i + 3])


# ---------------------------------------------------------------- what it accepts

@needs_ffmpeg
def test_a_png_and_a_jpeg_are_accepted_and_come_out_as_pngs_of_the_frames_long_side(tmp_path):
    png = write(tmp_path, "a.png", png_bytes(1080, 1920))
    jpg = jpeg_of(tmp_path, "b.jpg", 1920, 1080)
    result = run(tmp_path, {"slot-1:1": png, "slot-2:1": jpg})
    assert result["ok"] and result["rows"] == ["slot-1", "slot-2"] and result["sheet"] == "sheet.png"
    by_row = {a["row"]: a for a in result["assets"]}
    assert (by_row["slot-1"]["width"], by_row["slot-1"]["height"]) == (1080, 1920)
    assert (by_row["slot-2"]["width"], by_row["slot-2"]["height"]) == (1920, 1080)
    for a in result["assets"]:
        file = tmp_path / "out" / a["file"]
        raw = file.read_bytes()
        assert a["file"] == "asset-%s.png" % a["sha256"][:12] and hashlib.sha256(raw).hexdigest() == a["sha256"]
        assert oct(file.stat().st_mode & 0o777) == "0o400"
        assert _assets.image_facts(raw) == ("png", a["width"], a["height"])
    assert by_row["slot-1"]["source_sha256"] == hashlib.sha256(Path(png).read_bytes()).hexdigest()
    assert by_row["slot-2"]["source_sha256"] == hashlib.sha256(Path(jpg).read_bytes()).hexdigest()
    assert hashlib.sha256((tmp_path / "out" / "sheet.png").read_bytes()).hexdigest() == result["sheet_sha256"]


@needs_ffmpeg
def test_a_larger_picture_is_scaled_down_to_the_long_side_and_keeps_its_aspect(tmp_path):
    result = run(tmp_path, {"slot-1:1": write(tmp_path, "big.png", png_bytes(3000, 2000))})
    a = result["assets"][0]
    assert (a["width"], a["height"]) == (1920, 1280)


@needs_ffmpeg
def test_a_picture_is_never_enlarged_and_is_refused_only_when_its_layout_would_enlarge_it_past_one_and_a_half_times(tmp_path):
    """The supervisor's correction after live leg K3 (an Openverse medium rendition, 1024x683, was refused by the older rule): V9b-2 read the spec as "the long side
    becomes 1920, at most 1.5 times"; the rule now is the layout's: never enlarge, refuse `asset_too_small` by the size the page would draw."""
    ok = run(tmp_path, {"slot-1:1": write(tmp_path, "medium.png", png_bytes(1024, 683)), "slot-2:1": write(tmp_path, "tall.png", png_bytes(1080, 1920))})
    assert [(a["width"], a["height"]) for a in ok["assets"]] == [(1024, 683), (1080, 1920)]
    for name, size, row in (("tiny", (600, 337), "slot-1:1"), ("narrow", (800, 1200), "slot-1:1")):
        assert code_of(run, tmp_path, {row: write(tmp_path, name + ".png", png_bytes(*size))}, out="o-" + name) == ("asset_too_small", row), name


def test_the_target_size_follows_the_display_need_and_the_scale_rule():
    """d = the enlargement the layout asks of the source; refused when d > 1.5; scale s = min(1, max(1920 / long side, d)); the long side at most 3840."""
    keep = {(1024, 683): (1024, 683), (1080, 1920): (1080, 1920), (800, 2400): (800, 2400), (1080, 2400): (1080, 2400), (1280, 720): (1280, 720),
            (634, 400): (634, 400), (864, 1280): (864, 1280), (4000, 3000): (1920, 1440), (1080, 5000): (829, 3840), (3000, 2000): (1920, 1280)}
    for source, want in keep.items():
        assert A.target_size(*source, "f") == want, source
    for source in ((600, 337), (800, 1200), (632, 400), (864, 1080)):
        assert code_of(A.target_size, *source, "f") == ("asset_too_small", "f"), source
    assert A.display_need(1024, 683) < 1 and A.display_need(800, 1200) > 1.5 and A.display_need(1080, 1920) == 1 and A.display_need(4000, 3000) < 1
    assert A.MAX_OUT_SIDE == 3840


def test_the_size_rule_reads_the_pages_numbers():
    page = (K.BLOCKS / "oh" / "cutaway" / "renderat.html").read_text(encoding="utf-8")
    assert "SAFE = %d, MAX_FG_H = %d" % (A.SAFE, A.MAX_FG_H) in page
    assert (A.FRAME_W, A.FRAME_H, A.LONG_SIDE) == (DATA["frame"]["width"], DATA["frame"]["height"], 1920) and A.MAX_UPSCALE == 1.5 == A.MAX_UPSCALE_RATIO[0] / A.MAX_UPSCALE_RATIO[1]
    assert A.GLASS_RATIO_MAX[0] / A.GLASS_RATIO_MAX[1] == DATA["presets"]["cutaway"]["looks"]["glass_ratio_max"]


# ---------------------------------------------------------------- what it refuses

@needs_ffmpeg
def test_an_animated_png_a_gif_a_webp_and_a_file_of_no_known_kind_are_asset_type(tmp_path):
    animated = png_bytes(1280, 720, extra=[(b"acTL", struct.pack(">II", 2, 0))])
    bad = {"animated": animated, "gif": b"GIF89a" + b"\x00" * 40, "webp": b"RIFF\x20\x00\x00\x00WEBPVP8 " + b"\x00" * 40, "text": b"not a picture at all"}      # a clip is accepted since V9b-5a
    for name, raw in bad.items():
        assert code_of(run, tmp_path, {"slot-1:1": write(tmp_path, name, raw)}, out="o-" + name) == ("asset_type", "slot-1:1"), name


@needs_ffmpeg
def test_a_truncated_png_and_a_truncated_jpeg_are_asset_corrupt(tmp_path):
    full = png_bytes(1280, 720)
    assert code_of(run, tmp_path, {"slot-1:1": write(tmp_path, "cut.png", full[:len(full) // 2])}, out="o1") == ("asset_corrupt", "slot-1:1")
    assert code_of(run, tmp_path, {"slot-1:1": write(tmp_path, "nofooter.png", full[:-12])}, out="o2") == ("asset_corrupt", "slot-1:1")
    damaged = bytearray(full)
    damaged[40] ^= 0xFF                                        # a byte of the image data: its CRC no longer matches
    assert code_of(run, tmp_path, {"slot-1:1": write(tmp_path, "crc.png", bytes(damaged))}, out="o3") == ("asset_corrupt", "slot-1:1")
    jpg = Path(jpeg_of(tmp_path, "whole.jpg", 1280, 720)).read_bytes()
    assert code_of(run, tmp_path, {"slot-1:1": write(tmp_path, "cut.jpg", jpg[:len(jpg) // 2])}, out="o4") == ("asset_corrupt", "slot-1:1")


def test_thirty_seven_inputs_are_refused_and_thirty_six_are_not_too_many(tmp_path):
    png = write(tmp_path, "a.png", png_bytes(8, 8))
    many = {"s%d:%d" % (r, c): png for r in range(7) for c in range(1, 7)}
    assert len(many) == 42
    assert code_of(A.asset_sheet, items=dict(list(many.items())[:37]), mode="preview", out_dir=str(tmp_path / "o"), ffmpeg="/nowhere", data=DATA) \
        == ("too_many_assets", "asset")
    assert A.MAX_TILES == 36 == _host.ASSET_SHEET_MAX_TILES


def test_a_bad_key_a_bad_mode_and_no_input_are_closed_refusals(tmp_path):
    png = write(tmp_path, "a.png", png_bytes(8, 8))
    for key in ("a", "a:", "a:0", "a:7", "a:10", "A:1", ":1", "a:x", "a b:1"):
        assert code_of(A.asset_sheet, items={key: png}, mode="preview", out_dir=str(tmp_path / "o"), ffmpeg="/nowhere", data=DATA)[0] == "bad_slot", key
    assert code_of(A.asset_sheet, items={"a:1": png}, mode="other", out_dir=str(tmp_path / "o"), ffmpeg="/nowhere", data=DATA)[0] == "bad_mode"
    assert code_of(A.asset_sheet, items={}, mode="full", out_dir=str(tmp_path / "o"), ffmpeg="/nowhere", data=DATA) == ("no_assets", "asset")


def test_a_missing_file_a_link_and_a_picture_over_the_bounds_are_refused(tmp_path):
    png = write(tmp_path, "a.png", png_bytes(8, 8))
    link = tmp_path / "link.png"
    link.symlink_to(png)
    for path in (str(tmp_path / "nowhere.png"), str(link)):
        assert code_of(A.asset_sheet, items={"a:1": path}, mode="preview", out_dir=str(tmp_path / "o"), ffmpeg="/nowhere", data=DATA) == ("asset_unreadable", "a:1")
    small = dict(DATA, limits=dict(DATA["limits"], asset_max_side=7))
    assert code_of(A.asset_sheet, items={"a:1": png}, mode="preview", out_dir=str(tmp_path / "o"), ffmpeg="/nowhere", data=small) == ("asset_dimensions", "a:1")


# ---------------------------------------------------------------- what it writes

@needs_ffmpeg
def test_no_text_chunk_is_in_the_output_whatever_the_input_carried(tmp_path):
    planted = png_bytes(1280, 720, extra=[(b"tEXt", b"Comment\x00a note that must not travel"), (b"iTXt", b"Title\x00\x00\x00\x00\x00a title"),
                                          (b"tIME", struct.pack(">HBBBBB", 2026, 11, 21, 10, 0, 0))])
    assert {"tEXt", "iTXt", "tIME"} <= set(chunks_of(planted))
    jpg = Path(jpeg_of(tmp_path, "m.jpg", 1280, 720)).read_bytes()
    commented = jpg[:2] + b"\xff\xfe" + struct.pack(">H", 2 + 20) + b"a comment to remove!" + jpg[2:]       # a COM segment right after the SOI marker
    result = run(tmp_path, {"slot-1:1": write(tmp_path, "m.png", planted), "slot-2:1": write(tmp_path, "c.jpg", commented)})
    for a in result["assets"]:
        raw = (tmp_path / "out" / a["file"]).read_bytes()
        assert set(chunks_of(raw)) <= {"IHDR", "pHYs", "IDAT", "IEND"}, chunks_of(raw)      # the encoder's own pixel-size chunk, no text
        assert b"must not travel" not in raw and b"a comment to remove" not in raw
    sheet = (tmp_path / "out" / "sheet.png").read_bytes()
    assert not {"tEXt", "iTXt", "zTXt", "eXIf", "tIME"} & set(chunks_of(sheet))


@needs_ffmpeg
def test_the_same_bytes_come_out_twice_and_the_same_picture_twice_is_one_file(tmp_path):
    png = write(tmp_path, "a.png", png_bytes(1280, 720, (10, 200, 90)))
    first = run(tmp_path, {"slot-1:1": png, "slot-1:2": png}, out="one")
    second = run(tmp_path, {"slot-1:1": png, "slot-1:2": png}, out="two")
    assert first == second
    assert first["assets"][0]["file"] == first["assets"][1]["file"]
    assert sorted(p.name for p in (tmp_path / "one").iterdir()) == sorted(["sheet.png", first["assets"][0]["file"]])
    assert (tmp_path / "one" / "sheet.png").read_bytes() == (tmp_path / "two" / "sheet.png").read_bytes()


@needs_ffmpeg
def test_an_alpha_channel_is_kept_and_a_plain_picture_has_none(tmp_path):
    result = run(tmp_path, {"slot-1:1": write(tmp_path, "alpha.png", png_bytes(1280, 720, alpha=True)), "slot-2:1": write(tmp_path, "plain.png", png_bytes(1280, 720))})
    kinds = {a["row"]: (tmp_path / "out" / a["file"]).read_bytes()[25] for a in result["assets"]}
    assert kinds == {"slot-1": 6, "slot-2": 2}


@needs_ffmpeg
def test_preview_mode_writes_only_the_sheet_and_tiles_the_pictures(tmp_path):
    result = run(tmp_path, {"slot-1:1": write(tmp_path, "a.png", png_bytes(60, 100, (250, 10, 10))), "slot-1:2": write(tmp_path, "b.png", png_bytes(100, 60, (10, 10, 250)))},
                 mode="preview")
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["sheet.png"]
    assert [a["file"] for a in result["assets"]] == [None, None]
    cw, ch = A.cell_size()
    w, h, raw = pixels_of(str(tmp_path / "out" / "sheet.png"))
    assert (w, h) == (2 * cw, ch)
    assert pixel(raw, w, cw // 2, ch // 2)[0] > 200 and pixel(raw, w, cw + cw // 2, ch // 2)[2] > 200


@needs_ffmpeg
def test_a_tile_with_no_preview_is_the_themes_background(tmp_path):
    result = run(tmp_path, {"slot-1:1": write(tmp_path, "a.png", png_bytes(80, 80, (250, 10, 10))), "slot-1:3": write(tmp_path, "c.png", png_bytes(80, 80, (10, 250, 10))),
                            "slot-2:2": write(tmp_path, "d.png", png_bytes(80, 80, (10, 10, 250)))}, mode="preview")
    assert result["rows"] == ["slot-1", "slot-2"]
    cw, ch = A.cell_size()
    w, h, raw = pixels_of(str(tmp_path / "out" / "sheet.png"))
    assert (w, h) == (3 * cw, 2 * ch)
    centre = lambda col, row: pixel(raw, w, col * cw + cw // 2, row * ch + ch // 2)      # noqa: E731
    assert centre(1, 0) == BACKGROUND and centre(0, 1) == BACKGROUND and centre(2, 1) == BACKGROUND      # the tiles nobody gave a picture for
    assert centre(0, 0)[0] > 200 and centre(2, 0)[1] > 200 and centre(1, 1)[2] > 200


@needs_ffmpeg
def test_a_sheet_of_one_picture_and_the_widest_sheet_are_written(tmp_path):
    one = run(tmp_path, {"slot-1:1": write(tmp_path, "a.png", png_bytes(50, 50))}, mode="preview", out="one")
    assert one["rows"] == ["slot-1"]
    cw, ch = A.cell_size()
    assert pixels_of(str(tmp_path / "one" / "sheet.png"))[:2] == (cw, ch)
    wide = run(tmp_path, {"slot-1:6": write(tmp_path, "b.png", png_bytes(50, 50))}, mode="preview", out="wide")
    assert wide["rows"] == ["slot-1"] and pixels_of(str(tmp_path / "wide" / "sheet.png"))[:2] == (6 * cw, ch)


def test_two_pictures_for_one_place_are_asset_duplicate(tmp_path):
    png = write(tmp_path, "a.png", png_bytes(8, 8))
    assert code_of(A.asset_sheet, items={"a:1": png, "a:01": png}, mode="preview", out_dir=str(tmp_path / "o"), ffmpeg="/nowhere", data=DATA)[0] == "bad_slot"


def test_the_png_checks_walk_the_chunks_and_the_jpeg_check_reads_the_end_marker():
    good = png_bytes(4, 4)
    assert A.png_complete(good)
    assert not A.png_complete(good + b"x")                     # nothing after IEND
    assert not A.png_complete(good[:-1])
    assert A.jpeg_complete(b"\xff\xd8\xff\xe0abc\xff\xd9") and A.jpeg_complete(b"\xff\xd8\xff\xd9\x00\x00") and not A.jpeg_complete(b"\xff\xd8\xff\xe0abc")


# ---------------------------------------------------------------- the host side, with the fake docker

def test_the_verb_is_a_common_handler_and_its_flags_are_declared():
    assert "asset-sheet" in _host.COMMON_HANDLERS and "asset-sheet" in _host.COMMON_VERBS
    assert D.RESULT_SCHEMAS["asset-sheet"] is not None


def test_the_answer_is_rebuilt_from_a_closed_schema():
    answer = {"ok": True, "assets": [{"row": "slot-1", "col": 1, "file": "asset-0123456789ab.png", "sha256": "0123456789ab" + "0" * 52, "width": 1080, "height": 1920,
                                      "source_sha256": "f" * 64, "extra": "dropped"}], "sheet": "sheet.png", "sheet_sha256": "a" * 64, "rows": ["slot-1"], "stray": 1}
    clean = D.sanitise(answer, D.RESULT_SCHEMAS["asset-sheet"], "asset-sheet")
    assert set(clean) == {"ok", "assets", "sheet", "sheet_sha256", "rows"} and "extra" not in clean["assets"][0]
    rows = [dict(answer["assets"][0], kind="clip", seconds=2.5, file="asset-0123456789ab.mp4"), dict(answer["assets"][0], kind="image", seconds=0)]
    kept = D.sanitise(dict(answer, assets=rows), D.RESULT_SCHEMAS["asset-sheet"], "asset-sheet")["assets"]
    assert [(r["kind"], r["seconds"]) for r in kept] == [("clip", 2.5), ("image", 0)]          # V9b-5a: the rows keep kind and seconds
    too_many = dict(answer, assets=answer["assets"] * 37)
    with pytest.raises(Refusal):
        D.sanitise(too_many, D.RESULT_SCHEMAS["asset-sheet"], "asset-sheet")


def test_the_flags_of_the_verb_parse_on_the_host_and_in_the_image():
    import argparse
    import _inner
    host = argparse.ArgumentParser()
    _host.add_common_parsers(host.add_subparsers(dest="verb"))
    args = host.parse_args(["asset-sheet", "--asset", "slot-1:1=/x/a.png", "--asset", "slot-1:2=/x/b.png", "--mode", "preview", "--out", "/o"])
    assert args.asset == ["slot-1:1=/x/a.png", "slot-1:2=/x/b.png"] and args.mode == "preview" and args.out == "/o" and args.fps == 30
    inner = _inner.parser().parse_args(["asset-sheet", "--asset", "slot-1:1=/job/assets/slot-1.1", "--mode", "full", "--out", "/out"])
    assert inner.verb == "asset-sheet" and inner.mode == "full" and inner.fps == "30"
    assert host.parse_args(["asset-sheet", "--asset", "slot-1:1=/x/a.mp4", "--mode", "full", "--fps", "24", "--out", "/o"]).fps == 24
    with pytest.raises(SystemExit):
        host.parse_args(["asset-sheet", "--asset", "slot-1:1=/x/a.png", "--mode", "sideways", "--out", "/o"])


def test_the_host_refuses_a_bad_key_too_many_inputs_and_a_bad_mode_before_any_container(tmp_path):
    import argparse
    host = argparse.ArgumentParser()
    _host.add_common_parsers(host.add_subparsers(dest="verb"))
    png = write(tmp_path, "a.png", png_bytes(8, 8))
    for key in ("a", "a:0", "a:7", "A:1"):
        args = host.parse_args(["asset-sheet", "--asset", "%s=%s" % (key, png), "--mode", "preview", "--out", str(tmp_path / "o")])
        assert code_of(_host.verb_asset_sheet, args) == ("bad_slot", key[:32])
    many = ["--asset", "s%d:%d=%s" % (0, 1, png)] * 1
    args = host.parse_args(["asset-sheet", *[x for r in range(7) for c in range(1, 7) for x in ("--asset", "s%d:%d=%s" % (r, c, png))], "--mode", "preview",
                            "--out", str(tmp_path / "o")])
    assert code_of(_host.verb_asset_sheet, args) == ("too_many_assets", "asset")
    assert many


def test_the_asset_file_name_is_the_pictures_own_hash():
    assert _host.ASSET_FILE.fullmatch("asset-0123456789ab.png") and not _host.ASSET_FILE.fullmatch("asset-0123456789a.png")
    assert not _host.ASSET_FILE.fullmatch("../asset-0123456789ab.png") and not _host.ASSET_FILE.fullmatch("asset-0123456789AB.png")
    assert json.dumps(A.ASSET_NAME % ("0" * 12)) == '"asset-000000000000.png"'


@pytest.fixture
def world(tmp_path):
    (tmp_path / "home").mkdir()
    return DK.World(tmp_path)


@needs_ffmpeg
def test_the_host_stores_the_normalised_pictures_content_addressed_and_read_only_and_a_second_call_replays_them(world, tmp_path):
    a = write(tmp_path, "a.png", png_bytes(1280, 720, (20, 40, 200)))
    b = jpeg_of(tmp_path, "b.jpg", 1000, 1500)
    out_dir = tmp_path / "picked"
    before = len(world.runs())
    rc, out, err = world.host("asset-sheet", "--asset", "slot-1:1=" + a, "--asset", "slot-2:1=" + b, "--mode", "full", "--out", out_dir)
    assert rc == 0, err
    assert out["mode"] == "full" and out["rows"] == ["slot-1", "slot-2"] and out["sheet"] == "sheet.png" and out["replayed"] == 0
    assert [(x["row"], x["col"]) for x in out["assets"]] == [("slot-1", 1), ("slot-2", 1)]
    for x in out["assets"]:
        path = Path(x["path"])
        assert path.parent == out_dir and path.name == x["file"] == "asset-%s.png" % x["sha256"][:12]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == x["sha256"] and oct(path.stat().st_mode & 0o777) == "0o400"
        assert _assets.image_facts(path.read_bytes()) == ("png", x["width"], x["height"])
    assert (out["assets"][1]["width"], out["assets"][1]["height"]) == (1000, 1500)                    # never enlarged
    assert hashlib.sha256(Path(out["sheet_path"]).read_bytes()).hexdigest() == out["sheet_sha256"]
    run = world.runs()[before]["argv"]
    assert run[run.index("--network") + 1] == "none"
    assert sorted(p.name for p in out_dir.iterdir()) == sorted(["sheet.png"] + [x["file"] for x in out["assets"]])
    again = world.host("asset-sheet", "--asset", "slot-1:1=" + a, "--asset", "slot-2:1=" + b, "--mode", "full", "--out", out_dir)
    assert again[0] == 0 and again[1]["replayed"] == 2 and [x["sha256"] for x in again[1]["assets"]] == [x["sha256"] for x in out["assets"]]


@needs_ffmpeg
def test_the_host_in_preview_mode_keeps_only_the_sheet_and_a_refusal_inside_comes_out_closed(world, tmp_path):
    a = write(tmp_path, "a.png", png_bytes(120, 80))
    rc, out, err = world.host("asset-sheet", "--asset", "slot-1:2=" + a, "--mode", "preview", "--out", tmp_path / "p")
    assert rc == 0, err
    assert [p.name for p in (tmp_path / "p").iterdir()] == ["sheet.png"] and out["assets"][0]["file"] is None and out["assets"][0]["path"] is None
    gif = write(tmp_path, "g.gif", b"GIF89a" + b"\x00" * 64)
    rc, out, err = world.host("asset-sheet", "--asset", "slot-1:1=" + gif, "--mode", "preview", "--out", tmp_path / "q")
    assert rc == 1 and err.startswith("refused: asset_type slot-1:1") and out["code"] == "asset_type" and not (tmp_path / "q").exists()


# ---------------------------------------------------------------- clips (V9b-5a)

import clip_kit as C
import _media


def probe_json(path) -> dict:
    out = subprocess.run([K.FFPROBE, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, check=True, text=True, timeout=60).stdout
    return json.loads(out)


def run_clips(tmp: Path, items: dict, mode="full", out="out", **more):
    return A.asset_sheet(items=items, mode=mode, out_dir=str(tmp / out), ffmpeg=K.FFMPEG, ffprobe=K.FFPROBE, data=DATA, **more)


def fake_ffprobe(tmp: Path, document: dict) -> str:
    """A stand-in for ffprobe that prints `document`, for the facts a real encoder would not make for a test (a clip of 8000 pixels, an HDR clip)."""
    path = tmp / "ffprobe-fake"
    path.write_text("#!%s\nimport json, sys\nprint(json.dumps(%r))\n" % (sys.executable, document))
    path.chmod(0o755)
    return str(path)


def stream(**more) -> dict:
    return dict({"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p", "r_frame_rate": "30/1", "avg_frame_rate": "30/1"}, **more)


@needs_ffmpeg
def test_a_clip_in_full_mode_is_written_in_the_one_pinned_form(tmp_path):
    clip = C.counter_clip(tmp_path / "a.mp4", 1920, 1080, 60, fps=25)                        # 2.4 s at 25 frames a second
    result = run_clips(tmp_path, {"slot-1:1": clip}, fps=30)
    a, = result["assets"]
    assert a["kind"] == "clip" and a["file"] == "asset-%s.mp4" % a["sha256"][:12] and (a["width"], a["height"]) == (1920, 1080) and 2.3 <= a["seconds"] <= 2.5
    file = tmp_path / "out" / a["file"]
    assert hashlib.sha256(file.read_bytes()).hexdigest() == a["sha256"] and oct(file.stat().st_mode & 0o777) == "0o400"
    assert a["source_sha256"] == hashlib.sha256(Path(clip).read_bytes()).hexdigest()
    info = probe_json(file)
    v, = info["streams"]                                                                     # one stream: no audio, no subtitle, no data
    assert (v["codec_name"], v["profile"], v["pix_fmt"], v["r_frame_rate"], v["avg_frame_rate"]) == ("h264", "High", "yuv420p", "30/1", "30/1")
    assert (v["color_space"], v["color_primaries"], v["color_transfer"], v["color_range"]) == ("bt709", "bt709", "bt709", "tv")
    assert _media.faststart(str(file)) and set(info["format"].get("tags") or {}) <= {"major_brand", "minor_version", "compatible_brands"} and C.frames_of(file) == round(a["seconds"] * 30)
    sheet = tmp_path / "out" / "sheet.png"
    assert hashlib.sha256(sheet.read_bytes()).hexdigest() == result["sheet_sha256"]
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(["sheet.png", a["file"]])


@needs_ffmpeg
def test_the_same_clip_gives_the_same_bytes_twice_and_the_argv_pins_one_thread_everywhere(tmp_path):
    clip = C.counter_clip(tmp_path / "a.mp4", 1280, 720, 40)
    first, second = run_clips(tmp_path, {"slot-1:1": clip}, out="one"), run_clips(tmp_path, {"slot-1:1": clip}, out="two")
    assert first == second and (tmp_path / "one" / "sheet.png").read_bytes() == (tmp_path / "two" / "sheet.png").read_bytes()
    argv = A.clip_normalise_argv("ffmpeg", {"demuxer": "mov", "decoder": "h264", "color_space": "bt709", "width": 1280, "height": 720}, "/in/a.mp4", "/out/a.mp4", (1920, 1080), 30, 1000)
    assert argv[argv.index("-threads") + 1] == "1" and argv[argv.index("-filter_threads") + 1] == "1" and argv[argv.index("-filter_complex_threads") + 1] == "1"
    assert argv[argv.index("libx264") + 1:argv.index("libx264") + 3] == ["-threads", "1"] and argv[argv.index("-x264-params") + 1] == "threads=1:lookahead_threads=1:sliced-threads=0"
    assert argv[argv.index("-sws_flags") + 1] == _media.SWS and "flags=lanczos+accurate_rnd+bitexact" in argv[argv.index("-vf") + 1]
    assert ["-fflags", "+bitexact", "-flags:v", "+bitexact"] == argv[argv.index("-fflags"):argv.index("-fflags") + 4] and "+faststart" in argv


def test_the_clip_argv_forces_the_demuxer_and_the_decoder_reads_the_first_video_stream_only_and_drops_what_else_the_file_holds():
    clip = {"demuxer": "mov", "decoder": "h264", "color_space": "bt709", "width": 1920, "height": 1080}
    argv = A.clip_normalise_argv("ffmpeg", clip, "/in/a.mp4", "/out/a.mp4", (1920, 1080), 24, 5000)
    i = argv.index("-i")
    assert argv[i - 14:i] == ["-f", "mov", "-enable_drefs", "0", "-protocol_whitelist", "file", "-max_pixels", "33177600", "-codec_whitelist", "h264", "-c:v", "h264", "-t", "10"]
    assert argv[i + 1] == "/in/a.mp4"
    assert argv[argv.index("-map") + 1] == "0:v:0" and argv.count("-map") == 1
    for flag in ("-an", "-sn", "-dn"):
        assert flag in argv
    assert argv[argv.index("-map_metadata") + 1] == "-1" and argv[argv.index("-map_chapters") + 1] == "-1"
    assert argv[argv.index("-r") + 1] == "24" and argv[argv.index("-fps_mode") + 1] == "cfr" and argv[argv.index("-fs") + 1] == "5000"
    assert argv[argv.index("-vf") + 1].startswith("fps=24:start_time=0,scale=1920:1080:in_color_matrix=bt709:out_color_matrix=bt709:out_range=tv:")
    web = A.clip_normalise_argv("ffmpeg", dict(clip, demuxer="matroska", decoder="vp9"), "/in/a.webm", "/out/a.mp4", (1920, 1080), 30, 5000)
    assert web[web.index("-i") - 12:web.index("-i") - 2] == ["-f", "matroska", "-protocol_whitelist", "file", "-max_pixels", "33177600", "-codec_whitelist", "vp9", "-c:v", "vp9"]
    assert "-enable_drefs" not in web
    assert "-lavfi" not in argv and all(isinstance(a, str) for a in argv) and not any("filter_complex" == a for a in argv)


@needs_ffmpeg
def test_a_clip_is_told_by_its_first_bytes_never_by_its_name(tmp_path):
    mp4 = C.counter_clip(tmp_path / "real.mp4", 1280, 720, 30)
    webm = C.counter_clip(tmp_path / "real.webm", 1280, 720, 30, codec_args=("-c:v", "libvpx-vp9", "-b:v", "1M"))
    swapped = {"slot-1:1": write(tmp_path, "looks-like.webm", Path(mp4).read_bytes()), "slot-1:2": write(tmp_path, "looks-like.mp4", Path(webm).read_bytes())}
    result = run_clips(tmp_path, swapped)
    assert [a["kind"] for a in result["assets"]] == ["clip", "clip"] and all(a["file"].endswith(".mp4") for a in result["assets"])
    assert _media.clip_container(Path(mp4).read_bytes()[:_media.SNIFF_BYTES]) == "mov" and _media.clip_container(Path(webm).read_bytes()[:_media.SNIFF_BYTES]) == "matroska"
    assert _media.clip_container(png_bytes(8, 8)[:16]) is None and _media.clip_container(b"") is None


@needs_ffmpeg
def test_a_clip_with_audio_two_video_streams_and_a_data_stream_keeps_only_the_first_video_stream(tmp_path):
    blue = "color=c=0x2020F0:s=1280x720:r=30:d=1.5"
    red = "color=c=0xF02020:s=1280x720:r=30:d=1.5"
    many = tmp_path / "many.mov"
    C.ffmpeg("-f", "lavfi", "-i", red, "-f", "lavfi", "-i", blue, "-f", "lavfi", "-i", "sine=f=300:d=1.5", "-map", "0:v", "-map", "1:v", "-map", "2:a", "-pix_fmt", "yuv420p",
             "-c:v", "libx264", "-c:a", "aac", "-timecode", "01:00:00:00", str(many))
    kinds = {s["codec_type"] for s in probe_json(many)["streams"]}
    assert {"video", "audio", "data"} <= kinds and sum(1 for s in probe_json(many)["streams"] if s["codec_type"] == "video") == 2
    a, = run_clips(tmp_path, {"slot-1:1": str(many)})["assets"]
    out = tmp_path / "out" / a["file"]
    assert [s["codec_type"] for s in probe_json(out)["streams"]] == ["video"]
    r, g, b = C.rgb_at(out, 10, 640, 360)
    assert r > 150 and b < 100                                          # the first video stream (red), not the second (blue)


@needs_ffmpeg
def test_av1_is_read_only_when_the_images_ffmpeg_has_a_software_decoder_for_it(tmp_path):
    assert _media.clip_decoder("av1", ("libdav1d", "h264")) == "libdav1d" and _media.clip_decoder("av1", ("libaom-av1",)) == "libaom-av1"
    assert _media.clip_decoder("av1", ("av1", "h264", "hevc")) is None and _media.clip_decoder("av1", ()) is None          # the native decoder needs a hardware accelerator
    every = ("h264", "hevc", "vp8", "vp9")
    assert [_media.clip_decoder(c, every) for c in every + ("mpeg4", "prores")] == ["h264", "hevc", "vp8", "vp9", None, None]
    assert _media.clip_decoder("h264", ("hevc",)) is None and _media.clip_decoder("h264", ()) is None and _media.clip_decoder("h264", None) == "h264"      # a decoder the image lacks
    if "libsvtav1" not in subprocess.run([K.FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout or "libdav1d" not in _media.software_decoders(K.FFMPEG):
        pytest.skip("this ffmpeg has no av1 encoder or no software av1 decoder")
    clip = C.counter_clip(tmp_path / "a.mp4", 1280, 720, 20, codec_args=("-c:v", "libsvtav1"))
    assert probe_json(clip)["streams"][0]["codec_name"] == "av1"
    assert code_of(run_clips, tmp_path, {"slot-1:1": clip}, out="none", decoders=("h264", "hevc", "av1")) == ("asset_type", "slot-1:1")      # the image has no software decoder
    a, = run_clips(tmp_path, {"slot-1:1": clip}, out="some", decoders=("libdav1d",))["assets"]                                            # the image has one
    assert probe_json(tmp_path / "some" / a["file"])["streams"][0]["codec_name"] == "h264"


@needs_ffmpeg
def test_a_clip_of_twelve_seconds_is_cut_to_ten(tmp_path):
    clip = C.flat_clip(tmp_path / "long.mp4", 1280, 720, 12, fps=24)
    a, = run_clips(tmp_path, {"slot-1:1": clip})["assets"]
    assert 9.95 <= a["seconds"] <= 10.1 and C.frames_of(tmp_path / "out" / a["file"]) == 300
    short = C.flat_clip(tmp_path / "short.mp4", 1280, 720, 3)
    assert run_clips(tmp_path, {"slot-1:1": short}, out="s")["assets"][0]["seconds"] == pytest.approx(3.0, abs=0.05)


@needs_ffmpeg
def test_a_clip_follows_the_same_size_rule_with_even_sides(tmp_path):
    ok = C.flat_clip(tmp_path / "ok.mp4", 1280, 720, 1)
    a, = run_clips(tmp_path, {"slot-1:1": ok})["assets"]
    assert (a["width"], a["height"]) == (1280, 720)                                            # kept: never enlarged
    medium = C.flat_clip(tmp_path / "medium.mp4", 1024, 682, 1)
    assert (run_clips(tmp_path, {"slot-1:1": medium}, out="m")["assets"][0]["width"],) == (1024,)
    big = C.flat_clip(tmp_path / "big.mp4", 2560, 1440, 1)
    assert (lambda r: (r["width"], r["height"]))(run_clips(tmp_path, {"slot-1:1": big}, out="b")["assets"][0]) == (1920, 1080)       # scaled down
    small = C.flat_clip(tmp_path / "small.mp4", 600, 338, 1)                                    # glass needs 1.58 times
    assert code_of(run_clips, tmp_path, {"slot-1:1": small}, out="no") == ("asset_too_small", "slot-1:1")
    assert not (tmp_path / "no").exists()
    assert A.clip_size(1024, 683, "f") == (1024, 684) and A.clip_size(1080, 1920, "f") == (1080, 1920)          # the sides are made even
    assert A.clip_size(800, 2400, "f") == (800, 2400) and A.clip_size(1080, 2400, "f") == (1080, 2400) and A.clip_size(4000, 3000, "f") == (1920, 1440)
    assert A.clip_size(1080, 5000, "f") == (830, 3840)                                                              # capped at 3840 tall, then made even
    assert code_of(A.clip_size, 800, 1200, "f") == ("asset_too_small", "f") and code_of(A.clip_size, 600, 337, "f") == ("asset_too_small", "f")


@needs_ffmpeg
def test_the_rows_carry_the_kind_and_the_seconds(tmp_path):
    clip = C.flat_clip(tmp_path / "c.mp4", 1280, 720, 2)
    png = write(tmp_path, "p.png", png_bytes(1280, 720))
    for mode in ("full", "preview"):
        rows = run_clips(tmp_path, {"slot-1:1": png, "slot-1:2": clip}, mode=mode, out=mode)["assets"]
        assert [(r["kind"], r["seconds"]) for r in rows] == [("image", 0), ("clip", pytest.approx(2.0, abs=0.05))], mode
    assert rows[1]["file"] is None and rows[1]["sha256"] == rows[1]["source_sha256"] == hashlib.sha256(Path(clip).read_bytes()).hexdigest()


@needs_ffmpeg
def test_a_clips_tile_is_its_frame_at_half_a_second_with_a_marker_and_a_picture_tile_has_none(tmp_path):
    clip = tmp_path / "two-colours.mp4"
    C.ffmpeg("-f", "lavfi", "-i", "color=c=0xE01010:s=1280x720:r=30:d=0.5", "-f", "lavfi", "-i", "color=c=0x10E010:s=1280x720:r=30:d=1.5", "-filter_complex",
             "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-pix_fmt", "yuv420p", "-c:v", "libx264", str(clip))
    short = C.flat_clip(tmp_path / "short.mp4", 1280, 720, 0.3, colour="0x1010E0")
    png = write(tmp_path, "p.png", png_bytes(1280, 720, (200, 200, 30)))
    for mode in ("preview", "full"):
        run_clips(tmp_path, {"slot-1:1": str(clip), "slot-1:2": short, "slot-1:3": png}, mode=mode, out=mode)
        cw, ch = A.cell_size()
        w, h, raw = pixels_of(str(tmp_path / mode / "sheet.png"))
        assert (w, h) == (3 * cw, ch)
        centre = lambda col: pixel(raw, w, col * cw + cw // 2, ch // 2)                        # noqa: E731
        assert centre(0)[1] > 180 and centre(0)[0] < 80, mode                                    # green: the frame at 0.5 s
        assert centre(1)[2] > 180 and centre(1)[0] < 80, mode                                    # blue: a clip shorter than that gives its first frame
        assert centre(2)[0] > 150 and centre(2)[2] < 90, mode
        accent = tuple(int(DATA["theme"]["colors"]["accent"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        mx, my, mw, mh = A.MARKER
        for col, marked in ((0, True), (1, True), (2, False)):
            here = pixel(raw, w, col * cw + mx + mw // 2, my + mh // 2)
            assert (max(abs(here[i] - accent[i]) for i in range(3)) <= 3) == marked, (mode, col, here)


@needs_ffmpeg
def test_a_truncated_clip_is_asset_corrupt_and_a_clip_with_no_picture_stream_is_asset_type(tmp_path):
    clip = Path(C.counter_clip(tmp_path / "a.mp4", 1280, 720, 60, extra=("-movflags", "+faststart")))
    whole = clip.read_bytes()
    assert code_of(run_clips, tmp_path, {"slot-1:1": write(tmp_path, "cut.mp4", whole[:len(whole) // 2])}, out="o1") == ("asset_corrupt", "slot-1:1")
    assert code_of(run_clips, tmp_path, {"slot-1:1": write(tmp_path, "head.mp4", whole[:12])}, out="o2") == ("asset_corrupt", "slot-1:1")
    audio = tmp_path / "sound.m4a"
    C.ffmpeg("-f", "lavfi", "-i", "sine=f=300:d=1", "-c:a", "aac", str(audio))
    assert code_of(run_clips, tmp_path, {"slot-1:1": str(audio)}, out="o3") == ("asset_type", "slot-1:1")
    assert not any((tmp_path / "o1").iterdir()) and not (tmp_path / "o3").exists()         # a cut-short file is found when it is read to the end: nothing is kept


@needs_ffmpeg
def test_a_clip_over_the_size_caps_or_in_hdr_or_in_another_codec_is_refused_from_its_facts(tmp_path):
    clip = write(tmp_path, "any.mp4", Path(C.flat_clip(tmp_path / "src.mp4", 64, 64, 0.3)).read_bytes())
    cases = [({"streams": [stream(width=7681, height=1000)], "format": {"duration": "2"}}, "asset_dimensions"),
             ({"streams": [stream(width=7680, height=4321)], "format": {"duration": "2"}}, "asset_dimensions"),
             ({"streams": [stream(color_transfer="smpte2084")], "format": {"duration": "2"}}, "asset_type"),
             ({"streams": [stream(codec_name="mpeg4")], "format": {"duration": "2"}}, "asset_type"),
             ({"streams": [stream(codec_name="prores")], "format": {"duration": "2"}}, "asset_type"),
             ({"streams": [stream(disposition={"attached_pic": 1})], "format": {"duration": "2"}}, "asset_type"),
             ({"streams": [{"codec_type": "audio", "codec_name": "aac"}], "format": {"duration": "2"}}, "asset_type"),
             ({"streams": [stream()], "format": {}}, "asset_corrupt")]
    for n, (document, code) in enumerate(cases):
        probe = fake_ffprobe(tmp_path, document)
        assert code_of(A.asset_sheet, items={"slot-1:1": clip}, mode="preview", out_dir=str(tmp_path / ("o%d" % n)), ffmpeg=K.FFMPEG, ffprobe=probe, data=DATA,
                       decoders=("h264",)) == (code, "slot-1:1"), (n, document)
    exact = fake_ffprobe(tmp_path, {"streams": [stream(width=7680, height=4320)], "format": {"duration": "2"}})
    facts = _media.probe_clip(exact, clip, "mov", "f", ("h264",))
    assert (facts["width"], facts["height"], facts["codec"]) == (7680, 4320, "h264")
    rotated = fake_ffprobe(tmp_path, {"streams": [stream(width=1920, height=1080, side_data_list=[{"rotation": -90}])], "format": {"duration": "2"}})
    assert (lambda f: (f["width"], f["height"]))(_media.probe_clip(rotated, clip, "mov", "f", ("h264",))) == (1080, 1920)      # the displayed size


def test_the_frame_rate_flag_is_a_whole_number_from_24_to_60():
    assert [A.clip_fps(v) for v in (24, 30, 60, "45")] == [24, 30, 60, 45]
    for bad in (23, 61, 0, -30, "abc", 29.5, "030", None):
        assert code_of(A.clip_fps, bad) == ("bad_fps", "fps"), bad
    assert (_media.CLIP_FPS_MIN, _media.CLIP_FPS_DEFAULT, _media.CLIP_FPS_MAX) == (24, 30, 60)


@needs_ffmpeg
def test_a_clip_is_conformed_to_the_requested_rate(tmp_path):
    clip = C.counter_clip(tmp_path / "a.mp4", 1280, 720, 24, fps=24)                         # one second
    for fps in (24, 60):
        a, = run_clips(tmp_path, {"slot-1:1": clip}, out="r%d" % fps, fps=fps)["assets"]
        v, = probe_json(tmp_path / ("r%d" % fps) / a["file"])["streams"]
        assert v["r_frame_rate"] == v["avg_frame_rate"] == "%d/1" % fps and C.frames_of(tmp_path / ("r%d" % fps) / a["file"]) == fps


@needs_ffmpeg
def test_the_predominant_colour_of_a_clips_first_frame_follows_the_pages_rule(tmp_path):
    flat = C.flat_clip(tmp_path / "flat.mp4", 1280, 720, 0.5, colour="0x1EA05A", bt709=True)
    a, = run_clips(tmp_path, {"slot-1:1": flat})["assets"]
    colour = _media.predominant(_media.first_frame_rgb(K.FFMPEG, str(tmp_path / "out" / a["file"]), "mov"))
    assert colour is not None and all(abs(int(colour[i:i + 2], 16) - v) <= 17 for i, v in zip((0, 2, 4), (0x1E, 0xA0, 0x5A))), colour
    white = C.flat_clip(tmp_path / "white.mp4", 1280, 720, 0.5, colour="0xFFFFFF", bt709=True)
    b, = run_clips(tmp_path, {"slot-1:1": white}, out="w")["assets"]
    assert _media.predominant(_media.first_frame_rgb(K.FFMPEG, str(tmp_path / "w" / b["file"]), "mov")) is None


def test_the_predominant_rule_is_the_pages_rule_on_raw_samples():
    sample = lambda *rgb: bytes(rgb)                                                          # noqa: E731
    assert _media.predominant(sample(30, 160, 90) * 900 + sample(240, 240, 240) * 124) == "18A858"
    assert _media.predominant(sample(255, 255, 255) * 1024) is None and _media.predominant(sample(10, 10, 10) * 1024) is None and _media.predominant(b"") is None
    assert _media.predominant(sample(235, 240, 250) * 10) is None                              # every channel at 235 or more: skipped as near white
    assert _media.predominant(sample(235, 240, 100) * 10) is not None                          # one channel under 235: kept
    tie = sample(200, 40, 40) * 3 + sample(40, 40, 200) * 3                                    # two steps with the same count: the first to reach it wins
    assert _media.predominant(tie) == "%02X%02X%02X" % (0xC0 + 8, 0x20 + 8, 0x20 + 8)


@needs_ffmpeg
def test_the_host_stores_a_normalised_clip_content_addressed_and_read_only_and_a_second_call_replays_it(world, tmp_path):
    clip = C.counter_clip(tmp_path / "a.mp4", 1280, 720, 36)
    png = write(tmp_path, "p.png", png_bytes(1280, 720, (20, 40, 200)))
    out_dir = tmp_path / "picked"
    rc, out, err = world.host("asset-sheet", "--asset", "slot-1:1=" + clip, "--asset", "slot-1:2=" + png, "--mode", "full", "--fps", "24", "--out", out_dir)
    assert rc == 0, err
    video, picture = out["assets"]
    assert video["file"] == "asset-%s.mp4" % video["sha256"][:12] and picture["file"].endswith(".png") and out["replayed"] == 0
    path = Path(video["path"])
    assert path.parent == out_dir and hashlib.sha256(path.read_bytes()).hexdigest() == video["sha256"] and oct(path.stat().st_mode & 0o777) == "0o400"
    v, = probe_json(path)["streams"]
    assert v["codec_name"] == "h264" and v["r_frame_rate"] == "24/1" and (video["width"], video["height"]) == (1280, 720)
    assert sorted(p.name for p in out_dir.iterdir()) == sorted(["sheet.png", video["file"], picture["file"]])
    run = world.runs()[-1]["argv"]
    assert run[run.index("--network") + 1] == "none" and run[run.index("--fps") + 1] == "24"
    again = world.host("asset-sheet", "--asset", "slot-1:1=" + clip, "--asset", "slot-1:2=" + png, "--mode", "full", "--fps", "24", "--out", out_dir)
    assert again[0] == 0 and again[1]["replayed"] == 2 and again[1]["assets"][0]["sha256"] == video["sha256"]


def test_the_host_refuses_a_bad_frame_rate_before_any_container(tmp_path):
    import argparse
    host = argparse.ArgumentParser()
    _host.add_common_parsers(host.add_subparsers(dest="verb"))
    png = write(tmp_path, "a.png", png_bytes(8, 8))
    for fps in ("23", "61", "0"):
        args = host.parse_args(["asset-sheet", "--asset", "slot-1:1=" + png, "--mode", "full", "--fps", fps, "--out", str(tmp_path / "o")])
        assert code_of(_host.verb_asset_sheet, args) == ("bad_fps", "fps"), fps
    assert _host.ASSET_FILE.fullmatch("asset-0123456789ab.mp4") and not _host.ASSET_FILE.fullmatch("asset-0123456789ab.webm")


# ---------------------------------------------------------------- the review of #821: whitelists, caps, brands, durations

def test_only_the_brands_of_an_mp4_or_a_mov_and_the_doctypes_of_a_webm_are_clips():
    ftyp = lambda brand: b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 40                          # noqa: E731
    for brand in (b"isom", b"iso2", b"iso3", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"qt  "):
        assert _media.clip_container(ftyp(brand)) == "mov", brand
    for brand in (b"avif", b"avis", b"heic", b"heix", b"mif1", b"msf1", b"3gp4", b"M4A ", b"crx "):
        assert _media.clip_container(ftyp(brand)) is None, brand
    ebml = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81\x01\x42\xf2\x81\x04\x42\xf3\x81\x08"
    assert _media.clip_container(ebml + b"\x42\x82\x84webm" + b"\x00" * 20) == "matroska" and _media.clip_container(ebml + b"\x42\x82\x88matroska" + b"\x00" * 20) == "matroska"
    assert _media.clip_container(ebml + b"\x42\x82\x84xxxx" + b"\x00" * 20) is None and _media.clip_container(ebml[:4] + b"\x00" * 60) is None


def test_a_file_of_another_brand_is_asset_type_in_both_modes(tmp_path):
    for name, raw in (("avif", b"\x00\x00\x00\x1cftypavif" + b"\x00" * 60), ("heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 60), ("ebml", b"\x1a\x45\xdf\xa3" + b"\x00" * 60)):
        for mode in ("preview", "full"):
            assert code_of(A.asset_sheet, items={"slot-1:1": write(tmp_path, name, raw)}, mode=mode, out_dir=str(tmp_path / "o"), ffmpeg="/nowhere", data=DATA) == ("asset_type", "slot-1:1"), (name, mode)


def test_the_clip_input_carries_a_codec_whitelist_and_a_pixel_cap_on_ffprobe_and_ffmpeg_alike(tmp_path):
    every = ("h264", "hevc", "vp8", "vp9", "libdav1d", "libaom-av1", "h264_cuvid")
    probe_whitelist = _media.codec_whitelist(every).split(",")
    assert {"h264", "hevc", "vp8", "vp9", "libdav1d", "libaom-av1"} <= set(probe_whitelist) and not any("cuvid" in n or "v4l2" in n for n in probe_whitelist)
    assert "libdav1d" not in _media.codec_whitelist(("h264",)).split(",")                      # an av1 decoder is named only when the image has it
    argv_ffprobe = []
    probe = tmp_path / "ffprobe-record"
    probe.write_text("#!%s\nimport json, sys\nopen(%r, 'w').write(json.dumps(sys.argv[1:]))\nprint(json.dumps({'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 64, 'height': 64, 'r_frame_rate': '30/1', 'avg_frame_rate': '30/1'}], 'format': {'duration': '1'}}))\n"
                     % (sys.executable, str(tmp_path / "argv.json")))
    probe.chmod(0o755)
    _media.probe_clip(str(probe), "/x.mp4", "mov", "f", ("h264", "libdav1d"))
    argv_ffprobe = json.loads((tmp_path / "argv.json").read_text())
    assert argv_ffprobe[argv_ffprobe.index("-max_pixels") + 1] == "33177600" and argv_ffprobe[argv_ffprobe.index("-codec_whitelist") + 1].split(",") == _media.codec_whitelist(("h264", "libdav1d")).split(",")
    clip = {"demuxer": "mov", "decoder": "libdav1d", "color_space": "bt709", "width": 1920, "height": 1080, "seconds": 1.0}
    for argv in (A.clip_normalise_argv("ffmpeg", clip, "/i.mp4", "/o.mp4", (1920, 1080), 30, 100), A.clip_frame_argv("ffmpeg", clip, "/i.mp4", "/o.png"),
                 _media.compose_argv("ffmpeg", {"src": "/s", "has_audio": False, "fps": 30, "size": [1080, 1920], "src_matrix": "bt709", "kept": [[0, 60]], "layers": [], "frames_dir": "f",
                                                "pips": [], "out_frames": 60, "max_bytes": 1, "out_name": "o.mp4", "zoom": {"mode": "none", "factor": 1, "push_in": 0, "anchor_y": 0.25},
                                                "anchor": (540.0, 400.0), "fade": 0.015, "clips": [{"asset": "assets/c.mp4", "start_frame": 5, "end_frame": 20, "mode": "cover"}]})):
        i = argv.index("-max_pixels")
        assert argv[i + 1] == "33177600" and argv[argv.index("-codec_whitelist") + 1] in ("libdav1d", "h264") and argv[argv.index("-codec_whitelist") + 1] == argv[argv.index("-c:v", i) + 1]
    assert "h264_cuvid" not in " ".join(A.clip_normalise_argv("ffmpeg", clip, "/i.mp4", "/o.mp4", (1920, 1080), 30, 100))


@needs_ffmpeg
def test_the_whitelist_lets_a_clip_with_audio_through_and_refuses_a_codec_outside_it(tmp_path):
    with_audio = tmp_path / "audio.mp4"
    C.ffmpeg("-f", "lavfi", "-i", "color=c=red:s=1280x720:r=30:d=1", "-f", "lavfi", "-i", "sine=f=300:d=1", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(with_audio))
    a, = run_clips(tmp_path, {"slot-1:1": str(with_audio)})["assets"]
    assert a["kind"] == "clip"
    mpeg4 = tmp_path / "old.mp4"
    C.ffmpeg("-f", "lavfi", "-i", "color=c=red:s=1280x720:r=30:d=1", "-pix_fmt", "yuv420p", "-c:v", "mpeg4", str(mpeg4))
    assert code_of(run_clips, tmp_path, {"slot-1:1": str(mpeg4)}, out="o2") == ("asset_type", "slot-1:1")


def test_a_frame_rate_over_120_and_more_than_1200_frames_in_ten_seconds_are_asset_type(tmp_path):
    clip = write(tmp_path, "any.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40)
    def facts(**more):
        return fake_ffprobe(tmp_path, {"streams": [stream(**more)], "format": {"duration": "5"}})
    def refused(probe):
        return code_of(_media.probe_clip, probe, clip, "mov", "f", ("h264",))
    assert refused(facts(r_frame_rate="240/1", avg_frame_rate="30/1")) == ("asset_type", "f") and refused(facts(avg_frame_rate="121/1")) == ("asset_type", "f")
    assert _media.probe_clip(facts(r_frame_rate="120/1", avg_frame_rate="120/1"), clip, "mov", "f", ("h264",))["fps"] == 120.0
    assert refused(facts(nb_frames="1201", duration="1")) == ("asset_type", "f")                                  # more than 1200 in the 10 s window
    assert _media.probe_clip(facts(nb_frames="1200"), clip, "mov", "f", ("h264",))["codec"] == "h264"
    assert _media.probe_clip(facts(nb_frames="2400", duration="20"), clip, "mov", "f", ("h264",))["codec"] == "h264"       # 1200 of them fall in the first 10 s: kept
    assert (_media.CLIP_MAX_FPS, _media.CLIP_MAX_FRAMES, _media.CLIP_MAX_PIXELS) == (120, 1200, 33177600)


def test_a_normalised_clip_with_a_side_over_3840_is_asset_type_at_render(tmp_path):
    clip = write(tmp_path, "any.mp4", b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40)
    wide = fake_ffprobe(tmp_path, {"streams": [stream(width=3842, height=1080, format_name="x")], "format": {"duration": "2", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"}})
    assert code_of(_media.probe_clip, wide, clip, "mov", "f", None, True) == ("asset_type", "f")
    ok = fake_ffprobe(tmp_path, {"streams": [stream(width=3840, height=1080)], "format": {"duration": "2", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"}})
    assert _media.probe_clip(ok, clip, "mov", "f", None, True)["width"] == 3840
    assert _media.CLIP_RENDER_MAX_SIDE == A.MAX_OUT_SIDE == 3840


@needs_ffmpeg
def test_the_clips_length_is_its_video_streams_own_and_an_audio_track_running_past_it_does_not_count(tmp_path):
    clip = tmp_path / "long-audio.mp4"
    C.ffmpeg("-f", "lavfi", "-i", "color=c=red:s=1280x720:r=30:d=1", "-f", "lavfi", "-i", "sine=f=300:d=2", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(clip))
    assert probe_json(clip)["format"]["duration"] and float(probe_json(clip)["format"]["duration"]) > 1.5                     # the container says 2 s
    a, = run_clips(tmp_path, {"slot-1:1": str(clip)})["assets"]
    assert a["seconds"] == pytest.approx(1.0, abs=0.1)                                                                       # the video's 1 s
    assert _media.probe_clip(K.FFPROBE, str(clip), "mov", "f", ("h264",))["seconds"] == pytest.approx(1.0, abs=0.1)
    only_format = fake_ffprobe(tmp_path, {"streams": [stream()], "format": {"duration": "3"}})
    assert _media.probe_clip(only_format, str(clip), "mov", "f", ("h264",))["seconds"] == 3.0                                 # no stream length: the container's


def test_the_decoder_list_is_read_from_the_decoder_lines_and_not_from_the_legend(monkeypatch):
    listing = "Decoders:\n V..... = Video\n A..... = Audio\n ------\n V....D h264                 H.264\n VFS..D hevc                 HEVC\n V..... libdav1d             dav1d\n A....D aac                  AAC\n"
    monkeypatch.setattr(_media, "run", lambda argv, timeout, cwd=None: (listing, ""))
    assert _media.software_decoders("ffmpeg") == ("h264", "hevc", "libdav1d")


@needs_ffmpeg
def test_a_clip_whose_decoder_the_image_lacks_is_asset_type(tmp_path):
    clip = C.counter_clip(tmp_path / "a.mp4", 1280, 720, 10)
    assert code_of(run_clips, tmp_path, {"slot-1:1": clip}, decoders=("hevc",)) == ("asset_type", "slot-1:1")


def test_a_clip_entry_with_no_frame_is_a_closed_refusal_not_a_value_error():
    assert code_of(_media.clip_filters, {"asset": "a", "start_frame": 50, "end_frame": 50, "mode": "cover"}, 3, 0, 30, 120) == ("clip_no_frames", "clip")
    assert code_of(_media.clip_filters, {"asset": "a", "start_frame": 130, "end_frame": 140, "mode": "cover"}, 3, 0, 30, 120) == ("clip_no_frames", "clip")
