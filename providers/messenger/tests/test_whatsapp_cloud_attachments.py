"""Offline tests of the attachments of providers/messenger/whatsapp-cloud.py (ATT-3): each kind of medium Meta sends mapped into an update, the
signature check that is unchanged, and the listen op `fetch` (the media id asked of Graph at fetch time, the allow-listed media host, the token
sent only where it is required, the byte cap, the declared hash, a gone medium, the token absent from every error). Graph and the media host are
fakes; the only socket is the provider's own server and one throw-away loopback server.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_cloud_attachments.py
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import http.server
import json
import os
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

import whatsapp_cloud_kit as kit
from whatsapp_cloud_kit import (BSUID, MEDIA_HOST, MEDIA_ID, MEDIA_URL, NOW, PERSON, TOKEN, EndlessResponse, MediaOpener, Opener, Rig,
                                StreamResponse, envelope, http_error, lookup, media_message, text_message, wc)

BODY = b"%PDF-1.4 a small fake document " * 40
DIGEST = hashlib.sha256(BODY).hexdigest()
GET_MEDIA = f"GET /{MEDIA_ID}"
WRONG = "another-" + "value"                    # a signing value that is not the configured one


@pytest.fixture
def rig(tmp_path):
    made = []

    def make(*args, **kw):
        r = Rig(tmp_path / f"r{len(made)}", *args, **kw).start()
        made.append(r)
        return r
    yield make
    for r in made:
        r.stop()


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir(mode=0o700)
    return folder


def lookups(r):
    """The calls to Graph other than the token check the provider makes while it starts."""
    return [c for c in r.opener.calls if not c["path"].startswith("/" + kit.PHONE_ID)]


def served(**more):
    """A Graph that answers the lookup of the fake medium."""
    return Opener([(GET_MEDIA, lookup(**more))])


# --- the capabilities and the verbs ----------------------------------------------------------------------------------------------


def test_the_provider_declares_attachments_and_the_largest_file_meta_serves():
    assert wc.CAPABILITIES["attachments"] is True and wc.CAPABILITIES["max_attachment_bytes"] == 100 * 1024 * 1024
    done = subprocess.run([sys.executable, str(kit.SCRIPT), "capabilities", "--platform", "whatsapp-cloud"], capture_output=True, text=True)
    assert json.loads(done.stdout)["attachments"] is True and json.loads(done.stdout)["max_attachment_bytes"] == 104857600


def test_the_one_shot_fetch_verb_exits_2_with_the_listen_only_sentence(capsys):
    assert wc.main(["fetch-attachment", "--platform", "whatsapp-cloud", "--ref", MEDIA_ID, "--out", "/x", "--max-bytes", "5"]) == 2
    assert "listen mode" in capsys.readouterr().err


# --- the mapping of each type of medium -------------------------------------------------------------------------------------------


def only_update(r):
    assert kit.wait_for(lambda: len(r.out.updates()) == 1), (r.out.lines, r.logs)
    return r.out.updates()[0]


def test_a_document_becomes_an_attachment_with_its_name_and_type_and_the_caption_as_text(rig):
    r = rig()
    message = media_message("document", {"id": MEDIA_ID, "mime_type": "application/pdf", "sha256": "x", "filename": "plan.pdf",
                                         "caption": "the plan for northwind-shop"})
    assert r.post(envelope([message]))[0] == 200
    update = only_update(r)
    assert update["attachments"] == [{"ref": MEDIA_ID, "name": "plan.pdf", "size": None, "type": "application/pdf"}]
    assert update["text"] == "the plan for northwind-shop" and update["action"] is None and update["action_ref"] is None
    assert update["sender"] == update["chat"] == PERSON and update["private"] is True and update["update_id"] == "wamid.M1"


@pytest.mark.parametrize("kind, media, expected", [
    ("image", {"id": MEDIA_ID, "mime_type": "image/jpeg", "caption": "a photo"}, ("photo", None, "a photo")),
    ("audio", {"id": MEDIA_ID, "mime_type": "audio/mpeg"}, ("audio", None, None)),
    ("audio", {"id": MEDIA_ID, "mime_type": "audio/ogg; codecs=opus", "voice": True}, ("voice", None, None)),
    ("video", {"id": MEDIA_ID, "mime_type": "video/mp4", "caption": "a clip"}, ("video", None, "a clip")),
    ("sticker", {"id": MEDIA_ID, "mime_type": "image/webp", "animated": False}, ("sticker", None, None)),
])
def test_an_image_audio_video_or_sticker_is_named_as_the_kind_the_bridge_refuses_before_it_downloads(rig, kind, media, expected):
    r = rig()
    assert r.post(envelope([media_message(kind, media)]))[0] == 200
    update = only_update(r)
    assert [(a["type"], a["name"], update["text"]) for a in update["attachments"]] == [expected]
    assert update["attachments"][0]["ref"] == MEDIA_ID and update["attachments"][0]["size"] is None


def test_a_document_without_a_type_or_name_is_an_attachment_with_nulls(rig):
    r = rig()
    r.post(envelope([media_message("document", {"id": MEDIA_ID})]))
    assert only_update(r)["attachments"] == [{"ref": MEDIA_ID, "name": None, "size": None, "type": None}]


def test_a_declared_name_and_type_are_cleaned_and_a_blank_or_odd_caption_is_no_text(rig):
    r = rig()
    r.post(envelope([media_message("document", {"id": MEDIA_ID, "mime_type": "Application/PDF", "filename": "x\x00\x1by.pdf", "caption": "   "})]))
    update = only_update(r)
    assert update["attachments"][0]["name"] == "xy.pdf" and update["attachments"][0]["type"] == "application/pdf" and update["text"] is None
    r2 = rig()
    r2.post(envelope([media_message("image", {"id": MEDIA_ID, "caption": 5})]))
    assert only_update(r2)["text"] is None


@pytest.mark.parametrize("media", [{}, {"id": 5}, {"id": ""}, {"id": "../etc/passwd"}, {"id": "12 34"}, {"id": "a" * 65}, {"id": "1/2"}, {"id": None},
                                   {"id": MEDIA_ID + "\n"}, {"id": "?x=1"}])
def test_a_medium_with_no_valid_id_produces_nothing_and_opens_no_window(rig, media):
    r = rig()
    r.post(envelope([media_message("document", media)]))
    r.post(envelope([{"id": "wamid.NOOBJ", "type": "image", "from": PERSON, "timestamp": str(int(NOW))}]))
    r.post(envelope([{"id": "wamid.BADOBJ", "type": "video", "from": PERSON, "timestamp": str(int(NOW)), "video": "not an object"}]))
    assert r.out.updates() == [] and r.store.window == {}


def test_a_medium_opens_the_window_and_is_deduplicated_also_after_a_restart(rig, tmp_path):
    r = rig()
    r.post(envelope([media_message("document")]))
    r.post(envelope([media_message("document")]))
    assert len(r.out.updates()) == 1 and r.store.window[PERSON]["last_inbound"] == NOW
    assert "wamid.M1" in kit_seen(r)
    r.stop()
    again = kit.Rig(tmp_path / "r0", clock=r.clock).start()
    try:
        again.post(envelope([media_message("document")]))
        assert again.out.updates() == []
    finally:
        again.stop()


def kit_seen(r):
    return json.load(open(os.path.join(r.folder, wc.SEEN)))


def opened(r):
    """The person has written, so the window is open and a send goes out."""
    r.post(envelope([text_message("wamid.OPEN")]))
    assert kit.wait_for(lambda: len(r.out.updates()) == 1)
    return r


def test_a_medium_that_replies_to_a_card_carries_the_card_as_reply_to(rig):
    r = opened(rig())
    card_id = r.ask(1, PERSON, kit.card())["message_id"]
    r.post(envelope([media_message("document", context=card_id)]))
    assert kit.wait_for(lambda: len(r.out.updates()) == 2) and r.out.updates()[-1]["reply_to"] == card_id


def test_text_and_taps_are_unchanged_beside_the_media(rig):
    r = rig()
    r.post(envelope([text_message("wamid.T9"), kit.button_reply("wamid.B9")]))
    updates = r.out.updates()
    assert [(u["text"], u["action"], "attachments" in u) for u in updates] == [(kit.TEXT, None, False), (None, "7:approve", False)]


def test_a_medium_whose_sender_cannot_be_resolved_produces_nothing(rig):
    r = rig()
    r.post(envelope([media_message("document", sender=None, uid=None)]))
    r.post(envelope([media_message("document", wamid="wamid.M2", sender="not-digits", uid=None)]))
    assert r.out.updates() == []


# --- the webhook's signature is unchanged --------------------------------------------------------------------------------------


def test_an_unsigned_or_wrongly_signed_medium_is_refused_and_emits_nothing(rig):
    r = rig()
    body = kit.body_of(envelope([media_message("document")]))
    assert r.request("POST", "/" + kit.PATH, body, {"Content-Type": "application/json"})[0] == 401
    assert r.post(envelope([media_message("document")]), secret=WRONG)[0] == 401
    assert r.request("POST", "/" + kit.PATH, body, {"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + "0" * 64})[0] == 401
    assert r.out.updates() == [] and r.store.window == {}


def test_a_medium_is_accepted_only_after_ready(rig):
    r = rig()
    r.listener.hook.accepting = False
    assert r.post(envelope([media_message("document")]))[0] == 503 and r.out.updates() == []


# --- fetch: the happy path ------------------------------------------------------------------------------------------------------


def test_a_fetch_asks_graph_for_the_address_then_reads_it_with_the_token_and_writes_content(rig, out):
    r = rig(opener=served(size=len(BODY), sha=DIGEST), media=MediaOpener(payload=BODY))
    done = r.fetch(5, MEDIA_ID, out, 10_000_000)
    assert done == {"id": 5, "ok": True, "bytes": len(BODY), "sha256": DIGEST}
    path = out / "content"
    assert path.read_bytes() == BODY and stat.S_IMODE(path.stat().st_mode) == 0o600 and os.listdir(out) == ["content"]
    graph = [c for c in r.opener.calls if c["path"] == "/" + MEDIA_ID]
    assert len(graph) == 1 and graph[0]["method"] == "GET" and graph[0]["auth"] == f"Bearer {TOKEN}"
    (media,) = r.media.calls
    assert media["url"] == MEDIA_URL and media["auth"] == f"Bearer {TOKEN}" and media["method"] == "GET" and media["timeout"] == 10.0
    assert [c["path"] for c in r.opener.calls if "/messages" in c["path"]] == []


def test_the_address_is_asked_for_at_each_fetch_because_it_is_short_lived(rig, tmp_path):
    r = rig(opener=served(), media=MediaOpener(payload=BODY))
    for n in (1, 2):
        folder = tmp_path / f"f{n}"
        folder.mkdir(mode=0o700)
        assert r.fetch(n, MEDIA_ID, folder, 10**7)["ok"] is True
    assert len([c for c in r.opener.calls if c["path"] == "/" + MEDIA_ID]) == 2 and len(r.media.calls) == 2


def test_the_hash_graph_declares_is_checked_in_base64_too(rig, out):
    declared = base64.b64encode(hashlib.sha256(BODY).digest()).decode()
    r = rig(opener=served(sha=declared), media=MediaOpener(payload=BODY))
    assert r.fetch(1, MEDIA_ID, out, 10**7)["ok"] is True


def test_no_declared_hash_is_no_check(rig, out):
    r = rig(opener=served(), media=MediaOpener(payload=BODY))
    assert r.fetch(1, MEDIA_ID, out, 10**7)["sha256"] == DIGEST


# --- fetch: refusals -----------------------------------------------------------------------------------------------------------


def test_a_hash_that_does_not_match_is_refused_and_leaves_no_file(rig, out):
    r = rig(opener=served(sha=hashlib.sha256(b"another file").hexdigest()), media=MediaOpener(payload=BODY))
    done = r.fetch(1, MEDIA_ID, out, 10**7)
    assert done["ok"] is False and done["kind"] == "failed" and "hash" in done["reason"] and os.listdir(out) == []


def test_a_hash_of_no_known_shape_is_refused(rig, out):
    r = rig(opener=served(sha="not a hash"), media=MediaOpener(payload=BODY))
    done = r.fetch(1, MEDIA_ID, out, 10**7)
    assert done["ok"] is False and done["kind"] == "failed" and os.listdir(out) == []


def test_a_size_graph_declares_over_the_cap_is_refused_before_the_download(rig, out):
    r = rig(opener=served(size=5_000_000), media=MediaOpener(payload=BODY))
    done = r.fetch(1, MEDIA_ID, out, 1_000_000)
    assert done["ok"] is False and done["kind"] == "usage" and r.media.calls == [] and os.listdir(out) == []


@pytest.mark.parametrize("size", ["5000000", "999999999999999999"])
def test_a_size_given_as_a_string_of_digits_is_checked_before_the_download_too(rig, out, size):
    r = rig(opener=served(size=size), media=MediaOpener(payload=BODY))
    done = r.fetch(1, MEDIA_ID, out, 1_000_000)
    assert done["kind"] == "usage" and r.media.calls == [] and os.listdir(out) == []


@pytest.mark.parametrize("size", ["", "12ab", "-5", "1" * 19, True, 1.5, None, "١٢٣"])
def test_a_size_that_is_neither_a_whole_number_nor_digits_is_not_a_check_and_the_stream_decides(rig, out, size):
    r = rig(opener=served(size=size), media=MediaOpener(payload=BODY))
    assert r.fetch(1, MEDIA_ID, out, 10**6)["ok"] is True


def test_a_length_the_media_host_declares_over_the_cap_is_refused_before_a_byte_is_read(rig, out):
    body = StreamResponse(BODY, headers={"Content-Length": "99999999"})
    r = rig(opener=served(), media=MediaOpener(rule=lambda c: body))
    done = r.fetch(1, MEDIA_ID, out, 1_000_000)
    assert done["kind"] == "usage" and body.total == 0 and os.listdir(out) == []


def test_the_cap_is_enforced_mid_stream_when_nothing_was_declared(rig, out):
    body = EndlessResponse()
    r = rig(opener=served(), media=MediaOpener(rule=lambda c: body))
    done = r.fetch(1, MEDIA_ID, out, 300_000)
    assert done["ok"] is False and done["kind"] == "usage" and body.total <= 300_001 and os.listdir(out) == []


def test_a_graph_answer_without_an_address_is_a_failure(rig, out):
    for found in ({"id": MEDIA_ID}, {"url": 5}, {"url": ""}, {"url": None}):
        r = rig(opener=Opener([(GET_MEDIA, found)]))
        done = r.fetch(1, MEDIA_ID, out, 10**6)
        assert done["ok"] is False and done["kind"] == "failed" and r.media.calls == [], found


@pytest.mark.parametrize("url", [
    "https://evil.example/whatsapp_business/attachments/?mid=1",
    "http://lookaside.fbsbx.com/x",
    "https://lookaside.fbsbx.com.evil.example/x",
    "https://evil.example/lookaside.fbsbx.com/x",
    "https://user:pass@lookaside.fbsbx.com/x",
    "https://lookaside.fbsbx.com:8443/x",
    "https://evil.example\\@lookaside.fbsbx.com/x",
    "https://graph.facebook.com/v25.0/1",
    "https://127.0.0.1/x",
    "ftp://lookaside.fbsbx.com/x",
])
def test_an_address_off_meta_media_host_is_never_requested_and_the_token_never_leaves(rig, out, url):
    r = rig(opener=served(url=url), media=MediaOpener(payload=BODY))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["ok"] is False and done["kind"] == "failed" and "host" in done["reason"]
    assert r.media.calls == [], "no request is made to an address that is not on the list"
    assert all(url not in str(c) for c in r.opener.calls[1:]) and os.listdir(out) == []
    assert TOKEN not in json.dumps(r.out.lines) and all(TOKEN not in line for line in r.logs)


def test_the_media_address_is_not_echoed_in_the_answer(rig, out):
    r = rig(opener=served(url="https://evil.example/secret-looking-path?hash=abc"), media=MediaOpener())
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert "evil.example" not in json.dumps(done) and "secret-looking" not in json.dumps(done)


@pytest.mark.parametrize("ref", ["", "../x", "12/34", "12 34", "a" * 65, "1234567890\n", "?x=1", "..", "1.2", "%2e%2e", "ü"])
def test_a_reference_that_is_not_a_media_id_is_a_usage_error_with_no_call(rig, out, ref):
    r = rig(opener=served(), media=MediaOpener())
    done = r.fetch(1, ref, out, 10**6)
    assert done["ok"] is False and done["kind"] == "usage" and lookups(r) == [] and r.media.calls == []


@pytest.mark.parametrize("request_fields", [
    {"ref": 5}, {"ref": "x" * 513}, {"max_bytes": 0}, {"max_bytes": -1}, {"max_bytes": True}, {"max_bytes": "9"}, {"max_bytes": 1.5}, {"out": ""}, {"out": 5},
])
def test_a_fetch_request_with_a_missing_or_wrong_field_is_a_usage_error(rig, out, request_fields):
    r = rig(opener=served(), media=MediaOpener())
    request = {"id": 3, "op": "fetch", "ref": MEDIA_ID, "out": str(out), "max_bytes": 1000, **request_fields}
    r.pipe.send(request)
    assert kit.wait_for(lambda: any(a["id"] == 3 for a in r.out.answers()))
    done = next(a for a in r.out.answers() if a["id"] == 3)
    assert done["ok"] is False and done["kind"] == "usage" and lookups(r) == []


def test_the_folder_must_be_a_real_absolute_one_and_content_is_never_replaced(rig, tmp_path, out):
    r = rig(opener=served(), media=MediaOpener(payload=BODY))
    (out / "content").write_bytes(b"keep me")
    assert r.fetch(1, MEDIA_ID, out, 10**6)["kind"] == "usage" and (out / "content").read_bytes() == b"keep me"
    link = tmp_path / "link"
    os.symlink(out, link)
    assert r.fetch(2, MEDIA_ID, link, 10**6)["kind"] == "usage"
    assert r.fetch(3, MEDIA_ID, "relative/folder", 10**6)["kind"] == "usage"
    assert r.fetch(4, MEDIA_ID, tmp_path / "missing", 10**6)["kind"] == "usage"


# --- fetch: a medium Meta no longer serves -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("failure", [http_error(404), http_error(400, 100)])
def test_graph_saying_the_medium_does_not_exist_is_gone(rig, out, failure):
    r = rig(opener=Opener([(GET_MEDIA, lambda c: failure)]))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["ok"] is False and done["kind"] == "gone" and r.media.calls == []


@pytest.mark.parametrize("status", [404, 410])
def test_the_media_host_saying_the_medium_is_gone_is_gone(rig, out, status):
    r = rig(opener=served(), media=MediaOpener(rule=lambda c: http_error(status)))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["kind"] == "gone" and os.listdir(out) == []


def test_other_failures_are_failed_with_the_status_only(rig, out):
    r = rig(opener=served(), media=MediaOpener(rule=lambda c: http_error(500, body_text="planted-answer-text")))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["kind"] == "failed" and "500" in done["reason"] and "planted" not in json.dumps(r.out.lines)
    r2 = rig(opener=Opener([(GET_MEDIA, lambda c: http_error(500, 1, "planted-answer-text"))]))
    done = r2.fetch(1, MEDIA_ID, out, 10**6)
    assert done["kind"] == "failed" and "planted" not in json.dumps(r2.out.lines)


def test_a_token_graph_refuses_answers_not_configured_and_stops_the_provider_with_exit_3(rig, out):
    r = rig(opener=Opener([(GET_MEDIA, lambda c: http_error(401, 190))]))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["ok"] is False and done["kind"] == "not-configured"
    assert kit.wait_for(lambda: not r.thread.is_alive()) and r.result == [3]


def test_the_media_host_refusing_the_token_is_a_failure_that_does_not_stop_the_provider(rig, out):
    r = rig(opener=served(), media=MediaOpener(rule=lambda c: http_error(401)))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["kind"] == "failed" and r.thread.is_alive()
    assert r.fetch(2, MEDIA_ID, out, 10**6)["kind"] == "failed", "and it still answers"


# --- fetch: the token is in no error -----------------------------------------------------------------------------------------------


def leaks(r, *needles):
    text = json.dumps(r.out.lines) + "\n".join(r.logs)
    return [n for n in needles if n in text]


@pytest.mark.parametrize("error", [
    urllib.error.URLError("planted-token-here " + TOKEN),
    urllib.error.URLError(OSError(TOKEN)),
    OSError(TOKEN),
    ValueError(TOKEN),
    http.client.IncompleteRead(TOKEN.encode(), 5),
    http.client.RemoteDisconnected(TOKEN),
    http.client.BadStatusLine(TOKEN),
    RuntimeError(TOKEN),
])
def test_a_failure_of_the_media_host_names_the_kind_only_never_the_token(rig, out, error):
    r = rig(opener=served(), media=MediaOpener(rule=lambda c: error))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["ok"] is False and leaks(r, TOKEN, "planted-token-here") == []
    assert r.thread.is_alive(), "an unexpected failure does not stop the provider"


@pytest.mark.parametrize("error", [urllib.error.URLError(TOKEN), OSError(TOKEN), ValueError(TOKEN), http.client.RemoteDisconnected(TOKEN),
                                   http.client.IncompleteRead(TOKEN.encode(), 1), RuntimeError(TOKEN)])
def test_a_failure_of_graph_during_the_lookup_never_shows_the_token(rig, out, error):
    r = rig(opener=Opener([(GET_MEDIA, lambda c: error)]))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["ok"] is False and leaks(r, TOKEN) == [] and r.media.calls == []


def test_a_failure_in_the_middle_of_the_body_leaves_no_file_and_no_token(rig, out):
    body = StreamResponse(b"partial " * 100, error=http.client.IncompleteRead(TOKEN.encode(), 9))
    r = rig(opener=served(), media=MediaOpener(rule=lambda c: body))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["kind"] == "failed" and leaks(r, TOKEN) == [] and os.listdir(out) == []


def test_the_token_is_not_in_the_answer_of_a_success_either(rig, out):
    r = rig(opener=served(), media=MediaOpener(payload=BODY))
    r.fetch(1, MEDIA_ID, out, 10**6)
    assert leaks(r, TOKEN) == []


# --- fetch: a redirect is refused -----------------------------------------------------------------------------------------------------


class Redirecting(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Redirecting.seen.append((self.path, self.headers.get("Authorization")))
        self.send_response(302)
        self.send_header("Location", "http://other.example/stolen")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_the_real_media_opener_refuses_a_redirect_and_never_asks_where_it_points(monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    Redirecting.seen = []
    server = http.server.HTTPServer(("127.0.0.1", 0), Redirecting)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/m", headers={"Authorization": f"Bearer {TOKEN}"})
        with pytest.raises(wc.GraphError) as e:
            wc.MEDIA_OPENER.open(request, timeout=5)
        assert "redirect" in str(e.value) and TOKEN not in str(e.value) and e.value.status == 302
        assert len(Redirecting.seen) == 1, "one request: the redirect was not followed"
    finally:
        server.shutdown()
        server.server_close()


def test_a_redirect_from_the_media_host_is_a_failure_with_no_second_request(rig, out):
    r = rig(opener=served(), media=MediaOpener(rule=lambda c: wc.GraphError(302, None, "refusing to follow a 302 redirect: the request carries the token")))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["kind"] == "failed" and "redirect" in done["reason"] and len(r.media.calls) == 1 and leaks(r, TOKEN) == []


def test_the_providers_media_opener_is_the_one_that_refuses_redirects():
    assert any(isinstance(h, wc.RefuseRedirect) for h in wc.MEDIA_OPENER.handlers)
    assert wc.Graph(TOKEN, kit.PHONE_ID).media_opener is wc.MEDIA_OPENER


# --- fetch: the listener's behaviour ------------------------------------------------------------------------------------------------


def test_a_slow_fetch_does_not_hold_up_a_send(rig, out):
    gate = threading.Event()

    def slow(call):
        gate.wait(15)
        return StreamResponse(BODY)
    r = opened(rig(opener=served(), media=MediaOpener(rule=slow)))
    r.fetch(7, MEDIA_ID, out, 10**6, wait=False)
    assert kit.wait_for(lambda: len(r.media.calls) == 1)
    sent = r.ask(8, PERSON, kit.plain("hello"))
    assert sent["ok"] is True, "the send was answered while the fetch waits"
    assert not any(a["id"] == 7 for a in r.out.answers())
    gate.set()
    assert kit.wait_for(lambda: any(a["id"] == 7 for a in r.out.answers()))
    assert next(a for a in r.out.answers() if a["id"] == 7)["ok"] is True


def test_the_fetches_are_answered_one_at_a_time_in_order(rig, tmp_path):
    r = rig(opener=served(), media=MediaOpener(payload=BODY))
    folders = []
    for n in (1, 2, 3):
        folder = tmp_path / f"f{n}"
        folder.mkdir(mode=0o700)
        folders.append(folder)
        r.fetch(n, MEDIA_ID, folder, 10**6, wait=False)
    assert kit.wait_for(lambda: len([a for a in r.out.answers() if a["ok"]]) == 3)
    assert [a["id"] for a in r.out.answers()] == [1, 2, 3] and all((f / "content").read_bytes() == BODY for f in folders)


def test_an_unexpected_exception_in_a_fetch_is_answered_without_text_and_the_provider_goes_on(rig, out, monkeypatch):
    r = opened(rig(opener=served(), media=MediaOpener(payload=BODY)))
    monkeypatch.setattr(r.listener.graph, "fetch_media", lambda *a: (_ for _ in ()).throw(RuntimeError("planted-" + TOKEN)))
    done = r.fetch(1, MEDIA_ID, out, 10**6)
    assert done["ok"] is False and done["kind"] == "failed" and leaks(r, TOKEN, "planted-") == []
    assert r.ask(2, PERSON, kit.plain("still here"))["ok"] is True


def test_a_request_line_with_another_op_is_still_a_usage_error(rig):
    r = rig()
    r.pipe.send({"id": 4, "op": "delete"})
    assert kit.wait_for(lambda: any(a["id"] == 4 for a in r.out.answers()))
    done = next(a for a in r.out.answers() if a["id"] == 4)
    assert done["kind"] == "usage" and done["ok"] is False


def test_the_sends_are_unchanged_the_window_the_template_and_the_buttons(rig):
    r = opened(rig())
    done = r.ask(1, PERSON, kit.card())
    assert done["ok"] is True and r.opener.of_type("interactive")


def test_nothing_but_the_ids_of_the_fetch_reaches_graph(rig, out):
    r = rig(opener=served(), media=MediaOpener(payload=BODY))
    r.fetch(1, MEDIA_ID, out, 10**6)
    assert [(c["method"], c["path"]) for c in r.opener.calls] == [("GET", f"/{kit.PHONE_ID}?fields=id"), ("GET", f"/{MEDIA_ID}")]


def test_the_media_address_graph_gave_is_requested_exactly_as_listed(rig, out):
    r = rig(opener=served(url="https://LOOKASIDE.fbsbx.com:443/whatsapp_business/attachments/?mid=7&ext=9&hash=abc"), media=MediaOpener(payload=BODY))
    assert r.fetch(1, MEDIA_ID, out, 10**6)["ok"] is True
    assert r.media.calls[0]["url"] == f"https://{MEDIA_HOST}/whatsapp_business/attachments/?mid=7&ext=9&hash=abc"
