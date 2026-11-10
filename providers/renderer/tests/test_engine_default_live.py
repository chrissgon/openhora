"""The class default and the project's renderer key (V4) in real containers: what the runtime's `MediaEngine` does with no renderer named (the class
default, hyperframes), with `ffmpeg` named, for `block-params`, and with the HyperFrames image missing. Never builds, no network, no real recording:
the inputs are the short case of the engine contract (contract_kit), made by the common image's own ffmpeg.

Skipped unless both images' variables are set; the images must be built and recorded first, into the same state folder:

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 WB_HYPERFRAMES_DOCKER_TESTS=1 \\
    uv run --with pytest==9.1.1 pytest -q providers/renderer/tests/test_engine_default_live.py

with no `-n`. The helpers are the engine contract's (`test_engine_contract_live.py`): the lab, the shape check, the cleanliness check (C11).

The seam starts the provider with the resolver's minimum environment (providers/resolve.py `provider_environment`), so a test blocks folder
(RENDERER_TEST, RENDERER_BLOCKS_DIR) never reaches it: the renders here draw with the committed blocks. The reference render of each leg is therefore a
direct call of the host with the same minimum environment, not leg F1 of the contract file (which draws the HyperFrames engine from a test folder).
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
import hyperframes as H
from test_engine_contract_live import (FFMPEG_ON, HF_ON, Lab, Render, assert_clean, check_shape, fresh, host, lab, leftovers, real_state)  # noqa: F401

sys.path.insert(0, str(K.REPO / "runtime"))
import ops_step_seams as seams  # noqa: E402
import media_animation  # noqa: E402

pytestmark = pytest.mark.skipif(not (FFMPEG_ON and HF_ON), reason="real containers: set WB_RENDERER_DOCKER_TESTS=1 and WB_HYPERFRAMES_DOCKER_TESTS=1 (both images built and recorded first)")

ROOT = str(K.REPO)
RENDER_TIMEOUT = 1800
ENGINE_VARIABLES = ("RENDERER_VIDEO_PROVIDER", "RENDERER_PROVIDER")
TEST_VARIABLES = ("RENDERER_TEST", "RENDERER_BLOCKS_DIR")


@pytest.fixture(autouse=True)
def no_choice_in_the_environment(monkeypatch):
    for name in ENGINE_VARIABLES + TEST_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def render_args(lab, out_dir, engine):
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


def shaped(lab, engine, result, doc, out_dir):
    check_shape(lab, engine, Render(0, result, "", 0.0, out_dir, 0.0), doc)
    assert_clean(out_dir, passed=True)


def test_l1_with_no_renderer_named_the_default_engine_is_hyperframes_and_its_render_is_the_hosts(lab):
    lab.need("hyperframes")
    assert media_animation.engine_name(ROOT) == "hyperframes"
    result, doc, out_dir = through_the_seam(lab, None, "auto", "hyperframes")
    shaped(lab, "hyperframes", result, doc, out_dir)
    assert result["engine"] == "hyperframes" and "gate" in result and result["beats_drawn"] > 0
    assert result["gate"]["boxes"] > 0
    reference = directly(lab, "hyperframes", "hyperframes")
    assert result["sha256"] == reference["sha256"], "the seam's render is not the same engine's render of the same inputs"


def test_l2_naming_ffmpeg_renders_the_same_inputs_with_the_other_engine(lab):
    lab.need("hyperframes")
    assert media_animation.engine_name(ROOT, "ffmpeg") == "ffmpeg"
    result, doc, out_dir = through_the_seam(lab, "ffmpeg", "ffmpeg", "ffmpeg")
    shaped(lab, "ffmpeg", result, doc, out_dir)
    assert "gate" not in result
    reference = directly(lab, "ffmpeg", "ffmpeg")
    assert result["sha256"] == reference["sha256"], "the seam's render is not the same engine's render of the same inputs"


def test_l3_block_params_is_answered_by_the_engine_the_project_names_and_refused_by_the_other(tmp_path):
    params = K.write_json(tmp_path / "p.json", {"text": "Every step counts"})
    args = ["--block", "hf:spring-pop", "--params", str(params), "--vocabulary", str(K.VOCABULARY)]
    done = seams.MediaEngine(ROOT, None).call("renderer:video", "block-params", args, 120)
    assert done["ok"] is True and done["engine"] == "hyperframes" and done["block"] == "hf:spring-pop"
    other = seams.MediaEngine(ROOT, "ffmpeg").call("renderer:video", "block-params", ["--block", "oh:keyword", *args[2:]], 120)
    assert other["engine"] == "ffmpeg"
    with pytest.raises(seams.StepServiceError) as wrong_engine:
        seams.MediaEngine(ROOT, "ffmpeg").call("renderer:video", "block-params", args, 120)
    assert wrong_engine.value.code == "refused" and wrong_engine.value.reason == "block_not_on_engine oh:keyword"
    assert leftovers() == []


def test_l4_a_missing_hyperframes_image_is_refused_and_never_replaced_by_the_other_engine(lab, tmp_path, monkeypatch):
    state = os.environ["OPENHORA_STATE_DIR"]
    copy = tmp_path / "state"
    shutil.copytree(state, str(copy))
    record = copy / D.STATE_FOLDER / H.HF_RECORD
    assert record.is_file()
    record.unlink()
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(copy))
    out_dir = lab.folder / "out-default-missing"
    args, doc = render_args(lab, out_dir, "hyperframes")
    with pytest.raises(seams.StepServiceError) as refused:
        seams.MediaEngine(ROOT, None).call("renderer:video", "render", args, RENDER_TIMEOUT)
    assert refused.value.code == "not_configured"
    assert not out_dir.exists() or list(out_dir.iterdir()) == []
    assert leftovers() == []
    result, doc, ffmpeg_out = through_the_seam(lab, "ffmpeg", "ffmpeg-without-hf", "ffmpeg")      # the other engine still renders with that state, when it is named
    shaped(lab, "ffmpeg", result, doc, ffmpeg_out)
