"""Send the found file itself on a messaging app, behind the group `send-files` (slice S18, runtime/ops_file_read.py, runtime/messaging_file.py), through `ops.say`.

The stand-ins of test_file_read.py (a model that answers each line with a text the test wrote, and two fictional drives in memory behind the providers' seam) are reused. The messaging
bridge says what its app can carry with `can_send` (the provider's limits); the operations layer hands the file back in `result["attachment"]` ({"name", "kind", "data"}: bytes in
memory). Every expectation is a literal of this file: the line, the model's text, the reply, the bytes, the calls the providers saw. No network, no model, no secret store; every name,
folder and text is invented.

  with `send-files`: a text file comes as a document plus its preview; an image as a photo; a PDF as a document (the converter's text is scanned)
  without it: today's reply, byte for byte, and no attachment; with it but no limits named (a page, a terminal, a provider that cannot carry a file): the same
  `send-files` without `read-files` is refused when the file is accepted; the widening list shown by `config` and by the refusal carries the new line
  a credential in the text withholds the file AND the preview (a PDF's converted text too); a file with no text to scan is sent as it is
  a file over the app's limit gets one sentence (and the preview when it has text); a type outside the app's list is not sent
  a pick ("o 2") asks the right and the grant again: a profile that lost `send-files`, or a folder that was removed, sends nothing
  what is kept: nothing of the file is in the conversation, the store, the log, the output or the data folder (checked), and the staging folder is gone

Each oracle has a `test_vacuity_` case: the fault is planted and the outcome the oracle would reject is seen, so the oracle can fail.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_send.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL_PT  # noqa: E402,F401

import json
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_file_read import (ACCOUNTS, ACTIVITIES, FILE_PROFILES, LINE_1, PLAIN_KEY, READER, READER_KEY, SECRET_MARK, WANTED, HEAD, drives, item, op, phone, stored)  # noqa: F401  (the fixture and its helpers)
from test_ops_natural import world  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_file_read = st.load("ops_file_read")
ops_say = st.load("ops_say")
operations = st.load("operations")
policy_widening = st.load("policy_widening")
messaging_file = st.load("messaging_file")

SENDER = "55119000000031"
SENDER_KEY = f"telegram:{SENDER}"
SEND_PROFILES = dict(FILE_PROFILES, sender=["read", "talk", "interpret", "read-files", "send-files"])
SEND_SENDERS = {"telegram": [{"id": READER, "policy": "reader"}, {"id": SENDER, "policy": "sender"}]}
LIMITS = {"max_bytes": 20971520, "photo_max_bytes": 10485760, "photo_types": ["png", "jpeg"],
          "types": ["pdf", "docx", "xlsx", "pptx", "ooxml", "html", "csv", "text", "png", "jpeg", "webp", "gif"]}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64 + b"coral"
PDF = b"%PDF-1.7 a report about the choir budget"
KEY_BLOCK = b"notes\n-----BEGIN PRIV" + b"ATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIV" + b"ATE KEY-----\n"
SENT_TEXT = "Aqui está Foto do coral.png (OneDrive, pasta Documentos)."  # validate: allow english-only -- the Portuguese sentence or name under test
WITHHELD = "Encontrei {name} ({account}), mas não envio por aqui: o arquivo parece conter uma senha ou uma chave."  # validate: allow english-only -- the Portuguese sentence or name under test
TOO_BIG = "Encontrei {name} ({account}), mas ele é grande demais para eu enviar por aqui."  # validate: allow english-only -- the Portuguese sentence or name under test
NOT_SENT_KIND = "Encontrei {name} ({account}), mas não consigo enviar esse tipo de arquivo por aqui."  # validate: allow english-only -- the Portuguese sentence or name under test
NO_FOLDER = ("Não encontrei essa pasta dentro das pastas configuradas para as suas contas, e não procuro fora delas: "  # validate: allow english-only -- the Portuguese sentence or name under test
             "Google Drive, OneDrive.")
WIDENING_LINE = ("sends the found file itself to the chat, not only its text: the whole file leaves your drive for the messaging app's servers; one whose text looks like a password or a key is "
                 "not sent (adds to read-files)")


@pytest.fixture
def sending(drives, monkeypatch):
    """The `drives` world with a sender who holds `send-files` beside `read-files`, a reader who holds only `read-files`, a photo and a report in the drives, and a converter stand-in."""
    accept(drives["path"], policies=SEND_PROFILES, messaging={"senders": SEND_SENDERS}, accounts=ACCOUNTS, language="pt-BR")
    made = drives["drives"]
    made.folders[("microsoft", "/Documentos")] = made.folders[("microsoft", "/Documentos")] + [item("drv1/it!5", "Foto do coral.png"), item("drv1/it!6", "Foto do coral.bmp")]
    made.folders[("google", "GDRIVEFOLDER0001")] = made.folders[("google", "GDRIVEFOLDER0001")] + [item("gfile0000000005", "Relatorio do coral.pdf")]
    made.files[("microsoft", "drv1/it!5")] = PNG
    made.files[("microsoft", "drv1/it!6")] = b"BM" + b"\x00" * 64
    made.files[("google", "gfile0000000005")] = PDF
    converted = {"text": "Relatorio do coral\n\nTotal: 10 vozes.\n"}

    def converter(input_path, subtype, out_dir):
        Path(out_dir, "converted.md").write_text(converted["text"], encoding="utf-8")
        return {"converter": "stand-in"}
    monkeypatch.setattr(ops_file_read, "converter", converter)
    drives["converted"] = converted
    return drives


def ask(world, line, span, key=SENDER_KEY, limits=LIMITS, service=None):
    """One line on a messaging app: the model's text names the file, the call names the app's limits. The whole result of `say`."""
    world["answer"]["text"] = op("file-read", {"file": span, **({"service": service} if service else {})})
    line = line if span in line else f"Me traga o arquivo {span}"      # the name is a piece of the line, as the interpreter's check asks
    return ops.say(world["path"], line, channel="messaging", sender=key, **({"can_send": limits} if limits is not None else {}))


# --- with the group ----------------------------------------------------------------------------------------------------------------------------


def assert_text_file_comes_as_document_with_preview(result):
    assert result["reply"] == HEAD + ACTIVITIES.strip()
    assert result["attachment"] == {"name": WANTED + ".txt", "kind": "document", "data": ACTIVITIES.encode("utf-8")}


def test_a_text_file_comes_as_a_document_and_keeps_its_preview_as_the_message_text(sending):
    assert_text_file_comes_as_document_with_preview(ask(sending, LINE_1, WANTED))
    assert sending["drives"].reads() == [("microsoft", "drv1/it!1")]


def test_a_text_file_in_a_subfolder_named_as_the_person_sees_it_comes_as_text_and_as_a_file(sending):
    """S17b: "/openhora" is a folder the person sees in the Drive, not the configuration's alias; the plain text comes as before and, with `send-files`, the file comes too."""
    made = sending["drives"]
    made.folders[("google", "GDRIVEFOLDER0001")] = made.folders[("google", "GDRIVEFOLDER0001")] + [item("gdir_openhora", "openhora", kind="folder")]
    made.folders[("google", "gdir_openhora")] = [item("gmark00000000001", "openhora-mark.txt")]
    made.files[("google", "gmark00000000001")] = "marca do coral".encode("utf-8")
    line = "Me traga o arquivo openhora-mark da pasta /openhora"
    result = ask(sending, line, "openhora-mark")
    assert result["reply"] == "openhora-mark.txt (Google Drive, pasta Arquivos › openhora):\n\nmarca do coral"
    assert result["attachment"] == {"name": "openhora-mark.txt", "kind": "document", "data": "marca do coral".encode("utf-8")}
    plain = ask(sending, line, "openhora-mark", key=READER_KEY)          # without `send-files`: the same text and no file
    assert plain["reply"] == result["reply"] and "attachment" not in plain


def test_vacuity_a_file_sent_as_a_photo_or_without_its_preview_would_be_seen(sending, monkeypatch):
    """The planted fault: every file is a photo. The oracle above (a document) then fails."""
    monkeypatch.setattr(ops_file_read, "_attachment", lambda match, got, send: ({"name": match["name"], "kind": "photo", "data": got["data"]}, ""))
    result = ask(sending, LINE_1, WANTED)
    assert result["attachment"]["kind"] == "photo" and result["attachment"]["name"] == WANTED


def test_an_image_comes_as_a_photo_with_one_sentence_and_no_preview(sending):
    result = ask(sending, "Me traga a foto do coral", "Foto do coral.png")
    assert result["reply"] == SENT_TEXT
    assert result["attachment"] == {"name": "Foto do coral.png", "kind": "photo", "data": PNG}


def test_vacuity_an_image_over_the_photo_limit_is_a_document_and_a_type_the_app_does_not_show_as_a_photo_too(sending):
    """The oracle above (a photo) holds only under the photo limit and the photo types: the same bytes with a smaller limit, or with jpeg and png off the list, come as a document."""
    small = dict(LIMITS, photo_max_bytes=10)
    assert ask(sending, "Me traga a foto do coral", "Foto do coral.png", limits=small)["attachment"]["kind"] == "document"
    no_photos = dict(LIMITS, photo_types=[])
    assert ask(sending, "Me traga a foto do coral", "Foto do coral.png", limits=no_photos)["attachment"]["kind"] == "document"


def test_a_pdf_comes_as_a_document_and_its_converted_text_is_the_preview(sending):
    result = ask(sending, "Me traga o relatorio do coral", "Relatorio do coral.pdf")
    assert result["reply"] == "Relatorio do coral.pdf (Google Drive, pasta Arquivos):\n\nRelatorio do coral\n\nTotal: 10 vozes."
    assert result["attachment"] == {"name": "Relatorio do coral.pdf", "kind": "document", "data": PDF}


def test_a_google_doc_exported_as_markdown_gets_an_ending_and_is_a_document(sending):
    made = sending["drives"]
    made.folders[("microsoft", "/Documentos")] = []
    made.folders[("google", "GDRIVEFOLDER0002")] = [item("gdoc0000000001", "Ata do coral")]
    made.files[("google", "gdoc0000000001")] = b"# Ata\n\nPresentes: 10.\n"
    made.markdown.add(("google", "gdoc0000000001"))
    result = ask(sending, "Me traga o arquivo Ata do coral", "Ata do coral")
    assert result["reply"] == "Ata do coral (Google Drive, pasta Contratos 2026):\n\n# Ata\n\nPresentes: 10."
    assert result["attachment"] == {"name": "Ata do coral.md", "kind": "document", "data": b"# Ata\n\nPresentes: 10.\n"}


def test_a_file_with_no_text_to_scan_is_sent_as_it_is_and_says_so_in_one_sentence(sending):
    sending["converted"]["text"] = "  \n"
    result = ask(sending, "Me traga o relatorio do coral", "Relatorio do coral.pdf")
    assert result["reply"] == "Aqui está Relatorio do coral.pdf (Google Drive, pasta Arquivos)."  # validate: allow english-only -- the Portuguese sentence or name under test
    assert result["attachment"] == {"name": "Relatorio do coral.pdf", "kind": "document", "data": PDF}


# --- without it --------------------------------------------------------------------------------------------------------------------------------


def test_without_the_group_the_reply_is_todays_text_and_no_file_goes(sending):
    result = ask(sending, LINE_1, WANTED, key=READER_KEY)
    assert result["reply"] == HEAD + ACTIVITIES.strip()
    assert "attachment" not in result
    plain = ops.say(sending["path"], LINE_1, channel="messaging", sender=READER_KEY)      # the call as it was before this slice
    assert plain == result, "byte for byte the reply that was made before the group existed"


def test_vacuity_a_reply_that_ignored_the_group_would_send_the_file_to_the_reader(sending, monkeypatch):
    """The planted fault: the group is not asked. The reader, who holds only `read-files`, then gets the file; the oracle above (none) fails."""
    monkeypatch.setattr(operations, "holds", lambda group, channel, policy, sender=None: True)
    assert ask(sending, LINE_1, WANTED, key=READER_KEY)["attachment"]["name"] == WANTED + ".txt"


@pytest.mark.parametrize("limits", [None, {}, {"max_bytes": 0, "photo_max_bytes": 0, "photo_types": [], "types": []}, {"max_bytes": True, "photo_max_bytes": 0, "photo_types": [], "types": []}])
def test_with_the_group_but_no_usable_limits_from_the_app_no_file_goes(sending, limits):
    result = ask(sending, LINE_1, WANTED, limits=limits)
    assert result["reply"] == HEAD + ACTIVITIES.strip() and "attachment" not in result


def test_the_limits_are_ignored_off_a_messaging_app_and_the_typed_operation_returns_no_bytes(sending):
    assert ops_file_read._sending(ops_core.context(sending["path"]), "page", SENDER_KEY, {"can_send": LIMITS}) is None
    assert ops_file_read._sending(ops_core.context(sending["path"]), "messaging", SENDER_KEY, {"can_send": LIMITS}) == dict(LIMITS, types=list(LIMITS["types"]))
    out = ops.file_read(sending["path"], WANTED, account="microsoft", channel="messaging", sender=SENDER_KEY)
    assert out == {"status": "text", "name": WANTED, "folder": "Documentos", "account": "microsoft", "text": ACTIVITIES.strip(), "remaining": 0}


# --- the group in the configuration ------------------------------------------------------------------------------------------------------------


def test_send_files_without_read_files_is_refused_when_the_file_is_accepted(drives):
    write_config(drives["path"], policies=dict(FILE_PROFILES, sender=["read", "talk", "send-files"]), messaging={"senders": {"telegram": [{"id": SENDER, "policy": "sender"}]}})
    with pytest.raises(Exception) as refused:
        ops.accept_config(drives["path"], ops.config(drives["path"])["sha256"])
    assert "'send-files' needs 'read-files' beside it (it sends the file that reading files finds, so a policy that only sends is refused)" in str(refused.value)
    write_config(drives["path"], policies=None, messaging={"senders": {"telegram": [READER]}}, channels={"messaging": ["read", "talk", "send-files"]})
    with pytest.raises(Exception) as refused:
        ops.accept_config(drives["path"], ops.config(drives["path"])["sha256"])
    assert "channels.messaging: 'send-files' needs 'read-files' beside it" in str(refused.value)


def test_vacuity_a_policy_with_both_groups_is_accepted(drives):
    """The refusal above is of the missing `read-files` and of nothing else: the same profile with both groups is accepted."""
    accept(drives["path"], policies=dict(FILE_PROFILES, sender=["read", "talk", "read-files", "send-files"]), messaging={"senders": {"telegram": [{"id": SENDER, "policy": "sender"}]}})


def test_the_group_is_in_no_default_is_the_messaging_apps_alone_and_adds_to_read_files_without_granting_it(drives):
    assert "send-files" not in operations.DEFAULT_POLICY["messaging"]
    assert operations.GROUPS["send-files"] == {"operations": ("file-read",), "kind": "send"}
    assert "send-files" in operations.MESSAGING_ONLY_GROUPS and "send-files" in operations.KIND_ONLY
    assert operations.group_refusal("page", "send-files") is not None and operations.group_refusal("mcp", "send-files") is not None
    assert operations.group_refusal("messaging", "send-files") is None
    assert not operations.policy_allows("file-read", "messaging", {"messaging": ["send-files"]}), "it never grants the read it adds to"
    assert operations.holds("send-files", "messaging", {"messaging": ["read-files", "send-files"]}) and not operations.holds("send-files", "messaging", {"messaging": ["read-files"]})
    assert not operations.holds("send-files", "messaging", {}), "a channel with no entry holds nothing here"


def test_the_widening_list_shown_by_config_and_by_the_refusal_carries_the_line(drives):
    assert policy_widening.means("messaging", "send-files") == WIDENING_LINE
    write_config(drives["path"], policies=SEND_PROFILES, messaging={"senders": SEND_SENDERS})
    shown = ops.config(drives["path"])
    mine = [w for w in shown["widening"] if w["group"] == "send-files"]
    assert len(mine) == 1 and mine[0]["place"] == SENDER_KEY and mine[0]["means"] == WIDENING_LINE
    with pytest.raises(ops_core.OpsError) as refused:
        ops.accept_config(drives["path"], shown["sha256"])
    assert f"{SENDER_KEY}:send-files" in str(refused.value) and WIDENING_LINE in str(refused.value) and shown["widening_sha256"] in str(refused.value)


def test_vacuity_a_policy_without_the_group_lists_nothing_to_confirm(drives):
    write_config(drives["path"], policies=FILE_PROFILES, messaging={"senders": {"telegram": [{"id": READER, "policy": "reader"}]}})
    assert [w for w in ops.config(drives["path"])["widening"] if w["group"] == "send-files"] == []


# --- the credential scan -------------------------------------------------------------------------------------------------------------------------


def test_a_planted_credential_withholds_the_file_and_the_preview(sending):
    sending["drives"].files[("microsoft", "drv1/it!1")] = KEY_BLOCK
    result = ask(sending, LINE_1, WANTED)
    assert result["reply"] == WITHHELD.format(name=WANTED, account="OneDrive")
    assert "attachment" not in result and "MIIEvQ" not in result["reply"] and "notes" not in result["reply"]


def test_a_planted_credential_in_the_converted_text_of_a_pdf_withholds_it_too(sending):
    sending["converted"]["text"] = "Relatorio\n\n" + KEY_BLOCK.decode("ascii")
    result = ask(sending, "Me traga o relatorio do coral", "Relatorio do coral.pdf")
    assert result["reply"] == WITHHELD.format(name="Relatorio do coral.pdf", account="Google Drive")
    assert "attachment" not in result


def test_vacuity_a_scan_that_found_nothing_would_send_the_credential(sending, monkeypatch):
    """The planted fault: the scan finds nothing. The credential then goes out as a document and shows in the preview; the oracles above fail."""
    sending["drives"].files[("microsoft", "drv1/it!1")] = KEY_BLOCK
    monkeypatch.setattr(ops_file_read.sources._workcopy(), "scan", lambda data: None)
    result = ask(sending, LINE_1, WANTED)
    assert result["attachment"]["data"] == KEY_BLOCK and "MIIEvQ" in result["reply"]


# --- the limits ----------------------------------------------------------------------------------------------------------------------------------


def test_a_text_file_over_the_limit_gets_the_sentence_after_its_preview_and_no_file(sending):
    result = ask(sending, LINE_1, WANTED, limits=dict(LIMITS, max_bytes=10))
    assert result["reply"] == HEAD + ACTIVITIES.strip() + "\n\n" + TOO_BIG.format(name=WANTED, account="OneDrive")
    assert "attachment" not in result


def test_an_image_over_the_limit_gets_the_sentence_alone(sending):
    result = ask(sending, "Me traga a foto do coral", "Foto do coral.png", limits=dict(LIMITS, max_bytes=10))
    assert result["reply"] == TOO_BIG.format(name="Foto do coral.png", account="OneDrive")
    assert "attachment" not in result


def test_vacuity_a_size_check_that_always_passed_would_send_the_big_file(sending, monkeypatch):
    """The planted fault: the size is not checked. The file goes out over the limit; the oracles above fail."""
    monkeypatch.setattr(ops_file_read, "_limits", lambda caps: {"max_bytes": 10 ** 12, "photo_max_bytes": 10 ** 12, "photo_types": [], "types": list(LIMITS["types"])})
    assert ask(sending, LINE_1, WANTED, limits=dict(LIMITS, max_bytes=10))["attachment"]["data"] == ACTIVITIES.encode("utf-8")


def test_a_type_outside_the_apps_list_or_that_cannot_be_told_is_not_sent(sending):
    result = ask(sending, "Me traga a foto do coral", "Foto do coral.bmp")
    assert result["reply"] == NOT_SENT_KIND.format(name="Foto do coral.bmp", account="OneDrive") and "attachment" not in result
    no_png = dict(LIMITS, types=[t for t in LIMITS["types"] if t != "png"])
    result = ask(sending, "Me traga a foto do coral", "Foto do coral.png", limits=no_png)
    assert result["reply"] == NOT_SENT_KIND.format(name="Foto do coral.png", account="OneDrive") and "attachment" not in result


def test_vacuity_a_type_list_that_was_not_read_would_send_the_bmp(sending):
    """The oracle above rests on the list: with `bmp`-like bytes and no image sniffer entry the file is refused by the list alone; an app that lists `text` takes a text file."""
    only_text = dict(LIMITS, types=["text"])
    assert ask(sending, LINE_1, WANTED, limits=only_text)["attachment"]["kind"] == "document"
    assert "attachment" not in ask(sending, "Me traga o relatorio do coral", "Relatorio do coral.pdf", limits=only_text)


# --- the pick ("o 2") ----------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def two(sending):
    """Two files that carry the same words, one in each drive, so that a list is shown and a number picks one."""
    made = sending["drives"]
    made.folders[("google", "GDRIVEFOLDER0001")] = [item("gplan00000000001", "Plano do coral.txt")]
    made.folders[("microsoft", "/Documentos")] = [item("drv1/it!7", "Plano do coral.txt")]
    made.files[("google", "gplan00000000001")] = b"Plano do Google.\n"
    made.files[("microsoft", "drv1/it!7")] = b"Plano do OneDrive.\n"
    ops_file_read.forget_lists()
    return sending


LIST = ('Encontrei 2 arquivos que combinam. Qual deles? Diga o número, por exemplo "o 2".'  # validate: allow english-only -- the Portuguese sentence or name under test
        "\n1. Plano do coral.txt - pasta Arquivos, Google Drive\n2. Plano do coral.txt - pasta Documentos, OneDrive")


def pick(world, number=2, key=SENDER_KEY, limits=LIMITS):
    return ops.say(world["path"], f"o {number}", channel="messaging", sender=key, **({"can_send": limits} if limits is not None else {}))


def test_a_pick_after_a_list_sends_the_file_it_names_as_a_document_with_its_preview(two):
    assert ask(two, "Me traga o arquivo Plano do coral", "Plano do coral")["reply"] == LIST
    picked = pick(two)
    assert picked["reply"] == "Plano do coral.txt (OneDrive, pasta Documentos):\n\nPlano do OneDrive."
    assert picked["attachment"] == {"name": "Plano do coral.txt", "kind": "document", "data": b"Plano do OneDrive.\n"}


def test_a_pick_after_send_files_left_the_policy_sends_nothing(two):
    assert ask(two, "Me traga o arquivo Plano do coral", "Plano do coral")["reply"] == LIST
    accept(two["path"], policies=dict(SEND_PROFILES, sender=["read", "talk", "interpret", "read-files"]), messaging={"senders": SEND_SENDERS})
    picked = pick(two)
    assert picked["reply"] == "Plano do coral.txt (OneDrive, pasta Documentos):\n\nPlano do OneDrive."
    assert "attachment" not in picked


def test_vacuity_a_pick_that_did_not_ask_the_group_again_would_send_the_file(two, monkeypatch):
    """The planted fault: the group is believed from the search. The file goes after the group was removed; the oracle above fails."""
    assert ask(two, "Me traga o arquivo Plano do coral", "Plano do coral")["reply"] == LIST
    accept(two["path"], policies=dict(SEND_PROFILES, sender=["read", "talk", "interpret", "read-files"]), messaging={"senders": SEND_SENDERS})
    monkeypatch.setattr(ops_file_read, "_sending", lambda ctx, channel, sender, extras: ops_file_read._limits(extras.get("can_send")))
    assert pick(two)["attachment"]["data"] == b"Plano do OneDrive.\n"


def test_a_pick_after_read_files_left_the_policy_gets_the_refusal_and_sends_nothing(two):
    assert ask(two, "Me traga o arquivo Plano do coral", "Plano do coral")["reply"] == LIST
    accept(two["path"], policies=dict(SEND_PROFILES, sender=["read", "talk", "interpret"]), messaging={"senders": SEND_SENDERS})
    picked = pick(two)
    assert picked["reply"] == PLAIN_REFUSAL_PT and "attachment" not in picked
    assert two["drives"].reads() == []


def test_a_pick_after_the_folder_was_removed_sends_nothing(two):
    assert ask(two, "Me traga o arquivo Plano do coral", "Plano do coral")["reply"] == LIST
    accept(two["path"], accounts={"google": ACCOUNTS["google"], "microsoft": {"address": "ana@outlook.example", "folders": {"outra": "/Outra"}}})
    picked = pick(two)
    assert picked["reply"] == ("Não encontrei essa pasta dentro das pastas configuradas para as suas contas, e não procuro fora delas: "  # validate: allow english-only -- the Portuguese sentence or name under test
                               "Google Drive, OneDrive.")
    assert "attachment" not in picked
    assert two["drives"].reads() == []


def test_vacuity_a_pick_that_did_not_ask_the_grant_again_would_read_and_send_from_the_removed_folder(two, monkeypatch):
    """The planted fault: the list is believed. The file of the folder that is no longer configured is read and sent; the oracle above fails."""
    assert ask(two, "Me traga o arquivo Plano do coral", "Plano do coral")["reply"] == LIST
    accept(two["path"], accounts={"google": ACCOUNTS["google"], "microsoft": {"address": "ana@outlook.example", "folders": {"outra": "/Outra"}}})
    real = ops_file_read.project_config.account_entry

    def believed(cfg, service):
        return {"folders": {"default": "/Documentos", "contratos": "GDRIVEFOLDER0002"}} if service == "microsoft" else real(cfg, service)
    monkeypatch.setattr(ops_file_read.project_config, "account_entry", believed)
    assert pick(two)["attachment"]["data"] == b"Plano do OneDrive.\n"


# --- the bridge's side: one temporary file, gone after the send ------------------------------------------------------------------------------------


def test_the_limits_a_provider_declares_become_the_limits_of_the_call():
    caps = {"send_files": True, "max_send_bytes": 100, "max_photo_bytes": 50, "photo_types": ["png"], "send_types": ["text", "png"]}
    assert messaging_file.limits(caps) == {"max_bytes": 100, "photo_max_bytes": 50, "photo_types": ["png"], "types": ["text", "png"]}
    assert messaging_file.limits(dict(caps, send_files=False)) is None
    assert messaging_file.limits({k: v for k, v in caps.items() if k != "send_files"}) is None
    assert messaging_file.limits(dict(caps, max_send_bytes=0)) is None
    assert messaging_file.limits(None) is None


def test_the_file_is_checked_again_at_the_send_and_staged_in_one_file_that_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(messaging_file.tempfile, "tempdir", str(tmp_path))
    caps = messaging_file.limits({"send_files": True, "max_send_bytes": 100, "max_photo_bytes": 50, "photo_types": ["png"], "send_types": ["text", "png"]})
    held = {"name": "a.txt", "kind": "document", "data": b"hello"}
    policy = {"messaging": ["read", "read-files", "send-files"]}
    assert messaging_file.allowed(operations, policy, SENDER_KEY, held, caps) is True
    assert messaging_file.allowed(operations, {"messaging": ["read", "read-files"]}, SENDER_KEY, held, caps) is False, "the group was removed since the search"
    assert messaging_file.allowed(operations, {"messaging": ["read", "send-files"]}, SENDER_KEY, held, caps) is False
    assert messaging_file.allowed(operations, policy, SENDER_KEY, dict(held, data=b"x" * 101), caps) is False
    assert messaging_file.allowed(operations, policy, SENDER_KEY, dict(held, kind="photo", data=b"x" * 51), caps) is False
    assert messaging_file.allowed(operations, policy, SENDER_KEY, dict(held, kind="video"), caps) is False
    with messaging_file.staged(held) as entry:
        assert entry["name"] == "a.txt" and entry["kind"] == "document" and Path(entry["path"]).read_bytes() == b"hello"
        assert oct(Path(entry["path"]).stat().st_mode & 0o777) == "0o600" and oct(Path(entry["path"]).parent.stat().st_mode & 0o777) == "0o700"
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(RuntimeError):
        with messaging_file.staged(held):
            raise RuntimeError("the send failed")
    assert list(tmp_path.iterdir()) == [], "removed in a finally, whatever the end"


def test_vacuity_a_staging_that_forgot_to_remove_would_leave_the_bytes(tmp_path, monkeypatch):
    """The planted fault: the folder is not removed. The bytes stay; the oracle above (nothing left) fails."""
    monkeypatch.setattr(messaging_file.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(messaging_file.shutil, "rmtree", lambda *a, **k: None)
    with messaging_file.staged({"name": "a.txt", "kind": "document", "data": b"hello"}):
        pass
    assert [p.name for p in tmp_path.iterdir()] != []


# --- what is kept --------------------------------------------------------------------------------------------------------------------------------


def test_nothing_of_the_file_is_kept_in_the_conversation_the_store_the_log_the_output_or_the_data_folder(sending, caplog, capsys):
    sending["drives"].files[("microsoft", "drv1/it!5")] = PNG + b"UNIQUE-IMAGE-BYTES-18"
    result = ask(sending, LINE_1, WANTED)
    assert SECRET_MARK in result["reply"] and SECRET_MARK.encode() in result["attachment"]["data"]
    ask(sending, "Me traga a foto do coral", "Foto do coral.png")
    rows = stored(sending)
    assert [r["text"] for r in rows if r["role"] == "assistant"][-2:] == ["(mostrado onde foi pedido)", "(mostrado onde foi pedido)"]
    assert [r["text"] for r in rows if r["role"] == "user"][-2:] == ["(uma mensagem)", "(uma mensagem)"]
    everything = json.dumps(rows, ensure_ascii=False)
    for piece in (SECRET_MARK, WANTED, "ensaio do coral", "Atividades", "Foto do coral", "UNIQUE-IMAGE-BYTES-18"):
        assert piece not in everything
    seen = capsys.readouterr()
    for piece in (SECRET_MARK, WANTED, "Foto do coral", "UNIQUE-IMAGE-BYTES-18"):
        assert piece not in seen.out + seen.err + caplog.text
    holders = [Path(sending["path"]), Path(ops_core.context(sending["path"])["cfg"]["data_dir"])]
    for root in holders:
        for found in root.rglob("*"):
            if found.is_file() and ".git" not in found.parts:
                body = found.read_bytes()
                assert SECRET_MARK.encode() not in body and b"UNIQUE-IMAGE-BYTES-18" not in body, str(found.relative_to(root))
    staging = Path(ops_core.context(sending["path"])["cfg"]["data_dir"]) / "sources-staging"
    assert not staging.exists() or list(staging.iterdir()) == []
    assert ops.sources_catalog(sending["path"])["sources"] == []


def test_vacuity_a_store_that_kept_the_reply_would_show_the_mark(sending):
    """The oracle above looks for the file's words in the store; the reply that was SENT does hold them, so the check can fail."""
    result = ask(sending, LINE_1, WANTED)
    assert SECRET_MARK in result["reply"] and SECRET_MARK in json.dumps(result["reply"]), "the reply carries the words; the store must not"
