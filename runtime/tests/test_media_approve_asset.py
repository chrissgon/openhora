"""Tests of the approval of one file found on the open web (package V9b-3b, decision D6, limit L80): `video-media-approve-asset` in the terminal and on the page, the set approval that no longer
waits for it (C5), the clip rule (C6) and an offline walk from the web search to the render. The run of the skill is a stand-in, the sources are the fake of the class `stock:media`
(its `fetch` by link writes a flat-colour PNG into the quarantine), the renderer's `asset-sheet` a fake, and the store, the approval and the step's own checks are the real ones. Nothing is
called, no search is run, no link is opened; every name is invented and every host ends in `.example`.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_approve_asset.py
"""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import flag, ops, ops_core, run_task, world  # noqa: F401  (the fixture)
from media_stock_kit import REPO, LINK_MARK, configure, media_stock, ops_media_stock, ops_media_websearch, pick, review_of, web_candidate, web_document, web_world
from test_step_media_assets import delivered, go_on, layout_engine, stock_dir

operations = st.load("operations")
phrases = st.load("phrases")
ops_media = st.load("ops_media")

WARNING_EN = ("Copyright warning: this file was found on the open web, on {host}. The platform could not check who owns it or whether it may be reused, and the licence the page states, "
              "if any, was not checked. If you approve it and publish the video, the video may be taken down and your account may receive a copyright strike. Approve it only if you know you "
              "may use it. Source page: {page}")
WARNING_PT = ("Aviso de direitos autorais: este arquivo foi encontrado na internet, em {host}. A plataforma não conseguiu verificar quem é o dono nem se ele pode ser reutilizado, e a "  # validate: allow english-only -- the approved pt-BR warning
              "licença que a página diz ter, se houver, não foi verificada. Se você aprovar e publicar o vídeo, ele pode ser removido e sua conta pode receber uma advertência por direitos "  # validate: allow english-only -- the approved pt-BR warning
              "autorais. Aprove só se souber que pode usá-lo. Página de origem: {page}")  # validate: allow english-only -- the approved pt-BR warning
PAGE = web_candidate("beat7", 1)["page_url"]


def walk(world, monkeypatch, set_approved=True, stock="default", **more):
    """A video whose one slot got a candidate from the web search, picked, fetched, and its set approved (when `set_approved`): the web path from the search to the approval of the set."""
    layout_engine(world["engine"])
    w = web_world(world, monkeypatch, stock=stock)
    w["run"].document = web_document([web_candidate("beat7", 1, **more), web_candidate("beat7", 2)])
    done = ops.video_media_websearch(world["path"], w["task"], confirm=True)
    pick(world, w["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    ops.video_media_fetch_picks(world["path"], w["task"])
    shown = ops.video_media_approve(world["path"], w["task"])
    if set_approved:
        ops.video_media_approve(world["path"], w["task"], hash=shown["sha256"])
    return dict(w, done=done, shown=shown, sha=shown["set"]["assets"][0]["sha256"])


def approve_asset(world, w, confirm=None, slot="beat7", sha=None):
    return ops.video_media_approve_asset(world["path"], w["task"], slot, sha or w["sha"], confirm=confirm)


def approved_doc(world):
    return json.loads((stock_dir(world) / "approved.json").read_text())


def refused(call, *args, **kw) -> str:
    with pytest.raises(ops_core.OpsError) as caught:
        call(*args, **kw)
    return str(caught.value)


# --- the refusals, each with nothing written --------------------------------------------------------------------------------------------------


def test_each_refusal_writes_nothing(world, monkeypatch):
    w = walk(world, monkeypatch)
    before = (stock_dir(world) / "approved.json").read_bytes()
    folder_before = sorted(os.listdir(stock_dir(world)))
    cases = [
        ({"slot": "beat9"}, "not_unverified"),
        ({"sha": "1" * 64}, "wrong_hash"),
        ({"confirm": w["sha"][:11]}, "wrong_confirm"),
        ({"confirm": "0" * 12}, "wrong_confirm"),
        ({"confirm": w["sha"][:12].upper()}, "wrong_confirm"),
    ]
    for kwargs, code in cases:
        assert code in refused(approve_asset, world, w, **kwargs), kwargs
    for bad in (("Beat 7", w["sha"]), ("beat7", "abc"), ("beat7", w["sha"].upper())):
        with pytest.raises(ops_core.OpsError):
            ops.video_media_approve_asset(world["path"], w["task"], *bad)
    with pytest.raises(ops_core.OpsError):
        ops.video_media_approve_asset(world["path"], w["task"], "beat7", w["sha"], confirm=12)
    assert (stock_dir(world) / "approved.json").read_bytes() == before and sorted(os.listdir(stock_dir(world))) == folder_before


def test_a_video_that_does_not_wait_at_the_review_or_has_no_fetched_set_or_an_unapproved_one_is_refused(world, monkeypatch):
    w = walk(world, monkeypatch, set_approved=False)
    assert "not_approved" in refused(approve_asset, world, w) and not (stock_dir(world) / "approved.json").exists()      # the set comes first
    ops.video_media_approve(world["path"], w["task"], hash=w["shown"]["sha256"])
    (stock_dir(world) / ("asset-%s.png" % w["sha"][:12])).write_bytes(b"\x89PNG\r\n\x1a\nswapped")      # a file swapped under the same name
    assert "asset_changed" in refused(approve_asset, world, w)
    ctx = ops_core.context(world["path"])
    ctx["store"].step_task_move(ctx["conn"], w["task"], state="running", note=None, by="code")
    assert "not_at_review" in refused(approve_asset, world, w)


def test_with_no_fetched_set_nothing_can_be_approved(world, monkeypatch):
    layout_engine(world["engine"])
    w = web_world(world, monkeypatch)
    assert "no_set" in refused(approve_asset, world, w, sha="a" * 64)
    w["run"].document = web_document([web_candidate("beat7", 1)])
    ops.video_media_websearch(world["path"], w["task"], confirm=True)      # found, not fetched
    assert "no_set" in refused(approve_asset, world, w, sha="a" * 64)


def test_a_licensed_file_is_not_an_unverified_one_and_the_web_source_must_still_be_on(world, monkeypatch):
    layout_engine(world["engine"])
    found = web_world(world, monkeypatch)
    found["sources"].licences = {"shelf": "cc0-1.0"}
    done = ops.video_media_find(world["path"], found["task"], confirm=True)
    licensed = next(c["pick"] for c in done["slots"][0]["candidates"] if c["source"] == "shelf")
    pick(world, found["task"], "beat7", licensed, review_of(world)["revision"])
    ops.video_media_fetch_picks(world["path"], found["task"])
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    sha = shown["set"]["assets"][0]["sha256"]
    assert "not_unverified" in refused(ops.video_media_approve_asset, world["path"], found["task"], "beat7", sha)
    assert shown["needs_own_approval"] == []


def test_when_the_web_was_turned_off_after_the_set_was_approved_the_file_cannot_be_approved(world, monkeypatch):
    w = walk(world, monkeypatch)
    configure(world, monkeypatch, ["shelf"])
    assert "web_off" in refused(approve_asset, world, w) and approved_doc(world)["unverified"] == {}


# --- the warning, the record and the walk ------------------------------------------------------------------------------------------------------


def test_without_confirm_it_shows_the_warning_the_host_the_page_and_the_claim_and_writes_nothing(world, monkeypatch):
    w = walk(world, monkeypatch, screen_work=True)
    before = (stock_dir(world) / "approved.json").read_bytes()
    shown = approve_asset(world, w)
    scan = shown.pop("scan")      # P9-a: the scan's rows of this one file, shown in its box (tests: test_media_scan.py)
    assert scan["state"] == "done" and scan["clean"] == ["beat7"] and scan["rows"] == []
    assert shown == {"approved": False, "slot": "beat7", "sha256": w["sha"], "file": "asset-%s.png" % w["sha"][:12], "host": "pages.example", "page": PAGE,
                     "licence_claim": "free to use, says the page", "licence_claim_note": "claimed by the page, not checked", "screen_work": True,
                     "warning": WARNING_EN.format(host="pages.example", page=PAGE), "confirm": "--confirm-digits " + w["sha"][:12]}
    assert (stock_dir(world) / "approved.json").read_bytes() == before and approved_doc(world)["unverified"] == {}
    assert LINK_MARK not in json.dumps(shown), "the link of the file is nobody's"


def test_the_warning_is_the_approved_text_in_english_and_in_portuguese(world, monkeypatch):
    table = lambda tag: json.loads((REPO / "runtime" / "phrases_parts" / ("v9b-3b.%s.json" % tag)).read_text(encoding="utf-8"))["table"]      # noqa: E731
    assert table("en")["VID_WEB_WARNING"] == WARNING_EN and table("pt-BR")["VID_WEB_WARNING"] == WARNING_PT
    assert table("en")["VID_WEB_NOT_BUILT"] == "The web search is not set up here; the licensed sources were searched."
    assert table("en")["VID_WEB_NO_WEB"] == "The chosen model cannot search the web here; the licensed sources were searched."
    assert table("en")["VID_WEB_NEEDS_OWN"] == "This file needs its own approval after the warning."
    assert "plataforma" in table("pt-BR")["VID_WEB_WARNING"].lower() and "bancada" not in json.dumps(table("pt-BR")).lower()
    assert phrases.text("VID_WEB_WARNING", {"language": "pt-BR"}, host="pages.example", page=PAGE) == WARNING_PT.format(host="pages.example", page=PAGE)
    assert phrases.text("VID_WEB_WARNING", {"language": "en"}, host="pages.example", page=PAGE) == WARNING_EN.format(host="pages.example", page=PAGE)
    for key in table("en"):
        assert set(table("en")) == set(table("pt-BR")), key
        assert phrases.text(key, {"language": "pt-BR"}, host="h", page="p", words="w", count=1, slots="s") and phrases.text(key, {"language": "en"}, host="h", page="p", words="w", count=1, slots="s")


def test_with_the_first_twelve_digits_it_writes_the_record_the_step_reads_and_keeps_the_rest_of_the_approval(world, monkeypatch):
    w = walk(world, monkeypatch)
    before = approved_doc(world)
    assert before["unverified"] == {} and w["shown"]["needs_own_approval"] == ["beat7"]
    done = approve_asset(world, w, confirm=w["sha"][:12])
    assert done == {"approved": True, "slot": "beat7", "sha256": w["sha"]}
    after = approved_doc(world)
    [entry] = after["unverified"].values()
    assert set(entry) == {"sha256", "task", "at", "channel"} and entry["sha256"] == w["sha"] and entry["task"] == w["task"] and entry["channel"] == "terminal"
    assert {k: v for k, v in after.items() if k != "unverified"} == {k: v for k, v in before.items() if k != "unverified"}, "the hash and the rest are unchanged"
    shown = ops.video_media_approve(world["path"], w["task"])
    assert shown["approved"] is True and shown["needs_own_approval"] == [] and shown["own_approved"] == ["beat7"]
    page = ops.video_media_approve_asset(world["path"], w["task"], "beat7", w["sha"], confirm=w["sha"][:12], channel="page")
    assert page["approved"] is True and approved_doc(world)["unverified"]["beat7"]["channel"] == "page"


def test_a_new_pick_voids_it_and_the_same_set_approved_again_keeps_it(world, monkeypatch):
    w = walk(world, monkeypatch)
    approve_asset(world, w, confirm=w["sha"][:12])
    again = ops.video_media_approve(world["path"], w["task"], hash=w["shown"]["sha256"])      # the same hash again: what was approved file by file stays
    assert again["approved"] is True and again["needs_own_approval"] == [] and set(approved_doc(world)["unverified"]) == {"beat7"}
    other = next(c["pick"] for c in w["done"]["slots"][0]["candidates"] if c["pick"] != review_of(world)["slot_assets"]["beat7"])
    pick(world, w["task"], "beat7", other, review_of(world)["revision"])      # another pick: the whole approval goes
    assert not (stock_dir(world) / "approved.json").exists()
    ops.video_media_fetch_picks(world["path"], w["task"])
    fresh = ops.video_media_approve(world["path"], w["task"])
    assert fresh["approved"] is False and fresh["needs_own_approval"] == ["beat7"]


def test_the_set_approval_no_longer_waits_for_the_files_and_lists_what_still_needs_its_own(world, monkeypatch):
    w = walk(world, monkeypatch, set_approved=False)
    assert w["shown"]["needs_own_approval"] == ["beat7"] and w["shown"]["own_approved"] == [] and w["shown"]["approved"] is False
    done = ops.video_media_approve(world["path"], w["task"], hash=w["shown"]["sha256"])
    assert done["approved"] is True and done["needs_own_approval"] == ["beat7"] and done["own_approved"] == []
    approve_asset(world, w, confirm=w["sha"][:12])
    done = ops.video_media_approve(world["path"], w["task"], hash=w["shown"]["sha256"])
    assert done["needs_own_approval"] == [] and done["own_approved"] == ["beat7"]


def test_an_own_approval_for_another_task_or_another_hash_does_not_count_in_the_listing(world, monkeypatch):
    w = walk(world, monkeypatch)
    approved = approved_doc(world)
    media_stock.write_doc(world["data"], world["rid"], "approved.json", dict(approved, unverified={"beat7": {"sha256": w["sha"], "task": w["task"] + 1, "at": "x", "channel": "terminal"}}))
    assert ops.video_media_approve(world["path"], w["task"])["needs_own_approval"] == ["beat7"]
    media_stock.write_doc(world["data"], world["rid"], "approved.json", dict(approved, unverified={"beat7": {"sha256": "1" * 64, "task": w["task"], "at": "x", "channel": "terminal"}}))
    assert ops.video_media_approve(world["path"], w["task"])["needs_own_approval"] == ["beat7"]


def test_an_offline_walk_from_the_search_to_the_render_and_the_download_with_the_source_page(world, monkeypatch):
    w = walk(world, monkeypatch)
    out = go_on(world, w["task"])
    assert out["ok"] is False and out["code"] == "media_not_approved" and not world["engine"].of("render"), "the set alone is not enough for a file nobody checked"
    approve_asset(world, w, confirm=w["sha"][:12])      # the repair state of a Continue the set stopped accepts it
    out = run_task(world, w["task"])
    assert out["ok"] is True and out["stopped"] == "deliver"
    assert flag(world["engine"].of("render")[-1]["args"], "--asset-sha256") == "beat7=" + w["sha"]
    gate, doc = delivered(world, w["task"])
    [entry] = doc["web"]
    assert entry["page_host"] == "pages.example" and PAGE not in json.dumps(doc) and PAGE not in json.dumps(gate["payload"]["card"]) and LINK_MARK not in json.dumps(doc)
    assert ["CARD_VIDEO_WEB", {"host": "pages.example"}] in gate["payload"]["card"]
    ops.approve(world["path"], gate["id"], sha256=gate["payload_sha256"], channel="terminal")
    done = ops_media.video_download(world["path"], w["task"], out=str(Path(world["tmp"]) / "out.mp4"), channel="terminal")
    assert done["source_pages"] == ["Source page: " + PAGE], "the download is loopback only: the address may be in its answer"
    assert ops.video_credits(world["path"], w["task"], channel="page")["web"][0]["page"] == PAGE


def test_a_second_task_cannot_use_the_approval_of_the_first(world, monkeypatch):
    w = walk(world, monkeypatch)
    approve_asset(world, w, confirm=w["sha"][:12])
    approved = approved_doc(world)
    media_stock.write_doc(world["data"], world["rid"], "approved.json", dict(approved, task=w["task"] + 1, unverified={"beat7": dict(approved["unverified"]["beat7"], task=w["task"] + 1)}))
    out = go_on(world, w["task"])
    assert out["ok"] is False and out["code"] == "media_not_approved" and not world["engine"].of("render")


# --- the clip rule ---------------------------------------------------------------------------------------------------------------------------


def test_a_web_candidate_of_kind_clip_planted_in_the_set_is_refused_by_the_fetch_before_anything_is_fetched(world, monkeypatch):
    monkeypatch.setattr(ops_media_stock.media_animation, "asset_kinds", lambda root, implementation=None: ["image"])      # V9b-5c: the real catalogue now lists clips; an engine without them still refuses
    layout_engine(world["engine"])
    w = web_world(world, monkeypatch)
    w["run"].document = web_document([web_candidate("beat7", 1)])
    done = ops.video_media_websearch(world["path"], w["task"], confirm=True)
    found = json.loads((stock_dir(world) / "set.json").read_text())
    found["slots"][0]["candidates"][0]["kind"] = "clip"
    media_stock.write_doc(world["data"], world["rid"], "set.json", found)
    pick(world, w["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    message = refused(ops.video_media_fetch_picks, world["path"], w["task"])
    assert "clip_not_drawn" in message and w["sources"].of("fetch") == []
    assert "kind" in inspect.getsource(media_stock.read_web_candidates)


# --- where it can be called from ---------------------------------------------------------------------------------------------------------------


def test_the_two_operations_answer_the_terminal_and_the_page_only_and_are_not_served_in_words(world):
    for name in ("video-media-websearch", "video-media-approve-asset"):
        row = operations.by_name(name)
        assert set(row["channels"]) == {"terminal", "page"} and name in operations.LAN_REFUSED_OPS and name in operations.GROUPS["media"]["operations"]
        assert row["natural"]["class"] == "G" and "mcp" not in row["channels"] and "messaging" not in row["channels"]
    assert operations.by_name("video-media-websearch")["job"] is True and not operations.by_name("video-media-approve-asset").get("job")
    assert (operations.by_name("video-media-websearch")["natural"]["privacy"], operations.by_name("video-media-websearch")["natural"]["cost"]) == ("off-host", "model")
    assert (operations.by_name("video-media-approve-asset")["natural"]["privacy"], operations.by_name("video-media-approve-asset")["natural"]["cost"]) == ("own", "none")
    gated = {r["op"]: r for r in json.loads((REPO / "runtime" / "gated_ops.json").read_text(encoding="utf-8"))["rows"]}
    assert gated["video-media-websearch"]["kind"] == gated["video-media-approve-asset"]["kind"] == "internal"
    catalog = (REPO / "runtime" / "interpreter_catalog.json").read_text(encoding="utf-8")
    assert "video-media-approve-asset" not in catalog and "video-media-websearch" not in catalog, "not in the catalog a line in words reaches"
    for channel in ("messaging", "mcp", "chat", "queue"):
        for call, args in ((ops.video_media_websearch, (1,)), (ops.video_media_approve_asset, (1, "beat7", "a" * 64))):
            with pytest.raises(ops_core.OpsError):
                call("/nowhere", *args, channel=channel)
    assert list(inspect.signature(ops.video_media_approve_asset).parameters) == ["project", "task_id", "slot", "sha256", "confirm", "channel"], "one slot at a time: no bulk form"
    routes = {r["op"]: r for r in st.load("service").ROUTES if r["op"]}
    assert routes["video-media-websearch"]["take"] == ("confirm",) and routes["video-media-approve-asset"]["take"] == ("slot", "sha256", "confirm")
    assert ops_media_websearch.ops_media_stock is ops_media_stock and ops.video_media_websearch is ops_media_websearch.video_media_websearch


def test_limit_80_a_file_found_on_the_web_is_used_only_after_its_own_approval_bound_to_this_task_and_this_hash(world, monkeypatch):
    w = walk(world, monkeypatch)
    assert go_on(world, w["task"])["code"] == "media_not_approved" and not world["engine"].of("render")      # the set alone is not enough
    for channel in ("messaging", "mcp", "chat", "queue"):
        with pytest.raises(ops_core.OpsError):
            ops.video_media_approve_asset(world["path"], w["task"], "beat7", w["sha"], confirm=w["sha"][:12], channel=channel)
    assert "unverified" in approved_doc(world) and approved_doc(world)["unverified"] == {}
    assert "wrong_confirm" in refused(approve_asset, world, w, confirm="f" * 12)      # the first 12 digits of this file's sha256, typed or sent
    approve_asset(world, w, confirm=w["sha"][:12])
    [entry] = approved_doc(world)["unverified"].values()
    assert entry["task"] == w["task"] and entry["sha256"] == w["sha"]      # bound to this task and this sha256
    assert "video-media-approve-asset" in operations.LAN_REFUSED_OPS and "mcp" not in operations.by_name("video-media-approve-asset")["channels"]
    media_stock.write_doc(world["data"], world["rid"], "approved.json", dict(approved_doc(world), unverified={"beat7": dict(entry, task=w["task"] + 1)}))
    assert run_task(world, w["task"])["code"] == "media_not_approved", "never carried to another task"


# --- a web clip (package V9b-5c) ---------------------------------------------------------------------------------------------------------------------


def walk_clip(world, monkeypatch):
    """The web path for a clip slot: found, picked, fetched (the fake renderer makes an `.mp4` of the file the web provider fetched), the set approved, a cutaway layout for the slot in the proposal."""
    layout_engine(world["engine"])
    w = web_world(world, monkeypatch, {"beat7": ("market stall", "clip")})
    data, rid = world["data"], world["rid"]
    beats = json.loads(ops_media_stock.media.read_work(data, rid, "proposal.beats.json", 1 << 20))
    beats["layouts"] = [{"id": "b7", "beat": 7, "preset": "cutaway", "block": "oh:cutaway", "params": {"asset": "beat7"}, "word_from": 0, "word_to": 3}]
    ops_media_stock.media.write_work(data, rid, "proposal.beats.json", json.dumps(beats).encode("utf-8"))
    edl = json.loads(ops_media_stock.media.read_work(data, rid, "proposal.edl.json", 1 << 20))
    ops_media_stock.media.write_work(data, rid, "proposal.edl.json", json.dumps(dict(edl, fps=30)).encode("utf-8"))
    w["run"].document = web_document([web_candidate("beat7", 1, kind="clip"), web_candidate("beat7", 2, kind="clip")])
    done = ops.video_media_websearch(world["path"], w["task"], confirm=True)
    pick(world, w["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    answer = ops.video_media_fetch_picks(world["path"], w["task"])
    shown = ops.video_media_approve(world["path"], w["task"])
    ops.video_media_approve(world["path"], w["task"], hash=shown["sha256"])
    return dict(w, done=done, answer=answer, shown=shown, sha=shown["set"]["assets"][0]["sha256"])


def test_a_web_clip_is_sent_to_the_search_with_the_real_catalogue_and_the_prompt_says_a_clip(world, monkeypatch):
    w = web_world(world, monkeypatch, {"beat7": ("market stall", "image"), "beat8": ("fruit crate", "clip")})
    w["run"].document = web_document([web_candidate("beat7", 1), web_candidate("beat8", 1, kind="clip")])
    shown = ops.video_media_websearch(world["path"], w["task"], confirm=False)
    assert [s["slot"] for s in shown["slots"]] == ["beat7", "beat8"] and not shown.get("skipped")
    ops.video_media_websearch(world["path"], w["task"], confirm=True)
    prompt = w["run"].calls[0]["prompt"]
    assert "Slot `beat8`: a clip" in prompt and "Slot `beat7`: a picture" in prompt


def test_a_previewless_web_clip_can_be_picked_fetched_and_approved(world, monkeypatch):
    layout_engine(world["engine"])
    w = web_world(world, monkeypatch, {"beat7": ("market stall", "clip")})
    data, rid = world["data"], world["rid"]
    beats = json.loads(ops_media_stock.media.read_work(data, rid, "proposal.beats.json", 1 << 20))
    beats["layouts"] = [{"id": "b7", "beat": 7, "preset": "cutaway", "block": "oh:cutaway", "params": {"asset": "beat7"}, "word_from": 0, "word_to": 3}]
    ops_media_stock.media.write_work(data, rid, "proposal.beats.json", json.dumps(beats).encode("utf-8"))
    edl = json.loads(ops_media_stock.media.read_work(data, rid, "proposal.edl.json", 1 << 20))
    ops_media_stock.media.write_work(data, rid, "proposal.edl.json", json.dumps(dict(edl, fps=30)).encode("utf-8"))
    clip = web_candidate("beat7", 1, kind="clip")
    clip.pop("thumb_url")
    w["run"].document = web_document([clip])
    done = ops.video_media_websearch(world["path"], w["task"], confirm=True)
    assert done["slots"][0]["candidates"][0]["preview"] is False
    pick(world, w["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    answer = ops.video_media_fetch_picks(world["path"], w["task"])
    [call] = [c for c in w["sources"].of("fetch") if clip["media_url"] in c["flags"]]
    assert call["flags"][call["flags"].index("--kind") + 1] == "clip" and call["flags"][call["flags"].index("--out") + 1].endswith(os.path.join("stock", "quarantine"))
    assert answer["assets"][0]["kind"] == "clip" and answer["assets"][0]["file"] is None
    shown = ops.video_media_approve(world["path"], w["task"])
    ops.video_media_approve(world["path"], w["task"], hash=shown["sha256"])
    sha = shown["set"]["assets"][0]["sha256"]
    seen = approve_asset(world, dict(w, sha=sha))
    assert seen["file"] == "sheet.png" and seen["approved"] is False


def test_approve_asset_of_a_web_clip_shows_the_sheet_and_its_own_approval_binds_the_clip(world, monkeypatch):
    w = walk_clip(world, monkeypatch)
    assert w["answer"]["assets"][0]["kind"] == "clip" and w["answer"]["assets"][0]["file"] is None
    shown = approve_asset(world, w)
    assert shown["approved"] is False and shown["file"] == "sheet.png" and shown["confirm"] == "--confirm-digits " + w["sha"][:12]
    done = approve_asset(world, w, confirm=w["sha"][:12])
    assert done["approved"] is True
    assert approved_doc(world)["unverified"]["beat7"]["sha256"] == w["sha"]

