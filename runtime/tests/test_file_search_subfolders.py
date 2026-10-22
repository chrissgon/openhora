"""Find a file by a part of its name anywhere under the folders the person granted, subfolders included (slice S17, runtime/ops_file_read.py), through `ops.say`.

The stand-ins of test_file_read.py (a model that answers each line with a text the test wrote, and two fictional drives in memory behind the providers' seam) hold here a TREE:
the granted Google folder "default" holds a folder "openhora" that holds the file the maintainer asked for and a folder "2026"; the OneDrive folder "default" holds a folder "Igreja"
with a second file that carries the same words; a folder and a file outside the granted folders carry the asked name too. Every expectation is a literal of this file: the line, the
model's text, the reply, the calls the providers saw. No network, no model, no secret store; every name, folder and text is invented.

  the live line ("...do google drive"): found in the subfolder without naming it, the account words narrow and do not ask again (the cause of the ask-again is the check of the slot)
  a part of the name finds it; two matches: a numbered list with folder path and account, and "o 2" right after picks one; the list lasts one line
  a folder named in the line narrows the search; a folder that is not under a granted folder is refused in one sentence
  a same-named file outside the granted folders is never returned (the planted fault is seen); the search cut (depth, items, time) says so
  what is kept: no text, name or folder in the conversation or the project's files; a sender without `read-files` gets the refusal and no provider call

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_search_subfolders.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL_PT  # noqa: E402

import json
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import accept
from test_file_read import (ACCOUNTS, FILE_PROFILES, FILE_SENDERS, PLAIN_KEY, READER_KEY, SECRET_MARK, WANTED, drives, item, op, phone, stored)  # noqa: F401  (the fixture and its helpers)
from test_ops_natural import world  # noqa: F401

interpreter_route = st.load("interpreter_route")
natural = st.load("natural")
ops_core = st.load("ops_core")
ops_file_read = st.load("ops_file_read")
ops_interpret = st.load("ops_interpret")
interpreter = st.load("interpreter")

AGAIN = "Não tive certeza do que você quis dizer, então não fiz nada. Pode dizer de outro jeito?"  # validate: allow english-only -- the Portuguese sentence or name under test
DOC = f"# Atividades da semana\n\nSegunda: ensaio do coral.\nQuarta: visita as familias. {SECRET_MARK}\n"
GOOGLE_HEAD = f"{WANTED} (Google Drive, pasta default › openhora):\n\n"
GOOGLE_TEXT = GOOGLE_HEAD + DOC.strip()
ONEDRIVE_TEXT = "First sin activities list.txt (OneDrive, pasta default › Igreja):\n\nAna\nBeto"
NONE_SUB = ("Não encontrei um arquivo com esse nome. Procurei só nas pastas configuradas para as suas contas e nas pastas dentro delas: "  # validate: allow english-only -- the Portuguese sentence or name under test
            "default (Google Drive), contratos (Google Drive), default (OneDrive).")
CUT = " Parei de procurar antes do fim (as pastas são mais fundas ou maiores do que procuro de uma vez), então o arquivo pode estar mais adiante."  # validate: allow english-only -- the Portuguese sentence or name under test
NO_FOLDER = ("Não encontrei essa pasta dentro das pastas configuradas para as suas contas, e não procuro fora delas: "  # validate: allow english-only -- the Portuguese sentence or name under test
             "default (Google Drive), contratos (Google Drive), default (OneDrive).")
LIST_HEAD = 'Encontrei 2 arquivos que combinam. Qual deles? Diga o número, por exemplo "o 2".'  # validate: allow english-only -- the Portuguese sentence or name under test
LIST_TWO = (LIST_HEAD + "\n1. First sin activities list.txt - pasta default › Igreja, OneDrive"
            f"\n2. {WANTED} - pasta default › openhora, Google Drive")


@pytest.fixture
def tree(drives):
    """The drives of this file: the granted folders hold subfolders, and two folders outside them hold the asked name."""
    made = drives["drives"]
    made.folders = {
        ("google", "GDRIVEFOLDER0001"): [item("gfile0000000001", "Planilha de custos.xlsx"), item("gdir_openhora", "openhora", kind="folder")],
        ("google", "gdir_openhora"): [item("gdoc0000000001", WANTED), item("gdir_2026", "2026", kind="folder")],
        ("google", "gdir_2026"): [item("gfile0000000003", "Relatorio anual.txt")],
        ("google", "GDRIVEFOLDER0002"): [item("gfile0000000002", "Contrato de locacao.docx")],
        ("google", "OUTSIDEFOLDER0001"): [item("gout000000000001", WANTED)],
        ("microsoft", "/Documentos"): [item("drv1/it!2", "Lista de presenca.txt"), item("drv1/it!d1", "Igreja", kind="folder")],
        ("microsoft", "drv1/it!d1"): [item("drv1/it!3", "First sin activities list.txt")],
        ("microsoft", "/Particular"): [item("drv1/it!9", WANTED)]}
    made.files = {("google", "gdoc0000000001"): DOC.encode("utf-8"), ("google", "gfile0000000003"): b"anual", ("google", "gout000000000001"): b"outside the folders",
                  ("microsoft", "drv1/it!2"): b"Ana\nBeto\n", ("microsoft", "drv1/it!3"): b"Ana\nBeto\n", ("microsoft", "drv1/it!9"): b"the private folder"}
    made.markdown.add(("google", "gdoc0000000001"))
    ops_file_read.forget_lists()
    return drives


def says(world, span, service=None):
    world["answer"]["text"] = op("file-read", {"file": span, **({"service": service} if service else {})})


def services_called(world) -> set:
    return {s for s, v, a in world["drives"].calls}


# --- the live line ------------------------------------------------------------------------------------------------------------------------------


def test_the_live_line_finds_the_file_in_a_subfolder_without_the_folder_and_google_drive_does_not_ask_again(tree):
    says(tree, WANTED, "google drive")
    assert phone(tree, f"Me traga o conteudo do arquivo {WANTED} do google drive") == GOOGLE_TEXT
    assert tree["drives"].listed() == [("google", "GDRIVEFOLDER0001"), ("google", "GDRIVEFOLDER0002"), ("google", "gdir_2026"), ("google", "gdir_openhora")]
    assert tree["drives"].reads() == [("google", "gdoc0000000001")]
    assert services_called(tree) == {"google"}, "the account words narrow the search to that account"


def test_without_an_account_both_are_searched_and_the_exact_name_is_found_in_the_subfolder(tree):
    says(tree, WANTED)
    assert phone(tree, f"Me traga o conteudo do arquivo {WANTED}") == GOOGLE_TEXT
    assert services_called(tree) == {"google", "microsoft"}


@pytest.mark.parametrize("tail, slot, text, called", [
    ("do google drive", "google drive", GOOGLE_TEXT, {"google"}),
    ("do drive", "drive", GOOGLE_TEXT, {"google"}),
    ("do onedrive", "onedrive", ONEDRIVE_TEXT, {"microsoft"}),
    ("no onedrive", None, ONEDRIVE_TEXT, {"microsoft"}),            # the model gave no service word: the line names the account
    ("do google drive", None, GOOGLE_TEXT, {"google"})])
def test_the_account_words_narrow_the_account_whether_the_model_wrote_them_or_not(tree, tail, slot, text, called):
    says(tree, "first sin activities", slot)
    assert phone(tree, f"Me traga o arquivo first sin activities {tail}") == text
    assert services_called(tree) == called


def test_a_model_word_that_contradicts_the_account_the_line_names_asks_again_and_calls_no_provider(tree):
    says(tree, "first sin activities", "onedrive")
    assert phone(tree, "Me traga o arquivo first sin activities do google drive") == AGAIN
    assert tree["drives"].calls == []


def test_vacuity_a_reading_of_the_line_that_names_no_account_would_search_both_and_be_seen(tree, monkeypatch):
    """The planted fault: the line's account words are not read. The oracle of the first test (only Google is called) then fails, so it can fail."""
    monkeypatch.setattr(ops_file_read, "_account_of_line", lambda said, wanted: None)
    says(tree, WANTED)
    phone(tree, f"Me traga o conteudo do arquivo {WANTED} do google drive")
    assert services_called(tree) == {"google", "microsoft"}


def test_the_cause_of_the_ask_again_was_the_check_of_the_slot_that_took_two_words_for_a_piece_of_the_line():
    """`natural.check_operation` (unchanged, pinned) reads the `service` slot as ONE word of the line: "google drive" was refused, `interpreter._check_slots` said E_SPAN, the decision was
    `invalid` and the reply was the ask-again sentence. `_check_slots` now checks an account of two or three words in a row by the same rule for each word."""
    line = f"Me traga o conteudo do arquivo {WANTED} do google drive"
    assert natural.check_operation("file-read", {"file": WANTED, "service": "google drive"}, None, line)["ok"] is False      # the cause: unchanged on purpose
    assert interpreter._check_slots("file-read", {"file": WANTED, "service": "google drive"}, line) == ({"file": WANTED, "account": "google drive"}, None)
    assert interpreter._check_slots("file-read", {"file": WANTED, "service": "drive"}, line) == ({"file": WANTED, "account": "drive"}, None)
    assert interpreter._check_slots("file-read", {"file": WANTED, "service": "google calendar"}, line) == (None, "E_SPAN")      # not a run of the line
    assert interpreter._check_slots("file-read", {"file": WANTED, "service": "o conteudo do arquivo"}, line) == (None, "E_SPAN")      # four words
    assert interpreter._check_slots("file-read", {"file": WANTED, "service": "google  drive"}, line) == (None, "E_SPAN")      # one space between the words, as typed
    assert interpreter._check_slots("mail-send", {"to": "ana beto"}, "send to ana beto") == (None, "E_SPAN")      # only an account may be several words
    assert interpreter._check_slots("event-create", {"title": "Dentist", "service": "google calendar"}, "Dentist on my google calendar") == ({"title": "Dentist", "account": "google calendar"}, None)


# --- the match -------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("wanted, found, fits", [
    ("first sin activities", "Copy of the-first-sin-activities", True), ("FIRST SIN", "Copy of the-first-sin-activities", True), ("sin first", "Copy of the-first-sin-activities", True),
    ("first sin activities", "First sin.txt", False), ("lista de presença", "Lista de presenca.txt", True),  # validate: allow english-only -- the Portuguese sentence or name under test
    ("lista.docx", "Lista de presenca.txt", False), ("lista.txt", "Lista de presenca", True), ("contrat", "Contrato de locacao.docx", True), ("", "x", False), ("zebra", "Lista", False)])
def test_every_word_of_the_span_must_occur_in_the_name_with_the_extension_optional(wanted, found, fits):
    assert ops_file_read._fits(wanted, found) is fits


def test_a_part_of_the_name_finds_the_file(tree):
    says(tree, "first sin activities", "google drive")
    assert phone(tree, "Me traga o arquivo first sin activities do google drive") == GOOGLE_TEXT


def test_a_file_whose_whole_name_is_the_span_wins_over_files_that_only_hold_its_words(tree):
    tree["drives"].folders[("google", "gdir_openhora")].append(item("gdoc0000000002", f"{WANTED} (old).txt"))
    tree["drives"].files[("google", "gdoc0000000002")] = b"the old one"
    says(tree, WANTED, "google drive")
    assert phone(tree, f"Me traga o arquivo {WANTED} do google drive") == GOOGLE_TEXT
    says(tree, "first sin activities", "google drive")
    assert phone(tree, "Me traga o arquivo first sin activities do google drive").startswith("Encontrei 2 arquivos que combinam.")


def test_vacuity_a_match_that_ignored_the_words_would_find_a_file_for_any_name(tree, monkeypatch):
    """The planted fault: every name fits. The sentence for a name that is nowhere then no longer comes, so the oracle can fail."""
    says(tree, "relatorio inexistente")
    assert phone(tree, "Mostre o arquivo relatorio inexistente") == NONE_SUB
    monkeypatch.setattr(ops_file_read, "_fits", lambda wanted, found: True)
    assert phone(tree, "Mostre o arquivo relatorio inexistente") != NONE_SUB


def test_no_match_names_the_configured_folders_and_says_the_subfolders_were_included(tree):
    says(tree, "relatorio inexistente")
    reply = phone(tree, "Mostre o arquivo relatorio inexistente")
    assert reply == NONE_SUB
    for piece in ("OUTSIDE", "Particular", "GDRIVEFOLDER", "/Documentos", "openhora", "Igreja"):
        assert piece not in reply, "the folders are named as the configuration names them; a subfolder's name is never in a sentence that found nothing"


# --- several matches and the pick -------------------------------------------------------------------------------------------------------------


def test_two_matches_are_a_numbered_list_with_folder_path_and_account_and_o_2_picks_one_without_the_model(tree, monkeypatch):
    says(tree, "first sin activities")
    assert phone(tree, "Me traga o arquivo first sin activities") == LIST_TWO
    assert tree["drives"].reads() == []
    asked = []
    monkeypatch.setattr(interpreter_route, "complete", lambda *a, **kw: asked.append(1) or {"ok": False})
    assert phone(tree, "o 2") == GOOGLE_TEXT
    assert tree["drives"].reads() == [("google", "gdoc0000000001")]
    assert asked == [], "a pick is read by code: the model is never asked"
    assert ops_file_read._LISTS == {}, "a pick is used once"


def test_o_1_picks_the_first_of_the_list(tree):
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    assert phone(tree, "o 1") == ONEDRIVE_TEXT
    assert tree["drives"].reads() == [("microsoft", "drv1/it!3")]


def test_a_number_the_list_did_not_show_is_no_pick_and_the_line_goes_on(tree):
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    assert phone(tree, "o 9") == AGAIN
    assert tree["drives"].reads() == []


@pytest.mark.parametrize("other", ["e agora uma outra coisa", "/status"])
def test_the_list_lasts_one_line(tree, other):
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    phone(tree, other)
    assert phone(tree, "o 2") == AGAIN
    assert tree["drives"].reads() == []


def test_vacuity_a_list_that_did_not_end_with_the_next_line_would_pick_a_file_later(tree, monkeypatch):
    """The planted fault: `begin_turn` counts no line. The oracle of the test above (nothing is read) then fails, so it can fail."""
    monkeypatch.setattr(ops_file_read, "begin_turn", lambda ctx, channel, sender: None)
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    phone(tree, "/status")          # a command never reaches the reading of plain lines, so only `begin_turn` can end the list
    assert phone(tree, "o 2") == GOOGLE_TEXT


def test_a_sender_who_lost_the_group_since_the_list_gets_the_refusal_and_nothing_is_read(tree):
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    accept(tree["path"], policies=dict(FILE_PROFILES, reader=["read", "talk", "interpret"]), messaging={"senders": FILE_SENDERS}, accounts=ACCOUNTS, language="pt-BR")
    assert phone(tree, "o 2") == PLAIN_REFUSAL_PT
    assert tree["drives"].reads() == []


def test_a_sender_without_read_files_gets_the_refusal_and_no_provider_is_called(tree):
    says(tree, WANTED)
    assert phone(tree, f"Me traga o conteudo do arquivo {WANTED}", PLAIN_KEY) == PLAIN_REFUSAL_PT
    assert tree["drives"].calls == []


# --- the folder named in the line ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tail, text", [
    ("da pasta /openhora", GOOGLE_TEXT), ("na pasta Igreja", ONEDRIVE_TEXT), ("da pasta openhora do google drive", GOOGLE_TEXT), ("in the folder openhora", GOOGLE_TEXT),
    ("da pasta default › Igreja", ONEDRIVE_TEXT)])
def test_a_folder_named_in_the_line_narrows_the_search_to_it_and_what_is_under_it(tree, tail, text):
    says(tree, "first sin activities")
    assert phone(tree, f"Me traga o arquivo first sin activities {tail}") == text


def test_a_folder_name_that_two_folders_share_lists_the_files_of_both(tree):
    says(tree, "first sin activities")
    assert phone(tree, "Me traga o arquivo first sin activities na pasta default") == LIST_TWO


@pytest.mark.parametrize("line", ["Me traga o arquivo first sin activities da pasta Particular", f"Me traga o arquivo {WANTED} da pasta Particular",
                                  "Me traga o arquivo first sin activities da pasta /openhora/inexistente"])
def test_a_folder_that_is_not_under_a_granted_folder_is_refused_in_one_sentence_and_nothing_is_read(tree, line):
    says(tree, line.split("arquivo ", 1)[1].split(" da pasta")[0])
    reply = phone(tree, line)
    assert reply == NO_FOLDER
    assert tree["drives"].reads() == []
    assert ("google", "OUTSIDEFOLDER0001") not in tree["drives"].listed() and ("microsoft", "/Particular") not in tree["drives"].listed()
    assert "Particular" not in reply and "inexistente" not in reply


def test_a_span_that_ends_with_the_folder_phrase_is_read_as_a_name_and_a_folder(tree):
    says(tree, "first sin activities da pasta openhora")
    assert phone(tree, "Me traga o arquivo first sin activities da pasta openhora") == GOOGLE_TEXT


# --- a file outside the granted folders --------------------------------------------------------------------------------------------------------


def test_a_same_named_file_outside_the_granted_folders_is_never_listed_named_or_returned(tree):
    tree["drives"].folders[("google", "gdir_openhora")] = [item("gdir_2026", "2026", kind="folder")]
    says(tree, WANTED)
    reply = phone(tree, f"Me traga o conteudo do arquivo {WANTED}")
    assert reply == NONE_SUB
    assert tree["drives"].reads() == []
    assert ("google", "OUTSIDEFOLDER0001") not in tree["drives"].listed() and ("microsoft", "/Particular") not in tree["drives"].listed()
    for piece in ("OUTSIDE", "Particular", "outside the folders", "the private folder"):
        assert piece not in reply


def test_vacuity_a_walk_that_also_started_from_an_unconfigured_folder_would_return_the_outside_file(tree, monkeypatch):
    """The planted fault: the walk starts from a folder the configuration does not list (the ancestry check removed). The oracle above then fails, so it can fail."""
    tree["drives"].folders[("google", "gdir_openhora")] = [item("gdir_2026", "2026", kind="folder")]
    real = ops_file_read._walk

    def wrong(cfg, account=None):
        cfg = dict(cfg, accounts={**cfg["accounts"], "google": {**cfg["accounts"]["google"], "folders": {"default": "OUTSIDEFOLDER0001"}}})
        return real(cfg, account)
    monkeypatch.setattr(ops_file_read, "_walk", wrong)
    says(tree, WANTED)
    assert phone(tree, f"Me traga o conteudo do arquivo {WANTED}") != NONE_SUB
    assert ("google", "gout000000000001") in tree["drives"].reads()


# --- the bounds ----------------------------------------------------------------------------------------------------------------------------------


def chain(world, depth, file_at):
    """A chain n1 > n2 > ... under the Google folder "default": the file TARGET sits in the folder n<file_at>. n1 is level 1 below the configured folder."""
    folders = {("google", "GDRIVEFOLDER0001"): [item("gn1", "n1", kind="folder")], ("google", "GDRIVEFOLDER0002"): [], ("microsoft", "/Documentos"): []}
    for level in range(1, depth + 1):
        content = [item(f"gn{level + 1}", f"n{level + 1}", kind="folder")] if level < depth else []
        folders[("google", f"gn{level}")] = content + ([item("gtarget", "TARGET.txt")] if level == file_at else [])
    world["drives"].folders, world["drives"].files = folders, {("google", "gtarget"): b"found at the bottom"}


def test_a_file_five_levels_below_a_granted_folder_is_found_and_one_six_levels_below_is_not_and_the_reply_says_it_was_cut(tree):
    says(tree, "TARGET")
    chain(tree, 7, 5)
    assert phone(tree, "Me traga o arquivo TARGET") == "TARGET.txt (Google Drive, pasta default › n1 › n2 › n3 › n4 › n5):\n\nfound at the bottom"
    chain(tree, 7, 6)
    assert phone(tree, "Me traga o arquivo TARGET") == NONE_SUB + CUT
    assert ("google", "gn7") not in tree["drives"].listed() and ("google", "gn6") not in tree["drives"].listed()


def test_a_walk_that_listed_more_items_than_the_cap_stops_and_says_so(tree, monkeypatch):
    monkeypatch.setattr(ops_file_read, "MAX_ITEMS", 1)
    says(tree, "relatorio anual")
    assert phone(tree, "Mostre o arquivo relatorio anual") == NONE_SUB + CUT
    assert ("google", "gdir_openhora") not in tree["drives"].listed(), "the roots were listed (the cap is checked between listings), the subfolders were not"
    monkeypatch.setattr(ops_file_read, "MAX_ITEMS", 2000)
    assert phone(tree, "Mostre o arquivo relatorio anual").startswith("Relatorio anual.txt (Google Drive, pasta default › openhora › 2026):")


def test_a_walk_that_took_more_than_ten_seconds_stops_and_says_so(tree, monkeypatch):
    seconds = iter(range(0, 1000, 6))      # the clock moves 6 seconds at each reading
    monkeypatch.setattr(ops_file_read, "clock", lambda: next(seconds))
    says(tree, "relatorio anual")
    assert phone(tree, "Mostre o arquivo relatorio anual") == NONE_SUB + CUT
    assert ("google", "gdir_openhora") not in tree["drives"].listed()
    assert ops_file_read.MAX_SECONDS == 10.0 and ops_file_read.MAX_DEPTH == 5 and ops_file_read.MAX_ITEMS == 2000


def test_a_folder_that_lists_in_part_or_fails_makes_the_none_sentence_say_so(tree, monkeypatch):
    real = tree["drives"].__call__

    def failing(cls, verb, args, **kw):
        if "gdir_openhora" in args:
            raise RuntimeError("Drive said: token abc-SECRET-123 refused")
        return real(cls, verb, args, **kw)
    monkeypatch.setattr(ops_file_read, "provider_call", failing)
    says(tree, "relatorio anual")
    reply = phone(tree, "Mostre o arquivo relatorio anual")
    assert reply == NONE_SUB + " Não consegui olhar todos os arquivos dessas pastas (algumas têm mais arquivos do que consigo listar, ou não responderam), então o arquivo pode estar lá."  # validate: allow english-only -- the Portuguese sentence or name under test
    assert "SECRET" not in reply


# --- what is kept ----------------------------------------------------------------------------------------------------------------------------------


def test_nothing_of_the_file_the_subfolder_or_the_list_is_kept_beyond_the_reply(tree, caplog, capsys):
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    assert phone(tree, "o 2") == GOOGLE_TEXT
    rows = stored(tree)
    everything = json.dumps(rows, ensure_ascii=False)
    for piece in (SECRET_MARK, WANTED, "Igreja", "openhora", "Atividades", "first sin activities"):
        assert piece not in everything, piece
    assert [r["text"] for r in rows if r["role"] == "assistant"][-2:] == ["(mostrado onde foi pedido)"] * 2
    seen = capsys.readouterr()
    assert SECRET_MARK not in seen.out + seen.err + caplog.text and "openhora" not in seen.out + seen.err + caplog.text
    for root in (Path(tree["path"]), Path(ops_core.context(tree["path"])["cfg"]["data_dir"])):
        for found in root.rglob("*"):
            if found.is_file() and ".git" not in found.parts:
                data = found.read_bytes()
                assert SECRET_MARK.encode() not in data and b"Igreja" not in data and b"gdir_openhora" not in data, str(found.relative_to(root))
    assert ops_file_read._LISTS == {}
    staging = Path(ops_core.context(tree["path"])["cfg"]["data_dir"]) / "sources-staging"
    assert not staging.exists() or list(staging.iterdir()) == []
