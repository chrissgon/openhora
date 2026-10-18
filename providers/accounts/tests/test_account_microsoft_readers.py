"""Tests of the three Microsoft readers (providers/documents/onedrive.py, providers/mailbox/outlook.py, providers/calendar/outlook.py) with the
account token (package ACCT-M): each reads the account record (MICROSOFT_ACCOUNT_TOKEN) first and, when it is absent, its own legacy record
with the old exact check and one note; with both it uses the account one and does not fall back when that one is refused; a token that lacks
a permission of the platform's set, or carries another, is refused (exit 3) naming the account command; the readers still send GET requests
only, and no token is on stdout or stderr (the output half of limit L59; what environment a provider is given is the runtime's half). The stand-in services are the readers' own (their fakes are loaded from
their test folders). No network but loopback, no real account, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_microsoft_readers.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
for sub in ("mailbox", "calendar", "documents"):
    sys.path.insert(0, str(PROVIDERS / sub / "tests"))
import fake_graph  # noqa: E402  (the OneDrive stand-in)
import fake_graph_cal  # noqa: E402
import fake_graph_mail  # noqa: E402

PLATFORM = ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")
PREFIX = "https://graph.microsoft.com/"
SET_URL = " ".join(PREFIX + name for name in PLATFORM) + " offline_access"
GRANTED = SET_URL + " openid profile"
ACCOUNT_COMMAND = "microsoft_auth.py authorize"
ACCOUNT_REFRESH = "fake-account-refresh-token-not-real"
LEGACY_REFRESH = "fake-refresh-token-0-not-real"          # what every fake of the readers accepts as its first refresh token
ACCOUNT_VARIABLES = ("MICROSOFT_",)
FILTERED = ("OUTLOOK_", "MAILBOX_", "INTEGRATION_CALENDAR_", "INTEGRATION_DOCUMENTS_ONEDRIVE", "ONEDRIVE_", "MICROSOFT_")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


READERS = {
    "onedrive": PROVIDERS / "documents" / "onedrive.py",
    "mail": PROVIDERS / "mailbox" / "outlook.py",
    "calendar": PROVIDERS / "calendar" / "outlook.py",
}
LEGACY = {"onedrive": ("onedrive-sources", "ONEDRIVE_SOURCES_TOKEN", "Files.Read"), "mail": ("outlook-mail", "OUTLOOK_MAIL_TOKEN", "Mail.Read"),
          "calendar": ("outlook-calendar", "OUTLOOK_CALENDAR_TOKEN", "Calendars.ReadBasic")}
MODULES = {kind: load(path, f"reader_{kind}_for_the_account_tests") for kind, path in READERS.items()}


class Case:
    """One reader, its stand-in service and the way to run it as a process."""

    def __init__(self, kind: str):
        self.kind, self.script = kind, READERS[kind]
        self.username, self.legacy_secret, self.legacy_scope = LEGACY[kind]
        if kind == "onedrive":
            self.fake = fake_graph.FakeGraph()
            self.fake.add_file(fake_graph.DRIVE, "DOC1!101", "Weekly notes.docx", b"PK\x03\x04 a fictional note", mime=fake_graph.DOCX)
            self.command = ["search", "--query", "notes"]
            self.client_id = fake_graph.CLIENT_ID
        elif kind == "mail":
            self.fake = fake_graph_mail.FakeGraphMail()
            self.fake.add("m1", "2026-10-17T07:12:03Z", "Ana Lima", "ana@clinic.example", "Appointment confirmed", html="<p>Hello</p>")
            self.command = ["search", "--query", "in:inbox", "--since", "2026-10-01T00:00:00Z"]
            self.client_id = self.fake.CLIENT_ID
        else:
            self.fake = fake_graph_cal.FakeGraphCal()
            self.command = ["calendars"]
            self.client_id = self.fake.CLIENT_ID
        self.secrets = (self.fake.access_token if hasattr(self.fake, "access_token") else fake_graph.ACCESS_TOKEN, LEGACY_REFRESH, ACCOUNT_REFRESH)

    def overrides(self) -> dict:
        """The test overrides and nothing else of the fake's environment (the legacy record is each test's own choice)."""
        return {k: v for k, v in self.fake.env().items() if k != self.legacy_secret}

    def account_record(self, **over) -> dict:
        record = {"slot": "main", "refresh_token": ACCOUNT_REFRESH, "client_id": self.client_id, "tenant": "common", "scope": " ".join(PLATFORM),
                  "account_kind": "personal", "account": "casey.rivera@mail.example", "obtained_at": "2026-10-18T08:00:00Z"}
        record.update(over)
        return record

    def accept_account_token(self):
        """The service knows the account's refresh token and answers the platform's set."""
        self.fake.valid_refresh.add(ACCOUNT_REFRESH)
        self.fake.scope_granted = GRANTED

    def run(self, *argv, account=None, legacy=None, extra=None):
        base = {k: v for k, v in os.environ.items() if not k.startswith(FILTERED)}
        env = {**base, **self.overrides()}
        if account is not None:
            env["MICROSOFT_ACCOUNT_TOKEN"] = account if isinstance(account, str) else json.dumps(account)
        if legacy is not None:
            env[self.legacy_secret] = legacy if isinstance(legacy, str) else json.dumps(legacy)
        env.update(extra or {})
        done = subprocess.run([sys.executable, str(self.script), *argv], capture_output=True, text=True, timeout=120, env=env)
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stdout, done.stderr

    def legacy_record(self, **over) -> dict:
        return self.fake.record(**over)


@pytest.fixture(params=sorted(READERS))
def case(request):
    c = Case(request.param)
    yield c
    c.fake.close()


# --- the account record alone ------------------------------------------------------------------------------------------------


def test_a_reader_works_with_the_account_record_alone_and_says_which_record_it_used(case):
    case.accept_account_token()
    code, out, stdout, stderr = case.run("--check", account=case.account_record())
    assert code == 0, stderr
    assert out["ok"] is True and out["record"] == "account" and out["scope"] == " ".join(PLATFORM) and out["tenant"] == "common"
    assert "legacy" not in stderr, "no note: the account token is the way to sign in"
    form = case.fake.token_forms[0]
    assert form["grant_type"] == "refresh_token" and form["refresh_token"] == ACCOUNT_REFRESH
    assert form["scope"] == SET_URL, "the refresh names the platform's whole set and offline_access, nothing else"
    assert "client_secret" not in form
    code, out, stdout, stderr = case.run(*case.command, account=case.account_record())
    assert code == 0 and out is not None, stderr


def test_a_reader_sends_get_requests_only_to_graph_with_the_account_token(case):
    """The readers send GET only (and the token POST), whatever the token could do."""
    case.accept_account_token()
    assert case.run(*case.command, account=case.account_record())[0] == 0
    assert case.fake.methods and set(case.fake.methods) == {"GET"}, case.fake.methods
    assert all(r["method"] == "GET" for r in case.fake.requests)
    assert case.fake.token_forms and all(f["grant_type"] == "refresh_token" for f in case.fake.token_forms)


def test_no_token_is_on_stdout_or_stderr_on_any_path(case):
    """The output half of limit L59: the account token reaches a provider process and no output of it."""
    case.accept_account_token()
    outputs = []
    for argv, record in ((("--check",), case.account_record()), (case.command, case.account_record()),
                         (("--check",), case.account_record(refresh_token="fake-refused-refresh-token-not-real"))):
        outputs.append(case.run(*argv, account=record)[2:])
    case.fake.scope_granted = " ".join(PREFIX + n for n in PLATFORM[:-1]) + " offline_access"   # lacks User.Read
    outputs.append(case.run("--check", account=case.account_record())[2:])
    case.fake.scope_granted = GRANTED + " " + PREFIX + "Directory.Read.All"
    outputs.append(case.run("--check", account=case.account_record())[2:])
    for text in outputs:
        for secret in (*case.secrets, case.fake.access_token if hasattr(case.fake, "access_token") else "", "fake-refused-refresh-token-not-real",
                       "fake-refresh-token-1-not-real", "fake-refresh-token-2-not-real"):
            assert secret not in "".join(text), secret


def test_the_token_of_the_service_is_rejected_with_the_account_command_not_the_legacy_one(case):
    case.accept_account_token()
    case.fake.fail_next = (401, {}, {"error": {"code": "InvalidAuthenticationToken", "message": "Access token has expired."}})
    code, _, _, stderr = case.run(*case.command, account=case.account_record())
    assert code == 3 and ACCOUNT_COMMAND in stderr and case.username not in stderr and "outlook_auth.py" not in stderr and "onedrive_auth.py" not in stderr


def test_a_token_that_lacks_a_permission_of_the_set_is_refused_before_anything_is_read(case):
    case.accept_account_token()
    for missing in PLATFORM:
        case.fake.scope_granted = " ".join(PREFIX + n for n in PLATFORM if n != missing) + " offline_access openid"
        before = len(case.fake.requests)
        code, _, _, stderr = case.run(*case.command, account=case.account_record())
        assert code == 3, missing
        assert f"lacks {missing}" in stderr and ACCOUNT_COMMAND in stderr and "keep every box ticked" in stderr, stderr
        assert "nothing was read" in stderr and "nothing was stored" not in stderr
        assert len(case.fake.requests) == before, "no Graph call was made with the token"


def test_a_token_that_carries_another_permission_is_refused_and_says_how_to_remove_it(case):
    case.accept_account_token()
    for extra in ("Mail.Read", "Calendars.ReadBasic", "Files.Read", "Files.ReadWrite.All", "Directory.Read.All"):
        case.fake.scope_granted = GRANTED + " " + PREFIX + extra
        code, _, _, stderr = case.run("--check", account=case.account_record())
        assert code == 3, extra
        assert f"carries {extra}" in stderr and "does not ask" in stderr and "revoke the app's access" in stderr and ACCOUNT_COMMAND in stderr
    case.fake.omit_scope = True
    assert case.run("--check", account=case.account_record())[0] == 3, "a response that reports no scope cannot be shown to be the set"


def test_a_record_made_for_another_set_or_unreadable_is_not_configured_and_nothing_is_called(case):
    case.accept_account_token()
    legacy_shape = {"refresh_token": ACCOUNT_REFRESH, "client_id": case.client_id, "tenant": "common"}
    for record, wanted in ((case.account_record(scope=case.legacy_scope), "another set of permissions"),
                           (case.account_record(scope="Mail.ReadWrite"), "another set of permissions"),
                           (case.account_record(scope=None), "another set of permissions"),
                           (case.account_record(slot="Main!"), "unreadable or incomplete"), (case.account_record(refresh_token="a b"), "unreadable or incomplete"),
                           (case.account_record(client_id="café"), "unreadable or incomplete"), (case.account_record(tenant="../evil"), "not a tenant name"),
                           ("not json", "unreadable or incomplete"), (json.dumps(legacy_shape), "unreadable or incomplete")):
        code, _, _, stderr = case.run("--check", account=record)
        assert code == 3 and wanted in stderr and ACCOUNT_COMMAND in stderr, (record, stderr)
    assert case.fake.token_forms == [] and case.fake.requests == []


def test_a_refused_refresh_token_is_not_configured_and_names_the_account_command(case):
    case.accept_account_token()
    code, _, _, stderr = case.run("--check", account=case.account_record(refresh_token="fake-not-a-valid-token"))
    assert code == 3 and "refused the refresh token" in stderr and ACCOUNT_COMMAND in stderr and "fake-not-a-valid-token" not in stderr


def test_the_record_is_read_from_the_credentials_directory_and_never_rewritten(case, tmp_path):
    case.accept_account_token()
    folder = tmp_path / "credentials"
    folder.mkdir(mode=0o700)
    file = folder / "MICROSOFT_ACCOUNT_TOKEN"
    text = json.dumps(case.account_record())
    file.write_text(text + "\n", encoding="utf-8")
    file.chmod(0o600)
    folder.chmod(0o700)
    code, out, _, stderr = case.run("--check", extra={"OPENHORA_CREDENTIALS_DIR": str(folder)})
    assert code == 0 and out["record"] == "account", stderr
    assert out["rotation"].startswith("not stored"), "the test overrides never use the store"
    assert file.read_text(encoding="utf-8") == text + "\n"


# --- the legacy record, for one cycle ------------------------------------------------------------------------------------------------


def test_a_reader_works_with_its_legacy_record_alone_as_it_always_did_and_says_so_once(case):
    code, out, _, stderr = case.run("--check", legacy=case.legacy_record())
    assert code == 0, stderr
    assert out["record"] == "legacy" and out["scope"] == case.legacy_scope
    assert case.fake.token_forms[0]["scope"] == f"{PREFIX}{case.legacy_scope} offline_access", "the old exact request"
    assert f"using the legacy record {case.username}" in stderr and ACCOUNT_COMMAND in stderr and "move to the account token" in stderr
    assert stderr.count("using the legacy record") == 1
    assert case.run(*case.command, legacy=case.legacy_record())[0] == 0


def test_the_legacy_record_keeps_its_old_exact_check_so_the_account_set_is_not_accepted_by_it(case):
    case.fake.scope_granted = GRANTED
    code, _, _, stderr = case.run("--check", legacy=case.legacy_record())
    assert code == 3 and "nothing was read" in stderr and case.legacy_scope in stderr


def test_with_both_records_the_account_one_is_used_and_the_legacy_one_is_not_even_sent(case):
    case.accept_account_token()
    code, out, _, stderr = case.run("--check", account=case.account_record(), legacy=case.legacy_record())
    assert code == 0 and out["record"] == "account", stderr
    assert [f["refresh_token"] for f in case.fake.token_forms] == [ACCOUNT_REFRESH], "the legacy token never left the process"
    assert "legacy" not in stderr


def test_an_account_record_that_the_service_refuses_does_not_fall_back_to_the_legacy_one(case):
    case.accept_account_token()
    code, _, _, stderr = case.run("--check", account=case.account_record(refresh_token="fake-revoked-account-token"), legacy=case.legacy_record())
    assert code == 3 and ACCOUNT_COMMAND in stderr
    assert [f["refresh_token"] for f in case.fake.token_forms] == ["fake-revoked-account-token"]
    code, _, _, stderr = case.run("--check", account=case.account_record(scope="Mail.Read"), legacy=case.legacy_record())
    assert code == 3 and "another set of permissions" in stderr, "a wrong account record is an error to fix, not a reason to use the old one"


@pytest.mark.parametrize("malformed", ["garbage", "[]", json.dumps({"hello": "world"}), json.dumps({"refresh_token": "x", "client_id": "y", "scope": "Mail.Read"}),
                                       json.dumps({"slot": "main"})])
def test_a_malformed_account_record_is_exit_3_naming_the_entry_and_never_a_fall_back_to_the_legacy_record(case, malformed):
    """The fall back is for an account record that is ABSENT. One that exists under microsoft-account and is not whole is an error to fix."""
    case.accept_account_token()
    for legacy in (None, case.legacy_record()):
        before = len(case.fake.token_forms)
        code, _, _, stderr = case.run("--check", account=malformed, legacy=legacy)
        assert code == 3, (malformed, legacy, stderr)
        assert "microsoft-account" in stderr and ACCOUNT_COMMAND in stderr and "microsoft_auth.py forget" in stderr, stderr
        assert "unreadable or incomplete" in stderr
        assert len(case.fake.token_forms) == before, "no token of either record was sent"
        assert "using the legacy record" not in stderr


def test_with_no_record_at_all_both_commands_are_named(case):
    code, _, _, stderr = case.run(*case.command)
    assert code == 3 and ACCOUNT_COMMAND in stderr and case.legacy_secret in stderr and "MICROSOFT_ACCOUNT_TOKEN" in stderr
    assert "_auth.py authorize" in stderr, "the legacy command, for the person who still has the old record's registration"


def test_the_legacy_note_is_said_once_per_process_and_names_the_record_never_its_content(case, monkeypatch, capsys):
    module = MODULES[case.kind]
    legacy = json.dumps(case.legacy_record())

    class Found:
        def __init__(self, name):
            self.name = name

        def resolve(self, name, allow_store=True):
            return (legacy, "environment") if name == case.legacy_secret else None

    monkeypatch.setattr(module, "secret_resolver", lambda: Found(case.legacy_secret))
    monkeypatch.setattr(module, "account_resolver", lambda: Found("none"))
    module.msgraph._NOTED_LEGACY.clear()
    for _ in range(3):
        record, where = module.load_record(True)
        assert "slot" not in record and where == "environment"
    err = capsys.readouterr().err
    assert err.count("using the legacy record") == 1 and LEGACY_REFRESH not in err and case.legacy_secret not in err.replace(case.username, "")


# --- the rotation, per reader --------------------------------------------------------------------------------------------------------


class Store:
    def __init__(self, fail=False):
        self.values, self.fail, self.writes = {}, fail, []

    def set_password(self, service, username, value):
        if self.fail:
            raise RuntimeError("the secret store is locked")
        self.writes.append((service, username))
        self.values[(service, username)] = value


class StoreResolver:
    """Finds each secret where the real resolver finds it after `authorize`: in the OS secret store, as it is NOW."""

    def __init__(self, store, names):
        self.store, self.names = store, names   # names: secret name -> (service, username)

    def resolve(self, name, allow_store=True):
        found = self.store.values.get(self.names.get(name))
        return None if found is None else (found, "secret store")


def stage(case, monkeypatch, *, account=True, legacy=False):
    """The reader module pointed at the fake, with the records in a stand-in store, so that a rotation may be written back."""
    module = MODULES[case.kind]
    store = Store()
    names = {"MICROSOFT_ACCOUNT_TOKEN": ("openhora", "microsoft-account"), case.legacy_secret: ("openhora", case.username)}
    if account:
        store.values[names["MICROSOFT_ACCOUNT_TOKEN"]] = json.dumps(case.account_record())
    if legacy:
        store.values[names[case.legacy_secret]] = json.dumps(case.legacy_record())
    case.accept_account_token()
    base, token_url = case.fake.base, case.fake.token_url
    hosts = ("127.0.0.1",) if case.kind == "onedrive" else ()
    monkeypatch.setattr(module, "endpoints", lambda: (base, token_url, hosts, False))
    resolver = StoreResolver(store, names)
    monkeypatch.setattr(module, "secret_resolver", lambda: resolver)
    monkeypatch.setattr(module, "account_resolver", lambda: resolver)
    monkeypatch.setattr(module, "keyring_module", lambda test_mode: store)
    store.initial = dict(store.values)
    return module, store, names


def test_the_rotated_token_is_written_back_into_the_account_record_and_into_no_other(case, monkeypatch):
    module, store, names = stage(case, monkeypatch, legacy=True)
    account_key, legacy_key = names["MICROSOFT_ACCOUNT_TOKEN"], names[case.legacy_secret]
    assert module.main(["--check"]) == 0
    record = json.loads(store.values[account_key])
    assert record["refresh_token"] == "fake-refresh-token-1-not-real" != ACCOUNT_REFRESH
    assert {k: v for k, v in record.items() if k != "refresh_token"} == {k: v for k, v in case.account_record().items() if k != "refresh_token"}, \
        "the slot, the scope set and the address are kept"
    assert store.values[legacy_key] == store.initial[legacy_key], "the legacy record is untouched"
    assert store.writes == [account_key]
    assert module.main(["--check"]) == 0
    assert case.fake.token_forms[-1]["refresh_token"] == "fake-refresh-token-1-not-real", "the next call refreshes with the stored token"
    assert json.loads(store.values[account_key])["refresh_token"] == "fake-refresh-token-2-not-real"


def test_a_legacy_record_is_still_rewritten_only_in_its_own_entry(case, monkeypatch):
    module, store, names = stage(case, monkeypatch, account=False, legacy=True)
    case.fake.scope_granted = f"{PREFIX}{case.legacy_scope} offline_access"
    assert module.main(["--check"]) == 0
    assert store.writes == [names[case.legacy_secret]]
    assert json.loads(store.values[names[case.legacy_secret]])["refresh_token"] == "fake-refresh-token-1-not-real"
    assert "microsoft-account" not in [u for _, u in store.values]


def test_a_store_that_cannot_be_written_does_not_stop_the_call_and_the_old_account_token_is_kept(case, monkeypatch, capsys):
    module, store, names = stage(case, monkeypatch)
    store.fail = True
    assert module.main(case.command) == 0
    err = capsys.readouterr().err
    assert "could not be stored" in err and "carrying on with the old one" in err and "RuntimeError" in err and ACCOUNT_COMMAND in err
    assert store.values == store.initial and "fake-refresh-token-1-not-real" not in err


def test_an_account_record_forgotten_or_authorized_again_while_the_call_ran_is_not_written_back(case, monkeypatch, capsys):
    module, store, names = stage(case, monkeypatch)
    key = names["MICROSOFT_ACCOUNT_TOKEN"]
    original = module.refresh_access_token

    def refresh_then_forget(token_url, record):
        got = original(token_url, record)
        del store.values[key]
        return got

    monkeypatch.setattr(module, "refresh_access_token", refresh_then_forget)
    assert module.main(["--check"]) == 0
    assert store.values == {} and json.loads(capsys.readouterr().out)["rotation"] == "not stored: the record changed meanwhile"
    newer = json.dumps(case.account_record(refresh_token="fake-refresh-token-newer-authorization"))

    def refresh_then_authorize(token_url, record):
        got = original(token_url, record)
        store.values[key] = newer
        return got

    monkeypatch.setattr(module, "refresh_access_token", refresh_then_authorize)
    store.values[key] = json.dumps(case.account_record())
    assert module.main(["--check"]) == 0
    assert store.values[key] == newer


def test_a_record_from_the_environment_or_the_credentials_directory_is_never_rewritten(case, monkeypatch):
    module, store, names = stage(case, monkeypatch)
    text = json.dumps(case.account_record())

    class Fixed:
        def __init__(self, where):
            self.where = where

        def resolve(self, name, allow_store=True):
            return text, self.where

    for where in ("environment", "credentials directory"):
        monkeypatch.setattr(module, "account_resolver", lambda where=where: Fixed(where))
        monkeypatch.setattr(module, "secret_resolver", lambda where=where: Fixed(where))
        assert module.main(["--check"]) == 0
    assert store.values == store.initial and store.writes == []
