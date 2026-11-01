"""The account question on the messaging bridge (package mail-list-account, limits L64 and L65; runtime/messaging_bridge.py `ask_plan`, `plan_decide`, `plan_tapped`, the kind `plan-confirm` of
runtime/messaging_turn.py, the row `plan-bare-word` of runtime/ops_turn.py).

A list of mail with no account is answered "Which account? Gmail, Outlook or all." with one button for each option; the person's choice is the OK of the plan. The real bridge over the real
operations layer and a stand-in messenger, a stand-in model and a stand-in clock (plan_bridge_kit.py), as test_messaging_plan_confirm.py has them; the project's accounts are stood in at
`ops_items.account_choices` (the world of this rig has no mail source: the real catalog is the other file's) and the one place a read runs is a spy (`brig.reads`, its own literal count). The
rules that decide a card by a bare word run over the bridge world of test_messaging.py with the account question open. Every negative test counts the reads; each guard has a vacuity case that
plants the one fact it reads and shows the same counter sees the other result. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_mail_list_account.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the bridge, not the claim)
from plan_bridge_kit import ASKER_ID, OWNER_ID, OWNER_KEY, brig, bridge, ops, phrases, rig, wait_for, world  # noqa: F401
from test_messaging import world as card_world  # noqa: F401  (the bridge world of test_messaging.py, with a fake operations layer, for the rules that decide a card by a bare word)
from test_messaging import SENDER
from test_messaging_card_again import records, stale
from test_messaging_card_words import approvals, nothing_decided

ops_items = st.load("ops_items")
pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

LINE = "mostra meus emails"
OPTIONS = [("inbox", "Gmail", ["gmail", "google"]), ("work", "Outlook", ["outlook", "hotmail"])]


@pytest.fixture
def two(brig, monkeypatch):
    """The rig, with the project's two mail accounts stood in at `account_choices` (the options the real catalog gives in test_mail_list_account.py)."""
    everyone = phrases.text("PLAN_ALL_ACCOUNTS", brig.rig.cfg)

    def choices(ctx, args, channel=None, sender=None):
        if args.get("kind") != "mail" or args.get("account") or args.get("source") or args.get("count") or args.get("match") is not None:
            return None
        return [{"value": value, "label": label, "words": words} for value, label, words in OPTIONS] + [{"value": "*", "label": everyone}]
    monkeypatch.setattr(ops_items, "account_choices", choices)
    return brig


def t(brig, key, **fields):
    return phrases.text(key, brig.rig.cfg, **fields)


def question(brig, named=""):
    """The text of the question: "I understood: list your e-mails. Which account? Gmail, Outlook or all." in the rig's language."""
    what = t(brig, "UNDERSTOOD_ITEMS_MAIL") + named
    return t(brig, "PLAN_HEAD", what=what) + " " + t(brig, "PLAN_ASK_ACCOUNT", names="Gmail, Outlook", all=t(brig, "PLAN_ALL_ACCOUNTS").lower())


def live(brig, sender=OWNER_KEY):
    return ops.plan_live(brig.rig.world["path"], sender)


def reads(brig):
    """The lists that ran, as (the account chosen or None): the test's own count of the spy."""
    return [r["args"].get("source") for r in brig.reads]


def last_message(brig, chat=OWNER_ID):
    return brig.sent()[-1]["message"] if brig.sent() else None


def asked(brig, line=LINE):
    brig.ask(line)
    assert brig.idle()


# --- the question and its buttons ----------------------------------------------------------------------------------------------------------------


def test_the_question_has_one_button_for_each_account_and_all_and_nothing_was_read(two):
    asked(two)
    message = last_message(two)
    assert message["text"] == question(two) and [a["label"] for a in message["actions"]] == ["Gmail", "Outlook", t(two, "PLAN_ALL_ACCOUNTS")]
    assert reads(two) == [] and two.rig.calls == [], "no read, no model"
    assert set(two.question_actions()) == {"pick:0", "pick:1", "pick:2"}


def test_a_tap_runs_the_list_of_that_account_once_and_a_second_tap_or_an_old_questions_tap_reads_nothing(two):
    asked(two)
    outlook = two.question_actions()["pick:1"]
    two.tap(outlook)
    assert wait_for(lambda: reads(two) == ["work"]) and two.idle()
    two.tap(outlook)      # a second tap: the plan was taken
    assert wait_for(lambda: t(two, "PLAN_GONE") in two.texts()) and reads(two) == ["work"]
    two.reads.clear()
    asked(two)
    older = two.question_actions()["pick:0"]
    two.rig.says["text"] = json.dumps({"v": 1, "kind": "answer", "answers_item": "i2", "option": 3})
    two.say("nos dois")      # validate: allow english-only -- the Portuguese words under test
    assert wait_for(lambda: last_message(two)["text"].endswith(t(two, "PLAN_ASK"))) and reads(two) == [], "a free answer: the plan is stated again, nothing is read"
    sent = len(two.texts())
    two.tap(older)      # the old question's button: its plan is gone, a newer plan of the sender stands
    assert wait_for(lambda: len(two.texts()) > sent and two.texts()[-1] == t(two, "PLAN_GONE")) and reads(two) == []


def test_the_all_button_runs_the_list_without_a_source(two):
    asked(two)
    two.tap(two.question_actions()["pick:2"])
    assert wait_for(lambda: reads(two) == [None])


# --- typed answers ----------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("word, source", [("gmail", "inbox"), ("Gmail.", "inbox"), ("o outlook", "work"), ("1", "inbox"), ("2", "work"), ("both", None), ("todas", None), ("o segundo", "work")])      # validate: allow english-only -- the Portuguese words under test
def test_a_closed_word_that_names_an_account_runs_that_list_with_no_model(two, word, source):
    asked(two)
    two.say(word)
    assert wait_for(lambda: reads(two) == [source]) and two.idle() and two.rig.calls == [] and live(two) is None


def test_a_yes_sends_the_question_again_with_its_buttons_and_reads_nothing_a_no_drops_a_greeting_is_no_choice(two):
    asked(two)
    two.say("sim")      # validate: allow english-only -- the Portuguese words under test
    assert wait_for(lambda: len(two.texts()) == 2) and two.idle()
    again = last_message(two)
    assert again["text"] == question(two) and [a["label"] for a in again["actions"]] == ["Gmail", "Outlook", t(two, "PLAN_ALL_ACCOUNTS")] and reads(two) == []
    two.tap(two.question_actions()["pick:1"])
    assert wait_for(lambda: reads(two) == ["work"]), "the buttons of the question sent again work"
    asked(two)
    two.say("nao")      # validate: allow english-only -- the Portuguese words under test
    assert wait_for(lambda: two.texts()[-1] == t(two, "PLAN_DROPPED")) and reads(two) == ["work"] and live(two) is None
    asked(two)
    two.say("oi")      # validate: allow english-only -- the Portuguese words under test
    assert two.idle() and reads(two) == ["work"] and two.rig.calls == [], "a greeting is taken earlier and is no choice"


def test_a_line_in_question_form_is_no_answer_it_goes_to_the_model_and_so_does_a_yes_in_question_form(two):
    asked(two)
    two.rig.says["text"] = json.dumps({"v": 1, "kind": "answer", "answers_item": "i2", "option": 1})
    two.say("gmail?")
    assert wait_for(lambda: len(two.rig.calls) == 1) and two.idle(), "the model read the line: it asks, and is no closed word"
    assert last_message(two)["text"].endswith(t(two, "PLAN_ASK")) and reads(two) == [], "the model placed it: the plan is stated again for the person's own yes, nothing ran"
    asked(two)
    before = len(two.rig.calls)
    two.rig.says["text"] = json.dumps({"v": 1, "kind": "clarify"})
    two.say("sim?")      # validate: allow english-only -- the Portuguese words under test
    assert wait_for(lambda: len(two.rig.calls) == before + 1) and two.idle() and reads(two) == [], "PLAN-QUESTION-FORM: a yes in question form is no yes either: the model reads it, and nothing is read"
    assert live(two) is not None and last_message(two)["text"] == question(two), "the model could not place it: the account question again, the plan kept"


# --- not the last message ------------------------------------------------------------------------------------------------------------------------


def test_a_typed_word_while_the_question_is_not_the_last_message_decides_nothing_and_a_tap_still_runs_it(two):
    asked(two)
    two.bridge.reply(OWNER_ID, "A reminder: water the plants.")      # a delivered reminder: the question is no longer the last message
    for word in ("gmail", "sim", "todas"):      # validate: allow english-only -- the Portuguese words under test
        sent = len(two.texts())
        two.say(word)
        assert wait_for(lambda: len(two.texts()) > sent and two.texts()[-1] == t(two, "PLAN_NOT_LAST_ACCOUNT")), word
    assert two.idle() and reads(two) == [] and two.rig.calls == [] and live(two) is not None, "no read, no model, and the plan waits"
    two.tap(two.question_actions()["pick:0"])
    assert wait_for(lambda: reads(two) == ["inbox"]), "a button names its message: it needs no last-message rule"


def test_vacuity_with_the_question_planted_as_the_last_message_the_same_word_runs_the_list(two):
    asked(two)
    question_id = two.question_id()
    two.bridge.reply(OWNER_ID, "A reminder: water the plants.")

    class Always(dict):      # the one fact the kind `plan-confirm` reads, planted: the question is the last message
        def get(self, chat, default=None):
            return question_id
    two.bridge.last_sent = Always()
    two.say("gmail")
    assert wait_for(lambda: reads(two) == ["inbox"]), "the same counter that is empty in the test above sees the read"


def test_a_forwarded_account_runs_nothing(two):
    asked(two)
    two.say("gmail", forwarded=True)
    assert wait_for(lambda: two.texts()[-1] == t(two, "FWD_NOT_A_REQUEST")) and reads(two) == [] and live(two) is not None


# --- the platforms ------------------------------------------------------------------------------------------------------------------------------------


def test_with_two_buttons_at_most_the_question_is_text_and_a_typed_answer_still_works(two):
    two.caps(max_buttons=2)
    asked(two)
    message = last_message(two)
    assert message["text"] == question(two) and message["actions"] == []
    two.say("outlook")
    assert wait_for(lambda: reads(two) == ["work"])


def test_a_label_longer_than_the_platforms_limit_makes_the_question_text(two):
    two.caps(max_button_label=3)
    asked(two)
    assert last_message(two)["actions"] == [] and last_message(two)["text"] == question(two)


def test_on_e_mail_the_question_says_how_to_reply_and_only_a_reply_counts(two):
    two.caps(buttons=False, actions_need_reply=True)
    asked(two)
    message = last_message(two)
    assert message["actions"] == [] and message["text"] == question(two) + "\n" + t(two, "PLAN_REPLY_HOW_ACCOUNT")
    two.say("gmail")      # not a reply: on e-mail an answer is a reply (rule 50)
    assert wait_for(lambda: two.texts()[-1] == t(two, "PLAN_NOT_LAST_ACCOUNT")) and two.idle() and reads(two) == []
    two.say("gmail\n\n-- \nAna", reply_to=two.question_id())      # the signature is not words
    assert wait_for(lambda: reads(two) == ["inbox"])


# --- a free answer ------------------------------------------------------------------------------------------------------------------------------------


def test_a_free_answer_is_read_by_the_model_once_the_plan_is_stated_again_and_only_the_yes_runs_it(two):
    asked(two)
    assert two.rig.calls == []
    two.rig.says["text"] = json.dumps({"v": 1, "kind": "answer", "answers_item": "i2", "option": 2})
    two.say("o do trabalho")      # validate: allow english-only -- the Portuguese words under test
    assert wait_for(lambda: len(two.texts()) == 2) and two.idle()
    assert len(two.rig.calls) == 1 and reads(two) == []
    restated = last_message(two)
    assert restated["text"] == t(two, "PLAN_HEAD", what=t(two, "UNDERSTOOD_ITEMS_MAIL") + " " + t(two, "UNDERSTOOD_FROM_ACCOUNT", name="Outlook")) + " " + t(two, "PLAN_ASK")
    assert [a["label"] for a in restated["actions"]] == [t(two, "NT_BTN_YES"), t(two, "PLAN_BTN_NO")], "a plain question: Yes and No"
    two.say("sim")      # validate: allow english-only -- the Portuguese words under test
    assert wait_for(lambda: reads(two) == ["work"]) and len(two.rig.calls) == 1, "the person's own yes ran it: no second model call"


# --- the ledger ----------------------------------------------------------------------------------------------------------------------------------------


def test_the_ledger_record_holds_a_count_and_digits_and_no_name_and_no_source_id(two):
    asked(two)
    [record] = [c for c in two.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm"]
    assert record["plan_picks"] == 3 and sorted(record["actions"].values()) == ["pick:0", "pick:1", "pick:2"]
    dump = json.dumps(record)
    assert all(word not in dump for word in ("Gmail", "Outlook", "inbox", "work", "emails")), "no label, no source id, no word of the question"
    two.caps(max_buttons=2)
    asked(two)
    assert [c for c in two.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm"][-1]["plan_picks"] == 3, "a text question is bound as well: a typed word is its answer"


# --- the account question and a decision card ----------------------------------------------------------------------------------------------------------

LIVE_ACCOUNT = {"item": "a1b2c3", "sha256": "d" * 64, "op": "items", "choices": ["Gmail", "Outlook", "All"], "question": "I understood: list your e-mails. Which account? Gmail, Outlook or all."}


def question_open(card_world, last=True):
    """The account question of a plan that waits, sent as the bridge sends it; with `last` False a reminder was delivered after it."""
    card_world.fake.plan_live = lambda project, sender: LIVE_ACCOUNT
    card_world.fake.plan_choice = lambda project, sender, said: None
    card_world.bridge.ask_plan(card_world.projects[0], SENDER, LIVE_ACCOUNT["question"], dict(LIVE_ACCOUNT))
    if not last:
        card_world.bridge.reply(SENDER, "A reminder: water the plants.")


@pytest.mark.parametrize("last", [True, False])
@pytest.mark.parametrize("word", ["aprovo", "manda ver", "rejeito", "approve", "reject"])
def test_a_bare_card_word_with_the_account_question_last_or_waiting_brings_no_card_back_and_decides_none(card_world, word, last):
    stale(card_world)
    question_open(card_world, last)
    count = len(records(card_world))
    card_world.say(word)
    assert wait_for(lambda: len(card_world.calls("say")) == 2) and nothing_decided(card_world) and approvals(card_world) == [] and len(records(card_world)) == count, "no card was sent again and none was decided"


def test_vacuity_with_the_plan_guard_off_the_same_word_brings_the_card_back(card_world, monkeypatch):
    stale(card_world)
    question_open(card_world, last=False)
    count = len(records(card_world))
    monkeypatch.setattr(bridge.Bridge, "plan_waits", lambda self, listed, chat: False)
    card_world.say("aprovo")
    assert len(records(card_world)) == count + 1, "the card counter sees the card sent again when the one fact the guard reads is planted"


def test_a_yes_word_on_the_account_question_that_is_last_asks_it_again_and_decides_no_card(card_world):
    stale(card_world)
    question_open(card_world)
    count = len(records(card_world))
    card_world.say("sim")      # validate: allow english-only -- the Portuguese words under test
    assert wait_for(lambda: len(records(card_world)) == count + 1), "the question again, a new record"
    assert records(card_world)[-1]["kind"] == "plan-confirm" and records(card_world)[-1]["plan_picks"] == 3
    assert nothing_decided(card_world) and len(card_world.calls("say")) == 1, "no card decided, and the word went no further than the bridge (the one call is the greeting of `stale`)"
