"""Tests of the pictures of a video found on the open web (package V9b-3b): `video-media-websearch` (runtime/ops_media_websearch.py), the reading of its candidates file
(runtime/media_stock.py `read_web_candidates`), the three configuration keys, and the one set two searches build (runtime/ops_media_stock.py `_compose`). The run of the skill is a stand-in
(`FakeRun` of the kit) that writes the file the skill would write, the sources are the fake of the class `stock:media` (its `preview` writes a flat-colour PNG), the renderer's `asset-sheet` a
fake, and the store of recordings, the approval path and the checker script of the skill are the real ones. Nothing is called, no search is run, no link is opened; every name is invented
and every host ends in `.example`.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_websearch.py
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import media, ops, ops_core, work_file, world  # noqa: F401  (the fixture)
from media_stock_kit import (PAGE_MARK, REPO, SKILL, LINK_MARK, accepted, configure, media_stock, ops_media_edit, ops_media_websearch, pick, png, review_of, to_found, web_candidate, web_document,
                             web_world)

project_config = st.load("project_config")
policy_widening = st.load("policy_widening")
operations = st.load("operations")
phrases = st.load("phrases")
ops_runs = st.load("ops_runs")
ops_contained = st.load("ops_contained")
lab = st.load("lab")
REAL_EXECUTE = ops_contained.execute      # the real one, kept before a test puts the stand-in in its place

FOUND_ONE = {"beat7": ("market stall", "image")}
FOUND_TWO = {"beat7": ("market stall", "image"), "beat8": ("fruit crate", "image")}


def search(world, task, confirm=True):
    return ops.video_media_websearch(world["path"], task, confirm=confirm)


def find(world, task, confirm=True):
    return ops.video_media_find(world["path"], task, confirm=confirm)


def stock_folder(world):
    return Path(media_stock.folder_of(world["data"], world["rid"]))


def set_doc(world):
    return json.loads((stock_folder(world) / "set.json").read_text())


def quarantine(world):
    folder = stock_folder(world) / "quarantine"
    return sorted(os.listdir(folder)) if folder.exists() else []


def set_media(world, **keys):
    """The project's `media` object with more keys, accepted again (the widening it shows included)."""
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text())
    raw["media"] = dict(raw.get("media") or {}, **keys)
    path.write_text(json.dumps(raw))
    accepted(world)


def rows(world) -> list:
    ctx = ops_core.context(world["path"])
    return ctx["store"].runs_since(ctx["conn"], "2000-01-01T00:00:00Z")


def refused(call, *args, **kw) -> str:
    with pytest.raises(ops_core.OpsError) as caught:
        call(*args, **kw)
    return str(caught.value)


def text_of(world, key, **fields):
    return phrases.text(key, ops_core.context(world["path"])["cfg"], **fields)


def with_candidates(w, slot="beat7", n=2, **more):
    w["run"].document = web_document([web_candidate(slot, i, **more) for i in range(1, n + 1)])
    return w


# --- the gates of the operation, in order, with nothing run -------------------------------------------------------------------------------------------


def test_without_confirm_it_says_the_words_and_the_download_and_runs_nothing(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    shown = search(world, w["task"], confirm=False)
    assert shown["confirmed"] is False and shown["skipped"] == [] and [s["slot"] for s in shown["slots"]] == ["beat7"]
    assert "market stall" in shown["message"] and "web search of the model that runs it" in shown["message"] and "download small previews" in shown["message"]
    assert shown["message"] == text_of(world, "VID_WEB_PREVIEW", words="market stall")
    assert w["run"].calls == [] and w["sources"].calls == [] and not (stock_folder(world) / "set.json").exists() and rows(world) == []


def test_a_video_that_does_not_wait_at_the_review_is_refused_first_and_nothing_is_run(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    w["routing"]["web"] = False      # a later gate would refuse too: the first one answers
    ctx = ops_core.context(world["path"])
    ctx["store"].step_task_move(ctx["conn"], w["task"], state="running", note=None, by="code")
    assert "not_at_review" in refused(search, world, w["task"]) and w["run"].calls == []


def test_each_gate_refuses_in_its_order_and_nothing_is_run(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    ctx = ops_core.context(world["path"])
    ctx["store"].cursor_set(ctx["conn"], policy_widening.ACCOUNTS, json.dumps({"v": 1, "items": ""}))      # a record from before the open web's item was accepted
    assert "stock_not_accepted" in refused(search, world, w["task"]) and "accept-config --widen" in refused(search, world, w["task"])      # 2
    accepted(world)
    skill_md = Path(world["tree"]) / "skills" / SKILL / "SKILL.md"
    keep = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(keep.replace("requires: [search:web]", "requires: []"), encoding="utf-8")
    w["routing"]["web"] = False
    assert "web_not_built" in refused(search, world, w["task"])      # 4 comes before 5, and after 2 and 3
    assert text_of(world, "VID_WEB_NOT_BUILT") in refused(search, world, w["task"])
    skill_md.write_text(keep, encoding="utf-8")
    assert "web_no_web" in refused(search, world, w["task"]) and text_of(world, "VID_WEB_NO_WEB") in refused(search, world, w["task"])      # 5
    assert w["sources"].calls == [], "the licensed sources are untouched"
    w["routing"]["web"] = True
    set_media(world, websearch={"max_per_day": 1})
    assert search(world, w["task"])["confirmed"] is True
    assert len(w["run"].calls) == 1
    w["routing"]["web"] = False
    assert "web_no_web" in refused(search, world, w["task"])      # 5 comes before 6
    w["routing"]["web"] = True
    assert "web_limit" in refused(search, world, w["task"]) and text_of(world, "VID_WEB_LIMIT", count=1) in refused(search, world, w["task"])      # 6
    assert len(w["run"].calls) == 1, "none of the refusals ran anything"


def test_the_web_must_be_one_of_the_sources_of_the_project(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch, stock=["shelf"]))
    assert "web_off" in refused(search, world, w["task"]) and w["run"].calls == []


def test_a_slot_that_wants_a_clip_is_not_sent_while_the_engine_draws_none_and_is_listed_as_skipped(world, monkeypatch):
    monkeypatch.setattr(ops_media_websearch.media_animation, "asset_kinds", lambda root, implementation=None: ["image"])      # V9b-5c: the real catalogue now lists clips; an engine without them still skips the slot
    w = with_candidates(web_world(world, monkeypatch, {"beat7": ("market stall", "image"), "beat8": ("fruit crate", "clip")}))
    shown = search(world, w["task"], confirm=False)
    assert [s["slot"] for s in shown["slots"]] == ["beat7"] and [k["slot"] for k in shown["skipped"]] == ["beat8"]
    assert shown["skipped"][0]["message"] == text_of(world, "VID_STOCK_CLIP_NOT_DRAWN") and "fruit crate" not in shown["message"]
    done = search(world, w["task"])
    assert done["skipped"] == shown["skipped"] and w["run"].calls[0]["prompt"].startswith("Find media for this cutaway.") and "beat8" not in w["run"].calls[0]["prompt"]


def test_a_skipped_clip_slot_does_not_block_the_fetch_and_is_left_without_a_picture(world, monkeypatch):
    monkeypatch.setattr(ops_media_websearch.media_animation, "asset_kinds", lambda root, implementation=None: ["image"])      # the engine draws no clips, so the test holds after the merge into the clip branch
    w = with_candidates(web_world(world, monkeypatch, {"beat7": ("market stall", "image"), "beat8": ("fruit crate", "clip")}))
    done = search(world, w["task"])
    assert [s["slot"] for s in done["skipped"]] == ["beat8"]
    by_slot = {r["slot"]: r for r in set_doc(world)["slots"]}
    assert by_slot["beat8"]["candidates"] == [] and by_slot["beat7"]["candidates"]
    pick(world, w["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    got = ops.video_media_fetch_picks(world["path"], w["task"])
    assert got["without_picture"] == ["beat8"] and text_of(world, "VID_STOCK_NO_PICTURE", slots="beat8") in got["message"]
    assert [a["slot"] for a in got["assets"]] == ["beat7"] and len(w["sources"].of("fetch")) == 1


def test_a_video_whose_only_slots_want_clips_has_nothing_to_send(world, monkeypatch):
    monkeypatch.setattr(ops_media_websearch.media_animation, "asset_kinds", lambda root, implementation=None: ["image"])      # V9b-5c: the real catalogue now lists clips; an engine without them still skips the slot
    w = with_candidates(web_world(world, monkeypatch, {"beat7": ("market stall", "clip")}))
    assert "no_slots" in refused(search, world, w["task"]) and w["run"].calls == []


# --- the prompt: the measured form, and nothing of the project ------------------------------------------------------------------------------------------


def test_the_prompt_is_case_one_of_the_skill_byte_for_byte():
    cases = json.loads((REPO / "skills" / SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    first = next(c for c in cases if c["id"] == 1) if any(c["id"] == 1 for c in cases) else cases[0]
    slots = [{"slot": "sunrise-city", "want": "image", "search": "sunrise over a city skyline vertical wallpaper"}, {"slot": "coffee-pour", "want": "clip", "search": "pouring coffee close up slow motion free stock"}]
    assert ops_media_websearch._render_prompt(slots) == first["prompt"]
    assert ops_media_websearch._render_prompt(slots[:1]) == "Find media for this cutaway. Slot `sunrise-city`: a picture, search words \"sunrise over a city skyline vertical wallpaper\"."


def test_a_value_that_is_not_in_the_form_a_search_may_be_sent_in_is_refused_again_before_anything_runs():
    good = {"slot": "beat7", "want": "image", "search": "market stall"}
    ops_media_websearch._check_slots([good])
    for bad in (dict(good, slot="Beat 7"), dict(good, want="video"), dict(good, search="market stall 7"), dict(good, search="one two three four five six seven"), dict(good, search="a\nb"),
                dict(good, search="x" * 61)):
        with pytest.raises(ops_core.OpsError) as caught:
            ops_media_websearch._check_slots([bad])
        assert "slot_invalid" in str(caught.value)


def test_the_run_carries_only_the_words_of_the_slots_and_no_file_and_no_standing_instruction(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    marker = "ZEBRA-MARKER-5521"
    (Path(world["path"]) / "docs" / "workbench").mkdir(parents=True, exist_ok=True)
    (Path(world["path"]) / "docs" / "workbench" / "state.md").write_text("# State\n\n- note: %s\n" % marker, encoding="utf-8")
    transcript = json.loads(work_file(world, "transcript.json").read_text(encoding="utf-8"))
    transcript["words"][0]["text"] = marker
    media.write_work(world["data"], world["rid"], "transcript.json", json.dumps(transcript).encode("utf-8"))
    ops.instructions_set(world["path"], "Always mention %s.\n" % marker, ops.instructions_read(world["path"]).get("sha256") or "none", channel="terminal")
    search(world, w["task"])
    [call] = w["run"].calls
    assert call["prompt"].strip() == ops_media_websearch._render_prompt([{"slot": "beat7", "want": "image", "search": "market stall"}]) and marker not in call["prompt"]
    assert call["open_web"] is True and call["sourced"] == () and call["platforms"] == () and call["skill"] == SKILL and call["around"] is True
    assert call["timeout"] == 300 and call["max_cost"] == 0.6, "the defaults of media.websearch"
    assert "a screenshot of a shop" not in call["prompt"], "what the slot shows is the person's own text: it is not sent"


def test_the_real_execute_hands_the_lab_no_file_of_the_project(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    monkeypatch.setattr(ops_media_websearch.ops_contained, "execute", REAL_EXECUTE)
    monkeypatch.setattr(lab, "run_skill", w["run"].lab_call)
    monkeypatch.setattr(lab, "session", lambda: contextlib.nullcontext())
    monkeypatch.setattr(ops_runs, "_key_in_environment", lambda routing, keys: contextlib.nullcontext())
    (Path(world["path"]) / "docs" / "workbench").mkdir(parents=True, exist_ok=True)
    (Path(world["path"]) / "docs" / "workbench" / "state.md").write_text("# State\n", encoding="utf-8")
    done = search(world, w["task"])
    [call] = w["run"].calls
    assert done["confirmed"] is True and call["files"] == [] and call["open_web"] is True and call["retries"] == 0 and call["platforms"] == ()


# --- the read-back ----------------------------------------------------------------------------------------------------------------------------------


def bad_documents():
    ok = web_candidate("beat7", 1)
    return {
        "a link that is not https": web_document([dict(ok, media_url="http://pics.example/a.jpg")]),
        "a slot that was not sent": web_document([web_candidate("beat9", 1)]),
        "a kind that was not sent": web_document([dict(ok, kind="clip")]),
        "an unknown field": web_document([dict(ok, extra=1)]),
        "a screen work that is not a boolean": web_document([dict(ok, screen_work="no")]),
        "a title over its bound": web_document([dict(ok, title="x" * 121)]),
        "four candidates for one slot": web_document([web_candidate("beat7", i) for i in range(1, 5)]),
        "the same file twice": web_document([ok, dict(web_candidate("beat7", 2), media_url=ok["media_url"])]),
        "a link with a port": web_document([dict(ok, page_url="https://pages.example:8443/p")]),
        "a link with an address": web_document([dict(ok, media_url="https://10.0.0.1/a.jpg")]),
        "a link with user info": web_document([dict(ok, thumb_url="https://user@pics.example/a.jpg")]),
        "an open item that is not a closed code": web_document([ok], [{"code": "gave_up", "slot": "beat7"}]),
        "an open item for a slot that was not sent": web_document([ok], [{"code": "no_result", "slot": "beat9"}]),
        "another schema": dict(web_document([ok]), schema_version=2),
        "an unknown top-level key": dict(web_document([ok]), extra=[]),
    }


@pytest.mark.parametrize("name", list(bad_documents()))
def test_a_candidates_file_that_breaks_a_rule_is_refused_whole_and_nothing_is_fetched_or_kept(world, monkeypatch, name):
    w = web_world(world, monkeypatch)
    w["run"].document = bad_documents()[name]
    message = refused(search, world, w["task"])
    assert "candidates_invalid" in message and text_of(world, "VID_WEB_FAILED") in message
    assert w["sources"].of("preview") == [] and not (stock_folder(world) / "set.json").exists() and quarantine(world) == []
    assert not [n for n in os.listdir(stock_folder(world)) if n.startswith(".work")], "the scratch copy goes"


def test_each_of_the_two_checks_refuses_alone(world, monkeypatch):
    w = web_world(world, monkeypatch)
    w["run"].document = web_document([web_candidate("beat9", 1)])      # the slot was not sent
    monkeypatch.setattr(ops_media_websearch, "_check_with_script", lambda copy, sent: True)      # the skill's script says yes: the rules in code still say no
    assert "candidates_invalid" in refused(search, world, w["task"])
    w["run"].document = web_document([web_candidate("beat7", 1)])
    monkeypatch.setattr(ops_media_websearch, "_check_with_script", lambda copy, sent: False)      # the script says no: a file that passes the rules in code is refused too
    assert "candidates_invalid" in refused(search, world, w["task"])
    assert w["sources"].of("preview") == []


def test_a_file_that_is_not_json_is_over_64_kib_or_is_a_link_is_refused(world, monkeypatch):
    w = web_world(world, monkeypatch)
    w["run"].raw = b"not json {"
    assert "candidates_invalid" in refused(search, world, w["task"])
    w["run"].raw = json.dumps(web_document([web_candidate("beat7", 1, title="x" * 100)])).encode("utf-8") + b" " * (64 * 1024)
    assert "candidates_invalid" in refused(search, world, w["task"])
    w["run"].raw, w["run"].document, w["run"].link = None, web_document([web_candidate("beat7", 1)]), True      # a link in place of the file: never followed
    assert "candidates_invalid" in refused(search, world, w["task"])
    w["run"].link, w["run"].raw = False, None
    w["run"].document = None      # no file at all
    assert "candidates_invalid" in refused(search, world, w["task"])
    assert w["sources"].of("preview") == [] and not (stock_folder(world) / "set.json").exists()


def test_a_run_that_found_nothing_or_had_no_search_tool_says_so_and_keeps_nothing(world, monkeypatch):
    w = web_world(world, monkeypatch)
    w["run"].document = web_document([], [{"code": "no_result", "slot": "beat7"}])
    message = refused(search, world, w["task"])
    assert "web_nothing" in message and text_of(world, "VID_WEB_NOTHING") in message
    w["run"].document = web_document([], [{"code": "no_search_tool"}])
    message = refused(search, world, w["task"])
    assert "web_no_web" in message and text_of(world, "VID_WEB_NO_WEB") in message
    assert w["sources"].of("preview") == [] and not (stock_folder(world) / "set.json").exists()


def test_the_rules_in_code_are_the_rules_of_the_skills_script(tmp_path):
    ok = web_candidate("beat7", 1)
    sent = {"beat7": "image"}
    assert media_stock.read_web_candidates(web_document([ok], [{"code": "scene_only", "slot": "beat7", "note": "a film"}]), sent)["candidates"] == [ok]
    for bad in (None, [], {"schema_version": True, "candidates": [], "open": []}, web_document([dict(ok, resolution="12x")]), web_document([dict(ok, licence_claim="")]),
                web_document([dict(ok, slot=7)]), web_document([ok] * 2), web_document([], [{"code": "no_result"}])):
        with pytest.raises(media_stock.StockError) as caught:
            media_stock.read_web_candidates(bad, sent)
        assert caught.value.code == "candidates_invalid"
    checker = REPO / "skills" / SKILL / "scripts" / "check_candidates.py"
    text = checker.read_text(encoding="utf-8")      # the skill's script and the runtime's constants say the same numbers
    pick_int = lambda name: int(re.search(r"^%s = (\d+)$" % name, text, re.M).group(1))      # noqa: E731
    assert (pick_int("MAX_TOTAL"), pick_int("MAX_PER_SLOT"), pick_int("MAX_URL")) == (media_stock.WEB_MAX_TOTAL, media_stock.WEB_MAX_PER_SLOT, media_stock.WEB_MAX_URL)
    assert (pick_int("MAX_TITLE"), pick_int("MAX_CLAIM"), pick_int("MAX_TERMS"), pick_int("MAX_NOTE")) == (120, 200, 200, 200) == tuple(media_stock.WEB_BOUNDS[k] for k in ("title", "licence_claim", "site_terms", "note"))
    assert re.search(r'^REQUIRED = \("slot", "kind", "media_url", "page_url", "title", "licence_claim", "screen_work"\)$', text, re.M) and media_stock.WEB_REQUIRED == ("slot", "kind", "media_url", "page_url", "title", "licence_claim", "screen_work")
    assert re.search(r'^OPTIONAL = \("thumb_url", "resolution", "site_terms"\)$', text, re.M) and media_stock.WEB_OPTIONAL == ("thumb_url", "resolution", "site_terms")
    assert re.search(r'^OPEN_CODES = \("no_result", "no_search_tool", "scene_only"\)$', text, re.M) and media_stock.WEB_OPEN_CODES == ("no_result", "no_search_tool", "scene_only")


# --- the run folder -----------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["ok", "failed", "boom", "docker"])
def test_the_run_folder_and_the_copy_are_removed_after_a_success_a_failure_and_an_exception(world, monkeypatch, mode, capsys):
    w = with_candidates(web_world(world, monkeypatch))
    w["run"].mode = mode
    if mode == "ok":
        assert search(world, w["task"])["confirmed"] is True
    else:
        message = refused(search, world, w["task"])
        assert "web_failed" in message and text_of(world, "VID_WEB_FAILED") in message and LINK_MARK not in message
    data = Path(world["data"]).parent
    assert w["run"].dests, "the run was asked for"
    for dest in w["run"].dests:
        assert not Path(dest).exists(), "the folder that held pages from the open web is gone"
    runs_folder = Path(ops_core.context(world["path"])["cfg"]["data_dir"]) / "contained-runs"
    assert not runs_folder.exists() or os.listdir(runs_folder) == []
    [row] = rows(world)
    ctx = ops_core.context(world["path"])
    assert row["skill"] == SKILL and row["status"] == ("ok" if mode == "ok" else "failed") and ctx["store"].task_run_get(ctx["conn"], row["id"])["web"]
    assert LINK_MARK not in json.dumps(row, default=str) and "market stall" not in json.dumps(row, default=str)
    err = capsys.readouterr().err
    assert LINK_MARK not in err and "market stall" not in err and data.exists()


# --- the previews and the candidate record ------------------------------------------------------------------------------------------------------------


def test_each_candidate_gets_a_preview_through_the_provider_with_the_closed_flags_and_the_persons_host_lists(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch), n=2)
    set_media(world, web_refused_hosts=["blocked.example"], web_allowed_hosts=["pics.example", "cdn.pics.example"])
    done = search(world, w["task"])
    calls = w["sources"].of("preview", "web")
    assert len(calls) == 2 and done["found"] == 2
    for call, n in zip(sorted(calls, key=lambda c: c["flags"][c["flags"].index("--url") + 1]), (1, 2)):
        flags = call["flags"]
        assert flags[flags.index("--kind") + 1] == "image" and flags[flags.index("--url") + 1] == web_candidate("beat7", n)["thumb_url"]
        assert flags[flags.index("--out") + 1].endswith(os.path.join("stock", "quarantine")) and flags[flags.index("--max-bytes") + 1] == str(4 * 1024 * 1024)
        assert "--allow-unverified" in flags and flags.count("--refuse-host") == 1 and flags[flags.index("--refuse-host") + 1] == "blocked.example"
        assert [flags[i + 1] for i, x in enumerate(flags) if x == "--allow-host"] == ["pics.example", "cdn.pics.example"]
        assert call["timeout"] == 40
    assert not [c for c in w["sources"].calls if c["verb"] == "fetch"], "a preview is the only thing fetched at this stage"


def test_the_media_link_stands_in_for_the_preview_when_there_is_no_thumbnail(world, monkeypatch):
    w = web_world(world, monkeypatch)
    one = web_candidate("beat7", 1)
    one.pop("thumb_url")
    w["run"].document = web_document([one])
    search(world, w["task"])
    [call] = w["sources"].of("preview")
    assert call["flags"][call["flags"].index("--url") + 1] == one["media_url"]


def no_thumb(slot, n, kind="clip"):
    row = web_candidate(slot, n, kind=kind)
    row.pop("thumb_url")
    return row


def sheet_calls(w):
    return [c for c in w["sheets"].calls if c["mode"] == "preview"]


def test_a_web_clip_with_no_thumbnail_is_kept_with_no_preview_and_no_provider_call(world, monkeypatch):
    w = web_world(world, monkeypatch, {"beat7": ("market stall", "image"), "beat8": ("fruit crate", "clip")})
    clip = no_thumb("beat8", 1)
    w["run"].document = web_document([web_candidate("beat7", 1), clip])
    done = search(world, w["task"])
    assert not [c for c in w["sources"].calls if clip["media_url"] in c["flags"]], "no preview or fetch call names the clip"
    row = next(r for r in done["slots"] if r["slot"] == "beat8")
    [shown] = row["candidates"]
    assert shown["preview"] is False and shown["pick"] == "web:u-" + hashlib.sha256(clip["media_url"].encode("utf-8")).hexdigest()[:12]
    [record] = next(r for r in set_doc(world)["slots"] if r["slot"] == "beat8")["candidates"]
    assert record["preview"] is None and record["preview_in"] is None and record["preview_sha256"] is None and record["kind"] == "clip"
    assert done["dropped"]["preview"] == 0 and done["found"] == 2
    assert "beat8" not in {slot for slot, _ in sheet_calls(w)[-1]["items"]} and ("beat7", 1) in sheet_calls(w)[-1]["items"]
    assert LINK_MARK not in json.dumps(done)


def test_a_previewless_clip_keeps_the_column_of_the_others(world, monkeypatch):
    w = web_world(world, monkeypatch, {"beat8": ("fruit crate", "clip")})
    w["run"].document = web_document([no_thumb("beat8", 1), web_candidate("beat8", 2, kind="clip")])
    done = search(world, w["task"])
    assert [c["col"] for c in done["slots"][0]["candidates"]] == [1, 2] and [c["preview"] for c in done["slots"][0]["candidates"]] == [False, True]
    assert set(sheet_calls(w)[-1]["items"]) == {("beat8", 2)}


def test_a_search_whose_candidates_all_lack_a_preview_draws_no_sheet(world, monkeypatch):
    w = web_world(world, monkeypatch, {"beat8": ("fruit crate", "clip")})
    w["run"].document = web_document([no_thumb("beat8", 1), no_thumb("beat8", 2)])
    done = search(world, w["task"])
    assert done["sheet"] is None and sheet_calls(w) == [] and done["found"] == 2 and done["message"] != text_of(world, "VID_WEB_NOTHING")


def test_a_find_after_a_web_search_carries_a_previewless_clip_with_the_same_words_and_drops_it_when_they_change(world, monkeypatch):
    w = web_world(world, monkeypatch, {"beat7": ("market stall", "clip")})
    w["run"].document = web_document([no_thumb("beat7", 1)])
    first = search(world, w["task"])
    pick_of = first["slots"][0]["candidates"][0]["pick"]
    again = find(world, w["task"])
    assert [c["pick"] for c in again["slots"][0]["candidates"] if c["source"] == "web"] == [pick_of]
    ops_media_edit.edit(ops_core.context(world["path"]), w["task"], review_of(world)["revision"], [{"op": "slot_search", "slot": "beat7", "search": "stall at dawn", "want": "clip"}])
    after = find(world, w["task"])
    assert [c for c in after["slots"][0]["candidates"] if c["source"] == "web"] == []


def test_a_refused_preview_drops_its_candidate_and_is_counted_and_at_most_eighteen_run_four_at_a_time(world, monkeypatch):
    seven = {"beat%d" % n: ("fruit %s" % w_, "image") for n, w_ in zip(range(7, 13), "abcdef")}
    w = web_world(world, monkeypatch, seven)
    w["run"].document = web_document([web_candidate(slot, i) for slot in seven for i in (1, 2, 3)])      # 18 candidates: the most a run may give
    w["sources"].fail_urls = {web_candidate("beat7", 1)["thumb_url"], web_candidate("beat8", 2)["thumb_url"]}
    done = search(world, w["task"])
    assert len(w["sources"].of("preview")) == 18 == ops_media_websearch.PREVIEW_MAX and done["found"] == 16 and done["dropped"]["preview"] == 2
    assert w["sources"].most_active["web"] <= ops_media_websearch.PREVIEW_PARALLEL == 4
    assert len([c for r in done["slots"] for c in r["candidates"]]) == 16


def test_the_candidate_record_holds_what_the_page_claims_and_the_answer_never_holds_the_link_of_the_file(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch), n=2, screen_work=True)
    done = search(world, w["task"])
    doc = set_doc(world)
    assert doc["phase"] == "found" and doc["task"] == w["task"] and doc["sources"] == ["web"]
    [slot] = doc["slots"]
    for n, c in enumerate(slot["candidates"], 1):
        digest = c["preview_sha256"]
        assert c == {"source": "web", "item": "q-" + digest[:12], "pick": "web:q-" + digest[:12], "kind": "image", "licence": "unverified", "author": "", "title": "A market stall at dawn %d" % n,
                     "page": web_candidate("beat7", n)["page_url"], "licence_claim": "free to use, says the page", "site_terms": web_candidate("beat7", n)["site_terms"], "resolution": "1200x800",
                     "screen_work": True, "url": web_candidate("beat7", n)["media_url"], "page_host": "pages.example", "width": None, "height": None, "seconds": None,
                     "preview": "q-%s.png" % digest[:12], "preview_in": "quarantine", "preview_sha256": digest}
        assert (stock_folder(world) / "quarantine" / c["preview"]).is_file()
    assert sorted(quarantine(world)) == sorted(c["preview"] for c in slot["candidates"])
    shown = done["slots"][0]["candidates"]
    assert all(set(c) <= {"pick", "source", "item", "kind", "licence", "author", "title", "page", "width", "height", "seconds", "preview", "col", "licence_claim", "site_terms", "resolution",
                          "screen_work", "page_host"} for c in shown)
    assert [c["page_host"] for c in shown] == ["pages.example"] * 2 and all(c["screen_work"] is True and c["licence"] == "unverified" for c in shown)
    assert LINK_MARK not in json.dumps(done) and "media_url" not in json.dumps(done) and PAGE_MARK in json.dumps(done), "the page address is text for this computer's own page; the link of the file is nobody's"
    assert done["sheet"] == "sheet-preview.png" and w["sheets"].calls[-1]["mode"] == "preview" and len(w["sheets"].calls[-1]["items"]) == 2
    assert all(str(stock_folder(world) / "quarantine") in path for path in w["sheets"].calls[-1]["items"].values()), "the sheet is drawn from the quarantine's own files"


def test_two_candidates_with_the_same_preview_bytes_in_one_slot_are_kept_once(world, monkeypatch):
    w = web_world(world, monkeypatch)
    same = web_candidate("beat7", 2, thumb_url=web_candidate("beat7", 1)["thumb_url"])
    w["run"].document = web_document([web_candidate("beat7", 1), same])
    done = search(world, w["task"])
    assert done["found"] == 1 and len(quarantine(world)) == 1


def test_the_link_of_a_file_is_in_no_answer_no_run_row_no_message_and_no_error(world, monkeypatch, capsys):
    w = with_candidates(web_world(world, monkeypatch))
    answers = [search(world, w["task"], confirm=False), search(world, w["task"])]
    ctx = ops_core.context(world["path"])
    dump = "\n".join(ctx["conn"].iterdump())
    assert LINK_MARK not in json.dumps(answers) and LINK_MARK not in dump
    assert PAGE_MARK not in dump and "market stall" not in dump.replace("web media search", "")
    w["run"].mode = "failed"
    message = refused(search, world, w["task"])
    w["run"].mode = "boom"
    message += refused(search, world, w["task"])
    out = capsys.readouterr()
    assert LINK_MARK not in message and LINK_MARK not in out.err and LINK_MARK not in out.out
    assert LINK_MARK not in "\n".join(ctx["conn"].iterdump()) and LINK_MARK not in "\n".join(ops_core.context(world["path"])["conn"].iterdump())


# --- one set, two searches ----------------------------------------------------------------------------------------------------------------------------


def retype(world, task, words):
    ctx = ops_core.context(world["path"])
    ops_media_edit.edit(ctx, task, review_of(world)["revision"], [{"op": "slot_search", "slot": "beat7", "search": words, "want": "image"}])


def previews(world):
    return sorted(n for n in os.listdir(stock_folder(world)) if n.startswith("prev-"))


def test_a_find_after_a_web_search_replaces_the_licensed_candidates_only_and_a_web_search_after_a_find_the_web_ones_only(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    first = search(world, w["task"])
    assert [c["source"] for c in first["slots"][0]["candidates"]] == ["web", "web"] and len(quarantine(world)) == 2 and previews(world) == []
    media_stock.write_doc(world["data"], world["rid"], media_stock.APPROVED, {"hash": "x" * 64, "task": w["task"], "unverified": {}})
    both = find(world, w["task"])      # the words are the same: the web candidates are carried
    assert [c["source"] for c in both["slots"][0]["candidates"]] == ["web", "shelf", "web", "shelf"] and len(quarantine(world)) == 2 and len(previews(world)) == 2
    assert not (stock_folder(world) / "approved.json").exists(), "a new find voids the approval"
    kept = [c["pick"] for c in both["slots"][0]["candidates"] if c["source"] == "web"]
    assert kept == [c["pick"] for c in first["slots"][0]["candidates"]]
    media_stock.write_doc(world["data"], world["rid"], media_stock.APPROVED, {"hash": "x" * 64, "task": w["task"], "unverified": {}})
    again = search(world, w["task"])      # the words are the same: the licensed candidates are carried
    assert [c["source"] for c in again["slots"][0]["candidates"]] == ["web", "shelf", "web", "shelf"] and len(previews(world)) == 2 and len(quarantine(world)) == 2
    assert not (stock_folder(world) / "approved.json").exists(), "a new web search voids the approval"
    assert [c["pick"] for c in again["slots"][0]["candidates"]] == [c["pick"] for c in both["slots"][0]["candidates"]]
    assert w["sheets"].calls[-1]["mode"] == "preview" and len(w["sheets"].calls[-1]["items"]) == 4


def test_the_candidates_of_the_other_search_are_dropped_when_the_words_changed_and_their_files_go(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    search(world, w["task"])
    find(world, w["task"])
    assert len(quarantine(world)) == 2 and len(previews(world)) == 2
    retype(world, w["task"], "fruit crate")
    done = find(world, w["task"])      # the web candidates were found for other words: gone, with their files
    assert [c["source"] for c in done["slots"][0]["candidates"]] == ["shelf", "shelf"] and quarantine(world) == [] and len(previews(world)) == 2
    retype(world, w["task"], "market stall")
    done = search(world, w["task"])      # the licensed candidates were found for "fruit crate": gone, with their files
    assert [c["source"] for c in done["slots"][0]["candidates"]] == ["web", "web"] and previews(world) == [] and len(quarantine(world)) == 2
    done = find(world, w["task"])      # the same words: the web candidates stay
    assert [c["source"] for c in done["slots"][0]["candidates"]] == ["web", "shelf", "web", "shelf"] and len(quarantine(world)) == 2 and len(previews(world)) == 2
    retype(world, w["task"], "fruit crate")
    done = search(world, w["task"])
    assert [c["source"] for c in done["slots"][0]["candidates"]] == ["web", "web"] and previews(world) == [] and len(quarantine(world)) == 2


def test_a_carried_candidate_whose_preview_file_is_gone_or_changed_is_not_carried(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    search(world, w["task"])
    name = set_doc(world)["slots"][0]["candidates"][0]["preview"]
    (stock_folder(world) / "quarantine" / name).write_bytes(png(3, 3, (1, 1, 1)))      # swapped under the same name
    done = find(world, w["task"])
    assert [c["source"] for c in done["slots"][0]["candidates"]] == ["web", "shelf", "shelf"] and len(quarantine(world)) == 1


def test_a_find_with_no_licensed_source_still_refuses_with_stock_off(world, monkeypatch):
    found = to_found(world, monkeypatch, stock=["web"])
    assert "stock_off" in refused(find, world, found["task"])


def test_a_missing_web_item_never_blocks_a_licensed_find_and_a_web_search_needs_it(world, monkeypatch):
    found = to_found(world, monkeypatch, stock="default")
    ctx = ops_core.context(world["path"])
    items = policy_widening.account_items(ctx["cfg"], st.load("ops_config")._digest_key(ctx))
    licensed = [i for i in items if i["group"].startswith("stock=shelf@")]
    assert licensed and any(i["group"] == "stock=web@none" for i in items)
    ctx["store"].cursor_set(ctx["conn"], policy_widening.ACCOUNTS, json.dumps({"v": 1, "items": "".join(sorted(i["digest"] for i in items if i["group"] != "stock=web@none"))}))      # the record of a project accepted under V9b-3a
    assert find(world, found["task"])["found"] == 2
    assert "stock_not_accepted" in refused(search, world, found["task"])


def test_the_web_item_of_the_widening_is_the_approved_text_and_a_project_accepted_before_must_accept_again(world, monkeypatch):
    configure(world, monkeypatch, "default", accept=False)
    items = [i for i in ops.config(world["path"])["widening"] if i["group"].startswith("stock=")]
    assert [i["group"] for i in items] == ["stock=shelf@2026-11-11", "stock=web@none"]
    assert items[1]["means"] == policy_widening.WEB_MEANS == ("web search: the search words of each video are sent to the web search of the model that runs it and to that model's provider; "
                                                            "the pictures and clips found have no licence the workbench can check; each needs its own approval after a copyright warning; "
                                                            "a published video that uses one can be taken down and can strike your account")


# --- the three configuration keys ----------------------------------------------------------------------------------------------------------------------


def media_file(world, **keys):
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text())
    raw["media"] = keys
    path.write_text(json.dumps(raw))
    return project_config.load(world["path"])


def test_the_web_host_lists_and_the_bounds_of_a_search_are_checked_and_have_defaults(world, monkeypatch):
    configure(world, monkeypatch, "default", accept=False)
    cfg = media_file(world)
    assert media_stock.websearch_limits(cfg) == {"max_per_day": 5, "max_cost_usd": 0.6, "timeout_seconds": 300} and "web_refused_hosts" not in cfg["media"]
    cfg = media_file(world, web_refused_hosts=["blocked.example"], web_allowed_hosts=["pics.example", "a.b.example"], websearch={"max_per_day": 2})
    assert cfg["media"]["web_refused_hosts"] == ["blocked.example"] and cfg["media"]["web_allowed_hosts"] == ["pics.example", "a.b.example"]
    assert media_stock.websearch_limits(cfg) == {"max_per_day": 2, "max_cost_usd": 0.6, "timeout_seconds": 300}
    assert media_stock.websearch_limits(media_file(world, websearch={"max_cost_usd": 1.5, "timeout_seconds": 60}))["max_cost_usd"] == 1.5
    for key, bad in (("web_refused_hosts", "pics.example"), ("web_refused_hosts", ["Pics.Example"]), ("web_allowed_hosts", ["pics"]), ("web_allowed_hosts", ["10.0.0.1"]),
                     ("web_allowed_hosts", ["pics.example."]), ("web_refused_hosts", [3]), ("web_refused_hosts", ["a%d.example" % n for n in range(101)]), ("web_allowed_hosts", ["a b.example"]),
                     ("websearch", {"max_per_day": 0}), ("websearch", {"max_cost_usd": 9}), ("websearch", {"timeout_seconds": 5}), ("websearch", {"max_per_day": 1.5}), ("websearch", {"extra": 1}),
                     ("websearch", "often")):
        with pytest.raises(project_config.ConfigError):
            media_file(world, **{key: bad})
    assert len(media_file(world, web_refused_hosts=["a%d.example" % n for n in range(100)])["media"]["web_refused_hosts"]) == 100


def test_the_host_expression_and_the_caps_are_the_providers_own():
    net = (REPO / "providers" / "stock" / "_net.py").read_text(encoding="utf-8")
    found = re.search(r'^HOST_RE = re\.compile\(r"(.+?)"\)', net, re.M)
    assert found and found.group(1) == project_config.WEB_HOST_RE.pattern
    provider = (REPO / "providers" / "stock" / "web.py").read_text(encoding="utf-8")
    assert re.search(r'"host_list": (\d+)', provider).group(1) == str(project_config.WEB_HOSTS_MAX)
    assert re.search(r'PER_VIDEO = \{"previews": (\d+)', provider).group(1) == str(ops_media_websearch.PREVIEW_MAX)
    assert re.search(r'"preview_bytes": (\d) \* MIB', provider).group(1) == "4" and ops_media_websearch.PREVIEW_BYTES == 4 * 1024 * 1024
    assert re.search(r'"preview_seconds": (\d+)', provider).group(1) == "30" and ops_media_websearch.PREVIEW_TIMEOUT > 30      # the run's own timeout is over the provider's
    assert re.search(r'^VERBS = \("preview", "fetch"\)$', provider, re.M) and re.search(r'^PREVIEW_TYPES = \("image/png", "image/jpeg"\)$', provider, re.M)
    assert ops_media_websearch.PREVIEW_TYPES == ("image/png", "image/jpeg")


# --- the day -----------------------------------------------------------------------------------------------------------------------------------------


def test_the_day_limit_counts_the_runs_of_this_skill_started_today_whatever_their_end(world, monkeypatch):
    set_media(world, websearch={"max_per_day": 2})
    w = with_candidates(web_world(world, monkeypatch))
    set_media(world, websearch={"max_per_day": 2})
    w["run"].mode = "failed"
    assert "web_failed" in refused(search, world, w["task"])
    w["run"].mode = "ok"
    assert search(world, w["task"])["confirmed"] is True
    assert len(rows(world)) == 2
    message = refused(search, world, w["task"])
    assert "web_limit" in message and text_of(world, "VID_WEB_LIMIT", count=2) in message and len(w["run"].calls) == 2


# --- the files of the code ----------------------------------------------------------------------------------------------------------------------------


def test_no_source_is_named_in_the_websearch_file_and_it_runs_on_python_39_syntax():
    sources = {json.loads(p.read_text())["source"] for p in (REPO / "providers" / "stock" / "sources").glob("*.json")}
    text = (REPO / "runtime" / "ops_media_websearch.py").read_text(encoding="utf-8")
    assert len(sources) >= 3 and "web" in sources
    for source in sources:
        if source == "web":
            assert not re.search(r"(source|implementation|names?|sources|default\w*)\s*(==|!=|=|in)\s*[(\[\"']*\s*[\"']web[\"']", text), "the file names the source web"
            assert not re.search(r"[\"']web[\"']\s*,\s*[\"']shelf|[\"']shelf[\"']\s*,\s*[\"']web", text)
        else:
            assert not re.search(r"[\"'`]%s[\"'`]" % source, text), f"the file names the source {source}"
        assert not re.search(r"providers/stock/%s\.py" % source, text)
    assert not re.search(r":=|\bmatch \w+:|\bX \| Y\b", text) and "removeprefix" not in text
    import ast
    ast.parse(text, feature_version=(3, 9))


# --- the limits ------------------------------------------------------------------------------------------------------------------------------------


def test_limit_78_the_web_search_runs_only_after_the_acceptance_and_the_confirm_on_a_pair_measured_with_the_web_and_carries_nothing_of_the_project(world, monkeypatch):
    w = with_candidates(web_world(world, monkeypatch))
    assert search(world, w["task"], confirm=False)["confirmed"] is False and w["run"].calls == []      # no confirm: nothing is run
    w["routing"]["web"] = False
    assert "web_no_web" in refused(search, world, w["task"]) and w["run"].calls == []      # a pair that was not measured with the web: nothing is run
    w["routing"]["web"] = True
    ctx = ops_core.context(world["path"])
    ctx["store"].cursor_set(ctx["conn"], policy_widening.ACCOUNTS, json.dumps({"v": 1, "items": ""}))
    assert "stock_not_accepted" in refused(search, world, w["task"]) and w["run"].calls == []      # the item of the open web was not accepted: nothing is run
    accepted(world)
    done = search(world, w["task"])
    [call] = w["run"].calls
    assert done["confirmed"] is True and call["open_web"] is True and call["sourced"] == () and call["prompt"].strip() == ops_media_websearch._render_prompt(
        [{"slot": "beat7", "want": "image", "search": "market stall"}])      # the words of the slots and nothing else
    assert not Path(call["dest"]).exists(), "its folder is removed"
    w["run"].document = web_document([web_candidate("beat9", 1)])
    assert "candidates_invalid" in refused(search, world, w["task"]), "its answer is checked"


def test_limit_79_a_link_a_model_wrote_is_opened_only_by_the_open_web_provider_and_is_in_no_answer_or_run_row(world, monkeypatch):
    modules = {p.name for p in (REPO / "runtime").glob("*.py") if '"--url"' in p.read_text(encoding="utf-8") and "stock:media" in p.read_text(encoding="utf-8") or p.name == "ops_media_websearch.py"}
    assert modules == {"ops_media_stock.py", "ops_media_websearch.py"}, "the only runtime files that hand a link to a source of the class `stock:media`"
    for name in modules:
        text = (REPO / "runtime" / name).read_text(encoding="utf-8")
        assert not re.search(r"urlopen|http\.client|import requests|socket\.create_connection|import urllib\.request", text), name
        assert "sources.call(" in text, "a link goes through the class `stock:media`, never opened here"
    w = with_candidates(web_world(world, monkeypatch))
    set_media(world, web_refused_hosts=["blocked.example"])
    done = search(world, w["task"])
    assert [c["flags"][c["flags"].index("--refuse-host") + 1] for c in w["sources"].of("preview", "web")] == ["blocked.example"] * 2, "the person's lists are passed to it"
    ctx = ops_core.context(world["path"])
    assert LINK_MARK not in json.dumps(done) and LINK_MARK not in "\n".join(ctx["conn"].iterdump())
