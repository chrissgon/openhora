"""Offline tests of the optional reminder template of providers/messenger/whatsapp-twilio.py: setup with and without it, and the
send side without it. Every test points OPENHORA_STATE_DIR at a temporary folder.
Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_twilio_optional_template.py
"""
from __future__ import annotations

import json
import os

import pytest

import whatsapp_twilio_kit as kit
from whatsapp_twilio_kit import ACCOUNT, PERSON, TEMPLATE, TEXT, Clock, Opener, http_error, inbound, plain, wt

HOST = "northwind-laptop.tail1234.ts.net"
LOG_LINE = "outside the 24-hour window and no reminder template is configured; the card waits until you write"
BASE = ["--account-sid", ACCOUNT, "--sender", "+14155550100"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for name, value in kit.SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(wt, "funnel_host", lambda: HOST)
    old = os.umask(0o077)
    yield state
    os.umask(old)


def run_setup(*argv):
    return wt.cmd_setup(wt.build_parser().parse_args(["setup", *argv]))


def saved(home):
    return json.loads((home / "whatsapp-twilio" / "settings.json").read_text())


def test_setup_without_a_template_succeeds_records_none_and_says_the_person_must_write_first(home, capsys):
    assert run_setup(*BASE) == 0
    found = saved(home)
    assert found["template_sid"] is None and wt.check_settings(found) == found
    assert "must write first" in capsys.readouterr().out


def test_a_template_can_be_added_later_and_no_template_removes_it(home):
    assert run_setup(*BASE) == 0
    assert run_setup("--template-sid", TEMPLATE) == 0 and saved(home)["template_sid"] == TEMPLATE
    assert run_setup("--port", "8801") == 0 and saved(home)["template_sid"] == TEMPLATE
    assert run_setup("--no-template") == 0
    assert saved(home)["template_sid"] is None and saved(home)["account_sid"] == ACCOUNT
    assert run_setup("--no-template", "--template-sid", TEMPLATE) == 2


def test_a_malformed_template_sid_is_still_refused(home, capsys):
    assert run_setup(*BASE, "--template-sid", "HXshort") == 2
    assert not (home / "whatsapp-twilio" / "settings.json").exists()


@pytest.fixture
def rigs(tmp_path):
    made = []

    def make(**kw):
        r = kit.Rig(tmp_path, config={"template_sid": None}, **kw).start()
        made.append(r)
        return r
    yield make
    for r in made:
        if r.thread.is_alive():
            r.stop()


def test_outside_the_window_without_a_template_nothing_is_sent_the_answer_is_deferred_and_the_line_is_logged_once_a_day(rigs):
    clock = Clock()
    r = rigs(clock=clock)
    for n in range(1, 4):
        answer = r.ask(n, PERSON, plain(TEXT))
        assert answer["ok"] is False and answer["kind"] == "deferred"
    assert r.opener.calls == [] and r.logs.count(LOG_LINE) == 1
    clock.now += 24 * 3600 + 1
    assert r.ask(9, PERSON, plain(TEXT))["kind"] == "deferred"
    assert r.opener.calls == [] and r.logs.count(LOG_LINE) == 2


def test_after_a_message_from_the_person_the_card_is_sent(rigs):
    r = rigs()
    assert r.ask(1, PERSON, plain(TEXT))["kind"] == "deferred"
    assert r.post(inbound(0x50))[0] == 200
    assert r.ask(2, PERSON, plain(TEXT))["ok"] is True
    [call] = r.opener.calls
    assert call["fields"]["Body"] == TEXT


def test_error_63016_on_the_send_itself_without_a_template_defers_and_sends_no_template(rigs):
    opener = Opener([("POST", lambda call: http_error(400, 63016) if "Body" in call["fields"] else None)])
    r = rigs(opener=opener)
    assert r.post(inbound(0x50))[0] == 200
    assert r.ask(1, PERSON, plain(TEXT))["kind"] == "deferred"
    assert [c for c in opener.contents()] == [] and r.logs.count(LOG_LINE) == 1
    assert r.ask(2, PERSON, plain(TEXT))["kind"] == "deferred" and r.logs.count(LOG_LINE) == 1
