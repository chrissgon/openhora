#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The corpus of the entry replay (package S41-1), and the golden recorded from it.

`entry_corpus.jsonl` has one scenario per line: {"id", "channel", "platform", "sender", "prestate", "text", "reply_to", "forwarded", "kind", "action"}. This script writes it, the same way
every time (nothing is random), from three sources:

  1. the CLAIMERS table below: for every claimer of CLAIMER_NAMES (runtime/tests/entry_kit.py), at least five lines it takes and five near-misses that must go elsewhere, in pt-BR and
     en where the claimer reads words, under the pre-states where it applies. A scenario that two claimers both want is written once;
  2. the GUARDS table: the lines of the guard tests of limits L64 and L65 (test_messaging_card_words.py, test_messaging_plan_confirm.py, test_messaging_two_open.py,
     test_messaging_research_brake.py, test_messaging_card_revise.py), the lines and the states, not the test code;
  3. a deterministic sample of the corpora of today's code claimers: every SAMPLE_EVERY-th line (the first line taken rotating with the language, so that the languages do not all
     start at the same line) of runtime/tests/natural_corpus.jsonl, natural_writes_corpus.jsonl, natural_writes_mail_corpus.jsonl, evals/interpreter/dev-long-v2.jsonl and
     ix-test-v1.jsonl, each in the state `none` on messaging/buttons/owner, plus PAGE_LINES of them on the page and PAGE_LINES on the terminal.

`WB_FULL_FUZZ=1` (or `--full`) takes every line of the sampled corpora instead of one in SAMPLE_EVERY.

The golden, `entry_golden.jsonl`, is the outcome of every scenario on the tree as it was when the golden was recorded: a header line {"header": true, "commit", "corpus_sha256", "count",
"kit"} and then {"id", "outcome"} for each scenario. It is recorded ONCE, on the unchanged tree, by `--record`, which runs the replay in record mode (the world needs the fixtures of pytest):

  uv run --with pytest==9.1.1 --with pytest-xdist==3.8.0 python3 runtime/tests/entry_corpus_build.py --record

A later package never records it again: a difference is the finding. A change of the golden is a reviewed decision (runtime/README.md, "The entry replay").

THE BASE IS CLOSED (HOT-1; SPEC-HOTSPOTS 4.1). `entry_corpus.jsonl`, `entry_golden.jsonl` (its header included) and the tables of this script take no new scenario. A package that adds scenarios writes
`runtime/tests/entry_ext/<id>.scenarios.jsonl` (the corpus keys in the corpus order, every id starting with `<id>.`, an optional `model_text` for the stand-in model's answer to the scenario's
text) and records `entry_ext/<id>.golden.jsonl` with `--record-package <id>`; the replay reads the base and every package. Two packages conflict only on a row they both edit.

  python3 runtime/tests/entry_corpus_build.py            writes entry_corpus.jsonl
  python3 runtime/tests/entry_corpus_build.py --stats    the number of scenarios by channel, claimer and source
  uv run --with pytest==9.1.1 --with pytest-xdist==3.8.0 python3 runtime/tests/entry_corpus_build.py --record-package <id>    records entry_ext/<id>.golden.jsonl from entry_ext/<id>.scenarios.jsonl
  python3 runtime/tests/entry_corpus_build.py --record-added    refuses: the base golden is closed (use --record-package)
  uv run --with pytest==9.1.1 python3 runtime/tests/entry_corpus_build.py --check    fails when the committed corpus is not what this script writes, a scenario is not well formed, or a file of entry_ext/ has a problem
  uv run --with pytest==9.1.1 --with pytest-xdist==3.8.0 python3 runtime/tests/entry_corpus_build.py --record    records the golden

Writing the corpus needs only the standard library; `--check` imports the kit (the vocabulary of a scenario) and `--record` starts pytest, which the runtime's test fixtures need. Every name, address and sender is invented; the lines of the sampled corpora are the fictional ones the repository holds.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CORPUS_FILE = HERE / "entry_corpus.jsonl"
GOLDEN_FILE = HERE / "entry_golden.jsonl"
SAMPLE_EVERY = 7
PAGE_LINES = 30
SOURCES = (("natural_corpus", HERE / "natural_corpus.jsonl", "text", "language"), ("natural_writes", HERE / "natural_writes_corpus.jsonl", "line", "lang"),
           ("natural_writes_mail", HERE / "natural_writes_mail_corpus.jsonl", "line", "lang"), ("dev_long", REPO / "evals" / "interpreter" / "dev-long-v2.jsonl", "line", "lang"),
           ("ix_test", REPO / "evals" / "interpreter" / "ix-test-v1.jsonl", "line", "lang"))


def S(text, prestate="none", channel="messaging", sender="owner", platform="buttons", reply_to=None, forwarded=False, kind="text", action=None) -> dict:
    """One scenario without its id: the owner on a Telegram-like app, in the pre-state `none`, typing `text`."""
    return {"channel": channel, "platform": platform, "sender": sender, "prestate": prestate, "text": text, "reply_to": reply_to, "forwarded": forwarded, "kind": kind, "action": action}


def P(text, prestate="none", channel="page"):
    """A line typed on the page (or the terminal): no platform, no sender."""
    return S(text, prestate=prestate, channel=channel)


def O(text, sender="reader"):
    """A listed sender's plain line given straight to the operations layer (`ops.say` on the messaging channel), with no bridge before it."""
    return S(text, channel="ops", sender=sender)


def many(prestate, lines, **more):
    return [S(line, prestate, **more) for line in lines]


YES = ["sim", "Sim!", "aprovo", "pode marcar", "ok", "yes", "approve", "go ahead", "manda ver"]
NO = ["não", "Nao", "rejeito", "cancela", "deixa", "no", "reject", "cancel"]
STATES = ("none", "card_last", "plan_last", "plan_not_last", "two_cards")
DELETES = ["apague o arquivo contrato.pdf", "delete the file contract.pdf", "deleta o documento notas.txt", "remove o arquivo plano.docx do drive", "please delete my file budget.xlsx"]
REMINDERS_PT_EN = ["me lembra de ligar para o dentista amanhã às 9h", "lembrete: pagar o aluguel sexta 8h", "remind me to call the bank tomorrow at 9am", "remind me at 15:00 to stretch",
                   "me avisa segunda de manhã às 8 pra renovar o seguro do carro"]
SAY_NATURAL = ["desfaz", "undo", "cancela o 3", "cancela #3", "cancel #3", "anota: ligar pro dentista", "note: buy milk"]      # reminder forms of a sender who may not make reminders: a plain line
WRITES = ["coloca na agenda troca de pneus depois de amanhã 9h", "muda o título do evento 2 para ensaio da banda", "desmarca o evento 7", "add to the calendar dinner with the cousins Sunday at 3pm",
          "cancel meeting 7 on my outlook", "marca na agenda dentista segunda 9h30"]
WORK_LINES = ["escreva o post de lançamento", "create a document about the product launch", "cria um documento sobre o lançamento do produto", "write a poem about the sea"]
TIER_1 = ["what files do you have?", "quais arquivos você tem?", "pendências", "what do I need to approve?", "list the skills", "quais agentes", "show costs", "lista as pendencias", "list flows"]
STATES_Q = ["how are we doing?", "como estamos?", "status", "o que falta?", "what waits for me?"]
INTERPRETED = ["quick status check pls", "e aí, como anda o projeto", "tem alguma coisa esperando eu decidir?", "do i have any reminders set", "which skills do we have available rn",
               "tenho algum lembrete marcado", "how much have i spent so far?"]
PLAIN = ["Which market first?", "tell me a joke", "qual a capital da França?", "preciso organizar a visita da Maria na clinica Linden", "explain how a loan works"]
CLOSED_FORMS = ["aprova o pedido 7", "approve request 7", "cancela o pedido 3", "cancel request 3", "rejeite a pergunta 25"]
ANSWERS_ROUTER = ["um evento", "sim, um evento no google", "o evento"]
SLASH = ["/status", "/costs", "/ask what is in the lease?", "/new", "/version"]

# claimer -> {"take": [scenarios it takes], "near": [near-misses that must go elsewhere]}. The check of the replay reads the golden: every `take` has the claimer in its trace, no `near`
# does. Where a name appears in both lists of two claimers, the scenario is written once.
CLAIMERS = {
    "drop-unlisted": {
        "take": many("none", ["oi", "sim", "/pending", "aprova o 1", "what files do you have?"], sender="unlisted") + many("config_unaccepted", ["oi", "sim"]) + [S("oi", sender="group")],
        "near": many("none", ["oi", "sim", "/pending", "aprova o 1", "what files do you have?"], sender="reader")},
    "drop-invalid-attachments": {
        "take": [S(None, p, kind="attachment", action="invalid") for p in ("none", "card_last", "plan_last", "attachment_held")] + [S(None, kind="attachment", action="invalid", platform="email")],
        "near": [S(None, p, kind="attachment") for p in ("none", "card_last")] + many("none", ["oi", "sim"]) + [S(None, "plan_last", kind="attachment")]},
    "ignore": {
        "take": many("none", ["", "   ", None, "\n", "\t "]) + many("card_last", [""]),
        "near": many("none", ["oi", ".", "?", "/", "1"])},
    "forwarded-refusal": {
        "take": [S("sim", "card_last", forwarded=True), S("aprova", "card_last", forwarded=True), S("remind me at 15:00", forwarded=True), S("/approve 1", "card_last", forwarded=True),
                 S("não", "plan_last", forwarded=True), S("pare", "research_running", forwarded=True), S("oi", forwarded=True), S("lembra de ligar amanhã", forwarded=True)],
        "near": [S("sim", "card_last"), S("aprova", "card_last"), S("remind me at 15:00"), S("não", "plan_last"), S("pare", "research_running"), S("oi")]},
    "reply-to-card": {
        "take": [S(t, "card_last", reply_to="card") for t in ("me lembra de ligar amanhã 9h", "remind me to call tomorrow at 9am", "lembrete: pagar o aluguel sexta 8h", "remind me at 15:00 to stretch",
                                                              "me avisa segunda às 8 pra renovar o seguro")],
        "near": many("none", ["me lembra de ligar amanhã 9h", "remind me to call tomorrow at 9am"]) + [S("obrigado", "card_last", reply_to="card"), S("thanks", "card_last", reply_to="card"),
                                                                                                        S("oi", "none", reply_to="card")]},
    "reminder-draft-answer": {
        "take": many("reminder_draft", ["amanhã 9h", "9h", "hoje às 18h", "tomorrow 3pm", "sexta 10h"]),
        "near": many("none", ["amanhã 9h", "tomorrow 3pm"]) + many("reminder_draft", ["/pending", "what files do you have?"]) + [S("9h", "plan_last")]},
    "reminder-expired-yes": {
        "take": many("reminder_expired", ["sim", "yes", "ok", "claro", "pode"]),
        "near": many("reminder_expired", ["oi", "bom dia", "/pending"]) + many("none", ["sim"]) + many("reminder_draft", ["sim"])},
    "write-draft-answer": {
        "take": many("write_draft_title", ["Dentista da Júlia", "Team standup", "Dentist", "Aula de violão", "oi"]),
        "near": many("none", ["Dentista da Júlia", "Team standup"]) + many("write_draft_title", ["/pending", "what files do you have?", "Reunião com o time"])},
    "plan-confirm-word": {
        "take": many("plan_last", ["sim", "Sim!", "ok", "yes", "não", "no", "Nao", "claro"]),
        "near": many("plan_not_last", ["sim", "não"]) + many("none", ["sim"]) + many("plan_last", ["sim, mas amanhã", "nao, de amanha", "aprovo"]) + [S("sim", "plan_last", sender="asker")]},
    "card-word": {
        "take": many("card_last", YES) + many("card_last", NO) + many("two_cards", ["sim", "aprova todos", "não"]) + many("card_list_shown", ["aprova 2", "approve 1", "reject 2", "aprovo o 2"]) +
                many("plan_then_card", ["sim", "yes"]) + many("research_and_card", ["não"]),
        "near": many("card_last", ["sim, mas só amanhã", "ok vou ver", "aprovo o plano inteiro", "pode marcar o dentista"]) + many("plan_last", ["sim"]) + many("none", ["sim"]) +
                many("card_last", ["muda para as 10h"])},
    "research-stop": {
        "take": many("research_running", ["pare", "stop", "para", "cancela", "não", "chega", "never mind", "no"]),
        "near": many("research_running", ["oi", "pare a tarefa 3 e depois o resto", "/pare", "pare agora"]) + many("card_last", ["pare"]) + many("none", ["stop", "pare"])},
    "card-revise": {
        "take": many("card_last", ["muda para as 10h", "troca o título para Dentista", "change the time to 11am", "adia para sexta", "move it to 4pm"]),
        "near": many("none", ["muda para as 10h"]) + many("plan_last", ["muda para as 10h"]) + many("card_last", ["muda para as 10h"], sender="reader") +
                many("card_last", ["muda para as 10h"], forwarded=True) + many("card_last", ["muda para as 10h"], platform="email")},
    "project-switch": {
        "take": many("none", ["muda para o projeto northwind-shop", "qual projeto estou usando?", "which project am I using", "switch to project northwind-shop", "troca de projeto"]),
        "near": many("none", ["muda para as 10h", "project plan for tomorrow", "qual a capital da França?", "oi", "oi tudo bem?"])},
    "help-in-words": {
        "take": many("none", ["help", "ajuda", "what can you do", "o que você sabe fazer", "what commands do you have"], sender="reader"),
        "near": many("none", ["help", "ajuda", "what can you do"]) + many("none", ["help", "ajuda"], sender="asker")},
    "attachment-line": {
        "take": many("attachment_held", ["descarta", "adiciona ao projeto", "discard", "add to the project", "descarta esse arquivo", "salva", "save it"]),
        "near": many("none", ["descarta", "adiciona ao projeto", "discard"]) + many("attachment_held", ["oi", "sim", "add to project", "descarte esse arquivo"])},
    "attachment-arrived": {
"take": [S(None, p, kind="attachment") for p in ("none", "card_last", "plan_last", "attachment_held")] + [S("contrato do aluguel", kind="attachment"), S("save this please", "none", kind="attachment"),
                                                                                                                   S(None, kind="attachment", forwarded=True)],
        "near": many("none", ["oi", "contrato do aluguel"]) + many("attachment_held", ["descarta"]) + [S("oi", "card_last"), S("/pending", "plan_last")]},
    "attachment-typed": {
        "take": many("attachment_held", ["/add 1", "/discard 1"]) + many("none", ["/add 7", "/discard 7", "/add@bot 1"]),
        "near": many("none", ["/add", "/add x", "/discard", "adiciona ao projeto"]) + many("attachment_held", ["/approve 1", "/pending"])},
    "remind-typed": {
        "take": many("none", ["/remind 15:00 Call the dentist", "/remind 2026-10-20 09:30 pay rent", "/remind in 2h stretch", "/remind 9:30 stand up", "/remind@bot 18:00 dinner"]),
        "near": many("none", ["/remind", "/remind buy milk", "/remind 13hrs oil change tomorrow", "remind me at 15:00", "/remind 15:00"])},
    "write-form": {
        "take": many("none", WRITES[:5]) + [S(WRITES[5])],
        "near": many("none", WORK_LINES[:2]) + many("none", ["oi", "me lembra de ligar amanhã 9h", "what files do you have?"])},
    "reminder-form": {
        "take": many("none", REMINDERS_PT_EN) + many("none", ["/remind 13hrs oil change tomorrow", "meus lembretes"]),
        "near": many("none", ["Which market first?", "oi", "/reminders", "/remind 15:00 Call the dentist", "write a poem about the sea"])},
    "say-natural": {
        "take": many("none", SAY_NATURAL, sender="asker"),
        "near": many("none", ["anota: ligar pro dentista", "note: buy milk", "me lembra de ligar amanhã 9h", "/reminders", "oi"], sender="owner")},
    "reminders-list": {
        "take": many("none", ["/reminders", "/REMINDERS", "/reminders@bot", "/reminders now", "/reminders\n"]),
        "near": many("none", ["/reminder", "reminders", "meus lembretes", "/remind", "/remindersx"])},
    "forget-typed": {
        "take": many("none", ["/forget 3", "/forget 1", "/forget 99", "/forget@bot 2", "/FORGET 4"]),
        "near": many("none", ["/forget", "/forget x", "/forget 3x", "/forget -1", "cancela o lembrete 3"])},
    "tap": {
        "take": [S(None, "plan_last", kind="action", action="yes"), S(None, "plan_last", kind="action", action="no"), S(None, "card_last", kind="action", action="approve"),
                 S(None, "card_last", kind="action", action="reject"), S(None, "two_cards", kind="action", action="approve"), S(None, "none", kind="action", action="yes"),
                 S(None, "card_last", kind="action", action="release"), S(None, "plan_last", kind="action", action="approve", platform="email")],
        "near": many("plan_last", ["sim", "não"]) + many("card_last", ["sim", "não"]) + many("none", ["yes"])},
    "usage": {
        "take": many("none", ["/approve", "/reject", "/release", "/answer", "/add", "/discard", "/approve x", "/answer 3"]),
        "near": many("none", ["/approve 3", "/reject 3", "/release 3", "/answer 3 yes", "/add 1"])},
    "help-typed": {
        "take": many("none", ["/help", "/start", "/HELP", "/help@bot", "/start now"]),
        "near": many("none", ["help", "ajuda", "/helpme", "oi", "start"])},
    "project-typed": {
        "take": many("none", ["/project", "/project northwind-shop", "/project other", "/PROJECT", "/project@bot northwind-shop"]),
        "near": many("none", ["project", "muda para o projeto northwind-shop", "/projects", "oi", "qual projeto estou usando?"])},
    "pending-typed": {
        "take": many("none", ["/pending", "/pending now", "/PENDING", "/pending@bot", "/pending 3"]),
        "near": many("none", ["pendências", "/status", "what do I need to approve?", "oi", "/pendingx"])},
    "decision-typed": {
        "take": many("card_last", ["/approve 7", "/reject 7 no", "/release 3", "/answer 2 yes"]) + many("none", ["/approve 7", "/reject 7"]) + many("card_last", ["/approve 1"], platform="email"),
        "near": many("none", ["/approve", "/reject", "/answer 3", "aprova o pedido 7", "aprovo"])},
    "reply": {
        "take": [S(t, "none", reply_to="nothing") for t in ("ok obrigado", "thanks", "valeu", "can you resend that?", "entendi")] + [S("mostra minha agenda", "plan_last", reply_to="plan"),
                                                                                                                                 S("um evento", "router_question", reply_to="question")],
        "near": many("card_last", ["ok obrigado", "thanks"]) + many("none", ["oi"]) + many("card_last", ["sim", "muda para as 10h"], reply_to="card")},
    "say": {
        "take": many("none", PLAIN) + many("plan_last", ["oi"]) + many("research_running", ["oi"]),
        "near": many("none", ["/pending", "/reminders"]) + many("plan_last", ["sim"]) + many("none", [""]) + many("none", ["oi"], forwarded=True)},
    "delete-refusal-before-queue": {
        "take": many("none", DELETES, sender="asker"),
        "near": many("none", ["oi", "qual a capital da França?", "apague o evento de amanhã"], sender="asker") + many("none", DELETES[:2], sender="owner")},
    "closed-form-without-slot": {
        "take": many("none", CLOSED_FORMS),
        "near": many("none", TIER_1[:2]) + many("none", ["oi", "Which market first?"]) + many("none", ["/approve 7"])},
    "say-queue": {
        "take": many("none", PLAIN) + many("plan_last", ["tell me a joke"]),
        "near": many("none", CLOSED_FORMS[:3]) + many("none", ["/pending", "/approve"])},
    "confirmed-plan": {
        "take": many("plan_last", ["sim", "yes", "claro", "ok", "Sim!"]) + [S(None, "plan_last", kind="action", action="yes")],
        "near": many("plan_not_last", ["sim", "yes"]) + many("none", ["sim"]) + many("plan_last", ["não", "aprovo"])},
    "command": {
        "take": many("none", SLASH) + [P(t) for t in ("/status", "/costs", "/version")] + [P(t, channel="terminal") for t in ("/status", "/version")],
        "near": many("none", ["/pending", "/reminders", "/approve 3"]) + [P("status"), P("how are we doing?")]},
    "greeting": {
        "take": many("none", ["oi", "olá", "hello", "bom dia", "hi"]) + many("none", ["oi", "hello"], sender="asker"),
        "near": many("none", ["oi", "hello"], sender="reader") + many("none", ["oi, preciso de ajuda com os impostos", "hello, what is the capital of France?", "bom dia, qual a capital da França?"])},
    "plan-bare-word": {
        "take": many("plan_not_last", ["sim", "não", "yes", "no", "ok"]),
        "near": many("plan_last", ["sim", "não", "ok"]) + many("none", ["sim", "não"])},
    "delete-file": {
        "take": many("none", DELETES),
        "near": [P(t) for t in DELETES[:3]] + many("none", DELETES[:2], sender="asker")},
    "router-question": {
        "take": many("router_question", ANSWERS_ROUTER) + [P(t, "router_question") for t in ("um evento", "the Linden clinic")] + [P("um evento", "router_question", channel="terminal")],
        "near": many("router_question", ["what files do you have?", "Which market first?"]) + many("none", ["um evento"]) + [P("um evento"), P("what files do you have?", "router_question")]},
    "state-question": {
        "take": many("none", STATES_Q) + [P("how are we doing?"), P("como estamos?", channel="terminal")],
        "near": many("none", ["how are we doing with the new login, delete the old plan", "oi", "o que falta fazer no projeto, apague o plano antigo"]) + [P("oi"), P("status, then delete the old plan")]},
    "draft-answer": {
        "take": many("write_draft_title", ["Dentista da Júlia", "Team standup", "Dentist"]) + [P(t, "write_draft_title") for t in ("Dentista da Júlia", "Team standup", "Dentist")],
        "near": many("none", ["Dentista da Júlia"]) + [P("Dentista da Júlia"), P("amanhã 9h")] + [P("Reunião com o time", "write_draft_title")] + many("write_draft_title", ["/pending"])},
    "event-list-number": {
        "take": many("event_list_shown", ["o 2", "o 4", "cancela o 2", "cancela o 4", "2", "4"]),
        "near": many("none", ["o 2", "cancela o 2"]) + many("file_list_shown", ["o 2"]) + many("event_list_shown", ["cancela o evento 4", "oi"])},
    "file-list-number": {
        "take": many("file_list_shown", ["o 2", "o 1", "2", "1", "o 2."]),
        "near": many("none", ["o 2"]) + many("event_list_shown", ["o 2"]) + many("file_list_shown", ["oi", "o primeiro", "/pending"])},
    "write-form-ops": {
        "take": many("none", WRITES[:3]) + [P(t) for t in WRITES[:3]] + [P(t, channel="terminal") for t in WRITES[3:5]],
        "near": [P(t) for t in WORK_LINES[:2]] + many("none", WORK_LINES[:2]) + [P("write a poem about the sea")]},
    "tier-1-form": {
        "take": many("none", TIER_1) + [P(t) for t in TIER_1[:3]] + [P(t, channel="terminal") for t in TIER_1[3:5]],
        "near": many("none", ["oi", "qual a capital da França?", "tell me a joke"]) + [P("oi"), P("tell me a joke")]},
    "talk-refusal": {
        "take": [O(t, "reader") for t in ("oi", "tell me a joke", "qual a capital da França?", "Which market first?", "preciso organizar a visita da Maria na clinica Linden")],
        "near": [O(t, "owner") for t in ("oi", "tell me a joke")] + [O(t, "asker") for t in ("oi", "Which market first?")] + [O("what files do you have?", "reader")]},
    "interpreter": {
        "take": many("none", INTERPRETED),
        "near": [P(t) for t in INTERPRETED[:3]] + many("none", INTERPRETED[:2], sender="reader") + many("none", PLAIN[:2])},
    "planning-agent": {
        "take": many("none", PLAIN) + [P(t) for t in PLAIN[:3]] + [P(t, channel="terminal") for t in PLAIN[3:5]],
        "near": many("none", INTERPRETED[:3]) + many("none", ["oi", "/status"])},
}

# the lines of the guard tests of limits L64 and L65, with the state each is in
GUARDS = {
    "card_words": (many("card_last", ["Aprovo", "aprovo", "sim", "Sim!", "pode marcar", "pode aprovar", "ok", "yes", "approve", "approved", "go ahead", "manda ver"]) +
                   many("card_last", ["não", "Nao", "rejeito", "rejeita", "cancela", "deixa", "no", "reject", "cancel"]) +
                   many("card_last", ["pode marcar o dentista", "sim mas só amanhã", "ok vou ver", "aprovo o plano inteiro", "pode marcar amanhã às 3", "Agende corte de cabelo amanhã às 14h",
                                      "pode marcar o dentista quinta às 10h", "hello there"]) +
                   many("two_cards", ["sim", "aprova todos", "approve all", "todos não", "aprovo o 2", "pode marcar"]) +
                   many("card_list_shown", ["aprovo o 2", "aprova 2", "aprova 9", "sim", "aprova todos", "todos não", "rejeito 1"]) +
                   [S("sim", "card_last", reply_to="card"), S("sim", "card_last", reply_to="list"), S("sim", "card_last", reply_to="nothing"), S("não", "two_cards", reply_to="card"),
                    S("aprovo o 2", "two_cards", reply_to="card"), S("aprova todos", "two_cards", reply_to="card"), S("todos não", "two_cards", reply_to="card"),
                    S("sim", "card_last", sender="reader"), S("sim", "card_last", sender="asker"), S("sim", "card_last", sender="group"), S("sim", "card_last", sender="unlisted"),
                    S("sim", "card_last", forwarded=True), S("sim", "card_last", platform="email"), S("sim", "card_last", platform="email", reply_to="card"),
                    S("Aprovo", "card_last", platform="email", reply_to="card"), S("sim\n\n-- \nAna", "card_last", platform="email", reply_to="card"),
                    S("sim", "card_last", platform="email", reply_to="nothing")]),
    "plan_confirm": (many("plan_last", ["sim", "não", "nao, de amanha", "sim, mas amanhã", "mostra meus emails", "quero cancelar o pedido 3", "will it rain in Lisbon, weather in Lisbon tomorrow", "sim."]) +
                     [S("sim", "plan_last", sender="group"), S("sim", "plan_last", sender="asker"), S("sim", "plan_last", forwarded=True), S("sim", "plan_last", reply_to="plan"),
                      S("sim", "plan_not_last", reply_to="plan"), S("sim\n\n-- \nAna", "plan_last", platform="email", reply_to="plan"), S("sim", "plan_last", platform="email"),
                      S("não", "plan_last", platform="email", reply_to="plan"), S(None, "plan_last", kind="action", action="yes"), S(None, "plan_last", kind="action", action="no"),
                      S(None, "plan_last", sender="asker", kind="action", action="yes"), S(None, "plan_last", sender="group", kind="action", action="yes"),
                      S("sim", "plan_not_last"), S("não", "plan_not_last"), S("mostra minha agenda", "plan_last"), S("mostra minha agenda", "plan_not_last")]),
    "two_open": ([S("sim", "plan_last"), S("não", "plan_last"), S("sim", "plan_not_last"), S("não", "plan_not_last"), S("sim", "plan_not_last", reply_to="card"),
                  S("sim", "card_last"), S("sim", "two_cards"), S("sim", "card_last", reply_to="plan")] +
                 [S(t, "plan_then_card") for t in ("sim", "não", "aprovo", "ok")] + [S("sim", "plan_then_card", reply_to="card"), S("sim", "plan_then_card", reply_to="plan"),
                                                                                    S(None, "plan_then_card", kind="action", action="yes"), S(None, "plan_then_card", kind="action", action="approve")]),
    "research_brake": ([S(t, "research_running") for t in ("pare", "não", "stop", "cancela", "/pare", "pare a tarefa 3 e depois o resto", "oi")] +
                       [S("pare", "research_running", sender="asker"), S("pare", "research_running", sender="reader"), S("pare", "research_running", forwarded=True),
                        S("pare", "research_running", reply_to="nothing"), S("pare", "research_running", platform="email"), S("pare\n\n-- \nAna", "research_running", platform="email", reply_to="card"),
                        S("pare", "card_last"), S("não", "card_last"), S("sim", "research_running"), S("sim", "research_running", reply_to="plan"), S("pare", "none")] +
                       [S(t, "research_and_card") for t in ("não", "pare", "sim", "no", "stop")] + [S("não", "research_and_card", reply_to="card"), S("pare", "research_and_card", platform="email")]),
    "card_revise": ([S(t, "card_last") for t in ("Ajuste o corpo do email. Após \"Atenciosamente,\" coloque \"Marina Tavares\"", "Muda o texto para dizer outra coisa", "muda para as 10h",
                                                 "hello there", "what time is it in Lisbon", "lembre-me de ligar amanha as 9h", "/pending", "sim", "aprovo", "não", "pode marcar")] +
                    [S("muda para as 10h", "card_last", reply_to="card"), S("muda para as 10h", "card_last", reply_to="nothing"), S("muda para as 10h", "card_last", forwarded=True),
                     S("muda para as 10h", "card_last", sender="reader"), S("muda para as 10h", "card_last", sender="group"), S("muda para as 10h", "two_cards"),
                     S("muda para as 10h", "card_last", platform="email"), S("muda para as 10h", "plan_last")]),
}


# S41-1b: the scenarios each with TWO states live at once, and the inputs the single-state corpus did not reach. The review of S41-2 found the replay blind to a row whose effect needs two states
# at once or an uncommon input (the frame rows S41-8 reworks). Every composite holds the "sim" and the "yes" (the words every pending question reads), a line that answers one of the two
# questions, and a line that answers neither, in pt-BR and en. Recorded on the old order (c8c2594): the existing rows are not touched.
COMPOSITES = {
    "expired_and_write_draft": many("expired_and_write_draft", ["sim", "yes", "Dentista da Júlia", "Team standup", "não", "no", "/pending", "what files do you have?", "claro", "oi"]),
    "reminder_and_write_draft": many("reminder_and_write_draft", ["amanhã 9h", "tomorrow 3pm", "sim", "yes", "Dentista da Júlia", "Team standup", "/pending", "oi", "não"]),
    "reminder_and_expired": many("reminder_and_expired", ["amanhã 9h", "tomorrow 3pm", "sim", "yes", "/pending", "oi", "não", "claro"]),
    "plan_and_write_draft": many("plan_and_write_draft", ["sim", "yes", "não", "no", "Dentista da Júlia", "Team standup", "/pending", "mostra minha agenda", "ok"]),
    "plan_and_file_held": many("plan_and_file_held", ["sim", "yes", "não", "descarta", "adiciona ao projeto", "discard", "add to the project", "/pending", "oi"]) +
                          [S(t, "plan_and_file_held", kind="attachment") for t in ("sim", "yes", "descarta", None)],
    "plan_last_and_a_captioned_file": [S(t, "plan_last", kind="attachment") for t in ("sim", "yes", "não", "descarta", "ok", "no")] + [S("sim", "plan_not_last", kind="attachment")],
}
EDGES = {
    "reply_to_a_question_of_another_project": [S(t, "question_of_other_project", reply_to="question") for t in ("um evento", "o evento", "sim", "yes", "an event", "ok", "/pending")] +
                                              [S(t, "router_question", reply_to="question") for t in ("um evento", "sim")],
    "delete_from_a_sender_who_may_not_talk": many("none", DELETES, sender="reader") + many("none", ["oi", "qual a capital da França?"], sender="reader"),
    "forwarded_file_with_a_reminder_draft_open": [S(t, "reminder_draft", kind="attachment", forwarded=True) for t in (None, "sim", "yes", "amanhã 9h", "contrato do aluguel", "descarta")] +
                                                 [S(t, "reminder_draft", kind="attachment") for t in (None, "sim", "yes", "amanhã 9h", "contrato do aluguel")],
}


# S41-1c: the same method for the OPERATIONS layer (`ops_say._turn`, `ops_natural.take`). The review of S41-3 found orders and guards that no scenario reached: a router question or a write
# draft that is open when a state line or a form comes, a plan that is live (last or not) when a greeting that is also a yes comes, a sender who holds `interpret` and a read group and not
# `talk`, the shells mcp and chat, and the queue (a page line queued while a run is busy, drained by `route_queued`, a queued answer to the choice of a file for an `ask`). Each holds its
# "sim" and its "yes". Recorded on the old ops order (2fb497d).
STATE_LINES = ["progress", "status", "andamento", "how are we doing?", "o que falta?"]
GREETINGS_THAT_ARE_YES = ["beleza", "tudo bem", "oi, tudo bem?", "tudo certo", "ok, beleza"]
OPS_GROUPS = {
    "router_question_and_a_state_line": [P(t, "router_question") for t in STATE_LINES + ["sim", "yes"]] + [P(t, "router_question", channel="terminal") for t in ("status", "andamento", "sim")] +
                                        [S(t, "router_question") for t in ("progress", "status", "andamento", "sim", "yes")],
    "write_draft_and_a_state_line": [P(t, "write_draft_title") for t in STATE_LINES + ["sim", "yes"]] + [P(t, "write_draft_title", channel="terminal") for t in ("status", "andamento", "sim")] +
                                    [S(t, "write_draft_title") for t in ("progress", "andamento", "sim", "yes")],
    "write_draft_and_a_tier_1_form": [P(t, "write_draft_title") for t in TIER_1[:5] + ["sim", "yes"]] + [P(t, "write_draft_title", channel="terminal") for t in TIER_1[:3] + ["sim"]] +
                                     [S(t, "write_draft_title") for t in ("what files do you have?", "pendências", "list the skills", "sim", "yes")],
    "plan_not_last_and_a_greeting_that_is_a_yes": [S(t, "plan_not_last") for t in GREETINGS_THAT_ARE_YES + ["sim", "yes", "oi", "tudo bem?"]],
    "plan_last_and_a_greeting_that_is_a_yes": [S(t, "plan_last") for t in GREETINGS_THAT_ARE_YES + ["sim", "yes", "oi", "tudo bem?"]] + [O(t, "owner") for t in ("tudo bem", "beleza")],
    "interpreter_sender_without_talk": [S(t, sender="reader_interpret") for t in ("oi", "tell me a joke", "qual a capital da França?", "sim", "yes", "how are we doing?", "pendências", "what files do you have?")] +
                                       [O(t, "reader_interpret") for t in ("oi", "tell me a joke", "Which market first?", "sim", "yes", "how are we doing?", "status", "what files do you have?", "preciso organizar a visita da Maria na clinica Linden")],
    "mcp_and_chat_shells": [P(t, channel="mcp") for t in ("/status", "what files do you have?", "oi", "sim", "yes", "how are we doing?", "Which market first?")] +
                           [P(t, channel="chat") for t in ("/status", "oi", "sim", "what files do you have?", "Which market first?", "how are we doing?", "yes")],
    "a_page_line_queued_while_a_run_is_busy": [P(t, "route_busy") for t in ("Which market first?", "oi", "qual a capital da França?", "sim", "yes", "what files do you have?", "/status", "status")] +
                                              [P(t, "route_busy", channel="terminal") for t in ("Which market first?", "sim")] + [P(t, "route_busy", channel="chat") for t in ("Which market first?", "oi")],
    "a_queued_answer_to_the_choice_of_a_file": [P(t, "route_busy_ask_choice") for t in ("1", "2", "o 2", "sim", "yes", "oi", "what files do you have?")],
}


# --- generation ---------------------------------------------------------------------------------------------------------------------------------------


def key_of(scenario: dict) -> str:
    return json.dumps({k: v for k, v in scenario.items() if k != "id"}, sort_keys=True, ensure_ascii=False)


def read_rows(path):
    return [json.loads(raw) for raw in Path(path).read_text(encoding="utf-8").splitlines() if raw.strip()]


def sampled(rows: list, language_key: str, every: int) -> list:
    """The indexes of the lines one corpus gives: every `every`-th line of each language, the first one taken rotating with the language (the languages sorted, the n-th starts at
    line n modulo `every`), so that the languages do not all start at the same line. Deterministic."""
    languages = sorted({str(row.get(language_key) or "") for row in rows})
    seen = collections.Counter()
    chosen = []
    for index, row in enumerate(rows):
        language = str(row.get(language_key) or "")
        if seen[language] % every == languages.index(language) % every:
            chosen.append(index)
        seen[language] += 1
    return chosen


def sample_lines(full: bool) -> list:
    """[(source, index, line)] of the sampled corpora, in the order of the files."""
    out = []
    for name, path, text_key, language_key in SOURCES:
        rows = read_rows(path)
        for index in (range(len(rows)) if full else sampled(rows, language_key, SAMPLE_EVERY)):
            line = rows[index].get(text_key)
            if isinstance(line, str) and line.strip():
                out.append((name, index, line))
    return out


def generate(full: bool = False) -> tuple:
    """(scenarios, expectations): the scenarios with their ids, and [(claimer, "take" | "near", scenario id)] for the authored table. Nothing is random."""
    scenarios, by_key, expectations = [], {}, []

    def add(prefix, scenario):
        key = key_of(scenario)
        if key not in by_key:
            by_key[key] = {"id": prefix, **scenario}
            scenarios.append(by_key[key])
        return by_key[key]["id"]
    for claimer, rows in CLAIMERS.items():
        for role in ("take", "near"):
            for n, scenario in enumerate(rows[role], 1):
                expectations.append((claimer, role, add(f"{claimer}.{role}.{n:02d}", scenario)))
    for group, rows in GUARDS.items():
        for n, scenario in enumerate(rows, 1):
            add(f"guard.{group}.{n:02d}", scenario)
    lines = sample_lines(full)
    for source, index, line in lines:
        add(f"sample.{source}.{index:04d}", S(line))
    chosen = lines[:: max(1, len(lines) // PAGE_LINES)][:PAGE_LINES]
    for channel in ("page", "terminal"):
        for source, index, line in chosen:
            add(f"sample.{source}.{index:04d}.{channel}", S(line, channel=channel))
    for group, table in (("composite", COMPOSITES), ("edge", EDGES)):      # appended last: the rows before them are the golden's, in its order
        for name, rows in table.items():
            for n, scenario in enumerate(rows, 1):
                add(f"{group}.{name}.{n:02d}", scenario)
    for name, rows in OPS_GROUPS.items():
        for n, scenario in enumerate(rows, 1):
            add(f"opscomp.{name}.{n:02d}", scenario)
    return scenarios, expectations


def render(scenarios: list) -> str:
    return "".join(json.dumps(s, ensure_ascii=False, sort_keys=False) + "\n" for s in scenarios)


def sha256_of(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_corpus(full: bool = False, path=CORPUS_FILE) -> int:
    scenarios, _ = generate(full)
    Path(path).write_text(render(scenarios), encoding="utf-8")
    return len(scenarios)


def check_corpus() -> list:
    """The problems of the committed corpus: it differs from what this script writes, an id repeats, a scenario is not well formed."""
    scenarios, _ = generate(False)
    problems = []
    if not CORPUS_FILE.is_file() or CORPUS_FILE.read_text(encoding="utf-8") != render(scenarios):
        problems.append("entry_corpus.jsonl is not what entry_corpus_build.py writes: run it again (and the golden is then a reviewed decision)")
    ids = [s["id"] for s in scenarios]
    if len(set(ids)) != len(ids):
        problems.append("an id repeats")
    sys.path.insert(0, str(HERE))
    import entry_kit  # noqa: E402  (the vocabulary of a scenario; heavy: only the check imports it)
    for scenario in scenarios:
        for problem in entry_kit.check_scenario(scenario):
            problems.append(f"{scenario['id']}: {problem}")
    return problems


def stats() -> str:
    scenarios, expectations = generate(False)
    by_channel = collections.Counter(s["channel"] for s in scenarios)
    by_source = collections.Counter(s["id"].split(".")[0] for s in scenarios)
    taken = collections.Counter(c for c, role, _ in expectations if role == "take")
    near = collections.Counter(c for c, role, _ in expectations if role == "near")
    lines = [f"scenarios: {len(scenarios)}", f"by channel: {dict(by_channel)}", f"by source: {dict(by_source)}"]
    lines += [f"{name:34s} take {taken[name]:3d}  near {near[name]:3d}" for name in CLAIMERS]
    return "\n".join(lines)


def record(workers: int) -> int:
    """Run the replay in record mode (one test per shard, each writing its outcomes to a folder of its own), then write the golden: the header (the commit this tree is at, the hash of the
    corpus, the count), and the outcomes in the order of the corpus. Refuses to overwrite a golden that exists: it is recorded once; a later change is a reviewed decision."""
    if GOLDEN_FILE.exists() and os.environ.get("WB_ENTRY_RECORD_AGAIN") != "yes, a reviewed decision":
        print("entry_golden.jsonl exists: it is recorded once, and changed only as a reviewed decision (runtime/README.md, 'The entry replay')", file=sys.stderr)
        return 2
    import tempfile
    folder = tempfile.mkdtemp(prefix="entry-golden-")
    env = dict(os.environ, WB_ENTRY_RECORD="1", WB_ENTRY_RECORD_DIR=folder)
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(HERE / "test_entry_replay.py"), "-k", "record_the_golden"]
    if workers > 1:
        command += ["-n", str(workers)]
    code = subprocess.call(command, env=env, cwd=str(REPO))
    if code != 0:
        return code
    rows = {}
    for shard in sorted(Path(folder).glob("shard-*.jsonl")):
        for row in read_rows(shard):
            rows[row["id"]] = row
    scenarios = read_rows(CORPUS_FILE)
    missing = [s["id"] for s in scenarios if s["id"] not in rows]
    if missing:
        print(f"{len(missing)} scenarios were not recorded, the first is {missing[0]}", file=sys.stderr)
        return 1
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO), text=True).strip()
    answers = {json.loads(path.read_text())["answers_sha256"] for path in Path(folder).glob("meta-*.json")}
    if len(answers) != 1:
        print("the shards read different tables of recorded answers", file=sys.stderr)
        return 1
    header = {"header": True, "commit": commit, "corpus_sha256": sha256_of(CORPUS_FILE), "answers_sha256": answers.pop(), "count": len(scenarios),
              "note": "the outcome of every scenario of entry_corpus.jsonl on the tree at this commit, before any package of step 1 moved the order of the claimers"}
    GOLDEN_FILE.write_text(json.dumps(header, ensure_ascii=False) + "\n" + "".join(json.dumps(rows[s["id"]], ensure_ascii=False) + "\n" for s in scenarios), encoding="utf-8")
    print(f"golden of {len(scenarios)} scenarios recorded at {commit[:9]}", file=sys.stderr)
    return 0


def record_added(workers: int, commit: str) -> int:
    """The base golden is closed (SPEC-HOTSPOTS, HOT-1): the old extension of it is replaced by one file of rows per package, `--record-package`."""
    print("the base golden is closed (SPEC-HOTSPOTS): write runtime/tests/entry_ext/<id>.scenarios.jsonl and run --record-package <id>", file=sys.stderr)
    return 2


def ext_problems() -> list:
    """The problems of the files of entry_ext/ (the kit reads them; heavy, so imported here)."""
    sys.path.insert(0, str(HERE))
    import entry_kit  # noqa: E402
    return entry_kit.ext_problems()


def record_package(package: str, workers: int) -> int:
    """Record the golden of one package: only `entry_ext/<package>.scenarios.jsonl` is run, through the replay in record mode with `WB_ENTRY_RECORD_SET=<package>`; the header holds the commit this tree
    is at, the hash of the scenarios file, the hash of the package's model texts and the count. Refuses when a file of entry_ext/ has a problem, and when the golden of the package exists (it is
    recorded once; a later change is a reviewed decision)."""
    import tempfile
    sys.path.insert(0, str(HERE))
    import entry_kit  # noqa: E402
    if not entry_kit.EXT_ID.match(package) or package not in entry_kit.ext_packages():
        print(f"{package}: no file entry_ext/{package}.scenarios.jsonl (the id is lower case words joined by hyphens)", file=sys.stderr)
        return 2
    problems = entry_kit.ext_problems()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    golden = entry_kit.EXT_DIR / f"{package}.golden.jsonl"
    if golden.exists() and os.environ.get("WB_ENTRY_RECORD_AGAIN") != "yes, a reviewed decision":
        print(f"{golden.name} exists: it is recorded once, and changed only as a reviewed decision (runtime/README.md, 'The entry replay')", file=sys.stderr)
        return 2
    folder = tempfile.mkdtemp(prefix="entry-golden-package-")
    env = dict(os.environ, WB_ENTRY_RECORD="1", WB_ENTRY_RECORD_DIR=folder, WB_ENTRY_RECORD_SET=package)
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(HERE / "test_entry_replay.py"), "-k", "record_the_golden"]
    if workers > 1:
        command += ["-n", str(workers)]
    code = subprocess.call(command, env=env, cwd=str(REPO))
    if code != 0:
        return code
    rows = {}
    for shard in sorted(Path(folder).glob("shard-*.jsonl")):
        for row in read_rows(shard):
            rows[row["id"]] = row
    scenarios = entry_kit.ext_scenarios(package)
    missing = [s["id"] for s in scenarios if s["id"] not in rows]
    if missing:
        print(f"{len(missing)} scenarios were not recorded, the first is {missing[0]}", file=sys.stderr)
        return 1
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO), text=True).strip()
    header = {"header": True, "package": package, "commit": commit, "scenarios_sha256": sha256_of(entry_kit.EXT_DIR / f"{package}.scenarios.jsonl"),
              "overrides_sha256": entry_kit.overrides_sha256(package), "count": len(scenarios)}
    golden.write_text(json.dumps(header, ensure_ascii=False) + "\n" + "".join(json.dumps(rows[s["id"]], ensure_ascii=False) + "\n" for s in scenarios), encoding="utf-8")
    print(f"golden of {len(scenarios)} scenarios of {package} recorded at {commit[:9]}", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write the corpus of the entry replay, check it, or record the golden of the tree it runs on.")
    parser.add_argument("--check", action="store_true", help="fail when the committed corpus is not what this script writes")
    parser.add_argument("--record", action="store_true", help="record entry_golden.jsonl on the tree as it is now (once; never to change a golden)")
    parser.add_argument("--record-added", action="store_true", help="refused: the base golden is closed; use --record-package")
    parser.add_argument("--record-package", metavar="ID", help="record entry_ext/<id>.golden.jsonl from entry_ext/<id>.scenarios.jsonl (HOT-1)")
    parser.add_argument("--stats", action="store_true", help="print the number of scenarios by channel, source and claimer")
    parser.add_argument("--full", action="store_true", help="take every line of the sampled corpora (the same as WB_FULL_FUZZ=1); written to entry_corpus_full.jsonl, never committed")
    parser.add_argument("--workers", type=int, default=4, help="pytest-xdist workers of --record (default 4)")
    args = parser.parse_args(argv)
    full = args.full or os.environ.get("WB_FULL_FUZZ") == "1"
    if args.stats:
        print(stats())
        return 0
    if args.check:
        problems = check_corpus() + ext_problems()
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    if args.record:
        return record(args.workers)
    if args.record_package:
        return record_package(args.record_package, args.workers)
    if args.record_added:
        return record_added(args.workers, subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(REPO), text=True).strip())
    count = write_corpus(full, HERE / ("entry_corpus_full.jsonl" if full else "entry_corpus.jsonl"))
    print(f"{count} scenarios written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
