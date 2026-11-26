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


# Since M2 (PF-a4f) the committed ffmpeg engine draws caption, keyword, number and quote with the ports, which need the image's gsap runtime and a
# recorded determinism test at the image's hashes. The offline tests that are not about the ports draw with a copy of the committed blocks whose
# ffmpeg engine names the `oh:` pages (renderer_kit.oh_blocks); these modules test the committed defaults themselves and keep the committed folder.
COMMITTED_DEFAULTS = {"test_hf_ports", "test_renderer_blocks", "test_engine_default_live", "test_engine_contract_live", "test_engine_contract",
                      "test_hf_port_catalogue", "test_admit_port", "test_hf_port_render", "test_hf_port", "test_ffmpeg_admit_verb"}


@pytest.fixture(autouse=True)
def _oh_defaults(request, monkeypatch):
    if request.module.__name__.split(".")[-1] in COMMITTED_DEFAULTS:
        yield
        return
    import renderer_kit as K
    import _blocks
    folder = K.oh_blocks()
    monkeypatch.setattr(_blocks, "BLOCKS_DIR", folder)
    monkeypatch.setenv("RENDERER_TEST", "1")
    monkeypatch.setenv("RENDERER_BLOCKS_DIR", folder)
    yield
