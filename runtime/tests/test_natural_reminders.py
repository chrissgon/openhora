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

import standin_tree as st
from natural_cases_pt_br import CANDIDATE_CASES, TEXT_CASES, UNSURE_LINES
from test_attachments import case  # noqa: F401  (the project the attachment tests use, which the world fixture builds on)
from test_reminders import BRT, NOT_ENABLED, SENDER, THIRD, world  # noqa: F401  (the world fixture: a project with four listed senders and a clock)

natural = st.load("natural")
nt = st.load("natural_time")
ops = st.load("ops")
ops_reminders = st.load("ops_reminders")
phrases = st.load("phrases")
rm = st.load("reminders")

NOW = datetime.datetime(2026, 10, 18, 14, 0, tzinfo=BRT)       # Sunday

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
    ("calendar florist friday at 9", {"op": "calendar-event-create", "how": "trigger"}),
    ("call the florist tomorrow at 9 remind me", {"op": "remind", "how": "trigger"}),
    ("at 9am remind me to water the plants", {"op": "remind", "how": "trigger"}),
    ("forget the reminder about the florist", {"op": "reminder-forget", "how": "trigger", "id": None, "words": ["florist"]}),
    ("forget reminder 3 4", {"op": "reminder-forget", "how": "trigger", "id": None, "many": True}),
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
    ("approve plan 12", None),
    ("schedule", None),
    ("delete reminder emails from the customer list", {"op": "reminder-forget", "how": "trigger", "id": None, "words": ["emails", "from", "customer", "list"]}),
    ("delete reminder emails from the customer list and the old suppliers", None),
    ("reminders for the quarterly board meeting should be sent by friday at 3pm to every member", None),
    ("/remind 9h x", None),
    ("", None),
]


@pytest.mark.parametrize("line,expected", CANDIDATE_CASES + ENGLISH_CANDIDATES)
def test_a_line_is_matched_to_a_reminder_operation_by_the_tables_and_nothing_else_is(line, expected):
    assert natural.candidate(line) == expected


@pytest.mark.parametrize("line,expected", TEXT_CASES + [
    ("remind me tomorrow at 1 pm to call the florist", "call the florist"),
    ("remind me to call mom tomorrow at 9am", "call mom"),
    ("Please remind me in 2 hours about the oven", "the oven"),
    ("reminder: friday at 15:00 pay the rent", "pay the rent"),
])
def test_the_words_of_the_reminder_are_the_line_without_the_trigger_the_time_and_one_connector(line, expected):
    got = natural.understand(line, NOW, "trigger")
    assert got["text"] == expected and got["when"]


def test_the_command_form_needs_no_trigger_and_keeps_the_words_in_their_order():
    got = natural.understand("aula de violao as 13hrs amanha", NOW, "command")
    assert got["when"] == "2026-10-19 13:00" and got["text"] == "aula de violao"
    got = natural.understand("tomorrow 1 pm call the florist", NOW, "command")
    assert got["when"] == "2026-10-19 13:00" and got["text"] == "call the florist"


def test_what_is_missing_is_asked_and_the_draft_holds_what_is_known():
    time_missing = natural.understand("remind me to call mom", NOW, "trigger")["ask"]
    assert (time_missing["need"], time_missing["text"], time_missing["day"]) == ("time", "call mom", None)
    day_known = natural.understand("remind me to call mom tomorrow", NOW, "trigger")["ask"]
    assert day_known["need"] == "time" and day_known["day"]["date"] == "2026-10-19" and day_known["day"]["rel"] == 1
    two = natural.understand("remind me to call mom friday at 9", NOW, "trigger")["ask"]
    assert two["need"] == "reading" and [r["when"] for r in two["readings"]] == ["2026-10-23 09:00", "2026-10-23 21:00"]
    no_text = natural.understand("remind me tomorrow at 9am", NOW, "trigger")["ask"]
    assert no_text["need"] == "text" and no_text["readings"][0]["when"] == "2026-10-19 09:00"
    kind = natural.understand("violin class tomorrow at 1pm", NOW, "bare")["ask"]
    assert kind["need"] == "kind" and kind["text"] == "violin class" and kind["readings"][0]["when"] == "2026-10-19 13:00"
    assert natural.understand("", NOW, "command")["ask"]["need"] == "time"
    for asked in (time_missing, two, no_text, kind):
        assert asked["line"], "the draft keeps the line, in memory"


def test_a_draft_is_finished_by_a_time_a_reading_a_kind_or_the_missing_words_and_by_nothing_else():
    complete = natural.complete
    draft = natural.understand("remind me to call mom", NOW, "trigger")["ask"]
    done = complete(draft, "tomorrow 9am", NOW)
    assert done["when"] == "2026-10-19 09:00" and done["text"] == "call mom"
    assert complete(draft, "at 21h", NOW)["when"] == "21:00"
    assert complete(draft, "what is the weather", NOW) is None and complete(draft, "/pending", NOW) is None and complete(draft, "", NOW) is None
    assert complete(draft, "tomorrow", NOW)["ask"]["need"] == "time", "a day alone is still not a time"
    two = natural.understand("remind me to call mom friday at 9", NOW, "trigger")["ask"]
    assert complete(two, "21h", NOW)["when"] == "2026-10-23 21:00" and complete(two, "9:00", NOW)["when"] == "2026-10-23 09:00"
    assert complete(two, "21", NOW)["when"] == "2026-10-23 21:00" and complete(two, "9", NOW)["when"] == "2026-10-23 09:00", "a bare hour picks the reading with that hour"
    assert complete(two, "yes", NOW) is None, "yes picks nothing when two readings were offered"
    assert complete(two, "10h", NOW) is None
    one = {**two, "readings": two["readings"][:1]}
    assert complete(one, "yes", NOW)["when"] == "2026-10-23 09:00" and complete(one, "sim", NOW)["when"] == "2026-10-23 09:00"
    kind = natural.understand("violin class tomorrow at 1pm", NOW, "bare")["ask"]
    assert complete(kind, "reminder", NOW)["text"] == "violin class" and complete(kind, "a reminder", NOW)["when"] == "2026-10-19 13:00"
    assert complete(kind, "lembrete", NOW)["when"] == "2026-10-19 13:00"
    assert complete(kind, "calendar", NOW) == {"event": True} and complete(kind, "agenda", NOW) == {"event": True}
    assert complete(kind, "yes", NOW) is None, "yes does not say which of the two"
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


def test_the_table_of_rows_is_closed_and_a_planned_row_is_marked():
    assert [r["op"] for r in natural.NATURAL] == ["remind", "reminders", "reminder-forget", "calendar-event-create"]
    assert [r["op"] for r in natural.NATURAL if r.get("planned")] == ["calendar-event-create"]
    assert {r["op"] for r in natural.NATURAL if r["class"] in ("N", "R")} == {"remind", "reminders", "reminder-forget"}


def test_a_time_word_the_parse_did_not_use_asks_instead_of_making_the_reminder():
    lines = UNSURE_LINES + ["remind me next week at 10am to pay the rent", "remind me every monday at 8am to water the plants", "remind me tomorow at 9am to pay",
                            "remind me tomorrow at 9am until friday", "remind me on the weekend at 10am to call Ana", "remind me tomorrow at 9am in the afternoon to pay"]
    for line in lines:
        asked = natural.understand(line, NOW, "trigger")["ask"]
        assert asked["need"] == "time" and asked["unsure"] is True, line
    made = natural.understand("remind me tomorrow\u00ad at 9am to pay the rent", NOW)
    assert made["text"] == "pay the rent" and made["when"] == "2026-10-19 09:00", "a soft hyphen is not a letter"
    assert natural.understand("remind me tomorrow at 9am to pay the rent", NOW)["when"] == "2026-10-19 09:00", "nothing left over, nothing asked"


def test_the_answer_to_an_unsure_question_is_taken_whole_and_a_full_new_time_replaces_the_reading():
    unsure = natural.understand("remind me next week at 10am to pay the rent", NOW)["ask"]
    assert natural.complete(unsure, "friday at 10am", NOW)["when"] == "2026-10-23 10:00"
    assert natural.complete(unsure, "at 11am", NOW)["when"] == "11:00" or natural.complete(unsure, "11am", NOW)["when"] == "11:00"
    day = natural.understand("remind me tomorrow to call the florist", NOW)["ask"]
    assert natural.complete(day, "friday 10am", NOW)["when"] == "2026-10-23 10:00", "a day named in the answer replaces the day of the line"
    assert natural.complete(day, "9am", NOW)["when"] == "2026-10-19 09:00", "an hour alone keeps the day"
    two = natural.understand("remind me friday to pay", NOW)["ask"]
    assert natural.complete(two, "in 2 days at 9h", NOW)["when"] == "2026-10-20 09:00"
    assert natural.understand("remind me in 2 days at 9h to see the doctor", NOW)["when"] == "2026-10-20 09:00", "the day two days ahead at nine, not `in 2d`"


def test_a_reply_that_names_the_day_picks_the_reading_by_the_day_and_the_hour_together():
    ask = natural.understand("remind me next thursday at 3:30pm to see the architect", NOW)["ask"]
    assert [r["when"] for r in ask["readings"]] == ["2026-10-22 15:30", "2026-10-29 15:30"]
    assert natural.complete(ask, "the 29th", NOW)["when"] == "2026-10-29 15:30" and natural.complete(ask, "29", NOW)["when"] == "2026-10-29 15:30"
    assert natural.complete(ask, "the 22nd", NOW)["when"] == "2026-10-22 15:30"
    assert natural.complete(ask, "3:30pm", NOW) is None, "the hour is the same in both: it does not say which"
    assert natural.complete(ask, "thursday 4pm", NOW)["when"] == "2026-10-22 16:00", "a full new time replaces the offered ones"
    assert natural.understand("remind me at 3:30pm to stretch", NOW)["when"] == "15:30"
    three = natural.understand("remind me at 3 to stretch", NOW)["ask"]
    assert natural.complete(three, "15", NOW)["when"] == "15:00"


def test_a_text_answer_is_short_and_is_not_a_request_for_work():
    ask = natural.understand("remind me tomorrow at 9am", NOW)["ask"]
    assert natural.complete(ask, "water the plants", NOW)["text"] == "water the plants"
    assert natural.complete(ask, "write the launch post for the shop and send it to the whole team before the meeting", NOW) is None, "too long: a new line"
    assert natural.complete(ask, "write the launch post", NOW) is None, "a work request at its head: a new line"
    assert natural.complete(ask, "send a note to Ana", NOW) is None


def test_event_or_something_else_is_decided_by_the_answer_alone():
    for said, chosen in (("calendar", "event"), ("agenda", "event"), ("an event", "event"), ("something else", "other"), ("other", "other"), ("outra coisa", "other"),
                         ("no", "other"), ("yes", None), ("when", None), ("calendar or other", None)):
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
    got = ops.remind(world.path, channel="messaging", sender=SENDER, said="remind me tomorrow at 1 pm to call the florist")
    assert got["reminder"]["text"] == "call the florist" and got["reminder"]["due"] == "2026-10-19 13:00"
    assert got["human"] == {"date": "2026-10-19", "time": "13:00", "zone": "BRT", "rel": 1, "far": False, "rolled": False}
    assert got["reply"] == "Reminder #1 set for 2026-10-19 13:00 (BRT)."
    rolled = ops.remind(world.path, channel="messaging", sender=SENDER, said="13:00 stretch", how="command")
    assert rolled["human"]["rolled"] is True and rolled["human"]["date"] == "2026-10-19", "a time of day that had passed rolled over to tomorrow"
    again = ops.remind(world.path, channel="messaging", sender=SENDER, said="tomorrow 13:00 stretch", how="command")
    assert again["human"]["rolled"] is False, "a day named is never rolled"
    assert [r["text"] for r in world.rows("open")] == ["call the florist", "stretch", "stretch"]


def test_the_policy_is_asked_before_the_line_is_read_and_a_refusal_is_the_typed_one(world):  # noqa: F811
    with pytest.raises(ops.OpsError) as e:
        ops.remind(world.path, channel="messaging", sender=f"telegram:{THIRD}", said="remind me tomorrow at 1 pm to call the florist")
    assert NOT_ENABLED in str(e.value)
    with pytest.raises(ops.OpsError) as e2:
        ops.remind(world.path, "15:00", "x", channel="messaging", sender=f"telegram:{THIRD}")
    assert str(e.value) == str(e2.value), "the same sentence as the typed command"
    assert world.rows() == []


def test_a_question_stores_nothing_and_keeps_nothing_and_an_answer_to_it_makes_the_reminder(world):  # noqa: F811
    asked = ops.remind(world.path, channel="messaging", sender=SENDER, said="remind me to call mom friday at 9")
    assert asked["ask"]["need"] == "reading" and world.rows() == []
    made = ops.remind(world.path, channel="messaging", sender=SENDER, said="21h", how="trigger", draft=asked["ask"])
    assert made["reminder"]["text"] == "call mom" and made["reminder"]["due"] == "2026-10-23 21:00"
    assert ops.remind(world.path, channel="messaging", sender=SENDER, said="something else entirely", draft=asked["ask"]) == {"declined": True}
    kind = ops.remind(world.path, channel="messaging", sender=SENDER, said="violin class tomorrow 1pm", how="bare")["ask"]
    assert kind["need"] == "kind" and len(world.rows()) == 1
    assert ops.remind(world.path, channel="messaging", sender=SENDER, said="agenda", draft=kind) == {"event": True} and len(world.rows()) == 1
    assert ops.remind(world.path, channel="messaging", sender=SENDER, said="reminder", draft=kind)["reminder"]["text"] == "violin class"


def test_the_checks_of_the_strict_grammar_stay_over_a_line_in_words(world):  # noqa: F811
    for said, sentence in (("remind me today at 1pm to stretch", "That time has passed. Now it is 2026-10-18 14:00."),
                           ("remind me in 400 days to stretch", "A reminder is at most 366 days ahead."),
                           ("remind me 30/02 at 10:00 to stretch", "2027-02-30 is not a day of the calendar."),
                           ("remind me tomorrow at 9h with sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6", None)):
        with pytest.raises(ops.OpsError) as e:
            ops.remind(world.path, channel="messaging", sender=SENDER, said=said)
        if sentence:
            assert str(e.value) == sentence, said
        else:
            assert "looks like a credential" in str(e.value) and "A1b2C3d4E5f6" not in str(e.value)
    assert world.rows() == []


def test_the_terminal_and_the_page_keep_the_strict_grammar_and_the_sentence_they_always_got(world):  # noqa: F811
    got = world.remind("15:00", "Call the florist")
    assert got["reply"] == "Reminder #1 set for 2026-10-18 15:00 (BRT)." and got["human"]["time"] == "15:00"
    with pytest.raises(ops.OpsError):
        world.remind("13hrs", "x")


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
