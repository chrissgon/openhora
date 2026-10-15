"""Tests of the Drive authorization and pick commands (providers/documents/gdrive_auth.py), against the stand-in service
(fake_drive.py) and a small browser made of http.client: the consent URL asks for the scope drive.file and no other, with PKCE
S256 and a state; the client id, secret and Picker key come from the environment of the command and never from a flag or into a
printout; the authorization is stored as one record in a stand-in secret store; a later pick needs no consent. No Google host is
reached and no real credential exists.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_gdrive_auth.py
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
SCRIPT = REPO / "providers" / "documents" / "gdrive_auth.py"
sys.path.insert(0, str(HERE))
import fake_drive  # noqa: E402

_spec = importlib.util.spec_from_file_location("gdrive_auth_under_test", SCRIPT)
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)

SECRETS = (fake_drive.ACCESS_TOKEN, fake_drive.REFRESH_TOKEN, fake_drive.CLIENT_SECRET, fake_drive.API_KEY)
FILE_A, FILE_B = "1AaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaA", "1BbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbB"
PICKED = [{"id": FILE_A, "name": "Survey results", "mimeType": "application/vnd.google-apps.spreadsheet"},
          {"id": "1FolderXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "name": "Reports", "mimeType": "application/vnd.google-apps.folder"},
          {"id": FILE_B, "name": "report.pdf", "mimeType": "application/pdf"}]


class Store:
    """A stand-in secret store: set_password only."""

    def __init__(self):
        self.values = {}

    def set_password(self, service, username, value):
        self.values[(service, username)] = value


def browse(url, picks, results, nonce_sink=None):
    """What a person's browser does with the printed URL, minus Google: open /start, follow it to the consent URL (and, for the
    authorize flow, return from it with the state it carried), open the page, fetch the token, post the picks."""
    base = urllib.parse.urlparse(url)
    conn = lambda: http.client.HTTPConnection(base.hostname, base.port, timeout=10)  # noqa: E731

    def call(method, path, body=None):
        c = conn()
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                  headers={"Content-Type": "application/json"} if body is not None else {})
        r = c.getresponse()
        out = (r.status, dict(r.getheaders()), r.read())
        c.close()
        return out

    status, head, _ = call("GET", "/start")
    results["start"] = (status, head.get("Location", ""))
    location = head["Location"]
    if not location.startswith("/picker"):   # the authorize flow: the consent URL, and the way back from it
        query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        results["consent"] = query
        status, head, _ = call("GET", "/?" + urllib.parse.urlencode({"code": fake_drive.CODE, "state": query["state"][0]}))
        results["callback"] = status
        location = head["Location"]
    nonce = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)["n"][0]
    results["token"] = json.loads(call("GET", f"/token?n={nonce}")[2])
    results["page"] = call("GET", f"/picker?n={nonce}")[0]
    results["posted"] = call("POST", "/picked", {"n": nonce, "cancelled": False, "documents": picks})[0]


@pytest.fixture
def fake():
    f = fake_drive.FakeDrive()
    yield f
    f.close()


def test_the_consent_url_asks_for_drive_file_alone_with_pkce_and_a_state():
    verifier, challenge = auth.pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = auth.authorize_url(fake_drive.CLIENT_ID, "http://127.0.0.1:5555", "the-state", challenge)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert query["scope"] == ["https://www.googleapis.com/auth/drive.file"], "one scope, and it is the narrow one"
    assert query["code_challenge_method"] == ["S256"] and query["code_challenge"] == [challenge] and query["state"] == ["the-state"]
    assert query["response_type"] == ["code"] and query["redirect_uri"] == ["http://127.0.0.1:5555"]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"] and "include_granted_scopes" not in query
    assert fake_drive.CLIENT_SECRET not in url and "client_secret" not in query


def test_the_provider_and_the_authorization_name_one_and_the_same_scope_and_no_other():
    import re
    for name in ("gdrive.py", "gdrive_auth.py", "gdrive_picker.py"):
        text = (REPO / "providers" / "documents" / name).read_text(encoding="utf-8")
        scopes = set(re.findall(r"https://www\.googleapis\.com/auth/[a-z.]+", text))
        assert scopes <= {"https://www.googleapis.com/auth/drive.file"}, f"{name} names a scope beyond drive.file"
    assert auth.SCOPE == auth.gdrive.SCOPE == "https://www.googleapis.com/auth/drive.file"


def test_the_client_comes_from_the_environment_of_the_command_never_from_a_flag(monkeypatch):
    for name, _ in auth.INPUTS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GDRIVE_PROJECT_NUMBER", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(auth.ProviderError) as missing:
        auth.client_inputs()
    assert missing.value.code == 3 and "GDRIVE_CLIENT_ID" in str(missing.value) and "hidden prompt" in str(missing.value)
    monkeypatch.setenv("GDRIVE_CLIENT_ID", fake_drive.CLIENT_ID)
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", fake_drive.CLIENT_SECRET)
    monkeypatch.setenv("GDRIVE_PICKER_API_KEY", fake_drive.API_KEY)
    got = auth.client_inputs()
    assert got["project_number"] == "123456789012" and got["GDRIVE_CLIENT_SECRET"] == fake_drive.CLIENT_SECRET
    monkeypatch.setenv("GDRIVE_CLIENT_ID", "no-number-client")
    with pytest.raises(auth.ProviderError) as number:
        auth.client_inputs()
    assert number.value.code == 2 and "GDRIVE_PROJECT_NUMBER" in str(number.value)
    monkeypatch.setenv("GDRIVE_PROJECT_NUMBER", "999")
    assert auth.client_inputs()["project_number"] == "999"
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", "has a space")
    with pytest.raises(auth.ProviderError):
        auth.client_inputs()


def test_authorize_stores_one_record_then_opens_the_picker_and_prints_the_picks_without_a_secret(fake, monkeypatch, capsys):
    store, results = Store(), {}
    monkeypatch.setattr(auth, "keyring_module", lambda test_mode: store)
    for key, value in fake.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GDRIVE_SOURCES_TOKEN")
    monkeypatch.setenv("GDRIVE_CLIENT_ID", fake_drive.CLIENT_ID)
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", fake_drive.CLIENT_SECRET)
    monkeypatch.setenv("GDRIVE_PICKER_API_KEY", fake_drive.API_KEY)
    # The consent URL leads to Google, which the test does not reach: the "browser" below returns from it with the state it carried.
    monkeypatch.setattr(auth.webbrowser, "open", lambda url: threading.Thread(target=browse, args=(url, PICKED, results), daemon=True).start())
    assert auth.authorize(open_browser=True) == 0
    out, err = capsys.readouterr()
    assert results["start"][1].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert results["consent"]["scope"] == ["https://www.googleapis.com/auth/drive.file"] and results["callback"] == 302
    assert results["token"]["apiKey"] == fake_drive.API_KEY and results["page"] == 200 and results["posted"] == 200
    printed = json.loads(out)
    assert printed["authorized"] is True and [p["id"] for p in printed["picked"]] == [FILE_A, FILE_B], "the folder was dropped"
    assert printed["secret_store"] == {"service": "openhora", "username": "gdrive-sources"}
    record = json.loads(store.values[("openhora", "gdrive-sources")])
    assert set(record) == {"refresh_token", "client_id", "client_secret", "api_key", "project_number", "scope", "obtained_at"}
    assert record["refresh_token"] == fake_drive.REFRESH_TOKEN and record["scope"] == fake_drive.SCOPE
    form = [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"][0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert results["consent"]["code_challenge"] == [challenge], "the code was exchanged with the verifier of the challenge sent"
    for text in (out, err):
        for secret in SECRETS:
            assert secret not in text


def test_authorize_with_a_wrong_state_stores_nothing_and_fails(fake, monkeypatch, capsys):
    store = Store()
    monkeypatch.setattr(auth, "keyring_module", lambda test_mode: store)
    for key, value in fake.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GDRIVE_CLIENT_ID", fake_drive.CLIENT_ID)
    monkeypatch.setenv("GDRIVE_CLIENT_SECRET", fake_drive.CLIENT_SECRET)
    monkeypatch.setenv("GDRIVE_PICKER_API_KEY", fake_drive.API_KEY)
    seen = {}

    def forged(url):
        def go():
            base = urllib.parse.urlparse(url)
            c = http.client.HTTPConnection(base.hostname, base.port, timeout=10)
            c.request("GET", "/?" + urllib.parse.urlencode({"code": fake_drive.CODE, "state": "forged"}))
            seen["status"] = c.getresponse().status
        threading.Thread(target=go, daemon=True).start()

    monkeypatch.setattr(auth.webbrowser, "open", forged)
    assert auth.main(["authorize"]) == 1
    assert seen["status"] == 401 and store.values == {} and not [f for f in fake.token_forms if f.get("grant_type") == "authorization_code"]
    assert "state parameter does not match" in capsys.readouterr().err


PROVIDER = REPO / "providers" / "documents" / "gdrive.py"


def run_pick(fake, extra_env=None, record=None, script=SCRIPT):
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("GDRIVE_")}, **fake.env(**(record or {})), **(extra_env or {})}
    return subprocess.Popen([sys.executable, str(script), "pick", "--no-browser"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env)


def printed_url(proc):
    for line in proc.stderr:
        if line.startswith("http://127.0.0.1:"):
            return line.strip()
    raise AssertionError("the command printed no local URL")


def test_a_later_pick_refreshes_the_token_and_needs_no_consent(fake):
    proc = run_pick(fake)
    results = {}
    browse(printed_url(proc), PICKED, results)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert "consent" not in results and results["start"][1].startswith("/picker?n="), "no trip to Google"
    assert results["token"] == {"token": fake_drive.ACCESS_TOKEN, "apiKey": fake_drive.API_KEY, "appId": "123456789012"}
    printed = json.loads(out)
    assert printed == {"picked": [{"id": FILE_A, "name": "Survey results", "mime_type": "application/vnd.google-apps.spreadsheet"},
                                  {"id": FILE_B, "name": "report.pdf", "mime_type": "application/pdf"}], "cancelled": False}
    assert [f["grant_type"] for f in fake.token_forms] == ["refresh_token"]
    for text in (out, err):
        for secret in (fake_drive.REFRESH_TOKEN, fake_drive.CLIENT_SECRET, fake_drive.API_KEY, fake_drive.ACCESS_TOKEN):
            assert secret not in text


def test_a_pick_without_an_authorization_or_without_a_picker_key_says_what_to_run(fake):
    proc = run_pick(fake, extra_env={"GDRIVE_SOURCES_TOKEN": ""})
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 3 and "gdrive_auth.py authorize" in err and out == ""
    proc = run_pick(fake, record={"api_key": ""})
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 3 and "no Picker API key" in err
    assert fake.token_forms == [], "nothing was asked of Google"


def test_the_commands_are_checked_before_anything_starts(fake):
    run = lambda *argv: subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=60,  # noqa: E731
                                       env={**os.environ, **fake.env()})
    assert run().returncode == 2 and run("--check", "pick").returncode == 2
    checked = run("--check")
    assert checked.returncode == 0 and json.loads(checked.stdout)["has_refresh_token"] is True
    for secret in SECRETS:
        assert secret not in checked.stdout + checked.stderr
    missing = subprocess.run([sys.executable, str(SCRIPT), "--check"], capture_output=True, text=True, timeout=60,
                             env={**os.environ, **fake.env(), "GDRIVE_SOURCES_TOKEN": ""})
    assert missing.returncode == 3 and json.loads(missing.stdout) == {"found": False}


def test_the_provider_has_a_pick_verb_that_is_the_same_command_and_the_runtime_starts_it_through_the_resolver(fake):
    proc = run_pick(fake, script=PROVIDER)
    results = {}
    browse(printed_url(proc), PICKED, results)
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert [p["id"] for p in json.loads(out)["picked"]] == [FILE_A, FILE_B] and "consent" not in results
    missing = run_pick(fake, extra_env={"GDRIVE_SOURCES_TOKEN": ""}, script=PROVIDER)
    out, err = missing.communicate(timeout=60)
    assert missing.returncode == 3 and "gdrive_auth.py authorize" in err and out == ""
    for argv in (["stat", "--id", FILE_A, "--as-source", "--no-browser"], ["pick", "--as-source"]):
        done = subprocess.run([sys.executable, str(PROVIDER), *argv], capture_output=True, text=True, timeout=60, env={**os.environ, **fake.env()})
        assert done.returncode == 2, argv
