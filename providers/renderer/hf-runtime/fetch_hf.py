#!/usr/bin/env python3
"""Fetch the HyperFrames runtime and GSAP, and the registry files the image carries, from their pinned sources. Build time only.

    python3 -I fetch_hf.py --out <vendor folder> --registry-out <registry folder> [--pins npm-pins.json] [--registry registry.sha256]

`npm-pins.json` names two npm tarballs (gsap and hyperframes) by url and sha512 integrity, and for each the members to extract with their
sha256. Each tarball is read up to 64 MiB within 60 seconds and its integrity is checked before it is opened; it is opened in memory and
only the named members are read (a link, an absolute path, a `..`, or a member over 8 MiB is refused); each member's sha256 is checked and
the file is written, under its base name, to --out with mode 0444. `registry.sha256` (`# commit <40 hex>`, then `<sha256>  <path>` rows)
names files of the HyperFrames registry repository: each is fetched from the raw-file URL at that commit, up to 256 KiB, checked, and
written under --registry-out/<path> with mode 0444. Nothing is written until every file has passed: the files are written to a temporary
folder beside each destination and renamed at the end. Any mismatch prints one line on stderr and exits 2, leaving no output folder.
The Dockerfile runs this once at build time; nothing in the image runs it again. Standard library only. Data goes to stdout, diagnostics
to stderr.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TARBALL_URL = re.compile(r"^https://registry\.npmjs\.org/(gsap|hyperframes)/-/[a-z]+-[0-9.]+\.tgz$")
RAW_URL = "https://raw.githubusercontent.com/heygen-com/hyperframes/%s/%s"
TARBALL_CAP, MEMBER_CAP, REGISTRY_CAP, TIMEOUT = 64 * 1024 * 1024, 8 * 1024 * 1024, 256 * 1024, 60
PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}(/[A-Za-z0-9][A-Za-z0-9._-]{0,60}){0,5}")
HEX64, HEX40 = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{40}")
INTEGRITY = re.compile(r"sha512-[A-Za-z0-9+/]{86}==")


class Mismatch(Exception):
    pass


def opener(url):
    """The one network use besides the raw-file one: a GET of `url`. Tests replace it."""
    return urllib.request.urlopen(url, timeout=TIMEOUT)


def read_capped(url, cap):
    with opener(url) as response:
        body = response.read(cap + 1)
    if len(body) > cap:
        raise Mismatch("%s is over %d bytes" % (url[:80], cap))
    return body


def load_pins(path):
    with open(path, encoding="utf-8") as fh:
        pins = json.load(fh)
    if pins.get("schema_version") != 1 or not isinstance(pins.get("packages"), list) or not pins["packages"]:
        raise Mismatch("npm-pins.json: schema_version 1 and a list of packages are required")
    for pkg in pins["packages"]:
        if not TARBALL_URL.match(str(pkg.get("url", ""))):
            raise Mismatch("npm-pins.json: url outside the pattern: %s" % str(pkg.get("url"))[:80])
        if not INTEGRITY.fullmatch(str(pkg.get("integrity", ""))):
            raise Mismatch("npm-pins.json: bad integrity for %s" % str(pkg.get("name"))[:40])
        files = pkg.get("files")
        if not isinstance(files, dict) or not files:
            raise Mismatch("npm-pins.json: no files for %s" % str(pkg.get("name"))[:40])
        for member, digest in files.items():
            if not HEX64.fullmatch(str(digest)):
                raise Mismatch("npm-pins.json: bad sha256 for %s" % member[:60])
    return pins


def members_of(pkg, body):
    """{base name: bytes} of the pinned members of one tarball, every check made before anything is returned."""
    sri = "sha512-" + base64.b64encode(hashlib.sha512(body).digest()).decode()
    if sri != pkg["integrity"]:
        raise Mismatch("integrity mismatch for %s" % pkg["name"])
    out = {}
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
        for info in tar.getmembers():
            name = info.name
            if info.issym() or info.islnk() or name.startswith("/") or ".." in name.split("/"):
                raise Mismatch("%s: refused member %s" % (pkg["name"], name[:60]))
        for name, digest in pkg["files"].items():
            try:
                info = tar.getmember(name)
            except KeyError:
                raise Mismatch("%s: member %s not found" % (pkg["name"], name)) from None
            if not info.isfile() or info.size > MEMBER_CAP:
                raise Mismatch("%s: member %s is not a plain file under %d bytes" % (pkg["name"], name, MEMBER_CAP))
            data = tar.extractfile(info).read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise Mismatch("hash mismatch for %s" % name)
            base = os.path.basename(name)
            if base in out:
                raise Mismatch("two members named %s" % base)
            out[base] = data
    return out


def read_registry(path):
    commit, rows = None, []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("# commit "):
                commit = line.split()[2]
            elif line and not line.startswith("#"):
                parts = line.split(None, 1)
                if len(parts) != 2:
                    raise Mismatch("bad registry line: %s" % line[:60])
                rows.append((parts[0], parts[1].strip()))
    if not commit or not HEX40.fullmatch(commit):
        raise Mismatch("registry.sha256 has no '# commit <40 hex>' line")
    seen = set()
    for digest, name in rows:
        if not HEX64.fullmatch(digest) or not PATH.fullmatch(name) or name in seen:
            raise Mismatch("bad or duplicate registry line: %s" % name[:60])
        seen.add(name)
    return commit, rows


def write_tree(root, files):
    """Write {relative path: bytes} under a fresh `root` mode 0444, through a temporary sibling renamed at the end."""
    tmp = root + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        for rel, data in files.items():
            dest = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(data)
            os.chmod(dest, 0o444)
        if os.path.isdir(root):
            raise Mismatch("%s already exists" % root)
        os.makedirs(os.path.dirname(os.path.abspath(root)), exist_ok=True)
        os.rename(tmp, root)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def run(pins_path, registry_path, out, registry_out):
    vendor, registry = {}, {}
    for pkg in load_pins(pins_path)["packages"]:
        vendor.update(members_of(pkg, read_capped(pkg["url"], TARBALL_CAP)))
    commit, rows = read_registry(registry_path)
    for digest, name in rows:
        body = read_capped(RAW_URL % (commit, name), REGISTRY_CAP)
        if hashlib.sha256(body).hexdigest() != digest:
            raise Mismatch("hash mismatch for %s" % name)
        registry[name] = body
    write_tree(out, vendor)
    try:
        write_tree(registry_out, registry)
    except BaseException:
        for dirpath, _, names in os.walk(out):
            for n in names:
                os.chmod(os.path.join(dirpath, n), 0o644)
        shutil.rmtree(out, ignore_errors=True)
        raise
    return sorted(vendor), sorted(registry)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True, help="the folder the vendor files are written to (it must not exist)")
    p.add_argument("--registry-out", required=True, help="the folder the registry files are written under (it must not exist)")
    p.add_argument("--pins", default=os.path.join(HERE, "npm-pins.json"))
    p.add_argument("--registry", default=os.path.join(HERE, "registry.sha256"))
    args = p.parse_args(argv)
    try:
        vendor, registry = run(args.pins, args.registry, args.out, args.registry_out)
    except (Mismatch, tarfile.TarError, OSError, ValueError) as exc:
        print("fetch_hf: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps({"vendor": vendor, "registry": registry}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
