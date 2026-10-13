"""The browser the renderer's image holds: Chrome for Testing's headless shell, pinned by version and archive sha256.

browser-pin.json names the version and, for each architecture the image can be built for, the archive's URL, its size and md5
(both published by the official storage bucket's object metadata) and its sha256. Chrome for Testing publishes no sha256, so
the sha256 is computed once, at the maintainer's word, by `pin-browser --confirmed` (it downloads the archive, checks size and
md5 against the published values, and writes the sha256 into the pin file). The image's build then downloads the archive
itself and refuses one whose size, md5 or sha256 differs from the pin: a later build whose archive changed under the same
version fails. Nothing here runs unless a person starts a verb. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request

from _text import Refusal
from _vocab import HERE, read_json

PIN_FILE = os.path.join(HERE, "browser-pin.json")
ARCHITECTURES = {"aarch64": "linux-arm64", "arm64": "linux-arm64", "x86_64": "linux64", "amd64": "linux64"}


class NotConfigured(Refusal):
    """Something the person has to do first (exit 3): the pin has no sha256 yet, docker is not there."""


def load_pin(path=None) -> dict:
    pin = read_json(path or PIN_FILE)
    try:
        assert pin["version"] and pin["product"] == "chrome-headless-shell" and isinstance(pin["platforms"], dict)
        for spec in pin["platforms"].values():
            assert spec["url"].startswith(("https://", "http://127.0.0.1", "http://localhost")) and isinstance(spec["size"], int) and len(spec["md5"]) == 32
    except (AssertionError, KeyError, TypeError, AttributeError):
        raise Refusal("bad_pin", "browser-pin.json") from None
    return pin


def platform_for(architecture: str) -> str:
    """The pin's platform name for a docker daemon's architecture (`docker info --format {{.Architecture}}`)."""
    try:
        return ARCHITECTURES[architecture.strip().lower()]
    except KeyError:
        raise NotConfigured("architecture_not_pinned", architecture.strip()[:20]) from None


def spec_for(pin: dict, platform: str) -> dict:
    spec = pin["platforms"].get(platform)
    if spec is None:
        raise NotConfigured("platform_not_pinned", platform)
    return spec


def require_sha256(pin: dict, platform: str) -> dict:
    spec = spec_for(pin, platform)
    if not spec.get("sha256"):
        raise NotConfigured("pin_incomplete", platform)
    return spec


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def url_allowed(url: str, test_mode: bool) -> bool:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return True
    return test_mode and parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1")


def pin_browser(platform: str, pin_path=None, test_mode=False, dry_run=False) -> dict:
    """Download the archive of `platform` once, check its size and md5 against the pin, and record its sha256 in the pin
    file. An archive that does not match the published size and md5 is refused and nothing is written; a pin that already
    has a sha256 is compared with the archive's and a difference is refused (the archive changed under the same version)."""
    path = pin_path or PIN_FILE
    pin = load_pin(path)
    spec = spec_for(pin, platform)
    plan = {"platform": platform, "version": pin["version"], "url": spec["url"], "size": spec["size"], "md5": spec["md5"],
            "sha256": spec.get("sha256"), "max_bytes": pin["max_archive_bytes"]}
    if dry_run:
        return dict(plan, dry_run=True)
    if not url_allowed(spec["url"], test_mode):
        raise Refusal("url_not_allowed", "pin")
    sha, md5, total = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0   # md5 only cross-checks the bucket's own metadata
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(spec["url"], headers={"User-Agent": "openhora-renderer"}), timeout=60) as resp:
            for block in iter(lambda: resp.read(1 << 20), b""):
                total += len(block)
                if total > pin["max_archive_bytes"]:
                    raise Refusal("archive_too_large", "download")
                sha.update(block)
                md5.update(block)
    except Refusal:
        raise
    except (OSError, ValueError):
        raise Refusal("download_failed", "download") from None
    if total != spec["size"] or md5.hexdigest() != spec["md5"]:
        raise Refusal("archive_differs_from_published", "download")
    digest = sha.hexdigest()
    if spec.get("sha256") and spec["sha256"] != digest:
        raise Refusal("sha256_changed", "download")
    if not spec.get("sha256"):
        doc = read_json(path)
        doc["platforms"][platform]["sha256"] = digest
        fd, tmp = tempfile.mkstemp(prefix=".pin-", dir=os.path.dirname(os.path.abspath(path)))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1)
            fh.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    return dict(plan, dry_run=False, sha256=digest, recorded=not spec.get("sha256"))
