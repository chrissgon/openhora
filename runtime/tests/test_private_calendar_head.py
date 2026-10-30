"""PRIVATE-CALENDAR-HEAD: a line that starts with a calendar head ("agende", "agendar", "schedule", "book") and holds a time is a private write, as "marca ..." has been since S41-9.

The head words are data (`runtime/registry/private_words.json`, `lead_with_time` of each language); the time reader is `natural_time.find` and any hit counts, a day alone included
(the decision of 2026-10-30, OPEN-PCH-1). The maintainer accepted the 11 corpus lines that became private and the over-fire class, work requests that start with the head and a time
("schedule a post for tomorrow at 9am"): OPEN-PCH-2, "Aceito (Recomendado)". `docs/decisions/2026-10-30-private-calendar-head.md` carries both.

What is proven here, every expectation a literal of this file (the oracle is the literal, never the data under test):

  1. the oracle: each shape, in both languages, is a "write" for `turn_gate.private_kind`, and `turn_gate.new_request` says "write" for it as it did before;
  2. a twin for each shape that lacks the time or the head: it keeps the verdict it had (None, or "reminder" for the bare noun "agenda");
  3. downstream: the stored line is the neutral word and a sender the interpreter does not read gets the typed sentence of the writes; the twin is stored as written and gets none;
  4. the accepted lines and the over-fire class are pinned, so that a later change to the rule shows here first;
  5. structural: the calendar verbs of each language table are all in `lead_with_time`;
  6. vacuity: a copy of the data without "agende" and "schedule" fails the oracle and the structural check, and a planted wrong result fails the comparison.

Offline, no model, no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_private_calendar_head.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "runtime"))

import natural_time as nt  # noqa: E402
import ops_natural  # noqa: E402
import ops_turn  # noqa: E402
import phrase_kit as pk  # noqa: E402
import registry_data  # noqa: E402
import turn_gate  # noqa: E402
from test_registry_data import data_copy, write  # noqa: E402,F401  (the copy of the registry folder and its writer)

PT = {"language": "pt-BR"}
EN = {"language": "en"}

PT_WRITES = [      # validate: allow english-only -- the Portuguese lines under test
    "Agende corte de cabelo amanhã às 14h",      # validate: allow english-only -- the Portuguese line under test
    "agendar a revisão do carro sexta às 10h",      # validate: allow english-only -- the Portuguese line under test
    "por favor agende uma reunião com a Bia amanhã às 9h",      # validate: allow english-only -- the Portuguese line under test
    "pode agendar o dentista quinta às 10h?",
    "agende corte de cabelo amanhã",      # validate: allow english-only -- the Portuguese line under test
]
EN_WRITES = [
    "schedule a haircut tomorrow at 2pm",
    "book the vet on monday at 9am",
    "can you book a table friday at 8pm?",
    "schedule a haircut tomorrow",
]
PT_TWINS = [      # validate: allow english-only -- the Portuguese lines under test
    "agende corte de cabelo",
    "agende",
    "o que tenho na agenda amanhã às 14h?",      # validate: allow english-only -- the Portuguese line under test
    "agenda de amanhã",      # validate: allow english-only -- the Portuguese line under test
]
EN_TWINS = [
    "schedule a haircut",
    "schedule",
    "book",
    "what's on my calendar tomorrow at 2pm?",
    "scheduled posts for tomorrow at 9am?",
]

ACCEPTED = [      # validate: allow english-only -- the lines that became private (11), the Portuguese ones among them
    "Agende corte de cabelo amanhã às 14h",      # validate: allow english-only -- the Portuguese line under test
    "agende o fisioterapeuta sexta 9h",
    "agendar consulta com a dra. Helena dia 22 às 16h",
    "book an appointment with Dr. Helena on the 22nd at 4pm",
    "book the dentist friday at 9am",
    "schedule a meeting with Marta tomorrow at 2pm",
    "book dinner with Tobias on friday at 7pm",
    "schedule piano practice every day at 6pm",
    "book lunch with Priya wednesday 8am on Outlook",
    "book lunch with Priya wednesday 8 am on Outlook",
    "schedule Atlas project handoff for wednesday 8am",
]
OVER_FIRE = [      # validate: allow english-only -- work requests that start with the head and a time: accepted (OPEN-PCH-2), they are stored as the neutral word
    "schedule a post for tomorrow at 9am",
    "schedule the newsletter for friday at 10am",
    "agende a publicação do post amanhã às 9h",      # validate: allow english-only -- the Portuguese line under test
    "agendar o envio da campanha segunda 8h",
    "schedule a deploy for tonight at 11pm",
    "book club tomorrow at 7pm",
]


def planted_wrong(kind):
    """The wrong result the vacuity case plants: the verdict the base had for a head line (None)."""
    return None


# --- 1. the oracle ------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("line", PT_WRITES + EN_WRITES)
def test_a_calendar_head_with_a_time_is_a_private_write(line):
    assert turn_gate.private_kind(line) == "write"
    assert turn_gate.new_request(line) == "write"


def test_the_kind_changes_from_reminder_to_write_when_a_polite_word_leads():
    """`please` is no work starter, so the bare step read this line as a reminder before; the head now makes it a write."""
    assert turn_gate.private_kind("please schedule a call with Ana tomorrow at 3pm") == "write"
    assert turn_gate.new_request("please schedule a call with Ana tomorrow at 3pm") == "write"


# --- 2. the twins -------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("line", PT_TWINS + EN_TWINS + ["/remind 14:00 corte de cabelo"])      # validate: allow english-only -- the Portuguese lines under test
def test_a_line_without_the_time_or_the_head_stays_unflagged(line):
    assert turn_gate.private_kind(line) is None


def test_the_noun_agenda_and_the_reminder_noun_keep_their_kind():
    """GUARD-BARE-AGENDA does not join (OPEN-PCH-3): the noun "agenda" is no calendar head, and a reminder stays a reminder."""
    assert turn_gate.private_kind("agenda corte de cabelo amanhã às 14h") == "reminder"      # validate: allow english-only -- the Portuguese line under test
    assert turn_gate.private_kind("schedule a reminder for tomorrow at 9") == "reminder"


def test_the_twin_of_every_shape_is_the_same_line_without_one_part():
    """Each twin above is a line that holds the head without a time, or a time without the head; the oracle lines are not among them."""
    assert not set(PT_TWINS + EN_TWINS) & set(PT_WRITES + EN_WRITES)


# --- 3. downstream ------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("line", [PT_WRITES[0], PT_WRITES[2]])
def test_the_pt_br_line_is_stored_as_the_neutral_word_and_gets_the_typed_sentence(line):
    ctx = {"cfg": PT}
    stored = ops_natural.stored_line(ctx, line)
    pk.assert_said(stored, "NW_PRIVATE_LINE", PT)
    assert stored != line
    pk.assert_said(ops_turn.typed_sentence(ctx, line, "telegram:x"), "IX_TYPE_WRITE", PT)


def test_the_en_line_is_stored_as_the_neutral_word_and_gets_the_typed_sentence():
    ctx = {"cfg": EN}
    stored = ops_natural.stored_line(ctx, EN_WRITES[0])
    pk.assert_said(stored, "NW_PRIVATE_LINE", EN)
    assert stored != EN_WRITES[0]
    pk.assert_said(ops_turn.typed_sentence(ctx, EN_WRITES[0], "telegram:x"), "IX_TYPE_WRITE", EN)


def test_the_twin_is_stored_as_written_and_gets_no_sentence():
    ctx = {"cfg": EN}
    assert ops_natural.stored_line(ctx, "schedule a haircut") == "schedule a haircut"
    assert ops_turn.typed_sentence(ctx, "schedule a haircut", "telegram:x") is None
    ctx = {"cfg": PT}
    assert ops_natural.stored_line(ctx, "agende corte de cabelo") == "agende corte de cabelo"      # validate: allow english-only -- the Portuguese line under test
    assert ops_turn.typed_sentence(ctx, "agende corte de cabelo", "telegram:x") is None      # validate: allow english-only -- the Portuguese line under test


# --- 4. the accepted lines and the over-fire class -------------------------------------------------------------------------------------------------------

def test_the_eleven_accepted_lines_are_private_writes_and_were_requests_before():
    assert len(ACCEPTED) == 11 and len(set(ACCEPTED)) == 11
    for line in ACCEPTED:
        assert turn_gate.private_kind(line) == "write", line
        assert turn_gate.new_request(line) == "write", line


def test_the_over_fire_class_is_pinned_as_accepted():
    """Work requests that start with a head and a time are stored as the neutral word (OPEN-PCH-2). A later narrowing of the rule must change this list on purpose."""
    for line in OVER_FIRE:
        assert turn_gate.private_kind(line) == "write", line


# --- 5. structural ------------------------------------------------------------------------------------------------------------------------------------

def head_failures(data=None):
    """The calendar verbs of each language table that `lead_with_time` of that language does not hold."""
    path = registry_data.FOLDER if data is None else data
    words = json.loads((Path(path) / "private_words.json").read_text(encoding="utf-8"))["languages"]
    failures = []
    for table in nt.languages():
        have = set(words.get(table["tag"], {}).get("lead_with_time", []))
        for word in table["triggers"]["calendar_verb"] + table["triggers"]["calendar_loose"]:
            if registry_data_fold(word) not in have:
                failures.append((table["tag"], word))
    return failures


def registry_data_fold(word):
    """The fold the data file uses: lower case, no accent."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", word.lower()) if not unicodedata.combining(c))


def test_every_calendar_verb_of_a_language_table_is_a_lead_with_time():
    assert head_failures() == []
    expected = {"en": {"book", "schedule"}, "pt-BR": {"agendar", "agende", "marca", "marcar", "marque"}}
    words = json.loads((REPO / "runtime/registry/private_words.json").read_text(encoding="utf-8"))["languages"]
    for tag, heads in expected.items():
        assert heads <= set(words[tag]["lead_with_time"]), tag


# --- 6. vacuity ---------------------------------------------------------------------------------------------------------------------------------------

def test_a_copy_of_the_data_without_the_heads_fails_the_oracle_and_the_structural_check(data_copy):
    """The real data is the control: it passes. Without "agende" and "schedule" the two oracle lines are unflagged and the structural check names them."""
    assert turn_gate.private_kind("Agende corte de cabelo amanhã às 14h") == "write"      # validate: allow english-only -- the Portuguese line under test
    assert turn_gate.private_kind("schedule a haircut tomorrow at 2pm") == "write"
    assert head_failures(data_copy) == []
    data = json.loads((data_copy / "private_words.json").read_text(encoding="utf-8"))
    data["languages"]["pt-BR"]["lead_with_time"].remove("agende")
    data["languages"]["en"]["lead_with_time"].remove("schedule")
    write(data_copy, "private_words", data)
    assert turn_gate.private_kind("Agende corte de cabelo amanhã às 14h") is None      # validate: allow english-only -- the Portuguese line under test
    assert turn_gate.private_kind("schedule a haircut tomorrow at 2pm") is None
    assert head_failures(data_copy) == [("en", "schedule"), ("pt-BR", "agende")]


def test_a_planted_wrong_result_fails_the_comparison():
    """The oracle compares to a literal: planting the verdict of the base (None) for a head line makes the same comparison fail."""
    line = "schedule a haircut tomorrow at 2pm"
    assert turn_gate.private_kind(line) == "write"
    assert planted_wrong(turn_gate.private_kind(line)) != "write"
    with pytest.raises(AssertionError):
        assert planted_wrong(turn_gate.private_kind(line)) == "write"
