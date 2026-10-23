"""Find a file by a part of its name anywhere under the folders the person granted, subfolders included (slice S17, runtime/ops_file_read.py), through `ops.say`.

The stand-ins of test_file_read.py (a model that answers each line with a text the test wrote, and two fictional drives in memory behind the providers' seam) hold here a TREE:
the granted Google folder "default" holds a folder "openhora" that holds the file the maintainer asked for and a folder "2026"; the OneDrive folder "default" holds a folder "Igreja"
with a second file that carries the same words; a folder and a file outside the granted folders carry the asked name too. Every expectation is a literal of this file: the line, the
model's text, the reply, the calls the providers saw. No network, no model, no secret store; every name, folder and text is invented.

  the live line ("...do google drive"): found in the subfolder without naming it, the account words narrow and do not ask again (the cause of the ask-again is the check of the slot)
  a part of the name finds it; two matches: a numbered list with folder path and account, and "o 1" right after picks one; the list lasts one line
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
GOOGLE_HEAD = f"{WANTED} (Google Drive, pasta Arquivos › openhora):\n\n"
GOOGLE_TEXT = GOOGLE_HEAD + DOC.strip()
ONEDRIVE_TEXT = "First sin activities list.txt (OneDrive, pasta Documentos › Igreja):\n\nAna\nBeto"
NONE_SUB = ("Não encontrei um arquivo com esse nome. Procurei só nas pastas configuradas para as suas contas e nas pastas dentro delas: "  # validate: allow english-only -- the Portuguese sentence or name under test
            "Arquivos (Google Drive), Contratos 2026 (Google Drive), Documentos (OneDrive).")
CUT = " Parei de procurar antes do fim (as pastas são mais fundas ou maiores do que procuro de uma vez), então o arquivo pode estar mais adiante."  # validate: allow english-only -- the Portuguese sentence or name under test
NO_FOLDER = ("Não encontrei essa pasta dentro das pastas configuradas para as suas contas, e não procuro fora delas: "  # validate: allow english-only -- the Portuguese sentence or name under test
             "Arquivos (Google Drive), Contratos 2026 (Google Drive), Documentos (OneDrive).")
INCOMPLETE = "Não olhei tudo (as pastas são mais fundas ou maiores do que procuro de uma vez, ou alguma não respondeu), então outro arquivo pode combinar também."  # validate: allow english-only -- the Portuguese sentence or name under test
LIST_HEAD = 'Encontrei 2 arquivos que combinam. Qual deles? Diga o número, por exemplo "o 2".'  # validate: allow english-only -- the Portuguese sentence or name under test
LIST_TWO = (LIST_HEAD + f"\n1. {WANTED} - pasta Arquivos › openhora, Google Drive"
            "\n2. First sin activities list.txt - pasta Documentos › Igreja, OneDrive")


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
    ("do onedrive", "onedrive", ONEDRIVE_TEXT, {"microsoft"}),
    ("no onedrive", None, ONEDRIVE_TEXT, {"microsoft"}),            # the model gave no service word: the line names the account
    ("do google drive", None, GOOGLE_TEXT, {"google"})])
def test_the_account_words_narrow_the_account_whether_the_model_wrote_them_or_not(tree, tail, slot, text, called):
    says(tree, "first sin activities", slot)
    assert phone(tree, f"Me traga o arquivo first sin activities {tail}") == text
    assert services_called(tree) == called


@pytest.mark.parametrize("slot", ["drive", None])
def test_the_bare_word_drive_names_no_account_and_both_accounts_are_searched(tree, slot):
    says(tree, "first sin activities", slot)
    assert phone(tree, "Me traga o arquivo first sin activities do meu drive") == LIST_TWO
    assert services_called(tree) == {"google", "microsoft"}


def test_vacuity_a_drive_that_named_google_would_search_one_account_and_be_seen(tree, monkeypatch):
    """The planted fault: "drive" is read as Google's. The oracle above (both accounts are called) then fails, so it can fail."""
    monkeypatch.setattr(ops_file_read, "GENERIC", set())
    says(tree, "first sin activities", "drive")
    phone(tree, "Me traga o arquivo first sin activities do meu drive")
    assert services_called(tree) == {"google"}


def test_a_line_that_names_both_accounts_searches_both_or_asks_again_and_the_model_never_picks_one(tree):
    line = "Me traga o arquivo first sin activities do google drive ou do onedrive"
    says(tree, "first sin activities")
    assert phone(tree, line) == LIST_TWO
    assert services_called(tree) == {"google", "microsoft"}
    tree["drives"].calls.clear()
    says(tree, "first sin activities", "google drive")
    assert phone(tree, line) == AGAIN
    assert tree["drives"].calls == []


def test_vacuity_a_reading_that_kept_one_of_two_named_accounts_would_let_the_model_pick_and_be_seen(tree, monkeypatch):
    """The planted fault: only Google is read out of a line that names both. The oracle above then fails (the model's word is believed)."""
    monkeypatch.setattr(ops_file_read, "_accounts_of_line", lambda said, wanted: {"google"})
    says(tree, "first sin activities", "google drive")
    assert phone(tree, "Me traga o arquivo first sin activities do google drive ou do onedrive") == GOOGLE_TEXT


def test_a_model_word_that_contradicts_the_account_the_line_names_asks_again_and_calls_no_provider(tree):
    says(tree, "first sin activities", "onedrive")
    assert phone(tree, "Me traga o arquivo first sin activities do google drive") == AGAIN
    assert tree["drives"].calls == []


def test_vacuity_a_reading_of_the_line_that_names_no_account_would_search_both_and_be_seen(tree, monkeypatch):
    """The planted fault: the line's account words are not read. The oracle of the first test (only Google is called) then fails, so it can fail."""
    monkeypatch.setattr(ops_file_read, "_accounts_of_line", lambda said, wanted: set())
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
    assert phone(tree, "o 1") == GOOGLE_TEXT
    assert tree["drives"].reads() == [("google", "gdoc0000000001")]
    assert asked == [], "a pick is read by code: the model is never asked"
    assert ops_file_read._LISTS == {}, "a pick is used once"


def test_a_second_number_picks_the_second_entry(tree):
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    assert phone(tree, "o 2") == ONEDRIVE_TEXT
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
    assert phone(tree, "o 1") == AGAIN
    assert tree["drives"].reads() == []


def test_vacuity_a_list_that_did_not_end_with_the_next_line_would_pick_a_file_later(tree, monkeypatch):
    """The planted fault: `begin_turn` counts no line. The oracle of the test above (nothing is read) then fails, so it can fail."""
    monkeypatch.setattr(ops_file_read, "begin_turn", lambda ctx, channel, sender: None)
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    phone(tree, "/status")          # a command never reaches the reading of plain lines, so only `begin_turn` can end the list
    assert phone(tree, "o 1") == GOOGLE_TEXT


def test_a_sender_who_lost_the_group_since_the_list_gets_the_refusal_and_nothing_is_read(tree):
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    accept(tree["path"], policies=dict(FILE_PROFILES, reader=["read", "talk", "interpret"]), messaging={"senders": FILE_SENDERS}, accounts=ACCOUNTS, language="pt-BR")
    assert phone(tree, "o 1") == PLAIN_REFUSAL_PT
    assert tree["drives"].reads() == []


def test_a_sender_without_read_files_gets_the_refusal_and_no_provider_is_called(tree):
    says(tree, WANTED)
    assert phone(tree, f"Me traga o conteudo do arquivo {WANTED}", PLAIN_KEY) == PLAIN_REFUSAL_PT
    assert tree["drives"].calls == []


# --- the folder named in the line ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("tail, text", [
    ("da pasta /openhora", GOOGLE_TEXT), ("na pasta Igreja", ONEDRIVE_TEXT), ("da pasta openhora do google drive", GOOGLE_TEXT), ("in the folder openhora", GOOGLE_TEXT),
    ("da pasta Documentos › Igreja", ONEDRIVE_TEXT)])
def test_a_folder_named_in_the_line_narrows_the_search_to_it_and_what_is_under_it(tree, tail, text):
    says(tree, "first sin activities")
    assert phone(tree, f"Me traga o arquivo first sin activities {tail}") == text


def test_a_folder_name_that_two_folders_share_lists_the_files_of_both(tree):
    says(tree, "first sin activities")
    assert phone(tree, "Me traga o arquivo first sin activities na pasta default") == LIST_TWO


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

    def wrong(cfg, account=None, names_only=False):
        cfg = dict(cfg, accounts={**cfg["accounts"], "google": {**cfg["accounts"]["google"], "folders": {"default": "OUTSIDEFOLDER0001"}}})
        return real(cfg, account, names_only)
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
    assert phone(tree, "Me traga o arquivo TARGET") == "TARGET.txt (Google Drive, pasta Arquivos › n1 › n2 › n3 › n4 › n5):\n\nfound at the bottom\n\n" + INCOMPLETE      # n6 was found and not listed: a second file may be there
    chain(tree, 7, 6)
    assert phone(tree, "Me traga o arquivo TARGET") == NONE_SUB + CUT
    assert ("google", "gn7") not in tree["drives"].listed() and ("google", "gn6") not in tree["drives"].listed()


def test_a_walk_that_listed_more_items_than_the_cap_stops_and_says_so(tree, monkeypatch):
    monkeypatch.setattr(ops_file_read, "MAX_ITEMS", 1)
    says(tree, "relatorio anual")
    assert phone(tree, "Mostre o arquivo relatorio anual") == NONE_SUB + CUT
    assert ("google", "gdir_openhora") not in tree["drives"].listed(), "the roots were listed (the cap is checked between listings), the subfolders were not"
    monkeypatch.setattr(ops_file_read, "MAX_ITEMS", 2000)
    assert phone(tree, "Mostre o arquivo relatorio anual").startswith("Relatorio anual.txt (Google Drive, pasta Arquivos › openhora › 2026):")


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
    assert phone(tree, "o 1") == GOOGLE_TEXT
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


# --- review round: the grant at the pick, the cut said on a found file, the bounds ---------------------------------------------------------------


REVOKED = {"google": {"address": "ana@mail.example", "folders": {"contratos": "GDRIVEFOLDER0002"}}, "microsoft": ACCOUNTS["microsoft"]}
NO_FOLDER_NOW = ("Não encontrei essa pasta dentro das pastas configuradas para as suas contas, e não procuro fora delas: "  # validate: allow english-only -- the Portuguese sentence or name under test
                 "Google Drive, OneDrive.")


def revoke(world):
    accept(world["path"], policies=FILE_PROFILES, messaging={"senders": FILE_SENDERS}, accounts=REVOKED, language="pt-BR")


def test_the_pick_after_the_configured_folder_was_removed_reads_nothing_and_says_the_folder_is_not_one_of_yours(tree):
    says(tree, "first sin activities")
    assert phone(tree, "Me traga o arquivo first sin activities") == LIST_TWO
    revoke(tree)          # Google's folder "default" is no longer configured: the file #2 was found under it
    assert phone(tree, "o 1") == NO_FOLDER_NOW
    assert tree["drives"].reads() == []
    assert ops_file_read._LISTS == {}


def test_the_other_entry_still_reads_when_the_folder_of_that_file_is_still_configured(tree):
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    revoke(tree)
    assert phone(tree, "o 2") == ONEDRIVE_TEXT
    assert tree["drives"].reads() == [("microsoft", "drv1/it!3")]


def test_vacuity_a_pick_that_trusted_the_held_list_would_read_the_removed_folders_file(tree, monkeypatch):
    """The planted fault: the grant is read from the configuration as it was when the list was made. The oracle above (nothing is read) then fails, so it can fail."""
    stale = ops_core.context(tree["path"])["cfg"]
    says(tree, "first sin activities")
    phone(tree, "Me traga o arquivo first sin activities")
    revoke(tree)
    monkeypatch.setattr(ops_file_read.project_config, "account_entry", lambda cfg, service: stale["accounts"].get(service))
    assert phone(tree, "o 1") == GOOGLE_TEXT
    assert tree["drives"].reads() == [("google", "gdoc0000000001")]


def test_a_list_made_while_a_folder_failed_says_so_and_the_pick_carries_the_same_note(tree, monkeypatch):
    real = tree["drives"].__call__

    def failing(cls, verb, args, **kw):
        if "gdir_2026" in args:
            raise RuntimeError("Drive said: token abc-SECRET-123 refused")
        return real(cls, verb, args, **kw)
    monkeypatch.setattr(ops_file_read, "provider_call", failing)
    says(tree, "first sin activities")
    assert phone(tree, "Me traga o arquivo first sin activities") == LIST_TWO + "\n" + INCOMPLETE
    assert phone(tree, "o 1") == GOOGLE_TEXT + "\n\n" + INCOMPLETE


def test_a_single_match_found_while_a_listing_was_in_part_says_another_file_may_fit(tree):
    tree["drives"].folders[("google", "gdir_openhora")] = [item("gdoc0000000001", WANTED), item("gdir_2026", "2026", kind="folder")]
    real = tree["drives"].__call__

    def partial(cls, verb, args, **kw):
        out = real(cls, verb, args, **kw)
        return dict(out, truncated=True) if verb == "children" and "GDRIVEFOLDER0002" in args else out
    ops_file_read.provider_call = partial
    says(tree, WANTED, "google drive")
    assert phone(tree, f"Me traga o arquivo {WANTED} do google drive") == GOOGLE_TEXT + "\n\n" + INCOMPLETE


def test_a_search_that_listed_every_folder_whole_adds_no_note(tree):
    says(tree, WANTED, "google drive")
    assert INCOMPLETE not in phone(tree, f"Me traga o arquivo {WANTED} do google drive")


def test_the_items_cap_is_counted_item_by_item_inside_a_listing(tree, monkeypatch):
    tree["drives"].folders[("google", "GDRIVEFOLDER0001")] = [item(f"g{n:03d}", f"Arquivo {n:03d}.txt") for n in range(200)]
    tree["drives"].folders[("google", "GDRIVEFOLDER0002")] = [item(f"h{n:03d}", f"Outro {n:03d}.txt") for n in range(200)]
    monkeypatch.setattr(ops_file_read, "MAX_ITEMS", 250)
    found = ops_file_read._walk(ops_core.context(tree["path"])["cfg"])
    assert len(found["files"]) == 250 and found["cut"] == "items"
    assert [f["name"] for f in found["files"]][-1] == "Outro 049.txt"


def test_each_listing_is_asked_with_at_most_the_time_left(tree, monkeypatch):
    seconds = iter([0, 6, 12])          # started, the check before the first batch (4 s left), the check before the next (spent)
    monkeypatch.setattr(ops_file_read, "clock", lambda: next(seconds))
    asked = []
    real = tree["drives"].__call__
    monkeypatch.setattr(ops_file_read, "provider_call", lambda cls, verb, args, **kw: (asked.append(kw["timeout"]) if verb == "children" else None) or real(cls, verb, args, **kw))
    says(tree, "relatorio anual")
    assert phone(tree, "Mostre o arquivo relatorio anual") == NONE_SUB + CUT
    assert asked == [4, 4, 4] or asked == [4.0, 4.0, 4.0], asked


def test_a_provider_that_does_not_answer_is_given_up_when_the_ten_seconds_are_spent(tree, monkeypatch):
    import threading
    import time
    release = threading.Event()
    real = tree["drives"].__call__
    silent = {"only": "GDRIVEFOLDER0001"}          # one folder never answers; with None every folder is silent

    def provider(cls, verb, args, **kw):
        if silent["only"] is None or silent["only"] in args:
            release.wait(10)
        return real(cls, verb, args, **kw)
    monkeypatch.setattr(ops_file_read, "provider_call", provider)
    monkeypatch.setattr(ops_file_read, "MAX_SECONDS", 0.3)
    says(tree, "relatorio anual")
    try:
        started = time.monotonic()
        reply = phone(tree, "Mostre o arquivo relatorio anual")
        elapsed = time.monotonic() - started
        silent["only"] = None
        started = time.monotonic()
        nothing = phone(tree, "Mostre o arquivo relatorio anual")
        elapsed_all = time.monotonic() - started
    finally:
        release.set()
    assert reply.startswith(NONE_SUB.replace("Arquivos (Google Drive)", "Google Drive")) and reply.endswith(CUT) and "não responderam" in reply          # the silent folder's name is the service's own  # validate: allow english-only -- the Portuguese sentence or name under test
    assert nothing == "Não consegui olhar as suas pastas agora. Tente de novo em alguns minutos."  # validate: allow english-only -- the Portuguese sentence or name under test
    assert elapsed < 3 and elapsed_all < 3, "the answer does not wait for a provider that is silent"


def test_outside_a_messaging_app_a_list_asks_for_the_full_name_and_keeps_no_list_to_pick_from(tree):
    ctx = ops_core.context(tree["path"])
    extras = {}
    reply = ops_file_read.reply(tree["path"], ctx, {"file": "first sin activities"}, "Me traga o arquivo first sin activities", "page", None, extras)
    assert reply == ("Encontrei 2 arquivos que combinam. Qual deles? Escreva o nome completo, ou diga a pasta ou a conta em que ele está."  # validate: allow english-only -- the Portuguese sentence or name under test
                     f"\n1. {WANTED} - pasta Arquivos › openhora, Google Drive"
                     "\n2. First sin activities list.txt - pasta Documentos › Igreja, OneDrive")
    assert "número" not in reply and "o 1" not in reply and ops_file_read._LISTS == {}  # validate: allow english-only -- the Portuguese sentence or name under test


# --- S17b: the folder as the person sees it ----------------------------------------------------------------------------------------------------


NOTE_OPENHORA = ' Não achei a pasta "{folder}"; procurei em todas as suas pastas.'.strip()  # validate: allow english-only -- the Portuguese sentence or name under test
OPENHORA_TEXT = f"{WANTED} (Google Drive, pasta Arquivos › openhora):\n\n" + DOC.strip()
MARK_TEXT = "openhora-mark.txt (Google Drive, pasta Arquivos › openhora):\n\nmarca do coral"


@pytest.fixture
def real(tree):
    """The tree plus a second file in the subfolder "openhora"; the configured Google folder is called "default" in the configuration and "Arquivos" in the Drive."""
    tree["drives"].folders[("google", "gdir_openhora")] = tree["drives"].folders[("google", "gdir_openhora")] + [item("gmark00000000001", "openhora-mark.txt")]
    tree["drives"].files[("google", "gmark00000000001")] = "marca do coral".encode("utf-8")
    return tree


@pytest.mark.parametrize("span, tail, text", [
    (WANTED, "da pasta /openhora", OPENHORA_TEXT), (WANTED, "da pasta openhora", OPENHORA_TEXT), (WANTED, "da pasta /OPENHORÁ", OPENHORA_TEXT),  # validate: allow english-only -- the Portuguese sentence or name under test
    ("openhora-mark", "da pasta /openhora", MARK_TEXT), ("openhora-mark", "na pasta openhora", MARK_TEXT), (WANTED, "in the folder /openhora", OPENHORA_TEXT),
    ("Relatorio anual", "da pasta /openhora/2026", "Relatorio anual.txt (Google Drive, pasta Arquivos › openhora › 2026):\n\nanual"),
    ("Relatorio anual", "da pasta 2026", "Relatorio anual.txt (Google Drive, pasta Arquivos › openhora › 2026):\n\nanual"),
    ("Relatorio anual", "da pasta /openhora/2026 do google drive", "Relatorio anual.txt (Google Drive, pasta Arquivos › openhora › 2026):\n\nanual")])
def test_the_folder_the_person_sees_is_matched_from_any_folder_without_the_alias_and_the_file_is_read(real, span, tail, text):
    says(real, span)
    assert phone(real, f"Me traga o arquivo {span} {tail}") == text


@pytest.mark.parametrize("tail", ["da pasta /Arquivos", "da pasta default", "na pasta /default/openhora", "na pasta Arquivos/openhora"])
def test_the_real_name_of_the_configured_folder_and_its_alias_also_match(real, tail):
    says(real, WANTED)
    assert phone(real, f"Me traga o arquivo {WANTED} {tail}") == OPENHORA_TEXT


def test_the_configured_folder_may_be_the_one_the_person_calls_openhora_itself(real):
    """The live case: the folder configured as "default" is the Drive folder that is called openhora, and the person types /openhora, a name the configuration never held."""
    real["drives"].names[("google", "GDRIVEFOLDER0001")] = "openhora"
    real["drives"].folders[("google", "GDRIVEFOLDER0001")] = [item("gmark00000000001", "openhora-mark.txt"), item("gdoc0000000001", WANTED)]
    says(real, "openhora-mark")
    assert phone(real, "Me traga o arquivo openhora-mark da pasta /openhora") == "openhora-mark.txt (Google Drive, pasta openhora):\n\nmarca do coral"
    says(real, WANTED)
    assert phone(real, f"Me traga o arquivo {WANTED} da pasta openhora") == f"{WANTED} (Google Drive, pasta openhora):\n\n" + DOC.strip()


def test_vacuity_a_match_through_the_alias_alone_would_refuse_or_note_the_live_lines_and_be_seen(real, monkeypatch):
    """The planted fault: a named folder is matched only through "<alias> > ..." (the S17 rule). The live line then finds the file anywhere and says it did not find the folder."""
    monkeypatch.setattr(ops_file_read, "_named_dirs", lambda tree, folder: [])
    says(real, WANTED)
    reply = phone(real, f"Me traga o arquivo {WANTED} da pasta /openhora")
    assert reply == OPENHORA_TEXT + "\n\n" + NOTE_OPENHORA.format(folder="openhora") and reply != OPENHORA_TEXT


@pytest.mark.parametrize("tail, shown", [("da pasta /inexistente", "inexistente"), ("da pasta inexistente", "inexistente"), ("da pasta /openhora/inexistente", "openhora/inexistente"),
                                         ("da pasta /2026/openhora", "2026/openhora"), ("da pasta Particular", "Particular")])
def test_a_folder_that_is_not_there_gives_the_file_found_anywhere_and_one_note(real, tail, shown):
    says(real, WANTED)
    assert phone(real, f"Me traga o arquivo {WANTED} {tail}") == OPENHORA_TEXT + "\n\n" + NOTE_OPENHORA.format(folder=shown)


def test_a_folder_that_is_not_there_and_a_file_that_is_not_either_gives_the_none_found_sentence_with_the_real_names(real):
    says(real, "relatorio inexistente")
    assert phone(real, "Mostre o arquivo relatorio inexistente da pasta /nada") == NONE_SUB


def test_vacuity_a_folder_that_matched_everything_would_give_no_note_and_be_seen(real, monkeypatch):
    """The planted fault: an unknown folder means every folder. The note the oracle above wants is then missing."""
    monkeypatch.setattr(ops_file_read, "_named_dirs", lambda tree, folder: list(tree["dirs"]))
    says(real, WANTED)
    assert phone(real, f"Me traga o arquivo {WANTED} da pasta /inexistente") == OPENHORA_TEXT


PROBES = ["da pasta ..", "da pasta ../Particular", "da pasta /openhora/../..", "da pasta /", "da pasta ~", "da pasta ~/Documentos", "da pasta 1AbCdEfGhIjKlMnOpQrStUvWxYz0123456",
          "na pasta OUTSIDEFOLDER0001DRIVEID00", "da pasta /1AbCdEfGhIjKlMnOpQrStUvWxYz0123456/x"]


@pytest.mark.parametrize("tail", PROBES)
def test_a_path_that_points_outside_the_granted_folders_is_refused_by_the_real_names_and_nothing_is_listed_or_read(real, tail):
    says(real, WANTED)
    reply = phone(real, f"Me traga o arquivo {WANTED} {tail}")
    assert reply == NO_FOLDER
    assert real["drives"].listed() == [] and real["drives"].reads() == []
    assert "default" not in reply and "OUTSIDE" not in reply and "Particular" not in reply


def test_vacuity_a_line_with_dots_that_was_searched_like_any_name_would_find_the_file_and_be_seen(real, monkeypatch):
    """The planted fault: nothing is "outside". The oracle above (refused, nothing listed) then fails, so it can fail."""
    monkeypatch.setattr(ops_file_read, "_outside", lambda raw: False)
    says(real, WANTED)
    assert phone(real, f"Me traga o arquivo {WANTED} da pasta ../Particular") == OPENHORA_TEXT + "\n\n" + NOTE_OPENHORA.format(folder="../Particular")
    assert real["drives"].listed() != []


def test_a_same_named_file_outside_the_grant_is_never_returned_whatever_folder_is_named(real):
    real["drives"].folders[("google", "gdir_openhora")] = [item("gdir_2026", "2026", kind="folder")]
    for tail in ("", "da pasta Particular", "da pasta /openhora", "da pasta ../Particular"):
        says(real, WANTED)
        reply = phone(real, f"Me traga o arquivo {WANTED} {tail}".strip())
        assert reply in (NONE_SUB, NO_FOLDER), reply
    assert real["drives"].reads() == []
    assert ("google", "OUTSIDEFOLDER0001") not in real["drives"].listed() and ("microsoft", "/Particular") not in real["drives"].listed()


def conversations(world):
    """Every reply the phone gives to the lines below, joined: found, listed, picked, none, refused, a folder not there."""
    out = []
    says(world, "first sin activities")
    out += [phone(world, "Me traga o arquivo first sin activities"), phone(world, "o 2"), phone(world, "Me traga o arquivo first sin activities na pasta Igreja")]
    says(world, WANTED)
    out += [phone(world, f"Me traga o arquivo {WANTED} da pasta /openhora"), phone(world, f"Me traga o arquivo {WANTED} da pasta /nada"), phone(world, f"Me traga o arquivo {WANTED} da pasta ..")]
    says(world, "relatorio inexistente")
    out.append(phone(world, "Mostre o arquivo relatorio inexistente"))
    return out


def test_no_reply_shows_the_alias_of_a_configured_folder(real):
    replies = conversations(real)
    assert all(r for r in replies) and len(replies) == 7
    for r in replies:
        assert "default" not in r, r
        assert "contratos" not in r and "GDRIVEFOLDER" not in r, r


def test_vacuity_a_walk_that_named_the_folders_by_their_alias_would_show_it_and_be_seen(real, monkeypatch):
    """The planted fault: the first name of every path is the alias. The oracle above then fails."""
    real_walk = ops_file_read._walk

    def aliased(cfg, account=None, names_only=False):
        out = real_walk(cfg, account, names_only)
        for key, info in out["info"].items():
            info["lead"] = info["alias"]
        out["files"] = [dict(f, path=(out["info"][(f["service"], f["root"])]["alias"],) + f["path"][1:]) for f in out["files"]]
        out["roots"] = [(service, out["info"][(service, root)]["alias"]) for (service, root) in out["info"]]
        return out
    monkeypatch.setattr(ops_file_read, "_walk", aliased)
    assert any("default" in r for r in conversations(real))


def test_a_name_the_provider_could_not_give_is_left_out_not_replaced_by_the_services_name_and_the_drive_root_is_my_drive(real):
    """S18b: the service's own name used to stand for a folder whose name was not read ("pasta Google Drive"); it names no folder, so the reply names the account alone, and a subfolder keeps its own name."""
    real["drives"].names.clear()
    says(real, WANTED, "google drive")
    assert phone(real, f"Me traga o arquivo {WANTED} do google drive") == f"{WANTED} (Google Drive, pasta openhora):\n\n" + DOC.strip()
    accept(real["path"], policies=FILE_PROFILES, messaging={"senders": FILE_SENDERS}, accounts={"google": {"address": "ana@mail.example", "folders": {"default": "root"}},
                                                                                           "microsoft": ACCOUNTS["microsoft"]}, language="pt-BR")
    real["drives"].folders[("google", "root")] = [item("gdoc0000000001", WANTED)]
    assert phone(real, f"Me traga o arquivo {WANTED} do google drive") == f"{WANTED} (Google Drive, pasta Meu Drive):\n\n" + DOC.strip()


def test_the_real_names_are_read_once_for_each_google_folder_in_a_search(real):
    says(real, "relatorio inexistente")
    phone(real, "Mostre o arquivo relatorio inexistente")
    stats = [a for s, v, a in real["drives"].calls if v == "stat"]
    assert sorted(stats) == [("--id", "GDRIVEFOLDER0001"), ("--id", "GDRIVEFOLDER0002")]


def test_the_plain_text_file_is_returned_as_text_as_before(real):
    says(real, WANTED)
    reply = phone(real, f"Me traga o arquivo {WANTED} da pasta /openhora")
    assert reply == OPENHORA_TEXT and SECRET_MARK in reply
