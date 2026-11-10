"""Offline tests for the `video` kind of the `file` entry in providers/messenger/telegram.py (package V1d-2, decision 14): the preview of a delivery is sent as a video
by sendVideo. The Bot API is the fake opener of test_telegram.py (no network, no real token); the MP4 is a synthetic header.

Run: uv run --with pytest pytest providers/messenger/tests/test_telegram_video.py
"""
from __future__ import annotations

import json

import pytest

from test_telegram import TOKEN, Opener, message_file, run, telegram, token  # noqa: F401  (the fake Bot API of test_telegram.py)

MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(64)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32 + b"coral"


def staged(tmp_path, data, name="content"):
    path = tmp_path / name
    path.write_bytes(data)
    path.chmod(0o600)
    return str(path)


def send_video(monkeypatch, capsys, tmp_path, data=MP4, path=None, *answers):
    opener = Opener(*(answers or ({"message_id": 31}, {"message_id": 32})))
    file = {"name": "video-0123456789ab.mp4", "kind": "video", "path": path or staged(tmp_path, data)}
    message = message_file(tmp_path, text="The video to approve.", file=file)
    code, out, err = run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "4242", "--message-file", message)
    return code, out, err, opener


def test_a_video_is_sent_by_sendvideo_after_the_message_as_a_reply_to_it_with_streaming_on(monkeypatch, capsys, tmp_path):
    code, out, err, opener = send_video(monkeypatch, capsys, tmp_path)
    assert code == 0 and json.loads(out) == {"message_id": "31"}
    assert [r[0].rsplit("/", 1)[1] for r in opener.requests] == ["sendMessage", "sendVideo"]
    _, body, headers, _ = opener.requests[1]
    assert headers["Content-type"].startswith("multipart/form-data")
    assert b'name="chat_id"\r\n\r\n4242' in body and b'name="reply_to_message_id"\r\n\r\n31' in body
    assert b'name="supports_streaming"\r\n\r\ntrue' in body
    assert b'name="video"; filename="video-0123456789ab.mp4"' in body and b"Content-Type: video/mp4" in body and MP4 in body
    assert TOKEN not in err


def test_a_document_or_a_photo_does_not_ask_for_streaming(monkeypatch, capsys, tmp_path):
    opener = Opener({"message_id": 31}, {"message_id": 32})
    message = message_file(tmp_path, text="Here.", file={"name": "a.png", "kind": "photo", "path": staged(tmp_path, PNG)})
    assert run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "4242", "--message-file", message)[0] == 0
    assert b"supports_streaming" not in opener.requests[1][1]


def test_a_video_that_is_a_png_is_refused_before_any_call(monkeypatch, capsys, tmp_path):
    code, _, err, opener = send_video(monkeypatch, capsys, tmp_path, data=PNG)
    assert code == 2 and opener.requests == [] and TOKEN not in err and str(tmp_path) not in err


def test_a_video_over_the_limit_is_refused_before_any_call_and_the_same_file_under_the_real_limit_is_sent(monkeypatch, capsys, tmp_path):
    monkeypatch.setitem(telegram.CAPABILITIES, "max_video_bytes", 40)
    code, _, _, opener = send_video(monkeypatch, capsys, tmp_path)
    assert code == 2 and opener.requests == []
    monkeypatch.setitem(telegram.CAPABILITIES, "max_video_bytes", 20971520)
    assert send_video(monkeypatch, capsys, tmp_path)[0] == 0


def test_a_video_path_that_is_a_link_or_a_folder_or_missing_is_refused_before_any_call(monkeypatch, capsys, tmp_path):
    real = staged(tmp_path, MP4, "real")
    link = tmp_path / "link"
    link.symlink_to(real)
    for path in (str(link), str(tmp_path), str(tmp_path / "missing")):
        code, _, err, opener = send_video(monkeypatch, capsys, tmp_path, path=path)
        assert code == 2 and opener.requests == [] and str(tmp_path) not in err


def test_an_empty_video_is_refused(monkeypatch, capsys, tmp_path):
    code, _, _, opener = send_video(monkeypatch, capsys, tmp_path, data=b"")
    assert code == 2 and opener.requests == []


def test_a_video_telegram_refuses_after_the_message_went_out_prints_the_id_and_a_warning_with_no_path_or_token(monkeypatch, capsys, tmp_path):
    import urllib.error
    url = f"https://api.telegram.org/bot{TOKEN}/sendVideo"
    code, out, err, _ = send_video(monkeypatch, capsys, tmp_path, MP4, None, {"message_id": 31}, urllib.error.URLError(url))
    assert code == 0 and json.loads(out) == {"message_id": "31", "document_failed": True}
    assert "file was not" in err and TOKEN not in err and str(tmp_path) not in err


def test_the_sniffer_tells_an_mp4_by_ftyp_at_bytes_4_to_8_and_nothing_else_is_taken_for_one():
    assert telegram.sniff_type(MP4[:4096]) == "mp4"
    assert telegram.sniff_type(b"\x00\x00\x00\x18ftypisom" + bytes(8)) == "mp4"
    assert telegram.sniff_type(PNG) == "png" and telegram.sniff_type(b"plain text") == "text"
    assert telegram.sniff_type(b"\x00\x00\x00\x18moov" + bytes(8)) is None


def test_the_capabilities_declare_the_video_a_provider_sends():
    caps = telegram.CAPABILITIES
    assert caps["max_video_bytes"] == 20971520 and "mp4" in caps["video_types"]
    assert "mp4" not in caps["send_types"], "an mp4 is a video here, never a document"
