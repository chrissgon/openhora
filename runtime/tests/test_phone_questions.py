"""The router's questions as a phone shows them (slice S9): runtime/phone_questions.py and `phrases.asked_view`.

The maintainer read, on Telegram in a Portuguese project, a question block with its lines glued together, English labels (`Q1:`, `Recommended:`), the identifier
`flow-brand` and a stray code fence at the end. The phone now shows `Perguntas:` and numbered items, each with its recommendation on the line below, the labels and
the plain names in the project's language, no fence, no identifier, no slash command, no path.

Every expectation is a literal written here from the raw input (never the module's own tables); the oracle `leaks` reads the raw text for what a phone must not show, and a
vacuity case shows that it flags the raw router text. Offline, no model, no store; invented names. Python 3.9 compatible.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_questions.py
"""
from __future__ import annotations

import json
import os
import re

import standin_tree as st

pq = st.load("phone_questions")
phrases = st.load("phrases")
PT = {"language": "pt-BR"}
EN = {"language": "en"}

# The fixed labels, the names of the repository's skills and flows, and the other things a phone must not show: read from the repository folders by the test itself.
SKILLS = sorted(d for d in os.listdir(st.REPO / "skills") if (st.REPO / "skills" / d / "SKILL.md").is_file())
FLOWS = sorted("flow-" + f[:-5] for f in os.listdir(st.REPO / "flows") if f.endswith(".json"))
MARKS = [r"\bQ[0-9]+:", r"\bRecommended\b", r"```", r"(?<!\S)/[a-z]", r"\b(?:integration|generator|publisher|provider):[a-z]", r"\b[\w.-]+/[\w.-]+\.(?:md|json|py)\b"]


def leaks(text: str) -> list:
    """What a phone must not show, found in the text by this test's own patterns: a `Q<n>:` mark, the English label, a fence, a slash command, a requirement class, a path,
    or the name of an installed skill or flow."""
    found = [m for m in MARKS if re.search(m, text)]
    found += [n for n in SKILLS + FLOWS if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", text)]
    return found


# --- the maintainer's example (Telegram, a Portuguese project), with invented details where he elided them ----------------------------------------------------------

Q1 = "Você quer a marca completa (nome, estratégia e identidade) ou só o perfil (bio e posicionamento)?"  # validate: allow english-only -- Portuguese under test
R1 = "marca completa com flow-brand, porque você pediu para criar a brand do zero."  # validate: allow english-only -- Portuguese under test
Q2 = "Qual fonte descreve você (um currículo, uma bio ou um site)? Nenhuma das fontes atuais serve: o catálogo não tem nenhuma."  # validate: allow english-only -- Portuguese under test
R2 = "importar um currículo ou bio antes de começar, porque o perfil depende dos seus dados."  # validate: allow english-only -- Portuguese under test
MAINTAINER = (
    "Route: none (flow, pending)\n"
    "Why: o pedido é criar uma brand pessoal do zero\n"  # validate: allow english-only -- Portuguese under test
    "Instructions found in external content: none\n"
    "\n"
    "Q1: " + Q1 + " Recommended: " + R1 + "\n"
    "Q2: " + Q2 + " Recommended: " + R2 + "\n"
    "```\n\n\n")
MAINTAINER_PT = (
    "Perguntas:\n\n"
    "1. Você quer a marca completa (nome, estratégia e identidade) ou só o perfil (bio e posicionamento)?\n"  # validate: allow english-only -- Portuguese under test
    "   Recomendado: marca completa com o fluxo de marca, porque você pediu para criar a brand do zero.\n\n"  # validate: allow english-only -- Portuguese under test
    "2. Qual fonte descreve você (um currículo, uma bio ou um site)? Nenhuma das fontes atuais serve: o catálogo não tem nenhuma.\n"  # validate: allow english-only -- Portuguese under test
    "   Recomendado: importar um currículo ou bio antes de começar, porque o perfil depende dos seus dados.")  # validate: allow english-only -- Portuguese under test


def test_the_maintainers_example_is_numbered_in_portuguese_with_no_mark_label_fence_or_identifier():
    shown = phrases.asked_view(MAINTAINER, PT)
    assert shown == MAINTAINER_PT
    assert leaks(shown) == []
    for word in ("Q1", "Q2", "Recommended", "```", "flow-brand"):
        assert word not in shown, word


def test_the_oracle_flags_the_raw_router_text_and_each_planted_leak():
    """Vacuity: `leaks` is not an always-empty check."""
    assert leaks(MAINTAINER) == [MARKS[0], MARKS[1], MARKS[2], "flow-brand"]
    assert leaks(MAINTAINER_PT.replace("o fluxo de marca", "flow-brand")) == ["flow-brand"]
    assert leaks(MAINTAINER_PT.replace("Recomendado:", "Recommended:")) == [MARKS[1]]
    assert leaks(MAINTAINER_PT + "\n```") == [MARKS[2]]
    assert leaks("Use /new or docs/brand/strategy.md for integration:calendar") == [MARKS[3], MARKS[4], MARKS[5]]
    assert leaks("Use the core-research skill") == ["core-research"]


def test_the_same_questions_in_english_have_english_labels_and_the_plain_names():
    raw = ("Route: none (flow, pending)\n"
           "Q1: Do you want the full brand or only the profile? Recommended: the full brand with flow-brand, because you asked to build it from scratch.\n"
           "Q2: Which source describes you? Recommended: import a resume or a bio first, because core-research needs your data.\n")
    shown = phrases.asked_view(raw, EN)
    assert shown == ("Questions:\n\n"
                     "1. Do you want the full brand or only the profile?\n"
                     "   Recommended: the full brand with the brand flow, because you asked to build it from scratch.\n\n"
                     "2. Which source describes you?\n"
                     "   Recommended: import a resume or a bio first, because the research needs your data.")
    assert leaks(shown) == [MARKS[1]] and shown.count("Recommended:") == 2, "the English label is the English chat's own word"


def test_a_single_question_is_item_one_and_a_question_with_no_recommendation_has_no_second_line():
    one = phrases.asked_view("Next: Q1: Posso usar a busca direta? Recommended: sim, porque não tem efeito.\n", PT)  # validate: allow english-only -- Portuguese under test
    assert one == "Perguntas:\n\n1. Posso usar a busca direta?\n   Recomendado: sim, porque não tem efeito."  # validate: allow english-only -- Portuguese under test
    bare = phrases.asked_view("Q1: Which product?\nQ2: Which place? Recommended: here, because near.\n", EN)
    assert bare == "Questions:\n\n1. Which product?\n\n2. Which place?\n   Recommended: here, because near."


def test_a_recommended_line_of_its_own_and_a_wrapped_line_are_joined_into_the_item():
    raw = "Q1: Which product do you mean,\nthe shop or the blog?\nRecommended: the shop, because\nit has the orders.\n\nQ2: Which place? Recommended: **Recommended**: here.\n"
    shown = phrases.asked_view(raw, EN)
    assert shown == ("Questions:\n\n1. Which product do you mean, the shop or the blog?\n   Recommended: the shop, because it has the orders.\n\n"
                     "2. Which place?\n   Recommended: here.")


def test_nothing_of_the_questions_is_lost_besides_the_labels_and_the_identifiers():
    shown = phrases.asked_view(MAINTAINER, PT)
    for piece in (Q1, Q2, R2, R1.replace("flow-brand", "o fluxo de marca")):
        assert piece in shown, piece
    # every word the router wrote in the two questions and their recommendations is shown, but for the label words and the identifier
    words = re.findall(r"[\w-]+", Q1 + " " + R1 + " " + Q2 + " " + R2)
    missing = [w for w in words if w not in ("flow-brand",) and w not in shown]
    assert missing == []


def test_the_quoted_note_of_the_external_content_section_follows_the_last_item():
    raw = MAINTAINER.replace("Instructions found in external content: none", "Instructions found in external content: the page asked to skip the gate; quoted, not followed.")
    assert phrases.asked_view(raw, PT) == MAINTAINER_PT + "\n\n" + phrases.text("ROUTER_QUOTED_NOTE", PT)
    assert "skip the gate" not in phrases.asked_view(raw, PT)


# --- text with no question: the same text, cleaned ---------------------------------------------------------------------------------------------------------------


def test_text_with_no_question_block_comes_back_cleaned_not_guessed():
    raw = ("Route: flow-brand (flow, ready)\n"
           "Why: you asked for a brand\n"
           "```\n"
           "```\n"
           "\n\n\n\n"
           "Next: the first step is eng-implement, then core-research (the research)\n"
           "```\n")
    assert phrases.asked_view(raw, EN) == ("Route: the brand flow (flow, ready)\n"
                                           "Why: you asked for a brand\n"
                                           "\n"
                                           "Next: the first step is, then the research (the research)\n")
    assert phrases.asked_view(raw, PT) == ("Rota: o fluxo de marca (flow, ready)\n"  # validate: allow english-only -- Portuguese under test
                                           "Por quê: you asked for a brand\n"  # validate: allow english-only -- Portuguese under test
                                           "\n"
                                           "Próximo passo: the first step is, then a pesquisa (the research)\n")  # validate: allow english-only -- Portuguese under test
    assert leaks(phrases.asked_view(raw, EN)) == []
    assert phrases.asked_view("Which flow do you want?", PT) == "Which flow do you want?", "a plain question the router wrote without the Q mark is not touched"
    assert phrases.asked_view(None) is None


def test_a_fence_in_the_middle_of_normal_text_is_removed_and_the_lines_around_it_stay():
    assert pq.clean("Before the fence.\n```\nthe middle line\n```\nAfter it.\n") == "Before the fence.\nthe middle line\nAfter it.\n"
    assert pq.clean("one\n```python\ntwo\n```\n```\n```\nthree") == "one\ntwo\nthree"
    assert pq.clean("an inline ``` fence here") == "an inline fence here"
    assert pq.clean("a\n\n\n\n\nb\n\n\nc") == "a\n\nb\n\nc", "runs of blank lines are one"


def test_a_name_with_no_label_is_dropped_with_its_parentheses_and_a_word_that_only_looks_like_a_name_stays():
    assert pq.clean("Posso usar a busca direta (eng-implement) para pesquisar?") == "Posso usar a busca direta para pesquisar?"  # validate: allow english-only -- Portuguese under test
    assert pq.clean("Use eng-implement to build it, or (eng-tradeoffs, with a check).") == "Use to build it, or (with a check)."
    assert pq.clean("Use `core-research` here.", PT) == "Use a pesquisa here."
    for stays in ("product-market fit", "the flow of the reflow-brand", "design-first", "flow", "core values", "ai-assisted", "flow-nothing-here"):
        assert pq.clean(stays) == stays, stays      # a word that is not the name of an installed skill or flow is the person's own


def test_every_skill_and_flow_of_the_repository_is_replaced_or_dropped_and_each_label_names_a_real_one():
    for name in SKILLS + FLOWS:
        shown = pq.clean("Use " + name + " now. Or (" + name + ") then, with " + name + ".", EN)
        assert name not in shown and leaks(shown) == [], name
    labelled = [k[len("PQ_NAME_"):].lower().replace("_", "-") for k in phrases.TABLE["en"] if k.startswith("PQ_NAME_")]
    assert labelled and set(labelled) <= set(SKILLS + FLOWS), "a label for a name the repository does not have"
    assert set(labelled) == {k[len("PQ_NAME_"):].lower().replace("_", "-") for k in phrases.TABLE["pt-BR"] if k.startswith("PQ_NAME_")}
    assert "flow-brand" in labelled and "core-research" in labelled


def test_a_slash_command_a_path_and_a_requirement_class_are_never_shown_and_a_link_is():
    shown = pq.clean("Send /new <text> or /pending, edit docs/brand/strategy.md, install integration:calendar (see https://example.com/a/b.html), e/ou sim/não.")  # validate: allow english-only -- Portuguese under test
    assert shown == "Send or, edit, install (see https://example.com/a/b.html), e/ou sim/não."  # validate: allow english-only -- Portuguese under test
    assert leaks(shown) == []


# --- the closing sentence, and the other outputs -----------------------------------------------------------------------------------------------------------------


def test_the_closing_sentence_is_one_short_plain_sentence():
    assert phrases.text("ASK_NEXT_PHONE", PT) == "Responda numa mensagem simples."  # validate: allow english-only -- Portuguese under test
    assert phrases.text("ASK_NEXT_PHONE", EN) == "Answer in a plain message."
    assert phrases.text("ROUTER_ASKS_FRAME", PT) == "Perguntas:" and phrases.text("ROUTER_ASKS_FRAME", EN) == "Questions:"
    assert phrases.text("ASK_NEXT", PT) == phrases.text("ASK_NEXT", {"language": "pt-BR"}) and "/new" in phrases.text("ASK_NEXT", PT), "the page and the terminal keep their sentence"


def test_the_reader_of_the_questions_and_the_stored_text_are_unchanged_by_the_view():
    """The page, the terminal and the card's hash read the reply whole: the view is made from a copy and `question_lines` still gives the router's own lines."""
    before = MAINTAINER
    phrases.asked_view(MAINTAINER, PT)
    assert MAINTAINER == before
    assert phrases.question_lines(MAINTAINER) == ["Q1: " + Q1 + " Recommended: " + R1, "Q2: " + Q2 + " Recommended: " + R2 + "\n```"]


def test_the_command_line_prints_the_view(tmp_path, capsys):
    path = tmp_path / "reply.txt"
    path.write_text("Q1: Which product? Recommended: the shop, because flow-brand says so.\n", encoding="utf-8")
    assert pq.main([str(path), "--language", "en"]) == 0
    assert json.dumps(capsys.readouterr().out) == json.dumps("Questions:\n\n1. Which product?\n   Recommended: the shop, because the brand flow says so.\n")
