"""A negated noun does not choose the kind of a list (package ITEMS-NEGATION; runtime/natural_writes.py `items_kind`, `items_noun`, `_nouns_named`, `requests.writes.negators`).

The live case (2026-10-26): "mostra minha agenda" -> "Posso?" -> "I meant my unread emails, not the calendar". Both readings of the kind of a list took any calendar noun for the calendar, so the
corrected plan equalled the old one and was dropped (`PLAN_DROPPED`): safe, nothing ran, but the person got no new "Posso?". Now a calendar or mail noun that a negator reaches ("not the calendar",
"nao a agenda": a negator, then only single spaces and articles, no mark between) is the one the person does not want. A line with no negator reads as before. Reads only, always behind "Posso?".
Every line and expectation below is a literal of this file; the oracle is the table, not the code. Vacuity: a reach that is never or always negated fails the table. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_items_negation.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from plan_confirm_kit import OWNER, ok_of, op as model_op, ops, ops_say, phrases, say, world, rig  # noqa: F401  (the real-operations world, the model stood in)

natural = st.load("natural")
natural_writes = st.load("natural_writes")

# (line, items_noun, items_kind): the person's own lines, in English and in Portuguese (the lists of the tables merge, so each line is read by both)
TABLE = (
    ("I meant my unread emails, not the calendar", "mail", "mail"),
    ("quero os emails, não a agenda", "mail", "mail"),      # validate: allow english-only -- the Portuguese line under test
    ("a agenda, não os emails", "calendar", "calendar"),      # validate: allow english-only -- the Portuguese line under test
    ("não, a agenda", "calendar", "calendar"),      # validate: allow english-only -- a comma breaks the reach of the negator
    ("eventos no calendário", "calendar", "calendar"),      # validate: allow english-only -- the Portuguese "no" is "in the", not a negator
    ("emails sem a agenda", "mail", "mail"),
    ("my calendar and my emails", "calendar", "calendar"),      # both named and none negated: calendar, as before
    ("not the calendar", "mail", "mail"),      # OPEN-1: only one kind negated, the other kind
    ("not the emails", "calendar", "calendar"),
    ("the emails", "mail", "mail"),
    ("list my emails instead of the calendar", "mail", "mail"),
    ("emails em vez da agenda", "mail", "mail"),
    ("mostra os emails ao invés da agenda", "mail", "mail"),      # validate: allow english-only -- the Portuguese line under test
    ("the calendar, never the emails", "calendar", "calendar"),
    ("pelo menos a agenda", "calendar", "calendar"),      # "menos" is no negator
    ("not the unread calendar", "calendar", "calendar"),      # a word that is no article between the negator and the noun: the noun stays plain
    ("não os emails e não a agenda", None, "mail"),      # validate: allow english-only -- both negated: no choice for items_noun, the default for items_kind
    ("no, the one for tomorrow", None, "mail"),
    ("show me everything", None, "mail"),
    ("", None, "mail"),
)


@pytest.mark.parametrize("line,noun,kind", TABLE)
def test_the_noun_and_the_kind_of_a_line_follow_the_negation_table(line, noun, kind):
    assert natural_writes.items_noun(line) == noun
    assert natural_writes.items_kind(line) == kind


def test_a_line_that_is_not_a_string_names_nothing():
    assert natural_writes.items_noun(None) is None and natural_writes.items_kind(None) == "mail"


def test_the_two_exclusions_are_pinned_no_is_no_negator_in_any_table_and_menos_is_none_in_portuguese():
    tables = natural_writes._tables(None)
    every = [p for t in tables for p in natural_writes.writes_of(t).get("negators", [])]
    assert every, "the tables ship negators"
    assert "no" not in every and "menos" not in every
    assert {"not", "never", "without", "except", "instead of", "rather than"} <= set(every)
    assert {"nao", "nem", "sem", "exceto", "em vez de", "em vez do", "em vez da", "ao inves de", "ao inves do", "ao inves da"} <= set(every)
    assert [natural_writes.items_noun(line) for line in ("eventos no calendário", "pelo menos a agenda")] == ["calendar", "calendar"]      # validate: allow english-only -- the Portuguese lines under test


def test_named_splits_the_hits_of_a_phrase_by_the_negator_that_reaches_them():
    tables = natural_writes._tables(None)
    line = natural_writes.Line("emails, not the calendar, and my calendar, sem agenda, nao, agenda")
    plain, negated = natural_writes._nouns_named(line, ["calendar", "agenda"], tables)
    folded = line.norm
    assert [folded[s:e] for s, e in negated] == ["calendar", "agenda"]
    assert [folded[s:e] for s, e in plain] == ["calendar", "agenda"]
    assert negated[0][0] < plain[0][0] < negated[1][0] < plain[1][0], "line order"


# --- the shape of the table ------------------------------------------------------------------------------------------------------------------------


def table_with(negators):
    return {"tag": "xx", "requests": {"writes": {"negators": negators}}}


def test_check_writes_takes_negators_as_a_list_of_phrases_and_refuses_anything_else():
    natural_writes.check_writes(table_with(["not", "instead of"]))
    natural_writes.check_writes(table_with([]))
    for bad in ("not", [3], ["Not"], ["not  the"], ["n.t"], {"not": 1}, ["(not)"]):
        with pytest.raises(ValueError) as e:
            natural_writes.check_writes(table_with(bad))
        assert "negators is a list of phrases" in str(e.value), bad


def test_negators_is_a_top_level_key_of_the_closed_list_and_both_shipped_tables_fill_it():
    assert "negators" in natural_writes.TOP_KEYS
    for name in ("natural_lang_en", "natural_lang_pt_br"):
        table = st.load(name).TABLE
        natural_writes.check_writes(table)
        assert natural_writes.writes_of(table).get("negators"), name


def test_a_key_the_closed_list_does_not_hold_is_still_refused():
    with pytest.raises(ValueError) as e:
        natural_writes.check_writes({"tag": "xx", "requests": {"writes": {"deniers": ["not"]}}})
    assert "has no key 'deniers'" in str(e.value)


# --- vacuity ---------------------------------------------------------------------------------------------------------------------------------------


def mismatches():
    return [line for line, noun, kind in TABLE if (natural_writes.items_noun(line), natural_writes.items_kind(line)) != (noun, kind)]


def test_vacuity_a_reach_that_never_negates_or_always_negates_fails_the_table(monkeypatch):
    assert mismatches() == []
    monkeypatch.setattr(natural_writes, "_negated_before", lambda norm, at, negators, articles: False)
    never = mismatches()
    assert "I meant my unread emails, not the calendar" in never and "not the calendar" in never
    monkeypatch.setattr(natural_writes, "_negated_before", lambda norm, at, negators, articles: True)
    always = mismatches()
    assert "my calendar and my emails" in always and "the emails" in always


def test_vacuity_a_table_with_no_negators_reads_every_line_as_before(monkeypatch):
    monkeypatch.setattr(natural_writes, "listed", lambda tables, section, key, _real=natural_writes.listed: [] if key == "negators" else _real(tables, section, key))
    assert natural_writes.items_noun("I meant my unread emails, not the calendar") == "calendar"
    assert natural_writes.items_kind("list my emails, not the calendar") == "calendar"


# --- the flow: the corrected line asks a new question ---------------------------------------------------------------------------------------------


@pytest.fixture
def typed(rig, monkeypatch):
    """The command a plan hands over once it is confirmed, recorded instead of run."""
    rig.said_commands = []
    monkeypatch.setattr(ops_say, "_say_command", lambda project, ctx, line, channel, line_id, sender=None: rig.said_commands.append(line) or ("COMMAND-REPLY", None, None, False, None))
    return rig


def corrected(rig, line, model_text):
    """The agenda of today is asked, the person corrects it with `line`, the model (stood in) answers `model_text`. Returns (the first reply, the reply to the correction, the reads)."""
    reads = []
    from plan_confirm_kit import ops_natural
    rig.monkeypatch.setattr(ops_natural, "_read", lambda project, ctx, name, row, args, channel, sender: reads.append({"name": name, "args": args}) or "READ-REPLY")
    rig.world["clock"].set("2026-10-25 00:50")
    rig.says["text"] = model_op("items")
    old = say(rig, OWNER, "mostra minha agenda de hoje")      # validate: allow english-only -- the Portuguese line under test
    assert "plan_confirm" in old and reads == []
    rig.now[0] += 30
    rig.says["text"] = model_text
    return old, say(rig, OWNER, line), reads


@pytest.mark.parametrize("line,model_text", (
    ("quis dizer meus emails não lidos, não a agenda", model_op("items")),      # validate: allow english-only -- the Portuguese line under test
    ("I meant my unread emails, not the calendar", model_op("items")),
    ("não, quis dizer meus emails não lidos, não a agenda", model_op("mail-mark", {"state": "não lidos"})),      # validate: allow english-only -- the Portuguese line under test
    ("no, I meant my unread emails, not the calendar", model_op("mail-mark", {"state": "unread"})),
), ids=("pt-items", "en-items", "pt-card-kept-a-read", "en-card-kept-a-read"))
def test_a_corrected_line_that_negates_the_calendar_asks_a_new_question_for_the_mail_list_and_nothing_runs(typed, line, model_text):
    old, out, reads = corrected(typed, line, model_text)
    assert out["reply"] != phrases.text("PLAN_DROPPED", typed.cfg) and "plan_confirm" in out, "a NEW question, not a dropped plan"
    assert phrases.text("UNDERSTOOD_ITEMS_MAIL", typed.cfg) in out["reply"] and phrases.text("UNDERSTOOD_ITEMS_CALENDAR", typed.cfg) not in out["reply"]
    assert out["plan_confirm"]["item"] != old["plan_confirm"]["item"] and out["plan_confirm"]["sha256"] != old["plan_confirm"]["sha256"]
    assert reads == [] and typed.said_commands == [], "nothing was read or run before the OK"
    done = say(typed, OWNER, "sim", plan_ok=ok_of(out))
    assert done["reply"] == "READ-REPLY" and [r["args"]["kind"] for r in reads] == ["mail"] and typed.said_commands == []


def test_vacuity_without_the_negation_the_corrected_line_is_the_old_plan_and_is_dropped(typed, monkeypatch):
    monkeypatch.setattr(natural_writes, "_negated_before", lambda norm, at, negators, articles: False)
    old, out, reads = corrected(typed, "no, I meant my unread emails, not the calendar", model_op("mail-mark"))      # CB-9: a card with no slot, so that the revised read has none either, as at catalog version 1; with the slot `state` (a slot of `items` since version 2) the revised read would be a plan of its own
    assert out["reply"] == phrases.text("PLAN_DROPPED", typed.cfg) and "plan_confirm" not in out and reads == []
    typed.now[0] += 30
    typed.says["text"] = model_op("items")
    again = say(typed, OWNER, "I meant my unread emails, not the calendar")
    assert phrases.text("UNDERSTOOD_ITEMS_CALENDAR", typed.cfg) in again["reply"], "a line with no no is a new request: still the calendar without the negation"
