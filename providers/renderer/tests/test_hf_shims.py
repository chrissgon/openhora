"""The five shims the HyperFrames pages are served with (PF-a1): committed byte for byte from the pinned source, the fps literal of
`render_mode.js` made a placeholder."""
from __future__ import annotations

import hashlib

import renderer_kit as K

SHIMS = K.RENDERER / "hf-runtime" / "shims"
NAMES = ("early_stub", "capture_mode_shim", "virtual_time_shim", "render_mode", "bridge")
RENDER_MODE_AT_30 = "839db3cde97f9eda653b6db008bf38f746df7bc69aed42c7c2203dba4c6f57ae"


def sums():
    out = {}
    for line in (SHIMS / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        out[name.strip()] = digest
    return out


def test_sha256sums_matches_every_shim_and_lists_only_them():
    assert sorted(sums()) == sorted(n + ".js" for n in NAMES)
    for name, digest in sums().items():
        assert hashlib.sha256((SHIMS / name).read_bytes()).hexdigest() == digest, name
    assert sums()["early_stub.js"] == "ebf19aa17f8bda8a50d3513836828c7cd5f6a1df4cd42d9ea435ad738448fd39"
    assert sums()["bridge.js"] == "8d63f991f2a7c7a6a1d4806cd5e03468cb20aa25bef3473ca92dc49739719d9b"


def test_render_mode_with_the_placeholder_filled_with_30_is_the_upstream_file():
    text = (SHIMS / "render_mode.js").read_text(encoding="utf-8")
    assert text.count("__OH_FPS__") == 1 and "var __renderFps = __OH_FPS__;" in text
    assert hashlib.sha256(text.replace("__OH_FPS__", "30").encode()).hexdigest() == RENDER_MODE_AT_30
