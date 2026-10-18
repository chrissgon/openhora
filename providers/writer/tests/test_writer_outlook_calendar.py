"""Tests of the Outlook calendar writer (providers/writer/outlook-calendar.py; package W1; limits L55 to L59 as they apply to a writer). Against the stand-in service
(fake_graph_calendar_write.py) on 127.0.0.1: no Microsoft host is reached and no real credential exists. Every write path records each request (method, path,
query, body) and the tests assert the exact list: one POST to create (times in UTC, no attendee); a change is a read of the event, a comparison of its changeKey and
one PATCH of the changed parts only; a moved changeKey is refused before the PATCH. The writer has NO verb that removes an event (Microsoft does not say where a
removed event goes, SPEC-SECRETARY-WRITES Q12): asking for one exits 2 and no request is sent. A dry run reads no credential and opens no connection; a lost answer is
exit 4 and the same key finds what landed (`replayed`); a key that is done is not sent again. The account record is required, with the platform's whole set. The
request function refuses any method or path outside ALLOWED before it opens a connection.

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_outlook_calendar.py
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
import fake_graph_calendar_write as fgc  # noqa: E402

WRITER = REPO / "providers" / "writer" / "outlook-calendar.py"
KEY = "cal-fedcba9876543210fedcba9876543210"
START, END = "2026-10-19T13:00:00-03:00", "2026-10-19T14:00:00-03:00"
CREATE_SPEC = {"title": "Haircut", "all_day": False, "start_at": START, "end_at": END, "location": "Main Street", "reminder_minutes": 30, "notes": "Bring cash"}
EVENTS = "/v1.0/me/calendar/events"
NAMED_EVENTS = f"/v1.0/me/calendars/{fgc.NAMED}/events"


@pytest.fixture
def fake():
    f = fgc.FakeGraphCalendar()
    yield f
    f.close()


@pytest.fixture
def state(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    os.chmod(folder, 0o700)
    return folder


def env_of(fake, tmp_path, state, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "MICROSOFT_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env()})
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
        for secret in fgc.SECRETS + ("fake-refresh-token-1-not-real",):
            assert secret not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def calls(fake):
    """Every request the writer sent to Graph, as (method, path, query, body)."""
    return [(r["method"], r["path"], r["query"], r["body"]) for r in fake.graph_requests()]


def create_args(tmp_path, key=KEY, spec=None, mode="--confirmed", calendar="default"):
    return ["event-create", "--calendar", calendar, "--spec-file", spec_file(tmp_path, spec or CREATE_SPEC), "--idempotency-key", key, mode]


def an_event(fake, **more):
    return fake.add_event("AAMkEvent9999=", "Dentist", "2026-10-19T16:00:00", "2026-10-19T17:00:00", **more)


def patch_args(tmp_path, spec, change_key, key=KEY, mode="--confirmed", event="AAMkEvent9999=", calendar="default"):
    return ["event-patch", "--calendar", calendar, "--event", event, "--base-etag", change_key, "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", key, mode]


# --- a create ---------------------------------------------------------------------------------------------------------------------------------------


def test_a_create_is_exactly_one_post_with_the_events_fields_in_utc_and_no_attendee(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *create_args(tmp_path)))
    assert done["done"] is True and done["replayed"] is False and done["event_id"] == "AAMkEvent0001=" and done["etag"]
    [(method, path, query, body)] = calls(fake)
    assert (method, path, query) == ("POST", EVENTS, {})
    assert body == {"subject": "Haircut", "isAllDay": False, "start": {"dateTime": "2026-10-19T16:00:00", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-10-19T17:00:00", "timeZone": "UTC"}, "location": {"displayName": "Main Street"},
                    "body": {"contentType": "text", "content": "Bring cash"}, "isReminderOn": True, "reminderMinutesBeforeStart": 30,
                    "singleValueExtendedProperties": [{"id": fgc.KEY_PROPERTY, "value": KEY}]}
    assert "attendees" not in body and fake.unexpected() == [] and len(fake.token_forms) == 1
    assert fake.events["AAMkEvent0001="]["subject"] == "Haircut"


def test_a_create_in_a_named_calendar_goes_to_that_calendars_events_and_an_all_day_event_starts_at_midnight(fake, tmp_path, state):
    spec = {"title": "Trip", "all_day": True, "start_at": "2026-10-20", "end_at": "2026-10-22", "location": "", "reminder_minutes": None, "notes": ""}
    out(run(fake, tmp_path, state, *create_args(tmp_path, spec=spec, calendar=fgc.NAMED)))
    [(method, path, _, body)] = calls(fake)
    assert (method, path) == ("POST", NAMED_EVENTS)
    assert body == {"subject": "Trip", "isAllDay": True, "start": {"dateTime": "2026-10-20T00:00:00", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-10-22T00:00:00", "timeZone": "UTC"}, "singleValueExtendedProperties": [{"id": fgc.KEY_PROPERTY, "value": KEY}]}


def test_the_dry_run_reads_no_credential_opens_no_connection_and_prints_the_request_the_confirmed_run_sends(fake, tmp_path, state):
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})
    shown = out(run(fake, tmp_path, state, *create_args(tmp_path, mode="--dry-run"), env=bare))
    assert fake.requests == [] and fake.token_forms == [] and shown["dry_run"] is True and shown["ledger"] == "absent"
    out(run(fake, tmp_path, state, *create_args(tmp_path)))
    [(method, path, query, body)] = calls(fake)
    assert {"method": method, "path": path[len("/v1.0"):], "query": query, "headers": {}, "body": body} == shown["would"]


def test_a_done_key_is_not_sent_again(fake, tmp_path, state):
    first = out(run(fake, tmp_path, state, *create_args(tmp_path)))
    fake.requests.clear()
    fake.token_forms.clear()
    again = out(run(fake, tmp_path, state, *create_args(tmp_path)))
    assert again["replayed"] is True and again["event_id"] == first["event_id"] and fake.requests == [] and fake.token_forms == [] and len(fake.events) == 1


def test_a_lost_answer_of_a_create_is_unknown_and_the_same_key_finds_the_event_by_its_private_property(fake, tmp_path, state):
    fake.lose_answer_once = True
    lost = run(fake, tmp_path, state, *create_args(tmp_path))
    assert lost.returncode == 4 and "may or may not have landed" in lost.stderr and len(fake.events) == 1
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *create_args(tmp_path)))
    assert again["replayed"] is True and again["event_id"] == "AAMkEvent0001=" and len(fake.events) == 1
    [(method, path, query, _)] = calls(fake)
    assert (method, path) == ("GET", EVENTS) and KEY in query["$filter"] and fgc.KEY_PROPERTY in query["$filter"]


def test_a_redirect_on_a_write_is_unknown_nothing_follows_it_and_the_key_finds_nothing_so_it_is_sent_again(fake, tmp_path, state):
    fake.redirect_next = True
    lost = run(fake, tmp_path, state, *create_args(tmp_path))
    assert lost.returncode == 4 and [m for m, _, _, _ in calls(fake)] == ["POST"] and fake.events == {}
    fake.requests.clear()
    done = out(run(fake, tmp_path, state, *create_args(tmp_path)))
    assert done["replayed"] is False and [m for m, _, _, _ in calls(fake)] == ["GET", "POST"] and len(fake.events) == 1


# --- a change -----------------------------------------------------------------------------------------------------------------------------------------


def test_a_change_reads_the_event_compares_its_change_key_and_sends_one_patch_of_the_changed_parts(fake, tmp_path, state):
    base = an_event(fake)["changeKey"]
    done = out(run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Dentist (moved)"}, base)))
    assert done["done"] is True and done["replayed"] is False and done["event_id"] == "AAMkEvent9999="
    got, patched = calls(fake)
    assert got[0] == "GET" and got[1] == f"{EVENTS}/AAMkEvent9999="
    assert patched == ("PATCH", f"{EVENTS}/AAMkEvent9999=", {}, {"subject": "Dentist (moved)", "singleValueExtendedProperties": [{"id": fgc.KEY_PROPERTY, "value": KEY}]})
    assert fake.graph_requests()[0]["prefer"] == 'outlook.timezone="UTC", outlook.body-content-type="text"'
    assert fake.events["AAMkEvent9999="]["subject"] == "Dentist (moved)" and fake.unexpected() == []


def test_a_change_of_the_time_sends_start_end_and_all_day_together(fake, tmp_path, state):
    base = an_event(fake)["changeKey"]
    spec = {"all_day": True, "start_at": "2026-10-19", "end_at": "2026-10-20"}
    out(run(fake, tmp_path, state, *patch_args(tmp_path, spec, base, calendar=fgc.NAMED)))
    _, (method, path, _, body) = calls(fake)
    assert (method, path) == ("PATCH", f"{NAMED_EVENTS}/AAMkEvent9999=")
    assert body["isAllDay"] is True and body["start"] == {"dateTime": "2026-10-19T00:00:00", "timeZone": "UTC"}
    assert body["end"] == {"dateTime": "2026-10-20T00:00:00", "timeZone": "UTC"}


def test_a_change_to_an_event_whose_change_key_moved_is_refused_before_the_patch_and_the_key_is_free(fake, tmp_path, state):
    event = an_event(fake)
    old = event["changeKey"]
    event["changeKey"] = fake.next_key()
    proc = run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Late"}, old))
    assert proc.returncode == 1 and proc.stderr.strip().startswith("error: changed:")
    assert [m for m, _, _, _ in calls(fake)] == ["GET"] and fake.events["AAMkEvent9999="]["subject"] == "Dentist"
    assert out(run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Late"}, old, mode="--dry-run")))["ledger"] == "absent"


def test_a_change_to_an_event_that_is_gone_is_refused(fake, tmp_path, state):
    proc = run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Late"}, "CQAAABYAAAB00000001", event="AAMkGone00001="))
    assert proc.returncode == 1 and "changed:" in proc.stderr and [m for m, _, _, _ in calls(fake)] == ["GET"]


def test_a_lost_answer_of_a_change_is_found_by_the_key_on_the_event(fake, tmp_path, state):
    base = an_event(fake)["changeKey"]
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Once"}, base)).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *patch_args(tmp_path, {"title": "Once"}, base)))
    assert again["replayed"] is True and [m for m, _, _, _ in calls(fake)] == ["GET"] and fake.events["AAMkEvent9999="]["subject"] == "Once"


# --- no removal ---------------------------------------------------------------------------------------------------------------------------------------


def test_the_writer_has_no_verb_that_removes_an_event_and_asking_for_one_sends_nothing(fake, tmp_path, state):
    event = an_event(fake)
    for verb in ("event-delete", "event-remove", "event-cancel"):
        proc = run(fake, tmp_path, state, verb, "--calendar", "default", "--event", "AAMkEvent9999=", "--base-etag", event["changeKey"], "--idempotency-key", KEY,
                   "--confirmed")
        assert proc.returncode == 2 and "removing an event from an Outlook calendar is not available yet" in proc.stderr, verb
    assert fake.requests == [] and fake.token_forms == [] and "AAMkEvent9999=" in fake.events


def test_the_allow_list_holds_no_removal_and_the_request_function_refuses_one(fake):
    writer = load_writer()
    assert sorted({m for m, _ in writer.ALLOWED}) == ["GET", "PATCH", "POST"] and writer.SERVES == "writer:calendar"
    sent = []
    writer.msgraph.http = lambda *a, **k: sent.append(a)
    session = writer.Session(writer.msgraph.GraphClient(writer.PROFILE, fake.base, "token", True), {})
    removal = "DEL" + "ETE"      # built here so that no scan of this file's text mistakes the test for a request
    for entry, path in (((removal, r"/me/calendar/events/[^/]+"), "/me/calendar/events/x"), (("PUT", r"/me/calendar/events/[^/]+"), "/me/calendar/events/x"),
                        (writer.PATCH_DEFAULT, "/me/calendar/events"), (writer.POST_DEFAULT, "/me/calendar/events/x"), (writer.GET_DEFAULT, "/me/messages"),
                        (writer.PATCH_IN, "/me/calendars/a/events"), (writer.POST_IN, "/me/events"), (writer.PATCH_DEFAULT, "/me/calendar/events/x/y")):
        with pytest.raises(writer.WriterError) as why:
            writer.request(entry, session, path, {}, {})
        assert why.value.code == 2, (entry, path)
    assert sent == []


# --- reading an event ---------------------------------------------------------------------------------------------------------------------------------


def test_event_get_prints_what_the_runtime_needs_and_no_address(fake, tmp_path, state):
    an_event(fake, attendees=[{"emailAddress": {"address": "other@example.org"}}, {"emailAddress": {"address": fgc.ADDRESS}}], isReminderOn=True,
             reminderMinutesBeforeStart=15, body={"contentType": "text", "content": "Bring the x-rays"}, location={"displayName": "Main Street"})
    proc = run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkEvent9999=")
    shown = out(proc)
    assert shown["found"] is True and "other@example.org" not in proc.stdout
    event = shown["event"]
    assert event["title"] == "Dentist" and event["start"] == "2026-10-19T16:00:00Z" and event["end"] == "2026-10-19T17:00:00Z" and event["all_day"] is False
    assert event["organizer_self"] is True and event["attendees_other"] == 1 and event["recurring"] is False and event["etag"]
    assert event["notes"] == "Bring the x-rays" and event["reminder_minutes"] == 15 and event["location"] == "Main Street" and event["external_content"] is True
    [(method, path, query, _)] = calls(fake)
    assert (method, path) == ("GET", f"{EVENTS}/AAMkEvent9999=") and "$select" in query


def test_a_server_error_on_a_read_is_a_refusal_not_an_unknown_outcome_because_a_read_changes_nothing(fake, tmp_path, state):
    an_event(fake)
    fake.fail_get_next = 500
    proc = run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkEvent9999=")
    assert proc.returncode == 1 and "Graph returned 500" in proc.stderr and "may or may not have landed" not in proc.stderr


def test_a_503_on_a_write_is_unknown_and_the_key_stays_pending(fake, tmp_path, state):
    fake.refuse_next = (503, "serviceNotAvailable")
    proc = run(fake, tmp_path, state, *create_args(tmp_path))
    assert proc.returncode == 4 and "may or may not have landed" in proc.stderr
    assert out(run(fake, tmp_path, state, *create_args(tmp_path, mode="--dry-run")))["ledger"] == "pending"


def test_an_all_day_event_east_of_utc_is_read_in_its_own_zone_so_its_date_is_not_a_day_off(fake, tmp_path, state):
    own = {"start": {"dateTime": "2026-10-19T00:00:00.0000000", "timeZone": "Tokyo Standard Time"},
           "end": {"dateTime": "2026-10-20T00:00:00.0000000", "timeZone": "Tokyo Standard Time"}}
    an_event(fake, isAllDay=True, start={"dateTime": "2026-10-18T15:00:00.0000000", "timeZone": "UTC"},      # asked in UTC, Graph shifts the midnight of +09:00
             end={"dateTime": "2026-10-19T15:00:00.0000000", "timeZone": "UTC"}, _own=own)
    event = out(run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkEvent9999="))["event"]
    assert event["all_day"] is True and event["start"] == "2026-10-19" and event["end"] == "2026-10-20"
    assert [r["prefer"] for r in fake.graph_requests()] == ['outlook.timezone="UTC", outlook.body-content-type="text"', 'outlook.body-content-type="text"']
    fake.requests.clear()
    timed = fake.add_event("AAMkTimed00001=", "Dentist", "2026-10-19T16:00:00", "2026-10-19T17:00:00")
    assert timed and out(run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkTimed00001="))["event"]["start"] == "2026-10-19T16:00:00Z"
    assert len(fake.graph_requests()) == 1, "a timed event is read once"


def test_an_id_a_key_or_a_calendar_that_starts_with_a_hyphen_is_a_usage_error(fake, tmp_path, state):
    spec = spec_file(tmp_path, CREATE_SPEC)
    for args in (["event-create", "--calendar", "-x", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-create", "--calendar", "default", "--spec-file", spec, "--idempotency-key", "-k", "--dry-run"],
                 ["event-patch", "--calendar", "default", "--event", "-e", "--base-etag", "CQ1", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-patch", "--calendar", "default", "--event", "e1", "--base-etag", "-1", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"]):
        assert run(fake, tmp_path, state, *args).returncode == 2, args


@pytest.mark.parametrize("more", [{"type": "seriesMaster"}, {"type": "occurrence"}, {"type": "exception"}, {"seriesMasterId": "AAMkSeries0001="}], ids=str)
def test_event_get_says_recurring_for_a_series_an_occurrence_and_an_exception(fake, tmp_path, state, more):
    an_event(fake, **more)
    assert out(run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkEvent9999="))["event"]["recurring"] is True


def test_event_get_of_an_all_day_event_prints_days_and_of_a_gone_or_cancelled_event_found_false(fake, tmp_path, state):
    an_event(fake, isAllDay=True, start={"dateTime": "2026-10-19T00:00:00.0000000", "timeZone": "UTC"}, end={"dateTime": "2026-10-20T00:00:00.0000000", "timeZone": "UTC"})
    event = out(run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkEvent9999="))["event"]
    assert event["all_day"] is True and event["start"] == "2026-10-19" and event["end"] == "2026-10-20"
    assert out(run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkNone00001=")) == {"found": False, "reason": "gone"}
    fake.events["AAMkEvent9999="]["isCancelled"] = True
    assert out(run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkEvent9999="))["found"] is False


def test_event_get_of_an_event_in_another_time_zone_is_refused_not_guessed(fake, tmp_path, state):
    an_event(fake, start={"dateTime": "2026-10-19T13:00:00.0000000", "timeZone": "E. South America Standard Time"})
    proc = run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", "AAMkEvent9999=")
    assert proc.returncode == 1 and "time zone" in proc.stderr


# --- the account token --------------------------------------------------------------------------------------------------------------------------------


def test_check_refreshes_checks_the_whole_set_and_reads_one_calendar_entry(fake, tmp_path, state):
    shown = out(run(fake, tmp_path, state, "--check"))
    assert shown["ok"] is True and shown["record"] == "account" and shown["scope"] == " ".join(fgc.PLATFORM) and shown["tenant"] == "common"
    [(method, path, query, _)] = calls(fake)
    assert (method, path, query) == ("GET", "/v1.0/me/calendars", {"$select": "id", "$top": "1"})


@pytest.mark.parametrize("granted", [" ".join(fgc.PREFIX + n for n in fgc.PLATFORM[:2] + fgc.PLATFORM[3:]) + " offline_access",
                                     fgc.GRANTED + " " + fgc.PREFIX + "Calendars.ReadBasic"], ids=["lacks one", "carries another"])
def test_a_token_that_lacks_a_permission_of_the_set_or_carries_another_is_refused_before_any_call(fake, tmp_path, state, granted):
    fake.scope_granted = granted
    proc = run(fake, tmp_path, state, *create_args(tmp_path))
    assert proc.returncode == 3 and "microsoft_auth.py authorize" in proc.stderr
    assert fake.graph_requests() == [] and fake.events == {}


def test_a_legacy_record_alone_is_not_enough_for_a_writer(fake, tmp_path, state):
    env = env_of(fake, tmp_path, state)
    del env["MICROSOFT_ACCOUNT_TOKEN"]
    env["OUTLOOK_CALENDAR_TOKEN"] = json.dumps({"refresh_token": fgc.REFRESH_TOKEN, "client_id": fgc.CLIENT_ID, "tenant": "common", "scope": "Calendars.ReadBasic",
                                                "obtained_at": "2026-10-17T08:00:00Z"})
    proc = run(fake, tmp_path, state, *create_args(tmp_path), env=env)
    assert proc.returncode == 3 and fake.requests == [] and fake.token_forms == []


def test_the_overrides_are_for_tests_set_together_and_loopback_only(fake, tmp_path, state):
    env = env_of(fake, tmp_path, state)
    del env["WRITER_CALENDAR_OUTLOOK_TOKEN_URL"]
    assert run(fake, tmp_path, state, "--check", env=env).returncode == 2
    env = env_of(fake, tmp_path, state, WRITER_CALENDAR_OUTLOOK_API_BASE="https://graph.example.org/v1.0")
    proc = run(fake, tmp_path, state, "--check", env=env)
    assert proc.returncode == 2 and "loopback" in proc.stderr and fake.requests == []


# --- Graph says no ------------------------------------------------------------------------------------------------------------------------------------


def test_a_429_is_reported_with_its_retry_after_nothing_is_retried_and_the_key_is_free(fake, tmp_path, state):
    fake.refuse_next = (429, "ApplicationThrottled")
    proc = run(fake, tmp_path, state, *create_args(tmp_path))
    assert proc.returncode == 1 and "30 seconds" in proc.stderr
    assert [m for m, _, _, _ in calls(fake)] == ["POST"] and fake.events == {}
    assert out(run(fake, tmp_path, state, *create_args(tmp_path, mode="--dry-run")))["ledger"] == "absent"


def test_a_server_error_on_a_write_is_unknown_and_the_key_stays_pending(fake, tmp_path, state):
    fake.refuse_next = (500, "generalException")
    proc = run(fake, tmp_path, state, *create_args(tmp_path))
    assert proc.returncode == 4 and "may or may not have landed" in proc.stderr
    assert out(run(fake, tmp_path, state, *create_args(tmp_path, mode="--dry-run")))["ledger"] == "pending"


# --- the arguments ------------------------------------------------------------------------------------------------------------------------------------


def load_writer():
    spec = importlib.util.spec_from_file_location("outlook_calendar_writer_under_test", WRITER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_spec_with_an_attendee_an_unknown_key_or_a_hidden_character_is_a_usage_error_and_nothing_is_sent(fake, tmp_path, state):
    for spec in ({**CREATE_SPEC, "attendees": ["x@example.org"]}, {**CREATE_SPEC, "title": "A\nB"}, {**CREATE_SPEC, "title": "A\u202eB"},
                 {**CREATE_SPEC, "reminder_minutes": 99999}, {**CREATE_SPEC, "end_at": START}, {k: v for k, v in CREATE_SPEC.items() if k != "title"}):
        assert run(fake, tmp_path, state, *create_args(tmp_path, spec=spec)).returncode == 2, spec
    for spec in ({}, {"attendees": []}, {"start_at": START}, {"reminder_minutes": None}):
        assert run(fake, tmp_path, state, *patch_args(tmp_path, spec, "CQAAABYAAAB00000001")).returncode == 2, spec
    assert fake.requests == [] and fake.token_forms == []


def test_the_arguments_are_checked_and_a_flag_the_verb_does_not_read_is_refused(fake, tmp_path, state):
    spec = spec_file(tmp_path, CREATE_SPEC)
    for args in (["event-create", "--calendar", "default", "--spec-file", spec, "--idempotency-key", KEY],
                 ["event-create", "--calendar", "default", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run", "--confirmed"],
                 ["event-create", "--calendar", "../x", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-create", "--calendar", "default", "--event", "x1", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-patch", "--calendar", "default", "--event", "a/b", "--base-etag", "CQ1", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-patch", "--calendar", "default", "--event", "x1", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run"],
                 ["event-create", "--calendar", "default", "--spec-file", spec, "--idempotency-key", "bad key", "--dry-run"],
                 ["event-get", "--calendar", "default", "--event", "x1", "--confirmed"], ["--check", "event-get"], []):
        assert run(fake, tmp_path, state, *args).returncode == 2, args
    assert fake.requests == [] and fake.token_forms == []


def test_the_ledger_folder_is_private_and_holds_no_words_of_the_persons(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *create_args(tmp_path)))
    folder = state / "writer-outlook-calendar"
    assert oct(folder.stat().st_mode & 0o777) == "0o700" and oct((folder / "ledger.json").stat().st_mode & 0o777) == "0o600"
    ledger = json.loads((folder / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["keys"][KEY]["status"] == "done" and "Haircut" not in json.dumps(ledger)
