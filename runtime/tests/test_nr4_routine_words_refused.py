"""NR4: a routine's create, change and cancel are never done from words. Through the real messaging bridge, the stand-in Telegram provider, the real operations layer and a
stand-in interpreter model (the rig of test_commands_in_words.py), a line that asks for one of them is answered with the family sentence of a phone (`PHONE_ROUTINES`, "done on the
page") or, for a cancel, the sentence that offers the pause (`PHONE_ROUTINE_CANCEL`), and the operation of the routine is never called. A sender with no right to the line
gets the plain refusal. Offline, no network; every name and number is invented. The three are class W or a refused brake in the table, so no confirmation path is needed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_nr4_routine_words_refused.py
"""
from __future__ import annotations

import pytest

from test_ask import accept
from test_commands_in_words import PROFILES2, SENDERS2, BARE, OWNER, PAGE, docs, is_said, op, ops, rig, says, say, with_senders, world  # noqa: F401

LINES = {
    "routine-create": (("create a routine that runs the weekly report every monday", "cria uma rotina que roda o relatorio semanal toda segunda"),
                       {}, "PHONE_ROUTINES", "routine_create"),
    "routine-change": (("change routine 4 to run every friday", "muda a rotina 4 para rodar toda sexta"),
                       {"id": "4"}, "PHONE_ROUTINES", "routine_change"),
    "routine-cancel": (("cancel routine 4 for good", "cancela a rotina 4 de vez"),
                       {"id": "4"}, "PHONE_ROUTINE_CANCEL", "routine_cancel"),
}


@pytest.mark.parametrize("name", sorted(LINES))
def test_a_routine_create_change_or_cancel_in_words_is_refused_or_sent_elsewhere_and_nothing_is_called(rig, name):
    words, slots, key, function = LINES[name]
    calls = []
    for write in ("routine_create", "routine_change", "routine_cancel", "routine_pause", "routine_resume", "routine_approve"):
        rig.monkeypatch.setattr(ops, write, lambda *a, _w=write, **k: calls.append(_w) or {})
    text = words[0] if rig.language == "en" else words[1]
    out = rig.line(OWNER, text, op(name, slots))
    assert calls == [], (name, calls)      # the operation of the routine is never reached, whatever the reply
    assert len(out) == 1 and (is_said(rig, out[0], "PHONE_NOT_ALLOWED", where=PAGE[rig.language]) if name != "routine-cancel" else is_said(rig, out[0], key, where=PAGE[rig.language])), (name, out)      # the rig's owner may not edit routines: the policy turns create and change back
    if name != "routine-cancel":      # a sender who MAY edit routines (the grant on the channel and in the sender's profile) still cannot do it from words
        accept(rig.world["path"], policies={**PROFILES2, "owner": [*PROFILES2["owner"], "routine-edit"]}, messaging={"senders": SENDERS2},
               channels={"messaging": ["read", "talk", "answer", "routine-brakes", "routine-edit"]}, **({} if rig.language == "en" else {"language": "pt-BR"}))
        out = rig.line(OWNER, text, op(name, slots))
        assert says(rig, out, key, where=PAGE[rig.language]) and calls == [], (name, out, calls)
    assert rig.line(BARE, text, op(name, slots)) == [say(rig, "refusal")] and calls == []
