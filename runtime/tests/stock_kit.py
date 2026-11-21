"""The kit of the tests of the licensed pictures of a video (runtime/media_stock.py, runtime/ops_media_stock.py and the step's checks): a flat-colour PNG made with zlib, a fake
`stock:media` provider that writes the files a source's verbs would (previews and a full file of its own bytes) and records each call, a fake renderer `asset-sheet` that
writes what the verb would, and a world: a video that waits at the caption review in a project that uses the sources and accepted them. Not a test file. No library is called,
no process is run, no real picture, link, author or search result is used: every name is invented and every host ends in `.example`.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import threading
import zlib
from pathlib import Path

import standin_tree as st
from media_kit import media as media_store, ops, ops_core, to_review, work_file  # noqa: F401

REPO = st.REPO

media = st.load("media")
captions = st.load("captions")
media_stock = st.load("media_stock")
ops_media_stock = st.load("ops_media_stock")
ops_media_edit = st.load("ops_media_edit")
ops_step_seams = st.load("ops_step_seams")


def png(width: int = 4, height: int = 4, rgb=(10, 20, 30)) -> bytes:
    """A flat-colour PNG, made here with zlib."""
    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def flag(args, name):
    return args[args.index(name) + 1] if name in args else None


class FakeSources:
    """The class `stock:media` as ops_media_stock.Sources: `call(source, verb, flags, timeout)` returns the answer a source would and writes its files into `--out`.
    `licences` maps a source to the licence id its candidates carry (default cc0-1.0), `authors` to the author, `count` is how many candidates a search answers, `fail` maps a
    source to the closed code its verbs raise, `kinds` maps a source to the kinds it serves. `barrier`, when set, makes the first search of each source wait for the others
    (a proof that the sources of a slot are asked at the same time)."""

    def __init__(self):
        self.calls, self.licences, self.authors, self.count, self.fail, self.barrier = [], {}, {}, 2, {}, None
        self.lock, self.active, self.most_active, self.clip_seconds = threading.Lock(), {}, {}, 8
        self.waited = set()

    def of(self, verb, source=None):
        return [c for c in self.calls if c["verb"] == verb and (source is None or c["source"] == source)]

    def call(self, source, verb, flags, timeout):
        with self.lock:
            self.calls.append({"source": source, "verb": verb, "flags": list(flags), "timeout": timeout})
            self.active[source] = self.active.get(source, 0) + 1
            self.most_active[source] = max(self.most_active.get(source, 0), self.active[source])
        try:
            if source in self.fail:
                raise ops_media_stock.Refused(self.fail[source])
            if verb == "search":
                if self.barrier is not None and source not in self.waited:
                    self.waited.add(source)
                    self.barrier.wait(timeout=10)
                return self._search(source, flags)
            if verb == "fetch" and "--item" in flags:
                return self._fetch(source, flags)
            if verb == "fetch":
                return self._fetch_url(source, flags)
            raise AssertionError(verb)
        finally:
            with self.lock:
                self.active[source] -= 1

    def _search(self, source, flags):
        kind, query, out = flag(flags, "--kind"), flag(flags, "--query"), flag(flags, "--out")
        rows = []
        for n in range(min(int(flag(flags, "--count")), self.count)):
            item = "%s-%s-%d" % (source, query.replace(" ", "-"), n + 1)
            name = "prev-%s-%s%s.png" % (source, item, "-clip" if kind == "clip" else "")
            data = png(8, 8, (n * 40 % 255, 100, 200))
            Path(out, name).write_bytes(data)
            rows.append({"item": item, "kind": kind, "width": 1600, "height": 1200, "seconds": self.clip_seconds if kind == "clip" else None,
                         "author": self.authors.get(source, "Bram Hollow"), "title": "A picture of %s" % query, "licence": self.licences.get(source, "cc0-1.0"),
                         "page": "https://%s.example/p/%s" % (source, item), "preview": name, "preview_sha256": sha(data)})
        return {"ok": True, "source": source, "kind": kind, "candidates": rows, "dropped": {}, "requests": 1, "cached": False, "previews": len(rows)}

    def _fetch(self, source, flags):
        kind, item, out = flag(flags, "--kind"), flag(flags, "--item"), flag(flags, "--out")
        data = png(16, 16, (1, 2, 3 + len(item) % 200))
        name = "full-%s-%s.png" % (source, item)
        Path(out, name).write_bytes(data)
        return {"ok": True, "source": source, "item": item, "kind": kind, "file": name, "bytes": len(data), "sha256": sha(data), "licence": self.licences.get(source, "cc0-1.0"),
                "author": self.authors.get(source, "Bram Hollow"), "title": "A picture", "page": "https://%s.example/p/%s" % (source, item), "seconds": None, "requests": 1}

    def _fetch_url(self, source, flags):
        out = flag(flags, "--out")
        data = png(16, 16, (9, 9, 9))
        name = "q-%s.png" % sha(data)[:12]
        Path(out, name).write_bytes(data)
        return {"ok": True, "file": name, "bytes": len(data), "sha256": sha(data), "type": "image/png", "host": "pics.example"}


class FakeSheets:
    """The renderer's `asset-sheet` as MediaEngine hands it a call: writes the sheet and, in `full` mode, one `asset-<sha12>.png` per picture (a PNG of its own, not the source's
    bytes) into `--out`, and answers the verb's closed shape. `fail` is an exception to raise; `mutate` changes the answer."""

    def __init__(self):
        self.calls, self.fail, self.mutate = [], None, None

    def call(self, cls, verb, args, timeout):
        assert (cls, verb) == ("renderer:video", "asset-sheet")
        if self.fail is not None:
            raise self.fail
        mode, out = flag(args, "--mode"), flag(args, "--out")
        items = {}
        for i, a in enumerate(args):
            if a == "--asset":
                key, _, path = args[i + 1].partition("=")
                row, _, col = key.partition(":")
                items[(row, int(col))] = path
        self.calls.append({"mode": mode, "items": dict(items), "timeout": timeout})
        assets = []
        for (row, col), path in sorted(items.items()):
            source = Path(path).read_bytes()
            record = {"row": row, "col": col, "file": None, "sha256": sha(source), "width": 8, "height": 8, "source_sha256": sha(source)}
            if mode == "full":
                data = png(1080, 1920, (sum(source) % 255, 50, 60))
                name = "asset-%s.png" % sha(data)[:12]
                Path(out, name).write_bytes(data)
                record.update(file=name, sha256=sha(data), width=1080, height=1920)
            assets.append(record)
        Path(out, "sheet.png").write_bytes(png(30, 30, (7, 7, 7)))
        done = {"ok": True, "mode": mode, "assets": assets, "sheet": "sheet.png", "sheet_sha256": sha(Path(out, "sheet.png").read_bytes()), "rows": sorted({r for r, _ in items}),
                "replayed": 0}
        return self.mutate(done) if self.mutate else done


SLOT_SOURCE = {"slot": "beat7", "beat": 7, "param": "asset", "type": "image", "description": "a screenshot of a shop"}


def copy_stock_providers(tree: Path, extra=None) -> None:
    """The class's own files into the stand-in tree: the implementations, the helpers and each source's data file; `extra` maps a name to a source file (a dict) that gets a
    small implementation of its own (a second library for the merge)."""
    target = tree / "providers" / "stock"
    shutil.copytree(REPO / "providers" / "stock", target, ignore=shutil.ignore_patterns("tests", "__pycache__", "README.md"))
    for name, data in (extra or {}).items():
        (target / f"{name}.py").write_text(f'SERVES = "stock:media"\nSOURCE = "{name}"\n', encoding="utf-8")
        (target / "sources" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


LIBRARY = {"source": "fakelib", "licence_tier": "library", "licence": "pexels-license", "licences": None, "licence_url": "https://fakelib.example/licence", "terms_read_on": "2026-11-12",
           "secret": None, "secret_in": None, "api": {"host": "api.fakelib.example", "search_image": "/s", "search_clip": "/c", "item_image": "/i/{item}", "item_clip": "/v/{item}"},
           "media_hosts": ["img.fakelib.example"], "redirect_hosts": [], "path_patterns": {"preview": ".*", "image": ".*", "clip": ".*"}, "rendition": {"preview": "p", "image": "i", "clip": "c"},
           "cache_seconds": 0, "credit_line": None, "kinds": ["image", "clip"]}


def configure(world, monkeypatch, stock="default", accept=True, extra=None) -> None:
    """The project's runtime.json with a `media` object (`stock` a list of sources, `"default"` for none named, None for the key left out) accepted with the widening it
    shows, and the class's files in the stand-in tree."""
    tree = Path(world["tree"])
    if not (tree / "providers" / "stock").exists():
        copy_stock_providers(tree, extra)
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["media"] = {} if stock == "default" else {"stock": stock}
    path.write_text(json.dumps(raw), encoding="utf-8")
    if accept:
        accepted(world)


def accepted(world) -> None:
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"], widen=ops.config(world["path"])["widening_sha256"])


def to_found(world, monkeypatch, searches=None, stock="default", extra=None, accept=True):
    """A video at the caption review with a script slot `beat7` (and more when `searches` gives them) set to the choice `stock` with search words, in a project that
    accepted its sources, with the fakes in place. Returns {"task", "sources", "sheets"}."""
    configure(world, monkeypatch, stock, accept, extra)
    fake, sheets = FakeSources(), FakeSheets()
    monkeypatch.setattr(ops_media_stock, "_sources_for", lambda ctx: fake)
    monkeypatch.setattr(ops_media_stock, "_engine_of", lambda ctx: sheets)
    task = to_review(world)
    slots = [dict(SLOT_SOURCE, slot=s, beat=7 + n, description="a screenshot of a shop %d" % n) for n, s in enumerate((searches or {"beat7": ("market stall", "image")}))]
    data = world["data"]
    beats = json.loads(work_file(world, "proposal.beats.json").read_text(encoding="utf-8"))
    beats["slots"] = slots
    media.write_work(data, world["rid"], "proposal.beats.json", json.dumps(beats).encode("utf-8"))
    edits = []
    for slot, (words, want) in (searches or {"beat7": ("market stall", "image")}).items():
        edits += [{"op": "slot", "slot": slot, "choice": "stock"}, {"op": "slot_search", "slot": slot, "search": words, "want": want}]
    ops_media_edit.edit(ops_core.context(world["path"]), task, 0, edits)
    return {"task": task, "sources": fake, "sheets": sheets}


def pick(world, task, slot, pick_string, revision):
    return ops_media_edit.edit(ops_core.context(world["path"]), task, revision, [{"op": "slot_asset", "slot": slot, "pick": pick_string}])


def review_of(world):
    return json.loads(work_file(world, "review.json").read_text(encoding="utf-8"))
