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
