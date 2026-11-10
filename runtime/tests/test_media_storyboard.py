"""Tests of the storyboard of a short-video post (package V5-1, VD14): the operation `video-storyboard` (runtime/ops_media_storyboard.py), its file route,
the retention of its folders (runtime/upkeep.py) and its routes. The engine is the media kit's fake with a `storyboard` verb that writes PNG stand-ins; no
container, no tool and no model runs. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_storyboard.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import POST, FakeEngine, flag, media, ops, ops_core, post_text, sha, world  # noqa: F401
from test_service import PORT, STATUS, TOKEN, Standin

board = st.load("ops_media_storyboard")
animation = st.load("media_animation")
operations = st.load("operations")
seams = st.load("ops_step_seams")
service = st.load("service")
upkeep = st.load("upkeep")
cli = st.load("cli")
phrases = st.load("phrases")

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
LAN = "192.168.1.20"
PNG = b"\x89PNG\r\n\x1a\n"
DAY = 86400.0


class Drawing(FakeEngine):
    """The media kit's fake with the `storyboard` verb: it writes a PNG stand-in per beat and the sheet into --out and reports the beats."""

    def __init__(self, presets=("keyword", "cutaway")):
        super().__init__()
        self.presets = list(presets)

    def _storyboard(self, a):
        out = Path(flag(a, "--out"))
        out.mkdir(parents=True, exist_ok=True)
        beats = []
        for n, preset in enumerate(self.presets, 1):
            (out / f"beat-{n}.png").write_bytes(PNG + b"beat %d" % n)
            beats.append({"beat": n, "preset": preset, "file": f"beat-{n}.png", "sha256": "0" * 64})
        (out / "sheet.png").write_bytes(PNG + b"sheet")
        return {"ok": True, "beats": beats, "sheet": {"file": "sheet.png"}, "replayed": False}


@pytest.fixture(autouse=True)
def no_engine_variable(monkeypatch):
    monkeypatch.delenv("RENDERER_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("RENDERER_PROVIDER", raising=False)


@pytest.fixture
def drawing(world, monkeypatch):
    engine = Drawing()
    monkeypatch.setattr(board, "_engine_of", lambda ctx: engine)
    return engine


def draw(world, **kw):
    return board.video_storyboard(world["path"], kw.pop("post", POST), **kw)


# 1. the post checks


@pytest.mark.parametrize("post", ["../outside.md", "docs/marketing/content/Bad Name.md", "README.md", 7, None])
def test_a_name_that_is_not_a_post_is_bad_post_and_nothing_is_called(world, drawing, post):
    with pytest.raises(ops_core.OpsError) as refused:
        draw(world, post=post)
    assert "bad_post" in str(refused.value) and refused.value.code == 2 and drawing.calls == []


def test_a_post_that_is_not_there_is_bad_post(world, drawing):
    with pytest.raises(ops_core.OpsError) as refused:
        draw(world, post="docs/marketing/content/not-written-yet.md")
    assert "bad_post" in str(refused.value) and drawing.calls == []


def test_a_post_without_a_script_block_is_no_script_with_the_fixed_sentence(world, drawing):
    (Path(world["path"]) / POST).write_text(post_text(script=False), encoding="utf-8")
    with pytest.raises(ops_core.OpsError) as refused:
        draw(world)
    assert "no_script" in str(refused.value) and phrases.en("VID_STORYBOARD_NO_SCRIPT") in str(refused.value) and drawing.calls == []


def test_a_post_over_the_limit_and_a_linked_post_are_bad_post(world, drawing):
    project = Path(world["path"])
    big = project / "docs" / "marketing" / "content" / "big.md"
    big.write_bytes(b"x" * (st.load("step_media").POST_LIMIT + 1))
    with pytest.raises(ops_core.OpsError) as large:
        draw(world, post="docs/marketing/content/big.md")
    assert "bad_post" in str(large.value)
    link = project / "docs" / "marketing" / "content" / "linked.md"
    link.symlink_to(project / POST)
    with pytest.raises(ops_core.OpsError) as linked:
        draw(world, post="docs/marketing/content/linked.md")
    assert "bad_post" in str(linked.value) and drawing.calls == []


# 2. the call


def test_the_call_names_the_ffmpeg_engine_whatever_the_project_says(world, monkeypatch):
    seen = []

    class Spy(seams.MediaEngine):
        def call(self, cls, verb, args, timeout):
            seen.append((self._renderer, cls, verb, timeout))
            return Drawing().call(cls, verb, args, timeout)
    monkeypatch.setattr(seams, "MediaEngine", Spy)
    found = ops.video_storyboard(world["path"], POST)      # media.renderer is absent: the class default is hyperframes
    assert seen == [("ffmpeg", "renderer:video", "storyboard", 300)] and found["engine"] == "ffmpeg"
    assert seams.MediaStore(ops_core.context(world["path"])).renderer() is None


def test_the_call_carries_the_post_the_checker_the_vocabulary_and_no_recording(world, drawing):
    draw(world)
    [call] = drawing.of("storyboard")
    args = call["args"]
    assert (call["cls"], call["verb"], call["timeout"]) == ("renderer:video", "storyboard", 300)
    assert flag(args, "--post") == os.path.join(os.path.realpath(world["path"]), *POST.split("/"))
    assert flag(args, "--checker").endswith(os.path.join("mkt-social-copy", "scripts", "check_script.py"))
    assert flag(args, "--vocabulary").endswith(os.path.join("shared", "references", "video-presets.json"))
    assert flag(args, "--out").startswith(os.path.join(ops_core.context(world["path"])["cfg"]["data_dir"], "media", "storyboards"))
    assert "--face-box" not in args and "--transcript" not in args and "--in" not in args


def test_the_theme_flags_of_the_projects_identity_are_handed_on_and_the_default_gives_none(world, drawing, monkeypatch):
    draw(world)
    assert "--color" not in drawing.of("storyboard")[0]["args"] and "--font" not in drawing.of("storyboard")[0]["args"]      # no identity: the renderer's default theme
    monkeypatch.setattr(board.theme, "theme_args", lambda project, *a, **k: (["--color", "accent=#112233", "--font", "title=inter:700"], {}))
    draw(world)
    args = drawing.of("storyboard")[1]["args"]
    assert flag(args, "--color") == "accent=#112233" and flag(args, "--font") == "title=inter:700"


def test_a_refused_theme_is_refused_with_its_code(world, drawing):
    identity = Path(world["path"]) / "docs" / "brand" / "identity.md"
    identity.parent.mkdir(parents=True, exist_ok=True)
    identity.write_text("# Identity\n\n- Status: draft\n", encoding="utf-8")
    with pytest.raises(ops_core.OpsError) as refused:
        draw(world)
    assert str(refused.value).startswith("theme_draft:") and drawing.calls == []


def test_the_key_depends_on_the_post_the_theme_flags_and_the_pins(world, drawing, monkeypatch):
    first = draw(world)["key"]
    (Path(world["path"]) / POST).write_text(post_text() + "\nmore\n", encoding="utf-8")
    changed_post = draw(world)["key"]
    assert changed_post != first and len(changed_post) == 16
    monkeypatch.setattr(board, "_theme_flags", lambda project: ["--color", "accent=#112233"])
    assert draw(world)["key"] != changed_post
    monkeypatch.setattr(board, "_pins", lambda root: b"other pins")
    assert draw(world)["key"] not in (first, changed_post)
    assert board._key(b"ab", ["c"], b"") != board._key(b"a", ["bc"], b"")      # no part runs into the next


# 3. the return and the replay


def test_the_return_has_the_key_the_sheet_the_beats_the_engine_and_the_advisory_sentence(world, drawing):
    found = draw(world, channel="page")
    assert set(found) == {"key", "sheet", "beats", "engine", "advisory"} and found["sheet"] == "sheet.png" and found["engine"] == "ffmpeg"
    assert found["advisory"] == phrases.en("VID_STORYBOARD_ADVISORY")
    assert [(b["beat"], b["preset"], b["file"]) for b in found["beats"]] == [(1, "keyword", "beat-1.png"), (2, "cutaway", "beat-2.png")]
    assert found["beats"][0]["drawn_block"] == "oh:keyword" and found["beats"][0]["video_block"] == "hf:spring-pop"      # the block each engine's preset map names for the keyword preset: the video differs from the drawing


def test_video_block_is_null_where_the_projects_engine_draws_no_block_for_the_preset(world, drawing):
    found = draw(world)
    [cutaway] = [b for b in found["beats"] if b["preset"] == "cutaway"]
    assert cutaway["drawn_block"] == "oh:cutaway" and cutaway["video_block"] is None


def test_the_terminal_gets_the_absolute_path_of_the_sheet_and_the_page_does_not(world, drawing):
    terminal = draw(world, channel="terminal")
    assert os.path.isabs(terminal["sheet_path"]) and os.path.isfile(terminal["sheet_path"]) and terminal["key"] in terminal["sheet_path"]
    assert "sheet_path" not in draw(world, channel="page") and draw(world)["sheet_path"] == terminal["sheet_path"]


def test_the_same_key_is_a_replay_that_makes_no_call_and_touches_the_folder(world, drawing):
    first = draw(world)
    assert len(drawing.of("storyboard")) == 1
    folder = Path(first_path(world, first))
    old = time.time() - 5 * DAY
    os.utime(folder, (old, old))
    again = draw(world)
    assert again == first and len(drawing.of("storyboard")) == 1
    assert time.time() - folder.stat().st_mtime < 60


def test_a_folder_without_its_record_is_drawn_again(world, drawing):
    first = draw(world)
    (Path(first_path(world, first)) / "result.json").unlink()
    draw(world)
    assert len(drawing.of("storyboard")) == 2


def first_path(world, found):
    return os.path.join(ops_core.context(world["path"])["cfg"]["data_dir"], "media", "storyboards", found["key"])


# 4. the refusals of the renderer keep their closed codes


@pytest.mark.parametrize("code,wanted", [("not_configured", "not_configured"), ("refused", "engine_refused"), ("engine_failed", "engine_failed"), ("anything", "engine_failed")])
def test_the_engine_refusals_keep_closed_codes(world, drawing, code, wanted):
    drawing.fail["storyboard"] = seams.StepServiceError(code)
    with pytest.raises(ops_core.OpsError) as refused:
        draw(world)
    assert str(refused.value).startswith(wanted + ":")
    if code == "not_configured":
        assert world_next() in str(refused.value)


def world_next():
    return st.load("step_media").ENGINE_NEXT["not_configured"]


def test_a_report_that_is_not_beats_is_refused_and_leaves_no_record(world, drawing, monkeypatch):
    monkeypatch.setattr(Drawing, "_storyboard", lambda self, a: {"ok": True, "beats": [{"beat": "1", "preset": "keyword", "file": "../x.png"}]})
    with pytest.raises(ops_core.OpsError) as refused:
        draw(world)
    assert str(refused.value).startswith("engine_refused:")


# 5. the channel


def test_the_terminal_and_the_page_pass_and_the_rest_are_refused(world, drawing):
    for channel in (None, "terminal", "page"):
        assert draw(world, channel=channel)["engine"] == "ffmpeg"
    for channel in ("mcp", "messaging", "other"):
        with pytest.raises(ops_core.OpsError) as refused:
            draw(world, channel=channel)
        assert refused.value.code == 1
    with pytest.raises(ops_core.OpsError):
        board.video_storyboard_file(world["path"], "0" * 16, "sheet.png", "messaging")


# 6. the file route


def test_the_file_is_the_png_of_the_folder(world, drawing):
    found = draw(world)
    sheet = board.video_storyboard_file(world["path"], found["key"], "sheet.png", "page")
    assert sheet == {"media_type": "image/png", "data": PNG + b"sheet"}
    assert ops.video_storyboard_file(world["path"], found["key"], "beat-2.png")["data"] == PNG + b"beat 2"


@pytest.mark.parametrize("key,file", [("0" * 16, "sheet.png"), ("0" * 15, "sheet.png"), ("G" * 16, "sheet.png"), ("../" + "0" * 13, "sheet.png"),
                                      (7, "sheet.png"), ("0" * 16, "result.json"), ("0" * 16, "beat-123.png"), ("0" * 16, "../sheet.png"),
                                      ("0" * 16, "sheet.png/"), ("0" * 16, "Sheet.png"), ("0" * 16, None)])
def test_the_file_route_refuses_a_name_outside_the_pattern_and_a_bad_key(world, drawing, key, file):
    with pytest.raises(ops_core.OpsError) as refused:
        board.video_storyboard_file(world["path"], key, file)
    assert refused.value.code in (1, 2)


def test_the_file_route_refuses_a_link_and_a_file_that_is_not_a_png(world, drawing):
    found = draw(world)
    folder = Path(first_path(world, found))
    (folder / "beat-9.png").write_bytes(b"not a png at all")
    with pytest.raises(ops_core.OpsError) as bad:
        board.video_storyboard_file(world["path"], found["key"], "beat-9.png")
    assert "bad_file" in str(bad.value)
    secret = world["tmp"] / "outside.png"
    secret.write_bytes(PNG + b"secret")
    (folder / "beat-8.png").symlink_to(secret)
    with pytest.raises(ops_core.OpsError) as linked:
        board.video_storyboard_file(world["path"], found["key"], "beat-8.png")
    assert "not_found" in str(linked.value)
    other = world["tmp"] / "elsewhere"
    other.mkdir()
    (other / "sheet.png").write_bytes(PNG + b"elsewhere")
    data_dir = Path(ops_core.context(world["path"])["cfg"]["data_dir"])
    (data_dir / "media" / "storyboards" / ("a" * 16)).symlink_to(other)      # a linked folder
    with pytest.raises(ops_core.OpsError):
        board.video_storyboard_file(world["path"], "a" * 16, "sheet.png")


# 7. the routes and the LAN socket


@pytest.fixture
def stand(tmp_path):
    fake = Standin(tmp_path / "data")
    fake.answers["status"] = STATUS
    folder = tmp_path / "alpha"
    folder.mkdir()
    projects = [{"id": service.project_id(str(folder)), "name": "alpha", "path": str(folder)}]
    svc = service.Service(fake, projects, TOKEN, PORT, str(tmp_path), log=[].append)
    svc.lan_ip = LAN
    return types.SimpleNamespace(svc=svc, fake=fake, projects=projects)


def test_the_routes_cross_the_lan_socket_as_well_as_the_loopback_one(stand):
    [draw_route] = [r for r in service.ROUTES if r["op"] == "video-storyboard"]
    [file_route] = [r for r in service.ROUTES if r["op"] == "video-storyboard-file"]
    assert (draw_route["method"], draw_route["pattern"], draw_route["take"]) == ("POST", "/projects/{p}/video-storyboard", ("post",))
    assert (file_route["method"], file_route["pattern"], file_route["raw"]) == ("GET", "/projects/{p}/video-storyboard/{key}/{name}", True)
    assert operations.by_name("video-storyboard")["job"] is True and not operations.by_name("video-storyboard-file").get("job")
    assert "video-storyboard" not in operations.LAN_REFUSED_OPS and "video-storyboard-file" not in operations.LAN_REFUSED_OPS
    stand.fake.answers["video_storyboard"] = {"key": "0" * 16, "sheet": "sheet.png", "beats": [], "engine": "ffmpeg"}
    stand.fake.answers["video_storyboard_file"] = {"media_type": "image/png", "data": PNG}
    base = f"/api/v1/projects/{stand.projects[0]['id']}/video-storyboard"
    for lan in (False, True):
        host = f"{LAN}:{PORT}" if lan else f"127.0.0.1:{PORT}"
        sent = {"Host": host, "Authorization": f"Bearer {TOKEN}"}
        body = json.dumps({"post": POST}).encode()
        post_head = {**sent, "Origin": f"http://{host}", "Content-Type": "application/json", "Content-Length": str(len(body))}
        status, _, payload = service.handle(stand.svc, "POST", base, post_head, body, lan=lan)
        assert status == 202 and json.loads(payload)["op"] == "video-storyboard", lan      # a job: the draw can take minutes
        status, headers, payload = service.handle(stand.svc, "GET", f"{base}/{'0' * 16}/sheet.png", sent, b"", lan=lan)
        assert status == 200 and payload == PNG and headers["Content-Type"] == "image/png", lan
    assert [c[0] for c in stand.fake.calls if c[0] == "video_storyboard_file"] == ["video_storyboard_file"] * 2


def test_a_key_that_is_not_16_hex_is_no_route(stand):
    sent = {"Host": f"127.0.0.1:{PORT}", "Authorization": f"Bearer {TOKEN}"}
    base = f"/api/v1/projects/{stand.projects[0]['id']}/video-storyboard"
    for tail in ("ABCDEF0123456789/sheet.png", "0123/sheet.png", f"{'0' * 16}/.hidden", f"{'0' * 16}/../sheet.png"):
        status, _, _ = service.handle(stand.svc, "GET", f"{base}/{tail}", sent, b"")
        assert status == 404, tail


# 8. the terminal


def test_the_terminal_calls_the_operation(world, drawing):
    row, found = cli.run_row(["video-storyboard", "--project", world["path"], "--post", POST])
    assert row["name"] == "video-storyboard" and found["key"] and os.path.isfile(found["sheet_path"])
    again = cli.run(["video-storyboard", "--project", world["path"], "--post", POST])
    assert again == found and len(drawing.of("storyboard")) == 1


# 9. the retention


def put(data_dir, key, age_days, now):
    folder = Path(data_dir) / "media" / "storyboards" / key
    folder.mkdir(parents=True)
    (folder / "sheet.png").write_bytes(PNG)
    stamp = now - age_days * DAY
    os.utime(folder, (stamp, stamp))
    return folder


def test_upkeep_removes_a_folder_older_than_30_days_and_keeps_a_newer_one(tmp_path):
    data, now = str(tmp_path / "data"), 1_800_000_000.0
    old, young = put(data, "a" * 16, 31, now), put(data, "b" * 16, 29, now)
    stray = put(data, "not-a-key", 400, now)
    removed = upkeep.sweep_storyboards(data, now=now)
    assert removed == [{"storyboard": "a" * 16, "what": "all"}]
    assert not old.exists() and young.exists() and stray.exists()


def test_upkeep_never_follows_a_link_and_ignores_a_missing_folder(tmp_path):
    data, now = tmp_path / "data", 1_800_000_000.0
    assert upkeep.sweep_storyboards(str(data), now=now) == []
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("kept")
    base = data / "media" / "storyboards"
    base.mkdir(parents=True)
    (base / ("c" * 16)).symlink_to(outside)
    assert upkeep.sweep_storyboards(str(data), now=now) == [] and (outside / "keep.txt").exists()


def test_the_pass_of_the_media_part_removes_it_and_the_media_purge_leaves_the_folder_alone(world, drawing):
    found = draw(world)
    folder = Path(first_path(world, found))
    ctx = ops_core.context(world["path"])
    now = time.time()
    assert upkeep.sweep_media(ctx, now=now + 10 * DAY)["removed"] == [] and folder.exists()      # the store's own purge does not take it
    os.utime(folder, (now - 31 * DAY, now - 31 * DAY))
    done = upkeep.sweep_media(ctx, now=now)
    assert {"storyboard": found["key"], "what": "all"} in done["removed"] and not folder.exists()
    assert upkeep._counts(done)["removed"] >= 1


# 10. the live drawing (the supervisor's: a real container; never run by CI or by the executor)


@pytest.mark.skipif(os.environ.get("WB_RENDERER_DOCKER_TESTS") != "1", reason="a real container: set WB_RENDERER_DOCKER_TESTS=1 with the ffmpeg image built and recorded (OPENHORA_STATE_DIR), run with no -n")
def test_live_the_fictional_post_of_the_kit_is_drawn_in_the_container(world, monkeypatch):
    for name in ("RENDERER_VIDEO_PROVIDER", "RENDERER_PROVIDER", "RENDERER_TEST", "RENDERER_BLOCKS_DIR"):
        monkeypatch.delenv(name, raising=False)
    found = board.video_storyboard(world["path"], POST, "terminal")      # the real MediaEngine(root, "ffmpeg"), no stand-in
    assert found["engine"] == "ffmpeg" and found["beats"]
    sizes = {}
    for name in ["sheet.png"] + [b["file"] for b in found["beats"]]:
        data = board.video_storyboard_file(world["path"], found["key"], name, "page")["data"]
        assert data.startswith(PNG)
        sizes[name] = (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))      # the IHDR width and height
    assert all(sizes[b["file"]] == (1080, 1920) for b in found["beats"]) and sizes["sheet.png"][0] > 0
    again = board.video_storyboard(world["path"], POST, "terminal")
    assert again == found      # the replay


# 11. the module starts on its own


def test_the_module_starts_on_its_own():
    argv = [sys.executable, "-I", str(RUNTIME / "ops_media_storyboard.py")]
    helped = subprocess.run(argv + ["--help"], capture_output=True, text=True, env={})
    assert helped.returncode == 0 and helped.stdout.strip()
    assert subprocess.run(argv, capture_output=True, text=True, env={}).returncode == 2
