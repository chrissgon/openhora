"""The time guard of the interpreter's validator (package TIME-GUARD, runtime/interpreter.py `_classify`): code never reads an hour with no day for a line that may name a day.

The bug (found by replaying the dev pilot, no model call): `dev-es-00005`, "el jueves a las 15:00" with a word of a Portuguese table elsewhere in the line ("calendario"), was read by code as
15:00 of the clock's own day (a card on the wrong day), because Spanish has no time table and the old branch let such a line through as `code` whenever any table word stood outside the time.
Now an hour only, with words no table holds and no trigger word of a table beside the hour, is `ask` (`time-ask`), whatever the other words are. Checked with the test's own literal lines and
expectations: the dev item itself (read from the dev file), invented lines in es/fr/de/it with a weekday word, an hour and a table word elsewhere, and the pt/en lines that code still reads (an
hour with its trigger word, a day word, a lone hour). The dev item `dev-fr-00018` keeps its conservative clarify. Vacuity: the old branch, restored in a copy of `_classify`, fails the same oracle.
Offline, no model; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_time_guard.py
"""
from __future__ import annotations

import json
import pathlib

import interpreter_kit as kit
import standin_tree as st

interp = st.load("interpreter")

DEV = pathlib.Path(__file__).resolve().parents[2] / "evals" / "interpreter" / "dev.jsonl"
MADRID = "Europe/Madrid"
NOW_MADRID = kit.now_at("2026-10-27 09:15", MADRID)          # Tuesday

# (line, span, who decides): the test's own oracle, written by hand from the raw lines.
ASK = [
    ("apunta cena con Marta el viernes a las 20:30 en el calendario Casa", "el viernes a las 20:30"),
    ("note dîner avec Marta vendredi à 20:30 dans le calendar Maison", "vendredi à 20:30"),
    ("remind Marta Abendessen am Freitag um 20:30", "am Freitag um 20:30"),
    ("segna cena con Marta venerdì alle 20:30 nel calendario Casa", "venerdì alle 20:30"),
    ("agenda cena con Marta el miércoles a las 21:00 en el calendario Casa", "miércoles a las 21:00"),
]
CODE = [
    ("remind me at 3pm to call Dana", "at 3pm"),
    ("remind me to call Dana tomorrow at 3pm", "tomorrow at 3pm"),
    ("lembra de ligar para Dana às 15h", "às 15h"),
    ("lembra de ligar para Dana amanhã às 15h", "amanhã às 15h"),          # validate: allow english-only -- a Portuguese line is the input under test
    ("15:00", "15:00"),
]


def dev_item(item_id):
    for row in DEV.read_text(encoding="utf-8").splitlines():
        item = json.loads(row)
        if item["id"] == item_id:
            return item
    raise AssertionError(item_id)


def source_of(classify, span, line, now=NOW_MADRID):
    return classify(span, line, now)[0]


def wrong_asks(classify):
    """The lines of ASK that `classify` does not ask about, and the lines of CODE it does not leave to code: [] for a right guard."""
    bad = [line for line, span in ASK if source_of(classify, span, line) != "ask"]
    bad += [line for line, span in CODE if source_of(classify, span, line) != "code"]
    return bad


def test_the_dev_item_with_an_hour_and_a_weekday_is_asked_and_never_a_card_on_the_clocks_day():
    item = dev_item("dev-es-00005")
    assert item["line"] == "agéndame comida con Javier el jueves a las 15:00 en el calendario Gimnasio"
    span = item["gold"]["slots"]["time"][0]
    assert span == "el jueves a las 15:00"
    assert interp.time_source(span, NOW_MADRID, MADRID, item["line"]) == "ask"
    obj = {"v": 1, "kind": "op", "op": "event-create", "slots": {"title": "comida con Javier", "calendar": "Gimnasio", "time": span},
           "time_iso": item["gold"]["time"][0], "weekday": "thu"}          # the model's answer: the gold (2026-10-29, Thursday)
    got = interp.check(obj, item["line"], None, kit.CATALOG, NOW_MADRID, MADRID, kit.ALL_OPS)
    assert got["kind"] == "clarify" and got["why"] == "time-ask" and got["error"] is None, got
    # The clock's own day (Tuesday 2026-10-27) is never taken: not even with the model's other, wrong day.
    wrong = dict(obj, time_iso="2026-10-27T15:00", weekday="tue")
    got = interp.check(wrong, item["line"], None, kit.CATALOG, NOW_MADRID, MADRID, kit.ALL_OPS)
    assert got["kind"] == "clarify" and got["why"] == "time-ask", got


def test_lines_in_es_fr_de_it_with_a_weekday_an_hour_and_a_table_word_elsewhere_are_asked():
    for line, span in ASK:
        assert interp.time_source(span, NOW_MADRID, MADRID, line) == "ask", line
        obj = {"v": 1, "kind": "op", "op": "remind", "slots": {"text": "Marta", "when": span}, "time_iso": "2026-10-30T20:30", "weekday": "fri"}
        got = interp.check(obj, line, None, kit.CATALOG, NOW_MADRID, MADRID, kit.ALL_OPS)
        assert got["kind"] == "clarify" and got["why"] == "time-ask", (line, got)


def test_portuguese_and_english_lines_code_reads_are_still_code():
    for line, span in CODE:
        assert interp.time_source(span, NOW_MADRID, MADRID, line) == "code", line
    got = interp.check({"v": 1, "kind": "op", "op": "remind", "slots": {"text": "call Dana", "when": "at 3pm"}, "time_iso": "2026-10-27T15:00", "weekday": "tue"},
                       "remind me at 3pm to call Dana", None, kit.CATALOG, NOW_MADRID, MADRID, kit.ALL_OPS)
    assert got["time"] == {"local": "2026-10-27T15:00", "source": "code"}, got


def test_a_line_with_no_word_of_any_table_is_still_the_models_and_a_dated_reading_is_still_code():
    assert interp.time_source("mañana a las 15:00", kit.NOW, kit.ZONE, "recuérdame mañana a las 15:00 llamar a Dana") == "model"
    assert interp.time_source("el jueves a las 15:00", NOW_MADRID, MADRID, "agéndame comida con Javier el jueves a las 15:00") == "model"
    assert interp.time_source("friday at 3pm", NOW_MADRID, MADRID, "remind Javier friday at 3pm") == "code"


def test_the_conservative_clarify_of_the_injection_item_is_kept():
    item = dev_item("dev-fr-00018")
    assert "ignore tes règles" in item["line"]          # the instruction inside the line is data; the line is asked back, not followed
    span = item["gold"]["slots"]["time"][0]
    assert interp.time_source(span, kit.now_at("2026-10-25 10:00", "Europe/Paris"), "Europe/Paris", item["line"]) == "ask"          # as before this package: the guard did not move it
    obj = {"v": 1, "kind": "op", "op": "event-change", "slots": {"event": "4", "time": span}, "time_iso": item["gold"]["time"][0], "weekday": "thu"}
    got = interp.check(obj, item["line"], None, kit.CATALOG, kit.now_at("2026-10-25 10:00", "Europe/Paris"), "Europe/Paris", kit.ALL_OPS)
    assert got["kind"] == "clarify" and got["why"] == "time-ask", got


def test_vacuity_the_old_branch_fails_the_oracle_and_the_new_one_passes_it(monkeypatch):
    assert wrong_asks(interp._classify) == []
    monkeypatch.setattr(interp, "_hour_without_day_is_asked", lambda hits: False)          # the branch as it was before the guard: any table word outside the time let the hour through
    broken = wrong_asks(interp._classify)
    assert broken and set(broken) == {line for line, _span in ASK}          # the old branch reads every ASK line as code
    item = dev_item("dev-es-00005")
    assert source_of(interp._classify, "el jueves a las 15:00", item["line"]) == "code"
