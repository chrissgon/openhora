"""A locked secret store is told apart from a missing key in the runtime's own messages (package P-OPS, finding I3): the key
lookup of a model, the reason a task is held, the sentence that says what gets past it, and the secrets read of the
connections. Fakes only: a stand-in for the keyring library, no real store, no real secret.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_secret_state.py
"""
from __future__ import annotations

import sys
import types

import pytest

import standin_tree as st

secret_state = st.load("secret_state")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_reads = st.load("ops_reads")
lab = st.load("lab")

VARIABLE = "EXAMPLE_P_OPS_KEY"


class KeyringLocked(Exception):
    pass


class Locked:
    @staticmethod
    def get_password(service, username):
        raise KeyringLocked("the collection is locked")


class Absent:
    @staticmethod
    def get_password(service, username):
        return None


def fake_keyring(monkeypatch, store):
    """Stand in for the keyring library the resolver imports: its get_password is the store's."""
    module = types.ModuleType("keyring")
    module.get_password = store.get_password
    monkeypatch.setitem(sys.modules, "keyring", module)


def test_a_locked_store_is_a_sentence_and_an_absent_secret_is_nothing():
    assert "the secret store is locked or unavailable: unlock it" in secret_state.locked_sentence(store=Locked, fresh=True)
    assert secret_state.locked_sentence(store=Absent, fresh=True) == ""
    assert secret_state.probe(store=None, fresh=True)["state"] == "no-library"
    assert secret_state.locked_sentence(store=None, fresh=True) == ""


def test_the_answer_is_kept_for_a_moment_so_a_page_does_not_ask_a_locked_store_every_time(monkeypatch):
    calls = []

    class Counting:
        @staticmethod
        def get_password(service, username):
            calls.append(username)
            raise KeyringLocked("locked")
    fake_keyring(monkeypatch, Counting)
    secret_state.forget()
    now = [100.0]
    for _ in range(3):
        assert secret_state.locked_sentence(root=secret_state.ROOT, clock=lambda: now[0])
    assert len(calls) == 1
    now[0] += secret_state.PROBE_SECONDS + 1
    secret_state.locked_sentence(root=secret_state.ROOT, clock=lambda: now[0])
    assert len(calls) == 2
    secret_state.forget()


def test_the_runtimes_own_key_of_a_model_says_the_store_is_locked_and_not_that_it_is_missing(monkeypatch):
    for name in ("EXAMPLE_P_OPS_KEY",):
        monkeypatch.delenv(name, raising=False)
    fake_keyring(monkeypatch, Locked)
    value, reason = ops_core._own_key(VARIABLE)
    assert value is None and "the secret store is locked or unavailable: unlock it" in reason
    fake_keyring(monkeypatch, Absent)
    assert ops_core._own_key(VARIABLE) == (None, None)
    fake_keyring(monkeypatch, types.SimpleNamespace(get_password=lambda service, username: "x" * 12))
    assert ops_core._own_key(VARIABLE) == ("x" * 12, None)


def test_the_reason_a_task_is_held_names_a_locked_store_and_keeps_the_old_words_for_a_missing_key(monkeypatch):
    monkeypatch.setattr(lab, "credential_missing", lambda model=None: [VARIABLE])
    monkeypatch.setattr(lab, "resolve_model", lambda model=None: "model-one")
    monkeypatch.setattr(ops.dispatcher, "store_readable", lambda: "ok")
    monkeypatch.setattr(ops.secret_state, "locked_sentence", lambda *a, **k: secret_state.LOCKED_NOTE.split(";")[0])
    reason, why, missing = ops._credential_stop("model-one")
    assert reason == "credential" and missing == [VARIABLE]
    assert "the secret store is locked or unavailable: unlock it" in why and "is neither set nor found" not in why
    monkeypatch.setattr(ops.secret_state, "locked_sentence", lambda *a, **k: "")
    reason, why, missing = ops._credential_stop("model-one")
    assert reason == "credential" and "is neither set nor found in the secret store" in why and "locked" not in why


def test_what_gets_past_a_held_credential_says_to_unlock_the_store_when_it_is_locked(monkeypatch):
    monkeypatch.setattr(ops_reads.secret_state, "locked_sentence", lambda *a, **k: "the secret store is locked or unavailable: unlock it")
    line = ops_reads.held_next("/nonexistent-project", "credential", [VARIABLE])
    assert line.startswith("The secret store is locked or unavailable: unlock it") and "may be missing" in line and "nothing needs to be stored" not in line
    monkeypatch.setattr(ops_reads.secret_state, "locked_sentence", lambda *a, **k: "")
    assert ops_reads.held_next("/nonexistent-project", "credential", [VARIABLE]).startswith("The credential is in neither")


def test_the_secrets_read_of_the_connections_says_the_store_is_locked_and_lists_no_value(monkeypatch):
    fake_keyring(monkeypatch, Locked)
    rows, note = ops_reads._secret_rows()
    assert note and secret_state.LOCKED_NOTE in note
    assert all("value" not in row for row in rows)


def test_an_unsafe_credentials_directory_is_told_by_the_runtime_and_is_not_a_missing_key(monkeypatch, tmp_path):
    folder = tmp_path / "credentials"
    folder.mkdir()
    folder.chmod(0o755)
    monkeypatch.setenv("OPENHORA_CREDENTIALS_DIR", str(folder))
    fake_keyring(monkeypatch, Absent)
    said = secret_state.unreadable_sentence(fresh=True)
    assert said.startswith("the credentials directory is unsafe") and "chmod 700" in said and str(folder) in said
    value, reason = ops_core._own_key(VARIABLE)
    assert value is None and "chmod 700" in reason
    line = ops_reads.held_next("/nonexistent-project", "credential", [VARIABLE])
    assert line.startswith("The credentials directory is unsafe") and "may be missing" in line and "nothing needs to be stored" not in line
    monkeypatch.setattr(lab, "credential_missing", lambda model=None: [VARIABLE])
    monkeypatch.setattr(lab, "resolve_model", lambda model=None: "model-one")
    monkeypatch.setattr(ops.dispatcher, "store_readable", lambda: "ok")
    reason, why, missing = ops._credential_stop("model-one")
    assert "credentials directory is unsafe" in why and "is neither set nor found" not in why
    folder.chmod(0o700)
    assert secret_state.unreadable_sentence(fresh=True) == ""


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
