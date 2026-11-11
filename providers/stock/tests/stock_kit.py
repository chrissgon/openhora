"""The test kit of providers/stock/: a synthetic source file on `.example` hosts, generated media, a fake network and a fake secret resolver.
Nothing here touches a network, a real library, a real key or a real item: every id, name and host is made up."""
from __future__ import annotations

import copy
import json
import os
import struct
import sys
import zlib
from pathlib import Path

STOCK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STOCK))
import _net  # noqa: E402
import _stock  # noqa: E402

PUBLIC = "93.184.216.34"          # a global address (the example domain's)
KEY = "k-planted-7f3a91c2d4e85b60"     # a made-up key; every test that matters scans for it
TODAY = "2026-11-10"
API, IMG, VID, CDN = "api.stock.example", "img.stock.example", "vid.stock.example", "cdn.stock.example"


def png(width=4, height=4, colour=(40, 90, 160)):
    """A flat-colour PNG made with zlib."""
    row = b"\x00" + bytes(colour) * width

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def jpeg(size=200):
    """Bytes that begin as a JPEG does; nothing in the stock provider decodes them."""
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + bytes(range(256)) * (size // 256 + 1) + b"\xff\xd9"


def mp4(size=4096):
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x01" * size


def source(**over):
    """A filled synthetic source file (a `library` source on `.example` hosts); `over` replaces top-level keys, a dict value merges one level."""
    data = {
        "source": "pexels", "licence_tier": "library", "licence": "pexels-license", "licences": None,
        "licence_url": "https://licence.stock.example/terms", "terms_read_on": TODAY, "secret": "STOCK_PEXELS_API_KEY", "secret_in": "header",
        "api": {"host": API, "search_image": "/v1/search", "search_clip": "/v1/videos/search", "item_image": "/v1/photos/{item}",
                "item_clip": "/v1/videos/videos/{item}"},
        "media_hosts": [IMG, VID], "redirect_hosts": [CDN],
        "path_patterns": {"preview": r"/p/[0-9]+/medium\.jpg", "image": r"/p/[0-9]+/original\.jpg", "clip": r"/c/[0-9]+/[a-z0-9_]+\.mp4"},
        "rendition": {"preview": "medium", "image": "original", "clip": "video/mp4"},
        "cache_seconds": 0, "credit_line": None, "kinds": ["image", "clip"]}
    for key, value in over.items():
        data[key] = value
    return data


def write_source(folder, data=None, name="pexels.json") -> str:
    path = Path(folder) / name
    path.write_text(json.dumps(source() if data is None else data), encoding="utf-8")
    return str(path)


def photo(item=1001, width=2400, height=3200, author="Aster Lane"):
    return {"id": item, "width": width, "height": height, "url": "https://page.stock.example/photo/%s" % item, "photographer": author,
            "alt": "ignored text", "src": {"medium": "https://%s/p/%s/medium.jpg" % (IMG, item), "original": "https://%s/p/%s/original.jpg" % (IMG, item)}}


def video(item=2001, duration=12, author="Bram Hollow", files=None):
    files = files if files is not None else [
        {"file_type": "video/mp4", "width": 640, "height": 1136, "link": "https://%s/c/%s/small_%s.mp4" % (VID, item, item)},
        {"file_type": "video/mp4", "width": 2160, "height": 3840, "link": "https://%s/c/%s/large_%s.mp4" % (VID, item, item)},
        {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://%s/c/%s/hd_%s.mp4" % (VID, item, item)}]
    return {"id": item, "width": 2160, "height": 3840, "duration": duration, "url": "https://page.stock.example/video/%s" % item,
            "image": "https://%s/p/%s/medium.jpg" % (IMG, item), "user": {"name": author}, "video_files": files}


class Response:
    def __init__(self, status=200, body=b"", headers=None, length=True):
        self.status, self.body, self._pos = status, body, 0
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        if length and "content-length" not in self.headers and status == 200:
            self.headers["content-length"] = str(len(body))

    def getheader(self, name, default=None):
        return self.headers.get(name.lower(), default)

    def read(self, amount=None):
        end = len(self.body) if amount is None else self._pos + amount
        block = self.body[self._pos:end]
        self._pos += len(block)
        return block


def json_response(obj, **kw):
    body = json.dumps(obj).encode("utf-8")
    return Response(200, body, {"Content-Type": "application/json"}, **kw)


def image_response(body=None, kind="image/jpeg", **kw):
    return Response(200, jpeg() if body is None else body, {"Content-Type": kind}, **kw)


def clip_response(body=None, **kw):
    return Response(200, mp4() if body is None else body, {"Content-Type": "video/mp4"}, **kw)


class FakeNet:
    """A fake network: `routes` maps (host, path) to a Response, a list of Responses (served in turn) or a function (target, headers) -> Response.
    `requests` records every request: host, address, target and headers."""

    def __init__(self):
        self.routes, self.requests, self.resolved = {}, [], []
        self.address = PUBLIC

    def add(self, host, path, response):
        self.routes[(host, path)] = response
        return self

    def resolve(self, host, port, type=None):
        self.resolved.append(host)
        return [(2, 1, 6, "", (self.address, port))]

    def opener(self, host, address, timeout):
        return Conn(self, host, address)

    def install(self, monkeypatch):
        monkeypatch.setitem(_net.SEAMS, "resolve", self.resolve)
        monkeypatch.setitem(_net.SEAMS, "opener", self.opener)
        return self

    def api_requests(self):
        return [r for r in self.requests if r["host"] == API]

    def count(self, host=None):
        return len([r for r in self.requests if host in (None, r["host"])])


class Conn:
    def __init__(self, net, host, address):
        self.net, self.host, self.address, self.target, self.headers = net, host, address, None, None

    def request(self, method, target, headers=None):
        assert method == "GET"
        self.target, self.headers = target, dict(headers or {})
        self.net.requests.append({"host": self.host, "address": self.address, "target": target, "headers": dict(headers or {})})

    def getresponse(self):
        path = self.target.split("?", 1)[0]
        route = self.net.routes.get((self.host, path))
        if route is None:
            return Response(404, b"", {})
        if callable(route):
            return route(self.target, self.headers)
        if isinstance(route, list):
            route = route.pop(0) if len(route) > 1 else route[0]
        fresh = copy.copy(route)          # a response is read once: every request gets its own
        fresh._pos = 0
        return fresh

    def close(self):
        pass


class FakeResolver:
    """A stand-in for providers/secrets/resolver.py: `resolve(name)` gives (value, where) or None; a name not in `known` is not registered."""

    def __init__(self, values=None, known=None):
        self.values, self.known, self.asked = values if values is not None else {"STOCK_PEXELS_API_KEY": KEY}, known, []

    def resolve(self, name, **_):
        self.asked.append(name)
        if self.known is not None and name not in self.known:
            raise KeyError(name)
        value = self.values.get(name)
        return (value, "environment (%s)" % name) if value else None


def out_dir(tmp_path, name="out"):
    path = Path(tmp_path) / name
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)
    return str(path)


class Run:
    """One verb run through `_stock.run` with a fake network, a fake resolver and a state folder of its own."""

    def __init__(self, tmp_path, monkeypatch, data=None, impl=None, resolver=None):
        import io
        import pexels
        self.impl, self.tmp, self.io = impl or pexels, Path(tmp_path), io
        self.net = FakeNet().install(monkeypatch)
        self.resolver = resolver or FakeResolver()
        monkeypatch.setitem(_stock.SEAMS, "resolver", self.resolver)
        self.state = str(self.tmp / "state")
        self.environ = {"OPENHORA_STATE_DIR": self.state, "HTTPS_PROXY": "http://proxy.example:3128", "https_proxy": "http://proxy.example:3128"}
        self.source_file = write_source(self.tmp, data, self.impl.SOURCE + ".json")
        monkeypatch.setitem(_stock.SEAMS, "sources", str(self.tmp))
        self.out = out_dir(self.tmp)
        self.clock = [1_000_000.0]
        monkeypatch.setitem(_stock.SEAMS, "now", lambda: self.clock[0])

    def run(self, *argv, today=TODAY, source_file=None):
        out, err = self.io.StringIO(), self.io.StringIO()
        flags = ["--source-file", source_file or self.source_file, "--today", today]
        _stock.SEAMS["sources"] = os.path.dirname(source_file or self.source_file)        # the folder a source file must be in (monkeypatch restores the first value)
        code = _stock.run(self.impl, flags + list(argv), self.environ, out, err)
        text = out.getvalue()
        self.stdout, self.stderr = text, err.getvalue()
        return code, (json.loads(text) if text.strip() else None)

    def search(self, kind="image", query="mountain lake", count=3, *extra):
        return self.run("search", "--kind", kind, "--query", query, "--count", str(count), "--out", self.out, *extra)

    def fetch(self, kind="image", item="1001", max_bytes=20_000_000, *extra):
        return self.run("fetch", "--kind", kind, "--item", item, "--max-bytes", str(max_bytes), "--out", self.out, *extra)

    def everything(self):
        """All text this run could have leaked a key into: output, errors, every file under the out and state folders (names and contents)."""
        parts = [self.stdout, self.stderr]
        for root in (self.out, self.state):
            for base, dirs, files in os.walk(root):
                parts += [os.path.join(base, n) for n in dirs + files]
                parts += [Path(base, n).read_bytes().decode("latin-1") for n in files]
        return "\n".join(parts)

    def serve_search_image(self, photos):
        self.net.add(API, "/v1/search", json_response({"photos": photos}))
        for p in photos:
            self.net.add(IMG, "/p/%s/medium.jpg" % p["id"], image_response())

    def serve_search_clip(self, videos):
        self.net.add(API, "/v1/videos/search", json_response({"videos": videos}))
        for v in videos:
            self.net.add(IMG, "/p/%s/medium.jpg" % v["id"], image_response())


def deep(d):
    return copy.deepcopy(d)


def query_impl():
    """A synthetic implementation whose library takes the key in the query string (the Pixabay rule): pexels' reading, another way to carry the key."""
    import types
    import pexels
    impl = types.ModuleType("querylib")
    for name in ("SERVES", "SOURCE", "SECRET", "IMAGE_MIN", "search_request", "item_request", "read_search", "read_item"):
        setattr(impl, name, getattr(pexels, name))
    impl.auth = lambda src, key: ({}, {"key": key})
    impl.__doc__ = "a synthetic source that takes its key in the query string"
    return impl
