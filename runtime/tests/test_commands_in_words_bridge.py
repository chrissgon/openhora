"""A command asked for in words is the typed command to the messaging bridge (slice S20, limits L54 and L64; runtime/messaging_bridge.py `line`, `say`, `project_line`), over
the stand-in operations object and the stand-in messenger of test_messaging.py. Offline, no model, no network; every name and number is invented.

The operations layer hands the bridge a typed line (`result["typed"]`) for a plain line that stands for a command (runtime/ops_natural.py `hand_over`). For a command the bridge
answers itself (`/reject`, `/release`, `/add`, `/discard`, `/pending`) the bridge then does what it does for the typed line, through the same call; for a command the table answers
(`/cancel`, `/stop-task`, `/retry`, `/attachments`, `/progress`) it says the command's reply as it says the typed one's. The stand-in records every call in its own list, so each case
counts the calls itself, and the same case with the typed line must make the same call (the "typed" cases).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_commands_in_words_bridge.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import json

import pytest

import standin_tree as st
from test_messaging import OPEN_POLICY, SENDER, decision, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)
from test_messaging_card_revise import Revise, mail_card
from test_messaging_card_words import GRANTED, HASH, approvals, rejections

shell_kit = st.load("shell_kit")

KEY = "telegram:" + SENDER


def hands_over(world, typed, reply=""):
    """The stand-in `say` answers every line with this typed line and this reply, as the operations layer does for a plain line that stands for a command."""
    world.fake.answers["say"] = lambda project, **kw: {"reply": reply, "request_id": None, "pending_id": None, "ran": False, "queued": False, "typed": typed}


def silence(world):
    """The texts the bridge sent, once the jobs it started have ended."""
    assert wait_for(lambda: not world.bridge.exclusive and all(not t.is_alive() for t in world.bridge.threads))
    return world.texts()


# --- a command the bridge answers itself: the typed line is handled as typed -------------------------------------------------------------------------------


def test_a_reject_said_in_words_makes_the_call_the_typed_reject_makes(world):
    world.items[5] = decision("plan", 5)
    world.items[6] = decision("plan", 6, plan_sha256="q" * 64)
    world.bridge.tick()
    world.fake.calls.clear()
    hands_over(world, "/reject 5")
    world.say("rejeite o plano 5")
    assert wait_for(lambda: rejections(world) == [5]) and silence(world)[-1] == "Rejected #5."
    by_words = [dict(c[2]) for c in world.calls("reject")]
    world.say("/reject 6")
    assert wait_for(lambda: rejections(world) == [5, 6]) and silence(world)[-1] == "Rejected #6."
    assert [dict(c[2]) for c in world.calls("reject")] == [by_words[0], dict(by_words[0], pending_id=6)], "the same keys, the same channel and sender, the second plan's own number"
    assert by_words == [{"pending_id": 5, "channel": "messaging"}] and approvals(world) == []      # the stand-in records the keywords the operation takes (no `sender`: the bridge passes it only to an operation that takes one)


def test_a_question_dismissed_in_words_needs_no_card_as_the_typed_reject_needs_none(world):
    world.items[3] = decision("question", 3, title="Which warehouse?")
    hands_over(world, "/reject 3")
    world.say("reject question 3")
    assert wait_for(lambda: rejections(world) == [3]) and silence(world)[-1] == "Question #3 dismissed."


def test_a_decision_said_in_words_that_was_never_sent_to_the_chat_is_the_typed_commands_refusal_and_nothing_is_called(world):
    world.items[5] = decision("plan", 5)      # no tick: no card was sent to this chat
    hands_over(world, "/reject 5")
    world.say("rejeite o plano 5")
    assert silence(world)[-1] == "Act on the card sent to you (send /pending)." and rejections(world) == []
    world.say("/reject 5")
    assert silence(world)[-1] == "Act on the card sent to you (send /pending)." and rejections(world) == []


def test_a_release_said_in_words_makes_the_call_the_typed_release_makes(world):
    world.items[5] = decision("review", 5, title="Draft of the brief")
    world.bridge.tick()
    hands_over(world, "/release 5")
    world.say("libere a entrega 5")
    assert wait_for(lambda: world.calls("release")) and silence(world)[-1] == "Released #5."
    assert [dict(c[2]) for c in world.calls("release")] == [{"pending_id": 5, "channel": "messaging"}]


def test_a_sender_without_the_group_is_refused_by_words_as_by_the_typed_line_and_nothing_is_called(world):
    world.config["channels"] = {"messaging": ["read", "talk"]}
    world.items[5] = decision("plan", 5)
    world.items[6] = decision("review", 6)
    world.bridge.tick()
    for typed, line in (("/reject 5", "rejeite o plano 5"), ("/release 6", "libere a entrega 6")):
        hands_over(world, typed)
        world.say(line)
        by_words = silence(world)[-1]
        world.say(typed)
        assert by_words == PLAIN_REFUSAL and silence(world)[-1] == PLAIN_REFUSAL, typed
    assert world.calls("reject") == [] and world.calls("release") == []


@pytest.mark.parametrize("typed,word,number", [("/add 3", "add", 3), ("/discard 4", "discard", 4)])
def test_a_file_added_or_discarded_in_words_reaches_the_card_binding_of_the_typed_line(world, monkeypatch, typed, word, number):
    seen = []
    monkeypatch.setattr(world.bridge.attach, "typed", lambda project, chat, kind, n: seen.append((chat, kind, n)))
    hands_over(world, typed)
    world.say("a line in words")
    assert wait_for(lambda: seen == [(SENDER, word, number)]) and silence(world) == []


def test_the_pending_list_said_in_words_is_the_typed_pending(world):
    world.items[2] = decision("question", 2, title="Which warehouse?")
    world.bridge.tick()
    first = len(world.sent())
    hands_over(world, "/pending")
    world.say("mostra as pendencias")
    assert wait_for(lambda: len(world.sent()) > first)
    by_words = silence(world)[first:]
    world.say("/pending")
    assert wait_for(lambda: len(world.sent()) > first + len(by_words))
    assert silence(world)[first + len(by_words):first + 2 * len(by_words)] == by_words and by_words[0].startswith("northwind-shop: #2 question")


# --- a command the table answers: its reply is said as the typed one's ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("typed,reply,sentence", [
    ("/cancel 4", {"request": 4, "cancelled": [4], "already": False}, "Request 4 cancelled."),
    ("/cancel 4", {"request": 4, "cancelled": [], "already": True}, "Request 4 was already cancelled."),
    ("/stop-task 8", {"task": 8, "already": False}, "Task 8 stopped."),
    ("/stop-task 8", {"task": 8, "already": True}, "Task 8 was not running."),
    ("/retry 9", {"task_id": 9}, "Task 9 is ready to run again."),
    ("/attachments", {"held": [{"id": 1}, {"id": 2}]}, "Files waiting for your answer: 2."),
])
def test_a_command_the_table_answers_is_said_in_words_as_the_typed_command_is_said(world, typed, reply, sentence):
    hands_over(world, typed, json.dumps(reply))
    world.say("a line in words")
    assert silence(world) == [sentence]
    world.fake.answers["say"] = lambda project, **kw: {"reply": json.dumps(reply), "request_id": None, "pending_id": None, "ran": False, "queued": False}
    world.say(typed)
    assert silence(world) == [sentence, sentence], "the typed line says the same sentence"


def test_a_reply_with_no_typed_line_is_said_as_it_always_was(world):
    world.say("hello there")
    assert wait_for(lambda: world.texts() == ["Noted."])


# --- the line is answered by code, so it takes no model slot ------------------------------------------------------------------------------------------------


def test_a_decision_or_an_act_in_a_closed_form_is_not_kept_behind_the_planning_agent_and_a_plain_line_is(world):
    world.items[5] = decision("plan", 5)
    world.bridge.tick()
    world.bridge.exclusive[world.projects[0]["id"]] = "job 99"      # the planning agent is answering another request of the project
    hands_over(world, "/reject 5")
    world.say("rejeite o plano 5")
    assert wait_for(lambda: rejections(world) == [5]), "a brake said in words works while the agent is busy, as the typed /reject does"
    assert wait_for(lambda: world.texts()[-1] == "Rejected #5.") and len(world.calls("say")) == 1
    world.say("what time is it in Lisbon")
    assert wait_for(lambda: world.texts()[-1] == "Got it: I will answer this after the current one."), "a plain line waits its turn"
    assert len(world.calls("say")) == 1, "and has not been run"
    del world.bridge.exclusive[world.projects[0]["id"]]


# --- the project the lines go to, said in words -----------------------------------------------------------------------------------------------------------


def second_project(world):
    folder = world.tmp / "second-shop"
    folder.mkdir()
    world.projects.append({"id": shell_kit.project_id(str(folder)), "name": "second-shop", "path": str(folder), "data_dir": str(world.tmp / "data")})
    world.bridge = world.make()


@pytest.mark.parametrize("line", ["switch to project second-shop", "muda para o projeto second-shop", "cambia al proyecto second-shop", "passe au projet second-shop",
                                  "wechsle zum Projekt second-shop", "passa al progetto second-shop", "Muda para o projeto Second Shop, por favor"])
def test_a_project_chosen_in_words_is_the_one_the_typed_project_chooses(world, line):
    second_project(world)
    world.say(line)
    assert wait_for(lambda: world.texts() == ["Your lines now go to second-shop."]) and world.calls("say") == []
    world.say("hello there")
    assert wait_for(lambda: world.calls("say") and world.calls("say")[-1][1] == str(world.tmp / "second-shop")), "the next line goes to the project chosen"


def test_the_project_asked_about_in_words_and_a_name_that_is_none_say_what_the_typed_project_says(world):
    second_project(world)
    world.say("qual projeto estou usando")
    world.say("which project am I using")
    world.say("muda para o projeto fantasma")
    world.say("/project fantasma")
    shown = "Your lines go to northwind-shop. Projects: northwind-shop, second-shop."
    none = "No such project. Projects: northwind-shop, second-shop."
    assert wait_for(lambda: len(world.texts()) == 4) and world.texts() == [shown, shown, none, none] and world.calls("say") == []


def test_a_line_that_only_begins_like_a_project_change_is_a_request_and_goes_to_the_conversation(world):
    second_project(world)
    for line in ("usa o projeto como base para planejar a feira", "use project plan to write the launch email", "muda para o projeto novo da feira de outubro com todos os detalhes"):
        world.say(line)
        silence(world)
    assert len(world.calls("say")) == 3 and world.texts() == ["Noted."] * 3


# --- no regression: the words and the changes that went first keep going first ------------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["aprovo", "sim", "yes", "approve"])
def test_an_approve_word_still_approves_the_card_that_is_the_last_message_and_nothing_else_is_asked(world, word):
    world.items[1] = decision("plan", 1, plan_sha256="a" * 64)
    world.bridge.tick()
    world.fake.calls.clear()
    world.say(word)
    assert approvals(world) == [(1, "a" * 64)] and world.calls("say") == [] and silence(world)[-1] == "Approved #1."


def test_a_change_of_the_waiting_card_still_goes_before_the_commands_in_words(world):
    world.config["channels"] = {"messaging": GRANTED}
    mail_card(world)
    revise = Revise(world)
    line = "muda o fim para Abraco, Dana"
    world.say(line)
    assert wait_for(lambda: revise.changes) and revise.changes[0][2] == line and world.calls("say") == [] and world.calls("reject") == [] and approvals(world) == []


@pytest.mark.parametrize("line", ["me lembra às 25h", "marca reuniao dia 25", "25 de outubro", "rejeite 25 de outubro", "prazo: 25"])
def test_a_line_with_a_number_that_is_no_decision_does_not_become_one(world, line):
    world.items[25] = decision("plan", 25, plan_sha256="b" * 64)
    world.bridge.tick()
    world.fake.calls.clear()
    world.say(line)
    silence(world)
    assert world.calls("reject") == [] and world.calls("release") == [] and approvals(world) == []


# --- review round: the act stays with the line's own project, the card is sent again when the sentence says so, and a list keeps its positions ------------------------------


def test_a_project_chosen_meanwhile_does_not_move_the_act_of_a_line_that_was_already_read(world):
    second_project(world)
    world.items[5] = decision("plan", 5)
    world.bridge.tick()
    world.fake.calls.clear()
    first, other = world.projects[0], world.projects[1]

    def answer(project, **kw):
        world.bridge.chosen[SENDER] = other["id"]      # a /project said while the line was being read
        return {"reply": "", "request_id": None, "pending_id": None, "ran": False, "queued": False, "typed": "/reject 5"}
    world.fake.answers["say"] = answer
    world.say("rejeite o plano 5")
    assert wait_for(lambda: world.calls("reject"))
    assert [c[1] for c in world.calls("reject")] == [first["path"]], "the act is done for the project the line was read for"


def test_the_typed_line_of_a_platform_whose_acts_are_replies_asks_for_the_card_and_does_nothing(world, monkeypatch):
    world.items[5] = decision("plan", 5)
    world.bridge.tick()
    monkeypatch.setattr(world.bridge.messenger, "capabilities", lambda: dict(world.bridge.messenger.__class__.capabilities(world.bridge.messenger), actions_need_reply=True))
    hands_over(world, "/reject 5")
    world.say("rejeite o plano 5")
    assert wait_for(lambda: world.texts()[-1] == "Reply to the card of this decision to act on it.") and rejections(world) == []


def cards_sent(world, number):
    return [s for s in world.sent() if s["message"]["actions"] and f"#{number}" in s["message"]["text"]]


def resend_after(world, forced):
    world.items[5] = decision("plan", 5)
    world.bridge.tick()
    assert len(cards_sent(world, 5)) == 1
    world.bridge.resent[(world.projects[0]["id"], SENDER, 5)] = world.bridge.monotonic()      # a card sent again a moment ago
    world.fake.answers["say"] = lambda project, **kw: {"reply": "The card is above.", "request_id": None, "pending_id": None, "ran": False, "queued": False, "resend": 5,
                                                       **({"resend_forced": True} if forced else {})}
    world.say("aprova o 5")
    assert wait_for(lambda: world.texts()[-1] == "The card is above.")
    return len(cards_sent(world, 5))


def test_a_sentence_that_says_the_card_was_sent_again_is_said_only_after_it_was_sent_again_even_within_the_flood_rule(world):
    assert resend_after(world, forced=True) == 2


def test_vacuity_a_resend_that_is_not_asked_for_by_the_sentence_keeps_the_flood_rule(world):
    assert resend_after(world, forced=False) == 1, "the other flows of the bridge keep the rule: a line repeated within a minute is not a flood"


def test_after_a_list_a_position_with_a_word_still_chooses_from_the_list_and_the_card_sentence_is_not_said(world):
    world.items[1] = decision("plan", 1, plan_sha256="a" * 64)
    world.items[2] = decision("plan", 2, plan_sha256="b" * 64)
    world.bridge.tick()
    world.say("sim")      # two cards: the numbered list
    assert wait_for(lambda: world.texts()[-1].startswith("More than one decision waits"))
    world.fake.calls.clear()
    world.say("aprova o 2")
    assert wait_for(lambda: approvals(world) == [(2, "b" * 64)]) and world.calls("say") == []
    assert not any("sent the card" in text for text in silence(world))


def test_vacuity_a_typed_line_run_back_through_handle_chooses_the_project_again_and_the_check_sees_it(world, monkeypatch):
    bridge_class = type(world.bridge)
    second_project(world)
    world.items[5] = decision("plan", 5)
    world.bridge.tick()
    world.fake.calls.clear()
    other = world.projects[1]
    monkeypatch.setattr(bridge_class, "typed_line", lambda self, project, chat, typed: self.handle({"sender": chat, "chat": chat, "private": True, "text": typed}))

    def answer(project, **kw):
        world.bridge.chosen[SENDER] = other["id"]
        return {"reply": "", "request_id": None, "pending_id": None, "ran": False, "queued": False, "typed": "/reject 5"}
    world.fake.answers["say"] = answer
    world.say("rejeite o plano 5")
    assert wait_for(lambda: world.calls("reject")) or True
    assert [c[1] for c in world.calls("reject")] != [world.projects[0]["path"]], "the old way moved the act to the project chosen meanwhile (or lost it)"
