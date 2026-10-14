"""The project's theme in the media pipeline (package P4g of the short-video plan, A6.3): the `base` step appends the arguments of
runtime/theme.py, so the run with confirmed retakes carries them too, and the theme record reaches the step's result and render.json.
Through the real operations layer and the stand-in providers (runtime/tests/pipeline_kit.py): the stand-in renderer runs the REAL
`base` of providers/renderer/_inner.py, so `edl.json` shows the theme the renderer built. Offline, no model. The identity is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_pipeline_theme.py
"""
from __future__ import annotations

import json
import os
import shutil

import pytest

import pipeline_kit as kit
import standin_tree as st
from test_media_pipeline import code_task, edit, finish_review, make_world, start, state

ops = st.load("ops")
pipeline = st.load("pipeline")
theme = st.load("theme")

BLOCK = {
    "version": 1, "status": "approved", "mode_default": "dark",
    "color": {"bg": {"dark": "#0A1220", "light": "#FFFFFF"}, "fg": {"dark": "#F4F7FB", "light": "#101820"},
              "muted": {"dark": "#A9B4C4", "light": "#566275"}, "accent": {"dark": "#3DDC97", "light": "#0E7A4D"},
              "surface": {"dark": "#17233A", "light": "#E6ECF5"}},
    "font": {"display": {"family": "Inter", "weight": 800}, "body": {"family": "Inter", "weight": 500},
             "mono": {"family": "JetBrains Mono", "weight": 500}},
}
PROSE = "Orchard Studio keeps one green accent and a private motto nobody should read in a log."


def identity(block=BLOCK, status="approved (2026-10-01)"):
    text = block if isinstance(block, str) else json.dumps(block)
    return "# Visual identity: Orchard Studio\n\n- Owner: brand-identity\n- Status: %s\n\n%s\n\n## Tokens\n```brand-tokens\n%s\n```\n" % (status, PROSE, text)


def put(w, text):
    folder = os.path.join(w.project, "docs", "brand")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "identity.md"), "w", encoding="utf-8") as f:
        f.write(text)


def renderer_files(w):
    """The renderer's data the theme reads from the checkout the pipeline is pointed at (the stand-in tree holds none)."""
    for rel in ("providers/renderer/renderer-presets.json", "providers/renderer/assets/fonts/allowlist.json"):
        target = w.tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(kit.REPO / rel, target)


@pytest.fixture
def w(tmp_path, monkeypatch):
    world = make_world(tmp_path, monkeypatch)
    renderer_files(world)
    return world


def pairs(call, flag):
    return {call[i + 1].partition("=")[0]: call[i + 1].partition("=")[2] for i in range(len(call) - 1) if call[i] == flag}


def base_calls(w):
    return [c for c in kit.calls(w.tree, "renderer") if c[0] == "base"]


def edl(w):
    with open(os.path.join(w.folder, "edl.json"), encoding="utf-8") as f:
        return json.load(f)


def render_json(w):
    with open(os.path.join(w.folder, "render.json"), encoding="utf-8") as f:
        return json.load(f)


def everything_written(w):
    """Every file the pipeline wrote for the recording that is text, and the code task, as one string."""
    out = [json.dumps(code_task(w))]
    for name in os.listdir(w.folder):
        path = os.path.join(w.folder, name)
        if name.endswith(".json"):
            out.append(open(path, encoding="utf-8").read())
    return "\n".join(out)


# --- the arguments reach the renderer, in both runs of `base` ------------------------------------------------------------------------


def test_the_identitys_colours_and_fonts_reach_base_and_the_edit_list_carries_them(w):
    put(w, identity())
    start(w)
    done = finish_review(w)
    assert done["ok"] is True and done["stopped"] == "approval"
    proposal, final = base_calls(w)
    assert "--color" not in proposal and "--font" not in proposal, "the proposal list is not the render's: no theme"
    colors = pairs(final, "--color")
    assert colors == {"bg": "#0A1220", "text": "#F4F7FB", "muted": "#A9B4C4", "accent": "#3DDC97", "chip_border": "#3DDC97", "chip_fill": "#17233A",
                      "chip_text": "#3DDC97"}
    assert pairs(final, "--font") == {"display": "inter-800:800", "text": "inter-500:500", "mono": "jetbrains-mono-500:500"}
    theme_of_edl = edl(w)["theme"]
    assert theme_of_edl["colors"] == dict(theme_of_edl["colors"], **colors), "`edl.theme` equals the flags the renderer was given"
    assert theme_of_edl["fonts"] == {"display": {"id": "inter-800", "weight": 800}, "text": {"id": "inter-500", "weight": 500},
                                     "mono": {"id": "jetbrains-mono-500", "weight": 500}}


def test_the_run_with_confirmed_retakes_carries_the_theme_too(w):
    put(w, identity())
    start(w)
    edit(w, [{"op": "retake", "id": "retake-1", "confirmed": True}])
    finish_review(w)
    proposal, first, second = base_calls(w)
    assert "--confirm" not in first and second[second.index("--confirm") + 1] == "retake-1"
    flags = lambda call: [a for i, a in enumerate(call) if (i and call[i - 1] in ("--color", "--font"))]    # noqa: E731
    assert flags(first) == flags(second) and len(flags(second)) == 10
    assert [p["confirmed"] for p in edl(w)["proposals"]] == [True]
    assert edl(w)["theme"]["colors"]["accent"] == "#3DDC97", "the edit list the render uses is the second run's, and it has the accent"


def test_the_theme_record_is_in_the_step_result_and_in_render_json_beside_the_fonts(w):
    put(w, identity())
    start(w)
    finish_review(w)
    recorded = state(w)["steps"]["base"]["result"]["theme"]
    assert recorded["source"] == "identity" and recorded["reason"] is None and recorded["notes"] == []
    assert recorded["colors"]["accent"] == "#3DDC97" and recorded["fonts"]["display"] == "inter-800:800" and len(recorded["hash"]) == 64
    assert state(w)["steps"]["render"]["result"]["theme"] == recorded
    kept = render_json(w)
    assert kept["theme"] == recorded and "fonts" in kept, "the theme beside `fonts`, which render.json already held"
    assert render_json(w)["cover"]["name"], "the record survives the second write of render.json, when the cover is cut"
    assert render_json(w)["theme"] == recorded


def test_no_identity_runs_the_renderers_default_theme_and_the_record_says_so(w):
    start(w)
    finish_review(w)
    assert all("--color" not in c and "--font" not in c for c in base_calls(w))
    recorded = state(w)["steps"]["base"]["result"]["theme"]
    assert (recorded["source"], recorded["reason"], recorded["colors"], recorded["fonts"]) == ("default", "no_identity", {}, {})
    assert render_json(w)["theme"] == recorded
    assert edl(w)["theme"]["colors"]["accent"] == "#FFC93C", "the renderer's own default, a yellow"


def test_an_identity_with_the_old_open_block_runs_the_default_theme_and_says_the_block_is_not_closed(w):
    put(w, identity({"mode_default": "dark", "color": {"dark": {"bg": "#000000", "text": "#FFFFFF", "accent": "#07B6F0"}}, "font": {"body": "system-ui"}},
                    status="aprovado (2026-10-01)"))
    start(w)
    done = finish_review(w)
    assert done["ok"] is True
    assert all("--color" not in c for c in base_calls(w))
    recorded = state(w)["steps"]["base"]["result"]["theme"]
    assert (recorded["source"], recorded["reason"]) == ("default", "open_block")
    assert render_json(w)["theme"]["reason"] == "open_block"


# --- a refusal stops the step, resumable, and the person fixes it or chooses the default ------------------------------------------------


def test_a_draft_identity_stops_the_base_step_with_its_sentence_and_the_task_resumes_there(w):
    put(w, identity(dict(BLOCK, status="draft"), status="draft"))
    start(w)
    first = finish_review(w)
    assert first["ok"] is False and first["failed"] == "base" and first["code"] == "theme_draft"
    task = code_task(w)
    assert task["state"] == "failed"
    assert task["note"] == "base: theme_draft status -- " + theme.DRAFT_SENTENCE
    assert state(w)["failure"]["step"] == "base" and state(w)["steps"]["base"]["status"] == "failed"
    assert [c[0] for c in kit.calls(w.tree, "renderer")] == ["analyse", "base", "align"], "no renderer call was made for the refused step"
    put(w, identity())                                                   # the person approves it
    resumed = ops.media_pipeline(w.project, w.rid)
    assert resumed["ok"] is True and resumed["steps"]["base"] == "done" and resumed["stopped"] == "approval"
    assert kit.verbs(w.tree, "renderer") == ["analyse", "base", "align", "base", "align", "check", "render", "cover"]
    assert pairs(base_calls(w)[-1], "--color")["accent"] == "#3DDC97"


def test_a_low_contrast_theme_stops_the_step_with_the_pair_named(w):
    put(w, identity(dict(BLOCK, color=dict(BLOCK["color"], muted={"dark": "#4A5160"}))))
    start(w)
    out = finish_review(w)
    assert out["ok"] is False and out["failed"] == "base" and out["code"] == "theme_low_contrast"
    note = code_task(w)["note"]
    assert note.startswith("base: theme_low_contrast muted_on_chip_fill -- the muted on chip fill contrast is ") and "choose the default theme for this render" in note
    assert "Orchard" not in note


def test_the_choice_of_the_default_theme_goes_through_the_real_review_and_runs_it_and_records_the_choice(w):
    put(w, identity(dict(BLOCK, color=dict(BLOCK["color"], muted={"dark": "#4A5160"}))))
    start(w)
    failed = finish_review(w)
    assert failed["code"] == "theme_low_contrast" and "captions-edit" in code_task(w)["note"], "the refusal names the way out"
    ops.prepare_again(w.project, w.rid, "review")                                   # the way the sentence names: open the review again ...
    assert ops.captions_read(w.project, w.rid)["theme"] == "identity"
    shown = edit(w, [{"op": "theme", "choice": "default"}])                         # ... choose ...
    assert shown["theme"] == "default"
    resumed = finish_review(w)                                                       # ... and say done
    assert resumed["ok"] is True and resumed["stopped"] == "approval"
    assert all("--color" not in c for c in base_calls(w)[-1:])
    recorded = state(w)["steps"]["base"]["result"]["theme"]
    assert (recorded["source"], recorded["reason"]) == ("default", "chosen") and render_json(w)["theme"] == recorded


def test_the_theme_choice_of_the_review_is_closed_kept_and_undone_by_the_same_edit(w):
    start(w)
    assert ops.captions_read(w.project, w.rid)["theme"] == "identity"
    assert edit(w, [{"op": "theme", "choice": "default"}])["theme"] == "default"
    assert edit(w, [{"op": "theme", "choice": "identity"}])["theme"] == "identity"
    for bad in ({"op": "theme", "choice": "blue"}, {"op": "theme", "choice": ""}, {"op": "theme", "choice": None}, {"op": "theme"},
                {"op": "theme", "choice": "default", "color": "#FFFFFF"}):
        with pytest.raises(ops.OpsError):
            edit(w, [bad])
    assert ops.captions_read(w.project, w.rid)["theme"] == "identity", "an edit refused as a whole changes nothing"
    review_path = os.path.join(w.data, "media", w.rid, "review.json")
    stored = json.load(open(review_path))
    assert stored["version"] == 1 and stored["theme"] == "identity"
    del stored["theme"]                                                              # a review written before the key existed is still read
    json.dump(stored, open(review_path, "w"))
    assert ops.captions_read(w.project, w.rid)["theme"] == "identity"
    stored["theme"] = "blue"
    json.dump(stored, open(review_path, "w"))
    with pytest.raises(ops.OpsError):
        ops.captions_read(w.project, w.rid)


def test_the_approval_says_when_the_colours_are_the_renderers_own_and_why(w):
    put(w, identity({"mode_default": "dark", "color": {"dark": {"bg": "#000000"}}, "font": {"body": "system-ui"}}, status="aprovado (2026-10-14)"))
    start(w)
    finish_review(w)
    [pending] = [p for p in ops.pending(w.project)["pending"] if p["title"] == "Approve the rendered video"]
    body = ops.pending(w.project, pending["id"])["body"]
    assert "Colours: default theme: the identity's block is in the old format; run brand-identity again to write the closed one." in body
    payload = ops.pending(w.project, pending["id"])["payload"]["media_pipeline"]
    assert payload["theme"] == {"source": "default", "reason": "open_block"}


def test_the_approval_says_nothing_about_colours_when_they_come_from_the_identity(w):
    put(w, identity())
    start(w)
    finish_review(w)
    [pending] = [p for p in ops.pending(w.project)["pending"] if p["title"] == "Approve the rendered video"]
    item = ops.pending(w.project, pending["id"])
    assert "Colours" not in item["body"] and item["payload"]["media_pipeline"]["theme"] == {"source": "identity", "reason": None}


def test_a_bad_colour_and_an_unknown_role_stop_the_step_without_a_word_of_the_file(w):
    put(w, identity(dict(BLOCK, color=dict(BLOCK["color"], accent={"dark": "teal"}))))
    start(w)
    out = finish_review(w)
    assert (out["failed"], out["code"]) == ("base", "theme_bad_color")
    note = code_task(w)["note"]
    assert note.startswith("base: theme_bad_color color.accent.dark -- ") and "teal" not in note
    put(w, identity(dict(BLOCK, font=dict(BLOCK["font"], chip={"family": "Inter", "weight": 500}))))
    out = ops.media_pipeline(w.project, w.rid)
    assert (out["failed"], out["code"]) == ("base", "theme_unknown_role")


def test_nothing_of_the_identity_but_colours_and_font_ids_reaches_the_state_the_task_or_render_json(w):
    put(w, identity())
    start(w)
    finish_review(w)
    written = everything_written(w) + json.dumps(ops.status(w.project))
    for text in ("Orchard", "private motto", "green accent", "Visual identity"):
        assert text not in written, text


def test_a_changed_identity_changes_the_recorded_hash_when_the_step_runs_again(w):
    put(w, identity())
    start(w)
    finish_review(w)
    before = render_json(w)["theme"]["hash"]
    put(w, identity(dict(BLOCK, color=dict(BLOCK["color"], accent={"dark": "#E9C46A"}))))
    assert theme.theme_args(w.project)[1]["hash"] != before, "the card of a later package compares exactly this"
    ops.prepare_again(w.project, w.rid, "base")
    out = ops.media_pipeline(w.project, w.rid)
    assert out["ok"] is True
    assert render_json(w)["theme"]["hash"] != before and render_json(w)["theme"]["colors"]["accent"] == "#E9C46A"
