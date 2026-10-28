"""Tests of the series verbs of the Google calendar writer (providers/writer/google-calendar.py; package CB-6; limits L57 and L58). Against the stand-in service
(fake_gcal_write.py) on 127.0.0.1: no Google host is reached and no real credential exists. A series is a create spec with `recurrence` and `time_zone` together
(daily, or weekly on one weekday, no end); `event-get` reports `series_id` and `series_rule`; `event-delete --series` is the one DELETE of the master after a read of it;
`event-instances` reads the instances of a series in a window of at most two days; `event-cancel-occurrence` is one PATCH of one instance with `status: cancelled` and
nothing else, after a read of the instance and of its series. Every test asserts the exact list of requests the fake recorded. Every date is made up (2099 for a time that
has not come, 2020 for one that has).

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_google_calendar_series.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_gcal_write as fgw  # noqa: E402

WRITER = REPO / "providers" / "writer" / "google-calendar.py"
KEY = "ser-0123456789abcdef0123456789abcdef"
ZONE = "America/Sao_Paulo"
START, END = "2099-03-02T07:00:00-03:00", "2099-03-02T08:00:00-03:00"      # a Monday, 10:00Z
EVENTS = fgw.EVENTS_PREFIX
SERIES_SPEC = {"title": "Gym", "all_day": False, "start_at": START, "end_at": END, "location": "", "reminder_minutes": None, "notes": "",
               "recurrence": {"freq": "weekly", "byday": "MO"}, "time_zone": ZONE}
DAILY_SPEC = {**SERIES_SPEC, "recurrence": {"freq": "daily"}}
WEEKLY_RULE, DAILY_RULE = "RRULE:FREQ=WEEKLY;BYDAY=MO", "RRULE:FREQ=DAILY"


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


def env_of(fake, tmp_path, state, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "GOOGLE_ACCOUNT_TOKEN": fake.record_json(), **fake.env()})
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
        for secret in fgw.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def calls(fake):
    return [(r["method"], r["path"], r["query"], r["body"]) for r in fake.requests if r["path"] != "/token"]


def sent(fake):
    """(method, path) of every request after the token."""
    return [(m, p) for m, p, _, _ in calls(fake)]


def insert_args(tmp_path, spec, mode="--confirmed", key=KEY):
    return ["event-insert", "--calendar", fgw.CALENDAR, "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", key, mode]


def delete_args(etag, event="ser0001", mode="--confirmed", key=KEY, series=True):
    return ["event-delete", "--calendar", fgw.CALENDAR, "--event", event, "--base-etag", etag, "--idempotency-key", key, *(["--series"] if series else []), mode]


def cancel_args(etag, event="ser0001_1", series="ser0001", start="2099-03-09T07:00:00-03:00", mode="--confirmed", key=KEY):
    return ["event-cancel-occurrence", "--calendar", fgw.CALENDAR, "--event", event, "--series", series, "--expect-start", start, "--base-etag", etag,
            "--idempotency-key", key, mode]


def a_series(fake, rule=WEEKLY_RULE, **more):
    return fake.add_series("ser0001", "Gym", START, END, rule=rule, **more)


def forbidden_in_rrule(body) -> list:
    """The parts of an RRULE that must never be written: an end, an interval, a day of the month, anything but FREQ and one BYDAY."""
    found = []
    for line in body.get("recurrence") or []:
        for part in line[len("RRULE:"):].split(";"):
            if part.split("=")[0] not in ("FREQ", "BYDAY"):
                found.append(part)
    return found


# --- the spec of a series -----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("spec", [
    {k: v for k, v in SERIES_SPEC.items() if k != "time_zone"},                                     # a recurrence without its zone
    {k: v for k, v in SERIES_SPEC.items() if k != "recurrence"},                                    # a zone without a recurrence
    {**SERIES_SPEC, "recurrence": {"freq": "monthly"}},
    {**SERIES_SPEC, "recurrence": {"freq": "daily", "interval": 2}},
    {**SERIES_SPEC, "recurrence": {"freq": "daily", "until": "2099-12-31"}},
    {**SERIES_SPEC, "recurrence": {"freq": "weekly"}},                                              # no weekday
    {**SERIES_SPEC, "recurrence": {"freq": "weekly", "byday": ["MO", "TU"]}},                       # two days
    {**SERIES_SPEC, "recurrence": {"freq": "weekly", "byday": "XX"}},
    {**SERIES_SPEC, "recurrence": {"freq": "weekly", "byday": "MO", "count": 4}},
    {**SERIES_SPEC, "recurrence": {"freq": "weekly", "byday": "TU"}},                               # the start is a Monday in the zone
    {**SERIES_SPEC, "recurrence": "RRULE:FREQ=DAILY"},
    {**SERIES_SPEC, "recurrence": None},
    {**SERIES_SPEC, "all_day": True, "start_at": "2099-03-02", "end_at": "2099-03-03"},
    {**SERIES_SPEC, "time_zone": "Nowhere/Land"},
    {**SERIES_SPEC, "time_zone": "UTC"},
    {**SERIES_SPEC, "time_zone": "../etc/passwd"},
    {**SERIES_SPEC, "extra": 1},
], ids=lambda s: json.dumps(s, sort_keys=True)[:90])
def test_a_wrong_series_spec_is_a_usage_error_and_nothing_is_sent(fake, tmp_path, state, spec):
    for mode in ("--dry-run", "--confirmed"):
        assert run(fake, tmp_path, state, *insert_args(tmp_path, spec, mode)).returncode == 2
    assert fake.requests == []


def test_a_patch_never_carries_a_recurrence_or_a_zone(fake, tmp_path, state):
    for spec in ({"recurrence": {"freq": "daily"}}, {"time_zone": ZONE}, {"title": "Gym", "recurrence": {"freq": "daily"}, "time_zone": ZONE}):
        args = ["event-patch", "--calendar", fgw.CALENDAR, "--event", "ser0001", "--base-etag", '"1"', "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", KEY, "--dry-run"]
        assert run(fake, tmp_path, state, *args).returncode == 2, spec
    assert fake.requests == []


def test_a_weekly_series_dry_run_prints_one_post_with_the_rule_and_the_zone_on_both_ends_and_no_other_part(fake, tmp_path, state):
    shown = out(run(fake, tmp_path, state, *insert_args(tmp_path, SERIES_SPEC, "--dry-run")))
    would = shown["would"]
    assert (would["method"], would["path"]) == ("POST", EVENTS) and would["query"] == {"sendUpdates": "none", "fields": "id,etag,status"}
    body = would["body"]
    assert body["recurrence"] == [WEEKLY_RULE]
    assert body["start"] == {"dateTime": START, "timeZone": ZONE} and body["end"] == {"dateTime": END, "timeZone": ZONE}
    assert forbidden_in_rrule(body) == [] and "attendees" not in body and fake.requests == []


def test_a_daily_series_dry_run_prints_the_daily_rule_and_the_dry_run_hash_covers_the_series(fake, tmp_path, state):
    daily = out(run(fake, tmp_path, state, *insert_args(tmp_path, DAILY_SPEC, "--dry-run")))
    weekly = out(run(fake, tmp_path, state, *insert_args(tmp_path, SERIES_SPEC, "--dry-run")))
    plain = out(run(fake, tmp_path, state, *insert_args(tmp_path, {k: v for k, v in SERIES_SPEC.items() if k not in ("recurrence", "time_zone")}, "--dry-run")))
    assert daily["would"]["body"]["recurrence"] == [DAILY_RULE] and forbidden_in_rrule(daily["would"]["body"]) == []
    assert len({daily["would_sha256"], weekly["would_sha256"], plain["would_sha256"]}) == 3
    assert "recurrence" not in plain["would"]["body"] and "timeZone" not in plain["would"]["body"]["start"]      # a plain event is what it always was


def test_a_series_create_is_exactly_one_post_and_the_fake_holds_a_master_with_the_rule(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *insert_args(tmp_path, SERIES_SPEC)))
    assert done["done"] is True and done["event_id"] == "ev0001"
    assert sent(fake) == [("POST", EVENTS)] and fake.events["ev0001"]["recurrence"] == [WEEKLY_RULE] and fake.unexpected() == []


def test_a_lost_answer_of_a_series_create_is_found_by_its_private_property(fake, tmp_path, state):
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *insert_args(tmp_path, SERIES_SPEC)).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *insert_args(tmp_path, SERIES_SPEC)))
    assert again["replayed"] is True and again["event_id"] == "ev0001" and [m for m, _ in sent(fake)] == ["GET"]


# --- event-get: the series ------------------------------------------------------------------------------------------------------------------------------


def got(fake, tmp_path, state, event):
    return out(run(fake, tmp_path, state, "event-get", "--calendar", fgw.CALENDAR, "--event", event))["event"]


def test_event_get_gives_the_same_series_id_for_the_master_and_an_instance_and_the_rule_in_closed_words(fake, tmp_path, state):
    a_series(fake)
    master, instance = got(fake, tmp_path, state, "ser0001"), got(fake, tmp_path, state, "ser0001_1")
    assert (master["series_id"], master["series_rule"]) == ("ser0001", "weekly:MO")
    assert (instance["series_id"], instance["series_rule"]) == ("ser0001", "weekly:MO") and instance["recurring"] is True


def test_event_get_of_a_daily_series_says_daily_and_of_a_plain_event_says_null(fake, tmp_path, state):
    a_series(fake, rule=DAILY_RULE)
    fake.add_event("plain0001", "Dentist", {"dateTime": START}, {"dateTime": END})
    assert got(fake, tmp_path, state, "ser0001")["series_rule"] == "daily" and got(fake, tmp_path, state, "ser0001_2")["series_rule"] == "daily"
    plain = got(fake, tmp_path, state, "plain0001")
    assert plain["series_id"] is None and plain["series_rule"] is None and plain["recurring"] is False


@pytest.mark.parametrize("recurrence", [
    ["RRULE:FREQ=DAILY;INTERVAL=2"], ["RRULE:FREQ=DAILY;UNTIL=20991231T000000Z"], ["RRULE:FREQ=DAILY;COUNT=5"], ["RRULE:FREQ=WEEKLY;BYDAY=MO,TH"],
    ["RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"], ["RRULE:FREQ=WEEKLY"], ["RRULE:FREQ=MONTHLY;BYMONTHDAY=3"], ["RRULE:FREQ=DAILY;BYDAY=MO"],
    [WEEKLY_RULE, "EXDATE:20990309T100000Z"], ["RRULE:FREQ=WEEKLY;BYDAY=1MO"], ["RRULE:FREQ=DAILY;FREQ=DAILY"], ["FREQ=DAILY"], [], "RRULE:FREQ=DAILY",
], ids=str)
def test_a_rule_that_is_not_plain_daily_or_weekly_on_one_day_is_other(fake, tmp_path, state, recurrence):
    fake.add_event("ser0001", "Gym", {"dateTime": START}, {"dateTime": END}, recurrence=recurrence)
    fake.add_event("ser0001_1", "Gym", {"dateTime": START}, {"dateTime": END}, recurringEventId="ser0001")
    assert got(fake, tmp_path, state, "ser0001_1")["series_rule"] == "other"
    if recurrence:
        assert got(fake, tmp_path, state, "ser0001")["series_rule"] == "other"


def test_vacuity_a_plain_rule_and_an_interval_one_are_not_other(fake, tmp_path, state):      # the refusals above are not a reader that says other to everything
    for rule, word in ((DAILY_RULE, "daily"), ("RRULE:FREQ=DAILY;INTERVAL=1", "daily"), (WEEKLY_RULE, "weekly:MO"), ("RRULE:FREQ=WEEKLY;BYDAY=SU", "weekly:SU")):
        fake.events.clear()
        fake.add_event("ser0001", "Gym", {"dateTime": START}, {"dateTime": END}, recurrence=[rule])
        assert got(fake, tmp_path, state, "ser0001")["series_rule"] == word, rule


def test_an_instance_whose_master_is_gone_reads_as_other(fake, tmp_path, state):
    fake.add_event("ser0001_1", "Gym", {"dateTime": START}, {"dateTime": END}, recurringEventId="ser0001")
    assert got(fake, tmp_path, state, "ser0001_1")["series_rule"] == "other"


# --- the whole series ------------------------------------------------------------------------------------------------------------------------------------


def test_the_dry_run_of_a_series_cancel_prints_exactly_one_delete_of_the_master_and_sends_nothing(fake, tmp_path, state):
    master, _ = a_series(fake)
    shown = out(run(fake, tmp_path, state, *delete_args(master["etag"], mode="--dry-run")))
    assert shown["would"] == {"method": "DELETE", "path": f"{EVENTS}/ser0001", "query": {"sendUpdates": "none"}, "headers": {"If-Match": master["etag"]}, "body": None}
    assert fake.requests == [] and "ser0001" in fake.events


def test_a_series_cancel_reads_the_master_then_sends_one_delete_of_the_masters_id_and_the_whole_series_goes(fake, tmp_path, state):
    master, instances = a_series(fake)
    other = fake.add_event("keep0001", "Dentist", {"dateTime": START}, {"dateTime": END})
    done = out(run(fake, tmp_path, state, *delete_args(master["etag"])))
    assert done["done"] is True and done["replayed"] is False
    assert sent(fake) == [("GET", f"{EVENTS}/ser0001"), ("DELETE", f"{EVENTS}/ser0001")]
    assert fake.requests[-1]["if_match"] == master["etag"] and fake.requests[-1]["query"] == {"sendUpdates": "none"}
    assert set(fake.removed) == {"ser0001", "ser0001_0", "ser0001_1", "ser0001_2"} and list(fake.events) == ["keep0001"] and other["id"] in fake.events
    assert fake.unexpected() == [] and all(i["id"] in fake.removed for i in instances)


def refused(fake, tmp_path, state, args, words):
    proc = run(fake, tmp_path, state, *args)
    assert proc.returncode == 1 and words in proc.stderr, (proc.returncode, proc.stderr)
    assert fake.writes() == [] and fake.removed == {}      # nothing was sent but reads
    return proc


def test_a_series_cancel_with_a_moved_base_is_refused_with_nothing_removed_and_the_key_is_free(fake, tmp_path, state):
    master, _ = a_series(fake)
    old = master["etag"]
    master["etag"] = fake.next_etag()
    refused(fake, tmp_path, state, delete_args(old), "changed:")
    fake.requests.clear()
    assert out(run(fake, tmp_path, state, *delete_args(master["etag"])))["done"] is True      # vacuity: the same key with the right base goes through


@pytest.mark.parametrize("rule", ["RRULE:FREQ=DAILY;INTERVAL=2", "RRULE:FREQ=DAILY;COUNT=3", "RRULE:FREQ=WEEKLY;BYDAY=MO,TU"], ids=str)
def test_a_series_whose_rule_is_other_is_not_cancelled(fake, tmp_path, state, rule):
    master, _ = a_series(fake, rule=rule)
    refused(fake, tmp_path, state, delete_args(master["etag"]), "not eligible:")


def test_a_series_someone_else_organises_or_with_another_attendee_is_not_cancelled(fake, tmp_path, state):
    master, _ = a_series(fake, organizer={"email": "boss@example.org", "self": False})
    refused(fake, tmp_path, state, delete_args(master["etag"]), "organised by someone else")
    fake.events.clear()
    master, _ = a_series(fake, attendees=[{"email": "other@example.org", "self": False}, {"email": fgw.ACCOUNT, "self": True}])
    refused(fake, tmp_path, state, delete_args(master["etag"], key=KEY + "b"), "other attendees")


def test_an_event_that_is_not_a_series_master_is_not_cancelled_as_a_series(fake, tmp_path, state):
    master, instances = a_series(fake)
    refused(fake, tmp_path, state, delete_args(instances[1]["etag"], event="ser0001_1"), "not eligible:")      # an instance
    fake.add_event("plain0001", "Dentist", {"dateTime": START}, {"dateTime": END})
    refused(fake, tmp_path, state, delete_args(fake.events["plain0001"]["etag"], event="plain0001", key=KEY + "c"), "not eligible:")
    assert master["id"] in fake.events


def test_a_gone_series_is_refused_as_changed(fake, tmp_path, state):
    refused(fake, tmp_path, state, delete_args('"1"', event="ser9999"), "changed:")


def test_a_lost_answer_of_a_series_cancel_is_found_by_the_master_being_gone(fake, tmp_path, state):
    master, _ = a_series(fake)
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *delete_args(master["etag"])).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *delete_args(master["etag"])))
    assert again["replayed"] is True and sent(fake) == [("GET", f"{EVENTS}/ser0001")]


# --- the instances of a series -----------------------------------------------------------------------------------------------------------------------------


def instances_args(low, high, series="ser0001"):
    return ["event-instances", "--calendar", fgw.CALENDAR, "--series", series, "--from", low, "--to", high]


def test_event_instances_of_a_weekly_series_over_one_day_returns_that_instance_and_nothing_else_of_it(fake, tmp_path, state):
    a_series(fake, attendees=[{"email": "x@example.org", "self": False}])
    proc = run(fake, tmp_path, state, *instances_args("2099-03-09T00:00:00-03:00", "2099-03-09T23:59:59-03:00"))
    shown = out(proc)
    assert [i["id"] for i in shown["instances"]] == ["ser0001_1"] and "Gym" not in proc.stdout and "x@example.org" not in proc.stdout
    [instance] = shown["instances"]
    assert set(instance) == {"id", "etag", "start", "end", "status", "original_start"}
    assert instance["start"] == "2099-03-09T07:00:00-03:00" and instance["end"] == "2099-03-09T08:00:00-03:00" and instance["status"] == "confirmed"
    assert instance["original_start"] == "2099-03-09T07:00:00-03:00" and instance["etag"] == fake.events["ser0001_1"]["etag"]
    [(method, path, query, body)] = calls(fake)
    assert (method, path, body) == ("GET", f"{EVENTS}/ser0001/instances", None)
    assert query == {"timeMin": "2099-03-09T03:00:00Z", "timeMax": "2099-03-10T02:59:59Z", "showDeleted": "false", "maxResults": "10",
                     "fields": "items(id,etag,status,start,end,originalStartTime,recurringEventId)"}


def test_event_instances_over_a_day_with_none_returns_none_and_a_cancelled_instance_is_not_listed(fake, tmp_path, state):
    a_series(fake)
    assert out(run(fake, tmp_path, state, *instances_args("2099-03-10T00:00:00-03:00", "2099-03-11T00:00:00-03:00"))) == {"instances": []}
    fake.events["ser0001_1"]["status"] = "cancelled"
    assert out(run(fake, tmp_path, state, *instances_args("2099-03-09T00:00:00-03:00", "2099-03-10T00:00:00-03:00"))) == {"instances": []}


def test_event_instances_wider_than_two_days_or_backwards_or_malformed_is_a_usage_error_and_nothing_is_sent(fake, tmp_path, state):
    a_series(fake)
    for low, high in (("2099-03-09T00:00:00-03:00", "2099-03-11T00:00:01-03:00"), ("2099-03-09T00:00:00-03:00", "2099-03-12T00:00:00-03:00"),
                      ("2099-03-09T10:00:00-03:00", "2099-03-09T09:00:00-03:00"), ("2099-03-09T10:00:00-03:00", "2099-03-09T10:00:00-03:00"),
                      ("2099-03-09", "2099-03-10"), ("2099-03-09T00:00:00", "2099-03-09T12:00:00-03:00"), ("x", "y")):
        assert run(fake, tmp_path, state, *instances_args(low, high)).returncode == 2, (low, high)
    assert fake.requests == []
    assert out(run(fake, tmp_path, state, *instances_args("2099-03-09T00:00:00-03:00", "2099-03-11T00:00:00-03:00")))["instances"]      # vacuity: exactly two days passes


def test_event_instances_needs_its_flags_and_is_a_read(fake, tmp_path, state):
    a_series(fake)
    low, high = "2099-03-09T00:00:00-03:00", "2099-03-10T00:00:00-03:00"
    base = ["event-instances", "--calendar", fgw.CALENDAR]
    for args in (base + ["--from", low, "--to", high],                                                  # no series
                 base + ["--series", "ser0001", "--to", high], base + ["--series", "ser0001", "--from", low],
                 base + ["--series", "--from", low, "--to", high],                                      # --series without the master's id
                 base + ["--series", "ser0001", "--from", low, "--to", high, "--dry-run"], base + ["--series", "ser0001", "--from", low, "--to", high, "--confirmed"],
                 base + ["--series", "ser0001", "--from", low, "--to", high, "--event", "x1"],
                 instances_args(low, high, series="-x"), instances_args(low, high, series="a/b")):
        assert run(fake, tmp_path, state, *args).returncode == 2, args
    assert fake.requests == []


# --- one occurrence ------------------------------------------------------------------------------------------------------------------------------------------


def test_the_dry_run_of_an_occurrence_cancel_prints_one_patch_of_the_instance_with_only_the_status_and_the_key(fake, tmp_path, state):
    _, instances = a_series(fake)
    shown = out(run(fake, tmp_path, state, *cancel_args(instances[1]["etag"], mode="--dry-run")))
    would = shown["would"]
    assert would["method"] == "PATCH" and would["path"] == f"{EVENTS}/ser0001_1" and "ser0001_1" in would["path"] and would["path"] != f"{EVENTS}/ser0001"
    assert would["body"] == {"status": "cancelled", "extendedProperties": {"private": {"openhora_key": KEY}}}
    assert would["query"] == {"sendUpdates": "none", "fields": "id,etag,status"} and would["headers"] == {"If-Match": instances[1]["etag"]}
    assert fake.requests == []


def test_an_occurrence_cancel_reads_the_instance_and_the_series_then_patches_that_instance_only(fake, tmp_path, state):
    master, instances = a_series(fake)
    base = instances[1]["etag"]
    before = {i: json.dumps(fake.events[i], sort_keys=True) for i in ("ser0001", "ser0001_0", "ser0001_2")}
    done = out(run(fake, tmp_path, state, *cancel_args(base)))
    assert done["done"] is True and done["replayed"] is False and done["event_id"] == "ser0001_1"
    assert sent(fake) == [("GET", f"{EVENTS}/ser0001_1"), ("GET", f"{EVENTS}/ser0001"), ("PATCH", f"{EVENTS}/ser0001_1")]
    assert fake.requests[-1]["body"] == {"status": "cancelled", "extendedProperties": {"private": {"openhora_key": KEY}}}
    assert fake.requests[-1]["if_match"] == base and "DELETE" not in {m for m, _ in sent(fake)}
    assert fake.events["ser0001_1"]["status"] == "cancelled" and fake.removed == {} and fake.unexpected() == []      # an exception of the series: cancelled, not deleted
    assert {i: json.dumps(fake.events[i], sort_keys=True) for i in before} == before      # the master and every other instance are untouched
    window = out(run(fake, tmp_path, state, *instances_args("2099-03-02T00:00:00-03:00", "2099-03-04T00:00:00-03:00")))
    assert [i["id"] for i in window["instances"]] == ["ser0001_0"]
    again = out(run(fake, tmp_path, state, *instances_args("2099-03-09T00:00:00-03:00", "2099-03-10T00:00:00-03:00")))
    assert again == {"instances": []}


def test_a_daily_series_loses_one_day_and_keeps_the_others(fake, tmp_path, state):
    _, instances = a_series(fake, rule=DAILY_RULE)
    out(run(fake, tmp_path, state, *cancel_args(instances[2]["etag"], event="ser0001_2", start="2099-03-04T07:00:00-03:00")))
    shown = out(run(fake, tmp_path, state, *instances_args("2099-03-02T00:00:00-03:00", "2099-03-04T00:00:00-03:00")))
    assert [i["id"] for i in shown["instances"]] == ["ser0001_0", "ser0001_1"]
    assert out(run(fake, tmp_path, state, *instances_args("2099-03-04T00:00:00-03:00", "2099-03-05T00:00:00-03:00"))) == {"instances": []}      # the day that was cancelled


def test_an_occurrence_cancel_with_a_moved_base_is_refused_and_the_key_is_free(fake, tmp_path, state):
    _, instances = a_series(fake)
    old = instances[1]["etag"]
    instances[1]["etag"] = fake.next_etag()
    refused(fake, tmp_path, state, cancel_args(old), "changed:")
    fake.requests.clear()
    assert out(run(fake, tmp_path, state, *cancel_args(instances[1]["etag"])))["done"] is True      # vacuity


def test_an_occurrence_of_another_series_than_the_one_named_is_refused(fake, tmp_path, state):
    _, instances = a_series(fake)
    refused(fake, tmp_path, state, cancel_args(instances[1]["etag"], series="ser0002"), "not an occurrence of that series")


def test_the_masters_id_is_not_an_occurrence_and_is_refused(fake, tmp_path, state):
    master, _ = a_series(fake)
    refused(fake, tmp_path, state, cancel_args(master["etag"], event="ser0001", series="ser0001", start=START), "not an occurrence of that series")
    assert fake.events["ser0001"]["status"] == "confirmed"


def test_an_occurrence_that_is_already_cancelled_or_gone_is_refused_as_changed(fake, tmp_path, state):
    _, instances = a_series(fake)
    instances[1]["status"] = "cancelled"
    refused(fake, tmp_path, state, cancel_args(instances[1]["etag"]), "changed:")
    refused(fake, tmp_path, state, cancel_args('"1"', event="ser0001_9", key=KEY + "b"), "changed:")


def test_an_occurrence_that_was_moved_does_not_start_when_it_was_read_and_is_refused(fake, tmp_path, state):
    _, instances = a_series(fake)
    instances[1]["start"] = {"dateTime": "2099-03-09T09:00:00-03:00"}
    instances[1]["end"] = {"dateTime": "2099-03-09T10:00:00-03:00"}
    refused(fake, tmp_path, state, cancel_args(instances[1]["etag"]), "changed:")


def test_an_occurrence_in_the_past_is_refused_and_one_in_the_future_goes_through(fake, tmp_path, state):
    master, instances = fake.add_series("old0001", "Gym", "2020-03-02T07:00:00-03:00", "2020-03-02T08:00:00-03:00", rule=WEEKLY_RULE, days=2)
    refused(fake, tmp_path, state, cancel_args(instances[1]["etag"], event="old0001_1", series="old0001", start="2020-03-09T07:00:00-03:00"), "already started")
    _, future = a_series(fake)
    assert out(run(fake, tmp_path, state, *cancel_args(future[1]["etag"], key=KEY + "b")))["done"] is True


@pytest.mark.parametrize("more, words", [({"organizer": {"email": "boss@example.org", "self": False}}, "organised by someone else"),
                                         ({"attendees": [{"email": "other@example.org", "self": False}]}, "other attendees")], ids=["organizer", "attendee"])
def test_an_occurrence_of_a_series_that_is_not_the_persons_alone_is_refused(fake, tmp_path, state, more, words):
    _, instances = a_series(fake, **more)
    refused(fake, tmp_path, state, cancel_args(instances[1]["etag"]), words)


def test_an_occurrence_of_a_series_whose_rule_is_other_is_refused(fake, tmp_path, state):
    _, instances = a_series(fake, rule="RRULE:FREQ=DAILY;INTERVAL=2")
    refused(fake, tmp_path, state, cancel_args(instances[1]["etag"]), "not part of a plain daily or weekly series")


def test_a_lost_answer_of_an_occurrence_cancel_is_found_by_the_instance_being_cancelled(fake, tmp_path, state):
    _, instances = a_series(fake)
    base = instances[1]["etag"]
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *cancel_args(base)).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *cancel_args(base)))
    assert again["replayed"] is True and sent(fake) == [("GET", f"{EVENTS}/ser0001_1")]


def test_the_flags_of_the_new_verbs_are_checked(fake, tmp_path, state):
    _, instances = a_series(fake)
    etag = instances[1]["etag"]
    good = cancel_args(etag, mode="--dry-run")
    for args in ([a for a in good if a not in ("--expect-start", "2099-03-09T07:00:00-03:00")],              # no expected start
                 [a for a in good if a not in ("--series", "ser0001")],
                 good[:good.index("--expect-start") + 1] + ["2099-03-09"] + good[good.index("--expect-start") + 2:],
                 good[:good.index("--series")] + ["--series"] + good[good.index("--series") + 2:],             # --series without the master's id
                 good + ["--spec-file", "x"], good[:-1],                                                        # neither mode
                 delete_args(etag, mode="--dry-run") + ["--expect-start", "2099-03-09T07:00:00-03:00"],
                 ["event-delete", "--calendar", fgw.CALENDAR, "--event", "ser0001", "--series", "ser0001", "--base-etag", etag, "--idempotency-key", KEY, "--dry-run"],      # a switch: no value
                 ["event-get", "--calendar", fgw.CALENDAR, "--event", "ser0001", "--series"],
                 ["event-patch", "--calendar", fgw.CALENDAR, "--event", "ser0001", "--base-etag", etag, "--spec-file", spec_file(tmp_path, {"title": "x"}),
                  "--idempotency-key", KEY, "--series", "--dry-run"]):
        assert run(fake, tmp_path, state, *args).returncode == 2, args
    assert fake.requests == []


# --- the allow-list ---------------------------------------------------------------------------------------------------------------------------------------


def load_writer():
    spec = importlib.util.spec_from_file_location("google_calendar_writer_under_test_series", WRITER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_allow_list_gains_one_instances_read_and_no_delete_and_the_series_verbs_use_only_pairs_of_it(fake):
    writer = load_writer()
    assert [p for p in writer.ALLOWED if p[0] == "DELETE"] == [("DELETE", r"/calendar/v3/calendars/[^/]+/events/[^/]+")]
    assert [p for p in writer.ALLOWED if "instances" in p[1]] == [("GET", r"/calendar/v3/calendars/[^/]+/events/[^/]+/instances")]
    assert len(writer.ALLOWED) == 7 and sorted({m for m, _ in writer.ALLOWED}) == ["DELETE", "GET", "PATCH", "POST"]
    sent_to = []
    writer.http = lambda *a: sent_to.append(a)
    for entry, path in ((writer.REMOVE, "/calendar/v3/calendars/a/events/b/instances"), (writer.PATCH, "/calendar/v3/calendars/a/events/b/instances"),
                        (writer.INSERT, "/calendar/v3/calendars/a/events/b/instances"), (writer.INSTANCES, "/calendar/v3/calendars/a/events/b"),
                        (writer.INSTANCES, "/calendar/v3/calendars/a/events/b/instances/c"), (("POST", r"/calendar/v3/calendars/[^/]+/events/[^/]+/instances"),
                                                                                             "/calendar/v3/calendars/a/events/b/instances"),
                        (("PUT", r"/calendar/v3/calendars/[^/]+/events/[^/]+"), "/calendar/v3/calendars/a/events/b")):
        with pytest.raises(writer.ProviderError) as why:
            writer.request(entry, fake.base, "token", path, {}, {})
        assert why.value.code == 2, (entry, path)
    assert sent_to == []
    writer.request(writer.INSTANCES, fake.base, "token", "/calendar/v3/calendars/a/events/b/instances", {}, {})      # vacuity: the pair of the list reaches the connection
    assert len(sent_to) == 1


def test_no_run_of_any_series_verb_sends_a_request_outside_the_list_or_a_second_delete(fake, tmp_path, state):
    master, instances = a_series(fake)
    out(run(fake, tmp_path, state, *cancel_args(instances[0]["etag"], event="ser0001_0", start=START, key=KEY + "o")))
    out(run(fake, tmp_path, state, *instances_args("2099-03-02T00:00:00-03:00", "2099-03-04T00:00:00-03:00")))
    out(run(fake, tmp_path, state, "event-get", "--calendar", fgw.CALENDAR, "--event", "ser0001_1"))
    out(run(fake, tmp_path, state, *delete_args(master["etag"], key=KEY + "s")))
    assert fake.unexpected() == []
    assert [m for m, _ in sent(fake) if m == "DELETE"] == ["DELETE"] and [p for m, p in sent(fake) if m == "DELETE"] == [f"{EVENTS}/ser0001"]
    assert not [p for m, p in sent(fake) if m != "GET" and p.endswith("/instances")]


def test_vacuity_the_rrule_oracle_catches_an_end_an_interval_and_a_month_day():
    assert forbidden_in_rrule({"recurrence": ["RRULE:FREQ=DAILY;COUNT=3"]}) == ["COUNT=3"]
    assert forbidden_in_rrule({"recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=MO;UNTIL=20991231T000000Z", "RRULE:FREQ=DAILY;INTERVAL=2;BYMONTHDAY=3"]}) == \
        ["UNTIL=20991231T000000Z", "INTERVAL=2", "BYMONTHDAY=3"]
    assert forbidden_in_rrule({"recurrence": [WEEKLY_RULE]}) == [] and re.fullmatch(r"RRULE:FREQ=(DAILY|WEEKLY;BYDAY=(MO|TU|WE|TH|FR|SA|SU))", WEEKLY_RULE)
