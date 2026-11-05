"""Tests for skills/ops-repo-baseline/scripts/gitleaks_setup.py and for the gitleaks assets next to it.

Offline: nothing here downloads anything. The download function is replaced by a copy of a local archive,
and the archives are built in a temporary folder from fictional bytes.

Run: uv run --with pytest pytest skills/ops-repo-baseline/scripts/tests
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2]
SETUP = SKILL / "scripts" / "gitleaks_setup.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


@pytest.fixture()
def gl():
    return load("gitleaks_setup_under_test", SETUP)


def make_archive(path: Path, members: dict[str, bytes]) -> str:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------- the script ----------

def test_print_pin_needs_no_network_and_lists_four_official_urls():
    out = subprocess.run([sys.executable, str(SETUP), "--print-pin"], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    pin = json.loads(out.stdout)
    assert re.fullmatch(r"\d+\.\d+\.\d+", pin["version"])
    assert set(pin["sha256"]) == {"linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64"}
    for plat, digest in pin["sha256"].items():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert pin["urls"][plat] == (
            f"https://github.com/gitleaks/gitleaks/releases/download/v{pin['version']}/"
            f"gitleaks_{pin['version']}_{plat.replace('-', '_')}.tar.gz")


def test_install_from_a_local_archive_writes_binary_and_version(tmp_path, gl):
    archive = tmp_path / "a.tar.gz"
    digest = make_archive(archive, {"LICENSE": b"licence", "README.md": b"readme", "gitleaks": b"#!/bin/sh\necho fake\n"})
    gl.SHA256["linux-x64"] = digest
    dest = tmp_path / "bin"
    assert gl.main(["--archive", str(archive), "--platform", "linux-x64", "--dest", str(dest)]) == 0
    binary = dest / "gitleaks"
    assert binary.read_bytes() == b"#!/bin/sh\necho fake\n"
    assert binary.stat().st_mode & 0o111
    assert (dest / "gitleaks.version").read_text() == gl.VERSION + "\n"
    assert not (dest / "gitleaks.tmp").exists()
    assert sorted(p.name for p in dest.iterdir()) == ["gitleaks", "gitleaks.version"]


def test_a_checksum_that_differs_installs_nothing(tmp_path, gl):
    archive = tmp_path / "a.tar.gz"
    make_archive(archive, {"gitleaks": b"other bytes"})
    dest = tmp_path / "bin"
    with pytest.raises(SystemExit) as exc:
        gl.main(["--archive", str(archive), "--platform", "darwin-arm64", "--dest", str(dest)])
    assert "nothing was installed" in str(exc.value)
    assert not dest.exists()


def test_an_archive_without_the_binary_installs_nothing(tmp_path, gl):
    archive = tmp_path / "a.tar.gz"
    gl.SHA256["linux-arm64"] = make_archive(archive, {"README.md": b"x", "../gitleaks": b"escape", "sub/gitleaks": b"nested"})
    dest = tmp_path / "bin"
    with pytest.raises(SystemExit) as exc:
        gl.main(["--archive", str(archive), "--platform", "linux-arm64", "--dest", str(dest)])
    assert "no file named gitleaks" in str(exc.value)
    assert not (dest / "gitleaks").exists()
    assert not (tmp_path / "gitleaks").exists()


def test_download_is_the_only_network_call_and_is_checked_the_same(tmp_path, gl, monkeypatch):
    source = tmp_path / "source.tar.gz"
    gl.SHA256["darwin-x64"] = make_archive(source, {"gitleaks": b"binary"})
    asked = []

    def fake_download(url, out_path):
        asked.append(url)
        Path(out_path).write_bytes(source.read_bytes())

    monkeypatch.setattr(gl, "download", fake_download)
    dest = tmp_path / "bin"
    assert gl.main(["--platform", "darwin-x64", "--dest", str(dest)]) == 0
    assert asked == [gl.archive_url("darwin-x64")]
    assert (dest / "gitleaks").read_bytes() == b"binary"


def test_a_failed_download_exits_1_and_writes_nothing(tmp_path, gl, monkeypatch):
    def broken(url, out_path):
        raise OSError("offline")

    monkeypatch.setattr(gl, "download", broken)
    dest = tmp_path / "bin"
    assert gl.main(["--platform", "linux-x64", "--dest", str(dest)]) == 1
    assert not dest.exists()


def test_download_refuses_a_url_outside_the_releases_page(tmp_path, gl):
    with pytest.raises(SystemExit):
        gl.download("https://example.invalid/gitleaks.tar.gz", str(tmp_path / "x"))


def test_platform_detection(gl, monkeypatch):
    monkeypatch.setattr(gl.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(gl.platform, "machine", lambda: "arm64")
    assert gl.detect_platform() == "darwin-arm64"
    monkeypatch.setattr(gl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(gl.platform, "machine", lambda: "x86_64")
    assert gl.detect_platform() == "linux-x64"
    monkeypatch.setattr(gl.platform, "system", lambda: "Windows")
    with pytest.raises(SystemExit):
        gl.detect_platform()


# ---------- the pin is the same in every file that carries it ----------

def pin():
    return load("gitleaks_setup_pin", SETUP)


def test_workflow_asset_carries_the_pinned_version_and_linux_x64_checksum():
    text = (SKILL / "assets" / "checks.yml").read_text()
    module = pin()
    assert f'GITLEAKS_VERSION: "{module.VERSION}"' in text
    assert f'GITLEAKS_SHA256: "{module.SHA256["linux-x64"]}"' in text
    assert "sha256sum --check" in text
    # the checksum is checked before the archive is unpacked, and no action is used for gitleaks
    assert text.index("sha256sum --check") < text.index("tar -xzf")
    uses = [line for line in text.splitlines() if re.match(r"\s*-?\s*uses:", line)]
    assert not any("gitleaks" in line for line in uses)
    # the bundled scanner stays in the same job
    assert "scripts/secret-scan/secret_scan.py --history" in text


def test_hook_asset_names_the_pinned_version_and_never_downloads():
    text = (SKILL / "assets" / "pre-commit").read_text()
    assert f'= "{pin().VERSION}"' in text
    assert "gitleaks_setup.py" in text
    assert not re.search(r"\b(curl|wget)\b", text)
    assert "scripts/secret-scan/secret_scan.py" in text.split("gitleaks")[0]  # the bundled scan runs first


def test_reference_table_has_the_four_checksums_of_the_pin():
    text = (SKILL / "references" / "gitleaks.md").read_text()
    module = pin()
    for digest in module.SHA256.values():
        assert digest in text
    assert f"v{module.VERSION}" in text
    assert "2026-10-15" in text


# ---------- the configuration agrees with the bundled scanner ----------

def test_gitleaks_config_allows_exactly_the_bundled_scanners_planted_folders():
    scan = load("secret_scan_under_test", SKILL / "scripts" / "secret_scan.py")
    config = tomllib.loads((SKILL / "assets" / "gitleaks.toml").read_text())
    assert config["extend"] == {"useDefault": True}
    (allow,) = config["allowlists"]
    assert set(allow) == {"description", "paths"}  # paths only: no regexes, commits or stopwords
    (pattern,) = allow["paths"]
    folders = re.fullmatch(r"\(\^\|/\)\(([^)]*)\)/", pattern)
    assert folders, pattern
    assert set(folders.group(1).split("|")) == set(scan.PLANTED_DIRS)
    assert "rules" not in config


@pytest.mark.parametrize("rel", [
    "tests/app.js", "src/tests/app.js", "evals/files/x/pay.js", "docs/examples/a.env", "fixtures/a", "a/__tests__/b.js",
    "src/app.js", "src/testing/app.js", "contest/app.js", "tests", "latest/app.js", "example.js",
])
def test_gitleaks_config_and_bundled_scanner_agree_on_a_path(rel):
    scan = load("secret_scan_under_test2", SKILL / "scripts" / "secret_scan.py")
    config = tomllib.loads((SKILL / "assets" / "gitleaks.toml").read_text())
    regex = re.compile(config["allowlists"][0]["paths"][0])
    bundled_says_planted = bool(scan.PLANTED_DIRS & set(rel.split("/")[:-1]))
    assert bool(regex.search(rel)) == bundled_says_planted


# ---------- the gitleaks command and the way to ignore a finding are the same everywhere they are written ----------

def test_local_command_in_the_skill_equals_the_workflow_command_and_ignore_file_is_explained():
    skill_md = (SKILL / "SKILL.md").read_text()
    workflow = (SKILL / "assets" / "checks.yml").read_text()
    command = "git --redact --no-banner --exit-code 1 --config scripts/secret-scan/gitleaks.toml ."
    assert f"scripts/secret-scan/bin/gitleaks {command}" in skill_md
    assert command in workflow
    for text in (skill_md, (SKILL / "references" / "gitleaks.md").read_text()):
        assert ".gitleaksignore" in text
        assert "<commit>:<file>:<rule>:<line>" in text
        assert "<file>:<rule>:<line>" in text and "not committed yet" in text
    assert "stay red" in (SKILL / "references" / "gitleaks.md").read_text()
