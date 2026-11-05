"""A locked password manager is told by every messenger provider with the manager's own sentence, and is not reported as a missing token
(package S16). The real resolver, a FAKE `op` and a temporary mapping file; the messengers' files are unchanged: they print whatever
`store_locked_note()` says. Nothing real is read.

Run: uv run --with pytest==9.1.1 pytest providers/messenger/tests/test_messenger_password_manager.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

import whatsapp_cloud_kit as ckit
import whatsapp_twilio_kit as tkit
from whatsapp_cloud_kit import wc
from whatsapp_twilio_kit import wt

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
SAY = "the password manager (1Password) is locked or not signed in"
REF = "op://Example Vault/messenger/credential"
SENTINEL = "zz-not-a-real-value-msg-pm"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


telegram = load("messenger_telegram_pm", HERE.parent / "telegram.py")
discord = load("messenger_discord_pm", HERE.parent / "discord.py")
fake_op = load("fake_op_for_messengers", PROVIDERS / "secrets" / "tests" / "fake_op.py")
NAMES = ("MESSENGER_TELEGRAM_BOT_TOKEN", "MESSENGER_DISCORD_BOT_TOKEN", "MESSENGER_WHATSAPP_CLOUD_TOKEN", "MESSENGER_WHATSAPP_CLOUD_APP_SECRET",
         "MESSENGER_WHATSAPP_CLOUD_VERIFY_TOKEN", *tkit.SECRETS)


class Absent:
    @staticmethod
    def get_password(service, username):
        return None


def resolver():
    module = load("resolver_messenger_pm", PROVIDERS / "secrets" / "resolver.py")
    module._keyring = lambda: Absent
    return module


@pytest.fixture
def locked_manager(monkeypatch, tmp_path):
    op = fake_op.FakeOp(tmp_path / "bin")
    op.answer("*", rc=1, stderr="[ERROR] You are not signed in. " + SENTINEL)
    config = tmp_path / "config" / "openhora"
    config.mkdir(parents=True)
    mapping = config / "password-manager.json"
    mapping.write_text(json.dumps({"backend": "1password", "references": {name: REF for name in NAMES}}), encoding="utf-8")
    mapping.chmod(0o600)
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OPENHORA_CREDENTIALS_DIR", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("PATH", f"{op.folder}{os.pathsep}/usr/bin{os.pathsep}/bin")
    return op


def test_the_messengers_say_the_manager_is_locked_and_name_the_missing_token_after_it(locked_manager, monkeypatch):
    monkeypatch.setattr(telegram, "secret_resolver", resolver)
    with pytest.raises(telegram.ProviderError) as e:
        telegram.load_token(False)
    assert str(e.value).startswith(SAY) and "no Telegram bot token" in str(e.value) and SENTINEL not in str(e.value)
    monkeypatch.setattr(discord, "secret_resolver", resolver)
    with pytest.raises(discord.ProviderError) as e:
        discord.load_token()
    assert str(e.value).startswith(SAY) and "no Discord bot token" in str(e.value)
    for module in (wc, wt):
        with pytest.raises(module.ProviderError) as e:
            module.load_secrets(resolver=resolver())
        assert str(e.value).startswith(SAY) and SENTINEL not in str(e.value)


def test_an_unsafe_mapping_file_is_told_instead_of_a_missing_token(locked_manager, monkeypatch, tmp_path):
    (tmp_path / "config" / "openhora" / "password-manager.json").chmod(0o644)
    monkeypatch.setattr(telegram, "secret_resolver", resolver)
    with pytest.raises(telegram.ProviderError) as e:
        telegram.load_token(False)
    assert str(e.value).startswith("the password-manager mapping") and "chmod 600" in str(e.value)
    assert locked_manager.calls() == []


def test_in_test_mode_the_manager_is_not_asked(locked_manager, monkeypatch):
    monkeypatch.setattr(telegram, "secret_resolver", resolver)
    with pytest.raises(telegram.ProviderError) as e:
        telegram.load_token(True)
    assert SAY not in str(e.value) and locked_manager.calls() == []
