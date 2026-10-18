"""The messaging bridge in the project's language (package LR-1, runtime/phrases.py): the cards, the commands and their replies, the line about waiting
decisions, the notice of a message that could not be read, the waiting lines of a busy project (BQ-1) and the reminders (RM-1), on the stand-in
messenger. A project whose `language` is `pt-BR` gets Portuguese frames and replies; a project with no `language` gets exactly the English sentences
it always got (pinned here with exact strings); a tag with no table (`fr`) gets English. The decision's own text, the commands, the ids and the names of
the project never change. The table itself is in test_phrases.py, the files in test_runtime_language_files.py, the answers and the conversation in
test_runtime_language_ask.py. Offline, no model, no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_language.py
"""
from __future__ import annotations

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


ENGLISH = [
    ["This button is no longer valid. Send /pending."], [EN["HELP"]], ["Usage: /approve <id>"],
    ["Your lines go to northwind-shop. Projects: northwind-shop."], ["No such project. Projects: northwind-shop."], ["northwind-shop: nothing waits for you."],
    ["northwind-shop: #1 plan: Northwind shop\n#2 question: Northwind shop\n#3 review: Northwind shop"], ["Approved #1."], ["Rejected #1."], ["Answered #2."],
    ["Pending decision 2 is a question: approve takes a plan or an acceptance."], ["The hash you typed is not the one of the card you saw. Send /pending."],
    ["Act on the card sent to you (send /pending)."], ["Released #3."],
]
PORTUGUESE = [
    ["Este botão não é mais válido. Envie /pending."], [PT["HELP"]], ["Uso: /approve <id>"],  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    ["Suas mensagens vão para northwind-shop. Projetos: northwind-shop."], ["Esse projeto não existe. Projetos: northwind-shop."], ["northwind-shop: nada pendente para você."],  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    ["northwind-shop: #1 plano: Northwind shop\n#2 pergunta: Northwind shop\n#3 revisão: Northwind shop"], ["#1 aprovada."], ["#1 rejeitada."], ["#2 respondida."],  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    ["A decisão pendente 2 é do tipo pergunta: aprovar vale só para um plano ou um aceite."],  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    ["O hash que você digitou não é o do card que você viu. Envie /pending."],  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    ["Use o card que foi enviado a você (envie /pending)."], ["#3 liberada."],  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
]


def test_a_project_with_no_language_gets_the_english_sentences_it_always_got(world):
    assert replies(world, None) == ENGLISH


def test_a_portuguese_project_gets_portuguese_replies_and_the_commands_in_them_stay_the_same(world):
    assert replies(world, "pt-BR") == PORTUGUESE
    assert "/pending" in PORTUGUESE[0][0] and "/approve <id>" in PORTUGUESE[2][0]


def test_a_tag_with_no_table_gets_english_and_so_does_a_project_that_names_english(world):
    assert replies(world, "fr") == ENGLISH


def test_the_english_tag_is_english_too(world):
    assert replies(world, "en") == ENGLISH


# --- the cards -----------------------------------------------------------------------------------------------------------------------------------


def test_a_card_has_its_frames_in_portuguese_and_the_text_of_the_decision_is_not_touched(world):
    speak(world, "pt-BR")
    world.items[1] = decision("plan", 1)
    world.items[2] = decision("question", 2, title="Hours", body="When do we open?")
    world.bridge.tick()
    plan, question = [s["message"] for s in world.sent()]
    assert plan["text"] == f"northwind-shop · plano #1\n\nNorthwind shop\n\n{SECRET_TEXT}"
    assert [a["label"] for a in plan["actions"]] == ["Aprovar", "Rejeitar"]
    assert question["text"].startswith("northwind-shop · pergunta #2\n\nHours\n\nWhen do we open?")
    speak(world, None)
    world.items[3] = decision("plan", 3, plan_sha256="q" * 64)
    world.bridge.tick()
    english = world.sent()[-1]["message"]
    assert english["text"] == f"northwind-shop · plan #3\n\nNorthwind shop\n\n{SECRET_TEXT}" and [a["label"] for a in english["actions"]] == ["Approve", "Reject"]


def test_the_frames_of_a_card_the_policy_closes_are_in_portuguese(world):
    speak(world, "pt-BR")
    del world.config["channels"]
    world.config["messaging"]["page_url"] = "https://page.example/open"
    world.items[1] = decision("plan", 1)
    world.items[2] = decision("question", 2)
    world.bridge.tick()
    plan, question = [s["message"] for s in world.sent()]
    assert plan["actions"] == [] and PT["PAGE_LINE"] in plan["text"] and "Resolva isso na página ou no terminal." in plan["text"]  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert plan["link"] == {"label": "Abrir a página", "url": "https://page.example/open"}
    assert "Responda a esta mensagem com a sua resposta." in question["text"]


def test_a_card_with_no_buttons_offers_typed_lines_with_the_same_commands(world):
    speak(world, "pt-BR")
    world.caps(buttons=False)
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    text = world.sent()[0]["message"]["text"]
    assert "Envie /approve 1" in text and "Envie /reject 1" in text and "Send /" not in text
    world.caps(buttons=True, max_buttons=1)
    world.items[2] = decision("plan", 2, plan_sha256="r" * 64)
    world.bridge.tick()
    second = world.sent()[-1]["message"]
    assert [a["label"] for a in second["actions"]] == ["Aprovar"] and "Envie /reject 2" in second["text"]


def test_a_cut_text_and_a_text_that_follows_as_a_document_say_so_in_portuguese(world):
    speak(world, "pt-BR")
    world.caps(max_text=300, documents=False)
    world.items[1] = decision("plan", 1, body="x" * 2000)
    world.bridge.tick()
    assert world.sent()[0]["message"]["text"].rstrip().endswith("(continua na página)")
    world.caps(max_text=300, documents=True)
    world.items[2] = decision("plan", 2, body="y" * 2000, plan_sha256="s" * 64)
    world.bridge.tick()
    assert world.sent()[-1]["message"]["text"].rstrip().endswith("(o texto inteiro segue como documento)")
    assert world.sent()[-1]["message"]["document"]["text"].endswith("y" * 2000), "the file is the decision's own text"


def test_an_effect_card_says_where_to_approve_in_portuguese_and_the_command_is_not_translated(world):
    speak(world, "pt-BR")
    world.config["messaging"]["page_url"] = "https://page.example/open"
    world.items[7] = decision("effect", 7, title="Pull request", payload_sha256="e" * 64)
    world.bridge.tick()
    message = world.sent()[0]["message"]
    assert [a["label"] for a in message["actions"]] == ["Rejeitar"] and "Aprove na página ou no terminal:" in message["text"]
    command = bridge.scrub(operations.command_line("approve", world.projects[0]["path"], checkout=bridge.ROOT, pending_id=7, sha256="e" * 64))
    assert message["text"].rstrip().splitlines()[-1] == f"`{command}`" and "northwind-shop · efeito #7" in message["text"]
    world.say("/approve 7")
    assert world.calls("approve") == [] and world.texts()[-1].startswith("Efeitos são aprovados na página ou no terminal, com o hash:\n") and command in world.texts()[-1]  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_the_count_mode_names_the_kind_of_decision_in_the_language_and_carries_none_of_the_text(world):
    speak(world, "pt-BR")
    world.config["messaging"]["notices"] = "count"
    world.items[1] = decision("plan", 1, title="Secret title", body="Secret body")
    world.items[2] = decision("question", 2, title="Another secret", body="Another body")
    world.bridge.tick()
    blob = " ".join(world.texts())
    assert "Aguardando você: plano." in blob and "Aguardando você: pergunta." in blob and "ecret" not in blob and "body" not in blob  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_the_line_about_the_decisions_left_for_the_next_tick_is_in_portuguese(world):
    speak(world, "pt-BR")
    for number in range(1, 13):
        world.items[number] = decision("question", number, title=f"Q{number}")
    world.bridge.tick()
    assert world.sent()[-1]["message"]["text"] == "E mais 2 esperando. Envie /pending para listar."


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
    assert unread(lab)[-1] == PT["UNREAD_MANY"].format(n=3) == "3 mensagens enviadas a este canal não puderam ser lidas e foram deixadas de lado: nada foi feito com elas. Se alguma era sua, envie de novo."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
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
    assert lab.texts(OWNER) == [PT["QUEUED"], PT["STILL_WORKING"]] == ["Anotado: respondo a esta mensagem depois da atual.", "Ainda estou trabalhando na última mensagem."]
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
    assert lab.texts(OWNER) == ["Sem resposta: o projeto ficou ocupado por 30 minutos. Envie de novo."]
    assert lab.bridge.keep(lab.bridge.projects[0], OWNER, "again") is True
    lab.bridge.session_ready = lambda: False       # nothing starts: the line is still waiting when the bridge stops
    lab.bridge.close_queue()
    assert lab.texts(OWNER)[-1] == "Sem resposta: a ponte de mensagens parou. Envie de novo."


def test_a_command_the_busy_planning_agent_cannot_take_is_refused_in_the_language_too(lab, planner):  # noqa: F811
    configure(lab, [{"id": OWNER, "policy": "owner"}])
    accept(lab.path, language="pt-BR")
    planner.refusals = 1
    lab.say(OWNER, "/status")                       # a command is never kept: it is refused with the router's sentence
    assert settle(lab)
    assert lab.texts(OWNER) == [PT["RUN_BUSY"]] == ["O agente de planejamento está respondendo a outro pedido. Envie de novo daqui a pouco."]  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


# --- reminders (RM-1) ----------------------------------------------------------------------------------------------------------------------------------


def test_the_replies_to_the_reminder_commands_are_in_portuguese_and_the_words_of_the_person_are_not_touched(day):  # noqa: F811
    accept(day.path, language="pt-BR")
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    assert day.texts(OWNER)[-1] == f"Lembrete #1: hoje, dom 18/10, às 15:00 (BRT): {DENTIST}. Para desfazer: /forget 1."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    day.say(OWNER, "/remind")
    assert day.texts(OWNER)[-1] == PT["NT_ASK_WHEN_SLASH"] == "Quando? Ex.: /remind amanhã 13h corte de cabelo"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    day.say(OWNER, "/remind 25:00 call")
    assert day.texts(OWNER)[-1] == "25:00 não é uma hora do dia (00:00 a 23:59)."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    day.say(OWNER, "/remind 13:00 x")
    assert day.texts(OWNER)[-1] == "Lembrete #2: 13:00 de hoje já passou: amanhã, seg 19/10, às 13:00 (BRT): x. Para desfazer: /forget 2."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    day.say(OWNER, "/forget")
    assert day.texts(OWNER)[-1] == "Uso: /forget <n>"
    day.say(OWNER, "/reminders")
    assert day.texts(OWNER)[-1] == f"northwind-shop: lembretes pendentes (BRT)\n#1 2026-10-18 15:00 {DENTIST}\n#2 2026-10-19 13:00 x"
    day.say(OWNER, "/forget 99")
    assert day.texts(OWNER)[-1] == "Não há lembrete 99 esperando por você."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    day.say(OWNER, "/forget 2")
    assert day.texts(OWNER)[-1] == "Lembrete #2 cancelado."
    day.say(OWNER, "/forget 2")
    assert day.texts(OWNER)[-1] == "O lembrete 2 tem o status cancelado: não está esperando."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_a_due_reminder_goes_with_a_frame_in_the_language_and_the_late_mark_and_the_count_line_too(day):  # noqa: F811
    accept(day.path, language="pt-BR")
    day.say(OWNER, f"/remind 2026-10-19 09:00 {DENTIST}")
    day.clock.set("2026-10-19 14:00")
    day.bridge.tick()
    assert day.texts(OWNER)[-1] == f"Lembrete: {DENTIST} (marcado para 09:00)"
    day.say(OWNER, "/remind 2026-10-20 08:00 Third")
    day.clock.set("2026-10-20 15:00")
    day.bridge.tick()
    day.say(OWNER, "/reminders")
    assert day.texts(OWNER)[-1] == ("northwind-shop: nenhum lembrete pendente.\nNão enviados recentemente:\n"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
                                    "#2 2026-10-20 08:00 Third (perdido: a ponte de mensagens só o verificou mais de 6 horas depois do horário marcado)")
    listed(day, notices="count")
    accept(day.path, language="pt-BR")
    day.say(OWNER, "/remind 2026-10-21 08:00 Fourth")
    day.clock.set("2026-10-21 08:00")
    day.bridge.tick()
    assert day.texts(OWNER)[-1] == "Há um lembrete para agora (#3)."
    assert "Fourth" not in " ".join(day.texts(OWNER))


def test_an_english_project_gets_the_reminder_sentences_it_always_got(day):  # noqa: F811
    day.say(OWNER, f"/remind 15:00 {DENTIST}")
    assert day.texts(OWNER)[-1] == f"Reminder #1: today, Sun 18/10, at 15:00 (BRT): {DENTIST}. To undo: /forget 1."
    day.say(OWNER, "/forget 99")
    assert day.texts(OWNER)[-1] == "No reminder 99 waits for you."
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    assert day.texts(OWNER)[-1] == f"Reminder: {DENTIST}"
    for tag in ("fr", "pt"):
        accept(day.path, language=tag)
        day.say(OWNER, "/forget 99")
        assert day.texts(OWNER)[-1] == "No reminder 99 waits for you.", tag
