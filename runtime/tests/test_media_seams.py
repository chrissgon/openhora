"""Tests of the two seams of the media step (runtime/ops_step_seams.py `MediaStore` and `MediaEngine`, package V1b1-4): the engine's closed list of verbs and
its mapping of the resolver's failures, the store's names, references and platform files, and the services of a task. The resolver is a fake and the store of
recordings is the real one over a temporary folder; nothing is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_seams.py
"""
from __future__ import annotations

import types

import pytest

import standin_tree as st
from media_fixtures import Body, mp4_head

seams = st.load("ops_step_seams")
media = st.load("media")
project_config = st.load("project_config")
step_media = st.load("step_media")


class Gone(Exception):
    """ProviderCallError's stand-in."""

    def __init__(self, kind, exit_code=None):
        super().__init__(kind)
        self.kind, self.exit_code, self.reason = kind, exit_code, "x"


class Resolver:
    ProviderCallError = Gone

    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result if result is not None else {"ok": True}, error, []

    def call(self, cls, verb, args, **kw):
        self.calls.append((cls, verb, args, kw))
        if self.error:
            raise self.error
        return self.result

    def provider_environment(self, cls, implementation, secrets):
        return {"cls": cls}


def engine(monkeypatch, resolver):
    monkeypatch.setattr(project_config, "resolver", lambda root: resolver)
    return seams.MediaEngine("/root")


def test_the_engine_reaches_only_the_closed_verbs_of_the_two_classes_and_passes_no_implementation_unless_the_project_names_a_renderer(monkeypatch):
    resolver = Resolver()
    eng = engine(monkeypatch, resolver)
    assert seams.MediaEngine.CLASSES == {"transcriber:speech": ("transcribe",),
                                         "renderer:video": ("analyse", "base", "align", "check", "render", "cover", "still", "preview", "verify", "block-params")}
    assert eng.call("renderer:video", "render", ["--edl", "e"], 9) == {"ok": True}
    cls, verb, args, kw = resolver.calls[0]
    assert (cls, verb, args) == ("renderer:video", "render", ["--edl", "e"]) and "implementation" not in kw and kw["timeout"] == 9 and kw["root"] == "/root"
    for cls, verb in (("renderer:video", "build"), ("renderer:video", "pin-browser"), ("transcriber:speech", "models"), ("sender:email", "send"),
                      ("renderer:video", "transcribe")):
        with pytest.raises(seams.StepServiceError) as refused:
            eng.call(cls, verb, [], 1)
        assert refused.value.code == "refused"
    assert len(resolver.calls) == 1


def test_a_named_renderer_is_the_implementation_of_the_renderer_class_alone(monkeypatch):
    resolver = Resolver()
    monkeypatch.setattr(project_config, "resolver", lambda root: resolver)
    eng = seams.MediaEngine("/root", "ffmpeg")
    eng.call("renderer:video", "check", [], 1)
    eng.call("transcriber:speech", "transcribe", [], 1)
    assert resolver.calls[0][3]["implementation"] == "ffmpeg"
    assert "implementation" not in resolver.calls[1][3]


@pytest.mark.parametrize("error, code", [(Gone("not-configured"), "not_configured"), (Gone("usage", 2), "refused"), (Gone("failed", 1), "refused"),
                                         (Gone("failed", 7), "engine_failed"), (Gone("timeout"), "engine_failed")])
def test_the_engine_maps_each_failure_of_the_resolver_to_a_closed_code_and_keeps_no_reason(monkeypatch, error, code):
    with pytest.raises(seams.StepServiceError) as refused:
        engine(monkeypatch, Resolver(error=error)).call("renderer:video", "check", [], 1)
    assert refused.value.code == code and refused.value.reason == ""


def test_a_result_that_is_not_a_dict_is_an_engine_failure(monkeypatch):
    with pytest.raises(seams.StepServiceError) as refused:
        engine(monkeypatch, Resolver(result=["x"])).call("renderer:video", "check", [], 1)
    assert refused.value.code == "engine_failed"


@pytest.fixture
def store(tmp_path):
    ctx = {"cfg": {"data_dir": str(tmp_path / "data"), "project": str(tmp_path)}, "store": types.SimpleNamespace(), "conn": None}
    record = media.receive(ctx["cfg"]["data_dir"], Body(64, mp4_head()), 64)
    return seams.MediaStore(ctx), record["id"]


def test_reference_takes_only_the_closed_tuple_and_the_checker_and_the_platform_files_are_files_of_the_workbench(store):
    media_store, rid = store
    assert media_store.reference("shared/references/video-presets.json").endswith("shared/references/video-presets.json")
    for rel in ("shared/references/platforms/tiktok.json", "../x", "/etc/passwd", "skills/mkt-social-copy/scripts/check_script.py"):
        with pytest.raises(seams.StepServiceError) as refused:
            media_store.reference(rel)
        assert refused.value.code == "refused"
    assert media_store.checker().endswith("skills/mkt-social-copy/scripts/check_script.py")
    assert "video" in media_store.platform_file("instagram") and "video" not in media_store.platform_file("linkedin")
    assert media_store.platform_path("tiktok").endswith("shared/references/platforms/tiktok.json")


@pytest.mark.parametrize("name", ["../x", "a/b", "", "UP", "x" * 40, ".hidden", None, 3])
def test_platform_file_refuses_a_name_that_is_not_a_platforms_and_a_missing_one_is_not_found(store, name):
    with pytest.raises(seams.StepServiceError) as refused:
        store[0].platform_file(name)
    assert refused.value.code == "not_found"
    with pytest.raises(seams.StepServiceError):
        store[0].platform_file("nowhere")


def test_the_store_gives_work_paths_by_closed_names_reads_writes_and_removes_and_a_media_error_keeps_its_code(store):
    media_store, rid = store
    assert media_store.raw(rid).endswith("raw.mp4") and media_store.folder(rid).endswith(rid)
    with pytest.raises(seams.StepServiceError) as refused:
        media_store.path(rid, "../../etc/passwd")
    assert refused.value.code == "usage"
    with pytest.raises(seams.StepServiceError) as missing:
        media_store.read(rid, "transcript.json")
    assert missing.value.code == "not_found"
    media_store.write(rid, "transcript.json", b"{}")
    assert media_store.read(rid, "transcript.json") == b"{}" and media_store.sha256(rid, "transcript.json")
    media_store.write(rid, "edl.json", b"{}")
    assert media_store.remove(rid, ["transcript.json"]) == 1 and media_store.remove(rid, ["edl.json", "beats.json"]) == 1


def test_remove_compiles_the_three_pattern_strings_the_kind_names_and_only_those(store):
    media_store, rid = store
    assert (step_media.STILL_PATTERN, step_media.RENDER_PATTERN, step_media.COVER_PATTERN) == (media.STILL.pattern, media.RENDER.pattern, media.COVER.pattern)
    for name in ("still-0123456789ab.png", "render-0123456789ab.mp4", "cover-0123456789ab.png"):
        with open(media_store.path(rid, name, must_exist=False), "wb") as f:
            f.write(b"x")
    assert media_store.remove(rid, [step_media.STILL_PATTERN]) == 1 and media_store.remove(rid, [step_media.RENDER_PATTERN, step_media.COVER_PATTERN]) == 2
    with pytest.raises(seams.StepServiceError):
        media_store.remove(rid, [r".*"])


def test_settle_cover_names_a_cover_by_the_hash_of_its_bytes(store):
    media_store, rid = store
    with open(media_store.path(rid, "cover-0123456789ab.png", must_exist=False), "wb") as f:
        f.write(b"png bytes")
    final = media_store.settle_cover(rid, "cover-0123456789ab.png")
    assert final == f"cover-{media.sha256_of(media_store.path(rid, final))[:12]}.png" and final != "cover-0123456789ab.png"
    assert media_store.settle_cover(rid, final) == final


def test_setting_reads_the_projects_media_keys_and_nothing_else_and_none_when_the_project_names_none(store, tmp_path):
    media_store, rid = store
    assert media_store.setting("language") is None and media_store.setting("transcriber_model") is None
    named = seams.MediaStore({"cfg": {"data_dir": str(tmp_path), "media": {"language": "en", "other": 1}}, "store": None, "conn": None})
    assert named.setting("language") == "en" and named.setting("other") is None and named.setting("transcriber_model") is None


def test_services_of_a_task_holds_both_media_keys(tmp_path, monkeypatch):
    ctx = {"cfg": {"data_dir": str(tmp_path), "project": str(tmp_path)}, "store": None, "conn": None, "root": str(tmp_path)}
    found = seams.services(ctx)
    assert isinstance(found["media_store"], seams.MediaStore) and isinstance(found["media_engine"], seams.MediaEngine)
