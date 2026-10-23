"""The words that choose the project the lines go to (slice S20, runtime/command_words.py): a pure reading of one line, in the six languages the interpreter reads.

Every expectation is a literal of this file. A line is a form only when it is, whole, polite words, one lead phrase and at most five words of a name; a lead that may begin another
request ("usa o projeto como base...") is a form only for a name that is a project of the sender, which the bridge decides (test_commands_in_words_bridge.py). Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_command_words.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

command_words = st.load("command_words")

SWITCH = [
    ("pt-BR", "muda para o projeto northwind-shop", "northwind shop"),
    ("pt-BR", "Troque para o projeto Northwind Shop, por favor", "northwind shop"),
    ("pt-BR", "vai para o projeto loja", "loja"),
    ("en", "switch to project northwind", "northwind"),
    ("en", "Please go to the project second-shop", "second shop"),
    ("es", "cambia al proyecto tienda", "tienda"),
    ("es", "pasa al proyecto tienda nueva", "tienda nueva"),
    ("fr", "passe au projet boutique", "boutique"),
    ("fr", "bascule sur le projet boutique", "boutique"),
    ("de", "wechsle zum Projekt Laden", "laden"),
    ("de", "gehe zum Projekt Laden, bitte", "laden"),
    ("it", "passa al progetto negozio", "negozio"),
    ("it", "vai al progetto negozio", "negozio"),
]
WHICH = ["qual projeto estou usando", "Qual projeto?", "em qual projeto estou", "muda de projeto", "which project am I using", "switch project", "que proyecto estoy usando",
         "quel projet", "welches Projekt", "in welchem Projekt bin ich", "quale progetto", "cambia progetto", "por favor, troque de projeto", "muda para o projeto"]
NOT = ["", "oi", "/project loja", "usa o projeto como base para planejar a feira de outubro", "switch to project plan the new launch email with the whole team now",
       "project status", "qual o prazo do projeto", "show me the project plan", "create a project", "me manda o projeto", "go to project@bot"]


@pytest.mark.parametrize("language,line,name", SWITCH)
def test_a_switch_names_the_project_the_sender_wants_in_each_language(language, line, name):
    assert command_words.project(line) == {"name": name, "weak": False}, language


@pytest.mark.parametrize("line", WHICH)
def test_a_question_about_the_project_or_a_switch_with_no_name_is_the_typed_project_with_no_name(line):
    assert command_words.project(line) == {"name": ""}


@pytest.mark.parametrize("line", NOT)
def test_a_line_that_is_not_a_form_is_none(line):
    assert command_words.project(line) is None, line


def test_a_lead_that_may_begin_a_request_is_weak_and_the_bridge_takes_it_only_for_a_project_of_the_sender():
    assert command_words.project("use the project northwind") == {"name": "northwind", "weak": True}
    assert command_words.project("usa o projeto northwind") == {"name": "northwind", "weak": True}
    assert command_words.project("usa o projeto") is None, "a weak lead with no name is nothing"


def test_a_name_is_resolved_among_the_projects_of_the_sender_by_its_folded_name_or_id():
    listed = [("northwind-shop", "a1b2c3"), ("Second Shop", "d4e5f6")]
    assert command_words.resolve("northwind shop", listed) == "northwind-shop"
    assert command_words.resolve("SECOND shop", listed) == "Second Shop"
    assert command_words.resolve("D4E5F6", listed) == "Second Shop"
    assert command_words.resolve("northwind", listed) is None and command_words.resolve("", listed) is None


def test_vacuity_the_forms_are_the_only_thing_that_makes_a_line_a_change_of_project():
    assert command_words.project("qual projeto estou usando") is not None
    assert command_words.project("qual o prazo do projeto") is None, "the same word, in a line that is a request"


# --- a decision or an act that a model chose: believed only when the line says the same (slice S20, review round) --------------------------------------------------------------

natural = st.load("natural")

PLAIN = [      # (operation, number, line): the plain command, in the six languages
    ("reject", 25, "rejeite a pergunta 25"), ("reject", 25, "por favor, dispense a pergunta 25"), ("reject", 4, "please decline decision 4"), ("reject", 4, "rechaza la pregunta 4"),
    ("reject", 4, "refuse la question 4"), ("reject", 4, "lehne die Frage 4 ab"), ("reject", 4, "respingi la domanda 4"),
    ("release", 7, "libere a entrega 7"), ("release", 7, "release the delivery 7"), ("release", 7, "libere la livraison 7"), ("release", 7, "rilascia la consegna 7"),
    ("approve", 31, "aprueba la decision 31"), ("approve", 31, "genehmige die Entscheidung 31"), ("approve", 31, "approva la richiesta 31"),
    ("cancel", 9, "por favor, cancele a solicitacao numero 9"), ("cancel", 9, "please cancel request 9"), ("cancel", 9, "annule la demande 9"), ("cancel", 9, "storniere die Anfrage 9"),
    ("stop-task", 3, "pare a tarefa 3"), ("stop-task", 3, "please stop task 3"), ("stop-task", 3, "detén la tarea 3"), ("stop-task", 3, "ferma il compito 3"),
    ("retry", 3, "por favor, tente a tarefa 3 de novo"), ("retry", 3, "please retry task 3"), ("retry", 3, "reintenta la tarea 3"), ("retry", 3, "wiederhole die Aufgabe 3"),
    ("attachment-add", 2, "adicione o arquivo 2"), ("attachment-discard", 2, "please discard attachment 2"), ("attachment-add", 2, "ajoute le fichier 2"),
    ("routine-pause", 4, "pausa a rotina 4"), ("routine-pause", 4, "please pause routine 4"), ("routine-pause", 4, "pausa la rutina 4"), ("routine-pause", 4, "pausiere die Routine 4"),
]
NOT_PLAIN = [      # the same operations, in lines that are not a plain command: a negation, a condition, a time, a question, another verb, another object, a second number
    ("cancel", 1, "não precisa cancelar o pedido 1"), ("cancel", 2, "devo cancelar o pedido 2?"), ("cancel", 2, "cancela o 2"), ("cancel", 2, "cancela a tarefa 2"),  # validate: allow english-only -- the Portuguese lines under test
    ("cancel", 1, "no need to cancel request 1"), ("cancel", 1, "don't cancel request 1"), ("cancel", 1, "cancel request 1 tomorrow"), ("cancel", 1, "cancelar pedido 1 si llueve"),
    ("cancel", 1, "annule la demande 1 si besoin"), ("cancel", 1, "storniere die Anfrage 1 wenn nötig"), ("cancel", 1, "annulla la richiesta 1 se serve"),
    ("cancel", 1, "non annullare la richiesta 1"), ("cancel", 1, "no canceles la solicitud 1"), ("cancel", 1, "n'annule pas la demande 1"), ("cancel", 1, "storniere die Anfrage 1 nicht"),
    ("stop-task", 3, "se der erro, para a tarefa 3"), ("stop-task", 3, "don't stop task 3"), ("stop-task", 1, "stop task 1 of 2"), ("stop-task", 3, "should we stop task 3?"),
    ("retry", 3, "never retry the task 3"), ("retry", 3, "retry task 3 when it fails"),
    ("reject", 1, "não rejeite a 1"), ("reject", 3, "rejeite a pergunta de 3 dias atrás"), ("reject", 1, "don't reject 1"), ("reject", 1, "task 1 should be rejected"),  # validate: allow english-only -- the Portuguese lines under test
    ("reject", 1, "reject task 1"), ("release", 1, "release the file 1"), ("approve", 1, "if it is late approve plan 1"),
    ("attachment-discard", 2, "discard the request 2"), ("attachment-add", 2, "adicione 2"), ("routine-pause", 4, "pause task 4"), ("routine-pause", 4, "do not pause routine 4"),
]  # validate: allow english-only -- the Portuguese lines under test


@pytest.mark.parametrize("op,number,line", PLAIN)
def test_a_plain_command_in_any_of_the_six_languages_is_believed(op, number, line):
    assert command_words.vet(line, op, number) is None, line


@pytest.mark.parametrize("op,number,line", NOT_PLAIN)
def test_a_line_that_negates_asks_conditions_names_another_object_or_a_second_number_is_not_believed(op, number, line):
    assert command_words.vet(line, op, number) is not None, line


def test_the_number_is_the_one_in_the_line_and_the_models_must_equal_it():
    assert command_words.vet("cancel request 9", "cancel", 8) == "number" and command_words.vet("cancel request nine", "cancel", 9) == "number"
    assert command_words.vet("cancel request 9 and 10", "cancel", 9) == "number" and command_words.vet("cancel request 9", "cancel", True) == "number"
    assert command_words.vet("cancel request 9", "cancel", None) == "number"


def test_vacuity_the_same_probe_without_its_negation_is_believed_and_with_it_is_not():
    assert command_words.vet("cancel request 1", "cancel", 1) is None
    assert command_words.vet("do not cancel request 1", "cancel", 1) == "again"
    assert command_words.vet("cancel request 1?", "cancel", 1) == "again"
    assert command_words.vet("cancel request 1 if it fails", "cancel", 1) == "again"


def test_a_number_that_belongs_to_a_time_or_a_quantity_is_not_a_decision_number():
    for line in ("reject the question from 3 days ago", "rejeite a pergunta de 3 dias atrás", "rejeite a pergunta em 2 semanas", "rejeite a pergunta há 2 horas", "reject it 25%",
                 "rejeite por $25", "rejeite 25 reais", "rejeite a pergunta von 3 Tagen"):  # validate: allow english-only -- the Portuguese lines under test
        assert natural.decision_numbers(line) == [], line
    assert natural.decision_numbers("rejeite a pergunta 25") == [25] and natural.decision_numbers("reject question #7.") == [7]
