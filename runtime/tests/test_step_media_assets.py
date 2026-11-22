"""Tests of the pictures of the media set in the step kind `media` (package V9b-3a, limit L76): Continue is refused while a pick is not approved, the renderer is handed a picture only
when the approval holds, a file swapped under the same name fails, the credits of a CC BY picture ride the delivery document, the card and the body, and the seam for a picture
nobody checked (a planted synthetic candidate: the open-web path itself is another package) needs its own approval for this task, this sha256 and a source still in use. The engine is
the fake of media_kit; every picture is a flat-colour PNG made with zlib; nothing is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_media_assets.py
"""
from __future__ import annotations

import json
import os
import sys
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


def test_a_cc_by_picture_binds_its_credit_by_count_and_hash_not_by_text_in_the_document_the_card_and_the_body(world, monkeypatch):
    video = approved_video(world, monkeypatch, "cc-by-4.0")
    out = go_on(world, video["task"])
    assert out["stopped"] == "deliver"
    gate, doc = delivered(world, video["task"])
    [drawn] = json.loads(work_file(world, "render.json").read_text())["assets"]
    assert drawn["credit"].startswith("\"A picture of market stall\" by Bram Hollow, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), via shelf")
    assert doc["credits"] == {"count": 1, "sha256": sha(json.dumps([drawn["credit"]], ensure_ascii=False).encode("utf-8"))}
    assert doc["assets"][0]["licence"] == "cc-by-4.0" and doc["assets"][0]["slot"] == "beat7" and "web" not in doc
    keys = [line[0] for line in gate["payload"]["card"]]
    assert "CARD_VIDEO_ASSET" in keys and ["CARD_VIDEO_CREDITS_COUNT", {"count": "1", "sha": doc["credits"]["sha256"]}] in gate["payload"]["card"]
    assert "1 pictures need a credit; the credit text is on this computer's page" in gate["body"] and "Bram Hollow" not in gate["body"]
    assert "Picture: beat7, shelf, cc-by-4.0, sha256 " in gate["body"]
    assert gate["payload"]["effect"]["assets"] == 1 and gate["payload"]["effect"]["credits"] == 1


MARK_TITLE, MARK_AUTHOR = "zqxtitlemarker", "ZQXAUTHORMARKER"


def test_s4_library_text_is_absent_from_the_decision_the_hash_input_and_the_messaging_card_and_present_on_the_page_the_terminal_and_the_download(world, monkeypatch):
    layout_engine(world["engine"])
    found = to_found(world, monkeypatch, {"beat7": ("zqx title", "image")})
    found["sources"].licences, found["sources"].authors, found["sources"].titles = {"shelf": "cc-by-4.0"}, {"shelf": MARK_AUTHOR}, {"shelf": MARK_TITLE}
    done = ops.video_media_find(world["path"], found["task"], confirm=True)
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    ops.video_media_fetch_picks(world["path"], found["task"])
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    assert go_on(world, found["task"])["stopped"] == "deliver"
    gate, doc = delivered(world, found["task"])
    phrases = st.load("phrases")
    phone = phrases.card_text(gate["payload"]["card"], {"language": "pt-BR"}) + phrases.card_text(gate["payload"]["card"])      # the messaging card, in both languages
    hash_input = json.dumps(doc, sort_keys=True)
    for text in (gate["body"], hash_input, phone, json.dumps(gate["payload"]), gate["title"]):
        assert MARK_TITLE not in text and MARK_AUTHOR not in text
    assert "imagens precisam de crédito" in phone
    for channel in ("terminal", "page"):
        credits = ops.video_credits(world["path"], found["task"], channel=channel)
        assert MARK_TITLE in credits["credits"][0] and MARK_AUTHOR in credits["credits"][0] and credits["text_from_the_library"] is True
        assert credits["provided"] and credits["provided"][0].startswith("Media provided by shelf (")
    assert MARK_TITLE in shown["credits"][0]      # the approval's own answer, in the terminal and the page
    ops.approve(world["path"], gate["id"], sha256=gate["payload_sha256"], channel="terminal")
    got = st.load("ops_media").video_download(world["path"], found["task"], out=str(Path(world["tmp"]) / "s4.mp4"), channel="terminal")
    assert MARK_TITLE in got["credits"][0] and MARK_AUTHOR in got["credits"][0]


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
    assert ["CARD_VIDEO_WEB", {"host": "pics.example"}] in card and not any(line[0] == "CARD_VIDEO_WEB_PAGE" for line in card) and "gallery" not in json.dumps(card)      # S4: no page address on a card
    assert "gallery" not in json.dumps(gate["payload"]["effect"])


def test_a_card_never_shows_a_source_page_address_and_the_page_hash_helper_reads_an_https_address_only():
    host, page_sha = step_media._page_parts(PAGE)
    assert (host, page_sha) == ("pics.example", sha(PAGE.encode())) and step_media._page_parts("http://pics.example/x") == ("", "") and step_media._page_parts(None) == ("", "")
    doc = deliver_document.build(task=1, recording="a" * 16, platform="instagram", post="docs/marketing/content/x.md",
                                 video={"name": "render-%s.mp4" % ("b" * 12), "sha256": "b" * 64, "size": 10, "duration_ms": 5}, cover=None, verify_platform="instagram",
                                 assets=[{"slot": "beat7", "sha256": "c" * 64, "source": "web", "item": "q-" + "c" * 12, "licence": "unverified"}],
                                 web=[{"slot": "beat7", "sha256": "c" * 64, "page_host": host, "page_sha256": page_sha}])
    assert not any(line[0] == "CARD_VIDEO_WEB_PAGE" for line in deliver_document.card_lines(doc, "d" * 64))


def test_limit_76_only_an_approved_picture_is_rendered(world, monkeypatch):
    video = approved_video(world, monkeypatch)
    media_stock.void_approval(world["data"], world["rid"])
    out = go_on(world, video["task"])
    assert out["code"] == "media_not_approved" and not world["engine"].of("render")
    shown = ops.video_media_approve(world["path"], video["task"])
    ops.video_media_approve(world["path"], video["task"], hash=shown["sha256"])
    assert run_task(world, video["task"])["stopped"] == "deliver" and flag(world["engine"].of("render")[-1]["args"], "--asset-sha256").endswith(shown["set"]["assets"][0]["sha256"])


# --- the review fixes of #820 -------------------------------------------------------------------------------------------------------------------


import types

ops_media_edit = st.load("ops_media_edit")


def document_ctx(world, task):
    """A stand-in Context for `step_media._document` alone: the real media store, a files service that keeps the document, the project's configuration."""
    ctx = ops_core.context(world["path"])
    kept = {}
    files = types.SimpleNamespace(write=lambda t, c, doc: kept.setdefault("doc", doc) and "d" * 64)
    services = {"media_store": ops_step_seams.MediaStore(ctx), "effect_files": files, "config": ctx["cfg"], "media_engine": object()}
    step = types.SimpleNamespace(task_id=task, args={"media": world["rid"], "post": "docs/marketing/content/x.md"}, services=services)
    state = {"steps": {"take": {"result": {"platform": "instagram"}}, "cover": {"result": {}}, "verify": {"result": {}}}, "cycle": 0}
    return step, state, kept


def test_a_failure_at_the_render_or_the_document_is_not_a_repair_state_but_one_at_remap_is(world, monkeypatch):
    video = approved_video(world, monkeypatch)
    world["engine"].fail["render"] = ops_step_seams.StepServiceError("engine_failed")
    out = go_on(world, video["task"])
    assert out["ok"] is False and out["failed"] == "render"
    with pytest.raises(ops_core.OpsError) as refused:
        ops_media_edit.edit(ops_core.context(world["path"]), video["task"], review_of(world)["revision"], [{"op": "slot", "slot": "beat7", "choice": "none"}])
    assert "only while the video waits" in str(refused.value)
    row = task_row(world, video["task"])
    assert not ops_media_edit.stock_repair(row, row["step_state"])
    media_stock.void_approval(world["data"], world["rid"])
    world["engine"].fail.clear()
    again = run_task(world, video["task"])
    assert again["failed"] == "render" and again["code"] == "asset_not_approved"      # the approval check at the render: a code of the repair list, but not at remap
    row = task_row(world, video["task"])
    assert not ops_media_edit.stock_repair(row, row["step_state"])
    assert ops_media_edit.stock_repair(dict(row, state="failed"), {"failure": {"step": "remap", "code": "media_not_approved"}})
    assert not ops_media_edit.stock_repair(dict(row, state="failed"), {"failure": {"step": "document", "code": "media_not_approved"}})


def test_the_render_records_what_it_drew_and_a_set_changed_after_it_cannot_change_the_deliverys_assets_or_credits(world, monkeypatch):
    video = approved_video(world, monkeypatch, "cc-by-4.0")
    go_on(world, video["task"])
    record = json.loads(work_file(world, "render.json").read_text())
    [drawn] = record["assets"]
    assert drawn["slot"] == "beat7" and drawn["licence"] == "cc-by-4.0" and drawn["credit"].startswith('"A picture of market stall" by Bram Hollow, CC BY 4.0')
    _, doc = delivered(world, video["task"])
    changed = json.loads((stock_dir(world) / "set.json").read_text())
    changed["credits"], changed["credit_of"] = ["BOGUS"], {"beat7": "BOGUS"}
    changed["assets"][0]["licence"] = "cc0-1.0"
    media_stock.write_doc(world["data"], world["rid"], "set.json", changed)
    step, state, kept = document_ctx(world, video["task"])
    for name in ("verify.json",):
        media.write_work(world["data"], world["rid"], name, json.dumps({"passed": True, "platform": "instagram"}).encode())
    step_media._document(step, state)
    again = kept["doc"]
    assert again["credits"] == doc["credits"] and again["assets"] == doc["assets"] and "BOGUS" not in json.dumps(again)


def test_a_picture_of_the_set_that_no_beat_draws_gets_no_credit(world, monkeypatch):
    video = approved_video(world, monkeypatch, "cc-by-4.0")
    plain = world["engine"]

    def no_layout(a):
        out = flag(a, "--out")
        Path(out).write_text(json.dumps({"report": [], "slots": [dict(SLOT_SOURCE)]} if out.endswith("proposal.beats.json") else {"overlays": [], "layouts": []}))
        return {"ok": True, "beats": 1, "overlays": 0, "layouts": 0, "unmatched": []}
    plain._align = no_layout
    assert go_on(world, video["task"])["stopped"] == "deliver"
    _, doc = delivered(world, video["task"])
    assert "credits" not in doc and "assets" not in doc and "assets" not in json.loads(work_file(world, "render.json").read_text())


def test_removing_the_whole_media_object_after_an_unverified_approval_refuses_the_render(world, monkeypatch):
    plant = plant_unverified(world, monkeypatch)
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text())
    raw.pop("media")
    path.write_text(json.dumps(raw))
    accepted_now(world)
    out = go_on(world, plant["task"])
    assert out["ok"] is False and out["code"] == "media_not_approved" and not world["engine"].of("render")


def accepted_now(world):
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"], widen=ops.config(world["path"])["widening_sha256"])


def test_the_download_answer_repeats_the_credits_and_the_card_says_who_provided_the_media(world, monkeypatch):
    video = approved_video(world, monkeypatch, "cc-by-4.0")
    go_on(world, video["task"])
    gate, doc = delivered(world, video["task"])
    link = json.loads((stock_dir(world) / "set.json").read_text())["assets"][0]["source_link"]
    assert link.startswith("https://") and not any(line[0] == "CARD_VIDEO_PROVIDED" for line in gate["payload"]["card"])      # S4: not on the card that can go to a phone
    assert ops.video_credits(world["path"], video["task"], channel="page")["provided"] == ["Media provided by shelf (%s)" % link]
    ops.approve(world["path"], gate["id"], sha256=gate["payload_sha256"], channel="terminal")
    ops_media = st.load("ops_media")
    done = ops_media.video_download(world["path"], video["task"], out=str(Path(world["tmp"]) / "out.mp4"), channel="terminal")
    assert len(done["credits"]) == 1 and sha(json.dumps(done["credits"], ensure_ascii=False).encode("utf-8")) == doc["credits"]["sha256"]


# --- an added layout with its approved picture reaches the renderer's own check (the K3 finding: `slot_without_description`) -----------------------------------------------


COMPLETE_BEATS = {"schema_version": 1, "threshold": 0.6, "overlays": [], "layouts": [], "slots": [], "report": [], "fallbacks": [], "unmatched": []}
SHOW = "a mountain lake"


class Checks:
    """MediaEngine's stand-in for `block-params` (what the renderer's block checker answers); every other verb goes to the media kit's fake."""

    def __init__(self, real):
        self.real = real

    def call(self, cls, verb, args, timeout):
        if verb != "block-params":
            return self.real(cls, verb, args, timeout)
        return {"ok": True, "block": args[args.index("--block") + 1], "engine": "ffmpeg", "params": sorted(json.loads(Path(args[args.index("--params") + 1]).read_text()))}


def added_layout_video(world, monkeypatch, block="oh:cutaway", params=None, **words):
    """A video with an added layout `a1` (its words 3 to 5), its picture found, picked, fetched and approved; the fake renderer's final beats are the complete empty document
    the real aligner writes. Returns the task; the next step is the review's Continue."""
    engine = world["engine"]
    engine._align = lambda a: (Path(flag(a, "--out")).write_text(json.dumps(dict(COMPLETE_BEATS, slots=[]))), {"ok": True, "beats": 0, "overlays": 0, "layouts": 0, "unmatched": []})[1]
    monkeypatch.setattr(st.load("media_animation"), "engine_of", lambda ctx: Checks(engine.call))
    found = to_found(world, monkeypatch, searches={"beat7": ("market stall", "image")})
    edit = dict({"op": "animation", "block": block, "params": params if params is not None else {"fit": "cover"}, "word_from": 3, "word_to": 5, "search": "mountain lake", "want": "image"}, **words)
    ops_media = st.load("ops_media")
    ops_media.captions_edit(world["path"], found["task"], review_of(world)["revision"], edits=json.dumps([edit]))
    ops_media.captions_edit(world["path"], found["task"], review_of(world)["revision"], edits=json.dumps([{"op": "slot", "slot": "a1", "choice": "stock"}]))
    done = ops.video_media_find(world["path"], found["task"], confirm=True)
    for row in done["slots"]:
        pick(world, found["task"], row["slot"], row["candidates"][0]["pick"], review_of(world)["revision"])
    ops.video_media_fetch_picks(world["path"], found["task"])
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    return found["task"]


def beats_of(world):
    return json.loads(work_file(world, "beats.json").read_text(encoding="utf-8"))


def test_align_writes_the_slot_row_of_an_added_layout_drawn_with_its_approved_picture(world, monkeypatch):
    task = added_layout_video(world, monkeypatch, show=SHOW)
    out = go_on(world, task)
    assert out["ok"] is True and out["stopped"] == "deliver", out
    beats = beats_of(world)
    [layout] = beats["layouts"]
    assert layout["id"] == "a1" and layout["params"] == {"asset": "a1", "fit": "cover"}
    args = world["engine"].of("render")[-1]["args"]
    assert [a for a in args if a.startswith("a1=")][0].startswith("a1=") and args.count("--asset") == 1 and flag(args, "--asset").split("=")[0] == layout["params"]["asset"] == flag(args, "--asset-sha256").split("=")[0]      # the renderer finds the picture by the slot id the layout names
    assert beats["slots"] == [{"slot": "a1", "beat": layout["beat"], "param": "asset", "type": "image|clip", "description": SHOW}]      # the aligner's own shape: the vocabulary's picture kinds joined with `|`


@pytest.mark.parametrize("words,want", [({"show": SHOW}, SHOW), ({}, "mountain lake"), ({"show": "  "}, "mountain lake")])
def test_the_slot_description_is_what_the_person_said_the_picture_shows_else_the_search_words(world, monkeypatch, words, want):
    review_words = {k: v for k, v in words.items() if v.strip()}
    task = added_layout_video(world, monkeypatch, **review_words)
    assert go_on(world, task)["ok"] is True
    assert [r["description"] for r in beats_of(world)["slots"]] == [want]


def test_a_description_outside_the_renderers_limits_falls_back_to_a_plain_word(world):
    vocab = json.loads((st.REPO / "shared" / "references" / "video-presets.json").read_text())
    store = type("S", (), {"reference": staticmethod(lambda rel: str(st.REPO / rel))})
    for words in ([], ["ab"], ["x" * (vocab["limits"]["slot_description_max"] + 1)], [None, 4]):
        row = step_media._slot_row(store, {"id": "a1", "beat": 1001, "preset": "cutaway"}, {"asset_param": "asset", "words": words})
        assert row["description"] == step_media.SLOT_FALLBACK and vocab["limits"]["slot_description_min"] <= len(row["description"]) <= vocab["limits"]["slot_description_max"]


def test_a_slot_row_that_exists_is_not_written_twice(world):
    beats = {"slots": [{"slot": "a1", "beat": 1, "param": "asset", "type": "image", "description": "kept"}]}
    store = type("S", (), {"reference": staticmethod(lambda rel: str(st.REPO / rel))})
    step_media._add_slot_row(store, beats, {"id": "a1", "beat": 1001, "preset": "cutaway"}, {"asset_param": "asset", "words": ["new words"]})
    assert beats["slots"] == [{"slot": "a1", "beat": 1, "param": "asset", "type": "image", "description": "kept"}]


def renderer_checker():
    """The renderer's own modules and files: the edit list its code builds from a transcript, the vocabulary, the data file and the platform file, no process and no container."""
    folder = str(st.REPO / "providers" / "renderer")
    tests = folder + "/tests"
    for one in (folder, tests):
        if one not in sys.path:
            sys.path.insert(0, one)
    import _edl, _output, _vocab  # noqa: E401
    import renderer_kit as K
    data, vocab = _vocab.load_data(), _vocab.load_vocabulary(str(K.VOCABULARY))
    allow = {"fixture-800": {"id": "fixture-800"}}
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "c" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, data, allow, retake_mode="propose")
    platform = _output.read_platform(str(K.INSTAGRAM))
    return lambda beats, vocabulary=vocab: _output.check_documents(data, edl, beats, platform, vocabulary, allow), vocab


def test_the_beats_written_for_an_added_layout_pass_the_renderers_own_check(world, monkeypatch):
    check, _ = renderer_checker()
    task = added_layout_video(world, monkeypatch, show=SHOW)
    assert go_on(world, task)["ok"] is True
    beats = beats_of(world)
    assert check(beats)["mentions"] == [] and [e["id"] for e in beats["layouts"]] == ["a1"]
    broken = dict(beats, slots=[])      # the check does see the missing row: the K3 refusal
    with pytest.raises(Exception) as caught:
        check(broken)
    assert getattr(caught.value, "code", "") == "slot_without_description"


def test_the_beats_written_for_an_added_picture_overlay_pass_the_renderers_own_check(world, tmp_path):
    """No shipped block is an overlay with a picture, so the vocabulary file holds a planted overlay preset with one: the same code path (`pic_kind` overlay) read from that file, and the
    renderer's own check of what it wrote."""
    check, vocab = renderer_checker()
    planted = json.loads(json.dumps(vocab))
    planted["presets"]["pic_overlay"] = {"kind": "overlay", "params": {"asset": {"type": ["image"], "required": True}}}
    path = tmp_path / "planted-vocabulary.json"
    path.write_text(json.dumps(planted))
    store = type("S", (), {"reference": staticmethod(lambda rel: str(path))})
    entry = {"id": "a1", "beat": 1001, "preset": "pic_overlay", "params": {"asset": "a1"}, "word_from": 3, "word_to": 5, "score": 1.0}
    row = step_media._slot_row(store, entry, {"asset_param": "asset", "pic_kind": "overlay", "words": [SHOW]})
    assert row == {"slot": "a1", "beat": 1001, "param": "asset", "type": "image", "description": SHOW}
    assert check(dict(COMPLETE_BEATS, overlays=[entry], slots=[row]), planted)["mentions"] == []
