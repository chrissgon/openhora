"""A greeting gets a greeting back and a summary of what THIS sender may do (slice S5: runtime/greeting.py, ops_say.greeting_reply), through the real `ops.say` on the stand-in world.

Code decides, never the model: the interpreter's route is stood in by a stub that counts its calls, and a greeting makes none (the control line "lista os emails" makes one, so the count means
something). The summary names exactly the families the sender's policy permits: a policy without the sending of e-mail never mentions it. A sender who may not talk gets the refusal of today.
Every expected reply is a literal of this file. The Portuguese lines are data under test; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_say_greeting.py
"""
from __future__ import annotations

import re

import standin_tree as st
from test_ask import accept
from test_ops_natural import world  # noqa: F401  (the real-operations world fixture)
from test_ops_interpret_dispatch import ops_interpret, interpreter_route, prepare, ZONE  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")

MAINTAINER = ["read", "talk", "answer", "release", "approve-plans", "approve-acceptances", "reject-cancel", "brakes", "retry", "ask-mail", "calendar-write", "mail-send", "mail-organize",
              "files-write", "routine-brakes", "ask", "reminders", "add-sources", "approve-effect-calendar", "approve-effect-send-own", "approve-effect-mailbox", "approve-effect-files", "interpret"]
NO_SEND = [g for g in MAINTAINER if g not in ("mail-send", "approve-effect-send-own")]
PROFILES = {"maintainer": MAINTAINER, "nosend": NO_SEND, "bare": ["read", "talk"], "silent": ["read", "ask"], "plain": ["read", "talk", "interpret"]}
IDS = {name: f"5511900000{n:04d}" for n, name in enumerate(PROFILES, 1)}
SENDERS = {"telegram": [{"id": IDS[name], "policy": name} for name in PROFILES]}
WHO = {name: f"telegram:{IDS[name]}" for name in PROFILES}

PT_MAINTAINER = "\n".join([
    "Ol\u00e1! Eu posso ajudar com isto:",
    "- ler e resumir os seus e-mails",
    "- criar lembretes",
    "- criar, mudar ou cancelar eventos na sua agenda, com a sua aprova\u00e7\u00e3o",
    "- escrever e enviar e-mails, cada um s\u00f3 depois da sua aprova\u00e7\u00e3o",
    "- organizar a sua caixa de e-mail (rascunho, arquivar, mover, marcar, lixeira), com a sua aprova\u00e7\u00e3o",
    "- salvar arquivos no seu Drive ou OneDrive, com a sua aprova\u00e7\u00e3o",
    "- aprovar um card respondendo \"aprovo\" ou \"sim\", ou recusar respondendo \"n\u00e3o\"",
    "- voc\u00ea pode pedir com as suas palavras, em qualquer uma de seis l\u00ednguas",
])      # validate: allow english-only -- the Portuguese reply under test
EN_MAINTAINER = "\n".join([
    "Hello! Here is what I can do for you now:",
    "- read and summarise your e-mails",
    "- set reminders",
    "- create, change or cancel events on your calendar, after you approve",
    "- draft and send e-mails, each one only after you approve it",
    "- tidy your mailbox (drafts, archive, move, mark, trash), after you approve",
    "- save files to your Drive or OneDrive, after you approve",
    "- approve a card by replying \"approve\" or \"yes\", or refuse it by replying \"no\"",
    "- you can ask in your own words, in any of six languages",
])
EN_NO_SEND = EN_MAINTAINER.replace("- draft and send e-mails, each one only after you approve it\n", "")
EN_BARE = "Hello! Here is what I can do for you now:\n- send me a request in a sentence and I will pass it to the planning agent"
EN_PLAIN = "Hello! Here is what I can do for you now:\n- you can ask in your own words, in any of six languages"
REFUSAL = "error: /say is not enabled for this channel; the project's configuration (channels.messaging) turns it on"


def calls_of(world, monkeypatch, language=None):
    """The world with the five profiles and a stub model; the list every model call is appended to."""
    calls = []
    prepare(world, monkeypatch, calls, {"text": '{"v":1,"kind":"none"}'}, spies=False)
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS}, language=language)
    return calls


def phone(world, who, line):
    return ops.say(world["path"], line, channel="messaging", sender=WHO[who])


def test_the_maintainers_policy_gets_the_greeting_and_every_family_it_holds_in_portuguese(world, monkeypatch):
    calls = calls_of(world, monkeypatch, "pt-BR")
    assert phone(world, "maintainer", "Ola")["reply"] == PT_MAINTAINER and calls == []
    assert phone(world, "maintainer", "Bom dia, tudo bem?")["reply"] == PT_MAINTAINER and calls == []


def test_the_same_policy_in_an_english_project_gets_the_english_reply(world, monkeypatch):
    calls = calls_of(world, monkeypatch)
    assert phone(world, "maintainer", "hello")["reply"] == EN_MAINTAINER and calls == []


def test_the_summary_lists_only_what_the_policy_holds(world, monkeypatch):
    calls_of(world, monkeypatch)
    no_send = phone(world, "nosend", "hi")["reply"]
    assert no_send == EN_NO_SEND and "send" not in no_send.lower().replace("send me", ""), "a policy without mail-send never mentions sending"
    assert phone(world, "bare", "hi")["reply"] == EN_BARE
    assert phone(world, "plain", "hi")["reply"] == EN_PLAIN


def test_a_help_form_gets_the_same_summary_and_a_greeting_never_reaches_the_interpreter(world, monkeypatch):
    calls = calls_of(world, monkeypatch)
    for line in ("help", "What can you do?", "ayuda", "hola, buenos d\u00edas", "Bonjour !", "Guten Tag", "ciao", "ajuda"):
        assert phone(world, "maintainer", line)["reply"] == EN_MAINTAINER, line
    assert calls == [], "no model call for a greeting: code decides"
    phone(world, "maintainer", "obrigado, era so isso")      # validate: allow english-only -- the control line: a line no list of code claims does reach the model, so the count above means something
    assert len(calls) == 1 and calls[0]["route"], "the control line makes the one model call"


def test_a_greeting_followed_by_a_request_is_not_a_greeting_and_goes_on_as_before(world, monkeypatch):
    calls = calls_of(world, monkeypatch)
    for line in ("oi, lista os emails", "bom dia, me lembra de ligar para a Dana"):      # validate: allow english-only -- the lines under test: code reads a request after the greeting as it always did
        assert phone(world, "maintainer", line)["reply"] != EN_MAINTAINER, line
    assert len(calls) == 2, "both lines went on to the interpreter, as they did before"
    out = phone(world, "maintainer", "ola mundo app")      # validate: allow english-only -- the line under test: no list of code claims it, so the interpreter reads it
    assert out["reply"] != EN_MAINTAINER and len(calls) == 3


def test_a_sender_who_may_not_talk_gets_the_refusal_of_today_for_a_greeting(world, monkeypatch):
    calls = calls_of(world, monkeypatch)
    for line in ("hello", "bom dia", "hola, buenos d\u00edas"):
        assert phone(world, "silent", line)["reply"] == REFUSAL, line
    assert phone(world, "silent", "ajuda")["reply"].startswith("Commands:\n/pending"), "a help line in words is the fixed list for this sender, as it was"      # validate: allow english-only -- the line under test
    assert calls == []


def test_the_phone_reply_has_no_slash_command_and_no_internal_id(world, monkeypatch):
    calls_of(world, monkeypatch)
    for who in ("maintainer", "nosend", "bare", "plain"):
        reply = phone(world, who, "hello")["reply"]
        assert "/" not in reply and not re.search(r"\d", reply) and "@" not in reply, who
        assert len(reply.splitlines()) <= 9


def test_the_reply_is_stored_like_any_code_reply_and_opens_no_request(world, monkeypatch):
    calls_of(world, monkeypatch, "pt-BR")
    out = phone(world, "maintainer", "Ola")
    assert out["request_id"] is None and out["pending_id"] is None and out["ran"] is False and out["queued"] is False
    ctx = ops_core.context(world["path"])
    rows = ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=50)
    assert [(r["role"], r["text"]) for r in rows[-2:]] == [("user", "Ola"), ("assistant", PT_MAINTAINER)]


def test_on_the_page_the_greeting_has_no_phone_only_line(world, monkeypatch):
    calls_of(world, monkeypatch)
    reply = ops.say(world["path"], "hello", channel="page")["reply"]
    assert reply.startswith("Hello! Here is what I can do for you now:\n") and "approve a card by replying" not in reply and "ask in your own words" not in reply


def test_off_a_phone_a_help_line_keeps_the_list_of_commands_and_a_greeting_gets_the_summary(world, monkeypatch):
    calls_of(world, monkeypatch)
    assert ops.say(world["path"], "help", channel="chat")["reply"] == st.load("operations").chat_help()
    assert ops.say(world["path"], "hello", channel="chat")["reply"].startswith("Hello! Here is what I can do for you now:")


def test_the_phones_fixed_help_names_no_configuration_key():
    phrases = st.load("phrases")
    for tag in ("en", "pt-BR"):
        text = phrases.text("HELP", {"language": tag})
        assert "channels" not in text and text.endswith({"en": "depends on your permissions.", "pt-BR": "dependem das suas permiss\u00f5es."}[tag]), tag


def test_vacuity_the_oracle_catches_a_summary_that_names_a_family_the_policy_lacks(world, monkeypatch):
    calls_of(world, monkeypatch)
    planted = EN_NO_SEND + "\n- draft and send e-mails, each one only after you approve it"
    assert phone(world, "nosend", "hi")["reply"] != planted
    assert "send e-mails" in EN_MAINTAINER and "send e-mails" not in EN_NO_SEND
