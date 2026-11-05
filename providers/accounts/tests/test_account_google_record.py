"""Tests of the shared Google module (providers/_google.py): the platform's scope set and the check made on every token response, the account
record, the order in which a provider looks (the account record, then its legacy one with a warning once per process), and the scrub that keeps
a credential out of any printed text. No network: the one test of a refresh uses the stand-in service on 127.0.0.1.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_google_record.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_google_account as fga  # noqa: E402

_spec = importlib.util.spec_from_file_location("google_shared_under_test", REPO / "providers" / "_google.py")
google = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(google)

COMMAND = "google_auth.py authorize"
SET = " ".join(fga.PLATFORM_SET)


class Boom(Exception):
    def __init__(self, message, code=1, status=None):
        super().__init__(message)
        self.code = code


class Resolver:
    """A stand-in for providers/secrets/resolver.py: what it is asked and what it answers."""

    def __init__(self, values=None):
        self.values, self.asked = values or {}, []

    def resolve_state(self, name, allow_store=True):
        self.asked.append((name, allow_store))
        found = self.values.get(name)
        if found is None:
            return SimpleNamespace(state="missing", value="", source=None, detail="")
        return SimpleNamespace(state="found", value=found[0], source=found[1], detail="")


@pytest.fixture(autouse=True)
def fresh_process_state():
    """The module keeps two process-wide lists (what it must scrub, which legacy warnings it printed): start every test from empty ones."""
    google._SECRET_VALUES.clear()
    google._WARNED.clear()
    yield
    google._SECRET_VALUES.clear()
    google._WARNED.clear()


def record_text(**over):
    record = {"slot": "main", "refresh_token": fga.REFRESH_TOKEN, "client_id": fga.CLIENT_ID, "client_secret": fga.CLIENT_SECRET,
              "scope": SET, "account": fga.ACCOUNT, "obtained_at": "2026-10-18T09:00:00Z"}
    record.update(over)
    return json.dumps({k: v for k, v in record.items() if v is not None})


# --- the scope set --------------------------------------------------------------------------------------------------------


def test_the_platform_set_is_the_five_scopes_the_decision_names_and_the_previous_set_the_four_of_before_google_tasks():
    assert google.PLATFORM_SCOPES == fga.PLATFORM_SET and google.PREVIOUS_SCOPES == fga.PREVIOUS_SET and google.PLATFORM_SCOPES == google.PREVIOUS_SCOPES + (google.TASKS_SCOPE,)
    assert google.TASKS_SCOPE == fga.TASKS and google.TASKS_SCOPE.endswith("/auth/tasks")
    assert google.GMAIL_SCOPE.endswith("/gmail.modify") and google.DRIVE_SCOPE.endswith("/auth/drive")
    assert google.CALENDAR_EVENTS_SCOPE.endswith("/calendar.events") and google.CALENDAR_LIST_SCOPE.endswith("/calendar.calendarlist.readonly")
    assert "https://mail.google.com/" not in google.PLATFORM_SCOPES, "the scope that deletes permanently is never asked"


def test_exactly_the_set_passes_in_any_order_with_or_without_identity_words():
    google.check_platform_scope(SET, None, Boom)
    google.check_platform_scope(" ".join(reversed(fga.PLATFORM_SET)), None, Boom)
    google.check_platform_scope("openid email profile " + SET, None, Boom)
    google.check_platform_scope(SET + " https://www.googleapis.com/auth/userinfo.email", None, Boom)


@pytest.mark.parametrize("granted", [" ".join(fga.PLATFORM_SET[1:]), " ".join(fga.PLATFORM_SET[:3] + (fga.TASKS,)), fga.GMAIL_MODIFY,
                                     f"{fga.GMAIL_READONLY} {fga.CALENDAR_EVENTS} {fga.CALENDAR_LIST} {fga.DRIVE}"])
def test_a_token_that_lacks_a_scope_is_refused_with_exit_3_and_the_command(granted):
    with pytest.raises(Boom) as refused:
        google.check_platform_scope(granted, None, Boom)
    assert refused.value.code == 3 and "lacks" in str(refused.value) and COMMAND in str(refused.value)
    assert "keep every box ticked" in str(refused.value) and "nothing was read" in str(refused.value)


@pytest.mark.parametrize("extra", [fga.MAIL_ALL, "https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/drive.file",
                                   "https://www.googleapis.com/auth/contacts"])
def test_a_token_that_carries_another_scope_is_refused_with_exit_3_and_how_to_revoke(extra):
    with pytest.raises(Boom) as refused:
        google.check_platform_scope(SET + " " + extra, None, Boom)
    assert refused.value.code == 3 and extra in str(refused.value) and "does not ask" in str(refused.value)
    assert "Revoke the app's access" in str(refused.value) and COMMAND in str(refused.value)


def test_a_token_that_both_lacks_and_carries_says_both():
    with pytest.raises(Boom) as refused:
        google.check_platform_scope(" ".join(fga.PLATFORM_SET[:3]) + " " + fga.MAIL_ALL, None, Boom)
    assert fga.DRIVE in str(refused.value) and fga.MAIL_ALL in str(refused.value)


def test_a_response_that_omits_the_scope_passes_only_when_the_stored_scope_is_the_set():
    google.check_platform_scope(None, SET, Boom)
    google.check_platform_scope("", SET, Boom)
    for stored in (None, "", " ".join(fga.PLATFORM_SET[:3]), SET + " " + fga.MAIL_ALL):
        with pytest.raises(Boom) as refused:
            google.check_platform_scope(None, stored, Boom)
        assert refused.value.code == 3
    with pytest.raises(Boom):
        google.check_platform_scope(" ".join(fga.PLATFORM_SET[:3]), SET, Boom)   # a named scope is never overruled by the stored one


def test_the_outcome_ends_the_message_and_the_default_error_carries_the_exit_code():
    with pytest.raises(google.AccountError) as refused:
        google.check_platform_scope(fga.GMAIL_MODIFY, None, google.AccountError, "nothing stored")
    assert str(refused.value).count("nothing stored") == 1 and refused.value.code == google.EXIT_NOT_CONFIGURED


# --- the record -----------------------------------------------------------------------------------------------------------


def test_a_complete_record_is_read_with_its_slot_scope_account_and_date():
    record = google.parse_account_record(record_text(), Boom)
    assert record == {"refresh_token": fga.REFRESH_TOKEN, "client_id": fga.CLIENT_ID, "client_secret": fga.CLIENT_SECRET, "slot": "main",
                      "scope": SET, "account": fga.ACCOUNT, "obtained_at": "2026-10-18T09:00:00Z"}
    bare = google.parse_account_record(record_text(slot=None, scope=None, account=None, obtained_at=None), Boom)
    assert bare["slot"] == "main" and bare["scope"] == "" and bare["account"] is None and bare["obtained_at"] is None


@pytest.mark.parametrize("text", ["", "not json", "[]", "null", json.dumps({"refresh_token": "x"}), record_text(refresh_token=""),
                                  record_text(client_id=5), record_text(client_secret="has a space"), record_text(refresh_token="a\tb")])
def test_an_unreadable_or_incomplete_record_is_not_configured(text):
    with pytest.raises(Boom) as refused:
        google.parse_account_record(text, Boom)
    assert refused.value.code == 3 and COMMAND in str(refused.value)


def test_another_slot_is_refused_because_only_main_exists():
    with pytest.raises(Boom) as refused:
        google.parse_account_record(record_text(slot="work"), Boom)
    assert refused.value.code == 3 and "only the slot 'main' exists" in str(refused.value)
    assert google.check_slot("main", Boom) == "main"
    for bad in ("work", "Main", "", "a" * 13, None, "a b"):
        with pytest.raises(Boom) as usage:
            google.check_slot(bad, Boom)
        assert usage.value.code == 2


def test_a_credential_the_module_held_is_scrubbed_from_any_text():
    google.parse_account_record(record_text(), Boom)
    text = f"failed with {fga.REFRESH_TOKEN} and {fga.CLIENT_SECRET} and {fga.CLIENT_ID}"
    scrubbed = google.scrub(text)
    assert scrubbed == "failed with <hidden> and <hidden> and <hidden>"
    assert fga.REFRESH_TOKEN not in google.one_line(f"the {fga.REFRESH_TOKEN}\n token")


# --- the order a provider looks -------------------------------------------------------------------------------------------


def test_the_account_record_is_read_first_through_the_resolver_and_the_store_is_allowed_outside_test_mode():
    resolver = Resolver({"GOOGLE_ACCOUNT_TOKEN": (record_text(), "secret store")})
    loaded = google.load_account_record(resolver, False, error=Boom)
    assert loaded.legacy is None and loaded.source == "secret store" and loaded.record["refresh_token"] == fga.REFRESH_TOKEN
    assert resolver.asked == [("GOOGLE_ACCOUNT_TOKEN", True)]
    google.load_account_record(resolver, True, error=Boom)
    assert resolver.asked[-1] == ("GOOGLE_ACCOUNT_TOKEN", False), "test mode never reads the OS secret store"


def test_the_account_record_wins_over_a_legacy_one_and_the_legacy_loader_is_not_even_called(capsys):
    resolver = Resolver({"GOOGLE_ACCOUNT_TOKEN": (record_text(), "environment (GOOGLE_ACCOUNT_TOKEN)")})
    called = []
    loaded = google.load_account_record(resolver, True, legacy=("mailbox-gmail", lambda: called.append(1), "old command"), error=Boom)
    assert loaded.legacy is None and called == []
    assert capsys.readouterr().err == ""


def test_a_legacy_record_serves_when_there_is_no_account_record_with_one_warning_per_process_and_username(capsys):
    legacy = {"refresh_token": "fake-legacy-refresh-not-real", "client_id": "id", "client_secret": "fake-legacy-client-secret-not-real"}
    spec = ("calendar-google", lambda: (legacy, "environment (GOOGLE_CALENDAR_TOKEN)"), "uv run old/google_auth.py authorize")
    first = google.load_account_record(Resolver(), True, legacy=spec, error=Boom)
    second = google.load_account_record(Resolver(), True, legacy=spec, error=Boom)
    other = google.load_account_record(Resolver(), True, legacy=("gdrive-sources", spec[1], spec[2]), error=Boom)
    assert first.legacy == second.legacy == "calendar-google" and other.legacy == "gdrive-sources"
    assert first.record is legacy and first.source == "environment (GOOGLE_CALENDAR_TOKEN)"
    err = capsys.readouterr().err
    assert err.count("legacy record calendar-google") == 1 and err.count("legacy record gdrive-sources") == 1
    assert COMMAND in err and "move to the account token" in err
    assert "fake-legacy-refresh-not-real" not in err and google.scrub("fake-legacy-client-secret-not-real") == "<hidden>", "its secrets are held for the scrub"


def test_nothing_found_names_the_new_command_and_the_legacy_one():
    with pytest.raises(Boom) as refused:
        google.load_account_record(Resolver(), True, legacy=("gdrive-sources", lambda: None, "uv run old/gdrive_auth.py authorize"), error=Boom)
    assert refused.value.code == 3 and COMMAND in str(refused.value) and "old/gdrive_auth.py authorize" in str(refused.value)
    assert "GOOGLE_ACCOUNT_TOKEN" in str(refused.value)
    with pytest.raises(Boom) as no_legacy:
        google.load_account_record(Resolver(), True, error=Boom)
    assert no_legacy.value.code == 3 and COMMAND in str(no_legacy.value)


def test_an_unreadable_account_record_is_an_error_and_never_a_reason_to_fall_back(capsys):
    resolver = Resolver({"GOOGLE_ACCOUNT_TOKEN": ("{broken", "secret store")})
    legacy = ("mailbox-gmail", lambda: ({"refresh_token": "r", "client_id": "i", "client_secret": "s"}, "x"), "old")
    with pytest.raises(Boom) as refused:
        google.load_account_record(resolver, False, legacy=legacy, error=Boom)
    assert refused.value.code == 3 and "unreadable or incomplete" in str(refused.value)
    assert "GOOGLE_ACCOUNT_TOKEN" in str(refused.value) and "google-account" in str(refused.value), "the message names the record"
    assert capsys.readouterr().err == "", "no legacy warning: the legacy record was not used"


def test_only_the_slot_main_is_looked_up():
    resolver = Resolver()
    with pytest.raises(Boom) as refused:
        google.find_account_record(resolver, True, "work", Boom)
    assert refused.value.code == 2 and resolver.asked == []


# --- the token endpoint ---------------------------------------------------------------------------------------------------


def test_a_refresh_checks_the_scope_of_the_answer_and_holds_the_tokens_for_the_scrub():
    fake = fga.FakeGoogleAccount()
    try:
        record = google.parse_account_record(record_text(), Boom)
        data = google.refresh_access_token(fake.token_url, record, Boom)
        assert data["access_token"] == fga.ACCESS_TOKEN and google.scrub(fga.ACCESS_TOKEN) == "<hidden>"
        form_list = [r for r in fake.requests if r["path"] == "/token"]
        assert len(form_list) == 1 and form_list[0]["method"] == "POST"
        fake.refresh_scope = " ".join(fga.PLATFORM_SET[:2])
        with pytest.raises(Boom) as lacking:
            google.refresh_access_token(fake.token_url, record, Boom)
        assert lacking.value.code == 3
        fake.refresh_scope = None
        assert google.refresh_access_token(fake.token_url, record, Boom)["access_token"] == fga.ACCESS_TOKEN, "the stored scope is the set"
        with pytest.raises(Boom):
            google.refresh_access_token(fake.token_url, {**record, "scope": ""}, Boom)
        fake.token_error = "invalid_grant"
        with pytest.raises(Boom) as revoked:
            google.refresh_access_token(fake.token_url, record, Boom)
        assert revoked.value.code == 3 and "In production" in str(revoked.value) and COMMAND in str(revoked.value)
        fake.token_error = None
        with pytest.raises(Boom) as wrong_client:
            google.refresh_access_token(fake.token_url, {**record, "client_id": "someone-else"}, Boom)
        assert wrong_client.value.code == 3 and "rejected the OAuth client" in str(wrong_client.value)
    finally:
        fake.close()


def test_a_token_of_an_odd_shape_is_refused_and_no_redirect_is_followed():
    fake = fga.FakeGoogleAccount()
    try:
        record = google.parse_account_record(record_text(), Boom)
        original = fake.token
        fake.token = lambda form: (200, {"access_token": "good\r\nX-Injected: yes", "scope": SET})
        with pytest.raises(Boom) as odd:
            google.refresh_access_token(fake.token_url, record, Boom)
        assert "unexpected shape" in str(odd.value) and "Injected" not in str(odd.value)
        fake.token = original
        fake.redirect_token = True
        with pytest.raises(Boom) as redirected:
            google.refresh_access_token(fake.token_url, record, Boom)
        assert "refusing to follow a 302 redirect" in str(redirected.value) and "the request carries a credential" in str(redirected.value)
        assert fake.methods() == [("POST", "/token"), ("POST", "/token")], "the address in the Location header was never asked"
    finally:
        fake.close()


def test_the_module_sends_get_and_the_token_post_and_no_other_method():
    source = (REPO / "providers" / "_google.py").read_text(encoding="utf-8")
    import re
    assert set(re.findall(r'_send\("(\w+)"', source)) == {"GET", "POST"}
    for method in ("PUT", "PATCH", "DELETE", "HEAD"):
        assert f'"{method}"' not in source


def test_the_module_runs_on_python_3_9_syntax():
    import ast
    tree = ast.parse((REPO / "providers" / "_google.py").read_text(encoding="utf-8"), feature_version=(3, 9))
    assert tree is not None


def test_resolve_never_lists_the_accounts_folder_and_the_module_is_not_a_provider():
    spec = importlib.util.spec_from_file_location("providers_resolve_under_test", REPO / "providers" / "resolve.py")
    resolve = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = resolve
    spec.loader.exec_module(resolve)
    assert (REPO / "providers" / "accounts" / "google_auth.py").is_file()
    assert resolve.implementations_in("accounts", root=REPO) == [], "an authorization helper is not an implementation of any class"
    listed = json.loads(subprocess.run([sys.executable, str(REPO / "providers" / "resolve.py"), "--list", "--root", str(REPO)],
                                       capture_output=True, text=True, timeout=60).stdout)
    assert not [c for c in listed["classes"] if "accounts" in c["folder"] or c["implementations"] and "google_auth" in c["implementations"]]
    assert "_google" not in {name for c in listed["classes"] for name in c["implementations"]}
    refused = subprocess.run([sys.executable, str(REPO / "providers" / "resolve.py"), "--class", "integration:accounts", "--root", str(REPO)],
                             capture_output=True, text=True, timeout=60)
    assert refused.returncode == 3 and "has none" in refused.stderr
