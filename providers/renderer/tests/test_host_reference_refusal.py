"""A file or folder of a reference store (a path under the marker `.openhora-reference`) is looked at and measured, never used: the renderer's host
side refuses it, in `stage`, `mount_recording` and `add_mount`, before anything is read or mounted (contracts/runtime.md, limit L73)."""
from __future__ import annotations

import os
import types

import pytest

import renderer_kit  # noqa: F401  (puts providers/renderer on the path)
import _docker as D
import _host
from _text import Refusal


@pytest.fixture
def no_docker(monkeypatch):
    def fail(*a, **k):
        raise AssertionError("docker was called")
    monkeypatch.setattr(D.box, "docker", fail)
    monkeypatch.setattr(D.box, "run", fail)
    monkeypatch.setattr(D.subprocess, "run", fail)


@pytest.fixture
def store(tmp_path):
    root = tmp_path / "references"
    ref = root / "0123456789abcdef"
    ref.mkdir(parents=True)
    marker = root / ".openhora-reference"
    marker.write_text("x")
    marker.chmod(0o400)
    (ref / "video.mp4").write_bytes(b"not a real video")
    (ref / "facts.json").write_text("{}")
    return root


def job():
    return _host.Job(types.SimpleNamespace(), 30, "still")


def test_stage_refuses_a_file_of_a_reference_store(store, no_docker):
    for name in ("video.mp4", "facts.json"):
        with pytest.raises(Refusal) as caught:
            job().stage("input/file", str(store / "0123456789abcdef" / name))
        assert caught.value.code == "reference_refused"


def test_mount_recording_refuses_a_file_of_a_reference_store(store, no_docker):
    with pytest.raises(Refusal) as caught:
        job().mount_recording(str(store / "0123456789abcdef" / "video.mp4"))
    assert caught.value.code == "reference_refused" and caught.value.field == "recording"


def test_add_mount_refuses_a_folder_of_a_reference_store(store, no_docker):
    for folder in (store, store / "0123456789abcdef"):
        with pytest.raises(Refusal) as caught:
            job().add_mount(str(folder), "/extra", "ro")
        assert caught.value.code == "reference_refused"


def test_a_link_to_a_reference_file_is_refused_too(store, tmp_path, no_docker):
    link = tmp_path / "innocent.mp4"
    link.symlink_to(store / "0123456789abcdef" / "video.mp4")
    with pytest.raises(Refusal) as caught:
        job().mount_recording(str(link))
    assert caught.value.code == "reference_refused"


def test_a_file_outside_a_reference_store_is_not_refused_by_this_check(tmp_path, no_docker):
    plain = tmp_path / "recording.mov"
    plain.write_bytes(b"x")
    _host.refuse_reference(str(plain), "recording")
    j = job()
    assert j.mount_recording(str(plain)) == D.MOUNT_RECORDING and os.path.samefile(j.recording, plain)
    folder = tmp_path / "folder"
    folder.mkdir()
    assert j.add_mount(str(folder), "/extra", "ro") == "/extra"


def test_what_a_copy_made_outside_the_store_does_is_not_caught_and_the_limit_says_so(store, tmp_path, no_docker):
    """L73: the check reads paths, not content. A copy of the file made by hand is a plain file to the check."""
    copy = tmp_path / "mine.mp4"
    copy.write_bytes((store / "0123456789abcdef" / "video.mp4").read_bytes())
    _host.refuse_reference(str(copy), "recording")
    assert not os.path.islink(copy)
