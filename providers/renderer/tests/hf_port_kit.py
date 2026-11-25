"""The kit of the tests of our own ports under the second contract (PF-a4): two FICTIONAL tier-B fragments written for the tests (a badge for the card band and a
caption line; nothing copied from a port or from the registry), the blocks folder that carries them with a recorded determinism test, and a stand-in runtime
whose seek drives the timeline `oh-port` the host page registers. Not a test file. Standard library only."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import renderer_kit as K
import hf_second_kit as H
import _blocks
import _hf_host
import _hf_port

CARD = "hf:oh-test-badge"
CAPTION = "hf:oh-test-line"
COMMIT = "c" * 40
NOTICE = "Apache-2.0; a fictional fragment written for the tests; notices in providers/renderer/hf-runtime/NOTICE.md"

CARD_FRAGMENT = """<!-- hf:oh-test-badge: a fictional badge for the tests only. -->
<template data-hf-block="hf:oh-test-badge">
  <style>
    .stage { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; }
    .badge { padding: 10px 22px; border-radius: 12px; background: var(--c-accent); color: var(--c-text); font-family: var(--font-display); font-size: 48px; opacity: 0; will-change: opacity; %(extra)s }
  </style>
  <div class="stage"><div class="badge"></div></div>
  <script data-hf-build>
    function build(root, tl, data, ctx) {
      var badge = root.querySelector(".badge");
      badge.textContent = String(data.params.text);
      tl.fromTo(badge, { opacity: 0 }, { opacity: 1, duration: 0.2 }, 0);
    }
  </script>
</template>
"""

CAPTION_FRAGMENT = """<!-- hf:oh-test-line: a fictional caption line for the tests only. -->
<template data-hf-block="hf:oh-test-line">
  <style>
    .stage { position: absolute; inset: 0 0 44px 0; display: flex; align-items: flex-end; justify-content: center; pointer-events: none; }
    .line { display: flex; gap: 12px; font-family: var(--font-display); font-size: 56px; color: var(--c-text); opacity: 0; will-change: opacity; %(extra)s }
    .word { display: inline-block; }
  </style>
  <div class="stage"><div class="line"><span class="word"></span></div></div>
  <script data-hf-build>
    function build(root, tl, data, ctx) {
      var line = root.querySelector(".line");
      var proto = root.querySelector(".word");
      var made = proto.cloneNode(true);
      proto.remove();
      data.words.forEach(function (w) {
        var el = made.cloneNode(true);
        el.textContent = w.text;
        line.appendChild(el);
      });
      tl.fromTo(line, { opacity: 0 }, { opacity: 1, duration: 0.1 }, 0);
    }
  </script>
</template>
"""


def fragment(kind: str = "card", extra: str = "") -> str:
    return (CARD_FRAGMENT if kind == "card" else CAPTION_FRAGMENT) % {"extra": extra}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def block_doc(kind: str = "card", **over) -> dict:
    if kind == "card":
        doc = {"schema_version": 1, "name": CARD, "kind": "overlay", "preset": "keyword", "band": "card", "may_cross_face": False, "license": ["Apache-2.0"],
               "source": "hyperframes-registry", "use_when": "a fictional badge for one short phrase, used by the tests only",
               "params": {"text": {"type": "text", "max": 24, "required": True}}, "samples": [{"text": "Name every dollar"}], "natural_duration": 1.0,
               "implementations": {"gsap": "gsap.html"}, "tier": "B", "commit": COMMIT, "notice": NOTICE}
    else:
        doc = {"schema_version": 1, "name": CAPTION, "kind": "caption", "preset": "caption", "band": "caption", "may_cross_face": False, "license": ["Apache-2.0"],
               "source": "hyperframes-registry", "use_when": "a fictional caption line under the face, used by the tests only", "params": {}, "samples": [{}],
               "natural_duration": None, "implementations": {"gsap": "gsap.html"}, "tier": "B", "commit": COMMIT, "notice": NOTICE}
    doc.update(over)
    return doc


def record(served: str, runtime_sha256: str, **over) -> dict:
    rec = {"served_sha256": served, "runtime_sha256": runtime_sha256, "samples": 3, "frames": 90, "runs": 4, "blocked": 0, "date": "2026-11-24", "image": "openhora-renderer:test",
           "seconds": 1.5}
    rec.update(over)
    return rec


def port_runtime(monkeypatch, tmp) -> dict:
    """The stand-in runtime of `hf_second_kit`, with a seek that drives the timeline `oh-port` (the page of a port registers that one)."""
    monkeypatch.setattr(H, "FAKE_RUNTIME", H.FAKE_RUNTIME.replace('window.__timelines["oh-test-pop"]', 'window.__timelines["oh-port"]'))
    return H.write_runtime(tmp)


def blocks_folder(tmp, kinds=("card",), runtime_sha256=None, extra="", name="blocks", engine_presets=True) -> str:
    """A copy of the committed blocks with the fictional ports added (a recorded determinism test when `runtime_sha256` is given), the ffmpeg engine drawing the
    keyword and/or caption preset with them, pinned again. Returns the folder."""
    folder = Path(tmp) / name
    shutil.copytree(K.BLOCKS, folder)
    eng_path = folder / "engines" / "ffmpeg.json"
    eng = json.loads(eng_path.read_text())
    eng["runtimes"] = ["renderat", "hf", "gsap"]
    for kind in kinds:
        text = fragment(kind, extra).encode("utf-8")
        doc = block_doc(kind)
        short = doc["name"].split(":")[1]
        (folder / "hf" / short).mkdir(parents=True)
        (folder / "hf" / short / "gsap.html").write_bytes(text)
        if runtime_sha256:
            doc["determinism"] = record(_hf_port.served_digest(text), runtime_sha256)
        (folder / "hf" / short / "block.json").write_text(json.dumps(doc, indent=1) + "\n")
        if engine_presets:
            eng["presets"][doc["preset"]] = doc["name"]
    eng_path.write_text(json.dumps(eng, indent=1))
    _blocks.write_pins(str(folder))
    return str(folder)


def runtime_hash(rt: dict, browser_version: str = "Chrome/1.0", fps: int = 30) -> str:
    return _hf_host.load_runtime(rt["vendor"], rt["runtime_dir"] + "/shims", fps, browser_version)["runtime_sha256"]
