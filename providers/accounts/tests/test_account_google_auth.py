"""Tests of the Google account authorization (providers/accounts/google_auth.py), against the stand-in service (fake_google_account.py) and a
small browser made of http.client: the consent URL asks for exactly the four platform scopes with PKCE S256 and a state; the client id and
secret come from the environment of the command and never from a flag or into a printout; the authorization is stored as one record, with its
slot, address, scope and date, in a stand-in secret store; a consent that grants anything but exactly the four (one missing, or a wider scope
such as https://mail.google.com/) stores nothing and exits 3 naming the command; the callback listener refuses a wrong state, a wrong host and
a second callback; check and forget touch only the account record. No Google host is reached and no real credential exists.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_google_auth.py
"""
from __future__ import annotations

import base64
import hashlib
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
REPO = HERE.parents[2]
SCRIPT = REPO / "providers" / "accounts" / "google_auth.py"
sys.path.insert(0, str(HERE))
import fake_google_account as fga  # noqa: E402

_spec = importlib.util.spec_from_file_location("google_account_auth_under_test", SCRIPT)
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)


class PasswordDeleteError(Exception):    # the name keyring's own error has: nothing stored under that name
    pass


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


@pytest.fixture
def fake():
    f = fga.FakeGoogleAccount()
    yield f
    f.close()


def configure(fake, monkeypatch, store):
    monkeypatch.setattr(auth, "keyring_module", lambda test_mode: store)
    for key, value in fake.auth_env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GOOGLE_ACCOUNT_TOKEN", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", fga.CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", fga.CLIENT_SECRET)


def call(base, path, headers=None):
    c = http.client.HTTPConnection(base.hostname, base.port, timeout=10)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    out = (r.status, r.read())
    c.close()
    return out


def browser(fake, seen, state_override=None, error=None):
    """What a person's browser does with the printed consent URL, minus Google: read the state and the challenge from it and return to the
    redirect address with a code (or with a forged state, or with an error)."""
    def open_url(url):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        seen["consent"] = query
        fake.expected_challenge = query["code_challenge"][0]

        def go():
            base = urllib.parse.urlparse(query["redirect_uri"][0])
            state = state_override or query["state"][0]
            params = {"error": error, "state": state} if error else {"code": fga.CODE, "state": state}
            seen["status"] = call(base, "/?" + urllib.parse.urlencode(params))[0]
        seen["thread"] = threading.Thread(target=go, daemon=True)
        seen["thread"].start()
    return open_url


def no_secret(*texts):
    for text in texts:
        for secret in fga.SECRETS:
            assert secret not in text


# --- the consent URL ------------------------------------------------------------------------------------------------------


def test_the_consent_url_asks_for_the_four_platform_scopes_alone_with_pkce_and_a_state():
    verifier, challenge = auth.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = auth.authorize_url(fga.CLIENT_ID, "http://127.0.0.1:5555", "the-state", challenge)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert set(query["scope"][0].split()) == set(fga.PLATFORM_SET) and len(query["scope"][0].split()) == 4, "exactly the four, nothing wider"
    assert fga.MAIL_ALL not in query["scope"][0] and "https://www.googleapis.com/auth/calendar " not in query["scope"][0] + " "
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"] == [challenge] and query["state"] == ["the-state"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == ["http://127.0.0.1:5555"]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"] and "include_granted_scopes" not in query
    assert fga.CLIENT_SECRET not in url and "client_secret" not in query


def test_the_client_comes_from_the_environment_of_the_command_never_from_a_flag(monkeypatch):
    for name, _ in auth.INPUTS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(auth.ProviderError) as missing:
        auth.client_inputs()
    assert missing.value.code == 3 and "GOOGLE_CLIENT_ID" in str(missing.value) and "hidden prompt" in str(missing.value)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", fga.CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", fga.CLIENT_SECRET)
    assert auth.client_inputs() == {"GOOGLE_CLIENT_ID": fga.CLIENT_ID, "GOOGLE_CLIENT_SECRET": fga.CLIENT_SECRET}
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "has a space")
    with pytest.raises(auth.ProviderError) as spaced:
        auth.client_inputs()
    assert spaced.value.code == 2
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    asked = []
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt: asked.append(prompt) or "typed-secret")
    assert auth.client_inputs()["GOOGLE_CLIENT_SECRET"] == "typed-secret" and "GOOGLE_CLIENT_SECRET" in asked[0]
    for flag in ("--client-id", "--client-secret"):
        done = subprocess.run([sys.executable, str(SCRIPT), "authorize", flag, "x"], capture_output=True, text=True, timeout=60)
        assert done.returncode == 2


# --- authorize ------------------------------------------------------------------------------------------------------------


def test_authorize_stores_one_account_record_with_its_slot_address_and_scope_and_prints_no_secret(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.authorize("main", open_browser=True) == 0
    seen["thread"].join(10)
    out, err = capsys.readouterr()
    assert set(seen["consent"]["scope"][0].split()) == set(fga.PLATFORM_SET) and seen["status"] == 200
    printed = json.loads(out)
    assert printed["stored"] is True and printed["account"] == fga.ACCOUNT and printed["slot"] == "main"
    assert printed["secret_store"] == {"service": "openhora", "username": "google-account"}
    assert printed["scope"] == sorted(fga.PLATFORM_SET)
    assert list(store.values) == [("openhora", "google-account")], "one record, under its own name; the legacy ones are not touched"
    record = json.loads(store.values[("openhora", "google-account")])
    assert set(record) == {"slot", "refresh_token", "client_id", "client_secret", "scope", "account", "obtained_at"}
    assert record["slot"] == "main" and record["account"] == fga.ACCOUNT and set(record["scope"].split()) == set(fga.PLATFORM_SET)
    assert record["refresh_token"] == fga.REFRESH_TOKEN and record["client_id"] == fga.CLIENT_ID
    forms = [urllib.parse.parse_qs(r["body"].decode()) for r in fake.requests if r["path"] == "/token"]
    assert [f["grant_type"] for f in forms] == [["authorization_code"]]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(forms[0]["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
    assert seen["consent"]["code_challenge"] == [challenge], "the code was exchanged with the verifier of the challenge sent"
    assert forms[0]["redirect_uri"] == seen["consent"]["redirect_uri"]
    assert fake.methods() == [("POST", "/token"), ("GET", "/gmail/v1/users/me/profile")], "the address is read once, from the Gmail profile"
    no_secret(out, err)


def test_the_record_it_stores_is_what_the_readers_accept(fake, monkeypatch):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.authorize("main", open_browser=True) == 0
    record = auth.google.parse_account_record(store.values[("openhora", "google-account")])
    token = auth.google.refresh_access_token(fake.token_url, record)
    assert token["access_token"] == fga.ACCESS_TOKEN


@pytest.mark.parametrize("granted", [
    " ".join(fga.PLATFORM_SET[1:]), " ".join(fga.PLATFORM_SET[:3]), fga.GMAIL_MODIFY, "",
    " ".join(fga.PLATFORM_SET + (fga.MAIL_ALL,)), " ".join(fga.PLATFORM_SET + ("https://www.googleapis.com/auth/calendar",)),
    " ".join((fga.GMAIL_READONLY,) + fga.PLATFORM_SET[1:])])
def test_a_consent_that_did_not_grant_exactly_the_four_scopes_stores_nothing_and_names_the_command(fake, monkeypatch, capsys, granted):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    fake.consent_scope = granted or None
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.main(["authorize"]) == 3
    seen["thread"].join(10)
    err = capsys.readouterr().err
    assert store.values == {} and "google_auth.py authorize" in err and "nothing stored" in err
    assert fake.api_requests() == [], "no call was made with a token of the wrong scope"
    no_secret(err)


def test_a_consent_with_identity_words_alone_added_is_accepted(fake, monkeypatch):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    fake.consent_scope = "openid email profile " + " ".join(fga.PLATFORM_SET)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.main(["authorize"]) == 0
    assert len(store.values) == 1


def test_a_failing_profile_stops_before_anything_is_stored(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    fake.requests.clear()
    monkeypatch.setattr(auth.google, "get_json", lambda url, token, error=None: (_ for _ in ()).throw(auth.ProviderError("Google returned 403")))
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.main(["authorize"]) == 1
    assert store.values == {} and "403" in capsys.readouterr().err


def test_a_wrong_state_stores_nothing_and_exchanges_no_code(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen, state_override="forged"))
    assert auth.main(["authorize"]) == 1
    seen["thread"].join(10)
    assert seen["status"] == 401 and store.values == {}
    assert fake.requests == [], "no token call was made"
    assert "state parameter does not match" in capsys.readouterr().err


def test_a_refused_consent_stores_nothing(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen, error="access_denied"))
    assert auth.main(["authorize"]) == 1
    seen["thread"].join(10)
    assert seen["status"] == 400 and store.values == {} and fake.requests == []
    assert "access_denied" in capsys.readouterr().err


def test_an_answer_without_a_refresh_token_is_refused(monkeypatch):
    monkeypatch.setattr(auth.google, "token_request", lambda url, form, error=None: {"access_token": "a", "scope": " ".join(fga.PLATFORM_SET)})
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
    no_secret(err)


def test_the_test_overrides_must_be_loopback_and_set_together(monkeypatch):
    monkeypatch.setenv("GOOGLE_ACCOUNT_API_BASE", "https://gmail.example.com")
    monkeypatch.setenv("GOOGLE_ACCOUNT_TOKEN_URL", "http://127.0.0.1:9/token")
    with pytest.raises(auth.ProviderError) as remote:
        auth.endpoints()
    assert remote.value.code == 2 and "loopback" in str(remote.value)
    monkeypatch.delenv("GOOGLE_ACCOUNT_TOKEN_URL")
    with pytest.raises(auth.ProviderError) as alone:
        auth.endpoints()
    assert alone.value.code == 2 and "together" in str(alone.value)
    monkeypatch.delenv("GOOGLE_ACCOUNT_API_BASE")
    assert auth.endpoints() == ("https://gmail.googleapis.com", "https://oauth2.googleapis.com/token", False)


def test_only_the_slot_main_exists_and_another_is_refused_before_anything_starts(fake, capsys):
    assert auth.main(["authorize", "--account", "work"]) == 2
    assert auth.main(["check", "--account", "Bad Slot"]) == 2
    assert auth.main(["forget", "--account", "work"]) == 2
    err = capsys.readouterr().err
    assert "no registry row yet" in err and "1 to 12" in err
    assert fake.requests == []


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
        if not server.done.is_set():
            server.close()


def test_the_listener_refuses_a_wrong_state_with_401_and_ends_with_an_error():
    server = auth.CallbackServer("good-state")
    base = urllib.parse.urlparse(server.redirect_uri)
    assert call(base, "/?code=x&state=forged")[0] == 401
    with pytest.raises(auth.ProviderError) as refused:
        server.wait(5)
    assert "state parameter does not match" in str(refused.value)
    assert auth.state_matches("a", "a") and not auth.state_matches("a", "b") and not auth.state_matches("", "b")


def test_the_listener_gives_up_after_ten_minutes():
    assert auth.CALLBACK_TIMEOUT_SECONDS == 600 and auth.CallbackServer.wait.__defaults__ == (600,)
    server = auth.CallbackServer("s")
    with pytest.raises(auth.ProviderError) as timed_out:
        server.wait(0.3)     # the same code path with a short wait
    assert "no callback within" in str(timed_out.value)


# --- check and forget -----------------------------------------------------------------------------------------------------


def run_script(fake, *argv, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith(("GOOGLE_", "GMAIL_"))}
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60,
                          env={**base, **fake.auth_env(), "GOOGLE_ACCOUNT_TOKEN": fake.record_json(), **(env or {})})


def test_check_reads_the_record_the_way_the_providers_do_and_needs_no_network(fake):
    done = run_script(fake, "check")
    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)
    assert printed["found"] is True and printed["has_refresh_token"] is True and printed["account"] == fga.ACCOUNT
    assert printed["scope"] == sorted(fga.PLATFORM_SET) and printed["scope_is_platform_set"] is True and printed["slot"] == "main"
    assert printed["missing"] == [] and printed["extra"] == [] and printed["source"] == "environment (GOOGLE_ACCOUNT_TOKEN)"
    assert fake.requests == []
    no_secret(done.stdout, done.stderr)


def test_check_says_what_is_missing_and_what_is_extra_and_exits_3(fake):
    lacking = run_script(fake, "check", env={"GOOGLE_ACCOUNT_TOKEN": fake.record_json(scope=" ".join(fga.PLATFORM_SET[:3]))})
    assert lacking.returncode == 3 and json.loads(lacking.stdout)["missing"] == [fga.DRIVE]
    assert "google_auth.py authorize" in lacking.stderr
    wider = run_script(fake, "check", env={"GOOGLE_ACCOUNT_TOKEN": fake.record_json(scope=" ".join(fga.PLATFORM_SET + (fga.MAIL_ALL,)))})
    assert wider.returncode == 3 and json.loads(wider.stdout)["extra"] == [fga.MAIL_ALL]
    unnamed = run_script(fake, "check", env={"GOOGLE_ACCOUNT_TOKEN": fake.record_json(scope=None)})
    assert unnamed.returncode == 3 and json.loads(unnamed.stdout)["scope"] == []
    missing = run_script(fake, "check", env={"GOOGLE_ACCOUNT_TOKEN": ""})
    assert missing.returncode == 3 and json.loads(missing.stdout)["found"] is False and "google_auth.py authorize" in missing.stderr
    broken = run_script(fake, "check", env={"GOOGLE_ACCOUNT_TOKEN": "{not json"})
    assert broken.returncode == 3 and "unreadable or incomplete" in broken.stderr
    other_slot = run_script(fake, "check", env={"GOOGLE_ACCOUNT_TOKEN": fake.record_json(slot="work")})
    assert other_slot.returncode == 3 and "only the slot 'main' exists" in other_slot.stderr
    assert fake.requests == []


def test_forget_removes_only_the_account_record_and_says_google_was_not_told(fake, monkeypatch, capsys):
    store = Store()
    store.values[("openhora", "google-account")] = fake.record_json()
    for legacy in ("mailbox-gmail", "gmail-client-id", "gmail-client-secret", "calendar-google", "gdrive-sources"):
        store.values[("openhora", legacy)] = f"the {legacy} record stays"
    configure(fake, monkeypatch, store)
    assert auth.main(["forget"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["forgotten"] is True and ("openhora", "google-account") not in store.values and len(store.values) == 5
    assert "Google was not told" in err and "legacy records were not touched" in err and fake.requests == []
    assert auth.main(["forget"]) == 0, "forgetting what is not there is not an error"
    out, err = capsys.readouterr()
    assert json.loads(out)["forgotten"] is False and "nothing was stored" in err and len(store.values) == 5


def test_the_commands_are_checked_before_anything_starts(fake):
    run = lambda *argv: subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60,  # noqa: E731
                                       env={**os.environ, **fake.auth_env()})
    assert run().returncode == 2 and run("pick").returncode == 2 and run("--check").returncode == 2
    assert run("check", "--no-browser").returncode == 2 and run("forget", "--no-browser").returncode == 2
    assert fake.requests == []
    help_text = run("--help").stdout
    for needle in (fga.GMAIL_MODIFY, fga.CALENDAR_EVENTS, fga.CALENDAR_LIST, fga.DRIVE, "In production", "accessed 2026-10-18", "<workbench>",
                   "ACCT-SLOT", "one switch"):
        assert needle in help_text or needle == "one switch" and "stops every reader and writer" in help_text, needle


def test_a_malformed_token_in_the_exchange_stores_nothing_and_leaves_no_traceback(fake, monkeypatch, capsys):
    store, seen = Store(), {}
    configure(fake, monkeypatch, store)
    monkeypatch.setattr(auth.google, "token_request",
                        lambda url, form, error=None: {"access_token": "good", "refresh_token": "refresh\r\nX-Injected: yes",
                                                       "scope": " ".join(fga.PLATFORM_SET)})
    monkeypatch.setattr(auth.webbrowser, "open", browser(fake, seen))
    assert auth.main(["authorize"]) == 1
    seen["thread"].join(10)
    out, err = capsys.readouterr()
    assert store.values == {} and "unexpected shape" in err
    for text in (out, err):
        assert "Traceback" not in text and "Injected" not in text


def test_the_last_resort_of_authorize_prints_the_kind_and_not_the_message(fake, monkeypatch, capsys):
    configure(fake, monkeypatch, Store())
    monkeypatch.setattr(auth, "client_inputs", lambda: (_ for _ in ()).throw(RuntimeError("holds " + fga.CLIENT_SECRET)))
    assert auth.main(["authorize"]) == 1
    err = capsys.readouterr().err
    assert "unexpected RuntimeError" in err and fga.CLIENT_SECRET not in err
