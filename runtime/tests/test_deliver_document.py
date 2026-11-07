"""Tests of runtime/deliver_document.py, the pure document a delivery's approval covers: its closed keys and types, the names tied to the
hashes, the preview that must come from this very render, the blocks' order and size, and the text the person reads. Offline; no file and no
store; every value is made up here.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_deliver_document.py
"""
from __future__ import annotations

import copy
import hashlib

import pytest

import standin_tree as st

dd = st.load("deliver_document")

VIDEO_SHA = hashlib.sha256(b"northwind render").hexdigest()
COVER_SHA = hashlib.sha256(b"northwind cover").hexdigest()
PREVIEW_SHA = hashlib.sha256(b"northwind preview").hexdigest()
DIGEST = hashlib.sha256(b"the document").hexdigest()
POST = "docs/marketing/content/aster-lane-launch.md"


def video(sha=VIDEO_SHA):
    return {"name": f"render-{sha[:12]}.mp4", "sha256": sha, "size": 12_345_678, "duration_ms": 31_000}


def cover(sha=COVER_SHA):
    return {"name": f"cover-{sha[:12]}.png", "sha256": sha, "size": 99}


def make(**changes):
    args = dict(task=12, recording="0123456789abcdef", platform="instagram", post=POST, video=video(), cover=cover(),
                verify_platform="instagram", blocks=(), preview=None)
    args.update(changes)
    return dd.build(**args)


def refused(doc) -> str:
    with pytest.raises(ValueError) as e:
        dd.check(doc)
    return str(e.value)


def test_the_document_is_built_and_checked_and_comes_back_whole():
    doc = make()
    assert sorted(doc) == sorted(dd.KEYS) and doc["effect"] == "deliver" and doc["version"] == 1
    assert doc["verify"] == {"passed": True, "platform": "instagram"} and doc["blocks"] == [] and doc["preview"] is None
    assert dd.check(doc) is doc
    assert make(cover=None)["cover"] is None


def test_a_missing_key_is_refused_and_so_is_an_extra_one():
    doc = make()
    for key in dd.KEYS:
        broken = copy.deepcopy(doc)
        del broken[key]
        assert refused(broken) == key
    extra = {**doc, "note": "Aster Lane"}
    assert refused(extra) == "keys" and "Aster" not in refused(extra), "the message names a field and echoes no content"
    assert refused([]) == "document"


def test_a_wrong_type_or_value_in_a_field_is_refused():
    for field, value in (("effect", "publish"), ("version", 2), ("version", True), ("task", 0), ("task", "12"), ("task", True),
                         ("recording", "ABC"), ("recording", "0123456789abcde"), ("platform", "Insta gram"), ("platform", ""),
                         ("post", "docs/marketing/content/../x.md"), ("post", "docs/other/a.md"), ("post", "/etc/passwd"),
                         ("video", []), ("cover", "none"), ("verify", {"passed": True}), ("blocks", "[]"), ("preview", {})):
        broken = {**make(), field: value}
        assert refused(broken).split(".")[0] == field, (field, value)


def test_the_video_and_cover_names_must_match_their_hashes():
    doc = make()
    for part, key in (("video", "name"), ("cover", "name")):
        broken = copy.deepcopy(doc)
        broken[part][key] = f"{'render' if part == 'video' else 'cover'}-000000000000.{'mp4' if part == 'video' else 'png'}"
        assert refused(broken) == f"{part}.name"
    broken = copy.deepcopy(doc)
    broken["video"]["size"] = 0
    assert refused(broken) == "video.size"
    broken = copy.deepcopy(doc)
    broken["video"]["extra"] = 1
    assert refused(broken) == "video"
    broken = copy.deepcopy(doc)
    broken["video"]["sha256"] = "XYZ"
    assert refused(broken) == "video.sha256"


def test_a_verification_that_did_not_pass_or_ran_for_another_platform_is_refused():
    assert refused({**make(), "verify": {"passed": False, "platform": "instagram"}}) == "verify.passed"
    assert refused({**make(), "verify": {"passed": True, "platform": "tiktok"}}) == "verify.platform"


def test_a_preview_made_from_another_render_is_refused():
    good = {"sha256": PREVIEW_SHA, "size": 4000, "from_sha256": VIDEO_SHA}
    assert make(preview=good)["preview"] == good
    assert refused({**make(), "preview": {**good, "from_sha256": COVER_SHA}}) == "preview.from_sha256"
    assert refused({**make(), "preview": {**good, "size": 0}}) == "preview.size"
    assert refused({**make(), "preview": {"sha256": PREVIEW_SHA, "size": 4000}}) == "preview.from_sha256"


def test_a_card_may_approve_only_a_delivery_whose_preview_it_carried():
    assert dd.on_cards(make()) is False
    assert dd.on_cards(make(preview={"sha256": PREVIEW_SHA, "size": 4000, "from_sha256": VIDEO_SHA})) is True
    stale = {**make(), "preview": {"sha256": PREVIEW_SHA, "size": 4000, "from_sha256": COVER_SHA}}
    assert dd.on_cards(stale) is False, "a preview of another render approves nothing"
    assert dd.on_cards(None) is False and dd.on_cards({}) is False


def test_the_blocks_are_sorted_bounded_and_named_in_a_namespace():
    one = {"id": "core:lower-third", "sha256": hashlib.sha256(b"1").hexdigest()}
    two = {"id": "core:progress-bar", "sha256": hashlib.sha256(b"2").hexdigest()}
    assert make(blocks=[one, two])["blocks"] == [one, two]
    assert refused({**make(), "blocks": [two, one]}) == "blocks.order"
    assert refused({**make(), "blocks": [one, one]}) == "blocks.order"
    assert refused({**make(), "blocks": [{"id": "lower-third", "sha256": one["sha256"]}]}) == "blocks.id"
    assert refused({**make(), "blocks": [{"id": "core:x", "sha256": "abc"}]}) == "blocks.sha256"
    assert refused({**make(), "blocks": [{"id": "core:x"}]}) == "blocks.sha256"
    many = [{"id": f"core:block-{n:03d}", "sha256": one["sha256"]} for n in range(64)]
    assert len(make(blocks=many)["blocks"]) == 64
    many.append({"id": "core:block-999", "sha256": one["sha256"]})
    assert refused({**make(), "blocks": many}) == "blocks"


def test_build_refuses_what_check_refuses():
    with pytest.raises(ValueError):
        make(platform="Not A Platform")
    with pytest.raises(ValueError):
        make(verify_platform="tiktok")
    with pytest.raises(ValueError):
        make(video={**video(), "name": "render-aaaaaaaaaaaa.mp4"})


def test_the_text_the_person_reads_holds_every_fact_and_the_closing_sentence():
    one = {"id": "core:lower-third", "sha256": hashlib.sha256(b"1").hexdigest()}
    plain = dd.body(make(), DIGEST).split("\n")
    assert plain[0] == "Platform: instagram" and plain[1] == f"Post: {POST}"
    assert plain[2] == f"Video: render-{VIDEO_SHA[:12]}.mp4, 12.3 MB, 31.0 s, sha256 {VIDEO_SHA}"
    assert plain[3] == f"Cover: cover-{COVER_SHA[:12]}.png, sha256 {COVER_SHA}"
    assert plain[4:7] == ["verified for instagram", "no animation blocks", "no preview"]
    assert plain[-2] == f"Delivery document sha256 {DIGEST}"
    assert plain[-1] == "Approving marks this exact file downloadable. Nothing is published."
    full = dd.body(make(cover=None, blocks=[one], preview={"sha256": PREVIEW_SHA, "size": 4000, "from_sha256": VIDEO_SHA}), DIGEST)
    assert "Cover: no cover" in full and f"core:lower-third {one['sha256']}" in full
    assert f"preview {PREVIEW_SHA}, made from {VIDEO_SHA}" in full and "no preview" not in full
    for text in (full, "\n".join(plain)):
        assert text.count("docs/") == 1, "no text of the project beyond the post's path"


def test_the_title_the_description_and_the_closed_facts():
    doc = make()
    assert dd.title(doc) == "Deliver the video for instagram"
    assert dd.describe(doc) == f"deliver render-{VIDEO_SHA[:12]}.mp4 (instagram)"
    assert dd.summary(doc) == {"word": "deliver", "platform": "instagram", "video_sha256": VIDEO_SHA, "size": 12_345_678,
                               "duration_ms": 31_000, "blocks": 0, "preview": False}


def test_the_module_imports_nothing_of_the_repository_and_holds_no_function_that_delivers():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(dd.__file__).read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "re"}
