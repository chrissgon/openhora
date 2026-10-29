"""A line that is a request of its own is served, and the router's open question stays open (slice S4b, decision of 2026-10-22; runtime/ops_natural.py `recognises`,
runtime/ops_say.py `_turn`, runtime/messaging_bridge.py `_handle`).

The maintainer met it live on Telegram: the planning agent had asked a question, and five minutes later "mostra minha agenda" came back as the sentence that says the line was taken as
the answer to question #36, followed by the question again. S4 (#515) had bound the question to its asker for an hour, but `recognises` left every tier-1 READ ("liste meus emails",
"mostre os agentes") out of the lines that are new, on the thought that a read may be a one-word answer. A read of the person's own is a request. The rule, tested here with
the REAL operations layer and the real bridge on the chat tree (a stand-in router, a stand-in messenger, a stand-in clock), and, for a sender the interpreter reads, with a
stand-in model:

  1. a tier-1 form (a list or any other read included), a typed command, a reminder in words, an approve word for the card that is the last message, and a line the interpreter
     maps to an operation are each served, and the question is unchanged: still open, still bound to its asker, its request still `requested`, no new request, no sentence
     about it added to the reply (decision: no note, so that no reply carries a second subject);
  2. a plain answer ("o da caixa do Gmail") is still taken as the answer, and costs no second model call;
  3. a reply (the reply gesture) to the question's own message is the answer, whatever the line is;
  4. another sender's line is never this sender's answer, and a request of theirs is served as theirs.

Every expectation is a literal of this file. Each rule has a vacuity case that plants the old rule (or its opposite) and shows the same oracle then fails. Offline, no model,
no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_request_not_answer.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_chat import FLOW, reply
from test_interpret_router_frame import FRAME, HEAD, ask as ask_frame, bound, rig, say as say_as, spy_routes, spy_runs, text, world  # noqa: F401  (the interpreter's rig and its world)
from test_messaging_queue import settle
from test_router_question_phone import LINE, TEMPLATE, chat_tree, phone  # noqa: F401  (the bridge over the chat tree, with a stand-in router)
from test_router_question_stale import ANSWER, OWNER, STAFF, Wall, ask, open_questions, states, wall  # noqa: F401
from test_sender_profiles import POLICIES, accept
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
natural = st.load("natural")
natural_writes = st.load("natural_writes")
phrases = st.load("phrases")

TAKEN = "Tomei isso como resposta à pergunta #{id}."  # validate: allow english-only -- the Portuguese sentence under test
PLAIN_ANSWER = "o da caixa do Gmail"  # validate: allow english-only -- a line the person types in Portuguese
AGENTS = "agents:\n- name planning, pack planning"
NO_RIGHT = "Você ainda não tem permissão para isso por aqui."  # validate: allow english-only -- the Portuguese sentence under test
NOT_DONE = "Não consegui concluir isso."  # validate: allow english-only -- the Portuguese sentence under test
LISTING = "northwind-shop: #1 pergunta do assistente"  # validate: allow english-only -- the Portuguese sentence under test
NO_REMINDERS = "northwind-shop: nenhum lembrete pendente."  # validate: allow english-only -- the Portuguese sentence under test
WHICH_TIME = "Qual horário você quer: amanhã,"  # validate: allow english-only -- the Portuguese sentence under test

# (the line, how the reply to it begins): each is a request of its own to a phone whose owner holds the groups of POLICIES["owner"]
REQUESTS = [
    ("mostre os agentes", AGENTS),  # validate: allow english-only -- a line the person types in Portuguese
    ("quanto gastei hoje", "since: "),  # validate: allow english-only -- a line the person types in Portuguese
    ("mostra minha agenda", NOT_DONE),  # validate: allow english-only -- the line of the live case
    ("liste meus emails", NOT_DONE),  # validate: allow english-only -- a line the person types in Portuguese
    ("quais as fontes", NO_RIGHT),  # validate: allow english-only -- a line the person types in Portuguese
    ("/pending", LISTING),
    ("/status", "Pedidos abertos: 1."),  # validate: allow english-only -- the Portuguese sentence under test
]
READS = [line for line, _ in REQUESTS if not line.startswith("/")]
TAKEN_BY_THE_OLD_RULE = [line for line in READS if line != "quais as fontes"]      # the one that a missing group refuses before `say` is served the same way under both rules


def unchanged(phone, question):
    """The question is as the asker left it: open, the only one, its request still `requested`, bound (so that the next plain line of the asker still answers it)."""
    assert [q["id"] for q in open_questions(phone)] == [question["id"]]
    assert ops.pending(phone.path, question["id"])["status"] == "open"
    assert states(phone)[question["task_id"]] == "requested"
    assert len(states(phone)) == 1, "no new request was made"
    ctx = ops_core.context(phone.path)
    assert st.load("ops_say")._bound_question(ctx, f"telegram:{OWNER}") == question["id"]


def without_the_calendar_forms(monkeypatch):
    """The planted fault of the live line: `natural.match` as before the calendar nouns were in the `items` forms (no form for a line that names the agenda)."""
    real = natural.match
    monkeypatch.setattr(natural, "match", lambda line, languages=None: None if "agenda" in line else real(line, languages))


def old_rule(ctx, said, channel, sender):
    """`recognises` as it was before S4b: a tier-1 form that is a read is NOT a request (it may be the answer). The planted fault of the vacuity cases."""
    found = natural.match(said)
    if found is not None:
        return natural.class_of(found["op"]) != "R"
    return ops_natural.peek(ctx, said, channel, sender) or natural.candidate(said) is not None


def served(phone, wall, line):
    """The question, the replies to `line` typed by the owner five minutes after it was asked."""
    question = ask(phone, "pt-BR")
    wall.later(300)
    before = len(phone.texts(OWNER))
    plans = len([c for c in phone.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm"])
    phone.say(OWNER, line)
    if len([c for c in phone.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm"]) > plans:      # D5 is tested in test_plan_confirm*.py and test_messaging_plan_confirm.py: the read asks first, and the owner says "sim" to the question
        before = len(phone.texts(OWNER))
        phone.say(OWNER, "sim")
    return question, phone.texts(OWNER)[before:]


# --- 1. a request of its own is served and the question is unchanged ------------------------------------------------------------------


@pytest.mark.parametrize("line,begins", REQUESTS)
def test_a_request_of_its_own_is_served_and_the_open_question_is_untouched(phone, wall, line, begins):
    question, said = served(phone, wall, line)
    assert len(said) == 1 and said[0].startswith(begins), said
    assert phrases.text("ANSWER_TAKEN", {"language": "pt-BR"}, id=question["id"]) not in said[0]
    assert "pergunta #" not in said[0] and "continua aberta" not in said[0], "no note about the question is added to the reply"  # validate: allow english-only -- the Portuguese words under test
    unchanged(phone, question)


@pytest.mark.parametrize("line", TAKEN_BY_THE_OLD_RULE)
def test_vacuity_the_old_rule_takes_a_tier_1_read_as_the_answer_and_the_same_oracle_sees_it(phone, wall, monkeypatch, line):
    monkeypatch.setattr(ops_natural, "recognises", old_rule)
    question, said = served(phone, wall, line)
    assert said[0].startswith(TAKEN.format(id=question["id"])), said[0]
    with pytest.raises(AssertionError):
        unchanged(phone, question)


def test_a_command_of_the_table_is_never_the_answer_with_or_without_the_rule(phone, wall, monkeypatch):
    """A typed command is read before any question (ops_say._turn); the old rule changes nothing for it, and the oracle sees the same reply."""
    monkeypatch.setattr(ops_natural, "recognises", old_rule)
    question, said = served(phone, wall, "/pending")
    assert said[0].startswith(LISTING) and TAKEN.format(id=question["id"]) not in said[0]
    unchanged(phone, question)


def test_an_approve_word_decides_the_card_that_is_the_last_message_and_the_question_is_untouched(phone, wall):
    """A card word (S2) is read by the bridge before `say`. The plan card of another request is the last message sent to the chat; the question was asked before it."""
    question = ask(phone, "pt-BR")
    other = ops.request(phone.path, "another request of the project")["request"]
    ops.route(phone.path, other, flow="demo")
    phone.bridge.tick()
    assert settle(phone)
    before = len(phone.texts(OWNER))
    phone.say(OWNER, "aprovo")
    assert phone.texts(OWNER)[before:] == ["#2 aprovada."]  # validate: allow english-only -- the Portuguese sentence under test
    assert [q["id"] for q in open_questions(phone)] == [question["id"]] and ops.pending(phone.path, question["id"])["status"] == "open"
    assert states(phone)[question["task_id"]] == "requested" and states(phone)[other] == "planned"


def test_vacuity_the_same_word_with_no_card_last_is_the_answer_of_a_question_that_is_open(phone, wall):
    """With the question as the last message and no card, "aprovo" decides nothing and is a plain line: the answer (this is what the card test above is not)."""
    question, said = served(phone, wall, "aprovo")
    assert said[0].startswith(TAKEN.format(id=question["id"]))


# --- 2. a plain answer is still the answer, and costs no second call ------------------------------------------------------------------


def test_a_plain_answer_is_still_taken_as_the_answer(phone, wall):
    question = ask(phone, "pt-BR")
    reply(phone.tree, FLOW, "router-reply-2.md")
    wall.later(300)
    before = len(phone.texts(OWNER))
    phone.say(OWNER, PLAIN_ANSWER)
    said = phone.texts(OWNER)[before:]
    assert len(said) == 1 and said[0].startswith(TAKEN.format(id=question["id"])), said
    assert open_questions(phone) == []


def test_vacuity_a_rule_that_recognises_every_line_takes_the_plain_answer_for_a_request(phone, wall, monkeypatch):
    monkeypatch.setattr(ops_natural, "recognises", lambda *a, **k: True)
    question, said = served(phone, wall, PLAIN_ANSWER)
    assert TAKEN.format(id=question["id"]) not in said[0]


# --- 3. a reply to the question's own message is the answer ----------------------------------------------------------------------------


@pytest.mark.parametrize("line", READS)
def test_a_reply_to_the_question_message_is_the_answer_even_when_the_line_is_a_request(phone, wall, line):
    question = ask(phone, "pt-BR")
    sent = phone.bridge.last_message[OWNER]
    wall.later(300)
    reply(phone.tree, FLOW, "router-reply-2.md")
    phone.bridge.handle({"update_id": 2, "sender": OWNER, "chat": OWNER, "private": True, "text": line, "action": None, "action_ref": None, "reply_to": sent})
    assert settle(phone)
    assert open_questions(phone) == [] and ops.pending(phone.path, question["id"])["status"] != "open", "the reply gesture answered it"


@pytest.mark.parametrize("line", TAKEN_BY_THE_OLD_RULE)
def test_vacuity_the_same_line_without_the_reply_gesture_is_served_and_leaves_the_question_open(phone, wall, line):
    question, said = served(phone, wall, line)
    unchanged(phone, question)


# --- 4. another sender --------------------------------------------------------------------------------------------------------------


def test_another_senders_request_is_served_as_theirs_and_their_plain_line_is_nobodys_answer(phone, wall):
    question = ask(phone, "pt-BR")
    wall.later(300)
    before = {OWNER: len(phone.texts(OWNER)), STAFF: len(phone.texts(STAFF))}
    phone.say(STAFF, "mostre os agentes")  # validate: allow english-only -- a line the person types in Portuguese
    phone.say(STAFF, PLAIN_ANSWER)
    theirs = phone.texts(STAFF)[before[STAFF]:]
    assert len(theirs) == 2 and theirs[0].startswith(NO_RIGHT), "their own request is answered by their own profile (read-limited): a refusal, not the owner's list"
    assert theirs[1].startswith("Perguntas:"), "and their plain line is a new request of theirs, which the router asks about"  # validate: allow english-only -- the Portuguese label under test
    assert not any(TAKEN.format(id=question["id"]) in t for t in theirs), "a line of another sender is never the answer to this sender's question"
    assert phone.texts(OWNER)[before[OWNER]:] == [], "nothing was said to the asker"
    assert ops.pending(phone.path, question["id"])["status"] == "open" and states(phone)[question["task_id"]] == "requested"


def test_vacuity_the_same_plain_line_from_the_asker_is_the_answer(phone, wall):
    question, said = served(phone, wall, PLAIN_ANSWER)
    assert said[0].startswith(TAKEN.format(id=question["id"]))


# --- the interpreter's senders -------------------------------------------------------------------------------------------------------


def test_a_tier_1_read_of_a_sender_the_interpreter_reads_is_served_by_code_with_no_model_call_and_the_question_stays_open(rig):
    pending_id, _ = ask_frame(rig)
    spy_routes(rig)
    spy_runs(rig)
    out = say_as(rig, "owner", "mostre os agentes")  # validate: allow english-only -- a line the person types in Portuguese
    assert out["reply"] == "RUN-REPLY" and rig.spy == [{"run": "agents", "args": {}}], rig.spy
    assert rig.calls == [], "code took the line: the model was not called"
    assert bound(rig) == pending_id and ops.pending(rig.world["path"], pending_id)["status"] == "open"


def test_vacuity_under_the_old_rule_the_same_read_costs_a_model_call_and_the_model_decides(rig):
    pending_id, _ = ask_frame(rig)
    spy_routes(rig)
    spy_runs(rig)
    rig.monkeypatch.setattr(ops_natural, "recognises", old_rule)
    rig.says["text"] = text("answer", answers_item="i1")
    out = say_as(rig, "owner", "mostre os agentes")  # validate: allow english-only -- a line the person types in Portuguese
    assert len(rig.calls) == 1 and [(row["said"], row["answer_to"]) for row in rig.spy] == [("mostre os agentes", pending_id)]  # validate: allow english-only -- a line the person types in Portuguese
    assert out["reply"].startswith("I took that as the answer")


def test_the_live_line_is_served_as_the_calendar_list_by_code_with_no_model_call_and_the_question_stays_open(rig):
    """The line of the maintainer's Telegram test: a tier-1 form since S4b, so the model is not asked and cannot call it the answer."""
    pending_id, _ = ask_frame(rig)
    spy_routes(rig)
    spy_runs(rig)
    rig.says["text"] = text("answer", answers_item="i1")      # a model that would call it the answer is never asked
    out = say_as(rig, "owner", "mostra minha agenda")  # validate: allow english-only -- the line of the live case
    assert out["reply"] == "RUN-REPLY" and rig.spy == [{"run": "items", "args": {}}], rig.spy
    assert rig.calls == [], "no model call"
    assert bound(rig) == pending_id and ops.pending(rig.world["path"], pending_id)["status"] == "open"
    assert natural_writes.items_kind("mostra minha agenda") == "calendar"  # validate: allow english-only -- the line of the live case


def test_a_line_the_interpreter_maps_to_an_operation_is_served_and_the_question_stays_open_in_one_call(rig):
    pending_id, _ = ask_frame(rig)
    spy_routes(rig)
    spy_runs(rig)
    rig.says["text"] = text("op", op="items", slots={})
    out = say_as(rig, "owner", "enseña mi agenda de la semana")  # validate: allow english-only -- a line in a language with no tier-1 table
    assert out["reply"] == "RUN-REPLY" and rig.spy == [{"run": "items", "args": {}}], rig.spy
    assert [c["user"] for c in rig.calls] == [HEAD + FRAME + "\nline: enseña mi agenda de la semana"], "one call, with the frame"  # validate: allow english-only -- a line in a language with no tier-1 table
    assert bound(rig) == pending_id and ops.pending(rig.world["path"], pending_id)["status"] == "open"


def test_a_plain_answer_of_a_sender_the_interpreter_reads_costs_one_call_and_no_second(rig):
    pending_id, _ = ask_frame(rig)
    spy_routes(rig)
    rig.says["text"] = text("answer", answers_item="i1")
    out = say_as(rig, "owner", "the second hall, the shelf at the back")
    assert out["reply"] == "I took that as the answer to question #{}.\n\nROUTED".format(pending_id)
    assert len(rig.calls) == 1, "the model's one call decided it; nothing asked again"
