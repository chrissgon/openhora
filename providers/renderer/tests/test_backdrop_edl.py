"""P4b: the blurred shot, the edit-list side. `_edl.resolve_blurs` (which beats blur the speaker's shot, and over which frames), the timeline's `blurs` key (only a
timeline with a blurred span has it), the defaults' bounds (`_edl.check_backdrop_config`) and the render's `blurs_drawn` (`_render._blur_summary`). No limit on the
face, no count (the maintainer, 2026-11-28). Offline, synthetic, fictional."""
from __future__ import annotations

import copy
import json

import pytest

import renderer_kit as K
import _edl
import _render
import _vocab
from _text import Refusal
from _vocab import load_data, load_vocabulary
from test_transitions_edl import beats_of, entry, synthetic_edl

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))


def card(bid, a, b, **params):
    return entry(bid, "focus_card", dict({"asset": "a" + bid[1:]}, **params), a, b)


def resolve(layouts=(), overlays=(), vocab=VOCAB, data=DATA):
    return _edl.resolve_timeline(synthetic_edl(), beats_of(overlays=overlays, layouts=layouts), vocab, data)


def refused(fn, *args) -> Refusal:
    with pytest.raises(Refusal) as caught:
        fn(*args)
    return caught.value


def test_the_default_backdrop_is_blur_and_the_row_holds_the_entrys_final_frames():
    tl = resolve([card("a1", 4, 9)])
    (beat,) = tl["beats"]
    assert tl["blurs"] == [{"id": "a1", "start_frame": beat["start_frame"], "end_frame": beat["end_frame"]}]
    assert beat["end_frame"] - beat["start_frame"] >= round(DATA["presets"]["focus_card"]["min_duration"] * 30)
    assert resolve([card("a1", 4, 9, backdrop="blur")])["blurs"] == tl["blurs"]


@pytest.mark.parametrize("backdrop", ["none"])
def test_none_gives_no_row_and_the_timeline_has_no_blurs_key(backdrop):
    tl = resolve([card("a1", 4, 9, backdrop=backdrop)])
    assert "blurs" not in tl and len(tl["beats"]) == 1


def test_a_timeline_with_no_backdrop_beat_has_no_blurs_key_and_is_what_it_always_was():
    assert "blurs" not in resolve()
    assert "blurs" not in resolve(overlays=[entry("k1", "keyword", {"text": "Rule one"}, 4, 6)])
    assert "blurs" not in resolve(layouts=[entry("a1", "cutaway", {"asset": "a1"}, 4, 9)])      # a preset with no `backdrop` parameter is never blurred


def test_a_beat_clipped_by_the_next_one_gives_the_clipped_frames_and_a_dropped_one_gives_none():
    tl = resolve([card("a1", 4, 12), card("a2", 8, 14)])
    rows = {b["id"]: b for b in tl["blurs"]}
    beats = {b["id"]: b for b in tl["beats"]}
    assert beats["a1"].get("clipped") and rows["a1"]["end_frame"] == beats["a2"]["start_frame"] == rows["a2"]["start_frame"]
    assert {r["id"]: (r["start_frame"], r["end_frame"]) for r in tl["blurs"]} == {i: (b["start_frame"], b["end_frame"]) for i, b in beats.items()}
    assert all(a["end_frame"] <= b["start_frame"] for a, b in zip(tl["blurs"], tl["blurs"][1:]))      # one beat track: never overlapping
    twin = resolve([card("a1", 4, 9), card("a2", 4, 9)])
    assert twin["dropped"] == ["a1"] and [r["id"] for r in twin["blurs"]] == ["a2"]


def test_a_text_beat_with_a_backdrop_parameter_is_clipped_by_a_picture_and_its_row_follows():
    vocab = copy.deepcopy(VOCAB)
    vocab["presets"]["list"]["params"]["backdrop"] = {"type": "choice", "values": ["blur", "none"], "default": "blur"}
    tl = resolve([entry("a1", "cutaway", {"asset": "a1"}, 8, 10)], [entry("k1", "list", {"items": "One"}, 4, 12)], vocab=vocab)
    beats = {b["id"]: b for b in tl["beats"]}
    assert beats["k1"].get("clipped")
    assert tl["blurs"] == [{"id": "k1", "start_frame": beats["k1"]["start_frame"], "end_frame": beats["k1"]["end_frame"]}]
    assert "blurs" not in resolve([entry("a1", "cutaway", {"asset": "a1"}, 8, 10)], [entry("k1", "list", {"items": "One", "backdrop": "none"}, 4, 12)], vocab=vocab)
    assert "blurs" not in resolve([], [entry("k1", "list", {"items": "One", "backdrop": "none"}, 4, 12)], vocab=vocab)


def test_a_blur_row_with_an_unchecked_data_file_is_refused_only_when_a_beat_blurs():
    broken = copy.deepcopy(DATA)
    del broken["backdrop"]
    assert refused(resolve, [card("a1", 4, 9)], (), VOCAB, broken).code == "bad_backdrop_config"
    assert "blurs" not in resolve([card("a1", 4, 9, backdrop="none")], data=broken)        # a post that blurs nothing never reads the key (S2)
    assert "blurs" not in resolve(data=broken)


def test_the_committed_defaults_are_accepted_and_each_bound_is_refused():
    _edl.check_backdrop_config(DATA)
    blur = DATA["backdrop"]["blur"]
    assert set(blur) == {"sigma", "darken", "saturation"}

    def with_blur(**changes):
        data = copy.deepcopy(DATA)
        data["backdrop"]["blur"].update(changes)
        return data

    for good in ({"sigma": 0}, {"sigma": 1024}, {"darken": 0}, {"darken": 1}, {"saturation": 0}, {"saturation": 2}, {"sigma": 12}):
        _edl.check_backdrop_config(with_blur(**good))
    for key, bad in (("sigma", -0.1), ("sigma", 1024.5), ("darken", -0.01), ("darken", 1.01), ("saturation", -0.5), ("saturation", 2.01),
                     ("sigma", "40"), ("darken", True), ("saturation", None), ("sigma", float("nan")), ("darken", float("inf"))):
        err = refused(_edl.check_backdrop_config, with_blur(**{key: bad}))
        assert (err.code, err.field) == ("bad_backdrop_config", "backdrop.blur.%s" % key), (key, bad)
    for key in blur:
        data = copy.deepcopy(DATA)
        del data["backdrop"]["blur"][key]
        assert refused(_edl.check_backdrop_config, data).field == "backdrop.blur.%s" % key
    for broken in ({}, {"backdrop": []}, {"backdrop": {}}, {"backdrop": {"blur": "x"}}):
        assert refused(_edl.check_backdrop_config, dict(DATA, **broken) if broken else {}).code == "bad_backdrop_config"


def test_the_choice_names_and_the_review_preset_agree():
    assert _edl.BACKDROPS == ("blur", "none")      # a solid colour was removed on 2026-11-28 (P4c)
    spec = VOCAB["presets"]["focus_card"]["params"]["backdrop"]
    assert tuple(spec["values"]) == _edl.BACKDROPS and spec["default"] == "blur"
    assert DATA["backdrop"]["blur"] == {"sigma": 40, "darken": 0.5, "saturation": 0.5}      # the maintainer's pick (P4-5, "Desfoque medio")


def test_the_renders_answer_names_each_blurred_span_and_only_then():
    tl = resolve([card("a1", 4, 9), card("a2", 14, 20)])
    out = _render._blur_summary(tl)
    assert out == {"blurs_drawn": [{"id": r["id"], "start_frame": r["start_frame"], "end_frame": r["end_frame"]} for r in tl["blurs"]]} and len(out["blurs_drawn"]) == 2
    assert _render._blur_summary(resolve()) == {} and _render._blur_summary({"blurs": []}) == {}


def test_the_plan_of_a_render_has_a_blurs_key_only_when_a_beat_blurs():
    edl = synthetic_edl()
    for layouts, expect in (([card("a1", 4, 9)], True), ([card("a1", 4, 9, backdrop="none")], False), ([], False)):
        beats = beats_of(layouts=layouts)
        tl = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
        plan = _render.compose_plan(DATA, edl, tl, {"a1": {"kind": "png", "width": 64, "height": 64}}, {}, "/in/rec")
        assert ("blurs" in plan) is expect
        if expect:
            (row,) = plan["blurs"]
            assert row["params"] == DATA["backdrop"]["blur"] and row["color"] == edl["theme"]["colors"]["bg"]


# ---------------------------------------------------------------- a dry-run render of the kit's post with a card (the whole path, no frame drawn)

@pytest.fixture(scope="module")
def kit_docs(tmp_path_factory):
    return K.hf_documents(tmp_path_factory.mktemp("backdrop"))


def dry_run(kit_docs, tmp_path, monkeypatch, params, layouts=True):
    from test_dropped_beat_picture import a_png, with_slots
    data, edl, beats, vocab = kit_docs
    beats = copy.deepcopy(beats)
    if layouts:
        beats = with_slots(beats, [dict(entry("a1", "focus_card", dict({"asset": "s1"}, **params), 22, 27), beat=7)])
    (tmp_path / "edl.json").write_text(json.dumps(edl))
    (tmp_path / "beats.json").write_text(json.dumps(beats))
    (tmp_path / "s1.png").write_bytes(a_png())
    monkeypatch.setattr(_render, "check_recording", lambda *a, **k: {})
    return _render.render(edl_path=str(tmp_path / "edl.json"), beats_path=str(tmp_path / "beats.json"), src="unused.mp4", out=str(tmp_path / "out"),
                          platform_path=str(K.INSTAGRAM), vocabulary_path=str(K.VOCABULARY), asset_files={"s1": str(tmp_path / "s1.png")} if layouts else {}, asset_sha256s={},
                          ffmpeg="ffmpeg", ffprobe="ffprobe", browser={"path": "chrome"}, dry_run=True, blocks_dir=K.oh_blocks())


def test_a_dry_run_with_a_card_names_the_blurred_span_and_draws_the_stage_and_one_without_is_what_it_was(kit_docs, tmp_path, monkeypatch):
    for name in "abc":
        (tmp_path / name).mkdir()
    with_card = dry_run(kit_docs, tmp_path / "a", monkeypatch, {"stamp": "x"})
    (row,) = with_card["blurs_drawn"]
    assert row["id"] == "a1" and row["start_frame"] < row["end_frame"] <= with_card["out_seconds"] * 30 + 1
    card = next(b for b in with_card["beats_drawn"] if b["id"] == "a1")
    assert (card["preset"], card["block"]) == ("focus_card", "oh:focus-card") and (card["start_frame"], card["end_frame"]) == (row["start_frame"], row["end_frame"])
    graph = with_card["ffmpeg_argv"][with_card["ffmpeg_argv"].index("-filter_complex") + 1]
    assert "[bk_out]" in graph and "gblur=sigma=40:steps=3" in graph
    sharp = dry_run(kit_docs, tmp_path / "b", monkeypatch, {"backdrop": "none"})
    assert "blurs_drawn" not in sharp and "bk_" not in " ".join(sharp["ffmpeg_argv"])
    none = dry_run(kit_docs, tmp_path / "c", monkeypatch, {}, layouts=False)
    assert "blurs_drawn" not in none and "bk_" not in " ".join(none["ffmpeg_argv"])


# ---------------------------------------------------------------- the solid colour was removed (2026-11-28, P4c)

@pytest.mark.parametrize("preset,params", [("focus_card", {"asset": "a1"}), ("title_card", {"text": "Interest"})])
def test_a_beats_file_asking_for_a_solid_backdrop_is_refused_with_the_closed_value_code_and_never_mapped(preset, params):
    vocab_entry = VOCAB["presets"][preset]["params"]["backdrop"]
    assert vocab_entry["values"] == ["blur", "none"] and vocab_entry["default"] == "blur"
    err = refused(_edl.check_beats, beats_of(layouts=[entry("a1", preset, dict(params, backdrop="solid"), 4, 9)]), synthetic_edl(), VOCAB)
    assert err.code == "bad_choice" and err.field.endswith(".params.backdrop")
    for good in ("blur", "none"):
        assert _vocab.check_params(VOCAB, preset, dict(params, backdrop=good))["backdrop"] == good
    assert refused(_vocab.check_params, VOCAB, preset, dict(params, backdrop="solid")).code == "bad_choice"


def test_a_title_card_blurs_by_default_and_a_none_backdrop_gives_no_row():
    tl = resolve([entry("a1", "title_card", {"text": "Interest"}, 4, 9)])
    (beat,) = tl["beats"]
    assert tl["blurs"] == [{"id": "a1", "start_frame": beat["start_frame"], "end_frame": beat["end_frame"]}]
    assert "blurs" not in resolve([entry("a1", "title_card", {"text": "Interest", "backdrop": "none"}, 4, 9)])
