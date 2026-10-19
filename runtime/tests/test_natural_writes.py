"""The natural writes (package NR-5, runtime/natural_writes.py and the family modules): the shape of the language data, the registry of the families, the toolkit the
families read lines with, and (further down) each form of the calendar and files families in pt-BR and en. Pure: no store, no model, no network, no clock but the one
a test passes. Every name, address and file is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st

natural = st.load("natural")
nw = st.load("natural_writes")


def tables():
    return nw._tables()


def test_every_shipped_table_has_writes_of_the_shape_the_schema_asks():
    for table in tables():
        assert nw.writes_of(table), table["tag"]
        nw.check_writes(table)
        natural.check_requests(table)


def test_no_phrase_of_writes_holds_a_character_a_regular_expression_means_anything_by():
    for table in tables():
        body = nw.writes_of(table)
        for key in nw.TOP_KEYS:
            assert all(re.fullmatch(r"[a-z0-9]+( [a-z0-9]+)*", p) for p in body[key])
        for section, keys in nw.SECTIONS.items():
            for key in keys:
                assert all(re.fullmatch(r"[a-z0-9]+( [a-z0-9]+)*", p) for p in body[section].get(key, [])), (table["tag"], section, key)


def test_the_mail_lists_are_there_for_the_mail_package_to_fill():
    for table in tables():
        assert set(nw.writes_of(table)["mail"]) == set(nw.SECTIONS["mail"])


def test_a_phrase_with_a_regular_expression_character_or_an_unknown_key_is_refused():
    base = {"tag": "xx", "requests": {"writes": {"polite": ["please."]}}}
    with pytest.raises(ValueError, match="no regular-expression character"):
        nw.check_writes(base)
    with pytest.raises(ValueError, match="has no key 'bogus'"):
        nw.check_writes({"tag": "xx", "requests": {"writes": {"bogus": []}}})
    with pytest.raises(ValueError, match="writes is an object"):
        natural.check_requests({"tag": "xx", "requests": {"writes": ["x"]}})


def test_the_registry_names_the_families_and_every_operation_has_one():
    assert set(nw.FAMILIES) <= {"calendar", "files", "mail"}
    assert {name for name, cls in natural.CLASSES.items() if cls == "E"} == set(nw.OP_FAMILY)


def test_line_gives_back_the_persons_words_not_the_folded_ones():
    line = nw.Line("  Manda  PARA Bia: Até Amanha  ")
    start, end = line.find(["para"])
    assert line.span(start, end) == "PARA"
    assert line.span(*line.find(["ate"])) == "Até"


@pytest.mark.parametrize("text, expected", [("2", [2]), ("2, 4 e 7", [2, 4, 7]), ("1 a 3", [1, 2, 3]), ("#5", [5]), ("2 e 2", None), ("0", None), ("2 mas 3", None),
                                            ("3 a 2", None), ("1 a 40", None), ("", None)])
def test_numbers_reads_a_list_of_references_and_nothing_else(text, expected):
    line = nw.Line(text)
    assert nw.numbers(line, 0, len(line.norm), tables()) == expected


def test_a_service_word_names_an_account_only_with_its_introducing_word_or_by_itself_when_it_is_two_words():
    t = tables()
    for text, expected in [("salva no drive", "google"), ("save it to my onedrive", "microsoft"), ("add to my google calendar", "google"),
                           ("reuniao do google", None), ("no outlook e no gmail", None), ("sem conta", None)]:
        found = nw.service(nw.Line(text), t)
        assert (found[0] if found else None) == expected, text


def test_a_reminder_trigger_outside_the_text_spans_makes_the_line_no_write_form():
    t = tables()
    line = nw.Line("manda tal coisa e me lembra amanha")
    assert nw.reminder_outside(line, t, {}) is True
    start = line.norm.index("me lembra")
    assert nw.reminder_outside(line, t, {"body": (0, len(line.norm))}) is False
    assert nw.reminder_outside(nw.Line("sem gatilho"), t, {}) is False
    assert start > 0


def test_a_line_over_the_word_cap_or_with_a_mention_or_a_slash_is_never_claimed():
    assert nw._claim("marca dentista quinta") is True
    assert nw._claim(" ".join(["a"] * (nw.LINE_WORDS_MAX + 1))) is False
    assert nw._claim("marca @inbox quinta") is False
    assert nw._claim("manda para bia@exemplo.example") is True
    assert nw._claim("/remind 10 x") is False
    assert nw._claim("   ") is False
# chunk:forms


# --- the forms of the calendar and files families ------------------------------------------------------------------------------------------------------

import datetime  # noqa: E402

import natural_writes_cases_pt_br as lines  # noqa: E402

NOW = datetime.datetime(2026, 10, 19, 9, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))      # Monday


def slots_of(line, now=NOW):
    got = nw.read(line, now)
    return None if got is None else (got["op"], got["slots"], got)


@pytest.mark.parametrize("line, op, expected", lines.CASES, ids=[c[0][:48] for c in lines.CASES])
def test_each_form_gives_its_operation_and_exactly_the_slots_the_line_holds(line, op, expected):
    found = slots_of(line)
    if op is None:
        assert found is None, found
        return
    assert found is not None, line
    got_op, slots, reading = found
    assert got_op == op
    shown = {k: v for k, v in slots.items() if not k.startswith("_")}
    if "account" in expected and expected["account"] is None:      # a Google Doc names the account by its kind, not by a service word
        expected = {k: v for k, v in expected.items() if k != "account"}
    assert shown == expected, (line, shown)
    assert reading["family"] == nw.OP_FAMILY[op]


def test_a_text_slot_is_the_persons_own_words_verbatim_and_never_rewritten():
    got = nw.read("cria um arquivo chamado Ideias.MD com o texto: Comprar TINTA azul!!", NOW)
    assert got["slots"]["name"] == "Ideias.MD" and got["slots"]["content"] == "Comprar TINTA azul!!"
    assert got["spans"] == {"name": "Ideias.MD", "content": "Comprar TINTA azul!!"}
    got = nw.read("muda o título do evento 2 para  Dentista, de novo. ", NOW)
    assert got["slots"]["title"] == "Dentista, de novo."


def test_a_line_that_repeats_is_read_as_a_refusal_never_as_a_single_event():
    for text in lines.RECURRING:
        got = nw.read(text, NOW)
        assert got is not None and got["op"] == "event-create" and got["recurring"] is True and "start" not in got["slots"], text


def test_the_order_of_recognition_puts_the_write_heads_before_the_calendar_verb_and_a_reminder_stays_a_reminder():
    assert nw.candidate("marca dentista quinta às 10h") == {"family": "calendar", "op": "event-create"}
    assert nw.candidate("me lembra quinta às 10h do dentista") is None
    assert nw.candidate("remind me Thursday at 10am to call the dentist") is None
    assert nw.candidate("marca yoga amanhã às 7h e me lembra de levar a toalha") is None, "a reminder trigger outside a body span is two requests"
    assert nw.candidate("cancela o evento 4") == {"family": "calendar", "op": "event-cancel"}
    assert nw.candidate("cancela o lembrete 4") is None


def test_a_loose_scheduling_verb_stays_the_question_of_nr_1_and_is_read_only_when_the_operation_is_fixed():
    assert nw.candidate("agende reunião amanhã 10h") is None, "event or something else is asked first (decision D3)"
    got = nw.read("agende reunião amanhã 10h", NOW, op="event-create")
    assert got["slots"] == {"title": "reunião", "start": "2026-10-20T10:00"}
    assert nw.read("pon al dentista en mi calendario", NOW, op="event-create") is None, "no head and no time: nothing says it is an event"


def test_the_clock_free_candidate_and_the_read_agree_on_what_is_a_write_form():
    for line, op, _ in lines.CASES:
        found = nw.candidate(line)
        assert (found or {}).get("op") == op, line


def test_the_time_is_pinned_to_the_moment_the_line_was_read():
    got = nw.read("marca dentista daqui a 2 horas", NOW)
    assert got["slots"]["start"] == "2026-10-19T11:00" and got["reading"]["relative"]
    later = nw.read("marca dentista daqui a 2 horas", NOW + datetime.timedelta(minutes=30))
    assert later["slots"]["start"] == "2026-10-19T11:30"


def test_a_range_whose_end_is_not_after_its_start_is_marked_so_the_end_is_asked():
    got = nw.read("marca yoga amanhã das 8h às 7h", NOW)
    assert got["end_ok"] is False and "end" not in got["slots"] and got["slots"]["start"] == "2026-10-20T08:00"


def test_a_reading_the_engine_is_unsure_of_is_carried_as_a_doubt_not_as_a_question():
    got = nw.read("marca festa de natal quinta às 10h", NOW)
    assert got is not None and got["doubt"] is True and got["slots"]["start"] == "2026-10-22T10:00", "a holiday word left in the title is checked on the card, never silently dropped"


def test_the_write_mode_of_the_engine_leaves_the_results_of_nr_1_unchanged():
    assert natural.understand("dentista quinta às 10h", NOW, "write")["ask"]["need"] == "confirm"
    first = natural.understand("me lembra amanhã às 9h de ligar para a gráfica", NOW, "trigger")
    assert first["ask"]["need"] == "confirm" and first["ask"]["text"] == "ligar para a gráfica"
