"""Tests of what the Microsoft providers share (providers/_msgraph.py), seen from the three providers that load it: the OneDrive files provider,
the Outlook mailbox provider and the Outlook calendar provider. The point is the separation the code keeps even though it shares code: one
permission, one secret, one record, one set of test overrides and one client id variable for each, so that no token of one reaches what
another is for.

Run: uv run --with pytest==9.1.1 pytest providers/mailbox/tests/test_msgraph_shared.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


shared = load(PROVIDERS / "_msgraph.py", "msgraph_shared_under_test")
onedrive = load(PROVIDERS / "documents" / "onedrive.py", "onedrive_for_the_shared_tests")
mail = load(PROVIDERS / "mailbox" / "outlook.py", "outlook_mail_for_the_shared_tests")
calendar = load(PROVIDERS / "calendar" / "outlook.py", "outlook_calendar_for_the_shared_tests")
PROFILES = {"onedrive": onedrive.PROFILE, "mail": mail.PROFILE, "calendar": calendar.PROFILE}


def test_each_provider_has_its_own_permission_secret_entry_and_variables():
    assert {k: p.scope for k, p in PROFILES.items()} == {"onedrive": "Files.Read", "mail": "Mail.Read", "calendar": "Calendars.ReadBasic"}
    for field in ("secret", "keyring_username", "client_id_var", "tenant_var", "env_prefix", "user_agent", "scope"):
        values = [getattr(p, field) for p in PROFILES.values()]
        assert len(set(values)) == 3, f"two providers share {field}: {values}"
    assert {p.keyring_service for p in PROFILES.values()} == {"openhora"}


def test_each_refresh_names_its_one_permission_and_offline_access_and_nothing_else():
    for kind, profile in PROFILES.items():
        assert profile.refresh_scope == f"https://graph.microsoft.com/{profile.scope} offline_access", kind
        others = {p.scope for p in PROFILES.values()} - {profile.scope}
        assert not any(other in profile.refresh_scope for other in others), kind


def test_a_scope_check_of_one_provider_refuses_the_permission_of_another():
    for kind, profile in PROFILES.items():
        for other_kind, other in PROFILES.items():
            if kind == other_kind:
                assert shared.check_scope(profile, f"https://graph.microsoft.com/{other.scope} offline_access") == profile.scope
            else:
                with pytest.raises(shared.ProviderError) as refused:
                    shared.check_scope(profile, f"https://graph.microsoft.com/{other.scope} offline_access")
                assert refused.value.code == 3 and other.scope in str(refused.value)
                with pytest.raises(shared.ProviderError):
                    shared.check_scope(profile, f"{profile.scope} {other.scope}")


def test_the_commands_a_message_names_are_the_providers_own():
    assert "onedrive_auth.py" in onedrive.AUTH_COMMAND and "providers/mailbox/outlook_auth.py" in mail.AUTH_COMMAND
    assert "providers/calendar/outlook_auth.py" in calendar.AUTH_COMMAND
    for profile in PROFILES.values():
        assert profile.auth_command.startswith("uv run ") and profile.auth_command.endswith("_auth.py authorize")


def test_the_test_overrides_are_set_together_and_loopback_only_for_each_provider(monkeypatch):
    for profile in PROFILES.values():
        for name in (profile.env_base, profile.env_token_url, profile.env_download_hosts):
            monkeypatch.delenv(name, raising=False)
        base, token_url, hosts, test_mode = shared.endpoints(profile, ("files.example",))
        assert base == "https://graph.microsoft.com/v1.0" and token_url is None and test_mode is False and hosts == ("files.example",)
        monkeypatch.setenv(profile.env_base, "http://127.0.0.1:9")
        with pytest.raises(shared.ProviderError) as partial:
            shared.endpoints(profile)
        assert partial.value.code == 2 and "set together" in str(partial.value) and profile.env_token_url in str(partial.value)
        monkeypatch.setenv(profile.env_token_url, "http://127.0.0.1:9/token")
        if profile.download_hosts:
            monkeypatch.setenv(profile.env_download_hosts, "127.0.0.1")
        assert shared.endpoints(profile)[3] is True
        monkeypatch.setenv(profile.env_token_url, "https://login.example/token")
        with pytest.raises(shared.ProviderError) as remote:
            shared.endpoints(profile)
        assert remote.value.code == 2 and "loopback" in str(remote.value)
        for name in (profile.env_base, profile.env_token_url, profile.env_download_hosts):
            monkeypatch.delenv(name, raising=False)


def test_one_providers_overrides_do_not_move_another(monkeypatch):
    monkeypatch.setenv(mail.PROFILE.env_base, "http://127.0.0.1:9")
    monkeypatch.setenv(mail.PROFILE.env_token_url, "http://127.0.0.1:9/token")
    assert shared.endpoints(mail.PROFILE)[3] is True
    assert shared.endpoints(calendar.PROFILE)[3] is False and shared.endpoints(onedrive.PROFILE, ("files.example",))[3] is False


def test_plain_ascii_accepts_only_the_characters_a_header_may_carry():
    assert shared.plain_ascii("abc-DEF_123.~") and shared.plain_ascii("!~")
    for bad in ("", None, 5, ["a"], "a b", "a\tb", "a\r\nb", "café", "ő", "a\x00b", "a\x7fb"):
        assert not shared.plain_ascii(bad), repr(bad)


def test_a_record_that_a_refresh_could_not_send_is_not_configured():
    for profile in PROFILES.values():
        for bad in ({"refresh_token": "café", "client_id": "x"}, {"refresh_token": "x", "client_id": "aő"}, {"refresh_token": "a\nb", "client_id": "x"}):
            with pytest.raises(shared.ProviderError) as refused:
                shared.parse_record(profile, __import__("json").dumps(bad))
            assert refused.value.code == 3 and profile.auth_command in str(refused.value)


def test_the_error_of_a_request_names_the_kind_and_never_the_text():
    with pytest.raises(shared.ProviderError) as refused:
        shared.http("GET", "http://127.0.0.1:1/x", {"X": "a\r\nb: secret-looking-value"}, what="Microsoft Graph")
    assert "ValueError" in str(refused.value) and "secret-looking-value" not in str(refused.value)
    with pytest.raises(shared.ProviderError) as refused:
        shared.http("GET", "http://127.0.0.1:1/a b", {}, what="Microsoft Graph")
    assert "InvalidURL" in str(refused.value) and "a b" not in str(refused.value)
    with pytest.raises(shared.ProviderError) as refused:
        shared.http("GET", "http://127.0.0.1:1/x", {}, what="Microsoft Graph")   # nothing listens on port 1
    assert refused.value.code == 1


def test_the_shared_module_runs_on_the_interpreter_the_mailbox_tests_run_on():
    text = (PROVIDERS / "_msgraph.py").read_text(encoding="utf-8")
    assert "requires-python = \">=3.9\"" in text, "it runs on the interpreter the scheduler starts the mailbox tests with"
