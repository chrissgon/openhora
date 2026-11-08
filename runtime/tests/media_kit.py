"""The kit of the tests of the media step (runtime/step_media.py, runtime/ops_media_edit.py, runtime/ops_step_seams.py MediaStore and MediaEngine): a
fake engine that writes the synthetic output a verb would (JSON files, a render of fixed bytes) into the paths it is given and records each call, a
synthetic transcript, a post with a script, and the world (a project, a data folder, the real store of recordings) the tests share. Not a test file.
No provider is called, no tool is run, and every name is invented.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import standin_tree as st
from media_fixtures import Body, mp4_head

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
ops_step_seams = st.load("ops_step_seams")
ops_step_effects = st.load("ops_step_effects")
media = st.load("media")
steps = st.load("steps")
step_media = st.load("step_media")

KEY = "2027-11-02-aster-lane"
POST = f"docs/marketing/content/{KEY}.md"
WORDS = "Welcome to Aster Lane where every small step counts".split()
RENDER_BLOCKS = {"oh:caption": "a" * 64, "oh:keyword": "b" * 64}


def sha(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def post_text(network="instagram", script=True) -> str:
    lines = ["# Post: Aster Lane", "", "- Owner: mkt-social-copy", "- Status: draft", f"- Network: {network}" if network else "- Format: video", ""]
    if script:
        lines += ["## Script", "", "```script", "beat 1: hook", "Welcome to Aster Lane", "```", ""]
    return "\n".join(lines)


def transcript() -> dict:
    words, t = [], 0.5
    for i, text in enumerate(WORDS):
        words.append({"index": i, "text": text, "start": round(t, 3), "end": round(t + 0.3, 3), "segment": 0})
        t += 0.4
    segments = [{"index": 0, "start": 0.5, "end": words[-1]["end"], "text": " ".join(WORDS), "first_word": 0, "last_word": len(words) - 1}]
    return {"schema_version": 1, "language": "pt", "duration": 8.0, "words": words, "segments": segments, "facts": {"timestamps": "dtw"}}


def flag(args, name):
    return args[args.index(name) + 1] if name in args else None


class FakeEngine:
    """MediaEngine's stand-in: `call(cls, verb, args, timeout)` writes what the verb would into the paths of `args` and returns its result. `salt`
    changes the render's bytes (so another render has another hash), `fail` maps a verb to an exception it raises, `verify_ok` is the verdict."""

    CLASSES = ops_step_seams.MediaEngine.CLASSES

    def __init__(self):
        self.calls, self.salt, self.fail, self.verify_ok = [], b"one", {}, True

    def of(self, verb):
        return [c for c in self.calls if c["verb"] == verb]

    def call(self, cls, verb, args, timeout):
        self.calls.append({"cls": cls, "verb": verb, "args": list(args), "timeout": timeout})
        if verb in self.fail:
            raise self.fail[verb]
        return getattr(self, "_" + verb)(list(args))

    @staticmethod
    def _write(path, data):
        Path(path).write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode("utf-8"))

    def _transcribe(self, a):
        self._write(flag(a, "--out"), transcript())
        return {"ok": True}

    def _analyse(self, a):
        self._write(flag(a, "--out"), {"facts": {"duration": 8.0}, "silences": []})
        return {"ok": True, "duration": 8.0, "silences": 0, "has_audio": True}

    def _still(self, a):
        data = b"\x89PNG\r\n\x1a\nstill"
        name = f"still-{sha(data)[:12]}.png"
        self._write(os.path.join(flag(a, "--out"), name), data)
        return {"ok": True, "name": name, "sha256": sha(data), "at_ms": int(flag(a, "--at-ms"))}

    def _preview(self, a):
        data = b"preview " + self.salt
        digest = sha(data)
        name = f"preview-{digest[:12]}.mp4"
        self._write(os.path.join(flag(a, "--out"), name), data)
        return {"ok": True, "name": name, "path": os.path.join(flag(a, "--out"), name), "sha256": digest, "from_sha256": flag(a, "--sha256"),
                "bytes": len(data), "width": 720, "height": 1280}

    def _base(self, a):
        proposal = flag(a, "--out").endswith("proposal.edl.json")
        doc = {"proposals": [], "normalisation": {}}
        if not proposal:
            doc = {**doc, "words": [{"index": i} for i in range(len(WORDS))], "out_frames": 240, "fps": 30}
        self._write(flag(a, "--out"), doc)
        return {"ok": True, "kept_ranges": 1, "out_seconds": 8.0}

    def _align(self, a):
        if flag(a, "--out").endswith("proposal.beats.json"):
            self._write(flag(a, "--out"), {"report": [{"beat": 1, "preset": "caption", "matched": True}], "slots": []})
        else:
            self._write(flag(a, "--out"), {"overlays": [], "layouts": []})
        return {"ok": True, "beats": 1, "overlays": 0, "layouts": 0, "unmatched": []}

    def _check(self, a):
        return {"ok": True, "out_seconds": 8.0}

    def _render(self, a):
        data = b"the rendered video of Aster Lane " + self.salt
        digest = sha(data)
        path = os.path.join(flag(a, "--out"), f"render-{digest[:12]}.mp4")
        self._write(path, data)
        return {"ok": True, "path": path, "sha256": digest, "bytes": len(data), "verified": True, "output": {"duration": 8.0, "bytes": len(data)},
                "blocks": dict(RENDER_BLOCKS), "blocks_sha256": "c" * 64}

    def _cover(self, a):
        self._write(flag(a, "--out"), b"\x89PNG\r\n\x1a\ncover")
        return {"ok": True}

    def _verify(self, a):
        return {"ok": self.verify_ok}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A project with a post that has a script, a recording in the store and the fake engine in place of the real one."""
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    tree, project = built["tree"], built["project"]
    (tree / "flows").mkdir(exist_ok=True)
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    engine = FakeEngine()
    real_services = ops_step_seams.services
    monkeypatch.setattr(ops_step_seams, "services", lambda ctx: {**real_services(ctx), "media_engine": engine})
    (project / "docs" / "marketing" / "content").mkdir(parents=True)
    (project / POST).write_text(post_text(), encoding="utf-8")
    ops.accept_config(str(project), ops.project_config.load(str(project))["sha256"])
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    data = str(tmp_path / "data")
    record = media.receive(data, Body(64, mp4_head()), 64)
    yield {**built, "path": str(project), "tmp": tmp_path, "engine": engine, "rid": record["id"], "data": data}


def add(world, rid=None, post=POST):
    ctx = ops_core.context(world["path"])
    made = steps.add_task(ctx["store"], ctx["conn"], "media", {"media": rid or world["rid"], "post": post}, key="video", title="Make the video", text="Make it.")
    return made["task"]


def run_task(world, task):
    ctx = ops_core.context(world["path"])
    if ctx["store"].task_get(ctx["conn"], task)["state"] == "failed":
        ctx["store"].task_retry(ctx["conn"], task)
    return ops_steps.run_step(world["path"], task)


def open_items(world, task):
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_list(ctx["conn"], "open", task)


def task_row(world, task):
    ctx = ops_core.context(world["path"])
    return ctx["store"].task_get(ctx["conn"], task)


def to_review(world):
    task = add(world)
    out = run_task(world, task)
    assert out["ok"] is True and out.get("stopped") == "review", out
    return task


def to_gate(world):
    task = to_review(world)
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    out = run_task(world, task)
    assert out["ok"] is True and out.get("stopped") == "deliver", out
    [gate] = open_items(world, task)
    return task, gate


def work_file(world, name):
    return Path(media.folder_of(world["data"], world["rid"])) / name
