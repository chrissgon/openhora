"""Offline tests for the `typing` verb of providers/messenger/telegram.py (slice S10): the Bot API is a fake opener (no network, no real token).

The oracle reads the requests the fake opener recorded: the method named in the URL and the JSON body, written here as literals. The vacuity case plants a wrong chat id and shows
the same reading sees it.

Run: uv run --with pytest pytest providers/messenger/tests/test_telegram_typing.py
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from test_telegram import TOKEN, Opener, run, telegram, token  # noqa: F401  (the fake Bot API of test_telegram.py)


def test_typing_asks_the_bot_api_for_the_typing_action_in_that_chat_and_nothing_else(monkeypatch, capsys):
    opener = Opener(True)
    code, out, _ = run(monkeypatch, capsys, opener, "typing", "--platform", "telegram", "--chat", "4242")
    assert code == 0 and json.loads(out) == {"typing": True}
    assert len(opener.requests) == 1
    url, body = opener.requests[0][0], json.loads(opener.requests[0][1])
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendChatAction" and body == {"chat_id": 4242, "action": "typing"}


def test_a_group_chat_id_keeps_its_sign_and_a_wrong_one_would_be_seen(monkeypatch, capsys):
    opener = Opener(True)
    run(monkeypatch, capsys, opener, "typing", "--platform", "telegram", "--chat", "-100123")
    assert json.loads(opener.requests[0][1])["chat_id"] == -100123 != 100123      # vacuity: the same reading tells a dropped sign


@pytest.mark.parametrize("chat", ["abc", "12 3", "", "1" * 25])
def test_a_chat_that_is_not_an_id_is_a_usage_error_and_no_call_is_made(monkeypatch, capsys, chat):
    opener = Opener()
    code, _, err = run(monkeypatch, capsys, opener, "typing", "--platform", "telegram", "--chat", chat)
    assert code == 2 and opener.requests == [] and TOKEN not in err


def test_a_refusal_of_the_service_is_exit_1_without_the_token(monkeypatch, capsys):
    url = "https://api.telegram.org/bot/sendChatAction"
    import io
    refused = urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b'{"ok": false, "description": "bot was blocked by the user"}'))
    code, out, err = run(monkeypatch, capsys, Opener(refused), "typing", "--platform", "telegram", "--chat", "4242")
    assert code == 1 and out == "" and TOKEN not in err


def test_the_capabilities_declare_typing_and_the_verb_is_listed():
    assert telegram.CAPABILITIES["typing"] is True
