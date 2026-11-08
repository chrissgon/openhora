#!/usr/bin/env python3
"""Fetch the registry files listed in a manifest from the pinned commit and refuse any whose sha256 differs. Build time only.

    python3 -I fetch_registry.py <manifest> <dest>

Manifest lines: `<sha256>  <path inside the repository>`; a line `# commit <40 hex>` names the commit; other `#` lines are comments. Each
file is read up to 256 KiB (a longer one is refused), checked against its sha256 before anything is written, and written under
<dest>/<path> with mode 0444. A path that is not a plain relative path of the repository (no `..`, no leading slash, no odd character) is
refused. The one network use of this file is the raw-file URL below, at the pinned commit; the Dockerfile runs it at build time and
nothing in the image runs it again. Standard library only.
"""
import argparse
import hashlib
import os
import re
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/heygen-com/hyperframes/%s/%s"
CAP = 256 * 1024
PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}(/[A-Za-z0-9][A-Za-z0-9._-]{0,60}){0,5}")
HEX64, HEX40 = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{40}")


def read_manifest(path):
    commit, rows = None, []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("# commit "):
                commit = line.split()[2]
            elif line and not line.startswith("#"):
                parts = line.split(None, 1)
                if len(parts) != 2:
                    sys.exit("bad manifest line: %s" % line[:60])
                rows.append((parts[0], parts[1].strip()))
    if not commit or not HEX40.fullmatch(commit):
        sys.exit("registry.sha256 has no '# commit <40 hex>' line")
    seen = set()
    for digest, name in rows:
        if not HEX64.fullmatch(digest) or not PATH.fullmatch(name):
            sys.exit("bad manifest line: %s" % name[:60])
        if name in seen:
            sys.exit("duplicate path in the manifest: %s" % name[:60])
        seen.add(name)
    return commit, rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("manifest", help="registry.sha256")
    p.add_argument("dest", help="the folder the files are written under")
    args = p.parse_args(argv)
    commit, rows = read_manifest(args.manifest)
    for digest, name in rows:
        with urllib.request.urlopen(URL % (commit, name), timeout=60) as response:
            body = response.read(CAP + 1)
        if len(body) > CAP:
            sys.exit("%s is over %d bytes" % (name, CAP))
        got = hashlib.sha256(body).hexdigest()
        if got != digest:
            sys.exit("hash mismatch for %s: pinned %s, got %s" % (name, digest, got))
        out = os.path.join(args.dest, name)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(body)
        os.chmod(out, 0o444)
    print("fetched", len(rows), "files from", commit)


if __name__ == "__main__":
    main()
