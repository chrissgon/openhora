"""Tests of "Add an animation" in the runtime (package V1b3, VD15): the catalogue read as data (runtime/media_animation.py), the checker that hands a block's
parameters to the renderer's own checker through MediaEngine, the verb `block-params` of the engine seam, the beat the align step appends, the operation
`video-catalogue` and its route. The engine is a fake that answers `block-params` and passes every other verb to the media kit's; the one test that starts a
process runs the renderer's host verb on committed files (no container). Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_animation.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import POST, add, media, open_items, ops, ops_core, run_task, steps, task_row, work_file, world  # noqa: F401
from test_service import PORT, STATUS, TOKEN, Standin

animation = st.load("media_animation")
captions = st.load("captions")
seams = st.load("ops_step_seams")
ops_media = st.load("ops_media")
ops_media_catalogue = st.load("ops_media_catalogue")
project_config = st.load("project_config")
service = st.load("service")
operations = st.load("operations")
cli = st.load("cli")

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
BLOCKS = REPO / "providers" / "renderer" / "blocks"
VOCABULARY = REPO / "shared" / "references" / "video-presets.json"
KEYWORD = {"block": "oh:keyword", "params": {"text": "Every step counts"}}
ADD = dict(KEYWORD, op="animation", word_from=1, word_to=3)
LAN = "192.168.1.20"


@pytest.fixture(autouse=True)
def no_engine_variable(monkeypatch):
    monkeypatch.delenv("RENDERER_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("RENDERER_PROVIDER", raising=False)


class Checking:
    """MediaEngine's stand-in for `block-params`: records the call and, at the call, what the params file held and its mode."""

    def __init__(self, answer=None, error=None, real=None):
        self.calls, self.seen, self.answer, self.error, self.real = [], [], answer, error, real

    def call(self, cls, verb, args, timeout):
        if verb != "block-params":
            return self.real(cls, verb, args, timeout)
        self.calls.append((cls, verb, list(args), timeout))
        path = args[args.index("--params") + 1]
        self.seen.append((path, json.loads(Path(path).read_text(encoding="utf-8")), stat.S_IMODE(os.stat(path).st_mode)))
        if self.error is not None:
            raise self.error
        if self.answer is not None:
            return self.answer
        return {"ok": True, "block": args[args.index("--block") + 1], "engine": "ffmpeg", "params": sorted(self.seen[-1][1])}


def use(monkeypatch, engine):
    monkeypatch.setattr(animation, "engine_of", lambda ctx: engine)
    return engine


def ctx_of(tmp_path):
    return {"cfg": {"data_dir": str(tmp_path / "data")}}


def plant(tmp_path, mutate=None, pins=None, catalogue=None):
    """A root under tmp_path with a copy of the two committed files, the catalogue changed by `mutate(doc)`."""
    folder = tmp_path / "root" / "providers" / "renderer" / "blocks"
    folder.mkdir(parents=True)
    doc = json.loads((BLOCKS / "catalogue.json").read_text(encoding="utf-8"))
    if mutate:
        mutate(doc)
    (folder / "catalogue.json").write_bytes(catalogue if catalogue is not None else json.dumps(doc).encode("utf-8"))
    shutil.copy(BLOCKS / "pins.json", folder / "pins.json")
    if pins is not None:
        (folder / "pins.json").write_bytes(pins)
    return str(tmp_path / "root")


def entry(name="oh:extra", kind="overlay", preset="keyword", params=None, engines=("ffmpeg", "hyperframes")):
    return {"name": name, "namespace": "oh", "kind": kind, "preset": preset, "band": "overlay", "may_cross_face": False, "license": ["MIT"], "source": "openhora",
            "use_when": "a planted block", "params": params if params is not None else {"text": {"type": "text", "max": 24, "required": True}},
            "samples": [{}], "natural_duration": None, "runtimes": ["renderat"], "engines": list(engines)}


def refusal(call, *args):
    with pytest.raises(captions.CaptionError) as caught:
        call(*args)
    return caught.value.code, caught.value.field


# 1 and 2. the catalogue as data


def test_the_committed_catalogue_is_read_with_its_pins_and_hands_out_only_the_known_keys():
    found = animation.read_catalogue(str(REPO))
    assert found["blocks"]["oh:keyword"]["preset"] == "keyword" and found["blocks"]["oh:keyword"]["kind"] == "overlay"
    assert found["blocks_sha256"] == hashlib.sha256((BLOCKS / "pins.json").read_bytes()).hexdigest()
    raw = json.loads((BLOCKS / "catalogue.json").read_text(encoding="utf-8"))
    assert all(set(b) <= set(animation.CATALOGUE_KEYS) for b in raw["blocks"]), "a new key of the generator is added to CATALOGUE_KEYS on purpose"
    assert sorted(found["blocks"]) == sorted(b["name"] for b in raw["blocks"])


def renamed(doc):
    doc["blocks"][0]["name"] = "xx:keyword"


def duplicated(doc):
    doc["blocks"].append(copy.deepcopy(doc["blocks"][0]))


@pytest.mark.parametrize("how", ["missing", "huge", "link", "not_json", "bad_name", "duplicate", "bad_kind", "bad_version"])
def test_a_catalogue_that_cannot_be_read_is_refused_as_unreadable(tmp_path, how):
    root = plant(tmp_path)
    path = Path(root, "providers", "renderer", "blocks", "catalogue.json")
    if how == "missing":
        path.unlink()
    elif how == "huge":
        path.write_bytes(b" " * ((1 << 20) + 1))
    elif how == "link":
        real = path.with_name("real.json")
        path.rename(real)
        path.symlink_to(real)
    elif how == "not_json":
        path.write_bytes(b"{not json")
    else:
        doc = json.loads(path.read_text(encoding="utf-8"))
        {"bad_name": renamed, "duplicate": duplicated, "bad_kind": lambda d: d["blocks"][0].update(kind="movie"),
         "bad_version": lambda d: d.update(schema_version=2)}[how](doc)
        path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(animation.CatalogueError) as caught:
        animation.read_catalogue(root)
    assert caught.value.code == "catalogue_unreadable"


def test_a_pins_file_that_differs_by_one_byte_makes_the_catalogue_stale_and_an_extra_key_is_dropped(tmp_path):
    root = plant(tmp_path, pins=(BLOCKS / "pins.json").read_bytes() + b"\n")
    with pytest.raises(animation.CatalogueError) as caught:
        animation.read_catalogue(root)
    assert caught.value.code == "catalogue_stale"
    root = plant(tmp_path / "other", mutate=lambda d: d["blocks"][2].update(secret="x"))
    assert "secret" not in animation.read_catalogue(root)["blocks"][json.loads(Path(root, "providers/renderer/blocks/catalogue.json").read_text())["blocks"][2]["name"]]


# 3 and 4. the listing and the engine


def test_the_listing_says_for_each_block_whether_it_can_be_added_and_why_not(tmp_path, monkeypatch):
    def more(doc):
        doc["blocks"] += [entry("oh:bare", preset=None), entry("oh:pic", params={"asset": {"type": ["image", "clip"], "required": True}}),
                          entry("oh:only-hf", engines=("hyperframes",))]
    root = plant(tmp_path, more)
    monkeypatch.setattr(animation, "engine_name", lambda r, i=None: "ffmpeg")
    shown = animation.listing(root)
    rows = {b["name"]: b for b in shown["blocks"]}
    assert [b["name"] for b in shown["blocks"]] == sorted(rows)
    assert rows["oh:keyword"]["addable"] is True and rows["oh:keyword"]["why"] is None
    assert (rows["oh:cutaway"]["addable"], rows["oh:cutaway"]["why"]) == (False, "kind")
    assert rows["oh:caption"]["why"] == "kind"
    assert rows["oh:bare"]["why"] == "no_preset" and rows["oh:pic"]["why"] == "slot" and rows["oh:only-hf"]["why"] == "engine"
    assert shown["engine"] == "ffmpeg" and shown["presets"]["keyword"] == "oh:keyword" and (shown["animations_max"], shown["beats_max"]) == (12, 12)
    monkeypatch.setattr(animation, "engine_name", lambda r, i=None: None)
    none = animation.listing(root)
    whys = {b["name"]: b["why"] for b in none["blocks"]}
    assert none["presets"] == {} and none["engine"] is None
    assert whys["oh:bare"] == "no_preset" and whys["oh:pic"] == "slot" and whys["oh:cutaway"] == "kind"
    assert all(whys[name] == "not_configured" for name in ("oh:keyword", "oh:list", "oh:number", "oh:quote", "oh:only-hf"))


def test_the_engine_is_the_class_default_with_no_variable_set_and_the_one_a_project_names():
    assert animation.engine_name(str(REPO)) == "hyperframes"
    assert animation.engine_name(str(REPO), "ffmpeg") == "ffmpeg"
    assert animation.engine_name(str(REPO), "heygen") is None


def test_the_listing_and_the_checker_read_the_projects_renderer_through_the_store(tmp_path, monkeypatch):
    root = plant(tmp_path)
    asked = []
    monkeypatch.setattr(animation, "engine_name", lambda r, i=None: asked.append(i) or "ffmpeg")
    monkeypatch.setattr(seams.MediaStore, "renderer", lambda self: "ffmpeg")
    monkeypatch.setattr(seams.MediaStore, "root", lambda self: root)
    animation.listing(root, "ffmpeg")
    use(monkeypatch, Checking())
    animation.checker(ctx_of(tmp_path))("oh:keyword", {"text": "Every step counts"}, "edits[0]")
    assert asked == ["ffmpeg", "ffmpeg"]


# 5, 6 and 7. the checker


def test_the_checker_hands_the_cleaned_parameters_to_the_renderers_checker_in_a_private_file_and_removes_it(tmp_path, monkeypatch):
    fake = use(monkeypatch, Checking())
    animate = animation.checker(ctx_of(tmp_path))
    done = animate("oh:keyword", {"text": "  Every step counts "}, "edits[0]")
    assert done == {"block": "oh:keyword", "preset": "keyword", "params": {"text": "Every step counts"}}
    [(cls, verb, args, timeout)] = fake.calls
    assert (cls, verb, timeout) == ("renderer:video", "block-params", 60)
    assert args == ["--block", "oh:keyword", "--params", fake.seen[0][0], "--vocabulary", str(VOCABULARY)]
    path, held, mode = fake.seen[0]
    assert held == {"text": "Every step counts"} and mode == 0o600 and not os.path.exists(path)
    broken = use(monkeypatch, Checking(error=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        animate("oh:keyword", {"text": "x"}, "edits[0]")
    assert not os.path.exists(broken.seen[0][0])


def test_every_refusal_that_needs_no_engine_starts_no_process(tmp_path, monkeypatch):
    def more(doc):
        doc["blocks"] += [entry("oh:bare", preset=None), entry("oh:only-hf", engines=("hyperframes",))]
    root = plant(tmp_path, more)
    fake = use(monkeypatch, Checking())
    monkeypatch.setattr(seams.MediaStore, "root", lambda self: root)
    monkeypatch.setattr(animation, "engine_name", lambda r, i=None: "ffmpeg")
    animate = animation.checker(ctx_of(tmp_path))
    where = "edits[0]"
    assert refusal(animate, "keyword", {}, where) == ("bad_block", "edits[0].block")
    assert refusal(animate, "oh:nope", {}, where) == ("unknown_block", "edits[0].block")
    assert refusal(animate, "oh:cutaway", {}, where) == ("animation_kind", "edits[0].block")
    assert refusal(animate, "oh:bare", {}, where) == ("block_no_preset", "edits[0].block")
    assert refusal(animate, "oh:only-hf", {}, where) == ("block_not_on_engine", "edits[0].block")
    for bad in ("text", {f"p{k}": "x" for k in range(13)}, {"text": True}, {"text": {"a": 1}}, {"text": "x" * 9000}, {"Text": "x"}, {"text": float("nan")}):
        assert refusal(animate, "oh:keyword", bad, where) == ("bad_params", "edits[0].params"), bad
    monkeypatch.setattr(animation, "engine_name", lambda r, i=None: None)
    assert refusal(animation.checker(ctx_of(tmp_path)), "oh:keyword", {"text": "x"}, where)[0] == "not_configured"
    stale = plant(tmp_path / "stale", pins=b"{}")
    monkeypatch.setattr(seams.MediaStore, "root", lambda self: stale)
    assert refusal(animation.checker(ctx_of(tmp_path)), "oh:keyword", {"text": "x"}, where) == ("catalogue_stale", "edits[0].block")
    assert fake.calls == []


@pytest.mark.parametrize("raised, expected", [
    (seams.StepServiceError("refused", "undeclared_param params.size"), ("undeclared_param", "edits[0].params.size")),
    (seams.StepServiceError("refused", "block_unknown block"), ("block_unknown", "edits[0].block")),
    (seams.StepServiceError("refused", ""), ("block_check_failed", "edits[0]")),
    (seams.StepServiceError("not_configured"), ("not_configured", "edits[0]")),
    (seams.StepServiceError("engine_failed"), ("block_check_failed", "edits[0]")),
])
def test_the_checker_maps_what_the_engine_answers_to_a_closed_refusal(tmp_path, monkeypatch, raised, expected):
    use(monkeypatch, Checking(error=raised))
    assert refusal(animation.checker(ctx_of(tmp_path)), "oh:keyword", {"text": "x", "size": 3}, "edits[0]") == expected


@pytest.mark.parametrize("answer", [{"ok": True, "block": "oh:list", "params": ["text"]}, {"ok": True, "block": "oh:keyword", "params": ["text", "icon"]},
                                    {"ok": False, "block": "oh:keyword", "params": ["text"]}, ["x"]])
def test_an_answer_that_does_not_match_what_was_asked_is_a_failed_check(tmp_path, monkeypatch, answer):
    use(monkeypatch, Checking(answer=answer))
    assert refusal(animation.checker(ctx_of(tmp_path)), "oh:keyword", {"text": "x"}, "edits[0]") == ("block_check_failed", "edits[0]")


# 8. the engine seam


class Gone(Exception):
    def __init__(self, kind, exit_code=None, tail=""):
        super().__init__(kind)
        self.kind, self.exit_code, self.reason, self.stderr_tail = kind, exit_code, "x", tail


class Resolver:
    ProviderCallError = Gone

    def __init__(self, error):
        self.error = error

    def call(self, cls, verb, args, **kw):
        raise self.error

    def provider_environment(self, cls, implementation, secrets):
        return {}


def engine(monkeypatch, error):
    monkeypatch.setattr(project_config, "resolver", lambda root: Resolver(error))
    return seams.MediaEngine("/root")


def reason_of(monkeypatch, error, verb="block-params"):
    with pytest.raises(seams.StepServiceError) as refused:
        engine(monkeypatch, error).call("renderer:video", verb, [], 1)
    return refused.value.code, refused.value.reason


def test_the_engine_keeps_the_closed_refusal_line_of_block_params_and_of_no_other_verb(monkeypatch):
    assert "block-params" in seams.MediaEngine.CLASSES["renderer:video"]
    line = "refused: bad_number params.value   value must be a number"
    assert reason_of(monkeypatch, Gone("failed", 1, line)) == ("refused", "bad_number params.value")
    assert reason_of(monkeypatch, Gone("failed", 1, "something else entirely")) == ("refused", "")
    assert reason_of(monkeypatch, Gone("failed", 1, line), verb="check") == ("refused", "")
    assert reason_of(monkeypatch, Gone("usage", 2, line)) == ("refused", "")
    assert reason_of(monkeypatch, Gone("failed", 7, line)) == ("engine_failed", "")


# 9 and 10. the review, the align step and the gate


def fake_checker(world, monkeypatch):
    return use(monkeypatch, Checking(real=world["engine"].call))


def add_edit(world, task, revision=0, **kw):
    return ops_media.captions_edit(world["path"], task, revision, edits=json.dumps([dict(ADD, **kw)]))


def to_run(world, task):
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    return run_task(world, task)


def real_aligns(world):
    return [c for c in world["engine"].of("align") if not flag_of(c["args"], "--out").endswith("proposal.beats.json")]


def flag_of(args, name):
    return args[args.index(name) + 1]


def test_an_animation_is_added_shown_appended_by_align_and_removed_at_the_gate(world, monkeypatch):
    fake = fake_checker(world, monkeypatch)
    task = add(world)
    assert run_task(world, task)["stopped"] == "review"
    done = add_edit(world, task)
    assert done["mode"] == "review" and len(fake.calls) == 1
    held = json.loads(work_file(world, "review.json").read_text())
    assert [(a["id"], a["block"], a["preset"], a["params"], a["from"], a["to"]) for a in held["animations"]] == [
        ("a1", "oh:keyword", "keyword", {"text": "Every step counts"}, 1, 3)]
    shown = ops_media.captions_read(world["path"], task)["view"]
    assert [(a["id"], a["word_from"], a["word_to"], a["lost"]) for a in shown["animations"]] == [("a1", 1, 3, False)] and shown["counts"]["animations"] == 1
    out = to_run(world, task)
    assert out["ok"] is True and out["stopped"] == "deliver"
    beats = json.loads(work_file(world, "beats.json").read_text())
    [overlay] = beats["overlays"]
    assert overlay == {"id": "a1", "beat": 1001, "preset": "keyword", "params": {"text": "Every step counts"}, "block": "oh:keyword", "word_from": 1, "word_to": 3,
                       "score": 1.0}
    state = steps.state_of(steps.kind_of("media"), task_row(world, task)["step_state"])
    assert state["steps"]["align"]["result"]["animations"] == 1 and state["steps"]["align"]["result"]["overlays"] == 1
    assert json.loads(work_file(world, "transcript.edited.json").read_text())["words"][0]["text"] == "Welcome"
    [gate] = open_items(world, task)
    removed = ops_media.captions_edit(world["path"], task, 1, edits=json.dumps([{"op": "animation", "id": "a1", "remove": True}]))
    assert removed["mode"] == "gate" and removed["answered"] == gate["id"]
    world["engine"].salt = b"two"
    assert run_task(world, task)["stopped"] == "deliver"
    assert json.loads(work_file(world, "beats.json").read_text())["overlays"] == []


def test_an_animation_whose_words_were_all_cut_stops_the_align_step_before_the_engine_is_asked(world, monkeypatch):
    fake_checker(world, monkeypatch)
    task = add(world)
    run_task(world, task)
    add_edit(world, task, word_from=2, word_to=3)
    ops_media.captions_edit(world["path"], task, 1, edits=json.dumps([{"op": "delete", "index": 2}, {"op": "delete", "index": 3}]))
    before = len(real_aligns(world))
    out = to_run(world, task)
    assert out["ok"] is False and out["failed"] == "align" and out["code"] == "animation_lost" and out["field"] == "a1"
    assert len(real_aligns(world)) == before


def test_a_refused_parameter_changes_nothing_and_names_the_parameter_not_its_value(world, monkeypatch):
    use(monkeypatch, Checking(error=seams.StepServiceError("refused", "undeclared_param params.size"), real=world["engine"].call))
    task = add(world)
    run_task(world, task)
    with pytest.raises(ops_core.OpsError) as refused:
        add_edit(world, task, params={"text": "Secret words", "size": 3})
    assert str(refused.value) == "refused: undeclared_param edits[0].params.size" and "Secret" not in str(refused.value)
    assert not work_file(world, "review.json").exists()


# 11. the operation


def set_page(world, groups):
    file = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw.pop("channels", None)
    if groups is not None:
        raw["channels"] = {"page": groups}
    file.write_text(json.dumps(raw))
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"], widen=ops.config(world["path"])["widening_sha256"])


def test_video_catalogue_lists_for_the_terminal_and_the_page_and_refuses_the_rest(world, monkeypatch):
    shown = ops_media_catalogue.video_catalogue(world["path"])
    assert shown["engine"] == "hyperframes"      # the class default since V4
    assert {b["name"] for b in shown["blocks"] if b["addable"]} == {"oh:keyword", "oh:list", "oh:number", "oh:quote", "hf:count-up", "hf:spring-pop", "hf:testimonial-card"}
    assert ops_media_catalogue.video_catalogue(world["path"], "terminal") == shown and ops_media_catalogue.video_catalogue(world["path"], "page") == shown
    assert ops.video_catalogue(world["path"]) == shown
    for channel in ("mcp", "messaging", "other"):
        with pytest.raises(ops_core.OpsError) as refused:
            ops_media_catalogue.video_catalogue(world["path"], channel)
        assert refused.value.code == 1
    original = animation.read_catalogue

    def stale_catalogue(root):
        raise animation.CatalogueError("catalogue_stale")
    monkeypatch.setattr(animation, "read_catalogue", stale_catalogue)
    with pytest.raises(ops_core.OpsError) as stale:
        ops_media_catalogue.video_catalogue(world["path"])
    assert "catalogue_stale" in str(stale.value) and stale.value.code == 1
    monkeypatch.setattr(animation, "read_catalogue", original)
    set_page(world, ["read"])
    with pytest.raises(ops_core.OpsError):
        ops_media_catalogue.video_catalogue(world["path"], "page")


# 12. the route


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


def test_the_route_is_a_read_that_crosses_the_lan_socket_as_well_as_the_loopback_one(stand):
    [route] = [r for r in service.ROUTES if r["op"] == "video-catalogue"]
    assert (route["method"], route["pattern"]) == ("GET", "/projects/{p}/video-catalogue") and route["take"] == ()
    assert "video-catalogue" not in operations.LAN_REFUSED_OPS
    stand.fake.answers["video_catalogue"] = {"engine": "ffmpeg", "blocks": []}
    for lan in (False, True):
        host = f"{LAN}:{PORT}" if lan else f"127.0.0.1:{PORT}"
        sent = {"Host": host, "Authorization": f"Bearer {TOKEN}"}
        status, _, payload = service.handle(stand.svc, "GET", f"/api/v1/projects/{stand.projects[0]['id']}/video-catalogue", sent, b"", lan=lan)
        assert status == 200 and json.loads(payload)["engine"] == "ffmpeg", lan
    assert [c[0] for c in stand.fake.calls] == ["video_catalogue", "video_catalogue"]


# 13. the terminal


def test_the_terminal_calls_the_operation(world):
    shown = cli.run(["video-catalogue", "--project", world["path"]])
    assert shown == ops_media_catalogue.video_catalogue(world["path"]) and shown["engine"] == "hyperframes"


# 14. the modules start on their own


@pytest.mark.parametrize("name", ["media_animation.py", "ops_media_catalogue.py"])
def test_the_modules_start_on_their_own(name):
    argv = [sys.executable, "-I", str(RUNTIME / name)]
    flags = ["--help"]
    helped = subprocess.run(argv + flags, capture_output=True, text=True, env={})
    assert helped.returncode == 0 and helped.stdout.strip()
    assert subprocess.run(argv, capture_output=True, text=True, env={}).returncode == 2


# 15. the renderer's own checker, on the host


@pytest.mark.skipif(not (REPO / "providers" / "renderer" / "ffmpeg.py").exists(), reason="the renderer's host verb is not in this checkout")
def test_the_real_checker_accepts_a_declared_parameter_and_refuses_an_undeclared_one(tmp_path):
    ctx = ctx_of(tmp_path)
    animate = animation.checker(ctx)
    done = animate("oh:keyword", {"text": "Every step counts"}, "edits[0]")
    assert done == {"block": "oh:keyword", "preset": "keyword", "params": {"text": "Every step counts"}}
    assert refusal(animate, "oh:keyword", {"text": "x", "size": 3}, "edits[0]") == ("undeclared_param", "edits[0].params.size")
