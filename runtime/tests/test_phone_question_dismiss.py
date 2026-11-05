"""Turning a question down closes it, on a phone and everywhere (slice S14; runtime/ops_question.py, `ops.reject`, the bridge's `act`, `/discard` on a number that is no file).

The maintainer's live screen (a Portuguese project on Telegram): `/reject 14` on a question was answered in English with the layer's own words ("pending decision 14 is a question: reject
takes a plan, an acceptance or an effect"), `/discard 28` pointed to the card, and `/pending` listed each question by the kind and the title the code gave it (the router's own title, "the route
was not recognised"): nothing said what was asked, the old questions piled up, and the words were the platform's. Now `/reject <id>` (and `/discard <id>` on a number that is no file) closes a
question: the router's question is cancelled together with its request, by the cancel the conversation uses when code answers a request itself, when nothing else of the request is open; one
plain sentence answers; `/pending` says what is asked; and a plan is rejected as before.

THE ORACLE reads the phone's texts with phrase keys and their fields (runtime/tests/phrase_kit.py; the wording is pinned by the phrase snapshot) and this file's own literals (the internal words, the English function words). It never calls the code under test to decide what is
right. The vacuity cases plant the live lines of the maintainer's screen and show the same oracle flags them. Over the REAL operations layer on the chat tree with a stand-in router and a
stand-in messenger provider; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_question_dismiss.py
"""
from __future__ import annotations

import re

import pytest

import phone_said as ps
import phrase_kit as pk
import standin_tree as st
from test_chat import FLOW, reply
from test_chat import tree as chat_tree  # noqa: F401  (the chat tree fixture: a stand-in router)
from test_router_question_phone import LINE, TEMPLATE, phone  # noqa: F401  (the bridge over the chat tree)
from test_sender_profiles import OWNER, STAFF

ops = st.load("ops")
ops_question = st.load("ops_question")
ops_core = st.load("ops_core")
phrases = st.load("phrases")
PT = {"language": "pt-BR"}

PROSE = "I looked around and I am not sure what you want.\n"
INTERNAL = re.compile(r"\b(route|router|rota|rotas|roteador)\b|channels\.|\bflow-[a-z]|\bcore-[a-z]", re.I)
ENGLISH = re.compile(r"\b(the|is|not|reject|takes|an|acceptance|effect|pending decision)\b")      # the function words of the layer's English


def problems(text: str, portuguese: bool = True) -> list:
    """What is wrong with a phone's text: a word of the platform's internals and, for a Portuguese chat, the layer's English."""
    return ([f"internal {m.group(0)!r}" for m in INTERNAL.finditer(text)]
            + ([f"english {m.group(0)!r}" for m in ENGLISH.finditer(text) if text.startswith(("pending decision", "Pending decision"))] if portuguese else []))


def open_ids(phone) -> list:
    return [p["id"] for p in ops.pending(phone.path)["pending"]]


def requests(phone) -> list:
    return [r["state"] for r in ops.status(phone.path)["requests"]]


def ask(phone, template=TEMPLATE) -> int:
    """A line to the router that it answers with a question: the id of the pending decision it opened."""
    reply(phone.tree, template)
    phone.say(OWNER, LINE)
    return open_ids(phone)[-1]


# --- /reject on a question -------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("language,sentence", [("pt-BR", "Pergunta #{id} dispensada."), ("en", "Question #{id} dismissed.")])  # validate: allow english-only -- the Portuguese sentence under test
def test_reject_closes_the_question_and_cancels_its_request_with_one_plain_sentence(phone, language, sentence):
    phone.configure(language)
    qid = ask(phone)
    assert requests(phone) == ["requested"] and open_ids(phone) == [qid]
    phone.say(OWNER, f"/reject {qid}")
    assert phone.texts(OWNER)[-1] == sentence.format(id=qid)
    assert open_ids(phone) == [] and requests(phone) == ["cancelled"]
    assert problems(phone.texts(OWNER)[-1], language == "pt-BR") == []


def test_the_next_plain_line_after_a_dismissed_question_is_a_new_line_and_not_its_answer(phone):
    phone.configure("pt-BR")
    qid = ask(phone)
    phone.say(OWNER, f"/reject {qid}")
    reply(phone.tree, FLOW)
    phone.say(OWNER, "Qual mercado primeiro?")
    states = requests(phone)
    assert states[0] == "cancelled" and len(states) == 2 and states[1] != "cancelled", "a second request, the first stays cancelled"


def test_discard_on_a_number_that_is_no_file_closes_the_question_too(phone):
    phone.configure("pt-BR")
    qid = ask(phone)
    phone.say(OWNER, f"/discard {qid}")
    assert ps.alone(phone.texts(OWNER)[-1], "QUESTION_DISMISSED", PT, id=qid) and open_ids(phone) == [] and requests(phone) == ["cancelled"]
    assert "Use o card" not in phone.texts(OWNER)[-1], "not the old line that pointed to /pending"


def test_a_question_is_closed_without_the_card_it_was_asked_on(phone):
    """A question has no hash and no effect: the decision of a number the sender never got a card for is closed too (policy `reject-cancel` still decides who may)."""
    phone.configure("pt-BR")
    reply(phone.tree, TEMPLATE)
    asked = ops.say(phone.path, LINE)      # asked on the terminal: no chat was sent a card
    phone.say(OWNER, f"/reject {asked['pending_id']}")
    assert ps.alone(phone.texts(OWNER)[-1], "QUESTION_DISMISSED", PT, id=asked["pending_id"]) and requests(phone) == ["cancelled"]


def test_a_sender_without_the_reject_group_cannot_close_it(phone):
    """The staff profile may answer a question, not reject: the policy is asked as for any reject, and nothing changes."""
    phone.configure("pt-BR")
    qid = ask(phone)
    phone.say(STAFF, f"/reject {qid}")
    assert open_ids(phone) == [qid] and requests(phone) == ["requested"]
    assert ps.refused(phone.texts(STAFF)[-1], PT), phone.texts(STAFF)[-1]


def test_a_plan_is_rejected_as_before_and_its_request_is_cancelled(phone):
    phone.configure("pt-BR")
    reply(phone.tree, FLOW)
    planned = ops.say(phone.path, "Qual mercado primeiro?")
    phone.bridge.tick()
    phone.say(OWNER, f"/reject {planned['pending_id']}")
    assert ps.alone(phone.texts(OWNER)[-1], "REJECTED", PT, id=planned["pending_id"]) and requests(phone) == ["cancelled"]


# --- the operation: every channel -------------------------------------------------------------------------------------------------------------------------


def test_the_terminal_and_the_page_close_a_question_the_same_way_and_keep_their_english(phone):
    phone.configure("pt-BR")
    reply(phone.tree, TEMPLATE)
    asked = ops.say(phone.path, LINE)
    before = ops.pending(phone.path)["pending"]
    assert len(before) == 1 and pk.said(before[0]["title"], "TITLE_ROUTER_ASKS"), "the stored title is English: the page and the terminal list what they always did"
    out = ops.reject(phone.path, asked["pending_id"])
    assert out["resolution"] == "dismissed" and out["kind"] == "question" and out["request"] == asked["request_id"]
    assert asked["request_id"] in out["cancelled"] and asked["pending_id"] in out["pending"]
    assert ops.pending(phone.path)["pending"] == [] and requests(phone) == ["cancelled"]
    assert ops.pending(phone.path, asked["pending_id"])["status"] == "cancelled"


def test_a_decision_that_is_no_longer_open_is_refused_and_nothing_changes(phone):
    phone.configure("en")
    reply(phone.tree, TEMPLATE)
    asked = ops.say(phone.path, LINE)
    ops.reject(phone.path, asked["pending_id"])
    with pytest.raises(ops.OpsError) as refused:
        ops.reject(phone.path, asked["pending_id"])
    assert str(refused.value) == f"pending decision {asked['pending_id']} is cancelled, not open"


class Stub:
    """A store that holds one question and another open decision on its request: what `dismiss` reads, nothing else."""
    class StoreError(Exception):
        code = 1

    def __init__(self, others):
        self.others, self.cancelled = others, []

    def task_get(self, conn, task_id):
        return {"id": task_id, "parent_id": None}

    def tasks_list(self, conn, request):
        return [{"id": request, "parent_id": None}]

    def pending_list(self, conn, status, task_id):
        return [{"id": 5, "kind": "question"}] + [{"id": n, "kind": "plan"} for n in self.others]


def test_a_request_with_another_open_decision_is_not_cancelled_by_dismissing_one_question():
    ctx = {"store": Stub([6]), "conn": None, "cfg": {}}
    with pytest.raises(ops_core.OpsError) as refused:
        ops_question.dismiss(ctx, {"id": 5, "kind": "question", "status": "open", "task_id": 1})
    assert "was not dismissed" in str(refused.value) and ctx["store"].cancelled == []


# --- /pending in plain words -----------------------------------------------------------------------------------------------------------------------------


def listing(phone) -> str:
    phone.say(OWNER, "/pending")
    return next(t for t in phone.texts(OWNER) if t.startswith("northwind-shop: #"))


def test_pending_says_what_is_asked_and_what_was_not_understood_and_how_to_dismiss_in_portuguese(phone):
    phone.configure("pt-BR")
    reply(phone.tree, PROSE)
    unread = ops.say(phone.path, "algo sem sentido", channel="page")      # on a page an unreadable line stays open, as the maintainer's old ones did
    qid = ask(phone)
    shown = listing(phone)
    first, second, third = shown.split("\n")
    project, _, row = first.partition(": ")
    assert project == "northwind-shop" and pk.said(row, "PEND_NOT_UNDERSTOOD", PT, id=unread["pending_id"])
    assert pk.said(second, "PEND_QUESTION", PT, id=qid, text="Is this a reminder or an event of your calendar?") and pk.said(third, "PEND_DISMISS_TYPED", PT)
    assert all(problems(t) == [] for t in phone.texts(OWNER)), [t for t in phone.texts(OWNER) if problems(t)]


def test_pending_in_english_says_the_same_in_english(phone):
    phone.configure("en")
    qid = ask(phone)
    first, second = listing(phone).split("\n")
    project, _, row = first.partition(": ")
    assert project == "northwind-shop" and pk.said(row, "PEND_QUESTION", id=qid, text="Is this a reminder or an event of your calendar?") and pk.said(second, "PEND_DISMISS_TYPED")


def test_the_card_of_a_question_the_router_could_not_read_is_one_plain_sentence(phone):
    phone.configure("pt-BR")
    reply(phone.tree, PROSE)
    unread = ops.say(phone.path, "algo sem sentido", channel="page")
    phone.bridge.tick()
    [card] = [t for t in phone.texts(OWNER) if f"#{unread['pending_id']}" in t]
    blocks = card.split("\n\n")
    assert pk.said(blocks[0], "HEADER", PT, project="northwind-shop", kind=phrases.text("KIND_QUESTION", PT), id=unread["pending_id"])
    assert pk.said(blocks[1], "PEND_NOT_UNDERSTOOD_TITLE", PT) and pk.said(blocks[2], "PHONE_NOT_UNDERSTOOD", PT)
    assert problems(card) == [], card


def test_a_dismissed_question_leaves_the_list_and_the_empty_list_is_the_old_sentence(phone):
    phone.configure("pt-BR")
    qid = ask(phone)
    phone.say(OWNER, f"/reject {qid}")
    phone.say(OWNER, "/pending")
    assert ps.alone(phone.texts(OWNER)[-1], "NOTHING_WAITS", PT, name="northwind-shop")


def test_vacuity_the_maintainers_live_lines_fail_the_oracle_and_the_new_ones_pass():
    live = ["northwind-shop: #14 pergunta: A rota não foi reconhecida\n#25 pergunta: O roteador pergunta",  # validate: allow english-only -- the live lines of the maintainer's screen
            "pending decision 14 is a question: reject takes a plan, an acceptance or an effect"]
    assert all(problems(line) for line in live), "the planted old lines are noticed"
    assert problems("Pergunta #14 dispensada.") == [] and problems("northwind-shop: #14 pedido não entendido\nPara dispensar, responda: /reject <número>.") == []  # validate: allow english-only -- the Portuguese sentences under test
