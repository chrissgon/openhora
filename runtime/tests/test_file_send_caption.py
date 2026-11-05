"""The file alone, with one short caption (slice S18b; runtime/ops_file_read.py `_read_match`, `_render`, `_matches_of`, runtime/messaging_bridge.py `line`), through `ops.say`.

The maintainer's retest: with `send-files` the file came AND a long preview of its text. The person asked for the file, so a sender who holds `send-files` and whose app carries it gets the file
and one caption ("Here is the file <name> (<account>, folder <folder>).", in the project's language), never the text; every case in which the file is withheld gets its own sentence and never the
preview either. A sender without `send-files` gets the text, as before. The folder in the caption is the configured folder's real name ("Meu Drive" for the Drive root) with the subfolders after
it; when the name could not be read the account alone is named (the service's own name used to stand in for the folder: "pasta Google Drive").

Each oracle has a `test_vacuity_` case. Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_send_caption.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL_PT  # noqa: E402,F401

import time

import pytest

import standin_tree as st
from test_ask import accept
from test_file_read import ACCOUNTS, READER_KEY, WANTED, drives, item  # noqa: F401
from test_file_search_subfolders import DOC, real, tree  # noqa: F401  (the fixtures of the subfolder tests)
from test_file_send import KEY_BLOCK, LIMITS, SEND_PROFILES, SEND_SENDERS, TOO_BIG, WITHHELD, ask, caption
from test_ops_natural import world  # noqa: F401

ops_file_read = st.load("ops_file_read")
LINE = f"Me traga o arquivo {WANTED} da pasta /openhora"
ROOT_LINE = "Me traga o arquivo Nota na raiz"


@pytest.fixture
def holder(real):
    """The subfolder world with a sender who holds `send-files`, and a text file at the configured root."""
    accept(real["path"], policies=SEND_PROFILES, messaging={"senders": SEND_SENDERS}, accounts=ACCOUNTS, language="pt-BR")
    made = real["drives"]
    made.folders[("google", "GDRIVEFOLDER0001")] = made.folders[("google", "GDRIVEFOLDER0001")] + [item("groot0000000001", "Nota na raiz.txt")]
    made.files[("google", "groot0000000001")] = b"nota do coral\n"
    ops_file_read.forget_lists()
    return real


# --- the live line ----------------------------------------------------------------------------------------------------------------------------


def test_the_live_line_with_send_files_gives_one_caption_and_the_file_and_no_text(holder):
    holder["drives"].names[("google", "GDRIVEFOLDER0001")] = "openhora"          # the configured folder is the one called openhora in the Drive
    holder["drives"].folders[("google", "GDRIVEFOLDER0001")] = [item("gdoc0000000001", WANTED)]
    result = ask(holder, LINE, WANTED)
    assert result["reply"] == caption(WANTED, "Google Drive", "openhora")
    assert result["attachment"]["name"] == WANTED + ".md" and result["attachment"]["data"] == DOC.encode("utf-8") and result["attachment"]["kind"] == "document"
    assert "In-Class" not in result["reply"] and "ensaio" not in result["reply"] and "ZEBRA" not in result["reply"] and "\n" not in result["reply"], "one line, no text of the file"


def test_vacuity_without_send_files_the_same_line_is_the_text_as_before(holder):
    holder["drives"].names[("google", "GDRIVEFOLDER0001")] = "openhora"
    holder["drives"].folders[("google", "GDRIVEFOLDER0001")] = [item("gdoc0000000001", WANTED)]
    result = ask(holder, LINE, WANTED, key=READER_KEY)
    assert result["reply"] == f"{WANTED} (Google Drive, pasta openhora):\n\n" + DOC.strip() and "attachment" not in result


def test_a_file_in_a_subfolder_names_the_configured_folders_real_name_then_the_subfolder(holder):
    result = ask(holder, LINE, WANTED)
    assert result["reply"] == caption(WANTED, "Google Drive", "Arquivos › openhora") and result["attachment"]["name"] == WANTED + ".md"


def test_a_file_at_the_configured_root_names_the_configured_folder_alone(holder):
    result = ask(holder, ROOT_LINE, "Nota na raiz")
    assert result["reply"] == caption("Nota na raiz.txt", "Google Drive", "Arquivos") and result["attachment"]["data"] == b"nota do coral\n"


def test_the_drive_root_is_my_drive(holder):
    accept(holder["path"], policies=SEND_PROFILES, messaging={"senders": SEND_SENDERS}, accounts={"google": {"address": "ana@mail.example", "folders": {"default": "root"}}, "microsoft": ACCOUNTS["microsoft"]}, language="pt-BR")
    holder["drives"].folders[("google", "root")] = [item("groot0000000001", "Nota na raiz.txt")]
    result = ask(holder, ROOT_LINE, "Nota na raiz")
    assert result["reply"] == caption("Nota na raiz.txt", "Google Drive", "Meu Drive")


def test_a_name_that_was_not_read_leaves_the_folder_out_at_the_root_and_keeps_the_subfolder(holder):
    holder["drives"].names.clear()
    root = ask(holder, ROOT_LINE, "Nota na raiz")
    assert root["reply"] == caption("Nota na raiz.txt", "Google Drive") == "Aqui está o arquivo Nota na raiz.txt (Google Drive)."  # validate: allow english-only -- the Portuguese sentence or name under test
    assert "pasta" not in root["reply"]
    sub = ask(holder, LINE, WANTED)
    assert sub["reply"] == caption(WANTED, "Google Drive", "openhora")
    plain = ask(holder, ROOT_LINE, "Nota na raiz", key=READER_KEY)          # the text of a reader names the account alone too
    assert plain["reply"] == "Nota na raiz.txt (no Google Drive):\n\nnota do coral"  # validate: allow english-only -- the Portuguese sentence or name under test


def test_vacuity_the_services_name_in_place_of_the_folder_is_what_the_live_reply_said(holder, monkeypatch):
    """The planted fault: the matches keep the first name of the path whether it was read or not. The reply says "pasta Google Drive", as the live one did."""
    holder["drives"].names.clear()
    monkeypatch.setattr(ops_file_read, "_matches_of", lambda found: [{"service": f["service"], "folder": ops_file_read.PATH_JOIN.join(f["path"]), "root": f["root"], "id": f["id"], "name": f["name"],
                                                                     "supported": f["supported"], "size": f["size"], "modified": f["modified"], "exact": f["exact"]} for f in found])
    assert ask(holder, ROOT_LINE, "Nota na raiz")["reply"] == caption("Nota na raiz.txt", "Google Drive", "Google Drive")


def test_a_name_that_comes_late_is_waited_for_and_one_that_never_comes_in_time_is_left_out(holder, monkeypatch):
    """The cause found for the live "pasta Google Drive": the read of the folder's name had 2 s, from the provider's start to its answer, and a name that was late fell back to the service's name."""
    real_call = holder["drives"].__call__

    def slow(cls, verb, args, **kw):
        if verb == "stat":
            time.sleep(0.4)
        return real_call(cls, verb, args, **kw)
    monkeypatch.setattr(ops_file_read, "provider_call", slow)
    assert ask(holder, ROOT_LINE, "Nota na raiz")["reply"] == caption("Nota na raiz.txt", "Google Drive", "Arquivos")
    monkeypatch.setattr(ops_file_read, "ROOT_NAME_SECONDS", 0.1)
    assert ask(holder, ROOT_LINE, "Nota na raiz")["reply"] == caption("Nota na raiz.txt", "Google Drive")
    assert ops_file_read.MAX_SECONDS == 10.0, "the walk keeps its own ten seconds"


# --- the cases in which the file is withheld: the sentence, never the preview -------------------------------------------------------------------


def test_a_credential_withholds_the_file_and_the_text(holder):
    holder["drives"].files[("google", "groot0000000001")] = KEY_BLOCK
    result = ask(holder, ROOT_LINE, "Nota na raiz")
    assert result["reply"] == WITHHELD.format(name="Nota na raiz.txt", account="Google Drive") and "attachment" not in result and "MIIEvQ" not in result["reply"]


def test_a_file_over_the_limit_gets_the_sentence_and_not_the_text(holder):
    result = ask(holder, ROOT_LINE, "Nota na raiz", limits=dict(LIMITS, max_bytes=5))
    assert result["reply"] == TOO_BIG.format(name="Nota na raiz.txt", account="Google Drive") and "attachment" not in result and "nota do coral" not in result["reply"]


def test_a_type_that_is_not_sent_gets_the_sentence_and_not_the_text(holder):
    result = ask(holder, ROOT_LINE, "Nota na raiz", limits=dict(LIMITS, types=["png"]))
    assert result["reply"] == "Encontrei Nota na raiz.txt (Google Drive), mas não consigo enviar esse tipo de arquivo por aqui." and "attachment" not in result  # validate: allow english-only -- the Portuguese sentence or name under test


def test_vacuity_the_same_file_under_the_limits_goes_with_its_caption(holder):
    result = ask(holder, ROOT_LINE, "Nota na raiz")
    assert result["reply"] == caption("Nota na raiz.txt", "Google Drive", "Arquivos") and result["attachment"]["data"] == b"nota do coral\n"
