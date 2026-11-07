"""The transcriber's image, as `build --confirmed` left it, accepted by the provider's own image check. Gated: the test runs only with

    WB_RENDERER_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest providers/transcriber/tests/test_transcriber_docker_live.py

(the variable is the renderer job's: one job builds both images). It never builds, and no speech model is downloaded or needed: the
check that is made is the image's, not a transcription. A person's own `--check` exits 3 until a model is placed in the models folder, and
the reason it gives names the model, never the image.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("WB_RENDERER_DOCKER_TESTS") != "1",
                                reason="a real image: set WB_RENDERER_DOCKER_TESTS=1 (the transcriber image must be built first)")

HERE = Path(__file__).resolve().parent
PROVIDER = HERE.parent / "whispercpp.py"
# The state folder the build wrote its record into. The suite's guard points these two at a fresh folder for each test, so they are read
# here, at collection, before any test has run.
REAL_STATE = {name: os.environ.get(name) for name in ("OPENHORA_STATE_DIR", "XDG_STATE_HOME")}


def load():
    spec = importlib.util.spec_from_file_location("transcriber_docker_live_test", PROVIDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provider(monkeypatch):
    for name, value in REAL_STATE.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return load()


def test_the_image_just_built_is_the_one_the_provider_accepts(provider):
    found = provider.check_image()
    assert found["tag"] == provider.image_tag() and found["id"].startswith("sha256:")
    assert found["definition"] == provider.definition_hash() and found["cpu_flags"] and found["whisper_cpp_commit"]
