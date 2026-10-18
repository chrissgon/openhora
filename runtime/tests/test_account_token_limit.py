"""Limit L59 (package ACCT-G, with ACCT-M): the account token of the person's own Google or Microsoft account is read only by a provider process
the runtime starts with that one secret in its environment (the minimum environment plus the account token of its service and, for one cycle,
its legacy record), and it never enters a run, a prompt, a manifest, a card, a log or the store. These are the runtime's tests: which names a
source operation hands each provider, and that no run's environment, no catalog and no file of the sources holds them. The scope rule ("exactly
the platform's set, the authorize command named otherwise") and the printed output of each provider are tested where the providers are:
providers/accounts/tests/test_account_google_readers.py, test_limit_59_the_account_token_is_in_no_output_error_or_file_whatever_goes_wrong.
Stand-in values only; no real credential, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_account_token_limit.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st

REPO = st.REPO
sources = st.load("sources")
sources_mail = st.load("sources_mail")
sources_onedrive = st.load("sources_onedrive")
lab = st.load("lab")

_spec = importlib.util.spec_from_file_location("resolve_for_account_token_tests", REPO / "providers" / "resolve.py")
resolve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve)

GOOGLE, MICROSOFT = "GOOGLE_ACCOUNT_TOKEN", "MICROSOFT_ACCOUNT_TOKEN"
LEGACY = ("GMAIL_REFRESH_TOKEN", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GOOGLE_CALENDAR_TOKEN", "GDRIVE_SOURCES_TOKEN", "OUTLOOK_MAIL_TOKEN",
          "OUTLOOK_CALENDAR_TOKEN", "ONEDRIVE_SOURCES_TOKEN")
# (class, implementation, the secrets the runtime hands that provider, from the module that hands them)
PROVIDERS = [
    ("reader:email", "gmail", lambda: sources_mail.SECRETS[("reader:email", "gmail")], (GOOGLE, "GMAIL_REFRESH_TOKEN", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET")),
    ("reader:email", "outlook", lambda: sources_mail.SECRETS[("reader:email", "outlook")], (MICROSOFT, "OUTLOOK_MAIL_TOKEN")),
    ("integration:calendar", "google", lambda: sources_mail.SECRETS[("integration:calendar", "google")], (GOOGLE, "GOOGLE_CALENDAR_TOKEN")),
    ("integration:calendar", "outlook", lambda: sources_mail.SECRETS[("integration:calendar", "outlook")], (MICROSOFT, "OUTLOOK_CALENDAR_TOKEN")),
    ("integration:documents", "gdrive", lambda: sources.DRIVE_SECRETS, (GOOGLE, "GDRIVE_SOURCES_TOKEN")),
    ("integration:documents", "onedrive", lambda: sources_onedrive.ONEDRIVE_SECRETS, (MICROSOFT, "ONEDRIVE_SOURCES_TOKEN")),
]


@pytest.fixture
def cfg():
    return {"workbench": str(REPO)}


@pytest.mark.parametrize("cls, implementation, handed, expected", PROVIDERS, ids=[f"{c}-{i}" for c, i, _, _ in PROVIDERS])
def test_limit_59_a_provider_is_handed_its_services_account_token_and_its_legacy_record_and_no_other_secret(cfg, monkeypatch, cls, implementation,
                                                                                                         handed, expected):
    assert tuple(handed()) == expected, "the account token first, then the legacy record(s) of the same purpose"
    everything = (GOOGLE, MICROSOFT) + LEGACY + ("OPENROUTER_API_KEY", "VCS_GITHUB_TOKEN", "NOTION_TOKEN", "NOTION_SOURCES_TOKEN")
    for name in everything:
        monkeypatch.setenv(name, f"value-of-{name}")
    env = sources._provider_env(cfg, cls, tuple(handed()))
    for name in expected:
        assert env[name] == f"value-of-{name}"
    allowed = set(resolve.ENV_MINIMUM) | set(expected)
    assert set(env) <= allowed, sorted(set(env) - allowed)
    other = MICROSOFT if GOOGLE in expected else GOOGLE
    assert other not in env, "a provider is never given the account token of the other service"


def test_limit_59_the_converter_and_the_other_providers_are_given_no_account_token(cfg, monkeypatch):
    for name in (GOOGLE, MICROSOFT, "NOTION_SOURCES_TOKEN"):
        monkeypatch.setenv(name, f"value-of-{name}")
    for_converter = sources._provider_env(cfg, sources.CONVERTER_CLASS)
    assert GOOGLE not in for_converter and MICROSOFT not in for_converter
    for_notion = sources._provider_env(cfg, sources.NOTION_CLASS, (sources.NOTION_SECRET,))
    assert GOOGLE not in for_notion and MICROSOFT not in for_notion and for_notion["NOTION_SOURCES_TOKEN"] == "value-of-NOTION_SOURCES_TOKEN"


def test_limit_59_the_environment_of_a_run_holds_no_account_token_whatever_the_model_passes(monkeypatch, tmp_path):
    values = {GOOGLE: "fake-google-refresh-not-real-1a", MICROSOFT: "fake-microsoft-refresh-not-real-2b"}
    for name, refresh in values.items():
        monkeypatch.setenv(name, json.dumps({"slot": "main", "refresh_token": refresh, "client_id": "fake-client-id.example",
                                             "client_secret": "fake-client-secret-not-real"}))
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    passed = sorted({n for found in gate["models"].values() for n in found.get("pass_env", []) + found.get("web_pass_env", [])})
    assert not {GOOGLE, MICROSOFT} & set(passed), "no model's credential list names an account token"
    # The environment of a real run, built the way the lab builds it for every model and with every variable any model passes: first with
    # nothing passed, then with the whole union (the account tokens are in this process's environment, so a leak would show).
    for names in ((), tuple(passed)):
        env = lab.LAB.contained_env(str(tmp_path / f"run-{len(names)}"), names)
        text = json.dumps(env)
        assert not {GOOGLE, MICROSOFT} & set(env), "neither account token name is in a run's environment"
        for needle in (*values.values(), "fake-client-secret-not-real", "fake-client-id.example"):
            assert needle not in text, f"{needle} is in a run's environment"


def test_limit_59_the_account_token_is_registered_for_providers_only_and_under_its_own_store_name():
    spec = importlib.util.spec_from_file_location("resolver_for_account_token_tests", REPO / "providers" / "secrets" / "resolver.py")
    resolver = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = resolver
    spec.loader.exec_module(resolver)
    google = resolver.REGISTRY[GOOGLE]
    assert google.store_username == "google-account" and google.aliases == ()
    assert all(reader.startswith("providers/") for reader in google.readers), "only provider scripts read it"
    assert not any(reader.startswith(("runtime/", "scripts/", "evals/", "adapters/")) for reader in google.readers)
    runtime_text = "\n".join(p.read_text(encoding="utf-8") for p in (REPO / "runtime").glob("*.py") if p.name != "__init__.py")
    assert "get_password" not in runtime_text and "keyring.get" not in runtime_text, "the runtime never reads the store itself"


# --- what the real calls of the Drive and OneDrive modules hand a provider (captured as test_sources_mail.py does) -------------------


def capture_resolver(monkeypatch):
    seen = {}

    def capture(cls, verb, args, **kwargs):
        seen.update(cls=cls, verb=verb, args=list(args), kwargs=kwargs)
        return {"items": [], "count": 0, "truncated": False}
    monkeypatch.setitem(sys.modules, "workbench_sources_resolve", SimpleNamespace(call=capture, provider_environment=resolve.provider_environment))
    return seen


def set_everything(monkeypatch):
    for name in (GOOGLE, MICROSOFT) + LEGACY + ("OPENROUTER_API_KEY", "VCS_GITHUB_TOKEN", "NOTION_TOKEN", "NOTION_SOURCES_TOKEN"):
        monkeypatch.setenv(name, f"value-of-{name}")


def test_limit_59_the_real_drive_call_hands_the_provider_the_google_account_token_and_its_legacy_record_and_nothing_else(cfg, monkeypatch):
    set_everything(monkeypatch)
    seen = capture_resolver(monkeypatch)
    sources.drive_call(cfg, "stat", ["--id", "x", "--as-source"])
    env = seen["kwargs"]["env"]
    assert (seen["cls"], seen["kwargs"]["implementation"]) == ("integration:documents", "gdrive")
    assert {GOOGLE, "GDRIVE_SOURCES_TOKEN"} <= set(env) and MICROSOFT not in env
    assert set(env) <= set(resolve.ENV_MINIMUM) | {GOOGLE, "GDRIVE_SOURCES_TOKEN"}, sorted(set(env) - set(resolve.ENV_MINIMUM))


def test_limit_59_the_real_onedrive_call_hands_the_provider_the_microsoft_account_token_and_its_legacy_record_and_nothing_else(cfg, monkeypatch):
    set_everything(monkeypatch)
    seen = capture_resolver(monkeypatch)
    sources_onedrive.onedrive_call(cfg, "search", ["--query", "notes"])
    env = seen["kwargs"]["env"]
    assert (seen["cls"], seen["kwargs"]["implementation"]) == ("integration:documents", "onedrive")
    assert {MICROSOFT, "ONEDRIVE_SOURCES_TOKEN"} <= set(env) and GOOGLE not in env
    assert set(env) <= set(resolve.ENV_MINIMUM) | {MICROSOFT, "ONEDRIVE_SOURCES_TOKEN"}, sorted(set(env) - set(resolve.ENV_MINIMUM))


def test_limit_59_the_picker_is_handed_the_legacy_record_it_reads_and_never_the_account_token(cfg, monkeypatch):
    set_everything(monkeypatch)
    capture_resolver(monkeypatch)
    seen = {}

    def run(argv, env, timeout):
        seen.update(argv=argv, env=env)
        return 0, json.dumps({"picked": [], "cancelled": True})
    sources.pick_drive(cfg, run=run)
    assert seen["argv"] == ["pick"]
    assert seen["env"]["GDRIVE_SOURCES_TOKEN"] == "value-of-GDRIVE_SOURCES_TOKEN"
    assert GOOGLE not in seen["env"] and MICROSOFT not in seen["env"], "the Picker reads the legacy record alone"
    assert set(seen["env"]) <= set(resolve.ENV_MINIMUM) | {"GDRIVE_SOURCES_TOKEN"}


# --- the credential scan of the runtime knows the account tokens' formats (limit L6) ------------------------------------------------

GOOGLE_RECORD = json.dumps({"slot": "main", "refresh_token": "1//0gFakeRefreshNotReal0123456789abcdefXYZ", "client_id": "fake-client-id.example",
                            "client_secret": "GOCSPX-FakeNotReal0123456789abcdefgh", "scope": "x", "account": "pat@example.com"})
MICROSOFT_RECORD = json.dumps({"refresh_token": "0.AFakeNotRealMicrosoft0123456789abcdefXYZ", "client_id": "fake-client-id.example",
                               "tenant": "common", "scope": "Mail.ReadWrite"})


@pytest.mark.parametrize("text", [
    GOOGLE_RECORD, MICROSOFT_RECORD,
    f"export GOOGLE_ACCOUNT_TOKEN='{GOOGLE_RECORD}'", f"MICROSOFT_ACCOUNT_TOKEN={MICROSOFT_RECORD}",
    "GOOGLE_ACCOUNT_TOKEN: {\"refresh_token\": \"x\"}",
    "1//0gFakeRefreshNotReal0123456789abcdefXYZ", "GOCSPX-FakeNotReal0123456789abcdefgh", "ya29.a0FakeNotReal0123456789abcdefghijklmnop",
    "refresh_token = 'fake-microsoft-refresh-0123456789abc'", "client_secret: \"fake-client-secret-not-real-0123\"",
    "notes: the token is 1//0gFakeRefreshNotReal0123456789abcdefXYZ, keep it",
], ids=["google-record", "microsoft-record", "export-line", "microsoft-assignment", "assigned-object", "bare-refresh", "bare-client-secret",
        "bare-access", "key-equals", "key-colon", "inside-prose"])
def test_the_credential_scan_finds_the_account_token_formats(text):
    assert st.load("workcopy").credential_findings(text), text


@pytest.mark.parametrize("text", [
    "GOOGLE_ACCOUNT_TOKEN is the secret that holds the record", "export GOOGLE_ACCOUNT_TOKEN=<the JSON record>", "refresh_token: <your refresh token>",
    "the client_secret field is typed at a hidden prompt", "refresh_token = 'short'", "see https://example.com/a//0path/segment",
    "{\"refresh_token\": \"no-digit-here-just-words-in-it\"}", "API_KEY=<x>",
], ids=["name-only", "placeholder-record", "placeholder-key", "prose", "short", "url", "words-only", "existing-placeholder"])
def test_the_credential_scan_leaves_a_name_a_placeholder_and_plain_words_alone(text):
    assert st.load("workcopy").credential_findings(text) == [], text
