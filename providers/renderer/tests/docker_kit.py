"""A fake docker, a state folder and a way to run the provider's host side against them."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import renderer_kit as K
import _docker as D

FAKE = Path(__file__).resolve().parent / "fake_docker.py"


class World:
    def __init__(self, tmp: Path, image=True, **cfg):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.config = tmp / "dockerconfig"
        self.state = tmp / "state"
        self.bin.mkdir()
        self.config.mkdir()
        self.state.mkdir(mode=0o700)
        fake = self.bin / "docker"
        fake.write_text("#!%s\n" % sys.executable + FAKE.read_text().split("\n", 1)[1])
        fake.chmod(0o755)
        self.cfg = {"inner": str(K.SCRIPT), "browser": K.BROWSER, "images": {}}
        if not (K.HAVE_FFMPEG and K.BROWSER):
            # The container's self-check needs ffmpeg and a browser; the host side under test needs neither, so a machine without them
            # (a CI runner) is given the answer the image would give.
            self.cfg["selfcheck"] = {"ok": True, "ffmpeg": "ffmpeg version fake", "ffprobe": "ffprobe version fake", "missing": [], "python": "3.11.2",
                                     "browser": "HeadlessChrome/fake", "libass": True, "container": False, "templates": ["caption.html"]}
        self.cfg.update(cfg)
        if image:
            self.install_image()
        self.save()

    def install_image(self, definition=None):
        self.cfg["images"][D.image_tag()] = {"Id": "sha256:" + "cd" * 32, "Labels": {D.LABEL_DEFINITION: definition or D.definition_hash(),
                                                                                       "org.openhora.chrome.version": "155.0.8059.39"}}
        own = self.state / "renderer"
        own.mkdir(mode=0o700, exist_ok=True)
        (own / "image.json").write_text(json.dumps({"image_tag": D.image_tag(), "image_id": "sha256:" + "cd" * 32}))

    def save(self):
        (self.config / "fake.json").write_text(json.dumps(self.cfg))

    def calls(self):
        path = self.config / "calls.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def runs(self):
        return [c for c in self.calls() if c["argv"][:1] == ["run"]]

    def env(self, **extra):
        e = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.tmp / "home"), "DOCKER_CONFIG": str(self.config),
             "OPENHORA_STATE_DIR": str(self.state)}
        e.update(extra)
        return e

    def host(self, *args, env=None, timeout=300):
        done = subprocess.run([sys.executable, str(K.HOST), *map(str, args)], capture_output=True, text=True, env={**self.env(), **(env or {})}, timeout=timeout)
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stderr
