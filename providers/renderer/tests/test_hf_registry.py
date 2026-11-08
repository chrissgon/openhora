"""The registry pins of the HyperFrames image (V3b-3): `registry.sha256`, `fetch_registry.py`, the allowlist's agreement with them, the
Dockerfile's hook lines, and the rule that the registry's maker is named in one line only. Offline: the download is replaced by a stub."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "providers" / "renderer" / "hyperframes-image"
ALLOWLIST = ROOT / "providers" / "renderer" / "blocks" / "hf" / "allowlist.json"
LICENCE_SHA256 = "4259155fb06f127687ee7b0a8a3682d45132db0f2da26cbc0b7a2d1e796436b8"
COMMIT = "b4cc674f7f312e77ded32e0b53006cc0bad6723b"
MAKER = "hey" + "gen"                                  # written in two pieces so that this file is not a line that names it


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


F = load("fetch_registry_under_test", FOLDER / "fetch_registry.py")


def parsed():
    commit, rows = F.read_manifest(str(FOLDER / "registry.sha256"))
    return commit, dict((path, digest) for digest, path in rows)


def test_the_pin_file_names_the_commit_and_holds_the_licence_first():
    commit, rows = parsed()
    assert commit == COMMIT and rows["LICENSE"] == LICENCE_SHA256 and all(len(v) == 64 for v in rows.values())
    assert list(rows)[0] == "LICENSE"


def test_the_allowlists_commit_is_the_pin_files_and_every_file_of_every_entry_is_pinned_with_its_hash():
    commit, rows = parsed()
    allow = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    if allow["registry_commit"] is not None:
        assert allow["registry_commit"] == commit
    for block in allow["blocks"]:
        short = block["name"].split(":")[1]
        assert block["commit"] == commit and block["tier"] == "A"
        for rel, digest in block["files"].items():
            assert rows.get("registry/components/%s/%s" % (short, rel)) == digest, (block["name"], rel)
    pinned_components = {p.split("/")[2] for p in rows if p.startswith("registry/components/")}
    assert pinned_components == {b["name"].split(":")[1] for b in allow["blocks"]}, "the pin file holds the files of the admitted components and nothing else"


def test_the_fetch_script_starts_alone_and_its_url_is_the_only_line_naming_the_maker():
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/nonexistent")}
    done = subprocess.run([sys.executable, "-I", str(FOLDER / "fetch_registry.py"), "--help"], capture_output=True, text=True, env=env, timeout=60, cwd="/")
    assert done.returncode == 0 and "manifest" in done.stdout and "dest" in done.stdout, done.stderr[-400:]
    lines = [line for line in (FOLDER / "fetch_registry.py").read_text(encoding="utf-8").splitlines() if MAKER in line.lower()]
    assert len(lines) == 1 and lines[0].startswith("URL = ")
    for path in sorted(FOLDER.iterdir()):
        if path.is_file() and path.name not in ("fetch_registry.py", "NOTICE.md") and path.suffix in (".py", ".json", ".md", ".sha256", "") and path.name != "package-lock.json":
            assert MAKER not in path.read_text(encoding="utf-8", errors="replace").lower(), path.name


def test_the_dockerfile_has_the_two_hook_lines_in_place_of_the_comment_block_and_copies_the_inner_scripts_last():
    text = (FOLDER / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY registry.sha256 fetch_registry.py /opt/hf-build/\n" in text
    assert "RUN python3 -I /opt/hf-build/fetch_registry.py /opt/hf-build/registry.sha256 /opt/hf-registry\n" in text
    assert "#   COPY registry.sha256" not in text
    assert text.index("fetch_registry.py /opt/hf-build/") < text.index("useradd") < text.index("COPY hf_render.py") < text.index("COPY hf_wrap.py hf_compat.py")
    manifest = json.loads((FOLDER / "manifest.json").read_text(encoding="utf-8"))["files"]
    ignore = (FOLDER / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for name in ("hf_wrap.py", "hf_compat.py", "fetch_registry.py", "registry.sha256"):
        assert name in manifest and "!" + name in ignore


class Response:
    def __init__(self, body):
        self.body = body

    def read(self, n=-1):
        return self.body[:n] if n >= 0 else self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def manifest(tmp_path, rows, commit=COMMIT):
    path = tmp_path / "m.sha256"
    path.write_text("# commit %s\n# a comment\n" % commit + "".join("%s  %s\n" % row for row in rows))
    return str(path)


def test_the_fetch_writes_each_file_read_only_only_when_its_hash_matches(tmp_path, monkeypatch):
    body = b"a fictional licence\n"
    urls = []
    monkeypatch.setattr(F.urllib.request, "urlopen", lambda url, timeout: urls.append(url) or Response(body))
    F.main([manifest(tmp_path, [(hashlib.sha256(body).hexdigest(), "LICENSE"), (hashlib.sha256(body).hexdigest(), "registry/components/aster-pop/aster-pop.html")]), str(tmp_path / "out")])
    assert (tmp_path / "out" / "registry" / "components" / "aster-pop" / "aster-pop.html").read_bytes() == body
    assert oct((tmp_path / "out" / "LICENSE").stat().st_mode & 0o777) == "0o444" and all(("/%s/" % COMMIT) in u for u in urls)


def test_a_hash_mismatch_an_oversize_file_a_bad_path_or_no_commit_is_refused_and_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(F.urllib.request, "urlopen", lambda url, timeout: Response(b"other"))
    with pytest.raises(SystemExit) as mismatch:
        F.main([manifest(tmp_path, [("0" * 64, "LICENSE")]), str(tmp_path / "o1")])
    assert "hash mismatch" in str(mismatch.value) and not (tmp_path / "o1" / "LICENSE").exists()
    monkeypatch.setattr(F.urllib.request, "urlopen", lambda url, timeout: Response(b"x" * (F.CAP + 1)))
    with pytest.raises(SystemExit) as big:
        F.main([manifest(tmp_path, [("0" * 64, "LICENSE")]), str(tmp_path / "o2")])
    assert "over" in str(big.value)
    monkeypatch.setattr(F.urllib.request, "urlopen", lambda url, timeout: pytest.fail("a download was started"))
    for rows in ([("0" * 64, "../etc/passwd")], [("0" * 64, "/abs")], [("zz", "LICENSE")]):
        with pytest.raises(SystemExit):
            F.main([manifest(tmp_path, rows), str(tmp_path / "o3")])
    with pytest.raises(SystemExit):
        F.main([manifest(tmp_path, [], commit="short"), str(tmp_path / "o4")])


def test_a_manifest_line_with_one_token_and_a_duplicate_path_are_refused_with_a_clean_message(tmp_path, monkeypatch):
    monkeypatch.setattr(F.urllib.request, "urlopen", lambda url, timeout: pytest.fail("a download was started"))
    one = tmp_path / "one.sha256"
    one.write_text("# commit %s\n%s\n" % (COMMIT, "a" * 64))
    with pytest.raises(SystemExit) as caught:
        F.main([str(one), str(tmp_path / "o")])
    assert "bad manifest line" in str(caught.value)
    digest = "a" * 64
    with pytest.raises(SystemExit) as dup:
        F.main([manifest(tmp_path, [(digest, "LICENSE"), (digest, "LICENSE")]), str(tmp_path / "o2")])
    assert "duplicate path" in str(dup.value)
