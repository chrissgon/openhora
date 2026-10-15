"""One host writes the sources folder at a time, and no database or lock lives in a synced folder (package P-OPS, finding I4; limit
L28). Offline: the converter is a stand-in; the second host is a lease file written by the test.

  L28  a writer of the sources folder takes the folder's lease (host id, pid, expiry); a live lease of another host refuses the write and
       names that host; an expired lease is taken over

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_lease.py
"""
from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
from sources_fixture import standin_convert

ops = st.load("ops")
ops_core = st.load("ops_core")
sources = st.load("sources")
project_config = st.load("project_config")
lease = st.load("lease")
REPO = st.REPO
CSV = "name,price\napple,1.20\npear,3.10\n"
OTHER_HOST = "00ff00ff00ff00ff"


def write_config(tmp_path, **overrides) -> str:
    project = tmp_path / "project"
    (project / "docs" / "workbench").mkdir(parents=True, exist_ok=True)
    config = {"workbench": str(REPO), "data_dir": str(tmp_path / "data"), "store_db": str(tmp_path / "store" / "tasks.sqlite"),
              "sources_dir": str(tmp_path / "sources")}
    config.update(overrides)
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps({k: v for k, v in config.items() if v is not None}), encoding="utf-8")
    return str(project)


@pytest.fixture(autouse=True)
def isolated_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))


@pytest.fixture
def case(tmp_path, monkeypatch):
    path = write_config(tmp_path)
    ops.accept_config(path, project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "survey.csv").write_text(CSV, encoding="utf-8")
    row = sources.register(ctx, "survey", "file", "survey.csv")
    return SimpleNamespace(path=path, ctx=ctx, cfg=ctx["cfg"], folder=Path(ctx["cfg"]["sources_dir"]), tmp=tmp_path, row=row,
                           file=str(tmp_path / "files" / "survey.csv"))


def another_host(case, expires_in: float, name="laptop-two", pid=4242):
    """The lease another machine's runtime left in the (synced) folder."""
    now = time.time()
    (case.folder / lease.LEASE_NAME).write_text(json.dumps(
        {"host_id": OTHER_HOST, "host_name": name, "pid": pid, "taken_at": "x", "expires_at": now + expires_in, "expires": "x"}), encoding="utf-8")


def test_limit_28_a_writer_of_the_sources_folder_takes_its_lease_and_a_live_lease_of_another_host_refuses_the_write_naming_it(case):
    before = time.time()
    first = sources.import_version(case.ctx, case.row, case.file, convert=standin_convert)
    assert first["imported"] and first["version"] == 1
    held = json.loads((case.folder / lease.LEASE_NAME).read_text())
    mine = lease.host_identity(case.cfg["data_dir"])
    assert held["host_id"] == mine["id"] and held["pid"] == os.getpid() and before < held["expires_at"] - lease.LEASE_SECONDS + 1
    # another host's lease is live: this host refuses to write, names that host, and writes nothing
    another_host(case, expires_in=240, name="laptop-two", pid=4242)
    (case.tmp / "files" / "survey.csv").write_text(CSV + "fig,9.00\n", encoding="utf-8")
    with pytest.raises(sources.SourcesError) as refused:
        sources.import_version(case.ctx, case.row, case.file, convert=standin_convert, label="refresh")
    assert refused.value.code == "lease" and "laptop-two" in str(refused.value) and "4242" in str(refused.value)
    assert "does not write while it lasts" in str(refused.value)
    assert not (case.folder / "survey" / "2").exists()
    assert case.ctx["store"].source_version_count(case.ctx["conn"], "survey") == 1, "no row either"
    assert json.loads((case.folder / lease.LEASE_NAME).read_text())["host_id"] == OTHER_HOST, "the other host's lease was left as it was"


def test_an_expired_lease_of_another_host_is_taken_over_and_the_write_goes_on(case):
    another_host(case, expires_in=-1, name="old-desktop")
    done = sources.import_version(case.ctx, case.row, case.file, convert=standin_convert)
    assert done["imported"]
    held = json.loads((case.folder / lease.LEASE_NAME).read_text())
    assert held["host_id"] == lease.host_identity(case.cfg["data_dir"])["id"]


def test_this_hosts_own_lease_is_renewed_by_any_process_of_it(case):
    sources.import_version(case.ctx, case.row, case.file, convert=standin_convert)
    first = json.loads((case.folder / lease.LEASE_NAME).read_text())
    fd = os.open(case.folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        taken = lease.take(fd, case.cfg["data_dir"], now=first["expires_at"] - 10, pid=99999)
    finally:
        os.close(fd)
    assert taken["pid"] == 99999 and taken["took_over"] is None and taken["expires_at"] > first["expires_at"]


def test_the_lease_lasts_five_minutes_after_the_last_write_and_is_not_released(case):
    before = time.time()
    sources.import_version(case.ctx, case.row, case.file, convert=standin_convert)
    held = json.loads((case.folder / lease.LEASE_NAME).read_text())
    assert lease.LEASE_SECONDS == 300 and before + 299 < held["expires_at"] <= time.time() + 300
    assert (case.folder / lease.LEASE_NAME).is_file(), "it stays after the write: a sync may bring it to the other machine late"
    assert stat.S_IMODE((case.folder / lease.LEASE_NAME).stat().st_mode) == 0o600


def test_a_damaged_lease_is_taken_as_expired_and_a_link_at_its_name_is_never_written_through(case):
    outside = case.tmp / "outside.txt"
    outside.write_text("untouched")
    (case.folder / lease.LEASE_NAME).symlink_to(outside)
    sources.import_version(case.ctx, case.row, case.file, convert=standin_convert)
    assert outside.read_text() == "untouched"
    assert (case.folder / lease.LEASE_NAME).is_file() and not (case.folder / lease.LEASE_NAME).is_symlink()
    (case.folder / lease.LEASE_NAME).write_text("{not json")
    fd = os.open(case.folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert lease.read(fd) is None
        lease.take(fd, case.cfg["data_dir"], now=1.0)
        assert lease.read(fd)["host_id"] == lease.host_identity(case.cfg["data_dir"])["id"]
    finally:
        os.close(fd)


def test_the_host_id_is_made_once_in_the_data_folder_and_is_private(case):
    first = lease.host_identity(case.cfg["data_dir"])
    again = lease.host_identity(case.cfg["data_dir"])
    path = Path(case.cfg["data_dir"]) / lease.HOST_ID_NAME
    assert first == again and len(first["id"]) == 16 and stat.S_IMODE(path.stat().st_mode) == 0o600
    path.write_text("not an id\n")
    assert lease.host_identity(case.cfg["data_dir"])["id"] != "not an id"


# --- nothing but the sources folder lives where a sync client merges files (decision D30) -------------------------------


@pytest.mark.parametrize("folder", ["Dropbox", "Dropbox (Personal)", "OneDrive - Example Ltd", "Google Drive", "Nextcloud", "iCloud Drive",
                                    "Mobile Documents", "CloudStorage"])
def test_data_dir_and_the_stores_folder_are_refused_in_a_synced_folder(tmp_path, folder):
    synced = tmp_path / folder
    synced.mkdir()
    for key, value in (("data_dir", str(synced / "data")), ("store_db", str(synced / "store" / "tasks.sqlite"))):
        path = write_config(tmp_path, **{key: value})
        with pytest.raises(project_config.ConfigError) as refused:
            project_config.load(path)
        assert key in str(refused.value) and "synced folder" in str(refused.value) and folder in str(refused.value)


def test_a_marker_a_sync_client_leaves_in_a_parent_is_enough_and_a_plain_folder_is_not_refused(tmp_path):
    marked = tmp_path / "work"
    (marked / "deeper").mkdir(parents=True)
    (marked / ".stfolder").mkdir()
    path = write_config(tmp_path, data_dir=str(marked / "deeper" / "data"))
    with pytest.raises(project_config.ConfigError) as refused:
        project_config.load(path)
    assert ".stfolder" in str(refused.value)
    plain = write_config(tmp_path, data_dir=str(tmp_path / "plain" / "data"))
    assert project_config.load(plain)["data_dir"].endswith("plain/data")


def test_the_sources_folder_itself_may_be_in_a_synced_drive(tmp_path):
    synced = tmp_path / "Dropbox"
    synced.mkdir()
    path = write_config(tmp_path, sources_dir=str(synced / "sources"))
    assert project_config.load(path)["sources_dir"].endswith("Dropbox/sources")


def test_the_folder_of_a_link_into_a_synced_drive_is_in_it(tmp_path):
    synced = tmp_path / "OneDrive"
    (synced / "data").mkdir(parents=True)
    link = tmp_path / "shortcut"
    link.symlink_to(synced / "data")
    assert lease.synced_reason(str(link)) and "OneDrive" in lease.synced_reason(str(link))
    assert lease.synced_reason(str(tmp_path / "ordinary")) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
