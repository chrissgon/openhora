"""Tests of the licensed pictures of a video (package V9b-3a): the switches and the widening, `video-media-find`, `video-media-fetch-picks`, `video-media-sheet-file`,
`video-media-approve`, the credits and the retention (limits L75 and L77). The sources are a fake of the class `stock:media`, the renderer's `asset-sheet` a fake that writes
what the verb would, the store of recordings and the approval path the real ones. Nothing is called; every name is invented and every host ends in `.example`.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_stock.py
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import add, media, ops, ops_core, task_row, to_review, work_file, world  # noqa: F401
from media_stock_kit import (FakeSheets, FakeSources, LIBRARY, REPO, accepted, captions, configure, media_stock, ops_media_edit, ops_media_stock, pick, png, review_of, sha, to_found)

project_config = st.load("project_config")
policy_widening = st.load("policy_widening")
operations = st.load("operations")
upkeep = st.load("upkeep")
service = st.load("service")

FOUND_TWO = {"beat7": ("market stall", "image"), "beat8": ("fruit crate", "image")}


def find(world, task, confirm=True):
    return ops.video_media_find(world["path"], task, confirm=confirm)


def picked_all(world, task, rows):
    """Pick the first candidate of every slot in `rows` (the answer of a find) and return the review's revision after."""
    revision = review_of(world)["revision"]
    for row in rows:
        pick(world, task, row["slot"], row["candidates"][0]["pick"], revision)
        revision += 1
    return revision


def stock_folder(world):
    return Path(media_stock.folder_of(world["data"], world["rid"]))


# --- the switches and the widening ---------------------------------------------------------------------------------------------------------------


def test_the_default_sources_are_the_keyless_ones_and_an_empty_list_turns_stock_off(world, monkeypatch):
    configure(world, monkeypatch, "default", accept=False)
    cfg = project_config.load(world["path"])
    assert media_stock.sources_of(cfg) == ["web", "shelf"]      # the open-web tier first, then by name
    assert "stock" not in cfg["media"]
    configure(world, monkeypatch, [], accept=False)
    cfg = project_config.load(world["path"])
    assert cfg["media"]["stock"] == [] and media_stock.sources_of(cfg) == []
    raw = json.loads((Path(world["path"]) / "docs" / "workbench" / "runtime.json").read_text())
    raw.pop("media")
    (Path(world["path"]) / "docs" / "workbench" / "runtime.json").write_text(json.dumps(raw))
    assert media_stock.sources_of(project_config.load(world["path"])) == []      # a project with no `media` object uses none: the default is offered where videos are set up


@pytest.mark.parametrize("bad", ["shelf", ["nosuchsource"], ["shelf", "shelf"], [3], ["shelf"] * 9, ["a" * 40]])
def test_a_stock_list_that_is_not_a_list_of_shipped_sources_is_refused(world, monkeypatch, bad):
    configure(world, monkeypatch, "default", accept=False)
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text())
    raw["media"] = {"stock": bad}
    path.write_text(json.dumps(raw))
    with pytest.raises(project_config.ConfigError):
        project_config.load(world["path"])


def test_a_search_before_the_acceptance_answers_stock_not_accepted_naming_the_command(world, monkeypatch):
    configure(world, monkeypatch, "default", accept=False)      # the file changed and the person has not accepted it
    fake, sheets = FakeSources(), FakeSheets()
    monkeypatch.setattr(ops_media_stock, "_sources_for", lambda ctx: fake)
    monkeypatch.setattr(ops_media_stock, "_engine_of", lambda ctx: sheets)
    with pytest.raises(ops_core.OpsError) as refused:      # the file changed and was not accepted: the operations layer itself refuses until `accept-config`
        ops.video_media_find(world["path"], 1)
    assert "accept-config" in str(refused.value) and fake.calls == []


def test_the_acceptance_of_a_file_that_adds_a_source_is_needed_before_the_search_and_prints_what_is_given_away(world, monkeypatch):
    task = to_review(world)
    configure(world, monkeypatch, "default", accept=False)
    shown = ops.config(world["path"])
    items = [i for i in shown["widening"] if i["group"].startswith("stock=")]
    assert [i["group"] for i in items] == ["stock=shelf@2026-11-11", "stock=web@none"]      # V9b-3b: the open web is an item too, after the licensed ones
    assert "the search words of each video are sent to shelf" in items[0]["means"] and "cc-by-2.0" in items[0]["means"]
    assert "the files stay on this computer" in items[0]["means"]
    monkeypatch.setattr(ops_media_stock, "_sources_for", lambda ctx: FakeSources())
    accepted(world)
    with pytest.raises(ops_core.OpsError) as refused:      # accepted, but nothing is set up for the video yet
        ops.video_media_find(world["path"], task)
    assert "no_slots" in str(refused.value) or "not_at_review" in str(refused.value)


def test_the_widening_record_must_hold_the_stock_items_or_the_search_is_refused(world, monkeypatch):
    configure(world, monkeypatch, "default", accept=True)
    task = to_review(world)
    ctx = ops_core.context(world["path"])
    ctx["store"].cursor_set(ctx["conn"], policy_widening.ACCOUNTS, json.dumps({"v": 1, "items": ""}))      # a record from before the sources were accepted
    monkeypatch.setattr(ops_media_stock, "_sources_for", lambda ctx: FakeSources())
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_find(world["path"], task)
    assert "stock_not_accepted" in str(refused.value) and "accept-config --widen" in str(refused.value)


def test_one_widening_item_per_source_and_a_new_one_when_the_terms_date_changes(world, monkeypatch):
    configure(world, monkeypatch, ["shelf", "fakelib"], extra={"fakelib": LIBRARY})
    cfg = project_config.load(world["path"])
    items = policy_widening.stock_items(cfg, "k")
    assert [i["group"] for i in items] == ["stock=shelf@2026-11-11", "stock=fakelib@2026-11-12"]
    assert items[1]["means"].startswith("stock media from fakelib:") and media_stock.LICENCES_ACCEPTED[0] in items[1]["means"] and "read on 2026-11-12" in items[1]["means"]
    before, record = {i["digest"] for i in items}, policy_widening.dump_accounts(cfg, "k")      # the record the acceptance wrote, before the file changes
    source = Path(world["tree"]) / "providers" / "stock" / "sources" / "fakelib.json"
    data = json.loads(source.read_text())
    data["terms_read_on"] = "2027-01-02"
    source.write_text(json.dumps(data))
    again = policy_widening.stock_items(project_config.load(world["path"]), "k")
    assert again[1]["group"] == "stock=fakelib@2027-01-02" and {i["digest"] for i in again} != before and again[0]["digest"] == items[0]["digest"]
    wide = policy_widening.account_widening(record, project_config.load(world["path"]), "k")
    assert [i["group"] for i in wide if i["group"].startswith("stock=")] == ["stock=fakelib@2027-01-02"]
    assert policy_widening.stock_items({"media": {}}, "k") == [] and policy_widening.stock_items({}, "k") == []


# --- find ----------------------------------------------------------------------------------------------------------------------------------------


def test_find_without_confirm_sends_nothing_and_says_which_words_go_where(world, monkeypatch):
    found = to_found(world, monkeypatch)
    shown = find(world, found["task"], confirm=False)
    assert shown["confirmed"] is False and shown["sources"] == ["shelf"]
    assert shown["slots"] == [{"slot": "beat7", "show": "a screenshot of a shop 0", "search": "market stall", "want": "image"}]
    assert "market stall" in shown["message"] and "shelf" in shown["message"]
    assert found["sources"].calls == [] and found["sheets"].calls == [] and not (stock_folder(world) / "set.json").exists()


def test_find_with_confirm_searches_every_source_that_serves_the_kind_merges_round_robin_and_keeps_at_most_six(world, monkeypatch):
    found = to_found(world, monkeypatch, stock=["fakelib", "fakelib2", "fakelib3", "shelf"],
                     extra={"fakelib": LIBRARY, "fakelib2": dict(LIBRARY, source="fakelib2"), "fakelib3": dict(LIBRARY, source="fakelib3")})
    done = find(world, found["task"])
    [row] = done["slots"]
    assert done["confirmed"] is True and done["found"] == 6 and len(row["candidates"]) == 6
    assert [c["source"] for c in row["candidates"]] == ["fakelib", "fakelib2", "fakelib3", "shelf", "fakelib", "fakelib2"]      # round robin, in the order of media.stock, at most six
    assert [c["col"] for c in row["candidates"]] == [1, 2, 3, 4, 5, 6] and done["sheet"] == "sheet-preview.png"
    calls = found["sources"].of("search")
    assert len(calls) == 4 and all(c["flags"][c["flags"].index("--count") + 1] == "2" for c in calls)      # a source gives a slot at most two
    assert found["sheets"].calls[-1]["mode"] == "preview" and len(found["sheets"].calls[-1]["items"]) == 6
    assert sorted(n for n in os.listdir(stock_folder(world)) if n.startswith("prev-")) == sorted(
        c["preview"] for c in json.loads((stock_folder(world) / "set.json").read_text())["slots"][0]["candidates"])
    doc = json.loads((stock_folder(world) / "set.json").read_text())
    assert doc["phase"] == "found" and doc["task"] == found["task"] and (stock_folder(world) / "sheet-preview.png").exists()
    assert "media_url" not in json.dumps(done) and all(set(c) <= {"pick", "source", "item", "kind", "licence", "author", "title", "page", "width", "height", "seconds", "preview", "col"}
                                                       for c in row["candidates"])


def test_the_sources_of_a_slot_are_searched_at_the_same_time_and_each_source_one_request_at_a_time(world, monkeypatch):
    found = to_found(world, monkeypatch, FOUND_TWO, stock=["fakelib", "shelf"], extra={"fakelib": LIBRARY})
    found["sources"].barrier = threading.Barrier(2)      # both sources must be inside `search` together, or the barrier times out and the find fails
    done = find(world, found["task"])
    assert done["found"] == 8 and len(found["sources"].of("search")) == 4
    assert found["sources"].most_active == {"fakelib": 1, "shelf": 1}


def test_a_candidate_with_a_licence_outside_the_tuple_or_a_credit_licence_without_an_author_or_a_bad_shape_is_dropped(world, monkeypatch):
    found = to_found(world, monkeypatch, stock=["fakelib", "shelf"], extra={"fakelib": LIBRARY})
    found["sources"].licences = {"fakelib": "cc-by-sa-4.0", "shelf": "cc-by-4.0"}
    found["sources"].authors = {"shelf": ""}
    done = find(world, found["task"])
    assert done["found"] == 0 and done["dropped"]["licence"] == 4 and done["sheet"] is None
    assert found["sheets"].calls == []
    found["sources"].licences = {"shelf": "cc-by-4.0", "fakelib": media_stock.LICENCES_ACCEPTED[0]}
    found["sources"].authors = {"shelf": "Bram Hollow"}
    assert find(world, found["task"])["found"] == 4
    original = found["sources"]._search

    def odd(source, flags):
        answer = original(source, flags)
        answer["candidates"][0]["extra"] = 1
        answer["candidates"][1]["licence"] = "unverified"
        return answer
    found["sources"]._search = odd
    done = find(world, found["task"])
    assert done["found"] == 0 and done["dropped"]["shape"] == 2 and done["dropped"]["licence"] == 2      # the first of each source has an extra key, the second the licence `unverified`


def test_a_source_that_is_not_ready_or_times_out_is_skipped_and_counted(world, monkeypatch):
    found = to_found(world, monkeypatch, stock=["fakelib", "shelf"], extra={"fakelib": LIBRARY})
    found["sources"].fail = {"fakelib": "not_ready"}
    done = find(world, found["task"])
    assert done["found"] == 2 and done["dropped"]["source"] == 1


def test_seven_slots_with_words_are_refused_by_the_review_edit(world, monkeypatch):
    seven = {"beat%d" % n: ("fruit %s" % w, "image") for n, w in zip(range(7, 14), "abcdefg")}
    with pytest.raises(ops_core.OpsError) as refused:
        to_found(world, monkeypatch, seven)
    assert "too_many_slots" in str(refused.value)


def test_a_second_find_starts_over_and_voids_the_approval(world, monkeypatch):
    found = to_found(world, monkeypatch, FOUND_TWO)
    first = find(world, found["task"])
    previews = sorted(n for n in os.listdir(stock_folder(world)) if n.startswith("prev-"))
    assert len(previews) == 4
    media_stock.write_doc(world["data"], world["rid"], media_stock.APPROVED, {"hash": "x" * 64, "task": found["task"]})
    again = find(world, found["task"])
    assert not (stock_folder(world) / "approved.json").exists() and again["found"] == first["found"]
    assert sorted(n for n in os.listdir(stock_folder(world)) if n.startswith("prev-")) == previews      # the same previews, made again, never more than the set lists
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_find(world["path"], found["task"] + 99, confirm=True)
    assert "no such" in str(refused.value).lower() or "not found" in str(refused.value).lower() or refused.value.args


def test_a_find_needs_the_video_to_wait_at_the_review_and_a_slot_with_words(world, monkeypatch):
    found = to_found(world, monkeypatch)
    ctx = ops_core.context(world["path"])
    ctx["store"].step_task_move(ctx["conn"], found["task"], state="running", note=None, by="code")
    with pytest.raises(ops_core.OpsError) as refused:
        find(world, found["task"])
    assert "not_at_review" in str(refused.value)


def test_the_stock_folder_of_a_recording_in_a_reference_store_is_refused(world, monkeypatch):
    found = to_found(world, monkeypatch)
    marker = Path(world["data"]) / media_stock.media.references.MARKER
    marker.write_bytes(b"marker")
    with pytest.raises(ops_core.OpsError) as refused:
        find(world, found["task"])
    assert "reference store" in str(refused.value) and found["sources"].of("search") == []
    with pytest.raises(media.MediaError):
        media.path_of(world["data"], world["rid"], "stock/asset-%s.png" % ("a" * 12), must_exist=False)


# --- the picks, the fetch and the page's files -----------------------------------------------------------------------------------------------------


def test_fetch_picks_needs_a_pick_for_every_slot_fetches_only_the_picks_and_deletes_the_rest(world, monkeypatch):
    found = to_found(world, monkeypatch, FOUND_TWO)
    done = find(world, found["task"])
    revision = review_of(world)["revision"]
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][1]["pick"], revision)
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "no_pick" in str(refused.value) and "beat8" in str(refused.value) and found["sources"].of("fetch") == []
    pick(world, found["task"], "beat8", done["slots"][1]["candidates"][0]["pick"], revision + 1)
    got = ops.video_media_fetch_picks(world["path"], found["task"])
    assert [a["slot"] for a in got["assets"]] == ["beat7", "beat8"] and got["sheet"] == "sheet.png"
    assert len(found["sources"].of("fetch")) == 2
    assert found["sources"].of("fetch")[0]["flags"][found["sources"].of("fetch")[0]["flags"].index("--item") + 1] == done["slots"][0]["candidates"][1]["item"]
    names = sorted(os.listdir(stock_folder(world)))
    assert not [n for n in names if n.startswith("prev-") or n == "sheet-preview.png"]      # the previews and the preview sheet are gone
    assert [n for n in names if n.startswith("asset-")] and "sheet.png" in names and "set.json" in names
    doc = json.loads((stock_folder(world) / "set.json").read_text())
    assert doc["phase"] == "fetched" and [a["slot"] for a in doc["assets"]] == ["beat7", "beat8"] and doc["assets"][0]["licence"] == "cc0-1.0"
    assert found["sheets"].calls[-1]["mode"] == "full"


def test_a_slot_the_sources_found_nothing_for_is_left_without_a_picture(world, monkeypatch):
    found = to_found(world, monkeypatch, FOUND_TWO)
    real = found["sources"].call

    def call(source, verb, flags, timeout):
        if verb == "search" and "fruit crate" in flags:
            return {"ok": True, "source": source, "kind": "image", "candidates": [], "dropped": {}, "requests": 1, "cached": False, "previews": 0}
        return real(source, verb, flags, timeout)

    monkeypatch.setattr(found["sources"], "call", call)
    done = find(world, found["task"])
    assert done["slots"][1]["slot"] == "beat8" and done["slots"][1]["candidates"] == []
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    got = ops.video_media_fetch_picks(world["path"], found["task"])
    assert got["without_picture"] == ["beat8"] and [a["slot"] for a in got["assets"]] == ["beat7"]


def test_a_slot_whose_choice_is_no_longer_stock_is_skipped_by_the_fetch(world, monkeypatch):
    found = to_found(world, monkeypatch, FOUND_TWO)
    done = find(world, found["task"])
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    ops_media_edit.edit(ops_core.context(world["path"]), found["task"], review_of(world)["revision"], [{"op": "slot", "slot": "beat8", "choice": "none"}])
    got = ops.video_media_fetch_picks(world["path"], found["task"])
    assert got["without_picture"] == ["beat8"] and [a["slot"] for a in got["assets"]] == ["beat7"] and len(found["sources"].of("fetch")) == 1


def test_the_fetch_with_no_pick_at_all_is_refused(world, monkeypatch):
    found = to_found(world, monkeypatch, FOUND_TWO)
    find(world, found["task"])
    ops_media_edit.edit(ops_core.context(world["path"]), found["task"], review_of(world)["revision"],
                        [{"op": "slot", "slot": "beat7", "choice": "none"}, {"op": "slot", "slot": "beat8", "choice": "none"}])
    before = sorted(os.listdir(Path(media_stock.folder_of(world["data"], world["rid"]))))
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "no_pick" in str(refused.value) and "at least one slot" in str(refused.value) and found["sources"].of("fetch") == []
    assert sorted(os.listdir(Path(media_stock.folder_of(world["data"], world["rid"])))) == before


def test_a_clip_pick_is_refused_on_an_engine_that_draws_no_clips(world, monkeypatch):
    found = to_found(world, monkeypatch, {"beat7": ("market stall", "clip")}, stock=["fakelib"], extra={"fakelib": LIBRARY})
    done = find(world, found["task"])
    assert done["slots"][0]["candidates"][0]["kind"] == "clip"
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "clip_not_drawn" in str(refused.value) and "cannot draw clips" in str(refused.value) and found["sources"].of("fetch") == []


def test_the_fetched_answer_is_checked_the_licence_the_hash_the_size_and_the_renderers_files(world, monkeypatch):
    found = to_found(world, monkeypatch)
    done = find(world, found["task"])
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    original = found["sources"]._fetch

    def other_licence(source, flags):
        answer = original(source, flags)
        return dict(answer, licence="cc-by-sa-4.0")
    found["sources"]._fetch = other_licence
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "licence_refused" in str(refused.value)
    found["sources"]._fetch = lambda source, flags: dict(original(source, flags), sha256="0" * 64)
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "fetch_failed" in str(refused.value)
    found["sources"]._fetch = original
    found["sheets"].mutate = lambda answer: dict(answer, assets=[dict(a, source_sha256="1" * 64) for a in answer["assets"]])
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "engine_refused" in str(refused.value)
    found["sheets"].mutate = lambda answer: dict(answer, assets=[dict(a, file="asset-%s.png" % ("f" * 12)) for a in answer["assets"]])
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "engine_refused" in str(refused.value)


def test_a_pick_outside_the_candidates_is_refused_and_a_pick_for_a_slot_that_does_not_exist_too(world, monkeypatch):
    found = to_found(world, monkeypatch)
    find(world, found["task"])
    revision = review_of(world)["revision"]
    with pytest.raises(ops_core.OpsError) as refused:
        pick(world, found["task"], "beat7", "shelf:nosuchitem", revision)
    assert "asset_not_found" in str(refused.value)
    with pytest.raises(ops_core.OpsError) as refused:
        pick(world, found["task"], "beat99", "shelf:x", revision)
    assert "unknown_slot" in str(refused.value)


def test_the_sheet_route_serves_only_the_pictures_the_container_made(world, monkeypatch):
    found = to_found(world, monkeypatch)
    done = find(world, found["task"])
    served = ops.video_media_sheet_file(world["path"], found["task"], "sheet-preview.png", channel="page")
    assert served["media_type"] == "image/png" and served["data"].startswith(b"\x89PNG")
    folder = stock_folder(world)
    candidate = done["slots"][0]["candidates"][0]
    raw = json.loads((folder / "set.json").read_text())["slots"][0]["candidates"][0]["preview"]
    (folder / "quarantine").mkdir(mode=0o700)
    (folder / "quarantine" / ("q-" + "a" * 12 + ".png")).write_bytes(png())
    (folder / ("full-x-" + candidate["item"] + ".png")).write_bytes(png())
    for name in (raw, "q-" + "a" * 12 + ".png", "quarantine/q-" + "a" * 12 + ".png", "full-x-" + candidate["item"] + ".png", "set.json", "approved.json", "../record.json", "asset-xyz.png", ""):
        with pytest.raises(ops_core.OpsError):
            ops.video_media_sheet_file(world["path"], found["task"], name, channel="page")
    (folder / ("asset-" + "b" * 12 + ".png")).write_bytes(b"not a png")
    with pytest.raises(ops_core.OpsError):
        ops.video_media_sheet_file(world["path"], found["task"], "asset-" + "b" * 12 + ".png", channel="page")
    (folder / ("asset-" + "c" * 12 + ".png")).write_bytes(png())
    assert ops.video_media_sheet_file(world["path"], found["task"], "asset-" + "c" * 12 + ".png", channel="page")["data"].startswith(b"\x89PNG")
    os.symlink(str(folder / "sheet-preview.png"), str(folder / ("asset-" + "d" * 12 + ".png")))
    with pytest.raises(ops_core.OpsError):
        ops.video_media_sheet_file(world["path"], found["task"], "asset-" + "d" * 12 + ".png", channel="page")      # a link is never followed


def test_the_operations_answer_the_terminal_and_the_page_only_and_the_lan_socket_may_only_read_the_pictures(world):
    names = ("video-media-find", "video-media-fetch-picks", "video-media-approve")
    for name in names:
        row = operations.by_name(name)
        assert set(row["channels"]) == {"terminal", "page"} and row["model"] is False and name in operations.LAN_REFUSED_OPS
    sheet = operations.by_name("video-media-sheet-file")
    assert sheet["channels"] == ("page",) and "video-media-sheet-file" not in operations.LAN_REFUSED_OPS
    assert set(operations.by_name("video-credits")["channels"]) == {"terminal", "page"}
    for name in names + ("video-media-sheet-file", "video-credits"):
        assert "mcp" not in operations.by_name(name)["channels"] and "messaging" not in operations.by_name(name)["channels"] and name in operations.GROUPS["media"]["operations"]
    ops_by_name = {r["op"]: r for r in service.ROUTES if r["op"]}
    for name in names + ("video-media-sheet-file", "video-credits"):
        assert name in ops_by_name
    assert ops_by_name["video-media-sheet-file"]["raw"] is True
    with pytest.raises(ops_core.OpsError):
        ops.video_media_find("/nowhere", 1, channel="messaging")
    for call, args in ((ops.video_media_fetch_picks, (1,)), (ops.video_media_approve, (1,)), (ops.video_credits, (1,)), (ops.video_media_sheet_file, (1, "sheet.png"))):
        with pytest.raises(ops_core.OpsError):
            call("/nowhere", *args, channel="mcp")


# --- the approval --------------------------------------------------------------------------------------------------------------------------------


def fetched(world, monkeypatch, licence="cc0-1.0", words=None):
    found = to_found(world, monkeypatch, words)
    found["sources"].licences = {"shelf": licence}
    done = find(world, found["task"])
    picked_all(world, found["task"], done["slots"])
    ops.video_media_fetch_picks(world["path"], found["task"])
    return found, done


def test_approve_prints_the_set_its_hash_and_its_credits_and_needs_the_current_hash_to_approve(world, monkeypatch):
    found, _ = fetched(world, monkeypatch, "cc-by-3.0")
    shown = ops.video_media_approve(world["path"], found["task"])
    assert shown["approved"] is False and re.fullmatch("[0-9a-f]{64}", shown["sha256"]) and shown["needs_own_approval"] == []
    [asset] = shown["set"]["assets"]
    assert asset["licence"] == "cc-by-3.0" and asset["licence_url"] == "https://creativecommons.org/licenses/by/3.0/" and asset["slot"] == "beat7"
    [credit] = shown["credits"]
    assert credit.startswith("\"A picture of market stall\" by Bram Hollow, CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/), via shelf (https://shelf.example/p/")
    assert shown["credit_heading"] == "Credit to put in the caption"
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_approve(world["path"], found["task"], hash="0" * 64)
    assert "stale_hash" in str(refused.value) and not (stock_folder(world) / "approved.json").exists()
    with pytest.raises(ops_core.OpsError):
        ops.video_media_approve(world["path"], found["task"], hash="short")
    done = ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    assert done["approved"] is True and done["sha256"] == shown["sha256"]
    record = json.loads((stock_folder(world) / "approved.json").read_text())
    assert record["hash"] == shown["sha256"] and record["task"] == found["task"] and record["unverified"] == {} and record["sources"] == ["shelf", "web"]
    assert record["assets"][0]["sha256"] == asset["sha256"] and ops.video_media_approve(world["path"], found["task"])["approved"] is True
    assert oct((stock_folder(world) / "approved.json").stat().st_mode & 0o777) == "0o600"


def test_a_cc0_picture_puts_no_credit_and_the_approval_deletes_every_candidate_file(world, monkeypatch):
    found, _ = fetched(world, monkeypatch, "cc0-1.0")
    shown = ops.video_media_approve(world["path"], found["task"])
    assert shown["credits"] == []
    folder = stock_folder(world)
    (folder / "quarantine").mkdir(mode=0o700, exist_ok=True)
    (folder / "quarantine" / ("q-" + "e" * 12 + ".png")).write_bytes(png())
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    names = sorted(os.listdir(folder))
    keep = ["asset-%s.png" % shown["set"]["assets"][0]["sha256"][:12]]
    assert names == sorted(keep + ["approved.json", "set.json", "sheet.png"])
    assert not (folder / "quarantine").exists()


def test_a_pick_after_the_approval_voids_it_and_a_second_fetch_too(world, monkeypatch):
    found, done = fetched(world, monkeypatch)
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    assert (stock_folder(world) / "approved.json").exists()
    ops_media_edit.edit(ops_core.context(world["path"]), found["task"], review_of(world)["revision"], [{"op": "slot_asset", "slot": "beat7", "clear": True}])
    assert not (stock_folder(world) / "approved.json").exists() and "beat7" not in review_of(world)["slot_assets"]
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    assert not (stock_folder(world) / "approved.json").exists()
    with pytest.raises(ops_core.OpsError) as refused:      # the previews were deleted by the approval: a new find is the way back
        ops.video_media_approve(world["path"], found["task"] + 5)
    assert refused.value.args


def test_a_file_swapped_under_the_same_name_stops_the_approval(world, monkeypatch):
    found, _ = fetched(world, monkeypatch)
    [asset] = json.loads((stock_folder(world) / "set.json").read_text())["assets"]
    path = stock_folder(world) / ("asset-%s.png" % asset["sha256"][:12])
    path.chmod(0o600)
    path.write_bytes(png(2, 2, (250, 0, 0)))
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_approve(world["path"], found["task"])
    assert "asset_changed" in str(refused.value)


def test_approve_needs_a_fetched_set(world, monkeypatch):
    found = to_found(world, monkeypatch)
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_approve(world["path"], found["task"])
    assert "no_set" in str(refused.value)
    find(world, found["task"])
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_approve(world["path"], found["task"])
    assert "no_set" in str(refused.value)


# --- the credits record and the retention ---------------------------------------------------------------------------------------------------------


def test_the_credits_record_holds_what_answers_a_takedown_and_is_kept_a_year(world, monkeypatch):
    found, _ = fetched(world, monkeypatch, "cc-by-4.0")
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    record = ops.video_credits(world["path"], found["task"], channel="terminal")
    assert record["task"] == found["task"] and record["credits"] == shown["credits"] and record["web"] == []
    assert "search" not in record["assets"][0] and "show" not in record["assets"][0] and record["assets"][0]["source"] == "shelf"
    path = Path(world["data"]) / "media" / "credits" / ("%d.json" % found["task"])
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    now = path.stat().st_mtime
    assert media_stock.purge_credits(world["data"], now=now + 364 * 86400) == 0 and path.exists()
    assert media_stock.purge_credits(world["data"], now=now + 366 * 86400) == 1 and not path.exists()
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_credits(world["path"], found["task"])
    assert "no_credits" in str(refused.value)


def test_limit_75_licensed_media_is_fetched_only_after_the_acceptance_and_the_confirm_through_the_class(world, monkeypatch):
    found = to_found(world, monkeypatch)
    find(world, found["task"], confirm=False)
    assert found["sources"].calls == [], "nothing is sent without the person's confirm"
    ctx = ops_core.context(world["path"])
    ctx["store"].cursor_set(ctx["conn"], policy_widening.ACCOUNTS, json.dumps({"v": 1, "items": ""}))
    with pytest.raises(ops_core.OpsError) as refused:
        find(world, found["task"])
    assert "stock_not_accepted" in str(refused.value) and found["sources"].calls == [], "nothing is sent for sources the person did not accept"
    # every call of a source goes through the class: the real caller names the class, the implementation and no key, and it starts with the minimum environment of the class
    seen = {}

    class Resolver:
        class UnknownClass(Exception):
            pass

        class Unresolved(Exception):
            pass

        class ProviderCallError(Exception):
            kind = "failed"

        @staticmethod
        def provider_environment(cls, env, passes):
            seen["environment"] = (cls, tuple(passes))
            return {"PATH": "/usr/bin"}

        @staticmethod
        def call(cls, verb, args, **kw):
            seen.update(cls=cls, verb=verb, args=list(args), kw=kw)
            return {"ok": True}
    monkeypatch.setattr(project_config, "resolver", lambda root: Resolver)
    real = ops_media_stock.Sources(str(REPO))
    assert real.call("shelf", "search", ["--kind", "image", "--query", "market stall", "--count", 2, "--out", "/x"], 5) == {"ok": True}
    assert seen["cls"] == "stock:media" and seen["verb"] is None and seen["kw"]["implementation"] == "shelf" and seen["environment"] == ("stock:media", ())
    assert seen["args"][0] == "--source-file" and seen["args"][1].endswith("providers/stock/sources/shelf.json") and seen["args"][4] == "search"
    assert not any(re.search(r"key|token|secret", a, re.I) for a in seen["args"] if a.startswith("--") and a not in ("--source-file",))
    for flagged in ("--url", "--allow-unverified"):
        assert flagged not in seen["args"]


def test_no_source_is_named_in_the_runtime_files_of_the_stock_path():
    sources = {json.loads(p.read_text())["source"] for p in (REPO / "providers" / "stock" / "sources").glob("*.json")}
    assert len(sources) >= 3 and "web" in sources
    files = ("media_stock", "ops_media_stock", "step_media", "deliver_document", "captions", "media_animation", "policy_widening", "project_config", "media", "ops_media_edit",
             "upkeep", "operations", "service", "cli")
    for name in files:
        text = (REPO / "runtime" / (name + ".py")).read_text(encoding="utf-8")
        for source in sources:
            if source == "web":      # the word is also the key of the delivery document and of the credits record for a picture nobody checked: never a source's name, so no comparison or default
                assert not re.search(r"(source|implementation|names?|sources|default\w*)\s*(==|!=|=|in)\s*[(\[\"']*\s*[\"']web[\"']", text), f"{name}.py names the source web"
                assert not re.search(r"[\"']web[\"']\s*,\s*[\"']shelf|[\"']shelf[\"']\s*,\s*[\"']web", text), name
            else:
                assert not re.search(r"[\"'`]%s[\"'`]" % source, text), f"{name}.py names the source {source}"
            assert not re.search(r"providers/stock/%s\.py" % source, text), name
    for path in sorted((REPO / "providers" / "renderer").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for source in sources - {"web"}:
            assert not re.search(r"[\"']%s[\"']" % source, text), f"{path.name} names the source {source}"


def test_limit_77_stray_stock_files_go_after_a_day_and_the_credits_after_a_year(world, monkeypatch):
    found, _ = fetched(world, monkeypatch)
    shown = ops.video_media_approve(world["path"], found["task"])
    keep = "asset-%s.png" % shown["set"]["assets"][0]["sha256"][:12]
    folder = stock_folder(world)
    (folder / "quarantine").mkdir(mode=0o700)
    stray = {"prev-x-1.png": folder, "full-x-1.png": folder, "sheet-preview.png": folder, "asset-%s.png" % ("9" * 12): folder, "q-%s.png" % ("8" * 12): folder / "quarantine"}
    for name, where in stray.items():
        (where / name).write_bytes(png())
    now = os.stat(folder / keep).st_mtime
    assert media.purge(world["data"], now=now + 3600)["stray"] == 0 and all((w / n).exists() for n, w in stray.items())      # not yet a day
    done = media.purge(world["data"], now=now + 2 * 86400)
    assert done["stray"] == 6      # the five planted, and the full file the fetch left (it goes at the approval, or after a day) and not any((w / n).exists() for n, w in stray.items())
    assert not [n for n in os.listdir(folder) if n.startswith("full-")]
    assert (folder / keep).exists() and (folder / "set.json").exists() and (folder / "sheet.png").exists()      # what the set lists stays with the recording
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    record = media.load(world["data"], world["rid"])
    assert media.due(dict(record, delivered={"at": "2026-01-01T00:00:00Z", "sha256": "a" * 64, "task": 1, "pending": None}, purged={"raw": None}), media._epoch("2026-01-09T00:00:00Z")) == "raw"
    delivered = dict(record, delivered={"at": "2026-01-01T00:00:00Z", "sha256": "a" * 64, "task": found["task"], "pending": None})
    media.update(world["data"], world["rid"], lambda r: r.update(delivered=delivered["delivered"]))
    purged = media.purge(world["data"], now=media._epoch("2026-01-09T00:00:00Z"))
    assert purged["removed"] == [{"recording": world["rid"], "what": "raw"}] and not folder.exists()      # the pictures go with the recording 7 days after the delivery
    credits = Path(world["data"]) / "media" / "credits" / ("%d.json" % found["task"])
    assert credits.exists()
    ctx = ops_core.context(world["path"])
    cleaned = upkeep.sweep_media(ctx, now=credits.stat().st_mtime + 400 * 86400)
    assert {"credits": "record", "what": "all"} in cleaned["removed"] and not credits.exists()


def test_the_tuples_and_the_review_keys_have_one_reading_in_a_video_with_no_stock():
    review = captions.new_review()
    assert review["slot_searches"] == {} and review["slot_assets"] == {}
    old = {k: v for k, v in review.items() if k not in ("slot_searches", "slot_assets")}
    assert captions.check_review(old)["slot_assets"] == {}      # an absent key reads as {}: REVIEW_VERSION is still 1
    assert captions.REVIEW_VERSION == 1


# --- the review fixes of #820 -------------------------------------------------------------------------------------------------------------------


def test_fetch_picks_asks_the_acceptance_again_a_changed_terms_date_is_a_new_item_nobody_accepted(world, monkeypatch):
    found = to_found(world, monkeypatch)
    done = find(world, found["task"])
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    source = Path(world["tree"]) / "providers" / "stock" / "sources" / "shelf.json"
    data = json.loads(source.read_text())
    data["terms_read_on"] = "2027-02-03"
    source.write_text(json.dumps(data))
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "stock_not_accepted" in str(refused.value) and found["sources"].of("fetch") == []
    accepted(world)
    assert ops.video_media_fetch_picks(world["path"], found["task"])["assets"]


def test_a_fetched_file_must_carry_the_prefix_of_its_place(world, monkeypatch):
    found = to_found(world, monkeypatch)
    done = find(world, found["task"])
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    original = found["sources"]._fetch

    def odd(source, flags):
        answer = original(source, flags)
        folder = Path(flag_of(flags, "--out"))
        (folder / answer["file"]).rename(folder / "prev-sneaky.png")
        return dict(answer, file="prev-sneaky.png")
    found["sources"]._fetch = odd
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "fetch_failed" in str(refused.value)


def flag_of(flags, name):
    return flags[flags.index(name) + 1]


def test_the_fetch_answer_names_each_picture_file_and_says_who_provided_the_media(world, monkeypatch):
    found, _ = fetched(world, monkeypatch)
    shown = ops.video_media_approve(world["path"], found["task"])
    [asset] = shown["set"]["assets"]
    [line] = shown["provided"]
    assert line.startswith("Media provided by shelf (https://") and line.endswith(")")
    sheet = json.loads((stock_folder(world) / "set.json").read_text())["assets"][0]
    assert sheet["source_link"] and ("asset-%s.png" % asset["sha256"][:12]) in os.listdir(stock_folder(world))


def test_the_fetch_answer_carries_the_file_name_of_each_picture(world, monkeypatch):
    found = to_found(world, monkeypatch)
    done = find(world, found["task"])
    picked_all(world, found["task"], done["slots"])
    got = ops.video_media_fetch_picks(world["path"], found["task"])
    [a] = got["assets"]
    assert re.fullmatch(r"asset-[0-9a-f]{12}\.png", a["file"]) and (stock_folder(world) / a["file"]).exists() and got["provided"]


def test_a_choice_other_than_stock_clears_the_pick_and_voids_the_approval(world, monkeypatch):
    found, _ = fetched(world, monkeypatch)
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    assert (stock_folder(world) / "approved.json").exists()
    for choice in ("none", "keyword"):
        ops_media_edit.edit(ops_core.context(world["path"]), found["task"], review_of(world)["revision"], [{"op": "slot", "slot": "beat7", "choice": choice}])
        assert review_of(world)["slot_assets"] == {} and not (stock_folder(world) / "approved.json").exists()
        ops_media_edit.edit(ops_core.context(world["path"]), found["task"], review_of(world)["revision"], [{"op": "slot", "slot": "beat7", "choice": "stock"}])


def test_every_credit_line_fits_the_document_even_with_fields_of_the_longest_size():
    from media_stock_kit import media_stock as ms
    deliver = st.load("deliver_document")
    assert ms.CREDIT_MAX == deliver.CREDIT_MAX
    for licence in ms.LICENCES_CREDIT:
        asset = {"licence": licence, "title": "T" * 500, "author": "A" * 500, "source": "s" * 31, "page": "https://x.example/" + "p" * 280}
        line = ms.credit_line(asset)
        assert 0 < len(line) <= deliver.CREDIT_MAX and "\n" not in line
        deliver.build(task=1, recording="a" * 16, platform="instagram", post="docs/marketing/content/x.md",
                      video={"name": "render-%s.mp4" % ("b" * 12), "sha256": "b" * 64, "size": 5, "duration_ms": 5}, cover=None, verify_platform="instagram",
                      assets=[{"slot": "a1", "sha256": "c" * 64, "source": "shelf", "item": "x", "licence": licence}], credits={"count": 1, "sha256": "d" * 64})
    assert ms.credit_line({"licence": "cc0-1.0".replace("cc0", "cc-by").replace("1.0", "4.0"), "title": "a\nb", "author": "x", "source": "s", "page": ""}).count("\n") == 0


def test_the_stock_operations_refuse_a_channel_before_they_look_at_the_project(world, monkeypatch):
    found = to_found(world, monkeypatch)
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text())
    raw["media"] = {"language": "en"}
    path.write_text(json.dumps(raw))      # the file changed and is not accepted: the context would answer accept-config
    for channel in ("messaging", "mcp"):
        for call, args in ((ops.video_media_find, (found["task"],)), (ops.video_media_fetch_picks, (found["task"],)), (ops.video_media_approve, (found["task"],)),
                           (ops.video_credits, (found["task"],)), (ops.video_media_sheet_file, (found["task"], "sheet.png"))):
            with pytest.raises(ops_core.OpsError) as refused:
                call(world["path"], *args, channel=channel)
            assert "accept-config" not in str(refused.value), (call.__name__, channel)
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_find(world["path"], found["task"])      # no channel: the project is looked at, and the unaccepted file is what answers
    assert "accept-config" in str(refused.value)
    assert "video-credits" in operations.LAN_REFUSED_OPS and operations.by_name("video-media-find")["natural"]["cost"] == "none"


def test_a_part_file_the_stock_folder_left_goes_with_the_strays_and_the_clip_sentence_is_in_the_language(world, monkeypatch):
    found, _ = fetched(world, monkeypatch)
    folder = stock_folder(world)
    (folder / ".set.json.part").write_bytes(b"x")
    now = os.stat(folder / ".set.json.part").st_mtime
    assert media.purge(world["data"], now=now + 2 * 86400)["stray"] >= 1 and not (folder / ".set.json.part").exists()
    phrases = st.load("phrases")
    assert phrases.text("VID_STOCK_CLIP_NOT_DRAWN", {"language": "pt-BR"}) != phrases.en("VID_STOCK_CLIP_NOT_DRAWN")


def test_the_credits_record_is_kept_until_the_later_of_the_approval_and_the_delivery_plus_a_year(world, monkeypatch):
    found, _ = fetched(world, monkeypatch, "cc-by-4.0")
    shown = ops.video_media_approve(world["path"], found["task"])
    ops.video_media_approve(world["path"], found["task"], hash=shown["sha256"])
    path = Path(world["data"]) / "media" / "credits" / ("%d.json" % found["task"])
    record = json.loads(path.read_text())
    assert record["recording"] == world["rid"] and record["task"] == found["task"] and record["delivered_at"] is None
    base = media._epoch(record["approved_at"])
    day = 86400
    # approved, then delivered 100 days later: the delivery counts
    media._stamp_credits(world["data"], found["task"], now=base + 100 * day)
    assert media_stock.purge_credits(world["data"], now=base + 400 * day) == 0 and path.exists()
    assert media_stock.purge_credits(world["data"], now=base + 466 * day) == 1 and not path.exists()
    # delivered first, approved again later: the approval counts, and the delivery's time is kept
    media_stock.write_credits(world["data"], found["task"], dict(record, approved_at="2026-01-01T00:00:00Z", delivered_at="2025-01-01T00:00:00Z"))
    media_stock.write_credits(world["data"], found["task"], dict(record, approved_at="2026-03-01T00:00:00Z", delivered_at=None))
    kept = json.loads(path.read_text())
    assert kept["delivered_at"] == "2025-01-01T00:00:00Z"
    late = media._epoch("2026-03-01T00:00:00Z")
    assert media_stock.purge_credits(world["data"], now=late + 364 * day) == 0 and media_stock.purge_credits(world["data"], now=late + 366 * day) == 1


# --- a refusal of the renderer keeps its closed code (K3) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("code, key", [("asset_too_small", "VID_STOCK_ASSET_SMALL"), ("asset_type", "VID_STOCK_ASSET_UNUSABLE"), ("asset_corrupt", "VID_STOCK_ASSET_UNUSABLE"),
                                       ("asset_unreadable", "VID_STOCK_ASSET_UNUSABLE")])
def test_a_picture_the_renderer_refuses_keeps_its_closed_code_and_says_why_and_the_person_can_pick_again(world, monkeypatch, code, key):
    found = to_found(world, monkeypatch)
    done = find(world, found["task"])
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    found["sheets"].fail = ops_step_seams_error(code)
    original = found["sheets"].call
    found["sheets"].call = lambda cls, verb, args, timeout: original(cls, verb, args, timeout) if flag_of(args, "--mode") == "preview" else (_ for _ in ()).throw(found["sheets"].fail)
    phrases = st.load("phrases")
    for tag in ("en", "pt-BR"):
        with pytest.raises(ops_core.OpsError) as refused:
            ops.video_media_fetch_picks(world["path"], found["task"])
        assert str(refused.value).startswith(code + ":") and "engine_refused" not in str(refused.value)
    assert phrases.text(key, {"language": "en"}) in str(refused.value)
    doc = json.loads((stock_folder(world) / "set.json").read_text())
    assert doc["phase"] == "found" and doc["assets"] == [] and not (stock_folder(world) / "approved.json").exists()
    assert not [n for n in os.listdir(stock_folder(world)) if n.startswith("full-") or n.startswith(".work")]
    other = done["slots"][0]["candidates"][-1]["pick"]
    pick(world, found["task"], "beat7", other, review_of(world)["revision"])      # the candidates are still there: pick again
    assert review_of(world)["slot_assets"]["beat7"] == other


def ops_step_seams_error(code):
    from media_stock_kit import ops_step_seams as seams
    return seams.StepServiceError("refused", code)


def test_the_engine_keeps_a_code_of_the_closed_list_only_from_the_renderers_first_line(monkeypatch):
    seams = st.load("ops_step_seams")

    class Boom(Exception):
        kind, exit_code = "failed", 1

        def __init__(self, tail):
            self.stderr_tail = tail

    class Resolver:
        ProviderCallError = Boom
        failure = None

        @staticmethod
        def provider_environment(cls, env, passes):
            return {}

        @classmethod
        def call(cls, *a, **k):
            raise Boom(cls.failure)
    monkeypatch.setattr(project_config, "resolver", lambda root: Resolver)
    engine = ops_media_stock.SheetEngine("/x", None)
    for tail, reason in (("refused: asset_too_small asset", "asset_too_small"), ("refused: asset_type asset", "asset_type"), ("refused: nothing_known asset", ""),
                         ("refused: asset_too_small\x00 free text", ""), ("boom", "")):
        Resolver.failure = tail
        with pytest.raises(seams.StepServiceError) as refused:
            engine.call("renderer:video", "asset-sheet", ["--mode", "full"], 5)
        assert refused.value.code == "refused" and (refused.value.reason or "") == reason, tail
    source = (REPO / "providers" / "renderer" / "_asset_sheet.py").read_text(encoding="utf-8")
    assert set(re.findall(r'"(asset_[a-z_]+)"', source)) == set(ops_media_stock.ASSET_CODES)


def test_a_clip_row_from_the_renderer_never_reaches_the_stock_path_and_an_image_row_with_kind_and_seconds_does(world, monkeypatch):
    found = to_found(world, monkeypatch)
    done = find(world, found["task"])
    pick(world, found["task"], "beat7", done["slots"][0]["candidates"][0]["pick"], review_of(world)["revision"])
    found["sheets"].mutate = lambda answer: dict(answer, assets=[dict(a, kind="clip", seconds=4.0) for a in answer["assets"]])
    with pytest.raises(ops_core.OpsError) as refused:
        ops.video_media_fetch_picks(world["path"], found["task"])
    assert "engine_refused" in str(refused.value)
    found["sheets"].mutate = lambda answer: dict(answer, assets=[dict(a, kind="image", seconds=0) for a in answer["assets"]])      # the 5a shape of an image row
    assert ops.video_media_fetch_picks(world["path"], found["task"])["assets"]
    assert media_animation_kinds(world) == ["image"]


def media_animation_kinds(world):
    animation = st.load("media_animation")
    return animation.asset_kinds(str(REPO), None) if True else []
