"""Offline tests of the send side of providers/messenger/whatsapp-twilio.py: the window gate, the template, the messages (text,
and the Content messages of the card buttons when setup recorded the three templates), the 1600-character limit, the errors and
the listener over a pipe. Twilio's API is a fake opener; the only socket is the provider's own on 127.0.0.1.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_twilio_send.py
"""
from __future__ import annotations

import base64
import json
import time

import pytest

import whatsapp_twilio_kit as kit
from whatsapp_twilio_kit import (ACCOUNT, AUTH, BSUID, BUTTONS, FROM, KEY_SECRET, KEY_SID, NOW, PERSON, PUBLIC_URL, SENDER, TEMPLATE,
                                 TEXT, Clock, Opener, card, http_error, inbound, plain, wt)

WITH_BUTTONS = {"buttons": BUTTONS}
STATUS_URL = PUBLIC_URL + "?status=1"


def rig_of(tmp_path, *, opener=None, clock=None, buttons=False, **options):
    return kit.Rig(tmp_path, opener=opener or Opener(), clock=clock, config=WITH_BUTTONS if buttons else None, **options).start()


def open_window(r):
    assert r.post(inbound(0x50))[0] == 200


@pytest.fixture
def rigs(tmp_path):
    made = []

    def make(**kw):
        r = rig_of(tmp_path, **kw)
        made.append(r)
        return r
    yield make
    for r in made:
        if r.thread.is_alive():
            r.stop()


# --- text inside the window -----------------------------------------------------------------------------------------------------


def test_a_text_inside_the_window_is_one_message_with_the_senders_number_the_status_callback_and_no_content(rigs):
    r = rigs()
    open_window(r)
    answer = r.ask(1, PERSON, plain(TEXT))
    assert answer["ok"] is True
    [call] = r.opener.calls
    assert call["method"] == "POST" and call["url"] == f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Messages.json"
    assert call["fields"] == {"From": SENDER, "To": FROM, "Body": TEXT, "StatusCallback": STATUS_URL}
    assert call["content_type"] == "application/x-www-form-urlencoded" and call["timeout"] and call["timeout"] <= 15
    assert answer["message_id"] == kit.sid(0x1000 + 1)


def test_the_request_is_a_form_authenticated_as_the_restricted_key_and_the_auth_token_is_never_sent(rigs):
    r = rigs()
    open_window(r)
    r.ask(1, PERSON, plain(TEXT))
    [call] = r.opener.calls
    assert call["auth"] == "Basic " + base64.b64encode(f"{KEY_SID}:{KEY_SECRET}".encode()).decode()
    assert AUTH not in json.dumps(r.opener.calls) and ACCOUNT not in call["auth"]


def test_a_text_is_rendered_for_whatsapp_and_the_effect_command_is_byte_for_byte(rigs):
    r = rigs()
    open_window(r)
    command = "`python3 runtime/ops.py approve --path /srv/northwind-shop --id 12 --sha256 " + "ab" * 32 + "`"
    r.ask(1, PERSON, plain(f"**Effect** ~~old~~ [link](https://example.com)\n{command}"))
    body = r.opener.texts()[0]["Body"]
    assert body == f"*Effect* ~old~ link (https://example.com)\n{command}"


def test_a_text_that_rendering_makes_longer_than_1600_is_cut_with_the_note(rigs):
    r = rigs()
    open_window(r)
    table = "x" * 15 + "\n" + "\n".join("| " + "x" * 74 + " |" for _ in range(20))     # 1595 characters; the fence around a table adds 8
    assert len(table) <= 1600 and len(wt.render_whatsapp(table, 4096)) > 1600
    assert r.ask(1, PERSON, plain(table))["ok"] is True
    body = r.opener.texts()[0]["Body"]
    assert len(body) <= 1600 and body.endswith(wt.CUT_NOTE) and body.count("```") % 2 == 0


def test_the_cut_at_1600_never_falls_inside_a_fence_or_a_code_span():
    text = "intro\n```\n" + "\n".join(f"code line {i}" for i in range(300)) + "\n```\nlast"
    out = wt.render_whatsapp_twilio(text)
    assert len(out) <= 1600 and out.endswith("\n" + wt.CUT_NOTE) and out.count("```") % 2 == 0
    span = "`" + "s" * 80 + "`"
    out = wt.render_whatsapp_twilio("y" * 1560 + " " + span + " tail")
    assert span not in out and "`" not in out and len(out) <= 1600


def test_a_text_over_1600_characters_is_a_usage_error_of_the_bridge_and_not_split_by_the_provider(rigs):
    r = rigs()
    open_window(r)
    answer = r.ask(1, PERSON, plain("x" * 1601))
    assert answer["ok"] is False and answer["kind"] == "usage" and "1600" in answer["reason"]
    assert r.opener.calls == []
    assert r.ask(2, PERSON, plain("x" * 1600))["ok"] is True


def test_a_document_or_a_link_or_a_blank_text_is_a_usage_error(rigs):
    r = rigs()
    open_window(r)
    for n, bad in enumerate((plain(TEXT, document={"name": "a.md", "text": "body"}), plain(TEXT, link={"label": "x", "url": "https://x.example"}),
                             plain("   "), {"actions": []}, "not a dict", plain(TEXT, reply_to=5)), 1):
        answer = r.ask(n, PERSON, bad)
        assert answer["ok"] is False and answer["kind"] == "usage", bad
    assert r.opener.calls == []


def test_a_reply_to_is_accepted_and_not_sent_because_the_api_has_no_such_parameter(rigs):
    r = rigs()
    open_window(r)
    assert r.ask(1, PERSON, plain(TEXT, reply_to=kit.sid(0x70)))["ok"] is True
    assert set(r.opener.calls[0]["fields"]) == {"From", "To", "Body", "StatusCallback"}


# --- cards: typed commands by default, Content templates when setup recorded them -----------------------------------------


def test_without_the_three_template_sids_buttons_are_off_and_a_card_with_actions_is_a_usage_error(rigs):
    r = rigs()
    open_window(r)
    assert wt.capabilities(r.settings)["buttons"] is False and wt.capabilities(r.settings)["max_buttons"] == 0
    answer = r.ask(1, PERSON, card())
    assert answer["ok"] is False and answer["kind"] == "usage" and "at most 0 actions" in answer["reason"]
    assert r.opener.calls == []


def test_capabilities_follow_the_settings():
    off = wt.capabilities(kit.settings())
    assert off == {"max_text": 1600, "buttons": False, "max_buttons": 0, "max_button_label": 0, "lists": False, "max_list_rows": 0,
                   "url_buttons": False, "reply_context": True, "documents": False, "listen": True, "attachments": True,
                   "max_attachment_bytes": 16777216}
    on =wt.capabilities(kit.settings(buttons=BUTTONS))
    assert on == {**off, "buttons": True, "max_buttons": 3, "max_button_label": 20}
    assert wt.capabilities(None) == off


@pytest.mark.parametrize("count", [1, 2, 3])
def test_a_short_card_is_one_content_message_chosen_by_the_number_of_actions_with_the_body_titles_and_ids_as_variables(rigs, count):
    r = rigs(buttons=True)
    open_window(r)
    answer = r.ask(1, PERSON, card("Plan ready. Approve it?", n=count))
    assert answer["ok"] is True
    [call] = r.opener.calls
    fields = call["fields"]
    assert fields["ContentSid"] == BUTTONS[str(count)] and "Body" not in fields
    assert fields["From"] == SENDER and fields["To"] == FROM and fields["StatusCallback"] == STATUS_URL
    labels, ids = ["Approve", "Reject", "Later"], ["7:approve", "7:reject", "7:later"]
    expected = {"1": "Plan ready. Approve it?"}
    for k in range(count):
        expected[str(2 + 2 * k)], expected[str(3 + 2 * k)] = labels[k], ids[k]
    assert json.loads(fields["ContentVariables"]) == expected
    assert answer["message_id"] == kit.sid(0x1000 + 1)


def test_the_titles_are_cut_to_20_characters_made_different_and_the_body_is_rendered(rigs):
    r = rigs(buttons=True)
    open_window(r)
    actions = [{"id": "7:approve", "label": "A very long label that goes past twenty"}, {"id": "7:reject", "label": "A very long label that goes past twenty"},
               {"id": "7:release", "label": "A very long label that goes past twenty"}]
    r.ask(1, PERSON, {"text": "**Go** now?", "actions": actions, "link": None, "document": None})
    variables = json.loads(r.opener.calls[0]["fields"]["ContentVariables"])
    titles = [variables["2"], variables["4"], variables["6"]]
    assert all(0 < len(t) <= 20 for t in titles) and len({t.casefold() for t in titles}) == 3
    assert variables["1"] == "*Go* now?" and variables["3"] == "7:approve" and variables["7"] == "7:release"


def test_an_action_id_over_128_characters_is_a_usage_error_and_four_actions_too(rigs):
    r = rigs(buttons=True)
    open_window(r)
    long_id = {"id": "7:" + "a" * 127, "label": "Go"}
    assert r.ask(1, PERSON, {"text": "x", "actions": [long_id], "link": None, "document": None})["kind"] == "usage"
    ok_id = {"id": "7:" + "a" * 126, "label": "Go"}
    assert r.ask(2, PERSON, {"text": "x", "actions": [ok_id], "link": None, "document": None})["ok"] is True
    four = dict(card(n=3), actions=card(n=3)["actions"] + [{"id": "x", "label": "Four"}])
    assert r.ask(3, PERSON, four)["kind"] == "usage"


def test_a_long_card_is_the_text_then_a_buttons_message_with_a_short_fixed_body_and_the_answered_sid_is_the_texts(rigs):
    r = rigs(buttons=True)
    open_window(r)
    text = ("line of a long plan\n" * 60).strip()
    assert 1024 < len(text) <= 1600
    answer = r.ask(1, PERSON, card(text, n=2))
    assert answer["ok"] is True
    first, second = r.opener.calls
    assert first["fields"]["Body"] == text and "ContentSid" not in first["fields"]
    assert second["fields"]["ContentSid"] == BUTTONS["2"]
    assert json.loads(second["fields"]["ContentVariables"])["1"] == wt.BUTTONS_LINE
    assert answer["message_id"] == kit.sid(0x1000 + 1)
    # a reply to the buttons message binds to the card, as the text's SID
    r.post(inbound(2, body="reply", OriginalRepliedMessageSid=kit.sid(0x1000 + 2)))
    assert r.out.updates()[-1]["reply_to"] == kit.sid(0x1000 + 1)


def test_a_failing_buttons_message_after_the_text_is_logged_by_class_and_the_send_still_answers_ok(rigs):
    opener = Opener([("POST", lambda call: http_error(400, 21211) if "ContentSid" in call["fields"] else None)])
    r = rigs(opener=opener, buttons=True)
    open_window(r)
    text = ("line of a long plan\n" * 60).strip()
    assert r.ask(1, PERSON, card(text))["ok"] is True
    assert len(opener.calls) == 2 and any("buttons after the text" in line and "21211" in line for line in r.logs)


def test_when_twilio_refuses_the_variables_the_text_and_a_fixed_buttons_message_are_sent_and_it_is_said_once(rigs):
    refused = []

    def rule(call):
        fields = call["fields"]
        if "ContentSid" in fields and "\n" in json.loads(fields["ContentVariables"])["1"]:
            refused.append(1)
            return http_error(400, 21656, "planted-answer-text")
        return None
    opener = Opener([("POST", rule)])
    r = rigs(opener=opener, buttons=True)
    open_window(r)
    first = r.ask(1, PERSON, card("two\nlines\nhere?"))
    assert first["ok"] is True and len(opener.calls) == 3                   # refused Content, then the text, then the buttons
    assert opener.calls[1]["fields"]["Body"] == "two\nlines\nhere?"
    assert json.loads(opener.calls[2]["fields"]["ContentVariables"])["1"] == wt.BUTTONS_LINE
    assert first["message_id"] == kit.sid(0x1000 + 2)
    second = r.ask(2, PERSON, card("again\nwith newline?"))
    assert second["ok"] is True and len(opener.calls) == 5 and len(refused) == 1       # no second refused call: it goes the other way
    third = r.ask(3, PERSON, card("one line?"))
    assert third["ok"] is True and "ContentSid" in opener.calls[-1]["fields"] and "Body" not in opener.calls[-1]["fields"]
    notes = [line for line in r.logs if "21656" in line]
    assert len(notes) == 1 and "planted-answer-text" not in " ".join(r.logs)


# --- the window, the template ---------------------------------------------------------------------------------------------------


def test_with_no_message_from_the_person_the_template_goes_once_and_the_answer_is_deferred(rigs):
    r = rigs()
    first = r.ask(1, PERSON, plain(TEXT))
    assert first["ok"] is False and first["kind"] == "deferred" and "reminder was sent" in first["reason"]
    [call] = r.opener.calls
    assert call["fields"] == {"From": SENDER, "To": FROM, "ContentSid": TEMPLATE, "StatusCallback": STATUS_URL}
    second = r.ask(2, PERSON, plain(TEXT))
    assert second["kind"] == "deferred" and len(r.opener.calls) == 1


def test_the_window_closes_at_23_hours_30_minutes_and_the_template_is_sent_again_only_after_7_days(rigs):
    clock = Clock()
    r = rigs(clock=clock)
    open_window(r)
    clock.now = NOW + 23 * 3600 + 1799
    assert r.ask(1, PERSON, plain(TEXT))["ok"] is True
    clock.now = NOW + 23 * 3600 + 1800
    assert r.ask(2, PERSON, plain(TEXT))["kind"] == "deferred"
    assert len(r.opener.contents()) == 1
    clock.now += 7 * 86400 - 1
    assert r.ask(3, PERSON, plain(TEXT))["kind"] == "deferred" and len(r.opener.contents()) == 1
    clock.now += 2
    assert r.ask(4, PERSON, plain(TEXT))["kind"] == "deferred" and len(r.opener.contents()) == 2
    r.post(inbound(0x51))                                                        # the person writes: the window opens again
    assert r.ask(5, PERSON, plain(TEXT))["ok"] is True


def test_a_restart_never_resends_the_template_for_the_same_closed_window(tmp_path):
    clock = Clock()
    opener = Opener()
    first = rig_of(tmp_path, opener=opener, clock=clock)
    assert first.ask(1, PERSON, plain(TEXT))["kind"] == "deferred"
    first.stop()
    second = rig_of(tmp_path, opener=opener, clock=clock)
    try:
        assert second.ask(1, PERSON, plain(TEXT))["kind"] == "deferred"
        assert len(opener.contents()) == 1
    finally:
        second.stop()


def test_error_63016_on_the_send_itself_closes_the_window_sends_the_template_once_and_defers(rigs):
    opener = Opener([("POST", lambda call: http_error(400, 63016) if "Body" in call["fields"] else None)])
    r = rigs(opener=opener)
    open_window(r)
    answer = r.ask(1, PERSON, plain(TEXT))
    assert answer["kind"] == "deferred"
    assert len(opener.contents()) == 1 and opener.contents()[0]["ContentSid"] == TEMPLATE
    assert r.ask(2, PERSON, plain(TEXT))["kind"] == "deferred" and len(opener.contents()) == 1
    assert not r.store.window_open(PERSON, NOW)


def test_a_failed_template_is_logged_by_class_and_the_card_is_still_deferred(rigs):
    opener = Opener([("POST", lambda call: http_error(400, 63016) if "Body" in call["fields"] else http_error(400, 63032))])
    r = rigs(opener=opener)
    open_window(r)
    answer = r.ask(1, PERSON, plain(TEXT))
    assert answer["kind"] == "deferred" and "could not be sent" in answer["reason"]
    assert any("63032" in line for line in r.logs)


# --- errors -------------------------------------------------------------------------------------------------------------------------


def test_error_20003_is_not_configured_the_event_is_written_and_the_process_exits_3(tmp_path):
    opener = Opener([("POST", lambda call: http_error(401, 20003, "PLANTED_BODY_TEXT"))])
    r = rig_of(tmp_path, opener=opener)
    open_window(r)
    answer = r.ask(1, PERSON, plain(TEXT))
    assert answer["ok"] is False and answer["kind"] == "not-configured" and "PLANTED" not in json.dumps(r.out.lines)
    r.pipe.close()
    r.thread.join(10)
    assert r.result == [3]
    events = r.out.events("error")
    assert events and events[-1]["kind"] == "not-configured" and "PLANTED" not in json.dumps(events)


def test_http_401_without_a_code_is_also_not_configured(tmp_path):
    r = rig_of(tmp_path, opener=Opener([("POST", lambda call: http_error(401, None))]))
    open_window(r)
    assert r.ask(1, PERSON, plain(TEXT))["kind"] == "not-configured"
    r.thread.join(10)
    assert r.result == [3]


def test_a_rate_limit_is_failed_with_a_short_wait_before_the_next_send(rigs):
    opener = Opener([("POST", lambda call: http_error(429, 63018, "PLANTED_BODY_TEXT") if "limited" in call["fields"].get("Body", "") else None)])
    r = rigs(opener=opener, rate_wait=0.3)
    open_window(r)
    start = time.monotonic()
    answer = r.ask(1, PERSON, plain("limited"))
    assert answer["ok"] is False and answer["kind"] == "failed" and "63018" in answer["reason"] and "PLANTED" not in answer["reason"]
    assert r.ask(2, PERSON, plain(TEXT))["ok"] is True
    assert time.monotonic() - start >= 0.3


@pytest.mark.parametrize("status,code", [(400, 21211), (500, None), (400, 21610), (503, 20500)])
def test_other_failures_are_failed_with_the_status_and_the_code_and_never_the_body(rigs, status, code):
    r = rigs(opener=Opener([("POST", lambda call: http_error(status, code, "PLANTED_BODY_TEXT"))]))
    open_window(r)
    answer = r.ask(1, PERSON, plain(TEXT))
    assert answer["kind"] == "failed" and str(status) in answer["reason"] and "PLANTED" not in answer["reason"]
    assert (code is None) or str(code) in answer["reason"]
    assert "PLANTED" not in " ".join(r.logs)


def test_network_errors_and_bad_answers_are_failed(rigs):
    import urllib.error
    for rule in (urllib.error.URLError(OSError("planted-reason " + TEXT)), OSError("down"), {"status": "queued"}, b"not json", {"sid": "short"}):
        r = rigs(opener=Opener([("POST", rule)]))
        open_window(r)
        answer = r.ask(1, PERSON, plain(TEXT))
        assert answer["ok"] is False and answer["kind"] == "failed" and "planted" not in answer["reason"] and TEXT not in answer["reason"]
        r.stop()


def test_a_redirect_is_refused_because_the_request_carries_the_key():
    handler = wt.RefuseRedirect()
    with pytest.raises(wt.TwilioError) as e:
        handler.redirect_request(None, type("F", (), {"close": lambda self: None})(), 302, "x", {}, "https://elsewhere.example/")
    assert e.value.status == 302 and KEY_SECRET not in str(e.value)


def test_a_person_known_only_by_a_business_scoped_id_cannot_be_written_to_until_the_number_is_learned(rigs):
    r = rigs()
    open_window(r)
    answer = r.ask(1, BSUID, plain(TEXT))
    assert answer["ok"] is False and answer["kind"] == "failed" and "messaging.senders.whatsapp-twilio" in answer["reason"]
    r.post(inbound(0x52, frm=FROM, ExternalUserId=BSUID))
    assert r.ask(2, BSUID, plain(TEXT))["ok"] is True and r.opener.calls[-1]["fields"]["To"] == FROM


def test_requests_with_a_bad_shape_are_answered_or_dropped_without_a_crash(rigs):
    r = rigs()
    open_window(r)
    r.pipe.writer.write(b"not json\n")
    r.pipe.send({"op": "send", "chat": PERSON, "message": plain(TEXT)})                     # no id: dropped
    assert r.ask(3, "", plain(TEXT))["kind"] == "usage"
    assert r.ask(4, "x" * 65, plain(TEXT))["kind"] == "usage"
    r.pipe.send({"id": 5, "op": "receive", "chat": PERSON})
    assert kit.wait_for(lambda: any(a["id"] == 5 for a in r.out.answers()))
    assert next(a for a in r.out.answers() if a["id"] == 5)["kind"] == "usage"
    assert r.ask(6, PERSON, plain(TEXT))["ok"] is True


def test_the_end_of_stdin_stops_the_listener_with_code_0_and_the_port_closes(tmp_path):
    r = rig_of(tmp_path)
    assert r.stop() == 0
    assert r.listener.server.socket.fileno() == -1


def test_a_21656_status_report_for_a_card_resends_it_once_as_text_and_a_fixed_body_buttons_message(tmp_path):
    opener = Opener()
    r = rig_of(tmp_path, opener=opener, buttons=True)
    try:
        open_window(r)
        card_sid = r.ask(1, PERSON, card("Plan ready. Approve it?"))["message_id"]
        assert len(opener.calls) == 1 and "ContentSid" in opener.calls[0]["fields"]
        for report in (kit.status_report(kit.sid(0x99), "21656"), kit.status_report(card_sid, "21656", account=kit.OTHER_ACCOUNT)):
            assert r.status(report)[0] == 200
        assert r.status(kit.status_report(card_sid, "21656"))[0] == 200
        assert r.status(kit.status_report(card_sid, "21656", status="undelivered"))[0] == 200      # a second report: not resent
        assert r.ask(2, PERSON, plain("after"))["ok"] is True                                       # the worker handled the reports first
        texts = [c["fields"] for c in opener.calls[1:]]
        assert texts[0]["Body"] == "Plan ready. Approve it?" and "ContentSid" not in texts[0]
        assert json.loads(texts[1]["ContentVariables"])["1"] == wt.BUTTONS_LINE
        assert len(opener.calls) == 4 and texts[2]["Body"] == "after"
        assert any("status report" in line and "21656" in line for line in r.logs)
    finally:
        r.stop()
