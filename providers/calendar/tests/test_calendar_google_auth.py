"""Tests of the Google Calendar authorization (providers/calendar/google_auth.py), against the stand-in service (fake_gcal.py) and a small
browser made of http.client: the consent URL asks for exactly the two calendar scopes with PKCE S256 and a state; the client id and secret
come from the environment of the command and never from a flag or into a printout; the authorization is stored as one record of its own
in a stand-in secret store; a consent that grants anything but exactly the two scopes stores nothing; the callback listener refuses a wrong
state, a wrong host and a second callback, and gives up after ten minutes. No Google host is reached and no real credential exists.

Run: uv run --with pytest==9.1.1 pytest providers/calendar/tests/test_calendar_google_auth.py
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = REPO / "providers" / "calendar" / "google_auth.py"
sys.path.insert(0, str(HERE))
import fake_gcal  # noqa: E402

_spec = importlib.util.spec_from_file_location("google_auth_under_test", SCRIPT)
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)

SECRETS = (fake_gcal.ACCESS_TOKEN, fake_gcal.REFRESH_TOKEN, fake_gcal.CLIENT_SECRET)
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class Store:
    """A stand-in secret store: set_password and delete_password only. The real keyring is never touched."""

    def __init__(self):
        self.values = {}

    def set_password(self, service, username, value):
        self.values[(service, username)] = value

    def delete_password(self, service, username):
        if (service, username) not in self.values:
            raise PasswordDeleteError("not found")
        del self.values[(service, username)]


class PasswordDeleteError(Exception):    # the name keyring's own error has: nothing stored under that name
    pass


@pytest.fixture
def fake():
    f = fake_gcal.FakeGoogleCalendar()
    f.add_calendar(fake_gcal.ACCOUNT, "Personal", primary=True)
    yield f
    f.close()


def configure(fake, monkeypatch, store):
    monkeypatch.setattr(auth, "keyring_module", lambda test_mode: store)
    for key, value in fake.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GOOGLE_CALENDAR_TOKEN")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", fake_gcal.CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", fake_gcal.CLIENT_SECRET)


def call(base, path, headers=None):
    c = http.client.HTTPConnection(base.hostname, base.port, timeout=10)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    out = (r.status, r.read())
    c.close()
    return out


def browser(fake, seen, state_override=None, error=None, extra_calls=()):
    """What a person's browser does with the printed consent URL, minus Google: read the state and the challenge from it and return to the
    redirect address with a code (or with the state it was given, or a forged one)."""
    def open_url(url):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        seen["consent"] = query
        fake.expected_challenge = query["code_challenge"][0]

        def go():
            base = urllib.parse.urlparse(query["redirect_uri"][0])
            state = state_override or query["state"][0]
            params = {"error": error, "state": state} if error else {"code": fake_gcal.CODE, "state": state}
            seen["status"] = call(base, "/?" + urllib.parse.urlencode(params))[0]
            for path in extra_calls:
                try:
                    seen.setdefault("extra", []).append(call(base, path)[0])
                except OSError as exc:      # the listener is already closed
                    seen.setdefault("extra", []).append(type(exc).__name__)
        seen["thread"] = threading.Thread(target=go, daemon=True)
        seen["thread"].start()
    return open_url


# --- the consent URL ------------------------------------------------------------------------------------------------------


def test_the_consent_url_asks_for_the_two_calendar_scopes_alone_with_pkce_and_a_state():
    verifier, challenge = auth.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = auth.authorize_url(fake_gcal.CLIENT_ID, "http://127.0.0.1:5555", "the-state", challenge)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert query["scope"] == [f"{fake_gcal.EVENTS_SCOPE} {fake_gcal.LIST_SCOPE}"], "exactly the two read scopes, nothing wider"
    assert set(query["scope"][0].split()) == {"https://www.googleapis.com/auth/calendar.events.readonly",
                                              "https://www.googleapis.com/auth/calendar.calendarlist.readonly"}
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"] == [challenge] and query["state"] == ["the-state"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == ["http://127.0.0.1:5555"]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"] and "include_granted_scopes" not in query
    assert fake_gcal.CLIENT_SECRET not in url and "client_secret" not in query


def test_the_client_comes_from_the_environment_of_the_command_never_from_a_flag(monkeypatch):
    for name, _ in auth.INPUTS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(auth.ProviderError) as missing:
        auth.client_inputs()
    assert missing.value.code == 3 and "GOOGLE_CALENDAR_CLIENT_ID" in str(missing.value) and "hidden prompt" in str(missing.value)
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", fake_gcal.CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", fake_gcal.CLIENT_SECRET)
    assert auth.client_inputs() == {"GOOGLE_CALENDAR_CLIENT_ID": fake_gcal.CLIENT_ID, "GOOGLE_CALENDAR_CLIENT_SECRET": fake_gcal.CLIENT_SECRET}
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "has a space")
    with pytest.raises(auth.ProviderError) as spaced:
        auth.client_inputs()
    assert spaced.value.code == 2
    # On a terminal a missing value is typed at a hidden prompt.
    monkeypatch.delenv("GOOGLE_CALENDAR_CLIENT_SECRET")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    asked = []
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt: asked.append(prompt) or "typed-secret")
    assert auth.client_inputs()["GOOGLE_CALENDAR_CLIENT_SECRET"] == "typed-secret" and "GOOGLE_CALENDAR_CLIENT_SECRET" in asked[0]
    for flag in ("--client-id", "--client-secret"):
        done = subprocess.run([sys.executable, str(SCRIPT), "authorize", flag, "x"], capture_output=True, text=True, timeout=60)
        assert done.returncode == 2


# --- authorize ------------------------------------------------------------------------------------------------------------


def test_authorize_stores_one_record_of_its_own_and_prints_no_secret(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.authorize(open_browser=True) == 0
    seen["thread"].join(10)
    out, err = capsys.readouterr()
    assert seen["consent"]["scope"] == [f"{fake_gcal.EVENTS_SCOPE} {fake_gcal.LIST_SCOPE}"] and seen["status"] == 200
    printed = json.loads(out)
    assert printed["stored"] is True and printed["account"] == fake_gcal.ACCOUNT
    assert printed["secret_store"] == {"service": "openhora", "username": "calendar-google"}
    assert list(store.values) == [("openhora", "calendar-google")], "one record, under its own name (the Gmail one is another)"
    record = json.loads(store.values[("openhora", "calendar-google")])
    assert set(record) == {"refresh_token", "client_id", "client_secret", "scope", "account", "obtained_at"}
    assert record["refresh_token"] == fake_gcal.REFRESH_TOKEN and record["client_id"] == fake_gcal.CLIENT_ID
    assert set(record["scope"].split()) == set(auth.SCOPES) and record["account"] == fake_gcal.ACCOUNT
    form = [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"][0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert seen["consent"]["code_challenge"] == [challenge], "the code was exchanged with the verifier of the challenge sent"
    assert form["redirect_uri"] == seen["consent"]["redirect_uri"][0]
    assert set(fake.methods) == {"GET"}
    for text in (out, err):
        for secret in SECRETS:
            assert secret not in text


def test_the_record_it_stores_is_what_the_provider_reads_and_accepts(fake, monkeypatch):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.authorize(open_browser=True) == 0
    record = auth.google.parse_record(store.values[("openhora", "calendar-google")])
    token = auth.google.refresh_access_token(fake.token_url, record)
    assert token == fake_gcal.ACCESS_TOKEN


@pytest.mark.parametrize("granted", [fake_gcal.EVENTS_SCOPE, fake_gcal.LIST_SCOPE, f"{fake_gcal.BOTH_SCOPES} {GMAIL_SCOPE}",
                                     "https://www.googleapis.com/auth/calendar.readonly", ""])
def test_a_consent_that_did_not_grant_exactly_the_two_scopes_stores_nothing(fake, monkeypatch, capsys, granted):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    fake.scope_granted = granted
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.main(["authorize"]) == 3
    assert store.values == {} and "exactly the two calendar scopes" in capsys.readouterr().err
    assert fake.api_requests() == [], "no call was made with a token of the wrong scope"


def test_a_failing_calendar_api_stops_before_anything_is_stored(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    fake.fail_always = (403, "accessNotConfigured")
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.main(["authorize"]) == 1
    assert store.values == {} and "Google Calendar API is enabled" in capsys.readouterr().err


def test_a_wrong_state_stores_nothing_and_exchanges_no_code(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen, state_override="forged"))
    assert auth.main(["authorize"]) == 1
    seen["thread"].join(10)
    assert seen["status"] == 401 and store.values == {}
    assert not [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"]
    assert "state parameter does not match" in capsys.readouterr().err


def test_a_refused_consent_stores_nothing(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen, error="access_denied"))
    assert auth.main(["authorize"]) == 1
    seen["thread"].join(10)
    assert seen["status"] == 400 and store.values == {} and fake.token_forms == []
    assert "access_denied" in capsys.readouterr().err


def test_an_answer_without_a_refresh_token_is_refused(monkeypatch):
    monkeypatch.setattr(auth.google, "token_request", lambda url, form: {"access_token": "a", "scope": fake_gcal.BOTH_SCOPES})
    with pytest.raises(auth.ProviderError) as refused:
        auth.exchange_code("http://127.0.0.1:1/token", "c", "v", "id", "secret", "http://127.0.0.1:2")
    assert "no refresh token" in str(refused.value)


def test_a_store_that_cannot_be_written_is_an_error_and_names_no_secret(fake, monkeypatch, capsys):
    class Broken(Store):
        def set_password(self, service, username, value):
            raise RuntimeError(f"locked, and the value was {value}")
    configure(fake, monkeypatch, Broken())
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, {}))
    assert auth.main(["authorize"]) == 1
    err = capsys.readouterr().err
    assert "cannot write to the OS secret store: RuntimeError" in err
    for secret in SECRETS:
        assert secret not in err


# --- the callback listener ------------------------------------------------------------------------------------------------


def test_the_listener_is_loopback_only_refuses_a_wrong_host_and_a_stray_visit_and_takes_one_callback():
    server = auth.CallbackServer("good-state")
    try:
        base = urllib.parse.urlparse(server.redirect_uri)
        assert base.hostname == "127.0.0.1" and server.server.server_address[0] == "127.0.0.1"
        assert call(base, "/favicon.ico")[0] == 404 and call(base, "/")[0] == 404, "a visit with no state, code or error is not the callback"
        assert call(base, "/?code=x&state=good-state", headers={"Host": "evil.example:80"})[0] == 400, "the exact host is required"
        assert not server.done.is_set(), "neither of those ended the wait"
        assert call(base, "/?code=the-code&state=good-state")[0] == 200
        assert call(base, "/?code=another&state=good-state")[0] == 404, "a second callback is refused"
        assert call(base, "/?code=another&state=forged")[0] == 404
        assert server.wait(5) == "the-code", "the first callback is the one that counts"
    finally:
        server.close() if not server.done.is_set() else None


def test_the_listener_refuses_a_wrong_state_with_401_and_ends_with_an_error():
    server = auth.CallbackServer("good-state")
    base = urllib.parse.urlparse(server.redirect_uri)
    assert call(base, "/?code=x&state=forged")[0] == 401
    with pytest.raises(auth.ProviderError) as refused:
        server.wait(5)
    assert "state parameter does not match" in str(refused.value)
    assert auth.state_matches("a", "a") and not auth.state_matches("a", "b") and not auth.state_matches("", "b")


def test_the_listener_gives_up_after_ten_minutes_and_closes_its_port():
    assert auth.CALLBACK_TIMEOUT_SECONDS == 600
    server = auth.CallbackServer("s")
    port = server.server.server_address[1]
    with pytest.raises(auth.ProviderError) as timed_out:
        server.wait(0.3)     # the same code path with a short wait
    assert "no callback within" in str(timed_out.value)
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=2)
    assert auth.CallbackServer.wait.__defaults__ == (auth.CALLBACK_TIMEOUT_SECONDS,), "the default wait is the ten minutes"


# --- check and forget -----------------------------------------------------------------------------------------------------


def run_script(fake, *argv, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("GOOGLE_CALENDAR_", "INTEGRATION_CALENDAR_GOOGLE"))}
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60,
                          env={**base, **fake.env(), **(env or {})})


def test_check_reads_the_record_the_way_the_provider_does_and_needs_no_network(fake):
    done = run_script(fake, "check")
    assert done.returncode == 0
    printed = json.loads(done.stdout)
    assert printed["found"] is True and printed["has_refresh_token"] is True and printed["account"] == fake_gcal.ACCOUNT
    assert printed["scope"] == fake_gcal.BOTH_SCOPES
    assert fake.requests == [] and fake.token_forms == []
    for secret in SECRETS:
        assert secret not in done.stdout + done.stderr
    missing = run_script(fake, "check", env={"GOOGLE_CALENDAR_TOKEN": ""})
    assert missing.returncode == 3 and json.loads(missing.stdout)["found"] is False and "google_auth.py authorize" in missing.stderr
    broken = run_script(fake, "check", env={"GOOGLE_CALENDAR_TOKEN": "{not json"})
    assert broken.returncode == 3 and "unreadable or incomplete" in broken.stderr


def test_forget_removes_the_record_and_says_google_was_not_told(fake, monkeypatch, capsys):
    store = Store()
    store.values[("openhora", "calendar-google")] = fake.record_json()
    store.values[("openhora", "mailbox-gmail")] = "the gmail record stays"
    configure(fake, monkeypatch, store)
    assert auth.main(["forget"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["forgotten"] is True and list(store.values) == [("openhora", "mailbox-gmail")]
    assert "Google was not told" in err and fake.requests == [] and fake.token_forms == []
    assert auth.main(["forget"]) == 0, "forgetting what is not there is not an error"
    out, err = capsys.readouterr()
    assert json.loads(out)["forgotten"] is False and "nothing was stored" in err


def test_the_commands_are_checked_before_anything_starts(fake):
    run = lambda *argv: subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60,  # noqa: E731
                                       env={**os.environ, **fake.env()})
    assert run().returncode == 2 and run("pick").returncode == 2 and run("--check").returncode == 2
    assert run("check", "--no-browser").returncode == 2 and run("forget", "--no-browser").returncode == 2
    assert fake.requests == [] and fake.token_forms == []
    help_text = run("--help").stdout
    for needle in ("calendar.events.readonly", "calendar.calendarlist.readonly", "Publish app", "accessed 2026-10-17", "<workbench>"):
        assert needle in help_text, needle


def test_the_account_is_the_primary_calendar_even_when_it_is_on_a_later_page(fake):
    fake.calendars.clear()
    fake.add_calendar("other@example.com", "Other")
    fake.add_calendar(fake_gcal.ACCOUNT, "Personal", primary=True)
    fake.page_cap = 1
    assert auth.primary_account(fake.base, fake_gcal.ACCESS_TOKEN) == fake_gcal.ACCOUNT
    assert len(fake.api_requests()) == 2, "reading stopped at the page that held the primary calendar"
    fake.calendars.pop(fake_gcal.ACCOUNT)
    assert auth.primary_account(fake.base, fake_gcal.ACCESS_TOKEN) is None
