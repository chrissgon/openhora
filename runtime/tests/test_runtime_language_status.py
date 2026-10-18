"""Status words and the headings code writes, said at the reading layer on a phone (package LR-1): a project whose language has a table sees the translated word
and heading in a sentence made for a person; the store, the operations layer, the logs and what a shell reads keep the English word, and a project with no
language sees today's text byte for byte. The closed list is in test_phrases_status.py. Offline, no model; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_language_status.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging import decision, world  # noqa: F401  (the stand-in world fixture)
from test_messaging_reminders import DENTIST, day  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_sender_profiles import OWNER, accept
from test_sender_profiles_bridge import lab  # noqa: F401  (the lab fixture: the real operations layer)

ops = st.load("ops")
cards = st.load("messaging_cards")


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
    assert texts[0].startswith("northwind-shop · pergunta #2\n\nO roteador pergunta\n\nWhich flow do you want?")
    assert texts[1].startswith("northwind-shop · pergunta #3\n\nHours\n\n"), "a title that is the person's or the model's is not touched"
    assert texts[2].startswith("northwind-shop · aceite #4\n\nA entrega 2 não foi encaminhada depois do briefing\n\n")
    stored = world.items[2]
    card = world.bridge.ledger.last_card(world.projects[0]["id"], 2, "4242")
    assert card["content_sha256"] == cards.sha256_text("The router asks\n\nWhich flow do you want?") == cards.content_sha256(stored), "the hash is of the stored text"
    assert stored["title"] == "The router asks"
    world.say("/pending")
    assert world.texts()[-1] == ("northwind-shop: #2 pergunta: O roteador pergunta\n#3 pergunta: Hours\n#4 aceite: A entrega 2 não foi encaminhada depois do briefing")


def test_the_same_decisions_in_a_project_with_no_language_or_a_tag_with_no_table_read_as_they_always_did(world):
    texts = asks(world, None)
    assert texts[0].startswith("northwind-shop · question #2\n\nThe router asks\n\nWhich flow do you want?")
    assert texts[2].startswith("northwind-shop · acceptance #4\n\nDelivery 2 was not routed after its brief\n\n")
    world.say("/pending")
    assert world.texts()[-1] == ("northwind-shop: #2 question: The router asks\n#3 question: Hours\n#4 acceptance: Delivery 2 was not routed after its brief")


def test_a_tag_with_no_table_reads_as_english(world):
    texts = asks(world, "fr")
    assert texts[0].startswith("northwind-shop · question #2\n\nThe router asks\n\n")


def test_the_status_of_a_reminder_is_said_on_the_phone_and_stays_english_in_the_operations_layer_and_the_log(day):  # noqa: F811
    accept(day.path, language="pt-BR")
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    day.say(OWNER, "/forget 1")
    assert day.texts(OWNER)[-1] == "Lembrete #1 cancelado."
    day.say(OWNER, "/forget 1")
    assert day.texts(OWNER)[-1] == "O lembrete 1 tem o status cancelado: não está esperando."
    with pytest.raises(ops.OpsError) as caught:
        ops.reminder_forget(day.path, 1, channel="terminal")
    assert str(caught.value) == "Reminder 1 is cancelled, not waiting.", "the operations layer, and so the terminal, the MCP mode and the API, keep the store's word"
    assert not any("cancelado" in line for line in day.log) and not any("aprovado" in line for line in day.log)
    accept(day.path, language=None)
    day.say(OWNER, "/forget 1")
    assert day.texts(OWNER)[-1] == "Reminder 1 is cancelled, not waiting."
