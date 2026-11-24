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
