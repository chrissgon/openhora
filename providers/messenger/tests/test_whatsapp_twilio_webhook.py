"""Offline tests of the webhook side of providers/messenger/whatsapp-twilio.py: Twilio's signature (with the published test
vector), the empty TwiML answer, the filters (account, number, duplicates, status callbacks), the mapping of a message, a tap, a
reply and a business-scoped id, and the limits of the server. A local HTTP client against the provider's server on port 0.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_twilio_webhook.py
"""
from __future__ import annotations

import http.client
import os
import socket
import threading

import pytest

import whatsapp_twilio_kit as kit
from whatsapp_twilio_kit import (ACCOUNT, AUTH, BSUID, FROM, KEY_SECRET, NOW, OTHER_ACCOUNT, PATH, PERSON, PUBLIC_URL, SENDER, TEXT,
                                 card_tap, inbound, sid, status_report, wt)


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(**kw):
        r = kit.Rig(tmp_path, **kw).start()
        made.append(r)
        return r
    yield make
    for r in made:
        if r.thread.is_alive():
            r.stop()


# --- the signature -------------------------------------------------------------------------------------------------------------

VECTOR_URL = "https://mycompany.com/myapp.php?foo=1&bar=2"
VECTOR = [("CallSid", "CA1234567890ABCDE"), ("Caller", "+14158675309"), ("Digits", "1234"), ("From", "+14158675309"),
          ("To", "+18005551212")]


def test_the_provider_reproduces_twilios_published_test_vector():
    assert wt.compute_signature("12345", VECTOR_URL, VECTOR) == "RSOYDt4T1cUTdK1PDd93/VVr8B8="
    assert kit.reference_signature("12345", VECTOR_URL, VECTOR) == "RSOYDt4T1cUTdK1PDd93/VVr8B8="
    assert wt.signature_ok("12345", VECTOR_URL, VECTOR, "RSOYDt4T1cUTdK1PDd93/VVr8B8=")
    assert not wt.signature_ok("12345", VECTOR_URL, VECTOR, "RSOYDt4T1cUTdK1PDd93/VVr8B8")
    assert not wt.signature_ok("123456", VECTOR_URL, VECTOR, "RSOYDt4T1cUTdK1PDd93/VVr8B8=")
    assert not wt.signature_ok("12345", VECTOR_URL, VECTOR, None) and not wt.signature_ok("12345", VECTOR_URL, VECTOR, "")


def test_the_signature_is_the_validators_not_just_self_consistent():
    # the sorted names, a repeated pair counted once, different values of a name each counted, in sorted order
    once = wt.compute_signature("12345", VECTOR_URL, VECTOR)
    assert wt.compute_signature("12345", VECTOR_URL, VECTOR + [("Digits", "1234")]) == once
    assert wt.compute_signature("12345", VECTOR_URL, list(reversed(VECTOR))) == once
    two = VECTOR + [("Digits", "5678")]
    assert wt.compute_signature("12345", VECTOR_URL, two) != once
    assert wt.compute_signature("12345", VECTOR_URL, two) == wt.compute_signature("12345", VECTOR_URL, list(reversed(two)))
    for pairs in (two, [("a", ""), ("a", "b"), ("b", "x\u00e9\u65e5"), ("A", "z")], []):
        assert wt.compute_signature(kit.AUTH, VECTOR_URL, pairs) == kit.reference_signature(kit.AUTH, VECTOR_URL, pairs)


def test_the_url_is_accepted_with_and_without_the_default_port_and_as_received_with_its_query():
    url = "https://box.tail1234.ts.net/" + PATH
    with_port = "https://box.tail1234.ts.net:443/" + PATH
    for signed in (url, with_port):
        assert wt.signature_ok(AUTH, url, VECTOR, kit.reference_signature(AUTH, signed, VECTOR))
        assert wt.signature_ok(AUTH, with_port, VECTOR, kit.reference_signature(AUTH, signed, VECTOR))
    assert not wt.signature_ok(AUTH, url, VECTOR, kit.reference_signature(AUTH, "https://box.tail1234.ts.net:8443/" + PATH, VECTOR))
    assert not wt.signature_ok(AUTH, url, VECTOR, kit.reference_signature(AUTH, "http://box.tail1234.ts.net/" + PATH, VECTOR))
    assert wt.url_forms("https://h.example/p?x=1&y=%20") == ["https://h.example/p?x=1&y=%20", "https://h.example:443/p?x=1&y=%20"]


def test_a_valid_call_is_processed_and_answered_with_an_empty_twiml_response(rig):
    r = rig()
    status, body, head = r.post(inbound())
    assert status == 200 and body.startswith(b"<?xml") and body.endswith(b"<Response/>")
    assert head["Content-Type"].startswith("text/xml") and head["Cache-Control"] == "no-store"
    assert [u["text"] for u in r.out.updates()] == [TEXT]


@pytest.mark.parametrize("how", ["missing", "wrong", "token", "url", "host", "scheme", "query", "body", "empty", "latin1"])
def test_a_missing_or_wrong_signature_is_a_403_and_nothing_is_processed(rig, how):
    r = rig()
    fields = inbound()
    pairs = kit.as_pairs(fields)
    good = kit.reference_signature(AUTH, PUBLIC_URL, pairs)
    if how == "missing":
        status = r.request("POST", "/" + PATH, kit.form_body(pairs), {"Content-Type": "application/x-www-form-urlencoded"})[0]
    elif how == "wrong":
        status = r.post(fields, header=good[:-2] + "AA")[0]
    elif how == "token":
        status = r.post(fields, token=KEY_SECRET)[0]            # signed with the API key secret instead of the Auth Token
    elif how == "url":
        status = r.post(fields, url=PUBLIC_URL + "x")[0]
    elif how == "host":
        status = r.post(fields, url=PUBLIC_URL.replace("northwind-laptop", "other-laptop"))[0]
    elif how == "scheme":
        status = r.post(fields, url=PUBLIC_URL.replace("https", "http"))[0]
    elif how == "query":
        status = r.post(fields, query="a=b", url=PUBLIC_URL)[0]          # signed without the query that was sent
    elif how == "body":
        status = r.post(fields, raw=kit.form_body(pairs + [("Extra", "1")]), header=good)[0]
    elif how == "empty":
        status = r.post(fields, header="")[0]
    else:
        status = r.post(fields, header="\u00e9\u00e8" * 14)[0]                # a header outside ASCII compares safely
    assert status == 403
    assert r.out.updates() == []
    assert wt.Store(r.folder).is_seen(sid(1)) is False


def test_non_ascii_values_are_signed_over_their_utf8_bytes(rig):
    r = rig()
    body = "ol\u00e1, voc\u00ea n\u00e3o viu \u65e5\u672c\u8a9e \U0001F600"
    status = r.post(inbound(body=body, ProfileName="Jo\u00e3o"))[0]
    assert status == 200 and r.out.updates()[0]["text"] == body
    assert r.post(inbound(2, body=body), header=kit.reference_signature(AUTH, PUBLIC_URL, [("Body", body.encode().decode("latin-1"))]))[0] == 403


def test_a_body_that_is_not_utf8_or_has_too_many_fields_is_refused_before_anything_is_read(rig):
    r = rig()
    assert r.post(raw=b"Body=\xff\xfe&From=x", header="AAAA")[0] == 403
    many = "&".join(f"k{i}=v" for i in range(wt.MAX_FIELDS + 5)).encode()
    assert r.post(raw=many, header="AAAA")[0] == 403
    assert r.out.updates() == []


def test_a_repeated_pair_signs_like_the_single_pair_and_a_changed_value_does_not(rig):
    r = rig()
    pairs = kit.as_pairs(inbound())
    sig = kit.reference_signature(AUTH, PUBLIC_URL, pairs)
    assert r.post(raw=kit.form_body(pairs + [("Body", TEXT)]), header=sig)[0] == 200       # the validator drops the repeated pair
    assert r.post(raw=kit.form_body(inbound(2, body="changed")), header=kit.reference_signature(AUTH, PUBLIC_URL, pairs))[0] == 403


def test_the_url_with_the_default_port_is_accepted_as_twilios_validator_does(rig):
    r = rig()
    fields = inbound()
    assert r.post(fields, url=PUBLIC_URL.replace(kit.HOST, kit.HOST + ":443"))[0] == 200


def test_the_query_is_part_of_the_signed_url_as_received(rig):
    r = rig()
    # an unknown query that is signed is accepted as a call and ignored (200) and never read as a message
    assert r.post(inbound(), query="other=1")[0] == 200
    assert r.out.updates() == []
    assert r.post(inbound(), query="status=1")[0] == 200            # a status call with a message's fields: not a message
    assert r.out.updates() == []


# --- the server's limits ------------------------------------------------------------------------------------------------------------


def test_get_is_405_with_allow_post_and_another_path_or_method_is_404_or_405(rig):
    r = rig()
    status, _, head = r.request("GET", "/" + PATH)
    assert status == 405 and head["Allow"] == "POST"
    assert r.request("GET", "/" + PATH + "?hub.mode=subscribe")[0] == 405
    assert r.request("POST", "/elsewhere", b"a=b", {"Content-Length": "3"})[0] == 404
    assert r.request("PUT", "/" + PATH, b"a=b")[0] == 405
    assert r.request("DELETE", "/nowhere")[0] == 404
    assert r.request("POST", "/" + PATH + "%2f", b"a=b")[0] == 404 and r.request("POST", "/" + PATH + ";x", b"a=b")[0] == 404


def test_a_body_without_a_length_or_over_the_cap_is_refused_before_it_is_read(rig):
    r = rig()
    conn = http.client.HTTPConnection("127.0.0.1", r.port, timeout=5)
    conn.putrequest("POST", "/" + PATH)
    conn.putheader("Transfer-Encoding", "chunked")
    conn.endheaders()
    assert conn.getresponse().status == 411
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", r.port, timeout=5)
    conn.putrequest("POST", "/" + PATH)
    conn.putheader("Content-Length", str(wt.MAX_FORM_BODY + 1))
    conn.endheaders()
    assert conn.getresponse().status == 413
    conn.close()
    assert r.out.updates() == []


def test_the_server_binds_127_0_0_1_only_and_logs_nothing_from_a_request(rig):
    r = rig()
    assert r.listener.server.server_address[0] == "127.0.0.1" and wt.LOOPBACK == "127.0.0.1"
    r.post(inbound(), header="bad")
    r.request("GET", f"/{PATH}?secret=hunter2")
    source = open(kit.SCRIPT, encoding="utf-8").read() + open(kit.SCRIPT.with_name("whatsapp_meta.py"), encoding="utf-8").read()
    assert "0.0.0.0" not in source and "getfqdn" not in source and "compare_digest" in source
    assert wt.Handler.log_message is wt.Handler.log_error is wt.Handler.log_request
    assert "handle_error" in wt.Server.__dict__ and "server_bind" in wt.Server.__dict__
    assert not any(PATH in line or "hunter2" in line or AUTH in line for line in r.logs)


def test_posts_are_503_until_the_listener_is_ready_and_nothing_is_marked_seen(tmp_path):
    hook = wt.Webhook(kit.settings(), dict(kit.SECRETS), wt.Store(None), lambda u, uid=None: pytest.fail("emitted"))
    hook.accepting = False

    class Headers(dict):
        pass
    pairs = kit.as_pairs(inbound())
    head = Headers({"X-Twilio-Signature": kit.reference_signature(AUTH, PUBLIC_URL, pairs)})
    assert hook.handle_post(head, "", kit.form_body(pairs))[0] == 503
    assert hook.store.is_seen(sid(1)) is False


def test_slow_requests_are_bounded_by_the_total_deadline_and_the_handler_count(tmp_path):
    r = kit.Rig(tmp_path, deadline=0.5, limit=2).start()
    try:
        held = []
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", r.port))
            s.sendall(b"POST /" + PATH.encode() + b" HTTP/1.0\r\nContent-Length: 10\r\n\r\nab")
            held.append(s)
        assert kit.wait_for(lambda: r.listener.server.slots._value == 0, 3)
        status = r.request("POST", "/" + PATH, b"a=b", {"Content-Length": "3"})[0]
        assert status == 503
        assert kit.wait_for(lambda: r.listener.server.slots._value == 2, 5)         # the deadline cut the slow ones
        for s in held:
            s.close()
    finally:
        r.stop()


# --- the filters --------------------------------------------------------------------------------------------------------------------


def test_another_account_another_number_a_status_shape_or_no_text_is_ignored(rig):
    r = rig()
    assert r.post(inbound(1, account=OTHER_ACCOUNT))[0] == 200
    assert r.post(inbound(2, to="whatsapp:+14155550199"))[0] == 200
    assert r.post(inbound(3, body="   "))[0] == 200
    assert r.post(inbound(4, body=""))[0] == 200
    assert r.post({k: v for k, v in inbound(5).items() if k != "To"})[0] == 200
    assert r.post({k: v for k, v in inbound(6).items() if k != "AccountSid"})[0] == 200
    assert r.post(inbound(7, NumMedia="1", MediaUrl0="https://api.example/m", Body=""))[0] == 200
    assert r.post(inbound(8, ButtonText="Approve"))[0] == 200                    # a title with no payload is not a tap
    assert r.post(inbound(9, frm="whatsapp:"))[0] == 200 and r.post(inbound(10, frm="tel:+5511900000000"))[0] == 200
    assert r.post(inbound(11, MessageSid="bad sid"))[0] == 200
    assert r.out.updates() == []


def test_a_field_that_arrives_twice_with_different_values_is_never_read(rig):
    r = rig()
    pairs = kit.as_pairs(inbound()) + [("AccountSid", OTHER_ACCOUNT)]
    assert r.post(pairs)[0] == 200
    assert r.out.updates() == []


def test_a_duplicate_message_sid_is_dropped_also_after_a_restart(tmp_path):
    first = kit.Rig(tmp_path).start()
    assert first.post(inbound(1))[0] == 200 and first.post(inbound(1))[0] == 200
    assert len(first.out.updates()) == 1
    first.stop()
    again = kit.Rig(tmp_path).start()
    try:
        assert again.post(inbound(1))[0] == 200
        assert again.out.updates() == []
        assert again.post(inbound(2, body="new"))[0] == 200 and [u["text"] for u in again.out.updates()] == ["new"]
    finally:
        again.stop()


def test_a_failure_to_save_the_seen_ids_is_a_500_and_the_retry_is_deduplicated_in_memory(rig, monkeypatch):
    r = rig()
    real = r.store.save
    monkeypatch.setattr(r.store, "save", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    assert r.post(inbound(1))[0] == 500
    monkeypatch.setattr(r.store, "save", real)
    assert r.post(inbound(1))[0] == 200
    assert len(r.out.updates()) == 1


def test_processing_errors_are_a_500_with_a_class_only_diagnostic(rig, monkeypatch):
    r = rig()
    monkeypatch.setattr(wt.Webhook, "message", lambda self, m: (_ for _ in ()).throw(RuntimeError("boom " + TEXT)))
    assert r.post(inbound(1))[0] == 500
    assert any("RuntimeError" in line for line in r.logs) and not any(TEXT in line for line in r.logs)


# --- the mapping --------------------------------------------------------------------------------------------------------------------


def update_of(r):
    got = r.out.updates()
    assert len(got) == 1, got
    return got[0]


def test_a_text_becomes_an_update_with_the_digits_of_from_as_sender_and_chat(rig):
    r = rig()
    r.post(inbound(1))
    assert update_of(r) == {"update_id": sid(1), "sender": PERSON, "chat": PERSON, "private": True, "text": TEXT, "action": None,
                            "action_ref": None, "reply_to": None}


def test_a_card_button_tap_is_the_action_alone_and_never_the_body(rig):
    r = rig()
    r.post(card_tap(2, "12:approve", "Approve"))
    got = update_of(r)
    assert got["action"] == "12:approve" and got["text"] is None and got["sender"] == PERSON
    assert "Approve" not in str(got.values())


def test_the_templates_quick_reply_is_the_pending_command_and_any_other_payload_is_ignored(rig):
    r = rig()
    r.post(card_tap(2, "see-decisions", "See decisions"))
    got = update_of(r)
    assert got["text"] == "/pending" and got["action"] is None and got["reply_to"] is None
    for n, payload in enumerate(("See decisions", "approve", "7:", "7:Approve", "x" * 200, "7:approve; rm", "../../x"), 10):
        r.post(card_tap(n, payload))
    assert len(r.out.updates()) == 1


def test_the_template_button_id_is_the_one_in_the_settings(tmp_path):
    r = kit.Rig(tmp_path, config={"template_button_id": "ver-decisoes"}).start()
    try:
        r.post(card_tap(2, "see-decisions"))
        assert r.out.updates() == []
        r.post(card_tap(3, "ver-decisoes"))
        assert update_of(r)["text"] == "/pending"
    finally:
        r.stop()


def test_a_reply_carries_the_sid_of_the_message_it_answers(rig):
    r = rig()
    replied = sid(0x77)
    r.post(inbound(1, body="the answer", OriginalRepliedMessageSid=replied))
    assert update_of(r)["reply_to"] == replied
    r.post(inbound(2, body="x", OriginalRepliedMessageSid="not a sid!"))
    assert r.out.updates()[1]["reply_to"] is None


def test_a_person_known_only_by_a_business_scoped_id_is_the_id_until_the_number_is_learned(rig):
    r = rig()
    only = f"whatsapp:{BSUID}"
    r.post(inbound(1, frm=only, WaId=""))
    assert r.out.updates()[0]["sender"] == BSUID and r.out.updates()[0]["chat"] == BSUID
    r.post(inbound(2, frm=only, WaId="not-digits"))                  # WaId is read only when it has the shape of a number
    assert r.out.updates()[1]["chat"] == BSUID
    r.post(inbound(3, frm=FROM, ExternalUserId=BSUID))                # both together: the pair is learned
    assert r.out.updates()[2]["chat"] == PERSON
    r.post(inbound(4, frm=only, WaId=""))
    assert r.out.updates()[3]["chat"] == PERSON                       # now the id alone is the number
    assert r.store.digits_for(BSUID) == PERSON


def test_wa_id_with_digits_is_used_when_from_has_none_and_a_bad_id_is_dropped(rig):
    r = rig()
    r.post(inbound(1, frm=f"whatsapp:{BSUID}", WaId="5511933333333"))
    assert r.out.updates()[0]["chat"] == "5511933333333"
    r.post(inbound(2, frm="whatsapp:bad id with spaces", WaId=""))
    assert len(r.out.updates()) == 1


def test_the_window_clock_is_the_time_of_receipt_and_is_noted_before_the_update_is_emitted(tmp_path):
    seen = []
    r = kit.Rig(tmp_path)
    original = r.listener.emit
    r.listener.emit = lambda update, uid=None: (seen.append(r.store.window_open(update["chat"], NOW)), original(update, uid))
    r.start()
    try:
        r.post(inbound(1))
        assert seen == [True]
        assert r.store.entry(PERSON)[0] == NOW
    finally:
        r.stop()


# --- status callbacks ---------------------------------------------------------------------------------------------------------------


def test_only_error_63016_on_a_sid_this_process_sent_closes_the_window_and_sends_the_template(tmp_path):
    opener = kit.Opener()
    r = kit.Rig(tmp_path, opener=opener).start()
    try:
        r.post(inbound(1))
        done = r.ask(1, PERSON, kit.plain("hello"))
        sent_sid = done["message_id"]
        for report in (status_report(sent_sid, code="30008"), status_report(sent_sid, status="delivered", code=""),
                       status_report(sid(0x99), "63016"), status_report(sent_sid, "63016", account=OTHER_ACCOUNT),
                       status_report(sent_sid, "63016", frm="whatsapp:+14155550199")):
            assert r.status(report)[0] == 200
        assert opener.contents() == []
        assert r.store.window_open(PERSON, NOW)
        assert r.status(status_report(sent_sid, "63016"))[0] == 200
        assert kit.wait_for(lambda: opener.contents())
        assert opener.contents()[0]["ContentSid"] == kit.TEMPLATE and "ContentVariables" not in opener.contents()[0]
        assert not r.store.window_open(PERSON, NOW)
        assert r.status(status_report(sent_sid, "63016"))[0] == 200            # a second report: the template is not sent again
        r.status(status_report(sent_sid, "63016", status="undelivered"))
        assert r.ask(2, PERSON, kit.plain("later"))["kind"] == "deferred"          # the worker has handled the reports before this
        assert len(opener.contents()) == 1
    finally:
        r.stop()


def test_a_63016_report_after_a_restart_still_matches_because_the_sids_are_persisted(tmp_path):
    opener = kit.Opener()
    first = kit.Rig(tmp_path, opener=opener).start()
    first.post(inbound(1))
    sent_sid = first.ask(1, PERSON, kit.plain("hello"))["message_id"]
    first.stop()
    assert os.path.exists(os.path.join(first.folder, "sent.json"))
    assert oct(os.stat(os.path.join(first.folder, "sent.json")).st_mode & 0o777) == "0o600"
    second = kit.Rig(tmp_path, opener=opener).start()
    try:
        assert second.status(status_report(sent_sid, "63016"))[0] == 200
        assert kit.wait_for(lambda: opener.contents())
        assert opener.contents()[0]["ContentSid"] == kit.TEMPLATE
    finally:
        second.stop()


def test_a_person_who_wrote_after_the_message_keeps_the_window_open_on_a_late_report(tmp_path):
    clock = kit.Clock()
    opener = kit.Opener()
    r = kit.Rig(tmp_path, opener=opener, clock=clock).start()
    try:
        r.post(inbound(1))
        sent_sid = r.ask(1, PERSON, kit.plain("hello"))["message_id"]
        clock.now += 60
        r.post(inbound(2, body="again"))
        r.status(status_report(sent_sid, "63016"))
        assert r.ask(2, PERSON, kit.plain("after"))["ok"] is True                   # the worker has handled the report before this
        assert opener.contents() == [] and r.store.window_open(PERSON, clock.now)
    finally:
        r.stop()
