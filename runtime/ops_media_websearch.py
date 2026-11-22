#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations of a video's pictures found on the open web (package V9b-3b, decisions D6 to D8 of the V9b spec and its amendment of 2026-11-22): `video-media-websearch` and
`video-media-approve-asset`. A file found on the web has no licence the workbench can check, so it has its own approval, after a copyright warning, on top of the approval of the set:

  video_media_websearch(project, task, confirm=False, channel=None)   without `confirm`: the words that would be sent and nothing else. With it: one run of the skill SKILL on the open network
                                                                      (a model with web search, the words of the slots and no file of the project), its candidates file read back and checked twice,
                                                                      one small preview of each candidate fetched by the open-web provider into the quarantine, and the candidates merged into the
                                                                      media set (`set.json`, phase `found`) beside the licensed ones. The run folder is removed.
  video_media_approve_asset(project, task, slot, sha256, confirm=None, channel=None)
                                                                      the stronger approval of one fetched file that nobody checked: without `confirm` it shows the
                                                                      warning, the host, the page and the claim; with the first 12 hex digits of the file's sha256 it writes
                                                                      `approved.json["unverified"][slot]` = {sha256, task, at, channel}.

What code decides, in this order, before anything runs (the pattern of runtime/ops_research.py): the video waits at the caption review; the open-web source is on and accepted; the slots (at most six,
a clip slot is not sent while the engine draws no clips); the skill is a folder of this checkout that declares `search:web` and no side effect; the routed pair was measured with the web; the
day's count is under the bound of `media.websearch`; and, without `--confirm`, nothing more. The run carries no file of the project and no standing instruction: its prompt is rendered here from the
slot ids, the kinds and the search words, each checked again. Its answer is a file the run wrote; it is read without following a link, at most 64 KiB, copied into a scratch folder and checked by the
skill's own script (run isolated, runtime/isolated.py) and again by `media_stock.read_web_candidates`; either failing refuses the file whole. A URL a model wrote reaches the open-web provider only (by its
closed verbs) and no answer, run row, log or decision body ever holds one beyond its host; the page address is text for the terminal and this computer's own page. The operations are class G
(internal, never served in words), on the terminal and the page, never on the local network's socket (runtime/operations.py `LAN_REFUSED_OPS`), messaging or the MCP mode (limits L78 and L80).

No source is named here: the open-web source is the one whose data file says `unverified`. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import json
import os
import shutil
import stat
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import captions  # noqa: E402
import isolated  # noqa: E402
import lab  # noqa: E402
import media_animation  # noqa: E402
import media_stock  # noqa: E402
import ops_cancel  # noqa: E402
import ops_contained  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media_stock  # noqa: E402
import ops_runs  # noqa: E402
import ops_step_seams  # noqa: E402
import phrases  # noqa: E402
import skill_meta  # noqa: E402

SKILL = "mkt-video-media-search"
CHANNELS = ops_media_stock.CHANNELS
NEUTRAL = "web media search"      # the text of the request a run makes: the words are never in the store
CANDIDATES = (".workbench-local", "video", "web-candidates.json")
CANDIDATES_LIMIT = 64 * 1024
CHECKER = "check_candidates.py"
CHECK_TIMEOUT = 30
PREVIEW_TIMEOUT, PREVIEW_PARALLEL = 40, 4
PREVIEW_BYTES = 4 * media_stock.MIB
PREVIEW_MAX = media_stock.WEB_MAX_TOTAL      # = the open-web provider's PER_VIDEO["previews"] (a test compares)
PREVIEW_TYPES = ("image/png", "image/jpeg")
CLAIM_NOTE = "claimed by the page, not checked"
NOFOLLOW, DIRECTORY = getattr(os, "O_NOFOLLOW", 0), getattr(os, "O_DIRECTORY", 0)


def _fail(code: str, text: str, status: int = 1) -> "core.OpsError":
    return core.OpsError(f"{code}: {text}", status)


def _channel(operation: str, channel) -> None:
    ops_media_stock._channel(operation, channel)


# --- the prompt, the slots and the skill -----------------------------------------------------------------------------------------------------------


def _check_slots(slots) -> None:
    """Every value that would be sent, checked again: the slot id, the kind and the search words (at most six words). `slot_invalid` otherwise, with nothing run."""
    for s in slots:
        words = s["search"]
        if not (isinstance(s["slot"], str) and captions.SLOT_ID.fullmatch(s["slot"]) and s["want"] in captions.WANT_KINDS and isinstance(words, str) and captions.SEARCH.fullmatch(words)
                and len(words.split()) <= captions.SEARCH_WORDS):
            raise _fail("slot_invalid", "a slot's id, kind or search words are not in the form a web search may be sent")


def _render_prompt(slots) -> str:
    """The text of the run, in the form the skill was measured on (the first case of its eval file, which a test compares byte for byte): one sentence, then one per slot, joined by a space. Only
    the slot ids, the kinds and the search words are in it (`_check_slots` has checked them)."""
    parts = ["Find media for this cutaway." if len(slots) == 1 else "Find media for these cutaways of a short video."]
    for s in slots:
        parts.append("Slot `%s`: a %s, search words \"%s\"." % (s["slot"], "picture" if s["want"] == "image" else "clip", s["search"]))
    return " ".join(parts)


def _scope() -> dict:
    """The skill's declarations, or OpsError: a folder of this checkout that requires the web and has no side effect."""
    try:
        meta = skill_meta.declared(os.path.join(core.ROOT, "skills", SKILL))
    except skill_meta.SkillError:
        raise core.OpsError("the web media search skill is not in this checkout", 3) from None
    if not meta["web"] or meta["side_effects"]:
        raise core.OpsError("the web media search skill does not declare the web and no side effect", 3)
    return meta


def _today(ctx: dict) -> int:
    """How many web media searches were started today (local day), whatever their end."""
    rows = core._stored(ctx, ctx["store"].runs_since, ops_runs._midnight_utc())
    return sum(1 for row in rows if row.get("skill") == SKILL and row.get("task_id") == row.get("request_id"))


def _gates(ctx: dict, task_id):
    """What the two operations' first four checks share, in order, with nothing run: (task, recording id, source name)."""
    task, rid, state = ops_media_stock._task(ctx, task_id)
    ops_media_stock._at_review(ctx, task, state)
    return task, rid, ops_media_stock._web_ready(ctx)


# --- the read-back ----------------------------------------------------------------------------------------------------------------------------


def _read_file(cwd: str):
    """The bytes of the candidates file of a run, or None: every step opened without following a link, a regular file, at most CANDIDATES_LIMIT bytes, read once."""
    fd = None
    try:
        fd = os.open(cwd, os.O_RDONLY | DIRECTORY)
        for part in CANDIDATES[:-1]:
            nxt = os.open(part, os.O_RDONLY | DIRECTORY | NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        handle = os.open(CANDIDATES[-1], os.O_RDONLY | NOFOLLOW, dir_fd=fd)
    except (OSError, TypeError):
        if fd is not None:
            os.close(fd)
        return None
    os.close(fd)
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode) or info.st_size > CANDIDATES_LIMIT:
            return None
        with os.fdopen(handle, "rb", closefd=False) as f:
            data = f.read(CANDIDATES_LIMIT + 1)
        return data if len(data) <= CANDIDATES_LIMIT else None
    except OSError:
        return None
    finally:
        os.close(handle)


def _check_with_script(copy: str, sent: dict) -> bool:
    """The skill's own checker on the copy, run isolated (runtime/isolated.py: `-I -E -s`, a scrubbed environment, no shell): `ok` must be true in what it printed."""
    try:
        script = isolated.skill_script(core.ROOT, SKILL, CHECKER)
        if not os.path.isfile(script):
            return False
        done = isolated.run_script(script, ["--file", copy] + [a for slot, kind in sorted(sent.items()) for a in ("--slot", f"{slot}:{kind}")], cwd=os.path.dirname(copy), timeout=CHECK_TIMEOUT)
        answer = json.loads(done.stdout)
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError):
        return False
    return isinstance(answer, dict) and answer.get("ok") is True


def _read_back(ctx: dict, rid: str, cwd: str, sent: dict) -> dict:
    """The candidates a run wrote, checked twice (the skill's script on a copy, then `media_stock.read_web_candidates`); either check failing refuses the file whole (`candidates_invalid`, the
    sentence VID_WEB_FAILED). The bytes are read once; the copy is written 0600 into a scratch folder of the stock folder that is removed here."""
    cfg, data_dir = ctx["cfg"], ctx["cfg"]["data_dir"]
    refuse = lambda: _fail("candidates_invalid", phrases.text("VID_WEB_FAILED", cfg))      # noqa: E731
    data = _read_file(cwd)
    if data is None:
        raise refuse()
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise refuse() from None
    scratch = None
    try:
        scratch, path = media_stock.make_scratch(data_dir, rid)
        copy = os.path.join(path, "candidates.json")
        out = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
        with os.fdopen(out, "wb") as f:
            f.write(data)
        if not _check_with_script(copy, sent):
            raise refuse()
        try:
            return media_stock.read_web_candidates(parsed, sent)
        except media_stock.StockError:
            raise refuse() from None
    except media_stock.StockError as e:
        raise ops_media_stock._stock_error(e) from None
    except OSError:
        raise refuse() from None
    finally:
        if scratch is not None:
            with contextlib.suppress(media_stock.StockError):
                media_stock.remove_where(data_dir, rid, lambda n: n == scratch)


# --- the previews and the candidate records ---------------------------------------------------------------------------------------------------


def _host_flags(cfg: dict) -> list:
    media_cfg = cfg.get("media") or {}
    flags = []
    for host in media_cfg.get(ops_media_stock.REFUSED_HOSTS) or []:
        flags += ["--refuse-host", host]
    for host in media_cfg.get(ops_media_stock.ALLOWED_HOSTS) or []:
        flags += ["--allow-host", host]
    return flags


def _preview(ctx: dict, rid: str, sources, name: str, quarantine: str, row: dict):
    """(candidate, None) or (None, reason) for one candidate of a run: the open-web provider's `preview` verb fetches the thumbnail (else the file itself, an image) into the quarantine; its answer
    is checked against the closed shape, the type, the name (`q-<sha12>.<ext>`), the size and the file's own facts. A refused preview drops its candidate."""
    url = row.get("thumb_url") or row["media_url"]
    flags = ["--kind", "image", "--url", url, "--out", quarantine, "--max-bytes", str(PREVIEW_BYTES), "--allow-unverified"] + _host_flags(ctx["cfg"])
    try:
        done = sources.call(name, "preview", flags, PREVIEW_TIMEOUT)
    except ops_media_stock.Refused:
        return None, "preview"
    file, digest, size = done.get("file"), done.get("sha256"), done.get("bytes")
    if not (done.get("ok") is True and set(done) <= ops_media_stock.KEYS_WEB_FETCH and isinstance(file, str) and media_stock.PROVIDER_FILE.fullmatch(file) and file.startswith("q-")
            and done.get("type") in PREVIEW_TYPES and type(size) is int and 0 < size <= PREVIEW_BYTES and isinstance(digest, str) and media_stock.SHA256.fullmatch(digest)
            and file.startswith("q-" + digest[:12] + ".")):
        return None, "preview"
    try:
        facts = ops_media_stock._facts_at(ctx["cfg"]["data_dir"], rid, file, True)
    except media_stock.StockError:
        return None, "preview"
    if facts != (digest, size):
        return None, "preview"
    page = row["page_url"]
    item = "q-" + digest[:12]
    return {"source": name, "item": item, "pick": f"{name}:{item}", "kind": row["kind"], "licence": media_stock.UNVERIFIED, "author": "",
            "title": ops_media_stock._text(row["title"], ops_media_stock.TEXT), "page": page, "licence_claim": ops_media_stock._text(row["licence_claim"], 200),
            "site_terms": ops_media_stock._text(row.get("site_terms", ""), 200), "resolution": row.get("resolution") or "", "screen_work": row["screen_work"],
            "url": row["media_url"], "page_host": urllib.parse.urlsplit(page).hostname or "", "width": None, "height": None, "seconds": None, "preview": file,
            "preview_in": media_stock.QUARANTINE, "preview_sha256": digest}, None


def _previews(ctx: dict, rid: str, name: str, rows: list) -> tuple:
    """({slot: [candidates]}, refused): up to PREVIEW_MAX previews, PREVIEW_PARALLEL at a time (separate hosts, no shared resource); the same preview bytes in one slot are kept once."""
    quarantine = os.path.join(media_stock.folder_of(ctx["cfg"]["data_dir"], rid), media_stock.QUARANTINE)
    os.makedirs(quarantine, mode=0o700, exist_ok=True)
    sources = ops_media_stock._sources_for(ctx)
    rows = rows[:PREVIEW_MAX]
    with concurrent.futures.ThreadPoolExecutor(max_workers=PREVIEW_PARALLEL) as pool:
        jobs = [pool.submit(_preview, ctx, rid, sources, name, quarantine, row) for row in rows]
        done = [job.result() for job in jobs]
    out, refused = {}, 0
    for row, (got, why) in zip(rows, done):
        if got is None:
            refused += 1
            continue
        slot = out.setdefault(row["slot"], [])
        if all(c["pick"] != got["pick"] for c in slot):
            slot.append(got)
    return out, refused


# --- the operation ----------------------------------------------------------------------------------------------------------------------------


def video_media_websearch(project: str, task_id, confirm=False, channel=None) -> dict:
    """Search the open web for the pictures of the slots of this video. Without `confirm` it sends nothing and answers {"confirmed": False, "slots", "skipped", "message"}; with it, the answer of
    `video-media-find` ({"confirmed": True, "found", "slots", "sheet", "dropped", "message"}) and `skipped`. core.OpsError for every refusal, with nothing kept. The candidates that came from the
    web are shown with what their page claims, as text, and never with the link of the file."""
    _channel("video-media-websearch", channel)
    ctx = core.context(project)
    if not (type(confirm) is bool or confirm is None):
        raise core.OpsError("confirm is true or false", 2)
    cfg = ctx["cfg"]
    task, rid, name = _gates(ctx, task_id)      # 1 and 2
    store = ops_step_seams.MediaStore(ctx)
    review, proposal = ops_media_stock._read_review(store, rid)
    slots = media_stock.stock_slots(review, proposal)      # 3
    if len(slots) > media_stock.MAX_SLOTS:
        raise _fail("too_many_slots", f"at most {media_stock.MAX_SLOTS} slots take a picture from the media set")
    drawn = media_animation.asset_kinds(store.root(), store.renderer())
    sent = [s for s in slots if not (s["want"] == "clip" and "clip" not in drawn)]
    skipped = [{"slot": s["slot"], "want": s["want"], "message": phrases.text("VID_STOCK_CLIP_NOT_DRAWN", cfg)} for s in slots if s not in sent]
    if not sent:
        raise _fail("no_slots", "no slot has search words and the choice stock that the web search can serve: give a slot its words (slot_search) and choose stock for it")
    _check_slots(sent)
    prompt = ops_runs.task_prompt(_render_prompt(sent), "", [])      # every value checked again; an empty task text leaves the plain request
    try:
        _scope()      # 4
    except core.OpsError:
        raise _fail("web_not_built", phrases.text("VID_WEB_NOT_BUILT", cfg)) from None
    meta, keys, routing = ops_contained.routed(ctx, SKILL)      # 5
    if not routing["web"]:
        raise _fail("web_no_web", phrases.text("VID_WEB_NO_WEB", cfg))
    limits = media_stock.websearch_limits(cfg)
    made = _today(ctx)      # 6
    if made >= limits["max_per_day"]:
        raise _fail("web_limit", phrases.text("VID_WEB_LIMIT", cfg, count=made))
    if not confirm:      # 7
        return {"confirmed": False, "slots": sent, "skipped": skipped, "message": phrases.text("VID_WEB_PREVIEW", cfg, words="; ".join(s["search"] for s in sent))}
    try:
        identity = lab.skill_identity(SKILL)
    except lab.LabError:
        raise _fail("web_failed", phrases.text("VID_WEB_FAILED", cfg)) from None
    with core._route_lock(cfg):      # RunBusy: one conversation model call per project at a time
        ops_runs._recover(ctx, holding_route=True)
        number, dest = ops_contained._contained_folder(cfg)
        prepared_dir = os.path.join(cfg["data_dir"], core.PREPARED_DIR, f"contained-{number}")
        try:
            with core._claim_lock(cfg):      # the day's count and the run row are one step
                made = _today(ctx)
                if made >= limits["max_per_day"]:
                    raise _fail("web_limit", phrases.text("VID_WEB_LIMIT", cfg, count=made))
                started = core._stored(ctx, ctx["store"].answer_run_start, skill=SKILL, model=routing["model"], adapter=routing["adapter"], skill_version=identity["version"],
                                       skill_sha256=identity["content_sha256"], billing=routing["billing"] or "unknown", autonomy=routing["autonomy"], title=ctx["store"].ANSWER_TITLE,
                                       text=NEUTRAL, web=True)
            return _run(ctx, rid, name, task_id, slots, sent, skipped, meta, keys, routing, prompt, started, dest, prepared_dir, limits)
        finally:
            shutil.rmtree(prepared_dir, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)      # stricter than research: this folder held pages from the open web


def _run(ctx, rid, name, task_id, slots, sent, skipped, meta, keys, routing, prompt, started, dest, prepared_dir, limits) -> dict:
    cfg, store = ctx["cfg"], ctx["store"]
    request_id, run_id = started["request_id"], started["run_id"]

    def finish(**fields):
        """End the run and its request. A request cancelled meanwhile has the run recorded cancelled: the sentence that says so."""
        done = core._stored(ctx, store.answer_run_finish, run_id, run_dir=None, **fields)
        if done["cancelled"]:
            raise _fail("web_cancelled", phrases.text("ASK_CANCELLED", cfg))

    def fail(kind: str, reason: str, counts=None, image=None, reported=None):
        finish(status="failed", failure=kind, attempts=(counts or {}).get("attempts", 0), image_digest=image, error=ops_runs._note(reason), **ops_runs._reported_usage(reported, routing))
        raise _fail("web_failed", phrases.text("VID_WEB_FAILED", cfg))

    try:
        result = ops_contained.execute(ctx, SKILL, meta, keys, routing, prompt, timeout=limits["timeout_seconds"], dest=dest, prepared_dir=prepared_dir, max_cost=limits["max_cost_usd"],
                                       around=ops_cancel.watch(ctx, request_id), open_web=True)
    except core.OpsError as e:
        fail("internal", "the web search environment is off" if getattr(e, "lab_kind", None) == "docker" else "the run could not be made")
    except Exception as e:      # the run row never stays `running`; the error is recorded by its type only, never its text (it can hold a link)
        print(f"web media search: internal error {type(e).__name__}", file=sys.stderr)
        fail("internal", f"internal error {type(e).__name__}")
    counts, timing = result["counts"], result["timing"]
    if result["status"] != "ok":
        failure = result["failure"]
        fail(failure["kind"], f"the run failed ({failure['kind']})", counts, result["image_digest"], result.get("reported"))      # the lab's reason is never kept: it could hold a link
    number_of = lambda key, kind: timing.get(key) if isinstance(timing.get(key), kind) and not isinstance(timing.get(key), bool) else None      # noqa: E731
    every = ops_runs._reported_usage(lab.reported_usage(dest), routing)
    try:
        found = _read_back(ctx, rid, result["cwd"], {s["slot"]: s["want"] for s in sent})
        failed = None
    except core.OpsError as e:
        found, failed = None, e
    finish(status="ok", attempts=counts["attempts"], cost_usd=every.get("cost_usd", number_of("cost_usd", (int, float)) if routing["billing"] == "metered" else None),
           tokens=every.get("tokens", number_of("total_tokens", int)), duration_ms=number_of("duration_ms", int), skill_loaded=ops_runs._skill_loaded(timing, SKILL),
           image_digest=result["image_digest"], redactions=ops_runs._count(counts.get("redactions")))
    if failed is not None:
        raise failed
    if not found["candidates"]:
        if any(o["code"] == "no_search_tool" for o in found["open"]):
            raise _fail("web_no_web", phrases.text("VID_WEB_NO_WEB", cfg))
        raise _fail("web_nothing", phrases.text("VID_WEB_NOTHING", cfg))
    return _keep(ctx, rid, name, task_id, slots, skipped, found)


def _keep(ctx: dict, rid: str, name: str, task_id, slots: list, skipped: list, found: dict) -> dict:
    """The candidates of a web search into the set, replacing the open-web ones: the licensed candidates of a `found` set with the same words are carried, the quarantine and everything the previous
    approval bound go, the previews are fetched and the set is composed as `video-media-find` composes it."""
    data_dir = ctx["cfg"]["data_dir"]
    try:
        old = media_stock.read_doc(data_dir, rid, media_stock.SET)
    except media_stock.StockError:
        old = None
    per_source = ops_media_stock._carried(ctx, rid, old, task_id, slots, web=False)
    try:
        media_stock.clear_web(data_dir, rid)
        media_stock.void_approval(data_dir, rid)
        media_stock.ensure_folder(data_dir, rid)
    except media_stock.StockError as e:
        raise ops_media_stock._stock_error(e) from None
    got, refused = _previews(ctx, rid, name, found["candidates"])
    per_source[name] = got
    dropped = {"shape": 0, "licence": 0, "preview": refused, "source": 0}
    answer = ops_media_stock._compose(ctx, rid, task_id, slots, per_source, dropped)
    if not sum(len(v) for v in got.values()):
        answer["message"] = phrases.text("VID_WEB_NOTHING", ctx["cfg"])
    return dict(answer, skipped=skipped)


# --- the approval of one file ------------------------------------------------------------------------------------------------------------------


def video_media_approve_asset(project: str, task_id, slot, sha256, confirm=None, channel=None) -> dict:
    """The approval of one fetched file that nobody checked (decision D6). Refused, with nothing written: when the video is not at the review; when no fetched set is there or a file changed; when the
    set is not approved as it stands (`not_approved`); when `slot` is not an unverified asset of the set (`not_unverified`); when `sha256` is not that asset's (`wrong_hash`); when the open-web source is
    off or not accepted. Without `confirm`: {"approved": False, "slot", "sha256", "file", "host", "page", "licence_claim", "licence_claim_note", "screen_work", "warning", "confirm"}; with
    `confirm` (the terminal's `--confirm-digits`) equal to the first 12 hex digits of the sha256 (`wrong_confirm` otherwise): `approved.json["unverified"][slot]` = {sha256, task, at, channel}, answering {"approved": True, "slot",
    "sha256"}. Terminal and page only; never the interpreter, messaging, the MCP mode or the local network's socket."""
    _channel("video-media-approve-asset", channel)
    ctx = core.context(project)
    cfg, data_dir = ctx["cfg"], ctx["cfg"]["data_dir"]
    if not (isinstance(slot, str) and captions.SLOT_ID.fullmatch(slot)) or not (isinstance(sha256, str) and media_stock.SHA256.fullmatch(sha256)):
        raise core.OpsError("the slot is the id of a slot and the sha256 is 64 lowercase hexadecimal characters", 2)
    if confirm is not None and not isinstance(confirm, str):
        raise core.OpsError("confirm is the first 12 hexadecimal digits of the file's sha256", 2)
    task, rid, state = ops_media_stock._task(ctx, task_id)
    ops_media_stock._at_review(ctx, task, state)
    found = ops_media_stock._fetched_set(ctx, task_id, rid)
    try:
        approved = media_stock.read_doc(data_dir, rid, media_stock.APPROVED)
    except media_stock.StockError as e:
        raise ops_media_stock._stock_error(e) from None
    if not media_stock.approval_matches(found, approved):
        raise _fail("not_approved", phrases.text("VID_STOCK_NOT_APPROVED", cfg))
    document = media_stock.set_document(found)
    asset = next((a for a in document["assets"] if a["slot"] == slot and a["unverified"]), None)
    if asset is None:
        raise _fail("not_unverified", "this slot's file is not one that needs an approval of its own")
    if asset["sha256"] != sha256:
        raise _fail("wrong_hash", "that is not the sha256 of this slot's file")
    ops_media_stock._web_ready(ctx)
    if confirm is None:
        row = next((c for r in found.get("slots") or [] if isinstance(r, dict) for c in r.get("candidates") or [] if isinstance(c, dict) and c.get("pick") == f"{asset['source']}:{asset['item']}"), {})
        page = asset.get("page") or ""
        host = (row.get("page_host") if isinstance(row.get("page_host"), str) else "") or urllib.parse.urlsplit(page).hostname or ""
        return {"approved": False, "slot": slot, "sha256": sha256, "file": f"asset-{sha256[:12]}.png", "host": host, "page": page, "licence_claim": asset.get("licence_claim") or "",
                "licence_claim_note": CLAIM_NOTE, "screen_work": bool(row.get("screen_work")), "warning": phrases.text("VID_WEB_WARNING", cfg, host=host, page=page),
                "confirm": f"--confirm-digits {sha256[:12]}"}
    if confirm != sha256[:12]:
        raise _fail("wrong_confirm", "type the first 12 hexadecimal digits of the file's sha256")
    given = dict(approved.get("unverified") if isinstance(approved.get("unverified"), dict) else {})
    given[slot] = {"sha256": sha256, "task": task_id, "at": media_stock.now_stamp(), "channel": channel or "terminal"}
    try:
        media_stock.write_doc(data_dir, rid, media_stock.APPROVED, dict(approved, unverified=given))
    except media_stock.StockError as e:
        raise ops_media_stock._stock_error(e) from None
    return {"approved": True, "slot": slot, "sha256": sha256}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
