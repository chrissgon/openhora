"""Every beat the timeline leaves out has one reason, and both engines report it (V9b-3f). `resolve_timeline` gives a beat the neighbour pass cuts to zero `overlap`; the
HyperFrames page stage returns `beats_dropped` and `beats_dropped_reasons`, the host copies them into the render answer, and the container schema of `hf-page` accepts them
and refuses a bad row.

Offline: the documents are the kit's fictional post. No ffmpeg, no browser, no docker."""
from __future__ import annotations

import copy

import pytest

import renderer_kit as K
import _blocks
import _docker
import _edl
import _hf_compose as C
from test_dropped_beat_picture import layout, live_shape, with_slots
from test_hf_engine import FakeRun, args_for, run, world, test_blocks, pictures, tied_documents  # noqa: F401  (fixtures)
from _text import Refusal


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("leftout")
    data, edl, beats, vocab = K.hf_documents(folder)
    return data, edl, beats, vocab, folder


def resolve(docs, rows):
    data, edl, beats, vocab, _ = docs
    beats = with_slots(copy.deepcopy(beats), rows)
    return _edl.resolve_timeline(edl, beats, vocab, data)


def test_a_beat_cut_to_zero_by_the_neighbour_pass_is_dropped_as_overlap_and_every_dropped_id_has_one_reason(docs):
    # two pictures that start on the same word: the shorter is cut to nothing by the neighbour pass; the text beats under a picture are `under_picture`
    timeline = resolve(docs, [layout("a1", 7, "s1", 22, 24), layout("a0", 8, "s0", 22, 27)])
    reasons = {r["id"]: r["reason"] for r in timeline["dropped_reasons"]}
    assert reasons.get("a1") == "overlap"
    assert sorted(reasons) == sorted(timeline["dropped"]) and len(timeline["dropped_reasons"]) == len(timeline["dropped"])
    assert set(reasons.values()) <= {"overlap", "under_picture"}


def test_the_live_shape_has_a_reason_for_every_dropped_beat(docs):
    data, edl, beats, vocab = live_shape(docs)
    timeline = _edl.resolve_timeline(edl, with_slots(beats, beats["layouts"] + [layout("a4", 8, "s4", 22, 31)]), vocab, data)
    assert "a3" in timeline["dropped"]
    assert sorted(r["id"] for r in timeline["dropped_reasons"]) == sorted(timeline["dropped"])
    assert {r["reason"] for r in timeline["dropped_reasons"]} == {"under_picture", "overlap"}


def test_a_timeline_that_drops_nothing_has_no_reason_rows(docs):
    timeline = resolve(docs, [])
    assert timeline["dropped"] == [] and "dropped_reasons" not in timeline


@pytest.fixture(scope="module")
def catalogue():
    return _blocks.load_catalogue()


def test_hf_write_page_returns_the_dropped_beats_and_their_reasons_only_when_there_are_some(docs, catalogue, tmp_path):
    data, edl, beats, vocab, _ = docs
    (tmp_path / "quiet").mkdir()
    (tmp_path / "busy").mkdir()
    quiet = C.write_page(data, edl, beats, vocab, catalogue, str(tmp_path / "quiet"), edl["fps"], {})
    assert "beats_dropped" not in quiet and "beats_dropped_reasons" not in quiet
    rows = with_slots(copy.deepcopy(beats), [layout("a1", 7, "s1", 22, 24), layout("a0", 8, "s0", 22, 27)])
    result = C.write_page(data, edl, rows, vocab, catalogue, str(tmp_path / "busy"), edl["fps"], {"s1": "a" * 64, "s0": "b" * 64})
    assert "a1" in result["beats_dropped"]
    assert {"id": "a1", "reason": "overlap"} in result["beats_dropped_reasons"]
    assert sorted(r["id"] for r in result["beats_dropped_reasons"]) == sorted(result["beats_dropped"])


PAGE_ROW = {"ok": True, "page_sha256": "a" * 64, "vars_sha256": "b" * 64, "clips": 1, "zooms": 0, "duration": 1.0, "fps": 30, "layers": ["cuts"]}


def test_the_container_schema_accepts_the_dropped_beats_and_refuses_a_bad_row():
    schema = _docker.RESULT_SCHEMAS["hf-page"]
    good = _docker.sanitise(dict(PAGE_ROW, beats_dropped=["b1"], beats_dropped_reasons=[{"id": "b1", "reason": "under_picture"}]), schema, "hf-page")
    assert good["beats_dropped"] == ["b1"] and good["beats_dropped_reasons"] == [{"id": "b1", "reason": "under_picture"}]
    for bad in ([{"id": 1, "reason": "overlap"}], "overlap"):
        with pytest.raises(Refusal):
            _docker.sanitise(dict(PAGE_ROW, beats_dropped_reasons=bad), schema, "hf-page")


def test_the_hf_host_copies_the_dropped_beats_into_the_render_answer(world, monkeypatch, test_blocks, pictures):
    tied_documents(world)
    extra = {"beats_dropped": ["b1", "a1"], "beats_dropped_reasons": [{"id": "b1", "reason": "under_picture"}, {"id": "a1", "reason": "overlap"}]}
    result, _ = run(world, monkeypatch, "--asset", "s0=%s" % pictures[0], base_only=False, fake=FakeRun(page_extra=extra))
    assert result["beats_dropped"] == ["b1", "a1"] and result["beats_dropped_reasons"] == extra["beats_dropped_reasons"]
    result, _ = run(world, monkeypatch, "--asset", "s0=%s" % pictures[0], base_only=False)
    assert "beats_dropped" not in result and "beats_dropped_reasons" not in result
