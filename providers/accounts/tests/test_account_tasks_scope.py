"""The transition rule of the account tokens when the Tasks scopes joined the set (package CB-4, OPEN-CB-7, 2026-10-27; limit L59). The maintainer's live accounts hold a token of
the four Google scopes and the five Microsoft permissions: the merge must not cut them off. So every provider but the Tasks ones accepts EXACTLY the new set or EXACTLY the previous set
(nothing between, nothing beyond), the Tasks providers need the new set and refuse the previous one with the authorize command named, and the authorization always asks the new set.

Google (providers/_google.py): five scopes with `https://www.googleapis.com/auth/tasks`, four before. Microsoft (providers/_msgraph.py): six permissions with `Tasks.ReadWrite`, five before; a
refresh names only what the provider reads (the five) unless the record holds the six, in which case it names the six. Every case here is a literal of this file; the stand-in services are the
ones of the other tests, so no network but loopback and no real credential exists.

Run: uv run --with pytest==9.1.1 pytest providers/accounts/tests/test_account_tasks_scope.py
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
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "providers" / "writer" / "tests"))
sys.path.insert(0, str(REPO / "providers" / "tasks" / "tests"))
import fake_gcal_write as fgw  # noqa: E402
import fake_google_account as fga  # noqa: E402
import fake_graph_calendar_write as fgc  # noqa: E402
import fake_graph_tasks as fgt  # noqa: E402
import fake_gtasks as fgk  # noqa: E402


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


google = load(REPO / "providers" / "_google.py", "google_for_the_transition_tests")
msgraph = load(REPO / "providers" / "_msgraph.py", "msgraph_for_the_transition_tests")
TASKS = "https://www.googleapis.com/auth/tasks"
FOUR = (fga.GMAIL_MODIFY, fga.CALENDAR_EVENTS, fga.CALENDAR_LIST, fga.DRIVE)
FIVE = FOUR + (TASKS,)
COMMAND = "google_auth.py authorize"
MS_FIVE = ("Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "Files.ReadWrite", "User.Read")
MS_SIX = MS_FIVE + ("Tasks.ReadWrite",)
PREFIX = "https://graph.microsoft.com/"
OTHER = dict(run_hint="uv run x", env_prefix="X_TEST", user_agent="openhora-test", not_found="not found", forbidden_hint="forbidden")
MS_OLD = msgraph.account_profile(**OTHER)                  # every provider but the To Do ones
MS_TASKS = msgraph.account_profile(**OTHER, tasks=True)    # the To Do providers and the authorization


class Boom(Exception):
    def __init__(self, message, code=1, status=None):
        super().__init__(message)
        self.code = code


def accepted(granted, tasks, stored=None):
    try:
        google.check_platform_scope(granted, stored, Boom, tasks=tasks)
    except Boom as refused:
        assert refused.code == 3
        return str(refused)
    return None


# --- Google: the set, the previous set and the rule ------------------------------------------------------------------------------------------------


def test_the_sets_are_the_literals_of_this_file():
    assert google.PLATFORM_SCOPES == FIVE and google.PREVIOUS_SCOPES == FOUR and google.TASKS_SCOPE == TASKS
    assert msgraph.PLATFORM_SCOPES == MS_SIX and msgraph.PREVIOUS_SCOPES == MS_FIVE and msgraph.TASKS_SCOPE == "Tasks.ReadWrite"


@pytest.mark.parametrize("granted", [" ".join(FIVE), " ".join(reversed(FIVE)), "openid email profile " + " ".join(FIVE), " ".join(FOUR), " ".join(reversed(FOUR)), "openid " + " ".join(FOUR)])
def test_a_provider_that_does_not_read_tasks_accepts_exactly_the_five_or_exactly_the_four(granted):
    assert accepted(granted, tasks=False) is None


@pytest.mark.parametrize("granted", [" ".join(FIVE), " ".join(reversed(FIVE)), "openid email profile " + " ".join(FIVE)])
def test_a_tasks_provider_accepts_exactly_the_five(granted):
    assert accepted(granted, tasks=True) is None


@pytest.mark.parametrize("granted", [" ".join(FOUR), " ".join(reversed(FOUR)), "openid email profile " + " ".join(FOUR)])
def test_a_tasks_provider_refuses_the_four_with_the_authorize_command_and_the_scope_named(granted):
    said = accepted(granted, tasks=True)
    assert said is not None and COMMAND in said and TASKS in said and "before Google Tasks" in said and "keep every box ticked" in said


@pytest.mark.parametrize("tasks", [False, True])
@pytest.mark.parametrize("granted", [" ".join(FIVE) + " https://mail.google.com/", " ".join(FOUR) + " https://mail.google.com/", " ".join(FOUR) + " https://www.googleapis.com/auth/contacts",
                                     " ".join(FIVE[:3]) + " " + TASKS, " ".join(FOUR[:3]), " ".join(FOUR[1:] + (TASKS,)), TASKS, fga.GMAIL_MODIFY, "", "openid"])
def test_nothing_between_and_nothing_beyond_the_two_sets_is_accepted_by_any_provider(granted, tasks):
    said = accepted(granted or None, tasks=tasks)
    assert said is not None and COMMAND in said


def test_a_four_scope_token_that_also_carries_a_stranger_says_both_and_is_refused_by_the_provider_of_mail_too():
    said = accepted(" ".join(FOUR) + " https://mail.google.com/", tasks=False)
    assert "does not ask" in said and "https://mail.google.com/" in said and "Revoke" in said


def test_a_refresh_that_omits_the_scope_is_judged_by_the_stored_scope_with_the_same_rule():
    assert accepted(None, tasks=False, stored=" ".join(FOUR)) is None and accepted(None, tasks=False, stored=" ".join(FIVE)) is None
    assert accepted(None, tasks=True, stored=" ".join(FIVE)) is None
    assert accepted(None, tasks=True, stored=" ".join(FOUR)) is not None
    for stored in (None, "", " ".join(FOUR[:3]), " ".join(FIVE) + " https://mail.google.com/"):
        assert accepted(None, tasks=False, stored=stored) is not None
    assert accepted(" ".join(FOUR[:3]), tasks=False, stored=" ".join(FIVE)) is not None, "a named scope is never overruled by the stored one"


def test_the_default_is_the_provider_that_does_not_read_tasks():
    google.check_platform_scope(" ".join(FOUR), None, Boom)
    with pytest.raises(Boom):
        google.check_platform_scope(" ".join(FOUR), None, Boom, tasks=True)


# --- Google: the providers that exist, end to end -----------------------------------------------------------------------------------------------


def run_calendar_writer(fake, tmp_path, *args):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    os.chmod(state, 0o700)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    env.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "GOOGLE_ACCOUNT_TOKEN": fake.record_json(scope=fake.refresh_scope), **fake.env()})
    return subprocess.run([sys.executable, str(REPO / "providers" / "writer" / "google-calendar.py"), *args], env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("scope, code", [(" ".join(FOUR), 0), (" ".join(FIVE), 0), (" ".join(FIVE) + " https://mail.google.com/", 3), (" ".join(FOUR[:3] + (TASKS,)), 3)])
def test_the_calendar_writer_works_with_the_four_and_with_the_five_and_with_nothing_else(tmp_path, scope, code):
    fake = fgw.FakeGoogleCalendar()
    try:
        fake.refresh_scope = scope
        proc = run_calendar_writer(fake, tmp_path, "--check")
        assert proc.returncode == code, proc.stderr
        if code == 3:
            assert COMMAND in proc.stderr
    finally:
        fake.close()


def run_tasks_reader(fake, tmp_path, scope):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    fake.refresh_scope = scope
    env.update({"HOME": str(tmp_path / "home"), "GOOGLE_ACCOUNT_TOKEN": fake.record_json(scope=scope), **fake.env()})
    return subprocess.run([sys.executable, str(REPO / "providers" / "tasks" / "google.py"), "--check"], env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("scope, code", [(" ".join(FIVE), 0), (" ".join(FOUR), 3), (" ".join(FIVE) + " https://mail.google.com/", 3)])
def test_the_tasks_reader_works_with_the_five_alone(tmp_path, scope, code):
    fake = fgk.FakeGoogleTasks()
    try:
        proc = run_tasks_reader(fake, tmp_path, scope)
        assert proc.returncode == code, proc.stderr
    finally:
        fake.close()


def test_the_authorization_asks_for_the_five_and_stores_nothing_for_the_four(monkeypatch):
    auth = load(REPO / "providers" / "accounts" / "google_auth.py", "google_auth_for_the_transition_tests")
    assert tuple(auth.SCOPES) == FIVE
    monkeypatch.setattr(auth.google, "token_request", lambda url, form, error=None: {"access_token": "a", "refresh_token": "r", "scope": " ".join(FOUR)})
    with pytest.raises(auth.ProviderError) as refused:
        auth.exchange_code("http://127.0.0.1:1/token", "code", "verifier", "client", "secret", "http://127.0.0.1:2")
    assert refused.value.code == 3 and "nothing stored" in str(refused.value) and "Google Tasks" in str(refused.value)
    monkeypatch.setattr(auth.google, "token_request", lambda url, form, error=None: {"access_token": "a", "refresh_token": "r", "scope": " ".join(FIVE)})
    assert auth.exchange_code("http://127.0.0.1:1/token", "code", "verifier", "client", "secret", "http://127.0.0.1:2")["scope"] == " ".join(FIVE)


# --- Microsoft: the profiles, the records and the refresh ---------------------------------------------------------------------------------------


def granted(*names, extra=""):
    return " ".join(PREFIX + n for n in names) + " offline_access openid profile email" + extra


def test_the_two_profiles_name_the_five_and_the_six_and_accept_what_they_should():
    assert MS_OLD.scopes == MS_FIVE and MS_OLD.accepted == (MS_FIVE, MS_SIX) and MS_OLD.account is True
    assert MS_TASKS.scopes == MS_SIX and MS_TASKS.accepted == (MS_SIX,)
    assert MS_OLD.refresh_scope == " ".join(PREFIX + n for n in MS_FIVE) + " offline_access" and MS_TASKS.refresh_scope == " ".join(PREFIX + n for n in MS_SIX) + " offline_access"


def ms_accepts(profile, names, extra=""):
    try:
        return msgraph.check_platform_scope(profile, granted(*names, extra=extra))
    except msgraph.ProviderError as refused:
        assert refused.code == 3
        return str(refused)


@pytest.mark.parametrize("names", [MS_FIVE, MS_SIX, tuple(reversed(MS_FIVE)), tuple(reversed(MS_SIX))])
def test_a_provider_that_does_not_read_tasks_accepts_exactly_the_five_or_exactly_the_six(names):
    stored = ms_accepts(MS_OLD, names)
    assert stored in (" ".join(MS_FIVE), " ".join(MS_SIX)) and len(stored.split()) == len(names)


def test_a_to_do_provider_accepts_exactly_the_six_and_names_the_missing_permission_for_the_five():
    assert ms_accepts(MS_TASKS, MS_SIX) == " ".join(MS_SIX)
    said = ms_accepts(MS_TASKS, MS_FIVE)
    assert "Tasks.ReadWrite" in said and "microsoft_auth.py authorize" in said and "before To Do tasks" in said


@pytest.mark.parametrize("profile", [MS_OLD, MS_TASKS])
@pytest.mark.parametrize("names, extra", [(MS_FIVE, " " + PREFIX + "Mail.Read"), (MS_SIX, " " + PREFIX + "Mail.Read"), (MS_FIVE[1:], ""), (MS_SIX[1:], ""), (MS_FIVE[:2], ""), (("Tasks.ReadWrite",), ""),
                                          ((), ""), (MS_SIX[:-1] + ("Files.Read",), "")])
def test_nothing_between_and_nothing_beyond_the_two_sets_is_accepted_by_any_microsoft_provider(profile, names, extra):
    said = ms_accepts(profile, names, extra)
    assert "microsoft_auth.py authorize" in said and "nothing was read" in said


def record_text(*names, **over):
    base = {"slot": "main", "refresh_token": "fake-refresh-token-not-real", "client_id": "fake-client-id", "tenant": "common", "scope": " ".join(names), "account_kind": "personal",
            "account": "casey.rivera@mail.example", "obtained_at": "2026-10-27T08:00:00Z"}
    base.update(over)
    return json.dumps(base)


def test_a_record_of_the_five_serves_every_provider_but_the_to_do_ones_and_a_record_of_the_six_serves_all():
    assert msgraph.parse_account_record(MS_OLD, record_text(*MS_FIVE))["scope"] == " ".join(MS_FIVE)
    assert msgraph.parse_account_record(MS_OLD, record_text(*MS_SIX))["scope"] == " ".join(MS_SIX)
    assert msgraph.parse_account_record(MS_TASKS, record_text(*MS_SIX))["scope"] == " ".join(MS_SIX)
    with pytest.raises(msgraph.ProviderError) as refused:
        msgraph.parse_account_record(MS_TASKS, record_text(*MS_FIVE))
    assert refused.value.code == 3 and "Tasks.ReadWrite" in str(refused.value) and "before To Do tasks" in str(refused.value) and "microsoft_auth.py authorize" in str(refused.value)
    for bad in (MS_FIVE[1:], MS_SIX[1:], MS_FIVE + ("Mail.Read",), MS_SIX + ("Mail.Read",), ("Mail.Read",)):
        for profile in (MS_OLD, MS_TASKS):
            with pytest.raises(msgraph.ProviderError):
                msgraph.parse_account_record(profile, record_text(*bad))


def test_the_transition_flag_reads_either_record_whatever_the_profile_for_the_check_command():
    assert msgraph.parse_account_record(MS_TASKS, record_text(*MS_FIVE), transition=True)["scope"] == " ".join(MS_FIVE)
    with pytest.raises(msgraph.ProviderError):
        msgraph.parse_account_record(MS_TASKS, record_text(*MS_FIVE[1:]), transition=True)


def run_outlook_calendar_writer(fake, tmp_path, scope):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    os.chmod(state, 0o700)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "WRITER_", "INTEGRATION_", "MAILBOX_", "OPENHORA_"))}
    env.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "MICROSOFT_ACCOUNT_TOKEN": fake.record_json(scope=scope), **fake.env()})
    return subprocess.run([sys.executable, str(REPO / "providers" / "writer" / "outlook-calendar.py"), "--check"], env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("record_scope, asked_scope", [(MS_FIVE, MS_FIVE), (MS_SIX, MS_SIX)])
def test_a_refresh_names_what_the_record_holds_and_the_calendar_writer_works_with_either(tmp_path, record_scope, asked_scope):
    fake = fgc.FakeGraphCalendar()
    try:
        fake.scope_granted = granted(*record_scope)
        proc = run_outlook_calendar_writer(fake, tmp_path, " ".join(record_scope))
        assert proc.returncode == 0, proc.stderr
        form = fake.token_forms[-1]
        assert set(form["scope"].split()) == {PREFIX + n for n in asked_scope} | {"offline_access"}
    finally:
        fake.close()


def test_the_calendar_writer_refuses_a_record_of_the_six_whose_refresh_comes_back_with_a_stranger(tmp_path):
    fake = fgc.FakeGraphCalendar()
    try:
        fake.scope_granted = granted(*MS_SIX, extra=" " + PREFIX + "Mail.Read")
        proc = run_outlook_calendar_writer(fake, tmp_path, " ".join(MS_SIX))
        assert proc.returncode == 3 and "microsoft_auth.py authorize" in proc.stderr
    finally:
        fake.close()


def test_the_authorization_profile_is_the_six():
    auth = load(REPO / "providers" / "accounts" / "microsoft_auth.py", "microsoft_auth_for_the_transition_tests")
    assert auth.PROFILE.scopes == MS_SIX and auth.PROFILE.accepted == (MS_SIX,)
    assert auth.PROFILE.refresh_scope == " ".join(PREFIX + n for n in MS_SIX) + " offline_access"


def test_the_tasks_providers_declare_the_profile_and_the_flag_that_need_the_new_set():
    reader = load(REPO / "providers" / "tasks" / "microsoft.py", "tasks_microsoft_for_the_transition_tests")
    writer = load(REPO / "providers" / "writer" / "microsoft-todo.py", "writer_todo_for_the_transition_tests")
    assert reader.PROFILE.scopes == MS_SIX and writer.PROFILE.scopes == MS_SIX
    source = (REPO / "providers" / "tasks" / "google.py").read_text(encoding="utf-8") + (REPO / "providers" / "writer" / "google-tasks.py").read_text(encoding="utf-8")
    assert source.count("tasks=True") == 2, "both Google tasks providers refresh with the tasks flag"
    for path in sorted((REPO / "providers").glob("*/*.py")):
        if path.parent.name in ("tasks",) or path.name in ("google-tasks.py", "microsoft-todo.py"):
            continue
        text = path.read_text(encoding="utf-8")
        assert "tasks=True" not in text or path.parent.name == "accounts", f"{path} asks for the tasks set but is no tasks provider"


def test_vacuity_a_check_that_accepted_any_subset_of_the_five_would_fail_the_exactness_tests():
    """The oracle: the planted rule (a token is accepted when it holds the four, whatever else) accepts a stranger, which the tests above refuse."""
    def planted(granted_words, tasks):
        return set(FOUR) <= google.scope_words(granted_words)
    assert planted(" ".join(FOUR) + " https://mail.google.com/", False) is True and accepted(" ".join(FOUR) + " https://mail.google.com/", tasks=False) is not None
    assert planted(" ".join(FOUR), True) is True and accepted(" ".join(FOUR), tasks=True) is not None


# --- what the registry tells the person (providers/secrets/resolver.py, `--list`; contracts/secrets.md) --------------------------------------------


def test_the_registry_text_of_the_two_account_tokens_names_the_tasks_scope_and_says_plainly_that_it_can_change_and_delete_tasks():
    resolver = load(REPO / "providers" / "secrets" / "resolver.py", "resolver_for_the_registry_text_tests")      # reads the text; no secret is looked up
    google_entry, microsoft_entry = resolver.REGISTRY["GOOGLE_ACCOUNT_TOKEN"], resolver.REGISTRY["MICROSOFT_ACCOUNT_TOKEN"]
    assert TASKS in google_entry.permission and "exactly those five" in google_entry.permission and "exactly those four" not in google_entry.permission
    assert "delete tasks at the service" in google_entry.permission and "never delete" in google_entry.permission and "Tasks readers" in google_entry.purpose
    assert "Tasks.ReadWrite" in microsoft_entry.permission and "delete the person's tasks in Microsoft To Do" in microsoft_entry.permission and "never delete" in microsoft_entry.permission
    assert "Microsoft To Do" in microsoft_entry.purpose
    for entry, scripts in ((google_entry, ("providers/tasks/google.py", "providers/writer/google-tasks.py")), (microsoft_entry, ("providers/tasks/microsoft.py", "providers/writer/microsoft-todo.py"))):
        for script in scripts:
            assert script in entry.readers and (REPO / script).is_file(), script
    table = (REPO / "contracts" / "secrets.md").read_text(encoding="utf-8")
    assert "exactly those five" in table and "delete the person's tasks in Microsoft To Do" in table and "exactly those four" not in table


def test_vacuity_the_old_registry_wording_would_fail_the_text_test():
    """The oracle: the wording before CB-4 says four scopes and lists no tasks script, which the assertions above refuse."""
    old = "OAuth scopes ... exactly those four (providers/accounts/google_auth.py)"
    assert "exactly those five" not in old and "exactly those four" in old
