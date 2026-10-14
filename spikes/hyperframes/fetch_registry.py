"""Fetch the registry files listed in a manifest from the pinned commit and refuse any whose sha256 differs. Build time only.

Manifest lines: `<sha256>  <path inside the repository>`; a line `# commit <sha>` names the commit. Files go under <dest>/<path>.
"""
import hashlib
import os
import sys
import urllib.request

manifest, dest = sys.argv[1], sys.argv[2]
commit, rows = None, []
for line in open(manifest, encoding="utf-8"):
    line = line.strip()
    if line.startswith("# commit "):
        commit = line.split()[2]
    elif line and not line.startswith("#"):
        digest, path = line.split(None, 1)
        rows.append((digest, path.strip()))
if not commit or len(commit) != 40:
    sys.exit("registry.sha256 has no '# commit <40 hex>' line")
for digest, path in rows:
    url = "https://raw.githubusercontent.com/heygen-com/hyperframes/%s/%s" % (commit, path)
    with urllib.request.urlopen(url, timeout=60) as r:
        body = r.read()
    got = hashlib.sha256(body).hexdigest()
    if got != digest:
        sys.exit("hash mismatch for %s: pinned %s, got %s" % (path, digest, got))
    out = os.path.join(dest, path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as f:
        f.write(body)
print("fetched", len(rows), "files from", commit)
