"""Fetch one pinned static ffmpeg archive (BtbN builds, the one HyperFrames' own Dockerfile.render pins), check its size and sha256, and
unpack only bin/ffmpeg and bin/ffprobe. Build time only. Usage: python3 -I fetch_ffmpeg.py <url> <sha256> <dest-dir>
"""
import hashlib
import io
import os
import sys
import tarfile
import urllib.request

url, want, dest = sys.argv[1], sys.argv[2], sys.argv[3]
if not url.startswith("https://github.com/BtbN/FFmpeg-Builds/releases/download/"):
    sys.exit("refused: not a BtbN release url")
with urllib.request.urlopen(url, timeout=300) as r:
    body = r.read(400 * 1024 * 1024)
got = hashlib.sha256(body).hexdigest()
if got != want:
    sys.exit("refused: sha256 pinned %s, got %s (%d bytes)" % (want, got, len(body)))
os.makedirs(dest, exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(body), mode="r:xz") as t:
    for m in t.getmembers():
        if m.isfile() and m.name.split("/")[-2:] in (["bin", "ffmpeg"], ["bin", "ffprobe"]):
            f = t.extractfile(m)
            out = os.path.join(dest, os.path.basename(m.name))
            with open(out, "wb") as fh:
                fh.write(f.read())
            os.chmod(out, 0o755)
print("ffmpeg ok", len(body), "bytes", got)
