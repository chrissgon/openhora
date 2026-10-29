"""Natural requests, tier 1, the reminder rows (package NR-1, runtime/natural.py and `remind(said=...)` of runtime/ops_reminders.py): which lines a pattern table
matches to a reminder operation with no model, which it leaves alone, the words of the reminder it takes out of the line, the questions it asks back and how a
draft is finished, and the operation that reads the line with the clock after the policy: a sender whose profile lacks the group is refused before the line is
read, a question stores nothing, and nothing here reaches a model, a route, a provider or the network. The conversation through a bridge is in
test_messaging_natural.py; the parser in test_natural_time.py. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_reminders.py
"""
from __future__ import annotations

import datetime
import re

import pytest

import phrase_kit as pk
import standin_tree as st
from closed_heads import trigger_reading  # noqa: F401  (S41-11 PR 2b: the reminder engine's old entry, the way `trigger`, for the tests that read a line that starts with a remind word)
from natural_cases_pt_br import CANDIDATE_CASES, PLAIN_LINES, RECURRING_LINES, UNSURE_LINES
from natural_kit import made, said_yes
from test_attachments import case  # noqa: F401  (the project the attachment tests use, which the world fixture builds on)
from test_reminders import BRT, NOT_ENABLED, OTHER, SENDER, THIRD, world  # noqa: F401  (the world fixture: a project with four listed senders and a clock)

pytestmark = pytest.mark.usefixtures("trigger_reading")
natural = st.load("natural")
nt = st.load("natural_time")
turn_gate = st.load("turn_gate")
ops = st.load("ops")
ops_reminders = st.load("ops_reminders")
phrases = st.load("phrases")
rm = st.load("reminders")

NOW = datetime.datetime(2026, 10, 18, 14, 0, tzinfo=BRT)       # Sunday


def completed(draft, said, now=NOW):
    """`turn_gate.complete_reminder` (`natural.complete` with the guard's verdict, CANDIDATE-OUT), and the "yes" that makes the reminder when the answer was a reading shown for confirmation: a free-text reminder is made only after a yes."""
    got = turn_gate.complete_reminder(draft, said, now)
    if got and "ask" in got and got["ask"]["need"] == "confirm" and not got["ask"].get("retries"):
        return turn_gate.complete_reminder(got["ask"], "yes", now)
    return got

ENGLISH_CANDIDATES = [
    ("remind me tomorrow at 1pm to call the florist", {"op": "remind", "how": "trigger"}),
    ("Please remind me on friday to pay the rent", {"op": "remind", "how": "trigger"}),
    ("set a reminder for 9am: water the plants", {"op": "remind", "how": "trigger"}),
    ("reminder in 2 hours stretch", {"op": "remind", "how": "trigger"}),
    ("what reminders do I have", {"op": "reminders", "how": "trigger"}),
    ("list my reminders", {"op": "reminders", "how": "trigger"}),
    ("forget reminder 4", {"op": "reminder-forget", "how": "trigger", "id": 4}),
    ("cancel the reminder #7", {"op": "reminder-forget", "how": "trigger", "id": 7}),
    ("delete reminder", {"op": "reminder-forget", "how": "trigger", "id": None}),
    ("put on my calendar the florist friday at 9", {"op": "calendar-event-create", "how": "trigger"}),
    ("schedule a meeting tomorrow at 10", {"op": "calendar-event-create", "how": "ask"}),
    ("schedule the post for tomorrow at 9am", {"op": "calendar-event-create", "how": "ask"}),
    ("book a table friday at 8pm", {"op": "calendar-event-create", "how": "ask"}),
    ("calendar florist friday at 9", {"op": "calendar-event-create", "how": "ask"}),
    ("calendar for tomorrow?", None),
    ("calendar of october", None),
    ("what is on my calendar friday at 9?", None),
    ("undo", {"op": "reminder-restore", "how": "trigger"}),
    ("undo that", {"op": "reminder-restore", "how": "trigger"}),
    ("undo the last deploy and restart the service", None),
    ("cancel reminder 9", {"op": "reminder-forget", "how": "trigger", "id": 9}),
    ("forget reminder #9", {"op": "reminder-forget", "how": "trigger", "id": 9}),
    ("cancel the reminder of the 9 oclock one", {"op": "reminder-forget", "how": "trigger", "id": None, "words": ["9", "oclock", "one"]}),
    ("delete reminder emails from inbox", None),
    ("remove the reminder banner from the site", None),
    ("cancel the reminder feature in the app", None),
    ("reminders are broken", None),
    ("my reminders are not working", None),
    ("reminder 3 did not arrive", None),
    ("remind me every monday at 8am to water", {"op": "remind", "how": "trigger"}),
    ("every monday at 8am send me a summary", None),
    ("call the florist tomorrow at 9 remind me", {"op": "remind", "how": "trigger"}),
    ("at 9am remind me to water the plants", {"op": "remind", "how": "trigger"}),
    ("forget the reminder about the florist", {"op": "reminder-forget", "how": "trigger", "id": None, "words": ["florist"]}),
    ("forget reminder 3 4", {"op": "reminder-forget", "how": "trigger", "id": None, "ids": [3, 4], "confirm": True}),
    ("reminders", {"op": "reminders", "how": "trigger"}),
    ("do reminders work on whatsapp?", None),
    ("reminders are not arriving on my phone", None),
    ("schedule the post", None),
    ("note to self", {"op": "remind", "how": "note"}),
    ("note violin class tomorrow at 1pm", {"op": "remind", "how": "bare"}),
    ("violin class tomorrow 1pm", {"op": "remind", "how": "bare"}),
    # what must not become a reminder
    ("write the launch post for tomorrow at 9", None),
    ("what is due tomorrow at 9?", None),
    ("send the invoice friday at 3pm", None),
    ("how are we doing", None),
    ("sign off on proposal 12", None),
    ("schedule", None),
    ("delete reminder emails from the customer list", None),
    ("reminders for the quarterly board meeting should be sent by friday at 3pm to every member", None),
    ("/remind 9h x", None),
    ("", None),
]


@pytest.mark.parametrize("line,expected", CANDIDATE_CASES + ENGLISH_CANDIDATES)
def test_a_line_is_matched_to_a_reminder_operation_by_the_tables_and_nothing_else_is(line, expected):
    assert natural.candidate(line) == expected


def test_the_command_form_needs_no_trigger_and_keeps_the_words_in_their_order():
    got = made(natural, "aula de violao as 13hrs amanha", NOW, "command")
    assert got["when"] == "2026-10-19 13:00" and got["text"] == "aula de violao"
    got = made(natural, "tomorrow 1 pm call the florist", NOW, "command")
    assert got["when"] == "2026-10-19 13:00" and got["text"] == "call the florist"


def test_what_is_missing_is_asked_and_the_draft_holds_what_is_known():
    time_missing = natural.understand("remind me to phone the neighbour", NOW, "trigger")["ask"]
    assert (time_missing["need"], time_missing["text"], time_missing["day"]) == ("time", "phone the neighbour", None)
    day_known = natural.understand("remind me to phone the neighbour tomorrow", NOW, "trigger")["ask"]
    assert day_known["need"] == "time" and day_known["day"]["date"] == "2026-10-19" and day_known["day"]["rel"] == 1
    two = natural.understand("remind me to phone the neighbour friday at 9", NOW, "trigger")["ask"]
    assert two["need"] == "reading" and [r["when"] for r in two["readings"]] == ["2026-10-23 09:00", "2026-10-23 21:00"]
    no_text = natural.understand("remind me tomorrow at 9am", NOW, "trigger")["ask"]
    assert no_text["need"] == "text" and no_text["readings"][0]["when"] == "2026-10-19 09:00"
    kind = natural.understand("violin class tomorrow at 1pm", NOW, "bare")["ask"]
    assert kind["need"] == "kind" and kind["text"] == "violin class" and kind["readings"][0]["when"] == "2026-10-19 13:00"
    assert natural.understand("", NOW, "command")["ask"]["need"] == "time"
    for asked in (time_missing, two, no_text, kind):
        assert asked["line"], "the draft keeps the line, in memory"


def test_a_draft_is_finished_by_a_time_a_reading_a_kind_or_the_missing_words_and_by_nothing_else():
    complete = completed
    draft = natural.understand("remind me to phone the neighbour", NOW, "trigger")["ask"]
    done = complete(draft, "tomorrow 9am", NOW)
    assert done["when"] == "2026-10-19 09:00" and done["text"] == "phone the neighbour"
    assert complete(draft, "at 21h", NOW)["when"] == "2026-10-18 21:00"
    assert complete(draft, "what is the weather", NOW) is None and complete(draft, "/pending", NOW) is None and complete(draft, "", NOW) is None
    assert complete(draft, "tomorrow", NOW)["ask"]["need"] == "time", "a day alone is still not a time"
    two = natural.understand("remind me to phone the neighbour friday at 9", NOW, "trigger")["ask"]
    assert complete(two, "21h", NOW)["when"] == "2026-10-23 21:00" and complete(two, "9:00", NOW)["when"] == "2026-10-23 09:00"
    assert complete(two, "21", NOW)["when"] == "2026-10-23 21:00" and complete(two, "9", NOW)["when"] == "2026-10-23 09:00", "a bare hour picks the reading with that hour"
    again = complete(two, "yes", NOW)["ask"]
    assert again["need"] == "reading" and again["retries"] == 1, "yes picks nothing when two readings were offered: the question is asked once more"
    assert complete(again, "yes", NOW) is None, "and the second time the line is a new one"
    assert complete(two, "10h", NOW)["ask"]["retries"] == 1
    one = {**two, "readings": two["readings"][:1]}
    assert complete(one, "yes", NOW)["when"] == "2026-10-23 09:00" and complete(one, "sim", NOW)["when"] == "2026-10-23 09:00"
    kind = natural.understand("violin class tomorrow at 1pm", NOW, "bare")["ask"]
    assert complete(kind, "reminder", NOW)["text"] == "violin class" and complete(kind, "a reminder", NOW)["when"] == "2026-10-19 13:00"
    assert complete(kind, "lembrete", NOW)["when"] == "2026-10-19 13:00"
    assert complete(kind, "calendar", NOW) == {"event": True} and complete(kind, "agenda", NOW) == {"event": True}
    assert complete(kind, "yes", NOW)["text"] == "violin class" and complete(kind, "sim", NOW)["when"] == "2026-10-19 13:00", "a yes to \"a reminder or an event\" is the reminder"
    assert complete(kind, "a reminder please and an event", NOW) is None
    text = natural.understand("remind me tomorrow at 9am", NOW, "trigger")["ask"]
    assert complete(text, "water the plants", NOW)["text"] == "water the plants"
    assert complete(text, "what reminders do I have", NOW) is None, "a line that is itself a request is not the words of a reminder"


def test_a_moment_is_described_for_a_person_in_the_projects_language():
    reading = nt.parse("tomorrow 1pm", NOW)["reading"]
    assert natural.describe(reading, None) == "tomorrow, Mon 19/10, at 13:00"
    assert natural.describe(reading, {"language": "pt-BR"}, "BRT") == "amanhã, seg 19/10, às 13:00 (BRT)"      # validate: allow english-only -- the expected Portuguese sentence
    far = nt.parse("friday 9am", NOW)["reading"]
    assert natural.describe(far, None, "BRT") == "Fri 23/10 at 09:00 (BRT)" and natural.describe(far, {"language": "pt-BR"}) == "sex 23/10 às 09:00"      # validate: allow english-only -- the expected Portuguese sentence
    today = nt.parse("6pm", NOW)["reading"]
    assert natural.describe(today, None) == "today, Sun 18/10, at 18:00"
    assert natural.describe_day({"date": "2026-10-19", "rel": 1}, None) == "tomorrow, Mon 19/10" and natural.describe_day({"date": "2026-11-02", "rel": 15}, None) == "Mon 02/11"
    assert natural.describe({"date": "2027-02-30", "time": "10:00", "rel": 100}, None) == "2027-02-30 10:00", "a date the calendar lacks is shown as it was written"
    assert natural.capital("tomorrow, Mon 19/10") == "Tomorrow, Mon 19/10"


def test_every_new_sentence_is_a_key_of_the_phrase_table_in_both_languages():
    keys = [k for k in phrases.TABLE["en"] if k.startswith("NT_")]
    assert len(keys) >= 25 and sorted(keys) == sorted(k for k in phrases.TABLE["pt-BR"] if k.startswith("NT_"))
    for day in range(7):
        assert phrases.text(f"NT_WD_{day}", {"language": "pt-BR"}) != phrases.text(f"NT_WD_{day}", None)


def test_the_table_of_classes_holds_the_reminders_and_the_calendar_event_is_an_operation_now():
    assert {op: natural.CLASSES[op] for op in ("remind", "reminders", "reminder-forget", "reminder-restore")} == \
        {"remind": "N", "reminders": "R", "reminder-forget": "N", "reminder-restore": "N"}
    assert natural.CLASSES["event-create"] == "E" and natural.operation_of("calendar-event-create") == "event-create", "the intent is the operation the platform has"
    assert natural.PLANNED == ()


def test_a_full_reading_with_something_uncertain_is_shown_and_confirmed_never_asked_open_and_never_lost():
    lines = UNSURE_LINES + ["remind me tomorow at 9am to pay",
                            "remind me on the weekend at 10am to call Ana", "remind me tomorrow at 9am in the afternoon to pay", "remind me tomorrow 13.30 to pay"]
    for line in lines:
        asked = natural.understand(line, NOW, "trigger")["ask"]
        assert asked["need"] == "confirm" and asked["readings"] and asked["text"], line
    for line in PLAIN_LINES + ["remind me tomorrow at 9am to call Marcos", "remind me tomorrow at 9am to tidy the room", "remind me tomorrow at 9am to pay the rent"]:
        assert natural.understand(line, NOW, "trigger")["ask"]["need"] == "confirm" and "when" in made(natural, line, NOW, "trigger"), line
    soft = made(natural, "remind me tomorrow­ at 9am to pay the rent", NOW)
    assert soft["text"] == "pay the rent" and soft["when"] == "2026-10-19 09:00", "a soft hyphen is not a letter"
    assert natural.understand("remind me every monday at 8am to water the plants", NOW)["ask"]["need"] == "recurring"


def test_a_line_that_repeats_is_said_to_be_a_routines_and_is_never_a_one_off():
    for line in RECURRING_LINES + ["remind me every monday at 8am to water", "remind me daily at 9am to stretch", "remind me weekly on friday at 3pm to report",
                                  "remind me every 2 hours to drink water", "remind me each day at 7 to open the window"]:
        assert natural.understand(line, NOW, "trigger")["ask"]["need"] == "recurring", line


def test_the_answer_to_a_confirmation_makes_it_or_replaces_only_the_part_it_names_and_never_drops_the_day():
    ask = natural.understand("remind me on friday at 10am about the next month plan", NOW)["ask"]
    assert ask["need"] == "confirm" and ask["readings"][0]["when"] == "2026-10-23 10:00" and ask["text"] == "the next month plan"
    complete = completed
    assert complete(ask, "yes", NOW)["when"] == "2026-10-23 10:00" and complete(ask, "sim", NOW)["text"] == "the next month plan"
    assert complete(ask, "11am", NOW)["when"] == "2026-10-23 11:00", "an hour alone keeps the day"
    assert complete(ask, "saturday", NOW)["when"] == "2026-10-24 10:00", "a day alone keeps the hour"
    assert complete(ask, "saturday 8am", NOW)["when"] == "2026-10-24 08:00", "a day and an hour replace both"
    assert complete(ask, "in 2 hours", NOW)["when"] == "2026-10-18 16:00"
    assert complete(ask, "no", NOW) == {"cancel": True} and complete(ask, "cancel", NOW) == {"cancel": True} and complete(ask, "never mind", NOW) == {"cancel": True}
    assert complete(ask, "thanks", NOW)["ask"]["retries"] == 1 and complete(ask, "what is the weather", NOW) is None
    kind = natural.understand("plan the garden friday at 3pm", NOW, "bare")
    assert kind["ask"]["need"] == "kind"
    unsure = natural.understand("remind me tomorrow at 9am to tidy next month", NOW)["ask"]
    assert unsure["need"] == "confirm"
    assert completed(unsure, "yes", NOW)["text"] == "tidy next month"
    no_text = natural.understand("me lembra dia 3/10 às 9h", NOW)["ask"]      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert no_text["need"] == "text" and no_text["doubt"] is True
    assert natural.complete(no_text, "renew the insurance", NOW)["ask"]["need"] == "confirm", "the uncertain reading is confirmed once the words are there"


def test_a_day_word_with_a_typo_is_read_as_the_word_it_is_one_letter_from_and_the_reading_is_confirmed():
    ask = natural.understand("remind me tomorow at 1pm to call the florist", NOW)["ask"]
    assert ask["need"] == "confirm" and ask["readings"][0]["when"] == "2026-10-19 13:00" and ask["text"] == "call the florist", "tomorrow, not today: the typo is read"
    pt = natural.understand("me lembra amnhã às 13h de ligar para a Ana", NOW)["ask"]      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert pt["need"] == "confirm" and pt["readings"][0]["when"] == "2026-10-19 13:00" and pt["text"] == "ligar para a Ana"


def test_a_date_that_has_passed_this_year_is_confirmed_with_its_year_and_today_with_a_past_hour_stays_today():
    ask = natural.understand("remind me on 3/1 at 9am to renew the insurance", NOW, "trigger")
    assert ask["ask"]["need"] == "reading", "an x/y in an English line is asked month first or day first"
    pt = natural.understand("me lembra dia 3/10 às 9h de renovar o seguro", NOW, "trigger")["ask"]
    assert pt["need"] == "confirm" and pt["readings"][0]["when"] == "2027-10-03 09:00" and pt["readings"][0]["far"] is True
    assert natural.describe(pt["readings"][0], {"language": "pt-BR"}) == "dom 03/10/2027 às 09:00"      # validate: allow english-only -- the expected Portuguese sentence
    assert completed(pt, "sim", NOW)["when"] == "2027-10-03 09:00"
    today = made(natural, "me lembra dia 18/10 às 13h de ligar", NOW, "trigger")
    assert today["when"] == "2026-10-18 13:00", "today stays today: resolve refuses it as past"



def test_a_reply_that_names_the_day_picks_the_reading_by_the_day_and_the_hour_together():
    ask = natural.understand("remind me next thursday at 3:30pm to see the architect", NOW)["ask"]
    assert [r["when"] for r in ask["readings"]] == ["2026-10-22 15:30", "2026-10-29 15:30"]
    assert completed(ask, "the 29th", NOW)["when"] == "2026-10-29 15:30" and completed(ask, "29", NOW)["when"] == "2026-10-29 15:30"
    assert completed(ask, "the 22nd", NOW)["when"] == "2026-10-22 15:30"
    assert completed(ask, "3:30pm", NOW)["ask"]["retries"] == 1, "the hour is the same in both: it does not say which, the question is asked once more"
    assert completed(ask, "thursday 4pm", NOW)["when"] == "2026-10-22 16:00", "a full new time replaces the offered ones"
    assert made(natural, "remind me at 3:30pm to stretch", NOW)["when"] == "2026-10-18 15:30"
    three = natural.understand("remind me at 3 to stretch", NOW)["ask"]
    assert completed(three, "15", NOW)["when"] == "2026-10-18 15:00", "a reading picked is shown with its day: it is not read again as today or tomorrow"


def test_a_text_answer_is_short_and_is_not_a_request_for_work():
    ask = natural.understand("remind me tomorrow at 9am", NOW)["ask"]
    assert completed(ask, "water the plants", NOW)["text"] == "water the plants"
    assert completed(ask, "write the launch post for the shop and send it to the whole team before the meeting", NOW) is None, "too long: a new line"
    assert completed(ask, "write the launch post", NOW) is None, "a work request at its head: a new line"
    assert completed(ask, "send a note to Ana", NOW) is None


def test_event_or_something_else_is_decided_by_the_answer_alone():
    for said, chosen in (("calendar", "event"), ("agenda", "event"), ("an event", "event"), ("something else", "other"), ("other", "other"), ("outra coisa", "other"),
                         ("no", "other"), ("reminder", "notice"), ("lembrete", "notice"), ("a reminder", "notice"), ("yes", None), ("when", None),
                         ("calendar or other", None)):
        assert natural.answer_kind(said) == chosen, said


def test_a_moment_not_in_this_year_shows_its_year():
    far = nt.parse("on 2027-01-05 at 9am", NOW)["reading"]
    assert natural.describe(far, None, "BRT") == "Tue 05/01/2027 at 09:00 (BRT)" and natural.describe(nt.parse("on 2026-12-05 at 9am", NOW)["reading"], None) == "Sat 05/12 at 09:00"
    assert natural.describe(natural.info_of("2027-01-05", "09:00", NOW.date()), {"language": "pt-BR"}) == "ter 05/01/2027 às 09:00"      # validate: allow english-only -- the expected Portuguese sentence
    assert natural.info_of("2026-10-19", "13:00", NOW.date()) == {"date": "2026-10-19", "time": "13:00", "rel": 1, "far": False}


def test_the_tables_drive_every_trigger_so_no_word_of_a_language_is_in_the_rules():
    source = (st.RUNTIME / "natural.py").read_text(encoding="utf-8")
    pt = {w for phrase in nt.languages()[1]["triggers"]["remind"] + nt.languages()[1]["work_starters"] for w in phrase.split()} - {w for phrase in nt.languages()[0]["triggers"]["remind"] for w in phrase.split()}
    assert not [w for w in pt if len(w) > 3 and re.search(r"[\"'] ?" + re.escape(w) + r"\b", source)]


# --- the operation: the policy first, then the line, with the clock -----------------------------------------------------------------------------------


def test_a_line_makes_a_reminder_for_the_sender_with_the_facts_a_chat_shows(world):  # noqa: F811
    got = said_yes(ops, world.path, SENDER, "remind me tomorrow at 1 pm to call the florist")
    assert got["reminder"]["text"] == "call the florist" and got["reminder"]["due"] == "2026-10-19 13:00"
    assert got["human"] == {"date": "2026-10-19", "time": "13:00", "zone": "BRT", "rel": 1, "far": False, "rolled": False}
    pk.assert_said(got["reply"], "RM_SET", None, id=1, wall="2026-10-19 13:00", zone="BRT")
    first = ops.remind(world.path, channel="messaging", sender=SENDER, said="13:00 stretch", how="command")["ask"]
    assert first["need"] == "confirm" and first["readings"][0]["rolled"] is True, "a time of day that had passed rolled over to tomorrow, and the question says so"
    rolled = ops.remind(world.path, channel="messaging", sender=SENDER, said="yes", how="command", draft=first)
    assert rolled["human"]["date"] == "2026-10-19", "and the yes makes tomorrow's"
    again = said_yes(ops, world.path, SENDER, "tomorrow 13:00 stretch", "command")
    assert again["human"]["rolled"] is False, "a day named is never rolled"
    assert [r["text"] for r in world.rows("open")] == ["call the florist", "stretch", "stretch"]


def test_the_policy_is_asked_before_the_line_is_read_and_a_refusal_is_the_typed_one(world):  # noqa: F811
    with pytest.raises(ops.OpsError) as e:
        said_yes(ops, world.path, f"telegram:{THIRD}", "remind me tomorrow at 1 pm to call the florist")
    assert NOT_ENABLED in str(e.value)
    with pytest.raises(ops.OpsError) as e2:
        ops.remind(world.path, "15:00", "x", channel="messaging", sender=f"telegram:{THIRD}")
    assert str(e.value) == str(e2.value), "the same sentence as the typed command"
    assert world.rows() == []


def test_a_question_stores_nothing_and_keeps_nothing_and_an_answer_to_it_makes_the_reminder(world):  # noqa: F811
    asked = said_yes(ops, world.path, SENDER, "remind me to phone the neighbour friday at 9")
    assert asked["ask"]["need"] == "reading" and world.rows() == []
    picked = ops.remind(world.path, channel="messaging", sender=SENDER, said="21h", how="trigger", draft=asked["ask"])
    assert picked["ask"]["need"] == "confirm" and world.rows() == [], "a pick shows the whole reading and waits for the yes"
    made = ops.remind(world.path, channel="messaging", sender=SENDER, said="yes", how="trigger", draft=picked["ask"])
    assert made["reminder"]["text"] == "phone the neighbour" and made["reminder"]["due"] == "2026-10-23 21:00"
    retry = ops.remind(world.path, channel="messaging", sender=SENDER, said="something else entirely", draft=asked["ask"])
    assert retry["ask"]["retries"] == 1 and len(world.rows()) == 1
    assert ops.remind(world.path, channel="messaging", sender=SENDER, said="something else entirely", draft=retry["ask"]) == {"declined": True}
    kind = ops.remind(world.path, channel="messaging", sender=SENDER, said="violin class tomorrow 1pm", how="bare")["ask"]
    assert kind["need"] == "kind" and len(world.rows()) == 1
    assert ops.remind(world.path, channel="messaging", sender=SENDER, said="agenda", draft=kind)["event"] is True and len(world.rows()) == 1
    assert ops.remind(world.path, channel="messaging", sender=SENDER, said="reminder", draft=kind)["reminder"]["text"] == "violin class"


def test_the_checks_of_the_strict_grammar_stay_over_a_line_in_words(world):  # noqa: F811
    for said, sentence in (("remind me today at 1pm to stretch", ("RM_PAST", {"now": "18/10/2026 14:00"})),
                           ("remind me in 400 days to stretch", ("RM_TOO_FAR", {})),
                           ("remind me 30/02 at 10:00 to stretch", ("RM_NO_SUCH_DATE", {"given": "2027-02-30"})),
                           ("remind me tomorrow at 9h with sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6", None)):
        with pytest.raises(ops.OpsError) as e:
            ops.remind(world.path, channel="messaging", sender=SENDER, said=said)
        if sentence:
            pk.assert_said(str(e.value), sentence[0], None, **sentence[1])
        else:
            assert pk.said(str(e.value), "RM_CREDENTIAL") and "A1b2C3d4E5f6" not in str(e.value)
    assert world.rows() == []


def test_the_terminal_and_the_page_keep_the_strict_grammar_and_the_sentence_they_always_got(world):  # noqa: F811
    got = world.remind("15:00", "Call the florist")
    assert pk.said(got["reply"], "RM_SET", id=1, wall="2026-10-18 15:00", zone="BRT") and got["human"]["time"] == "15:00"
    with pytest.raises(ops.OpsError):
        world.remind("13hrs", "x")


# --- the undo and the forget by words, at the operation ------------------------------------------------------------------------------------------------------


def test_a_cancelled_reminder_is_brought_back_as_a_new_one_with_the_same_words_and_time_and_the_old_record_never_changes(world):  # noqa: F811
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 1 pm to water the plants")
    ops.reminder_forget(world.path, 1, channel="messaging", sender=SENDER)
    back = ops.reminder_restore(world.path, channel="messaging", sender=SENDER)
    assert back["restored"] == 1 and back["reminder"]["id"] == 2 and pk.said(back["reply"], "RM_BACK", old=1, new=2) and back["reminder"]["text"] == "water the plants"
    assert back["human"] == {"date": "2026-10-19", "time": "13:00", "zone": "BRT", "rel": 1, "far": False, "rolled": False}
    rows = {r["id"]: r for r in world.rows()}
    assert rows[1]["status"] == "cancelled" and rows[2]["status"] == "open" and (rows[1]["text"], rows[1]["due_utc"], rows[1]["chat"]) == (rows[2]["text"], rows[2]["due_utc"], rows[2]["chat"])
    with pytest.raises(ops.OpsError) as e:
        ops.reminder_restore(world.path, channel="messaging", sender=SENDER)
    pk.assert_said(str(e.value), "RM_ALREADY_BACK", n=1)


def test_the_undo_is_the_senders_own_within_ten_minutes_and_not_a_reminder_that_is_about_to_fire(world):  # noqa: F811
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 1 pm to water the plants")
    ops.reminder_forget(world.path, 1, channel="messaging", sender=SENDER)
    assert ops.reminder_restore(world.path, channel="messaging", sender=f"telegram:{OTHER}") == {"none": True}, "another sender's"
    with pytest.raises(ops.OpsError) as e:
        ops.reminder_restore(world.path, channel="messaging", sender=f"telegram:{THIRD}")
    assert NOT_ENABLED in str(e.value), "the group is the reminders' own"
    world.clock.moment += datetime.timedelta(seconds=601)
    assert ops.reminder_restore(world.path, channel="messaging", sender=SENDER) == {"none": True}, "ten minutes is the limit"
    world.clock.set("2026-10-19 12:50")
    said_yes(ops, world.path, SENDER, "remind me at 1 pm to call")
    ops.reminder_forget(world.path, 2, channel="messaging", sender=SENDER)
    world.clock.set("2026-10-19 12:59")
    world.clock.moment += datetime.timedelta(seconds=30)
    with pytest.raises(ops.OpsError) as e:
        ops.reminder_restore(world.path, channel="messaging", sender=SENDER)
    pk.assert_said(str(e.value), "RM_RESTORE_TOO_LATE", n=2)


def test_the_terminal_names_the_reminder_it_brings_back_and_the_old_sentence_of_the_forget_stays(world):  # noqa: F811
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 1 pm to water the plants")
    forgot = ops.reminder_forget(world.path, 1, channel="terminal")
    assert pk.said(forgot["reply"], "RM_FORGOT", id=1) and forgot["reminder"]["text"] == "water the plants" and forgot["human"]["time"] == "13:00"
    assert ops.reminder_restore(world.path, 9, channel="terminal") == {"none": True}
    pk.assert_said(ops.reminder_restore(world.path, 1, channel="terminal")["reply"], "RM_BACK", old=1, new=2)


def test_a_forget_by_words_looks_among_the_senders_own_by_whole_words_and_numbers_are_words(world):  # noqa: F811
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 1 pm to pay 2 invoices")
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 2 pm to pay the florist")
    said_yes(ops, world.path, f"telegram:{OTHER}", "remind me tomorrow at 3 pm to pay the florist")
    assert ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["flor"]) == {"none": True}, "a prefix is not a word"
    assert ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["1"]) == {"none": True}
    assert [r["id"] for r in ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["pay"])["choose"]] == [1, 2]
    done = ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["florist"])
    assert done["reminder"]["id"] == 2 and done["reminder"]["text"] == "pay the florist" and done["human"]["rel"] == 1
    assert {r["id"]: r["status"] for r in world.rows()} == {1: "open", 2: "cancelled", 3: "open"}, "the other sender's is untouched"


# --- nothing reaches a model, a route, a provider or the network -------------------------------------------------------------------------------------


def test_no_module_of_the_natural_requests_reaches_a_model_a_provider_or_the_network():
    for name in ("natural", "natural_time", "natural_lang_en", "natural_lang_pt_br"):
        source = (st.RUNTIME / f"{name}.py").read_text(encoding="utf-8")
        imports = set(re.findall(r"^\s*(?:import|from)\s+(\w+)", source, re.M))
        assert not imports & {"lab", "router", "plan", "effects", "effect_send", "subprocess", "socket", "urllib", "http", "requests", "ops", "ops_say", "approvals"}, (name, imports)
    tables = {t["tag"]: t for t in nt.languages()}
    assert set(tables) == {"en", "pt-BR"}
    for table in tables.values():
        assert not any(isinstance(v, str) and v.startswith("/") for v in table["triggers"]["remind"]), "a trigger is a word, never a slash command"
