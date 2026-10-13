"""Offline tests of the send side of providers/messenger/whatsapp-cloud.py: the window gate, the template, the messages, the
errors, and the listener's protocol (ready, answers, exit codes). The Graph API is a fake opener; no network.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_cloud_send.py
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error

import pytest

import whatsapp_cloud_kit as kit
from whatsapp_cloud_kit import (BSUID, NOW, PERSON, PHONE_ID, TEXT, TOKEN, Clock, Opener, Rig, card, envelope, http_error, plain,
                                settings, text_message, wc)

DAY = 86400
HOUR = 3600


def make_sender(tmp_path, opener=None, clock=None, folder="s", logs=None):
    clock = clock or Clock()
    (tmp_path / folder).mkdir(mode=0o700, exist_ok=True)
    store = wc.Store(str(tmp_path / folder), clock)
    opener = opener or Opener()
    sender = wc.Sender(wc.Graph(TOKEN, PHONE_ID, opener=opener), store, settings(), (logs if logs is not None else []).append, clock)
    return sender, opener, store, clock


def opened(tmp_path, **kw):
    """A sender whose person wrote a minute ago."""
    sender, opener, store, clock = make_sender(tmp_path, **kw)
    store.note_inbound(PERSON, clock() - 60)
    return sender, opener, store, clock


# --- 5. inside the window ---------------------------------------------------------------------------------------------------


def test_a_short_card_is_one_interactive_message_with_the_buttons_and_the_answer_is_its_id(tmp_path):
    sender, opener, _, _ = opened(tmp_path)
    wamid = sender.send(PERSON, card("**Plan** ready. Approve it?", n=3))
    [message] = opener.sent()
    assert wamid == "wamid.OUT1" and opener.calls[0]["path"] == f"/{PHONE_ID}/messages"
    assert opener.calls[0]["auth"] == f"Bearer {TOKEN}" and message["to"] == PERSON and message["type"] == "interactive"
    body = message["interactive"]
    assert body["type"] == "button" and body["body"]["text"] == "*Plan* ready. Approve it?"
    assert [b["reply"] for b in body["action"]["buttons"]] == [{"id": "7:approve", "title": "Approve"},
                                                                {"id": "7:reject", "title": "Reject"},
                                                                {"id": "7:later", "title": "Later"}]
    assert "context" not in message and message["messaging_product"] == "whatsapp"


def test_button_titles_are_cut_to_20_characters_and_there_are_at_most_three_buttons(tmp_path):
    sender, opener, _, _ = opened(tmp_path)
    c = card(n=3)
    c["actions"][0]["label"] = "A very long label that does not fit"
    sender.send(PERSON, c)
    titles = [b["reply"]["title"] for b in opener.sent()[0]["interactive"]["action"]["buttons"]]
    assert titles[0] == "A very long label th" and all(len(t) <= 20 for t in titles)
    with pytest.raises(wc.ProviderError) as e:
        wc.check_message(dict(card(n=3), actions=card(n=3)["actions"] + [{"id": "x", "label": "Four"}]))
    assert e.value.kind == "usage" and e.value.code == 2


def test_a_long_card_is_a_text_message_then_the_buttons_as_a_reply_and_the_answer_is_the_texts_id(tmp_path):
    sender, opener, _, _ = opened(tmp_path)
    text = "Detailed plan. " * 100          # 1500 characters: over the 1024 of a button message's body
    wamid = sender.send(PERSON, card(text))
    first, second = opener.sent()
    assert wamid == "wamid.OUT1" and first["type"] == "text" and first["text"] == {"body": text, "preview_url": False}
    assert second["type"] == "interactive" and second["context"] == {"message_id": "wamid.OUT1"}
    assert second["interactive"]["body"]["text"] == wc.BUTTONS_LINE
    assert [b["reply"]["id"] for b in second["interactive"]["action"]["buttons"]] == ["7:approve", "7:reject"]


def test_the_choice_between_one_message_and_two_is_made_on_the_rendered_text(tmp_path):
    sender, opener, _, _ = opened(tmp_path)
    shrinks = "**x** " * 190                    # 1140 raw characters, 760 once rendered: one message
    assert len(shrinks) > 1024 and len(wc.render_whatsapp_cloud(shrinks)) < 1024
    sender.send(PERSON, card(shrinks))
    assert len(opener.sent()) == 1
    grows = "[a](https://example.com/abcdefghij) " * 30      # 1080 raw, longer once rendered
    assert len(grows) > 1024
    opener.calls.clear()
    sender.send(PERSON, card(grows))
    assert [m["type"] for m in opener.sent()] == ["text", "interactive"]
    exact = "x" * 1024
    opener.calls.clear()
    sender.send(PERSON, card(exact))
    assert [m["type"] for m in opener.sent()] == ["interactive"]
    opener.calls.clear()
    sender.send(PERSON, card("x" * 1025))
    assert [m["type"] for m in opener.sent()] == ["text", "interactive"]


def test_text_without_actions_is_a_text_message_rendered_with_no_link_preview_and_a_reply_context(tmp_path):
    sender, opener, _, _ = opened(tmp_path)
    sender.send(PERSON, plain("See **this** [page](https://example.com/p)"))
    sender.send(PERSON, plain("an answer", reply_to="wamid.Q"))
    first, second = opener.sent()
    assert first["text"] == {"body": "See *this* page (https://example.com/p)", "preview_url": False} and "context" not in first
    assert second["context"] == {"message_id": "wamid.Q"} and second["text"]["preview_url"] is False
    assert all(m["recipient_type"] == "individual" for m in opener.sent())


def test_a_document_is_uploaded_then_sent_as_a_reply_to_the_text_and_the_answer_is_the_texts_id(tmp_path):
    sender, opener, _, _ = opened(tmp_path)
    wamid = sender.send(PERSON, plain("The plan", document={"name": "plan 1/2.md", "text": "# Plan\nbody"}))
    assert wamid == "wamid.OUT1"
    assert [c["path"].rsplit("/", 1)[1] for c in opener.calls] == ["messages", "media", "messages"]
    upload = opener.calls[1]
    assert upload["content_type"].startswith("multipart/form-data; boundary=")
    raw = upload["body"].decode()
    assert 'name="messaging_product"\r\n\r\nwhatsapp' in raw and 'name="type"\r\n\r\ntext/plain' in raw
    assert 'filename="plan_1_2.md"' in raw and "# Plan\nbody" in raw
    document = opener.sent()[1]
    assert document["type"] == "document" and document["document"] == {"id": "media.2", "filename": "plan_1_2.md"}
    assert document["context"] == {"message_id": "wamid.OUT1"}


def test_a_card_with_a_document_sends_the_card_then_the_document_as_replies(tmp_path):
    sender, opener, _, _ = opened(tmp_path)
    sender.send(PERSON, card(document={"name": "decision", "text": "full text"}))
    assert [m["type"] for m in opener.sent()] == ["interactive", "document"]
    assert opener.sent()[1]["document"]["filename"] == "decision.txt"
    assert opener.sent()[1]["context"] == {"message_id": "wamid.OUT1"}


def test_a_part_after_the_text_that_fails_is_logged_by_class_and_the_send_still_answers_ok(tmp_path):
    logs = []
    opener = Opener([("POST /109876543210001/media", lambda c: http_error(500))])
    sender, _, _, _ = opened(tmp_path, opener=opener, logs=logs)
    assert sender.send(PERSON, plain("text", document={"name": "d.txt", "text": "x"})) == "wamid.OUT1"
    assert any("document after the text could not be sent (500, None)" in line for line in logs)
    opener2 = Opener([("messages", lambda c: http_error(400, 131009) if c["body"]["type"] == "interactive" and c["body"]["interactive"]["body"]["text"] == wc.BUTTONS_LINE else None)])
    sender, _, _, _ = opened(tmp_path, opener=opener2, folder="t", logs=logs)
    assert sender.send(PERSON, card("y" * 2000)) == "wamid.OUT1"       # the buttons message failed; the text is delivered
    assert any("buttons after the text could not be sent (400, 131009)" in line for line in logs)
    opener3 = Opener([("media", lambda c: http_error(401, 190))])
    sender, _, _, _ = opened(tmp_path, opener=opener3, folder="u")
    with pytest.raises(wc.GraphError) as e:                              # a refused token is never swallowed
        sender.send(PERSON, plain("text", document={"name": "d.txt", "text": "x"}))
    assert e.value.kind == "not-configured"


def test_a_failure_of_the_first_message_is_raised(tmp_path):
    opener = Opener([("messages", lambda c: http_error(400, 131026))])
    sender, _, _, _ = opened(tmp_path, opener=opener)
    with pytest.raises(wc.GraphError) as e:
        sender.send(PERSON, plain("x"))
    assert e.value.error_code == 131026 and e.value.kind == "failed" and "planted-answer-text" not in str(e.value)


@pytest.mark.parametrize("bad,why", [
    (plain(""), "needs a text"), (plain("   "), "needs a text"), (plain("x" * 4097), "4096"),
    ({"text": "x", "actions": "no"}, "at most 3"), (dict(card(), actions=[{"id": "", "label": "a"}]), "action is"),
    (dict(card(), actions=[{"id": "a" * 257, "label": "a"}]), "256"), (dict(card(), actions=[{"id": "a", "label": " "}]), "action is"),
    (dict(plain("x"), link={"label": "l", "url": "https://example.com"}), "no link buttons"),
    (dict(plain("x"), document={"name": "d", "text": ""}), "document"), (dict(plain("x"), document="x"), "document"),
    (dict(plain("x"), reply_to=5), "reply_to"), ("not an object", "JSON object"),
])
def test_a_message_beyond_the_capabilities_is_a_usage_error(bad, why):
    with pytest.raises(wc.ProviderError) as e:
        wc.check_message(bad)
    assert e.value.kind == "usage" and e.value.code == 2 and why in str(e.value)


def test_a_chat_that_is_only_a_business_scoped_id_is_sent_to_the_remembered_digits_else_it_fails(tmp_path):
    sender, opener, store, clock = make_sender(tmp_path)
    store.note_inbound(BSUID, clock() - 60)
    with pytest.raises(wc.ProviderError) as e:
        sender.send(BSUID, plain("x"))
    assert e.value.kind == "failed" and opener.calls == [] and PERSON not in str(e.value)
    store.remember(BSUID, PERSON)               # learned: the window recorded under the id moves to the number
    sender.send(BSUID, plain("x"))
    assert opener.sent()[0]["to"] == PERSON
    for junk in ("", "+5511900000000", "55 11", "a" * 100, "5511900000000\n"):
        with pytest.raises(wc.ProviderError):
            sender.send(junk, plain("x"))


# --- 6. outside the window: the template ------------------------------------------------------------------------------------


def template_calls(opener):
    return opener.of_type("template")


def test_with_no_message_from_the_person_the_template_goes_out_once_and_the_answer_is_deferred(tmp_path):
    sender, opener, store, clock = make_sender(tmp_path)
    with pytest.raises(wc.Deferred) as e:
        sender.send(PERSON, card())
    assert "24-hour window" in e.value.reason and "reminder was sent" in e.value.reason
    [template] = template_calls(opener)
    assert template["template"] == {"name": "decisions_waiting", "language": {"code": "pt_BR"}}, "no variable, no component, no project text"
    assert template["to"] == PERSON and set(template) == {"messaging_product", "recipient_type", "to", "type", "template"}
    assert len(opener.sent()) == 1, "the card itself is not sent"
    for _ in range(5):
        with pytest.raises(wc.Deferred) as again:
            sender.send(PERSON, card())
    assert len(template_calls(opener)) == 1 and "already" in again.value.reason


def test_the_template_mark_survives_a_restart_and_a_week_later_it_is_sent_again_at_most_once_a_week(tmp_path):
    sender, opener, store, clock = make_sender(tmp_path)
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, card())
    sender2, opener2, store2, _ = make_sender(tmp_path, clock=clock)         # a restart: the same folder
    assert store2.entry(PERSON)[1] == clock()
    with pytest.raises(wc.Deferred):
        sender2.send(PERSON, card())
    assert template_calls(opener2) == []
    clock.now += 7 * DAY - 1
    with pytest.raises(wc.Deferred):
        sender2.send(PERSON, card())
    assert template_calls(opener2) == []
    clock.now += 2
    with pytest.raises(wc.Deferred):
        sender2.send(PERSON, card())
    assert len(template_calls(opener2)) == 1
    with pytest.raises(wc.Deferred):
        sender2.send(PERSON, card())
    assert len(template_calls(opener2)) == 1, "and not again the next minute"
    assert json.load(open(tmp_path / "s" / wc.WINDOW))[PERSON]["template_sent_at"] == clock.now


def test_the_gate_is_23_hours_30_minutes_from_the_last_message_and_each_closed_window_gets_one_template(tmp_path):
    sender, opener, store, clock = make_sender(tmp_path)
    store.note_inbound(PERSON, NOW)
    clock.now = NOW + 23 * HOUR + 29 * 60
    sender.send(PERSON, plain("still open"))
    assert len(opener.sent()) == 1
    clock.now = NOW + 23 * HOUR + 31 * 60
    for _ in range(3):
        with pytest.raises(wc.Deferred):
            sender.send(PERSON, plain("closed"))
    assert len(template_calls(opener)) == 1
    clock.now = NOW + 40 * HOUR
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, plain("closed"))
    assert len(template_calls(opener)) == 1, "the same closed window"
    store.note_inbound(PERSON, clock.now)                                   # the person writes again: a new window
    sender.send(PERSON, plain("open again"))
    clock.now += 25 * HOUR
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, plain("closed again"))
    assert len(template_calls(opener)) == 2, "one for each closed window"


def test_error_131047_on_the_first_message_closes_the_window_sends_the_template_once_and_defers(tmp_path):
    opener = Opener([("messages", lambda c: http_error(400, 131047) if c["body"]["type"] != "template" else None)])
    sender, _, store, clock = opened(tmp_path, opener=opener)
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, card())
    assert len(template_calls(opener)) == 1 and not store.window_open(PERSON, clock())
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, card())
    assert len(template_calls(opener)) == 1, "the second try is deferred by the local window, with no API call and no template"
    assert len(opener.sent()) == 2


def test_a_late_131047_report_closes_the_window_and_sends_the_template_for_a_message_this_process_sent(tmp_path):
    sender, opener, store, clock = opened(tmp_path)
    wamid = sender.send(PERSON, card())
    sender.late_failure("wamid.UNKNOWN")
    assert template_calls(opener) == [] and store.window_open(PERSON, clock())
    clock.now += 60
    sender.late_failure(wamid)
    sender.late_failure(wamid)               # Meta may repeat the status
    assert len(template_calls(opener)) == 1 and not store.window_open(PERSON, clock())


def test_a_late_report_for_a_message_older_than_the_latest_message_of_the_person_is_ignored(tmp_path):
    sender, opener, store, clock = opened(tmp_path)
    wamid = sender.send(PERSON, plain("x"))
    clock.now += 10
    store.note_inbound(PERSON, clock.now)    # the person wrote after it: the window is open again
    sender.late_failure(wamid)
    assert template_calls(opener) == [] and store.window_open(PERSON, clock.now)


def test_a_template_that_fails_is_not_marked_and_is_tried_again_and_a_refused_token_is_raised(tmp_path):
    logs = []
    state = {"fail": True}
    opener = Opener([("messages", lambda c: http_error(400, 132001) if state["fail"] else None)])
    sender, _, store, clock = make_sender(tmp_path, opener=opener, logs=logs)
    with pytest.raises(wc.Deferred) as e:
        sender.send(PERSON, card())
    assert "could not be sent" in e.value.reason and store.entry(PERSON)[1] == 0 and any("132001" in l for l in logs)
    state["fail"] = False
    with pytest.raises(wc.Deferred):
        sender.send(PERSON, card())
    assert len(template_calls(opener)) == 2 and store.entry(PERSON)[1] == clock()
    sender2, _, _, _ = make_sender(tmp_path, opener=Opener([("messages", lambda c: http_error(401, 190))]), folder="x")
    with pytest.raises(wc.GraphError) as g:
        sender2.send(PERSON, card())
    assert g.value.kind == "not-configured"


def test_nothing_is_sent_to_a_chat_that_is_not_digits_even_to_remind(tmp_path):
    sender, opener, _, _ = make_sender(tmp_path)
    with pytest.raises(wc.ProviderError):
        sender.send(BSUID, card())
    assert opener.calls == []


# --- the listener: ready, answers, exit codes --------------------------------------------------------------------------------


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(start=True, **kw):
        r = Rig(tmp_path / f"r{len(made)}", **kw)
        made.append(r)
        return r.start() if start else r
    yield make
    for r in made:
        if r.thread.is_alive():
            r.stop()


def write_to_the_bot(r, at=None):
    r.post(envelope([text_message(at=at if at is not None else r.clock())]))


def test_ready_comes_after_the_server_listens_and_the_token_works_and_the_check_uses_the_token(rig):
    r = rig()
    [check] = [c for c in r.opener.calls if c["method"] == "GET"]
    assert check["path"] == f"/{PHONE_ID}?fields=id" and check["auth"] == f"Bearer {TOKEN}" and check["timeout"] <= 10
    assert r.out.events("ready") == [{"event": "ready"}] and r.listener.server.server_address == ("127.0.0.1", r.port)


def test_the_server_listens_while_the_token_is_still_being_checked(tmp_path):
    release = threading.Event()
    r = Rig(tmp_path / "w", opener=Opener([("GET", lambda c: release.wait(10) and None)])).start(ready=False)
    try:
        assert kit.wait_for(lambda: r.listener.port, 5)
        assert r.request("GET", "/nothing")[0] == 404, "Meta's handshake could already be answered"
        assert r.out.events("ready") == []
        release.set()
        assert kit.wait_for(lambda: r.out.events("ready"), 5)
    finally:
        release.set()
        r.stop()


@pytest.mark.parametrize("error,exit_code,kind", [
    (http_error(401, 190), 3, "not-configured"), (http_error(401, None), 3, "not-configured"), (http_error(400, 0), 3, "not-configured"),
    (http_error(400, 100), 3, "not-configured"), (http_error(403, 10), 3, "not-configured"),
    (urllib.error.URLError("dns planted-host-name"), 1, "failed"), (http_error(500, None), 1, "failed"),
    (http_error(429, 4), 1, "failed"), (TimeoutError("slow"), 1, "failed"),
])
def test_a_refused_token_is_exit_3_with_the_error_event_and_a_network_problem_is_exit_1(tmp_path, error, exit_code, kind):
    r = Rig(tmp_path / "e", opener=Opener([("GET", error)])).start(ready=False)
    assert kit.wait_for(lambda: not r.thread.is_alive(), 5)
    assert r.result == [exit_code] and r.out.events("ready") == []
    [event] = r.out.events("error")
    assert event["kind"] == kind and "planted" not in json.dumps(r.out.lines) and TOKEN not in json.dumps(r.out.lines)
    r.pipe.close()


def test_a_port_that_is_taken_is_not_configured_with_a_sentence_that_names_setup(tmp_path):
    first = Rig(tmp_path / "p1").start()
    try:
        taken = settings(port=first.port)
        listener = wc.Listener(taken, dict(kit.SECRETS), wc.Store(None), out=kit.Capture(), stdin=kit.Pipe().reader,
                               graph=wc.Graph(TOKEN, PHONE_ID, opener=Opener()), log=lambda t: None)
        assert listener.run() == 3
        [event] = listener.out.events("error")
        assert event["kind"] == "not-configured" and "setup" in event["reason"]
    finally:
        first.stop()


def test_a_send_inside_the_window_is_answered_ok_with_the_message_id(rig):
    r = rig()
    write_to_the_bot(r)
    answer = r.ask(1, PERSON, card("Plan"))
    assert answer == {"id": 1, "ok": True, "message_id": "wamid.OUT2"}, "the id 1 was the token check's GET, which has no wamid"
    assert r.stop() == 0


def test_outside_the_window_the_answer_is_deferred_with_a_reason_and_the_template_goes_once(rig):
    r = rig()
    first = r.ask(1, PERSON, card())
    assert first["ok"] is False and first["kind"] == "deferred" and "24-hour window" in first["reason"]
    second = r.ask(2, PERSON, card())
    assert second["kind"] == "deferred" and len(r.opener.of_type("template")) == 1
    write_to_the_bot(r)                      # the person writes: the same card now goes out
    assert r.ask(3, PERSON, card())["ok"] is True
    assert r.stop() == 0


def test_a_late_131047_status_through_the_webhook_closes_the_window_and_the_card_is_deferred_after_it(rig):
    r = rig()
    write_to_the_bot(r)
    sent = r.ask(1, PERSON, card())
    assert sent["ok"] is True
    r.clock.now += 5
    r.post(envelope(statuses=[{"id": sent["message_id"], "status": "failed", "recipient_id": PERSON,
                               "errors": [{"code": 131047, "title": "Re-engagement message"}]}]))
    assert kit.wait_for(lambda: r.opener.of_type("template"), 5)
    again = r.ask(2, PERSON, card())
    assert again["kind"] == "deferred" and len(r.opener.of_type("template")) == 1


def test_a_rejected_token_during_a_send_answers_not_configured_writes_the_error_event_and_exits_3(rig):
    r = rig(opener=Opener([("messages", lambda c: http_error(401, 190))]))
    write_to_the_bot(r)
    answer = r.ask(1, PERSON, plain("x"))
    assert answer["kind"] == "not-configured" and answer["ok"] is False
    assert kit.wait_for(lambda: r.out.events("error"), 5) and r.out.events("error")[0]["kind"] == "not-configured"
    r.thread.join(5)
    assert r.result == [3]
    r.pipe.close()


@pytest.mark.parametrize("code", [190, 0])
def test_error_0_is_handled_like_190(rig, code):
    r = rig(opener=Opener([("messages", lambda c: http_error(400, code))]))
    write_to_the_bot(r)
    assert r.ask(1, PERSON, plain("x"))["kind"] == "not-configured"
    r.thread.join(5)
    assert r.result == [3]
    r.pipe.close()


@pytest.mark.parametrize("code", [130429, 131056])
def test_a_rate_limit_is_failed_with_a_short_wait_before_the_next_send(rig, code):
    r = rig(opener=Opener([("messages", lambda c: http_error(429, code))]), rate_wait=0.5)
    write_to_the_bot(r)
    start = time.monotonic()
    first = r.ask(1, PERSON, plain("x"))
    assert first["kind"] == "failed" and str(code) in first["reason"] and "planted-answer-text" not in first["reason"]
    r.opener.rules.clear()
    second = r.ask(2, PERSON, plain("y"))
    assert second["ok"] is True and time.monotonic() - start >= 0.45, "the worker waited before the next request"
    assert r.stop() == 0


def test_other_errors_are_failed_with_the_code_and_never_the_body(rig):
    r = rig(opener=Opener([("messages", lambda c: http_error(400, 131026, "the phone number 5511900000000 is secret"))]))
    write_to_the_bot(r)
    answer = r.ask(1, PERSON, plain("x"))
    assert answer["kind"] == "failed" and "131026" in answer["reason"] and "secret" not in answer["reason"] and PERSON not in answer["reason"]
    r.opener.rules[:] = [("messages", urllib.error.URLError("connection refused for planted-host"))]
    answer = r.ask(2, PERSON, plain("x"))
    assert answer["kind"] == "failed" and "planted-host" not in answer["reason"] and "could not be reached" in answer["reason"]
    assert r.stop() == 0


def test_bad_requests_are_answered_usage_or_dropped_and_nothing_stops(rig):
    r = rig()
    write_to_the_bot(r)
    r.pipe.writer.write(b"not json\n")
    r.pipe.send({"op": "send", "chat": PERSON, "message": plain("x")})          # no id: dropped
    r.pipe.send({"id": 5, "op": "ack", "chat": PERSON})
    r.pipe.send({"id": 6, "op": "send", "chat": 42, "message": plain("x")})
    r.pipe.send({"id": 7, "op": "send", "chat": PERSON, "message": {"text": "x", "actions": [{}] * 5}})
    assert kit.wait_for(lambda: len(r.out.answers()) == 3, 5)
    assert [(a["id"], a["kind"]) for a in r.out.answers()] == [(5, "usage"), (6, "usage"), (7, "usage")]
    assert r.ask(8, PERSON, plain("fine"))["ok"] is True
    assert r.stop() == 0


def test_a_request_line_over_one_mebibyte_is_dropped_and_the_next_one_is_served(rig):
    r = rig()
    write_to_the_bot(r)
    r.pipe.writer.write(b"x" * (1 << 20) + b"yy\n")
    assert r.ask(1, PERSON, plain("after"))["ok"] is True
    assert any("over 1 MiB" in l for l in r.logs) and r.stop() == 0


def test_the_end_of_stdin_ends_the_process_within_five_seconds_even_with_a_graph_call_in_flight(tmp_path):
    release = threading.Event()
    hang = Opener([("POST", lambda c: release.wait(30) and None)])
    r = Rig(tmp_path / "h", opener=hang).start()
    try:
        write_to_the_bot(r)
        r.pipe.send({"id": 1, "op": "send", "chat": PERSON, "message": plain("x")})
        assert kit.wait_for(lambda: len(hang.sent()) >= 1 or hang.count >= 2, 5)
        start = time.monotonic()
        r.pipe.close()
        r.thread.join(5)
        assert not r.thread.is_alive() and time.monotonic() - start < 4 and r.result == [0]
    finally:
        release.set()


def test_the_secrets_never_reach_the_protocol_or_the_logs_on_any_error_path(rig, capfd):
    r = rig(opener=Opener([("messages", lambda c: http_error(400, 131026, f"token {TOKEN} and {kit.APP_SECRET} and {PERSON}"))]))
    write_to_the_bot(r)
    r.ask(1, PERSON, plain(TEXT))
    r.post(envelope([text_message("wamid.Z")]), secret="wrong")
    r.stop()
    everything = json.dumps(r.out.lines) + "\n".join(r.logs) + "".join(capfd.readouterr())
    for secret in (TOKEN, kit.APP_SECRET, kit.VERIFY, kit.PATH):
        assert secret not in everything
    assert wc.redact(f"x {TOKEN} y", [TOKEN]) == "x <secret> y"
    assert wc.redact("call 5511900000000 error 131047") == "call <digits> error 131047"


def test_button_titles_are_stripped_never_empty_and_different_from_one_another():
    acts = lambda *labels: [{"id": str(i), "label": l} for i, l in enumerate(labels)]
    same = wc.button_titles(acts("Approve this long label A", "Approve this long label B", "Approve this long label C"))
    assert same == ["Approve this long la", "Approve this long 2", "Approve this long 3"] and all(0 < len(t) <= 20 for t in same)
    assert wc.button_titles(acts("Yes", "yes", "YES")) == ["Yes", "yes 2", "YES 3"]
    assert wc.button_titles(acts(" " * 20 + "late", "ok")) == ["late", "ok"]       # spaces are collapsed before the cut
    assert wc.button_titles(acts(chr(0xA0) * 3, "ok")) == ["Option 1", "ok"]
    assert wc.button_titles(acts("  padded   words  ")) == ["padded words"]
    sender_body = wc.buttons_body(PERSON, "x", acts("Same", "Same"))
    assert [b["reply"]["title"] for b in sender_body["interactive"]["action"]["buttons"]] == ["Same", "Same 2"]


def test_the_webhook_answers_503_until_the_token_check_has_passed_and_marks_nothing_seen(tmp_path):
    release = threading.Event()
    r = Rig(tmp_path / "n", opener=Opener([("GET", lambda c: release.wait(10) and None)])).start(ready=False)
    try:
        assert kit.wait_for(lambda: r.listener.port, 5)
        assert r.post(envelope([text_message()]))[0] == 503
        assert r.out.updates() == [] and r.store.seen == {}
        release.set()
        assert kit.wait_for(lambda: r.out.events("ready"), 5)
        assert r.post(envelope([text_message()]))[0] == 200 and len(r.out.updates()) == 1
    finally:
        release.set()
        r.stop()


def test_the_state_is_pruned_once_a_day_while_running(tmp_path):
    r = Rig(tmp_path / "pr", prune_every=0.2).start()
    try:
        r.store.mark_seen("wamid.OLD")
        r.store.remember("BR.old000000000000", "551100000009")
        r.clock.now += 40 * DAY                       # forty days later, nothing renewed it
        assert kit.wait_for(lambda: "wamid.OLD" not in r.store.seen and not r.store.identities, 5)
        assert json.load(open(r.folder + "/" + wc.SEEN)) == {} and json.load(open(r.folder + "/" + wc.IDENTITIES)) == {}
    finally:
        r.stop()
