"""The browser pin, the one-time pinning step and the image build's download script. No network but a loopback stand-in."""
from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import re
import stat
import subprocess
import sys
import threading
import zipfile

import pytest

import renderer_kit as K
import _browser as B
from _text import Refusal

FETCH = K.RENDERER / "_fetch_browser.py"


def make_zip(members, links=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data, mode in members:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | mode) << 16
            zf.writestr(info, data)
        for name, target in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return buf.getvalue()


GOOD = make_zip([("chrome-headless-shell-linux64/chrome-headless-shell", b"#!/bin/sh\necho Google Chrome for Testing 155.0.8059.39\n", 0o755),
                 ("chrome-headless-shell-linux64/LICENSE", b"fictional", 0o644)])


@pytest.fixture
def server():
    state = {"body": GOOD, "redirect": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if state["redirect"]:
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:9/x")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            self.wfile.write(state["body"])

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/chrome.zip" % httpd.server_address[1], state
    httpd.shutdown()


def pin_file(tmp_path, url, body=GOOD, sha=None, **over):
    spec = {"url": url, "size": len(body), "md5": hashlib.md5(body).hexdigest(), "sha256": sha, "binary": "chrome-headless-shell-linux64/chrome-headless-shell"}
    spec.update(over)
    path = tmp_path / "pin.json"
    path.write_text(json.dumps({"product": "chrome-headless-shell", "version": "155.0.8059.39", "max_archive_bytes": 10_000_000,
                                "platforms": {"linux64": spec}}))
    return str(path)


def test_the_shipped_pin_names_the_version_and_both_architectures_and_the_sha256_is_not_invented():
    pin = B.load_pin()
    assert pin["version"] == "155.0.8059.39" and set(pin["platforms"]) == {"linux-arm64", "linux64"}
    for spec in pin["platforms"].values():
        assert spec["sha256"] is None or re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])
        assert spec["url"].startswith("https://storage.googleapis.com/chrome-for-testing-public/" + pin["version"] + "/")
        assert isinstance(spec["size"], int) and len(spec["md5"]) == 32
    assert B.platform_for("aarch64") == "linux-arm64" and B.platform_for("x86_64") == "linux64"
    with pytest.raises(B.NotConfigured) as e:
        B.platform_for("riscv64")
    assert e.value.code == "architecture_not_pinned"


def test_a_build_needs_the_sha256_and_says_how_to_get_it(tmp_path):
    path = pin_file(tmp_path, "https://x.example/c.zip")
    pin = B.load_pin(path)
    with pytest.raises(B.NotConfigured) as e:
        B.require_sha256(pin, "linux64")
    assert e.value.code == "pin_incomplete"
    assert B.require_sha256(B.load_pin(pin_file(tmp_path, "https://x.example/c.zip", sha="a" * 64)), "linux64")["sha256"] == "a" * 64


def test_pin_browser_records_the_sha256_after_checking_size_and_md5(tmp_path, server):
    url, state = server
    path = pin_file(tmp_path, url)
    done = B.pin_browser("linux64", path, test_mode=True)
    assert done["sha256"] == hashlib.sha256(GOOD).hexdigest() and done["recorded"] is True
    assert json.load(open(path))["platforms"]["linux64"]["sha256"] == done["sha256"]
    again = B.pin_browser("linux64", path, test_mode=True)                  # the same archive again: nothing changes
    assert again["recorded"] is False
    state["body"] = GOOD + b"x"                                           # the archive changed under the same version
    with pytest.raises(Refusal) as e:
        B.pin_browser("linux64", path, test_mode=True)
    assert e.value.code == "archive_differs_from_published"
    other = make_zip([("chrome-headless-shell-linux64/chrome-headless-shell", b"other", 0o755)])
    state["body"] = other
    path2 = pin_file(tmp_path, url, body=other, sha="b" * 64)
    with pytest.raises(Refusal) as e:
        B.pin_browser("linux64", path2, test_mode=True)
    assert e.value.code == "sha256_changed"                                 # same size and md5 as published, another sha256 than pinned


def test_pin_browser_refuses_a_wrong_size_or_md5_and_writes_nothing(tmp_path, server):
    url, _ = server
    for over in ({"size": len(GOOD) + 1}, {"md5": "0" * 32}):
        path = pin_file(tmp_path, url, **over)
        with pytest.raises(Refusal) as e:
            B.pin_browser("linux64", path, test_mode=True)
        assert e.value.code == "archive_differs_from_published"
        assert json.load(open(path))["platforms"]["linux64"]["sha256"] is None


def test_pin_browser_refuses_a_redirect_a_plain_http_url_outside_test_mode_and_an_oversize_archive(tmp_path, server):
    url, state = server
    state["redirect"] = True
    with pytest.raises(Refusal) as e:
        B.pin_browser("linux64", pin_file(tmp_path, url), test_mode=True)
    assert e.value.code == "download_failed"
    state["redirect"] = False
    with pytest.raises(Refusal) as e:
        B.pin_browser("linux64", pin_file(tmp_path, url), test_mode=False)
    assert e.value.code == "url_not_allowed"
    path = pin_file(tmp_path, url)
    doc = json.load(open(path))
    doc["max_archive_bytes"] = 10
    json.dump(doc, open(path, "w"))
    with pytest.raises(Refusal) as e:
        B.pin_browser("linux64", path, test_mode=True)
    assert e.value.code == "archive_too_large"
    assert B.pin_browser("linux64", path, dry_run=True)["dry_run"] is True


# ---------------------------------------------------------------- the image's download script

def fetch(tmp_path, url, body=GOOD, sha=None, size=None, md5=None, env=None, binary="chrome-headless-shell-linux64/chrome-headless-shell", tmpdir=None):
    dest = tmp_path / "opt"
    tmp = tmpdir or tmp_path
    e = {"PATH": os.environ["PATH"], "TMPDIR": str(tmp), "RENDERER_TEST": "1", **(env or {})}
    done = subprocess.run([sys.executable, "-I", str(FETCH), url, str(len(body) if size is None else size), md5 or hashlib.md5(body).hexdigest(),
                           sha or hashlib.sha256(body).hexdigest(), str(dest), binary], capture_output=True, text=True, env=e, timeout=60)
    return done, dest


def test_the_build_download_unpacks_an_archive_that_matches_its_pin(tmp_path, server):
    url, _ = server
    done, dest = fetch(tmp_path, url)
    assert done.returncode == 0, done.stderr
    binary = dest / "chrome-headless-shell-linux64" / "chrome-headless-shell"
    assert binary.is_file() and os.access(binary, os.X_OK) and not (tmp_path / "chrome.zip").exists()


@pytest.mark.parametrize("what, kwargs, reason", [
    ("sha256", {"sha": "0" * 64}, "sha256_differs_from_pin"),
    ("md5", {"md5": "0" * 32}, "md5_differs_from_pin"),
    ("size", {"size": 5}, "size_differs_from_pin"),
    ("no sha256 pinned", {"sha": ""}, "pin_incomplete"),
    ("binary missing", {"binary": "nope/nothing"}, "binary_missing"),
])
def test_the_build_download_refuses_what_differs_from_the_pin(tmp_path, server, what, kwargs, reason):
    url, _ = server
    kwargs = dict(kwargs)
    if kwargs.get("sha") == "":
        done = subprocess.run([sys.executable, "-I", str(FETCH), url, str(len(GOOD)), hashlib.md5(GOOD).hexdigest(), "", str(tmp_path / "o"), "x"],
                              capture_output=True, text=True, env={"PATH": os.environ["PATH"], "RENDERER_TEST": "1", "TMPDIR": str(tmp_path)}, timeout=60)
    else:
        done, _ = fetch(tmp_path, url, **kwargs)
    assert done.returncode == 1 and reason in done.stderr, (what, done.stderr)


def test_the_build_download_refuses_an_archive_that_escapes_its_folder_or_holds_a_link(tmp_path, server):
    url, state = server
    for body in (make_zip([("../evil", b"x", 0o755)]), make_zip([("/abs/evil", b"x", 0o755)]),
                 make_zip([("chrome-headless-shell-linux64/chrome-headless-shell", b"x", 0o755)], links=[("chrome-headless-shell-linux64/link", "/etc/passwd")])):
        state["body"] = body
        done, dest = fetch(tmp_path, url, body=body)
        assert done.returncode == 1 and "archive_member" in done.stderr
        assert not (tmp_path / "evil").exists() and not os.path.exists(os.path.join(os.path.dirname(str(dest)), "evil"))


def test_the_build_download_takes_only_the_official_https_url_and_refuses_a_redirect(tmp_path, server):
    url, state = server
    done, _ = fetch(tmp_path, "https://example.com/chrome.zip")
    assert done.returncode == 1 and "url_not_allowed" in done.stderr
    done, _ = fetch(tmp_path, url, env={"RENDERER_TEST": "0"})
    assert done.returncode == 1 and "url_not_allowed" in done.stderr         # plain http only in test mode
    state["redirect"] = True
    done, _ = fetch(tmp_path, url)
    assert done.returncode == 1 and "download_failed" in done.stderr
