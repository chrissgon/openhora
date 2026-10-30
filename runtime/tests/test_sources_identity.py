"""The identity of a project in the marker of its sources folder, after a restart (limit L21, package sources-identity): a marker that names another DEVICE
but this folder's inode and a path that still leads to this folder is the same project; anything else stays `foreign`. Offline: the marker is planted as
text, the way an old one reads on disk; nothing is run in a container and no service is called.

The oracle is each test's own literal: `dev + 2` is a device this folder never had, `ino + 1` an inode it never had, and the real `shutil.copytree` is the
copy a person could make. The checks are functions (`passes`, `refuses`), so that the last test can plant a wrong rule in `sources._remounted` and see
them fail: a check that cannot fail proves nothing.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_sources_identity.py
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
from test_sources_limits import refused, write_config  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
sources = st.load("sources")
project_config = st.load("project_config")
lease = st.load("lease")

TOLD = "the project folder's device number changed"
RENEWED = "the marker now names the project folder's new device number"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    sources._TOLD_REMOUNT.clear()
    yield
    sources._TOLD_REMOUNT.clear()


def marked(tmp_path, **overrides):
    """A project whose configuration was accepted: its marker written by the runtime. Returns the project, its config, the marker's path, and the folder's
    device and inode."""
    project = write_config(tmp_path, **overrides)
    ops.accept_config(project, project_config.load(project)["sha256"])
    info = os.stat(project)
    cfg = ops_core.context(project)["cfg"]
    return SimpleNamespace(project=project, cfg=cfg, marker=Path(cfg["sources_dir"]) / sources.MARKER, dev=info.st_dev, ino=info.st_ino,
                           key=f"{info.st_dev}:{info.st_ino}")


def plant(world, project=..., path=..., **extra) -> bytes:
    """Write a marker as an old one reads on disk (a literal text, not made by the code under test) and return its bytes. `project` and `path` default to this
    folder's own; None leaves the key out for `path` and writes null for `project`."""
    data = {"kind": "openhora-sources", "version": 3, "id": "0123456789abcdef"}
    data["project"] = world.key if project is ... else project
    if path is ...:
        data["project_path"] = os.path.realpath(world.project)
    elif path is not None:
        data["project_path"] = path
    data.update(extra)
    text = json.dumps(data) + "\n"
    world.marker.write_text(text, encoding="utf-8")
    os.chmod(world.marker, 0o600)
    return text.encode("utf-8")


def passes(cfg) -> None:
    """The folder is this project's: the guardrail check and the open folder both accept it. An AssertionError otherwise (so that a wrong rule fails here)."""
    try:
        sources.check_folder(cfg)
        sources.Folder(cfg).close()
    except sources.SourcesError as e:
        raise AssertionError(f"the folder was refused: {e}") from None


def refuses(cfg) -> None:
    """The folder is refused as another project's by both. An AssertionError when either accepts it."""
    for call in (sources.check_folder, sources.Folder):
        try:
            result = call(cfg)
        except sources.SourcesError as e:
            assert "another project" in str(e) and e.code == "foreign", str(e)
            continue
        if result is not None:
            result.close()
        raise AssertionError(f"{call.__name__} accepted a folder that is another project's")


def other_device(world) -> str:
    return f"{world.dev + 2}:{world.ino}"


def test_same_path_and_inode_with_another_device_is_the_same_project_and_a_read_writes_nothing(tmp_path, capsys):
    world = marked(tmp_path)
    written = plant(world, other_device(world))
    capsys.readouterr()
    passes(world.cfg)
    passes(world.cfg)
    assert world.marker.read_bytes() == written, "a read never rewrites the marker"
    assert not (Path(world.cfg["sources_dir"]) / lease.LEASE_NAME).exists(), "a read takes no lease"
    assert sorted(p.name for p in Path(world.cfg["sources_dir"]).iterdir()) == [sources.MARKER]
    err = capsys.readouterr().err
    assert err.count(TOLD) == 1, "one line for the process and the project, not one for each use"
    assert str(world.project) not in err and other_device(world) not in err, "the line holds no path and no device number"


def test_another_inode_at_the_same_path_is_refused(tmp_path):
    world = marked(tmp_path)
    plant(world, f"{world.dev}:{world.ino + 1}")
    refuses(world.cfg)
    plant(world, f"{world.dev + 2}:{world.ino + 1}")
    refuses(world.cfg)


def test_another_path_with_the_same_inode_and_another_device_is_refused(tmp_path):
    world = marked(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    plant(world, other_device(world), path=str(elsewhere))
    refuses(world.cfg)
    plant(world, other_device(world), path=str(tmp_path / "gone"))
    refuses(world.cfg)


def test_a_renamed_project_on_the_same_device_keeps_passing_as_today(tmp_path):
    world = marked(tmp_path)
    plant(world, world.key, path=str(tmp_path / "an old name"))
    passes(world.cfg)


def assert_copy_refused(world, tmp_path):
    """A real copy of the project is another folder: a new inode, so it is refused with the marker as written and again with the device moved."""
    copy = tmp_path / "copy"
    shutil.copytree(world.project, copy)
    assert os.stat(copy).st_ino != world.ino, "a copy has an inode of its own"
    cfg = dict(project_config.load(str(copy)), sources_dir=world.cfg["sources_dir"])
    assert cfg["project"] != world.project
    written = world.marker.read_bytes()
    refuses(cfg)
    plant(world, other_device(world))
    refuses(cfg)
    return written


def test_a_copy_of_the_project_is_refused_also_after_the_device_moved(tmp_path):
    world = marked(tmp_path)
    assert_copy_refused(world, tmp_path)
    plant(world, other_device(world))
    passes(world.cfg)   # the original, with the same marker, is still this folder's


@pytest.mark.parametrize("project,path", [
    (..., None),                                  # no path recorded
    (..., 7),                                     # a path that is not text
    (..., "relative/project"),                    # a relative path
    ("x:INO", ...),                               # an id that is not two numbers
    (None, ...),                                  # no project at all
    ("", ...),
    (":", ...),
])
def test_a_marker_with_no_path_or_a_bad_id_is_refused_when_the_device_differs(tmp_path, project, path):
    world = marked(tmp_path)
    key = other_device(world) if project is ... else project.replace("INO", str(world.ino)) if isinstance(project, str) else project
    plant(world, key, path=path)
    refuses(world.cfg)


def test_a_symlink_and_another_spelling_of_the_project_pass_after_the_device_moved(tmp_path):
    world = marked(tmp_path)
    link = tmp_path / "alias"
    os.symlink(world.project, link)
    plant(world, other_device(world), path=str(link))
    passes(world.cfg)
    upper = world.project[:-len("project")] + "PROJECT"
    if os.path.isdir(upper):   # a disk that folds case (macOS): the typed case is what realpath keeps, and a string compare would refuse it
        plant(world, other_device(world), path=upper)
        passes(world.cfg)
    plant(world, other_device(world), path=world.project + "/../project")
    passes(world.cfg)


def test_the_marker_is_renewed_only_under_the_lease_and_records_the_old_id(tmp_path, capsys):
    world = marked(tmp_path)
    plant(world, other_device(world))
    with sources.Folder(world.cfg) as folder:
        capsys.readouterr()
        taken = sources.take_lease(folder, world.cfg)
    assert taken["took_over"] is None
    data = json.loads(world.marker.read_text())
    assert data["project"] == world.key and data["project_path"] == os.path.realpath(world.project)
    assert data["renewed_from"] == other_device(world)
    assert data["id"] != "0123456789abcdef", "the marker was rewritten whole, with an id of its own"
    folder_path = Path(world.cfg["sources_dir"])
    assert (folder_path / lease.LEASE_NAME).is_file()
    assert not (folder_path / (sources.MARKER + ".new")).exists()
    assert stat.S_IMODE(world.marker.stat().st_mode) == 0o600
    assert RENEWED in capsys.readouterr().err
    passes(world.cfg)   # and the rewritten marker is the project's own
    with sources.Folder(world.cfg) as folder:
        sources.take_lease(folder, world.cfg)
    assert json.loads(world.marker.read_text())["renewed_from"] == other_device(world), "a second lease does not renew again"


def test_a_lease_on_a_marker_of_another_project_changes_nothing(tmp_path):
    world = marked(tmp_path)
    own = plant(world, world.key, path=str(tmp_path / "an old name"))
    with sources.Folder(world.cfg) as folder:
        sources.take_lease(folder, world.cfg)
        assert world.marker.read_bytes() == own, "this project's own marker is not renewed for a stale path"
        for foreign in (f"{world.dev + 2}:{world.ino + 1}", f"{world.dev}:{world.ino + 1}"):
            written = plant(world, foreign)
            sources._renew_marker(folder.fd, world.cfg)
            assert world.marker.read_bytes() == written, foreign


def test_adopt_still_takes_a_foreign_folder_and_not_a_remounted_one(tmp_path):
    world = marked(tmp_path)
    sha = project_config.load(world.project)["sha256"]
    written = plant(world, other_device(world))
    done = ops.accept_config(world.project, sha, adopt_sources=True)
    assert "sources_folder_adopted" not in done, "a remounted marker is this project's: nothing is taken over"
    assert world.marker.read_bytes() == written, "and the acceptance does not rewrite it"
    plant(world, f"{world.dev + 2}:{world.ino + 1}")
    assert "--adopt-sources" in refused(ops.accept_config, world.project, sha)
    done = ops.accept_config(world.project, sha, adopt_sources=True)
    assert done["sources_folder_adopted"]["from"]["id"] == f"{world.dev + 2}:{world.ino + 1}"
    assert json.loads(world.marker.read_text())["project"] == world.key
    passes(world.cfg)


def test_an_old_marker_still_works(tmp_path):
    world = marked(tmp_path)
    text = ('{"kind": "openhora-sources", "version": 3, "id": "0123456789abcdef", "project": "%s", "project_path": "%s"}\n'
            % (world.key, os.path.realpath(world.project)))
    world.marker.write_text(text, encoding="utf-8")
    passes(world.cfg)
    with sources.Folder(world.cfg) as folder:
        sources.take_lease(folder, world.cfg)
    assert world.marker.read_text() == text, "a marker that already names this project is not rewritten"


def test_vacuity_the_checks_fail_on_a_wrong_rule(tmp_path, monkeypatch):
    # a rule that always says "the same project" lets a copy through: the copy check must fail
    world = marked(tmp_path / "a")
    monkeypatch.setattr(sources, "_remounted", lambda *a: True)
    with pytest.raises(AssertionError):
        assert_copy_refused(world, tmp_path / "a")
    monkeypatch.undo()
    # a rule that never says it refuses the project itself after the restart: the first check must fail
    world = marked(tmp_path / "b")
    plant(world, other_device(world))
    monkeypatch.setattr(sources, "_remounted", lambda *a: False)
    with pytest.raises(AssertionError):
        passes(world.cfg)
    monkeypatch.undo()
    passes(world.cfg)
    # and a rule that compares strings of the path (the case a person typed) would refuse a link: the symlink check needs the real stat
    link = tmp_path / "b" / "alias"
    os.symlink(world.project, link)
    plant(world, other_device(world), path=str(link))
    monkeypatch.setattr(sources, "_remounted", lambda data, project: data.get("project_path") == os.path.realpath(project))
    with pytest.raises(AssertionError):
        passes(world.cfg)
