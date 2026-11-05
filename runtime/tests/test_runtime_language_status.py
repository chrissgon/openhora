"""Status words and the headings code writes, said at the reading layer on a phone (package LR-1): a project whose language has a table sees the translated word
and heading in a sentence made for a person; the store, the operations layer, the logs and what a shell reads keep the English word, and a project with no
language sees today's text byte for byte. The closed list is in test_phrases_status.py. Offline, no model; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_language_status.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging import decision, world  # noqa: F401  (the stand-in world fixture)
from test_messaging_reminders import DENTIST, day  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_sender_profiles import OWNER, accept
from test_sender_profiles_bridge import lab  # noqa: F401  (the lab fixture: the real operations layer)

ops = st.load("ops")
cards = st.load("messaging_cards")
phrases = st.load("phrases")
PT_CFG = {"language": "pt-BR"}


def card_parts(text, cfg, kind, id):
    """A card is its header line (project, kind of the decision, number), a blank line, the title, a blank line and the body: returns (title, body)."""
    head, blank, title, blank_again, body = text.split("\n", 4)
    pk.assert_said(head, "HEADER", cfg, project="northwind-shop", kind=phrases.kind_word(kind, cfg), id=id)
    assert blank == "" and blank_again == "", text
    return title, body


def assert_pending_list(text, cfg, *entries):
    """The `/pending` reply: the first line is the project and the first entry, each other line one entry (a question's sentence, or the number, the kind and the heading of another
    decision as (kind, number, heading key, fields)), then the sentence that says how to dismiss one."""
    lines = text.split("\n")
    assert len(lines) == len(entries) + 1, text
    assert lines[0].startswith("northwind-shop: ")
    lines[0] = lines[0][len("northwind-shop: "):]
    for line, entry in zip(lines, entries):
        if entry[0] == "PEND_QUESTION":
            pk.assert_said(line, "PEND_QUESTION", cfg, **entry[1])
        else:
            kind, id, key, fields = entry
            prefix = f"#{id} {phrases.kind_word(kind, cfg)}: "
            assert line.startswith(prefix), line
            pk.assert_said(line[len(prefix):], key, cfg, **fields)
    pk.assert_said(lines[-1], "PEND_DISMISS_TYPED", cfg)


def asks(world, tag):
    if tag is None:
        world.config.pop("language", None)
    else:
        world.config["language"] = tag
    world.items[2] = decision("question", 2, title="The router asks", body="Which flow do you want?")
    world.items[3] = decision("question", 3, title="Hours", body="When do we open?")
    world.items[4] = decision("acceptance", 4, title="Delivery 2 was not routed after its brief", body="Accept that you read this.")
    world.bridge.tick()
    return [s["message"]["text"] for s in world.sent()]


def test_a_heading_code_wrote_whole_is_said_on_the_card_and_in_the_list_and_the_card_is_bound_to_the_stored_one(world):
    texts = asks(world, "pt-BR")
    title, body = card_parts(texts[0], PT_CFG, "question", 2)
    pk.assert_said(title, "TITLE_ROUTER_ASKS", PT_CFG)
    assert body.startswith("Which flow do you want?"), "a question that is not the router's own (no ending) keeps the heading code wrote"
    title, _body = card_parts(texts[1], PT_CFG, "question", 3)
    assert title == "Hours", "a title that is the person's or the model's is not touched"
    title, _body = card_parts(texts[2], PT_CFG, "acceptance", 4)
    pk.assert_said(title, "TITLE_REROUTE_FAILED", PT_CFG, k=2)
    stored = world.items[2]
    card = world.bridge.ledger.last_card(world.projects[0]["id"], 2, "830461975213")
    assert card["content_sha256"] == cards.sha256_text(phrases.text("TITLE_ROUTER_ASKS", None) + "\n\nWhich flow do you want?") == cards.content_sha256(stored), "the hash is of the stored text"
    pk.assert_said(stored["title"], "TITLE_ROUTER_ASKS", None)
    world.say("/pending")
    assert_pending_list(world.texts()[-1], PT_CFG, ("PEND_QUESTION", {"id": 2, "text": "Which flow do you want?"}), ("PEND_QUESTION", {"id": 3, "text": "When do we open?"}),
                        ("acceptance", 4, "TITLE_REROUTE_FAILED", {"k": 2}))


def test_the_body_of_an_unrecognised_route_is_stored_in_english_and_a_card_says_it_in_the_language_with_the_hash_unchanged(world):
    stored = ops._not_recognised(None, {"id": 3}, "the router's reply", "no route named", {})
    pk.assert_said(stored["body"], "BODY_NOT_NAMED", None, request=3)
    pk.assert_said(stored["title"], "TITLE_ROUTE_UNRECOGNISED", None)
    world.config["language"] = "pt-BR"
    world.items[6] = decision("question", 6, title=stored["title"], body=stored["body"])
    world.items[7] = decision("question", 7, title="Hours", body="The planning agent did not name a flow or a skill for request 3, but the shop opens at nine")
    world.bridge.tick()
    first, second = [s["message"]["text"] for s in world.sent()]
    title, body = card_parts(first, PT_CFG, "question", 6)
    pk.assert_said(title, "PEND_NOT_UNDERSTOOD_TITLE", PT_CFG)
    assert pk.said(body.split("\n")[0], "PHONE_NOT_UNDERSTOOD", PT_CFG)
    assert not pk.said(second, "BODY_NOT_NAMED", PT_CFG) and pk.said(second, "BODY_NOT_NAMED", None, request="3, but the shop opens at nine"), "a body that is not exactly the one code wrote is a person's or a model's text and is not touched"
    card = world.bridge.ledger.last_card(world.projects[0]["id"], 6, "830461975213")
    assert card["content_sha256"] == cards.sha256_text(stored["title"] + "\n\n" + stored["body"]), "the card is bound to the stored text"
    assert world.items[6]["body"] == stored["body"]
    world.config.pop("language")
    world.items[8] = decision("question", 8, title=stored["title"], body=stored["body"])
    world.bridge.tick()
    title, body = card_parts(world.sent()[-1]["message"]["text"], None, "question", 8)
    pk.assert_said(title, "PEND_NOT_UNDERSTOOD_TITLE", None)
    assert pk.said(body.split("\n")[0], "PHONE_NOT_UNDERSTOOD", None)


def test_the_same_decisions_in_a_project_with_no_language_or_a_tag_with_no_table_read_as_they_always_did(world):
    texts = asks(world, None)
    title, body = card_parts(texts[0], None, "question", 2)
    pk.assert_said(title, "TITLE_ROUTER_ASKS", None)
    assert body.startswith("Which flow do you want?")
    title, _body = card_parts(texts[2], None, "acceptance", 4)
    pk.assert_said(title, "TITLE_REROUTE_FAILED", None, k=2)
    world.say("/pending")
    assert_pending_list(world.texts()[-1], None, ("PEND_QUESTION", {"id": 2, "text": "Which flow do you want?"}), ("PEND_QUESTION", {"id": 3, "text": "When do we open?"}),
                        ("acceptance", 4, "TITLE_REROUTE_FAILED", {"k": 2}))


def test_a_tag_with_no_table_reads_as_english(world):
    texts = asks(world, "fr")
    title, _body = card_parts(texts[0], {"language": "fr"}, "question", 2)
    pk.assert_said(title, "TITLE_ROUTER_ASKS", {"language": "fr"})


def test_the_status_of_a_reminder_is_said_on_the_phone_and_stays_english_in_the_operations_layer_and_the_log(day):  # noqa: F811
    accept(day.path, language="pt-BR")
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.say(OWNER, "/forget 1")
    pk.assert_said(day.texts(OWNER)[-1], "NT_FORGOT_TEXT", PT_CFG, id=1, when="hoje, dom 18/10, às 15:00 (BRT)", text=DENTIST)  # validate: allow english-only -- the day words of a time are the value under test
    day.say(OWNER, "/forget 1")
    pk.assert_said(day.texts(OWNER)[-1], "RM_NOT_WAITING", PT_CFG, n=1, status="cancelado")
    with pytest.raises(ops.OpsError) as caught:
        ops.reminder_forget(day.path, 1, channel="terminal")
    assert pk.said(str(caught.value), "RM_NOT_WAITING", None, n=1, status="cancelled"), "the operations layer, and so the terminal, the MCP mode and the API, keep the store's word"
    assert not any("cancelado" in line for line in day.log) and not any("aprovado" in line for line in day.log)
    accept(day.path, language=None)
    day.say(OWNER, "/forget 1")
    pk.assert_said(day.texts(OWNER)[-1], "RM_NOT_WAITING", None, n=1, status="cancelled")
