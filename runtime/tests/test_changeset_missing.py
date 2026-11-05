"""A run folder of an open request that is gone is an explicit error, never a silent fallback (package P-OPS, review of retention): the
earlier work of a request lives in the change sets of its runs' folders, and skipping a missing one would start the next code task
without it.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_changeset_missing.py
"""
from __future__ import annotations

import subprocess
import sys

import pytest

import standin_tree as st

changeset = st.load("changeset")
ops = st.load("ops")
ops_task_run = st.load("ops_task_run")


def test_a_missing_run_folder_is_an_error_not_a_skip(tmp_path):
    present = tmp_path / "run-2"
    present.mkdir()
    assert changeset.current([str(present)]) is None, "a folder that exists and holds no change set is fine"
    with pytest.raises(changeset.ChangesetError) as raised:
        changeset.current([str(present), str(tmp_path / "run-1")])
    assert raised.value.kind == "missing" and "is gone" in raised.value.reason and "cancel the request" in raised.value.reason


def test_the_next_code_task_of_a_request_is_refused_when_an_earlier_run_folder_is_gone(tmp_path, monkeypatch):
    def clean(project, *args):
        return subprocess.CompletedProcess([], 0, stdout="" if args[0] == "status" else "abc123\n", stderr="")
    monkeypatch.setattr(ops_task_run, "_git", clean)
    monkeypatch.setattr(ops_task_run, "_request_run_dirs", lambda ctx, request_id: [str(tmp_path / "gone")])
    got = ops._code_state({"cfg": {"project": str(tmp_path)}}, {"parent_id": 7})
    assert "refused" in got and "the request's change set" in got["refused"] and "is gone" in got["refused"]
    monkeypatch.setattr(ops_task_run, "_request_run_dirs", lambda ctx, request_id: [])
    assert ops._code_state({"cfg": {"project": str(tmp_path)}}, {"parent_id": 7}) == {"project_commit": "abc123", "current": None}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
