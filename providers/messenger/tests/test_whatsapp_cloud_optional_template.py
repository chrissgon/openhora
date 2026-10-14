"""Offline tests of the optional reminder template of providers/messenger/whatsapp-cloud.py: setup with and without it, and the
send side without it (nothing sent, `deferred`, one log line per chat per 24 hours). Every test points OPENHORA_STATE_DIR at a
temporary folder. Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_cloud_optional_template.py
"""
from __future__ import annotations

import json
import os

import pytest

from whatsapp_cloud_kit import PERSON, PHONE_ID, TOKEN, Clock, Opener, card, plain, settings, wc

LOG_LINE = "outside the 24-hour window and no reminder template is configured; the card waits until you write"


@pytest.fixture
def home(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    old = os.umask(0o077)
    yield state
    os.umask(old)


def run_setup(*argv):
    return wc.cmd_setup(wc.build_parser().parse_args(["setup", *argv]))


def saved(home):
    return json.loads((home / "whatsapp-cloud" / "settings.json").read_text())


def test_setup_without_a_template_succeeds_records_none_and_says_the_person_must_write_first(home, capsys, monkeypatch):
    monkeypatch.setattr(wc, "funnel_host", lambda: "box.tail9.ts.net")
    assert run_setup("--phone-number-id", PHONE_ID) == 0
    found = saved(home)
    assert found["template"] is None and found["template_language"] is None
    assert wc.check_settings(found) == found and "must write first" in capsys.readouterr().out


@pytest.mark.parametrize("flag", [["--template", "decisions_waiting"], ["--template-language", "pt_BR"]])
def test_one_template_flag_without_the_other_is_a_usage_error_and_writes_nothing(home, capsys, monkeypatch, flag):
    monkeypatch.setattr(wc, "funnel_host", lambda: None)
    assert run_setup("--phone-number-id", PHONE_ID, *flag) == 2
    assert "--template-language" in capsys.readouterr().err and not (home / "whatsapp-cloud" / "settings.json").exists()


def test_a_template_can_be_added_later_and_no_template_removes_it(home, monkeypatch):
    monkeypatch.setattr(wc, "funnel_host", lambda: None)
    url = ("--public-url", "https://northwind-shop.example")      # MSG-11: without Tailscale the address is given on every run
    assert run_setup("--phone-number-id", PHONE_ID, *url) == 0
    assert run_setup("--template", "decisions_waiting", "--template-language", "pt_BR", *url) == 0
    assert saved(home)["template"] == "decisions_waiting"
    assert run_setup("--no-template", *url) == 0
    found = saved(home)
    assert found["template"] is None and found["template_language"] is None and found["phone_number_id"] == PHONE_ID
    assert run_setup("--no-template", "--template", "x") == 2


def test_a_settings_file_with_only_one_of_the_two_is_refused():
    with pytest.raises(wc.ProviderError):
        wc.check_settings(settings(template=None))


def no_template_sender(tmp_path, opener=None, clock=None, logs=None):
    clock = clock or Clock()
    (tmp_path / "s").mkdir(mode=0o700, exist_ok=True)
    store = wc.Store(str(tmp_path / "s"), clock)
    opener = opener or Opener()
    log = logs if logs is not None else []
    sender = wc.Sender(wc.Graph(TOKEN, PHONE_ID, opener=opener), store, settings(template=None, template_language=None), log.append, clock)
    return sender, opener, store, clock, log


def test_outside_the_window_without_a_template_nothing_is_sent_the_answer_is_deferred_and_the_line_is_logged_once_a_day(tmp_path):
    sender, opener, store, clock, logs = no_template_sender(tmp_path)
    for _ in range(4):
        with pytest.raises(wc.Deferred) as e:
            sender.send(PERSON, card())
    assert "24-hour window" in e.value.reason and opener.calls == []
    assert logs == [LOG_LINE]
    clock.now += 24 * 3600 - 1
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, plain("x"))
    assert logs == [LOG_LINE]
    clock.now += 2
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, plain("x"))
    assert logs == [LOG_LINE, LOG_LINE] and opener.calls == []
    assert store.entry(PERSON)[1] == 0, "no template mark is written"


def test_each_chat_has_its_own_log_line(tmp_path):
    sender, opener, _, _, logs = no_template_sender(tmp_path)
    for chat in (PERSON, "5511911111111"):
        with pytest.raises(wc.Deferred):
            sender.send(chat, card())
    assert logs == [LOG_LINE, LOG_LINE] and opener.calls == []


def test_after_a_message_from_the_person_the_card_is_sent(tmp_path):
    sender, opener, store, clock, _ = no_template_sender(tmp_path)
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, card())
    store.note_inbound(PERSON, clock())
    assert sender.send(PERSON, card()) == "wamid.OUT1" and len(opener.sent()) == 1


def test_a_late_131047_report_without_a_template_closes_the_window_and_sends_nothing(tmp_path):
    sender, opener, store, clock, logs = no_template_sender(tmp_path)
    store.note_inbound(PERSON, clock() - 60)
    wamid = sender.send(PERSON, card())
    clock.now += 60
    sender.late_failure(wamid)
    assert opener.of_type("template") == [] and not store.window_open(PERSON, clock())
    assert logs == [LOG_LINE]
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, card())
    assert logs == [LOG_LINE] and len(opener.sent()) == 1
