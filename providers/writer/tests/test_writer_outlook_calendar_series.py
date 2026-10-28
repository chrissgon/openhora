"""Tests of the series verbs of the Outlook calendar writer (providers/writer/outlook-calendar.py; package CB-6; limits L57 and L58). Against the stand-in service
(fake_graph_calendar_write.py) on 127.0.0.1: no Microsoft host is reached and no real credential exists. A series is a create spec with `recurrence` and `time_zone`
together (daily, or weekly on one weekday, no end), written in the zone it is expanded in; `event-get` reports `series_id` and `series_rule`; `event-cancel-series` is a
read of the master and one POST of Graph's `cancel` action on its id; `event-instances` reads the occurrences of a series in a window of at most two days;
`event-cancel-occurrence` is the same POST on one occurrence's id after a read of it and of its series. The `cancel` body is an empty object and there is no DELETE
anywhere, and no fallback to one. Every test asserts the exact list of requests the fake recorded. Every date is made up (2099 for a time that has not come, 2020 for
one that has).

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_outlook_calendar_series.py
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
KEY = "ser-fedcba9876543210fedcba9876543210"
ZONE = "America/Sao_Paulo"
START, END = "2099-03-02T07:00:00-03:00", "2099-03-02T08:00:00-03:00"      # a Monday, 10:00Z
EVENTS = "/v1.0/me/calendar/events"
MASTER = "AAMkSeries0001="
OCC = [f"AAMkSeries0001Occ{n}=" for n in range(3)]
SERIES_SPEC = {"title": "Gym", "all_day": False, "start_at": START, "end_at": END, "location": "", "reminder_minutes": None, "notes": "",
               "recurrence": {"freq": "weekly", "byday": "MO"}, "time_zone": ZONE}
DAILY_SPEC = {**SERIES_SPEC, "recurrence": {"freq": "daily"}}
WEEKLY = {"type": "weekly", "interval": 1, "daysOfWeek": ["monday"], "firstDayOfWeek": "sunday"}
FIRST, LAST = "2099-03-02T10:00:00", "2099-03-02T11:00:00"
FUTURE_START = "2099-03-09T10:00:00Z"      # the second occurrence of the weekly series, as the writer reads it (UTC)


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


def env_of(fake, tmp_path, state, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "MICROSOFT_ACCOUNT_TOKEN": fake.record_json(), **fake.env()})
    kept.update(extra)
    return kept


def spec_file(tmp_path, spec, name="spec.json"):
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    os.chmod(path, 0o600)
    return str(path)


def run(fake, tmp_path, state, *args):
    proc = subprocess.run([sys.executable, str(WRITER), *args], env=env_of(fake, tmp_path, state), capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):
        for secret in fgc.SECRETS + ("fake-refresh-token-1-not-real",):
            assert secret not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def calls(fake):
    return [(r["method"], r["path"], r["query"], r["body"]) for r in fake.graph_requests()]


def sent(fake):
    return [(m, p) for m, p, _, _ in calls(fake)]


def create_args(tmp_path, spec, mode="--confirmed", key=KEY, calendar="default"):
    return ["event-create", "--calendar", calendar, "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", key, mode]


def a_series(fake, pattern=None, step=7, **more):
    return fake.add_series(MASTER, "Gym", FIRST, LAST, pattern=pattern or WEEKLY, step=step, **more)


def series_args(change_key, event=MASTER, mode="--confirmed", key=KEY, calendar="default"):
    return ["event-cancel-series", "--calendar", calendar, "--event", event, "--base-etag", change_key, "--idempotency-key", key, mode]


def occurrence_args(change_key, event=OCC[1], series=MASTER, start=FUTURE_START, mode="--confirmed", key=KEY, calendar="default"):
    return ["event-cancel-occurrence", "--calendar", calendar, "--event", event, "--series", series, "--expect-start", start, "--base-etag", change_key,
            "--idempotency-key", key, mode]


def instances_args(low, high, series=MASTER, calendar="default"):
    return ["event-instances", "--calendar", calendar, "--series", series, "--from", low, "--to", high]


def refused(fake, tmp_path, state, args, words):
    proc = run(fake, tmp_path, state, *args)
    assert proc.returncode == 1 and words in proc.stderr, (proc.returncode, proc.stderr)
    assert [m for m, _ in sent(fake) if m != "GET"] == [] and fake.removed == {} and fake.cancelled == []      # nothing was sent but reads
    return proc


# --- the spec of a series --------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("spec", [
    {k: v for k, v in SERIES_SPEC.items() if k != "time_zone"},
    {k: v for k, v in SERIES_SPEC.items() if k != "recurrence"},
    {**SERIES_SPEC, "recurrence": {"freq": "monthly"}},
    {**SERIES_SPEC, "recurrence": {"freq": "daily", "interval": 2}},
    {**SERIES_SPEC, "recurrence": {"freq": "daily", "count": 3}},
    {**SERIES_SPEC, "recurrence": {"freq": "weekly"}},
    {**SERIES_SPEC, "recurrence": {"freq": "weekly", "byday": ["MO", "TU"]}},
    {**SERIES_SPEC, "recurrence": {"freq": "weekly", "byday": "MO", "until": "2099-12-31"}},
    {**SERIES_SPEC, "recurrence": {"freq": "weekly", "byday": "WE"}},
    {**SERIES_SPEC, "recurrence": "daily"},
    {**SERIES_SPEC, "all_day": True, "start_at": "2099-03-02", "end_at": "2099-03-03"},
    {**SERIES_SPEC, "time_zone": "Nowhere/Land"},
    {**SERIES_SPEC, "time_zone": "UTC"},
    {**SERIES_SPEC, "time_zone": "../etc/passwd"},
], ids=lambda s: json.dumps(s, sort_keys=True)[:90])
def test_a_wrong_series_spec_is_a_usage_error_and_nothing_is_sent(fake, tmp_path, state, spec):
    for mode in ("--dry-run", "--confirmed"):
        assert run(fake, tmp_path, state, *create_args(tmp_path, spec, mode)).returncode == 2
    assert fake.requests == [] and fake.token_forms == []


def test_a_patch_never_carries_a_recurrence_or_a_zone(fake, tmp_path, state):
    for spec in ({"recurrence": {"freq": "daily"}}, {"time_zone": ZONE}, {"title": "Gym", "recurrence": {"freq": "daily"}, "time_zone": ZONE}):
        args = ["event-patch", "--calendar", "default", "--event", MASTER, "--base-etag", "CQAAAB", "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", KEY, "--dry-run"]
        assert run(fake, tmp_path, state, *args).returncode == 2, spec
    assert fake.requests == []


def test_a_weekly_series_dry_run_is_one_post_with_the_pattern_the_range_and_the_zone_and_no_other_part(fake, tmp_path, state):
    would = out(run(fake, tmp_path, state, *create_args(tmp_path, SERIES_SPEC, "--dry-run")))["would"]
    assert (would["method"], would["path"], would["query"]) == ("POST", "/me/calendar/events", {})
    body = would["body"]
    assert body["start"] == {"dateTime": "2099-03-02T07:00:00", "timeZone": ZONE} and body["end"] == {"dateTime": "2099-03-02T08:00:00", "timeZone": ZONE}
    assert body["recurrence"] == {"pattern": WEEKLY, "range": {"type": "noEnd", "startDate": "2099-03-02"}}
    assert set(body["recurrence"]["range"]) == {"type", "startDate"} and set(body["recurrence"]["pattern"]) == {"type", "interval", "daysOfWeek", "firstDayOfWeek"}
    assert "attendees" not in body and fake.requests == []


def test_a_daily_series_dry_run_has_the_daily_pattern_and_the_hash_covers_the_series(fake, tmp_path, state):
    daily = out(run(fake, tmp_path, state, *create_args(tmp_path, DAILY_SPEC, "--dry-run")))
    weekly = out(run(fake, tmp_path, state, *create_args(tmp_path, SERIES_SPEC, "--dry-run")))
    plain = out(run(fake, tmp_path, state, *create_args(tmp_path, {k: v for k, v in SERIES_SPEC.items() if k not in ("recurrence", "time_zone")}, "--dry-run")))
    assert daily["would"]["body"]["recurrence"] == {"pattern": {"type": "daily", "interval": 1}, "range": {"type": "noEnd", "startDate": "2099-03-02"}}
    assert len({daily["would_sha256"], weekly["would_sha256"], plain["would_sha256"]}) == 3
    assert "recurrence" not in plain["would"]["body"] and plain["would"]["body"]["start"]["timeZone"] == "UTC"      # a plain event is what it always was


def test_the_date_and_the_wall_time_of_a_series_are_those_of_the_zone_not_of_utc(fake, tmp_path, state):
    late = {**SERIES_SPEC, "start_at": "2099-03-02T02:30:00Z", "end_at": "2099-03-02T03:30:00Z", "recurrence": {"freq": "weekly", "byday": "SU"}}      # Sunday 23:30 in Sao Paulo
    body = out(run(fake, tmp_path, state, *create_args(tmp_path, late, "--dry-run")))["would"]["body"]
    assert body["start"] == {"dateTime": "2099-03-01T23:30:00", "timeZone": ZONE} and body["recurrence"]["range"]["startDate"] == "2099-03-01"
    assert body["recurrence"]["pattern"]["daysOfWeek"] == ["sunday"]
    summer = {**SERIES_SPEC, "start_at": "2099-07-06T07:00:00Z", "end_at": "2099-07-06T08:00:00Z", "time_zone": "Europe/Lisbon"}      # a Monday, one hour ahead of UTC
    body = out(run(fake, tmp_path, state, *create_args(tmp_path, summer, "--dry-run")))["would"]["body"]
    assert body["start"] == {"dateTime": "2099-07-06T08:00:00", "timeZone": "Europe/Lisbon"} and body["recurrence"]["range"]["startDate"] == "2099-07-06"


def test_a_series_whose_first_wall_time_is_ambiguous_in_the_zone_is_refused_not_written_in_utc(fake, tmp_path, state):
    spec = {**SERIES_SPEC, "start_at": "2026-10-25T00:30:00Z", "end_at": "2026-10-25T01:30:00Z", "time_zone": "Europe/Lisbon", "recurrence": {"freq": "weekly", "byday": "SU"}}
    for mode in ("--dry-run", "--confirmed"):
        proc = run(fake, tmp_path, state, *create_args(tmp_path, spec, mode))
        assert proc.returncode == 2 and "ambiguous" in proc.stderr
    assert fake.requests == []
    fine = {**spec, "start_at": "2026-10-25T02:00:00Z", "end_at": "2026-10-25T03:00:00Z"}      # vacuity: the hour after the repeated one is written
    assert out(run(fake, tmp_path, state, *create_args(tmp_path, fine, "--dry-run")))["would"]["body"]["start"]["timeZone"] == "Europe/Lisbon"


def test_a_time_zone_flag_beside_a_series_must_be_the_same_name(fake, tmp_path, state):
    same = out(run(fake, tmp_path, state, *create_args(tmp_path, SERIES_SPEC, "--dry-run"), "--time-zone", ZONE))
    none = out(run(fake, tmp_path, state, *create_args(tmp_path, SERIES_SPEC, "--dry-run")))
    assert same["would_sha256"] == none["would_sha256"]
    proc = run(fake, tmp_path, state, *create_args(tmp_path, SERIES_SPEC, "--dry-run"), "--time-zone", "Europe/Lisbon")
    assert proc.returncode == 2 and "--time-zone" in proc.stderr and fake.requests == []


def test_a_series_create_is_exactly_one_post_and_a_lost_answer_is_found_by_its_private_property(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *create_args(tmp_path, SERIES_SPEC)))
    assert done["done"] is True and sent(fake) == [("POST", EVENTS)] and fake.unexpected() == []
    assert fake.events[done["event_id"]]["type"] == "seriesMaster" and fake.events[done["event_id"]]["recurrence"]["pattern"] == WEEKLY
    fake.requests.clear()
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *create_args(tmp_path, DAILY_SPEC, key=KEY + "b")).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *create_args(tmp_path, DAILY_SPEC, key=KEY + "b")))
    assert again["replayed"] is True and [m for m, _ in sent(fake)] == ["GET"]


# --- event-get: the series ------------------------------------------------------------------------------------------------------------------------------


def got(fake, tmp_path, state, event):
    return out(run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", event))["event"]


def test_event_get_gives_the_same_series_id_for_the_master_an_occurrence_and_an_exception_and_the_rule_in_closed_words(fake, tmp_path, state):
    master, occurrences = a_series(fake)
    occurrences[2]["type"] = "exception"
    seen = [got(fake, tmp_path, state, i) for i in (MASTER, OCC[0], OCC[2])]
    assert [(e["series_id"], e["series_rule"], e["recurring"]) for e in seen] == [(MASTER, "weekly:MO", True)] * 3


def test_event_get_of_a_daily_series_says_daily_and_of_a_plain_event_says_null(fake, tmp_path, state):
    a_series(fake, pattern={"type": "daily", "interval": 1}, step=1)
    fake.add_event("AAMkPlain0001=", "Dentist", "2099-03-02T10:00:00", "2099-03-02T11:00:00")
    assert got(fake, tmp_path, state, MASTER)["series_rule"] == "daily" and got(fake, tmp_path, state, OCC[1])["series_rule"] == "daily"
    plain = got(fake, tmp_path, state, "AAMkPlain0001=")
    assert plain["series_id"] is None and plain["series_rule"] is None and plain["recurring"] is False


@pytest.mark.parametrize("pattern, span", [
    ({"type": "daily", "interval": 2}, {"type": "noEnd"}), ({"type": "daily", "interval": 1}, {"type": "endDate", "endDate": "2099-12-31"}),
    ({"type": "daily", "interval": 1}, {"type": "numbered", "numberOfOccurrences": 5}), ({"type": "weekly", "interval": 1, "daysOfWeek": ["monday", "thursday"]}, {"type": "noEnd"}),
    ({"type": "weekly", "interval": 2, "daysOfWeek": ["monday"]}, {"type": "noEnd"}), ({"type": "weekly", "interval": 1, "daysOfWeek": []}, {"type": "noEnd"}),
    ({"type": "absoluteMonthly", "interval": 1, "dayOfMonth": 3}, {"type": "noEnd"}), ({"type": "daily", "interval": True}, {"type": "noEnd"}),
    ({"type": "daily"}, {"type": "noEnd"}), ({"type": "weekly", "interval": 1, "daysOfWeek": ["someday"]}, {"type": "noEnd"}),
], ids=str)
def test_a_rule_that_is_not_plain_daily_or_weekly_on_one_day_with_no_end_is_other(fake, tmp_path, state, pattern, span):
    fake.add_series(MASTER, "Gym", FIRST, LAST, pattern=pattern)
    fake.events[MASTER]["recurrence"]["range"] = {**span, "startDate": "2099-03-02"}
    assert got(fake, tmp_path, state, MASTER)["series_rule"] == "other" and got(fake, tmp_path, state, OCC[0])["series_rule"] == "other"


def test_vacuity_a_plain_pattern_is_not_other(fake, tmp_path, state):
    for pattern, word in (({"type": "daily", "interval": 1}, "daily"), ({"type": "daily", "interval": 1, "daysOfWeek": []}, "daily"), (WEEKLY, "weekly:MO"),
                          ({**WEEKLY, "daysOfWeek": ["sunday"]}, "weekly:SU")):
        fake.events.clear()
        fake.add_series(MASTER, "Gym", FIRST, LAST, pattern=pattern)
        assert got(fake, tmp_path, state, MASTER)["series_rule"] == word, pattern


def test_an_occurrence_whose_master_is_gone_reads_as_other(fake, tmp_path, state):
    fake.add_event(OCC[0], "Gym", FIRST, LAST, type="occurrence", seriesMasterId=MASTER)
    assert got(fake, tmp_path, state, OCC[0])["series_rule"] == "other"


# --- the whole series ------------------------------------------------------------------------------------------------------------------------------------


def test_the_dry_run_of_a_series_cancel_prints_exactly_one_post_of_cancel_on_the_masters_id_with_an_empty_body(fake, tmp_path, state):
    master, _ = a_series(fake)
    shown = out(run(fake, tmp_path, state, *series_args(master["changeKey"], mode="--dry-run")))
    assert shown["would"] == {"method": "POST", "path": f"/me/calendar/events/{MASTER.replace('=', '%3D')}/cancel", "query": {}, "headers": {}, "body": {},
                              "verb": "event-cancel-series", "guard": {}}
    assert fake.requests == [] and MASTER in fake.events


def test_a_series_cancel_reads_the_master_then_sends_one_cancel_post_on_the_masters_id_and_the_whole_series_goes_to_the_removed(fake, tmp_path, state):
    master, occurrences = a_series(fake)
    fake.add_event("AAMkKeep0001=", "Dentist", "2099-03-02T10:00:00", "2099-03-02T11:00:00")
    done = out(run(fake, tmp_path, state, *series_args(master["changeKey"])))
    assert done == {"done": True, "replayed": False, "event_id": MASTER, "etag": None}
    assert sent(fake) == [("GET", f"{EVENTS}/{MASTER}"), ("POST", f"{EVENTS}/{MASTER}/cancel")]
    assert calls(fake)[1][2:] == ({}, {})      # no query, and the body is the empty object: no comment can carry words
    assert fake.cancelled == [MASTER] and set(fake.removed) == {MASTER, *OCC} and list(fake.events) == ["AAMkKeep0001="]
    assert fake.unexpected() == [] and "DELETE" not in {m for m, _ in sent(fake)} and all(o["id"] in fake.removed for o in occurrences)


def test_a_series_cancel_in_a_named_calendar_goes_to_that_calendars_event(fake, tmp_path, state):
    master, _ = a_series(fake, _calendar=fgc.NAMED)
    out(run(fake, tmp_path, state, *series_args(master["changeKey"], calendar=fgc.NAMED)))
    assert sent(fake)[-1] == ("POST", f"/v1.0/me/calendars/{fgc.NAMED}/events/{MASTER}/cancel") and fake.cancelled == [MASTER]


def test_a_series_cancel_with_a_moved_change_key_is_refused_before_the_post_and_the_key_is_free(fake, tmp_path, state):
    master, _ = a_series(fake)
    old = master["changeKey"]
    master["changeKey"] = fake.next_key()
    refused(fake, tmp_path, state, series_args(old), "changed:")
    fake.requests.clear()
    assert out(run(fake, tmp_path, state, *series_args(master["changeKey"])))["done"] is True      # vacuity: the same key with the right base goes through


@pytest.mark.parametrize("pattern", [{"type": "daily", "interval": 2}, {"type": "weekly", "interval": 1, "daysOfWeek": ["monday", "friday"]}], ids=str)
def test_a_series_whose_rule_is_other_is_not_cancelled(fake, tmp_path, state, pattern):
    master, _ = a_series(fake, pattern=pattern)
    refused(fake, tmp_path, state, series_args(master["changeKey"]), "not eligible:")


def test_a_series_someone_else_organises_or_with_another_attendee_is_not_cancelled_and_one_with_only_the_person_is(fake, tmp_path, state):
    master, _ = a_series(fake, isOrganizer=False)
    refused(fake, tmp_path, state, series_args(master["changeKey"]), "organised by someone else")
    fake.events.clear()
    master, _ = a_series(fake, attendees=[{"emailAddress": {"address": "other@example.org"}}])
    refused(fake, tmp_path, state, series_args(master["changeKey"], key=KEY + "b"), "other attendees")
    fake.events.clear()
    master, _ = a_series(fake, attendees=[{"emailAddress": {"address": fgc.ADDRESS}}])      # vacuity: the person alone is no other attendee
    assert out(run(fake, tmp_path, state, *series_args(master["changeKey"], key=KEY + "c")))["done"] is True


def test_an_event_that_is_not_a_series_master_is_not_cancelled_as_a_series(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    refused(fake, tmp_path, state, series_args(occurrences[1]["changeKey"], event=OCC[1]), "not eligible:")      # an occurrence
    plain = fake.add_event("AAMkPlain0001=", "Dentist", "2099-03-02T10:00:00", "2099-03-02T11:00:00")
    refused(fake, tmp_path, state, series_args(plain["changeKey"], event="AAMkPlain0001=", key=KEY + "b"), "not eligible:")
    assert MASTER in fake.events


def test_a_gone_series_is_refused_as_changed(fake, tmp_path, state):
    refused(fake, tmp_path, state, series_args("CQAAAB", event="AAMkNone0001="), "changed:")


def test_when_graph_refuses_the_cancel_the_writer_exits_1_sends_nothing_else_and_never_falls_back_to_a_delete(fake, tmp_path, state):
    master, _ = a_series(fake)
    fake.refuse_next = (400, "ErrorInvalidRequest")
    proc = run(fake, tmp_path, state, *series_args(master["changeKey"]))
    assert proc.returncode == 1
    assert sent(fake) == [("GET", f"{EVENTS}/{MASTER}"), ("POST", f"{EVENTS}/{MASTER}/cancel")]      # the read, the cancel, and nothing after it
    assert "DELETE" not in {r["method"] for r in fake.requests} and MASTER in fake.events and fake.removed == {}
    fake.requests.clear()
    assert out(run(fake, tmp_path, state, *series_args(master["changeKey"])))["done"] is True      # the key was freed: the same request is tried again


def test_a_lost_answer_of_a_series_cancel_is_found_by_the_master_being_gone(fake, tmp_path, state):
    master, _ = a_series(fake)
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *series_args(master["changeKey"])).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *series_args(master["changeKey"])))
    assert again["replayed"] is True and sent(fake) == [("GET", f"{EVENTS}/{MASTER}")]


# --- the instances of a series -----------------------------------------------------------------------------------------------------------------------------


def test_event_instances_over_one_day_returns_that_occurrence_and_nothing_else_of_it(fake, tmp_path, state):
    a_series(fake, attendees=[{"emailAddress": {"address": "x@example.org"}}])
    proc = run(fake, tmp_path, state, *instances_args("2099-03-09T00:00:00Z", "2099-03-10T00:00:00Z"))
    shown = out(proc)
    assert "Gym" not in proc.stdout and "x@example.org" not in proc.stdout
    [instance] = shown["instances"]
    assert instance == {"id": OCC[1], "etag": fake.events[OCC[1]]["changeKey"], "start": "2099-03-09T10:00:00Z", "end": "2099-03-09T11:00:00Z", "status": "confirmed",
                        "original_start": "2099-03-09T10:00:00Z"}
    [(method, path, query, body)] = calls(fake)
    assert (method, path, body) == ("GET", f"{EVENTS}/{MASTER}/instances", None)
    assert query == {"startDateTime": "2099-03-09T00:00:00Z", "endDateTime": "2099-03-10T00:00:00Z", "$select": "id,changeKey,type,seriesMasterId,start,end,isCancelled,originalStart",
                     "$top": "10"}
    assert 'outlook.timezone="UTC"' in fake.graph_requests()[0]["prefer"]


def test_event_instances_in_a_named_calendar_and_over_a_day_with_none(fake, tmp_path, state):
    a_series(fake, _calendar=fgc.NAMED)
    assert [i["id"] for i in out(run(fake, tmp_path, state, *instances_args("2099-03-02T00:00:00Z", "2099-03-03T00:00:00Z", calendar=fgc.NAMED)))["instances"]] == [OCC[0]]
    assert sent(fake)[-1] == ("GET", f"/v1.0/me/calendars/{fgc.NAMED}/events/{MASTER}/instances")
    assert out(run(fake, tmp_path, state, *instances_args("2099-03-03T00:00:00Z", "2099-03-04T00:00:00Z", calendar=fgc.NAMED))) == {"instances": []}


def test_event_instances_wider_than_two_days_or_backwards_or_malformed_is_a_usage_error_and_nothing_is_sent(fake, tmp_path, state):
    a_series(fake, step=1)
    for low, high in (("2099-03-02T00:00:00Z", "2099-03-04T00:00:01Z"), ("2099-03-02T00:00:00Z", "2099-03-09T00:00:00Z"), ("2099-03-03T00:00:00Z", "2099-03-02T00:00:00Z"),
                      ("2099-03-02T00:00:00Z", "2099-03-02T00:00:00Z"), ("2099-03-02", "2099-03-03"), ("2099-03-02T00:00:00", "2099-03-03T00:00:00Z"), ("x", "y")):
        assert run(fake, tmp_path, state, *instances_args(low, high)).returncode == 2, (low, high)
    assert fake.requests == []
    assert len(out(run(fake, tmp_path, state, *instances_args("2099-03-02T00:00:00Z", "2099-03-04T00:00:00Z")))["instances"]) == 2      # vacuity: exactly two days passes


def test_a_cancelled_item_of_the_instances_is_not_listed(fake, tmp_path, state):
    _, occurrences = a_series(fake, step=1)
    window = instances_args("2099-03-03T00:00:00Z", "2099-03-05T00:00:00Z")
    assert [i["id"] for i in out(run(fake, tmp_path, state, *window))["instances"]] == [OCC[1], OCC[2]]      # vacuity: both are listed until one is cancelled
    occurrences[1]["isCancelled"] = True
    assert [i["id"] for i in out(run(fake, tmp_path, state, *window))["instances"]] == [OCC[2]]


def test_event_instances_needs_its_flags_and_is_a_read(fake, tmp_path, state):
    a_series(fake)
    low, high = "2099-03-09T00:00:00Z", "2099-03-10T00:00:00Z"
    base = ["event-instances", "--calendar", "default"]
    for args in (base + ["--from", low, "--to", high], base + ["--series", MASTER, "--to", high], base + ["--series", MASTER, "--from", low],
                 base + ["--series", MASTER, "--from", low, "--to", high, "--dry-run"], base + ["--series", MASTER, "--from", low, "--to", high, "--confirmed"],
                 base + ["--series", MASTER, "--from", low, "--to", high, "--event", "x1"], instances_args(low, high, series="-x"), instances_args(low, high, series="a/b")):
        assert run(fake, tmp_path, state, *args).returncode == 2, args
    assert fake.requests == []


# --- one occurrence ------------------------------------------------------------------------------------------------------------------------------------------


def test_the_dry_run_of_an_occurrence_cancel_prints_one_cancel_post_on_the_occurrences_id_and_never_the_masters(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    would = out(run(fake, tmp_path, state, *occurrence_args(occurrences[1]["changeKey"], mode="--dry-run")))["would"]
    assert would == {"method": "POST", "path": f"/me/calendar/events/{OCC[1].replace('=', '%3D')}/cancel", "query": {}, "headers": {}, "body": {},
                     "verb": "event-cancel-occurrence", "guard": {"series": MASTER, "expect_start": FUTURE_START}}
    assert fake.requests == [] and "Occ1" in would["path"]


def test_an_occurrence_cancel_reads_the_occurrence_and_its_series_then_cancels_that_occurrence_only(fake, tmp_path, state):
    master, occurrences = a_series(fake)
    before = {i: json.dumps(fake.events[i], sort_keys=True) for i in (MASTER, OCC[0], OCC[2])}
    done = out(run(fake, tmp_path, state, *occurrence_args(occurrences[1]["changeKey"])))
    assert done == {"done": True, "replayed": False, "event_id": OCC[1], "etag": None}
    assert sent(fake) == [("GET", f"{EVENTS}/{OCC[1]}"), ("GET", f"{EVENTS}/{MASTER}"), ("POST", f"{EVENTS}/{OCC[1]}/cancel")]
    assert calls(fake)[2][2:] == ({}, {}) and fake.cancelled == [OCC[1]] and set(fake.removed) == {OCC[1]}
    assert "DELETE" not in {m for m, _ in sent(fake)} and fake.unexpected() == []
    assert {i: json.dumps(fake.events[i], sort_keys=True) for i in before} == before      # the master and every other occurrence are untouched
    again = out(run(fake, tmp_path, state, *instances_args("2099-03-02T00:00:00Z", "2099-03-04T00:00:00Z")))
    assert [i["id"] for i in again["instances"]] == [OCC[0]]
    assert out(run(fake, tmp_path, state, *instances_args("2099-03-09T00:00:00Z", "2099-03-10T00:00:00Z"))) == {"instances": []}


def test_a_daily_series_loses_one_day_and_keeps_the_others(fake, tmp_path, state):
    _, occurrences = a_series(fake, pattern={"type": "daily", "interval": 1}, step=1)
    out(run(fake, tmp_path, state, *occurrence_args(occurrences[2]["changeKey"], event=OCC[2], start="2099-03-04T10:00:00Z")))
    assert [i["id"] for i in out(run(fake, tmp_path, state, *instances_args("2099-03-02T00:00:00Z", "2099-03-04T00:00:00Z")))["instances"]] == [OCC[0], OCC[1]]
    assert out(run(fake, tmp_path, state, *instances_args("2099-03-04T00:00:00Z", "2099-03-05T00:00:00Z"))) == {"instances": []}


def test_an_exception_that_starts_when_it_was_read_is_cancelled_like_an_occurrence(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    occurrences[1]["type"] = "exception"
    assert out(run(fake, tmp_path, state, *occurrence_args(occurrences[1]["changeKey"])))["done"] is True and fake.cancelled == [OCC[1]]


def test_an_occurrence_cancel_with_a_moved_change_key_is_refused_and_the_key_is_free(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    old = occurrences[1]["changeKey"]
    occurrences[1]["changeKey"] = fake.next_key()
    refused(fake, tmp_path, state, occurrence_args(old), "changed:")
    fake.requests.clear()
    assert out(run(fake, tmp_path, state, *occurrence_args(occurrences[1]["changeKey"])))["done"] is True      # vacuity


def test_an_occurrence_of_another_series_than_the_one_named_is_refused(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    refused(fake, tmp_path, state, occurrence_args(occurrences[1]["changeKey"], series="AAMkSeries0002="), "not an occurrence of that series")


def test_the_masters_id_and_a_plain_event_are_not_occurrences_and_are_refused(fake, tmp_path, state):
    master, _ = a_series(fake)
    refused(fake, tmp_path, state, occurrence_args(master["changeKey"], event=MASTER, start="2099-03-02T10:00:00Z"), "not an occurrence of that series")
    plain = fake.add_event("AAMkPlain0001=", "Dentist", "2099-03-09T10:00:00", "2099-03-09T11:00:00")
    refused(fake, tmp_path, state, occurrence_args(plain["changeKey"], event="AAMkPlain0001=", key=KEY + "b"), "not an occurrence of that series")


def test_an_occurrence_that_is_already_cancelled_or_gone_is_refused_as_changed(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    occurrences[1]["isCancelled"] = True
    refused(fake, tmp_path, state, occurrence_args(occurrences[1]["changeKey"]), "changed:")
    refused(fake, tmp_path, state, occurrence_args("CQAAAB", event="AAMkSeries0001Occ9="), "changed:")


def test_an_occurrence_that_was_moved_does_not_start_when_it_was_read_and_is_refused(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    occurrences[1]["type"] = "exception"
    occurrences[1]["start"] = {"dateTime": "2099-03-09T12:00:00.0000000", "timeZone": "UTC"}
    occurrences[1]["end"] = {"dateTime": "2099-03-09T13:00:00.0000000", "timeZone": "UTC"}
    refused(fake, tmp_path, state, occurrence_args(occurrences[1]["changeKey"]), "changed:")


def test_an_occurrence_in_the_past_is_refused_and_one_in_the_future_goes_through(fake, tmp_path, state):
    master, old = fake.add_series("AAMkOld0001=", "Gym", "2020-03-02T10:00:00", "2020-03-02T11:00:00", pattern=WEEKLY, step=7, days=2)
    refused(fake, tmp_path, state, occurrence_args(old[1]["changeKey"], event="AAMkOld0001Occ1=", series="AAMkOld0001=", start="2020-03-09T10:00:00Z"), "already started")
    _, future = a_series(fake)
    assert out(run(fake, tmp_path, state, *occurrence_args(future[1]["changeKey"], key=KEY + "b")))["done"] is True


@pytest.mark.parametrize("more, words", [({"isOrganizer": False}, "organised by someone else"),
                                         ({"attendees": [{"emailAddress": {"address": "other@example.org"}}]}, "other attendees")], ids=["organizer", "attendee"])
def test_an_occurrence_of_a_series_that_is_not_the_persons_alone_is_refused(fake, tmp_path, state, more, words):
    _, occurrences = a_series(fake, **more)
    refused(fake, tmp_path, state, occurrence_args(occurrences[1]["changeKey"]), words)


def test_an_occurrence_of_a_series_whose_rule_is_other_is_refused(fake, tmp_path, state):
    _, occurrences = a_series(fake, pattern={"type": "weekly", "interval": 2, "daysOfWeek": ["monday"]})
    refused(fake, tmp_path, state, occurrence_args(occurrences[1]["changeKey"]), "not part of a plain daily or weekly series")


def test_when_graph_refuses_the_occurrence_cancel_nothing_else_is_sent_and_there_is_no_delete(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    fake.refuse_next = (400, "ErrorInvalidRequest")
    assert run(fake, tmp_path, state, *occurrence_args(occurrences[1]["changeKey"])).returncode == 1
    assert sent(fake)[-1] == ("POST", f"{EVENTS}/{OCC[1]}/cancel") and "DELETE" not in {r["method"] for r in fake.requests} and fake.removed == {}


def test_a_lost_answer_of_an_occurrence_cancel_is_found_by_the_occurrence_being_gone(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    base = occurrences[1]["changeKey"]
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *occurrence_args(base)).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *occurrence_args(base)))
    assert again["replayed"] is True and sent(fake) == [("GET", f"{EVENTS}/{OCC[1]}")]


def test_the_flags_of_the_new_verbs_are_checked(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    key = occurrences[1]["changeKey"]
    good = occurrence_args(key, mode="--dry-run")

    def without(flag):
        at = good.index(flag)
        return good[:at] + good[at + 2:]
    for args in (without("--expect-start"), without("--series"), without("--base-etag"), without("--event"),
                 good[:good.index("--expect-start") + 1] + ["2099-03-09"] + good[good.index("--expect-start") + 2:],
                 good + ["--spec-file", "x"], good[:-1], good + ["--time-zone", ZONE],
                 series_args(key, mode="--dry-run") + ["--series", MASTER], series_args(key, mode="--dry-run") + ["--expect-start", FUTURE_START],
                 ["event-cancel-series", "--calendar", "default", "--event", "-x", "--base-etag", key, "--idempotency-key", KEY, "--dry-run"],
                 ["event-cancel-series", "--calendar", "default", "--event", "a/b", "--base-etag", key, "--idempotency-key", KEY, "--dry-run"],
                 ["event-delete", "--calendar", "default", "--event", MASTER, "--base-etag", key, "--idempotency-key", KEY, "--series", MASTER, "--dry-run"]):
        assert run(fake, tmp_path, state, *args).returncode == 2, args
    assert fake.requests == []


# --- the allow-list ---------------------------------------------------------------------------------------------------------------------------------------


def load_writer():
    spec = importlib.util.spec_from_file_location("outlook_calendar_writer_under_test_series", WRITER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_allow_list_gains_exactly_two_instances_reads_and_two_cancel_posts_and_no_delete(fake):
    writer = load_writer()
    delete = "DEL" + "ETE"
    assert [p for p in writer.ALLOWED if p[0] == delete] == [(delete, r"/me/calendar/events/(?:[A-Za-z0-9_-]|%3D|%2B)+"),
                                                             (delete, r"/me/calendars/(?:[A-Za-z0-9_-]|%3D)+/events/(?:[A-Za-z0-9_-]|%3D|%2B)+")]      # the two of S21, unchanged
    assert [p for p in writer.ALLOWED if p[1].endswith("/cancel")] == [("POST", r"/me/calendar/events/(?:[A-Za-z0-9_-]|%3D|%2B)+/cancel"),
                                                                       ("POST", r"/me/calendars/(?:[A-Za-z0-9_-]|%3D)+/events/(?:[A-Za-z0-9_-]|%3D|%2B)+/cancel")]
    assert [p for p in writer.ALLOWED if p[1].endswith("/instances")] == [("GET", r"/me/calendar/events/(?:[A-Za-z0-9_-]|%3D|%2B)+/instances"),
                                                                          ("GET", r"/me/calendars/(?:[A-Za-z0-9_-]|%3D)+/events/(?:[A-Za-z0-9_-]|%3D|%2B)+/instances")]
    assert len(writer.ALLOWED) == 15 and sorted({m for m, _ in writer.ALLOWED}) == [delete, "GET", "PATCH", "POST"]
    sent_to = []
    writer.msgraph.http = lambda *a, **k: sent_to.append(a)
    session = writer.Session(writer.msgraph.GraphClient(writer.PROFILE, fake.base, "token", True), {})
    for entry, path in ((writer.REMOVE_DEFAULT, "/me/calendar/events/x/cancel"), (writer.PATCH_DEFAULT, "/me/calendar/events/x/cancel"), (writer.POST_DEFAULT, "/me/calendar/events/x/cancel"),
                        (writer.CANCEL_DEFAULT, "/me/calendar/events/x"), (writer.CANCEL_DEFAULT, "/me/calendar/events/x/cancel/y"), (writer.CANCEL_DEFAULT, "/me/calendar/events//cancel"),
                        (writer.CANCEL_DEFAULT, "/me/calendar/events/../cancel"), (writer.CANCEL_DEFAULT, "/me/calendars/a/events/x/cancel"), (writer.CANCEL_IN, "/me/calendar/events/x/cancel"),
                        (writer.CANCEL_IN, "/me/calendars/a.b/events/x/cancel"), (writer.CANCEL_DEFAULT, "/me/events/x/cancel"), (writer.INSTANCES_DEFAULT, "/me/calendar/events/x"),
                        (writer.INSTANCES_DEFAULT, "/me/calendar/events/x/instances/y"), (writer.INSTANCES_DEFAULT, "/me/calendars/a/events/x/instances"),
                        (writer.GET_DEFAULT, "/me/calendar/events/x/instances"), (("POST", r"/me/calendar/events/(?:[A-Za-z0-9_-]|%3D|%2B)+/instances"), "/me/calendar/events/x/instances"),
                        ((delete, r"/me/calendar/events/[^/]+/cancel"), "/me/calendar/events/x/cancel")):
        with pytest.raises(writer.WriterError) as why:
            writer.request(entry, session, path, {}, {})
        assert why.value.code == 2, (entry, path)
    assert sent_to == []
    writer.request(writer.CANCEL_DEFAULT, session, "/me/calendar/events/x/cancel", {}, {}, {})      # vacuity: the pairs of the list pass the check and reach the connection
    writer.request(writer.INSTANCES_IN, session, "/me/calendars/a/events/x/instances", {}, {})
    assert len(sent_to) == 2


def test_no_run_of_any_series_verb_sends_a_delete_or_a_request_outside_the_list(fake, tmp_path, state):
    master, occurrences = a_series(fake)
    out(run(fake, tmp_path, state, *occurrence_args(occurrences[0]["changeKey"], event=OCC[0], start="2099-03-02T10:00:00Z", key=KEY + "o")))
    out(run(fake, tmp_path, state, *instances_args("2099-03-02T00:00:00Z", "2099-03-04T00:00:00Z")))
    out(run(fake, tmp_path, state, "event-get", "--calendar", "default", "--event", OCC[1]))
    out(run(fake, tmp_path, state, *series_args(master["changeKey"], key=KEY + "s")))
    assert fake.unexpected() == [] and not [m for m, _ in sent(fake) if m == "DEL" + "ETE"]
    assert [p for m, p in sent(fake) if m == "POST"] == [f"{EVENTS}/{OCC[0]}/cancel", f"{EVENTS}/{MASTER}/cancel"]


def test_vacuity_a_planted_delete_or_a_comment_would_be_caught_by_the_oracles_above():
    planted = [("DEL" + "ETE", f"{EVENTS}/{MASTER}")]
    assert [m for m, _ in planted if m == "DEL" + "ETE"] == ["DEL" + "ETE"]      # the oracle `no DELETE in sent(fake)` is not blind to one
    assert {"comment": "x"} != {} and not {}      # and `body == {}` fails on a body that holds a comment


# --- review round: the guard flags are in the hash, build() has no fallthrough, the type clause of the occurrence guard ------------------------------------------------


def dry_hash(fake, tmp_path, state, args):
    return out(run(fake, tmp_path, state, *args))["would_sha256"]


def test_the_hash_covers_the_verb_and_the_guard_flags_not_only_the_request(fake, tmp_path, state):
    key = "CQAAAB"
    series = dry_hash(fake, tmp_path, state, series_args(key, event=OCC[1], mode="--dry-run"))
    occurrence = dry_hash(fake, tmp_path, state, occurrence_args(key, mode="--dry-run"))
    assert series != occurrence      # the same cancel POST on the same id: one is a series cancel, the other an occurrence's
    base = occurrence_args(key, mode="--dry-run")
    assert dry_hash(fake, tmp_path, state, base) == occurrence      # vacuity: the same flags, the same hash
    other_series = base[:base.index("--series") + 1] + ["AAMkSeries0002="] + base[base.index("--series") + 2:]
    other_start = base[:base.index("--expect-start") + 1] + ["2099-03-16T10:00:00Z"] + base[base.index("--expect-start") + 2:]
    assert len({occurrence, dry_hash(fake, tmp_path, state, other_series), dry_hash(fake, tmp_path, state, other_start)}) == 3


def test_a_confirmed_run_with_other_guard_flags_than_the_preview_is_another_request_for_the_ledger(fake, tmp_path, state):
    _, occurrences = a_series(fake)
    key = occurrences[1]["changeKey"]
    swapped = occurrence_args(key, start="2099-03-16T10:00:00Z")
    assert dry_hash(fake, tmp_path, state, swapped[:-1] + ["--dry-run"]) != dry_hash(fake, tmp_path, state, occurrence_args(key, mode="--dry-run"))
    out(run(fake, tmp_path, state, *occurrence_args(key)))
    again = run(fake, tmp_path, state, *swapped)
    assert again.returncode == 2 and "used for another request" in again.stderr


def test_build_sends_no_request_for_a_verb_it_does_not_build_and_never_falls_back_to_the_delete(fake, tmp_path):
    import argparse
    writer = load_writer()
    args = argparse.Namespace(calendar="default", idempotency_key=KEY, event=MASTER, base_etag="CQAAAB", series=None, expect_start=None, spec_file=None, time_zone=None)
    for verb in ("event-instances", "event-get", "event-drop", "", None):
        with pytest.raises(writer.WriterError) as why:
            writer.build(verb, args)
        assert why.value.code == 2, verb
    assert writer.build("event-delete", args)["method"] == "DEL" + "ETE"      # vacuity: the one verb that builds the DELETE does


def test_the_type_clause_of_the_occurrence_guard_a_master_is_never_an_occurrence_even_if_it_names_itself_as_its_series(fake, tmp_path, state):
    master, _ = a_series(fake)
    master["seriesMasterId"] = MASTER
    refused(fake, tmp_path, state, occurrence_args(master["changeKey"], event=MASTER, series=MASTER, start="2099-03-02T10:00:00Z"), "not an occurrence of that series")
    assert MASTER in fake.events and fake.cancelled == []
