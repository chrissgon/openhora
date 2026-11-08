"""The lines of a delivery's body (package V1d-2; runtime/deliver_document.py `card_lines`, `title`, `PREVIEW_MAX_BYTES`): the body as card lines of the phrase table's family
CARD_, so a phone reads the deliver card in the project's language, with the English body unchanged byte for byte; the fixed title; and the two bodies of the caption
review, said whole in the project's language. Offline; every value is made up here.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_deliver_card_lines.py
"""
from __future__ import annotations

import hashlib
import json

import pytest

import standin_tree as st
from media_kit import (open_items, step_media, steps, to_review, world)  # noqa: F401  (world is a fixture)

dd = st.load("deliver_document")
phrases = st.load("phrases")

VIDEO_SHA = hashlib.sha256(b"northwind render").hexdigest()
COVER_SHA = hashlib.sha256(b"northwind cover").hexdigest()
BLOCK_SHAS = [hashlib.sha256(b"block a").hexdigest(), hashlib.sha256(b"block b").hexdigest()]
DIGEST = hashlib.sha256(b"the document").hexdigest()
POST = "docs/marketing/content/aster-lane-launch.md"
PT = {"language": "pt-BR"}


def make(cover=True, blocks=0, preview=True):
    video = {"name": f"render-{VIDEO_SHA[:12]}.mp4", "sha256": VIDEO_SHA, "size": 12_345_678, "duration_ms": 31_000}
    held = {"name": f"cover-{COVER_SHA[:12]}.png", "sha256": COVER_SHA, "size": 99} if cover else None
    ids = ["oh:caption", "oh:keyword"][:blocks]
    return dd.build(task=12, recording="0123456789abcdef", platform="instagram", post=POST, video=video, cover=held, verify_platform="instagram",
                    blocks=[{"id": i, "sha256": BLOCK_SHAS[n]} for n, i in enumerate(ids)],
                    preview={"sha256": VIDEO_SHA, "size": 12_345_678, "from_sha256": VIDEO_SHA} if preview else None)


FOUR = [make(), make(cover=False), make(blocks=2, preview=False), make(cover=False, blocks=1, preview=False)]


@pytest.mark.parametrize("doc", FOUR)
def test_the_lines_are_a_valid_card_whose_english_text_is_the_body_byte_for_byte(doc):
    lines = dd.card_lines(doc, DIGEST)
    assert phrases.card_valid(lines)
    assert phrases.card_text(lines) == dd.body(doc, DIGEST)
    assert all(isinstance(v, str) for _, fields in lines for v in fields.values())


def test_the_lines_that_the_document_decides_are_present_or_absent_by_what_it_holds():
    keys = lambda doc: [k for k, _ in dd.card_lines(doc, DIGEST)]      # noqa: E731
    full, bare = keys(make(blocks=2)), keys(make(cover=False, preview=False))
    assert full[0] == "CARD_VIDEO_PLATFORM" and full[-2:] == ["CARD_VIDEO_DIGEST", "CARD_VIDEO_CLOSING"]
    assert "CARD_VIDEO_COVER" in full and "CARD_VIDEO_NO_COVER" not in full and full.count("CARD_VIDEO_BLOCK") == 2 and "CARD_VIDEO_PREVIEW" in full
    assert "CARD_VIDEO_NO_COVER" in bare and "CARD_VIDEO_NO_BLOCKS" in bare and "CARD_VIDEO_NO_PREVIEW" in bare


def test_the_english_body_is_what_it_was_before_the_lines_so_a_stored_body_and_its_hash_do_not_change():
    doc = make(blocks=2)
    assert dd.body(doc, DIGEST).splitlines()[:3] == [
        "Platform: instagram", f"Post: {POST}", f"Video: render-{VIDEO_SHA[:12]}.mp4, 12.3 MB, 31.0 s, sha256 {VIDEO_SHA}"]
    assert dd.body(doc, DIGEST).splitlines()[-1] == dd.CLOSING


@pytest.mark.parametrize("doc", FOUR)
def test_in_portuguese_the_card_says_the_lines_and_leaves_the_values_as_they_are(doc):
    text = phrases.card_text(dd.card_lines(doc, DIGEST), PT)
    assert text != dd.body(doc, DIGEST)
    assert "Plataforma: instagram" in text and f"Publica\u00e7\u00e3o: {POST}" in text and "Aprovar marca este arquivo exato" in text
    for value in (f"render-{VIDEO_SHA[:12]}.mp4", VIDEO_SHA, DIGEST, "12.3", "31.0"):
        assert value in text
    assert "Platform:" not in text and "Approving marks" not in text


def test_the_title_is_fixed_and_a_phone_reads_it_in_the_project_language():
    for doc in FOUR:
        assert dd.title(doc) == dd.TITLE == "Deliver the video"
    assert phrases.heading(dd.title(FOUR[0]), PT) == "Entregar o vídeo"
    assert phrases.heading(dd.title(FOUR[0]), None) == "Deliver the video"


def test_the_largest_render_that_is_its_own_preview_is_20_mib():
    assert dd.PREVIEW_MAX_BYTES == 20 * 1024 * 1024


@pytest.mark.parametrize("still", [True, False])
def test_the_review_body_a_task_stores_is_the_whole_template_and_is_said_in_portuguese(world, monkeypatch, still):
    if not still:      # a review whose task made no still: the decision is built from a state with no `still` step
        built = step_media.KIND.decisions["review"]
        monkeypatch.setitem(step_media.KIND.decisions, "review", lambda ctx, state: built(ctx, {**state, "steps": {k: v for k, v in state["steps"].items() if k != "still"}}))
    task = to_review(world)
    [review] = open_items(world, task)
    text = review["body"]
    line = "A still was made for the face box." if still else "No still was made for the face box."
    assert review["title"] == "Check the captions" and text.endswith("\n\n" + steps.VERDICT_LINE) and line in text and "still-" not in text
    said = phrases.body(text, PT)
    assert said != text and "palavras foram transcritas" in said and "caixa do rosto" in said and ("Uma imagem" in said) is still
    assert "`continue`" in said and "`stop`" in said
    assert phrases.heading(review["title"], PT) == "Revise as legendas"


def test_both_review_bodies_match_the_template_the_step_builds_character_for_character():
    verdict = "\n\n" + steps.VERDICT_LINE
    for key, line in (("BODY_VIDEO_REVIEW_STILL", "A still was made for the face box."), ("BODY_VIDEO_REVIEW_NO_STILL", "No still was made for the face box.")):
        built = "\n".join(["{words} words were transcribed.", "{beats} beats are below the match threshold.", line, "Edit the captions, then continue."]) + verdict
        assert phrases.en(key) == built
        body = built.format(words=7, beats=2)
        assert phrases.body(body, PT).startswith("7 palavras foram transcritas.\n2 trechos")
        assert phrases.body(body, None) == body
