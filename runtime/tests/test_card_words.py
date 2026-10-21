"""The words that decide a decision card (package S2, runtime/card_words.py `card_word`, limit L64): the whole line is one closed approve or reject form, with polite
words, an article and a number or an ordinal, or the word for all, and no open tail.

THE ORACLE RULE (the lesson of NR-1, NR-5a and NR-5b, each of which had a circular checker). The oracle below reads the RAW line with this file's OWN literal lists
(ORACLE_APPROVE, ORACLE_REJECT, ORACLE_ALL, ORACLE_ORDINALS, ORACLE_POLITE) and its own hand-written fold. It never calls `card_word` or reads the module's lists. One
direction is checked by a separate test: every oracle phrase is in the module's lists (a list that loses one fails). The other direction is the walk: any line `card_word`
accepts that the oracle does not list is a violation, so a list that gains a looser phrase fails. The vacuity case plants a `card_word` that accepts an open tail and shows the
walk fails on it.

The lines are fictional. A Portuguese word with an accent is written with its escape, so that the file holds no Portuguese text.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_card_words.py
"""
from __future__ import annotations

import itertools

import pytest

import standin_tree as st

card_words = st.load("card_words")

# --- the oracle: its own lists, its own fold -----------------------------------------------------------------------------------------------------------------------------

ORACLE_APPROVE = [("sim",), ("ok",), ("aprovo",), ("aprova",), ("aprovar",), ("aprovado",), ("pode",), ("pode", "marcar"), ("pode", "mandar"), ("pode", "salvar"), ("manda", "ver"),
                  ("yes",), ("approve",), ("approved",), ("go", "ahead")]
ORACLE_REJECT = [("nao",), ("rejeito",), ("rejeita",), ("cancela",), ("deixa",), ("no",), ("reject",), ("cancel",)]
ORACLE_ALL = {"todos", "todas", "all"}
ORACLE_ARTICLES = {"o", "a", "the", "number", "n", "numero"}
ORACLE_ORDINALS = {"primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2, "terceiro": 3, "terceira": 3, "quarto": 4, "quarta": 4, "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6,
                   "setimo": 7, "setima": 7, "oitavo": 8, "oitava": 8, "nono": 9, "nona": 9, "decimo": 10, "decima": 10,
                   "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10}
ORACLE_POLITE = [("por", "favor"), ("pf",), ("please",), ("pls",), ("pode",), ("poderia",), ("consegue",), ("oi",), ("ola",), ("ei",), ("can", "you"), ("could", "you"), ("would", "you"),
                 ("hey",), ("hi",)]
ACCENTS = {"\u00e3": "a", "\u00e1": "a", "\u00e0": "a", "\u00e2": "a", "\u00e9": "e", "\u00ea": "e", "\u00ed": "i", "\u00f3": "o", "\u00f4": "o", "\u00f5": "o", "\u00fa": "u", "\u00e7": "c"}


def fold(line: str) -> list:
    """Lower case, accents off, every other character a space: the tokens of the raw line."""
    out = []
    for ch in line.lower():
        ch = ACCENTS.get(ch, ch)
        out.append(ch if ("a" <= ch <= "z" or "0" <= ch <= "9") else " ")
    return "".join(out).split()


def polite_run(tokens: list) -> bool:
    """Whether the tokens are nothing but polite phrases, in any number."""
    if not tokens:
        return True
    return any(tuple(tokens[:len(p)]) == p and polite_run(tokens[len(p):]) for p in ORACLE_POLITE)


def position(tokens: list):
    """(True, n) for an optional article and a number or an ordinal, (True, None) for nothing, (False, None) for anything else."""
    if not tokens:
        return True, None
    if tokens[0] in ORACLE_ARTICLES and len(tokens) > 1:
        tokens = tokens[1:]
    if len(tokens) == 1:
        word = tokens[0]
        if word.isdigit() and len(word) <= 2 and int(word) >= 1:
            return True, int(word)
        if word in ORACLE_ORDINALS:
            return True, ORACLE_ORDINALS[word]
    return False, None


def oracle(line: str):
    """What the raw line is, by this file's lists alone: {"op", "n", "all"} or None."""
    tokens = fold(line)
    if not tokens or len(tokens) > 8 or line.lstrip().startswith("/"):
        return None
    found = set()
    for start in range(len(tokens) + 1):
        for end in range(start + 1, len(tokens) + 1):
            if not (polite_run(tokens[:start]) and polite_run(tokens[end:])):
                continue
            core = tokens[start:end]
            for op, forms in (("approve", ORACLE_APPROVE), ("reject", ORACLE_REJECT)):
                for form in forms:
                    size = len(form)
                    if tuple(core[:size]) == form:
                        ok, n = position(core[size:])
                        if ok:
                            found.add((op, n, False))
                        if len(core) == size + 1 and core[size] in ORACLE_ALL:
                            found.add((op, None, True))
                    if len(core) == size + 1 and core[0] in ORACLE_ALL and tuple(core[1:]) == form:
                        found.add((op, None, True))
    ops = {op for op, _, _ in found}
    if len(ops) != 1 or len(found) != 1:
        return None
    op, n, every = next(iter(found))
    return {"op": op, "n": n, "all": every}


# --- hand-written expectations (never computed) -------------------------------------------------------------------------------------------------------------------------

GOOD = [
    ("sim", ("approve", None, False)), ("Sim!", ("approve", None, False)), ("ok", ("approve", None, False)), ("OK.", ("approve", None, False)),
    ("aprovo", ("approve", None, False)), ("Aprovo", ("approve", None, False)), ("aprova", ("approve", None, False)), ("aprovado", ("approve", None, False)),
    ("pode aprovar", ("approve", None, False)), ("aprovar", ("approve", None, False)),
    ("pode", ("approve", None, False)), ("pode marcar", ("approve", None, False)), ("Pode marcar!", ("approve", None, False)), ("pode mandar", ("approve", None, False)),
    ("pode salvar", ("approve", None, False)), ("manda ver", ("approve", None, False)), ("por favor, sim", ("approve", None, False)), ("sim, por favor", ("approve", None, False)),
    ("pode sim", ("approve", None, False)), ("yes", ("approve", None, False)), ("go ahead", ("approve", None, False)), ("approve", ("approve", None, False)),
    ("approved", ("approve", None, False)), ("yes please", ("approve", None, False)),
    ("N\u00e3o", ("reject", None, False)), ("nao", ("reject", None, False)), ("N\u00c3O!", ("reject", None, False)), ("rejeito", ("reject", None, False)),
    ("rejeita", ("reject", None, False)), ("cancela", ("reject", None, False)), ("deixa", ("reject", None, False)), ("no", ("reject", None, False)),
    ("reject", ("reject", None, False)), ("cancel", ("reject", None, False)), ("no, please", ("reject", None, False)),
    ("aprovo o 2", ("approve", 2, False)), ("aprovo #3", ("approve", 3, False)), ("aprova o 12", ("approve", 12, False)), ("aprova o primeiro", ("approve", 1, False)),
    ("aprova a segunda", ("approve", 2, False)), ("aprova o d\u00e9cimo", ("approve", 10, False)), ("rejeito o 1", ("reject", 1, False)), ("rejeita o terceiro", ("reject", 3, False)),
    ("approve the second", ("approve", 2, False)), ("reject number 4", ("reject", 4, False)), ("approve 2", ("approve", 2, False)), ("por favor aprovo o 2", ("approve", 2, False)),
    ("aprova todos", ("approve", None, True)), ("aprova todas", ("approve", None, True)), ("approve all", ("approve", None, True)), ("todos n\u00e3o", ("reject", None, True)),
    ("todas nao", ("reject", None, True)), ("reject all", ("reject", None, True)), ("rejeito todos", ("reject", None, True)),
]
BAD = [
    "pode marcar o dentista", "pode marcar amanh\u00e3 \u00e0s 3", "pode marcar amanh\u00e3 \u00e0s 10h", "sim mas s\u00f3 amanh\u00e3", "sim e n\u00e3o", "ok vou ver", "aprovo o 0", "aprovo o 100",
    "aprova todos o 2", "aprova rejeita", "o segundo sim", "cancela o lembrete 3", "cancela o pedido 4", "aprova o plano 3", "pode ser", "quero cancelar", "yes send it tomorrow",
    "approve the plan", "no way", "go on", "sim sim", "todos", "o primeiro", "2", "#2", "o", "", "   ", "/approve 3", "/sim", "aprovo o primeiro e o segundo", "aprovo o 2 e o 3",
    "podemos aprovar", "n\u00e3o sei", "talvez", "aprovo o x", "aprova um", "sim, mas muda a hora para as 15h", "reject the", "cancel it", "ok then", "aprovado por mim", "all",
    "todas as tres", "agende corte de cabelo amanh\u00e3 \u00e0s 14h no outlook",
]


def as_tuple(got):
    return None if got is None else (got["op"], got["n"], got["all"])


def test_every_good_line_gives_the_hand_written_answer_and_every_bad_line_none():
    for line, expected in GOOD:
        assert as_tuple(card_words.card_word(line)) == expected, line
    for line in BAD:
        assert card_words.card_word(line) is None, line


def test_the_guards_named_by_the_spec():
    """An open tail is no form; "approve all" is returned as `all` for the caller to refuse; "todos nao" is a reject of all."""
    assert card_words.card_word("pode marcar o dentista") is None, "an open tail is not a form"
    assert card_words.card_word("pode marcar amanh\u00e3 \u00e0s 3") is None
    assert card_words.card_word("aprova todos") == {"op": "approve", "n": None, "all": True}
    assert card_words.card_word("todos n\u00e3o") == {"op": "reject", "n": None, "all": True}
    assert card_words.card_word("aprovo o 2")["all"] is False and card_words.card_word("aprovo")["all"] is False


def test_a_line_that_is_both_an_approve_and_a_reject_form_is_none():
    assert card_words.card_word("aprova rejeita") is None and card_words.card_word("sim n\u00e3o") is None and card_words.card_word("yes no") is None


def test_a_slash_line_a_blank_line_and_a_non_text_are_none():
    for line in ("/aprovo", "  ", "", None, 3, ["sim"], {"text": "sim"}):
        assert card_words.card_word(line) is None, line


def test_a_long_sentence_that_starts_with_a_form_is_none():
    assert card_words.card_word("sim " * 9) is None and card_words.card_word("sim sim sim") is None


def test_the_oracle_agrees_with_every_hand_written_line():
    """The oracle itself is checked against the hand-written table, so a wrong oracle cannot hide a wrong card_word."""
    for line, expected in GOOD:
        assert as_tuple(oracle(line)) == expected, line
    for line in BAD:
        assert oracle(line) is None, line


# --- the walk: generated lines, the oracle decides what each one is ------------------------------------------------------------------------------------------------------

BANK = ["sim", "ok", "aprovo", "aprova", "pode", "marcar", "mandar", "salvar", "manda", "ver", "yes", "approve", "go", "ahead", "nao", "rejeito", "cancela", "deixa", "no", "reject",
        "cancel", "todos", "todas", "all", "hey", "can", "you", "o", "a", "the", "number", "2", "10", "0", "primeiro", "segunda", "third", "por", "favor", "please", "dentista", "lembrete",
        "3", "e", "mas", "amanha", "hoje", "arquivo", "agenda", "aprovar", "pf"]


def walk_lines():
    for size in (1, 2):
        for combo in itertools.product(BANK, repeat=size):
            yield " ".join(combo)
    for index, combo in enumerate(itertools.product(BANK, repeat=3)):
        if index % 11 == 0:
            yield " ".join(combo)
    for line, _ in GOOD:
        yield line
        yield line + " o dentista"
        yield "talvez " + line
        yield line.upper() + "!!"
    for line in BAD:
        yield line


def violations(word_of) -> list:
    """Every line where `word_of` and the oracle disagree: an act the oracle does not list, or an act the oracle lists and `word_of` misses."""
    bad = []
    for line in walk_lines():
        got, expected = as_tuple(word_of(line)), as_tuple(oracle(line))
        if got != expected:
            bad.append((line, got, expected))
    return bad


def test_the_walk_card_word_and_the_oracle_never_disagree():
    bad = violations(card_words.card_word)
    assert bad == [], bad[:12]


def test_the_walk_is_not_vacuous_it_fails_on_a_card_word_that_accepts_an_open_tail():
    """The vacuity case: a planted `card_word` that takes a line with a tail as an approval, and one that takes "all" as a single act, must both make the walk report violations."""
    real = card_words.card_word

    def open_tail(line):
        got = real(line)
        if got is None and isinstance(line, str) and line.split() and line.split()[0] in ("pode", "sim", "ok"):
            return {"op": "approve", "n": None, "all": False}
        return got

    def drops_all(line):
        got = real(line)
        return dict(got, all=False) if got else got
    assert violations(open_tail) != []
    assert violations(drops_all) != []


def test_every_phrase_the_oracle_lists_is_in_the_modules_lists_so_a_list_that_loses_one_fails():
    words = card_words.merged()
    for tokens in ORACLE_APPROVE:
        assert " ".join(tokens) in words["approve"] or tokens == ("pode", "aprovar"), tokens
    for tokens in ORACLE_REJECT:
        assert " ".join(tokens) in words["reject"], tokens
    assert ORACLE_ALL == set(words["all"]) and ORACLE_ARTICLES == set(words["articles"])
    for at, group in enumerate(words["ordinals"], 1):
        assert {w for w, n in ORACLE_ORDINALS.items() if n == at} == set(group), at
    assert {" ".join(t) for t in ORACLE_POLITE} == set(words["polite"])


def test_the_approve_reject_and_all_lists_are_disjoint_and_the_shipped_lists_pass_the_check():
    words = card_words.merged()
    assert not set(words["approve"]) & set(words["reject"]) and not set(words["approve"]) & set(words["all"]) and not set(words["reject"]) & set(words["all"])
    card_words.check()


@pytest.mark.parametrize("lists, message", [
    ({"approve": ["Sim"]}, "not a phrase"),
    ({"approve": ["sim!"]}, "not a phrase"),
    ({"approve": ["a.*"]}, "not a phrase"),
    ({"reject": ["n\u00e3o"]}, "not a phrase"),
    ({"all": ["todos  os"]}, "not a phrase"),
    ({"ordinals": [["Primeiro"]]}, "not a phrase"),
    ({"ordinals": [["a"]] * 11}, "at most 10"),
    ({"approve": ["sim"], "reject": ["sim"]}, "is in approve and in reject"),
    ({"approve": ["todos"], "all": ["todos"]}, "is in approve and in all"),
])
def test_the_check_rejects_a_malformed_list(monkeypatch, lists, message):
    monkeypatch.setitem(card_words.WORDS, "xx", lists)
    with pytest.raises(ValueError, match=message):
        card_words.check()
