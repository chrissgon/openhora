"""A question about the person's own data is not a web search (slice R2-F1, runtime/research_guard.py): the closed possessive forms, in six languages, both ways.

Pure. Every line is invented. The vacuity of each refusal is the same noun with no possessive: the bare noun stays allowed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_research_guard.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

guard = st.load("research_guard")

PERSONAL = [
    "mostra minha agenda", "liste meus emails", "liste meus e-mails de hoje", "qual o meu email", "quais sao meus arquivos", "abra minha pasta de contratos", "minha pasta",
    "meus ultimos 3 emails", "o que tem na minha agenda de amanhã",  # validate: allow english-only -- a Portuguese line under test
    "what is on my calendar", "show my e-mails", "my latest emails", "list my files", "open my folder", "my google drive", "is my inbox empty", "My Calendar",
    "que tengo en mi agenda", "mis correos de hoy", "mi ultimo correo", "mis archivos", "mi carpeta",
    "qu'y a-t-il dans mon agenda", "lis mes e-mails", "mon dossier", "ma boite mail", "mes fichiers",
    "was steht in meinem Kalender", "zeig mir meine E-Mails", "mein Ordner", "meine Dateien", "meinen Posteingang",
    "cosa c'e nella mia agenda", "leggi le mie email", "la mia cartella", "i miei file", "il mio calendario",
]
GENERAL = [
    "agenda cultural de Sao Paulo neste fim de semana", "quanto custa uma pasta de dente", "como vai estar o tempo em SP capital amanha?", "what is the calendar of public holidays in Brazil",
    "how do I send an email to the White House", "best free file hosting", "quem criou o formato de arquivo PDF", "the price of bitcoin in euros",
    "que agenda tem o presidente amanha", "cotacao do dolar hoje", "wetter in Berlin morgen", "il meteo a Roma domani", "la meteo a Paris demain", "mi dici il meteo a Roma",
    "o meu amigo trabalha na agenda cultural", "quem sao meus vizinhos famosos do bairro",
]


@pytest.mark.parametrize("line", PERSONAL)
def test_a_possessive_form_of_a_source_is_personal(line):
    assert guard.personal(line) is True, line


@pytest.mark.parametrize("line", GENERAL)
def test_a_general_question_or_a_bare_noun_is_not_personal(line):
    assert guard.personal(line) is False, line


def test_vacuity_the_same_noun_with_and_without_the_possessive():
    assert guard.personal("minha agenda") is True and guard.personal("a agenda") is False
    assert guard.personal("my emails") is True and guard.personal("the emails of the project") is False


def test_any_of_the_texts_counts_and_a_non_text_is_nothing():
    assert guard.personal("agenda de amanha", "mostra a minha agenda de amanha") is True
    assert guard.personal(None, "", 5) is False and guard.personal() is False


def test_accents_case_and_punctuation_do_not_matter():
    assert guard.personal("MINHA   AGENDA!!") is True and guard.personal("Mon  Dossier?") is True and guard.personal("e-mail: my E-MAIL") is True
