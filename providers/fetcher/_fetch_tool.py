"""Download the pinned tool file. Run by the image's build (providers/fetcher/Dockerfile) as
`python3 -I _fetch_tool.py <url> <size> <sha256> <redirect-hosts> <destination>`; also run by the tests against a loopback server.

The file is read once; its size and sha256 must equal the pin. Only https is accepted (a test may set FETCHER_TEST=1 to use a loopback
http server). Exactly one redirect is followed, only to https on a host of <redirect-hosts> (a comma-separated list of exact names);
a second redirect, or a redirect to any other host or scheme, is refused. The file is written mode 0555. Unlike the renderer's
browser download, which refuses every redirect, a release download of this tool redirects once to the host of its storage.
Exit 0 done, 1 refused (the reason is on stderr), 2 usage. Standard library only.
"""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REDIRECTS = (301, 302, 303, 307, 308)
MAX_URL = 2048


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def refuse(why: str):
    print("refused: %s" % why, file=sys.stderr)
    raise SystemExit(1)


def loopback_test(parts) -> bool:
    return os.environ.get("FETCHER_TEST") == "1" and parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")


def check_url(url: str, hosts=None) -> urllib.parse.SplitResult:
    """The parts of an https url with no user info; with `hosts`, its host must be one of them (lowercased, exact)."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL or any(ord(c) < 33 or ord(c) > 126 for c in url):
        refuse("url_not_allowed")
    parts = urllib.parse.urlsplit(url)
    if not (parts.scheme == "https" or loopback_test(parts)) or not parts.hostname or "@" in parts.netloc:
        refuse("url_not_allowed")
    if hosts is not None and parts.hostname.lower() not in hosts:
        refuse("redirect_host_not_allowed")
    return parts


def open_once(url: str):
    """(response, None) or (None, the Location of a redirect). Any other HTTP status is a refusal."""
    try:
        return urllib.request.build_opener(NoRedirect).open(url, timeout=120), None
    except urllib.error.HTTPError as e:
        if e.code in REDIRECTS and e.headers.get("Location"):
            return None, urllib.parse.urljoin(url, e.headers["Location"])
        refuse("download_failed")
    except (OSError, ValueError):
        refuse("download_failed")


def fetch(url: str, size: int, sha256: str, redirect_hosts, dest: str) -> None:
    if not (sha256 and size and redirect_hosts):
        refuse("pin_incomplete")
    check_url(url)
    hosts = {h.lower() for h in redirect_hosts}
    resp, location = open_once(url)
    if location is not None:
        check_url(location, hosts)
        resp, again = open_once(location)
        if again is not None:
            refuse("second_redirect")
    digest, total = hashlib.sha256(), 0
    tmp = dest + ".part"
    try:
        with resp, open(tmp, "wb") as out:
            for block in iter(lambda: resp.read(1 << 20), b""):
                total += len(block)
                if total > size:
                    refuse("size_differs_from_pin")
                digest.update(block)
                out.write(block)
        if total != size:
            refuse("size_differs_from_pin")
        if digest.hexdigest() != sha256:
            refuse("sha256_differs_from_pin")
        os.chmod(tmp, 0o555)
        os.replace(tmp, dest)
    except (OSError, ValueError):
        refuse("download_failed")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv) -> int:
    if len(argv) != 6 or not argv[2].isdigit():
        print("usage: _fetch_tool.py <url> <size> <sha256> <redirect-hosts> <destination>", file=sys.stderr)
        return 2
    hosts = [h for h in argv[4].split(",") if h]
    fetch(argv[1], int(argv[2]), argv[3], hosts, argv[5])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
