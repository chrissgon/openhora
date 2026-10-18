"""Offline tests for the attachments of providers/messenger/telegram.py (ATT-2): the mapping of what a sender sends, and the
`fetch-attachment` verb. The Bot API is a fake opener; two tests use a real server on the loopback port to see a real redirect.
No network, no real token.

Run: uv run --with pytest pytest providers/messenger/tests
"""
from __future__ import annotations

import hashlib
import http.client
import http.server
import importlib.util
import io
import json
import os
import stat
import sys
import threading
import time
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "telegram.py"
RUNTIME = Path(__file__).resolve().parents[3] / "runtime"
TOKEN = "123456789:FAKE-token-AAAAAAAAAAAAAAAAAAAA-never-print-me"
spec = importlib.util.spec_from_file_location("messenger_telegram_attachments_under_test", SCRIPT)
telegram = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = telegram
spec.loader.exec_module(telegram)

FILE_ID = "BQACAgQAAxkBAAIBZ2Fake_file-id-0001"
PDF = b"%PDF-1.4 a small fictional file " * 20


class Answer:
    def __init__(self, result):
        self.body = json.dumps({"ok": True, "result": result}).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        return self.body


class Stream:
    """A file download: the chunks it yields, the headers it answers, every size asked of read()."""

    def __init__(self, *chunks, length=None, fail=None):
        self.chunks, self.asked, self.fail = list(chunks), [], fail
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        self.asked.append(size)
        if not self.chunks:
            if self.fail is not None:
                raise self.fail
            return b""
        chunk = self.chunks.pop(0)
        if isinstance(chunk, BaseException):
            raise chunk
        if size is not None and 0 <= size < len(chunk):
            self.chunks.insert(0, chunk[size:])
            return chunk[:size]
        return chunk


class Opener:
    """Answers each call from a queue: a result (a JSON answer), a Stream, or an exception to raise. Records every request."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def open(self, request, timeout=None):
        self.requests.append((request.full_url, request.get_method(), dict(request.header_items()), timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer if isinstance(answer, Stream) else Answer(answer)


@pytest.fixture(autouse=True)
def token(monkeypatch):
    monkeypatch.setenv("MESSENGER_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.delenv("MESSENGER_TELEGRAM_API_BASE", raising=False)


def run(monkeypatch, capsys, opener, *argv):
    monkeypatch.setattr(telegram, "OPENER", opener)
    code = telegram.main(list(argv))
    seen = capsys.readouterr()
    return code, seen.out, seen.err


def fetch(monkeypatch, capsys, opener, out, ref=FILE_ID, cap=1_000_000):
    return run(monkeypatch, capsys, opener, "fetch-attachment", "--platform", "telegram", "--ref", ref, "--out", str(out),
               "--max-bytes", str(cap))


def got_file(path="documents/file_7.pdf", size=len(PDF)):
    return {"file_id": FILE_ID, "file_unique_id": "AgADu", "file_size": size, "file_path": path}


def http_error(status, description, url=None):
    url = url or f"https://api.telegram.org/bot{TOKEN}/getFile"
    return urllib.error.HTTPError(url, status, "x", {}, io.BytesIO(json.dumps({"ok": False, "description": description}).encode()))


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir(mode=0o700)
    return folder


# --- the mapping ---------------------------------------------------------------------------------------------------------

def message(**fields):
    base = {"message_id": 5, "from": {"id": 4242}, "chat": {"id": 4242, "type": "private"}}
    return {"update_id": 20, "message": {**base, **fields}}


def mapped(**fields):
    return telegram.mapped(message(**fields))


def test_capabilities_declare_attachments_and_the_bot_api_download_cap(monkeypatch, capsys):
    sys.path.insert(0, str(RUNTIME))
    import messaging_provider as provider
    caps = telegram.CAPABILITIES
    assert caps["attachments"] is True and type(caps["max_attachment_bytes"]) is int
    assert caps["max_attachment_bytes"] == 20 * 1024 * 1024
    for key, kind in provider.OPTIONAL_KEYS.items():
        if key in caps:
            assert type(caps[key]) is kind, key
    code, out, _ = run(monkeypatch, capsys, Opener(), "capabilities", "--platform", "telegram")
    assert code == 0 and json.loads(out) == caps


def test_a_document_maps_with_its_name_size_media_type_and_the_file_id_as_ref():
    found = mapped(document={"file_id": FILE_ID, "file_unique_id": "u", "file_name": "report.pdf", "mime_type": "application/pdf",
                             "file_size": 4096})
    assert found["attachments"] == [{"ref": FILE_ID, "name": "report.pdf", "size": 4096, "type": "application/pdf"}]
    assert found["text"] is None and found["sender"] == "4242" and found["private"] is True


def test_a_caption_is_the_text_and_the_update_passes_the_bridges_check():
    sys.path.insert(0, str(RUNTIME))
    import messaging_provider as provider
    found = mapped(document={"file_id": FILE_ID, "file_name": "plan.docx", "file_size": 10}, caption="@plan-brief")
    assert found["text"] == "@plan-brief"
    checked = provider.valid_update(found)
    assert checked["attachments"] == [{"ref": FILE_ID, "name": "plan.docx", "size": 10, "type": None}]
    assert checked["text"] == "@plan-brief"


def test_a_photo_is_named_photo_and_the_largest_size_is_the_one_taken():
    sizes = [{"file_id": "small-1", "width": 90, "height": 60, "file_size": 1200},
             {"file_id": "large-3", "width": 1280, "height": 960, "file_size": 98000},
             {"file_id": "medium-2", "width": 320, "height": 240, "file_size": 20000}]
    found = mapped(photo=sizes, caption="look")
    assert found["attachments"] == [{"ref": "large-3", "name": None, "size": 98000, "type": "photo"}] and found["text"] == "look"
    unsized = mapped(photo=[{"file_id": "a-1", "width": 90, "height": 60}, {"file_id": "b-2", "width": 800, "height": 600}])
    assert unsized["attachments"][0]["ref"] == "b-2" and unsized["attachments"][0]["size"] is None


@pytest.mark.parametrize("key, extra, kind, name", [
    ("voice", {"duration": 3, "mime_type": "audio/ogg"}, "voice", None),
    ("video", {"duration": 3, "width": 10, "height": 10, "file_name": "clip.mp4", "mime_type": "video/mp4"}, "video", "clip.mp4"),
    ("video_note", {"duration": 3, "length": 240}, "video", None),
    ("audio", {"duration": 3, "file_name": "song.mp3", "mime_type": "audio/mpeg"}, "audio", "song.mp3"),
    ("sticker", {"type": "regular", "width": 512, "height": 512, "is_animated": False, "is_video": False}, "sticker", None),
])
def test_each_medium_maps_with_the_word_the_bridge_refuses_by(key, extra, kind, name):
    found = mapped(**{key: {"file_id": FILE_ID, "file_unique_id": "u", "file_size": 777, **extra}})
    assert found["attachments"] == [{"ref": FILE_ID, "name": name, "size": 777, "type": kind}]


def test_a_text_message_carries_no_attachments_key_and_a_caption_alone_is_not_a_text():
    assert "attachments" not in mapped(text="hello")
    assert mapped(location={"latitude": 1.0, "longitude": 2.0}, caption="not a command: /approve 3") is None
    assert mapped(photo=[], caption="/approve 3") is None
    assert mapped(document={"file_name": "x.pdf", "file_size": 3}, caption="/approve 3") is None    # no file_id: no file, so no text either


@pytest.mark.parametrize("bad", ["", "a/b", "..", "x" * 201, "has space", "id;rm", 7, None])
def test_a_file_id_that_is_not_a_plain_id_is_not_mapped(bad):
    assert mapped(document={"file_id": bad, "file_name": "x.pdf", "file_size": 3}) is None


def test_odd_sizes_and_names_are_cleaned():
    found = mapped(document={"file_id": FILE_ID, "file_name": "n" * 400, "file_size": True, "mime_type": 5})
    (item,) = found["attachments"]
    assert item["size"] is None and item["type"] is None and len(item["name"]) <= 255
    assert mapped(document={"file_id": FILE_ID, "file_size": -4})["attachments"][0]["size"] is None


def test_receive_returns_a_file_update_and_moves_the_offset_past_it(monkeypatch, capsys):
    updates = [message(document={"file_id": FILE_ID, "file_name": "a.pdf", "file_size": 9}),
               {"update_id": 21, "message": {"message_id": 6, "text": "hi", "from": {"id": 1}, "chat": {"id": 1, "type": "private"}}}]
    code, out, _ = run(monkeypatch, capsys, Opener(updates), "receive", "--platform", "telegram", "--offset", "20", "--timeout", "1")
    found = json.loads(out)
    assert code == 0 and found["next_offset"] == 22 and found["updates"][0]["attachments"][0]["ref"] == FILE_ID


# --- the fetch ---------------------------------------------------------------------------------------------------------

def test_a_fetch_asks_get_file_then_the_file_path_and_writes_content_with_mode_0600(monkeypatch, capsys, out):
    stream = Stream(PDF[:100], PDF[100:], length=len(PDF))
    opener = Opener(got_file(), stream)
    code, printed, err = fetch(monkeypatch, capsys, opener, out)
    assert code == 0 and json.loads(printed) == {"bytes": len(PDF), "sha256": hashlib.sha256(PDF).hexdigest()}
    content = out / "content"
    assert content.read_bytes() == PDF and stat.S_IMODE(content.stat().st_mode) == 0o600
    assert [p.name for p in out.iterdir()] == ["content"]
    (get_file_url, get_file_method, _, _), (file_url, file_method, file_headers, timeout) = opener.requests
    assert get_file_url == f"https://api.telegram.org/bot{TOKEN}/getFile" and get_file_method == "POST"
    assert file_url == f"https://api.telegram.org/file/bot{TOKEN}/documents/file_7.pdf" and file_method == "GET"
    assert timeout == telegram.CONNECT_SECONDS and not {k.lower() for k in file_headers} & {"authorization", "cookie"}
    assert TOKEN not in printed + err


def test_the_bytes_are_asked_for_in_bounded_chunks_never_the_whole_body(monkeypatch, capsys, out):
    stream = Stream(PDF, length=len(PDF))
    code, _, _ = fetch(monkeypatch, capsys, Opener(got_file(), stream), out, cap=len(PDF) + 5)
    assert code == 0 and all(0 < size <= telegram.CHUNK_BYTES for size in stream.asked), stream.asked
    assert max(stream.asked) <= telegram.CHUNK_BYTES


def test_a_declared_size_over_the_cap_is_refused_before_any_download(monkeypatch, capsys, out):
    opener = Opener(got_file(size=5000))
    code, printed, err = fetch(monkeypatch, capsys, opener, out, cap=4999)
    assert code == 2 and printed == "" and len(opener.requests) == 1 and not list(out.iterdir())
    assert "5000" in err and TOKEN not in err


def test_a_content_length_over_the_cap_is_refused_before_the_body_is_read(monkeypatch, capsys, out):
    stream = Stream(b"x" * 10, length=999_999)
    code, _, err = fetch(monkeypatch, capsys, Opener({"file_path": "documents/a.bin"}, stream), out, cap=1000)
    assert code == 2 and stream.asked == [] and not list(out.iterdir()) and TOKEN not in err


def test_the_cap_is_enforced_mid_stream_when_nothing_was_declared_and_the_partial_file_is_removed(monkeypatch, capsys, out):
    stream = Stream(*[b"y" * 400 for _ in range(10)])
    code, printed, err = fetch(monkeypatch, capsys, Opener({"file_path": "documents/a.bin"}, stream), out, cap=1000)
    assert code == 2 and printed == "" and not list(out.iterdir())
    assert sum(min(s, 400) for s in stream.asked) <= 1000 + 400 and TOKEN not in err
    assert "at most 1000" in err


def test_a_body_that_lies_about_its_declared_size_is_caught_mid_stream(monkeypatch, capsys, out):
    stream = Stream(b"z" * 600, b"z" * 600, length=10)    # says 10, sends 1200
    code, _, _ = fetch(monkeypatch, capsys, Opener({"file_path": "documents/a.bin"}, stream), out, cap=1000)
    assert code == 2 and not list(out.iterdir())


def test_a_body_shorter_than_its_content_length_fails_and_leaves_nothing(monkeypatch, capsys, out):
    stream = Stream(b"a" * 50, length=100)
    code, printed, _ = fetch(monkeypatch, capsys, Opener({"file_path": "documents/a.bin"}, stream), out)
    assert code == 1 and printed == "" and not list(out.iterdir())


def test_a_slow_download_stops_at_the_whole_fetch_deadline(monkeypatch, capsys, out):
    ticks = iter([0.0])
    monkeypatch.setattr(telegram, "clock", lambda: next(ticks, 500.0))      # the first reading starts the fetch, every later one is far past the deadline
    code, _, err = fetch(monkeypatch, capsys, Opener({"file_path": "documents/a.bin"}, Stream(b"a" * 10, b"b" * 10, b"c" * 10)), out)
    assert code == 1 and "took longer" in err and not list(out.iterdir())


@pytest.mark.parametrize("failure", [
    http_error(400, "Bad Request: wrong file_id or the file is temporarily unavailable"),
])
def test_a_file_id_telegram_no_longer_knows_is_gone(monkeypatch, capsys, out, failure):
    code, printed, err = fetch(monkeypatch, capsys, Opener(failure), out)
    assert code == 1 and printed == "" and err.startswith("gone") and TOKEN not in err and not list(out.iterdir())


def test_a_file_that_is_not_served_at_its_path_is_gone(monkeypatch, capsys, out):
    url = f"https://api.telegram.org/file/bot{TOKEN}/documents/file_7.pdf"
    code, printed, err = fetch(monkeypatch, capsys, Opener(got_file(), http_error(404, "Not Found", url)), out)
    assert code == 1 and printed == "" and err.startswith("gone") and TOKEN not in err and not list(out.iterdir())


def test_gone_is_the_first_word_of_a_stderr_that_the_bridges_tail_still_holds(monkeypatch, capsys, out):
    code, _, err = fetch(monkeypatch, capsys, Opener(http_error(400, "Bad Request: wrong file_id")), out)
    assert code == 1 and err.startswith("gone") and len(err.strip().splitlines()) == 1 and len(err) < 300     # resolve.py keeps the last 300 characters


def test_a_file_telegram_says_is_too_big_is_an_over_the_cap_refusal(monkeypatch, capsys, out):
    code, _, err = fetch(monkeypatch, capsys, Opener(http_error(400, "Bad Request: file is too big")), out)
    assert code == 2 and not err.startswith("gone") and not list(out.iterdir())


def test_a_refused_token_on_get_file_is_not_configured_and_names_no_token(monkeypatch, capsys, out):
    code, _, err = fetch(monkeypatch, capsys, Opener(http_error(401, f"Unauthorized {TOKEN}")), out)
    assert code == 3 and TOKEN not in err


# --- the address is built, never taken ---------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "documents/../../x", "https://attacker.example/x", "//attacker.example/x",
                                  "documents/a b", "documents/a?x=1", "documents/a#f", "documents/a\\b", "a@attacker.example/x", "documents//a",
                                  "", ".hidden", "x" * 300, "documents/%2e%2e/x"])
def test_a_file_path_that_is_not_a_plain_relative_path_is_never_requested(monkeypatch, capsys, out, path):
    opener = Opener({"file_id": FILE_ID, "file_path": path})
    code, _, err = fetch(monkeypatch, capsys, opener, out)
    assert code == 1 and len(opener.requests) == 1 and not list(out.iterdir()), path     # only getFile went out
    assert TOKEN not in err


def test_the_file_url_must_stay_on_the_bot_api_host():
    base = telegram.DEFAULT_API_BASE
    assert telegram.file_url_allowed(f"{base}/file/bot{TOKEN}/documents/a.pdf", base, False)
    for url in (f"https://api.telegram.org.attacker.example/file/bot{TOKEN}/a", f"http://api.telegram.org/file/bot{TOKEN}/a",
                f"https://attacker.example/file/bot{TOKEN}/a", f"https://api.telegram.org@attacker.example/file/bot{TOKEN}/a",
                f"https://user:pw@api.telegram.org/file/bot{TOKEN}/a", f"https://api.telegram.org:8443/file/bot{TOKEN}/a",
                f"https://api.telegram.org/other/bot{TOKEN}/a", f"https://cdn.telegram.org/file/bot{TOKEN}/a"):
        assert not telegram.file_url_allowed(url, base, False), url


def test_no_redirect_is_followed_and_the_error_names_no_address():
    handler = telegram.RefuseRedirect()
    with pytest.raises(telegram.ProviderError) as e:
        handler.redirect_request(None, io.BytesIO(b""), 302, "Found", {}, "https://attacker.example/steal")
    assert "redirect" in str(e.value) and "attacker" not in str(e.value) and TOKEN not in str(e.value)
    assert any(isinstance(h, telegram.RefuseRedirect) for h in telegram.OPENER.handlers)


class Site(http.server.BaseHTTPRequestHandler):
    """A loopback Bot API: getFile answers a path, the file path answers `behaviour`."""

    behaviour = "redirect"
    other_port = 0
    hits = []

    def log_message(self, *args):
        pass

    getfile = "file"

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.hits.append(("POST", self.path))
        if self.getfile == "gone":
            body = json.dumps({"ok": False, "error_code": 400, "description": "Bad Request: wrong file_id or the file is temporarily unavailable"}).encode()
            self.send_response(400)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps({"ok": True, "result": {"file_id": FILE_ID, "file_size": 5, "file_path": "documents/file_9.txt"}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.hits.append(("GET", self.path, self.headers.get("Authorization")))
        if self.behaviour == "redirect":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.other_port}/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.behaviour == "drip":      # one byte every 0.4 s: a read that waits for a whole chunk would outlive the deadline
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(0.4)
            except OSError:
                pass
            return
        self.send_response(200)
        self.send_header("Content-Length", "5")
        self.end_headers()
        self.wfile.write(b"hello")


def serve(handler):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_real_redirect_off_the_host_is_refused_and_the_other_host_is_never_asked(monkeypatch, capsys, out):
    other_hits = []

    class Other(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            other_hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    other, site_hits = serve(Other), []
    handler = type("S", (Site,), {"behaviour": "redirect", "other_port": other.server_address[1], "hits": site_hits})
    site = serve(handler)
    try:
        monkeypatch.setenv("MESSENGER_TELEGRAM_API_BASE", f"http://127.0.0.1:{site.server_address[1]}")
        code, printed, err = run(monkeypatch, capsys, telegram.OPENER, "fetch-attachment", "--platform", "telegram", "--ref", FILE_ID,
                                 "--out", str(out), "--max-bytes", "1000")
    finally:
        site.shutdown()
        other.shutdown()
    assert code == 1 and printed == "" and "redirect" in err and TOKEN not in err and not list(out.iterdir())
    assert other_hits == [] and [h[0] for h in site_hits] == ["POST", "GET"]


def test_a_host_that_drips_one_byte_at_a_time_cannot_outlive_the_deadline(monkeypatch, capsys, out):
    site = serve(type("S", (Site,), {"behaviour": "drip", "hits": []}))
    monkeypatch.setattr(telegram, "FETCH_TOTAL_SECONDS", 1)
    try:
        monkeypatch.setenv("MESSENGER_TELEGRAM_API_BASE", f"http://127.0.0.1:{site.server_address[1]}")
        began = time.time()
        code, printed, err = run(monkeypatch, capsys, telegram.OPENER, "fetch-attachment", "--platform", "telegram", "--ref", FILE_ID,
                                 "--out", str(out), "--max-bytes", "100000")
        took = time.time() - began
    finally:
        site.shutdown()
    assert code == 1 and printed == "" and "took longer" in err and not list(out.iterdir())
    assert took < 4, took      # a blocking read(65536) would wait for the host to stop dripping (16 s)


def test_read_some_prefers_read1_and_falls_back_to_read():
    class Both:
        def read1(self, n):
            return b"one"

        def read(self, n):
            return b"all"

    class OnlyRead:
        def read(self, n):
            return b"all"

    assert telegram.read_some(Both(), 10) == b"one" and telegram.read_some(OnlyRead(), 10) == b"all"


def test_a_content_length_that_is_not_ascii_digits_is_not_read():
    assert telegram._declared_length(type("R", (), {"headers": {"Content-Length": "\u0663\u0664"}})()) is None
    assert telegram._declared_length(type("R", (), {"headers": {"Content-Length": "34"}})()) == 34
    assert telegram._declared_length(type("R", (), {"headers": {"Content-Length": "9" * 19}})()) is None


def test_a_real_download_over_loopback_with_the_real_opener(monkeypatch, capsys, out):
    hits = []
    site = serve(type("S", (Site,), {"behaviour": "file", "hits": hits}))
    try:
        monkeypatch.setenv("MESSENGER_TELEGRAM_API_BASE", f"http://127.0.0.1:{site.server_address[1]}")
        code, printed, err = run(monkeypatch, capsys, telegram.OPENER, "fetch-attachment", "--platform", "telegram", "--ref", FILE_ID,
                                 "--out", str(out), "--max-bytes", "1000")
    finally:
        site.shutdown()
    assert code == 0, err
    assert json.loads(printed) == {"bytes": 5, "sha256": hashlib.sha256(b"hello").hexdigest()} and (out / "content").read_bytes() == b"hello"
    assert hits[1][1] == f"/file/bot{TOKEN}/documents/file_9.txt" and hits[1][2] is None


def test_the_script_as_a_process_prints_the_answer_and_gone_is_the_first_word_of_stderr(tmp_path):
    """What the bridge sees across the process boundary: stdout JSON and exit 0, or exit 1 with `gone` first on stderr (providers/resolve.py keeps
    the last 300 characters of stderr, and runtime/messaging_provider.py reads that word)."""
    import subprocess
    out_ok, out_gone = tmp_path / "ok", tmp_path / "gone"
    out_ok.mkdir()
    out_gone.mkdir()
    env = dict(os.environ, MESSENGER_TELEGRAM_BOT_TOKEN=TOKEN)
    for behaviour, getfile, folder in (("file", "file", out_ok), ("file", "gone", out_gone)):
        hits = []
        site = serve(type("S", (Site,), {"behaviour": behaviour, "getfile": getfile, "hits": hits}))
        try:
            env["MESSENGER_TELEGRAM_API_BASE"] = f"http://127.0.0.1:{site.server_address[1]}"
            done = subprocess.run([sys.executable, str(SCRIPT), "fetch-attachment", "--platform", "telegram", "--ref", FILE_ID, "--out", str(folder),
                                   "--max-bytes", "1000"], capture_output=True, text=True, env=env, timeout=60)
        finally:
            site.shutdown()
        if getfile == "file":
            assert done.returncode == 0, done.stderr
            assert json.loads(done.stdout) == {"bytes": 5, "sha256": hashlib.sha256(b"hello").hexdigest()} and (folder / "content").read_bytes() == b"hello"
        else:
            assert done.returncode == 1 and done.stdout == "" and done.stderr.startswith("gone") and not list(folder.iterdir())
            assert " ".join(done.stderr.split())[-300:].startswith("gone")
        assert TOKEN not in done.stdout + done.stderr


# --- where the bytes go -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("ref", ["", "a/b", "../x", "a b", "x" * 201, "a;b", "a\nb"])
def test_a_ref_that_is_not_a_plain_file_id_is_a_usage_error_before_any_call(monkeypatch, capsys, out, ref):
    opener = Opener()
    code, printed, _ = fetch(monkeypatch, capsys, opener, out, ref=ref)
    assert code == 2 and printed == "" and opener.requests == []


@pytest.mark.parametrize("cap", ["0", "-5", "many"])
def test_a_cap_that_is_not_a_positive_number_is_a_usage_error(monkeypatch, capsys, out, cap):
    opener = Opener()
    code, _, _ = run(monkeypatch, capsys, opener, "fetch-attachment", "--platform", "telegram", "--ref", FILE_ID, "--out", str(out), "--max-bytes", cap)
    assert code == 2 and opener.requests == []


def test_the_output_folder_must_be_an_existing_real_folder(monkeypatch, capsys, tmp_path):
    missing = tmp_path / "nowhere"
    code, _, _ = fetch(monkeypatch, capsys, Opener(got_file(), Stream(b"abc")), missing)
    assert code == 2 and not missing.exists()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    code, _, _ = fetch(monkeypatch, capsys, Opener(got_file(), Stream(b"abc")), link)
    assert code == 2 and not list(real.iterdir())
    plain = tmp_path / "plain.txt"
    plain.write_text("x")
    assert fetch(monkeypatch, capsys, Opener(got_file(), Stream(b"abc")), plain)[0] == 2


def test_an_existing_content_file_or_a_planted_link_is_never_written_through(monkeypatch, capsys, out, tmp_path):
    target = tmp_path / "victim.txt"
    target.write_text("untouched")
    (out / "content").symlink_to(target)
    code, printed, _ = fetch(monkeypatch, capsys, Opener(got_file(), Stream(b"attacker bytes", length=14)), out)
    assert code == 1 and printed == "" and target.read_text() == "untouched" and (out / "content").is_symlink()
    (out / "content").unlink()
    (out / "content").write_text("earlier")
    code, _, _ = fetch(monkeypatch, capsys, Opener(got_file(), Stream(b"new", length=3)), out)
    assert code == 1 and (out / "content").read_text() == "earlier"


def test_a_name_never_reaches_a_path(monkeypatch, capsys, out, tmp_path):
    found = mapped(document={"file_id": FILE_ID, "file_name": "../../escape.pdf", "file_size": 3})
    assert found["attachments"][0]["name"] == "../../escape.pdf"      # shown by the bridge, escaped there
    code, _, _ = fetch(monkeypatch, capsys, Opener(got_file(), Stream(b"abc", length=3)), out)
    assert code == 0 and [p.name for p in out.iterdir()] == ["content"] and not (tmp_path / "escape.pdf").exists()
    assert not list(tmp_path.glob("**/escape*"))


# --- the token is in no output ------------------------------------------------------------------------------------------

def broken_url(path="documents/file_7.pdf"):
    return f"https://api.telegram.org/file/bot{TOKEN}/{path}"


FAILURES = [
    urllib.error.URLError(f"cannot reach {broken_url()}"),
    urllib.error.URLError(OSError(f"host {TOKEN}")),
    OSError(f"socket error {broken_url()}"),
    ValueError(f"bad {TOKEN}"),
    http.client.IncompleteRead(TOKEN.encode(), 5),
    http.client.RemoteDisconnected(f"closed {TOKEN}"),
    http.client.BadStatusLine(f"{TOKEN}"),
    http.client.InvalidURL(broken_url()),
    http_error(500, f"error for {TOKEN}", broken_url()),
    http_error(403, f"forbidden {TOKEN}", broken_url()),
    RuntimeError(f"unexpected {TOKEN}"),
]


@pytest.mark.parametrize("failure", FAILURES)
def test_no_failure_of_the_download_shows_the_token_or_a_traceback(monkeypatch, capsys, out, failure):
    code, printed, err = fetch(monkeypatch, capsys, Opener(got_file(), failure), out)
    assert code in (1, 3) and printed == "" and not list(out.iterdir())
    assert TOKEN not in printed + err and "123456789:" not in err and "Traceback" not in err and "api.telegram.org" not in err, err


@pytest.mark.parametrize("failure", FAILURES)
def test_no_failure_of_get_file_shows_the_token_or_a_traceback(monkeypatch, capsys, out, failure):
    code, printed, err = fetch(monkeypatch, capsys, Opener(failure), out)
    assert code in (1, 3) and printed == ""
    assert TOKEN not in printed + err and "123456789:" not in err and "Traceback" not in err, err


@pytest.mark.parametrize("failure", [http.client.IncompleteRead(b"abc", 5), http.client.HTTPException(f"x {TOKEN}"), OSError(f"x {TOKEN}"),
                                     ValueError(f"x {TOKEN}")])
def test_a_failure_in_the_middle_of_the_stream_removes_the_partial_file(monkeypatch, capsys, out, failure):
    code, printed, err = fetch(monkeypatch, capsys, Opener(got_file(), Stream(b"a" * 40, failure)), out)
    assert code == 1 and printed == "" and not list(out.iterdir()) and TOKEN not in err


def test_the_secret_is_still_not_an_argument_and_fetch_needs_the_token(monkeypatch, capsys, out):
    monkeypatch.delenv("MESSENGER_TELEGRAM_BOT_TOKEN")
    monkeypatch.setattr(telegram, "secret_resolver", lambda: type("R", (), {"resolve": staticmethod(lambda *a, **k: None)}))
    opener = Opener()
    code, _, err = fetch(monkeypatch, capsys, opener, out)
    assert code == 3 and opener.requests == [] and "keyring set openhora messenger-telegram" in err
