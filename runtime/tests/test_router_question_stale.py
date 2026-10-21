"""A question the router left open does not swallow the next line on a messaging app (package LIVE-2, reworked by slice S4 and decision 229 (1) of 2026-10-20; runtime/ops_say.py
`_open_question`, `_bound_question`, `_turn`, runtime/pending_items.py, runtime/ops_natural.py `recognises`, runtime/phrases.py ANSWER_TAKEN and ASK_NEXT_PHONE).

The maintainer met it live: a question stayed open from the day before; a new, unrelated line ("Salvar no drive") was taken as its ANSWER and the router asked yesterday's
question again. Three rules, tested here with the REAL operations layer on the chat tree, a stand-in router and a stand-in clock:

  1. on a messaging app an open question of the router is bound to the sender it was asked of and is answered by that sender's plain line only within
     pending_items.ROUTER_WINDOW (one hour, a constant); older, the next plain line is a new request and the old request is NOT cancelled by code (S4, decision 229 (1)); the
     other channels keep the question until it is answered or cancelled; the binding itself (another sender, a restart) is tested in test_router_binding.py;
  2. even within the window, a line that code recognises as a request of its own (a write to the person's accounts, a reminder, a cancel...) is a NEW line, never the answer;
     a read such as "progress" and a plain sentence may still be the answer;
  3. when a line is taken as the answer, the reply says so in the project's language ("I took that as the answer to question #2.") and the footer is a plain phrase, not "/new".

Offline, no model, no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_router_question_stale.py
"""
from __future__ import annotations

import datetime

import pytest

import standin_tree as st
from test_chat import FLOW, reply
from test_router_question_phone import LINE, TEMPLATE, chat_tree, phone  # noqa: F401  (the bridge over the chat tree, with a stand-in router)
from test_messaging_queue import settle
from test_sender_profiles import OWNER, STAFF

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")
ops_natural = st.load("ops_natural")
pending_items = st.load("pending_items")
natural = st.load("natural")
phrases = st.load("phrases")

ANSWER = "an event, 13:00, the Linden clinic, Aurora calendar"
UNRELATED = "Salvar no drive"      # the line of the live case: since ATT-3 a save form that code reads as a request of its own, never the answer
PLAIN = "tell me something else about the project today"      # a plain sentence no form of code reads: only the window decides
WRITE = "marca dentista quinta às 10h no google"      # validate: allow english-only -- a line the person types in Portuguese
READ = "what files do you have?"      # a tier-1 read: a form of code, not a request
REMINDER = "me lembra amanhã às 9 de regar as plantas"      # validate: allow english-only -- a line the person types in Portuguese


class Wall:
    """The clock of the age of a question, stood in: `now` moves with `later`."""

    def __init__(self, monkeypatch):
        self.moment = datetime.datetime.now(datetime.timezone.utc)
        monkeypatch.setattr(ops_say, "_question_clock", lambda: self.moment)

    def later(self, seconds):
        self.moment = self.moment + datetime.timedelta(seconds=seconds)


@pytest.fixture
def wall(monkeypatch):
    return Wall(monkeypatch)


def open_questions(phone):
    ctx = ops_core.context(phone.path)
    return [i for i in ctx["store"].pending_list(ctx["conn"], "open") if i["kind"] == "question"]


def states(phone):
    ctx = ops_core.context(phone.path)
    return {t["id"]: t["state"] for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] is None}


def ask(phone, language="en"):
    phone.configure(language)
    reply(phone.tree, TEMPLATE)
    phone.say(OWNER, LINE)
    [question] = open_questions(phone)
    return question


# --- 3. the answer is said to be one --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("language,taken", [("en", "I took that as the answer to question #{id}."), ("pt-BR", "Tomei isso como resposta à pergunta #{id}.")])  # validate: allow english-only -- the pt-BR sentence
def test_a_line_taken_as_the_answer_says_so_in_the_projects_language_with_no_slash_hint(phone, wall, language, taken):
    question = ask(phone, language)
    reply(phone.tree, FLOW, "router-reply-2.md")
    wall.later(60)
    phone.say(OWNER, ANSWER)
    said = phone.texts(OWNER)[-1]
    assert said.startswith(taken.format(id=question["id"])) and "/new" not in said, said
    assert phrases.text("ANSWER_TAKEN", {"language": language}, id=question["id"]) == taken.format(id=question["id"])
    assert open_questions(phone) == [], "the question was answered"


def test_the_footer_of_a_question_on_a_phone_is_a_plain_phrase_and_the_other_channels_keep_the_slash_line(phone):
    phone.configure("en")
    reply(phone.tree, TEMPLATE)
    out = ops.say(phone.path, LINE)
    assert out["reply"].endswith(phrases.text("ASK_NEXT", None)) and "/new" in out["reply"], "the terminal and the page are as they were"
    phone.say(OWNER, LINE)
    assert phone.texts(OWNER)[0].endswith(phrases.text("ASK_NEXT_PHONE", None)) and "/new" not in phone.texts(OWNER)[0]


# --- 1. the window ----------------------------------------------------------------------------------------------------------------


def test_within_one_hour_the_askers_plain_line_answers_the_question(phone, wall):
    """Decision 229 (1): the window is one hour (3600 s, the test's own literal), bound to the asker."""
    question = ask(phone)
    reply(phone.tree, FLOW, "router-reply-2.md")
    wall.later(3600 - 1)
    phone.say(OWNER, ANSWER)
    assert phone.texts(OWNER)[-1].startswith(phrases.text("ANSWER_TAKEN", None, id=question["id"])) and open_questions(phone) == []


def test_after_the_window_the_next_plain_line_is_a_new_request_and_the_old_request_stays_open_with_no_notice(phone, wall):
    """Decision 229 (1): nothing is cancelled by code when the hour runs out; the old request and its question stay as they were."""
    question = ask(phone)
    old = question["task_id"]
    texts_before = len(phone.texts(OWNER))
    wall.later(3600 + 1)
    reply(phone.tree, FLOW, "router-reply.md")
    phone.say(OWNER, "a plain line about something else entirely")
    said = phone.texts(OWNER)[texts_before:]
    assert len(said) == 1 and phrases.text("ANSWER_TAKEN", None, id=question["id"]) not in said[0], "one reply, and it does not say the line answered anything"
    assert states(phone)[old] == "requested", "the old request is not closed by code"
    assert [q["id"] for q in open_questions(phone)] == [question["id"]], "and its question is still open"
    assert ops.pending(phone.path, question["id"])["status"] == "open"
    assert len(phone.texts(OWNER)) == texts_before + 1, "no notice about anything"


def test_the_window_is_a_documented_constant_of_one_hour():
    """Decision 229 (1): one hour, in the store that binds the question."""
    assert pending_items.ROUTER_WINDOW == 3600 and not hasattr(ops_say, "ROUTER_QUESTION_TTL")


def test_the_page_and_the_terminal_keep_a_question_until_it_is_answered_or_cancelled(phone, wall):
    """Decision 229 (1) leaves the other channels as they were: no window, the conversation's last request."""
    question = ask(phone)
    reply(phone.tree, FLOW, "router-reply-2.md")
    wall.later(3600 * 10)
    out = ops.say(phone.path, ANSWER, channel="page")
    assert out["reply"] is not None and phrases.text("ANSWER_TAKEN", None, id=question["id"]) not in out["reply"], "no sentence of the phone is added on the page"
    assert open_questions(phone) == []


def test_a_time_that_cannot_be_read_keeps_the_question_as_it_always_was(phone, wall):
    """Decision 229 (1): a binding whose time cannot be read still answers (the asker has it), as the store's unreadable time always did."""
    question = ask(phone)
    ctx = ops_core.context(phone.path)
    sender = f"telegram:{OWNER}"
    [binding] = pending_items.items((ops_natural.project_key(phone.path), "messaging", sender))
    binding["state"]["asked_at"] = "not a time"
    wall.later(3600 * 10)
    assert ops_say._open_question(ctx, "messaging", sender) == question["id"]


def test_a_reply_to_the_question_answers_it_two_hours_later_and_a_plain_line_does_not(phone, wall):
    """Decision 229 (1), "afterwards by reply-to": the ledger records the message the question went out in, so a reply gesture to it answers it at any age (the existing reply
    path), while a plain line after the hour is a new request and leaves it open."""
    question = ask(phone)
    sent = phone.bridge.last_message[OWNER]
    record = phone.bridge.ledger.by_message(OWNER, sent)
    assert record is not None and record["kind"] == "question" and record["pending_id"] == question["id"], "the ledger holds the message the question was sent in"
    wall.later(7200)
    reply(phone.tree, FLOW, "router-reply.md")
    phone.say(OWNER, "a plain line much later")
    assert [q["id"] for q in open_questions(phone)] == [question["id"]], "a plain line two hours later left the question open"
    reply(phone.tree, FLOW, "router-reply-2.md")
    phone.bridge.handle({"update_id": 2, "sender": OWNER, "chat": OWNER, "private": True, "text": ANSWER, "action": None, "action_ref": None, "reply_to": sent})
    assert settle(phone)
    assert open_questions(phone) == [] and ops.pending(phone.path, question["id"])["status"] != "open", "the reply to the question answered it"


# --- 2. a request of its own is a new line -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", [WRITE, "cancela o pedido 99"])
def test_within_the_window_a_line_that_code_recognises_as_a_request_is_new_and_the_question_stays_open(phone, wall, line):
    question = ask(phone, "pt-BR")
    wall.later(300)
    texts_before = len(phone.texts(OWNER))
    assert ops_natural.recognises(ops_core.context(phone.path), line, "messaging", f"telegram:{OWNER}") is True
    phone.say(OWNER, line)
    said = phone.texts(OWNER)[texts_before:]
    assert said and not any(phrases.text("ANSWER_TAKEN", {"language": "pt-BR"}, id=question["id"]) in t for t in said), said
    assert [q["id"] for q in open_questions(phone)] == [question["id"]], "the router's question is still waiting for its answer"


def test_a_reminder_line_and_a_write_line_are_requests_and_a_plain_sentence_and_a_read_are_not():
    ctx = {"cfg": {"language": "en"}}
    for line in (WRITE, REMINDER, "cancel request 3", "stop task 5", "add file 3"):
        assert ops_natural.recognises(ctx, line, "messaging", "telegram:1") is True, line
    for line in (ANSWER, "yes, an event", "the second one", "progress", "status", "what is running"):
        assert ops_natural.recognises(ctx, line, "messaging", "telegram:1") is False, line


def test_the_stale_question_is_also_dropped_for_a_state_question_and_the_natural_peek(phone, wall):
    """Decision 229 (1): once the hour is out, the asker's phone has no question open for the state and the natural peek; nothing is cancelled."""
    question = ask(phone)
    wall.later(3600 + 5)
    ctx = ops_core.context(phone.path)
    assert ops_say.asks_state(ctx, "status", "messaging", f"telegram:{OWNER}") is True, "no question is open for the phone any more: the state is answered"
    assert ops_say.asks_state(ctx, "status", "page") is False, "but it is for the page"
    assert ops_say.asks_natural(ctx, WRITE, "messaging", f"telegram:{OWNER}") is True
    assert open_questions(phone)[0]["id"] == question["id"], "asking only reads: nothing is cancelled, even when a line is taken"


def test_the_live_case_a_question_from_yesterday_is_not_the_answer_to_a_line_of_today(phone, wall):
    """Decision 229 (1): the live case; a question from yesterday is never the answer, and it is left open, not cancelled."""
    question = ask(phone, "pt-BR")
    wall.later(24 * 3600)
    reply(phone.tree, FLOW, "router-reply.md")
    before = len(phone.texts(OWNER))
    phone.say(OWNER, UNRELATED)
    assert not any(phrases.text("ANSWER_TAKEN", {"language": "pt-BR"}, id=question["id"]) in t for t in phone.texts(OWNER)[before:]), "the live line is a request of its own, whatever the age"
    phone.say(OWNER, PLAIN)
    said = phone.texts(OWNER)[before:]
    assert said and phrases.text("ANSWER_TAKEN", {"language": "pt-BR"}, id=question["id"]) not in said[0] and question["title"] not in said[0]
    assert states(phone)[question["task_id"]] == "requested" and ops.pending(phone.path, question["id"])["status"] == "open", "left as it was"


def test_a_read_with_a_question_open_is_not_handled_by_code_so_it_takes_the_route_lock_as_the_answer_it_may_be(phone, wall):
    """Decision 229 (1): the asker's open question is the one that counts, within the hour."""
    ask(phone)
    ctx = ops_core.context(phone.path)
    assert ops_say.asks_natural(ctx, READ, "messaging", f"telegram:{OWNER}") is False, "the one-word answer reaches the router, as it always did"
    assert ops_say.asks_natural(ctx, WRITE, "messaging", f"telegram:{OWNER}") is True, "a request of its own takes no route lock"
    assert ops_say.asks_natural(ctx, READ, "messaging", f"telegram:{STAFF}") is True, "another listed sender has no question: a read is a read"
    wall.later(3600 + 1)
    assert ops_say.asks_natural(ctx, READ, "messaging", f"telegram:{OWNER}") is True, "and once the question is stale a read is a read"
