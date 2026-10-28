"""The cancel of a whole daily or weekly series, and what a line may and may not say about a series (package CB-7, runtime/recurrence.py, runtime/event_series.py, runtime/event_lookup.py,
runtime/step_calendar_event.py, runtime/calendar_document.py and runtime/effect_calendar.py; limits L54, L55, L56, L57, L58 and L61).

The maintainer decided on 2026-10-27 ("Criar e cancelar") that a line may cancel a whole series, never change one and never delete one for good. Here the real calendar world of
test_calendar_write.py (the real writers, started as processes, against the stand-in Google Calendar and Microsoft Graph), a stand-in clock (Tuesday 2026-11-03 10:00 at -03:00), the real
snapshots of a calendar source `agenda` whose events are the instances of one weekly series on Mondays at 07:00, the real family path and the real card; a line is carried out through the
real seam from a hand-written model text, so no model is asked. Every expectation is a literal of this file (the sentences by phrase key, the cards by their own lines, the requests as the
stand-in recorded them); each oracle that can pass wrongly has a vacuity case that plants the wrong result. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_series_cancel.py
"""
from __future__ import annotations

import datetime
import json

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, approve, fgc, fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_items = st.load("ops_items")
ops_steps = st.load("ops_steps")
ops_natural = st.load("ops_natural")
turn_gate = st.load("turn_gate")
phrases = st.load("phrases")
recurrence = st.load("recurrence")
event_series = st.load("event_series")
event_lookup = st.load("event_lookup")
step_calendar_event = st.load("step_calendar_event")
calendar_document = st.load("calendar_document")
messaging_cards = st.load("messaging_cards")

OWNER = "telegram:830461975213"
PROFILES = {"owner": ["read", "talk", "calendar-write", "ask-mail", "interpret"]}
UTC = datetime.timezone.utc
ZONE = "America/Sao_Paulo"
ALLOWED = {"event-cancel", "event-change", "event-create"}
TITLE = "Academia teste"
MASTER = "gymmaster"                 # Google's series master
GRAPH_MASTER = "AAMkGym00001="       # Graph's series master
FIRST = "2026-11-02T07:00:00-03:00"  # a Monday, the first occurrence of the series, already past on Tuesday 2026-11-03
LAST = "2026-11-02T08:00:00-03:00"
WEEKLY_MONDAY = "RRULE:FREQ=WEEKLY;BYDAY=MO"
GRAPH_WEEKLY = {"type": "weekly", "interval": 1, "daysOfWeek": ["monday"], "firstDayOfWeek": "sunday"}
GRAPH_DAILY = {"type": "daily", "interval": 1}
EVENTS = fgw.EVENTS_PREFIX
GRAPH_EVENTS = "/v1.0/me/calendar/events"


def text_of(key, **fields):
    return phrases.text(key, {"language": "pt-BR"}, **fields)


def op_text(name, slots=None, **more):
    return json.dumps({"v": 1, "kind": "op", "op": name, "slots": slots or {}, **more}, ensure_ascii=False)


def configure(world, language="pt-BR"):
    """The project's configuration: the language, one listed sender with the groups `calendar-write`, `ask-mail` (it may read a snapshot) and `interpret`, accepted."""
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw.update(language=language, policies=PROFILES, channels={"page": ["read", "calendar-write"]},
               messaging={"senders": {"telegram": [{"id": "830461975213", "policy": "owner"}]}})
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def clock_and_snapshots(world, monkeypatch, wall="2026-11-03 10:00"):
    """The clock of the world, by default Tuesday 2026-11-03 10:00 at -03:00; `wall` moves it (the snapshots and the step's preparation read the same moment)."""
    clock = Clock(monkeypatch, wall=wall)
    snaps = Snapshots(world, monkeypatch)
    moment = datetime.datetime.strptime(wall, "%Y-%m-%d %H:%M").replace(tzinfo=UTC) + datetime.timedelta(hours=3)
    snaps.now = moment
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: snaps.now)
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    monkeypatch.setattr(ops_steps, "_now", lambda: moment.isoformat())      # the clock of a step's preparation (it reads an instance's start against it): the same moment
    world["clock"], world["snaps"] = clock, snaps
    return snaps


def google_series(world, monkeypatch, rule=WEEKLY_MONDAY, days=4, first=FIRST, last=LAST, wall="2026-11-03 10:00", title=TITLE, **more):
    """A Google series in the stand-in provider (master `gymmaster`, instances `gymmaster_0`..), a calendar source `agenda` listing the instances from today on (a snapshot is a window
    that starts today; the instances it lists are `recurring`), and the clock. Returns (master, [instances])."""
    configure(world)
    snaps = clock_and_snapshots(world, monkeypatch, wall)
    master, instances = world["google"].add_series(MASTER, title, first, last, rule=rule, days=days, **more)
    listed = [i for i in instances if i["start"]["dateTime"][:10] >= wall[:10]]
    snaps.calendar("agenda", "google", fgw.CALENDAR, [tsm.event(n + 1, i["start"]["dateTime"], i["end"]["dateTime"], title, id=i["id"], recurring=True) for n, i in enumerate(listed)])
    return master, instances


def graph_series(world, monkeypatch, pattern=GRAPH_WEEKLY, days=4, step=7, first="2026-11-02T10:00:00", last="2026-11-02T11:00:00", **more):
    """A Graph series (master `AAMkGym00001=`, occurrences `AAMkGym0000Occ<n>=`, times in UTC as Graph prints them) and a calendar source `agenda` on Outlook listing from today on."""
    configure(world)
    snaps = clock_and_snapshots(world, monkeypatch)
    master, occurrences = world["graph"].add_series(GRAPH_MASTER, TITLE, first, last, pattern=pattern, days=days, step=step, **more)
    listed = [i for i in occurrences if i["start"]["dateTime"][:10] >= "2026-11-03"]
    snaps.calendar("agenda", "outlook", "default", [tsm.event(n + 1, i["start"]["dateTime"][:19] + "Z", i["end"]["dateTime"][:19] + "Z", TITLE, id=i["id"], recurring=True)
                                                       for n, i in enumerate(listed)])
    return master, occurrences


def decide(line, text):
    got = ops_interpret.decide(line, text, ops_natural._clock(), ZONE, ALLOWED)
    assert got["kind"] == "op", got
    return got


def carry(world, line, text, sender=OWNER):
    """(the reply, extras) of the decision a model text makes for the line, carried out through the real seam."""
    ctx = ops_core.context(world["path"])
    extras = {}
    with turn_gate.turn():
        got = ops_interpret._carry_out(world["path"], ctx, decide(line, text), line, sender, extras)
    return got[0], extras


def cancel(world, line, **slots):
    """What a model says for a cancel by words: the op `event-cancel` with the slots given (target, day)."""
    return carry(world, line, op_text("event-cancel", slots))


def body_lines(world, extras):
    return ops.pending(world["path"], extras["resend"])["body"].splitlines()


def google_writes(world):
    return world["google"].writes()


def graph_writes(world):
    return [(r["method"], r["path"], r["body"]) for r in world["graph"].graph_requests() if r["method"] != "GET"]


def no_card(world):
    """No decision is open (a preparation that is refused leaves a cancelled task behind, never a card)."""
    return rows(world)[1] == []


def nothing_started(world):
    """No task and no decision at all: a line answered before any preparation."""
    return rows(world) == ([], [])


# --- the whole series ---------------------------------------------------------------------------------------------------------------------------


def test_a_line_that_says_the_series_opens_one_card_of_the_series_and_the_approval_sends_one_delete_of_the_master(world, monkeypatch):
    google_series(world, monkeypatch)
    reply, extras = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1)
    lines = body_lines(world, extras)
    assert lines[0].startswith("Code cancels the whole series after your approval: every occurrence leaves the calendar."), "the card says in words that it is the whole series"
    for wanted in ("Repeats: every Monday, no end date", "The series began at: Mon 02/11/2026 07:00-08:00 (America/Sao_Paulo)", "The event now: Academia teste",
                   "Account: google (pat@example.com)", f"Event: {MASTER}"):
        assert wanted in lines, (wanted, lines)
    assert not [l for l in lines if "gymmaster_" in l], "no instance's id is on the card: it is the series' own"
    assert google_writes(world) == [], "a card is opened; the approval writes"
    done = approve(world, {"pending": extras["resend"]})
    assert done["task_state"] == "done"
    assert [(m, p, q, b) for m, p, q, b in google_writes(world)] == [("DELETE", f"{EVENTS}/{MASTER}", {"sendUpdates": "none"}, None)], "exactly one request, on the master's id"
    assert set(world["google"].removed) == {MASTER, "gymmaster_0", "gymmaster_1", "gymmaster_2", "gymmaster_3"} and world["google"].events == {}, "the stand-in takes the whole series with its master"



SERIES_LINES = [("cancela a série academia teste", "academia teste"), ("cancela todas as academias teste", "academias teste"),      # validate: allow english-only -- the Portuguese lines under test
                ("cancela de vez a academia teste", "academia teste"), ("cancela a academia teste toda segunda", "academia teste")]      # validate: allow english-only -- the Portuguese lines under test


@pytest.mark.parametrize("line,target", SERIES_LINES)
def test_the_series_words_open_the_card_of_the_series_and_never_of_one_occurrence(world, monkeypatch, line, target):
    google_series(world, monkeypatch)
    reply, extras = cancel(world, line, target=target)
    lead = text_of("RECUR_FOUND_SERIES", title=TITLE, rule=text_of("RECUR_RULE_WEEKLY_MO", time="07:00")) + "\n" if target == "academias teste" else ""      # a name that is near, not the same: the person is shown which series it is
    assert reply == lead + text_of("ACCT_CARD_SENT", pending=1), (line, reply)
    lines = body_lines(world, extras)
    assert lines[0].startswith("Code cancels the whole series after your approval") and "Repeats: every Monday, no end date" in lines and f"Event: {MASTER}" in lines, lines
    assert google_writes(world) == []


ASKED = [("cancela a academia teste", "academia teste"), ("cancela a academia de segunda", "academia"),      # validate: allow english-only -- the Portuguese lines under test
         ("cancela só a série toda da academia teste", "academia teste"), ("cancela a academia teste de vez só essa vez", "academia teste")]      # validate: allow english-only -- the Portuguese lines under test


@pytest.mark.parametrize("line,target", ASKED)
def test_a_line_with_both_kinds_of_words_or_neither_or_a_bare_weekday_asks_which_and_opens_no_card(world, monkeypatch, line, target):
    google_series(world, monkeypatch)
    reply, extras = cancel(world, line, target=target)
    assert reply == text_of("RECUR_WHICH", title=TITLE, rule=text_of("RECUR_RULE_WEEKLY_MO", time="07:00"), example="Mon 09/11"), (line, reply)
    assert nothing_started(world) and google_writes(world) == [] and "resend" not in extras, "no card, no memory: the next line is read on its own words"
    assert extras["stored"] == text_of("NW_PRIVATE_REPLY"), "the reply holds a title of the person's own calendar: the conversation keeps a neutral word"


def test_vacuity_with_the_ask_rule_taken_out_the_plain_line_opens_a_card(world, monkeypatch):
    google_series(world, monkeypatch)
    monkeypatch.setattr(recurrence, "which", lambda text, specific: "series")      # the rule removed in a copy: the oracle above must fail on it
    reply, extras = cancel(world, "cancela a academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1) and not no_card(world)


def test_a_series_that_is_not_a_plain_daily_or_weekly_one_gets_one_sentence_and_no_card(world, monkeypatch):
    google_series(world, monkeypatch, rule="RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO")
    reply, _ = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("RECUR_CANCEL_NOT_SIMPLE") and nothing_started(world)


@pytest.mark.parametrize("more", [{"organizer": {"email": "boss@example.com", "self": False}}, {"attendees": [{"email": "sam@example.com"}]}], ids=["another-organizer", "another-attendee"])
def test_a_series_the_person_does_not_organize_alone_gets_no_card_a_cancel_would_tell_the_guests(world, monkeypatch, more):
    google_series(world, monkeypatch, **more)
    reply, _ = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("RECUR_CANCEL_NOT_SIMPLE") and nothing_started(world) and google_writes(world) == []


def test_a_master_that_moved_after_the_card_is_stale_nothing_is_written_and_the_task_starts_over(world, monkeypatch):
    google_series(world, monkeypatch)
    _, extras = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    world["google"].events[MASTER]["etag"] = '"moved"'
    with pytest.raises(ops.OpsError) as stale:
        approve(world, {"pending": extras["resend"]})
    assert "another version" in str(stale.value) and "starts over" in str(stale.value)
    assert google_writes(world) == [] and MASTER in world["google"].events and world["google"].removed == {}


# --- a series is never changed, and no other verb reaches it ---------------------------------------------------------------------------------


def test_a_change_of_a_series_is_refused_in_a_plain_sentence_and_opens_no_card(world, monkeypatch):
    google_series(world, monkeypatch)
    reply, extras = carry(world, "muda a academia teste para as 8h", op_text("event-change", {"target": "academia teste", "time": "as 8h"}, time_iso="2026-11-04T08:00", weekday="wed"))      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("RECUR_CHANGE_REFUSED") and nothing_started(world) and "resend" not in extras and google_writes(world) == []
    assert reply == "Ainda não consigo mudar um evento que se repete. Você pode mudar a série no app da agenda, ou me pedir para cancelar a série inteira."      # validate: allow english-only -- the Portuguese sentence under test


@pytest.mark.parametrize("call", [lambda w: ops.event_cancel(w["path"], "google", "agenda#1"), lambda w: ops.event_change(w["path"], "google", "agenda#1", title="New name")],
                         ids=["plain-cancel", "change"])
def test_a_plain_cancel_or_a_change_of_an_event_of_a_series_is_refused_by_the_preparation(world, monkeypatch, call):
    google_series(world, monkeypatch)
    with pytest.raises(ops.OpsError) as refused:
        call(world)
    assert "this event repeats" in str(refused.value) and no_card(world) and google_writes(world) == []


def test_vacuity_with_the_series_check_taken_out_a_plain_cancel_opens_on_a_series(world, monkeypatch):
    google_series(world, monkeypatch)
    monkeypatch.setattr(step_calendar_event, "_eligible", lambda event, series=False: None)      # the check removed in a copy: the oracle above must fail on it
    started = ops.event_cancel(world["path"], "google", "agenda#1")
    assert started["pending"] and not no_card(world)


def test_the_typed_series_flag_opens_the_same_card_and_names_the_series_master_not_the_instance(world, monkeypatch):
    google_series(world, monkeypatch)
    started = ops.event_cancel(world["path"], "google", "agenda#1", series=True)
    lines = ops.pending(world["path"], started["pending"])["body"].splitlines()
    assert f"Event: {MASTER}" in lines and lines[0].startswith("Code cancels the whole series"), "agenda#1 is an instance of the series (gymmaster_1): the card is of the master"
    with pytest.raises(ops.OpsError):
        ops.event_cancel(world["path"], "google", "agenda#1", series=True, occurrence="2026-11-09")      # one or the other, never both


def test_an_event_that_is_not_part_of_a_series_is_not_cancelled_as_one(world, monkeypatch):
    google_series(world, monkeypatch)
    world["google"].add_event("evsingle", "Dentist", {"dateTime": "2026-11-10T09:00:00-03:00"}, {"dateTime": "2026-11-10T10:00:00-03:00"})
    world["snaps"].calendar("agenda", "google", fgw.CALENDAR, [tsm.event(1, "2026-11-10T09:00:00-03:00", "2026-11-10T10:00:00-03:00", "Dentist", id="evsingle")])
    with pytest.raises(ops.OpsError) as refused:
        ops.event_cancel(world["path"], "google", "agenda#1", series=True)
    assert "not part of a series" in str(refused.value) and no_card(world)


def test_the_card_on_a_phone_says_the_whole_series_in_words_and_holds_no_id(world, monkeypatch):
    google_series(world, monkeypatch)
    _, extras = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    item = ops.pending(world["path"], extras["resend"])
    shown = messaging_cards.effect_card_text(item, {"language": "pt-BR"}, True, False, False)
    assert "série inteira" in shown and "toda segunda-feira" in shown and "Academia teste" in shown, shown      # validate: allow english-only -- the Portuguese words under test
    assert MASTER not in shown and "gymmaster" not in shown and "Evento:" not in shown, "no id is shown on a phone"      # validate: allow english-only -- the Portuguese word under test


# --- Outlook, the two requests of one approval, and a series the platform created --------------------------------------------------------------


def test_an_outlook_series_is_cancelled_by_the_cancel_action_on_the_master_with_an_empty_body_and_no_delete_is_ever_sent(world, monkeypatch):
    graph_series(world, monkeypatch)
    reply, extras = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1)
    lines = body_lines(world, extras)
    assert lines[0].startswith("Code cancels the whole series after your approval") and "Outlook moves it to Deleted Items" in lines[0], "the place a cancelled series goes is the account's own"
    assert "Repeats: every Monday, no end date" in lines and any(line.startswith("Account: microsoft") for line in lines), lines
    assert graph_writes(world) == []
    assert approve(world, {"pending": extras["resend"]})["task_state"] == "done"
    sent = graph_writes(world)
    assert [(m, p.rsplit("/events/", 1)[1], b) for m, p, b in sent] == [("POST", f"{GRAPH_MASTER}/cancel", {})], "one request: the cancel action on the master, with an empty body (no comment can carry a word)"
    assert not [m for m, _, _ in sent if m == "DELETE"], "L57: no DELETE for a series"
    assert GRAPH_MASTER in world["graph"].removed and world["graph"].events == {}, "the stand-in takes the occurrences with the master"


def test_the_dry_run_and_the_confirmed_run_of_a_series_cancel_carry_exactly_the_same_flags_built_from_the_approved_card(world, monkeypatch):
    google_series(world, monkeypatch)
    _, extras = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    seen = []
    real = world["resolver"].call

    def spy(cls, verb, args, **kw):
        seen.append((verb, list(args)))
        return real(cls, verb, args, **kw)
    monkeypatch.setattr(world["resolver"], "call", spy)
    approve(world, {"pending": extras["resend"]})
    writes = [(verb, args) for verb, args in seen if "--dry-run" in args or "--confirmed" in args]
    assert [(v, a[-1]) for v, a in writes] == [("event-delete", "--dry-run"), ("event-delete", "--confirmed")], writes
    assert writes[0][1][:-1] == writes[1][1][:-1], "the same flags before the mode"
    flags = writes[0][1]
    assert "--series" in flags and flags[flags.index("--event") + 1] == MASTER and "--base-etag" in flags, "Google's event-delete takes --series for a series master: the guard the dry run's hash covers"


def test_a_series_the_platform_created_is_found_by_its_name_and_cancelled_whole(world, monkeypatch):
    configure(world)
    clock_and_snapshots(world, monkeypatch)
    started = ops.event_create(world["path"], "google", TITLE, "2026-11-09T07:00", repeat="weekly", channel="messaging", sender=OWNER)
    assert approve(world, started)["task_state"] == "done"
    created = [(m, p, b.get("recurrence")) for m, p, _, b in google_writes(world) if m == "POST"]
    assert created == [("POST", EVENTS, ["RRULE:FREQ=WEEKLY;BYDAY=MO"])], "the series was written once, with its rule"
    reply, extras = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=2), reply
    assert body_lines(world, extras)[0].startswith("Code cancels the whole series after your approval")
    assert approve(world, {"pending": extras["resend"]})["task_state"] == "done"
    assert [m for m, _, _, _ in google_writes(world)] == ["POST", "DELETE"] and world["google"].events == {}, "the series the platform made is the series the platform removed"
    again, _ = cancel(world, "cancela a série academia teste", target="academia teste")      # validate: allow english-only -- the Portuguese line under test
    assert again != text_of("ACCT_CARD_SENT", pending=3), "a removed series is no longer an event of the platform's ledger"


# --- the event's own name is not the person's words (review of #626) ---------------------------------------------------------------------------


@pytest.mark.parametrize("title,line,target", [("Daily", "cancela a daily", "daily"), ("Weekly review", "cancela a weekly review", "weekly review"),
                                               ("Curso todos os santos", "cancela o curso todos os santos", "curso todos os santos")])      # validate: allow english-only -- the Portuguese lines under test
def test_a_series_whose_name_holds_a_series_word_is_asked_about_and_never_cancelled_whole_by_its_name(world, monkeypatch, title, line, target):
    google_series(world, monkeypatch, title=title)
    reply, extras = cancel(world, line, target=target)
    assert reply == text_of("RECUR_WHICH", title=title, rule=text_of("RECUR_RULE_WEEKLY_MO", time="07:00"), example="Mon 09/11"), reply
    assert nothing_started(world) and "resend" not in extras


def test_a_series_whose_name_holds_a_series_word_can_still_be_cancelled_by_one_occurrence_by_words(world, monkeypatch):
    google_series(world, monkeypatch, title="Daily")
    reply, extras = cancel(world, "cancela só a daily de 16/11", target="daily", day="16/11")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1), reply
    assert body_lines(world, extras)[0].startswith("Code cancels only this one occurrence"), "the name 'daily' does not make this the whole series"
    assert "Event: gymmaster_2" in body_lines(world, extras)


def test_a_series_whose_name_holds_a_series_word_is_cancelled_whole_when_the_person_says_so_beside_the_name(world, monkeypatch):
    google_series(world, monkeypatch, title="Daily")
    reply, extras = cancel(world, "cancela a série daily", target="daily")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1) and body_lines(world, extras)[0].startswith("Code cancels the whole series")


def test_vacuity_with_the_name_left_in_the_line_a_series_called_daily_is_cancelled_whole_by_its_name(world, monkeypatch):
    google_series(world, monkeypatch, title="Daily")
    monkeypatch.setattr(recurrence, "without", lambda text, *pieces: text)      # the name not taken out, in a copy: the oracles above must fail on it
    reply, extras = cancel(world, "cancela a daily", target="daily")      # validate: allow english-only -- the Portuguese line under test
    assert reply == text_of("ACCT_CARD_SENT", pending=1) and body_lines(world, extras)[0].startswith("Code cancels the whole series")


def test_the_master_that_has_a_guest_is_refused_on_the_typed_path_though_its_instances_show_none(world, monkeypatch):
    google_series(world, monkeypatch)
    world["google"].events[MASTER]["attendees"] = [{"email": "sam@example.com"}]      # a cancel of the series would tell Sam: only the master has the guest
    with pytest.raises(ops.OpsError) as refused:
        ops.event_cancel(world["path"], "google", "agenda#1", series=True)
    assert "other attendees" in str(refused.value) and no_card(world) and google_writes(world) == []
    with pytest.raises(ops.OpsError) as refused:
        ops.event_cancel(world["path"], "google", "agenda#1", occurrence="2026-11-16")
    assert "other attendees" in str(refused.value) and no_card(world) and google_writes(world) == []


def test_a_series_rule_that_is_not_plain_is_refused_on_the_typed_path(world, monkeypatch):
    google_series(world, monkeypatch, rule="RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=MO")
    for call in (lambda: ops.event_cancel(world["path"], "google", "agenda#1", series=True), lambda: ops.event_cancel(world["path"], "google", "agenda#1", occurrence="2026-11-16")):
        with pytest.raises(ops.OpsError) as refused:
            call()
        assert "plain daily or weekly" in str(refused.value) and no_card(world) and google_writes(world) == []


# --- the words a model put inside the target (CB-9, round 2) -------------------------------------------------------------------------------------
# The measurement of 2026-10-28 read the recorded answers of the product: `event_series` took every word of the target out of the line before it looked for the person's words, so a target
# that holds them ("aula de violao que se repete toda semana", "this week's piano lesson", "yoga de todo dia", "weekly piano lesson") lost them and the reply was a question. The words of the
# target that say series or occurrence now count, unless they stand in the event's own name.

MARKERS = [("aula de violão que se repete toda semana", "Aula de violão", "toda semana"), ("this week's piano lesson", "Piano lesson", "this week"),      # validate: allow english-only -- the Portuguese words under test
           ("yoga de todo dia", "Yoga", "todo dia"), ("weekly piano lesson", "Piano lesson", "weekly"), ("todas as aulas de natação", "Aula de natação", "todas"),      # validate: allow english-only -- the Portuguese words under test
           ("the daily meeting every day", "Daily", "every day")]


@pytest.mark.parametrize("target,title,wanted", MARKERS)
def test_the_series_or_occurrence_words_inside_a_target_are_the_persons_unless_they_stand_in_the_title(target, title, wanted):
    assert recurrence.markers(target, title) == wanted


@pytest.mark.parametrize("target,title", [("daily", "Daily"), ("weekly review", "Weekly review"), ("curso todos os santos", "Curso todos os santos"), ("the daily standup", "Daily standup"),
                                          ("", "Daily"), (None, "Daily")])
def test_the_words_of_the_events_own_title_never_count(target, title):
    assert recurrence.markers(target, title) == ""


def test_vacuity_without_the_title_the_same_words_count():
    assert recurrence.markers("daily", "Aula") == "daily" and recurrence.markers("curso todos os santos", "Aula") == "todos"


def test_a_target_that_says_weekly_opens_the_card_of_the_series(world, monkeypatch):
    google_series(world, monkeypatch, title="Piano lesson")
    reply, extras = cancel(world, "cancel my weekly piano lesson", target="weekly piano lesson")
    assert reply.endswith(text_of("ACCT_CARD_SENT", pending=1)), reply      # a name that is near, not the same, is shown first: "Encontrei a série ... É esta?"
    assert body_lines(world, extras)[0].startswith("Code cancels the whole series after your approval") and f"Event: {MASTER}" in body_lines(world, extras)


def test_a_target_that_says_every_day_of_a_series_opens_the_card_of_the_series(world, monkeypatch):
    google_series(world, monkeypatch, title="Yoga")
    reply, extras = cancel(world, "tira da agenda a yoga todo dia", target="yoga todo dia")      # validate: allow english-only -- the Portuguese line under test
    assert reply.endswith(text_of("ACCT_CARD_SENT", pending=1)), reply
    assert body_lines(world, extras)[0].startswith("Code cancels the whole series after your approval")


def test_a_target_that_says_this_weeks_asks_for_the_instance_of_this_week_and_not_a_date(world, monkeypatch):
    google_series(world, monkeypatch, title="Piano lesson")
    reply, extras = cancel(world, "cancel just this week's piano lesson", target="this week's piano lesson")
    assert reply.endswith(text_of("ACCT_CARD_SENT", pending=1)), reply
    assert body_lines(world, extras)[0].startswith("Code cancels only this one occurrence") and "Event: gymmaster_1" in body_lines(world, extras), "the instance of Monday 09/11, the one inside the week"


def test_a_target_that_holds_the_repetition_of_the_line_in_its_own_words_is_the_series(world, monkeypatch):
    google_series(world, monkeypatch, title="Aula de violão")      # validate: allow english-only -- the Portuguese title under test
    reply, extras = cancel(world, "apaga da agenda a aula de violão toda semana", target="aula de violão toda semana")      # validate: allow english-only -- the Portuguese line under test
    assert reply.endswith(text_of("ACCT_CARD_SENT", pending=1)), reply
    assert body_lines(world, extras)[0].startswith("Code cancels the whole series after your approval")


def test_a_series_called_daily_and_a_target_with_its_name_alone_is_still_asked_about(world, monkeypatch):
    google_series(world, monkeypatch, title="Daily")
    reply, extras = cancel(world, "cancel the daily standup", target="daily standup")
    assert reply == text_of("RECUR_WHICH", title="Daily", rule=text_of("RECUR_RULE_WEEKLY_MO", time="07:00"), example="Mon 09/11"), reply
    assert nothing_started(world)


def test_a_series_called_daily_and_a_target_that_adds_every_day_is_the_series(world, monkeypatch):
    google_series(world, monkeypatch, title="Daily")
    reply, extras = cancel(world, "cancel the daily every day", target="daily every day")
    assert reply.endswith(text_of("ACCT_CARD_SENT", pending=1)) and body_lines(world, extras)[0].startswith("Code cancels the whole series")


def test_vacuity_with_the_markers_taken_out_the_target_that_says_weekly_is_asked_about_again(world, monkeypatch):
    google_series(world, monkeypatch, title="Piano lesson")
    monkeypatch.setattr(recurrence, "markers", lambda text, *titles: "")
    reply, extras = cancel(world, "cancel my weekly piano lesson", target="weekly piano lesson")
    assert reply == text_of("RECUR_WHICH", title="Piano lesson", rule=text_of("RECUR_RULE_WEEKLY_MO", time="07:00"), example="Mon 09/11")
