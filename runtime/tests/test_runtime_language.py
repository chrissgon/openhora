"""The messaging bridge in the project's language (package LR-1, runtime/phrases.py): the cards, the commands and their replies, the line about waiting
decisions, the notice of a message that could not be read, the waiting lines of a busy project (BQ-1) and the reminders (RM-1), on the stand-in
messenger. A project whose `language` is `pt-BR` gets Portuguese frames and replies; a project with no `language` gets exactly the English sentences
it always got (pinned here with exact strings); a tag with no table (`fr`) gets English. The decision's own text, the commands, the ids and the names of
the project never change. The table itself is in test_phrases.py, the files in test_runtime_language_files.py, the answers and the conversation in
test_runtime_language_ask.py. Offline, no model, no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_language.py
"""
from __future__ import annotations

import phrase_kit as pk
import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging import SECRET_TEXT, decision, wait_for, world  # noqa: F401  (the stand-in world fixture)
from test_messaging_queue import clocked, planner, settle  # noqa: F401  (the planner stand-in)
from test_messaging_reminders import DENTIST, day, listed  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_messaging_skip_notice import give
from test_sender_profiles import OWNER, accept
from test_sender_profiles_bridge import configure, lab  # noqa: F401  (the lab fixture: the real operations layer)

bridge = st.load("messaging_bridge")
phrases = st.load("phrases")
operations = st.load("operations")

EN, PT = phrases.TABLE["en"], phrases.TABLE["pt-BR"]
PT_CFG = {"language": "pt-BR"}


def speak(world, tag):
    """Set the project's language in the stand-in configuration (None leaves the key out, as every project without one)."""
    if tag is None:
        world.config.pop("language", None)
    else:
        world.config["language"] = tag


def step(world, line=None, action=None):
    """What the bridge sent in answer to one update: the new texts."""
    before = len(world.texts())
    world.say(line, action=action)
    return world.texts()[before:]


def replies(world, tag):
    """The same session in the language of `tag`: each reply, in order. The release of a delivery runs in a job, so it is waited for."""
    speak(world, tag)
    out = [step(world, action="99:approve"), step(world, "/help"), step(world, "/approve"), step(world, "/project"), step(world, "/project nowhere"), step(world, "/pending")]
    world.items[1], world.items[2], world.items[3] = decision("plan", 1), decision("question", 2), decision("review", 3)
    world.bridge.tick()
    world.fake.answers["approve"] = {"approved": True}
    out.append(step(world, "/pending"))
    world.items[5] = decision("plan", 5, plan_sha256="z" * 64)       # a decision no card was sent for
    out += [step(world, "/approve 1"), step(world, "/reject 1 no"), step(world, "/answer 2 yes"), step(world, "/approve 2"),
            step(world, "/approve 1 deadbeef"), step(world, "/approve 5")]
    before = len(world.texts())
    world.say("/release 3")
    assert wait_for(lambda: len(world.texts()) > before)
    out.append(world.texts()[before:])
    return out


def unread(lab):  # noqa: F811
    """The notices of a message that could not be read: the texts the lab's chat got that are not the cards of the decisions it holds."""
    return [t for t in lab.texts(OWNER) if "·" not in t]


def session(cfg):
    """What each reply of `replies` says in the language of `cfg`: for each step, the texts sent; a text is the (key, fields) it says whole, or the (key, fields) of each of its lines
    (a plain string is a line that is no sentence of the table: the number, the kind and the title of a decision)."""
    kind = lambda word: phrases.kind_word(word, cfg)      # noqa: E731  (the kind of a decision is a word of the table)
    return [
        [("STALE", {})], [("HELP", {})], [("USAGE_APPROVE", {})],
        [("PROJECT_NOW", {"name": "northwind-shop", "projects": "northwind-shop"})], [("PROJECT_NONE", {"projects": "northwind-shop"})], [("NOTHING_WAITS", {"name": "northwind-shop"})],
        [[f"northwind-shop: #1 {kind('plan')}: Northwind shop", ("PEND_QUESTION", {"id": 2, "text": "Northwind shop launch plan, the private paragraph"}),
          f"#3 {kind('review')}: Northwind shop", ("PEND_DISMISS_TYPED", {})]],
        [("APPROVED", {"id": 1})], [("REJECTED", {"id": 1})], [("ANSWERED", {"id": 2})],
        [("NOT_APPROVABLE", {"number": 2, "kind": kind("question")})], [("WRONG_HASH", {})],
        [("NO_CARD", {})], [("RELEASED", {"id": 3})],
    ]


def assert_session(got, cfg):
    """The replies of `replies` are the sentences of `session(cfg)`, by phrase key, nothing else."""
    expected = session(cfg)
    assert len(got) == len(expected), got
    for texts, specs in zip(got, expected):
        assert len(texts) == len(specs), texts
        for text, spec in zip(texts, specs):
            if isinstance(spec, tuple):
                pk.assert_said(text, spec[0], cfg, **spec[1])
                continue
            lines = text.split("\n")
            assert len(lines) == len(spec), text
            for line, want in zip(lines, spec):
                if isinstance(want, tuple):
                    pk.assert_said(line, want[0], cfg, **want[1])
                else:
                    assert line == want


def assert_labels(actions, cfg, *keys):
    """The labels of the buttons are the sentences of these phrase keys, in this order."""
    labels = [a["label"] for a in actions]
    assert len(labels) == len(keys), labels
    for label, key in zip(labels, keys):
        pk.assert_said(label, key, cfg)


def assert_header(text, cfg, kind, id, project="northwind-shop"):
    """A line of the card says its project, the kind of the decision (a word of the table) and its number."""
    pk.assert_said(text.split("\n")[0], "HEADER", cfg, project=project, kind=phrases.kind_word(kind, cfg), id=id)


def test_a_project_with_no_language_gets_the_english_sentences_it_always_got(world):
    assert_session(replies(world, None), None)


def test_a_portuguese_project_gets_portuguese_replies_and_the_commands_in_them_stay_the_same(world):
    got = replies(world, "pt-BR")
    assert_session(got, PT_CFG)
    assert "/pending" in got[0][0] and "/approve <id>" in got[2][0]


def test_a_tag_with_no_table_gets_english_and_so_does_a_project_that_names_english(world):
    assert_session(replies(world, "fr"), {"language": "fr"})


def test_the_english_tag_is_english_too(world):
    assert_session(replies(world, "en"), {"language": "en"})


# --- the cards -----------------------------------------------------------------------------------------------------------------------------------


def test_a_card_has_its_frames_in_portuguese_and_the_text_of_the_decision_is_not_touched(world):
    speak(world, "pt-BR")
    world.items[1] = decision("plan", 1)
    world.items[2] = decision("question", 2, title="Hours", body="When do we open?")
    world.bridge.tick()
    plan, question = [s["message"] for s in world.sent()]
    assert_header(plan["text"], PT_CFG, "plan", 1)
    assert plan["text"].partition("\n")[2] == f"\nNorthwind shop\n\n{SECRET_TEXT}"
    assert_labels(plan["actions"], PT_CFG, "LABEL_APPROVE", "LABEL_REJECT")
    assert_header(question["text"], PT_CFG, "question", 2)
    assert question["text"].partition("\n")[2].startswith("\nHours\n\nWhen do we open?")
    speak(world, None)
    world.items[3] = decision("plan", 3, plan_sha256="q" * 64)
    world.bridge.tick()
    english = world.sent()[-1]["message"]
    assert_header(english["text"], None, "plan", 3)
    assert english["text"].partition("\n")[2] == f"\nNorthwind shop\n\n{SECRET_TEXT}"
    assert_labels(english["actions"], None, "LABEL_APPROVE", "LABEL_REJECT")


def test_the_frames_of_a_card_the_policy_closes_are_in_portuguese(world):
    speak(world, "pt-BR")
    del world.config["channels"]
    world.config["messaging"]["page_url"] = "https://page.example/open"
    world.items[1] = decision("plan", 1)
    world.items[2] = decision("question", 2)
    world.bridge.tick()
    plan, question = [s["message"] for s in world.sent()]
    assert plan["actions"] == [] and pk.said(plan["text"], "PAGE_LINE", PT_CFG)
    assert set(plan["link"]) == {"label", "url"} and plan["link"]["url"] == "https://page.example/open"
    pk.assert_said(plan["link"]["label"], "PAGE_LABEL", PT_CFG)
    assert pk.said(question["text"], "REPLY_LINE", PT_CFG)


def test_a_card_with_no_buttons_ends_with_the_words_that_decide_it_and_a_second_act_is_a_typed_line(world):
    speak(world, "pt-BR")
    world.caps(buttons=False)
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    text = world.sent()[0]["message"]["text"]
    assert pk.said(text.splitlines()[-1], "REPLY_WORDS_LINE", PT_CFG) and "/approve" not in text and "Send " not in text
    world.caps(buttons=True, max_buttons=1)
    world.items[2] = decision("plan", 2, plan_sha256="r" * 64)
    world.bridge.tick()
    second = world.sent()[-1]["message"]
    assert_labels(second["actions"], PT_CFG, "LABEL_APPROVE")
    assert pk.said(second["text"], "SEND_LINE", PT_CFG, line="/reject 2")


def test_a_cut_text_and_a_text_that_follows_as_a_document_say_so_in_portuguese(world):
    speak(world, "pt-BR")
    world.caps(max_text=300, documents=False)
    world.items[1] = decision("plan", 1, body="x" * 2000)
    world.bridge.tick()
    assert pk.said(world.sent()[0]["message"]["text"].rstrip().splitlines()[-1], "CUT", PT_CFG)
    world.caps(max_text=300, documents=True)
    world.items[2] = decision("plan", 2, body="y" * 2000, plan_sha256="s" * 64)
    world.bridge.tick()
    assert pk.said(world.sent()[-1]["message"]["text"].rstrip().splitlines()[-1], "WHOLE", PT_CFG)
    assert world.sent()[-1]["message"]["document"]["text"].endswith("y" * 2000), "the file is the decision's own text"


def test_an_effect_card_says_where_to_approve_in_portuguese_and_the_command_is_not_translated(world):
    speak(world, "pt-BR")
    world.config["messaging"]["page_url"] = "https://page.example/open"
    world.items[7] = decision("effect", 7, title="Pull request", payload_sha256="e" * 64)
    world.bridge.tick()
    message = world.sent()[0]["message"]
    assert_labels(message["actions"], PT_CFG, "LABEL_REJECT")
    assert pk.said(message["text"], "EFFECT_LINE", PT_CFG)
    assert "cli.py" not in message["text"] and pk.said(message["text"], "HEADER", PT_CFG, project="northwind-shop", kind=phrases.kind_word("effect", PT_CFG), id=7)      # no command on a phone, and the kind is a plain word (LIVE-2)
    world.say("/approve 7")
    assert world.calls("approve") == []
    pk.assert_said(world.texts()[-1], "EFFECT_REPLY", PT_CFG, where=phrases.text("PHONE_WHERE_LINK", PT_CFG, url="https://page.example/open"))


def test_the_count_mode_names_the_kind_of_decision_in_the_language_and_carries_none_of_the_text(world):
    speak(world, "pt-BR")
    world.config["messaging"]["notices"] = "count"
    world.items[1] = decision("plan", 1, title="Secret title", body="Secret body")
    world.items[2] = decision("question", 2, title="Another secret", body="Another body")
    world.bridge.tick()
    blob = " ".join(world.texts())
    assert any(pk.said(text, "WAITS_COUNT", PT_CFG, kind=phrases.kind_word("plan", PT_CFG)) for text in world.texts())
    assert any(pk.said(text, "WAITS_COUNT", PT_CFG, kind=phrases.kind_word("question", PT_CFG)) for text in world.texts())
    assert "ecret" not in blob and "body" not in blob


def test_the_line_about_the_decisions_left_for_the_next_tick_is_in_portuguese(world):
    speak(world, "pt-BR")
    for number in range(1, 13):
        world.items[number] = decision("question", number, title=f"Q{number}")
    world.bridge.tick()
    pk.assert_said(world.sent()[-1]["message"]["text"], "MORE_LINE", PT_CFG, n=2)


# --- the notice of a message that could not be read ------------------------------------------------------------------------------------------------


def test_the_notice_of_a_message_that_could_not_be_read_is_in_the_projects_language(lab):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    give(lab, 1)
    lab.bridge.tick()
    assert unread(lab) == [EN["UNREAD_ONE"]]
    accept(lab.path, language="pt-BR")
    lab.bridge.unread_told.clear()
    give(lab, 3)
    lab.bridge.tick()
    pk.assert_said(unread(lab)[-1], "UNREAD_MANY", PT_CFG, n=3)
    lab.bridge.unread_told.clear()
    give(lab, 1)
    lab.bridge.tick()
    assert unread(lab)[-1] == PT["UNREAD_ONE"]


# --- the waiting lines of a busy project (BQ-1) -------------------------------------------------------------------------------------------------------


def test_the_sentences_of_a_waiting_line_are_in_the_projects_language(lab, planner):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    accept(lab.path, language="pt-BR")
    planner.hold = {0}
    lab.say(OWNER, "first")
    assert planner.reached(0).wait(10)
    lab.say(OWNER, "second")
    lab.say(OWNER, "third")
    queued, still_working = lab.texts(OWNER)
    pk.assert_said(queued, "QUEUED", PT_CFG)
    pk.assert_said(still_working, "STILL_WORKING", PT_CFG)
    planner.gate(0).set()
    assert settle(lab)
    assert lab.texts(OWNER)[2:] == ["Answer 0", "Answer 1"], "the answer of the planning agent is its own text"


def test_a_line_that_waited_too_long_and_a_line_left_when_the_bridge_stops_are_told_in_the_language(lab, planner):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    accept(lab.path, language="pt-BR")
    now = clocked(lab)
    assert lab.bridge.keep(lab.bridge.projects[0], OWNER, "waiting") is True
    now[0] += bridge.QUEUE_WAIT + 1
    lab.bridge.drain()
    [expired] = lab.texts(OWNER)
    pk.assert_said(expired, "QUEUE_EXPIRED", PT_CFG)
    assert lab.bridge.keep(lab.bridge.projects[0], OWNER, "again") is True
    lab.bridge.session_ready = lambda: False       # nothing starts: the line is still waiting when the bridge stops
    lab.bridge.close_queue()
    pk.assert_said(lab.texts(OWNER)[-1], "QUEUE_STOPPED", PT_CFG)


def test_a_command_the_busy_planning_agent_cannot_take_is_refused_in_the_language_too(lab, planner):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    accept(lab.path, language="pt-BR")
    planner.refusals = 1
    lab.say(OWNER, "/status")                       # a command is never kept: it is refused with the router's sentence
    assert settle(lab)
    [busy] = lab.texts(OWNER)
    pk.assert_said(busy, "RUN_BUSY", PT_CFG)


# --- reminders (RM-1) ----------------------------------------------------------------------------------------------------------------------------------


def test_the_replies_to_the_reminder_commands_are_in_portuguese_and_the_words_of_the_person_are_not_touched(day):  # noqa: F811
    accept(day.path, language="pt-BR")
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    pk.assert_said(day.texts(OWNER)[-1], "NT_SET_TEXT", PT_CFG, id=1, when="hoje, dom 18/10, às 15:00 (BRT)", text=DENTIST)  # validate: allow english-only -- the day words of a time are the value under test
    day.say(OWNER, "/remind")
    pk.assert_said(day.texts(OWNER)[-1], "NT_ASK_WHEN_SLASH", PT_CFG)
    day.say(OWNER, "/remind 25:00 call")
    pk.assert_said(day.texts(OWNER)[-1], "RM_NOT_A_TIME", PT_CFG, given="25:00")
    day.say(OWNER, "/remind 13:00 x")
    pk.assert_said(day.texts(OWNER)[-1], "NT_SET_TEXT", PT_CFG, id=2, text="x", when=phrases.text("NT_ROLLED", PT_CFG, time="13:00", when="amanhã, seg 19/10, às 13:00 (BRT)"))  # validate: allow english-only -- the day words of a time are the value under test
    day.say(OWNER, "/forget")
    pk.assert_said(day.texts(OWNER)[-1], "USAGE_FORGET", PT_CFG)
    day.say(OWNER, "/reminders")
    head, first, second = day.texts(OWNER)[-1].split("\n")
    assert head.startswith("northwind-shop: ") and pk.said(head[len("northwind-shop: "):], "RM_WAITING_HEAD", PT_CFG, zone="BRT")
    assert first == f"#1 hoje, dom 18/10, às 15:00: {DENTIST}" and second == "#2 amanhã, seg 19/10, às 13:00: x"  # validate: allow english-only -- the day words of a time are the value under test
    day.say(OWNER, "/forget 99")
    pk.assert_said(day.texts(OWNER)[-1], "RM_NO_SUCH", PT_CFG, n=99)
    day.say(OWNER, "/forget 2")
    pk.assert_said(day.texts(OWNER)[-1], "NT_FORGOT_TEXT", PT_CFG, id=2, when="amanhã, seg 19/10, às 13:00 (BRT)", text="x")  # validate: allow english-only -- the day words of a time are the value under test
    day.say(OWNER, "/forget 2")
    pk.assert_said(day.texts(OWNER)[-1], "RM_NOT_WAITING", PT_CFG, n=2, status="cancelado")


def test_a_due_reminder_goes_with_a_frame_in_the_language_and_the_late_mark_and_the_count_line_too(day):  # noqa: F811
    accept(day.path, language="pt-BR")
    day.say(OWNER, f"/remind 2026-10-19 09:00 {DENTIST}")
    day.clock.set("2026-10-19 14:00")
    day.bridge.tick()
    pk.assert_said(day.texts(OWNER)[-1], "RM_TEXT_LINE", PT_CFG, text=DENTIST + phrases.text("RM_TEXT_LATE", PT_CFG, at="09:00"))
    day.say(OWNER, "/remind 2026-10-20 08:00 Third")
    day.clock.set("2026-10-20 15:00")
    day.bridge.tick()
    day.say(OWNER, "/reminders")
    head, sent_head, third = day.texts(OWNER)[-1].split("\n")
    assert head.startswith("northwind-shop: ") and pk.said(head[len("northwind-shop: "):], "RM_NONE_WAIT", PT_CFG)
    pk.assert_said(sent_head, "RM_NOT_SENT_HEAD", PT_CFG)
    assert third.startswith("#2 hoje, ter 20/10, às 08:00: Third (") and third.endswith(")")  # validate: allow english-only -- the day words of a time are the value under test
    pk.assert_said(third[len("#2 hoje, ter 20/10, às 08:00: Third ("):-1], "RM_WHY_LATE", PT_CFG)  # validate: allow english-only -- the day words of a time are the value under test
    listed(day, notices="count")
    accept(day.path, language="pt-BR")
    day.say(OWNER, "/remind 2026-10-21 08:00 Fourth")
    day.clock.set("2026-10-21 08:00")
    day.bridge.tick()
    pk.assert_said(day.texts(OWNER)[-1], "RM_COUNT_LINE", PT_CFG, id=3)
    assert "Fourth" not in " ".join(day.texts(OWNER))


def test_an_english_project_gets_the_reminder_sentences_it_always_got(day):  # noqa: F811
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    pk.assert_said(day.texts(OWNER)[-1], "NT_SET_TEXT", None, id=1, when="today, Sun 18/10, at 15:00 (BRT)", text=DENTIST)
    day.say(OWNER, "/forget 99")
    pk.assert_said(day.texts(OWNER)[-1], "RM_NO_SUCH", None, n=99)
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    pk.assert_said(day.texts(OWNER)[-1], "RM_TEXT_LINE", None, text=DENTIST)
    for tag in ("fr", "pt"):
        accept(day.path, language=tag)
        day.say(OWNER, "/forget 99")
        pk.assert_said(day.texts(OWNER)[-1], "RM_NO_SUCH", {"language": tag}, n=99)
