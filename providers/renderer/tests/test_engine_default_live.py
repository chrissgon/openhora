"""The class default and the project's renderer key (V4, PF-b) in a real container: what the runtime's `MediaEngine` does with no renderer named (the
class default, ffmpeg), with the retired name `hyperframes` named (read as ffmpeg), for `block-params`, and with the ffmpeg image missing. Never builds, no
network, no real recording: the inputs are the short case of the engine contract (contract_kit), made by the common image's own ffmpeg.

Skipped unless the variable is set; the image must be built and recorded first, into the state folder:

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 \\
    uv run --with pytest==9.1.1 pytest -q providers/renderer/tests/test_engine_default_live.py

with no `-n`. The helpers are the engine contract's (`test_engine_contract_live.py`): the lab, the shape check, the cleanliness check (C11).

The seam starts the provider with the resolver's minimum environment (providers/resolve.py `provider_environment`), so a test blocks folder
(RENDERER_TEST, RENDERER_BLOCKS_DIR) never reaches it: the renders here draw with the committed blocks. The reference render of each leg is therefore a
direct call of the host with the same minimum environment, not leg F1 of the contract file (which draws from a test folder).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import renderer_kit as K
import _docker as D
from test_engine_contract_live import (FFMPEG_ON, Lab, Render, assert_clean, check_shape, fresh, host, lab, leftovers, real_state)  # noqa: F401

sys.path.insert(0, str(K.REPO / "runtime"))
import ops_step_seams as seams  # noqa: E402
import media_animation  # noqa: E402

pytestmark = pytest.mark.skipif(not FFMPEG_ON, reason="real container: set WB_RENDERER_DOCKER_TESTS=1 (the image built and recorded first)")

ROOT = str(K.REPO)
RENDER_TIMEOUT = 1800
ENGINE_VARIABLES = ("RENDERER_VIDEO_PROVIDER", "RENDERER_PROVIDER")
TEST_VARIABLES = ("RENDERER_TEST", "RENDERER_BLOCKS_DIR")


@pytest.fixture(autouse=True)
def no_choice_in_the_environment(monkeypatch):
    for name in ENGINE_VARIABLES + TEST_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def render_args(lab, out_dir, engine="ffmpeg"):
    rec, edl, beats, doc = lab.short()
    args = ["--edl", edl, "--beats", beats, "--in", rec, "--out", out_dir, "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY,
            "--cpus", 4, "--cpuset", "0-3"]
    if engine == "ffmpeg":
        args += ["--jobs", 2]
    return [str(a) for a in args], doc


def through_the_seam(lab, renderer, tag, engine):
    """One render of the F1 inputs through MediaEngine(ROOT, renderer): (the result, the edit list, the out folder)."""
    out_dir = lab.folder / ("out-default-" + tag)
    args, doc = render_args(lab, out_dir, engine)
    return seams.MediaEngine(ROOT, renderer).call("renderer:video", "render", args, RENDER_TIMEOUT), doc, out_dir


def directly(lab, tag, engine):
    """The reference: the same render by the engine's host with the provider environment the seam gives (no test blocks), as a person would run it."""
    out_dir = lab.folder / ("out-direct-" + tag)
    args, doc = render_args(lab, out_dir, engine)
    env = {k: v for k, v in os.environ.items() if k not in TEST_VARIABLES}
    rc, out, err = host(engine, "render", *args, timeout=RENDER_TIMEOUT, env=env)
    assert rc == 0, (out, err[-2000:])
    assert_clean(out_dir, passed=True)
    return out


def resolved(implementation):
    """The resolver's answer for the renderer the seam starts, with the environment MediaEngine passes."""
    r = seams.project_config.resolver(ROOT)
    return r.resolve("renderer:video", root=ROOT, env=r.provider_environment("renderer:video", None, ()), implementation=implementation)


def shaped(lab, engine, result, doc, out_dir):
    check_shape(lab, engine, Render(0, result, "", 0.0, out_dir, 0.0), doc)
    assert_clean(out_dir, passed=True)


def test_l1_with_no_renderer_named_the_engine_is_ffmpeg_and_its_render_is_the_hosts(lab):
    assert media_animation.engine_name(ROOT) == "ffmpeg"
    result, doc, out_dir = through_the_seam(lab, None, "auto", "ffmpeg")
    shaped(lab, "ffmpeg", result, doc, out_dir)
    chosen = resolved(None)       # the render result carries no engine key: the engine is the provider script the resolver gave the seam
    assert chosen["implementation"] == "ffmpeg" and chosen["path"].endswith("providers/renderer/ffmpeg.py") and "retired" not in chosen
    assert "gate" not in result
    reference = directly(lab, "ffmpeg", "ffmpeg")
    assert result["sha256"] == reference["sha256"], "the seam's render is not the same engine's render of the same inputs"


def test_l2_naming_hyperframes_renders_with_ffmpeg_the_same_sha256_as_l1(lab):
    assert media_animation.engine_name(ROOT, "hyperframes") == "ffmpeg"      # the retired name is read as its successor (PF-b)
    named, doc, named_out = through_the_seam(lab, "hyperframes", "hyperframes-named", "ffmpeg")
    shaped(lab, "ffmpeg", named, doc, named_out)
    chosen = resolved("hyperframes")
    assert chosen["implementation"] == "ffmpeg" and chosen["path"].endswith("providers/renderer/ffmpeg.py") and chosen["retired"] == "hyperframes"
    default, _, _ = through_the_seam(lab, None, "auto-again", "ffmpeg")
    assert named["sha256"] == default["sha256"], "the retired name did not draw what the default draws"


def test_l3_block_params_is_answered_by_ffmpeg_for_a_project_naming_hyperframes(tmp_path):
    params = K.write_json(tmp_path / "p.json", {"text": "Every step counts"})
    args = ["--block", "hf:spring-pop", "--params", str(params), "--vocabulary", str(K.VOCABULARY)]
    done = seams.MediaEngine(ROOT, "hyperframes").call("renderer:video", "block-params", args, 120)
    assert done["ok"] is True and done["engine"] == "ffmpeg" and done["block"] == "hf:spring-pop"
    other = seams.MediaEngine(ROOT, "ffmpeg").call("renderer:video", "block-params", ["--block", "oh:keyword", *args[2:]], 120)
    assert other["engine"] == "ffmpeg"
    # the refusal of a port with no record is proved by f7d of test_engine_contract_live (a planted blocks folder, which block-params does not read) and offline by test_hf_ports
    assert leftovers() == []


def test_l4_a_missing_ffmpeg_image_is_refused_not_configured(lab, tmp_path, monkeypatch):
    state = os.environ["OPENHORA_STATE_DIR"]
    copy = tmp_path / "state"
    shutil.copytree(state, str(copy))
    record = copy / D.STATE_FOLDER / D.BUILD_RECORD
    assert record.is_file()
    record.unlink()
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(copy))
    out_dir = lab.folder / "out-default-missing"
    args, doc = render_args(lab, out_dir)
    with pytest.raises(seams.StepServiceError) as refused:
        seams.MediaEngine(ROOT, None).call("renderer:video", "render", args, RENDER_TIMEOUT)
    assert refused.value.code == "not_configured"      # there is no other engine to replace it with (PF-b)
    assert not out_dir.exists() or list(out_dir.iterdir()) == []
    assert leftovers() == []
