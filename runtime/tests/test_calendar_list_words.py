"""The calendar read in words is a tier-1 form (slice S4b; runtime/natural_lang_en.py and natural_lang_pt_br.py `requests.forms.items`, `writes.calendar.nouns_plural`).

The live line of the maintainer's Telegram test, "mostra minha agenda", was no tier-1 form, so a sender whom the interpreter does not read, or a model that answered `answer`, had it taken
as the answer to the router's open question. Now the calendar nouns (pt: agenda, calendario, compromissos; en: calendar, agenda, schedule) are in the `items` forms with their usual verbs,
and `natural_writes.items_kind` says `calendar` for them. The forms are whole lines: a write that names the agenda ("Agende ...", "remova ... da agenda", "muda ... na agenda",
"cancela ... da agenda") is still no tier-1 form and reaches its write or lookup path; the second half pins, for each, the path it reached before this slice (literals of this file).

Every expectation is a literal. The vacuity cases plant a form that is too wide (a copy of the table with one more form) and show the same oracle catches it. Offline, pure; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_calendar_list_words.py
"""
from __future__ import annotations

import copy

import pytest

import standin_tree as st

natural = st.load("natural")
natural_writes = st.load("natural_writes")
event_lookup = st.load("event_lookup")
nt = st.load("natural_time")

CALENDAR_READS = [
    "mostra minha agenda",  # validate: allow english-only -- a line the person types in Portuguese
    "Mostra minha agenda",  # validate: allow english-only -- a line the person types in Portuguese
    "me mostra a agenda",  # validate: allow english-only -- a line the person types in Portuguese
    "minha agenda",  # validate: allow english-only -- a line the person types in Portuguese
    "minha agenda de amanhã",  # validate: allow english-only -- a line the person types in Portuguese
    "o que tenho na agenda",  # validate: allow english-only -- a line the person types in Portuguese
    "o que tem na agenda hoje",  # validate: allow english-only -- a line the person types in Portuguese
    "veja meu calendário",  # validate: allow english-only -- a line the person types in Portuguese
    "quais compromissos eu tenho hoje",  # validate: allow english-only -- a line the person types in Portuguese
    "show my calendar",
    "show my schedule",
    "list my calendar for tomorrow",
    "my agenda",
    "what's on my calendar today",
    "what do I have on my calendar",
]

# (the line, what it reached before this slice and still reaches): natural_writes.candidate op, event_lookup.verb_op, natural.candidate op ("" is none)
NOT_CAUGHT = [
    ("Agende dentista amanhã às 10", "", "", "calendar-event-create"),  # validate: allow english-only -- a line the person types in Portuguese
    ("Agende dentista amanhã às 10 no google", "", "", "calendar-event-create"),  # validate: allow english-only -- a line the person types in Portuguese
    ("marca na agenda dentista quinta às 10", "event-create", "", "calendar-event-create"),  # validate: allow english-only -- a line the person types in Portuguese
    ("remova a reunião da agenda", "", "event-cancel", ""),  # validate: allow english-only -- a line the person types in Portuguese
    ("cancela o dentista da agenda", "", "event-cancel", ""),  # validate: allow english-only -- a line the person types in Portuguese
    ("muda a reunião na agenda para as 11", "event-change", "event-change", "remind"),  # validate: allow english-only -- a line the person types in Portuguese
    ("remove the meeting from my calendar", "", "event-cancel", ""),
    ("cancel the dentist on my calendar", "", "event-cancel", ""),
    ("move the meeting on my calendar to 11", "", "event-change", ""),
    ("schedule a dentist visit tomorrow at 10", "", "", "calendar-event-create"),
    ("mostra minha agenda e cancela o dentista", "", "", ""),  # validate: allow english-only -- a line the person types in Portuguese
    ("show my calendar and delete the meeting", "", "", ""),
]


@pytest.mark.parametrize("line", CALENDAR_READS)
def test_a_calendar_read_in_words_is_the_tier_1_form_of_items_and_says_calendar(line):
    found = natural.match(line)
    assert found is not None and found["op"] == "items" and found["args"] == {}, found
    assert natural_writes.items_kind(line) == "calendar"


def test_the_mail_forms_still_say_mail_and_the_events_form_says_calendar():
    for line in ("liste meus emails", "show my emails", "what emails do i have"):
        assert natural.match(line)["op"] == "items" and natural_writes.items_kind(line) == "mail", line
    for line in ("mostre meus eventos", "show my events"):
        assert natural.match(line)["op"] == "items" and natural_writes.items_kind(line) == "calendar", line


@pytest.mark.parametrize("line,written,verb,candidate", NOT_CAUGHT)
def test_a_write_that_names_the_agenda_is_no_tier_1_form_and_reaches_the_path_it_reached_before(line, written, verb, candidate):
    assert natural.match(line) is None
    got = natural_writes.candidate(line)
    assert (got["op"] if got else "") == written
    assert (event_lookup.verb_op(line) or "") == verb
    assert ((natural.candidate(line) or {}).get("op") or "") == candidate


@pytest.fixture
def widened():
    """A function: the shipped tables with one more `items` form (the planted fault). `natural` caches the compiled forms by the id of a table, and an id is reused once a table is
    freed, so each copy is kept alive for the test and its cache entry is dropped before and after."""
    kept = []

    def make(form):
        tables = copy.deepcopy(nt.languages())
        for table in tables:
            table["requests"]["forms"]["items"] = [*table["requests"]["forms"]["items"], form]
            natural._COMPILED.pop(id(table), None)
        kept.append(tables)
        return tables
    yield make
    for tables in kept:
        for table in tables:
            natural._COMPILED.pop(id(table), None)


@pytest.mark.parametrize("form,line", [
    (r"(remova|cancela) (a reuniao|o dentista) da agenda", "cancela o dentista da agenda"),
    (r"muda a reuniao na agenda( para as 11)?", "muda a reuniao na agenda para as 11"),
    (r"(remove|cancel) the (meeting|dentist) (from|on) my calendar", "cancel the dentist on my calendar"),
])
def test_vacuity_a_form_that_is_too_wide_catches_the_write_and_the_same_oracle_sees_it(widened, form, line):
    tables = widened(form)
    assert natural.match(line, tables)["op"] == "items"
    with pytest.raises(AssertionError):
        assert natural.match(line, tables) is None
