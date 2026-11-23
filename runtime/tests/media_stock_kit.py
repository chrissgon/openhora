"""The kit of the tests of the licensed pictures of a video (runtime/media_stock.py, runtime/ops_media_stock.py and the step's checks): a flat-colour PNG made with zlib, a fake
`stock:media` provider that writes the files a source's verbs would (previews and a full file of its own bytes) and records each call, a fake renderer `asset-sheet` that
writes what the verb would, and a world: a video that waits at the caption review in a project that uses the sources and accepted them. Not a test file. No library is called,
no process is run, no real picture, link, author or search result is used: every name is invented and every host ends in `.example`.
"""
from __future__ import annotations

import hashlib
import json
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
ops_media_websearch = st.load("ops_media_websearch")
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
        self.titles = {}
        self.lock, self.active, self.most_active, self.clip_seconds = threading.Lock(), {}, {}, 8
        self.waited = set()
        self.bodies, self.say_bytes = {}, {}      # V9b-3c: the bytes an open-web link gives instead of the flat PNG, and the size its answer claims
        self.fail_urls = set()      # the links of the open web whose preview is refused (V9b-3b)

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
            if verb == "preview":
                return self._preview_url(source, flags)
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
                         "author": self.authors.get(source, "Bram Hollow"), "title": self.titles.get(source, "A picture of %s" % query), "licence": self.licences.get(source, "cc0-1.0"),
                         "page": "https://%s.example/p/%s" % (source, item), "preview": name, "preview_sha256": sha(data)})
        return {"ok": True, "source": source, "kind": kind, "candidates": rows, "dropped": {}, "requests": 1, "cached": False, "previews": len(rows)}

    def _fetch(self, source, flags):
        kind, item, out = flag(flags, "--kind"), flag(flags, "--item"), flag(flags, "--out")
        data = png(16, 16, (1, 2, 3 + len(item) % 200))
        name = "full-%s-%s%s.png" % (source, item, "-clip" if kind == "clip" else "")      # a clip's full file ends `-clip`: the fake renderer makes an `.mp4` of it
        Path(out, name).write_bytes(data)
        return {"ok": True, "source": source, "item": item, "kind": kind, "file": name, "bytes": len(data), "sha256": sha(data), "licence": self.licences.get(source, "cc0-1.0"),
                "author": self.authors.get(source, "Bram Hollow"), "title": "A picture", "page": "https://%s.example/p/%s" % (source, item), "seconds": None, "requests": 1}

    def _preview_url(self, source, flags):
        """The open-web provider's `preview`: a flat-colour PNG of its own (the colour comes from the link, so two links give two files) written into `--out` as `q-<sha12>.png`."""
        url, out = flag(flags, "--url"), flag(flags, "--out")
        if url in self.fail_urls:
            raise ops_media_stock.Refused("failed")
        data = self.bodies.get(url) or png(8, 8, tuple(hashlib.sha256(url.encode("utf-8")).digest()[:3]))
        name = "q-%s.png" % sha(data)[:12]
        Path(out, name).write_bytes(data)
        return {"ok": True, "file": name, "bytes": self.say_bytes.get(url, len(data)), "sha256": sha(data), "type": "image/png", "host": "pics.example"}

    def _fetch_url(self, source, flags):
        out = flag(flags, "--out")
        data = self.bodies.get(flag(flags, "--url")) or png(16, 16, (9, 9, 9))
        name = "q-%s%s.png" % (sha(data)[:12], "-clip" if flag(flags, "--kind") == "clip" else "")      # a clip's full file ends `-clip`: the fake renderer makes an `.mp4` of it
        Path(out, name).write_bytes(data)
        return {"ok": True, "file": name, "bytes": self.say_bytes.get(flag(flags, "--url"), len(data)), "sha256": sha(data), "type": "image/png", "host": "pics.example"}


class FakeSheets:
    """The renderer's `asset-sheet` as MediaEngine hands it a call: writes the sheet and, in `full` mode, one `asset-<sha12>.png` per picture (a PNG of its own, not the source's
    bytes) into `--out`, and answers the verb's closed shape. `fail` is an exception to raise; `mutate` changes the answer."""

    def __init__(self):
        self.calls, self.fail, self.mutate, self.clip_seconds = [], None, None, 4.0

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
        self.calls.append({"mode": mode, "items": dict(items), "timeout": timeout, "fps": flag(args, "--fps")})
        assets = []
        for (row, col), path in sorted(items.items()):
            source = Path(path).read_bytes()
            record = {"row": row, "col": col, "file": None, "sha256": sha(source), "width": 8, "height": 8, "source_sha256": sha(source)}
            if mode == "full" and Path(path).stem.endswith("-clip"):      # a clip: the renderer's normalised H.264 file, its bytes planted here
                data = b"\x00\x00\x00\x18ftypisom" + source
                name = "asset-%s.mp4" % sha(data)[:12]
                Path(out, name).write_bytes(data)
                record.update(file=name, sha256=sha(data), width=1080, height=1920, kind="clip", seconds=self.clip_seconds)
            elif mode == "full":
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


def per_item_template() -> dict:
    """The data file of the shipped keyless source whose tier is `per-item` (read by what it says, never by name): the model of the fictional source `shelf` the tests use."""
    for path in sorted((REPO / "providers" / "stock" / "sources").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("licence_tier") == "per-item" and data.get("secret_in") == "none":
            return data
    raise AssertionError("no per-item source is shipped")


def copy_stock_providers(tree: Path, extra=None) -> None:
    """The class's own files into the stand-in tree: the helpers, the open-web provider and its data file, a fictional per-item source `shelf` (the shipped one's data file under another
    name), and a small implementation of its own for each name of `extra` (a dict of data files: a second library for the merge). No shipped library is named."""
    target = tree / "providers" / "stock"
    (target / "sources").mkdir(parents=True)
    for name in ("_stock.py", "_net.py", "web.py"):
        shutil.copy(REPO / "providers" / "stock" / name, target / name)
    shutil.copy(REPO / "providers" / "stock" / "sources" / "web.json", target / "sources" / "web.json")
    sources = {"shelf": dict(per_item_template(), source="shelf")}
    sources.update(extra or {})
    for name, data in sources.items():
        (target / f"{name}.py").write_text(f'SERVES = "stock:media"\nSOURCE = "{name}"\n', encoding="utf-8")
        (target / "sources" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


LIBRARY = {"source": "fakelib", "licence_tier": "library", "licence": media_stock.LICENCES_ACCEPTED[0], "licences": None, "licence_url": "https://fakelib.example/licence", "terms_read_on": "2026-11-12",
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


# --- the web search (V9b-3b): a stand-in for the run of the skill, a candidates file and a world ------------------------------------------------------------------------------------

SKILL = "mkt-video-media-search"
LINK_MARK = "ZQX-LINK-MARK-7731"      # planted in the path and the query of every media link: it must never reach an answer, a run row, a log or stderr
PAGE_MARK = "aster-lane-page-4417"      # in the path of every page address: the terminal and this computer's own page may show it, a run row and stderr never


def web_candidate(slot: str, n: int = 1, kind: str = "image", **more) -> dict:
    """One candidate of the file the skill writes: invented hosts (`.example`), the planted token in the path and the query of each link."""
    base = {"slot": slot, "kind": kind, "media_url": "https://pics.example/m/%s/%s-%d.jpg?t=%s" % (LINK_MARK, slot, n, LINK_MARK), "thumb_url": "https://pics.example/t/%s/%s-%d.jpg?t=%s" % (LINK_MARK, slot, n, LINK_MARK),
            "page_url": "https://pages.example/gallery/%s/%s-%d" % (PAGE_MARK, slot, n), "title": "A market stall at dawn %d" % n, "licence_claim": "free to use, says the page",
            "screen_work": False, "resolution": "1200x800", "site_terms": "Pictures may be shared with a credit to the page."}
    base.update(more)
    return base


def web_document(candidates=(), opens=()) -> dict:
    return {"schema_version": 1, "candidates": list(candidates), "open": list(opens)}


class FakeRun:
    """`ops_contained.execute` as ops_media_websearch calls it: records what it was asked (the prompt, the web flag, the bounds, the files it was given), writes the candidates file a run of the skill
    would write into the run's own `cwd` (`document`, or `raw` bytes, or a link in its place with `link`), and answers the shape of `lab.run_skill`. `mode`: ok | failed | boom | docker."""

    def __init__(self):
        self.calls, self.dests, self.mode, self.document, self.raw, self.link, self.cost = [], [], "ok", None, None, False, 0.04
        self.seen = []      # what each run found in its folder when it ended (to prove the folder is removed afterwards)

    def __call__(self, ctx, skill, meta, keys, routing, prompt, *, platforms=(), timeout=None, dest, prepared_dir, max_cost, sourced=(), around=None, open_web=False):
        self.calls.append({"skill": skill, "prompt": prompt, "open_web": open_web, "timeout": timeout, "max_cost": max_cost, "sourced": tuple(sourced), "platforms": tuple(platforms or ()),
                           "around": around is not None, "dest": dest})
        return self._result(dest, open_web)

    def lab_call(self, skill, prompt, files, dest, *, web=False, model=None, timeout=None, retries=None, platforms=None, max_cost=None, **more):
        """`lab.run_skill` as the real `ops_contained.execute` calls it: records the files the run was handed."""
        self.calls.append({"skill": skill, "prompt": prompt, "open_web": web, "timeout": timeout, "max_cost": max_cost, "files": list(files), "platforms": tuple(platforms or ()), "retries": retries,
                           "dest": dest, "model": model})
        return self._result(dest, web)

    def _result(self, dest, open_web):
        self.dests.append(dest)
        if self.mode == "boom":
            raise RuntimeError("the stand-in exploded while it held the link " + LINK_MARK)
        if self.mode == "docker":
            refused = ops_core.OpsError("docker: the container runtime is unreachable", 3)
            refused.lab_kind = "docker"
            raise refused
        cwd = Path(dest) / "cwd"
        (Path(dest) / "outputs").mkdir(parents=True, exist_ok=True)
        cwd.mkdir(parents=True, exist_ok=True)
        counts = {"attempts": 1, "timeouts": 0, "refusals": 0, "adapter_failures": 0, "early_ends": 0, "pauses": 0, "redactions": 0}
        base = {"run_dir": str(dest), "cwd": str(cwd), "outputs": str(Path(dest) / "outputs"), "counts": counts, "model": "m", "adapter": "h", "web": open_web,
                "image_digest": "sha256:" + "5" * 64, "image_platform": "linux/arm64", "base_commit": None, "tmp": None, "staged": []}
        if self.mode == "failed":
            return dict(base, status="failed", failure={"kind": "timeout", "reason": "the run failed " + LINK_MARK, "detail": None}, response="", changes=None, timing={},
                        reported={"total_tokens": 900, "cost_usd": 0.01})
        folder = cwd / ".workbench-local" / "video"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "web-candidates.json"
        if self.link:
            outside = Path(dest) / "outside.json"
            outside.write_text(json.dumps(self.document or web_document()), encoding="utf-8")
            target.symlink_to(outside)
        elif self.raw is not None:
            target.write_bytes(self.raw)
        elif self.document is not None:
            target.write_text(json.dumps(self.document), encoding="utf-8")
        return dict(base, status="ok", failure=None, response="done", changes=None, timing={"total_tokens": 1200, "duration_ms": 15000, "cost_usd": self.cost, "skills_loaded": [SKILL]})


ROUTING = {"model": "m", "adapter": "h", "billing": "metered", "autonomy": "proven", "web": True, "key_missing": False}


def web_world(world, monkeypatch, searches=None, web=True, stock="default", **more):
    """A video at the caption review whose project uses the open web as a source (accepted with its item), the skill in the stand-in tree (it declares `search:web`, and the checker script is the
    real one), the fake source for the previews, and `FakeRun` in place of the run. Returns what `to_found` returns and `run` and `routing` (a dict the test may change)."""
    folder = st.skill(Path(world["tree"]), SKILL, "", ".workbench-local/video/web-candidates.json", area="marketing")
    manifest = folder / "SKILL.md"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("  requires: []", "  requires: [search:web]"), encoding="utf-8")
    shutil.copy(REPO / "skills" / SKILL / "scripts" / "check_candidates.py", folder / "scripts" / "check_candidates.py")
    found = to_found(world, monkeypatch, searches, stock=stock, **more)
    run, routing = FakeRun(), dict(ROUTING, web=web)
    monkeypatch.setattr(ops_media_websearch.ops_contained, "routed", lambda ctx, skill: ({"web": True, "side_effects": []}, None, routing))
    monkeypatch.setattr(ops_media_websearch.ops_contained, "execute", run)
    monkeypatch.setattr(ops_media_websearch.lab, "skill_identity", lambda skill: {"version": "0.1.0", "content_sha256": "e" * 64})
    monkeypatch.setattr(ops_media_websearch.lab, "reported_usage", lambda dest: None)
    return dict(found, run=run, routing=routing)
