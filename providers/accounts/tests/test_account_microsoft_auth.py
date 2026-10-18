"""Tests of the Microsoft account authorization command (providers/accounts/microsoft_auth.py), against the stand-in service
(fake_ms_account.py) and a small browser made of http.client: the consent URL asks for exactly the platform's five permissions and
offline_access, with PKCE S256, a state and the code in the query; the account's address is read once with GET /me; the authorization is
stored as one record of its own (a slot, the scope set, the address) in a stand-in secret store; a token that lacks one permission of the set
or carries another stores nothing and exits 3 naming the command; the client id comes from the environment and never from a flag; `check`
reads the record back without a network call and prints no token; `forget` deletes that one record and no other. No Microsoft host is reached
and no real credential exists.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_microsoft_auth.py
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import importlib.util
import json
import re
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
SCRIPT = HERE.parent / "microsoft_auth.py"
sys.path.insert(0, str(HERE))
import fake_ms_account  # noqa: E402

_spec = importlib.util.spec_from_file_location("microsoft_account_auth_under_test", SCRIPT)
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)

KEY = ("openhora", "microsoft-account")
SECRETS = (fake_ms_account.ACCESS_TOKEN, fake_ms_account.REFRESH_TOKEN, fake_ms_account.CODE)
PREFIX = "https://graph.microsoft.com/"
SET_URL = " ".join(PREFIX + name for name in fake_ms_account.PLATFORM) + " offline_access"


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
    f = fake_ms_account.FakeMsAccount()
    yield f
    f.close()


@pytest.fixture
def env(fake, monkeypatch):
    for key, value in fake.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("MICROSOFT_TENANT", raising=False)
    monkeypatch.delenv("MICROSOFT_ACCOUNT_TOKEN", raising=False)
    store = Store()
    monkeypatch.setattr(auth, "keyring_module", lambda test_mode: store)
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
    seen["callback"] = callback(port_of(url), {"code": fake_ms_account.CODE, "state": query["state"][0]})


def granted(*names, extra="offline_access openid profile"):
    return " ".join(PREFIX + name for name in names) + " " + extra


# --- the consent URL ---------------------------------------------------------------------------------------------------------


def test_the_consent_url_asks_for_the_platform_set_and_offline_access_alone_with_pkce_a_state_and_the_code_in_the_query():
    verifier, challenge = auth.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = auth.authorize_url(fake_ms_account.CLIENT_ID, "common", "http://localhost:5555", "the-state", challenge)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    assert query["scope"] == [SET_URL], "the five permissions of the platform and the refresh token, nothing else"
    assert query["scope"][0].split() == [PREFIX + n for n in ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")] + ["offline_access"]
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"] == [challenge] and query["state"] == ["the-state"]
    assert query["response_type"] == ["code"] and query["response_mode"] == ["query"] and query["redirect_uri"] == ["http://localhost:5555"]
    assert query["prompt"] == ["select_account"] and query["client_id"] == [fake_ms_account.CLIENT_ID]
    assert set(query) == {"client_id", "response_type", "redirect_uri", "response_mode", "scope", "state", "code_challenge", "code_challenge_method",
                          "prompt"}
    assert "client_secret" not in query and "login_hint" not in query and "include_granted_scopes" not in query


def test_an_offices_own_tenant_is_the_authority_of_the_url():
    url = auth.authorize_url(fake_ms_account.CLIENT_ID, "contoso.example", "http://localhost:1", "s", "c")
    assert url.startswith("https://login.microsoftonline.com/contoso.example/oauth2/v2.0/authorize?")


def test_the_platform_set_is_the_one_in_the_code_the_record_and_the_secret_contract():
    assert auth.PLATFORM_SCOPES == fake_ms_account.PLATFORM == ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")
    assert auth.PROFILE.refresh_scope == SET_URL and auth.PROFILE.account is True and auth.PROFILE.scope is None
    assert (auth.SECRET, auth.KEYRING_USERNAME) == ("MICROSOFT_ACCOUNT_TOKEN", "microsoft-account")
    assert (auth.PROFILE.client_id_var, auth.PROFILE.tenant_var) == ("MICROSOFT_CLIENT_ID", "MICROSOFT_TENANT")
    contract = (PROVIDERS.parent / "contracts" / "secrets.md").read_text(encoding="utf-8")
    for name in fake_ms_account.PLATFORM:
        assert name in contract


# --- the inputs of the command -----------------------------------------------------------------------------------------------


def test_the_client_id_comes_from_the_environment_of_the_command_or_a_hidden_prompt_never_from_a_flag(monkeypatch):
    monkeypatch.delenv("MICROSOFT_CLIENT_ID", raising=False)
    monkeypatch.delenv("MICROSOFT_TENANT", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(auth.ProviderError) as missing:
        auth.client_inputs()
    assert missing.value.code == 3 and "MICROSOFT_CLIENT_ID" in str(missing.value)
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", fake_ms_account.CLIENT_ID)
    assert auth.client_inputs() == {"client_id": fake_ms_account.CLIENT_ID, "tenant": "common"}
    monkeypatch.setenv("MICROSOFT_TENANT", "contoso.example")
    assert auth.client_inputs()["tenant"] == "contoso.example"
    monkeypatch.setenv("MICROSOFT_TENANT", "../evil")
    with pytest.raises(auth.ProviderError) as refused:
        auth.client_inputs()
    assert refused.value.code == 2
    monkeypatch.delenv("MICROSOFT_TENANT")
    for bad in ("has a space", "café", "x" * 101, "tab\tid"):
        monkeypatch.setenv("MICROSOFT_CLIENT_ID", bad)
        with pytest.raises(auth.ProviderError) as refused:
            auth.client_inputs()
        assert refused.value.code == 2, bad
    monkeypatch.delenv("MICROSOFT_CLIENT_ID")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(auth.msgraph.getpass, "getpass", lambda prompt: f" {fake_ms_account.CLIENT_ID} ")
    assert auth.client_inputs()["client_id"] == fake_ms_account.CLIENT_ID, "a terminal gets the hidden prompt"
    done = subprocess.run([sys.executable, str(SCRIPT), "authorize", "--client-id", "x"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and "--client-id" in done.stderr, "no flag carries the id"


def test_only_the_slot_main_exists_and_a_bad_slot_is_a_usage_error(fake, env, monkeypatch, capsys):
    opened = []
    monkeypatch.setattr(auth.webbrowser, "open", opened.append)
    for command in ("authorize", "check", "forget"):
        assert auth.main([command, "--account", "work"]) == 2
        assert auth.main([command, "--account", "Bad Slot!"]) == 2
        assert auth.main([command, "--account", "x" * 13]) == 2
    err = capsys.readouterr().err
    assert "only the slot main exists" in err and "second account is not built" in err
    assert opened == [] and env.values == {} and fake.token_forms == [] and fake.requests == []
    assert auth.main(["check", "--no-browser"]) == 2, "--no-browser is for authorize only"


# --- authorize ---------------------------------------------------------------------------------------------------------------


def test_authorize_stores_one_record_of_its_own_reads_the_address_once_and_prints_no_secret(fake, env, monkeypatch, capsys):
    seen = browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 0
    out, err = capsys.readouterr()
    assert seen["callback"][0] == 200 and b"Authorization received" in seen["callback"][2]
    consent = consent_query(seen["url"])
    assert consent["scope"] == [SET_URL] and consent["redirect_uri"][0].startswith("http://localhost:")
    printed = json.loads(out)
    assert printed == {"authorized": True, "secret_store": {"service": "openhora", "username": "microsoft-account"}, "slot": "main",
                       "account": fake_ms_account.ADDRESS, "account_kind": "personal", "scopes": list(fake_ms_account.PLATFORM),
                       "tenant": "common", "obtained_at": printed["obtained_at"]}
    assert list(env.values) == [KEY], "one record, in an entry of its own"
    record = json.loads(env.values[KEY])
    assert set(record) == {"slot", "refresh_token", "client_id", "tenant", "scope", "account_kind", "account", "obtained_at"}
    assert record["slot"] == "main" and record["refresh_token"] == fake_ms_account.REFRESH_TOKEN
    assert record["client_id"] == fake_ms_account.CLIENT_ID and record["tenant"] == "common"
    assert record["scope"] == "Mail.ReadWrite Mail.Send Calendars.ReadWrite Files.ReadWrite User.Read"
    assert record["account"] == fake_ms_account.ADDRESS and record["account_kind"] == "personal"
    form = [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"][0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert consent["code_challenge"] == [challenge], "the code was exchanged with the verifier of the challenge sent"
    assert form["redirect_uri"] == consent["redirect_uri"][0] and form["scope"] == SET_URL and "client_secret" not in form
    seen_calls = [(r["method"], r["path"], r["query"]) for r in fake.api_requests()]
    assert seen_calls == [("GET", "/v1.0/me", {"$select": "mail,userPrincipalName"}), ("GET", "/v1.0/me/drive", {"$select": "id,driveType"})], \
        "GET /me once for the address, and the kind of account: nothing else"
    assert set(fake.methods) == {"GET"}
    for text in (out, err):
        for secret in SECRETS:
            assert secret not in text, "no token on stdout or stderr"
    assert seen["url"] in err and fake_ms_account.CLIENT_ID in seen["url"], "the printed URL holds the public client id, the state and the challenge"


def test_the_address_is_the_mail_property_and_the_principal_name_when_there_is_none(fake, env, monkeypatch):
    fake.address = None
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 0
    assert json.loads(env.values[KEY])["account"] == "casey.rivera@work.example"


def test_an_address_that_cannot_be_read_stores_nothing(fake, env, monkeypatch, capsys):
    browser(monkeypatch, returns_with_the_code)
    fake.me_status = 403
    assert auth.main(["authorize"]) == 1
    assert env.values == {} and "Graph refused the request (profile get)" in capsys.readouterr().err
    fake.me_status, fake.address, fake.principal = 200, None, None
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 1
    assert env.values == {} and "no address" in capsys.readouterr().err
    for bad in ("not an address", "a b@mail.example", "café@mail.example", "@x", "x" * 400 + "@mail.example"):
        fake.address = bad
        browser(monkeypatch, returns_with_the_code)
        assert auth.main(["authorize"]) == 1, bad
        assert env.values == {}, bad
    capsys.readouterr()


def test_a_kind_of_account_that_cannot_be_read_is_a_note_and_not_a_failure(fake, env, monkeypatch, capsys):
    fake.drive_status = 500
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 0
    assert json.loads(env.values[KEY])["account_kind"] == "unknown"
    assert "the account kind could not be read" in capsys.readouterr().err
    fake.drive_status, fake.drive_type = 200, "business"
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 0
    assert json.loads(env.values[KEY])["account_kind"] == "work"


@pytest.mark.parametrize("missing", fake_ms_account.PLATFORM)
def test_limit_59_a_consent_that_lacks_one_permission_of_the_set_stores_nothing_and_names_the_command(fake, env, monkeypatch, capsys, missing):
    fake.scope_granted = granted(*[n for n in fake_ms_account.PLATFORM if n != missing])
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 3
    out, err = capsys.readouterr()
    assert env.values == {} and fake.api_requests() == [], "nothing stored and the token was not even used"
    assert f"lacks {missing}" in err and "microsoft_auth.py authorize" in err and "keep every box ticked" in err
    assert "nothing was stored" in err and "nothing was read" not in err
    assert out == "" and not any(s in out + err for s in SECRETS)


@pytest.mark.parametrize("extra", ["Mail.Read", "Calendars.ReadBasic", "Files.ReadWrite.All", "Mail.ReadWrite.Shared", "Directory.Read.All"])
def test_limit_59_a_consent_that_carries_another_permission_stores_nothing_and_says_how_to_remove_it(fake, env, monkeypatch, capsys, extra):
    fake.scope_granted = granted(*fake_ms_account.PLATFORM, extra)
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 3
    err = capsys.readouterr().err
    assert env.values == {} and fake.api_requests() == []
    assert f"carries {extra}" in err and "does not ask" in err and "revoke the app's access" in err and "microsoft_auth.py authorize" in err
    assert "nothing was stored" in err and "nothing was read" not in err


def test_a_consent_that_both_lacks_and_carries_says_so_and_stores_nothing(fake, env, monkeypatch, capsys):
    fake.scope_granted = granted("Mail.ReadWrite", "Mail.Send", "Calendars.ReadBasic")
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 3
    err = capsys.readouterr().err
    assert "lacks Calendars.ReadWrite, Files.ReadWrite, User.Read" in err and "Calendars.ReadBasic" in err and env.values == {}


def test_a_response_with_no_scope_at_all_cannot_be_shown_to_be_the_set_and_stores_nothing(fake, env, monkeypatch, capsys):
    fake.omit_scope = True
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 3
    assert env.values == {} and "lacks" in capsys.readouterr().err


def test_the_case_of_a_permission_name_does_not_matter_and_the_words_that_grant_nothing_are_ignored(fake, env, monkeypatch):
    fake.scope_granted = "mail.readwrite MAIL.SEND Calendars.ReadWrite https://graph.microsoft.com/FILES.READWRITE USER.READ openid profile email offline_access"
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 0
    assert json.loads(env.values[KEY])["scope"] == "Mail.ReadWrite Mail.Send Calendars.ReadWrite Files.ReadWrite User.Read", "stored as the code spells the set"


def test_no_refresh_token_stores_nothing(fake, env, monkeypatch, capsys):
    fake.no_refresh_token = True
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 1
    assert env.values == {} and "no refresh token" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["zq9\r\nX-Injected: 1", "zq9 with space", "zq9" + chr(0x151) + chr(0x20AC), "zq9\x00nul", "zq9\tx"])
def test_a_refresh_token_that_is_not_printable_ascii_stores_nothing_and_is_not_shown(fake, env, monkeypatch, capsys, bad):
    browser(monkeypatch, returns_with_the_code)
    real = auth.msgraph.token_request

    def with_a_bad_refresh_token(profile, url, form):
        data = real(profile, url, form)
        data["refresh_token"] = bad
        return data

    monkeypatch.setattr(auth.msgraph, "token_request", with_a_bad_refresh_token)
    assert auth.main(["authorize"]) == 1
    out, err = capsys.readouterr()
    assert env.values == {} and "no refresh token that can be kept" in err and "X-Injected" not in out + err and "zq9" not in out + err


def test_a_store_that_cannot_be_written_fails_without_a_secret_in_the_message(fake, env, monkeypatch, capsys):
    env.fail = True
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 1
    err = capsys.readouterr().err
    assert "cannot write to the OS secret store: RuntimeError" in err and fake_ms_account.REFRESH_TOKEN not in err


def test_authorize_checks_the_store_before_it_opens_the_browser(fake, env, monkeypatch):
    monkeypatch.setattr(auth, "keyring_module", lambda test_mode: (_ for _ in ()).throw(auth.ProviderError("no store", 3)))
    opened = []
    monkeypatch.setattr(auth.webbrowser, "open", opened.append)
    assert auth.main(["authorize"]) == 3 and opened == []


def test_a_wrong_state_stores_nothing_ends_the_session_and_says_so(fake, env, monkeypatch, capsys):
    seen = browser(monkeypatch, lambda url, s: s.update(callback=callback(port_of(url), {"code": fake_ms_account.CODE, "state": "forged"})))
    assert auth.main(["authorize"]) == 1
    assert seen["callback"][0] == 400 and b"State mismatch" in seen["callback"][2]
    assert env.values == {} and not [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"], "the code was never exchanged"
    assert "state parameter does not match" in capsys.readouterr().err


def test_a_work_tenant_that_needs_its_admin_says_so_and_names_the_account_command(fake, env, monkeypatch, capsys):
    fake.token_status = 400
    fake.token_error = {"error": "invalid_grant", "error_description": "AADSTS65001: The user or administrator has not consented to use the application."}
    browser(monkeypatch, returns_with_the_code)
    assert auth.main(["authorize"]) == 3
    err = capsys.readouterr().err
    assert "your Microsoft 365 admin must approve the app" in err and "microsoft_auth.py authorize" in err and env.values == {}


def test_a_declined_consent_is_not_a_setup_problem(fake, env, monkeypatch, capsys):
    seen = browser(monkeypatch, lambda url, s: s.update(callback=callback(port_of(url), {
        "error": "access_denied", "error_description": "AADSTS65004: The user declined to consent.", "state": consent_query(url)["state"][0]})))
    assert auth.main(["authorize"]) == 1
    assert seen["callback"][0] == 400 and env.values == {} and "declined" in capsys.readouterr().err


# --- check -------------------------------------------------------------------------------------------------------------------


def test_check_reads_the_record_back_without_a_network_call_and_prints_no_token(fake, env, monkeypatch, capsys):
    monkeypatch.setenv("MICROSOFT_ACCOUNT_TOKEN", fake.account_record_json())
    assert auth.main(["check"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out) == {"found": True, "source": "environment (MICROSOFT_ACCOUNT_TOKEN)", "slot": "main", "account": fake_ms_account.ADDRESS,
                               "account_kind": "personal", "tenant": "common", "scopes": list(fake_ms_account.PLATFORM), "has_refresh_token": True,
                               "obtained_at": "2026-10-18T08:00:00Z"}
    assert fake.token_forms == [] and fake.requests == [], "no network"
    assert not any(s in out + err for s in SECRETS)


def test_check_without_an_authorization_is_not_configured_and_names_the_command(fake, env, capsys):
    assert auth.main(["check"]) == 3
    out, err = capsys.readouterr()
    assert json.loads(out) == {"found": False} and "microsoft_auth.py authorize" in err


def test_check_refuses_a_record_that_is_not_an_account_record_or_was_made_for_another_set(fake, env, monkeypatch, capsys):
    legacy_shape = {"refresh_token": "x", "client_id": "y", "tenant": "common", "scope": "Mail.Read"}
    for text, wanted in ((json.dumps(legacy_shape), "unreadable or incomplete"), ("not json", "unreadable or incomplete"),
                         (fake.account_record_json(scope="Mail.Read"), "another set of permissions"),
                         (fake.account_record_json(scope="Mail.ReadWrite Mail.Send"), "another set of permissions"),
                         (fake.account_record_json(scope=" ".join(fake_ms_account.PLATFORM) + " Files.ReadWrite.All"), "another set of permissions"),
                         (fake.account_record_json(slot="Main"), "unreadable or incomplete"), (fake.account_record_json(slot=5), "unreadable or incomplete"),
                         (fake.account_record_json(refresh_token="a b"), "unreadable or incomplete"),
                         (fake.account_record_json(tenant="../evil"), "not a tenant name")):
        monkeypatch.setenv("MICROSOFT_ACCOUNT_TOKEN", text)
        assert auth.main(["check"]) == 3, text
        assert wanted in capsys.readouterr().err, text


# --- forget ------------------------------------------------------------------------------------------------------------------


def test_forget_deletes_the_account_record_and_no_other_and_revokes_nothing(fake, env, capsys):
    env.values[KEY] = fake.account_record_json()
    legacy = {("openhora", name): "legacy" for name in ("onedrive-sources", "outlook-mail", "outlook-calendar")}
    env.values.update(legacy)
    assert auth.main(["forget"]) == 0
    out, err = capsys.readouterr()
    assert env.values == legacy, "the legacy records are untouched"
    assert json.loads(out) == {"forgotten": True, "secret_store": {"service": "openhora", "username": "microsoft-account"}}
    assert "local record only" in err and fake.requests == [] and fake.token_forms == []
    assert auth.main(["forget"]) == 0 and json.loads(capsys.readouterr().out)["forgotten"] is False


# --- the command line --------------------------------------------------------------------------------------------------------


def test_help_lists_the_commands_the_set_and_the_exit_codes_and_a_missing_command_is_a_usage_error():
    done = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0
    for word in ("authorize", "check", "forget", "--account", "--no-browser", *fake_ms_account.PLATFORM, "Exit codes", "MICROSOFT_CLIENT_ID"):
        assert word in done.stdout, word
    assert subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=60).returncode == 2
    assert subprocess.run([sys.executable, str(SCRIPT), "refresh"], capture_output=True, text=True, timeout=60).returncode == 2


def test_the_command_runs_on_the_interpreter_the_shared_module_runs_on():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'requires-python = ">=3.9"' in text and 'dependencies = ["keyring==25.7.0"]' in text


def test_the_accounts_folder_is_not_a_class_folder_and_the_resolver_never_lists_it():
    done = subprocess.run([sys.executable, str(PROVIDERS / "resolve.py"), "--list"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0
    assert "providers/accounts" not in done.stdout and "microsoft_auth" not in done.stdout
    classes = json.loads(done.stdout)["classes"]
    assert not [c for c in classes if "accounts" in c["folder"] or "microsoft_auth" in json.dumps(c)]
    assert re.search(r"accounts", done.stdout) is None


def test_check_of_an_unsafe_credentials_file_is_exit_3_with_the_reason_and_not_found_false(fake, env, monkeypatch, tmp_path, capsys):
    folder = tmp_path / "credentials"
    folder.mkdir(mode=0o700)
    file = folder / "MICROSOFT_ACCOUNT_TOKEN"
    file.write_text(fake.account_record_json(), encoding="utf-8")
    file.chmod(0o644)
    folder.chmod(0o700)
    monkeypatch.setenv("OPENHORA_CREDENTIALS_DIR", str(folder))
    assert auth.main(["check"]) == 3
    out, err = capsys.readouterr()
    assert "cannot be read (unsafe)" in err and "microsoft-account" in err and '"found": false' not in out.lower()
    assert fake_ms_account.REFRESH_TOKEN not in out + err
    file.chmod(0o600)
    assert auth.main(["check"]) == 0 and json.loads(capsys.readouterr().out)["found"] is True
