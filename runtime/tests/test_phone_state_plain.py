"""A phone is not sent the state digest with an answer, a status says its titles in the language, and a file is not deleted from a message (slice S14, limit L62).

A. A direct turn of the planning agent ("thanks, that is all", a question it answers itself) used to end with the digest of the state (the progress of each request and what waits for the
   person) above the agent's answer. On a messaging app the reply is the answer alone (ops_say `_say_route`); the page and the terminal keep the digest.
B. Where the state IS asked, the titles of the requests and of what waits are the project's language: a title code wrote whole is said by its kind, never the stored English, and the two titles that
   name the platform's internals (the router asks, the route was not recognised) are said as what they mean (`ops_say._title`).
C. A line that asks to delete a file ("remova o arquivo logo do drive") is answered at once with one plain sentence, by code: no card, no request, no model (runtime/phone_delete.py).

THE ORACLE is phrase keys and their fields (runtime/tests/phrase_kit.py; the wording is pinned by the phrase snapshot), this file's own lists of lines, and the digest it must not see. It never calls the code under test to decide what is right; the vacuity cases plant the old
digest and show the oracle sees it. Over the REAL operations layer with a stand-in router; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_state_plain.py
"""
from __future__ import annotations

import pytest

import phone_said as ps
import phrase_kit as pk
import standin_tree as st
from test_ops_natural import KEY, accept, router_says, with_senders, world  # noqa: F401  (the real-operations world fixture)

ops = st.load("ops")
ops_say = st.load("ops_say")
phone_delete = st.load("phone_delete")
phrases = st.load("phrases")
PT = {"language": "pt-BR"}

DIRECT = "Route: none (direct)\nWhy: a thanks\nNext: Claro, o arquivo continua no Drive.\n"
ANSWER = "Claro, o arquivo continua no Drive."  # validate: allow english-only -- the Portuguese sentence under test
# literal: the words of the old digest that a phone must not show (the text is the limit)
DIGEST_MARKS = ("tarefas concluídas", "O que espera por você", "Proposes", "O agente de planejamento propõe", "0 of", "Nothing is waiting")  # validate: allow english-only -- Portuguese marks of the old digest


def phone(world, line):
    return ops.say(world["path"], line, channel="messaging", sender=KEY["owner"])


def digest_marks(text: str) -> list:
    return [m for m in DIGEST_MARKS if m in text]


# --- A. the answer alone ---------------------------------------------------------------------------------------------------------------------------------


def test_a_direct_turn_on_a_phone_is_the_answer_alone_and_the_page_keeps_the_digest(world):
    with_senders(world)
    accept(world["path"], language="pt-BR")
    router_says(world, DIRECT)
    out = phone(world, "Obrigado, era só isso.")  # validate: allow english-only -- the Portuguese line under test
    assert out["reply"] == ANSWER and digest_marks(out["reply"]) == []
    page = ops.say(world["path"], "Obrigado, era só isso.", channel="page")["reply"]  # validate: allow english-only -- the Portuguese line under test
    assert page.endswith(phrases.text("PROPOSES", PT) + ANSWER), "the page and the terminal keep what they always showed"  # validate: allow english-only -- the Portuguese text under test


def test_vacuity_the_old_digest_is_noticed_by_the_oracle():
    old = 'Pedido 20, "Mail: send from your account": 0 de 1 tarefas concluídas.\nO que espera por você: pergunta "The router asks" (decisão 25).\n\nO agente de planejamento propõe: ' + ANSWER  # validate: allow english-only -- the live digest of the maintainer's screen
    assert digest_marks(old) == ["tarefas concluídas", "O que espera por você", "O agente de planejamento propõe"] and digest_marks(ANSWER) == []  # validate: allow english-only -- the Portuguese text under test


# --- B. a status in the language -------------------------------------------------------------------------------------------------------------------------


class Reads:
    """The two reads state_reply asks of the operations layer, with the stored (English) titles a project holds."""
    @staticmethod
    def status(project):
        return {"requests": [
            {"id": 20, "title": "Mail: send from your account", "state": "waiting", "tasks": [{"id": 21, "title": "Mail: send from your account", "state": "waiting", "note": None}]},
            {"id": 26, "title": "Files: save the file you sent", "state": "waiting", "tasks": [{"id": 27, "title": "Files: save the file you sent", "state": "ready", "note": None}]}], "held": []}

    @staticmethod
    def progress(project):
        return {"progress": {"waiting_for_you": [
            {"kind": "question", "title": "The route was not recognised", "pending_id": 14}, {"kind": "question", "title": "The router asks", "pending_id": 25},
            {"kind": "plan", "title": "Plano do mercado", "pending_id": 30}]}}


def digest_lines(cfg):
    """The status of `Reads` as the lines a phone is told, in the language of `cfg`: (phrase key, fields) per line. A title code wrote whole, and the two that name the platform's
    internals, are said as the words of the table; a field that holds another sentence is that sentence said in the same language."""
    def t(key, **fields):
        return phrases.text(key, cfg, **fields)
    mail, save = t("TITLE_MAIL_SEND"), t("TITLE_FILE_SAVE")
    items = "; ".join([t("STATE_WAIT_ITEM", kind=t("KIND_QUESTION"), title=t("PEND_NOT_UNDERSTOOD_TITLE"), id=14), t("STATE_WAIT_ITEM", kind=t("KIND_QUESTION"), title=t("PEND_CARD_TITLE"), id=25),
                       t("STATE_WAIT_ITEM", kind=t("KIND_PLAN"), title="Plano do mercado", id=30)])
    return [("STATE_PROGRESS", {"id": 20, "title": mail, "done": 0, "total": 1, "names": ""}), ("STATE_WAITING", {"names": mail}),
            ("STATE_PROGRESS", {"id": 26, "title": save, "done": 0, "total": 1, "names": ""}), ("STATE_READY", {"id": 27, "title": save, "held": ""}),
            ("STATE_WAITS", {"items": items})]


def digest_said(text, cfg):
    """True when the lines of `text` are, in order, the lines of `digest_lines`."""
    lines = text.split("\n")
    expected = digest_lines(cfg)
    return len(lines) == len(expected) and all(pk.said(line, key, cfg, **fields) for line, (key, fields) in zip(lines, expected))


def test_a_status_says_the_titles_code_wrote_in_the_language_and_the_internal_ones_as_what_they_mean(monkeypatch):
    monkeypatch.setattr(ops_say, "_ops", lambda: Reads)
    shown = ops_say.state_reply("project", cfg=PT)
    assert digest_said(shown, PT), shown
    for stored in ("Mail: send from your account", "Files: save the file you sent", "The route was not recognised", "The router asks"):
        assert stored not in shown, stored
    assert not [w for w in ("rota", "roteador", "route", "router") if w in shown.lower()]


def test_the_same_status_in_english_says_the_plain_titles_too(monkeypatch):
    monkeypatch.setattr(ops_say, "_ops", lambda: Reads)
    shown = ops_say.state_reply("project", cfg={})
    assert digest_said(shown, {}) and "router" not in shown.lower(), shown


def test_vacuity_without_the_plain_titles_the_internal_words_come_back_and_the_oracle_sees_them(monkeypatch):
    monkeypatch.setattr(ops_say, "_ops", lambda: Reads)
    monkeypatch.setattr(ops_say, "PLAIN_TITLES", {})
    old = ops_say.state_reply("project", cfg=PT)
    assert not digest_said(old, PT) and "roteador" in old.lower() and "rota" in old.lower()


# --- C. a file is not deleted from a message -------------------------------------------------------------------------------------------------------------


DELETE_LINES = ["Remova o arquivo openhora-mark do drive", "Remova o arquivo openhora-mark.png do drive", "Remova o arquivo openhora-mark do drive em /openhora", "remova o arquivo da pasta /openhora",  # validate: allow english-only -- the lines under test
                "Remova openhora-mark.png do onedrive", "apague o logo.png da pasta Marca", "Apaga a foto de ontem", "por favor exclua o documento antigo do google drive", "jogue o arquivo na lixeira",  # validate: allow english-only -- the lines under test
                "mova o arquivo logo para a lixeira", "tire o arquivo openhora-mark do drive", "exclui as imagens da pasta fotos",  # validate: allow english-only -- the lines under test
                "Delete the file report.pdf", "please remove the photo from my drive", "can you erase the document", "move the file to the trash", "Borra el archivo viejo del drive", "Elimina la imagen",  # validate: allow english-only -- the lines under test
                "Supprime le fichier du dossier", "Efface la photo", "Lösche die Datei bitte aus dem Ordner", "Entferne das Dokument", "Cancella il file dal drive", "Elimina l'immagine"]  # validate: allow english-only -- the lines under test
NOT_DELETE_LINES = ["remova o evento de amanhã", "Remova o corte de cabelo de amanhã da agenda", "remova o corte de cabelo da agenda", "apague o evento de sexta", "apague o email com o documento anexo",  # validate: allow english-only -- the lines under test
                    "apague o e-mail do João", "mova o email para a lixeira", "tire o evento da agenda", "delete the meeting from the calendar", "apague o lembrete",  # validate: allow english-only -- the lines under test
                    "não apague o arquivo", "do not delete the file", "como apagar um arquivo?", "salva o arquivo no drive", "o arquivo foi apagado", "/delete arquivo", "Delete",  # validate: allow english-only -- the lines under test
                    "send the file to Maria", "remova a cláusula do contrato", "mostre o arquivo openhora-mark do drive", "descarta o arquivo", "discard the file"]      # the last two are the words of a held file's card (messaging_attach.line)  # validate: allow english-only -- the lines under test


@pytest.mark.parametrize("line", DELETE_LINES)
def test_a_request_to_delete_a_file_is_known_in_six_languages(line):
    assert phone_delete.asks(line) is True, line


@pytest.mark.parametrize("line", NOT_DELETE_LINES)
def test_a_line_that_is_not_a_request_to_delete_a_file_is_not_taken(line):
    assert phone_delete.asks(line) is False, line


@pytest.mark.parametrize("language,key", [("pt-BR", "pt-BR"), ("en", "en")])
def test_on_a_phone_a_request_to_delete_a_file_gets_the_plain_sentence_and_opens_nothing(world, language, key):
    with_senders(world)
    accept(world["path"], language=language)
    for line in ("Remova o arquivo openhora-mark do drive", "Delete the file openhora-mark from the drive"):
        out = phone(world, line)
        assert ps.alone(out["reply"], "PHONE_NO_FILE_DELETE", {"language": language}) and out["ran"] is False and out["request_id"] is None and out["pending_id"] is None
    assert st.calls(world["adapter"]) == [], "no model ran"
    assert ops.status(world["path"])["requests"] == [] and ops.pending(world["path"])["pending"] == []


def test_vacuity_the_oracle_notices_a_line_that_slips_through_and_a_line_that_is_caught_by_mistake():
    assert phone_delete.asks("Remova o arquivo openhora-mark do drive") and not phone_delete.asks("Mostre o arquivo openhora-mark do drive")
    assert len(DELETE_LINES) >= 20 and len(NOT_DELETE_LINES) >= 8 and not set(DELETE_LINES) & set(NOT_DELETE_LINES)
    assert [line for line in NOT_DELETE_LINES if phone_delete.asks(line)] == [], "the event and mail lines are not caught"
    assert [line for line in DELETE_LINES if not phone_delete.asks(line)] == [], "no file line slips through"
