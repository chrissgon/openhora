"""The step kind `ingest` (P5) on a Google Drive source (P7): an ingest with only a source id is a refresh, and for a Drive source that is
the version-first refresh of `source-refresh` (the provider's `stat`, then a read only when the file moved). The provider is a stand-in
function here (the real one, against the stand-in service, is tested in test_sources_drive.py). On the stand-in tree of standin_tree.py.
Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_ingest_drive.py
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

import standin_tree as st
from sources_fixture import standin_convert

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
sources = st.load("sources")
steps = st.load("steps")

FILE_ID = "1DocAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


class FakeDrive:
    """The Drive provider as the runtime calls it: stat and read of one file, with a version that moves when the text does."""

    def __init__(self):
        self.text, self.version, self.calls = "# Weekly notes\n\nOne.\n", 1, []

    def edit(self, text):
        self.text, self.version = text, self.version + 1

    def __call__(self, cfg, verb, args, *, call=None, timeout=0):
        self.calls.append(verb)
        version = f"{self.version}@2026-10-15T09:00:00.000Z"
        if verb == "stat":
            return {"id": FILE_ID, "name": "Weekly notes", "mime_type": "application/vnd.google-apps.document", "version": version,
                    "archived": False, "supported": True, "reason": ""}
        data = self.text.encode()
        Path(args[args.index("--out-dir") + 1], "content").write_bytes(data)
        return {"id": FILE_ID, "name": "Weekly notes", "mime_type": "application/vnd.google-apps.document", "version": version,
                "content": "markdown", "exported_as": "text/markdown", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "file": "content", "as_source": True}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    built["drive"] = FakeDrive()
    monkeypatch.setattr(sources, "drive_call", built["drive"])
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    built["path"] = project
    return built


def ingest(world, key, source="notes"):
    ctx = ops_core.context(world["path"])
    return steps.add_task(ctx["store"], ctx["conn"], "ingest", {"source": source}, key=key, title="Refresh the notes", text="Refresh the notes.")


def result_of(world, made):
    ctx = ops_core.context(world["path"])
    return ctx["store"].task_get(ctx["conn"], made["task"])["step_state"]["steps"]["ingest"]["result"]


def test_an_ingest_with_only_a_source_id_refreshes_a_drive_source_version_first(world):
    ctx = ops_core.context(world["path"])
    sources.register(ctx, "notes", "drive", FILE_ID, "Weekly notes")
    drive = world["drive"]

    first = ingest(world, "first")
    out = ops.run_step(world["path"], first["task"])
    assert out["ok"] is True and out["task_state"] == "done", out
    assert result_of(world, first) == {"source": "notes", "version": 1, "made": True, "unchanged": False}
    assert drive.calls == ["stat", "read"]
    assert (Path(ctx["cfg"]["sources_dir"]) / "notes" / "1" / "converted.md").read_text() == drive.text

    quiet = ingest(world, "quiet")
    assert ops.run_step(world["path"], quiet["task"])["ok"] is True
    assert result_of(world, quiet) == {"source": "notes", "version": 1, "made": False, "unchanged": True}
    assert drive.calls == ["stat", "read", "stat"], "Drive's version matched: nothing was read"

    drive.edit("# Weekly notes\n\nOne.\n\nTwo.\n")
    moved = ingest(world, "moved")
    assert ops.run_step(world["path"], moved["task"])["ok"] is True
    assert result_of(world, moved) == {"source": "notes", "version": 2, "made": True, "unchanged": False}
    assert drive.calls[-2:] == ["stat", "read"]
    row = ctx["store"].source_latest(ctx["conn"], "notes")
    assert row["label"] == "refresh" and row["origin_version"].startswith("2@")


def test_an_ingest_of_a_drive_source_cannot_be_given_a_file_or_an_address(world):
    ctx = ops_core.context(world["path"])
    sources.register(ctx, "notes", "drive", FILE_ID)
    made = steps.add_task(ctx["store"], ctx["conn"], "ingest", {"source": "notes", "url": "https://www.notion.so/" + "a" * 32}, key="x",
                          title="X", text="X.")
    out = ops.run_step(world["path"], made["task"])
    assert out["ok"] is False and out["code"] == "usage"
    assert world["drive"].calls == [], "the wrong kind of source is refused before Drive is asked"
