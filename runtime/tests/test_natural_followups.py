"""The follow-ups of the independent review of package NR-2 (PR #477, second round): a reminder to bring back that the router chose is never brought back at once, a
choice of a file offered in one project is never answered in another, a profile that lists `ask-mail` belongs to one sender, the yes and no words of the language data
count on every path, "help" in words is answered for a sender who may not talk, an operation the router named on a queued request is answered and not dropped, a routed
forget is confirmed in the conversation's own shell as in the terminal, and a question the page left open is swept on expiry. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_followups.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_ask_mail import ASK_ONLY, MAILER, PROFILES as MAIL_PROFILES
from test_ask import tree, two, write_config  # noqa: F401
from test_messaging_ask import wait_for
from test_messaging_natural_ops import rig  # noqa: F401
from test_ops_natural import KEY, OPERATION, OWNER, READER, NOTALK, docs, phone, router_says, say, with_senders, world  # noqa: F401

ops = st.load("ops")
ops_say = st.load("ops_say")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
drafts = st.load("drafts")
natural = st.load("natural")
phrases = st.load("phrases")
project_config = st.load("project_config")


def reminders(world, status=None) -> list:
    ctx = ops_core.context(world["path"])
    rows = ctx["store"].reminders_list(ctx["conn"], None)
    return [r for r in rows if status is None or r["status"] == status]


def one_open_reminder(world) -> int:
    ops.remind(world["path"], "in 2h", "dentist", to=KEY["owner"], channel="terminal")
    return reminders(world, "open")[0]["id"]


# --- M-A: the router never brings a reminder back at once --------------------------------------------------------------------------------------


def test_a_reminder_to_bring_back_that_the_router_chose_is_not_brought_back_at_once_and_the_reply_is_the_command(world):
    with_senders(world)
    rid = one_open_reminder(world)
    ops.reminder_forget(world["path"], rid, channel="messaging", sender=KEY["owner"])
    before = [(r["id"], r["status"]) for r in reminders(world)]
    router_says(world, OPERATION.format(name="reminder-restore") + f"Argument id: {rid}\n")
    out = phone(world, "owner", f"what about number {rid} then")
    assert [(r["id"], r["status"]) for r in reminders(world)] == before, "nothing was restored from a choice no code can check"
    assert out["reply"] == phrases.phone("PHONE_RESTORE", None) and drafts.count() == 0, out["reply"]      # a phone is told where, never the command (LIVE-2)
    ops.reminder_restore(world["path"], channel="messaging", sender=KEY["owner"])      # the typed command is as it was
    assert len(reminders(world)) == len(before) + 1


# --- MINOR 2: a choice offered in another project is never answered here ------------------------------------------------------------------------


def test_a_choice_of_a_file_offered_in_another_project_is_never_answered_in_this_one(docs):
    ctx = ops_core.context(docs["path"])
    elsewhere = {"kind": "which", "line": "what does it say", "ids": ["alpha-secret"], "project": ops_natural.project_key("/elsewhere/project")}
    drafts.put("page", "", elsewhere, "ops", ttl=600)
    assert ops_natural.peek(ctx, "1", "page", None) is False and ops_natural.needs(ctx, "1", "page", None) is None
    assert ops_natural.take(docs["path"], ctx, "1", "page", None, {}) is None
    assert drafts.count() == 0, "any other line drops the draft"
    here = {"kind": "which", "line": "what does it say", "ids": ["lease-contract"], "project": ops_natural.project_key(docs["path"])}
    drafts.put("page", "", here, "ops", ttl=600)
    assert ops_natural.peek(ctx, "1", "page", None) is True


# --- MINOR 3: a profile that lists ask-mail belongs to one sender -------------------------------------------------------------------------------


def test_a_profile_with_ask_mail_named_by_two_senders_is_refused_and_one_per_sender_is_not(two):
    path = two["path"]
    write_config(path, policies={"mailer": MAIL_PROFILES["mailer"]}, messaging={"senders": {"telegram": [{"id": MAILER, "policy": "mailer"}, {"id": ASK_ONLY, "policy": "mailer"}]}})
    with pytest.raises(project_config.ConfigError, match="belongs to one sender"):
        project_config.load(path)
    write_config(path, policies={"mailer": MAIL_PROFILES["mailer"]},
                 messaging={"senders": {"telegram": [{"id": MAILER, "policy": "mailer"}], "other-app": [{"id": MAILER, "policy": "mailer"}]}})
    with pytest.raises(project_config.ConfigError, match="belongs to one sender"):
        project_config.load(path)      # the same id on another platform is another person
    write_config(path, policies={"mailer": MAIL_PROFILES["mailer"], "second": MAIL_PROFILES["mailer"]},
                 messaging={"senders": {"telegram": [{"id": MAILER, "policy": "mailer"}, {"id": ASK_ONLY, "policy": "second"}]}})
    assert project_config.load(path)["channels"]["senders"][f"telegram:{ASK_ONLY}"] == MAIL_PROFILES["mailer"]
    write_config(path, policies={"mailer": MAIL_PROFILES["mailer"], "asker": MAIL_PROFILES["asker"]},
                 messaging={"senders": {"telegram": [{"id": MAILER, "policy": "mailer"}, {"id": MAILER, "policy": "mailer"}, {"id": ASK_ONLY, "policy": "asker"},
                                                      {"id": MAIL_NO_ASK, "policy": "asker"}]}})
    assert project_config.load(path)["channels"]["senders"][f"telegram:{MAILER}"] == MAIL_PROFILES["mailer"], "one entry twice is one sender; a profile without ask-mail may be shared"


MAIL_NO_ASK = "55119000000012"


# --- MINOR 1: the yes and no words of the language data count on every path --------------------------------------------------------------------


def test_the_yes_and_no_words_of_the_language_data_are_the_engines_own_on_a_confirmation_and_on_nothing_else():
    confirm, forget, time = {"need": "confirm"}, {"need": "forget"}, {"need": "time"}
    for word in ("sí", "Sí.", "はい", "oui", "да"):      # validate: allow english-only -- words of other languages are the input under test
        assert natural.engine_word(confirm, word) == "yes" and natural.engine_word(forget, word) == "yes", word
    for word in ("nein", "いいえ", "нет"):
        assert natural.engine_word(confirm, word) == "no", word
    assert natural.engine_word(time, "はい") == "はい", "only a question that asks for a confirmation reads them"
    assert natural.engine_word(confirm, "maybe") == "maybe" and natural.engine_word(confirm, None) is None


# --- NIT: "help" in words is answered for a sender who may not talk ----------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["help", "ajuda", "what can you do"])
def test_help_in_words_is_answered_with_the_messaging_help_for_a_sender_who_may_not_talk(rig, line):
    assert rig.bridge.needs(line, rig.project, READER) is None, "it needs no group of its own"
    rig.bridge.handle(rig.update(READER, line))
    assert wait_for(lambda: len(rig.sent()) == 1), line
    assert rig.sent()[0]["message"]["text"] == phrases.text("HELP", None) and st.calls(rig.world["adapter"]) == []
    rig.bridge.handle(rig.update(READER, "Which market first?"))
    assert wait_for(lambda: len(rig.sent()) == 2) and "not enabled" in rig.sent()[1]["message"]["text"], "a plain line still needs talk"


# --- NIT: an operation named for a queued request is answered ----------------------------------------------------------------------------------


def test_an_operation_the_router_named_for_a_queued_request_is_answered_and_the_request_is_cancelled(docs):
    import ops_core as core
    request = ops.request(docs["path"], "show me what you hold please")["request"]
    router_says(docs, OPERATION.format(name="sources"))
    with core._route_lock(ops_core.context(docs["path"])["cfg"]):
        assert ops.route(docs["path"], request, channel="page")["queued"] is True
    done = ops.route_queued(docs["path"])
    assert done["routed"] == "route" and done["operation"] == "sources" and done["pending_id"] is None, done
    answered = [m["text"] for m in ops.conversation(docs["path"])["messages"] if m["role"] == "assistant"]
    assert any(t.startswith("- lease-contract (file, ") for t in answered), answered
    assert ops.status(docs["path"])["requests"][0]["state"] == "cancelled" and ops.route_queued(docs["path"])["routed"] is None


# --- NIT: a routed forget is confirmed in the conversation's own shell as in the terminal -------------------------------------------------------


def test_a_reminder_to_forget_that_the_router_chose_is_confirmed_in_the_conversations_own_shell(world):
    with_senders(world)
    rid = one_open_reminder(world)
    router_says(world, OPERATION.format(name="reminder-forget") + f"Argument id: {rid}\n")
    asked = ops.say(world["path"], f"esse lembrete {rid} pode sair", channel="chat")      # validate: allow english-only -- a Portuguese line is the input under test
    assert "Cancel reminder #" in asked["reply"] and reminders(world, "open"), asked["reply"]
    done = ops.say(world["path"], "yes", channel="chat")
    assert "cancel" in done["reply"].lower() or "forgot" in done["reply"].lower() or str(rid) in done["reply"], done["reply"]
    assert reminders(world, "open") == [] and drafts.count() == 0


# --- NIT: a question the page left open is swept on expiry -------------------------------------------------------------------------------------


def test_a_question_about_a_reminder_the_page_left_open_is_swept_when_it_expires(world, monkeypatch):
    with_senders(world)
    rid = one_open_reminder(world)
    router_says(world, OPERATION.format(name="reminder-forget") + f"Argument id: {rid}\n")
    say(world, f"forget number {rid} now")
    assert drafts.count() == 1
    clock = {"t": ops_natural.monotonic()}
    monkeypatch.setattr(ops_natural, "monotonic", lambda: clock["t"] + ops_natural.DRAFT_TTL + 1)
    ctx = ops_core.context(world["path"])
    assert ops_natural.peek(ctx, "yes", "page", None) is False
    assert drafts.count() == 0, "swept, not only ignored"
    assert reminders(world, "open"), "and nothing was cancelled"


# --- L51: the words of a reminder are in the reminders table and in no reader's conversation --------------------------------------------------------------


SECRET = "trocar o filtro do ar"      # validate: allow english-only -- a Portuguese errand is the input under test
SPANISH_LINE = "recuerdame el martes a las 16 recoger el paquete en la porteria"
SPANISH_WORDS = "recoger el paquete en la porteria"


def seen_by_mcp(rig) -> list:
    return [m["text"] for m in ops.conversation(rig.project["path"], channel="mcp")["messages"]]


def test_the_question_of_a_routed_forget_shows_the_words_to_the_chat_and_the_conversation_keeps_a_neutral_word(rig):
    ops.remind(rig.project["path"], "in 2h", SECRET, to=KEY["owner"], channel="terminal")
    rid = [r for r in ops.reminders_read(rig.project["path"], channel="terminal")["open"]][0]["id"]
    router_says(rig.world, OPERATION.format(name="reminder-forget") + f"Argument id: {rid}\n")
    rig.bridge.handle(rig.update(OWNER, f"esse lembrete {rid} pode sair"))      # validate: allow english-only -- a Portuguese line is the input under test
    assert wait_for(lambda: len(rig.sent()) == 1 and not rig.bridge.exclusive)
    assert SECRET in rig.sent()[0]["message"]["text"] and rig.sent()[0]["message"]["text"].startswith("Cancel reminder #"), "the chat that asked reads the words"
    assert not any(SECRET in t for t in seen_by_mcp(rig)), seen_by_mcp(rig)
    rig.bridge.handle(rig.update(OWNER, "yes"))
    assert wait_for(lambda: len(rig.sent()) == 2)
    assert ops.reminders_read(rig.project["path"], channel="terminal")["open"] == []
    assert not any(SECRET in t for t in seen_by_mcp(rig)) and not any(SECRET in m["text"] for m in ops_core.context(rig.project["path"])["store"].messages_list(
        ops_core.context(rig.project["path"])["conn"], ops_say.CONVERSATION, limit=500) if m["role"] == "assistant")


def test_a_reminder_in_a_language_no_table_ships_is_shown_to_no_reader_but_the_persons_own_shell_and_never_reaches_the_routers_memory(rig):
    router_says(rig.world, OPERATION.format(name="remind") + f"Argument text: {SPANISH_WORDS}\nWhen: 2026-10-20 16:00\n")
    rig.bridge.handle(rig.update(OWNER, SPANISH_LINE))
    assert wait_for(lambda: len(rig.sent()) == 1 and not rig.bridge.exclusive)
    router_says(rig.world, "Route: none (direct)\nNext: nothing\n")
    rig.bridge.handle(rig.update(OWNER, "yes"))
    assert wait_for(lambda: len(rig.sent()) == 2)
    assert [r["text"] for r in ops.reminders_read(rig.project["path"], channel="terminal")["open"]] == [SPANISH_WORDS]
    for channel in ("mcp", "messaging", None):
        texts = [m["text"] for m in ops.conversation(rig.project["path"], channel=channel, sender=KEY["owner"])["messages"]]
        assert not any(SPANISH_WORDS in t or "paquete" in t for t in texts), (channel, texts)
        assert phrases.text("NAT_PRIVATE_LINE", None) in texts, channel
    page = [m["text"] for m in ops.conversation(rig.project["path"], channel="page")["messages"]]
    assert SPANISH_LINE in page, "the person's own shell shows their line"
    ctx = ops_core.context(rig.project["path"])
    rows = ctx["store"].messages_list(ctx["conn"], ops_say.CONVERSATION, limit=500)
    assert "paquete" not in ops_say.chat_memory(rows, set()), "the router's memory never carries the words"
