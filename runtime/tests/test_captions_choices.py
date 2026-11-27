"""The video's own choices in the caption review (package P2a): the edit kinds `caption`, `zoom` and `font` (runtime/captions.py), how they reach the renderer's `base`
as flags (runtime/step_media.py), and that a video that chooses nothing is asked for exactly what it was. Pure but for the step tests, which run the media step over the
kit's fake engine. The words and names are the fictional ones of media_kit.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_captions_choices.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import (flag, open_items, ops, ops_core, run_task, steps, task_row, to_gate, to_review, transcript, work_file, world)  # noqa: F401  (world is a fixture)

cap = st.load("captions")
ops_media_edit = st.load("ops_media_edit")
REPO = Path(__file__).resolve().parents[2]
RENDERER = REPO / "providers" / "renderer"
BLOCKS = {"hf:caption-highlight", "hf:caption-pill-karaoke", "oh:caption"}
FONTS = {"inter-800": 800, "inter-500": 500, "jetbrains-mono-500": 500}
DEFAULTS = {"factor": 1.1, "push_in": 0.02}
CHOICE_FLAGS = ("--caption-block", "--caption-position", "--zoom", "--zoom-factor", "--push-in")


@pytest.fixture(autouse=True)
def no_engine_variable(monkeypatch):
    monkeypatch.delenv("RENDERER_VIDEO_PROVIDER", raising=False)
    monkeypatch.delenv("RENDERER_PROVIDER", raising=False)


def fresh():
    return cap.start_edited(transcript()), cap.new_review()


def apply(edited, review, edits, **kw):
    kw = dict({"caption_blocks": BLOCKS, "zoom_defaults": DEFAULTS, "font_ids": FONTS}, **kw)
    return cap.apply_edits(edited, review, edits, revision=review["revision"], proposals={}, beats={1, 2, 3}, slots=set(), **kw)


def refusal(edits, review=None, **kw):
    edited, held = fresh()
    with pytest.raises(cap.CaptionError) as caught:
        apply(edited, review or held, edits, **kw)
    return caught.value.code, caught.value.field


# ---------------------------------------------------------------- the review ops

def test_each_op_sets_merges_and_clears():
    edited, review = fresh()
    _, one, counts = apply(edited, review, [{"op": "caption", "block": "hf:caption-pill-karaoke"}, {"op": "zoom", "push_in": 0},
                                            {"op": "font", "role": "display", "id": "jetbrains-mono-500"}])
    assert one["caption"] == {"block": "hf:caption-pill-karaoke"} and one["zoom"] == {"push_in": 0}
    assert one["fonts"] == {"display": {"id": "jetbrains-mono-500", "weight": 500}}      # no weight given: the allow-list row's
    assert one["revision"] == review["revision"] + 1 and counts == {"edited": 0, "split": 0, "merged": 0, "deleted": 0}
    _, two, _ = apply(edited, one, [{"op": "caption", "position": "center"}, {"op": "zoom", "mode": "none", "factor": 1.3},
                                    {"op": "font", "role": "text", "id": "inter-800", "weight": 700}])
    assert two["caption"] == {"block": "hf:caption-pill-karaoke", "position": "center"}      # a later edit keeps what it does not name
    assert two["zoom"] == {"push_in": 0, "mode": "none", "factor": 1.3}
    assert two["fonts"]["text"] == {"id": "inter-800", "weight": 700} and set(two["fonts"]) == {"display", "text"}
    _, three, _ = apply(edited, two, [{"op": "caption", "clear": True}, {"op": "zoom", "clear": True}, {"op": "font", "role": "display", "clear": True}])
    assert three["caption"] == {} and three["zoom"] == {} and list(three["fonts"]) == ["text"]
    assert cap.check_review(two)["zoom"] == two["zoom"]      # what is stored reads back


@pytest.mark.parametrize("edit, code, field", [
    ({"op": "caption", "block": "hf:nothing-here"}, "unknown_caption_block", "edits[0].block"),
    ({"op": "caption", "block": "oh:keyword"}, "unknown_caption_block", "edits[0].block"),      # a block the engine does not draw as a caption
    ({"op": "caption", "block": "Karaoke"}, "bad_choice", "edits[0].block"),
    ({"op": "caption", "position": "top"}, "bad_choice", "edits[0].position"),
    ({"op": "caption"}, "bad_choice", "edits[0]"),
    ({"op": "caption", "clear": True, "block": "oh:caption"}, "unknown_field", "edits[0]"),
    ({"op": "caption", "clear": False}, "unknown_field", "edits[0]"),
    ({"op": "zoom", "mode": "spin"}, "bad_zoom", "edits[0].mode"),
    ({"op": "zoom", "factor": 0.9}, "bad_zoom", "edits[0].factor"),
    ({"op": "zoom", "factor": 10.5}, "bad_zoom", "edits[0].factor"),
    ({"op": "zoom", "factor": float("nan")}, "bad_zoom", "edits[0].factor"),
    ({"op": "zoom", "factor": True}, "bad_zoom", "edits[0].factor"),
    ({"op": "zoom", "factor": "1.2"}, "bad_zoom", "edits[0].factor"),
    ({"op": "zoom", "push_in": -0.1}, "bad_zoom", "edits[0].push_in"),
    ({"op": "zoom", "push_in": float("inf")}, "bad_zoom", "edits[0].push_in"),
    ({"op": "zoom", "factor": 9, "push_in": 0.2}, "bad_zoom", "edits[0].push_in"),      # 9 x 1.2 is over 10
    ({"op": "zoom", "factor": 10, "push_in": 0.001}, "bad_zoom", "edits[0].push_in"),
    ({"op": "zoom"}, "bad_choice", "edits[0]"),
    ({"op": "font", "role": "title", "id": "inter-800"}, "bad_choice", "edits[0].role"),
    ({"op": "font", "id": "inter-800"}, "bad_choice", "edits[0].role"),
    ({"op": "font", "role": "display", "id": "comic-400"}, "unknown_font", "edits[0].id"),
    ({"op": "font", "role": "display", "id": "../inter-800"}, "unknown_font", "edits[0].id"),
    ({"op": "font", "role": "display"}, "unknown_font", "edits[0].id"),
    ({"op": "font", "role": "display", "id": "inter-800", "weight": 750}, "bad_font_weight", "edits[0].weight"),
    ({"op": "font", "role": "display", "id": "inter-800", "weight": 1000}, "bad_font_weight", "edits[0].weight"),
    ({"op": "font", "role": "display", "id": "inter-800", "weight": "700"}, "bad_font_weight", "edits[0].weight"),
    ({"op": "font", "role": "display", "clear": True, "id": "inter-800"}, "unknown_field", "edits[0]"),
    ({"op": "caption", "block": "oh:caption", "start": 3}, "time_not_accepted", "edits[0]"),
    ({"op": "zoom", "seconds": 3}, "time_not_accepted", "edits[0]"),
    ({"op": "font", "role": "display", "id": "inter-800", "extra": 1}, "unknown_field", "edits[0]"),
])
def test_each_refusal_has_its_code_and_names_the_field_and_changes_nothing(edit, code, field):
    edited, review = fresh()
    before = json.dumps(review, sort_keys=True)
    assert refusal([edit]) == (code, field)
    assert json.dumps(review, sort_keys=True) == before


def test_the_combined_zoom_bound_is_checked_on_the_merged_values_with_the_renderers_defaults():
    edited, review = fresh()
    assert refusal([{"op": "zoom", "factor": 9.9}]) == ("bad_zoom", "edits[0].push_in")      # 9.9 x 1.02 (the default push-in) is over 10
    _, held, _ = apply(edited, review, [{"op": "zoom", "factor": 9.5, "push_in": 0.05}])      # 9.975
    assert held["zoom"] == {"factor": 9.5, "push_in": 0.05}
    assert refusal([{"op": "zoom", "push_in": 0.06}], held) == ("bad_zoom", "edits[0].push_in")      # merged with the stored factor
    _, same, _ = apply(edited, held, [{"op": "zoom", "push_in": 0}])
    assert same["zoom"] == {"factor": 9.5, "push_in": 0}
    _, other, _ = apply(edited, review, [{"op": "zoom", "factor": 9.9}], zoom_defaults={"factor": 1.1, "push_in": 0.0})      # the defaults come from the caller
    assert other["zoom"] == {"factor": 9.9}
    _, plain, _ = cap.apply_edits(edited, review, [{"op": "zoom", "factor": 2}], revision=0, proposals={}, beats=set(), slots=set())      # none given: ZOOM_DEFAULTS
    assert plain["zoom"] == {"factor": 2}


def test_no_catalogue_refuses_every_block_and_no_allow_list_refuses_every_font_and_nothing_else_is_refused():
    assert refusal([{"op": "caption", "block": "oh:caption"}], caption_blocks=None) == ("caption_unavailable", "edits[0].block")
    assert refusal([{"op": "font", "role": "text", "id": "inter-500"}], font_ids=None) == ("unknown_font", "edits[0].id")
    edited, review = fresh()
    _, held, _ = apply(edited, review, [{"op": "caption", "position": "center"}, {"op": "zoom", "push_in": 0}], caption_blocks=None, font_ids=None)
    assert held["caption"] == {"position": "center"} and held["zoom"] == {"push_in": 0}
    _, listed, _ = apply(edited, review, [{"op": "font", "role": "mono", "id": "inter-500"}], font_ids={"inter-500"})      # a set of ids: the default weight
    assert listed["fonts"]["mono"] == {"id": "inter-500", "weight": 500}


def test_a_refused_edit_in_a_list_leaves_the_whole_list_unapplied():
    edited, review = fresh()
    with pytest.raises(cap.CaptionError):
        apply(edited, review, [{"op": "zoom", "push_in": 0}, {"op": "caption", "block": "nope:x"}])
    assert review["zoom"] == {}


def test_a_stored_review_without_the_three_keys_reads_and_views_and_a_broken_one_is_refused():
    edited, review = fresh()
    old = {k: v for k, v in review.items() if k not in ("caption", "zoom", "fonts")}
    read = cap.check_review(old)
    assert (read["caption"], read["zoom"], read["fonts"]) == ({}, {}, {})
    shown = cap.view(edited, read, {}, {}, {})
    assert (shown["caption"], shown["zoom"], shown["fonts"]) == ({}, {}, {})
    _, held, _ = apply(edited, review, [{"op": "caption", "block": "oh:caption", "position": "center"}, {"op": "zoom", "push_in": 0},
                                        {"op": "font", "role": "display", "id": "inter-800"}])
    again = cap.view(edited, held, {}, {}, {})
    assert again["caption"] == held["caption"] and again["zoom"] == {"push_in": 0} and again["fonts"] == {"display": {"id": "inter-800", "weight": 800}}
    for key, value in (("caption", {"block": "karaoke"}), ("caption", {"position": "top"}), ("caption", {"style": "x"}), ("caption", []),
                       ("zoom", {"mode": "spin"}), ("zoom", {"factor": 11}), ("zoom", {"push_in": -1}), ("zoom", {"factor": True}), ("zoom", {"speed": 1}),
                       ("fonts", {"title": {"id": "inter-800", "weight": 800}}), ("fonts", {"display": {"id": "Inter 800", "weight": 800}}),
                       ("fonts", {"display": {"id": "inter-800"}}), ("fonts", {"display": {"id": "inter-800", "weight": 850}}), ("fonts", [])):
        with pytest.raises(cap.CaptionError) as caught:
            cap.check_review(dict(review, **{key: value}))
        assert (caught.value.code, caught.value.field) == ("review_unreadable", key)


def test_the_constants_equal_the_renderers_own():
    presets = json.loads((RENDERER / "renderer-presets.json").read_text(encoding="utf-8"))
    assert list(cap.CAPTION_POSITIONS) == presets["caption"]["positions"]
    assert list(cap.ZOOM_MODES) == presets["zoom"]["modes"]
    assert list(cap.FONT_ROLES) == presets["theme"]["font_roles"]
    assert cap.ZOOM_DEFAULTS == {"factor": presets["zoom"]["factor"], "push_in": presets["zoom"]["push_in"]}
    edl = (RENDERER / "_edl.py").read_text(encoding="utf-8")
    assert float(re.search(r"^ZOOM_MAX = ([0-9.]+)", edl, re.M).group(1)) == cap.ZOOM_MAX
    assets = (RENDERER / "_assets.py").read_text(encoding="utf-8")
    assert re.search(r'^FONT_ID = re.compile\(r"(.*)"\)', assets, re.M).group(1) == cap.FONT_ID.pattern
    blocks = (RENDERER / "_blocks.py").read_text(encoding="utf-8")
    assert re.search(r'^NAME = re.compile\(r"\(oh\|hf\):" \+ _SHORT\)', blocks, re.M)      # the names a `caption` edit accepts are the catalogue's own shape
    assert re.search(r'^_SHORT = r"(.*)"', blocks, re.M).group(1) == cap.BLOCK_NAME.pattern.split(":", 1)[1]
    schema = json.loads((RENDERER / "edl.schema.json").read_text(encoding="utf-8"))
    assert schema["$defs"]["edl"]["properties"]["captions"]["properties"]["block"]["pattern"] == "^" + cap.BLOCK_NAME.pattern + "$"
    assert schema["$defs"]["edl"]["properties"]["captions"]["properties"]["position"]["enum"] == list(cap.CAPTION_POSITIONS)


# ---------------------------------------------------------------- the step: the choices reach `base`

def edit(world, task, edits, revision=0):
    return ops_media_edit.edit(ops_core.context(world["path"]), task, revision, edits)


def present(args):
    return [f for f in CHOICE_FLAGS + ("--font",) if f in args]


def test_a_review_with_no_choice_asks_base_for_exactly_what_it_asked_before(world):
    task = to_review(world)
    first = world["engine"].of("base")[0]["args"]      # the proposal: the review has not been answered, no choice yet
    assert first[:2] == ["--transcript", first[1]] and present(first) == []
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    assert run_task(world, task)["stopped"] == "deliver"
    args = world["engine"].of("base")[-1]["args"]
    assert present(args) == []
    kinds = [a for a in args if a.startswith("--")]
    assert kinds == ["--transcript", "--analysis", "--out", "--retakes"]      # the identity is a default theme here, so no colour or font pair either
    result = steps.state_of(steps.kind_of("media"), task_row(world, task)["step_state"])["steps"]["base"]["result"]
    assert not {"caption", "zoom", "fonts"} & set(result)      # the step's result has no new key for a video that chose nothing


def test_each_choice_adds_exactly_its_flags_to_the_final_base(world):
    task = to_review(world)
    done = edit(world, task, [{"op": "caption", "block": "hf:caption-pill-karaoke", "position": "center"}, {"op": "zoom", "mode": "alternate", "factor": 1.25, "push_in": 0},
                              {"op": "font", "role": "display", "id": "jetbrains-mono-500"}])
    assert done["mode"] == "review" and done["answered"] is None
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    assert run_task(world, task)["stopped"] == "deliver"
    args = world["engine"].of("base")[-1]["args"]
    assert [flag(args, f) for f in ("--caption-block", "--caption-position", "--zoom", "--zoom-factor", "--push-in")] == ["hf:caption-pill-karaoke", "center", "alternate", "1.25", "0"]
    fonts = [args[i + 1] for i, a in enumerate(args) if a == "--font"]
    assert fonts == ["display=jetbrains-mono-500:500"]
    result = steps.state_of(steps.kind_of("media"), task_row(world, task)["step_state"])["steps"]["base"]["result"]
    assert result["caption"] == {"block": "hf:caption-pill-karaoke", "position": "center"} and result["fonts"] == {"display": {"id": "jetbrains-mono-500", "weight": 500}}
    assert result["zoom"] == {"mode": "alternate", "factor": 1.25, "push_in": 0}      # the fake engine writes no zoom block, so the review's own is shown


def test_a_choice_not_in_the_catalogue_or_the_allow_list_is_refused_by_the_operation_and_writes_nothing(world):
    task = to_review(world)
    for bad, code in (({"op": "caption", "block": "oh:keyword"}, "unknown_caption_block"), ({"op": "caption", "block": "hf:made-up"}, "unknown_caption_block"),
                      ({"op": "font", "role": "text", "id": "papyrus-400"}, "unknown_font"), ({"op": "zoom", "factor": 12}, "bad_zoom")):
        with pytest.raises(ops_core.OpsError) as refused:
            edit(world, task, [bad])
        assert code in str(refused.value)
    assert not work_file(world, "review.json").exists() or json.loads(work_file(world, "review.json").read_text())["revision"] == 0


def test_a_choice_made_at_the_delivery_approval_reaches_the_next_base_so_the_new_render_has_it(world):
    task, gate = to_gate(world)      # Risk 3 of the spec: an edit at the approval re-runs `base`, as the theme edit relies on
    assert present(world["engine"].of("base")[-1]["args"]) == []
    bases = len(world["engine"].of("base"))
    done = edit(world, task, [{"op": "caption", "block": "oh:caption"}, {"op": "zoom", "push_in": 0}])
    assert done["mode"] == "gate" and done["answered"] == gate["id"]
    world["engine"].salt = b"two"
    out = run_task(world, task)
    assert out["ok"] is True and out["stopped"] == "deliver"
    assert len(world["engine"].of("base")) > bases      # base ran again
    args = world["engine"].of("base")[-1]["args"]
    assert flag(args, "--caption-block") == "oh:caption" and flag(args, "--push-in") == "0" and "--zoom" not in args
    [fresh_gate] = open_items(world, task)
    assert fresh_gate["payload_sha256"] != gate["payload_sha256"]


def test_the_font_op_accepts_every_id_of_the_committed_allow_list_with_its_weight():
    weights = ops_media_edit.theme.font_weights(str(REPO))
    assert {"montserrat-800", "anton-400", "oswald-700", "poppins-500"} <= set(weights)
    edited, review = fresh()
    for ident, weight in weights.items():
        _, held, _ = apply(edited, review, [{"op": "font", "role": "display", "id": ident}], font_ids=weights)
        assert held["fonts"]["display"] == {"id": ident, "weight": weight} and cap.FONT_ID.fullmatch(ident)
        _, again, _ = apply(edited, review, [{"op": "font", "role": "text", "id": ident, "weight": 700}], font_ids=weights)
        assert again["fonts"]["text"]["weight"] == 700
