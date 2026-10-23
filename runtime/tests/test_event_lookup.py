"""An event of the person's own calendar named by its words (slice S6, runtime/event_lookup.py with the seam in runtime/ops_interpret.py `_carry_out`).

The live case (2026-10-21, a pt-BR project): a line asking to remove the haircut for tomorrow was answered "ask in Portuguese or in English", a false sentence. Here the real calendar
snapshots (test_calendar_write.py's world, the stand-in providers of test_sources_mail.py), the real family path and the real card, a stand-in clock (Wednesday 2026-10-21 15:00 at -03:00),
no model text trusted: the decision is the one `check` believes for a hand-written model text. Every expectation is a literal of this file, the events and the sentences included; each
oracle reads the card's own lines or the sentence, never the code under test, and the vacuity tests plant a wrong result to show the oracle can fail. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_lookup.py
"""
from __future__ import annotations

import datetime
import json

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_ops_natural_writes import forget  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_items = st.load("ops_items")
ops_natural = st.load("ops_natural")
event_lookup = st.load("event_lookup")
interpreter_route = st.load("interpreter_route")

OWNER, TALKER = "telegram:4242", "telegram:5151"
PROFILES = {"owner": ["read", "talk", "calendar-write", "ask-mail", "interpret"], "talker": ["read", "talk", "calendar-write", "interpret"]}
IDS = {"owner": "4242", "talker": "5151"}
UTC = datetime.timezone.utc
ZONE = "America/Sao_Paulo"
LIVE = "Remova o corte de cabelo pra amanha da agenda"  # validate: allow english-only -- the Portuguese line or sentence under test
# The calendar, in the order the snapshot numbers it (by day, then start): (day, start, end, title, provider id).
EVENTS = [
    ("21", "09:00", "10:00", "Dentist", "evden"),            # 1  Wednesday 21/10, today
    ("22", "13:00", "14:00", "corte de cabelo", "evhair22"),     # 2  Thursday 22/10, tomorrow
    ("22", "18:00", "19:00", "Yoga", "evyoga"),               # 3  Thursday 22/10
    ("23", "13:00", "14:00", "corte de cabelo", "evhair23"),     # 4  Friday 23/10
    ("25", "08:00", "09:00", "Consulta Dra Lima", "evcons"),   # 5  Sunday 25/10
]
CANCEL = '{"v":1,"kind":"op","op":"event-cancel","slots":{}}'
ALLOWED = {"event-cancel", "event-change", "event-create", "mail-archive"}


def op_text(name, slots=None, **more):
    return json.dumps({"v": 1, "kind": "op", "op": name, "slots": slots or {}, **more}, ensure_ascii=False)


def build(world, monkeypatch, language="pt-BR", events=EVENTS):
    """The world: the language, two listed senders (the owner may read a snapshot, the talker may not), one Google calendar source `agenda` read on 2026-10-21, the clock, and
    the provider's own copy of every event (the card is made from the event as the provider holds it)."""
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw.update(language=language, policies=PROFILES, channels={"page": ["read", "calendar-write"]},
               messaging={"senders": {"telegram": [{"id": IDS[name], "policy": name} for name in PROFILES]}})
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    clock = Clock(monkeypatch, wall="2026-10-21 15:00")
    snaps = Snapshots(world, monkeypatch)
    snaps.now = datetime.datetime(2026, 10, 21, 17, 0, tzinfo=UTC)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: snaps.now)
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    provided = []
    for day, start, end, title, ident, *more in events:
        provided.append(tsm.event(len(provided) + 1, f"2026-10-{day}T{start}:00-03:00", f"2026-10-{day}T{end}:00-03:00", title, id=ident, **(more[0] if more else {})))
        world["google"].add_event(ident, title, {"dateTime": f"2026-10-{day}T{start}:00-03:00"}, {"dateTime": f"2026-10-{day}T{end}:00-03:00"})
    snaps.calendar("agenda", "google", fgw.CALENDAR, provided)
    world["clock"], world["snaps"] = clock, snaps
    return world


def decision(line, text):
    now = ops_natural._clock()
    got = ops_interpret.decide(line, text, now, ZONE, ALLOWED)
    assert got["kind"] == "op", got
    return got


def carry(world, line, text, sender=OWNER):
    """(the reply, extras) of the decision a model text makes for the line, carried out through the real seam."""
    ctx = ops_core.context(world["path"])
    extras = {}
    got = ops_interpret._carry_out(world["path"], ctx, decision(line, text), line, sender, extras)
    return got[0], extras


def card(world, extras):
    return ops.pending(world["path"], extras["resend"])


def reads_only(world):
    return [r for r in world["google"].requests if r["method"] != "GET" and not r["path"].endswith("/token")]


def card_problems(item, ref, title, when):
    """What is wrong with a card, read from its own lines: the event it names (`<source>#<n>`, the provider's title) and the time it shows."""
    lines = item["body"].splitlines()
    wanted = [f"Named as {ref}, from the snapshot read at 2026-10-21T17:00:00Z.", f"Removing, title: {title}", f"When: {when} (America/Sao_Paulo)",
              "Account: google (pat@example.com)"]
    return [w for w in wanted if w not in lines]


def test_the_live_line_opens_the_cancel_card_of_the_one_event_tomorrow(world, monkeypatch):
    build(world, monkeypatch)
    reply, extras = carry(world, LIVE, CANCEL)
    item = card(world, extras)
    assert reply == "O card #1 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test
    assert card_problems(item, "agenda#2", "corte de cabelo", "Thu 22/10/2026 13:00-14:00") == []
    assert "Event: evhair22" in item["body"].splitlines()
    assert reads_only(world) == [], "a card is opened; the approval writes"
    assert item["status"] == "open" and len(rows(world)[1]) == 1, "nothing is approved by this path"
    # the same card as the numbered form opens for the same event
    numbered = ops.natural_write(world["path"], "cancela o evento 2", channel="messaging", sender=OWNER)
    assert ops.pending(world["path"], numbered["resend"])["body"] == item["body"]


def test_the_oracle_of_the_card_fails_for_another_event(world, monkeypatch):
    build(world, monkeypatch)
    _, extras = carry(world, "Remova o corte de cabelo dia 23", CANCEL)
    other = card(world, extras)
    assert card_problems(other, "agenda#4", "corte de cabelo", "Fri 23/10/2026 13:00-14:00") == []
    assert card_problems(other, "agenda#2", "corte de cabelo", "Thu 22/10/2026 13:00-14:00") != [], "vacuity: the day-23 card is not the day-22 one"


def test_two_events_with_the_title_are_listed_by_the_numbers_of_the_snapshot_and_nothing_is_opened(world, monkeypatch):
    build(world, monkeypatch)
    reply, extras = carry(world, "Cancela o corte de cabelo", CANCEL)
    assert reply == ("Mais de um evento combina. Qual deles você quer cancelar?\n"      # validate: allow english-only -- the Portuguese line or sentence under test
                     "2. Thu 22/10/2026 13:00-14:00 · corte de cabelo\n4. Fri 23/10/2026 13:00-14:00 · corte de cabelo\n"
                     "Diga, por exemplo: cancela o evento 2.")      # validate: allow english-only -- the Portuguese line or sentence under test
    assert "resend" not in extras and rows(world) == ([], []) and extras["stored"] == "(pedido para as suas contas)"      # validate: allow english-only -- the Portuguese line or sentence under test
    # the numbered form that the list asks for opens the card of the number said
    numbered = ops.natural_write(world["path"], "cancela o evento 4", channel="messaging", sender=OWNER)
    assert card_problems(ops.pending(world["path"], numbered["resend"]), "agenda#4", "corte de cabelo", "Fri 23/10/2026 13:00-14:00") == []


def test_the_list_of_a_change_asks_for_the_number_and_the_new_time_in_english_too(world, monkeypatch):
    build(world, monkeypatch, language="en")
    reply, _ = carry(world, "Move the corte de cabelo to friday at 3pm", op_text("event-change", {"time": "friday at 3pm"}, time_iso="2026-10-23T15:00", weekday="fri"))
    assert reply == ("More than one event fits. Which one do you want to change?\n2. Thu 22/10/2026 13:00-14:00 · corte de cabelo\n"
                     "4. Fri 23/10/2026 13:00-14:00 · corte de cabelo\nSay its number and the new time, for example: move event 2 to Friday at 3 pm.")


@pytest.mark.parametrize("line, sentence", [
    ("Cancela a consulta", "Não encontrei nenhum evento com nome parecido nos próximos 30 dias. Peça a sua agenda para ver os eventos."),      # nor is the first word of a longer title  # validate: allow english-only -- the Portuguese line or sentence under test
    ("Cancela a aula de natação", "Não encontrei nenhum evento com nome parecido nos próximos 30 dias. Peça a sua agenda para ver os eventos."),  # validate: allow english-only -- the Portuguese line or sentence under test
    ("Remova o corte de cabelo de hoje", "Não encontrei nenhum evento com nome parecido nesse dia. Peça a sua agenda para ver os eventos."),      # the haircuts are tomorrow and the day after  # validate: allow english-only -- the Portuguese line or sentence under test
    ("Remova o Dentist pra amanha", "Não encontrei nenhum evento com nome parecido nesse dia. Peça a sua agenda para ver os eventos."),      # the dentist is today  # validate: allow english-only -- the Portuguese line or sentence under test
    ("Remova o corte de cabelo dia 24", "Não encontrei nenhum evento com nome parecido nesse dia. Peça a sua agenda para ver os eventos."),  # validate: allow english-only -- the Portuguese line or sentence under test
    ("Remova o yoga de sexta", "Não encontrei nenhum evento com nome parecido nos próximos 30 dias. Peça a sua agenda para ver os eventos."),      # a weekday: the yoga is on a Thursday  # validate: allow english-only -- the Portuguese line or sentence under test
])      # validate: allow english-only -- the Portuguese line or sentence under test
def test_a_title_that_only_partly_fits_or_falls_on_another_day_is_not_that_event(world, monkeypatch, line, sentence):
    build(world, monkeypatch)
    reply, extras = carry(world, line, CANCEL)
    assert reply == sentence and "resend" not in extras and rows(world) == ([], [])


def test_the_not_found_sentence_in_english(world, monkeypatch):
    build(world, monkeypatch, language="en")
    assert carry(world, "Cancel the swimming class", CANCEL)[0] == "I did not find an event with a similar name in the next 30 days. Ask for your calendar to see the events."


def test_a_day_the_words_name_narrows_the_list_to_that_day_and_a_weekday_to_its_dates(world, monkeypatch):
    build(world, monkeypatch)
    for line in ("Remova o corte de cabelo de sexta", "Remova o corte de cabelo 23/10", "Remova o corte de cabelo dia 23"):      # validate: allow english-only -- the Portuguese line or sentence under test
        _, extras = carry(world, line, CANCEL)
        assert card_problems(card(world, extras), "agenda#4", "corte de cabelo", "Fri 23/10/2026 13:00-14:00") == [], line


def test_a_day_code_cannot_read_is_asked_and_nothing_is_opened(world, monkeypatch):
    build(world, monkeypatch)
    for line in ("Remova o corte de cabelo dia 40", "Remova o corte de cabelo 31/02", "Remova o corte de cabelo na terça passada", "Remova o corte de cabelo hoje ou amanha"):  # validate: allow english-only -- the Portuguese line or sentence under test
        reply, extras = carry(world, line, CANCEL)
        assert reply == "Não consegui ler o dia que você quis dizer. Diga o nome do evento e o dia, por exemplo: amanhã ou 22/10." and "resend" not in extras, line      # validate: allow english-only -- the Portuguese line or sentence under test


def test_a_change_by_description_takes_the_new_time_from_the_verified_span_and_not_the_day_it_names(world, monkeypatch):
    build(world, monkeypatch)
    line = "Muda a consulta Dra Lima para as 10h do dia 23"
    reply, extras = carry(world, line, op_text("event-change", {"time": "as 10h do dia 23"}, time_iso="2026-10-23T10:00", weekday="fri"))
    item = card(world, extras)
    lines = item["body"].splitlines()
    assert "Named as agenda#5, from the snapshot read at 2026-10-21T17:00:00Z." in lines      # the consultation is on Sunday 25: the 23rd is the new day, not the event's
    assert "The event now is at: Sun 25/10/2026 08:00-09:00 (America/Sao_Paulo)" in lines
    assert "Before: When: Sun 25/10/2026 08:00-09:00 (America/Sao_Paulo)" in lines and "After: When: Fri 23/10/2026 10:00-11:00 (America/Sao_Paulo)" in lines
    assert "Unchanged: Title: Consulta Dra Lima" in lines, "only the time of the verified span changes"
    assert reads_only(world) == [] and item["status"] == "open"


def test_a_change_with_nothing_to_change_says_so_and_a_title_alone_is_a_change(world, monkeypatch):
    build(world, monkeypatch)
    reply, extras = carry(world, "Muda a consulta Dra Lima", op_text("event-change"))
    assert reply == "Achei o evento, mas não entendi o que mudar. Diga o novo dia e horário, ou o novo nome." and "resend" not in extras      # validate: allow english-only -- the Portuguese line or sentence under test
    _, extras = carry(world, "Renomeia a consulta Dra Lima para Retorno", op_text("event-change", {"title": "Retorno"}))
    lines = card(world, extras)["body"].splitlines()
    assert "Named as agenda#5, from the snapshot read at 2026-10-21T17:00:00Z." in lines and "After: Title: Retorno" in lines, lines


def test_a_sender_who_may_not_read_a_snapshot_learns_nothing_of_the_calendar(world, monkeypatch):
    build(world, monkeypatch)
    reply, extras = carry(world, LIVE, CANCEL, sender=TALKER)
    assert reply.startswith("As mensagens e os eventos são numerados num retrato") and "corte" not in reply and rows(world) == ([], [])      # validate: allow english-only -- the Portuguese line or sentence under test


def calendar_reads(world):
    """The reads of a calendar the stand-in provider has answered so far (the test's own count of the verbs it was sent)."""
    return [c for c in world["snaps"].providers.calls if c["cls"] != "reader:email"]


def add_new_event(world, title="reuniao com a Bia", day="24", ident="evnew"):
    """An event made after the snapshot was taken: the provider holds it, the snapshot does not."""
    start, end = f"2026-10-{day}T10:00:00-03:00", f"2026-10-{day}T11:00:00-03:00"
    world["snaps"].providers.events[("google", fgw.CALENDAR)].append(tsm.event(9, start, end, title, id=ident))
    world["google"].add_event(ident, title, {"dateTime": start}, {"dateTime": end})


def test_an_event_made_after_the_snapshot_is_found_after_one_refresh_and_its_card_opens(world, monkeypatch):
    build(world, monkeypatch)
    add_new_event(world)
    assert [e["title"] for e in event_lookup.events(ops_core.context(world["path"]), OWNER)[0]] != [], "the snapshot is readable"
    assert "reuniao com a Bia" not in [e["title"] for e in event_lookup.events(ops_core.context(world["path"]), OWNER)[0]], "control: the snapshot does not hold it yet"
    before = len(calendar_reads(world))
    reply, extras = carry(world, "Cancela a reuniao com a Bia", CANCEL)
    assert reply == "O card #1 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test
    assert len(calendar_reads(world)) - before == 1, "one read of the one calendar source"
    assert "Named as agenda#5, from the snapshot read at 2026-10-21T17:00:00Z." in card(world, extras)["body"].splitlines()
    assert reads_only(world) == [] and card(world, extras)["status"] == "open"


def test_a_second_miss_makes_exactly_one_provider_read_and_says_not_found(world, monkeypatch):
    build(world, monkeypatch)
    before = len(calendar_reads(world))
    reply, extras = carry(world, "Cancela a aula de natação", CANCEL)      # validate: allow english-only -- the Portuguese line or sentence under test
    assert reply == "Não encontrei nenhum evento com nome parecido nos próximos 30 dias. Peça a sua agenda para ver os eventos." and "resend" not in extras      # validate: allow english-only -- the Portuguese line or sentence under test
    assert len(calendar_reads(world)) - before == 1, "one read for the line, never a loop"
    carry(world, "Cancela a aula de natação", CANCEL)      # validate: allow english-only -- the Portuguese line or sentence under test
    assert len(calendar_reads(world)) - before == 2, "one more for the next line, and only one"


def test_a_hit_makes_no_provider_read(world, monkeypatch):
    build(world, monkeypatch)
    before = len(calendar_reads(world))
    carry(world, LIVE, CANCEL)
    assert len(calendar_reads(world)) == before


def test_a_sender_without_the_read_group_gets_no_refresh(world, monkeypatch):
    build(world, monkeypatch)
    add_new_event(world)
    before = len(calendar_reads(world))
    reply, _ = carry(world, "Cancela a reuniao com a Bia", CANCEL, sender=TALKER)
    assert reply.startswith("As mensagens e os eventos são numerados num retrato") and len(calendar_reads(world)) == before      # validate: allow english-only -- the Portuguese line or sentence under test


def test_a_failed_refresh_is_the_not_found_sentence_and_nothing_else(world, monkeypatch, capfd):
    build(world, monkeypatch)
    add_new_event(world)
    world["snaps"].providers.fail = tsm.Failure(reason="the provider said ZEBRA-SECRET")
    reply, extras = carry(world, "Cancela a reuniao com a Bia", CANCEL)
    assert reply == "Não encontrei nenhum evento com nome parecido nos próximos 30 dias. Peça a sua agenda para ver os eventos." and "resend" not in extras      # validate: allow english-only -- the Portuguese line or sentence under test
    assert "ZEBRA" not in reply + " ".join(capfd.readouterr())


def test_a_snapshot_older_than_26_hours_counts_as_a_miss_and_is_read_again(world, monkeypatch):
    build(world, monkeypatch)
    world["snaps"].later(hours=30)
    before = len(calendar_reads(world))
    reply, extras = carry(world, "Cancela o yoga", CANCEL)
    assert reply == "O card #1 espera a sua aprovação." and len(calendar_reads(world)) - before == 1      # validate: allow english-only -- the Portuguese line or sentence under test
    assert card(world, extras)["status"] == "open"


def test_a_stale_snapshot_that_cannot_be_read_again_is_the_not_found_sentence(world, monkeypatch):
    build(world, monkeypatch)
    world["snaps"].later(hours=30)
    world["snaps"].providers.fail = tsm.Failure()
    assert carry(world, LIVE, CANCEL)[0] == "Não encontrei nenhum evento com nome parecido nesse dia. Peça a sua agenda para ver os eventos."      # validate: allow english-only -- the Portuguese line or sentence under test


def test_a_cancelled_event_is_never_found(world, monkeypatch):
    build(world, monkeypatch, events=[("22", "13:00", "14:00", "corte de cabelo", "evgone", {"status": "cancelled"}), ("22", "18:00", "19:00", "Yoga", "evyoga")])
    assert carry(world, LIVE, CANCEL)[0] == "Não encontrei nenhum evento com nome parecido nesse dia. Peça a sua agenda para ver os eventos."      # validate: allow english-only -- the Portuguese line or sentence under test
    assert carry(world, "Cancela o yoga", CANCEL)[0] == "O card #1 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test, and the control: a live event is found


def test_a_rename_does_not_match_the_new_title_as_the_event_to_change(world, monkeypatch):
    build(world, monkeypatch, events=[("22", "10:00", "11:00", "Planejamento", "evplan")])
    text = op_text("event-change", {"title": "Planejamento trimestral"})
    reply, extras = carry(world, "Renomeia a reunião para Planejamento trimestral", text)      # validate: allow english-only -- the Portuguese line or sentence under test
    assert reply == "Não encontrei nenhum evento com nome parecido nos próximos 30 dias. Peça a sua agenda para ver os eventos." and "resend" not in extras and rows(world) == ([], [])      # validate: allow english-only -- the Portuguese line or sentence under test
    # control: when the old title is in the line, the same title span renames that event
    _, extras = carry(world, "Renomeia o planejamento para Planejamento trimestral", text)
    lines = card(world, extras)["body"].splitlines()
    assert "Named as agenda#1, from the snapshot read at 2026-10-21T17:00:00Z." in lines and "After: Title: Planejamento trimestral" in lines, lines


@pytest.mark.parametrize("line", ["Muda o yoga para as 10h do dia 23", "Muda o yoga para as 10h do\ndia 23", "Muda o yoga para as 10h do  dia 23", "Muda o yoga para as 10h do \t dia   23"])
def test_a_break_or_a_double_space_in_the_time_phrase_does_not_make_its_day_the_old_events_day(world, monkeypatch, line):
    build(world, monkeypatch, events=[("22", "18:00", "19:00", "Yoga", "evyoga22"), ("23", "18:00", "19:00", "Yoga", "evyoga23")])
    reply, extras = carry(world, line, op_text("event-change", {"time": "as 10h do dia 23"}, time_iso="2026-10-23T10:00", weekday="fri"))
    assert reply == ("Mais de um evento combina. Qual deles você quer mudar?\n1. Thu 22/10/2026 18:00-19:00 · Yoga\n2. Fri 23/10/2026 18:00-19:00 · Yoga\n"      # validate: allow english-only -- the Portuguese line or sentence under test
                     "Diga o número e o novo horário, por exemplo: remarca o evento 1 para sexta às 15h."), line      # validate: allow english-only -- the Portuguese line or sentence under test
    assert "resend" not in extras


def test_a_span_the_line_does_not_hold_is_a_question_and_no_day_is_read_from_the_unstripped_line(world, monkeypatch):
    build(world, monkeypatch)
    ctx = ops_core.context(world["path"])
    made = decision("Muda o yoga para as 10h do dia 23", op_text("event-change", {"time": "as 10h do dia 23"}, time_iso="2026-10-23T10:00", weekday="fri"))
    made["spans"] = {"time": "as 11h do dia 24"}      # a span the line does not hold (planted)
    got = event_lookup.open_event(world["path"], ctx, made, "Muda o yoga para as 10h do dia 23", OWNER, {}, st.load("ops_natural_writes"), ops_natural._clock())
    assert got == "Não consegui ler o dia que você quis dizer. Diga o nome do evento e o dia, por exemplo: amanhã ou 22/10."      # validate: allow english-only -- the Portuguese line or sentence under test


def test_a_word_of_the_day_or_a_yes_is_not_the_title_of_an_event(world, monkeypatch):
    build(world, monkeypatch, events=[("23", "09:00", "10:00", "Dia", "evdia"), ("23", "11:00", "12:00", "Sim", "evsim")])
    for line in ("cancela o dentista dia 23", "sim, cancela o dentista", "cancela o dentista, ok"):
        reply, extras = carry(world, line, CANCEL)
        assert reply.startswith("Não encontrei nenhum evento com nome parecido") and "resend" not in extras, line      # validate: allow english-only -- the Portuguese line or sentence under test


# --- the pure rule: which events a line names ------------------------------------------------------------------------------------------------------


def row(day, title, n=1):
    return {"source": "agenda", "n": n, "day": datetime.date.fromisoformat(day), "time": "09:00-10:00", "title": title}


TODAY = datetime.date(2026, 10, 21)


def titles(found):
    return [r["title"] for r in found]


def test_the_title_is_the_closest_name_of_the_line_folded_for_case_and_accents():
    rows_ = [row("2026-10-22", "Café com Ana"), row("2026-10-22", "Consulta"), row("2026-10-22", "A")]
    got = event_lookup.candidates(rows_, "cancela o CAFE COM ana", "none", None, TODAY)
    assert titles(got) == ["Café com Ana"] and got[0]["exact"] is True
    got = event_lookup.candidates(rows_, "cancela as consultas", "none", None, TODAY)
    assert titles(got) == ["Consulta"] and got[0]["exact"] is False, "a word one edit away is the word, and the match is not exact"
    assert titles(event_lookup.candidates(rows_, "cancela a consulta", "none", None, TODAY)) == ["Consulta"]
    assert titles(event_lookup.candidates(rows_, "cancela a reunião", "none", None, TODAY)) == [], "a title of one letter names nothing, and an unrelated word names nothing"  # validate: allow english-only -- the Portuguese line or sentence under test
    got = event_lookup.candidates(rows_, "cancela o café", "none", None, TODAY)
    assert titles(got) == ["Café com Ana"] and got[0]["exact"] is False, "a part of a title is a near name, not the exact one"
    assert titles(event_lookup.candidates(rows_, "cancela o cafe zzz yyy", "none", None, TODAY)) == [], "vacuity: unmatched words of the line weigh against it (2 of 5 is under the half)"


def test_a_title_inside_a_longer_title_that_also_fits_is_dropped():
    rows_ = [row("2026-10-22", "Aula", 1), row("2026-10-22", "Aula de Yoga", 2)]
    assert titles(event_lookup.candidates(rows_, "cancela a aula de yoga", "none", None, TODAY)) == ["Aula de Yoga"]
    assert titles(event_lookup.candidates(rows_, "cancela a aula", "none", None, TODAY)) == ["Aula"]


def test_the_window_is_today_to_thirty_days_ahead_and_a_named_day_may_lie_outside_it():
    rows_ = [row("2026-10-20", "Yoga", 1), row("2026-10-21", "Yoga", 2), row("2026-11-20", "Yoga", 3), row("2026-11-21", "Yoga", 4)]
    assert [r["n"] for r in event_lookup.candidates(rows_, "cancela o yoga", "none", None, TODAY)] == [2, 3]
    assert [r["n"] for r in event_lookup.candidates(rows_, "cancela o yoga", "day", datetime.date(2026, 10, 20), TODAY)] == [1]
    assert [r["n"] for r in event_lookup.candidates(rows_, "cancela o yoga", "weekday", 4, TODAY)] == [3]      # 20/11/2026 is a Friday; 21/10 is a Wednesday
    assert [r["n"] for r in event_lookup.candidates(rows_, "cancela o yoga", "none", None, TODAY)] != [1, 2, 3, 4], "vacuity: the window is not everything"


# --- a write that cannot be prepared ---------------------------------------------------------------------------------------------------------------

E_OPS = ["event-create", "event-change", "event-cancel", "mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash", "file-create", "file-replace",
         "file-save"]
LANGUAGE = {"pt-BR": "Por enquanto, peça isso em português ou em inglês.", "en": "For now, ask for that in Portuguese or in English."}      # validate: allow english-only -- the Portuguese line or sentence under test
CREATE = {"pt-BR": "Entendi que você quer criar um evento, mas não consegui montar o cartão. Diga o título, o dia e a hora.",      # validate: allow english-only -- the Portuguese line or sentence under test
          "en": "I understood that you want to create an event, but I could not prepare it. Tell me the title, the day and the time."}
GENERIC = {"pt-BR": "Entendi que você quer mudar algo nas suas contas, mas não consegui montar o cartão, então não fiz nada. Diga o que é, qual item e quando.",      # validate: allow english-only -- the Portuguese line or sentence under test
           "en": "I understood that you want to change something in your accounts, but I could not prepare it, so I did nothing. Tell me what it is, which item and when."}


def test_the_class_e_operations_are_these_thirteen():
    natural = st.load("natural")
    assert sorted(k for k, v in natural.CLASSES.items() if v == "E") == sorted(E_OPS), "an operation was added: give it a sentence here"


@pytest.mark.parametrize("language", ["pt-BR", "en"])
def test_a_pt_br_or_en_project_is_never_told_to_ask_in_another_language_for_any_write(world, monkeypatch, language):
    build(world, monkeypatch, language=language)
    ctx = ops_core.context(world["path"])
    for name in E_OPS:
        wanted = CREATE[language] if name == "event-create" else GENERIC[language]
        assert ops_interpret._cannot(ctx, name) == wanted, name
        assert ops_interpret._cannot(ctx, name) != LANGUAGE[language]


def test_a_language_with_no_write_forms_is_still_told_so_for_every_write(world, monkeypatch):
    build(world, monkeypatch, language="es")
    ctx = ops_core.context(world["path"])
    for name in E_OPS:
        assert ops_interpret._cannot(ctx, name) == "For now, ask for that in Portuguese or in English.", name


def test_an_event_with_no_time_in_a_pt_br_project_says_what_is_missing(world, monkeypatch):
    build(world, monkeypatch)
    reply, extras = carry(world, "preciso de um evento novo", op_text("event-create"))
    assert reply == CREATE["pt-BR"] and "resend" not in extras


def test_the_sentence_of_a_failed_write_is_not_the_language_sentence_vacuity():
    assert CREATE["pt-BR"] != LANGUAGE["pt-BR"] and GENERIC["en"] != LANGUAGE["en"]


# --- privacy: the whole turn --------------------------------------------------------------------------------------------------------------------


def test_the_whole_turn_stores_neither_the_line_nor_a_title_and_prints_nothing(world, monkeypatch, caplog, capfd):
    build(world, monkeypatch)
    queue = [CANCEL, CANCEL]

    def complete(route_id, system, user, **kw):
        return {"ok": True, "text": queue.pop(0), "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}

    monkeypatch.setattr(interpreter_route, "complete", complete)
    ops_interpret.forget_all()
    caplog.set_level(0)
    first = ops.say(world["path"], LIVE, channel="messaging", sender=OWNER)["reply"]
    second = ops.say(world["path"], "Cancela o corte de cabelo", channel="messaging", sender=OWNER)["reply"]
    assert first == "O card #1 espera a sua aprovação." and second.startswith("Mais de um evento combina."), (first, second)      # validate: allow english-only -- the Portuguese line or sentence under test
    ctx = ops_core.context(world["path"])
    stored = " ".join(m["text"] for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500))
    seen = stored + " ".join(r.getMessage() for r in caplog.records) + " ".join(capfd.readouterr())
    for piece in ("corte de cabelo", "Remova", "Cancela o", "amanha"):
        assert piece.lower() not in seen.lower(), piece
    assert "(pedido para as suas contas)" in stored or "(uma mensagem)" in stored      # validate: allow english-only -- the Portuguese line or sentence under test


def test_the_words_the_time_engine_reads_and_a_yes_at_the_edges_are_not_matched_against_titles():
    rows_ = [row("2026-10-23", "Dia", 1), row("2026-10-23", "Sim", 2), row("2026-10-23", "Reunião 10h", 3), row("2026-10-23", "Jantar da Ana", 4), row("2026-10-23", "Dentista", 5)]      # validate: allow english-only -- the Portuguese line or sentence under test
    assert titles(event_lookup.candidates(rows_, "cancela o dentista dia 23", "none", None, TODAY)) == ["Dentista"]
    assert titles(event_lookup.candidates(rows_, "sim, cancela o dentista", "none", None, TODAY)) == ["Dentista"]
    assert titles(event_lookup.candidates(rows_, "cancela o dentista, ok", "none", None, TODAY)) == ["Dentista"]
    assert titles(event_lookup.candidates(rows_, "cancela a reunião 10h", "none", None, TODAY)) == ["Reunião 10h"], "a title that holds a time is read against the whole line"      # validate: allow english-only -- the Portuguese line or sentence under test
    assert titles(event_lookup.candidates(rows_, "cancela o jantar da ana", "none", None, TODAY)) == ["Jantar da Ana"], "a yes word inside a title stays"
    assert titles(event_lookup.candidates(rows_, "cancela o dia", "none", None, TODAY)) == ["Dia"], "control: the word is a title when nothing reads it as a day"
