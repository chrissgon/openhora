"""A provider that exits 3 because the secret store is locked is not an expired authorization (package sources-identity, review of #673).

`providers/_google.py` and `providers/_msgraph.py` exit 3 (`not-configured`) for an account record that is there and cannot be read now (the OS secret store is locked or unavailable, the
credentials folder is unsafe), and also for a 401 on the API call. `providers/resolve.py` maps exit 3 to `not-configured` for all of them. The phone says "the authorization expired" only
when it is true: `sources_mail.provider_call` asks the secret store (runtime/secret_state.py) on `not-configured` and, when the store is locked or unavailable, carries no word, so the reply
is the plain sentence (a retry, after the person unlocks the store, may work). Here a real stand-in provider process exits 3 through the real `providers/resolve.py`, and a stand-in
resolver answers the state of the store. Offline; no real keyring, no real credentials.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_sources_mail_secret_store.py
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from types import SimpleNamespace

import pytest

import standin_tree as st

REPO = st.REPO
sources = st.load("sources")
sources_mail = st.load("sources_mail")
ops_items = st.load("ops_items")
secret_state = st.load("secret_state")

_spec = importlib.util.spec_from_file_location("resolve_for_secret_store_tests", REPO / "providers" / "resolve.py")
resolve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve)

PROVIDER_WORDS = "Gmail rejected the access token (401 on GET /gmail/v1/users/me/messages); rerun: uv run providers/mailbox/auth.py"
LOCKED_WORDS = "the Google account authorization (GOOGLE_ACCOUNT_TOKEN) cannot be read (locked): the secret store is locked"


def provider_that_exits_3(tmp_path, words):
    """The seam `provider_call` takes: the real `resolve.invoke` over a real process that prints `words` to stderr and exits 3."""
    script = tmp_path / "stand-in-provider.py"
    script.write_text(f"import sys\nsys.stderr.write({words!r} + '\\n')\nsys.exit(3)\n", encoding="utf-8")

    def call(cls, verb, args, **kwargs):
        return resolve.invoke(str(script), verb, args, timeout=30,
                              run=lambda argv: subprocess.run([sys.executable, *argv[argv.index(str(script)):]], capture_output=True, text=True, timeout=60, check=False))
    return call


def store_in_state(monkeypatch, state, manager="na"):
    """Stand in for the secret resolver runtime/secret_state.py loads: the store answers `state`, there is no unsafe credentials folder."""
    stand_in = SimpleNamespace(probe_store=lambda store="default": {"state": state, "detail": "the secret store is locked or unavailable: unlock it"},
                               credentials_status=lambda environ=None: {"state": "absent"},
                               manager_applies=lambda names: False,
                               probe_manager=lambda environ=None: {"state": manager, "detail": "the password manager"})
    monkeypatch.setattr(secret_state, "_resolver", lambda root: stand_in)
    secret_state.forget() if hasattr(secret_state, "forget") else None


def read(tmp_path, words=PROVIDER_WORDS):
    cfg = {"workbench": str(REPO)}
    with pytest.raises(sources.SourcesError) as caught:
        sources_mail.provider_call(cfg, "reader:email", "gmail", "search", ["--query", "in:inbox"], call=provider_that_exits_3(tmp_path, words))
    return caught.value


def test_the_same_module_is_the_one_sources_mail_asks():
    assert sys.modules["secret_state"] is secret_state


@pytest.mark.parametrize("state", ["locked", "unavailable"])
def test_a_locked_or_unavailable_store_carries_no_word_and_the_phone_gets_the_plain_sentence(tmp_path, monkeypatch, state):
    store_in_state(monkeypatch, state)
    error = read(tmp_path, LOCKED_WORDS)
    assert error.code == "mail" and error.provider_kind is None
    assert ops_items.reason_of(error.code, error.provider_kind) is None, "a retry after unlocking may work: not a reason only the computer solves... of authorization"


def test_an_answering_store_keeps_the_authorization_word_so_a_401_and_an_expired_grant_say_so(tmp_path, monkeypatch):
    store_in_state(monkeypatch, "ok")
    error = read(tmp_path)
    assert error.provider_kind == "not-configured" and ops_items.reason_of(error.code, error.provider_kind) == "authorization"
    assert "ZEBRA" not in str(error) and error.code == "mail"


def test_a_locked_password_manager_is_not_an_expired_authorization_either(tmp_path, monkeypatch):
    stand_in = SimpleNamespace(probe_store=lambda store="default": {"state": "ok", "detail": "the store answered"},
                               credentials_status=lambda environ=None: {"state": "absent"},
                               manager_applies=lambda names: True,
                               probe_manager=lambda environ=None: {"state": "locked", "detail": "the password manager is locked"})
    monkeypatch.setattr(secret_state, "_resolver", lambda root: stand_in)
    assert read(tmp_path).provider_kind is None


def test_an_unsafe_credentials_folder_is_not_an_expired_authorization_either(tmp_path, monkeypatch):
    stand_in = SimpleNamespace(probe_store=lambda store="default": {"state": "ok", "detail": "the store answered"},
                               credentials_status=lambda environ=None: {"state": "unsafe", "detail": "the folder is open to other users"},
                               manager_applies=lambda names: False,
                               probe_manager=lambda environ=None: {"state": "na", "detail": ""})
    monkeypatch.setattr(secret_state, "_resolver", lambda root: stand_in)
    assert read(tmp_path).provider_kind is None


def test_a_store_that_cannot_be_asked_is_not_guessed_at(tmp_path, monkeypatch):
    def broken(root):
        raise RuntimeError("the resolver does not run here")
    monkeypatch.setattr(secret_state, "_resolver", broken)
    assert read(tmp_path).provider_kind is None


def test_the_other_kinds_are_untouched_and_the_exit_code_is_the_providers(tmp_path):
    cfg = {"workbench": str(REPO)}
    for code, kind in ((2, "usage"), (1, "failed")):
        script = tmp_path / f"p{code}.py"
        script.write_text(f"import sys\nsys.exit({code})\n", encoding="utf-8")
        call = lambda cls, verb, args, _s=script, **kw: resolve.invoke(str(_s), verb, args, timeout=30, run=lambda argv: subprocess.run(  # noqa: E731
            [sys.executable, *argv[argv.index(str(_s)):]], capture_output=True, text=True, timeout=60, check=False))
        with pytest.raises(sources.SourcesError) as caught:
            sources_mail.provider_call(cfg, "reader:email", "gmail", "search", [], call=call)
        assert caught.value.provider_kind == kind


def test_vacuity_without_the_question_to_the_store_a_locked_store_would_read_as_an_authorization(tmp_path, monkeypatch):
    store_in_state(monkeypatch, "locked")
    monkeypatch.setattr(sources_mail, "_closed_kind", lambda cfg, kind, names: kind if kind in ("usage", "not-configured", "failed") else None)
    error = read(tmp_path, LOCKED_WORDS)
    assert error.provider_kind == "not-configured", "the planted rule says what the review found false"
    with pytest.raises(AssertionError):
        assert error.provider_kind is None
