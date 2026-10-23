"""Tests of the Outlook calendar authorization command (providers/calendar/outlook_auth.py), against the stand-in service (fake_graph_cal.py) and a
small browser made of http.client. The command shares its code with the mail and OneDrive ones (providers/_msgraph.py, tested through the mail
and OneDrive suites); what is tested here is what is the calendar's own: its one permission, Calendars.ReadBasic, in the consent URL and in the
check; its client id and tenant variables; its record, kept apart from the mail one; and that a registration which also holds another purpose's
permission is refused. No Microsoft host is reached and no real credential exists.

Run: uv run --with pytest==9.1.1 pytest providers/calendar/tests/test_calendar_outlook_auth.py
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import os
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "outlook_auth.py"
sys.path.insert(0, str(HERE))
import fake_graph_cal  # noqa: E402

_spec = importlib.util.spec_from_file_location("outlook_calendar_auth_under_test", SCRIPT)
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)
oc = auth.outlook

SECRETS = (fake_graph_cal.ACCESS_TOKEN, fake_graph_cal.REFRESH_TOKEN, fake_graph_cal.CODE)
KEY = ("openhora", "outlook-calendar")


class Store:
    def __init__(self, fail=False):
        self.values, self.fail = {}, fail

    def set_password(self, service, username, value):
        if self.fail:
            raise RuntimeError("the secret store is locked")
        self.values[(service, username)] = value

    def delete_password(self, service, username):
        if (service, username) not in self.values:
            raise type("PasswordDeleteError", (Exception,), {})("not found")
        del self.values[(service, username)]


def callback(port, query):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.putrequest("GET", "/?" + urllib.parse.urlencode(query), skip_host=True)
    c.putheader("Host", f"localhost:{port}")
    c.endheaders()
    r = c.getresponse()
    out = (r.status, dict(r.getheaders()), r.read())
    c.close()
    return out


def consent_query(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def port_of(url):
    return int(urllib.parse.urlparse(consent_query(url)["redirect_uri"][0]).port)


@pytest.fixture
def fake():
    f = fake_graph_cal.FakeGraphCal()
    yield f
    f.close()


@pytest.fixture
def env(fake, monkeypatch):
    for key, value in fake.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("OUTLOOK_CALENDAR_TOKEN")
    monkeypatch.setenv("OUTLOOK_CALENDAR_CLIENT_ID", fake_graph_cal.CLIENT_ID)
    monkeypatch.delenv("OUTLOOK_CALENDAR_TENANT", raising=False)
    store = Store()
    monkeypatch.setattr(oc, "keyring_module", lambda test_mode: store)
    return store


def browser(monkeypatch, then):
    seen = {}

    def open_url(url):
        seen["url"] = url
        threading.Thread(target=then, args=(url, seen), daemon=True).start()

    monkeypatch.setattr(auth.webbrowser, "open", open_url)
    return seen


def returns_with_the_code(url, seen):
    seen["callback"] = callback(port_of(url), {"code": fake_graph_cal.CODE, "state": consent_query(url)["state"][0]})


def test_the_consent_url_asks_for_calendars_readbasic_and_offline_access_alone():
    verifier, challenge = auth.pkce_pair()
    url = auth.authorize_url(fake_graph_cal.CLIENT_ID, "common", "http://localhost:5555", "the-state", challenge)
    query = consent_query(url)
    assert url.startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize?")
    assert query["scope"] == ["https://graph.microsoft.com/Calendars.ReadBasic offline_access"]
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"] == [challenge] and query["state"] == ["the-state"]
    assert "client_secret" not in query and "login_hint" not in query and "include_granted_scopes" not in query
    assert auth.outlook.REFRESH_SCOPE == "https://graph.microsoft.com/Calendars.ReadBasic offline_access"
    assert auth.CLIENT_ID_VAR == "OUTLOOK_CALENDAR_CLIENT_ID" and auth.TENANT_VAR == "OUTLOOK_CALENDAR_TENANT"


def test_the_client_id_comes_from_the_calendars_own_variable_and_never_from_the_mails(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.delenv("OUTLOOK_CALENDAR_CLIENT_ID", raising=False)
    monkeypatch.setenv("OUTLOOK_MAIL_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setenv("ONEDRIVE_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    with pytest.raises(auth.ProviderError) as missing:
        auth.client_inputs()
    assert missing.value.code == 3 and "OUTLOOK_CALENDAR_CLIENT_ID" in str(missing.value), "another purpose's client id is not borrowed"
    monkeypatch.setenv("OUTLOOK_CALENDAR_CLIENT_ID", fake_graph_cal.CLIENT_ID)
    assert auth.client_inputs() == {"client_id": fake_graph_cal.CLIENT_ID, "tenant": "common"}
    monkeypatch.setenv("OUTLOOK_CALENDAR_TENANT", "contoso.example")
    assert auth.client_inputs()["tenant"] == "contoso.example"


def test_authorize_stores_one_record_of_its_own_and_prints_no_secret(fake, env, monkeypatch, capsys):
    seen = browser(monkeypatch, returns_with_the_code)
    assert auth.authorize(open_browser=True) == 0
    out, err = capsys.readouterr()
    assert seen["callback"][0] == 200
    printed = json.loads(out)
    assert printed == {"authorized": True, "secret_store": {"service": "openhora", "username": "outlook-calendar"}, "scope": "Calendars.ReadBasic",
                       "tenant": "common", "obtained_at": printed["obtained_at"]}
    assert list(env.values) == [KEY]
    record = json.loads(env.values[KEY])
    assert set(record) == {"refresh_token", "client_id", "tenant", "scope", "obtained_at"}
    assert record["client_id"] == fake_graph_cal.CLIENT_ID and record["scope"] == "Calendars.ReadBasic"
    form = [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"][0]
    assert form["scope"] == "https://graph.microsoft.com/Calendars.ReadBasic offline_access" and "client_secret" not in form
    assert fake.requests == [], "the authorization reads no calendar"
    for text in (out, err):
        for secret in SECRETS:
            assert secret not in text


@pytest.mark.parametrize("granted,named", [
    ("https://graph.microsoft.com/Calendars.ReadBasic https://graph.microsoft.com/Mail.Read offline_access", "Mail.Read"),
    ("https://graph.microsoft.com/Calendars.ReadBasic https://graph.microsoft.com/Files.Read offline_access", "Files.Read"),
    ("https://graph.microsoft.com/Calendars.ReadBasic https://graph.microsoft.com/User.Read offline_access", "User.Read"),
    ("https://graph.microsoft.com/Calendars.Read offline_access", "Calendars.Read"),
    ("https://graph.microsoft.com/Calendars.ReadBasic https://graph.microsoft.com/Calendars.ReadWrite offline_access", "Calendars.ReadWrite"),
])
def test_a_registration_that_holds_any_other_permission_stores_nothing(fake, env, monkeypatch, capsys, granted, named):
    fake.scope_granted = granted
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 3
    assert env.values == {} and fake.api_requests() == []
    err = capsys.readouterr().err
    assert named in err and "Remove the other permissions" in err


def test_a_declined_sign_in_and_a_consent_the_admin_must_give_have_their_own_words(fake, env, monkeypatch, capsys):
    browser(monkeypatch, lambda url, seen: seen.update(callback=callback(port_of(url), {
        "error": "access_denied", "error_description": "AADSTS65004: the user declined", "state": consent_query(url)["state"][0]})))
    assert auth.main(["authorize"]) == 1
    err = capsys.readouterr().err
    assert "sign-in was declined" in err and "calendar/outlook_auth.py authorize" in err and "admin must approve" not in err
    browser(monkeypatch, lambda url, seen: seen.update(callback=callback(port_of(url), {
        "error": "consent_required", "error_description": "AADSTS90094: admin consent is required", "state": consent_query(url)["state"][0]})))
    assert auth.main(["authorize"]) == 3
    assert "your Microsoft 365 admin must approve the app" in capsys.readouterr().err
    assert env.values == {}


def test_a_wrong_state_stores_nothing(fake, env, monkeypatch, capsys):
    seen = browser(monkeypatch, lambda url, s: s.update(callback=callback(port_of(url), {"code": fake_graph_cal.CODE, "state": "forged"})))
    assert auth.main(["authorize"]) == 1
    assert seen["callback"][0] == 400 and env.values == {} and not [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"]


def test_forget_deletes_the_calendar_record_and_only_that(env, capsys):
    env.values[KEY] = "a record"
    env.values[("openhora", "outlook-mail")] = "the mail record"
    env.values[("openhora", "onedrive-sources")] = "the files record"
    assert auth.main(["forget"]) == 0
    assert json.loads(capsys.readouterr().out)["forgotten"] is True
    assert env.values == {("openhora", "outlook-mail"): "the mail record", ("openhora", "onedrive-sources"): "the files record"}


def run(fake, *argv, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith("OUTLOOK_") and not k.startswith("INTEGRATION_CALENDAR_")}
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60, env={**base, **fake.env(), **(env or {})})


def test_check_reports_whether_an_authorization_is_found_without_the_network_and_without_a_secret(fake):
    done = run(fake, "--check")
    assert done.returncode == 0
    found = json.loads(done.stdout)
    assert found["found"] is True and found["source"].startswith("environment") and found["scope"] == "Calendars.ReadBasic"
    assert fake.requests == [] and fake.token_forms == []
    for secret in SECRETS:
        assert secret not in done.stdout + done.stderr
    missing = run(fake, "--check", env={"OUTLOOK_CALENDAR_TOKEN": ""})
    assert missing.returncode == 3 and json.loads(missing.stdout) == {"found": False} and "outlook_auth.py authorize" in missing.stderr


def test_the_commands_are_checked_before_anything_starts(fake):
    assert run(fake).returncode == 2 and run(fake, "--check", "authorize").returncode == 2 and run(fake, "forget", "--no-browser").returncode == 2
    done = run(fake, "forget")
    assert done.returncode == 2 and "never uses the OS secret store" in done.stderr
    done = run(fake, "authorize", "--no-browser", env={"OUTLOOK_CALENDAR_CLIENT_ID": fake_graph_cal.CLIENT_ID})
    assert done.returncode == 2 and "never uses the OS secret store" in done.stderr and fake.requests == []
