"""Nothing of a line the model service read is kept (slice S1, limit L63, decision D2): not in the store, not in a log, not in the output of the process.

The token `Zebulon42` is in a Spanish reminder line, in a French event line and in a line whose call fails. After each, the raw bytes of every file of the world (the store's
database, its journal, the project) are searched for it, every log record at the lowest level is read, and standard output and error are read. A line the interpreter sent
on to the planning agent is stored as it always was (the control that shows the search can find the token). The oracle is the test's own token and its own search, not a
function of the code under test. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_interpret_privacy.py
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_ops_interpret_dispatch import IX_PROFILES, IX_SENDERS, KEY, ZONE, op
from test_ops_natural import world  # noqa: F401  (the real-operations world fixture)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
interpreter_route = st.load("interpreter_route")

TOKEN = "Zebulon42"
REMIND = "recuerdame llamar a Zebulon42 manana a las 10:00"
EVENT = "dame una cita con Zebulon42 el viernes a las 20:00"
REMIND_JSON = op("remind", {"text": "llamar a Zebulon42", "when": "manana a las 10:00"}, time_iso="2026-10-19T10:00", weekday="mon")
EVENT_JSON = op("event-create", {"title": "cita con Zebulon42", "time": "el viernes a las 20:00"}, time_iso="2026-10-23T20:00", weekday="fri")
ROUTE_JSON = '{"v":1,"kind":"route"}'


def stand_in(world, monkeypatch, answers):
    """The real operations, with the model stood in: the texts in `answers` are returned in turn."""
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()
    queue = list(answers)

    def complete(route_id, system, user, **kw):
        return {"ok": True, "text": queue.pop(0), "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}

    monkeypatch.setattr(interpreter_route, "complete", complete)


def where_found(tmp_path, caplog, capfd) -> list:
    """The places that hold the token: a file of the world (searched as raw bytes), a log record, the output of the process."""
    found = [str(p.relative_to(tmp_path)) for p in sorted(Path(tmp_path).rglob("*")) if p.is_file() and TOKEN.encode() in p.read_bytes()]
    found += ["log" for record in caplog.records if TOKEN in record.getMessage() or TOKEN in str(record.args) or TOKEN in str(record.exc_text)]
    out, err = capfd.readouterr()
    return found + (["stdout"] if TOKEN in out else []) + (["stderr"] if TOKEN in err else [])


def phone(world, line):
    return ops.say(world["path"], line, channel="messaging", sender=KEY["owner"])


def test_a_spanish_reminder_a_french_event_and_a_failed_call_leave_the_token_nowhere(world, monkeypatch, tmp_path, caplog, capfd):
    caplog.set_level(1)
    stand_in(world, monkeypatch, [REMIND_JSON, EVENT_JSON])
    asked = phone(world, REMIND)["reply"]
    assert "llamar a Zebulon42" in asked and asked.endswith("Confirm? (yes / another time)"), "the reminder reached the question that asks for a yes"
    opened = phone(world, EVENT)["reply"]
    assert opened == "None of your accounts is set up for this: the key accounts of runtime.json lists them, with what each may write to.", "the event reached its family, which has no account here"
    monkeypatch.setattr(interpreter_route, "complete", lambda route_id, system, user, **kw: {"ok": False, "code": "E_NETWORK"})
    write_config(world["path"], language="es")
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    assert phone(world, "llama a Zebulon42 manana")["reply"] == "I could not understand that right now. Try again in a few minutes."
    assert where_found(tmp_path, caplog, capfd) == []
    ctx = ops_core.context(world["path"])
    shown = [m["text"] for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=50)]
    assert shown[:2] == ["(a message)", "(reminder)"] and shown.count("(a message)") == 3


def test_a_line_the_interpreter_sends_to_the_planning_agent_is_stored_as_it_always_was(world, monkeypatch, tmp_path, caplog, capfd):
    caplog.set_level(1)
    stand_in(world, monkeypatch, [ROUTE_JSON])
    monkeypatch.setattr(st.load("ops_say"), "_say_route", lambda *a, **k: ("ROUTED", None, None, True, None))
    assert phone(world, "arma un plan para el taller de Zebulon42")["reply"] == "ROUTED"
    ctx = ops_core.context(world["path"])
    assert [m["text"] for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=50)][0] == "arma un plan para el taller de Zebulon42"
    assert where_found(tmp_path, caplog, capfd) != [], "the search finds the token where it is kept (the control)"


def test_vacuity_a_planted_copy_of_the_raw_line_into_the_store_is_caught(world, monkeypatch, tmp_path, caplog, capfd):
    caplog.set_level(1)
    stand_in(world, monkeypatch, [REMIND_JSON])
    real = ops_interpret.turn

    def leaking(project, ctx, said, sender, extras):
        ctx["store"].message_add(ctx["conn"], conversation=ops.CONVERSATION, role="user", text=said)      # the planted fault
        return real(project, ctx, said, sender, extras)

    monkeypatch.setattr(ops_interpret, "turn", leaking)
    phone(world, REMIND)
    assert where_found(tmp_path, caplog, capfd) != []


def test_vacuity_a_planted_log_of_the_line_is_caught(world, monkeypatch, tmp_path, caplog, capfd):
    caplog.set_level(1)
    stand_in(world, monkeypatch, [REMIND_JSON])
    real = ops_interpret.turn

    def chatty(project, ctx, said, sender, extras):
        logging.getLogger("planted").warning("read %s", said)      # the planted fault
        return real(project, ctx, said, sender, extras)

    monkeypatch.setattr(ops_interpret, "turn", chatty)
    phone(world, REMIND)
    assert "log" in where_found(tmp_path, caplog, capfd)
