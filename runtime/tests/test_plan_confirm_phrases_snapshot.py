"""The sentences of D5 in full, one snapshot per language (package BL2a, runtime/plan_confirm.py `understood`, the phrase keys `PLAN_*` and `UNDERSTOOD_*`).

The other tests of the package check the wording by phrase key and values, so a rewording of the table does not break them; this file holds the one literal snapshot of three full
sentences for each of en, pt-BR and es (es has no table: the English sentence with the values quoted). The clock is a stand-in (Sunday 2026-10-18 14:00 UTC); the research cap is read from
the configuration (`research.max_cost_usd` 0.6). A change of a sentence changes this file on purpose and is reviewed. Offline; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_confirm_phrases_snapshot.py
"""
from __future__ import annotations

import datetime

import pytest

import phrase_kit as pk
import standin_tree as st

ops_natural = st.load("ops_natural")
phrases = st.load("phrases")
plan_confirm = st.load("plan_confirm")

SNAPSHOT = {
    "en": ["I understood: show the events of your calendar for Mon 19/10/2026. Shall I go ahead?",
           "I understood: cancel request #3. Shall I go ahead?",
           "I understood: search the web for “weather in Lisbon” (a paid model run, up to US$ 0.60). Shall I go ahead?"],
    "pt-BR": ["Entendi: mostrar os eventos da sua agenda de seg 19/10/2026. Posso?",      # validate: allow english-only -- the Portuguese sentence under test
              "Entendi: cancelar o pedido #3. Posso?",      # validate: allow english-only -- the Portuguese sentence under test
              "Entendi: pesquisar na web: “previsão do tempo em Lisboa” (uma execução paga de modelo, até US$ 0,60). Posso?"],      # validate: allow english-only -- the Portuguese sentence under test
    "es": ["I understood: show the events of your calendar for Mon 19/10/2026. Shall I go ahead?",
           "I understood: cancel request #3. Shall I go ahead?",
           "I understood: search the web for “el tiempo en Lisboa” (a paid model run, up to US$ 0.60). Shall I go ahead?"],
}
CALLS = {"en": [("items", {}, "show the events for tomorrow"), ("cancel", {"request_id": 3}, "cancel request 3"), ("research", {"question": "weather in Lisbon"}, "weather in Lisbon")],
         "pt-BR": [("items", {}, "mostra os eventos de amanha"), ("cancel", {"request_id": 3}, "cancela o pedido 3"), ("research", {"question": "previsão do tempo em Lisboa"}, "x")],      # validate: allow english-only -- the Portuguese lines under test
         "es": [("items", {}, "show the events for tomorrow"), ("cancel", {"request_id": 3}, "cancela el pedido 3"), ("research", {"question": "el tiempo en Lisboa"}, "x")]}


@pytest.mark.parametrize("tag", ["en", "pt-BR", "es"])
def test_the_three_full_sentences_of_each_language_are_these(tag, monkeypatch):
    monkeypatch.setattr(ops_natural, "_clock", lambda: datetime.datetime(2026, 10, 18, 14, 0, tzinfo=datetime.timezone.utc))
    cfg = {"language": tag, "research": {"max_cost_usd": 0.6}, "channels": {}}
    ctx = {"cfg": cfg}
    got = [phrases.text("PLAN_HEAD", cfg, what=plan_confirm.understood(ctx, name, args, said)) + " " + phrases.text("PLAN_ASK", cfg) for name, args, said in CALLS[tag]]
    assert got == SNAPSHOT[tag]


def test_a_value_is_one_line_of_at_most_80_characters_and_a_number_is_a_number():
    cfg = {"language": "en", "research": {"max_cost_usd": 0.6}, "channels": {}}
    long = "weather in Lisbon\ntomorrow " + "x" * 200
    said = plan_confirm.understood({"cfg": cfg}, "research", {"question": long}, "x")
    shown = said.split("“")[1].split("”")[0]
    assert "\n" not in shown and len(shown) <= plan_confirm.VALUE_MAX and shown.startswith("weather in Lisbon tomorrow")
    pk.assert_said(plan_confirm.understood({"cfg": cfg}, "cancel", {"request_id": True}, "x"), "UNDERSTOOD_CANCEL", cfg, id="?")  # a number that is no number is never written as one
