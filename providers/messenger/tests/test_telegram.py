"""Offline tests for providers/messenger/telegram.py: the Bot API is a fake opener (no network, no real token).

Run: uv run --with pytest pytest providers/messenger/tests
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "telegram.py"
TOKEN = "123456789:FAKE-token-AAAAAAAAAAAAAAAAAAAA-never-print-me"
spec = importlib.util.spec_from_file_location("messenger_telegram_under_test", SCRIPT)
telegram = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = telegram
spec.loader.exec_module(telegram)


class Answer:
    def __init__(self, result):
        self.body = json.dumps({"ok": True, "result": result}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class Opener:
    """Answers each call from a queue: a result, or an exception to raise. Records every request."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def open(self, request, timeout=None):
        self.requests.append((request.full_url, request.data, dict(request.header_items()), timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return Answer(answer)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("MESSENGER_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.delenv("MESSENGER_TELEGRAM_API_BASE", raising=False)


def run(monkeypatch, capsys, opener, *argv):
    monkeypatch.setattr(telegram, "OPENER", opener)
    code = telegram.main(list(argv))
    seen = capsys.readouterr()
    return code, seen.out, seen.err


def message_file(tmp_path, **fields):
    path = tmp_path / "message.json"
    path.write_text(json.dumps({"text": "Hello", "actions": [], "link": None, "document": None, **fields}))
    return str(path)


def test_capabilities_need_no_token_and_no_call(monkeypatch, capsys):
    monkeypatch.delenv("MESSENGER_TELEGRAM_BOT_TOKEN")
    code, out, _ = run(monkeypatch, capsys, Opener(), "capabilities", "--platform", "telegram")
    caps = json.loads(out)
    assert code == 0 and caps["max_text"] == 4096 and caps["buttons"] is True and caps["lists"] is False
    assert set(caps) == {"max_text", "buttons", "max_buttons", "max_button_label", "lists", "max_list_rows", "url_buttons",
                         "reply_context", "documents"}


def test_receive_maps_a_message_and_a_callback_query_and_skips_the_rest(monkeypatch, capsys):
    updates = [
        {"update_id": 10, "message": {"message_id": 5, "text": "hello", "from": {"id": 4242}, "chat": {"id": 4242, "type": "private"}}},
        {"update_id": 11, "callback_query": {"id": "cb1", "data": "7:approve", "from": {"id": 4242},
                                             "message": {"message_id": 6, "chat": {"id": 4242, "type": "private"}}}},
        {"update_id": 12, "message": {"message_id": 8, "text": "in a group", "reply_to_message": {"message_id": 3},
                                      "from": {"id": 9}, "chat": {"id": -100, "type": "group"}}},
        {"update_id": 13, "message": {"message_id": 9, "photo": [], "from": {"id": 9}, "chat": {"id": 9, "type": "private"}}},
        {"update_id": 14, "edited_message": {}},
    ]
    opener = Opener(updates)
    code, out, _ = run(monkeypatch, capsys, opener, "receive", "--platform", "telegram", "--offset", "10", "--timeout", "20")
    found = json.loads(out)
    assert code == 0 and found["next_offset"] == 15
    assert found["updates"][0] == {"update_id": 10, "text": "hello", "action": None, "action_ref": None, "reply_to": None,
                                   "sender": "4242", "chat": "4242", "private": True}
    assert found["updates"][1]["action"] == "7:approve" and found["updates"][1]["action_ref"] == "cb1"
    assert found["updates"][1]["text"] is None
    assert found["updates"][2]["private"] is False and found["updates"][2]["reply_to"] == "3"
    assert len(found["updates"]) == 3
    url, body, _, timeout = opener.requests[0]
    assert url.endswith("/getUpdates") and json.loads(body) == {"offset": 10, "timeout": 20,
                                                                "allowed_updates": ["message", "callback_query"]}
    assert timeout > 20


def test_send_builds_the_inline_keyboard_and_a_url_button_as_plain_text(monkeypatch, capsys, tmp_path):
    opener = Opener({"message_id": 77})
    path = message_file(tmp_path, text="<b>not markup</b> *x*", actions=[{"id": "7:approve", "label": "Approve"},
                                                                         {"id": "7:reject", "label": "Reject"}],
                        link={"label": "Open the page", "url": "https://page.example/x"})
    code, out, _ = run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "4242", "--message-file", path)
    assert code == 0 and json.loads(out) == {"message_id": "77"}
    url, body, _, _ = opener.requests[0]
    sent = json.loads(body)
    assert url.endswith("/sendMessage") and sent["chat_id"] == 4242 and "parse_mode" not in sent
    assert sent["text"] == "<b>not markup</b> *x*"
    assert sent["reply_markup"] == {"inline_keyboard": [[{"text": "Approve", "callback_data": "7:approve"}],
                                                        [{"text": "Reject", "callback_data": "7:reject"}],
                                                        [{"text": "Open the page", "url": "https://page.example/x"}]]}


def test_a_document_is_sent_after_the_message_as_a_reply_to_it(monkeypatch, capsys, tmp_path):
    opener = Opener({"message_id": 31}, {"message_id": 32})
    path = message_file(tmp_path, document={"name": "plan 4.txt", "text": "the whole text"})
    code, out, _ = run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "-100", "--message-file", path)
    assert code == 0 and json.loads(out) == {"message_id": "31"}
    url, body, headers, _ = opener.requests[1]
    assert url.endswith("/sendDocument") and headers["Content-type"].startswith("multipart/form-data")
    assert b'name="reply_to_message_id"\r\n\r\n31' in body and b'filename="plan_4.txt"' in body and b"the whole text" in body


def test_a_message_beyond_the_capabilities_is_refused_before_any_call(monkeypatch, capsys, tmp_path):
    cases = [message_file(tmp_path, actions=[{"id": "x" * 65, "label": "Approve"}]),     # callback_data over 64 bytes
             message_file(tmp_path, actions=[{"id": "é" * 33, "label": "Approve"}]),  # 66 bytes in 33 characters
             message_file(tmp_path, text="x" * 4097),
             message_file(tmp_path, actions=[{"id": str(n), "label": "A"} for n in range(7)]),
             message_file(tmp_path, link={"label": "x", "url": "javascript:alert(1)"})]
    for path in cases:
        opener = Opener()
        code, out, err = run(monkeypatch, capsys, opener, "send", "--platform", "telegram", "--chat", "1", "--message-file", path)
        assert code == 2 and out == "" and opener.requests == [], err


def test_a_failing_call_writes_no_token_to_standard_output_or_error(monkeypatch, capsys, tmp_path):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    failures = [urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(json.dumps(
                    {"ok": False, "description": f"Unauthorized {TOKEN}"}).encode())),
                urllib.error.HTTPError(url, 500, "boom", {}, io.BytesIO(json.dumps(
                    {"ok": False, "description": f"error for {TOKEN}"}).encode())),
                urllib.error.URLError(f"cannot reach {url}"),
                OSError(f"socket error {url}"),
                RuntimeError(f"unexpected {TOKEN}")]
    codes = []
    for failure in failures:
        code, out, err = run(monkeypatch, capsys, Opener(failure), "receive", "--platform", "telegram", "--offset", "0", "--timeout", "1")
        assert TOKEN not in out + err and "123456789" not in out + err and "Traceback" not in err, err
        assert err.startswith("error: ") and out == ""
        codes.append(code)
    assert codes == [3, 1, 1, 1, 1]
    sent = Opener(urllib.error.URLError(url))
    code, out, err = run(monkeypatch, capsys, sent, "send", "--platform", "telegram", "--chat", "1",
                         "--message-file", message_file(tmp_path))
    assert code == 1 and TOKEN not in out + err


def test_a_409_from_get_updates_tells_the_person_to_remove_the_webhook(monkeypatch, capsys):
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    conflict = urllib.error.HTTPError(url, 409, "Conflict", {}, io.BytesIO(b'{"ok":false,"description":"Conflict: webhook"}'))
    code, out, err = run(monkeypatch, capsys, Opener(conflict), "receive", "--platform", "telegram", "--offset", "0", "--timeout", "1")
    assert code == 3 and "webhook" in err and "deleteWebhook" in err and TOKEN not in err


def test_ack_answers_the_callback_query(monkeypatch, capsys):
    opener = Opener(True)
    code, out, _ = run(monkeypatch, capsys, opener, "ack", "--platform", "telegram", "--action-ref", "cb9")
    assert code == 0 and json.loads(out) == {"acked": True}
    assert opener.requests[0][0].endswith("/answerCallbackQuery") and json.loads(opener.requests[0][1]) == {"callback_query_id": "cb9"}


def test_no_token_is_exit_3_and_another_platform_is_exit_2(monkeypatch, capsys):
    monkeypatch.delenv("MESSENGER_TELEGRAM_BOT_TOKEN")
    monkeypatch.setattr(telegram, "secret_resolver", lambda: type("R", (), {"resolve": staticmethod(lambda *a, **k: None)}))
    code, _, err = run(monkeypatch, capsys, Opener(), "ack", "--platform", "telegram", "--action-ref", "x")
    assert code == 3 and "keyring set openhora messenger-telegram" in err
    code, _, _ = run(monkeypatch, capsys, Opener(), "capabilities", "--platform", "other")
    assert code == 2


def test_the_platforms_line_is_the_one_the_resolver_reads_and_the_token_is_never_an_argument():
    text = SCRIPT.read_text()
    assert 'PLATFORMS = ("telegram",)' in text and '"parse_mode"' not in text
    assert "--token" not in text
