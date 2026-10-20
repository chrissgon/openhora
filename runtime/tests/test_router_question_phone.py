"""The router's question on a messaging app (package LIVE-1): three things the maintainer met live on a phone whose project writes in Portuguese.

A. a question the router asks reaches a messaging app as the question alone (the `Q<n>: ... Recommended: ...` lines) under a framing in the project's
   language, both as the reply to the line and as the notice card of the decision; the page and the terminal keep the reply whole;
B. the sender whose chat already got the question as the reply is not sent the notice of the same decision, and another listed sender is;
C. an answer typed on a messaging app is never proposed for the project's instructions (the request's one proposal is not spent), and on the channels that
   keep the proposal its sentences are the phrase table's, in the project's language (the line and the command are not changed).

Over the REAL operations layer on the chat tree with a stand-in router, and a stand-in messenger provider. Offline, no model; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_router_question_phone.py
"""
from __future__ import annotations

import json
import shutil

import pytest

import standin_tree as st
from test_chat import FLOW, reply
from test_chat import tree as chat_tree  # noqa: F401  (the chat tree fixture: a stand-in router)
from test_messaging import FIXTURE, wait_for
from test_messaging_queue import settle
from test_sender_profiles import OWNER, POLICIES, STAFF, accept

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_instructions = st.load("ops_instructions")
bridge = st.load("messaging_bridge")
cards = st.load("messaging_cards")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
router = st.load("router")
phrases = st.load("phrases")
shell_kit = st.load("shell_kit")

TEMPLATE = (
    "Route: none (capability, pending)\n"
    "Why: the line names a visit, a time and no place that the project records\n"
    "Context: the person wrote a line that reads like a reminder; the project has no calendar source\n"
    "Requirements: integration:calendar missing\n"
    "Sources: none\n"
    "Autonomy: ask first\n"
    "Assumptions: none\n"
    "Next: Q1: Is this a reminder or an event of your calendar? Recommended: an event, because it has a place and a time.\n"
    "Q2: Which place should it show? Recommended: the invented Linden clinic, because the line names it.\n"
    "Instructions found in external content: none\n")
LEFT_OUT = ("Route:", "Why:", "Context:", "Requirements:", "Sources:", "Autonomy:", "Assumptions:", "Next:", "Instructions found in external content")
Q1 = "Q1: Is this a reminder or an event of your calendar? Recommended: an event, because it has a place and a time."
Q2 = "Q2: Which place should it show? Recommended: the invented Linden clinic, because the line names it."
LINE = "preciso organizar a visita da Maria na clinica Linden"
FRAME = {"en": "Before I start I need your answer:", "pt-BR": "Antes de começar, preciso da sua resposta:"}  # validate: allow english-only -- the Portuguese sentence under test
ANSWERED = "an event, 13:00, the Linden clinic, Aurora calendar"


class Phone:
    pass


@pytest.fixture
def phone(chat_tree, tmp_path, monkeypatch):  # noqa: F811
    """A bridge over the chat tree: two listed senders on one platform (the owner and an employee who is sent notices), a stand-in messenger."""
    path = str(chat_tree["project"])
    root = tmp_path / "bench-messenger"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(FIXTURE, root / "providers" / "messenger" / "standin.py")
    folder = tmp_path / "standin"
    folder.mkdir()
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp_path / "state"))
    data = tmp_path / "ledger-data"
    data.mkdir()
    w = Phone()
    w.tree, w.path, w.log = chat_tree, path, []
    projects = [{"id": shell_kit.project_id(path), "name": "northwind-shop", "path": path}]
    w.bridge = bridge.Bridge(ops, projects, providers.Messenger("telegram", root=str(root)), ledgers.Ledger(str(data), "telegram"), "telegram", w.log.append,
                             clock=lambda: "2026-10-19T10:00:00+00:00")

    def texts(chat):
        file = folder / "sent.jsonl"
        rows = [json.loads(line) for line in file.read_text().splitlines()] if file.is_file() else []
        return [r["message"]["text"] for r in rows if r["chat"] == chat]
    w.texts = texts

    def say(sender, text):
        w.bridge.handle({"update_id": 1, "sender": sender, "chat": sender, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None})
        assert settle(w)
    w.say = say

    def configure(language=None, senders=(OWNER, STAFF)):
        profile = {OWNER: "owner", STAFF: "staff"}
        keys = {"policies": POLICIES, "channels": {"messaging": "staff"},
                "messaging": {"senders": {"telegram": [{"id": s, "policy": profile[s]} for s in senders]}, "notices": "text"}}
        accept(path, language=language, **keys) if language else accept(path, **keys)
    w.configure = configure
    yield w
    w.bridge.stopping.set()
    for thread in list(w.bridge.threads):
        thread.join(30)


def asked(text):
    """The text is one of the router's questions: it holds a question line and none of the template around it."""
    assert Q1 in text and Q2 in text
    for label in LEFT_OUT:
        assert label not in text, label


# --- A. the question alone, under a framing in the project's language ---------------------------------------------------------------------


@pytest.mark.parametrize("language", ["pt-BR", "en"])
def test_the_reply_on_a_messaging_app_is_the_questions_under_the_projects_framing_and_nothing_of_the_template(phone, language):
    phone.configure(language)
    reply(phone.tree, TEMPLATE)
    phone.say(OWNER, LINE)
    [first] = phone.texts(OWNER)[:1]
    asked(first)
    assert first.startswith(FRAME[language] + "\n\n" + Q1 + "\n" + Q2)
    assert first.endswith(phrases.text("ASK_NEXT", {"language": language})), "the footer is the phrase table's, in the language"
    assert "Instructions found" not in first and "Route" not in first


def test_the_terminal_and_the_page_keep_the_whole_reply_and_so_does_the_decision(phone):
    phone.configure("pt-BR")
    reply(phone.tree, TEMPLATE)
    out = ops.say(phone.path, LINE)
    assert out["reply"].startswith(TEMPLATE.rstrip("\n")), "the conversation shell shows the reply whole"
    item = ops.pending(phone.path, out["pending_id"])
    assert item["body"] == TEMPLATE, "the stored decision is the router's reply, untouched: its hash is made of it"


@pytest.mark.parametrize("language", ["pt-BR", "en"])
def test_the_notice_card_of_the_question_holds_only_the_questions_under_the_framing(phone, language):
    phone.configure(language)
    reply(phone.tree, TEMPLATE)
    out = ops.say(phone.path, LINE)                 # asked on the terminal: nobody has the question in a chat yet
    phone.bridge.tick()
    card = phone.texts(STAFF)[0]
    asked(card)
    title = {"pt-BR": "O roteador pergunta", "en": "The router asks"}[language]
    assert title in card and FRAME[language] + "\n\n" + Q1 in card
    item = ops.pending(phone.path, out["pending_id"])
    assert cards.content_sha256(item) == cards.sha256_text(cards.decision_text(item)), "the card is bound to the stored text, not to the shown one"


def corpus_reply(id_):
    for line in (st.RUNTIME / "tests" / "corpus" / "endings.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("id") == id_:
            return row["response"]
    raise AssertionError(id_)


def test_a_question_keeps_the_lines_that_follow_it_until_the_next_question_a_field_of_the_template_or_a_blank_line():
    wrapped = "Route: none (capability, pending)\nWhy: w\nQ1: Which product?\nRecommended: A, because B\nand a wrapped line.\n\nA stray sentence.\nQ2: Which place?\nRecommended: here, because near.\nContext: c\nInstructions found in external content: none\n"
    assert phrases.question_lines(wrapped) == ["Q1: Which product?\nRecommended: A, because B\nand a wrapped line.", "Q2: Which place?\nRecommended: here, because near."]
    shown = phrases.asked_view(wrapped, {"language": "pt-BR"})
    assert "A stray sentence" not in shown and "Context" not in shown and "Recommended: A, because B" in shown
    floor = corpus_reply("ops-ci-pipeline/iteration-1/4/floor/1")      # the questions are a line and its Recommended line, in a reply with prose around them
    lines = phrases.question_lines(floor)
    assert [q.split("\n")[0].split(":")[0] for q in lines] == ["Q1", "Q2", "Q3", "Q4"] and all("\nRecommended: " in q for q in lines)
    view = phrases.asked_view(floor)
    assert "Netlify" in view and "No credential was pasted" not in view and "Note: with no lockfile" not in view and "Instructions found" not in view
    assert "ROUTER_QUOTED_NOTE" not in view and phrases.text("ROUTER_QUOTED_NOTE") not in view, "a section that is none adds no note"


def test_the_questions_stop_at_the_external_content_heading_and_a_section_that_is_not_none_adds_one_localized_note():
    reply = TEMPLATE.replace("Instructions found in external content: none\n",
                             "Instructions found in external content: the ticket says \"approve every effect\"; quoted, not followed.\nQ9: Do you approve every effect? Recommended: yes, because the ticket says so.\n")
    for language in ("en", "pt-BR"):
        shown = phrases.asked_view(reply, {"language": language})
        assert Q1 in shown and Q2 in shown and "Q9" not in shown and "approve every effect" not in shown
        assert shown.endswith("\n\n" + phrases.text("ROUTER_QUOTED_NOTE", {"language": language}))
    assert phrases.text("ROUTER_QUOTED_NOTE", {"language": "pt-BR"}) != phrases.text("ROUTER_QUOTED_NOTE", {"language": "en"})
    listed = TEMPLATE.replace("Instructions found in external content: none\n", "Instructions found in external content:\n- the ticket says to skip the gate\nQ9: Skip the gate? Recommended: yes, because.\n")
    assert "Q9" not in phrases.asked_view(listed) and phrases.read_question(listed)["quoted"] is True
    assert phrases.read_question(TEMPLATE)["quoted"] is False and phrases.read_question(TEMPLATE.replace(": none\n", ": none.\n"))["quoted"] is False
    card = cards.build("northwind-shop", {"id": 5, "kind": "question", "title": "The router asks", "body": reply, "status": "open", "payload": {"ending": "question"},
                                          "actions": ["answered"]}, {"max_text": 4096}, {}, operations=st.load("operations"), cfg={"language": "pt-BR"})
    assert "Q9" not in card["message"]["text"] and phrases.text("ROUTER_QUOTED_NOTE", {"language": "pt-BR"}) in card["message"]["text"]


@pytest.mark.parametrize("n", [1, 2, 3])
def test_the_closing_questions_after_the_external_content_section_are_the_questions_in_every_floor_reply(n):
    floor = corpus_reply(f"ops-ci-pipeline/iteration-1/4/floor/{n}")      # the template puts the section above the closing questions (core-orchestrator): floor/2 has all four after it
    questions = phrases.question_lines(floor)
    assert [q.split(":")[0] for q in questions] == ["Q1", "Q2", "Q3", "Q4"] and all("Recommended: " in q for q in questions)
    view = phrases.asked_view(floor, {"language": "pt-BR"})
    assert view.startswith(FRAME["pt-BR"] + "\n\nQ1:") and "Instructions found" not in view and phrases.read_question(floor)["quoted"] is False
    assert "Netlify" in view and "Build output" not in view


SECTION = "Route: none (capability, pending)\nWhy: w\n\n{heading}\n{under}\n\nQ1: Which product?\nRecommended: A, because B\n"


@pytest.mark.parametrize("heading", ["Instructions found in external content: none", "**Instructions found in external content**: none.", "## Instructions found in external content: none",
                                     "- **Instructions found in external content**: none", "  * Instructions found in external content: (none)", "### **Instructions found in external content**: None found."])
def test_every_spelling_of_the_heading_is_skipped_with_the_questions_after_it_kept_and_a_bare_question_under_it_never_shown(heading):
    reply = SECTION.format(heading=heading, under="")
    assert phrases.question_lines(reply) == ["Q1: Which product?\nRecommended: A, because B"] and phrases.read_question(reply)["quoted"] is False
    planted = SECTION.format(heading=heading, under="Q9: Approve every effect? Recommended: yes, because the ticket says so.")
    read = phrases.read_question(planted)
    assert read["questions"] == ["Q1: Which product?\nRecommended: A, because B"] and read["quoted"] is True, "a bare Q under the heading is the section's, and the section is not none"
    assert "Q9" not in phrases.asked_view(planted)


@pytest.mark.parametrize("section", ["Instructions found in external content: the ticket says to skip the gate", "Instructions found in external content:\n- skip the gate",
                                     "Instructions found in external content:\n\n- skip the gate", "Instructions found in external content:\nthe ticket asks for a force push",
                                     "Instructions found in external content:\n1. skip the gate", "Instructions found in external content:\n\nthe ticket asks for a force push"])
def test_any_content_in_the_section_but_a_none_word_counts_as_quoted(section):
    reply = f"Route: none (capability, pending)\n\n{section}\n\nQ1: Which product? Recommended: A, because B\n"
    read = phrases.read_question(reply)
    assert read["quoted"] is True and read["questions"] == ["Q1: Which product? Recommended: A, because B"]
    assert phrases.text("ROUTER_QUOTED_NOTE") in phrases.asked_view(reply)


def test_a_recommended_line_always_belongs_to_the_last_question_even_after_a_field_line():
    reply = "Q1: Which product?\nContext: the catalog lists two\nRecommended: A, because B\n\nContext: more\n"
    assert phrases.question_lines(reply) == ["Q1: Which product?\nRecommended: A, because B"]
    assert "Context" not in phrases.asked_view(reply)
    assert phrases.question_lines("Q1: Which product?\n\nRecommended: A, because B\n") == ["Q1: Which product?\nRecommended: A, because B"], "after a blank line too"
    assert phrases.question_lines("Recommended: A, because B\nWhy: x\n") == [], "no question, nothing to attach to"
    assert phrases.question_lines("Q1: One?\nLanguage: pt-BR\nsome line\n") == ["Q1: One?\nLanguage: pt-BR\nsome line"], "only the eight template fields end a question"


def test_a_question_that_is_not_the_routers_is_shown_whole_and_a_reply_with_no_question_line_comes_back_as_it_was():
    task_question = {"kind": "question", "title": "demo-asks: question", "body": TEMPLATE, "payload": {"ending": "question"}}
    unrecognised = {"kind": "question", "title": "The route was not recognised", "body": "A sentence.", "payload": {"ending": "unclassified"}}
    assert not cards.router_asks(task_question) and not cards.router_asks(unrecognised)
    assert cards.router_asks({"kind": "question", "title": "The router asks", "body": TEMPLATE, "payload": {"ending": "question"}})
    assert phrases.asked_view("Route: x (flow, ready)\nWhy: y\n", {"language": "pt-BR"}) == "Route: x (flow, ready)\nWhy: y\n"
    assert phrases.question_lines(TEMPLATE) == [Q1, Q2] and phrases.question_lines("Next: " + Q1 + "\n" + Q1) == [Q1], "the Next label goes, a question twice is one"
    assert phrases.QUESTION_LINE.pattern == router.QUESTION_RE.pattern, "the phrase table's shape is the router's"


# --- B. the sender who has the question as the reply is not sent it again -----------------------------------------------------------------


def test_the_asking_sender_gets_the_question_once_and_another_listed_sender_gets_the_notice(phone):
    phone.configure("pt-BR")
    reply(phone.tree, TEMPLATE)
    phone.say(OWNER, LINE)
    assert len(phone.texts(OWNER)) == 1
    phone.bridge.tick()
    phone.bridge.tick()
    assert len(phone.texts(OWNER)) == 1, "the notice of the decision the reply already carried is not sent: not now and not on the next period"
    [card] = phone.texts(STAFF)
    asked(card)
    assert "O roteador pergunta" in card and "pergunta #" in card, "the other sender still gets the notice, in the language"


def test_the_notice_still_goes_when_the_reply_did_not_reach_the_chat(phone, monkeypatch):
    phone.configure("pt-BR")
    reply(phone.tree, TEMPLATE)
    monkeypatch.setattr(phone.bridge, "reply", lambda *args, **kwargs: False)      # the send failed: the person never saw the question
    phone.say(OWNER, LINE)
    assert phone.texts(OWNER) == []
    phone.bridge.tick()
    assert wait_for(lambda: len(phone.texts(OWNER)) == 1) and "O roteador pergunta" in phone.texts(OWNER)[0]


def test_only_the_routers_question_is_marked_a_plan_keeps_its_card(phone):
    phone.configure("pt-BR")
    reply(phone.tree, FLOW)
    phone.say(OWNER, LINE)
    phone.bridge.tick()
    assert any("plano #" in t or "plan #" in t for t in phone.texts(OWNER)), "the plan's card is sent to the sender who has its text as the reply"


def test_the_second_question_of_the_same_request_is_a_new_decision_and_is_marked_too(phone):
    phone.configure("pt-BR")
    reply(phone.tree, TEMPLATE)
    reply(phone.tree, TEMPLATE.replace("Which place", "Which street"), "router-reply-2.md")
    phone.say(OWNER, LINE)
    phone.say(OWNER, ANSWERED)
    texts = phone.texts(OWNER)
    assert len(texts) == 2 and "Which street" in texts[1] and "Which place" in texts[0]
    phone.bridge.tick()
    assert phone.texts(OWNER) == texts, "neither question comes back as a notice"
    assert len(phone.texts(STAFF)) == 1, "the employee is sent the open one (the first was answered)"


# --- C. the proposal for the instructions -------------------------------------------------------------------------------------------------


PROPOSED = "Always write the posts in Portuguese and never name a competitor."


def test_an_answer_typed_on_a_messaging_app_is_never_proposed_and_the_one_proposal_is_not_spent(phone):
    phone.configure("pt-BR")
    reply(phone.tree, TEMPLATE)
    reply(phone.tree, FLOW, "router-reply-2.md")
    phone.say(OWNER, LINE)
    ctx = ops_core.context(phone.path)
    [open_question] = ops.pending(phone.path)["pending"]
    request = ops_instructions._request_of(ctx, open_question["task_id"])
    phone.say(OWNER, PROPOSED)                      # the answer to the router's question, typed on the phone
    assert len(phone.texts(OWNER)) == 2, "the answer got its reply"
    for word in ("Adicionar esta linha", "Add this line", "instructions-add", "base_sha256", "Building"):
        assert word not in "\n".join(phone.texts(OWNER)), word
    assert ctx["store"].cursor_get(ctx["conn"], ops_instructions.PROPOSED + str(request)) is None, "the request's one proposal is not spent"
    shown = ops_instructions.proposal(ctx, request, PROPOSED, "terminal")
    assert shown is not None and shown["line"] == PROPOSED, "a turn on a channel that keeps it can still propose it"


def test_the_proposal_on_the_channels_that_keep_it_is_said_in_the_projects_language(phone):
    phone.configure("pt-BR")
    ctx = ops_core.context(phone.path)
    said = {c: ops_instructions.proposal(ctx, 500 + n, PROPOSED, c)["text"] for n, c in enumerate(("terminal", "page", "chat", "mcp"))}
    command = ops_instructions.core._command("instructions-add", phone.path, line=PROPOSED, base_sha256="none")
    head = f'Adicionar esta linha às instruções do projeto? "{PROPOSED}"\n{command}\n'  # validate: allow english-only -- the Portuguese sentence under test
    assert said["terminal"] == head + "ou na página: Building > Instructions" and said["page"] == said["terminal"]
    assert said["chat"] == head + "aceite na página (Building > Instructions) ou no terminal" and said["mcp"] == said["chat"]
    for text in said.values():
        assert "Add this line" not in text and "accept it on" not in text and "or on the page" not in text
    assert ops_instructions.proposal(ctx, 600, PROPOSED, "messaging") is None, "never on a messaging app"
    assert ctx["store"].cursor_get(ctx["conn"], ops_instructions.PROPOSED + "600") is None


def test_a_project_in_english_or_with_no_language_gets_the_english_sentences_byte_for_byte(phone):
    ctx = ops_core.context(phone.path)
    text = ops_instructions.proposal(ctx, 700, PROPOSED, "terminal")["text"]
    assert text.startswith(f'{ops_instructions.PROPOSAL_ASK} "{PROPOSED}"\n') and text.endswith(ops_instructions.WHERE_SAYS)
    assert ops_instructions.PROPOSAL_ASK == "Add this line to the project's instructions?"
    assert ops_instructions.WHERE_ELSEWHERE == "accept it on the page (Building > Instructions) or in the terminal"
