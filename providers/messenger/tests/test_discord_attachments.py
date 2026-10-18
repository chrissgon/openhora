"""Offline tests for the attachments of providers/messenger/discord.py (ATT-2): the mapping of a message's `attachments[]` and the listen op
`fetch`. Discord's REST API is the fake router of test_discord.py, the content host is a fake opener of its own (so that a header sent to it
can be seen); one test uses a real server on the loopback port to see a real redirect refused. No network, no websockets library, no real token.

Run: uv run --with pytest pytest providers/messenger/tests
"""
from __future__ import annotations

import hashlib
import http.client
import http.server
import io
import json
import stat
import sys
import threading
import time
import urllib.error
from pathlib import Path

import pytest

from test_discord import (BARE_VALUE, TAP_VALUE, TOKEN, USER, Reply, Rig, Router, Transport, dm, http_error, ready, router, started,  # noqa: F401
                          wait_for, hello, Conn, discord)

RUNTIME = Path(__file__).resolve().parents[3] / "runtime"
PDF = b"%PDF-1.4 a small fictional file " * 20
CDN = "https://cdn.discordapp.com/attachments/7001/9001/plan.pdf?ex=65a1&is=659f&hm=abcd1234"
REF = "7001:5001:9001"


class Stream:
    """A file download: the chunks it yields, the headers it answers, every size asked of read()."""

    def __init__(self, *chunks, length=None):
        self.chunks, self.asked = list(chunks), []
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        self.asked.append(size)
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if isinstance(chunk, BaseException):
            raise chunk
        if size is not None and 0 <= size < len(chunk):
            self.chunks.insert(0, chunk[size:])
            return chunk[:size]
        return chunk


class Cdn:
    """The content host: answers each call from a queue (a Stream, or an exception to raise) and records the request."""

    def __init__(self, *answers, gate=None):
        self.answers, self.requests, self.gate = list(answers), [], gate

    def open(self, request, timeout=None):
        self.requests.append({"url": request.full_url, "method": request.get_method(), "headers": {k.lower(): v for k, v in request.header_items()},
                              "timeout": timeout})
        if self.gate is not None:
            self.gate.wait(30)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def cdn_error(status, url=CDN):
    return urllib.error.HTTPError(url, status, "x", {}, io.BytesIO(b"<html>not json</html>"))


def the_message(url=CDN, size=len(PDF), att="9001", name="plan.pdf", **extra):
    item = {"id": att, "filename": name, "size": size, "content_type": "application/pdf", "url": url,
            "proxy_url": url.replace("cdn.discordapp.com", "media.discordapp.net")}
    item.update(extra)
    return {"id": "5001", "channel_id": "7001", "author": {"id": USER}, "content": "", "attachments": [item]}


def with_message(message, **kw):
    opener = router(**kw)
    opener.on("GET", r"^/channels/7001/messages/5001$", message)
    return opener


@pytest.fixture(autouse=True)
def quick_queues(monkeypatch):
    monkeypatch.setattr(discord, "QUEUE_POLL_SECONDS", 0.02)      # the workers look at their queues often, so a test ends at once


@pytest.fixture
def out(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir(mode=0o700)
    return folder


def ask(rig, rid=1, ref=REF, folder=None, cap=1_000_000, **raw):
    request = {"id": rid, "op": "fetch", "ref": ref, "out": str(folder), "max_bytes": cap}
    request.update(raw)
    rig.writer.write(json.dumps(request).encode() + b"\n")
    rig.writer.flush()
    return rig.answer(rid)


def serving(monkeypatch, cdn, message=None, *frames, **kw):
    opener = with_message(message or the_message(), **kw)
    monkeypatch.setattr(discord, "CDN_OPENER", cdn)
    rig, conn = started(monkeypatch, ready(), *frames, opener=opener)
    wait_for(lambda: rig.sink.events("ready"))
    return rig, opener


# --- the mapping ---------------------------------------------------------------------------------------------------------

def update_of(**fields):
    return discord.message_update(dm(**fields)["d"])


def test_capabilities_declare_attachments_and_a_cap_the_bridge_can_read():
    sys.path.insert(0, str(RUNTIME))
    import messaging_provider as provider
    caps = discord.CAPABILITIES
    assert caps["attachments"] is True and type(caps["max_attachment_bytes"]) is int and caps["max_attachment_bytes"] == 25 * 1024 * 1024
    for key, kind in provider.OPTIONAL_KEYS.items():
        if key in caps:
            assert type(caps[key]) is kind, key


def test_an_attachment_maps_to_the_three_ids_its_name_size_and_media_type():
    found = update_of(content="", attachments=[{"id": "9001", "filename": "plan.pdf", "size": 4096, "content_type": "application/pdf",
                                                "url": CDN, "proxy_url": CDN}])
    assert found["attachments"] == [{"ref": "7001:5001:9001", "name": "plan.pdf", "size": 4096, "type": "application/pdf"}]
    assert found["text"] is None and found["sender"] == USER and found["private"] is True
    assert CDN not in json.dumps(found) and "ex=" not in json.dumps(found)      # no address, signed or not, leaves the provider


def test_the_content_is_the_caption_and_the_update_passes_the_bridges_check():
    sys.path.insert(0, str(RUNTIME))
    import messaging_provider as provider
    found = update_of(content="@plan-brief", attachments=[{"id": "9001", "filename": "plan.docx", "size": 10}])
    assert found["text"] == "@plan-brief"
    checked = provider.valid_update(found)
    assert checked["attachments"] == [{"ref": "7001:5001:9001", "name": "plan.docx", "size": 10, "type": None}] and checked["text"] == "@plan-brief"


def test_a_blank_caption_is_no_text_and_a_plain_message_has_no_attachments_key():
    assert update_of(content="  \n", attachments=[{"id": "9001", "filename": "a.pdf", "size": 1}])["text"] is None
    plain = update_of(content="hello")
    assert plain["text"] == "hello" and "attachments" not in plain
    assert update_of(content="hello", attachments=[])["text"] == "hello" and "attachments" not in update_of(content="hello", attachments=[])


def test_several_files_are_listed_in_order_and_at_most_ten_are_taken():
    many = [{"id": str(9000 + n), "filename": f"f{n}.txt", "size": n, "content_type": "text/plain"} for n in range(14)]
    found = update_of(content="", attachments=many)
    assert [a["ref"] for a in found["attachments"]] == [f"7001:5001:{9000 + n}" for n in range(10)]


@pytest.mark.parametrize("item", [{"id": "x1", "filename": "a"}, {"id": "9;1", "filename": "a"}, {"id": 9001, "filename": "a"}, {"filename": "a"},
                                  {"id": "1" * 21, "filename": "a"}, "not an object", None])
def test_an_attachment_whose_id_is_not_a_snowflake_is_not_mapped(item):
    assert update_of(content="", attachments=[item]) is None
    kept = update_of(content="hi", attachments=[item])
    assert kept["text"] == "hi" and "attachments" not in kept


def test_a_message_without_a_channel_id_gives_no_ref():
    d = dm(content="", attachments=[{"id": "9001", "filename": "a.pdf"}])["d"]
    del d["channel_id"]
    assert discord.message_update(d) is None
    d["channel_id"] = "7001/../x"
    assert discord.message_update(d) is None
    d["channel_id"] = "\u0667\u0660\u0660\u0661"
    assert discord.message_update(d) is None


def test_odd_names_sizes_and_types_are_cleaned():
    found = update_of(content="", attachments=[{"id": "9001", "filename": "n" * 400, "size": True, "content_type": 5}])
    (item,) = found["attachments"]
    assert item["size"] is None and item["type"] is None and len(item["name"]) <= 255
    assert update_of(content="", attachments=[{"id": "9001", "filename": "", "size": -2}])["attachments"][0] == \
        {"ref": "7001:5001:9001", "name": None, "size": None, "type": None}


@pytest.mark.parametrize("change", [{"guild_id": "1"}, {"webhook_id": "2"}, {"author": {"id": USER, "bot": True}}, {"type": 7}])
def test_a_file_in_a_server_from_a_bot_or_a_webhook_is_still_ignored(change):
    assert update_of(content="", attachments=[{"id": "9001", "filename": "a.pdf"}], **change) is None


def test_a_file_message_reaches_the_bridge_through_the_gateway(monkeypatch):
    rig, conn = started(monkeypatch, ready(), dm(content="@plan-brief", attachments=[{"id": "9001", "filename": "a.pdf", "size": 3,
                                                                                     "content_type": "application/pdf", "url": CDN}]))
    wait_for(lambda: rig.sink.events("update"))
    (event,) = rig.sink.events("update")
    assert event["update"]["attachments"] == [{"ref": REF, "name": "a.pdf", "size": 3, "type": "application/pdf"}]
    assert CDN not in json.dumps(event)
    rig.end()


# --- the fetch ---------------------------------------------------------------------------------------------------------

def test_a_fetch_rereads_the_message_for_a_fresh_address_then_downloads_it_with_no_authorization(monkeypatch, out):
    cdn = Cdn(Stream(PDF[:100], PDF[100:], length=len(PDF)))
    rig, opener = serving(monkeypatch, cdn)
    answer = ask(rig, folder=out)
    assert answer == {"id": 1, "ok": True, "bytes": len(PDF), "sha256": hashlib.sha256(PDF).hexdigest()}
    content = out / "content"
    assert content.read_bytes() == PDF and stat.S_IMODE(content.stat().st_mode) == 0o600 and [p.name for p in out.iterdir()] == ["content"]
    (reread,) = opener.calls("GET", r"^/channels/7001/messages/5001$")
    assert reread["headers"]["authorization"] == f"Bot {TOKEN}"
    (download,) = cdn.requests
    assert download["url"] == CDN and download["method"] == "GET" and download["timeout"] == discord.CONNECT_SECONDS
    assert "authorization" not in download["headers"] and "cookie" not in download["headers"]
    assert TOKEN not in json.dumps(download) and TOKEN not in json.dumps(rig.sink.lines)
    assert rig.end() == 0


def test_the_bytes_are_asked_for_in_bounded_chunks(monkeypatch, out):
    stream = Stream(PDF, length=len(PDF))
    rig, _ = serving(monkeypatch, Cdn(stream))
    assert ask(rig, folder=out, cap=len(PDF) + 3)["ok"] is True
    assert stream.asked and all(0 < size <= discord.CHUNK_BYTES for size in stream.asked)
    rig.end()


def test_the_attachment_is_picked_by_its_id_among_the_messages_files(monkeypatch, out):
    message = the_message()
    message["attachments"].insert(0, dict(message["attachments"][0], id="9000", url=CDN.replace("9001", "9000").replace("plan", "other")))
    cdn = Cdn(Stream(b"abc", length=3))
    rig, _ = serving(monkeypatch, cdn, message)
    assert ask(rig, folder=out)["ok"] is True and cdn.requests[0]["url"] == CDN
    rig.end()


def test_a_message_that_is_gone_is_a_gone_answer_and_the_content_host_is_not_asked(monkeypatch, out):
    cdn = Cdn()
    rig, _ = serving(monkeypatch, cdn, http_error(404, {"message": "Unknown Message", "code": 10008}))
    answer = ask(rig, folder=out)
    assert answer["ok"] is False and answer["kind"] == "gone" and cdn.requests == [] and not list(out.iterdir())
    rig.end()


def test_a_message_that_no_longer_holds_the_file_is_gone(monkeypatch, out):
    cdn = Cdn()
    rig, _ = serving(monkeypatch, cdn, the_message(att="9002"))
    answer = ask(rig, folder=out)
    assert answer["kind"] == "gone" and cdn.requests == []
    rig.end()


def test_a_file_the_content_host_no_longer_has_is_gone(monkeypatch, out):
    rig, _ = serving(monkeypatch, Cdn(cdn_error(404)))
    answer = ask(rig, folder=out)
    assert answer["ok"] is False and answer["kind"] == "gone" and not list(out.iterdir())
    rig.end()


def test_a_declared_size_over_the_cap_is_refused_before_any_download(monkeypatch, out):
    cdn = Cdn()
    rig, _ = serving(monkeypatch, cdn, the_message(size=5000))
    answer = ask(rig, folder=out, cap=4999)
    assert answer["ok"] is False and answer["kind"] == "usage" and cdn.requests == [] and "5000" in answer["reason"]
    rig.end()


def test_a_content_length_over_the_cap_is_refused_before_the_body_is_read(monkeypatch, out):
    stream = Stream(b"x" * 10, length=999_999)
    rig, _ = serving(monkeypatch, Cdn(stream), the_message(size=5))
    answer = ask(rig, folder=out, cap=1000)
    assert answer["kind"] == "usage" and stream.asked == [] and not list(out.iterdir())
    rig.end()


def test_the_cap_is_enforced_mid_stream_and_the_partial_file_is_removed(monkeypatch, out):
    stream = Stream(*[b"y" * 400 for _ in range(10)])
    rig, _ = serving(monkeypatch, Cdn(stream), the_message(size=5))      # the platform said 5 and sends more: the count decides
    answer = ask(rig, folder=out, cap=1000)
    assert answer["ok"] is False and answer["kind"] == "usage" and not list(out.iterdir())
    assert sum(min(s, 400) for s in stream.asked) <= 1000 + 400
    rig.end()


def test_a_body_shorter_than_its_content_length_fails_and_leaves_nothing(monkeypatch, out):
    rig, _ = serving(monkeypatch, Cdn(Stream(b"a" * 50, length=100)), the_message(size=100))
    answer = ask(rig, folder=out)
    assert answer["ok"] is False and answer["kind"] == "failed" and not list(out.iterdir())
    rig.end()


def test_a_slow_download_stops_at_the_whole_fetch_deadline(monkeypatch, out):
    stream = Stream(b"a" * 10, b"b" * 10, b"c" * 10)
    rig, _ = serving(monkeypatch, Cdn(stream), the_message(size=30))
    ticks = iter([0.0])
    rig.listener.clock = lambda: next(ticks, 500.0)
    answer = ask(rig, folder=out)
    assert answer["kind"] == "failed" and "took longer" in answer["reason"] and not list(out.iterdir())
    rig.end()


@pytest.mark.parametrize("url", ["https://attacker.example/attachments/7001/9001/plan.pdf", "https://cdn.discordapp.com.attacker.example/a",
                                 "https://notcdn.discordapp.com/a", "http://cdn.discordapp.com/attachments/7001/9001/plan.pdf",
                                 "https://cdn.discordapp.com@attacker.example/a", "https://user:pw@cdn.discordapp.com/a",
                                 "https://cdn.discordapp.com:8443/a", "https://discord.com/api/v10/users/@me", "file:///etc/passwd",
                                 "//cdn.discordapp.com/a", "", None, 5])
def test_an_address_off_the_content_hosts_is_never_requested_and_the_token_goes_nowhere(monkeypatch, out, url):
    cdn = Cdn()
    message = the_message()
    message["attachments"][0]["url"] = url
    rig, opener = serving(monkeypatch, cdn, message)
    answer = ask(rig, folder=out)
    assert answer["ok"] is False and answer["kind"] == "failed" and cdn.requests == [] and not list(out.iterdir())
    assert len(opener.calls("GET", r"/messages/")) == 1 and all(r["path"].startswith(("/gateway", "/channels")) for r in opener.requests)
    rig.end()


def test_both_content_hosts_are_taken(monkeypatch, out):
    for host in ("cdn.discordapp.com", "media.discordapp.net"):
        folder = out / host
        folder.mkdir()
        cdn = Cdn(Stream(b"abc", length=3))
        rig, _ = serving(monkeypatch, cdn, the_message(url=f"https://{host}/attachments/7001/9001/plan.pdf?ex=1&is=2&hm=3"))
        assert ask(rig, folder=folder)["ok"] is True and cdn.requests[0]["url"].startswith(f"https://{host}/")
        rig.end()


def test_the_content_host_is_asked_through_an_opener_that_follows_no_redirect():
    assert any(isinstance(h, discord.RefuseRedirect) for h in discord.CDN_OPENER.handlers)
    assert discord.CDN_OPENER is not discord.OPENER
    with pytest.raises(discord.ProviderError) as e:
        discord.RefuseRedirect().redirect_request(None, io.BytesIO(b""), 302, "Found", {}, "https://attacker.example/steal")
    assert "attacker" not in str(e.value)


def test_a_host_that_drips_one_byte_at_a_time_cannot_outlive_the_deadline(monkeypatch, out):
    class Drip(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
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

    site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Drip)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    monkeypatch.setattr(discord, "FETCH_TOTAL_SECONDS", 1.0)
    connection = http.client.HTTPConnection("127.0.0.1", site.server_address[1], timeout=5)
    try:
        connection.request("GET", "/f")
        began = time.time()
        with pytest.raises(discord.ProviderError) as e:
            discord.stream_file(connection.getresponse(), str(out), 100_000, time.monotonic, time.monotonic())
        took = time.time() - began
    finally:
        connection.close()
        site.shutdown()
    assert "took longer" in str(e.value) and not list(out.iterdir())
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

    assert discord.read_some(Both(), 10) == b"one" and discord.read_some(OnlyRead(), 10) == b"all"


def test_a_content_length_that_is_not_ascii_digits_is_not_read():
    assert discord._declared_length(type("R", (), {"headers": {"Content-Length": "\u0663\u0664"}})()) is None
    assert discord._declared_length(type("R", (), {"headers": {"Content-Length": "34"}})()) == 34


def test_a_real_redirect_is_refused_by_the_content_opener():
    seen = []

    class Target(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    other = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Target)

    class Redirecting(Target):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{other.server_address[1]}/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()

    first = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Redirecting)
    for server in (other, first):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = discord.urllib.request.Request(f"http://127.0.0.1:{first.server_address[1]}/f", headers={"User-Agent": "x"})
        with pytest.raises(discord.ProviderError) as e:
            discord.CDN_OPENER.open(request, timeout=5)
    finally:
        first.shutdown()
        other.shutdown()
    assert "redirect" in str(e.value) and seen == []


def test_a_redirect_from_the_content_host_fails_the_fetch_with_no_address_in_the_answer(monkeypatch, out):
    refusal = discord.ProviderError("refusing to follow a 302 redirect: the request carries the bot's token")
    rig, _ = serving(monkeypatch, Cdn(refusal))
    answer = ask(rig, folder=out)
    assert answer["ok"] is False and answer["kind"] == "failed" and "attacker" not in answer["reason"] and not list(out.iterdir())
    rig.end()


# --- the ref, the folder and the file -------------------------------------------------------------------------------------

@pytest.mark.parametrize("ref", ["", "7001", "7001:5001", "7001:5001:9001:1", "7001:5001:x", "a:5001:9001", "7001/../x:5001:9001",
                                 "7001:5001:9001\n", " 7001:5001:9001", "7001:5001:" + "9" * 21, "../../etc/passwd", "7001:5001:9001/../../x",
                                 "\u0667\u0660\u0660\u0661:5001:9001", "7001:5001:\u0669\u0660\u0660\u0661"])    # Arabic-Indic digits are digits to \\d, not to this provider
def test_a_ref_that_is_not_three_numbers_is_a_usage_answer_and_nothing_is_requested(monkeypatch, out, ref):
    cdn = Cdn()
    rig, opener = serving(monkeypatch, cdn)
    answer = ask(rig, ref=ref, folder=out)
    assert answer["ok"] is False and answer["kind"] == "usage" and cdn.requests == [] and not list(out.iterdir())
    assert opener.calls("GET", r"/messages/") == []
    rig.end()


@pytest.mark.parametrize("raw", [{"max_bytes": 0}, {"max_bytes": -3}, {"max_bytes": "9"}, {"max_bytes": True}, {"max_bytes": None}, {"out": None},
                                 {"out": 7}, {"ref": 7}])
def test_a_request_that_does_not_fit_is_a_usage_answer(monkeypatch, out, raw):
    cdn = Cdn()
    rig, opener = serving(monkeypatch, cdn)
    answer = ask(rig, folder=out, **raw)
    assert answer["ok"] is False and answer["kind"] == "usage" and cdn.requests == [] and opener.calls("GET", r"/messages/") == []
    rig.end()


def test_the_output_folder_must_be_an_existing_real_folder(monkeypatch, tmp_path):
    cdn = Cdn(Stream(b"abc", length=3), Stream(b"abc", length=3), Stream(b"abc", length=3))
    rig, _ = serving(monkeypatch, cdn)
    assert ask(rig, 1, folder=tmp_path / "nowhere")["kind"] == "usage"
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert ask(rig, 2, folder=link)["kind"] == "usage" and not list(real.iterdir())
    plain = tmp_path / "plain.txt"
    plain.write_text("x")
    assert ask(rig, 3, folder=plain)["kind"] == "usage"
    rig.end()


def test_an_existing_content_file_or_a_planted_link_is_never_written_through(monkeypatch, out, tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched")
    (out / "content").symlink_to(victim)
    rig, _ = serving(monkeypatch, Cdn(Stream(b"attacker bytes", length=14), Stream(b"new", length=3)), the_message(size=14))
    assert ask(rig, 1, folder=out)["ok"] is False and victim.read_text() == "untouched" and (out / "content").is_symlink()
    (out / "content").unlink()
    (out / "content").write_text("earlier")
    assert ask(rig, 2, folder=out)["ok"] is False and (out / "content").read_text() == "earlier"
    rig.end()


def test_a_name_never_reaches_a_path(monkeypatch, out, tmp_path):
    message = the_message(name="../../escape.pdf", size=3)
    rig, _ = serving(monkeypatch, Cdn(Stream(b"abc", length=3)), message)
    assert ask(rig, folder=out, cap=10)["ok"] is True
    assert [p.name for p in out.iterdir()] == ["content"] and not list(tmp_path.glob("**/escape*"))
    assert update_of(content="", attachments=message["attachments"])["attachments"][0]["name"] == "../../escape.pdf"      # shown by the bridge, escaped there
    rig.end()


# --- the token, the failures and the other work --------------------------------------------------------------------------

def broken(label):
    return {"url": f"https://discord.com/api/v10/channels/7001/messages/5001?t={TOKEN}", "label": label}


FAILURES = [
    urllib.error.URLError(f"connection to https://discord.com/api/v10?t={TOKEN} refused"),
    urllib.error.URLError(OSError(f"host {TOKEN}")),
    OSError(f"broken {TOKEN} {BARE_VALUE}"),
    ValueError(f"{TOKEN}"),
    http.client.IncompleteRead(TOKEN.encode(), 5),
    http.client.RemoteDisconnected(f"closed {TOKEN}"),
    http.client.BadStatusLine(TOKEN),
    http_error(500, {"message": f"oops {TOKEN} {BARE_VALUE} {TAP_VALUE}", "code": 0}),
    http_error(403, {"message": f"no {TOKEN}", "code": 50001}),
    RuntimeError(f"unexpected {TOKEN}"),
]


@pytest.mark.parametrize("failure", FAILURES)
def test_no_failure_of_the_message_read_shows_the_token(monkeypatch, out, failure):
    cdn = Cdn()
    rig, _ = serving(monkeypatch, cdn, failure)
    answer = ask(rig, folder=out)
    assert answer["ok"] is False and answer["kind"] in ("failed", "not-configured")
    shown = json.dumps(rig.sink.lines) + "\n".join(rig.logs)
    for secret in (TOKEN, TAP_VALUE):
        assert secret not in shown
    assert "Traceback" not in shown and cdn.requests == []
    rig.end()


@pytest.mark.parametrize("failure", [f for f in FAILURES if not isinstance(f, urllib.error.HTTPError)] +
                         [cdn_error(500), cdn_error(403), cdn_error(401)])
def test_no_failure_of_the_download_shows_the_token_or_an_address(monkeypatch, out, failure):
    rig, _ = serving(monkeypatch, Cdn(failure))
    answer = ask(rig, folder=out)
    assert answer["ok"] is False and answer["kind"] in ("failed",) and not list(out.iterdir())
    shown = json.dumps(rig.sink.lines) + "\n".join(rig.logs)
    for secret in (TOKEN, "cdn.discordapp.com", "hm=abcd1234", "ex=65a1"):
        assert secret not in shown, secret
    assert rig.thread.is_alive(), "a 401 from the content host is not the bot's token refused: the process keeps going"
    rig.end()


@pytest.mark.parametrize("failure", [http.client.IncompleteRead(b"abc", 5), http.client.HTTPException(f"x {TOKEN}"), OSError(f"x {TOKEN}"),
                                     ValueError(f"x {TOKEN}")])
def test_a_failure_in_the_middle_of_the_stream_removes_the_partial_file(monkeypatch, out, failure):
    rig, _ = serving(monkeypatch, Cdn(Stream(b"a" * 40, failure)), the_message(size=80))
    answer = ask(rig, folder=out)
    assert answer["kind"] == "failed" and not list(out.iterdir()) and TOKEN not in json.dumps(rig.sink.lines)
    rig.end()


def test_a_401_on_the_message_read_is_the_bots_token_refused_like_a_send(monkeypatch, out):
    rig, _ = serving(monkeypatch, Cdn(), http_error(401, {"message": TOKEN}))
    answer = ask(rig, folder=out)
    assert answer["ok"] is False and answer["kind"] == "not-configured" and TOKEN not in json.dumps(rig.sink.lines)
    assert rig.join(5) == 3
    errors = rig.sink.events("error")
    assert errors and errors[-1]["kind"] == "not-configured"


def test_a_429_on_the_message_read_waits_once_and_asks_again(monkeypatch, out):
    cdn = Cdn(Stream(b"abc", length=3))
    opener = router()
    opener.on("GET", r"^/channels/7001/messages/5001$", http_error(429, {"retry_after": 0.5}), the_message(size=3))
    monkeypatch.setattr(discord, "CDN_OPENER", cdn)
    rig, conn = started(monkeypatch, ready(), opener=opener)
    wait_for(lambda: rig.sink.events("ready"))
    assert ask(rig, folder=out, cap=10)["ok"] is True and 0.5 in rig.pauses
    rig.end()


def test_a_fetch_runs_beside_a_send_and_a_held_fetch_does_not_hold_the_exit(monkeypatch, out):
    gate = threading.Event()
    cdn = Cdn(Stream(b"abc", length=3), gate=gate)
    rig, opener = serving(monkeypatch, cdn)
    rig.writer.write(json.dumps({"id": 1, "op": "fetch", "ref": REF, "out": str(out), "max_bytes": 10_000}).encode() + b"\n")
    rig.writer.flush()
    wait_for(lambda: cdn.requests)      # the fetch is inside the download, held
    rig.request(2)
    assert rig.answer(2)["ok"] is True      # a send is answered while the fetch waits
    began = time.time()
    rig.eof()
    assert rig.join(5, threads=False) == 0 and time.time() - began < 4
    gate.set()
    rig.threads_ended()


def test_every_fetch_answer_is_one_ascii_json_line_with_the_request_id(monkeypatch, out):
    rig, _ = serving(monkeypatch, Cdn(Stream(b"abc", length=3)), the_message(size=3))
    ask(rig, 41, folder=out, cap=10)
    assert all(isinstance(raw, bytes) and raw.endswith(b"\n") and raw.decode("ascii") for raw in rig.sink.raw)
    assert any(line.get("id") == 41 for line in rig.sink.lines)
    rig.end()


def test_the_listen_protocol_still_serves_a_send_that_is_not_a_fetch(monkeypatch, out):
    rig, _ = serving(monkeypatch, Cdn())
    rig.request(1)
    assert rig.answer(1) == {"id": 1, "ok": True, "message_id": "8001"}
    rig.writer.write(json.dumps({"id": 2, "op": "wave"}).encode() + b"\n")
    rig.writer.flush()
    assert rig.answer(2)["kind"] == "usage"
    rig.end()
