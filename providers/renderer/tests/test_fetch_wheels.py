"""`_fetch_wheels.py`, the build's one fetch of OpenCV and numpy (package P9-a1): a wheel is downloaded from a pinned host only, its size and sha256 must equal the
pin, its members are checked (no `..`, no absolute name, no link, only the wheel's own folders) and each one's sha256 against the wheel's own RECORD, all before
anything is written. No network: the download is a seam (`open_once`) pointed at a local file. Every wheel is built here, from invented files.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import stat
import zipfile

import pytest

import renderer_kit as K
import _fetch_wheels as W

NAME, VERSION = "demo_pkg", "1.2.3"
URL = "https://files.pythonhosted.org/packages/ab/cd/demo_pkg-1.2.3-cp311-cp311-manylinux2014_x86_64.whl"


def record_row(path, data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return "%s,sha256=%s,%d" % (path, digest, len(data))


def make_wheel(files=None, record=None, extra=(), link=None):
    """The bytes of a wheel with `files` ({member: bytes}) and a RECORD that lists them (or `record`, a replacement text); `extra` are members RECORD does not list."""
    files = files if files is not None else {"%s/__init__.py" % NAME: b"VALUE = 1\n", "%s/data.bin" % NAME: b"\x00\x01\x02", "%s.libs/libx.so" % NAME: b"ELF"}
    dist = "%s-%s.dist-info" % (NAME, VERSION)
    files = dict(files, **{dist + "/METADATA": b"Name: demo\n"})
    rows = [record_row(path, data) for path, data in files.items()] + ["%s/RECORD,," % dist]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for path, data in files.items():
            z.writestr(path, data)
        for path, data in extra:
            z.writestr(path, data)
        if link:
            info = zipfile.ZipInfo(link)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "/etc/passwd")
        z.writestr(dist + "/RECORD", record if record is not None else "\n".join(rows) + "\n")
    return buf.getvalue()


def entry(data, arch="amd64", **over):
    row = {"name": NAME, "version": VERSION, "arch": arch, "filename": URL.rsplit("/", 1)[1], "url": URL, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    row.update(over)
    return row


def pin(rows, hosts=("files.pythonhosted.org",), redirects=()):
    return {"note": "x", "source": "x", "read_on": "2026-11-26", "download_hosts": list(hosts), "redirect_hosts": list(redirects), "wheels": rows}


class Served:
    """A stand-in for the network: `open_once` answers with the bytes of the url's file, and logs every url asked for."""

    def __init__(self, monkeypatch, by_url):
        self.by_url, self.asked = by_url, []
        monkeypatch.setattr(W, "open_once", self.open_once)

    def open_once(self, url):
        self.asked.append(url)
        if url not in self.by_url:
            W.refuse("download_failed")
        return io.BytesIO(self.by_url[url]), None


def run(tmp_path, monkeypatch, rows, served, machine="x86_64", **pin_args):
    monkeypatch.setattr(W.platform, "machine", lambda: machine)
    path = tmp_path / "wheel-pin.json"
    path.write_text(json.dumps(pin(rows, **pin_args)), encoding="utf-8")
    dest = tmp_path / "site"
    dest.mkdir(exist_ok=True)
    W.wheels(str(path), str(dest))
    return dest


def refused(tmp_path, monkeypatch, rows, served, capsys, **kw):
    with pytest.raises(SystemExit) as caught:
        run(tmp_path, monkeypatch, rows, served, **kw)
    assert caught.value.code == 1
    err = capsys.readouterr().err
    return err.strip().split("refused: ")[-1]


def nothing_written(tmp_path):
    return list((tmp_path / "site").rglob("*")) == []


def test_a_good_wheel_is_unpacked_with_its_modes_and_nothing_else(tmp_path, monkeypatch):
    data = make_wheel()
    served = Served(monkeypatch, {URL: data})
    dest = run(tmp_path, monkeypatch, [entry(data)], served)
    assert (dest / NAME / "__init__.py").read_bytes() == b"VALUE = 1\n" and (dest / (NAME + ".libs") / "libx.so").read_bytes() == b"ELF"
    assert (dest / ("%s-%s.dist-info" % (NAME, VERSION)) / "RECORD").is_file() and served.asked == [URL]
    assert stat.S_IMODE((dest / NAME / "__init__.py").stat().st_mode) == 0o644 and stat.S_IMODE((dest / NAME).stat().st_mode) == 0o755


def test_only_the_wheels_of_the_machines_architecture_are_fetched(tmp_path, monkeypatch):
    amd, arm = make_wheel(), make_wheel({"%s/__init__.py" % NAME: b"VALUE = 2\n"})
    other = URL.replace("x86_64", "aarch64")
    served = Served(monkeypatch, {URL: amd, other: arm})
    dest = run(tmp_path, monkeypatch, [entry(amd), entry(arm, arch="arm64", url=other)], served, machine="aarch64")
    assert served.asked == [other] and (dest / NAME / "__init__.py").read_bytes() == b"VALUE = 2\n"


def test_a_machine_the_pin_does_not_hold_is_refused(tmp_path, monkeypatch, capsys):
    data = make_wheel()
    assert refused(tmp_path, monkeypatch, [entry(data)], Served(monkeypatch, {URL: data}), capsys, machine="riscv64") == "machine_not_pinned"
    assert nothing_written(tmp_path)


def test_a_size_that_differs_from_the_pin_is_refused_before_anything_is_written(tmp_path, monkeypatch, capsys):
    data = make_wheel()
    for size in (len(data) - 1, len(data) + 1):
        assert refused(tmp_path, monkeypatch, [entry(data, size=size)], Served(monkeypatch, {URL: data}), capsys) == "size_differs_from_pin"
        assert nothing_written(tmp_path)


def test_a_sha256_that_differs_from_the_pin_is_refused(tmp_path, monkeypatch, capsys):
    data = make_wheel()
    assert refused(tmp_path, monkeypatch, [entry(data, sha256="0" * 64)], Served(monkeypatch, {URL: data}), capsys) == "sha256_differs_from_pin"
    assert nothing_written(tmp_path)


def test_a_host_outside_the_pins_is_refused_and_nothing_is_asked_for(tmp_path, monkeypatch, capsys):
    data = make_wheel()
    for bad in ("https://evil.example/demo.whl", "http://files.pythonhosted.org/demo.whl", "https://user@files.pythonhosted.org/demo.whl", "https://files.pythonhosted.org.evil.example/d.whl"):
        served = Served(monkeypatch, {bad: data})
        reason = refused(tmp_path, monkeypatch, [entry(data, url=bad)], served, capsys)
        assert reason in ("url_not_allowed", "redirect_host_not_allowed") and served.asked == [], bad


def test_a_redirect_is_refused_unless_the_pin_names_its_host(tmp_path, monkeypatch, capsys):
    data = make_wheel()
    hop = "https://cdn.example/demo.whl"

    class Redirects(Served):
        def open_once(self, url):
            self.asked.append(url)
            return (None, hop) if url == URL else (io.BytesIO(data), None)
    served = Redirects(monkeypatch, {})
    assert refused(tmp_path, monkeypatch, [entry(data)], served, capsys) == "redirect_host_not_allowed"
    served = Redirects(monkeypatch, {})
    dest = run(tmp_path, monkeypatch, [entry(data)], served, redirects=("cdn.example",))
    assert served.asked == [URL, hop] and (dest / NAME / "__init__.py").is_file()


@pytest.mark.parametrize("name", ["%s/../evil.py" % NAME, "/abs/evil.py", "%s\\evil.py" % NAME, "other_pkg/__init__.py", "%s-9.9.9.data/scripts/x" % NAME])
def test_a_member_outside_the_wheels_own_folders_is_refused(tmp_path, monkeypatch, capsys, name):
    data = make_wheel(extra=[(name, b"x")])
    assert refused(tmp_path, monkeypatch, [entry(data)], Served(monkeypatch, {URL: data}), capsys) == "wheel_member_refused"
    assert nothing_written(tmp_path) and not (tmp_path / "evil.py").exists()


def test_a_link_member_is_refused(tmp_path, monkeypatch, capsys):
    data = make_wheel(link="%s/link.py" % NAME)
    assert refused(tmp_path, monkeypatch, [entry(data)], Served(monkeypatch, {URL: data}), capsys) == "wheel_member_refused"
    assert nothing_written(tmp_path)


def test_a_member_that_differs_from_the_records_hash_is_refused_before_anything_is_written(tmp_path, monkeypatch, capsys):
    files = {"%s/__init__.py" % NAME: b"VALUE = 1\n", "%s/data.bin" % NAME: b"\x00\x01\x02"}
    dist = "%s-%s.dist-info" % (NAME, VERSION)
    rows = [record_row("%s/__init__.py" % NAME, b"VALUE = 1\n"), record_row("%s/data.bin" % NAME, b"tampered"), record_row(dist + "/METADATA", b"Name: demo\n"), dist + "/RECORD,,"]
    data = make_wheel(files, record="\n".join(rows) + "\n")
    assert refused(tmp_path, monkeypatch, [entry(data)], Served(monkeypatch, {URL: data}), capsys) == "wheel_record_mismatch"
    assert nothing_written(tmp_path)


def test_a_member_that_the_record_does_not_list_is_refused(tmp_path, monkeypatch, capsys):
    data = make_wheel(extra=[("%s/unlisted.py" % NAME, b"x = 1\n")])
    assert refused(tmp_path, monkeypatch, [entry(data)], Served(monkeypatch, {URL: data}), capsys) == "wheel_record_mismatch"
    assert nothing_written(tmp_path)


def test_a_wheel_with_no_record_is_refused(tmp_path, monkeypatch, capsys):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("%s/__init__.py" % NAME, b"x")
    data = buf.getvalue()
    assert refused(tmp_path, monkeypatch, [entry(data)], Served(monkeypatch, {URL: data}), capsys) == "wheel_record_missing"
    assert nothing_written(tmp_path)


def test_an_unfilled_pin_is_refused(tmp_path, monkeypatch, capsys):
    data = make_wheel()
    for edit in ({"sha256": ""}, {"size": 0}, {"url": ""}, {"version": ""}, {"filename": ""}):
        assert refused(tmp_path, monkeypatch, [entry(data, **edit)], Served(monkeypatch, {URL: data}), capsys) == "pin_incomplete", edit


def test_the_committed_pin_has_both_architectures_for_every_name_and_is_not_filled_yet():
    committed = json.loads((K.RENDERER / "wheel-pin.json").read_text(encoding="utf-8"))
    names = {w["name"] for w in committed["wheels"]}
    assert names == {"opencv_python_headless", "numpy"}
    for name in names:
        assert sorted(w["arch"] for w in committed["wheels"] if w["name"] == name) == ["amd64", "arm64"]
    assert committed["download_hosts"] == ["files.pythonhosted.org"] and committed["redirect_hosts"] == []
    opencv = [w for w in committed["wheels"] if w["name"] == "opencv_python_headless"]
    assert {w["version"] for w in opencv} == {"4.14.0.94"} and {w["arch"]: w["size"] for w in opencv} == {"arm64": 35405458, "amd64": 57534165}
    assert {w["arch"]: w["sha256"] for w in opencv} == {"arm64": "29714d7716dbfddf9fec20ffb878765e94ccaecd7d3ebd6750877420296e2dc5",
                                                       "amd64": "5e02669eac0ba67b2a22d7245af1e8ee1a2ef1185ee526a063d8f0555224bd52"}
    # What the supervisor still has to read: when it is filled, `pin_missing` is false and every url is on the one host.
    if not W.pin_missing(committed):
        assert all(w["url"].startswith("https://files.pythonhosted.org/") and w["filename"] == w["url"].rsplit("/", 1)[1] and len(w["sha256"]) == 64 for w in committed["wheels"])


def test_build_refuses_while_the_wheel_pin_is_not_filled(tmp_path):
    import _docker as D
    from _browser import NotConfigured
    data = make_wheel()
    filled = tmp_path / "filled.json"
    filled.write_text(json.dumps(pin([entry(data)])), encoding="utf-8")
    D.require_wheels_pinned(str(filled))
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps(pin([entry(data, sha256="")])), encoding="utf-8")
    for path in (empty, tmp_path / "missing.json"):
        with pytest.raises(NotConfigured) as caught:
            D.require_wheels_pinned(str(path))
        assert (caught.value.code, caught.value.field) == ("pin_incomplete", "wheel-pin")
