"""Tests of the Google calendar writer (providers/writer/google-calendar.py; package W1; limits L55 to L59 as they apply to a writer). Against the stand-in
service (fake_gcal_write.py) on 127.0.0.1: no Google host is reached and no real credential exists. Every write path records each request (method, path, query,
body) and the tests assert the exact list: one POST to create, one PATCH with `If-Match` and only the changed parts, one DELETE with `If-Match`, `sendUpdates=none`
on each, no attendee anywhere. A dry run reads no credential and opens no connection. A moved version is refused (exit 1, `changed:`) with nothing changed; a lost
answer is exit 4 and the same key finds what landed (`replayed`); a key that is done is not sent again. The account record is required, with the platform's whole
set of scopes. The request function refuses any method or path outside ALLOWED before it opens a connection.

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_google_calendar.py
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
import fake_gcal_write as fgw  # noqa: E402

WRITER = REPO / "providers" / "writer" / "google-calendar.py"
KEY = "cal-0123456789abcdef0123456789abcdef"
START, END = "2026-10-19T13:00:00-03:00", "2026-10-19T14:00:00-03:00"
EVENTS = fgw.EVENTS_PREFIX
CREATE_SPEC = {"title": "Haircut", "all_day": False, "start_at": START, "end_at": END, "location": "Main Street", "reminder_minutes": 30, "notes": "Bring cash"}


@pytest.fixture
def fake():
    f = fgw.FakeGoogleCalendar()
    yield f
    f.close()


@pytest.fixture
def state(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    os.chmod(folder, 0o700)
    return folder


def env_of(fake, tmp_path, state, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "GOOGLE_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env()})
    kept.update(extra)
    return kept


def spec_file(tmp_path, spec, name="spec.json"):
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    os.chmod(path, 0o600)
    return str(path)


def run(fake, tmp_path, state, *args, record=None, env=None):
    proc = subprocess.run([sys.executable, str(WRITER), *args], env=env or env_of(fake, tmp_path, state, record), capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially (limit L59)
        for secret in fgw.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def calls(fake):
    """Every request the writer sent after the token POST, as (method, path, query, body)."""
    return [(r["method"], r["path"], r["query"], r["body"]) for r in fake.requests if r["path"] != "/token"]


def insert_args(tmp_path, key=KEY, spec=None, mode="--confirmed"):
    return ["event-insert", "--calendar", fgw.CALENDAR, "--spec-file", spec_file(tmp_path, spec or CREATE_SPEC), "--idempotency-key", key, mode]


def a_event(fake, **more):
    return fake.add_event("evabc12345", "Dentist", {"dateTime": START}, {"dateTime": END}, **more)


# --- a create ---------------------------------------------------------------------------------------------------------------------------------------


def test_a_create_is_exactly_one_post_with_the_events_fields_and_send_updates_none(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    assert done["done"] is True and done["replayed"] is False and done["event_id"] == "ev0001" and done["etag"]
    assert [r["method"] for r in fake.requests] == ["POST", "POST"]            # the token, then the event
    [(method, path, query, body)] = calls(fake)
    assert (method, path) == ("POST", EVENTS)
    assert query == {"sendUpdates": "none", "fields": "id,etag,status"}
    assert body == {"summary": "Haircut", "start": {"dateTime": START}, "end": {"dateTime": END}, "location": "Main Street", "description": "Bring cash",
                    "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
                    "extendedProperties": {"private": {"openhora_key": KEY}}}
    assert "attendees" not in body and fake.unexpected() == []
    assert all(r["bearer"] for r in fake.requests if r["path"] != "/token")
    assert fake.events["ev0001"]["summary"] == "Haircut"


def test_an_all_day_create_sends_dates_and_a_create_without_optional_parts_sends_none_of_them(fake, tmp_path, state):
    spec = {"title": "Trip", "all_day": True, "start_at": "2026-10-20", "end_at": "2026-10-22", "location": "", "reminder_minutes": None, "notes": ""}
    out(run(fake, tmp_path, state, *insert_args(tmp_path, spec=spec)))
    [(_, _, _, body)] = calls(fake)
    assert body == {"summary": "Trip", "start": {"date": "2026-10-20"}, "end": {"date": "2026-10-22"}, "extendedProperties": {"private": {"openhora_key": KEY}}}


def test_the_dry_run_reads_no_credential_opens_no_connection_and_prints_the_request_the_confirmed_run_sends(fake, tmp_path, state):
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})      # no token, no override: a dry run needs neither
    shown = out(run(fake, tmp_path, state, *insert_args(tmp_path, mode="--dry-run"), env=bare))
    assert fake.requests == [] and shown["dry_run"] is True and shown["ledger"] == "absent"
    would = shown["would"]
    assert would["method"] == "POST" and would["path"] == EVENTS and would["query"]["sendUpdates"] == "none" and would["headers"] == {}
    digest = shown["would_sha256"]
    assert len(digest) == 64
    out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    [(method, path, query, body)] = calls(fake)
    assert {"method": method, "path": path, "query": query, "headers": {}, "body": body} == would


def test_a_done_key_is_not_sent_again_and_the_replay_says_so(fake, tmp_path, state):
    first = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    assert again["replayed"] is True and again["event_id"] == first["event_id"]
    assert [r["path"] for r in fake.requests] == [] and len(fake.events) == 1       # not even the token was asked for
    other = out(run(fake, tmp_path, state, *insert_args(tmp_path, mode="--dry-run")))
    assert other["ledger"] == "done"


def test_a_key_used_for_another_request_is_a_usage_error(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    proc = run(fake, tmp_path, state, *insert_args(tmp_path, spec={**CREATE_SPEC, "title": "Something else"}))
    assert proc.returncode == 2 and "another request" in proc.stderr


def test_a_lost_answer_is_unknown_and_the_same_key_finds_the_event_by_its_private_property(fake, tmp_path, state):
    fake.lose_answer_once = True
    lost = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert lost.returncode == 4 and "may or may not have landed" in lost.stderr
    assert len(fake.events) == 1                      # it landed
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    assert again["replayed"] is True and again["event_id"] == "ev0001" and len(fake.events) == 1
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", EVENTS)]      # it looked, and sent nothing
    assert calls(fake)[0][2]["privateExtendedProperty"] == f"openhora_key={KEY}"
    assert [r["method"] for r in fake.requests if r["path"] != "/token"] == ["GET"]


def test_a_lost_answer_that_did_not_land_is_sent_again_after_the_lookup_finds_nothing(fake, tmp_path, state):
    fake.redirect_next = True              # the service answered a redirect: the outcome is not known, and nothing followed it
    lost = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert lost.returncode == 4 and "redirect" in lost.stderr
    assert [m for m, _, _, _ in calls(fake)] == ["POST"] and fake.events == {}
    fake.requests.clear()
    done = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    assert done["replayed"] is False and [(m, p) for m, p, _, _ in calls(fake)] == [("GET", EVENTS), ("POST", EVENTS)] and len(fake.events) == 1


# --- a change -----------------------------------------------------------------------------------------------------------------------------------------


def patch_args(tmp_path, spec, etag, key=KEY, mode="--confirmed", event="evabc12345"):
    return ["event-patch", "--calendar", fgw.CALENDAR, "--event", event, "--base-etag", etag, "--spec-file", spec_file(tmp_path, spec),
            "--idempotency-key", key, mode]


def test_a_change_is_exactly_one_patch_with_if_match_and_only_the_changed_parts(fake, tmp_path, state):
    base = a_event(fake)["etag"]
    out(run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Dentist (moved)"}, base)))
    [(method, path, query, body)] = calls(fake)
    assert (method, path) == ("PATCH", f"{EVENTS}/evabc12345") and query == {"sendUpdates": "none", "fields": "id,etag,status"}
    assert body == {"summary": "Dentist (moved)", "extendedProperties": {"private": {"openhora_key": KEY}}}
    assert fake.requests[-1]["if_match"] == base and fake.events["evabc12345"]["summary"] == "Dentist (moved)"
    assert fake.unexpected() == []


def test_a_change_of_the_time_sends_start_and_end_with_the_other_form_set_to_null(fake, tmp_path, state):
    event = a_event(fake)
    spec = {"all_day": True, "start_at": "2026-10-19", "end_at": "2026-10-20"}
    out(run(fake, tmp_path, state, *patch_args(tmp_path, spec, event["etag"])))
    [(_, _, _, body)] = calls(fake)
    assert body["start"] == {"date": "2026-10-19", "dateTime": None} and body["end"] == {"date": "2026-10-20", "dateTime": None}
    assert fake.events["evabc12345"]["start"] == {"date": "2026-10-19"}


def test_a_change_to_an_event_that_moved_is_refused_with_nothing_changed_and_the_key_is_free(fake, tmp_path, state):
    event = a_event(fake)
    old = event["etag"]
    event["etag"] = fake.next_etag()                       # somebody changed it meanwhile
    proc = run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Late"}, old))
    assert proc.returncode == 1 and proc.stderr.strip().startswith("error: changed:")
    assert fake.events["evabc12345"]["summary"] == "Dentist"
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("PATCH", f"{EVENTS}/evabc12345")]
    dry = out(run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Late"}, old, mode="--dry-run")))
    assert dry["ledger"] == "absent"


def test_a_lost_answer_of_a_change_is_found_by_the_key_on_the_event(fake, tmp_path, state):
    base = a_event(fake)["etag"]
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Once"}, base)).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Once"}, base)))
    assert again["replayed"] is True and [(m, p) for m, p, _, _ in calls(fake)] == [("GET", f"{EVENTS}/evabc12345")]
    assert fake.events["evabc12345"]["summary"] == "Once"


# --- a removal ----------------------------------------------------------------------------------------------------------------------------------------


def delete_args(etag, key=KEY, mode="--confirmed", event="evabc12345"):
    return ["event-delete", "--calendar", fgw.CALENDAR, "--event", event, "--base-etag", etag, "--idempotency-key", key, mode]


def test_a_removal_is_exactly_one_delete_with_if_match_and_send_updates_none(fake, tmp_path, state):
    event = a_event(fake)
    done = out(run(fake, tmp_path, state, *delete_args(event["etag"])))
    assert done["done"] is True and done["replayed"] is False
    [(method, path, query, body)] = calls(fake)
    assert (method, path, query, body) == ("DELETE", f"{EVENTS}/evabc12345", {"sendUpdates": "none"}, None)
    assert fake.requests[-1]["if_match"] == event["etag"] and "evabc12345" in fake.removed and fake.unexpected() == []


def test_a_removal_of_an_event_that_moved_is_refused_and_nothing_is_removed(fake, tmp_path, state):
    event = a_event(fake)
    old = event["etag"]
    event["etag"] = fake.next_etag()
    proc = run(fake, tmp_path, state, *delete_args(old))
    assert proc.returncode == 1 and "changed:" in proc.stderr and "evabc12345" in fake.events and fake.removed == {}


def test_a_lost_answer_of_a_removal_is_found_by_the_event_being_gone(fake, tmp_path, state):
    base = a_event(fake)["etag"]
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *delete_args(base)).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *delete_args(base)))
    assert again["replayed"] is True and [(m, p) for m, p, _, _ in calls(fake)] == [("GET", f"{EVENTS}/evabc12345")]


# --- reading an event ---------------------------------------------------------------------------------------------------------------------------------


def test_event_get_prints_what_the_runtime_needs_and_no_address(fake, tmp_path, state):
    a_event(fake, attendees=[{"email": "other@example.org", "self": False}, {"email": fgw.ACCOUNT, "self": True}], description="Bring the x-rays",
            reminders={"useDefault": False, "overrides": [{"method": "popup", "minutes": 15}]}, location="Main Street")
    proc = run(fake, tmp_path, state, "event-get", "--calendar", fgw.CALENDAR, "--event", "evabc12345")
    shown = out(proc)
    assert shown["found"] is True and "other@example.org" not in proc.stdout
    event = shown["event"]
    assert event["title"] == "Dentist" and event["start"] == START and event["end"] == END and event["all_day"] is False
    assert event["organizer_self"] is True and event["attendees_other"] == 1 and event["recurring"] is False
    assert event["notes"] == "Bring the x-rays" and event["reminder_minutes"] == 15 and event["location"] == "Main Street" and event["external_content"] is True
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", f"{EVENTS}/evabc12345")]


def test_event_get_says_recurring_for_a_series_and_for_an_occurrence_and_found_false_for_a_gone_event(fake, tmp_path, state):
    a_event(fake, recurrence=["RRULE:FREQ=WEEKLY"])
    assert out(run(fake, tmp_path, state, "event-get", "--calendar", fgw.CALENDAR, "--event", "evabc12345"))["event"]["recurring"] is True
    fake.add_event("evocc00001", "Standup", {"dateTime": START}, {"dateTime": END}, recurringEventId="evabc12345")
    assert out(run(fake, tmp_path, state, "event-get", "--calendar", fgw.CALENDAR, "--event", "evocc00001"))["event"]["recurring"] is True
    assert out(run(fake, tmp_path, state, "event-get", "--calendar", fgw.CALENDAR, "--event", "evnone0001")) == {"found": False, "reason": "gone"}
    del fake.events["evabc12345"]
    fake.removed["evabc12345"] = {"id": "evabc12345"}
    assert out(run(fake, tmp_path, state, "event-get", "--calendar", fgw.CALENDAR, "--event", "evabc12345"))["found"] is False


# --- the account token --------------------------------------------------------------------------------------------------------------------------------


def test_check_refreshes_checks_the_whole_set_and_reads_one_calendar_entry(fake, tmp_path, state):
    shown = out(run(fake, tmp_path, state, "--check"))
    assert shown["ok"] is True and sorted(shown["scope"]) == sorted(fgw.PLATFORM_SET) and shown["account"] == fgw.ACCOUNT
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", "/calendar/v3/users/me/calendarList")]


@pytest.mark.parametrize("scope", [" ".join(fgw.PLATFORM_SET[:2] + fgw.PLATFORM_SET[3:]), " ".join(fgw.PLATFORM_SET) + " https://mail.google.com/"],
                         ids=["lacks one", "carries another"])
def test_a_token_that_lacks_a_scope_of_the_set_or_carries_another_is_refused_before_any_call(fake, tmp_path, state, scope):
    fake.refresh_scope = scope
    proc = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert proc.returncode == 3 and "google_auth.py authorize" in proc.stderr
    assert calls(fake) == [] and fake.events == {}


def test_a_legacy_record_alone_is_not_enough_for_a_writer(fake, tmp_path, state):
    env = env_of(fake, tmp_path, state)
    del env["GOOGLE_ACCOUNT_TOKEN"]
    env["GOOGLE_CALENDAR_TOKEN"] = json.dumps({"refresh_token": fgw.REFRESH_TOKEN, "client_id": fgw.CLIENT_ID, "client_secret": fgw.CLIENT_SECRET,
                                               "scope": "x", "account": fgw.ACCOUNT, "obtained_at": "2026-10-17T09:00:00Z"})
    proc = run(fake, tmp_path, state, *insert_args(tmp_path), env=env)
    assert proc.returncode == 3 and fake.requests == []


def test_the_overrides_are_for_tests_set_together_and_loopback_only(fake, tmp_path, state):
    env = env_of(fake, tmp_path, state)
    del env["WRITER_CALENDAR_GOOGLE_TOKEN_URL"]
    assert run(fake, tmp_path, state, "--check", env=env).returncode == 2
    env = env_of(fake, tmp_path, state, WRITER_CALENDAR_GOOGLE_API_BASE="https://calendar.example.org")
    proc = run(fake, tmp_path, state, "--check", env=env)
    assert proc.returncode == 2 and "loopback" in proc.stderr and fake.requests == []


# --- the service says no ------------------------------------------------------------------------------------------------------------------------------


def test_a_429_is_reported_with_its_retry_after_nothing_is_retried_and_the_key_is_free(fake, tmp_path, state):
    fake.refuse_next = (429, "rateLimitExceeded")
    proc = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert proc.returncode == 1 and "Retry-After: 30" in proc.stderr and "Nothing was changed or retried" in proc.stderr
    assert [m for m, _, _, _ in calls(fake)] == ["POST"] and fake.events == {}
    assert out(run(fake, tmp_path, state, *insert_args(tmp_path, mode="--dry-run")))["ledger"] == "absent"


# --- the allow-list and the arguments -----------------------------------------------------------------------------------------------------------------


def load_writer():
    spec = importlib.util.spec_from_file_location("google_calendar_writer_under_test", WRITER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_request_function_refuses_any_method_or_path_outside_allowed_before_a_connection_is_opened(fake):
    writer = load_writer()
    sent = []
    writer.http = lambda *a: sent.append(a)
    for entry, path in ((("PUT", r"/calendar/v3/calendars/[^/]+/events/[^/]+"), "/calendar/v3/calendars/a/events/b"),
                        (("DELETE", r"/calendar/v3/calendars/[^/]+"), "/calendar/v3/calendars/a"),
                        (("DELETE", r"/calendar/v3/calendars/[^/]+/events/[^/]+"), "/calendar/v3/calendars/a/events/b/instances"),
                        (writer.REMOVE, "/calendar/v3/calendars/a"),
                        (writer.GET_EVENT, "/calendar/v3/users/me/settings"),
                        (writer.INSERT, "/calendar/v3/calendars/a/events/b"),
                        (writer.PATCH, "/calendar/v3/calendars/a/events"),
                        (writer.REMOVE, "/calendar/v3/calendars/a/events/b/c"),
                        (writer.INSERT, "/drive/v3/files")):
        with pytest.raises(writer.ProviderError) as why:
            writer.request(entry, fake.base, "token", path, {}, {})
        assert why.value.code == 2, (entry, path)
    assert sent == []


def test_the_allow_list_holds_exactly_one_delete_and_it_is_an_events_id(fake):
    writer = load_writer()
    deletes = [pair for pair in writer.ALLOWED if pair[0] == "DELETE"]
    assert deletes == [("DELETE", r"/calendar/v3/calendars/[^/]+/events/[^/]+")]
    assert sorted({m for m, _ in writer.ALLOWED}) == ["DELETE", "GET", "PATCH", "POST"] and writer.SERVES == "writer:calendar"


def test_a_spec_with_an_attendee_an_unknown_key_or_a_hidden_character_is_a_usage_error_and_nothing_is_sent(fake, tmp_path, state):
    for spec in ({**CREATE_SPEC, "attendees": ["x@example.org"]}, {**CREATE_SPEC, "title": "A\nB"}, {**CREATE_SPEC, "title": "A\u202eB"},
                 {**CREATE_SPEC, "reminder_minutes": 99999}, {**CREATE_SPEC, "end_at": START}, {k: v for k, v in CREATE_SPEC.items() if k != "title"}):
        proc = run(fake, tmp_path, state, *insert_args(tmp_path, spec=spec))
        assert proc.returncode == 2, spec
    for spec in ({}, {"attendees": []}, {"start_at": START}, {"reminder_minutes": None}):
        proc = run(fake, tmp_path, state, *patch_args(tmp_path, spec, '"1"'))
        assert proc.returncode == 2, spec
    assert fake.requests == []


def test_the_arguments_are_checked_and_a_flag_the_verb_does_not_read_is_refused(fake, tmp_path, state):
    spec = spec_file(tmp_path, CREATE_SPEC)
    for args in (["event-insert", "--calendar", fgw.CALENDAR, "--spec-file", spec, "--idempotency-key", KEY],                                  # neither mode
                 ["event-insert", "--calendar", fgw.CALENDAR, "--spec-file", spec, "--idempotency-key", KEY, "--dry-run", "--confirmed"],     # both
                 ["event-insert", "--calendar", "../x/y", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-insert", "--calendar", fgw.CALENDAR, "--event", "x1", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-patch", "--calendar", fgw.CALENDAR, "--event", "a/b", "--base-etag", '"1"', "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-delete", "--calendar", fgw.CALENDAR, "--event", "x1", "--idempotency-key", KEY, "--dry-run"],                   # no base
                 ["event-insert", "--calendar", fgw.CALENDAR, "--spec-file", spec, "--idempotency-key", "bad key", "--dry-run"],
                 ["event-get", "--calendar", fgw.CALENDAR, "--event", "x1", "--dry-run"], ["--check", "event-get"], []):
        assert run(fake, tmp_path, state, *args).returncode == 2, args
    assert run(fake, tmp_path, state, "event-drop", "--calendar", "x").returncode == 2           # argparse: not a verb of the writer
    assert fake.requests == []


def test_a_spec_that_is_a_link_or_not_a_file_is_refused(fake, tmp_path, state):
    real = spec_file(tmp_path, CREATE_SPEC)
    link = tmp_path / "link.json"
    link.symlink_to(real)
    for path in (str(link), str(tmp_path / "missing.json"), str(tmp_path)):
        proc = run(fake, tmp_path, state, "event-insert", "--calendar", fgw.CALENDAR, "--spec-file", path, "--idempotency-key", KEY, "--dry-run")
        assert proc.returncode == 2, path


def test_the_ledger_folder_is_private(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    folder = state / "writer-google-calendar"
    assert oct(folder.stat().st_mode & 0o777) == "0o700"
    assert oct((folder / "ledger.json").stat().st_mode & 0o777) == "0o600"
    ledger = json.loads((folder / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["keys"][KEY]["status"] == "done" and "Haircut" not in json.dumps(ledger)       # the ledger holds no words of the person's
