"""A locked secret store is not a missing secret, and the credentials directory serves a machine with no desktop session
(package P-OPS, finding I3). Fakes only: no real keyring is touched, no real secret is read.

Run: uv run --with pytest pytest providers/secrets/tests
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "resolver.py"
spec = importlib.util.spec_from_file_location("workbench_secret_resolver_locked_test", SCRIPT)
res = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = res
spec.loader.exec_module(res)

SENTINEL = "zz-not-a-real-value-77"
NAME = "VCS_GITHUB_TOKEN"


class KeyringLocked(Exception):
    """Named like the library's own error for a locked collection."""


class FakeStore:
    def __init__(self, values=None, error=None):
        self.values, self.error, self.asked = values or {}, error, []

    def get_password(self, service, username):
        self.asked.append((service, username))
        if self.error is not None:
            raise self.error
        return self.values.get((service, username))


def test_a_locked_store_is_reported_as_locked_and_an_absent_secret_as_missing():
    locked = res.resolve_state(NAME, environ={}, store=FakeStore(error=KeyringLocked("the collection is locked")))
    assert locked.state == "locked" and "unlock it" in locked.detail
    absent = res.resolve_state(NAME, environ={}, store=FakeStore())
    assert absent.state == "missing" and absent.detail == ""
    found = res.resolve_state(NAME, environ={}, store=FakeStore({("openhora", "github"): SENTINEL}))
    assert (found.state, found.value, found.source, found.service) == ("found", SENTINEL, "secret store", "openhora")


def test_callers_that_read_only_none_are_unchanged_and_the_last_failure_is_told():
    assert res.resolve(NAME, environ={}, store=FakeStore(error=RuntimeError("no backend"))) is None
    assert res.store_failure() == "unavailable" and res.store_locked_note() == res.LOCKED_SENTENCE
    assert res.resolve_detail(NAME, environ={}, store=FakeStore()) is None
    assert res.store_failure() is None and res.store_locked_note() == ""


def test_the_kind_follows_the_name_of_the_error_and_no_message_of_the_backend_is_kept():
    for error, kind in ((KeyringLocked("x"), "locked"), (RuntimeError("no recommended backend"), "unavailable")):
        got = res.probe_store(FakeStore(error=error))
        assert got["state"] == kind
        assert "no recommended backend" not in json.dumps(got)
    assert res.probe_store(FakeStore())["state"] == "ok"
    assert res.probe_store(None)["state"] == "no-library"


def test_the_probe_asks_for_a_name_nothing_stores():
    store = FakeStore({("openhora", "github"): SENTINEL})
    res.probe_store(store)
    assert store.asked == [("openhora", res.PROBE_USERNAME)]


def test_the_environment_wins_over_a_locked_store_and_the_store_is_not_asked():
    store = FakeStore(error=KeyringLocked("locked"))
    got = res.resolve_state(NAME, environ={NAME: SENTINEL}, store=store)
    assert got.state == "found" and store.asked == []


def test_a_new_service_that_raises_still_lets_the_old_one_answer_but_two_that_raise_are_locked():
    class PerService(FakeStore):
        def get_password(self, service, username):
            self.asked.append((service, username))
            if service == "openhora":
                raise KeyringLocked("locked")
            return self.values.get((service, username))

    assert res.resolve_state(NAME, environ={}, store=PerService({("ai-workbench", "github"): SENTINEL})).state == "found"
    # one service raised and the other holds nothing: the secret may be in the one that could not be read
    assert res.resolve_state(NAME, environ={}, store=PerService()).state == "locked"


def test_report_marks_locked_and_asks_the_store_once():
    store = FakeStore(error=KeyringLocked("locked"))
    rows = {r["name"]: r for r in res.report(environ={"GMAIL_CLIENT_ID": SENTINEL}, store=store)}
    assert rows[NAME]["state"] == "locked" and rows[NAME]["found"] is False
    assert rows["GMAIL_CLIENT_ID"]["state"] == "found"
    assert rows[NAME]["store"] == "locked"
    assert len(store.asked) <= 2, "after the first failure the store is not asked again for each of the other secrets"
    assert SENTINEL not in json.dumps(list(rows.values()))


def test_check_exits_4_for_a_locked_store_and_3_for_a_missing_secret(monkeypatch):
    def run(store):
        monkeypatch.setattr(res, "_keyring", lambda: store)
        monkeypatch.setattr(res.os, "environ", {})
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            return res.main(["--check", NAME]), err.getvalue()

    code, text = run(FakeStore(error=KeyringLocked("locked")))
    assert code == res.EXIT_LOCKED == 4 and "unlock it" in text
    code, text = run(FakeStore())
    assert code == res.EXIT_NOT_FOUND == 3 and "not found" in text


# --- the credentials directory ------------------------------------------------------------------------------------------


def make_dir(tmp_path, files=None, mode=0o700):
    folder = tmp_path / "credentials"
    folder.mkdir()
    for name, value in (files or {}).items():
        path = folder / name
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
    folder.chmod(mode)
    return folder


def test_a_secret_in_the_credentials_directory_is_found_by_its_name(tmp_path):
    folder = make_dir(tmp_path, {NAME: f"  {SENTINEL}\n"})
    store = FakeStore(error=KeyringLocked("locked"))
    got = res.resolve_state(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(folder)}, store=store)
    assert (got.state, got.value, got.source) == ("found", SENTINEL, "credentials directory")
    assert store.asked == [], "a store that is locked is not asked when the directory answered"
    assert res.resolve(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(folder)}, store=store) == (SENTINEL, "credentials directory")


def test_the_order_is_the_environment_then_the_directory_then_the_store(tmp_path):
    folder = make_dir(tmp_path, {NAME: "from-dir"})
    store = FakeStore({("openhora", "github"): "from-store"})
    both = {NAME: "from-env", "OPENHORA_CREDENTIALS_DIR": str(folder)}
    assert res.resolve(NAME, environ=both, store=store)[0] == "from-env"
    assert res.resolve(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(folder)}, store=store)[0] == "from-dir"
    assert res.resolve(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(tmp_path / "none")}, store=store)[0] == "from-store"


def test_the_directory_a_systemd_unit_sets_and_the_default_one_are_read(tmp_path):
    folder = make_dir(tmp_path, {NAME: SENTINEL})
    assert res.resolve(NAME, environ={"CREDENTIALS_DIRECTORY": str(folder)}, store=None) == (SENTINEL, "credentials directory")
    assert res.credentials_dir({"OPENHORA_CREDENTIALS_DIR": "/a", "CREDENTIALS_DIRECTORY": "/b"}) == "/a"
    home = tmp_path / "home"
    default = home / ".config" / "openhora" / "credentials"
    default.mkdir(parents=True)
    (default / NAME).write_text(SENTINEL)
    (default / NAME).chmod(0o600)
    default.chmod(0o700)
    assert res.resolve(NAME, environ={"HOME": str(home)}, store=None) == (SENTINEL, "credentials directory")
    assert res.credentials_dir({"HOME": str(tmp_path / "nobody")}) is None


def test_a_directory_or_file_others_can_read_is_unsafe_not_missing(tmp_path):
    open_dir = make_dir(tmp_path, {NAME: SENTINEL}, mode=0o755)
    got = res.resolve_state(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(open_dir)}, store=None)
    assert got.state == "unsafe" and "chmod 700" in got.detail and SENTINEL not in got.detail
    assert res.resolve(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(open_dir)}, store=None) is None
    open_dir.chmod(0o700)
    (open_dir / NAME).chmod(0o644)
    got = res.resolve_state(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(open_dir)}, store=None)
    assert got.state == "unsafe" and "chmod 600" in got.detail


def test_a_link_in_place_of_the_folder_or_the_file_is_refused(tmp_path):
    real = make_dir(tmp_path, {NAME: SENTINEL})
    link = tmp_path / "link"
    link.symlink_to(real)
    assert res.resolve_state(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(link)}, store=None).state == "unsafe"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text(SENTINEL)
    elsewhere.chmod(0o600)
    other = tmp_path / "other"
    other.mkdir()
    (other / NAME).symlink_to(elsewhere)
    other.chmod(0o700)
    assert res.resolve_state(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(other)}, store=None).state == "unsafe"


def test_a_file_that_is_not_there_is_missing_and_one_too_large_is_unsafe(tmp_path):
    folder = make_dir(tmp_path, {"OTHER_NAME": "x"})
    assert res.resolve_state(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(folder)}, store=None).state == "missing"
    (folder / NAME).write_text("x" * (res.CREDENTIAL_MAX_BYTES + 1))
    (folder / NAME).chmod(0o600)
    assert res.resolve_state(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(folder)}, store=None).state == "unsafe"


def test_a_file_named_like_another_secret_or_with_a_path_is_never_read(tmp_path):
    folder = make_dir(tmp_path, {"NOTION_TOKEN": SENTINEL})
    assert res.resolve_state(NAME, environ={"OPENHORA_CREDENTIALS_DIR": str(folder)}, store=None).state == "missing"


def test_the_listing_never_carries_a_value_and_says_where(tmp_path):
    folder = make_dir(tmp_path, {NAME: SENTINEL})
    rows = {r["name"]: r for r in res.report(environ={"OPENHORA_CREDENTIALS_DIR": str(folder)}, store=FakeStore())}
    assert rows[NAME]["found"] and rows[NAME]["source"] == "credentials directory"
    assert SENTINEL not in json.dumps(list(rows.values()))
    assert os.path.exists(folder / NAME)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
