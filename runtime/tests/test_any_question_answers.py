"""The answers to a question the interpreter read (package ANY-QUESTION Q1; runtime/ops_any_question.py, runtime/ops_interpret.py `_question`, runtime/ops_event_revise.py `revise`, runtime/plan_confirm.py,
runtime/line_card.py, runtime/messaging_bridge.py `waiting_card`): code answers from the card's own lines or a fixed sentence, and nothing is opened, ended, approved or run.

Over the real calendar world of test_event_revise_flow.py (the real family path, the real cards, a stand-in clock and a stand-in model that answers the interpreter's call by a hand-written text) and, for
the bridge, the stand-in operations object and messenger of test_messaging.py. A mail card is a stored effect decision that holds the lines of the card the mail family opens (its lines are the
ones of a real send card), written straight into the store. Every sentence is asserted by its phrase key (phrase_kit) in English and in Portuguese, or by a literal English string. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_any_question_answers.py
"""
from __future__ import annotations

import datetime
import json

import pytest

import phrase_kit as pk
import standin_tree as st
import test_event_lookup as tel
from test_calendar_write import fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_revise_flow import Model, create, fresh, open_cards, revise  # noqa: F401
from test_messaging import SENDER as BRIDGE_SENDER, wait_for, world as bridge_world  # noqa: F401  (the bridge world)
from test_messaging_card_revise import Revise, mail_card, settle
from test_ops_natural import KEY  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_say = st.load("ops_say")
ops_natural = st.load("ops_natural")
ops_card_revise = st.load("ops_card_revise")
ops_any_question = st.load("ops_any_question")
messaging_cards = st.load("messaging_cards")
plan_confirm = st.load("plan_confirm")
phrases = st.load("phrases")
turn_gate = st.load("turn_gate")
line_card = st.load("line_card")
interpreter = st.load("interpreter")

OWNER, TALKER, MAILER = "telegram:830461975213", "telegram:5151", "telegram:7070"
PROFILES = {"owner": ["read", "talk", "calendar-write", "ask-mail", "interpret", "reject-cancel", "reminders"],
            "talker": ["read", "talk", "calendar-write", "interpret"],            # no `ask-mail`: the private lines of a card are not shown to this sender
            "mailer": ["read", "talk", "interpret", "mail-send"]}
IDS = {"owner": "830461975213", "talker": "5151", "mailer": "7070"}
EN, PT = {"language": "en"}, {"language": "pt-BR"}
STAMP = ops_any_question.STAMP
MAIL_CARD = [["CARD_MAIL_SEND", {}], ["CARD_MAIL_FROM_ACCOUNT", {"account": "google", "address": "pat@example.com"}], ["CARD_MAIL_TO", {"addresses": "dana.holt@clinic.example"}],
             ["CARD_MAIL_SUBJECT", {"subject": "Moving our call"}], ["CARD_MAIL_COUNT", {"count": "1"}], ["CARD_MAIL_MESSAGE", {"body": "| Hello,\n|\n| Could we move our call?"}],
             ["CARD_MAIL_HASH", {"sha": "0" * 64}], ["CARD_MAIL_ONCE", {}]]
TODO_CARD = [["CARD_TODO_ADD", {}], ["CARD_ACCOUNT", {"account": "google", "address": "pat@example.com"}], ["CARD_TODO_LIST", {"list": "Home", "service": "Google Tasks"}],
             ["CARD_TODO_TITLE", {"title": "Buy milk"}], ["CARD_TODO_PLAIN", {}]]


def op_object(about, **more):
    return json.dumps({"v": 1, "kind": "question", "about": about, **more})


def built(world, monkeypatch, text=None, language="en"):
    """The calendar world with three senders (the owner reads private lines, the talker does not, the mailer holds mail-send) and the stand-in model."""
    monkeypatch.setattr(tel, "PROFILES", PROFILES)
    monkeypatch.setattr(tel, "IDS", IDS)
    tel.build(world, monkeypatch, language=language)
    return Model(monkeypatch, text)


def stamp(delta_days=0):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=delta_days)).strftime(STAMP)


def inject(world, card, task_id, status="open", resolution=None, answer=None, days_ago=0, title="Mail: send from your account"):
    """A stored effect decision whose card is `card` (the lines of a real card), written straight into the store: no mailer, no writer is involved."""
    ctx = ops_core.context(world["path"])
    cur = ctx["conn"].execute("INSERT INTO pending_decisions (task_id, kind, title, body, payload, payload_sha256, status, resolution, answer, created_at) VALUES (?, 'effect', ?, ?, ?, ?, ?, ?, ?, ?)",
                              (task_id, title, phrases.card_text(card), json.dumps({"card": card}), "ab" * 32, status, resolution, answer, stamp(days_ago)))
    ctx["conn"].commit()
    return cur.lastrowid


def turn(world, line, sender, waiting=None):
    """(the reply, extras) of the interpreter's turn for the line, as the operations layer runs it, with `waiting` the card the bridge says the line is about."""
    ctx = ops_core.context(world["path"])
    extras = {} if waiting is None else {"waiting_card": waiting}
    with turn_gate.turn():
        got = ops_interpret.turn(world["path"], ctx, line, sender, extras)
    return got[0], extras


def event_card(world, **more):
    number, sha = create(world, **more)
    return number, sha, ops.pending(world["path"], number)["task_id"]


# --- 1 and 2: the card call -----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("field,sentence", [
    ("when", "The card says:\nWhen: Sat 24/10/2026 08:00-09:00 (America/Sao_Paulo)\nNothing was changed; the card is below."),
    ("place", "The card says:\nWhere: Main Street\nNothing was changed; the card is below."),
    ("title", "The card says:\nTitle: evento social\nNothing was changed; the card is below."),
    ("approve", "This is what approving does, as the card says:\nCode creates this event after your approval, and nothing else.\nRejecting it does nothing. Nothing was changed; the card is below."),
])
def test_the_card_call_answers_a_question_about_the_card_from_its_own_lines_and_changes_nothing(world, monkeypatch, field, sentence):
    model = built(world, monkeypatch, op_object("card", field=field))
    old, sha, _ = event_card(world, location="Main Street")
    line = "where is this event?"
    got = revise(world, old, sha, line)
    assert got == {"say": sentence, "resend": old}
    assert open_cards(world) == [old] and len(model.calls) == 1
    assert ops_card_revise.decided(world["path"], "messaging", OWNER, line) is None, "the card call keeps nothing for the turn that follows"
    assert ops.pending(world["path"], old)["payload_sha256"] == sha and reads_only_nothing(world)


def reads_only_nothing(world):
    return tel.reads_only(world) == []


def test_the_card_call_says_so_in_portuguese_with_the_key_of_the_phrase(world, monkeypatch):
    built(world, monkeypatch, op_object("card", field="place"), language="pt-BR")
    old, sha, _ = event_card(world, location="Main Street")
    got = revise(world, old, sha, "onde fica esse evento?")      # validate: allow english-only -- the Portuguese line under test
    lines = phrases.text("CARD_CAL_WHERE", PT, location="Main Street")
    pk.assert_said(got["say"], "QUESTION_CARD_SAYS", PT, lines=lines)
    assert got["resend"] == old and open_cards(world) == [old]


@pytest.mark.parametrize("field,location", [("place", None), ("to", "Main Street"), ("from", None), ("subject", None)])
def test_a_field_the_card_does_not_hold_gets_the_sentence_that_the_card_does_not_say_that_and_the_account_is_a_line_of_the_card(world, monkeypatch, field, location):
    built(world, monkeypatch, op_object("card", field=field))
    old, sha, _ = event_card(world, location=location)
    got = revise(world, old, sha, "who is it for?")
    if field == "from":      # the account line is a line of the card: the account is said
        pk.assert_said(got["say"], "QUESTION_CARD_SAYS", EN, lines=phrases.text("CARD_ACCOUNT", EN, account="google", address="pat@example.com"))
    else:
        pk.assert_said(got["say"], "QUESTION_CARD_NONE", EN)
    assert got["resend"] == old and open_cards(world) == [old]


@pytest.mark.parametrize("about,more", [("done", {"op": "event-create"}), ("done", {}), ("can", {"op": "event-create"}), ("other", {})])
def test_a_question_that_is_not_about_the_card_passes_on_and_the_turn_that_follows_reads_it_once(world, monkeypatch, about, more):
    model = built(world, monkeypatch, op_object(about, **more))
    old, sha, _ = event_card(world)
    line = "was it created?"
    assert revise(world, old, sha, line) == {"pass": True}
    got = ops_card_revise.decided(world["path"], "messaging", OWNER, line)
    assert got is not None and got["kind"] == "question" and got["about"] == about
    assert open_cards(world) == [old] and len(model.calls) == 1


# --- 3 to 7: the main turn ------------------------------------------------------------------------------------------------------------------------------


def test_the_main_turn_answers_a_question_about_the_waiting_mail_card_from_its_lines_and_sends_the_card_again(world, monkeypatch):
    built(world, monkeypatch, op_object("card", field="to"))
    _, _, task = event_card(world)
    mail = inject(world, MAIL_CARD, task)
    reply, extras = turn(world, "who is this e-mail going to?", OWNER, waiting=mail)
    want = "The card says:\nTo: dana.holt@clinic.example\nNothing was changed; the card is below."
    assert reply == want and extras["resend"] == mail and extras["lead"] == want
    assert extras["stored"] == phrases.text("NAT_READ_REPLY", EN), "the conversation keeps a word: the reply may hold the card's private lines"
    assert ops.pending(world["path"], mail)["status"] == "open"


def test_a_sender_who_may_not_read_the_private_lines_of_the_card_is_told_the_card_does_not_say_it(world, monkeypatch):
    built(world, monkeypatch, op_object("card", field="to"))
    _, _, task = event_card(world)
    mail = inject(world, MAIL_CARD, task)
    reply, extras = turn(world, "who is this e-mail going to?", TALKER, waiting=mail)
    pk.assert_said(reply, "QUESTION_CARD_NONE", EN)
    assert "dana.holt" not in reply and "dana.holt" not in extras["lead"] and extras["resend"] == mail


def test_what_approving_does_is_the_first_line_of_the_card(world, monkeypatch):
    built(world, monkeypatch, op_object("card", field="approve"))
    _, _, task = event_card(world)
    mail = inject(world, MAIL_CARD, task)
    reply, _ = turn(world, "what happens if I approve?", OWNER, waiting=mail)
    pk.assert_said(reply, "QUESTION_CARD_APPROVE", EN, lines=phrases.text("CARD_MAIL_SEND", EN))


def test_a_question_about_the_card_with_no_card_waiting_gets_the_sentence_that_none_is_seen(world, monkeypatch):
    built(world, monkeypatch, op_object("card", field="when"))
    reply, extras = turn(world, "when is it?", OWNER)
    pk.assert_said(reply, "QUESTION_NO_CARD", EN)
    assert "resend" not in extras and "lead" not in extras


def test_a_card_that_is_gone_or_closed_is_no_card_waiting(world, monkeypatch):
    built(world, monkeypatch, op_object("card", field="when"))
    _, _, task = event_card(world)
    closed = inject(world, MAIL_CARD, task, status="resolved", resolution="approved")
    for waiting in (closed, 9999):
        reply, extras = turn(world, "when is it?", OWNER, waiting=waiting)
        pk.assert_said(reply, "QUESTION_NO_CARD", EN)
        assert "resend" not in extras


@pytest.mark.parametrize("language,cfg", [("en", EN), ("pt-BR", PT)])
@pytest.mark.parametrize("decision", ['{"v":1,"kind":"none"}', op_object("other")])
def test_a_card_word_in_question_form_with_a_card_waiting_decides_nothing_and_says_how_to_decide(world, monkeypatch, language, cfg, decision):
    built(world, monkeypatch, decision, language=language)
    old, sha, _ = event_card(world)
    for line in ("yes?", "sim?"):      # validate: allow english-only -- the Portuguese word under test
        reply, extras = turn(world, line, OWNER, waiting=old)
        pk.assert_said(reply, "QUESTION_CARD_WORD", cfg)
        assert extras["resend"] == old and extras["lead"] == reply
    assert open_cards(world) == [old] and ops.pending(world["path"], old)["status"] == "open"


def test_the_same_line_with_no_card_waiting_and_a_line_that_is_not_a_card_word_are_the_nothing_sentence(world, monkeypatch):
    built(world, monkeypatch, '{"v":1,"kind":"none"}')
    old, sha, _ = event_card(world)
    pk.assert_said(turn(world, "yes?", OWNER)[0], "IX_NONE", EN)
    pk.assert_said(turn(world, "can you book the dentist?", OWNER, waiting=old)[0], "IX_NONE", EN)
    assert open_cards(world) == [old]


def test_can_says_yes_for_what_the_sender_holds_the_policys_refusal_for_what_it_does_not_and_the_card_words_for_approve(world, monkeypatch):
    model = built(world, monkeypatch, op_object("can", op="mail-send"))
    ctx = lambda: ops_core.context(world["path"])      # noqa: E731
    reply, _ = turn(world, "can you send e-mails?", MAILER)
    pk.assert_said(reply, "CAN_YES", EN)
    reply, _ = turn(world, "can you send e-mails?", OWNER)      # the owner holds no mail-send
    assert reply == ops_interpret._refusal(ctx(), "mail-send", OWNER) and not pk.said(reply, "CAN_YES", EN)
    model.text = op_object("can", op="approve")
    pk.assert_said(turn(world, "can you approve a card?", OWNER)[0], "CAN_CARD", EN)
    model.text = op_object("can", op="config")
    reply, _ = turn(world, "can you change my settings?", OWNER)
    assert reply == ops_natural.phone_sentence(ctx(), "config")


def test_a_question_about_anything_else_is_the_fixed_sentence(world, monkeypatch):
    built(world, monkeypatch, op_object("other"))
    pk.assert_said(turn(world, "are you a real person?", OWNER)[0], "QUESTION_OTHER", EN)


# --- 8: what was done -----------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("op,planned", [("remind", "reminders"), ("reminders", "reminders"), ("cancel", "status"), ("event-create", "pending"), ("mail-send", "pending"), (None, "pending")])
def test_a_question_about_what_was_done_is_the_plan_of_a_read_and_nothing_runs_before_the_ok(world, monkeypatch, op, planned):
    built(world, monkeypatch, op_object("done", **({"op": op} if op else {})))
    _, _, task = event_card(world)
    inject(world, MAIL_CARD, task)
    reply, extras = turn(world, "did that go through?", OWNER)
    assert "plan_confirm" in extras, reply
    assert extras["plan_confirm"]["op"] == planned
    assert phrases.text("PLAN_ASK", EN) in reply
    if planned == "pending":
        assert phrases.text("UNDERSTOOD_DONE", EN) in reply
    assert not pk.said(reply, "DONE_HEAD", EN)


def test_the_ok_of_the_plan_lists_the_latest_cards_newest_first_at_most_three_with_how_each_ended(world, monkeypatch):
    built(world, monkeypatch, op_object("done"))
    _, _, task = event_card(world)      # a card of the event family, open, number 1
    a = inject(world, MAIL_CARD, task, status="resolved", resolution="approved", title="Mail: send from your account")
    b = inject(world, MAIL_CARD, task, status="resolved", resolution="rejected", title="Mail: send from your account")
    c = inject(world, MAIL_CARD, task, status="resolved", resolution="rejected", answer=ops_any_question.REPLACED_NOTE, title="Mail: send from your account")
    d = inject(world, MAIL_CARD, task, status="cancelled", title="Mail: send from your account")
    _, extras = turn(world, "did that go through?", OWNER)
    ctx = ops_core.context(world["path"])
    extras2 = {}
    reply = ops_say._confirmed(world["path"], ctx, "yes", OWNER, {"item": extras["plan_confirm"]["item"], "sha256": extras["plan_confirm"]["sha256"]}, extras2)
    lines = reply.splitlines()
    assert lines[0] == phrases.text("DONE_HEAD", EN) and len(lines) == 4, reply
    title = "Mail: send from your account"
    for line, number, state in zip(lines[1:], (d, c, b), ("DONE_STATE_CANCELLED", "DONE_STATE_REPLACED", "DONE_STATE_REJECTED")):
        pk.assert_said(line, "DONE_LINE", EN, number=str(number), what=title, state=phrases.text(state, EN))
    assert str(a) not in " ".join(lines) and extras2["stored"] == phrases.text("NAT_READ_REPLY", EN), "the fourth card is left out, and the conversation keeps a word"


def test_the_ok_with_no_card_in_the_last_days_says_so(world, monkeypatch):
    built(world, monkeypatch, op_object("done", op="mail-send"))
    event_card(world)      # only an event card: no mail card
    _, extras = turn(world, "was it sent?", OWNER)
    ctx = ops_core.context(world["path"])
    reply = ops_say._confirmed(world["path"], ctx, "yes", OWNER, {"item": extras["plan_confirm"]["item"], "sha256": extras["plan_confirm"]["sha256"]}, {})
    pk.assert_said(reply, "DONE_NONE", EN)


def test_a_sender_who_may_not_read_the_private_titles_sees_the_cards_without_what_they_hold(world, monkeypatch):
    built(world, monkeypatch, op_object("done"))
    _, _, task = event_card(world)
    inject(world, MAIL_CARD, task, status="resolved", resolution="approved", title="Mail: send from your account")
    _, extras = turn(world, "did that go through?", TALKER)
    ctx = ops_core.context(world["path"])
    reply = ops_say._confirmed(world["path"], ctx, "yes", TALKER, {"item": extras["plan_confirm"]["item"], "sha256": extras["plan_confirm"]["sha256"]}, {})
    assert "dana.holt" not in reply and "Moving our call" not in reply


# --- 9: question_done, pure -----------------------------------------------------------------------------------------------------------------------------

NOW = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=datetime.timezone.utc)
EVENT_CARD = [["CARD_CAL_CREATE", {}], ["CARD_ACCOUNT", {"account": "google", "address": "pat@example.com"}], ["CARD_CAL_TITLE", {"title": "Dinner"}]]
BOX_CARD = [["CARD_BOX_DRAFT_TO", {"to": "dana.holt@clinic.example"}]]
FILE_CARD = [["CARD_FILE_CODE_NEW", {}], ["CARD_FILE_NAME", {"name": "trip.pdf", "service": "Drive"}]]


def row(number, card, days_ago=1, status="open", resolution=None, answer=None, kind="effect", created=None, title="A card"):
    when = created if created is not None else (NOW - datetime.timedelta(days=days_ago)).strftime(STAMP)
    return {"id": number, "kind": kind, "status": status, "resolution": resolution, "answer": answer, "created_at": when, "title": title, "payload": {"card": card}}


def test_question_done_lists_the_cards_of_the_family_of_the_op_newest_first_within_seven_days_at_most_three():
    rows_ = [row(1, EVENT_CARD), row(2, MAIL_CARD, days_ago=2), row(3, BOX_CARD, days_ago=3), row(4, TODO_CARD), row(5, FILE_CARD),
             row(6, MAIL_CARD, days_ago=8),                       # 8 days old
             row(7, MAIL_CARD, created="not a stamp"),            # a stamp that does not parse
             row(8, MAIL_CARD, kind="plan"),                      # not an effect
             row(9, [["CARD_NOT_IN_THE_TABLE", {}]]),             # an invalid card
             row(10, MAIL_CARD, days_ago=-1),                     # made after `now`
             row(11, MAIL_CARD, days_ago=6, status="resolved", resolution="approved", title="Sent")]
    got = ops_any_question.question_done(rows_, "event-create", NOW)
    assert got == [{"pending_id": 1, "state": "open", "title": "A card"}]
    got = ops_any_question.question_done(rows_, "mail-send", NOW)
    assert [(g["pending_id"], g["state"]) for g in got] == [(11, "approved"), (3, "open"), (2, "open")], "mail and the mailbox are one family; newest first by number"
    got = ops_any_question.question_done(rows_, None, NOW)
    assert [g["pending_id"] for g in got] == [11, 5, 4], "any family: the three newest of all"
    assert ops_any_question.question_done(rows_, "todo-add", NOW) == [{"pending_id": 4, "state": "open", "title": "A card"}]
    assert ops_any_question.question_done(rows_, "file-ask", NOW) == [], "a read is not an act: it has no card"
    assert ops_any_question.question_done(rows_, "cancel", NOW) == [] and ops_any_question.question_done(rows_, "research", NOW) == []


@pytest.mark.parametrize("fields,state", [
    (dict(status="open"), "open"),
    (dict(status="resolved", resolution="approved"), "approved"),
    (dict(status="resolved", resolution="rejected"), "rejected"),
    (dict(status="resolved", resolution="rejected", answer="replaced by a revised card"), "replaced"),
    (dict(status="cancelled"), "cancelled"),
    (dict(status="resolved", resolution="answered"), "cancelled"),
])
def test_how_a_decision_ended(fields, state):
    assert ops_any_question.state_of(dict(fields)) == state


def test_the_family_of_a_card_skips_the_account_line_and_knows_four_families():
    assert [ops_any_question.family_of(c) for c in (EVENT_CARD, MAIL_CARD, BOX_CARD, TODO_CARD, FILE_CARD)] == ["event", "mail", "mail", "todo", "file"]
    assert ops_any_question.family_of([["CARD_ACCOUNT", {"account": "g", "address": "a@example.com"}], ["CARD_CAL_TITLE", {"title": "x"}]]) == "event"
    assert ops_any_question.family_of([["CARD_HIDDEN_NOTE", {}]]) is None and ops_any_question.family_of("nothing") is None


# --- 10: the hash of a plan -----------------------------------------------------------------------------------------------------------------------------


def test_a_plan_without_a_question_has_the_hash_it_had_before_and_a_plan_with_one_has_another():
    plain = plan_confirm.plan_sha256("pk", "telegram:1", "pending", {}, None, False, "what is pending")
    assert plain == "8a97dd6be0c0d50d28a86fb77d1909a3da793fd04a240afa4dc9047c9d56ff2b"      # the value of the module before ANY-QUESTION, for the same input
    choices = [{"value": "a"}, {"value": "all"}]
    assert plan_confirm.plan_sha256("pk", "telegram:1", "items", {"kind": "mail"}, None, True, "my mail", choices) == "7da597d6a588811486eec8776bdd78e42ec2d57cfedc1bbd306a4b9242d1db66"
    asked = plan_confirm.plan_sha256("pk", "telegram:1", "pending", {}, None, False, "what is pending", None, {"op": None})
    assert asked != plain and asked != plan_confirm.plan_sha256("pk", "telegram:1", "pending", {}, None, False, "what is pending", None, {"op": "mail-send"})


def test_a_plan_whose_question_was_altered_after_it_was_asked_is_not_taken(world, monkeypatch):
    built(world, monkeypatch, op_object("done", op="mail-send"))
    _, extras = turn(world, "was it sent?", OWNER)
    plan = plan_confirm.live(world["path"], OWNER)
    assert plan["state"]["question_done"] == {"op": "mail-send"}
    plan["state"]["question_done"] = {"op": None}      # a tamper of the stored plan
    assert plan_confirm.take(world["path"], OWNER, {"item": extras["plan_confirm"]["item"], "sha256": extras["plan_confirm"]["sha256"]}) is None
    plan["state"]["question_done"] = {"op": "mail-send"}
    assert plan_confirm.take(world["path"], OWNER, {"item": extras["plan_confirm"]["item"], "sha256": extras["plan_confirm"]["sha256"]}) is not None


# --- 11: the equalities the module copies ---------------------------------------------------------------------------------------------------------------


def test_the_copies_in_the_module_equal_their_sources_and_every_key_is_in_the_table():
    assert ops_any_question.REPLACED_NOTE == ops_card_revise.NOTE
    assert all(messaging_cards.PHONE_LINE.get(key) == value for key, value in ops_any_question.PHONE_HEAD.items())
    english = phrases.TABLE["en"]
    keys = [key for keys in ops_any_question.FIELD_KEYS.values() for key in keys] + list(ops_any_question.PHONE_HEAD.values()) + list(ops_any_question.PHONE_HEAD)
    assert [key for key in keys if key not in english] == []
    assert [key for key in ops_any_question.STATE_KEY.values() if key not in english] == []
    assert sorted(ops_any_question.FAMILIES) == ["event", "file", "mail", "todo"]


def test_card_lines_picks_the_lines_of_the_field_in_the_cards_order():
    assert ops_any_question.card_lines(MAIL_CARD, "to") == [["CARD_MAIL_TO", {"addresses": "dana.holt@clinic.example"}]]
    assert ops_any_question.card_lines(MAIL_CARD, "approve") == [["CARD_MAIL_SEND", {}]]
    assert ops_any_question.card_lines(MAIL_CARD, "other") == [] and ops_any_question.card_lines(MAIL_CARD, "place") == [] and ops_any_question.card_lines([], "to") == []
    assert ops_any_question.card_lines([["CARD_CAL_CHANGE", {"read_at": "x"}]], "approve") == [["PHONE_CAL_CHANGE", {"read_at": "x"}]]


# --- 12: the bridge -------------------------------------------------------------------------------------------------------------------------------------


def test_the_bridge_knows_the_card_that_is_the_last_message_and_none_in_every_other_case(bridge_world):
    mail_card(bridge_world)
    project = bridge_world.projects[0]
    chat = BRIDGE_SENDER
    assert bridge_world.bridge.waiting_card(project, chat) == 7
    [rec] = bridge_world.bridge.ledger.data["cards"]      # the ledger's own record: a change here is read by the next call
    item = bridge_world.items[7]
    sha = item["payload_sha256"]
    item["payload_sha256"] = "f" * 64      # the card changed since it was sent
    assert bridge_world.bridge.waiting_card(project, chat) is None
    item["payload_sha256"] = sha
    item["status"] = "resolved"            # closed
    assert bridge_world.bridge.waiting_card(project, chat) is None
    item["status"] = "open"
    kind = rec["kind"]
    rec["kind"] = "reminder"               # the last message is a reminder record
    assert bridge_world.bridge.waiting_card(project, chat) is None
    rec["kind"] = kind
    assert bridge_world.bridge.waiting_card(project, chat) == 7
    bridge_world.bridge.last_sent[chat] = "a-later-message"      # a later message ended it
    assert bridge_world.bridge.waiting_card(project, chat) is None
    bridge_world.bridge.last_sent[chat] = None
    assert bridge_world.bridge.waiting_card(project, chat) is None


def test_on_the_platform_whose_acts_are_replies_no_card_is_waiting(bridge_world):
    mail_card(bridge_world)
    bridge_world.caps(actions_need_reply=True)
    assert bridge_world.bridge.waiting_card(bridge_world.projects[0], BRIDGE_SENDER) is None


def test_a_card_that_is_not_whole_is_not_waiting(bridge_world):
    mail_card(bridge_world)
    [rec] = bridge_world.bridge.ledger.data["cards"]
    rec["whole"] = False
    assert bridge_world.bridge.waiting_card(bridge_world.projects[0], BRIDGE_SENDER) is None


def test_the_line_runs_with_the_card_held_on_its_thread_and_the_route_leg_does_not(bridge_world):
    mail_card(bridge_world)
    seen = []

    def say(project, **kw):
        seen.append((kw.get("text"), line_card.current()))
        return {"reply": "Noted.", "request_id": None, "pending_id": None, "ran": False, "queued": False}
    bridge_world.fake.answers["say"] = say
    project = bridge_world.projects[0]
    bridge_world.bridge.line(project, BRIDGE_SENDER, "where is this event?", None)()
    bridge_world.bridge.line(project, BRIDGE_SENDER, "and the second leg", None, route_pass="p")()      # the route leg does not
    assert seen == [("where is this event?", 7), ("and the second leg", None)]
    assert line_card.current() is None, "nothing is left held on the thread after the call"


def test_a_plain_line_after_a_card_reaches_the_operations_layer_with_the_card_held(bridge_world):
    mail_card(bridge_world)
    Revise(bridge_world, found=None)      # the line is no change of the card
    seen = []

    def say(project, **kw):
        seen.append(line_card.current())
        return {"reply": "Noted.", "request_id": None, "pending_id": None, "ran": False, "queued": False}
    bridge_world.fake.answers["say"] = say
    bridge_world.say("what does this card do?")
    assert wait_for(lambda: seen) and settle(bridge_world)
    assert seen == [7]
