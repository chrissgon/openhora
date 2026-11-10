"""The pin routine's two verbs (package V7c): `pin-latest` reads the release metadata and downloads nothing, `pin-raise --confirmed` writes the person's own
pin from it, and the effective pin (a valid raise, else the committed one) changes the image's definition hash. A fake opener stands in for the one https
call; nothing here reaches a network or starts a container. Fictional versions."""
from __future__ import annotations

import io
import json
import os
import socket

import pytest

import fetcher_kit as K
import _fetcher_image
import ytdlp

COMMITTED = dict(K.PIN, version="2099.01.01", url="https://download.example/releases/2099.01.01/yt-dlp", size=1000, sha256="ab" * 32)
NEWER = "2099.03.05"
DIGEST = "cd" * 32


def release(tag=NEWER, name="yt-dlp", digest="sha256:" + DIGEST, url=None, size=2000):
    asset = {"name": name, "size": size, "browser_download_url": url or "https://download.example/releases/%s/yt-dlp" % tag}
    if digest is not None:
        asset["digest"] = digest
    return {"tag_name": tag, "published_at": "2099-03-05T10:00:00Z", "assets": [asset, {"name": "other.zip", "size": 1}]}


class Opener:
    """The fake of ytdlp.release_open: records every (host, path) and answers with a status and a body."""

    def __init__(self, status=200, body=None, error=None):
        self.status, self.error, self.calls = status, error, []
        self.body = body if isinstance(body, bytes) else json.dumps(body if body is not None else release()).encode()

    def __call__(self, host, path, timeout):
        self.calls.append((host, path))
        if self.error:
            raise self.error
        return self.status, io.BytesIO(self.body)


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = K.World(tmp_path, monkeypatch, image=False)
    (w.folder / "tool-pin.json").write_text(json.dumps(COMMITTED))
    return w


def use(monkeypatch, opener):
    monkeypatch.setattr(ytdlp, "release_open", opener)
    return opener


def test_pin_latest_reads_one_release_page_and_downloads_and_writes_nothing(world, monkeypatch):
    opener = use(monkeypatch, Opener())
    code, out, _ = K.run_main(["pin-latest"])
    assert code == 0 and out == {"ok": True, "current": "2099.01.01", "latest": NEWER, "newer": True, "published_at": "2099-03-05T10:00:00Z",
                                 "size": 2000, "sha256": DIGEST}
    assert opener.calls == [("api.github.com", "/repos/yt-dlp/yt-dlp/releases/latest")] and world.calls() == []
    assert not (world.state / "fetcher" / "pin.json").exists()


def test_pin_latest_says_not_newer_for_the_same_or_an_older_release(world, monkeypatch):
    for tag in ("2099.01.01", "2098.12.30"):
        use(monkeypatch, Opener(body=release(tag=tag)))
        assert K.run_main(["pin-latest"])[1]["newer"] is False


def test_pin_latest_refuses_a_redirect_a_bad_status_a_big_body_and_a_failed_read(world, monkeypatch):
    for opener in (Opener(status=302), Opener(status=404), Opener(body=b" " * (ytdlp.MIB + 1)), Opener(error=OSError("no route")), Opener(body=b"not json"),
                   Opener(body=b"[1]")):
        use(monkeypatch, opener)
        code, out, _ = K.run_main(["pin-latest"])
        assert (code, out) == (1, {"ok": False, "code": "release_refused"}), opener.status
        assert len(opener.calls) == 1, "a redirect is never followed"


def test_pin_latest_refuses_an_asset_address_that_is_not_the_committed_ones_and_a_missing_asset(world, monkeypatch):
    for body in (release(url="https://evil.example/releases/%s/yt-dlp" % NEWER), release(name="yt-dlp.exe")):
        use(monkeypatch, Opener(body=body))
        assert K.run_main(["pin-latest"])[:2] == (2, {"ok": False, "code": "pin_refused"})
    use(monkeypatch, Opener(body=dict(release(), tag_name="latest")))
    assert K.run_main(["pin-latest"])[:2] == (1, {"ok": False, "code": "release_refused"})


def test_the_real_opener_refuses_a_name_that_resolves_to_a_private_address(monkeypatch):
    monkeypatch.setattr(ytdlp.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443))])
    with pytest.raises(OSError):
        ytdlp.release_open("api.github.com", "/x", 5)
    monkeypatch.setattr(ytdlp.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                                                                       (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 443))])
    with pytest.raises(OSError):
        ytdlp.release_open("api.github.com", "/x", 5)


def test_pin_raise_needs_confirmed_and_a_version_and_makes_no_call_without_them(world, monkeypatch):
    opener = use(monkeypatch, Opener())
    assert K.run_main(["pin-raise", "--version", NEWER])[:2] == (2, {"ok": False, "code": "bad_arguments"})
    assert K.run_main(["pin-raise", "--version", "latest; x", "--confirmed"])[:2] == (2, {"ok": False, "code": "bad_arguments"})
    assert opener.calls == [] and not (world.state / "fetcher" / "pin.json").exists()


def test_pin_raise_refuses_an_older_or_equal_version_before_any_call(world, monkeypatch):
    opener = use(monkeypatch, Opener())
    for version in ("2099.01.01", "2098.01.01"):
        assert K.run_main(["pin-raise", "--version", version, "--confirmed"])[:2] == (2, {"ok": False, "code": "pin_refused"})
    assert opener.calls == [] and not (world.state / "fetcher" / "pin.json").exists()


def test_pin_raise_refuses_another_asset_a_missing_digest_and_a_tag_that_is_not_the_one_asked_for(world, monkeypatch):
    for body in (release(name="yt-dlp_linux"), release(digest=None), release(digest="md5:abc"), release(tag="2099.04.04")):
        use(monkeypatch, Opener(body=body))
        assert K.run_main(["pin-raise", "--version", NEWER, "--confirmed"])[:2] == (2, {"ok": False, "code": "pin_refused"})
        assert not (world.state / "fetcher" / "pin.json").exists()


def test_pin_raise_writes_the_persons_own_pin_at_0600_and_the_definition_hash_follows(world, monkeypatch):
    before_tag, before_hash = _fetcher_image.image_tag(str(world.folder)), _fetcher_image.definition_hash(str(world.folder))
    committed_bytes = (world.folder / "tool-pin.json").read_bytes()
    opener = use(monkeypatch, Opener())
    code, out, _ = K.run_main(["pin-raise", "--version", NEWER, "--confirmed"])
    assert code == 0 and out["raised"] == NEWER and out["previous"] == "2099.01.01" and "build --confirmed" in out["next"]
    assert opener.calls == [("api.github.com", "/repos/yt-dlp/yt-dlp/releases/tags/" + NEWER)] and world.calls() == []
    path = world.state / "fetcher" / "pin.json"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    raised = json.loads(path.read_text())
    assert raised["version"] == NEWER and raised["sha256"] == DIGEST and raised["size"] == 2000 and raised["redirect_hosts"] == COMMITTED["redirect_hosts"]
    assert raised["url"] == "https://download.example/releases/%s/yt-dlp" % NEWER
    assert (world.folder / "tool-pin.json").read_bytes() == committed_bytes, "the committed pin is never written"
    assert _fetcher_image.effective_pin(str(world.folder))["version"] == NEWER
    assert _fetcher_image.definition_hash(str(world.folder)) != before_hash and _fetcher_image.image_tag(str(world.folder)) != before_tag
    shown = K.run_main(["pin-show"])[1]
    assert shown["source"] == "local-raise" and shown["pin"]["version"] == NEWER and shown["filled"] is True
    assert K.run_main(["build", "--dry-run"])[1]["tool_version"] == NEWER
    latest = K.run_main(["pin-latest"])[1]
    assert latest["current"] == NEWER and latest["newer"] is False


def test_a_raise_that_is_not_valid_is_ignored_and_the_committed_pin_stays(world):
    own = world.state / "fetcher"
    own.mkdir(mode=0o700, exist_ok=True)
    good = dict(COMMITTED, version=NEWER, url="https://download.example/releases/%s/yt-dlp" % NEWER, size=2000, sha256=DIGEST)
    path = own / "pin.json"
    base = _fetcher_image.definition_hash(str(world.folder))
    cases = [dict(good, version="2098.01.01"), dict(good, sha256="zz"), dict(good, asset="other"), dict(good, redirect_hosts=["evil.example"]),
             dict(good, url="https://evil.example/yt-dlp"), dict(good, size=0), dict(good, version="2099.03.05; x")]
    for bad in cases:
        path.write_text(json.dumps(bad))
        path.chmod(0o600)
        assert _fetcher_image.effective_pin(str(world.folder))["version"] == "2099.01.01", bad
    path.write_text(json.dumps(good))
    path.chmod(0o644)      # open to others: refused
    assert _fetcher_image.effective_pin(str(world.folder))["version"] == "2099.01.01"
    path.chmod(0o600)
    assert _fetcher_image.effective_pin(str(world.folder))["version"] == NEWER and _fetcher_image.definition_hash(str(world.folder)) != base
    path.unlink()
    os.symlink(str(world.folder / "tool-pin.json"), str(path))
    assert _fetcher_image.effective_pin(str(world.folder))["version"] == "2099.01.01", "a link is refused"


def test_version_order_is_by_number_not_by_text():
    assert _fetcher_image.is_newer("2099.10.01", "2099.9.01") is False and _fetcher_image.is_newer("2099.10.01", "2099.09.30")
    assert _fetcher_image.is_newer("2099.03.05.123456", "2099.03.05") and not _fetcher_image.is_newer("2099.03.05", "2099.03.05.1")
    assert _fetcher_image.is_newer("garbage", "2099.01.01") is False and _fetcher_image.is_newer("2099.01.02", None) is False
