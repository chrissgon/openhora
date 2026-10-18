"""Unit tests of what the Microsoft account token adds to providers/_msgraph.py (package ACCT-M): the platform's set and its check, the account
record and how a reader chooses between it and its legacy record, the profile a record belongs to, the profile's refresh scope, the account's
address, and the static facts the limits rest on (the readers send GET only, L58; the token enters a provider process through one secret
and nothing prints it, L59; no script holds a permanent delete). No network at all.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_microsoft.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
REPO = PROVIDERS.parent


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


msgraph = load(PROVIDERS / "_msgraph.py", "msgraph_for_the_account_unit_tests")
resolve = load(PROVIDERS / "resolve.py", "resolve_for_the_account_unit_tests")
resolver = load(PROVIDERS / "secrets" / "resolver.py", "resolver_for_the_account_unit_tests")
READER_FILES = (PROVIDERS / "documents" / "onedrive.py", PROVIDERS / "mailbox" / "outlook.py", PROVIDERS / "calendar" / "outlook.py")
PLATFORM = ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")
PREFIX = "https://graph.microsoft.com/"
ACCOUNT = msgraph.account_profile(run_hint="uv run x", env_prefix="X_TEST", user_agent="openhora-test", not_found="not found", forbidden_hint="forbidden")
LEGACY = msgraph.Profile(label="Outlook mail", scope="Mail.Read", secret="OUTLOOK_MAIL_TOKEN", keyring_username="outlook-mail",
                         auth_command="uv run legacy_auth.py authorize", run_hint="uv run y", env_prefix="Y_TEST", user_agent="openhora-test",
                         not_found="nf", forbidden_hint="fh", client_id_var="OUTLOOK_MAIL_CLIENT_ID", tenant_var="OUTLOOK_MAIL_TENANT")


def record(**over):
    base = {"slot": "main", "refresh_token": "fake-refresh-token-not-real", "client_id": "fake-client-id", "tenant": "common",
            "scope": " ".join(PLATFORM), "account_kind": "personal", "account": "casey.rivera@mail.example", "obtained_at": "2026-10-18T08:00:00Z"}
    base.update(over)
    return base


# --- the platform's set -----------------------------------------------------------------------------------------------------


def test_the_platform_set_is_the_five_permissions_the_maintainer_approved_and_offline_access_is_asked_besides():
    assert msgraph.PLATFORM_SCOPES == ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")
    assert ACCOUNT.scopes == msgraph.PLATFORM_SCOPES and ACCOUNT.account is True and ACCOUNT.scope is None
    assert ACCOUNT.refresh_scope == " ".join(PREFIX + n for n in PLATFORM) + " offline_access"
    assert "Files.ReadWrite.All" not in ACCOUNT.refresh_scope and "Mail.Read " not in ACCOUNT.refresh_scope
    assert (ACCOUNT.secret, ACCOUNT.keyring_username, ACCOUNT.keyring_service) == ("MICROSOFT_ACCOUNT_TOKEN", "microsoft-account", "openhora")
    assert msgraph.ACCOUNT_SLOT == "main"


def test_a_legacy_profile_is_unchanged_one_permission_and_the_old_request():
    assert LEGACY.scopes == ("Mail.Read",) and LEGACY.account is False
    assert LEGACY.refresh_scope == f"{PREFIX}Mail.Read offline_access"
    assert msgraph.check_scope(LEGACY, f"{PREFIX}Mail.Read offline_access") == "Mail.Read"
    with pytest.raises(msgraph.ProviderError):
        msgraph.check_scope(LEGACY, " ".join(PREFIX + n for n in PLATFORM))


def test_the_check_accepts_exactly_the_set_with_or_without_the_prefix_and_the_words_that_grant_nothing():
    expected = " ".join(PLATFORM)
    assert msgraph.check_platform_scope(ACCOUNT, " ".join(PREFIX + n for n in PLATFORM) + " offline_access openid profile email") == expected
    assert msgraph.check_platform_scope(ACCOUNT, " ".join(PLATFORM)) == expected
    assert msgraph.check_platform_scope(ACCOUNT, " ".join(n.upper() for n in reversed(PLATFORM))) == expected
    assert msgraph.check_platform_scope(ACCOUNT, "\n".join(PLATFORM) + "  ") == expected


@pytest.mark.parametrize("granted", [None, "", "offline_access", "Mail.ReadWrite", " ".join(PLATFORM[:-1]), " ".join(PLATFORM[1:]),
                                     "Mail.Read Mail.Send Calendars.ReadWrite Files.ReadWrite User.Read"])
def test_a_token_that_lacks_a_permission_is_refused_with_exit_3_and_the_command(granted):
    with pytest.raises(msgraph.ProviderError) as refused:
        msgraph.check_platform_scope(ACCOUNT, granted)
    assert refused.value.code == 3 and "the account token lacks" in str(refused.value)
    assert ACCOUNT.auth_command in str(refused.value) and "keep every box ticked" in str(refused.value)


@pytest.mark.parametrize("extra", ["Mail.Read", "Calendars.Read", "Files.ReadWrite.All", "Sites.Read.All", "Mail.ReadWrite.Shared", "Directory.Read.All"])
def test_a_token_that_carries_another_permission_is_refused_with_exit_3_and_the_command(extra):
    with pytest.raises(msgraph.ProviderError) as refused:
        msgraph.check_platform_scope(ACCOUNT, " ".join(PLATFORM) + " " + extra)
    assert refused.value.code == 3 and f"carries {extra}" in str(refused.value) and ACCOUNT.auth_command in str(refused.value)
    assert "revoke the app's access" in str(refused.value)


# --- the account record -----------------------------------------------------------------------------------------------------


def test_the_account_record_is_read_with_its_slot_scope_and_a_default_tenant():
    parsed = msgraph.parse_account_record(ACCOUNT, json.dumps(record()))
    assert parsed["slot"] == "main" and parsed["tenant"] == "common" and parsed["refresh_token"] == "fake-refresh-token-not-real"
    without_tenant = record()
    del without_tenant["tenant"]
    assert msgraph.parse_account_record(ACCOUNT, json.dumps(without_tenant))["tenant"] == "common"
    assert msgraph.parse_account_record(ACCOUNT, json.dumps(record(scope=" ".join(PREFIX + n for n in reversed(PLATFORM)))))["slot"] == "main"


@pytest.mark.parametrize("text", [
    "not json", "[]", json.dumps({}), json.dumps(record(slot=None)), json.dumps(record(slot="")), json.dumps(record(slot="UPPER")),
    json.dumps(record(slot="a" * 13)), json.dumps(record(slot="a b")), json.dumps(record(refresh_token="")), json.dumps(record(refresh_token="a b")),
    json.dumps(record(refresh_token="café")), json.dumps(record(refresh_token=5)), json.dumps(record(client_id="a\nb")),
    json.dumps(record(client_id=None))])
def test_an_unreadable_or_incomplete_account_record_is_not_configured(text):
    with pytest.raises(msgraph.ProviderError) as refused:
        msgraph.parse_account_record(ACCOUNT, text)
    assert refused.value.code == 3 and "unreadable or incomplete" in str(refused.value) and ACCOUNT.auth_command in str(refused.value)


@pytest.mark.parametrize("scope", [None, "", 5, "Mail.Read", "Mail.ReadWrite", " ".join(PLATFORM[:-1]), " ".join(PLATFORM) + " Mail.Read", "Files.Read"])
def test_a_record_made_for_another_set_is_not_configured(scope):
    with pytest.raises(msgraph.ProviderError) as refused:
        msgraph.parse_account_record(ACCOUNT, json.dumps(record(scope=scope)))
    assert refused.value.code == 3 and "another set of permissions" in str(refused.value)


def test_a_tenant_that_is_not_a_tenant_name_is_not_configured():
    for bad in ("../evil", "a/b", "a b", "-lead", 5, ["x"]):
        with pytest.raises(msgraph.ProviderError) as refused:
            msgraph.parse_account_record(ACCOUNT, json.dumps(record(tenant=bad)))
        assert refused.value.code == 3 and "not a tenant name" in str(refused.value)


def test_a_record_with_a_slot_is_the_accounts_and_one_without_is_not():
    assert msgraph.account_shaped(json.dumps(record())) and msgraph.account_shaped(json.dumps({"slot": 3}))
    assert not msgraph.account_shaped(json.dumps({"refresh_token": "x", "client_id": "y"}))
    assert not msgraph.account_shaped("not json") and not msgraph.account_shaped("[]") and not msgraph.account_shaped(None)
    assert msgraph.profile_of(record(), LEGACY, ACCOUNT) is ACCOUNT
    assert msgraph.profile_of({"refresh_token": "x", "client_id": "y"}, LEGACY, ACCOUNT) is LEGACY


# --- choosing between the account record and the legacy one -------------------------------------------------------------------


class Resolver:
    def __init__(self, found):
        self.found, self.asked = found, []

    def resolve(self, name, allow_store=True):
        self.asked.append((name, allow_store))
        return self.found.get(name)


def credentials(found, test_mode=False, account_found=None):
    legacy_resolver = Resolver(found)
    account_resolver = legacy_resolver if account_found is None else Resolver(account_found)
    result = msgraph.load_credentials(LEGACY, ACCOUNT, lambda: legacy_resolver, test_mode, lambda: account_resolver)
    return result, legacy_resolver, account_resolver


def test_the_account_record_is_asked_first_and_wins_and_the_legacy_one_is_not_even_asked():
    (rec, where), resolver_, _ = credentials({"MICROSOFT_ACCOUNT_TOKEN": (json.dumps(record()), "secret store"),
                                              "OUTLOOK_MAIL_TOKEN": (json.dumps({"refresh_token": "x", "client_id": "y"}), "environment")})
    assert rec["slot"] == "main" and where == "secret store"
    assert resolver_.asked == [("MICROSOFT_ACCOUNT_TOKEN", True)]


def test_the_legacy_record_is_used_when_the_account_record_is_absent_and_the_store_is_not_asked_in_test_mode():
    legacy = json.dumps({"refresh_token": "x", "client_id": "y", "tenant": "common", "scope": "Mail.Read"})
    msgraph._NOTED_LEGACY.clear()
    (rec, where), resolver_, _ = credentials({"OUTLOOK_MAIL_TOKEN": (legacy, "environment")}, test_mode=True)
    assert "slot" not in rec and where == "environment" and rec["scope"] == "Mail.Read"
    assert resolver_.asked == [("MICROSOFT_ACCOUNT_TOKEN", False), ("OUTLOOK_MAIL_TOKEN", False)], "allow_store is False in test mode"


def test_a_separate_account_resolver_is_the_one_asked_for_the_account_record():
    legacy = json.dumps({"refresh_token": "x", "client_id": "y"})
    (rec, _), legacy_resolver, account_resolver = credentials({"OUTLOOK_MAIL_TOKEN": (legacy, "environment")},
                                                              account_found={"MICROSOFT_ACCOUNT_TOKEN": (json.dumps(record()), "environment")})
    assert rec["slot"] == "main" and legacy_resolver.asked == [] and [n for n, _ in account_resolver.asked] == ["MICROSOFT_ACCOUNT_TOKEN"]


def test_nothing_found_names_both_commands_and_both_secrets():
    with pytest.raises(msgraph.ProviderError) as refused:
        credentials({})
    message = str(refused.value)
    assert refused.value.code == 3 and ACCOUNT.auth_command in message and LEGACY.auth_command in message
    assert "MICROSOFT_ACCOUNT_TOKEN" in message and "OUTLOOK_MAIL_TOKEN" in message


def test_a_wrong_account_record_is_an_error_even_when_a_legacy_record_exists():
    legacy = json.dumps({"refresh_token": "x", "client_id": "y"})
    with pytest.raises(msgraph.ProviderError) as refused:
        credentials({"MICROSOFT_ACCOUNT_TOKEN": (json.dumps(record(scope="Mail.Read")), "environment"), "OUTLOOK_MAIL_TOKEN": (legacy, "environment")})
    assert "another set of permissions" in str(refused.value)


def test_something_under_the_accounts_name_that_is_not_an_account_record_is_unreadable_alone_and_ignored_beside_a_legacy_record():
    legacy = json.dumps({"refresh_token": "x", "client_id": "y"})
    with pytest.raises(msgraph.ProviderError) as refused:
        credentials({"MICROSOFT_ACCOUNT_TOKEN": ("just-a-token", "environment")})
    assert "unreadable or incomplete" in str(refused.value) and ACCOUNT.auth_command in str(refused.value)
    (rec, _), _, _ = credentials({"MICROSOFT_ACCOUNT_TOKEN": ("just-a-token", "environment"), "OUTLOOK_MAIL_TOKEN": (legacy, "environment")})
    assert "slot" not in rec


def test_the_legacy_note_is_once_per_record_and_per_process_and_holds_no_content(capsys):
    legacy = json.dumps({"refresh_token": "secret-looking-refresh", "client_id": "y"})  # security-scan: allow secret-assignment -- a made-up value for a test that checks nothing prints it; no real account has it
    msgraph._NOTED_LEGACY.clear()
    for _ in range(3):
        credentials({"OUTLOOK_MAIL_TOKEN": (legacy, "environment")})
    err = capsys.readouterr().err
    assert err.count("using the legacy record outlook-mail") == 1 and ACCOUNT.auth_command in err and "secret-looking" not in err
    other = msgraph.Profile(label="OneDrive", scope="Files.Read", secret="ONEDRIVE_SOURCES_TOKEN", keyring_username="onedrive-sources",
                            auth_command="c", run_hint="r", env_prefix="Z_TEST", user_agent="u", not_found="n", forbidden_hint="f",
                            client_id_var="C", tenant_var="T")
    resolver_ = Resolver({"ONEDRIVE_SOURCES_TOKEN": (legacy, "environment")})
    msgraph.load_credentials(other, ACCOUNT, lambda: resolver_, True)
    assert "using the legacy record onedrive-sources" in capsys.readouterr().err, "each legacy record is told once"


# --- the account's address --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value, kept", [("casey.rivera@mail.example", True), ("a@b", True), ("x" * 300 + "@mail.example", True), ("no-at-sign", False),
                                         ("@lead.example", False), ("trail@", False), ("a b@mail.example", False), ("a\nb@mail.example", False),
                                         ("café@mail.example", False), ("", False), (None, False), (5, False), ("x" * 330 + "@mail.example", False)])
def test_only_a_plain_address_is_kept_as_the_accounts_name(value, kept):
    assert msgraph.clean_address(value) == (value if kept else None)


# --- the static facts the limits rest on ----------------------------------------------------------------------------------------------


def test_l58_the_graph_client_and_the_three_readers_send_no_write_method_to_graph():
    shared = (PROVIDERS / "_msgraph.py").read_text(encoding="utf-8")
    for method in ("PUT", "PATCH", "DELETE"):
        assert f'"{method}"' not in shared and f"'{method}'" not in shared, method
    posts = re.findall(r'http\("POST"', shared)
    assert len(posts) == 1 and shared.split('http("POST"')[0].rsplit("def ", 1)[1].startswith("token_request("), "the token endpoint is the one POST"
    client = shared.split("class GraphClient:", 1)[1].split("# --- the authorization command", 1)[0]
    assert 'http("GET"' in client and not re.search(r'http\("(?!GET)[A-Z]+"', client)
    for path in READER_FILES:
        code = re.sub(r'"""[\s\S]*?"""', "", path.read_text(encoding="utf-8"))
        assert not re.search(r'"(POST|PUT|PATCH|DELETE)"', code), path.name
        assert not re.search(r"\.(post|put|patch|delete)\(", code), path.name


def test_l57_no_script_of_the_account_work_holds_a_permanent_delete_call():
    for path in (PROVIDERS / "_msgraph.py", PROVIDERS / "accounts" / "microsoft_auth.py", *READER_FILES):
        code = re.sub(r'"""[\s\S]*?"""', "", path.read_text(encoding="utf-8"))
        for word in ("permanentDelete", "batchDelete", "emptyTrash", "DELETE"):
            assert word not in code, (path.name, word)


def test_l59_the_account_secret_reaches_a_provider_process_through_one_name_and_a_run_never_gets_it():
    env = {"PATH": "/usr/bin", "MICROSOFT_ACCOUNT_TOKEN": '{"refresh_token": "x"}', "OUTLOOK_MAIL_TOKEN": "legacy", "ONEDRIVE_SOURCES_TOKEN": "legacy",
           "VCS_GITHUB_TOKEN": "t", "MAILBOX_PROVIDER": "outlook"}
    for cls in ("reader:email", "integration:calendar", "integration:documents"):
        passed = resolve.provider_environment(cls, env, ("MICROSOFT_ACCOUNT_TOKEN",))
        assert passed["MICROSOFT_ACCOUNT_TOKEN"] == env["MICROSOFT_ACCOUNT_TOKEN"], cls
        assert "VCS_GITHUB_TOKEN" not in passed and "OUTLOOK_MAIL_TOKEN" not in passed and "ONEDRIVE_SOURCES_TOKEN" not in passed, cls
    without = resolve.provider_environment("reader:email", env)
    assert "MICROSOFT_ACCOUNT_TOKEN" not in without, "a provider is given only the secrets it is named for"


def test_l59_the_registry_row_names_the_set_the_record_and_the_readers_and_the_resolver_finds_it_in_the_environment():
    secret = resolver.REGISTRY["MICROSOFT_ACCOUNT_TOKEN"]
    assert secret.store_username == "microsoft-account" and secret.aliases == ()
    for name in PLATFORM:
        assert name in secret.permission
    assert "providers/accounts/microsoft_auth.py" in secret.readers and "providers/_msgraph.py" in secret.readers
    for path in READER_FILES:
        assert str(path.relative_to(REPO)) in secret.readers
    found = resolver.resolve("MICROSOFT_ACCOUNT_TOKEN", environ={"MICROSOFT_ACCOUNT_TOKEN": '{"slot": "main"}'}, store=None)
    assert found == ('{"slot": "main"}', "environment (MICROSOFT_ACCOUNT_TOKEN)")
    shown = json.dumps(resolver.report(environ={"MICROSOFT_ACCOUNT_TOKEN": "sentinel-value-not-real"}, store=None))  # security-scan: allow secret-assignment -- a made-up value for a test that checks nothing prints it; no real account has it
    assert "sentinel-value-not-real" not in shown, "the report never prints a value"
