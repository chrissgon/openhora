#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operation `video-media-scan-explain` (package P9-a3, the maintainer's answer to P9-3, limit L83): the one route by which the text a scan read from a picture leaves this computer.

  video_media_scan_explain(project, task_id, confirm=False, channel=None)
        without `confirm`: what would be sent and to whom, nothing sent: the slots, the lines the scan read, the QR codes' hosts, schemes and texts, and the model that would run (and its provider);
        the slots left out and why. With it: one run of the skill SKILL on the lines (a model with no tool and no web, no file of the project), its answer read back and checked twice, and the findings kept
        in the stock folder's `scan-explained.json` beside `scan.json` and answered for the page, which shows them as "not checked".

The person presses the button for one media set at a time; there is no consent word (decision P9-3 (a)). What code decides, in this order, before anything runs: the video waits at the caption review; the
set is fetched; the scan holds something to explain; the source of each file is a stock or web source (a file whose source has no licence tier is left out, whatever it holds: a future upload source of the
person's own files never reaches a model); the skill is a folder of this checkout that requires nothing and has no side effect; the routed model. The prompt is rendered here from the slot ids, the
lines and the QR items only, each checked again: never a picture, a frame, the slot's search words or anything of the recording. The run carries no file of the project and has no web. Its answer is a file
the run wrote; it is read without following a link, at most 64 KiB, copied into a scratch folder and checked by the skill's own script (run isolated, runtime/isolated.py), with the lines that were sent as
the grounding, and again here by the same rules; either failing refuses the file whole. The operation is class G (internal, never served in words), on the terminal and the page, never on the local
network's socket (runtime/operations.py `LAN_REFUSED_OPS`), messaging or the MCP mode. A run row holds a neutral line, never a quoted text. The skill has no lab evidence until the batched event, so the
run is supervised and the page says so.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import captions  # noqa: E402
import isolated  # noqa: E402
import lab  # noqa: E402
import media_stock  # noqa: E402
import ops_cancel  # noqa: E402
import ops_contained  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media_stock  # noqa: E402
import ops_media_websearch  # noqa: E402
import ops_runs  # noqa: E402
import phrases  # noqa: E402
import skill_meta  # noqa: E402

SKILL = "mkt-video-media-explain"
CHANNELS = ops_media_stock.CHANNELS
NEUTRAL = "media text explanation"      # the text of the request a run makes: the lines are never in the store
ANSWER = (".workbench-local", "video", "scan-explained.json")
ANSWER_LIMIT = 64 * 1024
CHECKER = "check_explained.py"
CHECK_TIMEOUT = 30
EXPLAIN_TIMEOUT = 300      # validity: a run must end
EXPLAIN_MAX_COST_USD = 0.6      # validity: a run is bounded in money (the figure of a web search's default)
LANGUAGES = {"en": "English", "pt-BR": "Brazilian Portuguese"}      # the language the explanations are asked in; a tag with no entry gets English
PHRASE_FIELDS = frozenset({"slot", "model", "count"})      # S4: the only fields a sentence of this operation is built from; a line the scan read is never one of them (L82, L83)
PHRASE_KEYS = ("VID_SCAN_EXPLAIN_BUTTON", "VID_SCAN_EXPLAIN_PREVIEW", "VID_SCAN_EXPLAIN_CONFIRM", "VID_SCAN_EXPLAIN_LEFT_OUT", "VID_SCAN_EXPLAIN_NOTHING", "VID_SCAN_EXPLAIN_FAILED",
               "VID_SCAN_EXPLAIN_BY", "VID_SCAN_EXPLAIN_SUPERVISED") + tuple(ops_media_stock.CONCERN_PHRASE.values())
LEFT_OUT_REASONS = ("source_not_stock",)
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _fail(code: str, text: str, status: int = 1) -> "core.OpsError":
    return core.OpsError(f"{code}: {text}", status)


# --- what is sent -----------------------------------------------------------------------------------------------------------------------------


def _grounded(item: dict) -> list:
    """The strings of one slot a quote may be: its text lines, and a QR code's host, scheme or text."""
    return list(item["lines"]) + [q.get("host") or q.get("scheme") or q.get("text") for q in item["qr"]]


def _check_sent(items: list) -> None:
    """Every value that would be sent, checked again: the slot id, each line and QR text as one cleaned line of the bounds the scan keeps, each host and scheme in its closed form. `explain_invalid` otherwise,
    with nothing run."""
    clean = lambda text, bound: isinstance(text, str) and text and len(text) <= bound and ops_media_stock._text(text, bound) == text      # noqa: E731
    for it in items:
        ok = (isinstance(it["slot"], str) and captions.SLOT_ID.fullmatch(it["slot"]) and len(it["lines"]) <= media_stock.SCAN_LINES_MAX and len(it["qr"]) <= media_stock.SCAN_QR_MAX
              and all(clean(line, media_stock.SCAN_LINE_MAX) for line in it["lines"]))
        for q in it["qr"]:
            ok = ok and ((q["kind"] == "link" and isinstance(q.get("host"), str) and media_stock.SCAN_HOST.fullmatch(q["host"]) is not None)
                         or (q["kind"] == "action" and q.get("scheme") in media_stock.SCAN_SCHEMES)
                         or (q["kind"] == "text" and clean(q.get("text"), media_stock.SCAN_QR_TEXT_MAX)))
        if not (ok and (it["lines"] or it["qr"])):
            raise _fail("explain_invalid", "a slot's id, a line or a QR code item is not in the form that may be sent")


def _render_prompt(items: list, language: str) -> str:
    """The text of the run, in the form the skill was measured on (the first case of its eval file, which a test compares byte for byte): one sentence, the language, then one sentence group per slot,
    joined by a space. Only the slot ids, the lines and the QR items are in it (`_check_sent` has checked them); each line is written as a JSON string, so a quotation mark in a line cannot end it."""
    parts = ["Explain the text found in these pictures of a short video.", f"Write each explanation in {language}."]
    for it in items:
        group = ["Slot `%s`:" % it["slot"]]
        if it["lines"]:
            group.append("text lines [%s]." % ", ".join(json.dumps(line, ensure_ascii=False) for line in it["lines"]))
        for q in it["qr"]:
            group.append("QR code opening a link on host %s." % json.dumps(q["host"]) if q["kind"] == "link" else "QR code starting an action, scheme %s." % json.dumps(q["scheme"]) if q["kind"] == "action"
                         else "QR code holding text %s." % json.dumps(q["text"], ensure_ascii=False))
        parts.append(" ".join(group))
    return " ".join(parts)


def _scope() -> dict:
    """The skill's declarations, or OpsError: a folder of this checkout that requires nothing and has no side effect."""
    try:
        meta = skill_meta.declared(os.path.join(core.ROOT, "skills", SKILL))
    except skill_meta.SkillError:
        raise core.OpsError("the media text explanation skill is not in this checkout", 3) from None
    if meta["requires"] or meta["side_effects"]:
        raise core.OpsError("the media text explanation skill declares a requirement or a side effect", 3)
    return meta


def _shown(items: list) -> list:
    """What the page and the terminal list as sent: the slot, the lines and the QR items, as the scan kept them (this computer's own page and terminal only)."""
    return [{"slot": it["slot"], "lines": list(it["lines"]), "qr": [dict(q) for q in it["qr"]]} for it in items]


# --- the read-back ----------------------------------------------------------------------------------------------------------------------------


def _read_findings(parsed, items: list) -> dict:
    """{sha256: [finding]} from an answer document parsed from a run's file, by the rules of the skill's script again, in code: the shape, exactly the slots that were sent, the closed words, the bounds, no web
    address in an explanation and every quote one of the strings that were sent for its slot. `core.OpsError` `explain_invalid` for the first rule broken, with nothing of the text in the message."""
    def bad():
        raise _fail("explain_invalid", "the explanation file breaks a rule")
    if not (isinstance(parsed, dict) and parsed.get("schema_version") == 1 and set(parsed) <= {"schema_version", "slots", "open"} and isinstance(parsed.get("slots"), list)
            and isinstance(parsed.get("open", []), list) and all(isinstance(o, dict) and o == {"code": "nothing_to_explain"} for o in parsed.get("open", []))):
        bad()
    by_slot = {it["slot"]: it for it in items}
    out, seen = {}, set()
    for row in parsed["slots"]:
        if not (isinstance(row, dict) and set(row) == {"slot", "findings"} and isinstance(row["slot"], str) and row["slot"] in by_slot and row["slot"] not in seen
                and isinstance(row["findings"], list) and 1 <= len(row["findings"]) <= media_stock.EXPLAIN_FINDINGS_MAX):
            bad()
        seen.add(row["slot"])
        allowed, found = _grounded(by_slot[row["slot"]]), []
        for f in row["findings"]:
            if not (isinstance(f, dict) and set(f) == {"source", "quote", "concern", "explanation"} and f["source"] in media_stock.EXPLAIN_SOURCES and f["concern"] in media_stock.EXPLAIN_CONCERNS
                    and isinstance(f["quote"], str) and isinstance(f["explanation"], str) and 1 <= len(f["quote"]) <= media_stock.EXPLAIN_QUOTE_MAX
                    and 1 <= len(f["explanation"]) <= media_stock.EXPLAIN_TEXT_MAX and "://" not in f["explanation"] and f["quote"] in allowed
                    and ops_media_stock._text(f["quote"], media_stock.EXPLAIN_QUOTE_MAX) == f["quote"] and ops_media_stock._text(f["explanation"], media_stock.EXPLAIN_TEXT_MAX)):
                bad()
            found.append({"source": f["source"], "quote": f["quote"], "concern": f["concern"], "explanation": ops_media_stock._text(f["explanation"], media_stock.EXPLAIN_TEXT_MAX)})      # the explanation is cleaned, a quote is exact
        out[by_slot[row["slot"]]["sha256"]] = found
    if seen != set(by_slot):
        bad()
    return out


def _check_with_script(copy: str, task_file: str, slots: list) -> bool:
    """The skill's own checker on the copy, run isolated (runtime/isolated.py: `-I -E -s`, a scrubbed environment, no shell), with the lines that were sent as the grounding: `ok` must be true in what it printed."""
    try:
        script = isolated.skill_script(core.ROOT, SKILL, CHECKER)
        if not os.path.isfile(script):
            return False
        done = isolated.run_script(script, ["--file", copy, "--task-file", task_file] + [a for slot in sorted(slots) for a in ("--slot", slot)], cwd=os.path.dirname(copy), timeout=CHECK_TIMEOUT)
        answer = json.loads(done.stdout)
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError):
        return False
    return isinstance(answer, dict) and answer.get("ok") is True


def _read_back(ctx: dict, rid: str, cwd: str, items: list) -> dict:
    """The findings a run wrote, checked twice (the skill's script on a copy, with the lines that were sent as the grounding, then `_read_findings`); either failing refuses the file whole
    (`explain_invalid`, the sentence VID_SCAN_EXPLAIN_FAILED). The bytes are read once; the copy and the task file are written 0600 into a scratch folder of the stock folder that is removed here."""
    cfg, data_dir = ctx["cfg"], ctx["cfg"]["data_dir"]
    refuse = lambda: _fail("explain_invalid", phrases.text("VID_SCAN_EXPLAIN_FAILED", cfg))      # noqa: E731
    data = ops_media_websearch._read_file(cwd, ANSWER, ANSWER_LIMIT)
    if data is None:
        raise refuse()
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise refuse() from None
    scratch = None
    try:
        scratch, path = media_stock.make_scratch(data_dir, rid)
        for name, body in (("explained.json", data), ("task.json", json.dumps({"slots": {it["slot"]: _grounded(it) for it in items}}, ensure_ascii=False).encode("utf-8"))):
            out = os.open(os.path.join(path, name), os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600)
            with os.fdopen(out, "wb") as f:
                f.write(body)
        if not _check_with_script(os.path.join(path, "explained.json"), os.path.join(path, "task.json"), [it["slot"] for it in items]):
            raise refuse()
        try:
            return _read_findings(parsed, items)
        except core.OpsError:
            raise refuse() from None
    except media_stock.StockError as e:
        raise ops_media_stock._stock_error(e) from None
    except OSError:
        raise refuse() from None
    finally:
        if scratch is not None:
            try:
                media_stock.remove_where(data_dir, rid, lambda n: n == scratch)
            except media_stock.StockError:
                pass


def _keep(ctx: dict, rid: str, assets: list, found: dict, model: str) -> None:
    """The findings into `scan-explained.json`, keyed by each file's sha256 (a later explanation of the same file replaces its entry; the entries of files no longer in the set go)."""
    data_dir = ctx["cfg"]["data_dir"]
    try:
        before = media_stock.read_explained(data_dir, rid)["assets"]
    except media_stock.StockError:
        before = {}
    keep = {a["sha256"] for a in assets}
    entries = {d: f for d, f in before.items() if d in keep and d not in found}
    entries.update(found)
    try:
        media_stock.write_doc(data_dir, rid, media_stock.EXPLAINED, {"version": media_stock.EXPLAINED_VERSION, "model": model, "assets": entries, "at": media_stock.now_stamp()})
    except media_stock.StockError as e:
        raise ops_media_stock._stock_error(e) from None


# --- the operation ----------------------------------------------------------------------------------------------------------------------------


def video_media_scan_explain(project: str, task_id, confirm=False, channel=None) -> dict:
    """Explain the text a scan found in the pictures of this video's media set. Without `confirm` it sends nothing and answers {"confirmed": False, "slots": what would be sent, "left_out", "model",
    "autonomy", "message": the sentence that says what goes to whom, "confirm": the label of the button that sends it}; with it, {"confirmed": True, "left_out", "explained": the report of the page}.
    core.OpsError for every refusal, with nothing kept. The text is shown on this computer's own page and the terminal, in fields of their own."""
    ops_media_stock._channel("video-media-scan-explain", channel)
    ctx = core.context(project)
    if not (type(confirm) is bool or confirm is None):
        raise core.OpsError("confirm is true or false", 2)
    cfg = ctx["cfg"]
    task, rid, state = ops_media_stock._task(ctx, task_id)      # 1
    ops_media_stock._at_review(ctx, task, state)
    found = ops_media_stock._fetched_set(ctx, task_id, rid)      # 2
    try:
        items = media_stock.explain_items(found["assets"], media_stock.read_scan(cfg["data_dir"], rid))
    except media_stock.StockError as e:
        raise ops_media_stock._stock_error(e) from None
    nothing = lambda: _fail("nothing_to_explain", phrases.text("VID_SCAN_EXPLAIN_NOTHING", cfg))      # noqa: E731
    if not items:      # 3
        raise nothing()
    sent = [it for it in items if media_stock.tier_of(core.ROOT, it["source"]) in media_stock.TIERS]      # 4: a stock or web source only
    left_out = [{"slot": it["slot"], "reason": "source_not_stock", "message": phrases.text("VID_SCAN_EXPLAIN_LEFT_OUT", cfg, slot=it["slot"])} for it in items if it not in sent]
    if not sent:
        raise nothing()
    _check_sent(sent)
    _scope()      # 5
    meta, keys, routing = ops_contained.routed(ctx, SKILL)      # 6
    prompt = ops_runs.task_prompt(_render_prompt(sent, LANGUAGES.get(phrases.tag(cfg), "English")), "", [])
    if not confirm:      # 7
        return {"confirmed": False, "slots": _shown(sent), "left_out": left_out, "model": routing["model"], "autonomy": routing["autonomy"], "supervised": routing["autonomy"] != "proven",
                "message": phrases.text("VID_SCAN_EXPLAIN_PREVIEW", cfg, model=routing["model"]), "confirm": phrases.text("VID_SCAN_EXPLAIN_CONFIRM", cfg),
                "supervised_note": phrases.text("VID_SCAN_EXPLAIN_SUPERVISED", cfg)}
    try:
        identity = lab.skill_identity(SKILL)
    except lab.LabError:
        raise _fail("explain_failed", phrases.text("VID_SCAN_EXPLAIN_FAILED", cfg)) from None
    with core._route_lock(cfg):      # RunBusy: one conversation model call per project at a time
        ops_runs._recover(ctx, holding_route=True)
        number, dest = ops_contained._contained_folder(cfg)
        prepared_dir = os.path.join(cfg["data_dir"], core.PREPARED_DIR, f"contained-{number}")
        try:
            with core._claim_lock(cfg):
                started = core._stored(ctx, ctx["store"].answer_run_start, skill=SKILL, model=routing["model"], adapter=routing["adapter"], skill_version=identity["version"],
                                       skill_sha256=identity["content_sha256"], billing=routing["billing"] or "unknown", autonomy=routing["autonomy"], title=ctx["store"].ANSWER_TITLE,
                                       text=NEUTRAL, web=False)
            return _run(ctx, rid, found, sent, left_out, meta, keys, routing, prompt, started, dest, prepared_dir)
        finally:
            shutil.rmtree(prepared_dir, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)      # this folder held the lines of a picture and what a model said about them


def _run(ctx, rid, found, sent, left_out, meta, keys, routing, prompt, started, dest, prepared_dir) -> dict:
    cfg, store = ctx["cfg"], ctx["store"]
    request_id, run_id = started["request_id"], started["run_id"]

    def finish(**fields):
        done = core._stored(ctx, store.answer_run_finish, run_id, run_dir=None, **fields)
        if done["cancelled"]:
            raise _fail("explain_cancelled", phrases.text("ASK_CANCELLED", cfg))

    def fail(kind: str, reason: str, counts=None, image=None, reported=None):
        finish(status="failed", failure=kind, attempts=(counts or {}).get("attempts", 0), image_digest=image, error=ops_runs._note(reason), **ops_runs._reported_usage(reported, routing))
        raise _fail("explain_failed", phrases.text("VID_SCAN_EXPLAIN_FAILED", cfg))

    try:
        # no file of the project enters this run: the skill's declared artifacts are emptied, so that the copy the run sees has none (the answer file is written in the run's own folder)
        result = ops_contained.execute(ctx, SKILL, dict(meta, inputs=[], outputs=[], updates=[]), keys, routing, prompt, timeout=EXPLAIN_TIMEOUT, dest=dest, prepared_dir=prepared_dir,
                                       max_cost=EXPLAIN_MAX_COST_USD, around=ops_cancel.watch(ctx, request_id), open_web=False)
    except core.OpsError as e:
        fail("internal", "the explanation environment is off" if getattr(e, "lab_kind", None) == "docker" else "the run could not be made")
    except Exception as e:      # the run row never stays `running`; the error is recorded by its type only, never its text (it can hold a line of a picture)
        print(f"media text explanation: internal error {type(e).__name__}", file=sys.stderr)
        fail("internal", f"internal error {type(e).__name__}")
    counts, timing = result["counts"], result["timing"]
    if result["status"] != "ok":
        failure = result["failure"]
        fail(failure["kind"], f"the run failed ({failure['kind']})", counts, result["image_digest"], result.get("reported"))      # the lab's reason is never kept: it could hold a line of a picture
    number_of = lambda key, kind: timing.get(key) if isinstance(timing.get(key), kind) and not isinstance(timing.get(key), bool) else None      # noqa: E731
    every = ops_runs._reported_usage(lab.reported_usage(dest), routing)
    try:
        findings = _read_back(ctx, rid, result["cwd"], sent)
        failed = None
    except core.OpsError as e:
        findings, failed = None, e
    finish(status="ok", attempts=counts["attempts"], cost_usd=every.get("cost_usd", number_of("cost_usd", (int, float)) if routing["billing"] == "metered" else None),
           tokens=every.get("tokens", number_of("total_tokens", int)), duration_ms=number_of("duration_ms", int), skill_loaded=ops_runs._skill_loaded(timing, SKILL),
           image_digest=result["image_digest"], redactions=ops_runs._count(counts.get("redactions")))
    if failed is not None:
        raise failed
    _keep(ctx, rid, found["assets"], findings, routing["model"])
    return {"confirmed": True, "left_out": left_out, "supervised": routing["autonomy"] != "proven", "supervised_note": phrases.text("VID_SCAN_EXPLAIN_SUPERVISED", cfg),
            "explained": ops_media_stock._explained_report(ctx, rid, found["assets"])}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
