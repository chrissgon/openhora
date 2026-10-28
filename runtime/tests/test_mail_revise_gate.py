"""The gate of the change of a waiting e-mail card by words (slice S13b, runtime/mail_revise.py, runtime/ops_card_revise.py, runtime/messaging_turn.py the kind `decision-card-revise`, runtime/messaging_bridge.py `revise_waiting`).

The live case (the maintainer's Telegram test, 2026-10-22): an open e-mail card whose body already ended with a closing formula and a name, after three changes asked and done. He wrote
a line that starts with the verb "escreva" ("write") and, after a colon and a blank line, the closing and the name again. That verb was no word that asks for a change and the text had
no quotation marks, so the line asked nothing of the card, went to the conversation and the planning agent asked him to paste the e-mail. Here that line, on the real operations layer,
the real mail family, the W2 stand-in mailers and a stand-in model (test_mail_revise_flow.py's world), and through the real bridge with a stand-in messenger. Every expectation is a
literal of this file.

Held here:
  * the live line, on a card that already ends so: the card is not changed, the person is told the e-mail already says that (RV_ALREADY) and the card is sent again, so the word "sim"
    still approves it; the line never reaches the conversation or the agent;
  * the same line on a card that does not end so: a new card whose text ends with it; after three earlier changes too;
  * a text block after a colon and a line break is a text the instruction asks for, as a quoted text is: the new card must hold it;
  * a line that names the card's object ("o email", "the subject"...) and asks nothing the gate reads goes on to its own path, with no model call and no sentence (round 2 of the review);
  * the lines that ask for nothing (a list, a thanks, a thought, a new e-mail) still go on to the conversation with no model call.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_revise_gate.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import phrase_kit as pk
import standin_tree as st
from test_mail_compose_flow import ADDRESS, SENDER, card_lines, clock, forget, op, text_of  # noqa: F401
from test_mail_revise_flow import CLOSED, SUBJECT, GROUPS, Model, check, hostile, nothing_sent, open_cards, opened, reply_is, revise, says, setup, status  # noqa: F401
from test_messaging import FIXTURE, wait_for
from test_send_own_account import ACCOUNTS, world  # noqa: F401  (the own-account mail world)

ops = st.load("ops")
ops_core = st.load("ops_core")
bridge = st.load("messaging_bridge")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")
mail_revise = st.load("mail_revise")
phrases = st.load("phrases")

NAMED = CLOSED + "\nRenato Bragança"      # validate: allow english-only -- the card's text in Portuguese
LIVE_LINE = "Escreva ao final do email:\n\nAtenciosamente,\nRenato Bragança"      # validate: allow english-only -- the live line, Portuguese
BLOCK = "Atenciosamente,\nRenato Bragança"      # validate: allow english-only -- the text block the live line asks for
PLAIN = "Olá,\n\nGostaria de marcar uma reunião amanhã às 16h. Você teria disponibilidade?"      # validate: allow english-only -- a Portuguese card text
ALREADY = "RV_ALREADY"      # the phrase key of the sentence a revision that changes nothing answers (pt-BR)
UNCLEAR = "Não entendi o ajuste."      # validate: allow english-only -- the sentence that no longer exists: it must never be said
OWNER = "4242"
EXACT_GROUPS = GROUPS + ("approve-effect-send-own", "ask-mail")      # ask-mail: the card shows the text of the e-mail on the phone, which is what makes it a card a word can approve


def exact_line(body):
    return f"Envie um email para {ADDRESS} assunto {SUBJECT}. texto exato: {body}"


def exact_decision(body):
    return op("mail-send", {"to": ADDRESS, "subject": SUBJECT, "body": "texto exato: " + body})


def card_with(world, monkeypatch, body, revise_answer=None):
    """The card of a text sent as written, over the REAL operations layer; the stand-in model answers the interpreter's call and, later, the revise call."""
    model = setup(world, monkeypatch, groups=EXACT_GROUPS, interpret=exact_decision(body), revise=revise_answer)
    from test_mail_compose_flow import phone
    number, sha = opened(world, phone(world, exact_line(body)))
    return model, number, sha


# --- the closed list of the words that ask for a change ---------------------------------------------------------------------------------------------------


WORDS = ["escreva", "escreve", "escrever", "ponha", "poe", "deixe", "deixa", "termine", "termina", "finalize", "finaliza", "encerre", "encerra", "assine", "assina", "reescreva",
         "reescreve", "acrescentar", "acrescente", "inclua", "retire", "retira", "write", "sign", "end", "finish", "rewrite", "append", "escribe", "escriba", "pon", "ponga", "firma",
         "écris", "écrivez", "mets", "mettez", "signe", "schreibe", "schreib", "setze", "beende", "unterschreibe", "scrivi", "metti"]      # validate: allow english-only -- the words in six languages


@pytest.mark.parametrize("word", [w for w in WORDS if mail_revise._fold(w) in mail_revise.WIDE_VERBS])
def test_the_verbs_that_write_or_end_a_text_ask_for_a_change_only_beside_a_locator_or_an_object_of_the_card(word):
    assert mail_revise.asks_change(f"{word} this at the end") is True and mail_revise.asks_change(f"{word} the e-mail") is True
    assert mail_revise.asks_change(f"{word} this") is False, "alone the same verb is an ordinary request"


@pytest.mark.parametrize("line", ["muda o fim", "troca a palavra", "ajusta o tom", "corrige o erro", "change this", "fix the typo"])      # validate: allow english-only -- lines under test
def test_the_words_that_have_always_asked_for_a_change_still_do_without_a_locator(line):
    assert mail_revise.asks_change(line) is True


@pytest.mark.parametrize("line", ["lista os emails", "obrigado", "pode enviar", "esquece", "qual o clima amanhã?", "também preciso marcar o dentista sexta", "quando é a reunião?", "ok"])      # validate: allow english-only -- Portuguese lines under test
def test_the_words_of_a_thought_or_a_request_are_not_words_that_ask_for_a_change(line):
    assert mail_revise.has_change_word(line) is False


# --- a text block after a colon and a line break ----------------------------------------------------------------------------------------------------------


def test_a_block_after_a_colon_and_a_line_break_is_a_text_the_instruction_asks_for_only_when_the_line_before_it_asks_for_it():
    assert mail_revise.literals(LIVE_LINE) == [BLOCK]
    assert mail_revise.literals('Ponha no fim do email:\n\n"Oi"\n\nTchau') == ['"Oi"\n\nTchau'], "a quoted text inside the block is part of the block"      # validate: allow english-only -- the Portuguese line under test
    assert mail_revise.literals("Escreva: Atenciosamente, Renato") == [], "a colon with the text on the same line is no block"
    assert mail_revise.literals("Escreva ao final:\n\n") == [] and mail_revise.literals("Escreva ao final:") == []      # validate: allow english-only -- the Portuguese line under test
    assert mail_revise.literals('Troque por "A b" ao final:\n\nC d') == ["A b", "C d"]      # validate: allow english-only -- the Portuguese line under test
    for line in ("Pensando aqui:\nacho que vou viajar sexta", "Lista de compras:\nleite\npão", "Me ajuda com isso:\nqual a capital da França?", "Escreva para a Ana:\nOi Ana", "Termina a tarefa:\n1. a\n2. b"):      # validate: allow english-only -- Portuguese lines under test
        assert mail_revise.literals(line) == [], line


def test_vacuity_the_old_reading_found_no_text_in_the_live_line():
    assert mail_revise.literals(mail_revise.clean(LIVE_LINE)) == [], "once the line is one line there is no block to find: the gate reads the line as typed"
    assert mail_revise.asks_change(mail_revise.clean(LIVE_LINE)) is True, "the verb with a locator is what opens the gate for the live line"


def test_a_block_is_present_when_its_words_are_there_whatever_the_white_space():
    assert mail_revise.accept(json.dumps({"subject": SUBJECT, "body": PLAIN + "\n\nAtenciosamente,\n\nRenato Bragança"}, ensure_ascii=False), ["a@b.example"], SUBJECT, PLAIN,      # validate: allow english-only -- the stand-in model's answer
                              LIVE_LINE) is not None
    assert mail_revise.accept(json.dumps({"subject": SUBJECT, "body": PLAIN + "\n\nAtenciosamente,"}, ensure_ascii=False), ["a@b.example"], SUBJECT, PLAIN, LIVE_LINE) == {"same": True, "holds": False}, "the block is not in the card and the answer did not write it: nothing changed and it is not already so"      # validate: allow english-only -- the stand-in model's answer


def test_the_words_that_name_the_object_of_the_card():
    named = ["o email está estranho", "o e-mail", "a mensagem não faz sentido", "o texto", "o assunto", "o evento", "the e-mail is odd", "the subject", "este email", "el asunto", "le texto"]      # validate: allow english-only -- lines in several languages
    other = ["lista os emails", "Envie um email para ana@client.example", "os emails de ontem", "um email novo", "emails", "obrigado"]      # validate: allow english-only -- lines under test
    assert [mail_revise.names_object(line) for line in named] == [True] * len(named)
    assert [mail_revise.names_object(line) for line in other] == [False] * len(other)


# --- the live line over the real operations layer -------------------------------------------------------------------------------------------------------


def test_the_live_line_is_a_line_for_the_card_and_on_a_card_that_already_ends_so_it_says_so_and_sends_the_card_again(world, clock, monkeypatch):
    model, old, sha = card_with(world, monkeypatch, NAMED, revise_answer=hostile(NAMED))
    assert check(world, old, sha, LIVE_LINE) == "mail"
    got = revise(world, old, sha, LIVE_LINE)
    assert reply_is(got, ALREADY, old), got
    assert status(world, old) == "open" and open_cards(world) == [old] and len(model.of("revise")) == 1
    nothing_sent(world)


def test_a_model_that_writes_the_block_twice_is_read_as_the_same_card(world, clock, monkeypatch):
    _, old, sha = card_with(world, monkeypatch, NAMED, revise_answer=hostile(NAMED + "\n" + BLOCK))
    assert reply_is(revise(world, old, sha, LIVE_LINE), ALREADY, old) and open_cards(world) == [old]


def test_the_same_line_on_a_card_that_does_not_end_so_opens_a_new_card_whose_text_ends_with_it(world, clock, monkeypatch):
    model, old, sha = card_with(world, monkeypatch, PLAIN, revise_answer=hostile(PLAIN + "\n\n" + BLOCK))
    got = revise(world, old, sha, LIVE_LINE)
    new = got["resend"]
    assert isinstance(new, int) and new != old and got["say"].startswith("Pronto: aqui está o e-mail")      # validate: allow english-only -- the Portuguese sentence under test
    assert text_of(card_lines(world, got))[-2:] == ["Atenciosamente,", "Renato Bragança"]      # validate: allow english-only -- the card's text
    assert status(world, old) != "open" and open_cards(world) == [new]
    assert "instruction: Escreva ao final do email:\n\nAtenciosamente,\nRenato Bragança\nbody:\n" in model.of("revise")[0]["user"], "the model is shown the line with its line breaks"      # validate: allow english-only -- the live line


def test_a_block_the_answer_does_not_hold_is_refused_and_the_card_is_sent_again(world, clock, monkeypatch):
    _, old, sha = card_with(world, monkeypatch, PLAIN, revise_answer=hostile(PLAIN + "\n\nAtenciosamente,\nOutro Nome"))
    assert revise(world, old, sha, LIVE_LINE)["resend"] == old and open_cards(world) == [old]


def test_after_three_earlier_changes_the_live_line_still_changes_the_card(world, clock, monkeypatch):
    model, number, sha = card_with(world, monkeypatch, PLAIN)
    lines = ['Troque a primeira palavra por "Oi"', 'Troque a segunda palavra por "Hey"', 'Troque a terceira palavra por "Hum"']      # validate: allow english-only -- the Portuguese lines under test
    body = PLAIN
    for line, word in zip(lines, ("Oi", "Hey", "Hum")):
        body = body + "\n" + word
        model.answers["revise"] = hostile(body)
        number_new = revise(world, number, ops.pending(world["path"], number)["payload_sha256"], line)["resend"]
        assert isinstance(number_new, int)
        number = number_new
    model.answers["revise"] = hostile(body + "\n\n" + BLOCK)
    sha = ops.pending(world["path"], number)["payload_sha256"]
    got = revise(world, number, sha, LIVE_LINE)
    assert isinstance(got["resend"], int) and got["resend"] != number and open_cards(world) == [got["resend"]]
    assert BLOCK.replace("\n", "\n│ ") in ops.pending(world["path"], got["resend"])["body"]


# --- a line that names the card's object and asks nothing the gate reads ----------------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["lista os emails", "obrigado", "pode enviar", "esquece", "qual o clima amanhã?", "também preciso marcar o dentista sexta", "Envie um email para ana@client.example. Quero marcar uma reuniao"])      # validate: allow english-only -- the Portuguese lines under test
def test_the_lines_that_ask_for_nothing_and_name_no_object_still_go_on_with_no_model_call(world, clock, monkeypatch, line):
    model, old, sha = card_with(world, monkeypatch, PLAIN)
    assert check(world, old, sha, line) is None and revise(world, old, sha, line) == {"pass": True}
    assert model.of("revise") == [] and open_cards(world) == [old]


# --- through the bridge ---------------------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def day(world, tmp_path, monkeypatch):
    model = setup(world, monkeypatch, groups=EXACT_GROUPS, interpret=exact_decision(NAMED), revise=hostile(NAMED))
    root = tmp_path / "bench-messenger"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    data = tmp_path / "ledger-data"
    data.mkdir()
    path = world["path"]
    w = SimpleNamespace(path=path, folder=folder, log=[], model=model, world=world)
    projects = [{"id": shell_kit.project_id(path), "name": "northwind-shop", "path": path}]
    w.bridge = bridge.Bridge(ops, projects, providers.Messenger("telegram", root=str(root)), ledgers.Ledger(str(data), "telegram"), "telegram", w.log.append,
                             clock=lambda: "2026-10-21T10:00:00+00:00")

    def sent():
        target = folder / "sent.jsonl"
        return [json.loads(line) for line in target.read_text().splitlines()] if target.is_file() else []

    def settle():
        for thread in list(w.bridge.threads):
            thread.join(30)

    def say(text, **fields):
        update = {"update_id": 1, "sender": OWNER, "chat": OWNER, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None}
        update.update(fields)
        w.bridge.handle(update)
        settle()
        assert wait_for(lambda: w.bridge.last_sent.get(OWNER) is not None or not w.sent())
    w.sent, w.say = sent, say
    w.texts = lambda: [r["message"]["text"] for r in sent()]
    yield w
    w.bridge.stopping.set()
    settle()


def gmail_sends(world):
    return [r for r in world["gmail"].requests if r["method"] == "POST" and "send" in r["path"]]


def test_the_live_line_through_the_bridge_says_it_is_already_so_shows_the_card_again_and_a_word_still_approves_it(day, clock, monkeypatch):
    day.say(exact_line(NAMED))
    first = len(day.sent())
    assert first >= 1 and "Renato Bragança" in day.texts()[-1]      # validate: allow english-only -- the card
    day.say(LIVE_LINE)
    assert says(day.texts()[first], ALREADY) and day.texts()[first + 1] == day.texts()[first - 1], "the sentence, then the card again"
    assert len(day.sent()) == first + 2 and len(day.model.of("revise")) == 1
    assert [c for c in day.model.calls if c["kind"] == "interpret"] != [] and len([c for c in day.model.calls if c["kind"] == "interpret"]) == 1, "the line was not read by the interpreter: it never reached the conversation"
    day.say("sim")
    assert len(gmail_sends(day.world)) == 1, "the word approved the card that was sent again"
    assert not any("Qual é o e-mail" in t for t in day.texts())      # validate: allow english-only -- the question the agent asked


def test_the_live_line_through_the_bridge_on_a_card_that_does_not_end_so_gives_a_new_card_that_a_word_approves(day, clock, monkeypatch):
    day.model.answers["interpret"] = exact_decision(PLAIN)
    day.model.answers["revise"] = hostile(PLAIN + "\n\n" + BLOCK)
    day.say(exact_line(PLAIN))
    first = len(day.sent())
    day.say(LIVE_LINE)
    assert wait_for(lambda: len(day.sent()) == first + 2)
    assert day.texts()[first].startswith("Pronto: aqui está o e-mail") and "Renato Bragança" in day.texts()[-1]      # validate: allow english-only -- the Portuguese sentence under test
    assert wait_for(lambda: day.bridge.last_sent.get(OWNER) is not None)
    day.say("sim")
    sends = gmail_sends(day.world)
    assert len(sends) == 1


def test_a_line_that_names_the_object_of_the_card_goes_on_to_its_own_path_through_the_bridge_and_asks_nothing_of_the_revise_model(day, clock, monkeypatch):
    day.model.answers["interpret"] = json.dumps({"v": 1, "kind": "none"})
    day.say(exact_line(NAMED))
    first = len(day.sent())
    day.say("lista o email do João")      # validate: allow english-only -- the Portuguese line under test
    assert len(day.model.of("revise")) == 0 and UNCLEAR not in day.texts() and len([c for c in day.model.calls if c["kind"] == "interpret"]) == 2, "it went to the interpreter as any line does"


# --- the review round: the verbs of ordinary requests, the card's object and the places ------------------------------------------------------------------------------


ORDINARY = ["escreva para a Ana amanhã", "termina a tarefa 3", "deixa pra lá", "deixa eu pensar", "write to Bob", "sign me up", "end", "finish the report by friday", "assina a newsletter",      # validate: allow english-only -- lines under test
            "pon una alarma a las 7", "Pensando aqui:\nacho que vou viajar sexta", "Lista de compras:\nleite\npão", "Me ajuda com isso:\nqual a capital da França?"]      # validate: allow english-only -- lines under test
REQUESTS = ["lista o email do João", "encaminha o email", "o email do João chegou?", "cancela o evento de amanhã"]      # validate: allow english-only -- lines under test


@pytest.mark.parametrize("line", ORDINARY + REQUESTS)
def test_an_ordinary_request_never_reaches_the_revise_model_and_goes_on_to_its_own_path(world, clock, monkeypatch, line):
    model, old, sha = card_with(world, monkeypatch, NAMED, revise_answer=hostile(NAMED + "\n" + line))
    assert check(world, old, sha, line) is None
    assert revise(world, old, sha, line) == {"pass": True}
    assert model.of("revise") == [] and open_cards(world) == [old] and status(world, old) == "open"
    assert check(world, old, sha, LIVE_LINE) == "mail", "vacuity: the live line, with its verb and its locator, is one"


@pytest.mark.parametrize("line, kept", [("Escreva ao final do email:\n\nAtenciosamente,\nRenato Bragança", True), ("assine o email no fim", True), ("termina o email com Abraços", True),      # validate: allow english-only -- lines under test
                                        ("escreva isso ao final", True), ("write this at the end of the e-mail", True)])      # validate: allow english-only -- Portuguese lines under test
def test_the_same_verbs_beside_a_locator_or_an_object_open_the_gate(world, clock, monkeypatch, line, kept):
    _, old, sha = card_with(world, monkeypatch, NAMED)
    assert check(world, old, sha, line) == "mail"


def test_rv_already_only_when_the_text_is_at_the_place_asked(world, clock, monkeypatch):
    _, old, sha = card_with(world, monkeypatch, NAMED, revise_answer=hostile(NAMED))
    assert reply_is(revise(world, old, sha, LIVE_LINE), ALREADY, old), "the card ends with the block and the line says the end"
    at_start = "Escreva no início do email:\n\nAtenciosamente,\nRenato Bragança"      # validate: allow english-only -- the Portuguese line under test
    got = revise(world, old, sha, at_start)
    assert not says(got["say"], ALREADY) and got["resend"] == old, "the card holds the block, but at the end, and the line asks for the start"
    _, old2, sha2 = card_with(world, monkeypatch, BLOCK + "\n\n" + PLAIN, revise_answer=hostile(BLOCK + "\n\n" + PLAIN))
    assert reply_is(revise(world, old2, sha2, at_start), ALREADY, old2)
    assert not says(revise(world, old2, sha2, LIVE_LINE)["say"], ALREADY), "and now it is the end that is not so"


def test_a_quoted_text_is_looked_for_as_written_and_only_a_block_is_compared_with_its_white_space_flattened():
    answer_flat = json.dumps({"subject": SUBJECT, "body": PLAIN + "\nAtenciosamente, Renato"}, ensure_ascii=False)      # validate: allow english-only -- the stand-in model's answer
    answer_lines = json.dumps({"subject": SUBJECT, "body": PLAIN + "\nAtenciosamente,\nRenato"}, ensure_ascii=False)      # validate: allow english-only -- the stand-in model's answer
    quoted = 'Coloque "Atenciosamente, Renato" ao final'      # validate: allow english-only -- the Portuguese line under test
    assert mail_revise.accept(answer_flat, ["a@b.example"], SUBJECT, PLAIN, quoted) is not None
    assert mail_revise.accept(answer_lines, ["a@b.example"], SUBJECT, PLAIN, quoted) is None, "a quoted text is S13's exact substring"
    block = "Escreva ao final do email:\n\nAtenciosamente,\nRenato"      # validate: allow english-only -- the Portuguese line under test
    assert mail_revise.accept(answer_flat, ["a@b.example"], SUBJECT, PLAIN, block) is not None, "a block ignores the white space"
