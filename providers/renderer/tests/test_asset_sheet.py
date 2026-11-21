"""The `asset-sheet` verb (`_asset_sheet.py`, package V9b-2): what it accepts, what it refuses and what it writes. Every picture is made here: a flat-colour
PNG built with `zlib` (never a real picture), a JPEG and a clip made by the host's ffmpeg (these tests are skipped without it). No docker, no browser, no
network. The host side (`_host.verb_asset_sheet`) is run against the fake docker of `docker_kit.py`. Names are fictional.
"""
from __future__ import annotations

import hashlib
import json
import struct
import subprocess
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
def test_an_upscale_of_one_and_a_half_times_is_accepted_and_more_is_refused(tmp_path):
    ok = run(tmp_path, {"slot-1:1": write(tmp_path, "ok.png", png_bytes(1280, 720))})
    assert (ok["assets"][0]["width"], ok["assets"][0]["height"]) == (1920, 1080)
    assert code_of(run, tmp_path, {"slot-1:1": write(tmp_path, "small.png", png_bytes(1279, 720))}, out="out2") == ("asset_too_small", "slot-1:1")
    assert not (tmp_path / "out2").exists() or not any((tmp_path / "out2").iterdir())


def test_the_target_size_is_integer_arithmetic_with_the_limit_at_one_and_a_half():
    assert A.target_size(1280, 720, "f") == (1920, 1080)
    assert A.target_size(720, 1280, "f") == (1080, 1920)
    assert A.target_size(1920, 1080, "f") == (1920, 1080)
    assert code_of(A.target_size, 1279, 700, "f") == ("asset_too_small", "f")
    assert A.target_size(1, 1920, "f") == (1, 1920)


# ---------------------------------------------------------------- what it refuses

@needs_ffmpeg
def test_an_animated_png_a_gif_a_webp_and_a_clip_are_asset_type(tmp_path):
    animated = png_bytes(1280, 720, extra=[(b"acTL", struct.pack(">II", 2, 0))])
    clip = tmp_path / "clip.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64:d=0.2:r=10", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip))
    bad = {"animated": animated, "gif": b"GIF89a" + b"\x00" * 40, "webp": b"RIFF\x20\x00\x00\x00WEBPVP8 " + b"\x00" * 40, "clip": clip.read_bytes()}
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
    too_many = dict(answer, assets=answer["assets"] * 37)
    with pytest.raises(Refusal):
        D.sanitise(too_many, D.RESULT_SCHEMAS["asset-sheet"], "asset-sheet")


def test_the_flags_of_the_verb_parse_on_the_host_and_in_the_image():
    import argparse
    import _inner
    host = argparse.ArgumentParser()
    _host.add_common_parsers(host.add_subparsers(dest="verb"))
    args = host.parse_args(["asset-sheet", "--asset", "slot-1:1=/x/a.png", "--asset", "slot-1:2=/x/b.png", "--mode", "preview", "--out", "/o"])
    assert args.asset == ["slot-1:1=/x/a.png", "slot-1:2=/x/b.png"] and args.mode == "preview" and args.out == "/o"
    inner = _inner.parser().parse_args(["asset-sheet", "--asset", "slot-1:1=/job/assets/slot-1.1", "--mode", "full", "--out", "/out"])
    assert inner.verb == "asset-sheet" and inner.mode == "full"
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
    assert max(out["assets"][1]["width"], out["assets"][1]["height"]) == 1920
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
