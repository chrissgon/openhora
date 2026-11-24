"""fetch_hf.py (build time only): a local fake tarball, served through a replaced opener, passes; every kind of mismatch refuses with exit 2
and leaves no output folder. No network."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import tarfile

import pytest

import renderer_kit as K

SPEC = importlib.util.spec_from_file_location("fetch_hf", K.RENDERER / "hf-runtime" / "fetch_hf.py")
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)

GSAP_URL = "https://registry.npmjs.org/gsap/-/gsap-3.14.2.tgz"
HF_URL = "https://registry.npmjs.org/hyperframes/-/hyperframes-0.9.19.tgz"
COMMIT = "b" * 40


def tarball(members, extra=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for info in extra or []:
            tar.addfile(info)
    return buf.getvalue()


def integrity(body):
    return "sha512-" + base64.b64encode(hashlib.sha512(body).digest()).decode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class World:
    def __init__(self, tmp_path, monkeypatch, gsap_extra=None, gsap_members=None, url=GSAP_URL):
        gs = gsap_members or {"package/dist/gsap.min.js": b"gsap-bytes", "package/other": b"x"}
        self.bodies = {url: tarball(gs, gsap_extra), HF_URL: tarball({"package/dist/hyperframe.runtime.iife.js": b"runtime", "package/dist/hyperframe.manifest.json": b"{}"})}
        self.license = b"licence text"
        self.pins = {"schema_version": 1, "packages": [
            {"name": "gsap", "version": "3.14.2", "url": url, "integrity": integrity(self.bodies[url]), "files": {"package/dist/gsap.min.js": sha(b"gsap-bytes")}},
            {"name": "hyperframes", "version": "0.9.19", "url": HF_URL, "integrity": integrity(self.bodies[HF_URL]),
             "files": {"package/dist/hyperframe.runtime.iife.js": sha(b"runtime"), "package/dist/hyperframe.manifest.json": sha(b"{}")}}]}
        self.registry = "# commit %s\n%s  LICENSE\n" % (COMMIT, sha(self.license))
        self.tmp = tmp_path
        self.out, self.reg_out = tmp_path / "vendor", tmp_path / "reg"
        self.asked = []
        raw = F.RAW_URL % (COMMIT, "LICENSE")
        self.bodies[raw] = self.license

        def opener(u):
            self.asked.append(u)
            return io.BytesIO(self.bodies[u]) if u in self.bodies else (_ for _ in ()).throw(AssertionError("unexpected url " + u))
        monkeypatch.setattr(F, "opener", opener)

    def run(self):
        (self.tmp / "pins.json").write_text(json.dumps(self.pins), encoding="utf-8")
        (self.tmp / "registry.sha256").write_text(self.registry, encoding="utf-8")
        return F.main(["--out", str(self.out), "--registry-out", str(self.reg_out), "--pins", str(self.tmp / "pins.json"), "--registry", str(self.tmp / "registry.sha256")])

    def nothing_left(self):
        return not self.out.exists() and not self.reg_out.exists() and not (self.tmp / "vendor.part").exists() and not (self.tmp / "reg.part").exists()


def test_a_good_fake_tarball_passes_writes_only_the_named_members_read_only(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    assert w.run() == 0
    assert sorted(p.name for p in w.out.iterdir()) == ["gsap.min.js", "hyperframe.manifest.json", "hyperframe.runtime.iife.js"]
    assert (w.out / "gsap.min.js").read_bytes() == b"gsap-bytes" and oct((w.out / "gsap.min.js").stat().st_mode & 0o777) == "0o444"
    assert (w.reg_out / "LICENSE").read_bytes() == w.license and oct((w.reg_out / "LICENSE").stat().st_mode & 0o777) == "0o444"
    assert json.loads(capsys.readouterr().out)["registry"] == ["LICENSE"]


def test_a_wrong_integrity_refuses_and_leaves_nothing(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.pins["packages"][0]["integrity"] = integrity(b"another body")
    assert w.run() == 2 and w.nothing_left() and "integrity mismatch" in capsys.readouterr().err


def test_a_wrong_member_sha256_refuses(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.pins["packages"][0]["files"]["package/dist/gsap.min.js"] = "0" * 64
    assert w.run() == 2 and w.nothing_left() and "hash mismatch" in capsys.readouterr().err


def test_a_link_member_refuses_even_when_it_is_not_one_of_the_named_members(tmp_path, monkeypatch, capsys):
    link = tarfile.TarInfo("package/evil")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    w = World(tmp_path, monkeypatch, gsap_extra=[link])
    assert w.run() == 2 and w.nothing_left() and "refused member" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["../x", "package/../../x", "/abs/x"])
def test_a_member_path_that_climbs_or_is_absolute_refuses(tmp_path, monkeypatch, name):
    w = World(tmp_path, monkeypatch, gsap_members={"package/dist/gsap.min.js": b"gsap-bytes", name: b"x"})
    assert w.run() == 2 and w.nothing_left()


def test_a_member_over_eight_mib_refuses(tmp_path, monkeypatch, capsys):
    big = b"a" * (8 * 1024 * 1024 + 1)
    w = World(tmp_path, monkeypatch, gsap_members={"package/dist/gsap.min.js": big})
    w.pins["packages"][0]["files"]["package/dist/gsap.min.js"] = sha(big)
    assert w.run() == 2 and w.nothing_left() and "under" in capsys.readouterr().err


def test_a_tarball_over_the_cap_refuses(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    monkeypatch.setattr(F, "TARBALL_CAP", 10)
    assert w.run() == 2 and w.nothing_left() and "is over" in capsys.readouterr().err


@pytest.mark.parametrize("url", ["https://example.test/gsap/-/gsap-3.14.2.tgz", "http://registry.npmjs.org/gsap/-/gsap-3.14.2.tgz",
                                 "https://registry.npmjs.org/other/-/other-1.0.0.tgz", "https://registry.npmjs.org.evil.test/gsap/-/gsap-3.14.2.tgz"])
def test_a_url_outside_the_pattern_refuses_before_any_request(tmp_path, monkeypatch, url):
    w = World(tmp_path, monkeypatch)
    w.pins["packages"][0]["url"] = url
    assert w.run() == 2 and w.nothing_left() and w.asked == []


def test_a_registry_row_with_the_wrong_hash_refuses_and_leaves_no_vendor_folder(tmp_path, monkeypatch, capsys):
    w = World(tmp_path, monkeypatch)
    w.registry = "# commit %s\n%s  LICENSE\n" % (COMMIT, "0" * 64)
    assert w.run() == 2 and w.nothing_left() and "hash mismatch for LICENSE" in capsys.readouterr().err


def test_a_registry_manifest_with_no_commit_or_a_bad_path_refuses(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.registry = "%s  LICENSE\n" % sha(w.license)
    assert w.run() == 2 and w.nothing_left()
    w.registry = "# commit %s\n%s  ../LICENSE\n" % (COMMIT, sha(w.license))
    assert w.run() == 2 and w.nothing_left()


def test_help_prints_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as stop:
        F.main(["--help"])
    assert stop.value.code == 0 and "--registry-out" in capsys.readouterr().out
