"""Tests of the OneDrive authorization command (providers/documents/onedrive_auth.py), against the stand-in service (fake_graph.py) and a
small browser made of http.client: the consent URL asks for Files.Read and offline_access and nothing else, with PKCE S256, a state and
the code in the query; the callback server answers only the right Host, only a request shaped like a callback, once, and then stops; the
client id comes from the environment of the command and never from a flag; the authorization is stored as one record in a stand-in
secret store; a token wider than Files.Read stores nothing. No Microsoft host is reached and no real credential exists.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_onedrive_auth.py
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = REPO / "providers" / "documents" / "onedrive_auth.py"
sys.path.insert(0, str(HERE))
import fake_graph  # noqa: E402

_spec = importlib.util.spec_from_file_location("onedrive_auth_under_test", SCRIPT)
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)
od = auth.onedrive

SECRETS = (fake_graph.ACCESS_TOKEN, fake_graph.REFRESH_TOKEN, fake_graph.CODE)


class Store:
    """A stand-in secret store: set_password and delete_password only."""

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


def callback(port, query, host="default", path="/"):
    """What a browser does when Microsoft redirects it to the loopback address: GET /?... with Host: localhost:<port> (or the one given)."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.putrequest("GET", path + ("?" + urllib.parse.urlencode(query) if query is not None else ""), skip_host=True)
    c.putheader("Host", f"localhost:{port}" if host == "default" else host)
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
    f = fake_graph.FakeGraph()
    yield f
    f.close()


@pytest.fixture
def env(fake, monkeypatch):
    for key, value in fake.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ONEDRIVE_SOURCES_TOKEN")
    monkeypatch.setenv("ONEDRIVE_CLIENT_ID", fake_graph.CLIENT_ID)
    monkeypatch.delenv("ONEDRIVE_TENANT", raising=False)
    store = Store()
    monkeypatch.setattr(od, "keyring_module", lambda test_mode: store)
    return store


def browser(monkeypatch, then):
    """Replace the system browser: it is handed the consent URL and, in a thread, plays what a person's browser does with it."""
    seen = {}

    def open_url(url):
        seen["url"] = url
        threading.Thread(target=then, args=(url, seen), daemon=True).start()

    monkeypatch.setattr(auth.webbrowser, "open", open_url)
    return seen


def returns_with_the_code(url, seen):
    query = consent_query(url)
    seen["callback"] = callback(port_of(url), {"code": fake_graph.CODE, "state": query["state"][0]})


# --- the consent URL ---------------------------------------------------------------------------------------------------------


def test_the_consent_url_asks_for_files_read_and_offline_access_alone_with_pkce_a_state_and_the_code_in_the_query():
    verifier, challenge = auth.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = auth.authorize_url(fake_graph.CLIENT_ID, "common", "http://localhost:5555", "the-state", challenge)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    assert query["scope"] == ["https://graph.microsoft.com/Files.Read offline_access"], "one permission and the refresh token, nothing else"
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"] == [challenge] and query["state"] == ["the-state"]
    assert query["response_type"] == ["code"] and query["response_mode"] == ["query"] and query["redirect_uri"] == ["http://localhost:5555"]
    assert query["prompt"] == ["select_account"] and query["client_id"] == [fake_graph.CLIENT_ID]
    assert set(query) == {"client_id", "response_type", "redirect_uri", "response_mode", "scope", "state", "code_challenge", "code_challenge_method",
                          "prompt"}
    assert "client_secret" not in query and "login_hint" not in query and "include_granted_scopes" not in query


def test_an_offices_own_tenant_is_the_authority_of_the_url():
    url = auth.authorize_url(fake_graph.CLIENT_ID, "contoso.example", "http://localhost:1", "s", "c")
    assert url.startswith("https://login.microsoftonline.com/contoso.example/oauth2/v2.0/authorize?")


def test_the_provider_and_the_authorization_name_one_and_the_same_scope_and_no_other():
    assert auth.onedrive.REFRESH_SCOPE == od.REFRESH_SCOPE == "https://graph.microsoft.com/Files.Read offline_access"
    for name in ("onedrive.py", "onedrive_auth.py"):
        text = (REPO / "providers" / "documents" / name).read_text(encoding="utf-8")
        named = set(re.findall(r"\b(?:Files|Sites|User|Mail|Calendars|Directory)\.[A-Za-z]+(?:\.[A-Za-z]+)?", text))
        assert named <= {"Files.Read", "User.Read"}, f"{name} names a permission beyond Files.Read: {sorted(named)}"   # User.Read: the doc says to remove it
    text = (REPO / "providers" / "documents" / "onedrive.py").read_text(encoding="utf-8")
    assert "User.Read" not in re.sub(r'"""[\s\S]*?"""', "", text), "no code names User.Read; only the documentation does"


# --- the inputs of the command -----------------------------------------------------------------------------------------------


def test_the_client_id_comes_from_the_environment_of_the_command_or_a_hidden_prompt_never_from_a_flag(monkeypatch):
    monkeypatch.delenv("ONEDRIVE_CLIENT_ID", raising=False)
    monkeypatch.delenv("ONEDRIVE_TENANT", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(auth.ProviderError) as missing:
        auth.client_inputs()
    assert missing.value.code == 3 and "ONEDRIVE_CLIENT_ID" in str(missing.value) and "hidden prompt" in str(missing.value)
    monkeypatch.setenv("ONEDRIVE_CLIENT_ID", fake_graph.CLIENT_ID)
    assert auth.client_inputs() == {"client_id": fake_graph.CLIENT_ID, "tenant": "common"}
    monkeypatch.setenv("ONEDRIVE_TENANT", "contoso.example")
    assert auth.client_inputs()["tenant"] == "contoso.example"
    for bad in ("../evil", "a/b", "a b", "-x"):
        monkeypatch.setenv("ONEDRIVE_TENANT", bad)
        with pytest.raises(auth.ProviderError) as refused:
            auth.client_inputs()
        assert refused.value.code == 2, bad
    monkeypatch.delenv("ONEDRIVE_TENANT")
    monkeypatch.setenv("ONEDRIVE_CLIENT_ID", "has a space")
    with pytest.raises(auth.ProviderError):
        auth.client_inputs()
    monkeypatch.delenv("ONEDRIVE_CLIENT_ID")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(auth.getpass, "getpass", lambda prompt: f" {fake_graph.CLIENT_ID} ")
    assert auth.client_inputs()["client_id"] == fake_graph.CLIENT_ID, "a terminal gets the hidden prompt"
    with pytest.raises(SystemExit):
        auth.main(["authorize", "--client-id", fake_graph.CLIENT_ID])   # there is no flag for it


# --- the whole authorization -------------------------------------------------------------------------------------------------


def test_authorize_stores_one_record_and_prints_no_secret(fake, env, monkeypatch, capsys):
    seen = browser(monkeypatch, returns_with_the_code)
    assert auth.authorize(open_browser=True) == 0
    out, err = capsys.readouterr()
    assert seen["callback"][0] == 200 and b"Authorization received" in seen["callback"][2]
    consent = consent_query(seen["url"])
    assert consent["scope"] == ["https://graph.microsoft.com/Files.Read offline_access"] and consent["redirect_uri"][0].startswith("http://localhost:")
    printed = json.loads(out)
    assert printed["authorized"] is True and printed["scope"] == "Files.Read" and printed["account_kind"] == "personal"
    assert printed["secret_store"] == {"service": "openhora", "username": "onedrive-sources"} and printed["tenant"] == "common"
    record = json.loads(env.values[("openhora", "onedrive-sources")])
    assert set(record) == {"refresh_token", "client_id", "tenant", "scope", "account_kind", "obtained_at"}
    assert record["refresh_token"] == fake_graph.REFRESH_TOKEN and record["client_id"] == fake_graph.CLIENT_ID and record["scope"] == "Files.Read"
    form = [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"][0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert consent["code_challenge"] == [challenge], "the code was exchanged with the verifier of the challenge sent"
    assert form["redirect_uri"] == consent["redirect_uri"][0] and form["scope"] == od.REFRESH_SCOPE and "client_secret" not in form
    assert set(fake.methods) <= {"GET"} and [r["path"] for r in fake.api_requests()] == ["/v1.0/me/drive"], "the one Graph call: the drive's type"
    for text in (out, err):
        for secret in SECRETS:
            assert secret not in text
    assert seen["url"] in err and fake_graph.CLIENT_ID in seen["url"], "the printed URL holds the public client id, the state and the challenge"


def test_a_work_account_is_recorded_as_work_and_an_unreadable_kind_as_unknown(fake, env, monkeypatch, capsys):
    fake.drive_type = "business"
    browser(monkeypatch, returns_with_the_code)
    assert auth.authorize(open_browser=True) == 0
    assert json.loads(env.values[("openhora", "onedrive-sources")])["account_kind"] == "work"
    fake.drive_type, fake.fail_next = "personal", (500, {}, {"error": {"code": "generalException", "message": "boom"}})
    capsys.readouterr()
    assert auth.authorize(open_browser=True) == 0
    assert json.loads(env.values[("openhora", "onedrive-sources")])["account_kind"] == "unknown"
    assert "account kind could not be read" in capsys.readouterr().err


def test_a_token_wider_than_files_read_at_the_authorization_stores_nothing(fake, env, monkeypatch, capsys):
    fake.scope_granted = "https://graph.microsoft.com/Files.Read https://graph.microsoft.com/User.Read offline_access"
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 3
    assert env.values == {} and fake.api_requests() == []
    err = capsys.readouterr().err
    assert "User.Read" in err and "Remove the other permissions" in err


def test_no_refresh_token_stores_nothing(fake, env, monkeypatch, capsys):
    fake.no_refresh_token = True
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 1
    assert env.values == {} and "no refresh token" in capsys.readouterr().err


def test_a_store_that_cannot_be_written_fails_without_a_secret_in_the_message(fake, env, monkeypatch, capsys):
    env.fail = True
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 1
    err = capsys.readouterr().err
    assert "cannot write to the OS secret store: RuntimeError" in err and fake_graph.REFRESH_TOKEN not in err


def test_authorize_checks_the_store_before_it_opens_the_browser(fake, env, monkeypatch, capsys):
    monkeypatch.setattr(od, "keyring_module", lambda test_mode: (_ for _ in ()).throw(od.ProviderError("no store", 3)))
    opened = []
    monkeypatch.setattr(auth.webbrowser, "open", opened.append)
    assert auth.main(["authorize"]) == 3 and opened == []


def test_no_browser_prints_the_url_and_opens_nothing(fake, env, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(auth.webbrowser, "open", opened.append)
    seen = {}

    def from_the_printed_url():
        for _ in range(100):
            err = capsys.readouterr().err
            urls = re.findall(r"https://login\.microsoftonline\.com/\S+", err)
            if urls:
                return urls[0]
            threading.Event().wait(0.05)

    original = auth.CallbackServer.wait

    def wait_after_playing_the_person(self, timeout=auth.SESSION_TIMEOUT_SECONDS):
        url = from_the_printed_url()
        seen["url"] = url
        returns_with_the_code(url, seen)
        return original(self, timeout)

    monkeypatch.setattr(auth.CallbackServer, "wait", wait_after_playing_the_person)
    assert auth.main(["authorize", "--no-browser"]) == 0
    assert opened == [] and seen["url"].startswith("https://login.microsoftonline.com/common/")


# --- the callback server -----------------------------------------------------------------------------------------------------


def test_a_wrong_state_stores_nothing_ends_the_session_and_says_so(fake, env, monkeypatch, capsys):
    seen = browser(monkeypatch, lambda url, s: s.update(callback=callback(port_of(url), {"code": fake_graph.CODE, "state": "forged"})))
    assert auth.main(["authorize"]) == 1
    assert seen["callback"][0] == 400 and b"State mismatch" in seen["callback"][2]
    assert env.values == {} and not [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"], "the code was never exchanged"
    assert "state parameter does not match" in capsys.readouterr().err


def test_the_callback_server_refuses_a_wrong_host_a_request_that_is_not_a_callback_and_a_second_callback_and_then_stops():
    server = auth.CallbackServer("the-state")
    port = server.port
    assert server.redirect_uri == f"http://localhost:{port}"
    try:
        assert callback(port, {"code": "c", "state": "the-state"}, host=f"127.0.0.1:{port}")[0] == 403, "only Host: localhost:<port>"
        assert callback(port, {"code": "c", "state": "the-state"}, host="evil.example")[0] == 403
        assert callback(port, {"code": "c", "state": "the-state"}, host=f"localhost:{port + 1}")[0] == 403
        assert callback(port, {"code": "c", "state": "the-state"}, host="")[0] == 403
        assert callback(port, {"code": "c", "state": "the-state"}, path="/other")[0] == 404
        assert callback(port, {"foo": "bar"})[0] == 404 and callback(port, None)[0] == 404, "not shaped like a callback: nothing consumed"
        assert callback(port, {"state": "the-state"})[0] == 404 and callback(port, {"code": "c"})[0] == 404
        assert not server.done.is_set() and server.outcome == {}
        status, headers, body = callback(port, {"code": "the-real-code", "state": "the-state"})
        assert status == 200 and headers["Cache-Control"] == "no-store" and headers["Referrer-Policy"] == "no-referrer"
        assert "the-real-code" not in body.decode(), "nothing received is shown back"
        assert callback(port, {"code": "second", "state": "the-state"})[0] == 404, "the callback is served once"
        assert server.wait(5) == "the-real-code", "and the first one is the one kept"
    finally:
        server.close()
    with pytest.raises(OSError):
        callback(port, {"code": "late", "state": "the-state"})


def test_the_callback_server_listens_on_ipv6_loopback_too_when_the_machine_has_it():
    server = auth.CallbackServer("s")
    try:
        if len(server.servers) < 2:
            pytest.skip("this machine has no usable ::1")
        c = http.client.HTTPConnection("::1", server.port, timeout=10)
        c.putrequest("GET", "/?code=c&state=s", skip_host=True)
        c.putheader("Host", f"localhost:{server.port}")
        c.endheaders()
        assert c.getresponse().status == 200
        assert server.wait(5) == "c"
    finally:
        server.close()


def test_a_session_with_no_callback_times_out_and_the_listener_stops():
    server = auth.CallbackServer("s")
    port = server.port
    with pytest.raises(auth.ProviderError) as late:
        server.wait(0.3)
    assert "no callback within" in str(late.value)
    with pytest.raises(OSError):
        callback(port, {"code": "c", "state": "s"})


def test_the_session_is_ten_minutes_and_the_callback_logs_no_request_line():
    assert auth.SESSION_TIMEOUT_SECONDS == 600
    handler_source = SCRIPT.read_text(encoding="utf-8")
    assert "def log_message(self, *args):" in handler_source


def test_an_error_callback_is_an_exit_not_a_code(fake, env, monkeypatch, capsys):
    def declined(url, seen):
        seen["callback"] = callback(port_of(url), {"error": "access_denied", "error_description": "AADSTS65004: the user declined", "state": consent_query(url)["state"][0]})

    browser(monkeypatch, declined)
    assert auth.main(["authorize"]) == 1, "a declined sign-in is not a setup problem"
    err = capsys.readouterr().err
    assert "sign-in was declined" in err and "admin must approve" not in err
    assert env.values == {}
    browser(monkeypatch, lambda url, seen: seen.update(callback=callback(port_of(url), {"error": "access_denied", "error_description": "the user cancelled",
                                                                                         "state": consent_query(url)["state"][0]})))
    capsys.readouterr()
    assert auth.main(["authorize"]) == 1
    err = capsys.readouterr().err
    assert "access_denied" in err and "nothing stored" in err and env.values == {}


def test_a_tenant_whose_admin_blocked_user_consent_is_told_to_ask_the_admin(fake, env, monkeypatch, capsys):
    browser(monkeypatch, lambda url, seen: seen.update(callback=callback(port_of(url), {
        "error": "consent_required", "error_description": "AADSTS90094: admin consent is required", "state": consent_query(url)["state"][0]})))
    assert auth.main(["authorize"]) == 3
    assert "your Microsoft 365 admin must approve the app" in capsys.readouterr().err


def test_an_error_text_from_the_callback_is_cut_and_never_reflected_in_the_page(fake, env, monkeypatch):
    seen = browser(monkeypatch, lambda url, s: s.update(callback=callback(port_of(url), {
        "error": "access_denied", "error_description": "<script>alert(1)</script>" + "x" * 5000, "state": consent_query(url)["state"][0]})))
    assert auth.main(["authorize"]) == 1
    assert b"<script>" not in seen["callback"][2]


# --- check and forget --------------------------------------------------------------------------------------------------------


def run(fake, *argv, env=None):
    base = {k: v for k, v in os.environ.items() if not k.startswith("ONEDRIVE_") and not k.startswith("INTEGRATION_DOCUMENTS_ONEDRIVE")}
    return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60, env={**base, **fake.env(), **(env or {})})


def test_check_reports_whether_an_authorization_is_found_without_the_network_and_without_a_secret(fake):
    done = run(fake, "--check")
    assert done.returncode == 0
    found = json.loads(done.stdout)
    assert found["found"] is True and found["source"].startswith("environment") and found["has_refresh_token"] is True
    assert (found["scope"], found["account_kind"], found["tenant"], found["obtained_at"]) == ("Files.Read", "personal", "common", "2026-10-15T08:00:00Z")
    assert fake.requests == [] and fake.token_forms == []
    for secret in SECRETS:
        assert secret not in done.stdout + done.stderr
    missing = run(fake, "--check", env={"ONEDRIVE_SOURCES_TOKEN": ""})
    assert missing.returncode == 3 and json.loads(missing.stdout) == {"found": False} and "authorize" in missing.stderr
    broken = run(fake, "--check", env={"ONEDRIVE_SOURCES_TOKEN": "not json"})
    assert broken.returncode == 3 and "unreadable or incomplete" in broken.stderr


def test_the_commands_are_checked_before_anything_starts(fake):
    assert run(fake).returncode == 2
    assert run(fake, "--check", "authorize").returncode == 2
    assert run(fake, "forget", "--no-browser").returncode == 2
    assert run(fake, "authorize", "--bogus").returncode == 2
    # test mode never touches the real store: authorize and forget refuse before anything else
    done = run(fake, "forget")
    assert done.returncode == 2 and "never uses the OS secret store" in done.stderr
    done = run(fake, "authorize", "--no-browser", env={"ONEDRIVE_CLIENT_ID": fake_graph.CLIENT_ID})
    assert done.returncode == 2 and "never uses the OS secret store" in done.stderr and fake.requests == []


def test_forget_deletes_our_record_and_only_that_and_says_how_to_revoke(env, monkeypatch, capsys):
    env.values[("openhora", "onedrive-sources")] = "a record"
    env.values[("openhora", "gdrive-sources")] = "another provider's record"
    assert auth.main(["forget"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["forgotten"] is True and env.values == {("openhora", "gdrive-sources"): "another provider's record"}
    assert "local record only" in err and "revoke" in err
    assert auth.main(["forget"]) == 0 and json.loads(capsys.readouterr().out)["forgotten"] is False, "nothing stored is not an error"


def test_forget_reports_a_store_that_fails_without_hiding_it(env, monkeypatch, capsys):
    class Locked:
        def delete_password(self, service, username):
            raise RuntimeError("locked")

    monkeypatch.setattr(od, "keyring_module", lambda test_mode: Locked())
    assert auth.main(["forget"]) == 1
    assert "cannot delete from the OS secret store: RuntimeError" in capsys.readouterr().err


def test_an_access_token_that_could_not_be_sent_as_a_header_stores_nothing_and_is_not_shown(fake, env, monkeypatch, capsys):
    fake.access_token = "tok\r\nX-Injected: 1"
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 1
    err = capsys.readouterr().err
    assert env.values == {} and "will not send" in err and "X-Injected" not in err and "Traceback" not in err


def test_a_step_the_command_cannot_take_is_told_apart_from_a_consent_the_admin_must_give(fake, env, monkeypatch, capsys):
    browser(monkeypatch, lambda url, seen: seen.update(callback=callback(port_of(url), {
        "error": "interaction_required", "error_description": "AADSTS50076: multi-factor", "state": consent_query(url)["state"][0]})))
    assert auth.main(["authorize"]) == 3
    err = capsys.readouterr().err
    assert "multi-factor sign-in" in err and "admin must approve" not in err
