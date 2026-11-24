"""The pins of the HyperFrames runtime and GSAP baked into the common image (D19, PF-a1): the npm pins equal the lockfile's, every hash is
whole, the registry manifest holds the commit and the LICENSE, and the shims are the committed bytes."""
from __future__ import annotations

import hashlib
import json
import re

import renderer_kit as K

RUNTIME = K.RENDERER / "hf-runtime"
HEX64 = re.compile(r"[0-9a-f]{64}")
LICENSE_SHA = "4259155fb06f127687ee7b0a8a3682d45132db0f2da26cbc0b7a2d1e796436b8"


def pins():
    return json.loads((RUNTIME / "npm-pins.json").read_text(encoding="utf-8"))


def test_the_url_and_integrity_of_each_package_are_the_lockfiles_entries():
    lock = json.loads((K.RENDERER / "hyperframes-image" / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    assert pins()["schema_version"] == 1
    assert [p["name"] for p in pins()["packages"]] == ["gsap", "hyperframes"]
    for pkg in pins()["packages"]:
        entry = lock["node_modules/" + pkg["name"]]
        assert pkg["url"] == entry["resolved"] and pkg["integrity"] == entry["integrity"] and pkg["version"] == entry["version"], pkg["name"]


def test_every_member_hash_is_a_whole_sha256_and_no_placeholder_is_left():
    members = {}
    for pkg in pins()["packages"]:
        members.update(pkg["files"])
    assert sorted(members) == ["package/dist/gsap.min.js", "package/dist/hyperframe.manifest.json", "package/dist/hyperframe.runtime.iife.js"]
    assert all(HEX64.fullmatch(v) for v in members.values())
    assert members["package/dist/hyperframe.runtime.iife.js"] == "ee05fb04973a2db6157f4a048ec66ce118cb7b2ca6e9e279295726b985ddb79d"
    text = (RUNTIME / "npm-pins.json").read_text(encoding="utf-8")
    assert not re.search(r"TODO|TBD|placeholder|xxxx|\.\.\.", text, re.I)


def test_the_registry_manifest_names_the_commit_and_the_license_row():
    lines = (RUNTIME / "registry.sha256").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# commit b4cc674f7f312e77ded32e0b53006cc0bad6723b"
    rows = [line for line in lines if line.strip() and not line.startswith("#")]
    assert rows == ["%s  LICENSE" % LICENSE_SHA]
    assert LICENSE_SHA == hashlib.sha256((K.RENDERER / "hyperframes-image" / "LICENSE-registry-Apache-2.0.txt").read_bytes()).hexdigest()


def test_the_dockerfile_fetches_before_it_copies_the_renderer():
    text = (K.RENDERER / "Dockerfile").read_text(encoding="utf-8")
    fetch, copy_all = text.index("fetch_hf.py --out /opt/renderer/vendor"), text.index("COPY . /opt/renderer/")
    assert fetch < copy_all < text.index("_inner.py --result /opt/renderer/versions.json selfcheck")
    assert text.count("fetch_hf.py --out") == 1 and "--registry-out /opt/renderer/hf-registry" in text
