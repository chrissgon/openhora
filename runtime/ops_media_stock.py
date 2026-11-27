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
  video_media_fetch_picks(project, task, channel=None)              every slot that has candidates and is still chosen as stock must have a pick (the `slot_asset` edit of the review; a slot with none, or no longer chosen, is left without a picture); each pick's full file is fetched (a
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

V9b-3b: one set holds the licensed candidates and the ones the open web gave (runtime/ops_media_websearch.py): `video_media_find` replaces the licensed candidates and carries the open-web ones of a
`found` set whose slot has the same words, `_compose` is the tail both searches share, `_web_ready` is the acceptance of the open-web source, and `video_media_approve` lists the files that still need their own approval.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import concurrent.futures
import math
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
SCAN_TIMEOUT = 660      # validity: the scan's container ends at 600 s (providers/renderer/_host.py SCAN_TIMEOUT), the host waits a minute more
SCAN_LANG = "eng+por+spa"      # = providers/renderer/_host.py SCAN_LANG (a test compares): the languages Tesseract reads
SCAN_ROW_CODES = media_stock.SCAN_CODES + ("scan_failed",)      # the rows' closed codes: the renderer's, and this module's own (a test compares the first with providers/renderer/_scan.py SCAN_CODES)
SCAN_PHRASE = {"text_found": "CARD_VIDEO_SCAN_TEXT_FOUND", "qr_link": "CARD_VIDEO_SCAN_QR_LINK", "qr_action": "CARD_VIDEO_SCAN_QR_ACTION", "qr_text": "CARD_VIDEO_SCAN_QR_TEXT",
               "qr_unreadable": "CARD_VIDEO_SCAN_QR_UNREADABLE", "scan_partial": "CARD_VIDEO_SCAN_PARTIAL", "scan_failed": "CARD_VIDEO_SCAN_FAILED"}
SCAN_FIELDS = frozenset({"slot", "host", "scheme", "count", "chars", "value", "total", "reason"})      # S4: the only fields a scan sentence is built from; the text a picture holds is never one of them (L82)
SCAN_PHRASE_KEYS = tuple(SCAN_PHRASE.values()) + ("CARD_VIDEO_SCAN_QR_LINK_UNKNOWN", "CARD_VIDEO_SCAN_NOT_RUN", "CARD_VIDEO_SCAN_HEADING", "CARD_VIDEO_SCAN_CLEAN", "CARD_VIDEO_SCAN_SCOPE", "CARD_VIDEO_SCAN_QUOTE")
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
    store = ops_step_seams.MediaStore(ctx)
    return SheetEngine(store.root(), store.renderer())


# The closed list of the codes `asset-sheet` refuses a picture with (providers/renderer/_asset_sheet.py; a test compares). Only a code of this list is kept; free text never is.
ASSET_CODES = ("asset_corrupt", "asset_dimensions", "asset_duplicate", "asset_max_bytes", "asset_max_pixels", "asset_max_side", "asset_too_small", "asset_type", "asset_unreadable")
ASSET_PHRASE = {"asset_too_small": "VID_STOCK_ASSET_SMALL"}      # every other code of the list says "this file cannot be used" (VID_STOCK_ASSET_UNUSABLE)


class SheetEngine(ops_step_seams.MediaEngine):
    """The media engine with one difference: a refusal of `asset-sheet` or of `scan` keeps its closed code (the first line of the renderer's stderr, `refused: <code> <field>`), read only if
    the code is in ASSET_CODES (for `scan`, media_stock.SCAN_REASONS), so the person is told why a picture was refused or why a scan did not run; a scan that timed out is the code `timeout`.
    Every other answer and failure is the engine's own."""

    def call(self, cls, verb, args, timeout):
        if verb not in ("asset-sheet", "scan"):
            return super().call(cls, verb, args, timeout)
        resolver = project_config.resolver(self._root)
        closed = ASSET_CODES if verb == "asset-sheet" else media_stock.SCAN_REASONS
        try:
            done = resolver.call(cls, verb, list(args), root=self._root, timeout=timeout, env=resolver.provider_environment(cls, None, ()),
                                 **({"implementation": self._renderer} if self._renderer else {}))
        except resolver.ProviderCallError as e:
            if e.kind == "not-configured":
                raise ops_step_seams.StepServiceError("not_configured") from None
            if verb == "scan" and e.kind == "timeout":
                raise ops_step_seams.StepServiceError("refused", "timeout") from None
            found = ops_step_seams.REFUSAL_LINE.search(getattr(e, "stderr_tail", "") or "") if e.kind != "usage" and e.exit_code == 1 else None
            if found and found.group(1) in closed:
                raise ops_step_seams.StepServiceError("refused", found.group(1)) from None
            raise ops_step_seams.StepServiceError("refused" if e.kind == "usage" or e.exit_code == 1 else "engine_failed") from None
        if not isinstance(done, dict):
            raise ops_step_seams.StepServiceError("engine_failed")
        return done


def _sheet(ctx: dict, mode: str, items: dict, out: str, fps=None) -> dict:
    """One `asset-sheet` call of the renderer: `items` is `{(row, col): path}`. `fps`, when given, is the edit list's frame rate a clip is normalised to (V9b-5c). The answer is
    the renderer's, read as untrusted: the shape is checked by the caller."""
    flags = ["--mode", mode, "--out", out]
    if fps is not None:
        flags += ["--fps", str(fps)]
    for (row, col), path in sorted(items.items()):
        flags += ["--asset", f"{row}:{col}={path}"]
    try:
        done = _engine_of(ctx).call("renderer:video", "asset-sheet", flags, SHEET_TIMEOUT)
    except ops_step_seams.StepServiceError as e:
        if e.code == "refused" and e.reason in ASSET_CODES:
            raise _fail(e.reason, phrases.text(ASSET_PHRASE.get(e.reason, "VID_STOCK_ASSET_UNUSABLE"), ctx["cfg"])) from None
        raise _fail("engine_refused" if e.code == "refused" else "not_configured" if e.code == "not_configured" else "engine_failed",
                    "the renderer could not make the sheet") from None
    return done if isinstance(done, dict) else {}


# --- the scan of the set's files (P9-a): text and QR codes, a warning and never a refusal -----------------------------------------------------------


class ScanFailed(Exception):
    """The scan did not give an answer: `reason` is one of media_stock.SCAN_REASONS."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _scan_call(ctx: dict, items: list) -> dict:
    """One `scan` call of the renderer (a container of its own, no network, on the normalised files): `items` is [(slot, path, width, height)]. Returns {"scanner": {...}, "assets": {slot: entry}}
    with every entry cleaned again (`media_stock.clean_scan_entry`), the answer being untrusted; ScanFailed otherwise."""
    flags = []
    for slot, path, width, height in items:
        flags += ["--asset", f"{slot}={path}", "--size", f"{slot}={width}x{height}"]
    try:
        done = _engine_of(ctx).call("renderer:video", "scan", flags, SCAN_TIMEOUT)
    except ops_step_seams.StepServiceError as e:
        raise ScanFailed("not_ready" if e.code == "not_configured" else e.reason if e.code == "refused" and e.reason in media_stock.SCAN_REASONS else "container_failed") from None
    rows = done.get("assets") if isinstance(done, dict) else None
    if not (isinstance(done, dict) and done.get("ok") is True and isinstance(rows, list) and done.get("lang") == SCAN_LANG
            and sorted(r.get("slot") for r in rows if isinstance(r, dict)) == sorted(i[0] for i in items) and len(rows) == len(items)):
        raise ScanFailed("container_result_invalid")
    versions = done.get("versions") if isinstance(done.get("versions"), dict) else {}
    image = done.get("image") if isinstance(done.get("image"), dict) else {}
    entries = {r["slot"]: media_stock.clean_scan_entry(r) for r in rows}
    if any(e is None for e in entries.values()):
        raise ScanFailed("container_result_invalid")
    return {"scanner": {"image": image.get("tag"), "lang": SCAN_LANG, "tesseract": versions.get("tesseract"), "opencv": versions.get("opencv")}, "assets": entries}


def _scan_set(ctx: dict, data_dir: str, rid: str, assets: list) -> None:
    """Scan the files of a fetched set and keep the result in `scan.json`, keyed by each file's sha256: a file whose entry is already there (a re-fetch that kept it) is not read again, and the
    entries of files that are no longer in the set go. It never raises and never refuses anything: a scan that fails is written as its closed reason, and the person is told on the approval."""
    try:
        before = media_stock.read_scan(data_dir, rid)
    except media_stock.StockError:
        before = {"scanner": {}, "assets": {}}
    keep = {a["sha256"] for a in assets}
    cached = {d: e for d, e in before["assets"].items() if d in keep} if before["scanner"].get("lang") == SCAN_LANG else {}
    todo = [a for a in assets if a["sha256"] not in cached]
    entries, scanner, failed = dict(cached), before["scanner"] if cached else {}, None
    if todo:
        folder = media_stock.folder_of(data_dir, rid)
        try:
            got = _scan_call(ctx, [(a["slot"], os.path.join(folder, media_stock.asset_name(a)), a["width"], a["height"]) for a in todo])
            scanner = got["scanner"]
            for a in todo:
                entries[a["sha256"]] = got["assets"][a["slot"]]
        except ScanFailed as e:
            failed = e.reason
    try:
        media_stock.write_doc(data_dir, rid, media_stock.SCAN, {"version": media_stock.SCAN_VERSION, "scanner": scanner, "assets": entries, "failed": failed, "at": media_stock.now_stamp()})
    except media_stock.StockError:
        pass      # a warning that cannot be kept is shown as not run on the approval


def _quote(lines) -> list:
    """The text a picture held, as the lines the page quotes: cleaned again, at most 8 lines and 600 characters in all (L82: never part of a sentence)."""
    out, total = [], 0
    for line in lines if isinstance(lines, list) else []:
        line = _text(line, media_stock.SCAN_LINE_MAX)
        if line and len(out) < media_stock.SCAN_LINES_MAX and total + len(line) <= media_stock.SCAN_CHARS_MAX:
            out.append(line)
            total += len(line)
    return out


def _scan_rows(slot: str, entry: dict, cfg: dict) -> list:
    """The rows of one file's entry, in the order the codes are listed: {"slot", "code", ...the numbers, the host or scheme..., "sentence"}; the text read is only in `quote`. A clean file has none."""
    say = lambda key, **fields: phrases.text(key, cfg, **fields)      # noqa: E731
    rows, codes = [], entry["codes"]
    if "text_found" in codes:
        rows.append({"slot": slot, "code": "text_found", "chars": entry["text"]["chars"], "quote": _quote(entry["text"]["lines"]), "cut": entry["text"]["cut"],
                     "sentence": say(SCAN_PHRASE["text_found"], slot=slot, chars=entry["text"]["chars"])})
    links, actions = {}, {}
    for q in entry["qr"]:
        if q["kind"] == "link":
            links[q["host"]] = links.get(q["host"], 0) + 1
        elif q["kind"] == "action":
            actions[q["scheme"]] = actions.get(q["scheme"], 0) + 1
        elif q["text"]:
            rows.append({"slot": slot, "code": "qr_text", "quote": [_text(q["text"], media_stock.SCAN_QR_TEXT_MAX)], "sentence": say(SCAN_PHRASE["qr_text"], slot=slot)})
    for host, count in sorted(links.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
        rows.append({"slot": slot, "code": "qr_link", "host": host, "count": count,
                     "sentence": say(SCAN_PHRASE["qr_link"], slot=slot, host=host) if host else say("CARD_VIDEO_SCAN_QR_LINK_UNKNOWN", slot=slot)})
    for scheme, count in sorted(actions.items()):
        rows.append({"slot": slot, "code": "qr_action", "scheme": scheme, "count": count, "sentence": say(SCAN_PHRASE["qr_action"], slot=slot, scheme=scheme)})
    if "qr_unreadable" in codes:
        rows.append({"slot": slot, "code": "qr_unreadable", "sentence": say(SCAN_PHRASE["qr_unreadable"], slot=slot)})
    if "scan_partial" in codes:
        rows.append({"slot": slot, "code": "scan_partial", "value": entry["frames_qr"], "total": entry["frames"],
                     "sentence": say(SCAN_PHRASE["scan_partial"], slot=slot, value=entry["frames_qr"], total=entry["frames"])})
    return rows


def _scan_report(ctx: dict, rid: str, assets: list) -> dict:
    """What the scan found in `assets` (the set's assets, or the one the person is about to approve), for the approval, read from `scan.json`: {"state": "done" when every file has its entry, "failed"
    when the scan could not run (and "reason"), "not_run" when none was made (a set fetched before the scan existed); "heading", "scope" and "quote_label" (the project's language), "rows", "clean": the
    slots with nothing found, "clean_lines"}. Each row's sentence is a phrase of the closed fields; the quoted text is in `quote` and nowhere else. It never raises: an unreadable `scan.json` is "not_run"."""
    cfg = ctx["cfg"]
    try:
        doc = media_stock.read_scan(cfg["data_dir"], rid)
    except media_stock.StockError:
        doc = {"assets": {}, "failed": None}
    rows, clean, missing = [], [], []
    for a in sorted(assets, key=lambda a: a["slot"]):
        entry = doc["assets"].get(a["sha256"])
        if entry is None:
            missing.append(a["slot"])
            continue
        found = _scan_rows(a["slot"], entry, cfg)
        rows += found
        if not found:
            clean.append(a["slot"])
    state, reason = "done", None
    if missing:
        state, reason = ("failed", doc["failed"]) if doc["failed"] else ("not_run", None)
        rows.append({"slot": None, "code": "scan_failed", "reason": reason,
                     "sentence": phrases.text(SCAN_PHRASE["scan_failed"], cfg, reason=reason) if reason else phrases.text("CARD_VIDEO_SCAN_NOT_RUN", cfg)})
    return {"state": state, "reason": reason, "heading": phrases.text("CARD_VIDEO_SCAN_HEADING", cfg), "scope": phrases.text("CARD_VIDEO_SCAN_SCOPE", cfg),
            "quote_label": phrases.text("CARD_VIDEO_SCAN_QUOTE", cfg), "rows": rows, "clean": clean,
            "clean_lines": [phrases.text("CARD_VIDEO_SCAN_CLEAN", cfg, slot=slot) for slot in clean]}


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


def _unaccepted(ctx: dict, names) -> list:
    """The widening items of the stock sources `names` that the record of `accept-config --widen` does not hold yet (the item of a source is its group `stock=<name>@...`)."""
    got = lambda name: core._stored(ctx, ctx["store"].cursor_get, name)      # noqa: E731
    prefixes = tuple(f"{policy_widening.STOCK_GROUP}{n}@" for n in names)
    return [i for i in policy_widening.account_widening(got(policy_widening.ACCOUNTS), ctx["cfg"], ops_config._digest_key(ctx)) if i["group"].startswith(prefixes)]


def _need_sources(ctx: dict) -> list:
    """The licensed sources this project uses, accepted: `stock_off` when it uses none, `stock_not_accepted` when the person has not accepted them yet (the widening
    record of `accept-config --widen` does not hold their items). The item of the open web is another source's: a missing one never blocks a licensed find (V9b-3b)."""
    cfg = ctx["cfg"]
    names = media_stock.licensed(cfg["workbench"], media_stock.sources_of(cfg))
    if not names:
        raise _fail("stock_off", "this project uses no licensed stock source: media.stock in docs/workbench/runtime.json lists them")
    if _unaccepted(ctx, names):
        raise _fail("stock_not_accepted", phrases.text("VID_STOCK_NOT_ACCEPTED", cfg))
    return names


def _web_ready(ctx: dict) -> str:
    """The name of the open-web source this project uses, when it is on and its item is accepted: `web_off` when `media.stock` lists none, `stock_not_accepted` when the person has not
    accepted its item (a project accepted before V9b-3b accepts again with `accept-config --widen`)."""
    name = media_stock.web_source(ctx["cfg"])
    if name is None:
        raise _fail("web_off", "this project does not use the open web as a source: media.stock in docs/workbench/runtime.json lists the sources")
    if _unaccepted(ctx, [name]):
        raise _fail("stock_not_accepted", phrases.text("VID_STOCK_NOT_ACCEPTED", ctx["cfg"]))
    return name


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


WEB_SHOWN = ("licence_claim", "site_terms", "resolution", "screen_work", "page_host")


def _shown(candidate: dict) -> dict:
    """A candidate as the answers show it: no file name, no URL but the page's (a library's own page, or the page an open-web file was found on, which is text for this computer's own
    page and the terminal). A candidate from the open web also shows what its page claims, its terms, its resolution, whether it is a still of a screen work and its host: text
    from the web, shown as such; never the link of the file."""
    out = {k: candidate[k] for k in ("pick", "source", "item", "kind", "licence", "author", "title", "page", "width", "height", "seconds")} | {"preview": candidate.get("preview") is not None}
    if candidate.get("licence") == media_stock.UNVERIFIED:
        out.update({k: candidate.get(k) for k in WEB_SHOWN})
    return out


def _previewless(c: dict) -> bool:
    """True for a clip of the open web that came with no thumbnail (K4): a candidate with no preview file, drawn on the sheet only after its fetch."""
    return (c.get("preview") is None and c.get("preview_in") is None and c.get("preview_sha256") is None and c.get("kind") == "clip" and c.get("licence") == media_stock.UNVERIFIED)


def _preview_path(folder: str, candidate: dict) -> str:
    """The file of a candidate's preview: in the stock folder, or in its quarantine for a candidate of the open web (`preview_in`)."""
    return os.path.join(folder, media_stock.QUARANTINE, candidate["preview"]) if candidate.get("preview_in") == media_stock.QUARANTINE else os.path.join(folder, candidate["preview"])


def _carried(ctx: dict, rid: str, old, task_id, slots: list, web: bool) -> dict:
    """{source: {slot: [candidates]}} of the candidates of the set `old` (phase `found`, this task) that a new search of the other kind keeps: those of the open web when `web`, else
    the licensed ones; only for a slot whose row has the same words and kind as the new one, only from a source this project still uses, and only while the preview file is
    there with the sha256 the candidate has (V9b-3b: one set, two searches)."""
    if not (isinstance(old, dict) and old.get("phase") == "found" and old.get("task") == task_id and isinstance(old.get("slots"), list)):
        return {}
    cfg, data_dir = ctx["cfg"], ctx["cfg"]["data_dir"]
    names = [n for n in media_stock.sources_of(cfg) if (media_stock.tier_of(cfg["workbench"], n) == "unverified") is web]
    new = {s["slot"]: (s["search"], s["want"]) for s in slots}
    out = {}
    for row in old["slots"]:
        if not isinstance(row, dict) or new.get(row.get("slot")) != (row.get("search"), row.get("want")):
            continue
        for c in row.get("candidates") or []:
            if (web and isinstance(c, dict) and c.get("source") in names and _previewless(c)
                    and all(k in c for k in ("pick", "item", "kind", "licence", "author", "title", "page", "width", "height", "seconds"))):
                out.setdefault(c["source"], {}).setdefault(row["slot"], []).append(c)      # no preview file to check
                continue
            if not (isinstance(c, dict) and c.get("source") in names and isinstance(c.get("preview"), str) and media_stock.PROVIDER_FILE.fullmatch(c["preview"])
                    and isinstance(c.get("preview_sha256"), str) and (c.get("licence") == media_stock.UNVERIFIED) is web and (c.get("preview_in") == media_stock.QUARANTINE) is web
                    and all(k in c for k in ("pick", "item", "kind", "licence", "author", "title", "page", "width", "height", "seconds"))):
                continue
            try:
                facts = _facts_at(data_dir, rid, c["preview"], web)
            except media_stock.StockError:
                continue
            if facts is not None and facts[0] == c["preview_sha256"]:
                out.setdefault(c["source"], {}).setdefault(row["slot"], []).append(c)
    return out


def _compose(ctx: dict, rid: str, task_id, slots: list, per_source: dict, dropped: dict) -> dict:
    """What the tail of a search does, for the licensed one and the open-web one alike (V9b-3b: one set, two searches): the candidates of each source (`per_source`: {source: {slot:
    [candidates]}}) merged per slot round robin in the order of `media.stock`, at most six; the previews no candidate kept go (a licensed one at once, an open-web one from the
    quarantine); the renderer draws the sheet of the previews; `set.json` is written in phase `found`. Returns the answer both searches give."""
    data_dir, cfg = ctx["cfg"]["data_dir"], ctx["cfg"]
    listed = [n for n in media_stock.sources_of(cfg) if n in per_source]
    merged = {s["slot"]: media_stock.merge([per_source[n].get(s["slot"], []) for n in listed]) for s in slots}      # the order of `listed` is the order of media.stock: the round robin's
    total = sum(len(v) for v in merged.values())
    keep = {c["preview"] for rows in merged.values() for c in rows if isinstance(c.get("preview"), str) and c.get("preview_in") != media_stock.QUARANTINE}
    keep_q = {c["preview"] for rows in merged.values() for c in rows if isinstance(c.get("preview"), str) and c.get("preview_in") == media_stock.QUARANTINE}
    try:
        media_stock.remove_where(data_dir, rid, lambda n: n.startswith("prev-") and n not in keep)      # a preview no candidate kept goes at once
        media_stock.prune_quarantine(data_dir, rid, keep_q)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    sheet = _preview_sheet(ctx, rid, slots, merged) if any(isinstance(c.get("preview"), str) for rows in merged.values() for c in rows) else None      # a candidate with no preview has no tile
    doc = {"version": media_stock.SET_VERSION, "task": task_id, "at": media_stock.now_stamp(), "phase": "found",
           "slots": [dict(s, candidates=merged[s["slot"]]) for s in slots], "assets": [], "sources": listed, "dropped": dropped}
    try:
        media_stock.write_doc(data_dir, rid, media_stock.SET, doc)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    return {"confirmed": True, "found": total, "sheet": sheet, "dropped": dropped, "message": phrases.text("VID_STOCK_FOUND", cfg, found=total, slots=len(slots)),
            "slots": [dict(s, candidates=[_shown(c) | {"col": n + 1} for n, c in enumerate(merged[s["slot"]])]) for s in slots]}


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
        old = media_stock.read_doc(data_dir, rid, media_stock.SET)
    except media_stock.StockError:
        old = None
    carried = _carried(ctx, rid, old, task_id, slots, web=True)      # V9b-3b: a new find replaces the licensed candidates only; the open-web ones of the same words stay
    try:
        media_stock.clear_licensed(data_dir, rid)
        media_stock.void_approval(data_dir, rid)
        folder = media_stock.ensure_folder(data_dir, rid)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    sources = _sources_for(ctx)
    facts = lambda name: media_stock.file_facts(data_dir, rid, name)      # noqa: E731
    dropped = {"shape": 0, "licence": 0, "preview": 0, "source": 0}

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
    per_source = dict(carried)
    for name, (answers, tier) in results:      # the order of `names` is the order of media.stock: the merge's round robin (`_compose` keeps it)
        per_source[name] = {}
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
            per_source[name][s["slot"]] = kept
    return _compose(ctx, rid, task_id, slots, per_source, dropped)


def _preview_sheet(ctx: dict, rid: str, slots: list, merged: dict):
    """The contact sheet of the previews, made by the renderer in a scratch folder and kept as `sheet-preview.png`. The answer is checked: it must hold the sheet and
    name exactly the tiles asked for. Returns the sheet's name."""
    data_dir = ctx["cfg"]["data_dir"]
    folder = media_stock.folder_of(data_dir, rid)
    items = {(s["slot"], n + 1): _preview_path(folder, c) for s in slots for n, c in enumerate(merged[s["slot"]]) if not _previewless(c)}      # the column of a candidate with no preview stays empty
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


CLIP_MIN_DURATION = 1.5      # = step_media.CLIP_TIMING["cutaway"]["min_duration"] (a test compares; this module does not import step_media)


def _clip_slot_ok(ctx: dict, store, review: dict, proposal, slot: str) -> bool:
    """True when the block that draws this slot is the one that can draw a clip (V9b-5c): the proposal entry whose params hold the slot, else the review's added layout."""
    root, implementation = store.root(), store.renderer()
    for bucket in ("layouts", "overlays"):
        for entry in (proposal or {}).get(bucket) or []:
            params = entry.get("params") if isinstance(entry, dict) else None
            for name, value in (params or {}).items():
                if value == slot:
                    return name == media_animation.CLIP_PARAM and media_animation.clip_block_ok(root, implementation, entry.get("block"), entry.get("preset"))
    for a in review.get("animations") or []:
        if a.get("id") == slot and "asset_param" in a:
            return a["asset_param"] == media_animation.CLIP_PARAM and media_animation.clip_block_ok(root, implementation, a.get("block"), a.get("preset"))
    return False


def _picked(found: dict, review: dict, store_kinds: list, cfg=None, clip_ok=None, current=None) -> tuple:
    """(picks, without): `picks` is [(slot row, chosen candidate)], `without` the ids of the slots left with no picture, in the set's order. Rule 1: a row with a pick needs a pick
    that is one of its candidates, and a clip needs an engine that draws clips and a slot that a cutaway draws (`clip_ok`, V9b-5c). Rule 2: a row with no pick that has no candidates, or is no longer a stock slot (`current` is the set
    of slot ids that are; None means every row is), is left without a picture: it is not fetched and the step renders it as the person's choice. Rule 3: a row with no pick that has
    candidates and is still a stock slot is a missing pick (`no_pick`). With no pick at all, `no_pick`."""
    out, missing, without = [], [], []
    for row in found["slots"]:
        pick = review["slot_assets"].get(row["slot"])
        if not pick:
            if not row["candidates"] or (current is not None and row["slot"] not in current):
                without.append(row["slot"])
            else:
                missing.append(row["slot"])
            continue
        chosen = next((c for c in row["candidates"] if c["pick"] == pick), None)
        if chosen is None:
            missing.append(row["slot"])
            continue
        if chosen["kind"] == "clip" and "clip" not in store_kinds:
            raise _fail("clip_not_drawn", phrases.text("VID_STOCK_CLIP_NOT_DRAWN", cfg))
        if chosen["kind"] == "clip" and clip_ok is not None and not clip_ok(row["slot"]):
            raise _fail("clip_block", phrases.text("VID_STOCK_CLIP_BLOCK", cfg))
        out.append((row, chosen))
    if missing:
        raise _fail("no_pick", "every slot needs a pick before the files are fetched; no pick for: " + ", ".join(missing))
    if not out:
        raise _fail("no_pick", "no slot has a pick: pick a candidate for at least one slot")
    return out, without


def video_media_fetch_picks(project: str, task_id, channel=None) -> dict:
    """Fetch the full file of each pick, have the renderer normalise it, and delete the previews and the unpicked files. Answers {"assets": [{"slot", "pick", "source",
    "kind", "licence", "width", "height"}], "sheet": "sheet.png", "message"}. The approval, if there was one, is void."""
    _channel("video-media-fetch-picks", channel)
    ctx = core.context(project)
    task, rid, state = _task(ctx, task_id)
    _at_review(ctx, task, state)
    store = ops_step_seams.MediaStore(ctx)
    review, proposal = _read_review(store, rid)
    data_dir, cfg = ctx["cfg"]["data_dir"], ctx["cfg"]
    try:
        found = media_stock.read_doc(data_dir, rid, media_stock.SET)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    if found is None or found.get("task") != task_id or not isinstance(found.get("slots"), list):
        raise _fail("no_set", "find the media first (video-media-find)")
    root = ctx["root"]
    picks, without = _picked(found, review, media_animation.asset_kinds(store.root(), store.renderer()), cfg,
                             clip_ok=lambda s: _clip_slot_ok(ctx, store, review, proposal, s),
                             current={s["slot"] for s in media_stock.stock_slots(review, proposal)})      # a clip is refused here, before any source is asked
    accepted = _need_sources(ctx) if any(c["licence"] != media_stock.UNVERIFIED for _, c in picks) else []      # the acceptance is asked again, for the kinds of source the picks come from: a source whose terms changed since the find is a new item the person has not accepted
    if any(c["licence"] == media_stock.UNVERIFIED for _, c in picks):
        _web_ready(ctx)
    names = media_stock.sources_of(cfg)
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
    fps = None
    if any(c["kind"] == "clip" for _, c in picks):      # a clip is normalised to the edit list's rate, so the engine draws it as it is (V9b-5c)
        fps = ops_media_edit._json(store, rid, ops_media_edit.PROPOSAL_EDL, default={}).get("fps")
        if type(fps) is not int or not 24 <= fps <= 60:
            raise _fail("engine_refused", "the edit list's frame rate cannot be read")
    try:
        done = _sheet(ctx, "full", items, path, fps)
    except core.OpsError:      # the picture was refused: nothing stays fetched, the set is back to its candidates, and the person picks again
        try:
            media_stock.remove_where(data_dir, rid, lambda n: n.startswith("full-") or n.startswith(".work") or n == media_stock.QUARANTINE)
            media_stock.write_doc(data_dir, rid, media_stock.SET, dict(found, phase="found", assets=[], credits=[], credit_of={}))
        except media_stock.StockError:
            pass
        raise
    rows = {(a.get("row"), a.get("col")): a for a in done.get("assets") or [] if isinstance(a, dict)}
    if done.get("ok") is not True or set(rows) != set(items) or done.get("sheet") != "sheet.png" or done.get("mode", "full") != "full":
        raise _fail("engine_refused", "the renderer's files are not what was asked for")
    assets, moves = [], {"sheet.png": media_stock.SHEET}
    for row, chosen in picks:
        slot = row["slot"]
        a = rows[(slot, 1)]
        name, digest, kind, seconds = a.get("file"), a.get("sha256"), chosen["kind"], a.get("seconds", 0)
        if not (isinstance(name, str) and media_stock.ASSET_FILE.fullmatch(name) and isinstance(digest, str) and media_stock.SHA256.fullmatch(digest)
                and name == media_stock.asset_name({"sha256": digest, "kind": kind}) and type(a.get("width")) is int and type(a.get("height")) is int and a["width"] > 0 and a["height"] > 0
                and a.get("source_sha256") == fetched[slot][1] and a.get("kind", "image") == kind
                and (seconds == 0 if kind == "image" else isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and 0 < seconds <= media_stock.CLIP_SECONDS_MAX + 0.1)):
            raise _fail("engine_refused", "the renderer's files are not what was asked for")
        if kind == "clip" and seconds < CLIP_MIN_DURATION + 3.0 / fps:      # too short for a cutaway: the set is back to its candidates, as an asset-sheet refusal leaves it
            try:
                media_stock.remove_where(data_dir, rid, lambda n: n.startswith("full-") or n.startswith(".work") or n == media_stock.QUARANTINE)
                media_stock.write_doc(data_dir, rid, media_stock.SET, dict(found, phase="found", assets=[], credits=[], credit_of={}))
            except media_stock.StockError:
                pass
            raise _fail("clip_too_short", phrases.text("VID_STOCK_CLIP_SHORT", cfg, seconds=f"{math.ceil((CLIP_MIN_DURATION + 3.0 / fps) * 10) / 10:.1f}"))
        moves[name] = name
        got = fetched[slot][2]
        data = media_stock.source_data(root, chosen["source"]) or {}
        assets.append({"slot": slot, "show": row["show"], "search": row["search"], "source": chosen["source"], "item": chosen["item"], "kind": chosen["kind"],
                       "licence": chosen["licence"], "licence_url": _licence_url(root, chosen["source"], chosen["licence"]),
                       "source_link": _source_link(root, chosen["source"]),
                       "terms_read_on": data.get("terms_read_on") if isinstance(data.get("terms_read_on"), str) else None,
                       "author": chosen["author"] or got.get("author") or "", "title": chosen["title"], "page": chosen["page"], "licence_claim": chosen.get("licence_claim") or "",
                       "sha256": digest, "width": a["width"], "height": a["height"],
                       "seconds": round(min(float(seconds), media_stock.CLIP_SECONDS_MAX), 3) if kind == "clip" else chosen["seconds"], "unverified": chosen["licence"] == media_stock.UNVERIFIED})
    try:
        media_stock.adopt(data_dir, rid, scratch, moves)
        media_stock.remove_where(data_dir, rid, lambda n: n.startswith("prev-") or n == media_stock.SHEET_PREVIEW)      # the previews and the preview sheet go now
        found = dict(found, phase="fetched", assets=assets, credits=media_stock.credits_of(assets), fetched_at=media_stock.now_stamp(),
                     credit_of={a["slot"]: media_stock.credit_line(a) for a in assets if a["licence"] in media_stock.LICENCES_CREDIT},
                     **({"clip_fps": fps} if fps is not None else {}))
        media_stock.write_doc(data_dir, rid, media_stock.SET, found)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    _scan_set(ctx, data_dir, rid, assets)      # P9-a: text and QR codes, in a container of its own; it fails alone and refuses nothing
    message = "Check the pictures, then approve the media set."
    if any(a["kind"] == "clip" for a in assets):
        message += " " + phrases.text("VID_STOCK_CLIP_TRIM", cfg, max=int(media_stock.CLIP_SECONDS_MAX))
    if without:
        message += " " + phrases.text("VID_STOCK_NO_PICTURE", cfg, slots=", ".join(without))
    return {"assets": [{k: a[k] for k in ("slot", "source", "kind", "licence", "width", "height", "seconds")}
                       | {"pick": f"{a['source']}:{a['item']}", "file": None if a["kind"] == "clip" else media_stock.asset_name(a)}
                       for a in assets],
            "sheet": media_stock.SHEET, "provided": _provided(assets, cfg), "without_picture": without, "message": message, "scan": _scan_report(ctx, rid, assets)}


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
            got = media_stock.file_facts(data_dir, rid, media_stock.asset_name(a))
            if got is None or got[0] != a["sha256"]:
                raise _fail("asset_changed", "a picture of the set is not the file that was made: fetch the picks again")
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    return found


def _own_given(approved, document: dict, task_id) -> dict:
    """{slot: the approval of its own} for the `unverified` assets of the set document that have one in `approved.json`: it must be bound to this task and to the sha256 of that asset."""
    given = approved.get("unverified") if isinstance(approved, dict) and isinstance(approved.get("unverified"), dict) else {}
    out = {}
    for a in document["assets"]:
        if a["unverified"] and isinstance(given.get(a["slot"]), dict) and given[a["slot"]].get("sha256") == a["sha256"] and given[a["slot"]].get("task") == task_id:
            out[a["slot"]] = given[a["slot"]]
    return out


def video_media_approve(project: str, task_id, hash=None, channel=None) -> dict:      # noqa: A002  (the flag is --hash)
    """The media set, for the person to read and approve. Without `hash`: {"approved": whether the current set is, "set": the set document, "sha256", "credits", "needs_own_approval":
    the slots of the assets that need one of their own (a licence nobody checked) and have none yet, "own_approved": the slots that have it}. With `hash` equal to the set's current
    hash: `approved.json` is written, the previews, the full files and the quarantine are deleted, the credits record is written, and {"approved": True, "sha256", "credits"} is
    answered; an approval of the same set that is already there keeps the own approvals it holds (V9b-3b). A stale hash is refused (`stale_hash`)."""
    _channel("video-media-approve", channel)
    ctx = core.context(project)
    task, rid, state = _task(ctx, task_id)
    _at_review(ctx, task, state)
    data_dir, cfg = ctx["cfg"]["data_dir"], ctx["cfg"]
    found = _fetched_set(ctx, task_id, rid)
    document = media_stock.set_document(found)
    digest = media_stock.set_hash(document)
    try:
        existing = media_stock.read_doc(data_dir, rid, media_stock.APPROVED)
        current = media_stock.approval_matches(found, existing)
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    own = _own_given(existing, document, task_id) if current else {}
    needs = [a["slot"] for a in document["assets"] if a["unverified"] and a["slot"] not in own]
    if hash is None:
        return {"approved": current, "set": document, "sha256": digest, "credits": document["credits"], "needs_own_approval": needs, "own_approved": sorted(own),
                "provided": _provided(found["assets"], cfg), "credit_heading": phrases.text("VID_STOCK_CREDIT", cfg), "scan": _scan_report(ctx, rid, found["assets"])}
    if not (isinstance(hash, str) and media_stock.SHA256.fullmatch(hash)):
        raise core.OpsError("the hash is 64 lowercase hexadecimal characters", 2)
    if hash != digest:
        raise _fail("stale_hash", f"the set is not the one that hash names; read it again (current sha256 {digest})")
    names = sorted(media_stock.sources_of(cfg))
    try:
        shown = media_stock.scan_digest(media_stock.read_scan(data_dir, rid))      # what the person was shown (an audit; the step kind never reads it)
    except media_stock.StockError:
        shown = None
    record = {"hash": digest, "at": media_stock.now_stamp(), "task": task_id, "sources": names, "unverified": own, "scan": shown,      # the same set approved again keeps what was approved file by file; a new set starts with none
              "assets": [{k: a[k] for k in ("slot", "sha256", "source", "item", "licence")} for a in document["assets"]]}
    try:
        media_stock.write_doc(data_dir, rid, media_stock.APPROVED, record)
        keep = {media_stock.asset_name(a) for a in document["assets"]}
        media_stock.clear_candidates(data_dir, rid, keep=keep | {media_stock.SHEET})
        media_stock.write_credits(data_dir, task_id, media_stock.credits_record(found, document, rid))
    except media_stock.StockError as e:
        raise _stock_error(e) from None
    return {"approved": True, "sha256": digest, "credits": document["credits"], "needs_own_approval": needs, "own_approved": sorted(own), "provided": _provided(found["assets"], cfg),
            "credit_heading": phrases.text("VID_STOCK_CREDIT", cfg)}


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
