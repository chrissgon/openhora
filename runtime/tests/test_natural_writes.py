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
    not_in_a_family = {"todo-add", "todo-done"}      # CB-5: the to-do list's cards are opened by runtime/ops_todo.py (the interpreter's branch), never by a natural-writes family
    assert {name for name, cls in natural.CLASSES.items() if cls == "E"} - not_in_a_family == set(nw.OP_FAMILY)
    assert not not_in_a_family & set(nw.OP_FAMILY)


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


def test_a_line_that_repeats_is_read_as_a_refusal_never_as_a_single_event_at_catalog_version_1(monkeypatch):
    monkeypatch.setattr(st.load("operations"), "LINE_CATALOG", 1)      # CB-9: since version 2 the closed forms do not claim a repeating line (the next test)
    for text in lines.RECURRING:
        got = nw.read(text, NOW)
        assert got is not None and got["op"] == "event-create" and got["recurring"] is True and "start" not in got["slots"], text


def test_since_catalog_version_2_a_line_that_repeats_is_no_write_form_and_goes_on_to_the_interpreter(monkeypatch):
    monkeypatch.setattr(st.load("operations"), "LINE_CATALOG", 2)
    for text in lines.RECURRING:
        assert nw.read(text, NOW) is None and nw.candidate(text) is None, text
        assert nw.read(text, NOW, op="event-create") is not None, "the operation fixed by the interpreter's decision still reads it: only the claim of the closed form is gone"


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


@pytest.mark.parametrize("said, kind", [("Evento no calendário", "event"), ("quero como evento", "event"), ("na agenda", "event"), ("no calendário", "event"), ("um evento", "event"),
                                        ("um lembrete", "notice"), ("lembrete aqui", "notice"), ("Quero como lembrete", "notice"), ("an event in the calendar", "event"),
                                        ("a reminder here", "notice"), ("I want it as an event please", "event"), ("outra coisa", "other"),
                                        ("um evento ou um lembrete", None), ("evento amanhã às 9", None), ("um evento no banco", None), ("talvez", None), ("", None)])
def test_the_kind_a_person_names_is_read_with_the_closed_words_around_it_and_nothing_open(said, kind):
    assert natural.answer_kind(said) == kind


def test_a_reply_to_the_kind_question_is_asked_once_more_up_to_eight_words_but_a_question_or_a_request_is_a_new_line():
    assert natural.short_answer("talvez mais tarde, ainda não sei", wide=True) and not natural.short_answer("talvez mais tarde, ainda não sei")
    assert not natural.short_answer("quando abre a loja", wide=True) and not natural.short_answer("quanto custa o evento?", wide=True)
    assert not natural.short_answer("me lembra amanhã às 9 de pagar a luz", wide=True), "a reminder of its own is a new line"
    assert not natural.short_answer(" ".join(["palavra"] * 9), wide=True)


def test_hours_written_bare_behind_a_range_marker_are_a_range_to_check_and_a_pair_that_could_be_the_afternoon_is_not_read():
    got = nw.read("marca reunião quinta de 13 a 15", NOW)
    assert got["slots"] == {"title": "reunião", "start": "2026-10-22T13:00", "end": "2026-10-22T15:00"} and got["doubt"] is True
    early = nw.read("marca reunião quinta de 1 a 3", NOW)
    assert "start" not in early["slots"] and "end" not in early["slots"], "1 to 3 could be the night or the afternoon: not read, the time is asked"
    assert nw.read("marca reunião quinta das 13h às 15h", NOW)["doubt"] is False


def test_a_number_left_among_the_words_of_the_title_is_checked_on_the_card_as_a_doubt():
    stray = nw.read("marca prova 20 às 14h", NOW)
    assert stray["slots"]["start"] == "2026-10-19T14:00" and stray["slots"]["title"] == "prova 20" and stray["doubt"] is True, "20 may be a day: checked on the card, never a silent title"
    assert nw.read("marca dentista quinta às 10h", NOW)["doubt"] is False


def test_the_provenance_check_pairs_an_end_with_its_start():
    accounts = {"google": {"calendars": {}}}
    said = ["marca reunião quinta das 13h às 15h"]
    ok = nw.problems("event-create", {"title": "reunião", "start": "2026-10-22T13:00", "end": "2026-10-22T15:00"}, said, accounts, {}, NOW)
    assert not [p for p in ok if "after start" in p]
    other_day = nw.problems("event-create", {"title": "reunião", "start": "2026-10-22T13:00", "end": "2026-10-23T15:00"}, said, accounts, {}, NOW)
    before = nw.problems("event-create", {"title": "reunião", "start": "2026-10-22T15:00", "end": "2026-10-22T13:00"}, said, accounts, {}, NOW)
    assert any("after start" in p for p in other_day) and any("after start" in p for p in before)


@pytest.mark.parametrize("line", ["marca reunião 3 às 10h", "marca sala 3 às 10h", "marca reunião com 2 às 15h", "marca aula 4 às 18h", "marca reunião quinta 3 às 10h", "marca reunião quinta 10 às 11h",
                                  "marca reunião quinta 1-3h", "marca reunião quinta 5-6h", "marca reunião quinta 13-15h", "marca reunião quinta de 13 a 15", "add to my calendar meeting Thursday 1-2pm"])
def test_a_number_beside_a_clock_is_never_silently_an_hour_the_card_is_preceded_by_the_check_line(line):
    assert nw.read(line, NOW)["doubt"] is True, line


@pytest.mark.parametrize("line", ["marca reunião dia 12 às 14h", "marca jantar dia 21 às 22h", "marca consulta no dia 5 às 9h", "remarca o evento 2 para dia 12 às 14h"])
def test_the_number_after_a_day_word_is_the_day_never_an_hour(line):
    got = nw.read(line, NOW)
    assert got["slots"]["start"][11:] in ("14:00", "22:00", "09:00") and "end" not in got["slots"] and got["slots"]["start"][:10] != "2026-10-19", line


def test_a_range_is_never_longer_than_twelve_hours_and_a_pair_below_seven_is_not_read():
    long = nw.read("marca reunião quinta das 7 às 23", NOW)
    assert "end" not in long["slots"], "16 hours: no range"
    assert "end" not in nw.read("marca reunião quinta 1-3h", NOW)["slots"] and "end" not in nw.read("marca reunião quinta 5-6h", NOW)["slots"]


def test_the_fuzz_checker_reads_ranges_with_its_own_table_and_does_not_accept_a_misreading_of_the_parser():
    accounts = {"google": {"calendars": {}}}
    ok = nw.problems("event-create", {"title": "reunião", "start": "2026-10-22T13:00", "end": "2026-10-22T15:00"}, ["marca reunião quinta 13-15h"], accounts, {}, NOW)
    assert not [p for p in ok if "start" in p or "end" in p]
    for said, start in (("marca reunião dia 12 às 14h", "2026-10-19T12:00"), ("marca reunião 3 às 10h", "2026-10-19T03:00"), ("marca reunião quinta 1-3h", "2026-10-22T01:00")):
        bad = nw.problems("event-create", {"title": "reunião", "start": start, "end": start[:11] + "14:00"}, [said], accounts, {}, NOW)
        assert any("start" in p for p in bad), (said, bad)
