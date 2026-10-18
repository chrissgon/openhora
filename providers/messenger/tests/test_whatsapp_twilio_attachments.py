"""Offline tests of the attachments of providers/messenger/whatsapp-twilio.py (ATT-3): `NumMedia`, `MediaUrlN` and `MediaContentTypeN` mapped into an
update, the signature check that is unchanged, and the listen op `fetch` (the address rebuilt from ids validated by a full-match pattern, the
account's key sent only to api.twilio.com, one redirect followed only to Twilio's media host with the key stripped, the byte cap, a gone medium, the
key absent from every error). Twilio is a fake; the only socket is the provider's own server and one throw-away loopback server.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_twilio_attachments.py
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

import whatsapp_twilio_kit as kit
from whatsapp_twilio_kit import (ACCOUNT, AUTH, KEY_SECRET, KEY_SID, MEDIA_HOST, OTHER_ACCOUNT, PERSON, EndlessResponse, MediaOpener, Rig,
                                 StreamResponse, http_error, inbound, media_ids, media_ref, media_url, redirect, with_media, wt)

BODY = b"%PDF-1.4 a small fake document " * 40
BASIC = "Basic " + base64.b64encode(f"{KEY_SID}:{KEY_SECRET}".encode()).decode()
REF = media_ref(1)
WRONG = "another-" + "value"                    # a signing value that is not the configured one
API_URL = f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Messages/{media_ids(1)[0]}/Media/{media_ids(1)[1]}"


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


def only_update(r):
    assert kit.wait_for(lambda: len(r.out.updates()) == 1), (r.out.lines, r.logs)
    return r.out.updates()[0]


def leaks(r, *needles):
    text = json.dumps(r.out.lines) + "\n".join(r.logs)
    return [n for n in needles if n in text]


# --- the capabilities and the verbs ----------------------------------------------------------------------------------------------


def test_the_provider_declares_attachments_and_twilios_16_mib_whatever_the_settings():
    for settings in (None, kit.settings(), kit.settings(buttons=kit.BUTTONS)):
        caps = wt.capabilities(settings)
        assert caps["attachments"] is True and caps["max_attachment_bytes"] == 16 * 1024 * 1024
    assert wt.capabilities(None)["buttons"] is False and wt.capabilities(None)["documents"] is False


def test_the_capabilities_verb_prints_them(tmp_path):
    env = {**os.environ, "OPENHORA_STATE_DIR": str(tmp_path / "state")}
    done = subprocess.run([sys.executable, str(kit.SCRIPT), "capabilities", "--platform", "whatsapp-twilio"], capture_output=True, text=True, env=env)
    assert json.loads(done.stdout)["attachments"] is True and json.loads(done.stdout)["max_attachment_bytes"] == 16777216


def test_the_one_shot_fetch_verb_exits_2_with_the_listen_only_sentence(capsys):
    assert wt.main(["fetch-attachment", "--platform", "whatsapp-twilio", "--ref", REF, "--out", "/x", "--max-bytes", "5"]) == 2
    assert "listen mode" in capsys.readouterr().err


# --- the mapping of the media of a message -----------------------------------------------------------------------------------------


def test_a_medium_only_message_is_no_longer_ignored_and_its_name_and_size_are_null(rig):
    r = rig()
    assert r.post(with_media(1, ("application/pdf",)))[0] == 200
    update = only_update(r)
    assert update["attachments"] == [{"ref": REF, "name": None, "size": None, "type": "application/pdf"}]
    assert update["text"] is None and update["action"] is None and update["sender"] == update["chat"] == PERSON and update["private"] is True
    assert update["update_id"] == media_ids(1)[0] and r.store.window[PERSON]["last_inbound"] == kit.NOW


def test_the_body_of_a_medium_message_is_the_caption(rig):
    r = rig()
    r.post(with_media(1, ("application/pdf",), body="the plan for northwind-shop"))
    assert only_update(r)["text"] == "the plan for northwind-shop"


@pytest.mark.parametrize("content_type, expected", [
    ("image/jpeg", "photo"), ("image/webp", "photo"), ("image/png", "photo"),
    ("audio/ogg", "audio"), ("audio/mpeg", "audio"), ("video/mp4", "video"),
    ("application/pdf", "application/pdf"),
    ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("text/csv", "text/csv"), ("Application/PDF; x=1", "application/pdf"),
    ("nonsense", None), ("", None),
])
def test_the_content_type_is_mapped_to_the_kind_the_bridge_refuses_early_or_kept_as_a_type(rig, content_type, expected):
    r = rig()
    r.post(with_media(1, (content_type,)))
    assert only_update(r)["attachments"][0]["type"] == expected


def test_a_message_with_several_media_gives_one_attachment_each_in_order(rig):
    r = rig()
    r.post(with_media(1, ("application/pdf", "image/jpeg", "text/plain")))
    refs = [a["ref"] for a in only_update(r)["attachments"]]
    assert refs == [media_ref(1, 0), media_ref(1, 1), media_ref(1, 2)]


def test_a_missing_content_type_is_a_null_type_and_the_medium_is_still_taken(rig):
    r = rig()
    fields = with_media(1, ("application/pdf",))
    del fields["MediaContentType0"]
    r.post(fields)
    assert only_update(r)["attachments"][0]["type"] is None


@pytest.mark.parametrize("change", [
    {"MediaUrl0": "https://api.example/m"},
    {"MediaUrl0": "http://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://api.twilio.com.evil.example/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://evil.example/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://user@api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://api.twilio.com:8443/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x" % (OTHER_ACCOUNT, 1, 10)},   # another account
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x?x=1" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x/" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x\n" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/SM%032x/Media/ME%032x" % (ACCOUNT, 1, 10)},    # not an MM
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032X/Media/ME%032x" % (ACCOUNT, 171, 10)},    # upper case
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%031x/Media/ME%032x" % (ACCOUNT, 1, 10)},    # short
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032x/../Media/ME%032x" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/MM%032x/Media/ME%032x.json" % (ACCOUNT, 1, 10)},
    {"MediaUrl0": ""},
])
def test_a_media_address_that_is_not_exactly_twilios_for_this_account_drops_the_whole_message(rig, change):
    r = rig()
    assert r.post(with_media(1, ("application/pdf",), **change))[0] == 200
    assert r.out.updates() == [] and r.store.window == {}


def test_the_message_sid_in_a_media_address_must_be_the_sid_of_the_message_that_carries_it(rig):
    r = rig()
    other = with_media(1, ("application/pdf",), MediaUrl0=media_url(2))              # the address of another message's medium
    assert r.post(other)[0] == 200 and r.out.updates() == []
    sm = with_media(3, ("application/pdf",), MessageSid="SM%032x" % 3)               # an SM message sid: the address (MM) cannot be its own
    assert r.post(sm)[0] == 200 and r.out.updates() == []
    assert r.post(with_media(4, ("application/pdf",)))[0] == 200 and len(r.out.updates()) == 1
    assert any("media" in line for line in r.logs), "a dropped message leaves a log line by class"


def test_a_message_with_a_medium_that_cannot_be_read_among_good_ones_is_dropped_whole(rig):
    r = rig()
    fields = with_media(1, ("application/pdf", "application/pdf"))
    fields["MediaUrl1"] = "https://evil.example/x"
    assert r.post(fields)[0] == 200 and r.out.updates() == []


def test_a_medium_the_count_promises_and_the_form_lacks_drops_the_message(rig):
    r = rig()
    fields = with_media(1, ("application/pdf",))
    fields["NumMedia"] = "2"
    assert r.post(fields)[0] == 200 and r.out.updates() == []


@pytest.mark.parametrize("count", ["11", "100", "-1"])
def test_a_count_over_ten_or_negative_drops_the_message(rig, count):
    r = rig()
    assert r.post(with_media(1, ("application/pdf",), NumMedia=count))[0] == 200 and r.out.updates() == []


@pytest.mark.parametrize("count", ["", "abc", "0", " 1", "1.0"])
def test_a_count_that_is_not_a_number_of_media_leaves_the_message_as_it_always_was(rig, count):
    r = rig()
    r.post(inbound(3, body=kit.TEXT, NumMedia=count, MediaUrl0=media_url(1)))
    assert [(u["text"], "attachments" in u) for u in r.out.updates()] == [(kit.TEXT, False)]


def test_a_medium_only_message_with_a_blank_count_is_still_ignored(rig):
    r = rig()
    r.post(inbound(4, body="", NumMedia="0", MediaUrl0=media_url(1)))
    assert r.out.updates() == []


def test_a_tap_with_media_fields_is_a_tap_only(rig):
    r = rig()
    r.post(kit.card_tap(5, NumMedia="1", MediaUrl0=media_url(1), MediaContentType0="application/pdf"))
    updates = r.out.updates()
    assert len(updates) == 1 and updates[0]["action"] == "7:approve" and "attachments" not in updates[0]


def test_a_title_with_no_payload_and_media_is_ignored_as_before(rig):
    r = rig()
    r.post(with_media(1, ("application/pdf",), ButtonText="Approve"))
    assert r.out.updates() == []


def test_a_medium_from_another_account_or_to_another_number_is_ignored(rig):
    r = rig()
    r.post(with_media(1, ("application/pdf",), account=OTHER_ACCOUNT))
    r.post(with_media(2, ("application/pdf",), To="whatsapp:+14155550199"))
    assert r.out.updates() == []


def test_a_duplicate_medium_message_is_dropped_also_after_a_restart(rig, tmp_path):
    r = rig()
    r.post(with_media(1))
    r.post(with_media(1))
    assert len(r.out.updates()) == 1
    r.stop()
    again = kit.Rig(tmp_path / "r0").start()
    try:
        again.post(with_media(1))
        assert again.out.updates() == []
    finally:
        again.stop()


def test_a_text_message_is_unchanged(rig):
    r = rig()
    r.post(inbound(9))
    assert [(u["text"], "attachments" in u) for u in r.out.updates()] == [(kit.TEXT, False)]


# --- the signature is unchanged ---------------------------------------------------------------------------------------------


def test_a_medium_message_with_a_missing_or_wrong_signature_is_refused_and_emits_nothing(rig):
    r = rig()
    fields = with_media(1)
    assert r.post(fields, header="")[0] == 403
    assert r.post(fields, token=WRONG)[0] == 403
    assert r.post(fields, url="https://other.example/" + kit.PATH)[0] == 403
    assert r.post(fields, header="bm90IGEgc2lnbmF0dXJl")[0] == 403
    assert r.out.updates() == [] and r.store.window == {}


def test_the_signature_covers_the_media_fields(rig):
    r = rig()
    fields = with_media(1)
    signature = kit.reference_signature(AUTH, kit.PUBLIC_URL, kit.as_pairs(fields))
    tampered = {**fields, "MediaUrl0": media_url(2)}
    assert r.post(tampered, header=signature)[0] == 403 and r.out.updates() == []


# --- fetch: the happy path ----------------------------------------------------------------------------------------------------


def test_the_address_is_rebuilt_from_the_ids_the_key_goes_to_api_twilio_com_and_the_cdn_gets_no_credential(rig, out):
    r = rig(media=MediaOpener(payload=BODY))
    done = r.fetch(5, REF, out, 10_000_000)
    assert done == {"id": 5, "ok": True, "bytes": len(BODY), "sha256": hashlib.sha256(BODY).hexdigest()}
    path = out / "content"
    assert path.read_bytes() == BODY and stat.S_IMODE(path.stat().st_mode) == 0o600 and os.listdir(out) == ["content"]
    first, second = r.media.calls
    assert first["url"] == API_URL and first["auth"] == BASIC and first["method"] == "GET" and first["timeout"] == 10.0
    assert second["url"] == r.media.cdn_url and second["auth"] is None and second["method"] == "GET"
    assert r.opener.calls == [], "no message is created by a fetch"


def test_a_medium_served_directly_with_no_redirect_is_taken_with_the_key_to_api_twilio_com_only(rig, out):
    r = rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: StreamResponse(BODY))]))
    assert r.fetch(1, REF, out, 10**7)["ok"] is True
    assert [c["url"] for c in r.media.calls] == [API_URL]


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_each_redirect_status_is_followed_once(rig, out, code):
    r = rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: redirect(f"https://{MEDIA_HOST}/x/y", code))], payload=BODY))
    assert r.fetch(1, REF, out, 10**7)["ok"] is True and len(r.media.calls) == 2


def test_the_second_media_host_twilio_documents_is_also_allowed(rig, out):
    r = rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: redirect("https://mms.twiliocdn.com/ACfake/token"))], payload=BODY))
    assert r.fetch(1, REF, out, 10**7)["ok"] is True and r.media.calls[1]["auth"] is None


def test_the_ids_in_the_ref_decide_the_address_and_the_account_is_the_settings(rig, out):
    r = rig(media=MediaOpener(payload=BODY))
    r.fetch(1, media_ref(7, 3), out, 10**7)
    message, media = media_ids(7, 3)
    assert r.media.calls[0]["url"] == f"https://api.twilio.com/2010-04-01/Accounts/{ACCOUNT}/Messages/{message}/Media/{media}"


# --- fetch: refusals ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("location", [
    "https://evil.example/x", "http://media.twiliocdn.com/x", "https://media.twiliocdn.com.evil.example/x", "https://evil.example/media.twiliocdn.com",
    "https://user@media.twiliocdn.com/x", "https://media.twiliocdn.com:8443/x", "https://api.twilio.com/x", "https://127.0.0.1/x", "/relative/path",
    "//media.twiliocdn.com/x", "ftp://media.twiliocdn.com/x", "https://evil.example\\@media.twiliocdn.com/x", "", None, "https://media.twiliocdn.com/x y",
])
def test_a_redirect_to_a_host_that_is_not_twilios_media_host_is_refused_and_never_requested(rig, out, location):
    r = rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: redirect(location))], payload=BODY))
    done = r.fetch(1, REF, out, 10**7)
    assert done["ok"] is False and done["kind"] == "failed"
    assert [c["url"] for c in r.media.calls] == [API_URL], "only the first request was made"
    assert leaks(r, KEY_SECRET, KEY_SID, BASIC, "evil.example") == [] and os.listdir(out) == []


def test_a_second_redirect_is_refused(rig, out):
    r = rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: redirect(f"https://{MEDIA_HOST}/a")), (MEDIA_HOST, lambda c: redirect(f"https://{MEDIA_HOST}/b"))]))
    done = r.fetch(1, REF, out, 10**7)
    assert done["ok"] is False and done["kind"] == "failed" and len(r.media.calls) == 2 and os.listdir(out) == []


def test_the_key_is_never_sent_to_the_cdn_even_when_the_cdn_is_asked_twice_or_answers_an_error(rig, out):
    r = rig(media=MediaOpener(rules=[(MEDIA_HOST, lambda c: http_error(403))]))
    assert r.fetch(1, REF, out, 10**7)["ok"] is False
    assert [c["auth"] for c in r.media.calls] == [BASIC, None]


def test_a_size_the_cdn_declares_over_the_cap_is_refused_before_a_byte_is_read(rig, out):
    body = StreamResponse(BODY, headers={"Content-Length": "99999999"})
    r = rig(media=MediaOpener(rules=[(MEDIA_HOST, lambda c: body)]))
    done = r.fetch(1, REF, out, 1_000_000)
    assert done["kind"] == "usage" and body.total == 0 and os.listdir(out) == []


def test_the_cap_is_enforced_mid_stream_when_nothing_was_declared(rig, out):
    body = EndlessResponse()
    r = rig(media=MediaOpener(rules=[(MEDIA_HOST, lambda c: body)]))
    done = r.fetch(1, REF, out, 300_000)
    assert done["ok"] is False and done["kind"] == "usage" and body.total <= 300_001 and os.listdir(out) == []


def test_a_file_exactly_the_cap_is_taken(rig, out):
    r = rig(media=MediaOpener(payload=b"a" * 4096))
    assert r.fetch(1, REF, out, 4096)["bytes"] == 4096


@pytest.mark.parametrize("ref", [
    "", "MM", f"{media_ids(1)[0]}", f"{media_ids(1)[0]}:", f":{media_ids(1)[1]}", f"{media_ids(1)[1]}:{media_ids(1)[0]}", f"SM{1:032x}:{media_ids(1)[1]}",
    f"{media_ids(11)[0].upper()}:{media_ids(11)[1]}", f"MM{1:031x}:{media_ids(1)[1]}", f"{media_ids(1)[0]}:{media_ids(1)[1]}\n",
    f"{media_ids(1)[0]}:{media_ids(1)[1]}/../x", f"{media_ids(1)[0]}/{media_ids(1)[1]}", f"{REF}:{REF}", f" {REF}", "../" + REF, f"MM{'g' * 32}:ME{'0' * 32}",
    "https://api.twilio.com/x", f"{REF}?x=1", f"{REF}#x",
])
def test_a_reference_that_is_not_exactly_message_sid_colon_media_sid_is_a_usage_error_with_no_request(rig, out, ref):
    r = rig(media=MediaOpener(payload=BODY))
    done = r.fetch(1, ref, out, 10**6)
    assert done["ok"] is False and done["kind"] == "usage" and r.media.calls == []


@pytest.mark.parametrize("request_fields", [
    {"ref": 5}, {"ref": "x" * 513}, {"max_bytes": 0}, {"max_bytes": -1}, {"max_bytes": True}, {"max_bytes": "9"}, {"out": ""}, {"out": 5},
])
def test_a_fetch_request_with_a_missing_or_wrong_field_is_a_usage_error(rig, out, request_fields):
    r = rig(media=MediaOpener(payload=BODY))
    r.pipe.send({"id": 3, "op": "fetch", "ref": REF, "out": str(out), "max_bytes": 1000, **request_fields})
    assert kit.wait_for(lambda: any(a["id"] == 3 for a in r.out.answers()))
    done = next(a for a in r.out.answers() if a["id"] == 3)
    assert done["ok"] is False and done["kind"] == "usage" and r.media.calls == []


def test_the_folder_must_be_a_real_absolute_one_and_content_is_never_replaced(rig, tmp_path, out):
    r = rig(media=MediaOpener(payload=BODY))
    (out / "content").write_bytes(b"keep me")
    assert r.fetch(1, REF, out, 10**6)["kind"] == "usage" and (out / "content").read_bytes() == b"keep me"
    link = tmp_path / "link"
    os.symlink(out, link)
    assert r.fetch(2, REF, link, 10**6)["kind"] == "usage"
    assert r.fetch(3, REF, "relative/folder", 10**6)["kind"] == "usage"
    assert r.fetch(4, REF, tmp_path / "missing", 10**6)["kind"] == "usage"


# --- fetch: a medium Twilio no longer serves -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [404, 410])
def test_twilio_saying_the_medium_does_not_exist_is_gone(rig, out, status):
    r = rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: http_error(status, 20404))]))
    done = r.fetch(1, REF, out, 10**6)
    assert done["ok"] is False and done["kind"] == "gone" and len(r.media.calls) == 1


@pytest.mark.parametrize("status", [404, 410])
def test_the_cdn_saying_the_medium_is_gone_is_gone(rig, out, status):
    r = rig(media=MediaOpener(rules=[(MEDIA_HOST, lambda c: http_error(status))]))
    assert r.fetch(1, REF, out, 10**6)["kind"] == "gone"


@pytest.mark.parametrize("status, code", [(401, 20003), (401, None), (403, 20003), (403, 20403)])
def test_a_refusal_of_the_key_on_the_media_path_fails_that_fetch_and_does_not_stop_the_provider(rig, out, status, code):
    r = opened(rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: http_error(status, code))])))
    done = r.fetch(1, REF, out, 10**6)
    assert done["ok"] is False and done["kind"] == "failed" and "permission to read media" in done["reason"]
    assert r.thread.is_alive() and r.result == [], "a key really revoked is caught by the next send"
    assert r.ask(2, PERSON, kit.plain("still here"))["ok"] is True


def test_a_key_that_may_not_read_media_is_a_failure_that_says_so_and_does_not_stop_the_provider(rig, out):
    r = rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: http_error(403, 20403, "planted-answer-text"))]))
    done = r.fetch(1, REF, out, 10**6)
    assert done["kind"] == "failed" and "403" in done["reason"] and "permission" in done["reason"] and "planted" not in json.dumps(done)
    assert r.thread.is_alive() and r.fetch(2, REF, out, 10**6)["kind"] == "failed"


def test_other_statuses_are_failed_with_the_numbers_only(rig, out):
    r = rig(media=MediaOpener(rules=[("api.twilio.com", lambda c: http_error(500, 20500, "planted-answer-text"))]))
    done = r.fetch(1, REF, out, 10**6)
    assert done["kind"] == "failed" and "500" in done["reason"] and "planted" not in json.dumps(r.out.lines)
    r2 = rig(media=MediaOpener(rules=[(MEDIA_HOST, lambda c: http_error(503, None, "planted-answer-text"))]))
    done = r2.fetch(1, REF, out, 10**6)
    assert done["kind"] == "failed" and "503" in done["reason"] and "planted" not in json.dumps(r2.out.lines)


# --- fetch: the key is in no error ---------------------------------------------------------------------------------------------------


SECRETS = (KEY_SECRET, KEY_SID, AUTH, BASIC, base64.b64encode(f"{KEY_SID}:{KEY_SECRET}".encode()).decode())


@pytest.mark.parametrize("error", [
    urllib.error.URLError("planted " + KEY_SECRET), urllib.error.URLError(OSError(KEY_SECRET)), OSError(KEY_SECRET), ValueError(KEY_SECRET),
    http.client.IncompleteRead(KEY_SECRET.encode(), 5), http.client.RemoteDisconnected(KEY_SECRET), http.client.BadStatusLine(KEY_SECRET),
    RuntimeError(KEY_SECRET),
])
@pytest.mark.parametrize("where", ["api.twilio.com", MEDIA_HOST])
def test_a_failure_at_either_host_names_the_kind_only_never_the_key(rig, out, error, where):
    r = rig(media=MediaOpener(rules=[(where, lambda c: error)]))
    done = r.fetch(1, REF, out, 10**6)
    assert done["ok"] is False and leaks(r, *SECRETS) == [] and r.thread.is_alive() and os.listdir(out) == []


def test_a_failure_in_the_middle_of_the_body_leaves_no_file_and_no_key(rig, out):
    body = StreamResponse(b"partial " * 100, error=http.client.IncompleteRead(KEY_SECRET.encode(), 9))
    r = rig(media=MediaOpener(rules=[(MEDIA_HOST, lambda c: body)]))
    done = r.fetch(1, REF, out, 10**6)
    assert done["kind"] == "failed" and leaks(r, *SECRETS) == [] and os.listdir(out) == []


def test_the_key_is_not_in_the_answer_of_a_success_either(rig, out):
    r = rig(media=MediaOpener(payload=BODY))
    r.fetch(1, REF, out, 10**6)
    assert leaks(r, *SECRETS) == []


# --- fetch: the real opener does not follow redirects ------------------------------------------------------------------------------------


class Redirecting(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        Redirecting.seen.append((self.path, self.headers.get("Authorization")))
        self.send_response(307)
        self.send_header("Location", "http://other.example/stolen")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_the_real_media_opener_hands_a_redirect_back_instead_of_following_it(monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    Redirecting.seen = []
    server = http.server.HTTPServer(("127.0.0.1", 0), Redirecting)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/m", headers={"Authorization": BASIC})
        with pytest.raises(urllib.error.HTTPError) as e:
            wt.MEDIA_OPENER.open(request, timeout=5)
        assert e.value.code == 307 and e.value.headers.get("Location") == "http://other.example/stolen"
        e.value.close()
        assert len(Redirecting.seen) == 1, "the redirect was not followed"
    finally:
        server.shutdown()
        server.server_close()


def test_the_default_wiring_uses_that_opener():
    assert any(isinstance(h, wt.NoRedirect) for h in wt.MEDIA_OPENER.handlers)
    assert wt.Twilio(KEY_SID, KEY_SECRET, ACCOUNT).media_opener is wt.MEDIA_OPENER


# --- fetch: the listener's behaviour -----------------------------------------------------------------------------------------------------


def opened(r):
    r.post(inbound(40))
    assert kit.wait_for(lambda: len(r.out.updates()) == 1)
    return r


def test_a_slow_fetch_does_not_hold_up_a_send(rig, out):
    gate = threading.Event()

    def slow(call):
        gate.wait(15)
        return StreamResponse(BODY)
    r = opened(rig(media=MediaOpener(rules=[("api.twilio.com", slow)])))
    r.fetch(7, REF, out, 10**6, wait=False)
    assert kit.wait_for(lambda: len(r.media.calls) == 1)
    assert r.ask(8, PERSON, kit.plain("hello"))["ok"] is True
    assert not any(a["id"] == 7 for a in r.out.answers())
    gate.set()
    assert kit.wait_for(lambda: any(a["id"] == 7 for a in r.out.answers()))
    assert next(a for a in r.out.answers() if a["id"] == 7)["ok"] is True


def test_an_unexpected_exception_in_a_fetch_is_answered_without_text_and_the_provider_goes_on(rig, out, monkeypatch):
    r = opened(rig(media=MediaOpener(payload=BODY)))
    monkeypatch.setattr(r.listener.api, "fetch_media", lambda *a: (_ for _ in ()).throw(RuntimeError("planted-" + KEY_SECRET)))
    done = r.fetch(1, REF, out, 10**6)
    assert done["ok"] is False and done["kind"] == "failed" and leaks(r, KEY_SECRET, "planted-") == []
    assert r.ask(2, PERSON, kit.plain("still here"))["ok"] is True


def test_a_request_with_another_op_is_still_a_usage_error(rig):
    r = rig()
    r.pipe.send({"id": 4, "op": "delete"})
    assert kit.wait_for(lambda: any(a["id"] == 4 for a in r.out.answers()))
    done = next(a for a in r.out.answers() if a["id"] == 4)
    assert done["kind"] == "usage" and done["ok"] is False


def test_the_sends_are_unchanged(rig):
    r = opened(rig())
    done = r.ask(1, PERSON, kit.plain("a note"))
    assert done["ok"] is True and r.opener.texts()[-1]["Body"] == "a note"


def test_a_fetch_before_any_message_works_because_it_needs_no_window(rig, out):
    r = rig(media=MediaOpener(payload=BODY))
    assert r.fetch(1, REF, out, 10**6)["ok"] is True
