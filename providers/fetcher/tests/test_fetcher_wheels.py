"""The wheel unpacker of the image's build (`_fetch_tool.py wheels`), against a loopback server and wheels made here under a fictional name.
Offline: the server is on loopback, the site folder is a temporary one."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import zipfile

import pytest

import fetcher_kit as K
import _fetch_tool

NAME = "asterlane_kit"
VERSION = "1.0"


def make_wheel(members, name=NAME, version=VERSION, links=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for member, data in members.items():
            z.writestr(member, data)
        for member, target in links:
            info = zipfile.ZipInfo(member)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, target)
    return buf.getvalue()


GOOD = {NAME + "/__init__.py": "X = 1\n", NAME + "/lib.so": "elf", "%s-%s.dist-info/METADATA" % (NAME, VERSION): "Name: x\n"}


def entry(blob, arch="any", port=0, path="/w.whl", name=NAME, version=VERSION):
    return {"name": name, "version": version, "arch": arch, "filename": "w.whl", "url": "http://127.0.0.1:%d%s" % (port, path), "size": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest()}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.setenv("FETCHER_TEST", "1")
    monkeypatch.setattr(_fetch_tool, "SITE_PREFIX", str(tmp_path))
    monkeypatch.setattr(_fetch_tool.site, "getsitepackages", lambda: ["/elsewhere/lib", str(site)])
    made = []

    def run(entries, routes, hosts=("127.0.0.1",), redirects=(), machine="x86_64", edit=None):
        for child in site.iterdir():
            (shutil.rmtree(child) if child.is_dir() else child.unlink())
        server = K.Server(routes)
        made.append(server)
        for e in entries:
            e["url"] = e["url"] and e["url"].replace("127.0.0.1:0", "127.0.0.1:%d" % server.port)
        pin = {"read_on": "2099-01-02", "download_hosts": list(hosts), "redirect_hosts": list(redirects), "wheels": entries}
        if edit:
            edit(pin)
        path = tmp_path / "wheel-pin.json"
        path.write_text(json.dumps(pin))
        monkeypatch.setattr(_fetch_tool.platform, "machine", lambda: machine)
        try:
            _fetch_tool.wheels(str(path))
            return 0
        except SystemExit as e:
            return e.code
    run.site = site
    yield run
    for s in made:
        s.stop()


def refused(setup, capsys, entries, routes, why, **kw):
    assert setup(entries, routes, **kw) == 1
    assert why in capsys.readouterr().err, why
    assert list(setup.site.iterdir()) == [], "nothing was written"


def test_a_pure_wheel_installs_on_both_machines_with_safe_modes(setup):
    blob = make_wheel(GOOD)
    for machine in ("x86_64", "aarch64"):
        assert setup([entry(blob)], {"/w.whl": (200, {}, blob)}, machine=machine) == 0
        assert (setup.site / NAME / "__init__.py").read_text() == "X = 1\n"
    for root, dirs, files in os.walk(setup.site):
        for name in files:
            assert stat.S_IMODE(os.stat(os.path.join(root, name)).st_mode) == 0o644
        for name in dirs + [""]:
            assert stat.S_IMODE(os.stat(os.path.join(root, name)).st_mode) & 0o022 == 0


def test_the_entry_of_the_machine_is_the_one_installed_and_another_machine_is_not_pinned(setup, capsys):
    amd, arm = make_wheel({NAME + "/__init__.py": "A = 'amd'\n"}), make_wheel({NAME + "/__init__.py": "A = 'arm'\n"})
    routes = {"/a.whl": (200, {}, amd), "/b.whl": (200, {}, arm)}
    entries = lambda: [entry(amd, "amd64", path="/a.whl"), entry(arm, "arm64", path="/b.whl")]  # noqa: E731
    assert setup(entries(), routes, machine="aarch64") == 0 and "arm" in (setup.site / NAME / "__init__.py").read_text()
    assert setup(entries(), routes, machine="x86_64") == 0 and "amd" in (setup.site / NAME / "__init__.py").read_text()
    for child in setup.site.iterdir():
        shutil.rmtree(child)
    refused(setup, capsys, entries(), routes, "machine_not_pinned", machine="riscv64")


@pytest.mark.parametrize("field", ["name", "version", "arch", "filename", "url", "size", "sha256"])
def test_each_null_field_is_pin_incomplete(setup, capsys, field):
    blob = make_wheel(GOOD)
    e = entry(blob)
    e[field] = None
    refused(setup, capsys, [e], {"/w.whl": (200, {}, blob)}, "pin_incomplete")


@pytest.mark.parametrize("edit", [lambda p: p.update(read_on=None), lambda p: p.update(download_hosts=[])])
def test_a_null_top_level_field_is_pin_incomplete(setup, capsys, edit):
    blob = make_wheel(GOOD)
    refused(setup, capsys, [entry(blob)], {"/w.whl": (200, {}, blob)}, "pin_incomplete", edit=edit)


def test_a_size_or_sha256_that_differs_is_refused(setup, capsys):
    blob = make_wheel(GOOD)
    routes = {"/w.whl": (200, {}, blob)}
    refused(setup, capsys, [dict(entry(blob), size=len(blob) - 1)], routes, "size_differs")
    refused(setup, capsys, [dict(entry(blob), size=len(blob) + 1)], routes, "size_differs")
    refused(setup, capsys, [dict(entry(blob), sha256="0" * 64)], routes, "sha256_differs")


def test_an_address_off_the_download_hosts_is_refused(setup, capsys):
    blob = make_wheel(GOOD)
    refused(setup, capsys, [entry(blob)], {"/w.whl": (200, {}, blob)}, "redirect_host_not_allowed", hosts=("files.example",))


def test_redirects_zero_or_one_to_a_listed_host_only(setup, capsys):
    blob = make_wheel(GOOD)
    one = {"/w.whl": (302, {"Location": "http://localhost:PORT/real"}, b""), "/real": (200, {}, blob)}
    assert setup([entry(blob)], {"/w.whl": (200, {}, blob)}) == 0                                     # zero
    assert setup([entry(blob)], one, redirects=("localhost",)) == 0                                    # one, to a listed host
    refused(setup, capsys, [entry(blob)], one, "redirect_host_not_allowed", redirects=())             # an empty list allows none
    refused(setup, capsys, [entry(blob)], one, "redirect_host_not_allowed", redirects=("other.example",))
    two = {"/w.whl": (302, {"Location": "/b"}, b""), "/b": (301, {"Location": "/c"}, b""), "/c": (200, {}, blob)}
    refused(setup, capsys, [entry(blob)], two, "second_redirect", redirects=("127.0.0.1",))


@pytest.mark.parametrize("members,links", [({"../x": "x"}, ()), ({"/abs": "x"}, ()), ({NAME + "\\a": "x"}, ()), ({NAME + "/ok.py": "x"}, [(NAME + "/link", "/etc/passwd")]),
                                           ({"%s-%s.data/x" % (NAME, VERSION): "x"}, ()), ({"other/x": "x"}, ()), ({NAME + "/a/../../x": "x"}, ())])
def test_a_member_that_is_not_allowed_refuses_the_whole_wheel_with_nothing_written(setup, capsys, members, links):
    blob = make_wheel(dict(GOOD, **members), links=links)
    refused(setup, capsys, [entry(blob)], {"/w.whl": (200, {}, blob)}, "wheel_member_refused")


def test_a_wheel_with_too_many_members_or_too_large_a_size_is_too_large(setup, capsys, monkeypatch):
    many = make_wheel({"%s/f%d" % (NAME, i): "" for i in range(2001)})
    refused(setup, capsys, [entry(many)], {"/w.whl": (200, {}, many)}, "wheel_too_large")
    big = make_wheel({NAME + "/big": b"\0" * (1 << 20)})
    monkeypatch.setattr(_fetch_tool, "MAX_UNPACKED", 1 << 19)
    refused(setup, capsys, [entry(big)], {"/w.whl": (200, {}, big)}, "wheel_too_large")
    assert _fetch_tool.MAX_UNPACKED == 1 << 19 and _fetch_tool.MAX_MEMBERS == 2000


def test_the_declared_size_over_256_mib_is_too_large(setup, capsys, monkeypatch):
    blob = make_wheel({NAME + "/x": "x"})
    real = zipfile.ZipFile.infolist

    def lying(self):
        infos = real(self)
        for info in infos:
            info.file_size = 257 << 20
        return infos
    monkeypatch.setattr(zipfile.ZipFile, "infolist", lying)
    refused(setup, capsys, [entry(blob)], {"/w.whl": (200, {}, blob)}, "wheel_too_large")


def test_the_c_module_beside_the_folder_of_cffi_and_the_libs_folder_are_allowed_and_no_other_top_level_file(setup, capsys):
    members = {"cffi/__init__.py": "", "_cffi_backend.cpython-311-x86_64-linux-gnu.so": "elf", "cffi.libs/libffi.so": "elf", "cffi-2.1.1.dist-info/METADATA": "x"}
    blob = make_wheel(members)
    e = entry(blob, name="cffi", version="2.1.1")
    assert setup([e], {"/w.whl": (200, {}, blob)}) == 0 and (setup.site / "_cffi_backend.cpython-311-x86_64-linux-gnu.so").exists()
    blob2 = make_wheel(dict(members, **{"stray.so": "elf"}))
    for child in setup.site.iterdir():
        (shutil.rmtree(child) if child.is_dir() else child.unlink())
    refused(setup, capsys, [entry(blob2, name="cffi", version="2.1.1")], {"/w.whl": (200, {}, blob2)}, "wheel_member_refused")


def test_there_is_no_site_folder_under_the_usual_prefix(setup, capsys, monkeypatch):
    blob = make_wheel(GOOD)
    monkeypatch.setattr(_fetch_tool, "SITE_PREFIX", "/nowhere/")
    refused(setup, capsys, [entry(blob)], {"/w.whl": (200, {}, blob)}, "no_site_folder")


def test_the_old_form_of_the_script_is_unchanged():
    assert _fetch_tool.main(["x", "wheels"]) == 2
