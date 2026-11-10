"""The transcriber's image, as `build --confirmed` left it, accepted by the provider's own image check. Gated: the test runs only with

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest providers/transcriber/tests/test_transcriber_docker_live.py

after `OPENHORA_STATE_DIR=<folder> python3 providers/transcriber/whispercpp.py build --confirmed`, with the same folder for both (the gate variable is the
renderer job's: one job builds both images). It never builds, and no speech model is downloaded or needed: the
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
# The state folder the build wrote its record into, named by OPENHORA_STATE_DIR. Only that variable is read, at collection: the root
# conftest replaces XDG_STATE_HOME with a temporary folder before this module is imported, so it cannot name the build's folder.
REAL_STATE_DIR = os.environ.get("OPENHORA_STATE_DIR")


def load():
    spec = importlib.util.spec_from_file_location("transcriber_docker_live_test", PROVIDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provider(monkeypatch):
    if not REAL_STATE_DIR:
        pytest.fail("the build and the tests must share one OPENHORA_STATE_DIR: set it to the same folder for %s and for pytest "
                    "(the root conftest replaces XDG_STATE_HOME, so that variable cannot carry it)" % "`OPENHORA_STATE_DIR=<folder> python3 providers/transcriber/whispercpp.py build --confirmed`")
    monkeypatch.setenv("OPENHORA_STATE_DIR", REAL_STATE_DIR)
    return load()


def test_the_image_just_built_is_the_one_the_provider_accepts(provider):
    found = provider.check_image()
    assert found["tag"] == provider.image_tag() and found["id"].startswith("sha256:")
    assert found["definition"] == provider.definition_hash() and found["cpu_flags"] and found["whisper_cpp_commit"]
