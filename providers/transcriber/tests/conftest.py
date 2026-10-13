"""Every test of this suite reaches no network but loopback: the guard of providers/loopback_only.py."""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("providers_loopback_only",
                                               Path(__file__).resolve().parents[2] / "loopback_only.py")
loopback_only = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loopback_only)


@pytest.fixture(scope="session")
def _loopback_site(tmp_path_factory):
    return loopback_only.write_site(str(tmp_path_factory.mktemp("loopback_site")))


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch, _loopback_site):
    loopback_only.guard(monkeypatch, _loopback_site)


# --- the transcriber's own fixtures ----------------------------------------------------------------------------------

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcriber_kit as kit  # noqa: E402


@pytest.fixture
def provider():
    return kit.load_provider()


@pytest.fixture
def world(tmp_path, monkeypatch, provider):
    """A fake docker first on PATH, a private state folder, a models folder with one fictional model, a models.json that
    pins it, and an input file. Nothing outside tmp_path is read or written."""
    fake = kit.Fake(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{fake.folder}{os.pathsep}{os.environ['PATH']}")
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    models = tmp_path / "models"
    models.mkdir(mode=0o700)
    weights = b"fictional model weights"
    (models / "ggml-demo.bin").write_bytes(weights)
    pins = tmp_path / "models.json"
    pins.write_text(json.dumps({"schema_version": 1, "models": [
        {"name": "demo", "file": "ggml-demo.bin", "sha256": hashlib.sha256(weights).hexdigest(), "size": len(weights),
         "dtw_preset": "small", "memory_mb": 1536, "url": "https://example.invalid/ggml-demo.bin"},
        {"name": "later", "file": "ggml-later.bin", "sha256": None, "size": 1, "dtw_preset": "medium", "memory_mb": 2048,
         "url": "https://example.invalid/ggml-later.bin"}]}))
    monkeypatch.setattr(provider, "MODELS_FILE", str(pins))
    audio = tmp_path / "talk.mp4"
    audio.write_bytes(b"\x00\x00\x00\x18ftypmp42 fictional recording")
    ns = type("World", (), {})()
    ns.fake, ns.state, ns.models, ns.pins, ns.input, ns.tmp, ns.provider = fake, state, models, pins, audio, tmp_path, provider
    ns.out = tmp_path / "out" / "transcript.json"
    ns.out.parent.mkdir()
    return ns
