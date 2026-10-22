"""The reading of a greeting or a request for help (slice S5, runtime/greeting.py): the WHOLE line is a closed form, in the six languages, or it is not a greeting.

Every expectation is a literal of this file: the lines below are what a person types, and the verdict of each is written by hand. No test reads the module's lists. A vacuity case plants
a reader that says yes to everything, one that says no to everything and one that stops at the first word, and shows the table catches each. The Portuguese lines are data under test
(`validate: allow english-only`), written with the escapes of their letters where an accent is needed; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_greeting.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

greeting = st.load("greeting")

GREETINGS = [
    # pt-BR
    "oi", "Oi!", "Ol\u00e1", "ola", "OLA!!", "bom dia", "Boa tarde \U0001f600", "boa noite", "E a\u00ed?", "tudo bem", "Tudo bem?", "oi, tudo bem?", "ol\u00e1 bom dia", "oiii", "ol\u00e1\u00e1\u00e1",
    "ajuda", "Ajuda por favor", "o que voc\u00ea faz", "O que voc\u00ea pode fazer?", "o que voce sabe fazer", "oi, o que voc\u00ea faz?",      # validate: allow english-only -- the Portuguese lines under test
    # en
    "hi", "Hello", "hello!", "hey", "Hey there", "good morning", "Good Evening!", "how are you?", "help", "Help me", "what can you do", "What can you do?", "hi, what can you do for me?", "heyyy",
    # es
    "hola", "\u00a1Hola!", "buenos d\u00edas", "Buenas tardes", "qu\u00e9 tal", "ayuda", "\u00bfQu\u00e9 puedes hacer?", "hola, qu\u00e9 sabes hacer",
    # fr
    "bonjour", "Bonsoir !", "salut", "ca va ?", "\u00c7a va ?", "aide", "Que peux-tu faire ?", "Qu'est-ce que tu sais faire ?", "bonjour, s'il vous pla\u00eet",
    # de
    "hallo", "Hallo!", "guten Tag", "Guten Morgen", "Gr\u00fc\u00df dich", "wie geht's?", "hilfe", "Was kannst du?", "hallo, was kannst du tun",
    # it
    "ciao", "Ciao!", "buongiorno", "Buonasera", "come stai?", "aiuto", "Cosa puoi fare?", "ciao, che cosa sai fare",
]
NOT_GREETINGS = [
    "oi, lista os emails", "ola mundo app", "bom dia, me lembra de ligar para a Dana", "oi Maria", "oi tudo bem lista os emails", "ajuda com o relatorio",      # validate: allow english-only -- the Portuguese lines under test
    "hello world", "hello, list my e-mails", "hi, remind me to call Dana", "help me write the report", "what can you do about the invoice",
    "hola, recu\u00e9rdame llamar a Dana", "bonjour, liste mes e-mails", "hallo, erinnere mich an Dana", "ciao, elenca le mie email",
    "sim", "aprovo", "ok", "lista os emails", "obrigado", "",
    "   ", "\U0001f44b", "?!", "/help", "/ask oi", "oi " * 11,
]
BY_LANGUAGE = [      # (tag, line, verdict): with a tag only that language's lists are read
    ("es", "hola", True), ("pt-BR", "hola", False), ("en", "hello", True), ("pt-BR", "hello", False), ("pt-BR", "bom dia", True), ("it", "bom dia", False),
    ("de", "guten Tag", True), ("fr", "guten Tag", False), ("fr", "bonjour", True), ("it", "ciao", True), ("xx", "hello", True), ("xx", "ciao", False),
]


def mismatches(reads):
    """The lines a reader gets wrong against the literal tables of this file."""
    wrong = [("greeting", line) for line in GREETINGS if reads(line) is not True]
    wrong += [("not a greeting", line) for line in NOT_GREETINGS if reads(line) is not False]
    return wrong


def test_every_greeting_and_help_form_of_the_six_languages_is_one_and_every_request_after_a_greeting_is_not():
    assert mismatches(greeting.is_greeting) == []


@pytest.mark.parametrize("line", GREETINGS)
def test_each_greeting_line(line):
    assert greeting.is_greeting(line) is True


@pytest.mark.parametrize("line", NOT_GREETINGS)
def test_each_line_that_is_not_a_greeting(line):
    assert greeting.is_greeting(line) is False


@pytest.mark.parametrize("tag,line,verdict", BY_LANGUAGE)
def test_with_a_tag_only_that_languages_lists_are_read(tag, line, verdict):
    assert greeting.is_greeting(line, tag) is verdict


@pytest.mark.parametrize("line,verdict", [("hello", True), ("bom dia", True), ("help", False), ("what can you do?", False), ("ajuda", False), ("hello, what can you do", False), ("ayuda", False)])
def test_without_helps_only_the_greetings_are_read(line, verdict):
    assert greeting.is_greeting(line, helps=False) is verdict


def test_a_non_text_value_is_not_a_greeting():
    assert [greeting.is_greeting(v) for v in (None, 3, b"oi", ["oi"])] == [False] * 4


def test_vacuity_the_table_catches_a_reader_that_is_wrong():
    assert len(mismatches(lambda line: True)) == len(NOT_GREETINGS)      # says yes to everything: misses every request
    assert len(mismatches(lambda line: False)) == len(GREETINGS)      # says no to everything: misses every greeting
    first_word = lambda line: bool(line.strip()) and not line.startswith("/") and any(line.lower().startswith(w) for w in ("oi", "ola", "hello", "hi", "hola", "ciao"))      # noqa: E731
    assert ("not a greeting", "oi, lista os emails") in mismatches(first_word)      # a reader that stops at the first word reads a request as a greeting
    assert mismatches(greeting.is_greeting) == [], "the real reader is the only one that passes"


def test_the_lists_are_phrases_in_the_form_the_line_is_normalised_to():
    greeting.check()
    for table in greeting.WORDS.values():
        for key in ("greet", "help", "filler"):
            assert all(p == greeting.normal(p) for p in table[key])
