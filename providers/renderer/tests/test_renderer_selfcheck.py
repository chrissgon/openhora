"""The image's selfcheck reads the vendor files, the registry files and the shims again and compares them with the pins (PF-a1): code `vendor_hash`
on a missing, extra or different file."""
from __future__ import annotations

import hashlib
import json
import shutil

import pytest

import renderer_kit as K
import _inner
from _text import Refusal

GOOD = {"gsap.min.js": b"gsap", "hyperframe.runtime.iife.js": b"runtime", "hyperframe.manifest.json": b"{}"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def world(tmp_path):
    """A fake image: an `hf-runtime` folder with pins for GOOD and one registry row, its shims copied, and the folders the build wrote."""
    here = tmp_path / "image"
    runtime = here / "hf-runtime"
    shutil.copytree(K.RENDERER / "hf-runtime" / "shims", runtime / "shims")
    pins = {"schema_version": 1, "packages": [
        {"name": "gsap", "files": {"package/dist/gsap.min.js": sha(GOOD["gsap.min.js"])}},
        {"name": "hyperframes", "files": {"package/dist/hyperframe.runtime.iife.js": sha(GOOD["hyperframe.runtime.iife.js"]), "package/dist/hyperframe.manifest.json": sha(GOOD["hyperframe.manifest.json"])}}]}
    (runtime / "npm-pins.json").write_text(json.dumps(pins), encoding="utf-8")
    (runtime / "registry.sha256").write_text("# commit %s\n%s  LICENSE\n" % ("a" * 40, sha(b"licence")), encoding="utf-8")
    vendor, registry = tmp_path / "vendor", tmp_path / "registry"
    vendor.mkdir()
    registry.mkdir()
    for name, data in GOOD.items():
        (vendor / name).write_bytes(data)
    (registry / "LICENSE").write_bytes(b"licence")
    return here, vendor, registry


def code_of(*args):
    with pytest.raises(Refusal) as exc:
        _inner.check_hf_runtime(*map(str, args))
    assert exc.value.code == "vendor_hash"
    return exc.value.field


def test_a_good_image_passes_and_counts_what_it_checked(tmp_path):
    here, vendor, registry = world(tmp_path)
    assert _inner.check_hf_runtime(str(here), str(vendor), str(registry)) == {"vendor": 3, "registry": 1, "shims": 5}


def test_a_different_vendor_file_is_vendor_hash(tmp_path):
    here, vendor, registry = world(tmp_path)
    (vendor / "gsap.min.js").write_bytes(b"gsap!")
    assert code_of(here, vendor, registry) == "vendor/gsap.min.js"


def test_a_missing_vendor_file_and_an_extra_one_are_vendor_hash(tmp_path):
    here, vendor, registry = world(tmp_path)
    (vendor / "hyperframe.manifest.json").unlink()
    assert code_of(here, vendor, registry) == "vendor/hyperframe.manifest.json"
    (vendor / "hyperframe.manifest.json").write_bytes(b"{}")
    (vendor / "extra.js").write_bytes(b"x")
    assert code_of(here, vendor, registry) == "vendor/extra.js"


def test_a_different_registry_file_is_vendor_hash(tmp_path):
    here, vendor, registry = world(tmp_path)
    (registry / "LICENSE").write_bytes(b"other")
    assert code_of(here, vendor, registry) == "hf-registry/LICENSE"


def test_a_changed_shim_is_vendor_hash(tmp_path):
    here, vendor, registry = world(tmp_path)
    (here / "hf-runtime" / "shims" / "bridge.js").write_bytes(b"changed")
    assert code_of(here, vendor, registry) == "shims/bridge.js"


def test_the_committed_files_describe_the_real_shims_and_pins():
    """The same check, against the repository's own pins, with the vendor files not present: it names the first one missing, never passes."""
    with pytest.raises(Refusal) as exc:
        _inner.check_hf_runtime(str(K.RENDERER), "/nonexistent/vendor", "/nonexistent/reg")
    assert exc.value.code == "vendor_hash"


# ---------------------------------------------------------------- the scanner's tools (P9-a1)

import sys
import types

import _scan
from _inner import NotConfigured

LANGS = "List of available languages in \"/usr/share/tesseract-ocr/5/tessdata/\" (4):\neng\nosd\npor\nspa\n"


def fake_tesseract(monkeypatch, langs=LANGS, version="tesseract 5.3.0\n leptonica-1.82.0\n"):
    def run(args, data=b""):
        if args == ["--version"]:
            return version
        if args == ["--list-langs"]:
            return langs
        raise AssertionError(args)
    monkeypatch.setattr(_scan, "tesseract_run", run)


def fake_modules(monkeypatch, cv2="4.14.0", numpy="2.3.1"):
    for name, version in (("cv2", cv2), ("numpy", numpy)):
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**{"__version__": version}) if version else None)


def test_the_scan_tools_report_their_versions_and_the_three_languages(monkeypatch):
    fake_tesseract(monkeypatch)
    fake_modules(monkeypatch)
    assert _inner.scan_tools("eng+por+spa") == {"tesseract": "5.3.0", "tessdata": ["eng", "osd", "por", "spa"], "opencv": "4.14.0", "numpy": "2.3.1"}


@pytest.mark.parametrize("what,edit,field", [
    ("a language", lambda m: fake_tesseract(m, langs=LANGS.replace("spa\n", "")), "scan:tessdata"),
    ("tesseract itself", lambda m: m.setattr(_scan, "tesseract_run", lambda args, data=b"": (_ for _ in ()).throw(Refusal("tool_failed", "tesseract"))), "scan:tesseract"),
    ("opencv", lambda m: fake_modules(m, cv2=None), "scan:opencv"),
    ("numpy", lambda m: fake_modules(m, numpy=None), "scan:numpy"),
])
def test_a_missing_tool_language_or_module_is_not_ready(monkeypatch, what, edit, field):
    fake_tesseract(monkeypatch)
    fake_modules(monkeypatch)
    edit(monkeypatch)
    with pytest.raises(NotConfigured) as caught:
        _inner.scan_tools("eng+por+spa")
    assert (caught.value.code, caught.value.field) == ("not_ready", field), what


def selfcheck_world(monkeypatch, container):
    import _cdp
    import _media
    monkeypatch.setattr(_inner, "tools", lambda args: ("ffmpeg", "ffprobe"))
    monkeypatch.setattr(_media, "run", lambda argv, timeout: (" libx264 aac png ", ""))
    monkeypatch.setattr(_media, "has_filter", lambda ffmpeg, name: True)
    monkeypatch.setattr(_media, "tool_version", lambda path: "fake 1")
    monkeypatch.setattr(_inner, "_browser_version", lambda path: "Chrome fake")
    monkeypatch.setattr(_inner, "browser_path", lambda args: "/browser")
    monkeypatch.setattr(_inner, "check_hf_runtime", lambda *a: {"vendor": 3, "registry": 1, "shims": 5})
    monkeypatch.setattr(_cdp, "container_mode", lambda: container)
    monkeypatch.setattr(_inner, "scan_tools", lambda lang: {"tesseract": "5.3.0", "tessdata": ["eng", "por", "spa"], "opencv": "4.14.0", "numpy": "2.3.1"})
    return types.SimpleNamespace(ffmpeg=None, ffprobe=None, browser=None, vendor=None, hf_registry=None, scan=False)


def test_outside_the_container_the_scan_keys_are_absent_unless_asked(monkeypatch):
    args = selfcheck_world(monkeypatch, container=False)
    out = _inner.verb_selfcheck(args)
    assert not {"tesseract", "tessdata", "opencv", "numpy"} & set(out)
    args.scan = True
    assert {"tesseract", "tessdata", "opencv", "numpy"} <= set(_inner.verb_selfcheck(args))


def test_inside_the_container_the_scan_keys_are_always_there_and_pass_the_hosts_schema(monkeypatch):
    out = _inner.verb_selfcheck(selfcheck_world(monkeypatch, container=True))
    assert out["tesseract"] == "5.3.0" and out["tessdata"] == ["eng", "por", "spa"] and out["opencv"] == "4.14.0" and out["numpy"] == "2.3.1"
    import _docker as D
    clean = D.sanitise(out, D.RESULT_SCHEMAS["selfcheck"])
    assert clean["tessdata"] == ["eng", "por", "spa"] and clean["numpy"] == "2.3.1"


def test_the_languages_the_image_must_hold_are_english_portuguese_and_spanish():
    assert _scan.DEFAULT_LANG == "eng+por+spa"
    import _host
    assert _host.SCAN_LANG == _scan.DEFAULT_LANG
