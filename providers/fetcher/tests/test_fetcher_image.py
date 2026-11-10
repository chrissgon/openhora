"""The image's definition: manifest and .dockerignore equal, the hash covers the pin, the refusal of a null pin before any docker call, and the
build's own download script against a loopback server. Offline."""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading

import pytest

import fetcher_kit as K
import _fetcher_image
import ytdlp

SCRIPT = K.FETCHER / "_fetch_tool.py"


def test_the_manifest_and_the_dockerignore_list_the_same_files():
    manifest = _fetcher_image.manifest(str(K.FETCHER))
    ignore = (K.FETCHER / ".dockerignore").read_text().split("\n")
    allowed = [line[1:] for line in ignore if line.startswith("!")]
    assert ignore[0] == "*" and sorted(allowed) == sorted(manifest["files"]) and manifest["folders"] == []
    for name in manifest["files"]:
        assert (K.FETCHER / name).is_file(), name


def test_the_definition_covers_the_manifests_files_and_the_effective_pin(tmp_path):
    folder = tmp_path / "f"
    shutil.copytree(K.FETCHER, folder, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    base = _fetcher_image.definition_hash(str(folder))
    assert _fetcher_image.image_tag(str(folder)) == "openhora-fetcher:" + base[:12]
    original = (folder / "tool-pin.json").read_text()
    pin = json.loads(original)
    (folder / "tool-pin.json").write_text(json.dumps(dict(pin, version="2099.02.02")))
    assert _fetcher_image.definition_hash(str(folder)) != base
    (folder / "tool-pin.json").write_text(original)
    assert _fetcher_image.definition_hash(str(folder)) == base
    (folder / "_fetcher_inner.py").write_text((folder / "_fetcher_inner.py").read_text() + "\n# edit\n")
    assert _fetcher_image.definition_hash(str(folder)) != base
    host_only = folder / "ytdlp.py"
    before = _fetcher_image.definition_hash(str(folder))
    host_only.write_text(host_only.read_text() + "\n# edit\n")
    assert _fetcher_image.definition_hash(str(folder)) == before, "a host-only file changes no image"


def test_the_committed_pin_is_filled_from_the_releases_metadata():
    pin = _fetcher_image.effective_pin(str(K.FETCHER))
    assert pin["tool"] == "yt-dlp" and pin["asset"] == "yt-dlp" and pin["js_runtime"] is None
    assert _fetcher_image.pin_missing(pin) == [] and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) and pin["redirect_hosts"]


def test_build_and_check_refuse_a_null_pin_before_any_docker_call(tmp_path, monkeypatch):
    world = K.World(tmp_path, monkeypatch, pin=False)
    for argv in (["--check"], ["build", "--confirmed"], ["build", "--dry-run"]):
        code, out, _ = K.run_main(argv)
        assert (code, out) == (3, {"ok": False, "code": "pin_not_filled"}), argv
    assert world.calls() == []


def test_build_needs_the_word_of_the_person_and_a_dry_run_prints_the_command_without_docker(tmp_path, monkeypatch):
    world = K.World(tmp_path, monkeypatch, image=False)
    assert K.run_main(["build"])[:2] == (2, {"ok": False, "code": "bad_arguments"})
    code, out, _ = K.run_main(["build", "--dry-run"])
    assert code == 0 and out["dry_run"] is True and out["command"][:2] == ["docker", "build"] and world.calls() == []
    command = " ".join(out["command"])
    assert "TOOL_SHA256=" + K.PIN["sha256"] in command and "TOOL_REDIRECT_HOSTS=objects.example" in command and "DEFINITION_HASH=" + out["definition"] in command


def test_build_records_the_image_and_check_then_passes_and_refuses_a_stale_or_replaced_one(tmp_path, monkeypatch):
    world = K.World(tmp_path, monkeypatch, image=False)
    assert K.run_main(["--check"])[:2] == (3, {"ok": False, "code": "image_not_built"})
    world.install_image()
    world.save()
    code, out, _ = K.run_main(["--check"])
    assert code == 0 and out["tool"] == K.PIN["version"]
    world.install_image(definition="0" * 64)
    world.save()
    assert K.run_main(["--check"])[:2] == (3, {"ok": False, "code": "image_not_built"})
    world.install_image()
    (world.state / "fetcher" / "image.json").write_text(json.dumps({"image_id": "sha256:other"}))
    world.save()
    assert K.run_main(["--check"])[:2] == (3, {"ok": False, "code": "image_not_built"})


def test_a_remote_daemon_and_a_stopped_one_are_not_configured(tmp_path, monkeypatch):
    world = K.World(tmp_path, monkeypatch, context="tcp://remote.example:2375")
    code, out, _ = K.run_main(["--check"])
    assert (code, out) == (3, {"ok": False, "code": "docker_not_local"})
    world.cfg.update(context="unix:///var/run/docker.sock", down=True)
    world.save()
    assert K.run_main(["--check"])[:2] == (3, {"ok": False, "code": "docker_not_running"})


def test_the_verbs_line_names_the_verbs_and_the_pin_show_verb_fetches_nothing(tmp_path, monkeypatch):
    world = K.World(tmp_path, monkeypatch, pin=False)
    assert ytdlp.VERBS == ("pin-show", "pin-latest", "pin-raise", "build", "reap", "fetch", "measure")
    code, out, _ = K.run_main(["pin-show"])
    assert code == 0 and out["filled"] is False and "sha256" in out["missing"] and world.calls() == []


def test_reap_needs_the_marker_and_removes_old_run_folders_only(tmp_path, monkeypatch):
    world = K.World(tmp_path, monkeypatch)
    old, fresh = world.ref / ".fetch-aaaaaaaaaaaa", world.ref / ".fetch-bbbbbbbbbbbb"
    for folder in (old, fresh):
        folder.mkdir()
    os.utime(old, (1, 1))
    code, out, _ = K.run_main(["reap", "--root", str(world.refs)])
    assert code == 0 and out["folders_removed"] == 1 and not old.exists() and fresh.exists()
    plain = tmp_path / "plain"
    plain.mkdir()
    assert K.run_main(["reap", "--root", str(plain)])[:2] == (2, {"ok": False, "code": "out_refused"})


# --- the build's download script, against a loopback server ------------------------------------------------------------------------------


class Server:
    def __init__(self, routes):
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                status, headers, body = routes[self.path]
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v.replace("PORT", str(outer.port)))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()


PAYLOAD = b"print('a pinned tool')\n" * 50
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def download(tmp_path, url, size=len(PAYLOAD), sha=DIGEST, hosts="127.0.0.1"):
    dest = tmp_path / "yt-dlp"
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), url, str(size), sha, hosts, str(dest)], capture_output=True, text=True,
                          env={"FETCHER_TEST": "1", "PATH": os.environ["PATH"]})
    return done, dest


@pytest.fixture
def server():
    made = []

    def start(routes):
        s = Server(routes)
        made.append(s)
        return s
    yield start
    for s in made:
        s.stop()


def test_the_download_checks_size_and_sha256_and_writes_the_file_read_only(tmp_path, server):
    s = server({"/a": (200, {}, PAYLOAD)})
    done, dest = download(tmp_path, "http://127.0.0.1:%d/a" % s.port)
    assert done.returncode == 0 and dest.read_bytes() == PAYLOAD and (dest.stat().st_mode & 0o777) == 0o555
    for size, sha, why in ((len(PAYLOAD) - 1, DIGEST, "size_differs"), (len(PAYLOAD) + 1, DIGEST, "size_differs"), (len(PAYLOAD), "0" * 64, "sha256_differs")):
        done, dest2 = download(tmp_path, "http://127.0.0.1:%d/a" % s.port, size=size, sha=sha)
        assert done.returncode == 1 and why in done.stderr


def test_exactly_one_redirect_to_a_listed_host_is_followed(tmp_path, server):
    s = server({"/a": (302, {"Location": "http://127.0.0.1:PORT/b"}, b""), "/b": (200, {}, PAYLOAD)})
    done, dest = download(tmp_path, "http://127.0.0.1:%d/a" % s.port)
    assert done.returncode == 0 and dest.read_bytes() == PAYLOAD


def test_a_second_redirect_is_refused(tmp_path, server):
    s = server({"/a": (302, {"Location": "/b"}, b""), "/b": (301, {"Location": "/c"}, b""), "/c": (200, {}, PAYLOAD)})
    done, dest = download(tmp_path, "http://127.0.0.1:%d/a" % s.port)
    assert done.returncode == 1 and "second_redirect" in done.stderr and not dest.exists()


def test_a_redirect_to_another_host_or_scheme_is_refused(tmp_path, server):
    s = server({"/a": (302, {"Location": "http://localhost:PORT/b"}, b""), "/b": (200, {}, PAYLOAD),
                "/c": (302, {"Location": "https://other.example/x"}, b""), "/d": (302, {"Location": "ftp://127.0.0.1/x"}, b"")})
    for path in ("/a", "/c", "/d"):
        done, dest = download(tmp_path, "http://127.0.0.1:%d%s" % (s.port, path))
        assert done.returncode == 1 and "redirect_host_not_allowed" in done.stderr or "url_not_allowed" in done.stderr, path
        assert not dest.exists()


def test_a_plain_http_url_is_refused_outside_the_test_mode_and_a_bad_status_is_a_failed_download(tmp_path, server):
    s = server({"/a": (200, {}, PAYLOAD), "/missing": (404, {}, b"no")})
    dest = tmp_path / "yt-dlp"
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), "http://127.0.0.1:%d/a" % s.port, str(len(PAYLOAD)), DIGEST, "127.0.0.1", str(dest)],
                          capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert done.returncode == 1 and "url_not_allowed" in done.stderr
    done, _ = download(tmp_path, "http://127.0.0.1:%d/missing" % s.port)
    assert done.returncode == 1 and "download_failed" in done.stderr


def test_the_dockerfile_passes_the_pin_to_the_script_and_never_uses_pip():
    text = (K.FETCHER / "Dockerfile").read_text()
    assert "pip" not in re.sub(r"#.*", "", text).lower().replace("pipe", "")
    assert '"${TOOL_URL}" "${TOOL_SIZE}" "${TOOL_SHA256}" "${TOOL_REDIRECT_HOSTS}" /opt/fetcher/yt-dlp' in text
    assert "FROM debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587" in text and "DEBIAN_SNAPSHOT=20261006T000000Z" in text
    assert "ffmpeg python3 ca-certificates" in text and 'ENTRYPOINT ["python3", "-I", "/opt/fetcher/_fetcher_inner.py"]' in text and "USER 10001:10001" in text
