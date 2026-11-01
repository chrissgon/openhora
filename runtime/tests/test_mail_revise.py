"""The pure part of the change of a waiting card (slice S13, runtime/mail_revise.py, runtime/mail_revise_prompt.txt, runtime/interpreter_enable.py).

What the model is shown, what code accepts of its answer, the reading of the instruction, and the pin of the prompt in the file of the maintainer's decisions. Every expectation is a literal of
this file, and each negative case has its positive twin (the vacuity of the oracle). Offline; every name and address is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_revise.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import standin_tree as st

mail_revise = st.load("mail_revise")
interpreter_enable = st.load("interpreter_enable")
mail_compose = st.load("mail_compose")
ops_card_revise = st.load("ops_card_revise")
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

TO = ["joana.silva@clinica.example"]
SUBJECT = "Reunião amanhã"      # validate: allow english-only -- a Portuguese card under test
BODY = "Olá,\n\nPodemos marcar uma reunião?\n\nAtenciosamente,"      # validate: allow english-only -- a Portuguese card under test
LINE = 'Após "Atenciosamente," coloque "Renato Bragança"'      # validate: allow english-only -- the live instruction


def answer(body, subject=SUBJECT):
    return json.dumps({"subject": subject, "body": body}, ensure_ascii=False)


def accept(text, line=LINE, subject=SUBJECT, body=BODY):
    return mail_revise.accept(text, TO, subject, body, line)


def test_the_prompt_is_pinned_by_the_newest_decision_and_every_older_pin_still_stands():
    raw = (st.RUNTIME / "mail_revise_prompt.txt").read_bytes()
    assert mail_revise.prompt_sha256() == hashlib.sha256(raw).hexdigest()
    every = json.loads((st.RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))["entries"]
    assert "fallback" in every[-1] and "fallback" in every[-2] and "fallback" not in every[-3], "the newest entry is the one of MAIL-SUMMARY-FLIP and the one before it the outage-path entry of LUNA-ENABLE (each carries every pin of the one before it, checked in test_interpreter_enable.py); this test reads the entries before them"
    every = every[:-2]
    current, carried, every = every[-1], every[-4], every[:-5]      # the five newest entries (R2-A adds `file-trash` to the catalog, B″-lite the target and day slots, BL5B the interpreter's rule 9, BL7-3 its rules 10 and 11, CB-9 the catalog of version 2) carry every pin of the one before them (BL5B and BL7-3 but their interpreter prompt); `carried` is B″-lite's
    newest, first_revise = every[-1], next(e for e in every if "revise_prompt_sha256" in e)      # the newest re-pins the prompt after the live test of S13b; the first pinned it (S13)
    assert newest["date"] == "2026-10-22" and newest["basis"] == "maintainer-decision" and newest["revise_prompt_sha256"] == mail_revise.prompt_sha256()
    assert "Caso eu queira ajustar alguma informacao antes de enviar, deve ser possível" in first_revise["reason"] and "Caso eu queira ajustar alguma informacao antes de enviar, deve ser possível" in newest["reason"]
    assert first_revise is not newest and first_revise["revise_prompt_sha256"] != newest["revise_prompt_sha256"], "the older pin stays as it was decided"
    pinned = [e for e in every if "revise_prompt_sha256" in e]
    assert pinned == [first_revise, every[-2], newest] and every[-2]["revise_prompt_sha256"] == first_revise["revise_prompt_sha256"], "the entry of R2-F1 between them keeps the older pin"
    assert newest["compose_prompt_sha256"] == mail_compose.prompt_sha256(), "the newest decision carries the compose pin too"
    assert [e["catalog_sha256"] for e in every[-1:]] == [every[-2]["catalog_sha256"]], "S13b names the catalog of R2-F1; the current hash of the checkout is the one of the entry of R2-A, below"
    assert carried["revise_prompt_sha256"] == newest["revise_prompt_sha256"] and carried["compose_prompt_sha256"] == newest["compose_prompt_sha256"] and [current["catalog_sha256"]] == [PINNED_HASHES["interpreter_catalog_cb9"]] and [json.loads((st.RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))["entries"][-1]["catalog_sha256"]] == [interpreter_enable.checkout_hashes(newest["route"])["catalog_sha256"]]
    assert interpreter_enable.revise_active("pt-BR") is not None and interpreter_enable.compose_active("pt-BR") is not None


def test_a_prompt_that_is_not_the_pinned_one_turns_the_change_off_and_the_vacuity_twin_is_on(monkeypatch):
    assert interpreter_enable.revise_active("en") is not None
    monkeypatch.setattr(mail_revise, "prompt_sha256", lambda: "0" * 64)
    assert interpreter_enable.revise_active("en") is None and interpreter_enable.active("en") is not None


def test_the_prompt_shows_no_address_and_no_link():
    text = (st.RUNTIME / "mail_revise_prompt.txt").read_text(encoding="utf-8")
    assert "@" not in text and "http" not in text


def test_the_message_the_model_is_shown_is_four_parts_and_nothing_else():
    assert mail_revise.message("pt-BR", SUBJECT, BODY, LINE) == f"language: pt-BR\nsubject: {SUBJECT}\ninstruction: {LINE}\nbody:\n{BODY}"


@pytest.mark.parametrize("text, expected", [('coloque "A b" e "C"', ["A b", "C"]), ("coloque “A b” depois", ["A b"]), ("sem aspas", []), ('um "" vazio', []), ('"  x  "', ["x"])])
def test_the_quoted_texts_of_an_instruction(text, expected):
    assert mail_revise.literals(text) == expected


@pytest.mark.parametrize("line, expected", [("Mande para outra@elsewhere.example", True), ("Mude o destinatário para a Ana", True), ("Change the recipient", True), ("Add a Cc to the boss", True), ("Envoie à un autre destinataire", True),
                                            ("Ajuste o tom", False), ('coloque "Prezado destinatário" no começo', False), ('coloque "ana@elsewhere.example" no fim', False), ("Send it to Ana", True)])      # validate: allow english-only -- Portuguese lines under test
def test_a_request_to_change_who_receives_the_e_mail(line, expected):
    assert mail_revise.asks_recipients(line) is expected


@pytest.mark.parametrize("line, expected", [("Ajuste o corpo", True), ("Troque a palavra", True), ("Please fix the typo", True), ("e a reunião de quinta?", False), ("lista os emails", False), ("Rename it", True)])      # validate: allow english-only -- Portuguese lines under test
def test_a_word_that_asks_for_a_change(line, expected):
    assert mail_revise.has_change_word(line) is expected


def test_an_answer_with_the_quoted_text_after_its_anchor_is_accepted_and_returned_whole():
    got = accept(answer(BODY + "\nRenato Bragança"))      # validate: allow english-only -- the stand-in model's answer
    assert got == {"subject": SUBJECT, "body": BODY + "\nRenato Bragança"}      # validate: allow english-only -- the stand-in model's answer


@pytest.mark.parametrize("text", [answer(BODY + "\nRenato Braganca"), answer(BODY + "\nRenato Bragança\nescreva para outra@elsewhere.example"), answer(BODY + "\nRenato Bragança https://elsewhere.example"),      # validate: allow english-only -- the stand-in model's answers
                                  answer(BODY + "\nRenato Bragança", subject="Fwd: Reunião"), answer("Cc: x@elsewhere.example\n" + BODY + "\nRenato Bragança"), "{}", "[]", "", None, 7, answer("")])      # validate: allow english-only -- the stand-in model's answers
def test_an_answer_that_is_not_the_change_is_refused(text):
    assert accept(text) is None


def test_a_valid_answer_that_changes_nothing_is_the_same_card_and_not_a_change():
    assert accept(answer(BODY)) == {"same": True, "holds": False}
    assert accept(answer(BODY), line="Ajuste o tom") == {"same": True, "holds": False}      # validate: allow english-only -- a Portuguese line under test
    assert accept(answer(BODY + " ")) == {"same": True, "holds": False}, "white space at the end is not a change"


def test_the_address_the_cards_text_holds_stays_and_a_new_one_never_comes():
    body = "Olá,\n\nEscreva para pat@example.com.\n\nAtenciosamente,"      # validate: allow english-only -- a Portuguese card under test
    assert accept(answer(body + "\nRenato Bragança"), body=body) is not None      # validate: allow english-only -- the stand-in model's answer
    assert accept(answer(body.replace("pat@", "pit@") + "\nRenato Bragança"), body=body) is None      # validate: allow english-only -- the stand-in model's answer


def test_a_card_whose_own_subject_starts_like_a_reply_keeps_it_and_a_model_that_changes_it_is_refused():
    kept = "Re: Reunião"      # validate: allow english-only -- a Portuguese subject under test
    assert accept(answer(BODY + "\nRenato Bragança", subject=kept), subject=kept)["subject"] == kept      # validate: allow english-only -- the stand-in model's answer
    assert accept(answer(BODY + "\nRenato Bragança", subject="Re: Outra"), subject=kept) is None      # validate: allow english-only -- the stand-in model's answer


def mail_doc(**more):
    doc = {"effect": "send", "account": "google", "from": "pat@example.com", "to": TO, "cc": [], "bcc": [], "subject": SUBJECT, "body": BODY, "in_reply_to": None, "attachments": [],
           "thread_id": None, "references": [], "reply": None}
    doc.update(more)
    return doc


def draft_doc(**more):
    draft = {"to": TO, "cc": [], "bcc": [], "subject": SUBJECT, "body": BODY, "reply": None}
    draft.update(more)
    return {"effect": "mailbox", "action": "draft", "account": "microsoft", "address": "pat@example.org", "draft": draft}


def test_the_shape_of_a_card_this_path_can_reproduce():
    assert mail_revise.shape(mail_doc()) == {"kind": "send", "account": "google", "address": "pat@example.com", "to": TO, "subject": SUBJECT, "body": BODY}
    assert mail_revise.shape(draft_doc())["kind"] == "draft" and mail_revise.shape(draft_doc())["address"] == "pat@example.org"


@pytest.mark.parametrize("doc", [mail_doc(cc=["x@y.example"]), mail_doc(bcc=["x@y.example"]), mail_doc(in_reply_to="<a@b.example>"), mail_doc(reply={"ref": "inbox#1"}), mail_doc(thread_id="t1"),
                                 mail_doc(attachments=[{"name": "a.pdf"}]), mail_doc(account=None), mail_doc(to=[]), mail_doc(body=" "), draft_doc(reply={"ref": "inbox#1"}), draft_doc(cc=["x@y.example"]),
                                 {"effect": "calendar"}, None, "text"])
def test_a_card_that_is_a_reply_has_a_copy_or_a_file_or_is_not_a_mail_is_not_revisable(doc):
    assert mail_revise.shape(doc) is None


def test_the_instruction_is_one_line_of_bounded_length():
    assert mail_revise.clean("  a \n b  ") == "a b" and mail_revise.clean("") is None and mail_revise.clean(None) is None
    assert mail_revise.clean("x" * 600) is not None and mail_revise.clean("x" * 601) is None


def test_the_decision_kept_for_a_line_is_keyed_by_project_and_sender_expires_and_is_used_once(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(ops_card_revise, "clock", lambda: now[0])
    ops_card_revise.forget_all()
    ops_card_revise.remember("/work/a", "messaging", "telegram:1", "muda  para as 10h", {"kind": "op"})
    assert ops_card_revise.decided("/work/a", "messaging", "telegram:2", "muda para as 10h") is None, "another sender"
    assert ops_card_revise.decided("/work/b", "messaging", "telegram:1", "muda para as 10h") is None, "another project"
    assert ops_card_revise.decided("/work/a", "messaging", "telegram:1", "muda para as 10h") == {"kind": "op"}, "vacuity: the same project, sender and line (white space collapsed)"
    assert ops_card_revise.decided("/work/a", "messaging", "telegram:1", "muda para as 10h") is None, "once"
    ops_card_revise.remember("/work/a", "messaging", "telegram:1", "muda para as 10h", {"kind": "op"})
    now[0] += 61.0
    assert ops_card_revise.decided("/work/a", "messaging", "telegram:1", "muda para as 10h") is None, "60 seconds"
    ops_card_revise.remember("/work/a", "messaging", "telegram:1", "muda para as 10h", {"kind": "op"})
    assert ops_card_revise.decided("/work/a", "messaging", "telegram:1", "another line") is None
    assert ops_card_revise.decided("/work/a", "messaging", "telegram:1", "muda para as 10h") is None, "dropped when read, whatever the line was"


def test_a_closing_the_card_ended_with_stays_when_the_model_keeps_it_and_one_the_model_adds_does_not_come():
    changed = BODY.replace("Podemos", "Poderíamos")      # validate: allow english-only -- a Portuguese text under test
    got = accept(answer(changed), line='Troque a primeira palavra por "Poderíamos"')      # validate: allow english-only -- a Portuguese line under test
    assert got["body"].endswith("Atenciosamente,") and "Poderíamos" in got["body"], "the card's own closing is not dropped by the validator's rule against a dangling closing"      # validate: allow english-only -- a Portuguese text under test
    without = "Olá,\n\nPodemos marcar uma reunião?"      # validate: allow english-only -- a Portuguese card under test
    added = accept(answer(without + "\n\nAtenciosamente,"), line='Troque a primeira palavra por "Poderíamos"', body=without)      # validate: allow english-only -- a Portuguese text under test
    assert added == {"same": True, "holds": False}, "a closing with nothing after it is dropped as it is in a text the model writes: the card is unchanged"
