"""Tests of the pictures of the media set in the step kind `media` (package V9b-3a, limit L76): Continue is refused while a pick is not approved, the renderer is handed a picture only
when the approval holds, a file swapped under the same name fails, the credits of a CC BY picture ride the delivery document, the card and the body, and the seam for a picture
nobody checked (a planted synthetic candidate: the open-web path itself is another package) needs its own approval for this task, this sha256 and a source still in use. The engine is
the fake of media_kit; every picture is a flat-colour PNG made with zlib; nothing is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_media_assets.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import flag, media, open_items, ops, ops_core, ops_step_seams, run_task, step_media, steps, task_row, to_gate, work_file, world  # noqa: F401
from media_stock_kit import SLOT_SOURCE, configure, media_stock, ops_media_stock, png, review_of, sha, to_found, FakeSheets, FakeSources, pick

deliver_document = st.load("deliver_document")
captions = st.load("captions")
PAGE = "https://pics.example/gallery/aster-lane-market?id=7"


def layout_engine(engine, slot="beat7"):
    """The fake renderer's `align` with a script slot: the proposal lists the slot, the final beats hold a cutaway layout that asks for its picture."""
    def align(a):
        out = flag(a, "--out")
        if out.endswith("proposal.beats.json"):
            Path(out).write_text(json.dumps({"report": [{"beat": 7, "preset": "cutaway", "matched": True}], "slots": [dict(SLOT_SOURCE, slot=slot)]}))
        else:
            asked = [a[i + 1] for i, x in enumerate(a) if x == "--empty-slot"]
            engine.asked_empty = asked
            layouts = [] if any(x.startswith(slot + "=") for x in asked) else [{"id": "b7", "beat": 7, "preset": "cutaway", "params": {"asset": slot}, "word_from": 0, "word_to": 3, "score": 1.0}]
            Path(out).write_text(json.dumps({"overlays": [], "layouts": layouts}))
        return {"ok": True, "beats": 1, "overlays": 0, "layouts": 1, "unmatched": []}
    engine._align = align
    engine.asked_empty = []


def approved_video(world, monkeypatch, licence="cc0-1.0"):
    """A video with a picture found, picked, fetched and approved, waiting at the review. Returns the world of stock_kit."""
    layout_engine(world["engine"])
    found = to_found(world, monkeypatch)
    found["sources"].licences = {"shelf": licence}
    done = ops.video_media_find(world["path"], found["task"], confirm=True)
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    ops.video_media_fetch_picks(world["path"], found["task"])
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    return dict(found, shown=shown)


def go_on(world, task):
    [review] = open_items(world, task)
    ops.answer(world["path"], review["id"], "continue")
    return run_task(world, task)


def stock_dir(world) -> Path:
    return Path(media_stock.folder_of(world["data"], world["rid"]))


# --- Continue and the render ----------------------------------------------------------------------------------------------------------------------


def test_continue_is_refused_while_a_pick_is_not_approved_and_the_next_step_says_what_to_do(world, monkeypatch):
    layout_engine(world["engine"])
    found = to_found(world, monkeypatch)
    done = ops.video_media_find(world["path"], found["task"], confirm=True)
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    out = go_on(world, found["task"])
    assert out["ok"] is False and out["code"] == "media_not_approved" and out["failed"] == "remap"
    assert out["next"] == "Approve the media set, or clear the picks, before you continue." and not world["engine"].of("render")
    ops.video_media_fetch_picks(world["path"], found["task"])      # fetched but not approved: still refused
    assert run_task(world, found["task"])["code"] == "media_not_approved"
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    out = run_task(world, found["task"])
    assert out["ok"] is True and out["stopped"] == "deliver"


def test_a_slot_with_the_choice_stock_and_no_pick_reads_as_none_and_the_render_gets_no_picture(world, monkeypatch):
    layout_engine(world["engine"])
    found = to_found(world, monkeypatch)
    out = go_on(world, found["task"])
    assert out["ok"] is True and out["stopped"] == "deliver"
    assert world["engine"].asked_empty == ["beat7=none"]
    assert "--asset" not in world["engine"].of("render")[-1]["args"]


def test_an_approved_picture_is_handed_to_the_renderer_with_its_hash_and_its_slot_is_not_passed_as_empty(world, monkeypatch):
    video = approved_video(world, monkeypatch)
    out = go_on(world, video["task"])
    assert out["ok"] is True and out["stopped"] == "deliver"
    assert world["engine"].asked_empty == []
    [asset] = video["shown"]["set"]["assets"]
    args = world["engine"].of("render")[-1]["args"]
    path = stock_dir(world) / ("asset-%s.png" % asset["sha256"][:12])
    assert flag(args, "--asset") == "beat7=" + str(path) and flag(args, "--asset-sha256") == "beat7=" + asset["sha256"]
    assert args.count("--asset") == 1
    state = task_row(world, video["task"])["step_state"]
    assert state["steps"]["render"]["result"]["pictures"] == 1 and state["steps"]["align"]["result"]["pictures"] == 1


def test_the_beats_that_use_no_picture_pass_no_asset_even_when_the_set_has_one(world, monkeypatch):
    video = approved_video(world, monkeypatch)
    engine = world["engine"]

    def plain_align(a):
        out = flag(a, "--out")
        Path(out).write_text(json.dumps({"report": [], "slots": [dict(SLOT_SOURCE)]} if out.endswith("proposal.beats.json") else {"overlays": [], "layouts": []}))
        return {"ok": True, "beats": 1, "overlays": 0, "layouts": 0, "unmatched": []}
    engine._align = plain_align
    out = go_on(world, video["task"])
    assert out["ok"] is True and "--asset" not in engine.of("render")[-1]["args"]


def test_a_file_swapped_under_the_same_name_fails_before_the_renderer_is_asked(world, monkeypatch):
    video = approved_video(world, monkeypatch)
    [asset] = video["shown"]["set"]["assets"]
    path = stock_dir(world) / ("asset-%s.png" % asset["sha256"][:12])
    path.chmod(0o600)
    path.write_bytes(png(3, 3, (255, 0, 0)))
    out = go_on(world, video["task"])
    assert out["ok"] is False and out["code"] == "asset_changed" and not world["engine"].of("render")


def test_a_pick_that_is_not_the_approved_one_or_a_set_of_another_task_or_a_changed_set_is_not_approved(world, monkeypatch):
    video = approved_video(world, monkeypatch)
    doc = json.loads((stock_dir(world) / "set.json").read_text())
    approved = json.loads((stock_dir(world) / "approved.json").read_text())
    review = review_of(world)
    media.write_work(world["data"], world["rid"], "review.json", json.dumps(dict(review, slot_assets={"beat7": "shelf:another-item"})).encode())
    assert go_on(world, video["task"])["code"] == "media_not_approved"
    media.write_work(world["data"], world["rid"], "review.json", json.dumps(review).encode())
    media_stock.write_doc(world["data"], world["rid"], "approved.json", dict(approved, task=video["task"] + 1))
    assert run_task(world, video["task"])["code"] == "media_not_approved"
    media_stock.write_doc(world["data"], world["rid"], "approved.json", approved)
    changed = dict(doc, assets=[dict(doc["assets"][0], title="Another title")])
    media_stock.write_doc(world["data"], world["rid"], "set.json", changed)
    assert run_task(world, video["task"])["code"] == "media_not_approved"      # the approval binds the hash of the set document, which holds the title
    media_stock.write_doc(world["data"], world["rid"], "set.json", doc)
    assert run_task(world, video["task"])["stopped"] == "deliver"


def test_a_licence_outside_the_tuple_is_never_rendered_even_with_the_set_approved(world, monkeypatch):
    video = approved_video(world, monkeypatch)
    doc = json.loads((stock_dir(world) / "set.json").read_text())
    doc["assets"][0]["licence"] = "cc-by-sa-4.0"
    media_stock.write_doc(world["data"], world["rid"], "set.json", doc)
    approved = json.loads((stock_dir(world) / "approved.json").read_text())
    media_stock.write_doc(world["data"], world["rid"], "approved.json", dict(approved, hash=step_media.stock_hash(doc)))      # even an approval that binds this very set
    assert go_on(world, video["task"])["code"] == "media_not_approved" and not world["engine"].of("render")


# --- the credits ------------------------------------------------------------------------------------------------------------------------------


def delivered(world, task):
    [gate] = open_items(world, task)
    doc = ops_step_seams.EffectFiles(ops_core.context(world["path"])["cfg"]).read(task, 0, gate["payload_sha256"])
    return gate, doc


def test_a_cc_by_picture_puts_its_credit_in_the_document_the_card_and_the_body_and_a_cc0_one_puts_none(world, monkeypatch):
    video = approved_video(world, monkeypatch, "cc-by-4.0")
    out = go_on(world, video["task"])
    assert out["stopped"] == "deliver"
    gate, doc = delivered(world, video["task"])
    [credit] = doc["credits"]
    assert credit.startswith("\"A picture of market stall\" by Bram Hollow, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), via shelf")
    assert doc["assets"][0]["licence"] == "cc-by-4.0" and doc["assets"][0]["slot"] == "beat7" and "web" not in doc
    keys = [line[0] for line in gate["payload"]["card"]]
    assert "CARD_VIDEO_ASSET" in keys and "CARD_VIDEO_CREDITS" in keys and ["CARD_VIDEO_CREDIT", {"credit": credit}] in gate["payload"]["card"]
    assert "Credit to put in the caption" in gate["body"] and credit in gate["body"] and "Picture: beat7, shelf, cc-by-4.0, sha256 " in gate["body"]
    assert gate["payload"]["effect"]["assets"] == 1 and gate["payload"]["effect"]["credits"] == 1


def test_a_cc0_picture_and_a_video_with_no_picture_leave_the_document_as_it_always_was(world, monkeypatch):
    video = approved_video(world, monkeypatch, "cc0-1.0")
    go_on(world, video["task"])
    gate, doc = delivered(world, video["task"])
    assert doc["assets"][0]["licence"] == "cc0-1.0" and "credits" not in doc and "web" not in doc
    assert not any(line[0] in ("CARD_VIDEO_CREDITS", "CARD_VIDEO_CREDIT") for line in gate["payload"]["card"])


def test_a_video_with_no_stock_has_the_document_summary_and_card_it_always_had(world):
    task, gate = to_gate(world)
    doc = ops_step_seams.EffectFiles(ops_core.context(world["path"])["cfg"]).read(task, 0, gate["payload_sha256"])
    assert set(doc) == set(deliver_document.KEYS) and "assets" not in gate["payload"]["effect"]
    assert not any(line[0] in ("CARD_VIDEO_ASSET", "CARD_VIDEO_WEB") for line in gate["payload"]["card"])


# --- the seam for a picture nobody checked (a planted synthetic candidate) -----------------------------------------------------------------------------


def plant_unverified(world, monkeypatch, own=True, stock=("shelf", "web")):
    """A video whose set holds one picture of the licence `unverified` (written here, as the open-web path of another package would), approved as a set, with the approval of
    its own when `own`. Nothing is fetched from anywhere: the picture is a flat-colour PNG."""
    layout_engine(world["engine"])
    configure(world, monkeypatch, list(stock))
    task = to_found(world, monkeypatch, stock=list(stock))["task"]
    data = png(1080, 1920, (200, 100, 50))
    digest = sha(data)
    folder = stock_dir(world)
    ops_media_stock.media_stock.ensure_folder(world["data"], world["rid"])
    (folder / ("asset-%s.png" % digest[:12])).write_bytes(data)
    asset = {"slot": "beat7", "show": "a market", "search": "market stall", "source": "web", "item": "q-" + digest[:12], "kind": "image", "licence": "unverified", "licence_url": "",
             "terms_read_on": None, "author": "", "title": "Market", "page": PAGE, "licence_claim": "free for all", "sha256": digest, "width": 1080, "height": 1920,
             "seconds": None, "unverified": True}
    found = {"version": 1, "task": task, "phase": "fetched", "slots": [], "assets": [asset], "credits": [], "sources": list(stock)}
    media_stock.write_doc(world["data"], world["rid"], "set.json", found)
    approved = {"hash": step_media.stock_hash(found), "at": "2026-11-21T10:00:00Z", "task": task, "sources": list(stock), "assets": [], "unverified": {}}
    if own:
        approved["unverified"] = {"beat7": {"sha256": digest, "at": "2026-11-21T10:01:00Z", "channel": "terminal", "task": task}}
    media_stock.write_doc(world["data"], world["rid"], "approved.json", approved)
    media.write_work(world["data"], world["rid"], "review.json", json.dumps(dict(review_of(world), slot_assets={"beat7": "web:q-" + digest[:12]})).encode())
    return {"task": task, "digest": digest, "found": found, "approved": approved}


def test_the_unverified_seam_is_refused_with_only_the_set_approval(world, monkeypatch):
    plant = plant_unverified(world, monkeypatch, own=False)
    out = go_on(world, plant["task"])
    assert out["ok"] is False and out["code"] == "media_not_approved" and not world["engine"].of("render")


def test_the_unverified_seam_is_refused_with_an_own_approval_for_another_sha256(world, monkeypatch):
    plant = plant_unverified(world, monkeypatch, own=False)
    approved = dict(plant["approved"], unverified={"beat7": {"sha256": "1" * 64, "at": "x", "channel": "terminal", "task": plant["task"]}})
    media_stock.write_doc(world["data"], world["rid"], "approved.json", approved)
    assert go_on(world, plant["task"])["code"] == "media_not_approved" and not world["engine"].of("render")


def test_the_unverified_seam_is_refused_with_an_own_approval_from_another_task_so_nothing_is_reused(world, monkeypatch):
    plant = plant_unverified(world, monkeypatch, own=False)
    approved = dict(plant["approved"], unverified={"beat7": {"sha256": plant["digest"], "at": "x", "channel": "terminal", "task": plant["task"] + 1}})
    media_stock.write_doc(world["data"], world["rid"], "approved.json", approved)
    assert go_on(world, plant["task"])["code"] == "media_not_approved" and not world["engine"].of("render")
    media_stock.write_doc(world["data"], world["rid"], "approved.json", dict(plant["approved"], task=plant["task"] + 1))      # an approval written for another task as a whole
    assert run_task(world, plant["task"])["code"] == "media_not_approved"


def test_the_unverified_seam_is_refused_when_the_source_was_turned_off_after_the_approval(world, monkeypatch):
    plant = plant_unverified(world, monkeypatch)
    configure(world, monkeypatch, ["shelf"])      # the project stops using the open-web source and accepts the file
    out = go_on(world, plant["task"])
    assert out["ok"] is False and out["code"] == "media_not_approved" and not world["engine"].of("render")


def test_the_unverified_render_check_stops_a_picture_whose_own_approval_goes_after_the_continue(world, monkeypatch):
    plant = plant_unverified(world, monkeypatch)
    original = world["engine"]._check

    def withdraw(a):
        media_stock.write_doc(world["data"], world["rid"], "approved.json", dict(plant["approved"], unverified={}))      # the approval is taken away between the Continue and the render
        return original(a)
    world["engine"]._check = withdraw
    out = go_on(world, plant["task"])
    assert out["ok"] is False and out["code"] == "asset_not_approved" and not world["engine"].of("render")


def test_the_unverified_seam_is_accepted_when_everything_holds_and_the_document_binds_the_host_and_the_hash_of_the_page_not_the_address(world, monkeypatch):
    plant = plant_unverified(world, monkeypatch)
    out = go_on(world, plant["task"])
    assert out["ok"] is True and out["stopped"] == "deliver"
    args = world["engine"].of("render")[-1]["args"]
    assert flag(args, "--asset-sha256") == "beat7=" + plant["digest"]
    gate, doc = delivered(world, plant["task"])
    [entry] = doc["web"]
    assert entry == {"slot": "beat7", "sha256": plant["digest"], "page_host": "pics.example", "page_sha256": sha(PAGE.encode())}
    assert doc["assets"][0]["licence"] == "unverified" and "gallery" not in json.dumps(doc) and PAGE not in json.dumps(doc)
    assert "gallery" not in gate["body"] and PAGE not in gate["body"] and "Found on the web, licence not checked: pics.example" in gate["body"]
    card = gate["payload"]["card"]
    assert ["CARD_VIDEO_WEB", {"host": "pics.example"}] in card and ["CARD_VIDEO_WEB_PAGE", {"page": PAGE}] in card      # the card shows the address, read from the store
    assert "gallery" not in json.dumps(gate["payload"]["effect"])


def test_the_card_shows_an_address_only_when_it_is_the_one_the_document_names():
    host, page_sha = step_media._page_parts(PAGE)
    assert (host, page_sha) == ("pics.example", sha(PAGE.encode())) and step_media._page_parts("http://pics.example/x") == ("", "") and step_media._page_parts(None) == ("", "")
    doc = deliver_document.build(task=1, recording="a" * 16, platform="instagram", post="docs/marketing/content/x.md",
                                 video={"name": "render-%s.mp4" % ("b" * 12), "sha256": "b" * 64, "size": 10, "duration_ms": 5}, cover=None, verify_platform="instagram",
                                 assets=[{"slot": "beat7", "sha256": "c" * 64, "source": "web", "item": "q-" + "c" * 12, "licence": "unverified"}],
                                 web=[{"slot": "beat7", "sha256": "c" * 64, "page_host": host, "page_sha256": page_sha}])
    assert ["CARD_VIDEO_WEB_PAGE", {"page": PAGE}] in deliver_document.card_lines(doc, "d" * 64, {"beat7": PAGE})
    assert not any(line[0] == "CARD_VIDEO_WEB_PAGE" for line in deliver_document.card_lines(doc, "d" * 64, {}))
    assert not any(line[0] == "CARD_VIDEO_WEB_PAGE" for line in deliver_document.card_lines(doc, "d" * 64))


def test_limit_76_only_an_approved_picture_is_rendered(world, monkeypatch):
    video = approved_video(world, monkeypatch)
    media_stock.void_approval(world["data"], world["rid"])
    out = go_on(world, video["task"])
    assert out["code"] == "media_not_approved" and not world["engine"].of("render")
    shown = ops.video_media_approve(world["path"], video["task"])
    ops.video_media_approve(world["path"], video["task"], hash=shown["sha256"])
    assert run_task(world, video["task"])["stopped"] == "deliver" and flag(world["engine"].of("render")[-1]["args"], "--asset-sha256").endswith(shown["set"]["assets"][0]["sha256"])
