"""The interpreter on a messaging line (slice S1, runtime/ops_interpret.py): what a decision of the model calls, line by line, in the six languages.

A stand-in model answers each line with a text the test wrote by hand; the spies stand in for the calls that carry a decision out (`ops_natural.run`,
`ops_natural_writes.open_line`, `ops_say._say_route`). Every expectation is a literal of this file: the line, the model's text, the call and its arguments, the sentence.
The user turn the model is shown is compared with a five-line string written here, and no reply holds a byte of what the model wrote. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_interpret_dispatch.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import json

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_ops_natural import KEY, PROFILES, SENDERS, world  # noqa: F401  (the real-operations world fixture)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
ops_natural_writes = st.load("ops_natural_writes")
ops_say = st.load("ops_say")
interpreter_route = st.load("interpreter_route")

REAL_OPEN_LINE = ops_natural_writes.open_line
ZONE = "America/Sao_Paulo"
TODAY = "today: 2026-10-18 Sun\ntime: 14:00\nzone: America/Sao_Paulo\nframe: null\nline: "      # the clock of the stand-in world: Sunday 2026-10-18 14:00 at -03:00
IX_PROFILES = dict(PROFILES, owner=PROFILES["owner"] + ["interpret", "mail-organize"], plain=["read", "talk", "interpret"], bare=["read", "talk"],
                   mailer=["read", "talk", "ask", "ask-mail", "reminders", "interpret"])
IX_SENDERS = {"telegram": [*SENDERS["telegram"], {"id": "55119000000007", "policy": "bare"}]}
BARE = "telegram:55119000000007"
PLAIN = KEY["plain"]
ROUTED = ("ROUTED", None, None, True, None)


def op(name, slots=None, **more):
    return json.dumps({"v": 1, "kind": "op", "op": name, "slots": slots or {}, **more}, ensure_ascii=False)


def prepare(world, monkeypatch, calls, answer, spies=True):
    """The world with the sender `owner` allowed to ask, the zone named, the model stood in (`answer["text"]` is what it returns for every line) and, unless `spies` is false,
    the three spies."""
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()

    def complete(route_id, system, user, **kw):
        calls.append({"route": route_id, "system": system, "user": user, "kw": kw})
        return {"ok": True, "text": answer["text"], "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}

    def run(project, ctx, name, args, said, channel, sender, extras, when=None, routed=False):
        calls.append({"run": name, "args": args, "said": said, "channel": channel, "sender": sender, "when": when, "routed": routed})
        return "RUN-REPLY"

    def open_line(project, ctx, said, channel, sender, extras, *, seed=None, hint=None):
        if seed is None and hint is None:      # the write forms of the pt/en tables, tried before the interpreter: the real call
            return REAL_OPEN_LINE(project, ctx, said, channel, sender, extras)
        calls.append({"open_line": True, "said": said, "channel": channel, "sender": sender, "seed": seed, "hint": hint})
        return answer.get("card", "CARD-REPLY")

    monkeypatch.setattr(interpreter_route, "complete", complete)
    if not spies:
        return
    monkeypatch.setattr(ops_natural, "run", run)
    monkeypatch.setattr(ops_natural_writes, "open_line", open_line)
    monkeypatch.setattr(ops_say, "_say_route", lambda *a, **k: calls.append({"routed": a[2]}) or ROUTED)


def phone(world, line, who="owner"):
    return ops.say(world["path"], line, channel="messaging", sender=KEY.get(who, who))


# (language, line, the model's text, the sentence, the call that follows the model's: {"run" | "open_line" | "routed": ...} or None)
EVENT_SEED = {"op": "event-create", "reading": {"date": "2026-10-23", "time": "20:00"}, "text": "cena con Dana"}
ONCE = "I was not sure what you meant, so I did nothing. Can you say it another way?"
TABLE = [
    ("pt-BR", "Me mostra o ultimo email do Outlook", op("items"), "RUN-REPLY", {"run": "items", "args": {}, "when": None, "routed": True}),
    ("en", "what is the budget for the launch plan about", op("ask"), "RUN-REPLY", {"run": "ask", "args": {}, "when": None, "routed": True}),
    ("es", "dime las tareas pendientes de la semana", op("pending"), "RUN-REPLY", {"run": "pending", "args": {}, "when": None, "routed": True}),
    ("fr", "montre-moi la tache 12", op("task", {"id": "12"}), "RUN-REPLY", {"run": "task", "args": {"task_id": 12}, "when": None, "routed": True}),
    ("de", "zeig mir die Aufgabe 7 bitte", op("task", {"id": "7"}), "RUN-REPLY", {"run": "task", "args": {"task_id": 7}, "when": None, "routed": True}),
    ("it", "mostrami la richiesta numero 3", op("pending", {"id": "3"}), "RUN-REPLY", {"run": "pending", "args": {"pending_id": 3}, "when": None, "routed": True}),
    ("es", "recuerdame llamar a Dana el lunes a las 15:00", op("remind", {"text": "llamar a Dana", "when": "el lunes a las 15:00"}, time_iso="2026-10-19T15:00", weekday="mon"),
     "RUN-REPLY", {"run": "remind", "args": {"text": "llamar a Dana"}, "when": "2026-10-19 15:00", "routed": True}),
    ("fr", "rappelle-moi d'appeler Dana vendredi a 15h", op("remind", {"text": "appeler Dana", "when": "vendredi a 15h"}, time_iso="2026-10-23T15:00", weekday="fri"),
     "RUN-REPLY", {"run": "remind", "args": {"text": "appeler Dana"}, "when": "2026-10-23 15:00", "routed": True}),
    ("de", "erinnere mich am Freitag um 15 Uhr an Dana", op("remind", {"text": "an Dana", "when": "am Freitag um 15 Uhr"}, time_iso="2026-10-23T15:00", weekday="fri"),
     "RUN-REPLY", {"run": "remind", "args": {"text": "an Dana"}, "when": "2026-10-23 15:00", "routed": True}),
    ("it", "ricordami di chiamare Dana venerdi alle 15:00", op("remind", {"text": "chiamare Dana", "when": "venerdi alle 15:00"}, time_iso="2026-10-23T15:00", weekday="fri"),
     "RUN-REPLY", {"run": "remind", "args": {"text": "chiamare Dana"}, "when": "2026-10-23 15:00", "routed": True}),
    ("es", "pon cena con Dana el viernes a las 20:00", op("event-create", {"title": "cena con Dana", "time": "el viernes a las 20:00"}, time_iso="2026-10-23T20:00", weekday="fri"),
     "CARD-REPLY", {"open_line": True, "seed": EVENT_SEED, "hint": None}),
    ("es", "archiva los mensajes 3 y 7", op("mail-archive", {"messages": "3,7"}), "CARD-REPLY", {"open_line": True, "seed": None, "hint": "mail-archive"}),
    ("fr", "supprime l'evenement numero 4", op("event-cancel", {"event": "4"}), "CARD-REPLY", {"open_line": True, "seed": None, "hint": "event-cancel"}),
    ("es", "cancela la solicitud 9", op("cancel", {"id": "9"}), "RUN-REPLY", {"run": "cancel", "args": {"request_id": 9}, "when": None, "routed": True}),
    ("de", "versuch Aufgabe 5 noch einmal", op("retry", {"id": "5"}), "RUN-REPLY", {"run": "retry", "args": {"task_id": 5}, "when": None, "routed": True}),
    ("en", "plan a three-day workshop for the new hires", '{"v":1,"kind":"route"}', "ROUTED", {"routed": "plan a three-day workshop for the new hires"}),
    ("pt-BR", "obrigado, era so isso", '{"v":1,"kind":"none"}', "I did not see a request in that message.", None),      # validate: allow english-only -- the Portuguese line or sentence under test
    ("es", "aprueba el plan", op("approve"), "A decision is made on its card: use the buttons of the card.", None),
    ("fr", "lance un tour du dispatcher", op("dispatch"), "That is not done from a message. Do it on the platform's page.", None),
    ("it", "metti la cosa nel calendario", '{"v":1,"kind":"clarify","ops":["event-create","remind"]}', ONCE, None),
    ("de", "schreib an Ana wegen der Rechnung", '{"v":1,"kind":"clarify","slot":"to"}', ONCE, None),
    ("es", "recuerdame llamar a Dana el lunes a las 15:00", op("remind", {"text": "llamar a Dana", "when": "el lunes a las 15:00"}, time_iso="2026-10-12T15:00", weekday="mon"),
     "That time has already passed. Say a time that is still ahead.", None),
    ("fr", "rappelle-moi d'appeler Dana vendredi a 15h", op("remind", {"text": "appeler Dana", "when": "vendredi a 15h"}, time_iso="2028-10-20T15:00", weekday="fri"),
     "That is more than a year away. Say a nearer day.", None),
    ("it", "ricordami di chiamare Dana venerdi alle 15:00", op("remind", {"text": "chiamare Dana", "when": "venerdi alle 15:00"}, time_iso="2026-10-23T15:00", weekday="mon"),
     "I am not sure of the day and the time. Say them again, with the day and the hour.", None),
    ("en", "tell me something about the unicorns", "Sure! ZEBRA-MODEL-TEXT I will do it", ONCE, None),
    ("es", "dime las tareas pendientes de la semana", op("pending", {"id": "99"}), ONCE, None),
    ("pt-BR", "Me mostra o ultimo email do Outlook", "```json\n" + op("items") + "\n```", "RUN-REPLY", {"run": "items", "args": {}, "when": None, "routed": True}),
]


def expect(row, calls, reply):
    """The mismatches of one row, as sentences (empty when it holds)."""
    lang, line, text, sentence, after = row
    problems = []
    if reply["reply"] != sentence:
        problems.append(f"{line!r}: reply {reply['reply']!r}")
    model = [c for c in calls if "user" in c]
    if len(model) != 1 or model[0]["user"] != TODAY + line:
        problems.append(f"{line!r}: the user turn is not the five lines")
    rest = [c for c in calls if "user" not in c]
    fixed = {"said": line, "channel": "messaging", "sender": KEY["owner"]}
    wanted = None if after is None else dict(after, **(fixed if "run" in after or "open_line" in after else {}))
    if wanted is None and rest or wanted is not None and (len(rest) != 1 or any(rest[0].get(k) != v for k, v in wanted.items())):
        problems.append(f"{line!r}: the call after the model is {rest!r}")
    for piece in (text, text.strip("`\n"), '"kind"', '"slots"', "time_iso", "ZEBRA"):
        if piece in reply["reply"]:
            problems.append(f"{line!r}: the reply holds a piece of the model's text")
    return problems


def run_table(world, monkeypatch, table, patch=None):
    problems = []
    for row in table:
        calls = []
        prepare(world, monkeypatch, calls, {"text": row[2]})
        if patch:
            patch(monkeypatch)
        problems += expect(row, calls, phone(world, row[1]))
    return problems


def swap_reads_and_writes(monkeypatch):
    """A planted fault: the operation a decision names is swapped between a read and a write before it is carried out."""
    real = ops_interpret._carry_out
    swap = {"items": "mail-archive", "mail-archive": "items"}

    def carry(project, ctx, decision, said, sender, extras):
        return real(project, ctx, dict(decision, op=swap.get(decision["op"], decision["op"])), said, sender, extras)

    monkeypatch.setattr(ops_interpret, "_carry_out", carry)


def test_the_table_is_at_least_twenty_rows_in_six_languages():
    assert len(TABLE) >= 20 and {row[0] for row in TABLE} == {"pt-BR", "en", "es", "fr", "de", "it"}


def test_every_decision_calls_what_the_table_says_and_the_model_is_shown_five_lines(world, monkeypatch):
    assert run_table(world, monkeypatch, TABLE) == []


def test_vacuity_a_dispatch_that_swaps_a_read_and_a_write_fails_the_table(world, monkeypatch):
    found = run_table(world, monkeypatch, TABLE, patch=swap_reads_and_writes)
    assert any("the call after the model" in p for p in found), "the table must notice a swapped dispatch"


def test_vacuity_a_reply_that_shows_the_model_text_is_noticed():
    shows = ("pt-BR", "obrigado, era so isso", '{"v":1,"kind":"none"}', '{"v":1,"kind":"none"}', None)      # validate: allow english-only -- the Portuguese line or sentence under test
    assert any("model's text" in p for p in expect(shows, [{"user": TODAY + shows[1]}], {"reply": '{"v":1,"kind":"none"}'}))


def test_the_call_is_the_daily_route_with_the_protocols_settings_and_the_hash_it_was_decided_on(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": '{"v":1,"kind":"none"}'})
    phone(world, "gracias, nada mas")
    sent = [c for c in calls if "route" in c]
    assert len(sent) == 1 and sent[0]["route"] == "or-deepseek-v4.1-flash"
    assert sent[0]["kw"] == {"accepted": ["1365ea7c385a28f38103f9b2d3b959faee6012691ed6ef50478a560d1014c9fd"], "deadline_ms": 6000, "temperature": 0, "max_tokens": 300,
                             "reasoning": "off"}


def test_a_write_no_table_reads_says_to_ask_in_portuguese_or_english_and_a_pt_br_project_is_answered_in_it(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": op("mail-archive", {"messages": "3,7"}), "card": None})
    assert phone(world, "archiva los mensajes 3 y 7")["reply"] == "For now, ask for that in Portuguese or in English."
    write_config(world["path"], language="pt-BR")
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    assert phone(world, "archiva los mensajes 3 y 7")["reply"] == "Por enquanto, peça isso em português ou em inglês."      # validate: allow english-only -- the Portuguese line or sentence under test
    prepare(world, monkeypatch, [], {"text": '{"v":1,"kind":"none"}'})
    assert phone(world, "gracias, nada mas")["reply"] == "Não vi um pedido nessa mensagem."      # validate: allow english-only -- the Portuguese line or sentence under test


def test_an_event_with_no_time_goes_to_its_family_with_the_name_only(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": op("event-create", {"title": "cena con Dana"})})
    assert phone(world, "pon cena con Dana")["reply"] == "CARD-REPLY"
    opened = [c for c in calls if "open_line" in c]
    assert len(opened) == 1 and opened[0]["seed"] is None and opened[0]["hint"] == "event-create"


def test_a_refusal_of_the_policy_is_the_sentence_the_typed_command_gets(world, monkeypatch):
    calls = []
    prepare(world, monkeypatch, calls, {"text": op("retry", {"id": "5"})})
    got = phone(world, "versuch Aufgabe 5 noch einmal", who="plain")["reply"]
    assert got == PLAIN_REFUSAL and "error" not in got and "/" not in got
    assert [c for c in calls if "run" in c] == []


def test_the_live_lines_of_the_maintainer_reach_a_read_and_the_yes_question(world, monkeypatch):
    """The lines that went to the planning agent in real use (2026-10-20), with the real read and the real reminder question behind the stand-in model."""
    calls = []
    prepare(world, monkeypatch, calls, {"text": op("items")}, spies=False)
    out = phone(world, "liste o ultimo email do meu Outlook", who="mailer")
    assert out["reply"] == "No numbered items yet: a mail or calendar source needs a snapshot first." and len(calls) == 1 and calls[0]["user"].endswith("line: liste o ultimo email do meu Outlook")
    prepare(world, monkeypatch, calls, {"text": op("remind", {"text": "llamar a Dana", "when": "manana a las 10:00"}, time_iso="2026-10-19T10:00", weekday="mon")}, spies=False)
    asked = phone(world, "recuerdame llamar a Dana manana a las 10:00")
    assert asked["reply"] == "I understood: tomorrow, Mon 19/10, at 10:00: llamar a Dana. Confirm? (yes / another time)"
    made = phone(world, "yes")
    assert made["reply"] == "Reminder #1: tomorrow, Mon 19/10, at 10:00 (BRT): llamar a Dana. To undo: /forget 1."
