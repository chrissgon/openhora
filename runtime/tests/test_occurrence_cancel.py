"""The cancel of ONE occurrence of a daily or weekly series, and which of the occurrence and the whole series a line asks for (package CB-7, runtime/event_series.py, runtime/recurrence.py,
runtime/step_calendar_event.py, runtime/calendar_document.py and runtime/effect_calendar.py; limits L54, L55, L56, L57 and L61).

The maintainer decided on 2026-10-27 ("Entra") that a line may cancel one occurrence: the occurrence is the one instance the PROVIDER lists for the day the person's words name (read by the time
engine, never the model's time), the card names its date and time as the provider has them and says that the series stays, and the approval sends one request on the instance's id and none on
the master. The world, the clock (Tuesday 2026-11-03 10:00 at -03:00), the calendar source and the way a line is carried out are those of test_series_cancel.py. Every expectation is a literal
of this file; each oracle that can pass wrongly has a vacuity case that plants the wrong result. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_occurrence_cancel.py
"""
from __future__ import annotations

import datetime
import json

import pytest

import standin_tree as st
from test_series_cancel import (EVENTS, GRAPH_DAILY, GRAPH_MASTER, MASTER, TITLE, approve, body_lines, cancel, carry, event_series, google_series, google_writes, graph_series,  # noqa: F401
                                graph_writes, nothing_started, no_card, op_text, ops, text_of, world)

effect_calendar = st.load("effect_calendar")
ops_step_seams = st.load("ops_step_seams")

DAILY = "RRULE:FREQ=DAILY"
DAILY_FIRST, DAILY_LAST = "2026-11-03T07:00:00-03:00", "2026-11-03T08:00:00-03:00"      # a daily series that began today at 07:00 (already started at 10:00)
RULE_MO = text_of("RECUR_RULE_WEEKLY_MO", time="07:00")


def weekly(world, monkeypatch, **more):
    return google_series(world, monkeypatch, **more)      # Mondays 07:00: gymmaster_0 is 02/11 (past), _1 is 09/11, _2 is 16/11, _3 is 23/11


def daily(world, monkeypatch, days=5):
    return google_series(world, monkeypatch, rule=DAILY, days=days, first=DAILY_FIRST, last=DAILY_LAST)      # gymmaster_0 is today 03/11 (started), _1 is 04/11 ...


def assert_card(world, extras, instance, when, time_text="07:00-08:00"):
    lines = body_lines(world, extras)
    assert lines[0].startswith("Code cancels only this one occurrence after your approval, and nothing else."), lines[0]
    for wanted in (f"Event: {instance}", f"The event now is at: {when} {time_text} (America/Sao_Paulo)", "The rest of the series stays as it is.", "Repeats: every Monday, no end date"
                   if "Mon" in when else "Repeats: every day, no end date", "The event now: Academia teste"):
        assert wanted in lines, (wanted, lines)
    assert f"Event: {MASTER}" not in lines, "the card is of the instance, never of the master"


# --- one occurrence, by the words that say so ---------------------------------------------------------------------------------------------------


def test_next_monday_opens_the_card_of_that_one_instance_and_the_approval_sends_one_patch_of_it_and_nothing_on_the_master(world, monkeypatch):
    master, instances = weekly(world, monkeypatch)
    before = {i["id"]: dict(i) for i in instances}
    reply, extras = cancel(world, "cancela só a academia teste da próxima segunda", target="academia teste", day="da próxima segunda")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1), reply
    assert_card(world, extras, "gymmaster_1", "Mon 09/11/2026")
    assert google_writes(world) == [], "a card is opened; the approval writes"
    assert approve(world, {"pending": extras["resend"]})["task_state"] == "done"
    sent = google_writes(world)
    assert [(m, p) for m, p, _, _ in sent] == [("PATCH", f"{EVENTS}/gymmaster_1")], "exactly one request, on the instance's id, none on the master"
    assert set(sent[0][3]) == {"status", "extendedProperties"} and sent[0][3]["status"] == "cancelled", "nothing but the status and the key can be in the body"
    assert world["google"].events["gymmaster_1"]["status"] == "cancelled"
    assert all(world["google"].events[i]["status"] == "confirmed" for i in ("gymmaster_0", "gymmaster_2", "gymmaster_3")) and world["google"].events[MASTER]["etag"] == master["etag"]
    assert world["google"].removed == {}, "L57: nothing was removed: no DELETE, the series stays"
    assert before["gymmaster_2"]["etag"] == world["google"].events["gymmaster_2"]["etag"], "no other instance was touched"


@pytest.mark.parametrize("line,slots,instance,when", [
    ("cancela só a academia teste de 16/11", {"target": "academia teste", "day": "16/11"}, "gymmaster_2", "Mon 16/11/2026"),      # validate: allow english-only -- the Portuguese lines under test
    ("cancela só a academia teste dia 23", {"target": "academia teste", "day": "dia 23"}, "gymmaster_3", "Mon 23/11/2026"),      # validate: allow english-only -- the Portuguese lines under test
    ("cancela a academia teste dessa semana", {"target": "academia teste"}, "gymmaster_1", "Mon 09/11/2026"),      # validate: allow english-only -- the Portuguese lines under test
    ("cancela só a academia teste", {"target": "academia teste", "day": "16/11"}, "gymmaster_2", "Mon 16/11/2026"),      # validate: allow english-only -- the Portuguese lines under test
])
def test_a_date_or_a_range_or_a_word_for_one_time_names_the_one_instance_the_provider_lists(world, monkeypatch, line, slots, instance, when):
    weekly(world, monkeypatch)
    if line == "cancela só a academia teste":      # validate: allow english-only -- the Portuguese line under test
        line = "cancela só a academia teste de 16/11"      # validate: allow english-only -- the Portuguese line under test
    reply, extras = cancel(world, line, **slots)
    assert reply == text_of("ACCT_CARD_SENT", pending=1), (line, reply)
    assert_card(world, extras, instance, when)


def test_a_daily_series_and_tomorrow_open_the_card_of_tomorrows_instance(world, monkeypatch):
    daily(world, monkeypatch)
    reply, extras = cancel(world, "cancela a academia teste de amanhã", target="academia teste", day="amanhã")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1), reply
    assert_card(world, extras, "gymmaster_1", "Wed 04/11/2026")
    assert approve(world, {"pending": extras["resend"]})["task_state"] == "done"
    assert [(m, p) for m, p, _, _ in google_writes(world)] == [("PATCH", f"{EVENTS}/gymmaster_1")]


def test_a_daily_series_over_this_week_lists_the_days_in_words_and_opens_no_card(world, monkeypatch):
    daily(world, monkeypatch)
    reply, extras = cancel(world, "cancela a academia teste dessa semana", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("RECUR_WHICH_DAY", title=TITLE, days="Wed 04/11, Thu 05/11, Fri 06/11, Sat 07/11", example="Wed 04/11") and nothing_started(world) and "resend" not in extras


def test_a_day_with_no_event_in_the_snapshot_is_the_lookups_own_sentence_and_one_the_provider_moved_away_from_is_ours(world, monkeypatch):
    weekly(world, monkeypatch)
    reply, _ = cancel(world, "cancela só a academia teste de 17/11", target="academia teste", day="17/11")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("EV_NAME_NONE_DAY", days=30) and nothing_started(world), "17/11 is a Tuesday: the series is on Mondays, the snapshot has no event that day"
    world["google"].events["gymmaster_2"]["start"], world["google"].events["gymmaster_2"]["end"] = {"dateTime": "2026-11-17T07:00:00-03:00"}, {"dateTime": "2026-11-17T08:00:00-03:00"}
    reply, _ = cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("RECUR_NO_OCCURRENCE", title=TITLE, day="Mon 16/11") and nothing_started(world), "the snapshot lists it on 16/11, the provider holds it on 17/11 now: no instance that day"


def test_an_instance_that_has_started_is_not_cancelled(world, monkeypatch):
    daily(world, monkeypatch)
    reply, _ = cancel(world, "cancela só a academia teste de hoje", target="academia teste", day="hoje")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("RECUR_OCCURRENCE_PAST", title=TITLE) and nothing_started(world), "today's instance began at 07:00 and it is 10:00"


def test_a_word_for_one_time_and_no_day_asks_the_date_and_opens_no_card(world, monkeypatch):
    weekly(world, monkeypatch)
    reply, _ = cancel(world, "cancela só a academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("RECUR_ASK_DATE", title=TITLE, example="Mon 09/11") and nothing_started(world), "a date the line does not say is a question, never a guess"


def test_an_instance_the_provider_already_cancelled_opens_no_card(world, monkeypatch):
    weekly(world, monkeypatch)
    world["google"].events["gymmaster_2"]["status"] = "cancelled"
    reply, _ = cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    assert "not on this calendar any more" in reply and no_card(world) and google_writes(world) == [], "the provider answers that the event is gone: the preparation's own sentence, no card"


# --- the date is the engine's and the instance is the provider's, never a model's ------------------------------------------------------------------


def test_a_time_the_model_wrote_for_another_day_changes_nothing_the_date_is_the_engines(world, monkeypatch):
    weekly(world, monkeypatch)
    line = "cancela só a academia teste de 16/11"      # validate: allow english-only -- the Portuguese line under test
    reply, extras = carry(world, line, op_text("event-cancel", {"target": "academia teste", "day": "16/11"}, time_iso="2026-11-30T07:00", weekday="mon"))
    assert reply == text_of("ACCT_CARD_SENT", pending=1)
    assert_card(world, extras, "gymmaster_2", "Mon 16/11/2026")


def test_vacuity_with_the_day_taken_from_a_model_made_date_the_instance_is_missed(world, monkeypatch):
    weekly(world, monkeypatch)
    monkeypatch.setattr(event_series, "_days_asked", lambda said, spans, kind, value, now: [datetime.date(2026, 11, 17)])      # a model-made date, in a copy: the oracles above must fail on it
    reply, _ = cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("RECUR_NO_OCCURRENCE", title=TITLE, day="Tue 17/11"), "the instance of 16/11 is missed"


def test_the_card_shows_the_instance_as_the_provider_has_it_even_when_the_line_says_another_hour(world, monkeypatch):
    weekly(world, monkeypatch)
    _, extras = cancel(world, "cancela só a academia teste de 16/11 às 9h", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    lines = body_lines(world, extras)
    assert "The event now is at: Mon 16/11/2026 07:00-08:00 (America/Sao_Paulo)" in lines and not [l for l in lines if "09:00" in l], lines


def test_an_instance_moved_by_hand_is_cancelled_at_its_own_time_and_the_card_shows_that_time(world, monkeypatch):
    weekly(world, monkeypatch)
    moved = world["google"].events["gymmaster_2"]
    moved["start"], moved["end"] = {"dateTime": "2026-11-16T08:30:00-03:00"}, {"dateTime": "2026-11-16T09:30:00-03:00"}
    _, extras = cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    assert "The event now is at: Mon 16/11/2026 08:30-09:30 (America/Sao_Paulo)" in body_lines(world, extras)
    assert approve(world, {"pending": extras["resend"]})["task_state"] == "done"
    assert [(m, p) for m, p, _, _ in google_writes(world)] == [("PATCH", f"{EVENTS}/gymmaster_2")]


def test_an_instance_that_moved_after_the_card_is_stale_nothing_is_written(world, monkeypatch):
    weekly(world, monkeypatch)
    _, extras = cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    world["google"].events["gymmaster_2"]["etag"] = '"moved"'
    with pytest.raises(ops.OpsError) as stale:
        approve(world, {"pending": extras["resend"]})
    assert "another version" in str(stale.value) and google_writes(world) == [] and world["google"].events["gymmaster_2"]["status"] == "confirmed"


def test_an_instance_that_started_at_another_time_after_the_card_is_stale_even_with_the_same_version(world, monkeypatch):
    weekly(world, monkeypatch)
    _, extras = cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    world["google"].events["gymmaster_2"]["start"] = {"dateTime": "2026-11-16T09:00:00-03:00"}      # the version is the card's; the time is not: the writer's own check or ours refuses
    with pytest.raises(ops.OpsError):
        approve(world, {"pending": extras["resend"]})
    assert google_writes(world) == []


# --- typed, the two requests of one approval, and Outlook ---------------------------------------------------------------------------------------


def test_the_typed_occurrence_flag_takes_a_day_and_finds_the_instance_of_the_series_the_reference_belongs_to(world, monkeypatch):
    weekly(world, monkeypatch)
    started = ops.event_cancel(world["path"], "google", "agenda#1", occurrence="2026-11-16")
    assert "Event: gymmaster_2" in ops.pending(world["path"], started["pending"])["body"].splitlines(), "agenda#1 is the 09/11 instance: the day named is another one of the same series"
    with pytest.raises(ops.OpsError) as none:
        ops.event_cancel(world["path"], "google", "agenda#1", occurrence="2026-11-17")
    assert "no occurrence on that day" in str(none.value)
    with pytest.raises(ops.OpsError) as past:
        ops.event_cancel(world["path"], "google", "agenda#1", occurrence="2026-11-02")
    assert "already started" in str(past.value)
    with pytest.raises(ops.OpsError):
        ops.event_cancel(world["path"], "google", "agenda#1", occurrence="16/11")      # a day is YYYY-MM-DD


def test_the_dry_run_and_the_confirmed_run_of_an_occurrence_cancel_carry_the_same_flags_with_the_series_and_the_start(world, monkeypatch):
    weekly(world, monkeypatch)
    _, extras = cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    seen = []
    real = world["resolver"].call

    def spy(cls, verb, args, **kw):
        seen.append((verb, list(args)))
        return real(cls, verb, args, **kw)
    monkeypatch.setattr(world["resolver"], "call", spy)
    approve(world, {"pending": extras["resend"]})
    writes = [(verb, args) for verb, args in seen if "--dry-run" in args or "--confirmed" in args]
    assert [(v, a[-1]) for v, a in writes] == [("event-cancel-occurrence", "--dry-run"), ("event-cancel-occurrence", "--confirmed")], writes
    assert writes[0][1][:-1] == writes[1][1][:-1]
    flags = writes[0][1]
    assert flags[flags.index("--event") + 1] == "gymmaster_2" and flags[flags.index("--series") + 1] == MASTER, "the instance's id for the event, the master's for the series"
    assert flags[flags.index("--expect-start") + 1] == "2026-11-16T07:00:00-03:00"


def test_an_outlook_occurrence_is_cancelled_by_the_cancel_action_on_the_occurrence_with_an_empty_body_and_the_master_is_untouched(world, monkeypatch):
    graph_series(world, monkeypatch)
    reply, extras = cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1), reply
    lines = body_lines(world, extras)
    assert lines[0].startswith("Code cancels only this one occurrence after your approval") and "Outlook moves it to Deleted Items" in lines[0], lines[0]
    assert "The event now is at: Mon 16/11/2026 07:00-08:00 (America/Sao_Paulo)" in lines and "The rest of the series stays as it is." in lines
    assert approve(world, {"pending": extras["resend"]})["task_state"] == "done"
    sent = graph_writes(world)
    assert [(m, p.rsplit("/events/", 1)[1], b) for m, p, b in sent] == [("POST", "AAMkGym00001Occ2=/cancel", {})], sent
    assert GRAPH_MASTER in world["graph"].events and "AAMkGym00001Occ2=" in world["graph"].removed and "AAMkGym00001Occ1=" in world["graph"].events, "only that occurrence went"
    assert not [m for m, _, _ in sent if m == "DELETE"], "L57: no DELETE"


def test_an_outlook_daily_series_and_tomorrow_open_the_card_of_tomorrows_occurrence(world, monkeypatch):
    graph_series(world, monkeypatch, pattern=GRAPH_DAILY, step=1, first="2026-11-03T10:00:00", last="2026-11-03T11:00:00", days=4)
    reply, extras = cancel(world, "cancela a academia teste de amanhã", target="academia teste", day="amanhã")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1), reply
    assert "The event now is at: Wed 04/11/2026 07:00-08:00 (America/Sao_Paulo)" in body_lines(world, extras)


def test_the_seam_starts_only_the_two_reads_with_the_token_and_a_write_verb_only_as_a_dry_run_while_a_card_is_prepared(world, monkeypatch):
    weekly(world, monkeypatch)
    assert ops_step_seams.CALENDAR_READ_VERBS == ("event-get", "event-instances")
    seen = []
    real = effect_calendar.provider_call

    def spy(root, implementation, verb, args, secrets=(), timeout=0):
        seen.append((verb, tuple(secrets), "--dry-run" in args, "--confirmed" in args))
        return real(root, implementation, verb, args, secrets, timeout or 60)
    monkeypatch.setattr(effect_calendar, "provider_call", spy)
    cancel(world, "cancela só a academia teste de 16/11", target="academia teste", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert {"event-get", "event-instances", "event-cancel-occurrence", "event-delete"} <= {v for v, _, _, _ in seen}
    for verb, secrets, dry, confirmed in seen:
        assert not confirmed, "no card is approved: nothing is confirmed"
        assert (verb in ("event-get", "event-instances") and secrets == ("GOOGLE_ACCOUNT_TOKEN",)) or (dry and secrets == ()), (verb, secrets, dry)
    assert google_writes(world) == []
