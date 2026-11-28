"""NR4: a routine's create, change and cancel are never done from words. Through the real messaging bridge, the stand-in Telegram provider, the real operations layer and a
stand-in interpreter model (the rig of test_commands_in_words.py), a line that asks for one of them is answered with the family sentence of a phone (`PHONE_ROUTINES`, "done on the
page") or, for a cancel, the sentence that offers the pause (`PHONE_ROUTINE_CANCEL`), and the operation of the routine is never called. A sender with no right to the line
gets the plain refusal. Offline, no network; every name and number is invented. The three are class W or a refused brake in the table, so no confirmation path is needed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_nr4_routine_words_refused.py
"""
from __future__ import annotations

import pytest

from test_commands_in_words import BARE, OWNER, PAGE, docs, is_said, op, ops, rig, says, say, with_senders, world  # noqa: F401

LINES = {
    "routine-create": (("create a routine that runs the weekly report every monday", "cria uma rotina que roda o relatorio semanal toda segunda"),
                       {"name": "weekly report", "flow": "flow-demo", "every": "monday"}, "PHONE_ROUTINES", "routine_create"),
    "routine-change": (("change routine 4 to run every friday", "muda a rotina 4 para rodar toda sexta"),
                       {"id": "4", "every": "friday"}, "PHONE_ROUTINES", "routine_change"),
    "routine-cancel": (("cancel routine 4 for good", "cancela a rotina 4 de vez"),
                       {"id": "4"}, "PHONE_ROUTINE_CANCEL", "routine_cancel"),
}


def _says(rig, text, key):
    try:
        return is_said(rig, text, key, where=PAGE[rig.language])
    except AssertionError:
        return False


@pytest.mark.parametrize("name", sorted(LINES))
def test_a_routine_create_change_or_cancel_in_words_is_refused_or_sent_elsewhere_and_nothing_is_called(rig, name):
    words, slots, key, function = LINES[name]
    calls = []
    for write in ("routine_create", "routine_change", "routine_cancel", "routine_pause", "routine_resume", "routine_approve"):
        rig.monkeypatch.setattr(ops, write, lambda *a, _w=write, **k: calls.append(_w) or {})
    text = words[0] if rig.language == "en" else words[1]
    out = rig.line(OWNER, text, op(name, slots))
    assert calls == [], (name, calls)      # the operation of the routine is never reached, whatever the reply
    # the owner of this rig has no `routine-edit` grant, so a create or a change is turned back by the policy before the table's own sentence; both are a refusal that runs nothing
    allowed = ("PHONE_NOT_ALLOWED", key) if name != "routine-cancel" else (key,)
    assert len(out) == 1 and any(_says(rig, out[0], k) for k in allowed), (name, out)
    assert rig.line(BARE, text, op(name, slots)) == [say(rig, "refusal")] and calls == []
