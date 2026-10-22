"""Offline tests for the `file` entry of the neutral message in providers/messenger/telegram.py (slice S18): the Bot API is a fake opener (no network, no real token).

The bridge writes the bytes to one file of its own and hands the provider its path; the provider reads it (no link followed, a regular file, within the limit of its kind), sends the
message and then the file as a reply to it, and reports a file Telegram refused with `document_failed`. The oracle reads the requests the fake opener recorded: the method in the URL and
the multipart body, written here as literals. Each refusal has a vacuity case: the file that fits goes out.

Run: uv run --with pytest pytest providers/messenger/tests/test_telegram_send_file.py
"""
from __future__ import annotations

import json
import os
import urllib.error

import pytest

from test_telegram import TOKEN, Opener, message_file, run, telegram, token  # noqa: F401  (the fake Bot API of test_telegram.py)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32 + b"coral"
PDF = b"%PDF-1.7 a report about the choir budget"
TEXT = "Segunda: ensaio do coral.\n".encode("utf-8")


def staged(tmp_path, data, name="content"):
    path = tmp_path / name
    path.write_bytes(data)
    path.chmod(0o600)
    return str(path)


def send(monkeypatch, capsys, tmp_path, data, kind, name, *answers):
    opener = Opener(*(answers or ({"message_id": 31}, {"message_id": 32})))
    path = message_file(tmp_path, text="Here it is.", file={"name": name, "kind": kind, "path": staged(tmp_path, data)})
    code, out, err = run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "4242", "--message-file", path)
    return code, out, err, opener


def test_a_text_file_is_sent_as_a_document_after_the_message_as_a_reply_to_it(monkeypatch, capsys, tmp_path):
    code, out, err, opener = send(monkeypatch, capsys, tmp_path, TEXT, "document", "Atividades da semana.txt")
    assert code == 0 and json.loads(out) == {"message_id": "31"}
    assert [r[0].rsplit("/", 1)[1] for r in opener.requests] == ["sendMessage", "sendDocument"]
    _, body, headers, _ = opener.requests[1]
    assert headers["Content-type"].startswith("multipart/form-data")
    assert b'name="chat_id"\r\n\r\n4242' in body and b'name="reply_to_message_id"\r\n\r\n31' in body
    assert b'name="document"; filename="Atividades_da_semana.txt"' in body and b"Content-Type: text/plain" in body and TEXT in body
    assert TOKEN not in err


def test_an_image_is_sent_as_a_photo_under_its_own_field(monkeypatch, capsys, tmp_path):
    code, out, _, opener = send(monkeypatch, capsys, tmp_path, PNG, "photo", "Foto do coral.png")
    assert code == 0 and json.loads(out) == {"message_id": "31"}
    url, body, _, _ = opener.requests[1]
    assert url.endswith("/sendPhoto") and b'name="photo"; filename="Foto_do_coral.png"' in body and b"Content-Type: image/png" in body and PNG in body


def test_a_pdf_is_sent_as_a_document_with_its_type(monkeypatch, capsys, tmp_path):
    code, _, _, opener = send(monkeypatch, capsys, tmp_path, PDF, "document", "Relatorio.pdf")
    url, body, _, _ = opener.requests[1]
    assert code == 0 and url.endswith("/sendDocument") and b"Content-Type: application/pdf" in body and PDF in body


def test_vacuity_the_name_keeps_its_ending_when_it_is_long(monkeypatch, capsys, tmp_path):
    _, _, _, opener = send(monkeypatch, capsys, tmp_path, TEXT, "document", ("x" * 200) + ".txt")
    assert b'filename="' + b"x" * 50 + b'.txt"' in opener.requests[1][1]


def test_vacuity_a_png_goes_either_way(monkeypatch, capsys, tmp_path):
    """A png is a photo or a document: the refusals below are of the kind and the list, not of the bytes."""
    code, _, _, opener = send(monkeypatch, capsys, tmp_path, PNG, "document", "a.png")
    assert code == 0 and opener.requests[1][0].endswith("/sendDocument")


@pytest.mark.parametrize("data, kind", [
    (b"BM" + b"\x00" * 60, "document"),                     # a bitmap: not on the list of types
    (b"MZ\x90\x00" + b"\x00" * 60, "document"),             # a program
    (TEXT, "photo"),                                        # text is never a photo
    (b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 20, "photo"),      # a type the app does not show as a photo
    (b"", "document")])
def test_a_file_that_is_not_on_the_list_or_not_what_its_kind_says_is_refused_before_any_call(monkeypatch, capsys, tmp_path, data, kind):
    code, _, err, opener = send(monkeypatch, capsys, tmp_path, data, kind, "a.bin")
    assert code == 2 and opener.requests == [] and TOKEN not in err and str(tmp_path) not in err


def test_a_file_over_the_limit_of_its_kind_is_refused_before_any_call(monkeypatch, capsys, tmp_path):
    monkeypatch.setitem(telegram.CAPABILITIES, "max_photo_bytes", 40)
    code, _, _, opener = send(monkeypatch, capsys, tmp_path, PNG, "photo", "a.png")
    assert code == 2 and opener.requests == []
    monkeypatch.setitem(telegram.CAPABILITIES, "max_send_bytes", 10)
    code, _, _, opener = send(monkeypatch, capsys, tmp_path, TEXT, "document", "a.txt")
    assert code == 2 and opener.requests == []


def test_vacuity_the_same_files_under_the_real_limits_are_sent(monkeypatch, capsys, tmp_path):
    assert send(monkeypatch, capsys, tmp_path, PNG, "photo", "a.png")[0] == 0
    assert send(monkeypatch, capsys, tmp_path, TEXT, "document", "a.txt")[0] == 0


def test_a_path_that_is_a_link_or_a_folder_or_missing_is_refused_before_any_call(monkeypatch, capsys, tmp_path):
    real = staged(tmp_path, TEXT, "real")
    link = tmp_path / "link"
    link.symlink_to(real)
    for path in (str(link), str(tmp_path), str(tmp_path / "missing")):
        opener = Opener()
        message = message_file(tmp_path, text="Here it is.", file={"name": "a.txt", "kind": "document", "path": path})
        code, _, err = run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "4242", "--message-file", message)
        assert code == 2 and opener.requests == [] and str(tmp_path) not in err


def test_a_malformed_file_entry_or_a_document_beside_it_is_refused(monkeypatch, capsys, tmp_path):
    path = staged(tmp_path, TEXT)
    bad = [{"name": "", "kind": "document", "path": path}, {"name": "a", "kind": "video", "path": path}, {"name": "a", "kind": "document", "path": "relative/x"},
           {"name": "a", "kind": "document"}, "text"]
    for file in bad:
        opener = Opener()
        message = message_file(tmp_path, text="Here it is.", file=file)
        assert run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "4242", "--message-file", message)[0] == 2 and opener.requests == []
    opener = Opener()
    message = message_file(tmp_path, text="Here it is.", file={"name": "a", "kind": "document", "path": path}, document={"name": "b", "text": "c"})
    assert run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "4242", "--message-file", message)[0] == 2 and opener.requests == []


def test_a_file_telegram_refuses_after_the_message_went_out_prints_the_id_and_a_warning_with_no_name_path_or_token(monkeypatch, capsys, tmp_path):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    code, out, err, _ = send(monkeypatch, capsys, tmp_path, PNG, "photo", "Foto secreta.png", {"message_id": 31}, urllib.error.URLError(url))
    assert code == 0 and json.loads(out) == {"message_id": "31", "document_failed": True}
    assert "file was not" in err and TOKEN not in err and "secreta" not in err and str(tmp_path) not in err


def test_the_capabilities_declare_what_this_provider_sends():
    caps = telegram.CAPABILITIES
    assert (caps["send_files"], caps["max_send_bytes"], caps["max_photo_bytes"], caps["photo_types"]) == (True, 20971520, 10485760, ["png", "jpeg"])
    assert set(caps["photo_types"]) <= set(caps["send_types"]) and "text" in caps["send_types"] and "pdf" in caps["send_types"]
    assert caps["max_send_bytes"] <= 50 * 1024 * 1024, "below the documented Bot API limit for a document"


def test_the_bytes_are_in_no_output(monkeypatch, capsys, tmp_path):
    _, out, err, _ = send(monkeypatch, capsys, tmp_path, TEXT, "document", "a.txt")
    assert b"ensaio" not in (out + err).encode("utf-8") and os.path.exists(tmp_path / "content"), "the provider reads the file and never removes or prints it: the bridge owns it"
