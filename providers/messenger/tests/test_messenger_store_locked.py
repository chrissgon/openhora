"""Offline tests: a locked secret store is told to the person by every messenger provider and is not reported as a missing token
(package P-OPS, finding I3). The real resolver, with a fake store that raises; nothing real is read.

Run: uv run --with pytest pytest providers/messenger/tests/test_messenger_store_locked.py
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
SAY = "the secret store is locked or unavailable: unlock it"
MISSING = "no Telegram bot token"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


telegram = load("messenger_telegram_store_locked", HERE.parent / "telegram.py")
discord = load("messenger_discord_store_locked", HERE.parent / "discord.py")


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


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("MESSENGER_TELEGRAM_BOT_TOKEN", "MESSENGER_DISCORD_BOT_TOKEN", wc.SECRET_TOKEN, wc.SECRET_APP, wc.SECRET_VERIFY,
                 *tkit.SECRETS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OPENHORA_CREDENTIALS_DIR", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home")


def resolver(store):
    module = load("resolver_store_locked", PROVIDERS / "secrets" / "resolver.py")
    module._keyring = lambda: store
    return module


def test_telegram_says_the_store_is_locked_first_and_an_absent_token_is_still_missing(clean_env, monkeypatch):
    monkeypatch.setattr(telegram, "secret_resolver", lambda: resolver(Locked))
    with pytest.raises(telegram.ProviderError) as e:
        telegram.load_token(False)
    assert str(e.value).startswith(SAY) and MISSING in str(e.value)
    monkeypatch.setattr(telegram, "secret_resolver", lambda: resolver(Absent))
    with pytest.raises(telegram.ProviderError) as e:
        telegram.load_token(False)
    assert SAY not in str(e.value) and str(e.value).startswith(MISSING)


def test_telegram_in_test_mode_does_not_ask_the_store_and_does_not_blame_it(clean_env, monkeypatch):
    monkeypatch.setattr(telegram, "secret_resolver", lambda: resolver(Locked))
    with pytest.raises(telegram.ProviderError) as e:
        telegram.load_token(True)
    assert SAY not in str(e.value)


def test_discord_says_the_store_is_locked_first(clean_env, monkeypatch):
    monkeypatch.setattr(discord, "secret_resolver", lambda: resolver(Locked))
    with pytest.raises(discord.ProviderError) as e:
        discord.load_token()
    assert str(e.value).startswith(SAY) and "no Discord bot token" in str(e.value)
    monkeypatch.setattr(discord, "secret_resolver", lambda: resolver(Absent))
    with pytest.raises(discord.ProviderError) as e:
        discord.load_token()
    assert SAY not in str(e.value)


def test_whatsapp_cloud_and_twilio_say_the_store_is_locked_first(clean_env):
    for module in (wc, wt):
        with pytest.raises(module.ProviderError) as e:
            module.load_secrets(resolver=resolver(Locked))
        assert str(e.value).startswith(SAY)
        with pytest.raises(module.ProviderError) as e:
            module.load_secrets(resolver=resolver(Absent))
        assert SAY not in str(e.value) and str(e.value).startswith("missing or malformed")


def test_a_resolver_without_the_locked_check_gives_the_old_sentence(clean_env):
    class Old:
        @staticmethod
        def resolve(name, **kw):
            return None
    with pytest.raises(wc.ProviderError) as e:
        wc.load_secrets(resolver=Old)
    assert SAY not in str(e.value)
