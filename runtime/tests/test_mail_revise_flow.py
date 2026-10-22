"""A waiting e-mail card is changed by words and replaced by a new card (slice S13, runtime/ops_card_revise.py, runtime/mail_revise.py, limits L55, L63 and L64).

Over the REAL operations layer, the real mail family and the W2 stand-in mailers on loopback (test_mail_compose_flow.py's world: no Google or Microsoft host is called), a stand-in
clock, and a stand-in model that answers the interpreter's call, the compose call and the revise call by hand-written texts and counts all three. Every expectation is a literal of this
file: the lines, the model's texts, the card's lines, the sentences. Every name and address is invented (`.example`).

Held here:
  * the live line of 2026-10-22 on the live card: the card ended with "Atenciosamente,", the line asks for a name after it, and a NEW card opens with the name after the closing, the same
    From, the same To; the old card can never be approved (its hash is refused) and nothing is sent;
  * a model answer that adds an address or a link, that does not hold a quoted text of the line, that is not valid, or a failed call: one plain sentence, the old card still open, no new card;
  * a line that asks to change who receives the e-mail: one sentence, no model call, no new card; the recipients and the account of a new card are the old card's, always;
  * a line code recognises as a request, a word that decides the card, a changed card (another hash), a sender who is not read by the interpreter, and a prompt that is no longer the pinned
    one are not a change; a line that changes nothing and asks for nothing goes on;
  * nothing of the instruction, the subject or the body is logged or printed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_revise_flow.py
"""
from __future__ import annotations

import base64
import email
import json
import logging
from pathlib import Path

import pytest

import standin_tree as st
from test_mail_compose_flow import ADDRESS, SENDER, ZONE, card_lines, clock, forget, op, phone, text_of  # noqa: F401
from test_send_own_account import ACCOUNTS, world  # noqa: F401  (the own-account mail world)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_card_revise = st.load("ops_card_revise")
interpreter_route = st.load("interpreter_route")
interpreter_enable = st.load("interpreter_enable")
mail_compose = st.load("mail_compose")
mail_revise = st.load("mail_revise")
phrases = st.load("phrases")

BARE = "telegram:5151"
CLOSED = "Olá,\n\nGostaria de marcar uma reunião amanhã às 16h. Você teria disponibilidade?\n\nAtenciosamente,"      # validate: allow english-only -- the stand-in model's Portuguese answer
SUBJECT = "Reunião amanhã às 16h"      # validate: allow english-only -- the stand-in subject in Portuguese
# A text sent as written ("texto exato:"): the card keeps the closing formula that ends it, which the compose call itself no longer leaves dangling (S12). It is the card the live case needs.
LIVE = f"Envie um email para {ADDRESS} assunto {SUBJECT}. texto exato: {CLOSED}"      # validate: allow english-only -- the Portuguese line under test
LIVE_DECISION = op("mail-send", {"to": ADDRESS, "subject": SUBJECT, "body": "texto exato: " + CLOSED})
COMPOSE = json.dumps({"subject": "Reunião amanhã às 16h", "body": CLOSED}, ensure_ascii=False)      # validate: allow english-only -- the stand-in model's Portuguese answer
INSTRUCTION = 'Ajuste o corpo do email. Após "Atenciosamente," coloque "Christopher Gonçalves"'      # validate: allow english-only -- the live line, Portuguese
REVISED_BODY = CLOSED + "\nChristopher Gonçalves"      # validate: allow english-only -- the stand-in model's Portuguese answer
REVISED = json.dumps({"subject": "Reunião amanhã às 16h", "body": REVISED_BODY}, ensure_ascii=False)      # validate: allow english-only -- the stand-in model's Portuguese answer
FAILED = "Não consegui fazer esse ajuste. Diga de outro jeito ou rejeite o card."      # validate: allow english-only -- the Portuguese sentence under test
RECIPIENTS = ("Não consigo mudar quem recebe um e-mail ajustando o card. Rejeite este card e peça um novo e-mail para a pessoa certa.")      # validate: allow english-only -- the Portuguese sentence under test
ZEBRA = "ZEBRA-INSTRUCTION-5521"
GROUPS = ("read", "talk", "interpret", "mail-send", "mail-organize", "reject-cancel")


class Model:
    """The stand-in for the daily route: `interpret`, `compose` and `revise` are the texts (or an exception, or None for a failed call) it answers; `calls` lists what each was shown."""

    def __init__(self, monkeypatch, interpret=LIVE_DECISION, compose=COMPOSE, revise=REVISED):
        self.answers, self.calls = {"interpret": interpret, "compose": compose, "revise": revise}, []
        monkeypatch.setattr(interpreter_route, "complete", self.complete)
        monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)

    def complete(self, route_id, system, user, **kw):
        kind = "compose" if system == mail_compose.prompt_template() else "revise" if system == mail_revise.prompt_template() else "interpret"
        self.calls.append({"kind": kind, "route": route_id, "system": system, "user": user, "kw": kw})
        answer = self.answers[kind]
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return {"ok": False, "code": "E_TIMEOUT"}
        return {"ok": True, "text": answer, "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}

    def of(self, kind):
        return [c for c in self.calls if c["kind"] == kind]


def setup(world, monkeypatch, language="pt-BR", groups=GROUPS, **answers):
    """The project with one account (google), a sender who may ask in words, send mail and reject, one who may not interpret, and the stand-in model."""
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = {"google": ACCOUNTS["google"]}
    raw["language"] = language
    raw["policies"] = {"owner": list(groups), "bare": ["read", "talk", "mail-send", "reject-cancel"]}
    raw["channels"] = {"page": ["read"]}
    raw["messaging"] = {"senders": {"telegram": [{"id": "4242", "policy": "owner"}, {"id": "5151", "policy": "bare"}]}}
    path.write_text(json.dumps(raw), encoding="utf-8")
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    return Model(monkeypatch, **answers)


def opened(world, out):
    """(the id of the card, its hash) of a card a line opened."""
    return out["resend"], ops.pending(world["path"], out["resend"])["payload_sha256"]


def check(world, number, sha, line, sender=SENDER):
    return ops.card_revise_check(world["path"], number, sha, line, channel="messaging", sender=sender)


def revise(world, number, sha, line, sender=SENDER):
    return ops.card_revise(world["path"], number, sha, line, channel="messaging", sender=sender)


def status(world, number):
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_get(ctx["conn"], number)["status"]


def open_cards(world):
    ctx = ops_core.context(world["path"])
    return [p["id"] for p in ctx["store"].pending_list(ctx["conn"], "open")]


def nothing_sent(world):
    assert world["gmail"].requests == [] and world["graph"].requests == []


def live_card(world, monkeypatch, **answers):
    model = setup(world, monkeypatch, **answers)
    number, sha = opened(world, phone(world, LIVE))
    assert text_of(card_lines(world, {"resend": number}))[-1] == "Atenciosamente,", "the card of the live case ends with the closing and no name"
    return model, number, sha


# --- the live line ---------------------------------------------------------------------------------------------------------------------------------


def test_the_live_instruction_replaces_the_card_with_one_whose_text_ends_with_the_name_and_the_old_card_is_never_approvable(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)
    before = card_lines(world, {"resend": old})
    assert check(world, old, sha, INSTRUCTION) == "mail"
    got = revise(world, old, sha, INSTRUCTION)
    new = got["resend"]
    assert isinstance(new, int) and new != old
    assert got["say"] == "Pronto: aqui está o e-mail com o seu ajuste. O card anterior não vale mais; aprove ou rejeite este."      # validate: allow english-only -- the Portuguese sentence under test
    lines = card_lines(world, got)
    assert lines[1:4] == ["From your own account: pat@example.com (google)", f"To: {ADDRESS}", "Subject: Reunião amanhã às 16h"]      # validate: allow english-only -- the stand-in model's answer
    assert before[1:3] == lines[1:3], "the same From and the same To"
    assert text_of(lines)[-2:] == ["Atenciosamente,", "Christopher Gonçalves"]      # validate: allow english-only -- the stand-in model's answer
    assert text_of(lines)[-1] == "Christopher Gonçalves" and text_of(lines)[:-1] == text_of(before)      # validate: allow english-only -- the stand-in model's answer
    assert status(world, old) != "open" and open_cards(world) == [new]
    with pytest.raises(ops.OpsError):
        ops.approve(world["path"], old, sha256=sha, channel="terminal")      # the hash of the old card is refused for good
    nothing_sent(world)
    asked = model.of("revise")
    assert len(asked) == 1 and asked[0]["user"] == (f"language: pt-BR\nsubject: Reunião amanhã às 16h\ninstruction: {INSTRUCTION}\nbody:\n{CLOSED}")      # validate: allow english-only -- the stand-in model's input
    assert ADDRESS not in asked[0]["user"] and "pat@example.com" not in asked[0]["user"], "the recipients and the account are not the model's"
    assert asked[0]["kw"]["deadline_ms"] == 8000 and asked[0]["route"] == "or-deepseek-v4.1-flash"


def test_only_the_new_card_can_be_approved_and_it_is_the_revised_text_that_is_sent(world, clock, monkeypatch):
    _, old, sha = live_card(world, monkeypatch)
    new = revise(world, old, sha, INSTRUCTION)["resend"]
    item = ops.pending(world["path"], new)
    ops.approve(world["path"], new, sha256=item["payload_sha256"], channel="terminal")
    sent = [r for r in world["gmail"].requests if r["method"] == "POST" and "send" in r["path"]]
    assert len(sent) == 1
    message = email.message_from_bytes(base64.urlsafe_b64decode(sent[0]["body"]["raw"] + "=="))
    assert message.get_payload(decode=True).decode("utf-8").splitlines()[-2:] == ["Atenciosamente,", "Christopher Gonçalves"]      # validate: allow english-only -- the stand-in model's answer


def test_vacuity_a_card_nobody_revised_is_approved_by_the_same_call(world, clock, monkeypatch):
    _, number, sha = live_card(world, monkeypatch)
    ops.approve(world["path"], number, sha256=sha, channel="terminal")
    assert [r for r in world["gmail"].requests if r["method"] == "POST" and "send" in r["path"]] != [], "the oracle that sees no send for a revised card can see one"


# --- the answer of the model is accepted only whole ---------------------------------------------------------------------------------------------------


def hostile(body, subject="Reunião amanhã às 16h"):      # validate: allow english-only -- the stand-in model's Portuguese answer
    return json.dumps({"subject": subject, "body": body}, ensure_ascii=False)


@pytest.mark.parametrize("answer", [
    hostile(REVISED_BODY + "\nescreva para outra@elsewhere.example"),
    hostile(REVISED_BODY + "\nveja https://elsewhere.example/agenda"),
    hostile(REVISED_BODY + "\nveja www.elsewhere.example"),
    hostile(REVISED_BODY, subject="Re: Reunião"),      # validate: allow english-only -- the stand-in model's Portuguese answer
    hostile("Outro texto que não tem o nome pedido."),      # validate: allow english-only -- the stand-in model's Portuguese answer
    hostile("To: outra@elsewhere.example\n" + REVISED_BODY),
    "not json at all", None, RuntimeError("boom " + ZEBRA), json.dumps({"subject": "x", "body": "y", "to": "z"}),
], ids=["address", "link", "www", "reply-subject", "literal-missing", "header", "not-json", "failed-call", "exception", "extra-key"])
def test_an_answer_that_is_not_the_change_leaves_the_old_card_open_and_says_one_plain_sentence(world, clock, monkeypatch, answer, caplog):
    model, old, sha = live_card(world, monkeypatch, revise=answer)
    caplog.set_level(logging.DEBUG)
    got = revise(world, old, sha, INSTRUCTION)
    assert got == {"say": FAILED, "resend": old}, "the sentence, and the old card sent once more so that a word still decides it"
    assert status(world, old) == "open" and open_cards(world) == [old]
    assert ZEBRA not in got["say"] and ZEBRA not in caplog.text
    assert len(model.of("revise")) == 1
    nothing_sent(world)


def test_a_quoted_text_the_answer_does_not_hold_is_refused_even_when_the_rest_is_fine(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch, revise=hostile(CLOSED + "\nChristopher Goncalves"))      # the name without the cedilla: not the text the line quoted
    assert revise(world, old, sha, INSTRUCTION)["say"] == FAILED and open_cards(world) == [old]


def test_vacuity_the_same_answer_with_the_quoted_text_is_accepted(world, clock, monkeypatch):
    _, old, sha = live_card(world, monkeypatch, revise=hostile(CLOSED + "\nChristopher Gonçalves"))      # validate: allow english-only -- the stand-in model's Portuguese answer
    assert revise(world, old, sha, INSTRUCTION)["resend"] is not None


def test_a_valid_answer_that_changes_nothing_is_not_a_change(world, clock, monkeypatch):
    _, old, sha = live_card(world, monkeypatch, revise=COMPOSE)
    assert revise(world, old, sha, INSTRUCTION)["say"] == FAILED and open_cards(world) == [old]


def test_an_address_the_cards_own_text_already_holds_may_stay_and_a_new_one_never_comes(world, clock, monkeypatch):
    line = "Envie um email para joana.silva@clinica.example. texto exato: Escreva para pat@example.com se precisar.\n\nAtenciosamente,"      # validate: allow english-only -- the Portuguese line under test
    typed = "Escreva para pat@example.com se precisar.\n\nAtenciosamente,"      # validate: allow english-only -- the Portuguese text under test
    model = setup(world, monkeypatch, interpret=op("mail-send", {"to": ADDRESS, "body": "texto exato: " + typed}))
    old, sha = opened(world, phone(world, line))
    assert text_of(card_lines(world, {"resend": old}))[0] == "Escreva para pat@example.com se precisar."      # validate: allow english-only -- the Portuguese text under test
    model.answers["revise"] = hostile(typed + "\nChristopher Gonçalves")      # validate: allow english-only -- the stand-in model's answer
    new = revise(world, old, sha, INSTRUCTION)["resend"]
    assert new is not None
    model.answers["revise"] = hostile(typed.replace("pat@example.com", "outra@elsewhere.example") + "\nChristopher Gonçalves")      # validate: allow english-only -- the stand-in model's answer
    assert revise(world, new, ops.pending(world["path"], new)["payload_sha256"], INSTRUCTION)["say"] == FAILED


def test_an_address_in_a_line_that_asks_for_no_change_is_a_new_request_in_free_words_and_goes_on(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)
    assert revise(world, old, sha, "Envie um email para ana@client.example. Quero marcar uma reuniao") == {"pass": True}      # validate: allow english-only -- the Portuguese line under test
    assert model.of("revise") == [] and open_cards(world) == [old]


# --- the recipients and the account are the old card's -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["Mande para outra@elsewhere.example em vez da Joana", "Mude o destinatário para a Ana", 'Troque o destinatário e coloque "Christopher Gonçalves" no fim', "Add a Cc to the boss",      # validate: allow english-only -- the Portuguese and English lines under test
                                  "Change the recipient to Ana"])
def test_a_line_that_asks_to_change_who_receives_the_e_mail_gets_one_sentence_and_no_model_call_and_no_card(world, clock, monkeypatch, line):
    model, old, sha = live_card(world, monkeypatch)
    got = revise(world, old, sha, line)
    assert got == {"say": RECIPIENTS, "resend": old}
    assert model.of("revise") == [] and open_cards(world) == [old] and status(world, old) == "open"
    nothing_sent(world)


def test_vacuity_a_quoted_word_that_looks_like_a_recipient_word_is_not_a_request_to_change_it(world, clock, monkeypatch):
    _, old, sha = live_card(world, monkeypatch, revise=hostile(CLOSED + "\nDestinatário: eu"))      # the quoted text is the person's own
    assert mail_revise.asks_recipients('Após "Atenciosamente," coloque "Prezado destinatário"') is False      # validate: allow english-only -- the Portuguese line under test
    assert mail_revise.asks_recipients("Mude o destinatário") is True


def test_the_new_card_keeps_the_recipients_and_the_account_even_when_the_model_names_others(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)
    model.answers["revise"] = json.dumps({"subject": "Reunião amanhã às 16h", "body": REVISED_BODY, "to": "outra@elsewhere.example"}, ensure_ascii=False)      # validate: allow english-only -- the stand-in model's answer
    assert revise(world, old, sha, INSTRUCTION)["say"] == FAILED
    model.answers["revise"] = REVISED
    new = revise(world, old, sha, INSTRUCTION)["resend"]
    assert card_lines(world, {"resend": new})[1:3] == ["From your own account: pat@example.com (google)", f"To: {ADDRESS}"]
    assert "elsewhere.example" not in ops.pending(world["path"], new)["body"]


# --- what a line is for a card ------------------------------------------------------------------------------------------------------------------------


def test_a_line_code_recognises_a_word_that_decides_a_card_a_command_and_a_greeting_are_not_a_change(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)
    for line in ("aprovo", "sim", "não", "/pending", "oi", "me lembra de ligar amanhã às 9h", "quais são meus lembretes", "o que está pendente?"):      # validate: allow english-only -- the Portuguese lines under test
        assert check(world, old, sha, line) is None, line
    assert model.of("revise") == []
    assert check(world, old, sha, INSTRUCTION) == "mail", "vacuity: the live line is one"


NOT_INSTRUCTIONS = ["lista os emails", "obrigado", "pode enviar", "esquece", "qual o clima amanhã?", "também preciso marcar o dentista sexta", "Envie um email para ana@client.example. Quero marcar uma reuniao"]      # validate: allow english-only -- the Portuguese lines under test


@pytest.mark.parametrize("line", NOT_INSTRUCTIONS)
def test_a_line_that_asks_for_no_change_never_reaches_the_model_and_goes_on(world, clock, monkeypatch, line):
    model, old, sha = live_card(world, monkeypatch, revise=hostile(CLOSED + "\n" + line))      # a model that would append the line to the card is never asked
    assert check(world, old, sha, line) is None
    assert revise(world, old, sha, line) == {"pass": True}
    assert model.of("revise") == [] and open_cards(world) == [old] and status(world, old) == "open"
    assert check(world, old, sha, INSTRUCTION) == "mail", "vacuity: a line with a change word and a quoted text is one"


def test_the_text_of_an_exact_text_card_is_never_sent_to_the_model_by_a_later_line_that_asks_for_nothing(world, clock, monkeypatch):
    line = "Envie um email para joana.silva@clinica.example. texto exato: Segredo " + ZEBRA + ".\n\nAtenciosamente,"      # validate: allow english-only -- the Portuguese line under test
    model = setup(world, monkeypatch, interpret=op("mail-send", {"to": ADDRESS, "body": "texto exato: Segredo " + ZEBRA + ".\n\nAtenciosamente,"}))      # validate: allow english-only -- the Portuguese line under test
    old, sha = opened(world, phone(world, line))
    for later in NOT_INSTRUCTIONS:
        assert revise(world, old, sha, later) == {"pass": True}
    assert model.of("revise") == [] and all(ZEBRA not in c["user"] for c in model.calls if c["kind"] != "interpret")
    revise(world, old, sha, INSTRUCTION)
    assert [ZEBRA in c["user"] for c in model.of("revise")] == [True], "a real instruction sends the card's text, and only then"


def test_a_card_that_changed_or_is_another_card_is_not_changed_and_a_replaced_card_says_so(world, clock, monkeypatch):
    _, old, sha = live_card(world, monkeypatch)
    assert check(world, old, "0" * 64, INSTRUCTION) is None
    assert check(world, old + 99, sha, INSTRUCTION) is None
    new = revise(world, old, sha, INSTRUCTION)["resend"]
    assert check(world, old, sha, INSTRUCTION) == "replaced" and check(world, new, ops.pending(world["path"], new)["payload_sha256"], INSTRUCTION) == "mail"
    assert check(world, old, sha, "obrigado") is None, "a line that asks for no change is not told anything"
    assert revise(world, old, sha, INSTRUCTION) == {"say": "Esse card foi substituído por um mais novo. Ajuste o card mais novo ou peça de novo.", "resend": None}      # validate: allow english-only -- the Portuguese sentence under test
    ops.reject(world["path"], new, channel="terminal")
    assert check(world, new, ops.pending(world["path"], new)["payload_sha256"], INSTRUCTION) is None, "a card that was rejected by the person is not a replaced one"


# --- the worst case is no open card, never two ----------------------------------------------------------------------------------------------------------


def test_a_card_that_cannot_be_ended_stops_the_change_before_anything_is_opened(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)
    real = ops.reject

    def refuse(project, pending_id, **kw):
        raise ops.OpsError("the store is busy", 1)
    monkeypatch.setattr(ops, "reject", refuse)
    got = revise(world, old, sha, INSTRUCTION)
    monkeypatch.setattr(ops, "reject", real)
    assert got == {"say": FAILED, "resend": old} and open_cards(world) == [old] and status(world, old) == "open"
    assert ops_core.context(world["path"])["store"].pending_list(ops_core.context(world["path"])["conn"], "open")[0]["id"] == old


def test_a_new_card_that_cannot_be_opened_leaves_no_open_card_and_says_to_ask_again(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)

    def cannot(project, line, **kw):
        raise ops.OpsError("no card", 1)
    monkeypatch.setattr(ops, "natural_write", cannot)
    got = revise(world, old, sha, INSTRUCTION)
    assert got == {"say": "Não consegui preparar o card ajustado e o anterior foi encerrado. Peça de novo.", "resend": None}      # validate: allow english-only -- the Portuguese sentence under test
    assert open_cards(world) == [] and status(world, old) != "open"
    nothing_sent(world)


def test_a_new_card_that_is_not_what_was_asked_is_ended_and_no_card_stays_open(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)
    real = ops.natural_write

    def other(project, line, **kw):
        seed = dict(kw["seed"], slots=dict(kw["seed"]["slots"], body=kw["seed"]["slots"]["body"] + "\nUm texto a mais."))      # validate: allow english-only -- a Portuguese text under test
        return real(project, line, **dict(kw, seed=seed))
    monkeypatch.setattr(ops, "natural_write", other)
    got = revise(world, old, sha, INSTRUCTION)
    assert got["resend"] is None and got["say"].endswith("Peça de novo.") and open_cards(world) == []      # validate: allow english-only -- the Portuguese sentence under test
    nothing_sent(world)


def test_a_card_approved_while_the_model_answered_is_told_so_and_nothing_else_is_opened(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)
    real = model.complete

    def approving(route_id, system, user, **kw):
        if system == mail_revise.prompt_template():
            ops.approve(world["path"], old, sha256=sha, channel="terminal")      # the person approves the card while the revision is being prepared
        return real(route_id, system, user, **kw)
    monkeypatch.setattr(interpreter_route, "complete", approving)
    got = revise(world, old, sha, INSTRUCTION)
    assert got == {"say": "Esse card já foi decidido antes de eu conseguir ajustá-lo, então nada foi alterado.", "resend": None}      # validate: allow english-only -- the Portuguese sentence under test
    assert open_cards(world) == [] and len([r for r in world["gmail"].requests if r["method"] == "POST" and "send" in r["path"]]) == 1, "the old card was sent as approved, once"


def test_a_sender_who_is_not_read_by_the_interpreter_or_may_not_reject_is_not_touched(world, clock, monkeypatch):
    model, old, sha = live_card(world, monkeypatch)
    assert check(world, old, sha, INSTRUCTION, sender=BARE) is None      # the other sender holds no `interpret`
    assert revise(world, old, sha, INSTRUCTION, sender=BARE) == {"pass": True}
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["policies"]["owner"] = [g for g in GROUPS if g != "reject-cancel"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert check(world, old, sha, INSTRUCTION) is None, "a sender who cannot end the old card cannot get a second one"
    assert model.of("revise") == [] and open_cards(world) == [old]


def test_a_changed_revise_prompt_turns_the_change_off_and_leaves_the_interpreter_on(world, clock, monkeypatch):
    _, old, sha = live_card(world, monkeypatch)
    monkeypatch.setattr(mail_revise, "prompt_sha256", lambda: "0" * 64)
    assert interpreter_enable.active("pt-BR") is not None and interpreter_enable.revise_active("pt-BR") is None
    assert check(world, old, sha, INSTRUCTION) is None


def test_a_draft_card_is_changed_the_same_way_and_a_reply_card_gets_the_sentence_that_it_cannot_be(world, clock, monkeypatch):
    model = setup(world, monkeypatch, interpret=op("mail-draft", {"to": ADDRESS, "body": "Quero falar de marcar uma reuniao para amanha as 16horas"}))      # validate: allow english-only -- the Portuguese line under test
    out = phone(world, "Faça um rascunho de email para joana.silva@clinica.example. Quero falar de marcar uma reuniao para amanha as 16horas")      # validate: allow english-only -- the Portuguese line under test
    old, sha = opened(world, out)
    assert check(world, old, sha, INSTRUCTION) == "mail"
    got = revise(world, old, sha, INSTRUCTION)
    assert got["resend"] not in (None, old) and status(world, old) != "open"
    item = ops.pending(world["path"], got["resend"])
    assert "Christopher Gonçalves" in item["body"] and item["payload_sha256"] != sha      # validate: allow english-only -- the stand-in model's answer
    reply = ops.mail_reply(world["path"], "google", "inbox#1", "Obrigado, até quinta.")      # validate: allow english-only -- the Portuguese text under test
    number = reply["pending"]
    cs = ops.pending(world["path"], number)["payload_sha256"]
    assert check(world, number, cs, "Ajuste o texto para dizer até sexta") == "sentence" and check(world, number, cs, "e a reunião de quinta?") is None      # validate: allow english-only -- the Portuguese lines under test
    assert revise(world, number, cs, "Ajuste o texto para dizer até sexta")["say"] == "Para mudar este card, rejeite e peça de novo."      # validate: allow english-only -- the Portuguese sentence under test
    assert status(world, number) == "open"


def test_nothing_of_the_instruction_the_subject_or_the_body_is_logged_or_printed(world, clock, monkeypatch, caplog, capsys):
    _, old, sha = live_card(world, monkeypatch, revise=RuntimeError("boom " + ZEBRA))
    caplog.set_level(logging.DEBUG)
    revise(world, old, sha, INSTRUCTION + " " + ZEBRA)
    out = capsys.readouterr()
    assert ZEBRA not in caplog.text and ZEBRA not in out.out + out.err and "Christopher" not in caplog.text + out.out + out.err
