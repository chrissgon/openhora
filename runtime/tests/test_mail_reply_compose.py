"""When the body of a reply describes its text, and what code accepts of the model's answer for a reply (BL7-2, runtime/mail_reply_compose.py and runtime/mail_compose.py).

The pure guards, offline, no model, no project, every name invented. `described` is read against its own literal lines: the line of the blind measure that took a described reply for
the text, an English twin, the reported words that must stay literal ("dizendo que...", "saying..."), the literal marker, and every reply or e-mail body the interpreter's corpora hold
(a corpus test: none of them is a description). `validate(..., body_only=True)` skips the check of the model's subject and no other: its oracle is the same text refused or accepted
without `body_only`, and a list of hostile bodies that stay refused. Vacuity tests show that the oracles of this file fail on a planted fault.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_reply_compose.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import standin_tree as st

mail_compose = st.load("mail_compose")
mail_reply_compose = st.load("mail_reply_compose")
natural = st.load("natural")

CORPORA = Path(__file__).resolve().parents[2] / "evals" / "interpreter"
CORPUS_FILES = ("dev.jsonl", "dev-long-v2.jsonl", "ix-test-v1.jsonl", "blite-blind-v2.jsonl")      # the last one is committed by BL7-0: used when it is there
BLIND_ID = "test-pt-br-60025"
BLIND_LINE = "responde a Marlene agradecendo pelo convite do aniversário e explicando com jeitinho que não vou poder ir"      # validate: allow english-only -- the Portuguese line of the blind measure
BLIND_BODY = "agradecendo pelo convite do aniversário e explicando com jeitinho que não vou poder ir"      # validate: allow english-only -- the Portuguese body span under test
TWIN_LINE = "reply to Marlene thanking her for the birthday invitation and explaining politely that I can't make it"
TWIN_BODY = "thanking her for the birthday invitation and explaining politely that I can't make it"
described = mail_reply_compose.described


# --- described -----------------------------------------------------------------------------------------------------------------------------------


def test_the_body_of_the_blind_line_and_an_english_twin_describe_the_text():
    assert described(BLIND_BODY, BLIND_LINE) is True
    assert described("agradecendo pelo convite do aniversário e explicando com jeitinho que não vou poder ir", "olha, responde a Marlene, agradecendo pelo convite do aniversário e explicando com jeitinho que não vou poder ir") is True      # validate: allow english-only -- the Portuguese line under test
    assert described(TWIN_BODY, TWIN_LINE) is True


def test_a_body_without_its_leading_gerund_still_describes_the_text_by_the_word_before_it_or_by_a_manner_phrase():
    assert described("pelo convite do aniversário", "responde a Marlene agradecendo pelo convite do aniversário") is True      # validate: allow english-only -- the Portuguese line under test: `before` is "agradecendo"
    assert described("that I can't come", "reply to Marlene explaining that I can't come") is True
    assert described("que não vou poder ir, com jeitinho", "responde a Marlene que não vou poder ir, com jeitinho") is True      # validate: allow english-only -- a manner phrase, no verb at all
    assert described("e explicando que não posso ir", "responde a Marlene e explicando que não posso ir") is True      # validate: allow english-only -- "e" is skipped: the second word is the verb


@pytest.mark.parametrize("body, line", [
    ("aceito a proposta", "responde ao Carlos dizendo que aceito a proposta"),      # validate: allow english-only -- the Portuguese line under test: `before` is "que", the body is the words as reported
    ("dizendo que aceito a proposta", "responde ao Carlos dizendo que aceito a proposta"),      # validate: allow english-only -- the Portuguese line under test: `first` is a say verb
    ("tell him yes", "reply to Sam, tell him yes"),
    ("saying thanks for the invite", "reply to Sam saying thanks for the invite"),
    ("thanks for the invite", "reply to Sam saying thanks for the invite"),
    ("thanks for the invite", "reply to Sam thanks for the invite"),
    ("ya la pagué", "responde al correo de Javier diciendo ya la pagué"),      # validate: allow english-only -- the Spanish line under test
    ("va bene", "rispondi alla mail di Paolo dicendo va bene"),      # validate: allow english-only -- the Italian line under test
])
def test_reported_words_and_plain_words_are_the_text(body, line):
    assert described(body, line) is False


def test_the_marker_of_a_literal_text_is_never_a_description_and_is_checked_first():
    assert described("texto exato: agradecendo pelo convite", "responde a Marlene texto exato: agradecendo pelo convite") is False      # validate: allow english-only -- the Portuguese line under test
    assert described("exact text: thanking her, politely", "reply to Marlene exact text: thanking her, politely") is False
    assert described("Exact Text : explaining kindly", "reply to Marlene Exact Text : explaining kindly") is False
    assert described("  texto exacto: agradeciendo", "responde a Marlene   texto exacto: agradeciendo") is False      # validate: allow english-only -- the Spanish line under test


SAY_VERBS = ("dizendo", "falando", "saying", "telling", "diciendo", "disant", "sagend", "dicendo")


@pytest.mark.parametrize("verb", SAY_VERBS)
def test_a_say_verb_as_the_word_before_or_the_first_word_keeps_the_text_literal_even_when_a_describing_word_follows(verb):
    assert described("politely we will pay on Monday", f"reply to Sam {verb} politely we will pay on Monday") is False, "the say verb is the word before: manner words are reported words"
    assert described("thanking you with kindness", f"reply to Sam {verb} thanking you with kindness") is False
    assert described(f"{verb} politely thanking you", f"reply to Sam {verb} politely thanking you") is False, "the say verb is the first word"
    assert described(f"and {verb} politely thanking you", f"reply to Sam and {verb} politely thanking you") is False, "or the second, behind a joining word"


def test_every_listed_describing_verb_describes_the_text_as_the_first_word_and_as_the_word_before():
    assert len(mail_reply_compose.HOW) >= 70
    for verb in sorted(mail_reply_compose.HOW):
        assert described(f"{verb} the invitation", f"reply to Sam {verb} the invitation") is True, verb
        assert described("the invitation", f"reply to Sam {verb} the invitation") is True, verb
        assert described(f"{verb} the invitation", f"reply to Sam. And now {verb} the invitation") is True, verb


def test_every_listed_manner_phrase_describes_the_text_only_as_whole_words():
    assert len(mail_reply_compose.MANNER) == 16
    for phrase in mail_reply_compose.MANNER:
        assert described(f"that I cannot come {phrase}", f"reply to Sam that I cannot come {phrase}") is True, phrase
    assert described("that kindly is her name", "reply to Sam that kindly is her name") is True, "a whole word"
    assert described("that unkindly is not a word of the list", "reply to Sam that unkindly is not a word of the list") is False, "a part of a word is not a manner phrase"
    assert described("com educacaoo", "responde a Sam com educacaoo") is False      # validate: allow english-only -- the Portuguese line under test


def test_the_lists_are_written_folded_so_that_a_typed_line_can_match_them():
    for word in mail_reply_compose.SAY | mail_reply_compose.HOW | mail_reply_compose.JOINERS | set(mail_reply_compose.MANNER):
        assert word == natural.normal(word) and word, word
    assert described("Agradecendo o convite", "Responde ao Sam Agradecendo o convite") is True      # validate: allow english-only -- the Portuguese line under test: capitals and accents are folded
    assert described("AGRADEÇA o convite", "responde ao Sam AGRADEÇA o convite") is True      # validate: allow english-only -- the Portuguese line under test
    assert described("with a Höflich tone", "reply to Sam with a Höflich tone") is True      # validate: allow english-only -- the German manner word, typed with its umlaut


def test_a_body_that_is_not_text_or_not_in_the_line_never_raises_and_is_not_described():
    for body in (None, 5, "", "   ", "...", ["agradecendo"]):
        assert described(body, BLIND_LINE) is False
    assert described("agradecendo pelo convite", None) is True, "no line: the body alone decides (the word before is unknown)"      # validate: allow english-only -- the Portuguese body under test
    assert described("pelo convite", "responde a Marlene falando sobre outra coisa") is False      # validate: allow english-only -- a body that is not in the line has no word before it
    assert described("pelo convite", "pelo convite agradecendo") is False, "the body opens the line: no word before it"      # validate: allow english-only -- the Portuguese line under test


# --- reported words stay literal behind a complementizer (finding 1) ----------------------------------------------------------------------------


@pytest.mark.parametrize("body, line", [
    ("confirme a reunião de amanhã", "responde a Marlene dizendo que confirme a reunião de amanhã"),      # validate: allow english-only -- the Portuguese line under test: an imperative after "dizendo que"
    ("não vou, com jeitinho", "responde a Marlene dizendo que não vou, com jeitinho"),      # validate: allow english-only -- the Portuguese line under test: a manner phrase after "dizendo que"
    ("que não vou, com jeitinho", "responde a Marlene falando que não vou, com jeitinho"),      # validate: allow english-only -- the Portuguese line under test: the span opens with the complementizer
    ("agradeça o convite", "responde a Marlene dizendo a ela que agradeça o convite"),      # validate: allow english-only -- the Portuguese line under test: "dizendo a ela que"
    ("I will gently remind the team", "reply to Sam saying that I will gently remind the team"),
    ("thank them politely", "reply to Sam telling him that thank them politely"),
    ("que confirmo, con cortesía", "responde a Sam diciendo que confirmo, con cortesía"),      # validate: allow english-only -- the Spanish line under test
    ("confirmando la reunión", "responde a Sam diciendo que confirmando la reunión"),      # validate: allow english-only -- the Spanish line under test
    ("je confirme poliment", "réponds à Paul en disant que je confirme poliment"),      # validate: allow english-only -- the French line under test: "en disant que"
    ("qu'il confirme", "réponds à Paul en disant qu'il confirme"),      # validate: allow english-only -- the French line under test: "qu'il"
    ("ich bestätige höflich", "antworte Paul sagend dass ich bestätige höflich"),      # validate: allow english-only -- the German line under test
    ("confermando la data", "rispondi a Paolo dicendo che confermando la data"),      # validate: allow english-only -- the Italian line under test
    ("che confermo gentilmente", "rispondi a Paolo dicendo che confermo gentilmente"),      # validate: allow english-only -- the Italian line under test
])
def test_anything_reported_after_a_say_verb_and_a_complementizer_stays_literal_in_six_languages(body, line):
    assert described(body, line) is False


def test_the_same_words_without_the_say_verb_are_described():
    assert described("confirme a reunião de amanhã", "responde a Marlene confirme a reunião de amanhã") is True      # validate: allow english-only -- the Portuguese line under test
    assert described("I will gently remind the team", "reply to Sam that I will gently remind the team") is True
    assert described("confirmando la reunión", "responde a Sam confirmando la reunión") is True      # validate: allow english-only -- the Spanish line under test


def test_a_say_verb_far_from_the_body_or_not_before_a_complementizer_does_not_protect_it():
    assert described("agradecendo o convite", "dizendo que sim, responde a Marlene agradecendo o convite") is True      # validate: allow english-only -- the say verb is four words away and no complementizer joins it to the body


# --- the literal marker in the line (finding 2) --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body, line", [
    ("agradecendo pelo convite", "responde a Marlene texto exato: agradecendo pelo convite"),      # validate: allow english-only -- the Portuguese line under test
    ("thanking you politely for the invite", "reply to Marlene, exact text: thanking you politely for the invite"),
    ("con cortesía, gracias", "responde a Marlene texto exacto: con cortesía, gracias"),      # validate: allow english-only -- the Spanish line under test
    ("remerciant poliment", "réponds à Paul texte exact : remerciant poliment"),      # validate: allow english-only -- the French line under test
])
def test_a_marker_in_the_line_before_the_body_keeps_it_literal_even_when_the_span_left_it_out(body, line):
    assert described(body, line) is False


def test_a_marker_after_the_body_or_a_body_not_found_in_the_line():
    assert described("agradecendo pelo convite", "responde a Marlene agradecendo pelo convite. texto exato: x") is True      # validate: allow english-only -- the marker comes after the body: it says nothing about it
    assert described("agradecendo pelo convite", "responde a Marlene texto exato: outra coisa") is False      # validate: allow english-only -- the body is not found as typed: a marker anywhere keeps the words literal


# --- written words are literal (finding 3) -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("body, line", [
    ("thank you so much, see you Friday", "reply to Marlene: thank you so much, see you Friday"),
    ("thank you!", "reply to Sam thank you!"),
    ("thank u for the invite", "reply to Sam thank u for the invite"),
    ("confirm receipt please", "reply to Bob: confirm receipt please"),
    ("explica melhor o que você quer dizer?", "responde ao João: explica melhor o que você quer dizer?"),      # validate: allow english-only -- the Portuguese line under test
    ("Obrigada pelo convite! Com carinho, Ana", "responde a Marlene: Obrigada pelo convite! Com carinho, Ana"),      # validate: allow english-only -- the Portuguese line under test
    ("please kindly send the invoice", "reply to Bob: please kindly send the invoice"),
    ("\"obrigado pelo convite, com carinho\"", "responde a Ana \"obrigado pelo convite, com carinho\""),      # validate: allow english-only -- the Portuguese line under test: a quoted body
    ("obrigado pelo convite, com carinho", "responde a Ana \"obrigado pelo convite, com carinho\""),      # validate: allow english-only -- the span without its quotes: the quote stands right before it
    ("thanks, kindly", "reply to Ana “thanks, kindly”"),
    ("agradecendo e recusando", "responde a Ana 'agradecendo e recusando'"),      # validate: allow english-only -- a single-quoted text
])
def test_a_colon_or_a_quote_before_the_body_and_a_thank_you_are_written_words_and_stay_literal(body, line):
    assert described(body, line) is False


def test_the_controls_of_the_written_words_rules_still_describe():
    assert described("agradecendo e recusando", "responde a Ana (agradecendo e recusando)") is True      # validate: allow english-only -- the Portuguese line under test: a bracket is not a dictation mark
    assert described("thank her and say no politely", "reply to Ana thank her and say no politely") is True, "'thank her' is a description of a thanks"
    assert described("thanking you politely", "reply to Ana thanking you politely") is True
    assert described("l'ami, agradecendo", "responde a l'ami, agradecendo") is False, "the apostrophe inside a word is not a quote and 'agradecendo' is not the first word"      # validate: allow english-only -- an apostrophe inside a word
    assert described("agradecendo", "responde a l'amie agradecendo") is True      # validate: allow english-only -- a word with an apostrophe before the body


# --- the corpora ---------------------------------------------------------------------------------------------------------------------------------


def corpus_bodies():
    """(id, line, [candidate bodies]) of every gold of the corpora that is a reply, a draft or an e-mail with a body, except the line of the blind measure that is a described reply."""
    out = []
    for name in CORPUS_FILES:
        path = CORPORA / name
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(raw)
            gold = row.get("gold") or {}
            body = (gold.get("slots") or {}).get("body")
            if gold.get("op") in ("mail-reply", "mail-draft", "mail-send") and body and row["id"] != BLIND_ID:
                out.append((row["id"], row["line"], list(body)))
    return out


def flagged(items):
    return [(item, body) for item, line, bodies in items for body in bodies if mail_reply_compose.described(body, line)]


def test_no_reply_or_e_mail_body_gold_of_the_corpora_is_taken_for_a_description():
    items = corpus_bodies()
    blind = (CORPORA / "blite-blind-v2.jsonl").exists()
    assert len(items) == 44 + (3 if blind else 0), "dev 3, dev-long-v2 4, ix-test-v1 37 and, once BL7-0 has committed the blind set, its 3 (47 in all)"
    assert flagged(items) == []


def test_vacuity_a_described_that_flags_everything_makes_the_corpus_test_fail_and_one_that_ignores_a_say_verb_makes_the_say_verb_test_fail(monkeypatch):
    monkeypatch.setattr(mail_reply_compose, "described", lambda body, line: True)
    assert len(flagged(corpus_bodies())) >= 44, "with the plant the corpus loop would fail"
    assert mail_reply_compose.described("aceito a proposta", "responde ao Carlos dizendo que aceito a proposta") is True      # validate: allow english-only -- the Portuguese line under test: the plant calls reported words a description
    monkeypatch.undo()
    monkeypatch.setattr(mail_reply_compose, "SAY", frozenset())
    assert mail_reply_compose.described("confirme a reunião de amanhã", "responde a Marlene dizendo que confirme a reunião de amanhã") is True, "without the say verbs the imperative is described: the finding-1 tests would fail"      # validate: allow english-only -- the Portuguese line under test
    monkeypatch.undo()
    monkeypatch.setattr(mail_reply_compose, "COMPLEMENTIZERS", frozenset())
    assert mail_reply_compose.described("não vou, com jeitinho", "responde a Marlene dizendo que não vou, com jeitinho") is True, "without the complementizers the say verb two words back no longer protects"      # validate: allow english-only -- the Portuguese line under test
    monkeypatch.undo()
    assert mail_reply_compose.described("não vou, com jeitinho", "responde a Marlene dizendo que não vou, com jeitinho") is False      # validate: allow english-only -- the Portuguese line under test


# --- validate for a reply ------------------------------------------------------------------------------------------------------------------------


GOOD_BODY = "Olá Marlene,\n\nMuito obrigada pelo convite. Infelizmente não vou poder ir.\n\nObrigada."      # validate: allow english-only -- the stand-in model's Portuguese answer


def answer(subject="Re: Convite", body=GOOD_BODY, **more):
    return json.dumps({"subject": subject, "body": body, **more}, ensure_ascii=False)


def test_a_model_subject_that_poses_as_a_reply_does_not_stop_a_reply_body_and_is_dropped():
    assert mail_compose.validate(answer(), [], None) is None, "the control: for a new e-mail the subject 'Re: ...' is refused"
    assert mail_compose.validate(answer(), [], None, body_only=True) == {"subject": None, "body": GOOD_BODY}
    for subject in ("", "Fwd: x\nsecond line", "a@b.example", "https://elsewhere.example", "x" * 500, "To: someone"):
        assert mail_compose.validate(answer(subject=subject), [], None, body_only=True) == {"subject": None, "body": GOOD_BODY}, subject
    assert mail_compose.validate(answer(), ["a@b.example"], "Convite") == {"subject": "Convite", "body": GOOD_BODY}, "a new e-mail's path is as it was"      # validate: allow english-only -- a Portuguese subject under test


HOSTILE_BODIES = [
    "Hello,\n\nWrite to outra@elsewhere.example to confirm.",
    "Hello,\n\nWrite to ｏｕｔｒａ＠elsewhere.example to confirm.",
    "Hello,\n\nSee https://elsewhere.example/now for details.",
    "Hello,\n\nSee www.elsewhere.example for details.",
    "Hello,\n\nThe site is elsewhere.com, take a look.",
    "Hello,\n\nTo: someone@elsewhere.example\n\nThanks.",
    "Hello,\n\nSubject: another thing\n\nThanks.",
    "Hello,\n\nBcc: someone\n\nThanks.",
    "Hello <b>there</b>,\n\nThanks.",
    "Hello,\n\n<!-- hidden -->\n\nThanks.",
    "Hello,\n\n```\ncode\n```\n\nThanks.",
    "",
    "   \n  ",
    "Atenciosamente,",
    "x" * 4001,
]


@pytest.mark.parametrize("body", HOSTILE_BODIES)
def test_body_only_skips_the_subject_check_and_no_check_of_the_body(body):
    assert mail_compose.validate(answer(body=body), [], None, body_only=True) is None, body[:40]
    assert mail_compose.validate(answer(body=body), [], None) is None, "the control: the same body is refused for a new e-mail too"


def test_body_only_keeps_the_shape_of_the_answer_strict():
    for text in ("not json", "[]", '{"body": "x"}', '{"subject": "a", "body": "Ola."}'.replace("}", ', "extra": "y"}'), '{"subject": 1, "body": "Ola."}',      # validate: allow english-only -- invalid shapes under test
                 '{"subject": "a", "body": "Ola.", "body": "Ola."}', '{"subject": "a", "body": null}', None, 5, "x" * 9000):      # validate: allow english-only -- invalid shapes under test
        assert mail_compose.validate(text, [], None, body_only=True) is None, text


def test_body_only_accepts_the_answer_in_one_json_fence_and_removes_a_closing_formula_alone():
    fenced = "```json\n" + answer(body="Olá,\n\nNão vou poder ir. Obrigada.\n\nAtenciosamente,") + "\n```"      # validate: allow english-only -- the stand-in model's Portuguese answer
    assert mail_compose.validate(fenced, [], None, body_only=True) == {"subject": None, "body": "Olá,\n\nNão vou poder ir. Obrigada."}      # validate: allow english-only -- the stand-in model's Portuguese answer


def test_vacuity_an_oracle_that_accepts_everything_flags_the_hostile_bodies_this_file_refuses(monkeypatch):
    monkeypatch.setattr(mail_compose, "validate", lambda text, to, subject=None, *, body_only=False: json.loads(text))
    assert all(mail_compose.validate(answer(body=body), [], None, body_only=True) is not None for body in HOSTILE_BODIES), "with the plant, every hostile body is let through"
