"""The scorer observes what the product does for a mail write (package BL7-4, fix D; limits L54 and L63).

`interpreter_pipeline.observe` drew a card for every believed operation of class E. The product does not: it opens the card of a mail write only when its family has what it needs, and
otherwise asks for it (a recipient, a body, a folder, a state) or says it could not prepare the write. `interpreter_pipeline.mail_step` mirrors `ops_interpret._carry_out` for a mail write,
with the stubs of the pipeline (one account, one mailbox, one matching message, a configured folder), and the measurement observes `clarify` where the product asks and `card` where it opens one.

This file is the proof that the mirror is the product. Over the real operations layer, the real mail family and the mail desk world of `test_send_own_account.py` (loopback stand-ins for the
mailers, a stand-in clock, one planted message per row), each row is a line and the text a stand-in model answers: the word the pipeline observes for it is `card` exactly when the product's turn
opened a card (`out["resend"]` is set), and `clarify` exactly when the product asked for something or said it could not prepare the write; the sentence is pinned too. Two rows
were the gaps the faithful mirror showed (a numbered mark the closed forms do not read, a target of seven content words) until package BL7-5 closed them: they are cards now, so that a change
of the product moves a row on purpose.
Every name and address is invented (`.example`); non-ASCII is written as `\\u` escapes. Vacuity: `mail_step` patched to return None always fails at least four rows.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_card_parity.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_mail_compose_flow import setup, phone, op, clock, forget  # noqa: F401  (the mail desk world, the stand-in model, the clock)
from test_send_own_account import world  # noqa: F401

ops = st.load("ops")
ops_natural_mail = st.load("ops_natural_mail")
interpreter_pipeline = st.load("interpreter_pipeline")

GROUPS = ("read", "talk", "interpret", "mail-send", "mail-organize", "ask-mail")
MARTA = tsm.message(1, "2026-10-20T09:00:00Z", sender="Marta Siqueira <marta.siqueira@agencia.example>", subject="Reembolso da viagem a Curitiba", id="p1", thread_id="t1",
                    text="Segue o pedido.", headers={"Message-ID": "<c1@x.example>"})
NADIA = tsm.message(2, "2026-10-20T10:00:00Z", sender="Nadia Ferreira <nadia.ferreira@feira.example>", subject="Volunteer schedule for the book fair", id="p2", thread_id="t2",
                    text="Segue o cronograma.", headers={"Message-ID": "<c2@x.example>"})
CLOCK = "2026-10-21T10:00"
ZONE = "America/Sao_Paulo"

# (name, project language, line, the stand-in model's answer, the word both must show, a piece of the product's sentence for a clarify). Every line is in free words that no closed write
# form claims, so that the product sends it to the interpreter (the test asserts it) and the pipeline's item is the same line.
ROWS = (
    ("bare-name send with a body", "en", "Could you shoot Jonas an email thanking him for the help with the move",
     op("mail-send", {"to": "Jonas", "body": "thanking him for the help with the move"}), "clarify", "What is the e-mail address of Jonas?"),
    ("typed-address send with a body", "en", "Shoot joana.silva@clinica.example an email saying the meeting is at four",
     op("mail-send", {"to": "joana.silva@clinica.example", "body": "saying the meeting is at four"}), "card", None),
    ("typed-address send with no body", "en", "Shoot joana.silva@clinica.example an email about the november quote",
     op("mail-send", {"to": "joana.silva@clinica.example", "subject": "the november quote"}), "clarify", "What should the e-mail to joana.silva@clinica.example say?"),
    ("target reply with a dictated body", "en", "Hey, answer the email Marta Siqueira sent me and say: Thanks, I accept the terms.",
     op("mail-reply", {"target": "Marta Siqueira", "body": "Thanks, I accept the terms."}), "card", None),
    ("target reply with no body", "en", "Hey, answer the email Marta Siqueira sent me",
     op("mail-reply", {"target": "Marta Siqueira"}), "clarify", "What should the reply say?"),
    ("a mail operation with empty slots", "en", "No need to list them, just archive these right away.",
     op("mail-archive", {}), "clarify", "I could not prepare it"),
    ("a recipient-less draft in a line with a mail noun", "en", "draft an email to the neighbours about our party on saturday",
     op("mail-draft", {"body": "to the neighbours about our party on saturday"}), "clarify", "I could not prepare it"),
    ("the blind item of an archive with no target (pt-BR)", "pt-BR", "N\u00e3o, nem precisa listar, arquiva esses a\u00ed logo de uma vez.",
     op("mail-archive", {}), "clarify", "n\u00e3o consegui montar o cart\u00e3o"),
    ("the blind item of a reply with no body (pt-BR)", "pt-BR", "Responde o e-mail da Marta Siqueira sobre o reembolso da viagem a Curitiba, por favor.",
     op("mail-reply", {"target": "Marta Siqueira sobre o reembolso da viagem a Curitiba"}), "clarify", "O que a resposta deve dizer?"),
    ("the blind item of a send to a bare name (pt-BR)", "pt-BR", "Escreve um e-mail pro Jonas agradecendo pela ajuda com a mudan\u00e7a no fim de semana, ele foi incr\u00edvel.",
     op("mail-send", {"to": "Jonas", "body": "agradecendo pela ajuda com a mudan\u00e7a no fim de semana, ele foi incr\u00edvel"}), "clarify", "Qual o e-mail de Jonas?"),
    ("a numbered mark the closed forms do not read (BL7-5, G1)", "pt-BR", "marca o 1 e o 2 como lido",
     op("mail-mark", {"messages": "1,2", "state": "lido"}), "clarify", "n\u00e3o consegui montar o cart\u00e3o"),          # BL7-5: bare numbers (no mail noun, no "#") are not message numbers: still asked
    ("a numbered mark with a mail noun (BL7-5, G1)", "pt-BR", "marca o email 1 e o 2 como lido",
     op("mail-mark", {"messages": "1,2", "state": "lido"}), "card", None),          # BL7-5: the numbers the model gave open the family when the closed forms read none
    ("a target of seven content words (BL7-5, G3)", "en", "Reply to Nadia Ferreira about the volunteer schedule for the book fair, thank her for the help",
     op("mail-reply", {"target": "Nadia Ferreira about the volunteer schedule for the book fair", "body": "thank her for the help"}), "card", None),          # BL7-5: the ground of a sender and a subject of seven content words ("Nadia Ferreira the volunteer schedule for the book fair")
    ("numbered trash, the model's numbers are the line's (BL7-5, G1)", "en", "trash emails 1 and 2 pls",
     op("mail-trash", {"messages": "1,2"}), "card", None),
    ("numbered trash, the model dropped a number (BL7-5, G1)", "en", "trash emails 1 and 2 pls",
     op("mail-trash", {"messages": "1"}), "clarify", "I could not prepare it"),
    ("numbers with a target beside them (BL7-5, G1)", "en", "trash emails 1 and 2 from Marta pls",
     op("mail-trash", {"messages": "1,2", "target": "Marta"}), "clarify", "I could not prepare it"),
    ("numbers of a room and a clock (BL7-5, G1)", "en", "trash the email about room 1 from the 2 o'clock meeting",
     op("mail-trash", {"messages": "1,2"}), "clarify", "I could not prepare it"),
    ("a count noun (BL7-5, G1)", "en", "trash the 2 budgets pls",
     op("mail-trash", {"messages": "2"}), "clarify", "I could not prepare it"),
    ("a numbered reply with a body (BL7-5, G1)", "en", "reply to email 1 with can we move it to next week",
     op("mail-reply", {"message": "1", "body": "can we move it to next week"}), "card", None),
    ("a numbered reply with no body (BL7-5, G1)", "en", "answer email 1 please",
     op("mail-reply", {"message": "1"}), "clarify", "What should the reply say?"),
    ("a numbered reply draft (BL7-5, G1)", "en", "put together a draft answer to email 2 with sounds good",
     op("mail-draft", {"message": "2", "body": "sounds good"}), "card", None),
    ("a numbered move with no folder named (BL7-5, G1)", "en", "stash email 1 somewhere else",
     op("mail-move", {"messages": "1"}), "clarify", "folder"),
    ("a numbered line in a project language with no write forms (BL7-5, G4)", "de", "L\u00f6sch bitte die Mails 1 und 2",
     op("mail-trash", {"messages": "1,2"}), "clarify", "ask for that in Portuguese or in English"),
    ("a move with no folder named", "en", "Can you stash the email from Marta Siqueira somewhere else",
     op("mail-move", {"target": "Marta Siqueira"}), "clarify", "folder"),
    ("an archive by target", "en", "Can you tuck away the email from Marta Siqueira",
     op("mail-archive", {"target": "Marta Siqueira"}), "card", None),
)


def product(world, monkeypatch, language, line, answer):
    """What the product's turn did for the line, the stand-in model answering `answer`: ("card" | "clarify", the reply, whether the interpreter was asked). The card of an e-mail, a reply and
    a draft is opened in this world; the preparation of an archive, a move, a mark and a trash needs the mailbox writer (test_mailbox_write.py's world), so for them the card counts as opened
    when the family resolved the arguments of the call, which is what the card is prepared from (`ops_natural_mail.resolve` returned `args`); it is the same for every row."""
    model = setup(world, monkeypatch, interpret=answer, compose=json.dumps({"subject": "S", "body": "B"}), groups=GROUPS, language=language)
    world["desk"].providers.mail["gmail"] = [dict(MARTA), dict(NADIA)]
    world["desk"].refresh("inbox")
    monkeypatch.setattr(ops_natural_mail, "_mail_sources", lambda ctx: [{"id": "inbox", "account": "google"}])
    resolved = []
    real = ops_natural_mail.resolve

    def spy(ctx, op, slots, channel, sender, said=None):
        got = real(ctx, op, slots, channel, sender, said)
        resolved.append(got)
        return got
    monkeypatch.setattr(ops_natural_mail, "resolve", spy)
    out = phone(world, line)
    opened = bool(out.get("resend")) or any("args" in got for got in resolved)
    return ("card" if opened else "clarify"), out.get("reply") or "", bool(model.of("interpret"))


def measured(language, line, answer):
    """The outcome the pipeline gives the same line and answer (no frame, the clock of the world)."""
    item = {"id": "parity-" + language, "split": "dev", "lang": language, "hard": False, "clock": CLOCK, "zone": ZONE, "channel": "messaging", "forwarded": False, "frame": None,
            "line": line, "gold": {"outcome": "op"}, "also": []}
    return interpreter_pipeline.run_item(item, 1, lambda system, user: {"ok": True, "text": answer, "finish": "stop", "usage": {}, "latency_ms": 1, "upstream": "stand-in"})


@pytest.mark.parametrize("name, language, line, answer, word, sentence", ROWS, ids=[row[0] for row in ROWS])
def test_the_pipeline_observes_a_card_exactly_when_the_product_opens_one(name, language, line, answer, word, sentence, world, clock, monkeypatch):
    got, reply, asked = product(world, monkeypatch, language, line, answer)
    out = measured(language, line, answer)
    assert asked, (name, "the product did not send the line to the interpreter", reply)
    assert got == word, (name, got, reply)          # the oracle: the product's own turn, with the row's literal
    assert out["observed"] == got, (name, out["observed"], got, reply)
    if word == "clarify" and sentence:
        assert sentence in reply, (name, reply)


def test_a_numbered_archive_is_read_by_the_interpreter_and_the_pipeline_observes_what_the_product_does(world, clock, monkeypatch):
    """"arquiva os e-mails 1 e 2" was claimed by the closed forms before the interpreter, so the product never asked the model (S41-11 took that claim out): the product asks the model now, and the
    pipeline, which mirrors the product, observes exactly what the product's own turn gives for the same line and answer."""
    line, answer = "arquiva os e-mails 1 e 2", op("mail-archive", {"messages": "1,2"})
    got, reply, asked = product(world, monkeypatch, "pt-BR", line, answer)
    assert asked, (got, reply, "the product sends the line to the interpreter")
    assert measured("pt-BR", line, answer)["observed"] == got, (got, reply)


def test_a_clarify_of_the_mail_step_has_the_slot_the_product_asks_first(world, clock, monkeypatch):
    by_name = {row[0]: row for row in ROWS}
    for name, slot in (("bare-name send with a body", "to"), ("typed-address send with no body", "body"), ("target reply with no body", "body"), ("a move with no folder named", "folder")):
        _, language, line, answer, _, _ = by_name[name]
        assert measured(language, line, answer)["detail"] == {"slot": slot}, name
    for name in ("a mail operation with empty slots", "a numbered mark the closed forms do not read (BL7-5, G1)"):
        _, language, line, answer, _, _ = by_name[name]
        assert measured(language, line, answer)["detail"] == {}, name          # "I could not prepare it": no slot


def test_an_operation_that_is_not_a_mail_write_is_still_a_card():
    answer = op("event-create", {"title": "dentist", "time": "thursday at 3pm"}, time_iso="2026-10-22T15:00", weekday="thu")
    out = measured("en", "put the dentist on the calendar thursday at 3pm", answer)
    assert out["observed"] == "card" and out["detail"]["op"] == "event-create"


def test_a_language_the_tables_do_not_detect_is_read_by_the_closed_forms():
    out = measured("es", "Responde al correo de Marta Siqueira", op("mail-reply", {"target": "Marta Siqueira"}))
    assert out["observed"] == "clarify" and out["detail"] == {}, out          # the product says IX_WRITE_LANGUAGE: a clarify with no slot


def test_vacuity_a_step_that_never_asks_fails_at_least_four_rows(monkeypatch, world, clock):
    monkeypatch.setattr(interpreter_pipeline, "mail_step", lambda decision, line, now, lang: None)
    failed = []
    for name, language, line, answer, word, _ in ROWS:
        if measured(language, line, answer)["observed"] != word:
            failed.append(name)
    assert len(failed) >= 4, failed
