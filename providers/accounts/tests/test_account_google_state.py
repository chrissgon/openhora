"""Tests of the follow-ups of the review of package ACCT-G, against the stand-in service (fake_google_account.py):

- an account record that is there and cannot be read now (the credentials directory or its file is unsafe, the OS secret store is locked) is
  not absent: exit 3 with the lookup's own detail, and no legacy record takes its place;
- authorize stores nothing when the Gmail profile gives no usable address;
- limit L58, the readers' part, as a static test of the code: every call that sends a request has the literal "GET", or "POST" to token_url, as
  its method (a variable method, or a POST to another address, is a finding; the two mutations a reviewer made are tested);
- the Picker says it is not needed when only the account record exists.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_google_state.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_google_account as fga  # noqa: E402
import test_account_google_auth as ta  # noqa: E402

_spec = importlib.util.spec_from_file_location("google_state_under_test", REPO / "providers" / "_google.py")
google = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(google)
_spec = importlib.util.spec_from_file_location("resolver_state_under_test", REPO / "providers" / "secrets" / "resolver.py")
resolver = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = resolver
_spec.loader.exec_module(resolver)

GMAIL = REPO / "providers" / "mailbox" / "gmail.py"
CALENDAR = REPO / "providers" / "calendar" / "google.py"
DRIVE = REPO / "providers" / "documents" / "gdrive.py"
SHARED = REPO / "providers" / "_google.py"
STRIPPED = ("GMAIL_", "GOOGLE_", "MAILBOX_", "INTEGRATION_", "GDRIVE_", "OPENHORA_CRED", "CREDENTIALS_DIR")


class Boom(Exception):
    def __init__(self, message, code=1, status=None):
        super().__init__(message)
        self.code = code


@pytest.fixture
def fake():
    f = fga.FakeGoogleAccount()
    yield f
    f.close()


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith(STRIPPED)}


# --- an unreadable account record is not an absent one -----------------------------------------------------------------------


class KeyringLocked(Exception):
    """Named like the library's own error for a locked collection."""


class LockedStore:
    def get_password(self, service, username):
        raise KeyringLocked("the collection is locked")


class WithStore:
    """The real resolver, asked with a store of the test's making instead of the machine's."""

    def __init__(self, store):
        self.store = store

    def resolve_state(self, name, allow_store=True):
        return resolver.resolve_state(name, allow_store=allow_store, environ={}, store=self.store)


def test_a_locked_store_is_an_error_naming_the_record_and_the_legacy_loader_is_never_asked():
    asked = []
    legacy = ("calendar-google", lambda: asked.append(1) or ({"refresh_token": "r", "client_id": "i", "client_secret": "s"}, "x"), "old")
    with pytest.raises(Boom) as locked:
        google.load_account_record(WithStore(LockedStore()), False, legacy=legacy, error=Boom)
    message = str(locked.value)
    assert locked.value.code == 3 and "GOOGLE_ACCOUNT_TOKEN" in message and "google-account" in message and "(locked)" in message
    assert "unlock it" in message and "no older record takes its place" in message
    assert asked == [], "a record that is there and cannot be read is not a reason to read an older one"


def test_a_store_that_answers_nothing_is_absent_and_the_legacy_record_serves(capsys):
    class Empty:
        def get_password(self, service, username):
            return None
    loaded = google.load_account_record(WithStore(Empty()), False, legacy=("calendar-google", lambda: ({"refresh_token": "r1", "client_id": "i1",
                                                                                                       "client_secret": "s1"}, "x"), "old"), error=Boom)
    assert loaded.legacy == "calendar-google"
    assert "legacy record calendar-google" in capsys.readouterr().err


def readers():
    return [("gmail", GMAIL, lambda f: f.gmail_env(), ["--check"]), ("calendar", CALENDAR, lambda f: f.calendar_env(), ["calendars"]),
            ("drive", DRIVE, lambda f: f.drive_env(), ["stat", "--id", fga.DOC_ID, "--as-source"])]


@pytest.mark.parametrize("name, script, endpoints, args", readers(), ids=["gmail", "calendar", "drive"])
def test_an_account_file_in_the_credentials_directory_that_others_can_read_is_unsafe_and_no_legacy_record_takes_its_place(
        fake, tmp_path, name, script, endpoints, args):
    folder = tmp_path / "creds"
    folder.mkdir(mode=0o700)
    os.chmod(folder, 0o700)
    record = folder / "GOOGLE_ACCOUNT_TOKEN"
    record.write_text(fake.record_json())
    env = {**clean_env(), **endpoints(fake), "OPENHORA_CREDENTIALS_DIR": str(folder),
           **fake.legacy_gmail_env(), **fake.legacy_calendar_env(), **fake.legacy_drive_env()}
    os.chmod(record, 0o644)
    unsafe = subprocess.run([sys.executable, str(script), *args], env=env, capture_output=True, text=True, timeout=60)
    assert unsafe.returncode == 3, unsafe.stderr
    assert "GOOGLE_ACCOUNT_TOKEN" in unsafe.stderr and "unsafe" in unsafe.stderr and "no older record takes its place" in unsafe.stderr
    assert "using the legacy record" not in unsafe.stderr and fake.requests == [], "nothing was read with an older record"
    for secret in fga.SECRETS:
        assert secret not in unsafe.stdout + unsafe.stderr
    os.chmod(record, 0o600)       # the same file made safe: the account record serves
    safe = subprocess.run([sys.executable, str(script), *args], env=env, capture_output=True, text=True, timeout=60)
    assert safe.returncode == 0, safe.stderr
    assert "legacy" not in safe.stderr


# --- authorize without an address ----------------------------------------------------------------------------------------


def test_authorize_stores_nothing_when_the_profile_gives_no_usable_address(fake, monkeypatch, capsys):
    store, seen = ta.Store(), {}
    ta.configure(fake, monkeypatch, store)
    original = fake.api
    fake.api = lambda path, query: (200, {"messagesTotal": 1}) if path == "/gmail/v1/users/me/profile" else original(path, query)
    monkeypatch.setattr(ta.auth.webbrowser, "open", ta.browser(fake, seen))
    assert ta.auth.main(["authorize"]) == 1
    seen["thread"].join(10)
    out, err = capsys.readouterr()
    assert store.values == {} and "no usable address" in err and "nothing stored" in err
    assert out == "" and fga.REFRESH_TOKEN not in err
    fake.api = lambda path, query: (200, {"emailAddress": "not an address"}) if path == "/gmail/v1/users/me/profile" else original(path, query)
    seen.clear()
    monkeypatch.setattr(ta.auth.webbrowser, "open", ta.browser(fake, seen))
    assert ta.auth.main(["authorize"]) == 1
    seen["thread"].join(10)
    assert store.values == {}


# --- limit L58, the readers: the method of every request is written out --------------------------------------------------


SENDERS = ("http", "_send")


def method_findings(source: str) -> list:
    """What breaks the rule in a provider's source: a call of the one function that sends a request (`http`, or `_send` in the shared module)
    whose first argument is not the literal "GET" or "POST", a "POST" whose second argument is not the name token_url, and a request opened
    or built anywhere but inside those functions."""
    tree = ast.parse(source)
    findings = []

    def visit(node, inside):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            inside = node.name
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name in SENDERS and not (isinstance(func, ast.Attribute) and name != "_send"):
                first = node.args[0] if node.args else None
                if not (isinstance(first, ast.Constant) and first.value in ("GET", "POST")):
                    findings.append((node.lineno, f"{name}() is not given the literal GET or POST"))
                elif first.value == "POST":
                    second = node.args[1] if len(node.args) > 1 else None
                    if not (isinstance(second, ast.Name) and second.id == "token_url"):
                        findings.append((node.lineno, f"{name}() sends a POST to something other than token_url"))
            elif (name == "urlopen" or name == "Request" or (name == "open" and isinstance(func, ast.Attribute)
                                                              and getattr(func.value, "id", None) == "OPENER")) and inside not in SENDERS:
                findings.append((node.lineno, f"{name}() outside the one function that sends a request"))
        for child in ast.iter_child_nodes(node):
            visit(child, inside)

    visit(tree, None)
    return findings


@pytest.mark.parametrize("script", [GMAIL, CALENDAR, DRIVE, SHARED], ids=lambda p: p.name)
def test_limit_58_every_request_of_a_reader_is_a_literal_get_or_a_post_to_the_token_endpoint(script):
    source = script.read_text(encoding="utf-8")
    assert method_findings(source) == [], script.name
    senders = [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", None)) in SENDERS]
    assert len(senders) >= 2, "the check saw the calls it is meant to see"


def mutated(path: Path, old: str, new: str) -> str:
    source = path.read_text(encoding="utf-8")
    assert source.count(old) >= 1, (path.name, old)
    return source.replace(old, new, 1)


def test_limit_58_the_two_mutations_a_reviewer_made_are_findings():
    variable = mutated(GMAIL, 'http("GET", url,', "http(verb, url,")
    assert [m for _, m in method_findings(variable)] == ["http() is not given the literal GET or POST"]
    elsewhere = mutated(GMAIL, 'http("POST", token_url,', 'http("POST", url,')
    assert [m for _, m in method_findings(elsewhere)] == ["http() sends a POST to something other than token_url"]
    put = mutated(CALENDAR, 'http("GET", url,', 'http("PUT", url,')
    assert method_findings(put)
    shared = mutated(SHARED, '_send("GET", url,', "_send(method, url,")
    assert method_findings(shared)
    stray = mutated(DRIVE, "def open_drive", "def stray(url):\n    return urllib.request.urlopen(url)\n\n\ndef open_drive")
    assert [m for _, m in method_findings(stray)] == ["urlopen() outside the one function that sends a request"]
    assert method_findings(GMAIL.read_text(encoding="utf-8")) == []


# --- the Picker with only the account record -------------------------------------------------------------------------------


def test_the_picker_says_it_is_not_needed_when_only_the_account_record_exists(fake):
    env = {**clean_env(), **fake.drive_env(), "GOOGLE_ACCOUNT_TOKEN": fake.record_json()}
    done = subprocess.run([sys.executable, str(DRIVE), "pick", "--no-browser"], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 2
    assert "Picker is not needed" in done.stderr and "source-drive --file-id" in done.stderr and "gdrive_auth.py authorize" not in done.stderr
    assert fake.requests == []
    nothing = subprocess.run([sys.executable, str(DRIVE), "pick", "--no-browser"], env={**clean_env(), **fake.drive_env()}, capture_output=True,
                             text=True, timeout=60)
    assert nothing.returncode == 3 and "gdrive_auth.py authorize" in nothing.stderr, "with no record at all the old advice stands"
