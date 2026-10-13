"""Offline tests of the sentence every messenger provider gives when the OS secret store cannot be read because the keyring library
is missing (MSG-11), against the real resolver with `keyring` made unimportable. No secret store is read.

Run: uv run --with pytest pytest providers/messenger/tests/test_messenger_store_missing.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import whatsapp_cloud_kit as ckit
import whatsapp_twilio_kit as tkit
from whatsapp_cloud_kit import wc
from whatsapp_twilio_kit import wt

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
SAY = "the OS secret store is not available in this Python (the keyring library is missing)"
RUN = "uv run --with keyring==25.7.0 python3"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


telegram = load("messenger_telegram_store_missing", HERE.parent / "telegram.py")
discord = load("messenger_discord_store_missing", HERE.parent / "discord.py")


@pytest.fixture
def no_keyring(monkeypatch):
    """A Python that has no keyring library: importing it raises ImportError."""
    monkeypatch.setitem(sys.modules, "keyring", None)
    for name in ("MESSENGER_TELEGRAM_BOT_TOKEN", "MESSENGER_DISCORD_BOT_TOKEN", *ckit_names(), *tkit.SECRETS):
        monkeypatch.delenv(name, raising=False)


def ckit_names():
    return (wc.SECRET_TOKEN, wc.SECRET_APP, wc.SECRET_VERIFY)


def resolver():
    return load("resolver_store_missing", PROVIDERS / "secrets" / "resolver.py")


def test_the_resolver_tells_an_unavailable_store_apart_without_reading_anything(no_keyring, monkeypatch):
    assert resolver().store_available() is False
    fake = type(sys)("keyring")
    monkeypatch.setitem(sys.modules, "keyring", fake)
    assert resolver().store_available() is True
    assert resolver().resolve("MESSENGER_TELEGRAM_BOT_TOKEN", environ={}, store=None) is None   # the lookup order is untouched


def test_whatsapp_cloud_says_the_store_is_missing_first(no_keyring):
    with pytest.raises(wc.ProviderError) as e:
        wc.load_secrets()
    text = str(e.value)
    assert e.value.kind == "not-configured" and e.value.code == 3
    assert text.startswith(SAY) and RUN in text and "export the variables" in text and "MESSENGER_WHATSAPP_CLOUD_TOKEN" in text


def test_whatsapp_twilio_says_the_store_is_missing_first(no_keyring):
    with pytest.raises(wt.ProviderError) as e:
        wt.load_secrets()
    text = str(e.value)
    assert e.value.code == 3 and text.startswith(SAY) and RUN in text and "messenger-whatsapp-twilio-auth-token" in text


def test_the_sentence_survives_the_redaction_of_the_cli(no_keyring, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "s"))
    assert wt.main(["setup", "--account-sid", tkit.ACCOUNT, "--sender", "+14155550100", "--public-host", "box.example"]) == 3
    err = capsys.readouterr().err
    assert SAY in err and RUN in err


def test_whatsapp_with_a_store_that_is_available_keeps_the_old_sentence(monkeypatch):
    class Stand:
        @staticmethod
        def resolve(name, **kw):
            return None

        @staticmethod
        def store_available():
            return True
    for module, call in ((wc, wc.load_secrets), (wt, wt.load_secrets)):
        with pytest.raises(module.ProviderError) as e:
            call(resolver=Stand)
        assert SAY not in str(e.value) and str(e.value).startswith("missing or malformed")


def test_a_resolver_without_the_check_or_with_a_broken_one_gives_the_old_sentence():
    class Old:
        @staticmethod
        def resolve(name, **kw):
            return None

    class Broken(Old):
        @staticmethod
        def store_available():
            raise RuntimeError("boom")
    for stand in (Old, Broken):
        with pytest.raises(wc.ProviderError) as e:
            wc.load_secrets(resolver=stand)
        assert SAY not in str(e.value)


def test_telegram_says_the_store_is_missing_first(no_keyring, monkeypatch):
    monkeypatch.setattr(telegram, "secret_resolver", resolver)
    with pytest.raises(telegram.ProviderError) as e:
        telegram.load_token(False)
    assert str(e.value).startswith(SAY) and RUN in str(e.value) and "MESSENGER_TELEGRAM_BOT_TOKEN" in str(e.value)
    with pytest.raises(telegram.ProviderError) as e:        # test mode: the store is not asked on purpose, so nothing is "missing"
        telegram.load_token(True)
    assert SAY not in str(e.value)


def test_telegram_keeps_the_old_sentence_with_a_store(monkeypatch):
    monkeypatch.setattr(telegram, "secret_resolver", lambda: type("R", (), {"resolve": staticmethod(lambda *a, **k: None),
                                                                           "store_available": staticmethod(lambda: True)}))
    with pytest.raises(telegram.ProviderError) as e:
        telegram.load_token(False)
    assert SAY not in str(e.value) and "keyring set openhora messenger-telegram" in str(e.value)


def test_discord_says_the_store_is_missing_first(no_keyring, monkeypatch, capsys):
    monkeypatch.setattr(discord, "secret_resolver", resolver)
    with pytest.raises(discord.ProviderError) as e:
        discord.load_token()
    assert str(e.value).startswith(SAY) and RUN in str(e.value) and "MESSENGER_DISCORD_BOT_TOKEN" in str(e.value)
    assert discord.main(["--check", "--platform", "discord"]) == 3
    assert SAY in capsys.readouterr().err


def test_discord_keeps_the_old_sentence_with_a_store(monkeypatch):
    monkeypatch.setattr(discord, "secret_resolver", lambda: type("R", (), {"resolve": staticmethod(lambda *a, **k: None),
                                                                          "store_available": staticmethod(lambda: True)}))
    with pytest.raises(discord.ProviderError) as e:
        discord.load_token()
    assert SAY not in str(e.value) and "keyring set openhora messenger-discord" in str(e.value)


def test_a_secret_that_is_set_but_malformed_does_not_blame_the_store(no_keyring, monkeypatch):
    values = {**tkit.SECRETS, wt.SECRET_AUTH: "has a space"}
    monkeypatch.setenv(wc.SECRET_TOKEN, "x")

    class Stand:
        @staticmethod
        def resolve(name, **kw):
            return (values[name], "environment") if name in values else None

        @staticmethod
        def store_available():
            return False
    with pytest.raises(wt.ProviderError) as e:
        wt.load_secrets(resolver=Stand)
    assert SAY not in str(e.value) and str(e.value).startswith("missing or malformed")
    values.pop(wt.SECRET_AUTH)                               # now one is entirely absent
    with pytest.raises(wt.ProviderError) as e:
        wt.load_secrets(resolver=Stand)
    assert str(e.value).startswith(SAY)


def test_every_test_here_is_isolated_from_the_real_secret_store_and_state_folder():
    import os
    assert os.environ["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
    assert "isolated-state" in os.environ["OPENHORA_STATE_DIR"]
