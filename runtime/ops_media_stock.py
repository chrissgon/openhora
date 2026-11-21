#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations of a video's licensed pictures (package V9b-3a, decisions D9 to D12 of the V9b spec): `video-media-find`, `video-media-fetch-picks`,
`video-media-sheet-file`, `video-media-approve` and `video-credits`. Previews first, the full file after the pick, use after the approval:

  video_media_find(project, task, confirm=False, channel=None)      without `confirm`: the words and the sources that would be asked, nothing sent. With it: each licensed
                                                                    source that serves a slot's kind is searched (the sources in parallel, each one request at a time), the
                                                                    candidates are merged per slot, a licence outside the tuple is dropped, the renderer's `asset-sheet` makes
                                                                    the preview sheet, and `set.json` is written. A second call starts over and voids the approval.
  video_media_fetch_picks(project, task, channel=None)              every slot must have a pick (the `slot_asset` edit of the review); each pick's full file is fetched (a
                                                                    licensed one by its provider, from the item id; an open-web one into the quarantine by the web provider),
                                                                    the renderer normalises each to a PNG, and the previews and the unpicked files are deleted.
  video_media_sheet_file(project, task, file, channel=None)         one PNG the container made (`sheet-preview.png`, `sheet.png`, `asset-<sha12>.png`), for the page; never a
                                                                    preview, a full file or a file of the quarantine.
  video_media_approve(project, task, hash=None, channel=None)       without `hash`: the set document, its hash, its credits and the assets that need their own approval. With
                                                                    the current hash: `approved.json` is written and the candidates are deleted.
  video_credits(project, task, channel=None)                        the credits record of a task: what answers a takedown request.

The rules of this module: nothing is searched or fetched for a project whose sources the person did not accept (`stock_not_accepted`, the record `accept-config --widen`
keeps) or without the person's confirm; a source is reached only through the class `stock:media` (providers/resolve.py), by the closed verbs `search` and `fetch`, with the
minimum environment of the class and no key (a source reads its own through the secret resolver); the answers are checked against closed shapes before anything is kept; no
media file's bytes are read here (the renderer's container decodes them) and none is served but the PNGs the container made; no URL or key is in an answer, a message or a
log. The terminal and the page may call these; the local network's socket may not call the first, second and fourth (runtime/operations.py `LAN_REFUSED_OPS`).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import captions  # noqa: E402
import media  # noqa: E402
import media_animation  # noqa: E402
import media_stock  # noqa: E402
import operations  # noqa: E402
import ops_config  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media_edit  # noqa: E402
import ops_step_seams  # noqa: E402
import phrases  # noqa: E402
import policy_widening  # noqa: E402
import project_config  # noqa: E402
import steps  # noqa: E402

CLASS = media_stock.CLASS
CHANNELS = (None, "terminal", "page")
SEARCH_TIMEOUT, FETCH_TIMEOUT, SHEET_TIMEOUT = 60, 300, 400
ITEM = re.compile(r"[A-Za-z0-9_-]{1,64}")
URL = re.compile(r"https://[^\s]{1,2040}")
TEXT = 120
PAGE = 300
SHEET_NAME = "sheet-preview.png"
PNG_LIMIT = 32 * 1024 * 1024
REFUSED_HOSTS, ALLOWED_HOSTS = "web_refused_hosts", "web_allowed_hosts"      # the person's host lists of the open web (read when the configuration holds them)
KEYS_SEARCH = {"ok", "source", "kind", "candidates", "dropped", "requests", "cached", "previews"}
KEYS_CANDIDATE = {"item", "kind", "width", "height", "seconds", "author", "title", "licence", "page", "preview", "preview_sha256"}
KEYS_FETCH = {"ok", "source", "item", "kind", "file", "bytes", "sha256", "licence", "author", "title", "page", "seconds", "requests"}
KEYS_WEB_FETCH = {"ok", "file", "bytes", "sha256", "type", "host"}


def _fail(code: str, text: str, status: int = 1) -> "core.OpsError":
    return core.OpsError(f"{code}: {text}", status)


def _channel(operation: str, channel) -> None:
    """The terminal, the page and a call that names no channel pass; every other channel is refused."""
    if channel not in CHANNELS:
        raise core.OpsError(operations.not_enabled(operation, project_config.clean_name(channel)), 1)


# --- the providers and the engine, seams a test replaces ------------------------------------------------------------------------------------------


class Refused(Exception):
    """A source refused or failed, with one of the closed codes `not_ready`, `timeout`, `usage`, `failed`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Sources:
    """The class `stock:media` through the resolver, for one project: `call(source, verb, flags, timeout)` starts the implementation `source`
    with `--source-file` and `--today` and returns the one JSON object it printed. It starts with the minimum environment of the class (no key: a source reads its own
    from the secret store), and keeps nothing of the provider's text: a refusal is one closed code."""

    def __init__(self, root: str):
        self._root = root

    def call(self, source: str, verb: str, flags, timeout: int) -> dict:
        resolver = project_config.resolver(self._root)
        args = ["--source-file", media_stock.source_path(self._root, source), "--today", time.strftime("%Y-%m-%d"), verb] + [str(f) for f in flags]
        try:
            done = resolver.call(CLASS, None, args, root=self._root, implementation=source, timeout=timeout, env=resolver.provider_environment(CLASS, None, ()))
        except (resolver.UnknownClass, resolver.Unresolved):
            raise Refused("not_ready") from None
        except resolver.ProviderCallError as e:
            raise Refused({"not-configured": "not_ready", "timeout": "timeout", "usage": "usage"}.get(e.kind, "failed")) from None
        if not isinstance(done, dict):
            raise Refused("failed")
        return done


def _sources_for(ctx: dict) -> "Sources":
    """The sources of a call: the real ones. A test replaces this function with a fake of `call(source, verb, flags, timeout)`."""
    return Sources(ctx["root"])


def _engine_of(ctx: dict):
    """The media engine of this project (a seam: a test puts a fake in its place)."""
    return media_animation.engine_of(ctx)


def _sheet(ctx: dict, mode: str, items: dict, out: str) -> dict:
    """One `asset-sheet` call of the renderer: `items` is `{(row, col): path}`. The answer is the renderer's, read as untrusted: the shape is checked by the caller."""
    flags = ["--mode", mode, "--out", out]
    for (row, col), path in sorted(items.items()):
        flags += ["--asset", f"{row}:{col}={path}"]
    try:
        done = _engine_of(ctx).call("renderer:video", "asset-sheet", flags, SHEET_TIMEOUT)
    except ops_step_seams.StepServiceError as e:
        raise _fail("engine_refused" if e.code == "refused" else "not_configured" if e.code == "not_configured" else "engine_failed",
                    "the renderer could not make the sheet") from None
    return done if isinstance(done, dict) else {}


# --- the task and its state ---------------------------------------------------------------------------------------------------------------


def _task(ctx: dict, task_id):
    """(task, recording id, state) of a step task of the kind `media`."""
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise core.OpsError("the task is a number", 2)
    store = ctx["store"]
    task = core._stored(ctx, store.task_get, task_id)
    if not store.is_step_task(task) or task.get("step_kind") != ops_media_edit.KIND:
        raise core.OpsError("this task is not a new video", 1)
    try:
        state = steps.state_of(steps.kind_of(ops_media_edit.KIND), task.get("step_state"))
    except steps.StepFailure:
        raise core.OpsError("the state of this task cannot be read", 1) from None
    rid = (task.get("step_args") or {}).get("media")
    if not isinstance(rid, str):
        raise core.OpsError("this task names no recording", 1)
    return task, rid, state


def _at_review(ctx: dict, task: dict, state: dict) -> None:
    """The media set is chosen while the video waits at the caption review, or after the media set stopped a Continue (`ops_media_edit.stock_repair`): a refusal otherwise."""
    if ops_media_edit.stock_repair(task, state):
        return
    if task["state"] != "waiting" or steps.step_status(state, "review") != "waiting":
        raise _fail("not_at_review", "the media is chosen while the video waits at the caption review")


def _read_review(store, rid: str):
    """(review, proposal beats) of the recording: the review as stored (or new), the proposal the review is made against."""
    transcript = ops_media_edit._json(store, rid, ops_media_edit.TRANSCRIPT)
    try:
        edited = captions.check_edited(ops_media_edit._json(store, rid, ops_media_edit.EDITED, default=captions.start_edited(transcript)))
        review = captions.reconcile(edited, captions.check_review(ops_media_edit._json(store, rid, ops_media_edit.REVIEW, default=captions.new_review())))
    except captions.CaptionError as e:
        raise core.OpsError(f"refused: {e.code} {e.field}".strip(), 1) from None
    return review, ops_media_edit._json(store, rid, ops_media_edit.PROPOSAL_BEATS)


def _stock_error(e: "media_stock.StockError") -> "core.OpsError":
    return _fail("stock_" + e.code, str(e))


def _need_sources(ctx: dict) -> list:
    """The licensed sources this project uses, accepted: `stock_off` when it uses none, `stock_not_accepted` when the person has not accepted them yet (the widening
    record of `accept-config --widen` does not hold their items)."""
    cfg = ctx["cfg"]
    names = media_stock.licensed(cfg["workbench"], media_stock.sources_of(cfg))
    if not names:
        raise _fail("stock_off", "this project uses no licensed stock source: media.stock in docs/workbench/runtime.json lists them")
    got = lambda name: core._stored(ctx, ctx["store"].cursor_get, name)      # noqa: E731
    missing = [i for i in policy_widening.account_widening(got(policy_widening.ACCOUNTS), cfg, ops_config._digest_key(ctx))
               if i["group"].startswith(policy_widening.STOCK_GROUP)]
    if missing:
        raise _fail("stock_not_accepted", phrases.text("VID_STOCK_NOT_ACCEPTED", cfg))
    return names


# --- the closed shapes of a provider's answer ----------------------------------------------------------------------------------------------------


def _text(value, limit: int) -> str:
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())[:limit] if isinstance(value, str) else ""


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) < 1e9


def _candidate(source: str, kind: str, raw, folder_facts, tier: str):
    """(candidate, None) for a candidate a source answered, or (None, reason) with reason `shape`, `licence`, `preview`. The preview file must be a regular file of the
    stock folder with the sha256 the source said (its bytes are not read here); the licence must be in the tuple, and a credit licence needs an author."""
    if not isinstance(raw, dict) or set(raw) != KEYS_CANDIDATE:
        return None, "shape"
    item = raw["item"]
    if not (isinstance(item, str) and ITEM.fullmatch(item)) or raw["kind"] != kind:
        return None, "shape"
    width, height, seconds = raw["width"], raw["height"], raw["seconds"]
    if not all(type(v) is int and v > 0 for v in (width, height)) or not (seconds is None or (_number(seconds) and seconds > 0)):
        return None, "shape"
    licence, author = raw["licence"], _text(raw["author"], TEXT)
    if licence not in media_stock.LICENCES_ACCEPTED or (media_stock.needs_credit(licence) and not author) or tier == "unverified":
        return None, "licence"
    preview, digest = raw["preview"], raw["preview_sha256"]
    if not (isinstance(preview, str) and media_stock.PROVIDER_FILE.fullmatch(preview) and preview.startswith("prev-") and isinstance(digest, str)
            and media_stock.SHA256.fullmatch(digest)) or folder_facts(preview) is None or folder_facts(preview)[0] != digest:
        return None, "preview"
    page = raw["page"] if isinstance(raw["page"], str) and len(raw["page"]) <= PAGE and (not raw["page"] or URL.fullmatch(raw["page"])) else ""
    return {"source": source, "item": item, "pick": f"{source}:{item}", "kind": kind, "licence": licence, "author": author, "title": _text(raw["title"], TEXT),
            "page": page, "width": width, "height": height, "seconds": seconds, "preview": preview, "preview_sha256": digest}, None


def _shown(candidate: dict) -> dict:
    """A candidate as the answers show it: no file name, no URL but the library's own page."""
    return {k: candidate[k] for k in ("pick", "source", "item", "kind", "licence", "author", "title", "page", "width", "height", "seconds")} | \
        {"preview": candidate.get("preview") is not None}


# --- find ----------------------------------------------------------------------------------------------------------------------------------------


def video_media_find(project: str, task_id, confirm=False, channel=None) -> dict:
    """Search the licensed sources for the pictures of the slots of this video. Without `confirm` it sends nothing and answers {"confirmed": False, "sources", "slots":
    [{"slot", "show", "search", "want"}], "message"}; with it, {"confirmed": True, "found", "slots": [{"slot", "show", "search", "want", "candidates": [...]}],
    "sheet", "dropped", "message"}. core.OpsError for every refusal, with nothing kept."""
    _channel("video-media-find", channel)
    ctx = core.context(project)
    if not (type(confirm) is bool or confirm is None):
        raise core.OpsError("confirm is true or false", 2)
    task, rid, state = _task(ctx, task_id)
    _at_review(ctx, task, state)
    names = _need_sources(ctx)
    store = ops_step_seams.MediaStore(ctx)
    review, proposal = _read_review(store, rid)
    slots = media_stock.stock_slots(review, proposal)
    if not slots:
        raise _fail("no_slots", "no slot has search words and the choice stock: give a slot its words (slot_search) and choose stock for it")
    if len(slots) > media_stock.MAX_SLOTS:
        raise _fail("too_many_slots", f"at most {media_stock.MAX_SLOTS} slots take a picture from the media set")
    root = ctx["root"]
    serving = {s["slot"]: [n for n in names if s["want"] in ((media_stock.source_data(root, n) or {}).get("kinds") or [])] for s in slots}
    calls = sum(len(v) for v in serving.values())
    if calls > media_stock.MAX_CALLS:
        raise _fail("too_many_calls", f"a video makes at most {media_stock.MAX_CALLS} calls to the libraries")
    if not confirm:
        words = "; ".join(f"{s['search']}" for s in slots)
        return {"confirmed": False, "sources": names, "slots": slots, "message": phrases.text("VID_STOCK_PREVIEW", ctx["cfg"], sources=", ".join(names), words=words)}
    data_dir = ctx["cfg"]["data_dir"]
    try:
        media_stock.clear_candidates(data_dir, rid)
        media_stock.void_approval(data_dir, rid)
        folder = media_stock.ensure_folder(data_dir, rid)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    sources = _sources_for(ctx)
    facts = lambda name: media_stock.file_facts(data_dir, rid, name)      # noqa: E731
    dropped = {"shape": 0, "licence": 0, "preview": 0, "source": 0}
    found = {s["slot"]: {} for s in slots}

    def run_source(name: str):
        """One source, its slots one after another (a source's rate limit): {slot: [candidates]}."""
        out = {}
        tier = media_stock.tier_of(root, name)
        for s in slots:
            if name not in serving[s["slot"]]:
                continue
            try:
                done = sources.call(name, "search", ["--kind", s["want"], "--query", s["search"], "--count", str(media_stock.PER_SOURCE), "--out", folder], SEARCH_TIMEOUT)
            except Refused:
                out[s["slot"]] = None
                continue
            rows = done.get("candidates") if done.get("ok") is True and set(done) <= KEYS_SEARCH and isinstance(done.get("candidates"), list) else None
            out[s["slot"]] = None if rows is None else rows[:media_stock.PER_SOURCE]
        return out, tier

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(names))) as pool:
        jobs = [(name, pool.submit(run_source, name)) for name in names]
        results = [(name, job.result()) for name, job in jobs]
    per_slot = {s["slot"]: [] for s in slots}
    for name, (answers, tier) in results:      # the order of `names` is the order of media.stock: the merge's round robin
        for s in slots:
            rows = answers.get(s["slot"], [])
            if rows is None:
                dropped["source"] += 1
                continue
            kept = []
            for raw in rows:
                got, why = _candidate(name, s["want"], raw, facts, tier)
                if got is None:
                    dropped[why] += 1
                else:
                    kept.append(got)
            per_slot[s["slot"]].append(kept)
    merged = {slot: media_stock.merge(lists) for slot, lists in per_slot.items()}
    total = sum(len(v) for v in merged.values())
    keep_files = {c["preview"] for rows in merged.values() for c in rows}
    try:
        media_stock.remove_where(data_dir, rid, lambda n: n.startswith("prev-") and n not in keep_files)      # a preview no candidate kept goes at once
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    sheet = None
    if total:
        sheet = _preview_sheet(ctx, rid, slots, merged)
    doc = {"version": media_stock.SET_VERSION, "task": task_id, "at": media_stock.now_stamp(), "phase": "found",
           "slots": [dict(s, candidates=merged[s["slot"]]) for s in slots], "assets": [], "sources": names, "dropped": dropped}
    try:
        media_stock.write_doc(data_dir, rid, media_stock.SET, doc)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    return {"confirmed": True, "found": total, "sheet": sheet, "dropped": dropped, "message": phrases.text("VID_STOCK_FOUND", ctx["cfg"], found=total, slots=len(slots)),
            "slots": [dict(s, candidates=[_shown(c) | {"col": n + 1} for n, c in enumerate(merged[s["slot"]])]) for s in slots]}


def _preview_sheet(ctx: dict, rid: str, slots: list, merged: dict):
    """The contact sheet of the previews, made by the renderer in a scratch folder and kept as `sheet-preview.png`. The answer is checked: it must hold the sheet and
    name exactly the tiles asked for. Returns the sheet's name."""
    data_dir = ctx["cfg"]["data_dir"]
    folder = media_stock.folder_of(data_dir, rid)
    items = {(s["slot"], n + 1): os.path.join(folder, c["preview"]) for s in slots for n, c in enumerate(merged[s["slot"]])}
    try:
        scratch, path = media_stock.make_scratch(data_dir, rid)
        done = _sheet(ctx, "preview", items, path)
        asked = {(r, c) for r, c in items}
        got = {(a.get("row"), a.get("col")) for a in done.get("assets") or [] if isinstance(a, dict)}
        if done.get("ok") is not True or got != asked or done.get("sheet") != "sheet.png":
            raise _fail("engine_refused", "the renderer's sheet is not what was asked for")
        media_stock.adopt(data_dir, rid, scratch, {"sheet.png": SHEET_NAME})
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    return SHEET_NAME


# --- fetch the picks ------------------------------------------------------------------------------------------------------------------------------


def _licence_url(root: str, name: str, licence: str) -> str:
    """The URL of a licence: a credit or public-domain licence's own page (media_stock.licence_name), else the library's `licence_url` of its data file."""
    found = media_stock.licence_name(licence)
    if found is not None:
        return found[2]
    given = (media_stock.source_data(root, name) or {}).get("licence_url")
    return given if isinstance(given, str) and URL.fullmatch(given) else ""


def _picked(found: dict, review: dict, store_kinds: list, cfg=None) -> list:
    """[(slot row, chosen candidate)] for every slot of the set: each slot must have a pick that is one of its candidates; a clip needs an engine that draws clips."""
    out, missing = [], []
    for row in found["slots"]:
        pick = review["slot_assets"].get(row["slot"])
        chosen = next((c for c in row["candidates"] if c["pick"] == pick), None) if pick else None
        if chosen is None:
            missing.append(row["slot"])
            continue
        if chosen["kind"] == "clip" and "clip" not in store_kinds:
            raise _fail("clip_not_drawn", phrases.text("VID_STOCK_CLIP_NOT_DRAWN", cfg))
        out.append((row, chosen))
    if missing:
        raise _fail("no_pick", "every slot needs a pick before the files are fetched; no pick for: " + ", ".join(missing))
    return out


def video_media_fetch_picks(project: str, task_id, channel=None) -> dict:
    """Fetch the full file of each pick, have the renderer normalise it, and delete the previews and the unpicked files. Answers {"assets": [{"slot", "pick", "source",
    "kind", "licence", "width", "height"}], "sheet": "sheet.png", "message"}. The approval, if there was one, is void."""
    _channel("video-media-fetch-picks", channel)
    ctx = core.context(project)
    task, rid, state = _task(ctx, task_id)
    _at_review(ctx, task, state)
    store = ops_step_seams.MediaStore(ctx)
    review, _ = _read_review(store, rid)
    data_dir, cfg = ctx["cfg"]["data_dir"], ctx["cfg"]
    try:
        found = media_stock.read_doc(data_dir, rid, media_stock.SET)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    if found is None or found.get("task") != task_id or not isinstance(found.get("slots"), list):
        raise _fail("no_set", "find the media first (video-media-find)")
    root = ctx["root"]
    accepted = _need_sources(ctx)      # the acceptance is asked again: a source whose terms changed since the find is a new item the person has not accepted
    names = media_stock.sources_of(cfg)
    picks = _picked(found, review, media_animation.asset_kinds(store.root(), store.renderer()), cfg)
    if len(picks) > media_stock.MAX_FULL:
        raise _fail("too_many_slots", f"at most {media_stock.MAX_FULL} files are fetched for a video")
    for _, chosen in picks:      # a source the project no longer lists, or that is licensed and not accepted, is not asked
        if chosen["source"] not in names or (media_stock.tier_of(root, chosen["source"]) != "unverified" and chosen["source"] not in accepted):
            raise _fail("source_off", "a pick comes from a source this project no longer uses: pick again")
    try:
        media_stock.void_approval(data_dir, rid)
        media_stock.remove_where(data_dir, rid, lambda n: n.startswith("full-") or n == media_stock.QUARANTINE or n.startswith(".work") or n == media_stock.SHEET
                                 or media_stock.ASSET_FILE.fullmatch(n) is not None)
        folder = media_stock.ensure_folder(data_dir, rid)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    sources = _sources_for(ctx)
    budget = [media_stock.MAX_FULL_BYTES]
    fetched = {}      # slot -> (path of the full file, sha256, answer)
    for row, chosen in picks:
        cap = min(media_stock.KIND_BYTES[chosen["kind"]], budget[0])
        if cap <= 0:
            raise _fail("too_large", "the files of this video together are over the limit")
        fetched[row["slot"]] = _fetch_one(ctx, sources, data_dir, rid, folder, root, chosen, cap)
        budget[0] -= fetched[row["slot"]][2]["bytes"]
    scratch, path = media_stock.make_scratch(data_dir, rid)
    items = {(slot, 1): got[0] for slot, got in fetched.items()}
    done = _sheet(ctx, "full", items, path)
    rows = {(a.get("row"), a.get("col")): a for a in done.get("assets") or [] if isinstance(a, dict)}
    if done.get("ok") is not True or set(rows) != set(items) or done.get("sheet") != "sheet.png" or done.get("mode", "full") != "full":
        raise _fail("engine_refused", "the renderer's files are not what was asked for")
    assets, moves = [], {"sheet.png": media_stock.SHEET}
    for row, chosen in picks:
        slot = row["slot"]
        a = rows[(slot, 1)]
        name, digest = a.get("file"), a.get("sha256")
        if not (isinstance(name, str) and media_stock.ASSET_FILE.fullmatch(name) and isinstance(digest, str) and media_stock.SHA256.fullmatch(digest)
                and name == f"asset-{digest[:12]}.png" and type(a.get("width")) is int and type(a.get("height")) is int and a["width"] > 0 and a["height"] > 0
                and a.get("source_sha256") == fetched[slot][1]):
            raise _fail("engine_refused", "the renderer's files are not what was asked for")
        moves[name] = name
        got = fetched[slot][2]
        data = media_stock.source_data(root, chosen["source"]) or {}
        assets.append({"slot": slot, "show": row["show"], "search": row["search"], "source": chosen["source"], "item": chosen["item"], "kind": chosen["kind"],
                       "licence": chosen["licence"], "licence_url": _licence_url(root, chosen["source"], chosen["licence"]),
                       "source_link": _source_link(root, chosen["source"]),
                       "terms_read_on": data.get("terms_read_on") if isinstance(data.get("terms_read_on"), str) else None,
                       "author": chosen["author"] or got.get("author") or "", "title": chosen["title"], "page": chosen["page"], "licence_claim": chosen.get("licence_claim") or "",
                       "sha256": digest, "width": a["width"], "height": a["height"], "seconds": chosen["seconds"], "unverified": chosen["licence"] == media_stock.UNVERIFIED})
    try:
        media_stock.adopt(data_dir, rid, scratch, moves)
        media_stock.remove_where(data_dir, rid, lambda n: n.startswith("prev-") or n == media_stock.SHEET_PREVIEW)      # the previews and the preview sheet go now
        found = dict(found, phase="fetched", assets=assets, credits=media_stock.credits_of(assets), fetched_at=media_stock.now_stamp(),
                     credit_of={a["slot"]: media_stock.credit_line(a) for a in assets if a["licence"] in media_stock.LICENCES_CREDIT})
        media_stock.write_doc(data_dir, rid, media_stock.SET, found)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    return {"assets": [{k: a[k] for k in ("slot", "source", "kind", "licence", "width", "height")} | {"pick": f"{a['source']}:{a['item']}", "file": f"asset-{a['sha256'][:12]}.png"}
                       for a in assets],
            "sheet": media_stock.SHEET, "provided": _provided(assets, cfg), "message": "Check the pictures, then approve the media set."}


def _source_link(root: str, source: str) -> str:
    """The link a licensed source's data file gives for itself (its terms page), or "" : shown as text, never loaded."""
    given = (media_stock.source_data(root, source) or {}).get("licence_url")
    return given if isinstance(given, str) and URL.fullmatch(given) else ""


def _provided(assets, cfg) -> list:
    """One line per licensed source whose picture the set holds: "Media provided by <source> (<link>)", in the project's language, the link as plain text."""
    out, seen = [], set()
    for a in assets:
        if a.get("licence") == media_stock.UNVERIFIED or a["source"] in seen:
            continue
        seen.add(a["source"])
        out.append(phrases.text("VID_STOCK_PROVIDED", cfg, source=a["source"], link=a.get("source_link") or "-"))
    return out


def _fetch_one(ctx: dict, sources, data_dir: str, rid: str, folder: str, root: str, chosen: dict, cap: int):
    """(path, sha256, answer) of one pick's full file. A licensed pick is fetched by its provider from the item id the library gave (no URL passes here); an open-web
    pick, which the web provider alone may open, by its URL into the quarantine. The answer is checked against the closed shape, and the file must be a regular file of the
    stock folder with the size and sha256 the provider said."""
    unverified = chosen["licence"] == media_stock.UNVERIFIED
    try:
        if unverified:
            url = chosen.get("url")
            if not (isinstance(url, str) and URL.fullmatch(url)) or media_stock.tier_of(root, chosen["source"]) != "unverified":
                raise _fail("source_off", "this pick cannot be fetched")
            quarantine = os.path.join(folder, media_stock.QUARANTINE)
            os.makedirs(quarantine, mode=0o700, exist_ok=True)
            media_cfg = ctx["cfg"].get("media") or {}
            flags = ["--kind", chosen["kind"], "--url", url, "--out", quarantine, "--max-bytes", str(cap), "--allow-unverified"]
            for host in media_cfg.get(REFUSED_HOSTS) or []:
                flags += ["--refuse-host", host]
            for host in media_cfg.get(ALLOWED_HOSTS) or []:
                flags += ["--allow-host", host]
            done = sources.call(chosen["source"], "fetch", flags, FETCH_TIMEOUT)
            keys, where = KEYS_WEB_FETCH, os.path.join(quarantine, str(done.get("file")))
        else:
            done = sources.call(chosen["source"], "fetch", ["--kind", chosen["kind"], "--item", chosen["item"], "--out", folder, "--max-bytes", str(cap)], FETCH_TIMEOUT)
            keys, where = KEYS_FETCH, os.path.join(folder, str(done.get("file")))
    except Refused as e:
        raise _fail("fetch_" + e.code, "a source could not give the file") from None
    name = done.get("file")
    if done.get("ok") is not True or not set(done) <= keys or not (isinstance(name, str) and media_stock.PROVIDER_FILE.fullmatch(name)):
        raise _fail("fetch_failed", "a source's answer is not in the shape the store keeps")
    if not unverified and (done.get("licence") not in media_stock.LICENCES_ACCEPTED or done.get("licence") != chosen["licence"] or done.get("item") != chosen["item"]):
        raise _fail("licence_refused", "a fetched file is not under the licence the candidate had")
    if not name.startswith("q-" if unverified else "full-"):
        raise _fail("fetch_failed", "a source's answer is not in the shape the store keeps")
    size, digest = done.get("bytes"), done.get("sha256")
    if type(size) is not int or not 0 < size <= cap or not (isinstance(digest, str) and media_stock.SHA256.fullmatch(digest)):
        raise _fail("fetch_failed", "a source's answer is not in the shape the store keeps")
    try:
        facts = _facts_at(data_dir, rid, name, unverified)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    if facts is None or facts != (digest, size):
        raise _fail("fetch_failed", "the fetched file is not the one the source reported")
    return where, digest, dict(done, bytes=size)


def _facts_at(data_dir: str, rid: str, name: str, quarantine: bool):
    """(sha256, size) of a file of the stock folder, or of its quarantine."""
    if not quarantine:
        return media_stock.file_facts(data_dir, rid, name)
    path = os.path.join(media_stock.folder_of(data_dir, rid), media_stock.QUARANTINE, name)
    try:
        digest, size = media.sha256_of(path), os.lstat(path).st_size
    except (media.MediaError, OSError):
        return None
    return digest, size


# --- the page's files, the approval and the credits -----------------------------------------------------------------------------------------------


def video_media_sheet_file(project: str, task_id, file, channel=None) -> dict:
    """One PNG the container made for this video's media set, for the page: {"media_type": "image/png", "data": bytes}. Only `sheet-preview.png`, `sheet.png` and
    `asset-<sha12>.png`; the raw preview and full files and the quarantine are never served. It may cross the local network's socket (it is our own drawing of previews
    already shown to the person)."""
    _channel("video-media-sheet-file", channel)
    ctx = core.context(project)
    _, rid, _ = _task(ctx, task_id)
    try:
        return {"media_type": "image/png", "data": media_stock.read_served(ctx["cfg"]["data_dir"], rid, file, PNG_LIMIT)}
    except media_stock.StockError as e:
        raise _stock_error(e) from None


def _fetched_set(ctx: dict, task_id, rid: str):
    """The set of this task in phase `fetched`, with each asset's file checked again against its sha256 (a file swapped under the same name is `asset_changed`)."""
    data_dir = ctx["cfg"]["data_dir"]
    try:
        found = media_stock.read_doc(data_dir, rid, media_stock.SET)
        if found is None or found.get("task") != task_id or found.get("phase") != "fetched" or not found.get("assets"):
            raise _fail("no_set", "fetch the picks first (video-media-fetch-picks)")
        for a in found["assets"]:
            got = media_stock.file_facts(data_dir, rid, f"asset-{a['sha256'][:12]}.png")
            if got is None or got[0] != a["sha256"]:
                raise _fail("asset_changed", "a picture of the set is not the file that was made: fetch the picks again")
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    return found


def video_media_approve(project: str, task_id, hash=None, channel=None) -> dict:      # noqa: A002  (the flag is --hash)
    """The media set, for the person to read and approve. Without `hash`: {"approved": whether the current set is, "set": the set document, "sha256", "credits", "needs_own_approval":
    the slots of the assets that need one of their own (a licence nobody checked)}. With `hash` equal to the set's current hash: `approved.json` is written, the previews, the full
    files and the quarantine are deleted, the credits record is written, and {"approved": True, "sha256", "credits"} is answered. A stale hash is refused (`stale_hash`)."""
    _channel("video-media-approve", channel)
    ctx = core.context(project)
    task, rid, state = _task(ctx, task_id)
    _at_review(ctx, task, state)
    data_dir, cfg = ctx["cfg"]["data_dir"], ctx["cfg"]
    found = _fetched_set(ctx, task_id, rid)
    document = media_stock.set_document(found)
    digest = media_stock.set_hash(document)
    try:
        current = media_stock.approval_matches(found, media_stock.read_doc(data_dir, rid, media_stock.APPROVED))
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    own = [a["slot"] for a in document["assets"] if a["unverified"]]
    if hash is None:
        return {"approved": current, "set": document, "sha256": digest, "credits": document["credits"], "needs_own_approval": own, "provided": _provided(found["assets"], cfg),
                "credit_heading": phrases.text("VID_STOCK_CREDIT", cfg)}
    if not (isinstance(hash, str) and media_stock.SHA256.fullmatch(hash)):
        raise core.OpsError("the hash is 64 lowercase hexadecimal characters", 2)
    if hash != digest:
        raise _fail("stale_hash", f"the set is not the one that hash names; read it again (current sha256 {digest})")
    names = sorted(media_stock.sources_of(cfg))
    record = {"hash": digest, "at": media_stock.now_stamp(), "task": task_id, "sources": names, "unverified": {},
              "assets": [{k: a[k] for k in ("slot", "sha256", "source", "item", "licence")} for a in document["assets"]]}
    try:
        media_stock.write_doc(data_dir, rid, media_stock.APPROVED, record)
        keep = {f"asset-{a['sha256'][:12]}.png" for a in document["assets"]}
        media_stock.clear_candidates(data_dir, rid, keep=keep | {media_stock.SHEET})
        media_stock.write_credits(data_dir, task_id, media_stock.credits_record(found, document, rid))
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    return {"approved": True, "sha256": digest, "credits": document["credits"], "needs_own_approval": own, "provided": _provided(found["assets"], cfg), "credit_heading": phrases.text("VID_STOCK_CREDIT", cfg)}


def video_credits(project: str, task_id, channel=None) -> dict:
    """The credits record of a task: the set document without the words typed for each slot, the credit lines, and each open-web asset's source page and claimed licence.
    It answers a takedown request. {"task", "assets", "credits", "web"}."""
    _channel("video-credits", channel)
    ctx = core.context(project)
    if isinstance(task_id, bool) or not isinstance(task_id, int):
        raise core.OpsError("the task is a number", 2)
    found = media_stock.read_credits(ctx["cfg"]["data_dir"], task_id)
    if found is None:
        raise _fail("no_credits", "no media set was approved for this task, or its credits record was removed after a year")
    provided = [phrases.text("VID_STOCK_PROVIDED", ctx["cfg"], source=p["source"], link=p.get("link") or "-") for p in found.get("providers") or [] if isinstance(p, dict)]
    return {"task": found.get("task"), "assets": found.get("assets") or [], "credits": found.get("credits") or [], "web": found.get("web") or [], "provided": provided,
            "text_from_the_library": True}      # S4: the credit lines, the titles, the authors and the page addresses are written by the libraries and the web: shown here, on this computer


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
