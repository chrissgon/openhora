"""Images and files saved to the person's own Drive or OneDrive from a messaging app (package ATT-3): a photo or an image file is held as a SAVE-ONLY hold (never converted,
never a source, never shown to a model), one card per file offers what the sender may do (save to each account the project lists, add to the project for a type that can be
a source, discard), the caption only preselects, a line about the file just sent acts on it, and the W4a save writes the held bytes with the media type of the image.
Over the real operations layer, a stand-in messenger and the W4a fake writers; the card of a save is stubbed where the bridge is tested (test_files_write.py proves the
write itself). No model, no network; synthetic images made here, invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_save_images.py
"""
from __future__ import annotations

import hashlib
import json

import pytest

import standin_tree as st
from sources_fixture import make_pdf
from test_attachments import IDENT, PDF, accept, case  # noqa: F401  (the project the attachment tests use)
from test_files_write import hold as hold_row, world as files_world  # noqa: F401  (the W4a world, a fake Drive and OneDrive)
from test_messaging_attach import make_world

ops = st.load("ops")
sources = st.load("sources")
ops_core = st.load("ops_core")
ops_natural_writes = st.load("ops_natural_writes")
attachments = st.load("attachments")
files_document = st.load("files_document")
natural_writes = st.load("natural_writes")
operations = st.load("operations")
phrases = st.load("phrases")
intake = st.load("intake")
step_files = st.load("step_files")

OTHER = "5151515151"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00synthetic"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00synthetic pixels"
GIF = b"GIF89a\x01\x00\x01\x00synthetic"
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 synthetic"
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"\x00" * 16
AVIF = b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifmif1" + b"\x00" * 16
ACCOUNTS = {"google": {"address": "pat@example.com", "folders": {"default": "FolderId0001"}},
            "microsoft": {"address": "casey@mail.example", "folders": {"default": "/Documents/openhora"}}}
PROFILES = {"owner": ["read", "talk", "add-sources", "files-write"], "saver": ["read", "talk", "files-write"], "staff": ["read", "talk", "add-sources"]}
SENDERS = [{"id": IDENT, "policy": "owner"}, {"id": OTHER, "policy": "staff"}]
SAVED = {"request": 1, "task": 1, "pending": 9, "word": "files", "on_cards": True}


def setup(case, monkeypatch, language="pt-BR", senders=None, accounts=ACCOUNTS, profiles=PROFILES):  # noqa: F811
    """A bridge over the stand-in messenger for a project that lists both accounts; the save card is stubbed (its calls are recorded in `seen`)."""
    seen = []
    monkeypatch.setattr(ops_natural_writes, "_call_operation", lambda project, op, args, channel, sender: (seen.append((op, dict(args), channel, sender)) or dict(SAVED)))
    w = make_world(case, monkeypatch)
    accept(case.path, accounts=accounts, policies=profiles, channels={"page": ["read"]}, language=language, messaging={"senders": {"telegram": senders or SENDERS}})
    sent_cards = []
    monkeypatch.setattr(w.bridge, "resend", lambda project, chat, pending: (sent_cards.append(pending) or True))
    w.seen, w.save_cards = seen, sent_cards
    return w


def teardown(w):
    w.bridge.stopping.set()
    w.settle()


def labels(w):
    return [a["label"] for a in w.sent()[-1]["message"]["actions"]]


def action(w, op):
    return next(a["id"] for a in w.sent()[-1]["message"]["actions"] if a["id"].endswith(":" + op))


def cards_sent(w):
    return [s for s in w.sent() if s["message"]["actions"]]


# --- what the bytes are --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("data, kind", [(PNG, "png"), (JPEG, "jpeg"), (GIF, "gif"), (WEBP, "webp"), (HEIC, "heic")])
def test_the_images_are_read_from_their_first_bytes_and_avif_is_not_one(data, kind):
    found = intake.sniff(data)
    assert found is not None and found[1] == kind and attachments.is_save_only(kind)
    attachments.accept_hold(found)
    with pytest.raises(intake.IntakeError):
        attachments.accept_hold(intake.sniff(AVIF))


def test_the_declared_type_of_an_image_must_be_what_its_bytes_are_and_a_photo_is_a_jpeg():
    wrong = attachments.mismatch
    assert wrong("image/png", "jpeg") is True and wrong("image/png", "png") is False and wrong("image/jpeg", "png") is True
    assert wrong("photo", "jpeg") is False and wrong("photo", "png") is True
    assert wrong("image/heic", "heic") is False and wrong("image/heif", "mif1") is False and wrong("image/heic", "pdf") is True
    assert wrong("application/pdf", "png") is True
    assert wrong("application/octet-stream", "png") is False, "a generic type goes by the bytes"


def test_a_photo_has_a_generated_name_and_an_image_gets_the_extension_its_bytes_say():
    taken = attachments.normalised({"ref": "r", "name": None, "size": 5, "type": "photo"})
    assert taken["type"] == "image/jpeg" and taken["name"].startswith("photo-") and taken["name"].endswith(".jpg")
    assert attachments.normalised({"ref": "r", "name": "x.pdf", "type": "application/pdf"})["name"] == "x.pdf"
    assert attachments.image_name("holiday", "png") == "holiday.png" and attachments.image_name("holiday.png", "png") == "holiday.png"
    assert attachments.image_name("holiday.png", "jpeg") == "holiday.jpg" and attachments.image_name("holiday.jpeg", "jpeg") == "holiday.jpeg"
    assert attachments.image_name("IMG_1.HEIC", "heic") == "IMG_1.HEIC" and attachments.image_name("IMG_1", "mif1") == "IMG_1.heif"


# --- the hold: save only -------------------------------------------------------------------------------------------------------------------


def test_an_image_is_held_save_only_with_no_source_id_and_the_bytes_untouched(case):  # noqa: F811
    out = case.hold(PNG, name="holiday", declared="image/png")
    row = case.rows()[0]
    assert (row["status"], row["kind"], row["target"], row["label"], row["name"]) == ("held", "png", None, None, "holiday.png")
    assert out["save_only"] is True and out["attachment"]["save_only"] is True and out["target"] is None
    assert attachments.read_held(str(case.data), row["id"]) == PNG
    assert sources.list_catalog(case.ctx, hashes=False) == [], "nothing reaches the sources"


def test_the_grant_that_adds_at_once_never_adds_an_image(case):  # noqa: F811
    from test_attachments import accept as keys  # noqa: PLC0415
    keys(case.path, channels={"messaging": "desk"}, messaging={"senders": {"telegram": [{"id": IDENT, "policy": "desk"}]}})
    out = case.hold(PNG, name="holiday.png", declared="image/png", direct=True)
    assert "added" not in out and case.rows()[0]["status"] == "held"


def test_an_image_whose_bytes_are_not_what_it_says_is_refused_and_counted(case):  # noqa: F811
    with pytest.raises(ops.OpsError, match="says it is a image/png and its bytes are a"):
        case.hold(JPEG, name="holiday.png", declared="image/png")
    with pytest.raises(ops.OpsError, match="says it is a image/jpeg and its bytes are a PDF"):
        case.hold(PDF, name="holiday.jpg", declared="image/jpeg")
    with pytest.raises(ops.OpsError, match="says it is a photo and its bytes are a"):
        case.hold(PNG, name="x", declared="photo")
    assert [(r["status"], r["code"]) for r in case.rows()] == [("refused", "mismatch")] * 3 and ops.attachments(case.path)["today"]["files"] == 3
    assert not (case.data / "attachments" / "held").exists()


def test_an_image_type_that_is_not_taken_is_refused_before_and_after_the_fetch(case):  # noqa: F811
    with pytest.raises(ops.OpsError, match="Voice notes, videos, audio and stickers are not taken"):
        case.hold(JPEG, name="x.svg", declared="image/svg+xml")
    with pytest.raises(ops.OpsError, match="was not added and was deleted"):
        case.hold(AVIF, name="x.avif", declared=None)
    assert [r["code"] for r in case.rows()] == ["media", "type"]


def test_an_image_is_never_a_source_the_add_says_so_and_the_file_stays_held(case):  # noqa: F811
    case.hold(PNG, name="holiday.png", declared="image/png")
    with pytest.raises(ops.OpsError) as refused:
        ops.attachment_add(case.path, 1, channel="messaging", sender=f"telegram:{IDENT}")
    assert str(refused.value) == "Images are not added to the project; I can save them to Drive or OneDrive."
    with pytest.raises(ops.OpsError) as terminal:
        ops.attachment_add(case.path, 1)
    assert str(terminal.value) == str(refused.value)
    assert case.rows()[0]["status"] == "held" and attachments.read_held(str(case.data), 1) == PNG
    for channel in ("mcp", "page"):
        assert "mcp" not in operations.by_name("attachment-add")["channels"] or channel != "mcp"
    assert "mcp" not in operations.by_name("attachment-hold")["channels"] and "mcp" not in operations.by_name("file-save")["channels"]
    assert ops.attachment_discard(case.path, 1)["discarded"] is True and case.rows()[0]["status"] == "discarded"


def test_the_size_cap_and_the_day_and_held_limits_apply_to_images(case, monkeypatch):  # noqa: F811
    with pytest.raises(ops.OpsError, match="a file from this app is at most"):
        case.hold(PNG, name="big.png", declared="image/png", declared_bytes=30 * 1024 * 1024)
    monkeypatch.setattr(attachments, "HELD_MAX", 1)
    case.hold(PNG, name="a.png", declared="image/png")
    with pytest.raises(ops.OpsError, match="wait for your answer already"):
        case.hold(JPEG, name="b.jpg", declared="image/jpeg")


# --- the save writes the held bytes with the media type of the image ----------------------------------------------------------------------------


@pytest.mark.parametrize("data, kind, name, mime", [(JPEG, "jpeg", "photo-2026-10-20-101500.jpg", "image/jpeg"), (PNG, "png", "scan.png", "image/png"),
                                                    (HEIC, "heic", "IMG_1.heic", "image/heic"), (GIF, "gif", "loop.gif", "image/gif"), (WEBP, "webp", "pic.webp", "image/webp")])
def test_a_save_of_an_image_writes_the_exact_bytes_with_its_media_type_after_the_approval(files_world, data, kind, name, mime):  # noqa: F811
    from test_files_write import approve, effect_doc, item_of  # noqa: PLC0415
    number = hold_row(files_world, data=data, name=name, kind=kind)
    started = ops.file_save(files_world["path"], "google", number)
    doc = effect_doc(files_world, started)
    assert doc["name"] == name and doc["content"]["media_type"] == mime and doc["content"]["kind"] == "held"
    assert [m for m in files_world["gd"].files.values() if m["name"] == name] == [], "the card writes nothing"
    assert f"Saves the file you sent: {name}" in item_of(files_world, started)["body"]
    approve(files_world, started)
    saved = [m for m in files_world["gd"].files.values() if m["name"] == name]
    assert len(saved) == 1 and saved[0]["content"] == data and saved[0]["mimeType"] == mime
    again = ops.file_save(files_world["path"], "microsoft", number)
    approve(files_world, again)
    [item] = [i for i in files_world["ms"].items.values() if i["name"] == name]
    assert item["content"] == data


def test_an_image_is_saved_only_as_the_image_its_bytes_are_and_never_made_or_replaced(files_world):  # noqa: F811
    number = hold_row(files_world, data=PNG, name="scan.png", kind="png")
    for wrong in ("scan.jpg", "scan.pdf", "scan.md"):
        with pytest.raises(ops.OpsError):
            ops.file_save(files_world["path"], "google", number, file_name=wrong)
    with pytest.raises(ops.OpsError):
        ops.file_save(files_world["path"], "google", number, file_name="scan.exe")
    for extension in ("png", "jpg", "heic"):          # a create is text or a Word file; it never takes an image type
        with pytest.raises(ops.OpsError):
            ops.file_create(files_world["path"], "google", f"x.{extension}", content="text")
    document = {"effect": "files", "operation": "create"}
    assert set(files_document.IMAGE_TYPES.values()) <= set(files_document.SAVE_TYPES.values()) and "png" not in files_document.CREATE_EXTENSIONS and document


def test_the_writers_and_the_runtime_agree_on_the_images():
    import importlib.util  # noqa: PLC0415
    path = st.REPO / "providers" / "writer" / "_files_common.py"
    spec = importlib.util.spec_from_file_location("w_att3_common", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.IMAGE_TYPES == files_document.IMAGE_TYPES
    for media in files_document.IMAGE_TYPES.values():
        assert module.check_media_type(media, images=True) == media
        with pytest.raises(module.WriterError):
            module.check_media_type(media)          # the verbs that change a file already there (update, replace) never take an image
    with pytest.raises(module.WriterError):
        module.check_media_type("image/svg+xml", images=True)
    for verb in ("cmd_update", "cmd_replace"):
        for name in ("gdrive", "onedrive"):
            source = (st.REPO / "providers" / "writer" / f"{name}.py").read_text(encoding="utf-8")
            if f"def {verb}(" in source:
                body = source.split(f"def {verb}(", 1)[1].split("\ndef ", 1)[0]
                assert "check_media_type(a.media_type)" in body and "images=True" not in body, (name, verb)


# --- the loose caption and the closed lines ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line, account", [
    ("Salva no drive", "google"), ("Salvar no drive", "google"), ("salve no onedrive", "microsoft"), ("guarda no drive", "google"), ("sobe pro drive", "google"),
    ("save to drive", "google"), ("save it to my drive", "google"), ("salva esse pdf no drive", "google"), ("salva isso no drive", "google"),
    ("salva esse arquivo no Google Drive", "google"), ("manda pro onedrive", "microsoft"), ("coloca no drive", "google"), ("save this to OneDrive", "microsoft")])
def test_a_line_that_saves_the_file_just_sent_is_a_save_form_with_its_service(line, account):
    found = natural_writes.read(line)
    assert found is not None and found["op"] == "file-save" and found["slots"].get("account") == account, line
    assert natural_writes.candidate(line) == {"family": "files", "op": "file-save"}


@pytest.mark.parametrize("line", ["Salvar", "pode salvar", "salva", "salva isso", "save", "save it", "keep it", "drop it", "save this"])
def test_a_save_word_alone_is_no_save_form_by_itself_and_is_a_line_about_the_last_file(line):
    assert natural_writes.read(line) is None or natural_writes.read(line)["op"] != "file-save", line          # the pure reader never claims it
    assert natural_writes.file_line(line) in ("save", None) and natural_writes.file_line(line) != "discard"
    assert natural_writes.file_line(line) == ("save" if line != "drop it" else None), line


@pytest.mark.parametrize("line", ["salva essa foto", "salva esse arquivo", "salva o anexo 1"])
def test_a_save_that_names_the_file_by_a_noun_or_a_number_is_a_save_form(line):
    found = natural_writes.read(line)
    assert found is not None and found["op"] == "file-save" and "account" not in found["slots"], line


@pytest.mark.parametrize("line", ["salva a vida do gato", "manda email pro joao", "guarda a data", "salva o arquivo", "send the report to Dana", "sobe o preço"])
def test_a_line_that_is_not_about_the_file_just_sent_is_not_taken(line):
    assert natural_writes.read(line) is None or natural_writes.read(line)["op"] != "file-save", line


@pytest.mark.parametrize("text, mode, account", [
    ("Salva no drive", "save", "google"), ("drive", "save", "google"), ("onedrive", "save", "microsoft"), ("nuvem do google", "save", "google"),
    ("salva isso aí", "save", None), ("save it", "save", None), ("upload to my gdrive", "save", "google"), ("manda pro one drive", "save", "microsoft"),
    ("adiciona ao projeto", "card", None), ("vira fonte", "card", None), ("salva no drive e no onedrive", "save", None), ("olha que legal", "card", None)])
def test_the_caption_only_preselects_and_by_closed_word_lists(text, mode, account):
    found = natural_writes.caption_files(text)
    assert (found["mode"], found["account"]) == (mode, account), text


@pytest.mark.parametrize("text, word", [("descarta", "discard"), ("pode descartar", "discard"), ("descarta esse arquivo", "discard"), ("discard it", "discard"),
                                        ("adiciona ao projeto", "add"), ("vira fonte", "add"), ("add to the project", "add"), ("pode adicionar", "add"),
                                        ("descarta o lembrete de amanhã", None), ("adiciona leite à lista de compras", None), ("/discard 3", None)])
def test_a_line_about_the_file_just_sent_is_a_closed_phrase_whole(text, word):
    assert natural_writes.file_line(text) == word, text


# --- through the bridge: one card, the caption preselects ------------------------------------------------------------------------------------


def test_a_photo_with_the_caption_save_to_drive_is_held_and_opens_the_save_card_and_no_other_card(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")], text="Salva no drive")
    assert len(case.rows()) == 1, (w.texts(), w.log)
    [row] = case.rows()
    assert (row["status"], row["kind"], row["declared_type"], row["target"], row["label"]) == ("held", "jpeg", "image/jpeg", None, None)
    assert row["name"].startswith("photo-") and row["name"].endswith(".jpg")
    assert w.seen == [("file-save", {"account": "google", "attachment": 1}, "messaging", f"telegram:{IDENT}")], (w.texts(), w.log)
    assert w.save_cards == [9], "the card of the save was sent, once"
    assert cards_sent(w) == [] and w.bridge.ledger.attachment_card(w.project["id"], 1, IDENT) is None, "no second card for the same file"
    assert attachments.read_held(str(case.data), 1) == JPEG
    teardown(w)


def test_a_png_document_with_the_caption_names_the_service_it_goes_to(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("d1", PNG)
    w.send([w.file("d1", "Holiday scan.png", len(PNG), "image/png")], text="salva no onedrive")
    assert w.seen == [("file-save", {"account": "microsoft", "attachment": 1}, "messaging", f"telegram:{IDENT}")] and case.rows()[0]["name"] == "Holiday scan.png"
    assert cards_sent(w) == []
    teardown(w)


def test_a_pdf_with_the_caption_salva_no_drive_opens_the_save_card_and_not_the_add_card(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))], text="Salva no drive")
    assert [s[1] for s in w.seen] == [{"account": "google", "attachment": 1}] and cards_sent(w) == []
    assert "não é lido" not in " ".join(w.texts()), "the old sentence is gone"
    teardown(w)


def test_a_save_word_with_no_service_goes_to_the_one_account(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch, accounts={"google": ACCOUNTS["google"]})
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))], text="salva isso aí")
    assert [s[1] for s in w.seen] == [{"account": "google", "attachment": 1}] and cards_sent(w) == []
    teardown(w)


def test_a_save_word_with_no_service_and_two_accounts_gets_the_one_card_and_no_numbered_question(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r2", make_pdf("Another"))
    w.send([w.file("r2", "Another.pdf")], text="salva isso aí")
    assert w.seen == [] and len(cards_sent(w)) == 1
    assert "Em qual conta" not in " ".join(w.texts())
    teardown(w)


def test_when_the_save_card_cannot_open_the_files_card_is_sent_so_that_nothing_is_left_without_one(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    monkeypatch.setattr(w.bridge, "resend", lambda project, chat, pending: False)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))], text="salva no drive")
    assert len(cards_sent(w)) == 1 and "Recebi Q3 plan.pdf" in cards_sent(w)[0]["message"]["text"]
    teardown(w)


def test_a_caption_that_asks_to_add_to_the_project_or_names_a_source_gets_the_card(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))], text="adiciona ao projeto")
    assert w.seen == [] and len(cards_sent(w)) == 1 and "lido só como um pedido para salvar" not in w.texts()[-1]
    w.reset()
    w.put("r2", make_pdf("Second"))
    w.send([w.file("r2", "Second.pdf")], text="olha que legal")
    assert w.seen == [] and "lido só como um pedido para salvar" in w.texts()[-1], "a caption that asks nothing is said to be read only for saving"
    teardown(w)


def test_a_caption_that_names_a_kind_the_file_is_not_preselects_nothing(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", "pic.jpg", len(JPEG), "image/jpeg")], text="salva esse pdf no drive")
    assert w.seen == [] and len(cards_sent(w)) == 1
    teardown(w)


# --- the one card ---------------------------------------------------------------------------------------------------------------------------


def test_an_image_gets_one_card_that_saves_to_each_account_and_discards_and_never_adds(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    [card] = cards_sent(w)
    assert labels(w) == ["Salvar no Google Drive", "Salvar no OneDrive", "Descartar"]
    text = card["message"]["text"]
    assert "Recebi photo-" in text and "JPEG). O que faço?" in text and "Adicionar ao projeto" not in text and "fonte" not in text
    assert w.seen == [] and len(w.sent()) == 1, "one message for the file"
    teardown(w)


def test_a_pdf_gets_one_card_with_both_saves_add_to_the_project_and_discard(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    assert labels(w) == ["Salvar no Google Drive", "Salvar no OneDrive", "Adicionar ao projeto", "Descartar"]
    text = w.sent()[-1]["message"]["text"]
    assert "Recebi Q3 plan.pdf" in text and "documento que o assistente pode ler" in text and "Google" not in text.split("\n", 2)[2] and "@" not in text
    teardown(w)


def test_the_card_in_english_says_the_same(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch, language="en")
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    assert labels(w) == ["Save to Google Drive", "Save to OneDrive", "Add to project", "Discard"]
    assert "I received Q3 plan.pdf" in w.sent()[-1]["message"]["text"] and "What should I do?" in w.sent()[-1]["message"]["text"]
    teardown(w)


def test_a_sender_without_files_write_sees_no_save_and_the_files_group_alone_does_not_let_a_file_in(case, monkeypatch):  # noqa: F811
    senders = [{"id": IDENT, "policy": "staff"}, {"id": OTHER, "policy": "saver"}]
    w = setup(case, monkeypatch, senders=senders)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    assert labels(w) == ["Adicionar ao projeto", "Descartar"]
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))], text="salva no drive")
    assert w.seen == [], "a caption cannot open a save the profile does not permit"
    w.reset()
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))], sender=OTHER)
    assert w.fetches() == [] and "Arquivos não são recebidos por este aplicativo" in w.texts()[0], "files come in through add-sources (the group of the hold), as they always did"
    teardown(w)


def test_a_sender_with_neither_group_gets_the_refusal_and_nothing_is_fetched(case, monkeypatch):  # noqa: F811
    senders = [{"id": IDENT, "policy": "owner"}, {"id": OTHER, "policy": "reader"}]
    w = setup(case, monkeypatch, senders=senders, profiles=dict(PROFILES, reader=["read"]))
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")], sender=OTHER)
    assert w.fetches() == [] and w.texts() == [phrases.text("ATT_OFF", {"language": "pt-BR"})]
    teardown(w)


def test_a_project_that_lists_one_account_draws_one_save_button(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch, accounts={"microsoft": ACCOUNTS["microsoft"]})
    w.put("p1", PNG)
    w.send([w.file("p1", "scan.png", len(PNG), "image/png")])
    assert labels(w) == ["Salvar no OneDrive", "Descartar"]
    teardown(w)


def test_a_platform_with_no_buttons_gets_the_words_that_save_and_the_typed_add_and_discard(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch, language="en")
    w.bridge.messenger.capabilities = lambda: {"attachments": True, "max_attachment_bytes": 10 ** 7, "buttons": False, "max_buttons": 0, "max_text": 4096}
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    text = w.texts()[-1]
    assert 'write "save to Google Drive"' in text and 'write "save to OneDrive"' in text and "Send /add 1" in text and "Send /discard 1" in text
    teardown(w)


# --- the buttons ----------------------------------------------------------------------------------------------------------------------------


def test_the_save_button_opens_the_save_card_of_that_file_and_the_sender_alone_can_use_it(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    chosen = action(w, "save-microsoft")
    w.say(action=chosen, sender=OTHER)
    assert w.seen == [], "another sender's tap is refused"
    w.say(action=chosen)
    assert w.seen == [("file-save", {"account": "microsoft", "attachment": 1}, "messaging", f"telegram:{IDENT}")], (w.texts(), w.log)
    assert case.rows()[0]["status"] == "held"
    teardown(w)


def test_a_tap_checks_the_senders_profile_again_and_the_file_as_it_is_now(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    chosen, discard = action(w, "save-google"), action(w, "discard")
    accept(case.path, policies=dict(PROFILES, owner=["read", "add-sources"]))
    w.say(action=chosen)
    assert w.seen == [] and w.texts()[-1] == "Salvar arquivos no Drive ou no OneDrive não está ligado para você neste projeto."
    accept(case.path, policies=PROFILES)
    w.say(action=discard)
    assert case.rows()[0]["status"] == "discarded"
    w.say(action=chosen)
    assert w.seen == [] and "arquivo" in w.texts()[-1].lower()
    teardown(w)


def test_the_add_and_discard_buttons_work_for_a_pdf_and_the_add_is_not_offered_for_an_image(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    w.say(action=action(w, "add"))
    assert w.texts()[-1].startswith("Adicionei Q3 plan.pdf") or "q3-plan" in w.texts()[-1]
    w.put("p1", PNG)
    w.send([w.file("p1", "pic.png", len(PNG), "image/png")])
    assert not any(a["id"].endswith(":add") for a in w.sent()[-1]["message"]["actions"])
    w.say("/add 2")
    assert w.texts()[-1] == "Imagens não viram fonte; posso salvar no Drive ou no OneDrive."
    assert case.rows()[1]["status"] == "held"
    teardown(w)


# --- a later line about the last file --------------------------------------------------------------------------------------------------------


def test_a_pdf_without_a_caption_is_saved_by_the_line_salvar_no_drive_sent_after(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    assert w.seen == []
    w.say("Salvar no drive")
    assert [s[1] for s in w.seen] == [{"account": "google", "attachment": 1}] and w.save_cards == [9]
    w.say("manda pro onedrive")
    assert w.seen[-1][1] == {"account": "microsoft", "attachment": 1}
    teardown(w)


def test_a_save_line_with_no_service_and_both_accounts_brings_the_files_card_back(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    w.say("pode salvar")
    assert w.seen == [] and w.texts()[-2] == phrases.text("NW_PICK_ON_CARD", {"language": "pt-BR"}) and len(cards_sent(w)) == 2
    assert labels(w) == ["Salvar no Google Drive", "Salvar no OneDrive", "Adicionar ao projeto", "Descartar"]
    teardown(w)


def test_with_one_account_the_line_pode_salvar_opens_that_save(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch, accounts={"microsoft": ACCOUNTS["microsoft"]})
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    w.say("pode salvar")
    assert w.seen[-1][1] == {"account": "microsoft", "attachment": 1}
    teardown(w)


def test_with_two_held_files_the_line_asks_which_by_their_cards_and_with_none_it_says_so(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.say("Salvar no drive")
    assert w.texts()[-1] == "Não tenho nenhum arquivo seu aguardando. Envie o arquivo e diga onde salvar." and w.seen == []
    w.put("r1", PDF)
    w.put("p1", JPEG)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    w.send([w.file("p1", None, len(JPEG), "photo")])
    w.say("Salvar no drive")
    assert w.seen == [] and phrases.text("NW_WHICH_FILE", {"language": "pt-BR"}) in w.texts()
    assert "Q3 plan.pdf" in w.sent()[-2]["message"]["text"] and "photo-" in w.sent()[-1]["message"]["text"], "each file by its name, with its own buttons"
    teardown(w)


def test_the_line_descarta_discards_the_last_file_and_adiciona_ao_projeto_adds_it(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    w.say("descarta")
    assert case.rows()[0]["status"] == "discarded" and not (case.data / "attachments" / "held" / "1").exists()
    w.put("r2", make_pdf("Second"))
    w.send([w.file("r2", "Second.pdf")])
    w.say("adiciona ao projeto")
    assert case.rows()[1]["status"] == "added"
    w.say("descarta")
    assert "descarta" not in " ".join(w.texts()[-1:]) and case.rows()[1]["status"] == "added", "no file waits: the line is an ordinary line"
    teardown(w)


def test_a_line_about_a_file_never_reaches_the_router_and_a_file_of_another_sender_is_never_named(case, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ops, "say", lambda *a, **k: (_ for _ in ()).throw(AssertionError("not routed")))
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    w.say("descarta", sender=OTHER)
    assert case.rows()[0]["status"] == "held"
    w.say("Salvar no drive", sender=OTHER)
    assert w.seen == []
    w.say("Salvar no drive")
    assert len(w.seen) == 1
    teardown(w)


# --- what is still refused ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["voice", "video", "audio", "sticker", "video/mp4", "audio/ogg"])
def test_a_voice_note_a_video_audio_and_a_sticker_are_still_refused_with_the_corrected_sentence(case, monkeypatch, kind):  # noqa: F811
    w = setup(case, monkeypatch)
    w.send([w.file("v1", "talk", 5000, kind)])
    assert w.texts() == [phrases.text("ATT_MEDIA", {"language": "pt-BR"})] and w.fetches() == [] and case.rows() == []
    assert "Notas de voz, vídeos, áudios e figurinhas ainda não são aceitos" in w.texts()[0] and "salvar no Drive ou no OneDrive" in w.texts()[0]
    teardown(w)


def test_an_image_that_is_too_large_or_whose_bytes_are_not_the_declared_type_is_refused(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.send([w.file("big", "big.png", 30 * 1024 * 1024, "image/png")])
    assert "big.png" in w.texts()[0] and w.fetches() == []
    w.put("liar", JPEG)
    w.send([w.file("liar", "liar.png", len(JPEG), "image/png")])
    assert case.rows()[-1]["code"] == "mismatch" and "liar.png" in w.texts()[-1]
    assert not (case.data / "attachments" / "held").exists()
    teardown(w)


def test_the_day_and_held_limits_hold_for_images_from_a_phone(case, monkeypatch):  # noqa: F811
    monkeypatch.setattr(attachments, "HELD_MAX", 1)
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.put("p2", PNG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    w.send([w.file("p2", "two.png", len(PNG), "image/png")])
    assert "já esperam pela sua resposta" in w.texts()[-1]
    assert len(case.rows("held")) == 1
    teardown(w)


# --- privacy -------------------------------------------------------------------------------------------------------------------------------


def test_the_name_of_a_file_and_the_save_line_are_not_in_the_conversation_the_mcp_mode_reads(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.put("d1", PNG)
    w.send([w.file("p1", None, len(JPEG), "photo")], text="Salva no drive")
    w.send([w.file("d1", "Passport scan.png", len(PNG), "image/png")])
    w.say("Salvar no onedrive")
    ctx = ops_core.context(case.path)
    stored = json.dumps(ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500))
    assert stored == "[]" and "Passport" not in stored and "photo-" not in stored
    assert "Passport" not in " ".join(w.log)
    teardown(w)


def test_an_image_is_never_given_to_a_model_a_converter_or_the_sources_folder(case, monkeypatch):  # noqa: F811
    called = []
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: called.append(cfg) or (lambda *a, **k: called.append(a)))
    monkeypatch.setattr(ops, "say", lambda *a, **k: called.append("say"))
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")], text="Salva no drive")
    w.say("/add 1")
    assert called == [] and sources.list_catalog(case.ctx, hashes=False) == []
    assert hashlib.sha256(attachments.read_held(str(case.data), 1)).hexdigest() == case.rows()[0]["sha256"]
    teardown(w)


def test_the_hold_is_the_add_sources_groups_alone_and_the_runtime_and_the_hold_agree_on_the_heic_brands():
    assert "attachment-hold" in operations.GROUPS["add-sources"]["operations"] and "attachment-hold" not in operations.GROUPS["files-write"]["operations"]
    assert "files-write" not in operations.DEFAULT_POLICY["messaging"]
    assert step_files.HELD_KINDS["png"] == ("png",) and step_files.HELD_KINDS["jpg"] == ("jpeg",) and step_files.HEIC_BRANDS == attachments.HEIC_BRANDS
    assert set(step_files.HELD_KINDS["heic"]) == set(attachments.IMAGE_TYPES["image/heic"])


# --- the review of #489 ---------------------------------------------------------------------------------------------------------------------


def later(monkeypatch, **delta):
    """The clock of the hold moved on (a file held a while ago)."""
    import datetime  # noqa: PLC0415
    real = attachments.utcnow
    monkeypatch.setattr(attachments, "utcnow", lambda: real() + datetime.timedelta(**delta))


def routed(monkeypatch):
    called = []
    monkeypatch.setattr(ops, "say", lambda *a, **k: called.append(a) or {"reply": "routed", "request_id": None, "pending_id": None})
    return called


def test_the_photos_of_an_album_get_names_of_their_own(case, monkeypatch):  # noqa: F811
    first = attachments.photo_name(None, "ref-one")
    assert first != attachments.photo_name(None, "ref-two") and first.endswith(".jpg")
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.put("p2", JPEG + b"x")
    w.send([w.file("p1", None, len(JPEG), "photo"), w.file("p2", None, len(JPEG) + 1, "photo")])
    names = [r["name"] for r in case.rows()]
    assert len(names) == 2 and len(set(names)) == 2
    teardown(w)


def test_a_taken_name_of_a_file_that_was_sent_gets_a_number_and_a_name_the_person_chose_is_never_changed(files_world):  # noqa: F811
    from test_files_write import approve, effect_doc  # noqa: PLC0415
    one = hold_row(files_world, data=JPEG, name="photo.jpg", kind="jpeg")
    two = hold_row(files_world, data=JPEG + b"2", name="photo.jpg", kind="jpeg", sender="4243")
    three = hold_row(files_world, data=JPEG + b"3", name="photo.jpg", kind="jpeg", sender="4244")
    approve(files_world, ops.file_save(files_world["path"], "google", one))
    second = ops.file_save(files_world["path"], "google", two)
    assert effect_doc(files_world, second)["name"] == "photo (2).jpg"
    approve(files_world, second)
    assert effect_doc(files_world, ops.file_save(files_world["path"], "google", three))["name"] == "photo (3).jpg"
    with pytest.raises(ops.OpsError, match="name_taken"):
        ops.file_save(files_world["path"], "google", three, file_name="photo.jpg")


def test_a_name_a_sender_gave_is_made_one_the_platform_writes_and_cut_cleanly(files_world):  # noqa: F811
    from test_files_write import effect_doc  # noqa: PLC0415
    for raw in ("Invoice #3, final@home.pdf", "x" * 300 + ".pdf", "..hidden.png", "-dash.png", "tab\tname.jpg"):
        safe = files_document.safe_name(raw)
        assert files_document.name_problem(safe, files_document.SAVE_EXTENSIONS) == "", (raw, safe)
        assert safe.rsplit(".", 1)[-1] == raw.rsplit(".", 1)[-1] and len(safe) <= files_document.NAME_MAX
    assert files_document.safe_name("Plan.pdf") == "Plan.pdf" and files_document.numbered("Plan.pdf", 2) == "Plan (2).pdf"
    assert len(files_document.numbered("x" * 120 + ".pdf", 10)) <= files_document.NAME_MAX
    number = hold_row(files_world, data=PNG, name="Passport scan #1, front.png", kind="png")
    assert effect_doc(files_world, ops.file_save(files_world["path"], "google", number))["name"] == "Passport scan _1_ front.png"
    assert attachments.clean_name("x" * 300 + ".pdf").endswith(".pdf") and "…" not in attachments.clean_name("e" * 300)


@pytest.mark.parametrize("name, sniffed, expected", [(".png", "png", "image.png"), ("a.png.", "png", "a.png"), ("a.png", "jpeg", "a.jpg"), ("...", "gif", "image.gif"),
                                                     ("pic", "webp", "pic.webp"), ("IMG.JPG", "jpeg", "IMG.JPG")])
def test_an_image_name_never_gets_a_double_extension_or_a_trailing_dot(name, sniffed, expected):
    assert attachments.image_name(name, sniffed) == expected


def test_image_jpg_is_the_jpeg_it_means(case):  # noqa: F811
    out = case.hold(JPEG, name="pic.jpg", declared="image/jpg")
    assert out["attachment"]["kind"] == "jpeg" and attachments.is_save_only_type("image/jpg") and attachments.mismatch("image/jpg", "png") is True


def test_a_save_caption_is_never_the_grant_that_adds_the_file_as_a_source(case, monkeypatch):  # noqa: F811
    profiles = dict(PROFILES, desk=["read", "add-sources-direct", "files-write"])
    w = setup(case, monkeypatch, senders=[{"id": IDENT, "policy": "desk"}], profiles=profiles)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))], text="salva no drive")
    assert [s[1] for s in w.seen] == [{"account": "google", "attachment": 1}] and case.rows()[0]["status"] == "held"
    assert sources.list_catalog(case.ctx, hashes=False) == []
    w.put("r2", make_pdf("Second"))
    w.send([w.file("r2", "Second.pdf")])
    assert case.rows()[1]["status"] == "added", "a file that asked for no save is still added at once by the grant"
    teardown(w)


@pytest.mark.parametrize("line", ["não quero", "nao quero", "never mind", "delete it", "apaga isso"])
def test_a_loose_line_never_discards_a_held_file(case, monkeypatch, line):  # noqa: F811
    called = routed(monkeypatch)
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    w.say(line)
    assert case.rows()[0]["status"] == "held" and len(called) == 1, ("the line is an ordinary line", w.texts(), w.log)
    teardown(w)


def test_a_line_about_the_file_reaches_only_a_file_held_for_less_than_an_hour_whose_card_is_in_the_chat(case, monkeypatch):  # noqa: F811
    called = routed(monkeypatch)
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    later(monkeypatch, hours=2)
    for line in ("descarta", "descarta o arquivo", "salvar", "adiciona ao projeto"):
        w.say(line)
    assert case.rows()[0]["status"] == "held" and len(called) == 4 and w.seen == [], "two hours later every one of them is an ordinary line"
    teardown(w)


def test_a_file_saved_by_its_caption_has_no_card_and_a_discard_line_leaves_it(case, monkeypatch):  # noqa: F811
    called = routed(monkeypatch)
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")], text="salva no drive")
    w.say("descarta")
    assert case.rows()[0]["status"] == "held" and len(called) == 1
    teardown(w)


def test_the_discard_line_works_within_the_hour(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    later(monkeypatch, minutes=30)
    w.say("descarta")
    assert case.rows()[0]["status"] == "discarded"
    teardown(w)


def test_the_bare_forms_act_on_a_recent_file_and_are_ordinary_lines_without_one(case, monkeypatch):  # noqa: F811
    called = routed(monkeypatch)
    w = setup(case, monkeypatch, language="en")
    for line in ("keep it", "drop it", "save it", "save"):
        w.say(line)
    assert len(called) == 4 and w.seen == []
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    w.say("drop it")
    assert len(called) == 5 and w.seen == [], "drop it saves nothing"
    w.say("save it")
    assert w.seen == [] and w.texts()[-2] == phrases.text("NW_PICK_ON_CARD", {"language": "en"}) and "I received photo-" in w.texts()[-1], "both services: the card again"
    teardown(w)


def test_a_bare_save_line_with_one_account_opens_that_save(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch, accounts={"google": ACCOUNTS["google"]})
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    w.say("salvar")
    assert [s[1]["account"] for s in w.seen] == ["google"]
    teardown(w)


def test_a_sender_without_files_write_gets_a_plain_refusal_for_every_way_to_ask_a_save(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch, senders=[{"id": IDENT, "policy": "staff"}])
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    w.say("Salvar no drive")
    refusal = phrases.text("ATT_SAVE_OFF", {"language": "pt-BR"})
    assert w.texts()[-1] == refusal and w.seen == []
    for text in w.texts():
        assert "/file-save" not in text and "error:" not in text
    teardown(w)


@pytest.mark.parametrize("language, caption, account", [("pt-BR", "adiciona no drive", "google"), ("pt-BR", "adicionar no onedrive", "microsoft"),
                                                        ("en", "add to drive", "google"), ("en", "add it to my onedrive", "microsoft")])
def test_a_service_named_beats_the_word_add(case, monkeypatch, language, caption, account):  # noqa: F811
    w = setup(case, monkeypatch, language=language)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))], text=caption)
    assert len(w.seen) == 1 and w.seen[0][1]["account"] == account and case.rows()[0]["status"] == "held"
    teardown(w)


def test_a_caption_that_names_a_service_the_project_does_not_list_is_one_message_the_files_card_with_a_line(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch, accounts={"google": ACCOUNTS["google"]})
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")], text="salva no onedrive")
    assert len(w.sent()) == 1 and w.seen == []
    text = w.texts()[0]
    assert "Recebi photo-" in text and "O OneDrive não está configurado neste projeto." in text and "error" not in text and "/file" not in text
    assert labels(w) == ["Salvar no Google Drive", "Descartar"]
    teardown(w)


def test_a_tap_on_a_save_for_an_account_removed_since_is_the_files_card_with_a_line(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    chosen = action(w, "save-microsoft")
    accept(case.path, accounts={"google": ACCOUNTS["google"]})
    w.reset()
    w.say(action=chosen)
    assert w.seen == [] and len(w.sent()) == 1 and "O OneDrive não está configurado neste projeto." in w.texts()[0] and labels(w) == ["Salvar no Google Drive", "Descartar"]
    teardown(w)


def test_a_folder_list_with_no_default_never_opens_a_question_from_a_caption_and_a_button_takes_the_first_folder(case, monkeypatch):  # noqa: F811
    accounts = {"google": {"address": "pat@example.com", "folders": {"fotos": "FolderId0001", "docs": "FolderId0002"}}}
    w = setup(case, monkeypatch, accounts=accounts)
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")], text="salva no drive")
    assert len(w.sent()) == 1 and w.seen == [] and "Recebi photo-" in w.texts()[0], "the file's card, one message, no question about the folder"
    w.say(action=action(w, "save-google"))
    assert [s[1] for s in w.seen] == [{"account": "google", "attachment": 1, "folder": "fotos"}], "the first folder the project lists; the card of the save names it"
    teardown(w)


def test_a_second_tap_on_save_sends_the_open_card_again_and_opens_nothing(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    monkeypatch.setattr(ops, "pending", lambda path, pending_id=None, **k: {"status": "open", "id": pending_id})
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    chosen = action(w, "save-google")
    w.say(action=chosen)
    w.say(action=chosen)
    assert len(w.seen) == 1 and w.save_cards == [9, 9], "the same card twice, one task"
    teardown(w)


def test_the_save_job_is_labelled_for_what_it_is(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    labelled = []
    real = w.bridge.start
    monkeypatch.setattr(w.bridge, "start", lambda project, chat, op, call: (labelled.append(op), real(project, chat, op, call))[1])
    w.put("p1", JPEG)
    w.send([w.file("p1", None, len(JPEG), "photo")])
    w.say(action=action(w, "save-google"))
    assert "file-save" in labelled and "event-create" not in labelled
    teardown(w)


def test_a_card_sent_again_keeps_the_version_it_would_make(case, monkeypatch):  # noqa: F811
    w = setup(case, monkeypatch)
    w.put("r1", PDF)
    w.send([w.file("r1", "Q3 plan.pdf", len(PDF))])
    w.say(action=action(w, "add"))
    w.put("r2", make_pdf("The Q3 plan, revised"))
    w.send([w.file("r2", "Plan v2.pdf")], text="@q3-plan")
    assert "versão 2" in w.texts()[-1]
    w.say("pode salvar")
    assert "versão 2 do documento `q3-plan`" in w.texts()[-1], w.texts()[-1]
    teardown(w)
