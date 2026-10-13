"""Offline tests of the webhook server of providers/messenger/whatsapp-cloud.py: the handshake, the signature on the raw bytes,
the limits of a request, the filter and the mapping of what Meta sends. A local HTTP client talks to the provider's server on
127.0.0.1 (port 0); the Graph API is a fake opener. No network, no Meta, no Funnel.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_cloud_webhook.py
"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

import whatsapp_cloud_kit as kit
from whatsapp_cloud_kit import (APP_SECRET, BSUID, NOW, PATH, PERSON, PHONE_ID, TEXT, VERIFY, Rig, button_reply, envelope,
                                template_tap, text_message, wc)


E = chr(0xE9)


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(**kw):
        r = Rig(tmp_path / f"r{len(made)}", **kw)
        made.append(r)
        return r.start()
    yield make
    for r in made:
        r.stop()


def hello(rig_, **more):
    return rig_.post(envelope([text_message(**more)]))


# --- 1. the handshake ---------------------------------------------------------------------------------------------------


def test_the_handshake_echoes_the_challenge_only_for_subscribe_and_the_right_verify_token(rig):
    r = rig()
    ok = r.request("GET", f"/{PATH}?hub.mode=subscribe&hub.verify_token={VERIFY}&hub.challenge=1158201444")
    assert ok[0] == 200 and ok[1] == b"1158201444" and ok[2]["Content-Type"].startswith("text/plain")
    assert ok[2]["X-Content-Type-Options"] == "nosniff"
    for query in (f"hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=1",
                  f"hub.mode=unsubscribe&hub.verify_token={VERIFY}&hub.challenge=1",
                  f"hub.verify_token={VERIFY}&hub.challenge=1",
                  "hub.mode=subscribe&hub.challenge=1",
                  f"hub.mode=subscribe&hub.verify_token={VERIFY}x&hub.challenge=1",
                  f"hub.mode=subscribe&hub.verify_token={VERIFY[:-1]}&hub.challenge=1",
                  f"hub.mode=subscribe&hub.verify_token={VERIFY}&hub.verify_token=again&hub.challenge=1",
                  "hub.mode=subscribe&hub.verify_token=%FF%FE%C3&hub.challenge=1"):   # non-ASCII must not raise
        status, body, _ = r.request("GET", f"/{PATH}?{query}")
        assert (status, body) == (403, b""), query
    for challenge in ("", "a%0d%0ab", "x" * 300, "%3Cscript%3E"):
        assert r.request("GET", f"/{PATH}?hub.mode=subscribe&hub.verify_token={VERIFY}&hub.challenge={challenge}")[0] == 400


def test_other_paths_are_404_and_other_methods_on_the_path_are_405(rig):
    r = rig()
    good = f"hub.mode=subscribe&hub.verify_token={VERIFY}&hub.challenge=1"
    for path in ("/", "/x", f"/{PATH}/", f"/{PATH}x", f"/{PATH[:-1]}", "/" + PATH.upper(), "/%2e%2e/" + PATH):
        assert r.request("GET", f"{path}?{good}")[0] == 404, path
        assert r.request("POST", path, b"{}", {"Content-Length": "2"})[0] == 404, path
    for method in ("PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
        status, _, headers = r.request(method, f"/{PATH}")
        assert status == 405 and headers["Allow"] == "GET, POST", method
        assert r.request(method, "/elsewhere")[0] == 404, method


def test_a_post_needs_a_content_length_and_a_body_over_three_mebibytes_is_refused_before_it_is_read(rig):
    r = rig()
    sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)
    sock.sendall(f"POST /{PATH} HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n".encode())
    assert sock.recv(100).startswith(b"HTTP/1.0 411")
    sock.close()
    sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)
    sock.sendall(f"POST /{PATH} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    assert sock.recv(100).startswith(b"HTTP/1.0 411")
    sock.close()
    for length in ("abc", "-1", "1 2", "99999999999999"):
        sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)
        sock.sendall(f"POST /{PATH} HTTP/1.1\r\nHost: x\r\nContent-Length: {length}\r\n\r\n".encode())
        assert sock.recv(100).startswith(b"HTTP/1.0 400"), length
        sock.close()
    sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)   # two lengths are ambiguous
    sock.sendall(f"POST /{PATH} HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{{}}".encode())
    assert sock.recv(100).startswith(b"HTTP/1.0 400")
    sock.close()
    sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)   # nothing of the body is sent: the answer comes at once
    sock.sendall(f"POST /{PATH} HTTP/1.1\r\nHost: x\r\nContent-Length: {3 * 1024 * 1024 + 1}\r\n\r\n".encode())
    assert sock.recv(100).startswith(b"HTTP/1.0 413")
    sock.close()
    assert r.out.updates() == []


def test_a_body_of_exactly_three_mebibytes_is_read_and_then_judged_by_its_signature(rig):
    r = rig()
    body = b" " * (3 * 1024 * 1024)
    assert r.post(None, raw=body)[0] == 200      # signed, not JSON: ignored with a 200
    assert r.post(None, raw=body, secret=APP_SECRET + "x")[0] == 401


# --- 2. the signature ---------------------------------------------------------------------------------------------------


def test_a_valid_signature_is_answered_200_and_the_update_is_written_before_the_answer_returns(rig):
    r = rig()
    status, _, _ = hello(r)
    assert status == 200
    [u] = r.out.updates()          # no waiting: the update line was written and flushed before the 200
    assert u == {"update_id": "wamid.A1", "sender": PERSON, "chat": PERSON, "private": True, "text": TEXT, "action": None,
                 "action_ref": None, "reply_to": None}


def test_a_missing_malformed_or_wrong_signature_is_401_and_nothing_is_processed(rig):
    r = rig()
    body = kit.body_of(envelope([text_message()]))
    good = kit.sign(body)
    cases = [None, "", "sha256=", "sha256=zz", good[len("sha256="):], good.upper(), "sha1=" + good[7:], good + "0", good[:-1],
             kit.sign(body, "another-secret"), "sha256=" + "0" * 64, "sha256=\xe9\xe9", "Bearer " + good]
    for header in cases:
        head = {} if header is None else {"X-Hub-Signature-256": header}
        status, _, _ = r.request("POST", f"/{PATH}", body, {"Content-Length": str(len(body)), **head})
        assert status == 401, header
    assert r.out.updates() == [] and r.store.seen == {}


def test_the_signature_is_checked_on_the_raw_bytes_a_reserialised_body_fails(rig):
    r = rig()
    payload = envelope([text_message()])
    raw = json.dumps(payload).encode()
    reserialised = json.dumps(payload, indent=1).encode()          # the same JSON, other bytes
    assert json.loads(raw) == json.loads(reserialised)
    assert r.request("POST", f"/{PATH}", reserialised, {"X-Hub-Signature-256": kit.sign(raw), "Content-Length": str(len(reserialised))})[0] == 401
    assert r.out.updates() == []
    assert r.request("POST", f"/{PATH}", raw, {"X-Hub-Signature-256": kit.sign(raw), "Content-Length": str(len(raw))})[0] == 200
    assert len(r.out.updates()) == 1


def test_the_comparison_is_on_bytes_and_a_non_ascii_secret_or_header_cannot_raise(rig):
    body = b"{}"
    assert wc.signature_ok("s" + E + "cret", body, "sha256=" + "0" * 64) is False
    assert wc.signature_ok("secret", body, "sha256=" + E + "0" * 63) is False
    assert wc.signature_ok("secret", body, None) is False
    import hmac as _hmac
    import hashlib
    good = "sha256=" + _hmac.new(("s" + E + "cret").encode(), body, hashlib.sha256).hexdigest()
    assert wc.signature_ok("s" + E + "cret", body, good) is True
    source = open(kit.SCRIPT, encoding="utf-8").read()
    assert "compare_digest" in source and "== self.secrets" not in source and "!= self.secrets" not in source


def test_a_signed_body_that_is_not_json_is_ignored_with_a_200_and_one_that_breaks_processing_is_500(rig, monkeypatch):
    r = rig()
    assert r.post(None, raw=b"not json")[0] == 200
    assert r.post(None, raw=b"\xff\xfe")[0] == 200
    assert r.post(None, raw=b"[1, 2]")[0] == 200 and r.post(None, raw=b'{"entry": 5}')[0] == 200
    assert r.out.updates() == []
    monkeypatch.setattr(wc.Webhook, "message", lambda self, m: (_ for _ in ()).throw(RuntimeError("boom")))
    assert hello(r)[0] == 500          # Meta retries on a 500


# --- 3. filtering and the dedupe ----------------------------------------------------------------------------------------


def test_another_phone_number_statuses_and_unsupported_types_produce_nothing(rig):
    r = rig()
    r.post(envelope([text_message("wamid.X1")], phone_id="999"))
    r.post(envelope(statuses=[{"id": "wamid.S", "status": "delivered", "recipient_id": PERSON}]))
    for n, kind in enumerate(("image", "audio", "video", "document", "sticker", "reaction", "location", "contacts", "order",
                              "system", "unsupported", "request_welcome")):
        r.post(envelope([{"id": f"wamid.U{n}", "type": kind, "from": PERSON, "from_user_id": BSUID, "timestamp": str(int(NOW))}]))
    r.post(envelope([{"id": "wamid.L", "type": "interactive", "from": PERSON, "timestamp": str(int(NOW)),
                      "interactive": {"type": "list_reply", "list_reply": {"id": "x", "title": "x"}}}]))
    r.post(envelope([text_message("wamid.E", body="   ")]))
    r.post(envelope([{"id": "wamid.N", "type": "text", "from": PERSON, "text": {"body": 5}}]))
    r.post(envelope([{"type": "text", "from": PERSON, "text": {"body": "no id"}}]))
    r.post(envelope([text_message("wamid.BAD", sender="not-digits", uid=None)]))
    r.post(envelope([text_message("wamid.NOID", sender=None, uid=None)]))
    assert r.out.updates() == []
    assert r.store.window == {}, "an ignored message opens no window"


def test_a_duplicate_wamid_is_dropped_also_after_a_restart(rig, tmp_path):
    r = rig()
    hello(r)
    hello(r)
    assert len(r.out.updates()) == 1
    assert list(kit_state(r.folder, wc.SEEN)) == ["wamid.A1"]
    r.stop()
    again = Rig(tmp_path / "r0", clock=r.clock).start()     # the same folder: a restart
    try:
        assert hello(again)[0] == 200
        assert again.out.updates() == [], "Meta retries for 7 days: the id is remembered"
    finally:
        again.stop()


def test_seen_ids_are_kept_eight_days_and_identities_thirty_and_pruned_at_the_start(tmp_path):
    folder = tmp_path / "wc"
    folder.mkdir(mode=0o700)
    clock = kit.Clock(NOW)
    day = 86400
    wc.write_private_json(str(folder / wc.SEEN), {"old": NOW - 9 * day, "recent": NOW - 7 * day})
    wc.write_private_json(str(folder / wc.IDENTITIES), {"BR.old": {"digits": "551100000001", "seen": NOW - 31 * day},
                                                        "BR.new": {"digits": "551100000002", "seen": NOW - 29 * day}})
    wc.write_private_json(str(folder / wc.WINDOW), {"5511000000aa": {"last_inbound": NOW - 40 * day},
                                                    "5511000000bb": {"last_inbound": NOW - 2 * day}})
    store = wc.Store(str(folder), clock)
    assert set(store.seen) == {"recent"} and set(store.identities) == {"BR.new"} and set(store.window) == {"5511000000bb"}
    assert list(kit_state(str(folder), wc.SEEN)) == ["recent"]       # the pruned state was written back
    assert oct((folder / wc.SEEN).stat().st_mode & 0o777) == "0o600"


def kit_state(folder, name):
    with open(f"{folder}/{name}", encoding="utf-8") as f:
        return json.load(f)


def test_the_state_files_are_mode_0600_and_the_caps_drop_the_oldest(tmp_path, monkeypatch):
    folder = tmp_path / "wc"
    folder.mkdir(mode=0o700)
    store = wc.Store(str(folder), kit.Clock(NOW))
    monkeypatch.setattr(wc, "SEEN_MAX", 3)
    for n in range(6):
        store.clock.now = NOW + n
        store.mark_seen(f"w{n}")
    store.save("seen")
    assert set(kit_state(str(folder), wc.SEEN)) == {"w3", "w4", "w5"}
    for name in (wc.SEEN, wc.WINDOW, wc.IDENTITIES):
        store.save({wc.SEEN: "seen", wc.WINDOW: "window", wc.IDENTITIES: "identities"}[name])
        assert (folder / name).stat().st_mode & 0o777 == 0o600


# --- 4. the mapping -----------------------------------------------------------------------------------------------------


def test_a_text_that_replies_to_a_message_carries_reply_to(rig):
    r = rig()
    hello(r, context="wamid.QUESTION")
    assert r.out.updates()[0]["reply_to"] == "wamid.QUESTION" and r.out.updates()[0]["text"] == TEXT


def test_a_button_reply_is_an_action_with_the_card_as_reply_to_and_a_template_button_is_the_pending_command(rig):
    r = rig()
    r.post(envelope([button_reply()]))
    r.post(envelope([template_tap()]))
    first, second = r.out.updates()
    assert first == {"update_id": "wamid.B1", "sender": PERSON, "chat": PERSON, "private": True, "text": None,
                     "action": "7:approve", "action_ref": None, "reply_to": "wamid.CARD"}
    assert second["text"] == "/pending" and second["action"] is None and second["reply_to"] is None


def test_the_identity_is_the_digits_when_present_the_remembered_digits_for_an_id_alone_else_the_id(rig):
    r = rig()
    r.post(envelope([text_message("wamid.1", sender=None)]))                 # unknown business-scoped id: the id itself
    assert r.out.updates()[-1]["sender"] == BSUID == r.out.updates()[-1]["chat"]
    r.post(envelope([text_message("wamid.2")]))                              # both arrive: the pair is learned
    assert r.out.updates()[-1]["sender"] == PERSON and r.store.digits_for(BSUID) == PERSON
    r.post(envelope([text_message("wamid.3", sender=None)]))                 # the id alone now resolves
    assert r.out.updates()[-1]["sender"] == PERSON
    r.post(envelope([text_message("wamid.4", sender=None, uid="BR.other0000000001")]))
    assert r.out.updates()[-1]["sender"] == "BR.other0000000001"
    assert kit_state(r.folder, wc.IDENTITIES)[BSUID]["digits"] == PERSON
    assert r.out.updates()[-1]["chat"] == r.out.updates()[-1]["sender"]      # the bridge requires them equal


def test_the_window_clock_is_the_messages_own_timestamp_not_the_time_of_receipt(rig):
    r = rig()
    day = 86400
    hello(r, at=NOW - 3 * day)                                                # a retry that arrives three days late
    assert r.store.entry(PERSON)[0] == NOW - 3 * day
    assert r.store.window_open(PERSON, NOW) is False
    hello(r, wamid="wamid.A2", at=NOW + 10 * day)                             # a timestamp from the future is read as now
    assert r.store.entry(PERSON)[0] == NOW + wc.CLOCK_SKEW
    hello(r, wamid="wamid.A3", at=NOW - day)                                  # an older one never moves the window back
    assert r.store.entry(PERSON)[0] == NOW + wc.CLOCK_SKEW
    r.post(envelope([{**text_message("wamid.A4"), "timestamp": "not a number"}]))
    assert r.store.entry(PERSON)[0] == NOW + wc.CLOCK_SKEW


def test_the_window_is_recorded_before_the_update_is_written_so_the_bridges_reply_finds_it_open(tmp_path):
    store = wc.Store(str(tmp_path), kit.Clock(NOW))
    seen = []
    hook = wc.Webhook(kit.settings(), dict(kit.SECRETS), store, lambda update, uid=None: seen.append(store.window_open(update["chat"], NOW)),
                      clock=kit.Clock(NOW))
    hook.process(envelope([text_message("wamid.W")]))
    assert seen == [True]


# --- 5. limits of the server --------------------------------------------------------------------------------------------


def test_the_server_binds_127_0_0_1_and_nothing_else(rig):
    r = rig()
    assert r.listener.server.server_address[0] == "127.0.0.1"
    source = open(kit.SCRIPT, encoding="utf-8").read()
    assert wc.LOOPBACK == "127.0.0.1" and "super().__init__((LOOPBACK, port), Handler)" in source
    with socket.socket() as s:                  # not reachable on another loopback address of the machine either
        s.settimeout(1)
        assert s.connect_ex(("127.0.0.2", r.port)) != 0


def test_a_request_that_stalls_is_cut_at_the_total_deadline_not_only_the_read_timeout(tmp_path):
    r = Rig(tmp_path / "d", deadline=0.6).start()
    try:
        sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)
        start = time.monotonic()
        sock.sendall(b"GET /")                      # a header that never ends, one byte at a time
        end = start + 4
        closed = False
        while time.monotonic() < end:
            try:
                sock.sendall(b"a")
                time.sleep(0.1)
            except OSError:
                closed = True
                break
        assert closed and time.monotonic() - start < 3, "the connection was cut near the deadline despite steady traffic"
        sock.close()
        sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)   # a body that never arrives
        sock.sendall(f"POST /{PATH} HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\nabc".encode())
        start = time.monotonic()
        sock.settimeout(4)
        assert sock.recv(100) == b"", "the stalled body ends with a closed connection and no answer"
        assert time.monotonic() - start < 3
        sock.close()
    finally:
        r.stop()


def test_concurrent_handlers_are_bounded_and_the_next_request_gets_503(tmp_path):
    r = Rig(tmp_path / "b", limit=2).start()
    try:
        held = []
        for _ in range(2):
            s = socket.create_connection(("127.0.0.1", r.port), timeout=5)
            s.sendall(b"GET /")                      # incomplete: the handler waits for the rest
            held.append(s)
        time.sleep(0.3)
        third = socket.create_connection(("127.0.0.1", r.port), timeout=5)
        assert third.recv(100).startswith(b"HTTP/1.0 503")
        third.close()
        for s in held:
            s.close()
        assert kit.wait_for(lambda: r.request("GET", "/none")[0] == 404, 5), "the slots come back"
    finally:
        r.stop()


def test_a_request_writes_nothing_to_stderr_not_the_path_nor_the_verify_token(rig, capfd):
    r = rig()
    r.request("GET", f"/{PATH}?hub.mode=subscribe&hub.verify_token={VERIFY}&hub.challenge=5")
    r.request("GET", f"/{PATH}?hub.mode=subscribe&hub.verify_token=wrong-{VERIFY}&hub.challenge=5")
    r.request("GET", f"/not-{PATH}")
    r.request("DELETE", f"/{PATH}")
    r.post(envelope([text_message()]), secret="wrong")
    sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)
    sock.sendall(b"\x00\x01garbage not http\r\n\r\n")
    sock.close()
    sock = socket.create_connection(("127.0.0.1", r.port), timeout=5)
    sock.sendall(b"GET /" + PATH.encode() + b" HTTP/1.1\r\nHost: x\r\n" + b"X: y\r\n" * 150 + b"\r\n")
    sock.recv(100)
    sock.close()
    time.sleep(0.2)
    seen = capfd.readouterr()
    for text in (seen.out, seen.err, "\n".join(r.logs)):
        for secret in (PATH, VERIFY, APP_SECRET, kit.TOKEN, PERSON, TEXT):
            assert secret not in text


def test_handle_error_and_the_default_log_methods_are_replaced(tmp_path):
    assert wc.Handler.log_message is wc.Handler.log_error is wc.Handler.log_request
    assert "handle_error" in wc.Server.__dict__ and "server_bind" in wc.Server.__dict__
    source = open(kit.SCRIPT, encoding="utf-8").read()
    assert "getfqdn" not in source


def test_a_failure_in_a_handler_thread_is_noted_by_class_only(rig, capfd):
    r = rig()
    r.listener.server.hook.note("seen", "x")
    try:
        raise ValueError(f"secret {VERIFY}")
    except ValueError:
        r.listener.server.handle_error(None, ("127.0.0.1", 1))
    assert VERIFY not in "\n".join(r.logs) + capfd.readouterr().err
    assert any("ValueError" in line for line in r.logs)


def test_statuses_for_messages_this_process_never_sent_are_ignored(rig):
    r = rig()
    r.post(envelope(statuses=[{"id": "wamid.UNKNOWN", "status": "failed", "errors": [{"code": 131047}]}]))
    assert r.listener.requests.empty()
    assert r.store.window == {}


def test_a_failed_status_with_131047_for_a_sent_wamid_is_queued_for_the_sender_worker(rig):
    r = rig()
    r.listener.sender.remember_sent("wamid.MINE", PERSON, NOW)
    r.post(envelope(statuses=[{"id": "wamid.MINE", "status": "failed", "errors": [{"code": 131047, "title": "x"}]}]))
    assert kit.wait_for(lambda: r.opener.of_type("template") != [], 5), r.logs
    r.post(envelope(statuses=[{"id": "wamid.MINE", "status": "failed", "errors": [{"code": 131026}]}]))   # another code: nothing
    r.post(envelope(statuses=[{"id": "wamid.MINE", "status": "delivered"}]))
    time.sleep(0.2)
    assert len(r.opener.of_type("template")) == 1


def test_the_path_is_matched_on_the_raw_request_target_before_any_decoding(rig):
    r = rig()
    good = f"hub.mode=subscribe&hub.verify_token={VERIFY}&hub.challenge=7"
    assert r.request("GET", f"/{PATH}?{good}")[0] == 200
    assert r.request("GET", f"/{PATH}?")[0] == 403
    encoded = "/%30" + PATH[1:]                  # the same path, percent-encoded: not the path
    assert r.request("GET", f"{encoded}?{good}")[0] == 404 and r.request("POST", encoded, b"{}", {"Content-Length": "2"})[0] == 404
    assert r.request("GET", f"/{PATH}%3F{good}")[0] == 404
    assert r.request("GET", f"/{PATH};x?{good}")[0] == 404


def test_a_failure_to_persist_is_a_500_so_meta_retries_and_the_retry_does_not_repeat_the_update(rig, monkeypatch):
    r = rig()
    real = r.store.save
    monkeypatch.setattr(r.store, "save", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    assert hello(r)[0] == 500 and len(r.out.updates()) == 1
    monkeypatch.setattr(r.store, "save", real)
    assert hello(r)[0] == 200 and len(r.out.updates()) == 1, "deduplicated in memory, and now written"
    assert list(kit_state(r.folder, wc.SEEN)) == ["wamid.A1"]


def test_a_reply_to_the_buttons_message_binds_to_the_card_and_a_late_failure_on_it_closes_the_window(rig):
    r = rig()
    hello(r)
    card = r.ask(1, PERSON, kit.card("Detailed plan. " * 100))       # text, then the buttons as a reply to it
    buttons = "wamid.OUT3"                                            # the token check was call 1, the text 2, the buttons 3
    assert card["message_id"] == "wamid.OUT2" and r.listener.sender.sent_info(buttons) is not None
    r.post(envelope([text_message("wamid.R1", body="blue", context=buttons)]))
    r.post(envelope([button_reply("wamid.R2", context=buttons)]))
    r.post(envelope([text_message("wamid.R3", body="other", context="wamid.UNRELATED")]))
    assert [u["reply_to"] for u in r.out.updates()[1:]] == ["wamid.OUT2", "wamid.OUT2", "wamid.UNRELATED"]
    r.clock.now += 5
    r.post(envelope(statuses=[{"id": buttons, "status": "failed", "errors": [{"code": 131047}]}]))
    assert kit.wait_for(lambda: r.opener.of_type("template"), 5)
