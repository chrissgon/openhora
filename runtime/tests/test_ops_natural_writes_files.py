"""The files family of the natural writes with the project (package NR-5a: runtime/ops_natural_files.py): a new file, a new revision of a file that is a source and the saving of a
file a sender sent, each opened as the card of its exact content by the operation's own function (W4a). Over the real operations layer and the W4a stand-in services on loopback
(test_files_write.py's world); nothing is written by a line, no Google or Microsoft host is called, no model runs. Every name and file is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_natural_writes_files.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_calendar_write import rows  # noqa: F401
from test_files_write import OTHER, PDF, SENDER, hold, item_of, register, seed_drive, world  # noqa: F401  (the files world)
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
drafts = st.load("drafts")
account_start = st.load("account_start")
phrases = st.load("phrases")

OWNER = "telegram:4242"
OTHERS = "telegram:777"
PLAIN = "telegram:6161"
PROFILES = {"owner": ["read", "talk", "files-write"], "other": ["read", "talk", "files-write"], "plain": ["read", "talk"]}
IDS = {"owner": "4242", "other": "777", "plain": "6161"}
OPEN = "waits for your approval"


@pytest.fixture(autouse=True)
def forget():
    drafts.clear()
    yield
    drafts.clear()


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


@pytest.fixture
def spy(monkeypatch):
    seen = []
    real = account_start.start

    def start(project, kind, args, **kw):
        seen.append((kind, dict(args), dict(kw)))
        return real(project, kind, args, **kw)
    monkeypatch.setattr(account_start, "start", start)
    return seen


def policy(world):
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw["policies"] = PROFILES
    raw["channels"] = {"page": ["read", "files-write"]}
    raw["messaging"] = {"senders": {"telegram": [{"id": IDS[name], "policy": name} for name in PROFILES]}}
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def phone(world, text, sender=OWNER):
    return ops.natural_write(world["path"], text, channel="messaging", sender=sender)


def body(world, out):
    return ops.pending(world["path"], out["resend"])["body"]


def test_a_file_the_sender_sent_is_saved_by_a_line_that_names_it_and_the_card_is_the_w4a_save_card(world, clock, spy):
    policy(world)
    hold(world, sender="4242")
    out = phone(world, "salva esse pdf no drive")
    assert out["resend"] and OPEN in out["reply"] and out["asked"] is False
    text = body(world, out)
    assert "Contract.pdf" in text and "Google Drive" in text
    assert [kind for kind, _, _ in spy] == ["file-write"] and spy[0][1]["operation"] == "save" and spy[0][1]["attachment"] == 1 and spy[0][2]["sender"] == OWNER
    assert world["gd"].requests == [] or all(r["method"] == "GET" or r["path"].endswith("/token") for r in world["gd"].requests), "a card writes nothing"


def test_the_kind_the_line_names_picks_among_the_senders_files_several_are_listed_and_none_is_said(world, clock, spy):
    policy(world)
    none = phone(world, "salva esse pdf no drive")
    assert none["reply"] == phrases.text("NW_NO_HELD", None) and spy == []
    hold(world, name="Contract.pdf", sender="4242")
    hold(world, data=b"PK-docx", name="Minutes.docx", sender="4242", kind="docx")
    only_pdf = phone(world, "salva esse pdf no drive")
    assert "Contract.pdf" in body(world, only_pdf)
    nothing = phone(world, "salva essa planilha no drive")
    assert nothing["reply"] == phrases.text("NW_NO_HELD_KIND", None, kind="xlsx") and spy[-1][1]["attachment"] == 1
    which = phone(world, "salva esse arquivo no drive")
    assert which["reply"] == phrases.text("NW_WHICH_FILE", None) and which["cards"] == [1, 2] and not which["asked"] and "resend" not in which, \
        "several files: their cards come back, with no numbered question and no draft"
    assert drafts.count() == 0


def test_a_file_someone_else_sent_is_never_named_nor_saved(world, clock, spy):
    policy(world)
    hold(world, name="Secret.pdf", sender="777")
    mine = phone(world, "salva esse pdf no drive")
    assert mine["reply"] == phrases.text("NW_NO_HELD", None) and "Secret" not in mine["reply"] and spy == []
    numbered = phone(world, "salva o anexo 1")
    assert numbered["reply"] == phrases.text("ATT_NO_SUCH", None, n=1) and spy == [], "a number the sender did not send is a file that does not exist"
    theirs = phone(world, "salva esse pdf no drive", OTHERS)
    assert "Secret.pdf" in body(world, theirs)


def test_a_new_file_needs_its_name_and_its_text_in_the_line_and_the_folder_is_a_name_the_account_lists(world, clock, spy):
    policy(world)
    out = phone(world, "cria um arquivo chamado ideias.md na pasta cv no drive com o texto: comprar tinta azul")
    text = body(world, out)
    assert "ideias.md" in text and "comprar tinta azul" in text and "Google Drive" in text
    assert spy[0][1]["operation"] == "create" and spy[0][1]["name"] == "ideias.md" and spy[0][1]["folder"] == "cv" and spy[0][1]["content"] == "comprar tinta azul"
    unknown = phone(world, "cria um arquivo chamado ideias2.md na pasta contratos no drive com o texto: x")
    assert unknown["asked"] and "I do not have the folder 'contratos'" in unknown["reply"] and "default, cv" in unknown["reply"]
    chosen = phone(world, "cv")
    assert "ideias2.md" in body(world, chosen)


def test_two_accounts_with_folders_are_asked_and_a_name_with_no_extension_is_asked_never_chosen(world, clock, spy):
    policy(world)
    first = phone(world, "cria uma nota chamada compras com o texto: pão e leite")
    assert first["asked"] and first["reply"].startswith("Which account?")
    second = phone(world, "microsoft")
    assert second["asked"] and "What is the file name?" in second["reply"] and spy == []
    third = phone(world, "compras.txt")
    assert "compras.txt" in body(world, third) and "OneDrive" in body(world, third) and "pão e leite" in body(world, third)


def test_a_google_doc_is_made_in_the_google_drive_with_its_word(world, clock, spy):
    policy(world)
    out = phone(world, "cria um documento google chamado roteiro com o texto: abertura e fechamento")
    assert spy[0][1]["name"] == "roteiro.gdoc" and spy[0][1]["account"] == "google" and "Google Doc" in body(world, out)


def test_a_new_revision_names_the_source_by_words_and_the_card_shows_the_revision_it_replaces(world, clock, spy):
    policy(world)
    seed_drive(world)
    out = phone(world, "substitui o texto do arquivo cv por: # CV 2026\n\nNova linha.")
    assert spy[0][1]["operation"] == "replace" and spy[0][1]["file"] == "cv" and spy[0][1]["content"] == "# CV 2026\n\nNova linha."
    none = phone(world, "substitui o texto do arquivo passaporte por: nada")
    assert none["reply"] == phrases.text("NAT_NO_SOURCE", None) and len(spy) == 1
    assert out["resend"]


def test_a_profile_without_files_write_gets_the_typed_sentence(world, clock, spy):
    policy(world)
    hold(world, sender="6161")
    out = phone(world, "salva esse pdf no drive", PLAIN)
    assert out["reply"].startswith("error: /file-save is not enabled for this channel") and spy == []


@pytest.mark.parametrize("channel, carried", [(None, "terminal"), ("page", "page")])
def test_a_new_file_opens_its_card_from_the_terminal_shell_and_the_page_with_the_real_carrying_channel(world, clock, spy, channel, carried):
    policy(world)
    reply = ops.say(world["path"], "cria um arquivo chamado ideias.md no drive com o texto: comprar tinta azul", channel=channel)["reply"]
    assert OPEN in reply and spy and spy[-1][2]["channel"] == carried and spy[-1][1]["operation"] == "create"
    held = hold(world, sender="4242")
    saved = ops.say(world["path"], "salva o anexo %d no drive" % held, channel=channel)["reply"]
    assert OPEN in saved and spy[-1][1]["operation"] == "save" and spy[-1][2]["channel"] == carried


def test_a_file_name_that_fails_the_check_is_asked_again_once_and_then_given_up_so_no_question_loops(world, clock, spy):
    policy(world)
    phone(world, "cria uma nota chamada compras com o texto: pão e leite")
    phone(world, "microsoft")
    again = phone(world, "compras")
    assert again["asked"] and "What is the file name?" in again["reply"]
    gave_up = phone(world, "notas")
    assert not gave_up["asked"] and gave_up["reply"] == phrases.text("NW_GIVE_UP", None) and spy == []
    nothing = phone(world, "compras.txt")
    assert nothing["reply"] is None, "the draft is gone: a name alone is no longer an answer"


def test_a_question_or_a_request_offered_as_a_name_is_a_new_line_never_the_name(world, clock, spy):
    policy(world)
    phone(world, "cria uma nota chamada compras com o texto: pão e leite")
    phone(world, "microsoft")
    for line in ("que horas são?", "qual o status?", "cria um documento sobre o lançamento", "faça um resumo da reunião de ontem", "pesquisa preços de passagens para Lisboa"):
        phone(world, "cria uma nota chamada compras com o texto: pão e leite")
        phone(world, "microsoft")
        other = phone(world, line)
        assert other["reply"] is None and other["asked"] is False and spy == [], line


def test_a_question_with_options_is_asked_once_more_for_a_short_non_answer_and_then_given_up_in_a_sentence(world, clock, spy):
    policy(world)
    first = phone(world, "cria uma nota chamada compras com o texto: pão e leite")
    assert first["reply"].startswith("Which account?")
    again = phone(world, "talvez")
    assert again["asked"] and again["reply"] == first["reply"], "the same question once more"
    gave_up = phone(world, "hmm")
    assert gave_up["reply"] == phrases.text("NW_GIVE_UP", None) and not gave_up["asked"] and spy == [] and drafts.count() == 0
    long_line = phone(world, "cria uma nota chamada compras com o texto: pão e leite")
    assert phone(world, "preciso pensar melhor sobre isso amanhã de manhã")["reply"] is None and long_line["asked"], "a long line is a new line, never a retry"
