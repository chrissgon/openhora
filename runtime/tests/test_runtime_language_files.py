"""The files a listed sender sends, in the project's language (package LR-1 over ATT-1b, runtime/phrases.py): the refusals before anything is fetched, the
card of a held file, the answer to a tap or a typed `/add` and `/discard`, the list of the files that wait, and what a phone is told of an error of the
operations layer. The operations layer is the real one over a real store, the converter and the messenger are the stand-ins of test_messaging_attach.py;
a project with no `language` gets the English sentences it always got. Offline, no model, no network; every name and id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_language_files.py
"""
from __future__ import annotations

import standin_tree as st
from test_attachments import IDENT, PDF, accept, case  # noqa: F401  (the project the attachment tests use)
from test_messaging_attach import card_action, make_world, world  # noqa: F401  (the stand-in world over a real store)

ops = st.load("ops")
attachments = st.load("attachments")
phrases = st.load("phrases")
PT = phrases.TABLE["pt-BR"]


def speak(world, tag):
    accept(world.case.path, language=tag)


def test_a_provider_that_takes_no_file_and_a_channel_without_the_group_are_told_in_portuguese(case, monkeypatch):  # noqa: F811
    w = make_world(case, monkeypatch, caps={"attachments": False})
    speak(w, "pt-BR")
    w.send([w.file()])
    assert w.texts() == ["A conexão deste aplicativo ainda não recebe arquivos."] and w.fetches() == []  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    w.reset()
    (w.folder / "caps.json").write_text('{"attachments": true, "max_attachment_bytes": 20971520}')
    w.messenger._caps = None
    accept(case.path, channels={"messaging": ["read", "talk"]}, policies=None, language="pt-BR")
    w.send([w.file()])
    assert w.texts() == ["Arquivos não são recebidos por este aplicativo neste projeto. Adicione na página ou no terminal (source-import)."]  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert w.fetches() == [] and case.rows() == []


def test_the_refusals_before_a_byte_is_fetched_are_in_portuguese(world):
    speak(world, "pt-BR")
    world.send([world.file("p1", "talk.ogg", 5000, "voice")])
    assert world.texts() == [PT["ATT_MEDIA"]] == ["Notas de voz, vídeos, áudios e figurinhas ainda não são aceitos, nem imagens que não sejam PNG, JPEG, WebP, GIF ou HEIC. "  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
                                                  "Envie uma foto ou imagem desses tipos para salvar no Drive ou no OneDrive, ou um PDF, um documento Word, uma planilha, "  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
                                                  "uma apresentação, uma página HTML ou um arquivo de texto para adicionar ao projeto."]  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    world.send([world.file("big", "Big.pdf", 30 * 1024 * 1024)])
    assert world.texts()[-1] == "Big.pdf tem 30,0 MiB; um arquivo deste aplicativo pode ter no máximo 20,0 MiB."
    before = len(world.texts())
    world.send([world.file()], text="please read the file")
    assert world.texts()[before].endswith("O texto enviado junto com um arquivo é lido só como um pedido para salvar; para o resto, use os botões do card dele.")  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert len(world.fetches()) == 1


def test_the_card_of_a_held_file_and_its_answers_are_in_portuguese(world):
    speak(world, "pt-BR")
    world.send([world.file("r1", "Q3 plan.pdf", len(PDF))])
    [message] = [s["message"] for s in world.sent()]
    assert message["text"] == (f"northwind-shop · arquivo #1\n\nRecebi Q3 plan.pdf ({attachments.size_text(len(PDF))}, pdf). O que faço?\n"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
                               "\"Adicionar ao projeto\" a transforma em um documento que o assistente pode ler em northwind-shop, como `q3-plan`.")  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert [(a["label"], a["id"].split(":")[1]) for a in message["actions"]] == [("Adicionar ao projeto", "add"), ("Descartar", "discard")]
    action = card_action(world, "add")
    world.reset()
    world.say("/pending")
    assert world.texts() == ["northwind-shop: nada pendente para você.",  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
                             "northwind-shop: arquivos esperando pela sua resposta\narquivo #1 Q3 plan.pdf: /add 1 ou /discard 1"]
    world.say(action=action)
    assert world.texts()[-1].splitlines()[0] == "Q3 plan.pdf adicionado como `q3-plan`, versão 1."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    world.say(action=action)
    assert world.texts()[-1] == "Esse arquivo tem o status adicionado: não está esperando pela sua resposta."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    world.say("/add 77")
    assert world.texts()[-1] == "Use o card que foi enviado a você (envie /pending)."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    world.say("/add")
    assert world.texts()[-1] == "Uso: /add <n>"


def test_a_typed_discard_is_answered_in_portuguese(world):
    speak(world, "pt-BR")
    world.put("r2", PDF + b"\n")
    world.send([world.file("r1"), world.file("r2", "Second.pdf")])
    world.say("/discard 2")
    assert world.texts()[-1] == "Second.pdf descartado."


def test_what_a_phone_is_told_of_an_error_of_the_operations_layer(world):
    phone = world.bridge.attach.phone
    speak(world, "pt-BR")
    assert phone(ops.OpsError("see /Users/someone/projects/x/ for it"), world.project) == PT["ATT_MACHINE"]
    assert phone(ops.OpsError("No file 3 waits for you."), world.project) == "Não há arquivo 3 esperando por você."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phone(ops.OpsError(attachments.REFUSED.format(name="a.docx", reason="it holds macros, which are never converted")), world.project) == (
        "a.docx não foi adicionado e foi apagado: contém macros, que nunca são convertidas.")  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phone(ops.OpsError("Send /add 3 or /discard 3."), world.project) == "Send /add 3 or /discard 3.", "a text the table does not know stays as the operations layer said it"
    assert phone(ops.OpsError("The sources folder cannot be opened", 3), world.project) == PT["ATT_MACHINE"]
    speak(world, None)
    assert phone(ops.OpsError("No file 3 waits for you."), world.project) == "No file 3 waits for you."
    assert phone(ops.OpsError("see /Users/someone/projects/x/ for it"), world.project) == attachments.MACHINE
    speak(world, "fr")
    assert phone(ops.OpsError("No file 3 waits for you."), world.project) == "No file 3 waits for you."


def test_an_english_project_gets_the_file_sentences_it_always_got(world):
    world.send([world.file("p1", "talk.ogg", 5000, "voice")])
    assert world.texts() == [attachments.MEDIA]
    world.send([world.file("r1", "Q3 plan.pdf", len(PDF))])
    assert world.texts()[-1].startswith(f"northwind-shop · file #1\n\nI received Q3 plan.pdf ({attachments.size_text(len(PDF))}, pdf). What should I do?\n")
    world.say(action=card_action(world, "add"))
    assert world.texts()[-1].splitlines()[0] == "Added Q3 plan.pdf as `q3-plan`, version 1."
    world.say("/add 77")
    assert world.texts()[-1] == "Act on the card sent to you (send /pending)."
