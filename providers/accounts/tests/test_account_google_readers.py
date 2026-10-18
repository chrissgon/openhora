"""Tests of the three Google readers (providers/mailbox/gmail.py, providers/calendar/google.py, providers/documents/gdrive.py) with the account
token: each works with only the account record, with only its legacy record (the old exact rule, a warning once per process), and prefers the
account record when both exist; a token that lacks a scope of the platform's set or carries another is refused with exit 3 before any call to
an API; a refresh that omits `scope` is accepted only when the stored scope is the set; the verbs of each reader are unchanged and send GET
only (limit L58, readers); and no credential is in anything a reader prints (limit L59). Against the stand-in service (fake_google_account.py)
on 127.0.0.1; no Google host is reached and no real credential exists.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_google_readers.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_google_account as fga  # noqa: E402

GMAIL = REPO / "providers" / "mailbox" / "gmail.py"
CALENDAR = REPO / "providers" / "calendar" / "google.py"
DRIVE = REPO / "providers" / "documents" / "gdrive.py"
SET = " ".join(fga.PLATFORM_SET)
WINDOW = ["--from", "2026-10-19T00:00:00-03:00", "--to", "2026-10-23T00:00:00-03:00"]


@pytest.fixture
def fake():
    f = fga.FakeGoogleAccount()
    yield f
    f.close()


class Reader:
    """One reader, how to start it against the stand-in, and the verbs that prove it works."""

    def __init__(self, name, script, endpoints, legacy, verbs):
        self.name, self.script, self.endpoints, self.legacy, self.verbs = name, script, endpoints, legacy, verbs


def readers(tmp_path):
    out = tmp_path / "drive-out"
    out.mkdir(exist_ok=True)
    return [
        Reader("gmail", GMAIL, lambda f: f.gmail_env(), lambda f: f.legacy_gmail_env(),
               [["--check"], ["search", "--query", "in:inbox", "--limit", "1"], ["get", "--id", "msg1"]]),
        Reader("calendar", CALENDAR, lambda f: f.calendar_env(), lambda f: f.legacy_calendar_env(),
               [["--check"], ["calendars"], ["events", "--calendar", fga.ACCOUNT, *WINDOW]]),
        Reader("drive", DRIVE, lambda f: f.drive_env(), lambda f: f.legacy_drive_env(),
               [["--check"], ["stat", "--id", fga.DOC_ID, "--as-source"], ["read", "--id", fga.DOC_ID, "--as-source", "--out-dir", str(out)]]),
    ]


def base_env(tmp_path):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "MAILBOX_", "INTEGRATION_", "GDRIVE_"))}
    kept["HOME"] = str(tmp_path / "home")
    return kept


def run(reader, args, env):
    proc = subprocess.run([sys.executable, str(reader.script), *args], env=env, capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially (limit L59)
        for secret in fga.SECRETS:
            assert secret not in stream and secret[:16] not in stream, (reader.name, args)
    return proc


def account_env(fake, reader, tmp_path, **record):
    return {**base_env(tmp_path), **reader.endpoints(fake), "GOOGLE_ACCOUNT_TOKEN": fake.record_json(**record)}


def refresh_tokens(fake):
    return [urllib.parse.parse_qs(r["body"].decode())["refresh_token"][0] for r in fake.requests if r["path"] == "/token"]


# --- the account record alone ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_each_reader_works_with_only_the_account_record_and_never_says_legacy(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    for args in reader.verbs:
        fake.requests.clear()
        done = run(reader, args, account_env(fake, reader, tmp_path))
        assert done.returncode == 0, (args, done.stderr)
        assert "legacy" not in done.stderr and refresh_tokens(fake) == [fga.REFRESH_TOKEN]
        assert all(r["bearer"] for r in fake.api_requests()), "the access token rode every API call"
        assert fake.api_requests() or (reader.name == "drive" and args == ["--check"]), "the Drive check only refreshes the token"


def test_the_check_of_each_reader_names_the_account_record_and_the_platform_set(fake, tmp_path):
    gmail, calendar, drive = readers(tmp_path)
    out = json.loads(run(gmail, ["--check"], account_env(fake, gmail, tmp_path)).stdout)
    assert out == {"ok": True, "account": fga.ACCOUNT, "token_source": "environment (GOOGLE_ACCOUNT_TOKEN)", "scope": SET, "record": "account"}
    out = json.loads(run(calendar, ["--check"], account_env(fake, calendar, tmp_path)).stdout)
    assert out["ok"] is True and out["record"] == "account" and out["scope"] == sorted(fga.PLATFORM_SET) and out["account"] == fga.ACCOUNT
    out = json.loads(run(drive, ["--check"], account_env(fake, drive, tmp_path)).stdout)
    assert out["ok"] is True and out["record"] == "account" and out["scope"] == sorted(fga.PLATFORM_SET) and out["account"] == fga.ACCOUNT


def test_the_verbs_print_what_they_always_printed_from_the_account_token(fake, tmp_path):
    gmail, calendar, drive = readers(tmp_path)
    found = json.loads(run(gmail, ["search", "--query", "in:inbox", "--limit", "1"], account_env(fake, gmail, tmp_path)).stdout)
    assert [m["subject"] for m in found["messages"]] == ["Lunch on Friday"] and found["messages"][0]["external_content"] is True
    listed = json.loads(run(calendar, ["calendars"], account_env(fake, calendar, tmp_path)).stdout)
    assert [c["id"] for c in listed["calendars"]] == [fga.ACCOUNT]
    events = json.loads(run(calendar, ["events", "--calendar", fga.ACCOUNT, *WINDOW], account_env(fake, calendar, tmp_path)).stdout)
    assert [e["title"] for e in events["events"]] == ["Haircut"]
    stat = json.loads(run(drive, ["stat", "--id", fga.DOC_ID, "--as-source"], account_env(fake, drive, tmp_path)).stdout)
    assert stat["name"] == "Weekly notes" and stat["supported"] is True
    read = json.loads(run(drive, ["read", "--id", fga.DOC_ID, "--as-source", "--out-dir", str(tmp_path / "drive-out")],
                          account_env(fake, drive, tmp_path)).stdout)
    assert read["content"] == "markdown" and (tmp_path / "drive-out" / "content").read_text(encoding="utf-8") == fga.DOC_TEXT


# --- the legacy record alone, and both -------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_each_reader_still_works_with_only_its_legacy_record_and_says_so_once(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    env = {**base_env(tmp_path), **reader.endpoints(fake), **reader.legacy(fake)}
    done = run(reader, reader.verbs[1], env)
    assert done.returncode == 0, done.stderr
    warnings = [line for line in done.stderr.splitlines() if "legacy record" in line]
    assert len(warnings) == 1 and "move to the account token" in warnings[0] and "google_auth.py authorize" in warnings[0]
    assert warnings[0].startswith("warning: using the legacy record ")
    legacy_refresh = {0: fga.LEGACY_GMAIL_REFRESH, 1: fga.LEGACY_CALENDAR_REFRESH, 2: fga.LEGACY_DRIVE_REFRESH}[which]
    assert refresh_tokens(fake) == [legacy_refresh]
    again = run(reader, reader.verbs[0], env)
    assert again.returncode == 0 and len([line for line in again.stderr.splitlines() if "legacy record" in line]) == 1, "once per process"


def test_the_legacy_check_prints_what_it_always_printed(fake, tmp_path):
    gmail, calendar, drive = readers(tmp_path)
    out = json.loads(run(gmail, ["--check"], {**base_env(tmp_path), **gmail.endpoints(fake), **gmail.legacy(fake)}).stdout)
    assert out == {"ok": True, "account": fga.ACCOUNT, "token_source": "environment (GMAIL_REFRESH_TOKEN)", "scope": fga.GMAIL_READONLY}
    out = json.loads(run(calendar, ["--check"], {**base_env(tmp_path), **calendar.endpoints(fake), **calendar.legacy(fake)}).stdout)
    assert set(out) == {"ok", "scope", "account", "obtained_at"} and len(out["scope"]) == 2
    out = json.loads(run(drive, ["--check"], {**base_env(tmp_path), **drive.endpoints(fake), **drive.legacy(fake)}).stdout)
    assert out == {"ok": True, "scope": fga.DRIVE_FILE, "obtained_at": "2026-10-16T09:00:00Z"}


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_the_account_record_is_preferred_when_both_exist_and_the_legacy_one_is_not_even_used(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    env = {**account_env(fake, reader, tmp_path), **reader.legacy(fake)}
    done = run(reader, reader.verbs[1], env)
    assert done.returncode == 0, done.stderr
    assert "legacy" not in done.stderr and refresh_tokens(fake) == [fga.REFRESH_TOKEN]


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_a_reader_with_neither_record_is_not_configured_and_names_both_commands(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    done = run(reader, reader.verbs[0], {**base_env(tmp_path), **reader.endpoints(fake)})
    assert done.returncode == 3 and "accounts/google_auth.py authorize" in done.stderr and "GOOGLE_ACCOUNT_TOKEN" in done.stderr
    assert "auth.py" in done.stderr and fake.requests == []


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_an_unreadable_account_record_is_an_error_and_the_legacy_one_is_not_a_way_around_it(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    for bad in ("{broken", json.dumps({"refresh_token": "x"}), fake.record_json(slot="work")):
        done = run(reader, reader.verbs[0], {**base_env(tmp_path), **reader.endpoints(fake), **reader.legacy(fake), "GOOGLE_ACCOUNT_TOKEN": bad})
        assert done.returncode == 3 and "legacy" not in done.stderr
    assert fake.requests == []


# --- the scope set --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_a_token_that_lacks_a_scope_is_refused_before_any_api_call(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    fake.refresh_scope = " ".join(fga.PLATFORM_SET[:3])
    done = run(reader, reader.verbs[1], account_env(fake, reader, tmp_path))
    assert done.returncode == 3 and fga.DRIVE in done.stderr and "lacks" in done.stderr and "google_auth.py authorize" in done.stderr
    assert fake.api_requests() == [], "nothing was read with a token that is not the set"


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_a_token_that_carries_another_scope_is_refused_before_any_api_call(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    fake.refresh_scope = SET + " " + fga.MAIL_ALL
    done = run(reader, reader.verbs[1], account_env(fake, reader, tmp_path))
    assert done.returncode == 3 and fga.MAIL_ALL in done.stderr and "does not ask" in done.stderr and "Revoke the app's access" in done.stderr
    assert fake.api_requests() == []


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_a_refresh_that_omits_the_scope_is_accepted_only_when_the_stored_scope_is_the_set(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    fake.refresh_scope = None
    ok = run(reader, reader.verbs[1], account_env(fake, reader, tmp_path))
    assert ok.returncode == 0, ok.stderr
    fake.requests.clear()
    for stored in (" ".join(fga.PLATFORM_SET[:3]), None, SET + " " + fga.MAIL_ALL):
        bad = run(reader, reader.verbs[1], account_env(fake, reader, tmp_path, scope=stored))
        assert bad.returncode == 3, stored
    assert fake.api_requests() == []


def test_the_legacy_scope_rule_of_each_reader_is_unchanged(fake, tmp_path):
    calendar, drive = readers(tmp_path)[1], readers(tmp_path)[2]
    fake.refresh_scope = SET      # a legacy record whose token turns out to carry the platform's set: the old exact rules refuse it
    for reader in (calendar, drive):
        done = run(reader, reader.verbs[0], {**base_env(tmp_path), **reader.endpoints(fake), **reader.legacy(fake)})
        assert done.returncode == 3, reader.name
    assert fake.api_requests() == []


# --- a refused or revoked token -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_a_revoked_authorization_and_a_wrong_client_are_not_configured_and_name_the_account_command(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    fake.token_error = "invalid_grant"
    revoked = run(reader, reader.verbs[0], account_env(fake, reader, tmp_path))
    assert revoked.returncode == 3 and "invalid_grant" in revoked.stderr and "accounts/google_auth.py authorize" in revoked.stderr
    assert "In production" in revoked.stderr and "seven days" in revoked.stderr
    fake.token_error = None
    wrong = run(reader, reader.verbs[0], account_env(fake, reader, tmp_path, client_id="someone-else"))
    assert wrong.returncode == 3 and "invalid_client" in wrong.stderr
    assert fake.api_requests() == []


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_a_rejected_access_token_names_the_account_command_not_the_legacy_one(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    original = fake.token
    fake.token = lambda form: (200, {"access_token": "fake-access-token-the-api-rejects", "scope": SET})
    done = run(reader, reader.verbs[1], account_env(fake, reader, tmp_path))
    assert done.returncode == 3 and "accounts/google_auth.py authorize" in done.stderr
    fake.token = original


# --- limit L58, the readers: GET only -------------------------------------------------------------------------------------


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_limit_58_every_verb_of_each_reader_sends_get_to_the_api_and_post_only_to_the_token_endpoint(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    for args in reader.verbs:
        assert run(reader, args, account_env(fake, reader, tmp_path)).returncode == 0, args
    for env_for in (lambda: account_env(fake, reader, tmp_path), lambda: {**base_env(tmp_path), **reader.endpoints(fake), **reader.legacy(fake)}):
        assert run(reader, reader.verbs[1], env_for()).returncode == 0
    methods = {(r["method"], r["path"] == "/token") for r in fake.requests}
    assert methods == {("GET", False), ("POST", True)}, "GET to the API, POST only to the token endpoint"
    assert len(fake.requests) > 6


def test_limit_58_the_readers_hold_no_call_that_could_change_anything(tmp_path):
    for script in (GMAIL, CALENDAR, DRIVE, REPO / "providers" / "_google.py"):
        source = script.read_text(encoding="utf-8")
        methods = set(re.findall(r'\bhttp\("(\w+)"', source)) | set(re.findall(r'\b_send\("(\w+)"', source))
        assert methods <= {"GET", "POST"}, (script.name, methods)
        for method in ("PUT", "PATCH", "DELETE"):
            assert f'"{method}"' not in source and f"'{method}'" not in source, (script.name, method)
        for forbidden in (".send(", "messages/send", "batchDelete", "emptyTrash", "/trash", "files.delete", "permanentDelete"):
            assert forbidden not in source.replace("# ", ""), (script.name, forbidden)


def test_limit_58_the_stand_in_would_have_seen_a_write(fake, tmp_path):
    """The proof that the assertions above can fail: a write sent to the stand-in is recorded and answered 405."""
    import http.client
    parsed = urllib.parse.urlparse(fake.base)
    for method in ("PUT", "PATCH", "DELETE", "POST"):
        c = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
        c.request(method, "/calendar/v3/calendars/x/events", body=b"{}")
        assert c.getresponse().status == 405
        c.close()
    assert {r["method"] for r in fake.requests} == {"PUT", "PATCH", "DELETE", "POST"}


# --- limit L59: the token is in nothing a reader prints -------------------------------------------------------------------


@pytest.mark.parametrize("which", [0, 1, 2], ids=["gmail", "calendar", "drive"])
def test_limit_59_the_account_token_is_in_no_output_error_or_file_whatever_goes_wrong(fake, tmp_path, which):
    reader = readers(tmp_path)[which]
    cases = []
    for args in reader.verbs:                                                    # success
        cases.append((args, account_env(fake, reader, tmp_path), None))
    for scope in (" ".join(fga.PLATFORM_SET[:2]), SET + " " + fga.MAIL_ALL):     # a refused scope
        cases.append((reader.verbs[1], account_env(fake, reader, tmp_path), scope))
    cases.append((reader.verbs[1], account_env(fake, reader, tmp_path, client_id="someone-else"), "keep"))   # a rejected client
    cases.append((reader.verbs[1], {**account_env(fake, reader, tmp_path), "GOOGLE_ACCOUNT_TOKEN": fake.record_json(slot="work")}, "keep"))
    cases.append((["no-such-verb"], account_env(fake, reader, tmp_path), "keep"))
    for args, env, scope in cases:
        if scope != "keep":
            fake.refresh_scope = scope if scope is not None else "auto"
        done = run(reader, args, env)       # run() asserts that no credential is in stdout or stderr
        assert done.returncode in (0, 2, 3), (args, done.returncode)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert fga.REFRESH_TOKEN not in text and fga.ACCESS_TOKEN not in text and fga.CLIENT_SECRET not in text, path
