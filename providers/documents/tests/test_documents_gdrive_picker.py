"""Tests of the one-shot loopback page that runs the Google Picker (providers/documents/gdrive_picker.py): the session refuses a
request with a wrong Host header, a callback with a wrong state, a second callback, a page or a token without its nonce, a post
from another origin and a second post; it stops after the pick; and the page it serves asks for folders to open and not to be
picked, several files at once, and holds no token. No Google host is ever reached: the exchange is a stand-in function, and the
suite's conftest refuses any address that is not loopback.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_gdrive_picker.py
"""
from __future__ import annotations

import http.client
import importlib.util
import json
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
_spec = importlib.util.spec_from_file_location("gdrive_picker_under_test", REPO / "providers" / "documents" / "gdrive_picker.py")
picker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(picker)

SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN = "fake-access-token-not-real"
IDS = ["1AaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaA", "1BbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbB", "1CcccccccccccccccccccccccccccccccccccccC"]


class Session:
    """One server on a free port with stand-in exchange and storage, and a small browser (http.client, no redirect followed)."""

    def __init__(self, access_token=None, response=None):
        self.exchanged, self.stored, self.urls = [], [], []
        reply = response or {"access_token": TOKEN, "refresh_token": "fake-refresh-token-not-real", "scope": SCOPE}

        def exchange(code, redirect_uri):
            self.exchanged.append((code, redirect_uri))
            return dict(reply)

        self.server = picker.OneShotServer(api_key="fake-api-key", project_number="123456789012", scope=SCOPE, access_token=access_token,
                                           authorize_url=lambda redirect, state: self._authorize(redirect, state), exchange=exchange,
                                           on_token=self.stored.append)
        self.server.serve()

    def _authorize(self, redirect, state):
        url = "https://accounts.example/auth?" + urllib.parse.urlencode({"redirect_uri": redirect, "state": state})
        self.urls.append(url)
        return url

    def req(self, method, path, body=None, host="default", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        head = dict(headers or {})
        if host != "default":
            head["Host"] = host
        data = None
        if body is not None:
            data = json.dumps(body).encode() if not isinstance(body, bytes) else body
            head.setdefault("Content-Type", "application/json")
        conn.request(method, path, body=data, headers=head)
        res = conn.getresponse()
        out = (res.status, dict(res.getheaders()), res.read())
        conn.close()
        return out

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def callback(self, state=None, code="fake-code", **kw):
        query = {"code": code, "state": self.server.state if state is None else state}
        return self.get("/?" + urllib.parse.urlencode(query), **kw)

    def to_picker(self):
        """The whole way to the open page: /start, the callback, and the nonce of the page the callback redirects to."""
        status, head, _ = self.get("/start")
        assert status == 302
        status, head, _ = self.callback()
        assert status == 302 and head["Location"].startswith("/picker?n=")
        return urllib.parse.parse_qs(urllib.parse.urlparse(head["Location"]).query)["n"][0]

    def close(self):
        try:
            self.server.close()
        except Exception:
            pass


@pytest.fixture
def session():
    s = Session()
    yield s
    s.close()


def test_the_start_sends_the_browser_to_google_with_the_servers_own_state(session):
    status, head, _ = session.get("/start")
    assert status == 302 and head["Location"] == session.urls[0]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(head["Location"]).query)
    assert query["state"] == [session.server.state] and query["redirect_uri"] == [f"http://127.0.0.1:{session.server.port}"]


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1", "localhost:%d", "127.0.0.1:1", "", "127.0.0.1:%d.evil.example"])
def test_a_request_with_the_wrong_host_header_is_refused_on_every_path(session, host):
    host = host.replace("%d", str(session.server.port))
    nonce = session.server.nonce
    for method, path in (("GET", "/start"), ("GET", "/"), ("GET", f"/picker?n={nonce}"), ("GET", f"/token?n={nonce}"),
                         ("POST", "/picked"), ("GET", "/anything")):
        status, _, body = session.req(method, path, body={"n": nonce} if method == "POST" else None, host=host)
        assert status == 403 and body == b"", (method, path, host)
    assert session.exchanged == [] and not session.server.done.is_set(), "nothing happened"


def test_a_callback_with_the_wrong_state_ends_the_session_and_stores_nothing(session):
    status, _, body = session.callback(state="not-the-state")
    assert status == 401 and b"State mismatch" in body
    assert session.exchanged == [] and session.stored == [] and session.server.access_token is None
    assert session.server.done.is_set() and "state" in session.server.error
    assert session.callback()[0] == 404, "the right state after the wrong one is a second callback: refused"


def test_the_callback_is_served_once(session):
    session.to_picker()
    assert session.callback()[0] == 404 and len(session.exchanged) == 1 and len(session.stored) == 1


def test_a_callback_that_carries_an_error_or_no_code_ends_the_session(session):
    status, _, _ = session.get("/?" + urllib.parse.urlencode({"error": "access_denied", "state": session.server.state}))
    assert status == 400 and session.exchanged == [] and session.server.error
    other = Session()
    try:
        assert other.get("/?" + urllib.parse.urlencode({"state": other.server.state}))[0] == 400
        assert other.server.error == "the callback carried no code"
    finally:
        other.close()


def test_a_consent_that_granted_more_or_less_than_drive_file_stores_nothing():
    for scope in (SCOPE + " https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/drive.readonly", ""):
        s = Session(response={"access_token": TOKEN, "refresh_token": "r", "scope": scope})
        try:
            status, _, _ = s.callback()
            assert status == 400 and s.stored == [] and s.server.access_token is None and "only" in s.server.error
        finally:
            s.close()


def test_the_page_and_the_token_need_the_nonce_and_the_token_is_served_a_few_times_only(session):
    nonce = session.to_picker()
    assert session.get("/picker")[0] == 403 and session.get("/picker?n=wrong")[0] == 403
    assert session.get("/token")[0] == 403 and session.get("/token?n=wrong")[0] == 403
    status, head, body = session.get(f"/token?n={nonce}")
    assert status == 200 and json.loads(body) == {"token": TOKEN, "apiKey": "fake-api-key", "appId": "123456789012"}
    assert head["Cache-Control"] == "no-store"
    for _ in range(picker.TOKEN_SERVED_MAX - 1):
        assert session.get(f"/token?n={nonce}")[0] == 200
    assert session.get(f"/token?n={nonce}")[0] == 403


def test_the_page_asks_for_several_files_and_never_for_a_folder_and_holds_no_token(session):
    nonce = session.to_picker()
    status, head, body = session.get(f"/picker?n={nonce}")
    page = body.decode()
    assert status == 200 and "MULTISELECT_ENABLED" in page and ".setSelectFolderEnabled(false)" in page
    assert "setSelectFolderEnabled(true)" not in page
    assert TOKEN not in page and "fake-api-key" not in page and "fake-refresh-token" not in page, "the page is fetched without a secret"
    assert json.dumps(nonce) in page
    assert head["Referrer-Policy"] == "no-referrer" and head["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in head["Content-Security-Policy"] and head["X-Content-Type-Options"] == "nosniff"


def test_the_picks_are_checked_and_the_session_stops_after_them(session):
    nonce = session.to_picker()
    documents = [
        {"id": IDS[0], "name": "Survey results\n(final)", "mimeType": "application/vnd.google-apps.spreadsheet"},
        {"id": IDS[1], "name": "Reports", "mimeType": picker.FOLDER_MIME},                 # a folder is dropped
        {"id": "short", "name": "bad id", "mimeType": "application/pdf"},                    # an id of the wrong shape is dropped
        {"id": IDS[2], "name": "report.pdf", "mimeType": "application/pdf"},
        {"id": IDS[0], "name": "again", "mimeType": "application/pdf"},                      # a repeat is dropped
        {"id": IDS[1] + "x", "name": "odd type", "mimeType": "x"}, "not an object",
    ]
    status, _, body = session.req("POST", "/picked", body={"n": nonce, "cancelled": False, "documents": documents})
    assert status == 200 and json.loads(body) == {"ok": True, "picked": 2}
    assert session.server.picks == [{"id": IDS[0], "name": "Survey results (final)", "mime_type": "application/vnd.google-apps.spreadsheet"},
                                    {"id": IDS[2], "name": "report.pdf", "mime_type": "application/pdf"}]
    assert session.server.done.is_set() and session.server.error is None and session.server.cancelled is False
    assert session.req("POST", "/picked", body={"n": nonce, "documents": documents})[0] == 409
    assert session.get(f"/token?n={nonce}")[0] == 403, "no token after the pick"
    session.server.close()
    with pytest.raises(OSError):
        session.get("/start")


def test_a_cancel_is_a_session_that_ends_with_no_picks(session):
    nonce = session.to_picker()
    assert session.req("POST", "/picked", body={"n": nonce, "cancelled": True, "documents": []})[0] == 200
    assert session.server.cancelled is True and session.server.picks == [] and session.server.done.is_set()


def test_a_post_needs_the_nonce_the_own_origin_and_a_reasonable_body(session):
    nonce = session.to_picker()
    good = {"n": nonce, "cancelled": False, "documents": []}
    assert session.req("POST", "/picked", body={**good, "n": "wrong"})[0] == 403
    assert session.req("POST", "/picked", body=good, headers={"Origin": "https://evil.example"})[0] == 403
    assert session.req("POST", "/picked", body=good, headers={"Origin": f"http://127.0.0.1:{session.server.port + 1}"})[0] == 403
    assert session.req("POST", "/other", body=good)[0] == 403
    assert session.req("POST", "/picked", body=b"{not json")[0] == 400
    assert session.req("POST", "/picked", body=b"x" * (picker.BODY_MAX + 1))[0] == 413
    assert not session.server.done.is_set(), "none of those ended the session"
    assert session.req("POST", "/picked", body=good, headers={"Origin": f"http://127.0.0.1:{session.server.port}"})[0] == 200


def test_a_post_before_a_token_is_held_is_refused(session):
    assert session.req("POST", "/picked", body={"n": session.server.nonce, "documents": []})[0] == 403


def test_a_later_pick_with_a_held_token_has_no_callback_at_all():
    s = Session(access_token=TOKEN)
    try:
        status, head, _ = s.get("/start")
        assert status == 302 and head["Location"].startswith("/picker?n=") and s.urls == []
        assert s.callback()[0] == 404 and s.exchanged == []
        nonce = urllib.parse.parse_qs(urllib.parse.urlparse(head["Location"]).query)["n"][0]
        assert s.get(f"/picker?n={nonce}")[0] == 200
    finally:
        s.close()


def test_the_picks_helper_keeps_only_what_has_the_expected_shape():
    assert picker.clean_picks([]) == []
    with pytest.raises(ValueError):
        picker.clean_picks({"id": IDS[0]})
    many = [{"id": f"1{i:0>38}", "name": "n", "mimeType": "application/pdf"} for i in range(picker.PICKS_MAX + 20)]
    assert len(picker.clean_picks(many)) == picker.PICKS_MAX
    long_name = picker.clean_picks([{"id": IDS[0], "name": "x" * 1000, "mimeType": "application/pdf"}])[0]["name"]
    assert len(long_name) == picker.NAME_MAX


def test_a_session_without_a_token_must_be_able_to_ask_for_one():
    with pytest.raises(ValueError):
        picker.OneShotServer(api_key="k", project_number="1", scope=SCOPE)
