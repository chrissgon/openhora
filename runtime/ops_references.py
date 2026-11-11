#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations of the reference videos (package V7b, decision 15): `reference-add`, `reference-video`, `reference-list`, `reference-read` and
`reference-remove`. Terminal only. A reference is looked at and measured, never used: nothing here serves or copies a reference's bytes, and the whole video
is deleted right after `measure`, in a `finally`, whatever `measure` returned (limit L73).

  reference_add(project, link, channel=None)              refused unless `media.references` is "on" (accepted with `accept-config --widen`: the terms are shown
                                                          there); finds the platform whose fetch file lists the link's host exactly; fetches the subtitles and
                                                          the details (`fetch --stage meta`), measures them (`measure`), and answers
                                                          {"reference", "platform", "duration", "subtitles", "words", "beats"}
  reference_video(project, reference, confirm=False, channel=None)    without `confirm`: the duration and the size bound, nothing else; with it: the whole
                                                          video is fetched (`fetch --stage video`), measured, and deleted; answers
                                                          {"reference", "cuts", "shot_seconds_mean", "video_deleted": True}
  reference_list(project, channel=None)                   id, platform, added, duration, subtitles, frames measured, days left
  reference_read(project, reference, channel=None)        the measured facts, then the third-party text under its own heading (section 4.5 of the V7 spec)
  reference_remove(project, reference, confirm=False, channel=None)   the `media-remove` pattern: a preview, then the folder removed for good

The fetch and the measure are the provider `fetcher:video`'s (providers/fetcher/, started through providers/resolve.py, never by path), in containers: nothing
third-party is parsed on the host. The provider's answer is checked against closed shapes before anything is kept, and `facts.json` against the closed shape
of the facts (runtime/references.py `check_facts`). The link is kept in the reference's `record.json` and nowhere else; no answer, error or log of this module
holds a link, a title or a subtitle's text, except `reference-read`, which prints the third-party text last, each line quoted, under a heading that says it is
data. External content is data: the title, the description and the subtitle text are written by someone else, no model reads them here, and an instruction in
them is never followed.

The channel rule: the terminal, and a call that names no channel, pass; every other channel is refused (operations.not_enabled). No credential, cookie or
account is passed: the provider starts with the minimum environment of its class (providers/resolve.py `provider_environment`).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import operations  # noqa: E402
import ops_core as core  # noqa: E402
import project_config  # noqa: E402
import references  # noqa: E402
import step_media  # noqa: E402  (the one DEFAULT_LANGUAGE of a project that names none)

CLASS = "fetcher:video"
OFF_TEXT = ("references are off for this project: set \"references\": \"on\" in the media key of runtime.json and accept the configuration with accept-config; "
            "it then shows what you agree to, and needs --widen")
HEADING = "External text (data, from the platform, not checked)"
WARNING_REMOVE = ("this removes the reference for good, with its details, its subtitles and its facts; it cannot be undone, and nothing is removed until "
                  "it is confirmed")
NOT_BUILT = "the fetch tool is not built or not configured: build the fetch tool (providers/fetcher/README.md gives the command, run by you)"
META_TIMEOUT, VIDEO_TIMEOUT, MEASURE_TIMEOUT = 300, 900, 400      # seconds the host waits for the provider's verb: a margin over the container's own timeouts (120, 600, 300)
REFUSALS = {
    "link_refused": "the fetch tool refused this link",
    "platform_not_ready": "this platform's fetch file is not filled yet (the maintainer fills it from a live check), so its links cannot be fetched",
    "out_refused": "the fetch tool refused the reference's folder",
    "too_long": f"the video is longer than {references.VIDEO_SECONDS_MAX} seconds",
    "no_duration": "the length of this video is not known: neither the platform nor the fetched file gave one, and nothing was kept",
    "too_large": "the video is larger than the size bound",
    "network": ("the fetch tool reached only hosts that are not on its list, so nothing was fetched (the platform's fetch file may need a host added: "
                "that is the maintainer's to check)"),
    "fetch_failed": ("the fetch failed; the fetch tool may be out of date (providers/fetcher/README.md says how to raise it: a command you type)"),
    "time_limit": "the fetch ran over its time limit",
}
CODE_WORD = re.compile(r"\b(" + "|".join(REFUSALS) + r")\b")
FETCH_KEYS = {"ok", "stage", "files", "duration", "width", "height", "subtitles", "refused_hosts", "bytes", "tool"}
FETCH_NAME = re.compile(r"info\.json|proxy\.json|subs\.[a-z]{2,3}\.vtt|video\.(mp4|webm|mov)")
SHA256 = re.compile(r"[0-9a-f]{64}")
USAGE_CODES = ("usage",)


def _channel(ctx: dict, operation: str, channel) -> None:
    """The terminal, and a call that names no channel, pass. Every other channel is refused: a reference is fetched and read in the terminal only."""
    if channel in (None, "terminal"):
        return
    raise core.OpsError(operations.not_enabled(operation, project_config.clean_name(channel)), 1)


def _ref_error(e: "references.RefError") -> "core.OpsError":
    """The OpsError of a refusal of the store: usage is the caller's (2), every other code is a state of the store (1). A message never holds a link."""
    return core.OpsError(f"{e} ({e.code})", 2 if e.code in USAGE_CODES else 1)


def _is_on(ctx: dict) -> bool:
    found = ctx["cfg"].get("media")
    return isinstance(found, dict) and found.get("references") == "on"


def _need_on(ctx: dict) -> None:
    if not _is_on(ctx):
        raise core.OpsError(OFF_TEXT, 1)


class Refused(Exception):
    """The fetch tool refused or failed, with one of the closed codes of REFUSALS."""

    def __init__(self, code: str):
        super().__init__(REFUSALS[code])
        self.code = code


class Fetcher:
    """The provider `fetcher:video` through the resolver, for one project. `call(verb, args, timeout)` returns the one JSON object the verb printed; a refusal
    is `Refused(<closed code>)`; a tool that is not built is a core.OpsError (NOT_BUILT). Nothing is read or passed but the minimum environment of the class."""

    def __init__(self, root: str):
        self._root = root

    def call(self, verb: str, args, timeout: int) -> dict:
        resolver = project_config.resolver(self._root)
        try:
            env = resolver.provider_environment(CLASS, None, ())
            done = resolver.call(CLASS, verb, list(args), root=self._root, timeout=timeout, env=env)
        except (resolver.UnknownClass, resolver.Unresolved):
            raise core.OpsError(NOT_BUILT, 1) from None
        except resolver.ProviderCallError as e:
            if e.kind == "not-configured":
                raise core.OpsError(NOT_BUILT, 1) from None
            if e.kind == "timeout":
                raise Refused("time_limit") from None
            if e.kind == "usage":
                raise core.OpsError("the fetch tool refused the call as written (a defect, not yours): nothing was fetched", 1) from None
            found = CODE_WORD.search(getattr(e, "stderr_tail", "") or "")
            raise Refused(found.group(1) if found else "fetch_failed") from None
        if not isinstance(done, dict):
            raise core.OpsError("the fetch tool's answer was not one JSON object", 1)
        return done


def _fetcher_for(ctx: dict) -> "Fetcher":
    """The fetcher of a call: the real one. A test replaces this function with a fake of the verb contract (`call(verb, args, timeout)`)."""
    return Fetcher(ctx["root"])


def _call(ctx: dict, verb: str, args, timeout: int) -> dict:
    try:
        return _fetcher_for(ctx).call(verb, args, timeout)
    except Refused as e:
        raise core.OpsError(f"{e} ({e.code})", 1) from None


def _fetch(ctx: dict, rid: str, platform: str, link: str, stage: str, max_bytes: int) -> dict:
    """One `fetch` of a stage into the reference's folder, checked: the answer is the closed shape, every file it names is a regular file of the closed names of
    that stage and of the size it says, and whatever else the folder holds is removed."""
    data_dir, root = ctx["cfg"]["data_dir"], ctx["root"]
    language = ((ctx["cfg"].get("media") or {}).get("language")) or step_media.DEFAULT_LANGUAGE
    flags = ["--url", link, "--platform", platform, "--platform-file", references.fetch_file_path(root, platform), "--stage", stage,
             "--out", references.folder_of(data_dir, rid), "--language", language, "--max-bytes", str(max_bytes)]
    if stage == "video":
        flags += ["--max-seconds", str(references.VIDEO_SECONDS_MAX)]
    out = _call(ctx, "fetch", flags, META_TIMEOUT if stage == "meta" else VIDEO_TIMEOUT)
    return _check_fetch(ctx, rid, stage, out, max_bytes)


def _check_fetch(ctx: dict, rid: str, stage: str, out: dict, max_bytes: int) -> dict:
    data_dir = ctx["cfg"]["data_dir"]

    def invalid():
        references.enforce_names(data_dir, rid)
        raise core.OpsError("the fetch tool's answer was not in the shape the store keeps: nothing was kept", 1)
    if out.get("ok") is not True or out.get("stage") != stage or not set(out) <= FETCH_KEYS | {"code"}:
        invalid()
    files = out.get("files")
    if not isinstance(files, list) or len(files) > 8:
        invalid()
    folder = references.folder_of(data_dir, rid)
    names = []
    for entry in files:
        if not (isinstance(entry, dict) and set(entry) == {"name", "size", "sha256"} and isinstance(entry["name"], str) and FETCH_NAME.fullmatch(entry["name"])
                and type(entry["size"]) is int and entry["size"] >= 0 and isinstance(entry["sha256"], str) and SHA256.fullmatch(entry["sha256"])):
            invalid()
        if entry["name"].startswith("video.") and stage != "video":
            invalid()
        try:
            found = os.lstat(os.path.join(folder, entry["name"]))
        except OSError:
            invalid()
        if not stat.S_ISREG(found.st_mode) or found.st_size != entry["size"]:
            invalid()
        names.append(entry["name"])
    if out.get("duration") is not None and not (references.is_num(out["duration"]) and out["duration"] >= 0):
        invalid()
    if out.get("subtitles") not in (None, "manual", "auto", "none"):
        invalid()
    if stage == "video":
        videos = [e for e in files if e["name"].startswith("video.")]
        if len(videos) != 1:
            invalid()
        if videos[0]["size"] > min(references.VIDEO_FILE_CAP, max_bytes):
            references.delete_video(data_dir, rid)
            raise core.OpsError(f"{REFUSALS['too_large']} (too_large)", 1)
    references.enforce_names(data_dir, rid)
    return out


def _measure(ctx: dict, rid: str, platform: str) -> dict:
    """One `measure` of the reference's folder (no network, in a container), then `facts.json` read and checked against the closed shape. A facts file that
    fails its check is removed, never kept."""
    data_dir = ctx["cfg"]["data_dir"]
    flags = ["--in", references.folder_of(data_dir, rid), "--out", references.facts_path(data_dir, rid), "--reference", rid, "--platform", platform]
    _call(ctx, "measure", flags, MEASURE_TIMEOUT)
    try:
        facts = references.check_facts(references.read_json(data_dir, rid, references.FACTS), rid, platform)
    except references.RefError:
        references.drop_facts(data_dir, rid)
        references.enforce_names(data_dir, rid)
        raise core.OpsError("the measured facts were not in the shape the store keeps: nothing was kept", 1) from None
    references.enforce_names(data_dir, rid)
    return facts


def reference_add(project: str, link, channel=None) -> dict:
    """Take a reference from a public link the person gives: refused unless `media.references` is "on" and the link's host is listed in a platform's fetch file.
    The subtitles and details are fetched and measured; a failure leaves nothing. Answers {"reference", "platform", "duration", "subtitles", "words", "beats"}."""
    ctx = core.context(project)
    _channel(ctx, "reference-add", channel)
    _need_on(ctx)
    data_dir = ctx["cfg"]["data_dir"]
    try:
        platform = references.platform_for(ctx["root"], link)
    except references.RefError as e:
        raise _ref_error(e) from None
    if platform is None:
        raise core.OpsError("no platform takes a link to this host: a platform's fetch file (shared/references/platforms/) lists the hosts it takes", 2)
    try:
        record = references.create(data_dir, platform, link)
    except references.RefError as e:
        raise _ref_error(e) from None
    rid = record["id"]
    try:
        with references.operation(data_dir, rid):
            fetched = _fetch(ctx, rid, platform, link, "meta", references.free_bytes(data_dir))
            duration = fetched.get("duration")
            references.update(data_dir, rid, lambda r: r.update(duration=duration if references.is_num(duration) else None))
            facts = _measure(ctx, rid, platform)
    except BaseException:
        try:
            references.remove(data_dir, rid)
        except references.RefError:
            pass
        raise
    return {"reference": rid, "platform": platform, "duration": facts["source"]["duration_s"], "subtitles": facts["source"]["subtitles"],
            "words": facts["speech"]["words"], "beats": facts["format"]["beat_count"]}


def _video_bound(data_dir: str) -> int:
    return min(references.VIDEO_FILE_CAP, references.free_bytes(data_dir))


def reference_video(project: str, reference, confirm=False, channel=None) -> dict:
    """Measure the frames of a reference. Without `confirm` it fetches nothing: the duration and the size bound, which the person reads first. With it the whole
    video is fetched, measured and deleted (in a `finally`: whatever `measure` returned). Answers {"reference", "cuts", "shot_seconds_mean", "video_deleted": True}."""
    ctx = core.context(project)
    _channel(ctx, "reference-video", channel)
    _need_on(ctx)
    if not (type(confirm) is bool or confirm is None):
        raise core.OpsError("confirm is true or false", 2)
    data_dir = ctx["cfg"]["data_dir"]
    try:
        record = references.load(data_dir, references.check_id(reference))
    except references.RefError as e:
        raise _ref_error(e) from None
    duration = record["duration"]
    if references.is_num(duration) and duration > references.VIDEO_SECONDS_MAX:
        raise core.OpsError(f"{REFUSALS['too_long']} (too_long)", 1)
    bound = _video_bound(data_dir)
    if bound <= 0:
        raise core.OpsError("the store of references is full: remove a reference first (reference-remove)", 1)
    if not confirm:
        warning = ("this fetches the whole video, measures it and deletes it at once; it is never kept, never used in a video and never leaves this "
                   "computer; nothing is fetched until it is confirmed (--confirm)")
        if not references.is_num(duration):
            warning += (f"; the platform gave no length for this video, so the fetch is bounded by the size bound and its time limit; the length is measured "
                        f"from the file after the download, and a video over {references.VIDEO_SECONDS_MAX} seconds is deleted and refused")
        return {"reference": reference, "confirmed": False, "duration": duration, "seconds_max": references.VIDEO_SECONDS_MAX, "max_bytes": bound,
                "warning": warning}
    rid, platform = record["id"], record["platform"]
    try:
        guard = references.operation(data_dir, rid)
        guard.__enter__()
    except references.RefError as e:
        raise _ref_error(e) from None
    kept = references.take_facts(data_dir, rid)
    deleted = False
    try:
        try:
            fetched = _fetch(ctx, rid, platform, record["link"], "video", bound)
            measured = fetched.get("duration")
            if references.is_num(measured):
                if measured > references.VIDEO_SECONDS_MAX:
                    references.delete_video(data_dir, rid)
                    raise core.OpsError(f"{REFUSALS['too_long']} (too_long)", 1)
                if not references.is_num(record["duration"]):
                    references.update(data_dir, rid, lambda r: r.update(duration=measured))
            size = references.video_size(data_dir, rid)
            references.update(data_dir, rid, lambda r: r["sizes"].update(video=size))
            references.drop_facts(data_dir, rid)
            facts = _measure(ctx, rid, platform)
            references.update(data_dir, rid, lambda r: r.update(stage="video", video_measured_at=references.stamp()))
        except BaseException:
            if kept is not None and references.take_facts(data_dir, rid) is None:
                try:
                    references.put_facts(data_dir, rid, kept)      # a measure that failed leaves the facts the reference had
                except references.RefError:
                    pass
            raise
        finally:
            deleted = references.delete_video(data_dir, rid)      # the whole video goes right after `measure`, whatever it returned
    except references.RefError as e:
        raise _ref_error(e) from None
    finally:
        guard.__exit__(None, None, None)
    if not deleted:
        raise core.OpsError("the video could not be deleted now; the retention removes it within an hour. Nothing else of it is kept (video_deleted: false)", 1)
    cuts = facts["cuts"]
    return {"reference": rid, "cuts": cuts["count"], "shot_seconds_mean": (cuts["shot_seconds"] or {}).get("mean"), "video_deleted": True}


def _facts_of(data_dir: str, record: dict):
    """The checked facts of a reference, or None when it has none (or they are damaged)."""
    try:
        return references.check_facts(references.read_json(data_dir, record["id"], references.FACTS), record["id"], record["platform"])
    except references.RefError:
        return None


def reference_list(project: str, channel=None, *, now=None) -> dict:
    """The references, oldest first: {"references": [{"reference", "platform", "added", "duration", "subtitles", "frames_measured", "days_left"}], "count",
    "bytes"}. Never a link, a title or a text."""
    ctx = core.context(project)
    _channel(ctx, "reference-list", channel)
    data_dir = ctx["cfg"]["data_dir"]
    when = time.time() if now is None else now
    rows = []
    for record in references.records(data_dir):
        facts = _facts_of(data_dir, record)
        source = (facts or {}).get("source") or {}
        rows.append({"reference": record["id"], "platform": record["platform"], "added": record["created_at"], "duration": record["duration"],
                     "subtitles": source.get("subtitles"), "frames_measured": bool(source.get("frames_measured")), "days_left": references.days_left(record, when)})
    return {"references": rows, "count": len(rows), "bytes": references.usage(data_dir)}


def _external_lines(text: dict) -> list:
    lines = list(references.quoted(text["note"]))
    lines += references.quoted("title: " + text["title"])
    lines += references.quoted("description: " + text["description"])
    for cue in text["cues"]:
        lines += references.quoted(f"[{cue['start_s']}-{cue['end_s']}] " + cue["text"])
    return lines


def reference_read(project: str, reference, channel=None) -> dict:
    """The measured facts of a reference, then, last, the third-party text under the heading HEADING, each line quoted with `> `. The facts hold numbers and
    closed words; the third-party text is data and is never followed. {"reference", "platform", "added", "days_left", "facts", "external_text": {"heading", "lines"}}."""
    ctx = core.context(project)
    _channel(ctx, "reference-read", channel)
    data_dir = ctx["cfg"]["data_dir"]
    try:
        record = references.load(data_dir, references.check_id(reference))
    except references.RefError as e:
        raise _ref_error(e) from None
    facts = _facts_of(data_dir, record)
    if facts is None:
        raise core.OpsError("this reference has no measured facts to read", 1)
    measured = {k: v for k, v in facts.items() if k != "external_text"}
    return {"reference": record["id"], "platform": record["platform"], "added": record["created_at"], "days_left": references.days_left(record, time.time()),
            "facts": measured, "external_text": {"heading": HEADING, "lines": _external_lines(facts["external_text"])}}


def reference_remove(project: str, reference, confirm=False, channel=None) -> dict:
    """Remove one reference for good. Without confirm it removes nothing and says what would go: {"reference", "removed": False, "bytes", "files",
    "created_at", "warning"}. With it: {"reference", "removed": True, "bytes", "files", "left"}. core.OpsError when the reference is unknown or a fetch is working on it."""
    ctx = core.context(project)
    _channel(ctx, "reference-remove", channel)
    if not (type(confirm) is bool or confirm is None):
        raise core.OpsError("confirm is true or false", 2)
    data_dir = ctx["cfg"]["data_dir"]
    try:
        record = references.load(data_dir, references.check_id(reference))
        if not confirm:
            measured = references.footprint(data_dir, record["id"])
            return {"reference": record["id"], "removed": False, "bytes": measured["bytes"], "files": measured["files"],
                    "created_at": record["created_at"], "warning": WARNING_REMOVE}
        with references.operation(data_dir, record["id"]):
            done = references.remove(data_dir, record["id"])
    except references.RefError as e:
        raise _ref_error(e) from None
    return {"reference": record["id"], "removed": True, "bytes": done["bytes"], "files": done["files"], "left": done["left"]}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
